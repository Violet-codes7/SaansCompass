import json
from types import SimpleNamespace

import pytest

from conftest import FIXED_NOW
from saans import ai, i18n
from saans.explain import POLICY, rule_text, stage_headline
from saans.personas import PERSONAS
from saans.profile import CONDITION_INFO, CONDITIONS, Profile, clean_job, guess_work
from saans.rules import default_rulebook
from saans.service import get_plan
from saans import data, web


@pytest.fixture
def client(mem_store, monkeypatch, live_fetcher):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    monkeypatch.delenv("BEDROCK_MODEL", raising=False)
    return web.create_app().test_client()


# Health conditions

def test_every_condition_has_full_advice():
    assert len(CONDITIONS) >= 15
    for c in CONDITION_INFO.values():
        assert c.why and c.tip and c.watch and c.short and c.shift in (0, 50, 100)


@pytest.mark.parametrize("cond,shift,charter", [
    ("bronchitis", 100, True), ("stroke", 100, True), ("covid", 100, True), ("tb", 100, True),
    ("allergic_rhinitis", 50, True), ("kidney", 50, True), ("anaemia", 50, True),
    ("smoker", 50, False), ("eyes", 0, False),
])
def test_condition_effects(cond, shift, charter):
    p = Profile(work="commuter", conditions=(cond,))
    assert p.threshold_shift() == shift and p.sensitive is charter
    assert p.apply(PERSONAS["commuter"]).sensitive is charter
    assert p.health()["details"][0]["title"] == CONDITIONS[cond]


def test_smoker_gets_lower_limits_but_not_the_stage4_charter(mem_store, live_fetcher):
    plan = get_plan("commuter", "ito", stage="IV", now=FIXED_NOW, fetcher=live_fetcher,
                    profile=Profile(work="commuter", conditions=("smoker",)))
    assert plan["thresholds"]["go_max"] == 100 and plan["health"]["level"] == "higher"
    assert all(r["policy_id"] != "charter.sensitive_groups.stage4" for r in plan["rules"])


def test_stroke_history_brings_in_the_charter(mem_store, live_fetcher):
    plan = get_plan("commuter", "ito", stage="IV", now=FIXED_NOW, fetcher=live_fetcher,
                    profile=Profile(work="commuter", conditions=("stroke",)))
    assert plan["health"]["level"] == "highest" and plan["health"]["charter"]
    walk = next(a for a in plan["activities"] if a["id"] == "lunch_walk")
    assert walk["rule"]["decision"] == "advised_against"


# Plain-language rules and stage wording

def test_every_policy_is_explained():
    ids = {p.id for p in default_rulebook().policies.values()}
    assert ids == set(POLICY)
    for text in POLICY.values():
        assert text["means"] and text["why"]


def test_uncovered_activity_never_reads_as_allowed():
    x = rule_text("office_attendance", {"decision": "check_official_order", "policy_id": None})
    assert "allowed" not in x["means"].lower().replace("not allowed", "")
    assert "Check" in x["do"]


@pytest.mark.parametrize("stage,value,cat,title,sub", [
    (0, 80, "Satisfactory", "No GRAP stage today", "Delhi's air is Satisfactory. GRAP starts at AQI 201."),
    (0, 195, "Moderate", "No GRAP stage today", "6 points below Stage I, which starts at AQI 201"),
    (3, 420, "Severe", "Stage III: Severe air", "dusty construction"),
])
def test_stage_headline(stage, value, cat, title, sub):
    h = stage_headline(stage, value, cat)
    assert h["title"] == title and sub in h["sub"]
    assert stage_headline(0, 150, "Moderate", "tomorrow")["title"] == "No GRAP stage tomorrow"


def test_plan_page_explains_rules_and_glance(client):
    html = client.get("/plan?persona=worker&area=ito&stage=III&day=today").get_data(as_text=True)
    assert "What it means for you:" in html and "Dusty construction work" in html
    assert "Official source" in html and "worker.dusty_cnd.stage3" in html
    assert "You are here" in html and "Stage III: Severe air" in html
    for label in ("At a glance in ITO", "AQI in ITO", "Worst time", "Your limits", "like smoking", "What to do today"):
        assert label in html
    html0 = client.get("/plan?persona=commuter&area=ito&stage=0&day=today").get_data(as_text=True)
    assert "No GRAP stage today" in html0 and ">None<" not in html0


def test_health_panel_lists_each_condition(client):
    html = client.get("/plan?persona=commuter&area=ito&cond=kidney&cond=eyes&age=64").get_data(as_text=True)
    assert "Kidney disease" in html and "Eye irritation" in html and "Age 64: over 60" in html
    assert "Watch for:" in html and "Call 112 now." in html and "If you feel unwell" in html


# What do you do: own words

@pytest.mark.parametrize("text,persona", [
    ("I deliver food for Swiggy on a scooter", "rider"),
    ("Mason on a building site in Rohini", "worker"),
    ("Class 4 student", "school"),
    ("Retired teacher who walks every morning", "older"),
    ("I train for marathons", "athlete"),
    ("Software engineer, I drive to Gurugram", "commuter"),
    ("मैं डिलीवरी करता हूँ", "rider"),
])
def test_keyword_fallback(text, persona):
    assert guess_work(text) == persona


def test_keyword_fallback_gives_up_on_nonsense():
    assert guess_work("blah") is None
    assert clean_job("  a\tb \x00 c ") == "a b c" and len(clean_job("x" * 500)) == 160


class FakeMessages:
    def __init__(self, text):
        self.text, self.calls = text, []

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=self.text)])


def test_classify_work_with_claude(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL", "anthropic.claude-opus-5-5")
    msgs = FakeMessages(json.dumps({"persona": "guard", "role": "night security guard at a mall.", "start_hour": 22, "end_hour": 6}))
    out = ai.classify_work("Night security guard at a mall", client=SimpleNamespace(messages=msgs))
    assert out == {"persona": "guard", "role": "Night security guard at a mall", "start_hour": 22, "end_hour": 6}
    assert msgs.calls[0]["output_config"]["format"]["type"] == "json_schema"
    bad = FakeMessages(json.dumps({"persona": "pilot", "start_hour": -1, "end_hour": -1}))
    assert ai.classify_work("x", client=SimpleNamespace(messages=bad)) is None
    unknown_hours = FakeMessages(json.dumps({"persona": "rider", "start_hour": -1, "end_hour": -1}))
    assert ai.classify_work("x", client=SimpleNamespace(messages=unknown_hours))["start_hour"] is None


def test_classify_work_is_off_without_bedrock(monkeypatch):
    monkeypatch.delenv("BEDROCK_MODEL", raising=False)
    assert ai.classify_work("rider") is None


def test_job_box_redirects_to_a_reading_you_can_correct(client, monkeypatch):
    monkeypatch.setattr(web, "_work_cache", {})
    resp = client.get("/plan?job=Zomato+rider&area=ito&age=30")
    assert resp.status_code == 302
    loc = resp.headers["Location"]
    assert "persona=rider" in loc and "read=keywords" in loc and "job=Zomato" in loc
    html = client.get(loc).get_data(as_text=True)
    assert "role=Zomato+rider" in loc
    assert "We read you as" not in html and "Delivery or gig rider" in html and 'class="role"' not in html
    assert '<details class="fix"' in html and "Change" in html
    assert 'name="read" value="picked"' in html and 'name="job" value="Zomato rider"' in html


def test_claude_reading_sets_hours_when_given(client, monkeypatch):
    monkeypatch.setattr(web, "_work_cache", {})
    monkeypatch.setattr(ai, "classify_work", lambda text: {"persona": "worker", "start_hour": 22, "end_hour": 6})
    loc = client.get("/plan?job=Night+guard&area=ito").headers["Location"]
    assert "read=ai" in loc and "start=22" in loc and "end=6" in loc
    # Hours the person chose themselves win.
    monkeypatch.setattr(web, "_work_cache", {})
    loc = client.get("/plan?job=Night+guard&area=ito&start=20&end=23").headers["Location"]
    assert "start=20" in loc and "start=22" not in loc


def test_job_text_is_not_logged(client, caplog, monkeypatch):
    monkeypatch.setattr(web, "_work_cache", {})
    caplog.set_level("INFO")
    client.get("/plan?persona=rider&area=ito&job=secret+words+here")
    assert "secret" not in caplog.text


# Hindi

def test_builtin_hindi_keeps_punctuation():
    assert i18n.builtin("At a glance") == "एक नज़र में"
    assert i18n.builtin(" · Moderate") == " · मध्यम"
    assert i18n.builtin("Something new") is None


class FakeTranslate:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, 0

    def translate_text(self, Text, SourceLanguageCode, TargetLanguageCode):
        self.calls += 1
        if self.fail:
            raise RuntimeError("AccessDenied")
        return {"TranslatedText": "\n".join("HI:" + line for line in Text.split("\n"))}


def test_to_hindi_uses_dictionary_then_translate(monkeypatch):
    monkeypatch.setattr(i18n, "_cache", {})
    monkeypatch.setattr(i18n, "_state", {"paused_until": 0.0})
    fake = FakeTranslate()
    out, source = i18n.to_hindi(["Your health", "Keep windows shut.", "Keep  windows\n shut."], client=fake, now=0)
    assert out == ["आपकी सेहत", "HI:Keep windows shut.", "HI:Keep windows shut."] and source is True
    assert fake.calls == 1
    i18n.to_hindi(["Keep windows shut."], client=fake, now=0)
    assert fake.calls == 1  # cached in memory


def test_to_hindi_falls_back_and_pauses_after_a_failure(monkeypatch):
    monkeypatch.setattr(i18n, "_cache", {})
    monkeypatch.setattr(i18n, "_state", {"paused_until": 0.0})
    fake = FakeTranslate(fail=True)
    out, source = i18n.to_hindi(["Your health", "Other text"], client=fake, now=100)
    assert out == ["आपकी सेहत", "Other text"] and source is False
    i18n.to_hindi(["Other text"], client=fake, now=200)
    assert fake.calls == 1


def test_translate_api(client, monkeypatch):
    monkeypatch.delenv("TRANSLATE", raising=False)
    body = client.post("/api/translate", json={"to": "hi", "texts": ["Today", "Unknown words"]}).get_json()
    assert body == {"texts": ["आज", "Unknown words"], "complete": False}
    assert client.post("/api/translate", json={"to": "hi", "texts": ["Today"]}).get_json()["complete"] is True
    assert client.post("/api/translate", json={"to": "fr", "texts": []}).status_code == 400
    assert client.post("/api/translate", json={"to": "hi", "texts": ["x"] * 401}).status_code == 400


def test_pages_have_the_language_switch(client):
    html = client.get("/").get_data(as_text=True)
    assert 'data-setlang="hi"' in html and "i18n.js" in html


def test_glance_is_about_the_area_and_groups_what_to_do(mem_store, live_fetcher):
    from saans.profile import parse_profile
    from werkzeug.datastructures import MultiDict
    p = parse_profile(MultiDict({"cond": "asthma", "age": "45", "commute": "auto"}), "commuter")
    plan = get_plan("commuter", "ito", now=FIXED_NOW, fetcher=live_fetcher, profile=p, modes=["auto"])
    g = plan["glance"]
    assert g["title"] == "At a glance in ITO" and g["area"]["aqi"] == plan["air"]["day_aqi"]
    assert g["area"]["note"] and "Delhi's average" in g["area"]["vs_delhi"]
    keys = [grp["key"] for grp in g["todo"]]
    assert keys[0] == "rules" and {"timing", "travel", "protect", "home", "health"} <= set(keys)
    health = next(grp for grp in g["todo"] if grp["key"] == "health")["items"]
    assert any("inhaler" in item for item in health)
    assert {m["key"] for m in g["moments"]} >= {"best", "worst", "set_out"}
    assert g["health"]["today"].startswith("ITO's AQI")


def test_commute_over_the_limit_is_not_a_normal_day(mem_store):
    from conftest import make_hours
    # Clean all day except the 09:00 and 18:00 commutes.
    hours = [30] * 24
    hours[9] = hours[18] = 90
    plan = get_plan("commuter", "ito", now=FIXED_NOW, fetcher=lambda a: make_hours(hours))
    assert plan["verdict"] == "limit"
