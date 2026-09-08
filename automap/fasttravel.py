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

    #: **The re-entry addresses `#207 (Run an exit's own handler before Fast
    #: Travel warps out)` rests on, measured only in Pool of Radiance.** A
    #: fast travel used to enter `NEWECL` at its own tail and skip the
    #: departing script -- the Kobold Caves' handler is what drops Princess
    #: Fatima on the way out, so a party that fast-travelled out kept her
    #: (`#180`). These five are the state a step leaves behind for
    #: `DUNGEON`'s own dispatch to pick up:
    #:
    #: * `after_step` -- `$0957`, `JSR $0A4C / JMP $08FC`: the redraw, then
    #:   entry 1, the per-square dispatch that runs after every step lands.
    #: * `forward_key` -- `$0978`, `JSR $098B`: the forward key in MOVE mode,
    #:   which runs `$10EC` (counting whether the step leaves the map into
    #:   `$6DD5`) and then entry 0.
    #: * `redraw` -- `$0A4C`, chained in front of `forward_key` so
    #:   `$C04E`/`$C04F` are fresh before entry 0's own wall test; `after_step`
    #:   calls it itself and needs no chain.
    #: * `saved_sp` -- `$03BF`, `$0809 TSX / STX $03BF`: the main loop's own
    #:   stack depth, rebuilt from rather than trusted, so it does not matter
    #:   whether the player left the game at the command bar or in MOVE mode.
    #: * `main_loop_return` -- `$08A6`: the address the main loop's own `JSR`
    #:   pushed, so `EXIT` unwinds into a state the game itself built.
    #:
    #: All five CONFIRMED against a running machine, three sessions, the NPC
    #: dropped every time the handler was answered `YES`
    #: (`docs/150-departing-prologues.md`). None measured in Curse or Silver
    #: Blades, so both stay None there and a fast travel in either title
    #: keeps entering `NEWECL` at its tail.
    after_step: int | None = None
    forward_key: int | None = None
    redraw: int | None = None
    saved_sp: int | None = None
    main_loop_return: int | None = None

    @property
    def has_travel_grid(self) -> bool:
        """Can this title put a party on an overland square at all?"""
        return self.travel_square is not None

    @property
    def has_exit_reentry(self) -> bool:
        """Can `#207`'s mechanism run a departing handler in this title?"""
        return None not in (self.after_step, self.forward_key, self.redraw,
                            self.saved_sp, self.main_loop_return)


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
    after_step=0x0957,
    forward_key=0x0978,
    redraw=0x0A4C,
    saved_sp=0x03BF,
    main_loop_return=0x08A6,
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


@dataclass(frozen=True)
class ExitRoute:
    """One departure a walking party can trigger directly from an area,
    reduced to what re-entering `DUNGEON`'s own dispatch needs -- `#207`.

    `entry` is which of `DUNGEON`'s two post-step dispatch points runs the
    departing handler: 1 for `after_step` (the per-square check that runs
    after every step lands, and does its own redraw first) or 0 for
    `forward_key` (the forward key in MOVE mode, reached by chaining the
    redraw in front of it so `$C04E`/`$C04F` are fresh before its own wall
    test).

    `square` is `(x, y)` for an exit entry 1 dispatches -- any square on the
    route triggers the same handler, so which one is not a functional choice
    -- or `(x, y, facing)` for one entry 0 dispatches, where `facing` is the
    direction `Geo.is_passable` confirmed open: `$10EC` never counts a step
    through a wall, so an ungated square would leave the handler's own gate
    closed.
    """

    entry: int
    square: tuple[int, int] | tuple[int, int, int]


#: `{(from_area, to_area): ExitRoute}`, Pool of Radiance only -- the only
#: title `has_exit_reentry` is true for. A pair with no row here is not
#: unreachable, only not a *direct* exit: `FastTravel` still enters `NEWECL`
#: at its tail for it, today's behaviour, unchanged. Generated by
#: `tools/genexits.py` from the game's own scripts and maps; run it again
#: (`tools/genexits.py --report work/reports/207-rows.md`) if the reading
#: this rests on -- `tools/eclexitkinds.py`'s -- ever changes.
#:
#: `tests/test_genexits.py` re-derives this off the player's own disks and
#: compares, the same shape `tests/test_newecl.py` already holds the address
#: table to.
EXIT_ROUTES: Mapping[tuple[int, int], ExitRoute] = MappingProxyType({
    (0, 8): ExitRoute(1, (4, 4)),
    (0, 11): ExitRoute(1, (6, 1)),
    (0, 21): ExitRoute(1, (15, 1)),
    (0, 26): ExitRoute(1, (15, 1)),
    (0, 27): ExitRoute(1, (15, 1)),
    (1, 25): ExitRoute(1, (7, 11)),
    (2, 18): ExitRoute(0, (4, 0, 0)),
    (7, 0): ExitRoute(1, (3, 8)),
    (7, 5): ExitRoute(0, (5, 7)),
    (9, 6): ExitRoute(1, (7, 7)),
    (13, 27): ExitRoute(1, (6, 15)),
    (14, 26): ExitRoute(0, (4, 0, 0)),
    (16, 27): ExitRoute(0, (4, 3)),
    (17, 26): ExitRoute(1, (8, 1)),
    (21, 0): ExitRoute(0, (7, 15, 2)),
    (22, 23): ExitRoute(1, (4, 10)),
    (22, 26): ExitRoute(1, (15, 15)),
    (23, 22): ExitRoute(1, (2, 11)),
    (25, 19): ExitRoute(1, (5, 2)),
    (25, 25): ExitRoute(1, (1, 0)),
    (25, 26): ExitRoute(0, (0, 0)),
    (25, 28): ExitRoute(1, (6, 3)),
    (26, 0): ExitRoute(1, (2, 6)),
    (26, 2): ExitRoute(1, (8, 14)),
    (26, 10): ExitRoute(1, (4, 3)),
    (26, 14): ExitRoute(1, (4, 3)),
    (26, 17): ExitRoute(1, (1, 2)),
    (26, 18): ExitRoute(1, (8, 14)),
    (26, 22): ExitRoute(1, (7, 1)),
    (26, 24): ExitRoute(1, (2, 6)),
    (26, 25): ExitRoute(0, (7, 11)),
    (26, 26): ExitRoute(1, (7, 1)),
    (26, 27): ExitRoute(0, (1, 2)),
    (27, 0): ExitRoute(1, (6, 2)),
    (27, 13): ExitRoute(1, (0, 2)),
    (27, 16): ExitRoute(1, (0, 0)),
    (27, 26): ExitRoute(0, (5, 12)),
    (27, 27): ExitRoute(1, (0, 0)),
    (28, 25): ExitRoute(1, (4, 0)),
})
