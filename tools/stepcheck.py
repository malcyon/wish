#!/usr/bin/env python3
"""Print the step `Session.step_towards` picks in each measured case.

    .venv/bin/python tools/stepcheck.py

Six positions on `tests/gamedata.py`'s arena, with the answer each one was
measured to want.  They are the table in `#170` -- the six cases the
breadth-first routing was prototyped against during `#127`, when the
prototype lived in `work/issue127/proto.py` and `work/` is gitignored, which
is why it is here instead.

This drives the **real** `Session.step_towards`, so it is a check on the
routing rather than a second copy of it: change the routing and this says
which of the six moved.  It needs no emulator and no display -- the arena
comes out of the player's own saved games through `tests/gamedata.py`, and
skips with nothing to say when those are not on the machine.

Two of the six are the defects:

* five friends on every square that gets closer -- greedy passed the turn,
  and there was a way round;
* rock between, the arena's block at x 20-22 -- greedy pressed a key into it,
  which in the running game moves nobody and spends no movement.
"""
from __future__ import annotations

import dataclasses
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

from session import STEP_KEYS, Session  # noqa: E402

from automap import combat  # noqa: E402
from automap.target import MemoryTarget  # noqa: E402


def variant(base, combatants):
    return combat.Battle(shape=base.shape, terrain=base.terrain,
                         camera=base.camera, combatants=tuple(combatants))


def cases():
    """`(name, battle, me, target, wanted)`, in the order `#170` lists them."""
    from gamedata import synthetic_arena

    b = combat.read_battle(MemoryTarget(synthetic_arena()))
    me, orc = b.party[0], b.enemies[0]           # (25,13) and (30,13)

    ally = dataclasses.replace(me, index=1, x=me.x + 1, y=me.y)
    adjacent = dataclasses.replace(orc, x=me.x + 1, y=me.y)
    on_top = dataclasses.replace(orc, x=me.x, y=me.y)
    penned = [dataclasses.replace(me, index=i, x=me.x + 1, y=me.y + dy)
              for i, dy in enumerate((-1, 0, 1), start=1)]
    west = dataclasses.replace(me, x=19, y=13)
    far = dataclasses.replace(orc, x=25, y=13)

    return [
        ("open arena, orc due east", b, me, orc, "KP_6"),
        ("ally on the square east",
         variant(b, (me, ally) + b.enemies), me, orc, "KP_9"),
        ("enemy adjacent east",
         variant(b, (me, adjacent)), me, adjacent, "KP_6"),
        ("enemy standing on you",
         variant(b, (me, on_top)), me, on_top, None),
        ("friends on every square that gets closer",
         variant(b, (me,) + tuple(penned) + (orc,)), me, orc, "KP_8"),
        ("rock between, arena block at x 20-22",
         variant(b, (west, far)), west, far, "KP_8"),
    ]


def main() -> int:
    try:
        rows = cases()
    except Exception as exc:                     # no disks, no saved games
        print(f"No arena to check against: {exc}")
        return 0

    bad = 0
    for name, battle, me, target, want in rows:
        got = Session.step_towards(battle, me, target)
        ok = got == want
        bad += not ok
        into = ""
        if got is not None:
            dx, dy = next(d for d, k in STEP_KEYS.items() if k == got)
            into = f"  into ({me.x + dx},{me.y + dy}) terrain " \
                   f"{battle.square(me.x + dx, me.y + dy)}"
        print(f"{'ok ' if ok else 'BAD'} {name:42} {str(got):5} "
              f"want {str(want):5}{into}")
    print(f"{len(rows) - bad} of {len(rows)} as measured")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
