"""The class code a converted DOS record carries.

`#310 (A trained C64 Curse character arrives in DOS with the wrong class on
his sheet)`.  The DOS sheet prints the class from `char_class`, and Curse of
the Azure Bonds' own C64 engine stops maintaining that byte the moment a
character is trained: `GEN $1939` computes the code, holds it in `X` and
stores `A`, which is zero on the matching path and the level he left his old
class at for a dual-classed one.  `docs/187-the-class-code-byte.md` has the
reading and the census.

So `goldbox.dos.write` checks the code against the record's own classes and
repairs it when the two contradict each other.  What these tests hold is the
three cases that decide the rule:

* an ordinary record, whose code is right and must not move;
* a trained Curse record, whose code is zero and must be recomputed from the
  class mask;
* SILAS, the shipped Pool of Radiance fighter whose *level array* carries a
  thief 1 that neither his mask nor his code knows about -- the reason the
  rule reads the mask rather than the levels.
"""

from __future__ import annotations

import pytest

from goldbox import dos, dos_layout, neutral


def _code_in(rec: bytes, key: str = "curse-of-the-azure-bonds") -> int:
    return rec[dos_layout.FIELDS_BY_NAME_FOR[key]["char_class"].offset]


def _character(class_bits: int, char_class: int, levels: dict,
               former: dict | None = None,
               game: str = "curse-of-the-azure-bonds") -> neutral.NeutralCharacter:
    """The smallest neutral record `dos.write` will build a record from."""
    char = neutral.NeutralCharacter(port="C64", source="test", game=game)
    char.set("name", "TESTER", "test")
    char.set("class_bits", class_bits, "test")
    char.set("char_class", char_class, "test")
    char.set("levels", dict(levels), "test")
    if former is not None:
        char.set("former_levels", dict(former), "test")
    return char


def test_a_code_that_agrees_with_the_class_mask_is_copied():
    """The ordinary case, and the one that must not move: 228 of 228 DOS
    records and 48 of 48 C64 Pool of Radiance and Silver Blades ones agree,
    so this rule may only ever fire on a record that contradicts itself."""
    char = _character(0x08, 2, {"fighter": 5})
    rec, _itm, _spc, _rep = dos.write(char)
    assert _code_in(rec) == 2


def test_a_trained_curse_records_zeroed_code_is_recomputed():
    """What Curse's own C64 trainer leaves behind.

    TRAVIS is a dwarf thief 6 / fighter 5 on `WISH-SPEC-curse-dual-classed`
    and his code reads 0, which is CLERIC -- and CLERIC is the word the DOS
    sheet drew for him in the running game before this rule existed.
    """
    char = _character(0x0C, 0, {"thief": 6, "fighter": 5})
    rec, _itm, _spc, _rep = dos.write(char)
    assert _code_in(rec) == 14        # fighter/thief
    # The repair is in the report's own byte-by-byte account, which is our
    # accounting rather than anything a player reads.
    at = dos_layout.FIELDS_BY_NAME_FOR["curse-of-the-azure-bonds"][
        "char_class"].offset
    assert "recomputed from class_bits" in _rep.sources[at], _rep.sources[at]
    # And it is not a warning: `editor/exports.py` puts every warning in front
    # of the player under a heading that says the conversion failed at
    # something, and this is a repair.
    assert not any("char_class" in w for w in _rep.warnings), _rep.warnings


def test_a_dual_classed_records_code_comes_from_the_level_array():
    """PHILIPPE: a human magic-user 6 who used `HUMAN CHANGE CLASS` and is a
    fighter 1.  Her code reads **6**, which is her old level rather than a
    class, and 6 is THIEF -- the word the DOS sheet drew for her.

    The mask cannot answer for her once she passes the level she left the
    magic-user at, because it carries both bits then and the code names the
    class she is.  The current level array does: the old class's slot is
    zeroed at the change and stays zero.  The engine agrees -- `GEN $1939`
    branches away from the mask walk entirely when `dual_class_level` is set.
    """
    char = _character(0x08, 6, {"fighter": 1}, former={"magic-user": 6})
    rec, _itm, _spc, _rep = dos.write(char)
    assert _code_in(rec) == 2         # fighter
    char = _character(0x09, 6, {"fighter": 7}, former={"magic-user": 6})
    rec, _itm, _spc, _rep = dos.write(char)
    assert _code_in(rec) == 2


def test_a_level_array_the_mask_does_not_know_about_is_not_a_contradiction():
    """SILAS, shipped with Pool of Radiance: `char_class` 2 and `class_bits`
    `0x08`, both fighter, with a thief 1 in his level array.

    Reading the code off the level array would make him a fighter/thief,
    which is this conversion inventing a class for a character the game calls
    a fighter.  The mask is the source, so his record round-trips.
    """
    char = _character(0x08, 2, {"fighter": 4, "thief": 1},
                      game="pool-of-radiance")
    rec, _itm, _spc, _rep = dos.write(char)
    assert _code_in(rec, "pool-of-radiance") == 2


def test_a_mask_the_games_table_has_no_code_for_leaves_the_source_value():
    """Three combinations have no code in the table the games walk, and
    `goldbox/yaml_io.py` refuses them for the same reason: a code that is not
    in the table means a different class.  There is nothing to repair with,
    so nothing is repaired."""
    char = _character(0x07, 9, {"magic-user": 3, "cleric": 3, "thief": 3})
    rec, _itm, _spc, _rep = dos.write(char)
    assert _code_in(rec) == 9


@pytest.mark.parametrize("bits, code", [
    (0x02, 0),      # cleric
    (0x08, 2),      # fighter
    (0x40, 3),      # paladin
    (0x80, 4),      # ranger
    (0x01, 5),      # magic-user
    (0x04, 6),      # thief
    (0x0A, 8),      # cleric/fighter
    (0x09, 13),     # fighter/magic-user
    (0x0C, 14),     # fighter/thief
])
def test_the_class_table_is_the_games_own(bits, code):
    """`CLASS_CODE_TABLE` is Curse's C64 `GEN $1951` byte for byte, and the
    codes it is indexed by are the standard Gold Box order every title's
    front end lists its classes in."""
    assert dos.CLASS_CODE_FOR_BITS[bits] == code
    assert dos.CLASS_CODE_TABLE[code] == bits
