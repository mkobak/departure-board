#!/usr/bin/env python3
"""GPIO pin scanner – finds which pins the rotary encoder is actually wired to.

Reads ALL free GPIO pins (not used by the RGB matrix HAT) and prints
which ones change when you rotate or press the encoder.

Usage:
    sudo python3 gpio_scan.py

Then:
  1. Do nothing for 3 seconds (baseline)
  2. Slowly rotate clockwise – note which pins change
  3. Slowly rotate counter-clockwise – note which pins change
  4. Press and release the button – note which pin changes

The output will tell you the ACTUAL BCM GPIO numbers your encoder is wired to.
"""
import time
import sys

try:
    import RPi.GPIO as GPIO
except ImportError:
    print("RPi.GPIO not available. Run this on the Raspberry Pi.")
    sys.exit(1)

# Pins used by adafruit-hat RGB matrix – do NOT read these
MATRIX_PINS = {4, 5, 6, 12, 13, 16, 17, 20, 21, 22, 23, 24, 26, 27}
# I2C (RTC on HAT)
I2C_PINS = {2, 3}
SKIP = MATRIX_PINS | I2C_PINS

# All BCM GPIOs on the Pi Zero 2W header
ALL_GPIO = set(range(0, 28))
# Scan these
SCAN_PINS = sorted(ALL_GPIO - SKIP)
# That gives us: 0, 1, 7, 8, 9, 10, 11, 14, 15, 18, 19, 25

def main():
    print("=== GPIO Pin Scanner for Rotary Encoder ===")
    print(f"Scanning BCM pins: {SCAN_PINS}")
    print(f"Skipping (matrix HAT): {sorted(MATRIX_PINS)}")
    print()

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    for pin in SCAN_PINS:
        try:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        except Exception as e:
            print(f"  Warning: could not setup GPIO {pin}: {e}")
            SCAN_PINS.remove(pin) if pin in SCAN_PINS else None

    # Read initial state
    state = {}
    for pin in SCAN_PINS:
        try:
            state[pin] = GPIO.input(pin)
        except Exception:
            state[pin] = -1

    print("Initial pin states (with internal pull-up enabled):")
    for pin in SCAN_PINS:
        phys = _bcm_to_physical(pin)
        print(f"  GPIO {pin:2d} (header pin {phys:2d}) = {state[pin]}")

    print()
    print("Watching for changes... Interact with the encoder now.")
    print("(Ctrl+C to quit)")
    print()
    print("  Timestamp      | Pin(s) changed          | All pin states")
    print("  " + "-" * 70)

    change_count = {}
    for pin in SCAN_PINS:
        change_count[pin] = 0

    try:
        while True:
            changed = []
            for pin in SCAN_PINS:
                try:
                    val = GPIO.input(pin)
                except Exception:
                    continue
                if val != state[pin]:
                    old = state[pin]
                    state[pin] = val
                    changed.append((pin, old, val))
                    change_count[pin] += 1

            if changed:
                ts = time.strftime('%H:%M:%S') + f".{int(time.time()*1000)%1000:03d}"
                parts = []
                for pin, old, new in changed:
                    phys = _bcm_to_physical(pin)
                    parts.append(f"GPIO{pin}(pin{phys}):{old}->{new}")
                # Compact state line
                state_str = " ".join(f"{p}={'H' if state[p] else 'L'}" for p in SCAN_PINS)
                print(f"  {ts} | {', '.join(parts):24s} | {state_str}")

            time.sleep(0.001)  # 1ms poll

    except KeyboardInterrupt:
        print()
        print()
        print("=== Summary: pins that changed ===")
        active = [(pin, count) for pin, count in change_count.items() if count > 0]
        if not active:
            print("  NO pins changed at all! Check:")
            print("  - Are the encoder wires actually clipped onto the stacking header?")
            print("  - Is VCC connected to 3.3V and GND to ground?")
            print("  - Try wiggling/reseating the wire clips")
        else:
            active.sort(key=lambda x: -x[1])
            print(f"  {'GPIO':>6} {'Pin':>6} {'Changes':>8}  Likely function")
            print(f"  {'----':>6} {'---':>6} {'-------':>8}  ----------------")
            for pin, count in active:
                phys = _bcm_to_physical(pin)
                # Heuristic: CLK/DT change a lot with rotation, SW changes less (just press/release)
                if count <= 4:
                    guess = "<-- probably SW (button)"
                elif len(active) >= 2 and count == max(c for _, c in active):
                    guess = "<-- probably CLK"
                elif len(active) >= 3:
                    guess = "<-- probably DT"
                else:
                    guess = ""
                print(f"  GPIO{pin:2d} pin{phys:2d}  {count:>8}  {guess}")
            print()
            print("  Use these pin numbers in the code:")
            pins = [p for p, _ in active]
            if len(pins) >= 3:
                print(f"    --enc-clk {pins[0]} --enc-dt {pins[1]} --enc-sw {pins[2]}")
            elif len(pins) == 2:
                print(f"    --enc-clk {pins[0]} --enc-sw {pins[1]}")
                print("    (DT not detected — only 2 pins changed)")
            elif len(pins) == 1:
                print(f"    Only 1 pin changed (GPIO {pins[0]}). All encoder signals")
                print("    might be on the same pin, or some wires are disconnected.")
    finally:
        GPIO.cleanup(SCAN_PINS)


# BCM GPIO to physical header pin mapping (Pi Zero 2W / 40-pin header)
_BCM_TO_PHYS = {
    0: 27, 1: 28, 2: 3, 3: 5, 4: 7, 5: 29, 6: 31, 7: 26,
    8: 24, 9: 21, 10: 19, 11: 23, 12: 32, 13: 33, 14: 8,
    15: 10, 16: 36, 17: 11, 18: 12, 19: 35, 20: 38, 21: 40,
    22: 15, 23: 16, 24: 18, 25: 22, 26: 37, 27: 13,
}

def _bcm_to_physical(bcm: int) -> int:
    return _BCM_TO_PHYS.get(bcm, 0)


if __name__ == '__main__':
    main()
