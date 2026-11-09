import unittest
from ring_analysis import extract_ring_properties

class BloodRingTests(unittest.TestCase):
 def test_extracts_10_fcr_blood_ring(self):
  r=extract_ring_properties('Blood Ring','10% Faster Cast Rate\\n3% Life Stolen Per Hit\\n+18 to Life\\n+5 to Strength\\n+27% Fire Resist')
  self.assertEqual(r['craft_type'],'blood_candidate')
  self.assertEqual(r['stats']['fcr'],10)
  self.assertTrue(r['fcr_valid_for_blood_ring'])
 def test_blood_ring_without_fcr_is_valid(self):
  r=extract_ring_properties('Blood Ring','3% Life Stolen Per Hit\\n+18 to Life')
  self.assertEqual(r['craft_type'],'blood_candidate')
  self.assertNotIn('fcr',r['stats'])
 def test_invalid_fcr_not_treated_as_blood_ring_roll(self):
  r=extract_ring_properties('Blood Ring','8% Faster Cast Rate\\n3% Life Stolen Per Hit')
  self.assertEqual(r['craft_type'],'unknown_or_other')
  self.assertFalse(r['fcr_valid_for_blood_ring'])
 def test_non_ring_is_ignored(self):
  self.assertIsNone(extract_ring_properties('Jah Rune','10% Faster Cast Rate'))


    def test_synthetic_generator_uses_at_most_four_random_affixes(self):
        from generate_test_blood_ring import generate
        for seed in range(100):
            item = generate(seed)
            self.assertGreaterEqual(item["random_affix_count"], 1)
            self.assertLessEqual(item["random_affix_count"], 4)
            self.assertEqual(item["random_affix_count"], len(item["random_affixes"]))
            self.assertEqual(len(item["random_affixes"]), len(set(item["random_affixes"])))
            self.assertEqual(item["visible_text"].count("\\\\n"), 3 + item["random_affix_count"])

if __name__=='__main__': unittest.main()
