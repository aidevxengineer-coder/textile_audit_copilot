import asyncio

from app.mcp.service import MCPService


def test_email_send_uses_dummy_outbox_without_smtp(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MCP_OUTPUT_DIR", str(tmp_path))
    service = MCPService()
    service.settings.smtp_host = None
    service.settings.smtp_username = None
    service.settings.smtp_password = None
    service.settings.smtp_from = None
    report = tmp_path / "report.pdf"
    report.write_bytes(b"dummy report")
    result = asyncio.run(service.send_email_report(recipient="person@example.com", subject="Report", body="Attached", report_path=str(report)))
    assert result["status"] == "simulated"
    assert result["dummy"] is True
    assert tmp_path.joinpath("dummy-gmail-outbox.jsonl").exists()
