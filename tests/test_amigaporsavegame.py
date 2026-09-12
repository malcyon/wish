"""The Amiga Pool of Radiance saved game, built from the source save (#316).

Until this existed, a converted party was wrapped in a `savgam<letter>.dat`
copied off the player's own disk 1 -- so the characters were theirs and the
square, the clock and the quest flags were SSI's.  These are the tests that
keep it built.

Everything reads the player's own disks: the Amiga images through
`gamedisks.toml`'s `amiga` entry, the C64 and DOS parties out of
`$WISH_SPECIMENS`.  Nothing here is committed and every test skips on a
machine that has neither.
"""

from __future__ import annotations

import pathlib

import pytest

from goldbox import amiga_dax, amiga_por
from goldbox.amiga_adf import AmigaDisk
from goldbox.amiga_port import AmigaRecordError
from tests import gamedata

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

ECL_DAX = "/ecl.dax"
SHIPPED_SAVEGAME = "/save/savgamA.dat"


# ---------------------------------------------------------------------------
# The player's own disks
# ---------------------------------------------------------------------------

def _amiga_images():
    from tools import amigasaves, gamedisks

    if not gamedisks.candidates("amiga"):
        pytest.skip("no Amiga disks; set $AMIGA_DISKS")
    return amigasaves.images()


def _disk_holding(path: str) -> bytes:
    """The first Amiga image carrying `path`, as that file's bytes."""
    for _name, data in _amiga_images():
        try:
            return AmigaDisk(bytearray(data)).read_file(path)
        except Exception:
            continue
    pytest.skip(f"no Amiga disk here carries {path}")


@pytest.fixture(scope="module")
def ecl_dax() -> bytes:
    """`ecl.dax` off Pool of Radiance disk 2, the `POOLDATA` volume."""
    return _disk_holding(ECL_DAX)


@pytest.fixture(scope="module")
def shipped() -> bytes:
    """The saved game Pool of Radiance disk 1 ships in slot A."""
    for _name, data in _amiga_images():
        try:
            save = AmigaDisk(bytearray(data)).read_file(SHIPPED_SAVEGAME)
        except Exception:
            continue
        # The Curse save disk carries a `save/savgamA.dat` too, and it is
        # 15221 bytes where this title's is 13141.
        if len(save) == amiga_por.POR_SAVEGAME_SIZE:
            return save
    pytest.skip("no Amiga Pool of Radiance disk 1 here")


def _c64_specimen(name: str) -> pathlib.Path:
    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    found = sorted((root / "por-c64").glob(f"WISH-SPEC-{name}.[dD]64"))
    if not found:
        pytest.skip(f"needs the C64 specimen WISH-SPEC-{name}")
    return found[0]


def _dos_specimen(name: str) -> pathlib.Path:
    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    where = root / "por-dos" / f"WISH-SPEC-{name}"
    if not where.is_dir():
        pytest.skip(f"needs the DOS specimen WISH-SPEC-{name}")
    return where


def _amiga_outdoor_specimen(name: str) -> bytes:
    """One file out of `WISH-SPEC-por-amiga-outdoor`, the run of `#321 (An
    Amiga Pool of Radiance conversion refuses a party standing on the travel
    grid, because no outdoor Amiga saved game has ever been read)`."""
    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    where = root / "por-amiga" / "WISH-SPEC-por-amiga-outdoor" / name
    if not where.is_file():
        pytest.skip(f"needs WISH-SPEC-por-amiga-outdoor/{name}")
    return where.read_bytes()


def _c64_state(name: str) -> amiga_por.PorSaveState:
    from goldbox import c64_port
    from goldbox.d64 import load_payload

    disk = _c64_specimen(name)
    payload = load_payload(str(disk),
                           c64_port.by_key("pool-of-radiance").save_file)
    return amiga_por.por_state_from_c64(payload, str(disk))


# ---------------------------------------------------------------------------
# The container: `ecl.dax`, and the depacker inside it
# ---------------------------------------------------------------------------

def test_every_block_of_ecl_dax_unpacks_to_the_length_its_index_states(
        ecl_dax):
    """The ByteKiller depacker, against the game's own container.

    The stream carries a running XOR of every longword it reads and the
    game's own routine ends with `tst.l d5` on it, so a block that comes out
    the right length with a wrong checksum raises rather than passing -- which
    is what makes this a check of the bits rather than of the arithmetic.
    """
    seen = 0
    for bid, body in amiga_dax.blocks(ecl_dax, "ecl.dax"):
        raw = next(r for i, _o, _c, r in amiga_dax.index(ecl_dax)
                   if i == bid)
        assert len(body) == raw
        # Every ECL script opens with its load address, `u16le` 5000, on all
        # three ports.
        assert body[:2] == b"\x88\x13", bid
        seen += 1
    assert seen == 29


def test_the_shipped_saved_game_carries_its_own_areas_ecl_block(
        ecl_dax, shipped):
    """The oracle the depacker is confirmed by, and the writer's whole basis.

    The engine's own saved game holds block `$49F2` of `ecl.dax` from byte 2
    on, then zeros -- the same relationship DOS's container has with
    `ECL<n>.DAX`.  If this holds, the buffer this conversion stages is the
    buffer the engine would have staged.
    """
    area = amiga_por.por_word(shipped, 0x49F2)
    body = amiga_dax.block(ecl_dax, area, "ecl.dax")[amiga_por.POR_ECL_HEADER:]
    start, end = amiga_por.POR_ECL_BUFFER
    assert shipped[start:start + len(body)] == body
    assert shipped[start + len(body):end] == bytes(end - start - len(body))


def test_a_dos_dax_is_refused_rather_than_read_as_an_amiga_one():
    """The two formats share an extension and nothing else (#65)."""
    with pytest.raises(amiga_dax.AmigaDaxError):
        amiga_dax.block(b"\x00\x09" + b"\x00" * 64, 0, "not-a-dax")


# ---------------------------------------------------------------------------
# Every byte accounted for, and no template
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("specimen", ["por-party-twin-pair",
                                      "porunconscious1",
                                      "por-c64-hall-resave"])
def test_a_c64_party_builds_a_saved_game_that_owes_nothing_to_anybody(
        ecl_dax, specimen):
    """13141 of 13141 bytes with a source, and none left to a template."""
    state = _c64_state(specimen)
    save, report = amiga_por.new_por_savegame(state, "B", 6, ecl_dax)
    assert len(save) == amiga_por.POR_SAVEGAME_SIZE
    assert len(report.sources) == amiga_por.POR_SAVEGAME_SIZE
    assert report.unwritten == []


def test_a_dos_party_builds_one_too(ecl_dax):
    folder = _dos_specimen("por-item-granted")
    from goldbox import dos_savegame

    savgam = (folder / "SAVGAMD.DAT").read_bytes()
    state = amiga_por.por_state_from_dos(savgam, "SAVGAMD.DAT")
    save, report = amiga_por.new_por_savegame(state, "D", 1, ecl_dax)
    assert report.unwritten == []
    # The place is the DOS save's own, read two ways.
    x, y, facing = dos_savegame.position(savgam)
    assert (save[amiga_por.POR_POS_X], save[amiga_por.POR_POS_Y]) == (x, y)
    assert save[amiga_por.POR_POS_FACING] == facing * dos_savegame.FACING_SCALE


def test_the_party_stands_where_the_source_save_says(ecl_dax):
    """What a player would notice: their own square, facing and clock."""
    from goldbox import dos_savegame

    state = _c64_state("porunconscious1")
    save, _report = amiga_por.new_por_savegame(state, "B", 6, ecl_dax)
    assert save[amiga_por.POR_POS_X] == state.x
    assert save[amiga_por.POR_POS_Y] == state.y
    assert save[amiga_por.POR_POS_FACING] == state.facing * 2
    for i, digit in enumerate(state.clock):
        assert amiga_por.por_word(save, dos_savegame.CLOCK + i) == digit
    assert amiga_por.por_word(save, dos_savegame.SCRIPT) == state.area
    assert amiga_por.por_word(save, dos_savegame.AREA) == state.geo
    assert save[amiga_por.POR_PARTY_SIZE_BYTE] == 6
    assert amiga_por.por_word(save, dos_savegame.PARTY_SIZE) == 6


# ---------------------------------------------------------------------------
# The round trip, masked by the declared list rather than by the diff
# ---------------------------------------------------------------------------

#: A provenance line the writer gives a byte it is **declaring** rather than
#: sourcing.  Masking by these rather than by whatever happened to differ is
#: what stops the test agreeing with the code by construction.
DECLARED = ("zeroed", "display scratch", "an unused name slot",
            "the wall art in front", "the square property")


def test_the_shipped_saved_game_round_trips_except_where_it_is_declared(
        ecl_dax, shipped):
    """Read the engine's own file, build it again, and diff.

    Every byte that differs has to be one the writer says it cannot source --
    engine state, the display scratch in the character table, or the two
    bytes the step routine recomputes.  A new difference anywhere else fails
    this, which is the point: the mask is the declared list.
    """
    state = amiga_por.por_state_from_amiga(shipped, "the shipped slot A")
    built, report = amiga_por.new_por_savegame(state, "A", 6, ecl_dax,
                                           portraits=True)
    unexplained = []
    for i, (was, now) in enumerate(zip(shipped, built)):
        if was == now:
            continue
        why = report.sources.get(i, "")
        if not why.startswith(DECLARED):
            unexplained.append((i, report.address(i), why))
    assert unexplained == []


def test_the_regions_a_player_would_notice_round_trip_byte_for_byte(
        ecl_dax, shipped):
    """The script buffer, the square, the clock and the six names.

    Split out from the mask above because these are the regions the ticket is
    about: a difference here is a party in the wrong place, and it should not
    be possible to hide one inside a wider "declared" list.
    """
    state = amiga_por.por_state_from_amiga(shipped, "the shipped slot A")
    built, _report = amiga_por.new_por_savegame(state, "A", 6, ecl_dax,
                                            portraits=True)
    start, end = amiga_por.POR_ECL_BUFFER
    assert built[start:end] == shipped[start:end]
    assert built[amiga_por.POR_POS_X:amiga_por.POR_POS_FACING + 1] == \
        shipped[amiga_por.POR_POS_X:amiga_por.POR_POS_FACING + 1]
    assert built[amiga_por.POR_VIEW_TYPE:amiga_por.POR_PARTY_SIZE_BYTE + 1] == \
        shipped[amiga_por.POR_VIEW_TYPE:amiga_por.POR_PARTY_SIZE_BYTE + 1]
    for n in range(6):
        at = amiga_por.POR_CHARACTER_TABLE + n * amiga_por.POR_CHARACTER_TABLE_STRIDE
        assert built[at:at + 8] == shipped[at:at + 8]


# ---------------------------------------------------------------------------
# What it refuses
# ---------------------------------------------------------------------------

def _outdoor_dos_state() -> amiga_por.PorSaveState:
    """A DOS saved game of a party on the west travel window, built here.

    Built rather than read off a specimen so this never skips: the values
    are the ones `#59 (Map the DOS saved game, not just the character
    record)` measured for an outdoor container, and the point of the test is
    what the **Amiga** writer does with them.
    """
    from goldbox import dos_savegame

    savgam = bytearray(dos_savegame.SAVGAM_SIZE)
    dos_savegame.put_word(savgam, dos_savegame.INDOORS, 0)
    dos_savegame.put_word(savgam, dos_savegame.AREA, 0)
    dos_savegame.put_word(savgam, dos_savegame.SCRIPT, 26)
    dos_savegame.put_travel_square(savgam, 7, 29)
    start, _ = dos_savegame.SAVE_POOL_OF_RADIANCE.script_buffer
    savgam[start] = 0x01
    savgam = bytes(savgam)
    assert dos_savegame.outdoors(savgam)
    return amiga_por.por_state_from_dos(savgam)


def test_a_party_on_the_travel_grid_gets_the_bytes_the_engine_writes(ecl_dax):
    """The two bytes `#321 (An Amiga Pool of Radiance conversion refuses a
    party standing on the travel grid, because no outdoor Amiga saved game
    has ever been read)` measured, and the container around them.

    This used to be a refusal, because byte 12810 and byte 12803 of an
    outdoor Amiga saved game had never been seen.  On 2026-09-07 a party
    bought passage from New Phlan's harbour master, sailed to the west
    landing and saved there twice: **12810 reads 3 and 12803 reads 14**, both
    2 of 2 and both the same as DOS.
    """
    from goldbox import dos_savegame

    state = _outdoor_dos_state()
    assert state.outdoors is True
    save, report = amiga_por.new_por_savegame(state, "B", 6, ecl_dax)

    assert save[amiga_por.POR_VIEW_TYPE] == amiga_por.POR_VIEW_TYPE_OVERLAND == 3
    assert save[amiga_por.POR_WALL_BYTE] == amiga_por.POR_WALL_OUTDOORS == 14
    assert amiga_por.por_word(save, dos_savegame.INDOORS) == 0
    assert amiga_por.por_word(save, dos_savegame.AREA) == 0
    assert amiga_por.por_word(save, dos_savegame.SCRIPT) == 26
    assert (amiga_por.por_word(save, dos_savegame.TRAVEL_X),
            amiga_por.por_word(save, dos_savegame.TRAVEL_Y)) == (7, 29)
    assert amiga_por.por_word(save, dos_savegame.DISK) == 7
    assert report.unwritten == []


def test_an_indoor_party_still_gets_the_indoor_pair(ecl_dax):
    """The other half of the gate, which is what makes it a gate.

    Force the outdoor branch and this fails: an indoor party would arrive
    with the travel grid's view type and a wall in front of it that the map
    does not have.
    """
    from goldbox import dos_savegame

    state = _c64_state("por-party-twin-pair")
    assert state.outdoors is False
    save, _report = amiga_por.new_por_savegame(state, "B", 6, ecl_dax)
    assert save[amiga_por.POR_VIEW_TYPE] == amiga_por.POR_VIEW_TYPE_3D == 1
    assert save[amiga_por.POR_WALL_BYTE] == 0
    assert amiga_por.por_word(save, dos_savegame.INDOORS) == 1
    assert amiga_por.por_word(save, dos_savegame.TRAVEL_X) == 0
    assert amiga_por.por_word(save, dos_savegame.TRAVEL_Y) == 0


def test_the_engines_own_outdoor_saved_game_round_trips(ecl_dax):
    """The strongest form: read what the Amiga engine wrote outdoors, build
    it again, and let the declared list be the mask.

    `WISH-SPEC-por-amiga-outdoor` slot B is the first Amiga saved game ever
    made on the travel grid -- world 20,29 on the status line, window-local
    (7, 29) in the file, area 26, six characters.
    """
    savgam = _amiga_outdoor_specimen("savgamB.dat")
    state = amiga_por.por_state_from_amiga(savgam, "WISH-SPEC-por-amiga-outdoor B")
    assert state.outdoors is True
    assert state.travel == (7, 29)
    assert state.area == 26
    built, report = amiga_por.new_por_savegame(state, "B", 6, ecl_dax)
    unexplained = []
    for i, (was, now) in enumerate(zip(savgam, built)):
        if was == now:
            continue
        why = report.sources.get(i, "")
        if not why.startswith(DECLARED):
            unexplained.append((i, report.address(i), why))
    assert unexplained == []
    start, end = amiga_por.POR_ECL_BUFFER
    assert built[start:end] == savgam[start:end]
    assert built[amiga_por.POR_POS_X:amiga_por.POR_POS_FACING + 1] == \
        savgam[amiga_por.POR_POS_X:amiga_por.POR_POS_FACING + 1]
    assert built[amiga_por.POR_VIEW_TYPE] == savgam[amiga_por.POR_VIEW_TYPE]
    assert built[amiga_por.POR_WALL_BYTE] == savgam[amiga_por.POR_WALL_BYTE]


def test_an_area_the_amiga_has_no_script_for_is_refused(ecl_dax):
    """`ecl.dax` holds 29 blocks and the C64 has 30; area 30 is the missing
    one, so a party standing there has no script to stage."""
    assert 30 not in amiga_dax.block_ids(ecl_dax)
    state = amiga_por.PorSaveState(title="Pool of Radiance", area=30, geo=30,
                               x=1, y=1, facing=0,
                               clock=(0,) * 6, wallset=(0xFFFF,) * 3,
                               flags=(0,) * 217, scratch={},
                               outdoors=False, travel=(0, 0), set_out=True,
                               header={})
    with pytest.raises(AmigaRecordError):
        amiga_por.new_por_savegame(state, "B", 6, ecl_dax)


def test_a_party_of_nobody_or_of_seven_is_refused(ecl_dax):
    state = _c64_state("por-party-twin-pair")
    for count in (0, 7):
        with pytest.raises(AmigaRecordError):
            amiga_por.new_por_savegame(state, "B", count, ecl_dax)


# ---------------------------------------------------------------------------
# The name table, and a party smaller than six
# ---------------------------------------------------------------------------

def test_only_as_many_names_are_written_as_the_party_has(ecl_dax):
    """What the engine does, measured on its own one-character saved game.

    `work/issue105`'s `savgamE.dat`, which Amiga Pool of Radiance itself
    wrote for a party of one, holds `CHRDATE1` in entry 0 and Amiga heap
    addresses in entries 1 to 7.  So a writer that filled all six would be
    writing something the engine does not.
    """
    state = _c64_state("por-party-twin-pair")
    save, _report = amiga_por.new_por_savegame(state, "C", 2, ecl_dax)
    assert save[amiga_por.POR_PARTY_SIZE_BYTE] == 2
    for n in range(amiga_por.POR_NAME_SLOTS):
        at = amiga_por.POR_CHARACTER_TABLE + n * amiga_por.POR_CHARACTER_TABLE_STRIDE
        want = f"CHRDATC{n + 1}".encode("ascii") if n < 2 else bytes(8)
        assert save[at:at + 8] == want, n


def test_a_saved_game_naming_one_character_can_be_pointed_at_another_slot(
        ecl_dax):
    """The regression `retarget_savegame` used to fail on.

    It demanded a `CHRDAT` name in all six entries, so an engine-written
    one-character saved game -- and every one this writer builds for a party
    of fewer than six -- was refused as "not the saved game this function
    knows how to point at another slot".
    """
    state = _c64_state("por-party-twin-pair")
    save, _report = amiga_por.new_por_savegame(state, "B", 1, ecl_dax)
    moved = amiga_por.retarget_savegame(save, "F")
    at = amiga_por.POR_CHARACTER_TABLE
    assert moved[at:at + 8] == b"CHRDATF1"
    assert moved[at + amiga_por.POR_CHARACTER_TABLE_STRIDE:
                 at + amiga_por.POR_CHARACTER_TABLE_STRIDE + 8] == bytes(8)


def test_a_file_with_no_names_at_all_is_still_refused():
    with pytest.raises(AmigaRecordError):
        amiga_por.retarget_savegame(bytes(amiga_por.POR_SAVEGAME_SIZE), "B")


# ---------------------------------------------------------------------------
# The independent parser agrees
# ---------------------------------------------------------------------------

def test_the_saved_game_parser_reads_a_built_one_and_every_check_passes(
        ecl_dax):
    """`tools/amigasavegame.py` walks the file the way the game writes it.

    It was written for `#28 (Decode an Amiga saved game, not just a character
    file)` against the engine's own files and knows nothing about this
    writer, so it agreeing is a second opinion rather than a restatement.
    """
    from tools import amigasavegame

    state = _c64_state("porunconscious1")
    save, _report = amiga_por.new_por_savegame(state, "B", 6, ecl_dax)
    parsed = amigasavegame.parse(save, source="built")
    assert parsed.shape is amigasavegame.POOL_OF_RADIANCE
    assert parsed.count == 6
    assert parsed.square["x"] == state.x
    assert parsed.square["y"] == state.y
    assert parsed.square["facing"] == state.facing * 2
    assert parsed.names[:6] == tuple(f"CHRDATB{n + 1}" for n in range(6))
    assert [claim for claim, ok, _detail in amigasavegame.check(parsed)
            if not ok] == []
