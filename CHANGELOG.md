# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Test suite covering safety modes, request helpers, and a smoke test per tool family.
- `CONTRIBUTING.md` with development setup and contribution guidelines.
- `SECURITY.md` with vulnerability reporting policy.
- CI improvements: linting (ruff), test execution, and coverage reporting.
- Multi-stage Dockerfile running as a non-root user.

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

[Unreleased]: https://github.com/damientilman/mailchimp-mcp-server/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/damientilman/mailchimp-mcp-server/releases/tag/v0.2.0
[0.1.2]: https://github.com/damientilman/mailchimp-mcp-server/releases/tag/v0.1.2
[0.1.1]: https://github.com/damientilman/mailchimp-mcp-server/releases/tag/v0.1.1
[0.1.0]: https://github.com/damientilman/mailchimp-mcp-server/releases/tag/v0.1.0
