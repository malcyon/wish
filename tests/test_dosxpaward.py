from __future__ import annotations

"""The unnamed run before a DOS record's portrait is the experience award.

`#254 (Two DOS gaps the Amiga port gives a shape to: a 16-bit field in
gap_13c, and a pointer at the end of the Silver Blades item)`. Pool of
Radiance's `gap_0b8`, Curse's and Gateway's `gap_13c` and Silver Blades'
`gap_14e` are one field and a half: a `u16le` base award and a `u8` awarded
per hit point. Pools of Darkness and Treasures of the Savage Frontier keep the
base alone, at `0x198`.

The tests below pin three independent routes to that, each read out of the
shipped `GAME.OVR` or the shipped creature files rather than out of a save:

* the **script property dispatcher**, whose ids are C64 record offsets --
  `0x0BB` copper through `0x0C5` gems, `0x119` hit points current, and
  `0x0F7`/`0x0F9` for this pair, which `docs/80-fields-wanted.md` has as
  CONFIRMED on the C64;
* the **creature records** in `MON<n>CHA.DAX`, which read the published AD&D
  1st edition values at those offsets;
* the **player records** of the corpus, where the award is zero, because it
  is a monster's field.

They read the player's own archives through `tools/dosbox.find_game` and skip
cleanly without them; no game bytes are in this repository, and the synthetic
records here are built out of zeroes.
"""

import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from goldbox import dos_layout  # noqa: E402
from goldbox import layout as c64_layout  # noqa: E402
from tools import dosxpaward as xp  # noqa: E402

#: The offsets this issue named, per record size.  `None` is a title with no
#: per-hit-point rate.
OFFSETS = {285: (0x0B8, 0x0BA), 422: (0x13C, 0x13E),
           439: (0x14E, 0x150), 510: (0x198, None)}


def _record(size: int, name: str = "GOBLIN", base: int = 0,
            per_hp: int = 0, hp: int = 0) -> bytes:
    """A synthetic record with the award fields set and nothing else.

    Generated here rather than sliced out of a save, because a slice of a game
    file is the game's data under a new name (`AGENTS.md`).
    """
    data = bytearray(size)
    data[0] = len(name)
    data[1:1 + len(name)] = name.encode("ascii")
    base_off, rate_off = OFFSETS[size]
    struct.pack_into("<H", data, base_off, base)
    if rate_off is not None:
        data[rate_off] = per_hp
    fields = {f.name: f for f in dos_layout.layout_for(size)}
    data[fields["hp_rolled"].offset] = hp
    return bytes(data)


# --- the offsets, and where they come from -----------------------------------


@pytest.mark.parametrize("size,expected", sorted(OFFSETS.items()))
def test_the_award_offsets_are_the_run_before_the_portrait(size, expected):
    """`award_offsets` reads them off `goldbox/dos_layout.py` rather than
    carrying its own table, so naming the fields there moves the tool."""
    assert xp.award_offsets(size) == expected


def test_the_run_is_three_bytes_in_the_earlier_titles_and_two_in_the_later():
    """Two numbers in four engines, one in two -- which is what the arithmetic
    says: Pools of Darkness adds the base and never multiplies."""
    assert all(xp.award_offsets(size)[1] is not None
               for size in (285, 422, 439))
    assert xp.award_offsets(510)[1] is None


def test_the_award_is_the_base_plus_the_rate_times_the_hit_points():
    record = _record(439, "OGRE", base=90, per_hp=5, hp=21)
    assert xp.award(record) == 90 + 5 * 21


def test_the_later_titles_award_is_the_base_alone():
    record = _record(510, "BULETTE", base=2792, hp=41)
    assert xp.award(record) == 2792


def test_the_hit_points_can_be_given_rather_than_read():
    """The engine multiplies by what the creature rolled, and a caller
    reading a live monster has that to hand."""
    record = _record(422, "OGRE", base=90, per_hp=5, hp=21)
    assert xp.award(record, hp=1) == 95


# --- the engines themselves --------------------------------------------------


def _overlay(stem: str) -> bytes:
    try:
        path = xp.find_game(stem) / "GAME.OVR"
    except FileNotFoundError:
        pytest.skip(f"needs the DOS {stem} archive; set FR_ARCHIVES")
    if not path.is_file():
        pytest.skip(f"no GAME.OVR beside DOS {stem}")
    return path.read_bytes()


#: The four engines whose dispatcher this pattern matches.  Pools of Darkness
#: and Treasures of the Savage Frontier match nothing, which is a fact about
#: the pattern and not about their record -- their award is at `0x198` and the
#: creature files prove it.
DISPATCHED = pytest.mark.parametrize(
    "stem", ["POOLRAD", "CURSE", "GATEWAY", "SECRET"])


@DISPATCHED
def test_the_dispatcher_points_the_two_ids_at_the_award_pair(stem):
    """`0x0F7` a word and `0x0F9` a byte, at the offsets this issue named."""
    sites = {ident: (disp, width)
             for _, ident, disp, width in xp.setter_sites(_overlay(stem))}
    base_off, rate_off = xp.award_offsets(xp.GAMES[stem])
    assert sites[xp.PROPERTY_AWARD] == (base_off, 2)
    assert sites[xp.PROPERTY_PER_HP] == (rate_off, 1)


@DISPATCHED
def test_every_dispatcher_id_that_names_a_c64_field_agrees_with_it(stem):
    """The corroboration the naming rests on: an id is a C64 record offset.

    Where the C64 field table has a field starting at the id, the DOS offset
    the arm writes is the field of the same name -- copper, silver, electrum,
    gold, platinum, gems, hit points current. There is no counter-example in
    any of the four, and the only ids that land in a C64 gap are `0x0F7` and
    `0x0F9`. **Gateway to the Savage Frontier has only those two arms**, which
    is why the count is asserted across the family below rather than here.
    """
    c64 = {f.offset: f for f in c64_layout.LAYOUT}
    ours = {f.offset: f for f in dos_layout.layout_for(xp.GAMES[stem])}
    for _, ident, disp, _ in xp.setter_sites(_overlay(stem)):
        theirs = c64.get(ident)
        if theirs is None or theirs.name.startswith("gap_"):
            assert ident in (xp.PROPERTY_AWARD, xp.PROPERTY_PER_HP)
            continue
        assert ours[disp].name == theirs.name, f"id {ident:#x} in {stem}"


def test_the_family_agrees_on_all_seventeen_of_them():
    """The sample size behind the sentence above: 17 arms whose id is a named
    C64 field, over four engines -- five in Pool of Radiance, five in Curse,
    seven in Silver Blades and none in Gateway -- and every one lands on the
    DOS field of that name."""
    c64 = {f.offset: f for f in c64_layout.LAYOUT}
    agreed = 0
    for stem in ("POOLRAD", "CURSE", "GATEWAY", "SECRET"):
        ours = {f.offset: f for f in dos_layout.layout_for(xp.GAMES[stem])}
        for _, ident, disp, _ in xp.setter_sites(_overlay(stem)):
            theirs = c64.get(ident)
            if theirs is None or theirs.name.startswith("gap_"):
                continue
            assert ours[disp].name == theirs.name
            agreed += 1
    assert agreed >= 17


def test_the_shipped_creatures_carry_the_published_values():
    """DOS Pool of Radiance's own `MON1CHA.DAX`, at the offsets above.

    GOBLIN GUARD 10 and 1, HOBGOBLIN 20 and 2, OGRE 90 and 5 -- the numbers
    `docs/80-fields-wanted.md` read off the C64 records, and AD&D 1st
    edition's own table. Three numbers with their provenance is a
    measurement rather than the game's data (`.claude/rules/conversions.md`).
    """
    try:
        game = xp.find_game("POOLRAD")
    except FileNotFoundError:
        pytest.skip("needs the DOS POOLRAD archive; set FR_ARCHIVES")
    rows = {name: (base, rate)
            for _, _, name, base, rate, _ in xp.monsters(game, 285)}
    assert rows["GOBLIN GUARD"] == (10, 1)
    assert rows["HOBGOBLIN"] == (20, 2)
    assert rows["OGRE"] == (90, 5)


def test_almost_every_creature_record_carries_an_award():
    """The positive control for the offsets: a field that is zero in every
    player and set in nearly every monster is not a field we have misplaced.

    Not *every* one: the named characters a script drops into a fight --
    Silver Blades' SIEGLINDA, CAPET and AVEROES -- read zero, which is what a
    creature you are not paid for looks like.
    """
    try:
        game = xp.find_game("SECRET")
    except FileNotFoundError:
        pytest.skip("needs the DOS SECRET archive; set FR_ARCHIVES")
    rows = list(xp.monsters(game, 439))
    assert len(rows) >= 40
    paid = [r for r in rows if r[3]]
    assert len(paid) >= 0.9 * len(rows)


def test_a_player_record_never_carries_one():
    """Every Pool of Radiance record the archives ship reads zero.

    Provenance: these are a download and nobody watched them being written
    (`.claude/rules/testing.md`), which is why this is stated as "the field is
    a creature's" rather than as anything about a particular party.
    """
    try:
        game = xp.find_game("POOLRAD")
    except FileNotFoundError:
        pytest.skip("needs the DOS POOLRAD archive; set FR_ARCHIVES")
    shipped = game.parent.parent / "Default files" / "Saves"
    if not shipped.is_dir():
        pytest.skip(f"no {shipped}")
    records = list(xp.records_under(shipped))
    assert len(records) >= 10
    for path, data in records:
        base_off, rate_off = xp.award_offsets(len(data))
        assert struct.unpack_from("<H", data, base_off)[0] == 0, path
        assert rate_off is None or data[rate_off] == 0, path
