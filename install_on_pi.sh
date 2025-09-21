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

TARGET_USER="mk"
HOME_DIR="/home/${TARGET_USER}"
REPO_DIR="${HOME_DIR}/departure-board"
SERVICE_FILE="departure-board.service"
VENV_DIR="${REPO_DIR}/.venv"

apt-get update
apt-get install -y git python3 python3-pip python3-venv python3-dev build-essential libgraphicsmagick++-dev libwebp-dev libjpeg-dev zlib1g-dev libfreetype6-dev libopenjp2-7-dev libtiff5-dev

# Clone or update repository (assumes you have already copied it; adjust if using git clone)
if [[ -d "$REPO_DIR" ]]; then
  echo "Repository directory already exists at $REPO_DIR (pulling latest)."
  sudo -u "$TARGET_USER" git -C "$REPO_DIR" pull --ff-only || true
else
  echo "Cloning repository (adjust URL if private fork)..."
  sudo -u "$TARGET_USER" git clone https://github.com/<youruser>/departure-board "$REPO_DIR"
fi

chown -R "$TARGET_USER":"$TARGET_USER" "$REPO_DIR"

# Create virtual environment (PEP 668 compliant)
if [[ ! -d "$VENV_DIR" ]]; then
  sudo -u "$TARGET_USER" python3 -m venv "$VENV_DIR"
fi
sudo -u "$TARGET_USER" bash -c "source '$VENV_DIR/bin/activate' && pip install --upgrade pip && pip install -r '$REPO_DIR/requirements.txt'"

# Build hzeller/rpi-rgb-led-matrix (if not already)
RGB_SRC="${HOME_DIR}/rpi-rgb-led-matrix"
if [[ ! -d "$RGB_SRC" ]]; then
  sudo -u "$TARGET_USER" git clone https://github.com/hzeller/rpi-rgb-led-matrix.git "$RGB_SRC"
fi
cd "$RGB_SRC"
sudo -u "$TARGET_USER" make build-python PYTHON="$VENV_DIR/bin/python"
cd bindings/python
# Install rgbmatrix binding into venv using pip (wheel build) instead of deprecated setup.py install
sudo -u "$TARGET_USER" bash -c "source '$VENV_DIR/bin/activate' && pip install --no-cache-dir ."

# Copy systemd service unit
cp "$REPO_DIR/$SERVICE_FILE" /etc/systemd/system/$SERVICE_FILE
# Patch service ExecStart and paths for TARGET_USER
sed -i "s|/home/pi/departure-board|$REPO_DIR|g" /etc/systemd/system/$SERVICE_FILE
sed -i "s|/home/mk/departure-board|$REPO_DIR|g" /etc/systemd/system/$SERVICE_FILE || true
sed -i "s|ExecStart=.*python3 .*matrix_departure_board.py|ExecStart=$VENV_DIR/bin/python $REPO_DIR/matrix_departure_board.py --stop 'Basel, Aeschenplatz' --limit 4 --brightness 40 --gpio-mapping adafruit-hat|" /etc/systemd/system/$SERVICE_FILE
sed -i "s|User=pi|User=$TARGET_USER|" /etc/systemd/system/$SERVICE_FILE || true
sed -i "s|Group=pi|Group=$TARGET_USER|" /etc/systemd/system/$SERVICE_FILE || true
systemctl daemon-reload
systemctl enable $SERVICE_FILE
# Don't start yet; allow editing ExecStart first if needed.
echo "Service installed but not started. Edit /etc/systemd/system/$SERVICE_FILE then run: systemctl start departure-board.service"
echo "(Using virtual environment at $VENV_DIR)"

echo "Done. Common next steps:"
echo "  sudo systemctl edit --full departure-board.service   # adjust stop name, brightness"
echo "  sudo systemctl start departure-board.service"
echo "  journalctl -u departure-board.service -f              # follow logs"
