import json
from types import SimpleNamespace

import pytest

from saans import ai, data
from saans.service import get_plan
from saans.web import create_app

NOVA = "apac.amazon.nova-lite-v1:0"


class FakeRuntime:
    def __init__(self, text=None, stop="end_turn", error=None):
        self.text, self.stop, self.error, self.calls = text, stop, error, []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"stopReason": self.stop, "output": {"message": {"content": [{"text": self.text}]}}}


@pytest.fixture
def nova(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL", NOVA)


@pytest.fixture
def plan(mem_store, monkeypatch, live_fetcher):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    return get_plan("rider", "ito", stage="III")


def test_model_choice_and_label(monkeypatch):
    assert ai.provider() is None and not ai.enabled()
    monkeypatch.setenv("BEDROCK_MODEL", "anthropic.claude-opus-5-5")
    assert ai.enabled() and ai.uses_messages_api() and ai.label() == "Claude on Amazon Bedrock"
    monkeypatch.setenv("BEDROCK_MODEL", NOVA)
    assert ai.enabled() and not ai.uses_messages_api() and ai.label() == "Amazon Nova on Bedrock"
    monkeypatch.setenv("BEDROCK_MODEL", "meta.llama3-70b")
    assert ai.label() == "Amazon Bedrock"
    monkeypatch.setenv("AI_PROVIDER", "off")
    assert not ai.enabled()


def test_converse_summary(plan, nova):
    rt = FakeRuntime(" Today: Stage III.\nDo this: take the metro. ")
    assert ai.summarize(plan, "hi", runtime=rt) == "Today: Stage III.\nDo this: take the metro."
    call = rt.calls[0]
    assert call["modelId"] == NOVA and "Hindi" in call["system"][0]["text"]
    assert "Not allowed" in call["messages"][0]["content"][0]["text"]


@pytest.mark.parametrize("rt", [
    FakeRuntime(error=RuntimeError("AccessDeniedException")),
    FakeRuntime("partial", stop="max_tokens"),
    FakeRuntime("blocked", stop="content_filtered"),
    FakeRuntime("   "),
])
def test_converse_failures_give_none(plan, nova, rt):
    assert ai.summarize(plan, runtime=rt) is None


def test_converse_reads_work_as_json(nova):
    rt = FakeRuntime(json.dumps({"persona": "worker", "start_hour": 22, "end_hour": 6}))
    assert ai.classify_work("Night guard", runtime=rt) == {"persona": "worker", "role": None, "start_hour": 22, "end_hour": 6}
    assert "JSON Schema" in rt.calls[0]["system"][0]["text"] and '"persona"' in rt.calls[0]["system"][0]["text"]
    fenced = FakeRuntime('```json\n{"persona": "rider", "start_hour": -1, "end_hour": -1}\n```')
    assert ai.classify_work("rider", runtime=fenced)["persona"] == "rider"
    assert ai.classify_work("x", runtime=FakeRuntime("not json")) is None


def test_converse_reads_route(nova):
    rt = FakeRuntime(json.dumps({"start": {"found": True, "lat": 28.67, "lon": 77.13},
                                 "destination": {"found": False, "lat": 0, "lon": 0}, "modes": ["bus", "plane"]}))
    out = ai.read_route("Paschim Vihar", "somewhere", "DTC bus", runtime=rt)
    assert out == {"start": (28.67, 77.13), "destination": None, "modes": ["bus"]}


def test_pages_name_the_bedrock_model(mem_store, monkeypatch, live_fetcher, nova):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    client = create_app().test_client()
    assert "Amazon Nova on Bedrock" not in client.get("/").get_data(as_text=True)  # no "made by" lines
    plan = client.get("/plan?persona=rider&area=ito").get_data(as_text=True)
    assert 'id="ai"' in plan and "Written by" not in plan
