import os
import json
import requests
from typing import Optional
from mcp.server.fastmcp import FastMCP

# --- Config ---
MAILCHIMP_API_KEY = os.environ.get("MAILCHIMP_API_KEY", "")
if not MAILCHIMP_API_KEY:
    raise ValueError(
        "MAILCHIMP_API_KEY environment variable is required. "
        "Get your API key at https://mailchimp.com/help/about-api-keys/"
    )

MAILCHIMP_DC = MAILCHIMP_API_KEY.split("-")[-1]
MAILCHIMP_BASE_URL = f"https://{MAILCHIMP_DC}.api.mailchimp.com/3.0"

mcp = FastMCP("mailchimp-mcp-server")


# --- Helper ---

def mc_request(endpoint: str, params: Optional[dict] = None, body: Optional[dict] = None, method: str = "GET") -> dict:
    """Make an authenticated request to the Mailchimp API."""
    url = f"{MAILCHIMP_BASE_URL}/{endpoint.lstrip('/')}"
    auth = ("anystring", MAILCHIMP_API_KEY)
    resp = requests.request(method, url, auth=auth, params=params, json=body, timeout=30)
    resp.raise_for_status()
    if resp.status_code == 204:
        return {"status": "success"}
    return resp.json()


# --- Tools ---

@mcp.tool()
def get_account_info() -> str:
    """Get Mailchimp account information (name, contact, stats)."""
    data = mc_request("/")
    return json.dumps({
        "account_name": data.get("account_name"),
        "email": data.get("email"),
        "first_name": data.get("first_name"),
        "last_name": data.get("last_name"),
        "total_subscribers": data.get("total_subscribers"),
        "industry_stats": data.get("industry_stats"),
    }, indent=2)


@mcp.tool()
def list_audiences(count: int = 10, offset: int = 0) -> str:
    """List all audiences/lists in the Mailchimp account.

    Args:
        count: Number of audiences to return (default 10).
        offset: Pagination offset.
    """
    data = mc_request("/lists", params={"count": count, "offset": offset})
    audiences = []
    for lst in data.get("lists", []):
        audiences.append({
            "id": lst["id"],
            "name": lst["name"],
            "member_count": lst["stats"]["member_count"],
            "unsubscribe_count": lst["stats"]["unsubscribe_count"],
            "open_rate": lst["stats"]["open_rate"],
            "click_rate": lst["stats"]["click_rate"],
            "date_created": lst["date_created"],
        })
    return json.dumps({"total_items": data.get("total_items"), "audiences": audiences}, indent=2)


@mcp.tool()
def get_audience_details(list_id: str) -> str:
    """Get detailed information about a specific audience/list.

    Args:
        list_id: The Mailchimp audience/list ID.
    """
    data = mc_request(f"/lists/{list_id}")
    return json.dumps({
        "id": data["id"],
        "name": data["name"],
        "stats": data.get("stats"),
        "date_created": data.get("date_created"),
        "list_rating": data.get("list_rating"),
        "subscribe_url_short": data.get("subscribe_url_short"),
    }, indent=2)


@mcp.tool()
def list_campaigns(count: int = 20, offset: int = 0, status: Optional[str] = None, since_send_time: Optional[str] = None) -> str:
    """List campaigns in the Mailchimp account.

    Args:
        count: Number of campaigns to return (default 20).
        offset: Pagination offset.
        status: Filter by status: 'save', 'paused', 'schedule', 'sending', 'sent'.
        since_send_time: Filter campaigns sent after this date (ISO 8601, e.g. '2025-01-01T00:00:00Z').
    """
    params = {"count": count, "offset": offset}
    if status:
        params["status"] = status
    if since_send_time:
        params["since_send_time"] = since_send_time
    data = mc_request("/campaigns", params=params)
    campaigns = []
    for c in data.get("campaigns", []):
        campaigns.append({
            "id": c["id"],
            "type": c.get("type"),
            "status": c.get("status"),
            "title": c.get("settings", {}).get("title"),
            "subject_line": c.get("settings", {}).get("subject_line"),
            "preview_text": c.get("settings", {}).get("preview_text"),
            "send_time": c.get("send_time"),
            "emails_sent": c.get("emails_sent"),
            "list_id": c.get("recipients", {}).get("list_id"),
            "list_name": c.get("recipients", {}).get("list_name"),
        })
    return json.dumps({"total_items": data.get("total_items"), "campaigns": campaigns}, indent=2)


@mcp.tool()
def get_campaign_details(campaign_id: str) -> str:
    """Get detailed information about a specific campaign.

    Args:
        campaign_id: The Mailchimp campaign ID.
    """
    data = mc_request(f"/campaigns/{campaign_id}")
    return json.dumps({
        "id": data["id"],
        "type": data.get("type"),
        "status": data.get("status"),
        "settings": data.get("settings"),
        "recipients": data.get("recipients"),
        "send_time": data.get("send_time"),
        "emails_sent": data.get("emails_sent"),
        "tracking": data.get("tracking"),
    }, indent=2)


@mcp.tool()
def get_campaign_report(campaign_id: str) -> str:
    """Get performance report for a sent campaign (opens, clicks, bounces, etc.).

    Args:
        campaign_id: The Mailchimp campaign ID.
    """
    data = mc_request(f"/reports/{campaign_id}")
    return json.dumps({
        "campaign_title": data.get("campaign_title"),
        "subject_line": data.get("subject_line"),
        "emails_sent": data.get("emails_sent"),
        "abuse_reports": data.get("abuse_reports"),
        "unsubscribed": data.get("unsubscribed"),
        "send_time": data.get("send_time"),
        "opens": data.get("opens"),
        "clicks": data.get("clicks"),
        "bounces": data.get("bounces"),
        "forwards": data.get("forwards"),
        "list_stats": data.get("list_stats"),
        "industry_stats": data.get("industry_stats"),
    }, indent=2)


@mcp.tool()
def get_campaign_click_details(campaign_id: str, count: int = 20) -> str:
    """Get click details for a campaign (which links were clicked and how many times).

    Args:
        campaign_id: The Mailchimp campaign ID.
        count: Number of URL results to return.
    """
    data = mc_request(f"/reports/{campaign_id}/click-details", params={"count": count})
    links = []
    for url_report in data.get("urls_clicked", []):
        links.append({
            "url": url_report.get("url"),
            "total_clicks": url_report.get("total_clicks"),
            "unique_clicks": url_report.get("unique_clicks"),
            "click_percentage": url_report.get("click_percentage"),
        })
    return json.dumps({"total_items": data.get("total_items"), "links": links}, indent=2)


@mcp.tool()
def list_audience_members(list_id: str, count: int = 20, offset: int = 0, status: Optional[str] = None) -> str:
    """List members of a specific audience/list.

    Args:
        list_id: The Mailchimp audience/list ID.
        count: Number of members to return (default 20).
        offset: Pagination offset.
        status: Filter by status: 'subscribed', 'unsubscribed', 'cleaned', 'pending', 'transactional'.
    """
    params = {"count": count, "offset": offset}
    if status:
        params["status"] = status
    data = mc_request(f"/lists/{list_id}/members", params=params)
    members = []
    for m in data.get("members", []):
        members.append({
            "id": m["id"],
            "email_address": m["email_address"],
            "status": m["status"],
            "full_name": m.get("full_name"),
            "merge_fields": m.get("merge_fields"),
            "open_rate": m.get("stats", {}).get("avg_open_rate"),
            "click_rate": m.get("stats", {}).get("avg_click_rate"),
            "timestamp_opt": m.get("timestamp_opt"),
        })
    return json.dumps({"total_items": data.get("total_items"), "members": members}, indent=2)


@mcp.tool()
def search_members(query: str, list_id: Optional[str] = None) -> str:
    """Search for members across audiences by email or name.

    Args:
        query: Search query (email address or name).
        list_id: Optional audience/list ID to restrict search.
    """
    params = {"query": query}
    if list_id:
        params["list_id"] = list_id
    data = mc_request("/search-members", params=params)
    results = []
    for match in data.get("exact_matches", {}).get("members", []):
        results.append({
            "email": match["email_address"],
            "status": match["status"],
            "full_name": match.get("full_name"),
            "list_id": match.get("list_id"),
        })
    for match in data.get("full_search", {}).get("members", []):
        results.append({
            "email": match["email_address"],
            "status": match["status"],
            "full_name": match.get("full_name"),
            "list_id": match.get("list_id"),
        })
    return json.dumps({"results": results}, indent=2)


@mcp.tool()
def get_audience_growth_history(list_id: str, count: int = 12) -> str:
    """Get monthly growth history for an audience (subscribes, unsubscribes, etc.).

    Args:
        list_id: The Mailchimp audience/list ID.
        count: Number of months to return (default 12).
    """
    data = mc_request(f"/lists/{list_id}/growth-history", params={"count": count})
    history = []
    for h in data.get("history", []):
        history.append({
            "month": h.get("month"),
            "subscribed": h.get("subscribed"),
            "unsubscribed": h.get("unsubscribed"),
            "reconfirm": h.get("reconfirm"),
            "cleaned": h.get("cleaned"),
            "pending": h.get("pending"),
            "transactional": h.get("transactional"),
        })
    return json.dumps({"list_id": list_id, "history": history}, indent=2)


@mcp.tool()
def list_automations(count: int = 20, offset: int = 0) -> str:
    """List automations (automated email workflows) in the account.

    Args:
        count: Number of automations to return.
        offset: Pagination offset.
    """
    data = mc_request("/automations", params={"count": count, "offset": offset})
    automations = []
    for a in data.get("automations", []):
        automations.append({
            "id": a["id"],
            "status": a.get("status"),
            "title": a.get("settings", {}).get("title"),
            "emails_sent": a.get("emails_sent"),
            "start_time": a.get("start_time"),
            "create_time": a.get("create_time"),
            "list_id": a.get("recipients", {}).get("list_id"),
        })
    return json.dumps({"total_items": data.get("total_items"), "automations": automations}, indent=2)


@mcp.tool()
def list_templates(count: int = 20, offset: int = 0) -> str:
    """List email templates available in the account.

    Args:
        count: Number of templates to return.
        offset: Pagination offset.
    """
    data = mc_request("/templates", params={"count": count, "offset": offset})
    templates = []
    for t in data.get("templates", []):
        templates.append({
            "id": t["id"],
            "name": t["name"],
            "type": t.get("type"),
            "date_created": t.get("date_created"),
            "active": t.get("active"),
        })
    return json.dumps({"total_items": data.get("total_items"), "templates": templates}, indent=2)


@mcp.tool()
def list_segments(list_id: str, count: int = 20, offset: int = 0) -> str:
    """List segments/tags for a specific audience.

    Args:
        list_id: The Mailchimp audience/list ID.
        count: Number of segments to return.
        offset: Pagination offset.
    """
    data = mc_request(f"/lists/{list_id}/segments", params={"count": count, "offset": offset})
    segments = []
    for s in data.get("segments", []):
        segments.append({
            "id": s["id"],
            "name": s["name"],
            "member_count": s.get("member_count"),
            "type": s.get("type"),
            "created_at": s.get("created_at"),
            "updated_at": s.get("updated_at"),
        })
    return json.dumps({"total_items": data.get("total_items"), "segments": segments}, indent=2)


# --- Write Tools: Members ---

@mcp.tool()
def add_member(list_id: str, email_address: str, status: str = "subscribed", first_name: Optional[str] = None, last_name: Optional[str] = None, tags: Optional[str] = None) -> str:
    """Add a new member to an audience.

    Args:
        list_id: The Mailchimp audience/list ID.
        email_address: Email address of the new member.
        status: Subscription status: 'subscribed', 'unsubscribed', 'cleaned', 'pending'.
        first_name: First name (optional).
        last_name: Last name (optional).
        tags: Comma-separated list of tags to apply (optional).
    """
    body: dict = {"email_address": email_address, "status": status}
    merge_fields = {}
    if first_name:
        merge_fields["FNAME"] = first_name
    if last_name:
        merge_fields["LNAME"] = last_name
    if merge_fields:
        body["merge_fields"] = merge_fields
    if tags:
        body["tags"] = [t.strip() for t in tags.split(",")]
    data = mc_request(f"/lists/{list_id}/members", body=body, method="POST")
    return json.dumps({
        "id": data.get("id"),
        "email_address": data.get("email_address"),
        "status": data.get("status"),
        "full_name": data.get("full_name"),
    }, indent=2)


@mcp.tool()
def update_member(list_id: str, email_address: str, status: Optional[str] = None, first_name: Optional[str] = None, last_name: Optional[str] = None) -> str:
    """Update an existing member in an audience.

    Args:
        list_id: The Mailchimp audience/list ID.
        email_address: Email address of the member to update.
        status: New status: 'subscribed', 'unsubscribed', 'cleaned', 'pending'.
        first_name: New first name.
        last_name: New last name.
    """
    import hashlib
    subscriber_hash = hashlib.md5(email_address.lower().encode()).hexdigest()
    body: dict = {}
    if status:
        body["status"] = status
    merge_fields = {}
    if first_name is not None:
        merge_fields["FNAME"] = first_name
    if last_name is not None:
        merge_fields["LNAME"] = last_name
    if merge_fields:
        body["merge_fields"] = merge_fields
    data = mc_request(f"/lists/{list_id}/members/{subscriber_hash}", body=body, method="PATCH")
    return json.dumps({
        "id": data.get("id"),
        "email_address": data.get("email_address"),
        "status": data.get("status"),
        "full_name": data.get("full_name"),
    }, indent=2)


@mcp.tool()
def unsubscribe_member(list_id: str, email_address: str) -> str:
    """Unsubscribe a member from an audience.

    Args:
        list_id: The Mailchimp audience/list ID.
        email_address: Email address of the member to unsubscribe.
    """
    import hashlib
    subscriber_hash = hashlib.md5(email_address.lower().encode()).hexdigest()
    data = mc_request(f"/lists/{list_id}/members/{subscriber_hash}", body={"status": "unsubscribed"}, method="PATCH")
    return json.dumps({
        "email_address": data.get("email_address"),
        "status": data.get("status"),
    }, indent=2)


@mcp.tool()
def delete_member(list_id: str, email_address: str) -> str:
    """Permanently delete a member from an audience. This cannot be undone.

    Args:
        list_id: The Mailchimp audience/list ID.
        email_address: Email address of the member to permanently delete.
    """
    import hashlib
    subscriber_hash = hashlib.md5(email_address.lower().encode()).hexdigest()
    mc_request(f"/lists/{list_id}/members/{subscriber_hash}/actions/delete-permanent", method="POST")
    return json.dumps({"status": "permanently_deleted", "email_address": email_address}, indent=2)


@mcp.tool()
def tag_member(list_id: str, email_address: str, tags_to_add: Optional[str] = None, tags_to_remove: Optional[str] = None) -> str:
    """Add or remove tags from a member.

    Args:
        list_id: The Mailchimp audience/list ID.
        email_address: Email address of the member.
        tags_to_add: Comma-separated tags to add (optional).
        tags_to_remove: Comma-separated tags to remove (optional).
    """
    import hashlib
    subscriber_hash = hashlib.md5(email_address.lower().encode()).hexdigest()
    tags = []
    if tags_to_add:
        for t in tags_to_add.split(","):
            tags.append({"name": t.strip(), "status": "active"})
    if tags_to_remove:
        for t in tags_to_remove.split(","):
            tags.append({"name": t.strip(), "status": "inactive"})
    mc_request(f"/lists/{list_id}/members/{subscriber_hash}/tags", body={"tags": tags}, method="POST")
    return json.dumps({"status": "updated", "email_address": email_address, "tags": tags}, indent=2)


# --- Write Tools: Campaigns ---

@mcp.tool()
def create_campaign(list_id: str, subject_line: str, title: Optional[str] = None, preview_text: Optional[str] = None, from_name: Optional[str] = None, reply_to: Optional[str] = None) -> str:
    """Create a new campaign draft (regular email).

    Args:
        list_id: The audience/list ID to send to.
        subject_line: The subject line of the email.
        title: Internal title for the campaign (defaults to subject_line).
        preview_text: Preview text shown in inbox.
        from_name: The 'from' name on the email.
        reply_to: The reply-to email address.
    """
    settings: dict = {"subject_line": subject_line, "title": title or subject_line}
    if preview_text:
        settings["preview_text"] = preview_text
    if from_name:
        settings["from_name"] = from_name
    if reply_to:
        settings["reply_to"] = reply_to
    body = {
        "type": "regular",
        "recipients": {"list_id": list_id},
        "settings": settings,
    }
    data = mc_request("/campaigns", body=body, method="POST")
    return json.dumps({
        "id": data.get("id"),
        "status": data.get("status"),
        "title": data.get("settings", {}).get("title"),
        "subject_line": data.get("settings", {}).get("subject_line"),
        "web_id": data.get("web_id"),
    }, indent=2)


@mcp.tool()
def update_campaign(campaign_id: str, subject_line: Optional[str] = None, title: Optional[str] = None, preview_text: Optional[str] = None, from_name: Optional[str] = None, reply_to: Optional[str] = None) -> str:
    """Update settings of an existing campaign draft.

    Args:
        campaign_id: The campaign ID to update.
        subject_line: New subject line.
        title: New internal title.
        preview_text: New preview text.
        from_name: New 'from' name.
        reply_to: New reply-to email address.
    """
    settings: dict = {}
    if subject_line:
        settings["subject_line"] = subject_line
    if title:
        settings["title"] = title
    if preview_text:
        settings["preview_text"] = preview_text
    if from_name:
        settings["from_name"] = from_name
    if reply_to:
        settings["reply_to"] = reply_to
    data = mc_request(f"/campaigns/{campaign_id}", body={"settings": settings}, method="PATCH")
    return json.dumps({
        "id": data.get("id"),
        "status": data.get("status"),
        "settings": data.get("settings"),
    }, indent=2)


@mcp.tool()
def set_campaign_content(campaign_id: str, html: str) -> str:
    """Set the HTML content of a campaign draft.

    Args:
        campaign_id: The campaign ID.
        html: The full HTML content for the email body.
    """
    data = mc_request(f"/campaigns/{campaign_id}/content", body={"html": html}, method="PUT")
    return json.dumps({"status": "content_set", "campaign_id": campaign_id}, indent=2)


@mcp.tool()
def schedule_campaign(campaign_id: str, schedule_time: str) -> str:
    """Schedule a campaign for sending at a specific time. The campaign must have content set.

    Args:
        campaign_id: The campaign ID.
        schedule_time: ISO 8601 date/time for sending (e.g. '2025-06-15T14:00:00Z').
    """
    mc_request(f"/campaigns/{campaign_id}/actions/schedule", body={"schedule_time": schedule_time}, method="POST")
    return json.dumps({"status": "scheduled", "campaign_id": campaign_id, "schedule_time": schedule_time}, indent=2)


@mcp.tool()
def unschedule_campaign(campaign_id: str) -> str:
    """Unschedule a previously scheduled campaign (returns it to draft).

    Args:
        campaign_id: The campaign ID to unschedule.
    """
    mc_request(f"/campaigns/{campaign_id}/actions/unschedule", method="POST")
    return json.dumps({"status": "unscheduled", "campaign_id": campaign_id}, indent=2)


@mcp.tool()
def replicate_campaign(campaign_id: str) -> str:
    """Duplicate an existing campaign.

    Args:
        campaign_id: The campaign ID to replicate.
    """
    data = mc_request(f"/campaigns/{campaign_id}/actions/replicate", method="POST")
    return json.dumps({
        "id": data.get("id"),
        "status": data.get("status"),
        "title": data.get("settings", {}).get("title"),
        "web_id": data.get("web_id"),
    }, indent=2)


@mcp.tool()
def delete_campaign(campaign_id: str) -> str:
    """Delete a campaign. Only works on campaigns that haven't been sent.

    Args:
        campaign_id: The campaign ID to delete.
    """
    mc_request(f"/campaigns/{campaign_id}", method="DELETE")
    return json.dumps({"status": "deleted", "campaign_id": campaign_id}, indent=2)


# --- Write Tools: Tags & Segments ---

@mcp.tool()
def create_segment(list_id: str, name: str, static: bool = True) -> str:
    """Create a new segment (or tag) in an audience.

    Args:
        list_id: The Mailchimp audience/list ID.
        name: Name of the segment/tag.
        static: If True, creates a static segment (tag). If False, creates a saved segment.
    """
    body: dict = {"name": name}
    if static:
        body["static_segment"] = []
    data = mc_request(f"/lists/{list_id}/segments", body=body, method="POST")
    return json.dumps({
        "id": data.get("id"),
        "name": data.get("name"),
        "member_count": data.get("member_count"),
        "type": data.get("type"),
    }, indent=2)


@mcp.tool()
def delete_segment(list_id: str, segment_id: str) -> str:
    """Delete a segment/tag from an audience.

    Args:
        list_id: The Mailchimp audience/list ID.
        segment_id: The segment/tag ID to delete.
    """
    mc_request(f"/lists/{list_id}/segments/{segment_id}", method="DELETE")
    return json.dumps({"status": "deleted", "segment_id": segment_id}, indent=2)


@mcp.tool()
def add_members_to_segment(list_id: str, segment_id: str, emails: str) -> str:
    """Add members to a static segment/tag.

    Args:
        list_id: The Mailchimp audience/list ID.
        segment_id: The segment/tag ID.
        emails: Comma-separated list of email addresses to add.
    """
    email_list = [e.strip() for e in emails.split(",")]
    data = mc_request(
        f"/lists/{list_id}/segments/{segment_id}",
        body={"members_to_add": email_list},
        method="POST",
    )
    return json.dumps({
        "total_added": data.get("total_added"),
        "total_removed": data.get("total_removed"),
        "errors": data.get("errors", []),
    }, indent=2)


@mcp.tool()
def remove_members_from_segment(list_id: str, segment_id: str, emails: str) -> str:
    """Remove members from a static segment/tag.

    Args:
        list_id: The Mailchimp audience/list ID.
        segment_id: The segment/tag ID.
        emails: Comma-separated list of email addresses to remove.
    """
    email_list = [e.strip() for e in emails.split(",")]
    data = mc_request(
        f"/lists/{list_id}/segments/{segment_id}",
        body={"members_to_remove": email_list},
        method="POST",
    )
    return json.dumps({
        "total_added": data.get("total_added"),
        "total_removed": data.get("total_removed"),
        "errors": data.get("errors", []),
    }, indent=2)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
