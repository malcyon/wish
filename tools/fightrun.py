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
import os
import pathlib
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOLS))

import session as S  # noqa: E402

from automap.paths import find_disks  # noqa: E402

#: Where the player keeps the disks, unless `--disks` says otherwise.  Read
#: only, ever: everything is copied into the slot's directory first.
#:
#: `$POR_DISKS` first, then the search `automap.paths` already does, which is
#: what every other tool here uses -- a path spelled out in the source is one
#: developer's machine written into a program that ships, and
#: `test_no_hardcoded_user_paths` fails the build on one.
DISKS = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")


#: Claiming a slot and staging the player's disks both live in
#: `tools/session.py` now: every tool that drives a session needs them, and
#: this file's copy was one of two.
claim_slot = S.claim_slot


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
        it is in.

        `FightResult.acted` now rests on the same answer, counted by `fight`
        rather than here (`#163`).  This stays because it is the count **per
        character**, which is what says one character took every turn
        (`#165`).

        **The two counts are not the same number and are not meant to be.**
        `fight` counts every turn that ended in a blow; this counts only the
        ones whose character already had an enemy in contact when the game
        asked it, so a character that walked three squares and then struck is
        in `blows` and not in this column.  `r.blows` is the total.
        """
        rows: dict[str, dict] = {}
        for t in self.turns:
            who = t["who"] or "?"
            r = rows.setdefault(who, {"who": who, "turns": 0,
                                      "contact": 0, "blows": 0})
            r["turns"] += 1
            if t["dist"] == 1:
                r["contact"] += 1
                if t["chose"] == S.ATTACK:
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
    started = time.time()
    rc = 0
    sess = None
    try:
        # Everything that can fail belongs inside this `try`, and the disk
        # copies are the ones that actually do: a misspelled `--save` is an
        # ordinary morning's mistake, and outside here it exits through
        # Python's own handler with the run's log unwritten and unclosed.
        # `Session` points itself at `SIDE0.D64` inside the slot, which is
        # where `stage_disks` just copied the save, so nothing needs saying
        # here.
        sess = S.Session(S.stage_disks(slot, disks, args.save), slot=slot)
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
            # `bars` and `highlights` as well as `lines`.  A fight that is
            # won and then does not hand the party back to the world spends
            # the rest of its budget somewhere, and row 24 is the only record
            # of where: one run reported `won` at 149 seconds and returned at
            # 900 with no way of saying what the other 751 went on.  The
            # highlight is logged beside the bar because the bar alone could
            # not say whether the driver was sitting on the wrong command
            # (`#171`).
            run.emit("fight_end", fight=fight, outcome=r.outcome,
                     turns=r.turns, seconds=round(r.seconds, 1),
                     acted=r.acted, blows=r.blows, evidence=r.evidence,
                     anybody_swung=r.anybody_swung,
                     lines=r.lines, bars=r.bars,
                     highlights=r.highlights)
            run.say(f"fight {fight}: {r.outcome} turns={r.turns} "
                    f"seconds={round(r.seconds, 1)}")
            # What `acted` rests on, beside `acted` itself.  A run whose
            # summary says only True is a run somebody has to take on trust,
            # and this one is the check that decides whether a conversion has
            # been proven in combat.
            run.say(r.evidence)
            run.report()
            if r.outcome in (S.LOST, S.NOT_FIGHTING):
                break
    except Exception as exc:
        import traceback
        # Into the log as well as onto the terminal: an unattended overnight
        # run is read the next morning through its `.jsonl`, and a failure
        # that exists only in a terminal nobody was watching is a run that
        # says nothing about why it stopped.
        run.emit("failed", error=repr(exc), traceback=traceback.format_exc())
        traceback.print_exc()
        rc = 1
    finally:
        # Each step guarded separately. Teardown failing is exactly when the
        # log is worth having, and an unguarded raise here would take the
        # release and the log's own close down with it.
        for what, step in (("session close", lambda: sess and sess.close()),
                           ("slot teardown", slot.teardown),
                           ("slot release", slot.release)):
            try:
                step()
            except Exception as exc:
                run.emit("cleanup_failed", step=what, error=repr(exc))
                run.say(f"Cleanup failed at {what}: {exc!r}")
                rc = rc or 1
        run.close()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
