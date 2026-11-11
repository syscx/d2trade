"""Phase 2 quality/rarity price calibration.

The market-quality prior is centered at 85. The central 80% interval is
75..95, so sigma is derived from the normal 10th/90th percentiles.
Below the peak, quality scales value down. Above the peak, rarity creates
a premium using the inverse normal-density ratio. Actual completed sales
calibrate the market's baseline price; the prior never invents a currency
anchor by itself.
"""
from __future__ import annotations

from math import exp
from statistics import median

MARKET_SCORE_CENTER = 85.0
MARKET_CENTRAL_80_HALF_WIDTH = 10.0
NORMAL_80_Z = 1.2815515655446004
MARKET_SCORE_SIGMA = MARKET_CENTRAL_80_HALF_WIDTH / NORMAL_80_Z


def quality_rarity_index(score: float) -> float:
    """Relative price index: quality discount below 85, rarity premium above."""
    score = max(0.0, min(100.0, float(score)))
    if score <= MARKET_SCORE_CENTER:
        return max(0.05, score / MARKET_SCORE_CENTER)
    z = (score - MARKET_SCORE_CENTER) / MARKET_SCORE_SIGMA
    return exp(0.5 * z * z)


def weighted_quantile(values: list[tuple[float, float]], q: float) -> float | None:
    """Weighted quantile over (value, positive weight) pairs."""
    valid = sorted((float(v), max(0.0, float(w))) for v, w in values if w > 0)
    total = sum(w for _, w in valid)
    if not valid or total <= 0:
        return None
    threshold = min(1.0, max(0.0, float(q))) * total
    running = 0.0
    for value, weight in valid:
        running += weight
        if running >= threshold:
            return value
    return valid[-1][0]


def estimate_phase2_rarity_price(
    target_score: float,
    sales: list[dict],
) -> dict:
    """Calibrate a common baseline from sale anchors, then price target rarity.

    Each sale dict requires value, heuristic_score, and may include weight.
    A sale at score S implies baseline = sale_price / rarity_index(S).
    The weighted median baseline resists outlier sale prices.
    """
    anchors = []
    for sale in sales:
        try:
            price = float(sale["value"])
            score = float(sale["heuristic_score"])
            weight = float(sale.get("weight", 1.0))
        except (KeyError, TypeError, ValueError):
            continue
        if price <= 0 or weight <= 0 or not 0 <= score <= 100:
            continue
        index = quality_rarity_index(score)
        anchors.append({
            "observation_id": sale.get("observation_id"),
            "sale_price": price,
            "sale_quality_score": score,
            "rarity_index": index,
            "implied_base_price": price / index,
            "weight": weight,
        })

    if not anchors:
        return {
            "status": "insufficient_anchors",
            "target_quality_score": float(target_score),
            "anchor_count": 0,
            "baseline_median": None,
            "low": None, "median": None, "high": None,
            "anchors": [],
        }

    baseline_values = [(a["implied_base_price"], a["weight"]) for a in anchors]
    baseline = weighted_quantile(baseline_values, 0.50)
    base_low = weighted_quantile(baseline_values, 0.25)
    base_high = weighted_quantile(baseline_values, 0.75)
    target_index = quality_rarity_index(target_score)
    return {
        "status": "estimate_available",
        "target_quality_score": float(target_score),
        "market_score_center": MARKET_SCORE_CENTER,
        "market_central_80_range": [
            MARKET_SCORE_CENTER - MARKET_CENTRAL_80_HALF_WIDTH,
            MARKET_SCORE_CENTER + MARKET_CENTRAL_80_HALF_WIDTH,
        ],
        "normal_sigma": MARKET_SCORE_SIGMA,
        "target_rarity_index": target_index,
        "anchor_count": len(anchors),
        "baseline_median": baseline,
        "low": base_low * target_index if base_low is not None else None,
        "median": baseline * target_index,
        "high": base_high * target_index if base_high is not None else None,
        "anchors": anchors,
    }
