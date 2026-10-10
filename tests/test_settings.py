import json

import pytest

from conftest import FIXED_NOW
from saans import data, settings, web
from saans.advisor import TEXT
from saans.personas import PERSONAS
from saans.service import get_plan


@pytest.fixture
def client(mem_store, monkeypatch, live_fetcher):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    return web.create_app().test_client()


# Settings file and environment overrides

def test_every_config_file_is_valid_json():
    for path in settings.CONFIG_DIR.glob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))


def test_environment_overrides_a_setting(monkeypatch):
    assert settings.get("dashboard_area") == "ito"
    monkeypatch.setenv("DASHBOARD_AREA", "dwarka")
    monkeypatch.setenv("FORECAST_DAYS", "5")
    monkeypatch.setenv("ALERT_PERSONAS", "rider, worker")
    assert settings.get("dashboard_area") == "dwarka"
    assert settings.get("forecast_days") == 5
    assert settings.get_list("alert_personas") == ["rider", "worker"]
    with pytest.raises(KeyError):
        settings.get("no_such_setting")


def test_dashboard_area_comes_from_settings(client, monkeypatch):
    monkeypatch.setenv("DASHBOARD_AREA", "dwarka")
    assert "Air quality at Dwarka" in client.get("/").get_data(as_text=True)


def test_alert_hours_on_the_plan_page_follow_settings(client, monkeypatch):
    monkeypatch.setenv("ALERT_MORNING_HOUR", "7")
    html = client.get("/plan?persona=school&area=ito").get_data(as_text=True)
    assert "at 07:00 and 19:00 when the plan changes" in html


# Hour by hour, per persona

def test_hours_carry_persona_advice_labels_and_tags(mem_store, live_fetcher):
    plan = get_plan("school", "ito", now=FIXED_NOW, fetcher=live_fetcher)
    labels = set(TEXT["hour_verdict_labels"].values())
    advice = set(PERSONAS["school"].hour_advice.values())
    for h in plan["hours"]:
        assert h["verdict_label"] in labels and h["advice"] in advice
    kinds = [t["kind"] for h in plan["hours"] for t in h["tags"]]
    assert kinds.count("worst") == 1 and "best" in kinds and "activity" in kinds


def test_rider_gets_a_break_not_a_best_time(mem_store, live_fetcher):
    plan = get_plan("rider", "ito", now=FIXED_NOW, fetcher=live_fetcher)
    kinds = {t["kind"] for h in plan["hours"] for t in h["tags"]}
    assert "break" in kinds and "best" not in kinds


def test_hour_by_hour_section_is_personal(client):
    school = client.get("/plan?persona=school&area=ito").get_data(as_text=True)
    rider = client.get("/plan?persona=rider&area=ito").get_data(as_text=True)
    assert "dp-chart" in school and PERSONAS["school"].question in school
    assert PERSONAS["rider"].hour_advice["go"] in rider and PERSONAS["rider"].hour_advice["go"] not in school


# Please read and the removed JSON button

def test_please_read_notes_have_titles(client):
    html = client.get("/plan?persona=older&area=ito&stage=III&age=70").get_data(as_text=True)
    notes = html.split("Please read", 1)[1].split("</details>", 1)[0]
    for key in ("stage_official", "forecast", "limits_profile", "medical"):
        assert f"note-{key}" in notes
    assert TEXT["notes"]["medical"]["title"] in notes


def test_plan_page_has_no_json_button(client):
    html = client.get("/plan?persona=older&area=ito").get_data(as_text=True)
    assert "/api/plan" not in html and ">JSON<" not in html


def test_stage_source_label_comes_from_config(client):
    html = client.get("/plan?persona=older&area=ito&stage=II").get_data(as_text=True)
    assert "What-if: set by you" in html and "Demo" not in html


# No forecast at all

def test_no_forecast_is_an_honest_503(mem_store, monkeypatch, failing_fetcher):
    monkeypatch.setattr(data, "fetch_open_meteo", failing_fetcher)
    client = web.create_app().test_client()
    page = client.get("/plan?persona=older&area=ito")
    assert page.status_code == 503 and "cannot be reached" in page.get_data(as_text=True)
    api = client.get("/api/plan?persona=older&area=ito")
    assert api.status_code == 503 and "cannot be reached" in api.get_json()["error"]
    home = client.get("/")
    assert home.status_code == 200 and "cannot be reached" in home.get_data(as_text=True)
