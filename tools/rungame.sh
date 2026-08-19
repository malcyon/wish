#!/usr/bin/env bash
# Launch Pool of Radiance for a reverse-engineering experiment.
#
# Runs VICE inside a nested X server (Xephyr) rather than on the desktop.
# This is not cosmetic -- it is what makes automation reliable:
#
#   * Under Wayland there is no dependable way to give an XWayland window
#     keyboard focus. `xdotool windowactivate` reports success, X11 even
#     reports VICE as _NET_ACTIVE_WINDOW, and keys still do not arrive.
#   * Inside Xephyr there is no window manager, so VICE's single window holds
#     input focus permanently and XTEST always lands on it.
#   * Keystrokes therefore cannot leak into the user's real desktop -- no
#     risk of typing into their terminal if focus wanders.
#   * The user can move, focus or ignore the Xephyr window freely; none of it
#     affects the driver.
#
# Differs from ~/.local/bin/pool-of-radiance in also enabling the binary
# monitor and using work/<name>.vfl, so the game writes to an experiment save
# disk and never to the real PORSAVE.D64 under /mnt/media.
#
#   tools/rungame.sh slots
set -euo pipefail
NAME="${1:?usage: rungame.sh <experiment-name>}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VFL="$REPO/work/$NAME.vfl"
DISKS="/mnt/media/roms/c64/Pool of Radiance Disks"
NESTED_DISPLAY="${POR_DISPLAY:-:7}"

[[ -f "$VFL" ]] || { echo "no fliplist at $VFL" >&2; exit 1; }

pkill -x x64sc  2>/dev/null || true
pkill -x Xephyr 2>/dev/null || true
sleep 1

Xephyr "$NESTED_DISPLAY" -screen 800x600 -title "PoR ($NAME, Claude-driven)" \
       -resizeable >/dev/null 2>&1 &
for _ in $(seq 20); do
    DISPLAY="$NESTED_DISPLAY" xdotool getdisplaygeometry >/dev/null 2>&1 && break
    sleep 0.5
done

# Both matter: the outer DISPLAY decides which X socket flatpak exposes to the
# sandbox, --env sets what the app inside actually connects to. Setting only
# --env silently lands the window on the host display instead.
export DISPLAY="$NESTED_DISPLAY"

exec flatpak run --share=network --env=DISPLAY="$NESTED_DISPLAY" \
    --command=x64sc net.sf.VICE \
    -flipname "$VFL" \
    -speed 100 \
    -VICIIshowstatusbar \
    -VICIIfilter 0 \
    -VICIIaspectmode 2 \
    -VICIIglfilter 1 \
    -binarymonitor -binarymonitoraddress 127.0.0.1:6502 \
    -autostart "$DISKS/POOL1.D64"
