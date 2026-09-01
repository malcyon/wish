#!/usr/bin/env python3
"""Drive a fight in Pool of Radiance from a saved game, unattended.

Boot a pool slot, load the player's save, walk until something ambushes the
party, and hand every command bar to `Session.melee_turn` until the fight is
over.  One JSON line per turn goes to the log, and the summary at the end is
the question every fight-driving issue has actually been asking:

    who took the turns, how many of them had an enemy in contact, and how
    many of those ended with a blow struck

which is what tells a fight the party fought from one it stood through.  Six
runs before `#126` ended with `THE PARTY HAS WON !` and no character having
attacked, and a log of command bars cannot tell those apart.

This lives in `tools/` because three copies of it have been written into
`work/` and thrown away -- Donald, 2026-09-01: *"If you develop tools, put
them into tools/, not work/.  That way, you don't have to rebuild them."*
Only the data it produces belongs in `work/`.

Nothing here writes to the player's disks: the save and the eight sides are
copied into the slot's own directory, and `Session.attach` refuses any path
outside it.

    tools/fightrun.py --save PORSAVE13.D64 --slot 1 --budget 600

`PORSAVE13.D64` three steps into the Slums is the reproduction `#127` and
`#165` were both measured on: one ambush, six characters, eight orcs,
everybody in contact on turn 1.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOLS))

import instance  # noqa: E402
import session as S  # noqa: E402

#: Where the player keeps the disks, unless `--disks` says otherwise.  Read
#: only, ever: everything is copied into the slot's directory first.
DISKS = pathlib.Path("/home/donald/c64/Pool of Radiance Disks")


def claim_slot(want: int | None, note: str):
    """A pool slot, or the specific one asked for.

    Claiming is first-free, so getting a named slot means holding the ones
    before it and letting them go again.  Nothing is ever killed to make room:
    a slot whose lease is held belongs to somebody.
    """
    if want is None:
        return instance.claim(note=note)
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
        raise RuntimeError(f"slot {want} is not free")
    return slot


class Run:
    """One booted session, and the log it writes."""

    def __init__(self, out: pathlib.Path, quiet: bool = False):
        out.parent.mkdir(parents=True, exist_ok=True)
        self.file = open(out, "w")
        self.quiet = quiet
        self.turns: list[dict] = []

    def emit(self, kind: str, **kw) -> None:
        kw["kind"] = kind
        kw["t"] = round(time.time(), 3)
        self.file.write(json.dumps(kw, default=str) + "\n")
        self.file.flush()

    def say(self, *a) -> None:
        if not self.quiet:
            print(*a, flush=True)

    def close(self) -> None:
        self.file.close()

    # -- the tactic -------------------------------------------------------
    def tactic(self, sess, state):
        """`melee_turn`, with the turn recorded before and after.

        The two numbers that matter are read **before** the turn is driven:
        who the game is asking, and whether that character has an enemy in
        contact.  A turn that had no enemy next door and struck no blow is not
        a failure, and a summary that does not separate the two says nothing.
        """
        b = sess.battle()
        me = sess.acting(b)
        dist = None
        if b is not None and me is not None:
            live = [e for e in b.enemies if e.alive and e.on_map]
            if live:
                dist = min(S.chebyshev(me, e) for e in live)
        row = {
            "n": len(self.turns) + 1,
            "who": None if me is None else me.name.strip(),
            "i": None if me is None else me.index,
            "xy": None if me is None else [me.x, me.y],
            "dist": dist,
            "bar": state.text,
        }
        self.emit("turn", **row)
        row["chose"] = sess.melee_turn(state)
        self.emit("turn_end", n=row["n"], who=row["who"], chose=row["chose"])
        self.say(f"  turn {row['n']:3d}  {str(row['who']):<14}"
                 f" dist={row['dist']}  {row['chose']}")
        self.turns.append(row)
        return row["chose"]

    # -- what the run proved ---------------------------------------------
    def summary(self) -> list[dict]:
        """Per character: turns, turns with an enemy in contact, blows struck.

        `melee_turn` answers `ATTACK` only when the blow resolved -- the move
        sub-bar went away after a step into an enemy's square -- so that is
        the count, rather than anything read off the message band.  A message
        cannot say who swung: the orcs are attacking the party in every fight
        it is in, which is why `FightResult.acted` is not proof (`#163`).
        """
        rows: dict[str, dict] = {}
        for t in self.turns:
            who = t["who"] or "?"
            r = rows.setdefault(who, {"who": who, "turns": 0,
                                      "contact": 0, "blows": 0})
            r["turns"] += 1
            if t["dist"] == 1:
                r["contact"] += 1
                if t["chose"] == "ATTACK":
                    r["blows"] += 1
        return sorted(rows.values(), key=lambda r: -r["turns"])

    def report(self) -> None:
        rows = self.summary()
        self.emit("summary", rows=rows)
        self.say(f"{'character':<16}{'turns':>7}{'in contact':>12}"
                 f"{'ended with a blow':>20}")
        for r in rows:
            self.say(f"{r['who']:<16}{r['turns']:>7}{r['contact']:>12}"
                     f"{r['blows']:>20}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--save", default="PORSAVE13.D64",
                   help="the save disk to load, inside --disks")
    p.add_argument("--disks", default=str(DISKS),
                   help="where the player's disks are; read, never written")
    p.add_argument("--slot", type=int, default=None,
                   help="demand this pool slot rather than the first free one")
    p.add_argument("--budget", type=float, default=600.0,
                   help="seconds to give each fight")
    p.add_argument("--fights", type=int, default=1,
                   help="how many consecutive ambushes to drive")
    p.add_argument("--walk", default="I",
                   help="the move to repeat while looking for a fight")
    p.add_argument("--steps", type=int, default=400,
                   help="give up after this many steps with no fight")
    p.add_argument("--out", default=None,
                   help="where the log goes (default work/fightrun/<save>.jsonl)")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    disks = pathlib.Path(args.disks)
    out = pathlib.Path(args.out) if args.out else (
        ROOT / "work" / "fightrun" / f"{pathlib.Path(args.save).stem}.jsonl")
    run = Run(out, args.quiet)
    slot = claim_slot(args.slot, f"fightrun/{args.save}")
    run.say(f"slot {slot.n} display {slot.display}  log {out}")
    slot.seed_vicerc()
    here = pathlib.Path(slot.dir)
    for i in range(1, 9):
        src = disks / f"POOL{i}.D64"
        if src.exists():
            shutil.copy(src, here / f"SIDE{i}.D64")
    shutil.copy(disks / args.save, here / "SIDE0.D64")

    sess = S.Session(str(here / "SIDE1.D64"), slot=slot)
    sess.save_disk = str(here / "SIDE0.D64")
    started = time.time()
    rc = 0
    try:
        if not sess.boot():
            raise RuntimeError("boot failed")
        if not sess.load_save():
            raise RuntimeError("load_save failed")
        if not sess.begin_adventuring():
            raise RuntimeError("begin_adventuring failed")
        sess.settle(3)
        run.say(f"in the world at {sess.position()}")
        run.emit("world", at=list(sess.position()))
        for fight in range(1, args.fights + 1):
            steps = 0
            while not sess.in_combat():
                if steps > args.steps:
                    raise RuntimeError("route exhausted with no fight")
                sess.walk_one(args.walk)
                sess.handle_prompt()
                steps += 1
            run.say(f"fight {fight}: after {steps} steps, "
                    f"t={round(time.time() - started, 1)}s")
            run.emit("fight_start", fight=fight, steps=steps)
            r = sess.fight(budget=args.budget, tactic=run.tactic)
            # `bars` as well as `lines`.  A fight that is won and then does
            # not hand the party back to the world spends the rest of its
            # budget somewhere, and the row-24 bars are the only record of
            # where: one run reported `won` at 149 seconds and returned at
            # 900 with no way of saying what the other 751 went on.
            run.emit("fight_end", fight=fight, outcome=r.outcome,
                     turns=r.turns, seconds=round(r.seconds, 1),
                     acted=r.acted, lines=r.lines, bars=r.bars)
            run.say(f"fight {fight}: {r.outcome} turns={r.turns} "
                    f"seconds={round(r.seconds, 1)}")
            run.report()
            if r.outcome in (S.LOST, S.NOT_FIGHTING):
                break
    except Exception:
        import traceback
        traceback.print_exc()
        rc = 1
    finally:
        try:
            sess.close()
        except Exception:
            pass
        slot.teardown()
        slot.release()
        run.close()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
