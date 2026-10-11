import io
import json
from types import SimpleNamespace

import anthropic
import httpx2 as httpx
import pytest

from saans import ai, data, stage
from saans import aqi as aqi_mod
from saans.service import get_plan
from saans.web import create_app


class FakeMessages:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.reply


def message(text, stop_reason="end_turn"):
    blocks = [SimpleNamespace(type="thinking", thinking="..."), SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


def fake_client(**kw):
    return SimpleNamespace(messages=FakeMessages(**kw))


@pytest.fixture
def plan(mem_store, monkeypatch, live_fetcher):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    return get_plan("rider", "ito", stage="III")


def test_summary_uses_plan_facts_only(plan):
    client = fake_client(reply=message(" Leave at 6 am. Older cars are not allowed. "))
    assert ai.summarize(plan, "en", client=client) == "Leave at 6 am. Older cars are not allowed."
    call = client.messages.calls[0]
    assert "English" in call["system"] and call["output_config"] == {"effort": "low"}
    assert "Not allowed" in call["messages"][0]["content"]


def test_summary_gives_each_aqi_its_band_and_corrects_a_wrong_one(plan):
    client = fake_client(reply=message("Today: Delhi is at AQI 218 (moderate), so keep rides short."))
    assert ai.summarize(plan, "en", client=client) == "Today: Delhi is at AQI 218 (poor), so keep rides short."
    facts = json.loads(client.messages.calls[0]["messages"][0]["content"])
    day = facts["day_aqi"]
    assert day["band"] == aqi_mod.category(day["aqi"]) and facts["delhi_aqi"]["band"] == aqi_mod.category(facts["delhi_aqi"]["aqi"])
    assert [b["band"] for b in facts["aqi_bands"]] == ["Good", "Satisfactory", "Moderate", "Poor", "Very Poor", "Severe"]
    assert "AQI bands" in client.messages.calls[0]["system"]


def test_summary_in_hindi(plan):
    client = fake_client(reply=message("सुबह 6 बजे निकलें।"))
    assert ai.summarize(plan, "hi", client=client) == "सुबह 6 बजे निकलें।"
    assert "Hindi" in client.messages.calls[0]["system"]


def test_refusal_and_empty_give_none(plan):
    assert ai.summarize(plan, client=fake_client(reply=message("x", "refusal"))) is None
    assert ai.summarize(plan, client=fake_client(reply=message("   "))) is None


def test_bedrock_errors_give_none(plan):
    req = httpx.Request("POST", "https://bedrock")
    err = anthropic.APIStatusError("denied", response=httpx.Response(403, request=req), body=None)
    assert ai.summarize(plan, client=fake_client(error=err)) is None
    assert ai.summarize(plan, client=fake_client(error=anthropic.APIConnectionError(request=req))) is None


def test_bad_language_rejected(plan):
    with pytest.raises(ValueError):
        ai.summarize(plan, "fr", client=fake_client(reply=message("x")))


def test_cache_key_changes_with_language_and_stage(plan, mem_store, monkeypatch, live_fetcher):
    other = get_plan("rider", "ito", stage="IV")
    assert ai.cache_key(plan, "en") != ai.cache_key(plan, "hi")
    assert ai.cache_key(plan, "en") != ai.cache_key(other, "en")


def test_speak_returns_data_url():
    polly = SimpleNamespace(synthesize_speech=lambda **kw: {"AudioStream": io.BytesIO(b"mp3")})
    assert ai.speak("hello", "hi", client=polly) == "data:audio/mpeg;base64,bXAz"


def test_speak_failure_gives_none():
    def boom(**kw):
        raise RuntimeError("AccessDenied")
    assert ai.speak("hello", client=SimpleNamespace(synthesize_speech=boom)) is None


# web routes

@pytest.fixture
def web(mem_store, monkeypatch, live_fetcher):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    monkeypatch.setenv("BEDROCK_MODEL", "anthropic.claude-opus-5-5")
    return create_app().test_client()


def test_summary_route_disabled_without_model(web, monkeypatch):
    monkeypatch.delenv("BEDROCK_MODEL")
    assert web.get("/api/summary?persona=rider&area=ito").status_code == 503
    assert 'id="ai"' not in web.get("/plan?persona=rider&area=ito").get_data(as_text=True)


def test_summary_route_and_cache(web, monkeypatch):
    calls = []
    monkeypatch.setattr(ai, "summarize", lambda plan, lang: calls.append(lang) or "Short summary.")
    for _ in range(2):
        body = web.get("/api/summary?persona=rider&area=ito&lang=hi").get_json()
        assert body == {"summary": "Short summary.", "lang": "hi", "by": "Claude on Amazon Bedrock"}
    assert calls == ["hi"]
    assert 'id="ai"' in web.get("/plan?persona=rider&area=ito").get_data(as_text=True)


def test_summary_route_errors(web, monkeypatch):
    monkeypatch.setattr(ai, "summarize", lambda plan, lang: None)
    assert web.get("/api/summary?persona=rider&area=ito&lang=fr").status_code == 400
    assert web.get("/api/summary?persona=pilot&area=ito").status_code == 400
    assert web.get("/api/summary?persona=rider&area=ito").status_code == 502


def test_speak_route(web, monkeypatch):
    monkeypatch.setattr(ai, "summarize", lambda plan, lang: "Hello.")
    monkeypatch.setattr(ai, "speak", lambda text, lang: "data:audio/mpeg;base64,AA==")
    body = web.get("/api/speak?persona=older&area=ito").get_json()
    assert body == {"audio": "data:audio/mpeg;base64,AA==", "text": "Hello."}


# declared stage from Parameter Store

class FakeSSM:
    def __init__(self, value=None, error=None):
        self.value, self.error = value, error

    def get_parameter(self, Name):
        if self.error:
            raise self.error
        return {"Parameter": {"Value": self.value}}


@pytest.mark.parametrize("raw,expected", [("unset", None), ("III", 3), (" iv ", 4), ("0", 0), ("banana", None)])
def test_declared_stage_values(monkeypatch, raw, expected):
    monkeypatch.setenv("OFFICIAL_STAGE_PARAM", "/saans-compass/official-stage")
    assert stage.declared_stage(ssm=FakeSSM(raw)) == expected


def test_declared_stage_off_or_failing(monkeypatch):
    monkeypatch.delenv("OFFICIAL_STAGE_PARAM", raising=False)
    assert stage.declared_stage(ssm=FakeSSM("III")) is None
    monkeypatch.setenv("OFFICIAL_STAGE_PARAM", "/x")
    assert stage.declared_stage(ssm=FakeSSM(error=RuntimeError("no access"))) is None


def test_declared_stage_is_cached(monkeypatch):
    monkeypatch.setenv("OFFICIAL_STAGE_PARAM", "/x")
    monkeypatch.setattr(stage, "_declared_cache", {"at": 1000.0, "value": 2})
    assert stage.declared_stage(now=1100.0) == 2


def test_resolve_stage_priority():
    assert stage.resolve_stage(480, official=1, declared=3)["source"] == "official"
    got = stage.resolve_stage(480, declared=3)
    assert (got["stage"], got["source"]) == (3, "declared")
    assert stage.resolve_stage(480)["source"] == "estimate"


def test_declared_stage_reaches_today_plan(mem_store, monkeypatch, live_fetcher):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    monkeypatch.setattr("saans.service.declared_stage", lambda: 4)
    today = get_plan("school", "ito")
    assert (today["stage"]["label"], today["stage"]["source"]) == ("IV", "declared")
    assert get_plan("school", "ito", day="tomorrow")["stage"]["source"] == "estimate"


def test_store_text_expires(mem_store):
    mem_store.put_text("AI#k", "hi", ttl_seconds=60, now=1000)
    assert mem_store.get_text("AI#k", now=1059) == "hi"
    assert mem_store.get_text("AI#k", now=1061) is None
