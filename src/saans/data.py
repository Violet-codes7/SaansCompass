"""Delhi areas and the hourly PM2.5 / PM10 forecast for them.

The live source is the Open-Meteo air-quality API (a model forecast, not a
sensor reading). Results are cached (forecast_cache_minutes). If the API
fails, the last real forecast for the area is used and labelled with when it
was fetched (up to last_forecast_hours old). With no real forecast at all,
ForecastUnavailable is raised: the app never makes numbers up.
"""
import json
import logging
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


def get_area(area_id):
    try:
        return AREAS[area_id]
    except KeyError:
        raise ValueError(f"area must be one of {', '.join(AREAS)}") from None


def now_ist():
    return datetime.now(IST)


def fetch_open_meteo(area, session=None):
    """Return a list of {time, pm25, pm10} for forecast_days days, in IST."""
    params = {
        "latitude": area.lat,
        "longitude": area.lon,
        "hourly": "pm2_5,pm10",
        "timezone": settings.get("timezone"),
        "forecast_days": settings.get("forecast_days"),
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
        forecast = {"hours": fetcher(area), "is_stale": False, "fetched_at": now.isoformat()}
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
