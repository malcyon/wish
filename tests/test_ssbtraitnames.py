"""Secret of the Silver Blades' effect-code table, and what the picker offers.

`#497 (The trait picker offers a Secret of the Silver Blades character six
names, and nobody has ruled on whether it should offer Pool of Radiance's
129)` is the ticket. Donald ruled on 2026-09-15 that the codes be named
properly rather than the picker staying thin or borrowing Pool of Radiance's
names unmarked, and `goldbox/traits.py`'s `NAMES_SILVER_BLADES` went from six
entries to 59 by the spell table and the check lists, and to 94 -- every one
of the 90 codes the engine honours in a slot -- by reading the handler each
code dispatches.

Two kinds of test here, and the second is the one that would catch a mistake:

* the picker offers what the table names, which is the ticket's own request;
* **the entries are re-derived off the player's own disks**: 44 by reading
  that title's spell-effect table, and the handler-named ones by reading the
  handler table through `tools/c64/traitquery.py` and pinning the bytes each
  name rests on -- the damage-type bit an immunity tests, the item template
  that grants the code, the creature that carries it, the spell routine that
  writes it. A base that slips or a name that drifts from the code turns
  these red. All of them skip with no disks.

`docs/171-c64-trait-slots.md` has the readings and `cited/497` the runs.
"""

from __future__ import annotations

import pytest

from automap import gamedisks
from editor import effects
from goldbox import c64_port, items, traits
from goldbox.d64 import D64
from tools.c64 import traitquery

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


@pytest.fixture(scope="module")
def dispatch():
    """The chain from the predicate to the handler tables, derived once."""
    return traitquery.dispatch_for(_disks(), SSB)


def _overlay(dispatch, name: str) -> bytes:
    body = dispatch.body_map.get(name)
    if body is None:
        pytest.skip(f"the Secret of the Silver Blades disks here ship no {name}")
    return body


# --- the table itself -------------------------------------------------------

def test_every_entry_carries_a_grade_this_project_uses():
    """A code with no grade is a code nobody has thought about hard enough.

    91 CONFIRMED and 3 PROBABLE, and the split is not decoration: the
    picker's `Seen in this game` section is `confidence != PROBABLE`, so a
    grade here decides which half of the list a player reads a name in. The
    three left PROBABLE are 43, 44 and 89, whose handlers were not read.
    """
    grades = [grade for _name, grade in traits.NAMES_SILVER_BLADES.values()]
    assert sorted(set(grades)) == ["CONFIRMED", "PROBABLE"]
    assert grades.count("CONFIRMED") == 91
    assert grades.count("PROBABLE") == 3
    assert sorted(code for code, (_n, g) in traits.NAMES_SILVER_BLADES.items()
                  if g == "PROBABLE") == [43, 44, 89]


def test_no_entry_is_blank_or_a_bare_number():
    """A name that is the number again is what `describe` already does for an
    unnamed code, so an entry saying it would be a row with nothing in it."""
    for code, (name, _grade) in traits.NAMES_SILVER_BLADES.items():
        assert name.strip()
        assert name.strip() != str(code)
        assert not name.startswith("trait ")


def test_the_picker_no_longer_warns_off_this_titles_own_spells():
    """`#562 (The trait picker warns a Silver Blades player off six of their
    own spells, because its warning tables are Pool of Radiance's)`.

    `editor.effects.warning`'s three tables -- `MONSTER_FIRST`, `BORN_WITH`
    and `NO_HANDLER` -- were Pool of Radiance's alone and every title read
    them. 63 is Pool of Radiance's own "no handler exists"; Secret of the
    Silver Blades' own Minor Globe of Invulnerability writes it, so it
    carries no warning there. 68, 69, 71, 106, 111 and 112 are real spells in
    this title's own 113-wide namespace and Pool of Radiance's own
    monster-attack-form cut; Pool of Radiance's half of each pair is the
    control that the fix moved one title and not both.
    """
    for code in (63, 68, 69, 71, 106, 111, 112):
        assert effects.warning(code, game=SSB) == "", code
    assert effects.warning(63, game=POOL) == effects.REASON_NO_HANDLER
    for code in (68, 69, 71, 106, 111, 112):
        assert effects.warning(code, game=POOL) == effects.REASON_MONSTER, code


def test_a_monster_attack_form_this_title_shares_still_warns():
    """The control inside the title itself: 64 (a monster's poison) and 93 (a
    monster's fire resistance) are not spells here either, so the fix must
    not have simply blanked the table."""
    for code in (64, 93):
        assert effects.warning(code, game=SSB) == effects.REASON_MONSTER, code


def test_curse_of_the_azure_bonds_own_minor_globe_carries_no_warning():
    """Named in `#562`'s root cause alongside Secret of the Silver Blades:
    Curse of the Azure Bonds' own Minor Globe of Invulnerability writes 63
    too, so it drops out of `NO_HANDLER` for that title as well."""
    curse = c64_port.CURSE_OF_THE_AZURE_BONDS
    assert effects.warning(63, game=curse) == ""


def test_the_table_is_still_this_titles_own():
    """It grew from six to 59 and none of the growth is Pool of Radiance's
    table by the back door: the codes that title spends on something this one
    does not have are absent, which is what `#186` and `#196` are about."""
    table = traits.for_game(SSB)
    assert table is not traits.for_game(POOL)
    for code in (38, 84, 124, 139, 255):
        assert code not in table
    # And the four Pool of Radiance names this title's own data contradicts
    # are not reused at their old numbers.
    for code in (3, 4, 27, 35):
        assert traits.describe(code, SSB) != traits.describe(code, POOL)


# --- the picker -------------------------------------------------------------

def test_the_picker_offers_every_code_the_table_names():
    """The ticket's own request. `editor.effects.offered` is what fills the
    picker, and on this title it now offers 94 rows where it offered six."""
    offered = effects.offered(SSB)
    assert len(offered) == len(traits.NAMES_SILVER_BLADES) == 94
    assert {code for code, _name, _seen in offered} == set(
        traits.NAMES_SILVER_BLADES)
    for code, name, seen in offered:
        assert name == traits.NAMES_SILVER_BLADES[code][0]
        assert seen is (traits.NAMES_SILVER_BLADES[code][1] != "PROBABLE")


def test_the_picker_still_offers_pool_of_radiances_own_list_unchanged():
    """The control: this title's table grew and nothing else moved."""
    assert len(effects.offered(POOL)) == len(traits.NAMES) - 1   # less FILL
    assert len(effects.offered(None)) == len(effects.offered(POOL))


def test_a_code_the_engine_ignores_still_reads_as_its_number():
    """The table names what a slot can do something with and nothing else:
    84 and 100 are inside this title's 113-code namespace and on no list, so
    the number stays the honest answer for them."""
    for code in (84, 100):
        assert traits.describe(code, SSB) == f"trait {code}"
        assert traits.confidence(code, SSB) == ""


def test_every_code_the_engine_honours_is_named():
    """The residue is zero, measured rather than counted: the check lists
    and the literal asks off the disks give the 90, and each has an entry."""
    _lists, honoured = traitquery.measure(_disks(), SSB)
    assert len(honoured) == 90
    assert honoured <= set(traits.NAMES_SILVER_BLADES)
    # And the four named for the active-effects panel alone are the only
    # entries the engine does not ask a slot about.
    assert sorted(set(traits.NAMES_SILVER_BLADES) - honoured) == [
        11, 12, 34, 111]


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


def test_code_73_is_not_named_from_the_spell_row_that_appears_to_write_it():
    """73 reads like a 45th spell-named code and it is not. Raised by a code
    review on 2026-09-15 and answered no, so the answer is pinned here.

    `COMBAT2`'s name table gives one string to a spell granted at two levels,
    so a shared pointer is ordinary. Rows 95 and 96 share
    `CHARM PERSON OR MAMMAL` and are the pair that writes two different codes:
    95 writes 73 with the message `IS PROTECTED`, 96 writes 11 with
    `IS CHARMED`. 96 is the spell -- `goldbox/spells.py` has it in druid
    level 2 and has 95 in no group at all -- and 11 is already this table's
    `charmed` from CHARM PERSON at spell 10.
    """
    from goldbox import spells
    table = traitquery.spell_effects(_disks(), SSB)
    assert table[95] == ("CHARM PERSON OR MAMMAL", 73, "IS PROTECTED")
    assert table[96] == ("CHARM PERSON OR MAMMAL", 11, "IS CHARMED")

    grouped = set()
    for first, last, _who, _level in spells.for_game(SSB.key).groups:
        grouped |= set(range(first, last + 1))
    assert 96 in grouped
    assert 95 not in grouped

    # 73 is named now, and by its handler rather than by row 95: `$292C`
    # zeroes damage carrying `$A904` bit 5, the breath-weapon bit, and four
    # dragons carry it. Nothing about a charm survives.
    assert traits.NAMES_SILVER_BLADES[73] == ("immune to breath weapons",
                                              "CONFIRMED")
    assert "charm" not in traits.describe(73, SSB).lower()
    assert traits.NAMES_SILVER_BLADES[11][0] == traits.NAMES[11][0]


def test_a_shared_spell_name_usually_means_one_spell_at_two_levels():
    """Which is why row 95 cannot be waved through as a name-table fault.

    Fifteen names are shared between spell rows in Silver Blades and eleven
    have every row writing the same code. **Each of the other four contains a
    row in no spell group** -- that is the discriminator, and it is what keeps
    39 coming from HASTE rather than from row 57, which shares CURE SERIOUS
    WOUNDS' pointer and writes 39 too.
    """
    from goldbox import spells
    table = traitquery.spell_effects(_disks(), SSB)
    descriptor = spells.for_game(SSB.key)
    grouped = set()
    for first, last, _who, _level in descriptor.groups:
        grouped |= set(range(first, last + 1))

    shared: dict[str, list[int]] = {}
    for spell, (name, _code, _message) in table.items():
        shared.setdefault(name, []).append(spell)
    shared = {name: rows for name, rows in shared.items() if len(rows) > 1}
    assert len(shared) == 15

    disagree = [rows for rows in shared.values()
                if len({table[s][1] for s in rows}) > 1]
    assert len(disagree) == 4
    for rows in disagree:
        assert any(s not in grouped for s in rows)
    assert sorted(set(range(1, descriptor.last_spell + 1)) - grouped) == [
        57, 59, 60, 61, 62, 63, 64, 65, 95, 97,
        99, 100, 101, 102, 103, 104, 105, 106, 107, 108]


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


# --- the handlers, re-read off the disks ------------------------------------

def test_the_handler_table_is_indexed_by_the_id_itself(dispatch):
    """`COMBAT $12C3` is `LDX $7F6E / LDA $EF90,X / STA / LDA $F001,X`: the
    scratch the predicate parks the id in, then the two tables at the id.
    Every handler-named entry rests on this indexing, so it is pinned before
    any of them."""
    assert (dispatch.ask_file, dispatch.ask_base) == ("COMBAT", 0x0800)
    assert (dispatch.low_at, dispatch.high_at) == (0xEF90, 0xF001)
    assert dispatch.namespace == 113
    body = dispatch.body_map["COMBAT"]
    at = dispatch.ask_off + 0x15
    assert body[at:at + 3] == bytes((0xAE, 0x6E, 0x7F))        # LDX $7F6E
    assert body[at + 3] == 0xBD
    assert body[at + 4] | body[at + 5] << 8 == dispatch.low_at
    assert body[at + 9] == 0xBD
    assert body[at + 10] | body[at + 11] << 8 == dispatch.high_at


def test_an_immunity_zeroes_the_damage_where_resist_fire_halves_it(dispatch):
    """93 was "half damage from fire" by agreement with Curse. Its handler
    and Resist Fire's differ by exactly the instruction that decides it: 20
    is `LSR $945F`, 93 lands on `$14EF`, which stores zero over the damage
    and the effect. 6, 73 and 98 are the same tail behind the electricity,
    breath and cold bits."""
    root = _disks()
    handler = lambda code, n: traitquery.handler_bytes(  # noqa: E731
        root, SSB, code, n, dispatch=dispatch)
    assert handler(20, 10) == bytes.fromhex("a9 01 2d 04 a9 f0 ee 4e 5f 94")
    assert handler(93, 4) == bytes.fromhex("a9 01 d0 20")
    assert handler(6, 5) == bytes.fromhex("a9 04 4c 32 29")
    assert handler(73, 4) == bytes.fromhex("a9 20 d0 02")
    assert handler(98, 11) == bytes.fromhex("a9 02 2d 04 a9 f0 03 20 ef 14 60")
    body = dispatch.body_map["COMBAT"]
    assert body[0x14EF - 0x0800:0x14F8 - 0x0800] == bytes.fromhex(
        "a9 00 8d 02 a9 8d 5f 94 60")
    for code in (6, 73, 93, 98):
        assert traits.NAMES_SILVER_BLADES[code][1] == "CONFIRMED"
    assert traits.NAMES_SILVER_BLADES[93][0] == traits.NAMES[112][0]
    assert traits.NAMES_SILVER_BLADES[96][0] == traits.NAMES[108][0]
    # 96 cancels sleep and charm outright; 95 and 18 do the same behind a
    # d100 under 90 and 30.
    assert handler(96, 5) == bytes.fromhex("a9 35 20 ea 14")
    assert handler(95, 2) == bytes.fromhex("a9 5a")
    assert handler(18, 2) == bytes.fromhex("a9 1e")


def test_the_items_that_grant_a_handler_named_code(dispatch):
    """Seven templates carry a passive power (+15 bit 7) whose +14 is a code
    the handler pass named, and the item is what the name says."""
    root = _disks()
    templates = items.load_item_templates(root + "/" + sorted(
        p.name for p in gamedisks.find(SSB.key).glob(SSB.disk_glob))[0],
        game=SSB)
    granted = {
        "BOOTS OF SPEED": 74, "LONG SWORD VS. GIANTS": 75, "MIRROR": 72,
        "SILVER SHIELD +5": 72, "PERIAPT OF HEALTH": 76,
        "STONE OF GOOD LUCK": 78, "RING OF INVISIBILITY": 56,
        "RING OF FIRE RESISTANCE": 61,
    }
    for name, code in granted.items():
        raw = templates[name]
        assert raw[14] == code, name
        assert raw[15] & 0x80, name
        assert traits.NAMES_SILVER_BLADES[code][1] == "CONFIRMED"
    # 90 reads the weapon's type entry rather than the template: byte +7 of
    # `ITEMS`, bit 7, on the blunt types and no others among those shipped.
    types = _overlay(dispatch, "ITEMS")
    blunt = {t for t in range(128) if types[t * 16 + 7] & 0x80}
    by_type = {raw[0]: name for name, raw in templates.items()}
    assert {by_type[t] for t in blunt if t in by_type} == {
        "HAMMER +4", "MACE +4", "MORNING STAR +2", "QUARTER STAFF +4",
        "SLING", "STAFF SLING +3", "FLAIL +4"}
    assert not any(t in blunt for t in (
        templates["LONG SWORD +4"][0], templates["DAGGER +3"][0],
        templates["LONG BOW"][0]))


def test_the_creatures_carry_what_their_handlers_do(dispatch):
    """The 71 `MON*` records against the handler readings: each id lands on
    the creature the *Monster Manual* gives that ability to, and the five
    with no carrier are the five the table says rest on the handler alone."""
    carriers: dict[int, set[str]] = {}
    seen: set[str] = set()
    for path in sorted(gamedisks.find(SSB.key).glob(SSB.disk_glob)):
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
    assert len(seen) == 71
    dragons = {"ANCIENT DRAGON", "RED DRAGON", "RED HATCHLING", "WHITE DRAGON"}
    expected = {
        6: {"STORM GIANT", "DREADLORD"}, 60: {"IRON GOLEM"},
        65: {"COCKATRICE"}, 66: {"REMORHAZ"}, 67: {"12HD PYROHYDRA"},
        70: {"UMBER HULK"}, 73: dragons, 79: {"IRON GOLEM"},
        80: {"HELL HOUND"}, 81: {"GIANT SLUG"},
        83: {"WHITE DRAGON", "ANCIENT DRAGON"}, 86: {"PHASE SPIDER"},
        88: {"DREADLORD", "DRIDER"}, 90: {"GIANT SLUG"}, 92: {"DREADLORD"},
        93: {"DREADLORD", "FIRE GIANT"}, 96: {"DREADLORD"},
        98: {"DREADLORD", "FROST GIANT"}, 99: {"DREADLORD"},
        103: {"DREADLORD", "GARGOYLE", "MARGOYLE"},
        104: {"ANCIENT DRAGON", "RED DRAGON", "RED HATCHLING"},
    }
    for code, names in expected.items():
        assert carriers.get(code) == names, code
    for code in (50, 54, 77, 82, 108):
        assert code not in carriers, code


def test_dispel_evil_writes_the_dismissal_touch_and_confusion_writes_107(
        dispatch):
    """Two spell-written codes the spell table's effect byte cannot show,
    because the routine writes them beside the byte's own code.

    `COMBAT $1F96`, DISPEL EVIL's routine: 32 to the caster with the message
    IS PROTECTED, then 4 silently. `$26E8`, CONFUSION's outcome table: 27,
    107, 111 or 11 by a d100 against 50, 70, 80, 100.
    """
    body = dispatch.body_map["COMBAT"]
    assert body[0x1F96 - 0x0800:0x1FAD - 0x0800] == bytes.fromhex(
        "20 2c 8f a2 20 ad 0a a9 8d 00 a9 a9 3a 20 23 12 a2 04 a9 80 4c 23 12")
    assert body[0x26E8 - 0x0800:0x26F0 - 0x0800] == bytes(
        (27, 107, 111, 11, 50, 70, 80, 100))
    assert traits.NAMES_SILVER_BLADES[32][1] == "CONFIRMED"
    assert traits.NAMES_SILVER_BLADES[107][1] == "CONFIRMED"


def test_110_is_the_paladins_cure_disease_timer(dispatch):
    """`GEN $0C6E` seeds record `$013` = 1 and `$012` = one per five levels;
    `ECL65 $871D` spends `$012` and plants 110 on the paladin with duration
    `$C7`; the camp table at `ECL65 $9496` sends 110 at expiry to `$8657`,
    which recomputes `$012`."""
    gen = _overlay(dispatch, "GEN")
    assert gen[0x46E:0x481] == bytes.fromhex(
        "a0 01 8c 13 7c c9 06 90 06 c8 c9 0b 90 01 c8 8c 12 7c 60")
    ecl = _overlay(dispatch, "ECL65")
    assert ecl[0x72E:0x733] == bytes.fromhex("a9 6e 20 7d 38")   # has 110?
    assert ecl[0x738:0x73F] == bytes.fromhex("a9 6e 8d 69 2a a9 c7")
    assert ecl[0x74B:0x74E] == bytes.fromhex("ce 12 7c")          # DEC $7C12
    ids = ecl[0x1496:0x14A3]
    assert ids == bytes((113, 38, 12, 14, 22, 34, 109, 110, 43, 44, 62, 15, 0))
    index = ids.index(110)
    target = ecl[0x14A3 + index] | ecl[0x14AF + index] << 8
    assert target == 0x8657
    assert ecl[0x657:0x65D] == bytes.fromhex("20 4e 88 8c 12 7c")
    # And lay on hands is the twin: 109, duration $C1, record $013.
    assert ecl[0x766:0x76E] == bytes.fromhex("a9 6d 8d 69 2a a9 c1 8d")
    assert ecl[0x779:0x77C] == bytes.fromhex("ce 13 7c")
    assert traits.NAMES_SILVER_BLADES[110][1] == "CONFIRMED"
