"""Smoke tests covering one representative tool per family.

These tests do not enumerate every tool; they verify each major area is wired up
correctly and that response payloads are shaped as documented. The full set of
fields returned by Mailchimp is not asserted.
"""

from __future__ import annotations

import json

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
                    },
                ],
            }
        )
        payload = _parse(server.list_audiences(count=5))
        assert payload["total_items"] == 2
        assert payload["audiences"][0]["id"] == "list_a"
        assert payload["audiences"][0]["member_count"] == 100

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
