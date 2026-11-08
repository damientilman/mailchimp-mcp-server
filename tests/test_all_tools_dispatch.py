"""Call every registered tool once with synthesized arguments.

The goal is not to assert on each payload (the family tests do that) but to make sure
no tool raises on a minimal, well-formed Mailchimp response and that each one returns
a JSON string. It catches signature drift, bad f-strings in endpoints and unhandled
`None` values the moment a tool is added or edited.
"""

from __future__ import annotations

import inspect
import json

import pytest

from mailchimp_mcp_server import server

# Arguments the generic synthesizer cannot guess (the tool casts the value itself).
OVERRIDES: dict[str, dict] = {
    "create_landing_page": {"template_id": "1"},
}


def _value_for(annotation) -> object:
    text = str(annotation)
    if "bool" in text:
        return True
    if "int" in text:
        return 1
    if "float" in text:
        return 1.5
    if "dict" in text:
        return {"key": "value"}
    if "list" in text or "List" in text:
        return ["a@b.co"]
    return "abc123"


def _required_kwargs(name: str) -> dict:
    fn = getattr(server, name)
    kwargs = {
        pname: _value_for(param.annotation)
        for pname, param in inspect.signature(fn).parameters.items()
        if param.default is inspect.Parameter.empty
    }
    kwargs.update(OVERRIDES.get(name, {}))
    return kwargs


@pytest.mark.parametrize("name", sorted(server.TOOL_RISK))
def test_tool_returns_json_on_minimal_response(name: str, mock_mc_request) -> None:
    mock_mc_request({"id": "x1", "name": "n1"})
    result = getattr(server, name)(**_required_kwargs(name))
    assert isinstance(result, str)
    json.loads(result)
