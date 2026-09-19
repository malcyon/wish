#!/usr/bin/env python3
"""Drive a save that arrives on a picture, and report what `begin_adventuring` says.

Kept from `#182 (A driven save that arrives on a picture is reported as a failed
load)`. A Sokol Keep arrival plays the boat scene, and `Session.begin_adventuring`
used to call that a failed load; the offline half is exercised by
`tests/test_arrivalscene.py`, and this is the live half. It claims a pool slot,
stages the player's Pool of Radiance disks into it (`tools.c64.session.stage_disks`),
copies the save you name over the slot's own save disk (`SIDE0.D64`), boots, loads
the save, begins adventuring, prints each step's result and the status, and
takes a screenshot of where it ended up.

    tools/pool_of_radiance/sokolarrivalcheck.py SAVE.D64 [--slot 1] [--disks DIR] [--shot PNG]

`SAVE.D64` is a Pool of Radiance save disk with the party at a Sokol Keep
arrival. `--disks` defaults to `automap.paths.find_disks()`. The player's disks
are never in the drive: everything is the slot's own staged copy. It claims a
pool slot and boots an emulator, so it belongs to `.claude/rules/emulator.md`.
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from automap.paths import find_disks  # noqa: E402
from tools.c64 import session as S  # noqa: E402
from tools.registry import scratch  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("save", type=pathlib.Path,
                        help="a Pool of Radiance save disk to load")
    parser.add_argument("--slot", type=int, default=1,
                        help="the pool slot to claim (default 1)")
    parser.add_argument("--disks", type=pathlib.Path,
                        help="the Pool of Radiance disks directory")
    parser.add_argument("--shot", type=pathlib.Path,
                        default=scratch.scratch_dir("sokolarrivalcheck") / "arrived.png",
                        help="where the final screenshot goes")
    args = parser.parse_args(argv)
    disks = args.disks or find_disks()
    if disks is None:
        parser.error("no Pool of Radiance disks found; set $POR_DISKS or "
                     "pass --disks")

    slot = S.claim_slot(args.slot, "p182-check")
    sess = None
    try:
        boot = S.stage_disks(slot, disks)
        shutil.copyfile(args.save, pathlib.Path(slot.dir) / "SIDE0.D64")
        sess = S.Session(boot, slot=slot)
        print("boot:", sess.boot())
        print("load_save:", sess.load_save())
        print("begin_adventuring:", sess.begin_adventuring())
        print("status:", sess.status())
        args.shot.parent.mkdir(parents=True, exist_ok=True)
        sess.kbd.screenshot(str(args.shot))
    finally:
        if sess is not None:
            sess.terminate()
        else:
            slot.teardown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
