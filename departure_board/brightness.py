"""Night-time dimming schedule and LED visibility checks.

The hzeller rpi-rgb-led-matrix library maps each 8-bit colour channel to an
11-bit PWM level through a CIE1931 curve:

    v     = c * brightness / 255          (brightness is 0-100)
    level = round(2047 * ((v + 16) / 116) ** 3)   (v / 902.3 for v <= 8)

``--pwm-bits N`` then drops the lowest ``11 - N`` bit planes, so any level
below ``2 ** (11 - N)`` is rendered as fully OFF. With the service's
``--pwm-bits 7`` that floor is 16/2047. This is why very low brightness
settings used to make the panel go completely dark.

This module is stdlib-only so it can be unit-tested without the matrix library.
"""
from __future__ import annotations

import sys
from datetime import datetime
from typing import Optional, Tuple

K_BIT_PLANES = 11


def is_night(now: Optional[datetime], start_hour: int, end_hour: int) -> bool:
    """True when ``now`` falls in [start_hour, end_hour), wrapping past midnight.

    start_hour == end_hour disables night mode entirely.
    """
    start = int(start_hour) % 24
    end = int(end_hour) % 24
    if start == end:
        return False
    h = (now or datetime.now()).hour
    if start < end:
        return start <= h < end
    return h >= start or h < end


def pwm_level(c: int, brightness: int, pwm_bits: int = K_BIT_PLANES) -> int:
    """Effective 11-bit PWM level the library will output for one channel."""
    c = max(0, min(255, int(c)))
    brightness = max(0, min(100, int(brightness)))
    v = c * brightness / 255.0
    if v <= 8:
        frac = v / 902.3
    else:
        frac = ((v + 16) / 116.0) ** 3
    level = int(round((2 ** K_BIT_PLANES - 1) * frac))
    dropped = max(0, K_BIT_PLANES - max(1, min(K_BIT_PLANES, int(pwm_bits))))
    return (level >> dropped) << dropped


def check_visibility(label: str, color: Tuple[int, int, int], brightness: int,
                     pwm_bits: int) -> bool:
    """Warn on stderr if any lit channel of ``color`` would render as OFF.

    Returns True when every non-zero channel is visible.
    """
    names = ("red", "green", "blue")
    ok = True
    for name, c in zip(names, color):
        if c <= 0:
            continue
        lvl = pwm_level(c, brightness, pwm_bits)
        if lvl == 0:
            ok = False
            print(f"[brightness] WARNING: {label}: {name}={c} at hw brightness {brightness} "
                  f"with pwm-bits {pwm_bits} maps to PWM level 0 (invisible). Raise the value.",
                  file=sys.stderr)
    if ok:
        levels = ','.join(str(pwm_level(c, brightness, pwm_bits)) for c in color)
        print(f"[brightness] {label}: color={color} hw={brightness} -> PWM levels ({levels})/2047",
              file=sys.stderr)
    return ok


def screensaver_color(dim: int, hw_brightness: int) -> Tuple[int, int, int]:
    """Amber colour the screensaver draws for ``dim`` at the given hw brightness.

    Mirrors the scaling in drawing.draw_screensaver_frame so the visibility
    check can evaluate exactly what will be drawn.
    """
    h = max(1, int(hw_brightness))
    scale = min(1.0, max(0.0, min(100.0, float(dim))) / h)
    return (int(255 * scale), int(140 * scale), 0)
