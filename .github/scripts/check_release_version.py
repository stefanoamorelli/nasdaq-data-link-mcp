"""Check that a release tag matches the versions in pyproject.toml and server.json.

Usage:
    python .github/scripts/check_release_version.py v2.0.0

Exits non-zero when the tag is not ``v<version>``, or when server.json (its
``version``, the PyPI package version or the OCI image tag) disagrees with
pyproject.toml. On GitHub Actions it also writes ``version=<version>`` to
``$GITHUB_OUTPUT``.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def problems(tag: str) -> tuple[str, list[str]]:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        version = str(tomllib.load(fh)["project"]["version"])
    found: list[str] = []
    if tag != f"v{version}":
        found.append(f"tag {tag!r} does not match pyproject version 'v{version}'")
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    if server.get("version") != version:
        found.append(f"server.json version is {server.get('version')!r}")
    # The MCP Registry verifies PyPI ownership through this line in the
    # package description (README.md); a release without it cannot register.
    marker = f"mcp-name: {server.get('name')}"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if not re.search(re.escape(marker) + r"(\s|-->)", readme):
        found.append(f"README.md lacks the line '<!-- {marker} -->'")
    for package in server.get("packages", []):
        kind = package.get("registryType")
        identifier = str(package.get("identifier", ""))
        if kind == "oci":
            if not identifier.endswith(f":{version}"):
                found.append(f"OCI image {identifier!r} is not tagged :{version}")
        elif package.get("version") != version:
            found.append(
                f"{kind} package {identifier!r} has version {package.get('version')!r}"
            )
    return version, found


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        sys.stderr.write("usage: check_release_version.py <tag>\n")
        return 2
    version, found = problems(argv[0].strip())
    for problem in found:
        sys.stderr.write(f"::error::{problem}\n")
    if found:
        return 1
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as fh:
            fh.write(f"version={version}\n")
    sys.stdout.write(f"Release {argv[0]} matches version {version}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
