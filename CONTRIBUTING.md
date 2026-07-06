# Contributing to Mailchimp MCP Server

Thanks for your interest in contributing! This project is an open source MCP server
for the [Mailchimp Marketing API](https://mailchimp.com/developer/marketing/api/).
Contributions of all kinds are welcome: bug reports, feature requests, documentation
improvements, and pull requests.

## Code of Conduct

Be respectful and constructive. Treat others the way you want to be treated. Harassment
or personal attacks will not be tolerated.

## Reporting Issues

Before opening an issue, please:

1. Search [existing issues](https://github.com/damientilman/mailchimp-mcp-server/issues)
   to avoid duplicates.
2. Include the Python version, OS, and the version of `mailchimp-mcp` you are running.
3. Provide a minimal reproduction (the exact tool call, expected vs. actual behavior).
4. For API errors, include the (redacted) error response from Mailchimp.

**Do not include API keys, account IDs, or member email addresses in issue reports.**
For security-related reports, see [SECURITY.md](SECURITY.md).

## Development Setup

This project uses [`uv`](https://docs.astral.sh/uv/) for dependency management.

```bash
git clone https://github.com/damientilman/mailchimp-mcp-server.git
cd mailchimp-mcp-server
uv sync --extra dev
```

To run the server locally against your own Mailchimp account:

```bash
export MAILCHIMP_API_KEY="your-key-here"
export MAILCHIMP_READ_ONLY=true  # recommended during development
uv run mailchimp-mcp
```

## Running Tests

The full test suite runs without hitting the Mailchimp API (all network calls are mocked):

```bash
uv run pytest
```

With coverage:

```bash
uv run pytest --cov=mailchimp_mcp_server --cov-report=term-missing
```

## Linting and Formatting

This project uses [`ruff`](https://docs.astral.sh/ruff/) for linting and formatting.

```bash
uv run ruff check src/ tests/      # lint
uv run ruff format src/ tests/     # format
```

CI runs `ruff check` and fails on lint violations, so run it before opening a PR. Formatting is
not enforced in CI, but running `ruff format` keeps diffs clean.

## Adding a New Tool

When adding a new tool, follow the existing patterns in `src/mailchimp_mcp_server/server.py`:

1. **Use `@mcp.tool()`** as the decorator.
2. **Write a comprehensive docstring** following the existing TDQS-style format:
   summary, use cases, authentication, args, returns, optional example.
3. **For write operations**, include the safety guard:
   ```python
   if (guard := _guard_write(action="...", **params)):
       return guard
   ```
4. **Return JSON strings** (`json.dumps(..., indent=2)`), not Python objects.
5. **Handle errors gracefully** — `mc_request` already returns `{"error": "..."}`
   payloads on failure; pass these through transparently.
6. **Add at least one smoke test** in `tests/test_tools_smoke.py`.

## Pull Request Process

1. Fork the repository and create a feature branch from `main`.
2. Make your changes with clear, focused commits.
3. Update `CHANGELOG.md` under the `[Unreleased]` section.
4. Run tests and linting locally.
5. Open a PR with a clear description of the change and its motivation.
6. Address review feedback as needed.

## Releasing

Maintainers tag releases with `vX.Y.Z` following semver. CHANGELOG entries move from
`[Unreleased]` to a versioned section on release.

## License

By contributing, you agree that your contributions will be licensed under the
[MIT License](LICENSE).
