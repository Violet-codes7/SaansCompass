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
    s = FakeSession(body=answer(json.dumps({"persona": "college", "role": "student at nit delhi", "start_hour": 22, "end_hour": 6})))
    assert ai.classify_work("I am a student in nit delhi", session=s) == {
        "persona": "college", "role": "Student at NIT Delhi", "start_hour": 22, "end_hour": 6}
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
    assert "Google Gemini" not in client.get("/").get_data(as_text=True)  # no "made by" lines
    plan = client.get("/plan?persona=rider&area=ito").get_data(as_text=True)
    assert 'id="ai"' in plan and "Written by" not in plan


def test_busy_gemini_is_tried_again_once(plan, gemini_on, monkeypatch):
    monkeypatch.setattr(ai.time, "sleep", lambda s: None)

    class Busy(FakeSession):
        def post(self, url, json=None, headers=None, timeout=None):
            self.calls.append(json)
            if len(self.calls) == 1:
                return SimpleNamespace(status_code=503, json=lambda: {}, text="")
            return SimpleNamespace(status_code=200, json=lambda: answer("Today: fine."), text="")
    s = Busy()
    assert ai.summarize(plan, session=s) == "Today: fine." and len(s.calls) == 2


def test_failure_reason_is_reported_without_the_key(mem_store, monkeypatch, live_fetcher, gemini_on):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    monkeypatch.setattr(ai.time, "sleep", lambda s: None)
    body = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded"}}
    monkeypatch.setattr(ai.requests, "post", lambda *a, **k: SimpleNamespace(status_code=429, json=lambda: body, text=""))
    resp = create_app().test_client().get("/api/summary?persona=rider&area=ito")
    assert resp.status_code == 502 and "reason" not in resp.get_json()  # shown in the logs only
    reason = ai.last_error()
    assert "429" in reason and "RESOURCE_EXHAUSTED" in reason and "test-key" not in reason


class Quota(FakeSession):
    """Out of quota (429) on the first `full` models, then an answer."""
    def __init__(self, full=1, missing=()):
        super().__init__()
        self.full, self.missing = full, missing

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(url)
        if any(m in url for m in self.missing):
            return SimpleNamespace(status_code=404, json=lambda: {}, text="")
        if len(self.calls) <= self.full:
            return SimpleNamespace(status_code=429, json=lambda: {"error": {"status": "RESOURCE_EXHAUSTED"}}, text="")
        return SimpleNamespace(status_code=200, json=lambda: answer("Today: fine."), text="")


def test_out_of_quota_hands_over_to_the_lighter_model(plan, gemini_on):
    s = Quota(full=1)
    assert ai.summarize(plan, session=s) == "Today: fine."
    assert "gemini-flash-latest" in s.calls[0] and "gemini-flash-lite-latest" in s.calls[1]
    s2 = Quota(full=0)
    ai.summarize(plan, session=s2)  # the full model rests; the light one is asked first
    assert len(s2.calls) == 1 and "gemini-flash-lite-latest" in s2.calls[0]


def test_resting_model_is_asked_again_later(gemini_on, monkeypatch):
    ai._resting["gemini-flash-latest"] = 1000.0
    assert ai.gemini_models(now=1010.0) == ["gemini-flash-lite-latest"]
    assert ai.gemini_models(now=1061.0) == ["gemini-flash-latest", "gemini-flash-lite-latest"]
    ai._resting["gemini-flash-lite-latest"] = 1000.0
    assert ai.gemini_models(now=1010.0) == ["gemini-flash-latest", "gemini-flash-lite-latest"]  # all resting: try anyway


def test_unknown_fallback_model_is_skipped(plan, gemini_on, monkeypatch):
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", '["gone-model", "gemini-flash-lite-latest"]')
    s = Quota(full=1, missing=("gone-model",))
    assert ai.summarize(plan, session=s) == "Today: fine." and len(s.calls) == 3
