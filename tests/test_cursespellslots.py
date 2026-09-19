from __future__ import annotations

"""`#547 (A C64-to-DOS Curse resave writes a thief's base skills and a mage's/
cleric's spell slots wrong, silently repaired by the engine's own next load)`,
the spell-slot half only -- the thief-skill half is `#440 (A Curse thief
converted between DOS and the C64 arrives seven points off, because DOS
stores a stack leftover in all eight skill columns)` working as built, and no
thief-skill code changes here.

`goldbox.c64_codec`'s reader unpacks `spells_castable` off the C64 record at
`0x0EE` for every title, even though Curse and Silver Blades never write those
bytes -- `goldbox.levels.LevelTables.stores_spell_capacity` is `False` for
both.  A C64 Curse source therefore reaches `goldbox.dos_codec.write` holding
three all-zero tuples per class, and a straight copy put those zeros into the
DOS record.  `goldbox.spells.capacity_by_class` is the game's own table,
already in the tree for a single-class character as `capacity`, widened to
take a level per class so a multi-class source's magic-user row is not read
at its overall level.

Everything below that reads a DOS record reads the player's own files at run
time -- the specimen tree and the DOS archives, the same two places
`tools/laterthac0.py`'s own `records()` walks -- and skips cleanly on a
machine that has neither.  No game bytes are committed.
"""

import glob
import os
import pathlib

import pytest

from goldbox import dos_codec, levels, neutral, spells
from goldbox.dos_codec import _ability_pair
from tools import dosbox

CURSE = "curse-of-the-azure-bonds"
SSB = "secret-of-the-silver-blades"
POOL = "pool-of-radiance"

_ZERO_SLOTS = {"cleric": (0, 0, 0), "magic-user": (0, 0, 0)}


def _c64_curse(levels: dict, wisdom: int, game: str = CURSE,
               castable: dict | None = None) -> neutral.NeutralCharacter:
    """A C64-read neutral Curse or Silver Blades caster, holding the C64's
    own `spells_castable` -- three all-zero tuples per class by default,
    which is what `goldbox.c64_codec`'s reader hands back for a title whose
    C64 engine never writes those bytes (`stores_spell_capacity=False`)."""
    char = neutral.NeutralCharacter("C64", game=game)
    char.set("levels", levels, "test fixture")
    char.set("wisdom", wisdom, "test fixture")
    char.set("spells_castable", castable or _ZERO_SLOTS,
             "test fixture: the C64's own reading, all zeros for a title "
             "that never stores this")
    return char


def _written(char: neutral.NeutralCharacter, game: str = CURSE
            ) -> dos_codec.DosCharacter:
    rec, _, _, _ = dos_codec.write(char)
    return dos_codec.DosCharacter(rec, deltas=game)


# --- the writer -----------------------------------------------------------

def test_a_c64_curse_magic_user_gets_the_table_row_not_the_c64_zeros():
    """PHILIPPE's own numbers from the issue: magic-user 5, wisdom 14."""
    dos = _written(_c64_curse({"magic-user": 5}, 14))
    assert tuple(dos.raw("spells_castable_magic_user")) == (4, 2, 1, 0, 0)
    # The cleric array is untouched -- no cleric level, so the source's own
    # (zero) bytes are kept rather than a row invented for a class the
    # character does not hold.
    assert tuple(dos.raw("spells_castable_cleric")) == (0, 0, 0, 0, 0)


def test_a_c64_curse_cleric_gets_the_table_row_with_its_wisdom_bonus():
    """SHARA's own numbers: cleric 5, wisdom 17 -- the wisdom bonus lands on
    the first two spell levels only, the one the base row does not reach."""
    dos = _written(_c64_curse({"cleric": 5}, 17))
    assert tuple(dos.raw("spells_castable_cleric")) == (5, 5, 2, 0, 0)
    assert tuple(dos.raw("spells_castable_magic_user")) == (0, 0, 0, 0, 0)


def test_a_c64_curse_fighter_gets_no_spell_slots():
    """A class the table has no row for keeps the C64's own (zero) bytes --
    `capacity_by_class` has nothing to offer, and the fallback is a copy."""
    dos = _written(_c64_curse({"fighter": 5}, 10))
    assert tuple(dos.raw("spells_castable_cleric")) == (0, 0, 0, 0, 0)
    assert tuple(dos.raw("spells_castable_magic_user")) == (0, 0, 0, 0, 0)


def test_an_amiga_curse_source_keeps_its_own_array():
    """`_SPELL_SLOT_RECOMPUTE_FROM_PORTS` names the C64 alone -- an Amiga
    source's own array is real (fifteen of fifteen Amiga Curse records this
    project has read hold the table row), so it is copied rather than
    recomputed.  This is what goes wrong if the gate is ever widened."""
    char = neutral.NeutralCharacter("Amiga", game=CURSE)
    char.set("levels", {"magic-user": 5}, "test fixture")
    char.set("wisdom", 14, "test fixture")
    char.set("spells_castable", {"cleric": (9, 9, 9), "magic-user": (7, 6, 5)},
             "test fixture: an Amiga source's own, real, array")
    dos = _written(char)
    assert tuple(dos.raw("spells_castable_cleric")) == (9, 9, 9, 0, 0)
    assert tuple(dos.raw("spells_castable_magic_user")) == (7, 6, 5, 0, 0)


def test_a_silver_blades_c64_source_still_writes_zeros():
    """Silver Blades' own C64 engine never stores this either
    (`stores_spell_capacity=False`), but `goldbox.spells._SLOTS` has no rows
    for it -- #31, #81 -- so the writer invents nothing and the zeros pass
    through unchanged, the same as before this fix."""
    dos = _written(_c64_curse({"magic-user": 5}, 14, game=SSB), game=SSB)
    assert tuple(dos.raw("spells_castable_cleric")) == (0,) * 7
    assert tuple(dos.raw("spells_castable_magic_user")) == (0,) * 7


def test_pool_of_radiance_is_untouched():
    """Pool of Radiance's own C64 engine does store the field
    (`stores_spell_capacity=True`), so the gate never applies and the
    source's own bytes are written exactly as before."""
    char = neutral.NeutralCharacter("C64", game=POOL)
    char.set("levels", {"magic-user": 5}, "test fixture")
    char.set("wisdom", 14, "test fixture")
    char.set("spells_castable", {"cleric": (0, 0, 0), "magic-user": (4, 3, 2)},
             "test fixture: a real C64 Pool of Radiance array")
    dos = _written(char, game=POOL)
    assert tuple(dos.raw("spells_castable_magic_user")) == (4, 3, 2)
    assert tuple(dos.raw("spells_castable_cleric")) == (0, 0, 0)


# --- the paladin and the ranger, #548 ---------------------------------------
# A Curse paladin casts cleric spells from level 9 and a ranger gets druid
# spells at 8 and magic-user spells at 9.  Neither holds a cleric or a
# magic-user level, so before this each arrived on the Amiga with all three
# arrays zero and stayed that way for ever -- the Amiga engine does not
# rebuild the block, measured on
# `WISH-SPEC-curse-c64toamiga-slotb-walked-saved-c`.
#
# The numbers are `GAME.OVR:0x3AC81`'s own, read a second time by
# `test_the_four_delta_tables_are_the_games_own` below.

@pytest.mark.parametrize("level,cleric", [
    (8, (0, 0, 0, 0, 0)),
    (9, (1, 0, 0, 0, 0)),
    (10, (2, 0, 0, 0, 0)),
    (11, (2, 1, 0, 0, 0)),
])
def test_a_c64_curse_paladin_gets_his_cleric_slots(level, cleric):
    """The paladin's rows go in the **cleric** array -- he has no array of
    his own, and `GAME.OVR:0x3ADF9` adds `DS:43E5` into `record[0x12C + s]`,
    the same five bytes the cleric branch fills."""
    dos = _written(_c64_curse({"paladin": level}, 10))
    assert tuple(dos.raw("spells_castable_cleric")) == cleric
    assert tuple(dos.raw("spells_castable_magic_user")) == (0, 0, 0, 0, 0)
    assert tuple(dos.raw("spells_castable_druid")) == (0, 0, 0, 0, 0)


def test_a_curse_paladin_gets_no_wisdom_bonus_spells():
    """The case a plausible implementation gets wrong.

    The bonus is `GAME.OVR:0x3B2E6` and the **cleric** branch is the only
    branch that calls it (`0x3AD4E`, flag argument zero); the paladin branch
    falls straight through to its spellbook grant.  So a paladin of 11 with
    Wisdom 18 holds `2 1 0 0 0` and not `4 3 0 0 0`.  The C64 agrees:
    `ECL65 $88F6` opens `LDA $7CCA / BEQ`, and `$7CCA` is the **cleric**
    class-level slot.
    """
    dos = _written(_c64_curse({"paladin": 11}, 18))
    assert tuple(dos.raw("spells_castable_cleric")) == (2, 1, 0, 0, 0)


@pytest.mark.parametrize("level,druid,magic_user", [
    (7, (0, 0, 0, 0, 0), (0, 0, 0, 0, 0)),
    (8, (1, 0, 0, 0, 0), (0, 0, 0, 0, 0)),
    (9, (1, 0, 0, 0, 0), (1, 0, 0, 0, 0)),
    (10, (2, 0, 0, 0, 0), (1, 0, 0, 0, 0)),
    (11, (2, 0, 0, 0, 0), (2, 0, 0, 0, 0)),
])
def test_a_c64_curse_ranger_fills_two_arrays(level, druid, magic_user):
    """One class level, two arrays.  `GAME.OVR:0x3AEB4` adds columns 1-3 of
    `DS:4448` into `record[0x131 + s]` -- the druid array, which is where a
    **ranger's** druid spells live, Curse having no druid class at all --
    and `0x3AEF5` adds columns 4-5 into `record[0x136 + s - 3]`, the first
    two levels of the magic-user array.
    """
    dos = _written(_c64_curse({"ranger": level}, 10))
    assert tuple(dos.raw("spells_castable_druid")) == druid
    assert tuple(dos.raw("spells_castable_magic_user")) == magic_user
    assert tuple(dos.raw("spells_castable_cleric")) == (0, 0, 0, 0, 0)


def test_a_ranger_who_is_also_a_magic_user_gets_both_runs_added():
    """Curse has no ranger/magic-user combination, so this pins the rule
    rather than a character: the builder walks all eight class slots and
    `add`s each one's rows into the arrays, so two contributions to the same
    array sum.  A writer that assigned instead of adding would lose one.
    """
    dos = _written(_c64_curse({"ranger": 11, "magic-user": 3}, 10))
    # magic-user 3 is `2 1 0 0 0`, the ranger adds `2 0 0 0 0` at level 11.
    assert tuple(dos.raw("spells_castable_magic_user")) == (4, 1, 0, 0, 0)
    assert tuple(dos.raw("spells_castable_druid")) == (2, 0, 0, 0, 0)


def test_a_curse_character_never_holds_a_druid_level():
    """A third of `#548`'s title is moot: **Curse has no druid class.**

    `goldbox.classcode.CLASS_CODE_TABLE` is Curse's own `GEN $1951` and
    gives class code 1, the druid, a bitmask of zero, so no record can carry
    the class.  The slot builder says it from the other side: its class loop
    branches on 0, 3, 4 and 5 and on nothing else, so a druid level would
    add no rows even if one could exist.  The writer must therefore invent
    nothing for a `"druid"` class level.
    """
    from goldbox import classcode
    assert classcode.CLASS_CODE_TABLE[1] == 0x00
    assert spells.capacity_by_class({"druid": 9}, 18, CURSE) == {}


def test_silver_blades_gets_no_paladin_or_ranger_row_either():
    """`_SLOTS` still has no Silver Blades entry at all (#31, #81), and a
    title with no rows must invent none for these two classes any more than
    for the other two."""
    assert spells.capacity_by_class({"paladin": 11, "ranger": 11}, 18, SSB) == {}


def test_pool_of_radiance_has_no_paladin_or_ranger_rows():
    """Pool of Radiance has neither class -- `goldbox.classcode`'s own
    comment says so -- so its `_SLOTS` entry keeps exactly the two tables it
    had and a caller asking for either gets nothing."""
    assert spells.capacity_by_class({"paladin": 11, "ranger": 11}, 18, POOL) == {}


# --- the four tables, read back off the player's own image ------------------
# The half of `#548` a hardcoded table cannot do for itself.  `goldbox/
# spells.py` holds four rows tables and this reads all four out of the DOS
# Curse `GAME.OVR` and `START.EXE` the player owns, the same way
# `tests/test_levels.py` re-reads the THAC0 rows, so a transcription slip
# fails here rather than shipping.
#
# **Nothing is located by a committed address.**  `builder_site` picks the one
# `add di, 0x12D` site that carries a class loop out of the three
# `dosspellslots.py sites` prints, `builder_classes` reads each branch's class
# number, first level, base and table offsets off the instructions, and
# `data_segment` resolves `DS` off the System unit's own start-up.  The one
# thing the test supplies is each class's **ceiling**, which is the title's
# rule rather than the builder's and comes from `goldbox.levels`.

#: `(class-slot number, the array it lands in, the committed rows, the
#: title's ceiling)`.  The class numbers are `goldbox.dos_codec.
#: CLASS_LEVEL_SLOTS`': 0 cleric, 3 paladin, 4 ranger, 5 magic-user.
_TABLES = (
    (0, "cleric", spells._CLERIC_CURSE, 10),
    (5, "magic-user", spells._MAGIC_USER_CURSE, 11),
    (3, "cleric", spells._PALADIN_CURSE, 11),
)


def _curse_image():
    """`(GAME.OVR, the expanded START.EXE image)` for DOS Curse, or a skip."""
    dosspellslots = pytest.importorskip("tools.dosspellslots")
    try:
        game = dosbox.find_game("CURSE")
    except FileNotFoundError as exc:
        pytest.skip(f"needs the player's DOS Curse archives: {exc}")
    return dosspellslots, ((game / "GAME.OVR").read_bytes(),
                           dosspellslots.image_of(game, None))


def _read_tables():
    """Every class branch's cumulative rows, off the player's own image."""
    dosspellslots, (ovr, image) = _curse_image()
    block, width = dosspellslots.block_of(422)
    assert (block, width) == (0x12D, 5), "Curse's slot block moved"
    return dosspellslots.slot_tables(
        ovr, image, block, width,
        {number: ceiling for number, _, _, ceiling in _TABLES} | {4: 11})


@pytest.mark.parametrize("number,array,committed,ceiling", _TABLES)
def test_the_four_delta_tables_are_the_games_own(number, array, committed,
                                                 ceiling):
    """Accumulating the builder's own delta table reproduces the rows in
    `goldbox/spells.py`, for the cleric, the magic-user and the paladin.

    The cleric and the magic-user are the corroboration that makes the
    paladin's and the ranger's safe to take from DOS: those two rows tables
    were read off the C64's `ECL65` payload `0x88D`, which stores the same
    progression as running totals rather than as deltas, and the DOS image
    reproduces both row for row -- 10 of 10 cleric levels and 11 of 11
    magic-user levels, no exceptions.
    """
    read = _read_tables()[number][array]
    assert len(committed) == ceiling
    assert [tuple(row) for row in committed] == read[:ceiling]


def test_the_rangers_one_table_fills_two_arrays():
    """The ranger's `DS:4448` is one table read twice: columns 1-3 into the
    druid array and columns 4-5 into the first two levels of the magic-user
    array, which is why `_RANGER_CURSE` carries a pair per level."""
    read = _read_tables()[4]
    assert set(read) == {"druid", "magic-user"}
    for level, (druid, magic_user) in enumerate(spells._RANGER_CURSE, start=1):
        assert read["druid"][level - 1] == druid, level
        assert read["magic-user"][level - 1] == magic_user, level


def test_the_builder_has_no_druid_branch():
    """Read from the other side: Curse's slot builder branches on class 0,
    3, 4 and 5 and on nothing else, so class 1 -- the druid -- gets no slots
    even if a record could carry the class, which
    `goldbox.classcode.CLASS_CODE_TABLE` says it cannot."""
    dosspellslots, (ovr, _) = _curse_image()
    site = dosspellslots.builder_site(ovr, 0x12D)
    classes = dosspellslots.builder_classes(ovr, site)
    assert sorted(c.number for c in classes) == [0, 3, 4, 5]


def test_the_paladin_and_ranger_thresholds_are_the_builders_own():
    """A paladin's rows start at 9 and a ranger's at 8 -- AD&D 1st edition's
    thresholds, and the same two `goldbox.spells.CURSE_OF_THE_AZURE_BONDS`
    already records as `paladin_cleric_level` and `ranger_spell_level` off
    the C64's `GEN $22FF` and `$2305`."""
    dosspellslots, (ovr, _) = _curse_image()
    site = dosspellslots.builder_site(ovr, 0x12D)
    starts = {c.number: c.from_level
              for c in dosspellslots.builder_classes(ovr, site)}
    assert starts[3] == 9 and starts[4] == 8
    table = spells.CURSE_OF_THE_AZURE_BONDS
    assert table.paladin_cleric_level[0][0] == starts[3]
    assert table.ranger_spell_level[0][0] == starts[4]


def test_the_wisdom_bonus_reads_the_score_in_force_not_the_permanent_one():
    """`#547`'s own open question, settled: the two agree already.

    The DOS builder's Wisdom bonus, `GAME.OVR:0x3B3A7`, is six compares
    against `record[0x15]` -- the **second** of the two wisdom bytes, which
    `goldbox.dos_codec._ability_pair` and `docs/204-the-dos-ability-pair.md`
    call the score *in force*.  The neutral record's `wisdom` is the score in
    force too (`abilities_second` carries the permanent one), and
    `_pair_bytes` writes it to `0x15`.  So the byte the writer computes from
    and the byte the engine computes from are the same byte.

    A drained cleric is where the two would diverge if they ever did, so the
    fixture sets them apart: permanent 18, in force 12.  The table gives
    wisdom 12 no bonus at all and wisdom 18 `(2, 2, 1, 1)`, so the base row
    coming back unchanged is the proof.
    """
    char = neutral.NeutralCharacter("C64", game=CURSE)
    char.set("levels", {"cleric": 5}, "test fixture")
    char.set("wisdom", 12, "test fixture: the score in force, drained")
    char.set("abilities_second", {"wisdom": 18},
             "test fixture: the permanent score")
    char.set("spells_castable", _ZERO_SLOTS, "test fixture")
    rec, _, _, _ = dos_codec.write(char)
    assert (rec[0x14], rec[0x15]) == (18, 12), "the pair is stored the other way"
    dos = dos_codec.DosCharacter(rec, deltas=CURSE)
    assert tuple(dos.raw("spells_castable_cleric")) == (3, 3, 1, 0, 0)
    assert tuple(spells._CLERIC_CURSE[4]) == (3, 3, 1, 0, 0)


def test_the_wisdom_bonus_compares_are_the_games_own():
    """Six compares against `record[0x15]`, and each one only where the base
    row already reaches that spell level.

    The bonus lands on `0x12D` twice (above 12 and above 13), `0x12E` twice
    (above 14 and 15), `0x12F` once (above 16) and `0x130` once (above 17),
    which is `goldbox.levels.wisdom_bonus_spells` exactly -- including the
    fourth-level bonus at 18 that an earlier note of this routine missed.
    """
    dosspellslots, (ovr, _) = _curse_image()
    import re
    import struct
    # `cmp byte ptr es:[di + 0x15], imm8 / jbe` then `cmp byte ptr es:[di +
    # imm16], 0 / jbe` then `inc byte ptr es:[di + imm16]`.
    pattern = (rb"\x26\x80\x7d\x15(.)\x76.\xc4\x7e\xf9\x26\x80\xbd(..)\x00"
               rb"\x76.\xc4\x7e\xf9\x26\xfe\x85(..)")
    found = [(m.group(1)[0], struct.unpack("<H", m.group(3))[0])
             for m in re.finditer(pattern, ovr, re.S)]
    assert len(found) == 6, f"expected six compares, got {found}"
    column = {}
    for score, at in found:
        column.setdefault(at - 0x12D, []).append(score)
    assert column == {0: [12, 13], 1: [14, 15], 2: [16], 3: [17]}
    for score, bonus in ((12, (0, 0, 0, 0, 0)), (13, (1, 0, 0, 0, 0)),
                         (15, (2, 1, 0, 0, 0)), (17, (2, 2, 1, 0, 0)),
                         (18, (2, 2, 1, 1, 0))):
        assert levels.wisdom_bonus_spells(score, CURSE) == bonus, score


def test_only_the_cleric_and_the_magic_user_get_a_level_one_slot():
    """`inc byte ptr es:[di + imm16]` before the row loop is the level-1
    base, and only two branches have one -- which is why a paladin 8 and a
    ranger 7 hold nothing rather than one slot each."""
    dosspellslots, (ovr, _) = _curse_image()
    site = dosspellslots.builder_site(ovr, 0x12D)
    bases = {c.number: c.base
             for c in dosspellslots.builder_classes(ovr, site)}
    assert bases == {0: 0x12D, 3: None, 4: None, 5: 0x137}


# --- the C64's own paladin and ranger, off the player's own disks ------------
# `#548`'s plan suggested a byte search of the C64 files for the DOS delta
# rows, to settle whether the C64 carries the same numbers.  **It does not
# carry them as a table at all**: the search finds nothing (the only hits for
# `1 0 0 0 0 / 2 0 0 0 0 / 2 1 0 0 0` anywhere on six Curse sides are `ECL65`
# `0x88D` and `0x8C4`, which are the first three rows of the magic-user and
# cleric tables -- both progressions open that way).  The C64 computes both
# classes arithmetically instead, in `ECL65` right after it copies the other
# two out of their tables, and these read that arithmetic off the disk.
#
# The block it builds is fifteen bytes at `$2BB6`, cleared by `$880D`, and the
# order is the C64's rather than the record's: `$2BB6` magic-user, `$2BBB`
# cleric, `$2BC0` druid.  Which is which is not assumed -- the two table
# copies name them, `$7CC9` being `level_magic_user` and `$7CCA`
# `level_cleric` in `goldbox/layout.py`.

def _ecl65() -> bytes:
    """Curse's `ECL65` payload off whichever C64 side carries it, or a skip."""
    gamedata = pytest.importorskip("tests.gamedata")
    from goldbox.d64 import split_load_address
    for disk in gamedata.curse_disks():
        entry = disk.find(b"ECL65")
        if entry is not None:
            return split_load_address(disk.read_file(entry))[1]
    pytest.skip("needs the player's C64 Curse disks")


def _c64_arrays(payload: bytes) -> dict[str, int]:
    """`{class: the address of its array}`, off the two table copies.

    Each is `LDX <level field> / BEQ / DEX / LDA #5 / JSR <multiply> /
    LDY #0 / TAX / LDA <table>,X / STA <array>,Y`, and the level field it
    reads is what names the array.
    """
    import re
    import struct
    out = {}
    pattern = (rb"\xae(..)\xf0.\xca\xa9\x05\x20..\xa0\x00\xaa\xbd..\x99(..)")
    for m in re.finditer(pattern, payload, re.S):
        level_field = struct.unpack("<H", m.group(1))[0]
        name = {0x7CC9: "magic-user", 0x7CCA: "cleric"}.get(level_field)
        if name:
            out[name] = struct.unpack("<H", m.group(2))[0]
    return out


def test_the_c64_paladin_reaches_the_same_three_rows():
    """No table on the C64 -- three compares instead, and the same answer.

    `LDA $7CCF` (`level_paladin`) / `LDX #$01` / `CMP #$09 / BCC` out /
    `CMP #$0A / BCC` / `INX` / `CMP #$0B / BCC` / `INC` the second-level
    slot, then `TXA / CLC / ADC` the first.  So 9 gives one first-level slot,
    10 two, and 11 two and a second-level one -- `_PALADIN_CURSE` exactly,
    and into the **cleric** array, which the two table copies name.
    """
    import re
    import struct
    payload = _ecl65()
    m = re.search(rb"\xad\xcf\x7c\xa2(.)\xc9(.)\x90.\xc9(.)\x90.\xe8"
                  rb"\xc9(.)\x90.\xee(..)\x8a\x18\x6d(..)\x8d(..)",
                  payload, re.S)
    assert m is not None, "ECL65 no longer computes the paladin's slots here"
    start, first, second, third = (m.group(i)[0] for i in range(1, 5))
    level_two, level_one, store = (struct.unpack("<H", m.group(i))[0]
                                   for i in (5, 6, 7))
    assert level_one == store, "the ADC and the STA disagree"
    assert _c64_arrays(payload)["cleric"] == level_one, \
        "the paladin's slots do not land in the cleric array"
    assert level_two == level_one + 1, "the second-level slot is not the next byte"
    rows = []
    for level in range(1, 12):
        row = [0, 0, 0, 0, 0]
        if level >= first:
            row[0] = start + (1 if level >= second else 0)
            row[1] = 1 if level >= third else 0
        rows.append(tuple(row))
    assert rows == [tuple(r) for r in spells._PALADIN_CURSE]


def test_the_c64_ranger_stops_one_short_of_the_dos_table_at_eleven():
    """The one place the two ports disagree, and it is the C64 that is odd.

    `LDX #$00 / LDY #$00 / LDA $7CD0` (`level_ranger`) / `CMP #$08 / BCC`
    out / `INX` / `CMP #$09 / BCC` store / `BEQ` past the second `INX` /
    `INX` / `INY` / `STX` the druid slot / `TYA / CLC / ADC` the magic-user
    one.  **`Y` is incremented once and never twice**, and there is no
    compare against 11 the way the paladin's has one -- so a C64 ranger 11
    is offered one first-level magic-user spell where DOS's `DS:4448` gives
    two, which is also what AD&D 1st edition gives.

    `_RANGER_CURSE` holds the DOS number, because the only thing that reads
    it writes a DOS-format record -- which the DOS engine rebuilds from
    `DS:4448` on load anyway, and which is what an Amiga record is built
    from. This asserts the C64's number rather than changing it, so the
    disagreement is recorded rather than quietly averaged away.
    """
    import re
    import struct
    payload = _ecl65()
    m = re.search(rb"\xa2\x00\xa0\x00\xad\xd0\x7c\xc9(.)\x90.\xe8\xc9(.)"
                  rb"\x90.\xf0\x01\xe8\xc8\x8e(..)\x98\x18\x6d(..)\x8d(..)",
                  payload, re.S)
    assert m is not None, "ECL65 no longer computes the ranger's slots here"
    druid_from, magic_user_from = m.group(1)[0], m.group(2)[0]
    druid_at, adc_at, store_at = (struct.unpack("<H", m.group(i))[0]
                                  for i in (3, 4, 5))
    assert adc_at == store_at
    assert _c64_arrays(payload)["magic-user"] == adc_at
    assert (druid_from, magic_user_from) == (8, 9)
    c64 = []
    for level in range(1, 12):
        if level < druid_from:
            c64.append((0, 0))
            continue
        x = 1 + (1 if level > magic_user_from else 0)
        y = 1 if level >= magic_user_from else 0
        c64.append((x, y))
    dos = [(d[0], m_[0]) for d, m_ in spells._RANGER_CURSE]
    assert c64[:10] == dos[:10], "the two ports agree below ranger 11"
    assert c64[10] == (2, 1) and dos[10] == (2, 2), \
        "the ranger-11 divergence has moved"


# --- the corpus sweep -------------------------------------------------------
# Modelled on `tests/test_laterthac0.py`: locate the field, compare against
# what `goldbox.spells.capacity_by_class` claims for that record's own class
# levels and wisdom, and count.  This reads DOS records already on disk --
# specimens this project's own writer produced before this fix, and records
# neither this fix nor any future one rewrites -- so the miss count is a
# property of the corpus, not of the code just changed.

#: `(agree, miss)` per title, measured 2026-09-15 against the specimen tree
#: and the DOS archives on this machine.  The corpus may only grow; a table
#: change or a newly read record that stops reproducing raises the miss
#: count, which is what this pins.
COUNTS = {
    CURSE: {"cleric": (16, 2), "magic-user": (29, 2)},
    POOL: {"cleric": (72, 2), "magic-user": (87, 0)},
}

#: The four known misses, all this project's own pre-fix output sitting in
#: the specimen tree -- `WISH-SPEC-curse-234-converted-party` and
#: `WISH-SPEC-curse-299-built-from-nothing`, each holding zeros where the
#: table gives LEDERA (magic-user 5, wisdom 15) `4 2 1 0 0` and SHARA
#: (cleric 6, wisdom 17) `5 5 3 0 0` -- and two Pool of Radiance
#: creation-time clerics, HALFE8 and HUMAN7, one point under the table at
#: wisdom 13 and 12 (#547's own "what I could not confirm": looks like the
#: wisdom bonus applied by the trainer and not at creation; not chased here).
KNOWN_MISSES = {
    (CURSE, "magic-user"): {"LEDERA"},
    (CURSE, "cleric"): {"SHARA"},
    (POOL, "cleric"): {"HALFE8", "HUMAN7"},
    (POOL, "magic-user"): set(),
}


def _dos_records(title: str):
    """Every DOS record of one title this machine has: the specimen tree
    and the DOS archives, the same two places `tools/laterthac0.py records`
    walks."""
    tree = pathlib.Path(os.environ.get(
        "WISH_SPECIMENS", pathlib.Path.home() / "wish-specimens"))
    files: list[str] = []
    for folder in sorted(tree.glob("*/WISH-SPEC-*")):
        files += glob.glob(str(folder) + "/CHRDAT*.SAV")
        files += glob.glob(str(folder) + "/*.CHA")
    if dosbox.ARCHIVES.is_dir():
        files += glob.glob(str(dosbox.ARCHIVES) + "/**/*.SAV", recursive=True)
        files += glob.glob(str(dosbox.ARCHIVES) + "/**/*.CHA", recursive=True)
    out = []
    for path in sorted(set(files)):
        try:
            char = dos_codec.read_character(path)
        except Exception:
            continue
        if char.deltas.key != title:
            continue
        out.append(char)
    return out


@pytest.mark.parametrize("title,school", [(CURSE, "cleric"),
                                          (CURSE, "magic-user"),
                                          (POOL, "cleric"),
                                          (POOL, "magic-user")])
def test_every_engine_written_record_reproduces_except_the_known_misses(
        title, school):
    """The finding itself: `capacity_by_class` gives what the engine's own
    resave holds, on every DOS record this machine has, except the four
    this project wrote before the fix and two Pool of Radiance oddities
    `#547` could not chase further.
    """
    if not dosbox.ARCHIVES.is_dir():
        # The counts below were measured over the specimen tree and the
        # archives together; the tree alone is a smaller corpus and would fail
        # them for lack of the archive's records, not for a wrong table.
        pytest.skip("needs the DOS archives as well as the specimen tree; "
                    "set FR_ARCHIVES or add dos-archives to gamedisks.yaml")
    records = _dos_records(title)
    if not records:
        pytest.skip(f"no DOS {title} records on this machine")

    field = f"spells_castable_{school.replace('-', '_')}"
    agree = miss = 0
    misses: set[str] = set()
    lines = []
    for char in records:
        level = char.class_levels.get(school)
        if not level:
            continue
        wisdom = _ability_pair(char, "wisdom")[0]
        want = spells.capacity_by_class(char.class_levels, wisdom, title)
        stored = tuple(char.raw(field))
        if want.get(school) == stored:
            agree += 1
        else:
            miss += 1
            misses.add(char.name)
            lines.append(f"{char.name}: stored={stored} "
                         f"want={want.get(school)} levels={char.class_levels} "
                         f"wisdom={wisdom}")

    total = agree + miss
    if not total:
        pytest.skip(f"no DOS {title} {school} caster on this machine")
    want_agree, want_miss = COUNTS[title][school]

    assert misses == KNOWN_MISSES[(title, school)], "\n".join(lines)
    assert total - agree == want_miss, "\n".join(lines)
    assert agree >= want_agree, (
        f"{agree} records reproduce, down from {want_agree} when this was "
        f"measured -- the corpus does not shrink\n" + "\n".join(lines))


#: The level each class starts casting at, and the array a record holds it
#: in.  Nothing on this machine reaches either: the highest Curse paladin
#: anywhere in the corpus is 6 and the highest ranger 5, which is the whole
#: reason `#548` had to be answered out of the engine rather than swept for.
_CASTS_FROM = {"paladin": (9, "cleric"), "ranger": (8, "druid")}


@pytest.mark.parametrize("class_name", ["paladin", "ranger"])
def test_every_engine_written_paladin_and_ranger_reproduces(class_name):
    """The sweep that cannot run yet, written so it starts the day it can.

    It **skips today**, and the skip message says why: the corpus tops out
    below the level either class casts from.  The moment a Curse paladin of
    9 or a ranger of 8 is played or converted into this machine's specimen
    tree, this asserts `goldbox.spells`' rows against what the DOS engine's
    own rebuild wrote, which is the check `test_the_four_delta_tables_are_
    the_games_own` cannot make: that reads the table, and this reads a
    record the engine filled from it.
    """
    from_level, array = _CASTS_FROM[class_name]
    records = _dos_records(CURSE)
    if not records:
        pytest.skip("no DOS Curse records on this machine")
    highest = max((c.class_levels.get(class_name) or 0) for c in records)
    casters = [c for c in records
               if (c.class_levels.get(class_name) or 0) >= from_level]
    if not casters:
        pytest.skip(
            f"no DOS Curse {class_name} of {from_level} or above on this "
            f"machine -- the highest anywhere in the corpus is {highest}, and "
            f"a {class_name} below {from_level} holds an all-zero array that "
            f"says nothing about the table")
    field = f"spells_castable_{array.replace('-', '_')}"
    lines = []
    for char in casters:
        wisdom = _ability_pair(char, "wisdom")[0]
        want = spells.capacity_by_class(char.class_levels, wisdom, CURSE)
        stored = tuple(char.raw(field))
        if want.get(array) != stored:
            lines.append(f"{char.name}: stored={stored} want={want.get(array)} "
                         f"levels={char.class_levels} wisdom={wisdom}")
    assert not lines, "\n".join(lines)
