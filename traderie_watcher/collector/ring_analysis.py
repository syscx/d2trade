"""Local extraction and screening for crafted blood rings."""
from __future__ import annotations
import re
from typing import Any

PATTERNS = {
 "fcr":[r"(\d{1,2})\s*%?\s*(?:faster\s+cast\s+rate|fcr)\b"],
 "life_leech":[r"(\d{1,2})\s*%?\s*(?:life\s+)?(?:stolen|leech)\s+per\s+hit",r"(\d{1,2})\s*%?\s*life\s+leech"],
 "life":[r"[+]?(\d{1,3})\s+to\s+life\b"],
 "strength":[r"[+]?(\d{1,2})\s+to\s+strength\b"],
 "dexterity":[r"[+]?(\d{1,2})\s+to\s+dexterity\b"],
 "all_resist":[r"[+]?(\d{1,2})\s+to\s+all\s+resistances?\b"],
 "fire_resist":[r"[+]?(\d{1,2})\s*%?\s*(?:to\s+)?fire\s+resist"],
 "cold_resist":[r"[+]?(\d{1,2})\s*%?\s*(?:to\s+)?cold\s+resist"],
 "lightning_resist":[r"[+]?(\d{1,2})\s*%?\s*(?:to\s+)?lightning\s+resist"],
 "poison_resist":[r"[+]?(\d{1,2})\s*%?\s*(?:to\s+)?poison\s+resist"],
 "mana":[r"[+]?(\d{1,3})\s+to\s+mana\b"],
 "attack_rating":[r"[+]?(\d{1,3})\s+to\s+attack\s+rating\b"],
 "life_replenish":[r"replenish\s+life\s*\+?\s*(\d{1,2})",r"\+(\d{1,2})\s+replenish\s+life"],
}

def extract_ring_properties(title: str, visible_text: str) -> dict[str,Any] | None:
 raw=" ".join(x for x in (title,visible_text) if x)
 if not re.search(r"\bring\b",raw,re.I): return None
 stats={}
 for key,patterns in PATTERNS.items():
  for pattern in patterns:
   m=re.search(pattern,raw,re.I)
   if m:
    stats[key]=int(m.group(1)); break
 # Blood-crafted rings have guaranteed life leech; treat as a candidate, not proof.
 blood_candidate=stats.get("life_leech",0)>0
 fcr=stats.get("fcr")
 score=0; reasons=[]
 if fcr == 10: score+=4; reasons.append("10% FCR: valid maximum Blood-ring FCR roll")
 elif fcr is not None: reasons.append(f"Invalid Blood-ring FCR value detected ({fcr}%); verify OCR or item classification")
 if stats.get("life_leech",0): score+=2; reasons.append("Life leech is consistent with a Blood-crafted ring")
 for key,threshold,label in [("life",40,"Life"),("strength",10,"Strength"),("all_resist",10,"All Resistances"),("mana",50,"Mana"),("attack_rating",100,"Attack Rating")]:
  value=stats.get(key,0)
  if value>=threshold: score+=2; reasons.append(f"Strong {label} roll")
  elif value: score+=1; reasons.append(f"Additional {label}")
 res=sum(stats.get(k,0) for k in ("fire_resist","cold_resist","lightning_resist","poison_resist"))
 if res>=30: score+=2; reasons.append("Useful combined single resistances")
 if score>=6: verdict="strong candidate; compare with similar FCR blood rings"
 elif score>=3: verdict="useful ring; value depends on caster build and other affixes"
 else: verdict="limited recognized premium stats; manual review"
 valid_blood_fcr = fcr is None or fcr == 10
 return {"item_type":"ring","craft_type":"blood_candidate" if blood_candidate and valid_blood_fcr else "unknown_or_other","stats":stats,"heuristic_score":score,"verdict":verdict,"reasons":reasons,"confidence":"low","fcr_valid_for_blood_ring":valid_blood_fcr,"raw_text":raw[:4000],"extraction_version":2}
