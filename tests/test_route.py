import json

import pytest

from conftest import FIXED_NOW
from saans import ai, data, route, web
from saans.personas import get_persona
from saans.service import get_plan


@pytest.fixture
def client(mem_store, monkeypatch, live_fetcher):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    monkeypatch.setattr(web, "_work_cache", {})
    monkeypatch.setattr(web, "_route_cache", {})
    return web.create_app().test_client()


# Places and travel from typed words

def test_nearest_area_and_coverage():
    area, km = route.nearest_area(28.63, 77.24)
    assert area.id == "ito" and km < 1
    assert route.nearest_area(19.07, 72.88)[0] is None  # Mumbai is outside what we cover


@pytest.mark.parametrize("text,area", [
    ("Mayur Vihar Phase 1", "anand-vihar"), ("Connaught Place", "ito"), ("R K Puram sector 4", "rk-puram"),
    ("DLF Cyber City, Gurugram", "dwarka"), ("Lajpat Nagar market", "okhla"), ("ITO", "ito"), ("Atlantis", None),
])
def test_match_place(text, area):
    found = route.match_place(text)
    assert (found.id if found else None) == area


def test_match_modes_puts_the_most_exposed_first():
    assert route.match_modes("Metro, then an e-rickshaw from the station") == ["auto", "metro"]
    assert route.main_mode(route.match_modes("I drive, sometimes walk")) == "walk"
    assert route.match_modes("") == []


def test_read_route_uses_ai_coordinates_then_keywords(monkeypatch):
    monkeypatch.setattr(ai, "read_route", lambda s, d, t: {"start": (28.669, 77.134), "destination": None,
                                                         "modes": ["bus"]})
    out = route.read_route("Paschim Vihar", "Connaught Place", "DTC bus")
    assert out == {"area": "punjabi-bagh", "to_area": "ito", "modes": ["bus"], "commute": "bus", "how": "ai"}


def test_ai_route_reading_is_checked(monkeypatch):
    answer = {"start": {"found": True, "lat": 28.57, "lon": 77.32},
              "destination": {"found": False, "lat": 0, "lon": 0}, "modes": ["metro", "rocket"]}
    monkeypatch.setattr(ai, "_structured", lambda *a, **k: json.dumps(answer))
    out = ai.read_route("Noida sector 18", "somewhere", "metro")
    assert out == {"start": (28.57, 77.32), "destination": None, "modes": ["metro"]}
    answer["start"]["lat"] = 200
    assert ai.read_route("x", "", "")["start"] is None
    monkeypatch.setattr(ai, "_structured", lambda *a, **k: None)
    assert ai.read_route("x", "y", "z") is None


# Trips

def test_corridor_runs_from_start_to_destination_in_order():
    stops = route.corridor(data.get_area("rohini"), data.get_area("okhla"))
    ids = [a.id for a in stops]
    assert ids[0] == "rohini" and ids[-1] == "okhla" and len(ids) > 2
    assert route.corridor(data.get_area("ito"), data.get_area("ito")) == [data.get_area("ito")]


def test_plan_with_destination_checks_both_trips(mem_store, live_fetcher):
    plan = get_plan("commuter", "anand-vihar", now=FIXED_NOW, fetcher=live_fetcher, to_area_id="rk-puram",
                    modes=["auto", "metro"])
    assert plan["area"]["id"] == "rk-puram"  # the day is spent at the destination
    r = plan["route"]
    assert r["from"]["id"] == "anand-vihar" and r["to"]["id"] == "rk-puram" and r["mode_labels"][0] == "Auto-rickshaw"
    going, back = r["legs"]
    persona = get_persona("commuter")
    assert going["time"] == f"{persona.commute_hour:02d}:00" and back["time"] == f"{persona.end_hour % 24:02d}:00"
    assert going["stops"][0]["id"] == "anand-vihar" and back["stops"][0]["id"] == "rk-puram"
    assert going["worst"]["aqi"] == max(s["aqi"] for s in going["stops"])
    assert plan["day_actions"][0].startswith("Going at ")  # this trip is above the commuter's limit
    assert plan["day_actions"][0] in plan["actions"]
    facts = ai.plan_facts(plan)["trips"]
    assert facts["from"] == "Anand Vihar" and "lat" not in json.dumps(facts)


def test_plan_without_destination_has_no_trips(mem_store, live_fetcher):
    assert get_plan("older", "ito", now=FIXED_NOW, fetcher=live_fetcher)["route"] is None


# Pages

def test_typed_route_is_read_once_into_the_link(client):
    resp = client.get("/plan?job=Office+job&from=Mayur+Vihar&to=Connaught+Place&travel=Metro+then+auto&area=")
    assert resp.status_code == 302
    loc = resp.headers["Location"]
    for part in ("area=anand-vihar", "to_area=ito", "commute=auto", "modes=auto%2Cmetro", "route_read=keywords"):
        assert part in loc
    html = client.get(loc).get_data(as_text=True)
    assert "Your trips" in html and "Going" in html and "Coming back" in html
    assert "Anand Vihar → ITO" in html and "Auto-rickshaw + Metro" in html
    assert "Air quality at ITO" in html


def test_live_location_start_is_not_read_again(client, monkeypatch):
    seen = []
    monkeypatch.setattr(route, "read_route", lambda s, d, t: seen.append((s, d, t)) or
                        {"area": None, "to_area": "rk-puram", "commute": None, "modes": [], "how": "keywords"})
    loc = client.get("/plan?persona=school&from=Near+ITO+(your+location)&area=ito&to=Saket").headers["Location"]
    assert seen == [(None, "Saket", None)] and "area=ito" in loc and "to_area=rk-puram" in loc


def test_unknown_place_says_so_and_offers_areas(client):
    loc = client.get("/plan?persona=commuter&from=Atlantis&to=Connaught+Place&area=").headers["Location"]
    html = client.get(loc).get_data(as_text=True)
    assert "We could not place &#34;Atlantis&#34;" in html and 'name="area"' in html


def test_trip_can_be_corrected_by_hand(client):
    html = client.get("/plan?persona=commuter&area=rohini&to_area=okhla&commute=bus&route_read=picked"
                      ).get_data(as_text=True)
    assert "Rohini → Okhla" in html and "Bus" in html and "(your choice)" not in html


def test_poster_shows_trips(client):
    html = client.get("/poster?persona=commuter&area=anand-vihar&to_area=ito&modes=metro&route_read=picked"
                      ).get_data(as_text=True)
    assert "Your trips" in html and "Anand Vihar → ITO" in html


def test_locate_api(client, caplog):
    caplog.set_level("INFO")
    ok = client.post("/api/locate", json={"lat": 28.6275, "lon": 77.2412}).get_json()
    assert ok["area"] == "ito" and ok["label"] == "Near ITO (your location)"
    far = client.post("/api/locate", json={"lat": 19.07, "lon": 72.88})
    assert far.status_code == 404 and "Type your town" in far.get_json()["error"]
    assert client.post("/api/locate", json={"lat": "x"}).status_code == 400
    assert client.post("/api/locate", json={"lat": 100, "lon": 0}).status_code == 400
    assert "28.6275" not in caplog.text and "77.2412" not in caplog.text


def test_places_anywhere_in_india_get_their_own_area(mem_store):
    from saans import data, route
    near = route.place_for(28.6300, 77.2400, "ITO crossing")
    assert near.id == "ito"  # within area_snap_km of ITO
    town = route.place_for(28.4595, 77.0266, "Gurugram")
    assert town.id.startswith("p-") and town.name == "Gurugram" and (town.lat, town.lon) == (28.46, 77.03)
    data._places.clear()
    assert data.get_area(town.id) == town  # read back from the store
    assert route.place_for(19.07, 72.88, "Mumbai").name == "Mumbai"
    assert route.place_for(51.51, -0.13, "London") is None  # outside India
    import pytest
    with pytest.raises(ValueError):
        data.get_area("p-000000000000")


# Places outside Delhi-NCR: their own air, no GRAP stage

def test_grap_applies_in_delhi_ncr_only(mem_store):
    assert data.in_grap_region(data.get_area("ito"))
    assert data.in_grap_region(route.place_for(28.4595, 77.0266, "Gurugram"))
    assert not data.in_grap_region(route.place_for(26.85, 80.95, "Lucknow"))


def test_plan_outside_ncr_has_no_grap_stage_or_rules(mem_store, live_fetcher):
    lucknow = route.place_for(26.85, 80.95, "Lucknow")
    plan = get_plan("commuter", lucknow.id, day="today", now=FIXED_NOW, store=mem_store, fetcher=live_fetcher,
                    every_stage=True)
    assert plan["grap_applies"] is False and plan["stage"]["source"] == "outside"
    assert plan["stage"]["headline"]["title"] == "No GRAP stage in Lucknow"
    assert not any(a["rule"] for a in plan["activities"]) and plan["stage_table"] is None
    assert set(live_fetcher.calls) == {lucknow.id}  # Delhi's areas are not needed
    assert plan["air"]["day_aqi"] is not None  # the town's own forecast


def test_plan_page_outside_ncr(client, monkeypatch):
    from saans import weather
    seen = []

    def no_weather(area):
        seen.append(area.name)
        raise TimeoutError("no network")
    monkeypatch.setattr(weather, "fetch_weather", no_weather)
    monkeypatch.setattr(data, "geocode", lambda text, session=None: (26.85, 80.95, "Lucknow"))
    loc = client.get("/plan?persona=commuter&from=Lucknow&area=&day=today").headers["Location"]
    assert "26.8" not in loc and "80.9" not in loc  # coordinates never go in the link
    html = client.get(loc).get_data(as_text=True)
    assert "No GRAP stage in Lucknow" in html and "GRAP rules apply only in Delhi-NCR." in html
    assert 'id="grap"' not in html and 'href="#grap"' not in html
    assert "Weather in Lucknow" in html and seen == ["Lucknow"]
