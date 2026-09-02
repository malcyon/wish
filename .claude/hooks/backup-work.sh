#!/usr/bin/env bash
# Snapshot `work/` to OneDrive, because it has been lost twice.
#
# `work/` is gitignored on purpose -- it holds the game's own bytes, which
# must never enter the repository -- so git is no protection for it at all.
# It has gone twice: `#136 (Rewrite the 80 citations of the 32 lost
# work/reports write-ups)` and `#148`, and Donald established the cause on
# 2026-09-02: he ran out of Claude quota, drove the project with Google
# Gemini for a while, and it deleted the whole directory. Probably because it
# does not read CLAUDE.md.
#
# **Snapshots, never a mirror.** An `rsync --delete` mirror would have
# faithfully replicated that `rm -rf` on its next run and destroyed the
# backup too. A dated tarball cannot be eaten by a later deletion, which is
# the entire point.
#
# A `Stop` hook rather than cron: this machine is not always on, and a hook
# fires exactly when it is on *and* `work/` has just changed. Throttled, and
# detached, so it never delays a turn.
set -euo pipefail

SRC="${CLAUDE_PROJECT_DIR:-/home/donald/src/wish}/work"
DEST="/data/OneDrive/wish-work"
STAMP="$DEST/.last"
KEEP=14
THROTTLE=$((10 * 60))

[ -d "$SRC" ] || exit 0
mkdir -p "$DEST"

# Throttle: at most one snapshot per THROTTLE seconds, however many turns run.
now=$(date +%s)
if [ -f "$STAMP" ]; then
    last=$(cat "$STAMP" 2>/dev/null || echo 0)
    [ $((now - last)) -lt "$THROTTLE" ] && exit 0
fi
echo "$now" > "$STAMP"

out="$DEST/wish-work-$(date +%Y-%m-%dT%H%M).tar.zst"

# `inst/` is emulator scratch, rebuilt by the pool on every claim, and it is
# most of the bulk. Everything else goes -- including the disk images, which
# are Donald's own game data going to Donald's own OneDrive.
tar --exclude='./inst' --exclude='./build' --exclude='./dist' \
    -C "$SRC" -cf - . 2>/dev/null | zstd -q -3 -o "$out" 2>/dev/null || exit 0

# Keep the last KEEP snapshots. Deleting the oldest of many is not the
# failure this guards against; losing every copy at once is.
ls -1t "$DEST"/wish-work-*.tar.zst 2>/dev/null | tail -n +$((KEEP + 1)) \
    | while read -r old; do rm -f "$old"; done

# Push only this folder. The onedrive systemd service is masked -- Donald's
# choice -- and nothing here unmasks it or touches the other 282G.
command -v onedrive >/dev/null 2>&1 &&
    onedrive --sync --single-directory 'wish-work' >/dev/null 2>&1 || true
