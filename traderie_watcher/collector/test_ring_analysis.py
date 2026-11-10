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
            "1% Life Stolen Per Hit\n+10 to Life\n+1 to Strength\n10% Faster Cast Rate\n+18 to Mana\n+13% to Fire Resistance\n+3 to Attack Rating")
        self.assertEqual(item["random_affix_count"], 4)
        self.assertTrue(item["poor_stat_combination"])
        self.assertLess(item["quality_score_percent"], 90)
        self.assertEqual(item["stats"]["fcr"], 10)
        self.assertEqual(item["stats"]["attack_rating"], 3)

    def test_high_roll_four_affix_ring_can_reach_full_score(self):
        item = extract_ring_properties("Blood Ring",
            "3% Life Stolen Per Hit\n+20 to Life\n+5 to Strength\n10% Faster Cast Rate\n+50 to Mana\n+30% to Fire Resistance\n+100 to Attack Rating")
        self.assertGreater(item["quality_score_percent"], 72.38)

    def test_mana_leech_is_extracted_and_scored(self):
        item = extract_ring_properties("Blood Ring", "+10% Faster Cast Rate\n6% Mana Stolen Per Hit\n3% Life Stolen Per Hit\n+6 to Dexterity")
        self.assertEqual(item["stats"]["mana_leech"], 6)
        self.assertEqual(item["stats"]["life_leech"], 3)
        self.assertGreater(score_ring_stats(item["stats"])[0], 0)

    def test_premium_affix_mismatch_is_explicit(self):
        from ring_analysis import ring_quality_gap
        target = {"fcr": 10, "attack_rating": 3, "fire_resist": 13, "mana": 18}
        observation_106 = {"fcr": 10, "mana_leech": 6, "life_leech": 3, "strength": 3, "dexterity": 6, "life": 15, "mana": 18}
        gap = ring_quality_gap(target, observation_106)
        self.assertEqual(gap["missing_from_target"], ["dexterity", "life", "life_leech", "mana_leech"])
        self.assertEqual(gap["mismatch_count"], 4)
        self.assertEqual(gap["penalty"], 0.48)

    def test_blood_package_scores_only_from_fixed_rolls(self):
        score, _ = score_ring_stats({"life_leech": 3})
        self.assertEqual(score, 5.0)  # 1/3 of the 15-point fixed package

    def test_low_attack_rating_has_negative_roll_quality(self):
        score, reasons = score_ring_stats({"attack_rating": 3})
        self.assertEqual(score, 0.0)  # final total is floored at zero
        self.assertTrue(any("low attack rating is penalized" in reason for reason in reasons))

    def test_attack_rating_60_to_99_is_weakly_weighted(self):
        score, reasons = score_ring_stats({"attack_rating": 60})
        self.assertGreater(score, 0.0)
        self.assertLess(score, 2.0)
        self.assertTrue(any("importance 0.45" in reason for reason in reasons))

    def test_all_resistance_uses_eleven_maximum_without_elemental_penalty(self):
        from ring_analysis import _affix_roll_quality
        roll, explanation = _affix_roll_quality("all_resist", 3)
        self.assertGreater(roll, 0.0)
        self.assertIn("maximum 11", explanation)
        perfect, _ = _affix_roll_quality("all_resist", 11)
        self.assertEqual(perfect, 1.0)

    def test_single_resistance_below_fifteen_still_gets_negative_score(self):
        from ring_analysis import _affix_roll_quality
        roll, explanation = _affix_roll_quality("fire_resist", 14)
        self.assertLess(roll, 0.0)
        self.assertIn("below 15", explanation)

    def test_fire_and_lightning_resistance_weights_exceed_cold_and_poison(self):
        from ring_analysis import AFFIX_IMPORTANCE
        self.assertGreater(AFFIX_IMPORTANCE["fire_resist"], AFFIX_IMPORTANCE["cold_resist"])
        self.assertGreater(AFFIX_IMPORTANCE["lightning_resist"], AFFIX_IMPORTANCE["cold_resist"])
        self.assertGreater(AFFIX_IMPORTANCE["cold_resist"], AFFIX_IMPORTANCE["poison_resist"])

    def test_perfect_all_resistance_gets_small_bonus(self):
        from ring_analysis import _perfect_roll_bonus
        self.assertEqual(_perfect_roll_bonus("all_resist", 11), 1.0)
        self.assertEqual(_perfect_roll_bonus("all_resist", 10), 0.0)

    def test_perfect_bonus_excludes_magic_find_and_gold_find(self):
        from ring_analysis import _perfect_roll_bonus
        self.assertEqual(_perfect_roll_bonus("magic_find", 25), 0.0)
        self.assertEqual(_perfect_roll_bonus("gold_find", 100), 0.0)
        self.assertEqual(_perfect_roll_bonus("attack_rating", 100), 1.0)
        self.assertEqual(_perfect_roll_bonus("attack_rating", 120), 0.0)

    def test_generator_all_resistance_never_exceeds_eleven(self):
        from generate_test_blood_ring import generate
        for seed in range(1000):
            item = generate(seed)
            if "all_resist" in item["random_affixes"]:
                match = __import__("re").search(
                    r"\\+(\\d+) to All Resistances", item["visible_text"]
                )
                self.assertIsNotNone(match)
                self.assertLessEqual(int(match.group(1)), 11)

    def test_perfect_roll_bonus_is_applied_to_score(self):
        score, reasons = score_ring_stats({"life_leech":3, "life":20, "strength":5, "all_resist":11})
        self.assertTrue(any("perfect-roll bonus +1.00" in reason for reason in reasons))
        self.assertGreater(score, 15.0)

    def test_magic_find_and_gold_find_have_low_importance(self):
        mf_score, _ = score_ring_stats({"magic_find": 25})
        gf_score, _ = score_ring_stats({"gold_find": 80})
        self.assertLess(mf_score, 5.0)
        self.assertLess(gf_score, 2.0)
        self.assertGreater(mf_score, gf_score)

    def test_generator_never_exceeds_three_prefixes_or_suffixes(self):
        from generate_test_blood_ring import generate
        for count in range(1,5):
            for seed in range(500):
                item=generate(seed,affix_count=count)
                self.assertLessEqual(item["prefix_count"],3)
                self.assertLessEqual(item["suffix_count"],3)
                self.assertEqual(item["prefix_count"]+item["suffix_count"],count)
                if count>=2:
                    self.assertGreaterEqual(item["prefix_count"],1)
                    self.assertGreaterEqual(item["suffix_count"],1)
                if count==4:
                    self.assertIn((item["prefix_count"],item["suffix_count"]),{(1,3),(2,2),(3,1)})
                self.assertEqual(len(item["prefix_affixes"]),item["prefix_count"])
                self.assertEqual(len(item["suffix_affixes"]),item["suffix_count"])

    def test_dexterity_magic_find_and_gold_find_are_parsed(self):
        item = extract_ring_properties("Rare Ring",
            "+12 to Dexterity\n25% Better Chance of Getting Magic Items\n80% Extra Gold from Monsters")
        self.assertEqual(item["stats"]["dexterity"], 12)
        self.assertEqual(item["stats"]["magic_find"], 25)
        self.assertEqual(item["stats"]["gold_find"], 80)

    def test_replenish_life_contributes_zero_quality_points(self):
        base, _ = score_ring_stats({"life_leech": 3, "life": 20, "strength": 5})
        with_replenish, reasons = score_ring_stats({
            "life_leech": 3, "life": 20, "strength": 5, "life_replenish": 5
        })
        self.assertEqual(with_replenish, base)
        self.assertTrue(any("life_replenish=5: +0.00" in reason for reason in reasons))

    def test_quality_below_65_is_always_poor_stat_combination(self):
        item = extract_ring_properties("Blood Ring",
            "1% Life Stolen Per Hit\\n+10 to Life\\n+1 to Strength\\n+5 to Mana")
        self.assertLess(item["quality_score_percent"], 65)
        self.assertTrue(item["poor_stat_combination"])

    def test_quality_at_or_above_65_keeps_existing_poor_combo_rules(self):
        item = extract_ring_properties("Blood Ring",
            "3% Life Stolen Per Hit\\n+20 to Life\\n+5 to Strength\\n10% Faster Cast Rate")
        if item["quality_score_percent"] >= 65:
            self.assertFalse(item["poor_stat_combination"])

    def test_magic_find_and_gold_find_have_weak_weights(self):
        mf_score, _ = score_ring_stats({"magic_find": 25})
        gf_score, _ = score_ring_stats({"gold_find": 80})
        self.assertEqual(mf_score, 4.25)  # 25/25 roll × 0.20 importance × 21.25 slot
        self.assertEqual(gf_score, 1.36)  # 80/100 roll × 0.08 importance × 21.25 slot


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
