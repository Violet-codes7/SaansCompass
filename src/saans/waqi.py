"""A live backup for CPCB's station readings: the World Air Quality Index
project (aqicn.org) republishes the same CPCB stations through a free API.

It reports each pollutant on the US EPA scale from the latest hourly reading,
so the value is turned back into a concentration (EPA breakpoints in
config/aqi.json) and then into India's AQI. Used only when the data.gov.in
feed gives nothing. The token is read from SSM and never logged.
"""
import json
import logging
import os
import time

from . import aqi as aqi_mod
from . import settings

log = logging.getLogger(__name__)

_key_cache = {"at": -1e18, "value": None}
_AQI = settings.load("aqi")
US_BREAKPOINTS = {"pm25": [tuple(b) for b in _AQI["us_pm25_breakpoints"]],
                  "pm10": [tuple(b) for b in _AQI["us_pm10_breakpoints"]]}


def _token(ssm=None, now=None):
    if os.environ.get("WAQI_TOKEN"):
        return os.environ["WAQI_TOKEN"]
    name = os.environ.get("WAQI_TOKEN_PARAM")
    if not name:
        return None
    now = now if now is not None else time.time()
    if ssm is None and now - _key_cache["at"] < settings.get("ai_key_cache_seconds"):
        return _key_cache["value"]
    try:
        if ssm is None:
            import boto3

            ssm = boto3.client("ssm")
        value = ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"].strip() or None
    except Exception as exc:  # not created yet, or no permission
        log.warning("aqicn token not available: %s", type(exc).__name__)
        value = None
    _key_cache.update(at=now, value=value)
    return value


def enabled():
    return bool(_token())


def us_to_concentration(index, pollutant):
    """The concentration (µg/m³) behind a US EPA sub-index, or None."""
    if index is None:
        return None
    for c_lo, c_hi, i_lo, i_hi in US_BREAKPOINTS[pollutant]:
        if index <= i_hi:
            return c_lo + (c_hi - c_lo) * (max(index, i_lo) - i_lo) / (i_hi - i_lo)
    return US_BREAKPOINTS[pollutant][-1][1]


def reading_from_feed(body):
    """{name, lat, lon, aqi, dominant, category, slug, updated} on India's
    scale from an aqicn feed answer, or None."""
    if not isinstance(body, dict) or body.get("status") != "ok" or not isinstance(body.get("data"), dict):
        return None
    d = body["data"]
    iaqi = d.get("iaqi") or {}

    def value(key):
        v = (iaqi.get(key) or {}).get("v")
        return float(v) if isinstance(v, (int, float)) else None

    pm25, pm10 = us_to_concentration(value("pm25"), "pm25"), us_to_concentration(value("pm10"), "pm10")
    aqi, dominant = aqi_mod.aqi(pm25, pm10)
    if aqi is None:
        return None
    city = d.get("city") or {}
    geo = city.get("geo") or [None, None]
    return {"name": city.get("name") or "", "lat": geo[0], "lon": geo[1], "aqi": aqi, "dominant": dominant,
            "category": aqi_mod.category(aqi), "slug": aqi_mod.category_slug(aqi),
            "updated": (d.get("time") or {}).get("s")}


def nearest(area, store=None, session=None):
    """The nearest station's reading for an area, cached for cpcb_cache_seconds, or None."""
    token = _token()
    if not token:
        return None
    key = f"WAQI#{area.id}"
    if store is not None and session is None:
        cached = store.get_text(key)
        if cached:
            return json.loads(cached) or None
    import requests

    url = settings.get("waqi_url").format(lat=area.lat, lon=area.lon)
    try:
        resp = (session or requests).get(url, params={"token": token}, timeout=settings.get("cpcb_timeout_seconds"))
        resp.raise_for_status()
        body = resp.json()
        reading = reading_from_feed(body)
        if reading is None:
            log.warning("aqicn gave no reading: %s", str(body.get("status"))[:20] if isinstance(body, dict) else "?")
    except Exception as exc:  # network, HTTP or JSON error; the URL carries the token, so log the type only
        log.warning("aqicn feed failed: %s", type(exc).__name__)
        return None
    if store is not None:
        store.put_text(key, json.dumps(reading or {}), ttl_seconds=settings.get("cpcb_cache_seconds"))
    return reading


def fresh_and_near(reading, area, now):
    """The reading as an official-air station for this area (short name,
    time, km), or None when it is too far away or too old to call "now"."""
    from datetime import datetime

    from .cpcb import _km, max_km, short_name

    if not reading or reading.get("lat") is None or reading.get("lon") is None:
        return None
    km = _km(area.lat, area.lon, reading["lat"], reading["lon"])
    if km > max_km(area, "waqi_max_km"):
        log.warning("aqicn reading not used: nearest station %.1f km away", km)
        return None
    try:
        t = datetime.strptime(str(reading.get("updated")), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        log.warning("aqicn reading not used: unreadable time")
        return None
    age = (now.replace(tzinfo=None) - t).total_seconds()
    if not 0 <= age <= settings.get("cpcb_stale_hours") * 3600:
        log.warning("aqicn reading not used: %.1f hours old", age / 3600)
        return None
    return {**reading, "short": short_name(reading["name"]), "time": t.strftime("%H:%M"), "km": round(km, 1),
            "via": "aqicn"}
