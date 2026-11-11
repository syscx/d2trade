import unittest

from phase2_rarity_valuation import (
    MARKET_SCORE_CENTER,
    MARKET_SCORE_SIGMA,
    estimate_phase2_rarity_price,
    quality_rarity_index,
)


class Phase2RarityValuationTests(unittest.TestCase):
    def test_market_distribution_is_centered_at_85_with_central_80_range(self):
        self.assertEqual(MARKET_SCORE_CENTER, 85.0)
        self.assertAlmostEqual(MARKET_SCORE_SIGMA, 10.0 / 1.2815515655446004)
        self.assertAlmostEqual(quality_rarity_index(85), 1.0)

    def test_score_95_is_about_2_276_times_center_rarity(self):
        self.assertAlmostEqual(quality_rarity_index(95), 2.276, places=2)

    def test_above_center_rarity_rises_symmetrically_by_distance(self):
        self.assertAlmostEqual(
            quality_rarity_index(80),
            quality_rarity_index(90),
            places=10,
        )
        self.assertGreater(quality_rarity_index(95), quality_rarity_index(90))
        self.assertGreater(quality_rarity_index(100), quality_rarity_index(95))

    def test_sale_at_95_for_10_jah_calibrates_score_85_baseline(self):
        # Price unit is intentionally abstract; callers pass PSkulls in production.
        result = estimate_phase2_rarity_price(85, [
            {"observation_id": 1, "value": 10.0, "heuristic_score": 95.0},
        ])
        self.assertEqual(result["status"], "estimate_available")
        self.assertAlmostEqual(result["median"], 10.0 / quality_rarity_index(95))
        self.assertAlmostEqual(result["median"], 4.393, places=2)

    def test_multiple_sales_use_weighted_median_of_implied_baselines(self):
        result = estimate_phase2_rarity_price(85, [
            {"observation_id": 1, "value": 10.0, "heuristic_score": 95.0},
            {"observation_id": 2, "value": 20.0, "heuristic_score": 100.0},
            {"observation_id": 3, "value": 1000.0, "heuristic_score": 85.0},
        ])
        self.assertEqual(result["anchor_count"], 3)
        # Median is resistant to the high-price outlier after quality normalization.
        self.assertLess(result["median"], 20.0)

    def test_empty_sales_do_not_invent_a_price(self):
        result = estimate_phase2_rarity_price(90, [])
        self.assertEqual(result["status"], "insufficient_anchors")
        self.assertIsNone(result["median"])


if __name__ == "__main__":
    unittest.main()
