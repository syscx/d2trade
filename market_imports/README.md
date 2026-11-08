# Market data import folder

Put exported/curated CSV or JSON observations here before running
python update_market_data.py.

Required fields: item_text, price_ist, status (sold or listing), source.
Category may be supplied or inferred. Optional fields: platform, realm, ladder,
season, observed_at (or sold_at), source_url.

Only mark completed sales as sold. Asking prices must be listing. Prices must
already be normalized to Ist. Keep exports homogeneous by platform, realm,
ladder, and season because current matching does not yet segment these fields.


For affix-aware pricing, include an optional affixes_json field. It should be a
JSON object of stable affix identifiers to numeric rolls, for example:

    {"enhanced_damage_pct": 35, "max_damage": 6, "strength": 8, "life": 11}

Use the same affix identifier consistently across every sale record. This
allows the model to compare four-affix jewels with different random rolls
instead of requiring identical item text. OCR-only extraction is incomplete.
