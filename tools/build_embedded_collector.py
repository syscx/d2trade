#!/usr/bin/env python3
"""Generate the single-file collector bundle from its maintained source modules.

Usage:
    python tools/build_embedded_collector.py
    python tools/build_embedded_collector.py --check
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "d2_autotrader4.py"
NL = chr(10)

# Keep this list in dependency-friendly order. These source files are the
# canonical development versions; d2_autotrader4.py is generated for release.
MODULES = (
    ("jewel_analysis", "traderie_watcher/collector/jewel_analysis.py"),
    ("ring_analysis", "traderie_watcher/collector/ring_analysis.py"),
    ("valuation", "traderie_watcher/collector/valuation.py"),
    ("phase2_rarity_valuation", "traderie_watcher/collector/phase2_rarity_valuation.py"),
    ("_d2_embedded_collector_server", "traderie_watcher/collector/server.py"),
)

BEGIN_LINE = "    # BEGIN AUTO-GENERATED: embedded collector sources. Do not edit by hand."
END_LINE = "    # END AUTO-GENERATED: embedded collector sources."


def render_block() -> str:
    lines = [
        BEGIN_LINE,
        "    _embedded_sources = {",
    ]
    for module_name, relative_path in MODULES:
        source_path = ROOT / relative_path
        if not source_path.is_file():
            raise FileNotFoundError(f"Missing source module: {source_path}")
        source = source_path.read_text(encoding="utf-8")
        # JSON string literals are valid Python literals and preserve Unicode,
        # quotes, backslashes, and every source newline exactly.
        lines.append(f"        {json.dumps(module_name)}: {json.dumps(source)},")
    lines.extend(("    }", END_LINE))
    return NL.join(lines) + NL


def update_text(original: str) -> str:
    generated = render_block()
    begin = original.find(BEGIN_LINE + NL)
    if begin >= 0:
        end_marker = original.find(END_LINE + NL, begin)
        if end_marker < 0:
            raise RuntimeError("Found generated-section start but not its end marker.")
        end = end_marker + len(END_LINE) + 1
        return original[:begin] + generated + original[end:]

    # One-time migration path for PR #7's original unmarked source dictionary.
    legacy_start = original.find("    _embedded_sources = {" + NL)
    anchor = original.find("    _embedded_modules = {}", legacy_start)
    if legacy_start >= 0 and anchor >= 0:
        closing = original.rfind("    }" + NL, legacy_start, anchor)
        if closing < 0:
            raise RuntimeError("Found legacy source dictionary but not its closing brace.")
        end = closing + len("    }" + NL)
        return original[:legacy_start] + generated + original[end:]

    raise RuntimeError(
        "Could not locate the embedded collector source dictionary. "
        "Refusing to modify an unknown d2_autotrader4.py layout."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify embedded code is current without modifying files",
    )
    args = parser.parse_args()

    original = TARGET.read_text(encoding="utf-8")
    generated = update_text(original)

    if args.check:
        if generated != original:
            print(
                "Embedded collector is stale. Run "
                "'python tools/build_embedded_collector.py' and commit the result.",
                file=sys.stderr,
            )
            return 1
        print("Embedded collector is up to date.")
        return 0

    if generated == original:
        print("Embedded collector is already up to date.")
        return 0

    # newline="" prevents Windows from translating the generated LF newlines.
    with TARGET.open("w", encoding="utf-8", newline="") as output:
        output.write(generated)
    print(f"Updated d2_autotrader4.py from {len(MODULES)} source modules.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
