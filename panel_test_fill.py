#!/usr/bin/env python3
"""Solid fill test for HUB75 panels using hzeller/rpi-rgb-led-matrix.

Use this to isolate hardware/power issues:
- Fill the panel with a static color (no redraws) and observe flicker.
- Measure 5V at the panel under load while the fill is displayed.

Examples:
  sudo python3 panel_test_fill.py --color amber --brightness 50 \
    --rows 64 --cols 128 --gpio-mapping adafruit-hat --limit-refresh-hz 240

Note: Run on the Pi with the rgbmatrix library installed; root is required for GPIO.
"""
from __future__ import annotations

import argparse
import sys
import time

try:
    from rgbmatrix import RGBMatrix, RGBMatrixOptions  # type: ignore
except Exception:
    print("rgbmatrix library not available; run on a Raspberry Pi with the library installed.", file=sys.stderr)
    sys.exit(2)


COLORS = {
    "white": (255, 255, 255),
    "amber": (255, 140, 0),
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "cyan": (0, 255, 255),
    "magenta": (255, 0, 255),
    "black": (0, 0, 0),
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Solid fill test for HUB75 panel")
    p.add_argument("--rows", type=int, default=64)
    p.add_argument("--cols", type=int, default=128)
    p.add_argument("--chain", type=int, default=1)
    p.add_argument("--parallel", type=int, default=1)
    p.add_argument("--brightness", type=int, default=40)
    p.add_argument("--gpio-mapping", default="adafruit-hat")
    p.add_argument("--limit-refresh-hz", type=int, default=None)
    p.add_argument("--slowdown-gpio", type=int, choices=[0,1,2,3,4], default=None)
    p.add_argument("--pwm-lsb-ns", type=int, default=None)
    p.add_argument("--dither-bits", type=int, default=1)
    p.add_argument("--pwm-bits", type=int, default=None)
    p.add_argument("--panel-type", default=None)
    p.add_argument("--led-rgb-sequence", default=None)
    p.add_argument("--disable-hardware-pulsing", action="store_true")
    p.add_argument("--color", choices=sorted(COLORS.keys()), default="amber",
                   help="Fill color to display")
    p.add_argument("--seconds", type=int, default=20, help="Display duration")
    return p.parse_args()


def main() -> int:
    opts = parse_args()
    options = RGBMatrixOptions()
    options.rows = opts.rows
    options.cols = opts.cols
    options.chain_length = opts.chain
    options.parallel = opts.parallel
    options.brightness = opts.brightness
    # Map deprecated name to the correct attribute if necessary
    try:
        options.hardware_mapping = opts.gpio_mapping  # type: ignore[attr-defined]
    except AttributeError:
        if hasattr(options, 'gpio_mapping'):
            setattr(options, 'gpio_mapping', opts.gpio_mapping)
    if opts.limit_refresh_hz is not None:
        options.limit_refresh_rate_hz = opts.limit_refresh_hz
    if opts.slowdown_gpio is not None:
        options.gpio_slowdown = opts.slowdown_gpio
    if opts.pwm_lsb_ns is not None:
        options.pwm_lsb_nanoseconds = opts.pwm_lsb_ns
    if opts.dither_bits is not None:
        options.pwm_dither_bits = opts.dither_bits
    if opts.pwm_bits is not None:
        options.pwm_bits = opts.pwm_bits
    if opts.panel_type:
        options.panel_type = opts.panel_type
    if opts.led_rgb_sequence:
        options.led_rgb_sequence = opts.led_rgb_sequence
    if opts.disable_hardware_pulsing:
        options.disable_hardware_pulsing = True

    matrix = RGBMatrix(options=options)
    off = matrix.CreateFrameCanvas()
    r, g, b = COLORS[opts.color]
    # Solid fill once; then keep swapping the same buffer, no per-frame drawing cost
    for y in range(off.height):
        for x in range(off.width):
            off.SetPixel(x, y, r, g, b)
    off = matrix.SwapOnVSync(off)
    # Keep the image displayed
    time.sleep(opts.seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
