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
          attack_s: float = 0.005, release_s: float = 0.02) -> List[float]:
    """Generate a sine tone with a short attack/release envelope to avoid clicks."""
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
        out.append(volume * env * math.sin(2.0 * math.pi * freq * (i / _SAMPLE_RATE)))
    return out


def _sweep(f_start: float, f_end: float, duration_s: float, volume: float = 0.5) -> List[float]:
    """Linear-frequency sweep from f_start to f_end."""
    n = int(_SAMPLE_RATE * duration_s)
    attack = max(1, int(_SAMPLE_RATE * 0.005))
    release = max(1, int(_SAMPLE_RATE * 0.02))
    out: List[float] = []
    phase = 0.0
    for i in range(n):
        t = i / _SAMPLE_RATE
        freq = f_start + (f_end - f_start) * (i / max(1, n - 1))
        phase += 2.0 * math.pi * freq / _SAMPLE_RATE
        if i < attack:
            env = i / attack
        elif i > n - release:
            env = max(0.0, (n - i) / release)
        else:
            env = 1.0
        out.append(volume * env * math.sin(phase))
    return out


def _silence(duration_s: float) -> List[float]:
    return [0.0] * int(_SAMPLE_RATE * duration_s)


def _concat(*parts: List[float]) -> List[float]:
    out: List[float] = []
    for p in parts:
        out.extend(p)
    return out


# Built-in sound generators. Each returns a list of float samples.
_BUILTIN_SOUNDS: Dict[str, "callable"] = {
    'notification': lambda: _concat(
        _tone(880.0, 0.12, volume=0.5),
        _silence(0.04),
        _tone(1320.0, 0.16, volume=0.5),
    ),
    'eat': lambda: _sweep(700.0, 1400.0, 0.08, volume=0.45),
    'game_over': lambda: _concat(
        _tone(440.0, 0.14, volume=0.5),
        _tone(330.0, 0.14, volume=0.5),
        _tone(220.0, 0.22, volume=0.5),
    ),
}


class AudioPlayer:
    """Non-blocking player that maps named sounds to WAV files and plays via ``aplay``.

    Pass ``enabled=False`` (or omit ``aplay`` from PATH) to make all calls no-ops.
    """

    def __init__(self, enabled: bool = True, device: Optional[str] = None,
                 overrides: Optional[Dict[str, str]] = None) -> None:
        self.enabled = enabled
        self.device = (device or '').strip() or None
        self._sounds: Dict[str, str] = {}
        self._tmpdir: Optional[str] = None
        self._current: Optional[subprocess.Popen] = None
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

    def play(self, name: str) -> None:
        """Play a registered sound by name. Fire-and-forget; never raises."""
        if not self.enabled:
            return
        path = self._sounds.get(name)
        if not path:
            return
        try:
            # Drop any prior playback so rapid triggers don't stack.
            if self._current is not None and self._current.poll() is None:
                try:
                    self._current.terminate()
                except Exception:  # noqa: BLE001
                    pass
            cmd: List[str] = [self._aplay or 'aplay', '-q']
            if self.device:
                cmd += ['-D', self.device]
            cmd.append(path)
            self._current = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:  # noqa: BLE001
            print(f'[audio] play({name!r}) failed: {e}', file=sys.stderr)
