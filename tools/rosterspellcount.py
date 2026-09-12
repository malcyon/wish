#!/usr/bin/env python3
"""Check a C64 roster block's per-level memorised-spell counters against the list.

`COM.PREP $15ED` recomputes roster `+0x03` onwards from the character record's
own memorised-spell list at `0x020`, one counter per spell level, using the
spell-id-to-level classifier at `COM.PREP $1751` (`COMBAT $26FE` is the same
routine).  So the counters are **derived** and this tool measures how often the
stored bytes still agree with the list they were derived from -- which is the
question `#365 (Three roster bytes have no established meaning, and a C64 party
converted to DOS is told so with no way to check it)` asks.

    tools/rosterspellcount.py                     every C64 save it can find
    tools/rosterspellcount.py --disks DIR         one directory of D64s
    tools/rosterspellcount.py --quiet             just the totals

Each row is one occupied roster block: the counters as stored, the counters as
`COM.PREP` would recompute them, and whether they match.  A **disagreement is
not corruption**: nothing in `CAMP` touches the counters, so memorising and
resting leaves them holding whatever the last fight computed, and a save taken
before any fight holds zeroes.  `docs/30-savegame-layout.md` has the reading.

Nothing here writes.  The game's bytes stay on the player's own disks.
"""

from __future__ import annotations

import argparse
import collections
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from automap.paths import disk_globs, find_disks  # noqa: E402
from goldbox import c64_codec, c64_port, savegame  # noqa: E402
from goldbox.d64 import D64  # noqa: E402

#: `COM.PREP $1751`: `LDA #$01 / CPX #$16 / ADC #$00 / CPX #$24 / ADC #$00 /
#: CPX #$38 / ADC #$00 / RTS`.  A spell id below 22 is level 1, 22-35 level 2,
#: 36-55 level 3 and 56 or above level 4 -- which is `goldbox.spells`'s own
#: `_GROUPS_POOL` boundaries, arrived at independently from the spell names.
POOL_LEVEL_THRESHOLDS = (0x16, 0x24, 0x38)

#: How many counters the recompute loop clears: `LDX #$08 / LDA #$00 /
#: STA $6C03,X / DEX / BPL`, so roster `+0x03` to `+0x0B`.
COUNTER_AT = savegame.ROSTER_UNKNOWN_03
COUNTER_LEN = 9

#: How many of those Pool of Radiance can ever fill -- the classifier returns
#: 1 to 4, so `+0x07` upwards stay zero for a party character.  `COMBAT $1C57`
#: stores a coordinate pair over `+0x0A`/`+0x0B` during a fight.
POOL_COUNTERS = 4


def spell_level(spell_id: int) -> int:
    """The level `COM.PREP $1751` gives a Pool of Radiance spell id."""
    return 1 + sum(1 for t in POOL_LEVEL_THRESHOLDS if spell_id >= t)


def recompute(memorised: bytes) -> list[int]:
    """What `COM.PREP $15ED` would leave in the nine counters."""
    counters = [0] * COUNTER_LEN
    for spell_id in memorised:
        if spell_id == 0:
            continue
        counters[spell_level(spell_id) - 1] += 1
    return counters


def disks(root: str, game) -> list[str]:
    seen: dict[str, str] = {}
    for pattern in disk_globs(game):
        for path in sorted(pathlib.Path(root).glob(pattern)):
            seen.setdefault(os.path.normcase(str(path)), str(path))
    for path in sorted(pathlib.Path(root).glob("*.[dD]64")):
        seen.setdefault(os.path.normcase(str(path)), str(path))
    return sorted(seen.values())


class Row:
    __slots__ = ("disk", "slot", "name", "stored", "wanted")

    def __init__(self, disk, slot, name, stored, wanted):
        self.disk, self.slot, self.name = disk, slot, name
        self.stored, self.wanted = stored, wanted

    @property
    def agrees(self) -> bool:
        return list(self.stored) == list(self.wanted)

    @property
    def vacuous(self) -> bool:
        """Nothing memorised, so agreeing costs the reading nothing."""
        return not any(self.wanted)

    @property
    def stale_zero(self) -> bool:
        """Stored all zero where the list says there is something to count."""
        return not any(self.stored) and any(self.wanted)

    @property
    def behind(self) -> bool:
        """Every counter at or below what the list says -- what a cache that
        was computed before the party memorised more looks like."""
        return all(s <= w for s, w in zip(self.stored, self.wanted))


def census(root: str, game) -> list[Row]:
    rows: list[Row] = []
    for path in disks(root, game):
        try:
            image = D64.open(path)
            _game, sg0, sg1 = savegame.load_save(image, game)
        except Exception:
            continue
        if sg1 is None:
            continue
        for slot in sg0.slots:
            if not slot.occupied:
                continue
            block = sg1.roster(slot.index)
            if block.roster_in_use == 0:
                continue
            record = slot.record
            stored = list(block.raw[COUNTER_AT:COUNTER_AT + COUNTER_LEN])[:POOL_COUNTERS]
            wanted = recompute(c64_codec.get_memorised(record, game))
            rows.append(Row(pathlib.Path(path).name, slot.index,
                            record.name, stored, wanted[:POOL_COUNTERS]))
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--disks", action="append",
                        help="a directory of D64 images; repeatable")
    parser.add_argument("--quiet", action="store_true",
                        help="totals only, no per-character rows")
    args = parser.parse_args(argv)

    game = c64_port.by_key("pool-of-radiance")
    roots = args.disks or [os.environ.get("POR_DISKS") or str(find_disks())]

    rows: list[Row] = []
    for root in roots:
        if not root or not os.path.isdir(root):
            print(f"no such directory: {root}", file=sys.stderr)
            continue
        rows += census(root, game)

    if not rows:
        print("no Pool of Radiance C64 saves found")
        return 1

    if not args.quiet:
        print(f"  {'disk':24s} {'slot':>4}  {'name':16s} "
              f"{'stored':16s} {'recomputed':16s} ok")
        for row in rows:
            stored = " ".join(f"{n:3d}" for n in row.stored)
            wanted = " ".join(f"{n:3d}" for n in row.wanted)
            print(f"  {row.disk:24s} {row.slot:>4}  {row.name:16s} "
                  f"{stored:16s} {wanted:16s} {'y' if row.agrees else 'n'}")

    real = [r for r in rows if not r.vacuous]
    agree = sum(1 for r in real if r.agrees)
    zero = sum(1 for r in real if r.stale_zero)
    ahead = [r for r in real if not r.agrees and not r.behind]
    print(f"\n  {len(rows)} occupied roster blocks over "
          f"{len({r.disk for r in rows})} disks")
    print(f"  {len(rows) - len(real)} have nothing memorised, so agreeing "
          f"says nothing; {len(real)} have something to count")
    print(f"  of those {len(real)}: {agree} agree with the recompute, "
          f"{len(real) - agree} do not")
    print(f"  {zero} of the disagreements are all-zero counters, and "
          f"{len(real) - agree - zero} are partly behind the list")
    print(f"  {len(ahead)} hold a counter **higher** than the list, which the "
          f"recompute cannot explain")
    by_disk = collections.Counter(r.disk for r in ahead)
    if by_disk:
        print("  those are on: "
              + ", ".join(f"{k} x{v}" for k, v in by_disk.most_common()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
