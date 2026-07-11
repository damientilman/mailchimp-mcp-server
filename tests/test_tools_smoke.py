"""Smoke tests covering one representative tool per family.

These tests do not enumerate every tool; they verify each major area is wired up
correctly and that response payloads are shaped as documented. The full set of
fields returned by Mailchimp is not asserted.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from mailchimp_mcp_server import server


def _parse(result: str) -> dict:
    return json.loads(result)


class TestAccount:
    def test_get_account_info(self, mock_mc_request) -> None:
        mock_mc_request(
            {
                "account_name": "Acme Inc.",
                "email": "owner@acme.com",
                "first_name": "Owner",
                "last_name": "Smith",
                "total_subscribers": 12345,
                "industry_stats": {"open_rate": 0.21, "click_rate": 0.03},
            }
        )
        payload = _parse(server.get_account_info())
        assert payload["account_name"] == "Acme Inc."
        assert payload["total_subscribers"] == 12345
        assert payload["industry_stats"]["open_rate"] == 0.21

    def test_ping(self, mock_mc_request) -> None:
        mock_mc_request({"health_check": "Everything's Chimpy!"})
        payload = _parse(server.ping())
        assert payload["health_check"] == "Everything's Chimpy!"
        assert payload["status_code"] == 200


class TestAudiences:
    def test_list_audiences_extracts_fields(self, mock_mc_request) -> None:
        mock_mc_request(
            {
                "total_items": 2,
                "lists": [
                    {
                        "id": "list_a",
                        "name": "Main Audience",
                        "date_created": "2024-01-01T00:00:00Z",
                        "stats": {
                            "member_count": 100,
                            "unsubscribe_count": 5,
                            "open_rate": 0.4,
                            "click_rate": 0.05,
                        },
                        "campaign_defaults": {
                            "from_name": "Acme",
                            "from_email": "hello@acme.com",
                            "subject": "",
                            "language": "en",
                        },
                        "double_optin": True,
                        "marketing_permissions": False,
                    },
                ],
            }
        )
        payload = _parse(server.list_audiences(count=5))
        assert payload["total_items"] == 2
        assert payload["audiences"][0]["id"] == "list_a"
        assert payload["audiences"][0]["member_count"] == 100
        assert payload["audiences"][0]["campaign_defaults"]["from_name"] == "Acme"
        assert payload["audiences"][0]["double_optin"] is True
        assert payload["audiences"][0]["marketing_permissions"] is False

    def test_list_audiences_settings_default_to_none_when_absent(self, mock_mc_request) -> None:
        mock_mc_request(
            {
                "total_items": 1,
                "lists": [
                    {
                        "id": "list_b",
                        "name": "Legacy",
                        "date_created": "2024-01-01T00:00:00Z",
                        "stats": {
                            "member_count": 10,
                            "unsubscribe_count": 0,
                            "open_rate": 0.0,
                            "click_rate": 0.0,
                        },
                    },
                ],
            }
        )
        payload = _parse(server.list_audiences())
        assert payload["audiences"][0]["campaign_defaults"] is None
        assert payload["audiences"][0]["double_optin"] is None
        assert payload["audiences"][0]["marketing_permissions"] is None

    def test_get_audience_details(self, mock_mc_request) -> None:
        mock_mc_request(
            {
                "id": "list_a",
                "name": "Main Audience",
                "stats": {"member_count": 100},
                "date_created": "2024-01-01T00:00:00Z",
                "list_rating": 4,
                "subscribe_url_short": "http://eepurl.com/abc",
            }
        )
        payload = _parse(server.get_audience_details(list_id="list_a"))
        assert payload["id"] == "list_a"
        assert payload["list_rating"] == 4


class TestCampaigns:
    def test_list_campaigns_passes_filters(self, mock_mc_request) -> None:
        calls = mock_mc_request({"total_items": 0, "campaigns": []})
        server.list_campaigns(count=10, status="sent", since_send_time="2025-01-01T00:00:00Z")
        assert calls[0]["endpoint"] == "/campaigns"
        assert calls[0]["params"]["status"] == "sent"
        assert calls[0]["params"]["since_send_time"] == "2025-01-01T00:00:00Z"
        assert calls[0]["params"]["count"] == 10

    def test_list_campaigns_omits_optional_params_when_none(self, mock_mc_request) -> None:
        calls = mock_mc_request({"total_items": 0, "campaigns": []})
        server.list_campaigns(count=5)
        assert "status" not in calls[0]["params"]
        assert "since_send_time" not in calls[0]["params"]


class TestCampaignContent:
    def test_returns_plain_text_and_withholds_html_by_default(self, mock_mc_request) -> None:
        calls = mock_mc_request({"plain_text": "Welcome aboard, here is your guide.", "html": "<p>Welcome</p>"})
        payload = _parse(server.get_campaign_content(campaign_id="cam_1"))
        assert calls[0]["endpoint"] == "/campaigns/cam_1/content"
        assert calls[0]["method"] == "GET"
        assert payload["campaign_id"] == "cam_1"
        assert payload["plain_text"].startswith("Welcome aboard")
        assert "html" not in payload

    def test_includes_html_when_opted_in(self, mock_mc_request) -> None:
        mock_mc_request({"plain_text": "Body copy", "html": "<p>Body copy</p>"})
        payload = _parse(server.get_campaign_content(campaign_id="cam_1", include_html=True))
        assert payload["html"] == "<p>Body copy</p>"

    def test_breaks_out_ab_variations(self, mock_mc_request) -> None:
        mock_mc_request(
            {
                "plain_text": "",
                "variate_contents": [
                    {"content_label": "Variation A", "plain_text": "Copy for A"},
                    {"content_label": "Variation B", "plain_text": "Copy for B"},
                ],
            }
        )
        payload = _parse(server.get_campaign_content(campaign_id="cam_variate"))
        assert len(payload["variations"]) == 2
        assert payload["variations"][0]["label"] == "Variation A"
        assert payload["variations"][1]["plain_text"] == "Copy for B"

    def test_propagates_api_error(self, mock_mc_request) -> None:
        mock_mc_request({"error": "Resource Not Found", "status": 404})
        payload = _parse(server.get_campaign_content(campaign_id="missing"))
        assert payload["error"] == "Resource Not Found"
        assert "plain_text" not in payload


class TestReports:
    def test_get_campaign_report_extracts_metrics(self, mock_mc_request) -> None:
        mock_mc_request(
            {
                "campaign_title": "Spring Sale",
                "subject_line": "20% off",
                "emails_sent": 1000,
                "abuse_reports": 0,
                "unsubscribed": 3,
                "send_time": "2025-04-01T10:00:00Z",
                "opens": {"opens_total": 400, "unique_opens": 350, "open_rate": 0.35},
                "clicks": {"clicks_total": 80, "unique_clicks": 70, "click_rate": 0.07},
                "bounces": {"hard_bounces": 1, "soft_bounces": 2},
                "forwards": {"forwards_count": 0},
                "list_stats": {},
                "industry_stats": {},
            }
        )
        payload = _parse(server.get_campaign_report(campaign_id="cam_1"))
        assert payload["campaign_title"] == "Spring Sale"
        assert payload["opens"]["open_rate"] == 0.35
        assert payload["clicks"]["unique_clicks"] == 70


class TestMembers:
    def test_list_audience_members(self, mock_mc_request) -> None:
        calls = mock_mc_request({"total_items": 0, "members": []})
        server.list_audience_members(list_id="list_a", count=50, status="subscribed")
        assert calls[0]["endpoint"] == "/lists/list_a/members"
        assert calls[0]["params"]["status"] == "subscribed"
        assert calls[0]["params"]["count"] == 50

    def test_add_member_includes_tags(self, mock_mc_request) -> None:
        calls = mock_mc_request({"id": "h", "email_address": "a@b.com", "status": "subscribed", "full_name": "Alice"})
        server.add_member(
            list_id="abc",
            email_address="a@b.com",
            first_name="Alice",
            tags="VIP, Newsletter",
        )
        body = calls[0]["body"]
        assert body["tags"] == ["VIP", "Newsletter"]
        assert body["merge_fields"]["FNAME"] == "Alice"


class TestAudienceCRUD:
    def _valid_payload(self) -> dict:
        return {
            "name": "New Audience",
            "from_name": "Damien",
            "from_email": "damien@tilman.marketing",
            "subject": "Welcome",
            "language": "en",
            "company": "Tilman Marketing",
            "address1": "1 Main St",
            "city": "Paris",
            "state": "IDF",
            "zip": "75001",
            "country": "FR",
            "permission_reminder": "You signed up at tilman.marketing.",
        }

    def test_create_audience_sends_required_fields(self, mock_mc_request) -> None:
        calls = mock_mc_request(
            {
                "id": "new_list",
                "name": "New Audience",
                "stats": {"member_count": 0},
                "date_created": "2026-05-16T00:00:00Z",
                "subscribe_url_short": "http://eepurl.com/x",
            }
        )
        result = server.create_audience(**self._valid_payload())
        payload = json.loads(result)

        assert payload["id"] == "new_list"
        assert payload["member_count"] == 0

        body = calls[0]["body"]
        assert calls[0]["endpoint"] == "/lists"
        assert calls[0]["method"] == "POST"
        assert body["name"] == "New Audience"
        assert body["contact"]["country"] == "FR"
        assert body["campaign_defaults"]["from_email"] == "damien@tilman.marketing"
        assert body["email_type_option"] is False

    def test_create_audience_propagates_api_error(self, mock_mc_request) -> None:
        mock_mc_request({"error": "Invalid Resource", "detail": "address1 is required", "status": 400})
        result = server.create_audience(**self._valid_payload())
        payload = json.loads(result)
        assert payload["error"] == "Invalid Resource"

    def test_delete_audience(self, mock_mc_request) -> None:
        calls = mock_mc_request({"status": "success"})
        result = server.delete_audience(list_id="list_a")
        payload = json.loads(result)
        assert payload == {"status": "deleted", "list_id": "list_a"}
        assert calls[0]["method"] == "DELETE"
        assert calls[0]["endpoint"] == "/lists/list_a"


class TestVariateCampaigns:
    def test_regular_campaign_default_type(self, mock_mc_request) -> None:
        calls = mock_mc_request(
            {"id": "cam1", "status": "save", "type": "regular", "settings": {"title": "Hi"}, "web_id": 1}
        )
        server.create_campaign(list_id="abc", subject_line="Hi")
        body = calls[0]["body"]
        assert body["type"] == "regular"
        assert "variate_settings" not in body

    def test_variate_campaign_parses_settings(self, mock_mc_request) -> None:
        calls = mock_mc_request(
            {"id": "cam2", "status": "save", "type": "variate", "settings": {"title": "AB"}, "web_id": 2}
        )
        variate = json.dumps(
            {
                "winner_criteria": "opens",
                "test_size": 20,
                "wait_time": 1440,
                "subject_lines": ["Spring Sale 20% off", "Last chance: 20% off Spring"],
            }
        )
        result = server.create_campaign(
            list_id="abc",
            subject_line="Spring Sale 20% off",
            campaign_type="variate",
            variate_settings_json=variate,
        )
        payload = json.loads(result)
        assert payload["type"] == "variate"

        body = calls[0]["body"]
        assert body["type"] == "variate"
        assert body["variate_settings"]["winner_criteria"] == "opens"
        assert body["variate_settings"]["subject_lines"] == [
            "Spring Sale 20% off",
            "Last chance: 20% off Spring",
        ]

    def test_variate_requires_settings(self, mock_mc_request) -> None:
        calls = mock_mc_request({"should": "not-be-called"})
        result = server.create_campaign(
            list_id="abc",
            subject_line="Hi",
            campaign_type="variate",
        )
        payload = json.loads(result)
        assert "error" in payload
        assert "variate_settings_json is required" in payload["error"]
        assert calls == []

    def test_variate_rejects_invalid_json(self, mock_mc_request) -> None:
        calls = mock_mc_request({"should": "not-be-called"})
        result = server.create_campaign(
            list_id="abc",
            subject_line="Hi",
            campaign_type="variate",
            variate_settings_json="{not valid json",
        )
        payload = json.loads(result)
        assert "Invalid variate_settings_json" in payload["error"]
        assert calls == []


class TestReportsExtras:
    def test_get_campaign_advice(self, mock_mc_request) -> None:
        mock_mc_request(
            {
                "total_items": 2,
                "advice": [
                    {"type": "negative", "message": "Your open rate is below industry average."},
                    {"type": "positive", "message": "Click rate is strong."},
                ],
            }
        )
        payload = json.loads(server.get_campaign_advice(campaign_id="cam_1"))
        assert payload["total_items"] == 2
        assert payload["advice"][0]["type"] == "negative"

    def test_get_campaign_locations_pagination(self, mock_mc_request) -> None:
        calls = mock_mc_request(
            {
                "total_items": 1,
                "locations": [
                    {"country_code": "US", "region": "CA", "region_name": "California", "opens": 42},
                ],
            }
        )
        payload = json.loads(server.get_campaign_locations(campaign_id="cam_1", count=50))
        assert payload["locations"][0]["country_code"] == "US"
        assert calls[0]["params"]["count"] == 50

    def test_get_eepurl_activity(self, mock_mc_request) -> None:
        mock_mc_request(
            {
                "eepurl": "http://eepurl.com/xyz",
                "twitter": {"statuses": 12, "impressions": 5000},
                "facebook": {"likes": 30, "unique_likes": 28},
                "clicks": {"referrer_clicks": [{"referrer": "t.co", "clicks": 12}]},
            }
        )
        payload = json.loads(server.get_eepurl_activity(campaign_id="cam_1"))
        assert payload["eepurl"] == "http://eepurl.com/xyz"
        assert payload["twitter"]["impressions"] == 5000
        assert payload["referrers"][0]["referrer"] == "t.co"


class TestTemplatesMetadata:
    def test_get_template(self, mock_mc_request) -> None:
        mock_mc_request(
            {
                "id": 42,
                "name": "Welcome Series",
                "type": "user",
                "drag_and_drop": True,
                "date_created": "2026-01-01T00:00:00Z",
                "date_edited": "2026-02-01T00:00:00Z",
                "active": True,
                "thumbnail": "https://example.com/t.png",
                "share_url": "https://us1.admin.mailchimp.com/...",
            }
        )
        payload = json.loads(server.get_template(template_id="42"))
        assert payload["id"] == 42
        assert payload["name"] == "Welcome Series"
        assert payload["type"] == "user"
        assert payload["drag_and_drop"] is True


class TestLandingPageCRUD:
    def test_create_landing_page_sends_template_id_as_int(self, mock_mc_request) -> None:
        calls = mock_mc_request(
            {
                "id": "page_1",
                "name": "Promo Page",
                "title": "Spring promo",
                "status": "unpublished",
                "url": None,
                "created_at": "2026-05-16T00:00:00Z",
                "list_id": "abc",
            }
        )
        server.create_landing_page(
            name="Promo Page",
            title="Spring promo",
            list_id="abc",
            template_id="42",
        )
        body = calls[0]["body"]
        assert body["name"] == "Promo Page"
        assert body["list_id"] == "abc"
        assert body["template"] == {"id": 42}
        assert body["tracking"] == {"opens": True, "clicks": True}
        assert calls[0]["method"] == "POST"

    def test_update_landing_page_only_sends_provided_fields(self, mock_mc_request) -> None:
        calls = mock_mc_request({"id": "page_1", "name": "X", "status": "unpublished"})
        server.update_landing_page(page_id="page_1", title="New title", tracking_clicks=False)
        body = calls[0]["body"]
        assert "name" not in body
        assert body["title"] == "New title"
        assert body["tracking"] == {"clicks": False}
        assert calls[0]["method"] == "PATCH"

    def test_delete_landing_page(self, mock_mc_request) -> None:
        calls = mock_mc_request({"status": "success"})
        result = server.delete_landing_page(page_id="page_1")
        payload = json.loads(result)
        assert payload == {"status": "deleted", "page_id": "page_1"}
        assert calls[0]["method"] == "DELETE"
        assert calls[0]["endpoint"] == "/landing-pages/page_1"

    def test_publish_landing_page(self, mock_mc_request) -> None:
        calls = mock_mc_request({"status": "success"})
        payload = json.loads(server.publish_landing_page(page_id="page_1"))
        assert payload == {"status": "published", "page_id": "page_1"}
        assert calls[0]["endpoint"] == "/landing-pages/page_1/actions/publish"
        assert calls[0]["method"] == "POST"

    def test_unpublish_landing_page(self, mock_mc_request) -> None:
        calls = mock_mc_request({"status": "success"})
        payload = json.loads(server.unpublish_landing_page(page_id="page_1"))
        assert payload == {"status": "unpublished", "page_id": "page_1"}
        assert calls[0]["endpoint"] == "/landing-pages/page_1/actions/unpublish"


class TestMemberNotesCRUD:
    EMAIL = "jane@example.com"
    # MD5("jane@example.com") computed once for assertions below.
    HASH = "9e26471d35a78862c17e467d87cddedf"

    def test_list_member_notes_uses_md5_hash(self, mock_mc_request) -> None:
        calls = mock_mc_request(
            {"total_items": 1, "notes": [{"id": 7, "note": "Asked for discount", "created_at": "2026-05-16T00:00:00Z"}]}
        )
        payload = json.loads(server.list_member_notes(list_id="abc", email_address=self.EMAIL))
        assert payload["total_items"] == 1
        assert payload["notes"][0]["id"] == 7
        assert calls[0]["endpoint"] == f"/lists/abc/members/{self.HASH}/notes"

    def test_add_member_note(self, mock_mc_request) -> None:
        calls = mock_mc_request(
            {"id": 7, "note": "VIP customer", "created_at": "2026-05-16T00:00:00Z", "created_by": "Damien"}
        )
        result = server.add_member_note(list_id="abc", email_address=self.EMAIL, note="VIP customer")
        payload = json.loads(result)
        assert payload["id"] == 7
        assert payload["email_address"] == self.EMAIL
        assert calls[0]["method"] == "POST"
        assert calls[0]["body"] == {"note": "VIP customer"}
        assert calls[0]["endpoint"] == f"/lists/abc/members/{self.HASH}/notes"

    def test_update_member_note(self, mock_mc_request) -> None:
        calls = mock_mc_request({"id": 7, "note": "Updated", "updated_at": "2026-05-17T00:00:00Z"})
        server.update_member_note(list_id="abc", email_address=self.EMAIL, note_id="7", note="Updated")
        assert calls[0]["method"] == "PATCH"
        assert calls[0]["endpoint"] == f"/lists/abc/members/{self.HASH}/notes/7"
        assert calls[0]["body"] == {"note": "Updated"}

    def test_delete_member_note(self, mock_mc_request) -> None:
        calls = mock_mc_request({"status": "success"})
        payload = json.loads(server.delete_member_note(list_id="abc", email_address=self.EMAIL, note_id="7"))
        assert payload == {"status": "deleted", "email_address": self.EMAIL, "note_id": "7"}
        assert calls[0]["method"] == "DELETE"
        assert calls[0]["endpoint"] == f"/lists/abc/members/{self.HASH}/notes/7"


class TestEcommerceCartsCRUD:
    def test_list_store_carts(self, mock_mc_request) -> None:
        mock_mc_request(
            {
                "total_items": 1,
                "carts": [
                    {
                        "id": "cart_1",
                        "customer": {"id": "cust_1", "email_address": "a@b.com"},
                        "currency_code": "EUR",
                        "order_total": 49.99,
                        "checkout_url": "https://shop.example/cart/cart_1",
                        "created_at": "2026-05-16T00:00:00Z",
                    }
                ],
            }
        )
        payload = json.loads(server.list_store_carts(store_id="store_a"))
        assert payload["total_items"] == 1
        assert payload["carts"][0]["currency_code"] == "EUR"

    def test_get_store_cart(self, mock_mc_request) -> None:
        calls = mock_mc_request(
            {
                "id": "cart_1",
                "customer": {"id": "cust_1"},
                "currency_code": "EUR",
                "order_total": 49.99,
                "lines": [{"id": "line_1", "product_id": "p_1", "quantity": 2, "price": 24.99}],
            }
        )
        payload = json.loads(server.get_store_cart(store_id="store_a", cart_id="cart_1"))
        assert payload["lines"][0]["quantity"] == 2
        assert calls[0]["endpoint"] == "/ecommerce/stores/store_a/carts/cart_1"

    def test_create_store_cart_parses_lines_json(self, mock_mc_request) -> None:
        calls = mock_mc_request(
            {"id": "cart_42", "customer": {"id": "cust_1"}, "currency_code": "EUR", "order_total": 19.99}
        )
        lines = json.dumps([{"id": "line_1", "product_id": "p_1", "quantity": 1, "price": 19.99}])
        server.create_store_cart(
            store_id="store_a",
            cart_id="cart_42",
            customer_id="cust_1",
            currency_code="EUR",
            order_total=19.99,
            lines_json=lines,
        )
        body = calls[0]["body"]
        assert body["id"] == "cart_42"
        assert body["customer"] == {"id": "cust_1"}
        assert body["lines"][0]["product_id"] == "p_1"
        assert calls[0]["method"] == "POST"

    def test_create_store_cart_rejects_invalid_lines_json(self, mock_mc_request) -> None:
        calls = mock_mc_request({"should": "not-be-called"})
        result = server.create_store_cart(
            store_id="store_a",
            cart_id="cart_42",
            customer_id="cust_1",
            currency_code="EUR",
            order_total=19.99,
            lines_json="{not json",
        )
        payload = json.loads(result)
        assert "Invalid lines_json" in payload["error"]
        assert calls == []

    def test_update_store_cart_only_sends_provided_fields(self, mock_mc_request) -> None:
        calls = mock_mc_request({"id": "cart_1", "order_total": 99.99})
        server.update_store_cart(store_id="store_a", cart_id="cart_1", order_total=99.99)
        body = calls[0]["body"]
        assert body == {"order_total": 99.99}
        assert calls[0]["method"] == "PATCH"

    def test_delete_store_cart(self, mock_mc_request) -> None:
        calls = mock_mc_request({"status": "success"})
        payload = json.loads(server.delete_store_cart(store_id="store_a", cart_id="cart_1"))
        assert payload == {"status": "deleted", "store_id": "store_a", "cart_id": "cart_1"}
        assert calls[0]["method"] == "DELETE"


class TestEcommercePromoRulesCRUD:
    def test_list_promo_rules(self, mock_mc_request) -> None:
        mock_mc_request(
            {
                "total_items": 1,
                "promo_rules": [
                    {
                        "id": "rule_1",
                        "title": "Summer Sale",
                        "description": "20% off",
                        "amount": 20,
                        "type": "percentage",
                        "target": "total",
                        "enabled": True,
                    }
                ],
            }
        )
        payload = json.loads(server.list_promo_rules(store_id="store_a"))
        assert payload["promo_rules"][0]["type"] == "percentage"

    def test_get_promo_rule(self, mock_mc_request) -> None:
        mock_mc_request({"id": "rule_1", "type": "percentage", "amount": 20, "enabled": True})
        payload = json.loads(server.get_promo_rule(store_id="store_a", promo_rule_id="rule_1"))
        assert payload["amount"] == 20

    def test_create_promo_rule(self, mock_mc_request) -> None:
        calls = mock_mc_request(
            {
                "id": "rule_42",
                "description": "Summer 20%",
                "amount": 20,
                "type": "percentage",
                "target": "total",
                "enabled": True,
                "created_at": "2026-05-16T00:00:00Z",
            }
        )
        server.create_promo_rule(
            store_id="store_a",
            promo_rule_id="rule_42",
            description="Summer 20%",
            amount=20,
            type="percentage",
            target="total",
            starts_at="2026-06-01T00:00:00Z",
        )
        body = calls[0]["body"]
        assert body["id"] == "rule_42"
        assert body["type"] == "percentage"
        assert body["target"] == "total"
        assert body["starts_at"] == "2026-06-01T00:00:00Z"
        assert "ends_at" not in body
        assert calls[0]["method"] == "POST"

    def test_update_promo_rule_enabled_toggle(self, mock_mc_request) -> None:
        calls = mock_mc_request({"id": "rule_1", "enabled": False, "updated_at": "2026-05-17T00:00:00Z"})
        server.update_promo_rule(store_id="store_a", promo_rule_id="rule_1", enabled=False)
        body = calls[0]["body"]
        assert body == {"enabled": False}
        assert calls[0]["method"] == "PATCH"

    def test_delete_promo_rule(self, mock_mc_request) -> None:
        calls = mock_mc_request({"status": "success"})
        payload = json.loads(server.delete_promo_rule(store_id="store_a", promo_rule_id="rule_1"))
        assert payload["status"] == "deleted"
        assert calls[0]["method"] == "DELETE"


class TestEcommercePromoCodesCRUD:
    def test_list_promo_codes(self, mock_mc_request) -> None:
        mock_mc_request(
            {
                "total_items": 1,
                "promo_codes": [
                    {
                        "id": "code_1",
                        "code": "SUMMER20",
                        "redemption_url": "https://shop.example/checkout",
                        "usage_count": 12,
                        "enabled": True,
                    }
                ],
            }
        )
        payload = json.loads(
            server.list_promo_codes(store_id="store_a", promo_rule_id="rule_1")
        )
        assert payload["promo_codes"][0]["code"] == "SUMMER20"
        assert payload["promo_codes"][0]["usage_count"] == 12

    def test_get_promo_code(self, mock_mc_request) -> None:
        mock_mc_request({"id": "code_1", "code": "SUMMER20", "usage_count": 12, "enabled": True})
        payload = json.loads(
            server.get_promo_code(store_id="store_a", promo_rule_id="rule_1", promo_code_id="code_1")
        )
        assert payload["code"] == "SUMMER20"

    def test_create_promo_code(self, mock_mc_request) -> None:
        calls = mock_mc_request(
            {
                "id": "code_42",
                "code": "VIP25",
                "redemption_url": "https://shop.example/checkout",
                "usage_count": 0,
                "enabled": True,
                "created_at": "2026-05-16T00:00:00Z",
            }
        )
        server.create_promo_code(
            store_id="store_a",
            promo_rule_id="rule_1",
            promo_code_id="code_42",
            code="VIP25",
            redemption_url="https://shop.example/checkout",
        )
        body = calls[0]["body"]
        assert body["id"] == "code_42"
        assert body["code"] == "VIP25"
        assert body["enabled"] is True
        assert calls[0]["endpoint"] == "/ecommerce/stores/store_a/promo-rules/rule_1/promo-codes"

    def test_update_promo_code_disable(self, mock_mc_request) -> None:
        calls = mock_mc_request({"id": "code_1", "enabled": False})
        server.update_promo_code(
            store_id="store_a", promo_rule_id="rule_1", promo_code_id="code_1", enabled=False
        )
        assert calls[0]["body"] == {"enabled": False}
        assert calls[0]["method"] == "PATCH"

    def test_delete_promo_code(self, mock_mc_request) -> None:
        calls = mock_mc_request({"status": "success"})
        payload = json.loads(
            server.delete_promo_code(store_id="store_a", promo_rule_id="rule_1", promo_code_id="code_1")
        )
        assert payload["status"] == "deleted"
        assert payload["promo_code_id"] == "code_1"
        assert calls[0]["method"] == "DELETE"


class TestAutomationCoverage:
    EMAIL = "jane@example.com"
    HASH = "9e26471d35a78862c17e467d87cddedf"

    def test_search_automation_campaigns_forces_type_filter(self, mock_mc_request) -> None:
        calls = mock_mc_request({"total_items": 0, "campaigns": []})
        server.search_automation_campaigns(count=50)
        params = calls[0]["params"]
        assert params["type"] == "automation"
        assert params["count"] == 50
        assert "list_id" not in params
        assert "since_send_time" not in params

    def test_search_automation_campaigns_threads_optional_filters(self, mock_mc_request) -> None:
        calls = mock_mc_request(
            {
                "total_items": 1,
                "campaigns": [
                    {
                        "id": "cam_1",
                        "status": "sent",
                        "settings": {"title": "Welcome day 1", "subject_line": "Welcome"},
                        "send_time": "2026-05-01T10:00:00Z",
                        "emails_sent": 1200,
                        "recipients": {"list_id": "list_a", "list_name": "Main"},
                    }
                ],
            }
        )
        server.search_automation_campaigns(
            list_id="list_a",
            status="sent",
            since_send_time="2026-04-01T00:00:00Z",
            before_send_time="2026-06-01T00:00:00Z",
        )
        params = calls[0]["params"]
        assert params["type"] == "automation"
        assert params["list_id"] == "list_a"
        assert params["status"] == "sent"
        assert params["since_send_time"] == "2026-04-01T00:00:00Z"
        assert params["before_send_time"] == "2026-06-01T00:00:00Z"

    def test_get_member_journey_events_filters_activity_feed(self, mock_mc_request) -> None:
        calls = mock_mc_request(
            {
                "activity": [
                    {"action": "automation_email_sent", "timestamp": "2026-05-01T10:00:00Z", "title": "Welcome", "campaign_id": "cam_1"},
                    {"action": "open", "timestamp": "2026-05-01T11:00:00Z", "title": "Welcome", "campaign_id": "cam_1"},
                    {"action": "journey_step_entered", "timestamp": "2026-05-02T09:00:00Z", "title": "Onboarding"},
                    {"action": "click", "url": "https://example.com", "timestamp": "2026-05-02T10:00:00Z"},
                ]
            }
        )
        payload = json.loads(server.get_member_journey_events(list_id="abc", email_address=self.EMAIL))
        assert payload["scanned"] == 4
        assert payload["total_journey_events"] == 2
        actions = [e["action"] for e in payload["events"]]
        assert "automation_email_sent" in actions
        assert "journey_step_entered" in actions
        assert "open" not in actions
        assert "click" not in actions
        assert calls[0]["endpoint"] == f"/lists/abc/members/{self.HASH}/activity-feed"

    def test_get_automation_summary_combines_two_calls(self, mock_mc_request) -> None:
        calls = mock_mc_request([
            {
                "total_items": 4,
                "automations": [
                    {"id": "a1", "status": "sending"},
                    {"id": "a2", "status": "sending"},
                    {"id": "a3", "status": "paused"},
                    {"id": "a4", "status": "save"},
                ],
            },
            {
                "total_items": 2,
                "campaigns": [
                    {"settings": {"title": "Welcome day 1"}, "emails_sent": 4200},
                    {"settings": {"title": "Welcome day 3"}, "emails_sent": 1800},
                ],
            },
        ])
        payload = json.loads(server.get_automation_summary(days=14))

        assert payload["classic_automations"]["total"] == 4
        assert payload["classic_automations"]["by_status"]["sending"] == 2
        assert payload["classic_automations"]["by_status"]["paused"] == 1
        assert payload["classic_automations"]["by_status"]["save"] == 1

        recent = payload["recent_automation_campaigns"]
        assert recent["window_days"] == 14
        assert recent["total_campaigns"] == 2
        assert recent["total_emails_sent"] == 6000
        assert recent["top_titles"][0]["title"] == "Welcome day 1"
        assert recent["top_titles"][0]["emails_sent"] == 4200

        assert len(calls) == 2
        assert calls[0]["endpoint"] == "/automations"
        assert calls[1]["endpoint"] == "/campaigns"
        assert calls[1]["params"]["type"] == "automation"
        assert "since_send_time" in calls[1]["params"]


class TestAccounts:
    def test_list_accounts_lists_default_and_named_without_secrets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(server, "MAILCHIMP_API_KEY", "supersecret-us1")
        monkeypatch.setattr(server, "READ_ONLY", False)
        monkeypatch.setattr(server, "DRY_RUN", False)
        monkeypatch.setattr(
            server,
            "MAILCHIMP_ACCOUNTS",
            {"tts": {"api_key": "ttssecret-us7", "dc": "us7", "base_url": "x", "read_only": True, "dry_run": False}},
        )
        result = server.list_accounts()
        payload = _parse(result)

        names = {a["name"]: a for a in payload["accounts"]}
        assert names["default"]["is_default"] is True
        assert names["default"]["read_only"] is False
        assert names["tts"]["read_only"] is True
        assert names["tts"]["is_default"] is False
        # never leak key material
        assert "supersecret" not in result
        assert "ttssecret" not in result

    def test_list_accounts_omits_default_when_no_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(server, "MAILCHIMP_API_KEY", "")
        monkeypatch.setattr(server, "MAILCHIMP_ACCOUNTS", {"tts": {"read_only": False, "dry_run": False}})
        payload = _parse(server.list_accounts())
        assert [a["name"] for a in payload["accounts"]] == ["tts"]

    def test_read_tool_routes_to_named_account_dc(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            server,
            "MAILCHIMP_ACCOUNTS",
            {"foo": {"api_key": "fookey-us9", "dc": "us9", "base_url": "https://us9.api.mailchimp.com/3.0", "read_only": False, "dry_run": False}},
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {"lists": [], "total_items": 0}
        with patch.object(requests.Session, "request", return_value=mock_resp) as mock_req:
            server.list_audiences(account="foo")
        assert mock_req.call_args.args[1].startswith("https://us9.api.mailchimp.com/3.0/")
        assert mock_req.call_args.kwargs["auth"] == ("anystring", "fookey-us9")


class TestFileManager:
    def test_list_files_extracts_fields(self, mock_mc_request) -> None:
        calls = mock_mc_request(
            {
                "total_items": 1,
                "files": [
                    {
                        "id": 7,
                        "name": "hero.png",
                        "type": "image",
                        "full_size_url": "https://cdn/hero.png",
                        "thumbnail_url": "https://cdn/t.png",
                        "size": 1024,
                        "width": 600,
                        "height": 400,
                        "folder_id": 3,
                        "created_at": "2024-01-01T00:00:00Z",
                        "created_by": "user",
                    }
                ],
            }
        )
        payload = _parse(server.list_files(type="image"))
        assert payload["total_items"] == 1
        assert payload["files"][0]["id"] == 7
        assert payload["files"][0]["full_size_url"].endswith("hero.png")
        assert calls[0]["params"]["type"] == "image"

    def test_upload_file_dispatch(self, mock_mc_request) -> None:
        calls = mock_mc_request(
            {
                "id": 9,
                "name": "a.png",
                "type": "image",
                "full_size_url": "u",
                "thumbnail_url": "t",
                "size": 1,
                "width": 1,
                "height": 1,
                "folder_id": 3,
                "created_at": "z",
            }
        )
        payload = _parse(server.upload_file(name="a.png", file_data="Zm9v", folder_id="3"))
        assert payload["id"] == 9
        assert calls[0]["method"] == "POST"
        assert calls[0]["endpoint"] == "/file-manager/files"
        assert calls[0]["body"]["file_data"] == "Zm9v"
        assert calls[0]["body"]["folder_id"] == 3

    def test_delete_file_dispatch(self, mock_mc_request) -> None:
        calls = mock_mc_request({"status": "success"})
        payload = _parse(server.delete_file(file_id="7"))
        assert payload["status"] == "success"
        assert calls[0]["method"] == "DELETE"
        assert calls[0]["endpoint"] == "/file-manager/files/7"

    def test_list_file_folders_extracts_fields(self, mock_mc_request) -> None:
        mock_mc_request(
            {"total_items": 1, "folders": [{"id": 3, "name": "Campaigns", "file_count": 12, "created_at": "z", "created_by": "u"}]}
        )
        payload = _parse(server.list_file_folders())
        assert payload["folders"][0]["id"] == 3
        assert payload["folders"][0]["file_count"] == 12


class TestSurveys:
    def test_list_surveys_dispatch(self, mock_mc_request) -> None:
        calls = mock_mc_request(
            {"total_items": 1, "surveys": [{"id": "s1", "title": "NPS", "status": "published", "url": "https://x"}]}
        )
        payload = _parse(server.list_surveys(list_id="abc"))
        assert payload["surveys"][0]["id"] == "s1"
        assert calls[0]["endpoint"] == "/lists/abc/surveys"

    def test_publish_survey_dispatch(self, mock_mc_request) -> None:
        calls = mock_mc_request({"status": "success"})
        payload = _parse(server.publish_survey(list_id="abc", survey_id="s1"))
        assert payload["status"] == "published"
        assert calls[0]["method"] == "POST"
        assert calls[0]["endpoint"] == "/lists/abc/surveys/s1/actions/publish"

    def test_unpublish_survey_dispatch(self, mock_mc_request) -> None:
        calls = mock_mc_request({"status": "success"})
        payload = _parse(server.unpublish_survey(list_id="abc", survey_id="s1"))
        assert payload["status"] == "unpublished"
        assert calls[0]["endpoint"] == "/lists/abc/surveys/s1/actions/unpublish"


class TestSignupForms:
    def test_list_signup_forms_dispatch(self, mock_mc_request) -> None:
        calls = mock_mc_request(
            {"signup_forms": [{"signup_form_url": "https://x", "header": {}, "contents": [], "styles": []}]}
        )
        payload = _parse(server.list_signup_forms(list_id="abc"))
        assert payload["signup_forms"][0]["signup_form_url"] == "https://x"
        assert calls[0]["endpoint"] == "/lists/abc/signup-forms"

    def test_customize_signup_form_dispatch(self, mock_mc_request) -> None:
        calls = mock_mc_request({"signup_forms": []})
        server.customize_signup_form(
            list_id="abc", contents=[{"section": "signup_message", "value": "<p>Hi</p>"}]
        )
        assert calls[0]["method"] == "POST"
        assert calls[0]["endpoint"] == "/lists/abc/signup-forms"
        assert calls[0]["body"]["contents"][0]["section"] == "signup_message"

    def test_customize_signup_form_requires_a_field(self, mock_mc_request) -> None:
        calls = mock_mc_request({"signup_forms": []})
        payload = _parse(server.customize_signup_form(list_id="abc"))
        assert "error" in payload
        assert calls == [], "no request should be dispatched when nothing is provided"

    def test_upload_file_dry_run_previews(self, monkeypatch: pytest.MonkeyPatch, mock_mc_request) -> None:
        monkeypatch.setattr(server, "DRY_RUN", True)
        calls = mock_mc_request({"should": "not-be-called"})
        payload = _parse(server.upload_file(name="a.png", file_data="Zm9v"))
        assert payload["dry_run"] is True
        assert payload["action"] == "upload file"
        assert "file_data" not in payload, "raw file data must not leak into the dry-run preview"
        assert calls == []


class TestVerifiedDomains:
    def test_list_verified_domains_dispatch(self, mock_mc_request) -> None:
        calls = mock_mc_request({"domains": [], "total_items": 0})
        server.list_verified_domains()
        assert calls[0]["endpoint"] == "/verified-domains"

    def test_verify_verified_domain_dispatch(self, mock_mc_request) -> None:
        calls = mock_mc_request({"verified": True})
        server.verify_verified_domain(domain_name="mail.example.com", code="123456")
        assert calls[0]["method"] == "POST"
        assert calls[0]["endpoint"] == "/verified-domains/mail.example.com/actions/verify"
        assert calls[0]["body"]["code"] == "123456"


class TestFoldersAndChecklist:
    def test_create_campaign_folder_dispatch(self, mock_mc_request) -> None:
        calls = mock_mc_request({"id": "f1", "name": "Q3"})
        server.create_campaign_folder(name="Q3")
        assert calls[0]["method"] == "POST"
        assert calls[0]["endpoint"] == "/campaign-folders"
        assert calls[0]["body"]["name"] == "Q3"

    def test_send_checklist_dispatch(self, mock_mc_request) -> None:
        calls = mock_mc_request({"is_ready": True, "items": []})
        payload = _parse(server.get_campaign_send_checklist(campaign_id="c1"))
        assert payload["is_ready"] is True
        assert calls[0]["endpoint"] == "/campaigns/c1/send-checklist"


class TestMemberComplianceAndUpsert:
    def test_delete_member_permanent_dispatch(self, mock_mc_request) -> None:
        calls = mock_mc_request({"status": "success"})
        server.delete_member_permanent(list_id="abc", email_address="A@B.com")
        assert calls[0]["method"] == "POST"
        assert calls[0]["endpoint"].endswith("/actions/delete-permanent")

    def test_upsert_member_uses_put(self, mock_mc_request) -> None:
        calls = mock_mc_request({"id": "h", "email_address": "a@b.com", "status": "subscribed"})
        server.upsert_member(list_id="abc", email_address="a@b.com", merge_fields={"FNAME": "Ada"})
        assert calls[0]["method"] == "PUT"
        assert calls[0]["body"]["status_if_new"] == "subscribed"
        assert calls[0]["body"]["merge_fields"]["FNAME"] == "Ada"

    def test_delete_member_permanent_dry_run(self, monkeypatch, mock_mc_request) -> None:
        monkeypatch.setattr(server, "DRY_RUN", True)
        calls = mock_mc_request({"should": "not-be-called"})
        payload = _parse(server.delete_member_permanent(list_id="abc", email_address="a@b.com"))
        assert payload["dry_run"] is True
        assert payload["action"] == "permanently delete member"
        assert calls == []


class TestBatchWebhooks:
    def test_create_batch_webhook_dispatch(self, mock_mc_request) -> None:
        calls = mock_mc_request({"id": "bw1", "url": "https://x", "enabled": True})
        server.create_batch_webhook(url="https://x")
        assert calls[0]["method"] == "POST"
        assert calls[0]["endpoint"] == "/batch-webhooks"


class TestAutomationEmailControl:
    def test_pause_automation_email_dispatch(self, mock_mc_request) -> None:
        calls = mock_mc_request({"status": "success"})
        server.pause_automation_email(workflow_id="w1", workflow_email_id="e1")
        assert calls[0]["method"] == "POST"
        assert calls[0]["endpoint"] == "/automations/w1/emails/e1/actions/pause"


class TestReportingExtras:
    def test_survey_responses_dispatch(self, mock_mc_request) -> None:
        calls = mock_mc_request({"responses": [], "total_items": 0})
        server.get_survey_responses(survey_id="s1")
        assert calls[0]["endpoint"] == "/reporting/surveys/s1/responses"

    def test_landing_page_reports_dispatch(self, mock_mc_request) -> None:
        calls = mock_mc_request({"landing_pages": [], "total_items": 0})
        server.list_landing_page_reports()
        assert calls[0]["endpoint"] == "/reporting/landing-pages"


class TestEcommerceWrites:
    def test_create_store_dispatch(self, mock_mc_request) -> None:
        calls = mock_mc_request({"id": "s1", "name": "Shop"})
        server.create_store(store_id="s1", name="Shop", currency_code="USD", additional_fields={"list_id": "abc"})
        assert calls[0]["method"] == "POST"
        assert calls[0]["endpoint"] == "/ecommerce/stores"
        assert calls[0]["body"]["currency_code"] == "USD"
        assert calls[0]["body"]["list_id"] == "abc"

    def test_create_store_order_dispatch(self, mock_mc_request) -> None:
        calls = mock_mc_request({"id": "o1"})
        server.create_store_order(store_id="s1", order_id="o1", customer={"id": "c1"}, lines=[{"id": "l1"}])
        assert calls[0]["method"] == "POST"
        assert calls[0]["endpoint"] == "/ecommerce/stores/s1/orders"
        assert calls[0]["body"]["customer"]["id"] == "c1"

    def test_delete_store_dry_run(self, monkeypatch, mock_mc_request) -> None:
        monkeypatch.setattr(server, "DRY_RUN", True)
        calls = mock_mc_request({"should": "not-be-called"})
        payload = _parse(server.delete_store(store_id="s1"))
        assert payload["dry_run"] is True
        assert payload["action"] == "delete store"
        assert calls == []
