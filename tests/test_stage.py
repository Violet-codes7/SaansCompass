import pytest

from saans.stage import parse_stage, resolve_stage, stage_from_aqi


@pytest.mark.parametrize("value,stage", [
    (None, None), (0, 0), (200, 0), (201, 1), (300, 1), (301, 2), (400, 2), (401, 3), (450, 3), (451, 4), (500, 4),
])
def test_stage_band_edges(value, stage):
    assert stage_from_aqi(value) == stage


@pytest.mark.parametrize("raw,stage", [
    (None, None), ("", None), ("  ", None), ("0", 0), ("none", 0), ("I", 1), ("ii", 2), ("III", 3), ("4", 4), ("IV", 4),
])
def test_parse_stage(raw, stage):
    assert parse_stage(raw) == stage


@pytest.mark.parametrize("raw", ["V", "5", "-1", "stage3", "<script>"])
def test_parse_stage_rejects_bad_input(raw):
    with pytest.raises(ValueError):
        parse_stage(raw)


def test_official_stage_wins_over_estimate():
    assert resolve_stage(480, official=1) == {"stage": 1, "label": "I", "source": "official", "day_aqi": 480,
                                              "estimate": "IV"}
    assert resolve_stage(480)["source"] == "estimate"
    assert resolve_stage(480)["stage"] == 4


def test_official_stage_zero_is_respected():
    info = resolve_stage(480, official=0)
    assert info["stage"] == 0 and info["source"] == "official"
