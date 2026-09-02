from __future__ import annotations

import asyncio
import base64
import io
from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import HumanMessage
from PIL import Image

from app.graph.node_utils import image_to_data_url
from app.graph.nodes.query_rewriter import query_rewriter
from app.services import ollama_service as service_module
from app.services.ollama_service import OllamaService, VisionInvocation


def _settings(**overrides):
    values = {
        "ai_provider": "ollama",
        "ollama_base_url": "http://127.0.0.1:11434",
        "ollama_text_model": "text-local",
        "ollama_vision_model": "vision-local",
        "ollama_request_timeout_seconds": 2,
        "groq_api_key": "test-key",
        "groq_text_model": "text-hosted",
        "groq_vision_model": "vision-hosted",
        "vision_provider": "ollama",
        "vision_fallback_provider": "groq",
        "vision_request_timeout_seconds": 1,
        "vision_max_images": 3,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _Response:
    def __init__(self, content: str) -> None:
        self.content = content


def test_ollama_vision_is_primary_and_groq_is_fallback(monkeypatch) -> None:
    attempts: list[tuple[str, list]] = []

    class FakeOllama:
        def __init__(self, *, model: str, **_kwargs) -> None:
            self.model = model

        async def ainvoke(self, messages):
            attempts.append((self.model, messages))
            if self.model == "vision-local":
                raise RuntimeError("local model is not pulled")
            return _Response("text")

    class FakeGroq:
        def __init__(self, *, model: str, **_kwargs) -> None:
            self.model = model

        async def ainvoke(self, messages):
            attempts.append((self.model, messages))
            return _Response("Visible blocked aisle near a marked exit.")

    monkeypatch.setattr(service_module, "ChatOllama", FakeOllama)
    monkeypatch.setattr(service_module, "_load_groq_chat", lambda: FakeGroq)
    service = OllamaService(settings=_settings())

    messages = [
        HumanMessage(
            content=[
                {"type": "text", "text": "What is visible?"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ]
        )
    ]
    result = asyncio.run(service.invoke_vision_with_metadata(messages))

    assert service.vision_provider_chain == ["ollama", "groq"]
    assert result.provider == "groq"
    assert result.model == "vision-hosted"
    assert "blocked aisle" in result.content
    local_image_block = attempts[0][1][0].content[1]
    hosted_image_block = attempts[1][1][0].content[1]
    assert local_image_block["image_url"] == "data:image/png;base64,AAAA"
    assert hosted_image_block["image_url"] == {"url": "data:image/png;base64,AAAA"}


def test_ollama_vision_can_run_without_a_groq_key(monkeypatch) -> None:
    class FakeOllama:
        def __init__(self, *, model: str, **_kwargs) -> None:
            self.model = model

        async def ainvoke(self, _messages):
            return _Response("PPE is visible; exit signage is not visible.")

    monkeypatch.setattr(service_module, "ChatOllama", FakeOllama)
    service = OllamaService(settings=_settings(groq_api_key=None))
    result = asyncio.run(service.invoke_vision_with_metadata([HumanMessage(content="inspect")]))

    assert service.vision_provider_chain == ["ollama"]
    assert result.provider == "ollama"
    assert "PPE" in result.content


def test_image_payload_is_resized_for_vision() -> None:
    original = Image.new("RGB", (3200, 1800), color=(120, 80, 40))
    source = io.BytesIO()
    original.save(source, format="JPEG", quality=95)

    data_url = image_to_data_url("image/jpeg", source.getvalue(), max_edge=800)
    encoded = data_url.split(",", 1)[1]
    prepared = Image.open(io.BytesIO(base64.b64decode(encoded)))

    assert max(prepared.size) <= 800
    assert len(base64.b64decode(encoded)) < len(source.getvalue())


def test_query_rewriter_passes_multiple_labeled_images(tmp_path: Path) -> None:
    image_paths: list[Path] = []
    for index in range(3):
        path = tmp_path / f"evidence-{index}.png"
        image = Image.new("RGB", (24, 24), color=(index * 30, 10, 20))
        image.save(path, format="PNG")
        image_paths.append(path)

    class FakeVisionService:
        vision_max_images = 2

        def __init__(self) -> None:
            self.messages = None

        async def invoke_vision_with_metadata(self, messages):
            self.messages = messages
            return VisionInvocation(
                content="Image 1 shows a clear aisle. Image 2 shows PPE in use.",
                provider="ollama",
                model="vision-local",
            )

        async def invoke_text(self, _messages):
            return "Assess visible aisle access and PPE evidence against the applicable audit criteria."

    class FakeEmitter:
        def __init__(self) -> None:
            self.events: list[tuple[str, str, str | None]] = []

        async def stage(self, node_name, status, detail=None):
            self.events.append((node_name, status, detail))

    vision_service = FakeVisionService()
    emitter = FakeEmitter()
    runtime = SimpleNamespace(
        ollama_service=vision_service,
        pipeline_log_service=None,
        emitter=emitter,
        run_id="run-1",
    )
    state = {
        "original_query": "Are the workers using PPE and are aisles clear?",
        "attachment_contexts": [
            {
                "file_name": path.name,
                "mime_type": "image/png",
                "stored_path": str(path),
                "document_type": "safety",
                "evidence_summary": f"Image evidence uploaded: {path.name}.",
            }
            for path in image_paths
        ],
        "conversation_history": [],
        "retry_count": 0,
    }

    result = asyncio.run(
        query_rewriter(state, {"configurable": {"runtime": runtime}})
    )

    assert result["image_analysis"].startswith("Image 1 shows")
    human_content = vision_service.messages[1].content
    assert sum(block.get("type") == "image_url" for block in human_content) == 2
    assert any("evidence-0.png" in block.get("text", "") for block in human_content)
    assert any("evidence-1.png" in block.get("text", "") for block in human_content)
    assert not any("evidence-2.png" in block.get("text", "") for block in human_content)
    assert any("Ollama (vision-local)" in (detail or "") for _node, _status, detail in emitter.events)

