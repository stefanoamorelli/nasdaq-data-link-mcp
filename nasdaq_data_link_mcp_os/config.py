"""Runtime settings, read from environment variables."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

API_KEY_ENV = "NASDAQ_DATA_LINK_API_KEY"
DEFAULT_BASE_URL = "https://data.nasdaq.com"
SIGN_UP_URL = "https://data.nasdaq.com/sign-up"
HARD_MAX_LIMIT = 1000


def _int(env: Mapping[str, str], name: str, default: int, lo: int, hi: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from None
    if not lo <= value <= hi:
        raise ValueError(f"{name} must be between {lo} and {hi}, got {value}")
    return value


def _float(env: Mapping[str, str], name: str, default: float, lo: float) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {raw!r}") from None
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {raw!r}")
    if value < lo:
        raise ValueError(f"{name} must be >= {lo}, got {value}")
    return value


def _log_level(raw: str | None) -> str:
    level = (raw or "WARNING").strip().upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError(
            "NDL_LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR or CRITICAL, "
            f"got {raw!r}"
        )
    return level


def parse_base_url(raw: str | None) -> str:
    """Validate NDL_BASE_URL: https only, no credentials, path or query."""
    if not raw or not raw.strip():
        return DEFAULT_BASE_URL
    url = raw.strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError(f"NDL_BASE_URL must be an https:// URL, got {raw!r}")
    if parts.username or parts.password or parts.path or parts.query or parts.fragment:
        raise ValueError(
            "NDL_BASE_URL must be a bare origin such as https://data.nasdaq.com"
        )
    return url


def parse_toolsets(raw: str | None) -> tuple[str, ...] | None:
    """Parse a comma-separated toolset list. ``None`` or ``all`` means every toolset."""
    if raw is None:
        return None
    names = tuple(dict.fromkeys(n.strip().lower() for n in raw.split(",") if n.strip()))
    if not names or "all" in names:
        return None
    return names


@dataclass(frozen=True)
class Settings:
    """Server configuration.

    Every field maps to an environment variable so the server can be tuned from an
    MCP client config without code changes.
    """

    api_key: str | None = None
    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: float = 30.0
    sql_timeout_seconds: float = 50.0
    max_retries: int = 3
    max_concurrency: int = 1
    data_cache_ttl: float = 300.0
    metadata_cache_ttl: float = 6 * 3600.0
    default_limit: int = 100
    max_limit: int = HARD_MAX_LIMIT
    max_response_bytes: int = 100_000
    toolsets: tuple[str, ...] | None = None
    log_level: str = "WARNING"
    tool_deadline_seconds: float = 50.0
    http_token: str | None = None
    allowed_hosts: tuple[str, ...] = ()

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ
        key = (env.get(API_KEY_ENV) or "").strip() or None
        max_limit = _int(env, "NDL_MAX_LIMIT", HARD_MAX_LIMIT, 1, HARD_MAX_LIMIT)
        return cls(
            api_key=key,
            base_url=parse_base_url(env.get("NDL_BASE_URL")),
            timeout_seconds=_float(env, "NDL_TIMEOUT_SECONDS", 30.0, 1.0),
            # Below the 60 s request timeout many MCP clients use.
            sql_timeout_seconds=_float(env, "NDL_SQL_TIMEOUT_SECONDS", 50.0, 5.0),
            max_retries=_int(env, "NDL_MAX_RETRIES", 3, 0, 10),
            # Free keys allow 1 running + 1 queued request; premium keys allow 5.
            max_concurrency=_int(env, "NDL_MAX_CONCURRENCY", 1, 1, 5),
            data_cache_ttl=_float(env, "NDL_CACHE_TTL_SECONDS", 300.0, 0.0),
            metadata_cache_ttl=_float(
                env, "NDL_METADATA_CACHE_TTL_SECONDS", 21600.0, 0.0
            ),
            default_limit=min(
                _int(env, "NDL_DEFAULT_LIMIT", 100, 1, HARD_MAX_LIMIT), max_limit
            ),
            max_limit=max_limit,
            # About 25-35k tokens of compact JSON, under most clients' output caps.
            max_response_bytes=_int(
                env, "NDL_MAX_RESPONSE_BYTES", 100_000, 5_000, 5_000_000
            ),
            toolsets=parse_toolsets(env.get("NDL_TOOLSETS")),
            log_level=_log_level(env.get("NDL_LOG_LEVEL")),
            # Ends a tool call before the 60 s timeout common MCP clients use.
            tool_deadline_seconds=_float(env, "NDL_TOOL_DEADLINE_SECONDS", 50.0, 5.0),
            http_token=(env.get("NDL_HTTP_TOKEN") or "").strip() or None,
            allowed_hosts=tuple(
                h.strip()
                for h in (env.get("NDL_ALLOWED_HOSTS") or "").split(",")
                if h.strip()
            ),
        )
