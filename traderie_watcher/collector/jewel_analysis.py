"""Structured extraction and conservative screening for Traderie jewels."""
from __future__ import annotations
import json, re
from typing import Any

STAT_PATTERNS = {
 "ias":[r"(?<!\d)(\d{1,2})\s*%?\s*(?:increased\s+attack\s+speed|ias)\b"],
 "enhanced_damage":[r"(?<!\d)(\d{1,3})\s*%?\s*enhanced\s+damage\b",r"(?<!\d)(\d{1,3})\s*%?\s*ed\b"],
 "max_damage":[r"[+]?\s*(\d{1,2})\s*(?:to\s+)?maximum\s+damage\b",r"[+]?\s*(\d{1,2})\s*max\s+damage\b",r"\+\s*(\d{1,2})\s*max\b"],
 "min_damage":[r"[+]?\s*(\d{1,2})\s*(?:to\s+)?minimum\s+damage\b",r"[+]?\s*(\d{1,2})\s*min\s+damage\b"],
 "all_resist":[r"[+]?\s*(\d{1,2})\s*(?:%\s*)?to\s+all\s+resistances?\b"],
 "life":[r"[+]?\s*(\d{1,3})\s+to\s+life\b"],
 "fhr":[r"[+]?\s*(\d{1,2})\s*%?\s*faster\s+hit\s+recovery\b"],
 "strength":[r"[+]?\s*(\d{1,2})\s+to\s+strength\b"],
 "dexterity":[r"[+]?\s*(\d{1,2})\s+to\s+dexterity\b"],
}
PHYSICAL={"ias","enhanced_damage","max_damage","min_damage"}
UTILITY={"all_resist","life","fhr","strength","dexterity"}
WEIGHTS={"ias":2.0,"enhanced_damage":2.0,"max_damage":1.5,"min_damage":1.0,"all_resist":1.5,"life":1.0,"fhr":1.5,"strength":1.0,"dexterity":1.0}
TOLERANCES={"ias":5,"enhanced_damage":10,"max_damage":5,"min_damage":5,"all_resist":5,"life":5,"fhr":5,"strength":5,"dexterity":5}

def _first_match(text: str, patterns: list[str]) -> int | None:
 for pattern in patterns:
  match=re.search(pattern,text,re.I)
  if match: return int(match.group(1))
 return None

def extract_jewel_properties(title: str, visible_text: str) -> dict[str,Any] | None:
 raw=" ".join(x for x in (title,visible_text) if x)
 if not re.search(r"\bjewel\b",raw,re.I): return None
 stats={k:v for k,p in STAT_PATTERNS.items() if (v:=_first_match(raw,p)) is not None}
 return {"item_type":"jewel","quality_hint":next((q for q in ("rare","magic","unique") if re.search(rf"\b{q}\b",raw,re.I)),None),"stats":stats,"raw_text":raw[:4000],"extraction_version":2}

def _archetypes(stats: dict[str,int]) -> set[str]:
 kinds=set()
 if set(stats)&PHYSICAL: kinds.add("physical_damage")
 if set(stats)&UTILITY: kinds.add("utility")
 return kinds

def recommend_jewel(stats: dict[str,int]) -> dict[str,Any]:
 kinds=_archetypes(stats); score=0; reasons=[]
 checks=[("ias",15,3,"15% IAS is a notable offensive modifier"),("enhanced_damage",35,3,"High Enhanced Damage"),("max_damage",10,2,"Meaningful maximum damage"),("min_damage",10,2,"Meaningful minimum damage")]
 for key,threshold,points,reason in checks:
  value=stats.get(key,0)
  if value>=threshold: score+=points; reasons.append(reason)
  elif value: score+=1; reasons.append(f"{key.replace('_',' ').title()} may help a physical setup")
 if stats.get("ias",0)>=15 and stats.get("enhanced_damage",0)>=30: reasons.append("IAS + Enhanced Damage is a relevant physical-jewel combination")
 for key,threshold,label in [("all_resist",10,"All Resistances"),("fhr",7,"Faster Hit Recovery"),("life",10,"Life"),("strength",6,"Strength"),("dexterity",6,"Dexterity")]:
  value=stats.get(key,0)
  if value>=threshold: score+=2; reasons.append(f"{value} {label} may help a utility setup")
  elif value: score+=1; reasons.append(f"Has {label}; demand depends on build")
 if not stats: verdict,action="no recognized jewel modifiers","manual_review"
 elif score>=5: verdict,action="notable jewel; compare within its stat category","compare_market"
 elif score: verdict,action="situational jewel; build and socket use matter","review_context"
 else: verdict,action="insufficient recognized premium modifiers","manual_review"
 return {"heuristic_score":score,"archetypes":sorted(kinds),"verdict":verdict,"recommended_action":action,"reasons":reasons,"confidence":"low","confidence_note":"Rule-based screening only; not confidence in market value.","disclaimer":"No build context or verified sale data is available; manually inspect before pricing."}

def parse_rune_request(text: str | None) -> list[dict[str,Any]]:
 if not text: return []
 names=r"(El|Eld|Tir|Nef|Eth|Ith|Tal|Ral|Ort|Thul|Amn|Sol|Shael|Dol|Hel|Io|Lum|Ko|Fal|Lem|Pul|Um|Mal|Ist|Gul|Vex|Ohm|Lo|Sur|Ber|Jah|Cham|Zod)"
 return [{"quantity":int(m.group(1)),"rune":m.group(2).title()} for m in re.finditer(rf"(\d+)\s*[xX]?\s*{names}\s*(?:rune)?\b",text,re.I)]

def analyze_listing(listing: dict[str,Any]) -> dict[str,Any] | None:
 extracted=extract_jewel_properties(str(listing.get("title") or ""),str(listing.get("visible_text") or ""))
 if extracted is None: return None
 trade=listing.get("i_give_text"); asking=listing.get("asking_price_text")
 return {**extracted,"price_observation":{"displayed_asking_price":asking or None,"requested_trade_text":trade or None,"requested_runes":parse_rune_request(trade),"price_kind":"asking_or_trade_request" if asking or trade else "not_observed","is_confirmed_sale":False,"numeric_estimate":None,"note":"Seller asks are not completed-sale prices; rune quantities are not converted into value."},"recommendation":recommend_jewel(extracted["stats"])}

def stat_similarity(left: dict[str,int], right: dict[str,int]) -> float:
 shared=set(left)&set(right)
 if not shared: return 0.0
 weight=sum(WEIGHTS[k] for k in shared)
 match=sum(WEIGHTS[k]*max(0.0,1-abs(left[k]-right[k])/(TOLERANCES[k]+1)) for k in shared)/weight
 coverage=weight/sum(WEIGHTS[k] for k in set(left)|set(right))
 return match*(0.65+0.35*coverage)

def comparable_offer_summary(db, stats: dict[str,int], exclude_observation_id: int | None=None) -> dict[str,Any]:
 rows=db.execute("SELECT observation_id,stats_json,requested_trade_text,displayed_asking_price FROM jewel_analyses ORDER BY observation_id DESC LIMIT 500").fetchall()
 candidates=[]
 for row in rows:
  if row["observation_id"]==exclude_observation_id: continue
  other=json.loads(row["stats_json"])
  if not (_archetypes(stats)&_archetypes(other)): continue
  similarity=stat_similarity(stats,other)
  if similarity>=0.55: candidates.append((similarity,row))
 candidates.sort(key=lambda x:x[0],reverse=True)
 offers=[{"observation_id":r["observation_id"],"similarity":round(sim,3),"requested_trade_text":r["requested_trade_text"],"displayed_asking_price":r["displayed_asking_price"]} for sim,r in candidates if r["requested_trade_text"] or r["displayed_asking_price"]]
 return {"matching_observation_count":len(candidates),"comparable_asking_offers":offers[:10],"price_estimate":None,"price_basis":"similar_listing_asks_only" if offers else "insufficient_comparables","warning":"Similarity is a rough stat filter. These are seller asks/trade requests, not verified sales or fair value."}
