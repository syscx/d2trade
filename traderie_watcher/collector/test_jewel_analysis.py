import json
import sqlite3
import unittest
from jewel_analysis import analyze_listing, comparable_offer_summary, extract_jewel_properties, parse_rune_request, stat_similarity

class JewelTests(unittest.TestCase):
 def test_extracts_target_stats(self):
  r=extract_jewel_properties('Ruby Jewel','15% Increased Attack Speed\n40% Enhanced Damage\n15 Maximum Damage')
  self.assertEqual(r['stats'],{'ias':15,'enhanced_damage':40,'max_damage':15})
 def test_non_jewel_is_ignored(self):
  self.assertIsNone(extract_jewel_properties('Jah Rune','15% Increased Attack Speed'))
 def test_trade_request_is_not_sale(self):
  r=analyze_listing({'title':'Rare Jewel','visible_text':'15% Increased Attack Speed\n29% Enhanced Damage','i_give_text':'1 X Ohm Rune'})
  self.assertFalse(r['trade_observation']['is_confirmed_sale'])
  self.assertEqual(r['trade_observation']['observed_runes'],[{'quantity':1,'rune':'Ohm'}])
  self.assertIsNone(r['trade_observation']['numeric_estimate'])
 def test_multiple_runes(self):
  self.assertEqual(parse_rune_request('1 X Ber Rune | 1 X Ist Rune'),[{'quantity':1,'rune':'Ber'},{'quantity':1,'rune':'Ist'}])
 def test_nearby_stats_match(self):
  self.assertGreaterEqual(stat_similarity({'ias':15,'enhanced_damage':29},{'ias':15,'enhanced_damage':28}),0.8)
 def test_different_archetypes_do_not_match(self):
  self.assertEqual(stat_similarity({'ias':15},{'all_resist':15}),0.0)
 def test_current_observation_excluded(self):
  db=sqlite3.connect(':memory:'); db.row_factory=sqlite3.Row
  db.execute('CREATE TABLE jewel_analyses (observation_id INTEGER,stats_json TEXT,requested_trade_text TEXT,displayed_asking_price TEXT)')
  st={'ias':15,'enhanced_damage':29}
  db.execute('INSERT INTO jewel_analyses VALUES (?,?,?,?)',(10,json.dumps(st,sort_keys=True),'1 Ohm',None))
  db.execute('INSERT INTO jewel_analyses VALUES (?,?,?,?)',(11,json.dumps({'ias':15,'enhanced_damage':28},sort_keys=True),'1 Ber',None))
  r=comparable_offer_summary(db,st,11)
  self.assertEqual(r['matching_observation_count'],1)
  self.assertEqual(r['comparable_asking_offers'][0]['observation_id'],10)

if __name__=='__main__': unittest.main()
