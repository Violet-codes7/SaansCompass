"""The full pipeline shared by the web pages and the alert run:
forecast -> AQI -> stage -> Cedar rules -> plan and dose."""
from datetime import timedelta

from . import data
from .advisor import build_plan
from .personas import get_persona
from .rules import default_rulebook
from .stage import declared_stage, parse_stage, resolve_stage
from .store import get_store

DAYS = ("today", "tomorrow")


def parse_day(raw):
    day = (raw or "today").strip().lower()
    if day not in DAYS:
        raise ValueError("day must be today or tomorrow")
    return day


def get_plan(persona_id, area_id, stage=None, day="today", now=None, store=None, rulebook=None, fetcher=None):
    """Raises ValueError with a user-facing message for bad input."""
    persona = get_persona(persona_id)
    area = data.get_area(area_id)
    official = parse_stage(stage)
    day = parse_day(day)

    now = now or data.now_ist()
    store = store or get_store()
    rulebook = rulebook or default_rulebook()
    kwargs = {"fetcher": fetcher} if fetcher else {}
    forecast = data.get_forecast(area, store, now=now, **kwargs)

    date = now.astimezone(data.IST).date() + timedelta(days=1 if day == "tomorrow" else 0)
    # CAQM's declaration applies to the day it is made; tomorrow stays an estimate.
    declared = declared_stage() if day == "today" and official is None else None
    stage_info = resolve_stage(data.day_aqi(forecast, date), official, declared)
    rule_results = rulebook.evaluate_persona(persona, area.id, stage_info["stage"])
    plan = build_plan(persona, area, forecast, date, stage_info, rule_results)
    plan["day"] = day
    return plan
