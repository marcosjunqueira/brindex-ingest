"""No-float-in-the-record helper for converting source numbers into exact decimal strings.

Mirrors `cornerstone-app`'s money idiom (`cornerstone-app/src/domain/comum/decimal.ts`,
`parseDecimalExato`/`formatDecimalBR`): never format a monetary value straight from a
`float` (`str(value)`/`f"{value:.Nf}"` both leak float round-off into the string). Instead
scale to an integer at a known power-of-10 denominator, then rebuild the decimal string
from that integer via integer arithmetic.
"""

from __future__ import annotations

import math


def scale_and_format(value: float | int | str | None, decimals: int) -> str | None:
    """Convert `value` to a fixed-`decimals` decimal string, or `None` if it's blank/non-numeric.

    `value` is expected to be a `float` fresh out of `xlrd` (this project's only float source —
    see `sources/treasury.py`). Blank XLS cells surface as `''`; `None` and non-finite floats
    (`nan`/`inf`, which `xlrd` never actually produces but which would otherwise corrupt the
    scaled integer) are treated the same way.
    """
    if value is None or value == "":
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None

    scale = 10**decimals
    scaled = round(numeric * scale)
    sign = "-" if scaled < 0 else ""
    scaled_abs = abs(scaled)
    int_part = scaled_abs // scale
    if decimals == 0:
        return f"{sign}{int_part}"
    frac_part = str(scaled_abs % scale).zfill(decimals)
    return f"{sign}{int_part}.{frac_part}"
