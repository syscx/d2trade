import tempfile
import unittest
from pathlib import Path
from local_market_evaluator import evaluate, import_records, infer_category

class LocalEvaluatorTests(unittest.TestCase):
    def test_requires_three_verified_sales(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "market.db"
            csv_path = Path(tmp) / "sales.csv"
            csv_path.write_text(
                "category,item_text,price_ist,status,source\n"
                "crafted_amulet,Blood Amulet +10% Faster Run/Walk +15 to Life +5% Life Stolen per Hit +20 to Strength,2,sold,source-a\n"
                "crafted_amulet,Blood Amulet +10% Faster Run/Walk +15 to Life +5% Life Stolen per Hit +20 to Strength,3,sold,source-b\n",
                encoding="utf-8"
            )
            import_records(csv_path, db)
            result = evaluate(
                "Blood Amulet +10% Faster Run/Walk +15 to Life +5% Life Stolen per Hit +20 to Strength",
                db
            )
            self.assertEqual(result["status"], "insufficient_data")

    def test_low_level_jewel_requires_level(self):
        self.assertEqual(infer_category("Rare Jewel Required Level: 18 +15% Enhanced Damage"), "rare_jewel_low_level")
        self.assertIsNone(infer_category("Rare Jewel +15% Enhanced Damage"))

if __name__ == "__main__":
    unittest.main()
