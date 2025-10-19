#!/usr/bin/env python3
"""Simple rotary encoder interface for Raspberry Pi.

Hardware (pins per user wiring):
    CLK (A phase)  -> GPIO10 (BOARD pin 19)
    DT  (B phase)  -> (optional) GPIO9 (BOARD pin 21)
    SW  (switch)   -> GPIO7  (BOARD pin 26)
  VCC -> 3V3 (pin 17)  IMPORTANT: use 3.3V, not 5V
  GND -> any ground (pin 20)

Design goals:
- Lightweight, no external deps besides RPi.GPIO (preferred minimal install) or fallback to gpiozero.
- Debounced edge detection using bouncetime in event detection (coarse, but fine for menu toggle).
- Directionless mode supported (default): use only CLK and SW. Each detent on CLK triggers on_rotate(+1), regardless of direction.
- Directional mode (optional): if DT is wired and directionless=False, +1 for clockwise, -1 for counter-clockwise using DT sampled at CLK rising edge.
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
from typing import Callable, Optional, Dict, Tuple
import threading
import os
import stat

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
        pin_clk: int = 7,   # Updated project default (working setup)
        pin_dt: Optional[int] = 9,  # Optional; keeps direction data if wired
        pin_sw: int = 11,  # Updated project default push button
        on_rotate: Optional[Callable[[int], None]] = None,
        on_button: Optional[Callable[[], None]] = None,
        debounce_ms: int = 4,
        button_debounce_ms: int = 120,
        force_polling: bool = False,
        debug: bool = False,
        steps_per_detent: Optional[int] = None,  # If None, auto: 1 when directionless, else 4
        directionless: bool = True,  # Default to directionless so CLK-only works out-of-the-box
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
        self._poll_thread: Optional[threading.Thread] = None
        self._use_polling = False
        self._force_polling = force_polling
        self._debug = debug
        # Mode
        self._directionless = bool(directionless or self.pin_dt is None)

        # Movement accumulation (for detent filtering)
        if steps_per_detent is None:
            # In directionless mode, we typically get one useful rising edge per detent.
            self._steps_per_detent = 1 if self._directionless else 4
        else:
            self._steps_per_detent = max(1, steps_per_detent)
        self._movement: int = 0

        # Quadrature decoding state (kept for potential future full-table usage)
        self._last_state: Optional[int] = None  # 2-bit state: (clk<<1)|dt
        # Transition table: (prev, new) -> incremental step (+/-1)
        # Valid CW sequence: 00->01->11->10->00  (each +1) => net +4
        # Valid CCW sequence: 00->10->11->01->00 (each -1) => net -4
        self._TRANSITIONS: Dict[Tuple[int,int], int] = {
            (0,1): +1, (1,3): +1, (3,2): +1, (2,0): +1,  # CW
            (0,2): -1, (2,3): -1, (3,1): -1, (1,0): -1,  # CCW
        }
        # Edge-based decoding state (prefer rising edge of CLK only)
        self._last_clk_level: Optional[int] = None
        self._last_clk_edge_time: float = 0.0
        # Button state for polling latch
        self._sw_last_level = None  # type: ignore[assignment]

    def start(self) -> None:
        if not _HAVE_GPIO:
            return
        if self._running:
            return
        # All GPIO attribute access guarded by _HAVE_GPIO, but static analyzers on non-Pi
        # systems see GPIO as None; add type: ignore to suppress false positives.
        try:
            GPIO.setmode(GPIO.BCM)  # type: ignore[attr-defined]
            GPIO.setup(self.pin_clk, GPIO.IN, pull_up_down=GPIO.PUD_UP)  # type: ignore[attr-defined]
            if not self._directionless and self.pin_dt is not None:
                GPIO.setup(self.pin_dt, GPIO.IN, pull_up_down=GPIO.PUD_UP)  # type: ignore[attr-defined]
            GPIO.setup(self.pin_sw, GPIO.IN, pull_up_down=GPIO.PUD_UP)  # type: ignore[attr-defined]
            clk0 = GPIO.input(self.pin_clk)  # type: ignore[attr-defined]
            dt0 = GPIO.input(self.pin_dt) if (not self._directionless and self.pin_dt is not None) else 1  # type: ignore[attr-defined]
            self._last_clk_state = clk0
            self._last_state = (clk0 << 1) | (dt0 & 1)
            self._last_clk_level = clk0
            if self._debug:
                uid = getattr(os, 'getuid', lambda: 'n/a')()
                gid = getattr(os, 'getgid', lambda: 'n/a')()
                print(f"[RotaryEncoder] UID={uid} GID={gid} polling={self._force_polling}")
                for dev in ("/dev/gpiomem","/dev/mem"):
                    try:
                        st = os.stat(dev)
                        mode = stat.filemode(st.st_mode)
                        print(f"[RotaryEncoder] {dev} exists mode={mode} owner={st.st_uid}:{st.st_gid}")
                        if os.access(dev, os.R_OK|os.W_OK):
                            print(f"[RotaryEncoder] Access RW OK for {dev}")
                        else:
                            print(f"[RotaryEncoder] Access RW DENIED for {dev}")
                    except FileNotFoundError:
                        print(f"[RotaryEncoder] {dev} missing")
            if self._debug:
                try:
                    sw0 = GPIO.input(self.pin_sw)  # type: ignore[attr-defined]
                    print(f"[RotaryEncoder] Initial CLK={clk0} DT={'n/a' if self._directionless else dt0} SW={sw0}")
                except Exception:
                    pass
            if not self._force_polling:
                try:
                    # Primary strategy: hardware event detection on CLK rising edge only
                    GPIO.add_event_detect(self.pin_clk, GPIO.RISING, callback=self._clk_callback, bouncetime=self.debounce_ms)  # type: ignore[attr-defined]
                    GPIO.add_event_detect(self.pin_sw, GPIO.FALLING, callback=self._button_callback, bouncetime=self.button_debounce_ms)  # type: ignore[attr-defined]
                except RuntimeError:
                    # Fallback to polling if event detection not possible
                    self._force_polling = True
            if self._force_polling:
                self._use_polling = True
                def _poll():  # inner thread function
                    last_dbg = 0.0
                    while self._running:
                        try:
                            clk_state = GPIO.input(self.pin_clk)  # type: ignore[attr-defined]
                            # Rising-edge-of-CLK decoding to suppress single-line noise
                            if self._last_clk_level is None:
                                self._last_clk_level = clk_state
                            if clk_state != self._last_clk_level:
                                # Edge detected
                                now_t = time.time()
                                rising = (self._last_clk_level == 0 and clk_state == 1)
                                self._last_clk_level = clk_state
                                # Only act on rising edges with simple debounce
                                if rising and (now_t - self._last_clk_edge_time) >= (self.debounce_ms / 1000.0):
                                    self._last_clk_edge_time = now_t
                                    # Directionless: every detent counts as +1; directional uses DT sample
                                    if self._directionless:
                                        step = +1
                                    else:
                                        dt_state = GPIO.input(self.pin_dt) if self.pin_dt is not None else 1  # type: ignore[attr-defined]
                                        step = +1 if dt_state == 0 else -1
                                    self._movement += step
                                    if abs(self._movement) >= self._steps_per_detent:
                                        delta = 1 if self._movement > 0 else -1
                                        self._movement = 0
                                        if self.on_rotate:
                                            try:
                                                if self._debug:
                                                    print(f"[RotaryEncoder] detent {delta}")
                                                self.on_rotate(delta)
                                            except Exception:  # noqa: BLE001
                                                pass
                            # periodic debug of raw pin states
                            if self._debug:
                                now = time.time()
                                if now - last_dbg >= 0.2:
                                    try:
                                        sw_state = GPIO.input(self.pin_sw)  # type: ignore[attr-defined]
                                        if self._directionless:
                                            print(f"[RotaryEncoder] CLK={clk_state} SW={sw_state}")
                                        else:
                                            dt_dbg = GPIO.input(self.pin_dt) if self.pin_dt is not None else 'n/a'  # type: ignore[attr-defined]
                                            print(f"[RotaryEncoder] CLK={clk_state} DT={dt_dbg} SW={sw_state}")
                                    except Exception:
                                        pass
                                    last_dbg = now
                            # Button polling with press-latch (active low). Trigger only on high->low transition.
                            if self.on_button:
                                try:
                                    sw_level = GPIO.input(self.pin_sw)  # type: ignore[attr-defined]
                                except Exception:
                                    sw_level = 1
                                if self._sw_last_level is None:
                                    self._sw_last_level = sw_level
                                if self._sw_last_level == 1 and sw_level == 0:
                                    nowp = time.time()
                                    if nowp - self._last_button_time >= (self.button_debounce_ms / 1000.0):
                                        self._last_button_time = nowp
                                        try:
                                            if self._debug:
                                                print("[RotaryEncoder] button FALLING (press)")
                                            self.on_button()
                                        except Exception:  # noqa: BLE001
                                            pass
                                self._sw_last_level = sw_level
                            time.sleep(0.002)
                        except Exception:
                            time.sleep(0.01)
                self._running = True  # mark before starting thread
                self._poll_thread = threading.Thread(target=_poll, daemon=True)
                self._poll_thread.start()
                return
        except RuntimeError as e:  # typical /dev/mem permission issues during basic setup
            raise RuntimeError(
                f"GPIO init failed early ({e}). Steps: ensure /dev/gpiomem accessible, no conflicting daemon, run with sudo or gpio group."  # noqa: E501
            ) from e
        except Exception:
            raise
        self._running = True

    def stop(self) -> None:
        if not _HAVE_GPIO:
            return
        if not self._running:
            return
        try:
            if not self._use_polling:
                GPIO.remove_event_detect(self.pin_clk)  # type: ignore[attr-defined]
                GPIO.remove_event_detect(self.pin_sw)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
        # Cleanup only configured pins
        pins = [self.pin_clk, self.pin_sw]
        if not self._directionless and self.pin_dt is not None:
            pins.append(self.pin_dt)
        try:
            GPIO.cleanup(pins)  # type: ignore[attr-defined]
        except Exception:
            pass
        self._running = False
        if self._poll_thread and self._poll_thread.is_alive():
            # Thread will exit naturally on next loop since _running False.
            self._poll_thread = None

    # Internal callbacks --------------------------------------------------
    def _clk_callback(self, channel: int) -> None:  # noqa: D401, ANN001
        if not _HAVE_GPIO:
            return
        if self.on_rotate is None:
            return
        # Edge-based: called on CLK rising due to event detector setup
        now = time.time()
        if (now - self._last_clk_edge_time) < (self.debounce_ms / 1000.0):
            return
        self._last_clk_edge_time = now
        try:
            if self._directionless:
                step = +1
            else:
                dt_state = GPIO.input(self.pin_dt) if self.pin_dt is not None else 1  # type: ignore[attr-defined]
                step = +1 if dt_state == 0 else -1
        except Exception:  # noqa: BLE001
            return
        self._movement += step
        if abs(self._movement) >= self._steps_per_detent:
            delta = 1 if self._movement > 0 else -1
            self._movement = 0
            try:
                if self._debug:
                    print(f"[RotaryEncoder] detent {delta}")
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
