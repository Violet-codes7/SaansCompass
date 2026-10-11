"""The pollution map and Cleaner route."""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from conftest import FIXED_NOW
from saans import airmap, cleanroute, data, i18n
from saans.web import create_app

STAMP = FIXED_NOW.strftime("%Y-%m-%dT%H:00:00+05:30")


def bounds(*stations):
    return {"status": "ok", "data": [
        {"lat": lat, "lon": lon, "uid": i, "aqi": aqi, "station": {"name": name, "time": t or STAMP}}
        for i, (name, lat, lon, aqi, t) in enumerate(stations)]}


class FakeSession:
    def __init__(self, body):
        self.body, self.calls = body, []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params})
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: self.body)


@pytest.fixture
def client(mem_store, monkeypatch, live_fetcher):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    monkeypatch.delenv("TOPIC_ARN", raising=False)
    return create_app().test_client()


def test_bounds_stations_are_on_india_scale_and_fresh_only(monkeypatch):
    old = (FIXED_NOW - timedelta(hours=5)).strftime("%Y-%m-%dT%H:00:00+05:30")
    body = bounds(("ITO, Delhi, India", 28.63, 77.24, "200", None), ("No reading, Delhi", 28.6, 77.2, "-", None),
                  ("Old, Delhi", 28.7, 77.1, "150", old))
    out = airmap.stations_from_bounds(body, FIXED_NOW)
    assert [s["name"] for s in out] == ["ITO"]
    assert out[0]["aqi"] == 324 and out[0]["slug"] == "very-poor" and out[0]["time"] == "09:00"
    assert airmap.stations_from_bounds({"status": "error", "data": "Invalid key"}, FIXED_NOW) == []


def test_token_and_box_go_to_aqicn(monkeypatch, mem_store):
    monkeypatch.setenv("WAQI_TOKEN", "tok")
    s = FakeSession(bounds(("ITO", 28.63, 77.24, "120", None)))
    out = airmap.stations(mem_store, FIXED_NOW, session=s)
    assert out["source"] == "aqicn" and len(out["stations"]) == 1
    params = s.calls[0]["params"]
    assert params["token"] == "tok" and params["latlng"] == ",".join(str(v) for v in airmap.default_box())


def test_falls_back_to_each_areas_forecast(mem_store, live_fetcher):
    out = airmap.stations(mem_store, FIXED_NOW, fetcher=live_fetcher)
    assert out["source"] == "forecast" and len(out["stations"]) == len(data.AREAS)


def test_base_map_is_amazon_location_when_the_key_exists(monkeypatch):
    monkeypatch.setenv("MAP_KEY_NAME", "saans-compass-map")
    monkeypatch.setenv("LOCATION_REGION", "ap-south-1")
    fake = SimpleNamespace(describe_key=lambda KeyName: {"Key": "v1.public.abc+/="})
    s = airmap.style("dark", client=fake)
    assert s["provider"] == "amazon-location"
    assert s["url"].startswith("https://maps.geo.ap-south-1.amazonaws.com/v2/styles/Standard/descriptor?key=v1.public.abc%2B%2F%3D")
    assert s["url"].endswith("color-scheme=Dark")


def test_base_map_falls_back_to_open_tiles(monkeypatch):
    assert airmap.style()["provider"] == "tiles"
    monkeypatch.setenv("MAP_KEY_NAME", "missing")

    def boom(KeyName):
        raise RuntimeError("no key")
    assert airmap.style(client=SimpleNamespace(describe_key=boom))["provider"] == "tiles"


# Two routes from ITO to Okhla: the straight one passes a dirty station.
STRAIGHT = [[77.24, 28.63], [77.26, 28.59], [77.28, 28.55]]
AROUND = [[77.24, 28.63], [77.20, 28.60], [77.24, 28.55], [77.28, 28.55]]
STATIONS = [{"lat": 28.59, "lon": 77.26, "aqi": 300}, {"lat": 28.63, "lon": 77.24, "aqi": 150},
            {"lat": 28.60, "lon": 77.20, "aqi": 80}, {"lat": 28.55, "lon": 77.24, "aqi": 90},
            {"lat": 28.55, "lon": 77.28, "aqi": 150}]


def answer(*routes):
    return {"Routes": [{"Legs": [{"Geometry": {"LineString": c}}], "Summary": {"Distance": km * 1000, "Duration": mins * 60}}
                       for c, km, mins in routes]}


def test_routes_are_read_from_amazon_location():
    out = cleanroute.routes_from_answer(answer((STRAIGHT, 10.2, 25)))
    assert out == [{"coords": STRAIGHT, "km": 10.2, "min": 25}]
    assert cleanroute.routes_from_answer({"Routes": [{"Legs": []}]}) == []


def test_samples_cover_the_line_end_to_end():
    pts = cleanroute.samples(STRAIGHT, 1.0, 80)
    assert pts[0] == (28.63, 77.24) and pts[-1] == (28.55, 77.28) and 9 <= len(pts) <= 12
    assert len(cleanroute.samples(STRAIGHT, 0.01, 5)) <= 6


def test_cleanest_route_is_the_smallest_dose(monkeypatch, mem_store):
    calls = []

    class Client:
        def calculate_routes(self, **kw):
            calls.append(kw)
            return answer((STRAIGHT, 10, 25), (AROUND, 14, 30))
    monkeypatch.setattr(airmap, "stations", lambda store, now, box=None, session=None, fetcher=None:
                        {"stations": STATIONS, "source": "aqicn", "box": list(box)})
    ito, okhla = data.get_area("ito"), data.get_area("okhla")
    out = cleanroute.compare(ito, okhla, "two_wheeler", mem_store, FIXED_NOW, client=Client())
    assert calls[0]["TravelMode"] == "Scooter" and calls[0]["Origin"] == [ito.lon, ito.lat]
    assert calls[0]["LegGeometryFormat"] == "Simple"
    straight, around = out["routes"]
    assert around["aqi"] < straight["aqi"] and out["best"] == 2 and out["pct"] > 0
    assert straight["aqi"] > cleanroute.TEXT["suggest_above_aqi"] and out["suggest"] is True
    assert around["slug"] == cleanroute.aqi_mod.category_slug(around["aqi"])


def test_no_better_path_on_clean_air_days(monkeypatch, mem_store):
    class Client:
        def calculate_routes(self, **kw):
            return answer((STRAIGHT, 10, 25), (AROUND, 14, 30))
    clean = [{**s, "aqi": s["aqi"] // 4} for s in STATIONS]  # every station Satisfactory or better
    monkeypatch.setattr(airmap, "stations", lambda *a, **k: {"stations": clean, "source": "aqicn", "box": []})
    out = cleanroute.compare(data.get_area("ito"), data.get_area("okhla"), "car", mem_store, FIXED_NOW, client=Client())
    assert out["routes"][0]["aqi"] <= cleanroute.TEXT["suggest_above_aqi"] and out["suggest"] is False


def test_no_routes_or_no_air_means_nothing_to_show(monkeypatch, mem_store):
    ito, okhla = data.get_area("ito"), data.get_area("okhla")

    class Fail:
        def calculate_routes(self, **kw):
            raise RuntimeError("AccessDenied")
    assert cleanroute.compare(ito, okhla, "car", mem_store, FIXED_NOW, client=Fail()) is None

    class One:
        def calculate_routes(self, **kw):
            return answer((STRAIGHT, 10, 25))
    monkeypatch.setattr(airmap, "stations", lambda *a, **k: {"stations": [], "source": None, "box": []})
    assert cleanroute.compare(ito, okhla, "car", mem_store, FIXED_NOW, client=One()) is None
    assert cleanroute.compare(ito, okhla, "metro", mem_store, FIXED_NOW, client=One()) is None


def test_trip_mode_is_the_one_that_covers_the_distance():
    plan = {"route": {"from": {"id": "ito"}, "to": {"id": "okhla"}, "modes": ["walk", "bus"]}}
    start, dest, mode = cleanroute.plan_trip(plan)
    assert (start.id, dest.id, mode) == ("ito", "okhla", "bus") and cleanroute.travel_mode(mode) == "Car"
    assert cleanroute.plan_trip({"route": {**plan["route"], "modes": ["walk", "metro"]}}) is None
    assert cleanroute.plan_trip({"route": None}) is None


def test_home_page_has_the_map_and_its_words_follow_hindi(client):
    html = client.get("/").get_data(as_text=True)
    assert 'id="air-map"' in html and "airmap.js" in html and airmap.MAP["text"]["title"] in html
    for text in list(airmap.MAP["text"].values()) + list(airmap.MAP["route"]["text"].values()):
        assert i18n.builtin(text), f"missing Hindi for {text!r}"


def test_map_and_route_can_be_turned_off(client, monkeypatch):
    monkeypatch.setenv("AIR_MAP", "off")
    monkeypatch.setenv("CLEAN_ROUTE", "off")
    assert 'id="air-map"' not in client.get("/").get_data(as_text=True)
    assert client.get("/api/map/stations").status_code == 404
    assert client.get("/api/routes?from=ito&to=okhla").status_code == 404
    html = client.get("/plan?persona=commuter&area=rohini&to_area=okhla&commute=bus&route_read=picked").get_data(as_text=True)
    assert 'id="clean-route"' not in html


def test_plan_with_a_trip_asks_for_cleaner_routes(client):
    html = client.get("/plan?persona=commuter&area=rohini&to_area=okhla&commute=bus&modes=bus&route_read=picked"
                      ).get_data(as_text=True)
    assert 'id="clean-route"' in html and "/api/routes?from=rohini&amp;to=okhla&amp;mode=bus" in html
    html = client.get("/plan?persona=commuter&area=rohini&to_area=okhla&modes=metro&route_read=picked").get_data(as_text=True)
    assert 'id="clean-route"' not in html


def test_api_endpoints(client, monkeypatch):
    body = client.get("/api/map/stations").get_json()
    assert body["source"] == "forecast" and body["stations"]
    assert client.get("/api/routes?from=atlantis&to=okhla").status_code == 400
    assert client.get("/api/routes?from=ito&to=okhla&mode=jet").status_code == 400
    monkeypatch.setattr(cleanroute, "compare", lambda *a, **k: None)
    assert client.get("/api/routes?from=ito&to=okhla").status_code == 503
    monkeypatch.setattr(cleanroute, "compare", lambda *a, **k: {"routes": [], "best": 1, "pct": 0, "suggest": False})
    assert client.get("/api/routes?from=ito&to=okhla&mode=car").get_json()["best"] == 1
