# Traderie Passive Market Watcher (prototype)

This is an isolated, read-only data collector. It does not modify the existing
D2R F9/F10 automation.

## What it does

- Runs only on `https://traderie.com/` and `https://www.traderie.com/`.
- Watches DOM changes and user-driven scrolling.
- Attempts to capture visible listing-card text, title, link, displayed asking
  price text, and current search/page context.
- Sends observations to a local Python service at `127.0.0.1:8765`.
- Stores raw observations in a local SQLite database.

## What it deliberately does not do

- No clicking, typing, key simulation, filter changes, or automatic Load More.
- No requests to Traderie from Python and no background crawling.
- No passwords, messages, payment data, or seller identity collection.
- A listing disappearing is not interpreted as a sale.
- Asking prices are not treated as confirmed transaction prices.

## Run the local collector

From this directory:

```bash
python collector/server.py
```

The service binds to loopback only. Health check:
`http://127.0.0.1:8765/health`.

The SQLite file is created beside `server.py` by default. Set
`TRADERIE_WATCHER_DB` to choose another location.

## Load the Chrome extension

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Choose **Load unpacked**.
4. Select `traderie_watcher/extension`.
5. Open or refresh a Traderie tab.

Start the Python collector before browsing. The extension does not control
Traderie; it only observes content already rendered in the tab.

## Structured jewel analysis

The local collector now analyzes captured listing snapshots whose title or
visible text identifies a jewel. It stores recognized stats separately in the
`jewel_analyses` table, while preserving the original observation unchanged.

Recognized first-pass properties include IAS, Enhanced Damage, Maximum Damage,
Minimum Damage, All Resistances, Life, Faster Hit Recovery, Strength, and
Dexterity. Extraction is heuristic: always compare the structured values with
the raw listing text before trusting them.

The collector also stores the displayed asking-price text and/or the
`I Give` barter request separately. These are seller asks, not confirmed
completed sales. It deliberately returns no numeric fair-value estimate until
there is enough reliable comparable-market data.

After restarting the collector, view recent jewel analyses at:

`http://127.0.0.1:8765/jewels`

Optional: `/jewels?limit=100` (maximum 200).

Each result includes structured stats, raw price/trade observations, a
heuristic recommendation, and exact-stat comparable asking offers when
available. The recommendation is a screening aid, not an appraisal.

## Data quality rules

Each row is an observation at a point in time. Repeated observations for the
same listing path can later be compared to detect price changes. A missing
listing is not proof of sale. All displayed prices remain asking-price
observations unless the user separately records a confirmed transaction.


## Blood-ring analysis and synthetic test

Listing snapshots with ring titles are also analyzed into a separate `ring_analyses`
table. The first pass recognizes FCR, life leech, life, strength, dexterity,
resistances, mana, attack rating, and replenish life. A life-leech ring is
marked a **blood-ring candidate**, not conclusively identified as a Blood craft.
FCR blood-ring screening is heuristic and does not produce a market price.

View recent ring analyses at:

`http://127.0.0.1:8765/rings`

Generate a random synthetic ring locally (it is never submitted or stored):

```bash
python collector/generate_test_blood_ring.py
```

Use `--seed 123` to reproduce a test case. Synthetic data is explicitly labeled
and must never be mixed with observed Traderie listings or verified sales.

## Rune and item valuation units

The user's current reference anchor is **1 Ist = 15 Perfect Skulls (Pskulls)**.
Sub-Ist values are displayed in Pskulls. Perfect Skull is treated as one
Pskull unit. Other rune exchange rates are deliberately left unknown until
configured from the user's own dated market observations; the collector will
not invent rates. Rune barter requests are now persisted as structured
quantity/name records as well as preserving the seller's original text.

## Recording verified completed sales

A listing disappearing or a seller's asking price is not a sale. A completed
sale must be entered separately and explicitly verified by the user.

Local API:

- `POST /sales` records a verified sale only when `verified: true`,
  `observation_id`, `sale_price_text`, and `verification_method` are supplied.
- Optional `sale_runes` is a list such as
  `[{"rune":"Ist","quantity":1},{"rune":"Perfect Skull","quantity":4}]`.
- `GET /sales` returns only records explicitly entered as verified.
- The numeric Pskull total is returned only when every rune/item in the bundle
  has a configured conversion rate. Unknown rates stay unknown.

Example local request (replace observation ID and actual sale details):

```bash
curl -X POST http://127.0.0.1:8765/sales ^
  -H "Content-Type: application/json" ^
  -d "{\"verified\":true,\"observation_id\":123,\"sale_price_text\":\"1 Ist + 4 Perfect Skulls\",\"sale_runes\":[{\"rune\":\"Ist\",\"quantity\":1},{\"rune\":\"Perfect Skull\",\"quantity\":4}],\"verification_method\":\"user_confirmed\",\"evidence_note\":\"Confirmed completed trade\"}"
```

The API binds to loopback only. Treat the verified-sales table as manually
curated training/evaluation data; do not automatically label listing snapshots
as sold.
