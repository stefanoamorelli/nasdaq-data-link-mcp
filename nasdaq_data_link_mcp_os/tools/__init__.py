"""Toolsets and their registration on the server."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast

from mcp.server import MCPServer
from mcp.server.mcpserver.tools.base import Tool
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase
from pydantic import ConfigDict

from nasdaq_data_link_mcp_os.tools import (
    core,
    equities,
    funds,
    nasdaq,
    sql,
    world_bank,
)
from nasdaq_data_link_mcp_os.tools._common import (
    READ_ONLY_LOCAL,
    READ_ONLY_REMOTE,
    Toolset,
    wrap_tool,
)

TOOLSETS: dict[str, Toolset] = {
    module.TOOLSET.name: module.TOOLSET
    for module in (
        core,
        sql,
        nasdaq,
        equities,
        funds,
        world_bank,
    )
}
ALWAYS_ON = ("core",)


def resolve_toolsets(requested: Iterable[str] | None) -> list[str]:
    """Return enabled toolset names in registry order. ``None`` means all."""
    if requested is None:
        return list(TOOLSETS)
    wanted = {name.strip().lower() for name in requested if name.strip()}
    unknown = wanted - set(TOOLSETS)
    if unknown:
        raise ValueError(
            f"Unknown toolset(s): {', '.join(sorted(unknown))}. Available: "
            f"{', '.join(TOOLSETS)} (or 'all')."
        )
    wanted.update(ALWAYS_ON)
    return [name for name in TOOLSETS if name in wanted]


def _compact_schema(schema: Any) -> Any:
    """Drop pydantic's generated ``title`` keys; names already say the same."""
    if isinstance(schema, dict):
        return {
            key: _compact_schema(value)
            for key, value in schema.items()
            if not (key == "title" and isinstance(value, str))
        }
    if isinstance(schema, list):
        return [_compact_schema(item) for item in schema]
    return schema


def _strict(tool: Tool) -> Tool:
    """Reject unknown arguments instead of silently ignoring them.

    Tools name the same concept the same way, but a model that guesses a
    parameter name should get a validation error, not unfiltered data.
    """
    base = tool.fn_metadata.arg_model
    strict = cast(
        type[ArgModelBase],
        type(
            base.__name__,
            (base,),
            {
                "model_config": ConfigDict(
                    **{**base.model_config, "title": f"[INVALID_REQUEST] {tool.name}"},
                    extra="forbid",
                    hide_input_in_errors=True,
                )
            },
        ),
    )
    tool.fn_metadata.arg_model = strict
    tool.parameters = _compact_schema(strict.model_json_schema(by_alias=True))
    return tool


def build_tools(
    names: Iterable[str],
    *,
    deadline_seconds: float | None = None,
    secret: str | None = None,
) -> list[Tool]:
    tools: list[Tool] = []
    for name in names:
        for spec in TOOLSETS[name].tools:
            tool = Tool.from_function(
                wrap_tool(spec.fn, deadline_seconds=deadline_seconds, secret=secret),
                name=spec.fn.__name__,
                title=spec.title,
                annotations=READ_ONLY_LOCAL if spec.local else READ_ONLY_REMOTE,
                meta={"toolset": name},
            )
            tools.append(_strict(tool))
    return tools


def table_tools(names: Iterable[str]) -> dict[str, list[str]]:
    """Map each table code to the enabled typed tools that read it."""
    mapping: dict[str, list[str]] = {}
    for name in names:
        for spec in TOOLSETS[name].tools:
            for code in spec.tables:
                mapping.setdefault(code, []).append(spec.fn.__name__)
    return mapping


def routing_hints(names: Iterable[str]) -> list[str]:
    return [hint for name in names for hint in TOOLSETS[name].hints]


def register_prompts(server: MCPServer, names: Iterable[str]) -> None:
    for name in names:
        for prompt in TOOLSETS[name].prompts:
            server.prompt(name=prompt.fn.__name__, title=prompt.title)(prompt.fn)
