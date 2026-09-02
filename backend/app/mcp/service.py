from __future__ import annotations

import asyncio
import json
import os
import shlex
import sys
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.config import get_settings
from app.mcp.web_sources import is_authoritative_url, normalize_authoritative_results


class MCPIntegrationError(RuntimeError):
    pass


class MCPService:
    """Official MCP client used by the API and LangGraph runtime.

    Local stdio servers are the secure default. A deployment may replace each
    command with any protocol-compatible open-source MCP server.
    """

    def __init__(self) -> None:
        self.settings = get_settings()

    def _default_command(self, server: str) -> str:
        script = Path(__file__).with_name("local_server.py").resolve()
        return f'"{sys.executable}" "{script}" {server}'

    def _command(self, server: str) -> str:
        if self.settings.use_dummy_communications and server in {"email", "whatsapp"}:
            return self._default_command(server)
        configured = getattr(self.settings, f"{server}_mcp_command", None)
        return configured or self._default_command(server)

    @staticmethod
    def _normalize_result(result: Any) -> Any:
        structured = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None)
        if structured is not None:
            return structured
        output: list[Any] = []
        for item in getattr(result, "content", []) or []:
            text = getattr(item, "text", None)
            if text is None:
                output.append(str(item))
                continue
            try:
                output.append(json.loads(text))
            except (TypeError, json.JSONDecodeError):
                output.append(text)
        return output[0] if len(output) == 1 else output

    @staticmethod
    def _exception_detail(exc: BaseException) -> str:
        nested = getattr(exc, "exceptions", None)
        if nested:
            details = [MCPService._exception_detail(item) for item in nested]
            return "; ".join(detail for detail in details if detail)
        return str(exc) or type(exc).__name__

    async def _call_tool(self, server: str, preferred_names: list[str], arguments: dict[str, Any]) -> Any:
        parts = shlex.split(self._command(server), posix=False)
        if not parts:
            raise MCPIntegrationError(f"No command configured for {server} MCP.")
        child_env = os.environ.copy()
        params = StdioServerParameters(
            command=parts[0].strip('"'),
            args=[part.strip('"') for part in parts[1:]],
            env=child_env,
        )
        try:
            async with AsyncExitStack() as stack:
                read, write = await stack.enter_async_context(stdio_client(params))
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                listed = await session.list_tools()
                names = {tool.name for tool in listed.tools}
                tool_name = next((name for name in preferred_names if name in names), None)
                if not tool_name:
                    raise MCPIntegrationError(
                        f"{server} MCP does not expose any of: {', '.join(preferred_names)}"
                    )
                result = await session.call_tool(tool_name, arguments=arguments)
                if getattr(result, "isError", False):
                    raise MCPIntegrationError(str(self._normalize_result(result)))
                return self._normalize_result(result)
        except MCPIntegrationError:
            raise
        except Exception as exc:
            raise MCPIntegrationError(f"{server} MCP failed: {self._exception_detail(exc)}") from exc

    async def health(self) -> dict[str, Any]:
        results = {}
        for server in ("filesystem", "documents", "web_search", "email", "whatsapp", "utilities"):
            try:
                results[server] = await self._call_tool(server, ["health"], {})
            except MCPIntegrationError as exc:
                results[server] = {"ok": False, "error": str(exc)}
        return results

    async def _verify_web_result(
        self,
        client: httpx.AsyncClient,
        row: dict[str, Any],
    ) -> dict[str, Any]:
        """Check that an official result still resolves without downloading it."""

        checked = dict(row)
        checked["checked_at"] = datetime.now(timezone.utc).isoformat()
        try:
            response = await client.head(row["url"])
            final_url = str(response.url).split("#", 1)[0]
            if response.status_code < 400 and is_authoritative_url(final_url):
                checked["url"] = final_url
                checked["source_url"] = final_url
                checked["content_verified"] = True
                checked["http_status"] = response.status_code
                return checked
            checked["http_status"] = response.status_code
        except httpx.HTTPError as exc:
            checked["verification_error"] = type(exc).__name__
        return checked

    async def _search_authoritative_sources(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        if not self.settings.enable_web_search_mcp:
            return []
        # Ask the search provider for primary sources up front instead of doing
        # a broad request and a slower second retry.  Post-filtering below is
        # still mandatory because search engines may ignore query operators.
        official_scope = (
            "site:ilo.org OR site:ifc.org OR site:oecd.org OR site:wrapcompliance.org OR "
            "site:ethicaltrade.org OR site:amfori.org OR site:oeko-tex.com OR site:zdhc.org OR "
            "site:cbp.gov OR site:dhs.gov OR site:punjab.gov.pk"
        )
        scoped_query = f"{query[:430]} ({official_scope})"
        result = await self._call_tool(
            "web_search",
            ["web_search"],
            {"query": scoped_query, "limit": max(1, min(limit * 3, 10))},
        )
        rows = normalize_authoritative_results(result, limit=limit)
        if not rows:
            return []
        # Link checks happen concurrently and stay inside the public method's
        # end-to-end deadline. An official host that rejects HEAD requests is
        # retained but remains marked as not content-verified.
        timeout = httpx.Timeout(1.5, connect=1.0)
        headers = {"User-Agent": "AuditReady-AI/1.0 (official-source link verification)"}
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            return list(await asyncio.gather(*(self._verify_web_result(client, row) for row in rows)))

    async def search_authoritative_sources(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        """Search official sources within one bounded interactive-time budget.

        A timeout is surfaced to the graph as an MCP failure. The graph logs
        it and takes its safe-response branch; this method never manufactures
        a result to make a timed-out search appear successful.
        """

        timeout_seconds = max(0.1, float(self.settings.web_search_timeout_seconds))
        try:
            return await asyncio.wait_for(
                self._search_authoritative_sources(query, limit=limit),
                timeout=timeout_seconds,
            )
        except TimeoutError as exc:
            raise MCPIntegrationError(
                f"web_search MCP exceeded its {timeout_seconds:g}s interactive deadline"
            ) from exc

    async def search_recent_standard_updates(self, query: str) -> list[dict[str, Any]]:
        """Backward-compatible alias for callers that request current guidance."""

        return await self.search_authoritative_sources(query)

    async def export_report_via_filesystem(self, *, report_bytes: bytes, destination_path: str) -> dict[str, Any]:
        import base64
        return await self._call_tool("filesystem", ["write_file"], {
            "path": destination_path,
            "content_base64": base64.b64encode(report_bytes).decode(),
        })

    async def generate_document(self, *, format: str, title: str, content: str, filename: str) -> Any:
        return await self._call_tool("documents", ["generate_document"], {
            "format": format, "title": title, "content": content, "filename": filename,
        })

    async def draft_email(self, *, recipient: str, subject: str, body: str, attachments: list[str] | None = None) -> Any:
        return await self._call_tool("email", ["draft_email"], {
            "recipient": recipient, "subject": subject, "body": body, "attachments": attachments or [],
        })

    async def send_email_report(self, *, recipient: str, subject: str, body: str, report_path: str) -> Any:
        return await self._call_tool("email", ["send_email"], {
            "recipient": recipient, "subject": subject, "body": body, "attachments": [report_path],
        })

    async def list_email_attachments(self, *, limit: int = 10) -> Any:
        return await self._call_tool("email", ["list_messages"], {"limit": limit})

    async def download_email_attachment(self, *, message_id: str, attachment_name: str) -> Any:
        return await self._call_tool("email", ["download_attachment"], {
            "message_id": message_id, "attachment_name": attachment_name,
        })

    async def invoke_utility(self, tool_name: str, query: str) -> Any:
        return await self._call_tool("utilities", [tool_name], {"query": query})

    async def list_whatsapp_messages(self, *, chat_id: str | None = None, limit: int = 20) -> Any:
        return await self._call_tool("whatsapp", ["list_messages"], {"chat_id": chat_id, "limit": limit})

    async def send_whatsapp_message(self, *, recipient: str, body: str) -> Any:
        return await self._call_tool("whatsapp", ["send_message"], {"recipient": recipient, "body": body})
