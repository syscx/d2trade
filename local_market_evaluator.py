"""Conservative, evidence-backed local D2R market evaluator.

Market records are imported explicitly; this module does not scrape websites or
pretend that asking listings are completed sales. Prices are normalized to Ist.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB = Path.home() / "Desktop" / "d2_market_intelligence.db"
SUPPORTED_CATEGORIES = {
    "crafted_amulet", "crafted_ring", "crafted_gloves", "crafted_boots",
    "rare_jewel_low_level",
}
STAT_PATTERNS = {
    "fcr": r"\b(\d+)\s*%?\s*faster cast(?:ing)? rate\b|\b(\d+)\s*%?\s*fcr\b",
    "ias": r"\b(\d+)\s*%?\s*increased attack speed\b|\b(\d+)\s*%?\s*ias\b",
    "life": r"\+\s*(\d+)\s+(?:to\s+)?life\b",
    "mana": r"\+\s*(\d+)\s+(?:to\s+)?mana\b",
    "all_res": r"\+\s*(\d+)\s*%?\s*to all resistances\b",
    "fire_res": r"\+\s*(\d+)\s*%?\s*to fire resistance\b",
    "cold_res": r"\+\s*(\d+)\s*%?\s*to cold resistance\b",
    "light_res": r"\+\s*(\d+)\s*%?\s*to lightning resistance\b",
    "poison_res": r"\+\s*(\d+)\s*%?\s*to poison resistance\b",
    "strength": r"\+\s*(\d+)\s+to strength\b",
    "dexterity": r"\+\s*(\d+)\s+to dexterity\b",
    "skills": r"\+\s*(\d+)\s+to\s+(.+?)\s+skill levels\b",
    "mf": r"\b(\d+)\s*%?\s*better chance of getting magic items\b",
    "ed": r"\b(\d+)\s*%?\s*enhanced damage\b",
}

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def normalize_text(value: str) -> str:
    return " ".join((value or "").lower().split())

def extract_features(item_text: str) -> dict[str, float]:
    text = normalize_text(item_text)
    features: dict[str, float] = {}
    for name, pattern in STAT_PATTERNS.items():
        match = re.search(pattern, text, re.I)
        if match:
            number = next((g for g in match.groups() if g and g.isdigit()), None)
            if number:
                features[name] = float(number)
    return features

def infer_category(item_text: str) -> str | None:
    text = normalize_text(item_text)
    if re.search(r"\bjewel\b", text):
        level = re.search(r"required level\s*:?\s*(\d+)", text)
        if level and int(level.group(1)) <= 19 and ("rare" in text or "yellow" in text):
            return "rare_jewel_low_level"
    families = {
        "amulet": ("amulet", "amulet"),
        "ring": ("ring", "ring"),
        "gloves": ("gloves", "gloves"),
        "boots": ("boots", "boots"),
    }
    for term, (kind, _) in families.items():
        if term in text and any(x in text for x in ("crafted", "craft", "blood", "caster", "safety", "hit power")):
            return "crafted_" + kind
    return None

def connect(db_path: Path = DEFAULT_DB) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY,
            fingerprint TEXT UNIQUE NOT NULL,
            category TEXT NOT NULL,
            item_text TEXT NOT NULL,
            features_json TEXT NOT NULL,
            price_ist REAL NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('sold','listing')),
            source TEXT NOT NULL,
            platform TEXT NOT NULL DEFAULT 'unknown',
            realm TEXT NOT NULL DEFAULT 'unknown',
            ladder TEXT NOT NULL DEFAULT 'unknown',
            season TEXT NOT NULL DEFAULT 'unknown',
            observed_at TEXT NOT NULL,
            source_url TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_obs_category_status ON observations(category,status)")
    conn.commit()
    return conn

def import_records(path: Path, db_path: Path = DEFAULT_DB) -> tuple[int, int]:
    raw = path.read_text(encoding="utf-8-sig")
    records = json.loads(raw) if path.suffix.lower() == ".json" else list(csv.DictReader(raw.splitlines()))
    if isinstance(records, dict):
        records = records.get("observations", [])
    inserted = rejected = 0
    with connect(db_path) as conn:
        for row in records:
            try:
                category = str(row.get("category") or infer_category(row.get("item_text", "")) or "")
                price = float(row["price_ist"])
                status = str(row.get("status", "listing")).lower()
                source = str(row.get("source", "")).strip()
                item_text = str(row["item_text"]).strip()
                if category not in SUPPORTED_CATEGORIES or status not in {"sold", "listing"} or price <= 0 or not source or not item_text:
                    raise ValueError("missing/invalid required field")
                observed = str(row.get("observed_at") or row.get("sold_at") or utc_now())
                features = extract_features(item_text)
                stable = "|".join((category, normalize_text(item_text), str(price), status, source, observed))
                fingerprint = __import__("hashlib").sha256(stable.encode()).hexdigest()
                cursor = conn.execute("""INSERT OR IGNORE INTO observations
                    (fingerprint,category,item_text,features_json,price_ist,status,source,platform,realm,ladder,season,observed_at,source_url)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (fingerprint, category, item_text, json.dumps(features, sort_keys=True), price, status,
                     source, row.get("platform","unknown"), row.get("realm","unknown"),
                     row.get("ladder","unknown"), row.get("season","unknown"), observed, row.get("source_url","")))
                inserted += max(cursor.rowcount, 0)
            except (KeyError, TypeError, ValueError):
                rejected += 1
        conn.commit()
    return inserted, rejected

def evaluate(item_text: str, db_path: Path = DEFAULT_DB, *, include_listings: bool = False,
             min_sold_comps: int = 3) -> dict[str, Any]:
    category = infer_category(item_text)
    if not category:
        return {"status": "manual_review", "reason": "Item category or low-level jewel requirement could not be confirmed."}
    features = extract_features(item_text)
    if not features:
        return {"status": "manual_review", "category": category, "reason": "No recognized item stats; refusing to guess."}
    if not db_path.exists():
        return {"status": "insufficient_data", "category": category, "reason": "No local market database yet."}
    with connect(db_path) as conn:
        statuses = ("sold", "listing") if include_listings else ("sold",)
        marks = ",".join("?" for _ in statuses)
        rows = conn.execute(f"SELECT * FROM observations WHERE category=? AND status IN ({marks})", (category, *statuses)).fetchall()
    candidates = []
    target_keys = set(features)
    for row in rows:
        comp = json.loads(row["features_json"])
        comp_keys = set(comp)
        union = target_keys | comp_keys
        overlap = len(target_keys & comp_keys) / len(union) if union else 0
        if overlap < 0.25:
            continue
        magnitude = sum(min(features[k], comp[k]) / max(features[k], comp[k], 1) for k in target_keys & comp_keys) / max(1, len(target_keys & comp_keys))
        score = overlap * 0.75 + magnitude * 0.25
        candidates.append((score, row))
    candidates.sort(key=lambda x: x[0], reverse=True)
    sold_count = sum(row["status"] == "sold" for _, row in candidates)
    sold = [(score, row) for score, row in candidates if row["status"] == "sold"][:15]
    if len(sold) < min_sold_comps:
        return {"status": "insufficient_data", "category": category, "sold_comps": len(sold),
                "reason": f"Need at least {min_sold_comps} reasonably similar completed sales; found {len(sold)}."}
    # Similarity-weighted median: resistant to outlier listings/sales.
    prices = [row["price_ist"] for _, row in sold]
    estimate = statistics.median(prices)
    confidence = "medium" if len(sold) >= 5 and statistics.median(s for s, _ in sold) >= 0.55 else "low"
    if include_listings:
        confidence = "low"
    return {"status": "ok", "category": category, "estimate_ist": round(estimate, 2),
            "range_ist": [round(min(prices), 2), round(max(prices), 2)],
            "confidence": confidence, "sold_comps": len(sold),
            "sources": sorted({r["source"] for _, r in sold}),
            "note": "Estimate is a comparable-sales median, not a guaranteed sale price."}

def create_snapshot(db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    with connect(db_path) as conn:
        rows = conn.execute("SELECT category,status,COUNT(*) n,MAX(observed_at) latest FROM observations GROUP BY category,status").fetchall()
    snapshot = {"created_at": utc_now(), "counts": [dict(r) for r in rows]}
    out = db_path.with_name("market_snapshot_latest.json")
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    tmp.replace(out)
    return snapshot

def main() -> None:
    parser = argparse.ArgumentParser(description="Import market comps and build a local D2R market snapshot.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--import-file", type=Path, help="CSV or JSON exported market observations")
    parser.add_argument("--snapshot", action="store_true")
    args = parser.parse_args()
    if args.import_file:
        added, rejected = import_records(args.import_file, args.db)
        print(f"Imported {added} records; rejected {rejected}.")
    if args.snapshot or not args.import_file:
        print(json.dumps(create_snapshot(args.db), indent=2))

if __name__ == "__main__":
    main()
