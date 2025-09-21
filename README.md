# Departure Board (Raspberry Pi RGB LED Matrix)

Displays next Swiss public transport departures on a 128x64 (or compatible) RGB LED matrix
using the [transport.opendata.ch](https://transport.opendata.ch/) API and the
[hzeller/rpi-rgb-led-matrix](https://github.com/hzeller/rpi-rgb-led-matrix) library.

## Components
- Raspberry Pi Zero 2 W
- 128x64 RGB LED panel + Adafruit RGB Matrix HAT

## Repository Files Added
- `fetch_departures.py` – Fetch & format departures
- `matrix_departure_board.py` – Main matrix rendering loop (headless Pi)
- `demo_board.py` – Local Tkinter visual demo / development
- `departure-board.service` – systemd unit to auto-start on boot
- `install_on_pi.sh` – Helper script to build dependencies & enable service
- `requirements.txt` – Python dependency list

## Quick Start (Manual)
SSH into the Pi (example hostname `tramboard.local`):

```bash
ssh pi@tramboard.local
sudo apt update
sudo apt install -y git python3 python3-pip python3-dev build-essential
# Clone your fork
cd /home/pi
git clone https://github.com/<youruser>/departure-board.git
cd departure-board
pip3 install -r requirements.txt
# Build hzeller library
cd ~
git clone https://github.com/hzeller/rpi-rgb-led-matrix.git
cd rpi-rgb-led-matrix
make build-python PYTHON=$(command -v python3)
cd bindings/python
sudo python3 setup.py install
# Test
cd /home/pi/departure-board
sudo python3 matrix_departure_board.py --stop "Basel, Aeschenplatz" --limit 4 --brightness 40 --gpio-mapping adafruit-hat
```

Stop with Ctrl+C.

## Using the Install Script
```bash
ssh pi@tramboard.local
curl -fsSL https://raw.githubusercontent.com/<youruser>/departure-board/main/install_on_pi.sh | sudo bash
```
Then edit the service if needed:
```bash
sudo systemctl edit --full departure-board.service
sudo systemctl start departure-board.service
sudo journalctl -u departure-board.service -f
```

## Systemd Service
`/etc/systemd/system/departure-board.service` (installed from repo). Key line:
```
ExecStart=/usr/bin/env python3 /home/pi/departure-board/matrix_departure_board.py --stop "Basel, Aeschenplatz" --limit 4 --brightness 40 --gpio-mapping adafruit-hat
```
Edit arguments to change stop, brightness, limit, etc.

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

## Command Line Options (matrix_departure_board.py)
```
--stop <name>          Origin stop/station (default from fetch_departures.STOP)
--dest <name>          Optional exact destination filter
--limit N              Number of departures (default fetch_departures.LIMIT)
--refresh SEC          Refresh interval (default 30)
--brightness 0-100     Panel brightness (default 40)
--rows H               Panel rows (default 64)
--cols W               Panel columns (default 128)
--gpio-mapping MAP     GPIO mapping (default adafruit-hat)
--chain N              Daisy-chained panel count
--parallel N           Parallel chains
--all                  Include all transport types (ignore default tram/train filter)
```

## Troubleshooting
| Symptom | Cause | Fix |
|---------|-------|-----|
| No output / all dark | Service not running or crash | `journalctl -u departure-board.service -f` |
| Flicker / tearing | Refresh rate too high | Lower `--brightness` or set `options.limit_refresh_rate_hz` inside script |
| Wrong colors / mapping | Incorrect `--gpio-mapping` | Use `regular`, `adafruit-hat`, etc. |
| Text truncated too aggressively | Panel size mismatch | Adjust `--cols`/`--rows` or chain/parallel values |
| ImportError rgbmatrix | Library not built | Re-run build steps (`make build-python` + `setup.py install`) |
| API errors / 429 | Over-fetching or network issues | Increase refresh interval, check connectivity |

## Developer Mode (No Hardware)
If `rgbmatrix` library is absent (e.g., on your desktop), the script prints
departure lines to stdout every refresh interval instead of drawing them.

## Updating
Pull latest changes, then restart service:
```bash
cd /home/pi/departure-board
git pull
sudo systemctl restart departure-board.service
```

## Uninstall
```bash
sudo systemctl disable --now departure-board.service
sudo rm /etc/systemd/system/departure-board.service
sudo systemctl daemon-reload
```
(Optional) Remove sources:
```bash
rm -rf /home/pi/departure-board /home/pi/rpi-rgb-led-matrix
```

## API Courtesy
Avoid very short refresh intervals (<15s) to reduce load. Default 30s is reasonable.

## Next Ideas
- Scroll destinations instead of truncating
- Add small in-memory cache to smooth network hiccups
- Show delay (+min) indicator
- Alternate pages if more departures than fit

---
Enjoy your live tram/train departure board!
