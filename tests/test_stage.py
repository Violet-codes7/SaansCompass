import pytest

from saans.stage import parse_stage, resolve_stage, stage_from_aqi


@pytest.mark.parametrize("value,stage", [
    (None, None), (0, 0), (200, 0), (201, 1), (300, 1), (301, 2), (400, 2), (401, 3), (450, 3), (451, 4), (500, 4),
])
def test_stage_band_edges(value, stage):
    assert stage_from_aqi(value) == stage


@pytest.mark.parametrize("raw,stage", [
    (None, None), ("", None), ("  ", None), ("0", 0), ("none", 0), ("I", 1), ("ii", 2), ("III", 3), ("4", 4), ("IV", 4),
])
def test_parse_stage(raw, stage):
    assert parse_stage(raw) == stage


@pytest.mark.parametrize("raw", ["V", "5", "-1", "stage3", "<script>"])
def test_parse_stage_rejects_bad_input(raw):
    with pytest.raises(ValueError):
        parse_stage(raw)


def test_official_stage_wins_over_estimate():
    got = resolve_stage(480, official=1)
    assert {k: got[k] for k in ("stage", "label", "source", "day_aqi", "estimate")} == {
        "stage": 1, "label": "I", "source": "official", "day_aqi": 480, "estimate": "IV"}
    assert resolve_stage(480)["source"] == "estimate"
    assert resolve_stage(480)["stage"] == 4


def test_official_stage_zero_is_respected():
    info = resolve_stage(480, official=0)
    assert info["stage"] == 0 and info["source"] == "official"


# Delhi-wide stage

def _fetch_with(dirty_area, dirty, clean):
    from conftest import make_hours

    def fetch(area):
        return make_hours([dirty if area.id == dirty_area else clean] * 24)
    return fetch


def test_stage_follows_delhi_not_one_area(mem_store):
    from conftest import FIXED_NOW
    from saans.service import get_plan
    fetch = _fetch_with("dwarka", 300, 70)  # one hotspot, the rest Moderate-to-Poor
    dwarka = get_plan("commuter", "dwarka", now=FIXED_NOW, fetcher=fetch)
    ito = get_plan("commuter", "ito", now=FIXED_NOW, fetcher=fetch)
    assert dwarka["stage"]["stage"] == ito["stage"]["stage"]
    assert dwarka["stage"]["day_aqi"] == ito["stage"]["day_aqi"]
    city = ito["stage"]["city"]
    assert city["count"] == 9 and city["high"]["id"] == "dwarka" and city["basis"] == "last24"
    assert city["aqi"] == round(sum(s["aqi"] for s in city["sites"]) / 9)
    assert dwarka["air"]["day_aqi"] > dwarka["stage"]["day_aqi"]  # the area's own air is still shown


def test_next_stage_and_outlook():
    from saans.stage import next_stage
    assert next_stage(0, 195) == {"stage": 1, "label": "I", "min_aqi": 201, "gap": 6}
    assert next_stage(4, 480) is None
    got = resolve_stage(195, outlook=320)
    assert got["outlook"] == {"aqi": 320, "stage": 2, "label": "II"} and got["basis"] == "area"


def test_plan_page_explains_where_delhi_stands(mem_store, monkeypatch):
    from saans import data, web
    fetch = _fetch_with("dwarka", 120, 60)
    monkeypatch.setattr(data, "fetch_open_meteo", fetch)
    monkeypatch.setattr(web, "_work_cache", {})
    html = web.create_app().test_client().get("/plan?persona=commuter&area=ito&day=today").get_data(as_text=True)
    for text in ("Where ITO stands", "the 24-hour AQI of 9 areas, averaged", "Worst: Dwarka",
                 "points away", "GRAP level at ITO", "sets the rules", "What Stage I would bring", "anti-smog guns",
                 "the same figure as the air dials"):
        assert text in html, text


def test_area_aqi_is_the_same_everywhere(mem_store, monkeypatch):
    from saans import data, web
    from saans.service import get_plan
    fetch = _fetch_with("dwarka", 120, 60)
    plan = get_plan("commuter", "ito", now=data.now_ist(), fetcher=fetch, day="today")
    dial = plan["air_now"]["particles"]
    assert plan["air"]["day_aqi"] == dial["aqi"] == plan["stage"]["area_aqi"]
    assert plan["air"]["pm25_day"] == dial["pm25"]
    assert [s["aqi"] for s in plan["stage"]["city"]["sites"] if s["id"] == "ito"] == [dial["aqi"]]
    monkeypatch.setattr(data, "fetch_open_meteo", fetch)
    monkeypatch.setattr(web, "_work_cache", {})
    html = web.create_app().test_client().get("/plan?persona=commuter&area=ito&day=today").get_data(as_text=True)
    aqi = dial["aqi"]
    assert f"ITO: AQI {aqi} (" in html and f'class="g-v">{aqi}</b>' in html and f"ITO {aqi}</b>" in html


def test_rules_follow_travel_and_vehicle(mem_store, live_fetcher):
    from conftest import FIXED_NOW
    from saans.profile import parse_profile
    from saans.service import get_plan
    from werkzeug.datastructures import MultiDict

    def rules(stage, modes=(), **profile):
        p = parse_profile(MultiDict(profile), "older") if profile else None
        plan = get_plan("commuter" if not profile else "older", "ito", stage=stage, now=FIXED_NOW,
                        fetcher=live_fetcher, profile=p, modes=modes)
        return {a["id"]: (a["label"], a["rule"]["decision"]) for a in plan["activities"] if a["rule"]}, plan

    metro, _ = rules("III", modes=["metro"])
    assert metro["morning_commute"] == ("Morning commute by metro", "allowed")
    car, _ = rules("III", vehicle="car_old", age="70")
    assert car["drive_bs3_petrol_bs4_diesel_car"][1] == "not_allowed"
    commute, plan = rules("I", modes=["car"])
    assert commute["morning_commute"][1] == "check_official_order"  # car not known
    explain = {a["id"]: a["explain"] for a in plan["activities"]}
    assert "Add your car" in explain["morning_commute"]["do"]


def test_area_level_leads_but_rules_follow_delhi(mem_store):
    from conftest import FIXED_NOW
    from saans.service import get_plan
    fetch = _fetch_with("dwarka", 300, 70)
    dwarka = get_plan("commuter", "dwarka", now=FIXED_NOW, fetcher=fetch)
    ito = get_plan("commuter", "ito", now=FIXED_NOW, fetcher=fetch)
    assert dwarka["stage"]["local"]["stage"] > ito["stage"]["local"]["stage"]
    assert dwarka["stage"]["stage"] == ito["stage"]["stage"]  # one stage in force for all of Delhi-NCR
