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
        self.check("Ring\n10% Mana Regeneration\n+  mana?\n+ 20 to Mana", "Caster Ring")

    def test_hit_power_ring(self):
        self.check("Ring\n5% Chance to Cast Level 4 Frost Nova When Struck\nAttacker Takes Damage of 4", "Hit Power Ring")

    def test_safety_ring_with_range(self):
        self.check("Ring\nDamage Reduced by 3\nMagic Damage Reduced by 1-2", "Safety Ring")

    def test_existing_blood_gloves_unchanged(self):
        self.check("Sharkskin Gloves\n3% Life Stolen Per Hit\n10% Chance of Crushing Blow", "Blood Gloves")

    def test_ambiguous_ring_fails_closed(self):
        self.check("Ring\n+ 15 to Life", None)


if __name__ == "__main__":
    unittest.main()
