#!/usr/bin/env python3
"""Render the photo-style bitmap assets for the Sunburst Navy watch face.

Writes PNGs into app/src/main/res/drawable-nodpi/ plus preview images. Run this after
changing artwork; the PNGs are committed, so CI does not need to re-render them.

Requires: python3 with numpy + Pillow, and node with the `playwright` package and a
Chromium build (used to rasterise the SVG layers with anti-aliasing and filters).
Everything is rendered at 2x and downsampled for clean edges.
"""

import base64
import io
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from face import (
    C, DATE_BORDER, DATE_CX, DATE_CY, DATE_H, DATE_W, HOUR, LIGHT, MARKER_3_IN, MARKER_IN,
    MARKER_OUT, MARKER_W, MINUTE, R, READOUT_H, READOUT_LEFT_X, READOUT_RIGHT_X, READOUT_W,
    READOUT_Y, RIM_IN, RING_R, SECOND, SHADOW_OFFSET, SIZE, TICK_IN, TICK_OUT, TRI_HALF_W,
    TRI_TIP, TRI_TOP, polar,
)

ROOT = Path(__file__).resolve().parent
DRAWABLE = ROOT / "app/src/main/res/drawable-nodpi"
PREVIEW_DIR = ROOT / "preview"
SS = 2  # supersampling factor


def f(v):
    return f"{v:.2f}".rstrip("0").rstrip(".")


def lerp_hex(a, b, t):
    t = min(max(t, 0.0), 1.0)
    ca = [int(a[i : i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb))


def steel(t):
    """Polished steel tone for a facet with relative brightness t in [0, 1]."""
    return lerp_hex("#454d57", "#fdfeff", t)


# =============================================================================
# Sunburst dial texture (numpy)
# =============================================================================


def sunburst_png():
    n = SIZE * SS
    rng = np.random.default_rng(7)
    ys, xs = np.mgrid[0:n, 0:n].astype(np.float64) + 0.5
    dx, dy = xs - n / 2, ys - n / 2
    r = np.hypot(dx, dy) / (n / 2)
    theta = np.arctan2(dx, -dy) % (2 * np.pi)  # clock angle, 0 at 12, clockwise

    r_px = np.maximum(np.hypot(dx, dy), 1.0)

    def angular_noise(samples, smooth):
        """Angular noise box-filtered over each pixel's angular width (anti-aliased)."""
        v = rng.normal(size=samples)
        k = np.ones(smooth) / smooth
        v = np.real(np.fft.ifft(np.fft.fft(v) * np.fft.fft(k, samples)))
        v /= v.std()
        cum = np.concatenate([[0.0], np.cumsum(np.tile(v, 3))])  # three turns, for wrap-around

        def integral(pos):
            i0 = np.floor(pos).astype(int)
            return cum[i0] + (pos - i0) * (cum[i0 + 1] - cum[i0])

        pos = theta / (2 * np.pi) * samples
        half = np.maximum(samples / (2 * np.pi * r_px), 0.5)  # half a pixel, in samples
        half = np.minimum(half, samples / 4)
        lo = pos - half + samples  # shift into the second turn so lo stays positive
        avg = (integral(lo + 2 * half) - integral(lo)) / (2 * half)
        # Averaging lowers contrast; restore it for the lines a pixel can still resolve.
        return avg * np.sqrt(np.minimum(2 * half / smooth, 6))

    fine = angular_noise(16000, 3)  # individual brushed lines
    coarse = angular_noise(420, 6)  # broader brushing bands
    # Radially brushed metal lit from the upper left: bright "bow-tie" on the 10:30-4:30 axis.
    axis = math.radians(315)
    bow = np.cos(theta - axis) ** 2
    bow = bow**3
    intensity = (
        0.30
        + 0.34 * bow
        + 0.12 * np.exp(-((r / 0.33) ** 2))
        - 0.10 * r**2
        # brushed lines converge at the centre; fade them there to avoid moire
        + (0.022 + 0.035 * bow) * fine * np.clip((r - 0.04) / 0.30, 0, 1)
        + 0.022 * coarse * np.clip(r / 0.2, 0, 1)
        + 0.006 * rng.normal(size=r.shape)
    )
    stops = np.array([0.0, 0.28, 0.52, 0.78, 1.0])
    colors = np.array(
        [[5, 12, 38], [13, 31, 82], [26, 56, 124], [56, 94, 164], [104, 140, 202]], dtype=np.float64
    )
    t = np.clip(intensity, 0, 1)
    rgb = np.stack([np.interp(t, stops, colors[:, c]) for c in range(3)], axis=-1)
    img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


# =============================================================================
# SVG building blocks
# =============================================================================

SHADOW_FILTER = (
    '<filter id="applied" x="-30%" y="-30%" width="160%" height="160%">'
    '<feDropShadow dx="1.5" dy="2.0" stdDeviation="1.1" flood-color="#000" flood-opacity="0.7"/>'
    '<feDropShadow dx="0" dy="0" stdDeviation="1.6" flood-color="#000" flood-opacity="0.35"/>'
    "</filter>"
)


def facet_brightness(deg):
    """Return (clockwise-facet, counter-clockwise-facet) brightness for a radial bar."""
    p = (math.cos(math.radians(deg)), math.sin(math.radians(deg)))
    d = p[0] * LIGHT[0] + p[1] * LIGHT[1]
    return 0.60 + 0.40 * d, 0.60 - 0.40 * d


def marker(deg, r_in, r_out, fill_cw=None, fill_ccw=None, outline="rgba(15,20,30,.55)"):
    a, b = facet_brightness(deg)
    fill_cw = fill_cw or steel(a)
    fill_ccw = fill_ccw or steel(b)
    w = MARKER_W / 2
    y0, y1 = C - r_out, C - r_in
    return (
        f'<g transform="rotate({f(deg)} {f(C)} {f(C)})">'
        f'<rect x="{f(C)}" y="{f(y0)}" width="{f(w)}" height="{f(y1 - y0)}" fill="{fill_cw}"/>'
        f'<rect x="{f(C - w)}" y="{f(y0)}" width="{f(w)}" height="{f(y1 - y0)}" fill="{fill_ccw}"/>'
        # bevelled ends catch the light differently
        f'<rect x="{f(C - w)}" y="{f(y0)}" width="{f(2 * w)}" height="1.4" fill="rgba(255,255,255,.35)"/>'
        f'<rect x="{f(C - w)}" y="{f(y1 - 1.4)}" width="{f(2 * w)}" height="1.4" fill="rgba(0,0,0,.25)"/>'
        f'<rect x="{f(C - w)}" y="{f(y0)}" width="{f(2 * w)}" height="{f(y1 - y0)}" fill="none" '
        f'stroke="{outline}" stroke-width="0.6"/>'
        "</g>"
    )


def triangle(fill_left=None, fill_right=None, outline="rgba(15,20,30,.55)"):
    top, tip, hw = C - TRI_TOP, C - TRI_TIP, TRI_HALF_W
    fill_left = fill_left or steel(0.60 + 0.40 * 0.6)
    fill_right = fill_right or steel(0.60 - 0.40 * 0.6)
    return (
        f'<polygon points="{f(C - hw)},{f(top)} {f(C)},{f(top)} {f(C)},{f(tip)}" fill="{fill_left}"/>'
        f'<polygon points="{f(C)},{f(top)} {f(C + hw)},{f(top)} {f(C)},{f(tip)}" fill="{fill_right}"/>'
        f'<polygon points="{f(C - hw)},{f(top)} {f(C + hw)},{f(top)} {f(C)},{f(tip)}" fill="none" '
        f'stroke="{outline}" stroke-width="0.6"/>'
    )


def all_markers(**kw):
    out = [triangle(fill_left=kw.get("fill_ccw"), fill_right=kw.get("fill_cw"), **{k: v for k, v in kw.items() if k == "outline"})]
    for h in range(1, 12):
        out.append(marker(h * 30, MARKER_3_IN if h == 3 else MARKER_IN, MARKER_OUT, **kw))
    return "".join(out)


def half_ring(stroke, width):
    x0, y0 = polar(0, RING_R)
    x1, y1 = polar(180, RING_R)
    j0a, j0b = polar(0, RING_R), polar(0, TRI_TIP)
    j1a, j1b = polar(180, RING_R), polar(180, MARKER_IN)
    return (
        f'<path d="M {f(x0)} {f(y0)} A {f(RING_R)} {f(RING_R)} 0 0 1 {f(x1)} {f(y1)}" fill="none" '
        f'stroke="{stroke}" stroke-width="{width}"/>'
        f'<line x1="{f(j0a[0])}" y1="{f(j0a[1])}" x2="{f(j0b[0])}" y2="{f(j0b[1])}" stroke="{stroke}" stroke-width="{width}"/>'
        f'<line x1="{f(j1a[0])}" y1="{f(j1a[1])}" x2="{f(j1b[0])}" y2="{f(j1b[1])}" stroke="{stroke}" stroke-width="{width}"/>'
    )


def dial_svg(texture):
    ticks = []
    for m in range(60):
        if m % 5:
            (x1, y1), (x2, y2) = polar(m * 6, TICK_IN), polar(m * 6, TICK_OUT)
            ticks.append(
                f'<line x1="{f(x1)}" y1="{f(y1)}" x2="{f(x2)}" y2="{f(y2)}" stroke="rgba(226,233,242,.82)" stroke-width="1.5"/>'
            )
    # lighter, less brushed outer zone on the right half, outside the silver ring
    zx0, zy0 = polar(0, RING_R)
    zx1, zy1 = polar(180, RING_R)
    ox0, oy0 = polar(0, RIM_IN)
    ox1, oy1 = polar(180, RIM_IN)
    zone = (
        f'<path d="M {f(zx0)} {f(zy0)} A {f(RING_R)} {f(RING_R)} 0 0 1 {f(zx1)} {f(zy1)} '
        f'L {f(ox1)} {f(oy1)} A {f(RIM_IN)} {f(RIM_IN)} 0 0 0 {f(ox0)} {f(oy0)} Z" fill="rgba(150,180,230,.07)"/>'
    )
    dx, dy = DATE_CX - DATE_W / 2, DATE_CY - DATE_H / 2
    ax, ay, aw, ah = dx + DATE_BORDER, dy + DATE_BORDER, DATE_W - 2 * DATE_BORDER, DATE_H - 2 * DATE_BORDER
    date = (
        f'<rect x="{f(dx)}" y="{f(dy)}" width="{DATE_W}" height="{DATE_H}" rx="1.5" fill="url(#frame)" filter="url(#applied)"/>'
        f'<rect x="{f(ax)}" y="{f(ay)}" width="{f(aw)}" height="{f(ah)}" fill="#f2f1ec"/>'
        f'<rect x="{f(ax)}" y="{f(ay)}" width="{f(aw)}" height="{f(ah)}" fill="url(#recess)"/>'
        f'<rect x="{f(ax)}" y="{f(ay)}" width="{f(aw)}" height="{f(ah)}" fill="url(#recess_l)"/>'
    )
    return f"""
<defs>
  {SHADOW_FILTER}
  <filter id="soft"><feGaussianBlur stdDeviation="2.2"/></filter>
  <radialGradient id="vignette" cx="{f(C)}" cy="{f(C)}" r="{f(RIM_IN)}" gradientUnits="userSpaceOnUse">
    <stop offset="0.72" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity="0.32"/>
  </radialGradient>
  <radialGradient id="rim" cx="{f(C)}" cy="{f(C)}" r="{f(R)}" gradientUnits="userSpaceOnUse">
    <stop offset="{f(RIM_IN / R)}" stop-color="#1c2638"/><stop offset="1" stop-color="#04070d"/>
  </radialGradient>
  <linearGradient id="frame" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#f7f9fb"/><stop offset=".5" stop-color="#bfc6cd"/><stop offset="1" stop-color="#6f7882"/>
  </linearGradient>
  <linearGradient id="recess" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#000" stop-opacity=".38"/><stop offset=".28" stop-color="#000" stop-opacity="0"/>
  </linearGradient>
  <linearGradient id="recess_l" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#000" stop-opacity=".22"/><stop offset=".12" stop-color="#000" stop-opacity="0"/>
  </linearGradient>
  <clipPath id="face"><circle cx="{f(C)}" cy="{f(C)}" r="{f(R)}"/></clipPath>
</defs>
<g clip-path="url(#face)">
  <image href="{texture}" x="0" y="0" width="{SIZE}" height="{SIZE}"/>
  {zone}
  <circle cx="{f(C)}" cy="{f(C)}" r="{f(RIM_IN)}" fill="url(#vignette)"/>
  {''.join(ticks)}
  <g filter="url(#applied)">{half_ring('#d9e0e8', 1.8)}</g>
  <g filter="url(#applied)">{all_markers()}</g>
  {date}
  <circle cx="{f(C)}" cy="{f(C)}" r="{f((RIM_IN + R) / 2)}" fill="none" stroke="url(#rim)" stroke-width="{f(R - RIM_IN)}"/>
  <circle cx="{f(C)}" cy="{f(C)}" r="{f(RIM_IN - 1.5)}" fill="none" stroke="#000" stroke-opacity=".45" stroke-width="3" filter="url(#soft)"/>
  <circle cx="{f(C)}" cy="{f(C)}" r="{f(RIM_IN)}" fill="none" stroke="#fff" stroke-opacity=".22" stroke-width=".8"/>
</g>"""


def ambient_dial_svg():
    dim = "#2f353d"
    return f"""
<rect x="0" y="0" width="{SIZE}" height="{SIZE}" fill="#000"/>
{half_ring('rgba(150,158,168,.55)', 1.4)}
{all_markers(fill_cw=dim, fill_ccw=dim, outline='#9aa2ab')}
"""


# =============================================================================
# Hands (local coordinates: pivot at origin, hand pointing up the -y axis)
# =============================================================================


def baton_outline(spec):
    tip, tail, h = spec["tip"], spec["tail"], spec["half"]
    return [(0, -tip), (h, -tip + 2.1 * h), (h, 4), (0.62 * h, tail), (-0.62 * h, tail), (-h, 4), (-h, -tip + 2.1 * h)]


def pts(points):
    return " ".join(f"{f(x)},{f(y)}" for x, y in points)


def baton_hand_svg(spec, hub_r):
    tip, h, l0 = spec["tip"], spec["half"], spec["lume_from"]
    outline = baton_outline(spec)
    tail = spec["tail"]
    left = [(0, -tip), (0, tail), (-0.62 * h, tail), (-h, 4), (-h, -tip + 2.1 * h)]
    right = [(0, -tip), (h, -tip + 2.1 * h), (h, 4), (0.62 * h, tail), (0, tail)]
    li = h - 0.38 * h - 0.6  # lume inset half width
    lume = [(0, -tip + 1.35 * h), (li, -tip + 1.35 * h + 1.6 * li), (li, -l0), (-li, -l0), (-li, -tip + 1.35 * h + 1.6 * li)]
    return f"""
<defs>
  <linearGradient id="lume" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#f6faf3"/><stop offset="1" stop-color="#d9e3d5"/>
  </linearGradient>
  <radialGradient id="hub" cx="0.35" cy="0.3" r="0.8">
    <stop offset="0" stop-color="#ffffff"/><stop offset=".6" stop-color="#b9c1c9"/><stop offset="1" stop-color="#5d6670"/>
  </radialGradient>
</defs>
<polygon points="{pts(left)}" fill="{steel(0.95)}"/>
<polygon points="{pts(right)}" fill="{steel(0.42)}"/>
<polygon points="{pts(outline)}" fill="none" stroke="rgba(20,25,35,.55)" stroke-width="0.7"/>
<polygon points="{pts(lume)}" fill="url(#lume)" stroke="rgba(10,14,20,.6)" stroke-width="0.9"/>
<circle cx="0" cy="0" r="{f(hub_r)}" fill="url(#hub)" stroke="rgba(20,25,35,.5)" stroke-width="0.6"/>
"""


def second_outline():
    tip, tail = SECOND["tip"], SECOND["tail"]
    return [(0, -tip), (0.9, -tip + 5), (1.4, 0), (1.9, tail - 3), (0, tail), (-1.9, tail - 3), (-1.4, 0), (-0.9, -tip + 5)]


def second_hand_svg():
    return f"""
<defs>
  <linearGradient id="needle" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#ffffff"/><stop offset=".5" stop-color="#e3e8ec"/><stop offset=".5" stop-color="#9ba4ad"/><stop offset="1" stop-color="#bfc6cd"/>
  </linearGradient>
  <radialGradient id="cap" cx="0.35" cy="0.3" r="0.8">
    <stop offset="0" stop-color="#ffffff"/><stop offset=".55" stop-color="#c3cad1"/><stop offset="1" stop-color="#58616b"/>
  </radialGradient>
</defs>
<polygon points="{pts(second_outline())}" fill="url(#needle)" stroke="rgba(20,25,35,.45)" stroke-width="0.4"/>
<circle cx="0" cy="0" r="6.2" fill="url(#cap)" stroke="rgba(20,25,35,.5)" stroke-width="0.6"/>
<circle cx="0" cy="0" r="2.1" fill="#6b737c"/><circle cx="-0.5" cy="-0.6" r="0.8" fill="#e8ecef"/>
"""


def silhouette_svg(polys, circles, blur):
    shapes = "".join(f'<polygon points="{pts(p)}"/>' for p in polys)
    shapes += "".join(f'<circle cx="0" cy="0" r="{f(r)}"/>' for r in circles)
    return (
        f'<defs><filter id="b" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="{blur}"/></filter></defs>'
        f'<g fill="#000" fill-opacity=".55" filter="url(#b)">{shapes}</g>'
    )


HAND_ASSETS = {
    # name: (svg builder, local bounds (minx, miny, maxx, maxy))
    "hour": (lambda: baton_hand_svg(HOUR, 9.5), (-10, -HOUR["tip"], 10, HOUR["tail"])),
    "minute": (lambda: baton_hand_svg(MINUTE, 7.6), (-8, -MINUTE["tip"], 8, MINUTE["tail"])),
    "second": (second_hand_svg, (-7, -SECOND["tip"], 7, SECOND["tail"])),
}
SHADOW_ASSETS = {
    "hour": ([baton_outline(HOUR)], [9.5], 2.0),
    "minute": ([baton_outline(MINUTE)], [7.6], 2.2),
    "second": ([second_outline()], [6.2], 1.6),
}


def hand_box(bounds, pad):
    minx, miny, maxx, maxy = bounds
    x0, y0 = math.floor(minx - pad), math.floor(miny - pad)
    w, h = math.ceil(maxx + pad) - x0, math.ceil(maxy + pad) - y0
    return x0, y0, w, h


# =============================================================================
# Rendering
# =============================================================================

NODE_RENDER = r"""
const { chromium } = require('playwright');
const jobs = JSON.parse(require('fs').readFileSync(process.argv[2], 'utf8'));
(async () => {
  const browser = await chromium.launch();
  for (const job of jobs) {
    const page = await browser.newPage({ viewport: { width: job.w, height: job.h } });
    await page.setContent(job.html, { waitUntil: 'load' });
    await page.screenshot({ path: job.out, omitBackground: true, clip: { x: 0, y: 0, width: job.w, height: job.h } });
    await page.close();
  }
  await browser.close();
})();
"""


def page(svg_body, view_box, w, h, scale):
    return (
        '<!doctype html><html><body style="margin:0;background:transparent">'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w * scale}" height="{h * scale}" viewBox="{view_box}" '
        f'style="display:block">{svg_body}</svg></body></html>'
    )


def render(jobs):
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "render.js"
        script.write_text(NODE_RENDER)
        job_file = Path(tmp) / "jobs.json"
        job_file.write_text(json.dumps(jobs))
        env = dict(os.environ)
        if "NODE_PATH" not in env:
            env["NODE_PATH"] = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
        subprocess.run(["node", str(script), str(job_file)], check=True, env=env)


def downsample(path, size):
    img = Image.open(path).convert("RGBA")
    # premultiply so transparent edges don't pick up dark fringes
    arr = np.asarray(img).astype(np.float64) / 255
    arr[..., :3] *= arr[..., 3:4]
    small = Image.fromarray((arr * 255).round().astype(np.uint8), "RGBA").resize(size, Image.LANCZOS)
    s = np.asarray(small).astype(np.float64) / 255
    alpha = s[..., 3:4]
    s[..., :3] = np.where(alpha > 0, s[..., :3] / np.maximum(alpha, 1e-6), 0)
    Image.fromarray((np.clip(s, 0, 1) * 255).round().astype(np.uint8), "RGBA").save(path, optimize=True)


def hand_layout():
    """Placement of every hand bitmap on the 480 canvas (shared with generate.py via JSON)."""
    layout = {}
    for name, (_, bounds) in HAND_ASSETS.items():
        x0, y0, w, h = hand_box(bounds, pad=2)
        layout[name] = dict(x=C + x0, y=C + y0, w=w, h=h, px=-x0 / w, py=-y0 / h)
    for name, (_, _, blur) in SHADOW_ASSETS.items():
        x0, y0, w, h = hand_box(HAND_ASSETS[name][1], pad=math.ceil(blur * 3) + 2)
        dx, dy = SHADOW_OFFSET[name]
        layout[f"{name}_shadow"] = dict(x=C + x0 + dx, y=C + y0 + dy, w=w, h=h, px=-x0 / w, py=-y0 / h)
    return layout


def main():
    DRAWABLE.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    texture = sunburst_png()
    full_box = f"0 0 {SIZE} {SIZE}"
    jobs = [
        ("dial", page(dial_svg(texture), full_box, SIZE, SIZE, SS), SIZE, SIZE),
        ("dial_ambient", page(ambient_dial_svg(), full_box, SIZE, SIZE, SS), SIZE, SIZE),
    ]
    for name, (build, bounds) in HAND_ASSETS.items():
        x0, y0, w, h = hand_box(bounds, pad=2)
        jobs.append((f"hand_{name}", page(build(), f"{x0} {y0} {w} {h}", w, h, SS), w, h))
    for name, (polys, circles, blur) in SHADOW_ASSETS.items():
        x0, y0, w, h = hand_box(HAND_ASSETS[name][1], pad=math.ceil(blur * 3) + 2)
        jobs.append((f"hand_{name}_shadow", page(silhouette_svg(polys, circles, blur), f"{x0} {y0} {w} {h}", w, h, SS), w, h))

    render([dict(html=html, out=str(DRAWABLE / f"{n}.png"), w=w * SS, h=h * SS) for n, html, w, h in jobs])
    for n, _, w, h in jobs:
        downsample(DRAWABLE / f"{n}.png", (w, h))

    layout = hand_layout()
    (ROOT / "hand_layout.json").write_text(json.dumps(layout, indent=2, sort_keys=True) + "\n")
    render_previews(layout)
    print("rendered", ", ".join(n for n, *_ in jobs))


# =============================================================================
# Previews: composite the real assets at 10:08:36 on the 2nd
# =============================================================================


def data_uri(path):
    return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode()


def render_previews(layout, hh=10, mm=8, ss=36, day=2, steps="8,421", bpm="72"):
    angles = {"hour": (hh % 12 + mm / 60) * 30, "minute": (mm + ss / 60) * 6, "second": ss * 6}

    def img(name, key=None, ambient=False):
        lay = layout[key or name]
        src = data_uri(DRAWABLE / f"{name}.png")
        rot = angles.get((key or name).replace("_shadow", ""), 0)
        style = (
            f"position:absolute;left:{f(lay['x'])}px;top:{f(lay['y'])}px;width:{lay['w']}px;height:{lay['h']}px;"
            f"transform-origin:{f(lay['px'] * lay['w'])}px {f(lay['py'] * lay['h'])}px;transform:rotate({f(rot)}deg)"
        )
        if ambient:
            style += ";opacity:.85"
        return f'<img src="{src}" style="{style}">'

    def full(name, opacity=1):
        return f'<img src="{data_uri(DRAWABLE / f"{name}.png")}" style="position:absolute;left:0;top:0;width:{SIZE}px;height:{SIZE}px;opacity:{opacity}">'

    icons = {
        "steps": '<svg width="22" height="22" viewBox="0 0 24 24" fill="#e3e8ee"><ellipse cx="8" cy="7" rx="3.6" ry="5.2"/><ellipse cx="16" cy="13" rx="3.6" ry="5.2"/><rect x="5" y="13" width="6" height="3" rx="1.5"/><rect x="13" y="19" width="6" height="3" rx="1.5"/></svg>',
        "heart": '<svg width="22" height="22" viewBox="0 0 24 24" fill="#e3e8ee"><path d="M12 21s-7.5-4.6-10-9.3C.3 8.4 2.2 4 6.3 4c2.3 0 3.9 1.3 5.7 3.4C13.8 5.3 15.4 4 17.7 4 21.8 4 23.7 8.4 22 11.7 19.5 16.4 12 21 12 21z"/></svg>',
    }

    def readouts(opacity):
        out = []
        for x, icon, text in ((READOUT_LEFT_X, "steps", steps), (READOUT_RIGHT_X, "heart", bpm)):
            out.append(
                f'<div style="position:absolute;left:{f(x)}px;top:{f(READOUT_Y)}px;width:{READOUT_W}px;height:{READOUT_H}px;'
                f'display:flex;align-items:center;gap:6px;color:#e3e8ee;opacity:{opacity};font:500 22px/1 Roboto,Arial,sans-serif;'
                f'letter-spacing:.04em;padding-left:4px">{icons[icon]}<span>{text}</span></div>'
            )
        return "".join(out)

    aw, ah = DATE_W - 2 * DATE_BORDER, DATE_H - 2 * DATE_BORDER
    ax, ay = DATE_CX - aw / 2, DATE_CY - ah / 2

    def date(color, opacity=1):
        return (
            f'<div style="position:absolute;left:{f(ax)}px;top:{f(ay)}px;width:{f(aw)}px;height:{f(ah)}px;display:flex;'
            f'align-items:center;justify-content:center;font:500 24px/1 Roboto,Arial,sans-serif;color:{color};opacity:{opacity}">{day}</div>'
        )

    active = (
        full("dial") + date("#151a22") + readouts(1)
        + img("hand_hour_shadow", "hour_shadow") + img("hand_hour", "hour")
        + img("hand_minute_shadow", "minute_shadow") + img("hand_minute", "minute")
        + img("hand_second_shadow", "second_shadow") + img("hand_second", "second")
    )
    ambient = (
        full("dial_ambient") + date("#e3e8ee", 0.8) + readouts(0.6)
        + img("hand_hour", "hour", True) + img("hand_minute", "minute", True)
    )
    jobs = []
    for name, body in (("preview", active), ("preview_ambient", ambient)):
        html = (
            '<!doctype html><html><body style="margin:0;background:#000">'
            f'<div style="position:relative;width:{SIZE}px;height:{SIZE}px;border-radius:50%;overflow:hidden;background:#000">'
            f"{body}</div></body></html>"
        )
        jobs.append(dict(html=html, out=str(PREVIEW_DIR / f"{name}.png"), w=SIZE, h=SIZE))
    render(jobs)
    # The watch-picker preview ships inside the APK.
    Image.open(PREVIEW_DIR / "preview.png").convert("RGB").save(DRAWABLE / "preview.png", optimize=True)


if __name__ == "__main__":
    main()
