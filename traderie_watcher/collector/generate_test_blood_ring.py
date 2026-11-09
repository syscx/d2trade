"""Generate synthetic Blood Ring examples for parser smoke tests."""
import argparse, json, random

def generate(seed=None):
 rng=random.Random(seed)
 stats={"fcr":rng.choice([None,10]),"life_leech":rng.randint(1,3),"life":rng.randint(1,20),"strength":rng.randint(1,5),"dexterity":rng.randint(1,5),"fire_resist":rng.randint(0,30),"lightning_resist":rng.randint(0,30),"mana":rng.randint(0,20)}
 lines=["Blood Ring (SYNTHETIC TEST DATA)"]
 if stats["fcr"] == 10: lines.append("10% Faster Cast Rate")
 lines += [f'{stats["life_leech"]}% Life Stolen Per Hit',f'+{stats["life"]} to Life',f'+{stats["strength"]} to Strength',f'+{stats["dexterity"]} to Dexterity',f'+{stats["fire_resist"]}% to Fire Resistance',f'+{stats["lightning_resist"]}% to Lightning Resistance',f'+{stats["mana"]} to Mana']
 return {"synthetic":True,"title":"Blood Ring (SYNTHETIC TEST DATA)","visible_text":"\\n".join(lines),"expected_stats":stats}

if __name__=="__main__":
 p=argparse.ArgumentParser(); p.add_argument("--seed",type=int,default=None); a=p.parse_args()
 print(json.dumps(generate(a.seed),indent=2))
