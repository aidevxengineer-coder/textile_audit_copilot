import asyncio

from app.mcp.service import MCPService


def test_all_six_local_mcp_servers_are_protocol_operational() -> None:
    status = asyncio.run(MCPService().health())
    assert set(status) == {"filesystem", "documents", "web_search", "email", "whatsapp", "utilities"}
    assert all(value.get("ok") is True for value in status.values())


def test_document_generation_mcp(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MCP_OUTPUT_DIR", str(tmp_path))
    service = MCPService()
    result = asyncio.run(service.generate_document(format="csv", title="Example", content="name,value\na,1", filename="example"))
    assert result["format"] == "csv"
    assert tmp_path.joinpath("example.csv").exists()


def test_dummy_gmail_and_whatsapp_mcp(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MCP_OUTPUT_DIR", str(tmp_path))
    service = MCPService()
    gmail = asyncio.run(service.list_email_attachments(limit=1))
    whatsapp = asyncio.run(service.list_whatsapp_messages(limit=1))
    sent = asyncio.run(service.send_whatsapp_message(recipient="+92-300-1234567", body="Audit reminder"))
    assert gmail["dummy"] is True and gmail["messages"][0]["id"] == "gmail-001"
    assert whatsapp["dummy"] is True and whatsapp["messages"][0]["id"] == "wa-001"
    assert sent["status"] == "simulated"
    assert tmp_path.joinpath("dummy-whatsapp-outbox.jsonl").exists()
