"""Generate synthetic Blood Rings with legal prefix/suffix distributions.

A ring may have at most three prefixes and three suffixes. Four-affix
rings are distributed 1/3, 2/2, or 3/1; never 4/0 or 0/4.
"""
import argparse
import json
import random

# Explicit test-generation pools. Each selected affix has a single side.
PREFIX_AFFIXES = [
    ("mana", lambda r: f"+{r.randint(1, 50)} to Mana"),
    ("all_resist", lambda r: f"+{r.randint(1, 11)} to All Resistances"),
    ("fire_resist", lambda r: f"+{r.randint(1, 30)}% to Fire Resistance"),
    ("cold_resist", lambda r: f"+{r.randint(1, 30)}% to Cold Resistance"),
    ("lightning_resist", lambda r: f"+{r.randint(1, 30)}% to Lightning Resistance"),
    ("poison_resist", lambda r: f"+{r.randint(1, 30)}% to Poison Resistance"),
    ("attack_rating", lambda r: f"+{r.randint(1, 120)} to Attack Rating"),
]
SUFFIX_AFFIXES = [
    ("fcr", lambda r: "10% Faster Cast Rate"),
    ("mana_leech", lambda r: f"{r.randint(1, 6)}% Mana Stolen Per Hit"),
    ("magic_find", lambda r: f"{r.randint(1, 25)}% Better Chance of Getting Magic Items"),
    ("gold_find", lambda r: f"{r.randint(1, 100)}% Extra Gold from Monsters"),
    ("life_replenish", lambda r: f"Replenish Life +{r.randint(1, 5)}"),
    ("dexterity", lambda r: f"+{r.randint(1, 15)} to Dexterity"),
]

def generate(seed=None, affix_count=None):
    rng=random.Random(seed)
    fixed={"life_leech":rng.randint(1,3),"life":rng.randint(10,20),"strength":rng.randint(1,5)}
    count=affix_count if affix_count is not None else rng.randint(1,4)
    if not 1<=count<=4:
        raise ValueError("affix_count must be between 1 and 4")
    # Ensure both sides are represented for 2+ affixes and neither side exceeds 3.
    prefix_count=rng.randint(max(1,count-3),min(3,count-1)) if count>=2 else rng.choice([0,1])
    suffix_count=count-prefix_count
    if count==1:
        prefix_count=1 if rng.random()<0.5 else 0
        suffix_count=1-prefix_count
    prefixes=rng.sample(PREFIX_AFFIXES,prefix_count) if prefix_count else []
    suffixes=rng.sample(SUFFIX_AFFIXES,suffix_count) if suffix_count else []
    selected=[(side,key,maker) for side,pool in (("prefix",prefixes),("suffix",suffixes)) for key,maker in pool]
    rng.shuffle(selected)
    lines=["Blood Ring (SYNTHETIC TEST DATA)",
        f'{fixed["life_leech"]}% Life Stolen Per Hit',
        f'+{fixed["life"]} to Life',f'+{fixed["strength"]} to Strength']
    for _,_,maker in selected:
        lines.append(maker(rng))
    return {"synthetic":True,"title":"Blood Ring (SYNTHETIC TEST DATA)",
        "visible_text":"\n".join(lines),"fixed_mods":fixed,
        "fixed_mods_present":sorted(fixed),"random_affix_count":count,
        "random_affixes":[key for _,key,_ in selected],
        "prefix_count":prefix_count,"suffix_count":suffix_count,
        "prefix_affixes":[key for side,key,_ in selected if side=="prefix"],
        "suffix_affixes":[key for side,key,_ in selected if side=="suffix"]}

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--seed",type=int,default=None)
    parser.add_argument("--affix-count",type=int,choices=range(1,5),default=None)
    args=parser.parse_args()
    print(json.dumps(generate(args.seed,args.affix_count),indent=2))
