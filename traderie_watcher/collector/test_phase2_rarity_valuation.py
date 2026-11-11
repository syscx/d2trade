import unittest

from phase2_rarity_valuation import (
    MARKET_CENTRAL_SHARE,
    MARKET_SCORE_CENTER,
    MARKET_SCORE_SIGMA,
    estimate_phase2_rarity_price,
    quality_rarity_index,
)


class Phase2RarityValuationTests(unittest.TestCase):
    def test_market_distribution_is_centered_at_85_with_75_to_95_central_85(self):
        self.assertEqual(MARKET_SCORE_CENTER, 85.0)
        self.assertEqual(MARKET_CENTRAL_SHARE, 0.85)
        self.assertAlmostEqual(MARKET_SCORE_SIGMA, 10.0 / 1.4395314709384563)
        self.assertAlmostEqual(quality_rarity_index(85), 1.0)

    def test_score_95_is_rare_relative_to_peak(self):
        self.assertAlmostEqual(quality_rarity_index(95), 2.819, places=2)
        self.assertGreater(quality_rarity_index(95), 1.0)

    def test_above_center_rarity_rises_with_score(self):
        # The two sides of the peak are intentionally asymmetric.
        self.assertLess(quality_rarity_index(80), quality_rarity_index(85))
        self.assertGreater(quality_rarity_index(90), quality_rarity_index(85))
        self.assertGreater(quality_rarity_index(95), quality_rarity_index(90))
        self.assertGreater(quality_rarity_index(100), quality_rarity_index(95))

    def test_actual_sale_price_is_used_as_anchor_without_fixed_currency_value(self):
        actual_sale_price = 1375.0
        result = estimate_phase2_rarity_price(85, [
            {"observation_id": 1, "value": actual_sale_price, "heuristic_score": 95.0},
        ])
        self.assertEqual(result["status"], "estimate_available")
        self.assertAlmostEqual(
            result["median"],
            actual_sale_price / quality_rarity_index(95),
        )
        self.assertEqual(result["anchors"][0]["sale_price"], actual_sale_price)

    def test_multiple_sales_use_weighted_median_of_implied_baselines(self):
        result = estimate_phase2_rarity_price(85, [
            {"observation_id": 1, "value": 100.0, "heuristic_score": 95.0},
            {"observation_id": 2, "value": 200.0, "heuristic_score": 100.0},
            {"observation_id": 3, "value": 10000.0, "heuristic_score": 85.0},
        ])
        self.assertEqual(result["anchor_count"], 3)
        self.assertLess(result["median"], 200.0)

    def test_empty_sales_do_not_invent_a_price(self):
        result = estimate_phase2_rarity_price(90, [])
        self.assertEqual(result["status"], "insufficient_anchors")
        self.assertIsNone(result["median"])


if __name__ == "__main__":
    unittest.main()
