import json
import tempfile
import unittest
from pathlib import Path
from local_market_evaluator import evaluate, import_records, infer_category

class LocalEvaluatorTests(unittest.TestCase):
    def test_four_affix_jewel_uses_variable_roll_comps(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "market.db"
            sales = Path(tmp) / "sales.json"
            records = [
                {
                    "category": "rare_jewel_low_level",
                    "item_text": "Rare Jewel Required Level: 18",
                    "affixes_json": {
                        "enhanced_damage_pct": 28,
                        "max_damage": 5,
                        "strength": 6,
                        "life": 8
                    },
                    "price_ist": 2.0, "status": "sold", "source": "source-a"
                },
                {
                    "category": "rare_jewel_low_level",
                    "item_text": "Rare Jewel Required Level: 18",
                    "affixes_json": {
                        "enhanced_damage_pct": 34,
                        "max_damage": 6,
                        "strength": 8,
                        "life": 10
                    },
                    "price_ist": 5.0, "status": "sold", "source": "source-b"
                },
                {
                    "category": "rare_jewel_low_level",
                    "item_text": "Rare Jewel Required Level: 18",
                    "affixes_json": {
                        "enhanced_damage_pct": 38,
                        "max_damage": 7,
                        "strength": 9,
                        "life": 12
                    },
                    "price_ist": 8.0, "status": "sold", "source": "source-c"
                }
            ]
            sales.write_text(json.dumps(records), encoding="utf-8")
            added, rejected = import_records(sales, db)
            self.assertEqual((added, rejected), (3, 0))
            result = evaluate(
                "Rare Jewel Required Level: 18", db,
                category="rare_jewel_low_level",
                affixes={
                    "enhanced_damage_pct": 35,
                    "max_damage": 6,
                    "strength": 8,
                    "life": 11
                }
            )
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["matched_affixes"], 4)
            self.assertEqual(result["training_sales"], 3)

    def test_low_level_jewel_requires_level(self):
        self.assertEqual(infer_category("Rare Jewel Required Level: 18 +15% Enhanced Damage"), "rare_jewel_low_level")
        self.assertIsNone(infer_category("Rare Jewel +15% Enhanced Damage"))

if __name__ == "__main__":
    unittest.main()
