"""The full pipeline shared by the web pages and the alert run:
forecast -> AQI -> stage -> Cedar rules -> plan and dose."""
from datetime import timedelta

from . import aqi as aqi_mod
from . import cpcb, data, guide, route, settings
from .advisor import TEXT as ADVICE
from .advisor import build_plan
from .personas import get_persona
from .profile import Profile
from .rules import default_rulebook
from .stage import declared_stage, parse_stage, resolve_stage
from .store import get_store

DAYS = ("today", "tomorrow")


def auto_day(now):
    """Today, or tomorrow from tomorrow_from_hour (IST) onwards."""
    return "tomorrow" if now.astimezone(data.IST).hour >= settings.get("tomorrow_from_hour") else "today"


def parse_day(raw, now=None):
    """today, tomorrow, or empty/auto to pick from the current IST time."""
    day = (raw or "auto").strip().lower()
    if day == "auto":
        return auto_day(now or data.now_ist())
    if day not in DAYS:
        raise ValueError("day must be today or tomorrow")
    return day


def official_air(area, store, now):
    """CPCB's live station reading for an area, and Delhi's CPCB average, or Nones."""
    try:
        stations = cpcb.get_stations(store, now.astimezone(data.IST))
        station = cpcb.nearest(stations, area)
        return ({**station, "short": cpcb.short_name(station["name"])} if station else None), cpcb.city_air(stations)
    except Exception as exc:  # never let the official feed break a page
        cpcb.log.warning("cpcb reading failed: %s", type(exc).__name__)
        return None, None


def air_now(forecast, now, official=None):
    """The forecast AQI for the current IST hour (an hourly estimate). The
    "now" AQI is CPCB's station figure when there is one, else the model's
    24-hour average."""
    local = now.astimezone(data.IST)
    r = data.readings_for(forecast, local.date(), [local.hour])[0]
    particles = data.particles_now(forecast, now)
    if official:
        particles = {**particles, "aqi": official["aqi"], "category": official["category"], "basis": "cpcb",
                     "dominant": official["dominant"], "station": official["short"], "updated": official["time"]}
    return {"aqi": r["aqi"], "category": aqi_mod.category(r["aqi"]), "dominant": r["dominant"],
            "time": local.strftime("%Y-%m-%d %H:00"), "particles": particles}


def get_plan(persona_id, area_id, stage=None, day="today", now=None, store=None, rulebook=None, fetcher=None,
             profile: Profile | None = None, to_area_id=None, modes=()):
    """Raises ValueError with a user-facing message for bad input.
    `profile` personalises hours, thresholds and the sensitive-group rules.
    `area_id` is where the person starts; with `to_area_id` (where they spend
    the day) the hour-by-hour plan uses the destination's air and the trips
    between the two are checked too."""
    persona = get_persona(persona_id)
    # The profile fits hours, limits, vehicle rules and travel; without one,
    # how the person travels (from the link) still fits the commute rules.
    persona = (profile or Profile(work=persona.id)).apply(persona, modes)
    start = data.get_area(area_id)
    dest = data.get_area(to_area_id) if to_area_id else None
    area = dest or start
    official = parse_stage(stage)
    now = now or data.now_ist()
    day = parse_day(day, now)

    store = store or get_store()
    rulebook = rulebook or default_rulebook()
    kwargs = {"fetcher": fetcher} if fetcher else {}
    forecast = data.get_forecast(area, store, now=now, **kwargs)

    date = now.astimezone(data.IST).date() + timedelta(days=1 if day == "tomorrow" else 0)
    # CAQM's declaration applies to the day it is made; tomorrow stays an estimate.
    declared = declared_stage() if day == "today" and official is None else None
    # GRAP is decided for all of Delhi-NCR on Delhi's city-wide AQI, so the
    # estimate uses every area, not just this one.
    forecasts = data.get_forecasts(data.AREAS.values(), store, now=now, fetcher=fetcher)
    forecasts[area.id] = forecast
    station, station_city = official_air(area, store, now)
    city = (station_city if day == "today" else None) or data.city_air(forecasts, date, now)
    next_day = data.city_air(forecasts, date + timedelta(days=1), now) if day == "today" else None
    stage_info = resolve_stage(city["aqi"] if city else data.day_aqi(forecast, date), official, declared,
                               city=city, outlook=next_day["aqi"] if next_day else None)
    # One AQI for the area everywhere on the page: the same figure as the air
    # dials (last 24 hours today, the day's forecast average tomorrow).
    if day == "today":
        area_aqi = station["aqi"] if station else data.particles_now(forecast, now)["aqi"]
    else:
        area_aqi = data.day_aqi(forecast, date)
    stage_info.update(area_aqi=area_aqi, day=day)
    sensitive = persona.sensitive or bool(profile and profile.sensitive)
    rule_results = rulebook.evaluate_persona(persona, area.id, stage_info["stage"], sensitive)
    plan = build_plan(persona, area, forecast, date, stage_info, rule_results, profile)
    plan["day"] = day
    plan["route"] = (route.trips(persona, start, dest, date, store, now, fetcher, modes=modes)
                     if dest and not (profile and profile.commute == "none") else None)
    trip_actions = [
        ADVICE["actions"]["trip_bad"].format(trip=leg["label"], time=leg["time"], area=leg["worst"]["name"],
                                             aqi=leg["worst"]["aqi"])
        for leg in (plan["route"] or {}).get("legs", [])
        if leg["worst"] and leg["worst"]["aqi"] > persona.limit_max
    ]
    if trip_actions:  # a bad trip matters more than the general tips
        plan["day_actions"] = trip_actions + plan["day_actions"]
        plan["actions"] = [a for a in plan["actions"] if a not in plan["day_actions"]] + plan["day_actions"]
    plan["official"] = station
    plan["air_now"] = air_now(forecast, now, station)
    pt = plan["air_now"]["particles"]
    if day == "today" and pt["pm25"] is not None:
        # The same 24-hour PM2.5 as the dashboard chips.
        plan["air"].update(pm25_day=pt["pm25"], cigarettes=round(pt["pm25"] / settings.get("cigarette_pm25_ugm3"), 1))
    tomorrow_aqi = data.day_aqi(forecast, now.astimezone(data.IST).date() + timedelta(days=1))
    plan["air_tomorrow"] = {"aqi": tomorrow_aqi, "category": aqi_mod.category(tomorrow_aqi)}
    plan["glance"] = guide.build(plan, persona, profile, modes)
    plan["dates"] = {
        "today": now.astimezone(data.IST).date().isoformat(),
        "tomorrow": (now.astimezone(data.IST).date() + timedelta(days=1)).isoformat(),
    }
    return plan
