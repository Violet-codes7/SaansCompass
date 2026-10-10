"""CPCB's live station AQI from the data.gov.in feed."""
from types import SimpleNamespace

import pytest

from conftest import FIXED_NOW
from saans import cpcb, data
from saans.service import get_plan

UPDATED = FIXED_NOW.strftime("%d-%m-%Y %H:00:00")


def rec(station, pollutant, avg, lat=None, lon=None, updated=UPDATED, key="avg_value"):
    r = {"country": "India", "state": "Delhi", "city": "Delhi", "station": station, "last_update": updated,
         "pollutant_id": pollutant, key: str(avg)}
    if lat is not None:
        r.update(latitude=str(lat), longitude=str(lon))
    return r


def station(name, lat, lon, pm25, pm10=100, no2=40, **kw):
    return [rec(name, "PM2.5", pm25, lat, lon, **kw), rec(name, "PM10", pm10, lat, lon, **kw),
            rec(name, "NO2", no2, lat, lon, **kw), rec(name, "OZONE", 30, lat, lon, **kw)]


def delhi_records(ito_pm25=312):
    out = station("ITO, Delhi - CPCB", 28.6286, 77.2410, ito_pm25)
    for k, a in enumerate(data.AREAS.values()):
        if a.id != "ito":
            out += station(f"{a.name}, Delhi - DPCC", a.lat + 0.001, a.lon, 200 + k)
    out += station("Far Away, Delhi - DPCC", 28.9, 77.0, 150)
    return out


class FakeSession:
    def __init__(self, records=None, status=200):
        self.records, self.status, self.calls = records, status, []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params})

        def raise_for_status():
            if self.status >= 400:
                raise RuntimeError(f"HTTP {self.status}")
        return SimpleNamespace(raise_for_status=raise_for_status, json=lambda: {"records": self.records})


@pytest.fixture
def feed_on(monkeypatch):
    monkeypatch.setenv("DATAGOV_API_KEY", "test-key")


def test_station_aqi_is_the_highest_sub_index():
    s = cpcb.stations_from_records(station("ITO, Delhi - CPCB", 28.6, 77.2, 312, pm10=250))
    assert s[0]["aqi"] == 312 and s[0]["dominant"] == "PM2.5" and s[0]["category"] == "Very Poor"


def test_older_field_names_are_read_too():
    recs = [rec("Rohini, Delhi - DPCC", p, v, key="pollutant_avg") for p, v in (("PM10", 180), ("NO2", 50), ("CO", 60))]
    assert cpcb.stations_from_records(recs)[0]["aqi"] == 180


def test_station_needs_three_pollutants_including_pm():
    two = [rec("A", "PM2.5", 300), rec("A", "NO2", 40)]
    no_pm = [rec("B", "NO2", 300), rec("B", "SO2", 40), rec("B", "CO", 50)]
    with_na = [rec("C", "PM2.5", 300), rec("C", "NO2", "NA"), rec("C", "CO", 50)]
    assert cpcb.stations_from_records(two + no_pm + with_na) == []


def test_nearest_station_matches_the_area(feed_on):
    stations = cpcb.get_stations(now=FIXED_NOW, session=FakeSession(delhi_records()))
    hit = cpcb.nearest(stations, data.get_area("ito"))
    assert hit["name"] == "ITO, Delhi - CPCB" and hit["aqi"] == 312 and hit["time"] == "09:00"


def test_station_found_by_name_when_the_feed_has_no_coordinates(feed_on):
    recs = [rec("ITO, Delhi - CPCB", p, v) for p, v in (("PM2.5", 290), ("PM10", 200), ("NO2", 40))]
    stations = cpcb.get_stations(now=FIXED_NOW, session=FakeSession(recs))
    assert cpcb.nearest(stations, data.get_area("ito"))["aqi"] == 290


def test_old_reports_are_not_called_now(feed_on):
    old = station("ITO, Delhi - CPCB", 28.6286, 77.2410, 312, updated="09-10-2026 20:00:00")
    assert cpcb.get_stations(now=FIXED_NOW, session=FakeSession(old)) == []


def test_feed_failure_or_no_key_gives_none(feed_on, monkeypatch):
    assert cpcb.get_stations(now=FIXED_NOW, session=FakeSession(status=500)) is None
    monkeypatch.delenv("DATAGOV_API_KEY")
    assert cpcb.fetch(FakeSession(delhi_records())) is None


def test_key_goes_in_the_request_only(feed_on):
    s = FakeSession(delhi_records())
    cpcb.get_stations(now=FIXED_NOW, session=s)
    assert s.calls[0]["params"]["api-key"] == "test-key" and s.calls[0]["params"]["filters[state]"] == "Delhi"
    assert [c["params"]["filters[state]"] for c in s.calls] == ["Delhi", "Haryana", "Uttar_Pradesh", "Rajasthan"]


def test_city_aqi_is_the_station_average(feed_on):
    stations = cpcb.get_stations(now=FIXED_NOW, session=FakeSession(delhi_records()))
    city = cpcb.city_air(stations)
    assert city["count"] == len(stations) and city["aqi"] == round(sum(s["aqi"] for s in stations) / len(stations))
    assert city["high"]["name"] == "ITO" and city["basis"] == "cpcb"


def test_plan_uses_cpcb_now_and_forecast_for_tomorrow(feed_on, mem_store, live_fetcher, monkeypatch):
    stations = cpcb.get_stations(now=FIXED_NOW, session=FakeSession(delhi_records()))
    monkeypatch.setattr(cpcb, "get_stations", lambda store=None, now=None, session=None: stations)
    today = get_plan("commuter", "ito", now=FIXED_NOW, fetcher=live_fetcher, day="today")
    assert today["air"]["day_aqi"] == 312 and today["air_now"]["particles"]["basis"] == "cpcb"
    assert today["stage"]["city"]["basis"] == "cpcb" and today["official"]["short"] == "ITO"
    tomorrow = get_plan("commuter", "ito", now=FIXED_NOW, fetcher=live_fetcher, day="tomorrow")
    assert tomorrow["air"]["day_aqi"] != 312 and tomorrow["stage"]["city"]["basis"] == "forecast"


def test_plan_falls_back_to_the_model_without_the_feed(mem_store, live_fetcher):
    plan = get_plan("commuter", "ito", now=FIXED_NOW, fetcher=live_fetcher, day="today")
    assert plan["official"] is None and plan["air_now"]["particles"]["basis"] != "cpcb"


def test_page_names_the_cpcb_station(feed_on, mem_store, live_fetcher, monkeypatch):
    from saans.web import create_app

    stations = cpcb.get_stations(now=FIXED_NOW, session=FakeSession(delhi_records()))
    monkeypatch.setattr(cpcb, "get_stations", lambda store=None, now=None, session=None: stations)
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    html = create_app().test_client().get("/plan?persona=commuter&area=ito&day=today").get_data(as_text=True)
    assert "CPCB, ITO station" in html and "at CPCB&#39;s ITO station" in html


class Refused(FakeSession):
    def get(self, url, params=None, timeout=None):
        import requests
        self.calls.append({"url": url, "params": params})
        raise requests.ConnectionError("refused")


def test_refused_host_is_retried_once_then_given_up(feed_on, monkeypatch):
    monkeypatch.setattr(cpcb.time, "sleep", lambda s: None)
    s = Refused()
    assert cpcb.fetch(s) is None and len(s.calls) == 2  # one retry, then the other states are skipped


def test_last_good_reading_covers_a_feed_outage(feed_on, mem_store, monkeypatch):
    monkeypatch.setattr(cpcb.time, "sleep", lambda s: None)
    good = cpcb.stations_from_records(delhi_records())
    mem_store.put_text(cpcb.LAST_KEY, __import__("json").dumps(good))
    monkeypatch.setattr(cpcb, "fetch", lambda session=None: None)
    stations = cpcb.get_stations(mem_store, now=FIXED_NOW)
    assert stations and cpcb.nearest(stations, data.get_area("ito"))["aqi"] == 312
