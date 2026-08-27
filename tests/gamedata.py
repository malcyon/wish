"""Game data comes from the player's own disks, never from this repository.

`CLAUDE.md` forbids committing the game's code, art or data files, and a test
fixture is not an exception -- a slice of `GEO04` in `tests/fixtures/` is the
same copy the rule forbids, merely renamed. So the tests that need real game
data read it off the player's disks at run time and skip when there are none.

That is a real cost: a bare checkout on a machine without the game verifies
less. It is the right cost. Where a test only needs *a* well-formed file rather
than a specific one, prefer `synthetic_geo` below, which is generated from the
format we documented and belongs to us.

Saved games are different and stay in `tests/fixtures/`: they are the player's
own data, produced by playing, and several of them capture states that no disk
still holds.
"""

from __future__ import annotations

import functools
import os
import pathlib

import pytest

from automap.paths import find_disks
from goldbox.d64 import D64, load_payload
from goldbox.geo import (
    ATTRIBUTES,
    BARRIERS,
    GRID,
    PASSABLE,
    SOLID,
    WALLS_NORTH_EAST,
    WALLS_SOUTH_WEST,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@functools.lru_cache(maxsize=1)
def disk_dir():
    """Where the player keeps their disks, or None."""
    return find_disks()


@functools.lru_cache(maxsize=None)
def _read(disk: str, name: bytes) -> bytes | None:
    try:
        return load_payload(disk, name)
    except Exception:
        return None


def game_file(name: str) -> bytes:
    """One file off whichever `POOL*.D64` carries it.

    Skips rather than fails when the disks are absent: not owning the game is
    not a broken checkout.
    """
    where = disk_dir()
    if where is None:
        pytest.skip("needs the game disks; set POR_DISKS to where they are")
    encoded = name.encode() if isinstance(name, str) else name
    for disk in sorted(where.glob("POOL*.[dD]64")):
        payload = _read(str(disk), encoded)
        if payload is not None:
            return payload
    pytest.skip(f"no POOL disk here carries {name}")


needs_disks = pytest.mark.skipif(disk_dir() is None,
                                 reason="needs the game disks")


# --- the second game ---------------------------------------------------------
# Curse of the Azure Bonds shares this project's decoders (docs/116). The tests
# that check it must not break when the disks are absent, and must not read
# anything out of the repository, so they look for the disks the same way the
# Pool of Radiance ones are found -- with `work/` added, because `CLAUDE.md`
# already names that as where disk images belong.

CURSE_ENV = "COAB_DISKS"
_REPO = pathlib.Path(__file__).resolve().parent.parent


def _curse_candidates():
    env = os.environ.get(CURSE_ENV)
    if env:
        return [pathlib.Path(env)]
    home = pathlib.Path.home()
    names = ("Curse of the Azure Bonds Disks", "Curse of the Azure Bonds",
             "CoAB", "Azure Bonds")
    roots = [pathlib.Path.cwd(), home, home / "Documents", home / "Games",
             home / "c64", home / "roms", home / "Downloads"]
    out = [r / n for r in roots for n in names]
    out += [_REPO / "work" / "curse", _REPO / "work" / "coab-research" / "disks"]
    return out


@functools.lru_cache(maxsize=1)
def curse_dir():
    """Where the player keeps their Curse of the Azure Bonds disks, or None."""
    for path in _curse_candidates():
        try:
            if path.is_dir() and (any(path.glob("CURSE*.D64"))
                                  or any(path.glob("CURSE*.d64"))):
                return path
        except OSError:
            continue
    return None


def curse_disks(engine_only: bool = True):
    """Every readable Curse side, skipping when there are none.

    One of the three published rips carries error bytes and is 175531 bytes,
    which `goldbox.d64` refuses; that side is simply skipped rather than failed.

    `engine_only` keeps the default to game sides, because a save disk matches
    the glob too and carries its own `SAVEAZURE`. Pass False to reach the save
    disks -- the player's exported characters live only there.
    """
    where = curse_dir()
    if where is None:
        pytest.skip(f"needs the Curse disks; set {CURSE_ENV} to where they are")
    out = []
    for path in sorted(where.glob("CURSE*.[dD]64")):
        try:
            disk = D64.open(path)
        except Exception:
            continue
        if engine_only and not any(
                e.name.startswith(b"GEO") or e.name == b"ITEMNAMES"
                for e in disk.directory()):
            continue
        out.append(disk)
    if not out:
        pytest.skip("no readable Curse game disk here")
    return out


def curse_file(name: str, engine_only: bool = True) -> bytes:
    """One file off whichever Curse side carries it, longest copy first.

    The sides disagree, and not only by duplication: `SAVEAZURE` is the full
    7424-byte pre-generated party on side B3 and a 2030-byte truncated demo
    party of the same name on side A2. Taking the first match gets the wrong
    one, so take the biggest.

    **Size comes from following the sector chain, never from the directory's
    block count.** This skipped any entry whose count was zero, and Curse writes
    exactly that for a character it exports: `\x02BRUTUS` on the save disk
    reports 0 blocks and reads back 582 bytes from an intact chain. The same
    defect hides a whole title -- every file on all six Death Knights of Krynn
    sides reports 0, because that release's directory was rewritten by the
    cracker (`work/reports/goldbox-inventory.md`). The chain is the file; the
    count is a claim about it.
    """
    encoded = name.encode() if isinstance(name, str) else name
    best = None
    for disk in curse_disks(engine_only=engine_only):
        entry = disk.find(encoded)
        if entry is None:
            continue
        try:
            data = disk.read_file(entry)
        except Exception:
            continue                      # a broken chain is not a candidate
        if best is None or len(data) > len(best):
            best = data
    if best is None:
        pytest.skip(f"no Curse disk here carries {name}")
    return best


def curse_exports():
    """Every exported Curse character on the player's disks, by file name.

    Curse marks an export with a leading `\x02` where Pool of Radiance uses
    `\x01`, and writes a 582-byte PRG: the 580-byte record behind its `$7C00`
    load address. These live on save disks, so this looks at every side.
    """
    out = {}
    for disk in curse_disks(engine_only=False):
        for entry in disk.directory():
            if not bytes(entry.name).startswith(b"\x02"):
                continue
            try:
                data = disk.read_file(entry)
            except Exception:
                continue
            if len(data) == 582:
                out[bytes(entry.name)] = data
    return out


needs_curse_disks = pytest.mark.skipif(curse_dir() is None,
                                       reason="needs the Curse disks")


def synthetic_geo() -> bytes:
    """A GEO built from the format, not copied from one.

    Four 256-byte planes over a 16x16 grid. Enough structure to exercise the
    decoder without the repository holding a map somebody drew: a walled border,
    one interior room with a door in it, and one edge carrying wall art with no
    barrier, which is the case that separates art from passability.
    """
    planes = bytearray(4 * 0x100)

    def square(x: int, y: int) -> int:
        return y * GRID + x

    def set_wall(x, y, north=None, east=None, south=None, west=None):
        """North and south are the HIGH nibble of their byte, east and west the
        low one -- `Geo.wall` is the authority and this mirrors it exactly."""
        at = square(x, y)
        if north is not None:
            planes[WALLS_NORTH_EAST + at] |= (north & 0x0F) << 4
        if east is not None:
            planes[WALLS_NORTH_EAST + at] |= east & 0x0F
        if south is not None:
            planes[WALLS_SOUTH_WEST + at] |= (south & 0x0F) << 4
        if west is not None:
            planes[WALLS_SOUTH_WEST + at] |= west & 0x0F

    def set_barrier(x, y, north=SOLID, east=SOLID, south=SOLID, west=SOLID):
        """Two bits per edge, shifted by the direction's own number."""
        planes[BARRIERS + square(x, y)] = (
            (west << 6) | (south << 4) | (east << 2) | north)

    for i in range(GRID):
        set_wall(i, 0, north=1)
        set_wall(i, GRID - 1, south=1)
        set_wall(0, i, west=1)
        set_wall(GRID - 1, i, east=1)
    for i in range(GRID):
        set_barrier(i, 0, north=SOLID, east=PASSABLE, south=PASSABLE,
                    west=PASSABLE)

    # A room at (4,4)-(6,6) with a door on the west side of (4,5).
    for x in range(4, 7):
        set_wall(x, 4, north=2)
        set_wall(x, 6, south=2)
    for y in range(4, 7):
        set_wall(4, y, west=2)
        set_wall(6, y, east=2)
    set_barrier(4, 5, north=SOLID, east=PASSABLE, south=SOLID, west=PASSABLE)
    planes[ATTRIBUTES + square(5, 5)] = 0x80        # roofed

    # (9,9): art on every edge, every barrier passable -- four doors.
    set_wall(9, 9, north=3, east=3, south=3, west=3)
    set_barrier(9, 9, north=PASSABLE, east=PASSABLE,
                south=PASSABLE, west=PASSABLE)

    # (10,10): SOLID bits on every edge and NO art. The engine tests art first,
    # so this square is open on all four sides. Five earlier readings of the
    # format got exactly this backwards.
    set_barrier(10, 10, north=SOLID, east=SOLID, south=SOLID, west=SOLID)
    return bytes(planes)


# --- a party, composed rather than captured ----------------------------------
# The same reasoning as `synthetic_geo` above, on the save side: a test that
# needs *a* party rather than a specific one gets one built from the format we
# documented, so the guarantee it holds runs on a machine with no game.
#
# It exists to be measured. The window's floor only appears once a save is open
# -- `EditorWindow._adopt` runs then, and `_size_roster` with it -- so #63 and
# #70 both wanted a party CI could open. What sets those widths is the roster's
# five columns, and every one of them is sized from the strings it holds; hence
# the widest case rather than a plausible one.

PARTY_SLOTS = 6
#: A party at the **format's** limits, not at plausible ones -- widths are the
#: only reason this exists, so a value the record can hold beats a value a
#: player would ever see.
#:
#: `hp_max` is two bytes (`goldbox/layout.py` `0x076`), so 65535 rather than a
#: three-digit total: capping it at 999 understated the window's floor by 14px,
#: which is 1251 against 1265 at the base font and exactly the number #71 turns
#: on. The roster's current-hit-points byte is one byte and 255 is its ceiling.
#:
#: `armour_class` is stored biased, `60 - AC` in a byte, so the lowest the
#: editor will let a user set is -195 -- four characters, not three. It happens
#: not to move the column today, which the `AC` header label already dominates,
#: and it is used anyway because "widest" should not mean "widest that matters
#: this week".
#:
#: Abilities are whatever `looks_occupied` accepts, 3..25, so 18 is
#: unremarkable and its width is two digits either way.
WIDEST_HP_MAX = 65535
WIDEST_HP, WIDEST_AC, PARTY_ABILITY = 255, -195, 18


def _widest(strings) -> str:
    """The longest of a table's labels, ties broken by the label itself.

    Longest, not widest in pixels: the point is to be reproducible on a machine
    whose font is not this one, and `half-elf` and `halfling` are the same
    number of characters on all of them.
    """
    return max(strings, key=lambda s: (len(s), s))


def _blank_disk() -> bytearray:
    """A formatted 35-track image with an empty directory."""
    from goldbox import d64
    data = bytearray(d64.IMAGE_SIZE)
    bam = d64.sector_offset(d64.DIRECTORY_TRACK, d64.HEADER_SECTOR)
    data[bam], data[bam + 1] = d64.DIRECTORY_TRACK, d64.DIRECTORY_SECTOR
    data[bam + 2] = 0x41                                    # DOS version 'A'
    pad = bytes([d64.NAME_PAD])
    data[bam + 0x90:bam + 0xA0] = b"SYNTHETIC".ljust(16, pad)
    data[bam + 0xA0:bam + 0xA2] = pad * 2
    data[bam + 0xA2:bam + 0xA4] = b"00"                     # disk id
    data[bam + 0xA4] = d64.NAME_PAD
    data[bam + 0xA5:bam + 0xA7] = b"2A"                     # DOS type
    data[bam + 0xA7:bam + 0xAB] = pad * 4
    first = d64.sector_offset(d64.DIRECTORY_TRACK, d64.DIRECTORY_SECTOR)
    data[first], data[first + 1] = 0, 0xFF                  # one sector, all of it
    return data


def _disk_with(files) -> bytes:
    """An image carrying each `(name, prg)` pair as a closed PRG.

    `goldbox/d64.py` has no block allocator on purpose -- it only ever rewrites a
    file over its own chain -- so the chain is laid down here: consecutive
    sectors from track 1, skipping the directory track. No 1541 would fill a
    disk in that order, and nothing that reads one cares.
    """
    from goldbox import d64
    if len(files) > d64.ENTRIES_PER_DIR_SECTOR:
        raise ValueError("this builder writes one directory sector")
    data = _blank_disk()
    free = [(t, s) for t in range(1, d64.TRACK_COUNT + 1)
            if t != d64.DIRECTORY_TRACK
            for s in range(d64.sectors_per_track(t))]
    dir_at = d64.sector_offset(d64.DIRECTORY_TRACK, d64.DIRECTORY_SECTOR)
    taken = 0
    for slot, (name, prg) in enumerate(files):
        chain = free[taken:taken + d64.D64.blocks_needed(len(prg))]
        taken += len(chain)
        for i, (track, sector) in enumerate(chain):
            off = d64.sector_offset(track, sector)
            chunk = prg[i * d64.PAYLOAD_PER_SECTOR:(i + 1) * d64.PAYLOAD_PER_SECTOR]
            if i + 1 < len(chain):
                data[off], data[off + 1] = chain[i + 1]
            else:
                # A last sector links to track 0 and names the last valid byte.
                data[off], data[off + 1] = 0, 1 + len(chunk)
            data[off + 2:off + 2 + len(chunk)] = chunk
        entry = dir_at + d64.ENTRY_BASE + slot * d64.ENTRY_SIZE
        data[entry] = 0x80 | d64.FILE_TYPE_PRG              # closed PRG
        data[entry + 1], data[entry + 2] = chain[0]
        data[entry + 3:entry + 3 + d64.NAME_LENGTH] = bytes(name).ljust(
            d64.NAME_LENGTH, bytes([d64.NAME_PAD]))
        data[entry + 28] = len(chain) & 0xFF
        data[entry + 29] = len(chain) >> 8
    return bytes(data)


def synthetic_party(game=None) -> bytes:
    """A save disk built from the format, not copied from one.

    Six characters, every one of them as wide as the record and the title's own
    tables allow: a name of `layout.NAME_SIZE` capital Ws, the longest race
    label in `games.race_table`, the class bitmask whose name in
    `editor.enums.class_bit_names` is the longest -- all four classic classes
    at once, `magic-user/cleric/thief/fighter` -- three digits of hit points
    each side of the slash, and a negative armour class so that column is three
    characters too.

    Widest and not plausible, because widths are the whole reason this exists.
    A party of six-letter names produces a floor that is true of nothing, and
    the roster is the one thing left in the header that is sized from the
    strings it holds.
    """
    from editor.enums import class_bit_names
    from goldbox import games
    from goldbox.d64 import attach_load_address
    from goldbox.encoding import COMBAT_BIAS
    from goldbox.layout import NAME_SIZE
    from goldbox.record import CharacterRecord
    from goldbox.savegame import (
        HEADER_SIZE,
        ROSTER_ARMOUR_CLASS,
        ROSTER_HP_CURRENT,
        ROSTER_MOVEMENT,
        ROSTER_SLOT_INDEX,
        ROSTER_STRIDE,
        ROSTER_THAC0,
        SLOT_STRIDE,
    )

    game = game or games.POOL_OF_RADIANCE
    races = games.race_table(game)
    race = _widest(races.values())
    classes = class_bit_names(game)
    mask = _widest(classes.values())

    record = CharacterRecord.blank()
    record.set("name", "W" * NAME_SIZE)
    for ability in ("strength", "intelligence", "wisdom", "dexterity",
                    "constitution", "charisma"):
        record.set(ability, PARTY_ABILITY)
    record.set("race", next(c for c, n in races.items() if n == race))
    record.set("class_bits", next(b for b, n in classes.items() if n == mask))
    record.set("hp_max", WIDEST_HP_MAX)
    head = record.to_bytes()[:SLOT_STRIDE]

    payload = bytearray(game.save_size)
    roster = bytearray(game.roster_size)
    for i in range(PARTY_SLOTS):
        payload[HEADER_SIZE + i * SLOT_STRIDE:
                HEADER_SIZE + (i + 1) * SLOT_STRIDE] = head
        at = i * ROSTER_STRIDE
        roster[at + ROSTER_SLOT_INDEX] = i
        roster[at + ROSTER_THAC0] = COMBAT_BIAS - 20
        roster[at + ROSTER_ARMOUR_CLASS] = COMBAT_BIAS - WIDEST_AC
        roster[at + ROSTER_HP_CURRENT] = WIDEST_HP
        roster[at + ROSTER_MOVEMENT] = 12

    # `Game.roster_in_payload` is the branch: Pool of Radiance alone keeps the
    # roster in its own file at its own load address, and every later title
    # folds it into the save payload at `roster_offset` -- `SaveGame0.roster_page`
    # is the same split on the read side.
    if game.roster_in_payload:
        payload[game.roster_offset:game.roster_offset + game.roster_size] = roster
        files = [(game.save_file, attach_load_address(game.save_load_address,
                                                       bytes(payload)))]
    else:
        files = [
            (game.save_file, attach_load_address(game.save_load_address,
                                                 bytes(payload))),
            (game.roster_file, attach_load_address(game.roster_load_address,
                                                   bytes(roster))),
        ]
    return _disk_with(files)


def synthetic_save(tmp_path, name: str = "SYNTHETIC.D64"):
    """`synthetic_party` written where a window can open it."""
    out = pathlib.Path(tmp_path) / name
    out.write_bytes(synthetic_party())
    return out


# --- a combat arena, composed rather than captured ---------------------------

COMBAT_MODE = 0x6E11
COMBAT_PARAMS = 0x0600
COMBAT_CAMERA = 0x037E
COMBAT_MAP = 0x8C00
COMBAT_ROSTER = 0x8300
COMBAT_POSITIONS = 0x8B00
COMBAT_INITIATIVE = 0xA380
COMBAT_RECORDS = 0x4D00
ARENA_STRIDE = 56
ARENA_MAX_X, ARENA_MAX_Y = 55, 25
OFF_MAP = 0xFF


def synthetic_arena(fighters=((0, 25, 13), (8, 30, 13))) -> dict[int, bytes]:
    """A fight, built from the player's own saves plus generated structures.

    This replaces a capture of live machine memory. A capture was the quick way
    to get a fixture, but it contains whatever game code happened to be resident
    at the time, which is exactly what the repository must not carry.

    Everything here is either the player's own data -- the character records out
    of `savedgame0.bin` and the roster out of `savedgame1.bin`, both saved games
    that would sit on a save disk -- or generated from the format:

    * the parameter block at `$0600`, which is what the reader must consult
      rather than assuming 56 x 26;
    * the map at `$8C00`, empty floor with bit 7 set under each combatant;
    * the position table at `$8B00`, `$FF $FF` for everyone not fighting.

    `fighters` is `(index, x, y)`, index 0-7 the party and 8 upward monsters.
    The party fighter must be an index the saved roster actually fills --
    `savedgame1.bin` holds one, at 0 -- or it has no record and is skipped.
    """
    from goldbox.encoding import COMBAT_BIAS
    from goldbox.savegame import (
        ROSTER_ARMOUR_CLASS,
        ROSTER_HP_CURRENT,
        ROSTER_MOVEMENT,
        ROSTER_STRIDE,
        ROSTER_THAC0,
        SAVE0_LOAD_ADDRESS,
        SAVE1_LOAD_ADDRESS,
    )
    ROSTER_RECORD_SLOT = 0x0D

    save0 = (FIXTURES / "savedgame0.bin").read_bytes()[2:]
    save1 = (FIXTURES / "savedgame1.bin").read_bytes()[2:]

    params = bytearray(0x14)
    params[0x02] = COMBAT_MAP & 0xFF
    params[0x03] = COMBAT_MAP >> 8
    params[0x04] = COMBAT_POSITIONS & 0xFF
    params[0x05] = COMBAT_POSITIONS >> 8
    params[0x06] = 64                                   # combatant slots
    params[0x07] = ARENA_STRIDE
    params[0x12] = ARENA_MAX_X
    params[0x13] = ARENA_MAX_Y

    squares = ARENA_STRIDE * (ARENA_MAX_Y + 1)
    field = bytearray(squares)
    # A block of impassable terrain in view of the fight, so the renderer has
    # something to draw besides floor. Bit 7 is "a combatant stands here"; the
    # low bits are the square's own kind.
    for y in range(11, 16):
        for x in range(20, 23):
            field[y * ARENA_STRIDE + x] = 0x01
    positions = bytearray([OFF_MAP]) * (64 * 4)
    for index, x, y in fighters:
        at = index * 4
        positions[at:at + 4] = bytes([x, y, (index * 4) & 0xFF, 0])
        field[y * ARENA_STRIDE + x] |= 0x80             # someone stands here

    # The roster runs past $83FF, so take it from the save and lay the
    # generated position table on top at $8B00.
    #
    # A saved game only carries eight roster blocks; index 8 and up land in
    # what was resident code when the range was dumped. So every monster gets a
    # block built here, copied from a real one and pointed at its own record --
    # without that, the slot pointer is garbage and the monster has no name.
    roster = bytearray(save1[:COMBAT_POSITIONS - SAVE1_LOAD_ADDRESS])
    for index, _x, _y in fighters:
        if index < 8:
            continue
        at = index * ROSTER_STRIDE
        block = bytearray(roster[:ROSTER_STRIDE])
        block[ROSTER_RECORD_SLOT] = index
        block[ROSTER_HP_CURRENT] = 5
        # The derived combat numbers come from here, not from the record.
        block[ROSTER_THAC0] = COMBAT_BIAS - 19
        block[ROSTER_ARMOUR_CLASS] = COMBAT_BIAS - 6
        block[ROSTER_MOVEMENT] = 9
        roster[at:at + ROSTER_STRIDE] = block
    roster += positions

    # Descending, so the first fighter listed acts first and the round is
    # plainly not over.
    initiative = bytearray(64)
    for n, (index, _x, _y) in enumerate(fighters):
        initiative[index] = len(fighters) - n

    records_at = COMBAT_RECORDS - SAVE0_LOAD_ADDRESS
    records = bytearray(save0[records_at:records_at + 12 * 0x100])

    # Slot 8 holds no record in a saved game -- combat slots are live-only --
    # so build a monster there. An ORC, with the Monster Manual's numbers, so
    # the tooltip has something real to be checked against.
    orc = bytearray(records[0:0x100])                   # a valid record's shape
    orc[0x000:0x014] = b"ORC".ljust(0x14, b"\x00")
    orc[0x0A0] = 1                                      # one hit die
    orc[0x0E1] = COMBAT_BIAS - 6                        # armour class 6
    orc[0x071] = COMBAT_BIAS - 19                       # THAC0 19
    orc[0x09F] = 9                                      # movement
    orc[0x076:0x078] = (5).to_bytes(2, "little")        # hit points, 16-bit
    orc[0x0D9] = 2                                      # attacks per round, x2
    orc[0x0DA:0x0DE] = bytes([1, 8, 0, 0])              # 1d8
    orc[0x0F7], orc[0x0F8], orc[0x0F9] = 10, 0, 1       # 10 + 1 a hit point
    records[8 * 0x100:9 * 0x100] = orc

    return {
        COMBAT_CAMERA: bytes([max(0, fighters[0][1] - 3),
                              max(0, fighters[0][2] - 3)]),
        COMBAT_PARAMS: bytes(params),
        COMBAT_RECORDS: bytes(records),
        COMBAT_MODE: bytes([2]),
        COMBAT_ROSTER: bytes(roster),
        COMBAT_MAP: bytes(field),
        COMBAT_INITIATIVE: bytes(initiative),
    }


def disk_path(stem: str):
    """The path to a named disk, or None. Never skips.

    Safe at module level, which `game_disk` is not: `pytest.skip` outside a test
    needs `allow_module_level`. Pair this with the `needs_disks` marker so the
    module skips as a whole when there are no disks.
    """
    where = disk_dir()
    if where is None:
        return None
    for name in (f"{stem}.D64", f"{stem}.d64", f"{stem}.D64.orig"):
        candidate = where / name
        if candidate.exists():
            return candidate
    return None


def game_disk(stem: str = "POOL1"):
    """The path to one of the player's game disks, or skip.

    Some readers want a disk to open rather than a payload -- `load_item_names`
    and `load_item_templates` take a path. Prefer `game_file` where a payload
    will do; this is for the rest.

    Several tests used to hardcode `work/POOL1.D64.orig` or an absolute path on
    somebody's machine. Both are invisible on CI, and one of them named a
    directory that no longer exists anywhere.
    """
    where = disk_dir()
    if where is None:
        pytest.skip("needs the game disks; set POR_DISKS to where they are")
    for name in (f"{stem}.D64", f"{stem}.d64", f"{stem}.D64.orig"):
        candidate = where / name
        if candidate.exists():
            return candidate
    pytest.skip(f"no {stem} disk where the game disks are")


def save_disks():
    """Every `PORSAVE*` disk the player has, in name order.

    For a check that wants a *population* rather than one specimen -- the
    sample size is the finding, and a test written against `PORSAVE13` alone
    reports n=1 however many disks are sitting beside it.  Empty when the
    disks are not there; pair it with the `needs_disks` marker.
    """
    where = disk_dir()
    if where is None:
        return []
    return sorted(where.glob("PORSAVE*.[dD]64"), key=lambda p: p.name)


def save_disk(stem: str = "PORSAVE"):
    """The path to one of the player's save disks, or skip."""
    where = disk_dir()
    if where is None:
        pytest.skip("needs the save disks; set POR_DISKS to where they are")
    for name in (f"{stem}.D64", f"{stem}.d64"):
        candidate = where / name
        if candidate.exists():
            return candidate
    pytest.skip(f"no {stem} where the disks are")
