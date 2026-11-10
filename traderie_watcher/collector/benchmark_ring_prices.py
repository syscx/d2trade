"""Generate three deterministic synthetic Blood Rings and price them against the local sale DB.

Run from this directory:
    python benchmark_ring_prices.py

Requires the collector server to be running at http://127.0.0.1:8765.
The server's existing completed-sale database is used; no observations are inserted.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

from generate_test_blood_ring import generate

API_URL = "http://127.0.0.1:8765/analyze/ring"
CASES = (
    ("sample_1", 101, 4),
    ("sample_2", 202, 3),
    ("sample_3", 303, 2),
)


def analyze_ring(case_name: str, seed: int, affix_count: int) -> dict:
    ring = generate(seed=seed, affix_count=affix_count)
    payload = {
        "title": ring["title"],
        "visible_text": ring["visible_text"],
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
        "seed": seed,
        "generated_ring": ring,
        "analysis_result": result,
    }


def main() -> int:
    results = []
    try:
        for case_name, seed, affix_count in CASES:
            results.append(analyze_ring(case_name, seed, affix_count))
    except (URLError, HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"Could not analyze rings through {API_URL}: {exc}")
        print("Start collector/server.py first, then run this script again.")
        return 1

    output_path = Path("ring_price_benchmark_results.json")
    output_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    for item in results:
        ring = item["generated_ring"]
        result = item["analysis_result"]
        analysis = result.get("analysis", {})
        valuation = result.get("valuation", {})
        print(f"\n=== {item['case']} (seed={item['seed']}) ===")
        print(ring["visible_text"])
        print(f"Quality score: {analysis.get('quality_score_percent')}/100")
        print(f"Poor stat combination: {analysis.get('poor_stat_combination')}")
        print(f"Price: {valuation.get('low')} / {valuation.get('median')} / "
              f"{valuation.get('high')} Pskulls (low / median / high)")
        print(f"Method: {valuation.get('valuation_method')}")
        print(f"Confidence: {valuation.get('confidence')}")
        print(f"Completed-sale comparables: {valuation.get('comparable_sales')} "
              f"(eligible: {valuation.get('eligible_comparable_sales')})")
        diagnostics = valuation.get("diagnostics", {}).get("counts", {})
        print(f"Sale diagnostics: {diagnostics}")
        for comparable in valuation.get("comparables", [])[:5]:
            print(
                "  comparable: "
                f"{comparable.get('sale_price_display')} -> "
                f"adjusted {comparable.get('estimated_contribution_pskulls')} Pskulls; "
                f"distance={comparable.get('distance')}"
            )

    print(f"\nFull results saved to: {output_path.resolve()}")
    print("Synthetic rings were analyzed only; no database observations were added.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
