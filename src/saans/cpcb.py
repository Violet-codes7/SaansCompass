"""CPCB's live station AQI, the same figures the CPCB AQI dashboard and the
Sameer app show, from the data.gov.in "Real time Air Quality Index" feed.

Each record is one pollutant at one station; its avg value is already that
pollutant's sub-index. A station's AQI is the highest sub-index, provided at
least cpcb_min_pollutants are reported and one of them is PM2.5 or PM10, as
CPCB requires. The feed's API key is read from SSM and never logged. Any
failure returns None, and the page falls back to the forecast model.
"""
import json
import logging
import math
import os
import time
from datetime import datetime

from . import aqi as aqi_mod
from . import settings

log = logging.getLogger(__name__)

_key_cache = {"at": -1e18, "value": None}
_memo = {"at": -1e18, "value": None}
CACHE_KEY = "CPCB#STATIONS"
LAST_KEY = "CPCB#LAST"


def _api_key(ssm=None, now=None):
    if os.environ.get("DATAGOV_API_KEY"):
        return os.environ["DATAGOV_API_KEY"]
    name = os.environ.get("DATAGOV_KEY_PARAM")
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
        log.warning("data.gov.in key not available: %s", type(exc).__name__)
        value = None
    _key_cache.update(at=now, value=value)
    return value


def enabled():
    return bool(_api_key())


def _number(raw):
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _field(record, names):
    for name in names:
        if record.get(name) not in (None, "", "NA"):
            return record[name]
    return None


def stations_from_records(records):
    """Station AQIs from the feed's records: [{name, lat, lon, aqi, dominant, updated}]."""
    fields = settings.get("cpcb_fields")
    by_station = {}
    for r in records:
        name = _field(r, fields["station"])
        pollutant = str(_field(r, fields["pollutant"]) or "").upper().replace("OZONE", "O3")
        value = _number(_field(r, fields["avg"]))
        if not name or not pollutant or value is None:
            continue
        s = by_station.setdefault(name, {"name": name, "lat": _number(_field(r, fields["lat"])),
                                         "lon": _number(_field(r, fields["lon"])),
                                         "updated": _field(r, fields["updated"]),
                                         "state": r.get(settings.get("cpcb_filter_field")), "subs": {}})
        s["subs"][pollutant] = value
    out = []
    for s in by_station.values():
        subs = s.pop("subs")
        if len(subs) < settings.get("cpcb_min_pollutants") or not ({"PM2.5", "PM10"} & set(subs)):
            continue
        dominant = max(subs, key=subs.get)
        value = round(subs[dominant])
        out.append({**s, "aqi": value, "dominant": dominant, "category": aqi_mod.category(value),
                    "slug": aqi_mod.category_slug(value)})
    return out


def _get(session, params):
    """One request to the feed: a refused or timed-out connection is tried
    again cpcb_retries times after cpcb_retry_seconds. Raises on failure."""
    import requests

    for attempt in range(settings.get("cpcb_retries") + 1):
        try:
            resp = (session or requests).get(settings.get("cpcb_url"), params=params,
                                             timeout=settings.get("cpcb_timeout_seconds"))
            resp.raise_for_status()
            return resp.json().get("records")
        except (requests.ConnectionError, requests.Timeout):
            if attempt == settings.get("cpcb_retries"):
                raise
            time.sleep(settings.get("cpcb_retry_seconds"))


def fetch(session=None):
    """The feed's records for the configured states, or for all of India when
    none are set (cpcb_filter_value), page by page up to cpcb_max_pages; None
    when the key is missing or the feed cannot be read. When the host cannot
    be reached at all, nothing more is tried."""
    import requests

    key = _api_key()
    if not key:
        return None
    states = settings.get("cpcb_filter_value") or [None]
    states = [states] if isinstance(states, str) else states
    limit = settings.get("cpcb_limit")
    records, ok = [], False
    for state in states:
        for page in range(settings.get("cpcb_max_pages")):
            params = {"api-key": key, "format": "json", "limit": limit, "offset": page * limit}
            if state:
                params[f"filters[{settings.get('cpcb_filter_field')}]"] = state
            try:
                got = _get(session, params)
            except (requests.ConnectionError, requests.Timeout) as exc:
                log.warning("cpcb feed failed: %s", type(exc).__name__)
                return records if ok else None
            except Exception as exc:  # HTTP or JSON error; the message may carry the URL, so log the type only
                log.warning("cpcb feed failed: %s", type(exc).__name__)
                break
            if not isinstance(got, list):
                break
            records += got
            ok = True
            if len(got) < limit:
                break
    return records if ok else None


def _parse_time(raw):
    for fmt in settings.get("cpcb_time_formats"):
        try:
            return datetime.strptime(str(raw), fmt)
        except ValueError:
            continue
    return None


def get_stations(store=None, now=None, session=None):
    """Fresh station AQIs, cached in memory and in the store; [] or None when unavailable."""
    now_s = time.time()
    ttl = settings.get("cpcb_cache_seconds")
    if session is None and now_s - _memo["at"] < ttl:
        stations = _memo["value"]
    else:
        stations = None
        cached = store.get_text(CACHE_KEY) if store is not None and session is None else None
        if cached:
            stations = json.loads(cached)
        else:
            records = fetch(session)
            if records is not None:
                stations = stations_from_records(records)
                if store is not None and stations:
                    store.put_text(CACHE_KEY, json.dumps(stations), ttl_seconds=ttl)
                    # The last good reading, for when the feed is down: still
                    # dropped below once it is older than cpcb_stale_hours.
                    store.put_text(LAST_KEY, json.dumps(stations), ttl_seconds=settings.get("cpcb_stale_hours") * 3600)
            elif store is not None and session is None:
                last = store.get_text(LAST_KEY)
                stations = json.loads(last) if last else None
        _memo.update(at=now_s, value=stations)
    if not stations or now is None:
        return stations
    # Drop stations whose last report is too old to call "now".
    local = now.replace(tzinfo=None)
    max_age = settings.get("cpcb_stale_hours") * 3600
    fresh = []
    for s in stations:
        t = _parse_time(s.get("updated"))
        if t is not None and 0 <= (local - t).total_seconds() <= max_age:
            fresh.append({**s, "time": t.strftime("%H:%M")})
    return fresh


def _km(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(a))


def max_km(area, areas_km="cpcb_max_km"):
    """How far a station may be from a place to stand for it: Delhi's areas
    sit on CPCB sites; a typed town is a centre point (place_station_km)."""
    from .data import is_place

    return settings.get("place_station_km") if is_place(area) else settings.get(areas_km)


def nearest(stations, area):
    """The station for an area: the nearest within max_km(area), else one named after it."""
    best = None
    for s in stations or ():
        if s.get("lat") is None or s.get("lon") is None:
            continue
        km = _km(area.lat, area.lon, s["lat"], s["lon"])
        if km <= max_km(area) and (best is None or km < best[0]):
            best = (km, s)
    if best:
        return {**best[1], "km": round(best[0], 1)}
    from .data import is_place

    if is_place(area):  # a town's name can match a station in another town
        return None
    name = area.name.lower().replace(" ", "")
    for s in stations or ():
        if s["name"].lower().replace(" ", "").startswith(name):
            return {**s, "km": None}
    return None


def city_air(stations):
    """Delhi's AQI as CPCB reports a city: the average of its own stations' AQIs."""
    city_state = settings.get("cpcb_city_state")
    stations = sorted((s for s in stations or () if s.get("state") in (None, city_state)), key=lambda s: s["aqi"])
    if len(stations) < settings.get("cpcb_city_min_stations"):
        return None
    value = round(sum(s["aqi"] for s in stations) / len(stations))
    sites = [{"id": s["name"], "name": short_name(s["name"]), "aqi": s["aqi"], "category": s["category"],
              "slug": s["slug"]} for s in stations]
    return {"aqi": value, "category": aqi_mod.category(value), "basis": "cpcb", "count": len(sites),
            "total": len(sites), "low": sites[0], "high": sites[-1], "sites": sites}


def short_name(name):
    """'ITO, Delhi - CPCB' -> 'ITO'."""
    return str(name).split(",")[0].split(" - ")[0].strip()
