import re
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


    def test_merged_blood_life_leech_and_strength_retain_random_affix_value(self):
        item = extract_ring_properties("Blood Ring",
            "3% Life Stolen Per Hit\n+5 to Strength\n"
            "2% Life Stolen Per Hit\n+18 to Strength")
        self.assertEqual(item["stats"]["life_leech"], 5)
        self.assertEqual(item["stats"]["strength"], 23)
        score, reasons = score_ring_stats(item["stats"])
        self.assertTrue(any("life_leech affix=2" in reason for reason in reasons))
        self.assertTrue(any("strength affix=18" in reason for reason in reasons))
        self.assertGreater(score, 30)

    def test_six_percent_mana_leech_is_a_full_roll(self):
        item = extract_ring_properties("Blood Ring",
            "1% Life Stolen Per Hit\n+10 to Life\n+1 to Strength\n"
            "6% Mana Stolen Per Hit")
        self.assertEqual(item["stats"]["mana_leech"], 6)
        score, reasons = score_ring_stats(item["stats"])
        self.assertTrue(any("mana_leech affix=6" in reason and "21.25" in reason
                            for reason in reasons))

    def test_premium_melee_example_scores_attack_rating_dex_strength_and_mpk(self):
        item = extract_ring_properties("Blood Ring",
            "1% Life Stolen Per Hit\n+10 to Life\n+23 to Strength\n"
            "+116 to Attack Rating\n+15 to Dexterity\n"
            "+1 to Mana After Each Kill")
        self.assertEqual(item["stats"]["attack_rating"], 116)
        self.assertEqual(item["stats"]["strength"], 23)
        self.assertEqual(item["stats"]["dexterity"], 15)
        self.assertEqual(item["stats"]["mana_per_kill"], 1)
        self.assertGreaterEqual(item["quality_score_percent"], 65)
        from ring_analysis import build_demand_analysis
        demand = build_demand_analysis(item["stats"])
        self.assertIn("attack_rating", demand["profiles"]["melee"]["useful_stats"])
        self.assertIn("strength", demand["profiles"]["melee"]["useful_stats"])
        self.assertIn("dexterity", demand["profiles"]["melee"]["useful_stats"])
        self.assertGreater(demand["profiles"]["melee"]["score"], 90.0)

    def test_attack_rating_116_is_near_maximum_roll(self):
        from ring_analysis import _affix_roll_quality
        quality, explanation = _affix_roll_quality("attack_rating", 116)
        self.assertGreaterEqual(quality, 0.93)
        self.assertIn("60 to 120", explanation)

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

    def test_attack_rating_uses_normalized_roll_without_penalty(self):
        score, reasons = score_ring_stats({"attack_rating": 3}, blood_craft=False)
        self.assertAlmostEqual(score, 3 / 120 * 21.25, places=2)
        self.assertTrue(any("normalized against maximum 120" in reason for reason in reasons))

    def test_attack_rating_60_is_half_of_one_random_slot(self):
        score, reasons = score_ring_stats({"attack_rating": 60}, blood_craft=False)
        self.assertEqual(score, 10.625)
        self.assertTrue(any("normalized against maximum 120" in reason for reason in reasons))

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

    def test_perfect_all_resistance_uses_one_full_slot(self):
        score, _ = score_ring_stats({"all_resist": 11}, blood_craft=False)
        self.assertEqual(score, 21.25)

    def test_perfect_roll_has_no_bonus_outside_four_slot_budget(self):
        self.assertEqual(score_ring_stats({"attack_rating": 120}, blood_craft=False)[0], 21.25)

    def test_generator_all_resistance_never_exceeds_eleven(self):
        from generate_test_blood_ring import generate
        for seed in range(1000):
            item = generate(seed)
            if "all_resist" in item["random_affixes"]:
                match = re.search(
                    r"\+(\d+) to All Resistances", item["visible_text"]
                )
                self.assertIsNotNone(match)
                self.assertLessEqual(int(match.group(1)), 11)

    def test_random_affix_points_never_exceed_one_slot(self):
        score, _ = score_ring_stats({"life_leech":3, "life":20, "strength":5, "all_resist":11})
        self.assertEqual(score, 36.25)

    def test_magic_find_and_gold_find_use_roll_quality(self):
        mf_score, _ = score_ring_stats({"magic_find": 25}, blood_craft=False)
        gf_score, _ = score_ring_stats({"gold_find": 80}, blood_craft=False)
        self.assertEqual(mf_score, 21.25)
        self.assertEqual(gf_score, 17.0)

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
        self.assertTrue(any("life_replenish affix=5" in reason and "+0.00/21.25" in reason for reason in reasons))

    def test_quality_below_65_is_always_poor_stat_combination(self):
        item = extract_ring_properties("Blood Ring",
            "1% Life Stolen Per Hit\n+10 to Life\n+1 to Strength\n+5 to Mana")
        self.assertLess(item["quality_score_percent"], 65)
        self.assertTrue(item["poor_stat_combination"])

    def test_quality_at_or_above_65_keeps_existing_poor_combo_rules(self):
        item = extract_ring_properties("Blood Ring",
            "3% Life Stolen Per Hit\n+20 to Life\n+5 to Strength\n10% Faster Cast Rate")
        if item["quality_score_percent"] >= 65:
            self.assertFalse(item["poor_stat_combination"])

    def test_magic_find_and_gold_find_use_roll_quality_not_market_importance(self):
        mf_score, _ = score_ring_stats({"magic_find": 25}, blood_craft=False)
        gf_score, _ = score_ring_stats({"gold_find": 80}, blood_craft=False)
        self.assertEqual(mf_score, 21.25)
        self.assertEqual(gf_score, 17.0)


class BuildDemandTests(unittest.TestCase):
    def test_broad_premium_ring_has_multi_build_demand(self):
        from ring_analysis import build_demand_analysis
        demand = build_demand_analysis({
            "fcr": 10, "strength": 5, "all_resist": 11,
            "dexterity": 15, "life_leech": 3, "life": 20,
        })
        self.assertGreaterEqual(demand["viable_profile_count"], 2)
        self.assertIn(demand["demand_tier"], {"multi_build", "broad"})
        self.assertGreaterEqual(demand["best_score"], 45)

    def test_attack_rating_is_not_a_sorceress_priority(self):
        from ring_analysis import build_demand_analysis
        with_ar = build_demand_analysis({"attack_rating": 100})
        without_ar = build_demand_analysis({})
        self.assertLess(with_ar["profiles"]["sorceress"]["score"], 1.0)
        self.assertGreater(with_ar["profiles"]["javazon"]["score"],
                           with_ar["profiles"]["sorceress"]["score"])
        self.assertGreater(with_ar["profiles"]["melee"]["score"],
                           with_ar["profiles"]["sorceress"]["score"])

    def test_fcr_and_all_resist_improve_caster_profiles(self):
        from ring_analysis import build_demand_analysis
        demand = build_demand_analysis({"fcr": 10, "all_resist": 11, "mana": 50})
        self.assertGreater(demand["profiles"]["sorceress"]["score"], 0)
        self.assertGreater(demand["profiles"]["general_caster"]["score"], 0)

    def test_empty_stats_have_no_viable_build_profiles(self):
        from ring_analysis import build_demand_analysis
        demand = build_demand_analysis({})
        self.assertEqual(demand["viable_profile_count"], 0)
        self.assertEqual(demand["demand_tier"], "weak")



class BuildRecommendationTests(unittest.TestCase):
    def test_javazon_target_recommends_javazon(self):
        from ring_analysis import build_recommendation
        result = build_recommendation({
            "fcr": 10, "mana_leech": 6, "all_resist": 11,
            "attack_rating": 100, "dexterity": 15,
        })
        self.assertEqual(result["recommended_build"], "javazon")
        self.assertGreaterEqual(result["fit_score"], 45)
        self.assertGreater(result["target_benchmark"]["completion_count"], 0)

    def test_melee_target_recommends_melee(self):
        from ring_analysis import build_recommendation
        result = build_recommendation({
            "life_leech": 3, "strength": 5, "dexterity": 15,
            "attack_rating": 100, "all_resist": 11,
        })
        self.assertEqual(result["recommended_build"], "melee")

    def test_caster_target_recommends_caster_audience(self):
        from ring_analysis import build_recommendation
        result = build_recommendation({
            "fcr": 10, "mana": 50, "mana_per_kill": 1,
            "all_resist": 11, "life": 20,
        })
        self.assertIn(result["recommended_build"], {"sorceress", "general_caster"})

    def test_no_meaningful_stats_has_no_recommendation(self):
        from ring_analysis import build_recommendation
        result = build_recommendation({})
        self.assertIsNone(result["recommended_build"])
        # The best candidate's target gaps remain visible for diagnostics,
        # even though the ring is not eligible for a recommendation.
        self.assertEqual(result["target_benchmark"]["target_count"], 5)
        self.assertEqual(result["target_benchmark"]["completion_count"], 0)
        self.assertEqual(len(result["target_benchmark"]["missing"]), 5)

    def test_target_benchmark_reports_missing_and_below_rolls(self):
        from ring_analysis import build_recommendation
        # Strong enough to recommend Javazon, but deliberately omit its
        # attack-rating target so the report must expose a target gap.
        result = build_recommendation({
            "fcr": 10, "mana_leech": 6, "all_resist": 11, "dexterity": 15,
        })
        self.assertEqual(result["recommended_build"], "javazon")
        benchmark = result["target_benchmark"]
        self.assertTrue(benchmark["missing"] or benchmark["below_target"])
        self.assertIn("attack_rating", [item["stat"] for item in benchmark["missing"]])



class EnergyShieldSorceressTests(unittest.TestCase):
    def test_extracts_poison_length_reduction(self):
        item = extract_ring_properties("Rare Ring",
            "10% Faster Cast Rate\n+50 to Mana\nPoison Length Reduced by 25%")
        self.assertEqual(item["stats"]["poison_length_reduced"], 25)

    def test_es_sorceress_recommended_for_fcr_mana_poison_defense_ring(self):
        from ring_analysis import build_recommendation
        result = build_recommendation({
            "fcr": 10, "mana": 50, "poison_resist": 30,
            "poison_length_reduced": 25, "strength": 5, "dexterity": 15,
        })
        self.assertEqual(result["recommended_build"], "es_sorceress")
        self.assertEqual(result["target_benchmark"]["target_count"], 6)
        self.assertEqual(result["target_benchmark"]["completion_count"], 6)

    def test_es_sorceress_requires_ten_fcr_on_ring(self):
        from ring_analysis import build_demand_analysis
        stats = {"mana": 50, "poison_resist": 30,
                 "poison_length_reduced": 25, "strength": 5, "dexterity": 15}
        result = build_demand_analysis(stats)
        self.assertEqual(result["profiles"]["es_sorceress"]["score"], 0.0)
        self.assertIn("blocked_reason", result["profiles"]["es_sorceress"])


    def test_sparse_affixes_do_not_force_a_build_recommendation(self):
        from ring_analysis import build_recommendation
        result = build_recommendation({
            "mana": 50, "poison_resist": 30,
            "poison_length_reduced": 25, "strength": 5, "dexterity": 15,
        })
        self.assertIsNone(result["recommended_build"])
        self.assertLess(result["target_coverage"], 0.60)

    def test_es_target_reports_missing_poison_defense(self):
        from ring_analysis import build_recommendation
        result = build_recommendation({
            "fcr": 10, "mana": 50, "strength": 5, "dexterity": 15,
        })
        if result["recommended_build"] == "es_sorceress":
            missing = {item["stat"] for item in result["target_benchmark"]["missing"]}
            self.assertTrue({"poison_resist", "poison_length_reduced"} & missing)

class ClassSpecificBuildProfileTests(unittest.TestCase):
    def test_caster_does_not_value_life_or_mana_leech(self):
        from ring_analysis import build_demand_analysis
        demand = build_demand_analysis({
            "fcr": 10, "mana": 50, "life_leech": 3, "mana_leech": 6,
            "all_resist": 11,
        })
        for profile in ("sorceress", "general_caster", "es_sorceress"):
            self.assertNotIn("life_leech", demand["profiles"][profile]["useful_stats"])
            self.assertNotIn("mana_leech", demand["profiles"][profile]["useful_stats"])

    def test_mana_per_kill_ring_affix_maximum_is_one(self):
        from ring_analysis import _affix_roll_quality
        roll, explanation = _affix_roll_quality("mana_per_kill", 1)
        self.assertEqual(roll, 1.0)
        self.assertIn("normalized against 1", explanation)

    def test_mana_per_kill_is_parsed_and_supports_caster(self):
        item = extract_ring_properties("Rare Ring",
            "+10% Faster Cast Rate\n+50 to Mana\n+1 Mana after Each Kill")
        self.assertEqual(item["stats"]["mana_per_kill"], 1)
        from ring_analysis import build_demand_analysis
        demand = build_demand_analysis(item["stats"])
        self.assertGreater(demand["profiles"]["sorceress"]["score"], 0)

    def test_lightning_javazon_prefers_lightning_over_fire_resistance(self):
        from ring_analysis import build_demand_analysis
        lightning = build_demand_analysis({
            "fcr": 10, "mana_leech": 6, "lightning_resist": 30,
            "fire_resist": 30, "all_resist": 11,
        })
        profile = lightning["profiles"]["javazon"]
        self.assertIn("lightning_resist", profile["useful_stats"])
        self.assertNotIn("fire_resist", profile["useful_stats"])

    def test_build_recommendations_overlap(self):
        from ring_analysis import build_recommendation
        result = build_recommendation({
            "fcr": 10, "life_leech": 3, "mana_leech": 6,
            "strength": 5, "dexterity": 15, "all_resist": 11,
        })
        builds = {item["build"] for item in result["recommendations"]}
        self.assertGreaterEqual(len(builds), 2)


class DirectionalComparablePenaltyTests(unittest.TestCase):
    def test_target_stronger_than_sale_has_no_directional_penalty(self):
        from server import directional_sale_penalty
        result = directional_sale_penalty(72, 55)
        self.assertEqual(result["weaker_by"], 0.0)
        self.assertEqual(result["penalty"], 1.0)

    def test_target_up_to_ten_points_weaker_has_no_directional_penalty(self):
        from server import directional_sale_penalty
        result = directional_sale_penalty(60, 70)
        self.assertEqual(result["excess"], 0.0)
        self.assertEqual(result["penalty"], 1.0)

    def test_target_more_than_ten_points_weaker_is_penalized(self):
        from server import directional_sale_penalty
        result = directional_sale_penalty(60, 80)
        self.assertEqual(result["weaker_by"], 20.0)
        self.assertEqual(result["excess"], 10.0)
        self.assertLess(result["penalty"], 1.0)

    def test_penalty_grows_as_sale_becomes_stronger_than_target(self):
        from server import directional_sale_penalty
        moderate = directional_sale_penalty(60, 75)["penalty"]
        large = directional_sale_penalty(60, 90)["penalty"]
        self.assertLess(large, moderate)



class UserObservationRegressionTests(unittest.TestCase):
    def test_three_random_affixes_leave_fourth_slot_empty(self):
        score, reasons = score_ring_stats({
            "life_leech": 3, "life": 20, "strength": 5,
            "attack_rating": 120, "min_damage": 9, "dexterity": 15,
        })
        self.assertEqual(score, 78.75)
        self.assertEqual(sum("Empty random affix slot" in r for r in reasons), 1)

    def test_observation_147_score_matches_15_85_formula(self):
        item = extract_ring_properties("Blood Ring",
            "2% Life Stolen Per Hit\\n+52 to Life\\n+3 to Strength\\n"
            "+14 to Dexterity\\n+104 to Attack Rating\\n+8 to Minimum Damage")
        self.assertAlmostEqual(item["quality_score_percent"], 85.47, places=2)


    """Exact stat snapshots supplied by the user; protect extraction and ranking."""
    def test_observation_147_is_premium_melee_ring(self):
        item=extract_ring_properties("Blood Ring",
            "2% Life Stolen Per Hit\n+52 to Life\n+3 to Strength\n"
            "+14 to Dexterity\n+104 to Attack Rating\n+8 to Minimum Damage")
        stats=item["stats"]
        self.assertEqual(stats["min_damage"],8)
        self.assertEqual(stats["attack_rating"],104)
        self.assertEqual(stats["life"],52)
        self.assertGreaterEqual(item["quality_score_percent"],80)
        from ring_analysis import build_demand_analysis
        self.assertGreaterEqual(build_demand_analysis(stats)["profiles"]["melee"]["score"],90)

    def test_observation_165_is_premium_melee_ring(self):
        item=extract_ring_properties("Blood Ring",
            "2% Life Stolen Per Hit\n+13 to Life\n+5 to Strength\n"
            "+120 to Attack Rating\n+9 to Minimum Damage\n"
            "Fire Resist +30%\nPoison Resist +24%")
        stats=item["stats"]
        self.assertEqual(stats["min_damage"],9)
        self.assertEqual(stats["max_damage"],None) if "max_damage" in stats else None
        self.assertEqual(stats["attack_rating"],120)
        self.assertEqual(stats["fire_resist"],30)
        self.assertEqual(stats["poison_resist"],24)
        self.assertGreaterEqual(item["quality_score_percent"],80)
        from ring_analysis import build_demand_analysis
        self.assertGreaterEqual(build_demand_analysis(stats)["profiles"]["melee"]["score"],90)

    def test_case4_is_materially_weaker_than_observations_147_and_165(self):
        case4=extract_ring_properties("Blood Ring",
            "2% Life Stolen Per Hit\n+18 to Life\n+4 to Strength\n"
            "3% Mana Stolen Per Hit\n+12 to Dexterity\n"
            "Lightning Resist +12%\n+40 to Mana")
        obs147=extract_ring_properties("Blood Ring",
            "2% Life Stolen Per Hit\n+52 to Life\n+3 to Strength\n"
            "+14 to Dexterity\n+104 to Attack Rating\n+8 to Minimum Damage")
        obs165=extract_ring_properties("Blood Ring",
            "2% Life Stolen Per Hit\n+13 to Life\n+5 to Strength\n"
            "+120 to Attack Rating\n+9 to Minimum Damage\n"
            "Fire Resist +30%\nPoison Resist +24%")
        self.assertLess(case4["quality_score_percent"],obs147["quality_score_percent"]-20)
        self.assertLess(case4["quality_score_percent"],obs165["quality_score_percent"]-20)
        from ring_analysis import build_demand_analysis
        self.assertLess(build_demand_analysis(case4["stats"])["profiles"]["melee"]["score"],
                        build_demand_analysis(obs147["stats"])["profiles"]["melee"]["score"])
        self.assertLess(build_demand_analysis(case4["stats"])["profiles"]["melee"]["score"],
                        build_demand_analysis(obs165["stats"])["profiles"]["melee"]["score"])

    def test_min_max_damage_are_melee_weighted_but_not_caster_weighted(self):
        from ring_analysis import build_demand_analysis
        demand=build_demand_analysis({"min_damage":9,"max_damage":15})
        self.assertGreater(demand["profiles"]["melee"]["score"],90)
        self.assertEqual(demand["profiles"]["sorceress"]["score"],0)

    def test_damage_reduction_stats_have_small_positive_value(self):
        from ring_analysis import AFFIX_IMPORTANCE, score_ring_stats
        self.assertGreater(AFFIX_IMPORTANCE["damage_reduced"],0)
        self.assertGreater(AFFIX_IMPORTANCE["magic_damage_reduced"],0)
        self.assertLess(AFFIX_IMPORTANCE["damage_reduced"],0.2)
        score,_=score_ring_stats({"damage_reduced":2,"magic_damage_reduced":2})
        self.assertGreater(score,0)


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
