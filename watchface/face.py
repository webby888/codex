"""Shared geometry and palette for the Sunburst Navy watch face.

Canvas is 480x480, the Galaxy Watch Ultra's native resolution, so images map 1:1 to pixels.
Radii are fractions of the dial radius R, measured from photos of the original watch.
"""

import math

SIZE = 480
C = SIZE / 2
R = SIZE / 2

# Light comes from the upper left; shadows fall down and to the right.
LIGHT = (-0.6, -0.8)

MARKER_IN, MARKER_OUT = 0.73 * R, 0.955 * R
MARKER_3_IN = 0.86 * R  # shortened to make room for the date window
MARKER_W = 11
TICK_IN, TICK_OUT = 0.815 * R, 0.85 * R
RING_R = 0.70 * R  # thin silver half-ring from 12 to 6
TRI_TOP, TRI_TIP, TRI_HALF_W = 0.96 * R, 0.79 * R, 0.095 * R
RIM_IN = 0.972 * R

DATE_CX, DATE_CY = C + 0.60 * R, C
DATE_W, DATE_H = 50, 36  # outer frame
DATE_BORDER = 4

# Hands: (length to tip, tail length, half width). Pivot is the dial centre.
HOUR = dict(tip=0.52 * R, tail=0.10 * R, half=8.5, lume_from=0.13 * R)
MINUTE = dict(tip=0.88 * R, tail=0.10 * R, half=6.5, lume_from=0.17 * R)
SECOND = dict(tip=0.84 * R, tail=0.28 * R)

# Hand height above the dial, expressed as shadow offset in px (dx, dy).
SHADOW_OFFSET = {"hour": (2, 3), "minute": (3, 4), "second": (4, 6)}

READOUT_Y = C + 0.40 * R
READOUT_W, READOUT_H = 112, 38
READOUT_LEFT_X = C - READOUT_W - 4
READOUT_RIGHT_X = C + 6

PRINT = "#FFE3E8EE"  # dial printing color


def polar(deg, r):
    a = math.radians(deg)
    return C + r * math.sin(a), C - r * math.cos(a)
