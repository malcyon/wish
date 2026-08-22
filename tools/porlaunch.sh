#!/usr/bin/env bash
# Launch VICE on its own X display with a given disk image autostarted.
#   porlaunch.sh <disk.d64>
#
# Everything that makes this instance *this* instance comes in through the
# environment, so `tools/instance.py` can hand a slot its own copy of all of it:
#
#   POR_DISPLAY  X display          (:7 by default -- the human's session)
#   POR_VICERC   config file        (-config; unset means VICE's own)
#   MONFLAGS     monitor addresses  (6502/6510 by default)
#   PORFLAGS     anything else      (an experiment's extra flags)
#   POR_HEADLESS 1 -> Xvfb instead of Xephyr, so eight instances do not put
#                eight game windows on Donald's desktop
#
# It kills nothing.  It used to `pkill -x x64sc` and `pkill -x Xephyr` on every
# launch, which under the instance pool would kill every other agent's emulator
# and Donald's own game with it.  Teardown is a process-group kill by whoever
# started this script -- see `tools/instance.py`, "never by name".
set -euo pipefail
DISK="${1:?usage: porlaunch.sh <disk.d64>}"
NESTED_DISPLAY="${POR_DISPLAY:-:7}"

if [ "${POR_HEADLESS:-0}" = "1" ]; then
    Xvfb "$NESTED_DISPLAY" -screen 0 1400x1050x24 >/dev/null 2>&1 &
else
    Xephyr "$NESTED_DISPLAY" -screen 1400x1050 -resizeable \
        -title "PoR (${POR_SLOT:+slot }${POR_SLOT:-drive})" \
        >/dev/null 2>&1 &
fi
for _ in $(seq 20); do
    DISPLAY="$NESTED_DISPLAY" xdotool getdisplaygeometry >/dev/null 2>&1 && break
    sleep 0.5
done

export DISPLAY="$NESTED_DISPLAY"
# --die-with-parent: the flatpak's own child goes when this script's group does,
# so a torn-down slot leaves nothing behind for the next claim to trip over.
exec flatpak run --die-with-parent --share=network \
    --env=DISPLAY="$NESTED_DISPLAY" \
    --command=x64sc net.sf.VICE \
    ${POR_VICERC:+-config "$POR_VICERC"} \
    -speed 100 -VICIIshowstatusbar -VICIIfilter 0 \
    -VICIIaspectmode 2 -VICIIglfilter 1 \
    ${MONFLAGS:--binarymonitor -binarymonitoraddress 127.0.0.1:6502} \
    ${PORFLAGS:-} \
    -autostart "$DISK"
