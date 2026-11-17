#!/usr/bin/env python3
"""Generate the single-file collector bundle from its maintained source modules.

Usage:
    python tools/build_embedded_collector.py       # update d2_autotrader4.py
    python tools/build_embedded_collector.py --check  # fail if generated code is stale
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "d2_autotrader4.py"

# The keys and order mirror the runtime's import dependencies.
MODULES = (
    ("jewel_analysis", "traderie_watcher/collector/jewel_analysis.py"),
    ("ring_analysis", "traderie_watcher/collector/ring_analysis.py"),
    ("valuation", "traderie_watcher/collector/valuation.py"),
    ("phase2_rarity_valuation", "traderie_watcher/collector/phase2_rarity_valuation.py"),
    ("_d2_embedded_collector_server", "traderie_watcher/collector/server.py"),
)

BEGIN_MARKER = (
    "    # BEGIN AUTO-GENERATED: embedded collector sources. "
    "Do not edit by hand.\\n"
)
END_MARKER = "    # END AUTO-GENERATED: embedded collector sources.\\n"

BLOCK_RE = re.compile(
    r"^    # BEGIN AUTO-GENERATED: embedded collector sources\\. "
    r"Do not edit by hand\\.\\n"
    r"    _embedded_sources = \\{\\n"
    r"[\\s\\S]*?"
    r"^    \\}\\n"
    r"    # END AUTO-GENERATED: embedded collector sources\\.\\n",
    re.MULTILINE,
)

# Also recognize the original unmarked dictionary so the first build is safe.
LEGACY_BLOCK_RE = re.compile(
    r"^    _embedded_sources = \\{\\n[\\s\\S]*?^    \\}\\n"
    r"(?=    _embedded_modules = \\{\\})",
    re.MULTILINE,
)


def render_block() -> str:
    entries = []
    for module_name, relative_path in MODULES:
        source_path = ROOT / relative_path
        if not source_path.is_file():
            raise FileNotFoundError(f"Missing source module: {source_path}")
        source = source_path.read_text(encoding="utf-8")
        # JSON string literals are valid Python string literals and preserve
        # every source character, including Unicode and trailing newlines.
        entries.append(f"        {json.dumps(module_name)}: {json.dumps(source)},\\n")
    return BEGIN_MARKER + "    _embedded_sources = {\\n" + "".join(entries) + (
        "    }\\n" + END_MARKER
    )


def update_text(original: str) -> str:
    block = render_block()
    if BLOCK_RE.search(original):
        return BLOCK_RE.sub(lambda _match: block, original, count=1)
    if LEGACY_BLOCK_RE.search(original):
        return LEGACY_BLOCK_RE.sub(lambda _match: block, original, count=1)
    raise RuntimeError(
        "Could not find the embedded source dictionary in d2_autotrader4.py. "
        "Refusing to modify an unknown file layout."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the embedded bundle is current without writing files",
    )
    args = parser.parse_args()

    original = TARGET.read_text(encoding="utf-8")
    generated = update_text(original)
    if args.check:
        if generated != original:
            print(
                "Embedded collector is out of date. Run "
                "'python tools/build_embedded_collector.py' and commit the result.",
                file=sys.stderr,
            )
            return 1
        print("Embedded collector is up to date.")
        return 0

    if generated == original:
        print("Embedded collector is already up to date.")
        return 0

    TARGET.write_text(generated, encoding="utf-8", newline="\\n")
    print(f"Updated {TARGET.relative_to(ROOT)} from {len(MODULES)} source modules.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
