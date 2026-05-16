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
