# Market data import folder

Put exported/curated CSV or JSON observations here before running
python update_market_data.py.

Required fields: item_text, price_ist, status (sold or listing), source.
Category may be supplied or inferred. Optional fields: platform, realm, ladder,
season, observed_at (or sold_at), source_url.

Only mark completed sales as sold. Asking prices must be listing. Prices must
already be normalized to Ist. Keep exports homogeneous by platform, realm,
ladder, and season because current matching does not yet segment these fields.
