"""Cleaner route: the road routes between two places from Amazon Location
Service, and the air along each.

A better path is offered only on bad-air trips (see compare). The air at points every sample_km along a route is the nearest live station
within station_km (airmap.stations, for a box around all the routes). A
route's dose is its average AQI times its minutes on the way; the cleanest
route is the one with the smallest dose, so a cleaner but much longer route
does not win by default. Results are cached for cpcb_cache_seconds.
"""
import json
import logging
import math

from . import aqi as aqi_mod
from . import airmap, data, settings
from .route import EXPOSURE_ORDER, distance_km

log = logging.getLogger(__name__)

TEXT = airmap.MAP["route"]


def enabled():
    return settings.get("clean_route")


def travel_mode(mode):
    """Amazon Location's travel mode for one of our ways of travelling, or
    None when routes don't fit it (metro, staying in one place)."""
    if not mode:
        mode = TEXT["default_mode"]
    return TEXT["travel_modes"].get(mode)


def _client():
    import boto3

    return boto3.client("geo-routes", region_name=settings.get("location_region") or None)


def routes_from_answer(resp):
    """[{"coords": [[lon, lat], ...], "km", "min"}] from a CalculateRoutes answer."""
    out = []
    for r in (resp or {}).get("Routes") or []:
        coords = []
        for leg in r.get("Legs") or []:
            coords.extend((leg.get("Geometry") or {}).get("LineString") or [])
        if len(coords) < 2:
            continue
        summary = r.get("Summary") or {}
        km = summary.get("Distance")
        km = km / 1000 if km is not None else sum(distance_km(a[1], a[0], b[1], b[0]) for a, b in zip(coords, coords[1:]))
        seconds = summary.get("Duration")
        out.append({"coords": coords, "km": round(km, 1), "min": round(seconds / 60) if seconds is not None else None})
    return out


def calculate(start, dest, travel, client=None):
    """The routes from start to dest, best first, or [] when they can't be found."""
    try:
        resp = (client or _client()).calculate_routes(
            Origin=[start.lon, start.lat], Destination=[dest.lon, dest.lat], TravelMode=travel,
            MaxAlternatives=TEXT["max_alternatives"], LegGeometryFormat="Simple", DepartNow=True)
    except Exception as exc:  # not set up, no permission, no route
        log.warning("routes failed: %s", type(exc).__name__)
        return []
    return routes_from_answer(resp)


def samples(coords, step_km, max_points):
    """Points (lat, lon) every step_km along a line, start and end included."""
    total = sum(distance_km(a[1], a[0], b[1], b[0]) for a, b in zip(coords, coords[1:]))
    step = max(step_km, total / max(max_points - 1, 1))
    out, next_at, done = [(coords[0][1], coords[0][0])], step, 0.0
    for a, b in zip(coords, coords[1:]):
        seg = distance_km(a[1], a[0], b[1], b[0])
        while seg > 0 and done + seg >= next_at:
            t = (next_at - done) / seg
            out.append((a[1] + (b[1] - a[1]) * t, a[0] + (b[0] - a[0]) * t))
            next_at += step
        done += seg
    out.append((coords[-1][1], coords[-1][0]))
    return out


def _nearest_aqi(lat, lon, stations, max_km):
    best = None
    for s in stations:
        km = distance_km(lat, lon, s["lat"], s["lon"])
        if km <= max_km and (best is None or km < best[0]):
            best = (km, s["aqi"])
    return best[1] if best else None


def _box(routes, pad_km):
    lats = [c[1] for r in routes for c in r["coords"]]
    lons = [c[0] for r in routes for c in r["coords"]]
    dlat = pad_km / 110.57
    dlon = pad_km / (111.32 * math.cos(math.radians(sum(lats) / len(lats))))
    return (round(min(lats) - dlat, 2), round(min(lons) - dlon, 2), round(max(lats) + dlat, 2), round(max(lons) + dlon, 2))


def _thin(coords, max_points=300):
    """Fewer points for drawing; the shape stays."""
    if len(coords) <= max_points:
        return coords
    k = math.ceil(len(coords) / max_points)
    return coords[::k] + ([coords[-1]] if (len(coords) - 1) % k else [])


def score(routes, stations, max_km=None):
    """Each route with its average AQI along the way and its dose, or None
    when too little of it is near a station."""
    out = []
    for i, r in enumerate(routes):
        values = [_nearest_aqi(lat, lon, stations, max_km or TEXT["station_km"])
                  for lat, lon in samples(r["coords"], TEXT["sample_km"], TEXT["max_samples"])]
        known = [v for v in values if v is not None]
        if not values or len(known) / len(values) < TEXT["min_covered"]:
            avg = None
        else:
            avg = round(sum(known) / len(known))
        minutes = r["min"] if r["min"] is not None else r["km"]
        out.append({"n": i + 1, "km": r["km"], "min": r["min"], "aqi": avg,
                    "slug": aqi_mod.category_slug(avg) if avg is not None else None,
                    "dose": avg * minutes if avg is not None else None, "coords": _thin(r["coords"])})
    return out


def _forecast_points(routes, store, now, fetcher=None):
    """Stand-in stations from the forecast model at points along the routes,
    for trips beyond the reach of monitoring stations."""
    step = TEXT["forecast_point_km"]
    seen, places = set(), []
    for r in routes:
        for lat, lon in samples(r["coords"], step, TEXT["max_samples"]):
            cell = (round(lat, 1), round(lon, 1))
            if cell not in seen and len(places) < TEXT["forecast_points"]:
                seen.add(cell)
                if data.in_coverage(lat, lon):
                    places.append(data.Area(f"pt-{cell[0]:.1f},{cell[1]:.1f}", "", cell[0], cell[1]))
    local = now.astimezone(data.IST)
    out = []
    forecasts = data.get_forecasts(places, store, now=now, fetcher=fetcher)
    for place in places:
        f = forecasts.get(place.id)
        r = data.readings_for(f, local.date(), [local.hour])[0] if f else None
        if r and r.get("aqi") is not None:
            out.append({"lat": place.lat, "lon": place.lon, "aqi": r["aqi"]})
    return out


def compare(start, dest, mode, store, now, client=None, session=None, fetcher=None):
    """{"routes", "best", "pct", "source"} for a trip, or None when there is
    nothing to compare (no routes, or no air along them)."""
    travel = travel_mode(mode)
    if travel is None or start.id == dest.id:
        return None
    key = f"ROUTES#{start.id}#{dest.id}#{travel}"
    if store is not None and client is None:
        cached = store.get_text(key)
        if cached:
            return json.loads(cached) or None
    routes = calculate(start, dest, travel, client)
    if not routes:
        return None
    air = airmap.stations(store, now, box=_box(routes, TEXT["station_km"]), session=session, fetcher=fetcher)
    scored = score(routes, air["stations"])
    if not any(r["dose"] is not None for r in scored):  # too few stations out here: the forecast at points on the way
        scored = score(routes, _forecast_points(routes, store, now, fetcher), TEXT["forecast_point_km"])
    # Route 1 is Amazon Location's first answer, the way most people would go.
    # A better path is suggested only when its air is worse than suggest_above_aqi
    # and another route cuts the pollution breathed by at least suggest_min_pct.
    usual = scored[0]
    known = [r for r in scored if r["dose"] is not None]
    out = None
    if usual["dose"] and known:
        best = min(known, key=lambda r: r["dose"])
        pct = round(100 * (usual["dose"] - best["dose"]) / usual["dose"])
        suggest = (usual["aqi"] > TEXT["suggest_above_aqi"] and best["n"] != usual["n"]
                   and pct >= TEXT["suggest_min_pct"])
        out = {"from": start.name, "to": dest.name, "travel": travel, "routes": scored, "best": best["n"],
               "pct": pct, "suggest": suggest, "source": air["source"]}
    if out and store is not None and client is None:
        store.put_text(key, json.dumps(out), ttl_seconds=settings.get("cpcb_cache_seconds"))
    return out


def plan_trip(plan):
    """(start, dest, mode) for the plan's trip, or None when it has none."""
    r = plan.get("route")
    if not r:
        return None
    try:
        start, dest = data.get_area(r["from"]["id"]), data.get_area(r["to"]["id"])
    except ValueError:
        return None
    modes = r.get("modes") or []
    if any(travel_mode(m) is None for m in modes):  # part of the trip is by metro, or no trip
        return None
    # The least exposed way listed is the one that covers the distance (bus, not the walk to it).
    return start, dest, (max(modes, key=EXPOSURE_ORDER.index) if modes else None)
