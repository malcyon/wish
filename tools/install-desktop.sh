#!/bin/sh
# Put the desktop entry and the icons where a Linux desktop will find them.
#
# Wish already calls `setDesktopFileName("wish")` and `setWindowIcon()`, but
# neither is enough on its own: **Wayland has no protocol for a client-supplied
# window icon**, so the compositor matches the window's app id against an
# installed `wish.desktop` and uses that file's `Icon=`. With no such file it
# falls back to a generic icon -- the gear.
#
# Everything goes under $HOME, so no root and nothing outside the user's own
# directories. Run it again after `tools/genicons.py` to refresh the icons.
set -eu

here=$(cd "$(dirname "$0")/.." && pwd)
apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
icons="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"

mkdir -p "$apps"
sed "s|^Exec=wish|Exec=${WISH_EXEC:-wish}|" "$here/assets/wish.desktop" \
    > "$apps/wish.desktop"

for src in "$here"/assets/icons/hicolor/*/apps/wish.png; do
    size=$(basename "$(dirname "$(dirname "$src")")")
    mkdir -p "$icons/$size/apps"
    cp "$src" "$icons/$size/apps/wish.png"
done

# Both caches are optional: the desktop reads the files either way, but a stale
# cache can keep showing the old icon until the next login.
command -v update-desktop-database >/dev/null 2>&1 &&
    update-desktop-database "$apps" || true
command -v gtk-update-icon-cache >/dev/null 2>&1 &&
    gtk-update-icon-cache -f -t "$icons" >/dev/null 2>&1 || true

echo "installed $apps/wish.desktop"
echo "installed icons into $icons"
echo "if the gear persists, log out and back in -- some shells cache per session"
