import hashlib
import json
import os
from typing import Optional

import requests
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
def get_campaign_content(campaign_id: str, include_html: bool = False) -> str:
    """Retrieve the rendered body content (plain text and optional HTML) of a campaign.

    Use to read the actual email copy that was sent — for content analysis, auditing, or
    repurposing. Use get_campaign_details for settings/metadata (subject, sender) and
    get_campaign_report for post-send performance. Use list_campaigns or search_campaigns to
    find campaign IDs.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Read-only, safe to retry.

    Args:
        campaign_id: The Mailchimp campaign ID (e.g. 'abc123def4'). Obtain from list_campaigns
            or search_campaigns. This is the API id, not the numeric web_id from the dashboard URL.
        include_html: If True, also include the raw HTML body. Defaults to False to keep
            responses small and analysis-friendly; plain_text is usually sufficient.

    Returns:
        JSON with fields: campaign_id, plain_text (the plain-text body), and html (only when
        include_html=True). For A/B (variate) campaigns, a variations array is included with one
        entry per content variation: {label, plain_text, html (if include_html)}. Returns error
        if the campaign_id is invalid or the campaign has no content.

    Example:
        get_campaign_content(campaign_id="abc123def4") -> {"campaign_id": "abc123def4", "plain_text": "Hi *|FNAME|* ..."}
    """
    data = mc_request(f"/campaigns/{campaign_id}/content")
    if isinstance(data, dict) and "error" in data:
        return json.dumps(data, indent=2)

    result: dict = {
        "campaign_id": campaign_id,
        "plain_text": data.get("plain_text", ""),
    }
    if include_html:
        result["html"] = data.get("html", "")

    variations = data.get("variate_contents") or []
    if variations:
        result["variations"] = [
            {
                "label": v.get("content_label", ""),
                "plain_text": v.get("plain_text", ""),
                **({"html": v.get("html", "")} if include_html else {}),
            }
            for v in variations
        ]

    return json.dumps(result, indent=2)


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
    """List Classic Automation workflows in the account with status and send counts.

    Returns Classic Automations only — ordered by creation date descending. Customer Journeys
    are NOT returned (Mailchimp does not expose a public read endpoint for journeys; only the
    journey-step trigger endpoint is public). To see what your Customer Journeys are sending,
    use search_automation_campaigns instead (it lists every campaign emitted by either system).
    Use get_automation_emails for individual emails within a Classic workflow. Use
    get_automation_summary for a counted overview combining both systems.

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
def get_automation_summary(days: int = 30) -> str:
    """Summarise automation activity across Classic Automations and Customer Journeys.

    Combines two API calls into a single overview useful for audits and dashboards:
    1. /automations to count Classic workflows by status (sending / paused / draft)
    2. /campaigns?type=automation&since_send_time=N days ago to count and sum what
       automations have actually sent recently (both Classic and Customer Journey emails
       show up as type='automation' campaigns)

    This is the recommended starting point for "what's my automation stack doing right now?"
    questions during an account audit. Use list_automations for the raw Classic list. Use
    search_automation_campaigns for the raw recent automation campaign feed.

    Authenticated via API key. Max 10 concurrent requests (2 are issued by this tool).
    Read-only, safe to retry.

    Args:
        days: Lookback window in days for the recent-sends portion (1-365, default 30).

    Returns:
        JSON with two sections:
        - classic_automations: total, by_status ({sending, paused, draft, ...})
        - recent_automation_campaigns: window_days, total_campaigns, total_emails_sent,
          top_titles (up to 5 titles ordered by emails_sent desc)
    """
    automations_data = mc_request("/automations", params={"count": 1000})
    by_status: dict = {}
    classic_total = 0
    if isinstance(automations_data, dict) and "error" not in automations_data:
        for a in automations_data.get("automations", []):
            classic_total += 1
            status = a.get("status") or "unknown"
            by_status[status] = by_status.get(status, 0) + 1

    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    campaigns_data = mc_request(
        "/campaigns",
        params={"count": 1000, "type": "automation", "since_send_time": since},
    )
    recent_campaigns: list = []
    recent_emails_sent = 0
    if isinstance(campaigns_data, dict) and "error" not in campaigns_data:
        for c in campaigns_data.get("campaigns", []):
            sent = c.get("emails_sent") or 0
            recent_emails_sent += sent
            recent_campaigns.append({
                "title": c.get("settings", {}).get("title"),
                "emails_sent": sent,
            })
    recent_campaigns.sort(key=lambda c: c.get("emails_sent") or 0, reverse=True)
    top_titles = [
        {"title": c["title"], "emails_sent": c["emails_sent"]}
        for c in recent_campaigns[:5]
    ]

    return json.dumps({
        "classic_automations": {
            "total": classic_total,
            "by_status": by_status,
        },
        "recent_automation_campaigns": {
            "window_days": days,
            "total_campaigns": len(recent_campaigns),
            "total_emails_sent": recent_emails_sent,
            "top_titles": top_titles,
        },
    }, indent=2)


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
def get_template(template_id: str) -> str:
    """Retrieve metadata for a template (name, type, dates, folder, thumbnail) without its HTML content.

    Use to inspect a template's settings or verify it exists before referencing it elsewhere.
    Use get_template_default_content to fetch the actual HTML body. Use list_templates to browse
    and discover template IDs.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.
    Returns 404 error if template_id is invalid.

    Args:
        template_id: Template ID (numeric string, e.g. '12345'). Obtain from list_templates.

    Returns:
        JSON with id, name, type ('user' | 'base' | 'gallery'), drag_and_drop (bool),
        date_created, date_edited, created_by, edited_by, active (bool), folder_id, thumbnail,
        share_url, category.
    """
    data = mc_request(f"/templates/{template_id}")
    return json.dumps({
        "id": data.get("id"),
        "name": data.get("name"),
        "type": data.get("type"),
        "drag_and_drop": data.get("drag_and_drop"),
        "date_created": data.get("date_created"),
        "date_edited": data.get("date_edited"),
        "created_by": data.get("created_by"),
        "edited_by": data.get("edited_by"),
        "active": data.get("active"),
        "folder_id": data.get("folder_id"),
        "thumbnail": data.get("thumbnail"),
        "share_url": data.get("share_url"),
        "category": data.get("category"),
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


@mcp.tool()
def create_audience(name: str, from_name: str, from_email: str, subject: str, language: str, company: str, address1: str, city: str, state: str, zip: str, country: str, permission_reminder: str, email_type_option: bool = False, address2: Optional[str] = None, phone: Optional[str] = None) -> str:
    """Create a new audience (list) with required contact info, campaign defaults, and permission reminder.

    Side effect: creates a billable audience under the Mailchimp plan. Mailchimp requires all
    contact fields (company, address, city, state, zip, country) and CAN-SPAM-compliant permission
    reminder text. Use update_audience to modify later, delete_audience for cleanup, or
    list_audiences to verify creation.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.
    Returns 400 error if any required field is missing or the plan audience limit is reached.

    Args:
        name: Audience display name shown in dashboard and audience picker (max 100 chars).
        from_name: Default sender name on campaigns (e.g. 'Marketing Team'). Max 100 chars.
        from_email: Default sender email. Must be on a verified sending domain.
        subject: Default subject line for new campaigns. Max 150 chars.
        language: Default language code (e.g. 'en', 'fr', 'es'). ISO 639-1 two-letter code.
        company: Legal company name displayed in email footer (required by CAN-SPAM).
        address1: Primary postal address line shown in email footer.
        city: City of the postal address.
        state: State or region of the postal address.
        zip: Postal/ZIP code.
        country: Two-letter ISO country code (e.g. 'US', 'FR', 'GB').
        permission_reminder: Sentence shown at the bottom of every email explaining why
            subscribers receive it (required by CAN-SPAM).
        email_type_option: If true, lets subscribers choose plaintext vs. HTML emails. Default false.
        address2: Optional secondary postal address line.
        phone: Optional contact phone number shown in the footer.

    Returns:
        JSON with id (new list_id, save for subsequent calls), name, member_count (0 at creation),
        date_created, subscribe_url_short.
    """
    if (guard := _guard_write(action="create audience", name=name, from_email=from_email)):
        return guard
    contact: dict = {
        "company": company,
        "address1": address1,
        "city": city,
        "state": state,
        "zip": zip,
        "country": country,
    }
    if address2:
        contact["address2"] = address2
    if phone:
        contact["phone"] = phone
    body = {
        "name": name,
        "contact": contact,
        "permission_reminder": permission_reminder,
        "campaign_defaults": {
            "from_name": from_name,
            "from_email": from_email,
            "subject": subject,
            "language": language,
        },
        "email_type_option": email_type_option,
    }
    data = mc_request("/lists", body=body, method="POST")
    if isinstance(data, dict) and "error" in data:
        return json.dumps(data, indent=2)
    return json.dumps({
        "id": data.get("id"),
        "name": data.get("name"),
        "member_count": data.get("stats", {}).get("member_count", 0),
        "date_created": data.get("date_created"),
        "subscribe_url_short": data.get("subscribe_url_short"),
    }, indent=2)


@mcp.tool()
def delete_audience(list_id: str) -> str:
    """Permanently delete an audience and all its members, segments, campaigns, and stats. Irreversible.

    Side effect: removes every member of the audience and all historical data tied to it.
    Cannot be undone via the API. Use update_audience to rename or archive-like changes instead.
    Use list_audience_members to back up members first if needed.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.
    Returns 404 error if list_id does not exist.

    Args:
        list_id: Audience/list ID to delete (10-char alphanumeric, e.g. 'abc123def4').
            Obtain from list_audiences. Double-check before calling — deletion is permanent.

    Returns:
        JSON with status ('deleted') and list_id on success, or error object on failure.
    """
    if (guard := _guard_write(action="delete audience", list_id=list_id)):
        return guard
    result = mc_request(f"/lists/{list_id}", method="DELETE")
    if isinstance(result, dict) and "error" in result:
        return json.dumps(result, indent=2)
    return json.dumps({"status": "deleted", "list_id": list_id}, indent=2)


# --- Write Tools: Campaigns ---

@mcp.tool()
def create_campaign(list_id: str, subject_line: str, title: Optional[str] = None, preview_text: Optional[str] = None, from_name: Optional[str] = None, reply_to: Optional[str] = None, segment_id: Optional[str] = None, campaign_type: str = "regular", variate_settings_json: Optional[str] = None) -> str:
    """Create a new email campaign in draft status, with optional segment targeting or A/B variate testing.

    Typical workflow: create_campaign -> set_campaign_content (add HTML body) -> send_test_email
    (preview) -> send_campaign or schedule_campaign (deliver). The campaign is created in 'save'
    (draft) status and cannot be sent until content is set. Use replicate_campaign instead to
    clone an existing campaign.

    For A/B testing, set campaign_type='variate' and pass variate_settings_json describing the
    test. Mailchimp will send variants to a sample of recipients, then auto-pick a winner based
    on winner_criteria and send it to the remaining audience after wait_time.

    Authenticated via API key. Subject to Mailchimp API rate limits (max 10 concurrent requests). Respects read-only and dry-run modes.

    Args:
        list_id: The audience/list ID to send to (e.g. 'abc123def4'). Obtain from list_audiences.
        subject_line: Subject line recipients see in their inbox. Keep under 150 chars.
            For variate campaigns testing subject lines, this is the default/fallback.
        title: Internal title for organizing in Mailchimp dashboard. Defaults to subject_line
            if omitted.
        preview_text: Preheader text shown after the subject line in inbox. Keep under 200 chars.
        from_name: Sender name on the email. Falls back to audience default if omitted.
        reply_to: Reply-to email address. Must be a verified domain. Falls back to audience default.
        segment_id: Saved segment ID to restrict recipients. Only members matching this segment
            receive the email. Obtain from list_segments. Omit to send to the full audience.
        campaign_type: 'regular' (default) for a standard campaign, or 'variate' for an A/B test.
            'plaintext', 'rss', and 'absplit' (legacy A/B) are also accepted but rarely used.
        variate_settings_json: Required when campaign_type='variate'. JSON string with keys:
            winner_criteria ('opens' | 'clicks' | 'manual' | 'total_revenue'), test_size (10-100,
            percent of audience sampled), wait_time (minutes before picking winner), and one of
            subject_lines (list of 2-8 strings), from_names (list of 2-8), reply_to_addresses
            (list of 2-8), send_times (list of 2-8 ISO datetimes), or contents (list of 2-8
            HTML strings). Example:
            '{"winner_criteria": "opens", "test_size": 20, "wait_time": 1440,
              "subject_lines": ["Spring Sale 20% off", "Last chance: 20% off Spring"]}'

    Returns:
        JSON with fields: id (string, the new campaign ID for use with set_campaign_content,
        send_campaign, etc.), status ('save'), title, subject_line, web_id (int, for Mailchimp
        web UI link), type. Returns error if list_id is invalid, variate_settings_json is
        malformed, or variate settings violate Mailchimp constraints.

    Example:
        create_campaign(list_id="abc123", subject_line="Spring Sale", preview_text="20% off") -> {"id": "def456", "status": "save", "type": "regular", ...}
    """
    if (guard := _guard_write(action="create campaign draft", list_id=list_id, subject_line=subject_line, campaign_type=campaign_type)):
        return guard
    if campaign_type == "variate" and not variate_settings_json:
        return json.dumps({"error": "variate_settings_json is required when campaign_type='variate'"}, indent=2)
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
    body: dict = {
        "type": campaign_type,
        "recipients": recipients,
        "settings": settings,
    }
    if variate_settings_json:
        try:
            body["variate_settings"] = json.loads(variate_settings_json)
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid variate_settings_json: {e}"}, indent=2)
    data = mc_request("/campaigns", body=body, method="POST")
    if isinstance(data, dict) and "error" in data:
        return json.dumps(data, indent=2)
    return json.dumps({
        "id": data.get("id"),
        "status": data.get("status"),
        "type": data.get("type"),
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
    result = mc_request(f"/campaigns/{campaign_id}/content", body={"html": html}, method="PUT")
    if isinstance(result, dict) and "error" in result:
        return json.dumps(result, indent=2)
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
def get_campaign_advice(campaign_id: str) -> str:
    """Retrieve Mailchimp's automated post-send feedback on a campaign (subject line, content, engagement tips).

    Use to surface algorithmic suggestions Mailchimp makes after looking at how a campaign
    performed (e.g. 'your open rate is below industry average, try shorter subject lines').
    Use get_campaign_report for raw metrics. Only works for sent campaigns.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.
    Returns 404 error if campaign_id is invalid. Returns an empty advice array if Mailchimp
    has no suggestions for the campaign.

    Args:
        campaign_id: The Mailchimp campaign ID (e.g. 'abc123def4'). Must be a sent campaign.

    Returns:
        JSON with total_items and advice array. Each entry: type ('positive' | 'negative' |
        'neutral'), message (string, the advice text).
    """
    data = mc_request(f"/reports/{campaign_id}/advice")
    advice = []
    for a in data.get("advice", []):
        advice.append({"type": a.get("type"), "message": a.get("message")})
    return json.dumps({"total_items": data.get("total_items"), "advice": advice}, indent=2)


@mcp.tool()
def get_campaign_locations(campaign_id: str, count: int = 20, offset: int = 0) -> str:
    """Retrieve geographic open data for a sent campaign, broken down by country and region.

    Use to map where opens happened — useful for region-targeted follow-ups, timezone-aware
    sending, or audit reports. Aggregated from IP geolocation at open time. Use
    get_domain_performance for per-provider stats instead. Only works for sent campaigns.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.

    Args:
        campaign_id: The Mailchimp campaign ID (e.g. 'abc123def4'). Must be a sent campaign.
        count: Number of locations to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with total_items and locations array. Each entry: country_code (ISO 2-letter,
        e.g. 'US'), region (string, state/province name or code), region_name (full name),
        opens (int, opens from that region).
    """
    data = mc_request(f"/reports/{campaign_id}/locations", params={"count": count, "offset": offset})
    locations = []
    for loc in data.get("locations", []):
        locations.append({
            "country_code": loc.get("country_code"),
            "region": loc.get("region"),
            "region_name": loc.get("region_name"),
            "opens": loc.get("opens"),
        })
    return json.dumps({"total_items": data.get("total_items"), "locations": locations}, indent=2)


@mcp.tool()
def get_eepurl_activity(campaign_id: str) -> str:
    """Retrieve social sharing stats for a campaign's eepurl (Mailchimp's short-URL share link).

    Use to measure how much the campaign was shared on Twitter/Facebook/etc. via the
    'Share this' link Mailchimp generates. Use get_campaign_click_details for in-email link
    clicks instead. Only works for sent campaigns where eepurl tracking is enabled.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.

    Args:
        campaign_id: The Mailchimp campaign ID (e.g. 'abc123def4'). Must be a sent campaign.

    Returns:
        JSON with eepurl (the short URL), twitter (object with statuses, first_status,
        last_status, replies, impressions, retweets), facebook (object with likes, recipient_likes,
        unique_likes), referrers array (list of {referrer, clicks, first_click, last_click}).
    """
    data = mc_request(f"/reports/{campaign_id}/eepurl")
    return json.dumps({
        "eepurl": data.get("eepurl"),
        "twitter": data.get("twitter"),
        "facebook": data.get("facebook"),
        "referrers": data.get("clicks", {}).get("referrer_clicks", []),
    }, indent=2)


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


@mcp.tool()
def get_member_journey_events(list_id: str, email_address: str, count: int = 50) -> str:
    """Retrieve a member's activity events filtered to automation- and journey-related actions.

    Returns the subset of the member's activity feed that relates to Classic Automations and
    (where Mailchimp surfaces them) Customer Journey emails. Useful to answer "what automation
    or journey emails has this contact received?" without scanning their full activity.

    Note: Mailchimp does not expose a public read API for Customer Journeys themselves. Journey
    emails do appear in the activity feed as automation-typed actions, so this tool surfaces them
    via that side-channel rather than reading the journey graph directly. Use trigger_customer_journey
    to enroll a contact into a specific journey step (the only journey write available via API).

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.

    Args:
        list_id: Audience/list ID (10-char alphanumeric). Obtain from list_audiences.
        email_address: Email of the member. Must exist in the audience.
        count: Number of activity rows to scan before filtering (1-1000, default 50). Raise if
            the member is highly active and you suspect automation events are missed.

    Returns:
        JSON with email_address, scanned (raw row count looked at), total_journey_events (after
        filtering), and events array. Each event: action (raw action type), timestamp, title
        (campaign / automation title if present), url (link clicked if any), campaign_id.
    """
    subscriber_hash = hashlib.md5(email_address.lower().encode()).hexdigest()
    data = mc_request(
        f"/lists/{list_id}/members/{subscriber_hash}/activity-feed",
        params={"count": count},
    )
    automation_keywords = ("automation", "journey")
    filtered = []
    raw_activity = data.get("activity", [])
    for a in raw_activity:
        action = (a.get("action") or "").lower()
        if any(k in action for k in automation_keywords):
            filtered.append({
                "action": a.get("action"),
                "timestamp": a.get("timestamp"),
                "title": a.get("title"),
                "url": a.get("url"),
                "campaign_id": a.get("campaign_id"),
            })
    return json.dumps({
        "email_address": email_address,
        "scanned": len(raw_activity),
        "total_journey_events": len(filtered),
        "events": filtered,
    }, indent=2)


# --- Read/Write Tools: Member Notes ---

@mcp.tool()
def list_member_notes(list_id: str, email_address: str, count: int = 20, offset: int = 0) -> str:
    """List CRM-style notes attached to a member by team members (not visible to the contact).

    Notes are internal annotations like "Called about pricing" or "VIP customer". They are not
    sent to the contact and do not affect deliverability. Use add_member_note to create one,
    update_member_note to edit, delete_member_note to remove.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.
    Returns 404 error if the member does not exist.

    Args:
        list_id: Audience/list ID (10-char alphanumeric, e.g. 'abc123def4'). Obtain from list_audiences.
        email_address: Email of the member whose notes to list. Must exist in the audience.
        count: Number of notes to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.

    Returns:
        JSON with email_address, total_items, and notes array. Each note: id (use as note_id),
        note (string, the text), created_at, created_by, updated_at.
    """
    subscriber_hash = hashlib.md5(email_address.lower().encode()).hexdigest()
    data = mc_request(
        f"/lists/{list_id}/members/{subscriber_hash}/notes",
        params={"count": count, "offset": offset},
    )
    notes = []
    for n in data.get("notes", []):
        notes.append({
            "id": n.get("id"),
            "note": n.get("note"),
            "created_at": n.get("created_at"),
            "created_by": n.get("created_by"),
            "updated_at": n.get("updated_at"),
        })
    return json.dumps({
        "email_address": email_address,
        "total_items": data.get("total_items"),
        "notes": notes,
    }, indent=2)


@mcp.tool()
def add_member_note(list_id: str, email_address: str, note: str) -> str:
    """Add a CRM-style internal note to a member. Not sent to the contact.

    Useful for sales/support context, e.g. "Asked for discount on annual plan", "Out of office
    until June 1st". Use update_member_note to edit an existing note instead of adding another.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.
    Returns 404 if the member does not exist; returns 400 if note text exceeds 1000 chars.

    Args:
        list_id: Audience/list ID. Obtain from list_audiences.
        email_address: Email of the member to attach the note to. Must exist in the audience.
        note: Note text (max 1000 chars). Plain text; markdown is not rendered in the Mailchimp UI.

    Returns:
        JSON with id (use as note_id), email_address, note, created_at, created_by.
    """
    if (guard := _guard_write(action="add member note", list_id=list_id, email_address=email_address)):
        return guard
    subscriber_hash = hashlib.md5(email_address.lower().encode()).hexdigest()
    data = mc_request(
        f"/lists/{list_id}/members/{subscriber_hash}/notes",
        body={"note": note},
        method="POST",
    )
    if isinstance(data, dict) and "error" in data:
        return json.dumps(data, indent=2)
    return json.dumps({
        "id": data.get("id"),
        "email_address": email_address,
        "note": data.get("note"),
        "created_at": data.get("created_at"),
        "created_by": data.get("created_by"),
    }, indent=2)


@mcp.tool()
def update_member_note(list_id: str, email_address: str, note_id: str, note: str) -> str:
    """Update the text of an existing member note. Replaces the entire note body.

    Use list_member_notes to find note_ids. Use add_member_note instead to create a new note
    rather than overwriting; use delete_member_note to remove a note.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.
    Returns 404 if the note or member does not exist.

    Args:
        list_id: Audience/list ID. Obtain from list_audiences.
        email_address: Email of the member who owns the note.
        note_id: Note ID to update. Obtain from list_member_notes.
        note: New note text (max 1000 chars). Replaces the previous text entirely.

    Returns:
        JSON with id, email_address, note (new value), updated_at.
    """
    if (guard := _guard_write(action="update member note", list_id=list_id, email_address=email_address, note_id=note_id)):
        return guard
    subscriber_hash = hashlib.md5(email_address.lower().encode()).hexdigest()
    data = mc_request(
        f"/lists/{list_id}/members/{subscriber_hash}/notes/{note_id}",
        body={"note": note},
        method="PATCH",
    )
    if isinstance(data, dict) and "error" in data:
        return json.dumps(data, indent=2)
    return json.dumps({
        "id": data.get("id"),
        "email_address": email_address,
        "note": data.get("note"),
        "updated_at": data.get("updated_at"),
    }, indent=2)


@mcp.tool()
def delete_member_note(list_id: str, email_address: str, note_id: str) -> str:
    """Permanently delete a note attached to a member. Cannot be undone.

    Use list_member_notes to find note_ids before calling. Does not affect the member itself,
    only the note.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.
    Returns 404 if the note or member does not exist.

    Args:
        list_id: Audience/list ID. Obtain from list_audiences.
        email_address: Email of the member who owns the note.
        note_id: Note ID to delete. Obtain from list_member_notes.

    Returns:
        JSON with status ('deleted'), email_address, note_id on success.
    """
    if (guard := _guard_write(action="delete member note", list_id=list_id, email_address=email_address, note_id=note_id)):
        return guard
    subscriber_hash = hashlib.md5(email_address.lower().encode()).hexdigest()
    result = mc_request(
        f"/lists/{list_id}/members/{subscriber_hash}/notes/{note_id}",
        method="DELETE",
    )
    if isinstance(result, dict) and "error" in result:
        return json.dumps(result, indent=2)
    return json.dumps({"status": "deleted", "email_address": email_address, "note_id": note_id}, indent=2)


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


# --- Write Tools: Landing Pages ---

@mcp.tool()
def create_landing_page(name: str, title: str, list_id: str, template_id: str, store_id: Optional[str] = None, description: Optional[str] = None, tracking_opens: bool = True, tracking_clicks: bool = True) -> str:
    """Create a new landing page in draft status from a template, optionally linked to a store.

    The page is created unpublished. Use update_landing_page to edit settings or
    publish_landing_page to make it live at its public URL. Use list_landing_pages or
    get_landing_page to inspect existing pages.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.
    Returns 400 error if template_id is invalid or list_id does not exist.

    Args:
        name: Internal name for the page (shown in the Mailchimp dashboard, not to visitors).
        title: Browser tab title (shown in the page's HTML <title>).
        list_id: Audience ID this page collects signups for (e.g. 'abc123def4').
            Obtain from list_audiences.
        template_id: Template ID to base the page on. Obtain from list_templates.
        store_id: Optional e-commerce store ID to link the page to. Obtain from
            list_ecommerce_stores.
        description: Optional internal description.
        tracking_opens: Track view-opens analytics. Default true.
        tracking_clicks: Track link clicks analytics. Default true.

    Returns:
        JSON with id (use as page_id for subsequent calls), name, title, status ('unpublished'),
        url (null until published), created_at, list_id.
    """
    if (guard := _guard_write(action="create landing page", name=name, list_id=list_id)):
        return guard
    body: dict = {
        "name": name,
        "title": title,
        "list_id": list_id,
        "template": {"id": int(template_id)},
        "tracking": {"opens": tracking_opens, "clicks": tracking_clicks},
    }
    if store_id:
        body["store_id"] = store_id
    if description:
        body["description"] = description
    data = mc_request("/landing-pages", body=body, method="POST")
    if isinstance(data, dict) and "error" in data:
        return json.dumps(data, indent=2)
    return json.dumps({
        "id": data.get("id"),
        "name": data.get("name"),
        "title": data.get("title"),
        "status": data.get("status"),
        "url": data.get("url"),
        "created_at": data.get("created_at"),
        "list_id": data.get("list_id"),
    }, indent=2)


@mcp.tool()
def update_landing_page(page_id: str, name: Optional[str] = None, title: Optional[str] = None, description: Optional[str] = None, tracking_opens: Optional[bool] = None, tracking_clicks: Optional[bool] = None) -> str:
    """Update settings of an existing landing page. Only provided fields are changed.

    Cannot change list_id or template after creation; create a new page instead. Use
    publish_landing_page / unpublish_landing_page to change live status. Use get_landing_page
    to inspect current settings before updating.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.
    Returns 404 error if page_id is invalid.

    Args:
        page_id: Landing page ID. Obtain from list_landing_pages.
        name: New internal name.
        title: New browser tab title.
        description: New internal description.
        tracking_opens: Toggle open tracking on/off.
        tracking_clicks: Toggle click tracking on/off.

    Returns:
        JSON with id, name, title, status, url, updated_at, list_id.
    """
    if (guard := _guard_write(action="update landing page", page_id=page_id)):
        return guard
    body: dict = {}
    if name is not None:
        body["name"] = name
    if title is not None:
        body["title"] = title
    if description is not None:
        body["description"] = description
    tracking: dict = {}
    if tracking_opens is not None:
        tracking["opens"] = tracking_opens
    if tracking_clicks is not None:
        tracking["clicks"] = tracking_clicks
    if tracking:
        body["tracking"] = tracking
    data = mc_request(f"/landing-pages/{page_id}", body=body, method="PATCH")
    if isinstance(data, dict) and "error" in data:
        return json.dumps(data, indent=2)
    return json.dumps({
        "id": data.get("id"),
        "name": data.get("name"),
        "title": data.get("title"),
        "status": data.get("status"),
        "url": data.get("url"),
        "updated_at": data.get("updated_at"),
        "list_id": data.get("list_id"),
    }, indent=2)


@mcp.tool()
def delete_landing_page(page_id: str) -> str:
    """Permanently delete a landing page. Cannot be undone.

    Side effect: the page becomes inaccessible at its public URL immediately. Past visit
    analytics remain in Mailchimp's reports area but the page itself is gone. Use
    unpublish_landing_page if you only want to take it offline temporarily.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.
    Returns 404 error if page_id is invalid.

    Args:
        page_id: Landing page ID to delete. Obtain from list_landing_pages.

    Returns:
        JSON with status ('deleted') and page_id on success.
    """
    if (guard := _guard_write(action="delete landing page", page_id=page_id)):
        return guard
    result = mc_request(f"/landing-pages/{page_id}", method="DELETE")
    if isinstance(result, dict) and "error" in result:
        return json.dumps(result, indent=2)
    return json.dumps({"status": "deleted", "page_id": page_id}, indent=2)


@mcp.tool()
def publish_landing_page(page_id: str) -> str:
    """Publish a landing page, making it live at its public URL.

    Idempotent on already-published pages. Use unpublish_landing_page to take a page offline.
    Use get_landing_page to confirm the live URL after publishing.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.
    Returns 400 if the page is missing required content; returns 404 if page_id is invalid.

    Args:
        page_id: Landing page ID to publish. Obtain from list_landing_pages.

    Returns:
        JSON with status ('published') and page_id on success.
    """
    if (guard := _guard_write(action="publish landing page", page_id=page_id)):
        return guard
    result = mc_request(f"/landing-pages/{page_id}/actions/publish", method="POST")
    if isinstance(result, dict) and "error" in result:
        return json.dumps(result, indent=2)
    return json.dumps({"status": "published", "page_id": page_id}, indent=2)


@mcp.tool()
def unpublish_landing_page(page_id: str) -> str:
    """Take a published landing page offline. The public URL stops serving the page.

    Reversible — re-publish with publish_landing_page. Use delete_landing_page for permanent
    removal instead.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.
    Returns 404 error if page_id is invalid.

    Args:
        page_id: Landing page ID to unpublish. Obtain from list_landing_pages.

    Returns:
        JSON with status ('unpublished') and page_id on success.
    """
    if (guard := _guard_write(action="unpublish landing page", page_id=page_id)):
        return guard
    result = mc_request(f"/landing-pages/{page_id}/actions/unpublish", method="POST")
    if isinstance(result, dict) and "error" in result:
        return json.dumps(result, indent=2)
    return json.dumps({"status": "unpublished", "page_id": page_id}, indent=2)


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


# --- Read/Write Tools: E-commerce Carts ---

@mcp.tool()
def list_store_carts(store_id: str, count: int = 20, offset: int = 0) -> str:
    """List carts for a store, including abandoned ones, with customer and total info.

    Carts in Mailchimp typically represent in-progress purchases synced from a connected
    storefront. Use for abandoned-cart workflows: filter by recent created_at, segment by
    cart total, then trigger a recovery automation. Use get_store_cart for a single cart
    with line items. Use list_store_orders for completed purchases.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.
    Returns 404 if store_id is invalid.

    Args:
        store_id: E-commerce store ID. Obtain from list_ecommerce_stores.
        count: Number of carts to return (1-1000, default 20).
        offset: Pagination offset.

    Returns:
        JSON with store_id, total_items, and carts array. Each cart: id, customer (object
        with id, email_address, opt_in_status), currency_code, order_total, tax_total,
        checkout_url, created_at, updated_at.
    """
    data = mc_request(
        f"/ecommerce/stores/{store_id}/carts",
        params={"count": count, "offset": offset},
    )
    carts = []
    for c in data.get("carts", []):
        carts.append({
            "id": c.get("id"),
            "customer": c.get("customer"),
            "currency_code": c.get("currency_code"),
            "order_total": c.get("order_total"),
            "tax_total": c.get("tax_total"),
            "checkout_url": c.get("checkout_url"),
            "created_at": c.get("created_at"),
            "updated_at": c.get("updated_at"),
        })
    return json.dumps({
        "store_id": store_id,
        "total_items": data.get("total_items"),
        "carts": carts,
    }, indent=2)


@mcp.tool()
def get_store_cart(store_id: str, cart_id: str) -> str:
    """Retrieve a single cart with its full line items, customer, and total breakdown.

    Use to inspect what's in an abandoned cart before triggering a recovery email.
    Use list_store_carts to browse and discover cart_ids.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.
    Returns 404 if store_id or cart_id is invalid.

    Args:
        store_id: E-commerce store ID. Obtain from list_ecommerce_stores.
        cart_id: Cart ID. Obtain from list_store_carts.

    Returns:
        JSON with id, customer, currency_code, order_total, tax_total, checkout_url,
        lines (array of {id, product_id, product_variant_id, quantity, price}),
        created_at, updated_at.
    """
    data = mc_request(f"/ecommerce/stores/{store_id}/carts/{cart_id}")
    if isinstance(data, dict) and "error" in data:
        return json.dumps(data, indent=2)
    return json.dumps({
        "id": data.get("id"),
        "customer": data.get("customer"),
        "currency_code": data.get("currency_code"),
        "order_total": data.get("order_total"),
        "tax_total": data.get("tax_total"),
        "checkout_url": data.get("checkout_url"),
        "lines": data.get("lines"),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
    }, indent=2)


@mcp.tool()
def create_store_cart(store_id: str, cart_id: str, customer_id: str, currency_code: str, order_total: float, lines_json: str, checkout_url: Optional[str] = None, tax_total: Optional[float] = None) -> str:
    """Create a cart in a store with line items and a customer reference. Used to push
    abandoned-cart data from an external system into Mailchimp for recovery workflows.

    cart_id is client-supplied (Mailchimp does not auto-generate it). The customer must
    already exist in the store; create them via Mailchimp's customer endpoints first if
    not. Use update_store_cart to modify after creation.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.

    Args:
        store_id: E-commerce store ID.
        cart_id: Client-supplied unique ID for the new cart (e.g. 'cart_42').
        customer_id: ID of an existing customer in the store.
        currency_code: ISO 4217 currency code (e.g. 'USD', 'EUR').
        order_total: Total order amount (line items + tax + shipping if any).
        lines_json: JSON string with the cart line items array. Example:
            '[{"id": "line_1", "product_id": "p_1", "product_variant_id": "p_1_red",
               "quantity": 2, "price": 19.99}]'
        checkout_url: Optional URL to resume the cart (used in recovery emails).
        tax_total: Optional tax portion of order_total.

    Returns:
        JSON with id, customer, currency_code, order_total, checkout_url, created_at.
    """
    if (guard := _guard_write(action="create cart", store_id=store_id, cart_id=cart_id)):
        return guard
    try:
        lines = json.loads(lines_json)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid lines_json: {e}"}, indent=2)
    body: dict = {
        "id": cart_id,
        "customer": {"id": customer_id},
        "currency_code": currency_code,
        "order_total": order_total,
        "lines": lines,
    }
    if checkout_url:
        body["checkout_url"] = checkout_url
    if tax_total is not None:
        body["tax_total"] = tax_total
    data = mc_request(f"/ecommerce/stores/{store_id}/carts", body=body, method="POST")
    if isinstance(data, dict) and "error" in data:
        return json.dumps(data, indent=2)
    return json.dumps({
        "id": data.get("id"),
        "customer": data.get("customer"),
        "currency_code": data.get("currency_code"),
        "order_total": data.get("order_total"),
        "checkout_url": data.get("checkout_url"),
        "created_at": data.get("created_at"),
    }, indent=2)


@mcp.tool()
def update_store_cart(store_id: str, cart_id: str, order_total: Optional[float] = None, tax_total: Optional[float] = None, checkout_url: Optional[str] = None, currency_code: Optional[str] = None, lines_json: Optional[str] = None) -> str:
    """Update an existing cart's totals, currency, checkout URL, or line items.

    Only provided fields are changed. To replace line items, pass a full lines_json array
    (partial line updates are not supported by this tool — use the Mailchimp UI or REST
    API directly for line-level edits).

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.
    Returns 404 if store_id or cart_id is invalid.

    Args:
        store_id: E-commerce store ID.
        cart_id: Existing cart ID.
        order_total: New order total.
        tax_total: New tax portion.
        checkout_url: New checkout URL.
        currency_code: New ISO 4217 currency code.
        lines_json: JSON string with a replacement line items array.

    Returns:
        JSON with id, order_total, tax_total, checkout_url, currency_code, updated_at.
    """
    if (guard := _guard_write(action="update cart", store_id=store_id, cart_id=cart_id)):
        return guard
    body: dict = {}
    if order_total is not None:
        body["order_total"] = order_total
    if tax_total is not None:
        body["tax_total"] = tax_total
    if checkout_url is not None:
        body["checkout_url"] = checkout_url
    if currency_code is not None:
        body["currency_code"] = currency_code
    if lines_json is not None:
        try:
            body["lines"] = json.loads(lines_json)
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid lines_json: {e}"}, indent=2)
    data = mc_request(f"/ecommerce/stores/{store_id}/carts/{cart_id}", body=body, method="PATCH")
    if isinstance(data, dict) and "error" in data:
        return json.dumps(data, indent=2)
    return json.dumps({
        "id": data.get("id"),
        "order_total": data.get("order_total"),
        "tax_total": data.get("tax_total"),
        "checkout_url": data.get("checkout_url"),
        "currency_code": data.get("currency_code"),
        "updated_at": data.get("updated_at"),
    }, indent=2)


@mcp.tool()
def delete_store_cart(store_id: str, cart_id: str) -> str:
    """Permanently delete a cart from a store. Cannot be undone.

    Use when an external system reports the cart has been completed (converted to order)
    or expired. Does not affect related orders or customer records.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.
    Returns 404 if store_id or cart_id is invalid.

    Args:
        store_id: E-commerce store ID.
        cart_id: Cart ID to delete.

    Returns:
        JSON with status ('deleted'), store_id, cart_id on success.
    """
    if (guard := _guard_write(action="delete cart", store_id=store_id, cart_id=cart_id)):
        return guard
    result = mc_request(f"/ecommerce/stores/{store_id}/carts/{cart_id}", method="DELETE")
    if isinstance(result, dict) and "error" in result:
        return json.dumps(result, indent=2)
    return json.dumps({"status": "deleted", "store_id": store_id, "cart_id": cart_id}, indent=2)


# --- Read/Write Tools: E-commerce Promo Rules ---

@mcp.tool()
def list_promo_rules(store_id: str, count: int = 20, offset: int = 0) -> str:
    """List discount/promo rules configured for a store (fixed amount, percentage, free shipping).

    A promo rule defines the discount mechanic (e.g. '20% off entire order'). Codes that
    customers redeem are attached to rules via list_promo_codes / create_promo_code.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.

    Args:
        store_id: E-commerce store ID. Obtain from list_ecommerce_stores.
        count: Number of rules to return (1-1000, default 20).
        offset: Pagination offset.

    Returns:
        JSON with store_id, total_items, and promo_rules array. Each rule: id, title,
        description, amount, type ('fixed' | 'percentage'), target ('per_item' | 'total' |
        'shipping'), enabled (bool), starts_at, ends_at, created_at, updated_at.
    """
    data = mc_request(
        f"/ecommerce/stores/{store_id}/promo-rules",
        params={"count": count, "offset": offset},
    )
    rules = []
    for r in data.get("promo_rules", []):
        rules.append({
            "id": r.get("id"),
            "title": r.get("title"),
            "description": r.get("description"),
            "amount": r.get("amount"),
            "type": r.get("type"),
            "target": r.get("target"),
            "enabled": r.get("enabled"),
            "starts_at": r.get("starts_at"),
            "ends_at": r.get("ends_at"),
        })
    return json.dumps({
        "store_id": store_id,
        "total_items": data.get("total_items"),
        "promo_rules": rules,
    }, indent=2)


@mcp.tool()
def get_promo_rule(store_id: str, promo_rule_id: str) -> str:
    """Retrieve a single promo rule by ID with its full configuration.

    Use to inspect a rule's current settings before updating, or to confirm a rule exists
    before attaching new codes. Use list_promo_rules to browse and discover IDs.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.
    Returns 404 if store_id or promo_rule_id is invalid.

    Args:
        store_id: E-commerce store ID.
        promo_rule_id: Rule ID to inspect.

    Returns:
        JSON with id, title, description, amount, type, target, enabled, starts_at,
        ends_at, created_at, updated_at.
    """
    data = mc_request(f"/ecommerce/stores/{store_id}/promo-rules/{promo_rule_id}")
    if isinstance(data, dict) and "error" in data:
        return json.dumps(data, indent=2)
    return json.dumps({
        "id": data.get("id"),
        "title": data.get("title"),
        "description": data.get("description"),
        "amount": data.get("amount"),
        "type": data.get("type"),
        "target": data.get("target"),
        "enabled": data.get("enabled"),
        "starts_at": data.get("starts_at"),
        "ends_at": data.get("ends_at"),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
    }, indent=2)


@mcp.tool()
def create_promo_rule(store_id: str, promo_rule_id: str, description: str, amount: float, type: str, target: str, enabled: bool = True, title: Optional[str] = None, starts_at: Optional[str] = None, ends_at: Optional[str] = None) -> str:
    """Create a promo rule (discount mechanic) in a store. Attach codes to it afterwards
    via create_promo_code.

    promo_rule_id is client-supplied. Common patterns: amount=20 + type='percentage' +
    target='total' for '20% off entire order'; amount=5 + type='fixed' + target='shipping'
    for '$5 off shipping'.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.

    Args:
        store_id: E-commerce store ID.
        promo_rule_id: Client-supplied unique ID for the rule.
        description: Internal description shown in Mailchimp UI.
        amount: Discount value. For type='percentage', a value between 0 and 100.
        type: 'fixed' for absolute amount or 'percentage' for percent off.
        target: 'per_item' (each item), 'total' (whole order), or 'shipping' (shipping cost only).
        enabled: Whether the rule is active. Default true.
        title: Optional public title.
        starts_at: Optional ISO 8601 start datetime (rule inactive before this).
        ends_at: Optional ISO 8601 end datetime (rule inactive after this).

    Returns:
        JSON with id, title, description, amount, type, target, enabled, created_at.
    """
    if (guard := _guard_write(action="create promo rule", store_id=store_id, promo_rule_id=promo_rule_id)):
        return guard
    body: dict = {
        "id": promo_rule_id,
        "description": description,
        "amount": amount,
        "type": type,
        "target": target,
        "enabled": enabled,
    }
    if title:
        body["title"] = title
    if starts_at:
        body["starts_at"] = starts_at
    if ends_at:
        body["ends_at"] = ends_at
    data = mc_request(f"/ecommerce/stores/{store_id}/promo-rules", body=body, method="POST")
    if isinstance(data, dict) and "error" in data:
        return json.dumps(data, indent=2)
    return json.dumps({
        "id": data.get("id"),
        "title": data.get("title"),
        "description": data.get("description"),
        "amount": data.get("amount"),
        "type": data.get("type"),
        "target": data.get("target"),
        "enabled": data.get("enabled"),
        "created_at": data.get("created_at"),
    }, indent=2)


@mcp.tool()
def update_promo_rule(store_id: str, promo_rule_id: str, description: Optional[str] = None, amount: Optional[float] = None, type: Optional[str] = None, target: Optional[str] = None, enabled: Optional[bool] = None, title: Optional[str] = None, starts_at: Optional[str] = None, ends_at: Optional[str] = None) -> str:
    """Update an existing promo rule. Only provided fields are changed.

    Useful to toggle a rule on/off (enabled), extend an end date, or adjust the discount
    amount mid-campaign. Use list_promo_rules to discover promo_rule_ids.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.
    Returns 404 if store_id or promo_rule_id is invalid.

    Args:
        store_id: E-commerce store ID.
        promo_rule_id: Existing rule ID.
        description: New internal description.
        amount: New discount amount.
        type: New type ('fixed' or 'percentage').
        target: New target ('per_item', 'total', or 'shipping').
        enabled: Toggle the rule on/off.
        title: New public title.
        starts_at: New start datetime (ISO 8601).
        ends_at: New end datetime (ISO 8601).

    Returns:
        JSON with id, title, description, amount, type, target, enabled, updated_at.
    """
    if (guard := _guard_write(action="update promo rule", store_id=store_id, promo_rule_id=promo_rule_id)):
        return guard
    body: dict = {}
    for key, value in [
        ("description", description),
        ("amount", amount),
        ("type", type),
        ("target", target),
        ("enabled", enabled),
        ("title", title),
        ("starts_at", starts_at),
        ("ends_at", ends_at),
    ]:
        if value is not None:
            body[key] = value
    data = mc_request(
        f"/ecommerce/stores/{store_id}/promo-rules/{promo_rule_id}",
        body=body,
        method="PATCH",
    )
    if isinstance(data, dict) and "error" in data:
        return json.dumps(data, indent=2)
    return json.dumps({
        "id": data.get("id"),
        "title": data.get("title"),
        "description": data.get("description"),
        "amount": data.get("amount"),
        "type": data.get("type"),
        "target": data.get("target"),
        "enabled": data.get("enabled"),
        "updated_at": data.get("updated_at"),
    }, indent=2)


@mcp.tool()
def delete_promo_rule(store_id: str, promo_rule_id: str) -> str:
    """Permanently delete a promo rule and all its associated promo codes. Irreversible.

    Side effect: every promo code attached to this rule is also deleted and stops working
    at checkout. Use update_promo_rule with enabled=false to disable a rule without
    deleting its codes.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.
    Returns 404 if store_id or promo_rule_id is invalid.

    Args:
        store_id: E-commerce store ID.
        promo_rule_id: Rule ID to delete.

    Returns:
        JSON with status ('deleted'), store_id, promo_rule_id on success.
    """
    if (guard := _guard_write(action="delete promo rule", store_id=store_id, promo_rule_id=promo_rule_id)):
        return guard
    result = mc_request(
        f"/ecommerce/stores/{store_id}/promo-rules/{promo_rule_id}",
        method="DELETE",
    )
    if isinstance(result, dict) and "error" in result:
        return json.dumps(result, indent=2)
    return json.dumps({
        "status": "deleted",
        "store_id": store_id,
        "promo_rule_id": promo_rule_id,
    }, indent=2)


# --- Read/Write Tools: E-commerce Promo Codes ---

@mcp.tool()
def list_promo_codes(store_id: str, promo_rule_id: str, count: int = 20, offset: int = 0) -> str:
    """List the redeemable codes attached to a promo rule (e.g. 'SUMMER20', 'VIPONLY').

    Codes are what customers type at checkout. They redeem the discount defined by the
    rule. A single rule can have many codes (e.g. one per customer segment).

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.

    Args:
        store_id: E-commerce store ID.
        promo_rule_id: Rule ID. Obtain from list_promo_rules.
        count: Number of codes to return (1-1000, default 20).
        offset: Pagination offset.

    Returns:
        JSON with store_id, promo_rule_id, total_items, and promo_codes array. Each code:
        id, code (the string customers type), redemption_url, usage_count, enabled,
        created_at, updated_at.
    """
    data = mc_request(
        f"/ecommerce/stores/{store_id}/promo-rules/{promo_rule_id}/promo-codes",
        params={"count": count, "offset": offset},
    )
    codes = []
    for c in data.get("promo_codes", []):
        codes.append({
            "id": c.get("id"),
            "code": c.get("code"),
            "redemption_url": c.get("redemption_url"),
            "usage_count": c.get("usage_count"),
            "enabled": c.get("enabled"),
            "created_at": c.get("created_at"),
            "updated_at": c.get("updated_at"),
        })
    return json.dumps({
        "store_id": store_id,
        "promo_rule_id": promo_rule_id,
        "total_items": data.get("total_items"),
        "promo_codes": codes,
    }, indent=2)


@mcp.tool()
def get_promo_code(store_id: str, promo_rule_id: str, promo_code_id: str) -> str:
    """Retrieve a single promo code by ID with its current settings and usage stats.

    Use to check a code's usage_count before a campaign, or confirm a code is enabled.
    Use list_promo_codes to browse codes for a rule.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.
    Returns 404 if any of store_id, promo_rule_id, or promo_code_id is invalid.

    Args:
        store_id: E-commerce store ID.
        promo_rule_id: Rule ID the code is attached to.
        promo_code_id: Code ID to inspect.

    Returns:
        JSON with id, code, redemption_url, usage_count, enabled, created_at, updated_at.
    """
    data = mc_request(
        f"/ecommerce/stores/{store_id}/promo-rules/{promo_rule_id}/promo-codes/{promo_code_id}"
    )
    if isinstance(data, dict) and "error" in data:
        return json.dumps(data, indent=2)
    return json.dumps({
        "id": data.get("id"),
        "code": data.get("code"),
        "redemption_url": data.get("redemption_url"),
        "usage_count": data.get("usage_count"),
        "enabled": data.get("enabled"),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
    }, indent=2)


@mcp.tool()
def create_promo_code(store_id: str, promo_rule_id: str, promo_code_id: str, code: str, redemption_url: str, enabled: bool = True) -> str:
    """Create a redeemable code under an existing promo rule.

    Customers type the `code` string at checkout to apply the rule's discount. Code matching
    is case-insensitive on the Mailchimp side. Use list_promo_codes to discover existing codes
    before creating duplicates.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.
    Returns 400 if promo_rule_id does not exist; returns 409 if promo_code_id already exists.

    Args:
        store_id: E-commerce store ID.
        promo_rule_id: Rule ID to attach the code to. Obtain from list_promo_rules.
        promo_code_id: Client-supplied unique ID for the code.
        code: The actual code string customers type at checkout (e.g. 'SUMMER20').
        redemption_url: URL where the code can be applied (your checkout page).
        enabled: Whether the code is active. Default true.

    Returns:
        JSON with id, code, redemption_url, usage_count (0 at creation), enabled, created_at.
    """
    if (guard := _guard_write(action="create promo code", store_id=store_id, promo_rule_id=promo_rule_id, code=code)):
        return guard
    body = {
        "id": promo_code_id,
        "code": code,
        "redemption_url": redemption_url,
        "enabled": enabled,
    }
    data = mc_request(
        f"/ecommerce/stores/{store_id}/promo-rules/{promo_rule_id}/promo-codes",
        body=body,
        method="POST",
    )
    if isinstance(data, dict) and "error" in data:
        return json.dumps(data, indent=2)
    return json.dumps({
        "id": data.get("id"),
        "code": data.get("code"),
        "redemption_url": data.get("redemption_url"),
        "usage_count": data.get("usage_count"),
        "enabled": data.get("enabled"),
        "created_at": data.get("created_at"),
    }, indent=2)


@mcp.tool()
def update_promo_code(store_id: str, promo_rule_id: str, promo_code_id: str, code: Optional[str] = None, redemption_url: Optional[str] = None, enabled: Optional[bool] = None) -> str:
    """Update a promo code's string, redemption URL, or enabled state. Cannot move a code
    to a different rule — delete and re-create instead.

    Common use: toggle enabled=false to temporarily disable a code after a campaign ends,
    without deleting the redemption history.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.
    Returns 404 if any of store_id, promo_rule_id, or promo_code_id is invalid.

    Args:
        store_id: E-commerce store ID.
        promo_rule_id: Rule ID the code is attached to.
        promo_code_id: Code ID to update.
        code: New code string (case-insensitive).
        redemption_url: New redemption URL.
        enabled: Toggle the code on/off.

    Returns:
        JSON with id, code, redemption_url, enabled, updated_at.
    """
    if (guard := _guard_write(action="update promo code", store_id=store_id, promo_rule_id=promo_rule_id, promo_code_id=promo_code_id)):
        return guard
    body: dict = {}
    if code is not None:
        body["code"] = code
    if redemption_url is not None:
        body["redemption_url"] = redemption_url
    if enabled is not None:
        body["enabled"] = enabled
    data = mc_request(
        f"/ecommerce/stores/{store_id}/promo-rules/{promo_rule_id}/promo-codes/{promo_code_id}",
        body=body,
        method="PATCH",
    )
    if isinstance(data, dict) and "error" in data:
        return json.dumps(data, indent=2)
    return json.dumps({
        "id": data.get("id"),
        "code": data.get("code"),
        "redemption_url": data.get("redemption_url"),
        "enabled": data.get("enabled"),
        "updated_at": data.get("updated_at"),
    }, indent=2)


@mcp.tool()
def delete_promo_code(store_id: str, promo_rule_id: str, promo_code_id: str) -> str:
    """Permanently delete a promo code. Past redemption history is lost. Irreversible.

    Use update_promo_code with enabled=false to disable a code while preserving its
    redemption stats. Use delete_promo_rule to remove the rule and all its codes at once.

    Authenticated via API key. Max 10 concurrent requests. Respects read-only and dry-run modes.
    Returns 404 if any of store_id, promo_rule_id, or promo_code_id is invalid.

    Args:
        store_id: E-commerce store ID.
        promo_rule_id: Rule ID the code is attached to.
        promo_code_id: Code ID to delete.

    Returns:
        JSON with status ('deleted'), store_id, promo_rule_id, promo_code_id on success.
    """
    if (guard := _guard_write(action="delete promo code", store_id=store_id, promo_rule_id=promo_rule_id, promo_code_id=promo_code_id)):
        return guard
    result = mc_request(
        f"/ecommerce/stores/{store_id}/promo-rules/{promo_rule_id}/promo-codes/{promo_code_id}",
        method="DELETE",
    )
    if isinstance(result, dict) and "error" in result:
        return json.dumps(result, indent=2)
    return json.dumps({
        "status": "deleted",
        "store_id": store_id,
        "promo_rule_id": promo_rule_id,
        "promo_code_id": promo_code_id,
    }, indent=2)


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
def search_automation_campaigns(count: int = 20, offset: int = 0, list_id: Optional[str] = None, status: Optional[str] = None, since_send_time: Optional[str] = None, before_send_time: Optional[str] = None) -> str:
    """List campaigns originated by an automation or a Customer Journey (campaign type='automation').

    Every email Mailchimp sends from a Classic automation or a Customer Journey creates a
    campaign object with type='automation'. This tool filters /campaigns to surface only those,
    so you can answer "what did my automations send recently?" without scanning all campaigns.

    Use this as the most practical workaround for the lack of a public Customer Journeys read
    API: while you can't list the journeys themselves, you can list the campaigns they emit.
    Use list_automations for Classic-only metadata (journey internals aren't exposed). Use
    list_campaigns for the full campaign feed.

    Authenticated via API key. Max 10 concurrent requests. Read-only, safe to retry.

    Args:
        count: Number of campaigns to return (1-1000, default 20).
        offset: Pagination offset. Use when total_items exceeds count.
        list_id: Optional audience ID to restrict to a single audience. Obtain from list_audiences.
        status: Filter by campaign status. Valid values: 'save', 'paused', 'schedule', 'sending',
            'sent'. Omit for all.
        since_send_time: Only return campaigns sent after this ISO 8601 datetime (e.g.
            '2026-04-01T00:00:00Z').
        before_send_time: Only return campaigns sent before this ISO 8601 datetime.

    Returns:
        JSON with total_items and campaigns array. Each campaign: id, status, title, subject_line,
        send_time, emails_sent, list_id, list_name. Useful to compute automation send volume and
        identify which automation/journey produced which email (via title patterns).
    """
    params: dict = {"count": count, "offset": offset, "type": "automation"}
    if list_id:
        params["list_id"] = list_id
    if status:
        params["status"] = status
    if since_send_time:
        params["since_send_time"] = since_send_time
    if before_send_time:
        params["before_send_time"] = before_send_time
    data = mc_request("/campaigns", params=params)
    campaigns = []
    for c in data.get("campaigns", []):
        campaigns.append({
            "id": c.get("id"),
            "status": c.get("status"),
            "title": c.get("settings", {}).get("title"),
            "subject_line": c.get("settings", {}).get("subject_line"),
            "send_time": c.get("send_time"),
            "emails_sent": c.get("emails_sent"),
            "list_id": c.get("recipients", {}).get("list_id"),
            "list_name": c.get("recipients", {}).get("list_name"),
        })
    return json.dumps({"total_items": data.get("total_items"), "campaigns": campaigns}, indent=2)


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
