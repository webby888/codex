#!/usr/bin/env python3
"""Generate the Sunburst Navy watch face.

One geometry model, two outputs:
  * app/src/main/res/raw/watchface.xml  - Watch Face Format (WFF v2) definition
  * preview/preview.html                - browser mock-up used to render preview.png

Edit the constants below and re-run `python3 generate.py`. Coordinates are on
the 450x450 WFF virtual canvas; the watch scales it to the real display.
"""

import math
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent
SIZE = 450
C = SIZE / 2  # centre
R = SIZE / 2  # dial radius

# --- Palette (sampled from the reference photos) -----------------------------
DIAL_CENTER = "#FF2C4C86"
DIAL_MID = "#FF1A3368"
DIAL_EDGE = "#FF0A1636"
SILVER_HI = "#FFF4F6F8"
SILVER = "#FFCBD1D7"
SILVER_LO = "#FF858E97"
HAND_SHADE = "#FFAEB6BE"  # shaded facet of the polished hands
PRINT = "#FFDCE3EA"  # dial printing / thin ring
TICK = "#FF9FB0C8"
LUME = "#FFEEF4EF"

# --- Geometry (fractions of the dial radius, measured from the photos) --------
MARKER_IN, MARKER_OUT = 0.74 * R, 0.95 * R
MARKER_3_IN = 0.84 * R  # shortened to make room for the date window
TICK_IN, TICK_OUT = 0.815 * R, 0.85 * R
RING_R = 0.70 * R  # thin silver half-ring from 12 to 6
TRI_TOP, TRI_TIP, TRI_HALF_W = 0.975 * R, 0.80 * R, 0.095 * R


def polar(deg, r):
    a = math.radians(deg)
    return C + r * math.sin(a), C - r * math.cos(a)


def f(v):
    return f"{v:.2f}".rstrip("0").rstrip(".")


# =============================================================================
# WFF XML
# =============================================================================


def stroke(color, thickness, cap="BUTT"):
    return f'<Stroke color="{color}" thickness="{f(thickness)}" cap="{cap}"/>'


def line(x1, y1, x2, y2, color, thickness, cap="BUTT"):
    return (
        f'<Line startX="{f(x1)}" startY="{f(y1)}" endX="{f(x2)}" endY="{f(y2)}">'
        f"{stroke(color, thickness, cap)}</Line>"
    )


def faceted_baton(deg, r_in, r_out):
    """Polished applied marker: base bar with a bright and a dark facet."""
    x1, y1 = polar(deg, r_in)
    x2, y2 = polar(deg, r_out)
    # unit vector perpendicular to the marker, pointing clockwise
    px, py = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    out = [line(x1, y1, x2, y2, SILVER, 10)]
    out.append(line(x1 - 2.5 * px, y1 - 2.5 * py, x2 - 2.5 * px, y2 - 2.5 * py, SILVER_HI, 4))
    out.append(line(x1 + 3.2 * px, y1 + 3.2 * py, x2 + 3.2 * px, y2 + 3.2 * py, SILVER_LO, 3))
    return out


def triangle_12():
    """Inverted triangle at 12, built from 1px rows (WFF v2 has no path primitive)."""
    out = []
    top_y, tip_y = C - TRI_TOP, C - TRI_TIP
    rows = int(tip_y - top_y)
    for i in range(rows + 1):
        y = top_y + i
        half = TRI_HALF_W * (1 - i / rows)
        if half < 0.5:
            break
        out.append(line(C - half, y, C, y, SILVER_HI, 1.3))
        out.append(line(C, y, C + half, y, SILVER, 1.3))
    return out


def part_draw(name, elements, extra="", children=""):
    return (
        f'<PartDraw name="{name}" x="0" y="0" width="{SIZE}" height="{SIZE}"{extra}>'
        + children
        + "".join(elements)
        + "</PartDraw>"
    )


def ambient(target, value):
    return f'<Variant mode="AMBIENT" target="{target}" value="{value}"/>'


def hand_group(name, angle_expr, shapes, ambient_alpha=None):
    variant = ambient("alpha", ambient_alpha) if ambient_alpha is not None else ""
    return (
        f'<Group name="{name}" x="0" y="0" width="{SIZE}" height="{SIZE}" pivotX="0.5" pivotY="0.5">'
        f'<Transform target="angle" value="{angle_expr}"/>{variant}'
        + part_draw(f"{name}_draw", shapes)
        + "</Group>"
    )


def rect(x, y, w, h, color, radius=0.0):
    if radius:
        return (
            f'<RoundRectangle x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(h)}" '
            f'cornerRadiusX="{f(radius)}" cornerRadiusY="{f(radius)}"><Fill color="{color}"/></RoundRectangle>'
        )
    return f'<Rectangle x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(h)}"><Fill color="{color}"/></Rectangle>'


def faceted_rect(x, y, w, h, radius):
    """Polished hand body: left half bright, right half shaded."""
    return (
        f'<RoundRectangle x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(h)}" '
        f'cornerRadiusX="{f(radius)}" cornerRadiusY="{f(radius)}"><Fill color="{SILVER}">'
        f'<LinearGradient startX="{f(x)}" startY="0" endX="{f(x + w)}" endY="0" '
        f'colors="{SILVER_HI} {SILVER_HI} {HAND_SHADE} {HAND_SHADE}" positions="0 0.5 0.5 1"/>'
        f"</Fill></RoundRectangle>"
    )


# Hand specs: (tail, tip, width, lume_from, lume_to, lume_width) in px from centre
HOUR = (0.12 * R, 0.52 * R, 15, 0.20 * R, 0.47 * R, 6)
MINUTE = (0.12 * R, 0.86 * R, 11, 0.28 * R, 0.81 * R, 4.5)
SECOND = (0.25 * R, 0.80 * R, 2.4)


def baton_hand(spec):
    tail, tip, w, l0, l1, lw = spec
    return [
        faceted_rect(C - w / 2, C - tip, w, tip + tail, w / 2.6),
        rect(C - lw / 2, C - l1, lw, l1 - l0, LUME, lw / 2),
    ]


def complication_slot(slot_id, x, provider, display_name):
    """Small printed-style readout: monochrome icon + value, swappable on the watch."""
    w, h = 104, 36
    body = (
        f'<PartImage x="4" y="7" width="22" height="22" tintColor="{PRINT}">'
        f'<Image resource="[COMPLICATION.MONOCHROMATIC_IMAGE]"/></PartImage>'
        f'<PartText x="30" y="0" width="{w - 30}" height="{h}">'
        f'<Text align="START" ellipsis="TRUE">'
        f'<Font family="SYNC_TO_DEVICE" size="22" weight="MEDIUM" color="{PRINT}" letterSpacing="0.04">'
        f'<Template>%s<Parameter expression="[COMPLICATION.TEXT]"/></Template>'
        f"</Font></Text></PartText>"
    )
    complications = "".join(
        f'<Complication type="{t}">{body}</Complication>' for t in ("SHORT_TEXT", "RANGED_VALUE")
    )
    return (
        f'<ComplicationSlot slotId="{slot_id}" displayName="{display_name}" '
        f'x="{f(x)}" y="{f(C + 0.40 * R)}" width="{w}" height="{h}" '
        f'supportedTypes="SHORT_TEXT RANGED_VALUE" isCustomizable="TRUE">'
        f'<DefaultProviderPolicy defaultSystemProvider="{provider}" defaultSystemProviderType="SHORT_TEXT"/>'
        f'<BoundingBox x="0" y="0" width="{w}" height="{h}"/>'
        f"{ambient('alpha', 150)}{complications}</ComplicationSlot>"
    )


def build_xml():
    s = []

    # Dial: radial base + sunburst sweep highlight (black in ambient for AOD).
    sweep_colors = " ".join(
        ["#00FFFFFF", "#33000000", "#00FFFFFF", "#26FFFFFF", "#00FFFFFF", "#33000000", "#00FFFFFF", "#26FFFFFF", "#00FFFFFF"]
    )
    sweep_pos = "0 0.125 0.25 0.375 0.5 0.625 0.75 0.875 1"
    s.append(
        part_draw(
            "dial",
            [
                f'<Ellipse x="0" y="0" width="{SIZE}" height="{SIZE}"><Fill color="{DIAL_MID}">'
                f'<RadialGradient centerX="{f(C)}" centerY="{f(C)}" radius="{f(R)}" '
                f'colors="{DIAL_CENTER} {DIAL_MID} {DIAL_EDGE}" positions="0 0.6 1"/></Fill></Ellipse>',
                # Highlight bands at 10:30/4:30, shadows at 1:30/7:30, like the photo.
                f'<Ellipse x="0" y="0" width="{SIZE}" height="{SIZE}"><Fill color="#00FFFFFF">'
                f'<SweepGradient centerX="{f(C)}" centerY="{f(C)}" startAngle="0" endAngle="360" '
                f'colors="{sweep_colors}" positions="{sweep_pos}"/></Fill></Ellipse>',
                # Slightly lighter outer zone on the right half (outside the silver ring).
                f'<Arc centerX="{f(C)}" centerY="{f(C)}" width="{f(2 * (RING_R + R) / 2)}" '
                f'height="{f(2 * (RING_R + R) / 2)}" startAngle="0" endAngle="180">'
                f"{stroke('#12FFFFFF', R - RING_R)}</Arc>",
            ],
            children=ambient("alpha", 0),
        )
    )

    # Inner edge of the case: dark rehaut + thin polished lip.
    s.append(
        part_draw(
            "rehaut",
            [
                f'<Arc centerX="{f(C)}" centerY="{f(C)}" width="{SIZE - 6}" height="{SIZE - 6}" '
                f'startAngle="0" endAngle="360">{stroke("#FF07102A", 6)}</Arc>',
                f'<Arc centerX="{f(C)}" centerY="{f(C)}" width="{SIZE - 2}" height="{SIZE - 2}" '
                f'startAngle="0" endAngle="360">{stroke("#FF9AA3AC", 2)}</Arc>',
            ],
            children=ambient("alpha", 0),
        )
    )

    # Thin silver half-ring 12 -> 6 with short radial joins to the 12 and 6 markers.
    x12a, y12a = polar(0, RING_R)
    x12b, y12b = polar(0, TRI_TIP)
    x6a, y6a = polar(180, RING_R)
    x6b, y6b = polar(180, MARKER_IN)
    s.append(
        part_draw(
            "ring",
            [
                f'<Arc centerX="{f(C)}" centerY="{f(C)}" width="{f(2 * RING_R)}" height="{f(2 * RING_R)}" '
                f'startAngle="0" endAngle="180">{stroke(PRINT, 1.6)}</Arc>',
                line(x12a, y12a, x12b, y12b, PRINT, 1.6),
                line(x6a, y6a, x6b, y6b, PRINT, 1.6),
            ],
            children=ambient("alpha", 90),
        )
    )

    # Minute ticks (skip hour positions).
    ticks = []
    for m in range(60):
        if m % 5 == 0:
            continue
        x1, y1 = polar(m * 6, TICK_IN)
        x2, y2 = polar(m * 6, TICK_OUT)
        ticks.append(line(x1, y1, x2, y2, TICK, 1.6))
    s.append(part_draw("minute_ticks", ticks, children=ambient("alpha", 0)))

    # Hour markers.
    markers = triangle_12()
    for h in range(1, 12):
        markers += faceted_baton(h * 30, MARKER_3_IN if h == 3 else MARKER_IN, MARKER_OUT)
    s.append(part_draw("hour_markers", markers, children=ambient("alpha", 170)))

    # Date window at 3 (white aperture), plus a plain dim date for ambient mode.
    dx, dy, dw, dh = C + 0.60 * R - 23, C - 17, 46, 34
    s.append(
        part_draw(
            "date_frame",
            [rect(dx, dy, dw, dh, SILVER, 2), rect(dx + 3, dy + 3, dw - 6, dh - 6, "#FFF7F7F4", 1)],
            children=ambient("alpha", 0),
        )
    )
    date_text = (
        '<Text align="CENTER"><Font family="SYNC_TO_DEVICE" size="23" weight="MEDIUM" color="{color}">'
        '<Template>%s<Parameter expression="[DAY]"/></Template></Font></Text>'
    )
    s.append(
        f'<PartText name="date" x="{f(dx + 3)}" y="{f(dy + 3)}" width="{dw - 6}" height="{dh - 6}">'
        f"{ambient('alpha', 0)}{date_text.format(color='#FF151A22')}</PartText>"
    )
    s.append(
        f'<PartText name="date_ambient" x="{f(dx + 3)}" y="{f(dy + 3)}" width="{dw - 6}" height="{dh - 6}" alpha="0">'
        f"{ambient('alpha', 200)}{date_text.format(color=PRINT)}</PartText>"
    )

    # Steps + heart rate, where the original dial prints its model text.
    s.append(complication_slot(0, C - 110, "STEP_COUNT", "Left readout"))
    s.append(complication_slot(1, C + 6, "HEART_RATE", "Right readout"))

    # Hands (drawn last so they sit on top). Seconds tick once per second, like a quartz Kinetic.
    s.append(hand_group("hour_hand", "[HOUR_0_11_MINUTE] * 30", baton_hand(HOUR)))
    s.append(hand_group("minute_hand", "[MINUTE_SECOND] * 6", baton_hand(MINUTE)))
    tail, tip, w = SECOND
    seconds = [
        rect(C - w / 2, C - tip, w, tip + tail, SILVER_HI, w / 2),
        rect(C - 3, C + tail - 22, 6, 22, SILVER, 3),  # counterweight
        f'<Ellipse x="{f(C - 7)}" y="{f(C - 7)}" width="14" height="14"><Fill color="{SILVER}"/></Ellipse>',
        f'<Ellipse x="{f(C - 2.5)}" y="{f(C - 2.5)}" width="5" height="5"><Fill color="{SILVER_LO}"/></Ellipse>',
    ]
    s.append(hand_group("second_hand", "[SECOND] * 6", seconds, ambient_alpha=0))

    scene = "\n    ".join(s)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<!-- GENERATED by watchface/generate.py - edit that file, not this one. -->\n"
        f'<WatchFace width="{SIZE}" height="{SIZE}" clipShape="CIRCLE">\n'
        '  <Metadata key="CLOCK_TYPE" value="ANALOG"/>\n'
        '  <Metadata key="PREVIEW_TIME" value="10:08:36"/>\n'
        '  <Scene backgroundColor="#FF000000">\n'
        f"    {scene}\n"
        "  </Scene>\n"
        "</WatchFace>\n"
    )


# =============================================================================
# Preview (HTML/SVG approximation of the same geometry)
# =============================================================================


def svg_color(argb):
    a = int(argb[1:3], 16) / 255
    return f"#{argb[3:]}", f"{a:.3f}"


def svg_line(x1, y1, x2, y2, color, w, cap="butt"):
    c, a = svg_color(color)
    return (
        f'<line x1="{f(x1)}" y1="{f(y1)}" x2="{f(x2)}" y2="{f(y2)}" stroke="{c}" '
        f'stroke-opacity="{a}" stroke-width="{f(w)}" stroke-linecap="{cap}"/>'
    )


def svg_arc(r, start, end, color, w):
    x1, y1 = polar(start, r)
    x2, y2 = polar(end, r)
    large = 1 if end - start > 180 else 0
    c, a = svg_color(color)
    return (
        f'<path d="M {f(x1)} {f(y1)} A {f(r)} {f(r)} 0 {large} 1 {f(x2)} {f(y2)}" fill="none" '
        f'stroke="{c}" stroke-opacity="{a}" stroke-width="{f(w)}"/>'
    )


def build_preview(hh=10, mm=8, ss=36, day=2, steps="8,421", bpm="72"):
    el = []
    el.append(svg_arc(RING_R + (R - RING_R) / 2, 0, 180, "#12FFFFFF", R - RING_R))
    el.append(f'<circle cx="{C}" cy="{C}" r="{C - 3}" fill="none" stroke="#07102A" stroke-width="6"/>')
    el.append(f'<circle cx="{C}" cy="{C}" r="{C - 1}" fill="none" stroke="#9AA3AC" stroke-width="2"/>')
    el.append(svg_arc(RING_R, 0, 180, PRINT, 1.6))
    el.append(svg_line(*polar(0, RING_R), *polar(0, TRI_TIP), PRINT, 1.6))
    el.append(svg_line(*polar(180, RING_R), *polar(180, MARKER_IN), PRINT, 1.6))
    for m in range(60):
        if m % 5:
            el.append(svg_line(*polar(m * 6, TICK_IN), *polar(m * 6, TICK_OUT), TICK, 1.6))
    el.append(
        f'<polygon points="{f(C - TRI_HALF_W)},{f(C - TRI_TOP)} {f(C)},{f(C - TRI_TOP)} {f(C)},{f(C - TRI_TIP)}" fill="#F4F6F8"/>'
        f'<polygon points="{f(C)},{f(C - TRI_TOP)} {f(C + TRI_HALF_W)},{f(C - TRI_TOP)} {f(C)},{f(C - TRI_TIP)}" fill="#CBD1D7"/>'
    )
    for h in range(1, 12):
        deg = h * 30
        r_in = MARKER_3_IN if h == 3 else MARKER_IN
        px, py = math.cos(math.radians(deg)), math.sin(math.radians(deg))
        (x1, y1), (x2, y2) = polar(deg, r_in), polar(deg, MARKER_OUT)
        el.append(svg_line(x1, y1, x2, y2, SILVER, 10))
        el.append(svg_line(x1 - 2.5 * px, y1 - 2.5 * py, x2 - 2.5 * px, y2 - 2.5 * py, SILVER_HI, 4))
        el.append(svg_line(x1 + 3.2 * px, y1 + 3.2 * py, x2 + 3.2 * px, y2 + 3.2 * py, SILVER_LO, 3))
    dx, dy = C + 0.60 * R - 23, C - 17
    el.append(f'<rect x="{f(dx)}" y="{f(dy)}" width="46" height="34" rx="2" fill="#CBD1D7"/>')
    el.append(f'<rect x="{f(dx + 3)}" y="{f(dy + 3)}" width="40" height="28" rx="1" fill="#F7F7F4"/>')
    el.append(
        f'<text x="{f(dx + 23)}" y="{f(dy + 25)}" font-size="23" font-weight="500" fill="#151A22" text-anchor="middle">{day}</text>'
    )
    # complication readouts (icons are simple stand-ins for the system icons)
    cy = C + 0.40 * R
    for x, icon, text in ((C - 110, "steps", steps), (C + 6, "heart", bpm)):
        if icon == "heart":
            el.append(
                f'<path transform="translate({f(x + 4)},{f(cy + 8)}) scale(0.9)" fill="#DCE3EA" '
                'd="M12 21s-7.5-4.6-10-9.3C.3 8.4 2.2 4 6.3 4c2.3 0 3.9 1.3 5.7 3.4C13.8 5.3 15.4 4 17.7 4 21.8 4 23.7 8.4 22 11.7 19.5 16.4 12 21 12 21z"/>'
            )
        else:
            el.append(
                f'<g transform="translate({f(x + 4)},{f(cy + 7)})" fill="#DCE3EA">'
                '<ellipse cx="7" cy="7" rx="4" ry="6"/><ellipse cx="15" cy="13" rx="4" ry="6"/></g>'
            )
        el.append(
            f'<text x="{f(x + 30)}" y="{f(cy + 26)}" font-size="22" font-weight="500" fill="#DCE3EA" letter-spacing="0.9">{escape(text)}</text>'
        )

    def hand(deg, shapes):
        return f'<g transform="rotate({f(deg)} {C} {C})">{shapes}</g>'

    def baton(spec):
        tail, tip, w, l0, l1, lw = spec
        return (
            f'<rect x="{f(C - w / 2)}" y="{f(C - tip)}" width="{f(w)}" height="{f(tip + tail)}" rx="{f(w / 2.6)}" fill="url(#steel)"/>'
            f'<rect x="{f(C - lw / 2)}" y="{f(C - l1)}" width="{f(lw)}" height="{f(l1 - l0)}" rx="{f(lw / 2)}" fill="#EEF4EF"/>'
        )

    el.append(hand((hh % 12 + mm / 60) * 30, baton(HOUR)))
    el.append(hand((mm + ss / 60) * 6, baton(MINUTE)))
    tail, tip, w = SECOND
    el.append(
        hand(
            ss * 6,
            f'<rect x="{f(C - w / 2)}" y="{f(C - tip)}" width="{w}" height="{f(tip + tail)}" rx="1.2" fill="#F4F6F8"/>'
            f'<rect x="{f(C - 3)}" y="{f(C + tail - 22)}" width="6" height="22" rx="3" fill="#CBD1D7"/>'
            f'<circle cx="{C}" cy="{C}" r="7" fill="#CBD1D7"/><circle cx="{C}" cy="{C}" r="2.5" fill="#858E97"/>',
        )
    )

    sweep = (
        "conic-gradient(from 0deg, rgba(255,255,255,0) 0%, rgba(0,0,0,.2) 12.5%, rgba(255,255,255,0) 25%, "
        "rgba(255,255,255,.15) 37.5%, rgba(255,255,255,0) 50%, rgba(0,0,0,.2) 62.5%, rgba(255,255,255,0) 75%, "
        "rgba(255,255,255,.15) 87.5%, rgba(255,255,255,0) 100%)"
    )
    # conic-gradient 0deg is 12 o'clock and runs clockwise, matching WFF's SweepGradient here.
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Sunburst Navy preview</title>
<style>
  html,body{{margin:0;background:#000}}
  .face{{position:relative;width:{SIZE}px;height:{SIZE}px;border-radius:50%;overflow:hidden;
    background:radial-gradient(circle at 50% 50%, #2C4C86 0%, #1A3368 60%, #0A1636 100%);
    font-family:Roboto,'Noto Sans',Arial,sans-serif}}
  .sweep{{position:absolute;inset:0;border-radius:50%;background:{sweep}}}
  svg{{position:absolute;inset:0}}
</style></head><body>
<div class="face"><div class="sweep"></div>
<svg width="{SIZE}" height="{SIZE}" viewBox="0 0 {SIZE} {SIZE}">
<defs><linearGradient id="steel" x1="0" x2="1" y1="0" y2="0">
<stop offset="0" stop-color="#F4F6F8"/><stop offset=".5" stop-color="#F4F6F8"/>
<stop offset=".5" stop-color="#AEB6BE"/><stop offset="1" stop-color="#AEB6BE"/></linearGradient></defs>
{chr(10).join(el)}
</svg></div></body></html>
"""


def main():
    xml_path = ROOT / "app/src/main/res/raw/watchface.xml"
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    xml_path.write_text(build_xml())
    preview = ROOT / "preview/preview.html"
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_text(build_preview())
    print(f"wrote {xml_path.relative_to(ROOT)} and {preview.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
