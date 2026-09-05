"""Where each title keeps the bytes a fast travel writes.

`automap/actions.py` carries the behaviour; this carries the numbers. They are
separated because the numbers are the part that is per title, and every one of
them was a Pool of Radiance constant until
`#19 (Can Curse be fast-travelled at all, or is the mechanism Pool of
Radiance's alone?)` read the other two titles' overlays.

**Nothing here is Pool of Radiance's address with an offset applied.** Each
field's comment says which instruction it was read out of, and
`tests/test_newecl.py` re-derives the lot off the player's own disks by
`tools/newecl.py`'s procedure -- find the script VM by its self-modifying
dispatch, take entry `$20` of the tables it builds, read the routine. A
constant written down is a claim nothing checks.

**A title with no row is offered no fast travel at all.** `addresses_for`
answers None, `FastTravel.legality` refuses, and `automap.actions.area_rows`
hands back nothing -- because the failure of a wrong address here is not an
error message, it is a `JMP` into somebody else's code and a byte written into
whatever the running title keeps at another title's number. Three of the six
C64 Gold Box titles have been read; the Krynn pair and Gateway have not.

## What differs, and what does not

| | Pool of Radiance | Curse | Silver Blades |
|---|---|---|---|
| `NEWECL` handler | `$2011` | `$21BA` | `$20E6` |
| tail, where a trip enters | `$2034` | `$21DD` | `$210C` |
| cache slot | `$6E1B` | `$7F1B` | `$7F1B` |
| disk byte | `$6E12` | `$7F12` | `$7F12` |
| came-from | `$49F2` | `$4BF2` | `$4BF2` |
| scratch wipe | `$4A00`+32 | `$4C00`+32 | `$4C00`+32 |
| also zeroed | -- | -- | **`$4BFB`** |
| indoors flag | `$49E6` | `$4BE6` | `$4BE6` |
| wall slot pinned | `$49E7`+3 | `$4BE7`+3 | `$4BE7`+3 |
| resident `WALLS` slot | `$6E1C` | none | none |
| travel-grid square | `$49C3` | none | none |
| live triple | `$C04B` | `$C04B` | `$C04B` |

The live triple does not relocate in any of them, which is the whole reason a
square can be written before the jump and flushed by the handler itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

#: Where the engine keeps the party's square while the game runs: x, y, facing.
#: **Unrelocated in all three titles read**, which is not an assumption --
#: `NEWECL`'s own tail call is `LDA <indoors> / BEQ / LDX #$02 / LDA $C04B,X /
#: STA <save position>,X`, and the `$C04B` in it is the same three bytes in
#: Pool of Radiance's `DUNGEON $1A3C`, Curse's `$1BE7` and Silver Blades'
#: `$1AF9`. CONFIRMED from the instructions, and measured in a running Curse
#: (`#19`).
LIVE_SQUARE = 0xC04B

#: How many bytes `NEWECL` wipes at `scratch`: `LDX #$1F ... DEX / BPL`, the
#: same count in all three.
SCRATCH_LEN = 0x20

#: How many wall pieces `wall_slot_pinned` covers. `DUNGEON` unpacks three --
#: `$ED50`, `$F05C` and `$F368` in Pool of Radiance.
WALL_SLOT_PINNED_LEN = 3


@dataclass(frozen=True)
class FastTravelAddresses:
    """One title's fast-travel addresses, each read out of that title's own
    overlays.

    Five fields are `NEWECL`'s own writes and its entry point; the rest are
    what a trip has to set up around them, and the three that can be None are
    the ones a later title turned out not to have.
    """

    #: `goldbox.games.Game.key`, so a row cannot be matched to the wrong title
    #: by a display string.
    key: str
    #: `goldbox.games.Game.title`, which is how `automap.actions.area_rows` and
    #: `goldbox/areas.py` spell a title. Kept here so the lookup takes either.
    title: str

    #: The `NEWECL` handler's head. Nothing jumps here -- a trip has no script
    #: stream for the operand fetch -- and it is carried so the tail can be
    #: shown to belong to it.
    handler: int
    #: Where a trip enters instead: the address the handler's own
    #: `CMP #$FF / BEQ` branches to, past the operand fetch.
    tail: int

    #: The `ECL` slot of the loaded-files cache. Bit 7 means "reload me", and
    #: the low seven bits are the area id.
    slot: int
    #: Which side of the game disks the arriving area lives on. The loader
    #: prompts when that side is not in the drive.
    disk: int
    #: Where the departing area's id is left for the arriving script to read.
    came_from: int
    #: The 32 bytes `NEWECL` zeroes: the origin of the scratch/persistent split.
    scratch: int
    #: Non-zero indoors, zero on the travel grid. Read, never written.
    indoors: int
    #: The key-wait loop `DUNGEON` idles in, `[start, end)`. The one place it
    #: is safe to take the program counter from.
    key_wait: tuple[int, int]
    #: The key fetcher that loop calls, in `LIBRARY`, `[start, end)`. Safe for
    #: the same reason: it is called *from* the loop.
    key_fetch: tuple[int, int]

    #: One flag per wall piece. Non-zero means "keep whatever screen codes are
    #: already there", so a piece can hold the previous area's wall art
    #: (`#179`). Zeroed by a trip because the departing scripts that clear it
    #: are what a trip skips.
    wall_slot_pinned: int | None = None
    wall_slot_pinned_len: int = WALL_SLOT_PINNED_LEN

    #: Slot 9 of the loaded-files cache, the resident `WALLS` file (`#156`).
    #: **Pool of Radiance only** -- it is the one title with a `WALLS00`, and
    #: setting a cache slot for a file another title does not have would be
    #: writing a number into a byte whose meaning here is unread.
    walls_slot: int | None = None

    #: The travel grid's own square, window-local x then y. **Pool of Radiance
    #: only**: no other C64 title in the family has a square-engine overland
    #: (`goldbox.games.Game.travel_grid`).
    travel_square: int | None = None

    #: Anything else the handler zeroes, one byte each. Silver Blades' zeroes
    #: `$4BFB` in front of the wipe and the other two do not.
    zeroed: tuple[int, ...] = ()

    #: The live x/y/facing triple, which no title relocated.
    live_square: int = LIVE_SQUARE
    scratch_len: int = SCRATCH_LEN

    @property
    def has_travel_grid(self) -> bool:
        """Can this title put a party on an overland square at all?"""
        return self.travel_square is not None


#: Pool of Radiance. `DUNGEON $2011`, and the five addresses in it are the
#: ones `docs/118-debug-mode.md` §3 has measured since P15 -- this row is a
#: restatement of what `automap/actions.py` already shipped, not a new reading,
#: and `tests/test_fasttravel_addresses.py` checks the two against each other.
#: `KEY_WAIT` and `KEY_FETCH` were measured from 400 program-counter samples
#: of an idle party and then reproduced from the bytes.
POOL_OF_RADIANCE = FastTravelAddresses(
    key="pool-of-radiance",
    title="Pool of Radiance",
    handler=0x2011,
    tail=0x2034,
    slot=0x6E1B,
    disk=0x6E12,
    came_from=0x49F2,
    scratch=0x4A00,
    indoors=0x49E6,
    key_wait=(0x10C2, 0x10EC),
    key_fetch=(0x2E4E, 0x2E6B),
    wall_slot_pinned=0x49E7,
    walls_slot=0x6E1C,
    travel_square=0x49C3,
)

#: Curse of the Azure Bonds. `DUNGEON $21BA`, instruction for instruction Pool
#: of Radiance's handler with three relocations: the cache slot by the loader's
#: page (`+$1100`) and the two save-relative writes by `save_load_address`
#: (`+$0200`). CONFIRMED from the bytecode, and CONFIRMED again in the running
#: machine -- four driven warps, each with an exact-byte map match at `$0400`
#: and the arriving script's own text on screen (`#19`).
#:
#: **No `walls_slot` and no `travel_square`.** Curse's disks carry no `WALLS`
#: file, only `WALLDEF01`-`WALLDEF12` and their `WALLSET`s, so slot 9 of the
#: cache holds something nobody has read; and it has no square-engine overland.
CURSE_OF_THE_AZURE_BONDS = FastTravelAddresses(
    key="curse-of-the-azure-bonds",
    title="Curse of the Azure Bonds",
    handler=0x21BA,
    tail=0x21DD,
    slot=0x7F1B,
    disk=0x7F12,
    came_from=0x4BF2,
    scratch=0x4C00,
    indoors=0x4BE6,
    key_wait=(0x101D, 0x1056),
    key_fetch=(0x2FD7, 0x2FF8),
    wall_slot_pinned=0x4BE7,
)

#: Secret of the Silver Blades. `DUNGEON $20E6`, and **six writes rather than
#: five**: `LDX #$1F / LDA #$00 / STA $4BFB / STA $4C00,X / DEX / BPL $2106`.
#: The back edge is the `STA $4C00,X`, so `$4BFB` is written once and the wipe
#: 32 times.
#:
#: `$4BFB` is the flag that suppresses the party's coordinates on the status
#: line -- `DUNGEON $0A0E` is `LDA $4BFB / BNE` over the block that loads the
#: square for printing (`docs/138-multiple-games.md` §8). Zeroing it is what
#: the handler does, so a trip does it too.
#:
#: PROBABLE rather than CONFIRMED: every address is read off Silver Blades' own
#: overlays and the handler is the same routine, and **no Silver Blades party
#: has been fast-travelled through this code**. `tools/ssbwarp.py` is the
#: driver that would settle it.
SECRET_OF_THE_SILVER_BLADES = FastTravelAddresses(
    key="secret-of-the-silver-blades",
    title="Secret of the Silver Blades",
    handler=0x20E6,
    tail=0x210C,
    slot=0x7F1B,
    disk=0x7F12,
    came_from=0x4BF2,
    scratch=0x4C00,
    indoors=0x4BE6,
    key_wait=(0x1050, 0x1089),
    key_fetch=(0x4101, 0x4122),
    wall_slot_pinned=0x4BE7,
    zeroed=(0x4BFB,),
)

#: Every title whose overlays have been read, by `Game.key`. Champions of
#: Krynn, Death Knights of Krynn and Gateway to the Savage Frontier are absent
#: rather than empty: nobody has looked, and an entry with Pool of Radiance's
#: numbers in it would fast-travel a party by writing into whatever those
#: titles keep at them.
ADDRESSES: Mapping[str, FastTravelAddresses] = MappingProxyType({
    a.key: a for a in (POOL_OF_RADIANCE, CURSE_OF_THE_AZURE_BONDS,
                       SECRET_OF_THE_SILVER_BLADES)
})

_BY_TITLE: Mapping[str, FastTravelAddresses] = MappingProxyType(
    {a.title: a for a in ADDRESSES.values()})


def addresses_for(game=None) -> FastTravelAddresses | None:
    """This title's fast-travel addresses, or None if nobody has read it.

    Takes whatever the caller is holding: a `goldbox.games.Game`, a `Game.key`,
    a `Game.title` -- which is how `goldbox/areas.py` spells a title -- or
    None, which means Pool of Radiance the way it does everywhere else in the
    program.

    **None is a refusal and never a default.** A caller that falls back to
    Pool of Radiance's row for a title that has no row writes Pool of
    Radiance's numbers into another game, which is the corruption `#14` fixed
    for the area list and the same one address by address.
    """
    if game is None:
        return POOL_OF_RADIANCE
    key = getattr(game, "key", None)
    if key is not None:
        return ADDRESSES.get(key)
    if isinstance(game, str):
        return ADDRESSES.get(game) or _BY_TITLE.get(game)
    return None


def supported(game=None) -> bool:
    """Can a fast travel be made in this title at all?"""
    return addresses_for(game) is not None
