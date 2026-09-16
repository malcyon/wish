"""Secret of the Silver Blades' effect-code table, and what the picker offers.

`#497 (The trait picker offers a Secret of the Silver Blades character six
names, and nobody has ruled on whether it should offer Pool of Radiance's
129)` is the ticket. Donald ruled on 2026-09-15 that the codes be named
properly rather than the picker staying thin or borrowing Pool of Radiance's
names unmarked, and `goldbox/traits.py`'s `NAMES_SILVER_BLADES` went from six
entries to 59.

Two kinds of test here, and the second is the one that would catch a mistake:

* the picker offers what the table names, which is the ticket's own request;
* **44 of the 59 entries are re-derived off the player's own disks** by
  reading that title's spell-effect table, so a name that drifts from what
  the game's data says turns this red. Those skip with no disks.

The other fifteen -- the ones earned by a check list, by a call site, by a
creature carrying the code or by `GEN`'s racial seed -- are graded PROBABLE
and cannot be re-derived this cheaply; `docs/171-c64-trait-slots.md` has the
runs and `tools/traitquery.py --compare` re-takes the first of them.
"""

from __future__ import annotations

import pytest

from editor import effects
from goldbox import c64_port, traits
from tools import gamedisks, traitquery

SSB = c64_port.SECRET_OF_THE_SILVER_BLADES
POOL = c64_port.POOL_OF_RADIANCE

#: Every code in the table that one of this title's own spells writes, and
#: the spell whose name has to be behind it. Read off the disks by the test
#: below rather than trusted from here: this list is what the run is checked
#: against, so a disagreement names the code.
BY_SPELL = {
    1: "BLESS", 2: "CURSE", 3: "STICKS TO SNAKES", 4: "DISPEL EVIL",
    5: "DETECT MAGIC", 8: "PROTECTION FROM EVIL", 9: "PROTECTION FROM GOOD",
    10: "RESIST COLD", 11: "CHARM PERSON", 12: "ENLARGE", 13: "BARKSKIN",
    17: "SHIELD", 20: "RESIST FIRE", 21: "SILENCE 15' RADIUS",
    23: "SPIRITUAL HAMMER", 24: "DETECT INVISIBILITY", 25: "INVISIBILITY",
    27: "FUMBLE", 28: "MIRROR IMAGE", 29: "RAY OF ENFEEBLEMENT",
    30: "STINKING CLOUD", 33: "CAUSE BLINDNESS", 34: "CAUSE DISEASE",
    35: "CONFUSION", 36: "BESTOW CURSE", 37: "BLINK", 39: "HASTE",
    41: "PROTECTION FROM NORMAL MISSILES", 42: "SLOW",
    45: "PROTECTION FROM EVIL 10' RADIUS",
    46: "PROTECTION FROM GOOD 10' RADIUS", 49: "PRAYER", 51: "SNAKE CHARM",
    52: "HOLD PERSON", 53: "SLEEP", 55: "POISON",
    57: "GLOBE OF INVULNERABLITY", 63: "MINOR GLOBE OF INVULNERABLITY",
    68: "FEEBLEMIND", 69: "INVISIBILITY TO ANIMALS", 71: "FAERIE FIRE",
    106: "ENTANGLE", 111: "FEAR", 112: "FIRE SHIELD",
}


def _disks():
    root = gamedisks.find(SSB.key)
    if root is None:
        pytest.skip("no Secret of the Silver Blades disks on this machine")
    return str(root)


# --- the table itself -------------------------------------------------------

def test_every_entry_carries_a_grade_this_project_uses():
    """A code with no grade is a code nobody has thought about hard enough.

    44 CONFIRMED and 15 PROBABLE, and the split is not decoration: the
    picker's `Seen in this game` section is `confidence != PROBABLE`, so a
    grade here decides which half of the list a player reads a name in.
    """
    grades = [grade for _name, grade in traits.NAMES_SILVER_BLADES.values()]
    assert sorted(set(grades)) == ["CONFIRMED", "PROBABLE"]
    assert grades.count("CONFIRMED") == 44
    assert grades.count("PROBABLE") == 15


def test_no_entry_is_blank_or_a_bare_number():
    """A name that is the number again is what `describe` already does for an
    unnamed code, so an entry saying it would be a row with nothing in it."""
    for code, (name, _grade) in traits.NAMES_SILVER_BLADES.items():
        assert name.strip()
        assert name.strip() != str(code)
        assert not name.startswith("trait ")


def test_the_table_is_still_this_titles_own():
    """It grew from six to 59 and none of the growth is Pool of Radiance's
    table by the back door: the codes that title spends on something this one
    does not have are absent, which is what `#186` and `#196` are about."""
    table = traits.for_game(SSB)
    assert table is not traits.for_game(POOL)
    for code in (38, 107, 124, 139, 255):
        assert code not in table
    # And the four Pool of Radiance names this title's own data contradicts
    # are not reused at their old numbers.
    for code in (3, 4, 27, 35):
        assert traits.describe(code, SSB) != traits.describe(code, POOL)


# --- the picker -------------------------------------------------------------

def test_the_picker_offers_every_code_the_table_names():
    """The ticket's own request. `editor.effects.offered` is what fills the
    picker, and on this title it now offers 59 rows where it offered six."""
    offered = effects.offered(SSB)
    assert len(offered) == len(traits.NAMES_SILVER_BLADES) == 59
    assert {code for code, _name, _seen in offered} == set(
        traits.NAMES_SILVER_BLADES)
    for code, name, seen in offered:
        assert name == traits.NAMES_SILVER_BLADES[code][0]
        assert seen is (traits.NAMES_SILVER_BLADES[code][1] != "PROBABLE")


def test_the_picker_still_offers_pool_of_radiances_own_list_unchanged():
    """The control: this title's table grew and nothing else moved."""
    assert len(effects.offered(POOL)) == len(traits.NAMES) - 1   # less FILL
    assert len(effects.offered(None)) == len(effects.offered(POOL))


def test_a_code_no_route_reached_still_reads_as_its_number():
    """35 of the 90 codes the engine honours here are unnamed, and the number
    is the honest answer for each. 92 is the halfling's own racial seed and
    this title's DREADLORD carries it too, which is why no reading of it
    survives; 105 is the ranger's."""
    for code in (7, 92, 105):
        assert traits.describe(code, SSB) == f"trait {code}"
        assert traits.confidence(code, SSB) == ""


# --- re-derived off the disks ----------------------------------------------

def test_the_spell_effect_table_is_where_this_title_keeps_it():
    """`COMBAT2 +2937`, nine bytes a record, one per spell id 1-117.

    Two checks that the base and the record size are right, neither of them
    the fit that found them: every value falls inside this title's own
    113-code namespace, and byte 1 is a message index that resolves to
    `IS BLESSED` for BLESS in the same string table `goldbox/spells.py`
    reads.
    """
    table = traitquery.spell_effects(_disks(), SSB)
    assert len(table) == 117
    name, effect, message = table[1]
    assert name == "BLESS"
    assert effect == 1
    assert message == "IS BLESSED"
    # One row is out of range -- spell 59, whose own name slot in the string
    # table is unused in this title and in Curse, and whose value is the
    # namespace size exactly in both. Everything else is a real code.
    out_of_range = [spell for spell, (_n, code, _m) in table.items()
                    if code >= 113]
    assert out_of_range == [59]


def test_every_spell_named_code_is_what_the_games_own_table_writes():
    """44 of the 59 entries re-derived off the disks.

    The check is not that the string matches a spell name -- several of them
    are Pool of Radiance's own wording for the same effect -- but that the
    code the table names is the code that spell writes. A base that slipped,
    a record size that changed or a transcription slip in `goldbox/traits.py`
    all show up here as a named code with the wrong spell behind it.
    """
    table = traitquery.spell_effects(_disks(), SSB)
    writers: dict[int, set[str]] = {}
    for _spell, (name, code, _message) in table.items():
        if code:
            writers.setdefault(code, set()).add(name)
    missing = {code: spell for code, spell in BY_SPELL.items()
               if spell not in writers.get(code, ())}
    assert missing == {}
    assert set(BY_SPELL) <= set(traits.NAMES_SILVER_BLADES)
    for code in BY_SPELL:
        assert traits.NAMES_SILVER_BLADES[code][1] == "CONFIRMED"


def test_the_three_codes_positional_agreement_got_wrong():
    """4, 27 and 35 are why the check-list route is PROBABLE and not better.

    Each sits in the same numbered check list here as in Curse, so agreement
    offered Pool of Radiance's name for it; each is in fact a spell this
    title has and Pool of Radiance has not. The test pins the disagreement
    rather than the repair, so a table that quietly took the borrowed name
    back turns it red.
    """
    table = traitquery.spell_effects(_disks(), SSB)
    by_code: dict[int, set[str]] = {}
    for _spell, (name, code, _message) in table.items():
        if code:
            by_code.setdefault(code, set()).add(name)
    assert "DISPEL EVIL" in by_code[4]
    assert "FUMBLE" in by_code[27]
    assert "CONFUSION" in by_code[35]
    for code in (4, 27, 35):
        assert traits.NAMES[code][0] != traits.NAMES_SILVER_BLADES[code][0]
