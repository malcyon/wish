"""A Curse of the Azure Bonds party converted to DOS gets the camp mode at 12807.

DOS Curse draws a loaded save's own map and wall sets only when the mode byte
at SAVGAM offset 12807 is not 0 (`GAME.OVR:0x1F450`), and the Pit of Moander's
script, like ten other indoor areas', runs no `LOADFILES` when the save already
names it.  ENCAMP > SAVE writes 2 there, the mode the camp menu sets on entry
(`GAME.OVR:0x1B3A6`); the party menu's own save writes 0 (`GAME.OVR:0x201C0`),
which is what a party that has not set out keeps.  The C64 saves here are built
from offsets; the Amiga and DOS ones are engine-written specimens, read at run
time.
"""
from __future__ import annotations

import dataclasses

import gamedata
import pytest

from goldbox import (
    amiga_savegame,
    c64_port,
    c64_save,
    dos_codec,
    world_state,
)
from goldbox import dos_savegame as sg
from goldbox.amiga_adf import AmigaDisk

CURSE_GAME = c64_port.CURSE_OF_THE_AZURE_BONDS
DOS_CURSE = sg.SAVE_CURSE_OF_THE_AZURE_BONDS
#: The Pit of Moander, `ECL11` in `ECL3.DAX`.
PIT, PIT_DAX = 0x11, 3
#: A square inside the Pit, and a wallset triple as the C64 cache holds one.
PIT_SQUARE = (1, 3, 0)
PIT_WALLSET = (3, 6, 7)
#: What ENCAMP > SAVE leaves in 12806 and 12807 after a load and BEGIN: the
#: camp mode 2 that 60 of the 64 distinct DOS Curse saves here hold.
CAMP_PAIR = (0, 2)


def _c64_state(area: int) -> world_state.WorldState:
    """What `from_c64` reads off a C64 Curse save standing in `area`."""
    cont = c64_save.container_for(CURSE_GAME)
    save0 = bytearray(cont.payload_size)
    save0[cont.current_script] = area
    save0[cont.current_geo] = area
    save0[cont.indoors] = 1
    save0[cont.position:cont.position + 3] = bytes(PIT_SQUARE)
    save0[cont.cache[0]:cont.cache[0] + cont.cache[1]] = (
        bytes([0xFF]) * cont.cache[1])
    state = world_state.from_c64(bytes(save0), game=CURSE_GAME)
    return dataclasses.replace(state, wallset=PIT_WALLSET)


def _dos_written(state: world_state.WorldState, dax: int = PIT_DAX) -> bytes:
    savgam = bytearray(DOS_CURSE.size)
    report = dos_codec.SaveReport(total=DOS_CURSE.size)
    dos_codec.savgam_writes(savgam, report, state, "A", 1, b"\0\0\x01",
                            game=CURSE_GAME, dax=dax)
    return bytes(savgam)


def _modes(savgam: bytes) -> tuple[int, int]:
    return savgam[DOS_CURSE.previous_mode], savgam[DOS_CURSE.mode]


def test_the_mode_byte_is_file_offset_12807():
    assert DOS_CURSE.mode == 12807 and DOS_CURSE.previous_mode == 12806


def test_a_c64_party_in_the_pit_converts_with_the_camp_mode():
    state = _c64_state(PIT)
    assert state.set_out and not state.outdoors
    savgam = _dos_written(state)
    assert sg.current_area(savgam) == PIT
    assert _modes(savgam) == CAMP_PAIR


def test_a_c64_party_that_has_not_set_out_keeps_the_party_menu_mode():
    state = _c64_state(0)
    assert world_state.has_not_set_out(state)
    assert _modes(_dos_written(state)) == (0, 0)


def test_put_tail_state_writes_zero_for_a_party_that_has_not_set_out():
    savgam = bytearray(DOS_CURSE.size)
    sg.put_tail_state(savgam, indoors=True, container=DOS_CURSE, set_out=False)
    assert _modes(savgam) == (0, 0)
    sg.put_tail_state(savgam, indoors=True, container=DOS_CURSE)
    assert _modes(savgam) == CAMP_PAIR


def _amiga_camp_save() -> amiga_savegame.AmigaSavegame:
    """`WISH-SPEC-coab-amiga-resave` slot E: Amiga Curse's own ENCAMP > SAVE."""
    where = gamedata.specimen("coab-amiga-resave", platform="amiga")
    path = where / "savgamE.dat"
    return amiga_savegame.parse(path.read_bytes(), amiga_savegame.CURSE,
                                str(path))


def test_an_amiga_party_moved_into_the_pit_converts_with_the_camp_mode():
    state = amiga_savegame.state_from_savegame(_amiga_camp_save())
    assert state.set_out and not state.outdoors
    x, y, facing = PIT_SQUARE
    in_the_pit = dataclasses.replace(state, area=PIT, geo=PIT, x=x, y=y,
                                     facing=facing)
    savgam = _dos_written(in_the_pit)
    assert sg.current_area(savgam) == PIT
    assert _modes(savgam) == CAMP_PAIR


def test_an_amiga_party_saved_at_the_party_menu_keeps_the_party_menu_mode():
    where = gamedata.specimen("curse-dostoamiga-partymenu-slotc",
                              platform="amiga")
    disk = AmigaDisk((where / "curseA-partymenu-slotc.adf").read_bytes())
    save = amiga_savegame.read_slot(disk, "C", amiga_savegame.CURSE)
    state = amiga_savegame.state_from_savegame(save)
    assert world_state.has_not_set_out(state)
    assert _modes(_dos_written(state)) == (0, 0)


def test_the_writer_matches_dos_curse_s_own_camp_save_of_a_converted_party():
    """Slot B of `WISH-SPEC-curse-632-wish-converted-resave` is DOS Curse's
    ENCAMP > SAVE of a party Wish converted from the C64: the game's own pair
    for exactly this state, which the writer gives back."""
    where = gamedata.specimen("curse-632-wish-converted-resave")
    engine = (where / "SAVGAMB.DAT").read_bytes()
    assert _modes(engine) == CAMP_PAIR
    state = world_state.from_dos(engine, DOS_CURSE)
    assert state.set_out
    assert _modes(_dos_written(state, dax=engine[DOS_CURSE.head])) == \
        _modes(engine)


@pytest.mark.parametrize("area", [0x50, 0x51])
def test_a_world_map_party_also_gets_the_camp_mode(area):
    """DOS Curse's own world-map save holds 2 at 12807 too; the loader's map
    gate tests indoors first, so it draws nothing from it out there."""
    cont = c64_save.container_for(CURSE_GAME)
    save0 = bytearray(cont.payload_size)
    save0[cont.current_script] = area
    save0[cont.current_geo] = 0x7F
    save0[cont.cache[0]:cont.cache[0] + cont.cache[1]] = (
        bytes([0xFF]) * cont.cache[1])
    state = world_state.from_c64(bytes(save0), game=CURSE_GAME)
    assert world_state.on_world_map(state)
    assert _modes(_dos_written(state, dax=1))[1] == CAMP_PAIR[1]
