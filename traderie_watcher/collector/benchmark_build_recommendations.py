"""Deterministic target benchmark for Blood Ring build recommendations.

Run:
    python benchmark_build_recommendations.py

This validates profile selection and target-gap reporting only. It does not
claim that heuristic fit scores or target rolls are calibrated market prices.
"""
from __future__ import annotations

import json
from pathlib import Path
from ring_analysis import build_recommendation

CASES = (
    {
        "name": "javazon_premium",
        "stats": {"fcr": 10, "mana_leech": 6, "all_resist": 11,
                  "attack_rating": 100, "dexterity": 15},
        "expected_build": "javazon",
    },
    {
        "name": "melee_premium",
        "stats": {"life_leech": 3, "strength": 5, "dexterity": 15,
                  "attack_rating": 100, "all_resist": 11},
        "expected_build": "melee",
    },
    {
        "name": "caster_premium",
        "stats": {"fcr": 10, "mana": 50, "mana_leech": 6,
                  "all_resist": 11, "lightning_resist": 30},
        "expected_build": "sorceress",
    },
    {
        "name": "es_sorceress_premium",
        "stats": {"fcr": 10, "mana": 50, "poison_resist": 30,
                  "poison_length_reduced": 25, "strength": 5, "dexterity": 15},
        "expected_build": "es_sorceress",
    },
    {
        "name": "es_sorceress_without_ring_fcr",
        "stats": {"mana": 50, "poison_resist": 30,
                  "poison_length_reduced": 25, "strength": 5, "dexterity": 15},
        "expected_build": None,
    },
    {
        "name": "weak_no_build",
        "stats": {},
        "expected_build": None,
    },
    {
        "name": "attack_rating_should_not_be_caster",
        "stats": {"attack_rating": 100},
        "forbidden_builds": {"sorceress", "general_caster"},
        "expected_build": None,
    },
)


def main() -> int:
    results = []
    failures = []
    for case in CASES:
        recommendation = build_recommendation(case["stats"])
        actual = recommendation["recommended_build"]
        expected = case.get("expected_build")
        forbidden = case.get("forbidden_builds", set())
        passed = actual == expected and actual not in forbidden
        row = {
            "name": case["name"],
            "stats": case["stats"],
            "expected_build": expected,
            "actual_build": actual,
            "fit_score": recommendation["fit_score"],
            "ranked_profiles": recommendation["ranked_profiles"],
            "target_benchmark": recommendation["target_benchmark"],
            "passed": passed,
        }
        results.append(row)
        if not passed:
            failures.append(row)
        print(f"{'PASS' if passed else 'FAIL'} {case['name']}: "
              f"expected={expected}, actual={actual}, "
              f"fit={recommendation['fit_score']}")
        if actual:
            target = recommendation["target_benchmark"]
            print(f"  target rolls met={target['completion_count']}/"
                  f"{target['target_count']}; "
                  f"below={len(target['below_target'])}; "
                  f"missing={len(target['missing'])}")

    output = {
        "benchmark": "blood_ring_build_recommendations",
        "cases": len(results),
        "passed": len(results) - len(failures),
        "failed": len(failures),
        "scope": "heuristic profile selection and target-gap reporting; not market-price calibration",
        "results": results,
    }
    output_path = Path("build_recommendation_benchmark_results.json")
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    print(f"\nResults: {output['passed']}/{output['cases']} passed")
    print(f"Saved: {output_path.resolve()}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
