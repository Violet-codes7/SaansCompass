from saans.dose import WHO_PM25_24H, segment_ug, total_dose


def test_segment_maths():
    # 100 µg/m³ x 1.6 m³/h x 30 min = 80 µg
    assert segment_ug(100, "moderate", 30) == 80


def test_reference_is_resting_in_who_guideline_air():
    d = total_dose([(WHO_PM25_24H, "rest", 60)])
    assert d["ratio"] == 1.0


def test_harder_breathing_raises_dose():
    rest = total_dose([(100, "rest", 60)])["ug"]
    heavy = total_dose([(100, "heavy", 60)])["ug"]
    assert heavy == rest * 6


def test_missing_hours_are_skipped_and_counted():
    d = total_dose([(None, "light", 60), (60, "light", 60)])
    assert d["missing_segments"] == 1 and d["minutes"] == 60 and d["ug"] == 60


def test_no_data_gives_no_ratio():
    assert total_dose([(None, "light", 60)])["ratio"] is None
