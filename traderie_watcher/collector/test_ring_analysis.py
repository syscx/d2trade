import unittest
from ring_analysis import extract_ring_properties

class BloodRingTests(unittest.TestCase):
 def test_extracts_fcr_blood_ring(self):
  r=extract_ring_properties("Blood Ring","10% Faster Cast Rate\n3% Life Stolen Per Hit\n+18 to Life\n+5 to Strength\n+27% Fire Resist")
  self.assertEqual(r["craft_type"],"blood_candidate")
  self.assertEqual(r["stats"]["fcr"],10)
  self.assertEqual(r["stats"]["life_leech"],3)
  self.assertEqual(r["stats"]["life"],18)
 def test_non_ring_is_ignored(self):
  self.assertIsNone(extract_ring_properties("Jah Rune","10% Faster Cast Rate"))

if __name__=="__main__": unittest.main()
