import json
from types import SimpleNamespace

import pytest
import requests

from saans import ai, data
from saans.service import get_plan
from saans.web import create_app


class FakeSession:
    def __init__(self, status=200, body=None, error=None):
        self.status, self.body, self.error, self.calls = status, body, error, []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        if self.error:
            raise self.error
        return SimpleNamespace(status_code=self.status, json=lambda: self.body, text="error text")


def answer(text, finish="STOP"):
    return {"candidates": [{"finishReason": finish, "content": {"parts": [{"text": text}]}}]}


@pytest.fixture
def gemini_on(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")


@pytest.fixture
def plan(mem_store, monkeypatch, live_fetcher):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    return get_plan("rider", "ito", stage="III")


def test_provider_choice(monkeypatch):
    assert ai.provider() is None and not ai.enabled()
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    assert ai.provider() == "gemini" and not ai.enabled()  # no key yet
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert ai.enabled() and ai.label() == "Google Gemini"
    monkeypatch.setenv("AI_PROVIDER", "off")
    assert not ai.enabled()


def test_gemini_summary(plan, gemini_on):
    s = FakeSession(body=answer(" Today: Stage III.\nDo this: take the metro. "))
    assert ai.summarize(plan, "hi", session=s) == "Today: Stage III.\nDo this: take the metro."
    call = s.calls[0]
    assert call["headers"] == {"x-goog-api-key": "test-key"} and "gemini-flash-latest" in call["url"]
    assert "Hindi" in call["json"]["systemInstruction"]["parts"][0]["text"]
    assert "Not allowed" in call["json"]["contents"][0]["parts"][0]["text"]


@pytest.mark.parametrize("session", [
    FakeSession(status=403, body={}),
    FakeSession(body={"candidates": []}),
    FakeSession(body=answer("partial", finish="SAFETY")),
    FakeSession(error=requests.ConnectionError()),
])
def test_gemini_failures_give_none(plan, gemini_on, session):
    assert ai.summarize(plan, session=session) is None


def test_gemini_reads_work(gemini_on):
    s = FakeSession(body=answer(json.dumps({"persona": "worker", "start_hour": 22, "end_hour": 6})))
    assert ai.classify_work("Night guard", session=s) == {"persona": "worker", "start_hour": 22, "end_hour": 6}
    cfg = s.calls[0]["json"]["generationConfig"]
    assert cfg["responseMimeType"] == "application/json" and "persona" in cfg["responseSchema"]["properties"]
    fenced = FakeSession(body=answer('```json\n{"persona": "rider", "start_hour": -1, "end_hour": -1}\n```'))
    assert ai.classify_work("rider", session=fenced)["persona"] == "rider"
    assert ai.classify_work("x", session=FakeSession(body=answer("not json"))) is None


def test_key_comes_from_parameter_store(monkeypatch):
    monkeypatch.setenv("GEMINI_KEY_PARAM", "/saans-compass/gemini-api-key")
    calls = []

    def get_parameter(Name, WithDecryption):
        calls.append((Name, WithDecryption))
        return {"Parameter": {"Value": "secret"}}

    assert ai._gemini_key(ssm=SimpleNamespace(get_parameter=get_parameter), now=0) == "secret"
    assert calls == [("/saans-compass/gemini-api-key", True)]

    def missing(**kw):
        raise RuntimeError("ParameterNotFound")

    assert ai._gemini_key(ssm=SimpleNamespace(get_parameter=missing), now=1) is None


def test_pages_name_gemini(mem_store, monkeypatch, live_fetcher, gemini_on):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    client = create_app().test_client()
    assert "Google Gemini reads this" in client.get("/").get_data(as_text=True)
    assert "Written by Google Gemini" in client.get("/plan?persona=rider&area=ito").get_data(as_text=True)
