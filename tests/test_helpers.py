"""Tests for the internal helpers: `_guard_write` and `mc_request`."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from mailchimp_mcp_server import server


class TestGuardWrite:
    def test_returns_none_in_normal_mode(self) -> None:
        assert server._guard_write(action="test") is None

    def test_blocks_in_read_only_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(server, "READ_ONLY", True)
        result = server._guard_write(action="delete", list_id="abc")
        payload = json.loads(result)
        assert "error" in payload
        assert "read-only" in payload["error"].lower()

    def test_returns_preview_in_dry_run_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(server, "DRY_RUN", True)
        result = server._guard_write(action="delete", list_id="abc", email="a@b.com")
        payload = json.loads(result)
        assert payload["dry_run"] is True
        assert payload["action"] == "delete"
        assert payload["list_id"] == "abc"
        assert payload["email"] == "a@b.com"

    def test_read_only_takes_precedence_over_dry_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(server, "READ_ONLY", True)
        monkeypatch.setattr(server, "DRY_RUN", True)
        result = server._guard_write(action="test")
        payload = json.loads(result)
        assert "error" in payload


class TestMcRequest:
    def test_missing_api_key_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(server, "MAILCHIMP_API_KEY", "")
        result = server.mc_request("/ping")
        assert "error" in result
        assert "MAILCHIMP_API_KEY" in result["error"]

    def test_successful_response_returns_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {"health_check": "Everything's Chimpy!"}
        with patch.object(requests, "request", return_value=mock_resp) as mock_req:
            result = server.mc_request("/ping")
        assert result == {"health_check": "Everything's Chimpy!"}
        called_url = mock_req.call_args.args[1]
        assert called_url == "https://us1.api.mailchimp.com/3.0/ping"

    def test_204_returns_success_status(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_resp.ok = True
        with patch.object(requests, "request", return_value=mock_resp):
            result = server.mc_request("/lists/abc/members/xyz", method="DELETE")
        assert result == {"status": "success"}

    def test_4xx_with_json_body_parses_error(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.ok = False
        mock_resp.json.return_value = {"title": "Resource Not Found", "detail": "List abc does not exist."}
        with patch.object(requests, "request", return_value=mock_resp):
            result = server.mc_request("/lists/abc")
        assert result["error"] == "Resource Not Found"
        assert "does not exist" in result["detail"]
        assert result["status"] == 404

    def test_4xx_with_invalid_json_falls_back_to_text(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.ok = False
        mock_resp.json.side_effect = ValueError("not json")
        mock_resp.text = "Internal Server Error"
        with patch.object(requests, "request", return_value=mock_resp):
            result = server.mc_request("/lists")
        assert "HTTP 500" in result["error"]
        assert "Internal Server Error" in result["detail"]

    def test_timeout_returns_error(self) -> None:
        with patch.object(requests, "request", side_effect=requests.exceptions.Timeout):
            result = server.mc_request("/ping")
        assert "timed out" in result["error"].lower()
        assert result["endpoint"] == "/ping"

    def test_connection_error_returns_error(self) -> None:
        with patch.object(requests, "request", side_effect=requests.exceptions.ConnectionError):
            result = server.mc_request("/ping")
        assert "connect" in result["error"].lower()
        assert result["endpoint"] == "/ping"

    def test_post_with_body_passes_json(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {"id": "abc123"}
        with patch.object(requests, "request", return_value=mock_resp) as mock_req:
            server.mc_request("/lists/abc/members", body={"email_address": "a@b.com"}, method="POST")
        args, kwargs = mock_req.call_args
        assert args[0] == "POST"
        assert args[1].endswith("/lists/abc/members")
        assert kwargs["json"] == {"email_address": "a@b.com"}


class TestMcRequestAccounts:
    def test_named_account_routes_to_its_dc_and_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            server,
            "MAILCHIMP_ACCOUNTS",
            {"foo": {"api_key": "fookey-us9", "dc": "us9", "base_url": "https://us9.api.mailchimp.com/3.0", "read_only": False, "dry_run": False}},
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {"ok": True}
        with patch.object(requests, "request", return_value=mock_resp) as mock_req:
            server.mc_request("/lists", account="foo")
        called_url = mock_req.call_args.args[1]
        assert called_url == "https://us9.api.mailchimp.com/3.0/lists"
        assert mock_req.call_args.kwargs["auth"] == ("anystring", "fookey-us9")

    def test_default_account_unaffected_by_registry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            server,
            "MAILCHIMP_ACCOUNTS",
            {"foo": {"api_key": "fookey-us9", "dc": "us9", "base_url": "https://us9.api.mailchimp.com/3.0", "read_only": False, "dry_run": False}},
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {"ok": True}
        with patch.object(requests, "request", return_value=mock_resp) as mock_req:
            server.mc_request("/lists")
        assert mock_req.call_args.args[1] == "https://us1.api.mailchimp.com/3.0/lists"
        assert mock_req.call_args.kwargs["auth"] == ("anystring", "test-key-us1")

    def test_unknown_account_returns_error_without_network(self) -> None:
        with patch.object(requests, "request") as mock_req:
            result = server.mc_request("/lists", account="nope")
        assert "error" in result
        assert "nope" in result["error"]
        mock_req.assert_not_called()
