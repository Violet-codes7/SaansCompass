from datetime import date

import pytest

from conftest import FIXED_NOW, make_hours
from saans import data
from saans.advisor import best_window
from saans.personas import PERSONAS, Persona
from saans.service import get_plan


def test_best_window_cleanest_and_worst():
    readings = [{"hour": h, "aqi": a} for h, a in zip(range(6), [300, 120, 80, 90, 250, 400])]
    assert best_window(readings, 60)["start"] == "02:00"
    assert best_window(readings, 90)["start"] == "02:00"  # 2 hours: 80+90
    assert best_window(readings, 60, prefer="worst")["start"] == "05:00"


def test_best_window_skips_missing_hours():
    readings = [{"hour": 0, "aqi": None}, {"hour": 1, "aqi": 150}, {"hour": 2, "aqi": 160}]
    assert best_window(readings, 60)["start"] == "01:00"
    assert best_window([{"hour": 0, "aqi": None}], 60) is None


def test_window_crossing_midnight_reads_next_day():
    night = Persona(
        id="night", label="Night worker", question="", start_hour=22, end_hour=2, effort="moderate",
        sensitive=False, go_max=200, limit_max=300, flex_activity="x", flex_prefers="worst", commute_hour=None,
    )
    assert night.hours() == [22, 23, 0, 1]
    pm = list(range(24))
    forecast = {"hours": make_hours(pm, days=2)}
    readings = data.readings_for(forecast, date(2026, 10, 10), night.hours())
    assert [r["time"] for r in readings] == [
        "2026-10-10T22:00", "2026-10-10T23:00", "2026-10-11T00:00", "2026-10-11T01:00",
    ]
    assert [r["pm25"] for r in readings] == [22, 23, 0, 1]


def test_missing_forecast_hours_come_back_empty():
    readings = data.readings_for({"hours": []}, date(2026, 10, 10), [9])
    assert readings[0]["aqi"] is None and readings[0]["category"] == "No data"


def test_two_personas_on_the_same_air_get_different_plans(mem_store, live_fetcher):
    school = get_plan("school", "ito", now=FIXED_NOW, fetcher=live_fetcher)
    rider = get_plan("rider", "ito", now=FIXED_NOW, fetcher=live_fetcher)
    assert school["stage"] == rider["stage"]
    assert school["best_window"]["start"] == "13:00"  # cleanest school hour
    assert rider["best_window"]["start"] == "19:00"  # dirtiest mid-shift hour, for the break
    assert school["dose"]["minutes"] != rider["dose"]["minutes"]
    assert rider["dose"]["minutes"] == 600


def test_rules_come_before_advice_in_the_plan(mem_store, live_fetcher):
    plan = get_plan("school", "ito", stage="IV", now=FIXED_NOW, fetcher=live_fetcher)
    assert {k: plan["stage"][k] for k in ("stage", "label", "source")} == {"stage": 4, "label": "IV", "source": "official"}
    assert plan["stage"]["headline"]["title"] == "Stage IV: Severe+ air"
    assert len(plan["rules"]) == len(PERSONAS["school"].activities)
    for a in plan["activities"]:
        assert a["rule"]["label"] in ("Allowed", "Not allowed", "Advised against", "Check the official order")
    by_id = {a["id"]: a for a in plan["activities"]}
    # Stage IV: primary classes must go hybrid, so the plan does not schedule them as usual.
    assert by_id["physical_classes_primary"]["rule"]["decision"] == "not_allowed"
    assert "Restricted at the GRAP stage" in by_id["physical_classes_primary"]["suggestion"]
    assert by_id["outdoor_pe"]["rule"]["decision"] == "advised_against"


def test_no_forecast_means_no_plan_never_made_up_numbers(mem_store, failing_fetcher, capsys):
    with pytest.raises(data.ForecastUnavailable):
        get_plan("older", "dwarka", now=FIXED_NOW, fetcher=failing_fetcher)
    assert "ForecastUnavailable" in capsys.readouterr().out
    assert mem_store.items == {}


def test_outage_falls_back_to_the_last_real_forecast(mem_store, live_fetcher, failing_fetcher, capsys):
    from datetime import timedelta
    fresh = get_plan("older", "dwarka", now=FIXED_NOW, fetcher=live_fetcher)
    later = FIXED_NOW + timedelta(hours=3)
    plan = get_plan("older", "dwarka", now=later, fetcher=failing_fetcher)
    assert plan["is_stale"] is True and plan["fetched_at"] == fresh["fetched_at"]
    assert plan["warnings"][0].startswith("The live forecast could not be reached")
    assert "StaleForecast" in capsys.readouterr().out
    with pytest.raises(data.ForecastUnavailable):  # too old to use
        get_plan("older", "dwarka", now=FIXED_NOW + timedelta(hours=49), fetcher=failing_fetcher)


def test_forecast_is_cached(mem_store, live_fetcher):
    get_plan("school", "ito", now=FIXED_NOW, fetcher=live_fetcher)
    get_plan("rider", "ito", now=FIXED_NOW, fetcher=live_fetcher)
    # Each area is fetched once: ITO for the plan, all of them for Delhi's AQI.
    assert sorted(live_fetcher.calls) == sorted(data.AREAS)


def test_expired_cache_is_refetched(mem_store, live_fetcher):
    from datetime import timedelta
    get_plan("school", "ito", now=FIXED_NOW, fetcher=live_fetcher)
    get_plan("school", "ito", now=FIXED_NOW + timedelta(minutes=31), fetcher=live_fetcher)
    assert live_fetcher.calls.count("ito") == 2


def test_tomorrow_uses_the_next_date(mem_store, live_fetcher):
    plan = get_plan("older", "ito", day="tomorrow", now=FIXED_NOW, fetcher=live_fetcher)
    assert plan["date"] == "2026-10-11" and plan["day"] == "tomorrow"


def test_open_meteo_parser_handles_nulls_and_bad_shapes():
    class Resp:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

    class Session:
        def __init__(self, payload):
            self.payload = payload

        def get(self, url, params, timeout):
            assert timeout == 3 and params["timezone"] == "Asia/Kolkata"
            return Resp(self.payload)

    from conftest import REAL_FETCH as real
    from saans.data import AREAS
    ok = {"hourly": {"time": ["2026-10-10T00:00"], "pm2_5": [None], "pm10": [80.0]}}
    assert real(AREAS["ito"], Session(ok)) == [{"time": "2026-10-10T00:00", "pm25": None, "pm10": 80.0}]
    bad = {"hourly": {"time": ["2026-10-10T00:00"], "pm2_5": [], "pm10": [80.0]}}
    try:
        real(AREAS["ito"], Session(bad))
        raise AssertionError("expected ValueError")
    except ValueError:
        pass



# The verdict never contradicts the rules (live-site review, 9 Oct)

SEVERITY = {"go": 0, "limit": 1, "stay_in": 2}


@pytest.mark.parametrize("persona,floor", [("school", "stay_in"), ("older", "stay_in"), ("rider", "limit")])
def test_stage_iv_caps_verdict(mem_store, monkeypatch, live_fetcher, persona, floor):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    clean = get_plan(persona, "ito", stage="0", now=FIXED_NOW)
    hard = get_plan(persona, "ito", stage="IV", now=FIXED_NOW)
    assert clean["verdict_note"] is None
    assert SEVERITY[hard["verdict"]] >= SEVERITY[floor]
    if SEVERITY[clean["verdict"]] < SEVERITY[floor]:
        assert "Stage IV" in hard["verdict_note"]


def test_school_at_stage_iv_gets_no_outdoor_window(mem_store, monkeypatch, live_fetcher):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    plan = get_plan("school", "ito", stage="IV", now=FIXED_NOW)
    assert plan["verdict"] == "stay_in" and plan["best_window"] is None
    assert all("advises against" in h["advice"] for h in plan["hours"])


def test_rules_rank_most_severe_first(mem_store, monkeypatch, live_fetcher):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    plan = get_plan("rider", "ito", stage="IV", now=FIXED_NOW)
    ranked = sorted((a for a in plan["activities"] if a["rule"]), key=lambda a: a["rank"])
    assert ranked[0]["rule"]["decision"] == "not_allowed"
