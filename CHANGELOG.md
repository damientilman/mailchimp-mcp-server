# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.6.0] - 2026-05

### Added
- **`search_automation_campaigns`** — list campaigns where `type='automation'`, with
  optional filters by audience, status, and date range. The most practical
  workaround for the lack of a public Customer Journeys read API: while the journey
  graph itself stays private, every email a journey emits creates a campaign
  surface-able through this tool.
- **`get_member_journey_events`** — retrieve a member's activity feed filtered
  client-side to actions whose type contains `"automation"` or `"journey"`. Useful
  to answer "what automation/journey emails has this contact received?".
- **`get_automation_summary`** — combined overview tool: counts Classic Automation
  workflows by status, plus aggregate send volume from automation-type campaigns
  in a configurable lookback window (default 30 days). Recommended starting point
  for account audits.
- 4 new tests covering filter wiring, server-side action filtering, and the
  multi-call aggregation in the summary tool.

### Changed
- Tool count bumped to **115** (was 112) — README, `glama.json`, and
  `pyproject.toml` descriptions updated accordingly.
- `list_automations` docstring now states clearly that Customer Journeys are NOT
  returned (Mailchimp does not expose a public read endpoint for them), and points
  at the new workaround tools.
- README's Automations section renamed to "Automations & Customer Journeys" and
  expanded to document the journey coverage gap and the recommended workarounds.

## [0.5.0] - 2026-05

### Added
- **E-commerce carts CRUD**: `list_store_carts`, `get_store_cart`,
  `create_store_cart`, `update_store_cart`, `delete_store_cart` — full lifecycle
  for cart objects, with line items passed as JSON for create/update. Designed
  to support abandoned-cart recovery workflows where the cart originates in an
  external system.
- **E-commerce promo rules CRUD**: `list_promo_rules`, `get_promo_rule`,
  `create_promo_rule`, `update_promo_rule`, `delete_promo_rule` — define
  discount mechanics (fixed amount, percentage, or free shipping; targeting
  per-item, total, or shipping cost).
- **E-commerce promo codes CRUD**: `list_promo_codes`, `get_promo_code`,
  `create_promo_code`, `update_promo_code`, `delete_promo_code` — manage the
  redeemable codes (e.g. `SUMMER20`) attached to a promo rule.
- 16 new smoke tests covering the additions, including JSON parsing for cart
  line items and the partial-PATCH paths on every update tool.
- Closes #19 (partial — the high-value subset specifically called out in the
  issue is implemented; full CRUD for stores, customers, orders, products, and
  variants is intentionally deferred because in practice that data is synced
  from external storefronts).

### Changed
- Tool count bumped to **112** (was 97) — README, `glama.json`, and
  `pyproject.toml` descriptions updated accordingly.

## [0.4.0] - 2026-05

### Added
- **Landing page lifecycle**: `create_landing_page`, `update_landing_page`,
  `delete_landing_page`, `publish_landing_page`, `unpublish_landing_page` — full
  CRUD plus publish/unpublish actions on top of the existing read tools
  (closes #11).
- **Member notes (CRM-style)**: `list_member_notes`, `add_member_note`,
  `update_member_note`, `delete_member_note` for internal annotations on
  contacts that are never sent to them (closes #8).
- **`get_template`**: metadata-only template lookup (name, type, dates,
  thumbnail, share URL) complementing the existing `get_template_default_content`
  for HTML retrieval (closes #10).
- Smoke tests for the ten new tools, including subscriber-hash routing for
  member notes and the JSON-shape contracts for landing page actions.

### Changed
- Tool count bumped to **97** (was 87) — README, `glama.json`, and
  `pyproject.toml` descriptions updated accordingly.

## [0.3.0] - 2026-05

### Added
- **A/B (variate) campaigns**: `create_campaign` now accepts `campaign_type='variate'`
  and a `variate_settings_json` payload describing subject lines / from names / send
  times / contents to test, the winner criterion, the test sample size, and the
  wait time before declaring a winner.
- **Audience lifecycle**: new `create_audience` and `delete_audience` tools for full
  list creation and removal (closes #9).
- **Advanced reports**: new `get_campaign_advice`, `get_campaign_locations`, and
  `get_eepurl_activity` tools for post-send feedback, geographic open breakdowns,
  and social sharing stats (closes #13).
- Test coverage extended to all five new tools and to the variate campaign branch
  of `create_campaign`.

### Changed
- Tool count bumped to **87** (was 82) — README, `pyproject.toml`, and `glama.json`
  descriptions updated accordingly.

## [0.2.1] - 2026-05

### Added
- Test suite covering safety modes, request helpers, and a smoke test per tool family.
- `CONTRIBUTING.md` with development setup and contribution guidelines.
- `SECURITY.md` with vulnerability reporting policy.
- CI improvements: linting (ruff), test execution, and coverage reporting.
- Multi-stage Dockerfile running as a non-root user.

### Changed
- Documentation rewritten to be MCP-client agnostic; install sections now show
  generic JSON/CLI examples rather than client-specific snippets.

## [0.2.0] - 2026-05

### Added
- Four new tools: `ping`, `search_campaigns`, `resend_to_non_openers`, `trigger_customer_journey`.
- Four additional template management tools, bringing total tools to **82**.

### Changed
- Rewrote all tool docstrings across five quality dimensions (TDQS scoring) for better
  agent-facing usability. Forty-three lower-scoring docstrings were further refined.
- CI now runs on Python 3.10, 3.12, and 3.13 via `setup-uv@v5`.

### Fixed
- CI YAML parsing issue with f-string curly braces.

## [0.1.2] - 2026-04

### Added
- Twenty-one new tools covering segments, merge fields, interests, webhooks, and
  additional campaign actions.
- CI workflow performing syntax and import validation across multiple Python versions.

### Changed
- Improved tool docstrings for TDQS scoring; refined nine lowest-scoring docstrings
  from C-rated to A/B-rated.

## [0.1.1] - 2026-03

### Added
- Read-only mode (`MAILCHIMP_READ_ONLY`) that blocks all write operations.
- Dry-run mode (`MAILCHIMP_DRY_RUN`) that previews write operations without executing them.
- Windows installation support.
- Dockerfile for Glama inspection and hosting.
- `glama.json` configuration for the Glama MCP registry.

### Changed
- Renamed package to `mailchimp-mcp` for PyPI publication.
- Improved error handling in API request helper.

### Fixed
- Broken packaging that prevented installation on certain platforms.

## [0.1.0] - 2026-03

### Added
- Initial release with read and write tools covering the Mailchimp Marketing API:
  campaigns, audiences, members, reports, segments, automations, templates,
  landing pages, e-commerce, and batch operations.
- MIT license, Python 3.10+ support, MCP-compatible via FastMCP.

[Unreleased]: https://github.com/damientilman/mailchimp-mcp-server/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/damientilman/mailchimp-mcp-server/releases/tag/v0.6.0
[0.5.0]: https://github.com/damientilman/mailchimp-mcp-server/releases/tag/v0.5.0
[0.4.0]: https://github.com/damientilman/mailchimp-mcp-server/releases/tag/v0.4.0
[0.3.0]: https://github.com/damientilman/mailchimp-mcp-server/releases/tag/v0.3.0
[0.2.1]: https://github.com/damientilman/mailchimp-mcp-server/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/damientilman/mailchimp-mcp-server/releases/tag/v0.2.0
[0.1.2]: https://github.com/damientilman/mailchimp-mcp-server/releases/tag/v0.1.2
[0.1.1]: https://github.com/damientilman/mailchimp-mcp-server/releases/tag/v0.1.1
[0.1.0]: https://github.com/damientilman/mailchimp-mcp-server/releases/tag/v0.1.0
