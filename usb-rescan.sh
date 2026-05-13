#!/usr/bin/env bash
# Rebind the mainline dwc2 USB host controller to force re-enumeration of
# attached devices at boot. Works around the Berrybase / Jieli UAC speaker
# which fails to enumerate cleanly on the cold boot following a power-cycle.
#
# Targets dwc2 ONLY. Unbind/rebind on dwc_otg (the legacy Broadcom driver,
# default on Pi Zero / 1 / 2 / 3 / Zero 2 W) crashes the kernel USB stack —
# the script silently exits if dwc2 isn't bound to a platform device.
#
# To enable dwc2 on Pi Zero 2 W add to /boot/firmware/config.txt:
#   dtoverlay=dwc2,dr_mode=host

set -u

drv_dir="/sys/bus/platform/drivers/dwc2"
if [ ! -d "$drv_dir" ]; then
    echo "usb-rescan: dwc2 driver not present; nothing to do" >&2
    exit 0
fi

rebound=0
for dev in "$drv_dir"/*.usb; do
    [ -e "$dev" ] || continue
    dev_name=$(basename "$dev")
    echo "usb-rescan: unbind dwc2/${dev_name}"
    echo "$dev_name" > "${drv_dir}/unbind"
    sleep 1
    echo "usb-rescan: bind   dwc2/${dev_name}"
    echo "$dev_name" > "${drv_dir}/bind"
    rebound=$((rebound + 1))
done

if [ "$rebound" -eq 0 ]; then
    echo "usb-rescan: no dwc2 platform device bound; nothing to do" >&2
fi

# Let udev / snd-usb-audio claim the re-enumerated device before subsequent
# services (departure-board.service) read /proc/asound/cards.
sleep 2
