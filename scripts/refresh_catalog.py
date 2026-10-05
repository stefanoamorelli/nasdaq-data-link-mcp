"""Re-validate the bundled table list against the live Nasdaq Data Link API.

For every selected table the script makes two documented Tables API calls with
the maintainer's key (sent in the X-Api-Token header, never in the URL):

1. ``GET /api/v3/datatables/{VENDOR}/{TABLE}/metadata`` for filters,
   primary_key, premium and status.refreshed_at.
2. ``GET /api/v3/datatables/{VENDOR}/{TABLE}.json?qopts.per_page=1`` to see what
   the key receives: rows from a non-premium table mean ``free``; rows (or zero
   rows) from a premium table mean ``sample``; HTTP 403 "no permission" means
   ``subscription``; HTTP 404 means the table is gone, so it moves from
   ``tables`` to ``known_missing``.

Access labels describe what a FREE key receives, so run this with a free key: a
premium key that subscribes to a table would make that table look like a sample.
A table the catalog marks ``sample`` although its metadata says premium=false
(SHARADAR/EVENTS serves sample tickers only) keeps its label. Names,
descriptions, notes and links are written by hand for this project and never
touched; the script stores nothing else from Nasdaq (no column lists, product
names or vendor text), and the loader rejects fields it does not know.

Requests run one at a time, at least ``--delay`` seconds apart. The key is read
from NASDAQ_DATA_LINK_API_KEY (or a .env file in the working directory).

Examples:
    uv run python scripts/refresh_catalog.py --only NDAQ/RTAT10 ZACKS/FC --dry-run
    uv run python scripts/refresh_catalog.py --access sample free
    uv run python scripts/refresh_catalog.py --all   # 2 calls per table, ~3 min
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
from dotenv import find_dotenv, load_dotenv

from nasdaq_data_link_mcp_os.catalog import ACCESS_LEVELS, CatalogEntry
from nasdaq_data_link_mcp_os.client import (
    NasdaqDataLinkClient,
    TableMetadata,
    normalize_table_code,
)
from nasdaq_data_link_mcp_os.config import Settings
from nasdaq_data_link_mcp_os.errors import (
    InvalidApiKeyError,
    MissingApiKeyError,
    NdlError,
    SubscriptionRequiredError,
    TableNotFoundError,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "nasdaq_data_link_mcp_os" / "data" / "catalog.json"
FREE_DAILY_LIMIT = 50_000  # x-ratelimit-limit reported for free keys
TRACKED_FIELDS = ("access", "refreshed_at", "filters", "primary_key")


class AuthError(Exception):
    """The key is missing or rejected: stop before anything is written."""


@dataclass
class Probe:
    code: str
    metadata: TableMetadata | None = None
    access: str | None = None  # free / sample / subscription / missing
    error: str | None = None
    notes: list[str] = field(default_factory=list)


def classify(premium: bool | None, readable: bool, current: str | None) -> str:
    """Access label for a table whose data call succeeded (``readable``) or 403'd."""
    if not readable:
        return "subscription"
    if premium:
        return "sample"
    # Metadata premium=false normally means full data, but a few tables serve a
    # fixed sample anyway; one data row cannot tell the two apart.
    return "sample" if current == "sample" else "free"


class Prober:
    def __init__(self, client: NasdaqDataLinkClient, delay: float) -> None:
        self.client = client
        self.delay = delay
        self.calls = 0
        self._last = 0.0
        self._warned_premium = False

    async def _pace(self) -> None:
        wait = self._last + self.delay - time.monotonic()
        if wait > 0:
            await anyio.sleep(wait)
        self._last = time.monotonic()
        self.calls += 1

    def _check_key_tier(self) -> None:
        limit = self.client.rate_limit.limit
        if limit and limit > FREE_DAILY_LIMIT and not self._warned_premium:
            self._warned_premium = True
            print(
                f"WARNING: this key allows {limit:,} calls a day, more than a free "
                "key. Tables it subscribes to will be labelled 'sample'.",
                file=sys.stderr,
            )

    async def probe(self, code: str, current: str | None) -> Probe:
        result = Probe(code)
        await self._pace()
        try:
            result.metadata = await self.client.get_metadata(code)
        except TableNotFoundError:
            result.access = "missing"
            return result
        except (MissingApiKeyError, InvalidApiKeyError) as exc:
            raise AuthError(str(exc)) from None
        except NdlError as exc:
            result.error = f"metadata: [{exc.kind}] {exc}"
            return result
        finally:
            self._check_key_tier()

        await self._pace()
        try:
            page = await self.client.get_table_page(
                code, [("qopts.per_page", "1")], use_cache=False
            )
        except SubscriptionRequiredError:
            readable = False
        except TableNotFoundError:
            result.access = "missing"
            return result
        except (MissingApiKeyError, InvalidApiKeyError) as exc:
            raise AuthError(str(exc)) from None
        except NdlError as exc:
            result.error = f"data: [{exc.kind}] {exc}"
            return result
        else:
            readable = True
            if not page.rows:
                result.notes.append("data call returned 0 rows")
        result.access = classify(result.metadata.premium, readable, current)
        if readable and not result.metadata.premium and current == "sample":
            result.notes.append("metadata says premium=false; 'sample' label kept")
        return result


def updated_entry(entry: dict[str, Any], probe: Probe) -> dict[str, Any]:
    """Copy of ``entry`` with the API-derived fields refreshed."""
    meta = probe.metadata
    new = dict(entry)
    if probe.access:
        new["access"] = probe.access
    if meta is None:
        return new
    if meta.refreshed_at:
        new["refreshed_at"] = meta.refreshed_at
    # Some 403 tables publish no schema (columns: []); keep the recorded one.
    if meta.columns:
        new["filters"] = meta.filters
        new["primary_key"] = meta.primary_key
    return new


def describe_changes(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    return [
        f"{name}: {old.get(name)!r} -> {new.get(name)!r}"
        for name in TRACKED_FIELDS
        if old.get(name) != new.get(name)
    ]


def render(catalog: dict[str, Any]) -> str:
    """Serialize in the bundled format: UTF-8, one table per line.

    Every entry is parsed back with the server's own loader first, which
    rejects unknown fields and access levels.
    """
    for raw in catalog["tables"]:
        CatalogEntry.from_json(raw)

    def dump(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    parts = []
    for key, value in catalog.items():
        if key == "tables":
            rows = ",\n".join(dump(entry) for entry in value)
            parts.append(f'"tables":[\n{rows}\n]')
        else:
            parts.append(f"{dump(key)}:{dump(value)}")
    return "{\n" + ",\n".join(parts) + "\n}\n"


def write_catalog(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".catalog-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def select(
    catalog: dict[str, Any], args: argparse.Namespace
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (catalog entries to refresh, codes outside the catalog to probe)."""
    entries: list[dict[str, Any]] = catalog["tables"]
    by_code = {e["code"]: e for e in entries}
    extra: list[str] = []
    if args.only:
        codes = list(dict.fromkeys(normalize_table_code(c) for c in args.only))
        chosen = [by_code[c] for c in codes if c in by_code]
        extra = [c for c in codes if c not in by_code]
    else:
        chosen = list(entries)
    if args.access:
        chosen = [e for e in chosen if e.get("access") in args.access]
    return chosen, extra


@dataclass
class Report:
    changed: dict[str, dict[str, Any]] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    unchanged: int = 0
    calls: int = 0


async def run_probes(
    settings: Settings,
    chosen: list[dict[str, Any]],
    extra: list[str],
    delay: float,
) -> Report:
    report = Report()
    async with NasdaqDataLinkClient(settings) as client:
        prober = Prober(client, delay)
        try:
            for entry in chosen:
                code = entry["code"]
                probe = await prober.probe(code, entry.get("access"))
                note = f" ({'; '.join(probe.notes)})" if probe.notes else ""
                if probe.error:
                    report.errors.append(code)
                    print(f"  ERROR    {code}: {probe.error}")
                    continue
                if probe.access == "missing":
                    report.missing.append(code)
                    print(f"  MISSING  {code}: 404, moved to known_missing")
                    continue
                new = updated_entry(entry, probe)
                diff = describe_changes(entry, new)
                if diff:
                    report.changed[code] = new
                    print(f"  CHANGED  {code}{note}")
                    for line in diff:
                        print(f"             {line}")
                else:
                    report.unchanged += 1
                    print(f"  ok       {code}: {new['access']}{note}")
            for code in extra:
                probe = await prober.probe(code, None)
                if probe.error:
                    report.errors.append(code)
                    print(f"  ERROR    {code} (not in catalog): {probe.error}")
                elif probe.access == "missing":
                    print(f"  ABSENT   {code}: not in catalog, 404 on Nasdaq")
                else:
                    print(
                        f"  NEW      {code}: not in catalog, exists "
                        f"({probe.access}); add an entry by hand"
                    )
        finally:
            report.calls = prober.calls
    return report


def apply(catalog: dict[str, Any], report: Report, *, full_run: bool) -> None:
    """Fold the probe results into ``catalog`` in place."""
    catalog["tables"] = [
        report.changed.get(e["code"], e)
        for e in catalog["tables"]
        if e["code"] not in report.missing
    ]
    if report.missing:
        known = set(catalog.get("known_missing") or [])
        catalog["known_missing"] = sorted(known | set(report.missing))
    if full_run and not report.errors:
        catalog["generated_at"] = datetime.now(UTC).date().isoformat()


def refresh(args: argparse.Namespace) -> int:
    path: Path = args.catalog
    catalog: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    chosen, extra = select(catalog, args)
    if not chosen and not extra:
        print("No table matches the selection.", file=sys.stderr)
        return 2

    load_dotenv(find_dotenv(usecwd=True), override=False)
    settings = Settings.from_env()
    if not settings.has_api_key:
        print("NASDAQ_DATA_LINK_API_KEY is not set.", file=sys.stderr)
        return 2
    settings = replace(
        settings,
        max_retries=5,
        max_concurrency=1,
        data_cache_ttl=0.0,
        metadata_cache_ttl=0.0,
    )
    total = len(chosen) + len(extra)
    print(
        f"Checking {total} table(s) with up to {2 * total} API calls, "
        f"{args.delay:g} s apart{' (dry run)' if args.dry_run else ''}."
    )
    try:
        report = anyio.run(run_probes, settings, chosen, extra, args.delay)
    except AuthError as exc:
        print(f"Stopped, nothing written: {exc}", file=sys.stderr)
        return 2

    print(
        f"\n{total} checked with {report.calls} API calls: "
        f"{len(report.changed)} changed, {report.unchanged} unchanged, "
        f"{len(report.missing)} missing, {len(report.errors)} errors."
    )
    revalidated_all = args.all and not report.errors
    if not (report.changed or report.missing or revalidated_all):
        print("Nothing to write.")
        return 1 if report.errors else 0
    apply(catalog, report, full_run=args.all)
    text = render(catalog)
    if args.dry_run:
        print(f"Dry run: catalog not written (would be {len(text.encode()):,} bytes).")
    else:
        write_catalog(path, text)
        print(f"Wrote {path} ({len(text.encode()):,} bytes).")
    return 1 if report.errors else 0


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Re-validate data/catalog.json against the live Tables API.",
        epilog="Labels describe what a free key receives; run with a free key.",
    )
    scope = parser.add_argument_group("selection (at least one)")
    scope.add_argument(
        "--only",
        nargs="+",
        metavar="CODE",
        help="Table codes to check, e.g. NDAQ/RTAT10 ZACKS/FC.",
    )
    scope.add_argument(
        "--access",
        nargs="+",
        choices=ACCESS_LEVELS,
        metavar="LEVEL",
        help="Only tables currently labelled with these levels: "
        f"{', '.join(ACCESS_LEVELS)}.",
    )
    scope.add_argument(
        "--all",
        action="store_true",
        help="Every table in the catalog (about 2 calls per table).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the changes without writing the catalog.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Minimum seconds between API calls (default 1, minimum 1).",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG,
        help="Catalog file to read and update (default: the bundled one).",
    )
    args = parser.parse_args(argv)
    if not (args.only or args.access or args.all):
        parser.error("choose tables with --only, --access or --all")
    if args.all and (args.only or args.access):
        parser.error("--all cannot be combined with --only or --access")
    if args.delay < 1.0:
        parser.error("--delay must be at least 1 second")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return refresh(args)
    except NdlError as exc:  # e.g. a malformed --only code
        print(f"[{exc.kind}] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
