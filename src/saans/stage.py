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


def resolve_stage(day_aqi, official=None, declared=None):
    """Stage to use, in order: the stage the user set (official), the stage the
    team recorded from CAQM's latest order (declared), then the AQI estimate."""
    if official is not None:
        stage, source = official, "official"
    elif declared is not None:
        stage, source = declared, "declared"
    else:
        stage, source = stage_from_aqi(day_aqi), "estimate"
    return {
        "stage": stage,
        "label": "Unknown" if stage is None else ROMAN[stage],
        "source": source,
        "day_aqi": day_aqi,
    }


_declared_cache = {"at": 0.0, "value": None}
DECLARED_CACHE_SECONDS = 300


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
    if ssm is None and now - _declared_cache["at"] < DECLARED_CACHE_SECONDS:
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
