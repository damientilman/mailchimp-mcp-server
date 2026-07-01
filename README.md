# Mailchimp MCP Server

[![CI](https://github.com/damientilman/mailchimp-mcp-server/actions/workflows/ci.yml/badge.svg)](https://github.com/damientilman/mailchimp-mcp-server/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/mailchimp-mcp.svg)](https://pypi.org/project/mailchimp-mcp/)
[![PyPI downloads](https://img.shields.io/pypi/dm/mailchimp-mcp.svg)](https://pypi.org/project/mailchimp-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io)

The most complete [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server for the [Mailchimp Marketing API](https://mailchimp.com/developer/marketing/): **227 tools** to query and manage your Mailchimp account from any MCP-compatible client. It covers the full campaign, audience, member, segment, automation and reporting surface, complete e-commerce (read and write), landing pages, File Manager, surveys, signup forms and verified domains, plus multi-account support and runtime-security guardrails (read-only, dry-run and audit modes, with per-tool risk metadata).

Uses the [Mailchimp Marketing API](https://mailchimp.com/developer/marketing/api/) via [`requests`](https://pypi.org/project/requests/). Not based on the official [mailchimp-marketing-python](https://github.com/mailchimp/mailchimp-marketing-python) client. I hit too many issues with it so I went with raw HTTP calls instead.

<a href="https://glama.ai/mcp/servers/damientilman/mailchimp-mcp">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/damientilman/mailchimp-mcp/badges/card.svg" alt="Mailchimp MCP server" />
</a>

<a href="https://glama.ai/mcp/servers/damientilman/mailchimp-mcp">
  <img src="https://glama.ai/mcp/servers/damientilman/mailchimp-mcp/badges/score.svg" alt="Mailchimp MCP server score" />
</a>

## Quick start

```bash
uvx mailchimp-mcp   # no install required; just needs MAILCHIMP_API_KEY
```

Add it to your MCP client (Claude Desktop, Cursor, Cline, …):

```json
{
  "mcpServers": {
    "mailchimp": {
      "command": "uvx",
      "args": ["mailchimp-mcp"],
      "env": {
        "MAILCHIMP_API_KEY": "your-key-us8",
        "MAILCHIMP_READ_ONLY": "true"
      }
    }
  }
}
```

Tip: start with `MAILCHIMP_READ_ONLY=true` to explore safely, then flip it off when you are ready to write. See [Configuration](#configuration) for all options.

## Demo

> _Demo recording coming soon._ A short clip showing a live session lands here (contributions welcome).

A typical exchange:

> **You:** Which of my last 5 campaigns had the worst click rate, and what does Mailchimp suggest to fix it?
>
> **Assistant:** *(chains `list_campaigns` → `get_campaign_report` for each → `get_campaign_advice`)* Your "March Digest" had the lowest click rate at 1.2%. Mailchimp suggests tightening the subject line and moving your primary CTA above the fold…

## Features

**Read**
- **Campaigns** - List, search, and inspect campaign details
- **Reports** - Open/click rates, bounces, per-link clicks, domain performance, unsubscribe details
- **Email activity** - Per-recipient open/click tracking, member activity history
- **Audiences** - Browse audiences, members, segments, tags, and growth history
- **Merge fields** - List custom fields for an audience
- **Interest categories & groups** - Browse interest categories and options
- **Webhooks** - List configured webhooks
- **Segments** - Get segment details, conditions, and member lists
- **Automations** - List workflows, inspect emails in a workflow, view queues
- **Templates** - Browse templates and extract HTML content
- **Landing pages** - List and inspect landing pages
- **File Manager** - Browse stored images and files, and folders
- **Surveys** - List and inspect an audience's surveys
- **Signup forms** - Inspect an audience's signup forms
- **E-commerce** - Stores, orders, products, customers (requires e-commerce integration)
- **Campaign folders** - Browse folder organization
- **Batch operations** - Monitor bulk operation status

**Write**
- **Members** - Add, update, unsubscribe, delete, and tag contacts
- **Audiences** - Batch subscribe members, update audience settings
- **Campaigns** - Create drafts, set HTML content, schedule, unschedule, duplicate, delete, send, send test, cancel
- **Segments/Tags** - Create, update, delete, add/remove members, dynamic conditions
- **Merge fields** - Create, update, delete custom fields
- **Interest categories** - Create and delete categories and interests
- **Webhooks** - Create and delete webhooks
- **Templates** - Create, update, and delete email templates
- **File Manager** - Upload (base64) and delete images and files
- **Surveys** - Publish and unpublish audience surveys
- **Signup forms** - Customize header, contents, and styles
- **Automations** - Pause and start automation workflows
- **E-commerce** - Cart lifecycle, promo rules, and promo codes for discount workflows
- **Batch** - Run bulk API operations in a single request

**Runtime security**
- **Risk metadata** - Per-tool read / write / destructive classification via MCP annotations and `describe_tools`
- **Audit log** - Optional structured JSON audit events per dispatch (`MAILCHIMP_AUDIT_LOG`)
- **Argument validation** - Pagination caps and required-ID checks before every request

## Prerequisites

- Python 3.10+
- A [Mailchimp API key](https://mailchimp.com/help/about-api-keys/)

## Installation

### Using `uvx` (recommended)

No installation needed — run directly:

```bash
uvx mailchimp-mcp
```

### Using `pip`

```bash
pip install mailchimp-mcp
```

Then run:

```bash
mailchimp-mcp
```

### From source

```bash
git clone https://github.com/damientilman/mailchimp-mcp-server.git
cd mailchimp-mcp-server
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Configuration

| Variable | Required | Description |
|---|---|---|
| `MAILCHIMP_API_KEY` | Yes | Your Mailchimp API key (format: `<key>-<dc>`, e.g. `abc123-us8`) |
| `MAILCHIMP_READ_ONLY` | No | Set to `true` to disable all write operations (default: `false`) |
| `MAILCHIMP_DRY_RUN` | No | Set to `true` to preview write operations without executing them (default: `false`) |
| `MAILCHIMP_API_KEY_<NAME>` | No | API key for an additional named account (e.g. `MAILCHIMP_API_KEY_MARKETING`). Target it with the `account` argument. See [Multi-account](#multi-account). |
| `MAILCHIMP_READ_ONLY_<NAME>` | No | Read-only mode for a specific named account (default: `false`) |
| `MAILCHIMP_DRY_RUN_<NAME>` | No | Dry-run mode for a specific named account (default: `false`) |
| `MAILCHIMP_AUDIT_LOG` | No | Set to `true` to emit a structured JSON audit event per tool dispatch to stderr (default: `false`). See [Runtime security](#runtime-security). |

The datacenter (`us8`, `us21`, etc.) is automatically extracted from each key.

### Safety modes

**Read-only mode** — When `MAILCHIMP_READ_ONLY=true`, all write tools (create, update, delete, schedule, etc.) are blocked and return an error. Read tools work normally. This is the recommended default for shared or exploratory setups where you only need reporting and analytics.

**Dry-run mode** — When `MAILCHIMP_DRY_RUN=true`, write tools return a preview of the action they *would* perform (tool name, target resource, parameters, and its risk tier) without making any API call. Useful for testing prompts before going live.

### Runtime security

The server is designed for defense-in-depth alongside an external MCP gateway: it owns the *semantics* (which tools are reads, reversible writes, or irreversible) and exposes them as machine-readable signals a gateway can enforce on, rather than making the gateway guess which calls are dangerous.

**Risk metadata** — Every tool is classified as `read`, `write`, or `destructive` (irreversible data loss or an irreversible send). This surfaces two ways:

- **MCP tool annotations** — `readOnlyHint`, `destructiveHint`, and `idempotentHint` travel through the standard `tools/list`, so any compliant client or gateway reads them directly.
- **`describe_tools`** — a read tool returning `{name, risk, read_only, destructive, idempotent}` for every tool plus per-tier counts, for gateways that prefer a tool call.

**Structured audit log** — With `MAILCHIMP_AUDIT_LOG=true`, each dispatch emits one JSON event to stderr with the tool, its risk tier, the `destructive` flag, the target account, the outcome (`executed` / `blocked_read_only` / `dry_run`), and the inspected arguments. Bulky or sensitive values (e.g. base64 `file_data`) are redacted and response bodies are never logged, so the stream is a safe audit sink to tail centrally.

**Argument-contract validation** — All writes funnel through a single `_guard_write` chokepoint, and every request is validated before dispatch (pagination `count` capped to 1–1000, missing path IDs rejected), so malformed calls fail fast and consistently instead of hitting the API.

### Multi-account

By default the server uses the single `MAILCHIMP_API_KEY`, exposed as the `default` account. To manage several Mailchimp accounts from one server, add `MAILCHIMP_API_KEY_<NAME>` variables — the suffix becomes the lowercased account name (e.g. `MAILCHIMP_API_KEY_MARKETING` → `marketing`).

Every tool then accepts an optional `account` argument, e.g. `list_audiences(account="marketing")`. Selection is per call and stateless — there is no "current account" to switch, so a write always names its target. Omitting `account` uses `default`. Call `list_accounts` to see the configured names and their safety-flag state, and each account can carry its own `MAILCHIMP_READ_ONLY_<NAME>` / `MAILCHIMP_DRY_RUN_<NAME>` flags (so a write-protected account and a writable one can live side by side). An unknown `account` returns an error listing the configured names.

Single-key setups are unaffected: with only `MAILCHIMP_API_KEY` set, nothing changes.

```json
{
  "mcpServers": {
    "mailchimp": {
      "command": "uvx",
      "args": ["mailchimp-mcp"],
      "env": {
        "MAILCHIMP_API_KEY": "your-default-key-us8",
        "MAILCHIMP_API_KEY_MARKETING": "another-key-us5",
        "MAILCHIMP_READ_ONLY_MARKETING": "true"
      }
    }
  }
}
```

### MCP client configuration

Most MCP clients accept a JSON configuration block describing how to launch the server.
Configure yours to invoke `uvx mailchimp-mcp` (or `mailchimp-mcp` if installed via pip)
with `MAILCHIMP_API_KEY` exported in the environment.

<details>
<summary>Using uvx (recommended)</summary>

```json
{
  "mcpServers": {
    "mailchimp": {
      "command": "uvx",
      "args": ["mailchimp-mcp"],
      "env": {
        "MAILCHIMP_API_KEY": "your-api-key-here"
      }
    }
  }
}
```
</details>

<details>
<summary>Using pip install</summary>

```json
{
  "mcpServers": {
    "mailchimp": {
      "command": "mailchimp-mcp",
      "env": {
        "MAILCHIMP_API_KEY": "your-api-key-here"
      }
    }
  }
}
```
</details>

<details>
<summary>Read-only mode (recommended for exploration)</summary>

```json
{
  "mcpServers": {
    "mailchimp": {
      "command": "uvx",
      "args": ["mailchimp-mcp"],
      "env": {
        "MAILCHIMP_API_KEY": "your-api-key-here",
        "MAILCHIMP_READ_ONLY": "true"
      }
    }
  }
}
```
</details>

### CLI-based clients

If your MCP client provides a CLI to register servers, the equivalent invocation is:

```bash
mcp-cli add mailchimp \
  -e MAILCHIMP_API_KEY=your-api-key-here \
  -- uvx mailchimp-mcp
```

Replace `mcp-cli` with your client's binary name. For read-only mode, add
`-e MAILCHIMP_READ_ONLY=true` to the command.

## Available Tools

### Account

| Tool | Description |
|---|---|
| `get_account_info` | Get account name, email, and subscriber count |
| `list_accounts` | List configured accounts and their read-only / dry-run state (for multi-account setups) |
| `describe_tools` | List every tool with its risk tier (read / write / destructive) for policy enforcement |

### Campaigns (read)

| Tool | Description |
|---|---|
| `list_campaigns` | List campaigns with optional filters (status, date) |
| `get_campaign_details` | Get full details of a specific campaign |
| `list_campaign_folders` | List campaign folders |

### Campaign Reports

| Tool | Description |
|---|---|
| `get_campaign_report` | Get performance metrics (opens, clicks, bounces) |
| `get_campaign_click_details` | Get per-link click data for a campaign |
| `get_email_activity` | Per-recipient activity (opens, clicks, bounces) |
| `get_open_details` | Who opened, when, how many times |
| `get_campaign_recipients` | List of recipients with delivery status |
| `get_campaign_unsubscribes` | Who unsubscribed after a campaign |
| `get_domain_performance` | Performance by email domain (gmail, outlook, etc.) |
| `get_ecommerce_product_activity` | Revenue per product for a campaign |
| `get_campaign_sub_reports` | Sub-reports (A/B tests, RSS, etc.) |
| `get_campaign_advice` | Mailchimp's automated post-send feedback on a campaign |
| `get_campaign_locations` | Geographic open data (country, region) |
| `get_eepurl_activity` | Social sharing stats (Twitter, Facebook, referrers) |

### Campaigns (write)

| Tool | Description |
|---|---|
| `create_campaign` | Create a new campaign draft (regular or A/B `variate`, with optional segment targeting) |
| `update_campaign` | Update settings or segment targeting of a campaign |
| `set_campaign_content` | Set the HTML content of a campaign draft |
| `schedule_campaign` | Schedule a campaign for a specific date/time |
| `unschedule_campaign` | Unschedule a campaign (back to draft) |
| `replicate_campaign` | Duplicate an existing campaign |
| `delete_campaign` | Delete an unsent campaign |
| `send_campaign` | Send a campaign immediately |
| `send_test_email` | Send a test email for a campaign |
| `cancel_send` | Cancel a campaign that is currently sending |

### Audiences (read)

| Tool | Description |
|---|---|
| `list_audiences` | List all audiences with stats |
| `get_audience_details` | Get detailed info for a specific audience |
| `list_audience_members` | List members with optional status filter |
| `search_members` | Search members by email or name |
| `get_audience_growth_history` | Monthly growth data (subscribes, unsubscribes) |

### Members (read)

| Tool | Description |
|---|---|
| `get_member_activity` | Activity history of a specific contact |
| `get_member_tags` | All tags assigned to a contact |
| `get_member_events` | Custom events for a contact |
| `list_member_notes` | List CRM-style internal notes attached to a contact |

### Members (write)

| Tool | Description |
|---|---|
| `add_member` | Add a new contact to an audience |
| `update_member` | Update a contact's name or status |
| `unsubscribe_member` | Unsubscribe a contact |
| `delete_member` | Permanently delete a contact |
| `tag_member` | Add or remove tags from a contact |
| `add_member_note` | Attach a CRM-style internal note to a contact |
| `update_member_note` | Update the text of an existing member note |
| `delete_member_note` | Delete a member note |

### Audiences (write)

| Tool | Description |
|---|---|
| `batch_subscribe` | Batch add/update multiple members in an audience |
| `update_audience` | Update audience settings (name, defaults, permission reminder) |
| `create_audience` | Create a new audience with contact info and campaign defaults |
| `delete_audience` | Permanently delete an audience and all its data |

### Segments & Tags

| Tool | Description |
|---|---|
| `list_segments` | List segments and tags for an audience |
| `get_segment` | Get segment details including conditions |
| `list_segment_members` | List members in a segment |
| `create_segment` | Create a new segment or tag (static or dynamic with conditions) |
| `update_segment` | Update a segment's name or conditions |
| `delete_segment` | Delete a segment or tag |
| `add_members_to_segment` | Add contacts to a segment/tag |
| `remove_members_from_segment` | Remove contacts from a segment/tag |

### Merge Fields

| Tool | Description |
|---|---|
| `list_merge_fields` | List custom fields for an audience |
| `create_merge_field` | Create a new custom field (text, number, dropdown, etc.) |
| `update_merge_field` | Update a custom field |
| `delete_merge_field` | Delete a custom field |

### Interest Categories & Groups

| Tool | Description |
|---|---|
| `list_interest_categories` | List interest categories for an audience |
| `create_interest_category` | Create a new interest category |
| `list_interests` | List interests within a category |
| `create_interest` | Create a new interest option |
| `delete_interest_category` | Delete an interest category |
| `delete_interest` | Delete an interest option |

### Webhooks

| Tool | Description |
|---|---|
| `list_webhooks` | List webhooks for an audience |
| `create_webhook` | Create a new webhook |
| `delete_webhook` | Delete a webhook |

### Automations & Customer Journeys

| Tool | Description |
|---|---|
| `list_automations` | List Classic Automation workflows (Customer Journeys are not exposed by Mailchimp's API) |
| `get_automation_emails` | List emails in a Classic workflow |
| `get_automation_email_queue` | View the send queue for an automation email |
| `pause_automation` | Pause all emails in a Classic workflow |
| `start_automation` | Start/resume all emails in a Classic workflow |
| `trigger_customer_journey` | Enroll a contact into a Customer Journey step (the only journey write Mailchimp exposes) |
| `search_automation_campaigns` | List campaigns emitted by either Classic Automations or Customer Journeys |
| `get_member_journey_events` | Filter a member's activity feed to automation/journey-related events |
| `get_automation_summary` | Combined overview: Classic workflows by status + recent automation send volume |

> Mailchimp does not expose a public read API for Customer Journeys (only the trigger endpoint above). The `search_automation_campaigns`, `get_member_journey_events` and `get_automation_summary` tools provide the recommended workarounds — they surface every campaign emitted by automations or journeys, even though the journey graph itself remains private.

### Templates

| Tool | Description |
|---|---|
| `list_templates` | List available email templates |
| `get_template` | Get template metadata (name, type, dates, thumbnail) |
| `get_template_default_content` | Get template HTML content |
| `create_template` | Create a new email template |
| `update_template` | Update template name or HTML |
| `delete_template` | Delete a user-created template |

### Landing Pages

| Tool | Description |
|---|---|
| `list_landing_pages` | List all landing pages |
| `get_landing_page` | Get details of a landing page |
| `create_landing_page` | Create a new landing page from a template |
| `update_landing_page` | Update settings of an existing landing page |
| `delete_landing_page` | Permanently delete a landing page |
| `publish_landing_page` | Publish a landing page to its public URL |
| `unpublish_landing_page` | Take a published landing page offline |

### File Manager

| Tool | Description |
|---|---|
| `list_files` | List images and files stored in the File Manager |
| `get_file` | Get a single file's metadata and hosted URL |
| `upload_file` | Upload a new image or file (base64-encoded) |
| `delete_file` | Permanently delete a file |
| `list_file_folders` | List File Manager folders |

### Surveys

| Tool | Description |
|---|---|
| `list_surveys` | List an audience's surveys with status and public URL |
| `get_survey` | Get a single survey's full details |
| `publish_survey` | Publish a survey to its public URL |
| `unpublish_survey` | Take a published survey offline |

### Signup Forms

| Tool | Description |
|---|---|
| `list_signup_forms` | Get the signup forms configured for an audience |
| `customize_signup_form` | Customize a signup form's header, contents, and styles |

### E-commerce

| Tool | Description |
|---|---|
| `list_ecommerce_stores` | List connected e-commerce stores |
| `list_store_orders` | List orders from a store |
| `list_store_products` | List products from a store |
| `list_store_customers` | List customers from a store |

### E-commerce Carts

| Tool | Description |
|---|---|
| `list_store_carts` | List carts (including abandoned) for a store |
| `get_store_cart` | Get a single cart with full line items |
| `create_store_cart` | Push a cart (e.g. an abandoned cart from an external system) |
| `update_store_cart` | Update a cart's totals, currency, checkout URL, or line items |
| `delete_store_cart` | Permanently delete a cart |

### E-commerce Promo Rules & Codes

| Tool | Description |
|---|---|
| `list_promo_rules` | List discount rules for a store |
| `get_promo_rule` | Get a single promo rule's configuration |
| `create_promo_rule` | Create a discount rule (fixed amount, percentage, free shipping) |
| `update_promo_rule` | Update a rule's amount, target, dates, or enabled state |
| `delete_promo_rule` | Permanently delete a rule and all its codes |
| `list_promo_codes` | List redeemable codes attached to a rule |
| `get_promo_code` | Get a single promo code with usage stats |
| `create_promo_code` | Create a redeemable code (e.g. 'SUMMER20') under a rule |
| `update_promo_code` | Update a code's string, redemption URL, or enabled state |
| `delete_promo_code` | Permanently delete a promo code |

### Batch Operations

| Tool | Description |
|---|---|
| `create_batch` | Run multiple API operations in bulk |
| `get_batch_status` | Check status of a batch operation |
| `list_batches` | List recent batch operations |
| `list_batch_webhooks` | List batch-completion webhooks |
| `get_batch_webhook` | Get a single batch webhook |
| `create_batch_webhook` | Create a batch-completion webhook |
| `update_batch_webhook` | Update a batch webhook's URL |
| `delete_batch_webhook` | Delete a batch webhook |

### Verified Domains

| Tool | Description |
|---|---|
| `list_verified_domains` | List sending domains and their verification state |
| `get_verified_domain` | Get a single sending domain's record |
| `create_verified_domain` | Start verification for a sending domain |
| `verify_verified_domain` | Complete verification with the emailed code |
| `delete_verified_domain` | Remove a verified sending domain |

### Connected Sites & Account

| Tool | Description |
|---|---|
| `list_connected_sites` | List connected sites for tracking and pop-ups |
| `get_connected_site` | Get a single connected site with its script |
| `create_connected_site` | Connect a website and generate its script |
| `delete_connected_site` | Remove a connected site |
| `verify_connected_site_script` | Verify the tracking script is installed |
| `list_authorized_apps` | List OAuth-authorized applications |
| `get_authorized_app` | Get a single authorized application |
| `get_chimp_chatter` | Read the account activity feed |
| `list_account_exports` | List account data export jobs |
| `get_account_export` | Get an export job's status and download URL |
| `create_account_export` | Start an account data export |

### Folders

| Tool | Description |
|---|---|
| `create_campaign_folder` | Create a campaign folder |
| `get_campaign_folder` | Get a single campaign folder |
| `update_campaign_folder` | Rename a campaign folder |
| `delete_campaign_folder` | Delete a campaign folder |
| `list_template_folders` | List template folders |
| `get_template_folder` | Get a single template folder |
| `create_template_folder` | Create a template folder |
| `update_template_folder` | Rename a template folder |
| `delete_template_folder` | Delete a template folder |

### Campaign Extras (checklist, collaboration, RSS)

| Tool | Description |
|---|---|
| `get_campaign_send_checklist` | Pre-send readiness checklist |
| `list_campaign_feedback` | List team collaboration comments |
| `get_campaign_feedback` | Get a single comment |
| `create_campaign_feedback` | Add a collaboration comment |
| `update_campaign_feedback` | Edit a comment |
| `delete_campaign_feedback` | Delete a comment |
| `pause_rss_campaign` | Pause an RSS-driven campaign |
| `resume_rss_campaign` | Resume an RSS-driven campaign |

### Audience Insights & Deliverability

| Tool | Description |
|---|---|
| `get_audience_activity` | Recent daily activity for an audience |
| `get_audience_top_locations` | Top countries of an audience |
| `get_audience_clients` | Top email clients used by an audience |
| `list_audience_abuse_reports` | Spam complaints for an audience |
| `get_audience_abuse_report` | A single audience abuse report |

### Members (compliance & advanced)

| Tool | Description |
|---|---|
| `upsert_member` | Add-or-update a member idempotently (PUT) |
| `delete_member_permanent` | GDPR permanent erasure of a member |
| `get_member_goals` | A member's recent tracked goal events |
| `add_member_event` | Record a custom event on a member |

### Automation Emails (single-email control)

| Tool | Description |
|---|---|
| `get_automation_email` | Get one email in a classic automation |
| `pause_automation_email` | Pause a single automation email |
| `start_automation_email` | Start a single automation email |
| `add_automation_queue_subscriber` | Enqueue a subscriber for an automation email |
| `get_automation_queue_subscriber` | Get a subscriber's queue status |
| `list_automation_removed_subscribers` | List subscribers removed from a workflow |
| `remove_automation_subscriber` | Remove a subscriber from a workflow |
| `get_automation_removed_subscriber` | Get a single removed subscriber |

### Reporting (extras)

| Tool | Description |
|---|---|
| `get_campaign_sent_to` | Per-recipient delivery status for a campaign |
| `get_campaign_abuse_reports` | Spam complaints for a campaign |
| `get_campaign_abuse_report` | A single campaign abuse report |
| `list_landing_page_reports` | Reports across all landing pages |
| `get_landing_page_report` | Report for a single landing page |
| `list_survey_reports` | Reports across all surveys |
| `get_survey_report` | Report for a single survey |
| `get_survey_responses` | List a survey's responses |
| `get_survey_response` | Get a single survey response |
| `get_survey_questions_report` | Per-question survey report |
| `get_survey_question_answers` | Answers for a single survey question |

### E-commerce (write)

| Tool | Description |
|---|---|
| `create_store` / `get_store` / `update_store` / `delete_store` | Store lifecycle |
| `get_store_product` / `create_store_product` / `update_store_product` / `delete_store_product` | Product lifecycle |
| `list_store_product_variants` / `get_store_product_variant` / `create_store_product_variant` / `update_store_product_variant` / `delete_store_product_variant` | Product variants |
| `list_store_product_images` / `get_store_product_image` / `create_store_product_image` / `update_store_product_image` / `delete_store_product_image` | Product images |
| `get_store_order` / `create_store_order` / `update_store_order` / `delete_store_order` | Order lifecycle |
| `list_store_order_lines` / `get_store_order_line` / `create_store_order_line` / `update_store_order_line` / `delete_store_order_line` | Order line items |
| `get_store_customer` / `create_store_customer` / `update_store_customer` / `delete_store_customer` | Customer lifecycle |
| `list_account_orders` | List orders across every store |

## Example Prompts

Once connected, you can ask your MCP client to perform requests like:

- *"Show me all my sent campaigns from the last 3 months"*
- *"What was the open rate and click rate for my last newsletter?"*
- *"How many subscribers did I gain this year?"*
- *"Which links got the most clicks in campaign X?"*
- *"Search for subscriber john@example.com"*
- *"Add tag 'VIP' to all members who opened my last campaign"*
- *"Create a draft campaign for my main audience with subject 'March Update'"*
- *"Create a campaign targeting only my VIP segment"*
- *"Send a test email of my draft campaign to test@example.com"*
- *"List all merge fields for my main audience"*
- *"Create a dropdown merge field called 'Industry' with options Tech, Finance, Healthcare"*
- *"Create a dynamic segment of members where FNAME is John"*
- *"Batch subscribe 50 members from this CSV data"*
- *"Set up a webhook to notify my app when new subscribers join"*
- *"Unsubscribe user@example.com from my list"*
- *"Show me the domain performance breakdown for my last campaign"*
- *"Where in the world did people open my newsletter? Show me the geographic breakdown."*
- *"Create an A/B test campaign with two subject lines and pick the winner by opens after 24 hours"*
- *"What advice does Mailchimp have for improving my last campaign?"*
- *"Pause my welcome automation"*
- *"List all orders from my Shopify store this month"*

### Workflow recipes

Multi-step requests that chain tools end to end:

- **Weekly performance review** — *"Summarise my last week: list campaigns sent since Monday, pull each report, and rank them by click rate with one takeaway each."* Chains `search_campaigns` → `get_campaign_report` → `get_campaign_advice`.
- **Deliverability audit** — *"Check my sending health: are my domains verified, any spam complaints on recent campaigns, and how did the last one perform by recipient domain?"* Chains `list_verified_domains` → `get_campaign_abuse_reports` → `get_domain_performance`.
- **Re-engagement** — *"Find everyone who didn't open my last newsletter and resend it with a new subject line."* Chains `get_campaign_report` → `resend_to_non_openers`.
- **Safe send** — *"Dry-run a campaign to my VIP segment, show me the send checklist, then send it once I confirm."* With `MAILCHIMP_DRY_RUN=true`, previews via `create_campaign` → `get_campaign_send_checklist` → `send_campaign`.
- **Agencies (multi-account)** — *"For both the `acme` and `globex` accounts, list this month's top campaign by open rate."* Passes `account="acme"` / `account="globex"` per call. See [Multi-account](#multi-account).

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup,
test instructions, and pull request guidelines.

## Security

If you find a security vulnerability, please follow the responsible disclosure process
described in [SECURITY.md](SECURITY.md).

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the full release history.

## Author

Built by [Damien Tilman](https://www.tilman.marketing) — damien@tilman.marketing

## License

MIT — see [LICENSE](LICENSE) for details.