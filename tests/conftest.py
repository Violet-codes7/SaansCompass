from datetime import datetime

import pytest

from saans import data, store
from saans.data import IST

REAL_FETCH = data.fetch_open_meteo
FIXED_NOW = datetime(2026, 10, 10, 9, 0, tzinfo=IST)


def make_hours(pm25_by_hour, days=3, start=FIXED_NOW):
    """Forecast hours in Open-Meteo's shape; pm25_by_hour is 24 values (None allowed)."""
    base = start.replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    from datetime import timedelta
    for d in range(days):
        for h, v in enumerate(pm25_by_hour):
            t = base + timedelta(days=d, hours=h)
            out.append({"time": t.strftime("%Y-%m-%dT%H:%M"), "pm25": v, "pm10": None if v is None else v * 1.5})
    return out


@pytest.fixture
def mem_store():
    s = store.MemoryStore()
    store.set_store(s)
    yield s
    store.set_store(None)


@pytest.fixture
def live_fetcher():
    """A fake Open-Meteo: clean afternoon, dirty night."""
    profile = [200] * 7 + [180, 150, 120, 90, 60, 40, 30, 30, 45, 70, 110, 160, 190, 210, 220, 220, 210]
    calls = []

    def fetch(area):
        calls.append(area.id)
        return make_hours(profile)

    fetch.calls = calls
    return fetch


@pytest.fixture
def failing_fetcher():
    def fetch(area):
        raise TimeoutError("no network")
    return fetch


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("tests must not call the real Open-Meteo API")
    monkeypatch.setattr(data, "fetch_open_meteo", boom)
    from saans import weather
    monkeypatch.setattr(weather, "fetch_weather", boom)
    # No AI model unless a test turns one on.
    from saans import ai
    for name in ("AI_PROVIDER", "BEDROCK_MODEL", "GEMINI_API_KEY", "GEMINI_KEY_PARAM", "GEMINI_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(ai, "_key_cache", {"at": -1e9, "value": None})
    monkeypatch.setattr(ai, "_resting", {})
    # No CPCB feed unless a test turns one on.
    from saans import cpcb
    for name in ("DATAGOV_API_KEY", "DATAGOV_KEY_PARAM"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cpcb, "_key_cache", {"at": -1e18, "value": None})
    monkeypatch.setattr(cpcb, "_memo", {"at": -1e18, "value": None})

    class NoBedrock:
        def converse(self, **kw):
            raise AssertionError("tests must not call the real Bedrock API")
    monkeypatch.setattr(ai, "_runtime", NoBedrock())
