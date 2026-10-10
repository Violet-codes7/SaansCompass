"""The plan page's "At a glance" (what to do, grouped and personal) and the
extra detail in "Your health". Built from the finished plan; all wording is
in config/glance.json."""
from . import aqi as aqi_mod
from . import settings
from .advisor import TEXT as ADVICE
from .advisor import verdict_for
from .profile import COMMUTE_TIPS

TEXT = settings.load("glance")
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


def _area(plan):
    air, stage = plan["air"], plan["stage"]
    value = air["day_aqi"]
    out = {"name": plan["area"]["name"], "aqi": value, "category": air["category"], "slug": _slug(value),
           "impact": air["impact"], "pollutant": air["pollutant"],
           "basis": TEXT["area_basis_today" if plan["day"] == "today" else "area_basis_tomorrow"],
           "note": TEXT["area_notes"].get(plan["area"]["id"]), "vs_delhi": None, "rank": None}
    city = stage.get("city")
    if city and value is not None:
        diff = value - city["aqi"]
        key = "vs_delhi_same" if abs(diff) <= 5 else "vs_delhi_above" if diff > 0 else "vs_delhi_below"
        out["vs_delhi"] = TEXT[key].format(diff=abs(diff), delhi=city["aqi"])
        ids = [s["id"] for s in city["sites"]]
        if plan["area"]["id"] in ids:
            out["rank"] = TEXT["rank"].format(rank=ids.index(plan["area"]["id"]) + 1, count=len(ids))
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
    if not groups["rules"]:
        groups["rules"].append(t["no_rules"].format(day=day, stage=plan["stage"]["headline"]["title"]))

    # Timing
    w = plan["best_window"]
    flex = persona.activity(persona.flex_activity)
    if w and w.get("clean") is False:
        groups["timing"].append(ADVICE["actions"]["no_clean_window"].format(start=w["start"], aqi=w["avg_aqi"]))
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

    # At home
    if bad:
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
        basis = TEXT["area_basis_today" if plan["day"] == "today" else "area_basis_tomorrow"]
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
