# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/damientilman/mailchimp-mcp-server/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/damientilman/mailchimp-mcp-server/releases/tag/v0.3.0
[0.2.1]: https://github.com/damientilman/mailchimp-mcp-server/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/damientilman/mailchimp-mcp-server/releases/tag/v0.2.0
[0.1.2]: https://github.com/damientilman/mailchimp-mcp-server/releases/tag/v0.1.2
[0.1.1]: https://github.com/damientilman/mailchimp-mcp-server/releases/tag/v0.1.1
[0.1.0]: https://github.com/damientilman/mailchimp-mcp-server/releases/tag/v0.1.0
