import pytest

from saans.aqi import PM10_BREAKPOINTS, PM25_BREAKPOINTS, aqi, category, correct_bands, sub_index


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


@pytest.mark.parametrize("text,expected", [
    ("Delhi is at AQI 218 (moderate) today.", "Delhi is at AQI 218 (poor) today."),  # seen on the live site
    ("The AQI of 218 is Moderate.", "The AQI of 218 is Poor."),
    ("AQI 218, moderate, so keep it short.", "AQI 218, poor, so keep it short."),
    ("Delhi's average is 218 (Moderate).", "Delhi's average is 218 (Poor)."),
    ("Moderate (AQI 218) all day.", "Poor (AQI 218) all day."),
    ("a moderate AQI of 218", "a poor AQI of 218"),
    ("AQI 330 (POOR)", "AQI 330 (VERY POOR)"),
    ("AQI 600 (Very Poor)", "AQI 600 (Severe)"),
])
def test_a_band_next_to_an_aqi_figure_is_that_figures_band(text, expected):
    assert correct_bands(text) == expected


@pytest.mark.parametrize("text", [
    "ITO: AQI 191 (Moderate), forecast model.",          # already right
    "AQI 45, good time for a walk",                       # "good" as a word, and right anyway
    "AQI 218, not a good time to run.",                   # "good" in another sense
    "Be back by 14:00 (Moderate effort is fine).",       # a time, not an AQI
    "AQI 150-220 (Moderate to Poor)",                     # a range of figures and bands
    "Leave at 10:00 (AQI 180) and be back by 14:00.",
    "",
])
def test_other_text_is_left_alone(text):
    assert correct_bands(text) == text
