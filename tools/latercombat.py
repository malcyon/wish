#!/usr/bin/env python3
"""Where each C64 Gold Box title keeps a fight, and one reader for all three.

`automap/combat.py` reads a running fight, and every address in it is Pool of
Radiance's. That is right for the window, which only opens on a title whose
addresses have been measured, and wrong for `tools/session.py`, which is asked
to drive Curse of the Azure Bonds and Secret of the Silver Blades as well: at
Pool of Radiance's addresses a Curse party standing on the combat floor reads
as no fight at all (`#334`).

So this file holds the per-title table and nothing else. The reading itself is
still `automap.combat`'s -- the shape, the combatant decode, the roster block,
the record slot, the effect arrays -- because a second copy of that would
drift, and the whole difference between the titles is four numbers.

**Two of the six addresses are not per-title at all.** The parameter block is
`$0600` and the camera origin `$037E` in all three, which is a reading rather
than an assumption: `GDRIVE00`, the square engine that draws the arena, names
the same twenty absolute addresses `$0600`-`$061B` and the same `$037E`/`$037F`
in the same order and at the same relative code positions in every one of the
three binaries.

Where the parameter block's *contents* come from is the one structural
difference. Pool of Radiance loads them off a `SQRPACI<nn>` file; the later two
ship no such file and their `COM.PREP` writes the block as immediate constants
-- Curse `$1436`-`$147E`, Silver Blades `$14AC`-`$14F4`, identical value for
value. That does not change the reading, because the block is read at run time
in both cases.

Nothing here opens a disk or writes anything. `docs/101-combat-view.md` has
Pool of Radiance's map of a fight; `#334` has where the later two's came from.
"""
from __future__ import annotations

import pathlib
import sys
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from automap.combat import (  # noqa: E402
    COMBAT,
    POSITION_STRIDE,
    ROSTER_STRIDE,
    Battle,
    _blocks,
    _combatant,
    helpless_indices,
    shape_from_params,
)
from goldbox import c64_port as G  # noqa: E402
from goldbox.savegame import (  # noqa: E402
    HEADER_SIZE,
    RECORD_SLOT_COUNT,
    SLOT_STRIDE,
)

#: The `SQRPACI` parameter block, and how much of it `shape_from_params` wants.
#: **The same address in all three titles** -- see the module docstring.
PARAMS = 0x0600
PARAMS_LEN = 0x14

#: Top-left square of the 7 x 7 window the game draws. The same address in all
#: three titles, for the same reason.
CAMERA = 0x037E


@dataclass(frozen=True)
class CombatMemory:
    """Where one title holds a fight while it is running.

    Everything here is an address in the machine, and none of it can be
    derived from the save's geometry: `mode` and `result` are bytes of the
    loader's own resident page, `roster` grows past the save's last page once
    a fight starts, and `initiative` is a table the combat overlay owns.

    `records` and `save_head` *are* geometry -- the save's load address and
    the twelve record slots `$400` into it -- and are kept here so a caller
    has one place to look rather than two.
    """

    #: `LINKER`'s dispatch byte: which overlay is resident. `2` is COMBAT.
    mode: int
    #: The 64 roster blocks of `$20` bytes, index 0-7 the party.
    roster: int
    #: One initiative byte a combatant; the round ends when all 64 are zero.
    initiative: int
    #: Where the save payload is loaded, which is where the effect arrays are.
    save_head: int
    #: The twelve record slots, `$100` apiece.
    records: int
    #: How the fight ended: `$00`/`$01` won, `$80` lost, `$81` ran away.
    result: int

    @property
    def save_head_length(self) -> int:
        """Enough for the effect arrays *and* the record slots in one read.

        One range rather than two: the cost of a read is the round trip, and
        the records sit `$400` past the head of the same image.
        """
        return HEADER_SIZE + RECORD_SLOT_COUNT * SLOT_STRIDE


#: One row a title, keyed the way `goldbox.c64_port.Game.key` is.
#:
#: **Curse of the Azure Bonds and Secret of the Silver Blades agree on every
#: address**, which is why the two rows below are the same values rather than
#: one row shared: they were derived from each title's own binary
#: independently, and writing them out twice is what makes a future
#: disagreement visible instead of silently inherited.
#:
#: Where each came from, all of it out of the titles' own files (`#334`):
#:
#: * `mode` -- both later titles' `LINKER` opens `LDA $7F11` where Pool of
#:   Radiance's opens `LDA $6E11`. Already `automap.c64.MODE_FLAG_LATER`.
#: * `roster` -- `COM.PREP` stores the roster base into `$03DF`/`$03E0`:
#:   `LDA #$83` at Pool of Radiance `$0895`, `LDA #$67` at Curse `$08A8` and
#:   Silver Blades `$08A8`.
#: * `initiative` -- Pool of Radiance's initiative loop (`COMBAT $08CE`,
#:   `LDA $A380,Y / BEQ / CMP / BCC / BNE / JSR / CMP / BCC / BCS / JSR / STA
#:   / STY / LDA / STA / DEY / BPL`) matches once each in the later titles'
#:   **`COMBAT2`**, reading `LDA $92E8,Y` under an `LDY #$3F`.
#: * `result` -- `POST.COM` writes `STX $7EC7` at Curse `$0906` and Silver
#:   Blades `$0917` where Pool of Radiance writes `STX $6DC7` at `$091A`, at
#:   the end of the same branch `#445 (The game's third fight outcome, THE
#:   PARTY RUNS AWAY, has never been seen on a screen)` read.
BY_KEY: dict[str, CombatMemory] = {
    G.POOL_OF_RADIANCE.key: CombatMemory(
        mode=0x6E11, roster=0x8300, initiative=0xA380,
        save_head=0x4900, records=0x4D00, result=0x6DC7),
    G.CURSE_OF_THE_AZURE_BONDS.key: CombatMemory(
        mode=0x7F11, roster=0x6700, initiative=0x92E8,
        save_head=0x4B00, records=0x4F00, result=0x7EC7),
    G.SECRET_OF_THE_SILVER_BLADES.key: CombatMemory(
        mode=0x7F11, roster=0x6700, initiative=0x92E8,
        save_head=0x4B00, records=0x4F00, result=0x7EC7),
}


def memory_for(game) -> CombatMemory | None:
    """This title's combat addresses, or None when nobody has measured them.

    **None is refusal, not a default.** Champions of Krynn and the two after
    it have never been run under a monitor, and reading Pool of Radiance's
    addresses on one of them yields a plausible battle rather than an error --
    which is the failure `#334` is about, with the titles swapped round.
    """
    if game is None:
        return None
    return BY_KEY.get(getattr(game, "key", None))


def read_battle(target, game=None, previous: Battle | None = None):
    """The fight in progress on `game`, or None when there is not one.

    `automap.combat.read_battle` with the four per-title addresses passed in.
    Two bursts, for the same reason it has two: the map's address and its
    length are in the first one.

    Answers None when the title has no measured addresses, when the mode byte
    is not COMBAT, and when the parameter block does not validate -- the last
    of which is the guard that stops a world screen's `$0600` being read as an
    arena.
    """
    if target is None:
        return None
    where = memory_for(game or G.POOL_OF_RADIANCE)
    if where is None:
        return None
    mode, params, camera = _blocks(target, ((where.mode, 1),
                                            (PARAMS, PARAMS_LEN),
                                            (CAMERA, 2)))
    if not mode or mode[0] != COMBAT:
        return None
    shape = shape_from_params(params)
    if shape is None:
        return None
    terrain, roster, positions, initiative, save_head = _blocks(target, (
        (shape.map_base, shape.length),
        (where.roster, shape.count * ROSTER_STRIDE),
        (shape.positions, shape.count * POSITION_STRIDE),
        (where.initiative, shape.count),
        (where.save_head, where.save_head_length)))
    if len(terrain) < shape.length \
            or len(save_head) < where.save_head_length:
        return None
    records = save_head[where.records - where.save_head:]
    helpless = helpless_indices(save_head)
    people = []
    for i in range(shape.count):
        who = _combatant(i, positions, roster, records, initiative, shape,
                         previous, helpless)
        if who is not None:
            people.append(who)
    return Battle(shape=shape, terrain=bytes(terrain),
                  combatants=tuple(people), camera=(camera[0], camera[1]))
