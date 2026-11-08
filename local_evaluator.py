"""Evidence-based local D2R evaluator.

Imports normalized market observations from CSV/JSON into SQLite. Verified sales
are kept separate from asking listings. Thin evidence returns MANUAL REVIEW.
"""
from __future__ import annotations
import csv, hashlib, json, os, re, sqlite3, statistics
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB_PATH = Path(os.getenv("D2_MARKET_DB", str(Path.home() / "Desktop" / "d2_market_intelligence.db")))
DATA_DIR = Path(os.getenv("D2_MARKET_DATA", str(Path.home() / "Desktop" / "d2_market_data")))
MIN_SALES = 3
SUPPORTED = {"amulet", "ring", "gloves", "boots", "jewel"}

def now():
    return datetime.now(timezone.utc).isoformat()

def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=20)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS observations(
          id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL,
          source TEXT NOT NULL, source_id TEXT, category TEXT NOT NULL,
          craft TEXT NOT NULL DEFAULT '', item_text TEXT NOT NULL,
          stats_json TEXT NOT NULL, price_ist REAL NOT NULL,
          status TEXT NOT NULL, observed_at TEXT NOT NULL, url TEXT
        );
        CREATE INDEX IF NOT EXISTS obs_lookup ON observations(category, craft, status, observed_at);
        CREATE TABLE IF NOT EXISTS daily_snapshot(
          day TEXT NOT NULL, category TEXT NOT NULL, craft TEXT NOT NULL,
          sold_count INTEGER NOT NULL, listed_count INTEGER NOT NULL,
          sold_median REAL, listed_median REAL, updated_at TEXT NOT NULL,
          PRIMARY KEY(day, category, craft)
        );
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)

def category_of(text):
    t = (text or "").lower()
    if re.search(r"\brare\s+jewel\b|\bjewel\b", t): return "jewel"
    for name, pat in (("amulet",r"\bamulet\b"),("ring",r"\bring\b"),
                      ("gloves",r"\b(gloves|gauntlets|bracers|mitts)\b"),
                      ("boots",r"\b(boots|greaves)\b")):
        if re.search(pat,t): return name
    return None

def parse_stats(text):
    t = (text or "").lower()
    patterns = {
      "fcr":r"(\d+)\s*%\s*faster\s+cast(?:ing)?\s+rate",
      "frw":r"(\d+)\s*%\s*faster\s+run(?:/walk| and walk)?",
      "ias":r"(\d+)\s*%\s*increased\s+attack\s+speed",
      "life":r"\+\s*(\d+)\s+(?:to\s+)?life\b",
      "mana":r"\+\s*(\d+)\s+(?:to\s+)?mana\b",
      "strength":r"\+\s*(\d+)\s+(?:to\s+)?strength\b",
      "dexterity":r"\+\s*(\d+)\s+(?:to\s+)?dexterity\b",
      "all_res":r"\+\s*(\d+)\s+to\s+all\s+resistances",
      "fire_res":r"\+\s*(\d+)\s*%\s*(?:to\s+)?fire\s+resist",
      "cold_res":r"\+\s*(\d+)\s*%\s*(?:to\s+)?cold\s+resist",
      "light_res":r"\+\s*(\d+)\s*%\s*(?:to\s+)?lightning\s+resist",
      "poison_res":r"\+\s*(\d+)\s*%\s*(?:to\s+)?poison\s+resist",
      "life_leech":r"(\d+)\s*%\s*life\s+stolen\s+per\s+hit",
      "mana_leech":r"(\d+)\s*%\s*mana\s+stolen\s+per\s+hit",
      "crushing_blow":r"(\d+)\s*%\s*crushing\s+blow",
      "magic_find":r"(\d+)\s*%\s*better\s+chance\s+of\s+getting\s+magic\s+items",
      "enhanced_damage":r"(\d+)\s*%\s*enhanced\s+damage",
      "max_damage":r"\+\s*(\d+)\s+to\s+maximum\s+damage",
      "min_damage":r"\+\s*(\d+)\s+to\s+minimum\s+damage",
      "required_level":r"required\s+level\s*:\s*(\d+)",
    }
    result={}
    for key,pat in patterns.items():
        m=re.search(pat,t)
        if m: result[key]=float(m.group(1))
    if "all_res" in result:
        for k in ("fire_res","cold_res","light_res","poison_res"):
            result[k]=max(result.get(k,0),result["all_res"])
    return result

def detect_craft(text, category):
    t=(text or "").lower()
    signatures = {
      "blood": ("life stolen per hit", "life leech", "life steal"),
      "caster": ("regenerate mana", "mana regeneration"),
      "hit power": ("knockback",),
      "safety": ("damage reduced by", "magic damage reduced by"),
    }
    hits=[]
    for craft,terms in signatures.items():
        if all(term in t for term in terms): hits.append(craft)
    # Amulet/ring/glove fixed mods vary; avoid guessing where signatures overlap.
    if category=="amulet" and "faster cast rate" in t and ("regenerate mana" in t or "mana regeneration" in t):
        hits.append("caster")
    if category=="amulet" and "faster run" in t and ("life stolen per hit" in t or "life leech" in t):
        hits.append("blood")
    unique=list(dict.fromkeys(hits))
    return unique[0] if len(unique)==1 else ""

def _fingerprint(row):
    raw="|".join(str(row.get(k,"")) for k in
      ("source","source_id","category","craft","item_text","price_ist","status","observed_at"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def import_row(row):
    item=str(row.get("item_text") or "").strip()
    category=str(row.get("category") or category_of(item) or "").lower()
    if not item or category not in SUPPORTED: return False
    try: price=float(row["price_ist"])
    except (KeyError,TypeError,ValueError): return False
    if price<0: return False
    status=str(row.get("status") or "listed").lower()
    if status not in {"sold","listed","unknown"}: return False
    observed=str(row.get("observed_at") or now())
    stats=row.get("stats") or parse_stats(item)
    craft=str(row.get("craft") or detect_craft(item,category)).lower()
    data={"source":str(row.get("source") or "manual"),"source_id":row.get("source_id"),
          "category":category,"craft":craft,"item_text":item,"price_ist":price,
          "status":status,"observed_at":observed}
    fp=_fingerprint(data)
    with connect() as db:
        cur=db.execute("""INSERT OR IGNORE INTO observations
          (fingerprint,source,source_id,category,craft,item_text,stats_json,price_ist,status,observed_at,url)
          VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
          (fp,data["source"],data["source_id"],category,craft,item,json.dumps(stats),
           price,status,observed,row.get("url")))
        return cur.rowcount==1

def import_directory():
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    added=skipped=0
    for path in sorted(DATA_DIR.iterdir()):
        try:
            if path.suffix.lower()==".csv":
                with path.open(encoding="utf-8-sig",newline="") as f: rows=list(csv.DictReader(f))
            elif path.suffix.lower()==".json":
                obj=json.loads(path.read_text(encoding="utf-8"))
                rows=obj if isinstance(obj,list) else obj.get("observations",[])
            else: continue
            for row in rows:
                if import_row(row): added+=1
                else: skipped+=1
        except Exception as exc:
            print(f"[LocalEvaluator] import failed for {path.name}: {exc}")
    return added,skipped

def update_daily_snapshot(day=None):
    day=day or datetime.now(timezone.utc).date().isoformat()
    start=day+"T00:00:00"
    end=(datetime.fromisoformat(day)+timedelta(days=1)).isoformat()
    with connect() as db:
        groups=db.execute("""SELECT category,craft,
          SUM(status='sold') sold_count,SUM(status='listed') listed_count,
          GROUP_CONCAT(CASE WHEN status='sold' THEN price_ist END) sold_prices,
          GROUP_CONCAT(CASE WHEN status='listed' THEN price_ist END) listed_prices
          FROM observations WHERE observed_at>=? AND observed_at<?
          GROUP BY category,craft""",(start,end)).fetchall()
        for g in groups:
            sold=[float(x) for x in (g["sold_prices"] or "").split(",") if x]
            listed=[float(x) for x in (g["listed_prices"] or "").split(",") if x]
            db.execute("INSERT OR REPLACE INTO daily_snapshot VALUES(?,?,?,?,?,?,?,?)",
              (day,g["category"],g["craft"],g["sold_count"],g["listed_count"],
               statistics.median(sold) if sold else None,
               statistics.median(listed) if listed else None,now()))
        db.execute("INSERT OR REPLACE INTO metadata VALUES('latest_snapshot',?)",(day,))

def evaluate(item_text):
    init_db()
    category=category_of(item_text)
    if not category:
        return {"price":None,"price_text":"MANUAL REVIEW (unsupported or unclear item type)",
                "confidence":"none","reason":"Could not identify amulet, ring, gloves, boots, or jewel."}
    stats=parse_stats(item_text)
    craft=detect_craft(item_text,category) if category!="jewel" else ""
    cutoff=(datetime.now(timezone.utc)-timedelta(days=45)).isoformat()
    with connect() as db:
        rows=db.execute("""SELECT * FROM observations WHERE category=? AND craft=?
          AND observed_at>=? AND status='sold' ORDER BY observed_at DESC""",
          (category,craft,cutoff)).fetchall()
        asks=db.execute("""SELECT price_ist FROM observations WHERE category=? AND craft=?
          AND observed_at>=? AND status='listed'""",(category,craft,cutoff)).fetchall()
    # Similarity is based on shared observed stat keys; avoid pretending category-only
    # sales are exact comparables when the item has meaningful stats.
    comps=[]
    target=set(stats)
    for row in rows:
        other=json.loads(row["stats_json"] or "{}")
        union=target|set(other)
        similarity=len(target & set(other))/len(union) if union else 0
        if similarity>=0.25 or not target:
            comps.append((similarity,float(row["price_ist"])))
    if len(comps)<MIN_SALES:
        return {"price":None,"price_text":"MANUAL REVIEW (insufficient verified sales)",
          "confidence":"none","category":category,"craft":craft,"stats":stats,
          "sold_comps":len(comps),"listed_comps":len(asks),
          "reason":"Insufficient recent sold comparables. Listings are not treated as sales."}
    comps.sort(reverse=True)
    prices=[p for _,p in comps[:30]]
    median=statistics.median(prices)
    confidence="medium" if len(prices)>=5 else "low"
    return {"price":round(median,2),"price_text":f"BIN: {median:g} Ist",
      "low":min(prices),"high":max(prices),"confidence":confidence,
      "category":category,"craft":craft,"stats":stats,"sold_comps":len(prices),
      "listed_comps":len(asks),"reason":f"Median of {len(prices)} recent sold comparables; asking prices excluded."}

def format_price(item_text):
    result=evaluate(item_text)
    print("[LocalEvaluator] "+json.dumps(result,ensure_ascii=False))
    return result["price_text"]

if __name__=="__main__":
    init_db()
    added,skipped=import_directory()
    update_daily_snapshot()
    print(f"Local market update complete: imported={added}, skipped={skipped}, db={DB_PATH}")
