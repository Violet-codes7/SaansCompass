"""The full pipeline shared by the web pages and the alert run:
forecast -> AQI -> stage -> Cedar rules -> plan and dose."""
from datetime import timedelta

from . import aqi as aqi_mod
from . import data
from .advisor import build_plan
from .personas import get_persona
from .profile import Profile
from .rules import default_rulebook
from .stage import declared_stage, parse_stage, resolve_stage
from .store import get_store

DAYS = ("today", "tomorrow")


# After this hour (IST) the plan opens on tomorrow by default.
TOMORROW_FROM_HOUR = 20


def auto_day(now):
    return "tomorrow" if now.astimezone(data.IST).hour >= TOMORROW_FROM_HOUR else "today"


def parse_day(raw, now=None):
    """today, tomorrow, or empty/auto to pick from the current IST time."""
    day = (raw or "auto").strip().lower()
    if day == "auto":
        return auto_day(now or data.now_ist())
    if day not in DAYS:
        raise ValueError("day must be today or tomorrow")
    return day


def air_now(forecast, now):
    """The forecast AQI for the current IST hour (an hourly estimate)."""
    local = now.astimezone(data.IST)
    r = data.readings_for(forecast, local.date(), [local.hour])[0]
    return {"aqi": r["aqi"], "category": aqi_mod.category(r["aqi"]), "dominant": r["dominant"],
            "time": local.strftime("%Y-%m-%d %H:00")}


def get_plan(persona_id, area_id, stage=None, day="today", now=None, store=None, rulebook=None, fetcher=None,
             profile: Profile | None = None):
    """Raises ValueError with a user-facing message for bad input.
    `profile` personalises hours, thresholds and the sensitive-group rules;
    it is used for this request only and never stored."""
    persona = get_persona(persona_id)
    if profile is not None:
        persona = profile.apply(persona)
    area = data.get_area(area_id)
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
    stage_info = resolve_stage(data.day_aqi(forecast, date), official, declared)
    sensitive = persona.sensitive or bool(profile and profile.sensitive)
    rule_results = rulebook.evaluate_persona(persona, area.id, stage_info["stage"], sensitive)
    plan = build_plan(persona, area, forecast, date, stage_info, rule_results, profile)
    plan["day"] = day
    plan["air_now"] = air_now(forecast, now)
    tomorrow_aqi = data.day_aqi(forecast, now.astimezone(data.IST).date() + timedelta(days=1))
    plan["air_tomorrow"] = {"aqi": tomorrow_aqi, "category": aqi_mod.category(tomorrow_aqi)}
    plan["dates"] = {
        "today": now.astimezone(data.IST).date().isoformat(),
        "tomorrow": (now.astimezone(data.IST).date() + timedelta(days=1)).isoformat(),
    }
    return plan
