"""Shared fixtures for the test suite.

All fixtures avoid hitting the real Mailchimp API. `mc_request` is patched at the
module level so any tool call routed through it can be controlled per-test.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from mailchimp_mcp_server import server


@pytest.fixture(autouse=True)
def _reset_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure each test starts with safety flags off and a valid-looking API key.

    Flags are module-level globals evaluated at import time, so individual tests
    that want them on must call `monkeypatch.setattr` themselves.
    """
    monkeypatch.setattr(server, "READ_ONLY", False)
    monkeypatch.setattr(server, "DRY_RUN", False)
    monkeypatch.setattr(server, "MAILCHIMP_API_KEY", "test-key-us1")
    monkeypatch.setattr(server, "MAILCHIMP_DC", "us1")
    monkeypatch.setattr(server, "MAILCHIMP_BASE_URL", "https://us1.api.mailchimp.com/3.0")
    monkeypatch.setattr(server, "MAILCHIMP_ACCOUNTS", {})
    # Retry backoff must never actually block the test suite.
    monkeypatch.setattr(server.time, "sleep", lambda *args, **kwargs: None)


@pytest.fixture
def mock_mc_request(monkeypatch: pytest.MonkeyPatch) -> Callable[[Any], list[dict]]:
    """Replace `mc_request` with a stub that returns a pre-configured payload.

    Returns a helper that, when called with a payload (or a list of payloads for
    sequenced calls), installs the stub and returns the list of recorded call
    arguments so a test can assert on what the tool dispatched.
    """

    def _install(payload: Any) -> list[dict]:
        calls: list[dict] = []
        responses = payload if isinstance(payload, list) else [payload]
        index = {"i": 0}

        def fake_request(
            endpoint: str,
            params: dict | None = None,
            body: dict | None = None,
            method: str = "GET",
            *,
            account: str | None = None,
        ) -> dict:
            calls.append(
                {"endpoint": endpoint, "params": params, "body": body, "method": method, "account": account}
            )
            response = responses[min(index["i"], len(responses) - 1)]
            index["i"] += 1
            return response

        monkeypatch.setattr(server, "mc_request", fake_request)
        return calls

    return _install
