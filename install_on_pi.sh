#!/usr/bin/env bash
set -euo pipefail

# Helper install script for Raspberry Pi OS (Bookworm/Bullseye) to set up
# hzeller/rpi-rgb-led-matrix Python environment and install departure board service.
# Run on the Pi:  curl -fsSL https://raw.githubusercontent.com/<youruser>/departure-board/main/install_on_pi.sh | bash
# (Adjust repo URL if needed.)

if [[ $(id -u) -ne 0 ]]; then
  echo "Please run as root (sudo)." >&2
  exit 1
fi

REPO_DIR="/home/pi/departure-board"
SERVICE_FILE="departure-board.service"

apt-get update
apt-get install -y git python3 python3-pip python3-dev build-essential libgraphicsmagick++-dev libwebp-dev libjpeg-dev zlib1g-dev libfreetype6-dev libopenjp2-7-dev libtiff5-dev

# Clone or update repository (assumes you have already copied it; adjust if using git clone)
if [[ -d "$REPO_DIR" ]]; then
  echo "Repository directory already exists at $REPO_DIR (skipping clone)."
else
  echo "Cloning repository (adjust URL if private fork)..."
  sudo -u pi git clone https://github.com/<youruser>/departure-board "$REPO_DIR"
fi

# Install Python deps (requests only) - rgbmatrix is built from source.
pip3 install --upgrade pip
pip3 install -r "$REPO_DIR/requirements.txt"

# Build hzeller/rpi-rgb-led-matrix (if not already)
RGB_SRC="/home/pi/rpi-rgb-led-matrix"
if [[ ! -d "$RGB_SRC" ]]; then
  sudo -u pi git clone https://github.com/hzeller/rpi-rgb-led-matrix.git "$RGB_SRC"
fi
cd "$RGB_SRC"
make build-python PYTHON=$(command -v python3)
# Install Python binding (creates rgbmatrix package)
cd bindings/python
python3 setup.py install

# Copy systemd service unit
cp "$REPO_DIR/$SERVICE_FILE" /etc/systemd/system/$SERVICE_FILE
systemctl daemon-reload
systemctl enable $SERVICE_FILE
# Don't start yet; allow editing ExecStart first if needed.
echo "Service installed but not started. Edit /etc/systemd/system/$SERVICE_FILE then run: systemctl start departure-board.service"

echo "Done. Common next steps:"
echo "  sudo systemctl edit --full departure-board.service   # adjust stop name, brightness"
echo "  sudo systemctl start departure-board.service"
echo "  journalctl -u departure-board.service -f              # follow logs"
