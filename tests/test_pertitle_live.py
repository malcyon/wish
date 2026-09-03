from __future__ import annotations

"""The automapper's roster card, once it stopped reading every title through
Pool of Radiance's tables.

Two faults, one function apart in `automap/live.py`, both found after
`#186 (The character sheet gives a Silver Blades elf a Pool of Radiance
ability)` and `#187 (Silver Blades characters are shown Pool of Radiance's
level progression)` fixed the same shape elsewhere:

* `#196 (The automapper's condition badges name a Silver Blades trait with
  Pool of Radiance's meaning)` -- `badges()` called `traits.describe(i)` with
  no game, and the badge **groups** were Pool of Radiance's effect ids besides.
* `#197 (A Curse or Silver Blades paladin or ranger has no class and no
  experience bar on its roster card)` -- `_classes` walked
  `goldbox.derive.CLASS_BITS`, the classic four, so bits `0x40` and `0x80`
  matched nothing.

Everything here is built from the format rather than opened, so none of it
needs the player's disks: the shipped Silver Blades party has no elf and no
save anybody holds was taken with a spell running on a later title.
"""

import dataclasses

from automap import live
from goldbox import games, traits
from goldbox.record import CharacterRecord
from goldbox.savegame import SaveGame0

POOL = games.POOL_OF_RADIANCE
CURSE = games.CURSE_OF_THE_AZURE_BONDS
SSB = games.SECRET_OF_THE_SILVER_BLADES
KRYNN = games.CHAMPIONS_OF_KRYNN

#: The *hasted* badge's only id, and the one Pool of Radiance's table names
#: "hasted". Silver Blades' own table does not name it at all -- `GEN $0C4B`
#: seeds nine codes and 39 is not among them -- so a Silver Blades card that
#: draws a running ninja for it is asserting a meaning nobody has read.
HASTE = 39
POOL_NAME_FOR_39 = "hasted"


def _record(**fields) -> CharacterRecord:
    """A record wide enough to decode, carrying whatever the test cares about."""
    record = CharacterRecord.blank()
    record.set("name", "PAINE")
    for ability in ("strength", "intelligence", "wisdom", "dexterity",
                    "constitution", "charisma"):
        record.set(ability, 12)
    record.set("hp_max", 60)
    for name, value in fields.items():
        record.set(name, value)
    return record


def _payload(game, record, effect=None, owner=0) -> bytes:
    """A `SAVEDGAME0` image holding one character and at most one effect.

    The effect arrays are payload offsets `$000`, `$040`, `$080` and `$280` in
    every title -- `test_coldread.py` measures that -- so writing one is the
    same four stores whichever game this is.
    """
    save0 = SaveGame0(bytearray(game.save_size), game)
    save0.write_record(0, record)
    data = bytearray(save0.to_bytes())
    if effect is not None:
        data[live.EFFECT_ID_OFFSET] = effect
        data[live.EFFECT_OWNER_OFFSET] = owner
        data[live.EFFECT_DURATION_OFFSET] = 8
    return bytes(data)


def _snapshot(game, record, effect=None, owner=0):
    snap = live.snapshot_from_bytes(_payload(game, record, effect, owner),
                                    bytes(live.ROSTER_PAGE), None, game)
    assert snap is not None
    return snap


def _fighter(level=8):
    return _record(class_bits=8, level_fighter=level, level=level,
                   experience=150_000)


# --- #196: which codes earn a badge, and what the badge says -----------------

def test_a_silver_blades_card_draws_no_badge_for_a_code_nobody_has_read():
    """The fault a player sees: a running ninja on a Silver Blades card,
    saying the character is hasted, when 39 is one of the codes this title
    reassigned and nobody has read what it now means.

    Before the fix this card carries `("running-ninja", "Hasted")`.
    """
    snap = _snapshot(SSB, _fighter(), effect=HASTE)
    assert snap.characters[0].conditions == ()


def test_a_pool_of_radiance_card_badges_the_same_effect_exactly_as_before():
    """The control. 39 is Pool of Radiance's own hasted and must stay a
    running ninja on the title the badge set was chosen for."""
    snap = _snapshot(POOL, _fighter(), effect=HASTE)
    assert snap.characters[0].conditions == (
        ("running-ninja", POOL_NAME_FOR_39.capitalize()),)


def test_curse_keeps_pool_of_radiances_badges_because_it_shares_its_codes():
    """Curse seeds every racial code Pool of Radiance does, on the race each
    name demands (`goldbox/traits.py`, `#186`), so its badges are not the
    thing this fix moves."""
    snap = _snapshot(CURSE, _fighter(), effect=HASTE)
    assert snap.characters[0].conditions == (
        ("running-ninja", POOL_NAME_FOR_39.capitalize()),)


def test_the_party_strip_is_per_title_too_and_the_effect_is_not_lost():
    """The bottom strip goes through the same `badges()`, so it has to move
    with the card -- and the effect has to stay *visible* somewhere, which is
    what `unbadged_party_effects` is for: `automap/panel.py` puts those in the
    debug log precisely so a title short of a glyph says so."""
    snap = _snapshot(SSB, _fighter(), effect=HASTE, owner=live.PARTY_WIDE)
    assert snap.party_badges == ()
    assert [e.id for e in snap.unbadged_party_effects] == [HASTE]

    control = _snapshot(POOL, _fighter(), effect=HASTE, owner=live.PARTY_WIDE)
    assert control.party_badges == (
        ("running-ninja", POOL_NAME_FOR_39.capitalize()),)
    assert control.unbadged_party_effects == ()


def test_a_badge_takes_its_name_from_the_running_titles_table(monkeypatch):
    """The naming half of #196, on its own.

    Silver Blades draws no badges at all, so it cannot show that
    `traits.describe` is now given the title -- a group that is empty names
    nothing either way. This builds the case the fix is *for*: a title that
    keeps Pool of Radiance's badge groups and gives one of their ids its own
    meaning. Before the fix the card reads "Hasted", Pool of Radiance's word,
    whatever is running.
    """
    from goldbox import games as _games

    invented = dataclasses.replace(CURSE, key="a-title-with-its-own-codes",
                                   title="A title with its own codes")
    monkeypatch.setitem(traits.TABLES, invented.key,
                        {HASTE: ("dazzled", "PROBABLE")})
    assert live.condition_badges(invented) == live.CONDITION_BADGES
    snap = _snapshot(invented, _fighter(), effect=HASTE)
    assert snap.characters[0].conditions == (("running-ninja", "Dazzled"),)
    assert _games.DEFAULT is POOL          # and the default did not move


def test_a_badge_name_comes_from_the_titles_own_trait_table():
    """`badges()` used to call `traits.describe(i)` with no game at all, which
    is `for_game(None)` and therefore Pool of Radiance's table whatever was
    running. 45 is the one badged id Silver Blades' own `GEN` establishes --
    it is what `$0FF0` writes for a paladin -- so it is the one that can show
    the two tables agreeing on a string by way of the right number."""
    assert traits.describe(45, SSB) == traits.describe(45, POOL)
    # And every other badged id is unread on that title, which is why the
    # groups are empty there rather than renamed.
    unread = [i for _, ids in live.CONDITION_BADGES for i in ids
              if i not in traits.for_game(SSB)]
    assert len(unread) == 16


def test_a_title_nobody_has_read_keeps_pool_of_radiances_badges():
    """The Krynn pair and Gateway get Pool of Radiance's trait table
    (`traits.for_game`), so they get its badge groups too -- the behaviour
    they have always had. Neither is reachable in the live view anyway:
    `Game.live_position` is unmeasured for both."""
    assert KRYNN.live_position is None
    assert live.condition_badges(KRYNN) == live.CONDITION_BADGES
    assert live.condition_badges(None) == live.CONDITION_BADGES
    assert live.condition_badges(SSB) == ()


def test_the_one_argument_badges_call_still_means_pool_of_radiance():
    """`tools/rostercard.py` and `tools/shotstrip.py` read
    `live.CONDITION_BADGES` directly and `badges()` is called with one
    argument in the existing tests. None is Pool of Radiance, here as in
    `traits.for_game` and `levels.for_game`."""
    assert live.badges((HASTE,)) == (
        ("running-ninja", POOL_NAME_FOR_39.capitalize()),)


# --- #197: the classes above the classic four -------------------------------

def test_a_silver_blades_ranger_gets_a_class_and_an_experience_bar():
    """PAINE, the Silver Blades ranger, read through the title she is in.
    Before the fix `_classes` returns an empty tuple and the card says `?`."""
    record = _record(class_bits=0x80, level_ranger=8, level=8,
                     experience=200_000)
    (ranger,) = live._classes(record, SSB)
    assert ranger.name == "ranger"
    assert ranger.level == 8
    assert not ranger.at_ceiling
    assert ranger.next_threshold == 225_001


def test_a_curse_paladin_gets_a_class_and_an_experience_bar():
    """GUY DE VALOIS' shape, on the title whose shipped party is literally
    named PALADIN and RANGER."""
    record = _record(class_bits=0x40, level_paladin=8, level=8,
                     experience=200_000)
    (paladin,) = live._classes(record, CURSE)
    assert paladin.name == "paladin"
    assert paladin.level == 8
    assert paladin.next_threshold == 350_001


def test_the_ranger_takes_her_level_from_her_own_slot_and_not_the_level_byte():
    """`0x0D0` is the ranger's slot in the eight-byte per-class level array,
    and it is the field to prefer -- the single `level` byte at `0x074` is
    allowed to disagree with it, the same way `char_class` may disagree with
    `class_bits`."""
    record = _record(class_bits=0x80, level_ranger=8, level=3,
                     experience=200_000)
    (ranger,) = live._classes(record, SSB)
    assert ranger.level == 8


def test_the_card_names_a_silver_blades_ranger_and_her_level():
    """End to end, through the one entry point the automapper draws from.
    Before the fix this card reads `?  L8`."""
    record = _record(class_bits=0x80, level_ranger=8, level=8,
                     experience=200_000)
    who = _snapshot(SSB, record).characters[0]
    assert who.class_text != "?"
    assert who.level_text == "L8"
    assert len(who.classes) == 1


def test_a_pool_of_radiance_fighter_reads_exactly_as_before():
    """The control that must not move: the abbreviations and the single bar
    are what every Pool of Radiance card has always drawn."""
    who = _snapshot(POOL, _fighter()).characters[0]
    assert who.class_text == "F"
    assert who.level_text == "L8"
    assert len(who.classes) == 1


def test_pool_of_radiance_still_has_no_paladin():
    """The fix reads *the title's* class list, not one list with three more
    rows bolted on. Pool of Radiance has no bit above 8, so a record carrying
    `0x40` on that title names no class -- which is the honest answer, and the
    answer it gave before."""
    record = _record(class_bits=0x40, level_paladin=8, level=8)
    assert live._classes(record, POOL) == ()
    assert _snapshot(POOL, record).characters[0].class_text == "?"


def test_a_multi_class_card_still_draws_a_bar_each():
    """LADY KATHERINE's shape -- the classic four still multi-class, and the
    per-class level array is where each one's level comes from."""
    record = _record(class_bits=5, level_magic_user=4, level_thief=6, level=6,
                     experience=20_000)
    got = {c.name: c.level for c in live._classes(record, POOL)}
    assert got == {"magic-user": 4, "thief": 6}
