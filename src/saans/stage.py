"""GRAP stage: an estimate from AQI, or the stage CAQM officially declared.

CAQM, not the AQI number alone, declares the official stage. The estimate
uses the AQI bands GRAP is defined on: Stage I 201-300, Stage II 301-400,
Stage III 401-450, Stage IV above 450.
"""

ROMAN = {0: "None", 1: "I", 2: "II", 3: "III", 4: "IV"}
_PARSE = {
    "0": 0, "none": 0,
    "1": 1, "i": 1,
    "2": 2, "ii": 2,
    "3": 3, "iii": 3,
    "4": 4, "iv": 4,
}


def stage_from_aqi(value):
    if value is None:
        return None
    if value <= 200:
        return 0
    if value <= 300:
        return 1
    if value <= 400:
        return 2
    if value <= 450:
        return 3
    return 4


def parse_stage(raw):
    """Parse a user-supplied stage. Empty means "not set". Raises ValueError."""
    if raw is None or str(raw).strip() == "":
        return None
    key = str(raw).strip().lower()
    if key not in _PARSE:
        raise ValueError("stage must be one of 0, I, II, III, IV")
    return _PARSE[key]


def resolve_stage(day_aqi, official=None):
    """Official stage wins over the estimate. Returns a dict for templates and JSON."""
    if official is not None:
        stage, source = official, "official"
    else:
        stage, source = stage_from_aqi(day_aqi), "estimate"
    return {
        "stage": stage,
        "label": "Unknown" if stage is None else ROMAN[stage],
        "source": source,
        "day_aqi": day_aqi,
    }
