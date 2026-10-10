"""aqicn.org as the live backup for CPCB's station readings."""
from types import SimpleNamespace

from conftest import FIXED_NOW
from saans import data, waqi
from saans.service import get_plan

UPDATED = FIXED_NOW.strftime("%Y-%m-%d %H:00:00")


def feed(us_pm25=200, us_pm10=120, name="ITO, Delhi, India", geo=(28.6286, 77.2410), updated=UPDATED):
    return {"status": "ok", "data": {"aqi": us_pm25, "idx": 1, "dominentpol": "pm25",
                                      "city": {"name": name, "geo": list(geo)},
                                      "iaqi": {"pm25": {"v": us_pm25}, "pm10": {"v": us_pm10}, "t": {"v": 27}},
                                      "time": {"s": updated, "tz": "+05:30"}}}


class FakeSession:
    def __init__(self, body):
        self.body, self.calls = body, []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params})
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: self.body)


def test_us_scale_is_turned_back_into_india_aqi():
    assert round(waqi.us_to_concentration(200, "pm25"), 1) == 150.4
    r = waqi.reading_from_feed(feed(us_pm25=200))
    assert r["aqi"] == 324 and r["dominant"] == "PM2.5" and r["category"] == "Very Poor"  # 150 µg/m³ on India's scale
    assert waqi.reading_from_feed({"status": "error", "data": "Invalid key"}) is None


def test_token_goes_in_the_request_and_the_station_must_be_near_and_fresh(monkeypatch, mem_store):
    monkeypatch.setenv("WAQI_TOKEN", "tok")
    s = FakeSession(feed())
    ito = data.get_area("ito")
    r = waqi.nearest(ito, session=s)
    assert s.calls[0]["params"] == {"token": "tok"} and "geo:28.6286;77.241" in s.calls[0]["url"]
    hit = waqi.fresh_and_near(r, ito, FIXED_NOW)
    assert hit["short"] == "ITO" and hit["time"] == "09:00" and hit["via"] == "aqicn"
    assert waqi.fresh_and_near(r, data.get_area("dwarka"), FIXED_NOW) is None  # too far
    old = waqi.reading_from_feed(feed(updated="2026-10-09 20:00:00"))
    assert waqi.fresh_and_near(old, ito, FIXED_NOW) is None


def test_plan_uses_aqicn_when_data_gov_in_is_down(monkeypatch, mem_store, live_fetcher):
    monkeypatch.setenv("WAQI_TOKEN", "tok")
    monkeypatch.setattr(waqi, "nearest", lambda area, store=None, session=None: waqi.reading_from_feed(feed()))
    plan = get_plan("commuter", "ito", now=FIXED_NOW, fetcher=live_fetcher, day="today")
    assert plan["official"]["via"] == "aqicn" and plan["air_now"]["particles"]["aqi"] == 324
    assert plan["air_now"]["particles"]["via"] == "aqicn"
