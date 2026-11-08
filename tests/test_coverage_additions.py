"""Tests for the tools added to close the gap with the Mailchimp Marketing API v3."""

from __future__ import annotations

import hashlib
import json

import pytest

from mailchimp_mcp_server import server

JANE_HASH = hashlib.md5(b"jane@co.com").hexdigest()

# (tool name, kwargs, expected method, expected endpoint)
READ_CASES = [
    ("list_campaign_reports", {}, "GET", "/reports"),
    ("get_link_click_details", {"campaign_id": "c1", "link_id": "l1"}, "GET", "/reports/c1/click-details/l1"),
    ("list_link_clickers", {"campaign_id": "c1", "link_id": "l1"}, "GET", "/reports/c1/click-details/l1/members"),
    (
        "get_link_clicker",
        {"campaign_id": "c1", "link_id": "l1", "email_address": "Jane@co.com"},
        "GET",
        f"/reports/c1/click-details/l1/members/{JANE_HASH}",
    ),
    ("get_member_open_details", {"campaign_id": "c1", "email_address": "jane@co.com"}, "GET", f"/reports/c1/open-details/{JANE_HASH}"),
    ("get_member_email_activity", {"campaign_id": "c1", "email_address": "jane@co.com"}, "GET", f"/reports/c1/email-activity/{JANE_HASH}"),
    ("get_member_sent_to_status", {"campaign_id": "c1", "email_address": "jane@co.com"}, "GET", f"/reports/c1/sent-to/{JANE_HASH}"),
    ("get_member_unsubscribe_record", {"campaign_id": "c1", "email_address": "jane@co.com"}, "GET", f"/reports/c1/unsubscribed/{JANE_HASH}"),
    ("get_audience_growth_for_month", {"list_id": "l1", "month": "2026-04"}, "GET", "/lists/l1/growth-history/2026-04"),
    ("search_tags", {"list_id": "l1", "name": "vip"}, "GET", "/lists/l1/tag-search"),
    ("get_interest_category", {"list_id": "l1", "category_id": "k1"}, "GET", "/lists/l1/interest-categories/k1"),
    ("get_interest", {"list_id": "l1", "category_id": "k1", "interest_id": "i1"}, "GET", "/lists/l1/interest-categories/k1/interests/i1"),
    ("get_automation", {"workflow_id": "w1"}, "GET", "/automations/w1"),
    ("get_landing_page_content", {"page_id": "p1"}, "GET", "/landing-pages/p1/content"),
    ("get_file_folder", {"folder_id": "f1"}, "GET", "/file-manager/folders/f1"),
    ("list_file_folder_files", {"folder_id": "f1"}, "GET", "/file-manager/folders/f1/files"),
    ("list_store_cart_lines", {"store_id": "s1", "cart_id": "c1"}, "GET", "/ecommerce/stores/s1/carts/c1/lines"),
    ("get_store_cart_line", {"store_id": "s1", "cart_id": "c1", "line_id": "n1"}, "GET", "/ecommerce/stores/s1/carts/c1/lines/n1"),
    ("list_sms_campaigns", {}, "GET", "/sms-campaigns"),
]

WRITE_CASES = [
    ("update_interest_category", {"list_id": "l1", "category_id": "k1", "title": "Topics"}, "PATCH", "/lists/l1/interest-categories/k1"),
    ("update_interest", {"list_id": "l1", "category_id": "k1", "interest_id": "i1", "name": "News"}, "PATCH", "/lists/l1/interest-categories/k1/interests/i1"),
    ("archive_automation", {"workflow_id": "w1"}, "POST", "/automations/w1/actions/archive"),
    ("create_file_folder", {"name": "Q4"}, "POST", "/file-manager/folders"),
    ("update_file_folder", {"folder_id": "f1", "name": "Q4 bis"}, "PATCH", "/file-manager/folders/f1"),
    ("delete_file_folder", {"folder_id": "f1"}, "DELETE", "/file-manager/folders/f1"),
    (
        "create_store_cart_line",
        {"store_id": "s1", "cart_id": "c1", "line_id": "n1", "product_id": "p1", "product_variant_id": "v1", "quantity": 2, "price": 9.5},
        "POST",
        "/ecommerce/stores/s1/carts/c1/lines",
    ),
    ("update_store_cart_line", {"store_id": "s1", "cart_id": "c1", "line_id": "n1", "additional_fields": {"quantity": 3}}, "PATCH", "/ecommerce/stores/s1/carts/c1/lines/n1"),
    ("delete_store_cart_line", {"store_id": "s1", "cart_id": "c1", "line_id": "n1"}, "DELETE", "/ecommerce/stores/s1/carts/c1/lines/n1"),
    ("create_campaign_from_survey", {"list_id": "l1", "survey_id": "sv1"}, "POST", "/lists/l1/surveys/sv1/actions/create-email"),
    ("replicate_survey", {"list_id": "l1", "survey_id": "sv1"}, "POST", "/lists/l1/surveys/sv1/actions/replicate"),
    ("enable_site_pixel", {"connected_site_id": "cs1"}, "POST", "/connected-sites/cs1/actions/enable-pixel"),
    ("disable_site_pixel", {"connected_site_id": "cs1"}, "POST", "/connected-sites/cs1/actions/disable-pixel"),
]


class TestReadAdditions:
    @pytest.mark.parametrize("name,kwargs,method,endpoint", READ_CASES)
    def test_dispatch(self, mock_mc_request, name, kwargs, method, endpoint) -> None:
        calls = mock_mc_request({"ok": True})
        payload = json.loads(getattr(server, name)(**kwargs))
        assert payload == {"ok": True}
        assert calls[0]["endpoint"] == endpoint
        assert calls[0]["method"] == method
        assert server.TOOL_RISK[name] == "read"

    @pytest.mark.parametrize("name,kwargs,method,endpoint", READ_CASES)
    def test_error_is_returned_as_is(self, mock_mc_request, name, kwargs, method, endpoint) -> None:
        mock_mc_request({"error": "Resource Not Found", "status": 404})
        payload = json.loads(getattr(server, name)(**kwargs))
        assert payload["error"] == "Resource Not Found"
        assert payload["status"] == 404

    def test_report_filters_skip_unset_values(self, mock_mc_request) -> None:
        calls = mock_mc_request({"reports": []})
        server.list_campaign_reports(count=5, campaign_type="regular")
        assert calls[0]["params"] == {"count": 5, "offset": 0, "type": "regular"}

    def test_member_tools_reject_invalid_email(self, mock_mc_request) -> None:
        calls = mock_mc_request({"ok": True})
        payload = json.loads(server.get_member_open_details(campaign_id="c1", email_address="not-an-email"))
        assert "error" in payload
        assert calls == []


class TestWriteAdditions:
    @pytest.mark.parametrize("name,kwargs,method,endpoint", WRITE_CASES)
    def test_dispatch(self, mock_mc_request, name, kwargs, method, endpoint) -> None:
        calls = mock_mc_request({"id": "x"})
        json.loads(getattr(server, name)(**kwargs))
        assert calls[0]["endpoint"] == endpoint
        assert calls[0]["method"] == method

    @pytest.mark.parametrize("name,kwargs,method,endpoint", WRITE_CASES)
    def test_dry_run_blocks_the_call(self, monkeypatch, mock_mc_request, name, kwargs, method, endpoint) -> None:
        monkeypatch.setattr(server, "DRY_RUN", True)
        calls = mock_mc_request({"id": "x"})
        payload = json.loads(getattr(server, name)(**kwargs))
        assert payload["dry_run"] is True
        assert calls == []

    @pytest.mark.parametrize("name,kwargs,method,endpoint", WRITE_CASES)
    def test_read_only_blocks_the_call(self, monkeypatch, mock_mc_request, name, kwargs, method, endpoint) -> None:
        monkeypatch.setattr(server, "READ_ONLY", True)
        calls = mock_mc_request({"id": "x"})
        payload = json.loads(getattr(server, name)(**kwargs))
        assert "error" in payload
        assert calls == []

    def test_archive_automation_is_destructive(self) -> None:
        assert server.TOOL_RISK["archive_automation"] == "destructive"

    @pytest.mark.parametrize("name", ["delete_file_folder", "delete_store_cart_line"])
    def test_deletes_are_destructive(self, name) -> None:
        assert server.TOOL_RISK[name] == "destructive"

    @pytest.mark.parametrize("name", ["update_interest_category", "create_file_folder", "enable_site_pixel", "replicate_survey"])
    def test_other_writes_stay_write(self, name) -> None:
        assert server.TOOL_RISK[name] == "write"

    def test_update_interest_category_only_sends_set_fields(self, mock_mc_request) -> None:
        calls = mock_mc_request({"id": "k1"})
        server.update_interest_category(list_id="l1", category_id="k1", title="Topics")
        assert calls[0]["body"] == {"title": "Topics"}

    def test_update_without_fields_is_rejected(self, mock_mc_request) -> None:
        calls = mock_mc_request({"id": "k1"})
        payload = json.loads(server.update_interest(list_id="l1", category_id="k1", interest_id="i1"))
        assert "error" in payload
        assert calls == []

    def test_delete_reports_status(self, mock_mc_request) -> None:
        mock_mc_request({"status": "success"})
        payload = json.loads(server.delete_file_folder(folder_id="f1"))
        assert payload == {"status": "deleted", "folder_id": "f1"}


class TestClickDetailsExposeLinkId:
    def test_links_carry_their_id(self, mock_mc_request) -> None:
        mock_mc_request({"total_items": 1, "urls_clicked": [{"id": "l1", "url": "https://a.be", "total_clicks": 3, "unique_clicks": 2, "click_percentage": 0.1}]})
        payload = json.loads(server.get_campaign_click_details(campaign_id="c1"))
        assert payload["links"][0]["id"] == "l1"
