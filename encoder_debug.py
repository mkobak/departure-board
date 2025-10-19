#!/usr/bin/env python3
"""Rotary encoder wiring/debug console tool for Raspberry Pi (BCM numbering).

Run this on the Pi to see raw edge events and debounced button presses.

Examples:
  sudo python3 encoder_debug.py --clk 7 --dt 9 --sw 11
  sudo python3 encoder_debug.py --clk 7 --sw 11 --no-dt

Notes:
- Uses internal pull-ups by default (typical wiring: SW/CLK/DT -> GPIOs, other side to GND).
- Prints on every edge for CLK/DT, and prints debounced PRESS/RELEASE for SW.
- If DT is wired, on each CLK rising edge it prints inferred direction (+ for CW, - for CCW).
"""
from __future__ import annotations

import argparse
import time
import sys
from datetime import datetime

try:
    import RPi.GPIO as GPIO  # type: ignore
    HAVE_GPIO = True
except Exception:
    GPIO = None  # type: ignore
    HAVE_GPIO = False


def ts() -> str:
    return datetime.now().strftime('%H:%M:%S.%f')[:-3]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Rotary encoder debug console")
    ap.add_argument('--clk', type=int, default=7, help='BCM pin for CLK (A)')
    ap.add_argument('--dt', type=int, default=9, help='BCM pin for DT (B)')
    ap.add_argument('--sw', type=int, default=11, help='BCM pin for SW (button)')
    ap.add_argument('--no-dt', action='store_true', help='Ignore DT (directionless)')
    ap.add_argument('--pull', choices=['up','down','none'], default='up', help='Internal pull resistor')
    ap.add_argument('--debounce-ms', type=int, default=120, help='Debounce window for SW press/release')
    ap.add_argument('--interval', type=float, default=0.005, help='Polling interval seconds for SW debounce loop')
    ap.add_argument('--verbose', action='store_true', help='Log periodic levels in addition to edges')
    args = ap.parse_args(argv)

    if not HAVE_GPIO:
        print("RPi.GPIO not available. Run on a Raspberry Pi.", file=sys.stderr)
        return 2

    clk = int(args.clk)
    dt = None if args.no_dt else int(args.dt)
    sw = int(args.sw)

    GPIO.setmode(GPIO.BCM)  # type: ignore[attr-defined]
    if args.pull == 'up':
        pull = GPIO.PUD_UP  # type: ignore[attr-defined]
    elif args.pull == 'down':
        pull = GPIO.PUD_DOWN  # type: ignore[attr-defined]
    else:
        pull = GPIO.PUD_OFF  # type: ignore[attr-defined]

    # Setup pins
    GPIO.setup(clk, GPIO.IN, pull_up_down=pull)  # type: ignore[attr-defined]
    if dt is not None:
        GPIO.setup(dt, GPIO.IN, pull_up_down=pull)  # type: ignore[attr-defined]
    GPIO.setup(sw, GPIO.IN, pull_up_down=pull)  # type: ignore[attr-defined]

    # Initial levels
    clk0 = GPIO.input(clk)  # type: ignore[attr-defined]
    dt0 = GPIO.input(dt) if dt is not None else None  # type: ignore[attr-defined]
    sw0 = GPIO.input(sw)  # type: ignore[attr-defined]
    print(f"{ts()} init: CLK={clk0} DT={'n/a' if dt is None else dt0} SW={sw0} pull={args.pull}")

    # Edge callbacks for CLK/DT
    def edge_cb(pin: int) -> None:
        try:
            level = GPIO.input(pin)  # type: ignore[attr-defined]
            if pin == clk:
                if dt is not None and level == 1:
                    dts = GPIO.input(dt)  # type: ignore[attr-defined]
                    direction = '+' if dts == 0 else '-'
                    print(f"{ts()} CLK {'RISING' if level else 'FALLING'} dt={dts} ROT={direction}")
                else:
                    print(f"{ts()} CLK {'RISING' if level else 'FALLING'}")
            elif dt is not None and pin == dt:
                print(f"{ts()} DT  {'RISING' if level else 'FALLING'}")
        except Exception as e:
            print(f"{ts()} edge error: {e}", file=sys.stderr)

    GPIO.add_event_detect(clk, GPIO.BOTH, callback=edge_cb)  # type: ignore[attr-defined]
    if dt is not None:
        GPIO.add_event_detect(dt, GPIO.BOTH, callback=edge_cb)  # type: ignore[attr-defined]

    # Debounced SW loop
    deb_s = max(0.02, min(0.2, args.debounce_ms / 1000.0))
    sw_raw_last = sw0
    sw_raw_change_t = time.time()
    sw_debounced = sw0
    sw_last_debounced = sw0
    last_levels_log = 0.0

    print("Press Ctrl+C to exit. Rotate and click to see events...")
    try:
        while True:
            now = time.time()
            try:
                sw_raw = GPIO.input(sw)  # type: ignore[attr-defined]
            except Exception:
                sw_raw = 1
            if sw_raw != sw_raw_last:
                sw_raw_last = sw_raw
                sw_raw_change_t = now
            else:
                if (now - sw_raw_change_t) >= deb_s:
                    sw_debounced = sw_raw
            if sw_debounced != sw_last_debounced:
                if sw_last_debounced == 1 and sw_debounced == 0:
                    print(f"{ts()} SW PRESS (debounced)")
                elif sw_last_debounced == 0 and sw_debounced == 1:
                    print(f"{ts()} SW RELEASE (debounced)")
                sw_last_debounced = sw_debounced

            if args.verbose and now - last_levels_log >= 0.5:
                c = GPIO.input(clk)  # type: ignore[attr-defined]
                d = GPIO.input(dt) if dt is not None else 'n/a'  # type: ignore[attr-defined]
                s = GPIO.input(sw)  # type: ignore[attr-defined]
                print(f"{ts()} levels: CLK={c} DT={d} SW={s}")
                last_levels_log = now

            time.sleep(max(0.001, args.interval))
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        try:
            GPIO.remove_event_detect(clk)  # type: ignore[attr-defined]
        except Exception:
            pass
        if dt is not None:
            try:
                GPIO.remove_event_detect(dt)  # type: ignore[attr-defined]
            except Exception:
                pass
        try:
            GPIO.cleanup([clk] + ([dt] if dt is not None else []) + [sw])  # type: ignore[attr-defined]
        except Exception:
            pass
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
