#!/usr/bin/env python3
"""A driven Secret of the Silver Blades session, on a pooled VICE instance.

`tools/curserun.py` is Curse of the Azure Bonds' equivalent and this is the
third of three, because a boot is the one part of driving a Gold Box title
that is genuinely per-release.  Everything below the title screen -- the
monitor, the keyboard, the screen reader, the menu walker, the disk-prompt
answerer -- is `tools/session.py`'s and is shared.

**The boot and the prompts are `tools/ssbwarp.py`'s already**, measured for
`#20 (Build an area table for Silver Blades)` over eight sessions, so this
file imports `SSBSession`, `stage` and `load_party` rather than restating
them.  What it adds is the one thing `#20` never needed: **a save disk this
project built, staged as `SIDE0`, and a session left serving so the party on
it can be read off the running game** (`#193 (Convert a Secret of the Silver
Blades DOS save into a C64 one, which the importer refuses today)` step 3).

    tools/ssbdisk.py --folder work/curse/SSB-D-paine-memorised --slot D \\
        --out work/193/SSBD.D64
    tools/ssbrun.py --pool 4 --save work/193/SSBD.D64 --out work/193/run1

Then drive it with `POR_CMD_PORT=65<slot> tools/porcmd screen`, exactly as
for the other two titles.  `--watch` launches and serves with no boot, for
reading a screen nothing recognises.

Five things about this rip cost `#20` a run each and all five are in
`ssbwarp.SSBSession`: a cracker intro before the game, twenty-five seconds
of silence needed before the first keypress, the fastloader prompt arriving
*after* the intro rather than before it, `INSERT SIDE A` in letters rather
than digits, and `$4BFB` hiding the status-line square in eleven of the
twenty-two areas -- so read `$C04B` and never the status line.

Nothing is written to the player's disks: the six sides are copied into the
pool slot, and the save disk is one this project built from a DOS save.
"""
from __future__ import annotations

import os
import pathlib
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOLS))

import gamedisks  # noqa: E402

from tools import session as por  # noqa: E402
from tools import ssbwarp  # noqa: E402


def run(argv: list[str]) -> None:
    watch = "--watch" in argv
    argv = [a for a in argv if a != "--watch"]
    want = None
    save = disks = out = ""
    i = 0
    while i < len(argv):
        if argv[i] == "--pool":
            i += 1
            if i < len(argv) and argv[i].isdigit():
                want = int(argv[i])
                i += 1
            continue
        if argv[i] in ("--save", "--disks", "--out") and i + 1 < len(argv):
            value = argv[i + 1]
            if argv[i] == "--save":
                save = value
            elif argv[i] == "--disks":
                disks = value
            else:
                out = value
            i += 2
            continue
        i += 1

    disks = disks or str(gamedisks.find("secret-of-the-silver-blades") or "")
    if not disks:
        raise SystemExit("no Silver Blades disks: set $SSB_DISKS or pass "
                         "--disks")
    slot = por.claim_slot(want, note=os.environ.get("POR_AGENT", "ssb193"))
    print(f"slot {slot.n}: monitor {slot.port} text {slot.text_port} "
          f"cmd {slot.cmd_port} display {slot.display} dir {slot.dir}",
          flush=True)
    first = ssbwarp.stage(slot, disks, save)
    if save:
        print(f"save disk: {save} -> {slot.dir}/SIDE0.D64", flush=True)
    sess = ssbwarp.SSBSession(first, slot=slot)
    sess.save_disk = f"{slot.dir}/SIDE0.D64"
    if out:
        pathlib.Path(out).mkdir(parents=True, exist_ok=True)
    if watch:
        sess.launch()
    else:
        booted = sess.boot()
        print("booted" if booted else "boot incomplete", flush=True)
        if booted:
            loaded = ssbwarp.load_party(sess)
            print("party loaded" if loaded else "party not loaded", flush=True)
            time.sleep(1.0)
            sess.dump()
    por.serve(sess)


if __name__ == "__main__":
    run(sys.argv[1:])
