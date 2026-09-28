#!/usr/bin/env python3
"""Press the indoor `M` key on chosen squares and read where it leaves the party.

`DUNGEON $0937` is the `M` handler: it turns the party about, sets `$2B7F`,
tries a forward step, and turns the party back only if `$2B7F` is still set.
`$0E64`, which runs when `$C04E` (the wall art on the edge being stepped
through) is non-zero, clears `$2B7F`, so the prediction is: no wall art behind
the party -- one square back, facing kept; a passable door behind -- one square
back, facing reversed; a solid wall behind -- no move, facing reversed.

    tools/pool_of_radiance/mkeyprobe.py --out DIR

Boots `npc_party.d64` (the Kobold Caves, `GEO0D`) on a pool slot, selects
`MOVE`, and for each case writes the square and facing into `$C04B`-`$C04D`,
sends `M` through the KERNAL buffer and reads the triple once the game is back
in its key wait.  The handler's bytes in memory are read too, so the result is
tied to the code that ran.  Writes `cases.json` and a screenshot per case to
`--out` (default: the scratch directory); the player's disks are only read.
A case that ends on anything but the move bar -- a wandering fight's text --
is marked as an event and ends the run, since the next key would answer it.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOLS / "areas"))

import exitreentry as X  # noqa: E402
import geomap  # noqa: E402

from goldbox.geo import OPPOSITE, STEP  # noqa: E402
from tools.c64 import session as S  # noqa: E402
from tools.registry import scratch  # noqa: E402

POSITION = 0xC04B
HANDLER = 0x0937
FLAG = 0x2B7F

#: (label, x, y, facing) on `GEO0D`; 0 N, 1 E, 2 S, 3 W.  No square involved
#: carries a script id, so nothing but the handler moves the party.
CASES = (
    ("solid-S", 2, 1, 2),
    ("solid-W", 1, 1, 3),
    ("solid-S2", 3, 1, 2),
    ("open-N", 3, 1, 0),
    ("door-N", 10, 4, 0),
    ("open-W", 7, 1, 3),
    ("door-W", 11, 2, 3),
)

#: Row 24 while the game waits for a direction in `MOVE`.
MOVE_BAR = "I,J,K,M"


def predict(geo, x: int, y: int, facing: int) -> tuple[str, tuple[int, int, int]]:
    """What the handler's own logic says `M` leaves: kind and (x, y, facing)."""
    back = OPPOSITE[facing]
    art, bar = geo.wall(x, y, back), geo.barrier(x, y, back)
    dx, dy = STEP[back]
    if art == 0:
        return "open", (x + dx, y + dy, facing)
    if bar == 1:
        return "door", (x + dx, y + dy, back)
    if bar == 0:
        return "solid", (x, y, back)
    return "locked", (x, y, back)


def run(args) -> int:
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    geo = geomap.all_maps()["GEO0D"]
    slot = S.claim_slot(args.slot, "issue708 M key probe")
    print(f"Slot {slot.n} display {slot.display}", flush=True)
    sess = None
    results = {"cases": []}
    try:
        boot = S.stage_disks(slot, X.DISKS)
        S.stage_writable(pathlib.Path(args.save).expanduser(),
                         pathlib.Path(slot.dir) / "SIDE0.D64")
        for p in pathlib.Path(slot.dir).glob("*.D64"):
            os.chmod(p, 0o644)
        sess = S.Session(boot, slot=slot)
        if not sess.boot():
            raise RuntimeError("Boot failed")
        if not sess.load_save():
            raise RuntimeError("The game did not accept the disk")
        if not sess.select_row("BEGIN ADVENTURING"):
            raise RuntimeError("BEGIN ADVENTURING could not be selected")
        if not sess.wait_for_world(timeout=args.arrive):
            raise RuntimeError("No command bar after BEGIN ADVENTURING")
        sess.settle(4)
        with sess.mon(5) as m:
            area = m.read(0x6E1B, 1)[0] & 0x7F
            results["handler_bytes"] = m.read(HANDLER, 38).hex(" ")
            results["start"] = list(m.read(POSITION, 3))
        results["area"] = area
        print(f"area {area}, start {results['start']}, "
              f"handler {results['handler_bytes']}", flush=True)
        if area != X.CAVES:
            raise RuntimeError("the save is not in the Kobold Caves")
        if not sess.select_bar("MOVE", timeout=20):
            raise RuntimeError("MOVE could not be selected")
        X.wait_idle(sess, timeout=60, need=4)
        for label, x, y, facing in CASES:
            kind, want = predict(geo, x, y, facing)
            screen = sess.screen()
            bar = screen.row(24) if screen is not None else ""
            if not bar.startswith(MOVE_BAR):
                # A key sent now would answer this screen, not the handler.
                results["stopped"] = {"before": label, "row24": bar}
                print(f"[{label}] not sent: row 24 is {bar!r}", flush=True)
                break
            with sess.mon(5) as m:
                m.write(POSITION, bytes([x, y, facing]))
            X.wait_idle(sess, timeout=30, need=3)
            sess.press_kernal(0x4D)
            time.sleep(1.0)
            X.wait_idle(sess, timeout=60, need=4)
            with sess.mon(5) as m:
                got = list(m.read(POSITION, 3))
                flag = m.read(FLAG, 1)[0]
                c04e = m.read(0xC04E, 2).hex(" ")
            row = sess.screen().row(24) if sess.screen() is not None else ""
            sess.kbd.screenshot(str(out / f"{label}.png"))
            ok = tuple(got) == want
            # Anything but the move bar afterwards is an event on the square
            # (a wandering fight's text), which may itself set the facing.
            event = not row.startswith(MOVE_BAR)
            rec = {"label": label, "before": [x, y, facing], "kind": kind,
                   "event": event,
                   "predicted": list(want), "after": got, "match": ok,
                   "flag_after": flag, "C04E_after": c04e, "row24": row}
            results["cases"].append(rec)
            print(f"[{label}] {kind}: ({x},{y}) f{facing} -> {got}, "
                  f"predicted {list(want)} {'OK' if ok else 'MISMATCH'} "
                  f"flag={flag} row24={row!r}", flush=True)
            if event:
                results["stopped"] = {"after": label, "row24": row}
                break
        (out / "cases.json").write_text(json.dumps(results, indent=1))
        return 0 if all(c["match"] for c in results["cases"]
                        if not c["event"]) else 1
    finally:
        (out / "cases.json").write_text(json.dumps(results, indent=1))
        for what, fn in (("session", sess.terminate if sess else None),
                         ("slot teardown", slot.teardown),
                         ("slot release", slot.release)):
            if fn is None:
                continue
            try:
                fn()
            except Exception as e:              # noqa: BLE001
                print(f"  {what} failed: {e}", flush=True)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--save", default=str(S.npc_party_save()))
    p.add_argument("--slot", type=int, default=None)
    p.add_argument("--out", default=str(scratch.scratch_dir("mkeyprobe", "run")))
    p.add_argument("--arrive", type=float, default=240.0)
    args = p.parse_args(argv)
    if X.DISKS is None:
        raise SystemExit("No game disks found. Set $POR_DISKS.")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
