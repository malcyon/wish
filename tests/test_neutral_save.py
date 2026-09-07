"""`goldbox.neutral_save.NeutralSave`, the lift of `goldbox.amiga.PorSaveState`
into one shape every port's saved-game reader fills
(`#352 (Lift PorSaveState into one NeutralSave that every port's saved-game
reader fills and both container writers take)`).

`tests/test_amigaporsavegame.py` and `tests/test_toamigapor.py` keep the
Amiga-specific coverage of the three `goldbox.amiga.por_state_from_*`
wrappers; what belongs here is the general reader itself -- that it agrees
with a title's own C64 and DOS specimens, and the five fields it added
against `PorSaveState`.
"""

from __future__ import annotations

import pathlib

import pytest

from goldbox import c64_save, dos, dos_savegame, games, neutral_save
from tests import gamedata


def _c64_specimen(name: str) -> pathlib.Path:
    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    found = sorted((root / "por-c64").glob(f"WISH-SPEC-{name}.[dD]64"))
    if not found:
        pytest.skip(f"needs the C64 specimen WISH-SPEC-{name}")
    return found[0]


def _c64_state(name: str, game=None) -> neutral_save.NeutralSave:
    from goldbox.d64 import load_payload

    game = game or games.POOL_OF_RADIANCE
    disk = _c64_specimen(name)
    payload = load_payload(str(disk), game.save_file)
    return neutral_save.from_c64(payload, game, str(disk))


def _dos_savgam(name: str, slot: str) -> bytes:
    where = gamedata.specimen(name)
    savgam = where / f"SAVGAM{slot}.DAT"
    if not savgam.is_file():
        pytest.skip(f"WISH-SPEC-{name} has no {savgam.name}")
    return savgam.read_bytes()


# ---------------------------------------------------------------------------
# The one twin pair this project has: a DOS save, and the C64 engine's own
# resave of the party this project's own converter built from it.
# ---------------------------------------------------------------------------

def test_from_c64_and_from_dos_agree_on_the_projects_one_twin_pair():
    """`WISH-SPEC-por-c64-hall-resave` is the C64 engine's own `ENCAMP >
    SAVE` of `WISH-SPEC-por-party-trained-c2` (DOS slot F), converted by
    this project's own `dos.convert_save` and then loaded and resaved --
    `tests/test_dosconversionarea.py` already cites the pair for `$49C5`
    and `$49F2` alone. `from_c64` and `from_dos` read both files
    independently and agree exactly on area, resident map, square, facing
    and all 217 quest flags.

    The clock does not agree to the digit: the C64 read holds one more
    minute-units digit than the DOS source (5 against 4), which is the
    boot-to-`ENCAMP`-menu time VICE spent between the disk being written and
    the player reaching `SAVE CURRENT GAME` -- a real minute passing, not a
    reader disagreement, so only the four digits time cannot move against
    are asserted exactly.

    The wallset, the per-script scratch and the header words are **not**
    asserted here: area 11 borrows New Phlan's `GEO00` and loads no
    `WALLSET` of its own (`goldbox.dos.c64_wall_triple`'s own docstring),
    and the hall's script runs between the DOS save and the C64 resave, so
    those three are expected to differ and do.
    """
    c64_state = _c64_state("por-c64-hall-resave")
    dos_state = neutral_save.from_dos(
        _dos_savgam("por-party-trained-c2", "F"))

    assert c64_state.area == dos_state.area == 11
    assert c64_state.geo == dos_state.geo == 0
    assert (c64_state.x, c64_state.y, c64_state.facing) == \
        (dos_state.x, dos_state.y, dos_state.facing) == (5, 0, 3)
    assert c64_state.outdoors is dos_state.outdoors is False
    assert c64_state.set_out is dos_state.set_out is True
    assert c64_state.flags == dos_state.flags
    assert len(c64_state.flags) == len(dos_state.flags) == 217

    sub, c64_minute, minute_tens, hour, day, month = c64_state.clock
    dos_sub, dos_minute, dos_minute_tens, dos_hour, dos_day, dos_month = \
        dos_state.clock
    assert (hour, day, month) == (dos_hour, dos_day, dos_month)
    assert minute_tens == dos_minute_tens
    assert c64_minute - dos_minute in (0, 1)


# ---------------------------------------------------------------------------
# The five fields PorSaveState lacked
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("game,width", [
    (games.CURSE_OF_THE_AZURE_BONDS, 224),
    (games.SECRET_OF_THE_SILVER_BLADES, 224),
])
def test_the_flag_window_is_the_later_titles_own_wider_one(game, width):
    """`PorSaveState` always read Pool of Radiance's 217-byte window, which
    is 7 bytes short of Curse and Secret of the Silver Blades' own 224
    (`c64_save.Container.quest_flags`).  `from_c64` and `from_dos` both
    read the width from that table instead of assuming Pool of Radiance's.
    """
    name = ("curse-dual-classed" if game is games.CURSE_OF_THE_AZURE_BONDS
            else "ssb-malachite-trained")
    state = _c64_state(name, game)
    assert len(state.flags) == width == \
        c64_save.container_for(game).quest_flags[1]


def test_from_dos_reads_the_same_wider_window_for_the_later_titles():
    savgam = _dos_savgam("curse-299-whole-engine-resave", "D")
    state = neutral_save.from_dos(savgam)
    assert state.title == "Curse of the Azure Bonds"
    assert len(state.flags) == 224


def test_the_later_titles_copied_header_words_are_read():
    """`+$E7`-`+$E9` and `+$FD`-`+$FE`: Pool of Radiance copies none of them,
    Curse of the Azure Bonds copies `+$E7`-`+$E8` and Secret of the Silver
    Blades all five (`c64_save.Container.copied`) -- read here regardless of
    title, so `header` is never a title-shaped lookup for a caller."""
    savgam = _dos_savgam("curse-299-whole-engine-resave", "D")
    state = neutral_save.from_dos(savgam)
    assert set(state.header) == set(neutral_save.HEADER_ADDRESSES)


def _fresh_savgam() -> bytes:
    """A party that has never pressed `BEGIN ADVENTURING`: the initialiser's
    own signature (`tests/test_dosconvert.py`'s `_never_adventured_savgam`,
    not imported -- a test module's private helpers are not another's to
    depend on) -- area 0, map 0, `$49E6` = 0, an all-zero staged script."""
    savgam = bytearray(dos_savegame.SAVGAM_SIZE)
    dos_savegame.put_position(savgam, 15, 1, 3)
    return bytes(savgam)


def test_a_party_that_has_never_set_out_is_placed_at_the_start_of_the_story():
    """`set_out` is false and `area`/`x`/`y`/`facing` are already New Phlan's
    arrival square, `areas.STARTS`'s own answer -- not the initialiser's
    `15,1` the raw file happens to hold at the same offset by coincidence,
    and not a refusal (`#301`, `#326`)."""
    state = neutral_save.from_dos(_fresh_savgam())
    assert state.set_out is False
    assert state.area == 0
    assert (state.x, state.y, state.facing) == (15, 1, 3)
    assert state.outdoors is False


def test_a_party_standing_in_the_world_is_left_where_it_is():
    savgam = bytearray(dos_savegame.SAVGAM_SIZE)
    dos_savegame.put_word(savgam, dos_savegame.INDOORS, 1)
    dos_savegame.put_position(savgam, 3, 9, 2)
    dos_savegame.put_clock(savgam, (0, 8, 5, 16, 4, 2))
    start, _ = dos_savegame.SAVE_POOL_OF_RADIANCE.script_buffer
    savgam[start] = 0x01
    dos_savegame.put_word(savgam, dos.LATER_BEGUN_WORD, 255)
    state = neutral_save.from_dos(bytes(savgam))
    assert state.set_out is True
    assert (state.x, state.y, state.facing) == (3, 9, 2)


# ---------------------------------------------------------------------------
# `PorSaveState` is `NeutralSave`, and the Amiga wrappers still refuse an
# outdoor party
# ---------------------------------------------------------------------------

def test_por_save_state_is_neutral_save():
    from goldbox import amiga

    assert amiga.PorSaveState is neutral_save.NeutralSave
