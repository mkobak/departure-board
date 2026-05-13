"""Simple non-blocking audio player for notification chimes and game sounds.

Uses ALSA's ``aplay`` (always present on Raspberry Pi OS) so no Python audio
dependencies are required. Default sounds are generated as small WAVs into a
temp directory on init, so the package ships no audio assets. Custom WAV files
can be registered to override defaults.

Design notes:
- ``play()`` is fire-and-forget: it spawns ``aplay`` via ``Popen`` and returns
  immediately. The previous playback is terminated so rapid events do not pile
  up subprocesses on the Pi Zero 2 W.
- When ``aplay`` is missing or disabled, calls are silent no-ops. This keeps
  the dev-mode (no-Pi) path working.
- Backend can later swap to ``simpleaudio``/``pygame.mixer`` for lower latency
  without changing call sites.
"""
from __future__ import annotations

import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from datetime import datetime
from typing import Dict, List, Optional, Tuple


_SAMPLE_RATE = 22050


def _write_wav(path: str, samples: List[float]) -> None:
    """Write a mono 16-bit PCM WAV. ``samples`` are floats in [-1.0, 1.0]."""
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_SAMPLE_RATE)
        frames = bytearray()
        for s in samples:
            v = max(-1.0, min(1.0, s))
            frames += struct.pack('<h', int(v * 32767))
        w.writeframes(bytes(frames))


def _tone(freq: float, duration_s: float, volume: float = 0.5,
          attack_s: float = 0.005, release_s: float = 0.02,
          shape: str = 'sine') -> List[float]:
    """Generate a tone (sine or square) with a short attack/release envelope.

    ``shape='square'`` gives the punchier 8-bit feel typical of arcade games.
    """
    n = int(_SAMPLE_RATE * duration_s)
    attack = max(1, int(_SAMPLE_RATE * attack_s))
    release = max(1, int(_SAMPLE_RATE * release_s))
    out: List[float] = []
    for i in range(n):
        if i < attack:
            env = i / attack
        elif i > n - release:
            env = max(0.0, (n - i) / release)
        else:
            env = 1.0
        phase = 2.0 * math.pi * freq * (i / _SAMPLE_RATE)
        if shape == 'square':
            sample = 1.0 if math.sin(phase) >= 0 else -1.0
        else:
            sample = math.sin(phase)
        out.append(volume * env * sample)
    return out


def _sweep(f_start: float, f_end: float, duration_s: float, volume: float = 0.5,
           shape: str = 'sine') -> List[float]:
    """Linear-frequency sweep from f_start to f_end (sine or square)."""
    n = int(_SAMPLE_RATE * duration_s)
    attack = max(1, int(_SAMPLE_RATE * 0.005))
    release = max(1, int(_SAMPLE_RATE * 0.02))
    out: List[float] = []
    phase = 0.0
    for i in range(n):
        freq = f_start + (f_end - f_start) * (i / max(1, n - 1))
        phase += 2.0 * math.pi * freq / _SAMPLE_RATE
        if i < attack:
            env = i / attack
        elif i > n - release:
            env = max(0.0, (n - i) / release)
        else:
            env = 1.0
        if shape == 'square':
            sample = 1.0 if math.sin(phase) >= 0 else -1.0
        else:
            sample = math.sin(phase)
        out.append(volume * env * sample)
    return out


def _silence(duration_s: float) -> List[float]:
    return [0.0] * int(_SAMPLE_RATE * duration_s)


def _concat(*parts: List[float]) -> List[float]:
    out: List[float] = []
    for p in parts:
        out.extend(p)
    return out


# Built-in sound generators. Each returns a list of float samples.
# Pitches roughly follow a C major scale so sequences feel musical.
_BUILTIN_SOUNDS: Dict[str, "callable"] = {
    # Notification: two-tone chime (sine, gentler than game sounds).
    'notification': lambda: _concat(
        _tone(880.0, 0.12, volume=0.5),
        _silence(0.04),
        _tone(1320.0, 0.16, volume=0.5),
    ),
    # Bootup: ascending 4-note arpeggio C5-E5-G5-C6.
    'bootup': lambda: _concat(
        _tone(523.25, 0.09, volume=0.28, shape='square'),
        _tone(659.25, 0.09, volume=0.28, shape='square'),
        _tone(783.99, 0.09, volume=0.28, shape='square'),
        _tone(1046.50, 0.18, volume=0.32, shape='square'),
    ),
    # --- Snake ---
    # Eat: short rising blip (Pac-Man dot feel).
    'snake_eat': lambda: _sweep(700.0, 1400.0, 0.07, volume=0.45, shape='square'),
    # Die: descending death sweep.
    'snake_die': lambda: _concat(
        _sweep(700.0, 110.0, 0.45, volume=0.3, shape='square'),
        _silence(0.04),
        _tone(82.0, 0.18, volume=0.25, shape='square'),
    ),
    # --- Breakout ---
    # Paddle hit: percussive low square. Short attack/release so the body of
    # the tone is audible (the default 20ms release eats short sounds). 220Hz
    # rather than 180Hz because most small USB speakers roll off below ~200Hz.
    'breakout_paddle': lambda: _tone(220.0, 0.06, volume=0.75, shape='square',
                                      attack_s=0.002, release_s=0.005),
    # Brick break: pitched per tier (0=top/red highest, 4=bottom/blue lowest).
    # Frequencies are kept above 600Hz so all tiers are audible on USB speakers,
    # while still giving a clear pitch progression across rows.
    'breakout_brick_0': lambda: _tone(1320.0, 0.07, volume=0.55, shape='square',
                                       attack_s=0.002, release_s=0.005),
    'breakout_brick_1': lambda: _tone(1100.0, 0.07, volume=0.55, shape='square',
                                       attack_s=0.002, release_s=0.005),
    'breakout_brick_2': lambda: _tone(900.0, 0.07, volume=0.55, shape='square',
                                       attack_s=0.002, release_s=0.005),
    'breakout_brick_3': lambda: _tone(750.0, 0.07, volume=0.55, shape='square',
                                       attack_s=0.002, release_s=0.005),
    'breakout_brick_4': lambda: _tone(620.0, 0.07, volume=0.55, shape='square',
                                       attack_s=0.002, release_s=0.005),
    # Wall bounce: very short click. (Currently unused — kept for future opt-in.)
    'breakout_wall': lambda: _tone(440.0, 0.02, volume=0.35, shape='square'),
    # Lose a life: descending warble.
    'breakout_lose_life': lambda: _concat(
        _tone(440.0, 0.10, volume=0.3, shape='square'),
        _tone(330.0, 0.10, volume=0.3, shape='square'),
        _tone(220.0, 0.18, volume=0.3, shape='square'),
    ),
    # Game over: longer, more dramatic descent.
    'breakout_game_over': lambda: _concat(
        _tone(523.25, 0.12, volume=0.3, shape='square'),
        _tone(392.00, 0.12, volume=0.3, shape='square'),
        _tone(311.13, 0.12, volume=0.3, shape='square'),
        _tone(196.00, 0.28, volume=0.3, shape='square'),
    ),
    # Level cleared: triumphant ascending arpeggio.
    'breakout_level': lambda: _concat(
        _tone(523.25, 0.08, volume=0.5, shape='square'),
        _tone(659.25, 0.08, volume=0.5, shape='square'),
        _tone(783.99, 0.08, volume=0.5, shape='square'),
        _tone(1046.50, 0.10, volume=0.5, shape='square'),
        _tone(1318.51, 0.20, volume=0.55, shape='square'),
    ),
    # Ball launch: rising whoosh.
    'breakout_launch': lambda: _sweep(200.0, 600.0, 0.08, volume=0.4, shape='square'),
}


class AudioPlayer:
    """Non-blocking player that maps named sounds to WAV files and plays via ``aplay``.

    Pass ``enabled=False`` (or omit ``aplay`` from PATH) to make all calls no-ops.
    """

    def __init__(self, enabled: bool = True, device: Optional[str] = None,
                 overrides: Optional[Dict[str, str]] = None,
                 quiet_start_hour: int = 22, quiet_end_hour: int = 8) -> None:
        self.enabled = enabled
        self.device = (device or '').strip() or None
        # Quiet hours: silence playback between start and end hours (24h clock).
        # Wraps midnight if start > end (e.g. 22..8 means 22:00-08:00).
        # Set start == end to disable.
        self.quiet_start_hour = int(quiet_start_hour) % 24
        self.quiet_end_hour = int(quiet_end_hour) % 24
        self._sounds: Dict[str, str] = {}
        self._tmpdir: Optional[str] = None
        # Active playbacks. Allow some overlap so rapid arcade events (e.g. brick
        # ticks) don't cut each other off, but cap to avoid runaway process spam.
        self._active: List[subprocess.Popen] = []
        self._max_concurrent: int = 4
        self._aplay = shutil.which('aplay')
        if self.enabled and self._aplay is None:
            print('[audio] aplay not found on PATH; audio disabled', file=sys.stderr)
            self.enabled = False
        if self.enabled:
            self._tmpdir = tempfile.mkdtemp(prefix='departure-board-audio-')
            for name, gen in _BUILTIN_SOUNDS.items():
                path = os.path.join(self._tmpdir, f'{name}.wav')
                try:
                    _write_wav(path, gen())
                    self._sounds[name] = path
                except Exception as e:  # noqa: BLE001
                    print(f'[audio] failed to generate sound {name!r}: {e}', file=sys.stderr)
            # Apply user overrides (custom WAV file paths)
            for name, path in (overrides or {}).items():
                if not path:
                    continue
                if not os.path.isfile(path):
                    print(f'[audio] override for {name!r} not found: {path}', file=sys.stderr)
                    continue
                self._sounds[name] = path

    def register(self, name: str, path: str) -> None:
        """Register or replace a named sound with a WAV file on disk."""
        if path and os.path.isfile(path):
            self._sounds[name] = path

    def _in_quiet_hours(self, now: Optional[datetime] = None) -> bool:
        if self.quiet_start_hour == self.quiet_end_hour:
            return False
        h = (now or datetime.now()).hour
        if self.quiet_start_hour < self.quiet_end_hour:
            return self.quiet_start_hour <= h < self.quiet_end_hour
        # Window wraps midnight: e.g. start=22, end=8 -> hours 22,23,0..7
        return h >= self.quiet_start_hour or h < self.quiet_end_hour

    def play(self, name: str) -> None:
        """Play a registered sound by name. Fire-and-forget; never raises."""
        if not self.enabled:
            return
        if self._in_quiet_hours():
            return
        path = self._sounds.get(name)
        if not path:
            return
        try:
            # Reap finished playbacks before checking the concurrent cap.
            self._active = [p for p in self._active if p.poll() is None]
            if len(self._active) >= self._max_concurrent:
                return
            cmd: List[str] = [self._aplay or 'aplay', '-q']
            if self.device:
                cmd += ['-D', self.device]
            cmd.append(path)
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._active.append(proc)
        except Exception as e:  # noqa: BLE001
            print(f'[audio] play({name!r}) failed: {e}', file=sys.stderr)
