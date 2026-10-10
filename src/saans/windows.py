"""When to open the windows and when to run an air purifier, hour by hour,
for a day spent indoors or in one place. Built from the day's hourly AQI and
the person's own limits; all wording is in config/glance.json ("windows")."""
from . import aqi as aqi_mod
from . import data, settings

TEXT = settings.load("glance")["windows"]


def _ranges(hours):
    """[13, 14, 15, 20] -> [(13, 16), (20, 21)]: runs of consecutive hours, end exclusive."""
    out = []
    for h in hours:
        if out and out[-1][1] == h:
            out[-1] = (out[-1][0], h + 1)
        else:
            out.append((h, h + 1))
    return out


def _label(run):
    return f"{run[0]:02d}:00–{run[1] % 24:02d}:00"


def plan_windows(plan, now=None):
    """{"hours": [{hour, aqi, state, past}], "lines": [...]} for the plan's day, or
    None when the feature is off or there are no hourly figures. Each hour is
    "open" (air the rooms), "shut", or "purifier" (shut, and run a purifier)."""
    if not settings.get("window_planner_enabled"):
        return None
    hourly = (plan.get("hourly_aqi") or {}).get(plan["day"]) or {}
    if not hourly:
        return None
    go = plan["thresholds"]["go_max"]
    open_max = min(go, settings.get("window_open_aqi_max"))
    sleep = settings.get("sleep_hours")
    now = now or data.now_ist()
    current = now.astimezone(data.IST).hour if plan["day"] == "today" else -1
    hours = []
    for h in range(24):
        value = hourly.get(f"{h:02d}:00")
        if value is None:
            continue
        state = "open" if value <= open_max else "purifier" if value > go else "shut"
        hours.append({"hour": h, "aqi": value, "state": state, "slug": aqi_mod.category_slug(value),
                      "past": h < current, "sleep": h >= sleep[0] or h < sleep[1]})
    ahead = [h for h in hours if not h["past"]]
    if not ahead:
        return None
    lines = []
    opens = _ranges([h["hour"] for h in ahead if h["state"] == "open"])
    if opens:
        best = min(opens, key=lambda r: sum(hourly[f"{h:02d}:00"] for h in range(*r)) / (r[1] - r[0]))
        avg = round(sum(hourly[f"{h:02d}:00"] for h in range(*best)) / (best[1] - best[0]))
        lines.append(TEXT["open"].format(times=_label(best), aqi=avg))
        others = [r for r in opens if r != best]
        if others:
            lines.append(TEXT["open_also"].format(times=", ".join(_label(r) for r in others)))
    else:
        cleanest = min(ahead, key=lambda h: h["aqi"])
        lines.append(TEXT["open_none"].format(time=f"{cleanest['hour']:02d}:00", aqi=cleanest["aqi"],
                                              minutes=settings.get("window_airing_minutes")))
    shut = _ranges([h["hour"] for h in ahead if h["state"] != "open"])
    clean = _ranges([h["hour"] for h in ahead if h["state"] == "purifier"])
    if shut and shut == clean:  # every shut hour needs the purifier too: one line
        lines.append(TEXT["shut_purifier"].format(times=", ".join(_label(r) for r in shut)))
    else:
        if shut:
            lines.append(TEXT["shut"].format(times=", ".join(_label(r) for r in shut)))
        if clean:
            lines.append(TEXT["purifier"].format(times=", ".join(_label(r) for r in clean)))
    if clean and any(h["state"] == "purifier" and h["sleep"] for h in ahead):
        lines.append(TEXT["purifier_sleep"])
    return {"hours": hours, "lines": lines, "open_max": open_max, "go": go}
