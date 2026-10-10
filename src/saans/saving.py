"""How much PM2.5 following the plan saves, and the signed-in person's
weekly diary of it.

Following the plan means the flexible activity at the plan's best time,
anything the plan moves indoors done indoors (at indoor_pm25_ratio of the
outdoor air), and, for people out on a whole shift, the break off the road at
the worst hours. It is compared with the same minutes outdoors at the worst
hours (and at the person's usual times). Like the breath dose, it is an
estimate for comparison, not a measurement; masks are left out.
"""
import math

from . import settings
from .advisor import best_window
from .dose import segment_ug
from .personas import VENTILATION_M3_PER_HOUR

INDOORS = {"advised_against", "too_poor", "very_poor_movable"}  # suggestions that move an activity indoors


def _run(by_hour, start, minutes):
    """Average PM2.5 over the hours a `minutes`-long run starting at `start` covers, or None."""
    values = [by_hour.get((start + k) % 24, {}).get("pm25") for k in range(max(1, math.ceil(minutes / 60)))]
    return None if not values or any(v is None for v in values) else sum(values) / len(values)


def _hours_of(window):
    if not window:
        return set()
    out, h, end = set(), window["start_hour"], int(window["end"][:2])
    while h != end:
        out.add(h)
        h = (h + 1) % 24
    return out


def dose_saved(plan, persona):
    """{"follow_ug", "worst_ug", "usual_ug", "minutes", "vs_worst_pct", "vs_usual_pct", "show"}, or None when
    the feature is off or there is nothing outdoors to compare."""
    if not settings.get("dose_saved_enabled"):
        return None
    readings = plan["hours"]
    by_hour = {r["hour"]: r for r in readings}
    indoor = settings.get("indoor_pm25_ratio")
    follow = worst = usual = 0.0
    minutes = 0
    if persona.whole_window_exposure:
        flex = persona.activity(persona.flex_activity)
        breaks = _hours_of(plan["best_window"])  # the break, at the worst hours
        for r in readings:
            if r["pm25"] is None:
                continue
            in_break = r["hour"] in breaks
            out = segment_ug(r["pm25"], flex.effort if in_break else persona.effort, 60)
            follow += out * (indoor if in_break else 1)
            worst += out
            usual += out
            minutes += 60
    else:
        acts = {a.id: a for a in persona.activities}
        window = plan["best_window"] if persona.flex_prefers == "cleanest" else None
        for a in plan["activities"]:
            act = acts.get(a["id"])
            if not act or not act.outdoor or act.hour is None or not act.minutes or a["suggestion_key"] == "not_allowed":
                continue
            at_usual = _run(by_hour, act.hour, act.minutes)
            if at_usual is None:
                continue
            at_plan = at_worst = at_usual
            if act.id == persona.flex_activity and window and a["suggestion_key"] != "too_poor":
                at_plan = _run(by_hour, window["start_hour"], act.minutes) or at_usual
                bad = best_window(readings, act.minutes, "worst")
                at_worst = _run(by_hour, bad["start_hour"], act.minutes) if bad else at_usual
            factor = indoor if a["suggestion_key"] in INDOORS else 1
            follow += segment_ug(at_plan, act.effort, act.minutes) * factor
            worst += segment_ug(max(at_worst, at_usual), act.effort, act.minutes)
            usual += segment_ug(at_usual, act.effort, act.minutes)
            minutes += act.minutes
    if not worst:
        return None

    def pct(base):
        return max(0, round(100 * (1 - follow / base))) if base else 0
    return {"follow_ug": round(follow, 1), "worst_ug": round(worst, 1), "usual_ug": round(usual, 1),
            "minutes": minutes, "vs_worst_pct": pct(worst), "vs_usual_pct": pct(usual),
            "show": pct(worst) >= settings.get("dose_saved_min_pct")}  # too small to be worth a headline


# The weekly diary: one entry per day, kept under the account only.

def cigarettes(ug):
    """Berkeley Earth's rule of thumb (a day in 22 µg/m³ of PM2.5 is about one
    cigarette), as inhaled µg: a day at rest in that air."""
    per_cigarette = settings.get("cigarette_pm25_ugm3") * VENTILATION_M3_PER_HOUR["rest"] * 24
    return round(ug / per_cigarette, 1)


def diary_entry(plan, followed):
    saved = plan.get("dose_saved") or {}
    return {"followed": followed, "aqi": plan["air"]["day_aqi"], "area": plan["area"]["name"],
            "follow_ug": saved.get("follow_ug"), "worst_ug": saved.get("worst_ug"), "minutes": saved.get("minutes")}


def add_to_diary(diary, date, entry):
    """The diary with this day's entry, keeping the last diary_days days."""
    diary = {**(diary or {}), date: entry}
    return dict(sorted(diary.items())[-settings.get("diary_days"):])


def week(diary, today):
    """The last seven days, oldest first, and what following the plan saved over them."""
    from datetime import date, timedelta

    end = date.fromisoformat(today)
    share = settings.get("diary_followed_share")
    days, saved_ug, worst_ug, followed = [], 0.0, 0.0, 0
    for k in range(6, -1, -1):
        d = (end - timedelta(days=k)).isoformat()
        e = (diary or {}).get(d)
        days.append({"date": d, "day": (end - timedelta(days=k)).strftime("%a"), "entry": e})
        if e and e.get("worst_ug") and e.get("follow_ug") is not None:
            part = share.get(e["followed"], 0)
            saved_ug += part * (e["worst_ug"] - e["follow_ug"])
            worst_ug += e["worst_ug"]
            followed += 1 if part else 0
    peak = max([d["entry"]["worst_ug"] for d in days if d["entry"] and d["entry"].get("worst_ug")] or [0])
    for d in days:  # bars: what was breathed (by how much of the plan was followed) against the worst hours
        e = d["entry"]
        ok = e and peak and e.get("worst_ug") and e.get("follow_ug") is not None
        breathed = e["worst_ug"] - share.get(e["followed"], 0) * (e["worst_ug"] - e["follow_ug"]) if ok else 0
        d["bar_pct"] = round(100 * breathed / peak) if ok else 0
        d["worst_pct"] = round(100 * e["worst_ug"] / peak) if ok else 0
    return {"days": days, "followed": followed, "logged": sum(1 for d in days if d["entry"]),
            "saved_pct": round(100 * saved_ug / worst_ug) if worst_ug else 0,
            "cigarettes": cigarettes(saved_ug)}
