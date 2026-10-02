"""A Curse of the Azure Bonds party saved on the world map converts between ports.

The world map (areas `$50` and `$51`) is outdoors with no travel grid: every
port saves `$49E6` = 0 there, no port's load path reads `$49C5` while it is 0,
the square is the one the party last stood on, and the party's place on the
map is the node at `$4C9B` with its destination at `$4C9C`, both inside the
quest-flag window.  The synthetic saves here are built from offsets and carry
no game data; the specimen tests read the two engine-written world-map saves
we have, at run time.
"""
from __future__ import annotations

import dataclasses
import pathlib
import types

import gamedata
import pytest

from goldbox import (
    areas,
    c64_port,
    c64_save,
    dos_codec,
    world_state,
)
from goldbox import dos_savegame as sg

CURSE = areas.CURSE_OF_THE_AZURE_BONDS
CURSE_GAME = c64_port.CURSE_OF_THE_AZURE_BONDS
DOS_CURSE = sg.SAVE_CURSE_OF_THE_AZURE_BONDS
#: The node and destination, as payload offsets of the C64 save and as
#: indices into `WorldState.flags`.
NODE, DESTINATION = 0x4C9B - 0x4B00, 0x4C9C - 0x4B00
FLAGS_FIRST = c64_save.CURSE_OF_THE_AZURE_BONDS.quest_flags[0]
#: `$49C5` as the C64's world-map script writes it, `LOADFILES #127`.
NO_MAP = 0x7F


# --- the area model ---------------------------------------------------------
def test_the_world_map_rows_save_outdoors_without_a_travel_grid():
    for area in (0x50, 0x51):
        row = areas.area_in(area, CURSE)
        assert row.world_map is True
        assert row.saves_outdoors is True
        assert row.outdoors is False      # no SQRDATA: not a travel grid
        assert row.sqrdata is None


def test_no_other_row_of_any_title_is_a_world_map():
    marked = [(title, row.id) for title, rows in areas.TABLES.items()
              for row in rows if row.world_map]
    assert marked == [(CURSE, 0x50), (CURSE, 0x51)]
    for rows in areas.TABLES.values():
        for row in rows:
            if not row.world_map:
                assert row.saves_outdoors == row.outdoors


# --- reading a DOS or Amiga save --------------------------------------------
def _dos_world_map(*, indoors: int = 0, area: int = 0x50, geo: int = 3,
                   node: int = 4, destination: int = 5) -> bytes:
    """A DOS Curse container standing on the world map, built from offsets."""
    savgam = bytearray(DOS_CURSE.size)
    savgam[DOS_CURSE.head] = 1
    sg.put_word(savgam, sg.AREA, geo, DOS_CURSE)
    sg.put_word(savgam, sg.SCRIPT, area, DOS_CURSE)
    sg.put_word(savgam, sg.DISK, 1, DOS_CURSE)
    sg.put_word(savgam, sg.INDOORS, indoors, DOS_CURSE)
    sg.put_word(savgam, sg.VAR_BASE + NODE, node, DOS_CURSE)
    sg.put_word(savgam, sg.VAR_BASE + DESTINATION, destination, DOS_CURSE)
    sg.put_position(savgam, 0, 15, 0, DOS_CURSE)
    sg.put_wall_block(savgam, (1, 2, 4), DOS_CURSE)
    start, _end = DOS_CURSE.script_buffer
    savgam[start] = 1               # a staged script: the party has set out
    sg.put_party_size(savgam, 1, DOS_CURSE)
    return bytes(savgam)


def test_a_dos_world_map_save_reads_as_outdoors_on_the_world_map():
    state = world_state.from_dos(_dos_world_map(), DOS_CURSE)
    assert state.area == 0x50
    assert state.outdoors is True
    assert world_state.on_world_map(state)
    assert state.geo == 3                       # the save's own $49C5
    assert (state.x, state.y, state.facing) == (0, 15, 0)
    assert state.wallset == (1, 2, 4)           # the square block's triple
    assert state.flags[NODE - FLAGS_FIRST] == 4
    assert state.flags[DESTINATION - FLAGS_FIRST] == 5


def test_a_world_map_save_marked_indoors_is_still_a_contradiction():
    with pytest.raises(dos_codec.DosRecordError, match=r"\$49E6 says indoors"):
        world_state.from_dos(_dos_world_map(indoors=1), DOS_CURSE)


def test_an_indoor_area_marked_outdoors_is_still_a_contradiction():
    savgam = _dos_world_map(area=0x03, geo=3)
    with pytest.raises(dos_codec.DosRecordError, match=r"\$49E6 says outdoors"):
        world_state.from_dos(savgam, DOS_CURSE)


# --- writing it -------------------------------------------------------------
def _c64_world_map_state(**changes) -> world_state.WorldState:
    """What `from_c64` reads off a C64 world-map save, built from offsets."""
    cont = c64_save.container_for(CURSE_GAME)
    save0 = bytearray(cont.payload_size)
    save0[cont.current_script] = 0x50
    save0[cont.current_geo] = NO_MAP
    save0[cont.indoors] = 0
    save0[cont.position:cont.position + 3] = bytes((0, 15, 0))
    save0[cont.cache[0]:cont.cache[0] + cont.cache[1]] = (
        bytes([0xFF]) * cont.cache[1])
    save0[NODE], save0[DESTINATION] = 4, 5
    state = world_state.from_c64(bytes(save0), game=CURSE_GAME)
    return dataclasses.replace(state, **changes)


def test_the_c64_reads_its_world_map_save_as_the_world_map():
    state = _c64_world_map_state()
    assert state.outdoors and world_state.on_world_map(state)
    assert state.geo == NO_MAP == world_state.WORLD_MAP_GEO
    assert state.wallset == (sg.EMPTY,) * 3


def _dos_written(state: world_state.WorldState) -> bytes:
    savgam = bytearray(DOS_CURSE.size)
    report = dos_codec.SaveReport(total=DOS_CURSE.size)
    dos_codec.savgam_writes(savgam, report, state, "A", 1, b"\0\0\x01",
                            game=CURSE_GAME, dax=1)
    return bytes(savgam)


@pytest.mark.parametrize("geo,wallset", [
    (NO_MAP, (sg.EMPTY,) * 3),                       # from the C64
    (3, (1, 2, 4)),                                  # from DOS or the Amiga
])
def test_the_dos_writer_keeps_the_party_on_the_world_map(geo, wallset):
    state = _c64_world_map_state(geo=geo, wallset=wallset)
    savgam = _dos_written(state)
    assert sg.word(savgam, sg.INDOORS, DOS_CURSE) == 0
    assert sg.word(savgam, sg.AREA, DOS_CURSE) == geo
    assert sg.word(savgam, sg.SCRIPT, DOS_CURSE) == 0x50
    assert sg.position(savgam, DOS_CURSE) == (0, 15, 0)
    assert sg.wall_block(savgam, DOS_CURSE)[0] == wallset
    back = world_state.from_dos(savgam, DOS_CURSE)
    for field in ("area", "geo", "x", "y", "facing", "outdoors", "travel",
                  "wallset", "flags", "scratch"):
        assert getattr(back, field) == getattr(state, field), field


def test_the_c64_writer_writes_what_the_world_map_script_leaves():
    """`$4BC5` = `$7F` and `$4BE6` = 0, as `ECL50`'s entry writes them, and
    a cache empty but for the script and `ANIMATE00`."""
    state = dataclasses.replace(_c64_world_map_state(), geo=3,
                                wallset=(1, 2, 4))
    cont = c64_save.container_for(CURSE_GAME)
    save0 = bytearray(cont.payload_size)
    dos_codec.apply_file_cache(save0, state, cont)
    dos_codec.apply_position(save0, state)
    at, slots = cont.cache
    want = bytearray([0xFF]) * slots
    want[dos_codec.CACHE_ECL] = 0x50 | dos_codec.FILE_CACHE_RELOAD
    want[dos_codec.CACHE_ANIMATE] = (dos_codec.ANIMATE_RESIDENT
                                     | dos_codec.FILE_CACHE_RELOAD)
    assert save0[at:at + slots] == want
    assert save0[cont.current_geo] == 0x7F
    assert save0[cont.indoors] == 0
    assert save0[cont.current_script] == 0x50
    assert save0[cont.disk_hint] == 1
    assert tuple(save0[cont.position:cont.position + 3]) == (0, 15, 0)
    back = world_state.from_c64(bytes(save0), game=CURSE_GAME)
    assert back.outdoors and back.area == 0x50 and back.geo == 0x7F
    assert (back.x, back.y, back.facing) == (0, 15, 0)


# --- the engine-written saves, through Save As ------------------------------
C64_SPECIMEN = ("curse-813-c64-worldmap-0x50", "c64",
                "WISH-SPEC-curse-813-c64-worldmap-0x50.D64", None)
AMIGA_SPECIMEN = ("curse-37-amiga-worldmap-tilverton", "amiga",
                  "curseA-slotF-worldmap-tilverton.adf", "F")


def _specimen_file(name, platform, filename) -> pathlib.Path:
    """A one-file specimen sits beside its provenance; a folder one inside."""
    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree ($WISH_SPECIMENS)")
    for folder in (f"coab-{platform}", f"por-{platform}"):
        flat = root / folder / filename
        if flat.is_file():
            return flat
    where = gamedata.specimen(name, platform)
    found = sorted(pathlib.Path(where).glob(filename))
    if not found:
        pytest.skip(f"specimen {name} holds no {filename}")
    return found[0]


def _amiga_disks() -> tuple[pathlib.Path, pathlib.Path]:
    from automap import gamedisks
    for root in gamedisks.candidates("amiga"):
        one = sorted(pathlib.Path(root).rglob("CurseOfTheAzureBonds_A.adf"))
        two = sorted(pathlib.Path(root).rglob("CurseOfTheAzureBonds_B.adf"))
        if one and two:
            return one[0], two[0]
    pytest.skip("needs the player's Amiga Curse disks A and B")


def _save_as(source: pathlib.Path, slot, port: str, out: pathlib.Path) -> dict:
    from automap import gamedisks
    from editor import convert
    from tools.convert import saveasdrive
    from tools.dos import dosbox
    try:
        c64 = pathlib.Path(str(gamedisks.find("curse-of-the-azure-bonds")))
        dos = dosbox.find_game("CURSE")
    except (gamedisks.RegistryError, FileNotFoundError):
        pytest.skip("needs the player's C64 Curse disks and DOS Curse")
    one, two = _amiga_disks()
    window = types.SimpleNamespace(
        game_files_for=lambda title: convert._game_files_from_folder(c64, title))
    report = saveasdrive.save_as(
        window, source, port, out, source_slot=slot, dos_folder=dos,
        amiga_disk=two if port == "amiga" else None,
        amiga_disk_one=one if port == "amiga" else None)
    assert "refused" not in report, report.get("error")
    return report


def _read_back(port: str, written: list[str]):
    """`(state, extra)` for what Save As wrote, read as the destination."""
    from goldbox import amiga_savegame, savegame
    from goldbox.amiga_adf import AmigaDisk
    from goldbox.d64 import D64
    paths = [pathlib.Path(p) for p in written]
    if port == "c64":
        _game, s0, _s1 = savegame.load_save(D64.open(paths[0]))
        payload = bytes(s0._data)
        return world_state.from_c64(payload, game=CURSE_GAME), payload
    if port == "amiga":
        saved = amiga_savegame.read_slot(AmigaDisk.open(paths[0]), "A")
        return amiga_savegame.state_from_savegame(saved), saved
    savgam = next(p for p in paths if p.name.upper().startswith("SAVGAM"))
    data = savgam.read_bytes()
    return world_state.from_dos(data, DOS_CURSE), data


@pytest.mark.parametrize("specimen,port", [
    (C64_SPECIMEN, "amiga"), (C64_SPECIMEN, "dos"),
    (AMIGA_SPECIMEN, "c64"), (AMIGA_SPECIMEN, "dos"),
])
def test_an_engine_written_world_map_save_converts_through_save_as(
        specimen, port, tmp_path):
    name, platform, filename, slot = specimen
    source = _specimen_file(name, platform, filename)
    report = _save_as(source, slot, port, tmp_path)
    before = (_read_back(platform, [str(source)])[0] if platform == "c64"
              else _amiga_source_state(source, slot))
    after, raw = _read_back(port, report["written"])

    assert after.area == before.area == 0x50
    assert after.outdoors is True and world_state.on_world_map(after)
    assert (after.x, after.y, after.facing) == (before.x, before.y,
                                                before.facing) == (0, 15, 0)
    assert after.travel == before.travel
    assert after.flags == before.flags          # the node and destination too
    assert after.scratch == before.scratch      # the neighbour row
    assert after.clock == before.clock
    if port == "c64":
        cont = c64_save.container_for(CURSE_GAME)
        assert raw[cont.current_geo] == 0x7F and raw[cont.indoors] == 0
        assert after.wallset == (sg.EMPTY,) * 3
    else:
        assert after.geo == before.geo          # $7F from the C64, 3 kept
        assert after.wallset == before.wallset
    if port == "amiga":
        assert (raw.first_mode, raw.mode) == (4, 2)   # the Amiga's own pair
        assert raw.word(sg.INDOORS) == 0


def _amiga_source_state(path: pathlib.Path, slot: str):
    from goldbox import amiga_savegame
    from goldbox.amiga_adf import AmigaDisk
    return amiga_savegame.state_from_savegame(
        amiga_savegame.read_slot(AmigaDisk.open(path), slot))


def test_the_amiga_engine_written_world_map_save_reads():
    name, platform, filename, slot = AMIGA_SPECIMEN
    state = _amiga_source_state(_specimen_file(name, platform, filename), slot)
    assert state.area == 0x50 and state.outdoors
    assert state.geo == 3                       # the sewers' map, kept
    assert (state.x, state.y, state.facing) == (0, 15, 0)
    assert state.wallset == (1, 2, 4)
    assert state.flags[NODE - FLAGS_FIRST] == 0  # Tilverton
