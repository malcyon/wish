#!/usr/bin/env bash
# Launch VICE inside Xephyr with a given disk image autostarted.
#   launch.sh <disk.d64>
set -euo pipefail
DISK="${1:?usage: launch.sh <disk.d64>}"
NESTED_DISPLAY="${POR_DISPLAY:-:7}"

pkill -x x64sc  2>/dev/null || true
pkill -x Xephyr 2>/dev/null || true
sleep 1

Xephyr "$NESTED_DISPLAY" -screen 1400x1050 -title "PoR (drive)" -resizeable >/dev/null 2>&1 &
for _ in $(seq 20); do
    DISPLAY="$NESTED_DISPLAY" xdotool getdisplaygeometry >/dev/null 2>&1 && break
    sleep 0.5
done

export DISPLAY="$NESTED_DISPLAY"
exec flatpak run --share=network --env=DISPLAY="$NESTED_DISPLAY" \
    --command=x64sc net.sf.VICE \
    -speed 100 -VICIIshowstatusbar -VICIIfilter 0 \
    -VICIIaspectmode 2 -VICIIglfilter 1 \
    ${MONFLAGS:--binarymonitor -binarymonitoraddress 127.0.0.1:6502} \
    -autostart "$DISK"
