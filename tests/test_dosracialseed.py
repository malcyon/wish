"""`tools/dosracialseed.py`: what DOS Pool of Radiance's engine says 97 is.

`#247 (Nobody knows whether innate effect 97 is racial or the constitution
bonus)` could not be settled by a specimen, because every race that carries
97 also earns a constitution bonus.  It was settled by reading the engine:
creation pushes 97 on the race byte alone, and the handler for 97 reads the
character's constitution at the moment a saving throw is rolled
(`docs/189-effect-97-from-the-code.md`).

The synthetic test pins the reader's grammar with no game data.  The rest
read the player's own `GAME.OVR` and `START.EXE` out of the archives through
`tools.dosbox.find_game`, and skip without them -- `goldbox.dos`'s race table
is checked against the engine's creation switch, and `goldbox.levels`'s
constitution rule against the handler's band table.
"""

import pathlib
import struct
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

#: `tools/dosracialseed.py` disassembles the overlay, so it imports capstone at
#: module level -- and capstone is not installed on the CI runners, where this
#: file failed on all four jobs with `ModuleNotFoundError: No module named
#: 'capstone'` while passing here.  `tests/test_amiga68k.py` guards the same
#: dependency the same way.
pytest.importorskip("capstone")

from goldbox import dos, levels  # noqa: E402
from tools import dosracialseed  # noqa: E402

INNATE = bytes((0x31, 0xC0, 0x50,          # xor ax, ax / push ax   (duration 0)
                0xB0, 0xFF, 0x50,          # mov al, 0xff / push ax (data)
                0xB0, 0x00, 0x50))         # mov al, 0 / push ax    (flag)


def _call(eid: int) -> bytes:
    return bytes((0xB0, eid, 0x50)) + INNATE + dosracialseed.ADD_AFFECT


def _switch(branches: dict[int, list[int]]) -> bytes:
    """A creation switch in the engine's own shape, for the races given."""
    bodies = [(race, b"".join(_call(e) for e in ids))
              for race, ids in branches.items()]
    out = bytearray(dosracialseed.RACE_READ)
    # each branch: cmp al, race / jne next / calls / jmp join
    sizes = [2 + 2 + len(body) + 3 for _, body in bodies]
    join = len(out) + sum(sizes) + 2                       # past a final nop
    for (race, body), size in zip(bodies, sizes):
        out += bytes((0x3C, race, 0x75, size - 4))
        out += body
        rel = join - (len(out) + 3)
        out += b"\xe9" + struct.pack("<h", rel)
    out += b"\x90\x90"
    return bytes(out)


def test_the_reader_walks_a_switch_of_the_engines_shape():
    """Six calls over two branches, read back per race and per argument."""
    blob = b"\x00" * 16 + _switch({5: [90, 97], 1: [90, 97, 26, 47]}) + b"\x00" * 16
    assert dosracialseed.creation_switch(blob) == 16
    assert dosracialseed.creation_table(blob) == {
        5: [(90, 0, 0xFF, 0), (97, 0, 0xFF, 0)],
        1: [(90, 0, 0xFF, 0), (97, 0, 0xFF, 0), (26, 0, 0xFF, 0), (47, 0, 0xFF, 0)],
    }


def test_a_race_read_that_is_not_the_switch_is_passed_over():
    """A race read that indexes a table has no `cmp al` after it and no
    `add_affect` calls near it; the reader must not stop there."""
    decoy = dosracialseed.RACE_READ + b"\x98\x8b\xf8"      # cwde / mov di, ax
    blob = decoy + b"\x00" * 64 + _switch({3: [97, 18, 47, 48], 5: [90, 97]})
    assert dosracialseed.creation_switch(blob) == len(decoy) + 64
    assert dosracialseed.creation_table(blob)[3] == [
        (97, 0, 0xFF, 0), (18, 0, 0xFF, 0), (47, 0, 0xFF, 0), (48, 0, 0xFF, 0)]


# --- the engine itself --------------------------------------------------------


@pytest.fixture(scope="module")
def engine():
    """`GAME.OVR` and the expanded `START.EXE` from the player's archives."""
    from tools import dosbox, unexepack
    try:
        game = dosbox.find_game()
    except FileNotFoundError:
        pytest.skip("needs DOS Pool of Radiance in the archives; set FR_ARCHIVES")
    ovr = (game / "GAME.OVR").read_bytes()
    image, _ = unexepack.unpack((game / "START.EXE").read_bytes())
    return ovr, image


def test_creation_writes_every_racial_id_by_race_alone(engine):
    """The switch on record `0x2E`, read out of the player's own overlay.

    Five races get a branch, each call is `(id, 0, 0xFF, 0)` --
    `INNATE_PAYLOAD` -- and the sturdy rows are `RACE_COMBAT_EFFECTS` to the
    id and the order.  The set of ids is `INNATE_EFFECTS` exactly.
    """
    ovr, _ = engine
    table = dosracialseed.creation_table(ovr)
    assert sorted(table) == [1, 2, 3, 4, 5]
    for calls in table.values():
        for _eid, duration, data, flag in calls:
            assert (duration, data, flag) == (0, 0xFF, 0)
    ids = {race: tuple(c[0] for c in calls) for race, calls in table.items()}
    assert ids[2] == (107,) and ids[4] == (124,)
    for race, name in ((1, "dwarf"), (3, "gnome"), (5, "halfling")):
        assert ids[race] == dos.RACE_COMBAT_EFFECTS[name], name
    assert {e for row in ids.values() for e in row} == set(dos.INNATE_EFFECTS)


def test_97_adds_the_constitution_band_on_the_wand_and_spell_columns(engine):
    """The handler 97 dispatches to reads constitution when the throw is
    rolled and adds the band to the roll, on save types 2 and 4 only; 90 is
    the same table on type 0.  The bands are `constitution_save_bonus`."""
    ovr, image = engine
    read = dosracialseed.handlers(ovr, image, (90, 97))
    assert sorted(read[97]["save_types"]) == [2, 4]
    assert read[90]["save_types"] == [0]
    for eid in (90, 97):
        h = read[eid]
        assert h["reads_constitution"] and h["adds_to_roll"], eid
        assert h["bands"] == [(4, 6, 1), (7, 10, 2), (11, 13, 3), (14, 17, 4), (18, 20, 5)]
        for con in range(3, 21):
            band = next((b for lo, hi, b in h["bands"] if lo <= con <= hi), 0)
            assert band == levels.constitution_save_bonus(con), (eid, con)
