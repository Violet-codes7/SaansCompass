"""Delhi areas and the hourly PM2.5 / PM10 forecast for them.

The live source is the Open-Meteo air-quality API (a model forecast, not a
sensor reading). Results are cached (forecast_cache_minutes). If the API
fails, the last real forecast for the area is used and labelled with when it
was fetched (up to last_forecast_hours old). With no real forecast at all,
ForecastUnavailable is raised: the app never makes numbers up.
"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests

from . import aqi as aqi_mod
from . import settings

log = logging.getLogger(__name__)

IST = settings.tz()


class ForecastUnavailable(Exception):
    """No live or recent real forecast for an area."""


@dataclass(frozen=True)
class Area:
    id: str
    name: str
    lat: float
    lon: float


AREAS = {a["id"]: Area(**a) for a in settings.load("areas")["areas"]}


# Places someone typed that are not near one of the AREAS (Gurugram, Lucknow).
# A link names one by a short id; its name and rounded coordinates are kept in
# the store under that id, so no coordinates go in a link or a log.
PLACE_PREFIX = "p-"
_places = {}


def _km(lat1, lon1, lat2, lon2):
    import math
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def make_place(lat, lon, name, store=None):
    """An Area for a typed place anywhere in India, or None when it is
    outside the country's box (place_bounds)."""
    import hashlib

    box = settings.get("place_bounds")
    if not (box["lat"][0] <= lat <= box["lat"][1] and box["lon"][0] <= lon <= box["lon"][1]):
        return None
    digits = settings.get("place_round_digits")
    lat, lon = round(lat, digits), round(lon, digits)
    name = " ".join(str(name).split())[:settings.get("place_name_max_chars")] or "Your place"
    pid = PLACE_PREFIX + hashlib.sha256(f"{lat},{lon},{name}".encode()).hexdigest()[:12]
    area = Area(pid, name, lat, lon)
    _places[pid] = area
    try:
        _place_store(store).put_text("PLACE#" + pid, json.dumps({"name": name, "lat": lat, "lon": lon}),
                                     ttl_seconds=settings.get("place_days") * 86400)
    except Exception as exc:
        log.warning("could not keep place %s: %s", pid, type(exc).__name__)
    return area


def in_grap_region(area):
    """True when GRAP applies to the place: Delhi's areas, and typed places
    within grap_region_km of Delhi (Delhi-NCR). Never when GRAP is switched
    off (grap_enabled)."""
    if not settings.get("grap_enabled"):
        return False
    if area.id in AREAS:
        return True
    centre = settings.get("weather_place")
    return _km(area.lat, area.lon, centre["lat"], centre["lon"]) <= settings.get("grap_region_km")


def is_place(area):
    """A typed place rather than one of Delhi's areas."""
    return str(area.id).startswith(PLACE_PREFIX)


def _place_store(store):
    if store is not None:
        return store
    from .store import get_store  # here to avoid an import cycle
    return get_store()


def get_area(area_id, store=None):
    if area_id in AREAS:
        return AREAS[area_id]
    if str(area_id).startswith(PLACE_PREFIX):
        if area_id in _places:
            return _places[area_id]
        try:
            raw = _place_store(store).get_text("PLACE#" + area_id)
        except Exception:
            raw = None
        if raw:
            p = json.loads(raw)
            _places[area_id] = Area(area_id, p["name"], p["lat"], p["lon"])
            return _places[area_id]
        raise ValueError("That place has expired. Please type it again.")
    raise ValueError(f"area must be one of {', '.join(AREAS)}") from None


def geocode(text, session=None):
    """(lat, lon, name) for a town or locality name from the Open-Meteo
    geocoding API, or None. Used when the AI model cannot read the place."""
    params = {"name": str(text)[:settings.get("place_name_max_chars")], "count": 1,
              "countryCode": settings.get("geocode_country"), "language": "en", "format": "json"}
    try:
        resp = (session or requests).get(settings.get("geocode_url"), params=params,
                                         timeout=settings.get("http_timeout_seconds"))
        resp.raise_for_status()
        hit = (resp.json().get("results") or [None])[0]
    except Exception as exc:  # network, HTTP or JSON error; the typed text is never logged
        log.warning("geocoding failed: %s", type(exc).__name__)
        return None
    if not hit or not all(isinstance(hit.get(k), (int, float)) for k in ("latitude", "longitude")):
        return None
    return float(hit["latitude"]), float(hit["longitude"]), hit.get("name") or str(text)


def now_ist():
    return datetime.now(IST)


def fetch_open_meteo(area, session=None):
    """Return a list of {time, pm25, pm10} for past_days and forecast_days days, in IST."""
    params = {
        "latitude": area.lat,
        "longitude": area.lon,
        "hourly": "pm2_5,pm10",
        "timezone": settings.get("timezone"),
        "forecast_days": settings.get("forecast_days"),
        # Yesterday too, so "now" can be a 24-hour average as CPCB computes it.
        "past_days": settings.get("past_days"),
    }
    get = (session or requests).get
    resp = get(settings.get("open_meteo_url"), params=params, timeout=settings.get("http_timeout_seconds"))
    resp.raise_for_status()
    hourly = resp.json()["hourly"]
    times, pm25, pm10 = hourly["time"], hourly["pm2_5"], hourly["pm10"]
    if not (len(times) == len(pm25) == len(pm10)) or not times:
        raise ValueError("Open-Meteo returned mismatched or empty hourly arrays")
    return [
        {"time": t, "pm25": _clean(a), "pm10": _clean(b)}
        for t, a, b in zip(times, pm25, pm10)
    ]


def _clean(value):
    if value is None:
        return None
    value = float(value)
    return value if value >= 0 else None


def emit_fallback_metric(area_id, name):
    """CloudWatch custom metric via Embedded Metric Format (a structured log line)."""
    print(json.dumps({
        "_aws": {
            "Timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            "CloudWatchMetrics": [{
                "Namespace": "SaansCompass",
                "Dimensions": [[]],
                "Metrics": [{"Name": name, "Unit": "Count"}],
            }],
        },
        name: 1,
        "area": area_id,
    }))


def plausible(rows):
    """Model rows with PM10 held to at most model_pm10_pm25_ratio_max times
    PM2.5. The forecast model can put far too much dust in PM10 (a reading of
    600 at Dwarka next to a much lower PM2.5); stations in Delhi rarely see
    PM10 more than a few times PM2.5, so a higher model PM10 is treated as a
    model error. The model's own figure is kept as pm10_model."""
    ratio = settings.get("model_pm10_pm25_ratio_max")
    out = []
    for r in rows:
        pm25, pm10 = r.get("pm25"), r.get("pm10")
        if ratio and pm25 is not None and pm10 is not None and pm10 > ratio * pm25:
            r = {**r, "pm10": round(ratio * pm25, 1), "pm10_model": pm10}
        out.append(r)
    return out


def get_forecast(area, store, now=None, fetcher=None):
    """Forecast for an area: cache, then Open-Meteo, then the last real
    forecast (marked stale). Raises ForecastUnavailable if there is none."""
    now = now or now_ist()
    fetcher = fetcher or fetch_open_meteo  # looked up at call time so tests can replace it
    date_key = now.astimezone(IST).strftime("%Y-%m-%d")
    epoch = now.timestamp()
    cached = store.get_forecast(area.id, date_key, now=epoch)
    if cached:
        return cached
    try:
        forecast = {"hours": plausible(fetcher(area)), "is_stale": False, "fetched_at": now.isoformat()}
    except Exception as exc:  # network, HTTP, JSON or shape errors
        log.warning("forecast for %s failed: %s", area.id, exc)
        last = store.get_last_forecast(area.id, now=epoch)
        if last:
            emit_fallback_metric(area.id, "StaleForecast")
            return {**last, "is_stale": True}
        emit_fallback_metric(area.id, "ForecastUnavailable")
        raise ForecastUnavailable(
            f"The live forecast for {area.name} cannot be reached right now. Please try again in a few minutes."
        ) from exc
    try:
        store.put_forecast(area.id, date_key, forecast, now=epoch)
        store.put_last_forecast(area.id, forecast, now=epoch)
    except Exception as exc:
        log.warning("could not cache forecast for %s: %s", area.id, exc)
    return forecast


def get_forecasts(areas, store, now=None, fetcher=None):
    """{area id: forecast or None} for several areas, fetched in parallel."""
    def one(area):
        try:
            return area.id, get_forecast(area, store, now=now, fetcher=fetcher)
        except ForecastUnavailable:
            return area.id, None

    areas = list(areas)
    with ThreadPoolExecutor(max_workers=min(8, len(areas))) as pool:
        return dict(pool.map(one, areas))


def readings_for(forecast, date, hours):
    """Hourly readings with AQI for the given hours of `date` (IST).

    `hours` is in order; when it wraps (e.g. 22, 23, 0, 1) the later hours
    fall on the next day. Hours missing from the forecast come back with
    no data rather than being dropped.
    """
    by_time = {h["time"]: h for h in forecast["hours"]}
    out = []
    day = date
    prev = None
    for hour in hours:
        if prev is not None and hour < prev:
            day = day + timedelta(days=1)
        prev = hour
        key = f"{day.isoformat()}T{hour:02d}:00"
        raw = by_time.get(key, {})
        pm25, pm10 = raw.get("pm25"), raw.get("pm10")
        value, dominant = aqi_mod.aqi(pm25, pm10)
        out.append({
            "time": key,
            "hour": hour,
            "pm25": pm25,
            "pm10": pm10,
            "aqi": value,
            "dominant": dominant,
            "category": aqi_mod.category(value),
            "slug": aqi_mod.category_slug(value),
        })
    return out


def day_aqi(forecast, date):
    """AQI from the day's average PM2.5 and PM10, closer to CPCB's 24-hour basis."""
    prefix = date.isoformat()
    pm25 = [h["pm25"] for h in forecast["hours"] if h["time"].startswith(prefix) and h["pm25"] is not None]
    pm10 = [h["pm10"] for h in forecast["hours"] if h["time"].startswith(prefix) and h["pm10"] is not None]
    avg25 = sum(pm25) / len(pm25) if pm25 else None
    avg10 = sum(pm10) / len(pm10) if pm10 else None
    return aqi_mod.aqi(avg25, avg10)[0]


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def particles_now(forecast, now):
    """PM2.5 and PM10 for the current IST hour and averaged over a day.

    The average is over the last 24 hours, the way CPCB computes AQI, when at
    least rolling_min_hours of them are known; otherwise it is the forecast
    average for today. basis says which.
    """
    local = now.astimezone(IST).replace(minute=0, second=0, microsecond=0)
    by_time = {h["time"]: h for h in forecast["hours"]}
    last24 = [by_time.get((local - timedelta(hours=k)).strftime("%Y-%m-%dT%H:00"), {}) for k in range(24)]
    known = [h for h in last24 if h.get("pm25") is not None]
    if len(known) >= settings.get("rolling_min_hours"):
        rows, basis = last24, "last24"
    else:
        prefix = local.date().isoformat()
        rows, basis = [h for h in forecast["hours"] if h["time"].startswith(prefix)], "today"
    hour = by_time.get(local.strftime("%Y-%m-%dT%H:00"), {})
    pm25, pm10 = _mean(h.get("pm25") for h in rows), _mean(h.get("pm10") for h in rows)
    held = any(h.get("pm10_model") is not None for h in rows)
    pm10_model = _mean(h.get("pm10_model", h.get("pm10")) for h in rows) if held else None
    value, dominant = aqi_mod.aqi(pm25, pm10)
    rnd = lambda v: round(v) if v is not None else None  # noqa: E731
    return {"basis": basis, "pm25": rnd(pm25), "pm10": rnd(pm10), "pm10_model": rnd(pm10_model),
            "aqi": value, "dominant": dominant,
            "category": aqi_mod.category(value) if value is not None else None,
            "pm25_hour": rnd(hour.get("pm25")), "pm10_hour": rnd(hour.get("pm10"))}


def city_air(forecasts, date, now):
    """Delhi's AQI the way CPCB reports a city: the average of its sites' AQIs.

    For today each site's AQI is its last-24-hour average (particles_now); for
    another day it is that day's forecast average. GRAP is decided on this
    city-wide figure, not on one neighbourhood. None when fewer than
    city_min_areas sites have a forecast.
    """
    today = now.astimezone(IST).date()
    sites = []
    for area_id, f in forecasts.items():
        if not f:
            continue
        value = particles_now(f, now)["aqi"] if date == today else day_aqi(f, date)
        if value is not None:
            area = AREAS[area_id]
            sites.append({"id": area.id, "name": area.name, "aqi": value,
                          "category": aqi_mod.category(value), "slug": aqi_mod.category_slug(value)})
    if len(sites) < settings.get("city_min_areas"):
        return None
    sites.sort(key=lambda s: s["aqi"])
    value = round(sum(s["aqi"] for s in sites) / len(sites))
    return {"aqi": value, "category": aqi_mod.category(value), "basis": "last24" if date == today else "forecast",
            "count": len(sites), "total": len(forecasts), "low": sites[0], "high": sites[-1], "sites": sites}
