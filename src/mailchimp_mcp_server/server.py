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
    """Retrieve Mailchimp account details including name, contact info, total subscribers, and industry benchmarks.

    Use this to verify API connectivity or inspect account-level metrics. Typically the first
    call in a workflow. Do not use this as a health check; use ping instead (faster, no payload).
    Use list_audiences to get per-audience stats.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Returns:
        JSON with fields: account_name (string), email (account owner), first_name, last_name,
        total_subscribers (int, all audiences combined), industry_stats (object with open/click
        rate benchmarks for the account's industry). Returns an error object if the API key is
        invalid or missing.

    Example:
        get_account_info() -> {"account_name": "My Company", "total_subscribers": 5000, "industry_stats": {"open_rate": 0.21, ...}}
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
    """List audiences (lists) with subscriber counts and engagement rates.

    First step in most workflows to discover list_id values. Use get_audience_details for full
    stats of a known audience. Use search_members to find a specific member.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.

    Args:
        count: Audiences to return (1-1000, default 10). Most accounts have fewer than 10.
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and audiences array. Each: id (use as list_id), name, member_count,
        unsubscribe_count, open_rate (0-1), click_rate (0-1), date_created.
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
    """Retrieve full stats, subscribe URL, and rating for a specific audience.

    Use when you have a list_id and need detailed metrics or the public subscribe URL. Use
    list_audiences to browse all audiences and discover list_ids instead.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.
    Returns 404 error if list_id is invalid.

    Args:
        list_id: Audience/list ID (10-char alphanumeric, e.g. 'abc123def4'). Obtain from list_audiences.

    Returns:
        JSON with id, name, stats (member_count, unsubscribe_count, open_rate, click_rate),
        date_created, list_rating (0-5), subscribe_url_short.
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
    """List campaigns with metadata, send stats, and filtering by status or date.

    Use to browse campaigns and discover campaign IDs. Use get_campaign_details for full settings
    of a single campaign. Use get_campaign_report for post-send performance metrics. Use
    search_campaigns to find campaigns by keyword instead of browsing.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        count: Number of campaigns to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.
        status: Filter by status. Valid values: 'save' (draft), 'paused', 'schedule',
            'sending', 'sent'. Omit to return all statuses.
        since_send_time: Only return campaigns sent after this datetime. ISO 8601 format
            (e.g. '2025-01-01T00:00:00Z'). Only applies to sent campaigns.

    Returns:
        JSON with total_items and campaigns array. Each campaign: id, type ('regular', 'plaintext',
        'absplit', 'rss', 'variate'), status, title, subject_line, preview_text, send_time
        (ISO 8601 or null), emails_sent, list_id, list_name.

    Example:
        list_campaigns(count=10, status="sent") -> {"total_items": 42, "campaigns": [{"id": "abc123", "status": "sent", ...}]}
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
    """Retrieve full configuration of a specific campaign including settings, recipients, and tracking options.

    Use to inspect subject line, sender, audience targeting, or tracking settings. Use
    get_campaign_report instead for post-send performance (opens, clicks, bounces). Use
    list_campaigns or search_campaigns to find campaign IDs.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        campaign_id: The Mailchimp campaign ID (e.g. 'abc123def4'). Obtain from list_campaigns
            or search_campaigns.

    Returns:
        JSON with fields: id, type, status, settings (subject_line, title, from_name, reply_to),
        recipients (list_id, segment_opts), send_time (ISO 8601 or null), emails_sent, tracking
        (opens, html_clicks, text_clicks booleans). Returns error if campaign_id is invalid.

    Example:
        get_campaign_details(campaign_id="abc123def4") -> {"id": "abc123def4", "status": "sent", "settings": {"subject_line": "Spring Sale", ...}}
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
    """Retrieve aggregate performance metrics for a sent campaign: opens, clicks, bounces, benchmarks.

    High-level overview. Use get_campaign_click_details for per-link data, get_open_details for
    per-recipient opens, get_campaign_recipients for delivery status. Only works for sent campaigns.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.

    Args:
        campaign_id: Campaign ID (e.g. 'abc123def4'). Must be sent. Obtain from list_campaigns(status="sent").

    Returns:
        JSON with campaign_title, subject_line, emails_sent, abuse_reports, unsubscribed, send_time,
        opens (opens_total, unique_opens, open_rate 0-1), clicks (clicks_total, unique_clicks,
        click_rate), bounces, forwards, list_stats, industry_stats.
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
    """Retrieve per-link click data for a campaign showing which URLs were clicked and how many times.

    Use to analyze which links drove engagement. Use get_campaign_report instead for aggregate
    totals (opens, clicks, bounces). Use get_email_activity for per-recipient click timelines.
    Only works for sent campaigns.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        campaign_id: The Mailchimp campaign ID (e.g. 'abc123def4'). Must be a sent campaign.
        count: Number of URL results to return (1-1000, default 20).

    Returns:
        JSON with total_items and links array. Each link: url (string), total_clicks (int, includes
        repeat clicks), unique_clicks (int, one per subscriber), click_percentage (decimal 0-1).

    Example:
        get_campaign_click_details(campaign_id="abc123") -> {"total_items": 5, "links": [{"url": "https://example.com", "total_clicks": 120, "unique_clicks": 95, "click_percentage": 0.019}]}
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
    """List members of a specific audience with subscription status, merge fields, and engagement stats.

    Use to browse members of a known audience. Use search_members instead to find a specific
    person by email or name across all audiences. Use list_segment_members to list members of
    a specific segment/tag.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        count: Number of members to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.
        status: Filter by subscription status. Valid values: 'subscribed', 'unsubscribed',
            'cleaned', 'pending', 'transactional'. Omit to return all statuses.

    Returns:
        JSON with total_items and members array. Each member: id (MD5 hash of email), email_address,
        status, full_name, merge_fields (object with FNAME, LNAME, etc.), open_rate (decimal 0-1),
        click_rate (decimal 0-1), timestamp_opt (ISO 8601 opt-in time).

    Example:
        list_audience_members(list_id="abc123", count=50, status="subscribed") -> {"total_items": 5000, "members": [{"email_address": "jane@co.com", "status": "subscribed", ...}]}
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
    """Search for members across all audiences by email address or name, returning both exact and fuzzy matches.

    Use when looking for a specific person and you may not know which audience they belong to.
    Use list_audience_members instead to browse all members of a known audience. Use
    get_member_activity or get_member_tags after finding a member for engagement data.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        query: Search query. Full email address for exact match, or name/partial email for
            fuzzy search. Minimum 3 characters.
        list_id: Optional audience/list ID to restrict search to a single audience. Obtain
            from list_audiences.

    Returns:
        JSON with results array combining exact and fuzzy matches. Each result: email, status
        ('subscribed', 'unsubscribed', etc.), full_name, list_id (audience the member belongs to).
        Exact matches appear first.

    Example:
        search_members(query="john@example.com") -> {"results": [{"email": "john@example.com", "status": "subscribed", "list_id": "abc123", ...}]}
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
    """Retrieve monthly growth history for an audience (subscribes, unsubscribes, cleaned).

    Each record is one calendar month, ordered newest first. Use get_audience_details for
    current totals instead of historical trends.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.

    Args:
        list_id: Audience/list ID (10-char alphanumeric, e.g. 'abc123def4'). Obtain from list_audiences.
        count: Months to return (1-1000, default 12).

    Returns:
        JSON with list_id and history array. Each: month (YYYY-MM), subscribed, unsubscribed,
        reconfirm, cleaned, pending, transactional (all cumulative ints).
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
    """List automation workflows in the account with status and send counts.

    Returns all automations regardless of status (sending, paused, draft), ordered by creation
    date descending. Includes both Classic Automations and Customer Journeys. Use
    get_automation_emails for individual emails within a workflow.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.

    Args:
        count: Automations to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and automations array. Each: id, status ('sending'/'paused'/'draft'),
        title, emails_sent, start_time, create_time, list_id.
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
    """List email templates in the account (user-created and Mailchimp gallery templates).

    Use to browse templates and find template IDs. Use get_template_default_content to extract
    HTML from a template. Use create_template to add new templates. Do not use to find campaigns;
    use list_campaigns instead.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.

    Args:
        count: Templates to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and templates array. Each: id (int), name, type ('user'/'gallery'/
        'base'), date_created, active (boolean).
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
def get_template_default_content(template_id: str) -> str:
    """Retrieve the default HTML content of a template for use in campaign content.

    Use to extract a template's HTML before customizing it with set_campaign_content. Only works
    for user-created templates; gallery templates may return limited content. Use list_templates
    to find template IDs.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.
    Returns 404 error if template_id is invalid.

    Args:
        template_id: Template ID (numeric string, e.g. '12345'). Obtain from list_templates.

    Returns:
        JSON with html (string, full HTML content), sections (object with editable content blocks).
    """
    data = mc_request(f"/templates/{template_id}/default-content")
    return json.dumps({
        "html": data.get("html"),
        "sections": data.get("sections"),
    }, indent=2)


@mcp.tool()
def create_template(name: str, html: str, folder_id: Optional[str] = None) -> str:
    """Create a new reusable email template from HTML content.

    Use to save HTML email designs for reuse across campaigns. Retrieve template HTML later via
    get_template_default_content for use with set_campaign_content. Use list_templates to browse
    existing templates. Do not use for one-off emails; use set_campaign_content directly instead.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.

    Args:
        name: Display name for the template (e.g. 'Monthly Newsletter v2').
        html: Complete HTML content. Must be valid HTML with inline CSS for email client
            compatibility. Mailchimp merge tags (e.g. *|FNAME|*, *|UNSUB|*) are supported.
        folder_id: Optional template folder ID to organize the template. Obtain from the
            Mailchimp web UI.

    Returns:
        JSON with id (int, new template ID), name, type ('user'), active (boolean), date_created.
    """
    if (guard := _guard_write(action="create template", name=name)):
        return guard
    body: dict = {"name": name, "html": html}
    if folder_id:
        body["folder_id"] = folder_id
    data = mc_request("/templates", body=body, method="POST")
    return json.dumps({
        "id": data.get("id"),
        "name": data.get("name"),
        "type": data.get("type"),
        "active": data.get("active"),
        "date_created": data.get("date_created"),
    }, indent=2)


@mcp.tool()
def update_template(template_id: str, name: Optional[str] = None, html: Optional[str] = None) -> str:
    """Update an existing template's name or HTML content.

    Only provided fields are updated. Only works for user-created templates; gallery and base
    templates cannot be modified. Use create_template to create a new template instead of
    modifying a gallery template.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.
    Returns 404 error if template_id is invalid.

    Args:
        template_id: Template ID to update (numeric string, e.g. '12345'). Obtain from list_templates.
        name: New display name for the template.
        html: New HTML content. Replaces all existing content.

    Returns:
        JSON with id, name, type, active, date_edited.
    """
    if (guard := _guard_write(action="update template", template_id=template_id)):
        return guard
    body: dict = {}
    if name is not None:
        body["name"] = name
    if html is not None:
        body["html"] = html
    data = mc_request(f"/templates/{template_id}", body=body, method="PATCH")
    return json.dumps({
        "id": data.get("id"),
        "name": data.get("name"),
        "type": data.get("type"),
        "active": data.get("active"),
        "date_edited": data.get("date_edited"),
    }, indent=2)


@mcp.tool()
def delete_template(template_id: str) -> str:
    """Delete a user-created template permanently.

    Irreversible. Only works for user-created templates; gallery and base templates cannot be
    deleted. Does not affect campaigns already using this template's content. Use list_templates
    to find template IDs.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.
    Returns 404 error if template_id is invalid or is not a user template.

    Args:
        template_id: Template ID to delete (numeric string, e.g. '12345'). Must be type 'user'.

    Returns:
        JSON with status ("deleted"), template_id.
    """
    if (guard := _guard_write(action="delete template", template_id=template_id)):
        return guard
    mc_request(f"/templates/{template_id}", method="DELETE")
    return json.dumps({"status": "deleted", "template_id": template_id}, indent=2)


@mcp.tool()
def list_segments(list_id: str, count: int = 20, offset: int = 0) -> str:
    """List segments and tags for an audience with member counts and types.

    Use to discover segment IDs for campaign targeting or membership management. Returns both
    static (tags, manual) and dynamic (saved, auto-updated) segments. Use get_segment for full
    details including filter conditions.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.

    Args:
        list_id: Audience/list ID (10-char alphanumeric, e.g. 'abc123def4'). Obtain from list_audiences.
        count: Segments to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and segments array. Each: id (use as segment_id), name, member_count,
        type ('static'/'saved'), created_at, updated_at.
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
    """Add a new member to an audience with optional name and tags.

    Creates a new contact. Returns "Member Exists" error if already present. Choose the right
    member tool: add_member for new contacts, update_member to change profile/status of existing
    contacts, tag_member to manage tags on existing contacts, batch_subscribe for bulk add/update
    (up to 500), unsubscribe_member to opt out, delete_member for permanent GDPR removal. Side
    effect: status='pending' triggers a double opt-in confirmation email.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.

    Args:
        list_id: Audience/list ID (10-char alphanumeric, e.g. 'abc123def4'). Obtain from list_audiences.
        email_address: Email of the new member. Must not already exist in the audience.
        status: 'subscribed' (default), 'pending' (triggers opt-in email), 'unsubscribed', 'cleaned'.
        first_name: First name (FNAME merge field).
        last_name: Last name (LNAME merge field).
        tags: Comma-separated tag names (e.g. 'VIP,Newsletter'). Created automatically if new.

    Returns:
        JSON with id (MD5 hash of email), email_address, status, full_name.
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
    """Update a member's profile fields or subscription status. Does not manage tags.

    Only provided fields are updated; omitted fields remain unchanged. Idempotent: re-applying
    the same values is safe. Side effect: changing status to 'pending' triggers a re-confirmation
    email. Choose the right member tool: update_member for profile/status changes, tag_member for
    tag management, unsubscribe_member as shortcut for opt-out, add_member if the contact does
    not exist yet, batch_subscribe for bulk operations.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.
    Returns 404 error if member does not exist. Returns 400 if status transition is invalid
    (e.g. cleaned to subscribed).

    Args:
        list_id: Audience/list ID (10-char alphanumeric, e.g. 'abc123def4'). Obtain from list_audiences.
        email_address: Email of the member to update. Must exist in the audience.
        status: New status: 'subscribed', 'unsubscribed', 'cleaned', 'pending'.
        first_name: New first name (FNAME merge field).
        last_name: New last name (LNAME merge field).

    Returns:
        JSON with id, email_address, status, full_name.
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
    """Unsubscribe a member from an audience, preserving profile and history for reporting.

    Reversible via update_member(status='subscribed'). Use delete_member for permanent removal
    (GDPR). Returns 404 error if member does not exist.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.

    Args:
        list_id: Audience/list ID (10-char alphanumeric, e.g. 'abc123def4'). Obtain from list_audiences.
        email_address: Email of the member. Must be a valid email address and exist in the audience.

    Returns:
        JSON with email_address, status ("unsubscribed").
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
    """Permanently delete a member and all their data from an audience.

    Use only for complete data removal (e.g. GDPR right-to-erasure requests). All activity history,
    merge field data, and tag associations are permanently lost. Use unsubscribe_member instead to
    stop sending while preserving data for reporting. There is no undo.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). This operation is irreversible. Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        email_address: Email address of the member to permanently delete. Must exist in the audience.

    Returns:
        JSON with fields: status ("permanently_deleted"), email_address. Returns error if the
        member does not exist.

    Example:
        delete_member(list_id="abc123", email_address="jane@co.com") -> {"status": "permanently_deleted", "email_address": "jane@co.com"}
    """
    if (guard := _guard_write(action="permanently delete member", email_address=email_address, list_id=list_id)):
        return guard
    subscriber_hash = hashlib.md5(email_address.lower().encode()).hexdigest()
    mc_request(f"/lists/{list_id}/members/{subscriber_hash}/actions/delete-permanent", method="POST")
    return json.dumps({"status": "permanently_deleted", "email_address": email_address}, indent=2)


@mcp.tool()
def tag_member(list_id: str, email_address: str, tags_to_add: Optional[str] = None, tags_to_remove: Optional[str] = None) -> str:
    """Add or remove tags from a single member. Does not modify profile data or subscription status.

    Tags are case-insensitive free-form labels. Added tags are created automatically if new;
    removed tags are silently ignored if not present. Idempotent. Choose the right member tool:
    tag_member for per-member tag changes, add_members_to_segment for bulk-adding members to a
    tag/segment, add_member with tags param for tagging at signup, update_member for profile/status
    changes, get_member_tags to check current tags.

    Authenticated via API key (read scope required). Max 10 concurrent requests. Respects
    read-only and dry-run modes. Returns 404 error if the member does not exist.

    Args:
        list_id: Audience/list ID (10-char alphanumeric, e.g. 'abc123def4'). Obtain from list_audiences.
        email_address: Email of the member. Must exist in the audience.
        tags_to_add: Comma-separated tag names to add (e.g. 'VIP,Returning Customer').
        tags_to_remove: Comma-separated tag names to remove (e.g. 'Trial').

    Returns:
        JSON with status ("updated"), email_address, tags array with name and status 'active'/'inactive'.
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
    """Add or update up to 500 members in a single synchronous request.

    Use for bulk operations. Choose the right member tool: batch_subscribe for 2-500 members,
    add_member or update_member for a single member, create_batch for imports larger than 500.
    Side effect: members with status='pending' each receive a double opt-in confirmation email.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.

    Args:
        list_id: Audience/list ID (10-char alphanumeric, e.g. 'abc123def4'). Obtain from list_audiences.
        members_json: JSON array of members (max 500). Each requires email_address and status
            ('subscribed'/'unsubscribed'/'cleaned'/'pending'). Optional: merge_fields, tags.
        update_existing: If true (default), existing members are updated. If false, skipped as errors.

    Returns:
        JSON with new_members, updated_members, errors array, total_created, total_updated, error_count.
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
    """Update audience-level settings: name, default sender, subject, and permission reminder.

    Changes apply to newly created campaigns only; does not retroactively affect existing ones.
    Only provided fields are updated. Use get_audience_details to check current settings.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.

    Args:
        list_id: Audience/list ID (10-char alphanumeric, e.g. 'abc123def4'). Obtain from list_audiences.
        name: New audience display name (shown in Mailchimp UI and audience picker).
        from_name: Default sender name for new campaigns (e.g. 'Marketing Team'). Max 100 chars.
        from_email: Default sender email. Must be a verified sending domain in Mailchimp.
        subject: Default subject line for new campaigns (e.g. 'Monthly Update'). Max 150 chars.
        permission_reminder: Why subscribers receive emails (required by CAN-SPAM).

    Returns:
        JSON with id, name, permission_reminder, campaign_defaults (from_name, from_email, subject,
        language).
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
    """Create a new regular email campaign in draft status, optionally targeting a specific segment.

    Typical workflow: create_campaign -> set_campaign_content (add HTML body) -> send_test_email
    (preview) -> send_campaign or schedule_campaign (deliver). The campaign is created in 'save'
    (draft) status and cannot be sent until content is set. Use replicate_campaign instead to
    clone an existing campaign.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Respects read-only and dry-run modes.

    Args:
        list_id: The audience/list ID to send to (e.g. 'abc123def4'). Obtain from list_audiences.
        subject_line: Subject line recipients see in their inbox. Keep under 150 chars.
        title: Internal title for organizing in Mailchimp dashboard. Defaults to subject_line
            if omitted.
        preview_text: Preheader text shown after the subject line in inbox. Keep under 200 chars.
        from_name: Sender name on the email. Falls back to audience default if omitted.
        reply_to: Reply-to email address. Must be a verified domain. Falls back to audience default.
        segment_id: Saved segment ID to restrict recipients. Only members matching this segment
            receive the email. Obtain from list_segments. Omit to send to the full audience.

    Returns:
        JSON with fields: id (string, the new campaign ID for use with set_campaign_content,
        send_campaign, etc.), status ('save'), title, subject_line, web_id (int, for Mailchimp
        web UI link). Returns error if list_id is invalid.

    Example:
        create_campaign(list_id="abc123", subject_line="Spring Sale", preview_text="20% off everything") -> {"id": "def456", "status": "save", "title": "Spring Sale", ...}
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

    Use to modify subject line, sender, or segment targeting before sending. Only works on
    campaigns in 'save' (draft) status; returns error for sent/scheduled campaigns. Only provided
    fields are updated; omitted fields remain unchanged. Use set_campaign_content to change the
    HTML body instead.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Respects read-only and dry-run modes.

    Args:
        campaign_id: The campaign ID to update (e.g. 'abc123def4'). Obtain from list_campaigns
            or create_campaign.
        subject_line: New subject line for the email.
        title: New internal title for organizing in Mailchimp.
        preview_text: New preview/preheader text.
        from_name: New sender name.
        reply_to: New reply-to email address. Must be a verified domain.
        list_id: Audience/list ID. Required when changing segment_id. Obtain from list_audiences.
        segment_id: Saved segment ID to target. Requires list_id to also be set. Obtain from
            list_segments.

    Returns:
        JSON with fields: id, status, settings (full settings object), recipients (list_id,
        segment_opts).

    Example:
        update_campaign(campaign_id="abc123", subject_line="Updated Subject") -> {"id": "abc123", "status": "save", "settings": {"subject_line": "Updated Subject", ...}}
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
    """Set the full HTML body of a campaign draft, replacing any existing content entirely.

    Use after create_campaign to add the email body before sending. The campaign must be in 'save'
    (draft) status. Overwrites all previous content. Typical workflow: create_campaign ->
    set_campaign_content -> send_test_email -> send_campaign. Use update_campaign to change
    settings (subject, sender) instead of content.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Respects read-only and dry-run modes.

    Args:
        campaign_id: The campaign ID (e.g. 'abc123def4'). Obtain from create_campaign or
            list_campaigns(status='save').
        html: Complete HTML content for the email body. Must be valid HTML. Use inline CSS for
            email client compatibility. Mailchimp merge tags (e.g. *|FNAME|*, *|UNSUB|*) are
            supported. Large HTML payloads may time out; keep under 200KB.

    Returns:
        JSON with fields: status ("content_set"), campaign_id. Returns error if campaign is
        not in draft status.

    Example:
        set_campaign_content(campaign_id="abc123", html="<html><body><h1>Hello *|FNAME|*!</h1></body></html>") -> {"status": "content_set", "campaign_id": "abc123"}
    """
    if (guard := _guard_write(action="set campaign content", campaign_id=campaign_id)):
        return guard
    data = mc_request(f"/campaigns/{campaign_id}/content", body={"html": html}, method="PUT")
    return json.dumps({"status": "content_set", "campaign_id": campaign_id}, indent=2)


@mcp.tool()
def schedule_campaign(campaign_id: str, schedule_time: str) -> str:
    """Schedule a campaign draft for sending at a specific future time.

    Use to schedule delivery of a draft campaign. The campaign must have content set via
    set_campaign_content and be in 'save' status. Use unschedule_campaign to cancel a scheduled
    send. Use send_campaign instead for immediate delivery. Use send_test_email first to preview.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Respects read-only and dry-run modes.

    Args:
        campaign_id: The campaign ID (e.g. 'abc123def4'). Must be in 'save' status with content set.
        schedule_time: When to send. ISO 8601 datetime in UTC (e.g. '2025-06-15T14:00:00Z').
            Must be at least 15 minutes in the future. Mailchimp rounds to the nearest quarter hour.

    Returns:
        JSON with fields: status ("scheduled"), campaign_id, schedule_time. Returns error if
        campaign has no content or is not in draft status.

    Example:
        schedule_campaign(campaign_id="abc123", schedule_time="2025-06-15T14:00:00Z") -> {"status": "scheduled", "campaign_id": "abc123", "schedule_time": "2025-06-15T14:00:00Z"}
    """
    if (guard := _guard_write(action="schedule campaign", campaign_id=campaign_id, schedule_time=schedule_time)):
        return guard
    mc_request(f"/campaigns/{campaign_id}/actions/schedule", body={"schedule_time": schedule_time}, method="POST")
    return json.dumps({"status": "scheduled", "campaign_id": campaign_id, "schedule_time": schedule_time}, indent=2)


@mcp.tool()
def unschedule_campaign(campaign_id: str) -> str:
    """Cancel a scheduled campaign send, returning it to draft ('save') status for editing.

    Use to cancel a scheduled send before it goes out. Only works on campaigns in 'schedule'
    status; returns error for drafts or sent campaigns. After unscheduling, the campaign can be
    edited via update_campaign/set_campaign_content and rescheduled.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Respects read-only and dry-run modes.

    Args:
        campaign_id: The campaign ID to unschedule (e.g. 'abc123def4'). Must be in 'schedule'
            status. Obtain from list_campaigns(status='schedule').

    Returns:
        JSON with fields: status ("unscheduled"), campaign_id. Returns error if the campaign
        is not currently scheduled.

    Example:
        unschedule_campaign(campaign_id="abc123") -> {"status": "unscheduled", "campaign_id": "abc123"}
    """
    if (guard := _guard_write(action="unschedule campaign", campaign_id=campaign_id)):
        return guard
    mc_request(f"/campaigns/{campaign_id}/actions/unschedule", method="POST")
    return json.dumps({"status": "unscheduled", "campaign_id": campaign_id}, indent=2)


@mcp.tool()
def replicate_campaign(campaign_id: str) -> str:
    """Clone an existing campaign into a new draft with identical settings, recipients, and content.

    Use to reuse a successful campaign as a starting point. Works on campaigns of any status
    (draft, scheduled, sent). The new campaign is created in 'save' (draft) status. Use
    update_campaign and set_campaign_content to modify the copy before sending. Use
    create_campaign instead to build from scratch.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Respects read-only and dry-run modes.

    Args:
        campaign_id: The campaign ID to replicate (e.g. 'abc123def4'). Obtain from list_campaigns.

    Returns:
        JSON with fields: id (string, the NEW campaign's ID, different from original), status
        ('save'), title (original title with " (copy)" appended), web_id (int, for Mailchimp
        web UI).

    Example:
        replicate_campaign(campaign_id="abc123") -> {"id": "def456", "status": "save", "title": "Spring Sale (copy)", "web_id": 789012}
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
    """Permanently delete a campaign from the account.

    Use to remove unwanted draft or scheduled campaigns. Only works on campaigns that have not
    been sent (status 'save' or 'schedule'). Sent campaigns cannot be deleted and will return
    an error. Use replicate_campaign to clone before deleting if you want to preserve settings.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). This operation is irreversible. Respects read-only and dry-run modes.

    Args:
        campaign_id: The campaign ID to delete (e.g. 'abc123def4'). Must not be a sent campaign.

    Returns:
        JSON with fields: status ("deleted"), campaign_id. Returns error if the campaign has
        already been sent.

    Example:
        delete_campaign(campaign_id="abc123") -> {"status": "deleted", "campaign_id": "abc123"}
    """
    if (guard := _guard_write(action="delete campaign", campaign_id=campaign_id)):
        return guard
    mc_request(f"/campaigns/{campaign_id}", method="DELETE")
    return json.dumps({"status": "deleted", "campaign_id": campaign_id}, indent=2)


@mcp.tool()
def send_campaign(campaign_id: str) -> str:
    """Send a campaign immediately to all targeted recipients. Emails begin delivering within minutes.

    Use for immediate delivery. The campaign must have content set via set_campaign_content and be
    in 'save' (draft) status. Use schedule_campaign instead to send at a future time. Use
    send_test_email first to preview the email before sending to real recipients. Once sent,
    emails cannot be recalled.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). This operation is irreversible. Respects read-only and dry-run modes.

    Args:
        campaign_id: The campaign ID to send (e.g. 'abc123def4'). Must be in 'save' status
            with content set. Obtain from create_campaign or list_campaigns(status='save').

    Returns:
        JSON with fields: status ("sent"), campaign_id. Returns error if the campaign has no
        content, is already sent, or is in schedule status (use unschedule_campaign first).

    Example:
        send_campaign(campaign_id="abc123") -> {"status": "sent", "campaign_id": "abc123"}
    """
    if (guard := _guard_write(action="send campaign", campaign_id=campaign_id)):
        return guard
    mc_request(f"/campaigns/{campaign_id}/actions/send", method="POST")
    return json.dumps({"status": "sent", "campaign_id": campaign_id}, indent=2)


@mcp.tool()
def send_test_email(campaign_id: str, test_emails: str, send_type: str = "html") -> str:
    """Send a test/preview email to specific addresses without affecting the real audience.

    Side effect: sends a real email. Tests do not count against send limits and are not tracked
    in reports. Campaign must have content set via set_campaign_content. Recommended before
    send_campaign or schedule_campaign.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.

    Args:
        campaign_id: Campaign ID (e.g. 'abc123def4'). Must have content set.
        test_emails: Comma-separated emails (e.g. 'me@co.com,team@co.com'). Max 10 per request.
        send_type: Format: 'html' (default) or 'plaintext'.

    Returns:
        JSON with status ("test_sent"), campaign_id, test_emails array. Error if no content set.
    """
    if (guard := _guard_write(action="send test email", campaign_id=campaign_id)):
        return guard
    email_list = [e.strip() for e in test_emails.split(",")]
    body = {"test_emails": email_list, "send_type": send_type}
    mc_request(f"/campaigns/{campaign_id}/actions/test", body=body, method="POST")
    return json.dumps({"status": "test_sent", "campaign_id": campaign_id, "test_emails": email_list}, indent=2)


@mcp.tool()
def cancel_send(campaign_id: str) -> str:
    """Cancel a campaign mid-send, stopping delivery to remaining recipients.

    Only works on campaigns with status 'sending'. Already-delivered emails cannot be recalled.
    Irreversible. Use unschedule_campaign for scheduled (not yet sending) campaigns instead.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.

    Args:
        campaign_id: Campaign ID (e.g. 'abc123def4'). Must be in 'sending' status.

    Returns:
        JSON with status ("cancelled"), campaign_id. Error if not currently sending.
    """
    if (guard := _guard_write(action="cancel campaign send", campaign_id=campaign_id)):
        return guard
    mc_request(f"/campaigns/{campaign_id}/actions/cancel-send", method="POST")
    return json.dumps({"status": "cancelled", "campaign_id": campaign_id}, indent=2)


# --- Write Tools: Tags & Segments ---

@mcp.tool()
def create_segment(list_id: str, name: str, static: bool = True, match: Optional[str] = None, conditions_json: Optional[str] = None) -> str:
    """Create a new segment or tag in an audience for grouping members.

    Static segments (default) have manual membership via add_members_to_segment. Dynamic segments
    auto-update based on filter conditions. No destructive side effects. Use tag_member to apply
    tags to individual members instead.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.

    Args:
        list_id: Audience/list ID (10-char alphanumeric, e.g. 'abc123def4'). Obtain from list_audiences.
        name: Display name for the segment or tag.
        static: True (default) for manual membership; false for dynamic (requires match + conditions_json).
        match: Condition logic for dynamic segments: 'all' (AND) or 'any' (OR). Required when static=false.
        conditions_json: JSON conditions array for dynamic segments. Required when static=false.

    Returns:
        JSON with id (new segment ID), name, member_count, type ('static'/'saved'), options.
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
    """Delete a segment or tag from an audience. Members remain in the audience.

    Irreversible. Use update_segment to rename or modify conditions instead of deleting. Use
    list_segments to find segment IDs.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.
    Returns 404 error if segment does not exist.

    Args:
        list_id: Audience/list ID (10-char alphanumeric, e.g. 'abc123def4'). Obtain from list_audiences.
        segment_id: Segment/tag ID to delete (numeric string, e.g. '12345'). Obtain from list_segments.

    Returns:
        JSON with status ("deleted"), segment_id.
    """
    if (guard := _guard_write(action="delete segment", list_id=list_id, segment_id=segment_id)):
        return guard
    mc_request(f"/lists/{list_id}/segments/{segment_id}", method="DELETE")
    return json.dumps({"status": "deleted", "segment_id": segment_id}, indent=2)


@mcp.tool()
def add_members_to_segment(list_id: str, segment_id: str, emails: str) -> str:
    """Add members to a static segment or tag by email address.

    Only works on static segments (tags), not dynamic segments. Members must already exist in
    the audience. Use tag_member for single-member tag management instead.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.

    Args:
        list_id: Audience/list ID (10-char alphanumeric, e.g. 'abc123def4'). Obtain from list_audiences.
        segment_id: Static segment/tag ID (numeric string, e.g. '12345'). Obtain from list_segments.
        emails: Comma-separated emails to add (e.g. 'a@co.com,b@co.com'). Must exist in audience.

    Returns:
        JSON with total_added, total_removed (always 0), errors array.
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
    """Remove members from a static segment or tag. Members remain in the audience.

    Only works on static segments (tags), not dynamic segments. Non-existent members in the
    email list are silently skipped. Use tag_member with tags_to_remove for single-member removal.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.
    Returns 404 error if segment_id or list_id is invalid.

    Args:
        list_id: Audience/list ID (10-char alphanumeric, e.g. 'abc123def4'). Obtain from list_audiences.
        segment_id: Static segment/tag ID (numeric string, e.g. '12345'). Obtain from list_segments.
        emails: Comma-separated email addresses to remove (e.g. 'a@co.com,b@co.com').

    Returns:
        JSON with total_added (always 0), total_removed, errors array.
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
    """Update a segment's name or dynamic filter conditions.

    Only provided fields are updated. Idempotent: re-applying the same name is safe. Cannot
    change a segment from static to dynamic or vice versa. Use add_members_to_segment or
    remove_members_from_segment to manage static segment membership instead.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.
    Returns 404 error if segment_id is invalid. Providing match without conditions_json is ignored.

    Args:
        list_id: Audience/list ID (10-char alphanumeric, e.g. 'abc123def4'). Obtain from list_audiences.
        segment_id: Segment ID to update (numeric string, e.g. '12345'). Obtain from list_segments.
        name: New display name for the segment.
        match: Condition match type for dynamic segments: 'all' (AND) or 'any' (OR).
            Must be provided together with conditions_json.
        conditions_json: JSON string of conditions array. Must be provided with match.

    Returns:
        JSON with id, name, member_count, type ('static'/'saved'), options.
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
    """Retrieve full details of a specific segment including member count and filter conditions.

    Use to inspect a segment's conditions or verify its type and member count. Use list_segments
    to browse all segments. Use list_segment_members to see individual members in the segment.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        segment_id: The segment ID (numeric string, e.g. '12345'). Obtain from list_segments.

    Returns:
        JSON with fields: id, name, member_count (int), type ('static' for tags, 'saved' for
        dynamic segments), created_at (ISO 8601), updated_at (ISO 8601), options (object with
        match and conditions for dynamic segments, null for static segments).

    Example:
        get_segment(list_id="abc123", segment_id="12345") -> {"id": 12345, "name": "VIP", "member_count": 150, "type": "static", ...}
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

    Use to see who is in a segment. Use list_audience_members to browse all members of the full
    audience instead. Use get_segment to check segment metadata and member count first.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        segment_id: The segment ID (numeric string, e.g. '12345'). Obtain from list_segments.
        count: Number of members to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and members array. Each member: id, email_address, status,
        full_name, merge_fields (object with FNAME, LNAME, etc.).

    Example:
        list_segment_members(list_id="abc123", segment_id="12345", count=50) -> {"total_items": 150, "members": [{"email_address": "jane@co.com", ...}]}
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
    """List merge fields (custom data fields) defined for an audience, including tags, types, and defaults.

    Use to discover available merge fields and their tag names before adding or updating members.
    Default fields (FNAME, LNAME, ADDRESS, PHONE) are always present. Use create_merge_field to
    add custom fields. Merge field tags are used in add_member/update_member merge_fields objects
    and in email content as *|TAG|* merge tags.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        count: Number of merge fields to return (1-1000, default 50).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and merge_fields array. Each field: merge_id (int, use with
        update_merge_field/delete_merge_field), tag (string, e.g. 'FNAME'), name (display name),
        type ('text', 'number', 'date', etc.), required (boolean), default_value, options
        (choices for dropdown/radio types).

    Example:
        list_merge_fields(list_id="abc123") -> {"total_items": 6, "merge_fields": [{"merge_id": 1, "tag": "FNAME", "name": "First Name", "type": "text", ...}]}
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

    Use to add custom data fields beyond the defaults (FNAME, LNAME, ADDRESS, PHONE). Once
    created, populate per-member via add_member/update_member using the tag name. The type
    cannot be changed after creation. Use list_merge_fields to check existing fields first.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        name: Display name for the field (e.g. 'Company Name').
        type: Field data type. Valid values: 'text', 'number', 'address', 'date', 'birthday',
            'phone', 'url', 'imageurl', 'zip', 'dropdown', 'radio'. Cannot be changed after creation.
        tag: Short uppercase tag name (e.g. 'COMPANY'). Max 10 characters, letters and numbers
            only. Auto-generated from name if omitted. Used as *|TAG|* in email content.
        required: Whether the field is required when subscribing (default false).
        default_value: Default value for new subscribers.
        choices: Comma-separated choices for 'dropdown' or 'radio' types (e.g. 'Small,Medium,Large').
            Required when type is 'dropdown' or 'radio'. Ignored for other types.

    Returns:
        JSON with fields: merge_id (int, for update/delete), tag (string), name, type, required.

    Example:
        create_merge_field(list_id="abc123", name="Company", type="text", tag="COMPANY") -> {"merge_id": 5, "tag": "COMPANY", "name": "Company", "type": "text", ...}
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
    """Update a merge field's name, default value, required flag, or dropdown/radio choices.

    Only provided fields are updated; omitted fields remain unchanged. Choices are replaced
    entirely (old choices are lost). Do not use to change field type or tag (immutable after
    creation); use delete_merge_field then create_merge_field instead.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.
    Returns 404 error if merge_id is invalid or does not exist.

    Args:
        list_id: Audience/list ID (10-char alphanumeric, e.g. 'abc123def4'). Obtain from list_audiences.
        merge_id: Merge field ID (numeric string, e.g. '5'). Obtain from list_merge_fields.
        name: New display name for the field.
        required: Whether the field is required when subscribing.
        default_value: New default value for new subscribers.
        choices: Comma-separated choices for dropdown/radio types (e.g. 'Small,Medium,Large').
            Replaces all existing choices. Ignored for other field types.

    Returns:
        JSON with merge_id, tag, name, type, required.
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
    """Delete a custom merge field and all its stored data from an audience.

    Use only when you no longer need the field. All data stored in this field for every member
    is permanently lost. Default fields (FNAME, LNAME, ADDRESS, PHONE) cannot be deleted and
    will return an error. Use list_merge_fields to find merge_id values.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). This operation is irreversible. Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        merge_id: The merge field ID to delete (numeric string). Obtain from list_merge_fields.
            Cannot be a default field.

    Returns:
        JSON with fields: status ("deleted"), merge_id. Returns error if the field is a default
        field or does not exist.

    Example:
        delete_merge_field(list_id="abc123", merge_id="5") -> {"status": "deleted", "merge_id": "5"}
    """
    if (guard := _guard_write(action="delete merge field", list_id=list_id, merge_id=merge_id)):
        return guard
    mc_request(f"/lists/{list_id}/merge-fields/{merge_id}", method="DELETE")
    return json.dumps({"status": "deleted", "merge_id": merge_id}, indent=2)


# --- Read/Write Tools: Interest Categories & Groups ---

@mcp.tool()
def list_interest_categories(list_id: str, count: int = 50, offset: int = 0) -> str:
    """List interest categories (group containers) for an audience, showing titles and form types.

    Use to discover category IDs, then list_interests for options within each. Use
    create_interest_category to add new categories.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.

    Args:
        list_id: Audience/list ID (10-char alphanumeric, e.g. 'abc123def4'). Obtain from list_audiences.
        count: Categories to return (1-1000, default 50).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and categories array. Each: id, title, type ('checkboxes'/'dropdown'/
        'radio'/'hidden'), list_id.
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
    """Create a new interest category (group container) in an audience for organizing subscriber preferences.

    Use to create a container for interest options. Typical workflow: create_interest_category ->
    create_interest (add options within the category). The type controls how subscribers interact
    with it on signup forms. Use list_interest_categories to check existing categories first.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        title: Display title for the category (e.g. 'Preferred Topics'). Must be unique within
            the audience.
        type: How the category appears on signup forms. Valid values: 'checkboxes' (subscribers
            can select multiple), 'dropdown' (single select), 'radio' (single select), 'hidden'
            (not shown on forms, managed via API only).

    Returns:
        JSON with fields: id (string, use with create_interest, list_interests,
        delete_interest_category), title, type, list_id.

    Example:
        create_interest_category(list_id="abc123", title="Newsletter Preferences", type="checkboxes") -> {"id": "cat456", "title": "Newsletter Preferences", "type": "checkboxes", ...}
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
    """List interest options within a category, with subscriber counts per option.

    Use after list_interest_categories to see individual options (e.g. "Tech", "Sports").
    Interest IDs are needed when setting member preferences via add_member/update_member. Do not
    use to manage member preferences directly; set interests per-member via the API instead.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.
    Returns 404 error if category_id is invalid.

    Args:
        list_id: Audience/list ID (10-char alphanumeric, e.g. 'abc123def4'). Obtain from list_audiences.
        category_id: Interest category ID. Obtain from list_interest_categories.
        count: Number of interests to return (1-1000, default 50).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and interests array. Each interest: id, name, subscriber_count, display_order.
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
    """Create a new interest option within an interest category (e.g. add "Tech" to a "Topics" category).

    Use after create_interest_category to add selectable options. Each option becomes available
    on signup forms (unless category type is 'hidden'). Use list_interests to check existing
    options. Use delete_interest to remove an option.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        category_id: The interest category ID. Obtain from list_interest_categories or
            create_interest_category.
        name: Display name for the interest option (e.g. 'Tech', 'Sports'). Must be unique
            within the category.

    Returns:
        JSON with fields: id (string, use with delete_interest), name, subscriber_count (int,
        starts at 0).

    Example:
        create_interest(list_id="abc123", category_id="cat456", name="Technology") -> {"id": "int789", "name": "Technology", "subscriber_count": 0}
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
    """Delete an interest category and all its interest options at once.

    Removes the entire category with all its options. All subscriber associations with interests
    in this category are removed. Subscribers themselves are not affected. Use delete_interest
    instead to remove a single option while keeping the category. Use list_interest_categories
    to find category IDs.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). This operation is irreversible. Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        category_id: The interest category ID to delete. Obtain from list_interest_categories.

    Returns:
        JSON with fields: status ("deleted"), category_id. Returns error if category does
        not exist.

    Example:
        delete_interest_category(list_id="abc123", category_id="cat456") -> {"status": "deleted", "category_id": "cat456"}
    """
    if (guard := _guard_write(action="delete interest category", list_id=list_id, category_id=category_id)):
        return guard
    mc_request(f"/lists/{list_id}/interest-categories/{category_id}", method="DELETE")
    return json.dumps({"status": "deleted", "category_id": category_id}, indent=2)


@mcp.tool()
def delete_interest(list_id: str, category_id: str, interest_id: str) -> str:
    """Delete a single interest option from a category, keeping the category and other options intact.

    Use to remove one specific option. The interest and its subscriber associations are removed.
    Use delete_interest_category instead to remove the entire category with all options at once.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). This operation is irreversible. Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        category_id: The interest category ID. Obtain from list_interest_categories.
        interest_id: The interest option ID to delete. Obtain from list_interests.

    Returns:
        JSON with fields: status ("deleted"), interest_id. Returns error if interest does
        not exist.

    Example:
        delete_interest(list_id="abc123", category_id="cat456", interest_id="int789") -> {"status": "deleted", "interest_id": "int789"}
    """
    if (guard := _guard_write(action="delete interest", list_id=list_id, category_id=category_id, interest_id=interest_id)):
        return guard
    mc_request(f"/lists/{list_id}/interest-categories/{category_id}/interests/{interest_id}", method="DELETE")
    return json.dumps({"status": "deleted", "interest_id": interest_id}, indent=2)


# --- Read/Write Tools: Webhooks ---

@mcp.tool()
def list_webhooks(list_id: str) -> str:
    """List webhooks configured for an audience, showing callback URLs, events, and source filters.

    Use to audit integrations or find webhook IDs before deleting via delete_webhook. Do not use
    to check webhook delivery history; Mailchimp does not expose delivery logs via the API.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.

    Args:
        list_id: Audience/list ID (10-char alphanumeric, e.g. 'abc123def4'). Obtain from list_audiences.

    Returns:
        JSON with total_items and webhooks array. Each webhook: id, url, events (boolean flags:
        subscribe, unsubscribe, profile, cleaned, upemail, campaign), sources (boolean flags:
        user, admin, api), list_id.
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
    """Create a webhook that sends HTTP POST notifications to an external URL on audience events.

    Side effect: Mailchimp sends a validation GET request during creation; the URL must be
    publicly accessible and return HTTP 200. All events and sources enabled by default if
    omitted. Do not use for polling or batch data retrieval; use list_audience_members or
    campaign reports instead.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.

    Args:
        list_id: Audience/list ID (10-char alphanumeric, e.g. 'abc123def4'). Obtain from list_audiences.
        url: Public HTTPS URL to receive POST requests. Must return HTTP 200 on GET validation.
        events: Comma-separated events: 'subscribe', 'unsubscribe', 'profile', 'cleaned',
            'upemail', 'campaign'. All enabled if omitted.
        sources: Comma-separated sources: 'user', 'admin', 'api'. All enabled if omitted.

    Returns:
        JSON with id, url, events (boolean flags), sources (boolean flags). Error if URL validation fails.
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
    """Delete a webhook, immediately stopping event notifications to its URL.

    Irreversible. Do not use when you want to temporarily pause notifications; webhooks have
    no pause mechanism. Use create_webhook to set up a replacement afterward.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.
    Returns 404 error if webhook_id or list_id is invalid.

    Args:
        list_id: Audience/list ID (10-char alphanumeric, e.g. 'abc123def4'). Obtain from list_audiences.
        webhook_id: The webhook ID to delete. Obtain from list_webhooks.

    Returns:
        JSON with status ("deleted"), webhook_id.
    """
    if (guard := _guard_write(action="delete webhook", list_id=list_id, webhook_id=webhook_id)):
        return guard
    mc_request(f"/lists/{list_id}/webhooks/{webhook_id}", method="DELETE")
    return json.dumps({"status": "deleted", "webhook_id": webhook_id}, indent=2)


# --- Read Tools: Detailed Reports ---

@mcp.tool()
def get_email_activity(campaign_id: str, count: int = 20, offset: int = 0) -> str:
    """Retrieve per-recipient activity timeline for a sent campaign (opens, clicks, bounces).

    Use get_open_details for open data only. Use get_campaign_report for aggregate totals. Use
    get_campaign_recipients for delivery status only.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.

    Args:
        campaign_id: Campaign ID (e.g. 'abc123def4'). Must be a sent campaign.
        count: Recipient records to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and emails array. Each: email_address, activity array with action
        ('open'/'click'/'bounce'), timestamp, url (clicks only).
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
    """Retrieve per-recipient open data for a sent campaign (who opened, when, how many times).

    Use get_campaign_report for aggregate open rates. Use get_email_activity for all activity
    types combined.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.

    Args:
        campaign_id: Campaign ID (e.g. 'abc123def4'). Must be a sent campaign.
        count: Records to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and members array. Each: email_address, opens_count, opens array
        with timestamps.
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
    """Retrieve the delivery roster for a sent campaign showing each recipient's delivery status and open count.

    Use to verify who received a campaign and whether they opened it. Use get_email_activity for
    detailed per-recipient timelines (clicks, bounces with timestamps). Use get_campaign_report
    for aggregate metrics. Only works for sent campaigns; returns error for drafts or scheduled.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        campaign_id: The Mailchimp campaign ID (e.g. 'abc123def4'). Must be a sent campaign.
        count: Number of recipients to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items (int) and recipients array. Each recipient: email_address,
        status ('sent', 'hard', 'soft'), open_count (int), last_open (ISO 8601 or null).

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
    """Retrieve members who unsubscribed from a specific sent campaign, with reasons.

    Use get_campaign_report for aggregate unsubscribe count instead.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.
    Returns 404 error if campaign_id is invalid. Returns empty array for unsent campaigns.

    Args:
        campaign_id: Campaign ID (e.g. 'abc123def4'). Must be a sent campaign.
        count: Records to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and unsubscribes array. Each: email_address, reason (string or null),
        timestamp.
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
    """Retrieve campaign performance broken down by recipient email domain (gmail.com, outlook.com, etc.).

    Use to identify deliverability issues with specific providers or compare engagement across
    domains. Use get_campaign_report for overall aggregate metrics. Only works for sent campaigns.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        campaign_id: The Mailchimp campaign ID (e.g. 'abc123def4'). Must be a sent campaign.

    Returns:
        JSON with total_items and domains array. Each domain: domain (string, e.g. 'gmail.com'),
        emails_sent (int), bounces (int), opens (int), clicks (int), unsubs (int).

    Example:
        get_domain_performance(campaign_id="abc123") -> {"total_items": 15, "domains": [{"domain": "gmail.com", "emails_sent": 2000, "opens": 500, "clicks": 80, ...}]}
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
    """Retrieve e-commerce product activity for a campaign showing revenue per product.

    Requires an active e-commerce integration; returns total_items: 0 if none is connected.
    Use list_ecommerce_stores to verify status. Only works for sent campaigns.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.
    Returns 404 error if campaign_id is invalid.

    Args:
        campaign_id: Campaign ID (e.g. 'abc123def4'). Must be a sent campaign.
        count: Products to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and products array. Each: title, sku, image_url, total_revenue
        (float, store currency), total_purchased.
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
    """Retrieve child report data for A/B test, variate, or RSS campaign sub-items.

    Read-only, no side effects. Returns empty data for regular campaigns; use get_campaign_report
    instead. Check campaign type with get_campaign_details first ('absplit', 'variate', 'rss').

    Authenticated via API key. Max 10 concurrent requests. Safe to retry.

    Args:
        campaign_id: Campaign ID (e.g. 'abc123def4'). Should be type 'absplit', 'variate', or
            'rss'. Obtain from list_campaigns.

    Returns:
        JSON with sub-reports. Format varies: A/B tests include per-variant opens, clicks, winner;
        RSS includes per-item send stats with dates.
    """
    data = mc_request(f"/reports/{campaign_id}/sub-reports")
    return json.dumps(data, indent=2)


# --- Read Tools: Member Activity ---

@mcp.tool()
def get_member_activity(list_id: str, email_address: str, count: int = 20) -> str:
    """Retrieve a member's email interaction history (opens, clicks, bounces across all campaigns).

    Shows email actions only. Use get_member_events for custom API-triggered events. Use
    get_member_tags for tag data. Use search_members first to find which audience a member belongs to.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.
    Returns 404 error if the member does not exist in the audience.

    Args:
        list_id: Audience/list ID (10-char alphanumeric, e.g. 'abc123def4'). Obtain from list_audiences.
        email_address: Email of the member. Must exist in the audience.
        count: Number of activity records to return (1-1000, default 20).

    Returns:
        JSON with email_address and activity array. Each: action ('open'/'click'/'bounce'),
        timestamp, campaign_id, title.
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
    """Retrieve all tags currently assigned to a specific member.

    Use to see which tags a member has before modifying them. Use tag_member to add or remove tags.
    Use list_segments to see all available tags/segments in the audience.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        email_address: Email address of the member. Must exist in the audience.
        count: Number of tags to return (1-1000, default 50).

    Returns:
        JSON with email_address, total_items (int), and tags array. Each tag: id (int),
        name (string), date_added (ISO 8601).

    Example:
        get_member_tags(list_id="abc123", email_address="jane@co.com") -> {"email_address": "jane@co.com", "total_items": 3, "tags": [{"name": "VIP", "date_added": "2025-01-15T10:00:00Z", ...}]}
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
    """Retrieve custom API-triggered events for a specific member (e.g. "purchased", "signed_up").

    Use to view events sent to Mailchimp via the Events API. These are custom application events,
    not email interactions (opens, clicks); use get_member_activity for email engagement data.
    Returns empty if no custom events have been recorded for the member.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        email_address: Email address of the member. Must exist in the audience.
        count: Number of events to return (1-1000, default 20).

    Returns:
        JSON with email_address, total_items (int), and events array. Each event: name (string,
        event name), occurred_at (ISO 8601), properties (object, custom key-value data or null).

    Example:
        get_member_events(list_id="abc123", email_address="jane@co.com") -> {"email_address": "jane@co.com", "total_items": 5, "events": [{"name": "purchased", "occurred_at": "2025-06-01T10:00:00Z", "properties": {"product": "T-Shirt"}}]}
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
    """List individual emails within an automation workflow with sequence, delays, and send counts.

    Returns all emails regardless of status. Do not confuse with get_email_activity (campaign
    engagement). Use get_automation_email_queue to see queued subscribers for a specific email.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.

    Args:
        automation_id: Automation workflow ID (e.g. 'auto123'). Obtain from list_automations.

    Returns:
        JSON with total_items and emails array. Each email: id, position (sequence starting at 1),
        status ('sending'/'paused'/'draft'), subject_line, title, emails_sent, send_time, delay.
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
    """Retrieve the queue of subscribers about to receive a specific automation email, with scheduled send times.

    Use to see who is waiting to receive a particular email in a workflow. Use
    get_automation_emails first to find email_id values within the workflow.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        automation_id: The automation workflow ID (e.g. 'auto123'). Obtain from list_automations.
        email_id: The specific email ID within the automation. Obtain from get_automation_emails.

    Returns:
        JSON with total_items (int) and queue array. Each entry: email_address (string),
        next_send (ISO 8601 timestamp of scheduled send).

    Example:
        get_automation_email_queue(automation_id="auto123", email_id="email456") -> {"total_items": 12, "queue": [{"email_address": "jane@co.com", "next_send": "2025-06-02T10:00:00Z"}]}
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
    """Pause an automation workflow, stopping delivery while preserving the queue.

    Queued subscribers resume when restarted via start_automation. New subscribers still enter
    the queue but do not receive emails while paused. Reversible.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.

    Args:
        automation_id: Automation workflow ID (e.g. 'auto123'). Obtain from list_automations.

    Returns:
        JSON with status ("paused"), automation_id. Error if already paused or in draft status.
    """
    if (guard := _guard_write(action="pause automation", automation_id=automation_id)):
        return guard
    mc_request(f"/automations/{automation_id}/actions/pause-all-emails", method="POST")
    return json.dumps({"status": "paused", "automation_id": automation_id}, indent=2)


@mcp.tool()
def start_automation(automation_id: str) -> str:
    """Start or resume all emails in an automation workflow, activating delivery to queued subscribers.

    Use to activate a new automation or resume a paused one. Queued subscribers begin receiving
    emails. Use pause_automation to temporarily stop. Use list_automations to check current status.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Respects read-only and dry-run modes.

    Args:
        automation_id: The automation workflow ID (e.g. 'auto123'). Obtain from list_automations.

    Returns:
        JSON with fields: status ("started"), automation_id. Returns error if automation is
        already sending or is in draft status.

    Example:
        start_automation(automation_id="auto123") -> {"status": "started", "automation_id": "auto123"}
    """
    if (guard := _guard_write(action="start automation", automation_id=automation_id)):
        return guard
    mc_request(f"/automations/{automation_id}/actions/start-all-emails", method="POST")
    return json.dumps({"status": "started", "automation_id": automation_id}, indent=2)


# --- Read Tools: Landing Pages ---

@mcp.tool()
def list_landing_pages(count: int = 20, offset: int = 0) -> str:
    """List landing pages with publication status, URLs, and associated audiences.

    Landing pages are standalone web pages, not emails. Use get_landing_page for full details.
    Do not use to find email campaigns; use list_campaigns instead.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.

    Args:
        count: Landing pages to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and landing_pages array. Each: id, name, title, status
        ('published'/'unpublished'/'draft'), url (null if not published), published_at, created_at, list_id.
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
    """Retrieve full details of a landing page including description and tracking settings.

    Use list_landing_pages to browse all pages and discover page IDs.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.
    Returns 404 error if page_id is invalid.

    Args:
        page_id: Landing page ID (alphanumeric string). Obtain from list_landing_pages.

    Returns:
        JSON with id, name, title, description, status ('published'/'unpublished'/'draft'), url,
        published_at, created_at, updated_at, list_id, tracking.
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
    """List connected e-commerce stores (Shopify, WooCommerce, etc.) with platform and currency info.

    Use to discover store IDs for list_store_orders, list_store_products, list_store_customers.
    Also verifies integration status before get_ecommerce_product_activity. Returns total_items: 0
    if no integration is configured.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.

    Returns:
        JSON with total_items and stores array. Each: id (use as store_id), list_id, name,
        platform, domain, currency_code (ISO 4217), money_format, created_at.
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
    """List orders from a connected e-commerce store with totals and fulfillment status.

    Requires an active integration. Use list_store_customers for customer-level aggregates instead.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.

    Args:
        store_id: E-commerce store ID (alphanumeric string). Obtain from list_ecommerce_stores.
        count: Orders to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and orders array. Each: id, customer (email), order_total (float),
        currency_code (ISO 4217), financial_status, fulfillment_status, processed_at_foreign,
        lines_count.
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

    Use to browse the product catalog synced to Mailchimp. Useful for verifying sync status or
    finding product data for campaign content. Use list_ecommerce_stores to find store IDs. Use
    get_ecommerce_product_activity for campaign-level product revenue data.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        store_id: The e-commerce store ID. Obtain from list_ecommerce_stores.
        count: Number of products to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and products array. Each product: id (string), title, url (product
        page link), vendor (string), image_url (string or null), variants_count (int).
        Returns total_items: 0 if no integration is configured.

    Example:
        list_store_products(store_id="store123", count=50) -> {"total_items": 200, "products": [{"id": "prod_123", "title": "Blue T-Shirt", "variants_count": 3, ...}]}
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
    """List customers from a connected e-commerce store with order counts, total spend, and opt-in status.

    Use to analyze customer purchasing behavior or identify high-value customers. Requires an
    active e-commerce integration. Use list_ecommerce_stores to find store IDs. Use
    list_store_orders for per-order detail instead of customer-level aggregates.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        store_id: The e-commerce store ID. Obtain from list_ecommerce_stores.
        count: Number of customers to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and customers array. Each customer: id (string), email_address,
        first_name, last_name, orders_count (int), total_spent (float, in store currency),
        opt_in_status (boolean), created_at (ISO 8601).

    Example:
        list_store_customers(store_id="store123", count=50) -> {"total_items": 500, "customers": [{"email_address": "jane@co.com", "orders_count": 5, "total_spent": 299.95, ...}]}
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

    Folders are organizational containers only; they do not affect campaign delivery or behavior.
    Returns an empty array if no folders exist. Do not use to find campaigns; use list_campaigns
    or search_campaigns instead.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.

    Args:
        count: Number of folders to return (1-1000, default 50).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and folders array. Each folder: id, name, count (campaigns in folder).
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
    """Submit multiple API operations as a single asynchronous batch request.

    Use for bulk operations exceeding other tool limits (e.g. batch_subscribe max 500). Operations
    run asynchronously; poll with get_batch_status. Each operation runs independently. Can include
    destructive operations (DELETE, POST).

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.

    Args:
        operations: JSON array of operations. Each requires: method ('GET'/'POST'/'PATCH'/'PUT'/
            'DELETE'), path (API endpoint, e.g. '/lists/abc123/members'), optional body (JSON string).

    Returns:
        JSON with id (batch ID for get_batch_status), status ('pending'), total_operations, submitted_at.
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

    Use after create_batch to poll for completion. Call repeatedly until status is 'finished'.
    Do not use for non-batch operations. Use list_batches to see all recent batch operations.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        batch_id: The batch operation ID (e.g. 'batch123abc'). Obtain from create_batch.

    Returns:
        JSON with fields: id, status ('pending' = queued, 'started' = in progress,
        'finished' = complete), total_operations (int), finished_operations (int),
        errored_operations (int), submitted_at (ISO 8601), completed_at (ISO 8601 or null),
        response_body_url (string, downloadable tar.gz archive with per-operation results,
        only available when status is 'finished').

    Example:
        get_batch_status(batch_id="batch123") -> {"status": "finished", "total_operations": 100, "finished_operations": 100, "errored_operations": 2, "response_body_url": "https://...", ...}
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
    """List recent batch operations with status and progress.

    Use get_batch_status for detailed progress on a specific batch.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.

    Args:
        count: Batch operations to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and batches array. Each: id, status ('pending'/'started'/'finished'),
        total_operations, finished_operations, errored_operations, submitted_at, completed_at.
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


# --- Tools: Ping & Search ---

@mcp.tool()
def ping() -> str:
    """Check API connectivity and verify the API key is valid.

    Fastest health check available. Use get_account_info instead if you need account details.
    Returns error object if the key is invalid or missing.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.

    Returns:
        JSON with health_check ('ok' if connected), status_code (200 if healthy).
    """
    data = mc_request("/ping")
    return json.dumps({
        "health_check": data.get("health_check"),
        "status_code": 200 if "health_check" in data else data.get("status", 0),
    }, indent=2)


@mcp.tool()
def search_campaigns(query: str, count: int = 20, offset: int = 0) -> str:
    """Search campaigns by keyword across titles, subject lines, and list names.

    Use to find campaigns when you do not know the ID. Use list_campaigns to browse by status
    or date instead. Queries under 3 characters return an error.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.

    Args:
        query: Search string (minimum 3 characters). Matches against campaign titles, subject
            lines, and list names.
        count: Number of results to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and results array. Each result: campaign object with id, type,
        status, title, subject_line, send_time, emails_sent.
    """
    data = mc_request("/search-campaigns", params={"query": query, "count": count, "offset": offset})
    results = []
    for r in data.get("results", []):
        c = r.get("campaign", {})
        results.append({
            "campaign": {
                "id": c.get("id"),
                "type": c.get("type"),
                "status": c.get("status"),
                "title": c.get("settings", {}).get("title"),
                "subject_line": c.get("settings", {}).get("subject_line"),
                "send_time": c.get("send_time"),
                "emails_sent": c.get("emails_sent"),
            }
        })
    return json.dumps({"total_items": data.get("total_items"), "results": results}, indent=2)


@mcp.tool()
def resend_to_non_openers(campaign_id: str) -> str:
    """Create a new draft campaign targeting only recipients who did not open the original.

    The new campaign inherits content and settings from the original. Not idempotent: calling
    twice creates two separate drafts. Workflow: resend_to_non_openers -> update_campaign
    (change subject) -> send_campaign or schedule_campaign. Do not use for A/B test campaigns
    or campaigns sent less than 24 hours ago (open tracking may be incomplete).

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.
    Returns error if the original campaign status is not 'sent'.

    Args:
        campaign_id: ID of the original sent campaign (e.g. 'abc123def4'). Obtain from
            list_campaigns(status='sent').

    Returns:
        JSON with id (new campaign ID), status ('save'), title, web_id.
    """
    if (guard := _guard_write(action="resend to non-openers", campaign_id=campaign_id)):
        return guard
    data = mc_request(f"/campaigns/{campaign_id}/actions/create-resend", method="POST")
    return json.dumps({
        "id": data.get("id"),
        "status": data.get("status"),
        "title": data.get("settings", {}).get("title"),
        "web_id": data.get("web_id"),
    }, indent=2)


@mcp.tool()
def trigger_customer_journey(journey_id: str, step_id: str, email_address: str) -> str:
    """Trigger a contact into a specific step of a Customer Journey workflow.

    Side effect: the contact begins receiving journey emails immediately. The contact must be
    a subscribed member of the journey's audience. Use list_automations to find journey IDs.
    For Classic Automations, use start_automation instead. For one-time emails, use
    send_campaign or create_campaign instead.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.
    Returns error if contact is not subscribed or step is not a valid API-trigger entry point.

    Args:
        journey_id: Customer Journey ID. Found in the Mailchimp web UI or via list_automations.
        step_id: Step ID to trigger into. Must be an API-trigger entry point.
        email_address: Email of the contact. Must be subscribed in the journey's audience.

    Returns:
        JSON with status ('triggered'), journey_id, step_id, email_address.
    """
    if (guard := _guard_write(action="trigger customer journey", journey_id=journey_id, step_id=step_id, email_address=email_address)):
        return guard
    mc_request(
        f"/customer-journeys/journeys/{journey_id}/steps/{step_id}/actions/trigger",
        body={"email_address": email_address},
        method="POST",
    )
    return json.dumps({"status": "triggered", "journey_id": journey_id, "step_id": step_id, "email_address": email_address}, indent=2)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
