import os
import json
import hashlib
import requests
from typing import Optional
from mcp.server.fastmcp import FastMCP

# --- Config ---
MAILCHIMP_API_KEY = os.environ.get("MAILCHIMP_API_KEY", "")
MAILCHIMP_DC = MAILCHIMP_API_KEY.split("-")[-1] if "-" in MAILCHIMP_API_KEY else "us1"
MAILCHIMP_BASE_URL = f"https://{MAILCHIMP_DC}.api.mailchimp.com/3.0"
READ_ONLY = os.environ.get("MAILCHIMP_READ_ONLY", "").lower() in ("1", "true", "yes")
DRY_RUN = os.environ.get("MAILCHIMP_DRY_RUN", "").lower() in ("1", "true", "yes")

mcp = FastMCP("mailchimp-mcp-server")


# --- Helpers ---

def _guard_write(**context) -> Optional[str]:
    """Block writes in read-only mode, preview them in dry-run mode.

    Returns a JSON string to short-circuit the caller, or None to proceed.
    """
    if READ_ONLY:
        return json.dumps({"error": "Server is in read-only mode. Set MAILCHIMP_READ_ONLY=false to allow writes."}, indent=2)
    if DRY_RUN:
        return json.dumps({"dry_run": True, **context}, indent=2)
    return None


def mc_request(endpoint: str, params: Optional[dict] = None, body: Optional[dict] = None, method: str = "GET") -> dict:
    """Make an authenticated request to the Mailchimp API."""
    if not MAILCHIMP_API_KEY:
        return {"error": "MAILCHIMP_API_KEY environment variable is not set. Get your API key at https://mailchimp.com/help/about-api-keys/"}
    url = f"{MAILCHIMP_BASE_URL}/{endpoint.lstrip('/')}"
    auth = ("anystring", MAILCHIMP_API_KEY)
    try:
        resp = requests.request(method, url, auth=auth, params=params, json=body, timeout=30)
    except requests.exceptions.Timeout:
        return {"error": "Request timed out after 30 seconds", "endpoint": endpoint}
    except requests.exceptions.ConnectionError:
        return {"error": "Could not connect to Mailchimp API", "endpoint": endpoint}
    if resp.status_code == 204:
        return {"status": "success"}
    if not resp.ok:
        try:
            err = resp.json()
            return {
                "error": err.get("title", "API error"),
                "detail": err.get("detail", ""),
                "status": resp.status_code,
            }
        except Exception:
            return {"error": f"HTTP {resp.status_code}", "detail": resp.text[:500]}
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
    if (guard := _guard_write(action="add member", email_address=email_address, list_id=list_id, status=status)):
        return guard
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
    if (guard := _guard_write(action="update member", email_address=email_address, list_id=list_id)):
        return guard
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
    """Unsubscribe a member from an audience. The member will stop receiving campaigns.

    Args:
        list_id: The Mailchimp audience/list ID.
        email_address: Email address of the member to unsubscribe.
    """
    if (guard := _guard_write(action="unsubscribe member", email_address=email_address, list_id=list_id)):
        return guard
    subscriber_hash = hashlib.md5(email_address.lower().encode()).hexdigest()
    data = mc_request(f"/lists/{list_id}/members/{subscriber_hash}", body={"status": "unsubscribed"}, method="PATCH")
    return json.dumps({
        "email_address": data.get("email_address"),
        "status": data.get("status"),
    }, indent=2)


@mcp.tool()
def delete_member(list_id: str, email_address: str) -> str:
    """Permanently delete a member from an audience. This action is irreversible — the member's
    history, activity, and all associated data will be lost.

    Args:
        list_id: The Mailchimp audience/list ID.
        email_address: Email address of the member to permanently delete.
    """
    if (guard := _guard_write(action="permanently delete member", email_address=email_address, list_id=list_id)):
        return guard
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
    if (guard := _guard_write(action="update member tags", email_address=email_address, list_id=list_id)):
        return guard
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


# --- Write Tools: Audiences ---

@mcp.tool()
def batch_subscribe(list_id: str, members_json: str, update_existing: bool = True) -> str:
    """Batch add or update multiple members in an audience in a single request.

    Args:
        list_id: The Mailchimp audience/list ID.
        members_json: JSON string of members array. Each member needs at minimum: email_address, status.
            Example: '[{"email_address":"a@b.com","status":"subscribed","merge_fields":{"FNAME":"Alice"}}]'
        update_existing: If True, update members that already exist (default True).
    """
    if (guard := _guard_write(action="batch subscribe members", list_id=list_id)):
        return guard
    members = json.loads(members_json)
    body = {"members": members, "update_existing": update_existing}
    data = mc_request(f"/lists/{list_id}", body=body, method="POST")
    return json.dumps({
        "new_members": len(data.get("new_members", [])),
        "updated_members": len(data.get("updated_members", [])),
        "errors": data.get("errors", []),
        "total_created": data.get("total_created"),
        "total_updated": data.get("total_updated"),
        "error_count": data.get("error_count"),
    }, indent=2)


@mcp.tool()
def update_audience(list_id: str, name: Optional[str] = None, from_name: Optional[str] = None, from_email: Optional[str] = None, subject: Optional[str] = None, permission_reminder: Optional[str] = None) -> str:
    """Update audience settings (name, default from/subject, permission reminder).

    Args:
        list_id: The Mailchimp audience/list ID.
        name: New audience name.
        from_name: Default 'from' name for campaigns.
        from_email: Default 'from' email for campaigns.
        subject: Default email subject.
        permission_reminder: Permission reminder text shown to subscribers.
    """
    if (guard := _guard_write(action="update audience", list_id=list_id)):
        return guard
    body: dict = {}
    if name:
        body["name"] = name
    if permission_reminder:
        body["permission_reminder"] = permission_reminder
    campaign_defaults = {}
    if from_name:
        campaign_defaults["from_name"] = from_name
    if from_email:
        campaign_defaults["from_email"] = from_email
    if subject:
        campaign_defaults["subject"] = subject
    if campaign_defaults:
        body["campaign_defaults"] = campaign_defaults
    data = mc_request(f"/lists/{list_id}", body=body, method="PATCH")
    return json.dumps({
        "id": data.get("id"),
        "name": data.get("name"),
        "permission_reminder": data.get("permission_reminder"),
        "campaign_defaults": data.get("campaign_defaults"),
    }, indent=2)


# --- Write Tools: Campaigns ---

@mcp.tool()
def create_campaign(list_id: str, subject_line: str, title: Optional[str] = None, preview_text: Optional[str] = None, from_name: Optional[str] = None, reply_to: Optional[str] = None, segment_id: Optional[str] = None) -> str:
    """Create a new campaign draft (regular email), optionally targeting a specific segment.

    Args:
        list_id: The audience/list ID to send to.
        subject_line: The subject line of the email.
        title: Internal title for the campaign (defaults to subject_line).
        preview_text: Preview text shown in inbox.
        from_name: The 'from' name on the email.
        reply_to: The reply-to email address.
        segment_id: Optional saved segment ID to target. Only sends to members in this segment.
    """
    if (guard := _guard_write(action="create campaign draft", list_id=list_id, subject_line=subject_line)):
        return guard
    settings: dict = {"subject_line": subject_line, "title": title or subject_line}
    if preview_text:
        settings["preview_text"] = preview_text
    if from_name:
        settings["from_name"] = from_name
    if reply_to:
        settings["reply_to"] = reply_to
    recipients: dict = {"list_id": list_id}
    if segment_id:
        recipients["segment_opts"] = {"saved_segment_id": int(segment_id)}
    body = {
        "type": "regular",
        "recipients": recipients,
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
def update_campaign(campaign_id: str, subject_line: Optional[str] = None, title: Optional[str] = None, preview_text: Optional[str] = None, from_name: Optional[str] = None, reply_to: Optional[str] = None, list_id: Optional[str] = None, segment_id: Optional[str] = None) -> str:
    """Update settings or segment targeting of an existing campaign draft.

    Args:
        campaign_id: The campaign ID to update.
        subject_line: New subject line.
        title: New internal title.
        preview_text: New preview text.
        from_name: New 'from' name.
        reply_to: New reply-to email address.
        list_id: Audience/list ID (required if changing segment targeting).
        segment_id: Saved segment ID to target within the audience.
    """
    if (guard := _guard_write(action="update campaign", campaign_id=campaign_id)):
        return guard
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
    body: dict = {}
    if settings:
        body["settings"] = settings
    if list_id or segment_id:
        recipients: dict = {}
        if list_id:
            recipients["list_id"] = list_id
        if segment_id:
            recipients["segment_opts"] = {"saved_segment_id": int(segment_id)}
        body["recipients"] = recipients
    data = mc_request(f"/campaigns/{campaign_id}", body=body, method="PATCH")
    return json.dumps({
        "id": data.get("id"),
        "status": data.get("status"),
        "settings": data.get("settings"),
        "recipients": data.get("recipients"),
    }, indent=2)


@mcp.tool()
def set_campaign_content(campaign_id: str, html: str) -> str:
    """Set the HTML content of a campaign draft.

    Args:
        campaign_id: The campaign ID.
        html: The full HTML content for the email body.
    """
    if (guard := _guard_write(action="set campaign content", campaign_id=campaign_id)):
        return guard
    data = mc_request(f"/campaigns/{campaign_id}/content", body={"html": html}, method="PUT")
    return json.dumps({"status": "content_set", "campaign_id": campaign_id}, indent=2)


@mcp.tool()
def schedule_campaign(campaign_id: str, schedule_time: str) -> str:
    """Schedule a campaign for sending at a specific time. Once the scheduled time arrives,
    the campaign will be sent to all recipients in the audience. The campaign must have content set.

    Args:
        campaign_id: The campaign ID.
        schedule_time: ISO 8601 date/time for sending (e.g. '2025-06-15T14:00:00Z').
    """
    if (guard := _guard_write(action="schedule campaign", campaign_id=campaign_id, schedule_time=schedule_time)):
        return guard
    mc_request(f"/campaigns/{campaign_id}/actions/schedule", body={"schedule_time": schedule_time}, method="POST")
    return json.dumps({"status": "scheduled", "campaign_id": campaign_id, "schedule_time": schedule_time}, indent=2)


@mcp.tool()
def unschedule_campaign(campaign_id: str) -> str:
    """Unschedule a previously scheduled campaign (returns it to draft).

    Args:
        campaign_id: The campaign ID to unschedule.
    """
    if (guard := _guard_write(action="unschedule campaign", campaign_id=campaign_id)):
        return guard
    mc_request(f"/campaigns/{campaign_id}/actions/unschedule", method="POST")
    return json.dumps({"status": "unscheduled", "campaign_id": campaign_id}, indent=2)


@mcp.tool()
def replicate_campaign(campaign_id: str) -> str:
    """Duplicate an existing campaign.

    Args:
        campaign_id: The campaign ID to replicate.
    """
    if (guard := _guard_write(action="replicate campaign", campaign_id=campaign_id)):
        return guard
    data = mc_request(f"/campaigns/{campaign_id}/actions/replicate", method="POST")
    return json.dumps({
        "id": data.get("id"),
        "status": data.get("status"),
        "title": data.get("settings", {}).get("title"),
        "web_id": data.get("web_id"),
    }, indent=2)


@mcp.tool()
def delete_campaign(campaign_id: str) -> str:
    """Delete a campaign. This is irreversible. Only works on campaigns that haven't been sent.

    Args:
        campaign_id: The campaign ID to delete.
    """
    if (guard := _guard_write(action="delete campaign", campaign_id=campaign_id)):
        return guard
    mc_request(f"/campaigns/{campaign_id}", method="DELETE")
    return json.dumps({"status": "deleted", "campaign_id": campaign_id}, indent=2)


@mcp.tool()
def send_campaign(campaign_id: str) -> str:
    """Send a campaign immediately. The campaign must have content set and be in 'save' status.
    This action is irreversible -- the email will be delivered to all recipients.

    Args:
        campaign_id: The campaign ID to send.
    """
    if (guard := _guard_write(action="send campaign", campaign_id=campaign_id)):
        return guard
    mc_request(f"/campaigns/{campaign_id}/actions/send", method="POST")
    return json.dumps({"status": "sent", "campaign_id": campaign_id}, indent=2)


@mcp.tool()
def send_test_email(campaign_id: str, test_emails: str, send_type: str = "html") -> str:
    """Send a test email for a campaign to one or more email addresses.

    Args:
        campaign_id: The campaign ID.
        test_emails: Comma-separated list of email addresses to send the test to.
        send_type: Type of test email: 'html' or 'plaintext' (default 'html').
    """
    if (guard := _guard_write(action="send test email", campaign_id=campaign_id)):
        return guard
    email_list = [e.strip() for e in test_emails.split(",")]
    body = {"test_emails": email_list, "send_type": send_type}
    mc_request(f"/campaigns/{campaign_id}/actions/test", body=body, method="POST")
    return json.dumps({"status": "test_sent", "campaign_id": campaign_id, "test_emails": email_list}, indent=2)


@mcp.tool()
def cancel_send(campaign_id: str) -> str:
    """Cancel a campaign that is currently sending. Only works for campaigns with status 'sending'.

    Args:
        campaign_id: The campaign ID to cancel.
    """
    if (guard := _guard_write(action="cancel campaign send", campaign_id=campaign_id)):
        return guard
    mc_request(f"/campaigns/{campaign_id}/actions/cancel-send", method="POST")
    return json.dumps({"status": "cancelled", "campaign_id": campaign_id}, indent=2)


# --- Write Tools: Tags & Segments ---

@mcp.tool()
def create_segment(list_id: str, name: str, static: bool = True, match: Optional[str] = None, conditions_json: Optional[str] = None) -> str:
    """Create a new segment (or tag) in an audience. For dynamic segments, provide match and conditions_json.

    Args:
        list_id: The Mailchimp audience/list ID.
        name: Name of the segment/tag.
        static: If True, creates a static segment (tag). If False, creates a saved segment.
        match: Condition match type: 'all' or 'any'. Required for dynamic segments.
        conditions_json: JSON string of conditions array for dynamic segments.
            Example: '[{"condition_type":"TextMerge","field":"merge_fields/FNAME","op":"is","value":"John"}]'
    """
    if (guard := _guard_write(action="create segment", list_id=list_id, name=name)):
        return guard
    body: dict = {"name": name}
    if match and conditions_json:
        conditions = json.loads(conditions_json)
        body["options"] = {"match": match, "conditions": conditions}
    elif static:
        body["static_segment"] = []
    data = mc_request(f"/lists/{list_id}/segments", body=body, method="POST")
    return json.dumps({
        "id": data.get("id"),
        "name": data.get("name"),
        "member_count": data.get("member_count"),
        "type": data.get("type"),
        "options": data.get("options"),
    }, indent=2)


@mcp.tool()
def delete_segment(list_id: str, segment_id: str) -> str:
    """Delete a segment/tag from an audience. This is irreversible — the segment and its
    association with members will be removed.

    Args:
        list_id: The Mailchimp audience/list ID.
        segment_id: The segment/tag ID to delete.
    """
    if (guard := _guard_write(action="delete segment", list_id=list_id, segment_id=segment_id)):
        return guard
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
    if (guard := _guard_write(action="add members to segment", list_id=list_id, segment_id=segment_id)):
        return guard
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
    if (guard := _guard_write(action="remove members from segment", list_id=list_id, segment_id=segment_id)):
        return guard
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


@mcp.tool()
def update_segment(list_id: str, segment_id: str, name: Optional[str] = None, match: Optional[str] = None, conditions_json: Optional[str] = None) -> str:
    """Update a segment's name or conditions.

    Args:
        list_id: The Mailchimp audience/list ID.
        segment_id: The segment ID to update.
        name: New name for the segment.
        match: Condition match type: 'all' or 'any'.
        conditions_json: JSON string of conditions array.
            Example: '[{"condition_type":"TextMerge","field":"merge_fields/FNAME","op":"is","value":"John"}]'
    """
    if (guard := _guard_write(action="update segment", list_id=list_id, segment_id=segment_id)):
        return guard
    body: dict = {}
    if name:
        body["name"] = name
    if match and conditions_json:
        conditions = json.loads(conditions_json)
        body["options"] = {"match": match, "conditions": conditions}
    data = mc_request(f"/lists/{list_id}/segments/{segment_id}", body=body, method="PATCH")
    return json.dumps({
        "id": data.get("id"),
        "name": data.get("name"),
        "member_count": data.get("member_count"),
        "type": data.get("type"),
        "options": data.get("options"),
    }, indent=2)


@mcp.tool()
def get_segment(list_id: str, segment_id: str) -> str:
    """Get detailed information about a specific segment, including conditions for dynamic segments.

    Args:
        list_id: The Mailchimp audience/list ID.
        segment_id: The segment ID.
    """
    data = mc_request(f"/lists/{list_id}/segments/{segment_id}")
    return json.dumps({
        "id": data.get("id"),
        "name": data.get("name"),
        "member_count": data.get("member_count"),
        "type": data.get("type"),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
        "options": data.get("options"),
    }, indent=2)


@mcp.tool()
def list_segment_members(list_id: str, segment_id: str, count: int = 20, offset: int = 0) -> str:
    """List members in a specific segment.

    Args:
        list_id: The Mailchimp audience/list ID.
        segment_id: The segment ID.
        count: Number of members to return (default 20).
        offset: Pagination offset.
    """
    data = mc_request(f"/lists/{list_id}/segments/{segment_id}/members", params={"count": count, "offset": offset})
    members = []
    for m in data.get("members", []):
        members.append({
            "id": m.get("id"),
            "email_address": m.get("email_address"),
            "status": m.get("status"),
            "full_name": m.get("full_name"),
            "merge_fields": m.get("merge_fields"),
        })
    return json.dumps({"total_items": data.get("total_items"), "members": members}, indent=2)


# --- Read/Write Tools: Merge Fields ---

@mcp.tool()
def list_merge_fields(list_id: str, count: int = 50, offset: int = 0) -> str:
    """List merge fields (custom fields) for an audience.

    Args:
        list_id: The Mailchimp audience/list ID.
        count: Number of merge fields to return (default 50).
        offset: Pagination offset.
    """
    data = mc_request(f"/lists/{list_id}/merge-fields", params={"count": count, "offset": offset})
    fields = []
    for f in data.get("merge_fields", []):
        fields.append({
            "merge_id": f.get("merge_id"),
            "tag": f.get("tag"),
            "name": f.get("name"),
            "type": f.get("type"),
            "required": f.get("required"),
            "default_value": f.get("default_value"),
            "options": f.get("options"),
        })
    return json.dumps({"total_items": data.get("total_items"), "merge_fields": fields}, indent=2)


@mcp.tool()
def create_merge_field(list_id: str, name: str, type: str, tag: Optional[str] = None, required: bool = False, default_value: Optional[str] = None, choices: Optional[str] = None) -> str:
    """Create a new merge field (custom field) in an audience.

    Args:
        list_id: The Mailchimp audience/list ID.
        name: Display name for the merge field.
        type: Field type: text, number, address, date, birthday, phone, url, imageurl, zip, dropdown, radio.
        tag: Short tag name (e.g. 'COMPANY'). Auto-generated if omitted.
        required: Whether the field is required (default False).
        default_value: Default value for the field.
        choices: Comma-separated choices for dropdown or radio types.
    """
    if (guard := _guard_write(action="create merge field", list_id=list_id, name=name, type=type)):
        return guard
    body: dict = {"name": name, "type": type, "required": required}
    if tag:
        body["tag"] = tag
    if default_value:
        body["default_value"] = default_value
    if choices:
        body["options"] = {"choices": [c.strip() for c in choices.split(",")]}
    data = mc_request(f"/lists/{list_id}/merge-fields", body=body, method="POST")
    return json.dumps({
        "merge_id": data.get("merge_id"),
        "tag": data.get("tag"),
        "name": data.get("name"),
        "type": data.get("type"),
        "required": data.get("required"),
    }, indent=2)


@mcp.tool()
def update_merge_field(list_id: str, merge_id: str, name: Optional[str] = None, required: Optional[bool] = None, default_value: Optional[str] = None, choices: Optional[str] = None) -> str:
    """Update an existing merge field in an audience.

    Args:
        list_id: The Mailchimp audience/list ID.
        merge_id: The merge field ID to update.
        name: New display name.
        required: Whether the field is required.
        default_value: New default value.
        choices: New comma-separated choices for dropdown or radio types.
    """
    if (guard := _guard_write(action="update merge field", list_id=list_id, merge_id=merge_id)):
        return guard
    body: dict = {}
    if name is not None:
        body["name"] = name
    if required is not None:
        body["required"] = required
    if default_value is not None:
        body["default_value"] = default_value
    if choices is not None:
        body["options"] = {"choices": [c.strip() for c in choices.split(",")]}
    data = mc_request(f"/lists/{list_id}/merge-fields/{merge_id}", body=body, method="PATCH")
    return json.dumps({
        "merge_id": data.get("merge_id"),
        "tag": data.get("tag"),
        "name": data.get("name"),
        "type": data.get("type"),
        "required": data.get("required"),
    }, indent=2)


@mcp.tool()
def delete_merge_field(list_id: str, merge_id: str) -> str:
    """Delete a merge field from an audience. This is irreversible -- all data stored in this
    field for every member will be lost.

    Args:
        list_id: The Mailchimp audience/list ID.
        merge_id: The merge field ID to delete.
    """
    if (guard := _guard_write(action="delete merge field", list_id=list_id, merge_id=merge_id)):
        return guard
    mc_request(f"/lists/{list_id}/merge-fields/{merge_id}", method="DELETE")
    return json.dumps({"status": "deleted", "merge_id": merge_id}, indent=2)


# --- Read/Write Tools: Interest Categories & Groups ---

@mcp.tool()
def list_interest_categories(list_id: str, count: int = 50, offset: int = 0) -> str:
    """List interest categories (groups) for an audience.

    Args:
        list_id: The Mailchimp audience/list ID.
        count: Number of categories to return (default 50).
        offset: Pagination offset.
    """
    data = mc_request(f"/lists/{list_id}/interest-categories", params={"count": count, "offset": offset})
    categories = []
    for c in data.get("categories", []):
        categories.append({
            "id": c.get("id"),
            "title": c.get("title"),
            "type": c.get("type"),
            "list_id": c.get("list_id"),
        })
    return json.dumps({"total_items": data.get("total_items"), "categories": categories}, indent=2)


@mcp.tool()
def create_interest_category(list_id: str, title: str, type: str) -> str:
    """Create a new interest category (group) in an audience.

    Args:
        list_id: The Mailchimp audience/list ID.
        title: Display title for the category.
        type: Input type: 'checkboxes', 'dropdown', 'radio', or 'hidden'.
    """
    if (guard := _guard_write(action="create interest category", list_id=list_id, title=title)):
        return guard
    body = {"title": title, "type": type}
    data = mc_request(f"/lists/{list_id}/interest-categories", body=body, method="POST")
    return json.dumps({
        "id": data.get("id"),
        "title": data.get("title"),
        "type": data.get("type"),
        "list_id": data.get("list_id"),
    }, indent=2)


@mcp.tool()
def list_interests(list_id: str, category_id: str, count: int = 50, offset: int = 0) -> str:
    """List interests (options) within an interest category.

    Args:
        list_id: The Mailchimp audience/list ID.
        category_id: The interest category ID.
        count: Number of interests to return (default 50).
        offset: Pagination offset.
    """
    data = mc_request(f"/lists/{list_id}/interest-categories/{category_id}/interests", params={"count": count, "offset": offset})
    interests = []
    for i in data.get("interests", []):
        interests.append({
            "id": i.get("id"),
            "name": i.get("name"),
            "subscriber_count": i.get("subscriber_count"),
            "display_order": i.get("display_order"),
        })
    return json.dumps({"total_items": data.get("total_items"), "interests": interests}, indent=2)


@mcp.tool()
def create_interest(list_id: str, category_id: str, name: str) -> str:
    """Create a new interest (option) within an interest category.

    Args:
        list_id: The Mailchimp audience/list ID.
        category_id: The interest category ID.
        name: Name of the interest option.
    """
    if (guard := _guard_write(action="create interest", list_id=list_id, category_id=category_id, name=name)):
        return guard
    body = {"name": name}
    data = mc_request(f"/lists/{list_id}/interest-categories/{category_id}/interests", body=body, method="POST")
    return json.dumps({
        "id": data.get("id"),
        "name": data.get("name"),
        "subscriber_count": data.get("subscriber_count"),
    }, indent=2)


@mcp.tool()
def delete_interest_category(list_id: str, category_id: str) -> str:
    """Delete an interest category and all its interests. This is irreversible.

    Args:
        list_id: The Mailchimp audience/list ID.
        category_id: The interest category ID to delete.
    """
    if (guard := _guard_write(action="delete interest category", list_id=list_id, category_id=category_id)):
        return guard
    mc_request(f"/lists/{list_id}/interest-categories/{category_id}", method="DELETE")
    return json.dumps({"status": "deleted", "category_id": category_id}, indent=2)


@mcp.tool()
def delete_interest(list_id: str, category_id: str, interest_id: str) -> str:
    """Delete an interest (option) from an interest category. This is irreversible.

    Args:
        list_id: The Mailchimp audience/list ID.
        category_id: The interest category ID.
        interest_id: The interest ID to delete.
    """
    if (guard := _guard_write(action="delete interest", list_id=list_id, category_id=category_id, interest_id=interest_id)):
        return guard
    mc_request(f"/lists/{list_id}/interest-categories/{category_id}/interests/{interest_id}", method="DELETE")
    return json.dumps({"status": "deleted", "interest_id": interest_id}, indent=2)


# --- Read/Write Tools: Webhooks ---

@mcp.tool()
def list_webhooks(list_id: str) -> str:
    """List webhooks configured for an audience.

    Args:
        list_id: The Mailchimp audience/list ID.
    """
    data = mc_request(f"/lists/{list_id}/webhooks")
    webhooks = []
    for w in data.get("webhooks", []):
        webhooks.append({
            "id": w.get("id"),
            "url": w.get("url"),
            "events": w.get("events"),
            "sources": w.get("sources"),
            "list_id": w.get("list_id"),
        })
    return json.dumps({"total_items": data.get("total_items"), "webhooks": webhooks}, indent=2)


@mcp.tool()
def create_webhook(list_id: str, url: str, events: Optional[str] = None, sources: Optional[str] = None) -> str:
    """Create a webhook for an audience to receive notifications on member events.

    Args:
        list_id: The Mailchimp audience/list ID.
        url: The URL to receive webhook POST requests.
        events: Comma-separated events to listen for: subscribe, unsubscribe, profile, cleaned, upemail, campaign.
        sources: Comma-separated sources to listen for: user, admin, api.
    """
    if (guard := _guard_write(action="create webhook", list_id=list_id, url=url)):
        return guard
    body: dict = {"url": url}
    if events:
        event_list = [e.strip() for e in events.split(",")]
        body["events"] = {e: True for e in event_list}
    if sources:
        source_list = [s.strip() for s in sources.split(",")]
        body["sources"] = {s: True for s in source_list}
    data = mc_request(f"/lists/{list_id}/webhooks", body=body, method="POST")
    return json.dumps({
        "id": data.get("id"),
        "url": data.get("url"),
        "events": data.get("events"),
        "sources": data.get("sources"),
    }, indent=2)


@mcp.tool()
def delete_webhook(list_id: str, webhook_id: str) -> str:
    """Delete a webhook from an audience. This is irreversible.

    Args:
        list_id: The Mailchimp audience/list ID.
        webhook_id: The webhook ID to delete.
    """
    if (guard := _guard_write(action="delete webhook", list_id=list_id, webhook_id=webhook_id)):
        return guard
    mc_request(f"/lists/{list_id}/webhooks/{webhook_id}", method="DELETE")
    return json.dumps({"status": "deleted", "webhook_id": webhook_id}, indent=2)


# --- Read Tools: Detailed Reports ---

@mcp.tool()
def get_email_activity(campaign_id: str, count: int = 20, offset: int = 0) -> str:
    """Get email activity for each recipient of a campaign (opens, clicks, bounces per member).

    Args:
        campaign_id: The Mailchimp campaign ID.
        count: Number of members to return.
        offset: Pagination offset.
    """
    data = mc_request(f"/reports/{campaign_id}/email-activity", params={"count": count, "offset": offset})
    emails = []
    for e in data.get("emails", []):
        emails.append({
            "email_address": e.get("email_address"),
            "activity": e.get("activity", []),
        })
    return json.dumps({"total_items": data.get("total_items"), "emails": emails}, indent=2)


@mcp.tool()
def get_open_details(campaign_id: str, count: int = 20, offset: int = 0) -> str:
    """Get detailed open information for a campaign (who opened, when, how many times).

    Args:
        campaign_id: The Mailchimp campaign ID.
        count: Number of records to return.
        offset: Pagination offset.
    """
    data = mc_request(f"/reports/{campaign_id}/open-details", params={"count": count, "offset": offset})
    members = []
    for m in data.get("members", []):
        members.append({
            "email_address": m.get("email_address"),
            "opens_count": m.get("opens_count"),
            "opens": m.get("opens", []),
        })
    return json.dumps({"total_items": data.get("total_items"), "members": members}, indent=2)


@mcp.tool()
def get_campaign_recipients(campaign_id: str, count: int = 20, offset: int = 0) -> str:
    """Get the list of recipients for a sent campaign with their delivery status.

    Args:
        campaign_id: The Mailchimp campaign ID.
        count: Number of recipients to return.
        offset: Pagination offset.
    """
    data = mc_request(f"/reports/{campaign_id}/sent-to", params={"count": count, "offset": offset})
    recipients = []
    for r in data.get("sent_to", []):
        recipients.append({
            "email_address": r.get("email_address"),
            "status": r.get("status"),
            "open_count": r.get("open_count"),
            "last_open": r.get("last_open"),
        })
    return json.dumps({"total_items": data.get("total_items"), "recipients": recipients}, indent=2)


@mcp.tool()
def get_campaign_unsubscribes(campaign_id: str, count: int = 20, offset: int = 0) -> str:
    """Get members who unsubscribed after a specific campaign.

    Args:
        campaign_id: The Mailchimp campaign ID.
        count: Number of records to return.
        offset: Pagination offset.
    """
    data = mc_request(f"/reports/{campaign_id}/unsubscribed", params={"count": count, "offset": offset})
    unsubs = []
    for u in data.get("unsubscribes", []):
        unsubs.append({
            "email_address": u.get("email_address"),
            "reason": u.get("reason"),
            "timestamp": u.get("timestamp"),
        })
    return json.dumps({"total_items": data.get("total_items"), "unsubscribes": unsubs}, indent=2)


@mcp.tool()
def get_domain_performance(campaign_id: str) -> str:
    """Get campaign performance broken down by email domain (gmail, outlook, yahoo, etc.).

    Args:
        campaign_id: The Mailchimp campaign ID.
    """
    data = mc_request(f"/reports/{campaign_id}/domain-performance")
    domains = []
    for d in data.get("domains", []):
        domains.append({
            "domain": d.get("domain"),
            "emails_sent": d.get("emails_sent"),
            "bounces": d.get("bounces"),
            "opens": d.get("opens"),
            "clicks": d.get("clicks"),
            "unsubs": d.get("unsubs"),
        })
    return json.dumps({"total_items": data.get("total_items"), "domains": domains}, indent=2)


@mcp.tool()
def get_ecommerce_product_activity(campaign_id: str, count: int = 20, offset: int = 0) -> str:
    """Get e-commerce product activity for a campaign (revenue, orders per product). Requires e-commerce integration.

    Args:
        campaign_id: The Mailchimp campaign ID.
        count: Number of products to return.
        offset: Pagination offset.
    """
    data = mc_request(f"/reports/{campaign_id}/ecommerce-product-activity", params={"count": count, "offset": offset})
    products = []
    for p in data.get("products", []):
        products.append({
            "title": p.get("title"),
            "sku": p.get("sku"),
            "image_url": p.get("image_url"),
            "total_revenue": p.get("total_revenue"),
            "total_purchased": p.get("total_purchased"),
        })
    return json.dumps({"total_items": data.get("total_items"), "products": products}, indent=2)


@mcp.tool()
def get_campaign_sub_reports(campaign_id: str) -> str:
    """Get sub-reports for a campaign (A/B test variants, RSS items, etc.).

    Args:
        campaign_id: The Mailchimp campaign ID.
    """
    data = mc_request(f"/reports/{campaign_id}/sub-reports")
    return json.dumps(data, indent=2)


# --- Read Tools: Member Activity ---

@mcp.tool()
def get_member_activity(list_id: str, email_address: str, count: int = 20) -> str:
    """Get the activity history of a specific member (opens, clicks, bounces, etc.).

    Args:
        list_id: The Mailchimp audience/list ID.
        email_address: Email address of the member.
        count: Number of activity records to return.
    """
    subscriber_hash = hashlib.md5(email_address.lower().encode()).hexdigest()
    data = mc_request(f"/lists/{list_id}/members/{subscriber_hash}/activity", params={"count": count})
    activities = []
    for a in data.get("activity", []):
        activities.append({
            "action": a.get("action"),
            "timestamp": a.get("timestamp"),
            "campaign_id": a.get("campaign_id"),
            "title": a.get("title"),
        })
    return json.dumps({"email_address": email_address, "activity": activities}, indent=2)


@mcp.tool()
def get_member_tags(list_id: str, email_address: str, count: int = 50) -> str:
    """Get all tags assigned to a specific member.

    Args:
        list_id: The Mailchimp audience/list ID.
        email_address: Email address of the member.
        count: Number of tags to return.
    """
    subscriber_hash = hashlib.md5(email_address.lower().encode()).hexdigest()
    data = mc_request(f"/lists/{list_id}/members/{subscriber_hash}/tags", params={"count": count})
    tags = []
    for t in data.get("tags", []):
        tags.append({
            "id": t.get("id"),
            "name": t.get("name"),
            "date_added": t.get("date_added"),
        })
    return json.dumps({"email_address": email_address, "total_items": data.get("total_items"), "tags": tags}, indent=2)


@mcp.tool()
def get_member_events(list_id: str, email_address: str, count: int = 20) -> str:
    """Get custom events for a specific member.

    Args:
        list_id: The Mailchimp audience/list ID.
        email_address: Email address of the member.
        count: Number of events to return.
    """
    subscriber_hash = hashlib.md5(email_address.lower().encode()).hexdigest()
    data = mc_request(f"/lists/{list_id}/members/{subscriber_hash}/events", params={"count": count})
    events = []
    for e in data.get("events", []):
        events.append({
            "name": e.get("name"),
            "occurred_at": e.get("occurred_at"),
            "properties": e.get("properties"),
        })
    return json.dumps({"email_address": email_address, "total_items": data.get("total_items"), "events": events}, indent=2)


# --- Read/Write Tools: Automations (granular) ---

@mcp.tool()
def get_automation_emails(automation_id: str) -> str:
    """List all emails in an automation workflow.

    Args:
        automation_id: The automation workflow ID.
    """
    data = mc_request(f"/automations/{automation_id}/emails")
    emails = []
    for e in data.get("emails", []):
        emails.append({
            "id": e.get("id"),
            "position": e.get("position"),
            "status": e.get("status"),
            "subject_line": e.get("settings", {}).get("subject_line"),
            "title": e.get("settings", {}).get("title"),
            "emails_sent": e.get("emails_sent"),
            "send_time": e.get("send_time"),
            "delay": e.get("delay"),
        })
    return json.dumps({"total_items": data.get("total_items"), "emails": emails}, indent=2)


@mcp.tool()
def get_automation_email_queue(automation_id: str, email_id: str) -> str:
    """Get the queue of subscribers about to receive an automation email.

    Args:
        automation_id: The automation workflow ID.
        email_id: The specific email ID within the automation.
    """
    data = mc_request(f"/automations/{automation_id}/emails/{email_id}/queue")
    queue = []
    for q in data.get("queue", []):
        queue.append({
            "email_address": q.get("email_address"),
            "next_send": q.get("next_send"),
        })
    return json.dumps({"total_items": data.get("total_items"), "queue": queue}, indent=2)


@mcp.tool()
def pause_automation(automation_id: str) -> str:
    """Pause all emails in an automation workflow. Subscribers currently in the queue will
    not receive further emails until the workflow is resumed.

    Args:
        automation_id: The automation workflow ID.
    """
    if (guard := _guard_write(action="pause automation", automation_id=automation_id)):
        return guard
    mc_request(f"/automations/{automation_id}/actions/pause-all-emails", method="POST")
    return json.dumps({"status": "paused", "automation_id": automation_id}, indent=2)


@mcp.tool()
def start_automation(automation_id: str) -> str:
    """Start (or resume) all emails in an automation workflow. Queued subscribers will begin
    receiving emails again.

    Args:
        automation_id: The automation workflow ID.
    """
    if (guard := _guard_write(action="start automation", automation_id=automation_id)):
        return guard
    mc_request(f"/automations/{automation_id}/actions/start-all-emails", method="POST")
    return json.dumps({"status": "started", "automation_id": automation_id}, indent=2)


# --- Read Tools: Landing Pages ---

@mcp.tool()
def list_landing_pages(count: int = 20, offset: int = 0) -> str:
    """List all landing pages in the account.

    Args:
        count: Number of landing pages to return.
        offset: Pagination offset.
    """
    data = mc_request("/landing-pages", params={"count": count, "offset": offset})
    pages = []
    for p in data.get("landing_pages", []):
        pages.append({
            "id": p.get("id"),
            "name": p.get("name"),
            "title": p.get("title"),
            "status": p.get("status"),
            "url": p.get("url"),
            "published_at": p.get("published_at"),
            "created_at": p.get("created_at"),
            "list_id": p.get("list_id"),
        })
    return json.dumps({"total_items": data.get("total_items"), "landing_pages": pages}, indent=2)


@mcp.tool()
def get_landing_page(page_id: str) -> str:
    """Get details of a specific landing page.

    Args:
        page_id: The landing page ID.
    """
    data = mc_request(f"/landing-pages/{page_id}")
    return json.dumps({
        "id": data.get("id"),
        "name": data.get("name"),
        "title": data.get("title"),
        "description": data.get("description"),
        "status": data.get("status"),
        "url": data.get("url"),
        "published_at": data.get("published_at"),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
        "list_id": data.get("list_id"),
        "tracking": data.get("tracking"),
    }, indent=2)


# --- Read Tools: E-commerce ---

@mcp.tool()
def list_ecommerce_stores() -> str:
    """List all connected e-commerce stores."""
    data = mc_request("/ecommerce/stores")
    stores = []
    for s in data.get("stores", []):
        stores.append({
            "id": s.get("id"),
            "list_id": s.get("list_id"),
            "name": s.get("name"),
            "platform": s.get("platform"),
            "domain": s.get("domain"),
            "currency_code": s.get("currency_code"),
            "money_format": s.get("money_format"),
            "created_at": s.get("created_at"),
        })
    return json.dumps({"total_items": data.get("total_items"), "stores": stores}, indent=2)


@mcp.tool()
def list_store_orders(store_id: str, count: int = 20, offset: int = 0) -> str:
    """List orders from a connected e-commerce store.

    Args:
        store_id: The e-commerce store ID.
        count: Number of orders to return.
        offset: Pagination offset.
    """
    data = mc_request(f"/ecommerce/stores/{store_id}/orders", params={"count": count, "offset": offset})
    orders = []
    for o in data.get("orders", []):
        orders.append({
            "id": o.get("id"),
            "customer": o.get("customer", {}).get("email_address"),
            "order_total": o.get("order_total"),
            "currency_code": o.get("currency_code"),
            "financial_status": o.get("financial_status"),
            "fulfillment_status": o.get("fulfillment_status"),
            "processed_at_foreign": o.get("processed_at_foreign"),
            "lines_count": len(o.get("lines", [])),
        })
    return json.dumps({"total_items": data.get("total_items"), "orders": orders}, indent=2)


@mcp.tool()
def list_store_products(store_id: str, count: int = 20, offset: int = 0) -> str:
    """List products from a connected e-commerce store.

    Args:
        store_id: The e-commerce store ID.
        count: Number of products to return.
        offset: Pagination offset.
    """
    data = mc_request(f"/ecommerce/stores/{store_id}/products", params={"count": count, "offset": offset})
    products = []
    for p in data.get("products", []):
        products.append({
            "id": p.get("id"),
            "title": p.get("title"),
            "url": p.get("url"),
            "vendor": p.get("vendor"),
            "image_url": p.get("image_url"),
            "variants_count": len(p.get("variants", [])),
        })
    return json.dumps({"total_items": data.get("total_items"), "products": products}, indent=2)


@mcp.tool()
def list_store_customers(store_id: str, count: int = 20, offset: int = 0) -> str:
    """List customers from a connected e-commerce store.

    Args:
        store_id: The e-commerce store ID.
        count: Number of customers to return.
        offset: Pagination offset.
    """
    data = mc_request(f"/ecommerce/stores/{store_id}/customers", params={"count": count, "offset": offset})
    customers = []
    for c in data.get("customers", []):
        customers.append({
            "id": c.get("id"),
            "email_address": c.get("email_address"),
            "first_name": c.get("first_name"),
            "last_name": c.get("last_name"),
            "orders_count": c.get("orders_count"),
            "total_spent": c.get("total_spent"),
            "opt_in_status": c.get("opt_in_status"),
            "created_at": c.get("created_at"),
        })
    return json.dumps({"total_items": data.get("total_items"), "customers": customers}, indent=2)


# --- Read Tools: Campaign Folders ---

@mcp.tool()
def list_campaign_folders(count: int = 50, offset: int = 0) -> str:
    """List campaign folders used to organize campaigns.

    Args:
        count: Number of folders to return.
        offset: Pagination offset.
    """
    data = mc_request("/campaign-folders", params={"count": count, "offset": offset})
    folders = []
    for f in data.get("folders", []):
        folders.append({
            "id": f.get("id"),
            "name": f.get("name"),
            "count": f.get("count"),
        })
    return json.dumps({"total_items": data.get("total_items"), "folders": folders}, indent=2)


# --- Batch Operations ---

@mcp.tool()
def create_batch(operations: str) -> str:
    """Run multiple API operations in a single batch request. Useful for bulk updates.
    Each operation runs against the Mailchimp API — destructive operations included.

    Args:
        operations: JSON string of operations array. Each operation needs: method, path, and optionally body.
            Example: [{"method":"POST","path":"/lists/abc123/members/hash/tags","body":"{\"tags\":[{\"name\":\"VIP\",\"status\":\"active\"}]}"}]
    """
    if (guard := _guard_write(action="run batch operations")):
        return guard
    ops = json.loads(operations)
    data = mc_request("/batches", body={"operations": ops}, method="POST")
    return json.dumps({
        "id": data.get("id"),
        "status": data.get("status"),
        "total_operations": data.get("total_operations"),
        "submitted_at": data.get("submitted_at"),
    }, indent=2)


@mcp.tool()
def get_batch_status(batch_id: str) -> str:
    """Check the status of a batch operation.

    Args:
        batch_id: The batch operation ID.
    """
    data = mc_request(f"/batches/{batch_id}")
    return json.dumps({
        "id": data.get("id"),
        "status": data.get("status"),
        "total_operations": data.get("total_operations"),
        "finished_operations": data.get("finished_operations"),
        "errored_operations": data.get("errored_operations"),
        "submitted_at": data.get("submitted_at"),
        "completed_at": data.get("completed_at"),
        "response_body_url": data.get("response_body_url"),
    }, indent=2)


@mcp.tool()
def list_batches(count: int = 20, offset: int = 0) -> str:
    """List recent batch operations.

    Args:
        count: Number of batch operations to return.
        offset: Pagination offset.
    """
    data = mc_request("/batches", params={"count": count, "offset": offset})
    batches = []
    for b in data.get("batches", []):
        batches.append({
            "id": b.get("id"),
            "status": b.get("status"),
            "total_operations": b.get("total_operations"),
            "finished_operations": b.get("finished_operations"),
            "errored_operations": b.get("errored_operations"),
            "submitted_at": b.get("submitted_at"),
            "completed_at": b.get("completed_at"),
        })
    return json.dumps({"total_items": data.get("total_items"), "batches": batches}, indent=2)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
