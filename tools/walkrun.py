#!/usr/bin/env python3
"""Unattended: boot, load a save, walk a route, save at every step.

    walkrun.py --name inn-east --route IIIIIIKIIIIII

Route letters are the game's own: `I` forward, `J` turn left, `K` turn right,
`M` turn about.  Every step records the party position before and after, so a
move that does not change the position is a **wall** -- which is the whole
point of the corpus.  One save disk is written per step into
`work/drive/walks/`, with a manifest naming the intended route.

Everything is torn down at the end, checkpoints included, and a screenshot is
taken if anything goes wrong -- an armed checkpoint or a stranded Xephyr looks
exactly like a hung game to whoever runs this next.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

sys.path.insert(0, "/home/donald/src/wish/tools")
from session import HERE, Session  # noqa: E402

WALKS = f"{HERE}/walks"
BASE_SAVE = "/home/donald/c64/Pool of Radiance Disks/PORSAVE11.D64"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--route", required=True, help="I forward, J left, K right, M about")
    ap.add_argument("--save-every", type=int, default=1, help="0 to never save")
    ap.add_argument("--base", default=BASE_SAVE)
    ap.add_argument("--timeout", type=float, default=3600)
    args = ap.parse_args()

    os.makedirs(WALKS, exist_ok=True)
    work_save = f"{HERE}/SIDE0.D64"
    shutil.copy(args.base, work_save)

    sess = Session(f"{HERE}/SIDE1.D64")
    sess.save_disk = work_save
    started = time.time()
    steps: list[dict] = []
    ok = False
    try:
        if not sess.boot():
            raise RuntimeError("boot failed")
        if not sess.load_save():
            raise RuntimeError("could not load the save")
        if not sess.begin_adventuring():
            raise RuntimeError("could not begin adventuring")
        sess.settle(3)
        sess.log("in the world at", sess.position())

        for i, move in enumerate(args.route.upper()):
            if time.time() - started > args.timeout:
                raise RuntimeError("timed out")
            before = list(sess.position())
            moved = sess.walk_one(move)
            sess.settle(2)
            after = list(sess.position())
            rec = {
                "step": i,
                "move": move,
                "before": before,
                "after": after,
                # A bump advances the clock, so "the status line changed" is not
                # evidence of movement.  Blocked means the *square* did not
                # change on a forward step -- that is the map fact.
                "blocked": move == "I" and before[:2] == after[:2],
                "status_moved": moved,
            }
            if args.save_every and i % args.save_every == 0:
                if not sess.save_game():
                    steps.append(rec)
                    raise RuntimeError(f"save failed at step {i}")
                out = f"{WALKS}/{args.name}-{i:02d}.D64"
                shutil.copy(work_save, out)
                rec["disk"] = os.path.basename(out)
                on_disk = read_position(out)
                rec["disk_position"] = on_disk
                if on_disk != after:
                    sess.log(f"  MISMATCH memory {after} vs disk {on_disk}")
            steps.append(rec)
            sess.log(f"  step {i} {move}: {before} -> {after}"
                     + ("  BLOCKED" if rec["blocked"] else ""))
        ok = True
    except Exception as exc:
        sess.log(f"FAILED: {type(exc).__name__}: {exc}")
        sess.kbd.screenshot(f"{WALKS}/{args.name}-failure.png")
        try:
            sess.dump()
        except Exception:
            pass
    finally:
        manifest = {
            "name": args.name,
            "route": args.route.upper(),
            "base_save": args.base,
            "completed": ok,
            "steps": steps,
        }
        with open(f"{WALKS}/{args.name}.json", "w") as fh:
            json.dump(manifest, fh, indent=2)
        sess.close()
    return 0 if ok else 1


def read_position(disk: str) -> list[int]:
    sys.path.insert(0, "/home/donald/src/wish")
    from por.d64 import D64

    s = D64.open(disk).read_file("SAVEDGAME0")[2:]
    return [s[0xC0], s[0xC1], s[0xC2]]


if __name__ == "__main__":
    raise SystemExit(main())
