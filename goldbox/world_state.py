"""Where a party is standing and when — the world state a save carries.

**Not `goldbox/world.py`**, which is the overland travel map -- the
`SQRDATA0n` grid Pool of Radiance's wilderness is drawn from. This
module is about a *party*: its square, facing, clock, area, resident
map, quest flags and script scratch. Donald named the concept on
2026-09-07 and said the two names side by side are no trouble:
"Having world.py and world_state.py is fine. I can tell the difference."

The lift `#352 (Handle world state for Amiga saves)` asks for:
`goldbox.amiga.PorSaveState` proved the shape for a Pool of Radiance party
standing indoors, and this module is that shape generalised over every
title and every direction, so the C64 and DOS container writers no longer
have to read their source straight out of the other port's file.

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

from . import areas, c64_save, dos_savegame

__all__ = ["WorldState", "HEADER_ADDRESSES", "from_c64", "from_dos",
           "from_amiga"]


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

    Lifted from `goldbox.amiga.PorSaveState`, which held everything below
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
    #: read this when it is false, the way `goldbox.dos.HEADER_ZEROED`
    #: already does for the C64 side.
    travel: "tuple[int, int]"
    #: Has this party pressed `BEGIN ADVENTURING` at all?  False for a save
    #: made from the party-formation menu, whose `area`, `geo`, `x`, `y` and
    #: `facing` above are already the party's arrival square rather than the
    #: initialiser's world state, substituted the way the game's own first
    #: step would place it (`#301`, `#326`).
    set_out: bool
    #: The later titles' own copied header words, by address: `+$E7`-`+$E9`
    #: and `+$FD`-`+$FE` off `$4900` (`c64_save.Container.copied`,
    #: `dos.LATER_HEADER_COPIED`).  Pool of Radiance copies none of them and
    #: they are read anyway, so one shape answers for every title.
    header: "dict[int, int]"
    #: Where this was read from, for the report.
    source: str = ""


#: The later titles' own copied header words, both runs
#: `c64_save.Container.copied` and `goldbox.dos.LATER_HEADER_COPIED` name --
#: `+$E7`-`+$E9` and `+$FD`-`+$FE` off `$4900`.  Curse of the Azure Bonds
#: copies `+$E7`-`+$E8`; Secret of the Silver Blades copies all five; Pool of
#: Radiance copies none.  Read for every title regardless, so a
#: :class:`WorldState` reader never has to know which title it is building.
HEADER_ADDRESSES: "tuple[int, ...]" = (0x49E7, 0x49E8, 0x49E9, 0x49FD, 0x49FE)


def _resolve_dos_place(savgam: bytes, shape: "dos_savegame.DosSaveShape"):
    """`(area, geo, x, y, facing, outdoors, fresh)` for a DOS save.

    Generalises `goldbox.dos._where_the_party_is`, `._resident_geo` and the
    shared "has this party set out" logic `.apply_position` and
    `.apply_file_cache` each used to re-derive on their own -- one read
    rather than three functions agreeing with each other by construction.
    Raises the same `goldbox.dos.DosRecordError` either of those did, on the
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


def from_c64(save0: bytes, game=None, source: str = "") -> WorldState:
    """A C64 `SAVEDGAME0` payload, as a place and a clock.

    `SAVEDGAME0` is a memory image based at `goldbox.dos.SAVE0_BASE`, so
    every ECL address :class:`WorldState` names is one payload offset away,
    and `c64_save.container_for` says which title's own quest-flag width and
    header offsets apply.  Generalises `goldbox.amiga.por_state_from_c64`
    (now a one-line wrapper of this) beyond Pool of Radiance's own 217-byte
    flag window, and reads an outdoor party rather than refusing one.  **The
    wrapper refuses nothing either**, as it did until 2026-09-07: the two
    bytes an outdoor Amiga saved game holds were measured that day and
    `#321 (An Amiga Pool of Radiance conversion refuses a party standing on
    the travel grid, because no outdoor Amiga saved game has ever been
    read)` closed.

    There is no "has this party set out" question on the C64 side: every
    C64 save this project has read represents a party already in the
    world, so `set_out` is always true.
    """
    from . import dos_codec as _dos

    container = c64_save.container_for(game)
    base = _dos.SAVE0_BASE
    first, width = container.quest_flags
    return WorldState(
        title=container.game.title,
        area=save0[container.current_script],
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
        set_out=True,
        header={a: save0[a - base] for a in HEADER_ADDRESSES},
        source=source)


def from_dos(savgam: bytes,
            shape: "dos_savegame.DosSaveShape | int | str | None" = None,
            source: str = "") -> WorldState:
    """A DOS `SAVGAM<slot>.DAT`, as a place and a clock.

    The DOS container is the same array of the same words in the other
    endianness, so most of this is a straight read through
    `goldbox.dos_savegame` -- generalises `goldbox.amiga.por_state_from_dos`
    (now a one-line wrapper of this) over every title `save_shape_for`
    knows, rather than assuming Pool of Radiance's own flag width, and over
    a party that has never adventured, which `_resolve_dos_place` places at
    the start of the story rather than refusing.

    Reads an outdoor party rather than refusing one, because the C64 side
    already has a travel square to write it into, and
    `goldbox.amiga.por_state_from_dos` refuses nothing either -- for the
    same reason `from_c64`'s wrapper stopped, on 2026-09-07.
    """
    from . import dos_codec as _dos

    shape = dos_savegame.save_shape_for(
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
    `work/p190/C64OUT1.D64` -- the engine's own outdoor resave from
    `#190 (A C64 party standing on the travel grid cannot be written into a
    DOS save)` -- holds 5 in that slot for the same area 26 this reads 0
    for.  So this takes the same substitution `_resolve_dos_place` does.
    """
    from . import amiga_por as _amiga
    from . import c64_port
    from . import dos_codec as _dos

    area = _amiga.por_word(savgam, dos_savegame.SCRIPT)
    outdoors = not _amiga.por_word(savgam, dos_savegame.INDOORS)
    where = areas.area_in(area, c64_port.POOL_OF_RADIANCE.title)
    geo = (_dos._sqrdata_number(where.sqrdata)
           if outdoors and where is not None and where.sqrdata
           else _amiga.por_word(savgam, dos_savegame.AREA))
    return WorldState(
        title=c64_port.POOL_OF_RADIANCE.title,
        area=area,
        geo=geo,
        x=savgam[_amiga.POR_POS_X], y=savgam[_amiga.POR_POS_Y],
        facing=savgam[_amiga.POR_POS_FACING] // dos_savegame.FACING_SCALE,
        clock=tuple(_amiga.por_word(savgam, dos_savegame.CLOCK + i)
                    for i in range(dos_savegame.CLOCK_DIGITS)),
        wallset=tuple(_amiga.por_word(savgam, _amiga.POR_WALLSET + i)
                     for i in range(3)),
        flags=tuple(_amiga.por_word(savgam, dos_savegame.FLAGS_FIRST + i)
                    for i in range(c64_save.POOL_OF_RADIANCE.quest_flags[1])),
        scratch={a: _amiga.por_word(savgam, a) for a in _dos.SHARED_SCRATCH},
        outdoors=outdoors,
        travel=(_amiga.por_word(savgam, dos_savegame.TRAVEL_X),
                _amiga.por_word(savgam, dos_savegame.TRAVEL_Y)),
        set_out=True,
        header={a: _amiga.por_word(savgam, a) for a in HEADER_ADDRESSES},
        source=source)
