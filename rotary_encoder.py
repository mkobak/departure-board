#!/usr/bin/env python3
"""Simple rotary encoder interface for Raspberry Pi.

Hardware (pins per user wiring):
  CLK (A phase)  -> GPIO10 (BOARD pin 19)
  DT  (B phase)  -> GPIO9  (BOARD pin 21)
  SW  (switch)   -> GPIO25 (BOARD pin 22)
  VCC -> 3V3 (pin 17)  IMPORTANT: use 3.3V, not 5V
  GND -> any ground (pin 20)

Design goals:
- Lightweight, no external deps besides RPi.GPIO (preferred minimal install) or fallback to gpiozero.
- Debounced edge detection using bouncetime in event detection (coarse, but fine for menu toggle).
- Provide callback on rotation direction: +1 for clockwise, -1 for counter-clockwise (subject to mechanical definition; swap if reversed).
- Provide callback on button press (short press) – currently optional (not used yet by main script but available for future features).

Usage:
    from rotary_encoder import RotaryEncoder
    enc = RotaryEncoder(on_rotate=lambda delta: print('rot', delta))
    enc.start()
    ... (loop) ...
    enc.stop()

If RPi.GPIO is not available (e.g. running on dev machine), the class becomes a no-op stub.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

try:  # Prefer RPi.GPIO
    import RPi.GPIO as GPIO  # type: ignore
    _HAVE_GPIO = True
except Exception:  # noqa: BLE001
    GPIO = None  # type: ignore
    _HAVE_GPIO = False

try:
    # Optional import: if gpiozero is present but RPi.GPIO missing, you could implement alt logic.
    # For now we just no-op if RPi.GPIO missing.
    import gpiozero  # type: ignore  # noqa: F401
except Exception:  # noqa: BLE001
    pass


class RotaryEncoder:
    def __init__(
        self,
        pin_clk: int = 10,
        pin_dt: int = 9,
        pin_sw: int = 25,
        on_rotate: Optional[Callable[[int], None]] = None,
        on_button: Optional[Callable[[], None]] = None,
        debounce_ms: int = 4,
        button_debounce_ms: int = 120,
    ) -> None:
        self.pin_clk = pin_clk
        self.pin_dt = pin_dt
        self.pin_sw = pin_sw
        self.on_rotate = on_rotate
        self.on_button = on_button
        self.debounce_ms = debounce_ms
        self.button_debounce_ms = button_debounce_ms
        self._running = False
        self._last_button_time = 0.0
        self._last_clk_state: Optional[int] = None

    def start(self) -> None:
        if not _HAVE_GPIO:
            return
        if self._running:
            return
        # All GPIO attribute access guarded by _HAVE_GPIO, but static analyzers on non-Pi
        # systems see GPIO as None; add type: ignore to suppress false positives.
        GPIO.setmode(GPIO.BCM)  # type: ignore[attr-defined]
        GPIO.setup(self.pin_clk, GPIO.IN, pull_up_down=GPIO.PUD_UP)  # type: ignore[attr-defined]
        GPIO.setup(self.pin_dt, GPIO.IN, pull_up_down=GPIO.PUD_UP)  # type: ignore[attr-defined]
        GPIO.setup(self.pin_sw, GPIO.IN, pull_up_down=GPIO.PUD_UP)  # type: ignore[attr-defined]
        self._last_clk_state = GPIO.input(self.pin_clk)  # type: ignore[attr-defined]
        # Use edge detection on CLK; sample DT to determine direction.
        GPIO.add_event_detect(self.pin_clk, GPIO.BOTH, callback=self._clk_callback, bouncetime=self.debounce_ms)  # type: ignore[attr-defined]
        GPIO.add_event_detect(self.pin_sw, GPIO.FALLING, callback=self._button_callback, bouncetime=self.button_debounce_ms)  # type: ignore[attr-defined]
        self._running = True

    def stop(self) -> None:
        if not _HAVE_GPIO:
            return
        if not self._running:
            return
        try:
            GPIO.remove_event_detect(self.pin_clk)  # type: ignore[attr-defined]
            GPIO.remove_event_detect(self.pin_sw)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
        GPIO.cleanup([self.pin_clk, self.pin_dt, self.pin_sw])  # type: ignore[attr-defined]
        self._running = False

    # Internal callbacks --------------------------------------------------
    def _clk_callback(self, channel: int) -> None:  # noqa: D401, ANN001
        if not _HAVE_GPIO:
            return
        if self.on_rotate is None:
            return
        try:
            clk_state = GPIO.input(self.pin_clk)  # type: ignore[attr-defined]
            dt_state = GPIO.input(self.pin_dt)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return
        # Determine direction: typical encoder logic -> if CLK changed, compare DT
        if clk_state != self._last_clk_state:
            # If DT != CLK -> clockwise else counter-clockwise (may need swap; test physically)
            if dt_state != clk_state:
                delta = 1
            else:
                delta = -1
            self._last_clk_state = clk_state
            try:
                self.on_rotate(delta)
            except Exception:  # noqa: BLE001
                pass

    def _button_callback(self, channel: int) -> None:  # noqa: D401, ANN001
        if not _HAVE_GPIO:
            return
        now = time.time()
        if now - self._last_button_time < (self.button_debounce_ms / 1000.0):
            return
        self._last_button_time = now
        if self.on_button:
            try:
                self.on_button()
            except Exception:  # noqa: BLE001
                pass


__all__ = ["RotaryEncoder"]
