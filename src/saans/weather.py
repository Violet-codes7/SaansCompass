"""Current weather for an area, from the Open-Meteo forecast API (no key).

Weather explains the air: still, humid air holds pollution near the ground,
and wind clears it. Cached for 30 minutes. On any failure the page simply
shows no weather; there is no demo fallback for it.
"""
import json
import logging

import requests

from . import data

log = logging.getLogger(__name__)

WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
CACHE_SECONDS = 30 * 60


def fetch_weather(area, session=None):
    params = {
        "latitude": area.lat,
        "longitude": area.lon,
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m",
        "wind_speed_unit": "kmh",
        "timezone": "Asia/Kolkata",
    }
    resp = (session or requests).get(WEATHER_URL, params=params, timeout=data.TIMEOUT_SECONDS)
    resp.raise_for_status()
    cur = resp.json()["current"]
    return {
        "time": cur["time"],
        "temp_c": float(cur["temperature_2m"]),
        "humidity": float(cur["relative_humidity_2m"]),
        "wind_kmh": float(cur["wind_speed_10m"]),
    }


def explain(w):
    """One or two sentences on what today's weather does to the air."""
    notes = []
    if w["wind_kmh"] < 10:
        notes.append("Very little wind, so pollution is not being blown away and builds up near the ground.")
    elif w["wind_kmh"] >= 20:
        notes.append("A good breeze is helping to clear pollution.")
    else:
        notes.append("A light breeze is moving some pollution along.")
    if w["humidity"] >= 70:
        notes.append("Humid air helps fine particles grow and linger, which can make haze worse.")
    if w["temp_c"] < 15:
        notes.append("Cool air near the ground often traps smoke under a warmer layer above (an inversion).")
    return " ".join(notes)


def get_weather(area, store, fetcher=None):
    fetcher = fetcher or fetch_weather  # looked up at call time so tests can replace it
    key = f"WX#{area.id}"
    try:
        cached = store.get_text(key)
        if cached:
            w = json.loads(cached)
            w["note"] = explain(w)
            return w
    except Exception as exc:
        log.warning("weather cache read failed: %s", exc)
    try:
        w = fetcher(area)
    except Exception as exc:
        log.warning("weather for %s failed: %s", area.id, exc)
        return None
    try:
        store.put_text(key, json.dumps(w), ttl_seconds=CACHE_SECONDS)
    except Exception as exc:
        log.warning("could not cache weather for %s: %s", area.id, exc)
    w["note"] = explain(w)
    return w
