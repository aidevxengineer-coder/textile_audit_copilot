from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from langchain_ollama import ChatOllama

from app.config import get_settings


class AIProviderTimeoutError(RuntimeError):
    def __init__(self, provider: str, operation: str, timeout_seconds: float) -> None:
        timeout_label = f"{timeout_seconds:g}"
        super().__init__(f"{provider} '{operation}' call did not respond within {timeout_label}s.")


# Backwards-compatible import for any integrations that still use the old name.
OllamaTimeoutError = AIProviderTimeoutError


class VisionProviderError(RuntimeError):
    """Raised only after every configured vision provider has failed."""


@dataclass(frozen=True)
class VisionInvocation:
    content: str
    provider: str
    model: str


def _load_groq_chat() -> type:
    try:
        from langchain_groq import ChatGroq
    except ImportError as exc:
        raise RuntimeError("Install langchain-groq to use Groq.") from exc
    return ChatGroq


def _response_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("text"):
                parts.append(str(block["text"]))
        if parts:
            return "\n".join(parts)
    return str(content)


def _ollama_vision_messages(messages: list[Any]) -> list[Any]:
    """Convert OpenAI-style image blocks to ChatOllama's accepted shape.

    Groq expects ``image_url={url: ...}``, while ChatOllama accepts the URL as
    a direct string. Keeping this adapter at the provider boundary allows the
    graph to use one canonical multimodal message format.
    """

    adapted: list[Any] = []
    for message in messages:
        content = getattr(message, "content", None)
        if not isinstance(content, list):
            adapted.append(message)
            continue
        blocks: list[Any] = []
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "image_url":
                blocks.append(block)
                continue
            image_url = block.get("image_url")
            if isinstance(image_url, dict) and image_url.get("url"):
                blocks.append({**block, "image_url": image_url["url"]})
            else:
                blocks.append(block)
        if hasattr(message, "model_copy"):
            adapted.append(message.model_copy(update={"content": blocks}))
        else:
            adapted.append(message)
    return adapted


class OllamaService:
    def __init__(self, settings: Any | None = None) -> None:
        settings = settings or get_settings()
        self.request_timeout_seconds = settings.ollama_request_timeout_seconds
        self.provider_name = settings.ai_provider.strip().title()
        if settings.ai_provider.lower() == "groq":
            if not settings.groq_api_key:
                raise RuntimeError("AI_PROVIDER=groq requires GROQ_API_KEY.")
            ChatGroq = _load_groq_chat()
            self.text_llm = ChatGroq(
                model=settings.groq_text_model,
                api_key=settings.groq_api_key,
                temperature=0.1,
                timeout=settings.ollama_request_timeout_seconds,
            )
        else:
            self.text_llm = ChatOllama(
                model=settings.ollama_text_model,
                base_url=settings.ollama_base_url,
                temperature=0.1,
            )

        self.vision_request_timeout_seconds = settings.vision_request_timeout_seconds
        self.vision_max_images = max(1, min(int(settings.vision_max_images), 5))
        self._vision_clients: list[tuple[str, str, Any]] = []
        configured_providers = [settings.vision_provider, settings.vision_fallback_provider]
        for raw_provider in configured_providers:
            provider = str(raw_provider or "none").strip().lower()
            if provider == "none" or any(item[0] == provider for item in self._vision_clients):
                continue
            if provider == "ollama":
                self._vision_clients.append(
                    (
                        provider,
                        settings.ollama_vision_model,
                        ChatOllama(
                            model=settings.ollama_vision_model,
                            base_url=settings.ollama_base_url,
                            temperature=0.1,
                        ),
                    )
                )
            elif provider == "groq":
                # A missing Groq key disables only this vision option. The
                # local Ollama path remains available and image uploads do not
                # break text chat initialization.
                if not settings.groq_api_key:
                    continue
                ChatGroq = _load_groq_chat()
                self._vision_clients.append(
                    (
                        provider,
                        settings.groq_vision_model,
                        ChatGroq(
                            model=settings.groq_vision_model,
                            api_key=settings.groq_api_key,
                            temperature=0.1,
                            timeout=settings.vision_request_timeout_seconds,
                        ),
                    )
                )
            else:
                raise RuntimeError(f"Unsupported vision provider: {provider}.")

        if not self._vision_clients:
            raise RuntimeError("No usable vision provider is configured.")

    @property
    def vision_provider_chain(self) -> list[str]:
        return [provider for provider, _model, _client in self._vision_clients]

    async def _with_timeout(
        self,
        operation: str,
        coro: Any,
        *,
        provider_name: str | None = None,
        timeout_seconds: float | None = None,
    ) -> Any:
        timeout = timeout_seconds or self.request_timeout_seconds
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except TimeoutError as exc:
            raise AIProviderTimeoutError(provider_name or self.provider_name, operation, timeout) from exc

    async def invoke_text(self, messages: list[Any]) -> str:
        response = await self._with_timeout("invoke_text", self.text_llm.ainvoke(messages))
        return _response_text(response)

    async def invoke_structured(self, schema: type, messages: list[Any]) -> Any:
        structured_llm = self.text_llm.with_structured_output(schema)
        return await self._with_timeout("invoke_structured", structured_llm.ainvoke(messages))

    async def stream_text(self, messages: list[Any]) -> AsyncGenerator[str, None]:
        stream = self.text_llm.astream(messages)
        while True:
            try:
                chunk = await asyncio.wait_for(stream.__anext__(), timeout=self.request_timeout_seconds)
            except StopAsyncIteration:
                break
            except TimeoutError as exc:
                raise AIProviderTimeoutError(self.provider_name, "stream_text", self.request_timeout_seconds) from exc
            if chunk.content:
                yield str(chunk.content)

    async def invoke_vision_with_metadata(self, messages: list[Any]) -> VisionInvocation:
        failures: list[str] = []
        for provider, model, client in self._vision_clients:
            provider_messages = _ollama_vision_messages(messages) if provider == "ollama" else messages
            try:
                response = await self._with_timeout(
                    "invoke_vision",
                    client.ainvoke(provider_messages),
                    provider_name=provider.title(),
                    timeout_seconds=self.vision_request_timeout_seconds,
                )
                content = _response_text(response).strip()
                if not content:
                    raise RuntimeError("Vision provider returned an empty response.")
                return VisionInvocation(content=content, provider=provider, model=model)
            except Exception as exc:
                failures.append(f"{provider}: {str(exc)[:180]}")

        detail = "; ".join(failures) or "no provider attempts were available"
        raise VisionProviderError(f"Image analysis failed for every configured provider ({detail}).")

    async def invoke_vision(self, messages: list[Any]) -> str:
        result = await self.invoke_vision_with_metadata(messages)
        return result.content
