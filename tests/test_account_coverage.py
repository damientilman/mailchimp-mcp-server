"""Structural guarantee that every tool carries and threads the `account` argument.

This future-proofs CI: any new @mcp.tool() added without `account` (or that forgets to
thread it into mc_request / _guard_write) fails here, not silently in production.
"""

from __future__ import annotations

import ast
import inspect

from mailchimp_mcp_server import server

# list_accounts intentionally takes no `account` (it lists them).
_EXEMPT = {"list_accounts"}

_TREE = ast.parse(inspect.getsource(server))
_TOOLS = [
    node
    for node in _TREE.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    and any(isinstance(d, ast.Call) and getattr(d.func, "attr", None) == "tool" for d in node.decorator_list)
]


def _params(fn: ast.FunctionDef) -> set[str]:
    return {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}


def test_tools_were_discovered() -> None:
    assert len(_TOOLS) > 100, "tool discovery looks wrong"


def test_every_tool_has_account_param() -> None:
    missing = [fn.name for fn in _TOOLS if fn.name not in _EXEMPT and "account" not in _params(fn)]
    assert not missing, f"tools missing `account` parameter: {missing}"


def test_every_call_threads_account() -> None:
    missing: list[str] = []
    for fn in _TOOLS:
        if fn.name in _EXEMPT:
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("mc_request", "_guard_write"):
                threaded = any(
                    kw.arg == "account" and isinstance(kw.value, ast.Name) and kw.value.id == "account"
                    for kw in node.keywords
                )
                if not threaded:
                    missing.append(f"{fn.name}:{node.func.id}@L{node.lineno}")
    assert not missing, f"calls not threading account=account: {missing}"


def test_every_tool_documents_account() -> None:
    missing = [fn.name for fn in _TOOLS if fn.name not in _EXEMPT and "account:" not in (ast.get_docstring(fn) or "")]
    assert not missing, f"tools whose docstring omits `account:`: {missing}"
