"""The pollution map: live station AQIs around a box, and the base-map style.

Stations come from aqicn.org's map endpoint (the CPCB stations it
republishes), else from CPCB's own feed, else each Delhi area's forecast.
aqicn gives one US-scale AQI per station, which is read as PM2.5 (the usual
leading pollutant here) and turned into India's AQI.

The base map is Amazon Location Service when its API key exists (the key
is read once with DescribeKey and cached), else open raster tiles.
"""
import json
import logging
import os
import time
from datetime import datetime

from . import aqi as aqi_mod
from . import cpcb, data, settings, waqi

log = logging.getLogger(__name__)

MAP = settings.load("map")
_key_cache = {"at": -1e18, "value": None}
_memo = {}


def enabled():
    return settings.get("air_map")


def default_box():
    """(south, west, north, east) around the map centre."""
    c, pad = MAP["center"], MAP["bounds_pad"]
    return (round(c["lat"] - pad["lat"], 3), round(c["lon"] - pad["lon"], 3),
            round(c["lat"] + pad["lat"], 3), round(c["lon"] + pad["lon"], 3))


def _station(name, lat, lon, value, updated, source):
    return {"name": cpcb.short_name(name), "lat": round(lat, 4), "lon": round(lon, 4), "aqi": value,
            "category": aqi_mod.category(value), "slug": aqi_mod.category_slug(value), "time": updated,
            "source": source}


def stations_from_bounds(body, now):
    """Fresh stations on India's scale from an aqicn map/bounds answer."""
    if not isinstance(body, dict) or body.get("status") != "ok" or not isinstance(body.get("data"), list):
        return []
    max_age = MAP["station_stale_hours"] * 3600
    out = []
    for s in body["data"]:
        try:
            us = float(s.get("aqi"))
            lat, lon = float(s["lat"]), float(s["lon"])
            t = datetime.fromisoformat(str((s.get("station") or {}).get("time")))
        except (TypeError, ValueError, KeyError):
            continue  # "-" for a station with no reading, or no time
        if t.tzinfo is None:
            t = t.replace(tzinfo=data.IST)
        if not 0 <= (now - t).total_seconds() <= max_age:
            continue
        value, _ = aqi_mod.aqi(waqi.us_to_concentration(us, "pm25"), None)
        if value is None:
            continue
        out.append(_station((s.get("station") or {}).get("name") or "", lat, lon, value,
                            t.astimezone(data.IST).strftime("%H:%M"), "aqicn"))
    return out


def _from_waqi(box, now, session=None):
    token = waqi._token()
    if not token:
        return None
    import requests

    try:
        resp = (session or requests).get(settings.get("waqi_bounds_url"),
                                         params={"token": token, "latlng": ",".join(str(v) for v in box)},
                                         timeout=settings.get("cpcb_timeout_seconds"))
        resp.raise_for_status()
        return stations_from_bounds(resp.json(), now)
    except Exception as exc:  # the URL carries the token, so log the type only
        log.warning("aqicn map failed: %s", type(exc).__name__)
        return None


def _inside(box, lat, lon):
    return box[0] <= lat <= box[2] and box[1] <= lon <= box[3]


def _from_cpcb(box, store, now):
    try:
        stations = cpcb.get_stations(store, now) or []
    except Exception as exc:
        log.warning("cpcb map failed: %s", type(exc).__name__)
        return None
    return [_station(s["name"], s["lat"], s["lon"], s["aqi"], s.get("time"), "cpcb") for s in stations
            if s.get("lat") is not None and s.get("lon") is not None and _inside(box, s["lat"], s["lon"])]


def _from_forecast(box, store, now, fetcher=None):
    areas = [a for a in data.AREAS.values() if _inside(box, a.lat, a.lon)]
    if not areas:
        return []
    out = []
    for area_id, f in data.get_forecasts(areas, store, now=now, fetcher=fetcher).items():
        if not f:
            continue
        p = data.particles_now(f, now)
        if p and p.get("aqi") is not None:
            a = data.AREAS[area_id]
            out.append(_station(a.name, a.lat, a.lon, p["aqi"], None, "forecast"))
    return out


def stations(store, now, box=None, session=None, fetcher=None):
    """{"stations", "source", "box"}: the live AQI at stations inside a box
    (default: around the map centre), cached for cpcb_cache_seconds."""
    box = tuple(box or default_box())
    local = now.astimezone(data.IST)
    key = "MAP#" + ",".join(f"{v:.2f}" for v in box)
    ttl = settings.get("cpcb_cache_seconds")
    hit = _memo.get(key)
    if session is None and hit and time.time() - hit[0] < ttl:
        return hit[1]
    if session is None and store is not None:
        cached = store.get_text(key)
        if cached:
            out = json.loads(cached)
            _memo[key] = (time.time(), out)
            return out
    found, source = None, None
    for source, fetch in (("aqicn", lambda: _from_waqi(box, local, session)),
                          ("cpcb", lambda: _from_cpcb(box, store, local)),
                          ("forecast", lambda: _from_forecast(box, store, local, fetcher))):
        try:
            found = fetch()
        except data.ForecastUnavailable:
            found = None
        if found:
            break
    out = {"stations": found or [], "source": source if found else None, "box": list(box)}
    if found and session is None:
        _memo[key] = (time.time(), out)
        if store is not None:
            store.put_text(key, json.dumps(out), ttl_seconds=ttl)
    return out


def _location_key(client=None, now=None):
    """The Amazon Location API key's value, or None (not set up, or no permission)."""
    name = os.environ.get("MAP_KEY_NAME")
    if not name:
        return None
    now = now if now is not None else time.time()
    if client is None and now - _key_cache["at"] < settings.get("ai_key_cache_seconds"):
        return _key_cache["value"]
    try:
        if client is None:
            import boto3

            client = boto3.client("location", region_name=settings.get("location_region") or None)
        value = client.describe_key(KeyName=name)["Key"] or None
    except Exception as exc:
        log.warning("map key not available: %s", type(exc).__name__)
        value = None
    _key_cache.update(at=now, value=value)
    return value


def style(scheme="light", client=None):
    """What MapLibre needs for the base map: a style URL (Amazon Location) or
    an inline raster style (open tiles)."""
    key = _location_key(client)
    if key:
        from urllib.parse import quote

        region = settings.get("location_region") or os.environ.get("AWS_REGION", "")
        return {"url": MAP["location_style_url"].format(region=region, style=MAP["location_style"],
                                                        key=quote(key, safe=""),
                                                        scheme=MAP["location_schemes"].get(scheme, "Light")),
                "provider": "amazon-location"}
    return {"style": {"version": 8, "sources": {"base": {"type": "raster", "tiles": MAP["fallback_tiles"],
                                                          "tileSize": 256,
                                                          "attribution": MAP["fallback_attribution"]}},
                      "layers": [{"id": "base", "type": "raster", "source": "base"}]},
            "provider": "tiles"}
