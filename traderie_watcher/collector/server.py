"""Local, read-only ingestion API for the Traderie Passive Market Watcher.

The server binds to loopback only. It stores observations in SQLite and never
requests Traderie pages or controls the browser.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urljoin

from jewel_analysis import analyze_listing, comparable_offer_summary

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("TRADERIE_WATCHER_DB", ROOT / "traderie_observations.sqlite3"))
HOST = "127.0.0.1"
PORT = 8765
MAX_BODY = 256_000
ALLOWED_ORIGIN_PREFIX = "chrome-extension://"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def initialize() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                observation_type TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                source_url TEXT NOT NULL,
                page_context_json TEXT,
                listing_key TEXT,
                listing_title TEXT,
                asking_price_text TEXT,
                visible_text TEXT,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_observations_captured_at
                ON observations(captured_at);
            CREATE INDEX IF NOT EXISTS idx_observations_listing_key
                ON observations(listing_key);
            CREATE TABLE IF NOT EXISTS jewel_analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                observation_id INTEGER NOT NULL UNIQUE REFERENCES observations(id),
                analyzed_at TEXT NOT NULL,
                item_type TEXT NOT NULL,
                quality_hint TEXT,
                stats_json TEXT NOT NULL,
                recommendation_json TEXT NOT NULL,
                displayed_asking_price TEXT,
                requested_trade_text TEXT,
                raw_text TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_jewel_analyses_stats
                ON jewel_analyses(stats_json);
        """)


class Handler(BaseHTTPRequestHandler):
    server_version = "TraderieLocalCollector/0.1"

    def _cors(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin.startswith(ALLOWED_ORIGIN_PREFIX):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self._json(204, {})

    def do_GET(self) -> None:
        path = urlparse(self.path)
        if path.path == "/health":
            self._json(200, {"ok": True, "database": str(DB_PATH)})
            return
        if path.path == "/jewels":
            try:
                limit = min(max(int(parse_qs(path.query).get("limit", ["50"])[0]), 1), 200)
                with connect() as db:
                    rows = db.execute("""
                        SELECT j.*, o.listing_key, o.listing_title, o.source_url, o.captured_at
                        FROM jewel_analyses j
                        JOIN observations o ON o.id = j.observation_id
                        ORDER BY j.id DESC LIMIT ?
                    """, (limit,)).fetchall()
                    results = []
                    for row in rows:
                        stats = json.loads(row["stats_json"])
                        recommendation = json.loads(row["recommendation_json"])
                        results.append({
                            "observation_id": row["observation_id"],
                            "listing_title": row["listing_title"],
                            "listing_url": urljoin(row["source_url"], row["listing_key"]) if row["listing_key"] else row["source_url"],
                            "captured_at": row["captured_at"],
                            "quality_hint": row["quality_hint"],
                            "stats": stats,
                            "price_observation": {
                                "displayed_asking_price": row["displayed_asking_price"],
                                "requested_trade_text": row["requested_trade_text"],
                                "is_confirmed_sale": False
                            },
                            "recommendation": recommendation,
                            "market_comparables": comparable_offer_summary(db, stats, row["observation_id"])
                        })
                self._json(200, {"ok": True, "count": len(results), "jewels": results})
            except (ValueError, TypeError):
                self._json(400, {"error": "invalid limit"})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/observations":
            self._json(404, {"error": "not found"})
            return

        origin = self.headers.get("Origin", "")
        if not origin.startswith(ALLOWED_ORIGIN_PREFIX):
            self._json(403, {"error": "extension origin required"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY:
                raise ValueError("invalid request size")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("JSON object required")

            source_url = str(payload.get("source_url", ""))
            parsed = urlparse(source_url)
            if parsed.scheme != "https" or parsed.hostname not in {"traderie.com", "www.traderie.com"}:
                raise ValueError("source_url must be a Traderie HTTPS page")

            kind = str(payload.get("observation_type", ""))
            if kind not in {"page_context", "listing_snapshot"}:
                raise ValueError("unsupported observation_type")

            listing = payload.get("listing") if isinstance(payload.get("listing"), dict) else {}
            context = payload.get("page_context") if isinstance(payload.get("page_context"), dict) else {}
            captured_at = str(payload.get("captured_at") or datetime.now(timezone.utc).isoformat())

            with connect() as db:
                cursor = db.execute("""
                    INSERT INTO observations (
                        observation_type, captured_at, source_url, page_context_json,
                        listing_key, listing_title, asking_price_text, visible_text, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    kind, captured_at, source_url, json.dumps(context, ensure_ascii=False),
                    str(listing.get("listing_key") or "")[:1000] or None,
                    str(listing.get("title") or "")[:300],
                    str(listing.get("asking_price_text") or "")[:100],
                    str(listing.get("visible_text") or "")[:4000],
                    json.dumps(payload, ensure_ascii=False)
                ))
                if kind == "listing_snapshot":
                    analysis = analyze_listing(listing)
                    if analysis:
                        db.execute("""
                            INSERT OR REPLACE INTO jewel_analyses (
                                observation_id, analyzed_at, item_type, quality_hint,
                                stats_json, recommendation_json, displayed_asking_price,
                                requested_trade_text, raw_text
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            cursor.lastrowid, datetime.now(timezone.utc).isoformat(),
                            analysis["item_type"], analysis["quality_hint"],
                            json.dumps(analysis["stats"], sort_keys=True),
                            json.dumps(analysis["recommendation"], ensure_ascii=False),
                            analysis["price_observation"]["displayed_asking_price"],
                            analysis["price_observation"]["requested_trade_text"],
                            analysis["raw_text"]
                        ))
            self._json(201, {"ok": True, "id": cursor.lastrowid,
                             "jewel_analyzed": bool(kind == "listing_snapshot" and analysis)})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:  # Keep the server alive; report a concise error.
            self._json(500, {"error": f"storage failure: {type(exc).__name__}"})


if __name__ == "__main__":
    initialize()
    print(f"Traderie local collector listening on http://{HOST}:{PORT}")
    print(f"SQLite database: {DB_PATH}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
