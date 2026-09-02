#!/usr/bin/env python3
"""Raise a character's level on a **running** machine, past the trainer.

Written for `#142 (The party effects line is computed every poll and shown
nowhere)`, where the question was what the game writes into the effect table
for a spell that lands on the whole party -- and every party on every disk
here tops out at a **level 2 cleric**, two levels below the lowest such spell.
There was no save to answer it from and no reasonable amount of play that
would make one.

So this replays what `automap/actions.py`'s `LevelUp` already does -- the
trainer's own sequence out of `GEN $1B8C`, field for field
(`docs/135-levelling.md`) -- against a pool slot's binary monitor, once per
level asked for.

    tools/livelevel.py --port 6522 --name ROLAND --levels 3

**Experience is written first, at every level, and that is the whole reason
this is not a one-liner.** The trainer clamps experience to just under the
next threshold, so a character levelled twice in a row is short of the second
threshold by one point and `LevelUp` refuses. Each round therefore writes a
number well above every threshold and lets the clamp bring it back down.

**What it leaves behind is a doctored character**: the experience it was
given is not experience it earned, and the levels are real but unpaid for. It
is a rig for an experiment, not a way to play, and a machine it has touched
should not be saved over anything anybody wants to keep.

`--dry-run` prints the party and writes nothing.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from automap import actions  # noqa: E402
from automap.target import ViceTarget  # noqa: E402
from goldbox import games  # noqa: E402
from goldbox.layout import field_by_name  # noqa: E402

#: Above every threshold in `goldbox/levels.py`, so one write covers any level
#: the ceilings allow. The clamp puts it back to something the record can hold.
PLENTY = 99_000


def show(party) -> None:
    for m in party.members:
        record = m.record
        print(f"  slot {m.slot}  {m.name:16s} level {record.get('level')} "
              f"C{record.get('level_cleric')} "
              f"MU{record.get('level_magic_user')} "
              f"F{record.get('level_fighter')} "
              f"T{record.get('level_thief')}  "
              f"xp {record.get('experience')}  hp {m.hp}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Raise a character's level on a running emulator, by "
                    "replaying what the training hall writes.")
    ap.add_argument("--port", type=int, required=True, metavar="N",
                    help="the binary monitor to drive; a pool slot prints its "
                         "own. Required, and 6502/6510/6600 are refused")
    ap.add_argument("--name", default="", metavar="WHO",
                    help="the character to raise, by the name the game shows")
    ap.add_argument("--levels", type=int, default=1, metavar="N",
                    help="how many times to level (default: %(default)s)")
    ap.add_argument("--class-name", default="", metavar="CLASS",
                    help="which class to raise, for a multi-class character; "
                         "otherwise the one the trainer would pick")
    ap.add_argument("--spell", type=int, default=None, metavar="ID",
                    help="the spell a magic-user learns, which the game makes "
                         "it choose and this will not choose for it")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the party and write nothing")
    args = ap.parse_args(argv[1:])

    # **Donald's own ports, and this tool writes.** `CLAUDE.md` is flat about
    # 6502, 6510 and 6600: anything listening there is a game a human started
    # from the desktop menu -- do not attach, do not probe. The read-only
    # tools beside this one default to 6502 and are harmless doing it; this
    # one puts experience into a character and forces a level-up, so the same
    # default would mean one forgotten flag corrupts a save somebody is in the
    # middle of playing. `--port` is required rather than defaulted, and these
    # three are refused outright: no version of this tool's job wants them.
    if args.port in (6502, 6510, 6600):
        print(f"Port {args.port} is the human's own game, and this tool "
              f"writes to it. Claim a pool slot and pass the port it prints.",
              file=sys.stderr)
        return 2

    target = ViceTarget(host="127.0.0.1", port=args.port)
    try:
        party = actions.read_party(target, games.DEFAULT)
        if party is None:
            print("The machine had no party in it.")
            return 1
        print("Before:")
        show(party)
        if args.dry_run:
            return 0
        if not args.name:
            print("Say which character with --name.")
            return 2
        for round_ in range(args.levels):
            party = actions.read_party(target, games.DEFAULT)
            wanted = [m for m in party.members
                      if m.name.strip().upper() == args.name.strip().upper()]
            if not wanted:
                print(f"No character called {args.name} is in the party.")
                return 2
            member = wanted[0]
            size = field_by_name("experience").size
            target.write(member.field_address("experience"),
                         PLENTY.to_bytes(size, "little"))
            outcome = actions.LevelUp().run(
                target, slot=member.slot,
                class_name=args.class_name, spell=args.spell)
            print(f"  {round_ + 1}: {outcome.message}")
            if not outcome.ok:
                return 1
        print("After:")
        show(actions.read_party(target, games.DEFAULT))
    finally:
        target.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
