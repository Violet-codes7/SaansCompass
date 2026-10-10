"""GRAP stage: an estimate from AQI, or the stage CAQM officially declared.

CAQM, not the AQI number alone, declares the official stage. The estimate
uses the AQI bands GRAP is defined on: Stage I 201-300, Stage II 301-400,
Stage III 401-450, Stage IV above 450.
"""

from . import settings

ROMAN = {0: "None", 1: "I", 2: "II", 3: "III", 4: "IV"}
_PARSE = {
    "0": 0, "none": 0,
    "1": 1, "i": 1,
    "2": 2, "ii": 2,
    "3": 3, "iii": 3,
    "4": 4, "iv": 4,
}


# The lowest day AQI of each stage, from config/explain.json.
_STAGE_MIN_AQI = sorted(((int(k), v["min_aqi"]) for k, v in settings.load("explain")["stages"].items()), reverse=True)


def stage_from_aqi(value):
    if value is None:
        return None
    for stage, min_aqi in _STAGE_MIN_AQI:
        if value >= min_aqi:
            return stage
    return 0


def parse_stage(raw):
    """Parse a user-supplied stage. Empty means "not set". Raises ValueError."""
    if raw is None or str(raw).strip() == "":
        return None
    key = str(raw).strip().lower()
    if key not in _PARSE:
        raise ValueError("stage must be one of 0, I, II, III, IV")
    return _PARSE[key]


def next_stage(stage, value):
    """The stage above `stage` and how many AQI points `value` is below it, or None at Stage IV."""
    above = sorted((n, m) for n, m in _STAGE_MIN_AQI if n > (stage or 0))
    if not above:
        return None
    n, min_aqi = above[0]
    return {"stage": n, "label": ROMAN[n], "min_aqi": min_aqi,
            "gap": None if value is None else max(min_aqi - value, 0)}


def outside_stage():
    """The stage for a place outside Delhi-NCR, where GRAP does not apply."""
    return {"stage": 0, "label": ROMAN[0], "source": "outside", "day_aqi": None, "basis": "area", "city": None,
            "estimate": None, "next": None, "outlook": None}


def resolve_stage(day_aqi, official=None, declared=None, city=None, outlook=None):
    """Stage to use, in order: the stage the user set (official), the stage the
    team recorded from CAQM's latest order (declared), then the AQI estimate.

    `day_aqi` is the AQI the estimate is made from: Delhi's city-wide AQI
    (`city`, from data.city_air) when known, else the area's own. `outlook`
    is the city AQI forecast for the next day, for "where this is heading".
    """
    if official is not None:
        stage, source = official, "official"
    elif declared is not None:
        stage, source = declared, "declared"
    else:
        stage, source = stage_from_aqi(day_aqi), "estimate"
    estimate = stage_from_aqi(day_aqi)
    ahead = stage_from_aqi(outlook)
    return {
        "stage": stage,
        "label": "Unknown" if stage is None else ROMAN[stage],
        "source": source,
        "day_aqi": day_aqi,
        "basis": "city" if city else "area",
        "city": city,
        # The AQI estimate, shown beside a declared or user-set stage when they differ.
        "estimate": None if estimate is None else ROMAN[estimate],
        "next": next_stage(estimate, day_aqi),
        "outlook": None if ahead is None else {"aqi": outlook, "stage": ahead, "label": ROMAN[ahead]},
    }


_declared_cache = {"at": 0.0, "value": None}


def declared_stage(ssm=None, now=None):
    """Stage CAQM has declared, from SSM Parameter Store, cached for 5 minutes.

    The parameter named by OFFICIAL_STAGE_PARAM holds 0, I-IV, or "unset".
    Any error or "unset" means no declared stage, so the estimate is used.
    """
    import os
    import time

    name = os.environ.get("OFFICIAL_STAGE_PARAM")
    if not name:
        return None
    now = now if now is not None else time.time()
    if ssm is None and now - _declared_cache["at"] < settings.get("declared_stage_cache_seconds"):
        return _declared_cache["value"]
    try:
        if ssm is None:
            import boto3

            ssm = boto3.client("ssm")
        raw = ssm.get_parameter(Name=name)["Parameter"]["Value"]
        value = None if raw.strip().lower() == "unset" else parse_stage(raw)
    except Exception:
        value = None
    _declared_cache.update(at=now, value=value)
    return value
