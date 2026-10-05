"""Smoke-test an MCP server over stdio using only the standard library.

Runs the given command, performs the ``initialize`` handshake, sends
``notifications/initialized``, lists the tools (following pagination) and can
call one tool. Exits non-zero with a message on stderr when anything is off.

Usage:
    python .github/scripts/mcp_stdio_smoke.py [options] -- COMMAND [ARGS...]

Example:
    python .github/scripts/mcp_stdio_smoke.py --min-tools 10 \\
        --call ndl_search_tables --arguments '{"query": "WB/DATA", "limit": 1}' \\
        -- docker run --rm -i -e NASDAQ_DATA_LINK_API_KEY nasdaq-data-link-mcp:ci
"""

from __future__ import annotations

import argparse
import json
import queue
import subprocess
import sys
import threading
import time
from typing import Any

PROTOCOL_VERSION = "2025-11-25"


class SmokeError(RuntimeError):
    pass


class StdioSession:
    def __init__(self, command: list[str], timeout: float) -> None:
        self.timeout = timeout
        self.proc = subprocess.Popen(  # noqa: S603 - command comes from the caller
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._lines: queue.Queue[str | None] = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        self._next_id = 0

    def _pump(self) -> None:
        if self.proc.stdout is None:
            return
        for line in self.proc.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def send(self, message: dict[str, Any]) -> None:
        if self.proc.stdin is None:
            raise SmokeError("server stdin is not a pipe")
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self._next_id += 1
        request_id = self._next_id
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        self.send(message)
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SmokeError(f"no response to {method} within {self.timeout:.0f}s")
            try:
                line = self._lines.get(timeout=remaining)
            except queue.Empty:
                continue
            if line is None:
                raise SmokeError(
                    f"server exited (code {self.proc.poll()}) before answering {method}"
                )
            line = line.strip()
            if not line:
                continue
            try:
                reply = json.loads(line)
            except json.JSONDecodeError:
                raise SmokeError(f"non-JSON line on stdout: {line[:200]!r}") from None
            if reply.get("id") != request_id:
                continue  # a notification or a server-initiated request
            if "error" in reply:
                raise SmokeError(f"{method} failed: {reply['error']}")
            return reply.get("result")

    def close(self) -> int:
        if self.proc.stdin is not None:
            self.proc.stdin.close()
        try:
            return self.proc.wait(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
            raise SmokeError("server did not exit after stdin was closed") from None


def run(args: argparse.Namespace) -> list[str]:
    session = StdioSession(args.command, args.timeout)
    report: list[str] = []
    try:
        init = session.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "stdio-smoke", "version": "1.0.0"},
            },
        )
        info = init.get("serverInfo") or {}
        report.append(
            f"server {info.get('name')} {info.get('version')}, "
            f"protocol {init.get('protocolVersion')}"
        )
        session.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            page = session.request("tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(page.get("tools") or [])
            cursor = page.get("nextCursor")
            if not cursor:
                break
        names = sorted(t["name"] for t in tools)
        report.append(f"{len(names)} tools: {', '.join(names)}")
        if len(names) < args.min_tools:
            raise SmokeError(
                f"expected at least {args.min_tools} tools, got {len(names)}"
            )
        missing = [n for n in args.expect_tool if n not in names]
        if missing:
            raise SmokeError(f"missing tools: {', '.join(missing)}")

        if args.call:
            result = session.request(
                "tools/call",
                {"name": args.call, "arguments": json.loads(args.arguments)},
            )
            if result.get("isError"):
                raise SmokeError(f"{args.call} returned an error: {result}")
            structured = result.get("structuredContent")
            summary = json.dumps(structured)[:300] if structured else "no structured"
            report.append(f"{args.call} -> {summary}")
    finally:
        code = session.close()
    if code != 0:
        raise SmokeError(f"server exited with code {code}")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--min-tools", type=int, default=1)
    parser.add_argument("--expect-tool", action="append", default=[])
    parser.add_argument("--call", help="Tool to call after listing tools.")
    parser.add_argument("--arguments", default="{}", help="JSON arguments for --call.")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("give the server command after --")
    try:
        report = run(args)
    except SmokeError as exc:
        sys.stderr.write(f"MCP stdio smoke test FAILED: {exc}\n")
        return 1
    sys.stdout.write("MCP stdio smoke test passed\n")
    for line in report:
        sys.stdout.write(f"  {line}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
