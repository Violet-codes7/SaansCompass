from datetime import datetime

import pytest
from werkzeug.datastructures import MultiDict

from conftest import FIXED_NOW
from saans import ai, data
from saans.personas import PERSONAS
from saans.profile import guess_work, parse_profile, tidy_role
from saans.rules import ADVISED_AGAINST, ALLOWED, CHECK, NOT_ALLOWED, RuleBook
from saans.service import get_plan, parse_day


def args(**kw):
    md = MultiDict()
    for k, v in kw.items():
        for item in (v if isinstance(v, list) else [v]):
            md.add(k, item)
    return md


def test_no_profile_fields_means_no_profile():
    assert parse_profile(args(persona="rider", area="ito"), "rider") is None


def test_profile_parses_and_lowers_thresholds():
    p = parse_profile(args(age="67", cond=["asthma", "diabetes"], commute="bus", start="7", end="10", mask="1"), "older")
    assert (p.age, p.conditions, p.commute, p.start_hour, p.end_hour, p.mask) == (67, ("asthma", "diabetes"), "bus", 7, 10, True)
    assert p.sensitive and p.threshold_shift() == 100
    older = p.apply(PERSONAS["older"])
    assert (older.go_max, older.limit_max) == (50, 100) and older.hours() == [7, 8, 9]
    assert p.reasons() == ["over 60", "asthma", "diabetes"]


def test_healthy_adult_keeps_usual_thresholds():
    p = parse_profile(args(age="30", commute="metro"), "commuter")
    fitted = p.apply(PERSONAS["commuter"])
    assert not p.sensitive and (fitted.go_max, fitted.limit_max) == (PERSONAS["commuter"].go_max,
                                                                     PERSONAS["commuter"].limit_max)
    assert fitted.activity("morning_commute").rules_action == "travel_metro"  # judged by how they travel


def test_child_and_pregnancy_shift_by_50():
    assert parse_profile(args(age="9"), "school").threshold_shift() == 50
    assert parse_profile(args(cond="pregnant"), "commuter").threshold_shift() == 50


@pytest.mark.parametrize("bad", [
    {"age": "abc"}, {"age": "0"}, {"cond": "flu"}, {"commute": "rocket"},
    {"start": "7"}, {"start": "7", "end": "7"}, {"start": "25", "end": "3"},
])
def test_bad_profile_input(bad):
    with pytest.raises(ValueError):
        parse_profile(args(**bad), "rider")


def test_auto_day_opens_on_today_unless_an_evening_switch_is_set(monkeypatch):
    assert parse_day(None, FIXED_NOW) == "today"
    assert parse_day("", FIXED_NOW.replace(hour=23)) == "today"
    monkeypatch.setenv("TOMORROW_FROM_HOUR", "20")
    assert parse_day("", FIXED_NOW.replace(hour=21)) == "tomorrow"
    assert parse_day("today", FIXED_NOW.replace(hour=21)) == "today"


# Rules for the new personas and for sensitive groups

BOOK = RuleBook.from_dir()


@pytest.mark.parametrize("persona,activity,stage,sensitive,decision", [
    ("worker", "dusty_construction_work", 2, False, ALLOWED),
    ("worker", "dusty_construction_work", 3, False, NOT_ALLOWED),
    ("worker", "other_construction_work", 4, False, ALLOWED),
    ("worker", "other_construction_work", 4, True, ADVISED_AGAINST),
    ("worker", "outdoor_work_shift", 3, False, ALLOWED),
    ("worker", "outdoor_work_shift", 4, False, CHECK),
    ("commuter", "drive_private_car", 1, False, ALLOWED),
    ("commuter", "drive_private_car", 2, False, ADVISED_AGAINST),
    ("commuter", "drive_bs3_petrol_bs4_diesel_car", 3, False, NOT_ALLOWED),
    ("commuter", "office_attendance", 2, False, ALLOWED),
    ("commuter", "office_attendance", 3, False, CHECK),
    ("commuter", "morning_commute", 3, False, CHECK),
    ("commuter", "lunch_walk", 4, False, ADVISED_AGAINST),
    ("athlete", "outdoor_training", 3, False, ALLOWED),
    ("athlete", "outdoor_training", 4, False, ADVISED_AGAINST),
    ("rider", "outdoor_shift", 4, False, CHECK),
    ("rider", "outdoor_shift", 4, True, ADVISED_AGAINST),
    ("rider", "outdoor_shift", 3, True, ALLOWED),
])
def test_new_rules(persona, activity, stage, sensitive, decision):
    result = BOOK.evaluate(persona, activity, "ito", stage, sensitive)
    assert result.decision == decision
    if decision != CHECK:
        assert result.policy_id and result.clause


def test_profile_reaches_the_plan(mem_store, live_fetcher):
    p = parse_profile(args(age="45", cond="heart", commute="two_wheeler", mask="1"), "rider")
    plan = get_plan("rider", "ito", stage="IV", now=FIXED_NOW, fetcher=live_fetcher, profile=p)
    shift = next(a for a in plan["activities"] if a["id"] == "outdoor_shift")
    assert shift["rule"]["decision"] == ADVISED_AGAINST
    assert plan["profile"]["conditions"] == ["Heart disease or high blood pressure"]
    assert plan["thresholds"] == {"go_max": 100, "limit_max": 200}
    assert any("N95" in a for a in plan["actions"])
    assert plan["health"]["tips"] and plan["dates"]["today"] == "2026-10-10"
    facts = ai.plan_facts(plan)
    assert facts["profile"]["age"] == 45 and facts["actions"]


@pytest.mark.parametrize("persona", ["worker", "commuter", "athlete"])
def test_new_personas_plan(mem_store, live_fetcher, persona):
    plan = get_plan(persona, "ito", now=FIXED_NOW, fetcher=live_fetcher)
    assert plan["verdict"] and plan["hours"] and plan["actions"] is not None


def test_vehicle_keeps_only_its_own_rule():
    commuter = PERSONAS["commuter"]
    old = parse_profile(args(vehicle="car_old", commute="car"), "commuter").apply(commuter)
    ids = [a.id for a in old.activities]
    assert "drive_private_car" not in ids and ids.count("drive_bs3_petrol_bs4_diesel_car") == 1
    assert old.activity("morning_commute").rules_action == "drive_bs3_petrol_bs4_diesel_car"
    none = parse_profile(args(vehicle="none", commute="none"), "commuter").apply(commuter)
    assert not {a.id for a in none.activities} & {"drive_private_car", "drive_bs3_petrol_bs4_diesel_car",
                                                  "morning_commute", "evening_commute"}
    # An older person who drives an old car gets the car rule too, judged as written for commuters.
    older = parse_profile(args(vehicle="car_old"), "older").apply(PERSONAS["older"])
    car = older.activity("drive_bs3_petrol_bs4_diesel_car")
    assert car.rules_as == "commuter" and car.label.startswith("Driving your BS-III")
    with pytest.raises(ValueError):
        parse_profile(args(vehicle="spaceship"), "commuter")


def test_every_kind_of_day_has_a_label_keywords_and_an_ai_hint():
    from saans.personas import PERSONAS
    from saans.profile import WORK, WORK_KEYWORDS

    assert len(PERSONAS) >= 19 and set(WORK) == set(PERSONAS)
    assert set(PERSONAS) == {pid for pid, _ in WORK_KEYWORDS}
    assert all(p.ai_hint for p in PERSONAS.values())


@pytest.mark.parametrize("text, persona", [
    ("I am a student in nit delhi", "college"), ("Class 4 student, I walk to school", "school"),
    ("Retired teacher, I walk in the park", "older"), ("I drive an auto in Laxmi Nagar", "driver"),
    ("I sell chai from a stall", "vendor"), ("I work from home", "wfh"), ("Nurse at AIIMS", "healthcare"),
    ("Traffic police at ITO", "guard"), ("7 months pregnant", "pregnant"), ("Mother of a 2 year old baby", "young_child"),
    ("Factory worker in Okhla", "factory"), ("Safai karmchari", "sanitation"), ("Teacher at DPS", "teacher"),
    ("I run 10 km before work", "athlete"), ("Swiggy delivery rider at night", "rider"),
])
def test_keywords_pick_the_closer_kind_of_day(text, persona):
    assert guess_work(text) == persona


def test_role_line_is_tidy():
    assert tidy_role("I am a student in nit delhi") == "Student in NIT Delhi"
    assert tidy_role("traffic police at ito.") == "Traffic police at ITO"
