"""Benchmark seven synthetic Blood Rings against the local completed-sale database.

Coverage:
- 2 deterministic random rings
- 2 medium-quality rings (designed to score 45-64)
- 3 high-quality 10 FCR rings (designed to score >= 65)

Run from this directory:
    python benchmark_ring_prices.py

Requires collector/server.py running at http://127.0.0.1:8765.
Synthetic requests are read-only and do not insert observations.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

from generate_test_blood_ring import generate

API_URL = "http://127.0.0.1:8765/analyze/ring"

# The first two are genuinely randomized by the seeded generator. Fixed seeds
# make the benchmark repeatable while still exercising different stat mixes.
RANDOM_CASES = (
    ("random_1", 411),
    ("random_2", 927),
)

# Four non-FCR affixes with moderate rolls: intended to land in the middle band.
MEDIUM_CASES = (
    ("medium_1", "3% Life Stolen Per Hit\n+15 to Life\n+3 to Strength\n"
     "4% Mana Stolen Per Hit\n+10 to Dexterity\n+15% to Fire Resistance\n+35 to Mana"),
    ("medium_2", "2% Life Stolen Per Hit\n+18 to Life\n+4 to Strength\n"
     "3% Mana Stolen Per Hit\n+12 to Dexterity\n+12% to Lightning Resistance\n+40 to Mana"),
)

# All three have 10 FCR and strong complementary rolls. All Resistance is capped at 11. These are designed
# high-score examples to test the premium-comparable path.
HIGH_FCR_CASES = (
    ("high_fcr_1", "3% Life Stolen Per Hit\n+20 to Life\n+5 to Strength\n"
     "10% Faster Cast Rate\n6% Mana Stolen Per Hit\n+15 to Dexterity\n+11 to All Resistances"),
    ("high_fcr_2", "3% Life Stolen Per Hit\n+19 to Life\n+5 to Strength\n"
     "10% Faster Cast Rate\n6% Mana Stolen Per Hit\n+15 to Dexterity\n+50 to Mana"),
    ("high_fcr_3", "3% Life Stolen Per Hit\n+20 to Life\n+4 to Strength\n"
     "10% Faster Cast Rate\n6% Mana Stolen Per Hit\n+20 to All Resistances\n+30% to Fire Resistance"),
)


def post_ring(case_name: str, category: str, seed: int | None,
              title: str, visible_text: str) -> dict:
    payload = {
        "title": title,
        "visible_text": visible_text,
        "synthetic": True,
    }
    request = Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    return {
        "case": case_name,
        "category": category,
        "seed": seed,
        "generated_ring": {"title": title, "visible_text": visible_text},
        "analysis_result": result,
    }


def build_cases() -> list[tuple[str, str, int | None, str, str]]:
    cases = []
    for name, seed in RANDOM_CASES:
        ring = generate(seed=seed)  # random 1-4 affix count and random rolls
        cases.append((name, "random", seed, ring["title"], ring["visible_text"]))
    for name, visible_text in MEDIUM_CASES:
        cases.append((name, "medium_score", None,
                      "Blood Ring (SYNTHETIC TEST DATA)", visible_text))
    for name, visible_text in HIGH_FCR_CASES:
        cases.append((name, "high_score_10_fcr", None,
                      "Blood Ring (SYNTHETIC TEST DATA)", visible_text))
    return cases


def main() -> int:
    results = []
    try:
        for case in build_cases():
            results.append(post_ring(*case))
    except (URLError, HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"Could not analyze rings through {API_URL}: {exc}")
        print("Start collector/server.py first, then run this script again.")
        return 1

    output_path = Path("ring_price_benchmark_results.json")
    output_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Analyzed {len(results)} synthetic rings")
    for item in results:
        result = item["analysis_result"]
        analysis = result.get("analysis", {})
        valuation = result.get("valuation", {})
        diagnostics = valuation.get("diagnostics", {}).get("counts", {})
        print(f"\n=== {item['case']} [{item['category']}]"
              f"{f' seed={item["seed"]}' if item['seed'] is not None else ''} ===")
        print(item["generated_ring"]["visible_text"])
        print(f"Quality score: {analysis.get('quality_score_percent')}/100")
        print(f"Poor stat combination: {analysis.get('poor_stat_combination')}")
        print(f"Price: {valuation.get('low')} / {valuation.get('median')} / "
              f"{valuation.get('high')} Pskulls (low / median / high)")
        print(f"Method: {valuation.get('valuation_method')}")
        print(f"Confidence: {valuation.get('confidence')}")
        print(f"Completed-sale comparables: {valuation.get('comparable_sales')} "
              f"(eligible: {valuation.get('eligible_comparable_sales')})")
        print(f"Close matches: {diagnostics.get('close_comparables')}; "
              f"distant matches: {diagnostics.get('rejected_by_distance')}")
        for comparable in valuation.get("comparables", [])[:5]:
            print(
                "  comparable: "
                f"{comparable.get('sale_price_display')} -> "
                f"adjusted {comparable.get('estimated_contribution_pskulls')} Pskulls; "
                f"distance={comparable.get('distance')}"
            )

    output = {
        "benchmark_cases": len(results),
        "category_counts": {
            category: sum(1 for item in results if item["category"] == category)
            for category in ("random", "medium_score", "high_score_10_fcr")
        },
        "results": results,
    }
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nFull results saved to: {output_path.resolve()}")
    print("Synthetic rings were analyzed only; no database observations were added.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
