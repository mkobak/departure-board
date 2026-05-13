#!/usr/bin/env bash
# Rebind the Pi's USB host controller to force re-enumeration of attached
# devices after a cold boot. Works around cheap USB audio devices (e.g. the
# Berrybase / Jieli UACDemoV1.0 speaker) whose UAC chip glitches on power-up
# and gets missed by the initial bus scan, so they never appear in lsusb until
# physically replugged.
#
# The rebind effectively simulates an unplug/replug for everything on the USB
# bus. On a Pi Zero 2 W this is the only software-only path since the USB
# port has no per-port power switching.
#
# Discovers the driver dynamically so it works across Pi models:
#   * Older RPi stack: dwc_otg (Pi Zero / 1 / 2 / 3 / Zero 2 W)
#   * Mainline:        dwc2   (some configs)
#   * Pi 4 / Pi 5:     xhci-hcd via PCI (not handled here; not needed there)

set -u

rebound=0
for driver in dwc_otg dwc2; do
    drv_dir="/sys/bus/platform/drivers/${driver}"
    [ -d "$drv_dir" ] || continue
    for dev in "$drv_dir"/*.usb; do
        [ -e "$dev" ] || continue
        dev_name=$(basename "$dev")
        echo "usb-rescan: unbind ${driver}/${dev_name}"
        echo "$dev_name" > "${drv_dir}/unbind" || true
        sleep 1
        echo "usb-rescan: bind   ${driver}/${dev_name}"
        echo "$dev_name" > "${drv_dir}/bind" || true
        rebound=$((rebound + 1))
    done
done

if [ "$rebound" -eq 0 ]; then
    echo "usb-rescan: no dwc_otg/dwc2 platform device found; nothing to do"
fi

# Give udev / snd-usb-audio a moment to claim the re-enumerated device
# before the next service (departure-board.service) starts and reads
# /proc/asound/cards.
sleep 2
