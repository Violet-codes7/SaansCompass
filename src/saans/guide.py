"""The plan page's "At a glance" (what to do, grouped and personal) and the
extra detail in "Your health". Built from the finished plan; all wording is
in config/glance.json."""
from . import aqi as aqi_mod
from . import settings
from .advisor import TEXT as ADVICE
from .advisor import verdict_for
from .profile import COMMUTE_ACTIVITIES, COMMUTE_TIPS

TEXT = settings.load("glance")
WHO_PM25_24H = next(p for p in settings.load("particles")["particles"] if p["key"] == "pm25")["limits"]["who_24h"]
SCALE_MAX = 500


def _slug(value):
    return aqi_mod.category_slug(value) if value is not None else "no-data"


def _ranges(hours):
    """[7, 8, 9, 17, 18] -> "07:00–10:00, 17:00–19:00"."""
    out, start, prev = [], None, None
    for h in sorted(hours) + [None]:
        if start is None:
            start = prev = h
        elif h is not None and h == prev + 1:
            prev = h
        else:
            out.append(f"{start:02d}:00–{(prev + 1) % 24:02d}:00")
            start = prev = h
    return ", ".join(out)


def _basis(plan):
    """How the area's AQI was measured, in a few words."""
    if plan["day"] == "today" and plan.get("official"):
        return TEXT["area_basis_cpcb"].format(station=plan["official"]["short"], time=plan["official"]["time"])
    return TEXT["area_basis_today" if plan["day"] == "today" else "area_basis_tomorrow"]


def _area(plan):
    air, stage = plan["air"], plan["stage"]
    value = air["day_aqi"]
    out = {"name": plan["area"]["name"], "aqi": value, "category": air["category"], "slug": _slug(value),
           "impact": air["impact"], "pollutant": air["pollutant"],
           "basis": _basis(plan),
           "note": TEXT["area_notes"].get(plan["area"]["id"]), "vs_delhi": None, "rank": None}
    city = stage.get("city")
    if city and value is not None:
        diff = value - city["aqi"]
        key = "vs_delhi_same" if abs(diff) <= 5 else "vs_delhi_above" if diff > 0 else "vs_delhi_below"
        out["vs_delhi"] = TEXT[key].format(diff=abs(diff), delhi=city["aqi"])
        ids = [s["id"] for s in city["sites"]]
        if plan["area"]["id"] in ids:
            # Ranked by the same figure the card shows (a station's reading
            # can differ from the model's), so the rank and "cleaner than" agree.
            rank = 1 + sum(s["aqi"] < value for s in city["sites"] if s["id"] != plan["area"]["id"])
            out["rank"] = TEXT["rank"].format(rank=rank, count=len(ids))
    return out


def _moments(plan, persona):
    limit = plan["thresholds"]["go_max"]
    out = []

    def add(key, label, time, value, sub=None):
        out.append({"key": key, "label": label, "time": time, "aqi": value, "slug": _slug(value), "sub": sub,
                    "over": value is not None and value > limit})

    w = plan["best_window"]
    if w:
        label = (TEXT["break"] if persona.flex_prefers == "worst"
                 else TEXT["least_bad"] if w.get("clean") is False else TEXT["best"])
        add("best", label, f"{w['start']}–{w['end']}", w["avg_aqi"], plan["best_window_title"])
    if plan["air"]["worst"]:
        add("worst", TEXT["worst"], plan["air"]["worst"]["time"], plan["air"]["worst"]["aqi"])
    if plan["commute"]:
        add("set_out", TEXT["set_out"], plan["commute"]["time"], plan["commute"]["aqi"])
    tomorrow = plan.get("air_tomorrow") or {}
    if plan["day"] == "today" and tomorrow.get("aqi") is not None and plan["air"]["day_aqi"] is not None:
        diff = tomorrow["aqi"] - plan["air"]["day_aqi"]
        sub = TEXT["tomorrow_better" if diff <= -20 else "tomorrow_worse" if diff >= 20 else "tomorrow_same"]
        add("tomorrow", TEXT["tomorrow"], None, tomorrow["aqi"], sub)
    return out


def _outdoor_at(a, persona):
    """An outdoor part of the day (not the trip) with a time and an AQI, that the rules allow."""
    act = next((x for x in persona.activities if x.id == a["id"]), None)
    return (act is not None and act.outdoor and a["id"] not in COMMUTE_ACTIVITIES and a["time"]
            and a["aqi"] is not None and not (a["rule"] and a["rule"]["decision"] == "not_allowed"))


def _todo(plan, persona, profile, modes):
    t, day = TEXT["todo"], plan["day"]
    limit, go = plan["thresholds"]["limit_max"], plan["thresholds"]["go_max"]
    verdict = plan["verdict"]
    groups = {k: [] for k in TEXT["groups"]}

    # GRAP rules
    for decision, key in (("not_allowed", "not_allowed"), ("advised_against", "advised_against")):
        for a in plan["activities"]:
            if a["rule"] and a["rule"]["decision"] == decision:
                groups["rules"].append(ADVICE["actions"][key].format(label=a["label"]))
    if not groups["rules"] and plan["stage"]["source"] != "outside":
        groups["rules"].append(t["no_rules"].format(day=day, stage=plan["stage"]["headline"]["title"]))

    # Timing: each outdoor part of the day at its own hour, then the best window
    timed = [a for a in plan["activities"] if _outdoor_at(a, persona)][:settings.get("glance_activity_lines")]
    for a in timed:
        advice = persona.hour_advice.get(verdict_for(persona, a["aqi"])) or ""
        groups["timing"].append(" ".join(filter(None, [t["activity_at"].format(
            activity=a["label"], time=a["time"], aqi=a["aqi"], advice=advice), a["suggestion"]])))
    w = plan["best_window"]
    flex = persona.activity(persona.flex_activity)
    if w and w.get("clean") is False:
        groups["timing"].append(ADVICE["actions"]["no_clean_window"].format(start=w["start"], aqi=w["avg_aqi"]))
    elif any(a["id"] == flex.id and a["suggestion"] for a in timed):
        pass  # its own line above already says when it is cleaner
    elif w and persona.flex_prefers == "cleanest":
        groups["timing"].append(ADVICE["actions"]["best_time"].format(activity=flex.label, start=w["start"],
                                                                      end=w["end"], aqi=w["avg_aqi"]))
    elif w:
        groups["timing"].append(ADVICE["actions"]["break"].format(start=w["start"], end=w["end"]))
    known = [r for r in plan["hours"] if r["aqi"] is not None]
    over = [r["hour"] for r in known if r["aqi"] > go]
    if known:
        groups["timing"].append(t["hours_over"].format(over=len(over), total=len(known), limit=go,
                                                       times=_ranges(over)) if over
                                else t["hours_over_none"].format(total=len(known), limit=go))
    worst = plan["air"]["worst"]
    if worst and worst["aqi"] > go:
        groups["timing"].append(t["avoid_worst"].format(time=worst["time"], aqi=worst["aqi"]))
    tomorrow = plan.get("air_tomorrow") or {}
    if day == "today" and tomorrow.get("aqi") is not None and plan["air"]["day_aqi"] is not None:
        diff = tomorrow["aqi"] - plan["air"]["day_aqi"]
        if diff >= 20:
            groups["timing"].append(t["tomorrow_worse"].format(aqi=tomorrow["aqi"]))
        elif diff <= -20:
            groups["timing"].append(t["tomorrow_better"].format(aqi=tomorrow["aqi"]))

    # Getting around
    for leg in (plan.get("route") or {}).get("legs", []):
        if leg["worst"] and leg["worst"]["aqi"] > persona.limit_max:
            groups["travel"].append(ADVICE["actions"]["trip_bad"].format(
                trip=leg["label"], time=leg["time"], area=leg["worst"]["name"], aqi=leg["worst"]["aqi"]))
    c = plan["commute"]
    if c and c["aqi"] is not None and c["aqi"] > go:
        groups["travel"].append(t["set_out_over"].format(time=c["time"], aqi=c["aqi"], limit=go))
    mode = next(iter(modes), None) or (profile.commute if profile else None)
    if mode and COMMUTE_TIPS.get(mode):
        groups["travel"].append(COMMUTE_TIPS[mode])
    elif mode != "none" and plan["commute"]:
        groups["travel"].append(t["travel_default"])

    # Protect your lungs
    bad = verdict in ("limit", "stay_in") or (plan["air"]["day_aqi"] or 0) > go
    if bad:
        groups["protect"].append(ADVICE["actions"]["mask_have" if profile and profile.mask else "mask_advice"])
        groups["protect"].append(t["exercise"])
    else:
        groups["protect"].append(t["exercise_ok"])

    # At home: the window planner's own hours when it is on, else general advice
    if plan.get("windows"):
        groups["home"] += plan["windows"]["lines"]
    elif bad:
        groups["home"].append(ADVICE["actions"]["windows"])
        groups["home"].append(t["purifier"])
    groups["home"].append(t["home_sources"])
    groups["home"].append(t["water"])

    # Your health
    if profile and profile.sensitive and verdict != "go":
        groups["health"].append(ADVICE["actions"]["watch_symptoms"])
    if profile:
        groups["health"] += profile.tips()
    if profile and profile.conditions:
        groups["health"].append(t["medicines"])
    if not groups["health"]:
        groups["health"].append(t["symptoms_general"])

    return [{"key": k, **TEXT["groups"][k], "items": list(dict.fromkeys(v))} for k, v in groups.items() if v]


def _health(plan, persona, profile):
    h = TEXT["health"]
    value, go, limit = plan["air"]["day_aqi"], plan["thresholds"]["go_max"], plan["thresholds"]["limit_max"]
    verdict = verdict_for(persona, value)
    today = None
    if verdict:
        basis = _basis(plan)
        today = h[f"today_{verdict}"].format(area=plan["area"]["name"], aqi=value, basis=basis, go=go, limit=limit)
    shift = plan["health"].get("shift") or 0
    reasons = plan["health"].get("reasons") or []
    pct = lambda v: round(min(max(v, 0), SCALE_MAX) / SCALE_MAX * 100, 1)  # noqa: E731
    return {
        "today": today,
        "verdict": verdict,
        "impact": plan["air"]["impact"],
        "limits": {"go": go, "limit": limit, "go_pct": pct(go), "limit_pct": pct(limit),
                   "aqi": value, "aqi_pct": pct(value) if value is not None else None,
                   "note": h["limits_shift"].format(shift=shift, reasons=", ".join(reasons)) if shift and reasons
                   else h["limits_usual"]},
    }


def build(plan, persona, profile=None, modes=()):
    title = TEXT["title" if plan["day"] == "today" else "title_tomorrow"].format(area=plan["area"]["name"])
    return {
        "title": title,
        "area": _area(plan),
        "moments": _moments(plan, persona),
        "todo": _todo(plan, persona, profile, modes),
        "health": _health(plan, persona, profile),
    }


def hour_details(plan, wx=None):
    """Everything about each hour of the plan, for the clickable hourly view:
    air, particles, weather, the person's plans and what to do."""
    from .weather import band, compass, hour_note

    t = TEXT["hours"]
    by_time = {h["time"][:13]: h for h in (wx or {}).get("hours", [])}
    out = []
    for r in plan["hours"]:
        hour = r["hour"]
        w = by_time.get(r["time"][:13])
        weather = None
        if w:
            weather = {**w, "wind_from": compass(w.get("wind_dir"))[1], "note": hour_note(w),
                       "bands": {k: band(k, w.get(k)) for k in ("temp_c", "humidity", "wind_kmh", "mixing_m")}}
        plans = []
        for a in plan["activities"]:
            if not a["time"]:
                continue
            start = int(a["time"][:2])
            span = max(1, -(-(a["minutes"] or 60) // 60))
            if (hour - start) % 24 < span:
                plans.append(a)
        tags = {tag["kind"] for tag in r.get("tags", [])}
        do = list(t["do"][r.get("verdict") or "none"])
        if "worst" in tags:
            do.insert(0, t["do_worst"])
        if "best" in tags:
            do.insert(0, t["do_best"])
        out.append({
            "hour": hour,
            "label": f"{hour:02d}:00–{(hour + 1) % 24:02d}:00",
            "pm25": round(r["pm25"]) if r["pm25"] is not None else None,
            "pm10": round(r["pm10"]) if r["pm10"] is not None else None,
            "times_who": round(r["pm25"] / WHO_PM25_24H, 1) if r["pm25"] is not None else None,
            "weather": weather,
            "plans": plans,
            "do": do,
        })
    return out
