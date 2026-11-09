"""Structured extraction and conservative recommendations for Traderie jewels.

Only text already captured from the visible Traderie DOM is analyzed. Asking
prices and barter requests are never represented as completed-sale prices.
"""
from __future__ import annotations

import json
import re
from typing import Any

STAT_PATTERNS = {
    "ias": [
        r"(?<!\d)(\d{1,2})\s*%?\s*(?:increased\s+attack\s+speed|ias)\b",
    ],
    "enhanced_damage": [
        r"(?<!\d)(\d{1,3})\s*%?\s*enhanced\s+damage\b",
        r"(?<!\d)(\d{1,3})\s*%?\s*ed\b",
    ],
    "max_damage": [
        r"[+]?\s*(\d{1,2})\s*(?:to\s+)?maximum\s+damage\b",
        r"[+]?\s*(\d{1,2})\s*max\s+damage\b",
        r"\+\s*(\d{1,2})\s*max\b",
    ],
    "min_damage": [
        r"[+]?\s*(\d{1,2})\s*(?:to\s+)?minimum\s+damage\b",
        r"[+]?\s*(\d{1,2})\s*min\s+damage\b",
    ],
    "all_resist": [r"[+]?\s*(\d{1,2})\s*(?:%\s*)?to\s+all\s+resistances?\b"],
    "life": [r"[+]?\s*(\d{1,3})\s+to\s+life\b"],
    "fhr": [r"[+]?\s*(\d{1,2})\s*%?\s* faster\s+hit\s+recovery\b"],
    "strength": [r"[+]?\s*(\d{1,2})\s+to\s+strength\b"],
    "dexterity": [r"[+]?\s*(\d{1,2})\s+to\s+dexterity\b"],
}

def _first_match(text: str, patterns: list[str]) -> int | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None

def extract_jewel_properties(title: str, visible_text: str) -> dict[str, Any] | None:
    raw = " ".join(part for part in (title, visible_text) if part)
    if not re.search(r"\bjewel\b", raw, re.IGNORECASE):
        return None

    stats = {key: _first_match(raw, patterns) for key, patterns in STAT_PATTERNS.items()}
    stats = {key: value for key, value in stats.items() if value is not None}
    return {
        "item_type": "jewel",
        "quality_hint": next((q for q in ("rare", "magic", "unique") if re.search(rf"\b{q}\b", raw, re.I)), None),
        "stats": stats,
        "raw_text": raw[:4000],
        "extraction_version": 1,
    }

def recommend_jewel(stats: dict[str, int]) -> dict[str, Any]:
    ias = stats.get("ias", 0)
    ed = stats.get("enhanced_damage", 0)
    maxd = stats.get("max_damage", 0)
    score = 0
    reasons: list[str] = []

    if ias >= 15:
        score += 3
        reasons.append("15% IAS is a strong offensive breakpoint stat")
    elif ias:
        score += 1
        reasons.append("IAS adds offensive utility")
    if ed >= 35:
        score += 3
        reasons.append("High Enhanced Damage")
    elif ed:
        score += 1
        reasons.append("Enhanced Damage adds weapon damage")
    if maxd >= 15:
        score += 3
        reasons.append("+15 Maximum Damage is a strong damage modifier")
    elif maxd:
        score += 1
        reasons.append("Maximum Damage adds offensive value")

    if ias >= 15 and ed >= 30 and maxd >= 10:
        verdict = "high-potential physical damage jewel"
        action = "keep_and_price_check"
    elif score >= 4:
        verdict = "promising jewel; compare against similar listings"
        action = "compare_market"
    elif score >= 1:
        verdict = "situational jewel; value depends on build and demand"
        action = "review_context"
    else:
        verdict = "not enough recognized premium stats"
        action = "manual_review"

    return {
        "heuristic_score": score,
        "verdict": verdict,
        "recommended_action": action,
        "reasons": reasons,
        "confidence": "medium" if len(stats) >= 2 else "low",
        "disclaimer": "Heuristic screening only; not a market price or completed-sale valuation.",
    }

def analyze_listing(listing: dict[str, Any]) -> dict[str, Any] | None:
    title = str(listing.get("title") or "")
    visible = str(listing.get("visible_text") or "")
    extracted = extract_jewel_properties(title, visible)
    if extracted is None:
        return None

    stats = extracted["stats"]
    trade_request = listing.get("i_give_text")
    displayed_price = listing.get("asking_price_text")
    return {
        **extracted,
        "price_observation": {
            "displayed_asking_price": displayed_price or None,
            "requested_trade_text": trade_request or None,
            "price_kind": "asking_or_trade_request" if displayed_price or trade_request else "not_observed",
            "is_confirmed_sale": False,
            "numeric_estimate": None,
            "note": "Do not treat an asking price or requested barter as a completed sale.",
        },
        "recommendation": recommend_jewel(stats),
    }

def comparable_offer_summary(db, stats: dict[str, int], exclude_observation_id: int | None = None) -> dict[str, Any]:
    """Return same-stat observed asks only; never claim these are sale prices."""
    rows = db.execute(
        "SELECT observation_id, requested_trade_text, displayed_asking_price "
        "FROM jewel_analyses WHERE stats_json = ? ORDER BY observation_id DESC LIMIT 20",
        (json.dumps(stats, sort_keys=True),),
    ).fetchall()
    offers = [
        {"observation_id": row["observation_id"],
         "requested_trade_text": row["requested_trade_text"],
         "displayed_asking_price": row["displayed_asking_price"]}
        for row in rows if row["observation_id"] != exclude_observation_id
        and (row["requested_trade_text"] or row["displayed_asking_price"])
    ]
    return {
        "matching_observation_count": len(rows),
        "comparable_asking_offers": offers[:10],
        "price_estimate": None,
        "price_basis": "asking_prices_only" if offers else "insufficient_comparables",
        "warning": "These are observed asks/trade requests, not verified completed sales.",
    }
