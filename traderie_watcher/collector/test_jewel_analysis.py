import unittest

from jewel_analysis import analyze_listing, extract_jewel_properties


class JewelExtractionTests(unittest.TestCase):
    def test_extracts_three_target_stats(self):
        result = extract_jewel_properties(
            "Ruby Jewel",
            "15% Increased Attack Speed\n40% Enhanced Damage\n15 Maximum Damage"
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["stats"], {
            "ias": 15, "enhanced_damage": 40, "max_damage": 15
        })

    def test_does_not_treat_non_jewel_listing_as_jewel(self):
        self.assertIsNone(extract_jewel_properties(
            "Jah Rune", "15% Increased Attack Speed"
        ))

    def test_analysis_keeps_trade_request_separate_from_sale(self):
        result = analyze_listing({
            "title": "Ruby Jewel",
            "visible_text": "15% Increased Attack Speed\n40% Enhanced Damage\n15 Maximum Damage",
            "i_give_text": "1 Ber Rune",
            "asking_price_text": None
        })
        self.assertEqual(result["price_observation"]["requested_trade_text"], "1 Ber Rune")
        self.assertFalse(result["price_observation"]["is_confirmed_sale"])
        self.assertEqual(result["recommendation"]["recommended_action"], "keep_and_price_check")


if __name__ == "__main__":
    unittest.main()
