"""Curse of the Azure Bonds' effect-code table, and what it disagrees about
with Pool of Radiance.

`#561 (A Curse of the Azure Bonds character's traits are named from Pool of
Radiance's table, which disagrees with Curse's own data about eight codes)`
is the ticket. `goldbox/traits.py`'s `NAMES_CURSE` gives Curse a table of its
own, the way `#497` gave Secret of the Silver Blades one -- most of it Pool
of Radiance's strings at the same numbers, with the codes Curse's own spell
table and monster census contradict replaced or left unnamed.

Two kinds of test here, and the second is the one that would catch a
mistake:

* the picker offers what the table names;
* **the entries are re-derived off the player's own disks**: the thirteen
  spell-written codes through `tools.traitquery.spell_effects`, and the
  monster-carried refusals by reading the `MON*` templates directly, the way
  `tests/test_ssbtraitnames.py` reads Silver Blades'. A base that slips or a
  name that drifts from the game's own data turns these red. All of them
  skip with no disks.
"""

from __future__ import annotations

import pytest

from editor import effects
from goldbox import c64_port, traits
from goldbox.d64 import D64
from tools import gamedisks, traitquery

CURSE = c64_port.CURSE_OF_THE_AZURE_BONDS
POOL = c64_port.POOL_OF_RADIANCE

#: The thirteen codes Curse's own spell table CONFIRMS disagree with or are
#: missing from `NAMES`, and the spell that writes each one. Read off the
#: disks by the test below rather than trusted from here: this is what the
#: run is checked against, so a disagreement names the code.
BY_SPELL = {
    3: "STICKS TO SNAKES", 4: "DISPEL EVIL", 7: "FAERIE FIRE",
    27: "FUMBLE", 35: "CONFUSION", 63: "MINOR GLOBE OF INVULNERABLITY",
    68: "FEEBLEMIND", 69: "INVISIBILITY TO ANIMALS",
    136: "ENTANGLE", 142: "FEAR", 143: "FIRE SHIELD",
}

#: The ten codes refused by the monster census -- a Pool of Radiance name
#: landing on a Curse creature that cannot have it -- with no replacement
#: name read yet, so `NAMES_CURSE` omits them.
REFUSED_UNNAMED = (57, 81, 82, 84, 85, 86, 87, 90, 96, 103)

#: The eight codes above `NAMES`'s reach that a Curse creature carries and
#: `NAMES` never named at all.
CURSE_ONLY = (128, 129, 130, 131, 132, 133, 135, 138)


def _disks():
    root = gamedisks.find(CURSE.key)
    if root is None:
        pytest.skip("no Curse of the Azure Bonds disks on this machine")
    return str(root)


# --- the table itself -------------------------------------------------------

def test_the_table_is_curses_own():
    """It is not Pool of Radiance's table by the back door."""
    assert traits.for_game(CURSE) is traits.NAMES_CURSE
    assert traits.for_game(CURSE) is not traits.for_game(POOL)


def test_reverting_the_wiring_loses_the_fix():
    """Pins `TABLES["curse-of-the-azure-bonds"]` at `NAMES_CURSE`: point it
    back at `NAMES` and this goes red, which is the regression `#561` is
    about -- a Faerie Fire victim reading "training with a Manual of Bodily
    Health"."""
    assert traits.TABLES["curse-of-the-azure-bonds"] is traits.NAMES_CURSE
    assert traits.describe(7, CURSE) == "Faerie Fire"
    assert traits.describe(7, POOL) != "Faerie Fire"


def test_no_entry_is_blank_or_a_bare_number():
    for code, (name, _grade) in traits.NAMES_CURSE.items():
        assert name.strip()
        assert name.strip() != str(code)
        assert not name.startswith("trait ")


def test_the_thirteen_codes_dont_carry_pool_of_radiances_wording():
    for code in BY_SPELL:
        assert traits.NAMES_CURSE[code][0] != traits.NAMES.get(
            code, (None,))[0]


def test_the_refused_codes_are_unnamed_rather_than_wrong():
    """The picker and the sheet fall back to the number rather than
    repeating a name the game's own creatures contradict."""
    for code in REFUSED_UNNAMED:
        assert code not in traits.NAMES_CURSE
        assert traits.describe(code, CURSE) == f"trait {code}"
        assert traits.confidence(code, CURSE) == ""


def test_curse_only_codes_are_unnamed_too():
    for code in CURSE_ONLY:
        assert code not in traits.NAMES
        assert code not in traits.NAMES_CURSE
        assert traits.describe(code, CURSE) == f"trait {code}"


def test_71_73_and_109_keep_pool_of_radiances_wording_on_purpose():
    """Their only Curse evidence is an unset spell-name pointer and no
    creature carries them, so nothing here contradicts Pool of Radiance."""
    for code in (71, 73, 109):
        assert traits.NAMES_CURSE[code][0] == traits.NAMES[code][0]


def test_most_of_the_shared_namespace_transfers_unchanged():
    touched = set(BY_SPELL) | set(REFUSED_UNNAMED) | set(CURSE_ONLY) | {
        60, 71, 73, 105, 109}
    unchanged = [code for code in traits.NAMES
                 if code not in touched]
    assert len(unchanged) > 100
    for code in unchanged:
        assert traits.NAMES_CURSE.get(code) == traits.NAMES[code]


# --- the picker -------------------------------------------------------------

def test_the_picker_offers_what_the_table_names():
    offered = effects.offered(CURSE)
    assert {code for code, _name, _seen in offered} == set(
        traits.NAMES_CURSE) - {effects.FILL}
    for code, name, seen in offered:
        assert name == traits.NAMES_CURSE[code][0]
        assert seen is (traits.NAMES_CURSE[code][1] != "PROBABLE")


def test_the_picker_still_offers_pool_of_radiances_own_list_unchanged():
    assert len(effects.offered(POOL)) == len(traits.NAMES) - 1   # less FILL


# --- re-derived off the disks ------------------------------------------------

def test_the_spell_effect_table_is_where_curse_keeps_it():
    """`COMBAT2 +2732`, nine bytes a record, one per spell id 1-100."""
    table = traitquery.spell_effects(_disks(), CURSE)
    assert len(table) == 100
    name, effect, message = table[1]
    assert name == "BLESS"
    assert effect == 1
    assert message == "IS BLESSED"


def test_every_spell_named_code_is_what_curses_own_table_writes():
    """The thirteen codes `NAMES_CURSE` gives new wording, re-derived: the
    code the table names is the code that spell writes, filtered to rows in
    a spell group (`docs/171-c64-trait-slots.md`'s rule for excluding a row
    whose name pointer was never set, which reads as the table's first
    string, BLESS)."""
    from goldbox import spells

    table = traitquery.spell_effects(_disks(), CURSE)
    descriptor = spells.for_game(CURSE.key)
    grouped: set[int] = set()
    for first, last, _who, _level in descriptor.groups:
        grouped |= set(range(first, last + 1))

    writers: dict[int, set[str]] = {}
    for spell, (name, code, _message) in table.items():
        if code and spell in grouped:
            writers.setdefault(code, set()).add(name)

    missing = {code: spell for code, spell in BY_SPELL.items()
               if spell not in writers.get(code, ())}
    assert missing == {}
    for code in BY_SPELL:
        assert traits.NAMES_CURSE[code][1] == "CONFIRMED"


def test_71_73_and_109_are_written_only_by_an_ungrouped_row():
    """Corroborates why these three stay unnamed by the spell route: the
    only row writing each is in no spell group and carries the unset-pointer
    name BLESS."""
    from goldbox import spells

    table = traitquery.spell_effects(_disks(), CURSE)
    descriptor = spells.for_game(CURSE.key)
    grouped: set[int] = set()
    for first, last, _who, _level in descriptor.groups:
        grouped |= set(range(first, last + 1))

    for code in (71, 73, 109):
        writers = [(spell, name) for spell, (name, c, _m) in table.items()
                   if c == code]
        assert writers
        for spell, name in writers:
            assert spell not in grouped
            assert name == "BLESS"


def test_the_creatures_that_refuse_the_pool_of_radiance_names():
    """The ten refused codes, read straight off the 70 `MON*` templates:
    each lands on a creature the *Monster Manual* power `NAMES` gives that
    number cannot have."""
    carriers: dict[int, set[str]] = {}
    seen: set[str] = set()
    for path in sorted(gamedisks.find(CURSE.key).glob(CURSE.disk_glob)):
        image = D64.open(str(path))
        for entry in image.directory():
            name = bytes(entry.name).decode("latin-1")
            if not name.startswith("MON") or name in seen:
                continue
            seen.add(name)
            body = image.read_file(entry)[2:]
            monster = body[:20].split(b"\0")[0].decode("latin-1").strip()
            for code in body[0xAD:0xB7]:
                if code:
                    carriers.setdefault(code, set()).add(monster)
    assert len(seen) == 70
    expected = {
        57: {"SHAMBLING MOUND", "BIT O' MOANDER"},
        81: {"DRAGONBAIT", "SHAMBLING MOUND", "BIT O' MOANDER", "ALIAS"},
        82: {"SHAMBLING MOUND", "BIT O' MOANDER"},
        84: {"SHAMBLING MOUND", "BIT O' MOANDER"},
        85: {"LG VEGEPYGMY", "SM VEGEPYGMY"},
        86: {"GIANT SLUG"},
        87: {"BEHOLDER"},
        90: {"BLACK DRAGON"},
        96: {"OWL BEAR"},
        103: {"SALAMANDER"},
    }
    for code, names in expected.items():
        assert carriers.get(code) == names, code
    # And 68 and 69 -- Pool of Radiance's GHOUL and DRIDER specials -- have
    # no Curse carrier at all, because Curse ships no GHOUL and no DRIDER.
    assert 68 not in carriers
    assert 69 not in carriers
    assert not any(name in ("GHOUL", "DRIDER") for names in carriers.values()
                   for name in names)


def test_curse_only_codes_carried_by_a_creature_names_never_names():
    carriers: set[int] = set()
    for path in sorted(gamedisks.find(CURSE.key).glob(CURSE.disk_glob)):
        image = D64.open(str(path))
        for entry in image.directory():
            name = bytes(entry.name).decode("latin-1")
            if not name.startswith("MON"):
                continue
            body = image.read_file(entry)[2:]
            for code in body[0xAD:0xB7]:
                if code:
                    carriers.add(code)
    for code in CURSE_ONLY:
        assert code in carriers, code
        assert code not in traits.NAMES
