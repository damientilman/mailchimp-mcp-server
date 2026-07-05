"""Tests for the tools/list footprint optimizations: description trimming and tool profiles."""

from __future__ import annotations

import inspect

from mailchimp_mcp_server import server


class TestDescriptionTrim:
    def test_boilerplate_removed_from_wire_descriptions(self) -> None:
        for tool in server.mcp._tool_manager.list_tools():
            description = tool.description or ""
            assert "Authenticated via API key." not in description
            assert "account: Optional account name" not in description

    def test_source_docstrings_stay_full(self) -> None:
        # Trimming is runtime-only; the source docstrings keep the account line the
        # coverage test relies on.
        source = inspect.getsource(server.get_audience_details)
        assert "account: Optional account name" in source

    def test_summary_and_args_preserved(self) -> None:
        description = server.mcp._tool_manager.get_tool("list_files").description
        assert description.startswith("List images and files")
        assert "count:" in description  # real argument docs kept
        assert "offset:" in description

    def test_empty_args_header_dropped(self) -> None:
        # get_account_info's only parameter was `account`; the now-empty Args: header is gone.
        description = server.mcp._tool_manager.get_tool("get_account_info").description
        assert "Args:" not in description
        assert description.startswith("Retrieve Mailchimp account details")


class TestSelectedToolNames:
    RISK = {"list_x": "read", "create_x": "write", "delete_x": "destructive"}

    def test_empty_or_all_keeps_everything(self) -> None:
        assert server._selected_tool_names("", self.RISK) is None
        assert server._selected_tool_names("all", self.RISK) is None
        assert server._selected_tool_names("  ", self.RISK) is None

    def test_single_tier(self) -> None:
        assert server._selected_tool_names("read", self.RISK) == {"list_x"}

    def test_multiple_tiers(self) -> None:
        assert server._selected_tool_names("read,write", self.RISK) == {"list_x", "create_x"}

    def test_explicit_tool_name(self) -> None:
        assert server._selected_tool_names("delete_x", self.RISK) == {"delete_x"}

    def test_mixed_names_and_tiers(self) -> None:
        assert server._selected_tool_names("read,delete_x", self.RISK) == {"list_x", "delete_x"}

    def test_case_insensitive(self) -> None:
        assert server._selected_tool_names("READ", self.RISK) == {"list_x"}


class TestDefaultProfile:
    def test_default_process_exposes_all_tools(self) -> None:
        # With MAILCHIMP_TOOLS unset (the test env), nothing is filtered out.
        assert len(server.mcp._tool_manager.list_tools()) == len(server.TOOL_RISK)
        assert len(server.TOOL_RISK) > 200
