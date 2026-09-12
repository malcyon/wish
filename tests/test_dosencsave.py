"""Which screen makes DOS Pool of Radiance rewrite stored encumbrance.

`tools/dosencsave.py` staged 999 into every record of a training-ladder rung
**before the boot**, so the engine read the spoiled value when it loaded the
party, and then took three saves off that one load.  What the three saves hold
is asserted here, because the finding is a negative one and a negative finding
is the kind that quietly stops being true when a reader changes.

* a party-menu `SAVE CURRENT GAME` and a camp save both wrote 999 back, so
  neither recomputes;
* one `VIEW` later, the character whose sheet was drawn holds his true sum and
  the five whose sheets were not still hold 999.

That is what `#323 (The encumbrance identity does not survive the training
fee, so failing it is not evidence of an edited record)` needed: a stale
stored total says nobody has looked at that character's sheet since the money
moved, and says nothing about who wrote the record.

These skip where the specimen tree is absent, which is every CI runner.
"""

from __future__ import annotations

import gamedata
import pytest

from goldbox import dos_codec

MENU = "por-enc-spoiled-menusave"
CAMP = "por-enc-spoiled-campsave"
VIEWED = "por-enc-spoiled-viewed"

#: What was written into every record's stored encumbrance before the boot.
#: None of these six characters' own arithmetic can produce it, which is why
#: a record still holding it afterwards means the engine wrote back what it
#: loaded rather than a number of its own.
SPOIL = 999

#: The sum every one of the six should have: 19,000 coins and no items.
SUM = 19000


def _records(name: str, letter: str):
    if not gamedata.have_specimen(name):
        pytest.skip(f"needs specimen WISH-SPEC-{name}")
    folder = gamedata.specimen(name)
    return [dos_codec.read_character(folder / f"CHRDAT{letter}{n}.SAV")
            for n in range(1, 7)]


@pytest.mark.parametrize("name,letter", [(MENU, "A"), (CAMP, "B")])
def test_a_save_writes_back_the_stored_value_it_loaded(name, letter):
    """Neither save path recomputes: 6 of 6 come back holding the spoiled 999.

    The party trained nobody, bought nothing and stood still, so the only
    thing that could have changed the field is the save itself.
    """
    for who in _records(name, letter):
        assert who.get("encumbrance") == SPOIL, who.name
        assert who.expected_encumbrance() == SUM, who.name


def test_drawing_a_sheet_writes_the_recomputed_total_into_that_record():
    """`VIEW` is what rewrites it, and only for the character it drew.

    One action after the camp save above, in the same boot: WISHFTR's sheet
    was drawn -- it showed 19000 over a file that said 999 -- and the next
    save wrote 19000 into his record.  The other five are the control.
    """
    party = _records(VIEWED, "D")
    viewed, rest = party[0], party[1:]
    assert viewed.name == "WISHFTR"
    assert viewed.get("encumbrance") == SUM
    assert viewed.get("encumbrance") == viewed.expected_encumbrance()
    for who in rest:
        assert who.get("encumbrance") == SPOIL, who.name


def test_the_training_ladder_agrees_once_the_restaging_is_taken_out():
    """The ladder's climbing total is one fee a boot plus our own poke.

    `tools/dostrainprobe.install` moves stored encumbrance with the gold it
    writes, so rung *n+1* is staged at rung *n*'s stored value plus whatever
    the restaging put back -- and the engine leaves it there.  Reproducing
    that arithmetic is what shows the drift is not the engine adding 1000 a
    rung, which is how the ladder was read before.
    """
    from tools.dosencsave import LADDER_GOLD

    names = [f"por-party-ladder-rung{n}" for n in range(8)]
    if not all(gamedata.have_specimen(n) for n in names):
        pytest.skip("needs the training-ladder specimens")
    seen = []
    for name in names:
        folder = gamedata.specimen(name)
        # **The rungs are not all installed under the same letter** -- rung 0
        # is F where the rest are E -- so the first roster slot is found by
        # position rather than by a letter that changes under the test.
        first = sorted(folder.glob("CHRDAT?1.SAV"))[0]
        who = dos_codec.read_character(first)
        assert who.name == "WISHFTR"
        seen.append((sum(who.money.values()), who.get("encumbrance")))
    for (coins, stored), (_, nxt) in zip(seen, seen[1:]):
        assert stored + (LADDER_GOLD - coins) == nxt
