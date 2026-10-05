"""Regenerate the tool reference in README.md and docs/ from the server itself.

Tools, prompts and resources come from a server built with ``create_server``
and listed through an in-memory MCP client, so the reference shows exactly
what a client sees. The tables each tool reads come from its ``ToolSpec``, and
what a free API key gets from the bundled catalog (``data/catalog.json``).
Nothing calls Nasdaq, and the output depends only on the code and the catalog.

Written:
- README.md: the blocks between ``<!-- NAME:start -->`` and ``<!-- NAME:end -->``
  for NAME = tools, free-tables and prompts-resources;
- docs/tools/overview.mdx and one docs/tools/<toolset>.mdx per toolset;
- docs/access-levels.mdx: the block between ``{/* free-tables:start */}`` and
  ``{/* free-tables:end */}``;
- docs/docs.json: the pages of the "Tools" navigation group.

Usage:
    uv run python scripts/generate_tool_docs.py           # rewrite the files
    uv run python scripts/generate_tool_docs.py --check   # exit 1 if stale
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import anyio
from mcp import Client
from mcp import types as mcp_types

from nasdaq_data_link_mcp_os.catalog import ACCESS_LEVELS, Catalog, CatalogEntry
from nasdaq_data_link_mcp_os.config import Settings
from nasdaq_data_link_mcp_os.server import create_server
from nasdaq_data_link_mcp_os.tools import ALWAYS_ON, TOOLSETS
from nasdaq_data_link_mcp_os.tools._common import STALE_AFTER_DAYS

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
DOCS = ROOT / "docs"
DOCS_JSON = DOCS / "docs.json"
ACCESS_PAGE = DOCS / "access-levels.mdx"
TOOLS_DIR = DOCS / "tools"
TOOLS_NAV_GROUP = "Tools"
SCRIPT = "scripts/generate_tool_docs.py"

ACCESS_LABELS = {
    "free": "Free",
    "sample": "Sample",
    "subscription": "Subscription",
    "unknown": "Not probed",
}
# Tools whose ToolSpec lists no tables, or whose tables say little about access.
FREE_KEY_OVERRIDES = {
    "ndl_check_api_status": "Free (one request to NDAQ/RTAT10)",
    "ndl_sql_query": "Usually NDAQ/RTAT and NDAQ/RTAT10 only",
}
# Parameters left out of the README's "main parameters" column.
MINOR_PARAMS = ("limit", "cursor", "descending", "columns")
MAX_MAIN_PARAMS = 5
# Toolsets whose tools read any table rather than one dataset.
GENERIC_TOOLSETS = ("core", "sql")


# ----------------------------------------------------------------- collect


@dataclass(frozen=True)
class ToolDoc:
    name: str
    title: str
    description: str
    schema: dict[str, Any]
    toolset: str
    local: bool
    tables: tuple[str, ...]

    @property
    def summary(self) -> str:
        return one_line(self.description.split("\n\n")[0])

    @property
    def body(self) -> str:
        """The description after its first line, as paragraphs."""
        rest = self.description.split("\n", 1)[1] if "\n" in self.description else ""
        paragraphs = [one_line(p) for p in rest.split("\n\n") if p.strip()]
        return "\n\n".join(paragraphs)


@dataclass(frozen=True)
class Listing:
    tools: list[ToolDoc]
    prompts: list[mcp_types.Prompt]
    resources: list[mcp_types.Resource]
    templates: list[mcp_types.ResourceTemplate]


async def _paged(fetch: Callable[..., Awaitable[Any]], attr: str) -> list[Any]:
    items: list[Any] = []
    cursor: str | None = None
    while True:
        page = await fetch(cursor=cursor)
        items.extend(getattr(page, attr))
        cursor = page.next_cursor
        if not cursor:
            return items


async def _collect() -> Listing:
    specs = {
        spec.fn.__name__: (name, spec)
        for name, toolset in TOOLSETS.items()
        for spec in toolset.tools
    }
    server = create_server(Settings(api_key="docs-generator"))
    async with Client(server) as client:
        tools = await _paged(client.list_tools, "tools")
        prompts = await _paged(client.list_prompts, "prompts")
        resources = await _paged(client.list_resources, "resources")
        templates = await _paged(client.list_resource_templates, "resource_templates")
    docs: list[ToolDoc] = []
    for tool in tools:
        if tool.name not in specs:
            raise SystemExit(f"{tool.name} is listed but has no ToolSpec")
        toolset, spec = specs.pop(tool.name)
        meta = tool.meta or {}
        if meta.get("toolset") != toolset:
            raise SystemExit(f"{tool.name}: _meta.toolset is {meta.get('toolset')!r}")
        docs.append(
            ToolDoc(
                name=tool.name,
                title=tool.title or tool.name,
                description=(tool.description or "").strip(),
                schema=dict(tool.input_schema),
                toolset=toolset,
                local=spec.local,
                tables=tuple(spec.tables),
            )
        )
    if specs:
        raise SystemExit(f"Tools not listed by the server: {', '.join(sorted(specs))}")
    return Listing(docs, prompts, resources, templates)


# ------------------------------------------------------------------ format


def one_line(text: str) -> str:
    return " ".join(text.split())


def cell(text: str) -> str:
    """Text for a Markdown table cell."""
    return one_line(text).replace("|", "\\|")


_CODE_SPAN = re.compile(r"(`+).+?\1", re.DOTALL)


def mdx(text: str) -> str:
    """Escape the characters MDX treats as syntax, outside code spans."""
    out: list[str] = []
    pos = 0
    for match in _CODE_SPAN.finditer(text):
        out.append(re.sub(r"([{}<>])", r"\\\1", text[pos : match.start()]))
        out.append(match.group(0))
        pos = match.end()
    out.append(re.sub(r"([{}<>])", r"\\\1", text[pos:]))
    return "".join(out)


def code(value: str) -> str:
    return f"`{value}`"


def plain(text: str) -> str:
    return text


def table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
    ]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


class Reference:
    """Everything the generated text is built from."""

    def __init__(self, listing: Listing, catalog: Catalog) -> None:
        self.listing = listing
        self.catalog = catalog
        self.snapshot = catalog.generated_at or "unknown"
        self.by_toolset: dict[str, list[ToolDoc]] = {name: [] for name in TOOLSETS}
        for tool in listing.tools:
            self.by_toolset[tool.toolset].append(tool)
        self.table_tools: dict[str, list[str]] = {}
        for tool in listing.tools:
            for code_ in tool.tables:
                self.table_tools.setdefault(code_, []).append(tool.name)
        prompt_toolsets = {
            prompt.fn.__name__: name
            for name, toolset in TOOLSETS.items()
            for prompt in toolset.prompts
        }
        self.prompt_toolset = {
            p.name: prompt_toolsets.get(p.name, "") for p in listing.prompts
        }

    # -------------------------------------------------------- data helpers

    def entry(self, table_code: str) -> CatalogEntry | None:
        return self.catalog.get(table_code)

    def access(self, table_code: str) -> str:
        entry = self.entry(table_code)
        return entry.access if entry else "unknown"

    def last_refreshed(self, table_code: str) -> str | None:
        entry = self.entry(table_code)
        return entry.refreshed_at[:10] if entry and entry.refreshed_at else None

    def is_current(self, day: str) -> bool:
        """Refreshed within the server's staleness window of the snapshot."""
        try:
            age = date.fromisoformat(self.snapshot) - date.fromisoformat(day)
        except ValueError:
            return False
        return age.days <= STALE_AFTER_DAYS

    def free_key(self, tool: ToolDoc) -> str:
        """What a free key gets from the tables a tool reads."""
        if tool.name in FREE_KEY_OVERRIDES:
            return FREE_KEY_OVERRIDES[tool.name]
        if not tool.tables:
            return "No API call" if tool.local else "Depends on the table"
        groups: dict[str, list[str]] = {}
        for code_ in tool.tables:
            groups.setdefault(self.access(code_), []).append(code_)
        primary = self.access(tool.tables[0])
        levels = [primary, *(lvl for lvl in ACCESS_LEVELS if lvl != primary)]
        levels = [lvl for lvl in levels if lvl in groups]
        if len(levels) == 1:
            text = ACCESS_LABELS[primary]
            if primary == "subscription":
                text = "Subscription only"
        else:
            parts = []
            for i, level in enumerate(levels):
                label = ACCESS_LABELS[level] if i == 0 else ACCESS_LABELS[level].lower()
                codes = groups[level]
                if len(codes) > 3:
                    parts.append(f"{label} ({len(codes)} tables)")
                else:
                    parts.append(f"{label}: {', '.join(codes)}")
            text = "; ".join(parts)
        day = self.last_refreshed(tool.tables[0])
        if primary == "free" and day and not self.is_current(day):
            text += f", last refreshed {day}"
        if tool.local:
            text += " (answered locally, no API call)"
        return text

    def main_params(self, tool: ToolDoc) -> str:
        props: dict[str, Any] = tool.schema.get("properties", {})
        required = set(tool.schema.get("required", []))
        names = [n for n in props if n in required]
        names += [n for n in props if n not in required]
        shown: list[str] = []
        dates = False
        for name in names:
            if name in MINOR_PARAMS:
                continue
            if name in ("start_date", "end_date"):
                dates = True
                continue
            shown.append(f"**{code(name)}**" if name in required else code(name))
        if dates:
            shown.append(f"{code('start_date')}/{code('end_date')}")
        if not shown:
            return "none"
        extra = len(shown) - MAX_MAIN_PARAMS
        if extra > 0:
            shown = [*shown[:MAX_MAIN_PARAMS], f"+{extra} more"]
        return ", ".join(shown)

    # ---------------------------------------------------------- README

    def readme_tools(self) -> list[str]:
        tools = self.listing.tools
        lines = [
            f"{len(tools)} tools in {len(TOOLSETS)} toolsets. "
            f"{', '.join(code(n) for n in ALWAYS_ON)} is always on; "
            "`NDL_TOOLSETS` or `--toolsets` picks the others. Bold parameters "
            "are required. *Free key* is what a free API key gets from the "
            f"tables the tool reads (catalog snapshot {self.snapshot}).",
        ]
        for name, toolset in TOOLSETS.items():
            lines += [
                "",
                f"### {name}",
                "",
                f"{cell(toolset.description)} Reference: "
                f"[docs/tools/{name}.mdx](docs/tools/{name}.mdx).",
                "",
            ]
            lines += table(
                ["Tool", "What it does", "Main parameters", "Free key"],
                [
                    [
                        code(t.name),
                        cell(t.summary),
                        self.main_params(t),
                        cell(self.free_key(t)),
                    ]
                    for t in self.by_toolset[name]
                ],
            )
        return lines

    def free_table_rows(
        self, link: Callable[[str], str], escape: Callable[[str], str]
    ) -> list[list[str]]:
        generic = {
            spec.fn.__name__
            for name in GENERIC_TOOLSETS
            if name in TOOLSETS
            for spec in TOOLSETS[name].tools
        }
        rows = []
        for entry in sorted(self.catalog.entries, key=lambda e: e.code):
            if entry.access != "free":
                continue
            # Typed tools first; ndl_query_table reads every table.
            tools = sorted(
                self.table_tools.get(entry.code, []), key=lambda t: t in generic
            )
            read_with = ", ".join(link(t) for t in tools) or code("ndl_query_table")
            day = self.last_refreshed(entry.code)
            if day is None:
                refreshed = "unknown"
            elif self.is_current(day):
                refreshed = f"{day} (current)"
            else:
                refreshed = day
            rows.append(
                [code(entry.code), escape(cell(entry.name)), read_with, refreshed]
            )
        return rows

    def free_tables(
        self, link: Callable[[str], str], escape: Callable[[str], str]
    ) -> list[str]:
        rows = self.free_table_rows(link, escape)
        counts = {
            level: sum(1 for e in self.catalog.entries if e.access == level)
            for level in ACCESS_LEVELS
        }
        summary = ", ".join(f"{counts[level]} {level}" for level in ACCESS_LEVELS)
        intro = (
            f"The catalog snapshot of {self.snapshot} has "
            f"{len(self.catalog.entries)} tables: {summary}. These are the "
            f"{len(rows)} that a free key reads in full. A table counts as "
            f"current when Nasdaq refreshed it within {STALE_AFTER_DAYS} days of "
            "the snapshot; tool results add a staleness note past that age."
        )
        lines = [escape(intro), ""]
        lines += table(
            ["Table", "Contents", "Read with", "Last refreshed by Nasdaq"], rows
        )
        return lines

    def prompts_resources(self, escape: Callable[[str], str]) -> list[str]:
        prompt_rows = []
        for prompt in self.listing.prompts:
            args = [
                f"{code(a.name)}{'' if a.required else ' (optional)'}"
                for a in prompt.arguments or []
            ]
            prompt_rows.append(
                [
                    code(prompt.name),
                    code(self.prompt_toolset.get(prompt.name, "")),
                    ", ".join(args) or "none",
                    escape(cell(prompt.description or "")),
                ]
            )
        resource_rows = [
            [code(str(r.uri)), r.mime_type or "", escape(cell(r.description or ""))]
            for r in self.listing.resources
        ]
        resource_rows += [
            [code(t.uri_template), t.mime_type or "", escape(cell(t.description or ""))]
            for t in self.listing.templates
        ]
        lines = [
            "Prompts (a prompt is offered only when its toolset is enabled):",
            "",
        ]
        lines += table(
            ["Prompt", "Toolset", "Arguments", "What it asks for"], prompt_rows
        )
        lines += ["", "Resources:", ""]
        lines += table(["URI", "Type", "Contents"], resource_rows)
        return lines

    # ------------------------------------------------------------ docs

    def overview_page(self) -> str:
        tools = self.listing.tools
        lines = [
            "---",
            'title: "Tools overview"',
            f'description: "{len(tools)} read-only tools in {len(TOOLSETS)} '
            'toolsets, plus prompts and resources."',
            "---",
            "",
            generated_note_mdx(),
            "",
            f"Every tool is read-only. {code('core')} is always on; set "
            "`NDL_TOOLSETS` (or `--toolsets`) to a comma-separated list to "
            "load fewer tools. Bold parameters are required. *Free key* is what "
            "a free API key gets from the tables the tool reads (catalog "
            f"snapshot {self.snapshot}); see [access levels](/access-levels).",
        ]
        for name, toolset in TOOLSETS.items():
            lines += [
                "",
                f"## [{name}](/tools/{name})",
                "",
                mdx(cell(toolset.description)),
                "",
            ]
            lines += table(
                ["Tool", "What it does", "Main parameters", "Free key"],
                [
                    [
                        f"[{code(t.name)}](/tools/{name})",
                        mdx(cell(t.summary)),
                        self.main_params(t),
                        mdx(cell(self.free_key(t))),
                    ]
                    for t in self.by_toolset[name]
                ],
            )
        lines += ["", "## Prompts and resources", ""]
        lines += self.prompts_resources(mdx)
        return "\n".join(lines) + "\n"

    def toolset_page(self, name: str) -> str:
        toolset = TOOLSETS[name]
        tools = self.by_toolset[name]
        enable = (
            "It is always on."
            if name in ALWAYS_ON
            else f"Load it alone (with `core`) with `NDL_TOOLSETS={name}`."
        )
        lines = [
            "---",
            f'title: "{name} toolset"',
            f'sidebarTitle: "{name}"',
            f'description: "{one_line(toolset.description).replace(chr(34), chr(39))}"',
            "---",
            "",
            generated_note_mdx(),
            "",
            f"{mdx(one_line(toolset.description))} {enable}",
            "",
        ]
        lines += table(
            ["Tool", "Free key"],
            [[code(t.name), mdx(cell(self.free_key(t)))] for t in tools],
        )
        for tool in tools:
            lines += self.tool_section(tool)
        prompts = [
            p for p in self.listing.prompts if self.prompt_toolset.get(p.name) == name
        ]
        if prompts:
            lines += ["", "## Prompts"]
            for prompt in prompts:
                lines += ["", f"### {prompt.name}", ""]
                lines.append(mdx(one_line(prompt.description or "")))
                args = prompt.arguments or []
                if args:
                    lines += [""]
                    lines += table(
                        ["Argument", "Required", "Description"],
                        [
                            [
                                code(a.name),
                                "yes" if a.required else "no",
                                mdx(cell(a.description or "")),
                            ]
                            for a in args
                        ],
                    )
        return "\n".join(lines) + "\n"

    def tool_section(self, tool: ToolDoc) -> list[str]:
        where = (
            "Answers locally, without calling Nasdaq."
            if tool.local
            else "Calls Nasdaq Data Link."
        )
        lines = [
            "",
            f"## {tool.name}",
            "",
            f"**{mdx(tool.title)}**. {mdx(tool.summary)} Read-only. {where}",
        ]
        if tool.body:
            lines += ["", mdx(tool.body)]
        lines += ["", "### Parameters", ""]
        rows = param_rows(tool.schema)
        if rows:
            lines += table(["Name", "Type", "Default", "Description"], rows)
        else:
            lines.append("None.")
        if tool.tables:
            lines += ["", "### Tables", ""]
            table_rows = []
            for code_ in tool.tables:
                entry = self.entry(code_)
                name = cell(entry.name) if entry else ""
                label = code(code_)
                if entry and entry.docs_url:
                    label = f"[{label}]({entry.docs_url})"
                day = self.last_refreshed(code_) or "unknown"
                table_rows.append(
                    [label, mdx(name), ACCESS_LABELS[self.access(code_)], day]
                )
            lines += table(
                ["Table", "Name", "Free key", "Last refreshed by Nasdaq"], table_rows
            )
        return lines


def generated_note_mdx() -> str:
    return (
        f"{{/* Generated by {SCRIPT} from the server's tool listing. "
        f"Edit the tool code, then run: uv run python {SCRIPT} */}}"
    )


# -------------------------------------------------------------- parameters


def type_text(schema: dict[str, Any]) -> tuple[str, list[Any]]:
    """A short type name and the allowed values, if the schema is an enum."""
    if "anyOf" in schema:
        parts = [s for s in schema["anyOf"] if s.get("type") != "null"]
        texts: list[str] = []
        values: list[Any] = []
        for part in parts:
            text, enum = type_text(part)
            texts.append(text)
            values += enum
        return " or ".join(dict.fromkeys(texts)), values
    kind = schema.get("type")
    if "enum" in schema:
        return "string" if kind == "string" else str(kind or "enum"), list(
            schema["enum"]
        )
    if kind == "array":
        item_text, values = type_text(schema.get("items", {}))
        return f"list of {item_text}s", values
    if kind == "integer" and ("minimum" in schema or "maximum" in schema):
        lo, hi = schema.get("minimum", ""), schema.get("maximum", "")
        return f"integer ({lo}-{hi})", []
    return str(kind or "any"), []


def default_text(name: str, schema: dict[str, Any], required: set[str]) -> str:
    if name in required:
        return "required"
    if "default" not in schema or schema["default"] is None:
        return "none"
    return code(json.dumps(schema["default"]))


def param_rows(schema: dict[str, Any]) -> list[list[str]]:
    props: dict[str, Any] = schema.get("properties", {})
    required = set(schema.get("required", []))
    rows = []
    for name, prop in props.items():
        kind, values = type_text(prop)
        description = mdx(cell(prop.get("description", "")))
        if values:
            listed = ", ".join(code(str(v)) for v in values)
            description = f"{description} One of: {listed}.".strip()
        rows.append([code(name), kind, default_text(name, prop, required), description])
    return rows


# ------------------------------------------------------------------ files


def replace_block(text: str, name: str, body: list[str], *, mdx_file: bool) -> str:
    if mdx_file:
        start, end = f"{{/* {name}:start */}}", f"{{/* {name}:end */}}"
        note = generated_note_mdx()
    else:
        start, end = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
        note = f"<!-- Generated by {SCRIPT}; do not edit by hand. -->"
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    if len(pattern.findall(text)) != 1:
        raise SystemExit(f"Expected exactly one {start} ... {end} block")
    block = "\n".join([start, note, "", *body, "", end])
    return pattern.sub(lambda _: block, text)


def docs_json(current: str) -> str:
    config = json.loads(current)
    pages = ["tools/overview", *(f"tools/{name}" for name in TOOLSETS)]
    groups = config.get("navigation", {}).get("groups", [])
    for group in groups:
        if group.get("group") == TOOLS_NAV_GROUP:
            group["pages"] = pages
            break
    else:
        raise SystemExit(f'docs.json has no "{TOOLS_NAV_GROUP}" navigation group')
    return json.dumps(config, indent=2, ensure_ascii=False) + "\n"


def render(ref: Reference) -> dict[Path, str]:
    """Map each output file to its new content."""
    out: dict[Path, str] = {}
    readme = README.read_text(encoding="utf-8")
    readme = replace_block(readme, "tools", ref.readme_tools(), mdx_file=False)
    readme = replace_block(
        readme, "free-tables", ref.free_tables(code, plain), mdx_file=False
    )
    readme = replace_block(
        readme,
        "prompts-resources",
        ref.prompts_resources(plain),
        mdx_file=False,
    )
    out[README] = readme

    access = ACCESS_PAGE.read_text(encoding="utf-8")

    def doc_link(tool_name: str) -> str:
        toolset = next(t.toolset for t in ref.listing.tools if t.name == tool_name)
        return f"[{code(tool_name)}](/tools/{toolset})"

    body = ref.free_tables(doc_link, mdx)
    out[ACCESS_PAGE] = replace_block(access, "free-tables", body, mdx_file=True)

    out[TOOLS_DIR / "overview.mdx"] = ref.overview_page()
    for name in TOOLSETS:
        out[TOOLS_DIR / f"{name}.mdx"] = ref.toolset_page(name)
    out[DOCS_JSON] = docs_json(DOCS_JSON.read_text(encoding="utf-8"))
    return out


def stale_pages(expected: dict[Path, str]) -> list[Path]:
    """Generated tool pages that no longer belong to any toolset."""
    keep = {p.name for p in expected if p.parent == TOOLS_DIR}
    return sorted(p for p in TOOLS_DIR.glob("*.mdx") if p.name not in keep)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="Change nothing; exit 1 when a generated file is out of date.",
    )
    args = parser.parse_args(argv)

    listing = anyio.run(_collect)
    expected = render(Reference(listing, Catalog.load()))
    changed = [
        path
        for path, content in expected.items()
        if not path.is_file() or path.read_text(encoding="utf-8") != content
    ]
    extra = stale_pages(expected)
    names = [str(p.relative_to(ROOT)) for p in [*changed, *extra]]
    if args.check:
        if names:
            print(f"Out of date (run: uv run python {SCRIPT}):")
            for name in names:
                print(f"  {name}")
            return 1
        print(f"Tool docs are up to date ({len(expected)} files).")
        return 0
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    for path in changed:
        path.write_text(expected[path], encoding="utf-8")
    for path in extra:
        path.unlink()
    print(f"Wrote {len(changed)} and removed {len(extra)} of the generated files.")
    for name in names:
        print(f"  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
