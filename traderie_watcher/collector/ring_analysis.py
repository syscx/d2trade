"""Blood-ring stat extraction and explainable quality scoring.

Blood craft package: 15% of total score.
Four random affix slots: 85% total, 21.25% each.
Affix importance weights prevent inherently weak stats from scoring like FCR.
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
 "poison_length_reduced":[r"poison\s+length\s+reduced\s+by\s+(\d{1,3})\s*%"],
 "mana":[r"[+]?([\d]{1,3})\s+to\s+mana\b"],
 "mana_per_kill":[r"([+]?\d{1,2})\s+mana\s+after\s+each\s+kill",r"([+]?\d{1,2})\s+to\s+mana\s+after\s+each\s+kill",r"([+]?\d{1,2})\s+to\s+mana\s+per\s+kill"],
 "attack_rating":[r"[+]?([\d]{1,3})\s+to\s+attack\s+rating\b"],
 "magic_find":[r"(\d{1,2})\s*%?\s*better\s+chance\s+of\s+getting\s+magic\s+items?"],
 "gold_find":[r"(\d{1,3})\s*%?\s*(?:extra\s+gold|gold\s+find)"],
 "life_replenish":[r"replenish\s+life\s*\+?\s*(\d{1,2})",r"\+(\d{1,2})\s+replenish\s+life"],
}

FIXED_BLOOD_KEYS = {"life_leech", "life", "strength"}
RANDOM_AFFIX_KEYS = (
 "fcr", "mana_leech", "dexterity", "all_resist", "fire_resist",
 "cold_resist", "lightning_resist", "poison_resist", "mana", "mana_per_kill",
 "attack_rating", "magic_find", "gold_find", "life_replenish", "poison_length_reduced",
)
# Relative market usefulness of a perfect roll. FCR is the benchmark.
# These are transparent initial heuristics, not fitted market coefficients.
AFFIX_IMPORTANCE = {
 "fcr":1.00, "mana_leech":0.90, "all_resist":0.85, "mana_per_kill":0.55,
 "fire_resist":0.85, "cold_resist":0.60, "lightning_resist":0.85, "poison_resist":0.50, "poison_length_reduced":0.35,
 "dexterity":0.75, "mana":0.55, "attack_rating":0.45,
 "life_replenish":0.00, "magic_find":0.20, "gold_find":0.08,
}

def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
 return max(low, min(high, value))

def _affix_roll_quality(key: str, value: int) -> tuple[float, str]:
 """Return roll quality, including negative scoring below useful thresholds."""
 if key == "fcr":
  return (1.0 if value == 10 else 0.0, "10 FCR is a full-score affix")
 if key in {"fire_resist","cold_resist","lightning_resist","poison_resist"}:
  if value < 15:
   return (-0.25 * (15-value)/15, "resistance below 15 receives negative scoring")
  return (_clamp((value-15)/15), "resistance scored from 15 to 30")
 if key == "all_resist":
  return (_clamp(value/11), "all resistance scored against ring maximum 11")
 if key == "attack_rating":
  if value < 60:
   return (-0.05, "low attack rating is penalized")
  return (0.025 + _clamp((value-60)/40)*0.975, "attack rating scored from 60 to 100")
 maxima = {
  "mana":50, "mana_leech":6, "mana_per_kill":3, "dexterity":15,
  "magic_find":25, "gold_find":100, "life_replenish":5,
  "all_resist":11, "fire_resist":30, "cold_resist":30,
  "lightning_resist":30, "poison_resist":30, "attack_rating":120, "poison_length_reduced":25,
 }
 maximum = maxima.get(key)
 if maximum:
  return (_clamp(value/maximum), f"{key} roll normalized against {maximum}")
 return (0.0, f"{key} has no configured roll benchmark")

def blood_craft_quality(stats: dict[str, int]) -> float:
 """Average normalized roll quality of the three guaranteed Blood properties."""
 ranges = {"life_leech":(1,3), "life":(10,20), "strength":(1,5)}
 values=[]
 for key,(minimum,maximum) in ranges.items():
  value=stats.get(key)
  values.append(_clamp((value-minimum)/(maximum-minimum)) if value is not None else 0.0)
 return sum(values)/3.0

def _perfect_roll_bonus(key: str, value: int) -> float:
 """Small bonus for hitting the configured maximum on a useful affix."""
 maxima = {
  "fcr":10, "mana_leech":6, "all_resist":11,
  "fire_resist":30, "cold_resist":30, "lightning_resist":30,
  "poison_resist":30, "poison_length_reduced":25, "mana":50, "dexterity":15,
  "attack_rating":100,
 }
 return 1.0 if AFFIX_IMPORTANCE.get(key, 0.0) > 0 and maxima.get(key) == value else 0.0


def score_ring_stats(stats: dict[str, int]) -> tuple[float, list[str]]:
 """Return a 0-100 score: 15 fixed Blood points + four weighted affix slots."""
 fixed_score=blood_craft_quality(stats)*15.0
 reasons=[f"Blood craft package: {fixed_score:.2f}/15 (life leech, life, strength rolls)"]
 scored=[]
 for key in RANDOM_AFFIX_KEYS:
  if key not in stats:
   continue
  roll, explanation=_affix_roll_quality(key,int(stats[key]))
  importance=AFFIX_IMPORTANCE[key]
  bonus=_perfect_roll_bonus(key,int(stats[key]))
  scored.append((key,roll,importance,explanation,bonus))
 # Select the four strongest affixes using their weighted score plus perfect-roll bonus.
 scored.sort(key=lambda x:x[1]*x[2]*21.25+x[4],reverse=True)
 chosen=scored[:4]
 affix_score=0.0
 for key,roll,importance,explanation,bonus in chosen:
  points=roll*importance*21.25
  affix_score+=points+bonus
  bonus_note=f"; perfect-roll bonus +{bonus:.2f}" if bonus else ""
  reasons.append(f"{key}={stats[key]}: {points+bonus:+.2f}/21.25 (base {points:.2f}; importance {importance:.2f}{bonus_note}; {explanation})")
 for slot in range(4-len(chosen)):
  reasons.append(f"Empty random affix slot {slot+1}: 0/21.25")
 total=max(0.0,min(100.0,fixed_score+affix_score))
 reasons.append(f"Total quality: {total:.2f}/100")
 return round(total,2),reasons


# Build profiles are deliberately separate from the universal roll score.
# Initial weights are transparent heuristics and should be calibrated against
# collected sales rather than treated as established market coefficients.
BUILD_PROFILES = {
 "javazon": {
  # Lightning Javazon: Sunder-related resistance pressure makes lightning
  # resistance more valuable than fire resistance for this profile.
  "fcr":1.00,"mana_leech":0.90,"lightning_resist":1.00,"all_resist":0.90,
  "attack_rating":0.80,"dexterity":0.75,"strength":0.55,"life":0.40,
  "mana_per_kill":0.35,"fire_resist":0.25,"cold_resist":0.30,"poison_resist":0.20,
  "life_leech":0.10,"mana":0.25,
 },
 "sorceress": {
  # Ordinary spellcaster: leech requires physical attack damage and is not
  # counted as useful caster demand. Mana per Kill is preferred instead.
  "fcr":1.00,"mana":0.90,"mana_per_kill":0.85,"all_resist":0.80,
  "lightning_resist":0.70,"fire_resist":0.60,"cold_resist":0.60,
  "poison_resist":0.45,"life":0.55,"dexterity":0.35,"strength":0.20,
  "mana_leech":0.0,"life_leech":0.0,"attack_rating":0.0,
 },
 "es_sorceress": {
  "fcr":1.00,"mana":1.00,"poison_resist":0.95,
  "poison_length_reduced":0.90,"strength":0.45,"dexterity":0.50,
  "mana_per_kill":0.75,"all_resist":0.10,"life":0.10,
  "mana_leech":0.0,"life_leech":0.0,"lightning_resist":0.10,
 },
 "melee": {
  # Melee values offensive stats most, while retaining defensive stats as
  # useful secondary affixes rather than treating them as unusable.
  "attack_rating":1.00,"life_leech":0.95,"mana_leech":0.70,
  "strength":0.90,"dexterity":0.85,"life":0.70,
  "all_resist":0.65,"lightning_resist":0.50,"fire_resist":0.45,
  "cold_resist":0.40,"poison_resist":0.30,"mana":0.20,
  "mana_per_kill":0.20,"fcr":0.15,
 },
 "general_caster": {
  "fcr":1.00,"mana":0.85,"mana_per_kill":0.80,"all_resist":0.80,
  "lightning_resist":0.70,"fire_resist":0.60,"cold_resist":0.60,
  "poison_resist":0.45,"life":0.55,"dexterity":0.35,"strength":0.20,
  "mana_leech":0.0,"life_leech":0.0,"attack_rating":0.0,
 },
}

def _profile_roll_quality(key: str, value: int) -> float:
 """Normalize a stat for build-fit scoring without reusing market importance."""
 if key == "life_leech":
  return _clamp(value / 3.0)
 if key == "life":
  return _clamp((value - 10.0) / 10.0)
 if key == "strength":
  return _clamp(value / 5.0)
 if key == "mana_per_kill":
  return _clamp(value / 3.0)
 return max(0.0, _affix_roll_quality(key, int(value))[0])

def build_demand_analysis(stats: dict[str, int]) -> dict[str, Any]:
 """Score every overlapping build audience; profiles are not exclusive labels."""
 scores = {}
 for profile, weights in BUILD_PROFILES.items():
  if profile == "es_sorceress" and stats.get("fcr") != 10:
   scores[profile] = {"score": 0.0, "useful_stats": [],
                      "blocked_reason": "requires 10 FCR on the ring"}
   continue
  candidates = []
  for key, weight in weights.items():
   if key in stats and weight > 0:
    candidates.append((_profile_roll_quality(key, int(stats[key])) * weight,
                       weight, key, int(stats[key])))
  candidates.sort(key=lambda item: item[0], reverse=True)
  selected = candidates[:4]
  denominator = sum(sorted([w for w in weights.values() if w > 0],
                            reverse=True)[:4]) or 1.0
  score = 100.0 * sum(item[0] for item in selected) / denominator
  scores[profile] = {
   "score": round(_clamp(score, 0.0, 100.0), 2),
   "useful_stats": [item[2] for item in selected],
   "stat_contributions": [
    {"stat": item[2], "value": item[3], "weight": item[1],
     "normalized_roll": round(_profile_roll_quality(item[2], item[3]), 3),
     "contribution": round(item[0], 3)}
    for item in selected
   ],
  }
 ranked = sorted(scores.items(), key=lambda item: item[1]["score"], reverse=True)
 viable = [name for name, result in ranked if result["score"] >= 40.0]
 return {
  "profiles": scores,
  "ranked_profiles": [name for name, _ in ranked],
  "best_profile": ranked[0][0] if ranked else None,
  "best_score": ranked[0][1]["score"] if ranked else 0.0,
  "viable_profile_count": len(viable),
  "viable_profiles": viable,
  "demand_tier": ("broad" if len(viable) >= 3 else
                  "multi_build" if len(viable) == 2 else
                  "niche" if len(viable) == 1 else "weak"),
 }

BUILD_TARGETS = {
 "javazon": {"fcr":10,"mana_leech":4,"lightning_resist":20,"all_resist":8,"attack_rating":80},
 "sorceress": {"fcr":10,"mana":35,"mana_per_kill":2,"all_resist":8,"lightning_resist":20},
 "es_sorceress": {"fcr":10,"mana":35,"poison_resist":20,"poison_length_reduced":25,"strength":5,"dexterity":10},
 "melee": {"life_leech":3,"strength":5,"dexterity":10,"attack_rating":80,"all_resist":8},
 "general_caster": {"fcr":10,"mana":35,"mana_per_kill":2,"all_resist":8,"life":15},
}

def build_recommendation(stats: dict[str, int]) -> dict[str, Any]:
 """Return overlapping build audiences and explain their strongest stat matches."""
 demand = build_demand_analysis(stats)
 ranked = demand["ranked_profiles"]
 best = demand["best_profile"]
 score = float(demand["best_score"])
 recommendations = []
 for name in demand["viable_profiles"]:
  profile_result = demand["profiles"][name]
  targets = BUILD_TARGETS.get(name, {})
  met = [key for key, minimum in targets.items()
         if stats.get(key) is not None and stats[key] >= minimum]
  coverage = len(met) / len(targets) if targets else 0.0
  # A high fit score with some target coverage is enough to show a recommendation.
  # Overlapping audiences are intentional; do not force a single winner.
  if profile_result["score"] >= 40.0 and coverage >= 0.40:
   recommendations.append({
    "build": name, "fit_score": profile_result["score"],
    "target_coverage": round(coverage, 3),
    "useful_stats": profile_result.get("useful_stats", []),
    "stat_contributions": profile_result.get("stat_contributions", []),
    "met_targets": met,
   })
 recommendations.sort(key=lambda item: item["fit_score"], reverse=True)
 candidate = recommendations[0]["build"] if recommendations else best
 target = BUILD_TARGETS.get(candidate, {}) if candidate else {}
 met = []
 missing = []
 below = []
 for key, minimum in target.items():
  actual = stats.get(key)
  if actual is None:
   missing.append({"stat": key, "target": minimum})
  elif actual >= minimum:
   met.append({"stat": key, "actual": actual, "target": minimum})
  else:
   below.append({"stat": key, "actual": actual, "target": minimum,
                 "gap": minimum - actual})
 return {
  "recommended_build": candidate if recommendations else None,
  "recommendations": recommendations,
  "best_candidate": best,
  "fit_score": round(score, 2),
  "target_coverage": round(len(met) / len(target), 3) if target else 0.0,
  "confidence": "heuristic",
  "demand_tier": demand["demand_tier"],
  "viable_profiles": demand["viable_profiles"],
  "ranked_profiles": [
   {"build": name, "fit_score": demand["profiles"][name]["score"],
    "useful_stats": demand["profiles"][name]["useful_stats"]}
   for name in ranked
  ],
  "target_benchmark": {
   "targets": target, "met": met, "below_target": below,
   "missing": missing, "completion_count": len(met),
   "target_count": len(target),
  },
  "summary": (
   "Matching build audiences: " + ", ".join(x["build"] for x in recommendations)
   if recommendations else
   ("No build profile reached the recommendation threshold; fallback remains quality-based."
    if best else "No build profile could be evaluated.")
  ),
  "caveat": "Build weights and target rolls are transparent initial heuristics, not market-trained prices. Mana/life leech have zero ordinary-caster demand weight; Lightning Javazon prioritizes lightning resistance. ES Sorceress requires 10 FCR on the ring.",
}

def ring_quality_features(stats: dict[str,int]) -> set[str]:
 thresholds={"mana_leech":4,"life_leech":3,"dexterity":5,"strength":5,"life":15,"attack_rating":100,"all_resist":10}
 return {key for key,minimum in thresholds.items() if stats.get(key,0)>=minimum}

def ring_quality_gap(target: dict[str,int], comparable: dict[str,int]) -> dict[str,Any]:
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
   match=re.search(pattern,raw,re.I)
   if match:
    stats[key]=int(match.group(1)); break
 blood_candidate=stats.get("life_leech",0)>0
 fcr=stats.get("fcr")
 score,reasons=score_ring_stats(stats)
 if score>=80: verdict="excellent ring; prioritize high-end completed-sale comparisons"
 elif score>=55: verdict="promising ring; value depends on affix combination and market sales"
 elif score>=35: verdict="situational ring; use distance-weighted completed sales"
 else: verdict="low-quality ring; conservative fallback unless sales show otherwise"
 valid_blood_fcr=fcr is None or fcr==10
 random_affixes=[key for key in RANDOM_AFFIX_KEYS if key in stats]
 weak=sum(1 for key in random_affixes if _affix_roll_quality(key,stats[key])[0]*AFFIX_IMPORTANCE[key]<0.15)
 poor=(score<65.0 or (len(random_affixes)>=3 and (weak>=2 or sum(_affix_roll_quality(k,stats[k])[0]*AFFIX_IMPORTANCE[k] for k in random_affixes)/len(random_affixes)<0.35)))
 return {"item_type":"ring","craft_type":"blood_candidate" if blood_candidate and valid_blood_fcr else "unknown_or_other",
  "stats":stats,"heuristic_score":score,"quality_score_percent":score,"verdict":verdict,"reasons":reasons,
  "random_affixes":random_affixes,"random_affix_count":len(random_affixes),"poor_stat_combination":poor,
  "confidence":"low","fcr_valid_for_blood_ring":valid_blood_fcr,"raw_text":raw[:4000],"extraction_version":6}
