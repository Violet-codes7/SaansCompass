"""CPCB-style AQI from PM2.5 and PM10.

CPCB defines these breakpoints for 24-hour averages. Applying them to single
hours gives an approximation, so every page labels hourly AQI as an estimate.
Each segment starts where the previous one ends so there are no gaps between
CPCB's integer breakpoints (for example 30 and 31 µg/m³).
"""

# (concentration low, concentration high, index low, index high), µg/m³
PM25_BREAKPOINTS = (
    (0, 30, 0, 50),
    (30, 60, 51, 100),
    (60, 90, 101, 200),
    (90, 120, 201, 300),
    (120, 250, 301, 400),
    (250, 380, 401, 500),
)

PM10_BREAKPOINTS = (
    (0, 50, 0, 50),
    (50, 100, 51, 100),
    (100, 250, 101, 200),
    (250, 350, 201, 300),
    (350, 430, 301, 400),
    (430, 510, 401, 500),
)

CATEGORIES = (
    (50, "Good"),
    (100, "Satisfactory"),
    (200, "Moderate"),
    (300, "Poor"),
    (400, "Very Poor"),
    (500, "Severe"),
)

MAX_AQI = 500


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
    return "Severe"


def category_slug(value):
    return category(value).lower().replace(" ", "-")
