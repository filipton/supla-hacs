#!/usr/bin/env python3
"""Re-vendor supla_server/ into the Home Assistant integration.

The integration ships its own copy of the server package so it has no runtime
dependency beyond what Home Assistant already installs. That copy must stay
byte-identical to the original, minus the parts Home Assistant does not use, so
this script does the copy and verifies the result.

    python3 tools/sync_vendor.py          # copy, then check
    python3 tools/sync_vendor.py --check  # check only, exit 1 on drift
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "supla_server"
TARGET = ROOT / "custom_components" / "supla_local" / "server"

#: Not used inside Home Assistant: the REST API, its web panel and the CLI.
EXCLUDED = {"http_api.py", "app.py", "__main__.py", "web"}


def wanted() -> list[Path]:
    return sorted(
        path
        for path in SOURCE.iterdir()
        if path.suffix == ".py" and path.name not in EXCLUDED
    )


def sync() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    for path in wanted():
        shutil.copy2(path, TARGET / path.name)
    expected = {path.name for path in wanted()}
    for path in TARGET.iterdir():
        if path.name == "__pycache__":
            shutil.rmtree(path)
        elif path.name not in expected:
            path.unlink()


def check() -> int:
    problems: list[str] = []
    expected = {path.name for path in wanted()}

    for path in wanted():
        copy = TARGET / path.name
        if not copy.is_file():
            problems.append(f"missing from the vendored copy: {path.name}")
        elif not filecmp.cmp(path, copy, shallow=False):
            problems.append(f"differs from supla_server/: {path.name}")

    for path in sorted(TARGET.iterdir()):
        if path.name == "__pycache__":
            continue
        if path.name not in expected:
            problems.append(f"not in supla_server/: {path.name}")

    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    if problems:
        print(
            f"\n{len(problems)} problem(s). Run tools/sync_vendor.py to fix.",
            file=sys.stderr,
        )
        return 1
    print(f"vendored copy matches supla_server/ ({len(expected)} modules)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="verify without copying anything"
    )
    args = parser.parse_args()
    if not args.check:
        sync()
    return check()


if __name__ == "__main__":
    sys.exit(main())
