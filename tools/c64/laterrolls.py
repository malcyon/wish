#!/usr/bin/env python3
"""Corroborate Curse's d20 store and attack block, live, in a driven fight.

`#39 (Combat view and combat log for Curse and Silver Blades)`'s comments read
the later titles' attack-roll routine out of the binary and named two
addresses in `ECL64` (resident at `$8000`), CONFIRMED from the instructions
alone and never watched on a running machine:

    the d20 store              $A915
    the attack block (12 B)    $9458-$9463
        +0  the number needed  (`ACTOR` +4, `TARGET` +5, `ATTEMPTS` +9,
                                 `LANDINGS` +A, hit flag +B: PROBABLE by
                                 census, not by reading the write)

This drives the same Tilverton `PUNCH BARKEEP` fight `#334 (The session
driver cannot fight in Curse or Silver Blades, and says the party is not in a
fight while it is standing on the combat floor)` proved
(`tools/c64/laterbattle.py`, `cited/334/run5`), and reads those thirteen
bytes before combat, on first reaching the floor, and again after every
`QUICK`-resolved turn -- so a change is seen against a baseline rather than
read once and trusted.

    tools/c64/laterrolls.py --pool 4 \\
        --save ~/wish-specimens/por-c64/WISH-SPEC-curse-trained-party.D64 \\
        --turns 8 --out DIR

Nothing is written outside `--out` and the pool slot's own directory.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from goldbox import c64_port as G  # noqa: E402
from tools import gamedisks, scratch  # noqa: E402
from tools.c64 import laterbattle as LB  # noqa: E402
from tools.c64 import session as S  # noqa: E402

#: Read live off the machine in `ECL64` (resident at `$8000`), per
#: `#39`'s 2026-09-09 comment. Both CONFIRMED from the binary alone before
#: this run; the attack block's inner five offsets are PROBABLE by census.
D20 = 0xA915
ATTACK_BLOCK = 0x9458
ATTACK_LEN = 12
#: Offsets into the 12-byte block this run watches for, named from the
#: issue's census table.
OFFSETS = {"number_needed": 0, "ACTOR": 4, "TARGET": 5, "ATTEMPTS": 9,
           "LANDINGS": 0xA, "hit_flag": 0xB}


class RollsBattle(LB.Battle):
    """`tools.c64.laterbattle.Battle`, plus the two roll addresses."""

    def read_rolls(self, stage: str) -> dict:
        d20 = self.peek(D20, 1)[0]
        block = self.peek(ATTACK_BLOCK, ATTACK_LEN)
        out = {
            "stage": stage,
            "d20": d20,
            "block": block.hex(" "),
            **{name: block[off] for name, off in OFFSETS.items()},
        }
        self.log("rolls", **out)
        return out

    def quickfight_with_rolls(self, turns: int) -> list[dict]:
        """`Run.quickfight`, but read the two roll addresses around each press."""
        readings = []
        for turn in range(turns):
            if not self.in_combat():
                self.log("fight-over", turn=turn, row24=self.row24())
                break
            before = self.read_rolls(f"before-turn-{turn}")
            rows = [r.rstrip() for r in self.dump(f"turn-{turn:02d}")]
            said = [r.strip() for r in rows
                    if "HIT" in r or "MISS" in r or "DAMAGE" in r]
            pressed = self.sess.press_bar("QUICK", timeout=15.0)
            self.sess.settle(3.0)
            after = self.read_rolls(f"after-turn-{turn}")
            after_rows = [r.strip() for r in self.sess_rows()
                          if "HIT" in r or "MISS" in r or "DAMAGE" in r]
            self.log("quick", turn=turn, pressed=pressed, before_text=said,
                     after_text=after_rows, row24=self.row24())
            readings.append({"turn": turn, "before": before, "after": after})
        else:
            self.log("quick-budget", turns=turns)
        return readings


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--save", required=True, help="the save disk to boot")
    p.add_argument("--disks", default=None, help="Curse's six sides")
    p.add_argument("--pool", dest="slot", type=int, default=None,
                   help="claim this instance-pool slot")
    p.add_argument("--out", default=str(scratch.scratch_dir("laterrolls", "run")),
                   help="run directory")
    p.add_argument("--steps", type=int, default=60, help="walk budget")
    p.add_argument("--world", type=float, default=240.0,
                   help="seconds to give BEGIN ADVENTURING to reach the world")
    p.add_argument("--look", type=float, default=8.0,
                   help="seconds between readings while waiting for the world")
    p.add_argument("--wait", type=int, default=15,
                   help="settles to give the combat screen to draw")
    p.add_argument("--turns", type=int, default=8,
                   help="turns to resolve with QUICK, reading the rolls "
                        "before and after each")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    disks = args.disks or str(gamedisks.find(G.CURSE_OF_THE_AZURE_BONDS.key)
                               or "")
    if not disks:
        raise SystemExit("no Curse disks; pass --disks")
    out = pathlib.Path(args.out)
    run = RollsBattle(out, args.quiet)
    run.slot = S.claim_slot(args.slot, "laterrolls/39")
    run.log("slot", n=run.slot.n, display=run.slot.display,
            dir=str(run.slot.dir), save=args.save, disks=disks,
            title=G.CURSE_OF_THE_AZURE_BONDS.title)
    rc = 1
    try:
        rc = LB.curse_fight(run, args, disks)
        if rc:
            return rc
        sess = run.sess
        # Baseline: the two addresses in the world, before any fight exists.
        run.read_rolls("in-the-world")
        for n in range(args.wait):
            if run.in_combat():
                break
            s = sess.screen()
            state = sess.combat_state(s)
            run.log("waiting-for-combat", look=n, mode=sess.mode(),
                    readable=s is not None, bar=state.kind,
                    row24=state.text.strip())
            if state.kind == S.BAR_PRESS or s is None:
                sess.press_kernal(0x0D)
            sess.settle(4.0)
        run.dump("combat-floor")
        run.log("combat", on_the_floor=run.in_combat(), mode=sess.mode(),
                row24=run.row24())
        if not run.in_combat():
            rc = 2
            return rc
        run.probe("combat-floor")
        run.read_rolls("combat-floor")
        run.quickfight_with_rolls(args.turns)
        run.probe("after-quick")
        run.read_rolls("after-quick")
        rc = 0
    finally:
        run.log("done", rc=rc)
        if run.sess is not None:
            run.sess.terminate()
        if getattr(run, "slot", None) is not None:
            run.slot.teardown()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
