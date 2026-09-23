"""Where a party is standing and when — the world state a save carries.

**Not `goldbox/world.py`**, which is the overland travel map -- the
`SQRDATA0n` grid Pool of Radiance's wilderness is drawn from. This
module is about a *party*: its square, facing, clock, area, resident
map, quest flags and script scratch. Donald named the concept on
2026-09-07 and said the two names side by side are no trouble:
"Having world.py and world_state.py is fine. I can tell the difference."

The lift `#352 (Handle world state for Amiga saves)` asks for:
`goldbox.amiga_por.PorSaveState` proved the shape for a Pool of Radiance party
standing indoors, and `WorldState` is that shape generalised over the three
titles whose saved game is an array of ECL words (Pool of Radiance, Curse of
the Azure Bonds, Secret of the Silver Blades): `from_c64` and `from_dos` read
all three and `from_amiga` reads Pool of Radiance, so the C64 and DOS container
writers no longer have to read their source straight out of the other port's
file.  `PodWorldState` is the separate class for Pools of Darkness, whose saved
game is a byte-wide array.

`goldbox/neutral.py` grades a **character** field because its meaning was
measured per port and some are still guesses.  Nothing here is graded:
every address a :class:`WorldState` names is read identically by all
three engines' own save routines (`docs/165-amiga-savegame.md`,
`docs/141-dos-savegame.md`, `goldbox/c64_save.py`), which is what
`#352`'s ratifying comment on `#51 (Every permutation of DOS, C64 and
Amiga, in both directions)` (2026-09-07) calls the whole cost of the lift:
five fields `PorSaveState` lacked against what DOS <-> C64 already
converts.  So `WorldState` is a frozen dataclass and stays one -- it gets
none of `NeutralCharacter`'s `Value`/`Confidence`/`Writer.take` machinery.

**What each container holds that the other two do not never lives here.**
The C64's loaded-files cache and icon table, DOS's container byte and name
table, the Amiga's pad bytes -- every one of those comes from the area
table, a measured constant or the slot letter, never from the source save
(`#352`'s comment again).  A shape holding only what comes from the source
save loses nothing.
"""

from __future__ import annotations

import dataclasses
import struct

from . import areas, c64_save, dos_savegame

__all__ = ["WorldState", "PodWorldState", "HEADER_ADDRESSES", "from_c64",
           "from_dos", "from_amiga", "pod_from_dos"]


@dataclasses.dataclass(frozen=True)
class WorldState:
    """Where a party is standing, and when.

    The part of a saved game that belongs to the **party** rather than to
    the disk it was found on, in the ECL address space all three ports
    share -- which is why one shape serves a C64 source, a DOS one and an
    Amiga one.  Everything here is read out of the save being converted, or
    -- for a party that has never pressed `BEGIN ADVENTURING` -- substituted
    from `goldbox.areas.STARTS` the way the game's own first step would
    place it (`#301`, `#326`); nothing is a guess.

    `facing` is the C64's 0-3.  Both DOS and the Amiga store it doubled and
    both writers do the doubling, so a caller never sees the doubled form.

    Lifted from `goldbox.amiga_por.PorSaveState`, which held everything below
    but `title`, `outdoors`, `travel`, `set_out` and `header` -- the five
    fields the DOS <-> C64 pair already needed and the Amiga writer never
    had to ask for, because `#316 (Write the Amiga Pool of Radiance saved
    game from the source save, so a converted party arrives where it was
    standing)` used to refuse an outdoor party and a party that has not set
    out before either ever reached a `PorSaveState`.  **The outdoor half of
    that is over**: the two bytes nobody had seen were measured on
    2026-09-07 and `#321 (An Amiga Pool of Radiance conversion refuses a
    party standing on the travel grid, because no outdoor Amiga saved game
    has ever been read)` closed, so an outdoor Amiga party is read like any
    other.
    """

    #: The title this save belongs to, `goldbox.c64_port.C64Container.title`.
    title: str
    #: The area the party is in, indoors or out.
    area: int
    #: The resident `GEO` -- **not** the area.  The two part company for an
    #: area whose script loads no map of its own, such as the training
    #: hall, and outdoors this is the resident `SQRDATA` number instead.
    geo: int
    x: int
    y: int
    facing: int
    #: The six clock digits: sub-minute, minute units, minute tens, hour,
    #: day, month.
    clock: "tuple[int, ...]"
    #: The `WALLDEF`/`8X8D` block ids, `$FFFF` for an empty slot.
    wallset: "tuple[int, int, int]"
    #: The quest flags, one value per address in order -- 217 addresses for
    #: Pool of Radiance and 224 for Curse of the Azure Bonds and Secret of
    #: the Silver Blades (`c64_save.Container.quest_flags`).
    flags: "tuple[int, ...]"
    #: The per-script scratch, by address.
    scratch: "dict[int, int]"
    #: Is the party on the travel grid rather than indoors?
    outdoors: bool
    #: The travel-grid square.  Meaningful only when `outdoors` is true --
    #: every writer leaves the destination's travel pair zero rather than
    #: read this when it is false, the way `goldbox.dos_codec.HEADER_ZEROED`
    #: already does for the C64 side.
    travel: "tuple[int, int]"
    #: Has this party pressed `BEGIN ADVENTURING` at all?  False for a save
    #: made from the party-formation menu.  `from_c64` leaves its `area` and
    #: square as read (raw area 0); `from_dos` substitutes the arrival square
    #: the game's own first step would give it.  Writers do not look at the
    #: area: they ask `has_not_set_out`.
    set_out: bool
    #: The later titles' own copied header words, by address: `+$E7`-`+$E9`
    #: and `+$FD`-`+$FE` off `$4900` (`c64_save.Container.copied`,
    #: `dos_codec.LATER_HEADER_COPIED`).  Pool of Radiance copies none of them and
    #: they are read anyway, so one shape answers for every title.
    header: "dict[int, int]"
    #: Where this was read from, for the report.
    source: str = ""


@dataclasses.dataclass(frozen=True)
class PodWorldState:
    """Where a Pools of Darkness party is standing, and when.

    Beside :class:`WorldState` rather than inside it, because this title's
    saved game is a different structure: a 1024-byte array of one-byte ECL
    variables in place of the 5120-byte word array, a seven-digit clock, no
    wallset, no quest-flag window and no per-script scratch.  Holds the fields
    both `pod_from_dos` and `goldbox.amiga_savegame.pod_from_amiga` fill, and
    nothing derivable from `variables` -- see `clock`, `in_dungeon` and
    `wilderness_square`.

    `facing` is 0-3, as on :class:`WorldState`.  `pod_from_dos` takes it from
    `dos_savegame.position`, which divides the stored byte by
    `dos_savegame.FACING_SCALE`, and `pod_from_amiga` divides the Amiga's
    square by the same factor.

    `x` and `y` are the square `dos_savegame.position` reads.  It documents
    them as stale outdoors for Pool of Radiance; whether they go stale in this
    title's wilderness is not established.
    """

    title: str
    #: The whole variable array; variable *N* is `variables[N - 1]`.
    variables: bytes
    x: int
    y: int
    facing: int
    #: The fourth and fifth bytes of the square block.
    wall_ahead: int
    square_property: int
    #: The interface mode before the current one, and the current one
    #: (`dos_savegame.POD_MODE_WILDERNESS`, `POD_MODE_DUNGEON`, 2 in camp).
    previous_mode: int
    mode: int
    #: The two words the dungeon loader passes to `LoadMap`.
    dungeon_map: int
    map_block: int
    #: The party size byte that ends the square block.
    count: int
    #: Where this was read from, for the report.
    source: str = ""

    @property
    def clock(self) -> "tuple[int, ...]":
        """The seven clock digits, in `dos_savegame.POD_CLOCK_RADIX` order."""
        first = dos_savegame.POD_CLOCK - dos_savegame.POD_VAR_FIRST
        return tuple(self.variables[first + i]
                     for i in range(dos_savegame.POD_CLOCK_DIGITS))

    @property
    def in_dungeon(self) -> bool:
        """Is the party in a dungeon rather than the wilderness?"""
        return self.variables[
            dos_savegame.POD_IN_DUNGEON - dos_savegame.POD_VAR_FIRST] != 0

    @property
    def wilderness_square(self) -> "tuple[int, int]":
        """The overland square.  Stale while `in_dungeon` is true: the pair is
        left at the last wilderness square rather than cleared."""
        first = dos_savegame.POD_VAR_FIRST
        return (self.variables[dos_savegame.POD_WILDERNESS_X - first],
                self.variables[dos_savegame.POD_WILDERNESS_Y - first])


#: The later titles' own copied header words, both runs
#: `c64_save.Container.copied` and `goldbox.dos_codec.LATER_HEADER_COPIED` name --
#: `+$E7`-`+$E9` and `+$FD`-`+$FE` off `$4900`.  Curse of the Azure Bonds
#: copies `+$E7`-`+$E8`; Secret of the Silver Blades copies all five; Pool of
#: Radiance copies none.  Read for every title regardless, so a
#: :class:`WorldState` reader never has to know which title it is building.
HEADER_ADDRESSES: "tuple[int, ...]" = (0x49E7, 0x49E8, 0x49E9, 0x49FD, 0x49FE)


def _resolve_dos_place(savgam: bytes, shape: "dos_savegame.DosContainer"):
    """`(area, geo, x, y, facing, outdoors, fresh)` for a DOS save.

    Generalises `goldbox.dos_codec._where_the_party_is`, `._resident_geo` and the
    shared "has this party set out" logic `.apply_position` and
    `.apply_file_cache` each used to re-derive on their own -- one read
    rather than three functions agreeing with each other by construction.
    Raises the same `goldbox.dos_codec.DosRecordError` either of those did, on the
    same two contradictions: an area no row of this title names, and a
    save whose own indoors byte disagrees with its area's row.
    """
    from . import dos_codec as _dos

    where, fresh = _dos._where_the_party_is(savgam, shape.title, shape)
    if fresh:
        start, _row = _dos._start_of_the_story(shape.title)
        x, y, facing = (start.arrival.x, start.arrival.y,
                        start.arrival.facing or 0)
    else:
        x, y, facing = dos_savegame.position(savgam, shape)

    savgam_outdoors = where.outdoors if fresh else dos_savegame.outdoors(savgam)
    if savgam_outdoors != where.outdoors:
        raise _dos.DosRecordError(
            f"the save's own $49E6 says "
            f"{'outdoors' if savgam_outdoors else 'indoors'}, but script id "
            f"{where.id} ({where.name or where.ecl}) is marked "
            f"{'outdoors' if where.outdoors else 'indoors'} in "
            "goldbox/areas.py -- these two disagree and neither is trusted "
            "over the other")

    if where.outdoors:
        geo = _dos._sqrdata_number(where.sqrdata)
    elif fresh:
        geo = areas.geo_number(where.geo)
    else:
        geo = _dos._resident_geo(savgam, where, shape.title)

    return where.id, geo, x, y, facing, where.outdoors, fresh


def is_pre_adventure_area(title: str, area: int) -> bool:
    """Whether `area` is the placeless state a Curse or Silver Blades party
    is in before `BEGIN ADVENTURING`.

    Raw area 0 there, where no row of the title's area table names it.  Pool
    of Radiance's area 0 is New Phlan, so it is never this.
    """
    return (area == 0
            and title in (areas.CURSE_OF_THE_AZURE_BONDS,
                          areas.SECRET_OF_THE_SILVER_BLADES)
            and areas.area_in(0, title) is None)


def has_not_set_out(state: "WorldState") -> bool:
    """Whether a Curse or Silver Blades party is still in the placeless state
    before `BEGIN ADVENTURING`."""
    return (not state.set_out
            and state.title in (areas.CURSE_OF_THE_AZURE_BONDS,
                                areas.SECRET_OF_THE_SILVER_BLADES))


def from_c64(save0: bytes, game=None, source: str = "") -> WorldState:
    """A C64 `SAVEDGAME0` payload, as a place and a clock.

    `SAVEDGAME0` is a memory image based at `goldbox.dos_codec.SAVE0_BASE`, so
    every ECL address :class:`WorldState` names is one payload offset away,
    and `c64_save.container_for` says which title's own quest-flag width and
    header offsets apply.  Generalises `goldbox.amiga_por.por_state_from_c64`
    (now a one-line wrapper of this) beyond Pool of Radiance's own 217-byte
    flag window, and reads an outdoor party rather than refusing one.  **The
    wrapper refuses nothing either**, as it did until 2026-09-07: the two
    bytes an outdoor Amiga saved game holds were measured that day and
    `#321 (An Amiga Pool of Radiance conversion refuses a party standing on
    the travel grid, because no outdoor Amiga saved game has ever been
    read)` closed.

    `set_out` is false only for a Curse or Silver Blades save whose area is
    the raw 0 no row of either title's area table names -- the party menu's
    own SAVE CURRENT GAME, made before `BEGIN ADVENTURING`.  `area`, `geo`
    and the square stay as the payload holds them, because that state has
    no place: a writer that needs the first real area takes it from
    `goldbox.areas.STARTS`.  Pool of Radiance's area 0 is New Phlan, a real
    place, so its `set_out` is always true.
    """
    from . import dos_codec as _dos

    container = c64_save.container_for(game)
    base = _dos.SAVE0_BASE
    first, width = container.quest_flags
    area = save0[container.current_script]
    return WorldState(
        title=container.game.title,
        area=area,
        geo=save0[container.current_geo],
        x=save0[container.position],
        y=save0[container.position + 1],
        facing=save0[container.position + 2],
        clock=tuple(save0[container.clock + i]
                    for i in range(dos_savegame.CLOCK_DIGITS)),
        wallset=_dos.c64_wall_triple(save0, container),
        flags=tuple(save0[first + i] for i in range(width)),
        scratch={a: save0[a - base] for a in _dos.SHARED_SCRATCH},
        outdoors=not save0[container.indoors],
        travel=(save0[container.travel_position],
                save0[container.travel_position + 1]),
        set_out=not is_pre_adventure_area(container.game.title, area),
        header={a: save0[a - base] for a in HEADER_ADDRESSES},
        source=source)


def from_dos(savgam: bytes,
            shape: "dos_savegame.DosContainer | int | str | None" = None,
            source: str = "") -> WorldState:
    """A DOS `SAVGAM<slot>.DAT`, as a place and a clock.

    The DOS container is the same array of the same words in the other
    endianness, so most of this is a straight read through
    `goldbox.dos_savegame` -- generalises `goldbox.amiga_por.por_state_from_dos`
    (now a one-line wrapper of this) over every title `container_for`
    knows, rather than assuming Pool of Radiance's own flag width, and over
    a party that has never adventured, which `_resolve_dos_place` places at
    the start of the story rather than refusing.

    Reads an outdoor party rather than refusing one, because the C64 side
    already has a travel square to write it into, and
    `goldbox.amiga_por.por_state_from_dos` refuses nothing either -- for the
    same reason `from_c64`'s wrapper stopped, on 2026-09-07.
    """
    from . import dos_codec as _dos

    shape = dos_savegame.container_for(
        shape if shape is not None else len(savgam))
    area_id, geo, x, y, facing, outdoors, fresh = _resolve_dos_place(
        savgam, shape)
    width = c64_save.container_for(shape.key).quest_flags[1]
    return WorldState(
        title=shape.title,
        area=area_id, geo=geo, x=x, y=y, facing=facing,
        clock=tuple(dos_savegame.word(savgam, dos_savegame.CLOCK + i, shape)
                    for i in range(dos_savegame.CLOCK_DIGITS)),
        wallset=dos_savegame.wall_triple(savgam),
        flags=tuple(dos_savegame.word(savgam, dos_savegame.FLAGS_FIRST + i,
                                      shape)
                    for i in range(width)),
        scratch={a: dos_savegame.word(savgam, a, shape)
                 for a in _dos.SHARED_SCRATCH},
        outdoors=outdoors,
        travel=dos_savegame.travel_square(savgam),
        set_out=not fresh,
        header={a: dos_savegame.word(savgam, a, shape)
                for a in HEADER_ADDRESSES},
        source=source)


def from_amiga(savgam: bytes, source: str = "") -> WorldState:
    """An Amiga `savgam<letter>.dat`, as a place and a clock.

    Pool of Radiance is the only Amiga container this project reads a party
    out of, so `title` is always its own and `header` is read but empty of
    meaning -- Pool of Radiance's own `c64_save.Container.copied` is empty.
    Generalises `goldbox.amiga_por.por_state_from_amiga`, which is now a
    one-line wrapper that checks the file length and nothing else -- it
    refused an outdoor save until 2026-09-07, when the two bytes one holds
    were measured and `#321 (An Amiga Pool of Radiance conversion refuses a
    party standing on the travel grid, because no outdoor Amiga saved game
    has ever been read)` closed.  There is no "has this party
    set out" question read off an Amiga file either -- every Amiga save
    read is a party in the world -- so `set_out` is always true, as on the
    C64 side.

    **`geo` is not the raw file word when the party is outdoors.**  Two
    engine-written outdoor Amiga saves hold 0 at the word `_resident_geo`
    reads indoors (`#321 (An Amiga Pool of Radiance conversion refuses a
    party standing on the travel grid, because no outdoor Amiga saved game
    has ever been read)`), and `_resolve_dos_place` already knows the same
    is true of a DOS source and substitutes the area table's own `sqrdata`
    number rather than trust it.  Reading the raw 0 through here instead
    writes a C64 loaded-files cache with no `SQRDATA` slot filled in --
    `#376 (An Amiga party on the travel grid still cannot be converted to
    the C64 or DOS, because the reader refuses one)`: the game accepted the
    disk, drew the roster, and never reached a world to show, and
    `p190/C64OUT1.D64` (scratch, deleted) -- the engine's own outdoor resave from
    `#190 (A C64 party standing on the travel grid cannot be written into a
    DOS save)` -- holds 5 in that slot for the same area 26 this reads 0
    for.  So this takes the same substitution `_resolve_dos_place` does.
    """
    from . import amiga_savegame as _amiga
    from . import c64_port
    from . import dos_codec as _dos

    area = _amiga.word(savgam, dos_savegame.SCRIPT)
    outdoors = not _amiga.word(savgam, dos_savegame.INDOORS)
    where = areas.area_in(area, c64_port.POOL_OF_RADIANCE.title)
    geo = (_dos._sqrdata_number(where.sqrdata)
           if outdoors and where is not None and where.sqrdata
           else _amiga.word(savgam, dos_savegame.AREA))
    return WorldState(
        title=c64_port.POOL_OF_RADIANCE.title,
        area=area,
        geo=geo,
        x=savgam[_amiga.POR_POSITION[0]], y=savgam[_amiga.POR_POSITION[1]],
        facing=savgam[_amiga.POR_POSITION[2]] // dos_savegame.FACING_SCALE,
        clock=tuple(_amiga.word(savgam, dos_savegame.CLOCK + i)
                    for i in range(dos_savegame.CLOCK_DIGITS)),
        wallset=tuple(_amiga.word(savgam, _amiga.POR_WALLSET + i)
                     for i in range(3)),
        flags=tuple(_amiga.word(savgam, dos_savegame.FLAGS_FIRST + i)
                    for i in range(c64_save.POOL_OF_RADIANCE.quest_flags[1])),
        scratch={a: _amiga.word(savgam, a) for a in _dos.SHARED_SCRATCH},
        outdoors=outdoors,
        travel=(_amiga.word(savgam, dos_savegame.TRAVEL_X),
                _amiga.word(savgam, dos_savegame.TRAVEL_Y)),
        set_out=True,
        header={a: _amiga.word(savgam, a) for a in HEADER_ADDRESSES},
        source=source)


def pod_from_dos(savgam: bytes,
                 shape: "dos_savegame.DosContainer | int | str | None" = None,
                 source: str = "") -> PodWorldState:
    """A Pools of Darkness `SAVGAM<slot>.PTY`, as a place and a clock.

    Reads through `goldbox.dos_savegame`, so a buffer that is not the
    container's size is refused there.  A container with no byte-wide variable
    array, which is every title but this one, raises.  `WorldState.from_dos`
    is the reader for those and still refuses this title's file.

    **The size names the container, not the title**: a Treasures of the Savage
    Frontier `SAVGAM<slot>.PTY` is also 1364 bytes and `dos_savegame.container_for`
    answers it with this row, so `title` reads "Pools of Darkness" for it too;
    `source` is what says which game the file came from.
    """
    shape = dos_savegame.container_for(
        shape if shape is not None else len(savgam))
    if not shape.var_bytes:
        raise dos_savegame.DosSaveError(
            f"a {shape.title} saved game holds no byte-wide variable array")
    x, y, facing = dos_savegame.position(savgam, shape)
    return PodWorldState(
        title=shape.title,
        variables=bytes(savgam[:shape.var_bytes]),
        x=x, y=y, facing=facing,
        wall_ahead=savgam[shape.tail_scratch],
        square_property=savgam[shape.tail_scratch + 1],
        previous_mode=savgam[shape.previous_mode],
        mode=savgam[shape.mode],
        dungeon_map=struct.unpack_from(
            "<H", savgam, dos_savegame.POD_MAP)[0],
        map_block=struct.unpack_from(
            "<H", savgam, dos_savegame.POD_MAP_BLOCK)[0],
        count=savgam[shape.party_size_byte],
        source=source)
