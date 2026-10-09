from datetime import datetime

import pytest
from werkzeug.datastructures import MultiDict

from conftest import FIXED_NOW
from saans import ai, data
from saans.personas import PERSONAS
from saans.profile import parse_profile
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
    assert not p.sensitive and p.apply(PERSONAS["commuter"]) == PERSONAS["commuter"]


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


def test_auto_day_switches_to_tomorrow_in_the_evening():
    assert parse_day(None, FIXED_NOW) == "today"
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
