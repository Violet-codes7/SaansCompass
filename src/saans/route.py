"""Where someone starts, where they spend the day, and how they travel.

Typed places are read by the AI model into approximate coordinates, then
matched to the nearest area we have a forecast for; when the model is off,
area names and well-known localities (config/route.json) are matched instead.
A live location from the browser is matched the same way. Coordinates are
used for this request only: never stored, logged or put in a link.

Trips are judged on the areas the straight line between start and
destination passes near (an approximation of the road route), at the hour
the person leaves and the hour they come back.
"""
import math
import re
from datetime import timedelta

from . import aqi as aqi_mod
from . import ai, data, settings

TEXT = settings.load("route")
ALIASES = TEXT["aliases"]
COMMUTE_KEYWORDS = TEXT["commute_keywords"]
EXPOSURE_ORDER = TEXT["exposure_order"]
MODE_LABELS = settings.load("profile")["commute_modes"]


def distance_km(lat1, lon1, lat2, lon2):
    """Great-circle distance."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def nearest_area(lat, lon):
    """(area, km) for the closest area, or (None, km) when even that one is
    further than max_area_distance_km."""
    area = min(data.AREAS.values(), key=lambda a: distance_km(lat, lon, a.lat, a.lon))
    km = distance_km(lat, lon, area.lat, area.lon)
    return (area if km <= settings.get("max_area_distance_km") else None), round(km, 1)


def _words(text):
    return " " + " ".join(re.findall(r"[a-z0-9]+", str(text or "").lower())) + " "


def match_place(text):
    """The area named in free text (an area name or a known locality), or None.
    The longest match wins, so "Mayur Vihar" beats a bare "Vihar"."""
    words = _words(text)
    best, best_len = None, 0
    for area in data.AREAS.values():
        for name in [area.name, area.id.replace("-", " ")] + ALIASES.get(area.id, []):
            key = _words(name)
            if len(key) > best_len and key in words:
                best, best_len = area, len(key)
    return best


def match_modes(text):
    """Ways of travelling mentioned in free text, most exposed first."""
    words = _words(text)
    found = [m for m, keys in COMMUTE_KEYWORDS.items() if any(_words(k) in words for k in keys)]
    return sorted(found, key=EXPOSURE_ORDER.index)


def main_mode(modes):
    """The most exposed way of travelling: the one the advice is about."""
    modes = [m for m in modes if m in EXPOSURE_ORDER]
    return min(modes, key=EXPOSURE_ORDER.index) if modes else None


def read_route(start, destination, travel):
    """{"area", "to_area", "commute", "modes", "how"} from typed text. Areas
    are ids or None when a place could not be found."""
    reading = ai.read_route(start, destination, travel)
    out, used_ai = {}, reading is not None
    for key, text, field in (("area", start, "start"), ("to_area", destination, "destination")):
        area = None
        if reading and reading[field]:
            area = nearest_area(*reading[field])[0]
        if area is None and text:
            area = match_place(text)
        out[key] = area.id if area else None
    modes = (reading["modes"] if reading else []) or match_modes(travel)
    out["modes"] = sorted(dict.fromkeys(modes), key=EXPOSURE_ORDER.index)
    out["commute"] = main_mode(out["modes"])
    out["how"] = "ai" if used_ai else "keywords"
    return out


def corridor(start, dest):
    """Areas near the straight line from start to dest, in travel order."""
    if start.id == dest.id:
        return [start]
    # Flat projection around Delhi is accurate enough at this scale.
    kx = 111.32 * math.cos(math.radians((start.lat + dest.lat) / 2))
    ky = 110.57

    def xy(a):
        return ((a.lon - start.lon) * kx, (a.lat - start.lat) * ky)

    bx, by = xy(dest)
    length2 = bx * bx + by * by
    via = []
    for a in data.AREAS.values():
        if a.id in (start.id, dest.id):
            continue
        px, py = xy(a)
        t = (px * bx + py * by) / length2
        if not 0 < t < 1:
            continue
        off = math.hypot(px - t * bx, py - t * by)
        if off <= settings.get("route_corridor_km"):
            via.append((t, a))
    return [start] + [a for _, a in sorted(via, key=lambda v: v[0])] + [dest]


def trip_hours(persona):
    """(leave, come back) hours for the persona's day."""
    leave = persona.commute_hour if persona.commute_hour is not None else persona.start_hour
    return leave, persona.end_hour % 24


def _forecasts(areas, store, now, fetcher):
    return data.get_forecasts(areas, store, now=now, fetcher=fetcher)


def trips(persona, start, dest, date, store, now, fetcher=None, modes=()):
    """The air on the way out and back, stop by stop."""
    stops = corridor(start, dest)
    forecasts = _forecasts(stops, store, now, fetcher)
    leave, back = trip_hours(persona)
    legs = []
    for key, hour, order in (("go", leave, stops), ("back", back, list(reversed(stops)))):
        day = date + timedelta(days=1) if key == "back" and back < leave else date
        points = []
        for a in order:
            f = forecasts.get(a.id)
            r = data.readings_for(f, day, [hour])[0] if f else None
            value = r["aqi"] if r else None
            points.append({"id": a.id, "name": a.name, "aqi": value,
                           "category": aqi_mod.category(value) if value is not None else None,
                           "slug": aqi_mod.category_slug(value) if value is not None else "no-data"})
        known = [p for p in points if p["aqi"] is not None]
        legs.append({"key": key, "label": TEXT["trip_labels"][key], "time": f"{hour:02d}:00", "stops": points,
                     "worst": max(known, key=lambda p: p["aqi"]) if known else None})
    return {
        "from": {"id": start.id, "name": start.name},
        "to": {"id": dest.id, "name": dest.name},
        "modes": list(modes),
        "mode_labels": [MODE_LABELS[m] for m in modes if m in MODE_LABELS],
        "km": round(distance_km(start.lat, start.lon, dest.lat, dest.lon), 1),
        "legs": legs,
    }
