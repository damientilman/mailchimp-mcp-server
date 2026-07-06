# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- Every write and destructive tool now surfaces the API error instead of reporting a hard-coded
  success. Around 20 tools — including `send_campaign`, `send_test_email`, `schedule_campaign`,
  `cancel_send`, `delete_campaign`, `pause_automation`, and the `delete_*` family — previously
  discarded the API result and always returned success, so a rejected send was reported as
  `sent` and a failed delete as `deleted`. The error each docstring promised is now actually
  returned.
- `delete_member` and `tag_member` now surface the API error instead of always reporting
  success — a failed GDPR deletion no longer returns a false `permanently_deleted` confirmation.
- `tag_member` no longer documents "read scope required": it is a write, and the note is dropped
  to match the other tools.
- The `idempotent` hint (MCP annotation and `describe_tools`) now agrees with the docstrings for
  `update_member`, `tag_member`, `update_segment`, and `publish_landing_page`, which state they
  are idempotent but were previously reported otherwise.
- Malformed JSON passed to `batch_subscribe`, `create_segment`, `update_segment`, or
  `create_batch` returns a readable error instead of raising an unhandled exception.
- Path parameters containing `..` are rejected before dispatch, closing an endpoint-traversal
  gap the empty-segment (`//`) check missed.
- Audit log now redacts subscriber PII (`email_address`, `email`, `merge_fields`) at any depth,
  including inside `batch_subscribe` member arrays; previously only `file_data` was masked.
- Corrected the contradictory docs on `delete_member` / `delete_member_permanent`: both call the
  same permanent-deletion endpoint and are equivalent.

### Added
- **Tool profiles** — `MAILCHIMP_TOOLS` selects which tools to expose, to shrink the tool-list
  payload sent to the model on every turn. Accepts a comma-separated mix of risk tiers
  (`read` / `write` / `destructive`) and/or exact tool names; unset or `all` exposes everything.
  Example: `MAILCHIMP_TOOLS=read` loads ~115 read tools (~29k tokens) instead of all 227 (~63k).
- **Automatic retries** on transient failures (429 and 5xx) with exponential backoff, honoring
  the `Retry-After` header. Configurable via `MAILCHIMP_MAX_RETRIES` (default 3). Network
  timeouts are not retried, so a write that may already have landed is never replayed.
- **Connection pooling** — one keep-alive `requests.Session` per account, so sequential calls
  reuse the TCP/TLS connection instead of reconnecting each time.

### Changed
- **Leaner tool descriptions** — repeated per-tool boilerplate (the "Authenticated via API key…"
  note and the identical `account:` argument line) is trimmed from the wire descriptions at
  import, cutting the full tool-list footprint by roughly 18% with no loss of tool-selection
  information. Source docstrings are unchanged.
- Email addresses are validated before use; a malformed address returns a clear error instead
  of a confusing 404 against a hash that matches no member.
- `batch_subscribe` enforces the documented 500-member cap, and `offset` must be zero or greater.

## [1.0.0] - 2026-07-01

### Added
- **Runtime security guardrails** (#36) — server-side signals a runtime-security gateway can
  enforce on, following the defense-in-depth split discussed in the community thread:
  - **Machine-readable risk metadata** — every tool is classified `read` / `write` /
    `destructive` (irreversible data loss or an irreversible send). Exposed both as
    MCP-standard tool annotations (`readOnlyHint` / `destructiveHint` / `idempotentHint`) via
    `tools/list` and through a new **`describe_tools`** read tool (per-tool risk + tier counts).
  - **Structured audit log** — `MAILCHIMP_AUDIT_LOG=true` emits one JSON event per dispatch to
    stderr (tool, risk tier, destructive flag, account, outcome, inspected args) from the two
    chokepoints; bulky/sensitive values (e.g. `file_data`) are redacted, response bodies never
    logged. Off by default with zero overhead.
  - **Argument-contract validation** — `mc_request` rejects out-of-range `count` (must be
    1–1000) and missing path IDs before dispatch, and the dry-run preview now carries the
    tool's risk tier.
- **Multi-account support** (#37) — configure additional Mailchimp accounts with
  `MAILCHIMP_API_KEY_<NAME>` environment variables (the plain `MAILCHIMP_API_KEY`
  remains the implicit `default`). Every tool gains an optional `account` argument to
  target a specific account per call; selection is stateless, with no active-account
  switching, so a write always names its target. Each account derives its datacenter
  from its own key and honors its own `MAILCHIMP_READ_ONLY_<NAME>` /
  `MAILCHIMP_DRY_RUN_<NAME>` safety flags, so a write-protected and a writable account
  can live in the same server. An unknown `account` returns an error listing the
  configured accounts. Single-key setups are unaffected and behave exactly as before.
- **`list_accounts`** — read-only tool returning the configured account names and their
  read-only / dry-run state, for discovering valid `account` values. Never returns API keys.
- **File Manager** (#14) — `list_files`, `get_file`, `upload_file` (base64), `delete_file`,
  and `list_file_folders`, enabling programmatic image hosting for campaign and template content.
- **Surveys** (#15) — `list_surveys`, `get_survey`, `publish_survey`, and `unpublish_survey`
  for an audience's surveys.
- **Signup forms** (#16) — `list_signup_forms` and `customize_signup_form` (header, contents,
  and styles) for an audience's default signup form.
- **Sending foundations & compliance** — **Verified Domains** (list/get/create/verify/delete),
  **campaign send-checklist** (`get_campaign_send_checklist`), **GDPR** `delete_member_permanent`,
  and idempotent `upsert_member` (PUT add-or-update).
- **Reporting & organization** — **Survey reports** (`list_survey_reports`, `get_survey_report`,
  `get_survey_responses`, `get_survey_response`, `get_survey_questions_report`,
  `get_survey_question_answers`), **Landing Page reports** (`list_landing_page_reports`,
  `get_landing_page_report`), campaign `get_campaign_sent_to` and abuse reports, **Campaign and
  Template folder CRUD**, and audience `get_audience_top_locations` / `get_audience_activity`.
- **Automation & deliverability** — single-email control for classic automations (get / pause /
  start / queue / removed-subscribers), `add_member_event`, `get_member_goals`, audience
  `get_audience_clients` and abuse reports, **batch webhooks CRUD**, `get_chimp_chatter`,
  account exports, connected sites, authorized apps, campaign collaboration feedback, and RSS
  campaign pause/resume.
- **Full e-commerce writes** — CRUD for stores, products, product variants, product images,
  orders, order lines, and customers, plus account-wide `list_account_orders`. These manual
  writes target custom/headless storefronts (Shopify/WooCommerce sync automatically).

### Changed
- Tool count bumped to **227** (was 115) — README and `glama.json` descriptions updated
  accordingly. Adds multi-account, File Manager, Surveys, Signup forms, Verified Domains,
  reporting depth, deliverability, automation controls, full e-commerce writes, and the
  `describe_tools` risk-metadata tool.

### Fixed
- Account selectors are now matched case-insensitively — a capitalized `account`
  (e.g. `"Marketing"`, `"Default"`) resolves to the configured account instead of erroring,
  matching how account names are lowercased when the registry is built.
- The `ToolAnnotations` import is now optional — on older `mcp` SDKs that predate tool
  annotations the server still imports and runs; risk metadata remains available via
  `describe_tools`, only the `tools/list` annotations are skipped.

## [0.7.0] - 2026-06-24

### Added
- **`get_campaign_content`** — read tool returning a campaign's rendered body copy via
  `GET /campaigns/{id}/content`. Fills the gap between `get_campaign_details` (settings)
  and `set_campaign_content` (draft writes), which left no way to read the body of a sent
  campaign. Returns `plain_text` by default, with `include_html` to opt into the raw HTML;
  A/B (variate) campaigns return a per-variation breakdown. Registered as a read tool, so it
  stays available under `MAILCHIMP_READ_ONLY=true`.

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
