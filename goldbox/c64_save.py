"""Where each C64 title's saved game keeps the things a conversion writes.

`goldbox/games.py` says how big a title's save file is and where it loads;
this module says what is *inside* it -- which pages are characters, which are
items, where the names and the roster are, which header bytes a conversion
computes and which it writes as a measured zero.  A table, not a class
hierarchy, for the same reason `goldbox/games.py` is one: what differs between
the titles is a handful of numbers.

**Every offset here is a payload offset**, so the same number means the same
thing in both titles -- Pool of Radiance's save image loads at `$4900` and
Curse of the Azure Bonds' at `$4B00`, and every field anybody has looked at
sits at the same distance into the payload.  That is not a convenience: it is
the finding.  The same routine appears in both titles' `DUNGEON` with every
operand `$200` apart -- Pool of Radiance's clock tick at `$0DEC` reads
`INC $49C6,X / CMP $0E4D,X / STA $49C6,X` and Curse's at `$0D4F` reads
`INC $4BC6,X / CMP $0DB0,X / STA $4BC6,X`, instruction for instruction -- and
the two ports' `ECL` bytecode is the same bytes, so the scripts cannot name
different addresses (`#192` step 0a).

What is **not** the same is the container around those bytes.  Pool of
Radiance writes two files and keeps twelve character pages, twelve item pages
and its roster in the second file; every later title writes one file with
eight character pages, a table of the party's names where Pool of Radiance's
ninth character page would be, eight item pages, a page of map memory and the
roster at the end.

Confidence: Pool of Radiance's row and Curse of the Azure Bonds' are each
measured on that title's own engine-written saves.  Secret of the Silver
Blades' is not -- the only save of it anybody here has is the one SSI shipped
-- so its rows are read out of that title's own overlays and its `ECL`
bytecode wherever the code says anything at all, and graded where they are
made.
"""

from __future__ import annotations

import dataclasses

from . import games
from .games import Game

__all__ = [
    "Container",
    "Region",
    "POOL_OF_RADIANCE",
    "CURSE_OF_THE_AZURE_BONDS",
    "SECRET_OF_THE_SILVER_BLADES",
    "CONTAINERS",
    "container_for",
]


#: A run of payload bytes and the sentence its report line carries.
Region = tuple[int, int, str]


@dataclasses.dataclass(frozen=True)
class Container:
    """One title's saved game, as payload offsets and measured verdicts."""

    game: Game

    # -- the pages ---------------------------------------------------------
    #: Where the character slots begin, and how many pages of them the file
    #: actually has.  `party_slots` is how many a party member can occupy;
    #: `record_pages` is how many the file carries, which is more than that
    #: in Pool of Radiance because combat fills four more.
    slot_area: int = 0x400
    slot_stride: int = 0x100
    party_slots: int = 8
    record_pages: int = 12
    #: The party's names again, sixteen bytes each, or None for a title that
    #: keeps no such table.
    name_table: int | None = None
    name_stride: int = 16
    #: Which index that table is keyed by.  False -- Curse of the Azure
    #: Bonds' -- means entry *n* is the name of the character in slot *n*.
    #: True means entry *n* is the *n*th character of the marching order,
    #: which is the reverse, because the C64 fills slots from the top down.
    #: See `SECRET_OF_THE_SILVER_BLADES` below for why the two titles differ.
    names_in_marching_order: bool = False
    #: The item pages, one per slot, and how many the file carries.
    item_area: int = 0x1000
    item_pages: int = 12
    #: The combat-icon table: eight icons of 36 bytes, ending exactly where
    #: the slot area begins.
    icon_table: int = 0x2E0
    icon_size: int = 36
    #: The map the party has walked, or None for a title that keeps none in
    #: its saved game.
    map_memory: tuple[int, int] | None = None
    #: Where the roster blocks are.  An offset means "in this payload"; None
    #: means the title writes them into `game.roster_file` instead.
    roster_offset: int | None = None
    roster_stride: int = 0x20

    # -- the header --------------------------------------------------------
    #: The loaded-files cache: 25 slots, one per file kind.
    cache: tuple[int, int] = (0x2C0, 25)
    #: Does a converted save have to set bit 7 on the slots it fills?
    #:
    #: **The two titles are the reverse of each other, and getting it wrong
    #: is a save whose cache the loader reads as something else.**  Pool of
    #: Radiance ORs the bit on the *load* path -- `GEN $25DE` is
    #: `LDA $4BC0,X / ORA #$80 / STA $6E13,X` over all 25 -- so whatever a
    #: save carries is discarded and set again.  Curse ORs it on the *save*
    #: path and copies raw on load: `CAMP $0CBC` and `GEN $1F9F` are
    #: `LDA $7F13,X / ORA #$80 / STA $4DC0,X`, and `GEN $1F55` is
    #: `LDA $4DC0,X / STA $7F13,X` with no `ORA` (`#192` step 0e).
    cache_bit7: bool = False
    #: The byte the loader asks the player for a disk side by.
    disk_hint: int = 0xEA
    #: The map `LOADFILES` reloads, the script id, and the indoors flag.
    current_geo: int = 0xC5
    current_script: int = 0xF2
    indoors: int = 0xE6
    #: The party's square and facing, the travel-grid square, the six clock
    #: digits, and the quest-flag page.
    #:
    #: **The flag page ends in a different place in each title**, so this is
    #: `(offset, length)` rather than a shared constant.  Pool of Radiance's
    #: stops at `+$1F8` because `+$1FA` and `+$1FD` are its wallset and
    #: wallmap triples; Secret of the Silver Blades keeps its wall triples
    #: elsewhere and its scripts use the page to the end -- see
    #: `goldbox.dos.quest_flags`.
    position: int = 0xC0
    travel_position: int = 0xC3
    clock: int = 0xC6
    quest_flags: tuple[int, int] = (0x120, 0xD9)
    #: The switch that decides whether the character sheet draws a portrait.
    portrait_switch: int = 0xFF

    #: Header runs a conversion writes as zero, with what measured each.
    zeroed: tuple[Region, ...] = ()
    #: Header runs a conversion copies out of the DOS save, at the same
    #: distance into that title's own ECL variable array.
    copied: tuple[Region, ...] = ()

    # -- derived -----------------------------------------------------------
    @property
    def payload_size(self) -> int:
        return self.game.save_size

    @property
    def roster_in_payload(self) -> bool:
        return self.roster_offset is not None

    def slot(self, index: int) -> int:
        return self.slot_area + index * self.slot_stride

    def items(self, index: int) -> int:
        return self.item_area + index * self.slot_stride

    def icon(self, index: int) -> int:
        return self.icon_table + index * self.icon_size

    def name(self, index: int) -> int:
        if self.name_table is None:
            raise ValueError(f"{self.game.title} keeps no name table")
        return self.name_table + index * self.name_stride

    def name_index(self, slot: int, party: int) -> int:
        """Which table entry belongs to the character in `slot`.

        `party` is how many characters the party has, because a marching-order
        table is indexed from the top slot down and the top slot is
        `party - 1` -- the same arithmetic `goldbox.dos.marching_slot` does
        in the other direction.
        """
        return (party - 1 - slot) if self.names_in_marching_order else slot


#: What every entry of Pool of Radiance's zeroing list was measured by, said
#: once rather than eleven times.  All 192 bytes were written as zero in a
#: converted save that was then loaded, walked, taken into a random encounter
#: and taken through an area change in VICE (`#118`), and 48 of the 56 that
#: were unattributed before that run are zero in all 99 C64 save payloads on
#: this machine.
_POOL_ZERO = ("zero: no part of the conversion computes it, and a save with "
              "all 192 of these written as zero loaded, walked, fought and "
              "changed area (#118)")

#: And what Curse's list rests on, which is a different measurement.  Every
#: byte of the header outside the square, the clock, the eight named bytes,
#: the cache and the icon table is **zero in both engine-written Curse saves
#: on this machine** -- `work/issue32/specimens/A-no-items.D64`, taken before
#: the party had walked anywhere, and `D-curse-party-with-items.D64`, taken in
#: Tilverton after shopping.  So a zero here is the value the engine itself
#: writes rather than a value nobody has looked at.  PROBABLE: two saves of
#: one party, and `#192` step 3 is the run that loads one back.
_CURSE_ZERO = ("zero: what both engine-written Curse saves hold there, and "
               "what the same address is written as in a Pool of Radiance "
               "save that was loaded, walked and fought in (#118, #192)")

POOL_OF_RADIANCE = Container(
    game=games.POOL_OF_RADIANCE,
    zeroed=(
        (0x0C3, 2, _POOL_ZERO), (0x0CC, 26, _POOL_ZERO),
        (0x0E7, 3, _POOL_ZERO), (0x0EB, 5, _POOL_ZERO),
        (0x0F0, 2, _POOL_ZERO), (0x0F3, 9, _POOL_ZERO),
        (0x0FC, 1, _POOL_ZERO), (0x0FD, 2, _POOL_ZERO),
        (0x1F9, 135, _POOL_ZERO), (0x2D9, 7, _POOL_ZERO),
    ),
)

#: Curse of the Azure Bonds.  Four rows differ from Pool of Radiance's and
#: each has its own measurement:
#:
#: * **the disk hint is `+$EE`, not `+$EA`.**  `CAMP $0C87` is
#:   `LDA $7F12 / STA $2BE6 / STA $4BEE` on the save path and `GEN $2008` is
#:   `LDA $4BEE / STA $7F12` on the load path; `+$EE` reads 2 in all three
#:   engine-written Curse saves, whose files are on side 2, and `+$EA` reads
#:   0 in all three and is named by nothing in 411 files (`#192` step 0e).
#:   So Pool of Radiance's five-byte zeroing run from `+$EB` is split in two
#:   here, and `+$EE` is written from the area's own row.
#: * **`+$E7` and `+$E8` are copied, not zeroed.**  Four area scripts write
#:   them at their heads and `DUNGEON $1502` reads them; nobody has said what
#:   they hold, so the party's own value crosses rather than a zero.
#: * **the per-script scratch `+$100`-`+$11F` is copied.**  `DUNGEON $21BA`,
#:   the `NEWECL` handler, clears it **only when the script id changes**
#:   (`CMP $7F1B / BEQ` guarding `LDX #$1F / LDA #$00 / STA $4C00,X`), so a
#:   save taken inside an area is carrying live scratch its own script reads
#:   on the next step.  Pool of Radiance zeroes it because `DUNGEON $202A`
#:   does the same clear and its converted saves always arrive somewhere.
#: * **the party's names have a table of their own** at `+$C00`, where Pool
#:   of Radiance's ninth character page would be.  Sixteen bytes each **in
#:   slot order**: in both engine-written specimens name *n* is the name in
#:   the record at slot *n*, for six characters and for four.
CURSE_OF_THE_AZURE_BONDS = Container(
    game=games.CURSE_OF_THE_AZURE_BONDS,
    party_slots=8,
    record_pages=8,
    name_table=0xC00,
    item_pages=8,
    map_memory=(0x1800, 0x400),
    roster_offset=0x1C00,
    cache_bit7=True,
    disk_hint=0xEE,
    zeroed=(
        (0x0C3, 2, _CURSE_ZERO), (0x0CC, 26, _CURSE_ZERO),
        (0x0E9, 1, _CURSE_ZERO),
        (0x0EA, 1,
         "zero: this is Pool of Radiance's disk hint and Curse does not use "
         "it -- no absolute-mode instruction in 411 files names it, against "
         "three that name +$EE, and it reads 0 in all three engine-written "
         "Curse saves whose files are on side 2 (#192 step 0e)"),
        (0x0EB, 3, _CURSE_ZERO),
        (0x0EF, 1, _CURSE_ZERO),
        (0xC80, 0x380,
         "zero: the name table fills the first 128 bytes of its page and the "
         "rest of the page is zero in all three engine-written Curse saves"),
        (0x0F0, 2, _CURSE_ZERO), (0x0F3, 9, _CURSE_ZERO),
        (0x0FC, 1,
         "zero: the two ports disagree about it -- the DOS save holds 4 and "
         "both engine-written C64 saves hold 2 -- so it is a loader value "
         "each port keeps for itself rather than a variable the party "
         "carries, and Pool of Radiance's own zero here was loaded, walked "
         "and fought in (#118)"),
        (0x0FD, 2,
         "zero: nineteen of Curse's area scripts write +$FE and nine write "
         "+$FD from their own entry code, so the arriving script refills "
         "both (#192 step 0e)"),
        (0x1F9, 135, _CURSE_ZERO), (0x2D9, 7, _CURSE_ZERO),
    ),
    copied=(
        (0x0E7, 2,
         "from the DOS save: four area scripts write these two at their "
         "heads and DUNGEON $1502 reads them, and nobody has said what they "
         "hold -- so the party's own value crosses rather than a zero "
         "(#192 step 0e)"),
        (0x100, 0x20,
         "the per-script scratch, from the DOS save: DUNGEON $21BA clears it "
         "only when the script id changes, so a save taken inside an area is "
         "carrying live scratch its own script reads on the next step "
         "(#192 step 0a)"),
    ),
)

#: What Silver Blades' zeroing list rests on, and it is a weaker measurement
#: than either of the other two: **there is one Secret of the Silver Blades
#: save on this machine and it is the one SSI shipped on side 6**, so a zero
#: here is what that file holds rather than what an engine-written save of a
#: played party holds.  Every byte of the header outside the square, the
#: clock, the named bytes, the cache and the icon table is zero in it.  The
#: `#193` step-3 resave is what turns this into a measurement of the engine.
_SILVER_ZERO = ("zero: what the one Secret of the Silver Blades save on this "
                "machine holds there, and what the same address is written as "
                "in a Pool of Radiance save that was loaded, walked and "
                "fought in (#118, #193)")

#: Secret of the Silver Blades.  **The container is Curse of the Azure Bonds'
#: byte for byte under a different file name** -- one 7424-byte `SAVEDBASH` at
#: `$4B00`, header `$400`, eight character pages, a name table at `+$C00`,
#: eight item pages at `+$1000`, map memory at `+$1800` and the roster at
#: `+$1C00` (`tests/test_silverblades.py`).  Three rows differ from Curse's,
#: and each was read out of this title's own overlays rather than assumed:
#:
#: * **the cache bit and the disk hint are Curse's, and the code says so.**
#:   `CAMP $0CA5` is `LDX #$18 / LDA $7F13,X / ORA #$80 / STA $4DC0,X` on the
#:   save path with `LDA $4BF2 / ORA #$80 / STA $4DC8` after it, `GEN $2469`
#:   is the same loop, and `GEN $2424` is `LDA $4DC0,X / STA $7F13,X` with no
#:   `ORA` on the load path -- so a converted save must set bit 7 itself.
#:   `CAMP $0C65` is `LDA $7F12 / STA $4BEE` and `GEN $228E` is
#:   `LDA $4BEE / STA $7F12`, so `+$EE` is the disk hint here too; `+$EA` is
#:   named twice in `DUNGEON $0B0E`, which stores a table byte into it and
#:   reads it back three instructions later, so nothing in the save reaches
#:   that read.  CONFIRMED.
#: * **`+$E7`-`+$E9` and `+$FD`-`+$FE` are copied rather than zeroed.**  An
#:   address census over all 22 of this title's scripts, both ports
#:   (`tools/eclcensus.py`), gives `$4BE7` and `$4BE8` 18 writes and **no
#:   reads** over seventeen scripts, `$4BE9` 10 writes over seven, `$4BFD` 8
#:   and `$4BFE` 16.  They are per-area constants an arriving script sets, and
#:   the party's own value is in the DOS save at the same ECL address, so the
#:   conversion writes that rather than a zero nobody has measured.  Curse
#:   zeroes `+$FD`/`+$FE` and its engine put 8 and 9 back unasked, which is
#:   the same fact from the other side.
#: * **the name table may be keyed the other way round.**  In both
#:   engine-written Curse saves entry *n* is the name in slot *n*; in the
#:   shipped `SAVEDBASH` entry 0 is GUY DE VALOIS and slot 0 is MORGAINE, so
#:   the table runs in marching order and the slots run the other way.
#:   Everything else in that file is slot-ordered -- roster block *n* carries
#:   slot *n*'s armour class and hit points, six of six -- so it is the table
#:   that is reversed and not the file.  **PROBABLE, on one file that SSI
#:   shipped**; `#193` step 3 is what settles it, because a wrong order is a
#:   party whose names do not match its sheets.
SECRET_OF_THE_SILVER_BLADES = Container(
    game=games.SECRET_OF_THE_SILVER_BLADES,
    party_slots=8,
    record_pages=8,
    name_table=0xC00,
    names_in_marching_order=True,
    item_pages=8,
    map_memory=(0x1800, 0x400),
    roster_offset=0x1C00,
    cache_bit7=True,
    disk_hint=0xEE,
    quest_flags=(0x120, 0xE0),
    zeroed=(
        (0x0C3, 2, _SILVER_ZERO), (0x0CC, 26, _SILVER_ZERO),
        (0x0EA, 1,
         "zero: DUNGEON $0B0E stores a byte it has just read out of its own "
         "table here and reads it back at $0B1E, so nothing in the save "
         "reaches that read -- and Pool of Radiance's disk hint is at +$EE "
         "in this title, named by CAMP, GEN and LINKER (#193)"),
        (0x0EB, 3, _SILVER_ZERO),
        (0x0EF, 1, _SILVER_ZERO),
        (0xC80, 0x380,
         "zero: the name table fills the first 128 bytes of its page and the "
         "rest of the page is zero in the shipped save"),
        (0x0F0, 2, _SILVER_ZERO), (0x0F3, 9, _SILVER_ZERO),
        (0x0FC, 1,
         "zero: the two ports disagree about it -- all five DOS Silver "
         "Blades containers on this machine hold 4 and the shipped C64 save "
         "holds 2 -- so it is a loader value each port keeps for itself "
         "rather than a variable the party carries, and Curse's converted "
         "save booted with a zero here (#192, #193)"),
        (0x200, 128, _SILVER_ZERO), (0x2D9, 7, _SILVER_ZERO),
    ),
    copied=(
        (0x0E7, 3,
         "from the DOS save: seventeen of this title's area scripts write "
         "+$E7 and +$E8 at their heads and seven write +$E9, none of the "
         "twenty-two ever reads one, and DUNGEON does -- so the party's own "
         "value crosses rather than a zero (#193)"),
        (0x0FD, 2,
         "from the DOS save: per-area constants four scripts write into +$FD "
         "and fourteen into +$FE, read by DUNGEON and by no script (#193)"),
        (0x100, 0x20,
         "the per-script scratch, from the DOS save: the NEWECL handler "
         "clears it only when the script id changes, so a save taken inside "
         "an area is carrying live scratch its own script reads on the next "
         "step (#192 step 0a, #193)"),
    ),
)

CONTAINERS: dict[str, Container] = {
    c.game.key: c for c in (POOL_OF_RADIANCE, CURSE_OF_THE_AZURE_BONDS,
                            SECRET_OF_THE_SILVER_BLADES)}


def container_for(game=None) -> Container:
    """The container for a title, Pool of Radiance's by default.

    Takes a `goldbox.games.Game`, a key, a `Container`, or None -- the same
    shape `goldbox.spells.for_game` takes, so a caller holding any of them
    does not have to convert first.  A title with no row raises: writing a
    save for a container nobody has measured would be inventing its geometry,
    and an unrecognised key is more likely a typo than a new title.
    """
    if isinstance(game, Container):
        return game
    key = getattr(game, "key", game)
    if key is None:
        return POOL_OF_RADIANCE
    try:
        return CONTAINERS[key]
    except KeyError:
        raise KeyError(
            f"no saved-game container measured for {key!r}; "
            f"{', '.join(sorted(CONTAINERS))} are the ones this project has "
            f"read a save of") from None
