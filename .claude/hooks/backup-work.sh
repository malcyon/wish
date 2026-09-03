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
# fires exactly when it is on *and* `work/` has just changed. Detached, so it
# never delays a turn, and throttled to an hour -- `Stop` fires at the end of
# every turn, which would be dozens of 25MB uploads a night for no extra
# safety. `SessionStart` fires it too, so a night that starts more than an
# hour after the last snapshot gets one before anything changes.
set -euo pipefail

SRC="${CLAUDE_PROJECT_DIR:-/home/donald/src/wish}/work"
DEST="/data/OneDrive/wish-work"
STAMP="$DEST/.last"
KEEP=14          # recent snapshots, whatever their date
KEEP_DAYS=30     # plus the first snapshot of each of the last 30 days
THROTTLE=$((60 * 60))   # Donald, 2026-09-02: "once an hour is enough"

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

# Retention, and the shape of it is the whole point.
#
# Keeping only the last N at a ten-minute cadence is about two hours of
# history, so a deletion nobody notices for an evening rolls the good copies
# off the end while the hook faithfully snapshots the empty directory. That
# is the exact failure this exists to survive, so:
#
#   * the last KEEP snapshots, whatever their date -- the fine grain;
#   * plus the FIRST snapshot of every day, for KEEP_DAYS days.
#
# A daily cannot be pushed off by a busy evening, so the floor on how far
# back you can go is measured in weeks rather than in turns.
keep_list=$(mktemp)
trap 'rm -f "$keep_list"' EXIT
ls -1t "$DEST"/wish-work-*.tar.zst 2>/dev/null | head -n "$KEEP" > "$keep_list"
# The oldest snapshot bearing each date is that day's keeper.
ls -1 "$DEST"/wish-work-*.tar.zst 2>/dev/null \
    | sed 's/.*wish-work-\([0-9-]*\)T.*/\1/' | sort -u | tail -n "$KEEP_DAYS" \
    | while read -r day; do
          ls -1 "$DEST"/wish-work-"$day"T*.tar.zst 2>/dev/null | head -1
      done >> "$keep_list"
ls -1 "$DEST"/wish-work-*.tar.zst 2>/dev/null | while read -r f; do
    grep -qxF "$f" "$keep_list" || rm -f "$f"
done

# Push only this folder. The onedrive systemd service is masked -- Donald's
# choice -- and nothing here unmasks it or touches the other 282G.
command -v onedrive >/dev/null 2>&1 &&
    onedrive --sync --single-directory 'wish-work' >/dev/null 2>&1 || true
