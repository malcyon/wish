"""Curse of the Azure Bonds' effect-code table, and what it disagrees about
with Pool of Radiance.

`#561 (A Curse of the Azure Bonds character's traits are named from Pool of
Radiance's table, which disagrees with Curse's own data about eight codes)`
is where `goldbox/traits.py`'s `NAMES_CURSE` came from, and `#567 (Twelve of
Curse of the Azure Bonds' own effect codes have no name at all, only a
refusal of Pool of Radiance's wrong one)` is where the eighteen codes it
could only refuse got names, by reading the routine each one dispatches.

Two kinds of test here, and the second is the one that would catch a
mistake:

* the picker offers what the table names;
* **the entries are re-derived off the player's own disks**: the thirteen
  spell-written codes through `tools.c64.traitquery.spell_effects`, the
  monster-carried ones by reading the `MON*` templates directly, and the
  handler-named ones by pinning what each name rests on -- the damage-type
  bit an immunity tests, the percentile a resistance rolls, the combat
  message a ranged form prints, the item word a vulnerability names. A base
  that slips or a name that drifts from the game's own data turns these red.
  All of them skip with no disks.

`docs/222-naming-curses-effect-codes-from-their-handlers.md` has the
readings and the anchors they rest on.
"""

from __future__ import annotations

import pytest

from automap import gamedisks
from editor import effects
from goldbox import c64_port, items, spells, traits
from goldbox.d64 import D64
from tools.c64 import traitquery

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

#: The ten codes the monster census could only refuse -- a Pool of Radiance
#: name landing on a Curse creature that cannot have it -- and the creature
#: that carries each. Named from their handlers on `#567`.
REFUSED = (57, 81, 82, 84, 85, 86, 87, 90, 96, 103)

#: The eight codes above `NAMES`'s reach that a Curse creature carries and
#: `NAMES` never named at all. Named from their handlers on `#567`.
CURSE_ONLY = (128, 129, 130, 131, 132, 133, 135, 138)

#: Every code `NAMES_CURSE` names from its handler rather than from the
#: spell table or the census.
FROM_HANDLERS = REFUSED + CURSE_ONLY + (73,)


def _disks():
    root = gamedisks.find(CURSE.key)
    if root is None:
        pytest.skip("no Curse of the Azure Bonds disks on this machine")
    return str(root)


@pytest.fixture(scope="module")
def dispatch():
    """The chain from the predicate to the handler tables, derived once."""
    return traitquery.dispatch_for(_disks(), CURSE)


@pytest.fixture(scope="module")
def messages():
    """Curse's own name table: spells 1-100, then the combat messages."""
    _disks()
    descriptor = spells.for_game(CURSE.key)
    for path in sorted(gamedisks.find(CURSE.key).glob(CURSE.disk_glob)):
        image = D64.open(str(path))
        if any(bytes(entry.name).rstrip(b"\xa0 ") == descriptor.file
               for entry in image.directory()):
            return spells.load_spell_names(str(path), game=CURSE.key)
    pytest.skip("no Curse side here carries the name table")


def _handler(dispatch, code: int, count: int) -> bytes:
    return traitquery.handler_bytes(_disks(), CURSE, code, count,
                                    dispatch=dispatch)


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


def test_the_handler_named_codes_have_a_name_of_their_own():
    """The eighteen `#561` could only refuse, and 73. Every one is named,
    CONFIRMED, and says something Pool of Radiance's table does not."""
    assert len(FROM_HANDLERS) == 19
    for code in FROM_HANDLERS:
        name, grade = traits.NAMES_CURSE[code]
        assert grade == "CONFIRMED", code
        assert name != traits.NAMES.get(code, (None,))[0], code
        assert traits.describe(code, CURSE) != f"trait {code}"


def test_73_no_longer_keeps_pool_of_radiances_wording():
    """`#561` kept 71, 73 and 109 on the grounds that no Curse data
    contradicted them. Curse's own handler for 73 does: it is the breath-
    weapon immunity, which is what Silver Blades calls its own 73 and is not
    a rear claw rake."""
    assert traits.NAMES_CURSE[73][0] != traits.NAMES[73][0]
    assert traits.NAMES_CURSE[73][0] == "no damage from a breath weapon"


def test_71_and_109_keep_pool_of_radiances_wording_on_purpose():
    """Their only Curse evidence is an unset spell-name pointer and no
    creature carries them, so nothing here contradicts Pool of Radiance."""
    for code in (71, 109):
        assert traits.NAMES_CURSE[code][0] == traits.NAMES[code][0]


def test_most_of_the_shared_namespace_transfers_unchanged():
    touched = set(BY_SPELL) | set(FROM_HANDLERS) | {60, 71, 105, 109}
    unchanged = [code for code in traits.NAMES if code not in touched]
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


def test_the_picker_offers_the_eighteen_that_used_to_be_bare_numbers():
    """What a player sees change: `trait 135` becomes a name, and the codes
    are offered in the picker rather than missing from it."""
    offered = {code for code, _name, _seen in effects.offered(CURSE)}
    for code in FROM_HANDLERS:
        assert code in offered, code
    assert len(effects.offered(CURSE)) == len(traits.NAMES_CURSE) - 1


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
    """Why the spell route says nothing about these three: the only row
    writing each is in no spell group and carries the unset-pointer name
    BLESS. 73 is named here from its handler instead, not from this row."""
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


def test_the_creatures_that_carry_the_handler_named_codes():
    """The ten refused codes, read straight off the 70 `MON*` templates.
    Each is the creature whose *Monster Manual* entry the handler reading
    describes: the shambling mound that engulfs, the vegepygmies an edged
    weapon barely scratches, the slug that spits acid, the beholder's eyes,
    the black dragon's breath, the owl bear's hug, the salamander's heat."""
    root = gamedisks.find(CURSE.key)
    if root is None:
        pytest.skip("no Curse of the Azure Bonds disks on this machine")
    carriers: dict[int, set[str]] = {}
    seen: set[str] = set()
    for path in sorted(root.glob(CURSE.disk_glob)):
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
        128: {"DRACOLICH"},
        129: {"BEHOLDER", "RAKSHASA"},
        130: {"RAKSHASA"},
        131: {"HELL HOUND"},
        132: {"TYRANTHRAXUS"},
        133: {"DRACOLICH"},
        135: {"DRACOLICH", "LG VEGEPYGMY", "SM VEGEPYGMY", "TYRANTHRAXUS"},
        138: {"ALIAS", "DRACANDROS", "DRAGONBAIT"},
    }
    for code, names in expected.items():
        assert carriers.get(code) == names, code
    # And 68 and 69 -- Pool of Radiance's GHOUL and DRIDER specials -- have
    # no Curse carrier at all, because Curse ships no GHOUL and no DRIDER.
    assert 68 not in carriers
    assert 69 not in carriers
    assert not any(name in ("GHOUL", "DRIDER") for names in carriers.values()
                   for name in names)


# --- the handlers the last eighteen names rest on ---------------------------

def test_the_handler_table_is_indexed_by_the_id_itself(dispatch):
    """`COMBAT $12C3` parks the id and reads the two tables at it. Every
    handler-named entry rests on this indexing, so it is pinned first."""
    assert (dispatch.ask_file, dispatch.ask_base) == ("COMBAT", 0x0800)
    assert (dispatch.low_at, dispatch.high_at) == (0xEE2A, 0xEEBC)
    assert dispatch.namespace == 146


def test_the_anchors_the_readings_stand_on(dispatch):
    """Four addresses, each pinned by a code Curse's own spell table already
    CONFIRMED: `$945F` the damage and `$A904` the damage type (Resist Fire
    tests bit 0 and halves; Resist Cold tests bit 1), `$1530` the tail that
    zeroes both, `$152B` the same only for the effect in A."""
    assert _handler(dispatch, 20, 10) == bytes.fromhex(
        "a9 01 2d 04 a9 f0 ee 4e 5f 94")
    assert _handler(dispatch, 10, 4) == bytes.fromhex("a9 02 d0 02")
    body = dispatch.body_map["COMBAT"]
    at = 0x1530 - dispatch.ask_base
    assert body[at:at + 9] == bytes.fromhex("a9 00 8d 02 a9 8d 5f 94 60")
    assert body[at - 5:at] == bytes.fromhex("cd 02 a9 d0 08")


def test_the_four_immunities_differ_only_in_the_damage_type_bit(dispatch):
    """112, 110, 135 and 73 share one tail and one `AND $A904`; what each
    loads in front of it is the whole of the difference. The bit order is
    the message table's own -- FROM FIRE, FROM COLD, FROM ELECTRICITY."""
    for code, bit in ((112, 0x01), (110, 0x02), (135, 0x04), (73, 0x20)):
        assert _handler(dispatch, code, 2) == bytes((0xA9, bit)), code
        assert traits.NAMES_CURSE[code][1] == "CONFIRMED"
    assert traits.NAMES_CURSE[135][0] == "immune to electricity"


def test_the_breath_weapons_say_breathes(dispatch, messages):
    """90, 128 and 131 all print combat message 21 through `$138F`, which is
    `BREATHES...`; 86 prints 36, `SPITS ACID`, which is also what the
    ANHKHEG's already-named acid squirt prints. A message index is the name
    table's entry `101 + n`."""
    assert messages[101 + 21] == "BREATHES..."
    assert messages[101 + 36] == "SPITS ACID"
    assert messages[101 + 19] == "ENGULFS ITS FOE"
    for code, index, length in ((90, 0x15, 28), (128, 0x15, 28),
                                (131, 0x15, 28), (86, 0x24, 12),
                                (121, 0x24, 36), (57, 0x13, 82)):
        assert bytes((0xA2, index, 0x20, 0x8F, 0x13)) in _handler(
            dispatch, code, length), code
    # 90's damage type is acid and a breath; 128's is fire, magic and a
    # breath; both take the damage from the creature's own hit-point maximum
    # at record 0x076. 131's is a flat seven points of fire.
    assert bytes.fromhex("ad 76 7c 8d 05 a9") in _handler(dispatch, 90, 40)
    assert bytes.fromhex("a9 30 8d 04 a9") in _handler(dispatch, 90, 44)
    assert bytes.fromhex("a9 29 8d 04 a9") in _handler(dispatch, 128, 44)
    assert bytes.fromhex("a9 07 8d 05 a9") in _handler(dispatch, 131, 20)


def test_the_magic_resistances_are_one_routine_and_four_percentiles(
        dispatch):
    """105, 106, 107, 124 and 129 all reach `$26DB`, which rolls d100 under
    A. 50 for the drow, 90 for the elf and 30 for the half-elf are names the
    table already had; 129's A is 100, which is what makes it total."""
    for code, percent in ((105, 50), (107, 90), (124, 30), (129, 100)):
        assert _handler(dispatch, code, 2) == bytes((0xA9, percent)), code
    assert traits.NAMES_CURSE[129][0] == "100% magic resistance"


def test_the_beholders_seven_rays(dispatch, messages):
    """87's handler fires three of seven ranged attacks a round out of
    parallel tables at `$2549`: four cast a spell at caster level 10 and
    three set a status behind a save. The seven are the beholder's own eye
    rays."""
    body = dispatch.body_map["COMBAT"]
    at = 0x2549 - dispatch.ask_base
    rays = list(body[at:at + 7])
    assert rays == [55, 10, 84, 66, 6, 46, 67]
    # The first four are spell ids in Curse's own name table...
    assert [messages[i] for i in rays[:4]] == [
        "SLOW", "CHARM PERSON", "FEAR", "CAUSE SERIOUS WOUNDS"]
    # ...and the last three are combat message indices, at `101 + n`.
    assert [messages[101 + i] for i in rays[4:]] == [
        "TURNS TO STONE", "IS KILLED", "DISAPPEARS"]
    assert traits.NAMES_CURSE[87][0] == "eye rays, three a round"


def test_the_weapon_a_vegepygmy_barely_notices(dispatch):
    """85 reads byte +7 of the attacker's `ITEMS` type entry, staged at
    `$7E8C`, and sets the damage to the bit it finds: bit 0 is the edged and
    piercing types, where bit 7 is the blunt ones 90 reads in Silver
    Blades."""
    assert _handler(dispatch, 85, 14) == bytes.fromhex(
        "20 21 14 ad 93 7e 29 01 f0 03 8d 5f 94 60")
    types = dispatch.body_map["ITEMS"]
    edged = {t for t in range(128) if types[t * 16 + 7] & 0x01}
    blunt = {t for t in range(128) if types[t * 16 + 7] & 0x80}
    assert not edged & blunt
    assert len(edged) == 18 and len(blunt) == 13


def test_only_a_blessed_quarrel_names_word_135(dispatch):
    """130 kills its carrier outright when the weapon's name word +3 is 135,
    and Curse ships exactly one template whose +3 is 135."""
    assert bytes.fromhex("ad 7f 7e c9 87") in _handler(dispatch, 130, 20)
    root = gamedisks.find(CURSE.key)
    first = sorted(root.glob(CURSE.disk_glob))[0]
    templates = items.load_item_templates(str(first), game=CURSE)
    named = {name for name, raw in templates.items() if raw[3] == 135}
    assert named == {"BLESSED QUARREL(S)"}
    assert items.load_item_names(str(first), game=CURSE)[135] == "BLESSED"


def test_the_salamanders_heat_asks_about_fire_resistance(dispatch):
    """103 adds 1d6 to its own weapon damage unless the other combatant has
    one of the three ids in the table at `$F182` -- which are the three
    Curse already calls fire resistance."""
    body = dispatch.body_map["COMBAT2"]
    assert list(body[0xF182 - 0xE000:0xF185 - 0xE000]) == [54, 61, 20]
    assert 61 in traits.NAMES_CURSE and 20 in traits.NAMES_CURSE
    assert "Fire" in traits.NAMES_CURSE[20][0]
    assert bytes.fromhex("bd 82 f1") in _handler(dispatch, 103, 15)


def test_the_owl_bears_hug_waits_for_an_attack_roll_of_18(dispatch):
    """96's first instruction loads an immediate `ECL64` patches with the
    attack d20 it has just rolled, and compares it with 18. The `STA $25A6`
    that does the patching sits directly after that roll."""
    assert _handler(dispatch, 96, 6) == bytes.fromhex("a9 ff c9 12 90 f9")
    assert bytes.fromhex("a0 14 20 6a 2f 8d a6 25") in dispatch.body_map[
        "ECL64"]


def test_the_two_holds_immobilise_their_victim(dispatch):
    """57 and 96 both apply 58 -- Curse's own `immobile` -- to the other
    combatant and park a partner id on themselves. 57 gates on having landed
    two hits this round, the counter `ECL64` zeroes and increments."""
    engulf = _handler(dispatch, 57, 82)
    assert engulf[:7] == bytes.fromhex("ad 62 94 c9 02 90 4a")
    assert bytes.fromhex("a9 3a 8d 02 a9") in engulf
    assert bytes.fromhex("a9 3a") in _handler(dispatch, 96, 30)
    assert traits.NAMES_CURSE[58][0] == "immobile"


def test_the_damage_the_three_weapon_codes_change(dispatch):
    """81 halves the weapon damage outright -- two instructions, the same
    `LSR $945F` 60 reaches on its own halving arm. 82 halves it for cold
    only and rewrites what a made save does. 84 zeroes electricity damage
    and heals 1d8 instead."""
    assert _handler(dispatch, 81, 4) == bytes.fromhex("4e 5f 94 60")
    assert _handler(dispatch, 82, 10) == bytes.fromhex(
        "a9 02 2d 04 a9 f0 03 4c a2 22")
    assert _handler(dispatch, 84, 12) == bytes.fromhex(
        "a9 04 2d 04 a9 f0 1c a9 00 8d 5f 94")


def test_133_cancels_three_effects_and_the_paralysis_column(dispatch):
    """142 Fear, 29 Ray of Enfeeblement and 68 Feeblemind each through
    `$152B`, then anything whose save byte names save column 0 -- record
    `0x09A`, `save_paralysis`, which is paralysis, poison and death magic."""
    handler = _handler(dispatch, 133, 25)
    for code in (142, 29, 68):
        assert bytes((0xA9, code, 0x20, 0x2B, 0x15)) in handler, code
    assert bytes.fromhex("ad 3b a9 29 1c") in handler
    for code in (142, 29, 68):
        assert code in traits.NAMES_CURSE


def test_138_turns_its_carrier_invisible_at_the_start_of_combat(dispatch):
    """`LDA $945C / STA $945D` makes the target itself, and the id applied is
    25, Curse's own `invisible`, with no duration."""
    assert _handler(dispatch, 138, 15) == bytes.fromhex(
        "ad 5c 94 8d 5d 94 a0 00 a9 80 a2 19 4c 31 12")
    assert traits.NAMES_CURSE[25][0] == "invisible"


def test_132_throws_a_lightning_bolt(dispatch, messages):
    """Its message goes through `$1383`, which prints the name table's entry
    directly rather than at `101 + n`."""
    assert bytes.fromhex("a2 3e 20 83 13") in _handler(dispatch, 132, 15)
    assert messages[0x3E] == "THROWS A LIGHTNING BOLT"
