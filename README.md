departure lines to stdout every refresh interval instead of drawing them.
# Departure Board (Raspberry Pi RGB LED Matrix)

Displays next Swiss public transport departures on a 128x64 RGB LED matrix
using the [transport.opendata.ch](https://transport.opendata.ch/) API and the
[hzeller/rpi-rgb-led-matrix](https://github.com/hzeller/rpi-rgb-led-matrix) library.

## Components
- Raspberry Pi Zero 2 W
- 128x64 RGB LED panel + Adafruit RGB Matrix HAT
- (Optional) Rotary encoder with push button (for switching stops)

## Repository Files
- `fetch_departures.py` – Fetch & format departures
- `matrix_departure_board.py` – Hardware rendering loop
- `demo_board.py` – Tkinter simulator
- `departure-board.service` – systemd unit
- `install_on_pi.sh` – Automated setup (venv + build)
- `requirements.txt` – Python deps (requests only)

## Quick Start (Manual, Virtual Environment)
Raspberry Pi OS Bookworm enforces PEP 668 (externally managed system Python). Use a project venv:

```bash
ssh mk@tramboard.local
sudo apt update
sudo apt install -y git python3 python3-venv python3-dev build-essential

cd /home/mk
git clone https://github.com/<youruser>/departure-board.git
cd departure-board
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Build hzeller library against venv python
cd /home/mk
git clone https://github.com/hzeller/rpi-rgb-led-matrix.git
cd rpi-rgb-led-matrix
make build-python PYTHON=/home/mk/departure-board/.venv/bin/python
cd bindings/python
/home/mk/departure-board/.venv/bin/python setup.py install

# Test run (GPIO may require sudo; try without first)
cd /home/mk/departure-board
sudo /home/mk/departure-board/.venv/bin/python matrix_departure_board.py \
	--stop "Basel, Aeschenplatz" --limit 4 --brightness 40 --gpio-mapping adafruit-hat
```

Stop with Ctrl+C.

## Using the Install Script (Automated venv)
```bash
ssh mk@tramboard.local
curl -fsSL https://raw.githubusercontent.com/<youruser>/departure-board/main/install_on_pi.sh | sudo bash
```
Then optionally edit the service:
```bash
sudo systemctl edit --full departure-board.service
sudo systemctl start departure-board.service
sudo journalctl -u departure-board.service -f
```

## Systemd Service
Example ExecStart after install script:
```
ExecStart=/home/mk/departure-board/.venv/bin/python /home/mk/departure-board/matrix_departure_board.py --stop "Basel, Aeschenplatz" --limit 4 --brightness 40 --gpio-mapping adafruit-hat
```
Adjust arguments for different stop, brightness, limit, mapping, etc.

Enable & start:
```bash
sudo systemctl enable departure-board.service
sudo systemctl start departure-board.service
```
Check status/logs:
```bash
systemctl status departure-board.service
journalctl -u departure-board.service -f
```
Disable:
```bash
sudo systemctl disable --now departure-board.service
```

## Command Line Options
```
--stop <name>          Origin stop/station (default from fetch_departures.STOP)
--dest <name>          Optional exact destination filter
--limit N              Number of departures (default fetch_departures.LIMIT)
--refresh SEC          Refresh interval (default 30)
--brightness 0-100     Panel brightness (default 40)
--rows H               Panel rows (default 64)
--cols W               Panel columns (default 128)
--gpio-mapping MAP     Hardware mapping (default adafruit-hat)
--chain N              Daisy-chained panel count
--parallel N           Parallel chains
--all                  Include all transport types (ignore default tram/train filter)
```

## Migration from Global Install
If you previously relied on global `pip3 install`:
1. Stop service: `sudo systemctl stop departure-board.service`
2. Create venv: `cd /home/mk/departure-board && python3 -m venv .venv && source .venv/bin/activate`
3. `pip install -r requirements.txt`
4. Rebuild rgbmatrix for venv: `make build-python PYTHON=.../.venv/bin/python && (cd bindings/python && .../.venv/bin/python setup.py install)`
5. Update service ExecStart to `.venv/bin/python`
6. `sudo systemctl daemon-reload && sudo systemctl restart departure-board.service`
7. Remove any unneeded global packages (optional).

## Troubleshooting
| Symptom | Cause | Fix |
|---------|-------|-----|
| No output / all dark | Service not running or crash | `journalctl -u departure-board.service -f` |
| Flicker / tearing | Refresh rate too high | Lower `--brightness`; keep limit_refresh_rate_hz moderate |
| Wrong colors / mapping | Mapping flag mismatch | Try `--gpio-mapping adafruit-hat` (maps to hardware_mapping) |
| Text truncated too much | Panel size or chain mismatch | Adjust `--cols`/`--rows`/`--chain`/`--parallel` |
| ImportError rgbmatrix | Binding not installed in venv | Rebuild with venv python & reinstall |
| API errors / 429 | Too many requests | Increase refresh interval (>=30s) |

## Developer Mode (No Hardware)
If `rgbmatrix` import fails, script prints formatted departures every cycle.

## Updating
```bash
cd /home/mk/departure-board
git pull
/home/mk/departure-board/.venv/bin/pip install -r requirements.txt --upgrade
sudo systemctl restart departure-board.service
```

## Uninstall
```bash
sudo systemctl disable --now departure-board.service
sudo rm /etc/systemd/system/departure-board.service
sudo systemctl daemon-reload
```
Optional cleanup:
```bash
rm -rf /home/mk/departure-board /home/mk/rpi-rgb-led-matrix
```

## API Courtesy
Avoid very short refresh intervals (<15s). Default 30s balances timeliness and API load.

## Next Ideas
- Scroll destinations instead of truncating
- Show delay / real-time difference
- Page through more departures
- Caching + offline fallback

---
Enjoy your live tram/train departure board!

## Rotary Encoder (Optional Stop Switching)

A rotary encoder can cycle among predefined stops (default list includes `Basel, Aeschenplatz` and `Basel, Denkmal`). When you supply a different `--stop`, it is inserted into the list. Each detent advances to the next stop; direction is ignored by default (directionless mode) so you only need a single phase pin.

### Default GPIOs (BCM numbering)

| Function | GPIO | Header Pin | Notes |
|----------|------|------------|-------|
| CLK (A)  | 7    | 26         | Directionless counting (rising edge) |
| DT (B)   | 9    | 21         | Optional; only used if directional mode later enabled |
| SW (btn) | 11   | 23         | Currently also emits pulses if miswired; short press reserved for future | 
| VCC      | 3V3  | 1 / 17     | Use 3.3V only |
| GND      | GND  | any GND    | Common ground |

If you only wire CLK and SW (no DT), rotation still works because directionless mode is the default. Every valid detent = +1.

### Changing pins
Use CLI flags `--enc-clk`, `--enc-dt`, `--enc-sw`. Example:
```bash
sudo .venv/bin/python matrix_departure_board.py --stop "Basel, Aeschenplatz" --enc-clk 7 --enc-dt 9 --enc-sw 11
```

### Polling vs interrupts
Pass `--enc-poll` if interrupts fail or you need deterministic polling (the service file uses polling by default for reliability with some HAT conflicts).

### Steps per detent
`--enc-steps-per-detent 1` is correct for directionless mode (one rising edge per detent). If you enable directional quadrature later (set `directionless=False` in code or expose a flag), you might use 2 or 4 depending on encoder resolution.

### Quick test script
```bash
python - <<'PY'
from rotary_encoder import RotaryEncoder
import time
e = RotaryEncoder(on_rotate=lambda d: print('delta', d), pin_clk=7, pin_dt=9, pin_sw=11)
e.start()
print('Rotate now (Ctrl+C to exit)')
try:
		while True:
				time.sleep(1)
except KeyboardInterrupt:
		e.stop()
PY
```

If `RPi.GPIO` is missing (e.g., running on a PC), the encoder class no-ops.

### Auto-start with systemd
The provided `departure-board.service` now includes the encoder defaults and early initialization for reliability:
```
ExecStart=/home/mk/departure-board/.venv/bin/python /home/mk/departure-board/matrix_departure_board.py \
	--stop "Basel, Aeschenplatz" --limit 4 --brightness 40 --gpio-mapping adafruit-hat \
	--encoder-early --encoder-delay 0.05 --enc-clk 7 --enc-dt 9 --enc-sw 11 \
	--enc-steps-per-detent 1 --enc-poll --rotate-min-interval 0.10 --rotate-fetch-delay 0.5
```
Enable at boot (after copying service file to `/etc/systemd/system/`):
```bash
sudo cp departure-board.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now departure-board.service
```
View logs:
```bash
journalctl -u departure-board.service -f
```
