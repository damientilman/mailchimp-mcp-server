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
    """List all audiences (lists) in the account with subscriber counts and engagement rates.

    Use this as the first step in most workflows to discover audience IDs (list_id). Almost every
    other tool requires a list_id from this output. Use get_audience_details when you already have
    a list_id and need full stats. Do not use this to find a specific member; use search_members.
    Most accounts have 1-5 audiences.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        count: Number of audiences to return (1-1000, default 10). Most accounts have fewer than 10.
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and audiences array. Each audience: id (use as list_id in other
        tools), name, member_count, unsubscribe_count, open_rate (decimal 0-1), click_rate
        (decimal 0-1), date_created (ISO 8601).

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
    """Retrieve full stats, subscribe URL, and rating for a specific audience.

    Use when you already have a list_id and need detailed metrics (member counts by status,
    open/click rates, list rating 0-5) or the public subscribe URL. Use list_audiences instead
    to browse all audiences and discover list_ids.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.

    Returns:
        JSON with fields: id, name, stats (member_count, unsubscribe_count, open_rate, click_rate,
        etc.), date_created (ISO 8601), list_rating (0-5), subscribe_url_short (public signup link).
        Returns error object if list_id is invalid.

    Example:
        get_audience_details(list_id="abc123def4") -> {"id": "abc123def4", "name": "Newsletter", "stats": {"member_count": 5000, ...}, "list_rating": 4}
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
    """Retrieve aggregate performance metrics for a sent campaign: opens, clicks, bounces, and industry benchmarks.

    Use for a high-level overview of campaign results. Use get_campaign_click_details for per-link
    click data. Use get_open_details for per-recipient open data. Use get_campaign_recipients for
    delivery status per recipient. Use get_campaign_sub_reports for A/B test variant results.
    Only works for sent campaigns; returns an error for drafts or scheduled campaigns.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        campaign_id: The Mailchimp campaign ID (e.g. 'abc123def4'). Must be a sent campaign.
            Obtain from list_campaigns(status="sent").

    Returns:
        JSON with fields: campaign_title, subject_line, emails_sent (int), abuse_reports (int),
        unsubscribed (int), send_time (ISO 8601), opens (opens_total, unique_opens, open_rate as
        decimal 0-1), clicks (clicks_total, unique_clicks, click_rate), bounces (hard_bounces,
        soft_bounces), forwards (forwards_count, forwards_opens), list_stats, industry_stats
        (open_rate, click_rate, bounce_rate for comparison).

    Example:
        get_campaign_report(campaign_id="abc123") -> {"emails_sent": 5000, "opens": {"open_rate": 0.25, "unique_opens": 1250}, ...}
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
    """Retrieve monthly growth history for an audience showing subscribes, unsubscribes, and cleaned contacts over time.

    Use to analyze audience growth trends or detect unusual churn. Each record represents one
    calendar month. Data starts from the audience creation date, ordered newest first. Use
    get_audience_details for current totals instead of historical trends.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        count: Number of months to return (1-1000, default 12). Set to 24 or 36 for longer trends.

    Returns:
        JSON with list_id and history array. Each entry: month (YYYY-MM format), subscribed (int,
        cumulative total), unsubscribed (int, cumulative), reconfirm (int), cleaned (int),
        pending (int), transactional (int).

    Example:
        get_audience_growth_history(list_id="abc123def4", count=6) -> {"list_id": "abc123def4", "history": [{"month": "2025-06", "subscribed": 5200, "unsubscribed": 120, ...}]}
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
    """List automation workflows (automated email sequences) in the account with status and send counts.

    Use to discover automation IDs and check their status. Use get_automation_emails to see
    individual emails within a workflow. Use pause_automation/start_automation to control them.
    Includes both Classic Automations and Customer Journeys.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        count: Number of automations to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and automations array. Each automation: id (use with
        get_automation_emails, pause_automation, start_automation), status ('sending', 'paused',
        'draft'), title, emails_sent (int), start_time (ISO 8601 or null), create_time (ISO 8601),
        list_id (associated audience).

    Example:
        list_automations() -> {"total_items": 3, "automations": [{"id": "auto123", "status": "sending", "title": "Welcome Series", ...}]}
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
    """List email templates available in the account (both user-created and Mailchimp gallery templates).

    Use to browse templates for reference when building campaign content via set_campaign_content.
    Do not use this to find campaigns; use list_campaigns instead.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        count: Number of templates to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and templates array. Each template: id (int), name, type ('user',
        'gallery', 'base'), date_created (ISO 8601), active (boolean).

    Example:
        list_templates() -> {"total_items": 10, "templates": [{"id": 12345, "name": "Monthly Newsletter", "type": "user", ...}]}
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
    """List all segments and tags for a specific audience with member counts and types.

    Use to discover segment IDs before targeting campaigns (create_campaign with segment_id) or
    managing membership (add_members_to_segment). Returns both static segments (tags, manual) and
    dynamic (saved) segments (auto-updated by conditions). Use get_segment for full details
    including filter conditions.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        count: Number of segments to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and segments array. Each segment: id (int, use as segment_id in
        other tools), name, member_count (int), type ('static' for tags, 'saved' for dynamic
        segments), created_at (ISO 8601), updated_at (ISO 8601).

    Example:
        list_segments(list_id="abc123") -> {"total_items": 5, "segments": [{"id": 12345, "name": "VIP", "type": "static", "member_count": 150, ...}]}
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

    Use to subscribe one person. Use batch_subscribe for multiple members at once (up to 500).
    Returns an error if the email already exists; use update_member to modify existing members.
    Side effect: if status='pending', Mailchimp sends a double opt-in confirmation email to the address.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        email_address: Email address of the new member. Must not already exist in the audience.
        status: Subscription status. Valid values: 'subscribed' (default, immediate opt-in),
            'pending' (triggers double opt-in confirmation email), 'unsubscribed', 'cleaned'.
        first_name: First name, stored in the FNAME merge field.
        last_name: Last name, stored in the LNAME merge field.
        tags: Comma-separated tag names to apply (e.g. 'VIP,Newsletter'). Tags are created
            automatically if they do not exist.

    Returns:
        JSON with fields: id (MD5 hash of email), email_address, status, full_name. Returns
        error with title "Member Exists" if the email is already in the audience.

    Example:
        add_member(list_id="abc123", email_address="jane@co.com", first_name="Jane", tags="VIP") -> {"id": "abc123", "email_address": "jane@co.com", "status": "subscribed", ...}
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
    """Update an existing member's profile fields or subscription status.

    Use to change a member's name or status. Only provided fields are updated; omitted fields
    remain unchanged. Use unsubscribe_member as a shortcut for status change to unsubscribed.
    Use tag_member to manage tags. Use add_member if the member does not exist yet.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        email_address: Email address of the member to update. Must already exist in the audience.
            Use search_members to verify existence.
        status: New subscription status. Valid values: 'subscribed', 'unsubscribed', 'cleaned',
            'pending'. Changing to 'pending' triggers a re-confirmation email.
        first_name: New first name (FNAME merge field).
        last_name: New last name (LNAME merge field).

    Returns:
        JSON with fields: id, email_address, status, full_name. Returns error if the member
        does not exist in the audience.

    Example:
        update_member(list_id="abc123", email_address="jane@co.com", first_name="Janet") -> {"id": "abc123", "email_address": "jane@co.com", "status": "subscribed", "full_name": "Janet Doe"}
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
    """Unsubscribe a member from an audience, preserving their profile and history for reporting.

    Use to opt someone out while keeping their data. Reversible via update_member(status='subscribed').
    Use delete_member instead to permanently remove all data (irreversible, for GDPR). Do not use
    if the member does not exist; returns an error.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        email_address: Email address of the member to unsubscribe. Must exist in the audience.

    Returns:
        JSON with fields: email_address, status ("unsubscribed").

    Example:
        unsubscribe_member(list_id="abc123", email_address="jane@co.com") -> {"email_address": "jane@co.com", "status": "unsubscribed"}
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
    """Add or remove tags from a specific member. Tags are free-form labels for organizing contacts.

    Use to manage per-member labels. Provide at least one of tags_to_add or tags_to_remove. Tags
    are created automatically if they do not exist. Use get_member_tags to check current tags.
    Use add_members_to_segment to add multiple members to a segment at once instead.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        email_address: Email address of the member. Must exist in the audience.
        tags_to_add: Comma-separated tag names to add (e.g. 'VIP,Returning Customer'). Tags
            are created if they do not already exist.
        tags_to_remove: Comma-separated tag names to remove (e.g. 'Trial'). Silently ignored
            if the tag is not currently on the member.

    Returns:
        JSON with fields: status ("updated"), email_address, tags (array of changes with name
        and status 'active'/'inactive').

    Example:
        tag_member(list_id="abc123", email_address="jane@co.com", tags_to_add="VIP,Premium") -> {"status": "updated", "email_address": "jane@co.com", "tags": [{"name": "VIP", "status": "active"}, ...]}
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
    """Add or update up to 500 members in an audience in a single synchronous request.

    Use when adding or updating more than one member at a time. Use add_member or update_member
    for a single member. Use create_batch for imports larger than 500 members. Side effect: members
    with status='pending' will each receive a double opt-in confirmation email.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        members_json: JSON string of members array (max 500 items). Each member requires at minimum:
            email_address (string) and status ('subscribed', 'unsubscribed', 'cleaned', 'pending').
            Optional fields: merge_fields (object), tags (array of strings).
            Example: '[{"email_address":"a@b.com","status":"subscribed","merge_fields":{"FNAME":"Alice"}}]'
        update_existing: If true (default), existing members are updated with provided data.
            If false, existing members are skipped and counted as errors.

    Returns:
        JSON with fields: new_members (int), updated_members (int), errors (array with detail per
        failed email), total_created (int), total_updated (int), error_count (int).

    Example:
        batch_subscribe(list_id="abc123", members_json='[{"email_address":"a@b.com","status":"subscribed"}]') -> {"total_created": 1, "total_updated": 0, "error_count": 0, ...}
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
    """Update audience-level settings: name, default campaign sender, subject, and permission reminder.

    Use to change defaults that apply to newly created campaigns for this audience. Does not
    retroactively affect existing campaigns. Only provided fields are updated; omitted fields
    remain unchanged. Use get_audience_details to check current settings before updating.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        name: New audience display name.
        from_name: Default 'from' name for new campaigns sent to this audience.
        from_email: Default 'from' email. Must be a verified sending domain in Mailchimp.
        subject: Default email subject line for new campaigns.
        permission_reminder: Text shown to subscribers explaining why they receive emails.
            Required by CAN-SPAM.

    Returns:
        JSON with fields: id, name, permission_reminder, campaign_defaults (object with from_name,
        from_email, subject, language).

    Example:
        update_audience(list_id="abc123def4", name="VIP Newsletter") -> {"id": "abc123def4", "name": "VIP Newsletter", "campaign_defaults": {...}}
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
    """Send a test/preview email to specific addresses without sending to the full audience.

    Use to preview a campaign before sending to real recipients. The campaign must have content
    set via set_campaign_content. Test emails do not count against send limits and are not tracked
    in reports. Side effect: sends a real email to the specified addresses. Recommended step
    before send_campaign or schedule_campaign.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Respects read-only and dry-run modes.

    Args:
        campaign_id: The campaign ID (e.g. 'abc123def4'). Must have content set.
        test_emails: Comma-separated email addresses to send the test to (e.g. 'me@co.com,team@co.com').
            Maximum of 10 test addresses per request.
        send_type: Format of the test email. Valid values: 'html' (default), 'plaintext'.

    Returns:
        JSON with fields: status ("test_sent"), campaign_id, test_emails (array). Returns error
        if campaign has no content.

    Example:
        send_test_email(campaign_id="abc123", test_emails="me@company.com") -> {"status": "test_sent", "campaign_id": "abc123", "test_emails": ["me@company.com"]}
    """
    if (guard := _guard_write(action="send test email", campaign_id=campaign_id)):
        return guard
    email_list = [e.strip() for e in test_emails.split(",")]
    body = {"test_emails": email_list, "send_type": send_type}
    mc_request(f"/campaigns/{campaign_id}/actions/test", body=body, method="POST")
    return json.dumps({"status": "test_sent", "campaign_id": campaign_id, "test_emails": email_list}, indent=2)


@mcp.tool()
def cancel_send(campaign_id: str) -> str:
    """Cancel a campaign that is currently in the process of sending, stopping delivery to remaining recipients.

    Use to stop a campaign mid-send. Only works on campaigns with status 'sending'; returns error
    for drafts, scheduled, or already-sent campaigns. Recipients who already received the email
    are not affected; already-delivered emails cannot be recalled. Use unschedule_campaign instead
    to cancel a scheduled (not yet sending) campaign.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). This operation is irreversible. Respects read-only and dry-run modes.

    Args:
        campaign_id: The campaign ID to cancel (e.g. 'abc123def4'). Must be in 'sending' status.
            Obtain from list_campaigns(status='sending').

    Returns:
        JSON with fields: status ("cancelled"), campaign_id. Returns error if the campaign is
        not currently sending.

    Example:
        cancel_send(campaign_id="abc123") -> {"status": "cancelled", "campaign_id": "abc123"}
    """
    if (guard := _guard_write(action="cancel campaign send", campaign_id=campaign_id)):
        return guard
    mc_request(f"/campaigns/{campaign_id}/actions/cancel-send", method="POST")
    return json.dumps({"status": "cancelled", "campaign_id": campaign_id}, indent=2)


# --- Write Tools: Tags & Segments ---

@mcp.tool()
def create_segment(list_id: str, name: str, static: bool = True, match: Optional[str] = None, conditions_json: Optional[str] = None) -> str:
    """Create a new segment or tag in an audience for grouping members.

    Use to create either a static segment (tag, manual membership) or a dynamic (saved) segment
    with auto-membership based on conditions. For static segments, use add_members_to_segment
    afterward to populate. Use tag_member to apply tags to individual members one at a time.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        name: Display name for the segment or tag.
        static: If true (default), creates a static segment (tag) with manual membership.
            If false, creates a dynamic segment; match and conditions_json are required.
        match: Condition match type for dynamic segments. Valid values: 'all' (AND logic),
            'any' (OR logic). Required when static=false, ignored when static=true.
        conditions_json: JSON string of conditions array for dynamic segments. Required when
            static=false. Example: '[{"condition_type":"TextMerge","field":"merge_fields/FNAME","op":"is","value":"John"}]'

    Returns:
        JSON with fields: id (int, the new segment ID for use with add_members_to_segment,
        create_campaign), name, member_count, type ('static' or 'saved'), options (conditions
        for dynamic segments, null for static).

    Example:
        create_segment(list_id="abc123", name="VIP Customers") -> {"id": 12345, "name": "VIP Customers", "type": "static", ...}
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
    """Delete a segment or tag from an audience. Members themselves are not removed.

    Use to remove a segment you no longer need. The segment association with members is removed,
    but members stay in the audience. Cannot be undone. Use list_segments to find segment IDs.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). This operation is irreversible. Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        segment_id: The segment/tag ID to delete (numeric string, e.g. '12345'). Obtain from
            list_segments.

    Returns:
        JSON with fields: status ("deleted"), segment_id. Returns error if the segment does
        not exist.

    Example:
        delete_segment(list_id="abc123", segment_id="12345") -> {"status": "deleted", "segment_id": "12345"}
    """
    if (guard := _guard_write(action="delete segment", list_id=list_id, segment_id=segment_id)):
        return guard
    mc_request(f"/lists/{list_id}/segments/{segment_id}", method="DELETE")
    return json.dumps({"status": "deleted", "segment_id": segment_id}, indent=2)


@mcp.tool()
def add_members_to_segment(list_id: str, segment_id: str, emails: str) -> str:
    """Add multiple members to a static segment or tag by email address in a single request.

    Use to bulk-add members to an existing static segment. Only works on static segments (tags),
    not dynamic (saved) segments; use get_segment to check segment type. Members must already
    exist in the audience. Use tag_member instead for single-member tag management.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        segment_id: The static segment/tag ID (numeric string, e.g. '12345'). Must be type
            'static'. Obtain from list_segments.
        emails: Comma-separated email addresses to add (e.g. 'a@co.com,b@co.com'). Each email
            must already exist in the audience.

    Returns:
        JSON with fields: total_added (int), total_removed (int, always 0 for this operation),
        errors (array of error objects for emails that could not be added).

    Example:
        add_members_to_segment(list_id="abc123", segment_id="12345", emails="jane@co.com,john@co.com") -> {"total_added": 2, "total_removed": 0, "errors": []}
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
    """Remove multiple members from a static segment or tag by email address.

    Use to bulk-remove members from a static segment. Only removes the segment association;
    members remain in the audience. Only works on static segments (tags), not dynamic (saved)
    segments. Use tag_member with tags_to_remove for single-member removal.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        segment_id: The static segment/tag ID (numeric string, e.g. '12345'). Must be type
            'static'. Obtain from list_segments.
        emails: Comma-separated email addresses to remove (e.g. 'a@co.com,b@co.com').

    Returns:
        JSON with fields: total_added (int, always 0 for this operation), total_removed (int),
        errors (array of error objects).

    Example:
        remove_members_from_segment(list_id="abc123", segment_id="12345", emails="jane@co.com") -> {"total_added": 0, "total_removed": 1, "errors": []}
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

    Use to rename a segment or change its filter conditions. Only provided fields are updated.
    Use add_members_to_segment/remove_members_from_segment to manage static segment membership.
    Cannot change a segment from static to dynamic or vice versa.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        segment_id: The segment ID to update (numeric string, e.g. '12345'). Obtain from list_segments.
        name: New display name for the segment.
        match: Condition match type for dynamic segments. Valid values: 'all' (AND), 'any' (OR).
            Must be provided together with conditions_json. Ignored for static segments.
        conditions_json: JSON string of conditions array. Must be provided together with match.
            Example: '[{"condition_type":"TextMerge","field":"merge_fields/FNAME","op":"is","value":"John"}]'

    Returns:
        JSON with fields: id, name, member_count, type ('static' or 'saved'), options (conditions).

    Example:
        update_segment(list_id="abc123", segment_id="12345", name="Premium VIP") -> {"id": 12345, "name": "Premium VIP", "member_count": 150, ...}
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
    """Update an existing merge field's name, default value, required flag, or dropdown/radio choices.

    Use to rename a field, change its default, or update choices. The field type and tag cannot
    be changed after creation. Only provided fields are updated. Use list_merge_fields to find
    merge_id values.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        merge_id: The merge field ID to update (numeric string). Obtain from list_merge_fields.
        name: New display name for the field.
        required: Whether the field is required when subscribing.
        default_value: New default value for new subscribers.
        choices: New comma-separated choices for 'dropdown' or 'radio' types (e.g. 'Small,Medium,Large').
            Replaces all existing choices. Only applicable to dropdown/radio fields.

    Returns:
        JSON with fields: merge_id, tag, name, type, required.

    Example:
        update_merge_field(list_id="abc123", merge_id="5", name="Organization") -> {"merge_id": 5, "tag": "COMPANY", "name": "Organization", "type": "text", ...}
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
    """List interest categories (groups) defined for an audience, showing titles and form types.

    Interest categories are containers for interest options that subscribers can select (e.g.
    "Preferred Topics" with options "Tech", "Sports", "Music"). Use to discover category IDs,
    then use list_interests to see options within each category. Use create_interest_category
    to add new categories.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        count: Number of categories to return (1-1000, default 50).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and categories array. Each category: id (string, use with
        list_interests, create_interest, delete_interest_category), title, type ('checkboxes',
        'dropdown', 'radio', 'hidden'), list_id.

    Example:
        list_interest_categories(list_id="abc123") -> {"total_items": 2, "categories": [{"id": "abc", "title": "Topics", "type": "checkboxes", ...}]}
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
    """List interest options within a specific interest category, with subscriber counts per option.

    Use after list_interest_categories to see individual options (e.g. "Tech", "Sports") within
    a category. Interest IDs are used when setting member preferences via the API. Use
    create_interest to add new options.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        category_id: The interest category ID. Obtain from list_interest_categories.
        count: Number of interests to return (1-1000, default 50).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and interests array. Each interest: id (string, use with
        delete_interest), name, subscriber_count (int), display_order (int).

    Example:
        list_interests(list_id="abc123", category_id="cat456") -> {"total_items": 3, "interests": [{"id": "int789", "name": "Tech", "subscriber_count": 200, ...}]}
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
    """List all webhooks configured for an audience, showing callback URLs, subscribed events, and source filters.

    Use to audit existing webhook integrations or find webhook IDs before deleting via
    delete_webhook. Webhooks send HTTP POST requests to external URLs when audience events
    (subscribe, unsubscribe, profile update, etc.) occur. Use create_webhook to add new webhooks.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.

    Returns:
        JSON with total_items and webhooks array. Each webhook: id (string, use with
        delete_webhook), url (callback URL), events (object with boolean flags: subscribe,
        unsubscribe, profile, cleaned, upemail, campaign), sources (object with boolean flags:
        user, admin, api), list_id.

    Example:
        list_webhooks(list_id="abc123") -> {"total_items": 1, "webhooks": [{"id": "wh789", "url": "https://example.com/hook", "events": {"subscribe": true, ...}, ...}]}
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
    """Create a webhook for an audience that sends HTTP POST requests to an external URL when member events occur.

    Use to set up real-time event notifications. Side effect: Mailchimp sends a validation GET
    request to the URL during creation; the URL must be publicly accessible and return HTTP 200.
    If events or sources are omitted, all are enabled by default. Use list_webhooks to check
    existing webhooks. Use delete_webhook to remove.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        url: Publicly accessible HTTPS URL to receive webhook POST requests. Must respond to
            a GET validation request with HTTP 200. Example: 'https://example.com/hook'.
        events: Comma-separated events to listen for. Valid values: 'subscribe', 'unsubscribe',
            'profile', 'cleaned', 'upemail', 'campaign'. All enabled if omitted.
        sources: Comma-separated sources to filter by. Valid values: 'user' (subscriber actions),
            'admin' (Mailchimp UI actions), 'api' (API calls). All enabled if omitted.

    Returns:
        JSON with fields: id (string, use with delete_webhook), url, events (object with boolean
        flags), sources (object with boolean flags). Returns error if URL validation fails.

    Example:
        create_webhook(list_id="abc123", url="https://example.com/hook", events="subscribe,unsubscribe") -> {"id": "wh789", "url": "https://example.com/hook", "events": {"subscribe": true, "unsubscribe": true}, ...}
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
    """Delete a webhook from an audience, immediately stopping event notifications to the external URL.

    Use to stop sending notifications. The external URL stops receiving events immediately.
    Use list_webhooks to find webhook IDs. Use create_webhook to set up a replacement.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). This operation is irreversible. Respects read-only and dry-run modes.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        webhook_id: The webhook ID to delete. Obtain from list_webhooks.

    Returns:
        JSON with fields: status ("deleted"), webhook_id. Returns error if webhook does not exist.

    Example:
        delete_webhook(list_id="abc123", webhook_id="wh789") -> {"status": "deleted", "webhook_id": "wh789"}
    """
    if (guard := _guard_write(action="delete webhook", list_id=list_id, webhook_id=webhook_id)):
        return guard
    mc_request(f"/lists/{list_id}/webhooks/{webhook_id}", method="DELETE")
    return json.dumps({"status": "deleted", "webhook_id": webhook_id}, indent=2)


# --- Read Tools: Detailed Reports ---

@mcp.tool()
def get_email_activity(campaign_id: str, count: int = 20, offset: int = 0) -> str:
    """Retrieve the full activity timeline per recipient for a sent campaign (opens, clicks, bounces with timestamps).

    Use to see exactly what each recipient did and when. Use get_open_details if you only need
    open data. Use get_campaign_report for aggregate totals. Use get_campaign_recipients for
    delivery status only. Only works for sent campaigns.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        campaign_id: The Mailchimp campaign ID (e.g. 'abc123def4'). Must be a sent campaign.
        count: Number of recipient records to return (1-1000, default 20). Each record contains
            all activity for one recipient.
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and emails array. Each entry: email_address and activity array
        where each activity has action ('open', 'click', 'bounce'), timestamp (ISO 8601),
        and url (string, present only for click actions).

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
    """Retrieve per-recipient open data for a campaign showing who opened, when, and how many times.

    Use to identify engaged subscribers or analyze open timing patterns. Use get_campaign_report
    for aggregate open rates. Use get_email_activity for all activity types (opens, clicks,
    bounces) combined. Only works for sent campaigns.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        campaign_id: The Mailchimp campaign ID (e.g. 'abc123def4'). Must be a sent campaign.
        count: Number of records to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and members array. Each member: email_address, opens_count (int,
        total opens including repeats), opens (array of objects with timestamp in ISO 8601).

    Example:
        get_open_details(campaign_id="abc123", count=100) -> {"total_items": 1250, "members": [{"email_address": "jane@co.com", "opens_count": 3, "opens": [{"timestamp": "2025-06-01T10:00:00Z"}, ...]}]}
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
    """Retrieve members who unsubscribed as a result of a specific sent campaign, with their reasons.

    Use to analyze unsubscribe causes after a campaign. Use get_campaign_report for the aggregate
    unsubscribe count. Only works for sent campaigns.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        campaign_id: The Mailchimp campaign ID (e.g. 'abc123def4'). Must be a sent campaign.
        count: Number of records to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and unsubscribes array. Each entry: email_address, reason (string,
        subscriber-provided reason or null), timestamp (ISO 8601).

    Example:
        get_campaign_unsubscribes(campaign_id="abc123") -> {"total_items": 5, "unsubscribes": [{"email_address": "jane@co.com", "reason": "No longer interested", ...}]}
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
    """Retrieve e-commerce product activity for a campaign showing revenue and orders attributed to each product.

    Use to measure campaign ROI by product. Requires an active e-commerce store integration
    (Shopify, WooCommerce, etc.); returns empty results if none is connected. Use
    list_ecommerce_stores to verify integration status. Only works for sent campaigns.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        campaign_id: The Mailchimp campaign ID (e.g. 'abc123def4'). Must be a sent campaign.
        count: Number of products to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and products array. Each product: title (string), sku (string),
        image_url (string or null), total_revenue (float, in store currency), total_purchased (int).
        Returns total_items: 0 if no e-commerce store is connected.

    Example:
        get_ecommerce_product_activity(campaign_id="abc123") -> {"total_items": 5, "products": [{"title": "Blue T-Shirt", "total_revenue": 450.00, "total_purchased": 15, ...}]}
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
    """Retrieve child report data for A/B test variants, variate campaigns, or RSS-driven campaign items.

    Use only for campaigns with sub-reports: A/B tests (per-variant performance), variate
    campaigns (per-combination results), or RSS campaigns (per-item send stats). Returns empty
    or minimal data for regular campaigns; use get_campaign_report instead. Use
    get_campaign_details first to check campaign type ('absplit', 'variate', 'rss').

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        campaign_id: The Mailchimp campaign ID (e.g. 'abc123def4'). Should be type 'absplit',
            'variate', or 'rss' for meaningful results. Obtain from list_campaigns.

    Returns:
        JSON with sub-reports data. Format varies by campaign type: A/B tests include per-variant
        opens, clicks, and winner data; RSS campaigns include per-item send stats with dates.
        Returns minimal/empty data for regular campaigns.

    Example:
        get_campaign_sub_reports(campaign_id="abc123") -> {"sub_reports": [{"id": "variant_a", "opens": 150, "clicks": 30, ...}]}
    """
    data = mc_request(f"/reports/{campaign_id}/sub-reports")
    return json.dumps(data, indent=2)


# --- Read Tools: Member Activity ---

@mcp.tool()
def get_member_activity(list_id: str, email_address: str, count: int = 20) -> str:
    """Retrieve the email interaction history of a specific member (opens, clicks, bounces across all campaigns).

    Use to see a single member's engagement over time. Shows email-related actions only. Use
    get_member_events for custom API-triggered events. Use get_member_tags for tag assignments.
    Use search_members first if you need to find which audience a member belongs to.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        list_id: The Mailchimp audience/list ID (e.g. 'abc123def4'). Obtain from list_audiences.
        email_address: Email address of the member. Must exist in the audience.
        count: Number of activity records to return (1-1000, default 20).

    Returns:
        JSON with email_address and activity array. Each activity: action ('open', 'click',
        'bounce'), timestamp (ISO 8601), campaign_id (string), title (campaign title string).

    Example:
        get_member_activity(list_id="abc123", email_address="jane@co.com") -> {"email_address": "jane@co.com", "activity": [{"action": "open", "timestamp": "2025-06-01T10:00:00Z", "campaign_id": "abc123", ...}]}
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
    """List all individual emails within an automation workflow showing sequence, subject lines, delays, and send counts.

    Use to inspect what emails an automation sends and in what order. Do not confuse with
    get_email_activity, which is for regular campaign engagement. Use list_automations to find
    automation IDs. Use get_automation_email_queue to see queued subscribers for a specific email.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        automation_id: The automation workflow ID (e.g. 'auto123'). Obtain from list_automations.

    Returns:
        JSON with total_items and emails array. Each email: id (string, use with
        get_automation_email_queue), position (int, sequence order starting at 1), status
        ('sending', 'paused', 'draft'), subject_line, title, emails_sent (int), send_time
        (ISO 8601), delay (object with amount and type, e.g. {"amount": 1, "type": "day"}).

    Example:
        get_automation_emails(automation_id="auto123") -> {"total_items": 3, "emails": [{"id": "email1", "position": 1, "subject_line": "Welcome!", "emails_sent": 500, ...}]}
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
    """Pause all emails in an automation workflow, stopping delivery while preserving the queue.

    Use to temporarily stop an automation. Queued subscribers are preserved and will resume
    receiving emails when restarted via start_automation. New subscribers still enter the queue
    but do not receive emails while paused. Reversible.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Respects read-only and dry-run modes.

    Args:
        automation_id: The automation workflow ID (e.g. 'auto123'). Obtain from list_automations.

    Returns:
        JSON with fields: status ("paused"), automation_id. Returns error if automation is
        already paused or in draft status.

    Example:
        pause_automation(automation_id="auto123") -> {"status": "paused", "automation_id": "auto123"}
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
    """List all landing pages in the account with publication status, URLs, and associated audiences.

    Use to browse landing pages, find published URLs, or check status. Landing pages are
    standalone web pages for lead capture or promotions, not emails. Use get_landing_page for
    full details of a specific page. Do not confuse with list_campaigns (email campaigns).

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        count: Number of landing pages to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and landing_pages array. Each page: id (string, use with
        get_landing_page), name, title, status ('published', 'unpublished', 'draft'), url
        (public URL when published, null otherwise), published_at (ISO 8601 or null),
        created_at (ISO 8601), list_id (associated audience).

    Example:
        list_landing_pages() -> {"total_items": 3, "landing_pages": [{"name": "Spring Sale", "status": "published", "url": "https://mailchi.mp/abc123/spring-sale", ...}]}
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
    """Retrieve full details of a specific landing page including description, tracking settings, and timestamps.

    Use when you have a page_id and need complete information. Use list_landing_pages to browse
    all pages and discover page IDs.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        page_id: The landing page ID. Obtain from list_landing_pages.

    Returns:
        JSON with fields: id, name, title, description (string), status ('published',
        'unpublished', 'draft'), url (public URL or null), published_at (ISO 8601 or null),
        created_at (ISO 8601), updated_at (ISO 8601), list_id, tracking (object with
        analytics settings).

    Example:
        get_landing_page(page_id="page123") -> {"id": "page123", "name": "Spring Sale", "status": "published", "url": "https://mailchi.mp/abc123/spring-sale", ...}
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
    """List all connected e-commerce stores (Shopify, WooCommerce, etc.) with platform and currency info.

    Use to discover store IDs before querying orders (list_store_orders), products
    (list_store_products), or customers (list_store_customers). Also use to verify e-commerce
    integration status before calling get_ecommerce_product_activity. Returns total_items: 0
    if no integration is configured.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Returns:
        JSON with total_items and stores array. Each store: id (string, use as store_id in
        other e-commerce tools), list_id (associated audience), name, platform ('shopify',
        'woocommerce', 'bigcommerce', etc.), domain, currency_code (ISO 4217, e.g. 'USD'),
        money_format (display format string), created_at (ISO 8601).

    Example:
        list_ecommerce_stores() -> {"total_items": 1, "stores": [{"id": "store123", "name": "My Shop", "platform": "shopify", "currency_code": "USD", ...}]}
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
    """List orders from a connected e-commerce store with customer info, totals, and fulfillment status.

    Use to browse orders synced from your e-commerce platform. Requires an active integration;
    use list_ecommerce_stores to find store IDs and verify connectivity. Use
    list_store_customers for customer-level aggregates instead of per-order data.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        store_id: The e-commerce store ID. Obtain from list_ecommerce_stores.
        count: Number of orders to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and orders array. Each order: id (string), customer (email address
        string), order_total (float, in store currency), currency_code (ISO 4217),
        financial_status ('paid', 'pending', 'refunded', etc.), fulfillment_status ('fulfilled',
        'partial', null), processed_at_foreign (ISO 8601), lines_count (int, number of line items).

    Example:
        list_store_orders(store_id="store123", count=50) -> {"total_items": 200, "orders": [{"id": "ord_123", "customer": "jane@co.com", "order_total": 59.99, ...}]}
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

    Use to see how campaigns are organized. Folders are organizational containers only; they
    do not affect campaign behavior. Do not confuse with list_campaigns (which lists campaigns
    themselves).

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        count: Number of folders to return (1-1000, default 50).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and folders array. Each folder: id (string), name (string),
        count (int, number of campaigns in the folder).

    Example:
        list_campaign_folders() -> {"total_items": 3, "folders": [{"id": "folder123", "name": "Q1 2025", "count": 12}]}
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
    """Submit multiple API operations as a single asynchronous batch request for bulk processing.

    Use for bulk operations exceeding other tool limits (e.g. batch_subscribe handles up to 500;
    use this for larger imports). Operations run asynchronously in the background. Use
    get_batch_status to poll for completion. Each operation runs independently; failures in one
    do not affect others. Can include destructive operations (DELETE, POST).

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Respects read-only and dry-run modes.

    Args:
        operations: JSON string of operations array. Each operation requires: method (string,
            HTTP verb: 'GET', 'POST', 'PATCH', 'PUT', 'DELETE'), path (string, API endpoint
            without base URL, e.g. '/lists/abc123/members'), and optionally body (JSON string
            for POST/PATCH/PUT).
            Example: '[{"method":"POST","path":"/lists/abc123/members/hash/tags","body":"{\"tags\":[{\"name\":\"VIP\",\"status\":\"active\"}]}"}]'

    Returns:
        JSON with fields: id (string, batch ID for use with get_batch_status), status ('pending'),
        total_operations (int), submitted_at (ISO 8601).

    Example:
        create_batch(operations='[{"method":"GET","path":"/lists"}]') -> {"id": "batch123", "status": "pending", "total_operations": 1, ...}
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
    """List recent batch operations with their status and progress.

    Use to find batch IDs or monitor multiple ongoing batches. Use get_batch_status for detailed
    progress on a specific batch.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        count: Number of batch operations to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and batches array. Each batch: id (string), status ('pending',
        'started', 'finished'), total_operations (int), finished_operations (int),
        errored_operations (int), submitted_at (ISO 8601), completed_at (ISO 8601 or null).

    Example:
        list_batches(count=10) -> {"total_items": 5, "batches": [{"id": "batch123", "status": "finished", "total_operations": 100, ...}]}
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
    """Check API connectivity and verify that the Mailchimp API key is valid.

    Use as a health check before running other operations. Fastest way to verify the API key is
    correctly configured. Do not use get_account_info for health checks; this is lighter and
    purpose-built. Returns error if the key is invalid or missing.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Returns:
        JSON with fields: health_check (string, 'ok' if connected), status_code (int, 200 if
        healthy). Returns error object if the API key is invalid.

    Example:
        ping() -> {"health_check": "ok", "status_code": 200}
    """
    data = mc_request("/ping")
    return json.dumps({
        "health_check": data.get("health_check"),
        "status_code": 200 if "health_check" in data else data.get("status", 0),
    }, indent=2)


@mcp.tool()
def search_campaigns(query: str, count: int = 20, offset: int = 0) -> str:
    """Search campaigns by keyword across titles, subject lines, and list names.

    Use to find campaigns by keyword when you do not know the campaign ID. Use list_campaigns
    instead to browse all campaigns by status or date. Use get_campaign_details for full settings
    once you have the ID.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        query: Search query string. Matches against campaign titles, subject lines, and list
            names (e.g. 'spring sale', 'newsletter'). Minimum 3 characters.
        count: Number of results to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and results array. Each result contains a campaign object with:
        id, type, status, title, subject_line, send_time (ISO 8601 or null), emails_sent (int).

    Example:
        search_campaigns(query="spring sale") -> {"total_items": 3, "results": [{"campaign": {"id": "abc123", "title": "Spring Sale 2025", "status": "sent", ...}}]}
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
    """Create a new draft campaign targeting only recipients who did not open the original sent campaign.

    Use to resend a campaign to non-openers with a potentially different subject line. The
    original must be a sent campaign. Creates a new campaign in 'save' (draft) status. Use
    update_campaign to change the subject line, then send_campaign or schedule_campaign to deliver.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Respects read-only and dry-run modes.

    Args:
        campaign_id: The ID of the original sent campaign (e.g. 'abc123def4'). Must have
            status 'sent'. Obtain from list_campaigns(status='sent').

    Returns:
        JSON with fields: id (string, the NEW campaign's ID), status ('save'), title (string),
        web_id (int). Returns error if original campaign was not sent.

    Example:
        resend_to_non_openers(campaign_id="abc123") -> {"id": "def456", "status": "save", "title": "Spring Sale (Resend)", "web_id": 789012}
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

    Use to programmatically enroll a contact at a specific entry point in a Customer Journey
    (the successor to Classic Automations, with branching logic). The contact must already exist
    as a subscribed member in the journey's audience. Side effect: the contact begins receiving
    journey emails immediately. Journey and step IDs must be obtained from the Mailchimp web UI
    or the automations API.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Respects read-only and dry-run modes.

    Args:
        journey_id: The Customer Journey ID (e.g. 'journey123'). Found in the Mailchimp web UI
            URL or via list_automations.
        step_id: The specific step ID to trigger the contact into. Must be an API-trigger entry
            point step configured in the journey.
        email_address: Email address of the contact to enroll. Must be a subscribed member of
            the journey's audience.

    Returns:
        JSON with fields: status ('triggered'), journey_id, step_id, email_address. Returns
        error if the contact is not subscribed or the step is not a valid trigger point.

    Example:
        trigger_customer_journey(journey_id="j123", step_id="s456", email_address="jane@co.com") -> {"status": "triggered", "journey_id": "j123", "step_id": "s456", "email_address": "jane@co.com"}
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
