import os, sys, time, json, keyboard, pyautogui, cv2, uuid, queue, threading
import hashlib
import sqlite3
from datetime import datetime, timezone
import numpy as np
from PIL import Image, ImageGrab
import pygetwindow as gw
from google import genai
from playwright.sync_api import sync_playwright
import re


# ---------------------------------------------------------------------------
# Embedded Traderie collector + local ring valuation (single-file runtime)
# ---------------------------------------------------------------------------
def start_embedded_collector():
    global _EMBEDDED_COLLECTOR_HTTPD
    if globals().get("_EMBEDDED_COLLECTOR_HTTPD") is not None:
        return
    import threading as _threading
    import types as _types
    _embedded_sources = {
    "jewel_analysis": "\"\"\"Structured extraction and conservative screening for Traderie jewels.\"\"\"\nfrom __future__ import annotations\nimport json, re\nfrom typing import Any\n\nSTAT_PATTERNS = {\n \"ias\":[r\"(?<!\\d)(\\d{1,2})\\s*%?\\s*(?:increased\\s+attack\\s+speed|ias)\\b\"],\n \"enhanced_damage\":[r\"(?<!\\d)(\\d{1,3})\\s*%?\\s*enhanced\\s+damage\\b\",r\"(?<!\\d)(\\d{1,3})\\s*%?\\s*ed\\b\"],\n \"max_damage\":[r\"[+]?\\s*(\\d{1,2})\\s*(?:to\\s+)?maximum\\s+damage\\b\",r\"[+]?\\s*(\\d{1,2})\\s*max\\s+damage\\b\",r\"\\+\\s*(\\d{1,2})\\s*max\\b\"],\n \"min_damage\":[r\"[+]?\\s*(\\d{1,2})\\s*(?:to\\s+)?minimum\\s+damage\\b\",r\"[+]?\\s*(\\d{1,2})\\s*min\\s+damage\\b\"],\n \"all_resist\":[r\"[+]?\\s*(\\d{1,2})\\s*(?:%\\s*)?to\\s+all\\s+resistances?\\b\"],\n \"life\":[r\"[+]?\\s*(\\d{1,3})\\s+to\\s+life\\b\"],\n \"fhr\":[r\"[+]?\\s*(\\d{1,2})\\s*%?\\s*faster\\s+hit\\s+recovery\\b\"],\n \"strength\":[r\"[+]?\\s*(\\d{1,2})\\s+to\\s+strength\\b\"],\n \"dexterity\":[r\"[+]?\\s*(\\d{1,2})\\s+to\\s+dexterity\\b\"],\n}\nPHYSICAL={\"ias\",\"enhanced_damage\",\"max_damage\",\"min_damage\"}\nUTILITY={\"all_resist\",\"life\",\"fhr\",\"strength\",\"dexterity\"}\nWEIGHTS={\"ias\":2.0,\"enhanced_damage\":2.0,\"max_damage\":1.5,\"min_damage\":1.0,\"all_resist\":1.5,\"life\":1.0,\"fhr\":1.5,\"strength\":1.0,\"dexterity\":1.0}\nTOLERANCES={\"ias\":5,\"enhanced_damage\":10,\"max_damage\":5,\"min_damage\":5,\"all_resist\":5,\"life\":5,\"fhr\":5,\"strength\":5,\"dexterity\":5}\n\ndef _first_match(text: str, patterns: list[str]) -> int | None:\n for pattern in patterns:\n  match=re.search(pattern,text,re.I)\n  if match: return int(match.group(1))\n return None\n\ndef extract_jewel_properties(title: str, visible_text: str) -> dict[str,Any] | None:\n raw=\" \".join(x for x in (title,visible_text) if x)\n if not re.search(r\"\\bjewel\\b\",raw,re.I): return None\n stats={k:v for k,p in STAT_PATTERNS.items() if (v:=_first_match(raw,p)) is not None}\n return {\"item_type\":\"jewel\",\"quality_hint\":next((q for q in (\"rare\",\"magic\",\"unique\") if re.search(rf\"\\b{q}\\b\",raw,re.I)),None),\"stats\":stats,\"raw_text\":raw[:4000],\"extraction_version\":2}\n\ndef _archetypes(stats: dict[str,int]) -> set[str]:\n kinds=set()\n if set(stats)&PHYSICAL: kinds.add(\"physical_damage\")\n if set(stats)&UTILITY: kinds.add(\"utility\")\n return kinds\n\ndef recommend_jewel(stats: dict[str,int]) -> dict[str,Any]:\n kinds=_archetypes(stats); score=0; reasons=[]\n checks=[(\"ias\",15,3,\"15% IAS is a notable offensive modifier\"),(\"enhanced_damage\",35,3,\"High Enhanced Damage\"),(\"max_damage\",10,2,\"Meaningful maximum damage\"),(\"min_damage\",10,2,\"Meaningful minimum damage\")]\n for key,threshold,points,reason in checks:\n  value=stats.get(key,0)\n  if value>=threshold: score+=points; reasons.append(reason)\n  elif value: score+=1; reasons.append(f\"{key.replace('_',' ').title()} may help a physical setup\")\n if stats.get(\"ias\",0)>=15 and stats.get(\"enhanced_damage\",0)>=30: reasons.append(\"IAS + Enhanced Damage is a relevant physical-jewel combination\")\n for key,threshold,label in [(\"all_resist\",10,\"All Resistances\"),(\"fhr\",7,\"Faster Hit Recovery\"),(\"life\",10,\"Life\"),(\"strength\",6,\"Strength\"),(\"dexterity\",6,\"Dexterity\")]:\n  value=stats.get(key,0)\n  if value>=threshold: score+=2; reasons.append(f\"{value} {label} may help a utility setup\")\n  elif value: score+=1; reasons.append(f\"Has {label}; demand depends on build\")\n if not stats: verdict,action=\"no recognized jewel modifiers\",\"manual_review\"\n elif score>=5: verdict,action=\"notable jewel; compare within its stat category\",\"compare_market\"\n elif score: verdict,action=\"situational jewel; build and socket use matter\",\"review_context\"\n else: verdict,action=\"insufficient recognized premium modifiers\",\"manual_review\"\n return {\"heuristic_score\":score,\"archetypes\":sorted(kinds),\"verdict\":verdict,\"recommended_action\":action,\"reasons\":reasons,\"confidence\":\"low\",\"confidence_note\":\"Rule-based screening only; not confidence in market value.\",\"disclaimer\":\"No build context or verified sale data is available; manually inspect before pricing.\"}\n\ndef parse_rune_request(text: str | None) -> list[dict[str,Any]]:\n \"\"\"Parse rune barter terms; a bare rune name means quantity one.\"\"\"\n if not text:\n  return []\n names=r\"(El|Eld|Tir|Nef|Eth|Ith|Tal|Ral|Ort|Thul|Amn|Sol|Shael|Dol|Hel|Io|Lum|Ko|Fal|Lem|Pul|Um|Mal|Ist|Gul|Vex|Ohm|Lo|Sur|Ber|Jah|Cham|Zod)\"\n pattern=rf\"(?<![A-Za-z])(?:(\\d+)\\s*[xX]?\\s*)?{names}(?:\\s*rune)?(?![A-Za-z])\"\n found=[]\n for match in re.finditer(pattern,text,re.I):\n  found.append({\"quantity\":int(match.group(1) or 1),\"rune\":match.group(2).title()})\n return found\n\ndef analyze_listing(listing: dict[str,Any]) -> dict[str,Any] | None:\n extracted=extract_jewel_properties(str(listing.get(\"title\") or \"\"),str(listing.get(\"visible_text\") or \"\"))\n if extracted is None: return None\n trade=listing.get(\"observed_trade_text\") or listing.get(\"i_give_text\") or listing.get(\"asking_price_text\")\n record_type=listing.get(\"record_type\") or \"unknown_listing_record\"\n is_sale=record_type==\"completed_sale_observation\"\n status=\"completed_sale_page_record\" if is_sale else (\"active_or_asking\" if record_type==\"active_listing_ask\" else \"unknown\")\n note=\"Completed-sales page record; displayed trade terms may overstate the actual deal.\" if is_sale else (\"Active listing asking terms; not a completed sale.\" if record_type==\"active_listing_ask\" else \"Trade direction could not be identified.\")\n return {**extracted,\"record_type\":record_type,\"trade_observation\":{\"displayed_asking_price\":None,\"observed_trade_text\":trade or None,\"observed_runes\":parse_rune_request(trade),\"price_kind\":\"observed_completed_sale_trade_terms\" if is_sale else (\"seller_asking_terms\" if record_type==\"active_listing_ask\" else \"unknown\"),\"transaction_status\":status,\"is_confirmed_sale\":is_sale,\"sale_price_reliability\":\"uncertain_possible_overstatement\" if is_sale else None,\"numeric_estimate\":None,\"note\":note},\"recommendation\":recommend_jewel(extracted[\"stats\"])}\n\ndef stat_similarity(left: dict[str,int], right: dict[str,int]) -> float:\n shared=set(left)&set(right)\n if not shared: return 0.0\n weight=sum(WEIGHTS[k] for k in shared)\n match=sum(WEIGHTS[k]*max(0.0,1-abs(left[k]-right[k])/(TOLERANCES[k]+1)) for k in shared)/weight\n coverage=weight/sum(WEIGHTS[k] for k in set(left)|set(right))\n return match*(0.65+0.35*coverage)\n\ndef comparable_offer_summary(db, stats: dict[str,int], exclude_observation_id: int | None=None) -> dict[str,Any]:\n rows=db.execute(\"SELECT observation_id,stats_json,requested_trade_text,displayed_asking_price FROM jewel_analyses ORDER BY observation_id DESC LIMIT 500\").fetchall()\n candidates=[]\n for row in rows:\n  if row[\"observation_id\"]==exclude_observation_id: continue\n  other=json.loads(row[\"stats_json\"])\n  if not (_archetypes(stats)&_archetypes(other)): continue\n  similarity=stat_similarity(stats,other)\n  if similarity>=0.55: candidates.append((similarity,row))\n candidates.sort(key=lambda x:x[0],reverse=True)\n offers=[{\"observation_id\":r[\"observation_id\"],\"similarity\":round(sim,3),\"requested_trade_text\":r[\"requested_trade_text\"],\"displayed_asking_price\":r[\"displayed_asking_price\"]} for sim,r in candidates if r[\"requested_trade_text\"] or r[\"displayed_asking_price\"]]\n return {\"matching_observation_count\":len(candidates),\"comparable_sale_observations\":offers[:10],\"comparable_asking_offers\":offers[:10],\"price_estimate\":None,\"price_basis\":\"similar_completed_sale_page_records_only\" if offers else \"insufficient_comparables\",\"warning\":\"Similarity is a rough stat filter. These are completed-sale page trade terms, but displayed values may overstate the true deal; not verified cash-equivalent fair value.\"}\n",
    "ring_analysis": "\"\"\"Blood-ring stat extraction and explainable quality scoring.\n\nBlood craft package: 15% of total score.\nFour random affix slots: 85% total, 21.25% each.\nAffix importance weights prevent inherently weak stats from scoring like FCR.\n\"\"\"\nfrom __future__ import annotations\nimport re\nfrom typing import Any\n\nPATTERNS = {\n \"fcr\":[r\"(\\d{1,2})\\s*%?\\s*(?:faster\\s+cast\\s+rate|fcr)\\b\"],\n \"life_leech\":[r\"(\\d{1,2})\\s*%?\\s*life\\s+(?:stolen|leech)\\s+per\\s+hit\",r\"(\\d{1,2})\\s*%?\\s*life\\s+leech\"],\n \"mana_leech\":[r\"(\\d{1,2})\\s*%?\\s*mana\\s+(?:stolen|leech)\\s+per\\s+hit\",r\"(\\d{1,2})\\s*%?\\s*mana\\s+leech\"],\n \"life\":[r\"[+]?([\\d]{1,3})\\s+to\\s+life\\b\"],\n  \"strength\":[r\"[+]?([\\d]{1,3})\\s+to\\s+strength\\b\"],\n \"dexterity\":[r\"[+]?([\\d]{1,2})\\s+to\\s+dexterity\\b\"],\n \"all_resist\":[r\"[+]?([\\d]{1,2})\\s+to\\s+all\\s+resistances?\\b\"],\n \"fire_resist\":[r\"[+]?([\\d]{1,2})[ \\t]*%?[ \\t]*(?:to[ \\t]+)?fire[ \\t]+resist\",r\"fire[ \\t]+resist[ \\t]*[+]?([\\d]{1,2})[ \\t]*%?\"],\n \"cold_resist\":[r\"[+]?([\\d]{1,2})[ \\t]*%?[ \\t]*(?:to[ \\t]+)?cold[ \\t]+resist\",r\"cold[ \\t]+resist[ \\t]*[+]?([\\d]{1,2})[ \\t]*%?\"],\n \"lightning_resist\":[r\"[+]?([\\d]{1,2})[ \\t]*%?[ \\t]*(?:to[ \\t]+)?lightning[ \\t]+resist\",r\"lightning[ \\t]+resist[ \\t]*[+]?([\\d]{1,2})[ \\t]*%?\"],\n \"poison_resist\":[r\"[+]?([\\d]{1,2})[ \\t]*%?[ \\t]*(?:to[ \\t]+)?poison[ \\t]+resist\",r\"poison[ \\t]+resist[ \\t]*[+]?([\\d]{1,2})[ \\t]*%?\"],\n \"poison_length_reduced\":[r\"poison\\s+length\\s+reduced\\s+by\\s+(\\d{1,3})\\s*%\"],\n \"mana\":[r\"[+]?([\\d]{1,3})\\s+to\\s+mana\\b\"],\n \"mana_per_kill\":[r\"([+]?\\d{1,2})\\s+mana\\s+after\\s+each\\s+kill\",r\"([+]?\\d{1,2})\\s+to\\s+mana\\s+after\\s+each\\s+kill\",r\"([+]?\\d{1,2})\\s+to\\s+mana\\s+per\\s+kill\"],\n \"attack_rating\":[r\"[+]?([\\d]{1,3})\\s+to\\s+attack\\s+rating\\b\"],\n \"min_damage\":[r\"[+]?([\\d]{1,2})\\s+to\\s+minimum\\s+damage\\b\"],\n \"max_damage\":[r\"[+]?([\\d]{1,2})\\s+to\\s+maximum\\s+damage\\b\"],\n \"damage_reduced\":[r\"damage\\s+reduced\\s+by\\s+(\\d{1,2})\"],\n \"magic_damage_reduced\":[r\"magic\\s+damage\\s+reduced\\s+by\\s+(\\d{1,2})\"],\n \"magic_find\":[r\"(\\d{1,2})\\s*%?\\s*better\\s+chance\\s+of\\s+getting\\s+magic\\s+items?\"],\n \"gold_find\":[r\"(\\d{1,3})\\s*%?\\s*(?:extra\\s+gold|gold\\s+find)\"],\n \"life_replenish\":[r\"replenish\\s+life\\s*\\+?\\s*(\\d{1,2})\",r\"\\+(\\d{1,2})\\s+replenish\\s+life\"],\n}\n\nFIXED_BLOOD_KEYS = {\"life_leech\", \"life\", \"strength\"}\nRANDOM_AFFIX_KEYS = (\n \"fcr\", \"mana_leech\", \"dexterity\", \"all_resist\", \"fire_resist\",\n \"cold_resist\", \"lightning_resist\", \"poison_resist\", \"mana\", \"mana_per_kill\",\n \"attack_rating\", \"min_damage\", \"max_damage\", \"damage_reduced\", \"magic_damage_reduced\", \"life\", \"strength\", \"life_leech\", \"magic_find\", \"gold_find\", \"life_replenish\", \"poison_length_reduced\",\n)\n# Relative market usefulness of a perfect roll. FCR is the benchmark.\n# These are transparent initial heuristics, not fitted market coefficients.\nAFFIX_IMPORTANCE = {\n \"fcr\":1.00, \"mana_leech\":0.90, \"all_resist\":0.85, \"mana_per_kill\":0.55,\n \"fire_resist\":0.85, \"cold_resist\":0.60, \"lightning_resist\":0.85, \"poison_resist\":0.50, \"poison_length_reduced\":0.35,\n \"dexterity\":0.75, \"strength\":0.90, \"life_leech\":0.95, \"mana\":0.55, \"attack_rating\":0.80,\n \"life_replenish\":0.0, \"magic_find\":0.20, \"gold_find\":0.08,\n \"min_damage\":1.00, \"max_damage\":1.00, \"damage_reduced\":0.12, \"magic_damage_reduced\":0.12,\n \"energy\":0.15, \"defense\":0.10, \"fhr\":0.25, \"ias\":0.65, \"damage_to_mana\":0.08, \"life\":0.65,\n}\n\ndef _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:\n return max(low, min(high, value))\n\ndef _affix_roll_quality(key: str, value: int) -> tuple[float, str]:\n \"\"\"Normalize an affix roll against its configured maximum (0..1).\"\"\"\n maxima = {\n  \"fcr\":10, \"mana\":50, \"mana_leech\":6, \"mana_per_kill\":1,\n  \"dexterity\":15, \"strength\":20, \"life_leech\":6, \"magic_find\":25,\n  \"gold_find\":100, \"life_replenish\":5, \"min_damage\":9, \"max_damage\":15,\n  \"damage_reduced\":2, \"magic_damage_reduced\":2, \"energy\":15,\n  \"defense\":100, \"fhr\":10, \"ias\":20, \"damage_to_mana\":12,\n  \"life\":40, \"all_resist\":11, \"fire_resist\":30, \"cold_resist\":30,\n  \"lightning_resist\":30, \"poison_resist\":30, \"attack_rating\":120,\n  \"poison_length_reduced\":25,\n }\n maximum=maxima.get(key)\n if not maximum:\n  return (0.0, f\"{key} has no configured roll benchmark\")\n if key in {\"fire_resist\", \"cold_resist\", \"lightning_resist\", \"poison_resist\"} and value < 15:\n  return ((value - 15) / 15.0, f\"{key} below 15 minimum useful roll\")\n range_text = \"60 to 120\" if key == \"attack_rating\" else f\"0 to {maximum}\"\n return (_clamp(value / maximum), f\"{key} roll normalized against maximum {maximum} (normalized against {maximum}; maximum {maximum}; range {range_text})\")\n\ndef blood_craft_quality(stats: dict[str, int]) -> float:\n \"\"\"Average Blood-package roll divided by its maximum possible value.\n\n The guaranteed Blood properties are life leech (max 3), life (max 20),\n and strength (max 5). Missing properties score zero; values are clamped.\n \"\"\"\n maxima = {\"life_leech\": 3, \"life\": 20, \"strength\": 5}\n qualities = [\n  _clamp(float(stats.get(key, 0)) / maximum)\n  for key, maximum in maxima.items()\n ]\n return sum(qualities) / len(maxima)\n\ndef _perfect_roll_bonus(key: str, value: int) -> float:\n \"\"\"Small bonus for hitting the configured maximum on a useful affix.\"\"\"\n maxima = {\n  \"fcr\":10, \"mana_leech\":6, \"all_resist\":11,\n  \"fire_resist\":30, \"cold_resist\":30, \"lightning_resist\":30,\n  \"poison_resist\":30, \"poison_length_reduced\":25, \"mana\":50,\n  \"dexterity\":15, \"strength\":20, \"attack_rating\":120,\n }\n return 1.0 if AFFIX_IMPORTANCE.get(key, 0.0) > 0 and maxima.get(key) == value else 0.0\n\n\ndef score_ring_stats(stats: dict[str, int], blood_craft: bool = True) -> tuple[float, list[str]]:\n \"\"\"Score the Blood package out of 15 plus four random affix slots worth 21.25 each.\"\"\"\n fixed_score = blood_craft_quality(stats) * 15.0 if blood_craft else 0.0\n reasons = [f\"Blood craft package: {fixed_score:.2f}/15 (life leech, life, strength rolls)\"]\n candidates = []\n for key in RANDOM_AFFIX_KEYS:\n  if key not in stats:\n   continue\n  if AFFIX_IMPORTANCE.get(key, 0.0) <= 0:\n   reasons.append(f\"{key} affix={stats[key]}: +0.00/21.25 (excluded from quality score; does not consume a random slot)\")\n   continue\n  raw_value = int(stats[key])\n  # Remove the guaranteed Blood craft portion before treating excess as a random affix.\n  value = (max(0, raw_value - 3) if blood_craft and key == \"life_leech\" else\n           max(0, raw_value - 5) if blood_craft and key == \"strength\" else\n           max(0, raw_value - 20) if blood_craft and key == \"life\" else raw_value)\n  if value <= 0 or AFFIX_IMPORTANCE.get(key, 0.0) <= 0:\n   continue\n  roll, explanation = _affix_roll_quality(key, value)\n  candidates.append((key, value, roll, explanation))\n # The item can contribute at most four random affixes. Each slot is worth 85/4;\n # unused slots remain zero rather than redistributing their points.\n candidates.sort(key=lambda item: item[2], reverse=True)\n chosen = candidates[:4]\n affix_score = 0.0\n for key, value, roll, explanation in chosen:\n  points = roll * 21.25\n  affix_score += points\n  reasons.append(\n   f\"{key} affix={value} (combined stat {stats[key]}): \"\n   f\"{points:+.2f}/21.25 ({explanation})\"\n  )\n for slot in range(4 - len(chosen)):\n  reasons.append(f\"Empty random affix slot {slot + 1}: 0/21.25\")\n total = _clamp(fixed_score + affix_score, 0.0, 100.0)\n reasons.append(f\"Total quality: {total:.2f}/100\")\n return total, reasons\n\n\n# Build profiles are deliberately separate from the universal roll score.\n# Initial weights are transparent heuristics and should be calibrated against\n# collected sales rather than treated as established market coefficients.\nBUILD_PROFILES = {\n \"javazon\": {\n  # Lightning Javazon: Sunder-related resistance pressure makes lightning\n  # resistance more valuable than fire resistance for this profile.\n  \"fcr\":1.00,\"mana_leech\":0.90,\"lightning_resist\":1.00,\"all_resist\":0.90,\n  \"attack_rating\":0.80,\"dexterity\":0.75,\"strength\":0.55,\"life\":0.40,\n  \"mana_per_kill\":0.35,\"fire_resist\":0.25,\"cold_resist\":0.30,\"poison_resist\":0.20,\n  \"life_leech\":0.10,\"mana\":0.25,\n },\n \"sorceress\": {\n  # Ordinary spellcaster: leech requires physical attack damage and is not\n  # counted as useful caster demand. Mana per Kill is preferred instead.\n  \"fcr\":1.00,\"mana\":0.90,\"mana_per_kill\":0.85,\"all_resist\":0.80,\n  \"lightning_resist\":0.70,\"fire_resist\":0.60,\"cold_resist\":0.60,\n  \"poison_resist\":0.45,\"life\":0.55,\"dexterity\":0.35,\"strength\":0.20,\n  \"mana_leech\":0.0,\"life_leech\":0.0,\"attack_rating\":0.0,\n },\n \"es_sorceress\": {\n  \"fcr\":1.00,\"mana\":1.00,\"poison_resist\":0.95,\n  \"poison_length_reduced\":0.90,\"strength\":0.45,\"dexterity\":0.50,\n  \"mana_per_kill\":0.75,\"all_resist\":0.10,\"life\":0.10,\n  \"mana_leech\":0.0,\"life_leech\":0.0,\"lightning_resist\":0.10,\n },\n \"melee\": {\n  # Melee values offensive stats most, while retaining defensive stats as\n  # useful secondary affixes rather than treating them as unusable.\n  \"attack_rating\":1.00,\"min_damage\":1.00,\"max_damage\":1.00,\n  \"life_leech\":0.95,\"mana_leech\":0.70,\"ias\":0.90,\n  \"strength\":0.90,\"dexterity\":0.85,\"life\":0.70,\n  \"all_resist\":0.65,\"lightning_resist\":0.50,\"fire_resist\":0.45,\n  \"cold_resist\":0.40,\"poison_resist\":0.30,\"mana\":0.20,\n  \"mana_per_kill\":0.20,\"fcr\":0.15,\"damage_reduced\":0.20,\"magic_damage_reduced\":0.20,\n  \"defense\":0.15,\"fhr\":0.20,\"life_replenish\":0.15,\n },\n \"general_caster\": {\n  \"fcr\":1.00,\"mana\":0.85,\"mana_per_kill\":0.80,\"all_resist\":0.80,\n  \"lightning_resist\":0.70,\"fire_resist\":0.60,\"cold_resist\":0.60,\n  \"poison_resist\":0.45,\"life\":0.55,\"dexterity\":0.35,\"strength\":0.20,\n  \"mana_leech\":0.0,\"life_leech\":0.0,\"attack_rating\":0.0,\n },\n}\n\ndef _profile_roll_quality(key: str, value: int) -> float:\n \"\"\"Normalize a stat for build-fit scoring without reusing market importance.\"\"\"\n if key == \"life_leech\":\n  return _clamp(value / 9.0)\n if key == \"life\":\n  return _clamp((value - 10.0) / 10.0)\n if key == \"strength\":\n  return _clamp(value / 25.0)\n if key == \"mana_per_kill\":\n  return _clamp(value / 1.0)\n return max(0.0, _affix_roll_quality(key, int(value))[0])\n\ndef build_demand_analysis(stats: dict[str, int]) -> dict[str, Any]:\n \"\"\"Score every overlapping build audience; profiles are not exclusive labels.\"\"\"\n scores = {}\n for profile, weights in BUILD_PROFILES.items():\n  if profile == \"es_sorceress\" and stats.get(\"fcr\") != 10:\n   scores[profile] = {\"score\": 0.0, \"useful_stats\": [],\n                      \"blocked_reason\": \"requires 10 FCR on the ring\"}\n   continue\n  candidates = []\n  for key, weight in weights.items():\n   if key in stats and weight > 0:\n    candidates.append((_profile_roll_quality(key, int(stats[key])) * weight,\n                       weight, key, int(stats[key])))\n  candidates.sort(key=lambda item: item[0], reverse=True)\n  selected = candidates[:4]\n  denominator = sum(item[1] for item in selected) or 1.0\n  score = 100.0 * sum(item[0] for item in selected) / denominator\n  scores[profile] = {\n   \"score\": round(_clamp(score, 0.0, 100.0), 2),\n   \"useful_stats\": [item[2] for item in selected],\n   \"stat_contributions\": [\n    {\"stat\": item[2], \"value\": item[3], \"weight\": item[1],\n     \"normalized_roll\": round(_profile_roll_quality(item[2], item[3]), 3),\n     \"contribution\": round(item[0], 3)}\n    for item in selected\n   ],\n  }\n # Mana per Kill is a caster signal; use it only to break exact score ties.\n ranked = sorted(\n  scores.items(),\n  key=lambda item: (\n   item[1][\"score\"],\n   1 if item[0] in {\"sorceress\", \"general_caster\"} and stats.get(\"mana_per_kill\", 0) > 0 else 0,\n  ),\n  reverse=True,\n )\n viable = [name for name, result in ranked if result[\"score\"] >= 40.0]\n return {\n  \"profiles\": scores,\n  \"ranked_profiles\": [name for name, _ in ranked],\n  \"best_profile\": ranked[0][0] if ranked else None,\n  \"best_score\": ranked[0][1][\"score\"] if ranked else 0.0,\n  \"viable_profile_count\": len(viable),\n  \"viable_profiles\": viable,\n  \"demand_tier\": (\"broad\" if len(viable) >= 3 else\n                  \"multi_build\" if len(viable) == 2 else\n                  \"niche\" if len(viable) == 1 else \"weak\"),\n }\n\nBUILD_TARGETS = {\n \"javazon\": {\"fcr\":10,\"mana_leech\":4,\"lightning_resist\":20,\"all_resist\":8,\"attack_rating\":80},\n \"sorceress\": {\"fcr\":10,\"mana\":35,\"mana_per_kill\":1,\"all_resist\":8,\"lightning_resist\":20},\n \"es_sorceress\": {\"fcr\":10,\"mana\":35,\"poison_resist\":20,\"poison_length_reduced\":25,\"strength\":5,\"dexterity\":10},\n \"melee\": {\"life_leech\":3,\"strength\":5,\"dexterity\":10,\"attack_rating\":80,\"all_resist\":8},\n \"general_caster\": {\"fcr\":10,\"mana\":35,\"mana_per_kill\":1,\"all_resist\":8,\"life\":15},\n}\n\ndef build_recommendation(stats: dict[str, int]) -> dict[str, Any]:\n \"\"\"Return overlapping build audiences and explain their strongest stat matches.\"\"\"\n demand = build_demand_analysis(stats)\n ranked = demand[\"ranked_profiles\"]\n best = demand[\"best_profile\"]\n score = float(demand[\"best_score\"])\n recommendations = []\n for name in demand[\"viable_profiles\"]:\n  profile_result = demand[\"profiles\"][name]\n  targets = BUILD_TARGETS.get(name, {})\n  met = [key for key, minimum in targets.items()\n         if stats.get(key) is not None and stats[key] >= minimum]\n  coverage = len(met) / len(targets) if targets else 0.0\n  # A high fit score with some target coverage is enough to show a recommendation.\n  # Overlapping audiences are intentional; do not force a single winner.\n  if profile_result[\"score\"] >= 40.0 and coverage >= 0.60:\n   recommendations.append({\n    \"build\": name, \"fit_score\": profile_result[\"score\"],\n    \"target_coverage\": round(coverage, 3),\n    \"useful_stats\": profile_result.get(\"useful_stats\", []),\n    \"stat_contributions\": profile_result.get(\"stat_contributions\", []),\n    \"met_targets\": met,\n   })\n recommendations.sort(key=lambda item: item[\"fit_score\"], reverse=True)\n candidate = recommendations[0][\"build\"] if recommendations else best\n target = BUILD_TARGETS.get(candidate, {}) if candidate else {}\n met = []\n missing = []\n below = []\n for key, minimum in target.items():\n  actual = stats.get(key)\n  if actual is None:\n   missing.append({\"stat\": key, \"target\": minimum})\n  elif actual >= minimum:\n   met.append({\"stat\": key, \"actual\": actual, \"target\": minimum})\n  else:\n   below.append({\"stat\": key, \"actual\": actual, \"target\": minimum,\n                 \"gap\": minimum - actual})\n return {\n  \"recommended_build\": candidate if recommendations else None,\n  \"recommendations\": recommendations,\n  \"best_candidate\": best,\n  \"fit_score\": round(score, 2),\n  \"target_coverage\": round(len(met) / len(target), 3) if target else 0.0,\n  \"confidence\": \"heuristic\",\n  \"demand_tier\": demand[\"demand_tier\"],\n  \"viable_profiles\": demand[\"viable_profiles\"],\n  \"ranked_profiles\": [\n   {\"build\": name, \"fit_score\": demand[\"profiles\"][name][\"score\"],\n    \"useful_stats\": demand[\"profiles\"][name][\"useful_stats\"]}\n   for name in ranked\n  ],\n  \"target_benchmark\": {\n   \"targets\": target, \"met\": met, \"below_target\": below,\n   \"missing\": missing, \"completion_count\": len(met),\n   \"target_count\": len(target),\n  },\n  \"summary\": (\n   \"Matching build audiences: \" + \", \".join(x[\"build\"] for x in recommendations)\n   if recommendations else\n   (\"No build profile reached the recommendation threshold; fallback remains quality-based.\"\n    if best else \"No build profile could be evaluated.\")\n  ),\n  \"caveat\": \"Build weights and target rolls are transparent initial heuristics, not market-trained prices. Mana/life leech have zero ordinary-caster demand weight; Lightning Javazon prioritizes lightning resistance. ES Sorceress requires 10 FCR on the ring.\",\n}\n\ndef ring_quality_features(stats: dict[str,int]) -> set[str]:\n thresholds={\"mana_leech\":4,\"life_leech\":3,\"dexterity\":5,\"strength\":5,\"life\":15,\"attack_rating\":100,\"all_resist\":10}\n return {key for key,minimum in thresholds.items() if stats.get(key,0)>=minimum}\n\ndef ring_quality_gap(target: dict[str,int], comparable: dict[str,int]) -> dict[str,Any]:\n target_features=ring_quality_features(target)\n comparable_features=ring_quality_features(comparable)\n missing=sorted(comparable_features-target_features)\n extra=sorted(target_features-comparable_features)\n return {\"target_features\":sorted(target_features),\"comparable_features\":sorted(comparable_features),\n  \"missing_from_target\":missing,\"missing_from_comparable\":extra,\n  \"mismatch_count\":len(missing)+len(extra),\"penalty\":round(0.12*(len(missing)+len(extra)),4)}\n\ndef extract_ring_properties(title: str, visible_text: str) -> dict[str,Any] | None:\n raw=\" \".join(x for x in (title,visible_text) if x)\n if not re.search(r\"\\bring\\b\",raw,re.I): return None\n stats={}\n for key,patterns in PATTERNS.items():\n  matches=[]\n  seen_spans=set()\n  for pattern in patterns:\n   for match in re.finditer(pattern,raw,re.I):\n    if match.span() not in seen_spans:\n     matches.append(match)\n     seen_spans.add(match.span())\n  if matches:\n   # Blood craft Life Leech and Strength may be merged with random affixes.\n   stats[key]=(sum(int(m.group(1)) for m in matches)\n               if key in {\"life_leech\", \"strength\", \"life\"} else int(matches[0].group(1)))\n blood_candidate=stats.get(\"life_leech\",0)>0\n fcr=stats.get(\"fcr\")\n blood_tag=bool(re.search(r\"\\bblood\\s+ring\\b\",title,re.I))\n score,reasons=score_ring_stats(stats,blood_craft=blood_tag)\n if score>=80: verdict=\"excellent ring; prioritize high-end completed-sale comparisons\"\n elif score>=55: verdict=\"promising ring; value depends on affix combination and market sales\"\n elif score>=35: verdict=\"situational ring; use distance-weighted completed sales\"\n else: verdict=\"low-quality ring; conservative fallback unless sales show otherwise\"\n valid_blood_fcr=fcr is None or fcr==10\n random_affixes=[]\n for key in RANDOM_AFFIX_KEYS:\n  if key not in stats:\n   continue\n  fixed_base=(3 if key==\"life_leech\" else 5 if key==\"strength\" else 20 if key==\"life\" else 0)\n  random_value=max(0,stats[key]-fixed_base) if blood_tag and key in FIXED_BLOOD_KEYS else stats[key]\n  if random_value>0:\n   random_affixes.append(key)\n weak=sum(1 for key in random_affixes if _affix_roll_quality(key,stats[key])[0]*AFFIX_IMPORTANCE[key]<0.15)\n poor=(score<65.0 or (len(random_affixes)>=3 and (weak>=2 or sum(_affix_roll_quality(k,stats[k])[0]*AFFIX_IMPORTANCE[k] for k in random_affixes)/len(random_affixes)<0.35)))\n return {\"item_type\":\"ring\",\"craft_type\":\"blood_candidate\" if blood_candidate and valid_blood_fcr else \"unknown_or_other\",\n  \"stats\":stats,\"heuristic_score\":score,\"quality_score_percent\":score,\"verdict\":verdict,\"reasons\":reasons,\n  \"random_affixes\":random_affixes,\"random_affix_count\":len(random_affixes),\"poor_stat_combination\":poor,\n  \"confidence\":\"low\",\"fcr_valid_for_blood_ring\":valid_blood_fcr,\"raw_text\":raw[:4000],\"extraction_version\":9}\n",
    "valuation": "\"\"\"Transparent rune-to-Perfect-Skull conversion helpers.\n\nConfigured rates supplied by the user:\n1 Ist = 15 Pskulls; 1 Jah = 15 Ist = 225 Pskulls.\n1 Ber = 0.95 Jah; 1 Cham = 0.8 Jah.\nOther unknown rune rates remain unknown rather than being guessed.\n\"\"\"\nfrom __future__ import annotations\n\nIST_VALUE_PSKULLS = 15\nDEFAULT_RUNE_VALUES_PSKULLS = {\n    \"Ist\": 15,\n    \"Jah\": 225,\n    \"Ber\": 213.75,  # 0.95 Jah\n    \"Cham\": 180,    # 0.8 Jah\n    \"Perfect Skull\": 1,\n    \"Pskull\": 1,\n    \"Pskulls\": 1,\n}\n\ndef normalize_rune_name(name: str) -> str:\n    return name.strip().title()\n\n\ndef format_pskull_value(value: float | int | None) -> str | None:\n    \"\"\"Format small values in Pskulls and large values as Ist + Pskull remainder.\n\n    Up to 2 Ist, exact Ist multiples retain the legacy two-decimal display;\n    non-multiples stay in Pskulls. Above 2 Ist, use whole Ist plus remainder.\n    \"\"\"\n    if value is None:\n        return None\n    amount = round(float(value), 4)\n    if amount < 0:\n        raise ValueError(\"value cannot be negative\")\n    if amount > 2 * IST_VALUE_PSKULLS:\n        whole_ist = int(amount // IST_VALUE_PSKULLS)\n        remainder = round(amount - whole_ist * IST_VALUE_PSKULLS, 4)\n        if remainder == 0:\n            return f\"{whole_ist} Ist\"\n        return f\"{whole_ist} Ist + {remainder:g} Pskulls\"\n    if amount == 2 * IST_VALUE_PSKULLS:\n        return \"2 Ist\"\n    if amount >= IST_VALUE_PSKULLS and amount % IST_VALUE_PSKULLS == 0:\n        return f\"{amount / IST_VALUE_PSKULLS:.2f} Ist\"\n    return f\"{amount:g} Pskulls\"\n\ndef rune_bundle_value_pskulls(runes: list[dict], rates: dict[str, float] | None = None) -> dict:\n    if not runes:\n        return {\"value_pskulls\": None, \"display\": None, \"missing_rune_rates\": [],\n                \"ist_anchor_pskulls\": IST_VALUE_PSKULLS}\n    table = dict(DEFAULT_RUNE_VALUES_PSKULLS)\n    if rates:\n        table.update({normalize_rune_name(k): float(v) for k, v in rates.items()})\n    total = 0.0\n    missing = []\n    for item in runes:\n        name = normalize_rune_name(str(item.get(\"rune\", \"\")))\n        qty = int(item.get(\"quantity\", 0))\n        if qty < 0:\n            raise ValueError(\"rune quantity cannot be negative\")\n        if name not in table:\n            missing.append(name)\n        else:\n            total += qty * table[name]\n    if missing:\n        return {\"value_pskulls\": None, \"display\": None,\n                \"missing_rune_rates\": sorted(set(missing)),\n                \"ist_anchor_pskulls\": IST_VALUE_PSKULLS}\n    display = format_pskull_value(total)\n    return {\"value_pskulls\": round(total, 4), \"display\": display,\n            \"missing_rune_rates\": [], \"ist_anchor_pskulls\": IST_VALUE_PSKULLS}\n",
    "phase2_rarity_valuation": "\"\"\"Phase 2 quality/rarity price calibration.\n\nThe market-quality prior is centered at 85. The central 85% interval is\n75..95, so sigma is derived from the normal 7.5th/92.5th percentiles.\nBelow the peak, quality scales value down. Above the peak, rarity creates\na premium using the inverse normal-density ratio. Actual completed sales\ncalibrate the market's baseline price; no sale price is hardcoded.\n\"\"\"\nfrom __future__ import annotations\n\nfrom math import exp\n\nMARKET_SCORE_CENTER = 85.0\nMARKET_CENTRAL_SHARE = 0.85\nMARKET_CENTRAL_HALF_WIDTH = 10.0\nNORMAL_CENTRAL_85_Z = 1.4395314709384563\nMARKET_SCORE_SIGMA = MARKET_CENTRAL_HALF_WIDTH / NORMAL_CENTRAL_85_Z\n\n\ndef quality_rarity_index(score: float) -> float:\n    \"\"\"Relative price index: quality discount below 85, rarity premium above.\"\"\"\n    score = max(0.0, min(100.0, float(score)))\n    if score <= MARKET_SCORE_CENTER:\n        return max(0.05, score / MARKET_SCORE_CENTER)\n    z = (score - MARKET_SCORE_CENTER) / MARKET_SCORE_SIGMA\n    return exp(0.5 * z * z)\n\n\ndef weighted_quantile(values: list[tuple[float, float]], q: float) -> float | None:\n    \"\"\"Weighted quantile over (value, positive weight) pairs.\"\"\"\n    valid = sorted((float(v), max(0.0, float(w))) for v, w in values if w > 0)\n    total = sum(w for _, w in valid)\n    if not valid or total <= 0:\n        return None\n    threshold = min(1.0, max(0.0, float(q))) * total\n    running = 0.0\n    for value, weight in valid:\n        running += weight\n        if running >= threshold:\n            return value\n    return valid[-1][0]\n\n\ndef estimate_phase2_rarity_price(target_score: float, sales: list[dict]) -> dict:\n    \"\"\"Calibrate price from completed-sale anchors and target score rarity.\n\n    Each sale requires value and heuristic_score; weight is optional.\n    Each observed sale implies a baseline price after normalizing for its\n    score's rarity. The weighted median baseline resists outlier sales.\n    \"\"\"\n    anchors = []\n    for sale in sales:\n        try:\n            price = float(sale[\"value\"])\n            score = float(sale[\"heuristic_score\"])\n            weight = float(sale.get(\"weight\", 1.0))\n        except (KeyError, TypeError, ValueError):\n            continue\n        if price <= 0 or weight <= 0 or not 0 <= score <= 100:\n            continue\n        index = quality_rarity_index(score)\n        anchors.append({\n            \"observation_id\": sale.get(\"observation_id\"),\n            \"sale_price\": price,\n            \"sale_quality_score\": score,\n            \"rarity_index\": index,\n            \"implied_base_price\": price / index,\n            \"weight\": weight,\n        })\n\n    if not anchors:\n        return {\n            \"status\": \"insufficient_anchors\",\n            \"target_quality_score\": float(target_score),\n            \"anchor_count\": 0,\n            \"baseline_median\": None,\n            \"low\": None, \"median\": None, \"high\": None,\n            \"anchors\": [],\n        }\n\n    baseline_values = [(a[\"implied_base_price\"], a[\"weight\"]) for a in anchors]\n    baseline = weighted_quantile(baseline_values, 0.50)\n    base_low = weighted_quantile(baseline_values, 0.25)\n    base_high = weighted_quantile(baseline_values, 0.75)\n    target_index = quality_rarity_index(target_score)\n    return {\n        \"status\": \"estimate_available\",\n        \"target_quality_score\": float(target_score),\n        \"market_score_center\": MARKET_SCORE_CENTER,\n        \"market_central_share\": MARKET_CENTRAL_SHARE,\n        \"market_central_range\": [\n            MARKET_SCORE_CENTER - MARKET_CENTRAL_HALF_WIDTH,\n            MARKET_SCORE_CENTER + MARKET_CENTRAL_HALF_WIDTH,\n        ],\n        \"normal_sigma\": MARKET_SCORE_SIGMA,\n        \"target_rarity_index\": target_index,\n        \"anchor_count\": len(anchors),\n        \"baseline_median\": baseline,\n        \"low\": base_low * target_index if base_low is not None else None,\n        \"median\": baseline * target_index,\n        \"high\": base_high * target_index if base_high is not None else None,\n        \"anchors\": anchors,\n    }\n",
    "_d2_embedded_collector_server": "\"\"\"Loopback-only passive Traderie collector and local market-learning API.\"\"\"\nfrom __future__ import annotations\nimport json, os, sqlite3\nfrom statistics import median\nfrom datetime import datetime, timezone\nfrom http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\nfrom pathlib import Path\nfrom urllib.parse import urlparse, parse_qs, urljoin\nfrom jewel_analysis import analyze_listing, comparable_offer_summary, parse_rune_request\nfrom ring_analysis import extract_ring_properties, score_ring_stats, ring_quality_gap, build_demand_analysis, build_recommendation, BUILD_PROFILES\nfrom valuation import rune_bundle_value_pskulls, format_pskull_value\nfrom phase2_rarity_valuation import estimate_phase2_rarity_price\n\nROOT=Path(__file__).resolve().parent\nDB_PATH=Path(os.environ.get(\"TRADERIE_WATCHER_DB\",ROOT/\"traderie_observations.sqlite3\"))\nHOST=\"127.0.0.1\"; PORT=8765; MAX_BODY=256_000\nALLOWED_ORIGIN_PREFIX=\"chrome-extension://\"\n\ndef connect():\n db=sqlite3.connect(DB_PATH); db.row_factory=sqlite3.Row; return db\n\ndef directional_sale_penalty(target_score, sale_score, threshold=10.0, decay=0.12):\n \"\"\"Discount a sale only when its ring/build score exceeds the target's.\n\n A target stronger than the sale receives no directional penalty. The first\n threshold points of weakness are tolerated; additional gap decays the sale's\n statistical influence exponentially.\n \"\"\"\n weaker_by=max(0.0,float(sale_score)-float(target_score))\n excess=max(0.0,weaker_by-float(threshold))\n penalty=__import__(\"math\").exp(-float(decay)*excess)\n return {\"weaker_by\":round(weaker_by,2),\"excess\":round(excess,2),\n         \"penalty\":round(penalty,4),\"threshold\":float(threshold)}\n\n\ndef is_completed_sale_listing(listing):\n # Traderie completed-sale cards use \"They Give\" for the item and \"I Give\"\n # for the seller-entered final trade price. Legacy collector stored the\n # completed-sale classification as listing_type=\"barter_offer\".\n kind=listing.get(\"record_type\")\n status=listing.get(\"transaction_status\")\n if kind==\"completed_sale_observation\" or status==\"completed_sale_page_record\":\n  return True\n if kind or status:\n  return False\n legacy_type=listing.get(\"listing_type\")\n they_give=str(listing.get(\"they_give_text\") or \"\").strip()\n i_give=str(listing.get(\"i_give_text\") or \"\").strip()\n visible=str(listing.get(\"visible_text\") or \"\")\n has_both_labels=(\"They Give\" in visible and \"I Give\" in visible)\n return legacy_type==\"barter_offer\" and bool(they_give and i_give and has_both_labels)\n\n\ndef initialize():\n DB_PATH.parent.mkdir(parents=True,exist_ok=True)\n with connect() as db:\n  db.executescript(\"\"\"\n  PRAGMA journal_mode=WAL;\n  CREATE TABLE IF NOT EXISTS observations (\n   id INTEGER PRIMARY KEY AUTOINCREMENT, observation_type TEXT NOT NULL,\n   captured_at TEXT NOT NULL, source_url TEXT NOT NULL, page_context_json TEXT,\n   listing_key TEXT, listing_title TEXT, asking_price_text TEXT, visible_text TEXT,\n   payload_json TEXT NOT NULL);\n  CREATE INDEX IF NOT EXISTS idx_observations_captured_at ON observations(captured_at);\n  CREATE INDEX IF NOT EXISTS idx_observations_listing_key ON observations(listing_key);\n  CREATE TABLE IF NOT EXISTS jewel_analyses (\n   id INTEGER PRIMARY KEY AUTOINCREMENT, observation_id INTEGER NOT NULL UNIQUE REFERENCES observations(id),\n   analyzed_at TEXT NOT NULL, item_type TEXT NOT NULL, quality_hint TEXT,\n   stats_json TEXT NOT NULL, recommendation_json TEXT NOT NULL,\n   displayed_asking_price TEXT, requested_trade_text TEXT, raw_text TEXT NOT NULL);\n  CREATE INDEX IF NOT EXISTS idx_jewel_analyses_stats ON jewel_analyses(stats_json);\n  CREATE TABLE IF NOT EXISTS ring_analyses (\n   id INTEGER PRIMARY KEY AUTOINCREMENT, observation_id INTEGER NOT NULL UNIQUE REFERENCES observations(id),\n   analyzed_at TEXT NOT NULL, craft_type TEXT, stats_json TEXT NOT NULL,\n   analysis_json TEXT NOT NULL, raw_text TEXT NOT NULL);\n  CREATE TABLE IF NOT EXISTS verified_sales (\n   id INTEGER PRIMARY KEY AUTOINCREMENT, observation_id INTEGER NOT NULL REFERENCES observations(id),\n   sold_at TEXT NOT NULL, recorded_at TEXT NOT NULL, sale_price_text TEXT NOT NULL,\n   sale_runes_json TEXT NOT NULL DEFAULT '[]', sale_value_pskulls REAL,\n   verification_method TEXT NOT NULL, evidence_note TEXT,\n   verified INTEGER NOT NULL CHECK(verified=1));\n  CREATE INDEX IF NOT EXISTS idx_verified_sales_observation ON verified_sales(observation_id);\n  \"\"\")\n  cols={r[\"name\"] for r in db.execute(\"PRAGMA table_info(jewel_analyses)\")}\n  if \"requested_runes_json\" not in cols:\n   db.execute(\"ALTER TABLE jewel_analyses ADD COLUMN requested_runes_json TEXT NOT NULL DEFAULT '[]'\")\n  # Backfill previously captured listings so existing blood rings are analyzed.\n  existing={r[\"observation_id\"] for r in db.execute(\"SELECT observation_id FROM ring_analyses\")}\n  old_rows=db.execute(\"SELECT id,payload_json FROM observations WHERE observation_type='listing_snapshot' ORDER BY id\").fetchall()\n  for old in old_rows:\n   try:\n    payload=json.loads(old[\"payload_json\"])\n    listing=payload.get(\"listing\") if isinstance(payload,dict) else None\n    if not isinstance(listing,dict): continue\n    jewel_row=db.execute(\"SELECT requested_runes_json FROM jewel_analyses WHERE observation_id=?\",(old[\"id\"],)).fetchone()\n    if jewel_row and not jewel_row[\"requested_runes_json\"]:\n     parsed_runes=parse_rune_request(listing.get(\"i_give_text\"))\n     db.execute(\"UPDATE jewel_analyses SET requested_runes_json=? WHERE observation_id=?\",\n      (json.dumps(parsed_runes,ensure_ascii=False),old[\"id\"]))\n    # Re-analyze old snapshots on startup so newly supported stats (Dexterity,\n    # Magic Find, Gold Find) are populated in the existing local database too.\n    ring=extract_ring_properties(str(listing.get(\"title\") or \"\"),str(listing.get(\"visible_text\") or \"\"))\n    if ring:\n     db.execute(\"\"\"INSERT INTO ring_analyses(observation_id,analyzed_at,craft_type,stats_json,analysis_json,raw_text)\n      VALUES(?,?,?,?,?,?)\n      ON CONFLICT(observation_id) DO UPDATE SET analyzed_at=excluded.analyzed_at,\n       craft_type=excluded.craft_type,stats_json=excluded.stats_json,\n       analysis_json=excluded.analysis_json,raw_text=excluded.raw_text\"\"\",\n      (old[\"id\"],datetime.now(timezone.utc).isoformat(),ring[\"craft_type\"],\n       json.dumps(ring[\"stats\"],sort_keys=True),json.dumps(ring,ensure_ascii=False),ring[\"raw_text\"]))\n   except (ValueError,TypeError,json.JSONDecodeError):\n    continue\n\nclass Handler(BaseHTTPRequestHandler):\n server_version=\"TraderieLocalCollector/0.2\"\n def _json(self,status,data):\n  body=json.dumps(data,ensure_ascii=False).encode()\n  self.send_response(status); self.send_header(\"Content-Type\",\"application/json; charset=utf-8\")\n  self.send_header(\"Content-Length\",str(len(body)))\n  origin=self.headers.get(\"Origin\",\"\")\n  if origin.startswith(ALLOWED_ORIGIN_PREFIX):\n   self.send_header(\"Access-Control-Allow-Origin\",origin); self.send_header(\"Vary\",\"Origin\")\n   self.send_header(\"Access-Control-Allow-Methods\",\"POST, GET, OPTIONS\")\n   self.send_header(\"Access-Control-Allow-Headers\",\"Content-Type\")\n  self.end_headers(); self.wfile.write(body)\n def _body(self):\n  n=int(self.headers.get(\"Content-Length\",\"0\"))\n  if n<=0 or n>MAX_BODY: raise ValueError(\"invalid request size\")\n  value=json.loads(self.rfile.read(n))\n  if not isinstance(value,dict): raise ValueError(\"JSON object required\")\n  return value\n def do_OPTIONS(self): self._json(204,{})\n def do_GET(self):\n  path=urlparse(self.path); params=parse_qs(path.query)\n  try: limit=min(max(int(params.get(\"limit\",[\"50\"])[0]),1),200)\n  except ValueError: self._json(400,{\"error\":\"invalid limit\"}); return\n  if path.path==\"/health\":\n   self._json(200,{\"ok\":True,\"database\":str(DB_PATH)}); return\n  if path.path==\"/debug/ring-sales\":\n   with connect() as db:\n    total=db.execute(\"SELECT COUNT(*) FROM observations WHERE observation_type='listing_snapshot'\").fetchone()[0]\n    ring_total=db.execute(\"SELECT COUNT(*) FROM ring_analyses\").fetchone()[0]\n    blood_total=db.execute(\"SELECT COUNT(*) FROM ring_analyses WHERE craft_type='blood_candidate'\").fetchone()[0]\n    rows=db.execute(\"\"\"SELECT o.id,o.listing_key,o.source_url,o.page_context_json,o.payload_json,ra.stats_json,ra.craft_type\n      FROM observations o LEFT JOIN ring_analyses ra ON ra.observation_id=o.id\n      WHERE o.observation_type='listing_snapshot' ORDER BY o.id DESC\"\"\").fetchall()\n   counts={\"listing_snapshots\":total,\"ring_analyses\":ring_total,\"blood_candidates\":blood_total,\n    \"record_types\":{},\"completed_sale_records\":0,\"completed_blood_records\":0,\n    \"parseable_rune_prices\":0,\"matching_fcr_10\":0,\"matching_fcr_10_and_two_stats\":0}\n   samples=[]\n   for row in rows:\n    try:\n     payload=json.loads(row[\"payload_json\"]); listing=payload.get(\"listing\") or {}\n     kind=listing.get(\"record_type\") or \"missing\"\n     counts[\"record_types\"][kind]=counts[\"record_types\"].get(kind,0)+1\n     is_sale=is_completed_sale_listing(listing)\n     if not is_sale and len(samples)<8:\n      samples.append({\"observation_id\":row[\"id\"],\"reason\":\"not_classified_as_sale\",\n       \"listing_key\":row[\"listing_key\"],\"title\":listing.get(\"title\"),\n       \"source_url\":row[\"source_url\"],\"page_context\":json.loads(row[\"page_context_json\"] or \"{}\"),\n       \"listing_fields\":sorted(listing.keys()),\n       \"record_type\":listing.get(\"record_type\"),\"listing_type\":listing.get(\"listing_type\"),\n       \"transaction_status\":listing.get(\"transaction_status\"),\n       \"visible_text\":str(listing.get(\"visible_text\") or \"\")[:1800]})\n     if is_sale:\n      counts[\"completed_sale_records\"]+=1\n      if row[\"craft_type\"]!=\"blood_candidate\": continue\n      counts[\"completed_blood_records\"]+=1\n      trade=(listing.get(\"i_give_text\") or listing.get(\"observed_trade_text\") or \"\").strip()\n      parsed=parse_rune_request(trade); value=rune_bundle_value_pskulls(parsed)\n      if value[\"value_pskulls\"] is None: \n       if len(samples)<8: samples.append({\"observation_id\":row[\"id\"],\"reason\":\"unparsed_or_unknown_price\",\"trade_text\":trade,\"parsed_runes\":parsed})\n       continue\n      counts[\"parseable_rune_prices\"]+=1\n      stats=json.loads(row[\"stats_json\"] or \"{}\")\n      if stats.get(\"fcr\")==10:\n       counts[\"matching_fcr_10\"]+=1\n       if len(stats)>=2: counts[\"matching_fcr_10_and_two_stats\"]+=1\n      if len(samples)<8: samples.append({\"observation_id\":row[\"id\"],\"reason\":\"parsed\",\"trade_text\":trade,\"parsed_runes\":parsed,\"price_pskulls\":value[\"value_pskulls\"],\"stats\":stats})\n    except (ValueError,TypeError,KeyError,json.JSONDecodeError):\n     continue\n   self._json(200,{\"ok\":True,\"database\":str(DB_PATH),\"counts\":counts,\"samples\":samples}); return\n  if path.path==\"/jewels\":\n   with connect() as db:\n    rows=db.execute(\"\"\"SELECT j.*,o.listing_key,o.listing_title,o.source_url,o.captured_at\n      FROM jewel_analyses j JOIN observations o ON o.id=j.observation_id\n      ORDER BY j.id DESC LIMIT ?\"\"\",(limit,)).fetchall()\n    out=[]\n    for r in rows:\n     stats=json.loads(r[\"stats_json\"]); runes=json.loads(r[\"requested_runes_json\"] or \"[]\")\n     out.append({\"observation_id\":r[\"observation_id\"],\"listing_title\":r[\"listing_title\"],\n      \"listing_url\":urljoin(r[\"source_url\"],r[\"listing_key\"]) if r[\"listing_key\"] else r[\"source_url\"],\n      \"captured_at\":r[\"captured_at\"],\"quality_hint\":r[\"quality_hint\"],\"stats\":stats,\n      \"sale_observation\":{\"observed_trade_text\":r[\"requested_trade_text\"],\"observed_runes\":runes,\n       \"observed_rune_value\":rune_bundle_value_pskulls(runes),\"record_type\":\"completed_sale_page_record\",\n       \"transaction_status\":\"completed_sale_page_record\",\"is_completed_sale_page_record\":True,\n       \"sale_price_reliability\":\"uncertain_possible_overstatement\",\"numeric_estimate\":None},\n      \"recommendation\":json.loads(r[\"recommendation_json\"]),\n      \"market_comparables\":comparable_offer_summary(db,stats,r[\"observation_id\"])})\n   self._json(200,{\"ok\":True,\"count\":len(out),\"jewels\":out}); return\n  if path.path==\"/rings\":\n   with connect() as db:\n    rows=db.execute(\"\"\"SELECT r.*,o.listing_title,o.listing_key,o.source_url,o.captured_at\n      FROM ring_analyses r JOIN observations o ON o.id=r.observation_id\n      ORDER BY r.id DESC LIMIT ?\"\"\",(limit,)).fetchall()\n    out=[{\"observation_id\":r[\"observation_id\"],\"listing_title\":r[\"listing_title\"],\n      \"listing_url\":urljoin(r[\"source_url\"],r[\"listing_key\"]) if r[\"listing_key\"] else r[\"source_url\"],\n      \"captured_at\":r[\"captured_at\"],\"craft_type\":r[\"craft_type\"],\n      \"analysis\":json.loads(r[\"analysis_json\"])} for r in rows]\n   self._json(200,{\"ok\":True,\"count\":len(out),\"rings\":out}); return\n  if path.path==\"/sales\":\n   with connect() as db:\n    rows=db.execute(\"SELECT * FROM verified_sales ORDER BY id DESC LIMIT ?\",(limit,)).fetchall()\n    out=[{\"sale_id\":r[\"id\"],\"observation_id\":r[\"observation_id\"],\"sold_at\":r[\"sold_at\"],\n      \"sale_price_text\":r[\"sale_price_text\"],\"sale_runes\":json.loads(r[\"sale_runes_json\"]),\n      \"sale_value_pskulls\":r[\"sale_value_pskulls\"],\"verification_method\":r[\"verification_method\"],\n      \"evidence_note\":r[\"evidence_note\"],\"verified\":True} for r in rows]\n   self._json(200,{\"ok\":True,\"count\":len(out),\"sales\":out}); return\n  self._json(404,{\"error\":\"not found\"})\n def do_POST(self):\n  path=urlparse(self.path).path\n  try:\n   payload=self._body()\n   if path==\"/analyze/ring\":\n    title=str(payload.get(\"title\") or \"Blood Ring (SYNTHETIC TEST DATA)\")[:300]\n    visible=str(payload.get(\"visible_text\") or \"\")[:4000]\n    if not visible.strip(): raise ValueError(\"visible_text is required\")\n    analysis=extract_ring_properties(title,visible)\n    if not analysis: raise ValueError(\"input does not look like a ring\")\n    analysis[\"build_recommendation\"]=build_recommendation(analysis[\"stats\"])\n    # Completed-sale page records are automatically usable market evidence.\n    # Their 90% reliability is a statistical weight, not a 10% price discount.\n    from jewel_analysis import parse_rune_request\n    with connect() as db:\n     rows=db.execute(\"\"\"SELECT o.id,o.listing_key,o.payload_json,o.captured_at,ra.stats_json,ra.craft_type\n       FROM observations o JOIN ring_analyses ra ON ra.observation_id=o.id\n       WHERE o.observation_type='listing_snapshot'\n       ORDER BY o.captured_at DESC,o.id DESC\"\"\").fetchall()\n    target=analysis[\"stats\"]\n    target_score=analysis[\"heuristic_score\"]\n    seen=set()\n    comps=[]\n    diagnostics={\"listing_snapshots_scanned\":len(rows),\"completed_sales\":0,\"duplicate_listings_skipped\":0,\n      \"non_completed_sales_skipped\":0,\"non_blood_rings_skipped\":0,\"unknown_or_unparsed_prices\":0,\n      \"fcr_mismatch\":0,\"insufficient_stat_overlap\":0,\"eligible_before_top_20\":0}\n    for row in rows:\n     try:\n      saved=json.loads(row[\"payload_json\"])\n      listing=saved.get(\"listing\") or {}\n      if not is_completed_sale_listing(listing):\n       diagnostics[\"non_completed_sales_skipped\"]+=1\n       continue\n      diagnostics[\"completed_sales\"]+=1\n      listing_key=row[\"listing_key\"] or str(row[\"id\"])\n      if listing_key in seen:\n       diagnostics[\"duplicate_listings_skipped\"]+=1\n       continue\n      seen.add(listing_key)\n      if row[\"craft_type\"]!=\"blood_candidate\":\n       diagnostics[\"non_blood_rings_skipped\"]+=1\n       continue\n      trade_text=(listing.get(\"i_give_text\") or listing.get(\"observed_trade_text\") or \"\").strip()\n      runes=parse_rune_request(trade_text)\n      price=rune_bundle_value_pskulls(runes)\n      if price[\"value_pskulls\"] is None:\n       diagnostics[\"unknown_or_unparsed_prices\"]+=1\n       continue\n      other=json.loads(row[\"stats_json\"])\n      if other.get(\"fcr\") != target.get(\"fcr\"):\n       diagnostics[\"fcr_mismatch\"]+=1\n      # FCR mismatch is a distance penalty, not a hard exclusion; different\n      # builds and breakpoint choices can still make a sale informative.\n      shared=set(target).intersection(other)\n      if len(shared)<1:\n       diagnostics[\"insufficient_stat_overlap\"]+=1\n       continue\n      # Compare the union, not just shared stats: missing premium stats count as zero.\n      # This prevents a weak target from matching only on its few overlapping stats.\n      union=set(target).union(other)\n      stat_weights={\"fcr\":2.0,\"life_leech\":1.5,\"mana_leech\":2.0,\"life\":1.5,\"strength\":1.4,\"dexterity\":1.5,\n        \"attack_rating\":1.0,\"all_resist\":1.0,\"fire_resist\":0.8,\"cold_resist\":0.8,\n        \"lightning_resist\":0.8,\"poison_resist\":0.8,\"mana\":0.7,\"mana_per_kill\":0.7,\"poison_length_reduced\":0.6,\"magic_find\":0.5,\"gold_find\":0.25}\n      distance_parts={}\n      for key in union:\n       a=float(target.get(key,0)); b=float(other.get(key,0))\n       scale=max(abs(a),abs(b),10.0)\n       distance_parts[key]=round(abs(a-b)/scale*stat_weights.get(key,1.0),4)\n      if key==\"fcr\" and a!=b: distance_parts[key]+=0.25\n      stat_distance=sum(distance_parts.values())/max(sum(stat_weights.get(k,1.0) for k in union),1.0)\n      other_score,_=score_ring_stats(other)\n      score_gap=abs(target_score-other_score)\n      quality=ring_quality_gap(target,other)\n      quality_penalty=quality[\"penalty\"]\n      distance=stat_distance+(score_gap/100.0)*0.75+quality_penalty\n      comps.append({\"distance\":distance,\"stat_distance\":stat_distance,\"score_gap\":score_gap,\"quality_gap\":quality,\"quality_penalty\":quality_penalty,\n       \"value\":float(price[\"value_pskulls\"]),\"weight\":0.90,\"observation_id\":row[\"id\"],\n       \"trade_text\":trade_text,\"listing_key\":listing_key,\"captured_at\":row[\"captured_at\"],\n       \"stats\":other,\"heuristic_score\":other_score,\"shared_stats\":sorted(shared),\n       \"distance_components\":distance_parts})\n     except (ValueError,TypeError,KeyError,json.JSONDecodeError):\n      continue\n    comps.sort(key=lambda x:x[\"distance\"])\n    diagnostics[\"eligible_before_top_20\"]=len(comps)\n    MAX_COMPARABLE_DISTANCE=0.55\n    close=[x for x in comps if x[\"distance\"] <= MAX_COMPARABLE_DISTANCE]\n    diagnostics[\"distance_threshold\"]=MAX_COMPARABLE_DISTANCE\n    diagnostics[\"rejected_by_distance\"]=sum(1 for x in comps if x[\"distance\"] > MAX_COMPARABLE_DISTANCE)\n    diagnostics[\"close_comparables\"]=len(close)\n    diagnostics[\"sales_phase_qualified\"]=len(close)>=3\n\n    quality_percent=float(analysis.get(\"quality_score_percent\",target_score))\n    poor_combination=bool(analysis.get(\"poor_stat_combination\"))\n    build_demand=build_demand_analysis(target)\n    build_recommendation_result=build_recommendation(target)\n    viable_builds=build_demand.get(\"viable_profiles\",[])\n    best_build_score=float(build_demand[\"best_score\"])\n\n    def adjusted_comparables(items):\n     adjusted_rows=[]\n     for item in items:\n      bandwidth=0.65\n      effective_distance=float(item.get(\"build_distance\",item[\"distance\"]))\n      distance_weight=__import__(\"math\").exp(-((effective_distance/bandwidth)**2))\n      if item.get(\"build\"):\n       comparable_quality=max(float(item.get(\"sale_build_fit\",0.0)),1.0)\n       target_quality=max(float(item.get(\"target_build_fit\",0.0)),1.0)\n      else:\n       comparable_quality=max(float(item[\"heuristic_score\"]),1.0)\n       target_quality=max(quality_percent,1.0)\n      raw_quality_ratio=target_quality/comparable_quality\n      # A target that is stronger than its comparable may retain an upward\n      # quality adjustment. A weaker target must never receive an upward\n      # adjustment from a stronger sale record.\n      if item.get(\"build\"):\n       directional=directional_sale_penalty(\n        item.get(\"target_build_fit\",0.0),item.get(\"sale_build_fit\",0.0))\n      else:\n       directional=directional_sale_penalty(quality_percent,item[\"heuristic_score\"])\n      directional_penalty=directional[\"penalty\"]\n      quality_ratio=max(0.50,min(1.50,raw_quality_ratio))\n      if directional[\"weaker_by\"]>0:\n       quality_ratio=min(1.0,quality_ratio)\n      weaker_by=directional[\"weaker_by\"]\n      adjusted_price=max(0.0,item[\"value\"]*(quality_ratio**0.75))\n      combined_weight=(item[\"weight\"]*distance_weight*\n       float(item.get(\"build_match_weight\",1.0))*directional_penalty)\n      adjusted_rows.append({**item,\"distance_weight\":distance_weight,\n       \"quality_ratio\":quality_ratio,\"adjusted_price\":adjusted_price,\n       \"target_weaker_score_gap\":weaker_by,\n       \"directional_penalty_threshold\":directional[\"threshold\"],\n       \"directional_penalty_excess\":directional[\"excess\"],\n       \"directional_price_penalty\":directional_penalty,\n       \"combined_weight\":combined_weight})\n     adjusted_rows.sort(key=lambda x:x[\"adjusted_price\"])\n     return adjusted_rows\n\n    def weighted_quantile(items,q):\n     total=sum(x[\"combined_weight\"] for x in items)\n     if not items or total<=0: return None\n     threshold=total*q\n     running=0.0\n     for item in items:\n      running+=item[\"combined_weight\"]\n      if running>=threshold: return item[\"adjusted_price\"]\n     return items[-1][\"adjusted_price\"]\n\n    # Phase 1: direct nearest-sale evidence. Three close completed sales are\n    # required, but all eligible sales remain available to Phase 2.\n    phase1_selected=close[:20] if len(close)>=3 else []\n    phase=\"phase_1_direct_sales\" if phase1_selected else \"phase_2_build_specific\"\n    phase2_build_results=[]\n    phase2_pool=[]\n    phase2_build_matched=False\n    if phase1_selected:\n     selected=phase1_selected\n     phase_reason=(f\"Phase 1 qualified: {len(close)} completed Blood Ring sales \"\n                   f\"within distance {MAX_COMPARABLE_DISTANCE}; direct ring similarity is primary.\")\n    else:\n     # Phase 2 scores each completed sale against every viable audience for\n     # the target. A sale can support multiple overlapping build profiles.\n     for build in viable_builds:\n      target_fit=float(build_demand[\"profiles\"][build][\"score\"])\n      build_weights=BUILD_PROFILES.get(build,{})\n      build_sales=[]\n      for item in comps:\n       if int(item[\"stats\"].get(\"fcr\",0)) != int(target.get(\"fcr\",0)):\n        continue\n       sale_demand=build_demand_analysis(item[\"stats\"])\n       sale_fit=float(sale_demand[\"profiles\"].get(build,{}).get(\"score\",0.0))\n       if sale_fit < 25.0:\n        continue\n       fit_gap=abs(target_fit-sale_fit)/100.0\n       parts={}\n       for stat,weight in build_weights.items():\n        if weight<=0: continue\n        av=float(target.get(stat,0)); bv=float(item[\"stats\"].get(stat,0))\n        scale=max(abs(av),abs(bv),10.0)\n        parts[stat]=abs(av-bv)/scale*float(weight)\n       denominator=sum(float(w) for w in build_weights.values() if w>0) or 1.0\n       build_stat_distance=sum(parts.values())/denominator\n       build_distance=build_stat_distance+fit_gap*0.25\n       match_weight=max(0.05,min(1.0,(sale_fit/100.0)*__import__(\"math\").exp(-fit_gap*2.0)))\n       candidate={**item,\"build\":build,\"target_build_fit\":target_fit,\n        \"sale_build_fit\":sale_fit,\"build_distance\":round(build_distance,4),\n        \"build_distance_components\":{k:round(v,4) for k,v in parts.items()},\n        \"build_match_weight\":match_weight}\n       build_sales.append(candidate)\n      build_sales.sort(key=lambda x:x[\"build_distance\"])\n      for candidate in build_sales[:12]:\n       phase2_pool.append(candidate)\n      phase2_build_results.append({\n       \"build\":build,\"target_fit_score\":target_fit,\n       \"fcr_segment\":(\"10_fcr\" if int(target.get(\"fcr\",0))==10 else \"non_fcr\"),\n       \"fcr_segment_candidate_count\":sum(1 for x in comps if int(x[\"stats\"].get(\"fcr\",0))==int(target.get(\"fcr\",0))),\n       \"opposite_fcr_segment_excluded\":sum(1 for x in comps if int(x[\"stats\"].get(\"fcr\",0))!=int(target.get(\"fcr\",0))),\n       \"eligible_sale_count\":len(build_sales),\n       \"selected_sales\":[{\"observation_id\":x[\"observation_id\"],\n        \"sale_build_fit\":x[\"sale_build_fit\"],\"distance\":x[\"build_distance\"],\n        \"price_pskulls\":x[\"value\"]} for x in build_sales[:5]],\n       \"reason\":(\"Matched completed sales whose stats also fit this build; \"\n                 \"ranking uses ring-stat distance and similarity of build-fit scores.\")\n      })\n     phase2_build_matched=bool(phase2_pool)\n     # Deduplicate sales across overlapping builds, retaining their strongest\n     # build match while recording all matching audiences.\n     dedup={}\n     for item in phase2_pool:\n      key=item[\"observation_id\"]\n      if key not in dedup or item[\"build_match_weight\"]>dedup[key][\"build_match_weight\"]:\n       dedup[key]=item\n      else:\n       prior=dedup[key]\n       prior[\"also_matches\"]=sorted(set(prior.get(\"also_matches\",[])+[item[\"build\"]]))\n     selected=sorted(dedup.values(),key=lambda x:x[\"build_distance\"])\n     if not selected:\n      phase=\"phase_2_insufficient_relevant_sales\"\n      # Distant or audience-mismatched sales must not create an invented price.\n      # In particular, a weak ring must not inherit the price of much stronger\n      # melee sales merely because no close historical match exists.\n      selected=[]\n      phase_reason=(\"Phase 2 found no sufficiently relevant completed sales. \"\n                    \"No market median is reported; collect closer sales instead.\")\n     else:\n      phase_reason=(\"Phase 1 lacked three close sales. Phase 2 valued the ring using \"\n                    \"completed sales matching its overlapping build audiences.\")\n\n    diagnostics[\"phase1_close_sales\"]=len(close)\n    diagnostics[\"phase1_required_close_sales\"]=3\n    diagnostics[\"phase2_build_sale_candidates\"]=len(phase2_pool)\n    diagnostics[\"phase2_builds_evaluated\"]=len(phase2_build_results)\n    diagnostics[\"valuation_phase\"]=phase\n    diagnostics[\"sales_phase_qualified\"]=bool(phase1_selected)\n\n    adjusted=adjusted_comparables(selected)\n    phase2_rarity_diagnostics=None\n    if phase2_build_matched and selected:\n     # New Phase 2: each completed sale is an independent price anchor.\n     # Normalize its price by its quality/rarity index, take the weighted\n     # median baseline, then apply the target ring's index. Unlike the legacy\n     # Phase 2, this does not extrapolate from build-fit score ratios.\n     rarity=estimate_phase2_rarity_price(quality_percent, selected)\n     phase2_rarity_diagnostics=rarity\n     anchor_by_id={a[\"observation_id\"]:a for a in rarity.get(\"anchors\",[])}\n     rarity_adjusted=[]\n     for item in selected:\n      anchor=anchor_by_id.get(item[\"observation_id\"])\n      if not anchor:\n       continue\n      contribution=anchor[\"implied_base_price\"]*rarity[\"target_rarity_index\"]\n      rarity_adjusted.append({**item,\n       \"adjusted_price\":contribution,\n       \"quality_ratio\":rarity[\"target_rarity_index\"]/anchor[\"rarity_index\"],\n       \"distance_weight\":1.0,\n       \"combined_weight\":anchor[\"weight\"],\n       \"rarity_anchor\":anchor})\n     adjusted=sorted(rarity_adjusted,key=lambda x:x[\"adjusted_price\"])\n     low=rarity[\"low\"]\n     med=rarity[\"median\"]\n     high=rarity[\"high\"]\n     method=\"phase_2_normal_rarity_calibrated_completed_sales\"\n     effective=sum(x[\"combined_weight\"] for x in adjusted)\n     prices=[x[\"adjusted_price\"] for x in adjusted]\n     relative_range=(prices[-1]-prices[0])/max(med or 0.0,1.0) if len(prices)>1 else 1.0\n     confidence=(\"medium\" if len(adjusted)>=5 and effective>=2.0 and relative_range<=0.50 else \"low\")\n     phase2_confidence_diagnostics={\"relative_price_range\":round(relative_range,3),\n      \"effective_sample_weight\":round(effective,3),\"comparable_count\":len(adjusted),\n      \"medium_rule\":\"at least 5 anchors, effective weight >=2.0, relative range <=0.50\",\n      \"pricing_model\":\"normal_distribution_rarity\"}\n    elif adjusted:\n     low=weighted_quantile(adjusted,0.25)\n     med=weighted_quantile(adjusted,0.50)\n     high=weighted_quantile(adjusted,0.75)\n     if phase1_selected:\n      method=\"phase_1_direct_completed_sales\"\n      confidence=\"high\" if len(close)>=5 and sum(x[\"combined_weight\"] for x in adjusted)>=1.5 else \"medium\"\n     else:\n      method=\"phase_2_nearest_sales_without_build_match\"\n      confidence=\"low\"\n    else:\n     # No priced completed sale can support a market estimate. Retain a\n     # transparent heuristic anchor, but mark it explicitly as uncalibrated.\n     low=None\n     med=None\n     high=None\n     method=\"insufficient_relevant_completed_sales\"\n     confidence=\"very_low\"\n     phase_reason += \" No usable comparable sale supports a numeric price estimate.\"\n\n    note=phase_reason\n    valuation={\"status\":(\"estimate_available\" if med is not None else \"insufficient_relevant_sales\"),\"currency\":\"Pskulls\",\n     \"low\":round(low,2) if low is not None else None,\n     \"median\":round(med,2) if med is not None else None,\n     \"high\":round(high,2) if high is not None else None,\n     \"display\":{\"low\":format_pskull_value(low) if low is not None else None,\n      \"median\":format_pskull_value(med) if med is not None else None,\n      \"high\":format_pskull_value(high) if high is not None else None},\n     \"comparable_sales\":len(adjusted),\"eligible_comparable_sales\":len(comps),\n     \"valuation_phase\":phase,\"phase1_rate\":round(len(close)/max(len(comps),1),3),\n     \"phase1_close_sales\":len(close),\"phase1_required\":3,\n     \"reliability_weight\":0.90,\"valuation_method\":method,\"confidence\":confidence,\n     \"quality_score_percent\":quality_percent,\"poor_stat_combination\":poor_combination,\n     \"effective_weight\":round(sum(x[\"combined_weight\"] for x in adjusted),4),\n     \"phase2_confidence_diagnostics\":(phase2_confidence_diagnostics if phase2_build_matched else None),\n     \"phase2_rarity_model\":phase2_rarity_diagnostics,\n     \"diagnostics\":{\"target_stats\":target,\"target_quality_score\":quality_percent,\n      \"target_verdict\":analysis[\"verdict\"],\"counts\":diagnostics,\n      \"build_demand\":build_demand,\"build_recommendation\":build_recommendation_result,\n      \"phase_explanation\":{\"phase\":phase,\"reason\":phase_reason,\n       \"phase1\":{\"close_sales\":len(close),\"required\":3,\"distance_threshold\":MAX_COMPARABLE_DISTANCE,\n        \"qualified\":bool(phase1_selected)},\n       \"phase2\":{\"builds_evaluated\":phase2_build_results,\"build_sale_candidate_count\":len(phase2_pool)}},\n      \"low_quality_cap_boundary\":{\"quality_below\":65,\"requires_poor_stat_combination\":True,\n       \"requires_zero_viable_profiles\":True,\"best_profile_score_below\":35},\n      \"selection_method\":\"Phase 1: at least 3 close direct completed sales; Phase 2: all deduplicated build-matched completed-sale anchors, normalized by the 85-centered normal rarity model; no numeric estimate without anchors.\",\n      \"selected_comparables\":[{\"observation_id\":x[\"observation_id\"],\n       \"captured_at\":x[\"captured_at\"],\"sale_price_pskulls\":x[\"value\"],\n       \"sale_price_display\":format_pskull_value(x[\"value\"]),\n       \"adjusted_price_pskulls\":round(x[\"adjusted_price\"],2),\n       \"adjusted_price_display\":format_pskull_value(x[\"adjusted_price\"]),\n       \"distance\":round(x.get(\"build_distance\",x[\"distance\"]),4),\"distance_weight\":round(x[\"distance_weight\"],4),\n       \"build\":x.get(\"build\"),\"also_matches\":x.get(\"also_matches\",[]),\n       \"target_build_fit\":x.get(\"target_build_fit\"),\"sale_build_fit\":x.get(\"sale_build_fit\"),\n       \"build_match_weight\":round(x.get(\"build_match_weight\",1.0),4),\n       \"quality_ratio\":round(x[\"quality_ratio\"],4),\n       \"target_weaker_score_gap\":x.get(\"target_weaker_score_gap\",0.0),\n       \"directional_penalty_threshold\":x.get(\"directional_penalty_threshold\",10.0),\n       \"directional_penalty_excess\":x.get(\"directional_penalty_excess\",0.0),\n       \"directional_price_penalty\":x.get(\"directional_price_penalty\",1.0),\n       \"weight\":round(x[\"combined_weight\"],4),\n       \"stats\":x[\"stats\"],\"quality_score\":x[\"heuristic_score\"],\n       \"quality_gap\":x[\"quality_gap\"],\"distance_components\":x[\"distance_components\"],\n        \"build_distance_components\":x.get(\"build_distance_components\",{})}\n       for x in adjusted],\n      \"closest_candidates\":[{\"observation_id\":x[\"observation_id\"],\n       \"price_display\":format_pskull_value(x[\"value\"]),\"stats\":x[\"stats\"],\n       \"quality_score\":x[\"heuristic_score\"],\"distance\":round(x[\"distance\"],4)}\n       for x in comps[:25]]},\n     \"note\":note}\n    valuation[\"comparables\"]=[{\"observation_id\":x[\"observation_id\"],\n      \"sale_price_pskulls\":x[\"value\"],\"sale_price_display\":format_pskull_value(x[\"value\"]),\n      \"estimated_contribution_pskulls\":round(x[\"adjusted_price\"],2),\n      \"distance\":round(x.get(\"build_distance\",x[\"distance\"]),4),\"build\":x.get(\"build\"),\n      \"target_build_fit\":x.get(\"target_build_fit\"),\"sale_build_fit\":x.get(\"sale_build_fit\"),\n      \"reliability\":x[\"weight\"],\n      \"distance_weight\":round(x[\"distance_weight\"],4),\"trade_text\":x[\"trade_text\"],\n      \"stats\":x[\"stats\"],\"quality_score\":x[\"heuristic_score\"]} for x in adjusted]\n    self._json(200,{\"ok\":True,\"synthetic\":bool(payload.get(\"synthetic\",False)),\n      \"analysis\":analysis,\"valuation\":valuation}); return\n   if path==\"/observations\":\n    origin=self.headers.get(\"Origin\",\"\")\n    if not origin.startswith(ALLOWED_ORIGIN_PREFIX): self._json(403,{\"error\":\"extension origin required\"}); return\n    source=str(payload.get(\"source_url\",\"\")); parsed=urlparse(source)\n    if parsed.scheme!=\"https\" or parsed.hostname not in {\"traderie.com\",\"www.traderie.com\"}:\n     raise ValueError(\"source_url must be a Traderie HTTPS page\")\n    kind=str(payload.get(\"observation_type\",\"\"))\n    if kind not in {\"page_context\",\"listing_snapshot\"}: raise ValueError(\"unsupported observation_type\")\n    listing=payload.get(\"listing\") if isinstance(payload.get(\"listing\"),dict) else {}\n    context=payload.get(\"page_context\") if isinstance(payload.get(\"page_context\"),dict) else {}\n    captured=str(payload.get(\"captured_at\") or datetime.now(timezone.utc).isoformat())\n    with connect() as db:\n     cur=db.execute(\"\"\"INSERT INTO observations(observation_type,captured_at,source_url,page_context_json,\n      listing_key,listing_title,asking_price_text,visible_text,payload_json) VALUES(?,?,?,?,?,?,?,?,?)\"\"\",\n      (kind,captured,source,json.dumps(context,ensure_ascii=False),str(listing.get(\"listing_key\") or \"\")[:1000] or None,\n       str(listing.get(\"title\") or \"\")[:300],str(listing.get(\"asking_price_text\") or \"\")[:100],\n       str(listing.get(\"visible_text\") or \"\")[:4000],json.dumps(payload,ensure_ascii=False)))\n     analyzed={\"jewel\":False,\"ring\":False}\n     if kind==\"listing_snapshot\":\n      jewel=analyze_listing(listing)\n      if jewel:\n       pr=jewel[\"trade_observation\"]\n       db.execute(\"\"\"INSERT INTO jewel_analyses(observation_id,analyzed_at,item_type,quality_hint,stats_json,\n        recommendation_json,displayed_asking_price,requested_trade_text,raw_text,requested_runes_json)\n        VALUES(?,?,?,?,?,?,?,?,?,?)\"\"\",(cur.lastrowid,datetime.now(timezone.utc).isoformat(),jewel[\"item_type\"],\n        jewel[\"quality_hint\"],json.dumps(jewel[\"stats\"],sort_keys=True),json.dumps(jewel[\"recommendation\"],ensure_ascii=False),\n        pr[\"displayed_asking_price\"],pr[\"observed_trade_text\"],jewel[\"raw_text\"],json.dumps(pr[\"observed_runes\"],ensure_ascii=False)))\n       analyzed[\"jewel\"]=True\n      ring=extract_ring_properties(str(listing.get(\"title\") or \"\"),str(listing.get(\"visible_text\") or \"\"))\n      if ring:\n       db.execute(\"\"\"INSERT INTO ring_analyses(observation_id,analyzed_at,craft_type,stats_json,analysis_json,raw_text)\n        VALUES(?,?,?,?,?,?)\"\"\",(cur.lastrowid,datetime.now(timezone.utc).isoformat(),ring[\"craft_type\"],\n        json.dumps(ring[\"stats\"],sort_keys=True),json.dumps(ring,ensure_ascii=False),ring[\"raw_text\"]))\n       analyzed[\"ring\"]=True\n    self._json(201,{\"ok\":True,\"id\":cur.lastrowid,\"analyzed\":analyzed}); return\n   if path==\"/sales\":\n    if payload.get(\"verified\") is not True: raise ValueError(\"verified must be true; unverified asks cannot be recorded as sales\")\n    obs=int(payload[\"observation_id\"]); price=str(payload.get(\"sale_price_text\") or \"\").strip()\n    method=str(payload.get(\"verification_method\") or \"\").strip()\n    if not price or not method: raise ValueError(\"sale_price_text and verification_method are required\")\n    runes=payload.get(\"sale_runes\") or []\n    if not isinstance(runes,list) or any(not isinstance(x,dict) for x in runes): raise ValueError(\"sale_runes must be a list of rune quantity objects\")\n    value=rune_bundle_value_pskulls(runes)\n    numeric=value[\"value_pskulls\"]\n    sold=str(payload.get(\"sold_at\") or datetime.now(timezone.utc).isoformat())\n    with connect() as db:\n     exists=db.execute(\"SELECT id FROM observations WHERE id=?\",(obs,)).fetchone()\n     if not exists: raise ValueError(\"observation_id not found\")\n     cur=db.execute(\"\"\"INSERT INTO verified_sales(observation_id,sold_at,recorded_at,sale_price_text,\n      sale_runes_json,sale_value_pskulls,verification_method,evidence_note,verified)\n      VALUES(?,?,?,?,?,?,?,?,1)\"\"\",(obs,sold,datetime.now(timezone.utc).isoformat(),price,\n      json.dumps(runes,ensure_ascii=False),numeric,method,str(payload.get(\"evidence_note\") or \"\")[:2000]))\n    self._json(201,{\"ok\":True,\"sale_id\":cur.lastrowid,\"verified\":True,\n      \"sale_value_pskulls\":numeric,\"rune_value\":value}); return\n   self._json(404,{\"error\":\"not found\"})\n  except (ValueError,TypeError,KeyError,json.JSONDecodeError) as exc: self._json(400,{\"error\":str(exc)})\n  except Exception as exc: self._json(500,{\"error\":f\"storage failure: {type(exc).__name__}\"})\n\nif __name__==\"__main__\":\n initialize()\n print(f\"Traderie local collector listening on http://{HOST}:{PORT}\")\n print(f\"SQLite database: {DB_PATH}\")\n ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()\n",
    }
    _embedded_modules = {}
    for _module_name, _source in _embedded_sources.items():
        _module = _types.ModuleType(_module_name)
        _module.__file__ = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "_embedded_" + _module_name + ".py"
        )
        sys.modules[_module_name] = _module
        exec(compile(_source, _module.__file__, "exec"), _module.__dict__)
        _embedded_modules[_module_name] = _module
    _server_module = _embedded_modules["_d2_embedded_collector_server"]
    _server_module.initialize()
    _httpd = _server_module.ThreadingHTTPServer(
        (_server_module.HOST, _server_module.PORT), _server_module.Handler
    )
    _httpd.daemon_threads = True
    _thread = _threading.Thread(
        target=_httpd.serve_forever,
        name="TraderieEmbeddedCollector",
        daemon=True
    )
    _thread.start()
    _EMBEDDED_COLLECTOR_HTTPD = _httpd
    print(
        "[Local Valuator] Embedded Traderie collector ready at "
        f"http://{_server_module.HOST}:{_server_module.PORT}"
    )


def ask_local_ring_valuation(title, visible_text, task_id):
    """Return the collector's evidence-backed ring valuation and diagnostics."""
    import urllib.request as _urlrequest
    payload = json.dumps({
        "title": title or "Ring",
        "visible_text": visible_text or ""
    }).encode("utf-8")
    request = _urlrequest.Request(
        "http://127.0.0.1:8765/analyze/ring",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with _urlrequest.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "local valuation returned not-ok"))
        valuation = result.get("valuation") or {}
        analysis = result.get("analysis") or {}
        confidence = str(valuation.get("confidence") or "very_low").lower()
        phase = str(valuation.get("valuation_phase") or "unknown_phase")
        quality = valuation.get("quality_score_percent")
        display = (valuation.get("display") or {}).get("median")
        median_value = valuation.get("median")
        if confidence in ("low", "very_low") or median_value is None or not display:
            price_line = (
                "Unknown from local, please self judge from score "
                f"(Local phase: {phase}; Confidence: {confidence}; "
                f"Quality score: {quality if quality is not None else 'N/A'}/100)"
            )
        else:
            price_line = (
                f"BIN: {display} "
                f"(Valuation source: Local; Phase: {phase}; "
                f"Confidence: {confidence}; Quality score: {quality}/100)"
            )
        print(
            f"[{task_id}] [Local Valuator] phase={phase}, confidence={confidence}, "
            f"quality={quality}, median={display or 'Unknown'}"
        )
        return {"price_line": price_line, "valuation": valuation, "analysis": analysis}
    except Exception as exc:
        print(f"[{task_id}] [Local Valuator] valuation unavailable: {type(exc).__name__}: {exc}")
        return None



try:
    client = genai.Client()
except Exception as e:
    print(f"【錯誤】Google AI 初始化失敗: {e}"); sys.exit(1)

# 使用固定的沙盒資料夾，關閉程式後下次開，登入狀態依然會保留
PURE_SANDBOX_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "d2_shared_sandbox_profile")

# 價格歷史資料庫路徑（與 sandbox profile 同目錄，方便管理）
PRICE_DB_PATH = os.path.join(os.path.expanduser("~"), "Desktop", "d2_price_history.db")

# 建立一個執行緒安全的任務佇列
TASK_QUEUE = queue.Queue()
# Serialize hotkey callbacks so rapid F9 presses cannot overlap screen capture.
CAPTURE_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Simple Price History DB (SQLite)
# ---------------------------------------------------------------------------
class PriceHistoryDB:
    """Lightweight local cache so identical item texts skip Gemini re-queries."""

    def __init__(self, db_path: str = PRICE_DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS price_history (
                    text_hash   TEXT PRIMARY KEY,
                    item_text   TEXT NOT NULL,
                    price       TEXT NOT NULL,
                    created_at  TEXT NOT NULL,
                    hit_count   INTEGER DEFAULT 1
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_created_at
                ON price_history(created_at)
            """)
            conn.commit()

    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize item text for consistent hashing (whitespace + case)."""
        return " ".join(text.strip().lower().split())

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def get(self, item_text: str):
        """Return a cached price only while it is fresh (24-hour TTL)."""
        norm = self._normalize(item_text)
        if not norm:
            return None
        h = self._hash(norm)
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT price, created_at, hit_count FROM price_history WHERE text_hash = ?",
                    (h,)
                ).fetchone()
                if not row:
                    return None
                price, created_at, hits = row
                try:
                    created = datetime.fromisoformat(created_at)
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    age = (datetime.now(timezone.utc) - created).total_seconds()
                except (TypeError, ValueError):
                    age = float("inf")
                if age < 0 or age > 86400:
                    return None
                conn.execute("UPDATE price_history SET hit_count = ? WHERE text_hash = ?", (hits + 1, h))
                conn.commit()
                return price
        except Exception as e:
            print(f"[PriceDB] lookup error: {e}")
        return None
    def save(self, item_text: str, price: str) -> None:
        """Insert or update a price entry."""
        norm = self._normalize(item_text)
        if not norm or not price or price.strip().casefold() in {"unknown", "n/a", "error"}:
            return
        h = self._hash(norm)
        now = datetime.now(timezone.utc).isoformat()
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO price_history (text_hash, item_text, price, created_at, hit_count)
                    VALUES (?, ?, ?, ?, 1)
                    ON CONFLICT(text_hash) DO UPDATE SET
                        price = excluded.price,
                        created_at = excluded.created_at,
                        hit_count = hit_count + 1
                """, (h, item_text[:2000], price, now))
                conn.commit()
        except Exception as e:
            print(f"[PriceDB] save error: {e}")


# Global DB instance
PRICE_DB = PriceHistoryDB()


def detect_and_crop_tooltip(f_path, o_path):
    """Crop a likely tooltip; fail closed when no plausible region is found."""
    print("正在透過電腦視覺掃描 D2R 提示框...")
    img = cv2.imread(f_path)
    if img is None:
        raise RuntimeError("截圖檔案無法讀取。")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 15, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best_box, max_area = None, 0
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if 150 < w < (gray.shape[1] * 0.5) and 150 < h < (gray.shape[0] * 0.8):
            if w * h > max_area:
                max_area, best_box = w * h, (x, y, w, h)
    if not best_box:
        raise RuntimeError("找不到可信的裝備提示框；已停止，避免把整個桌面送去 OCR。")
    x, y, w, h = best_box
    p = 5
    crop = img[max(0, y-p):min(gray.shape[0], y+h+p), max(0, x-p):min(gray.shape[1], x+w+p)]
    if crop.size == 0 or crop.shape[0] < 100 or crop.shape[1] < 100:
        raise RuntimeError("偵測到的提示框尺寸異常；已停止處理。")
    if not cv2.imwrite(o_path, crop, [int(cv2.IMWRITE_JPEG_QUALITY), 95]):
        raise RuntimeError("無法寫入提示框裁切圖片。")
    return o_path


def capture_d2r_screen(r_path):
    """Capture only the game window. Never silently fall back to the desktop."""
    print("\n[F9 觸發] 正在擷取遊戲視窗...")
    d2r_windows = gw.getWindowsWithTitle("Diablo II: Resurrected")
    if not d2r_windows:
        raise RuntimeError("找不到 Diablo II: Resurrected 視窗；請確認遊戲已開啟。")
    d2r_win = d2r_windows[0]
    if getattr(d2r_win, "isMinimized", False):
        raise RuntimeError("遊戲視窗目前已最小化。")
    try:
        d2r_win.activate()
        time.sleep(0.35)
    except Exception as e:
        raise RuntimeError(f"無法將遊戲視窗切到前景：{e}") from e
    left, top, right, bottom = d2r_win.left, d2r_win.top, d2r_win.right, d2r_win.bottom
    if right <= left or bottom <= top:
        raise RuntimeError("遊戲視窗尺寸無效。")
    ImageGrab.grab(bbox=(left, top, right, bottom)).save(r_path)
    if not os.path.exists(r_path) or os.path.getsize(r_path) < 1024:
        raise RuntimeError("遊戲截圖為空或檔案尺寸異常。")
    return r_path
def ask_gemini_to_price_only(ocr_text):
    """Try a realistic price first; return Unknown when the estimate is not defensible."""
    print("正在將文字發送至 Gemini 估價...")
    cached = PRICE_DB.get(ocr_text)
    if cached is not None:
        print(f"👉 [PriceDB 快取命中] BIN {cached}")
        return cached
    system_prompt = (
        "You are a Diablo II: Resurrected item-market appraiser. "
        "Estimate a realistic current asking price using the item's exact stats. "
        "If the item text is incomplete or the value cannot be estimated responsibly, answer exactly 'Unknown'. "
        "Return one short price string only; do not invent market evidence."
    )
    try:
        res = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=f"Estimate a realistic D2R market asking price from this OCR text:\\n\\n{ocr_text}",
            config={"system_instruction": system_prompt}
        )
        price = (res.text or "").strip().splitlines()[0].strip()
        if not price or price.casefold() in {"unknown", "n/a", "error"} or len(price) > 80:
            print("Gemini 無法提供可靠的常規估價，改用偏高推薦價模式。")
            return "Unknown"
        PRICE_DB.save(ocr_text, price)
        print(f"👉 Gemini 估價結果: {price}")
        return price
    except Exception as e:
        print(f"Gemini 常規估價失敗: {e}")
        return "Unknown"


def ask_gemini_recommended_price(ocr_text):
    """Fallback: choose a higher-end but still plausible asking price in Ist."""
    prompt = (
        "You are pricing a Diablo II: Resurrected item for a seller who prefers an optimistic listing. "
        "The normal pricing pass could not produce a reliable estimate. Based only on the item text below, "
        "choose a higher-than-typical but still plausible asking price in Ist runes. "
        "Do not choose an absurd jackpot price. If the item is clearly low-value, choose a modest price. "
        "Return exactly one line: Recommend price: X Ist. X is a concise quantity such as 1, 2, 0.5, or 2x. "
        "Do not add explanations.\\n\\nItem OCR:\\n" + ocr_text
    )
    try:
        res = client.models.generate_content(model="gemini-3.8-flash", contents=prompt)
        value = (res.text or "").strip().splitlines()[0].strip()
        if not value or value.casefold() in {"unknown", "n/a", "error"} or len(value) > 80:
            raise ValueError("Gemini did not return a usable recommendation")
        if "ist" not in value.casefold():
            value = f"Recommend price: {value} Ist"
        elif not value.casefold().startswith("recommend price:"):
            value = f"Recommend price: {value}"
        print(f"👉 Gemini 偏高推薦價: {value}")
        return value
    except Exception as e:
        print(f"Gemini 偏高推薦價也失敗: {e}")
        return "Recommend price: MANUAL REVIEW (Gemini unavailable)"


def classify_crafted_item_title(ocr_text, task_id):
    """Deterministic crafted-item classification from diablo2.io OCR text."""
    text = " ".join((ocr_text or "").casefold().split())
    # Identify base item type from the item's actual base-name wording.
    boot_terms = (
        "boots", "greaves", "light plated boots", "chain boots",
        "heavy boots", "war boots", "battle boots", "greaves",
        "demonhide boots", "wyrmhide boots", "scarabshell boots",
        "boneweave boots", "mesh boots", "myrmidon greaves",
        " mirrored boots", "ward boots", " sharkskin boots",
    )
    is_boots = any(term.strip() in text for term in boot_terms)
    is_ring = "ring" in text
    is_amulet = "amulet" in text
    # Match the complete D2R gloves base family (normal, exceptional, elite).
    # Use full base names rather than generic words such as "gloves" or "gauntlets".
    glove_base_names = (
        "leather gloves",
        "heavy gloves",
        "chain gloves",
        "light gauntlets",
        "gauntlets",
        "demonhide gloves",
        "sharkskin gloves",
        "heavy bracers",
        "battle gauntlets",
        "war gauntlets",
        "bramble mitts",
        "vampirebone gloves",
        "vambraces",
        "crusader gauntlets",
        "ogre gauntlets",
    )
    matched_glove_bases = [
        base_name for base_name in glove_base_names
        if re.search(rf"(?<!\w){re.escape(base_name)}(?!\w)", text)
    ]
    is_gloves = bool(matched_glove_bases)
    item_type_flags = {
        "Boots": is_boots,
        "Ring": is_ring,
        "Amulet": is_amulet,
        "Gloves": is_gloves,
    }
    item_types = [name for name, matched in item_type_flags.items() if matched]
    print(
        f"[{task_id}] 分類診斷："
        f"boots={is_boots}, ring={is_ring}, amulet={is_amulet}, "
        f"gloves={is_gloves}, glove_bases={matched_glove_bases}, "
        f"item_types={item_types}"
    )
    if len(item_types) != 1:
        print(f"[{task_id}] OCR 無法唯一判斷物品種類；保留原標題。")
        return None

    # Gloves use their own recipe families and fixed-mod signatures.
    # The base item narrows the possible recipe; the recipe-specific mods confirm it.
    if is_gloves:
        glove_recipe_bases = {
            "Caster": (
                "leather gloves", "demonhide gloves", "bramble mitts",
            ),
            "Blood": (
                "heavy gloves", "sharkskin gloves", "vampirebone gloves",
            ),
            "Hit Power": (
                "chain gloves", "heavy bracers", "vambraces",
            ),
            "Safety": (
                "gauntlets", "war gauntlets", "ogre gauntlets",
            ),
        }
        matching_families = [
            family
            for family, bases in glove_recipe_bases.items()
            if any(
                re.search(rf"(?<!\w){re.escape(base)}(?!\w)", text)
                for base in bases
            )
        ]

        # Caster Gloves: mana regeneration + mana after each kill.
        # +10-20 Mana is another fixed mod, but OCR can truncate that line;
        # do not make it mandatory when the two distinctive mods are present.
        has_mana_per_kill = bool(re.search(
            r"\+\s*\d+\s+(?:to\s+)?mana\s+after\s+each\s+kill",
            text
        ))
        has_mana_regen = (
            "regenerate mana" in text or "mana regeneration" in text
        )

        # Blood Gloves: life leech + crushing blow.
        has_life_leech = (
            "life stolen per hit" in text
            or "life leech" in text
            or "life steal" in text
        )
        has_crushing_blow = (
            "crushing blow" in text
            or bool(re.search(r"\bchance of crushing blow\b", text))
        )

        # Hit Power Gloves: knockback + Frost Nova when struck.
        has_knockback = "knockback" in text
        has_frost_nova_on_struck = (
            "frost nova" in text and ("when struck" in text or "when hit" in text)
        )

        # Safety Gloves: physical and magic damage reduction.
        has_damage_reduce = (
            "damage reduced by" in text or "damage reduction" in text
        )
        has_magic_reduce = (
            "magic damage reduced by" in text
            or "magic damage reduction" in text
        )

        glove_checks = {
            "Caster": has_mana_regen and has_mana_per_kill,
            "Blood": has_life_leech and has_crushing_blow,
            "Hit Power": has_knockback and has_frost_nova_on_struck,
            "Safety": has_damage_reduce and has_magic_reduce,
        }
        matched_crafts = [
            family for family in matching_families if glove_checks[family]
        ]
        if len(matched_crafts) == 1:
            title = f"{matched_crafts[0]} Gloves"
            print(f"[{task_id}] 依手套專屬底材與固定屬性分類為：{title}")
            return title

        print(
            f"[{task_id}] 手套 Craft 無法唯一判斷；"
            f"底材家族={matching_families}，"
            f"符合屬性={[family for family, matched in glove_checks.items() if matched]}；"
            "保留網站 OCR 原標題。"
        )
        return None

    # Ring recipes have distinct fixed-mod pairs. Match the numeric OCR
    # variants (for example "+ 15 to Life"), not only the stat-name fragments.
    def has_stat(pattern):
        return bool(re.search(pattern, text, re.IGNORECASE))

    if is_ring:
        # Some OCR engines confuse a standalone "I"/"l" with the digit "1"
        # in numeric stat rolls (for example, "Reduced By I"). Correct only
        # isolated characters, not letters inside ordinary words.
        ring_text = re.sub(r"\b[il]\b", "1", text)

        def has_ring_stat(pattern):
            return bool(re.search(pattern, ring_text, re.IGNORECASE))

        # Caster Ring's fixed +10-20 Mana line is occasionally truncated by
        # diablo2.io OCR to a bare "+19". Accept that orphan number only when
        # it directly precedes the Mana Regeneration line and is in the
        # recipe's known 10-20 range; do not infer mana from arbitrary numbers.
        has_caster_mana = (
            has_ring_stat(r"\+\s*\d+\s+(?:to\s+)?mana\b")
            or has_ring_stat(
                r"\+\s*(?:1[0-9]|20)\s+(?=(?:regenerate\s+mana|mana\s+regeneration)\b)"
            )
        )
        ring_checks = {
            "Blood": (
                has_ring_stat(r"\b\d+(?:-\d+)?\s*%?\s*life\s+stolen\s+per\s+hit\b")
                or has_ring_stat(r"\b\d+(?:-\d+)?\s*%?\s*(?:life\s+leech|life\s+steal)\b")
            ) and has_ring_stat(r"\+\s*\d+\s+(?:to\s+)?life\b"),
            "Caster": (
                has_ring_stat(r"\bregenerate\s+mana\b")
                or has_ring_stat(r"\bmana\s+regeneration\b")
            ) and has_caster_mana,
            "Hit Power": (
                has_ring_stat(r"\d+\s*%?\s*chance\s+to\s+cast.*?frost\s+nova.*?when\s+struck")
                or has_ring_stat(r"frost\s+nova.*?when\s+struck")
            ) and has_ring_stat(r"attacker\s+takes\s+damage"),
            "Safety": has_ring_stat(r"damage\s+reduced\s+by\s+\d+(?:-\d+)?") and has_ring_stat(
                r"magic\s+damage\s+reduced\s+by\s+\d+(?:-\d+)?"
            ),
        }
        matched_rings = [family for family, matched in ring_checks.items() if matched]
        if len(matched_rings) != 1:
            print(f"[{task_id}] Ring Craft 特徵不唯一或不足（{matched_rings}）；保留網站 OCR 原標題。")
            return None
        title = f"{matched_rings[0]} Ring"
        print(f"[{task_id}] 依 Ring 固定屬性分類為：{title}")
        return title

    # Amulets have their own recipe signatures. Do not reuse ring checks:
    # Blood Amulet adds Faster Run/Walk; Caster Amulet adds Faster Cast Rate;
    # Hit Power Amulet adds Monster Flee; Safety Amulet adds Chance of Blocking.
    if is_amulet:
        # Correct isolated OCR I/l substitutions in numeric rolls only.
        amulet_text = re.sub(r"\b[il]\b", "1", text)

        def has_amulet_stat(pattern):
            return bool(re.search(pattern, amulet_text, re.IGNORECASE))

        has_amulet_life_leech = (
            has_amulet_stat(r"\b\d+(?:-\d+)?\s*%?\s*life\s+stolen\s+per\s+hit\b")
            or has_amulet_stat(r"\b\d+(?:-\d+)?\s*%?\s*(?:life\s+leech|life\s+steal)\b")
        )
        has_amulet_life = has_amulet_stat(r"\+\s*\d+(?:-\d+)?\s+(?:to\s+)?life\b")
        has_faster_run_walk = has_amulet_stat(
            r"\b\d+(?:-\d+)?\s*%?\s*faster\s+run\s*(?:/\s*|and\s+)?walk\b"
        ) or has_amulet_stat(r"\b\d+(?:-\d+)?\s*%?\s*faster\s+run(?:ning)?\b")

        has_faster_cast_rate = has_amulet_stat(
            r"\b\d+(?:-\d+)?\s*%?\s*faster\s+cast(?:ing)?\s+rate\b"
        ) or has_amulet_stat(r"\b\d+(?:-\d+)?\s*%?\s*fcr\b")
        has_amulet_mana_regen = (
            has_amulet_stat(r"\bregenerate\s+mana\s+\d+(?:-\d+)?\s*%?")
            or has_amulet_stat(r"\bmana\s+regeneration\s+\d+(?:-\d+)?\s*%?")
        )
        # diablo2.io OCR may truncate the fixed +10-20 Mana line to
        # a bare "+N" immediately before "Regenerate Mana".
        has_amulet_mana = (
            has_amulet_stat(r"\+\s*\d+(?:-\d+)?\s+(?:to\s+)?mana\b")
            or has_amulet_stat(
                r"\+\s*(?:1[0-9]|20)\s+(?=(?:regenerate\s+mana|mana\s+regeneration)\b)"
            )
        )

        has_amulet_frost_nova = has_amulet_stat(
            r"\b5\s*%?\s*chance\s+to\s+cast\s+(?:level\s+)?4\s+frost\s+nova\s+when\s+struck\b"
        ) or has_amulet_stat(r"\bfrost\s+nova\s+when\s+struck\b")
        has_monster_flee = has_amulet_stat(
            r"\bhit\s+causes\s+monster\s+to\s+flee\s+\+?\s*\d+(?:-\d+)?\s*%?"
        ) or has_amulet_stat(
            r"\bmonster\s+flees\s+\+?\s*\d+(?:-\d+)?\s*%?"
        )
        has_amulet_attacker_damage = has_amulet_stat(
            r"\battacker\s+takes\s+damage\s+(?:of\s+)?\d+(?:-\d+)?\b"
        )

        has_block_chance = has_amulet_stat(
            r"\+?\s*\d+(?:-\d+)?\s*%?\s*increased\s+chance\s+of\s+blocking\b"
        ) or has_amulet_stat(
            r"\b\d+(?:-\d+)?\s*%?\s*increased\s+chance\s+to\s+block\b"
        )
        has_amulet_damage_reduce = has_amulet_stat(
            r"\bdamage\s+reduced\s+by\s+\d+(?:-\d+)?\b"
        )
        has_amulet_magic_reduce = has_amulet_stat(
            r"\bmagic\s+damage\s+reduced\s+by\s+\d+(?:-\d+)?\b"
        )

        amulet_checks = {
            # Blood Amulet: all three fixed modifiers are distinct from Blood Ring.
            "Blood": has_amulet_life_leech and has_amulet_life and has_faster_run_walk,
            # Caster Amulet: FCR is mandatory; do not confuse it with Caster Ring.
            "Caster": has_faster_cast_rate and has_amulet_mana_regen and has_amulet_mana,
            # Hit Power Amulet: Monster Flee is unique to this amulet recipe.
            "Hit Power": has_amulet_frost_nova and has_monster_flee and has_amulet_attacker_damage,
            # Safety Amulet: blocking chance distinguishes it from Safety Ring.
            "Safety": has_block_chance and has_amulet_damage_reduce and has_amulet_magic_reduce,
        }
        matched_amulets = [
            family for family, matched in amulet_checks.items() if matched
        ]
        if len(matched_amulets) != 1:
            print(
                f"[{task_id}] Amulet Craft 特徵不唯一或不足（{matched_amulets}）；"
                "保留網站 OCR 原標題。"
            )
            return None
        title = f"{matched_amulets[0]} Amulet"
        print(f"[{task_id}] 依 Amulet 專屬固定屬性分類為：{title}")
        return title

    # Non-ring, non-glove equipment keeps its existing recipe-family rules.
    # Numeric values are allowed between '+' and the stat name in OCR output.
    has_mana_regen = "regenerate mana" in text or "mana regeneration" in text
    has_plus_mana = bool(re.search(
        r"\\+\\s*\\d+\\s+(?:to\\s+)?mana\\b|increase maximum mana", text
    ))
    has_life = bool(re.search(r"\\+\\s*\\d+\\s+(?:to\\s+)?life\\b", text))
    has_life_leech = "life stolen per hit" in text or "life leech" in text or "life steal" in text
    has_damage_reduce = "damage reduced by" in text or "damage reduction" in text
    has_magic_reduce = "magic damage reduced by" in text or "magic damage reduction" in text
    has_struck = "when struck" in text or "struck" in text
    has_frost_nova = "frost nova" in text

    candidates = []
    if has_mana_regen and has_plus_mana:
        candidates.append("Caster")
    if has_life and has_life_leech:
        candidates.append("Blood")
    if has_damage_reduce and has_magic_reduce:
        candidates.append("Safety")
    if has_struck and has_frost_nova:
        candidates.append("Hit Power")

    if len(candidates) != 1:
        print(f"[{task_id}] Craft 特徵不唯一或不足（{candidates}）；保留網站 OCR 原標題。")
        return None
    title = f"{candidates[0]} {item_types[0]}"
    print(f"[{task_id}] 依 OCR 屬性規則分類為：{title}")
    return title


def process_trading_workflow(context, image_path, task_id):
    """Upload the tooltip to diablo2.io, wait for its OCR, then ask Gemini to price the text."""
    print(f"[{task_id}] 2. 正在開啟 diablo2.io 交易表單...")
    try:
        pages = context.pages
        page = pages[0] if len(pages) == 1 and pages[0].url == "about:blank" else context.new_page()
        page.set_default_timeout(15000)
        page.goto("https://diablo2.io/posting.php?mode=post&f=16", wait_until="domcontentloaded", timeout=30000)

        title_input = page.locator("input[placeholder*='Enter the exact name of the item being traded']").first
        description_box = page.locator("textarea[placeholder*='Enter any comments about the item being traded']").first
        title_input.wait_for(state="visible", timeout=15000)
        description_box.wait_for(state="visible", timeout=15000)
        before_title = title_input.input_value().strip()
        before_description = description_box.input_value().strip()
        print(f"[{task_id}] 已找到交易標題與描述欄位；準備展開圖片附件區...")

        # The screenshot shows this attachment control is collapsed until clicked.
        attach_toggle = page.get_by_text("Optional: Attach a cropped screenshot of the item", exact=False).first
        attach_toggle.wait_for(state="visible", timeout=10000)
        attach_toggle.click()
        page.wait_for_timeout(300)

        file_inputs = page.locator("input[type='file']")
        file_inputs.first.wait_for(state="attached", timeout=10000)
        input_info = page.locator("input[type='file']").evaluate_all("""els => els.map((el, index) => ({
            index, accept: (el.getAttribute('accept') || '').toLowerCase(),
            name: el.getAttribute('name') || '',
            disabled: el.disabled
        }))""")
        print(f"[{task_id}] 找到檔案控制項：{input_info}")
        image_index = next((x['index'] for x in input_info if not x['disabled'] and ('image' in x['accept'] or '.png' in x['accept'] or '.jpg' in x['accept'] or '.jpeg' in x['accept'])), None)
        if image_index is None and len(input_info) == 1 and not input_info[0]['disabled']:
            image_index = input_info[0]['index']
        if image_index is None:
            raise RuntimeError("展開圖片附件區後，無法唯一確認圖片上傳欄位；停止以避免上傳到錯誤欄位。")

        upload_input = file_inputs.nth(image_index)
        print(f"[{task_id}] 3. 正在將裁切圖片上傳至 diablo2.io...")
        upload_input.set_input_files(image_path)
        # The site may consume the selected file asynchronously and then clear or
        # replace the file input. A non-empty input.files value is not proof that
        # the upload failed, so do not use it as an upload-success gate.
        print(f"[{task_id}] 圖片已交給瀏覽器檔案控制項；等待網站處理與 OCR 回填...")
        # Playwright set_input_files emits native input/change events. Do not
        # dispatch duplicates; instead verify the resulting OCR form values.

        print(f"[{task_id}] 正在等待 diablo2.io 原生 OCR 更新標題或描述欄位（最多 45 秒）...")
        print(f"[{task_id}] 上傳後欄位初始狀態：title={len(title_input.input_value().strip())} chars, description={len(description_box.input_value().strip())} chars")
        # diablo2.io first writes a transient "[Parsing item text ...]" status.
        # That status is longer than 40 chars, so length/change alone is NOT OCR completion.
        # Wait for real item text, then require it to remain unchanged for 3 polls.
        import time
        deadline = time.monotonic() + 75
        last_snapshot = None
        stable_polls = 0
        ocr_title = ""
        ocr_description = ""
        while time.monotonic() < deadline:
            current_title = title_input.input_value().strip()
            current_description = description_box.input_value().strip()
            snapshot = (current_title, current_description)
            parsing_status = bool(re.search(
                r"parsing\\s+item\\s+text|processing\\s+(?:image|screenshot)|please\\s+wait",
                current_description,
                re.IGNORECASE
            ))
            has_item_content = (
                len(current_description) >= 50
                and not parsing_status
                and bool(re.search(
                    r"defense:|kick damage:|required level:|durability:|resist|damage reduced|life stolen|mana|frost nova|\\[quote\\]",
                    current_description,
                    re.IGNORECASE
                ))
            )
            changed_from_baseline = (
                current_title != before_title or current_description != before_description
            )
            if changed_from_baseline and has_item_content:
                if snapshot == last_snapshot:
                    stable_polls += 1
                else:
                    stable_polls = 0
                if stable_polls >= 3:
                    ocr_title, ocr_description = current_title, current_description
                    break
            else:
                stable_polls = 0
            last_snapshot = snapshot
            time.sleep(0.5)
        else:
            raise RuntimeError(
                "diablo2.io 尚未提供穩定的 OCR 物品文字（可能仍在 Parsing）；"
                "為避免把 Parsing 當成物品資料，不會呼叫 Gemini 或修改表單。"
            )

        # Strip forum quote wrappers but preserve all recognized item lines.
        ocr_description = re.sub(r"^\\[quote\\]", "", ocr_description, flags=re.IGNORECASE)
        ocr_description = re.sub(r"\\[/quote\\]$", "", ocr_description, flags=re.IGNORECASE).strip()
        ocr_text = "\\n".join(part for part in (ocr_title, ocr_description) if part).strip()
        if len(ocr_text) < 50 or re.search(r"parsing\\s+item\\s+text", ocr_text, re.IGNORECASE):
            raise RuntimeError("OCR 結果仍是狀態訊息或文字不足；停止以避免錯誤估價。")
        if len(ocr_text) < 40:
            raise RuntimeError(f"網站欄位有變動，但 OCR 文字仍不足（{len(ocr_text)} 字）；不呼叫 Gemini。")
        if ocr_title == before_title and ocr_description == before_description:
            raise RuntimeError("未偵測到網站 OCR 結果變化；不呼叫 Gemini。")
        print(f"[{task_id}] diablo2.io OCR 已更新。標題：{ocr_title!r}；描述長度：{len(ocr_description)}")
        print(f"[{task_id}] 4. 判斷 Craft 類型與物品種類...")
        crafted_title = classify_crafted_item_title(ocr_text, task_id)
        if crafted_title:
            # Autocomplete is optional. Never press Enter here: on this form Enter
            # can activate the trade submit action and navigate away.
            try:
                title_input.click()
                title_input.press("Control+A")
                title_input.press("Backspace")
                title_input.press_sequentially(crafted_title, delay=80)
                if title_input.input_value().strip() != crafted_title:
                    raise RuntimeError("標題欄位未保留輸入文字")

                print(f"[{task_id}] 已逐字輸入 {crafted_title}；等待自動完成建議...")
                page.wait_for_timeout(2500)
                clicked = page.evaluate("""(target) => {
                    const input = document.querySelector(
                        "input[placeholder*='Enter the exact name of the item being traded']"
                    );
                    if (!input) return false;
                    const norm = value => (value || '').trim().toLocaleLowerCase().replace(/\\s+/g, ' ');
                    const wanted = norm(target);
                    const inputRect = input.getBoundingClientRect();
                    const candidates = Array.from(document.querySelectorAll(
                        '[role="option"], li, .ui-menu-item, .tt-suggestion, ' +
                        '.autocomplete-suggestion, [class*="suggest"]'
                    )).filter(el => {
                        const style = getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        const text = norm(el.innerText || el.textContent);
                        const visible = style.display !== 'none' &&
                                        style.visibility !== 'hidden' &&
                                        rect.width > 0 && rect.height > 0;
                        const safeTag = !['FORM', 'BUTTON', 'INPUT', 'TEXTAREA'].includes(el.tagName);
                        const nearInput = rect.top >= inputRect.top - 20 &&
                                          rect.top < inputRect.bottom + 260;
                        return visible && safeTag && nearInput && text === wanted;
                    }).sort((a, b) => {
                        const ar = a.getBoundingClientRect(), br = b.getBoundingClientRect();
                        return (ar.width * ar.height) - (br.width * br.height);
                    });
                    if (!candidates.length) return false;
                    candidates[0].dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
                    candidates[0].dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));
                    candidates[0].click();
                    return true;
                }""", crafted_title)
                if clicked:
                    print(f"[{task_id}] 已用滑鼠事件選取完全符合的自動完成項目。")
                else:
                    print(f"[{task_id}] 未找到安全且完全符合的下拉項目；保留標題並繼續 Gemini。")
                # Verify the form is still present; autocomplete must never navigate away.
                if title_input.count() == 0 or not title_input.is_visible():
                    print(f"[{task_id}] 自動完成後標題欄位不存在；不再操作頁面，價格流程仍嘗試繼續。")
                ocr_title = crafted_title
            except Exception as e:
                print(f"[{task_id}] 自動完成未選取（{e}）；保留標題並繼續 Gemini。")
                ocr_title = crafted_title
        else:
            print(f"[{task_id}] 無法可靠分類為指定 Craft 類型，保留網站 OCR 標題。")
        print(f"[{task_id}] OCR 原文（前 500 字）：{ocr_text[:500]}")
        print(f"[{task_id}] 5. 將網站 OCR 文字交給 Gemini 估價...")
        estimate = ask_gemini_to_price_only(ocr_text)
        if estimate and estimate.strip().casefold() != "unknown":
            price_line = f"BIN: {estimate} (Valuation source: Gemini; Attempt: 1)"
        else:
            # Preserve the original two-pass Gemini behavior: the optimistic
            # recommendation is the single retry. Only use local valuation if
            # this second Gemini request also fails to return a usable result.
            print(f"[{task_id}] Gemini first valuation failed; retrying Gemini once with recommended-price prompt...")
            retry_estimate = ask_gemini_recommended_price(ocr_text)
            retry_failed = (
                not retry_estimate
                or retry_estimate.strip().casefold() in {"unknown", "n/a", "error"}
                or "manual review" in retry_estimate.casefold()
                or "gemini unavailable" in retry_estimate.casefold()
            )
            if not retry_failed:
                price_line = f"{retry_estimate} (Valuation source: Gemini; Attempt: 2)"
            else:
                print(f"[{task_id}] Gemini retry also failed; trying embedded local valuation...")
                local_result = None
                if re.search(r"\bring\b", ocr_text, re.IGNORECASE):
                    local_result = ask_local_ring_valuation(ocr_title, ocr_description, task_id)
                if local_result:
                    price_line = local_result["price_line"]
                else:
                    price_line = (
                        "Unknown from Gemini after 2 attempts; "
                        "local valuation unavailable. Please self judge."
                    )
        # Do not attempt form writes after an unexpected navigation.
        if page.is_closed() or "/posting.php?mode=post" not in page.url:
            raise RuntimeError(
                f"diablo2.io 表單已離開或被導向（{page.url}）；"
                "為避免誤寫其他頁面，停止價格回填。請確認未提交交易。"
            )
        # Preserve the OCR textarea without firing its input/change handlers:
        # the site listens to edits there and may restart its own OCR/parser,
        # replacing valid OCR text with a transient "Parsing..." status.
        base_description = ocr_description if ocr_description else ocr_text
        final_description = f"{base_description}\n\n{price_line}"
        description_box.evaluate("""(el, value) => {
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLTextAreaElement.prototype, 'value'
            ).set;
            setter.call(el, value);
        }""", final_description)
        if description_box.input_value().strip() != final_description.strip():
            raise RuntimeError("價格文字寫入後回讀驗證失敗；停止。")
        print(f"[{task_id}] 已保留 OCR 原文並加入價格（未觸發網站重新解析）：{price_line}")

        # The site can clear the file input after receiving the image for OCR.
        # OCR field changes are the reliable signal here; do not require the
        # transient input.files list to remain populated.
        if title_input.input_value().strip() != ocr_title:
            raise RuntimeError("交易標題在估價階段發生非預期變化；停止。")
        print(f"[{task_id}] 【完成】網站 OCR、Gemini 估價及欄位驗證完成。")
        print("請人工確認遊戲模式、平台、物品類別、圖片附件與價格，再自行點擊 Create Trade Listing。")
    except Exception as e:
        print(f"[{task_id}] 工作流程停止：{type(e).__name__}: {e}")
    finally:
        if os.path.exists(image_path):
            try:
                os.remove(image_path)
            except OSError as e:
                print(f"[{task_id}] 無法清理暫存圖片 {image_path}: {e}")

def on_f9_pressed():
    """Capture one item per F9 press and enqueue it for sequential processing."""
    task_id = uuid.uuid4().hex[:6].upper()
    raw_img = f"raw_{task_id}.png"
    cropped_img = f"crop_{task_id}.jpg"

    # keyboard hotkey callbacks may overlap; serialize capture so each queued
    # task gets its own complete screenshot before the next F9 capture begins.
    with CAPTURE_LOCK:
        try:
            capture_d2r_screen(raw_img)
            detect_and_crop_tooltip(raw_img, cropped_img)
            if os.path.exists(raw_img):
                os.remove(raw_img)

            # Unbounded FIFO queue: every successfully captured F9 request waits
            # until the single browser worker is ready to process it.
            TASK_QUEUE.put((cropped_img, task_id))
            print(
                f"[{task_id}] 裝備掃描成功！已加入排程；"
                f"目前等待中的任務：{TASK_QUEUE.qsize()}"
            )
        except Exception as e:
            print(f"[{task_id}] 裝備掃描停止：{type(e).__name__}: {e}")
            for path in (raw_img, cropped_img):
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass

def main():
    print("==========================================================")
    print("  D2R 一鍵 [F9] 安全單執行緒核心 ➔ 共用登入狀態")
    print("  Classifier diagnostic build: glove-itemtype-2026-11-08")
    print("==========================================================")
    print("正在初始化共享瀏覽器核心，請稍候...")
    try:
        start_embedded_collector()
    except Exception as collector_error:
        print(
            "[Local Valuator] Embedded collector failed to start; "
            f"local fallback will be unavailable: {collector_error}"
        )
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=PURE_SANDBOX_DIR,
            headless=False
        )
        print("🚀 [系統] 共享登入狀態的瀏覽器核心已啟動完成。")
        print(f"📦 [系統] 價格歷史資料庫: {PRICE_DB_PATH}")
        print("\n系統準備就緒！")
        print("👉 請進入 D2R 遊戲，滑鼠指著裝備並按下 [F9] 鍵。")
        print("👉 系統會自動導向交易區、觸發 OCR 並填入待確認描述。")
        print("👉 最終上架仍由你手動確認。按 Ctrl+C 可安全退出。")
        print("----------------------------------------------------------")
        keyboard.add_hotkey("f9", on_f9_pressed)
        try:
            while True:
                try:
                    cropped_img, task_id = TASK_QUEUE.get(timeout=0.25)
                except queue.Empty:
                    cropped_img = task_id = None
                if cropped_img:
                    try:
                        process_trading_workflow(context, cropped_img, task_id)
                    finally:
                        TASK_QUEUE.task_done()
                try:
                    _ = context.pages
                except Exception:
                    print("[系統] 瀏覽器核心已被關閉，系統安全退出。")
                    break
        except KeyboardInterrupt:
            print("\n[系統] 收到中斷訊號，準備安全退出。")
        finally:
            keyboard.unhook_all()
            try:
                context.close()
            except Exception:
                pass
if __name__ == "__main__":
    main()
