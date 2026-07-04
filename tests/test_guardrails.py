"""Tests for the runtime-security guardrails: risk metadata, MCP annotations,
structured audit events, and argument-contract validation."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import requests

from mailchimp_mcp_server import server


def _events(err: str) -> list[dict]:
    return [json.loads(line) for line in err.splitlines() if line.strip().startswith("{")]


class TestRiskMetadata:
    def test_describe_tools_classifies_and_counts(self) -> None:
        payload = json.loads(server.describe_tools())
        summary = payload["summary"]
        assert summary["total"] == len(server.TOOL_RISK)
        assert summary["read"] + summary["write"] + summary["destructive"] == summary["total"]
        # every delete_* tool is destructive
        assert summary["destructive"] >= sum(1 for n in server.TOOL_RISK if n.startswith("delete_"))

        by_name = {t["name"]: t for t in payload["tools"]}
        assert by_name["delete_campaign"]["risk"] == "destructive"
        assert by_name["delete_campaign"]["destructive"] is True
        assert by_name["delete_campaign"]["idempotent"] is True
        assert by_name["send_campaign"]["risk"] == "destructive"
        assert by_name["send_campaign"]["idempotent"] is False
        assert by_name["list_campaigns"]["risk"] == "read"
        assert by_name["list_campaigns"]["read_only"] is True
        assert by_name["upsert_member"]["risk"] == "write"
        assert by_name["upsert_member"]["idempotent"] is True

    def test_mcp_annotations_expose_risk(self) -> None:
        tm = server.mcp._tool_manager
        assert tm.get_tool("delete_store").annotations.destructiveHint is True
        assert tm.get_tool("delete_store").annotations.idempotentHint is True
        assert tm.get_tool("list_audiences").annotations.readOnlyHint is True
        assert tm.get_tool("list_audiences").annotations.destructiveHint is False
        assert tm.get_tool("create_campaign").annotations.readOnlyHint is False
        assert tm.get_tool("create_campaign").annotations.destructiveHint is False


class TestArgumentValidation:
    def test_rejects_out_of_range_count(self) -> None:
        out = server.mc_request("/lists", params={"count": 5000})
        assert "error" in out and "1 and 1000" in out["error"]

    def test_rejects_empty_path_parameter(self) -> None:
        out = server.mc_request("/lists//members")
        assert "error" in out and "required path parameter" in out["error"]

    def test_allows_account_root(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {"account_name": "Acme"}
        with patch.object(requests.Session, "request", return_value=mock_resp):
            out = server.mc_request("/")
        assert out == {"account_name": "Acme"}


class TestAuditLog:
    def test_off_by_default_is_silent(self, capsys) -> None:
        # AUDIT_LOG defaults off; a blocked write must not emit anything.
        server._emit_audit("delete_campaign", "blocked_read_only", account="default")
        assert capsys.readouterr().err == ""

    def test_blocked_write_is_audited(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(server, "AUDIT_LOG", True)
        monkeypatch.setattr(server, "READ_ONLY", True)
        server.delete_campaign(campaign_id="c1")
        events = _events(capsys.readouterr().err)
        match = [e for e in events if e["tool"] == "delete_campaign"]
        assert match and match[0]["outcome"] == "blocked_read_only"
        assert match[0]["risk"] == "destructive"
        assert match[0]["destructive"] is True

    def test_dry_run_preview_and_event_carry_risk(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(server, "AUDIT_LOG", True)
        monkeypatch.setattr(server, "DRY_RUN", True)
        payload = json.loads(server.delete_store(store_id="s1"))
        assert payload["dry_run"] is True
        assert payload["risk"] == "destructive"
        assert payload["destructive"] is True
        events = _events(capsys.readouterr().err)
        assert any(e["tool"] == "delete_store" and e["outcome"] == "dry_run" for e in events)

    def test_executed_read_is_audited(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(server, "AUDIT_LOG", True)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {"lists": [], "total_items": 0}
        with patch.object(requests.Session, "request", return_value=mock_resp):
            server.list_audiences()
        events = _events(capsys.readouterr().err)
        match = [e for e in events if e["tool"] == "list_audiences"]
        assert match and match[0]["outcome"] == "executed"
        assert match[0]["risk"] == "read"
        assert match[0]["method"] == "GET"

    def test_audit_redacts_file_data(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(server, "AUDIT_LOG", True)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {"id": 1}
        with patch.object(requests.Session, "request", return_value=mock_resp):
            server.upload_file(name="a.png", file_data="SUPERSECRETBASE64")
        err = capsys.readouterr().err
        assert "SUPERSECRETBASE64" not in err
        assert "<redacted>" in err
