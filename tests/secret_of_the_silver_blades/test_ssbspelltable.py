from __future__ import annotations

"""Silver Blades' spell groups in `goldbox.spells` against the DOS spell table.

The player's own `START.EXE` holds a 16-byte entry per spell id whose first two
bytes are the casting class and the spell level; class 4 marks a slot that is
not a spell. Skips without the DOS disks. No game bytes are committed.
"""

import pytest

from goldbox import spells
from tools.dos import dosbox, dosspellslots

SSB = spells.SECRET_OF_THE_SILVER_BLADES

#: The engine's class byte, as Wish names it. 4 is "not a spell".
CLASSES = {0: "cleric", 1: "druid", 3: "magic-user"}
NOT_A_SPELL_CLASS = 4

#: Ids where Wish and DOS's table deliberately differ, each with its reason.
EXCEPTIONS = {
    108: "DOS has class 1 level 9 named `spell 108`; the C64 has druid 2 named "
         "TRIP, and neither trainer grants it, so Wish keeps it not a spell",
    109: "DOS has class 3 level 0 named `spell 109`; the C64 level is 0 too, "
         "so no menu lists it, and Wish keeps it in magic-user 6 with "
         "`not_granted`",
}


@pytest.fixture(scope="module")
def table():
    """`{id: (class, level)}` for ids 1 to 117, or a skip."""
    try:
        game = dosbox.find_game("SECRET")
    except FileNotFoundError as exc:
        pytest.skip(f"needs the Silver Blades DOS disks: {exc}")
    ovr = (game / "GAME.OVR").read_bytes()
    image = dosspellslots.image_of(game, None)
    block, _ = dosspellslots.block_of(439)
    offset = None
    for site, _count in dosspellslots.fill_sites(ovr, block):
        offset = dosspellslots.table_offset(ovr, site)
        if offset is not None:
            break
    assert offset is not None
    base = dosspellslots.data_segment(image) * 16 + offset
    return {sid: (image[base + sid * 16], image[base + sid * 16 + 1])
            for sid in range(1, SSB.last_spell + 1)}


def test_the_class_4_slots_are_exactly_the_not_a_spell_list(table):
    dos = {sid for sid, (cls, _) in table.items() if cls == NOT_A_SPELL_CLASS}
    assert dos == set(SSB.not_a_spell) - set(EXCEPTIONS)


def test_every_other_id_has_the_class_and_level_the_engine_gives_it(table):
    wrong = {}
    for sid, (cls, level) in table.items():
        if cls == NOT_A_SPELL_CLASS or sid in EXCEPTIONS:
            continue
        got = spells.spell_group(sid, SSB.key)
        if got != (CLASSES.get(cls, f"class {cls}"), level):
            wrong[sid] = (got, (cls, level))
    assert wrong == {}


def test_the_exceptions_still_differ(table):
    """An exception that stopped differing would be a stale excuse."""
    for sid in EXCEPTIONS:
        cls, level = table[sid]
        assert (spells.spell_group(sid, SSB.key)
                != (CLASSES.get(cls), level)
                or sid in SSB.not_a_spell)
