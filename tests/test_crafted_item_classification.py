"""Regression tests for crafted item classification.

Extracts the production classifier AST so tests do not initialize game hooks,
Playwright, the Gemini client, or the price database.
"""
import ast
import re
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "d2_autotrader4.py"
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
function = next(node for node in tree.body
                if isinstance(node, ast.FunctionDef)
                and node.name == "classify_crafted_item_title")
namespace = {"re": re}
exec(compile(ast.Module(body=[function], type_ignores=[]), str(SOURCE), "exec"), namespace)
classify = namespace["classify_crafted_item_title"]


class CraftedClassificationTests(unittest.TestCase):
    def check(self, text, expected):
        self.assertEqual(classify(text, "TEST"), expected)

    def test_blood_ring_numeric_and_range_stats(self):
        self.check("Blood Ring\n1-3% Life Stolen Per Hit\n+ 15 to Life", "Blood Ring")

    def test_caster_ring(self):
        self.check("Ring\n10% Mana Regeneration\n+ 20 to Mana", "Caster Ring")

    def test_hit_power_ring(self):
        self.check("Ring\n5% Chance to Cast Level 4 Frost Nova When Struck\nAttacker Takes Damage of 4", "Hit Power Ring")

    def test_safety_ring_with_range(self):
        self.check("Ring\nDamage Reduced by 3\nMagic Damage Reduced by 1-2", "Safety Ring")

    def test_safety_ring_with_ocr_confusing_one_for_letter_i(self):
        self.check(
            "Bone Turn\nRing\n+120 to Attack Rating\n+19 to Strength\n"
            "+1 to Vitality\n+13\nPoison Resist +7%\n"
            "Damage Reduced By I\nMagic Damage Reduced By I",
            "Safety Ring",
        )

    def test_caster_ring_with_truncated_mana_line(self):
        self.check(
            "Eagle Band\nRing\n+120 to Attack Rating\n"
            "8% Life Stolen Per Hit\n+7 to Strength\n+3 to Energy\n"
            "+19\nRegenerate Mana 5%\n"
            "5% Better Chance of Getting Magic Items",
            "Caster Ring",
        )

    def test_blood_amulet_uses_amulet_specific_modifiers(self):
        self.check(
            "Mara's Beads\nAmulet\n1-3% Life Stolen Per Hit\n"
            "+10-20 to Life\n5-10% Faster Run/Walk",
            "Blood Amulet",
        )

    def test_caster_amulet_requires_fcr_mana_regen_and_mana(self):
        self.check(
            "Amulet\n5-10% Faster Cast Rate\n"
            " Regenerate Mana 4-10%\n+10-20 to Mana",
            "Caster Amulet",
        )

    def test_caster_amulet_with_truncated_mana_bonus(self):
        self.check(
            "Eagle Necklace\nAmulet\nRequired Level: 89\n"
            "+2 to Barbarian Skill Levels\n+10% Faster Cast Rate\n"
            "4% Life Stolen Per Hit\n+16\nRegenerate Mana 10%\n"
            "All Resistances +5\n+8% Damage Taken Goes to Mana",
            "Caster Amulet",
        )

    def test_hit_power_amulet_uses_monster_flee(self):
        self.check(
            "Amulet\n5% Chance to Cast Level 4 Frost Nova When Struck\n"
            "Attacker Takes Damage of 3-10\nHit Causes Monster to Flee +1-2%",
            "Hit Power Amulet",
        )

    def test_safety_amulet_uses_block_chance(self):
        self.check(
            "Amulet\n+5% Increased Chance of Blocking\n"
            "Damage Reduced by 1-4\nMagic Damage Reduced by 1-2",
            "Safety Amulet",
        )

    def test_ring_stats_alone_do_not_classify_as_blood_amulet(self):
        self.check(
            "Amulet\n1-3% Life Stolen Per Hit\n+10-20 to Life",
            None,
        )

    def test_existing_blood_gloves_unchanged(self):
        self.check("Sharkskin Gloves\n3% Life Stolen Per Hit\n10% Chance of Crushing Blow", "Blood Gloves")

    def test_ambiguous_ring_fails_closed(self):
        self.check("Ring\n+ 15 to Life", None)


if __name__ == "__main__":
    unittest.main()
