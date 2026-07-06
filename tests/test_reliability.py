"""Tests for the reliability-hardening pass: error propagation on writes, JSON-argument
guards, path-traversal rejection, PII redaction in the audit log, and batch bounds."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
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


# Write tools whose success payload was previously hard-coded regardless of the API outcome.
# (tool callable, kwargs, the success-status string that must NOT appear on a failed call)
_HARDCODED_WRITES = [
    (lambda: server.send_campaign(campaign_id="c1"), "sent"),
    (lambda: server.send_test_email(campaign_id="c1", test_emails="a@b.com"), "test_sent"),
    (lambda: server.schedule_campaign(campaign_id="c1", schedule_time="2026-01-01T00:00:00Z"), "scheduled"),
    (lambda: server.unschedule_campaign(campaign_id="c1"), "unscheduled"),
    (lambda: server.cancel_send(campaign_id="c1"), "cancelled"),
    (lambda: server.delete_campaign(campaign_id="c1"), "deleted"),
    (lambda: server.delete_template(template_id="t1"), "deleted"),
    (lambda: server.delete_segment(list_id="l1", segment_id="s1"), "deleted"),
    (lambda: server.delete_webhook(list_id="l1", webhook_id="w1"), "deleted"),
    (lambda: server.pause_automation(automation_id="a1"), "paused"),
    (lambda: server.start_automation(automation_id="a1"), "started"),
    (lambda: server.trigger_customer_journey(journey_id="j1", step_id="s1", email_address="a@b.com"), "triggered"),
]


class TestHardCodedWriteResults:
    """The 20 write/destructive tools that discarded mc_request's result must now surface errors."""

    @pytest.mark.parametrize("call, success_status", _HARDCODED_WRITES)
    def test_surfaces_api_error(self, mock_mc_request, call, success_status) -> None:
        mock_mc_request({"error": "Bad Request", "detail": "already sent", "status": 400})
        payload = json.loads(call())
        assert payload.get("error") == "Bad Request"
        assert payload.get("status") != success_status

    def test_send_campaign_confirms_on_success(self, mock_mc_request) -> None:
        mock_mc_request({"status": "success"})
        payload = json.loads(server.send_campaign(campaign_id="c1"))
        assert payload["status"] == "sent"
        assert payload["campaign_id"] == "c1"


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


class TestResponseVolumeBounds:
    def test_campaign_html_truncated_with_note(self, monkeypatch, mock_mc_request) -> None:
        monkeypatch.setattr(server, "MAX_CONTENT_CHARS", 100)
        mock_mc_request({"plain_text": "short", "html": "x" * 5000})
        payload = json.loads(server.get_campaign_content(campaign_id="c1", include_html=True))
        assert len(payload["html"]) == 100
        assert "truncated" in payload
        assert "html (5000 chars)" in payload["truncated"]
        assert "plain_text" not in payload["truncated"]  # short field untouched

    def test_no_note_when_under_cap(self, monkeypatch, mock_mc_request) -> None:
        monkeypatch.setattr(server, "MAX_CONTENT_CHARS", 100000)
        mock_mc_request({"plain_text": "hello", "html": "<p>hi</p>"})
        payload = json.loads(server.get_campaign_content(campaign_id="c1", include_html=True))
        assert "truncated" not in payload
        assert payload["html"] == "<p>hi</p>"

    def test_cap_disabled_when_zero(self, monkeypatch, mock_mc_request) -> None:
        monkeypatch.setattr(server, "MAX_CONTENT_CHARS", 0)
        mock_mc_request({"plain_text": "p", "html": "y" * 300000})
        payload = json.loads(server.get_campaign_content(campaign_id="c1", include_html=True))
        assert len(payload["html"]) == 300000
        assert "truncated" not in payload


class TestBatchRiskTier:
    def test_create_batch_is_destructive(self) -> None:
        assert server.TOOL_RISK["create_batch"] == "destructive"

    def test_describe_tools_marks_create_batch_destructive(self) -> None:
        by_name = {t["name"]: t for t in json.loads(server.describe_tools())["tools"]}
        assert by_name["create_batch"]["risk"] == "destructive"
        assert by_name["create_batch"]["destructive"] is True

    def test_batch_subscribe_stays_write(self) -> None:
        # add/update only, no permanent deletion -> still a plain write, not destructive.
        assert server.TOOL_RISK["batch_subscribe"] == "write"


class TestMetadataTruthfulness:
    """Docstrings must not contradict the machine-readable risk/idempotency signals."""

    def test_no_tool_claims_read_scope_for_a_write(self) -> None:
        # A2: 'read scope required' appeared on tag_member, a write. It should exist nowhere.
        import inspect

        for name, risk in server.TOOL_RISK.items():
            fn = getattr(server, name)
            doc = inspect.getdoc(fn) or ""
            assert "read scope required" not in doc, f"{name} ({risk}) claims read scope"

    @pytest.mark.parametrize(
        "name", ["update_member", "tag_member", "update_segment", "publish_landing_page"]
    )
    def test_idempotent_prose_matches_annotation(self, name) -> None:
        # B1: these tools say "Idempotent" in prose; the machine hint must agree.
        import inspect

        doc = inspect.getdoc(getattr(server, name)) or ""
        assert "idempotent" in doc.lower()
        assert server._idempotent(name) is True

    def test_describe_tools_reports_idempotent_for_these(self) -> None:
        by_name = {t["name"]: t for t in json.loads(server.describe_tools())["tools"]}
        for name in ("update_member", "tag_member", "update_segment", "publish_landing_page"):
            assert by_name[name]["idempotent"] is True


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
