"""Loopback-only passive Traderie collector and local market-learning API."""
from __future__ import annotations
import json, os, sqlite3
from statistics import median
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urljoin
from jewel_analysis import analyze_listing, comparable_offer_summary, parse_rune_request
from ring_analysis import extract_ring_properties, score_ring_stats, ring_quality_gap, build_demand_analysis, build_recommendation, BUILD_PROFILES
from valuation import rune_bundle_value_pskulls, format_pskull_value

ROOT=Path(__file__).resolve().parent
DB_PATH=Path(os.environ.get("TRADERIE_WATCHER_DB",ROOT/"traderie_observations.sqlite3"))
HOST="127.0.0.1"; PORT=8765; MAX_BODY=256_000
ALLOWED_ORIGIN_PREFIX="chrome-extension://"

def connect():
 db=sqlite3.connect(DB_PATH); db.row_factory=sqlite3.Row; return db

def directional_sale_penalty(target_score, sale_score, threshold=10.0, decay=0.12):
 """Discount a sale only when its ring/build score exceeds the target's.

 A target stronger than the sale receives no directional penalty. The first
 threshold points of weakness are tolerated; additional gap decays the sale's
 statistical influence exponentially.
 """
 weaker_by=max(0.0,float(sale_score)-float(target_score))
 excess=max(0.0,weaker_by-float(threshold))
 penalty=__import__("math").exp(-float(decay)*excess)
 return {"weaker_by":round(weaker_by,2),"excess":round(excess,2),
         "penalty":round(penalty,4),"threshold":float(threshold)}


def is_completed_sale_listing(listing):
 # Traderie completed-sale cards use "They Give" for the item and "I Give"
 # for the seller-entered final trade price. Legacy collector stored the
 # completed-sale classification as listing_type="barter_offer".
 kind=listing.get("record_type")
 status=listing.get("transaction_status")
 if kind=="completed_sale_observation" or status=="completed_sale_page_record":
  return True
 if kind or status:
  return False
 legacy_type=listing.get("listing_type")
 they_give=str(listing.get("they_give_text") or "").strip()
 i_give=str(listing.get("i_give_text") or "").strip()
 visible=str(listing.get("visible_text") or "")
 has_both_labels=("They Give" in visible and "I Give" in visible)
 return legacy_type=="barter_offer" and bool(they_give and i_give and has_both_labels)


def initialize():
 DB_PATH.parent.mkdir(parents=True,exist_ok=True)
 with connect() as db:
  db.executescript("""
  PRAGMA journal_mode=WAL;
  CREATE TABLE IF NOT EXISTS observations (
   id INTEGER PRIMARY KEY AUTOINCREMENT, observation_type TEXT NOT NULL,
   captured_at TEXT NOT NULL, source_url TEXT NOT NULL, page_context_json TEXT,
   listing_key TEXT, listing_title TEXT, asking_price_text TEXT, visible_text TEXT,
   payload_json TEXT NOT NULL);
  CREATE INDEX IF NOT EXISTS idx_observations_captured_at ON observations(captured_at);
  CREATE INDEX IF NOT EXISTS idx_observations_listing_key ON observations(listing_key);
  CREATE TABLE IF NOT EXISTS jewel_analyses (
   id INTEGER PRIMARY KEY AUTOINCREMENT, observation_id INTEGER NOT NULL UNIQUE REFERENCES observations(id),
   analyzed_at TEXT NOT NULL, item_type TEXT NOT NULL, quality_hint TEXT,
   stats_json TEXT NOT NULL, recommendation_json TEXT NOT NULL,
   displayed_asking_price TEXT, requested_trade_text TEXT, raw_text TEXT NOT NULL);
  CREATE INDEX IF NOT EXISTS idx_jewel_analyses_stats ON jewel_analyses(stats_json);
  CREATE TABLE IF NOT EXISTS ring_analyses (
   id INTEGER PRIMARY KEY AUTOINCREMENT, observation_id INTEGER NOT NULL UNIQUE REFERENCES observations(id),
   analyzed_at TEXT NOT NULL, craft_type TEXT, stats_json TEXT NOT NULL,
   analysis_json TEXT NOT NULL, raw_text TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS verified_sales (
   id INTEGER PRIMARY KEY AUTOINCREMENT, observation_id INTEGER NOT NULL REFERENCES observations(id),
   sold_at TEXT NOT NULL, recorded_at TEXT NOT NULL, sale_price_text TEXT NOT NULL,
   sale_runes_json TEXT NOT NULL DEFAULT '[]', sale_value_pskulls REAL,
   verification_method TEXT NOT NULL, evidence_note TEXT,
   verified INTEGER NOT NULL CHECK(verified=1));
  CREATE INDEX IF NOT EXISTS idx_verified_sales_observation ON verified_sales(observation_id);
  """)
  cols={r["name"] for r in db.execute("PRAGMA table_info(jewel_analyses)")}
  if "requested_runes_json" not in cols:
   db.execute("ALTER TABLE jewel_analyses ADD COLUMN requested_runes_json TEXT NOT NULL DEFAULT '[]'")
  # Backfill previously captured listings so existing blood rings are analyzed.
  existing={r["observation_id"] for r in db.execute("SELECT observation_id FROM ring_analyses")}
  old_rows=db.execute("SELECT id,payload_json FROM observations WHERE observation_type='listing_snapshot' ORDER BY id").fetchall()
  for old in old_rows:
   try:
    payload=json.loads(old["payload_json"])
    listing=payload.get("listing") if isinstance(payload,dict) else None
    if not isinstance(listing,dict): continue
    jewel_row=db.execute("SELECT requested_runes_json FROM jewel_analyses WHERE observation_id=?",(old["id"],)).fetchone()
    if jewel_row and not jewel_row["requested_runes_json"]:
     parsed_runes=parse_rune_request(listing.get("i_give_text"))
     db.execute("UPDATE jewel_analyses SET requested_runes_json=? WHERE observation_id=?",
      (json.dumps(parsed_runes,ensure_ascii=False),old["id"]))
    # Re-analyze old snapshots on startup so newly supported stats (Dexterity,
    # Magic Find, Gold Find) are populated in the existing local database too.
    ring=extract_ring_properties(str(listing.get("title") or ""),str(listing.get("visible_text") or ""))
    if ring:
     db.execute("""INSERT INTO ring_analyses(observation_id,analyzed_at,craft_type,stats_json,analysis_json,raw_text)
      VALUES(?,?,?,?,?,?)
      ON CONFLICT(observation_id) DO UPDATE SET analyzed_at=excluded.analyzed_at,
       craft_type=excluded.craft_type,stats_json=excluded.stats_json,
       analysis_json=excluded.analysis_json,raw_text=excluded.raw_text""",
      (old["id"],datetime.now(timezone.utc).isoformat(),ring["craft_type"],
       json.dumps(ring["stats"],sort_keys=True),json.dumps(ring,ensure_ascii=False),ring["raw_text"]))
   except (ValueError,TypeError,json.JSONDecodeError):
    continue

class Handler(BaseHTTPRequestHandler):
 server_version="TraderieLocalCollector/0.2"
 def _json(self,status,data):
  body=json.dumps(data,ensure_ascii=False).encode()
  self.send_response(status); self.send_header("Content-Type","application/json; charset=utf-8")
  self.send_header("Content-Length",str(len(body)))
  origin=self.headers.get("Origin","")
  if origin.startswith(ALLOWED_ORIGIN_PREFIX):
   self.send_header("Access-Control-Allow-Origin",origin); self.send_header("Vary","Origin")
   self.send_header("Access-Control-Allow-Methods","POST, GET, OPTIONS")
   self.send_header("Access-Control-Allow-Headers","Content-Type")
  self.end_headers(); self.wfile.write(body)
 def _body(self):
  n=int(self.headers.get("Content-Length","0"))
  if n<=0 or n>MAX_BODY: raise ValueError("invalid request size")
  value=json.loads(self.rfile.read(n))
  if not isinstance(value,dict): raise ValueError("JSON object required")
  return value
 def do_OPTIONS(self): self._json(204,{})
 def do_GET(self):
  path=urlparse(self.path); params=parse_qs(path.query)
  try: limit=min(max(int(params.get("limit",["50"])[0]),1),200)
  except ValueError: self._json(400,{"error":"invalid limit"}); return
  if path.path=="/health":
   self._json(200,{"ok":True,"database":str(DB_PATH)}); return
  if path.path=="/debug/ring-sales":
   with connect() as db:
    total=db.execute("SELECT COUNT(*) FROM observations WHERE observation_type='listing_snapshot'").fetchone()[0]
    ring_total=db.execute("SELECT COUNT(*) FROM ring_analyses").fetchone()[0]
    blood_total=db.execute("SELECT COUNT(*) FROM ring_analyses WHERE craft_type='blood_candidate'").fetchone()[0]
    rows=db.execute("""SELECT o.id,o.listing_key,o.source_url,o.page_context_json,o.payload_json,ra.stats_json,ra.craft_type
      FROM observations o LEFT JOIN ring_analyses ra ON ra.observation_id=o.id
      WHERE o.observation_type='listing_snapshot' ORDER BY o.id DESC""").fetchall()
   counts={"listing_snapshots":total,"ring_analyses":ring_total,"blood_candidates":blood_total,
    "record_types":{},"completed_sale_records":0,"completed_blood_records":0,
    "parseable_rune_prices":0,"matching_fcr_10":0,"matching_fcr_10_and_two_stats":0}
   samples=[]
   for row in rows:
    try:
     payload=json.loads(row["payload_json"]); listing=payload.get("listing") or {}
     kind=listing.get("record_type") or "missing"
     counts["record_types"][kind]=counts["record_types"].get(kind,0)+1
     is_sale=is_completed_sale_listing(listing)
     if not is_sale and len(samples)<8:
      samples.append({"observation_id":row["id"],"reason":"not_classified_as_sale",
       "listing_key":row["listing_key"],"title":listing.get("title"),
       "source_url":row["source_url"],"page_context":json.loads(row["page_context_json"] or "{}"),
       "listing_fields":sorted(listing.keys()),
       "record_type":listing.get("record_type"),"listing_type":listing.get("listing_type"),
       "transaction_status":listing.get("transaction_status"),
       "visible_text":str(listing.get("visible_text") or "")[:1800]})
     if is_sale:
      counts["completed_sale_records"]+=1
      if row["craft_type"]!="blood_candidate": continue
      counts["completed_blood_records"]+=1
      trade=(listing.get("i_give_text") or listing.get("observed_trade_text") or "").strip()
      parsed=parse_rune_request(trade); value=rune_bundle_value_pskulls(parsed)
      if value["value_pskulls"] is None: 
       if len(samples)<8: samples.append({"observation_id":row["id"],"reason":"unparsed_or_unknown_price","trade_text":trade,"parsed_runes":parsed})
       continue
      counts["parseable_rune_prices"]+=1
      stats=json.loads(row["stats_json"] or "{}")
      if stats.get("fcr")==10:
       counts["matching_fcr_10"]+=1
       if len(stats)>=2: counts["matching_fcr_10_and_two_stats"]+=1
      if len(samples)<8: samples.append({"observation_id":row["id"],"reason":"parsed","trade_text":trade,"parsed_runes":parsed,"price_pskulls":value["value_pskulls"],"stats":stats})
    except (ValueError,TypeError,KeyError,json.JSONDecodeError):
     continue
   self._json(200,{"ok":True,"database":str(DB_PATH),"counts":counts,"samples":samples}); return
  if path.path=="/jewels":
   with connect() as db:
    rows=db.execute("""SELECT j.*,o.listing_key,o.listing_title,o.source_url,o.captured_at
      FROM jewel_analyses j JOIN observations o ON o.id=j.observation_id
      ORDER BY j.id DESC LIMIT ?""",(limit,)).fetchall()
    out=[]
    for r in rows:
     stats=json.loads(r["stats_json"]); runes=json.loads(r["requested_runes_json"] or "[]")
     out.append({"observation_id":r["observation_id"],"listing_title":r["listing_title"],
      "listing_url":urljoin(r["source_url"],r["listing_key"]) if r["listing_key"] else r["source_url"],
      "captured_at":r["captured_at"],"quality_hint":r["quality_hint"],"stats":stats,
      "sale_observation":{"observed_trade_text":r["requested_trade_text"],"observed_runes":runes,
       "observed_rune_value":rune_bundle_value_pskulls(runes),"record_type":"completed_sale_page_record",
       "transaction_status":"completed_sale_page_record","is_completed_sale_page_record":True,
       "sale_price_reliability":"uncertain_possible_overstatement","numeric_estimate":None},
      "recommendation":json.loads(r["recommendation_json"]),
      "market_comparables":comparable_offer_summary(db,stats,r["observation_id"])})
   self._json(200,{"ok":True,"count":len(out),"jewels":out}); return
  if path.path=="/rings":
   with connect() as db:
    rows=db.execute("""SELECT r.*,o.listing_title,o.listing_key,o.source_url,o.captured_at
      FROM ring_analyses r JOIN observations o ON o.id=r.observation_id
      ORDER BY r.id DESC LIMIT ?""",(limit,)).fetchall()
    out=[{"observation_id":r["observation_id"],"listing_title":r["listing_title"],
      "listing_url":urljoin(r["source_url"],r["listing_key"]) if r["listing_key"] else r["source_url"],
      "captured_at":r["captured_at"],"craft_type":r["craft_type"],
      "analysis":json.loads(r["analysis_json"])} for r in rows]
   self._json(200,{"ok":True,"count":len(out),"rings":out}); return
  if path.path=="/sales":
   with connect() as db:
    rows=db.execute("SELECT * FROM verified_sales ORDER BY id DESC LIMIT ?",(limit,)).fetchall()
    out=[{"sale_id":r["id"],"observation_id":r["observation_id"],"sold_at":r["sold_at"],
      "sale_price_text":r["sale_price_text"],"sale_runes":json.loads(r["sale_runes_json"]),
      "sale_value_pskulls":r["sale_value_pskulls"],"verification_method":r["verification_method"],
      "evidence_note":r["evidence_note"],"verified":True} for r in rows]
   self._json(200,{"ok":True,"count":len(out),"sales":out}); return
  self._json(404,{"error":"not found"})
 def do_POST(self):
  path=urlparse(self.path).path
  try:
   payload=self._body()
   if path=="/analyze/ring":
    title=str(payload.get("title") or "Blood Ring (SYNTHETIC TEST DATA)")[:300]
    visible=str(payload.get("visible_text") or "")[:4000]
    if not visible.strip(): raise ValueError("visible_text is required")
    analysis=extract_ring_properties(title,visible)
    if not analysis: raise ValueError("input does not look like a ring")
    analysis["build_recommendation"]=build_recommendation(analysis["stats"])
    # Completed-sale page records are automatically usable market evidence.
    # Their 90% reliability is a statistical weight, not a 10% price discount.
    from jewel_analysis import parse_rune_request
    with connect() as db:
     rows=db.execute("""SELECT o.id,o.listing_key,o.payload_json,o.captured_at,ra.stats_json,ra.craft_type
       FROM observations o JOIN ring_analyses ra ON ra.observation_id=o.id
       WHERE o.observation_type='listing_snapshot'
       ORDER BY o.captured_at DESC,o.id DESC""").fetchall()
    target=analysis["stats"]
    target_score=analysis["heuristic_score"]
    seen=set()
    comps=[]
    diagnostics={"listing_snapshots_scanned":len(rows),"completed_sales":0,"duplicate_listings_skipped":0,
      "non_completed_sales_skipped":0,"non_blood_rings_skipped":0,"unknown_or_unparsed_prices":0,
      "fcr_mismatch":0,"insufficient_stat_overlap":0,"eligible_before_top_20":0}
    for row in rows:
     try:
      saved=json.loads(row["payload_json"])
      listing=saved.get("listing") or {}
      if not is_completed_sale_listing(listing):
       diagnostics["non_completed_sales_skipped"]+=1
       continue
      diagnostics["completed_sales"]+=1
      listing_key=row["listing_key"] or str(row["id"])
      if listing_key in seen:
       diagnostics["duplicate_listings_skipped"]+=1
       continue
      seen.add(listing_key)
      if row["craft_type"]!="blood_candidate":
       diagnostics["non_blood_rings_skipped"]+=1
       continue
      trade_text=(listing.get("i_give_text") or listing.get("observed_trade_text") or "").strip()
      runes=parse_rune_request(trade_text)
      price=rune_bundle_value_pskulls(runes)
      if price["value_pskulls"] is None:
       diagnostics["unknown_or_unparsed_prices"]+=1
       continue
      other=json.loads(row["stats_json"])
      if other.get("fcr") != target.get("fcr"):
       diagnostics["fcr_mismatch"]+=1
      # FCR mismatch is a distance penalty, not a hard exclusion; different
      # builds and breakpoint choices can still make a sale informative.
      shared=set(target).intersection(other)
      if len(shared)<1:
       diagnostics["insufficient_stat_overlap"]+=1
       continue
      # Compare the union, not just shared stats: missing premium stats count as zero.
      # This prevents a weak target from matching only on its few overlapping stats.
      union=set(target).union(other)
      stat_weights={"fcr":2.0,"life_leech":1.5,"mana_leech":2.0,"life":1.5,"strength":1.4,"dexterity":1.5,
        "attack_rating":1.0,"all_resist":1.0,"fire_resist":0.8,"cold_resist":0.8,
        "lightning_resist":0.8,"poison_resist":0.8,"mana":0.7,"mana_per_kill":0.7,"poison_length_reduced":0.6,"magic_find":0.5,"gold_find":0.25}
      distance_parts={}
      for key in union:
       a=float(target.get(key,0)); b=float(other.get(key,0))
       scale=max(abs(a),abs(b),10.0)
       distance_parts[key]=round(abs(a-b)/scale*stat_weights.get(key,1.0),4)
      if key=="fcr" and a!=b: distance_parts[key]+=0.25
      stat_distance=sum(distance_parts.values())/max(sum(stat_weights.get(k,1.0) for k in union),1.0)
      other_score,_=score_ring_stats(other)
      score_gap=abs(target_score-other_score)
      quality=ring_quality_gap(target,other)
      quality_penalty=quality["penalty"]
      distance=stat_distance+(score_gap/100.0)*0.75+quality_penalty
      comps.append({"distance":distance,"stat_distance":stat_distance,"score_gap":score_gap,"quality_gap":quality,"quality_penalty":quality_penalty,
       "value":float(price["value_pskulls"]),"weight":0.90,"observation_id":row["id"],
       "trade_text":trade_text,"listing_key":listing_key,"captured_at":row["captured_at"],
       "stats":other,"heuristic_score":other_score,"shared_stats":sorted(shared),
       "distance_components":distance_parts})
     except (ValueError,TypeError,KeyError,json.JSONDecodeError):
      continue
    comps.sort(key=lambda x:x["distance"])
    diagnostics["eligible_before_top_20"]=len(comps)
    MAX_COMPARABLE_DISTANCE=0.55
    close=[x for x in comps if x["distance"] <= MAX_COMPARABLE_DISTANCE]
    diagnostics["distance_threshold"]=MAX_COMPARABLE_DISTANCE
    diagnostics["rejected_by_distance"]=sum(1 for x in comps if x["distance"] > MAX_COMPARABLE_DISTANCE)
    diagnostics["close_comparables"]=len(close)
    diagnostics["sales_phase_qualified"]=len(close)>=3

    quality_percent=float(analysis.get("quality_score_percent",target_score))
    poor_combination=bool(analysis.get("poor_stat_combination"))
    build_demand=build_demand_analysis(target)
    build_recommendation_result=build_recommendation(target)
    viable_builds=build_demand.get("viable_profiles",[])
    best_build_score=float(build_demand["best_score"])

    def adjusted_comparables(items):
     adjusted_rows=[]
     for item in items:
      bandwidth=0.65
      effective_distance=float(item.get("build_distance",item["distance"]))
      distance_weight=__import__("math").exp(-((effective_distance/bandwidth)**2))
      if item.get("build"):
       comparable_quality=max(float(item.get("sale_build_fit",0.0)),1.0)
       target_quality=max(float(item.get("target_build_fit",0.0)),1.0)
      else:
       comparable_quality=max(float(item["heuristic_score"]),1.0)
       target_quality=max(quality_percent,1.0)
      raw_quality_ratio=target_quality/comparable_quality
      # A target that is stronger than its comparable may retain an upward
      # quality adjustment. A weaker target must never receive an upward
      # adjustment from a stronger sale record.
      if item.get("build"):
       directional=directional_sale_penalty(
        item.get("target_build_fit",0.0),item.get("sale_build_fit",0.0))
      else:
       directional=directional_sale_penalty(quality_percent,item["heuristic_score"])
      directional_penalty=directional["penalty"]
      quality_ratio=max(0.50,min(1.50,raw_quality_ratio))
      if directional["weaker_by"]>0:
       quality_ratio=min(1.0,quality_ratio)
      weaker_by=directional["weaker_by"]
      adjusted_price=max(0.0,item["value"]*(quality_ratio**0.75))
      combined_weight=(item["weight"]*distance_weight*
       float(item.get("build_match_weight",1.0))*directional_penalty)
      adjusted_rows.append({**item,"distance_weight":distance_weight,
       "quality_ratio":quality_ratio,"adjusted_price":adjusted_price,
       "target_weaker_score_gap":weaker_by,
       "directional_penalty_threshold":directional["threshold"],
       "directional_penalty_excess":directional["excess"],
       "directional_price_penalty":directional_penalty,
       "combined_weight":combined_weight})
     adjusted_rows.sort(key=lambda x:x["adjusted_price"])
     return adjusted_rows

    def weighted_quantile(items,q):
     total=sum(x["combined_weight"] for x in items)
     if not items or total<=0: return None
     threshold=total*q
     running=0.0
     for item in items:
      running+=item["combined_weight"]
      if running>=threshold: return item["adjusted_price"]
     return items[-1]["adjusted_price"]

    # Phase 1: direct nearest-sale evidence. Three close completed sales are
    # required, but all eligible sales remain available to Phase 2.
    phase1_selected=close[:20] if len(close)>=3 else []
    phase="phase_1_direct_sales" if phase1_selected else "phase_2_build_specific"
    phase2_build_results=[]
    phase2_pool=[]
    phase2_build_matched=False
    if phase1_selected:
     selected=phase1_selected
     phase_reason=(f"Phase 1 qualified: {len(close)} completed Blood Ring sales "
                   f"within distance {MAX_COMPARABLE_DISTANCE}; direct ring similarity is primary.")
    else:
     # Phase 2 scores each completed sale against every viable audience for
     # the target. A sale can support multiple overlapping build profiles.
     for build in viable_builds:
      target_fit=float(build_demand["profiles"][build]["score"])
      build_weights=BUILD_PROFILES.get(build,{})
      build_sales=[]
      for item in comps:
       if int(item["stats"].get("fcr",0)) != int(target.get("fcr",0)):
        continue
       sale_demand=build_demand_analysis(item["stats"])
       sale_fit=float(sale_demand["profiles"].get(build,{}).get("score",0.0))
       if sale_fit < 25.0:
        continue
       fit_gap=abs(target_fit-sale_fit)/100.0
       parts={}
       for stat,weight in build_weights.items():
        if weight<=0: continue
        av=float(target.get(stat,0)); bv=float(item["stats"].get(stat,0))
        scale=max(abs(av),abs(bv),10.0)
        parts[stat]=abs(av-bv)/scale*float(weight)
       denominator=sum(float(w) for w in build_weights.values() if w>0) or 1.0
       build_stat_distance=sum(parts.values())/denominator
       build_distance=build_stat_distance+fit_gap*0.25
       match_weight=max(0.05,min(1.0,(sale_fit/100.0)*__import__("math").exp(-fit_gap*2.0)))
       candidate={**item,"build":build,"target_build_fit":target_fit,
        "sale_build_fit":sale_fit,"build_distance":round(build_distance,4),
        "build_distance_components":{k:round(v,4) for k,v in parts.items()},
        "build_match_weight":match_weight}
       build_sales.append(candidate)
      build_sales.sort(key=lambda x:x["build_distance"])
      for candidate in build_sales[:12]:
       phase2_pool.append(candidate)
      phase2_build_results.append({
       "build":build,"target_fit_score":target_fit,
       "fcr_segment":("10_fcr" if int(target.get("fcr",0))==10 else "non_fcr"),
       "fcr_segment_candidate_count":sum(1 for x in comps if int(x["stats"].get("fcr",0))==int(target.get("fcr",0))),
       "opposite_fcr_segment_excluded":sum(1 for x in comps if int(x["stats"].get("fcr",0))!=int(target.get("fcr",0))),
       "eligible_sale_count":len(build_sales),
       "selected_sales":[{"observation_id":x["observation_id"],
        "sale_build_fit":x["sale_build_fit"],"distance":x["build_distance"],
        "price_pskulls":x["value"]} for x in build_sales[:5]],
       "reason":("Matched completed sales whose stats also fit this build; "
                 "ranking uses ring-stat distance and similarity of build-fit scores.")
      })
     phase2_build_matched=bool(phase2_pool)
     # Deduplicate sales across overlapping builds, retaining their strongest
     # build match while recording all matching audiences.
     dedup={}
     for item in phase2_pool:
      key=item["observation_id"]
      if key not in dedup or item["build_match_weight"]>dedup[key]["build_match_weight"]:
       dedup[key]=item
      else:
       prior=dedup[key]
       prior["also_matches"]=sorted(set(prior.get("also_matches",[])+[item["build"]]))
     selected=sorted(dedup.values(),key=lambda x:x["build_distance"])[:20]
     if not selected:
      phase="phase_2_insufficient_relevant_sales"
      # Distant or audience-mismatched sales must not create an invented price.
      # In particular, a weak ring must not inherit the price of much stronger
      # melee sales merely because no close historical match exists.
      selected=[]
      phase_reason=("Phase 2 found no sufficiently relevant completed sales. "
                    "No market median is reported; collect closer sales instead.")
     else:
      phase_reason=("Phase 1 lacked three close sales. Phase 2 valued the ring using "
                    "completed sales matching its overlapping build audiences.")

    diagnostics["phase1_close_sales"]=len(close)
    diagnostics["phase1_required_close_sales"]=3
    diagnostics["phase2_build_sale_candidates"]=len(phase2_pool)
    diagnostics["phase2_builds_evaluated"]=len(phase2_build_results)
    diagnostics["valuation_phase"]=phase
    diagnostics["sales_phase_qualified"]=bool(phase1_selected)

    adjusted=adjusted_comparables(selected)
    if adjusted:
     low=weighted_quantile(adjusted,0.25)
     med=weighted_quantile(adjusted,0.50)
     high=weighted_quantile(adjusted,0.75)
     if phase1_selected:
      method="phase_1_direct_completed_sales"
      confidence="high" if len(close)>=5 and sum(x["combined_weight"] for x in adjusted)>=1.5 else "medium"
     elif phase2_build_matched:
      method="phase_2_build_specific_completed_sales"
      prices=sorted(x["adjusted_price"] for x in adjusted)
      p50=median(prices) if prices else 0.0
      relative_range=(prices[-1]-prices[0])/max(p50,1.0) if len(prices)>1 else 1.0
      effective=sum(x["combined_weight"] for x in adjusted)
      confidence=("medium" if len(adjusted)>=5 and effective>=2.0 and relative_range<=0.35 else "low")
      phase2_confidence_diagnostics={"relative_price_range":round(relative_range,3),
       "effective_sample_weight":round(effective,3),"comparable_count":len(adjusted),
       "medium_rule":"at least 5 comparables, effective weight >=2.0, relative range <=0.35"}
     else:
      method="phase_2_nearest_sales_without_build_match"
      confidence="low"
    else:
     # No priced completed sale can support a market estimate. Retain a
     # transparent heuristic anchor, but mark it explicitly as uncalibrated.
     low=None
     med=None
     high=None
     method="insufficient_relevant_completed_sales"
     confidence="very_low"
     phase_reason += " No usable comparable sale supports a numeric price estimate."

    note=phase_reason
    valuation={"status":("estimate_available" if med is not None else "insufficient_relevant_sales"),"currency":"Pskulls",
     "low":round(low,2) if low is not None else None,
     "median":round(med,2) if med is not None else None,
     "high":round(high,2) if high is not None else None,
     "display":{"low":format_pskull_value(low) if low is not None else None,
      "median":format_pskull_value(med) if med is not None else None,
      "high":format_pskull_value(high) if high is not None else None},
     "comparable_sales":len(adjusted),"eligible_comparable_sales":len(comps),
     "valuation_phase":phase,"phase1_rate":round(len(close)/max(len(comps),1),3),
     "phase1_close_sales":len(close),"phase1_required":3,
     "reliability_weight":0.90,"valuation_method":method,"confidence":confidence,
     "quality_score_percent":quality_percent,"poor_stat_combination":poor_combination,
     "effective_weight":round(sum(x["combined_weight"] for x in adjusted),4),
     "phase2_confidence_diagnostics":(phase2_confidence_diagnostics if phase2_build_matched else None),
     "diagnostics":{"target_stats":target,"target_quality_score":quality_percent,
      "target_verdict":analysis["verdict"],"counts":diagnostics,
      "build_demand":build_demand,"build_recommendation":build_recommendation_result,
      "phase_explanation":{"phase":phase,"reason":phase_reason,
       "phase1":{"close_sales":len(close),"required":3,"distance_threshold":MAX_COMPARABLE_DISTANCE,
        "qualified":bool(phase1_selected)},
       "phase2":{"builds_evaluated":phase2_build_results,"build_sale_candidate_count":len(phase2_pool)}},
      "low_quality_cap_boundary":{"quality_below":65,"requires_poor_stat_combination":True,
       "requires_zero_viable_profiles":True,"best_profile_score_below":35},
      "selection_method":"Phase 1: at least 3 close direct completed sales; Phase 2: build-fit-ranked completed sales when Phase 1 fails; heuristic only when no usable sale prices exist.",
      "selected_comparables":[{"observation_id":x["observation_id"],
       "captured_at":x["captured_at"],"sale_price_pskulls":x["value"],
       "sale_price_display":format_pskull_value(x["value"]),
       "adjusted_price_pskulls":round(x["adjusted_price"],2),
       "adjusted_price_display":format_pskull_value(x["adjusted_price"]),
       "distance":round(x.get("build_distance",x["distance"]),4),"distance_weight":round(x["distance_weight"],4),
       "build":x.get("build"),"also_matches":x.get("also_matches",[]),
       "target_build_fit":x.get("target_build_fit"),"sale_build_fit":x.get("sale_build_fit"),
       "build_match_weight":round(x.get("build_match_weight",1.0),4),
       "quality_ratio":round(x["quality_ratio"],4),
       "target_weaker_score_gap":x.get("target_weaker_score_gap",0.0),
       "directional_penalty_threshold":x.get("directional_penalty_threshold",10.0),
       "directional_penalty_excess":x.get("directional_penalty_excess",0.0),
       "directional_price_penalty":x.get("directional_price_penalty",1.0),
       "weight":round(x["combined_weight"],4),
       "stats":x["stats"],"quality_score":x["heuristic_score"],
       "quality_gap":x["quality_gap"],"distance_components":x["distance_components"],
        "build_distance_components":x.get("build_distance_components",{})}
       for x in adjusted],
      "closest_candidates":[{"observation_id":x["observation_id"],
       "price_display":format_pskull_value(x["value"]),"stats":x["stats"],
       "quality_score":x["heuristic_score"],"distance":round(x["distance"],4)}
       for x in comps[:25]]},
     "note":note}
    valuation["comparables"]=[{"observation_id":x["observation_id"],
      "sale_price_pskulls":x["value"],"sale_price_display":format_pskull_value(x["value"]),
      "estimated_contribution_pskulls":round(x["adjusted_price"],2),
      "distance":round(x.get("build_distance",x["distance"]),4),"build":x.get("build"),
      "target_build_fit":x.get("target_build_fit"),"sale_build_fit":x.get("sale_build_fit"),
      "reliability":x["weight"],
      "distance_weight":round(x["distance_weight"],4),"trade_text":x["trade_text"],
      "stats":x["stats"],"quality_score":x["heuristic_score"]} for x in adjusted]
    self._json(200,{"ok":True,"synthetic":bool(payload.get("synthetic",False)),
      "analysis":analysis,"valuation":valuation}); return
   if path=="/observations":
    origin=self.headers.get("Origin","")
    if not origin.startswith(ALLOWED_ORIGIN_PREFIX): self._json(403,{"error":"extension origin required"}); return
    source=str(payload.get("source_url","")); parsed=urlparse(source)
    if parsed.scheme!="https" or parsed.hostname not in {"traderie.com","www.traderie.com"}:
     raise ValueError("source_url must be a Traderie HTTPS page")
    kind=str(payload.get("observation_type",""))
    if kind not in {"page_context","listing_snapshot"}: raise ValueError("unsupported observation_type")
    listing=payload.get("listing") if isinstance(payload.get("listing"),dict) else {}
    context=payload.get("page_context") if isinstance(payload.get("page_context"),dict) else {}
    captured=str(payload.get("captured_at") or datetime.now(timezone.utc).isoformat())
    with connect() as db:
     cur=db.execute("""INSERT INTO observations(observation_type,captured_at,source_url,page_context_json,
      listing_key,listing_title,asking_price_text,visible_text,payload_json) VALUES(?,?,?,?,?,?,?,?,?)""",
      (kind,captured,source,json.dumps(context,ensure_ascii=False),str(listing.get("listing_key") or "")[:1000] or None,
       str(listing.get("title") or "")[:300],str(listing.get("asking_price_text") or "")[:100],
       str(listing.get("visible_text") or "")[:4000],json.dumps(payload,ensure_ascii=False)))
     analyzed={"jewel":False,"ring":False}
     if kind=="listing_snapshot":
      jewel=analyze_listing(listing)
      if jewel:
       pr=jewel["trade_observation"]
       db.execute("""INSERT INTO jewel_analyses(observation_id,analyzed_at,item_type,quality_hint,stats_json,
        recommendation_json,displayed_asking_price,requested_trade_text,raw_text,requested_runes_json)
        VALUES(?,?,?,?,?,?,?,?,?,?)""",(cur.lastrowid,datetime.now(timezone.utc).isoformat(),jewel["item_type"],
        jewel["quality_hint"],json.dumps(jewel["stats"],sort_keys=True),json.dumps(jewel["recommendation"],ensure_ascii=False),
        pr["displayed_asking_price"],pr["observed_trade_text"],jewel["raw_text"],json.dumps(pr["observed_runes"],ensure_ascii=False)))
       analyzed["jewel"]=True
      ring=extract_ring_properties(str(listing.get("title") or ""),str(listing.get("visible_text") or ""))
      if ring:
       db.execute("""INSERT INTO ring_analyses(observation_id,analyzed_at,craft_type,stats_json,analysis_json,raw_text)
        VALUES(?,?,?,?,?,?)""",(cur.lastrowid,datetime.now(timezone.utc).isoformat(),ring["craft_type"],
        json.dumps(ring["stats"],sort_keys=True),json.dumps(ring,ensure_ascii=False),ring["raw_text"]))
       analyzed["ring"]=True
    self._json(201,{"ok":True,"id":cur.lastrowid,"analyzed":analyzed}); return
   if path=="/sales":
    if payload.get("verified") is not True: raise ValueError("verified must be true; unverified asks cannot be recorded as sales")
    obs=int(payload["observation_id"]); price=str(payload.get("sale_price_text") or "").strip()
    method=str(payload.get("verification_method") or "").strip()
    if not price or not method: raise ValueError("sale_price_text and verification_method are required")
    runes=payload.get("sale_runes") or []
    if not isinstance(runes,list) or any(not isinstance(x,dict) for x in runes): raise ValueError("sale_runes must be a list of rune quantity objects")
    value=rune_bundle_value_pskulls(runes)
    numeric=value["value_pskulls"]
    sold=str(payload.get("sold_at") or datetime.now(timezone.utc).isoformat())
    with connect() as db:
     exists=db.execute("SELECT id FROM observations WHERE id=?",(obs,)).fetchone()
     if not exists: raise ValueError("observation_id not found")
     cur=db.execute("""INSERT INTO verified_sales(observation_id,sold_at,recorded_at,sale_price_text,
      sale_runes_json,sale_value_pskulls,verification_method,evidence_note,verified)
      VALUES(?,?,?,?,?,?,?,?,1)""",(obs,sold,datetime.now(timezone.utc).isoformat(),price,
      json.dumps(runes,ensure_ascii=False),numeric,method,str(payload.get("evidence_note") or "")[:2000]))
    self._json(201,{"ok":True,"sale_id":cur.lastrowid,"verified":True,
      "sale_value_pskulls":numeric,"rune_value":value}); return
   self._json(404,{"error":"not found"})
  except (ValueError,TypeError,KeyError,json.JSONDecodeError) as exc: self._json(400,{"error":str(exc)})
  except Exception as exc: self._json(500,{"error":f"storage failure: {type(exc).__name__}"})

if __name__=="__main__":
 initialize()
 print(f"Traderie local collector listening on http://{HOST}:{PORT}")
 print(f"SQLite database: {DB_PATH}")
 ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
