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

from goldbox import dos_codec, neutral, spells
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
    and the DOS archives, the same two places `tools/laterthac0.py.records`
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
