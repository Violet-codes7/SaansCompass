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
    return get_plan("commuter", "ito", stage="III")


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
    assert len(sent["plan"]["hours"]) == len(plan["hours"]) and sent["plan"]["grap_stage"]
    assert any(r["decision"] == "Not allowed" for r in sent["plan"]["rule_details"])
    assert "Hindi" in s.calls[0]["systemInstruction"]["parts"][0]["text"]


def test_chat_rejects_empty_question_and_bad_language(plan, gemini_on):
    with pytest.raises(ValueError):
        ai.chat(plan, "   ", session=FakeSession())
    with pytest.raises(ValueError):
        ai.chat(plan, "hi", lang="fr", session=FakeSession())


def test_chat_route(mem_store, monkeypatch, live_fetcher, gemini_on):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    seen = []
    monkeypatch.setattr(ai, "chat", lambda plan, q, h, lang: seen.append((plan["area"]["id"], q, lang)) or "Answer.")
    web = create_app().test_client()
    resp = web.post("/api/chat?persona=rider&area=okhla", json={"question": "Can I ride now?", "lang": "en"})
    assert resp.get_json() == {"answer": "Answer.", "by": "Google Gemini"} and seen == [("okhla", "Can I ride now?", "en")]
    assert web.post("/api/chat?persona=rider&area=okhla", json={"question": " "}).status_code == 400
    assert web.post("/api/chat?persona=pilot&area=okhla", json={"question": "x"}).status_code == 400
    monkeypatch.setattr(ai, "chat", lambda *a: None)
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
