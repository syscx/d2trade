"""Transparent rune-to-Perfect-Skull conversion helpers.

Configured rates supplied by the user:
1 Ist = 15 Pskulls; 1 Jah = 15 Ist = 225 Pskulls.
Unknown rune rates remain unknown rather than being guessed.
"""
from __future__ import annotations

IST_VALUE_PSKULLS = 15
DEFAULT_RUNE_VALUES_PSKULLS = {
    "Ist": 15,
    "Jah": 225,
    "Perfect Skull": 1,
    "Pskull": 1,
    "Pskulls": 1,
}

def normalize_rune_name(name: str) -> str:
    return name.strip().title()

def rune_bundle_value_pskulls(runes: list[dict], rates: dict[str, float] | None = None) -> dict:
    if not runes:
        return {"value_pskulls": None, "display": None, "missing_rune_rates": [],
                "ist_anchor_pskulls": IST_VALUE_PSKULLS}
    table = dict(DEFAULT_RUNE_VALUES_PSKULLS)
    if rates:
        table.update({normalize_rune_name(k): float(v) for k, v in rates.items()})
    total = 0.0
    missing = []
    for item in runes:
        name = normalize_rune_name(str(item.get("rune", "")))
        qty = int(item.get("quantity", 0))
        if qty < 0:
            raise ValueError("rune quantity cannot be negative")
        if name not in table:
            missing.append(name)
        else:
            total += qty * table[name]
    if missing:
        return {"value_pskulls": None, "display": None,
                "missing_rune_rates": sorted(set(missing)),
                "ist_anchor_pskulls": IST_VALUE_PSKULLS}
    display = f"{total:g} Pskulls" if total < IST_VALUE_PSKULLS else f"{total / IST_VALUE_PSKULLS:.2f} Ist"
    return {"value_pskulls": round(total, 4), "display": display,
            "missing_rune_rates": [], "ist_anchor_pskulls": IST_VALUE_PSKULLS}
