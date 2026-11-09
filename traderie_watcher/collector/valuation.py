"""Transparent rune-to-Perfect-Skull conversion helpers.

Configured rates supplied by the user:
1 Ist = 15 Pskulls; 1 Jah = 15 Ist = 225 Pskulls.
1 Ber = 0.95 Jah; 1 Cham = 0.8 Jah.
Other unknown rune rates remain unknown rather than being guessed.
"""
from __future__ import annotations

IST_VALUE_PSKULLS = 15
DEFAULT_RUNE_VALUES_PSKULLS = {
    "Ist": 15,
    "Jah": 225,
    "Ber": 213.75,  # 0.95 Jah
    "Cham": 180,    # 0.8 Jah
    "Perfect Skull": 1,
    "Pskull": 1,
    "Pskulls": 1,
}

def normalize_rune_name(name: str) -> str:
    return name.strip().title()


def format_pskull_value(value: float | int | None) -> str | None:
    """Format small values in Pskulls and large values as Ist + Pskull remainder.

    Up to 2 Ist, exact Ist multiples retain the legacy two-decimal display;
    non-multiples stay in Pskulls. Above 2 Ist, use whole Ist plus remainder.
    """
    if value is None:
        return None
    amount = round(float(value), 4)
    if amount < 0:
        raise ValueError("value cannot be negative")
    if amount > 2 * IST_VALUE_PSKULLS:
        whole_ist = int(amount // IST_VALUE_PSKULLS)
        remainder = round(amount - whole_ist * IST_VALUE_PSKULLS, 4)
        if remainder == 0:
            return f"{amount / IST_VALUE_PSKULLS:.2f} Ist"
        return f"{whole_ist} Ist + {remainder:g} Pskulls"
    if amount == 2 * IST_VALUE_PSKULLS:
        return "2 Ist"
    if amount >= IST_VALUE_PSKULLS and amount % IST_VALUE_PSKULLS == 0:
        return f"{amount / IST_VALUE_PSKULLS:.2f} Ist"
    return f"{amount:g} Pskulls"

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
    display = format_pskull_value(total)
    return {"value_pskulls": round(total, 4), "display": display,
            "missing_rune_rates": [], "ist_anchor_pskulls": IST_VALUE_PSKULLS}
