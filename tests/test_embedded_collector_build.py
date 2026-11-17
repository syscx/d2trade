"""Regression tests for the generated single-file collector bundle."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_embedded_collector_bundle_is_current() -> None:
    result = subprocess.run(
        [sys.executable, "tools/build_embedded_collector.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
