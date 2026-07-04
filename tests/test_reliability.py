"""Tests for the reliability-hardening pass: error propagation on writes, JSON-argument
guards, path-traversal rejection, PII redaction in the audit log, and batch bounds."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import requests

from mailchimp_mcp_server import server


def _events(err: str) -> list[dict]:
    return [json.loads(line) for line in err.splitlines() if line.strip().startswith("{")]


class TestWriteErrorPropagation:
    """A failing API call must surface the error, never a hard-coded success."""

    def test_delete_member_surfaces_api_error(self, mock_mc_request) -> None:
        mock_mc_request({"error": "Resource Not Found", "detail": "member gone", "status": 404})
        payload = json.loads(server.delete_member(list_id="abc", email_address="j@co.com"))
        assert payload.get("error") == "Resource Not Found"
        assert payload.get("status") != "permanently_deleted"

    def test_delete_member_confirms_on_success(self, mock_mc_request) -> None:
        mock_mc_request({"status": "success"})
        payload = json.loads(server.delete_member(list_id="abc", email_address="j@co.com"))
        assert payload["status"] == "permanently_deleted"
        assert payload["email_address"] == "j@co.com"

    def test_tag_member_surfaces_api_error(self, mock_mc_request) -> None:
        mock_mc_request({"error": "Resource Not Found", "status": 404})
        payload = json.loads(server.tag_member(list_id="abc", email_address="j@co.com", tags_to_add="VIP"))
        assert payload.get("error") == "Resource Not Found"
        assert payload.get("status") != "updated"


class TestJsonArgumentGuards:
    """Malformed JSON in a string argument must return a readable error, not raise."""

    def test_batch_subscribe_rejects_bad_json(self, mock_mc_request) -> None:
        calls = mock_mc_request({"new_members": []})
        payload = json.loads(server.batch_subscribe(list_id="abc", members_json="{not json"))
        assert "Invalid members_json" in payload["error"]
        assert calls == []  # never dispatched

    def test_create_segment_rejects_bad_json(self, mock_mc_request) -> None:
        calls = mock_mc_request({"id": "seg1"})
        payload = json.loads(
            server.create_segment(list_id="abc", name="S", match="all", conditions_json="[bad")
        )
        assert "Invalid conditions_json" in payload["error"]
        assert calls == []

    def test_update_segment_rejects_bad_json(self, mock_mc_request) -> None:
        calls = mock_mc_request({"id": "seg1"})
        payload = json.loads(
            server.update_segment(list_id="abc", segment_id="seg1", match="all", conditions_json="[bad")
        )
        assert "Invalid conditions_json" in payload["error"]
        assert calls == []

    def test_create_batch_rejects_bad_json(self, mock_mc_request) -> None:
        calls = mock_mc_request({"id": "batch1"})
        payload = json.loads(server.create_batch(operations="{bad"))
        assert "Invalid operations" in payload["error"]
        assert calls == []


class TestBatchBounds:
    def test_batch_subscribe_rejects_over_500(self, mock_mc_request) -> None:
        calls = mock_mc_request({"new_members": []})
        members = json.dumps([{"email_address": f"u{i}@co.com", "status": "subscribed"} for i in range(501)])
        payload = json.loads(server.batch_subscribe(list_id="abc", members_json=members))
        assert "max is 500" in payload["error"]
        assert calls == []

    def test_batch_subscribe_accepts_500(self, mock_mc_request) -> None:
        calls = mock_mc_request({"new_members": [], "updated_members": []})
        members = json.dumps([{"email_address": f"u{i}@co.com", "status": "subscribed"} for i in range(500)])
        server.batch_subscribe(list_id="abc", members_json=members)
        assert len(calls) == 1


class TestEmailValidation:
    def test_malformed_email_rejected_without_network(self, mock_mc_request) -> None:
        calls = mock_mc_request({"status": "success"})
        payload = json.loads(server.delete_member(list_id="abc", email_address="not-an-email"))
        assert "Invalid email address" in payload["error"]
        assert calls == []

    def test_empty_email_rejected(self, mock_mc_request) -> None:
        calls = mock_mc_request({"status": "success"})
        payload = json.loads(server.update_member(list_id="abc", email_address=""))
        assert "Invalid email address" in payload["error"]
        assert calls == []

    def test_valid_email_dispatches(self, mock_mc_request) -> None:
        calls = mock_mc_request({"status": "subscribed", "email_address": "j@co.com"})
        server.unsubscribe_member(list_id="abc", email_address="j@co.com")
        assert len(calls) == 1


class TestOffsetValidation:
    def test_negative_offset_rejected(self) -> None:
        with patch.object(requests.Session, "request") as mock_req:
            result = server.mc_request("/lists", params={"offset": -5, "count": 10})
        assert "offset" in result["error"]
        mock_req.assert_not_called()


class TestPathTraversal:
    def test_double_dot_segment_rejected_without_network(self) -> None:
        with patch.object(requests.Session, "request") as mock_req:
            result = server.mc_request("/lists/../../pool/members")
        assert "error" in result
        assert ".." in result["error"]
        mock_req.assert_not_called()

    def test_normal_path_still_allowed(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {"ok": True}
        with patch.object(requests.Session, "request", return_value=mock_resp) as mock_req:
            result = server.mc_request("/lists/abc123/members")
        assert result == {"ok": True}
        mock_req.assert_called_once()


def _resp(status: int, *, ok: bool | None = None, payload: dict | None = None, headers: dict | None = None) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.ok = ok if ok is not None else status < 400
    r.json.return_value = payload if payload is not None else {}
    r.headers = headers or {}
    return r


class TestRetry:
    def test_retries_429_then_succeeds(self) -> None:
        seq = [_resp(429), _resp(200, payload={"ok": True})]
        with patch.object(requests.Session, "request", side_effect=seq) as mock_req:
            result = server.mc_request("/ping")
        assert result == {"ok": True}
        assert mock_req.call_count == 2

    def test_retries_5xx_then_gives_up_with_error(self, monkeypatch) -> None:
        monkeypatch.setattr(server, "MAX_RETRIES", 3)
        r = _resp(503)
        r.json.side_effect = ValueError("not json")
        r.text = "Service Unavailable"
        with patch.object(requests.Session, "request", return_value=r) as mock_req:
            result = server.mc_request("/ping")
        assert "HTTP 503" in result["error"]
        assert mock_req.call_count == 4  # initial + 3 retries

    def test_honors_retry_after_header(self, monkeypatch) -> None:
        waits: list[float] = []
        monkeypatch.setattr(server.time, "sleep", lambda s: waits.append(s))
        seq = [_resp(429, headers={"Retry-After": "2"}), _resp(200, payload={"ok": True})]
        with patch.object(requests.Session, "request", side_effect=seq):
            server.mc_request("/ping")
        assert waits == [2.0]

    def test_no_retry_on_success(self) -> None:
        with patch.object(requests.Session, "request", return_value=_resp(200, payload={"ok": True})) as mock_req:
            server.mc_request("/ping")
        assert mock_req.call_count == 1

    def test_timeout_not_retried(self) -> None:
        with patch.object(requests.Session, "request", side_effect=requests.exceptions.Timeout) as mock_req:
            result = server.mc_request("/ping")
        assert "timed out" in result["error"].lower()
        assert mock_req.call_count == 1  # writes may have landed; never replayed


class TestSessionPooling:
    def test_session_reused_per_account(self) -> None:
        server._SESSIONS.clear()
        with patch.object(requests.Session, "request", return_value=_resp(200, payload={"ok": True})):
            server.mc_request("/ping")
            server.mc_request("/lists")
        assert set(server._SESSIONS) == {"default"}


class TestAuditPiiRedaction:
    def test_top_level_email_redacted(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(server, "AUDIT_LOG", True)
        monkeypatch.setattr(server, "READ_ONLY", True)
        server.delete_member(list_id="abc", email_address="jane@secret.com")
        err = capsys.readouterr().err
        assert "jane@secret.com" not in err
        assert "<redacted>" in err

    def test_nested_member_emails_redacted_in_executed_event(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(server, "AUDIT_LOG", True)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {"new_members": [], "updated_members": []}
        members = json.dumps(
            [{"email_address": "buried@secret.com", "status": "subscribed", "merge_fields": {"FNAME": "Jane"}}]
        )
        with patch.object(requests.Session, "request", return_value=mock_resp):
            server.batch_subscribe(list_id="abc", members_json=members)
        err = capsys.readouterr().err
        assert "buried@secret.com" not in err
        assert "Jane" not in err
