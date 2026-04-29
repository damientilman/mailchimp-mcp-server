# Mailchimp MCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io)

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server for the [Mailchimp Marketing API](https://mailchimp.com/developer/marketing/). 74 tools to query and manage your Mailchimp account directly from Claude.

Uses the [Mailchimp Marketing API](https://mailchimp.com/developer/marketing/api/) via [`requests`](https://pypi.org/project/requests/). Not based on the official [mailchimp-marketing-python](https://github.com/mailchimp/mailchimp-marketing-python) client. I hit too many issues with it so I went with raw HTTP calls instead.

<a href="https://glama.ai/mcp/servers/@damientilman/mailchimp-mcp">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/@damientilman/mailchimp-mcp/badge" alt="Mailchimp MCP server" />
</a>

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
- **Templates** - Browse available email templates
- **Landing pages** - List and inspect landing pages
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
- **Automations** - Pause and start automation workflows
- **Batch** - Run bulk API operations in a single request

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

The datacenter (`us8`, `us21`, etc.) is automatically extracted from the key.

### Safety modes

**Read-only mode** — When `MAILCHIMP_READ_ONLY=true`, all write tools (create, update, delete, schedule, etc.) are blocked and return an error. Read tools work normally. This is the recommended default for shared or exploratory setups where you only need reporting and analytics.

**Dry-run mode** — When `MAILCHIMP_DRY_RUN=true`, write tools return a preview of the action they *would* perform (tool name, target resource, parameters) without making any API call. Useful for testing prompts before going live.

### Claude Desktop

Add this to your `claude_desktop_config.json`:

> **Windows (Microsoft Store)**: If Claude Desktop was installed via the Microsoft Store, the config file is located at `C:\Users\<user>\AppData\Local\Packages\Claude_<id>\LocalCache\Roaming\Claude\claude_desktop_config.json` instead of the usual `%APPDATA%\Claude\` path.

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

### Claude Code

```bash
claude mcp add mailchimp \
  -s user \
  -e MAILCHIMP_API_KEY=your-api-key-here \
  -- uvx mailchimp-mcp
```

For read-only mode:

```bash
claude mcp add mailchimp \
  -s user \
  -e MAILCHIMP_API_KEY=your-api-key-here \
  -e MAILCHIMP_READ_ONLY=true \
  -- uvx mailchimp-mcp
```

## Available Tools

### Account

| Tool | Description |
|---|---|
| `get_account_info` | Get account name, email, and subscriber count |

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

### Campaigns (write)

| Tool | Description |
|---|---|
| `create_campaign` | Create a new campaign draft (with optional segment targeting) |
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

### Members (write)

| Tool | Description |
|---|---|
| `add_member` | Add a new contact to an audience |
| `update_member` | Update a contact's name or status |
| `unsubscribe_member` | Unsubscribe a contact |
| `delete_member` | Permanently delete a contact |
| `tag_member` | Add or remove tags from a contact |

### Audiences (write)

| Tool | Description |
|---|---|
| `batch_subscribe` | Batch add/update multiple members in an audience |
| `update_audience` | Update audience settings (name, defaults, permission reminder) |

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

### Automations

| Tool | Description |
|---|---|
| `list_automations` | List automated email workflows |
| `get_automation_emails` | List emails in a workflow |
| `get_automation_email_queue` | View the send queue for an automation email |
| `pause_automation` | Pause all emails in a workflow |
| `start_automation` | Start/resume all emails in a workflow |

### Templates

| Tool | Description |
|---|---|
| `list_templates` | List available email templates |

### Landing Pages

| Tool | Description |
|---|---|
| `list_landing_pages` | List all landing pages |
| `get_landing_page` | Get details of a landing page |

### E-commerce

| Tool | Description |
|---|---|
| `list_ecommerce_stores` | List connected e-commerce stores |
| `list_store_orders` | List orders from a store |
| `list_store_products` | List products from a store |
| `list_store_customers` | List customers from a store |

### Batch Operations

| Tool | Description |
|---|---|
| `create_batch` | Run multiple API operations in bulk |
| `get_batch_status` | Check status of a batch operation |
| `list_batches` | List recent batch operations |

## Example Prompts

Once connected, you can ask Claude things like:

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
- *"Pause my welcome automation"*
- *"List all orders from my Shopify store this month"*

## Author

Built by [Damien Tilman](https://www.tilman.marketing) — damien@tilman.marketing

## License

MIT — see [LICENSE](LICENSE) for details.