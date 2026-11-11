import unittest

from benchmark_phase2_rarity import backtest_case


class Phase2RarityBenchmarkTests(unittest.TestCase):
    def test_leave_one_out_holds_out_each_sale(self):
        case = {
            "case": "example",
            "category": "phase2_regression",
            "analysis_result": {
                "analysis": {"quality_score_percent": 85.0},
                "valuation": {
                    "valuation_phase": "phase_2_build_specific",
                    "diagnostics": {
                        "selected_comparables": [
                            {"observation_id": 1, "sale_price_pskulls": 100.0,
                             "quality_score": 85.0, "weight": 1.0},
                            {"observation_id": 2, "sale_price_pskulls": 200.0,
                             "quality_score": 95.0, "weight": 1.0},
                            {"observation_id": 3, "sale_price_pskulls": 300.0,
                             "quality_score": 90.0, "weight": 1.0},
                        ]
                    },
                },
            },
        }
        result = backtest_case(case)
        self.assertEqual(result["phase2_anchor_count"], 3)
        self.assertEqual(result["holdout_prediction_count"], 3)
        self.assertTrue(all(
            row["training_anchor_count"] == 2
            for row in result["predictions"]
        ))

    def test_non_phase2_case_is_not_backtested(self):
        case = {
            "case": "phase1",
            "analysis_result": {
                "valuation": {
                    "valuation_phase": "phase_1_direct_sales",
                    "diagnostics": {"selected_comparables": []},
                }
            },
        }
        result = backtest_case(case)
        self.assertEqual(result["phase2_anchor_count"], 0)
        self.assertEqual(result["holdout_prediction_count"], 0)


if __name__ == "__main__":
    unittest.main()
