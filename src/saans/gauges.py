"""Ring gauges drawn as inline SVG on the server: no chart library, no
JavaScript, and they print. Colours come from CSS classes so they follow the
page's light and dark themes."""
import itertools
import math

from markupsafe import Markup, escape

# CPCB AQI bands, matching the colour classes in app.css.
AQI_BANDS = [(0, 50, "good"), (50, 100, "satisfactory"), (100, 200, "moderate"),
             (200, 300, "poor"), (300, 400, "very-poor"), (400, 500, "severe")]

START, SWEEP = 135.0, 270.0  # degrees, clockwise from the x axis (SVG y points down)
CX, CY, R = 60.0, 56.0, 44.0
_ids = itertools.count(1)  # gradient ids, unique on a page


def _point(angle, r=R):
    a = math.radians(angle)
    return CX + r * math.cos(a), CY + r * math.sin(a)


def _angle(value, lo, hi):
    value = min(max(value, lo), hi)
    return START + SWEEP * (value - lo) / (hi - lo)


def _arc(a0, a1, cls, width=9, stroke=None):
    x0, y0 = _point(a0)
    x1, y1 = _point(a1)
    large = 1 if a1 - a0 > 180 else 0
    paint = f' style="stroke:{stroke}"' if stroke else ""  # beats the band colour rules in app.css
    return (f'<path class="arc {cls}" d="M{x0:.1f} {y0:.1f} A{R} {R} 0 {large} 1 {x1:.1f} {y1:.1f}" '
            f'fill="none" stroke-width="{width}" stroke-linecap="round" pathLength="100"{paint}/>')


def _fill(a, cls, stroke=None):
    """The filled part of the ring, from the start to angle `a`, with a knob at its end."""
    parts = [_arc(START, max(a, START + 0.5), f"fill {cls}", stroke=stroke)]
    x, y = _point(a)
    parts.append(f'<circle class="knob {cls}" cx="{x:.1f}" cy="{y:.1f}" r="6.5" stroke-width="3"/>')
    return parts


def _svg(parts, label, value_text, unit="", defs=""):
    unit_text = f'<tspan class="g-unit" dx="2">{escape(unit)}</tspan>' if unit else ""
    return Markup(
        f'<svg class="gauge" viewBox="0 0 120 100" role="img" aria-label="{escape(label)}">'
        + (f"<defs>{defs}</defs>" if defs else "")
        + _arc(START, START + SWEEP, "track")
        + "".join(parts)
        + f'<text class="g-val" x="{CX}" y="{CY + 9}" text-anchor="middle">{escape(value_text)}{unit_text}</text></svg>'
    )


def _aqi_gradient(gid):
    """Left to right across the dial, through the AQI band colours (set in app.css)."""
    stops = "".join(f'<stop class="g-stop {cls}" offset="{(lo + hi) / 1000:.2f}"/>' for lo, hi, cls in AQI_BANDS)
    x0, x1 = CX - R, CX + R
    return (f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="{x0:.0f}" y1="0" x2="{x1:.0f}" y2="0">'
            f"{stops}</linearGradient>")


def aqi_gauge(value, label):
    if value is None:
        return _svg([], f"{label}: no data", "–")
    cls = next((c for lo, hi, c in AQI_BANDS if value < hi), AQI_BANDS[-1][2])
    gid = f"g-aqi-{next(_ids)}"
    return _svg(_fill(_angle(value, 0, 500), f"band {cls}", stroke=f"url(#{gid})"),
                f"{label}: AQI {value}", str(value), defs=_aqi_gradient(gid))


def simple_gauge(value, lo, hi, unit, label):
    if value is None:
        return _svg([], f"{label}: no data", "–")
    shown = f"{value:.0f}{unit}" if abs(value) >= 10 or unit == "%" else f"{value:.1f}{unit}"
    return _svg(_fill(_angle(value, lo, hi), "accent"), f"{label}: {shown}", shown)


def band_gauge(value, dial, label):
    """A ring filled to `value` (clamped to the dial's range), in the colour of the
    config/weather.json band the value falls in."""
    lo, hi = dial["lo"], dial["hi"]
    if value is None:
        return _svg([], f"{label}: no data", "–")
    band = next((b for b in dial["bands"] if value < b["max"]), dial["bands"][-1])
    inline = dial["unit"] in ("°C", "%")  # short enough to sit on the number
    unit = dial["unit"] if inline else ""
    shown = f"{value:.0f}{unit}" if abs(value) >= 10 or unit else f"{value:.1f}"
    return _svg(_fill(_angle(value, lo, hi), f"band tone-{band['tone']}"),
                f"{label}: {value:.0f} {dial['unit']}", shown, "" if inline else dial["unit"])


def qr_code(url, label):
    """A QR code for `url` as inline SVG, so a printed poster links back to the live plan."""
    import segno

    svg = segno.make(url, error="m").svg_inline(scale=3, border=2, dark="#000", light="#fff", omitsize=True)
    return Markup(svg.replace("<svg ", f'<svg role="img" aria-label="{escape(label)}" ', 1))
