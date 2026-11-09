import unittest
from ring_analysis import extract_ring_properties, score_ring_stats
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

    def test_synthetic_generator_always_emits_fixed_blood_mods(self):
        from generate_test_blood_ring import generate
        for seed in range(100):
            item = generate(seed, affix_count=4)
            self.assertEqual(set(item["fixed_mods"]), {"life_leech", "life", "strength"})
            self.assertEqual(item["random_affix_count"], 4)
            self.assertEqual(len(item["random_affixes"]), 4)
            self.assertIn("Life Stolen Per Hit", item["visible_text"])
            self.assertIn("to Life", item["visible_text"])
            self.assertIn("to Strength", item["visible_text"])

    def test_synthetic_generator_uses_one_to_four_random_affixes(self):
        from generate_test_blood_ring import generate
        for seed in range(100):
            item = generate(seed)
            self.assertGreaterEqual(item["random_affix_count"], 1)
            self.assertLessEqual(item["random_affix_count"], 4)
            self.assertEqual(item["random_affix_count"], len(item["random_affixes"]))
            self.assertEqual(len(item["random_affixes"]), len(set(item["random_affixes"])))
            self.assertEqual(len(item["visible_text"].splitlines()), 4 + item["random_affix_count"])

    def test_user_example_ring_has_four_affixes_and_poor_combo(self):
        item = extract_ring_properties("Blood Ring",
            "1% Life Stolen Per Hit\\n+10 to Life\\n+1 to Strength\\n10% Faster Cast Rate\\n+18 to Mana\\n+13% to Fire Resistance\\n+3 to Attack Rating")
        self.assertEqual(item["random_affix_count"], 4)
        self.assertTrue(item["poor_stat_combination"])
        self.assertLess(item["quality_score_percent"], 90)
        self.assertEqual(item["stats"]["fcr"], 10)
        self.assertEqual(item["stats"]["attack_rating"], 3)

    def test_high_roll_four_affix_ring_can_reach_full_score(self):
        item = extract_ring_properties("Blood Ring",
            "3% Life Stolen Per Hit\\n+20 to Life\\n+5 to Strength\\n10% Faster Cast Rate\\n+50 to Mana\\n+30% to Fire Resistance\\n+100 to Attack Rating")
        self.assertEqual(item["quality_score_percent"], 100)

    def test_mana_leech_is_extracted_and_scored(self):
        item = extract_ring_properties("Blood Ring", "+10% Faster Cast Rate\\n6% Mana Stolen Per Hit\\n3% Life Stolen Per Hit\\n+6 to Dexterity")
        self.assertEqual(item["stats"]["mana_leech"], 6)
        self.assertEqual(item["stats"]["life_leech"], 3)
        self.assertGreaterEqual(score_ring_stats(item["stats"])[0], 7)

    def test_premium_affix_mismatch_is_explicit(self):
        from ring_analysis import ring_quality_gap
        target = {"fcr": 10, "attack_rating": 3, "fire_resist": 13, "mana": 18}
        observation_106 = {"fcr": 10, "mana_leech": 6, "life_leech": 3, "strength": 3, "dexterity": 6, "life": 15, "mana": 18}
        gap = ring_quality_gap(target, observation_106)
        self.assertEqual(gap["missing_from_target"], ["dexterity", "life", "life_leech", "mana_leech"])
        self.assertEqual(gap["mismatch_count"], 4)
        self.assertEqual(gap["penalty"], 0.48)

    def test_reduced_life_leech_weight(self):
        score, reasons = score_ring_stats({"life_leech": 3})
        self.assertEqual(score, 1)
        self.assertTrue(any("reduced weight" in reason for reason in reasons))

    def test_low_attack_rating_is_penalized(self):
        score, _ = score_ring_stats({"attack_rating": 59})
        self.assertEqual(score, -1)

    def test_attack_rating_60_to_99_is_weak_positive(self):
        score, _ = score_ring_stats({"attack_rating": 60})
        self.assertEqual(score, 0.5)

    def test_all_resistance_below_four_is_low_value(self):
        score, _ = score_ring_stats({"all_resist": 3})
        self.assertEqual(score, 0.5)

    def test_dexterity_magic_find_and_gold_find_are_parsed(self):
        item = extract_ring_properties("Rare Ring",
            "+12 to Dexterity\\n25% Better Chance of Getting Magic Items\\n80% Extra Gold from Monsters")
        self.assertEqual(item["stats"]["dexterity"], 12)
        self.assertEqual(item["stats"]["magic_find"], 25)
        self.assertEqual(item["stats"]["gold_find"], 80)

    def test_magic_find_and_gold_find_have_weak_weights(self):
        mf_score, _ = score_ring_stats({"magic_find": 25})
        gf_score, _ = score_ring_stats({"gold_find": 80})
        self.assertEqual(mf_score, 1)
        self.assertEqual(gf_score, 0.5)


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
