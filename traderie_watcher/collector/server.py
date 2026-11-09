"""Loopback-only passive Traderie collector and local market-learning API."""
from __future__ import annotations
import json, os, sqlite3
from statistics import median
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urljoin
from jewel_analysis import analyze_listing, comparable_offer_summary, parse_rune_request
from ring_analysis import extract_ring_properties, score_ring_stats, ring_quality_gap
from valuation import rune_bundle_value_pskulls, format_pskull_value

ROOT=Path(__file__).resolve().parent
DB_PATH=Path(os.environ.get("TRADERIE_WATCHER_DB",ROOT/"traderie_observations.sqlite3"))
HOST="127.0.0.1"; PORT=8765; MAX_BODY=256_000
ALLOWED_ORIGIN_PREFIX="chrome-extension://"

def connect():
 db=sqlite3.connect(DB_PATH); db.row_factory=sqlite3.Row; return db

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
       continue
      shared=set(target).intersection(other)
      if len(shared)<2:
       diagnostics["insufficient_stat_overlap"]+=1
       continue
      # Compare the union, not just shared stats: missing premium stats count as zero.
      # This prevents a weak target from matching only on its few overlapping stats.
      union=set(target).union(other)
      stat_weights={"fcr":2.0,"life_leech":1.5,"mana_leech":2.0,"life":1.5,"strength":1.4,"dexterity":1.5,
        "attack_rating":1.0,"all_resist":1.0,"fire_resist":0.8,"cold_resist":0.8,
        "lightning_resist":0.8,"poison_resist":0.8,"mana":0.7,"magic_find":0.5,"gold_find":0.25}
      distance_parts={}
      for key in union:
       a=float(target.get(key,0)); b=float(other.get(key,0))
       scale=max(abs(a),abs(b),10.0)
       distance_parts[key]=round(abs(a-b)/scale*stat_weights.get(key,1.0),4)
      stat_distance=sum(distance_parts.values())/max(sum(stat_weights.get(k,1.0) for k in union),1.0)
      other_score,_=score_ring_stats(other)
      score_gap=abs(target_score-other_score)
      quality=ring_quality_gap(target,other)
      quality_penalty=quality["penalty"]
      distance=stat_distance+(score_gap/10.0)*0.75+quality_penalty
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
    selected=[x for x in comps if x["distance"] <= MAX_COMPARABLE_DISTANCE][:20]
    diagnostics["distance_threshold"]=MAX_COMPARABLE_DISTANCE
    diagnostics["rejected_by_distance"]=sum(1 for x in comps if x["distance"] > MAX_COMPARABLE_DISTANCE)
    if len(selected)>=3:
     weighted=[(item["value"],item["weight"]/(1.0+item["distance"])) for item in selected]
     weighted.sort(key=lambda x:x[0])
     total_weight=sum(w for _,w in weighted)
     def weighted_quantile(q):
      threshold=total_weight*q
      running=0.0
      for value,weight in weighted:
       running+=weight
       if running>=threshold: return value
      return weighted[-1][0]
     low=weighted_quantile(0.25); med=weighted_quantile(0.50); high=weighted_quantile(0.75)
     valuation={"status":"estimate_available","currency":"Pskulls",
       "low":low,"median":med,"high":high,
       "display":{"low":format_pskull_value(low),"median":format_pskull_value(med),"high":format_pskull_value(high)},
       "comparable_sales":len(selected),"eligible_comparable_sales":len(comps),
       "reliability_weight":0.90,"effective_weight":round(total_weight,3),
       "price_distribution":[{"price_pskulls":price,"price_display":format_pskull_value(price),
         "sale_count":sum(1 for x in selected if x["value"]==price)}
         for price in sorted({x["value"] for x in selected})],
       "diagnostics":{"target_stats":target,"target_heuristic_score":target_score,
         "target_verdict":analysis["verdict"],"selection_method":"same FCR; weighted stat distance; premium-affix mismatch penalty; heuristic-score gap penalty; max distance 0.55",
         "counts":diagnostics,"selected_comparables":[{"observation_id":x["observation_id"],
          "captured_at":x["captured_at"],"price_pskulls":x["value"],"price_display":format_pskull_value(x["value"]),
          "trade_text":x["trade_text"],"stats":x["stats"],"heuristic_score":x["heuristic_score"],
          "distance":round(x["distance"],4),"stat_distance":round(x["stat_distance"],4),
          "score_gap":x["score_gap"],"quality_gap":x["quality_gap"],"quality_penalty":x["quality_penalty"],"shared_stats":x["shared_stats"],
          "distance_components":x["distance_components"]} for x in selected],
         "next_closest_not_selected":[{"observation_id":x["observation_id"],"price_display":format_pskull_value(x["value"]),
          "stats":x["stats"],"heuristic_score":x["heuristic_score"],"distance":round(x["distance"],4),
          "quality_gap":x["quality_gap"],"rejection_reason":"outside_distance_threshold" if x["distance"] > MAX_COMPARABLE_DISTANCE else "top_20_limit"}
          for x in comps if x not in selected][:25]},
       "note":"Completed-sale page records only. Comparables must pass a strict quality-aware distance threshold; premium-affix mismatches are penalized. 90% is a reliability weight, not a price discount."}
     valuation["comparables"]=[{"observation_id":x["observation_id"],"price_pskulls":x["value"],
        "price_display":format_pskull_value(x["value"]),"distance":round(x["distance"],4),
        "reliability":x["weight"],"trade_text":x["trade_text"],
        "stats":x["stats"],"heuristic_score":x["heuristic_score"]} for x in selected]
    else:
     valuation={"status":"insufficient_data","currency":"Pskulls","low":None,"median":None,"high":None,
       "comparable_sales":len(selected),"eligible_comparable_sales":len(comps),"reliability_weight":0.90,
       "diagnostics":{"target_stats":target,"target_heuristic_score":target_score,"counts":diagnostics,
        "eligible_comparables":[{"observation_id":x["observation_id"],"price_display":format_pskull_value(x["value"]),
         "stats":x["stats"],"heuristic_score":x["heuristic_score"],"distance":round(x["distance"],4)} for x in selected],
        "closest_candidates":[{"observation_id":x["observation_id"],"price_display":format_pskull_value(x["value"]),
         "stats":x["stats"],"heuristic_score":x["heuristic_score"],"distance":round(x["distance"],4),
         "stat_distance":round(x["stat_distance"],4),"score_gap":x["score_gap"],
         "quality_gap":x["quality_gap"],"quality_penalty":x["quality_penalty"],
         "distance_components":x["distance_components"]} for x in comps[:25]]},
       "note":"At least 3 completed-sale Blood-ring records with known prices, matching FCR, and quality-aware distance <= 0.55 are required. No price is forced when close matches are insufficient."}
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
