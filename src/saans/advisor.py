"""SaansPlan: turn the hourly forecast into a plan for one persona.

Rules come first: an activity the GRAP rules say is not allowed is never
recommended, whatever the air looks like. The thresholds here are our own
heuristics, labelled as such on every page.
"""
import math

from collections import Counter

from . import data
from .aqi import category as aqi_category
from .dose import total_dose
from .explain import CATEGORY_IMPACT, POLLUTANTS, rule_text, stage_headline
from .profile import COMMUTE_TIPS
from .rules import ADVISED_AGAINST, NOT_ALLOWED, CHECK


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


VERDICT_MEANING = {
    "go": "The air stays within your safe range for normal outdoor activity.",
    "limit": "Go out if you need to, but keep it short and easy, and mask up.",
    "stay_in": "The air is above your limit for outdoor activity: keep it indoors where you can.",
}

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
        return "No forecast for this hour."
    v = verdict_for(persona, value)
    if persona.id == "rider":
        return {
            "go": "Normal riding.",
            "limit": "Wear a well-fitted N95 if you have one; take breaks off the road.",
            "stay_in": "Worst hours: a good time for your break indoors.",
        }[v]
    return {
        "go": "Fine for outdoor activity.",
        "limit": "Keep outdoor time short and easy.",
        "stay_in": "Keep activity indoors.",
    }[v]


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


def _actions(persona, profile, verdict, window, activities, commute, flex):
    """Short, concrete things to do today, most important first."""
    out = []
    for a in activities:
        if a["rule"] and a["rule"]["decision"] == NOT_ALLOWED:
            out.append(f"Not allowed at this GRAP stage: {a['label']}. Plan around it.")
    for a in activities:
        if a["rule"] and a["rule"]["decision"] == ADVISED_AGAINST:
            out.append(f"Skip or move indoors: {a['label']} (GRAP citizen charter).")
    if window and window.get("clean") is False:
        out.append(f"No clean window today. The least-bad time is {window['start']} (AQI about {window['avg_aqi']}).")
    elif window and persona.flex_prefers == "cleanest" and verdict != "stay_in":
        out.append(f"Best time for {flex.label}: {window['start']}–{window['end']} (AQI about {window['avg_aqi']}).")
    elif window and persona.flex_prefers == "worst":
        out.append(f"Take your break {window['start']}–{window['end']}, when the air is worst, indoors if you can.")
    if verdict in ("limit", "stay_in"):
        if profile and profile.mask:
            out.append("Wear your N95 outdoors; it only works if it fits tightly with no gaps.")
        else:
            out.append("A well-fitted N95 cuts what you breathe in outdoors; cloth and surgical masks do little.")
        out.append("Keep windows shut at the worst hours and air rooms out at the cleanest one.")
    if profile and profile.commute and COMMUTE_TIPS.get(profile.commute) and commute is not None:
        out.append(COMMUTE_TIPS[profile.commute])
    if profile and profile.sensitive and verdict != "go":
        out.append("Watch for cough, wheeze, chest tightness or breathlessness, and go indoors if they start.")
    return out


def build_plan(persona, area, forecast, date, stage_info, rule_results, profile=None):
    readings = data.readings_for(forecast, date, persona.hours())
    for r in readings:
        r["advice"] = hour_advice(persona, r["aqi"])

    rules_by_activity = {r.activity_id: r for r in rule_results}
    flex = persona.activity(persona.flex_activity)
    # A break off the road is taken mid-shift, not in the first or last hour.
    pool = readings[1:-1] if persona.flex_prefers == "worst" and len(readings) > 3 else readings
    window = best_window(pool, flex.minutes or 60, persona.flex_prefers)

    # Outdoor-by-choice personas: if even the cleanest window is bad, stay in.
    # Riders are out all shift, so the verdict follows the shift average.
    if persona.flex_prefers == "cleanest":
        verdict = verdict_for(persona, window["avg_aqi"] if window else None)
    else:
        verdict = verdict_for(persona, _average_aqi(readings))

    floor = rule_floor(persona, rules_by_activity, stage_info["stage"])
    verdict_note = None
    if floor and (verdict is None or SEVERITY[floor] > SEVERITY[verdict]):
        verdict = floor
        verdict_note = f"Set by the GRAP rules at Stage {stage_info['label']}, not by the AQI alone."
    if floor == "stay_in" and persona.flex_prefers == "cleanest":
        for r in readings:
            r["advice"] = "GRAP advises against outdoor activity at this stage."
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
            suggestion = "Restricted at the GRAP stage in force. The rule says what applies instead."
        elif rule and rule.decision == ADVISED_AGAINST:
            suggestion = "GRAP's citizen charter advises against this at this stage. Keep it indoors or skip it."
        elif a.id == flex.id and window and persona.flex_prefers == "cleanest" and verdict == "stay_in":
            suggestion = (f"Even the cleanest time ({window['start']}, AQI about {window['avg_aqi']}) "
                          "is too poor. Keep it indoors.")
        elif a.id == flex.id and window and at_aqi is not None and window["start_hour"] != a.hour:
            if persona.flex_prefers == "cleanest" and window["avg_aqi"] < at_aqi:
                suggestion = f"Cleaner from {window['start']} (AQI about {window['avg_aqi']}) than at {a.hour:02d}:00."
            elif persona.flex_prefers == "worst" and window["avg_aqi"] > at_aqi:
                suggestion = (f"Take it from {window['start']} instead, when the air is worst "
                              f"(AQI about {window['avg_aqi']}), and stay off the road.")
        elif a.outdoor and at_aqi is not None and verdict_for(persona, at_aqi) == "stay_in":
            suggestion = ("Air is very poor at this time. Move it indoors." if a.movable
                          else "Air is very poor at this time. Keep it short and avoid busy roads.")
        activities.append({
            "id": a.id,
            "label": a.label,
            "time": f"{a.hour:02d}:00" if a.hour is not None else None,
            "minutes": a.minutes,
            "aqi": at_aqi,
            "slug": at["slug"] if at else None,
            "rule": rule.to_dict() if rule else None,
            "explain": rule_text(a.id, rule.to_dict()) if rule else None,
            "suggestion": suggestion,
            "rank": RULE_ORDER.get(rule.decision, 3) if rule else 4,
        })
        allowed = not (rule and rule.decision == NOT_ALLOWED)
        if a.hour is not None and a.outdoor and allowed and not persona.whole_window_exposure:
            segments.append(((at or {}).get("pm25"), a.effort, a.minutes))

    if persona.whole_window_exposure:
        # Every hour of the shift at the persona's effort, except the default
        # break hour, which is counted at the break's effort.
        segments = [
            (r["pm25"], flex.effort if r["hour"] == flex.hour else persona.effort, 60)
            for r in readings
        ]

    warnings = [
        "Hourly AQI is an estimate: CPCB defines AQI on 24-hour averages.",
        "The forecast is a model (Open-Meteo), not a ground station reading.",
        "Activity thresholds and breath dose are our own estimates, not an official order. Not medical advice.",
    ]
    if stage_info["source"] == "estimate":
        warnings.insert(0, "The GRAP stage is estimated from AQI. CAQM declares the official stage; set it if you know it.")
    if profile and profile.threshold_shift():
        warnings.append(f"Your Go and Limit thresholds are {profile.threshold_shift()} AQI points lower "
                        f"because of: {', '.join(profile.reasons())}. Our heuristic, not medical advice.")
    if forecast["is_demo"]:
        warnings.insert(0, "Demo data: the live forecast could not be reached.")
    if any(r.decision == CHECK for r in rule_results):
        warnings.append('Some answers say "Check the official order": the GRAP schedule does not cover them.')

    if persona.flex_prefers == "cleanest":
        window_title = f"Cleanest time for: {flex.label}"
    else:
        window_title = f"Best time for: {flex.label} (worst air, get off the road)"

    day_aqi = stage_info.get("day_aqi")
    day_category = aqi_category(day_aqi) if day_aqi is not None else None
    stage_info = {**stage_info, "headline": stage_headline(stage_info["stage"], day_aqi, day_category)}
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
        "is_demo": forecast["is_demo"],
        "fetched_at": forecast["fetched_at"],
        "verdict": verdict,
        "verdict_label": persona.verdict_labels[verdict] if verdict else "Not enough data",
        "verdict_note": verdict_note,
        "verdict_meaning": VERDICT_MEANING.get(verdict),
        "best_window": window,
        "best_window_title": window_title,
        "commute": {"time": f"{commute['hour']:02d}:00", "aqi": commute["aqi"], "category": commute["category"]}
        if commute else None,
        "rules": [r.to_dict() for r in rule_results],
        "activities": activities,
        "hours": readings,
        "dose": total_dose(segments),
        "warnings": warnings,
        "dominant": dominant,
        "air": {
            "day_aqi": day_aqi,
            "category": day_category,
            "impact": CATEGORY_IMPACT.get(day_category),
            "pollutant": POLLUTANTS.get(dominant),
            "worst": {"time": f"{worst['hour']:02d}:00", "aqi": worst["aqi"], "category": worst["category"]}
            if worst else None,
            # Berkeley Earth's rule of thumb: a day in 22 µg/m³ of PM2.5 is
            # about one cigarette.
            "pm25_day": round(mean_pm25) if mean_pm25 is not None else None,
            "cigarettes": round(mean_pm25 / 22, 1) if mean_pm25 is not None else None,
        },
        "thresholds": {"go_max": persona.go_max, "limit_max": persona.limit_max},
        "profile": profile.summary() if profile else None,
        "health": {
            "reasons": profile.reasons() if profile else [],
            "tips": profile.tips() if profile else [],
            **(profile.health() if profile else {"level": "higher" if persona.sensitive else "usual",
                                                 "shift": 0, "charter": persona.sensitive, "details": []}),
        },
        "actions": _actions(persona, profile, verdict, window, activities, commute, flex),
    }
