"""Tests for the transport selection layer (stdio / streamable-http / sse).

The network transports are exercised without binding a socket: `main` is driven with `mcp.run`
patched, so these assert on what the server *would* start and how it configures the SDK.
"""

from __future__ import annotations

import pytest

from mailchimp_mcp_server import server


class TestResolveTransport:
    def test_unset_and_stdio_are_stdio(self) -> None:
        assert server._resolve_transport("") == "stdio"
        assert server._resolve_transport("  ") == "stdio"
        assert server._resolve_transport("stdio") == "stdio"

    def test_streamable_http_spellings(self) -> None:
        for spec in ("streamable-http", "streamable_http", "streamablehttp", "http"):
            assert server._resolve_transport(spec) == "streamable-http"

    def test_sse(self) -> None:
        assert server._resolve_transport("sse") == "sse"

    def test_case_and_whitespace_insensitive(self) -> None:
        assert server._resolve_transport("  SSE  ") == "sse"
        assert server._resolve_transport("Streamable-HTTP") == "streamable-http"

    def test_unknown_value_raises_instead_of_falling_back(self) -> None:
        # A typo must not silently start a stdio server no client is waiting on.
        with pytest.raises(ValueError, match="Unknown MAILCHIMP_TRANSPORT"):
            server._resolve_transport("websocket")


class TestTransportSecurity:
    def test_none_when_no_allow_lists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Keeping the SDK's own loopback defaults is the right behaviour for a local deployment.
        monkeypatch.setattr(server, "ALLOWED_HOSTS", [])
        monkeypatch.setattr(server, "ALLOWED_ORIGINS", [])
        assert server._transport_security() is None

    def test_allow_lists_are_applied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(server, "ALLOWED_HOSTS", ["mcp.internal:8000"])
        monkeypatch.setattr(server, "ALLOWED_ORIGINS", ["https://app.internal"])
        settings = server._transport_security()
        assert settings.enable_dns_rebinding_protection is True
        assert settings.allowed_hosts == ["mcp.internal:8000"]
        assert settings.allowed_origins == ["https://app.internal"]

    def test_wildcard_disables_rebinding_protection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(server, "ALLOWED_HOSTS", ["*"])
        monkeypatch.setattr(server, "ALLOWED_ORIGINS", [])
        assert server._transport_security().enable_dns_rebinding_protection is False


class TestMainDispatch:
    @staticmethod
    def _capture_run(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
        calls: list[dict] = []
        monkeypatch.setattr(server.mcp, "run", lambda **kwargs: calls.append(kwargs))
        return calls

    def test_default_runs_stdio_without_touching_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = self._capture_run(monkeypatch)
        monkeypatch.setattr(server, "TRANSPORT", "")
        monkeypatch.setattr(server.mcp.settings, "host", "sentinel")
        server.main()
        # stdio must stay a bare run() call: no host/port mutation, no banner.
        assert calls == [{}]
        assert server.mcp.settings.host == "sentinel"

    @pytest.mark.parametrize("spec,expected", [("http", "streamable-http"), ("sse", "sse")])
    def test_network_transport_binds_configured_host_and_port(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, spec: str, expected: str
    ) -> None:
        calls = self._capture_run(monkeypatch)
        monkeypatch.setattr(server, "TRANSPORT", spec)
        monkeypatch.setattr(server, "HOST", "0.0.0.0")
        monkeypatch.setattr(server, "PORT", 9123)
        monkeypatch.setattr(server, "ALLOWED_HOSTS", [])
        monkeypatch.setattr(server, "ALLOWED_ORIGINS", [])
        server.main()
        assert calls == [{"transport": expected}]
        assert server.mcp.settings.host == "0.0.0.0"
        assert server.mcp.settings.port == 9123

    def test_unknown_transport_aborts_before_running(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = self._capture_run(monkeypatch)
        monkeypatch.setattr(server, "TRANSPORT", "grpc")
        with pytest.raises(ValueError):
            server.main()
        assert calls == []


class TestStartupBanner:
    def _banner(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, **overrides) -> str:
        monkeypatch.setattr(server.mcp, "run", lambda **kwargs: None)
        monkeypatch.setattr(server, "TRANSPORT", overrides.get("transport", "http"))
        monkeypatch.setattr(server, "HOST", overrides.get("host", "127.0.0.1"))
        monkeypatch.setattr(server, "PORT", 8000)
        monkeypatch.setattr(server, "ALLOWED_HOSTS", [])
        monkeypatch.setattr(server, "ALLOWED_ORIGINS", [])
        monkeypatch.setattr(server, "READ_ONLY", overrides.get("read_only", False))
        server.main()
        return capsys.readouterr().err

    def test_states_the_missing_authentication(self, monkeypatch, capsys) -> None:
        banner = self._banner(monkeypatch, capsys)
        assert "NO authentication" in banner
        assert "MAILCHIMP_API_KEY" in banner
        assert f"{len(server.TOOL_RISK)} tools exposed" in banner

    def test_warns_louder_off_loopback(self, monkeypatch, capsys) -> None:
        assert "not loopback" in self._banner(monkeypatch, capsys, host="0.0.0.0")
        assert "not loopback" not in self._banner(monkeypatch, capsys, host="127.0.0.1")

    def test_read_only_hint_only_when_writes_are_live(self, monkeypatch, capsys) -> None:
        assert "MAILCHIMP_READ_ONLY=true" in self._banner(monkeypatch, capsys)
        assert "MAILCHIMP_READ_ONLY=true" not in self._banner(monkeypatch, capsys, read_only=True)

    def test_sse_deprecation_noted(self, monkeypatch, capsys) -> None:
        assert "deprecated" in self._banner(monkeypatch, capsys, transport="sse")
        assert "deprecated" not in self._banner(monkeypatch, capsys, transport="http")


class TestAsgiAppsBuild:
    """The SDK must actually be able to build both HTTP apps for this tool registry."""

    def test_sse_app_exposes_its_routes(self) -> None:
        routes = {getattr(r, "path", None) for r in server.mcp.sse_app().routes}
        assert "/sse" in routes

    def test_streamable_http_app_builds(self) -> None:
        assert server.mcp.streamable_http_app() is not None
