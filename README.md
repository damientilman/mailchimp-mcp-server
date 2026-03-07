# Mailchimp MCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io)

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server for the [Mailchimp Marketing API](https://mailchimp.com/developer/marketing/). 53 tools to query and manage your Mailchimp account directly from Claude.

<a href="https://glama.ai/mcp/servers/@damientilman/mailchimp-mcp">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/@damientilman/mailchimp-mcp/badge" alt="Mailchimp MCP server" />
</a>

## Features

**Read**
- **Campaigns** - List, search, and inspect campaign details
- **Reports** - Open/click rates, bounces, per-link clicks, domain performance, unsubscribe details
- **Email activity** - Per-recipient open/click tracking, member activity history
- **Audiences** - Browse audiences, members, segments, tags, and growth history
- **Automations** - List workflows, inspect emails in a workflow, view queues
- **Templates** - Browse available email templates
- **Landing pages** - List and inspect landing pages
- **E-commerce** - Stores, orders, products, customers (requires e-commerce integration)
- **Campaign folders** - Browse folder organization
- **Batch operations** - Monitor bulk operation status

**Write**
- **Members** - Add, update, unsubscribe, delete, and tag contacts
- **Campaigns** - Create drafts, set HTML content, schedule, unschedule, duplicate, delete
- **Segments/Tags** - Create, delete, add/remove members
- **Automations** - Pause and start automation workflows
- **Batch** - Run bulk API operations in a single request

## Prerequisites

- Python 3.10+
- A [Mailchimp API key](https://mailchimp.com/help/about-api-keys/)

## Installation

### Using `uvx` (recommended)

No installation needed — run directly:

```bash
uvx mailchimp-mcp-server
```

### Using `pip`

```bash
pip install mailchimp-mcp-server
```

Then run:

```bash
mailchimp-mcp-server
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

The server requires one environment variable:

| Variable | Description |
|---|---|
| `MAILCHIMP_API_KEY` | Your Mailchimp API key (format: `<key>-<dc>`, e.g. `abc123-us8`) |

The datacenter (`us8`, `us21`, etc.) is automatically extracted from the key.

### Claude Desktop

Add this to your `claude_desktop_config.json`:

<details>
<summary>Using uvx (recommended)</summary>

```json
{
  "mcpServers": {
    "mailchimp": {
      "command": "uvx",
      "args": ["mailchimp-mcp-server"],
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
      "command": "mailchimp-mcp-server",
      "env": {
        "MAILCHIMP_API_KEY": "your-api-key-here"
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
  -- uvx mailchimp-mcp-server
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
| `create_campaign` | Create a new campaign draft |
| `update_campaign` | Update subject line, title, preview text, etc. |
| `set_campaign_content` | Set the HTML content of a campaign draft |
| `schedule_campaign` | Schedule a campaign for a specific date/time |
| `unschedule_campaign` | Unschedule a campaign (back to draft) |
| `replicate_campaign` | Duplicate an existing campaign |
| `delete_campaign` | Delete an unsent campaign |

### Audiences (read)

| Tool | Description |
|---|---|
| `list_audiences` | List all audiences with stats |
| `get_audience_details` | Get detailed info for a specific audience |
| `list_audience_members` | List members with optional status filter |
| `search_members` | Search members by email or name |
| `get_audience_growth_history` | Monthly growth data (subscribes, unsubscribes) |
| `list_segments` | List segments and tags for an audience |

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

### Segments & Tags (write)

| Tool | Description |
|---|---|
| `create_segment` | Create a new segment or tag |
| `delete_segment` | Delete a segment or tag |
| `add_members_to_segment` | Add contacts to a segment/tag |
| `remove_members_from_segment` | Remove contacts from a segment/tag |

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
- *"Unsubscribe user@example.com from my list"*
- *"Show me the domain performance breakdown for my last campaign"*
- *"Pause my welcome automation"*
- *"List all orders from my Shopify store this month"*

## Author

Built by [Damien Tilman](https://www.tilman.marketing) — damien@tilman.marketing

## License

MIT — see [LICENSE](LICENSE) for details.