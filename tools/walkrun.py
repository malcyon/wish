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
import pathlib
import shutil
import sys
import time

_TOOLS = pathlib.Path(__file__).resolve().parent
_ROOT = _TOOLS.parent

sys.path.insert(0, str(_TOOLS))
import instance  # noqa: E402
from session import HERE, Session  # noqa: E402

sys.path.insert(0, str(_ROOT))
from automap.paths import find_disks  # noqa: E402

WALKS = f"{HERE}/walks"
_disks = find_disks()
BASE_SAVE = str(_disks / "PORSAVE11.D64") if _disks else "PORSAVE11.D64"


def claim_slot(n: int | None) -> instance.Slot:
    """Claim a pool slot -- required, never the human's ports (#144).

    `instance.claim()` has no way to ask for slot *n* by number; it always
    hands back the lowest-numbered free one.  So when a brief names a slot,
    this claims whatever comes back and, if it is not the one asked for,
    releases it and refuses rather than run on a different slot.  That still
    gets the named slot in the case a brief actually describes -- the lower
    slots already held by other agents, and the named one free.
    """
    slot = instance.claim(game="por", note=os.environ.get("POR_AGENT", ""))
    if n is not None and slot.n != n:
        got = slot.n
        slot.release()
        raise RuntimeError(
            f"--slot {n} was requested but instance.claim() only hands out "
            f"the lowest free slot, which was {got}; refusing to run on it"
        )
    return slot


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--route", required=True, help="I forward, J left, K right, M about")
    ap.add_argument("--save-every", type=int, default=1, help="0 to never save")
    ap.add_argument("--base", default=BASE_SAVE)
    ap.add_argument("--timeout", type=float, default=3600)
    ap.add_argument("--slot", type=int, default=None,
                     help="a specific instance-pool slot, if a brief names one; "
                          "otherwise the next free slot. A slot is always claimed -- "
                          "there is no way to run this against the human's own ports")
    args = ap.parse_args()

    os.makedirs(WALKS, exist_ok=True)

    # `slot.env()` does not set this -- `POR_HEADLESS` swaps `Xephyr` for
    # `Xvfb` in `porlaunch.sh`, but it is a separate switch the caller sets,
    # not one of the five keys `Slot.env()` returns.  This tool is unattended
    # by definition, so it defaults itself headless rather than depend on
    # whoever invokes it having exported it first; `setdefault` still lets an
    # explicit `POR_HEADLESS=0` win for someone deliberately watching a run.
    os.environ.setdefault("POR_HEADLESS", "1")

    try:
        slot = claim_slot(args.slot)
    except (instance.PoolFull, instance.PoolUnavailable, RuntimeError) as exc:
        print(f"could not claim an instance-pool slot: {exc}", file=sys.stderr)
        return 1

    try:
        here = str(slot.dir)
        work_save = f"{here}/SIDE0.D64"
        shutil.copy(args.base, work_save)

        sess = Session(slot=slot)
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
            with open(f"{WALKS}/{args.name}.json", "w", encoding="utf-8") as fh:
                json.dump(manifest, fh, indent=2)
            sess.close()
        return 0 if ok else 1
    finally:
        slot.release()


def read_position(disk: str) -> list[int]:
    sys.path.insert(0, str(_ROOT))
    from goldbox.d64 import D64

    s = D64.open(disk).read_file("SAVEDGAME0")[2:]
    return [s[0xC0], s[0xC1], s[0xC2]]


if __name__ == "__main__":
    raise SystemExit(main())
