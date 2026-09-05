from __future__ import annotations

"""The neutral character record, and the codecs either side of it.

`docs/117-save-conversion.md` and issue #25: three formats in two directions
is six converters, three codecs around one neutral record is three readers and
three writers.  These are the tests of the middle -- that a value put into it
comes back out of a writer unchanged, that a value no writer will take is
*reported*, and that a value the reader does not stand behind is refused
rather than guessed at.
"""


import pytest
from test_dossave import _save_dir, needs_dos_saves

from goldbox import amiga, c64_codec, dos, dos_layout, games, neutral
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


def test_the_two_ports_share_one_report_shape():
    """Step 2 of #25: every direction reports what it dropped the same way."""
    assert issubclass(c64_codec.Report, neutral.Report)
    assert issubclass(amiga.Report, neutral.Report)
    # And one builder makes both disposition tables.
    assert dos.field_disposition() == neutral.disposition(
        dos.DIRECT, dos.TRANSFORMED, dos.DROPPED, "the C64's")
    assert amiga.field_disposition() == neutral.disposition(
        amiga.DIRECT, amiga.TRANSFORMED, amiga.DROPPED, "the Amiga's")


def test_undeclared_finds_a_field_no_disposition_names():
    """The shared form of `test_every_declared_field_has_a_disposition`."""
    declared = {f.name for f in dos_layout.LAYOUT
                if not f.name.startswith("gap_")}
    assert neutral.undeclared(declared, dos.field_disposition()) == \
        (set(), set())
    # Take one away and it is named, rather than lost.
    short = dict(dos.field_disposition())
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


def test_a_lowercase_name_from_a_non_dos_source_is_folded_to_capitals():
    """`#290 (A character named in lower case draws as punctuation on the
    C64, and only the DOS import folds the name)`: `goldbox.dos.c64_name`
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

def _filled(game=None) -> NeutralCharacter:
    """A neutral character with a different value in every field, so a value
    landing in the wrong place cannot pass."""
    char = NeutralCharacter("test", source="a made-up character", game=game)
    char.set("name", "ROUNDTRIP", "made up", Confidence.CONFIRMED,
             Provenance.RESHAPED)
    for n, (field, _) in enumerate(c64_codec.DIRECT):
        char.set(field, n + 1, f"made up, value {n + 1}")
    # `race` chooses the infravision the writer computes; keep it in range.
    char.set("race", 1, "made up: elf")
    char.set("spells_known", [1, 5, 55], "made up")
    char.set("spells_memorised", [44, 21, 3], "made up")
    char.set("levels", {"fighter": 7, "thief": 3}, "made up")
    char.set("spells_castable", {"cleric": (3, 2, 1),
                                 "magic-user": (4, 3, 2)}, "made up")
    char.set("size_small", 1, "made up")
    char.set("turn_power", 6, "made up")
    char.set("attack_forms", bytes(range(1, 9)), "made up")
    char.set("innate_effects", [18, 47], "made up")
    char.set("inventory", [bytes(range(16))], "made up")
    char.set("roster_tail", bytes(range(9)), "made up")
    return char


def test_every_value_a_writer_takes_comes_back_out_of_the_record():
    """The round trip the neutral layer can have on its own: put a value in,
    write it, and read the same value back off the C64 record."""
    from goldbox import spells

    char = _filled()
    rec, rep = c64_codec.write(char)

    assert rec.name == "ROUNDTRIP"
    for field, c64 in c64_codec.DIRECT:
        assert rec.get(c64) == char.get(field), field
    assert spells.spells_known(rec.to_bytes()) == [1, 5, 55]
    assert [b for b in rec.get_raw("spells_memorised") if b] == [44, 21, 3]
    assert rec.get("level_fighter") == 7
    assert rec.get("level_thief") == 3
    assert rec.get_raw("spells_castable")[:3] == bytes((0x34, 0x23, 0x12))
    assert rec.get("size_small") == 1
    # Not 6, and not a round trip: the writer computes the turning byte from
    # the cleric and paladin levels rather than copying a source's (#288), and
    # this character is a fighter 7 / thief 3, who turns nothing.
    # `tests/test_turning.py` is where the value itself is checked.
    assert rec.get("turn_power") == 0
    assert rec.get_raw("attack_forms") == bytes(range(1, 9))
    assert [b for b in rec.get_raw("item_effects") if b] == [18, 47]
    assert rec.get_raw("inventory")[:16] == bytes(range(16))
    assert rec.get_raw("roster_tail") == bytes(range(9))
    # And every one of the 580 bytes has a provenance, as `docs/117` asks.
    assert rep.unaccounted == []


def test_a_field_the_target_cannot_represent_is_reported():
    """Never dropped silently: a class the C64 has no level slot for, and a
    field this writer takes nothing from.

    `encumbrance` is the example rather than `portrait_head`: since #57 the
    C64 writer copies a `portrait_head` it is given, so a field genuinely
    left untaken is one still in `c64_codec.DROPPED`.
    """
    char = _filled()
    char.set("levels", {"fighter": 7, "druid": 4}, "made up")
    char.set("encumbrance", 42, "made up")
    _, rep = c64_codec.write(char)
    assert any("druid" in w for w in rep.warnings)
    assert any(d.startswith("encumbrance:") for d in rep.dropped)


def test_a_spell_the_target_has_no_bit_for_is_reported():
    char = _filled()
    char.set("spells_known", [1, 56], "made up")
    _, rep = c64_codec.write(char)
    assert any("56" in w for w in rep.warnings)


def test_more_items_than_slots_is_reported():
    char = _filled()
    char.set("inventory", [bytes(16)] * 20, "made up")
    _, rep = c64_codec.write(char)
    assert any("sixteen slots" in w for w in rep.warnings)


def test_more_innate_effects_than_slots_is_reported():
    """#236 (A character converted to the C64 with more than ten innate
    effects loses the extra ones with no report): eleven ids, ten trait
    slots -- the eleventh must be named in the report, not just cut off."""
    char = _filled()
    char.set("innate_effects", list(range(1, 12)), "made up")
    _, rep = c64_codec.write(char)
    assert any("11" in w and "ten slots" in w for w in rep.warnings)


def _granted(effect_id: int) -> bytes:
    """One nine-byte `granted_effects` node, in the shared shape
    `goldbox/dos.py` reads: id, a zero duration, the value `0x0C` a passive
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


def test_more_granted_effects_than_free_slots_is_reported():
    """Nine innate ids leave one free slot; two item grants do not both
    fit, and the loss must be named rather than silently cut off."""
    char = _filled()
    char.set("innate_effects", list(range(1, 10)), "made up")
    char.set("granted_effects", [_granted(61), _granted(89)], "made up")
    _, rep = c64_codec.write(char)
    assert any("2 item-granted effects" in w and "1 free trait slots" in w
               for w in rep.warnings)


# --- the DOS reader, against real files --------------------------------------

@needs_dos_saves
def test_the_dos_reader_sets_nothing_the_c64_writer_leaves_behind():
    """The DOS->C64 path as reader + writer: everything the reader carries,
    the writer takes.  A field appearing here would be one to build the C64
    side out for, or one to say out loud in `DROPPED`."""
    for path in sorted(_save_dir().glob("*.SAV")):
        if path.stat().st_size != dos_layout.RECORD_SIZE:
            continue
        char = dos.to_neutral(dos.read_character(path))
        assert char.port == "DOS"
        _, rep = c64_codec.write(char)
        assert not [d for d in rep.dropped if "takes nothing from it" in d]


@needs_dos_saves
def test_the_reader_grades_every_value_it_carries():
    """A value with no grade cannot be refused, so every one carries the grade
    `goldbox/dos_layout.py` gives the field it was read from."""
    path = next(p for p in sorted(_save_dir().glob("*.SAV"))
                if p.stat().st_size == dos_layout.RECORD_SIZE)
    char = dos.to_neutral(dos.read_character(path))
    assert char.fields
    for name in char.keys():
        assert isinstance(char.value(name).confidence, Confidence)
        assert char.value(name).origin


# --- the neutral vocabulary's own disposition --------------------------------

def test_every_neutral_field_has_a_disposition_in_every_writer():
    """The gap the design review found: `goldbox.dos.field_disposition` checks the
    DOS layout and nothing checked the *neutral* vocabulary, so a name added
    to `FIELDS` and never wired up would rot in silence.

    Both writers now state what they do with each of the 64 names, and this is
    what fails when one of them forgets.
    """
    for writer in (c64_codec, amiga):
        unaccounted, unknown = neutral.undeclared(
            neutral.FIELDS, writer.field_disposition())
        assert unaccounted == set(), (writer.__name__, "no disposition")
        assert unknown == set(), (writer.__name__, "not in the vocabulary")


def test_a_name_dropped_from_a_writers_table_is_named_rather_than_lost():
    short = dict(c64_codec.field_disposition())
    del short["race"]
    assert neutral.undeclared(neutral.FIELDS, short) == ({"race"}, set())


# --- the shared take-refuse-report protocol ----------------------------------

def _writer(char, floor=Confidence.GUESS, dropped=()):
    rep = neutral.Report()
    return neutral.Writer(char, rep, into="test", floor=floor,
                          dropped=dropped), rep


def test_the_floor_applies_to_a_derivation_as_much_as_to_a_copy():
    """`NeutralCharacter.get` applies no floor, which is why `Writer.get`
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

    And `former_levels` is a field in the two titles whose `RecordShape` has
    `dual_class` -- Pool of Radiance never touches `0x0B9`/`0x0BA` (#224).
    `_filled` sets no former class, so this round trip stays at Curse and
    Silver Blades' own "empty" convention, `{}`, and Pool of Radiance's
    reader leaves the name off entirely rather than guess at a slot number
    the title's own GEN never wrote (#256, #234).
    """
    char = _filled(game=game)
    rec, _ = c64_codec.write(char)
    back = c64_codec.read(rec, game=game)
    taken = ({n for n, _ in c64_codec.DIRECT}
             | {n for n, _ in c64_codec.TRANSFORMED})
    if not c64_codec.record_shape(game).second_abilities:
        taken.discard("abilities_second")
    if not c64_codec.record_shape(game).identity_pair:
        taken.discard("unnamed_0ab")
    if not c64_codec.record_shape(game).dual_class:
        taken.discard("former_levels")
    taken.discard("granted_effects")
    assert taken - set(back.keys()) == set()


def test_record_shape_refuses_a_title_it_has_not_measured():
    """Champions of Krynn has a `Game` but no `RecordShape` row (#274): asking
    for its shape must not hand back Pool of Radiance's silently."""
    with pytest.raises(KeyError):
        c64_codec.record_shape(games.BY_KEY["champions-of-krynn"])
    with pytest.raises(KeyError):
        c64_codec.record_shape("champions-of-krynn")


def test_record_shape_still_defaults_pool_of_radiance_for_no_title_at_all():
    """None means a caller with no title in hand at all, not an unmeasured
    one, and every other test in this file calls `record_shape(None)`
    expecting Pool of Radiance back."""
    assert c64_codec.record_shape(None) is c64_codec.POOL_OF_RADIANCE_RECORD
    assert c64_codec.record_shape() is c64_codec.POOL_OF_RADIANCE_RECORD


def test_the_c64_reader_grades_every_value_from_the_layout():
    back = c64_codec.read(c64_codec.write(_filled())[0])
    for name in back.keys():
        assert isinstance(back.value(name).confidence, Confidence)
        assert back.value(name).origin
