"""GRAP switched off (grap_enabled false, the deployed default): no stage, no rules, no GRAP text."""
import pytest

from conftest import FIXED_NOW
from saans import ai, data, web
from saans.service import get_plan


@pytest.fixture(autouse=True)
def grap_off(monkeypatch):
    monkeypatch.setenv("GRAP_ENABLED", "false")


@pytest.fixture
def client(mem_store, monkeypatch, live_fetcher):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    return web.create_app().test_client()


def test_plan_has_no_stage_or_rules(mem_store, live_fetcher):
    plan = get_plan("commuter", "ito", day="today", now=FIXED_NOW, store=mem_store, fetcher=live_fetcher,
                    every_stage=True)
    assert plan["grap_applies"] is False and not any(a["rule"] for a in plan["activities"])
    assert plan["stage_table"] is None and set(live_fetcher.calls) == {"ito"}
    facts = ai.chat_facts(plan)
    assert "grap_stage" not in facts and facts["grap_applies"] is False and not facts["rules_today"]


@pytest.mark.parametrize("path", ["/", "/plan?persona=commuter&area=ito&route_read=picked&day=today",
                                  "/poster?persona=commuter&area=ito&route_read=picked&day=today"])
def test_pages_do_not_mention_grap(client, path):
    html = client.get(path).get_data(as_text=True)
    assert "GRAP" not in html and "CAQM" not in html and "Stage I" not in html
