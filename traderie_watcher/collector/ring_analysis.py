"""Blood-ring stat extraction and explainable quality scoring.

Blood craft package: 15% of total score.
Four random affix slots: 85% total, 21.25% each.
The score is a quality indicator, not a direct currency conversion.
"""
from __future__ import annotations
import re
from typing import Any

PATTERNS = {
 "fcr":[r"(\d{1,2})\s*%?\s*(?:faster\s+cast\s+rate|fcr)\b"],
 "life_leech":[r"(\d{1,2})\s*%?\s*life\s+(?:stolen|leech)\s+per\s+hit",r"(\d{1,2})\s*%?\s*life\s+leech"],
 "mana_leech":[r"(\d{1,2})\s*%?\s*mana\s+(?:stolen|leech)\s+per\s+hit",r"(\d{1,2})\s*%?\s*mana\s+leech"],
 "life":[r"[+]?([\d]{1,3})\s+to\s+life\b"],
 "strength":[r"[+]?([\d]{1,2})\s+to\s+strength\b"],
 "dexterity":[r"[+]?([\d]{1,2})\s+to\s+dexterity\b"],
 "all_resist":[r"[+]?([\d]{1,2})\s+to\s+all\s+resistances?\b"],
 "fire_resist":[r"[+]?([\d]{1,2})\s*%?\s*(?:to\s+)?fire\s+resist"],
 "cold_resist":[r"[+]?([\d]{1,2})\s*%?\s*(?:to\s+)?cold\s+resist"],
 "lightning_resist":[r"[+]?([\d]{1,2})\s*%?\s*(?:to\s+)?lightning\s+resist"],
 "poison_resist":[r"[+]?([\d]{1,2})\s*%?\s*(?:to\s+)?poison\s+resist"],
 "mana":[r"[+]?([\d]{1,3})\s+to\s+mana\b"],
 "attack_rating":[r"[+]?([\d]{1,3})\s+to\s+attack\s+rating\b"],
 "magic_find":[r"(\d{1,2})\s*%?\s*better\s+chance\s+of\s+getting\s+magic\s+items?"],
 "gold_find":[r"(\d{1,3})\s*%?\s*(?:extra\s+gold|gold\s+find)"],
 "life_replenish":[r"replenish\s+life\s*\+?\s*(\d{1,2})",r"\+(\d{1,2})\s+replenish\s+life"],
}

FIXED_BLOOD_KEYS = {"life_leech", "life", "strength"}
RANDOM_AFFIX_KEYS = (
 "fcr", "mana_leech", "dexterity", "all_resist", "fire_resist",
 "cold_resist", "lightning_resist", "poison_resist", "mana",
 "attack_rating", "magic_find", "gold_find", "life_replenish",
)

def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
 return max(low, min(high, value))

def _affix_roll_quality(key: str, value: int) -> tuple[float, str]:
 """Return a normalized slot score; negative values mark rolls below useful floors."""
 if key == "fcr":
  return (1.0 if value == 10 else 0.0, "10 FCR is a full-score affix" if value == 10 else "invalid/non-premium FCR roll")
 if key in {"fire_resist","cold_resist","lightning_resist","poison_resist"}:
  if value < 15:
   return (-0.25 * (15-value)/15, "resistance below 15 receives negative scoring")
  return (_clamp((value-15)/15), "resistance scored from 15 to 30")
 if key == "attack_rating":
  if value < 60:
   return (_clamp(value/60)*0.05, "low attack rating contributes almost nothing")
  return (0.05 + _clamp((value-60)/40)*0.95, "attack rating scored from 60 to 100")
 maxima = {
  "mana":50, "mana_leech":6, "dexterity":15, "all_resist":20,
  "magic_find":25, "gold_find":100, "life_replenish":5,
 }
 maximum = maxima.get(key)
 if maximum:
  return (_clamp(value/maximum), f"{key} roll normalized against {maximum}")
 return (0.0, f"{key} has no configured roll benchmark")

def blood_craft_quality(stats: dict[str, int]) -> float:
 """Average roll quality of the three guaranteed Blood-craft properties."""
 ranges = {"life_leech":(1,3), "life":(10,20), "strength":(1,5)}
 values=[]
 for key,(minimum,maximum) in ranges.items():
  # Missing fixed mods are treated as unverified/zero quality rather than
  # silently averaging only the properties the parser happened to find.
  value=stats.get(key)
  values.append(_clamp((value-minimum)/(maximum-minimum)) if value is not None else 0.0)
 return sum(values)/3.0

def score_ring_stats(stats: dict[str, int]) -> tuple[float, list[str]]:
 """Return 0-100 quality score and an auditable per-slot explanation."""
 fixed_roll = blood_craft_quality(stats)
 fixed_score = fixed_roll * 15.0
 reasons = [f"Blood craft package: {fixed_score:.2f}/15 (life leech, life, strength rolls)"]
 affix_scores=[]
 for key in RANDOM_AFFIX_KEYS:
  if key not in stats:
   continue
  quality, explanation = _affix_roll_quality(key, int(stats[key]))
  affix_scores.append((key, quality, explanation))
 affix_scores.sort(key=lambda x: x[1], reverse=True)
 # There can be at most four random affixes. Each slot is 21.25 points.
 chosen=affix_scores[:4]
 affix_score=0.0
 for key,quality,explanation in chosen:
  points=quality*21.25
  affix_score += points
  reasons.append(f"{key}={stats[key]}: {points:+.2f}/21.25 ({explanation})")
 for slot in range(4-len(chosen)):
  reasons.append(f"Empty random affix slot {slot+1}: 0/21.25")
 total=max(0.0,min(100.0,fixed_score+affix_score))
 reasons.append(f"Total quality: {total:.2f}/100")
 return round(total,2), reasons

def ring_quality_features(stats: dict[str, int]) -> set[str]:
 thresholds = {"mana_leech":4,"life_leech":3,"dexterity":5,"strength":5,"life":15,"attack_rating":100,"all_resist":10}
 return {key for key, minimum in thresholds.items() if stats.get(key,0) >= minimum}

def ring_quality_gap(target: dict[str, int], comparable: dict[str, int]) -> dict[str, Any]:
 target_features=ring_quality_features(target)
 comparable_features=ring_quality_features(comparable)
 missing=sorted(comparable_features-target_features)
 extra=sorted(target_features-comparable_features)
 return {"target_features":sorted(target_features),"comparable_features":sorted(comparable_features),
  "missing_from_target":missing,"missing_from_comparable":extra,
  "mismatch_count":len(missing)+len(extra),"penalty":round(0.12*(len(missing)+len(extra)),4)}

def extract_ring_properties(title: str, visible_text: str) -> dict[str,Any] | None:
 raw=" ".join(x for x in (title,visible_text) if x)
 if not re.search(r"\bring\b",raw,re.I): return None
 stats={}
 for key,patterns in PATTERNS.items():
  for pattern in patterns:
   m=re.search(pattern,raw,re.I)
   if m:
    stats[key]=int(m.group(1)); break
 blood_candidate=stats.get("life_leech",0)>0
 fcr=stats.get("fcr")
 score,reasons=score_ring_stats(stats)
 if score>=80: verdict="excellent ring; prioritize high-end completed-sale comparisons"
 elif score>=55: verdict="promising ring; value depends on affix combination and market sales"
 elif score>=35: verdict="situational ring; use distance-weighted completed sales"
 else: verdict="low-quality ring; conservative fallback unless sales show otherwise"
 valid_blood_fcr = fcr is None or fcr == 10
 random_affixes=[key for key in RANDOM_AFFIX_KEYS if key in stats]
 weak_affixes=sum(1 for key in random_affixes if _affix_roll_quality(key,stats[key])[0] < 0.15)
 poor_combination=(len(random_affixes)>=3 and (weak_affixes>=2 or sum(_affix_roll_quality(k,stats[k])[0] for k in random_affixes)/len(random_affixes)<0.35))
 return {"item_type":"ring","craft_type":"blood_candidate" if blood_candidate and valid_blood_fcr else "unknown_or_other",
  "stats":stats,"heuristic_score":score,"quality_score_percent":score,"verdict":verdict,"reasons":reasons,
  "random_affixes":random_affixes,"random_affix_count":len(random_affixes),"poor_stat_combination":poor_combination,
  "confidence":"low","fcr_valid_for_blood_ring":valid_blood_fcr,"raw_text":raw[:4000],"extraction_version":5}
