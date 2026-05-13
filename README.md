# Departure Board (Raspberry Pi RGB LED Matrix)

Displays next Swiss public transport departures on a 128x64 RGB LED matrix
using the [transport.opendata.ch](https://transport.opendata.ch/) API and the
[hzeller/rpi-rgb-led-matrix](https://github.com/hzeller/rpi-rgb-led-matrix) library.

Features: real-time departures, weather screens, screensaver, Telegram message overlay,
rotary encoder navigation, and a Snake game.

## Hardware

- Raspberry Pi Zero 2 W
- 128x64 RGB LED panel + Adafruit RGB Matrix HAT
- (Optional) Rotary encoder with push button

## Project Structure

```
departure-board/
├── matrix_departure_board.py    # Entry point (thin wrapper)
├── fetch_departures.py          # Transport API client
├── rotary_encoder.py            # Rotary encoder driver
├── demo_board.py                # Tkinter simulator (no Pi needed)
│
├── departure_board/             # Main application package
│   ├── app.py                   # Event loop, CLI args, main()
│   ├── drawing.py               # Frame rendering (departures, weather, screensaver, etc.)
│   ├── renderer.py              # Text measurement, layout, draw helpers
│   ├── font.py                  # Shared 5x7 bitmap font
│   ├── constants.py             # Layout constants
│   ├── weather.py               # Open-Meteo weather integration
│   ├── scores.py                # High score persistence
│   └── games/
│       ├── __init__.py          # Game registry
│       └── snake.py             # Snake game
│
├── tools/                       # Hardware debug/test utilities
│   ├── encoder_debug.py         # Rotary encoder GPIO debugger
│   ├── gpio_scan.py             # Auto-discover encoder GPIO pins
│   └── panel_test_fill.py       # Panel color fill test
│
├── departure-board.service      # systemd unit file
├── install_on_pi.sh             # Automated Pi setup script
├── requirements.txt             # Python dependencies
└── .env.example                 # Telegram bot credentials template
```

## Setup

### Prerequisites

```bash
ssh <user>@<hostname>.local
sudo apt update
sudo apt install -y git python3 python3-venv python3-dev build-essential
```

### Install (Manual)

```bash
cd /home/<user>
git clone https://github.com/<youruser>/departure-board.git
cd departure-board
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Build the hzeller RGB matrix library against the venv Python:

```bash
cd /home/<user>
git clone https://github.com/hzeller/rpi-rgb-led-matrix.git
cd rpi-rgb-led-matrix
make build-python PYTHON=/home/<user>/departure-board/.venv/bin/python
cd bindings/python
/home/<user>/departure-board/.venv/bin/python setup.py install
```

Test run:

```bash
cd /home/<user>/departure-board
sudo .venv/bin/python matrix_departure_board.py \
    --stop "Basel, Aeschenplatz" --limit 4 --brightness 40 --gpio-mapping adafruit-hat
```

Stop with Ctrl+C.

### Install (Automated)

```bash
ssh <user>@<hostname>.local
curl -fsSL https://raw.githubusercontent.com/<youruser>/departure-board/main/install_on_pi.sh | sudo bash
```

Then optionally edit the service and start it:

```bash
sudo systemctl edit --full departure-board.service
sudo systemctl start departure-board.service
```

## Running as a Service

Enable and start:

```bash
sudo ln -sf /home/<user>/departure-board/departure-board.service /etc/systemd/system/departure-board.service
sudo systemctl daemon-reload
sudo systemctl enable --now departure-board.service
```

Check logs:

```bash
journalctl -u departure-board.service -f
```

Disable:

```bash
sudo systemctl disable --now departure-board.service
```

## Updating

After pulling new code:

```bash
cd /home/<user>/departure-board
git pull
.venv/bin/pip install -r requirements.txt --upgrade
sudo systemctl restart departure-board.service
```

> **Note:** If you installed the service by **copying** (not symlinking), you must also re-copy and reload:
> ```bash
> sudo cp departure-board.service /etc/systemd/system/departure-board.service
> sudo systemctl daemon-reload && sudo systemctl restart departure-board.service
> ```

## Command Line Options

```
--stop <name>          Origin stop/station (default: Basel, Aeschenplatz)
--dest <name>          Optional exact destination filter
--limit N              Number of departures (default 4)
--refresh SEC          Refresh interval in seconds (default 30)
--brightness 0-100     Panel brightness (default 40)
--rows H               Panel rows (default 64)
--cols W               Panel columns (default 128)
--gpio-mapping MAP     Hardware mapping (default adafruit-hat)
--chain N              Daisy-chained panel count
--parallel N           Parallel chains
--all                  Include all transport types
```

Advanced tuning, encoder, screensaver, and Telegram options are available.
Run `python matrix_departure_board.py --help` for the full list.

## Rotary Encoder (Optional)

A rotary encoder can cycle among predefined stops. Each detent advances to the next stop;
button press toggles the departure page. Double-click enters the game menu.
**Long-press (~3 seconds) triggers a clean shutdown** — see the section below.

## Safe Shutdown (Long-Press)

Hold the encoder button for ~3 seconds to cleanly power off the Pi. After about
1 second a "Shutting down" message with a progress bar appears on the panel;
keep holding to confirm. Release before the bar fills to abort. Once the panel
goes dark you can safely unplug. This avoids the SD-card corruption that hard
power-cuts can cause.

### One-time setup (already done by `install_on_pi.sh`)

The service user needs passwordless access to `/sbin/poweroff`:

```bash
sudo install -m 440 -o root -g root \
    ~/departure-board/departure-board-shutdown.sudoers \
    /etc/sudoers.d/departure-board-shutdown
sudo visudo -c   # should print "parsed OK" for the new file
```

If you run the service as a user other than `mk`, edit the username in
[departure-board-shutdown.sudoers](departure-board-shutdown.sudoers) before installing.

### Default GPIOs (BCM numbering)

| Function | GPIO | Header Pin | Notes |
|----------|------|------------|-------|
| VCC (+)  | 3V3  | 17         | Use 3.3V only |
| CLK (A)  | 10   | 19         | Rotation phase A |
| DT (B)   | 9    | 21         | Rotation phase B |
| SW (btn) | 11   | 23         | Push button |
| GND      | GND  | 25         | Ground |

### Changing pins

```bash
sudo .venv/bin/python matrix_departure_board.py \
    --stop "Basel, Aeschenplatz" --enc-clk 10 --enc-dt 9 --enc-sw 11
```

### Polling vs interrupts

Pass `--enc-poll` if interrupts fail or you need deterministic polling.

### Quick test

```bash
python tools/encoder_debug.py --clk 10 --dt 9 --sw 11
```

## Telegram Integration

1. Copy `.env.example` to `.env` and fill in your bot token and chat ID.
2. Or pass `--telegram-token` and `--telegram-chat-id` via CLI / service file.
3. Incoming messages display as a 30-second overlay on the board.
4. When in the game menu, messages set the player name (first 6 characters).

## Audio (Notification + Game Sounds)

A USB speaker plugged into the Pi plays:

- A **bootup** arpeggio when the service starts.
- A **two-tone chime** on incoming Telegram messages.
- **Snake**: eat-food blip, descending death sweep.
- **Breakout**: ball launch whoosh, paddle thunk, pitched brick ticks
  (higher tones for top rows), lose-life warble, game-over descent, level-up
  fanfare.

All sounds are square/sine waves generated in-process — no audio files to
ship or install. Override the Telegram chime with `--telegram-sound PATH`.

### Find your USB device

```bash
aplay -l
```

Look for the USB speaker's card name, then pass it as an ALSA device string,
for example `plughw:CARD=USB,DEV=0`. If you only have one output device, you
can omit this and the system default will be used.

### CLI flags

```
--no-audio                   Disable all sound output
--audio-device DEV           ALSA device (e.g. plughw:CARD=USB,DEV=0)
--telegram-sound PATH        Custom WAV for the notification chime
--audio-quiet-start HOUR     Quiet hours start (24h, default 22)
--audio-quiet-end HOUR       Quiet hours end (24h, default 8)
```

Audio is silenced during quiet hours (default 22:00–08:00). Set start == end to
disable. These can also be set via `.env` as `AUDIO_DEVICE`, `TELEGRAM_SOUND`,
`NO_AUDIO=1`, `AUDIO_QUIET_START`, `AUDIO_QUIET_END`.

### Requirements

`aplay` (from `alsa-utils`) must be on the Pi. It's preinstalled on Raspberry
Pi OS. If `aplay` is missing, audio is silently disabled.

## Developer Mode (No Hardware)

If `rgbmatrix` is not available, the script prints departures to stdout every cycle.

To run the Tkinter GUI simulator on any machine (no Pi needed):

```bash
pip install requests
python demo_board.py
```

## Debug Tools

Located in `tools/`:

```bash
python tools/encoder_debug.py --help    # Debug rotary encoder wiring
python tools/gpio_scan.py               # Auto-discover encoder GPIO pins
python tools/panel_test_fill.py --help   # Test panel with solid color fill
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| No output / all dark | Service not running or crash | `journalctl -u departure-board.service -f` |
| Flicker / tearing | Refresh rate too high | Lower `--brightness`; keep `--limit-refresh-hz` moderate |
| Wrong colors / mapping | Mapping flag mismatch | Try `--gpio-mapping adafruit-hat` |
| Text truncated too much | Panel size or chain mismatch | Adjust `--cols`/`--rows`/`--chain`/`--parallel` |
| ImportError rgbmatrix | Binding not installed in venv | Rebuild with venv python & reinstall |
| API errors / 429 | Too many requests | Increase `--refresh` interval (>=30s) |

## Uninstall

```bash
sudo systemctl disable --now departure-board.service
sudo rm /etc/systemd/system/departure-board.service
sudo systemctl daemon-reload
rm -rf /home/<user>/departure-board /home/<user>/rpi-rgb-led-matrix
```

## API Courtesy

Avoid very short refresh intervals (<15s). Default 30s balances timeliness and API load.
