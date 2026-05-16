"""End-to-end tests for read-only and dry-run safety modes on real tool functions."""

from __future__ import annotations

import json

import pytest

from mailchimp_mcp_server import server


class TestReadOnlyMode:
    def test_write_tool_blocked(self, monkeypatch: pytest.MonkeyPatch, mock_mc_request) -> None:
        monkeypatch.setattr(server, "READ_ONLY", True)
        calls = mock_mc_request({"should": "not-be-called"})

        result = server.add_member(list_id="abc", email_address="a@b.com")
        payload = json.loads(result)

        assert "error" in payload
        assert "read-only" in payload["error"].lower()
        assert calls == [], "mc_request must not be invoked when read-only blocks the call"

    def test_delete_tool_blocked(self, monkeypatch: pytest.MonkeyPatch, mock_mc_request) -> None:
        monkeypatch.setattr(server, "READ_ONLY", True)
        calls = mock_mc_request({"should": "not-be-called"})

        result = server.delete_campaign(campaign_id="cam_123")
        payload = json.loads(result)

        assert "error" in payload
        assert calls == []

    def test_read_tool_not_blocked(self, monkeypatch: pytest.MonkeyPatch, mock_mc_request) -> None:
        monkeypatch.setattr(server, "READ_ONLY", True)
        calls = mock_mc_request({"health_check": "Everything's Chimpy!"})

        result = server.ping()
        payload = json.loads(result)

        assert payload["health_check"] == "Everything's Chimpy!"
        assert len(calls) == 1, "read tools must execute even in read-only mode"


class TestDryRunMode:
    def test_write_tool_returns_preview(self, monkeypatch: pytest.MonkeyPatch, mock_mc_request) -> None:
        monkeypatch.setattr(server, "DRY_RUN", True)
        calls = mock_mc_request({"should": "not-be-called"})

        result = server.add_member(
            list_id="abc",
            email_address="a@b.com",
            first_name="Alice",
        )
        payload = json.loads(result)

        assert payload["dry_run"] is True
        assert payload["action"] == "add member"
        assert payload["email_address"] == "a@b.com"
        assert payload["list_id"] == "abc"
        assert calls == [], "mc_request must not be invoked in dry-run mode"

    def test_dry_run_records_action_metadata(self, monkeypatch: pytest.MonkeyPatch, mock_mc_request) -> None:
        monkeypatch.setattr(server, "DRY_RUN", True)
        mock_mc_request({})

        result = server.send_campaign(campaign_id="cam_xyz")
        payload = json.loads(result)

        assert payload["dry_run"] is True
        assert payload["campaign_id"] == "cam_xyz"


class TestNormalMode:
    def test_write_tool_executes_in_normal_mode(self, mock_mc_request) -> None:
        calls = mock_mc_request(
            {
                "id": "md5hash",
                "email_address": "a@b.com",
                "status": "subscribed",
                "full_name": "Alice",
            }
        )

        result = server.add_member(list_id="abc", email_address="a@b.com", first_name="Alice")
        payload = json.loads(result)

        assert payload["email_address"] == "a@b.com"
        assert payload["status"] == "subscribed"
        assert len(calls) == 1
        assert calls[0]["method"] == "POST"
        assert calls[0]["endpoint"] == "/lists/abc/members"
        assert calls[0]["body"]["email_address"] == "a@b.com"
        assert calls[0]["body"]["merge_fields"] == {"FNAME": "Alice"}
