import json
from types import SimpleNamespace

import pytest

from saans import ai, data
from saans.service import get_plan
from saans.web import create_app


class FakeSession:
    def __init__(self, text="Go out at 14:00, when the AQI is lowest."):
        self.text, self.calls = text, []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(json)
        body = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": self.text}]}}]}
        return SimpleNamespace(status_code=200, json=lambda: body, text="")


@pytest.fixture
def plan(mem_store, monkeypatch, live_fetcher):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    return get_plan("commuter", "ito", stage="III", every_stage=True)


@pytest.fixture
def gemini_on(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")


def test_chat_sends_plan_question_and_trimmed_history(plan, gemini_on):
    s = FakeSession()
    history = [{"role": "user", "text": "hi"}, {"role": "assistant", "text": "Hello"}, {"role": "system", "text": "x"},
               "junk"] + [{"role": "user", "text": f"q{i}"} for i in range(10)]
    assert ai.chat(plan, "  When should I go out?  ", history, "hi", session=s) == "Go out at 14:00, when the AQI is lowest."
    sent = json.loads(s.calls[0]["contents"][0]["parts"][0]["text"])
    assert sent["question"] == "When should I go out?"
    assert len(sent["conversation"]) == 6 and all(t["role"] in ("user", "assistant") for t in sent["conversation"])
    facts = sent["plan"]
    assert len(facts["your_hours"]) == len(plan["hours"]) and facts["grap_stage"] and facts["time_now"]
    assert any(r["decision"] == "Not allowed" for r in facts["rules_today"])
    assert len(facts["hourly_aqi"]["today"]) == 24 and len(facts["hourly_aqi"]["tomorrow"]) == 24
    assert "Hindi" in s.calls[0]["systemInstruction"]["parts"][0]["text"]


def test_chat_rejects_empty_question_and_bad_language(plan, gemini_on):
    with pytest.raises(ValueError):
        ai.chat(plan, "   ", session=FakeSession())
    with pytest.raises(ValueError):
        ai.chat(plan, "hi", lang="fr", session=FakeSession())


def test_chat_route(mem_store, monkeypatch, live_fetcher, gemini_on):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    seen = []
    monkeypatch.setattr(ai, "chat", lambda plan, q, h, lang, look_up: seen.append((plan["area"]["id"], q, lang, bool(plan["stage_table"]))) or "Answer.\nNEXT: What about tomorrow? | Do I need a mask?")
    web = create_app().test_client()
    resp = web.post("/api/chat?persona=rider&area=okhla", json={"question": "Can I ride now?", "lang": "en"})
    assert resp.get_json() == {"answer": "Answer.", "follow_ups": ["What about tomorrow?", "Do I need a mask?"],
                               "by": "Google Gemini"} and seen == [("okhla", "Can I ride now?", "en", True)]
    assert web.post("/api/chat?persona=rider&area=okhla", json={"question": " "}).status_code == 400
    assert web.post("/api/chat?persona=pilot&area=okhla", json={"question": "x"}).status_code == 400
    monkeypatch.setattr(ai, "chat", lambda *a, **k: None)
    assert web.post("/api/chat?persona=rider&area=okhla", json={"question": "x"}).status_code == 502


def test_chat_is_off_without_a_model_and_shown_with_one(mem_store, monkeypatch, live_fetcher):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    web = create_app().test_client()
    assert web.post("/api/chat?persona=rider&area=ito", json={"question": "x"}).status_code == 503
    assert 'id="chat"' not in web.get("/plan?persona=rider&area=ito").get_data(as_text=True)
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    html = web.get("/plan?persona=rider&area=ito").get_data(as_text=True)
    assert 'id="chat"' in html and "Ask Saans" in html and "Ask about these rules" in html and 'data-chat="What should I do at' in html


def test_chat_knows_the_car_rules_at_every_stage(plan):
    rows = {r["what"]: r for r in ai.chat_facts(plan)["rules_at_every_stage"]}
    old = rows["Car: BS-III or older petrol, or BS-IV or older diesel"]["by_stage"]
    new = rows["Car: BS-VI, CNG, electric or BS-IV petrol"]["by_stage"]
    assert old["II"] == "Allowed" and old["III"] == "Not allowed" and new["III"] != "Not allowed"
    assert rows["Metro"]["by_stage"]["IV"] == "Allowed"
    assert all(r["rules"] for r in rows.values() if "Not allowed" in r["by_stage"].values())


def test_page_plans_skip_the_stage_table(mem_store, monkeypatch, live_fetcher):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    assert get_plan("commuter", "ito")["stage_table"] is None


class ScriptedSession(FakeSession):
    """Answers each call with the next text in turn."""
    def __init__(self, *texts):
        super().__init__()
        self.texts = list(texts)

    def post(self, url, json=None, headers=None, timeout=None):
        self.text = self.texts.pop(0)
        return super().post(url, json, headers, timeout)


def test_chat_looks_up_places_the_question_names(plan, gemini_on):
    s = ScriptedSession("PLACES: Noida, Uttar Pradesh; Atlantis", "Leave at 10:00; Noida is about AQI 160.\nNEXT: And coming back?")
    asked = []
    look_up = lambda names: asked.append(names) or [{"asked": "Noida, Uttar Pradesh", "found": "Noida", "aqi_now": 160},
                                                   {"asked": "Atlantis", "found": None}]
    answer = ai.chat(plan, "Taking my students to Noida by bus", session=s, look_up=look_up)
    assert asked == [["Noida, Uttar Pradesh", "Atlantis"]] and len(s.calls) == 2
    second = json.loads(s.calls[1]["contents"][0]["parts"][0]["text"])
    assert second["plan"]["places_asked"][0]["found"] == "Noida"
    assert ai.split_follow_ups(answer) == ("Leave at 10:00; Noida is about AQI 160.", ["And coming back?"])
    # Asking for places twice gives no answer rather than a marker line.
    assert ai.chat(plan, "Noida?", session=ScriptedSession("PLACES: Noida", "PLACES: Noida"), look_up=look_up) is None


def test_follow_ups_are_split_from_the_answer():
    assert ai.split_follow_ups("Go at 14:00.\n**NEXT:** A? | B? | C? | D?") == ("Go at 14:00.", ["A?", "B?", "C?"])
    assert ai.split_follow_ups("Just this.") == ("Just this.", [])
    assert ai.asked_places("Go at 14:00.") is None


def test_chat_facts_keep_only_rules_that_restrict(plan):
    facts = ai.chat_facts(plan)
    assert facts["rules_today"] and all(r["decision"] != "Allowed" for r in facts["rules_today"])
    assert facts["allowed_rest"] and facts["places_air"][0]["place"] == "ITO"


def test_asked_places_finds_air_without_the_ai(mem_store, monkeypatch, live_fetcher):
    from saans import service
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    out = service.asked_places(["Anand Vihar", "Nowhere at all"], store=mem_store)
    assert out[0]["found"] == "Anand Vihar" and len(out[0]["hourly_aqi"]["today"]) == 24 and out[0]["aqi_now"]
    assert out[1] == {"asked": "Nowhere at all", "found": None}
