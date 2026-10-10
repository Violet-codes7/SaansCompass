import pytest

from saans import data, weather
from saans.gauges import aqi_gauge, simple_gauge
from saans.web import create_app

REAL_FETCH_WEATHER = weather.fetch_weather  # before the autouse fixture replaces it
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
    assert "Air quality at ITO" in home and "Weather in Delhi" in home and "Why it matters" in home
    plan = client.get("/plan?persona=rider&area=okhla").get_data(as_text=True)
    assert "Air quality at Okhla" in plan and plan.count('<svg class="gauge"') == 6  # 3 air, 3 weather


def test_plan_without_weather_still_renders(mem_store, monkeypatch, live_fetcher):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    html = create_app().test_client().get("/plan?persona=older&area=ito").get_data(as_text=True)
    assert "Weather is not available right now" in html and "Weather in Delhi" in html


FULL_WX = {**WX, "time": "2026-10-10T09:00", "feels_c": 29.4, "dew_c": 22.1, "gust_kmh": 14.0, "wind_dir": 315.0,
           "mixing_m": 240.0}


def test_weather_bands_and_compass():
    assert weather.band("wind_kmh", 5.6)["name"] == "Calm" and weather.band("wind_kmh", 25)["name"] == "Moderate breeze"
    assert weather.band("temp_c", 27.0)["name"] == "Warm" and weather.band("humidity", 74)["name"] == "Humid"
    assert weather.band("mixing_m", 240)["tone"] == "red" and weather.band("mixing_m", None) is None
    assert weather.compass(315) == ("north-west", "NW") and weather.compass(2) == ("north", "N")


def test_weather_explains_mixing_height_and_stubble_smoke():
    note = weather.explain(FULL_WX)
    assert "low lid" in note and "240 m" in note and "crop-stubble" in note
    assert "crop-stubble" not in weather.explain({**FULL_WX, "time": "2026-06-10T09:00"})
    assert "crop-stubble" not in weather.explain({**FULL_WX, "wind_dir": 120.0})


def test_fetch_weather_reads_the_extra_fields():
    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"current": {"time": "2026-10-10T09:00", "temperature_2m": 27, "relative_humidity_2m": 74,
                                "wind_speed_10m": 5.6, "apparent_temperature": 29.4, "dew_point_2m": 22.1,
                                "wind_direction_10m": 315, "wind_gusts_10m": 14},
                    "hourly": {"time": ["2026-10-10T08:00", "2026-10-10T09:00"], "boundary_layer_height": [180, 240],
                               "temperature_2m": [26, 27], "wind_speed_10m": [4, None]}}

    class Session:
        def get(self, url, params, timeout):
            assert "boundary_layer_height" in params["hourly"] and "wind_direction_10m" in params["current"]
            return Resp()

    w = REAL_FETCH_WEATHER(data.AREAS["ito"], session=Session())
    assert w["mixing_m"] == 240.0 and w["wind_dir"] == 315.0 and w["feels_c"] == 29.4
    assert w["hours"][0] == {"time": "2026-10-10T08:00", "temp_c": 26.0, "humidity": None, "wind_kmh": 4.0,
                             "wind_dir": None, "mixing_m": 180.0}
    assert w["hours"][1]["wind_kmh"] is None


def test_old_cached_weather_without_new_fields_still_renders(mem_store):
    mem_store.put_text("WX#ito", '{"time": "2026-10-10T09:00", "temp_c": 27.0, "humidity": 74.0, "wind_kmh": 5.6}')
    w = weather.get_weather(data.AREAS["ito"], mem_store, fetcher=lambda a: 1 / 0)
    assert w["mixing_m"] is None and w["wind_from"] is None and "little wind" in w["note"]


def test_dashboard_shows_banded_weather_and_particles(mem_store, monkeypatch, live_fetcher):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    monkeypatch.setattr(weather, "fetch_weather", lambda area: dict(FULL_WX))
    html = create_app().test_client().get("/plan?persona=rider&area=okhla").get_data(as_text=True)
    assert html.count('<svg class="gauge"') == 7
    for part in ("Feels like 29°C", "Dew point 22°C", "From the north-west", "Gusts 14 km/h", "Mixing height",
                 "Very low lid", "This hour", "µg/m³", "× WHO"):
        assert part in html
    assert 'id="particles"' not in html and "Deep in the lungs" not in html  # the section was dropped


def test_particles_use_24_hours_when_known():
    from datetime import timedelta
    from conftest import FIXED_NOW, make_hours
    yesterday = FIXED_NOW - timedelta(days=1)
    full = {"hours": make_hours([100] * 24, days=3, start=yesterday)}
    p = data.particles_now(full, FIXED_NOW)
    assert p["basis"] == "last24" and p["pm25"] == 100 and p["pm10"] == 150 and p["pm25_hour"] == 100
    today_only = {"hours": make_hours([40] * 12 + [80] * 12, days=1, start=FIXED_NOW)}
    p = data.particles_now(today_only, FIXED_NOW)
    assert p["basis"] == "today" and p["pm25"] == 60


def test_hours_are_clickable_with_full_details(mem_store, monkeypatch, live_fetcher):
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    wx = dict(FULL_WX, hours=[{"time": f"{data.now_ist().date().isoformat()}T{h:02d}:00", "temp_c": 20.0 + h, "humidity": 60.0,
                               "wind_kmh": 3.0, "wind_dir": 300.0, "mixing_m": 250.0} for h in range(24)])
    monkeypatch.setattr(weather, "fetch_weather", lambda area: wx)
    html = create_app().test_client().get("/plan?persona=commuter&area=ito&day=today").get_data(as_text=True)
    panels = html.split('class="dp-detail')[1:]
    assert len(panels) == html.count('role="tab" class="dp-col') > 10
    assert sum('role="tabpanel" >' in p for p in panels) == 1  # one hour open, the rest hidden
    assert "Your plans this hour" in html and "Do this now" in html and "× WHO" in html
    nine = next(p for p in panels if "09:00–10:00" in p)
    assert "Morning commute" in nine and "29°C" in nine and "Very low lid" in nine  # that hour's own weather


def test_weather_is_read_for_delhi_not_the_plan_area(mem_store, monkeypatch, live_fetcher):
    asked = []
    monkeypatch.setattr(data, "fetch_open_meteo", live_fetcher)
    monkeypatch.setattr(weather, "fetch_weather", lambda area: asked.append(area.id) or dict(WX))
    create_app().test_client().get("/plan?persona=rider&area=okhla")
    assert asked == ["delhi"]


def test_implausible_model_pm10_is_held_and_said(mem_store, monkeypatch):
    from conftest import FIXED_NOW
    rows = [{"time": f"2026-10-{d:02d}T{h:02d}:00", "pm25": 120.0, "pm10": 598.0} for d in (9, 10, 11) for h in range(24)]
    held = data.plausible(rows)
    assert held[0]["pm10"] == 300.0 and held[0]["pm10_model"] == 598.0  # 2.5 x PM2.5
    assert data.plausible([{"time": "t", "pm25": 120.0, "pm10": 200.0}])[0] == {"time": "t", "pm25": 120.0, "pm10": 200.0}
    f = {"hours": held}
    pt = data.particles_now(f, FIXED_NOW)
    assert pt["pm10"] == 300 and pt["pm10_model"] == 598 and pt["aqi"] < 500
    monkeypatch.setattr(data, "fetch_open_meteo", lambda area: [dict(r) for r in rows])
    monkeypatch.setattr(weather, "fetch_weather", lambda area: dict(WX))
    monkeypatch.setattr(data, "now_ist", lambda: FIXED_NOW)
    html = create_app().test_client().get("/plan?persona=rider&area=dwarka&day=today").get_data(as_text=True)
    assert "Model said" not in html and "Severe" not in html.split('id="air"')[1].split("</figure>")[0]
