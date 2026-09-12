from __future__ import annotations

"""Turning a DOS Pool of Radiance save into a C64 one, checked field by field.

`tests/test_dossave.py` measures the DOS file; this module checks what
`goldbox/dos.py` does with it.  The two halves of the promise in
`docs/117-save-conversion.md` are what most of these tests are:

* **losslessness** -- a DOS record read and handed back byte for byte, which
  is how a read-only decoder proves it understood the file;
* **nothing dropped silently** -- every field declared in `goldbox/dos_layout.py`
  has a disposition, and every byte of the 580-byte C64 record has a
  provenance.

**The saves are Donald's, not the repository's.**  They live in his unpacked
Steam copy of *Forgotten Realms: The Archives*; set `$FR_ARCHIVES` to point
somewhere else.  With no archives the file-reading tests skip, which is what
CI does -- the table tests above them do not need a save at all.
"""


import pathlib

import gamedata
import pytest
import yaml
from gamedata import needs_disks
from test_dossave import _game_dirs, _save_dir, needs_dos_saves

from goldbox import (
    areas,
    c64_codec,
    c64_port,
    dos_codec,
    dos_port,
    levels,
    levelup,
    neutral,
    savegame,
    spells,
    world_state,
)
from goldbox import dos_savegame as sg
from goldbox.layout import RECORD_SIZE as C64_RECORD_SIZE

# --- the tables, which need no save -----------------------------------------

def test_the_layout_tiles_the_record():
    """Every one of the 285 bytes belongs to exactly one entry, and every one
    of the item record's 63 likewise. `_build` raises on an overlap, so this
    is the other half: nothing falls out of the bottom."""
    assert sum(f.size for f in dos_port.LAYOUT) == dos_port.RECORD_SIZE
    assert sum(f.size for f in dos_port.ITEM_LAYOUT) == dos_port.ITEM_SIZE
    offsets = [f.offset for f in dos_port.LAYOUT]
    assert offsets == sorted(offsets)


def test_every_declared_field_has_a_disposition():
    """The rule `docs/117` sets: a DOS field with no C64 home is *reported*.

    A field declared in the layout and named nowhere in `DIRECT`,
    `TRANSFORMED` or `DROPPED` would be one dropped in silence, which is the
    failure this test exists to make impossible.
    """
    declared = {f.name for f in dos_port.LAYOUT
                if not f.name.startswith("gap_")}
    assert declared - set(dos_codec.field_disposition()) == set()
    assert set(dos_codec.field_disposition()) - declared == set()


def test_the_spell_id_space_is_shared():
    """DOS byte *n* of the spellbook is spell id *n + 1*, and the ids are the
    C64's own -- the DOS array's cleric-1 / mage-1 / cleric-2 / mage-2 /
    cleric-3 / mage-3 runs are `goldbox/spells.py`'s group boundaries exactly."""
    bounds = [(lo, hi) for lo, hi, _, _ in spells.SPELL_GROUPS]
    assert bounds == [(1, 8), (9, 21), (22, 28), (29, 35), (36, 44), (45, 55)]
    # 56 DOS bytes hold ids 1..56; the C64's seven bytes hold bits 1..55.
    assert dos_port.SPELLBOOK_SPELLS == 56
    assert spells.LAST_SPELLBOOK_SPELL == 55


def _plain_row_character(race: int, constitution: int = 13,
                         game: str = "pool-of-radiance"
                         ) -> neutral.NeutralCharacter:
    """A DOS-read neutral fighter 1, holding the plain class row DOS stores.

    `(14, 15, 16, 17, 17)` is the level-1 fighter row `test_levels.py`'s own
    `test_the_modifier_that_made_two_level_one_fighters_differ` measures --
    what a DOS record carries whether or not the character's race takes the
    constitution bonus, since DOS applies that bonus on the roll rather than
    in the stored bytes.
    """
    char = neutral.NeutralCharacter("DOS", game=game)
    char.set("race", race, "test fixture")
    char.set("constitution", constitution, "test fixture")
    char.set("levels", {"fighter": 1}, "test fixture")
    for name, value in zip(
            ("save_paralysis", "save_petrification", "save_wands",
             "save_breath", "save_spell"), (14, 15, 16, 17, 17)):
        char.set(name, value, "test fixture")
    return char


def test_a_dwarf_gnome_or_halfling_gets_the_c64s_own_saves_not_the_dos_row():
    """`#311 (A DOS dwarf, gnome or halfling converted to the C64 loses his
    constitution bonus to saving throws, because the C64 keeps it inside the
    five stored bytes)`.

    DOS keeps the plain class row and applies the bonus on the roll; the C64
    subtracts it into the five bytes on the way in.  A converted dwarf's
    record should hold what `goldbox.levels.saving_throws` computes, not the
    plain row `DIRECT` copied in.
    """
    plain = (14, 15, 16, 17, 17)
    bonus = levels.constitution_save_bonus(13)
    assert bonus == 3
    for race in (1, 3, 5):                        # dwarf, gnome, halfling
        rec, _ = c64_codec.write(_plain_row_character(race))
        got = tuple(rec.get(n) for n in
                    ("save_paralysis", "save_petrification", "save_wands",
                     "save_breath", "save_spell"))
        assert got == tuple(v - bonus for v in plain), race


def test_a_human_still_gets_the_plain_row():
    """The other half of the same check: nobody but a sturdy race moves."""
    rec, _ = c64_codec.write(_plain_row_character(race=7))
    got = tuple(rec.get(n) for n in
                ("save_paralysis", "save_petrification", "save_wands",
                 "save_breath", "save_spell"))
    assert got == (14, 15, 16, 17, 17)


_THIEF_SKILL_FIELDS = (
    "thief_pick_pockets", "thief_open_locks", "thief_find_traps",
    "thief_move_silently", "thief_hide_in_shadows", "thief_hear_noise",
    "thief_climb_walls", "thief_read_languages")


def _thief_character(race: int, dexterity: int, stored: tuple[int, ...],
                     thief_level: int = 1,
                     game: str = "pool-of-radiance"
                     ) -> neutral.NeutralCharacter:
    """A DOS-read neutral thief, holding DOS's own eight stored percentages."""
    char = neutral.NeutralCharacter("DOS", game=game)
    char.set("race", race, "test fixture")
    char.set("dexterity", dexterity, "test fixture")
    char.set("levels", {"thief": thief_level}, "test fixture")
    for name, value in zip(_THIEF_SKILL_FIELDS, stored):
        char.set(name, value, "test fixture")
    return char


def test_a_converted_halfling_thief_gets_the_c64s_own_skills_not_dos():
    """`#431 (A converted halfling thief keeps the other port's skill
    percentages, because the two ports ship different halfling rows)`.

    WISHTHI, thief 1, halfling, dexterity 12: DOS's own record holds
    `35 30 25 20 25 15 70 0`.  A copy would leave the C64 record holding
    those same eight bytes, which its own trainer would never write --
    `35 30 30 30 15 -5 80 -5` is what `GEN $1FEC` gives the same character.
    """
    stored = (35, 30, 25, 20, 25, 15, 70, 0)
    rec, _ = c64_codec.write(_thief_character(race=5, dexterity=12,
                                              stored=stored))
    got = tuple(rec.get(n) for n in _THIEF_SKILL_FIELDS)
    assert got == (35, 30, 30, 30, 15, -5, 80, -5)


def test_a_dwarf_thief_still_gets_a_c64_specific_number():
    """The dwarf is the control `#431` names: 7 of 8 columns already agree,
    and the eighth -- read languages -- is where DOS clamps a negative to
    zero and the C64 stores the byte. A copy would carry DOS's clamped 0."""
    stored = (30, 35, 35, 15, 10, 10, 75, 0)     # DOS: read languages clamped
    rec, _ = c64_codec.write(_thief_character(race=1, dexterity=15,
                                              stored=stored))
    got = tuple(rec.get(n) for n in _THIEF_SKILL_FIELDS)
    assert got == (30, 35, 35, 15, 10, 10, 75, -5)


def test_a_curse_thief_gets_the_table_row_rather_than_what_dos_stored():
    """Curse ships the same racial table on both ports, so this is not
    `#431 (A converted halfling thief keeps the other port's skill
    percentages, because the two ports ship different halfling rows)`'s
    reason -- it is `#440 (A Curse thief converted between DOS and the C64
    arrives seven points off, because DOS stores a stack leftover in all
    eight skill columns)`'s.

    DOS Curse's own routine adds an uninitialised stack byte to all eight
    columns (`#437 (A Curse thief's stored skills sit seven points above the
    rows the engine's own tables give)`, `GAME.OVR 0x03B74A`), so what the
    source record holds is not what any table produces. The C64 record gets
    the clean row computed here, and the eighth column is where the two
    ports visibly part: DOS clamps a negative read-languages to zero and the
    C64 stores the byte.

    This test asserted the copy until 2026-09-08, which is the behaviour
    `#440` fixed.
    """
    stored = (35, 30, 25, 20, 25, 15, 70, 0)
    rec, _ = c64_codec.write(_thief_character(
        race=5, dexterity=12, stored=stored,
        game="curse-of-the-azure-bonds"))
    got = tuple(rec.get(n) for n in _THIEF_SKILL_FIELDS)
    want = levels.thief_skills(1, 5, "curse-of-the-azure-bonds", dexterity=12)
    assert got == tuple(want)
    assert got != stored
    assert got[7] == -5


def test_the_class_level_permutation_covers_every_c64_slot():
    """DOS indexes its eight level slots by class *number*, the C64 by class
    *bit*. Druid and monk have no C64 slot; nothing else is lost."""
    fields = [f for _, _, f in dos_codec.CLASS_LEVEL_SLOTS if f]
    assert set(fields) == {"level_cleric", "level_fighter", "level_paladin",
                           "level_ranger", "level_magic_user", "level_thief"}
    assert [n for n, _, f in dos_codec.CLASS_LEVEL_SLOTS if f is None] == [1, 7]


def test_item_to_c64_is_the_harness_projection():
    """One copy of the projection. `tools/dosbox.py` re-exports this one."""
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent
                           / "tools"))
    import dosbox
    assert dosbox.item_to_c64 is dos_codec.item_to_c64


# --- the record, against real files -----------------------------------------

def _records():
    where = _save_dir()
    if where is None:
        pytest.skip("needs a DOS save; set FR_ARCHIVES to the archives")
    out = [dos_codec.read_character(p) for p in
           sorted(where.glob("*.SAV")) + sorted(where.glob("*.CHA"))
           if p.stat().st_size == dos_port.RECORD_SIZE]
    if not out:
        pytest.skip("no DOS Pool of Radiance character records here")
    return out


@needs_dos_saves
def test_a_record_is_handed_back_unchanged():
    """Losslessness, in the form the DOS side can have it.

    The DOS file is read-only in practice -- `wish` never writes one -- but a
    reader has to be able to prove it understood the file, and handing the
    bytes back is that proof.
    """
    where = _save_dir()
    checked = 0
    for path in sorted(where.glob("*.SAV")) + sorted(where.glob("*.CHA")):
        if path.stat().st_size != dos_port.RECORD_SIZE:
            continue
        assert dos_codec.read_character(path).to_bytes() == path.read_bytes()
        checked += 1
    assert checked >= 24


@needs_dos_saves
def test_the_encumbrance_identity_balances():
    """`encumbrance = money + sum(weight x quantity)`, through the reader.

    The cheapest whole-record check there is: self-contained arithmetic across
    the money block, the item file and one derived field, so it confirms the
    money offsets, the 63-byte stride, the weight offset and the byte order
    at once. Two records are known to miss it and are PROBABLY edited --
    `CHRDATA4.SAV` (GILES) and `CHRDATA5.SAV` (ASTRID), whose cached line and
    stored total agree with each other against a round quantity byte, where
    the engine itself keeps the quantity byte and the stored total in step
    and lets only the cached line go stale (`docs/125-bug-notes.md` N19). A
    different saved slot for each of those same two characters,
    `CHRDATB4.SAV` and `CHRDATB5.SAV`, balances exactly, so the exception is
    the file rather than the name. Every other record here has to balance
    exactly -- a miss anywhere else is a reader regression, not a known edit.
    """
    known_misses = {"CHRDATA4.SAV", "CHRDATA5.SAV"}
    where = _save_dir()
    paths = [p for p in sorted(where.glob("*.SAV")) + sorted(where.glob("*.CHA"))
             if p.stat().st_size == dos_port.RECORD_SIZE]
    assert len(paths) >= 24
    unexplained = []
    for path in paths:
        char = dos_codec.read_character(path)
        if char.get("encumbrance") != char.expected_encumbrance() \
                and path.name not in known_misses:
            unexplained.append((path.name, char.name))
    assert unexplained == [], f"unexplained miss: {unexplained}"


@needs_dos_saves
def test_an_export_carries_no_items():
    """An export zeroes the item count, which is the one systematic
    difference between a save slot and a `.CHA`. A stale `.ITM` sitting beside
    it must not be read as the character's inventory -- and the archives hold
    exactly that."""
    where = _save_dir()
    checked = 0
    for path in sorted(where.glob("*.CHA")):
        char = dos_codec.read_character(path)
        assert char.items == ()
        assert char.get("encumbrance") == char.expected_encumbrance()
        checked += 1
    assert checked >= 6


@needs_dos_saves
def test_every_known_spell_is_one_its_owner_could_cast():
    """The transpose, checked the only way that does not assume it.

    Every byte set in the DOS spellbook falls in a `goldbox/spells.py` group whose
    class the character has, with no crossover in either direction: a level-1
    cleric sets exactly the eight first-level cleric ids, a level-3 magic-user
    sets the thirteen first-level and seven second-level magic-user ids.
    """
    casters = 0
    for char in _records():
        known = char.spells_known
        if not known:
            continue
        casters += 1
        bits = char.get("class_bits")
        for sid in known:
            group = spells.spell_group(sid)
            assert group is not None, (char.name, sid)
            school = group[0]
            assert (school == "cleric" and bits & 2) or \
                   (school == "magic-user" and bits & 1), (char.name, sid,
                                                           school)
    assert casters >= 8


@needs_dos_saves
def test_a_first_level_cleric_knows_the_eight_first_level_cleric_spells():
    """The sharpest single check on the ordering: eight bytes, in a row, at
    the start, and `goldbox/spells.py` says ids 1-8 are cleric level 1."""
    seen = 0
    for char in _records():
        levels = char.class_levels
        if levels != {"cleric": 1}:
            continue
        assert char.spells_known == list(range(1, 9)), char.name
        seen += 1
    assert seen >= 2


@needs_dos_saves
def test_conversion_accounts_for_every_byte():
    """`docs/117` makes this the test that replaces a round trip: for any
    offset in the output, say where that byte came from."""
    for char in _records():
        rec, report = dos_codec.to_c64_record(char)
        assert len(rec.to_bytes()) == C64_RECORD_SIZE
        assert report.unaccounted == [], (char.name, report.unaccounted[:8])
        assert report.dropped


@needs_dos_saves
def test_the_converted_record_says_what_the_dos_one_said():
    """Field for field, on everything the two ports encode the same way."""
    for char in _records():
        rec, _ = dos_codec.to_c64_record(char)
        assert rec.name == char.name
        assert rec.strength == char.get("strength")
        assert rec.exceptional_strength == char.get("exceptional_strength")
        assert rec.race == char.get("race")
        # The class byte copies because the two ports share one 18-entry
        # table; the bitmask copies because they share the bit order.
        assert rec.char_class == char.get("char_class")
        assert rec.class_bits == char.get("class_bits")
        assert rec.age == char.get("age")
        assert rec.hp_max == char.get("hp_max")
        assert rec.get("hp_current") == char.get("hp_current")
        assert rec.level == char.get("level")
        # `#366 (A converted magic-user or thief arrives with the other
        # port's THAC0, because the two ports ship different tables and
        # the conversion copies the byte)`: the C64's own table disagrees
        # with DOS's for a magic-user 1-5 or a thief 1-4, so the byte is
        # recomputed through the C64's table rather than copied from DOS's.
        assert rec.thac0_base_value == levels.base_thac0(char.class_levels)
        assert rec.get("experience") == char.get("experience")
        assert spells.spells_known(rec.to_bytes()) == char.spells_known
        # Memorised spells: DOS fills from the end, the C64 from the start.
        assert [b for b in rec.get_raw("spells_memorised") if b] \
            == char.spells_memorised
        # The per-class levels, permuted.
        for _, name, field in dos_codec.CLASS_LEVEL_SLOTS:
            if field:
                assert rec.get(field) == char.class_levels.get(name, 0)


@needs_dos_saves
def test_the_converted_items_are_the_dos_items():
    """Sixteen fixed C64 slots against a DOS chain of 63-byte records."""
    from goldbox.items import ITEM_SIZE as C64_ITEM_SIZE

    converted = 0
    for char in _records():
        rec, _ = dos_codec.to_c64_record(char)
        inv = rec.get_raw("inventory")
        for n, item in enumerate(char.items[:16]):
            assert inv[n * C64_ITEM_SIZE:(n + 1) * C64_ITEM_SIZE] \
                == item.to_c64()
            converted += 1
        # Nothing past the last item.
        rest = inv[len(char.items[:16]) * C64_ITEM_SIZE:]
        assert rest == bytes(len(rest))
    assert converted >= 50


@needs_dos_saves
def test_a_character_with_no_thief_level_carries_no_thief_skills():
    """A cheap sanity check on the eight-byte block, and on the permutation
    that puts the thief level where the C64 keeps it."""
    for char in _records():
        rec, _ = dos_codec.to_c64_record(char)
        if rec.get("level_thief"):
            continue
        assert all(rec.get(f) == 0 for f in
                   ("thief_pick_pockets", "thief_open_locks",
                    "thief_find_traps", "thief_climb_walls"))


@needs_dos_saves
def test_innate_and_granted_effects_reach_a_trait_slot_and_running_ones_do_not():
    """The `.SPC` file splits three ways, and the C64 trait slots now take
    two of them (#232).

    Curse's own importer keeps exactly the innate racial ids out of a Pool of
    Radiance `.spc`; `goldbox/traits.py` names the same numbers the same way --
    107 is elf sleep resistance and 124 is the half-elf's on both sides.  A
    ring or a girdle grants an effect the same way, at duration zero and
    outside `INNATE_EFFECTS`, and it now reaches a free trait slot too, the
    way the item's own READY would put it there
    (`docs/171-c64-trait-slots.md`, #252). A spell still counting down --
    nonzero duration -- must not reach the trait slots: a Bless with four
    rounds left on it would arrive as a permanent bonus, which is a defect a
    player can see.

    **A running effect is reported nowhere.**  Donald, 2026-08-27: *"For
    running effects, that would expire after a certain period of time, we do
    not need to report those. The user will not expect this to carry over,
    so reporting it is unnecessary."*  An innate effect that cannot be
    converted is the opposite case and is still reported -- `write`'s gnome
    line is the one specimen of it.  So what this asserts is "innate and
    granted are written, running is not, and none of the three is ever
    reported", which is the thing a player would meet.
    """
    innate = running = granted = 0
    for char in _records():
        rec, report = dos_codec.to_c64_record(char)
        slots = [b for b in rec.get_raw("item_effects") if b]
        for e in char.effects:
            eid = e[0]
            duration = int.from_bytes(e[1:3], "little")
            if eid in dos_codec.INNATE_EFFECTS:
                assert eid in slots, (char.name, eid)
                innate += 1
            elif duration != 0:
                running += 1
                assert eid not in slots, (char.name, eid)
            else:
                granted += 1
                assert eid in slots, (char.name, eid)
        assert not [d for d in report.dropped if d.startswith(".SPC effect")], \
            char.name
    assert innate >= 5
    assert running >= 2
    assert granted >= 1


def test_an_item_granted_effect_reaches_a_c64_trait_slot():
    """#232: the ring's id used to be reported as a loss and nothing else --
    now it is written where the C64's own READY would write it.

    `por-item-granted` is the one DOS record anybody has that the game
    itself wrote an item's grant into: THRENDER GRONE's flail readied with
    effect 61 (wearing a Ring of Fire Resistance) and power `0x80`, saved by
    the engine to slot D.  Its `.SPC` is four racial ids, a `BLESS` at two
    minutes, and the ring's `61 00 00 0C 00`.  The C64 record must carry the
    four racial ids and 61 into its ten trait slots and must not carry the
    `BLESS`, which is a running spell and needs no report either
    (Donald, 2026-08-27).
    """
    from test_doswriter import _item_granted_specimen

    from goldbox import traits

    path = _item_granted_specimen()
    if path is None:
        pytest.skip("no por-item-granted specimen; "
                    "tools/dosspcexpiry.py ready makes one")
    char = dos_codec.read_character(path)
    rec, rep = dos_codec.to_c64_record(char)
    slots = [b for b in rec.get_raw("item_effects") if b]
    assert sorted(slots) == sorted([90, 97, 26, 47, 61]), slots
    said = traits.describe(61)
    assert not any(said in d for d in rep.dropped)
    assert not any("trait slot" in w for w in rep.warnings)


@needs_dos_saves
def test_every_dropped_field_reaches_the_player_unless_the_c64_derives_it():
    """What the import's `Conversion Info` pane shows of the drop list, which
    since 2026-09-06 is all of it.  Donald, having seen the pane: *"do not
    show dropped fields if they are derived in the new game. Show others
    for now. I will refine them as we go."*

    He then read the two lines that produced and took both out on the same
    day, which is the second half of the rule: **a field is shown only when
    a player loses something by it.**  `icon_dimension` is how many squares
    a figure covers and every player character covers one; `turn_class` is
    the row of the turning table an undead creature answers to, and a
    cleric's own ability is `turn_power`, which is computed and stored
    (#288).  Neither costs anybody anything, so neither has a sentence.

    So a field reaches a player when it is on `DROPPED` **and**
    `DROPPED_PLAYER_TEXT` has words for it.  `DERIVED` and `CONSTANTS` --
    what the C64 recomputes on load, and what holds the same value in every
    record anybody has read (#324) -- are not on `DROPPED` at all and can
    never reach it.

    `UNREPORTED_DROPS` stays gone, and this fails if it comes back: it
    silenced fields by an agent's judgement of what a player would notice,
    which is the judgement Donald took back.  A silence now costs somebody
    writing a reason into the block above the dict, where he can read it.

    **Nothing measured left the code.**  Every name is still in `DROPPED`,
    so `field_disposition` still accounts for it and
    `test_every_declared_field_has_a_disposition` still holds.
    """
    assert not hasattr(dos_codec, "UNREPORTED_DROPS")
    silent = ({name for name, *_ in dos_codec.DERIVED}
              | {name for name, _ in dos_codec.CONSTANTS})
    assert silent.isdisjoint(dict(dos_codec.DROPPED))

    seen = 0
    for char in _records():
        _rec, report = dos_codec.to_c64_record(char)
        for name, _why in dos_codec.DROPPED:
            sentence = dos_codec.DROPPED_PLAYER_TEXT.get(name)
            if sentence:
                assert sentence in report.dropped, (char.name, name)
            else:
                assert not [d for d in report.dropped if name in d], \
                    (char.name, name, "silent, so nothing names it")
        for name in silent:
            assert not [d for d in report.dropped if name in d], \
                (char.name, name)
        seen += 1
    assert seen >= 6, "needs a party to check against"


def test_no_dropped_reason_carries_developer_detail():
    """`.claude/rules/gui-text.md`: no memory address, file offset or bare
    issue number in front of a player.  `DROPPED`'s and `WRITE_DROPPED`'s own
    `why` text is what reaches `editor/dosimport.py`'s Import pane and the
    DOS writer's own report, verbatim -- a hex offset or a bare `#NNN`
    written into one entry reaches a player the same way `field_10c_10f`'s
    and `field_83_87`'s did after
    #235 (Two unattributed DOS byte ranges in the combat tail are dropped
    converting to C64, and nobody knows what they hold), and the way
    `portrait_head`'s already-shipped `(#57)` did before this test existed.

    **This now checks the composed line, not only the `why` clause.**
    `to_neutral` used to put an unconditional `DOS {name} @{offset:#05x}:`
    in front of every one of the ~15 lines in the table, which would have
    failed this test against every entry before
    #244 (Every DROPPED entry's composed line carries a raw hex file offset
    in front of the player, not only the two #235 fixed) took the prefix
    out. Checking `report.dropped` itself, over a real conversion, is what
    stops that returning.
    """
    import re

    hex_offset = re.compile(r"0[xX][0-9A-Fa-f]+|\$[0-9A-Fa-f]+")
    bare_issue = re.compile(r"#\d+")
    for name, why in dos_codec.DROPPED:
        assert not hex_offset.search(why), (name, why)
        assert not bare_issue.search(why), (name, why)
    for name, why in dos_codec.WRITE_DROPPED:
        assert not hex_offset.search(why), (name, why)
        assert not bare_issue.search(why), (name, why)


@needs_dos_saves
def test_no_composed_dropped_line_carries_developer_detail():
    """The same guard as `test_no_dropped_reason_carries_developer_detail`,
    against `report.dropped` itself rather than the `why` clauses that feed
    it -- the composed line is what a player actually reads in
    `editor/dosimport.py`'s Import pane, through `dropped_text`.
    """
    import re

    hex_offset = re.compile(r"0[xX][0-9A-Fa-f]+|\$[0-9A-Fa-f]+")
    bare_issue = re.compile(r"#\d+")
    seen = 0
    for char in _records():
        _rec, report = dos_codec.to_c64_record(char)
        for line in report.dropped:
            assert not hex_offset.search(line), (char.name, line)
            assert not bare_issue.search(line), (char.name, line)
        seen += 1
    assert seen >= 6, "needs a party to check against"


def test_every_dropped_name_has_player_text():
    """A sentence in `DROPPED_PLAYER_TEXT` names a field that is really on
    `DROPPED`, and every sentence a player reads opens with a capital.

    **The reverse does not hold**, and that is deliberate. A name with no
    sentence is shown nothing, which is how `icon_dimension` and
    `turn_class` left the pane on 2026-09-06: Donald read both, asked what
    they meant, and neither turned out to cost a player anything -- all
    player characters cover one square on the combat floor, and the turning
    row belongs to the undead creature rather than to the cleric turning
    it, whose own ability `goldbox/derive.py` computes and the writer
    stores (#288).

    So this pins the direction that can go wrong. A sentence with no field
    behind it is text nobody can ever read; a field with no sentence is a
    deliberate silence, and the block above the dict says why for each.
    """
    assert set(dos_codec.DROPPED_PLAYER_TEXT) <= set(dict(dos_codec.DROPPED))
    for text in dos_codec.DROPPED_PLAYER_TEXT.values():
        assert text[:1].isupper(), text


def test_the_portrait_is_transformed_and_not_dropped_in_any_title():
    """The menu is stored (`goldbox.portraits.POOL_OF_RADIANCE_MENU`), so
    there is no longer a Pool of Radiance conversion without it and the
    pair's disposition is a rule rather than a loss.  Curse and Silver
    Blades draw no sheet portrait (#300), and theirs says so in the same
    row rather than calling a face nobody draws a drop."""
    for title in (dos_codec.POOL_OF_RADIANCE, dos_codec.CURSE_OF_THE_AZURE_BONDS):
        disposition = dos_codec.field_disposition(title)
        for name in ("portrait_head", "portrait_body"):
            assert not disposition[name].startswith("dropped:"), \
                (title, name, disposition[name])
    assert "portrait_head" not in dict(dos_codec.DROPPED)
    assert "portrait_head" in dict(dos_codec.TRANSFORMED)


def test_a_character_with_no_portrait_is_not_reported_as_having_lost_one():
    """Position 0 is not a menu entry -- it is how the record says "no face
    chosen" -- and every character this project converts from the C64, or
    back off an Amiga disk that came from one, carries it.  Reporting that as
    a portrait that "could not be converted" tells a player something false
    about their own save (#377, A converted character with no portrait at
    all is shown a message saying its portrait could not be converted).

    A synthetic all-zero Pool of Radiance record needs no game disk: it is a
    fact about `goldbox.portraits.PortraitTables._art`'s own `1 <= n <=
    len(table)` gate, not a measurement of the game.
    """
    from goldbox.portraits import PortraitTables

    tables = PortraitTables(heads=tuple(range(1, 15)),
                            bodies=tuple(range(1, 13)),
                            source="synthetic, for this test")
    blank = dos_codec.DosCharacter(bytes(dos_codec.POOL_OF_RADIANCE.record_size))
    neutral = dos_codec.to_neutral(blank, portraits=tables)
    assert not [d for d in neutral.dropped if "portrait" in d.lower()], \
        neutral.dropped

    # A position the menu genuinely cannot answer for -- not zero -- still
    # gets the line: only "no face chosen" is silent.
    raw = bytearray(bytes(dos_codec.POOL_OF_RADIANCE.record_size))
    raw[dos_port.FIELDS_BY_NAME["portrait_body"].offset] = 13  # outside
    odd = dos_codec.DosCharacter(bytes(raw))                            # the menu
    neutral = dos_codec.to_neutral(odd, portraits=tables)
    assert [d for d in neutral.dropped if "portrait (body)" in d.lower()], \
        neutral.dropped


def test_every_derived_field_carries_the_run_that_demonstrated_it():
    """#324 (The import pane tells a player nine fields could not be
    converted that the C64 recomputes for itself): `DERIVED`'s third field
    is the evidence that moved a name off `DROPPED`, and a row with nothing
    there is a row nobody has earned yet.
    """
    for name, why, run in dos_codec.DERIVED:
        assert why.strip(), name
        assert run.strip(), name


@needs_disks
def test_no_dos_derived_or_constant_field_reaches_the_import_pane():
    """#324: converting `WISH-SPEC-por-party-l1-intown` slot E through
    `editor.dosimport.rehearse` -- the same call `File > Import` makes --
    shows no line for item bookkeeping, heap state, the running-effects
    link, which hand holds a weapon or the five constant bytes at
    `field_83_87`.  What is left on the pane is exactly the lines still on
    `DROPPED`, in their player text -- shown since 2026-09-06 (Donald:
    *"Show others for now"*) -- and nothing else.
    """
    from editor.dosimport import GameFiles, rehearse
    from goldbox.d64 import load_payload
    from goldbox.iconparts import IconParts

    where = gamedata.disk_dir()
    if where is None:
        pytest.skip("needs the game disks; set POR_DISKS to where they are")
    icon = animate = None
    for disk in sorted(where.glob("POOL*.[dD]64")):
        try:
            icon = icon if icon is not None else IconParts.load(str(disk))
        except Exception:
            pass
        try:
            animate = animate if animate is not None else \
                load_payload(str(disk), dos_codec.ANIMATE_FILE)
        except Exception:
            pass
    if icon is None or animate is None:
        pytest.skip("no POOL disk here carries SPELLE64/SPELLN64 or ANIMATE00")
    folder = gamedata.specimen("por-party-l1-intown")
    conversion = rehearse(folder, "E", GameFiles(icon=icon, animate=animate))
    keywords = ("item list", "internal game state", "running-effects list",
               "which hand is holding", "five bytes that make no difference")
    for line in conversion.report.dropped:
        lowered = line.lower()
        for keyword in keywords:
            assert keyword not in lowered, line
    assert sorted(conversion.report.dropped) == \
        sorted(dos_codec.DROPPED_PLAYER_TEXT.values()), conversion.report.dropped


def test_no_player_text_says_something_was_not_carried():
    """#270 (A conversion's drop text still tells the player a field was
    "not carried", the word AGENTS.md banned tonight): every sentence already
    named the loss in the clause after the comma -- "not carried, so the
    character arrives without it" -- so the fix is the three words before it,
    not a rewrite of what the line says.

    Checked in the tables directly, across all three codecs that build a
    player-facing drop sentence this way, rather than only through one
    conversion's own output.
    """
    from goldbox import amiga_later, c64_codec

    tables = (dos_codec.DROPPED_PLAYER_TEXT.values(),
             c64_codec.NO_C64_STATUS.values(),
             amiga_later.LATER_DROPPED_PLAYER_TEXT.values())
    for values in tables:
        for text in values:
            assert "not carried" not in text, text
            assert "carried separately" not in text, text


def test_a_status_drop_line_does_not_say_not_carried():
    """The inline-composed sentence, not just the tables: a status the C64
    has no value for is built with an f-string in `goldbox/c64_codec.py`, so
    the table guard above cannot see it."""
    from goldbox import c64_codec
    from goldbox.layout import Confidence
    from goldbox.neutral import NeutralCharacter

    char = NeutralCharacter("test")
    char.set("status", "made up: not a real status", "made up",
             Confidence.CONFIRMED)
    _rec, rep = c64_codec.write(char)
    assert rep.dropped, "expected the made-up status to be reported dropped"
    for line in rep.dropped:
        assert "not carried" not in line, line


def test_the_identity_byte_is_written_for_all_three_c64_titles():
    """Donald, 2026-09-05: "Yes, write the identity byte. No, don't tell the
    user about it." `docs/170-c64-identity-pair.md`: only Pool of Radiance's
    own GEN draws the pair at `0x0E6`-`0x0E7`, but the field exists in every
    title's 580-byte layout and nothing reads it back in any of them, so
    `goldbox.c64_codec.write` puts it there for Curse of the Azure Bonds and
    Secret of the Silver Blades too, and says nothing about it either way."""
    from goldbox import c64_codec, c64_port
    from goldbox.layout import Confidence
    from goldbox.neutral import NeutralCharacter

    for game in (c64_port.POOL_OF_RADIANCE, c64_port.CURSE_OF_THE_AZURE_BONDS,
                c64_port.SECRET_OF_THE_SILVER_BLADES):
        char = NeutralCharacter("test", game=game)
        char.set("unnamed_0ab", 0x57, "made up", Confidence.CONFIRMED)
        rec, rep = c64_codec.write(char)
        assert rec.get_raw("identity_pair") == b"\x57\x00", game.key
        assert not [d for d in rep.dropped if "identity" in d.lower()], \
            (game.key, rep.dropped)


# --- the saved game ----------------------------------------------------------

def _savgam(slot: str) -> bytes:
    where = _save_dir()
    if where is None:
        pytest.skip("needs a DOS save; set FR_ARCHIVES to the archives")
    path = where / f"SAVGAM{slot}.DAT"
    if not path.exists():
        pytest.skip(f"no SAVGAM{slot}.DAT here")
    return path.read_bytes()


@needs_dos_saves
def test_the_quest_flags_narrow_to_bytes():
    """A copy with a stride change: read the DOS word, write the C64 byte.

    Every nonzero word in the 217-entry window fits in a byte, so nothing is
    lost by narrowing. The counter counts: `$4AC1`, the commissions counter
    with ten `ADD 1` sites, reads 0, 1 and 2 across slots J, B and A, in the
    order the parties progressed.
    """
    counts = {}
    for slot in "JBA":
        save = _savgam(slot)
        flags = dos_codec.quest_flags(save)
        assert len(flags) == dos_codec.FLAGS_LAST - dos_codec.FLAGS_FIRST + 1
        for addr in range(dos_codec.FLAGS_FIRST, dos_codec.FLAGS_LAST + 1):
            word = sg.word(save, addr)
            assert word <= 0xFF, (slot, hex(addr), word)
        counts[slot] = flags[0x4AC1 - dos_codec.FLAGS_FIRST]
    assert counts["J"] < counts["B"] < counts["A"]


@needs_dos_saves
def test_the_sokal_keep_flags_are_set_together_or_not_at_all():
    """`work/reports/quest-flags.md` names six ECL15 flags that a party which
    has taken the keep sets to 255. A base off by one would straddle them."""
    addresses = (0x4A21, 0x4A26, 0x4A27, 0x4A28, 0x4A29, 0x4AD7)
    states = set()
    for slot in "JBA":
        save = _savgam(slot)
        values = {sg.word(save, a) for a in addresses}
        assert values in ({0}, {255}), (slot, values)
        states.add(frozenset(values))
    assert len(states) == 2, "no save differs, so this proves nothing"


@needs_dos_saves
def test_the_party_square_and_area_read_out():
    """Four reads and a halving. Facing is the C64's value doubled on DOS."""
    for slot in "JBA":
        save = _savgam(slot)
        x, y, facing = sg.position(save)
        assert 0 <= x < 32 and 0 <= y < 32
        assert facing in (0, 1, 2, 3)
        assert save[sg.POS_FACING] in (0, 2, 4, 6)
        assert 0 <= sg.geo_block(save) < 32
        assert 1 <= sg.dax_number(save) <= 8
        # `$49C5` is the resident map and `$49F2` is the area, and they hold
        # the same number in all three of these because all three stand in an
        # area that loads its own map. They part company in the training
        # hall, where the script loads none (#257).
        assert sg.current_area(save) == sg.geo_block(save)


@needs_dos_saves
def test_the_flags_and_the_square_land_where_a_c64_save_keeps_them():
    """Steps 5 and 6 against a blank `SAVEDGAME0` window: the flags go to
    `$4A20` and the square to `$49C0`, both as offsets from `$4900`."""
    save = _savgam("A")
    state = world_state.from_dos(save)
    payload = bytearray(0x1C00)
    changed = dos_codec.apply_quest_flags(payload, state)
    assert changed == sum(1 for b in dos_codec.quest_flags(save) if b)
    dos_codec.apply_position(payload, state)
    x, y, facing = sg.position(save)
    assert payload[0x49C0 - 0x4900] == x
    assert payload[0x49C1 - 0x4900] == y
    assert payload[0x49C2 - 0x4900] == facing
    # The area is not written here: `$4BC2` is slot 2 of the loaded-files
    # cache, so it belongs to `apply_file_cache` with the other twenty-four.
    payload[0x4BC2 - 0x4900] = 0xFF
    dos_codec.apply_position(payload, state)
    assert payload[0x4BC2 - 0x4900] == 0xFF
    dos_codec.apply_file_cache(payload, state)
    assert payload[0x4BC2 - 0x4900] == sg.geo_block(save)   # slot 2, the map
    # Nothing outside the two regions was touched.
    assert payload[:0x49C0 - 0x4900] == bytes(0xC0)


# --- the YAML view -----------------------------------------------------------

@needs_dos_saves
def test_a_dos_party_exports_as_the_same_yaml_a_c64_party_does():
    """Step 2, and the reason it is worth having on its own: one shape, one
    set of field names, one renderer."""
    from goldbox.yaml_io import to_yaml

    data = dos_codec.export_party(_save_dir(), "A")
    assert data["port"] == "dos"
    assert len(data["party"]) == 6
    text = to_yaml(data)
    back = yaml.safe_load(text)
    assert [e["name"] for e in back["party"]] == \
           [e["name"] for e in data["party"]]
    first = data["party"][0]
    assert first["_dos_encumbrance"] == first["_dos_encumbrance_expected"]
    assert first["classes"]
    assert first["levels"]


# --- the whole save ----------------------------------------------------------

@needs_dos_saves
def test_convert_save_accounts_for_the_whole_payload():
    """Every one of the 9216 bytes of **both** files has a provenance,
    including "not converted -- left as the template save had it", which is
    why a template is required at all.

    `SAVEDGAME1` used to be absent from the report entirely (#120): its 194
    written bytes had no provenance line and its 1854 template-inherited ones
    were not counted, so `3833/7168 bytes accounted for` was a statement
    about half the output.
    """
    save0 = bytearray(0x1C00)
    save1 = bytearray(0x0800)
    report = dos_codec.convert_save(_save_dir(), "A", save0, save1)
    assert report.total == len(save0) + len(save1)
    assert report.unaccounted == []
    assert any("quest-flag" in w for w in report.warnings)
    # The six roster blocks the conversion writes are named, and named as
    # being in the other file -- `0x0100` means two different things now.
    for place in range(6):
        at = len(save0) + place * dos_codec.ROSTER_STRIDE
        assert "SAVEDGAME1" in report.sources[at]
        assert "roster" in report.sources[at]


@needs_dos_saves
def test_convert_save_accounts_for_save0_alone_when_there_is_no_save1():
    """`save1` is optional, and with none given the report covers exactly the
    one file it was handed."""
    save0 = bytearray(0x1C00)
    report = dos_codec.convert_save(_save_dir(), "A", save0)
    assert report.total == len(save0)
    assert report.unaccounted == []


@pytest.mark.skipif(not gamedata.have_specimen("por-item-twenty"),
                    reason="needs the twenty-item specimen")
def test_a_character_with_more_items_than_the_c64_holds_truncates_silently():
    """#399 (A conversion that runs out of item or trait slots tells the
    player nothing, because the pane never shows a warning) drafted a
    sentence for this.  `WISH-SPEC-por-item-twenty` is WISHFTR, whose `.ITM`
    an editor widened to twenty items before the engine loaded and re-saved
    all of them intact (`provenance.toml`) -- this project's own manufactured
    specimen, the only record anywhere on the machine over sixteen items in
    #399's own 950-character census.  Donald ruled the sentence unneeded
    after seeing that: "I agree that we do not need the sentences." So
    converting him to the C64 still truncates to sixteen; nothing says so.
    """
    save0 = bytearray(0x1C00)
    save1 = bytearray(0x0800)
    report = dos_codec.convert_save(gamedata.specimen("por-item-twenty"), "G",
                              save0, save1)
    assert not any("carry only sixteen" in w for w in report.losses)
    assert not any("carry only sixteen" in w for w in report.warnings)


@pytest.mark.skipif(not gamedata.have_specimen("por-party-l1"),
                    reason="needs the party-l1 specimen")
def test_a_conversion_that_truncates_nothing_reports_no_loss():
    """The control for the test above: six characters, nothing over any
    ceiling (`WISH-SPEC-por-party-l1`'s own `provenance.toml`).  `losses`
    has to stay empty here or every DOS-to-C64 conversion would show a line
    that names no actual loss."""
    save0 = bytearray(0x1C00)
    save1 = bytearray(0x0800)
    report = dos_codec.convert_save(gamedata.specimen("por-party-l1"), "C",
                              save0, save1)
    assert report.losses == []


@pytest.mark.skipif(not gamedata.have_specimen("por-party-l1"),
                    reason="needs the party-l1 specimen")
def test_the_partys_own_bookkeeping_never_reaches_losses():
    """The two lines `write_c64_save` appends about the party as a whole --
    the quest-flag byte count and the roster slots a six-character DOS party
    leaves empty in the C64's eight -- fire on *every* conversion (measured
    at 0 of 217 quest-flag bytes here) and are not a fact about anything the
    player owns.  They stay in `warnings`, for the log, and never reach
    `losses`, which is the list `editor.dosimport.pane_text` reads (#399)."""
    save0 = bytearray(0x1C00)
    save1 = bytearray(0x0800)
    report = dos_codec.convert_save(gamedata.specimen("por-party-l1"), "C",
                              save0, save1)
    assert any("quest-flag" in w for w in report.warnings)
    assert any("emptied" in w for w in report.warnings)
    assert not any("quest-flag" in w for w in report.losses)
    assert not any("emptied" in w for w in report.losses)


@needs_dos_saves
def test_a_template_from_another_area_is_retargeted_not_refused():
    """`$FF` in all twenty-five slots, then slot 2 = the `GEO`, slot 8 = the
    area id and slot 11 = `ANIMATE00`. The arriving script's entry 4 refills
    the rest, CONFIRMED twice in the running game
    (`docs/140-loaded-files-cache.md`). Slot 11 is the third because the save
    *carries* `ANIMATE00` in `SAVEDGAME1`'s tail, and a save that leaves the
    slot empty cannot complete a transition into an area (#102). The three
    bytes outside the cache go with it, `$49EA` above all -- without the disk
    hint the loader sits on `INSERT SIDE # N` hunting a file that is not on
    the side it asked for.
    """
    savgam = _savgam("A")
    there = sg.current_area(savgam)
    where = areas.area(there)
    save0 = bytearray(0x1C00)
    save0[0x4BC2 - dos_codec.SAVE0_BASE] = (there + 1) & 0x7F
    dos_codec.convert_save(_save_dir(), "A", save0)
    at = dos_codec.FILE_CACHE[0] - dos_codec.SAVE0_BASE
    cache = bytes(save0[at:at + dos_codec.FILE_CACHE[1]])
    want = bytearray(b"\xFF" * dos_codec.FILE_CACHE[1])
    want[dos_codec.CACHE_GEO] = sg.geo_block(savgam)
    want[dos_codec.CACHE_ECL] = there
    want[11] = 0                 # ANIMATE00, and see below
    assert cache == bytes(want)
    assert save0[dos_codec.DISK_HINT - dos_codec.SAVE0_BASE] == where.disk
    assert save0[dos_codec.CURRENT_GEO - dos_codec.SAVE0_BASE] == want[dos_codec.CACHE_GEO]
    assert save0[dos_codec.CURRENT_SCRIPT - dos_codec.SAVE0_BASE] == there
    assert save0[dos_codec.INDOORS - dos_codec.SAVE0_BASE] == 1


@needs_dos_saves
def test_a_template_already_in_the_area_is_retargeted_like_any_other():
    """A template standing where the DOS party stands used to keep its own
    cache, on the reasoning that the game wrote it and it names more files
    than a converted save needs. That was the one path in the conversion
    that preferred an inherited value to a computed one, and #121 removed it.

    The recipe is confirmed twice in the running game
    (`docs/140-loaded-files-cache.md`), and **one of those two tests is
    itself a same-area case** -- PORSAVE13 standing in the Slums with a
    Slums save converted onto it -- so the branch this replaces is the one
    already proven unnecessary. What it cost was 29 bytes of somebody
    else's save on #118's inherited list, for no gain.
    """
    savgam = _savgam("A")
    there = sg.current_area(savgam)
    where = areas.area(there)
    save0 = bytearray(0x1C00)
    at = dos_codec.FILE_CACHE[0] - dos_codec.SAVE0_BASE
    save0[at:at + dos_codec.FILE_CACHE[1]] = bytes(range(0x20, 0x39))
    save0[at + dos_codec.CACHE_GEO] = there | dos_codec.FILE_CACHE_RELOAD
    dos_codec.convert_save(_save_dir(), "A", save0)
    want = bytearray(b"\xFF" * dos_codec.FILE_CACHE[1])
    want[dos_codec.CACHE_GEO] = sg.geo_block(savgam)
    want[dos_codec.CACHE_ECL] = there
    want[11] = 0                 # ANIMATE00, as in the other-area case
    assert bytes(save0[at:at + dos_codec.FILE_CACHE[1]]) == bytes(want)
    # The four bytes outside the cache are written too. They used to be
    # skipped on this branch, which is how $49EA -- the side the loader asks
    # for -- kept the template's value.
    assert save0[dos_codec.DISK_HINT - dos_codec.SAVE0_BASE] == where.disk
    assert save0[dos_codec.CURRENT_GEO - dos_codec.SAVE0_BASE] == want[dos_codec.CACHE_GEO]
    assert save0[dos_codec.CURRENT_SCRIPT - dos_codec.SAVE0_BASE] == there
    assert save0[dos_codec.INDOORS - dos_codec.SAVE0_BASE] == 1


@needs_dos_saves
def test_an_area_that_names_no_map_takes_the_one_the_save_names():
    """Six of the thirty areas name no map of their own: the four whose script
    loads none and the two that pick one at run time.  All six used to be
    refused, on the reasoning that guessing a map is what writes a save that
    loads and hangs -- and the training hall is one of them, so a player who
    saved there got `Saves from this location are not supported.` (#257).

    There is nothing to guess.  `$49C5` in the save **is** the resident map,
    written by `LOADFILES` and read by the `GEO` loader, so area 8 -- Phlan
    City Hall, whose script loads no map at all -- converts onto New Phlan's
    `GEO00` because that is the word its own save carries.
    """
    savgam = bytearray(_savgam("A"))
    save0 = bytearray(0x1C00)
    at = dos_codec.FILE_CACHE[0] - dos_codec.SAVE0_BASE
    for id in (3, 8):
        # `$49F2`, not `$49C5`: the area is the script word, and area 8 is one
        # of the places that proves it, since its script loads no map and
        # leaves `$49C5` at New Phlan's 0.
        sg.put_word(savgam, sg.SCRIPT, id)
        assert sg.current_area(bytes(savgam)) == id
        state = world_state.from_dos(bytes(savgam))
        dos_codec.apply_file_cache(save0, state)
        assert save0[at + dos_codec.CACHE_ECL] == id
        assert save0[at + dos_codec.CACHE_GEO] == sg.geo_block(bytes(savgam)) == 0
        assert save0[dos_codec.CURRENT_GEO - dos_codec.SAVE0_BASE] == 0
        assert save0[dos_codec.CURRENT_SCRIPT - dos_codec.SAVE0_BASE] == id


@needs_dos_saves
def test_a_resident_map_no_area_loads_is_refused():
    """`$49C5` is trusted, and trusted is not unchecked.  `GEO0C` is on no
    disk and in no row, so a save claiming it is either not a save this
    reader understands or an area table with a row missing -- and either way
    the answer is not to write it into a converted save (#257).
    """
    savgam = bytearray(_savgam("A"))
    sg.put_word(savgam, sg.AREA, 0x0C)
    # The check now runs while `state` is built, before `apply_file_cache`
    # is ever reached (`world_state.from_dos`'s own `_resident_geo` read).
    with pytest.raises(dos_codec.DosRecordError, match="GEO0C"):
        world_state.from_dos(bytes(savgam))


@needs_dos_saves
def test_a_resident_map_that_contradicts_the_area_is_refused():
    """The other check on `$49C5`.  Area 20 loads `GEO14` and nothing else, so
    a save that says the party is in area 20 with `GEO15` resident is two
    sources disagreeing, and neither is trusted over the other.  Twelve of
    twelve Pool of Radiance saves whose area owns a map agree, so this has
    never fired on a real one (#257).
    """
    savgam = bytearray(_savgam("A"))
    sg.put_word(savgam, sg.SCRIPT, 20)
    sg.put_word(savgam, sg.AREA, 21)
    with pytest.raises(dos_codec.DosRecordError, match="GEO15"):
        world_state.from_dos(bytes(savgam))


@pytest.mark.skipif(not gamedata.have_specimen("por-party-trained-c2"),
                    reason="needs the training-hall specimen")
def test_a_training_hall_save_converts_into_the_hall_on_new_phlans_map():
    """The whole of `#257`, on the save that found it.

    A player trains a cleric in New Phlan's training hall, encamps, saves, and
    converts.  `WISH-SPEC-por-party-trained-c2` is that save, driven from
    character creation in `#249`, and its two place words part company: the
    area is 11 and the resident map is New Phlan's `GEO00`, because `ECL0B`
    contains no `LOADFILES` at all and runs on whatever `ECL00` left on the
    screen.

    Reading the map as the area put the party in New Phlan; reading the area
    as the map refused the save.  Both words are read, each from its own
    address, and the two disagreeing is the point rather than a fault.
    """
    where = gamedata.specimen("por-party-trained-c2")
    savgam = (where / "SAVGAMF.DAT").read_bytes()
    assert (sg.current_area(savgam), sg.geo_block(savgam)) == (11, 0)

    save0 = bytearray(0x1C00)
    state = world_state.from_dos(savgam)
    dos_codec.apply_file_cache(save0, state)
    at = dos_codec.FILE_CACHE[0] - dos_codec.SAVE0_BASE
    assert save0[at + dos_codec.CACHE_ECL] == 11          # the hall's script
    assert save0[at + dos_codec.CACHE_GEO] == 0           # on New Phlan's map
    assert save0[dos_codec.CURRENT_SCRIPT - dos_codec.SAVE0_BASE] == 11
    assert save0[dos_codec.CURRENT_GEO - dos_codec.SAVE0_BASE] == 0
    assert save0[dos_codec.INDOORS - dos_codec.SAVE0_BASE] == 1
    # POOL3 carries both `ECL0B` and `GEO00`, so one hint answers for both.
    assert save0[dos_codec.DISK_HINT - dos_codec.SAVE0_BASE] == areas.area(11).disk == 3


def _outdoor_savgam(script: int = 26) -> bytes:
    """An overland save in the measured shape of `work/p59-outdoor`'s three:
    `$49E6` = 0, `$49C5` = 0, the area id in `$49F2` alone, the square in
    `$49C3`/`$49C4`, and the stale indoor square left in 12801-12803.

    `script` picks which of the three measured windows (#59: areas 25, 26 and
    27) -- 26 by default, unchanged from before this took a parameter."""
    savgam = bytearray(_savgam("A"))
    sg.put_word(savgam, sg.INDOORS, 0)
    sg.put_word(savgam, sg.AREA, 0)
    sg.put_word(savgam, sg.SCRIPT, script)
    sg.put_travel_square(savgam, 7, 29)
    return bytes(savgam)


# script, SQRDATA number, disk hint -- `goldbox/areas.py`'s entries for 25-27.
OUTDOOR_WINDOWS = [(25, 4, 6), (26, 5, 7), (27, 6, 8)]


@needs_dos_saves
@pytest.mark.parametrize("script,sqrdata,disk", OUTDOOR_WINDOWS)
def test_an_overland_save_writes_the_outdoor_cache_recipe(script, sqrdata, disk):
    """#47's outdoor form: slot 4 = the SQRDATA number where slot 2 would
    hold the GEO, slot 2 left `$FF`, `$49E6` = 0, `$49C5` = the SQRDATA
    number, and the disk hint naming the side that carries the area's `ECL`.

    Parametrized over all three measured windows (#59: 3 of 3 specimens),
    not only 26 -- #99 named this the coverage gap between "measured" and
    "unit-tested"."""
    savgam = _outdoor_savgam(script)
    state = world_state.from_dos(savgam)
    save0 = bytearray(0x1C00)
    line = dos_codec.apply_file_cache(save0, state)
    assert f"SQRDATA0{sqrdata}" in line
    at = dos_codec.FILE_CACHE[0] - dos_codec.SAVE0_BASE
    assert save0[at + dos_codec.CACHE_SQRDATA] == sqrdata
    assert save0[at + dos_codec.CACHE_ECL] == script
    assert save0[at + dos_codec.CACHE_GEO] == dos_codec.FILE_CACHE_EMPTY
    # Slot 11 goes with them: `SAVEDGAME1`'s tail *is* `ANIMATE00`, and a save
    # that leaves the slot empty cannot walk into an area (#102). Written as
    # the literal 11 and 0 rather than through the module's own names, so a
    # constant renumbered by hand fails here instead of following the change:
    # `ANIMATE00` is the only `ANIMATE` file in the game, on all eight sides.
    assert save0[at + 11] == 0
    assert save0[dos_codec.INDOORS - dos_codec.SAVE0_BASE] == 0
    assert save0[dos_codec.CURRENT_GEO - dos_codec.SAVE0_BASE] == sqrdata
    assert save0[dos_codec.CURRENT_SCRIPT - dos_codec.SAVE0_BASE] == script
    assert save0[dos_codec.DISK_HINT - dos_codec.SAVE0_BASE] == disk


@needs_dos_saves
@pytest.mark.parametrize("script", [25, 26, 27])
def test_an_overland_save_places_the_party_on_the_travel_pair(script):
    """Outdoors the square goes to `$49C3`/`$49C4` and `$49C0`-`$49C2` is
    left the template's -- the DOS file's own 12801/12802 are the stale
    square the party left the grid on, not where it stands."""
    savgam = _outdoor_savgam(script)
    state = world_state.from_dos(savgam)
    save0 = bytearray(0x1C00)
    save0[0x49C0 - 0x4900:0x49C3 - 0x4900] = b"\x11\x22\x33"
    notes = dos_codec.apply_position(save0, state)
    assert save0[0x49C3 - 0x4900] == 7
    assert save0[0x49C4 - 0x4900] == 29
    assert bytes(save0[0x49C0 - 0x4900:0x49C3 - 0x4900]) == b"\x11\x22\x33"
    assert {a for a, _ in notes} == {0x49C3, 0x49C4}


@needs_dos_saves
@pytest.mark.parametrize("script", [25, 26, 27])
def test_an_outdoor_area_id_is_read_from_the_script_word(script):
    """`$49C5` is 0 on the travel grid (3 of 3 outdoor specimens), so a
    reader keying on it would take an overland party for one in New Phlan."""
    savgam = _outdoor_savgam(script)
    assert sg.geo_block(savgam) == 0
    assert sg.current_area(savgam) == script
    indoor = _savgam("A")
    assert sg.current_area(indoor) == sg.geo_block(indoor)


# --- #99: the two outdoor signals checked against each other ----------------

def _mismatched_savgam(indoors_word: int, area: int, script: int) -> bytes:
    """A `SAVGAM` whose own `$49E6` disagrees with what `goldbox/areas.py` says
    about its script id -- never seen on a real disk (#59 is 3 of 3
    agreeing), but reachable by a corrupt or hand-edited save now that #50 no
    longer refuses all outdoor input.  Built from nothing rather than a real
    specimen, because the whole point is a save no real disk has ever held."""
    savgam = bytearray(sg.SAVGAM_SIZE)
    sg.put_word(savgam, sg.INDOORS, indoors_word)
    sg.put_word(savgam, sg.AREA, area)
    sg.put_word(savgam, sg.SCRIPT, script)
    # A party in the world, not one that has never set out: a container
    # built from nothing is all zero, which is exactly the never-adventured
    # signature `dos.never_adventured` reads (#301, #326), and such a save
    # is converted to the start rather than refused.  Stage a script.
    _stage_a_script(savgam)
    return bytes(savgam)


def test_an_outdoor_bit_with_an_indoor_script_id_is_refused():
    """`$49E6` = 0 (outdoors) but the script id names an indoor area.

    The compare used to run inside `apply_file_cache` itself; it is
    `world_state.from_dos`'s own `_resolve_dos_place` now, raised while
    `state` is built rather than when it is used, so this checks the build.
    """
    savgam = _mismatched_savgam(indoors_word=0, area=0, script=1)
    assert sg.outdoors(savgam) is True
    assert areas.area(sg.current_area(savgam)).outdoors is False
    with pytest.raises(dos_codec.DosRecordError):
        world_state.from_dos(savgam)


def test_an_indoor_bit_with_an_outdoor_script_id_is_refused():
    """`$49E6` != 0 (indoors) but the area, `$49F2`, is one of the three
    overland windows.  It read `$49C5` here until #257 established that the
    area is the script word indoors as well as out."""
    savgam = _mismatched_savgam(indoors_word=1, area=0, script=26)
    assert sg.outdoors(savgam) is False
    assert areas.area(sg.current_area(savgam)).outdoors is True
    with pytest.raises(dos_codec.DosRecordError):
        world_state.from_dos(savgam)


@needs_dos_saves
def test_the_roster_tail_comes_from_the_dos_combat_tail():
    """DOS `0x110`-`0x11C` is the C64's roster block `0x10E`-`0x11B` at a
    displacement of -2: armour class, the armour bonus and the eight running
    attack-form bytes, then hit points widening by one.

    THAC0 is the one byte of the four the C64 does not copy (#405, A
    converted character's THAC0 on the C64 sheet is the source save's stored
    byte, and the engine only corrects it at his first fight): it is
    recomputed from the C64's own `thac0_base` and strength bonus, which
    `tests/test_c64thac0.py` covers directly.
    """
    for char in _records():
        rec, _ = dos_codec.to_c64_record(char)
        assert rec.get("armour_class") == char.get("armour_class")
        assert rec.get_raw("roster_tail") == char.raw("roster_tail")
        assert rec.get("roster_movement") == char.get("movement_current")


@needs_dos_saves
def test_the_converted_clock_is_the_dos_partys_and_not_the_templates():
    """The time of day is converted, not inherited (#103).

    Three DOS saves, three different clocks -- 10:02, 1:22 and 10:56 -- each
    converted onto a template whose own six clock bytes are a sentinel no
    real save holds.  Before the fix all three arrived reading the sentinel,
    which is what a player saw as 21:15 on a party whose save said 10:15.
    """
    sentinel = bytes([9, 9, 9, 21, 28, 11])   # 21:99 on day 28 of month 11
    seen = set()
    for slot in "JBA":
        savgam = _savgam(slot)
        save0 = bytearray(0x1C00)
        at = sg.CLOCK - dos_codec.SAVE0_BASE
        save0[at:at + sg.CLOCK_DIGITS] = sentinel
        dos_codec.convert_save(_save_dir(), slot, save0)
        want = bytes(sg.word(savgam, sg.CLOCK + i)
                     for i in range(sg.CLOCK_DIGITS))
        assert bytes(save0[at:at + sg.CLOCK_DIGITS]) == want, slot
        # And it reads back as the same time through the C64's own accessor,
        # so the six digits are in the order the status line prints.
        hour, minute, day, month = sg.clock(savgam)
        c64 = savegame.SaveGame0.from_bytes(bytes(save0))
        assert c64.party.clock == (hour, minute)
        seen.add((hour, minute, day, month))
    assert len(seen) == 3, "the three saves must differ or this proves nothing"


@needs_dos_saves
def test_a_clock_digit_too_large_for_its_field_is_reported():
    """A digit above what its field holds means the six words are not the
    clock, so it is a warning rather than a silent narrowing."""
    savgam = bytearray(_savgam("A"))
    sg.put_word(savgam, sg.CLOCK + 3, 300)      # the hour digit, limit 24
    state = world_state.from_dos(bytes(savgam))
    save0 = bytearray(0x1C00)
    note, complaints = dos_codec.apply_clock(save0, state)
    assert "the clock" in note
    assert len(complaints) == 1 and "clock digit 3" in complaints[0]
    assert save0[sg.CLOCK + 3 - dos_codec.SAVE0_BASE] == 300 & 0xFF


@needs_dos_saves
def test_the_converted_party_marches_in_the_dos_order():
    """The C64 lists the party from the highest slot down (#101).

    `ENCAMP > ALTER > ORDER` in `work/p3/W1.D64` -- an engine-written save
    whose slots 0-5 are MALCYON, LADY KATHERINE, ROLAND, SILAS, MAGNUS,
    BRUTUS -- asks `WHO TAKES POSITION #1?` over a list headed by BRUTUS, and
    the main panel lists the same six in the same order (`work/p102/order2.log`).
    So DOS position 0 belongs in the highest slot, and writing it into slot 0
    put the DOS party's front-rank fighter at the back.
    """
    for slot in "JBA":
        party = [c.name for c in dos_codec.read_party(_save_dir(), slot)]
        assert len(party) == 6
        save0 = bytearray(0x1C00)
        save1 = bytearray(0x0800)
        dos_codec.convert_save(_save_dir(), slot, save0, save1)
        sg0 = savegame.SaveGame0.from_bytes(bytes(save0))
        by_slot = {s.index: s.record.name for s in sg0.slots if s.occupied}
        # Highest slot first is the C64's marching order; it must be the DOS
        # party's own order, not its reverse.
        assert [by_slot[i] for i in sorted(by_slot, reverse=True)] == party
        # And the roster block travels with the record: +0x0D is the record's
        # slot index, identity in every engine-written save read.
        stride = savegame.ROSTER_STRIDE
        for i in sorted(by_slot):
            assert save1[i * stride + 0x0D] == i, (slot, i)


@needs_dos_saves
def test_the_converted_inventory_follows_its_owner_to_the_reversed_slot():
    """The item page and the slot record must not come apart when the party is
    reversed: page `n` at `$5900` belongs to the character in slot `n`."""
    from goldbox import items

    slot = "A"
    # Keyed by name, not by index: reading the expected count back through
    # `marching_slot` would make the test agree with the code by construction.
    want = {c.name: c.get("item_count")
            for c in dos_codec.read_party(_save_dir(), slot)}
    assert len(want) == 6 and any(want.values())
    save0 = bytearray(0x1C00)
    dos_codec.convert_save(_save_dir(), slot, save0)
    sg0 = savegame.SaveGame0.from_bytes(bytes(save0))
    for place in [s.index for s in sg0.slots if s.occupied]:
        who = sg0.slots[place].record.name
        converted = list(items.items_for_slot(bytes(save0), place))
        assert len(converted) == want[who], (who, place)


# --- the other three titles (#53) -------------------------------------------
#
# Reading is per title and the title is the record's own length.  These tests
# are the evidence that `goldbox/dos_layout.py`'s four shapes are right: a shape
# one byte out fails several of them at once, because each check is a fact
# about the *content* of a field rather than about the table that names it.

#: The archive folder name for each shape, so a test can find that title's
#: shipped party.
_TITLE_FOLDER = {
    "pool-of-radiance": "POOLRAD",
    "curse-of-the-azure-bonds": "CURSE",
    "secret-of-the-silver-blades": "SECRET",
    "pools-of-darkness": "Pools of Darkness",
}


def _title_records(shape):
    """Every shipped record of one title, or a skip."""
    where = _game_dirs().get(_TITLE_FOLDER[shape.key])
    if where is None:
        pytest.skip(f"no DOS {shape.title} here; set FR_ARCHIVES")
    out = [dos_codec.read_character(p) for p in sorted(where.glob("CHRDAT*.SAV"))
           if p.stat().st_size == shape.record_size]
    if not out:
        pytest.skip(f"no DOS {shape.title} records here")
    return out


def _all_titles():
    return pytest.mark.parametrize(
        "shape", dos_port.DELTAS, ids=[s.key for s in dos_port.DELTAS])


def test_each_shape_tiles_its_own_record():
    """Every byte of all four records belongs to exactly one entry, and the
    widths add up to the size the file actually is.  `layout_for` raises on a
    shape that does not, so this is the other half."""
    for shape in dos_port.DELTAS:
        table = dos_port.layout_for(shape)
        assert sum(f.size for f in table) == shape.record_size, shape.key
        assert [f.offset for f in table] == sorted(f.offset for f in table)
    # No two titles are the same length, which is what lets a record name its
    # own title with nothing else to go on.
    assert len(dos_port.DELTAS_BY_SIZE) == len(dos_port.DELTAS)


def test_the_pool_of_radiance_shape_is_the_table_it_was_read_from():
    """The generator must reproduce the hand-written table exactly -- offsets,
    widths, kinds and notes.  Without this the other three shapes would be
    free to drift the one that is measured against 24 specimens."""
    assert dos_port.layout_for(dos_port.POOL_OF_RADIANCE) \
        == dos_port.LAYOUT


def test_a_record_of_an_unknown_length_is_refused():
    """A file that is not one of the four sizes names no title, and guessing
    is how a reader hands back rubbish that looks like a character."""
    with pytest.raises(dos_codec.DosRecordError):
        dos_codec.DosCharacter(bytes(300))


@_all_titles()
def test_every_record_of_every_title_rebuilds_byte_for_byte(shape):
    """Decode every field through the title's table, encode it back, compare.

    This is the round trip a read-only decoder can make, and it is not the
    trivial one: `to_bytes` hands the bytes back untouched, where this goes
    through `_decode`/`_encode` for every entry.  A field declared one byte
    wide that is really two comes back with its second byte zeroed.
    """
    records = _title_records(shape)
    for char in records:
        assert char.rebuild() == bytes(char), (shape.key, char.name)
    assert len(records) >= 6, shape.key


@_all_titles()
def test_the_encumbrance_identity_balances_in_every_title(shape):
    """`money + sum(item weight x quantity)` against the stored encumbrance.

    Self-contained arithmetic across three structures, so it confirms the
    money block, the 63-byte item stride, the weight offset and the byte
    order together -- and it is what says Pools of Darkness really does keep
    **three** coin slots where every earlier title keeps seven.
    """
    for char in _title_records(shape):
        assert char.expected_encumbrance() == char.get("encumbrance"), \
            (shape.key, char.name)


@_all_titles()
def test_the_level_array_is_indexed_by_class_number_in_every_title(shape):
    """DOS indexes its per-class levels by the class *number*, and the class
    byte says which slots may be set.  A spellbook or a memorised region one
    byte out moves this array and the check fails."""
    for char in _title_records(shape):
        number = char.get("char_class")
        assert number in dos_codec.CLASS_SLOTS_FOR_CLASS, (shape.key, char.name,
                                                    number)
        levels = char.raw("class_levels")
        want = {n for n in dos_codec.CLASS_SLOTS_FOR_CLASS[number]
                if n < len(levels)}
        assert {n for n, v in enumerate(levels) if v} == want, \
            (shape.key, char.name, char.get("char_class"), list(levels))
        assert char.get("level") == max(levels), (shape.key, char.name)


@_all_titles()
def test_only_the_proven_titles_convert(shape):
    """Reading is per title; converting is not, until a title has been proven
    the way `.claude/rules/conversions.md` asks for -- bytes matching and a
    converted save loaded in the running game.

    Pool of Radiance was always proven; Curse joined it as step 4 of
    `#192 (Convert a Curse of the Azure Bonds DOS save into a C64 one, which
    the importer refuses today)`, after step 3 read a converted party's sheet
    in VICE. Handing a Silver Blades record to the C64 writer would read
    Curse's or Pool of Radiance's offsets out of a 439-byte record, so it
    still raises instead."""
    char = _title_records(shape)[0]
    if shape in dos_codec.CONVERTS:
        dos_codec.to_neutral(char)
        return
    with pytest.raises(dos_codec.WrongTitleError):
        dos_codec.to_neutral(char)


@_all_titles()
def test_the_class_bitmask_is_what_the_level_arrays_imply(shape):
    """`class_bits` against the classes the level arrays actually name.

    The check that bites hardest on a wrong shape, because the two sit at
    opposite ends of the undecoded middle: move either and they disagree.
    54 of 54 shipped records across the four titles.
    """
    for char in _title_records(shape):
        assert char.get("class_bits") == dos_codec.class_bits_for(char), \
            (shape.key, char.name, hex(char.get("class_bits")))


@_all_titles()
def test_the_class_level_array_reads_a_seven_or_eight_slot_title_alike(shape):
    """`DosCharacter.class_levels` used to walk `CLASS_LEVEL_SLOTS`'
    eight rows regardless of the record's own array width, raising
    `IndexError` on every Secret of the Silver Blades and Pools of Darkness
    record -- both seven slots wide, the monk's dropped (#423).

    PAINE (`ranger 8`) and MALACHITE (`fighter 7, thief 8`), named in the
    issue, are Silver Blades records in the shipped archives.
    """
    named = {"PAINE": {"ranger": 8}, "MALACHITE": {"fighter": 7, "thief": 8}}
    seen = set()
    for char in _title_records(shape):
        assert char.class_levels  # does not raise, and every record has one
        if shape.key == "secret-of-the-silver-blades" and char.name in named:
            assert char.class_levels == named[char.name], (shape.key,
                                                            char.name)
            seen.add(char.name)
    if shape.key == "secret-of-the-silver-blades":
        assert seen == set(named), seen


@_all_titles()
def test_the_shipped_party_reads_as_characters(shape):
    """The cheap sanity of a record that decoded: abilities in range, a
    printable name, hit points inside their maximum, five saving throws that
    are d20 rolls, a size that is small or medium, a party slot."""
    for char in _title_records(shape):
        who = (shape.key, char.name)
        assert char.name.isprintable() and char.name, who
        for stat in ("strength", "intelligence", "wisdom", "dexterity",
                     "constitution", "charisma"):
            assert all(3 <= b <= 25 for b in char.raw(stat)), (who, stat)
        assert 0 < char.get("hp_current") <= char.get("hp_max"), who
        saves = [char.get(n) for n in ("save_paralysis", "save_petrification",
                                       "save_wands", "save_breath",
                                       "save_spell")]
        assert all(1 <= v <= 20 for v in saves), (who, saves)
        assert char.get("size") in (1, 2), who
        assert 0 <= char.get("combat_figure") <= 7, who
        assert char.get("movement") in (6, 9, 12), who


def test_a_dual_classed_character_carries_the_class_it_was():
    """Pools of Darkness keeps a second level array for the class a
    dual-classed character left behind, indexed the same way: ABAGAIL is a
    magic-user 12 who was a cleric 11, and her class bitmask carries both."""
    shape = dos_port.DELTAS_BY_SIZE[510]
    by_name = {c.name: c for c in _title_records(shape)}
    abagail = by_name.get("ABAGAIL")
    if abagail is None:
        pytest.skip("this Pools of Darkness party has no ABAGAIL")
    assert abagail.get("char_class") == 5                    # magic-user
    assert list(abagail.raw("class_levels"))[5] == 12
    assert list(abagail.raw("former_class_levels"))[0] == 11  # cleric
    assert abagail.get("class_bits") == 0x03                 # both


def test_the_silver_blades_rangers_hold_the_c64_grant_list_exactly():
    """The strongest single check on a shape this project did not measure
    itself: the ranger's grant was read mechanically out of the **C64** `GEN`
    file, and DOS Silver Blades' three shipped rangers hold its level-8 row --
    77, 78, 79, 80 -- and nothing else.

    Three of three, on a 117-byte spellbook 0x071 bytes into a 439-byte
    record neither port's table knew about the other.

    It used to read a transcribed id list, `spells._RANGER_GRANT_SILVER_
    BLADES`. That list is gone: `goldbox/levelup.py` derives a ranger's ids
    from `SpellTable.groups` and a pair of spell levels now, so this asks the
    derivation rather than a copy of the answer (#89).
    """
    shape = dos_port.DELTAS_BY_SIZE[439]
    want = set(levelup._ranger_spell_ids(8, c64_port.SECRET_OF_THE_SILVER_BLADES))
    rangers = [c for c in _title_records(shape) if c.get("char_class") == 4]
    assert len(rangers) == 3
    for char in rangers:
        assert set(char.spells_known) == want, char.name


def test_the_silver_blades_clerics_hold_the_cleric_grant_levels():
    """The level-8 clerics know cleric levels 1-4 and nothing else, which is
    `goldbox/spells.py`'s Silver Blades groups 1-8, 22-28, 37-44, {58, 66-70}."""
    shape = dos_port.DELTAS_BY_SIZE[439]
    want = (set(range(1, 9)) | set(range(22, 29)) | set(range(37, 45))
            | {58} | set(range(66, 71)))
    clerics = [c for c in _title_records(shape) if c.get("char_class") == 0]
    assert len(clerics) == 2
    for char in clerics:
        assert set(char.spells_known) == want, char.name


# --- the template's spare characters (#104) ---------------------------------

def _plant(save0: bytearray, save1: bytearray, place: int, name: bytes) -> None:
    """Put something in a slot that `looks_occupied` agrees is a character.

    A synthetic template rather than a real save, because what is being tested
    is a rule -- no slot the converted party did not fill may still read as
    occupied -- and a synthetic one can hold **eight**, which is the case a
    six-character DOS party cannot cover and no engine-written save on this
    machine happens to be.
    """
    at = savegame.SLOT_AREA_BASE - savegame.SAVE0_LOAD_ADDRESS \
        + place * savegame.SLOT_STRIDE
    save0[at:at + len(name)] = name
    save0[at + 0x14:at + 0x1A] = bytes([12] * 6)   # six abilities, 3..25
    save1[place * savegame.ROSTER_STRIDE] = 1      # roster_in_use


@needs_dos_saves
def test_no_spare_character_survives_a_conversion():
    """A DOS save holds six characters and a C64 save eight, so a conversion
    always leaves at least two of the template's slots unwritten. They must
    not still read as characters: the party would arrive with strangers in it,
    carrying items that are not theirs and sharing the experience.

    **The whole slot goes**, not the one byte the engine's own `DROP` writes
    (#118). `ZSLOT8` wiped 555 non-zero bytes of an eight-character save this
    way and the party in it walked five squares and won a fight, so a slot
    that is nobody's carries none of the previous owner's abilities, hit
    points or items either.
    """
    save0 = bytearray(0x1C00)
    save1 = bytearray(0x0800)
    # Names no DOS party can be carrying, so the assertion below cannot pass
    # or fail by coincidence -- the shipped party has a BRUTUS and a MAGNUS.
    for place, name in ((6, b"XYZZY"), (7, b"PLUGH")):
        _plant(save0, save1, place, name)
    planted = savegame.SaveGame0.from_bytes(bytes(save0))
    assert [s.index for s in planted.slots if s.occupied] == [6, 7], \
        "the synthetic template must start out holding those two"

    party = dos_codec.read_party(_save_dir(), "A")
    report = dos_codec.convert_save(_save_dir(), "A", save0, save1)
    sg0 = savegame.SaveGame0.from_bytes(bytes(save0))
    filled = {s.index for s in sg0.slots if s.occupied}
    assert filled == set(range(len(party))), sorted(filled)
    names = {s.record.name for s in sg0.slots if s.occupied}
    assert "XYZZY" not in names and "PLUGH" not in names, sorted(names)
    # The roster block says the same thing, and both have to agree or the
    # engine reads one structure as full and the other as empty.
    for place in range(len(party), 8):
        assert save1[place * savegame.ROSTER_STRIDE] == 0, place
    assert report.unaccounted == []
    # And nothing of XYZZY is left behind it: not the name, not the abilities
    # `_plant` wrote at +0x14, not the item block, not the icon.
    for place in range(len(party), dos_codec.SLOT_TOTAL):
        for base in (savegame.SLOT_AREA_BASE, dos_codec.ITEM_AREA):
            at = base - savegame.SAVE0_LOAD_ADDRESS + place * dos_codec.SLOT_STRIDE
            assert bytes(save0[at:at + dos_codec.SLOT_STRIDE]) == \
                bytes(dos_codec.SLOT_STRIDE), f"slot {place} at ${base:04X}"
    for place in range(len(party), savegame.SLOT_COUNT):
        at = dos_codec.ICON_TABLE - savegame.SAVE0_LOAD_ADDRESS \
            + place * dos_codec.ICON_SIZE
        assert bytes(save0[at:at + dos_codec.ICON_SIZE]) == bytes(dos_codec.ICON_SIZE)
        at = place * savegame.ROSTER_STRIDE
        assert bytes(save1[at:at + savegame.ROSTER_STRIDE]) == \
            bytes(savegame.ROSTER_STRIDE)


# --- a save built from nothing (#118) ---------------------------------------
#
# The regions below are what a template used to supply. Each has a run behind
# it in the emulator, on this issue's comments; what these assert is that the
# writer puts the measured value there rather than leaving the buffer's.

def _game_files():
    """The icon and `ANIMATE00` off the player's own disks, or skip.

    Read at run time, never stored: both are the game's own data and
    `AGENTS.md` forbids a fixture that is a slice of a game file.
    """
    import gamedata

    from goldbox.d64 import load_payload
    from goldbox.iconparts import IconParts

    where = gamedata.disk_dir()
    if where is None:
        pytest.skip("needs the game disks; set POR_DISKS to where they are")
    icon = animate = None
    for disk in sorted(where.glob("POOL*.[dD]64")):
        try:
            icon = icon if icon is not None else \
                IconParts.load(str(disk)).default_icon()
        except Exception:
            pass
        try:
            animate = animate if animate is not None else \
                load_payload(str(disk), dos_codec.ANIMATE_FILE)
        except Exception:
            pass
    if icon is None or animate is None:
        pytest.skip("no POOL disk here carries SPELLE64 or ANIMATE00")
    return icon, animate


@needs_dos_saves
def test_a_save_built_from_nothing_accounts_for_every_byte():
    """`new_save` returns a report whose `unwritten` is empty, for every slot
    the DOS folder holds.

    That is the whole of #118 stated as a test: a byte with no source is a
    byte inherited from somebody else's save, and there is no longer a save to
    inherit one from. Without the zeroing tables and the two game files this
    goes red with 5405 entries.
    """
    icon, animate = _game_files()
    slots = dos_codec.slots_available(_save_dir())
    assert slots, "the DOS save folder has to hold at least one slot"
    for slot in slots:
        save0, save1, report = dos_codec.new_save(_save_dir(), slot, icon, animate)
        assert report.unwritten == [], slot
        assert report.unaccounted == [], slot
        assert len(save0) + len(save1) == report.total == 9216


@needs_dos_saves
def test_the_combat_icons_of_the_party_are_the_ones_creation_writes():
    """Zero is refused here (#57): screen code 0 in `CHARPIC00` is a real
    glyph, so a zeroed 36-byte icon draws as a 3x3 block of black hooks on the
    combat floor rather than as nothing.

    So every occupied slot carries the icon the game's own character creation
    writes, every empty *player* slot carries zero -- nothing draws an icon
    for a slot with no character in it -- and the two NPC-only slots no DOS
    party can ever fill carry that same creation default rather than zero
    (`#363 (A DOS-to-C64 conversion writes zero into the two NPC-only
    combat-icon slots instead of the engine's own seeded default)`).
    """
    icon, animate = _game_files()
    party = dos_codec.read_party(_save_dir(), "A")
    save0, _save1, _report = dos_codec.new_save(_save_dir(), "A", icon, animate)
    for place in range(savegame.SLOT_COUNT):
        at = dos_codec.ICON_TABLE - dos_codec.SAVE0_BASE + place * dos_codec.ICON_SIZE
        got = bytes(save0[at:at + dos_codec.ICON_SIZE])
        occupied = place < len(party)
        want = icon if occupied or place in dos_codec.NPC_ICON_SLOTS \
            else bytes(dos_codec.ICON_SIZE)
        assert got == want, place
        if occupied or place in dos_codec.NPC_ICON_SLOTS:
            assert any(got), f"slot {place} would draw as black hooks"


def _icon_parts():
    """`IconParts` off whichever `POOL*` side carries it, or skip."""
    from goldbox.iconparts import IconParts

    where = gamedata.disk_dir()
    if where is None:
        pytest.skip("needs the game disks; set POR_DISKS to where they are")
    for disk in sorted(where.glob("POOL*.[dD]64")):
        try:
            return IconParts.load(str(disk))
        except Exception:
            pass
    pytest.skip("no POOL disk here carries SPELLE64/SPELLN64")


@needs_dos_saves
def test_a_converted_party_keeps_its_own_combat_figures():
    """#130 (A converted DOS party arrives with six identical combat figures,
    not its own): `convert_save` used to hand every character the same
    36-byte default icon.  Given the C64's own option tables instead of
    composed bytes, each character gets the figure his own DOS record names,
    through `IconParts.dos_icon` -- exactly `_icon_for`'s helper, checked
    directly against `new_save`'s own output.
    """
    from goldbox.iconparts import dos_size

    parts = _icon_parts()
    _icon, animate = _game_files()
    slot = next((s for s in dos_codec.slots_available(_save_dir())
                if len({(c.get("icon_head"), c.get("icon_body"))
                        for c in dos_codec.read_party(_save_dir(), s)}) > 1),
               None)
    if slot is None:
        pytest.skip("needs a DOS party whose combat figures are not all "
                    "the same")
    party = dos_codec.read_party(_save_dir(), slot)
    save0, _save1, _report = dos_codec.new_save(_save_dir(), slot, parts, animate)
    icons = {}
    for index, char in enumerate(party):
        place = dos_codec.marching_slot(index, len(party))
        at = dos_codec.ICON_TABLE - dos_codec.SAVE0_BASE + place * dos_codec.ICON_SIZE
        icons[place] = bytes(save0[at:at + dos_codec.ICON_SIZE])
        want = parts.dos_icon(char.get("icon_head"), char.get("icon_body"),
                              dos_size(char.get("size")),
                              bytes(char.get("icon_colours")))
        assert icons[place] == want, char.name
    assert len(set(icons.values())) > 1, "every figure came out the same"


# --- the sheet portrait, and the trap in its switch (#57) -------------------
#
# `$49FF` bit 7 is what makes `LIBRARY $48A4` fetch `HEAD<xx>`/`BODY<xx>` at
# all.  Turning it on over a party some of whom carry no id sends the loader
# after `HEAD00` -- a real portrait -- and `BODY00`, which is on none of the
# eight sides, and the sheet sticks with no way off it.  So the two tests
# below are the two ways this can go wrong, not one: the switch has to come
# on when it is safe and stay off when it is not.

def _portrait_tables_from_disks():
    """The creation menu off the player's own C64 game disks, or `None`.

    The import direction reads the **destination** port's own binary --
    `goldbox/portraits.py`'s `tables_from_disks` -- because the directory a
    conversion already holds for the combat icon and `ANIMATE00` is the C64
    disks, not the DOS folder.
    """
    from goldbox import portraits

    where = gamedata.disk_dir()
    if where is None:
        return None
    try:
        return portraits.tables_from_disks(where)
    except portraits.PortraitError:
        return None


@needs_dos_saves
def test_an_imported_party_carries_its_own_faces_and_switches_the_portrait_on():
    """Every character keeps the face DOS gave it, and `$49FF` comes out
    `$81` -- the byte the drawing routine reads before it fetches `HEAD<xx>`
    and `BODY<xx>` at all.

    Needs a slot whose whole party sits in the fourteen-and-twelve menu; a
    party with one member outside it is the next test, on purpose.
    """
    tables = _portrait_tables_from_disks()
    if tables is None:
        pytest.skip("needs the game disks; set POR_DISKS to where they are")
    icon, animate = _game_files()
    where = _save_dir()
    slot = party = None
    for candidate in dos_codec.slots_available(where):
        candidate_party = dos_codec.read_party(where, candidate)
        neutral = [dos_codec.to_neutral(c, portraits=tables) for c in candidate_party]
        if all("portrait_head" in n and "portrait_body" in n
               for n in neutral):
            slot, party = candidate, candidate_party
            break
    if slot is None:
        pytest.skip("no DOS slot here has every character in the menu")

    save0, _save1, _report = dos_codec.new_save(where, slot, icon, animate,
                                          portraits=tables)
    at = dos_codec.PORTRAIT_SWITCH - dos_codec.SAVE0_BASE
    assert save0[at] == dos_codec.PORTRAIT_ON

    seen = 0
    for index, char in enumerate(party):
        place = dos_codec.marching_slot(index, len(party))
        head_want = tables.head_art(char.get("portrait_head"))
        body_want = tables.body_art(char.get("portrait_body"))
        rec_at = dos_codec.SLOT_AREA - dos_codec.SAVE0_BASE + place * dos_codec.SLOT_STRIDE
        assert save0[rec_at + 0x0FE] == head_want, char.name
        assert save0[rec_at + 0x0FF] == body_want, char.name
        seen += 1
    assert seen == len(party)


@needs_dos_saves
def test_a_party_missing_one_face_leaves_the_portrait_switched_off(tmp_path):
    """One character with no id in the menu, and the whole party goes dark
    rather than sticking on a character sheet with no way off it.

    Turning `$49FF` on over a record left at zero sends the loader after
    `HEAD00` -- a real portrait -- and `BODY00`, which is on none of the
    eight sides: measured, VICE, the sheet then draws with `INSERT SIDE # 2,
    AND PRESS ANY KEY.` where its command bar should be and never leaves it.
    So a party like this one must come out `$01`, not `$81`.
    """
    import shutil

    tables = _portrait_tables_from_disks()
    if tables is None:
        pytest.skip("needs the game disks; set POR_DISKS to where they are")
    icon, animate = _game_files()
    where = _save_dir()
    slot = None
    for candidate in dos_codec.slots_available(where):
        if len(list(where.glob(f"CHRDAT{candidate}?.SAV"))) >= 2:
            slot = candidate
            break
    if slot is None:
        pytest.skip("needs a DOS slot holding at least two characters")

    for path in sorted(where.glob(f"CHRDAT{slot}?.*")):
        shutil.copy(path, tmp_path / path.name)
    shutil.copy(where / f"SAVGAM{slot}.DAT", tmp_path / f"SAVGAM{slot}.DAT")

    first = sorted(tmp_path.glob(f"CHRDAT{slot}?.SAV"))[0]
    raw = bytearray(first.read_bytes())
    raw[dos_port.FIELDS_BY_NAME["portrait_head"].offset] = 99  # outside
    first.write_bytes(bytes(raw))                                # the menu

    save0, _save1, _report = dos_codec.new_save(tmp_path, slot, icon, animate,
                                          portraits=tables)
    at = dos_codec.PORTRAIT_SWITCH - dos_codec.SAVE0_BASE
    assert save0[at] == dos_codec.PORTRAIT_OFF


#: `(disk, NPC slot)` known not to carry the engine's own seeded default, and
#: why -- the same style `test_derive.py`'s `THAC0_EXPLAINED` uses, a named
#: set rather than a count, so a *new* disk failing this still turns the
#: assertion red instead of being folded silently into a bigger tolerance.
#:
#: `PORSAVEA.D64` and `PORSAVEB.D64` are Wish's own historical output,
#: established by `#346 (The default-icon test reads every save disk the
#: player owns, and two of them no longer carry the seeded icon in an NPC
#: slot)`: both NPC slots on both disks are 36 bytes of zero, the pattern
#: every DOS-to-C64 conversion produced before `#363 (A DOS-to-C64 conversion
#: writes zero into the two NPC-only combat-icon slots instead of the
#: engine's own seeded default)` fixed `goldbox.dos.write_c64_save`. That fix
#: does not rewrite a disk already on the player's machine, so these two stay
#: exceptions until Donald converts that party again.
NPC_SLOT_EXPLAINED = {
    ("PORSAVEA.D64", 6): "converted from DOS before #363's fix; zero, not "
                          "the seeded default",
    ("PORSAVEA.D64", 7): "the same",
    ("PORSAVEB.D64", 6): "the same party, saved again",
    ("PORSAVEB.D64", 7): "the same",
}


@needs_disks
def test_the_default_icon_is_what_the_engine_seeded_the_table_with():
    """Composed from the option tables, and checked against the player's own
    save disks rather than against a number written down here.

    Slots 6 and 7 are the NPC-only slots nobody has ever edited, so they
    still hold what the table was seeded with -- on every disk except the
    two named in :data:`NPC_SLOT_EXPLAINED`, which are Wish's own past
    output rather than the engine's. And **0** in slots 0-5, which is what
    says the match is the creation default rather than a shape any character
    happens to carry.
    """
    from goldbox import icons
    from goldbox.d64 import D64
    from goldbox.iconparts import IconParts

    #: Slots 6 and 7 are the two a DOS party can never fill, so the engine's
    #: seeding is still in them on every save the player has ever made.
    NPC_SLOTS = (6, 7)

    want = IconParts.load(str(gamedata.game_disk("POOL3"))).default_icon()
    checked = seeded = nudged = explained = 0
    unexplained = []
    for path in gamedata.save_disks():
        try:
            _game, sg0, _sg1 = savegame.load_save(D64.open(path))
        except Exception:
            continue                      # a roster disk with no save on it
        checked += 1
        payload = sg0.to_bytes()
        for place in range(savegame.SLOT_COUNT):
            same = icons.icon_for_slot(payload, place).raw == want
            if place in NPC_SLOTS:
                if same:
                    seeded += 1
                elif (path.name.upper(), place) in NPC_SLOT_EXPLAINED:
                    explained += 1
                else:
                    unexplained.append((path.name, place))
            else:
                nudged += same
    assert checked, "needs at least one save disk to check against"
    # `seeded + explained` accounts for every NPC slot on every disk checked;
    # what makes this a test rather than bookkeeping is that a slot matching
    # neither the seed nor a name in NPC_SLOT_EXPLAINED goes to `unexplained`
    # and fails it -- so a *new* disk in this state turns the suite red
    # instead of being folded silently into a bigger tolerance.
    assert seeded + explained == checked * len(NPC_SLOTS)
    assert not unexplained, \
        f"{len(unexplained)} of {checked * len(NPC_SLOTS)} NPC slots match " \
        f"neither the seeded default nor a known exception: {unexplained}"
    assert nudged == 0, "a slot the player edited matches the default"


@needs_dos_saves
def test_animate00_is_written_where_the_cache_says_it_is():
    """`$8400`-`$8753` is `ANIMATE00` as the loader leaves it, off the
    player's own disk.

    It is not scratch: the loaded-files cache slot 11 says the file is
    resident, so the engine does not reload it and calls into whatever the
    save carried (#102). The bounds are the file's own -- `$8400 + 852 - 1` is
    `$8753`, exactly where the bitmap buffer begins -- and the buffer after it
    is zero, which is what makes the split checkable rather than asserted.
    """
    icon, animate = _game_files()
    assert len(animate) == dos_codec.ANIMATE_SIZE
    save0, save1, _report = dos_codec.new_save(_save_dir(), "A", icon, animate)
    at = dos_codec.ANIMATE_AT - dos_codec.SAVE1_BASE
    assert bytes(save1[at:at + len(animate)]) == animate
    end = at + len(animate)
    assert dos_codec.SAVE1_BASE + end == dos_codec.BITMAP_BUFFER[0]
    assert bytes(save1[end:]) == bytes(len(save1) - end)
    # The two halves of the claim, in one place: the cache says the file is
    # resident, and the bytes it points at are the file. Asserting only the
    # first is how a save came to say `ANIMATE00` was in memory over a page
    # of zeros (#122).
    slot11 = dos_codec.FILE_CACHE[0] - dos_codec.SAVE0_BASE + dos_codec.CACHE_ANIMATE
    assert save0[slot11] == 0x00, "the file number, and ANIMATE00 is the only one"


@needs_dos_saves
def test_convert_save_with_no_animate_reports_the_region_as_inherited():
    """Handed no `animate`, `convert_save` leaves `$8400`-`$8753` alone --
    and says so, byte by byte, in `Report.unwritten`.

    This is the invariant #122 was filed about, stated from the other side.
    The cache is written to say slot 11 is resident whatever happens, so a
    caller that does not supply the file has produced a save asserting
    `ANIMATE00` is in memory over bytes nobody looked at. `new_save` is what
    refuses that; the report is what makes it visible to anything else, and
    a well-meant "just zero it" here would put the assertion back over a page
    of zeros with nothing left to notice.
    """
    save0 = bytearray(dos_codec.SAVE0_SIZE)
    save1 = bytearray(dos_codec.SAVE1_SIZE)
    report = dos_codec.convert_save(_save_dir(), "A", save0, save1)
    at = len(save0) + dos_codec.ANIMATE_AT - dos_codec.SAVE1_BASE
    inherited = set(report.unwritten)
    assert set(range(at, at + dos_codec.ANIMATE_SIZE)) <= inherited
    slot11 = dos_codec.FILE_CACHE[0] - dos_codec.SAVE0_BASE + dos_codec.CACHE_ANIMATE
    assert save0[slot11] == 0x00, "the file number, and ANIMATE00 is the only one"


@needs_dos_saves
def test_a_wrong_sized_animate_is_refused_rather_than_written():
    """852 bytes on all eight `POOL` sides. Something else is not the file,
    and writing it would put the wrong bytes under a cache entry that says
    they are the right ones.

    **The long case is the one that needs the check.** A short payload leaves
    a byte with no source and `new_save` catches it anyway; a long one runs
    past `$8753` into the bitmap buffer, and every byte of it is accounted
    for, so nothing else would notice.
    """
    icon, animate = _game_files()
    for wrong in (animate[:-1], animate + b"\x00"):
        with pytest.raises(dos_codec.DosRecordError):
            dos_codec.new_save(_save_dir(), "A", icon, wrong)


@needs_dos_saves
def test_the_built_disk_is_the_two_files_a_save_disk_needs():
    """Thirteen of the player's fifteen save disks hold `SAVEDGAME1` and
    `SAVEDGAME0` in that directory order and nothing else, so a disk built
    from nothing is those two files and no others."""
    from goldbox.savegame import load_save

    icon, animate = _game_files()
    save0, save1, _report = dos_codec.new_save(_save_dir(), "A", icon, animate)
    disk = dos_codec.save_disk(bytes(save0), bytes(save1))
    assert [bytes(e.name) for e in disk.directory()] == \
        [b"SAVEDGAME1", b"SAVEDGAME0"]
    _game, sg0, sg1 = load_save(disk)
    assert sg0.to_bytes() == bytes(save0)
    assert sg1.to_bytes() == bytes(save1)


def _outdoor_folder(tmp_path, slot: str = "A", script: int = 26):
    """A DOS save folder holding one slot, patched to stand on the travel grid.

    All three of Donald's own DOS saves are indoors, so an outdoor
    `new_save` cannot be reached from the archives as they stand -- and
    `_outdoor_savgam` alone cannot reach it either, because `convert_save`
    reads `SAVGAM<slot>.DAT` off the disk rather than taking bytes.  So the
    slot's files are copied into `tmp_path` and the copy of the `SAVGAM` is
    the one that is patched; nothing under `$FR_ARCHIVES` is written.
    """
    import shutil

    where = _save_dir()
    if where is None:
        pytest.skip("needs a DOS save; set FR_ARCHIVES to the archives")
    for path in sorted(where.glob(f"CHRDAT{slot}?.*")):
        shutil.copy(path, tmp_path / path.name)
    if not list(tmp_path.glob(f"CHRDAT{slot}?.SAV")):
        pytest.skip(f"no CHRDAT{slot}?.SAV here")
    (tmp_path / f"SAVGAM{slot}.DAT").write_bytes(_outdoor_savgam(script))
    return tmp_path


@needs_dos_saves
def test_an_outdoor_dos_save_builds_a_whole_c64_save(tmp_path):
    """An outdoor DOS party converts at all, which it did not (#118).

    `apply_position` writes `$49C0`-`$49C2` on its **indoor** branch only:
    outdoors the square is the travel pair `$49C3`/`$49C4` and those three
    bytes are nobody's.  With a template underneath that was "left alone";
    from nothing it is three bytes with no source, so `new_save` refused
    every outdoor save there is -- `3 bytes of the save have no source ...
    the first is SAVEDGAME0 $49C0`.

    Zero is what the game's own ENCAMP > SAVE writes there outdoors
    (`work/p3/W4.D64`-`W7.D64`), which is what `DUNGEON_SQUARE` records.
    """
    icon, animate = _game_files()
    folder = _outdoor_folder(tmp_path)
    save0, save1, report = dos_codec.new_save(folder, "A", icon, animate)
    assert report.unwritten == []
    assert report.unaccounted == []
    assert len(save0) + len(save1) == report.total == 9216
    at = dos_codec.DUNGEON_SQUARE[0] - dos_codec.SAVE0_BASE
    assert bytes(save0[at:at + dos_codec.DUNGEON_SQUARE[1]]) == bytes(3)
    # The travel pair is the square the party is actually standing on, and it
    # is the one thing that would be lost by zeroing the whole run at once.
    assert [save0[sg.TRAVEL_X - dos_codec.SAVE0_BASE],
            save0[sg.TRAVEL_Y - dos_codec.SAVE0_BASE]] == [7, 29]
    assert save0[dos_codec.INDOORS - dos_codec.SAVE0_BASE] == 0


@needs_dos_saves
def test_an_indoor_dos_save_still_carries_its_own_dungeon_square():
    """The other half of the zero, and what stops it being written always.

    Indoors `apply_position` writes all three over the zero, so a conversion
    that zeroed `$49C0`-`$49C2` unconditionally would put every imported
    indoor party on square 0,0 facing north.  Checked against the DOS save's
    own bytes rather than against a square written down here.
    """
    icon, animate = _game_files()
    slot = dos_codec.slots_available(_save_dir())[0]
    save0, _save1, _report = dos_codec.new_save(_save_dir(), slot, icon, animate)
    at = dos_codec.DUNGEON_SQUARE[0] - dos_codec.SAVE0_BASE
    want = sg.position(_savgam(slot))
    assert not sg.outdoors(_savgam(slot)), \
        "this test needs an indoor slot; all three archives saves are indoors"
    assert tuple(save0[at:at + 3]) == want


def test_a_measured_title_recomputes_the_saves_and_an_unmeasured_one_keeps_its_row(
        monkeypatch):
    """`goldbox.levels.RACIAL_SAVE_BONUS_MEASURED` is a gate, not a list of
    titles: a title in it has a converted character's five saving-throw
    columns recomputed the way the C64's own trainer stores them, and a
    title outside it keeps the row its source held, because a guessed
    number is worse than the one the player had (`#311 (A DOS dwarf, gnome
    or halfling converted to the C64 loses his constitution bonus to saving
    throws, because the C64 keeps it inside the five stored bytes)`).

    All three C64 titles are in it now.  Silver Blades joined on 2026-09-06
    (`#344 (A converted Silver Blades dwarf, gnome or halfling keeps DOS's
    saving throws, because that title's racial bonus has never been watched
    in the game)`): MALACHITE, a dwarf with constitution 17, trained five
    times on one boot with only his race byte changed between presses, and
    the engine wrote `6 10 6 12 7` for the dwarf and `10 10 10 12 11` for
    gnome, halfling and human -- 25 of 25 columns what `saving_throws`
    computes.  Only the dwarf takes the bonus there: `$11D8` is an equality
    test against race 3, not Curse's odd-race test.

    So what is pinned is the rule and not the membership.  The second half
    is the one worth keeping: it is what stops a future title being
    recomputed from a formula nobody has watched.  The predicate is
    deliberately not `trainer_measured`, which asks a broader question.
    """
    from goldbox import levels

    columns = ("save_paralysis", "save_petrification", "save_wands",
               "save_breath", "save_spell")
    plain = (14, 15, 16, 17, 17)
    #: The dwarf, in each title's own race numbering: 1 in Pool of Radiance
    #: and Curse, 3 in Silver Blades (`goldbox/levels.py`'s table).
    dwarf = {"pool-of-radiance": 1, "curse-of-the-azure-bonds": 1,
             "secret-of-the-silver-blades": 3}

    def written(game: str) -> tuple:
        rec, _ = c64_codec.write(_plain_row_character(dwarf[game], game=game))
        return tuple(rec.get(n) for n in columns)

    for game, race in dwarf.items():
        assert levels.racial_save_bonus_measured(game), game
        want = tuple(levels.saving_throws({"fighter": 1}, race, 13, game))
        assert want != plain, f"{game}: a dwarf's row must move"
        assert written(game) == want, game

    # The same dwarf under a title the set does not hold keeps DOS's row.
    last = "secret-of-the-silver-blades"
    monkeypatch.setattr(levels, "RACIAL_SAVE_BONUS_MEASURED",
                        levels.RACIAL_SAVE_BONUS_MEASURED - {last})
    assert not levels.racial_save_bonus_measured(last)
    assert written(last) == plain


# --- #301, #326: a party that has not set out --------------------------------

def _stage_a_script(savgam: bytearray) -> None:
    """Make a container from nothing read as a party **in the world**: one
    non-zero byte in the staged area script, and `$4FE1` at the 255 that 51
    of the 95 played Pool of Radiance containers on this machine hold -- the
    two readings `dos.never_adventured` takes."""
    start, _ = sg.SAVE_POOL_OF_RADIANCE.script_buffer
    savgam[start] = 0x01
    sg.put_word(savgam, dos_codec.LATER_BEGUN_WORD, 255)


def _never_adventured_savgam() -> bytes:
    """The signature all seven Pool of Radiance never-adventured containers
    on this machine share: area 0, map 0, `$49E6` = 0, `$4FE1` = 0, square
    `15,1` facing west, clock 00:00 and an all-zero script buffer
    (`#326 (A Pool of Radiance save made before the party began
    adventuring is refused, because the initialiser left $49E6 at 0 and New
    Phlan is indoors)`).  Built from nothing, which is how the initialiser
    leaves it."""
    savgam = bytearray(sg.SAVGAM_SIZE)
    sg.put_position(savgam, 15, 1, 3)
    return bytes(savgam)


def _new_phlan_savgam() -> bytes:
    """A party standing in New Phlan with the clock running: the same area
    word and map word as a never-adventured save, and nothing else the same.
    Thirteen real containers here are in this state, the archives' own
    `SAVGAMA.DAT` at 16:58 among them."""
    savgam = bytearray(sg.SAVGAM_SIZE)
    sg.put_word(savgam, sg.INDOORS, 1)
    sg.put_position(savgam, 3, 9, 2)
    sg.put_clock(savgam, (0, 8, 5, 16, 4, 2))       # 16:58, day 4, month 2
    _stage_a_script(savgam)
    return bytes(savgam)


def test_a_party_that_has_not_set_out_is_read_off_the_container_not_the_area_word():
    """Area 0 is New Phlan in Pool of Radiance, so the word cannot say
    whether the party has set out; the container can.  The two saves here
    hold the same `$49F2` and the same `$49C5` and are told apart by the
    staged script alone (#326)."""
    fresh = _never_adventured_savgam()
    standing = _new_phlan_savgam()
    assert sg.current_area(fresh) == sg.current_area(standing) == 0
    assert sg.geo_block(fresh) == sg.geo_block(standing) == 0
    assert dos_codec.never_adventured(fresh)
    assert not dos_codec.never_adventured(standing)
    # The word on its own tells the same story, for the title with no buffer.
    assert sg.word(fresh, dos_codec.LATER_BEGUN_WORD) == 0
    assert sg.word(standing, dos_codec.LATER_BEGUN_WORD) == 255


def test_a_pool_of_radiance_party_that_has_not_set_out_converts_to_new_phlan():
    """`$49E6` is 0 in such a save because the initialiser left it 0, and
    New Phlan is indoors, so the indoors compare refused every one of the
    seven (#326).  Now the start row says where the party goes -- area 0,
    `GEO00`, POOL3, `15,1` facing west -- and `$49E6` is written 1 from
    the row rather than compared against the initialiser."""
    savgam = _never_adventured_savgam()
    assert sg.outdoors(savgam), "the initialiser's $49E6 reads as outdoors"
    state = world_state.from_dos(savgam)
    save0 = bytearray(0x1C00)
    line = dos_codec.apply_file_cache(save0, state)
    at = dos_codec.FILE_CACHE[0] - dos_codec.SAVE0_BASE
    assert save0[at + dos_codec.CACHE_ECL] == 0
    assert save0[at + dos_codec.CACHE_GEO] == 0
    assert save0[dos_codec.CURRENT_SCRIPT - dos_codec.SAVE0_BASE] == 0
    assert save0[dos_codec.CURRENT_GEO - dos_codec.SAVE0_BASE] == 0
    assert save0[dos_codec.INDOORS - dos_codec.SAVE0_BASE] == 1
    assert save0[dos_codec.DISK_HINT - dos_codec.SAVE0_BASE] == areas.area(0).disk == 3
    assert "had not set out" in line
    dos_codec.apply_position(save0, state)
    assert tuple(save0[0xC0:0xC3]) == (15, 1, 3)


def test_a_party_standing_in_new_phlan_is_left_exactly_where_it_is():
    """The regression the obvious fix causes, and the test that matters most
    here: a rule reading "area 0 means the party has not set out" would move
    thirteen real containers out of New Phlan to the arrival square and
    reset their clocks.  A party at `3,9` facing south at 16:58 stays there
    and is told nothing (#326)."""
    savgam = _new_phlan_savgam()
    state = world_state.from_dos(savgam)
    save0 = bytearray(0x1C00)
    line = dos_codec.apply_file_cache(save0, state)
    assert "had not set out" not in line
    at = dos_codec.FILE_CACHE[0] - dos_codec.SAVE0_BASE
    assert save0[at + dos_codec.CACHE_ECL] == 0 and save0[at + dos_codec.CACHE_GEO] == 0
    assert save0[dos_codec.INDOORS - dos_codec.SAVE0_BASE] == 1
    dos_codec.apply_position(save0, state)
    assert tuple(save0[0xC0:0xC3]) == (3, 9, 2)
    note, _ = dos_codec.apply_clock(save0, state)
    assert "16:58" in note


@needs_dos_saves
def test_a_conversion_with_no_disks_at_all_gives_every_character_his_own_face(
        monkeypatch):
    """The whole point of storing the menu.  Donald, 2026-09-06: *"Just pull
    them from each title so you can cross reference them. Then you don't
    need the disks at all."*

    No `POOL<n>.D64`, no `GEN`, no `START.EXE`: every reader that could
    fetch the creation menu off a disk is replaced with one that fails the
    test if it is so much as called, the icon and `ANIMATE00` are dummy
    bytes, and `new_save` is given no `portraits` at all.  Every character
    still arrives with the `HEAD<xx>`/`BODY<xx>` id his own DOS menu
    position names, the sheet-portrait switch comes out on, and the report
    carries no portrait line.

    `#131 (Lift WISH_EXPERIMENTAL_DOS_IMPORT, which needs the import
    working for all three C64 titles)` had this refuse for one night --
    `NoPortraitTablesError`, a sentence Donald never approved -- and the
    refusal, the sentence and the exception are all gone.  Watched failing
    with the fallback in `to_neutral` taken out: the switch comes out
    `PORTRAIT_OFF` and every id reads zero.
    """
    from goldbox import portraits

    def never(*_args, **_kwargs):
        raise AssertionError("a game file was read for the creation menu")

    for name in ("tables_from_disks", "tables_from_c64", "tables_from_dos"):
        monkeypatch.setattr(portraits, name, never)
    monkeypatch.setattr(dos_codec, "tables_from_dos", never)
    assert not hasattr(dos_codec, "NoPortraitTablesError")
    assert not hasattr(dos_codec, "NO_PORTRAIT_TABLES")

    menu = portraits.stored_tables(None)
    where = _save_dir()
    slot = party = None
    for candidate in dos_codec.slots_available(where):
        candidate_party = dos_codec.read_party(where, candidate)
        if all(menu.head_art(c.get("portrait_head")) is not None
               and menu.body_art(c.get("portrait_body")) is not None
               for c in candidate_party):
            slot, party = candidate, candidate_party
            break
    if slot is None:
        pytest.skip("no DOS slot here has every character in the menu")

    save0, _save1, report = dos_codec.new_save(where, slot, bytes(36), bytes(852))
    assert save0[dos_codec.PORTRAIT_SWITCH - dos_codec.SAVE0_BASE] == dos_codec.PORTRAIT_ON
    seen = 0
    for index, char in enumerate(party):
        place = dos_codec.marching_slot(index, len(party))
        rec_at = dos_codec.SLOT_AREA - dos_codec.SAVE0_BASE + place * dos_codec.SLOT_STRIDE
        assert save0[rec_at + 0x0FE] == \
            menu.head_art(char.get("portrait_head")), char.name
        assert save0[rec_at + 0x0FF] == \
            menu.body_art(char.get("portrait_body")), char.name
        seen += 1
    assert seen == len(party) >= 1
    assert not [d for d in report.dropped if "portrait" in d.lower()], \
        report.dropped


@pytest.mark.skipif(not gamedata.have_specimen("por-party-l1-intown"),
                    reason="needs the New Phlan tour specimen")
def test_a_real_new_phlan_party_converts_where_it_stood():
    """`WISH-SPEC-por-party-l1-intown` slot E: six characters this project
    rolled, taken through the opening tour and saved by the game's own
    `ENCAMP > SAVE` at `0,4` facing west in New Phlan.  Area 0, map 0, and
    a staged script.  It converts to where it stood, with no sentence about
    the beginning of the story (#326)."""
    where = gamedata.specimen("por-party-l1-intown")
    savgam = (where / "SAVGAME.DAT").read_bytes()
    assert sg.current_area(savgam) == 0
    assert not dos_codec.never_adventured(savgam)
    save0 = bytearray(0x1C00)
    report = dos_codec.convert_save(where, "E", save0)
    assert tuple(save0[0xC0:0xC3]) == sg.position(savgam) == (0, 4, 3)
    assert report.messages == []


@pytest.mark.skipif(not gamedata.have_specimen("por-304-modify-exited"),
                    reason="needs the never-adventured specimen")
def test_a_real_never_adventured_party_converts_and_the_player_is_told():
    """`WISH-SPEC-por-304-modify-exited` slot C: two fighters rolled in the
    game's own CREATE NEW CHARACTER, added to the party and saved from the
    party-formation menu, never having pressed `BEGIN ADVENTURING`.  It was
    refused with the `$49E6` message until #326; it converts to the start
    of the story now, and the one sentence Donald approved on #301 is on
    the report for the messages pane."""
    where = gamedata.specimen("por-304-modify-exited")
    savgam = (where / "SAVGAMC.DAT").read_bytes()
    assert dos_codec.never_adventured(savgam)
    assert sg.word(savgam, dos_codec.LATER_BEGUN_WORD) == 0
    save0 = bytearray(0x1C00)
    report = dos_codec.convert_save(where, "C", save0)
    assert tuple(save0[0xC0:0xC3]) == (15, 1, 3)
    assert save0[dos_codec.INDOORS - dos_codec.SAVE0_BASE] == 1
    assert save0[dos_codec.CURRENT_SCRIPT - dos_codec.SAVE0_BASE] == 0
    assert report.messages == [dos_codec.NOT_SET_OUT]
    assert dos_codec.NOT_SET_OUT in report.summary()
    assert report.unaccounted == []
