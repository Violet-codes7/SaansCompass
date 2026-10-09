"""Dial gauges drawn as inline SVG on the server: no chart library, no
JavaScript, and they print. Colours come from CSS classes so they follow the
page's light and dark themes."""
import math

from markupsafe import Markup, escape

# CPCB AQI bands, matching the colour classes in app.css.
AQI_BANDS = [(0, 50, "good"), (50, 100, "satisfactory"), (100, 200, "moderate"),
             (200, 300, "poor"), (300, 400, "very-poor"), (400, 500, "severe")]

START, SWEEP = 150.0, 240.0  # degrees, clockwise from the x axis (SVG y points down)
CX, CY, R = 60.0, 60.0, 46.0


def _point(angle, r=R):
    a = math.radians(angle)
    return CX + r * math.cos(a), CY + r * math.sin(a)


def _angle(value, lo, hi):
    value = min(max(value, lo), hi)
    return START + SWEEP * (value - lo) / (hi - lo)


def _arc(a0, a1, cls, width=10):
    x0, y0 = _point(a0)
    x1, y1 = _point(a1)
    large = 1 if a1 - a0 > 180 else 0
    return (f'<path class="arc {cls}" d="M{x0:.1f} {y0:.1f} A{R} {R} 0 {large} 1 {x1:.1f} {y1:.1f}" '
            f'fill="none" stroke-width="{width}"/>')


def _needle(angle):
    x, y = _point(angle, R - 12)
    return (f'<line class="needle" x1="{CX}" y1="{CY}" x2="{x:.1f}" y2="{y:.1f}" stroke-width="3" '
            f'stroke-linecap="round"/><circle class="hub" cx="{CX}" cy="{CY}" r="5"/>')


def _svg(parts, label, value_text):
    return Markup(
        f'<svg class="gauge" viewBox="0 0 120 100" role="img" aria-label="{escape(label)}">'
        + "".join(parts)
        + f'<text class="g-val" x="{CX}" y="{CY + 30}" text-anchor="middle">{escape(value_text)}</text></svg>'
    )


def aqi_gauge(value, label):
    parts = [_arc(_angle(lo, 0, 500), _angle(hi, 0, 500), f"band {cls}") for lo, hi, cls in AQI_BANDS]
    if value is None:
        return _svg(parts, f"{label}: no data", "–")
    parts.append(_needle(_angle(value, 0, 500)))
    return _svg(parts, f"{label}: AQI {value}", str(value))


def simple_gauge(value, lo, hi, unit, label):
    parts = [_arc(START, START + SWEEP, "track")]
    if value is None:
        return _svg(parts, f"{label}: no data", "–")
    a = _angle(value, lo, hi)
    if a > START + 0.5:
        parts.append(_arc(START, a, "fill"))
    parts.append(_needle(a))
    shown = f"{value:.0f}{unit}" if abs(value) >= 10 or unit == "%" else f"{value:.1f}{unit}"
    return _svg(parts, f"{label}: {shown}", shown)
