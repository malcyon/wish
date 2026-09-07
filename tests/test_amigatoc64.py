from __future__ import annotations

"""An Amiga Pool of Radiance save slot becoming a C64 one (#353).

You save on the Amiga standing in the Slums at 21:22 with half the quests
done and you want to carry on on the Commodore 64.  The six characters have
crossed since 2026-08-26 -- `goldbox.amiga.to_neutral` then
`goldbox.c64_codec.write`, 90 of 90 sheet fields -- and what these tests
cover is the game around them: the party's own square, the area it is
standing in, the clock and the 217 quest flags.

**Everything reads the player's own disks**, through `tools/gamedisks.py`'s
`amiga` entry, and skips on a machine that has none.  Nothing here is
committed: an Amiga disk image is the game's own code and data
(`AGENTS.md`), and a slice of one is the same copy under a new name.

The two sources are the two shapes of disk, on purpose:

* **the shipped disk 1, slot A** -- a `save` drawer, six characters with
  items, portraits and their own combat figures, standing on New Phlan's
  arrival square where SSI left them;
* **a `POOLSAVE` save disk** -- files at the root, and a slot the Amiga
  game's own `ENCAMP ▸ SAVE` wrote, which is where the place actually being
  somewhere is proved.  `$WISH_SPECIMENS/por-amiga/WISH-SPEC-por-amiga-slums-resave` is that
  disk, put there on 2026-09-07 under `#332 (The specimen tree cannot hold
  an Amiga saved game, so the first two engine-written Amiga parties sit
  outside its checks)`; the tests that want it skip when it is on neither
  the specimen tree nor `work/`.
"""

import pathlib

import pytest

from goldbox import amiga, c64_codec, dos, games, world_state
from goldbox.amiga import AmigaRecordError
from goldbox.amiga_adf import AmigaDisk

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

WORK = pathlib.Path(__file__).resolve().parent.parent / "work"

#: The engine-written Amiga saved game this direction was proved against:
#: Amiga Pool of Radiance's own `ENCAMP ▸ SAVE` to slot C on 2026-09-05,
#: standing in the Slums at 21:22 (`#316`'s run 2).
#:
#: In the specimen tree since 2026-09-07 -- `#332 (The specimen tree cannot
#: hold an Amiga saved game, so the first two engine-written Amiga parties
#: sit outside its checks)` -- with the `work/` copy kept as a fallback,
#: because that is
#: where a machine that has not had `tools/specimens.py add` run on it still
#: has one and `work/` is gitignored either way.
ENGINE_SPECIMEN = ("por-amiga/WISH-SPEC-por-amiga-slums-resave/"
                   "poolsave-c64-after-C.adf")
ENGINE_IN_WORK = WORK / "issue316" / "poolsave-c64-after-C.adf"
ENGINE_SLOT = "C"


def _engine_save_disk() -> pathlib.Path | None:
    """Where the engine-written Amiga slot C is on this machine, or `None`."""
    import os

    tree = pathlib.Path(os.environ.get("WISH_SPECIMENS")
                        or pathlib.Path.home() / "wish-specimens")
    for candidate in (tree / ENGINE_SPECIMEN, ENGINE_IN_WORK):
        if candidate.exists():
            return candidate
    return None

#: A conversion needs the combat icon tables and `ANIMATE00` off the player's
#: C64 disks and refuses without them.  Zeros stand in wherever what is under
#: test is the place or the party rather than the figure -- the same thing
#: `tests/test_curseconvert.py` does, and for the same reason: this is a
#: round trip of our own code, not a claim about what a game disk holds.
BLANK_ICON, BLANK_ANIMATE = bytes(36), bytes(852)


def _pool_of_radiance_disk_1() -> AmigaDisk:
    """The player's Amiga Pool of Radiance disk 1, with slot A in its drawer.

    **Matched on the record's own size, not on the file names.** Amiga Curse
    of the Azure Bonds keeps its saves under the same `save/savgamA.dat` and
    `save/CHRDATA1.sav` names, and a search that stops at the first disk
    carrying those picks up the Curse save disk on this machine and then
    fails several calls down with a 428-byte record. 288 bytes is Pool of
    Radiance's own (`goldbox.amiga.amiga_shape_for`).
    """
    from tools import amigasaves, gamedisks

    if not gamedisks.candidates("amiga"):
        pytest.skip("no Amiga disks; set $AMIGA_DISKS")
    for _name, data in amigasaves.images():
        # The whole open inside the guard: most of what this walks is not a
        # Gold Box disk at all, and a bootable image with no AmigaDOS root
        # block raises here rather than at the lookup.
        try:
            disk = AmigaDisk(bytearray(data))
            record = disk.read_file("/save/CHRDATA1.sav")
            disk.lookup("/save/savgamA.dat")
        except Exception:
            continue
        if len(record) == amiga.AMIGA_POR_RECORD_SIZE:
            return disk
    pytest.skip("no Amiga Pool of Radiance disk 1 here")


@pytest.fixture(scope="module")
def shipped_disk() -> AmigaDisk:
    """Pool of Radiance Amiga disk 1, whose `save` drawer holds slot A."""
    return _pool_of_radiance_disk_1()


@pytest.fixture(scope="module")
def engine_disk() -> AmigaDisk:
    """The `POOLSAVE` disk the Amiga game itself saved slot C onto."""
    path = _engine_save_disk()
    if path is None:
        pytest.skip(f"neither $WISH_SPECIMENS/{ENGINE_SPECIMEN} nor "
                    f"{ENGINE_IN_WORK} is on this machine")
    return AmigaDisk.open(str(path))


@pytest.fixture(scope="module")
def outdoor_disk() -> AmigaDisk:
    """`WISH-SPEC-por-amiga-outdoor`'s own disk.  Slot A is the shipped save
    staged next to the harbour master; slots B and C are the first two
    saved games the Amiga engine itself ever wrote on the travel grid,
    one overland step apart -- `#321 (An Amiga Pool of Radiance conversion
    refuses a party standing on the travel grid, because no outdoor Amiga
    saved game has ever been read)`'s run.
    """
    from tests import gamedata

    where = gamedata.specimen("por-amiga-outdoor", "amiga")
    return AmigaDisk.open(str(where / "por1-outdoor.adf"))


# ---------------------------------------------------------------------------
# Reading the slot off the disk
# ---------------------------------------------------------------------------

def test_the_two_shapes_of_save_disk_are_told_apart_by_their_save_entry(
        shipped_disk, engine_disk):
    """A game disk keeps its saves in a `save` drawer and a `POOLSAVE` disk
    keeps them at the root, which is the whole of the difference and is read
    off the disk rather than passed in (#36).

    On disk 1 `/save` is a drawer holding the slot-list file `/save/save`;
    on a save disk `/save` **is** the slot-list file.
    """
    assert amiga.por_save_drawer(shipped_disk) == amiga.POR_SAVE_DRAWER
    assert amiga.por_save_drawer(engine_disk) == ""
    assert amiga.por_save_path("savgamA.dat", "save") == "/save/savgamA.dat"
    assert amiga.por_save_path("savgamA.dat", "") == "/savgamA.dat"


def test_a_disk_with_no_save_entry_at_all_is_refused(tmp_path):
    """A blank floppy is not a save disk with no saves on it; it is not a
    save disk.  Answering `""` for it would send every reader hunting the
    root of an unrelated volume."""
    blank = AmigaDisk.blank("EMPTY")
    with pytest.raises(AmigaRecordError) as raised:
        amiga.por_save_drawer(blank)
    assert "save" in str(raised.value)


def test_the_shipped_slot_reads_six_characters_and_its_saved_game(
        shipped_disk):
    """`read_por_slot` gives the pair the C64 writer takes: a party of
    `goldbox.dos.DosCharacter` and the 13,141-byte `savgam<letter>.dat`.

    The names are read back off the records rather than pinned to a list,
    because what is under test is that the disk's blocks were read at all.
    """
    party, savgam = amiga.read_por_slot(shipped_disk, "A")
    assert len(party) == amiga.POR_PARTY_MAX
    assert all(isinstance(c, dos.DosCharacter) for c in party)
    assert all(c.shape.key == games.POOL_OF_RADIANCE.key for c in party)
    assert all(c.name for c in party)
    assert len(savgam) == amiga.POR_SAVEGAME_SIZE
    # The shipped party carries gear, so the `.itm` was read too -- which a
    # reader that opened only the `.sav` would pass every other assertion
    # here without.
    assert sum(len(c.items) for c in party) > 0


def test_reading_off_the_disk_gives_what_reading_off_a_path_gives(
        shipped_disk, tmp_path):
    """`tools/porslot.py` reads the three files through a temporary directory
    because `read_amiga_por` wanted a path.  `read_por_slot` reads the blocks
    directly, and this is the check that the two ways in agree -- otherwise
    a second reader has quietly appeared to drift from the first."""
    for index in range(1, amiga.POR_PARTY_MAX + 1):
        stem = f"/save/{amiga.por_filename('A', index, '')}"
        here = tmp_path / f"A{index}.sav"
        here.write_bytes(shipped_disk.read_file(stem + ".sav"))
        for suffix in (".itm", ".spc"):
            try:
                here.with_suffix(suffix).write_bytes(
                    shipped_disk.read_file(stem + suffix))
            except Exception:
                pass
    party, _ = amiga.read_por_slot(shipped_disk, "A")
    for index, char in enumerate(party, start=1):
        by_path = amiga.read_amiga_por(tmp_path / f"A{index}.sav")
        assert amiga.to_dos_character(by_path).to_bytes() == char.to_bytes()
        assert len(by_path.items) == len(char.items)
        assert len(by_path.effects) == len(char.effects)


def test_a_slot_the_disk_has_no_files_for_is_refused_by_name(shipped_disk):
    """Disk 1 ships slot A alone, so every other letter has no records --
    and the sentence names the file it looked for rather than raising a
    `KeyError` several calls down."""
    assert amiga.por_slots_present(shipped_disk) == ["A"]
    with pytest.raises(AmigaRecordError) as raised:
        amiga.read_por_slot(shipped_disk, "F")
    assert "CHRDATF1" in str(raised.value)


def test_a_one_character_slot_reads_one_character(engine_disk):
    """The engine fills the saved game's character table only as far as the
    party goes, so a party of one is a real case rather than a broken disk
    -- `read_por_slot` stops at the first missing `.sav` instead of
    demanding six."""
    party, _ = amiga.read_por_slot(engine_disk, ENGINE_SLOT)
    assert 1 <= len(party) <= amiga.POR_PARTY_MAX


def test_the_three_amiga_record_sizes_name_their_own_titles():
    """288, 428 and 340 bytes, and no two are the same -- so a reader handed
    an `.adf` with nothing else to go on can say what is on it, which is what
    `editor.convert.Source.detect` rests on."""
    assert amiga.amiga_shape_for(288).key == "pool-of-radiance"
    assert amiga.amiga_shape_for(428).key == "curse-of-the-azure-bonds"
    assert amiga.amiga_shape_for(340).key == "secret-of-the-silver-blades"
    with pytest.raises(AmigaRecordError) as raised:
        amiga.amiga_shape_for(285)          # the DOS Pool of Radiance record
    assert "285" in str(raised.value)


# ---------------------------------------------------------------------------
# The place, which is what this direction adds
# ---------------------------------------------------------------------------

def test_an_indoor_party_still_reads_as_indoors(shipped_disk):
    """The other half of the gate lifted by `#376 (An Amiga party on the
    travel grid still cannot be converted to the C64 or DOS, because the
    reader refuses one)`, so it cannot be a tautology: an indoor party is
    unaffected by an outdoor one no longer being refused."""
    _party, savgam = amiga.read_por_slot(shipped_disk, "A")
    state = amiga.read_por_state(savgam, "the shipped slot A")
    assert state.outdoors is False


def test_a_party_on_the_travel_grid_reads_the_travel_square(outdoor_disk):
    """`read_por_state` used to refuse an outdoor party outright -- `#321
    (An Amiga Pool of Radiance conversion refuses a party standing on the
    travel grid, because no outdoor Amiga saved game has ever been read)`.
    `#376` lifted the guard once `#321` had measured the two bytes that had
    never been seen.

    `WISH-SPEC-por-amiga-outdoor`'s slots B and C are the first two saved
    games the Amiga engine itself ever wrote on the travel grid, one
    overland step apart: world `20,29 E 05:53` and `20,28 N 17:53` on the
    game's own status line, `#321`'s run.  The status line prints the world
    coordinate; the file holds the window-local one, `(7, 29)` and
    `(7, 28)`, and `goldbox/areas.py` names `(7, 29)` area 26's WEST boat
    landing.
    """
    for slot, travel, hour, minute, facing in (
            ("B", (7, 29), 5, 53, 1),      # east
            ("C", (7, 28), 17, 53, 0)):    # north
        _party, savgam = amiga.read_por_slot(outdoor_disk, slot)
        state = amiga.read_por_state(savgam, f"slot {slot}")
        assert state.outdoors is True
        assert state.travel == travel
        assert state.area == 26
        assert state.facing == facing
        assert (state.clock[3], state.clock[2] * 10 + state.clock[1]) == \
            (hour, minute), slot


def test_an_outdoor_party_converts_to_the_c64_travel_grid(outdoor_disk):
    """The headline `#376 (An Amiga party on the travel grid still cannot be
    converted to the C64 or DOS, because the reader refuses one)` asks for:
    a party read off the Amiga engine's own outdoor save, written into a C64
    `SAVEDGAME0`, and read back through `goldbox.world_state.from_c64` --
    the two ports agreeing rather than one number compared with itself, the
    way `test_the_converted_save_stands_the_party_where_the_amiga_save_did`
    proves the indoor case.

    **`geo` is the one field that is not a straight copy.**  The Amiga
    engine leaves the resident-map word at 0 outdoors, exactly as DOS does,
    and `goldbox.world_state.from_amiga` substitutes the area table's own
    `SQRDATA05` for area 26's window rather than pass the 0 through --
    `work/p190/C64OUT1.D64`, the engine's own outdoor resave from `#190 (A
    C64 party standing on the travel grid cannot be written into a DOS
    save)`, holds 5 in the same slot for the same area, and a save built
    with the raw 0 loaded in VICE, drew the party roster and never reached
    a world to show.

    **Facing is not asserted.**  Outdoors, the C64 keeps its live overland
    heading at `$033D`, outside the region `SAVEDGAME0` is an image of, so
    `goldbox.dos.apply_position` writes only the travel square outdoors and
    leaves the C64's own `$49C2` however `new_save_from` zeroed it -- a
    limit of the C64 container itself, the same one `#321`'s own comment
    found in the other direction, and not something this reader can supply.
    """
    party, savgam = amiga.read_por_slot(outdoor_disk, "B")
    source = amiga.read_por_state(savgam, "slot B")
    assert source.outdoors is True
    assert source.geo == 5

    save0, _save1, report = dos.new_save_from(
        source, party, BLANK_ICON, BLANK_ANIMATE)
    landed = world_state.from_c64(bytes(save0))

    assert landed.outdoors is True
    assert landed.travel == source.travel == (7, 29)
    assert landed.area == source.area == 26
    assert landed.geo == source.geo == 5
    assert landed.clock == source.clock
    assert report.unwritten == []


def test_a_saved_game_of_the_wrong_length_is_refused(shipped_disk):
    """A `savgam<letter>.dat` is 13,141 bytes and the reader says so, rather
    than reading a word off the end of a short one."""
    with pytest.raises(AmigaRecordError) as raised:
        amiga.read_por_state(bytes(100))
    assert str(amiga.POR_SAVEGAME_SIZE) in str(raised.value)


def test_the_converted_save_stands_the_party_where_the_amiga_save_did(
        engine_disk):
    """The headline of `#353 (Convert an Amiga Pool of Radiance save to the
    C64, so a party standing in the Slums on the Amiga arrives there in
    VICE)`: read the place out of the C64 save this writes and it is the
    Amiga save's own place, field for field.

    Read back through `goldbox.world_state.from_c64`, which is a different
    reader over a different container -- so this is the two ports agreeing
    rather than one number compared with itself.
    """
    party, savgam = amiga.read_por_slot(engine_disk, ENGINE_SLOT)
    source = amiga.read_por_state(savgam, "slot C")
    save0, _save1, _report = dos.new_save_from(
        source, party, BLANK_ICON, BLANK_ANIMATE)
    landed = world_state.from_c64(bytes(save0))

    assert landed.area == source.area
    assert landed.geo == source.geo
    assert (landed.x, landed.y, landed.facing) == \
        (source.x, source.y, source.facing)
    assert landed.clock == source.clock
    assert landed.flags == source.flags
    assert landed.outdoors == source.outdoors is False

    #: **The wallset is not asserted, and that is not a gap.** The C64 keeps
    #: its three `WALLSET` pieces in loaded-files cache slots 15-17, and
    #: `goldbox.dos.apply_file_cache` writes `$FF` -- empty -- into all
    #: twenty-five and then fills only slots 2, 8 and 11, which is the recipe
    #: `docs/140-loaded-files-cache.md` proved live twice. So a converted
    #: save names no wallset and the engine loads the area's own on arrival,
    #: exactly as it does for a DOS source. `#352`'s own closing comment
    #: found the same on the one real DOS/C64 twin pair the specimen tree
    #: holds.
    assert landed.wallset == (0xFFFF, 0xFFFF, 0xFFFF)
    assert source.wallset != landed.wallset


def test_the_engine_written_amiga_slot_is_in_the_slums_at_21_22(engine_disk):
    """The specimen this direction was proved on, pinned so a later run
    knows what it was reading: Amiga Pool of Radiance's own `ENCAMP ▸ SAVE`
    to slot C on 2026-09-05, standing in the Slums.

    Named in the game's own terms because that is what a person compares the
    running C64 against -- area 20 is `goldbox/areas.py`'s The Slums, and
    the six clock digits are sub-minute, minute units, minute tens, hour,
    day, month.
    """
    from goldbox import areas

    _party, savgam = amiga.read_por_slot(engine_disk, ENGINE_SLOT)
    state = amiga.read_por_state(savgam, "slot C")
    assert areas.area_in(state.area, state.title).name == "The Slums"
    hour = state.clock[3]
    minute = state.clock[2] * 10 + state.clock[1]
    assert (hour, minute) == (21, 22)
    assert (state.x, state.y) == (14, 4)


# ---------------------------------------------------------------------------
# The party
# ---------------------------------------------------------------------------

def test_the_converted_party_is_the_amiga_partys_own_fields(shipped_disk):
    """Every character the C64 save carries reads back as the character the
    Amiga record held -- through `goldbox.c64_codec.read` on one side and
    `goldbox.amiga.to_neutral` on the other, which is two readers over two
    containers rather than one value compared with itself.

    The shipped party is the one to do this on: six characters, three
    classes between them, one multi-classed, and every one carrying gear and
    a portrait, so the comparison has something to be wrong about.
    """
    party, savgam = amiga.read_por_slot(shipped_disk, "A")
    state = amiga.read_por_state(savgam, "the shipped slot A")
    save0, save1, _report = dos.new_save_from(
        state, party, BLANK_ICON, BLANK_ANIMATE)

    from goldbox.savegame import SaveGame0, SaveGame1

    sg0 = SaveGame0.from_bytes(bytes(save0), games.POOL_OF_RADIANCE)
    sg1 = SaveGame1(bytes(save1), games.POOL_OF_RADIANCE)
    landed = [c64_codec.read(slot.record, roster=sg1.roster(slot.index),
                             game=games.POOL_OF_RADIANCE)
              for slot in sg0.characters]
    assert len(landed) == len(party)

    #: **The C64 lists its party from the highest slot down** (#101), so the
    #: Amiga file order and the C64 slot order are reverses of one another
    #: and `goldbox.dos.marching_slot` is what turns one into the other.
    #: Zipping the two lists as they come compares GARWAN against MELCAR and
    #: fails on the first field, which is what this reversal is here to stop
    #: -- and asserting it is also the check that the marching order crossed
    #: rather than being scrambled.
    landed = list(reversed(landed))
    assert [c.fields["name"].value for c in landed] == \
        [c.name for c in party]

    #: The fields both ports encode the same way and a player reads off the
    #: sheet.  Compared as decoded values rather than as bytes, which is what
    #: `.claude/rules/conversions.md` means by reading the sheet: an AC of 9
    #: displayed as 51 is a byte-identical save with a wrong sheet.
    same = ("name", "strength", "exceptional_strength", "intelligence",
            "wisdom", "dexterity", "constitution", "charisma",
            "race", "sex", "alignment", "age", "class_bits",
            "hp_max", "hp_current", "experience", "armour_class")
    for c64, amiga_char in zip(landed, party):
        source = dos.to_neutral(amiga_char)
        for name in same:
            assert c64.fields[name].value == source.fields[name].value, \
                f"{source.fields['name'].value}: {name}"

    #: The gear, which is not a field on either neutral record: the C64 keeps
    #: sixteen fixed item slots in the payload and `goldbox.items` is what
    #: reads them, where the Amiga keeps a `.itm` file the record's own count
    #: indexes into.  The shipped party carries 3, 3, 3, 3, 3 and 2 items, so
    #: a conversion that dropped the `.itm` would fail this and pass
    #: everything above it.
    from goldbox.items import items_for_slot

    for index, amiga_char in enumerate(party):
        place = dos.marching_slot(index, len(party))
        assert len(items_for_slot(bytes(save0), place,
                                  games.POOL_OF_RADIANCE)) == \
            len(amiga_char.items), amiga_char.name


def test_every_byte_of_the_converted_save_has_a_source(shipped_disk):
    """`.claude/rules/conversions.md`'s rule against a template: a save built
    from an Amiga slot owes nothing to anybody else's, and
    `goldbox.dos.new_save_from` raises rather than hand one back with a byte
    in it nobody wrote."""
    party, savgam = amiga.read_por_slot(shipped_disk, "A")
    state = amiga.read_por_state(savgam, "the shipped slot A")
    save0, save1, report = dos.new_save_from(
        state, party, BLANK_ICON, BLANK_ANIMATE)
    assert report.unwritten == []
    assert len(report.sources) == report.total == len(save0) + len(save1)


def test_the_amiga_party_arrives_with_its_own_combat_figures(shipped_disk):
    """`#130 (A converted DOS party arrives with six identical combat
    figures, not its own)` for this direction, and the one UNKNOWN
    `#353`'s plan named.

    The Amiga record holds `icon_head`, `icon_body` and `icon_colours` at
    the same offsets the DOS record does (`goldbox.amiga.to_dos_record`), so
    an `IconParts` composes each character's own figure exactly as it does
    for a DOS source.  The check is that six characters do not all get the
    same 36 bytes, which is what a converter with no route to the figure
    hands back.
    """
    from gamedata import disk_dir

    from goldbox.iconparts import IconParts

    disks = disk_dir()
    if disks is None:
        pytest.skip("needs the player's C64 game disks for SPELLE64/SPELLN64")
    parts = None
    for path in sorted(pathlib.Path(disks).glob("*.[dD]64")):
        try:
            parts = IconParts.load(str(path))
            break
        except Exception:
            continue
    if parts is None:
        pytest.skip("no C64 disk here carries the icon option tables")

    party, savgam = amiga.read_por_slot(shipped_disk, "A")
    state = amiga.read_por_state(savgam, "the shipped slot A")
    save0, _save1, _report = dos.new_save_from(
        state, party, parts, BLANK_ANIMATE)

    from goldbox import c64_save

    container = c64_save.container_for(games.POOL_OF_RADIANCE)
    figures = []
    for index in range(len(party)):
        at = container.icon(dos.marching_slot(index, len(party)))
        figures.append(bytes(save0[at:at + dos.ICON_SIZE]))
    # The shipped six name five distinct heads and five distinct bodies
    # between them, so their figures cannot all be one figure -- and six
    # identical ones is exactly what a converter with no route to the figure
    # hands back (#130).
    assert len({c.get("icon_head") for c in party}) > 1
    assert len(set(figures)) > 1
    assert all(any(f) for f in figures)
