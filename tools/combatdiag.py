#!/usr/bin/env python3
"""Drive a fight with every routing decision logged, and read the log back.

    tools/combatdiag.py run --out work/combatdiag/run1.jsonl --slot 4
    tools/combatdiag.py read work/combatdiag/run1.jsonl

`run` boots a pool slot, loads a save, walks until something ambushes the
party and hands every turn to the shipped `Session.melee_turn` -- changing
nothing about it. What it adds is instrumentation: `step_towards`,
`await_bar`, `combat_bar` and the keyboard are wrapped, so the log carries

  * **every candidate square** `step_towards` looked at, with its terrain
    byte, its occupied bit, who is standing on it, whether it is inside the
    arena and how much closer it gets -- beside the key that was chosen;
  * the whole terrain grid at the top of each turn;
  * every bar the driver waited for, whether it arrived, and how long it took;
  * every key sent.

`read` renders that back as one indented line per event.

**Why this is not `tools/stepcheck.py`.** `stepcheck` runs the same routing
offline against the arena in `tests/gamedata.py`, needs no emulator, and
answers "which square would it pick". This one answers the questions only a
live machine can: whether the key that was pressed did anything, how long the
game took to admit it, and what the bar said afterwards.

Both of `#127 (A driven character stands next to an enemy and passes its turn
instead of attacking)` and `#170 (A driven character walks into rock, because
step_towards never reads the terrain)` were diagnosed from a log this made --
#127 off `avoid` holding the attack key on every turn because `MOVE LEFT` had
not gone down 20 ms after the press, and #170 off the terrain column, which
`step_towards` was logging and not reading.

Needs a set of disks: `$POR_DISKS`, or `automap.paths.find_disks()`. The pool
owns the emulator -- claim, launch, tear down; nothing is killed by name, and
the player's disks are copied into the slot and never written.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import session as S  # noqa: E402

from automap.paths import find_disks  # noqa: E402

#: Give up walking rather than circling an area that will not ambush anybody.
MAX_STEPS = 400


def _disks() -> pathlib.Path:
    disks = pathlib.Path(os.environ.get("POR_DISKS") or (find_disks() or ""))
    if not disks.is_dir():
        raise SystemExit("no game disks: set $POR_DISKS")
    return disks


def run(args) -> int:
    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out = out_path.open("w")

    def emit(kind, **kw):
        kw["kind"] = kind
        kw["t"] = round(time.time(), 3)
        out.write(json.dumps(kw, default=str) + "\n")
        out.flush()

    slot = S.claim_slot(args.slot, note=f"combatdiag {out_path.name}")
    print(f"slot {slot.n} bin {slot.port} text {slot.text_port} "
          f"display {slot.display}", flush=True)
    boot = S.stage_disks(slot, _disks(), args.save)
    sess = S.Session(boot, slot=slot)

    # -- instrumentation ---------------------------------------------------
    # `step_towards` is a staticmethod, so the underlying function has to be
    # taken out of the class dictionary rather than off the class.
    orig_step = S.Session.__dict__["step_towards"].__func__
    orig_await = S.Session.await_bar
    orig_bar = S.Session.combat_bar
    orig_key = sess.kbd.key

    def logged_step(battle, me, target, avoid=()):
        cand = []
        for (dx, dy), key in S.STEP_KEYS.items():
            x, y = me.x + dx, me.y + dy
            holds = battle.shape.holds(x, y)
            who = battle.at(x, y) if holds else None
            cand.append({
                "key": key, "d": [dx, dy], "xy": [x, y],
                "in": holds,
                "terrain": battle.square(x, y) if holds else None,
                "occbit": battle.occupied(x, y) if holds else None,
                "who": (who.name.strip() if who is not None else None),
                "party": (who.is_party if who is not None else None),
                "reach": (max(abs(target.x - x), abs(target.y - y))
                          if holds else None),
                "avoided": key in avoid,
            })
        key = orig_step(battle, me, target, avoid)
        emit("step_towards", me=[me.x, me.y], name=me.name.strip(),
             target=[target.x, target.y], tname=target.name.strip(),
             dist=S.chebyshev(me, target), avoid=sorted(avoid),
             chose=key, cand=cand)
        return key

    def logged_await(self, kinds, timeout=6.0, interval=0.4):
        t0 = time.time()
        r = orig_await(self, kinds, timeout, interval)
        emit("await_bar", kinds=list(kinds), took=round(time.time() - t0, 2),
             got=(None if r is None else [r.kind, r.text, r.moves_left]))
        return r

    def logged_bar(self, label, timeout=20.0, row=24):
        t0 = time.time()
        r = orig_bar(self, label, timeout, row)
        emit("combat_bar", label=label, ok=r, took=round(time.time() - t0, 2))
        return r

    def logged_key(nm, hold=0.10, gap=0.14):
        emit("key", key=nm)
        return orig_key(nm, hold, gap)

    S.Session.step_towards = staticmethod(logged_step)
    S.Session.await_bar = logged_await
    S.Session.combat_bar = logged_bar
    sess.kbd.key = logged_key

    def snapshot(tag):
        b = sess.battle()
        if b is None:
            emit("battle", tag=tag, ok=False)
            return None
        s = sess.screen()
        me = sess.acting(b, s)
        emit("battle", tag=tag, ok=True,
             shape=[b.shape.width, b.shape.height],
             acting=(None if me is None else
                     {"i": me.index, "n": me.name.strip(),
                      "xy": [me.x, me.y], "hp": me.hp, "mv": me.movement}),
             party=[{"i": c.index, "n": c.name.strip(), "xy": [c.x, c.y],
                     "hp": c.hp, "on": c.on_map, "ini": c.initiative,
                     "mv": c.movement}
                    for c in b.party],
             foes=[{"i": c.index, "n": c.name.strip(), "xy": [c.x, c.y],
                    "hp": c.hp, "on": c.on_map, "ini": c.initiative}
                   for c in b.enemies],
             bar=(None if s is None else s.row(24).rstrip()))
        return b

    turn_no = [0]

    def tactic(sess_, state):
        turn_no[0] += 1
        emit("turn", n=turn_no[0], bar=state.text)
        b = snapshot(f"turn{turn_no[0]}")
        if b is not None:
            emit("terrain", tag=f"turn{turn_no[0]}",
                 grid=["".join(f"{b.square(x, y):02x}"
                               for x in range(b.shape.width))
                       for y in range(b.shape.height)])
        t0 = time.time()
        chose = sess_.melee_turn(state)
        emit("turn_end", n=turn_no[0], chose=chose,
             took=round(time.time() - t0, 2))
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
        emit("world", at=list(sess.position()))

        for fight_n in range(1, args.fights + 1):
            steps = 0
            while not sess.in_combat():
                if steps > MAX_STEPS:
                    raise RuntimeError("route exhausted with no fight")
                sess.walk_one(args.walk)
                sess.handle_prompt()
                steps += 1
            print(f"FIGHT {fight_n} after {steps} steps, "
                  f"t={round(time.time() - started, 1)}", flush=True)
            emit("fight_start", n=fight_n, steps=steps)
            snapshot(f"fight{fight_n}-start")
            r = sess.fight(budget=args.budget, tactic=tactic)
            emit("fight_end", n=fight_n, outcome=r.outcome, turns=r.turns,
                 seconds=round(r.seconds, 1), acted=r.acted,
                 lines=r.lines, bars=r.bars)
            print(f"  fight {fight_n}: {r.outcome} turns={r.turns} "
                  f"secs={round(r.seconds)} acted={r.acted}", flush=True)
            if r.outcome == S.BUDGET:
                print("  out of budget; stopping", flush=True)
                break
            sess.settle(4)
        return 0
    except Exception as exc:                                # noqa: BLE001
        import traceback
        traceback.print_exc()
        emit("error", err=str(exc))
        return 1
    finally:
        try:
            sess.close()
        except Exception:
            pass
        slot.teardown()
        slot.release()
        out.close()
        print(f"log: {out_path}", flush=True)


def read(args) -> int:
    """Render a log as one indented line per event."""
    for line in pathlib.Path(args.log).read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        k = r["kind"]
        if k == "world":
            print(f"in the world at {r['at']}")
        elif k == "fight_start":
            print(f"### FIGHT {r.get('n', 1)} after {r['steps']} steps")
        elif k == "fight_end":
            print(f"### FIGHT {r.get('n', 1)} {r['outcome']} "
                  f"turns={r['turns']} secs={r.get('seconds')} "
                  f"acted={r['acted']}")
            print(f"    lines: {r.get('lines')}")
            print(f"    bars:  {r.get('bars')}")
        elif k == "turn":
            print(f"--- TURN {r['n']}  bar={r['bar']!r}")
        elif k == "battle" and r.get("ok") and r["tag"].startswith("turn"):
            a = r["acting"]
            print(f"    acting {a and a['n']} at {a and a['xy']} "
                  f"mv={a and a['mv']}")
            print("    foes  "
                  f"{[(c['xy'], c['hp']) for c in r['foes'] if c['on'] and c['hp']]}")
        elif k == "terrain":
            for row in r["grid"]:
                print(f"    | {row}")
        elif k == "step_towards":
            print(f"    step {r['name']}{r['me']} -> {r['target']} "
                  f"d={r['dist']} avoid={r['avoid']} chose={r['chose']}")
            for c in r["cand"]:
                if not c["in"]:
                    continue
                who = c["who"] or "-"
                print(f"       {c['key']} {c['xy']} terrain={c['terrain']} "
                      f"occ={c['occbit']} on={who} reach={c['reach']}"
                      + ("  AVOIDED" if c["avoided"] else ""))
        elif k == "key":
            print(f"      key {r['key']}")
        elif k == "await_bar":
            print(f"      await {r['kinds']} {r['took']}s -> {r['got']}")
        elif k == "combat_bar":
            print(f"      bar {r['label']} ok={r['ok']} {r['took']}s")
        elif k == "turn_end":
            print(f"    == turn {r['n']} chose {r['chose']} in {r['took']}s")
        elif k == "error":
            print(f"ERROR {r['err']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="drive a fight and write a log")
    r.add_argument("--out", default="work/combatdiag/run.jsonl")
    r.add_argument("--slot", type=int, default=None,
                   help="pool slot to claim; the first free one by default")
    r.add_argument("--save", default="PORSAVE13.D64",
                   help="the save disk on the player's disk folder to load")
    r.add_argument("--fights", type=int, default=3)
    r.add_argument("--budget", type=float, default=600.0,
                   help="seconds one fight may take before it is given up on")
    r.add_argument("--walk", default="I",
                   help="the letter walked to look for an ambush")
    r.set_defaults(func=run)

    d = sub.add_parser("read", help="render a log written by `run`")
    d.add_argument("log")
    d.set_defaults(func=read)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
