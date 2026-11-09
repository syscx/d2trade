"""Generate clearly synthetic Blood Ring examples for parser smoke tests.

These fixtures are never sent to Traderie or inserted into the market database.
"""
from __future__ import annotations
import argparse, random

def generate(seed: int | None=None) -> dict:
 rng=random.Random(seed)
 stats={
  "fcr":rng.choice([5,6,7,8,9,10]),
  "life_leech":rng.randint(1,3),
  "life":rng.randint(1,20),
  "strength":rng.randint(1,5),
  "dexterity":rng.randint(1,5),
  "fire_resist":rng.randint(0,30),
  "lightning_resist":rng.randint(0,30),
  "mana":rng.randint(0,20),
 }
 lines=["Blood Ring (SYNTHETIC TEST DATA)",
  f'{stats["fcr"]}% Faster Cast Rate',
  f'{stats["life_leech"]}% Life Stolen Per Hit',
  f'+{stats["life"]} to Life',
  f'+{stats["strength"]} to Strength',
  f'+{stats["dexterity"]} to Dexterity',
  f'+{stats["fire_resist"]}% to Fire Resistance',
  f'+{stats["lightning_resist"]}% to Lightning Resistance',
  f'+{stats["mana"]} to Mana']
 return {"synthetic":True,"title":"Blood Ring (SYNTHETIC TEST DATA)","visible_text":"\n".join(lines),"expected_stats":stats}

if __name__=="__main__":
 parser=argparse.ArgumentParser()
 parser.add_argument("--seed",type=int,default=None)
 args=parser.parse_args()
 import json
 print(json.dumps(generate(args.seed),indent=2))
