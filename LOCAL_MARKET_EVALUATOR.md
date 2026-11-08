# Local D2R market evaluator

## Behavior

- Gemini remains the primary price pass.
- If Gemini returns Unknown or errors, the local evaluator checks comparable
  completed-sale records in ~/Desktop/d2_market_intelligence.db.
- Supports crafted amulets, rings, gloves, boots, and rare jewels with required
  level 19 or lower (the OCR must include required level for jewels).
- Requires at least three comparable sold records. Otherwise the form gets
  PRICE: MANUAL REVIEW; it does not fabricate a price.
- Asking prices are stored separately and excluded from default estimates.
- Estimates include an Ist range, comparable count, and confidence.

## Import and daily update

1. Collect/export data in a way permitted by each site's terms and applicable law.
   This branch does not scrape Traderie, diablo2.io, or JSP.
2. Normalize prices to Ist; mark verified sales sold and asking prices listing.
3. Place CSV/JSON exports in market_imports/.
4. Run python update_market_data.py daily, or use:
   python local_market_evaluator.py --import-file path/to/export.csv --snapshot

The daily job has a one-hour runtime budget, logs per-file errors, and writes a
latest snapshot. It does not rewrite code or automatically promote scoring rules.
Schedule it with Windows Task Scheduler using an At startup trigger, python.exe
as the program, update_market_data.py as the argument, and this repository as
the working directory. A daily trigger is preferable if repeated startup runs
are undesirable.

## Limitations

- No marketplace API integration or automatic scraping is included.
- Prices must be normalized to Ist by the data provider; exchange-rate history
  is not modeled.
- Comparable matching uses recognized stat overlap and median prices. It does
  not yet segment comps by platform, realm, ladder, or season; keep each import
  dataset homogeneous.
- This is a conservative prototype, not a validated appraisal model.
- OCR parsing is incomplete; unrecognized items return manual review.
