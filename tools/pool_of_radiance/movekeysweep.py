#!/usr/bin/env python3
"""At a live move sub-bar, press every key and record what it did.

    tools/pool_of_radiance/movekeysweep.py [NAME [SAVE [BUDGET [SLOT]]]]

This is a run for `#127 (A driven character stands next to an enemy and
passes its turn instead of attacking)`.  NAME is the log's name (default
`sweep1`), SAVE a save disk in `$POR_DISKS` (default `PORSAVE13.D64`), BUDGET
the fight's time budget in seconds (default 900) and SLOT the pool slot to
take (default 1).  It claims that slot, boots the game and walks until a
fight starts, so it drives an emulator.

The probe showed the step into an enemy square doing nothing for ten seconds.
Every press in both runs was `KP_1`, so two readings survive and this tells
them apart: is a step into an occupied square refused, or is `KP_1` dead?

For each press it records the destination square's contents (empty, a party
member, an enemy), whether the character moved, whether `MOVE LEFT` went down,
and whether the target lost hit points.

Research only.  Writes `<name>.jsonl` into `OUT`, the tool's scratch directory.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from automap.paths import find_disks  # noqa: E402
from tools.c64 import session as S  # noqa: E402
from tools.registry import instance, scratch  # noqa: E402

OUT = scratch.scratch_dir("movekeysweep")


def disks_dir() -> pathlib.Path:
    """The player's Pool of Radiance disk folder: `$POR_DISKS`, then the search."""
    where = os.environ.get("POR_DISKS") or find_disks()
    if not where:
        raise SystemExit("no C64 disks; set POR_DISKS")
    return pathlib.Path(where)

# The eight steps, plus the two keys a joystick fire button is usually on.
CANDIDATES = [("KP_8", (0, -1)), ("KP_9", (1, -1)), ("KP_6", (1, 0)),
              ("KP_3", (1, 1)), ("KP_2", (0, 1)), ("KP_1", (-1, 1)),
              ("KP_4", (-1, 0)), ("KP_7", (-1, -1)),
              ("KP_5", None), ("KP_0", None), ("space", None)]


def claim_slot(want: int, note: str):
    holds, slot = [], None
    while True:
        s = instance.claim(note=note)
        if s.n == want:
            slot = s
            break
        holds.append(s)
        if s.n > want:
            break
    for h in holds:
        h.release()
    if slot is None:
        raise RuntimeError(f"slot {want} not free")
    return slot


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("name", nargs="?", default="sweep1")
    ap.add_argument("save", nargs="?", default="PORSAVE13.D64")
    ap.add_argument("budget", nargs="?", type=float, default=900.0)
    ap.add_argument("slot", nargs="?", type=int, default=1)
    args = ap.parse_args(argv)
    name, save, budget, want_slot = (args.name, args.save, args.budget,
                                     args.slot)
    DISKS = disks_dir()

    scratch.ensure(OUT)
    out = open(OUT / f"{name}.jsonl", "w")

    def emit(kind, **kw):
        kw["kind"] = kind
        kw["t"] = round(time.time(), 3)
        out.write(json.dumps(kw, default=str) + "\n")
        out.flush()

    slot = claim_slot(want_slot, f"issue127/{name}")
    print(f"slot {slot.n} display {slot.display}", flush=True)
    slot.seed_vicerc()
    here = pathlib.Path(slot.dir)
    for i in range(1, 9):
        src = DISKS / f"POOL{i}.D64"
        if src.exists():
            shutil.copyfile(src, here / f"SIDE{i}.D64")
    shutil.copyfile(DISKS / save, here / "SIDE0.D64")

    sess = S.Session(str(here / "SIDE1.D64"), slot=slot)
    sess.save_disk = str(here / "SIDE0.D64")

    def look(index):
        b = sess.battle()
        who = None if b is None else next(
            (c for c in b.combatants if c.index == index), None)
        bar = sess.combat_state()
        return b, who, bar

    def press(index, key, delta, hold):
        b, me, bar = look(index)
        if b is None or me is None or bar.kind != S.BAR_MOVE:
            return False, bar
        dest = who = None
        if delta is not None:
            dx, dy = delta
            dest = (me.x + dx, me.y + dy)
            who = b.at(*dest) if b.shape.holds(*dest) else None
        target_hp = None if who is None else who.hp
        sess.kbd.key(key, hold, 0.30)
        time.sleep(1.6)
        b2, me2, bar2 = look(index)
        who2 = None
        if who is not None and b2 is not None:
            who2 = next((c for c in b2.combatants if c.index == who.index),
                        None)
        emit("press", key=key, hold=hold, at=[me.x, me.y], dest=dest,
             holds=(None if dest is None else b.shape.holds(*dest)),
             terrain=(None if dest is None or not b.shape.holds(*dest)
                      else b.square(*dest)),
             on_dest=(None if who is None else
                      ("party" if who.is_party else "enemy")),
             dest_name=(None if who is None else who.name.strip()),
             before=[bar.text, bar.moves_left],
             after=[bar2.text, bar2.moves_left],
             moved=(None if me2 is None else [me2.x, me2.y] != [me.x, me.y]),
             dest_hp=[target_hp, None if who2 is None else who2.hp],
             r23=None)
        return True, bar2

    turns = [0]

    def tactic(sess_, state):
        turns[0] += 1
        b = sess_.battle()
        me = sess_.acting(b)
        if b is None or me is None:
            return sess_.combat_turn()
        live = [e for e in b.enemies if e.alive and e.on_map]
        if not live:
            return sess_.combat_turn()
        target = min(live, key=lambda e: S.chebyshev(me, e))
        emit("turn", n=turns[0], who=me.name.strip(), i=me.index,
             xy=[me.x, me.y], target=[target.x, target.y],
             dist=S.chebyshev(me, target))
        if not sess_.combat_bar("MOVE", timeout=15):
            return sess_.combat_turn()
        if sess_.await_bar((S.BAR_MOVE,), timeout=8) is None:
            return sess_.combat_turn()
        # The direction of the enemy first, twice -- once at the ordinary hold
        # and once at double it -- then everything else.
        dx = max(-1, min(1, target.x - me.x))
        dy = max(-1, min(1, target.y - me.y))
        toward = S.STEP_KEYS.get((dx, dy))
        order = []
        if toward is not None and S.chebyshev(me, target) == 1:
            order.append((toward, (dx, dy), 0.15))
            order.append((toward, (dx, dy), 0.45))
        for key, delta in CANDIDATES:
            order.append((key, delta, 0.15))
        for key, delta, hold in order:
            ok, bar = press(me.index, key, delta, hold)
            if not ok:
                break
        if sess_.combat_state().kind == S.BAR_MOVE:
            sess_.press_kernal(0x0D)
        return "SWEEP"

    started = time.time()
    try:
        if not sess.boot():
            raise RuntimeError("boot failed")
        if not sess.load_save():
            raise RuntimeError("load_save failed")
        if not sess.begin_adventuring():
            raise RuntimeError("begin_adventuring failed")
        sess.settle(3)
        print("in the world at", sess.position(), flush=True)
        steps = 0
        while not sess.in_combat():
            if steps > 400:
                raise RuntimeError("route exhausted with no fight")
            sess.walk_one("I")
            sess.handle_prompt()
            steps += 1
        print(f"FIGHT after {steps} steps t={round(time.time()-started,1)}",
              flush=True)
        emit("fight_start", steps=steps)
        r = sess.fight(budget=budget, tactic=tactic)
        emit("fight_end", outcome=r.outcome, turns=r.turns, acted=r.acted,
             lines=r.lines)
        print(f"fight: {r.outcome} turns={r.turns} acted={r.acted}", flush=True)
        return 0
    except Exception:
        import traceback
        traceback.print_exc()
        return 1
    finally:
        try:
            sess.close()
        except Exception:
            pass
        slot.teardown()
        slot.release()
        out.close()


if __name__ == "__main__":
    raise SystemExit(main())
