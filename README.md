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
│   ├── reminders.py             # Pickup reminder schedule (compost/trash/cardboard)
│   ├── brightness.py            # Night dimming schedule + LED visibility check
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
--brightness 0-100     Panel brightness during the day (default 40)
--night-brightness N   Panel brightness during night hours (default: same as --brightness)
--night-start H        Hour night dimming begins (default 21)
--night-end H          Hour night dimming ends (default 6; start == end disables)
--screensaver-brightness N        Screensaver brightness, day (default 15)
--screensaver-brightness-night N  Screensaver brightness, night (default: same as day)
--force-reminder TEXT  Debug: always show TEXT as the screensaver reminder line
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

## Weather Screens

Two weather screens (Basel, Zürich) use Open-Meteo (no API key). Besides the current
temperature, min/max, wind and real-feel, the bottom line shows a precipitation outlook
built from the 15-minute forecast:

| Line | Meaning |
|---|---|
| `Rain from 13:45` | dry now, first wet slot today at 13:45 |
| `Rain until 14:30` | raining now, first dry slot at 14:30 (`Rain now` if it doesn't stop today) |
| `No rain today` | nothing above the threshold for the rest of today |
| `Rain tomorrow 09:00` / `No rain tomorrow` | from 20:00 the outlook covers tonight and tomorrow |

`Snow` replaces `Rain` when the slot reports snowfall. A slot counts as wet at
`PRECIP_THRESHOLD_MM` (0.1 mm per 15 min); the evening switch hour is `PRECIP_EVENING_HOUR`.
Both live in [departure_board/weather.py](departure_board/weather.py). The line is recomputed
on every redraw from the cached forecast, so `from`/`until` times stay correct between fetches.

## Screensaver, Reminders & Night Dimming

After `--screensaver-timeout` seconds without encoder input the panel shows only the
clock, jumping to a new random spot every minute.

**Pickup reminders.** From 20:00 on the evening before a pickup until 09:00 on the pickup
day, the screensaver adds a `Reminder: …` line on the bottom text row. It shifts left/right
each minute and the clock stays clear of it. The schedule lives in
[departure_board/reminders.py](departure_board/reminders.py):

- Compost: every Thursday
- Trash: every Tuesday and Friday
- Cardboard: every 4th Wednesday, anchored on 2026-09-09 (`CARDBOARD_ANCHOR`, 28-day period)

Edit the constants there to change days, hours or the cardboard anchor date. To check the
layout at any time of day run with `--force-reminder "Reminder: Cardboard" --screensaver-timeout 6`.

**Night dimming.** Between `--night-start` and `--night-end` (default 21:00-06:00) the panel
switches to `--night-brightness` and the screensaver to `--screensaver-brightness-night`.
The switch is logged as `[brightness] night mode on/off` in the journal.

**Why very low values show nothing.** The LED library maps each colour channel through a
CIE1931 curve to an 11-bit PWM level, and `--pwm-bits N` discards the lowest `11-N` bits.
With `--pwm-bits 7` any level below 16/2047 renders as OFF: at amber the green channel dies
below hardware brightness 13 (or screensaver value 13) and red below 7 (screensaver 8). At startup the
service prints the resulting PWM levels for every configured value and a
`[brightness] WARNING` if one would be invisible:

```bash
journalctl -u departure-board.service -b | grep brightness
```

Safe values with `--pwm-bits 7`: hardware brightness >= 20, screensaver brightness >= 15.
Visible is not the same as stable, though: on this panel screensaver values below 30
(tested 20, 25, 26) flicker because the LEDs run on only the shortest PWM pulses, so 30 is
the practical screensaver floor day and night. Night dimming therefore mainly affects the
main screens (hardware brightness 60 -> 40).

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

### Known bad speaker (Berrybase / Jieli UAC)

The original micro-USB speaker (Jieli chipset) does not survive a USB host reset while it
stays powered: after a cold boot *and* after `sudo reboot` it is completely absent from
`lsusb` (not even a failed enumeration in `dmesg`), and only a physical replug sometimes
revives it. On a Pi Zero the USB port's 5V cannot be switched in software, so the dwc2
rebind in `usb-rescan.sh` cannot help. Verified 2026-09-04. Fixes are hardware only: a
different speaker (C-Media CM108/CM119 or TI PCM2704 based devices enumerate reliably), or a
GPIO-switched 5V line on the speaker cable so the board can power-cycle it at boot.

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
| Flicker | Refresh rate too low (measure with `--show-refresh`) | Lower `--pwm-lsb-ns` (50 is the library minimum); see the note below |
| Dark panel at night / dim screensaver invisible | Value below the PWM floor for `--pwm-bits` | Check `journalctl` for `[brightness] WARNING`; raise `--night-brightness` / `--screensaver-brightness-night` |
| Wrong colors / mapping | Mapping flag mismatch | Try `--gpio-mapping adafruit-hat` |
| Text truncated too much | Panel size or chain mismatch | Adjust `--cols`/`--rows`/`--chain`/`--parallel` |
| ImportError rgbmatrix | Binding not installed in venv | Rebuild with venv python & reinstall |
| API errors / 429 | Too many requests | Increase `--refresh` interval (>=30s) |

**Refresh rate and flicker (Pi Zero 2 W, 128x64 panel).** The library doubles the OE pulse
across all 11 internal bit planes starting from `--pwm-lsb-ns`, and `--pwm-bits N` only drops
the *shortest* planes. With 7 bits the displayed pulses are lsb x 16 ... lsb x 1024, so the
frame time is dominated by the long pulses, not by shifting data: at lsb 100 ns the panel ran
at 130 Hz and each dropped bit plane gained only ~6 Hz. Halving the LSB to 50 ns (the library
minimum) gave 220 Hz and removed the visible flicker; `--slowdown-gpio 0` smears the image on
this panel. A shorter LSB lowers the duty cycle, so `--brightness` was raised 60 -> 65 (night
40 -> 43, screensaver 30 -> 33) to keep the same light output. `--limit-refresh-hz 200` pins
the rate below the maximum so it stays constant and short stalls are absorbed. On the Pi,
`cmdline.txt` carries the library's recommended core isolation
`isolcpus=domain,managed_irq,3 nohz_full=3 rcu_nocbs=3 irqaffinity=0,1,2` (plain `isolcpus=3`
leaves interrupts and the timer tick on the refresh core, which shows as a brief dip every
few seconds), the CPU governor is `performance`, and WiFi power saving is off. Do not run the
service with `--encoder-debug`: it logs five lines per second to the journal and the periodic
journal flush to the SD card stalls the refresh thread. Measured 2026-09-04.

## Uninstall

```bash
sudo systemctl disable --now departure-board.service
sudo rm /etc/systemd/system/departure-board.service
sudo systemctl daemon-reload
rm -rf /home/<user>/departure-board /home/<user>/rpi-rgb-led-matrix
```

## API Courtesy

Avoid very short refresh intervals (<15s). Default 30s balances timeliness and API load.
