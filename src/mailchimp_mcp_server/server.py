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
    """Get Mailchimp account information including name, contact details, and subscriber stats.

    Use this tool to verify API connectivity, check account-level metrics, or retrieve
    industry benchmarks. This is the starting point for most workflows. Read-only. Does not
    modify data.

    Args:
        No parameters required.

    Returns:
        JSON with fields: account_name, email, first_name, last_name, total_subscribers, industry_stats.

    Example:
        get_account_info() -> {"account_name": "My Company", "total_subscribers": 5000, ...}
    """
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
    """List all audiences (also called lists) in the Mailchimp account with subscriber counts and engagement rates.

    Use this tool as the first step in most workflows to discover audience IDs. Almost every
    other tool requires a list_id, which you get from this tool's output. Use get_audience_details
    instead when you already have a list_id and need full stats or the subscribe URL. Do not use
    this tool to find a specific member; use search_members for that. Most Mailchimp accounts
    have 1-5 audiences. Read-only. Does not modify data.

    Args:
        count: Number of audiences to return (1-1000, default 10). Most accounts have fewer
            than 10 audiences.
        offset: Pagination offset for retrieving additional pages. Use when total_items exceeds count.

    Returns:
        JSON with total_items and audiences array. Each audience includes: id (use this as
        list_id in other tools), name, member_count, unsubscribe_count, open_rate (decimal 0-1),
        click_rate (decimal 0-1), date_created (ISO 8601).

    Example:
        list_audiences(count=5) -> {"total_items": 2, "audiences": [{"id": "abc123", "name": "Newsletter", "member_count": 5000, ...}]}
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
    """Get detailed information about a specific audience including full stats and subscribe URL.

    Use this tool when you already have a list_id and need full stats (member counts, open/click
    rates, rating) or the subscribe URL. Use list_audiences instead to browse all audiences.
    Read-only. Does not modify data.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').

    Returns:
        JSON with fields: id, name, stats (full stats object), date_created, list_rating,
        subscribe_url_short.

    Example:
        get_audience_details(list_id="abc123def4") -> {"id": "abc123def4", "name": "Newsletter", "stats": {...}}
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
    """List campaigns in the Mailchimp account with basic metadata and send stats.

    Use this tool to browse campaigns, find campaign IDs, or filter by status/date.
    Use get_campaign_details for full settings of a single campaign, or get_campaign_report
    for post-send performance metrics. Read-only. Does not modify data.

    Args:
        count: Number of campaigns to return (max 1000, default 20).
        offset: Pagination offset for retrieving additional pages.
        status: Filter by campaign status. Valid values: 'save' (draft), 'paused', 'schedule',
            'sending', 'sent'.
        since_send_time: Only return campaigns sent after this datetime. Format: ISO 8601
            (e.g. '2025-01-01T00:00:00Z').

    Returns:
        JSON with total_items and campaigns array (id, type, status, title, subject_line,
        preview_text, send_time, emails_sent, list_id, list_name).

    Example:
        list_campaigns(count=10, status="sent") -> {"total_items": 42, "campaigns": [...]}
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
    """Get full configuration of a specific campaign including settings, recipients, and tracking.

    Use this tool to inspect a campaign's subject line, sender, audience targeting, or tracking
    options. Use get_campaign_report instead for post-send performance metrics (opens, clicks,
    bounces). Read-only. Does not modify data.

    Args:
        campaign_id: The Mailchimp campaign ID (e.g. 'abc123def4').

    Returns:
        JSON with fields: id, type, status, settings (subject_line, title, from_name, reply_to),
        recipients (list_id, segment), send_time, emails_sent, tracking.

    Example:
        get_campaign_details(campaign_id="abc123def4") -> {"id": "abc123def4", "status": "sent", "settings": {...}}
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
    """Get aggregate performance report for a sent campaign including opens, clicks, bounces, and industry benchmarks.

    Use this tool for a high-level overview of campaign performance. Use get_campaign_click_details
    for per-link click data, get_open_details for per-recipient open data, or get_campaign_recipients
    for delivery status per recipient. Only available for sent campaigns. Read-only. Does not
    modify data.

    Args:
        campaign_id: The Mailchimp campaign ID (e.g. 'abc123def4').

    Returns:
        JSON with fields: campaign_title, subject_line, emails_sent, abuse_reports, unsubscribed,
        send_time, opens (total/unique/rate), clicks (total/unique/rate), bounces (hard/soft),
        forwards, list_stats, industry_stats.

    Example:
        get_campaign_report(campaign_id="abc123") -> {"emails_sent": 5000, "opens": {"open_rate": 0.25}, ...}
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
    """Get per-link click data for a campaign showing which URLs were clicked and how many times.

    Use this tool to analyze which links in the email drove the most engagement. Use
    get_campaign_report instead for aggregate campaign metrics (total opens, clicks, bounces).
    Read-only. Does not modify data.

    Args:
        campaign_id: The Mailchimp campaign ID (e.g. 'abc123def4').
        count: Number of URL results to return (max 1000, default 20).

    Returns:
        JSON with total_items and links array (url, total_clicks, unique_clicks, click_percentage).

    Example:
        get_campaign_click_details(campaign_id="abc123") -> {"total_items": 5, "links": [{"url": "https://...", "total_clicks": 120, ...}]}
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
    """List members of a specific audience with their subscription status, merge fields, and engagement stats.

    Use this tool to browse members of a known audience. Use search_members instead when looking
    for a specific person by email or name across all audiences. Supports pagination for large
    audiences. Read-only. Does not modify data.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        count: Number of members to return (max 1000, default 20).
        offset: Pagination offset for retrieving additional pages.
        status: Filter by subscription status. Valid values: 'subscribed', 'unsubscribed',
            'cleaned', 'pending', 'transactional'.

    Returns:
        JSON with total_items and members array (id, email_address, status, full_name,
        merge_fields, open_rate, click_rate, timestamp_opt).

    Example:
        list_audience_members(list_id="abc123", count=50, status="subscribed")
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
    """Search for members across all audiences by email address or name.

    Use this tool when looking for a specific person and you may not know which audience they
    belong to. Returns both exact matches and partial matches. Use list_audience_members instead
    to browse all members of a known audience. Read-only. Does not modify data.

    Args:
        query: Search query. Can be a full email address (for exact match) or a name/partial
            email (for fuzzy search).
        list_id: Optional audience/list ID to restrict the search to a single audience.

    Returns:
        JSON with results array (email, status, full_name, list_id) combining exact and
        fuzzy matches.

    Example:
        search_members(query="john@example.com") -> {"results": [{"email": "john@example.com", ...}]}
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
    """Get monthly growth history for an audience showing subscribes, unsubscribes, and cleaned contacts over time.

    Use this tool to analyze audience growth trends or detect unusual churn patterns.
    Each record represents one calendar month. Data is available from the audience creation date.
    Read-only. Does not modify data.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        count: Number of months to return (default 12, max 1000).

    Returns:
        JSON with list_id and history array (month, subscribed, unsubscribed, reconfirm,
        cleaned, pending, transactional).

    Example:
        get_audience_growth_history(list_id="abc123def4", count=6) -> {"list_id": "abc123def4", "history": [{"month": "2025-01", ...}]}
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
    """List automation workflows (automated email sequences) in the account.

    Use this tool to discover automations and their IDs. Use get_automation_emails to see
    individual emails within a workflow, or pause_automation/start_automation to control them.
    Read-only. Does not modify data.

    Args:
        count: Number of automations to return (max 1000, default 20).
        offset: Pagination offset for retrieving additional pages.

    Returns:
        JSON with total_items and automations array (id, status, title, emails_sent, start_time,
        create_time, list_id).

    Example:
        list_automations() -> {"total_items": 3, "automations": [{"id": "auto123", "status": "sending", ...}]}
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
    """List email templates available in the account (both user-created and Mailchimp defaults).

    Use this tool to browse available templates. Templates can be used as a starting point
    when creating campaign content. Read-only. Does not modify data.

    Args:
        count: Number of templates to return (max 1000, default 20).
        offset: Pagination offset for retrieving additional pages.

    Returns:
        JSON with total_items and templates array (id, name, type, date_created, active).

    Example:
        list_templates() -> {"total_items": 10, "templates": [{"id": 12345, "name": "Monthly Newsletter", ...}]}
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
    """List all segments and tags for a specific audience with member counts.

    Use this tool to discover segment/tag IDs before targeting campaigns or managing members.
    Returns both static segments (tags) and dynamic (saved) segments. Use get_segment for
    full details including conditions on a specific segment. Read-only. Does not modify data.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        count: Number of segments to return (max 1000, default 20).
        offset: Pagination offset for retrieving additional pages.

    Returns:
        JSON with total_items and segments array (id, name, member_count, type, created_at, updated_at).
        Type is 'static' for tags or 'saved' for dynamic segments.

    Example:
        list_segments(list_id="abc123") -> {"total_items": 5, "segments": [{"id": 12345, "name": "VIP", "type": "static", ...}]}
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
    """Add a single new member to an audience with optional name and tags.

    Use this tool to subscribe one person. For adding multiple members at once, use
    batch_subscribe instead. If the email already exists, this will return an error;
    use update_member to modify existing members. Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        email_address: Email address of the new member.
        status: Subscription status. Valid values: 'subscribed' (default, immediate opt-in),
            'pending' (triggers double opt-in confirmation email), 'unsubscribed', 'cleaned'.
        first_name: First name, stored in the FNAME merge field.
        last_name: Last name, stored in the LNAME merge field.
        tags: Comma-separated tags to apply (e.g. 'VIP,Newsletter').

    Returns:
        JSON with fields: id, email_address, status, full_name.

    Example:
        add_member(list_id="abc123", email_address="jane@co.com", first_name="Jane", tags="VIP")
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
    """Update an existing member's profile or subscription status.

    Use this tool to change a member's name or status. Only provided fields are updated;
    omitted fields remain unchanged. Use unsubscribe_member as a shortcut to unsubscribe,
    or tag_member to manage tags. Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        email_address: Email address of the member to update. Must already exist in the audience.
        status: New subscription status. Valid values: 'subscribed', 'unsubscribed', 'cleaned', 'pending'.
        first_name: New first name (FNAME merge field).
        last_name: New last name (LNAME merge field).

    Returns:
        JSON with fields: id, email_address, status, full_name.

    Example:
        update_member(list_id="abc123", email_address="jane@co.com", first_name="Janet")
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
    """Unsubscribe a member from an audience. The member stops receiving campaigns but their profile and history are preserved.

    Use this tool to opt someone out while keeping their data for reporting. Use delete_member
    instead to permanently remove all data. This is reversible by resubscribing the member
    via update_member. Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        email_address: Email address of the member to unsubscribe.

    Returns:
        JSON with fields: email_address, status ("unsubscribed").

    Example:
        unsubscribe_member(list_id="abc123", email_address="jane@co.com")
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
    """Permanently delete a member and all their data from an audience. This action is irreversible.

    Use this tool only when you need to completely remove a member's history, activity, and
    associated data (e.g. for GDPR compliance). Use unsubscribe_member instead to simply stop
    sending emails while preserving the member's data for reporting. Respects read-only and
    dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        email_address: Email address of the member to permanently delete.

    Returns:
        JSON with fields: status ("permanently_deleted"), email_address.

    Example:
        delete_member(list_id="abc123", email_address="jane@co.com")
    """
    if (guard := _guard_write(action="permanently delete member", email_address=email_address, list_id=list_id)):
        return guard
    subscriber_hash = hashlib.md5(email_address.lower().encode()).hexdigest()
    mc_request(f"/lists/{list_id}/members/{subscriber_hash}/actions/delete-permanent", method="POST")
    return json.dumps({"status": "permanently_deleted", "email_address": email_address}, indent=2)


@mcp.tool()
def tag_member(list_id: str, email_address: str, tags_to_add: Optional[str] = None, tags_to_remove: Optional[str] = None) -> str:
    """Add or remove tags from a specific member. Tags are free-form labels for organizing contacts.

    Use this tool to manage per-member labels. Tags are different from segments: tags are applied
    directly to individual members, while segments are audience-level groupings based on criteria.
    Use add_members_to_segment to add members to a static segment instead. Provide at least one
    of tags_to_add or tags_to_remove. Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        email_address: Email address of the member.
        tags_to_add: Comma-separated tag names to add (e.g. 'VIP,Returning Customer').
        tags_to_remove: Comma-separated tag names to remove (e.g. 'Trial').

    Returns:
        JSON with fields: status ("updated"), email_address, tags (array of changes applied).

    Example:
        tag_member(list_id="abc123", email_address="jane@co.com", tags_to_add="VIP,Premium")
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
    """Batch add or update multiple members in an audience in a single request (up to 500 members).

    Use this tool when adding or updating more than one member at a time. For a single member,
    use add_member or update_member instead. For very large imports (500+), use create_batch.
    Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        members_json: JSON string of members array. Each member needs at minimum: email_address, status.
            Supported status values: 'subscribed', 'unsubscribed', 'cleaned', 'pending'.
            Example: '[{"email_address":"a@b.com","status":"subscribed","merge_fields":{"FNAME":"Alice"}}]'
        update_existing: If true, existing members are updated with the provided data (default true).
            If false, existing members are skipped and counted as errors.

    Returns:
        JSON with fields: new_members, updated_members, errors, total_created, total_updated, error_count.

    Example:
        batch_subscribe(list_id="abc123def4", members_json='[{"email_address":"a@b.com","status":"subscribed"}]')
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
    """Update audience settings such as name, default campaign sender, and permission reminder.

    Use this tool to change audience-level defaults that apply to new campaigns. This does not
    affect campaigns already created. Only provided fields are updated; omitted fields remain unchanged.
    Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        name: New audience name.
        from_name: Default 'from' name for campaigns sent to this audience.
        from_email: Default 'from' email for campaigns sent to this audience.
        subject: Default email subject line for new campaigns.
        permission_reminder: Permission reminder text shown to subscribers explaining why they receive emails.

    Returns:
        JSON with fields: id, name, permission_reminder, campaign_defaults.

    Example:
        update_audience(list_id="abc123def4", name="VIP Newsletter") -> {"id": "abc123def4", "name": "VIP Newsletter", ...}
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

    Use this tool to start building a new email campaign. The campaign is created in 'save' (draft)
    status. After creating, use set_campaign_content to add HTML content, then send_campaign or
    schedule_campaign to deliver it. Respects read-only and dry-run modes.

    Args:
        list_id: The audience/list ID to send to (e.g. 'abc123def4'). Use list_audiences to find IDs.
        subject_line: The subject line recipients will see in their inbox.
        title: Internal title for organizing campaigns in Mailchimp (defaults to subject_line).
        preview_text: Preview text shown after the subject line in inbox (also called preheader).
        from_name: The sender name on the email. Falls back to audience default if omitted.
        reply_to: The reply-to email address. Falls back to audience default if omitted.
        segment_id: Saved segment ID to target. Only members in this segment will receive the email.
            Use list_segments to find segment IDs.

    Returns:
        JSON with fields: id (the new campaign ID), status, title, subject_line, web_id.

    Example:
        create_campaign(list_id="abc123", subject_line="Spring Sale", preview_text="20% off everything")
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

    Use this tool to modify a campaign's subject line, sender, or segment targeting before sending.
    Only works on campaigns in 'save' (draft) status. Only provided fields are updated; omitted
    fields remain unchanged. Respects read-only and dry-run modes.

    Args:
        campaign_id: The campaign ID to update (e.g. 'abc123def4').
        subject_line: New subject line for the email.
        title: New internal title for organizing in Mailchimp.
        preview_text: New preview/preheader text.
        from_name: New sender name.
        reply_to: New reply-to email address.
        list_id: Audience/list ID. Required when changing segment_id.
        segment_id: Saved segment ID to target. Use list_segments to find IDs.

    Returns:
        JSON with fields: id, status, settings, recipients.

    Example:
        update_campaign(campaign_id="abc123", subject_line="Updated Subject Line")
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
    """Set the full HTML content of a campaign draft, replacing any existing content.

    Use this tool after create_campaign to add the email body. The campaign must be in 'save' (draft)
    status. This replaces any existing content entirely. Respects read-only and dry-run modes.

    Args:
        campaign_id: The campaign ID (e.g. 'abc123def4').
        html: The complete HTML content for the email body. Must be valid HTML including
            any inline CSS needed for email rendering.

    Returns:
        JSON with fields: status ("content_set"), campaign_id.

    Example:
        set_campaign_content(campaign_id="abc123", html="<html><body><h1>Hello!</h1></body></html>")
    """
    if (guard := _guard_write(action="set campaign content", campaign_id=campaign_id)):
        return guard
    data = mc_request(f"/campaigns/{campaign_id}/content", body={"html": html}, method="PUT")
    return json.dumps({"status": "content_set", "campaign_id": campaign_id}, indent=2)


@mcp.tool()
def schedule_campaign(campaign_id: str, schedule_time: str) -> str:
    """Schedule a campaign for sending at a specific future time.

    Use this tool to schedule a draft campaign for later delivery. The campaign must have content
    set via set_campaign_content and be in 'save' status. Use unschedule_campaign to cancel.
    Use send_campaign instead for immediate delivery. Respects read-only and dry-run modes.

    Args:
        campaign_id: The campaign ID (e.g. 'abc123def4').
        schedule_time: When to send the campaign. Format: ISO 8601 datetime in UTC
            (e.g. '2025-06-15T14:00:00Z'). Must be in the future.

    Returns:
        JSON with fields: status ("scheduled"), campaign_id, schedule_time.

    Example:
        schedule_campaign(campaign_id="abc123", schedule_time="2025-06-15T14:00:00Z")
    """
    if (guard := _guard_write(action="schedule campaign", campaign_id=campaign_id, schedule_time=schedule_time)):
        return guard
    mc_request(f"/campaigns/{campaign_id}/actions/schedule", body={"schedule_time": schedule_time}, method="POST")
    return json.dumps({"status": "scheduled", "campaign_id": campaign_id, "schedule_time": schedule_time}, indent=2)


@mcp.tool()
def unschedule_campaign(campaign_id: str) -> str:
    """Unschedule a previously scheduled campaign, returning it to draft ('save') status.

    Use this tool to cancel a scheduled send. The campaign must be in 'schedule' status.
    After unscheduling, the campaign can be edited and rescheduled. Respects read-only and dry-run modes.

    Args:
        campaign_id: The campaign ID to unschedule (e.g. 'abc123def4').

    Returns:
        JSON with fields: status ("unscheduled"), campaign_id.

    Example:
        unschedule_campaign(campaign_id="abc123")
    """
    if (guard := _guard_write(action="unschedule campaign", campaign_id=campaign_id)):
        return guard
    mc_request(f"/campaigns/{campaign_id}/actions/unschedule", method="POST")
    return json.dumps({"status": "unscheduled", "campaign_id": campaign_id}, indent=2)


@mcp.tool()
def replicate_campaign(campaign_id: str) -> str:
    """Duplicate an existing campaign, creating a new draft copy with the same settings, recipients, and content.

    Use this tool to clone a successful campaign as a starting point for a new send, avoiding
    the need to recreate settings manually. The new campaign is created in 'save' (draft) status
    and can be modified via update_campaign or set_campaign_content before sending. Works on
    campaigns of any status (draft, scheduled, or sent). Use create_campaign instead to build
    a campaign from scratch. This is a write operation that creates a new campaign. Respects
    read-only and dry-run modes.

    Args:
        campaign_id: The campaign ID to replicate (e.g. 'abc123def4'). Use list_campaigns
            to find IDs.

    Returns:
        JSON with fields: id (the new campaign's ID, different from the original), status
        ('save'), title, web_id (for opening in Mailchimp's web UI).

    Example:
        replicate_campaign(campaign_id="abc123") -> {"id": "def456", "status": "save", "title": "Spring Sale (copy)", ...}
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
    """Permanently delete a campaign. This action is irreversible.

    Use this tool to remove a draft or scheduled campaign. Only works on campaigns that have not
    been sent (status 'save' or 'schedule'). Sent campaigns cannot be deleted. Respects read-only
    and dry-run modes.

    Args:
        campaign_id: The campaign ID to delete (e.g. 'abc123def4').

    Returns:
        JSON with fields: status ("deleted"), campaign_id.

    Example:
        delete_campaign(campaign_id="abc123")
    """
    if (guard := _guard_write(action="delete campaign", campaign_id=campaign_id)):
        return guard
    mc_request(f"/campaigns/{campaign_id}", method="DELETE")
    return json.dumps({"status": "deleted", "campaign_id": campaign_id}, indent=2)


@mcp.tool()
def send_campaign(campaign_id: str) -> str:
    """Send a campaign immediately to all recipients. This action is irreversible.

    Use this tool for immediate delivery. The campaign must have HTML content set (via
    set_campaign_content) and be in 'save' (draft) status. Use schedule_campaign instead
    to send at a future time. Use send_test_email first to preview. Respects read-only and
    dry-run modes.

    Args:
        campaign_id: The campaign ID to send (e.g. 'abc123def4').

    Returns:
        JSON with fields: status ("sent"), campaign_id.

    Example:
        send_campaign(campaign_id="abc123")
    """
    if (guard := _guard_write(action="send campaign", campaign_id=campaign_id)):
        return guard
    mc_request(f"/campaigns/{campaign_id}/actions/send", method="POST")
    return json.dumps({"status": "sent", "campaign_id": campaign_id}, indent=2)


@mcp.tool()
def send_test_email(campaign_id: str, test_emails: str, send_type: str = "html") -> str:
    """Send a test/preview email for a campaign to specific email addresses without sending to the full audience.

    Use this tool to preview a campaign before sending to real recipients. The campaign must have
    content set. Test emails do not count against send limits and are not tracked in reports.
    Respects read-only and dry-run modes.

    Args:
        campaign_id: The campaign ID (e.g. 'abc123def4').
        test_emails: Comma-separated email addresses to send the test to (e.g. 'me@co.com,team@co.com').
        send_type: Format of the test email. Valid values: 'html' (default), 'plaintext'.

    Returns:
        JSON with fields: status ("test_sent"), campaign_id, test_emails.

    Example:
        send_test_email(campaign_id="abc123", test_emails="me@company.com")
    """
    if (guard := _guard_write(action="send test email", campaign_id=campaign_id)):
        return guard
    email_list = [e.strip() for e in test_emails.split(",")]
    body = {"test_emails": email_list, "send_type": send_type}
    mc_request(f"/campaigns/{campaign_id}/actions/test", body=body, method="POST")
    return json.dumps({"status": "test_sent", "campaign_id": campaign_id, "test_emails": email_list}, indent=2)


@mcp.tool()
def cancel_send(campaign_id: str) -> str:
    """Cancel a campaign that is currently in the process of sending.

    Use this tool to stop a campaign mid-send. Only works on campaigns with status 'sending'.
    Recipients who already received the email will not be affected. This cannot undo already-delivered
    emails. Respects read-only and dry-run modes.

    Args:
        campaign_id: The campaign ID to cancel (e.g. 'abc123def4').

    Returns:
        JSON with fields: status ("cancelled"), campaign_id.

    Example:
        cancel_send(campaign_id="abc123")
    """
    if (guard := _guard_write(action="cancel campaign send", campaign_id=campaign_id)):
        return guard
    mc_request(f"/campaigns/{campaign_id}/actions/cancel-send", method="POST")
    return json.dumps({"status": "cancelled", "campaign_id": campaign_id}, indent=2)


# --- Write Tools: Tags & Segments ---

@mcp.tool()
def create_segment(list_id: str, name: str, static: bool = True, match: Optional[str] = None, conditions_json: Optional[str] = None) -> str:
    """Create a new segment or tag in an audience.

    Use this tool to create either a static segment (tag) for manual member management, or a
    dynamic (saved) segment with filter conditions for automatic membership. For static segments,
    use add_members_to_segment afterward to add members. Use tag_member instead to apply
    tags to individual members one at a time. Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        name: Display name for the segment or tag.
        static: If true (default), creates a static segment (tag) with manual membership.
            If false, creates a dynamic segment using match/conditions_json filters.
        match: Condition match type for dynamic segments. Valid values: 'all' (every condition
            must match), 'any' (at least one condition must match). Required when static=false.
        conditions_json: JSON string of conditions array for dynamic segments.
            Example: '[{"condition_type":"TextMerge","field":"merge_fields/FNAME","op":"is","value":"John"}]'

    Returns:
        JSON with fields: id (the new segment ID), name, member_count, type, options.

    Example:
        create_segment(list_id="abc123", name="VIP Customers")
        create_segment(list_id="abc123", name="Johns", static=False, match="all", conditions_json='[{"condition_type":"TextMerge","field":"merge_fields/FNAME","op":"is","value":"John"}]')
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
    """Delete a segment or tag from an audience. This action is irreversible.

    Use this tool to remove a segment you no longer need. The segment and its association with
    members will be removed. Members themselves are not deleted from the audience. Respects
    read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        segment_id: The segment/tag ID to delete (numeric, e.g. '12345').

    Returns:
        JSON with fields: status ("deleted"), segment_id.

    Example:
        delete_segment(list_id="abc123", segment_id="12345")
    """
    if (guard := _guard_write(action="delete segment", list_id=list_id, segment_id=segment_id)):
        return guard
    mc_request(f"/lists/{list_id}/segments/{segment_id}", method="DELETE")
    return json.dumps({"status": "deleted", "segment_id": segment_id}, indent=2)


@mcp.tool()
def add_members_to_segment(list_id: str, segment_id: str, emails: str) -> str:
    """Add members to a static segment or tag by email address.

    Use this tool to add multiple members to an existing static segment at once. Only works on
    static segments (tags), not dynamic (saved) segments. Members must already exist in the audience.
    Use tag_member instead to manage tags on a single member. Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        segment_id: The static segment/tag ID (numeric, e.g. '12345').
        emails: Comma-separated email addresses to add (e.g. 'a@co.com,b@co.com').

    Returns:
        JSON with fields: total_added, total_removed, errors.

    Example:
        add_members_to_segment(list_id="abc123", segment_id="12345", emails="jane@co.com,john@co.com")
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
    """Remove members from a static segment or tag by email address.

    Use this tool to remove multiple members from a static segment at once. This only removes
    the segment association; members remain in the audience. Only works on static segments (tags),
    not dynamic (saved) segments. Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        segment_id: The static segment/tag ID (numeric, e.g. '12345').
        emails: Comma-separated email addresses to remove (e.g. 'a@co.com,b@co.com').

    Returns:
        JSON with fields: total_added, total_removed, errors.

    Example:
        remove_members_from_segment(list_id="abc123", segment_id="12345", emails="jane@co.com")
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
    """Update a segment's name or filter conditions.

    Use this tool to rename a segment or change its dynamic filter conditions. Only provided fields
    are updated; omitted fields remain unchanged. Use add_members_to_segment or
    remove_members_from_segment to manage membership of static segments. Respects read-only
    and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        segment_id: The segment ID to update (numeric, e.g. '12345').
        name: New display name for the segment.
        match: Condition match type for dynamic segments. Valid values: 'all', 'any'.
        conditions_json: JSON string of conditions array for dynamic segments.
            Example: '[{"condition_type":"TextMerge","field":"merge_fields/FNAME","op":"is","value":"John"}]'

    Returns:
        JSON with fields: id, name, member_count, type, options.

    Example:
        update_segment(list_id="abc123", segment_id="12345", name="Premium VIP")
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
    """Get detailed information about a specific segment, including filter conditions for dynamic segments.

    Use this tool to inspect a segment's conditions or check its member count. Use list_segments
    to browse all segments, or list_segment_members to see individual members in the segment.
    Read-only. Does not modify data.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        segment_id: The segment ID (numeric, e.g. '12345'). Use list_segments to find IDs.

    Returns:
        JSON with fields: id, name, member_count, type ('static' or 'saved'), created_at,
        updated_at, options (filter conditions for dynamic segments).

    Example:
        get_segment(list_id="abc123", segment_id="12345") -> {"id": 12345, "name": "VIP", "member_count": 150, ...}
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
    """List individual members belonging to a specific segment or tag.

    Use this tool to see who is in a segment. Use list_audience_members to browse all members
    of the full audience instead. Read-only. Does not modify data.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        segment_id: The segment ID (numeric, e.g. '12345'). Use list_segments to find IDs.
        count: Number of members to return (max 1000, default 20).
        offset: Pagination offset for retrieving additional pages.

    Returns:
        JSON with total_items and members array (id, email_address, status, full_name, merge_fields).

    Example:
        list_segment_members(list_id="abc123", segment_id="12345", count=50)
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
    """List merge fields (custom data fields like FNAME, LNAME, COMPANY) defined for an audience.

    Use this tool to discover available merge fields and their tags before adding or updating
    members. Default merge fields (FNAME, LNAME, ADDRESS, PHONE) are always present.
    Use create_merge_field to add custom fields. Read-only. Does not modify data.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        count: Number of merge fields to return (max 1000, default 50).
        offset: Pagination offset for retrieving additional pages.

    Returns:
        JSON with total_items and merge_fields array (merge_id, tag, name, type, required,
        default_value, options).

    Example:
        list_merge_fields(list_id="abc123") -> {"total_items": 6, "merge_fields": [{"tag": "FNAME", "name": "First Name", ...}]}
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
    """Create a new custom merge field in an audience for storing additional member data.

    Use this tool to add custom data fields beyond the default FNAME/LNAME/ADDRESS/PHONE.
    Once created, the field can be populated per-member via add_member or update_member using
    the tag name. The field type cannot be changed after creation. Respects read-only and
    dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        name: Display name for the field (e.g. 'Company Name').
        type: Field type. Valid values: 'text', 'number', 'address', 'date', 'birthday',
            'phone', 'url', 'imageurl', 'zip', 'dropdown', 'radio'. Cannot be changed after creation.
        tag: Short uppercase tag name used to reference this field (e.g. 'COMPANY'). Max 10 chars.
            Auto-generated from name if omitted.
        required: Whether the field is required when subscribing (default false).
        default_value: Default value for new subscribers.
        choices: Comma-separated choices for 'dropdown' or 'radio' types (e.g. 'Small,Medium,Large').

    Returns:
        JSON with fields: merge_id, tag, name, type, required.

    Example:
        create_merge_field(list_id="abc123", name="Company", type="text", tag="COMPANY")
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
    """Update an existing merge field's name, default value, or options.

    Use this tool to rename a field, change its default value, or update dropdown/radio choices.
    The field type cannot be changed after creation. Only provided fields are updated.
    Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        merge_id: The merge field ID to update (numeric). Use list_merge_fields to find IDs.
        name: New display name for the field.
        required: Whether the field is required when subscribing.
        default_value: New default value for new subscribers.
        choices: New comma-separated choices for 'dropdown' or 'radio' types (e.g. 'Small,Medium,Large').

    Returns:
        JSON with fields: merge_id, tag, name, type, required.

    Example:
        update_merge_field(list_id="abc123", merge_id="5", name="Organization")
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
    """Delete a custom merge field from an audience. This action is irreversible.

    Use this tool to remove a custom field you no longer need. All data stored in this field
    for every member in the audience will be permanently lost. Default merge fields (FNAME,
    LNAME, ADDRESS, PHONE) cannot be deleted. Use list_merge_fields to find merge_id values.
    Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        merge_id: The merge field ID to delete (numeric). Use list_merge_fields to find IDs.

    Returns:
        JSON with fields: status ("deleted"), merge_id.

    Example:
        delete_merge_field(list_id="abc123", merge_id="5")
    """
    if (guard := _guard_write(action="delete merge field", list_id=list_id, merge_id=merge_id)):
        return guard
    mc_request(f"/lists/{list_id}/merge-fields/{merge_id}", method="DELETE")
    return json.dumps({"status": "deleted", "merge_id": merge_id}, indent=2)


# --- Read/Write Tools: Interest Categories & Groups ---

@mcp.tool()
def list_interest_categories(list_id: str, count: int = 50, offset: int = 0) -> str:
    """List interest categories (groups) defined for an audience.

    Interest categories are containers for interest options that subscribers can select (e.g.
    a category "Preferred Topics" with interests "Tech", "Sports", "Music"). Use this tool to
    discover category IDs, then use list_interests to see the options within each category.
    Read-only. Does not modify data.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        count: Number of categories to return (max 1000, default 50).
        offset: Pagination offset for retrieving additional pages.

    Returns:
        JSON with total_items and categories array (id, title, type, list_id).

    Example:
        list_interest_categories(list_id="abc123") -> {"total_items": 2, "categories": [{"id": "abc", "title": "Topics", ...}]}
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

    Use this tool to create a container for interest options. After creating, use create_interest
    to add individual options within the category. The type determines how subscribers interact
    with it on signup forms. Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        title: Display title for the category (e.g. 'Preferred Topics').
        type: How the category appears on signup forms. Valid values: 'checkboxes' (multi-select),
            'dropdown' (single-select), 'radio' (single-select), 'hidden' (not shown on forms).

    Returns:
        JSON with fields: id, title, type, list_id.

    Example:
        create_interest_category(list_id="abc123", title="Newsletter Preferences", type="checkboxes")
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
    """List interest options within a specific interest category, with subscriber counts.

    Use this tool after list_interest_categories to see the individual options (e.g. "Tech",
    "Sports") within a category. Interest IDs are needed when setting member preferences.
    Read-only. Does not modify data.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        category_id: The interest category ID. Use list_interest_categories to find IDs.
        count: Number of interests to return (max 1000, default 50).
        offset: Pagination offset for retrieving additional pages.

    Returns:
        JSON with total_items and interests array (id, name, subscriber_count, display_order).

    Example:
        list_interests(list_id="abc123", category_id="cat456") -> {"total_items": 3, "interests": [{"name": "Tech", ...}]}
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
    """Create a new interest option within an interest category.

    Use this tool after create_interest_category to add selectable options (e.g. add "Tech"
    to a "Topics" category). Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        category_id: The interest category ID. Use list_interest_categories to find IDs.
        name: Display name for the interest option (e.g. 'Tech', 'Sports').

    Returns:
        JSON with fields: id, name, subscriber_count.

    Example:
        create_interest(list_id="abc123", category_id="cat456", name="Technology")
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
    """Delete an interest category and all its interest options. This action is irreversible.

    Use this tool to remove an entire category with all its options at once. All interests
    within the category and their subscriber associations will be removed. Subscribers
    themselves are not affected. Use delete_interest instead to remove a single option within
    a category. Use list_interest_categories to find category IDs. Respects read-only and
    dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        category_id: The interest category ID to delete. Use list_interest_categories to find IDs.

    Returns:
        JSON with fields: status ("deleted"), category_id.

    Example:
        delete_interest_category(list_id="abc123", category_id="cat456")
    """
    if (guard := _guard_write(action="delete interest category", list_id=list_id, category_id=category_id)):
        return guard
    mc_request(f"/lists/{list_id}/interest-categories/{category_id}", method="DELETE")
    return json.dumps({"status": "deleted", "category_id": category_id}, indent=2)


@mcp.tool()
def delete_interest(list_id: str, category_id: str, interest_id: str) -> str:
    """Delete a single interest option from an interest category. This action is irreversible.

    Use this tool to remove one specific option while keeping the category and other options
    intact. The interest and its subscriber associations will be removed. Use
    delete_interest_category instead to remove the entire category with all its options.
    Use list_interests to find interest IDs. Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        category_id: The interest category ID.
        interest_id: The interest option ID to delete. Use list_interests to find IDs.

    Returns:
        JSON with fields: status ("deleted"), interest_id.

    Example:
        delete_interest(list_id="abc123", category_id="cat456", interest_id="int789")
    """
    if (guard := _guard_write(action="delete interest", list_id=list_id, category_id=category_id, interest_id=interest_id)):
        return guard
    mc_request(f"/lists/{list_id}/interest-categories/{category_id}/interests/{interest_id}", method="DELETE")
    return json.dumps({"status": "deleted", "interest_id": interest_id}, indent=2)


# --- Read/Write Tools: Webhooks ---

@mcp.tool()
def list_webhooks(list_id: str) -> str:
    """List all webhooks configured for an audience, showing their URLs, events, and sources.

    Use this tool to audit existing webhook integrations or find webhook IDs before updating
    or deleting them. Webhooks send HTTP POST requests to external URLs when audience events
    occur. Read-only. Does not modify data.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').

    Returns:
        JSON with total_items and webhooks array (id, url, events, sources, list_id).

    Example:
        list_webhooks(list_id="abc123") -> {"total_items": 1, "webhooks": [{"url": "https://example.com/hook", ...}]}
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
    """Create a webhook for an audience that sends HTTP POST requests when member events occur.

    Use this tool to set up real-time notifications to an external URL. The URL must be publicly
    accessible and respond to a validation GET request. If events or sources are omitted,
    all events/sources are enabled by default. Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        url: The publicly accessible URL to receive webhook POST requests (e.g. 'https://example.com/hook').
        events: Comma-separated events to listen for. Valid values: 'subscribe', 'unsubscribe',
            'profile', 'cleaned', 'upemail', 'campaign'. All enabled if omitted.
        sources: Comma-separated sources to filter by. Valid values: 'user' (subscriber actions),
            'admin' (Mailchimp UI), 'api' (API calls). All enabled if omitted.

    Returns:
        JSON with fields: id, url, events, sources.

    Example:
        create_webhook(list_id="abc123", url="https://example.com/hook", events="subscribe,unsubscribe")
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
    """Delete a webhook from an audience. This action is irreversible.

    Use this tool to stop sending event notifications to an external URL. The external URL
    will immediately stop receiving notifications for this audience. Use list_webhooks to find
    webhook IDs. Use create_webhook to set up a new webhook. Respects read-only and dry-run
    modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        webhook_id: The webhook ID to delete. Use list_webhooks to find IDs.

    Returns:
        JSON with fields: status ("deleted"), webhook_id.

    Example:
        delete_webhook(list_id="abc123", webhook_id="wh789")
    """
    if (guard := _guard_write(action="delete webhook", list_id=list_id, webhook_id=webhook_id)):
        return guard
    mc_request(f"/lists/{list_id}/webhooks/{webhook_id}", method="DELETE")
    return json.dumps({"status": "deleted", "webhook_id": webhook_id}, indent=2)


# --- Read Tools: Detailed Reports ---

@mcp.tool()
def get_email_activity(campaign_id: str, count: int = 20, offset: int = 0) -> str:
    """Get the full activity timeline for each recipient of a campaign, showing every open, click, and bounce event.

    Use this tool to see exactly what each recipient did and when. Each recipient's activity
    is a chronological list of actions (open, click, bounce). Use get_open_details instead if
    you only need open data. Use get_campaign_report instead for aggregate totals (total opens,
    clicks, bounces across all recipients). Use get_campaign_recipients instead if you only
    need delivery status without detailed activity. Only available for sent campaigns.
    Read-only. Does not modify data.

    Args:
        campaign_id: The Mailchimp campaign ID (e.g. 'abc123def4'). Must be a sent campaign.
        count: Number of recipient records to return (1-1000, default 20). Each record
            contains all activity for one recipient.
        offset: Pagination offset for retrieving additional pages. Use when total_items
            exceeds count.

    Returns:
        JSON with total_items and emails array. Each entry includes: email_address and
        activity array where each activity has action ('open', 'click', 'bounce'),
        timestamp (ISO 8601), and url (for click actions).

    Example:
        get_email_activity(campaign_id="abc123", count=50) -> {"total_items": 5000, "emails": [{"email_address": "jane@co.com", "activity": [{"action": "open", "timestamp": "2025-06-01T10:00:00Z"}, ...]}]}
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
    """Get per-recipient open data for a campaign showing who opened, when, and how many times.

    Use this tool to identify engaged subscribers or analyze open timing patterns. Use
    get_campaign_report for aggregate open rates, or get_email_activity for all activity types
    (opens, clicks, bounces) combined per recipient. Read-only. Does not modify data.

    Args:
        campaign_id: The Mailchimp campaign ID (e.g. 'abc123def4').
        count: Number of records to return (max 1000, default 20).
        offset: Pagination offset for retrieving additional pages.

    Returns:
        JSON with total_items and members array (email_address, opens_count, opens array
        with timestamps).

    Example:
        get_open_details(campaign_id="abc123", count=100)
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
    """Get the delivery roster for a sent campaign showing each recipient's delivery status and open count.

    Use this tool to verify exactly who received a campaign and whether they opened it. Only
    available for campaigns that have been sent. Use get_email_activity instead for detailed
    per-recipient actions (clicks, bounces, opens with timestamps). Use get_campaign_report
    instead for aggregate metrics (total opens, clicks, bounces). Do not use this for draft
    or scheduled campaigns; they have no recipients yet. Read-only. Does not modify data.

    Args:
        campaign_id: The Mailchimp campaign ID (e.g. 'abc123def4'). Must be a sent campaign.
        count: Number of recipients to return (1-1000, default 20). Use with offset to
            paginate through large audiences.
        offset: Pagination offset for retrieving additional pages. Use when total_items
            exceeds count.

    Returns:
        JSON with total_items (total recipients) and recipients array. Each recipient
        includes: email_address, status ('sent', 'hard' bounce, 'soft' bounce),
        open_count (number of times opened), last_open (ISO 8601 timestamp or null).

    Example:
        get_campaign_recipients(campaign_id="abc123", count=100) -> {"total_items": 5000, "recipients": [{"email_address": "jane@co.com", "status": "sent", "open_count": 3, ...}]}
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
    """Get members who unsubscribed as a result of a specific campaign, with their reasons.

    Use this tool to analyze unsubscribe causes after a campaign. Use get_campaign_report for
    the aggregate unsubscribe count. Read-only. Does not modify data.

    Args:
        campaign_id: The Mailchimp campaign ID (e.g. 'abc123def4').
        count: Number of records to return (max 1000, default 20).
        offset: Pagination offset for retrieving additional pages.

    Returns:
        JSON with total_items and unsubscribes array (email_address, reason, timestamp).

    Example:
        get_campaign_unsubscribes(campaign_id="abc123")
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
    """Get campaign performance broken down by email domain (gmail.com, outlook.com, yahoo.com, etc.).

    Use this tool to identify deliverability issues with specific email providers or compare
    engagement across domains. Use get_campaign_report for overall aggregate metrics. Read-only.
    Does not modify data.

    Args:
        campaign_id: The Mailchimp campaign ID (e.g. 'abc123def4').

    Returns:
        JSON with total_items and domains array (domain, emails_sent, bounces, opens, clicks, unsubs).

    Example:
        get_domain_performance(campaign_id="abc123") -> {"domains": [{"domain": "gmail.com", "opens": 500, ...}]}
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
    """Get e-commerce product activity for a campaign showing revenue and orders per product.

    Use this tool to measure campaign ROI by product. Requires an active e-commerce store
    integration (Shopify, WooCommerce, etc.). Returns empty results if no e-commerce store
    is connected. Use list_ecommerce_stores to verify integration status. Read-only. Does not
    modify data.

    Args:
        campaign_id: The Mailchimp campaign ID (e.g. 'abc123def4').
        count: Number of products to return (max 1000, default 20).
        offset: Pagination offset for retrieving additional pages.

    Returns:
        JSON with total_items and products array (title, sku, image_url, total_revenue, total_purchased).

    Example:
        get_ecommerce_product_activity(campaign_id="abc123")
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
    """Get child report data for A/B test variants, variate campaigns, or RSS-driven campaign items.

    Use this tool only for campaigns that have sub-reports: A/B tests (shows per-variant
    performance), variate campaigns (shows each combination's results), or RSS campaigns
    (shows per-item send data). For standard single-send regular campaigns, this returns
    empty results; use get_campaign_report instead for those. Use get_campaign_details first
    to check the campaign type before calling this. Read-only. Does not modify data.

    Args:
        campaign_id: The Mailchimp campaign ID (e.g. 'abc123def4'). Should be an A/B test,
            variate, or RSS campaign for meaningful results.

    Returns:
        JSON with the sub-reports data structure. Format varies by campaign type: A/B tests
        include per-variant opens/clicks/winner data; RSS campaigns include per-item
        send stats. Returns empty or minimal data for regular campaigns.

    Example:
        get_campaign_sub_reports(campaign_id="abc123") -> {"sub_reports": [{"id": "variant_a", "opens": 150, "clicks": 30, ...}]}
    """
    data = mc_request(f"/reports/{campaign_id}/sub-reports")
    return json.dumps(data, indent=2)


# --- Read Tools: Member Activity ---

@mcp.tool()
def get_member_activity(list_id: str, email_address: str, count: int = 20) -> str:
    """Get the email interaction history of a specific member (opens, clicks, bounces across campaigns).

    Use this tool to see a single member's engagement over time. This shows email-related actions
    (opens, clicks, bounces). Use get_member_events instead for custom API-triggered events,
    or get_member_tags for tag assignments. Read-only. Does not modify data.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        email_address: Email address of the member to look up.
        count: Number of activity records to return (max 1000, default 20).

    Returns:
        JSON with email_address and activity array (action, timestamp, campaign_id, title).

    Example:
        get_member_activity(list_id="abc123", email_address="jane@co.com")
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
    """Get all tags currently assigned to a specific member.

    Use this tool to see which tags a member has. Use tag_member to add or remove tags,
    or list_segments to see all available tags in the audience. Read-only. Does not modify data.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        email_address: Email address of the member to look up.
        count: Number of tags to return (max 1000, default 50).

    Returns:
        JSON with email_address, total_items, and tags array (id, name, date_added).

    Example:
        get_member_tags(list_id="abc123", email_address="jane@co.com")
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
    """Get custom API-triggered events for a specific member.

    Use this tool to view events that were sent to Mailchimp via the Events API (e.g. "purchased",
    "signed_up"). These are different from email activity (opens, clicks); use get_member_activity
    for email interactions instead. Read-only. Does not modify data.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4').
        email_address: Email address of the member to look up.
        count: Number of events to return (max 1000, default 20).

    Returns:
        JSON with email_address, total_items, and events array (name, occurred_at, properties).

    Example:
        get_member_events(list_id="abc123", email_address="jane@co.com")
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
    """List all individual emails within an automation workflow, showing the sequence, subject lines, delays, and send counts.

    Use this tool to inspect what emails an automation sends and in what order. Each automation
    workflow contains one or more emails sent in sequence with configurable delays between them.
    Use list_automations first to find automation IDs. Use get_automation_email_queue to see
    which subscribers are queued for a specific email within the workflow. Do not confuse with
    get_email_activity, which shows per-recipient engagement for regular campaigns, not
    automations. Read-only. Does not modify data.

    Args:
        automation_id: The automation workflow ID (e.g. 'auto123'). Use list_automations
            to find IDs.

    Returns:
        JSON with total_items and emails array. Each email includes: id (use with
        get_automation_email_queue), position (order in sequence, starting at 1), status
        ('sending', 'paused', 'draft'), subject_line, title, emails_sent (total delivered),
        send_time, delay (time between trigger and send).

    Example:
        get_automation_emails(automation_id="auto123") -> {"total_items": 3, "emails": [{"id": "email1", "position": 1, "subject_line": "Welcome!", ...}]}
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
    """Get the queue of subscribers about to receive a specific automation email.

    Use this tool to see who is waiting to receive a particular email in a workflow and when
    it will be sent. Use get_automation_emails first to find the email_id within the workflow.
    Read-only. Does not modify data.

    Args:
        automation_id: The automation workflow ID (e.g. 'auto123'). Use list_automations to find IDs.
        email_id: The specific email ID within the automation. Use get_automation_emails to find IDs.

    Returns:
        JSON with total_items and queue array (email_address, next_send).

    Example:
        get_automation_email_queue(automation_id="auto123", email_id="email456")
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
    """Pause all emails in an automation workflow. This is reversible via start_automation.

    Use this tool to temporarily stop an automation from sending emails without losing queued
    subscribers. Subscribers currently in the queue will not receive further emails until the
    workflow is resumed via start_automation. New subscribers will still be added to the queue
    but will not receive emails while paused. Use list_automations to find automation IDs.
    Respects read-only and dry-run modes.

    Args:
        automation_id: The automation workflow ID (e.g. 'auto123'). Use list_automations to find IDs.

    Returns:
        JSON with fields: status ("paused"), automation_id.

    Example:
        pause_automation(automation_id="auto123")
    """
    if (guard := _guard_write(action="pause automation", automation_id=automation_id)):
        return guard
    mc_request(f"/automations/{automation_id}/actions/pause-all-emails", method="POST")
    return json.dumps({"status": "paused", "automation_id": automation_id}, indent=2)


@mcp.tool()
def start_automation(automation_id: str) -> str:
    """Start or resume all emails in an automation workflow.

    Use this tool to activate a new automation or resume a paused one. Queued subscribers will
    begin receiving emails again. Use pause_automation to temporarily stop the workflow. Use
    list_automations to find automation IDs and check current status. Respects read-only and
    dry-run modes.

    Args:
        automation_id: The automation workflow ID (e.g. 'auto123'). Use list_automations to find IDs.

    Returns:
        JSON with fields: status ("started"), automation_id.

    Example:
        start_automation(automation_id="auto123")
    """
    if (guard := _guard_write(action="start automation", automation_id=automation_id)):
        return guard
    mc_request(f"/automations/{automation_id}/actions/start-all-emails", method="POST")
    return json.dumps({"status": "started", "automation_id": automation_id}, indent=2)


# --- Read Tools: Landing Pages ---

@mcp.tool()
def list_landing_pages(count: int = 20, offset: int = 0) -> str:
    """List all landing pages in the account with their publication status, URLs, and associated audiences.

    Use this tool to browse landing pages created in Mailchimp, find their published URLs,
    or check their status. Landing pages are standalone web pages used for lead capture,
    promotions, or sign-ups. Use get_landing_page instead when you already have a page_id
    and need full details including description and tracking settings. Do not confuse with
    list_campaigns; landing pages are web pages, not emails. Read-only. Does not modify data.

    Args:
        count: Number of landing pages to return (1-1000, default 20).
        offset: Pagination offset for retrieving additional pages. Use when total_items
            exceeds count.

    Returns:
        JSON with total_items and landing_pages array. Each page includes: id (use with
        get_landing_page), name, title, status ('published', 'unpublished', 'draft'),
        url (public URL when published), published_at (ISO 8601), created_at (ISO 8601),
        list_id (associated audience).

    Example:
        list_landing_pages() -> {"total_items": 3, "landing_pages": [{"name": "Spring Sale", "status": "published", "url": "https://...", ...}]}
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
    """Get full details of a specific landing page including description, tracking, and timestamps.

    Use this tool when you have a page_id and need complete information. Use list_landing_pages
    to browse all pages. Read-only. Does not modify data.

    Args:
        page_id: The landing page ID. Use list_landing_pages to find IDs.

    Returns:
        JSON with fields: id, name, title, description, status, url, published_at, created_at,
        updated_at, list_id, tracking.

    Example:
        get_landing_page(page_id="page123")
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
    """List all connected e-commerce stores (Shopify, WooCommerce, etc.) with their platform and currency info.

    Use this tool to discover connected stores and their IDs before querying orders, products,
    or customers. Returns empty if no e-commerce integration is configured. Read-only. Does
    not modify data.

    Args:
        No parameters required.

    Returns:
        JSON with total_items and stores array (id, list_id, name, platform, domain,
        currency_code, money_format, created_at).

    Example:
        list_ecommerce_stores() -> {"total_items": 1, "stores": [{"name": "My Shop", "platform": "shopify", ...}]}
    """
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
    """List orders from a connected e-commerce store with customer, total, and fulfillment info.

    Use this tool to browse recent orders. Requires an active e-commerce integration.
    Use list_ecommerce_stores to find store IDs. Read-only. Does not modify data.

    Args:
        store_id: The e-commerce store ID. Use list_ecommerce_stores to find IDs.
        count: Number of orders to return (max 1000, default 20).
        offset: Pagination offset for retrieving additional pages.

    Returns:
        JSON with total_items and orders array (id, customer email, order_total, currency_code,
        financial_status, fulfillment_status, processed_at_foreign, lines_count).

    Example:
        list_store_orders(store_id="store123", count=50)
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
    """List products from a connected e-commerce store with titles, URLs, and variant counts.

    Use this tool to browse the product catalog synced from your e-commerce platform (Shopify,
    WooCommerce, etc.) to Mailchimp. Useful for verifying product sync status or finding product
    data for campaign content. Requires an active e-commerce integration; returns empty if none
    is configured. Use list_ecommerce_stores first to find store IDs and verify integration
    status. Use get_ecommerce_product_activity instead for campaign-level product revenue data.
    Read-only. Does not modify data.

    Args:
        store_id: The e-commerce store ID. Use list_ecommerce_stores to find IDs.
        count: Number of products to return (1-1000, default 20).
        offset: Pagination offset for retrieving additional pages. Use when total_items
            exceeds count.

    Returns:
        JSON with total_items and products array. Each product includes: id, title,
        url (product page link), vendor, image_url, variants_count.

    Example:
        list_store_products(store_id="store123", count=50) -> {"total_items": 200, "products": [{"title": "Blue T-Shirt", ...}]}
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
    """List customers from a connected e-commerce store with order counts and total spend.

    Use this tool to analyze customer purchasing behavior. Requires an active e-commerce
    integration. Use list_ecommerce_stores to find store IDs. Read-only. Does not modify data.

    Args:
        store_id: The e-commerce store ID. Use list_ecommerce_stores to find IDs.
        count: Number of customers to return (max 1000, default 20).
        offset: Pagination offset for retrieving additional pages.

    Returns:
        JSON with total_items and customers array (id, email_address, first_name, last_name,
        orders_count, total_spent, opt_in_status, created_at).

    Example:
        list_store_customers(store_id="store123", count=50)
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
    """List campaign folders used to organize campaigns in the Mailchimp dashboard.

    Use this tool to see how campaigns are organized into folders. Read-only. Does not
    modify data.

    Args:
        count: Number of folders to return (max 1000, default 50).
        offset: Pagination offset for retrieving additional pages.

    Returns:
        JSON with total_items and folders array (id, name, count of campaigns in folder).

    Example:
        list_campaign_folders() -> {"total_items": 3, "folders": [{"name": "Q1 2025", "count": 12, ...}]}
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
    """Run multiple API operations in a single asynchronous batch request.

    Use this tool for bulk operations that exceed the limits of other tools (e.g. batch_subscribe
    handles up to 500 members; use this for larger imports). Operations run asynchronously;
    use get_batch_status to check progress. Each operation runs independently and can include
    destructive operations. Respects read-only and dry-run modes.

    Args:
        operations: JSON string of operations array. Each operation requires: method (HTTP verb),
            path (API endpoint), and optionally body (JSON string).
            Example: '[{"method":"POST","path":"/lists/abc123/members/hash/tags","body":"{\"tags\":[{\"name\":\"VIP\",\"status\":\"active\"}]}"}]'

    Returns:
        JSON with fields: id (batch ID for status checks), status, total_operations, submitted_at.

    Example:
        create_batch(operations='[{"method":"GET","path":"/lists"}]')
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
    """Check the progress and completion status of an asynchronous batch operation.

    Use this tool after create_batch to poll for completion. Batch operations run
    asynchronously and may take minutes to complete depending on volume. Call this tool
    repeatedly until status changes to 'finished'. Do not use this tool for non-batch
    operations; use the individual tool's response directly instead. When the batch finishes,
    response_body_url contains a downloadable archive with per-operation results. Use
    list_batches instead to see all recent batch operations at once. Read-only. Does not
    modify data.

    Args:
        batch_id: The batch operation ID returned by create_batch (e.g. 'batch123abc').

    Returns:
        JSON with fields: id, status ('pending' = queued, 'started' = in progress,
        'finished' = complete), total_operations, finished_operations, errored_operations,
        submitted_at (ISO 8601), completed_at (ISO 8601, null if not finished),
        response_body_url (download link for results, only available when finished).

    Example:
        get_batch_status(batch_id="batch123") -> {"status": "finished", "total_operations": 100, "finished_operations": 100, "errored_operations": 2, ...}
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
    """List recent batch operations with their status and progress.

    Use this tool to find batch IDs or monitor multiple ongoing batch operations.
    Use get_batch_status for detailed progress on a specific batch. Read-only. Does not
    modify data.

    Args:
        count: Number of batch operations to return (max 1000, default 20).
        offset: Pagination offset for retrieving additional pages.

    Returns:
        JSON with total_items and batches array (id, status, total_operations, finished_operations,
        errored_operations, submitted_at, completed_at).

    Example:
        list_batches(count=10) -> {"total_items": 5, "batches": [{"id": "batch123", "status": "finished", ...}]}
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
