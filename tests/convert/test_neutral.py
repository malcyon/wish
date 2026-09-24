from __future__ import annotations

"""The neutral character record, and the codecs either side of it.

`docs/117-save-conversion.md` and issue #25: three formats in two directions
is six converters, three codecs around one neutral record is three readers and
three writers.  These are the tests of the middle -- that a value put into it
comes back out of a writer unchanged, that a value no writer will take is
*reported*, and that a value the reader does not stand behind is refused
rather than guessed at.
"""


import dataclasses

import pytest
from support.dossave import _save_dir, needs_dos_saves
from support.neutralrecords import _filled

from goldbox import amiga_pod, c64_codec, c64_port, derive, dos_codec, dos_port, neutral
from goldbox import levels as level_tables
from goldbox.encoding import combat_value
from goldbox.layout import FIELDS_BY_NAME as C64_FIELDS
from goldbox.layout import Confidence
from goldbox.neutral import NeutralCharacter, Provenance
from goldbox.record import CharacterRecord

# --- the vocabulary ----------------------------------------------------------

def test_a_field_outside_the_vocabulary_is_refused():
    """A reader that invents a name would be a field silently unread by every
    writer, which is the failure the declared vocabulary exists to stop."""
    char = NeutralCharacter("test")
    with pytest.raises(neutral.NeutralError):
        char.set("strenght", 18, "a typo")


def test_every_field_the_c64_writer_takes_is_declared():
    """The writer's own table cannot name a field the vocabulary does not."""
    for name, c64 in c64_codec.DIRECT:
        assert name in neutral.FIELDS, name
        assert c64 in C64_FIELDS, c64


def test_the_dos_reader_and_the_neutral_vocabulary_agree_on_combat_figure():
    """#305: `dos_codec.to_neutral`'s `DIRECT` loop reads `dos_codec.fields[dos_name]`
    and then does `out.set(dos_name, ...)` with the very same string, so the
    DOS field name and the neutral field it becomes cannot be two different
    spellings -- renaming one without the other leaves the byte unset on one
    side. `combat_figure` replaced the old `party_order` misnomer once #305
    read the byte as an allocated combat-picture slot rather than a marching
    position; this pins the two tables to the same name so the next rename
    cannot half-land the way this one first did.

    The C64's own field at `goldbox/layout.py` 0x10D keeps the name
    `party_order` -- a different byte that shares the old name by
    coincidence, `editor/binding.py` wiring it to `goldbox.layout.LAYOUT`
    rather than to this neutral field -- so `c64_codec.DIRECT` still maps
    the *neutral* `combat_figure` onto the *C64* `party_order`.
    """
    assert dict(dos_codec.DIRECT)["combat_figure"] == "combat_figure"
    assert "combat_figure" in neutral.FIELDS
    assert "combat_figure" in dos_port.FIELDS_BY_NAME
    assert "party_order" not in neutral.FIELDS
    assert "party_order" not in dos_port.FIELDS_BY_NAME
    assert dict(c64_codec.DIRECT)["combat_figure"] == "party_order"
    assert "party_order" in C64_FIELDS


def test_a_synthetic_dos_record_reads_its_combat_figure_byte_as_neutral():
    """The round trip the table check above cannot see: a DOS record built
    from zero bytes but for `combat_figure` (0x0BF, #305) comes back out of
    `dos_codec.to_neutral` under that name, not under the old `party_order`."""
    raw = bytearray(dos_port.RECORD_SIZE)
    field = dos_port.FIELDS_BY_NAME["combat_figure"]
    raw[field.offset] = 4
    char = dos_codec.to_neutral(dos_codec.DosCharacter(bytes(raw)))
    assert char.get("combat_figure") == 4
    assert char.get("party_order") is None    # not a neutral field any more


def test_the_two_ports_share_one_report_type():
    """Step 2 of #25: every direction reports what it dropped the same way."""
    assert issubclass(c64_codec.Report, neutral.Report)
    assert issubclass(amiga_pod.Report, neutral.Report)
    # And one builder makes both disposition tables.
    assert dos_codec.field_disposition() == neutral.disposition(
        dos_codec.DIRECT, dos_codec.TRANSFORMED, dos_codec.DROPPED, "the C64's",
        derived=tuple((n, w) for n, w, _run in dos_codec.DERIVED),
        constants=dos_codec.CONSTANTS)
    # Spelled `POD_WRITE_*` since #470's stage 10 split the Amiga codec by
    # title: these four are the Pools of Darkness writer's own tables and
    # were named as though they were the whole port's.
    assert amiga_pod.pod_write_field_disposition() == neutral.disposition(
        amiga_pod.POD_WRITE_DIRECT,
        amiga_pod.POD_WRITE_TRANSFORMED + amiga_pod.POD_WRITE_WHEN_PRESENT,
        amiga_pod.POD_WRITE_DROPPED, "the Amiga's",
        derived=amiga_pod.POD_WRITE_DERIVED,
        constants=amiga_pod.POD_WRITE_CONSTANTS)


def test_undeclared_finds_a_field_no_disposition_names():
    """The shared form of `test_every_declared_field_has_a_disposition`."""
    declared = {f.name for f in dos_port.LAYOUT
                if not f.name.startswith("gap_")}
    assert neutral.undeclared(declared, dos_codec.field_disposition()) == \
        (set(), set())
    # Take one away and it is named, rather than lost.
    short = dict(dos_codec.field_disposition())
    del short["strength"]
    assert neutral.undeclared(declared, short) == ({"strength"}, set())


# --- confidence: a writer refuses what the reader does not stand behind ------

def test_a_value_graded_unknown_is_not_written():
    """The point of a grade per field: a codec refuses to write what it does
    not understand rather than writing a plausible-looking guess."""
    char = NeutralCharacter("test")
    char.set("wisdom", 9, "somewhere", Confidence.UNKNOWN)
    assert char.get("wisdom") == 9          # it is carried
    assert char.take("wisdom") is None      # and it is not written

    rec, rep = c64_codec.write(char)
    assert rec.wisdom == 0
    assert any("wisdom" in d and "UNKNOWN" in d for d in rep.dropped)


def test_a_grade_a_writer_will_take_is_written():
    char = NeutralCharacter("test")
    char.set("wisdom", 9, "somewhere", Confidence.PROBABLE)
    rec, rep = c64_codec.write(char)
    assert rec.wisdom == 9
    assert not any("wisdom" in d for d in rep.dropped)


def test_a_value_graded_exactly_at_the_minimum_grade_asked_for_is_taken():
    """The minimum grade is the lowest one a writer accepts, so a value graded
    at it is written; only a lower grade is refused."""
    char = NeutralCharacter("test")
    char.set("wisdom", 9, "somewhere", Confidence.PROBABLE)
    taken = char.take("wisdom", Confidence.PROBABLE)
    assert taken is not None
    assert taken.value == 9


def test_a_probable_value_is_refused_when_confirmed_is_asked_for():
    """PROBABLE and CONFIRMED are different grades: a writer that will only
    stand behind CONFIRMED must not be handed a PROBABLE value."""
    char = NeutralCharacter("test")
    char.set("wisdom", 9, "somewhere", Confidence.PROBABLE)
    assert char.take("wisdom", Confidence.CONFIRMED) is None
    char.set("strength", 16, "somewhere", Confidence.CONFIRMED)
    assert char.take("strength", Confidence.CONFIRMED) is not None


def test_a_lowercase_name_from_a_non_dos_source_is_folded_to_capitals():
    """`#290 (A character named in lower case draws as punctuation on the
    C64, and only the DOS import folds the name)`: `goldbox.dos_codec.c64_name`
    only reached the DOS-to-C64 path. An Amiga source, a YAML import or
    anything else that builds a `NeutralCharacter` and calls
    `c64_codec.write` went through unfolded, and the C64 drew the name as
    punctuation and digits -- watched on the running machine, `Guy de
    Valois ` drew as `G59 $% V!,/)3`. The fold now lives in
    `goldbox.petscii.encode_record_name`, which this call reaches even
    though nothing here is DOS."""
    char = NeutralCharacter("test", source="a made-up character")
    char.set("name", "Guy de Valois ", "made up", Confidence.CONFIRMED,
             Provenance.RESHAPED)
    rec, _ = c64_codec.write(char)
    assert rec.to_bytes()[:20] == b"GUY DE VALOIS" + b"\x00" * 7


# --- losslessness through the middle -----------------------------------------


def test_every_value_a_writer_takes_comes_back_out_of_the_record():
    """The round trip the neutral layer can have on its own: put a value in,
    write it, and read the same value back off the C64 record.

    The five saving-throw columns, `thac0_base` and `thac0_current` are the
    deliberate exceptions, checked on their own below. `write` recomputes the
    saves from level, race and constitution the way the C64's own trainer
    stores them, rather than copying the neutral value across, for a title
    whose racial saving-throw bonus is measured (`#311 (A DOS dwarf, gnome or
    halfling converted to the C64 loses his constitution bonus to saving
    throws, because the C64 keeps it inside the five stored bytes)`) --
    `_filled()` defaults to Pool of Radiance, which is one. `thac0_base` is
    recomputed from the class levels through this title's own table rather
    than copied, because a source's own port may have written it through a
    different one (`#366 (A converted magic-user or thief arrives with the
    other port's THAC0, because the two ports ship different tables and the
    conversion copies the byte)`). `thac0_current` is recomputed from that
    same `thac0_base` plus the AD&D strength bonus, the way `LIBRARY $3918`
    rebuilds it at the party's first fight, rather than copied from the
    source (`#405 (A converted character's THAC0 on the C64 sheet is the
    source save's stored byte, and the engine only corrects it at his first
    fight)`). A field that quietly stopped round-tripping for a different
    reason must still fail the loop below, so all three are named and
    excluded rather than the loop being weakened.

    The eight thief-skill columns are the fourth exception, and are checked
    the same way below. `write` recomputes them from the thief level, race
    and dexterity through the C64 title's own table, rather than copying the
    source's, for a title whose racial thief row is confirmed to differ
    between the two ports (`#431 (A converted halfling thief keeps the other
    port's skill percentages, because the two ports ship different halfling
    rows)`) -- `_filled()` defaults to Pool of Radiance, which is one.
    """
    from goldbox import spells

    char = _filled()
    rec, rep = c64_codec.write(char)
    save_columns = {field for field, _ in c64_codec._SAVE_COLUMNS}
    thief_columns = {field for field, _ in c64_codec._THIEF_SKILL_COLUMNS}

    assert rec.name == "ROUNDTRIP"
    for field, c64 in c64_codec.DIRECT:
        if (field in save_columns or field in thief_columns
                or field in ("thac0_base", "thac0_current")):
            continue
        assert rec.get(c64) == char.get(field), field
    expected_thac0 = level_tables.base_thac0(char.get("levels"), char.game)
    assert rec.thac0_base_value == expected_thac0
    # Not a round trip: `char`'s made-up `thac0_base` is 8 (a value plucked
    # from `DIRECT`'s position), and the class levels (fighter 7, thief 3)
    # give 14 through the C64's own table.
    assert expected_thac0 != combat_value(char.get("thac0_base"))
    # `thac0_current`: this record's own recomputed `thac0_base` byte plus
    # the strength-to-hit bonus for `char`'s made-up strength of 1 -- 0,
    # since `derive.strength_bonuses` has no penalty below 17 -- gated on
    # `strength_bonus_flag`, which `write` always sets to 1 (#277). Not a
    # round trip: `char`'s made-up `thac0_current` is discarded entirely.
    assert rec.get("strength_bonus_flag") == 1
    hit, _ = derive.strength_bonuses(char.get("strength"),
                                     char.get("exceptional_strength"))
    assert hit == 0
    assert rec.get("thac0") == rec.get("thac0_base")
    assert level_tables.racial_save_bonus_measured(char.game)
    expected_saves = level_tables.saving_throws(
        char.get("levels"), char.get("race"), char.get("constitution"),
        char.game)
    for value, (field, c64) in zip(expected_saves, c64_codec._SAVE_COLUMNS):
        assert rec.get(c64) == value, field
        # Not a round trip: the class row less the constitution bonus, not
        # the plain value this test put in.
        assert value != char.get(field), field
    assert level_tables.thief_skill_race_differs_by_port(char.game)
    expected_skills = level_tables.thief_skills(
        char.get("levels")["thief"], char.get("race"), char.game,
        dexterity=char.get("dexterity"))
    for value, (field, c64) in zip(expected_skills,
                                   c64_codec._THIEF_SKILL_COLUMNS):
        assert rec.get(c64) == value, field
        # Not a round trip: the C64's own row for an elf thief of level 3,
        # not the plain value this test put in.
        assert value != char.get(field), field
    assert spells.spells_known(rec.to_bytes()) == [1, 5, 55]
    assert [b for b in rec.get_raw("spells_memorised") if b] == [44, 21, 3]
    assert rec.get("level_fighter") == 7
    assert rec.get("level_thief") == 3
    assert rec.get_raw("spells_castable")[:3] == bytes((0x34, 0x23, 0x12))
    assert rec.get("size_small") == 1
    # Not 6, and not a round trip: the writer computes the turning byte from
    # the cleric and paladin levels rather than copying a source's (#288), and
    # this character is a fighter 7 / thief 3, who turns nothing.
    # `tests/records/test_turning.py` is where the value itself is checked.
    assert rec.get("turn_power") == 0
    assert rec.get_raw("attack_forms") == bytes(range(1, 9))
    assert [b for b in rec.get_raw("item_effects") if b] == [18, 47]
    assert rec.get_raw("inventory")[:16] == bytes(range(16))
    assert rec.get_raw("roster_tail") == bytes(range(9))
    # And every one of the 580 bytes has a provenance, as `docs/117` asks.
    assert rep.unaccounted == []


def test_a_field_the_target_cannot_represent_is_reported(monkeypatch):
    """Never dropped silently: a field this writer takes nothing from.

    The example is whatever is still in `c64_codec.DROPPED`, which is how a
    writer declares the fields it takes nothing from -- `portrait_head` left
    that list in #57, when the C64 writer learnt to copy one it is given, and
    `encumbrance` left it on 2026-09-13 for `c64_codec.DERIVED`, the C64
    recomputing the total from the purses and item weights while it draws a
    sheet.  Naming the list rather than a field keeps the test about the
    mechanism: `Writer.finish` composes a line for a field the record carries
    and the writer never took.
    """
    # `DROPPED` is empty once the writer takes something from every field, so
    # the test writes against a made-up entry: what it checks is
    # `Writer.finish`, not the list.
    monkeypatch.setitem(neutral.FIELDS, "made_up_field", "a made-up field")
    monkeypatch.setattr(c64_codec, "DROPPED",
                        (("made_up_field", "a made-up reason"),))
    names = [n for n, _ in c64_codec.DROPPED]
    for name in names:
        char = _filled()
        char.set(name, 42, "made up")
        _, rep = c64_codec.write(char)
        assert any(d.startswith(f"{name}:") for d in rep.dropped), (
            name, rep.dropped)


def test_a_class_the_c64_has_no_level_slot_for_is_silent():
    """A DOS class the C64 title's level array has no slot for is still
    left off the sheet -- but not named, since #399 (A conversion that runs
    out of item or trait slots tells the player nothing, because the pane
    never shows a warning) drafted a sentence for this and Donald ruled it
    unneeded after a 950-character census found nobody reaching any of that
    ticket's ceilings: "I agree that we do not need the sentences." """
    char = _filled()
    char.set("levels", {"fighter": 7, "druid": 4}, "made up")
    rec, rep = c64_codec.write(char)
    assert not any("druid" in w for w in rep.warnings)
    assert rec.get("level_fighter") == 7


def test_a_spell_the_target_has_no_bit_for_is_silent():
    """Restoration, id 56, is one bit short of Pool of Radiance's own C64
    spellbook mask -- still left off, but not named, on the same #399
    ruling as the class and item ceilings below.  #411 (Nobody knows
    whether a converted cleric loses Restoration, because the spellbook
    field is one bit short of the game's own spell list) is where a future
    finding about who can actually reach this belongs."""
    char = _filled()
    char.set("spells_known", [1, 56], "made up")
    rec, rep = c64_codec.write(char)
    assert not any("Restoration" in w for w in rep.warnings)
    back = c64_codec.read(rec, game=char.game).get("spells_known")
    assert 1 in back and 56 not in back


def test_more_items_than_slots_is_silent():
    """Truncated to sixteen and not named -- #399's own census found this
    ceiling touched only by a specimen the project manufactured to reach
    it, never by a real character.  Donald, 2026-09-07: "I agree that we do
    not need the sentences."."""
    char = _filled()
    items = [bytes([n]) + bytes(15) for n in range(1, 21)]
    char.set("inventory", items, "made up")
    rec, rep = c64_codec.write(char)
    assert not any("carry only sixteen" in w for w in rep.warnings)
    raw = rec.get_raw("inventory")
    assert [raw[n * 16] for n in range(16)] == list(range(1, 17))


def test_more_innate_effects_than_slots_is_silent():
    """#236 (A character converted to the C64 with more than ten innate
    effects loses the extra ones with no report) drafted a sentence for
    this; #399's own census found no real character reaching the ten trait
    slots (widest anywhere: 5, engine-written), and Donald ruled the
    sentence unneeded -- so eleven ids still fill only the first ten slots,
    silently."""
    char = _filled()
    char.set("innate_effects", list(range(1, 12)), "made up")
    rec, rep = c64_codec.write(char)
    assert not any("on their own" in w for w in rep.warnings)
    assert list(rec.get_raw("item_effects")) == list(range(1, 11))


def _granted(effect_id: int) -> bytes:
    """One nine-byte `granted_effects` node, in the shared shape
    `goldbox/dos_codec.py` reads: id, a zero duration, the value `0x0C` a passive
    item grant carries, a clear removal flag, and a NULL next pointer."""
    return bytes((effect_id, 0, 0, 0x0C, 0, 0, 0, 0, 0))


def test_a_granted_effect_lands_in_a_free_trait_slot():
    """#232: an item-granted effect used to be reported as a drop and
    written nowhere; now the id lands where the item's own READY would put
    it (`docs/171-c64-trait-slots.md`, #252)."""
    char = _filled()
    char.set("granted_effects", [_granted(61)], "made up")
    rec, rep = c64_codec.write(char)
    assert 61 in rec.get_raw("item_effects")
    assert not any("61" in d for d in rep.dropped)


def test_a_granted_effect_fills_from_the_top_after_the_innate_ones():
    """Racial ids seed from slot 0, the way `GEN` itself does; a readied
    item's id is granted into the first free slot scanning from 9, the way
    `SPELLE04 $ADD4` itself scans when an item is readied."""
    char = _filled()
    char.set("innate_effects", [18, 47], "made up")
    char.set("granted_effects", [_granted(61)], "made up")
    rec, _ = c64_codec.write(char)
    slots = list(rec.get_raw("item_effects"))
    assert slots[:2] == [18, 47]
    assert slots[9] == 61


def test_more_granted_effects_than_free_slots_is_silent():
    """Nine innate ids leave one free slot; two item grants do not both
    fit -- still not named, on the same #399 ruling as the test above."""
    char = _filled()
    char.set("innate_effects", list(range(1, 10)), "made up")
    char.set("granted_effects", [_granted(61), _granted(89)], "made up")
    rec, rep = c64_codec.write(char)
    assert not any("effects your character's items grant" in w
                   for w in rep.warnings)
    assert rec.get_raw("item_effects")[9] == 61


# --- the DOS reader, against real files --------------------------------------

@needs_dos_saves
def test_the_dos_reader_sets_nothing_the_c64_writer_leaves_behind():
    """The DOS->C64 path as reader + writer: everything the reader carries,
    the writer takes.  A field appearing here would be one to build the C64
    side out for, or one to say out loud in `DROPPED`."""
    for path in sorted(_save_dir().glob("*.SAV")):
        if path.stat().st_size != dos_port.RECORD_SIZE:
            continue
        char = dos_codec.to_neutral(dos_codec.read_character(path))
        assert char.port == "DOS"
        _, rep = c64_codec.write(char)
        assert not [d for d in rep.dropped if "takes nothing from it" in d]


@needs_dos_saves
def test_the_reader_grades_every_value_it_carries():
    """A value with no grade cannot be refused, so every one carries the grade
    `goldbox/dos_port.py` gives the field it was read from."""
    path = next(p for p in sorted(_save_dir().glob("*.SAV"))
                if p.stat().st_size == dos_port.RECORD_SIZE)
    char = dos_codec.to_neutral(dos_codec.read_character(path))
    assert char.fields
    for name in char.keys():
        assert isinstance(char.value(name).confidence, Confidence)
        assert char.value(name).origin


# --- the neutral vocabulary's own disposition --------------------------------

def test_every_neutral_field_has_a_disposition_in_every_writer():
    """The gap the design review found: `goldbox.dos_codec.field_disposition` checks the
    DOS layout and nothing checked the *neutral* vocabulary, so a name added
    to `FIELDS` and never wired up would rot in silence.

    Both writers now state what they do with each of the 64 names, and this is
    what fails when one of them forgets.

    **The Amiga writer is named rather than duck-typed since #470's stage 10.**
    A module-wide `field_disposition` read as the whole port's and was the
    Pools of Darkness writer's alone -- the Amiga has three writers and the
    other two already answer under their own names, `write_por` through
    `goldbox.dos_codec`'s table and `later_field_disposition(deltas)`.
    """
    tables = ((c64_codec, c64_codec.field_disposition()),
              (amiga_pod, amiga_pod.pod_write_field_disposition()))
    for writer, table in tables:
        unaccounted, unknown = neutral.undeclared(neutral.FIELDS, table)
        assert unaccounted == set(), (writer.__name__, "no disposition")
        assert unknown == set(), (writer.__name__, "not in the vocabulary")


def test_a_name_dropped_from_a_writers_table_is_named_rather_than_lost():
    short = dict(c64_codec.field_disposition())
    del short["race"]
    assert neutral.undeclared(neutral.FIELDS, short) == ({"race"}, set())


# --- the shared take-refuse-report protocol ----------------------------------

def _writer(char, floor=Confidence.GUESS, dropped=(), derived=(),
            constants=()):
    rep = neutral.Report()
    return neutral.Writer(char, rep, into="test", floor=floor,
                          dropped=dropped, derived=derived,
                          constants=constants), rep


def test_the_minimum_grade_applies_to_a_derivation_as_much_as_to_a_copy():
    """`NeutralCharacter.get` applies no minimum grade, which is why `Writer.get`
    exists: a byte computed from a field the writer would have refused to copy
    would be a guess wearing a rule's clothes."""
    char = NeutralCharacter("test")
    char.set("race", 3, "a value nobody measured", Confidence.UNKNOWN)
    assert char.get("race") == 3           # the record hands it over
    w, _ = _writer(char)
    assert w.get("race", 0) == 0           # the writer will not stand behind it


def test_a_refusal_carries_the_drops_that_rode_on_it():
    """`Value.dropped` is what the reader left behind to produce a value, and
    that is a fact about the source whether or not the value is written."""
    char = NeutralCharacter("test")
    char.set("innate_effects", [18], "the .SPC file", Confidence.UNKNOWN,
             dropped=[".SPC effect 90: a running effect"])
    w, rep = _writer(char)
    assert w.use("innate_effects") is None
    assert any("not a grade this conversion will write" in d
               for d in rep.dropped)
    assert ".SPC effect 90: a running effect" in rep.dropped


def test_the_closing_sweep_quotes_the_codecs_own_reason():
    char = NeutralCharacter("test")
    char.set("encumbrance", 300, "the DOS byte")
    w, rep = _writer(char, dropped=(("encumbrance", "derived; no such field"),))
    w.finish()
    assert "encumbrance: derived; no such field" in rep.dropped


def test_the_closing_sweep_names_a_field_the_codec_never_declared():
    char = NeutralCharacter("test")
    char.set("encumbrance", 300, "the DOS byte")
    w, rep = _writer(char)
    w.finish()
    assert any("takes nothing from it" in d for d in rep.dropped)


def test_emitting_a_value_reports_the_drops_that_rode_on_it():
    """A value the writer does write still carries what the reader left behind
    to produce it, and that reaches the report beside the bytes it became."""
    char = NeutralCharacter("test")
    char.set("innate_effects", [18], "the .SPC file",
             dropped=[".SPC effect 90: a running effect"])
    w, rep = _writer(char)
    v = w.use("innate_effects")
    assert v is not None
    w.emit(v, "traits", 0, 2)
    assert rep.dropped == [".SPC effect 90: a running effect"]


def test_the_summary_lists_the_count_then_each_warning_then_each_drop():
    rep = neutral.Report(total=4)
    rep.note(0, 2, "first two bytes")
    rep.warnings.append("a value was clamped")
    rep.dropped.append("a field with no home")
    assert rep.summary().split("\n") == [
        "2/4 bytes accounted for",
        "  WARNING: a value was clamped",
        "  dropped: a field with no home",
    ]


def test_lost_puts_the_line_on_losses_and_on_warnings():
    rep = neutral.Report()
    rep.lost("hp_max: 65535 does not fit the DOS one-byte field; clamped")
    line = "hp_max: 65535 does not fit the DOS one-byte field; clamped"
    assert rep.losses == [line]
    assert rep.warnings == [line]
    assert rep.dropped == []


def test_a_readers_warning_copied_by_the_closing_sweep_is_not_a_loss():
    char = NeutralCharacter("test")
    char.warnings.append("the reader found a name with no terminator")
    w, rep = _writer(char)
    w.finish()
    assert rep.warnings == ["the reader found a name with no terminator"]
    assert rep.losses == []


def test_the_summary_of_a_report_with_no_losses_has_no_lost_line():
    rep = neutral.Report(total=1)
    rep.warnings.append("a note")
    assert "lost" not in rep.summary()


def test_the_summary_lists_each_loss_after_the_drops():
    rep = neutral.Report(total=4)
    rep.dropped.append("a field with no home")
    rep.lost("a value was clamped")
    assert rep.summary().split("\n") == [
        "0/4 bytes accounted for",
        "  WARNING: a value was clamped",
        "  dropped: a field with no home",
        "  lost: a value was clamped",
    ]


def test_a_subclass_that_declares_its_own_losses_field_still_works():
    @dataclasses.dataclass
    class Sub(neutral.Report):
        losses: list[str] = dataclasses.field(default_factory=list)

    rep = Sub()
    rep.lost("x")
    assert rep.losses == ["x"] and rep.warnings == ["x"]


# --- derived and constant rows are reported, and are not drops --------------

def _three_untaken():
    char = NeutralCharacter("test")
    char.set("encumbrance", 300, "the DOS byte")
    char.set("attack_level", 4, "the DOS byte")
    char.set("armour_class_base", 50, "the DOS byte")
    return char


def test_a_derived_name_goes_to_derived_and_not_to_dropped():
    w, rep = _writer(_three_untaken(),
                     derived=(("encumbrance", "the engine rebuilds it"),))
    w.finish()
    assert "encumbrance: the engine rebuilds it" in rep.derived
    assert not [d for d in rep.dropped if "encumbrance" in d]


def test_a_constants_name_goes_to_derived_and_not_to_dropped():
    w, rep = _writer(_three_untaken(),
                     constants=(("armour_class_base", "fifty for every record"),))
    w.finish()
    assert "armour_class_base: fifty for every record" in rep.derived
    assert not [d for d in rep.dropped if "armour_class_base" in d]


def test_a_dropped_name_stays_on_dropped_when_other_tables_are_given():
    w, rep = _writer(_three_untaken(),
                     dropped=(("attack_level", "no such byte"),),
                     derived=(("encumbrance", "rebuilt"),))
    w.finish()
    assert "attack_level: no such byte" in rep.dropped
    assert not [d for d in rep.derived if "attack_level" in d]


def test_each_untaken_name_lands_on_exactly_one_list():
    w, rep = _writer(_three_untaken(),
                     dropped=(("attack_level", "no such byte"),),
                     derived=(("encumbrance", "rebuilt"),),
                     constants=(("armour_class_base", "fifty"),))
    w.finish()
    assert rep.dropped == ["attack_level: no such byte"]
    assert sorted(rep.derived) == ["armour_class_base: fifty",
                                   "encumbrance: rebuilt"]
    assert rep.losses == []


def test_a_name_in_no_table_keeps_the_generic_drop_line_beside_derived_ones():
    w, rep = _writer(_three_untaken(),
                     derived=(("encumbrance", "rebuilt"),))
    w.finish()
    assert sorted(d.split(":")[0] for d in rep.dropped) == [
        "armour_class_base", "attack_level"]
    assert all("takes nothing from it" in d for d in rep.dropped)


def test_a_taken_field_is_on_no_list_even_when_it_is_declared_derived():
    char = NeutralCharacter("test")
    char.set("encumbrance", 300, "the DOS byte")
    w, rep = _writer(char, derived=(("encumbrance", "rebuilt"),))
    assert w.use("encumbrance") is not None
    w.finish()
    assert rep.derived == [] and rep.dropped == []


def test_the_derived_line_reads_as_a_drop_line_would_have():
    char = NeutralCharacter("test")
    char.set("encumbrance", 300, "the DOS byte")
    w, as_drop = _writer(char, dropped=(("encumbrance", "rebuilt"),))
    w.finish()
    w, as_derived = _writer(char, derived=(("encumbrance", "rebuilt"),))
    w.finish()
    assert as_derived.derived == as_drop.dropped


def test_the_summary_lists_each_derived_line_after_the_drops():
    rep = neutral.Report(total=4)
    rep.dropped.append("a field with no home")
    rep.derived.append("a field the engine rebuilds")
    rep.lost("a value was clamped")
    assert rep.summary().split("\n") == [
        "0/4 bytes accounted for",
        "  WARNING: a value was clamped",
        "  dropped: a field with no home",
        "  derived: a field the engine rebuilds",
        "  lost: a value was clamped",
    ]


def test_the_summary_of_a_report_with_no_derived_lines_has_no_derived_line():
    rep = neutral.Report(total=1)
    rep.dropped.append("a field with no home")
    assert rep.summary() == ("0/1 bytes accounted for\n"
                             "  dropped: a field with no home")


def test_a_count_of_dropped_plus_losses_does_not_include_derived():
    """The Save As refusal counts `dropped` and `losses` (`editor/saveplan.
    losses`); a stand-in with the same two-list read is enough to show a
    derived row cannot add to it while a real narrowing still does."""
    def losses(report):
        return [*report.dropped, *report.losses]

    w, rep = _writer(_three_untaken(),
                     dropped=(("attack_level", "no such byte"),
                              ("armour_class_base", "no such byte")),
                     derived=(("encumbrance", "rebuilt"),))
    w.finish()
    only_derived = neutral.Report()
    only_derived.derived.append("encumbrance: rebuilt")
    assert losses(only_derived) == []
    assert len(losses(rep)) == 2
    rep.lost("hp_max: clamped")
    assert "hp_max: clamped" in losses(rep)


# --- the C64 reader, as far as the Amiga and YAML writers need it ------------

@pytest.mark.parametrize("game,at,size", [
    ("pool-of-radiance", 0x020, 81),
    ("curse-of-the-azure-bonds", 0x020, 69),
    ("secret-of-the-silver-blades", 0x01B, 74),
])
def test_a_character_with_twenty_memorised_spells_keeps_all_twenty(
        game, at, size):
    """The reader stopped at the declared field and lost everything past it.

    A Pool of Radiance cleric 6 who is also a magic-user 6 may prepare
    twenty-one spells, and the reader took sixteen -- so five vanished from
    the Spells tab, from the YAML export and from anything converted, while
    the C64 game still had them (#268).

    Synthetic on purpose: no C64 party on this machine has more than three
    spells prepared, so the case that would catch this is one nobody can take
    off a disk.
    """
    ids = list(range(1, 21))
    rec = CharacterRecord.blank()
    assert c64_codec.memorised_span(game) == (at, size)
    c64_codec.set_memorised(rec, bytes(ids) + bytes(size - len(ids)), game)
    assert c64_codec.read(rec, game=game).get("spells_memorised") == ids
    # And the same twenty go back to the same bytes.
    char = NeutralCharacter("test", game=game)
    char.set("spells_memorised", ids, "made up")
    written, _ = c64_codec.write(char)
    assert written.to_bytes()[at:at + size] == bytes(ids) + bytes(size - 20)


@pytest.mark.parametrize("game", sorted(c64_codec.RECORD_SHAPES))
def test_the_c64_reader_supplies_what_the_c64_writer_takes(game):
    """Read a full record and write it back: every neutral name the writer's
    disposition says it takes is one the reader set.

    Once per title, because `abilities_second` is a field in only two of the
    three. In Pool of Radiance those seven bytes at `0x065` are seven more
    slots of the memorised list, so neither half of the codec touches them
    under that name, and a reader that set the field anyway would be putting
    spell ids into an ability array (#268).

    And `unnamed_0ab` is a field in only one of the three: Pool of Radiance's
    GEN draws the identity pair at `0x0E6`-`0x0E7` and Curse of the Azure
    Bonds' and Secret of the Silver Blades' never do (#258, The C64 side of
    0x0AB is unnamed, so the conversion drops it with no issue behind it).

    And `granted_effects` is taken but never comes back under its own name:
    it is written into a free trait slot the way an item's own READY would
    fill it (#232, #252), and a trait slot the converter filled and one
    READY filled are the same byte to the engine's own compare -- no
    provenance byte, so the reader cannot tell one from `innate_effects`
    (`docs/171-c64-trait-slots.md`).

    And `former_levels` is a field in the two titles whose `C64Deltas` has
    `dual_class` -- Pool of Radiance never touches `0x0B9`/`0x0BA` (#224).
    `_filled` sets no former class, so this round trip stays at Curse and
    Silver Blades' own "empty" convention, `{}`, and Pool of Radiance's
    reader leaves the name off entirely rather than guess at a slot number
    the title's own GEN never wrote (#256, #234).

    And `npc_control_byte` is set only for a companion -- `_filled` builds
    an ordinary player character, so `npc` is set true here to exercise it;
    otherwise the reader has nothing to set it from (#303).

    And `icon_head`, `icon_body` and `icon_colours` never come back under
    their own names either: the C64 keeps no head/body index at all, only
    the composed figure in the save's own table of eight, so `write` never
    reads the three off `char` directly -- a caller composes `write`'s own
    `icon` argument from them first, through `goldbox/iconparts.py` -- and
    `read` has nothing in the record to decompose them back out of (#612).

    And `scroll_bundles` never comes back: the C64 has no joined scroll, so
    the writer puts a joined scroll's scrolls one to a slot and the reader
    hands them back in `inventory` with nothing to say they were joined
    (#432).
    """
    char = _filled(game=game)
    char.set("npc", True, "test fixture: exercise npc_control_byte")
    rec, _ = c64_codec.write(char)
    back = c64_codec.read(rec, game=game)
    taken = ({n for n, _ in c64_codec.DIRECT}
             | {n for n, _ in c64_codec.TRANSFORMED})
    if not c64_codec.deltas_for(game).second_abilities:
        taken.discard("abilities_second")
    if not c64_codec.deltas_for(game).identity_pair:
        taken.discard("unnamed_0ab")
    if not c64_codec.deltas_for(game).dual_class:
        taken.discard("former_levels")
    taken.discard("granted_effects")
    # `read` is given no payload here, so it returns no effect rows.
    taken.discard("running_effects")
    taken.discard("icon_head")
    taken.discard("icon_body")
    taken.discard("icon_colours")
    taken.discard("scroll_bundles")
    assert taken - set(back.keys()) == set()


def test_deltas_for_refuses_a_title_it_has_not_measured():
    """Champions of Krynn has a `Game` but no `C64Deltas` row (#274): asking
    for its shape must not hand back Pool of Radiance's silently."""
    with pytest.raises(KeyError):
        c64_codec.deltas_for(c64_port.BY_KEY["champions-of-krynn"])
    with pytest.raises(KeyError):
        c64_codec.deltas_for("champions-of-krynn")


def test_deltas_for_still_defaults_pool_of_radiance_for_no_title_at_all():
    """None means a caller with no title in hand at all, not an unmeasured
    one, and every other test in this file calls `deltas_for(None)`
    expecting Pool of Radiance back."""
    assert c64_codec.deltas_for(None) is c64_codec.POOL_OF_RADIANCE_RECORD
    assert c64_codec.deltas_for() is c64_codec.POOL_OF_RADIANCE_RECORD


def test_the_c64_reader_grades_every_value_from_the_layout():
    back = c64_codec.read(c64_codec.write(_filled())[0])
    for name in back.keys():
        assert isinstance(back.value(name).confidence, Confidence)
        assert back.value(name).origin


def test_an_npc_template_s_drain_fill_converts_as_stored():
    """Both ports' templates hold FF in the drain pair and both games read it
    the same way, so a companion's stored bytes reach DOS unchanged."""
    rec = CharacterRecord.blank()
    rec.set_npc(True)
    rec.set("levels_drained", 255)
    rec.set("hp_lost_to_drain", 255)

    char = c64_codec.read(rec)
    assert char.get("levels_drained") == 255
    assert char.get("hp_lost_to_drain") == 255
    written, _items, _effects, _report = dos_codec.write(char)
    assert written[dos_port.FIELDS_BY_NAME["levels_drained"].offset] == 0xFF
    assert written[dos_port.FIELDS_BY_NAME["hp_lost_to_drain"].offset] == 0xFF

    rec.set_npc(False)
    assert c64_codec.read(rec).get("levels_drained") == 255
    assert c64_codec.read(rec).get("hp_lost_to_drain") == 255
