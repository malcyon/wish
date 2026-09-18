#!/usr/bin/env python3
"""Press the attack step and then WAIT, logging what the game does.

    tools/attackwatch.py [NAME [SAVE [BUDGET [SLOT]]]]

This is a run for `#127 (A driven character stands next to an enemy and
passes its turn instead of attacking)`.  NAME is the log's name (default
`probe1`), SAVE a save disk in `$POR_DISKS` (default `PORSAVE13.D64`), BUDGET
the fight's time budget in seconds (default 600) and SLOT the pool slot to
take (default 4).  It claims that slot, boots the game and walks until a
fight starts, so it drives an emulator.

The diagnosis run showed every turn ending with the attack key in `avoid`
because `MOVE LEFT` had not gone down 20 ms after the press.  This asks the
only question that is left: if nothing else is sent, does the attack resolve,
how long does it take, and does `MOVE LEFT` ever move?

Research only.  Writes work/issue127/<name>.jsonl.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from automap.paths import find_disks  # noqa: E402
from tools import instance  # noqa: E402
from tools import session as S  # noqa: E402

OUT = ROOT / "work" / "issue127"


def disks_dir() -> pathlib.Path:
    """The player's Pool of Radiance disk folder: `$POR_DISKS`, then the search."""
    where = os.environ.get("POR_DISKS") or find_disks()
    if not where:
        raise SystemExit("no C64 disks; set POR_DISKS")
    return pathlib.Path(where)


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
    ap.add_argument("name", nargs="?", default="probe1")
    ap.add_argument("save", nargs="?", default="PORSAVE13.D64")
    ap.add_argument("budget", nargs="?", type=float, default=600.0)
    ap.add_argument("slot", nargs="?", type=int, default=4)
    args = ap.parse_args(argv)
    name, save, budget, want_slot = (args.name, args.save, args.budget,
                                     args.slot)
    DISKS = disks_dir()

    OUT.mkdir(parents=True, exist_ok=True)
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

    probes = [0]

    def watch(tag, target_index, seconds=10.0, gap=0.25):
        """Poll the screen and the fight, changing nothing."""
        t0 = time.time()
        last = None
        while time.time() - t0 < seconds:
            s = sess.screen()
            b = sess.battle()
            who = None
            if b is not None:
                who = next((c for c in b.combatants
                            if c.index == target_index), None)
            row = {
                "dt": round(time.time() - t0, 2),
                "r22": None if s is None else s.row(22).rstrip(),
                "r23": None if s is None else s.row(23).rstrip(),
                "r24": None if s is None else s.row(24).rstrip(),
                "hp": None if who is None else who.hp,
                "xy": None if who is None else [who.x, who.y],
            }
            if row != last:
                emit("watch", tag=tag, **row)
                last = dict(row)
            time.sleep(gap)

    def tactic(sess_, state):
        b = sess_.battle()
        me = sess_.acting(b)
        if b is None or me is None:
            return sess_.combat_turn()
        live = [e for e in b.enemies if e.alive and e.on_map]
        if not live:
            return sess_.combat_turn()
        target = min(live, key=lambda e: S.chebyshev(me, e))
        d = S.chebyshev(me, target)
        emit("actor", n=me.name.strip(), i=me.index, xy=[me.x, me.y],
             target=[target.x, target.y], thp=target.hp, dist=d)
        if d != 1 or probes[0] >= 6:
            return sess_.melee_turn(state)
        probes[0] += 1
        tag = f"probe{probes[0]}"
        if not sess_.combat_bar("MOVE", timeout=15):
            return sess_.combat_turn()
        moving = sess_.await_bar((S.BAR_MOVE,), timeout=8)
        emit("took_move", tag=tag,
             got=None if moving is None else [moving.text, moving.moves_left])
        if moving is None:
            return sess_.combat_turn()
        dx = max(-1, min(1, target.x - me.x))
        dy = max(-1, min(1, target.y - me.y))
        key = S.STEP_KEYS[(dx, dy)]
        emit("attack_key", tag=tag, key=key, d=[dx, dy])
        sess_.kbd.key(key, 0.15, 0.30)
        watch(tag, target.index, seconds=10.0)
        after = sess_.battle()
        mine = None if after is None else next(
            (c for c in after.combatants if c.index == me.index), None)
        foe = None if after is None else next(
            (c for c in after.combatants if c.index == target.index), None)
        emit("after", tag=tag,
             me=None if mine is None else [mine.x, mine.y],
             foe=None if foe is None else [foe.x, foe.y, foe.hp],
             bar=sess_.combat_state().text)
        if sess_.combat_state().kind == S.BAR_MOVE:
            sess_.press_kernal(0x0D)
        return "PROBE"

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
        emit("fight_end", outcome=r.outcome, turns=r.turns,
             seconds=round(r.seconds, 1), acted=r.acted, lines=r.lines,
             bars=r.bars)
        print(f"fight: {r.outcome} turns={r.turns} acted={r.acted}", flush=True)
        print("lines:", r.lines, flush=True)
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
