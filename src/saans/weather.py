"""Current weather for an area, from the Open-Meteo forecast API (no key).

Weather explains the air: still, humid air holds pollution near the ground,
and wind clears it. Cached for weather_cache_minutes. On any failure the page simply
shows no weather; nothing is made up in its place.
"""
import json
import logging

import requests

from . import settings

log = logging.getLogger(__name__)

TEXT = settings.load("weather")
DIALS = TEXT["dials"]


HOURLY = {"temperature_2m": "temp_c", "relative_humidity_2m": "humidity", "wind_speed_10m": "wind_kmh",
          "wind_direction_10m": "wind_dir", "boundary_layer_height": "mixing_m"}


def fetch_weather(area, session=None):
    params = {
        "latitude": area.lat,
        "longitude": area.lon,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,dew_point_2m,"
                   "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
        # Hour by hour for yesterday to tomorrow, for the plan's hourly view.
        # boundary_layer_height is how high the air near the ground mixes:
        # low means pollution is trapped.
        "hourly": ",".join(HOURLY),
        "past_days": settings.get("past_days"),
        "forecast_days": 2,
        "wind_speed_unit": "kmh",
        "timezone": settings.get("timezone"),
    }
    resp = (session or requests).get(settings.get("weather_url"), params=params,
                                     timeout=settings.get("http_timeout_seconds"))
    resp.raise_for_status()
    body = resp.json()
    cur = body["current"]

    def num(value):
        return float(value) if isinstance(value, (int, float)) else None

    hourly = body.get("hourly") or {}
    times = hourly.get("time") or []
    hours = [{"time": t, **{name: num((hourly.get(key) or [None] * len(times))[i]) for key, name in HOURLY.items()}}
             for i, t in enumerate(times)]
    this_hour = next((h for h in hours if h["time"][:13] == cur["time"][:13]), hours[0] if hours else {})
    return {
        "time": cur["time"],
        "temp_c": float(cur["temperature_2m"]),
        "humidity": float(cur["relative_humidity_2m"]),
        "wind_kmh": float(cur["wind_speed_10m"]),
        "feels_c": num(cur.get("apparent_temperature")),
        "dew_c": num(cur.get("dew_point_2m")),
        "gust_kmh": num(cur.get("wind_gusts_10m")),
        "wind_dir": num(cur.get("wind_direction_10m")),
        "mixing_m": this_hour.get("mixing_m"),
        "hours": hours,
    }


def band(key, value):
    """The band a reading falls in, from config/weather.json, or None."""
    if value is None:
        return None
    for b in DIALS[key]["bands"]:
        if value < b["max"]:
            return b
    return DIALS[key]["bands"][-1]


def compass(degrees):
    """(full name, short name) of the direction the wind blows from."""
    if degrees is None:
        return None, None
    i = int((degrees % 360) / 22.5 + 0.5) % 16
    return TEXT["compass"][i], TEXT["compass_short"][i]


def explain(w):
    """What today's weather does to the air, from the bands each reading falls in."""
    notes = []
    for key in ("wind_kmh", "mixing_m", "humidity", "temp_c"):
        b = band(key, w.get(key))
        if b and b["air"]:
            text = b["air"].format(value=int(round(w[key], -1)) if key == "mixing_m" else w[key])
            if text not in notes:
                notes.append(text)
    stubble = TEXT["stubble"]
    month = int(str(w.get("time", "0000-00"))[5:7] or 0)
    if w.get("wind_dir") is not None and month in stubble["months"] \
            and stubble["from_deg"] <= w["wind_dir"] % 360 <= stubble["to_deg"]:
        notes.append(stubble["text"])
    return " ".join(notes)


def hour_note(h):
    """What one hour's weather does to the air, from its bands, in one line."""
    notes = []
    for key in ("wind_kmh", "mixing_m"):
        b = band(key, h.get(key))
        if b and b["air"]:
            notes.append(b["air"].format(value=int(round(h[key], -1)) if key == "mixing_m" else h[key]))
    return " ".join(notes)


def decorate(w):
    """Bands, direction and the explanation, for the page."""
    w = dict(w)
    w.setdefault("hours", [])
    for key in DIALS:
        w.setdefault(key, None)
    for key in ("feels_c", "dew_c", "gust_kmh", "wind_dir"):
        w.setdefault(key, None)
    w["bands"] = {key: band(key, w[key]) for key in DIALS}
    w["wind_from"], w["wind_from_short"] = compass(w["wind_dir"])
    w["note"] = explain(w)
    return w


def get_weather(area, store, fetcher=None):
    fetcher = fetcher or fetch_weather  # looked up at call time so tests can replace it
    key = f"WX#{area.id}"
    try:
        cached = store.get_text(key)
        if cached:
            return decorate(json.loads(cached))
    except Exception as exc:
        log.warning("weather cache read failed: %s", exc)
    try:
        w = fetcher(area)
    except Exception as exc:
        log.warning("weather for %s failed: %s", area.id, exc)
        return None
    try:
        store.put_text(key, json.dumps(w), ttl_seconds=settings.get("weather_cache_minutes") * 60)
    except Exception as exc:
        log.warning("could not cache weather for %s: %s", area.id, exc)
    return decorate(w)
