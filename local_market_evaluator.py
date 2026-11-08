"""Affix-aware local D2R price model trained from completed sales.

Import structured affixes when OCR cannot reliably distinguish every affix.
All prices are normalized to Ist before import. No marketplace scraping.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sqlite3
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB = Path.home() / "Desktop" / "d2_market_intelligence.db"
SUPPORTED_CATEGORIES = {
    "crafted_amulet", "crafted_ring", "crafted_gloves", "crafted_boots",
    "rare_jewel_low_level",
}
# OCR convenience parser. For reliable 4-affix jewel training, provide
# affixes_json explicitly in imports, with stable affix IDs and numeric rolls.
STAT_PATTERNS = {
    "fcr_pct": r"\b(\d+)\s*%?\s*(?:faster cast(?:ing)? rate|fcr)\b",
    "ias_pct": r"\b(\d+)\s*%?\s*(?:increased attack speed|ias)\b",
    "life": r"\+\s*(\d+)\s+(?:to\s+)?life\b",
    "mana": r"\+\s*(\d+)\s+(?:to\s+)?mana\b",
    "all_res_pct": r"\+\s*(\d+)\s*%?\s*to all resistances\b",
    "fire_res_pct": r"\+\s*(\d+)\s*%?\s*to fire resistance\b",
    "cold_res_pct": r"\+\s*(\d+)\s*%?\s*to cold resistance\b",
    "light_res_pct": r"\+\s*(\d+)\s*%?\s*to lightning resistance\b",
    "poison_res_pct": r"\+\s*(\d+)\s*%?\s*to poison resistance\b",
    "strength": r"\+\s*(\d+)\s+to strength\b",
    "dexterity": r"\+\s*(\d+)\s+to dexterity\b",
    "mf_pct": r"\b(\d+)\s*%?\s*better chance of getting magic items\b",
    "enhanced_damage_pct": r"\b(\d+)\s*%?\s*enhanced damage\b",
    "max_damage": r"\+\s*(\d+)\s+to maximum damage\b",
    "min_damage": r"\+\s*(\d+)\s+to minimum damage\b",
    "attack_rating": r"\+\s*(\d+)\s+to attack rating\b",
    "life_replenish": r"replenish life\s*\+\s*(\d+)",
    "mana_after_kill": r"\+\s*(\d+)\s+mana after each kill\b",
}

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def normalize_text(value: str) -> str:
    return " ".join((value or "").lower().split())

def extract_features(item_text: str) -> dict[str, float]:
    text = normalize_text(item_text)
    result: dict[str, float] = {}
    for key, pattern in STAT_PATTERNS.items():
        match = re.search(pattern, text, re.I)
        if match:
            result[key] = float(match.group(1))
    return result

def parse_affixes(row: dict[str, Any], item_text: str) -> dict[str, float]:
    raw = row.get("affixes_json") or row.get("affixes")
    if raw:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict):
            raise ValueError("affixes_json must be a JSON object of affix_id: roll")
        values = {}
        for key, value in parsed.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values[str(key)] = float(value)
            elif isinstance(value, str):
                # Categorical affixes use 1.0 for presence; numeric values are preferred.
                try:
                    values[str(key)] = float(value)
                except ValueError:
                    values[str(key)] = 1.0
            else:
                raise ValueError(f"unsupported roll value for affix {key}")
        return values
    return extract_features(item_text)

def infer_category(item_text: str) -> str | None:
    text = normalize_text(item_text)
    if re.search(r"\bjewel\b", text):
        level = re.search(r"required level\s*:?\s*(\d+)", text)
        if level and int(level.group(1)) <= 19 and ("rare" in text or "yellow" in text):
            return "rare_jewel_low_level"
    for term in ("amulet", "ring", "gloves", "boots"):
        if term in text and any(x in text for x in ("crafted", "craft", "blood", "caster", "safety", "hit power")):
            return "crafted_" + term
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
                features = parse_affixes(row, item_text)
                if not features:
                    raise ValueError("no parsed stats; provide affixes_json")
                observed = str(row.get("observed_at") or row.get("sold_at") or utc_now())
                stable = "|".join((category, normalize_text(item_text), json.dumps(features, sort_keys=True), str(price), status, source, observed))
                fingerprint = hashlib.sha256(stable.encode()).hexdigest()
                cursor = conn.execute("""INSERT OR IGNORE INTO observations
                    (fingerprint,category,item_text,features_json,price_ist,status,source,platform,realm,ladder,season,observed_at,source_url)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (fingerprint, category, item_text, json.dumps(features, sort_keys=True), price, status,
                     source, row.get("platform","unknown"), row.get("realm","unknown"),
                     row.get("ladder","unknown"), row.get("season","unknown"), observed, row.get("source_url","")))
                inserted += max(cursor.rowcount, 0)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                rejected += 1
        conn.commit()
    return inserted, rejected

def _roll_distance(a: float, b: float, low: float, high: float) -> float:
    # Normalize a roll difference by the observed range for this affix, rather
    # than comparing raw values (e.g. +10 FCR and +10 life are not equivalent).
    span = max(high - low, 1.0)
    return min(abs(a - b) / span, 1.0)

def _distance(target: dict[str, float], comp: dict[str, float],
              ranges: dict[str, tuple[float, float]]) -> tuple[float, int]:
    keys = set(target) | set(comp)
    if not keys:
        return 1.0, 0
    per_affix = []
    shared = 0
    for key in keys:
        if key not in target or key not in comp:
            per_affix.append(0.85)  # affix identity mismatch / missing affix
            continue
        shared += 1
        low, high = ranges.get(key, (min(target[key], comp[key]), max(target[key], comp[key])))
        per_affix.append(_roll_distance(target[key], comp[key], low, high))
    # Mild penalty for comparing items with different numbers of known affixes.
    return sum(per_affix) / len(per_affix), shared

def evaluate(item_text: str, db_path: Path = DEFAULT_DB, *,
             affixes: dict[str, float] | None = None,
             category: str | None = None, top_k: int = 25) -> dict[str, Any]:
    category = category or infer_category(item_text)
    if category not in SUPPORTED_CATEGORIES:
        return {"status": "manual_review", "reason": "Item category or low-level jewel requirement could not be confirmed."}
    target = affixes or extract_features(item_text)
    if not target:
        return {"status": "manual_review", "category": category,
                "reason": "No recognized affix rolls. Provide structured affixes_json for this item."}
    if not db_path.exists():
        return {"status": "insufficient_data", "category": category, "reason": "No local market database yet."}
    with connect(db_path) as conn:
        # Only completed sales train the model. Listings never become sale labels.
        rows = conn.execute("SELECT * FROM observations WHERE category=? AND status='sold'", (category,)).fetchall()
    if not rows:
        return {"status": "insufficient_data", "category": category, "sold_records": 0,
                "reason": "No completed sales in this item family yet."}

    samples = [(json.loads(row["features_json"]), row) for row in rows]
    ranges: dict[str, tuple[float, float]] = {}
    all_keys = set().union(*(set(features) for features, _ in samples))
    for key in all_keys:
        values = [features[key] for features, _ in samples if key in features]
        ranges[key] = (min(values), max(values))

    scored = []
    for features, row in samples:
        distance, shared = _distance(target, features, ranges)
        # Exponential kernel gives the closest affix+roll profiles the greatest
        # influence while allowing non-identical rolls to contribute.
        weight = math.exp(-4.0 * distance) * (1.0 + 0.15 * shared)
        scored.append((distance, weight, shared, row))
    scored.sort(key=lambda x: x[0])
    if not scored or max(shared for _, _, shared, _ in scored) == 0:
        return {"status": "insufficient_data", "category": category,
                "reason": "No shared affix identities with completed sales; refusing to extrapolate across unrelated affixes."}
    chosen = scored[:max(1, min(top_k, len(scored)))]
    weights = [max(w, 1e-8) for _, w, _, _ in chosen]
    prices = [float(row["price_ist"]) for _, _, _, row in chosen]
    # Weighted median is robust to jackpot outliers and mislabeled sale records.
    ordered = sorted(zip(prices, weights), key=lambda pair: pair[0])
    half = sum(weights) / 2
    running = 0.0
    estimate = ordered[-1][0]
    for price, weight in ordered:
        running += weight
        if running >= half:
            estimate = price
            break

    median_distance = statistics.median(d for d, _, _, _ in chosen)
    shared_affixes = max((shared for _, _, shared, _ in chosen), default=0)
    # Confidence reflects training-set size and whether the model found related
    # affixes. It is not a guarantee; the full sample count is always exposed.
    if len(rows) >= 30 and median_distance <= 0.25 and shared_affixes >= 2:
        confidence = "high"
    elif len(rows) >= 10 and median_distance <= 0.45 and shared_affixes >= 1:
        confidence = "medium"
    else:
        confidence = "low"
    if shared_affixes == 0:
        confidence = "very_low"
    return {
        "status": "ok", "category": category, "estimate_ist": round(estimate, 2),
        "confidence": confidence, "training_sales": len(rows),
        "used_sales": len(chosen), "median_affix_distance": round(median_distance, 3),
        "matched_affixes": shared_affixes,
        "weighted_sale_range_ist": [round(min(prices), 2), round(max(prices), 2)],
        "sources": sorted({row["source"] for _, _, _, row in chosen}),
        "note": "Affix-aware estimate learned from completed sales; variable rolls are normalized by each affix's observed range. Confidence depends on sample size and similarity."
    }

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
    parser = argparse.ArgumentParser(description="Import D2R sales and build an affix-aware local price model.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--import-file", type=Path, help="CSV or JSON market observations")
    parser.add_argument("--snapshot", action="store_true")
    args = parser.parse_args()
    if args.import_file:
        added, rejected = import_records(args.import_file, args.db)
        print(f"Imported {added} records; rejected {rejected}.")
    if args.snapshot or not args.import_file:
        print(json.dumps(create_snapshot(args.db), indent=2))

if __name__ == "__main__":
    main()
