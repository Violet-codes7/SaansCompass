import pytest

from saans.aqi import PM10_BREAKPOINTS, PM25_BREAKPOINTS, aqi, category, sub_index


@pytest.mark.parametrize("conc,expected", [
    (0, 0), (30, 50), (60, 100), (90, 200), (120, 300), (250, 400), (380, 500), (1000, 500),
])
def test_pm25_breakpoint_edges(conc, expected):
    assert sub_index(conc, PM25_BREAKPOINTS) == expected


@pytest.mark.parametrize("conc,expected", [
    (0, 0), (50, 50), (100, 100), (250, 200), (350, 300), (430, 400), (510, 500), (900, 500),
])
def test_pm10_breakpoint_edges(conc, expected):
    assert sub_index(conc, PM10_BREAKPOINTS) == expected


def test_just_above_a_breakpoint_moves_to_the_next_band():
    assert sub_index(30.5, PM25_BREAKPOINTS) == 52
    assert category(sub_index(30.5, PM25_BREAKPOINTS)) == "Satisfactory"


def test_worst_pollutant_wins():
    assert aqi(100, 120) == (234, "PM2.5")
    assert aqi(20, 310) == (260, "PM10")


def test_missing_readings():
    assert aqi(None, None) == (None, None)
    assert aqi(None, 310) == (260, "PM10")
    assert category(None) == "No data"


def test_negative_concentration_rejected():
    with pytest.raises(ValueError):
        sub_index(-1, PM25_BREAKPOINTS)


@pytest.mark.parametrize("value,name", [
    (50, "Good"), (51, "Satisfactory"), (100, "Satisfactory"), (101, "Moderate"),
    (200, "Moderate"), (201, "Poor"), (300, "Poor"), (301, "Very Poor"), (400, "Very Poor"),
    (401, "Severe"), (500, "Severe"),
])
def test_categories(value, name):
    assert category(value) == name
