#!/usr/bin/env python3
"""What does QUIT on the DONE sub-bar actually do? -- a driven probe for `#165
(One character that cannot act takes every turn in a driven fight)`.

    .venv/bin/python tools/pool_of_radiance/slumsquitprobe.py [NAME [SAVE [BUDGET [SLOT]]]]

NAME is the run's name (default `quit1`), SAVE the save disk in the Pool of
Radiance folder (default `PORSAVE13.D64`), BUDGET the fight's time budget in
seconds (default 480) and SLOT the pool slot to claim (default 1).

`end_turn` takes GUARD, then DELAY, then EXIT. A character whose sub-bar reads
`DELAY QUIT SPEED EXIT` gets DELAY, which postpones it rather than finishing
with it, so it comes straight back and the rest of the party never acts. QUIT
is the one command of the five nobody has pressed.

This drives one Slums ambush with the shipped `melee_turn` and, the first two
times it reaches a sub-bar with no GUARD on it, presses QUIT instead and then
changes nothing for eight seconds -- logging the mode byte, the acting
combatant index at $A4F4, and rows 22-24 every 0.4 s, so "the turn ended" can
be told from "the battle ended".

It also records, for every sub-bar reached, whether the character had taken
MOVE that turn -- which settles whether GUARD drops off after a character has
moved.

Boots VICE in a pool slot (`.claude/rules/emulator.md`), so it is never run for
`--help`. Research only: nothing in `tools/c64/session.py` is changed. Writes
`<name>.jsonl` under this tool's scratch directory.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from automap import gamedisks  # noqa: E402
from tools.c64 import session as S  # noqa: E402
from tools.registry import instance, scratch  # noqa: E402

OUT = scratch.scratch_dir("slumsquitprobe")

ACTING = 0xA4F4          # docs/147-combat-rolls.md: 0-7 party, 8 up monsters


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
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", nargs="?", default="quit1")
    ap.add_argument("save", nargs="?", default="PORSAVE13.D64")
    ap.add_argument("budget", nargs="?", type=float, default=480.0)
    ap.add_argument("slot", nargs="?", type=int, default=1)
    args = ap.parse_args(argv)
    name, save, budget, want_slot = (args.name, args.save, args.budget,
                                     args.slot)

    disks = gamedisks.find("pool-of-radiance")
    if disks is None:
        raise SystemExit("no Pool of Radiance disks: set $POR_DISKS or add a "
                         "pool-of-radiance entry to gamedisks.yaml")

    OUT.mkdir(parents=True, exist_ok=True)
    out = open(OUT / f"{name}.jsonl", "w")

    def emit(kind, **kw):
        kw["kind"] = kind
        kw["t"] = round(time.time(), 3)
        out.write(json.dumps(kw, default=str) + "\n")
        out.flush()

    slot = claim_slot(want_slot, f"issue165/{name}")
    print(f"slot {slot.n} display {slot.display}", flush=True)
    slot.seed_vicerc()
    here = pathlib.Path(slot.dir)
    for i in range(1, 9):
        src = disks / f"POOL{i}.D64"
        if src.exists():
            shutil.copyfile(src, here / f"SIDE{i}.D64")
    shutil.copyfile(disks / save, here / "SIDE0.D64")

    class Probe(S.Session):
        """The shipped session, with `end_turn` instrumented and QUIT tried."""

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.took_move = False       # was MOVE taken on this turn?
            self.quits = 0
            self.quit_verdict = None

        def combat_bar(self, label, timeout=20.0, row=24):
            ok = super().combat_bar(label, timeout, row)
            if ok and label == "MOVE":
                self.took_move = True
            return ok

        def snap(self):
            s = self.screen()
            mode = self.mode()
            try:
                with self.mon(5) as m:
                    acting = m.read(ACTING, 2)
            except Exception:
                acting = None
            b = self.battle()
            who = None if b is None else self.acting(b, s)
            return {
                "mode": mode,
                "acting": None if acting is None else list(acting),
                "r22": None if s is None else s.row(22).rstrip(),
                "r23": None if s is None else s.row(23).rstrip(),
                "r24": None if s is None else s.row(24).rstrip(),
                "kind": self.combat_state(s).kind,
                "panel": None if who is None else who.name.strip(),
                "enemies": None if b is None else
                    sum(1 for e in b.enemies if e.alive and e.on_map),
            }

        def end_turn(self):
            bar = self.combat_state().text
            guard = S.word_column(bar, "GUARD") >= 0
            emit("subbar", bar=bar, guard=guard, took_move=self.took_move)
            if not guard and S.word_column(bar, "QUIT") >= 0 and self.quits < 2:
                self.quits += 1
                before = self.snap()
                emit("quit_before", n=self.quits, state=before)
                ok = self.combat_bar("QUIT", timeout=8)
                emit("quit_pressed", n=self.quits, ok=ok)
                for i in range(20):
                    time.sleep(0.4)
                    emit("quit_watch", n=self.quits, i=i, state=self.snap())
                after = self.snap()
                emit("quit_after", n=self.quits, before=before, after=after)
                # Conservative: if pressing QUIT put a yes/no question up,
                # answer NO rather than ending somebody's fight blind.
                if after["kind"] == S.BAR_YESNO or \
                        after["kind"] == S.BAR_CONTINUE:
                    self.combat_bar("NO", timeout=8)
                    emit("quit_answered_no", n=self.quits, state=self.snap())
                return "QUIT"
            return S.Session.end_turn(self)

    sess = Probe(str(here / "SIDE1.D64"), slot=slot)
    sess.save_disk = str(here / "SIDE0.D64")

    turns = [0]

    def tactic(sess_, state):
        turns[0] += 1
        sess_.took_move = False
        b = sess_.battle()
        me = sess_.acting(b)
        dist = None
        if b is not None and me is not None:
            live = [e for e in b.enemies if e.alive and e.on_map]
            if live:
                dist = min(S.chebyshev(me, e) for e in live)
        emit("turn", n=turns[0],
             who=None if me is None else me.name.strip(),
             i=None if me is None else me.index,
             xy=None if me is None else [me.x, me.y],
             dist=dist)
        chose = sess_.melee_turn(state)
        emit("turn_end", n=turns[0], chose=chose,
             who=None if me is None else me.name.strip())
        return chose

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
    raise SystemExit(main(sys.argv[1:]))
