"""Dose saved, the weekly diary and the window planner."""
import pytest

from saans import data, saving, windows
from saans.service import get_plan


@pytest.fixture
def plan_for(mem_store, monkeypatch, live_fetcher):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    return lambda persona, **kw: get_plan(persona, "ito", day="tomorrow", **kw)


def test_following_the_plan_breathes_less_than_the_worst_hours(plan_for):
    ds = plan_for("school")["dose_saved"]
    assert ds["follow_ug"] < ds["usual_ug"] <= ds["worst_ug"] and 0 < ds["vs_worst_pct"] <= 100
    assert ds["minutes"] > 0


def test_tiny_savings_and_the_switch_hide_it(plan_for, monkeypatch):
    assert not plan_for("rider")["dose_saved"]["show"]  # a short break off the road saves only a little
    monkeypatch.setenv("DOSE_SAVED_ENABLED", "false")
    assert plan_for("school")["dose_saved"] is None


def test_window_planner_opens_at_clean_hours_and_shuts_at_bad_ones(plan_for):
    wp = plan_for("school")["windows"]
    states = {h["hour"]: h["state"] for h in wp["hours"]}
    aqi = {h["hour"]: h["aqi"] for h in wp["hours"]}
    assert all(states[h] == "open" for h in states if aqi[h] <= wp["open_max"])
    assert all(states[h] == "purifier" for h in states if aqi[h] > wp["go"])
    assert wp["lines"][0].startswith("Open the windows") and any("purifier" in line for line in wp["lines"])


def test_window_planner_switch(plan_for, monkeypatch):
    monkeypatch.setenv("WINDOW_PLANNER_ENABLED", "false")
    assert plan_for("school")["windows"] is None


def test_week_counts_only_followed_days():
    diary = {}
    for date, followed in (("2026-10-05", "yes"), ("2026-10-07", "partly"), ("2026-10-08", "no"), ("2026-09-01", "yes")):
        diary = saving.add_to_diary(diary, date, {"followed": followed, "follow_ug": 100.0, "worst_ug": 300.0})
    w = saving.week(diary, "2026-10-08")
    assert [d["date"] for d in w["days"]][0] == "2026-10-02" and w["logged"] == 3 and w["followed"] == 2
    assert w["saved_pct"] == round(100 * (200 + 100) / 900)
    assert [d["bar_pct"] for d in w["days"] if d["entry"]] == [33, 67, 100]


def test_ranges_join_consecutive_hours():
    assert windows._ranges([0, 1, 2, 5, 6, 23]) == [(0, 3), (5, 7), (23, 24)]


def test_a_run_to_midnight_ends_at_24():
    from saans.windows import _label
    assert _label((20, 24)) == "20:00–24:00"
