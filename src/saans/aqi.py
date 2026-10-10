"""CPCB-style AQI from PM2.5 and PM10.

CPCB defines these breakpoints for 24-hour averages. Applying them to single
hours gives an approximation, so every page labels hourly AQI as an estimate.
Each segment starts where the previous one ends so there are no gaps between
CPCB's integer breakpoints (for example 30 and 31 µg/m³).
"""

from . import settings

_AQI = settings.load("aqi")
# (concentration low, concentration high, index low, index high), µg/m³
PM25_BREAKPOINTS = tuple(tuple(b) for b in _AQI["pm25_breakpoints"])
PM10_BREAKPOINTS = tuple(tuple(b) for b in _AQI["pm10_breakpoints"])
CATEGORIES = tuple((c["max"], c["name"]) for c in _AQI["categories"])
MAX_AQI = _AQI["max_aqi"]


def sub_index(concentration, breakpoints):
    """Index for one pollutant, or None when the reading is missing."""
    if concentration is None:
        return None
    if concentration < 0:
        raise ValueError("concentration cannot be negative")
    for c_lo, c_hi, i_lo, i_hi in breakpoints:
        if concentration <= c_hi:
            return round(i_lo + (i_hi - i_lo) * (concentration - c_lo) / (c_hi - c_lo))
    return MAX_AQI


def aqi(pm25, pm10):
    """Return (aqi, dominant pollutant). The worst pollutant wins.

    Returns (None, None) when both readings are missing.
    """
    candidates = []
    pm25_index = sub_index(pm25, PM25_BREAKPOINTS)
    pm10_index = sub_index(pm10, PM10_BREAKPOINTS)
    if pm25_index is not None:
        candidates.append((pm25_index, "PM2.5"))
    if pm10_index is not None:
        candidates.append((pm10_index, "PM10"))
    if not candidates:
        return None, None
    return max(candidates, key=lambda c: c[0])


def category(value):
    if value is None:
        return "No data"
    for upper, name in CATEGORIES:
        if value <= upper:
            return name
    return CATEGORIES[-1][1]


def category_slug(value):
    return category(value).lower().replace(" ", "-")
