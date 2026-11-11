"""Leave-one-out backtest for the Phase 2 rarity pricing model.

Run after benchmark_ring_prices.py has generated its JSON output:
    python benchmark_phase2_rarity.py
    python benchmark_phase2_rarity.py --input ring_price_benchmark_results.json --output phase2_rarity_backtest.json

For every Phase 2 case, each selected completed sale is held out in turn.
The remaining sales estimate the held-out sale's price at its own quality
score. This measures calibration against observed prices without using the
sale being predicted as its own anchor.

This is a historical-anchor backtest, not a guarantee of future market value.
It only evaluates the completed sales selected by the live API's Phase 2
comparable-selection logic.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
from typing import Any

from phase2_rarity_valuation import estimate_phase2_rarity_price


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _get_phase2_sales(case: dict) -> list[dict]:
    valuation = case.get("analysis_result", {}).get("valuation", {})
    if valuation.get("valuation_phase") != "phase_2_build_specific":
        return []
    rows = valuation.get("diagnostics", {}).get("selected_comparables", [])
    sales = []
    for row in rows:
        price = _number(row.get("sale_price_pskulls"))
        score = _number(row.get("quality_score"))
        weight = _number(row.get("weight")) or 1.0
        if price is None or score is None or not 0 <= score <= 100:
            continue
        sales.append({
            "observation_id": row.get("observation_id"),
            "value": price,
            "heuristic_score": score,
            "weight": weight,
        })
    return sales


def backtest_case(case: dict) -> dict:
    sales = _get_phase2_sales(case)
    predictions = []
    for index, held_out in enumerate(sales):
        training_sales = sales[:index] + sales[index + 1:]
        estimate = estimate_phase2_rarity_price(
            held_out["heuristic_score"], training_sales
        )
        predicted = _number(estimate.get("median"))
        if predicted is None:
            continue
        actual = held_out["value"]
        error = predicted - actual
        predictions.append({
            "observation_id": held_out.get("observation_id"),
            "score": held_out["heuristic_score"],
            "actual_pskulls": round(actual, 2),
            "predicted_pskulls": round(predicted, 2),
            "absolute_error_pskulls": round(abs(error), 2),
            "absolute_percentage_error": round(abs(error) / actual, 4),
            "signed_percentage_error": round(error / actual, 4),
            "training_anchor_count": len(training_sales),
        })

    errors = [p["absolute_percentage_error"] for p in predictions]
    signed = [p["signed_percentage_error"] for p in predictions]
    return {
        "case": case.get("case", "unknown"),
        "category": case.get("category"),
        "target_score": (
            case.get("analysis_result", {}).get("analysis", {})
            .get("quality_score_percent")
        ),
        "phase2_anchor_count": len(sales),
        "holdout_prediction_count": len(predictions),
        "median_absolute_percentage_error": round(median(errors), 4) if errors else None,
        "mean_absolute_percentage_error": round(sum(errors) / len(errors), 4) if errors else None,
        "median_signed_percentage_error": round(median(signed), 4) if signed else None,
        "predictions": predictions,
        "note": (
            "Not enough independent anchors for leave-one-out validation."
            if len(predictions) == 0 else None
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="ring_price_benchmark_results.json")
    parser.add_argument("--output", default="phase2_rarity_backtest.json")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Input not found: {input_path}")
        print("Run: python benchmark_ring_prices.py")
        return 1

    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read benchmark input: {exc}")
        return 1

    cases = payload.get("results", []) if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        print("Invalid benchmark JSON: expected a results array.")
        return 1

    results = [backtest_case(case) for case in cases if isinstance(case, dict)]
    eligible = [r for r in results if r["holdout_prediction_count"]]
    all_predictions = [
        p for result in eligible for p in result["predictions"]
    ]
    all_ape = [p["absolute_percentage_error"] for p in all_predictions]
    all_signed = [p["signed_percentage_error"] for p in all_predictions]

    report = {
        "benchmark": "phase2_rarity_leave_one_out",
        "input": str(input_path),
        "phase2_cases": len(results),
        "cases_with_holdout_predictions": len(eligible),
        "holdout_prediction_count": len(all_predictions),
        "overall_median_absolute_percentage_error": (
            round(median(all_ape), 4) if all_ape else None
        ),
        "overall_mean_absolute_percentage_error": (
            round(sum(all_ape) / len(all_ape), 4) if all_ape else None
        ),
        "overall_median_signed_percentage_error": (
            round(median(all_signed), 4) if all_signed else None
        ),
        "case_results": results,
        "interpretation": (
            "MAPE is the average absolute percentage error; signed error above "
            "zero means overprediction and below zero means underprediction. "
            "Small sample sizes and selected-comparable bias limit conclusions."
        ),
    }

    output_path = Path(args.output)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("Phase 2 rarity leave-one-out backtest")
    print(f"Phase 2 cases: {len(results)}")
    print(f"Cases with predictions: {len(eligible)}")
    print(f"Held-out sale predictions: {len(all_predictions)}")
    if all_predictions:
        print(f"Median absolute % error: {median(all_ape) * 100:.1f}%")
        print(f"Mean absolute % error:   {(sum(all_ape) / len(all_ape)) * 100:.1f}%")
        print(f"Median signed % error:   {median(all_signed) * 100:+.1f}%")
    else:
        print("No leave-one-out predictions; the selected sales lack enough anchors.")
    for result in results:
        mape = result["median_absolute_percentage_error"]
        mape_text = f"{mape * 100:.1f}%" if mape is not None else "n/a"
        print(
            f"  {result['case']}: anchors={result['phase2_anchor_count']}, "
            f"predictions={result['holdout_prediction_count']}, "
            f"median APE={mape_text}"
        )
    print(f"Detailed report: {output_path.resolve()}")
    print("This backtest is diagnostic; it does not certify market accuracy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
