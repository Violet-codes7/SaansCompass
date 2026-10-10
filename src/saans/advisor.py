"""SaansPlan: turn the hourly forecast into a plan for one persona.

Rules come first: an activity the GRAP rules say is not allowed is never
recommended, whatever the air looks like. The thresholds here are our own
heuristics, labelled as such on every page.
"""
import math

from collections import Counter

from . import data, settings
from .aqi import category as aqi_category
from .dose import total_dose
from .explain import CATEGORY_IMPACT, POLLUTANTS, VERDICT_MEANING, rule_text, rules_for_you, stage_headline
from .profile import COMMUTE_TIPS
from .rules import ADVISED_AGAINST, NOT_ALLOWED, CHECK

TEXT = settings.load("advice")


def best_window(readings, minutes, prefer="cleanest"):
    """Contiguous run of hours long enough for `minutes` with the lowest
    (prefer="cleanest") or highest (prefer="worst") average AQI.
    Hours without data are skipped. Ties go to the earliest window."""
    length = max(1, math.ceil(minutes / 60))
    best = None
    for i in range(len(readings) - length + 1):
        chunk = readings[i:i + length]
        if any(r["aqi"] is None for r in chunk):
            continue
        avg = sum(r["aqi"] for r in chunk) / length
        better = best is None or (avg < best["avg_aqi_exact"] if prefer == "cleanest" else avg > best["avg_aqi_exact"])
        if better:
            best = {
                "start": f"{chunk[0]['hour']:02d}:00",
                "end": f"{(chunk[-1]['hour'] + 1) % 24:02d}:00",
                "start_hour": chunk[0]["hour"],
                "avg_aqi_exact": avg,
            }
    if best:
        best["avg_aqi"] = round(best.pop("avg_aqi_exact"))
    return best


def verdict_for(persona, value):
    if value is None:
        return None
    if value <= persona.go_max:
        return "go"
    if value <= persona.limit_max:
        return "limit"
    return "stay_in"


SEVERITY = {"go": 0, "limit": 1, "stay_in": 2}
RULE_ORDER = {NOT_ALLOWED: 0, ADVISED_AGAINST: 1, CHECK: 2}


def rule_floor(persona, rules_by_activity, stage):
    """Least strict verdict the GRAP rules allow for this persona's outdoor
    activities. The AQI verdict can only make the plan stricter than this."""
    floor = None
    for a in persona.activities:
        rule = rules_by_activity.get(a.id)
        if not rule or not a.outdoor:
            continue
        if rule.decision == ADVISED_AGAINST:
            level = "stay_in"
        elif rule.decision == NOT_ALLOWED or (rule.decision == CHECK and (stage or 0) >= 3):
            level = "limit"
        else:
            continue
        if floor is None or SEVERITY[level] > SEVERITY[floor]:
            floor = level
    return floor


def hour_advice(persona, value):
    if value is None:
        return TEXT["no_forecast_hour"]
    v = verdict_for(persona, value)
    return (persona.hour_advice or TEXT["hour_advice_default"])[v]


def _reading_at(readings, hour):
    for r in readings:
        if r["hour"] == hour:
            return r
    return None


def _average_aqi(readings):
    values = [r["aqi"] for r in readings if r["aqi"] is not None]
    return round(sum(values) / len(values)) if values else None


def _dominant(readings):
    counts = Counter(r.get("dominant") for r in readings if r.get("dominant"))
    return counts.most_common(1)[0][0] if counts else None


def _rule_actions(activities):
    """What the GRAP rules rule out today, as actions."""
    out = []
    for decision, key in ((NOT_ALLOWED, "not_allowed"), (ADVISED_AGAINST, "advised_against")):
        for a in activities:
            if a["rule"] and a["rule"]["decision"] == decision:
                out.append(TEXT["actions"][key].format(label=a["label"]))
    return out


def _day_actions(persona, profile, verdict, window, commute, flex):
    """Short, concrete things to do today beyond the rules, most important first."""
    out = []
    if window and window.get("clean") is False:
        out.append(TEXT["actions"]["no_clean_window"].format(start=window["start"], aqi=window["avg_aqi"]))
    elif window and persona.flex_prefers == "cleanest" and verdict != "stay_in":
        out.append(TEXT["actions"]["best_time"].format(activity=flex.label, start=window["start"], end=window["end"],
                                                       aqi=window["avg_aqi"]))
    elif window and persona.flex_prefers == "worst":
        out.append(TEXT["actions"]["break"].format(start=window["start"], end=window["end"]))
    if verdict in ("limit", "stay_in"):
        if profile and profile.mask:
            out.append(TEXT["actions"]["mask_have"])
        else:
            out.append(TEXT["actions"]["mask_advice"])
        out.append(TEXT["actions"]["windows"])
    if profile and profile.commute and COMMUTE_TIPS.get(profile.commute) and commute is not None:
        out.append(COMMUTE_TIPS[profile.commute])
    if profile and profile.sensitive and verdict != "go":
        out.append(TEXT["actions"]["watch_symptoms"])
    return out


def _tag_hours(readings, persona, window):
    """Label each hour with what happens in it: the person's activities, the
    best (or break) window and the worst hour."""
    labels = TEXT["hour_tags"]
    by_hour = {r["hour"]: r for r in readings}
    for r in readings:
        r["tags"] = []
        r["verdict_label"] = TEXT["hour_verdict_labels"].get(r["verdict"], "")
    for a in persona.activities:
        if a.hour is None:
            continue
        for k in range(max(1, math.ceil((a.minutes or 60) / 60))):
            r = by_hour.get((a.hour + k) % 24)
            if r and a.label not in [t["text"] for t in r["tags"]]:
                r["tags"].append({"kind": "activity", "text": a.label})
    if window:
        kind = "best" if persona.flex_prefers == "cleanest" else "break"
        start, end = window["start_hour"], int(window["end"][:2])
        h = start
        while h != end:
            if h in by_hour:
                by_hour[h]["tags"].insert(0, {"kind": kind, "text": labels[kind]})
            h = (h + 1) % 24
    known = [r for r in readings if r["aqi"] is not None]
    if known:
        worst = max(known, key=lambda r: r["aqi"])
        worst["tags"].insert(0, {"kind": "worst", "text": labels["worst"]})


def _notes(forecast, stage_info, profile, rule_results):
    """The "Please read" notes, most important first."""
    n = TEXT["notes"]

    def note(key, **kw):
        return {"key": key, "title": n[key]["title"], "text": n[key]["text"].format(**kw)}

    out = []
    if forecast.get("is_stale"):
        out.append(note("stale", fetched=forecast["fetched_at"][:16].replace("T", " ")))
    if stage_info["source"] != "outside":
        out.append(note({"estimate": "stage_estimate", "declared": "stage_declared"}.get(stage_info["source"],
                                                                                         "stage_official"),
                        stage=stage_info["label"]))
    out.append(note("forecast"))
    if profile and profile.threshold_shift():
        out.append(note("limits_profile", shift=profile.threshold_shift(), reasons=", ".join(profile.reasons())))
    else:
        out.append(note("limits"))
    if any(r.decision == CHECK for r in rule_results):
        out.append(note("uncovered"))
    out.append(note("medical"))
    return out


def build_plan(persona, area, forecast, date, stage_info, rule_results, profile=None):
    readings = data.readings_for(forecast, date, persona.hours())
    for r in readings:
        r["advice"] = hour_advice(persona, r["aqi"])
        r["verdict"] = verdict_for(persona, r["aqi"])

    rules_by_activity = {r.activity_id: r for r in rule_results}
    flex = persona.activity(persona.flex_activity)
    # A break off the road is taken mid-shift, not in the first or last hour.
    pool = readings[1:-1] if persona.flex_prefers == "worst" and len(readings) > 3 else readings
    window = best_window(pool, flex.minutes or 60, persona.flex_prefers)

    # Outdoor-by-choice personas: if even the cleanest window is bad, stay in.
    # Riders are out all shift, so the verdict follows the shift average.
    if persona.flex_prefers == "cleanest":
        verdict = verdict_for(persona, window["avg_aqi"] if window else None)
        # Fixed outdoor parts of the day (a commute) cannot move to the clean
        # hour: if any is above the person's limit, the day is not a normal one.
        fixed = [_reading_at(readings, a.hour) for a in persona.activities
                 if a.outdoor and not a.movable and a.hour is not None]
        if verdict == "go" and any(r and r["aqi"] is not None and r["aqi"] > persona.go_max for r in fixed):
            verdict = "limit"
    else:
        verdict = verdict_for(persona, _average_aqi(readings))

    floor = rule_floor(persona, rules_by_activity, stage_info["stage"])
    verdict_note = None
    if floor and (verdict is None or SEVERITY[floor] > SEVERITY[verdict]):
        verdict = floor
        verdict_note = TEXT["verdict_note"].format(stage=stage_info["label"])
    if floor == "stay_in" and persona.flex_prefers == "cleanest":
        for r in readings:
            r["advice"] = TEXT["rule_floor_hour"]
            r["verdict"] = "stay_in"
    if window and persona.flex_prefers == "cleanest":
        window["clean"] = window["avg_aqi"] <= persona.limit_max
    flex_rule = rules_by_activity.get(flex.id)
    if flex_rule and flex_rule.decision in (NOT_ALLOWED, ADVISED_AGAINST):
        window = None  # never suggest a time for something the rules advise against

    commute = _reading_at(readings, persona.commute_hour) if persona.commute_hour is not None else None

    activities = []
    segments = []
    for a in persona.activities:
        rule = rules_by_activity.get(a.id)
        at = _reading_at(readings, a.hour) if a.hour is not None else None
        at_aqi = at["aqi"] if at else None
        suggestion = None
        if rule and rule.decision == NOT_ALLOWED:
            suggestion = TEXT["suggestions"]["not_allowed"]
        elif rule and rule.decision == ADVISED_AGAINST:
            suggestion = TEXT["suggestions"]["advised_against"]
        elif a.id == flex.id and window and persona.flex_prefers == "cleanest" and verdict == "stay_in":
            suggestion = TEXT["suggestions"]["too_poor"].format(start=window["start"], aqi=window["avg_aqi"])
        elif a.id == flex.id and window and at_aqi is not None and window["start_hour"] != a.hour:
            if persona.flex_prefers == "cleanest" and window["avg_aqi"] < at_aqi:
                suggestion = TEXT["suggestions"]["cleaner_at"].format(start=window["start"], aqi=window["avg_aqi"],
                                                                      hour=f"{a.hour:02d}:00")
            elif persona.flex_prefers == "worst" and window["avg_aqi"] > at_aqi:
                suggestion = TEXT["suggestions"]["take_break_at"].format(start=window["start"], aqi=window["avg_aqi"])
        elif a.outdoor and at_aqi is not None and verdict_for(persona, at_aqi) == "stay_in":
            suggestion = TEXT["suggestions"]["very_poor_movable" if a.movable else "very_poor_fixed"]
        activities.append({
            "id": a.id,
            "label": a.label,
            "time": f"{a.hour:02d}:00" if a.hour is not None else None,
            "minutes": a.minutes,
            "aqi": at_aqi,
            "slug": at["slug"] if at else None,
            "rule": rule.to_dict() if rule else None,
            "explain": rule_text(a.rules_action or a.id, rule.to_dict()) if rule else None,
            "suggestion": suggestion,
            "rank": RULE_ORDER.get(rule.decision, 3) if rule else 4,
        })
        allowed = not (rule and rule.decision == NOT_ALLOWED)
        if a.hour is not None and a.outdoor and allowed and not persona.whole_window_exposure:
            segments.append(((at or {}).get("pm25"), a.effort, a.minutes))

    _tag_hours(readings, persona, window)

    if persona.whole_window_exposure:
        # Every hour of the shift at the persona's effort, except the default
        # break hour, which is counted at the break's effort.
        segments = [
            (r["pm25"], flex.effort if r["hour"] == flex.hour else persona.effort, 60)
            for r in readings
        ]

    notes = _notes(forecast, stage_info, profile, rule_results)
    day_actions = _day_actions(persona, profile, verdict, window, commute, flex)

    window_title = TEXT["window_title"]["cleanest" if persona.flex_prefers == "cleanest" else "worst"].format(
        activity=flex.label)

    day_aqi = stage_info.get("day_aqi")
    day_category = aqi_category(day_aqi) if day_aqi is not None else None
    stage_info = {**stage_info, "headline": stage_headline(stage_info["stage"], day_aqi, day_category,
                                                           stage_info.get("day", "today"),
                                                           outside=area.name if stage_info["source"] == "outside" else None)}
    # The stage follows Delhi's AQI; the air section is about this area.
    area_aqi = stage_info.get("area_aqi", day_aqi)
    area_category = aqi_category(area_aqi) if area_aqi is not None else None
    known = [r for r in readings if r["aqi"] is not None]
    worst = max(known, key=lambda r: r["aqi"]) if known else None
    day_pm25 = [r["pm25"] for r in data.readings_for(forecast, date, list(range(24))) if r.get("pm25") is not None]
    mean_pm25 = sum(day_pm25) / len(day_pm25) if day_pm25 else None
    dominant = _dominant(readings)

    return {
        "persona": {"id": persona.id, "label": persona.label, "question": persona.question},
        "area": {"id": area.id, "name": area.name},
        "date": date.isoformat(),
        "stage": stage_info,
        "is_stale": forecast.get("is_stale", False),
        "fetched_at": forecast["fetched_at"],
        "verdict": verdict,
        "verdict_label": persona.verdict_labels[verdict] if verdict else TEXT["no_data_verdict"],
        "verdict_note": verdict_note,
        "verdict_meaning": VERDICT_MEANING.get(verdict),
        "best_window": window,
        "best_window_title": window_title,
        "commute": {"time": f"{commute['hour']:02d}:00", "aqi": commute["aqi"], "category": commute["category"]}
        if commute else None,
        "rules": [r.to_dict() for r in rule_results],
        "activities": activities,
        "rules_rest": rules_for_you(activities, stage_info["stage"], stage_info.get("day", "today")),
        "hours": readings,
        "dose": total_dose(segments),
        "notes": notes,
        "warnings": [n["text"] for n in notes],
        "dominant": dominant,
        "air": {
            "day_aqi": area_aqi,
            "category": area_category,
            "impact": CATEGORY_IMPACT.get(area_category),
            "pollutant": POLLUTANTS.get(dominant),
            "worst": {"time": f"{worst['hour']:02d}:00", "aqi": worst["aqi"], "category": worst["category"]}
            if worst else None,
            # Berkeley Earth's rule of thumb: a day in 22 µg/m³ of PM2.5 is
            # about one cigarette.
            "pm25_day": round(mean_pm25) if mean_pm25 is not None else None,
            "cigarettes": round(mean_pm25 / settings.get("cigarette_pm25_ugm3"), 1) if mean_pm25 is not None else None,
        },
        "thresholds": {"go_max": persona.go_max, "limit_max": persona.limit_max},
        "profile": profile.summary() if profile else None,
        "health": {
            "reasons": profile.reasons() if profile else [],
            "tips": profile.tips() if profile else [],
            **(profile.health() if profile else {"level": "higher" if persona.sensitive else "usual",
                                                 "shift": 0, "charter": persona.sensitive, "details": []}),
        },
        "actions": _rule_actions(activities) + day_actions,
        "day_actions": day_actions,
    }
