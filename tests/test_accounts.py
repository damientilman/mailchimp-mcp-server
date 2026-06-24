"""Tests for multi-account loading and resolution."""

from __future__ import annotations

import pytest

from mailchimp_mcp_server import server


class TestLoadAccounts:
    def test_loads_named_accounts_with_dc_and_flags(self, monkeypatch: pytest.MonkeyPatch) -> None:
        env = {
            "MAILCHIMP_API_KEY": "default-us1",
            "MAILCHIMP_API_KEY_MARKETING": "mktkey-us5",
            "MAILCHIMP_READ_ONLY_MARKETING": "true",
            "MAILCHIMP_API_KEY_SALES": "saleskey-us9",
            "MAILCHIMP_DRY_RUN_SALES": "1",
        }
        monkeypatch.setattr(server.os, "environ", env)
        accounts = server._load_accounts()

        assert set(accounts) == {"marketing", "sales"}
        assert accounts["marketing"]["dc"] == "us5"
        assert accounts["marketing"]["base_url"] == "https://us5.api.mailchimp.com/3.0"
        assert accounts["marketing"]["read_only"] is True
        assert accounts["marketing"]["dry_run"] is False
        assert accounts["sales"]["dc"] == "us9"
        assert accounts["sales"]["dry_run"] is True
        assert accounts["sales"]["read_only"] is False

    def test_plain_key_is_not_stored_as_named_account(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(server.os, "environ", {"MAILCHIMP_API_KEY": "default-us1"})
        assert server._load_accounts() == {}

    def test_dc_falls_back_to_us1_when_no_dash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(server.os, "environ", {"MAILCHIMP_API_KEY_FOO": "nodash"})
        assert server._load_accounts()["foo"]["dc"] == "us1"

    def test_empty_value_is_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(server.os, "environ", {"MAILCHIMP_API_KEY_FOO": ""})
        assert server._load_accounts() == {}

    def test_default_suffix_is_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # MAILCHIMP_API_KEY_DEFAULT would shadow the implicit default; it must be ignored.
        monkeypatch.setattr(server.os, "environ", {"MAILCHIMP_API_KEY_DEFAULT": "x-us2"})
        assert server._load_accounts() == {}

    def test_safety_env_vars_are_not_mistaken_for_accounts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # MAILCHIMP_READ_ONLY / MAILCHIMP_DRY_RUN must not be read as MAILCHIMP_API_KEY_<NAME>.
        env = {"MAILCHIMP_READ_ONLY": "true", "MAILCHIMP_DRY_RUN": "true"}
        monkeypatch.setattr(server.os, "environ", env)
        assert server._load_accounts() == {}


class TestResolveAccount:
    def test_none_resolves_to_live_default_globals(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(server, "MAILCHIMP_API_KEY", "live-us3")
        monkeypatch.setattr(server, "MAILCHIMP_BASE_URL", "https://us3.api.mailchimp.com/3.0")
        resolved = server._resolve_account(None)
        assert resolved["name"] == "default"
        assert resolved["api_key"] == "live-us3"
        assert resolved["base_url"] == "https://us3.api.mailchimp.com/3.0"

    def test_default_string_resolves_to_globals(self) -> None:
        assert server._resolve_account("default")["name"] == "default"

    def test_named_account_resolves_from_registry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            server,
            "MAILCHIMP_ACCOUNTS",
            {"tts": {"api_key": "k-us7", "dc": "us7", "base_url": "https://us7.api.mailchimp.com/3.0", "read_only": True, "dry_run": False}},
        )
        resolved = server._resolve_account("tts")
        assert resolved["name"] == "tts"
        assert resolved["api_key"] == "k-us7"
        assert resolved["base_url"] == "https://us7.api.mailchimp.com/3.0"
        assert resolved["read_only"] is True

    def test_unknown_account_returns_error_listing_names(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(server, "MAILCHIMP_API_KEY", "live-us1")
        monkeypatch.setattr(
            server,
            "MAILCHIMP_ACCOUNTS",
            {"tts": {"api_key": "k-us7", "dc": "us7", "base_url": "x", "read_only": False, "dry_run": False}},
        )
        resolved = server._resolve_account("nope")
        assert "error" in resolved
        assert "nope" in resolved["error"]
        assert "default" in resolved["error"]
        assert "tts" in resolved["error"]

    def test_available_names_includes_default_only_when_key_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(server, "MAILCHIMP_ACCOUNTS", {"tts": {"read_only": False, "dry_run": False}})
        monkeypatch.setattr(server, "MAILCHIMP_API_KEY", "live-us1")
        assert server._available_account_names() == ["default", "tts"]
        monkeypatch.setattr(server, "MAILCHIMP_API_KEY", "")
        assert server._available_account_names() == ["tts"]
