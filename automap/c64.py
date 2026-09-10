"""A running Commodore 64, as the addresses one title keeps things at.

`AmigaMachine` in `automap/amiga.py` is the same idea for the other machine,
and this file is deliberately its mirror: one frozen row per title, a registry
keyed by title key, and a title with no measurement refused rather than handed
another title's numbers.

**What a machine is, and what it is not.** A `C64Machine` answers "where is
this, right now, in a running game" -- the engine's live party square, the
loader's dispatch byte, and the live address of each region the save image
occupies while the game holds it in memory. It is not a save file: that is
`goldbox.c64_save.Container`, which holds the same regions as *payload
offsets*, and the machine is those offsets plus the address the payload loads
at. It is not the title's rules either: those are `goldbox.titles.Title`, which
every machine here carries by reference.

**Three of the six titles' live addresses have never been measured, and that
is a fact rather than a gap to paper over.** Champions of Krynn, Death Knights of
Krynn and Gateway to the Savage Frontier have no `live_position` and no
`mode_flag`, because nobody has run them under a monitor. Both stay None, and
every caller refuses on None instead of reading Pool of Radiance's address and
believing what it finds there -- `automap.actions.mode` is the one that matters,
since an unmeasured mode flag reads as "not combat" whatever the machine is
doing, which is a gate that is open rather than a gate that is missing.

Built for `#470 (Give the project a neutral title beside its neutral character
record, with one port per platform a title shipped on)`, stage 6.

**Nothing here has an alias back on `goldbox.c64_port.Game`, and that is
forced rather than chosen.** Every other rename in that ticket leaves the old
name working; a read-through for `live_position` or `mode_flag` would import
`automap` from inside `goldbox`, and
`tests/test_wish.py::test_goldbox_imports_no_transport` forbids that -- it is
what keeps `editor/`'s promise that it never talks to an emulator. So the
callers moved in the same commit instead. What `Game` does keep is
`travel_grid`, which reads through to `Title`, and the save-image `_base`
properties, which `goldbox/savegame.py` needs and stage 7 folds into
`C64Container`; `tests/test_c64machine.py` pins that those agree with this
module's for all six titles.
"""

from __future__ import annotations

from dataclasses import dataclass

from goldbox import c64_port, c64_save, titles
from goldbox.titles import Title

#: Where the **engine** keeps the party's square while the game runs, which is
#: not where it writes it when the game saves. `$C04B` x, `$C04C` y, `$C04D`
#: facing.
#:
#: MEASURED, three times over, and not inferred from anything:
#:
#: * Pool of Radiance -- `$1A3C` is `if $49E6 then copy $C04B..$C04D into
#:   $49C0..$49C2`, and 29 of its 30 area scripts write it (`docs/118` §);
#: * Curse of the Azure Bonds -- found by intersecting two 64K dumps taken
#:   either side of a step, one candidate left (`docs/120` §4);
#: * Secret of the Silver Blades -- the same triple, confirmed unchanged over
#:   nine steps and three refusals (`docs/121` §5).
#:
#: `docs/138-multiple-games.md` records it as CONFIRMED for those three titles
#: and for no others, which is why the Krynn titles and Gateway leave
#: `live_position` None below.
LIVE_POSITION_GOLDBOX = 0xC04B

#: `LINKER`'s dispatch byte in Pool of Radiance: which overlay is running, and
#: `2` is COMBAT. Outside the save image like `live_position`, and like it a
#: measurement of one title rather than a family constant -- `LINKER` is
#: 136 bytes of resident code at `$2B80`.
#:
#: CONFIRMED: "`$6E11` is the mode flag" in `docs/50-experiments.md` reads the
#: outer loop itself -- `LDA $6E11`, index the overlay name table, load it at
#: `$0800`, call it.
MODE_FLAG_POOL = 0x6E11

#: The same byte in Curse of the Azure Bonds and Secret of the Silver Blades,
#: and it is **not** Pool of Radiance's plus anything the save image moved by:
#: `LINKER` is its own resident, so the flag went `$6E11` -> `$7F11` while the
#: save image went `$4900` -> `$4B00`.
#:
#: Read out of the loader's own first instruction, which is where the address
#: is an absolute operand and so does not depend on where `LINKER` loads:
#: `LINKER` on `CURSE_A.D64` and on `SILVER-1.D64` both begin `AD 11 7F`,
#: `LDA $7F11`, then index a name table of ten entries and `JSR $0800`. **The
#: name table is Pool of Radiance's, entry for entry** -- `GEN`, `DUNGEON`,
#: `COMBAT`, `INIT`, `COM.PREP`, `POST.COM`, two dead slots, `FINAL`, `CAMP` --
#: so `2` is COMBAT in all three titles and `automap.actions.COMBAT` needs no
#: per-title value.
#:
#: CONFIRMED for both, each in its own driven session on pool slot 2. `LINKER`
#: is resident at `$2D00` in both -- byte-identical to the disk copy -- and the
#: flag was sampled across every overlay change the session made: Curse world
#: `1`, camp `9`, world `1`, roster `0`, world `1`; Silver Blades credits `3`
#: `INIT`, roster `0` `GEN`, world `1`, treasure `5` `POST.COM`, world `1`.
#: `LDA #$09 / STA $7F11` sits at `$100E` in Curse's resident `DUNGEON`, where
#: Pool of Radiance's `DUNGEON $10B1` writes `9`.
#:
#: **`2` was sampled live on Silver Blades**, at the end of 228 driven steps:
#: `1` -> `4` `COM.PREP` -> `2` with `MOVE VIEW AIM TURN QUICK DONE` on the
#: command bar, and `identify` refusing because `$7F11` is 2. That is also the
#: first live sighting of `4` in any title. On Curse it was not: no session has
#: reached a fight there, so `2` rests on the dispatch table alone -- which is
#: the same table, so the risk is small and it is written down rather than
#: glossed. `docs/50-experiments.md`, "the later titles' mode flag is `$7F11`";
#: issue #29.
MODE_FLAG_LATER = 0x7F11


@dataclass(frozen=True)
class C64Machine:
    """One title's running game, as live addresses.

    `title` is the title's own rules; `container` is its saved game as payload
    offsets, and is None for the three titles whose saves nobody here has ever
    read. Every `_base` property below is a payload offset raised to a live
    address by `save_load_address`, and it takes the offset from `container`
    where there is one so that the machine and the file cannot come to
    disagree about where a region sits.

    **`live_position` and `mode_flag` are the two that are not geometry.**
    Neither is inside the save image, so neither follows `save_load_address`
    and neither transfers between titles; None means nobody has measured this
    title's, and a caller must refuse rather than fall back, because a wrong
    address yields a plausible answer instead of an error.
    """

    title: Title
    container: c64_save.Container | None

    #: Where the payload loads. **Stage 7's**, not this stage's: it is disk
    #: geometry, and it is here only because `Container` cannot supply it for
    #: the three titles that have no `Container` row. When `C64Container`
    #: absorbs what is left of `Game`, these three fields read through it.
    save_load_address: int
    #: Pool of Radiance keeps its roster in a second file at `$8300`; every
    #: later title folds it into the payload's last page, so this is that
    #: title's own `save_load_address` and the offset is `$1C00`.
    roster_load_address: int
    roster_offset: int = 0

    live_position: int | None = None
    mode_flag: int | None = None

    # -- the save image, live ---------------------------------------------
    @property
    def slot_area_base(self) -> int:
        """The first character slot."""
        c = self.container
        return self.save_load_address + (c.slot_area if c else
                                         c64_port.HEADER_SIZE)

    @property
    def item_area_base(self) -> int:
        """The first character's item page."""
        c = self.container
        return self.save_load_address + (c.item_area if c else
                                         c64_port.ITEM_AREA_OFFSET)

    @property
    def icon_table_base(self) -> int:
        """The eight combat icons."""
        c = self.container
        return self.save_load_address + (c.icon_table if c else
                                         c64_port.ICON_TABLE_OFFSET)

    @property
    def save_position_base(self) -> int:
        """The save image's own copy of the party square.

        Refreshed only when the game saves, so it names the square the party
        stood on at the last save. `live_position` is the one that moves.
        """
        c = self.container
        return self.save_load_address + (c.position if c else
                                         c64_port.POSITION_OFFSET)

    @property
    def shown_clock_base(self) -> int:
        """The three clock digits the status line draws: units, tens, hour.

        **Not the whole clock.** The engine keeps six one-byte digits from
        `container.clock`, `+$C6`, and the first of them is a sub-minute tick
        nothing ever prints; the status line reads `+$C7`, `+$C8`, `+$C9` and
        `automap.target` folds them as `c[2] * 60 + c[1] * 10 + c[0]`, which
        at `+$C6` would be minute tens times sixty and nonsense. The two
        constants sat a byte apart with no explanation until the tick loop was
        read in all three titles -- `tools/c64clock.py`, and
        `docs/30-savegame-layout.md`.
        """
        return self.save_load_address + c64_port.SHOWN_CLOCK_OFFSET

    @property
    def indoors_flag_base(self) -> int | None:
        """`$49E6`: zero on the travel grid, non-zero in a `GEO` area.

        None unless the title has a travel grid, the same refusal
        `live_position` makes for the same reason: reading this on a title
        with no square-engine overland would answer a byte of unrelated
        resident code as though it meant something.
        """
        if not self.title.travel_grid:
            return None
        c = self.container
        return self.save_load_address + (c.indoors if c else
                                         c64_port.INDOORS_FLAG_OFFSET)

    @property
    def travel_position_base(self) -> int | None:
        """`$49C3`/`$49C4`: the window-local travel-grid square, x then y.

        None unless the title has a travel grid, for the same reason as
        `indoors_flag_base`.
        """
        if not self.title.travel_grid:
            return None
        c = self.container
        return self.save_load_address + (c.travel_position if c else
                                         c64_port.TRAVEL_POSITION_OFFSET)

    @property
    def roster_base(self) -> int:
        """The roster's live address, wherever it lives."""
        return self.roster_load_address + self.roster_offset


def _machine(game: c64_port.Game, *, live_position: int | None = None,
             mode_flag: int | None = None) -> C64Machine:
    """One row, taking its disk geometry from the `Game` it belongs to.

    Read rather than retyped, so this stage moves the two live addresses and
    copies no number that already exists somewhere else. A title `titles.py`
    does not know gets a `Title` of its own with no tables in it -- `None`
    races mean "we do not know", which is what a `Game` built outside the
    registry already meant.
    """
    title = titles.BY_KEY.get(game.key) or Title(key=game.key,
                                                 title=game.title)
    return C64Machine(
        title=title,
        container=c64_save.CONTAINERS.get(game.key),
        save_load_address=game.save_load_address,
        roster_load_address=(game.save_load_address if game.roster_file is None
                             else game.roster_load_address),
        roster_offset=game.roster_offset,
        live_position=live_position,
        mode_flag=mode_flag,
    )


#: One row per C64 title, keyed the way `goldbox.titles.BY_KEY` is.
#:
#: The last three carry neither live address: nobody has run those titles under
#: the monitor, and `$C04B` and `$6E11` are measurements of other games rather
#: than family constants. `tests/test_pertitle_live.py` pins that they answer
#: None, because a title quietly acquiring somebody else's address is the
#: defect this whole table exists to prevent (`#29`).
MACHINES: dict[str, C64Machine] = {
    "pool-of-radiance": _machine(
        c64_port.POOL_OF_RADIANCE,
        live_position=LIVE_POSITION_GOLDBOX, mode_flag=MODE_FLAG_POOL),
    "curse-of-the-azure-bonds": _machine(
        c64_port.CURSE_OF_THE_AZURE_BONDS,
        live_position=LIVE_POSITION_GOLDBOX, mode_flag=MODE_FLAG_LATER),
    "secret-of-the-silver-blades": _machine(
        c64_port.SECRET_OF_THE_SILVER_BLADES,
        live_position=LIVE_POSITION_GOLDBOX, mode_flag=MODE_FLAG_LATER),
    "champions-of-krynn": _machine(c64_port.CHAMPIONS_OF_KRYNN),
    "death-knights-of-krynn": _machine(c64_port.DEATH_KNIGHTS_OF_KRYNN),
    "gateway-to-the-savage-frontier": _machine(
        c64_port.GATEWAY_TO_THE_SAVAGE_FRONTIER),
}

#: What a caller gets when it names no title. Pool of Radiance, because every
#: caller that names none predates the table and means it -- the same default
#: `goldbox.c64_port.DEFAULT` is.
DEFAULT = MACHINES[c64_port.DEFAULT.key]


def machine_for(game=None) -> C64Machine:
    """The machine for a title: a `Game`, a `Title`, a key, or None.

    Takes the same shapes `goldbox.c64_save.container_for` does, so a caller
    holding any of them does not have to convert first. None is Pool of
    Radiance's, matching every caller's own `game or games.DEFAULT`.

    **A `Game` outside the registry is built rather than refused**, because its
    geometry is on the row and its live addresses are simply unmeasured -- so
    it answers the addresses it always did and None for the two that have to be
    measured. A bare key nobody knows raises, since that is a typo rather than
    a title.
    """
    if isinstance(game, C64Machine):
        return game
    if game is None:
        return DEFAULT
    key = getattr(game, "key", game)
    found = MACHINES.get(key)
    if found is not None:
        return found
    if isinstance(game, c64_port.Game):
        return _machine(game)
    raise KeyError(
        f"no C64 machine for {key!r}; "
        f"{', '.join(sorted(MACHINES))} are the titles this project knows")
