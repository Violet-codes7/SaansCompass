import pytest

from saans import data, weather
from saans.gauges import aqi_gauge, simple_gauge
from saans.web import create_app

WX = {"time": "2026-10-10T09:00", "temp_c": 27.0, "humidity": 74.0, "wind_kmh": 5.6}


def test_aqi_gauge_draws_bands_and_needle():
    svg = str(aqi_gauge(165, "AQI now"))
    assert svg.startswith("<svg") and svg.count('class="arc band') == 6
    assert "needle" in svg and ">165<" in svg and 'aria-label="AQI now: AQI 165"' in svg


def test_gauges_handle_missing_and_out_of_range_values():
    assert "needle" not in str(aqi_gauge(None, "x")) and ">–<" in str(aqi_gauge(None, "x"))
    assert ">520<" in str(aqi_gauge(520, "x"))  # needle pinned at the end, value still shown
    assert ">5.6<" in str(simple_gauge(5.6, 0, 40, "", "Wind"))
    assert ">74%<" in str(simple_gauge(74, 0, 100, "%", "Humidity"))


def test_weather_explains_still_humid_air():
    note = weather.explain(WX)
    assert "little wind" in note and "Humid" in note
    assert "breeze is helping" in weather.explain({**WX, "wind_kmh": 25, "humidity": 40})


def test_weather_is_cached_and_failure_is_quiet(mem_store):
    calls = []

    def fetch(area):
        calls.append(area.id)
        return dict(WX)
    area = data.AREAS["ito"]
    assert weather.get_weather(area, mem_store, fetcher=fetch)["wind_kmh"] == 5.6
    assert weather.get_weather(area, mem_store, fetcher=fetch)["note"]
    assert calls == ["ito"]

    def fail(area):
        raise TimeoutError()
    assert weather.get_weather(data.AREAS["okhla"], mem_store, fetcher=fail) is None


@pytest.fixture
def client(mem_store, monkeypatch, live_fetcher):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    monkeypatch.setattr(weather, "fetch_weather", lambda area: dict(WX))
    return create_app().test_client()


def test_dashboard_on_home_and_plan(client):
    home = client.get("/").get_data(as_text=True)
    assert "Air quality at ITO" in home and "Weather now" in home and "Why it matters" in home
    plan = client.get("/plan?persona=rider&area=okhla").get_data(as_text=True)
    assert "Air quality at Okhla" in plan and plan.count('<svg class="gauge"') == 5


def test_plan_without_weather_still_renders(mem_store, monkeypatch, live_fetcher):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    html = create_app().test_client().get("/plan?persona=older&area=ito").get_data(as_text=True)
    assert "Weather is not available right now" in html
