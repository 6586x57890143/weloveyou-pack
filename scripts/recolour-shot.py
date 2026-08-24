#!/usr/bin/env python3
"""Recolour a Prism Launcher screenshot onto the wly palette.

    scripts/recolour-shot.py raw.png assets/prism-import.png [--box x0,y0,x1,y1]

Prism's accent is a theme colour that differs per user, so moving it to our pink
is not a lie about the application. The layout is never touched: recognising the
real window is the entire point of showing it, and a screenshot that disagrees
with what someone sees on their own screen is worse than no screenshot.

Two things the first attempt got wrong, recorded so the next one does not:

- **Warm the greys, do not remap their luminance.** Mapping value onto a ramp
  from the ground colour to the text colour lifted the whole window two stops
  and turned a dark dialog into a light one. Multiplying by the ground colour's
  own channel ratios keeps every pixel exactly as dark as it was.
- **Land the accent on the target, not near it.** Scaling value by a constant
  darkened Prism's #B25679 to #C48596 rather than reaching #E39AAE. The scale
  has to be derived from the source accent so that colour maps exactly.

Needs Pillow, which is why this is a hand-run script and not part of CI.
"""

from __future__ import annotations

import argparse
import colorsys
import sys

try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.exit("this needs Pillow: pip install pillow")

HEART = (0xE3, 0x9A, 0xAE)       # --heart, the wly accent
GROUND = (0x21, 0x1F, 0x1B)      # --bg, a warm neutral
SRC_ACCENT = (0xB2, 0x56, 0x79)  # Prism's default magenta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--box", default=None,
                    help="x0,y0,x1,y1 to outline in the accent, e.g. the URL field")
    a = ap.parse_args()

    h_h, h_s, h_v = colorsys.rgb_to_hsv(*[c / 255 for c in HEART])
    tint = (1.0, GROUND[1] / GROUND[0], GROUND[2] / GROUND[0])
    v_scale = h_v / (SRC_ACCENT[0] / 255)

    im = Image.open(a.src).convert("RGB")
    px = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            hh, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            if s < 0.12:
                px[x, y] = (round(r * tint[0]), round(g * tint[1]), round(b * tint[2]))
            elif hh > 0.88 or hh < 0.02:
                nr, ng, nb = colorsys.hsv_to_rgb(h_h, h_s, min(1.0, v * v_scale))
                px[x, y] = (round(nr * 255), round(ng * 255), round(nb * 255))
            # Launcher logos and the grass block are content, not chrome, and
            # recolouring them would make the sidebar unrecognisable.

    if a.box:
        x0, y0, x1, y1 = (int(n) for n in a.box.split(","))
        ImageDraw.Draw(im).rectangle([x0, y0, x1, y1], outline=HEART, width=2)

    im.save(a.dst)
    print("wrote %s %dx%d" % (a.dst, w, h))
    return 0


if __name__ == "__main__":
    sys.exit(main())
