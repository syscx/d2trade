"""Local extraction and screening for crafted blood rings."""
from __future__ import annotations
import re
from typing import Any

PATTERNS = {
 "fcr":[r"(\d{1,2})\s*%?\s*(?:faster\s+cast\s+rate|fcr)\b"],
 "life_leech":[r"(\d{1,2})\s*%?\s*(?:life\s+)?(?:stolen|leech)\s+per\s+hit",r"(\d{1,2})\s*%?\s*life\s+leech"],
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
 "gold_find":[r"(\d{1,3})\s*%?\s*(?:extra\s+ gold|gold\s+find)"],
 "life_replenish":[r"replenish\s+life\s*\+?\s*(\d{1,2})",r"\+(\d{1,2})\s+replenish\s+life"],
}

def score_ring_stats(stats: dict[str, int]) -> tuple[float, list[str]]:
 """Explainable heuristic score; deliberately not a price conversion."""
 score = 0.0
 reasons: list[str] = []
 def add(points: float, reason: str) -> None:
  nonlocal score
  score += points
  reasons.append(f"{reason} ({points:+g})")
 fcr=stats.get("fcr")
 if fcr == 10: add(4,"10% FCR")
 elif fcr is not None: reasons.append(f"Invalid Blood-ring FCR value ({fcr}%)")
 leech=stats.get("life_leech",0)
 if leech: add(1,"Life leech (reduced weight)")
 for key,label in (("life","Life"),("strength","Strength"),("dexterity","Dexterity")):
  value=stats.get(key,0)
  if key=="life":
   if value>=40: add(2,"High Life")
   elif value>0: add(1,"Additional Life")
  elif value>=10: add(2,f"High {label}")
  elif value>0: add(1,f"Additional {label}")
 ar=stats.get("attack_rating",0)
 if ar>=100: add(2,"Attack Rating 100+")
 elif ar>=60: add(0.5,"Attack Rating 60-99")
 elif ar>0: add(-1,"Attack Rating below 60 (penalty)")
 all_res=stats.get("all_resist",0)
 if all_res>=10: add(2,"All Resistances 10+")
 elif all_res>=4: add(1,"All Resistances 4-9")
 elif all_res>0: add(0.5,"All Resistances below 4 (low value)")
 mana=stats.get("mana",0)
 if mana>=50: add(2,"Mana 50+")
 res=sum(stats.get(k,0) for k in ("fire_resist","cold_resist","lightning_resist","poison_resist"))
 if res>=30: add(2,"Combined single resistances 30+")
 mf=stats.get("magic_find",0)
 if mf>=20: add(1,"Magic Find (weak bonus)")
 elif mf>0: add(0.5,"Magic Find (small bonus)")
 gf=stats.get("gold_find",0)
 if gf>=50: add(0.5,"Gold Find (very weak bonus)")
 elif gf>0: add(0.25,"Gold Find (minimal bonus)")
 return round(score,2), reasons

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
 if score>=6: verdict="strong candidate; compare with similar FCR blood rings"
 elif score>=3: verdict="useful ring; value depends on caster build and other affixes"
 else: verdict="limited recognized premium stats; manual review"
 valid_blood_fcr = fcr is None or fcr == 10
 return {"item_type":"ring","craft_type":"blood_candidate" if blood_candidate and valid_blood_fcr else "unknown_or_other","stats":stats,"heuristic_score":score,"verdict":verdict,"reasons":reasons,"confidence":"low","fcr_valid_for_blood_ring":valid_blood_fcr,"raw_text":raw[:4000],"extraction_version":3}
