import unittest
from ring_analysis import extract_ring_properties
from valuation import format_pskull_value, rune_bundle_value_pskulls

class BloodRingTests(unittest.TestCase):
    def test_extracts_10_fcr_blood_ring(self):
        item = extract_ring_properties("Blood Ring", "10% Faster Cast Rate\n3% Life Stolen Per Hit\n+18 to Life\n+5 to Strength\n+27% Fire Resist")
        self.assertEqual(item["craft_type"], "blood_candidate")
        self.assertEqual(item["stats"]["fcr"], 10)
        self.assertTrue(item["fcr_valid_for_blood_ring"])

    def test_blood_ring_without_fcr_is_valid(self):
        item = extract_ring_properties("Blood Ring", "3% Life Stolen Per Hit\n+18 to Life")
        self.assertEqual(item["craft_type"], "blood_candidate")
        self.assertNotIn("fcr", item["stats"])

    def test_invalid_fcr_not_treated_as_blood_ring_roll(self):
        item = extract_ring_properties("Blood Ring", "8% Faster Cast Rate\n3% Life Stolen Per Hit")
        self.assertEqual(item["craft_type"], "unknown_or_other")
        self.assertFalse(item["fcr_valid_for_blood_ring"])

    def test_non_ring_is_ignored(self):
        self.assertIsNone(extract_ring_properties("Jah Rune", "10% Faster Cast Rate"))

    def test_synthetic_generator_uses_at_most_four_random_affixes(self):
        from generate_test_blood_ring import generate
        for seed in range(100):
            item = generate(seed)
            self.assertGreaterEqual(item["random_affix_count"], 1)
            self.assertLessEqual(item["random_affix_count"], 4)
            self.assertEqual(item["random_affix_count"], len(item["random_affixes"]))
            self.assertEqual(len(item["random_affixes"]), len(set(item["random_affixes"])))
            self.assertEqual(len(item["visible_text"].splitlines()), 4 + item["random_affix_count"])

class RuneValueDisplayTests(unittest.TestCase):
    def test_values_above_two_ist_show_remainder_in_pskulls(self):
        self.assertEqual(format_pskull_value(39), "2 Ist + 9 Pskulls")
        self.assertEqual(format_pskull_value(45), "3 Ist")

    def test_two_ist_threshold_keeps_compact_format(self):
        self.assertEqual(format_pskull_value(30), "2 Ist")
        self.assertEqual(format_pskull_value(29), "29 Pskulls")

    def test_user_rune_rates_use_mixed_display(self):
        result = rune_bundle_value_pskulls([
            {"rune": "Ist", "quantity": 2},
            {"rune": "Perfect Skull", "quantity": 9},
        ])
        self.assertEqual(result["value_pskulls"], 39)
        self.assertEqual(result["display"], "2 Ist + 9 Pskulls")


if __name__ == "__main__":
    unittest.main()
