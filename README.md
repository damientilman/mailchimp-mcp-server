# Mailchimp MCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io)

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that provides read-only access to the [Mailchimp Marketing API](https://mailchimp.com/developer/marketing/). Query your campaigns, audiences, reports, automations, and more directly from Claude.

## Features

- **Campaigns** — List, search, and inspect campaign details
- **Reports** — Get open rates, click rates, bounces, and per-link click data
- **Audiences** — Browse audiences, members, segments, and tags
- **Growth history** — Monthly subscriber growth for any audience
- **Automations** — List automated email workflows
- **Templates** — Browse available email templates
- **Search** — Find members by email or name across all audiences

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

### Campaigns

| Tool | Description |
|---|---|
| `list_campaigns` | List campaigns with optional filters (status, date) |
| `get_campaign_details` | Get full details of a specific campaign |
| `get_campaign_report` | Get performance metrics (opens, clicks, bounces) |
| `get_campaign_click_details` | Get per-link click data for a campaign |

### Audiences

| Tool | Description |
|---|---|
| `list_audiences` | List all audiences with stats |
| `get_audience_details` | Get detailed info for a specific audience |
| `list_audience_members` | List members with optional status filter |
| `search_members` | Search members by email or name |
| `get_audience_growth_history` | Monthly growth data (subscribes, unsubscribes) |
| `list_segments` | List segments and tags for an audience |

### Automations & Templates

| Tool | Description |
|---|---|
| `list_automations` | List automated email workflows |
| `list_templates` | List available email templates |

## Example Prompts

Once connected, you can ask Claude things like:

- *"Show me all my sent campaigns from the last 3 months"*
- *"What was the open rate and click rate for my last newsletter?"*
- *"How many subscribers did I gain this year?"*
- *"Which links got the most clicks in campaign X?"*
- *"Search for subscriber john@example.com"*

## Author

Built by [Damien Tilman](https://www.tilman.marketing) — damien@tilman.marketing

## License

MIT — see [LICENSE](LICENSE) for details.
