"""Canonicalisation of raw time-of-use slot codes."""

import re

_TOU_DIRECTION_PREFIX = re.compile(r"(?:^|_)(?:OFFTAKE|INJECTION)_")
_TOU_SLOT_CODE_ALIASES = {
    "HIGH_LOAD_HOURS": "PEAK",
    "LOW_LOAD_HOURS": "OFFPEAK",
    "EN": "EXCLUSIVE_NIGHT",
}


def canonicalise_slot_code(raw: str) -> str:
    """Drop everything through the first OFFTAKE or INJECTION token, alias-map, then lowercase."""
    upper = raw.upper()
    match = _TOU_DIRECTION_PREFIX.search(upper)
    if match is not None:
        upper = upper[match.end() :]
    return _TOU_SLOT_CODE_ALIASES.get(upper, upper).lower()
