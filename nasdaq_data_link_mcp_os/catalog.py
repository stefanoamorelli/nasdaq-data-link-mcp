"""Bundled list of Nasdaq Data Link tables (``data/catalog.json``).

Nasdaq Data Link has no search or listing endpoint for tables, so the server
ships a short list: the tables its tools read plus every table a free key reads
in full. Names, descriptions and notes are written for this project. Each entry
records what a *free* API key receives when it reads the table:

- ``free``: full data.
- ``sample``: a fixed sample, often a few tickers or an old date window.
- ``subscription``: nothing (HTTP 403) without a paid subscription.

Tables outside the list still work with the generic tools; their access is
reported as ``unknown`` unless the live metadata says the table is free.
Schemas are always read live from the metadata endpoint.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, fields
from functools import lru_cache
from importlib import resources
from typing import Any, Literal

Access = Literal["free", "sample", "subscription", "unknown"]
# The levels an entry can have; "unknown" is only for tables outside the list.
ACCESS_LEVELS: tuple[Access, ...] = ("free", "sample", "subscription")
# Readable tables rank above equally relevant tables a free key cannot read.
_ACCESS_BOOST = {"free": 5.0, "sample": 2.0, "subscription": 0.0}

ACCESS_NOTES: dict[str, str] = {
    "free": "Full data with a free API key.",
    "sample": (
        "Premium table: keys without a subscription to it receive only a fixed "
        "sample (often a few tickers or an old date window), and filters outside "
        "the sample return 0 rows."
    ),
    "subscription": (
        "Premium table: needs a paid subscription; a free key gets HTTP 403."
    ),
    "unknown": (
        "Not in the bundled table list; access depends on your key's subscriptions."
    ),
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str | None) -> set[str]:
    return set(_TOKEN_RE.findall((text or "").lower()))


@dataclass(frozen=True)
class CatalogEntry:
    code: str
    vendor: str
    name: str
    access: Access
    description: str
    notes: str | None = None
    filters: tuple[str, ...] = ()
    primary_key: tuple[str, ...] = ()
    docs_url: str | None = None
    refreshed_at: str | None = None

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> CatalogEntry:
        unknown = set(raw) - ENTRY_FIELDS
        if unknown:
            raise ValueError(f"{raw.get('code')}: unexpected fields {sorted(unknown)}")
        if raw.get("access") not in ACCESS_LEVELS:
            raise ValueError(f"{raw.get('code')}: invalid access {raw.get('access')!r}")
        return cls(
            **{
                **raw,
                "filters": tuple(raw.get("filters") or ()),
                "primary_key": tuple(raw.get("primary_key") or ()),
            }
        )

    def summary(self) -> dict[str, Any]:
        """Compact representation for search results."""
        out: dict[str, Any] = {
            "code": self.code,
            "name": self.name,
            "access": self.access,
            "description": self.description,
        }
        if self.notes:
            out["notes"] = self.notes
        if self.filters:
            out["filters"] = list(self.filters)
        if self.docs_url:
            out["docs_url"] = self.docs_url
        return out


ENTRY_FIELDS = frozenset(f.name for f in fields(CatalogEntry))


class Catalog:
    def __init__(
        self,
        entries: list[CatalogEntry],
        *,
        generated_at: str | None = None,
        known_missing: list[str] | None = None,
    ) -> None:
        self.entries = entries
        self.generated_at = generated_at
        self._by_code = {e.code: e for e in entries}
        self._missing = set(known_missing or ())

    @classmethod
    def load(cls) -> Catalog:
        return _load_bundled()

    def get(self, code: str) -> CatalogEntry | None:
        return self._by_code.get(code.strip().upper())

    def is_known_missing(self, code: str) -> bool:
        return code.strip().upper() in self._missing

    def vendors(self) -> Counter[str]:
        return Counter(e.vendor for e in self.entries)

    def search(
        self,
        query: str = "",
        *,
        access: Access | None = None,
        vendor: str | None = None,
        limit: int = 20,
    ) -> list[CatalogEntry]:
        """Rank entries by keyword overlap; readable tables win ties."""
        terms = _tokens(query)
        exact = query.strip().upper()
        vendor_up = vendor.strip().upper() if vendor else None
        scored: list[tuple[float, str, CatalogEntry]] = []
        for e in self.entries:
            if (access and e.access != access) or (vendor_up and e.vendor != vendor_up):
                continue
            score = 50.0 if exact and e.code == exact else 0.0
            score += 8 * len(terms & _tokens(e.code))
            score += 6 * len(terms & _tokens(e.name))
            score += 3 * len(terms & (_tokens(e.description) | _tokens(e.notes)))
            if terms and not score:
                continue
            scored.append((-(score + _ACCESS_BOOST[e.access]), e.code, e))
        scored.sort(key=lambda item: item[:2])
        return [item[2] for item in scored[:limit]]


@lru_cache(maxsize=1)
def _load_bundled() -> Catalog:
    raw = json.loads(
        resources.files("nasdaq_data_link_mcp_os")
        .joinpath("data/catalog.json")
        .read_text(encoding="utf-8")
    )
    return Catalog(
        [CatalogEntry.from_json(item) for item in raw["tables"]],
        generated_at=raw.get("generated_at"),
        known_missing=raw.get("known_missing"),
    )
