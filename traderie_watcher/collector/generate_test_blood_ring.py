"""Generate plausible synthetic Blood Rings for parser/valuation tests.
Fixed Blood-craft mods are separate from up to four random affixes.
"""
import argparse
import json
import random

AFFIXES = [
    ("fcr", lambda r: "10% Faster Cast Rate"),
    ("dexterity", lambda r: f"+{r.randint(1, 15)} to Dexterity"),
    ("fire_resist", lambda r: f"+{r.randint(1, 30)}% to Fire Resistance"),
    ("cold_resist", lambda r: f"+{r.randint(1, 30)}% to Cold Resistance"),
    ("lightning_resist", lambda r: f"+{r.randint(1, 30)}% to Lightning Resistance"),
    ("poison_resist", lambda r: f"+{r.randint(1, 30)}% to Poison Resistance"),
    ("mana", lambda r: f"+{r.randint(1, 20)} to Mana"),
    ("attack_rating", lambda r: f"+{r.randint(1, 100)} to Attack Rating"),
    ("life_replenish", lambda r: f"Replenish Life +{r.randint(1, 5)}"),
]

def generate(seed=None):
    rng = random.Random(seed)
    fixed = {
        "life_leech": rng.randint(1, 3),
        "life": rng.randint(10, 20),
        "strength": rng.randint(1, 5),
    }
    affix_count = rng.randint(1, 4)
    selected = rng.sample(AFFIXES, affix_count)
    lines = [
        "Blood Ring (SYNTHETIC TEST DATA)",
        f'{fixed["life_leech"]}% Life Stolen Per Hit',
        f'+{fixed["life"]} to Life',
        f'+{fixed["strength"]} to Strength',
    ]
    for _, make_line in selected:
        lines.append(make_line(rng))
    return {
        "synthetic": True,
        "title": "Blood Ring (SYNTHETIC TEST DATA)",
        "visible_text": "\n".join(lines),
        "fixed_mods": fixed,
        "random_affix_count": affix_count,
        "random_affixes": [key for key, _ in selected],
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()
    print(json.dumps(generate(args.seed), indent=2))
