"""Rough breath dose: PM2.5 level x breathing effort x minutes.

This is an estimate for comparison, not a clinical measure. The reference is
the same minutes spent at rest in air at the WHO 24-hour PM2.5 guideline
(15 µg/m³), so "4x" reads as "four times what clean air would give you".
"""
from .personas import VENTILATION_M3_PER_HOUR

WHO_PM25_24H = 15.0


def segment_ug(pm25, effort, minutes):
    """µg of PM2.5 inhaled over one segment, or None if the reading is missing."""
    if pm25 is None:
        return None
    return pm25 * VENTILATION_M3_PER_HOUR[effort] * minutes / 60.0


def total_dose(segments):
    """segments: iterable of (pm25, effort, minutes). Missing readings are skipped and counted."""
    dose = 0.0
    reference = 0.0
    minutes = 0
    missing = 0
    for pm25, effort, mins in segments:
        ug = segment_ug(pm25, effort, mins)
        if ug is None:
            missing += 1
            continue
        dose += ug
        reference += WHO_PM25_24H * VENTILATION_M3_PER_HOUR["rest"] * mins / 60.0
        minutes += mins
    ratio = round(dose / reference, 1) if reference else None
    return {
        "ug": round(dose, 1),
        "minutes": minutes,
        "reference_ug": round(reference, 1),
        "ratio": ratio,
        "missing_segments": missing,
    }
