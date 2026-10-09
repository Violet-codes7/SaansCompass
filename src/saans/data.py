"""Delhi areas and the hourly PM2.5 / PM10 forecast for them.

The live source is the Open-Meteo air-quality API (a model forecast, not a
sensor reading). Results are cached for 30 minutes. If the API fails or takes
longer than 3 seconds, clearly labelled demo data is used instead.
"""
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from . import aqi as aqi_mod

log = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30), "IST")  # India has no daylight saving
OPEN_METEO_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
TIMEOUT_SECONDS = 3
FORECAST_DAYS = 3  # today, tomorrow, and the day after for shifts that cross midnight
DEMO_PROFILE = Path(__file__).parent / "data" / "demo_profile.json"


@dataclass(frozen=True)
class Area:
    id: str
    name: str
    lat: float
    lon: float


# Approximate locations of well-known CPCB/DPCC monitoring sites.
AREAS = {
    a.id: a
    for a in (
        Area("anand-vihar", "Anand Vihar", 28.6469, 77.3159),
        Area("ito", "ITO", 28.6286, 77.2410),
        Area("punjabi-bagh", "Punjabi Bagh", 28.6740, 77.1310),
        Area("rk-puram", "R K Puram", 28.5633, 77.1869),
        Area("dwarka", "Dwarka", 28.5921, 77.0460),
        Area("rohini", "Rohini", 28.7325, 77.1199),
        Area("okhla", "Okhla", 28.5308, 77.2713),
        Area("lodhi-road", "Lodhi Road", 28.5918, 77.2273),
        Area("jahangirpuri", "Jahangirpuri", 28.7328, 77.1706),
    )
}


def get_area(area_id):
    try:
        return AREAS[area_id]
    except KeyError:
        raise ValueError(f"area must be one of {', '.join(AREAS)}") from None


def now_ist():
    return datetime.now(IST)


def fetch_open_meteo(area, session=None):
    """Return a list of {time, pm25, pm10} for FORECAST_DAYS days, in IST."""
    params = {
        "latitude": area.lat,
        "longitude": area.lon,
        "hourly": "pm2_5,pm10",
        "timezone": "Asia/Kolkata",
        "forecast_days": FORECAST_DAYS,
    }
    get = (session or requests).get
    resp = get(OPEN_METEO_URL, params=params, timeout=TIMEOUT_SECONDS)
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


def demo_hours(area, now):
    profile = json.loads(DEMO_PROFILE.read_text(encoding="utf-8"))
    mult = profile["area_multiplier"][area.id]
    start = now.astimezone(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    for day in range(FORECAST_DAYS):
        day_mult = mult * (1 + profile["daily_increase"] * day)
        for hour, base in enumerate(profile["pm25_by_hour"]):
            t = start + timedelta(days=day, hours=hour)
            pm25 = round(base * day_mult, 1)
            out.append({
                "time": t.strftime("%Y-%m-%dT%H:%M"),
                "pm25": pm25,
                "pm10": round(pm25 * profile["pm10_ratio"], 1),
            })
    return out


def emit_demo_metric(area_id):
    """CloudWatch custom metric via Embedded Metric Format (a structured log line)."""
    print(json.dumps({
        "_aws": {
            "Timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            "CloudWatchMetrics": [{
                "Namespace": "SaansCompass",
                "Dimensions": [[]],
                "Metrics": [{"Name": "DemoDataFallback", "Unit": "Count"}],
            }],
        },
        "DemoDataFallback": 1,
        "area": area_id,
    }))


def get_forecast(area, store, now=None, fetcher=None):
    """Forecast for an area: cache, then Open-Meteo, then demo data."""
    now = now or now_ist()
    fetcher = fetcher or fetch_open_meteo  # looked up at call time so tests can replace it
    date_key = now.astimezone(IST).strftime("%Y-%m-%d")
    epoch = now.timestamp()
    cached = store.get_forecast(area.id, date_key, now=epoch)
    if cached:
        return cached
    try:
        forecast = {"hours": fetcher(area), "is_demo": False, "fetched_at": now.isoformat()}
    except Exception as exc:  # network, HTTP, JSON or shape errors all fall back
        log.warning("forecast for %s failed, using demo data: %s", area.id, exc)
        emit_demo_metric(area.id)
        # Demo data is not cached, so the next request retries the live source.
        return {"hours": demo_hours(area, now), "is_demo": True, "fetched_at": now.isoformat()}
    try:
        store.put_forecast(area.id, date_key, forecast, now=epoch)
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
