# Local D2R market evaluator

## Pricing approach

- Gemini remains the primary estimate. The local model runs when Gemini returns
  Unknown or fails.
- Supports crafted amulets, rings, gloves, boots, and rare jewels requiring
  level 19 or lower.
- It does not require exact item-text matches or a fixed minimum of three comps.
  It compares affix identities and roll values, then weights completed sales
  according to normalized roll distance.
- For each affix, roll differences are normalized against the observed range
  in the sales dataset. This prevents a raw +5 life difference from being
  treated as equivalent to a +5% damage difference.
- Affix identity matters: different affixes are not treated as the same stat.
  If no shared affix identity exists in the sales dataset, the model refuses
  to extrapolate and requests manual review.
- The estimate is a similarity-weighted median of the nearest completed sales,
  reducing the influence of extreme outlier prices.
- Confidence and training sample counts are returned with each estimate.
  A low-confidence estimate is not a verified market value.

## Important: structured affix data

OCR text alone cannot reliably identify every affix or distinguish all
four-affix rare jewels. For better training data, supply affixes_json on each
observation. It must be a JSON object whose keys are stable affix identifiers
and whose values are the actual numeric rolls. Example:

    {
      "enhanced_damage_pct": 35,
      "max_damage": 6,
      "strength": 8,
      "life": 11
    }

Use the same identifier for the same affix on every record. Do not merge
different affixes just because their displayed text or numeric values look
similar. Keep the complete item text too, so the parsed data can be audited.
The current OCR parser is a convenience fallback for common stats, not a
complete D2R affix parser.

## Import and daily update

1. Collect/export data in a way permitted by each site's terms and applicable law.
   This branch does not scrape Traderie, diablo2.io, or JSP.
2. Normalize prices to Ist; mark verified completed sales sold and asking
   prices listing. Only completed sales train the model.
3. Put CSV/JSON exports in market_imports/.
4. Run python update_market_data.py daily, or:
   python local_market_evaluator.py --import-file path/to/export.json --snapshot

The daily job has a one-hour runtime budget, logs per-file errors, and writes a
latest snapshot. It does not rewrite code or automatically promote scoring rules.
Schedule it with Windows Task Scheduler using an At startup trigger, python.exe
as the program, update_market_data.py as the argument, and this repository as
the working directory.

## Limitations and next validation

- No marketplace API integration or automatic scraping is included.
- Prices must be normalized to Ist by the data provider; exchange-rate history
  is not modeled.
- Current training comparisons do not yet segment by platform, realm, ladder,
  or season; keep each import dataset homogeneous.
- Per-affix roll normalization currently uses observed dataset ranges, not a
  complete game-data table of legal affix roll ranges.
- Affix extraction from OCR is incomplete. For rare jewels and crafted items,
  structured affixes_json is strongly recommended.
- This is a first data-driven prototype. Validate estimates against held-out
  sales and manually reviewed examples before relying on prices.
