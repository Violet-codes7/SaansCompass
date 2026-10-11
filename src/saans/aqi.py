"""CPCB-style AQI from PM2.5 and PM10.

CPCB defines these breakpoints for 24-hour averages. Applying them to single
hours gives an approximation, so every page labels hourly AQI as an estimate.
Each segment starts where the previous one ends so there are no gaps between
CPCB's integer breakpoints (for example 30 and 31 µg/m³).
"""

import re

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


# Band words in written text (an AI answer): a band named right next to an AQI
# number must be that number's band on the scale above, whatever the writer chose.
_BAND = "|".join(sorted((re.escape(name) for _, name in CATEGORIES), key=len, reverse=True))
_NOT_A_BAND = (r"(?![ \t]+(?:time|times|idea|news|exercise|activity|activities|walk|walks|run|runs|workout|day|choice|option|moment|window|reason|thing|way|start|plan|for[ \t]+(?:a|an|your|you)\b))"
               r"(?![ \t]*(?:-|–|to\b|or\b)[ \t]*(?:" + _BAND + r"))")  # a range of bands is left alone
_NUMBER = r"(?<![\d:.])(\d{1,3})(?![\d:.])"
_AFTER = re.compile(  # "AQI 218 (Moderate)", "AQI of 218, moderate", "AQI 218 which is moderate", "218 (Moderate)"
    r"(?:\bAQI\b(?:[ \t]*(?:of|is|was|at|around|about|near|nearly|roughly|~|:|=))*[ \t]*~?" + _NUMBER
    + r"(?P<sep>[ \t]*(?:\(|,|;|:|-|–|—|\bis\b|\bwhich is\b|\bi\.e\.)?[ \t]*(?:(?:still|already|now|only|in the|in)[ \t]+)?)"
    + r"|(?<![-–])(?<!to )(?<!- )" + _NUMBER + r"(?P<sep2>[ \t]*\([ \t]*))"  # not the end of a range
    + r"(?P<band>" + _BAND + r")\b" + _NOT_A_BAND, re.IGNORECASE)
_BEFORE = re.compile(  # "Moderate (AQI 218)", "a moderate AQI of 218"
    r"\b(?P<band>" + _BAND + r")(?P<sep>[ \t]*(?:air(?:[ \t]+quality)?[ \t]*)?(?:\([ \t]*)?AQI(?:[ \t]+of)?[ \t]*~?)" + _NUMBER,
    re.IGNORECASE)


def _like(word, band):
    """`band` in the same case as the word it replaces."""
    if word.isupper():
        return band.upper()
    return band.lower() if word.islower() else band


def correct_bands(text):
    """`text` with each band word that sits next to an AQI number replaced by
    that number's band on this scale; everything else is left as it is."""
    if not text:
        return text

    def after(m):
        value = int(m.group(1) or m.group(3))
        band = m.group("band")
        return m.group(0)[:m.start("band") - m.start()] + _like(band, category(min(value, MAX_AQI)))

    def before(m):
        value = int(m.group(3))
        return _like(m.group("band"), category(min(value, MAX_AQI))) + m.group("sep") + m.group(3)

    return _BEFORE.sub(before, _AFTER.sub(after, text))
