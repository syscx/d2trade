"""Bounded daily market-data import job."""
from pathlib import Path
import time
from local_market_evaluator import DEFAULT_DB, create_snapshot, import_records

ROOT = Path(__file__).resolve().parent
IMPORT_DIR = ROOT / "market_imports"
MAX_RUNTIME_SECONDS = 3600

def main():
    started = time.monotonic()
    IMPORT_DIR.mkdir(exist_ok=True)
    files = sorted(p for p in IMPORT_DIR.iterdir() if p.suffix.lower() in {".csv", ".json"})
    imported = rejected = failed = 0
    for path in files:
        if time.monotonic() - started >= MAX_RUNTIME_SECONDS:
            print("One-hour budget reached; remaining files deferred.")
            break
        try:
            good, bad = import_records(path, DEFAULT_DB)
            imported += good
            rejected += bad
            print(f"{path.name}: imported={good}, rejected={bad}")
        except Exception as exc:
            failed += 1
            print(f"{path.name}: FAILED: {type(exc).__name__}: {exc}")
    snapshot = create_snapshot(DEFAULT_DB)
    print(f"Daily update complete: imported={imported}, rejected={rejected}, failed_files={failed}")
    print(f"Snapshot timestamp: {snapshot['created_at']}")

if __name__ == "__main__":
    main()
