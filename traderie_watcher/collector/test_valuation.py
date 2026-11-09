import unittest
from valuation import rune_bundle_value_pskulls

class RuneValuationTests(unittest.TestCase):
 def test_ist_is_fifteen_pskulls(self):
  r=rune_bundle_value_pskulls([{"rune":"Ist","quantity":1}])
  self.assertEqual(r["value_pskulls"],15)
  self.assertEqual(r["display"],"1.00 Ist")
 def test_perfect_skulls_are_pskull_units(self):
  r=rune_bundle_value_pskulls([{"rune":"Perfect Skull","quantity":7}])
  self.assertEqual(r["value_pskulls"],7)
  self.assertEqual(r["display"],"7 Pskulls")
 def test_unknown_rune_rate_is_not_guessed(self):
  r=rune_bundle_value_pskulls([{"rune":"Gul","quantity":1}])
  self.assertIsNone(r["value_pskulls"])
  self.assertEqual(r["missing_rune_rates"],["Gul"])
 def test_configured_sub_ist_rune_displays_pskulls(self):
  r=rune_bundle_value_pskulls([{"rune":"Gul","quantity":1}],{"Gul":7})
  self.assertEqual(r["display"],"7 Pskulls")

if __name__=="__main__": unittest.main()
