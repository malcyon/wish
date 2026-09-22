from __future__ import annotations

"""Reading an Amiga Pools of Darkness `.pc`, and the DOS route (#194).

`goldbox.amiga_pod.PodWriter` has turned a neutral character into a `Save/NAME.pc`
since `#7`, and **nothing turned one back**: `PodCharacter` had no caller
anywhere in `goldbox/`, `editor/` or `tools/`, so the Amiga end of
`#194 (Import and export a Pools of Darkness save between DOS and the Amiga)`
had one direction of two. `goldbox.amiga_pod.pod_to_neutral` is the other, and
this is its proof.

What is tested, hardest evidence first.

* **The two ports' tables are the same tables.** Race, class code, class-level
  slots and alignment all index identically on the Amiga `.pc` and the DOS
  510-byte record, so a same-title conversion copies rather than looks up.
  That is the claim everything else rests on and it is checked against both
  ports' own files.
* **The round trips**, each with its own count: a `.pc` read and written back,
  and a DOS record converted into a `.pc`.
* **The count of what the reader fills**, stated as a number rather than a
  shrug, and pinned here so that it moves when somebody decodes another region
  rather than drifting.

**The specimens are the `Save/*.pc` files on the player's own Amiga disk
images** -- twelve in the `Save` drawer of Pools of Darkness disk 3 and seven
more on alternate rips -- read at run time through `gamedisks.yaml`'s `amiga`
entry -- the same route
`tests/amiga/test_amiga.py` uses for the Amiga Pool of Radiance records, and for the
same reason: they are not loose files on any machine. Everything here skips
without the disks, which is what CI does.
"""

import pathlib

import pytest
from support.podamiga import pc_bytes

from goldbox import amiga_pod, dos_codec, dos_port, neutral

POD = dos_port.POOLS_OF_DARKNESS

#: The names the reader fills and the two the writer drops but it does not.
READ_ONLY = ("armour_class", "armour_class_base")


def pc_records() -> list[tuple[str, bytes]]:
    """:func:`pc_bytes`, sorted, skipping when there are none."""
    found = pc_bytes()
    if not found:
        pytest.skip("no Amiga Pools of Darkness .pc files; set $AMIGA_DISKS")
    return sorted(found.items())


def dos_records() -> list[pathlib.Path]:
    """The shipped DOS Pools of Darkness records, by directory and size."""
    from support.dossave import _game_dirs

    where = _game_dirs().get("Pools of Darkness")
    if where is None:
        pytest.skip("needs the Pools of Darkness archive; set FR_ARCHIVES")
    found = [p for p in sorted(where.rglob("*.SAV"))
             if p.stat().st_size == POD.record_size]
    if not found:
        pytest.skip("no Pools of Darkness records in the archive")
    return found


# --- the two ports index the same tables -------------------------------------

def test_the_race_numbering_is_the_same_on_both_ports():
    """`goldbox.amiga_pod.RACES` and `goldbox.dos_port
    .POOLS_OF_DARKNESS_RACE_NUMBERS` are the same six names in the same
    order, with `monster` after them on the DOS side only.

    This is what makes `race` a copy rather than a lookup, and it is also
    what `goldbox/c64_port.py`'s Pools of Darkness entry would have to say --
    it has none, and its default is Pool of Radiance's numbering, under which
    race 5 is a halfling rather than the human it is here.
    """
    ours = tuple(name.lower() for name in amiga_pod.RACES)
    theirs = tuple(POD.race_numbers)
    assert ours == theirs[:len(ours)]
    assert theirs[len(ours):] == ("monster",)
    assert theirs[5] == "human"


def test_the_class_codes_and_level_slots_are_the_same_on_both_ports():
    """A class code read off a DOS record names the same class in
    `goldbox.amiga_pod.CLASSES`, and the seven level slots are in one order.

    Checked against both ports' own files rather than by reading the two
    tuples side by side: every DOS record's class code, looked up in the
    Amiga table, has to agree with the classes its own level array holds.
    """
    assert tuple(n.lower() for n in amiga_pod.CLASS_LEVEL_SLOTS) == \
        tuple(name for _n, name, _f in dos_codec.CLASS_LEVEL_SLOTS[:7])
    seen = 0
    for path in dos_records():
        char = dos_codec.read_character(path)
        code = char.get("char_class")
        assert 0 <= code < len(amiga_pod.CLASSES), (path.name, code)
        held = {name for n, name, _f in dos_codec.CLASS_LEVEL_SLOTS
                if n < len(char.raw("class_levels"))
                and char.raw("class_levels")[n]}
        named = {p.strip().lower() for p in
                 amiga_pod.CLASSES[code].replace("M-U", "MAGIC-USER").split("/")}
        # A dual-classed character's code names what he *is*, so his old
        # class is in neither set: compare what he currently holds.
        assert held <= named or named <= held, (path.name, held, named)
        seen += 1
    assert seen >= 12


def test_a_paladin_is_lawful_good_on_both_ports():
    """The alignment byte is `law * 3 + morality` on both, so 0 is lawful
    good -- and every paladin in either port's own files reads 0, which is
    the one alignment AD&D allows one."""
    paladins = 0
    for path in dos_records():
        char = dos_codec.read_character(path)
        if amiga_pod.CLASSES[char.get("char_class")] == "PALADIN":
            assert char.get("alignment") == 0, path.name
            paladins += 1
    for name, raw in pc_records():
        c = amiga_pod.PodCharacter.from_bytes(raw)
        if c.class_name == "PALADIN":
            assert c.alignment == 0, name
            paladins += 1
    assert paladins >= 4


# --- the reader --------------------------------------------------------------

def test_every_neutral_field_has_a_reader_disposition():
    """A field `goldbox/neutral.py` declares and `pod_field_disposition`
    names nowhere would be one dropped in silence."""
    assert neutral.undeclared(neutral.FIELDS,
                              amiga_pod.pod_field_disposition()) == (set(), set())


@pytest.mark.parametrize("share", (0, 255))
def test_the_pod_treasure_share_is_a_raw_byte_in_both_directions(share):
    """The SSB importer gives PoD an exact byte, including explicit zero."""
    raw = bytearray(amiga_pod.RECORD_LENGTH)
    raw[amiga_pod.FIELD_83_87_SECOND] = share
    character = amiga_pod.PodCharacter.from_bytes(raw)
    assert character.treasure_share == share
    assert amiga_pod.pod_to_neutral(character).get("treasure_share") == share

    writer = amiga_pod.PodWriter(name="TEST", treasure_share=share)
    written = writer.to_bytes()
    assert written[amiga_pod.FIELD_83_87_SECOND] == share
    assert writer.provenance()[amiga_pod.FIELD_83_87_SECOND] == "treasure_share"


@pytest.mark.parametrize("share", (0, 255))
def test_the_pod_conversion_keeps_an_explicit_treasure_share(share):
    """A `.pc` read reaches both composed Amiga writing routes unchanged."""
    raw = bytearray(amiga_pod.PodWriter(
        name="TEST",
        character_class=amiga_pod.CLASSES.index("FIGHTER"),
        class_levels=(0, 0, 1, 0, 0, 0, 0),
        class_bits=amiga_pod.CLASS_BIT["fighter"],
    ).to_bytes())
    raw[amiga_pod.FIELD_83_87_SECOND] = share
    character = amiga_pod.pod_to_neutral(bytes(raw))

    writer, _write_report = amiga_pod.write_pod(character)
    assert writer.to_bytes()[amiga_pod.FIELD_83_87_SECOND] == share
    assert writer.provenance()[amiga_pod.FIELD_83_87_SECOND] == "treasure_share"

    written, report = amiga_pod.to_pc(character)
    assert written[amiga_pod.FIELD_83_87_SECOND] == share
    assert report.unaccounted(written) == []
    assert report.sources[amiga_pod.FIELD_83_87_SECOND].startswith(
        "treasure_share <- Amiga")


def test_write_pod_reports_the_derived_and_constant_fields_as_derived():
    """`write_pod` itself, not just `pod_write_field_disposition`, routes
    :data:`amiga_pod.POD_WRITE_DERIVED` and :data:`amiga_pod.POD_WRITE_CONSTANTS`
    to `report.derived` rather than `report.dropped`."""
    raw = bytearray(amiga_pod.PodWriter(
        name="TEST",
        character_class=amiga_pod.CLASSES.index("FIGHTER"),
        class_levels=(0, 0, 1, 0, 0, 0, 0),
        class_bits=amiga_pod.CLASS_BIT["fighter"],
    ).to_bytes())
    character = amiga_pod.pod_to_neutral(bytes(raw))

    _writer, report = amiga_pod.write_pod(character)

    names = {"armour_class_base", "armour_class", "encumbrance",
             "thac0_current", "movement_current", "combat_figure",
             "roster_tail"}
    derived_names = {line.split(":", 1)[0] for line in report.derived}
    dropped_names = {line.split(":", 1)[0] for line in report.dropped}
    assert names <= derived_names
    assert names.isdisjoint(dropped_names)


def test_the_reader_drops_a_strict_subset_of_what_the_writer_drops():
    """The two lists say different things, and this is the one crossing
    between them that is allowed.

    **Reading a byte and writing one are not the same undertaking**: the
    reader can take a field the writer must not fill in until somebody has
    watched the loader accept it. The reverse -- a name the reader drops and
    the writer converts -- would usually be a field this module claims to
    convert in a direction it cannot even read.

    `innate_effects` is the one exception, and it is a classification rather
    than a byte. The reader cannot tell an innate node from a readied item's
    grant in this title, so it puts every node that never expires into
    `granted_effects`; a DOS or C64 source *has* made that split, and the
    writer puts both lists into the one chain the record holds. 1 of 1, named
    here so a second one cannot appear without this going red.
    """
    writer = {n for n, _ in amiga_pod.POD_WRITE_DROPPED}
    reader = {n for n, _ in amiga_pod.pod_read_dropped()}
    assert reader - writer == {"innate_effects"}
    assert writer - reader
    assert amiga_pod.pod_write_field_disposition()["innate_effects"].startswith(
        "an id each")
    for name in READ_ONLY:
        assert amiga_pod.pod_field_disposition()[name].startswith("copied")


def test_every_genuine_record_reads_to_a_coherent_character():
    """The cross-checks that would fail on a wrong offset rather than
    restating one field: the level is the highest of the class levels, the
    class code decomposes to the classes the level array holds, every
    ability is a legal score, and the alignment is one the game has a word
    for.
    """
    seen = 0
    for name, raw in pc_records():
        out = amiga_pod.pod_to_neutral(raw)
        assert out.get("name"), name
        assert str(out.get("name")).isprintable(), name
        levels = {k: v for k, v in out.get("levels").items() if v}
        assert levels, name
        assert out.get("level") == max(levels.values()), name
        for ability in neutral.ABILITIES:
            if ability == "exceptional_strength":
                continue
            assert 3 <= out.get(ability) <= 25, (name, ability)
        assert 0 <= out.get("alignment") < len(amiga_pod.ALIGNMENTS), name
        assert out.get("sex") in (0, 1), name
        assert 0 <= out.get("race") < len(amiga_pod.RACES), name
        seen += 1
    assert seen >= 12


def test_the_ranger_gets_the_neutral_bit_and_the_paladin_keeps_dos_bit_six():
    """The `.pc` stores DOS's own mask, where the paladin and the ranger
    share bit 6, and the neutral record gives the ranger bit 7. A reader that
    copied the byte would send every Amiga ranger on as a paladin -- which is
    `#292`'s bug on the later titles and the fault `#193` found and fixed for
    Silver Blades on the C64.
    """
    rangers = paladins = 0
    for name, raw in pc_records():
        c = amiga_pod.PodCharacter.from_bytes(raw)
        out = amiga_pod.pod_to_neutral(raw)
        if c.class_name == "RANGER":
            assert c.class_bits == 0x40, name
            assert out.get("class_bits") & 0x80, name
            assert not out.get("class_bits") & 0x40, name
            rangers += 1
        elif c.class_name == "PALADIN":
            assert c.class_bits == 0x40, name
            assert out.get("class_bits") & 0x40, name
            paladins += 1
    assert rangers >= 2 and paladins >= 2


# --- the round trips ---------------------------------------------------------

def test_a_record_written_back_keeps_every_field_the_reader_read():
    """`.pc` -> `pod_to_neutral` -> `to_pc`, over the decoded fields.

    **18 of 19 identical at every decoded offset, and the nineteenth differs
    only in the name bytes past its NUL terminator**: `?T.pc` stores
    `3F 54 00 3F 3F ...`, so the engine left rubbish after the terminator and
    the writer NUL-pads. That is the same thing the DOS round trip masks for
    `name_text` past the count byte, and it is not a loss.

    The whole record is **not** compared, and the spans below are the honest
    boundary. What is deliberately outside them, and why: the heap pointers at
    `0x000`-`0x03F`, which the loader overwrites; the derived block the game
    recomputes (`DERIVED`); the combat icon at `0x0BB`-`0x0BD` and
    `0x0BF`-`0x0C4`, which the writer fills from the engine's own creation
    defaults rather than from the source, because no neutral field holds a
    player's choice on the ICON screen and 13 of these 19 characters differ from
    the engine's default in at least one of head, body and colours;
    the memorised list at `0x0CC`, which is zero in 19 of 19 files and so has
    nothing to compare; and the rest of the bytes no neutral field names --
    the stale item count at `0x0C7` and `hands_used` at `0x0C8`, which the
    game rebuilds with `encumbrance`, and `gap_19a` at `0x0C9`, which is 2 in
    5 of the 19.

    **`paladin_cures` at `0x080` is inside the spans**: JORILD and TURBO K
    hold 1 and come back holding 1, where the writer used to leave it 0.
    `Report.unaccounted` is the writer's own guarantee and is asserted empty
    here.
    """
    spans = {
        "experience": (amiga_pod.EXPERIENCE, 4),
        "platinum": (amiga_pod.PLATINUM, 2),
        "gems": (amiga_pod.GEMS, 2),
        "jewelry": (amiga_pod.JEWELRY, 2),
        "age": (amiga_pod.AGE, 2),
        "race": (amiga_pod.RACE, 1),
        "char_class": (amiga_pod.CLASS, 1),
        "sex": (amiga_pod.SEX, 1),
        "alignment": (amiga_pod.ALIGNMENT, 1),
        "abilities": (amiga_pod.ABILITIES, 2 * amiga_pod.ABILITY_COUNT),
        "exceptional_strength": (amiga_pod.EXCEPTIONAL_STRENGTH, 2),
        "hp_max": (amiga_pod.HP_MAX, 1),
        "movement": (amiga_pod.MOVEMENT, 1),
        "class_levels": (amiga_pod.CLASS_LEVELS, amiga_pod.CLASS_LEVEL_COUNT),
        "treasure_share": (amiga_pod.FIELD_83_87_SECOND, 1),
        # `0x0B3` is `armour_class_base`, which the writer emits as the
        # unarmoured constant every record on either port holds; the neutral
        # `armour_class` is the byte at `0x187`, which the game recomputes on
        # load and this writer leaves alone, so it has no span here.
        "armour_class_base": (amiga_pod.ARMOUR_CLASS, 1),
        "hp_current": (amiga_pod.HP_CURRENT, 1),
        "saving_throws": (amiga_pod.SAVING_THROWS, amiga_pod.SAVING_THROW_COUNT),
        "level": (amiga_pod.LEVEL, 1),
        "thief_skills": (amiga_pod.THIEF_SKILLS, amiga_pod.THIEF_SKILL_COUNT),
        "class_bits": (amiga_pod.CLASS_BITS, 1),
        "name": (amiga_pod.NAME, amiga_pod.NAME_LENGTH),
        # The four combat bytes, the scalars, the spellbook and the spell
        # slots.
        "status": (amiga_pod.STATUS, 1),
        "hostile": (amiga_pod.HOSTILE, 1),
        "active": (amiga_pod.ACTIVE, 1),
        "quickfight": (amiga_pod.QUICKFIGHT, 1),
        "thac0_base": (amiga_pod.THAC0_BASE, 1),
        "paladin_cures": (amiga_pod.PALADIN_CURES, 1),
        "hp_rolled": (amiga_pod.HP_ROLLED, 1),
        "unnamed_0ab": (amiga_pod.UNNAMED_0AB, 1),
        "experience_award": (amiga_pod.EXPERIENCE_AWARD, 2),
        "size": (amiga_pod.SIZE, 1),
        # No neutral field names it, and the writer emits the 1 the engine's
        # creation routine writes; 19 of 19 hold it, so it is inside.
        "icon_dimension": (amiga_pod.ICON_DIMENSION, 1),
        # Likewise `02 02`, which creation writes and the importer forces.
        "unnamed_1a4": (amiga_pod.UNNAMED_1A4, 2),
        "npc_control_byte": (amiga_pod.NPC_CONTROL, 1),
        "former_level": (amiga_pod.FORMER_LEVEL, 1),
        "former_class_levels": (amiga_pod.FORMER_CLASS_LEVELS,
                                amiga_pod.CLASS_LEVEL_COUNT),
        "attack_forms": (amiga_pod.ATTACK_FORMS, amiga_pod.ATTACK_FORM_COUNT),
        "spells_known": (amiga_pod.SPELLBOOK, amiga_pod.SPELLBOOK_BYTES),
        "spells_castable": (amiga_pod.SPELLS_CASTABLE,
                            amiga_pod.SPELL_SLOT_LEVELS
                            * len(amiga_pod.SPELL_SLOT_CLASSES)),
    }
    seen = clean = 0
    exceptions: list[str] = []
    for name, raw in pc_records():
        out, report = amiga_pod.to_pc(amiga_pod.pod_to_neutral(raw))
        assert report.unaccounted(out) == [], name
        differs = sorted(field for field, (at, size) in spans.items()
                         if out[at:at + size] != raw[at:at + size])
        seen += 1
        if not differs:
            clean += 1
            continue
        assert differs == ["name"], (name, differs)
        # The name matches up to and including its terminator; what follows
        # is the engine's leftover.
        stem = raw[amiga_pod.NAME:amiga_pod.NAME + amiga_pod.NAME_LENGTH].split(b"\0")[0]
        assert out[amiga_pod.NAME:amiga_pod.NAME + len(stem)] == stem, name
        exceptions.append(name)
    assert seen >= 12
    assert clean == seen - len(exceptions)
    assert exceptions == ["T.pc"], exceptions


def test_every_dos_record_converts_into_a_pc():
    """DOS -> `dos_codec.to_neutral` -> `amiga_pod.to_pc`, 12 of 12.

    The route this ticket asked for, in the direction that has both ends: the
    DOS reader learned this title today and the Amiga writer has always had
    it. Each output is read back with `PodCharacter` and checked against the
    DOS record it came from, which is stronger than checking it is 484 bytes.
    """
    seen = 0
    for path in dos_records():
        char = dos_codec.read_character(path)
        out = dos_codec.to_neutral(char)
        pc, report = amiga_pod.to_pc(out)
        # 404 of record, twenty a carried item, ten a running effect -- and
        # never shorter than the 484 the game's own shortest file is.
        back = amiga_pod.PodCharacter.from_bytes(pc)
        assert len(pc) == max(
            amiga_pod.RECORD_LENGTH,
            amiga_pod.RECORD_BYTES
            + amiga_pod.ITEM_FILE_SIZE * len(back.items)
            + amiga_pod.EFFECT_FILE_SIZE * len(back.effects)), path.name
        assert len(back.items) == len(out.get("inventory")), path.name
        assert report.unaccounted(pc) == [], path.name
        # The writer cuts trailing blanks, which DOS counts into its own
        # length byte: Guy de Valois is stored `Guy de Valois ` there.
        assert back.name == char.name[:amiga_pod.NAME_LENGTH].rstrip(), path.name
        assert back.race == char.get("race"), path.name
        assert back.sex == char.get("sex"), path.name
        assert back.alignment == char.get("alignment"), path.name
        assert back.age == char.get("age"), path.name
        assert back.experience == char.get("experience"), path.name
        assert back.platinum == char.get("platinum"), path.name
        assert back.level == char.get("level"), path.name
        assert back.hit_points_max == char.get("hp_max"), path.name
        # `char.get` hands back the DOS pair raw, so the neutral record's
        # own value -- the score in force -- is what to compare against.
        assert list(back.abilities) == [
            out.get(a) for a in neutral.ABILITIES[:6]], path.name
        seen += 1
    assert seen >= 12


def test_a_dos_paladins_cure_byte_lands_in_the_pc():
    """DOS Pools of Darkness `paladin_cures` -> the `.pc`'s byte at 0x080.

    Read off the shipped archive's records: **which of them read 1 is
    whatever the archive holds, and the test asks that at least one does**, so
    a converter that wrote 0 for all of them cannot pass."""
    ones = seen = 0
    for path in dos_records():
        char = dos_codec.read_character(path)
        pc, _report = amiga_pod.to_pc(dos_codec.to_neutral(char))
        assert pc[amiga_pod.PALADIN_CURES] == char.get("paladin_cures"), path.name
        ones += char.get("paladin_cures") == 1
        seen += 1
    assert seen >= 12
    assert ones >= 1


def test_a_paladins_cure_byte_survives_dos_to_amiga_and_back():
    """A made-up DOS Pools of Darkness paladin holding 1 comes out of
    DOS -> neutral -> `.pc` -> neutral -> DOS holding 1, at every step.

    Built from `goldbox/dos_port.py`'s own table, so it runs with no disks
    and carries no game bytes."""
    f = dos_port.FIELDS_BY_NAME_FOR[POD.key]
    for held in (1, 0):
        raw = bytearray(POD.record_size)
        raw[0] = 5
        raw[1:6] = b"JORIL"
        raw[f["race"].offset] = 5
        raw[f["class_levels"].offset + 5] = 12
        raw[f["class_bits"].offset] = 0x40
        raw[f["paladin_cures"].offset] = held
        neutral_char = dos_codec.to_neutral(dos_codec.DosCharacter(bytes(raw)))
        assert neutral_char.get("paladin_cures") == held
        pc, _ = amiga_pod.to_pc(neutral_char)
        assert pc[amiga_pod.PALADIN_CURES] == held
        back = amiga_pod.pod_to_neutral(pc)
        assert back.get("paladin_cures") == held
        rec, _itm, _spc, _rep = dos_codec.write(back)
        assert rec[f["paladin_cures"].offset] == held


def test_a_dual_classed_character_arrives_as_the_class_he_is():
    """**ABAGAIL is a magic-user 12 who was a cleric 11 and PAINE a
    magic-user 13 who was a ranger 9**, and the class code has to name what
    each of them is while the old class keeps its level.

    The neutral class mask holds a dual-classed character's old class as well
    as his current one, because the C64 needs it. Copied straight into the
    Amiga's single class code it makes ABAGAIL a `CLERIC/MAGIC-USER`, a class
    she is not, and PAINE nothing at all -- Pools of Darkness has no
    magic-user/ranger code, and no character can be both at once.

    So the code at `0x059` names the class he is, and the class he trained out
    of goes where this engine's own dual-class routine puts it: its level into
    the array at `0x0A4` and the level he left at into `0x08A`.
    """
    seen = 0
    for path in dos_records():
        char = dos_codec.read_character(path)
        out = dos_codec.to_neutral(char)
        former = {k: v for k, v in (out.get("former_levels") or {}).items()
                  if v}
        pc, _report = amiga_pod.to_pc(out)
        back = amiga_pod.PodCharacter.from_bytes(pc)
        held = {k for k, v in out.get("levels").items() if v}
        named = {p.strip().lower() for p in
                 amiga_pod.CLASSES[back.character_class]
                 .replace("M-U", "MAGIC-USER").split("/")}
        assert named == held, (path.name, named, held)
        was = {name.lower(): level for name, level
               in zip(amiga_pod.CLASS_LEVEL_SLOTS, back.former_class_levels)
               if level}
        assert was == former, (path.name, was, former)
        assert back.former_level == (max(former.values()) if former else 0), \
            path.name
        seen += bool(former)
    assert seen == 2, f"{seen} dual-classed characters, expected ABAGAIL and PAINE"


def test_a_converted_character_arrives_in_the_party():
    """The byte at `0x184` is what the other two ports draw a name red for,
    and every `.pc` the game itself wrote holds 1 there -- 19 of 19.

    A writer leaving it zero hands the player a party member the game may be
    showing as out of it, which is the defect `#475` is named for. Checked on
    both routes into the writer: a DOS record of this title, and a record
    built from nothing but a name.
    """
    assert amiga_pod.PodWriter(name="TEST").to_bytes()[amiga_pod.ACTIVE] == 1
    seen = 0
    for name, raw in pc_records():
        assert raw[amiga_pod.ACTIVE] == 1, name
        out, _rep = amiga_pod.to_pc(amiga_pod.pod_to_neutral(raw))
        assert out[amiga_pod.ACTIVE] == 1, name
        seen += 1
    for path in dos_records():
        out, _rep = amiga_pod.to_pc(
            dos_codec.to_neutral(dos_codec.read_character(path)))
        assert out[amiga_pod.ACTIVE] == 1, path.name
        assert amiga_pod.PodCharacter.from_bytes(out).active, path.name
        seen += 1
    assert seen >= 24, seen


def test_a_character_the_game_has_taken_out_of_the_party_stays_out():
    """The other polarity, which a default of 1 would paper over: a source
    that says the character is out of the party writes zero."""
    raw = bytearray(amiga_pod.PodWriter(
        name="GONE", character_class=amiga_pod.CLASSES.index("FIGHTER"),
        class_levels=(0, 0, 3, 0, 0, 0, 0),
        class_bits=amiga_pod.CLASS_BIT["fighter"]).to_bytes())
    raw[amiga_pod.ACTIVE] = 0
    raw[amiga_pod.STATUS] = neutral.STATUS_NAMES.index("unconscious")
    char = amiga_pod.pod_to_neutral(bytes(raw))
    assert char.get("active") is False
    assert char.get("status") == "unconscious"

    out, _rep = amiga_pod.to_pc(char)
    assert out[amiga_pod.ACTIVE] == 0
    assert out[amiga_pod.STATUS] == neutral.STATUS_NAMES.index("unconscious")


# --- what the writer takes from a synthetic character ------------------------
#
# Each test below builds its neutral character from a record `PodWriter`
# makes from a name, so it needs no disk, and changes exactly one field. The
# specimens cannot pin these: all 19 genuine records hold the same value in
# both halves of the exceptional-strength pair, have `hostile` 0, have an
# experience award of zero and carry no effect id twice.

def a_neutral_fighter() -> neutral.NeutralCharacter:
    raw = amiga_pod.PodWriter(
        name="SYNTH", character_class=amiga_pod.CLASSES.index("FIGHTER"),
        class_levels=(0, 0, 3, 0, 0, 0, 0),
        class_bits=amiga_pod.CLASS_BIT["fighter"]).to_bytes()
    return amiga_pod.pod_to_neutral(raw)


def test_a_source_that_does_not_say_whether_he_is_in_the_party_writes_one():
    """`active` defaults to true when the neutral record has no such field,
    which is every C64 source: a character being converted is in the party,
    and a zero here is the flag that may draw his name as out of it."""
    char = a_neutral_fighter()
    del char.fields["active"]
    out, _rep = amiga_pod.to_pc(char)
    assert out[amiga_pod.ACTIVE] == 1


def test_a_hostile_character_is_written_hostile():
    char = a_neutral_fighter()
    char.set("hostile", True, "test")
    out, _rep = amiga_pod.to_pc(char)
    assert out[amiga_pod.HOSTILE] == 1
    assert amiga_pod.PodCharacter.from_bytes(out).hostile


def test_the_experience_award_is_written_as_a_big_endian_word():
    char = a_neutral_fighter()
    char.set("experience_award", 300, "test")
    out, _rep = amiga_pod.to_pc(char)
    assert out[amiga_pod.EXPERIENCE_AWARD:amiga_pod.EXPERIENCE_AWARD + 2] == (
        (300).to_bytes(2, "big"))


def test_exceptional_strength_keeps_its_two_halves_in_their_own_bytes():
    """The in-force percentile is byte 0 of the pair at `0x07C` and the
    permanent one is byte 1, the other way round from the six ability pairs.
    That assignment is inferred from the later titles, not read off an Amiga
    specimen.

    Written and read with the two values different, because they are equal
    in all 19 genuine records: a reader and a writer that disagreed about
    which byte is which changed the record at `0x07C` on a round trip and
    nothing on any disk showed it.
    """
    char = a_neutral_fighter()
    char.set("exceptional_strength", 0x32, "test")
    char.set("abilities_second", {"exceptional_strength": 0x64}, "test")
    out, _rep = amiga_pod.to_pc(char)
    at = amiga_pod.EXCEPTIONAL_STRENGTH
    assert out[at] == 0x32
    assert out[at + 1] == 0x64

    back = amiga_pod.PodCharacter.from_bytes(out)
    assert back.exceptional_strength == 0x32
    assert back.exceptional_strength_permanent == 0x64
    read = amiga_pod.pod_to_neutral(out)
    assert read.get("exceptional_strength") == 0x32
    assert read.get("abilities_second")["exceptional_strength"] == 0x64
    again, _rep = amiga_pod.to_pc(read)
    assert again[at:at + 2] == out[at:at + 2]


def test_an_effect_listed_as_granted_and_as_innate_is_written_once():
    """The chain holds one node per id: a granted effect also named among the
    innate ones is not written twice, and the skip is on the report."""
    char = a_neutral_fighter()
    granted = bytes((5, 0, 0, 0xFF, 0, 0, 0, 0, 0))
    char.set("granted_effects", [granted], "test")
    char.set("innate_effects", [5], "test")
    out, rep = amiga_pod.to_pc(char)
    back = amiga_pod.PodCharacter.from_bytes(out)
    assert [node[0] for node in back.effects] == [5]
    assert [line for line in rep.dropped if "already in the chain" in line]


def test_a_memorised_spell_lands_at_the_front_of_the_region():
    """The end the engine's own MEMORIZE screen fills from (#475).

    `0x000A5C` counts up from index 0 for the first zero byte and writes the
    id there, and the tidy pass at `0x000864` sorts what is in the region
    ascending by `id & 0x7f` towards index 0. So a converted list belongs
    against `0x0CC` and not against `0x158`, and writing it the other way
    round would leave the whole of it past every entry the engine reads.
    """
    char = a_neutral_fighter()
    # Highest first, which is the order the neutral record keeps.
    char.set("spells_memorised", [34, 21, 3], "test")
    out, rep = amiga_pod.to_pc(char)
    at = amiga_pod.SPELLS_MEMORISED
    assert out[at:at + 4] == bytes((3, 21, 34, 0))
    assert out[at + amiga_pod.SPELLS_MEMORISED_LENGTH - 1] == 0
    assert not [line for line in rep.dropped if "memorised" in line]
    assert amiga_pod.pod_to_neutral(out).get("spells_memorised") == [34, 21, 3]


def test_a_spell_still_being_memorised_keeps_its_pending_bit():
    """Both ports store `id + 0x80` until a night's rest takes it off, and
    the Amiga sorts by the id with that bit masked away (`andi.b #$7f` at
    every reader, `0x000890` in the tidy pass), so a pending level-1 spell
    stays in front of a ready level-9 one."""
    char = a_neutral_fighter()
    pending = 3 | amiga_pod.SPELLS_MEMORISED_PENDING
    char.set("spells_memorised", [34, pending], "test")
    out, _rep = amiga_pod.to_pc(char)
    at = amiga_pod.SPELLS_MEMORISED
    assert out[at:at + 2] == bytes((pending, 34))


def test_a_memorised_id_that_is_not_a_byte_is_reported_and_not_fatal():
    """The region's byte is an id in 1-255 with bit 7 as the pending flag. 300
    and 256 do not fit a byte, -1 is not an id, 0 is an empty slot and 128 is
    the pending flag on an empty slot -- each is reported and the rest of the
    list is written, where one of them used to abort the whole conversion with
    `bytes must be in range(0, 256)`."""
    pending = 5 | amiga_pod.SPELLS_MEMORISED_PENDING
    char = a_neutral_fighter()
    char.set("spells_memorised", [300, 256, 128, 34, pending, 3, 0, -1], "test")
    out, rep = amiga_pod.to_pc(char)
    at = amiga_pod.SPELLS_MEMORISED
    assert out[at:at + 4] == bytes((3, pending, 34, 0))
    assert [line for line in rep.dropped
            if line.startswith("5 memorised spell ids")
            and line.endswith("300, 256, 128, 0, -1")]


def test_the_writer_refuses_a_memorised_id_that_is_not_a_byte():
    for bad in (300, 256, 128, 0, -1):
        with pytest.raises(ValueError):
            amiga_pod.PodWriter(
                name="SPELL", spells_memorised=(bad,)).to_bytes()


def test_more_memorised_spells_than_the_region_holds_are_reported():
    char = a_neutral_fighter()
    char.set("spells_memorised", [7] * 200, "test")
    out, rep = amiga_pod.to_pc(char)
    at = amiga_pod.SPELLS_MEMORISED
    length = amiga_pod.SPELLS_MEMORISED_LENGTH
    assert out[at:at + length] == bytes([7] * length)
    assert out[at + length] == 0            # the spellbook mask, untouched
    assert [line for line in rep.dropped if "59 memorised spells past" in line]


def test_the_combat_icon_is_the_one_the_engine_would_have_created():
    """A converted character arrives with the picture creation would have
    given him.

    The routine at `0x00C736` is what character creation calls at `0x00FD92`:
    a halfling has his own head, the other races split by sex and size, and
    the body is the first class slot with a level in it.
    """
    char = a_neutral_fighter()
    out, _rep = amiga_pod.to_pc(char)
    assert out[amiga_pod.ICON_HEAD] == 5          # male, medium
    assert out[amiga_pod.ICON_BODY] == 0x18       # a fighter
    assert out[amiga_pod.ICON_COLOURS:
               amiga_pod.ICON_COLOURS + amiga_pod.ICON_COLOUR_COUNT] == (
        amiga_pod.ICON_COLOURS_DEFAULT)
    assert out[amiga_pod.ICON_DIMENSION] == amiga_pod.ICON_DIMENSION_DEFAULT
    assert amiga_pod.ICON_COLOURS_DEFAULT.hex() == "91a2b3c4e6f7"


@pytest.mark.parametrize("race,sex,size,levels,head,body", (
    ("HUMAN", "MALE", 2, {"cleric": 14}, 5, 0x17),
    ("HUMAN", "FEMALE", 2, {"paladin": 12}, 9, 0x18),
    ("DWARF", "MALE", 1, {"fighter": 9, "thief": 13}, 0, 0x18),
    ("HALFLING", "FEMALE", 2, {"thief": 16}, 3, 5),
    ("ELF", "FEMALE", 1, {"magic-user": 14}, 7, 0x1D),
    ("ELF", "MALE", 2, {"ranger": 13}, 5, 1),
))
def test_the_engines_own_icon_rule_by_race_sex_size_and_class(
        race, sex, size, levels, head, body):
    """Every branch of `0x00C736` and of the body chain at `0x00C79E`."""
    slots = [0] * amiga_pod.CLASS_LEVEL_COUNT
    for name, level in levels.items():
        slots[amiga_pod.CLASS_LEVEL_SLOTS.index(name.upper())] = level
    assert amiga_pod.engine_default_icon(
        amiga_pod.RACES.index(race), amiga_pod.SEXES.index(sex), size,
        slots) == (head, body)


def test_the_writer_refuses_an_icon_past_the_screens_own_wrap():
    """13 and 31 are where the ICON screen wraps each byte back to zero, so
    they are the last art `CHEAD.TLB` and `CBODY.TLB` have; a value past
    either makes the loader refuse the whole file."""
    for kwargs in ({"icon_head": 14}, {"icon_body": 32},
                   {"icon_head": -1}, {"icon_body": -1}):
        with pytest.raises(ValueError):
            amiga_pod.PodWriter(name="ICON", **kwargs).to_bytes()
    assert amiga_pod.PodWriter(
        name="ICON", icon_head=13, icon_body=31).to_bytes()[
            amiga_pod.ICON_HEAD] == 13


def test_the_roster_byte_is_what_creation_writes_and_not_a_marching_slot():
    """`0x0BD` is assigned when the character joins: the join routine at
    `0x027398` stores 0xFF over it and then counts it up to the first free
    slot of eight. So the writer emits creation's own 13, which is what 17
    of the 19 `.pc` files hold."""
    char = a_neutral_fighter()
    char.set("combat_figure", 2, "the source's own marching slot")
    out, rep = amiga_pod.to_pc(char)
    assert out[amiga_pod.COMBAT_FIGURE] == amiga_pod.NO_PARTY_SLOT == 13
    # A field the engine rebuilds on load is a derived field, not a drop
    # (Fix 1): `write_pod`'s `neutral.Writer` now routes it that way.
    assert [line for line in rep.derived
            if "combat_figure" in line and "0x027398" in line]


def test_every_specimens_icon_is_inside_the_screens_own_range():
    """The wrap points read off the ICON screen, checked against the files:
    no record on the disks holds a head past 13 or a body past 31."""
    records = pc_records()
    heads = [raw[amiga_pod.ICON_HEAD] for _name, raw in records]
    bodies = [raw[amiga_pod.ICON_BODY] for _name, raw in records]
    assert max(heads) <= 13, heads
    assert max(bodies) <= 31, bodies
    assert all(raw[amiga_pod.ICON_DIMENSION]
               == amiga_pod.ICON_DIMENSION_DEFAULT for _name, raw in records)


def test_the_engines_icon_default_is_what_most_of_the_disks_records_hold():
    """The rule at `0x00C736` is the ICON screen's *starting position*, so a
    record matching it is one nobody changed. Across all 19 records that is 15
    heads, 11 bodies and 10 colour blocks; the exact counts are asserted only
    when all 19 are present. The rest are player choices, which is what makes
    this the default and not a constraint."""
    heads = bodies = colours = 0
    records = pc_records()
    for _name, raw in records:
        want = amiga_pod.engine_default_icon(
            raw[amiga_pod.RACE], raw[amiga_pod.SEX], raw[amiga_pod.SIZE],
            raw[amiga_pod.CLASS_LEVELS:
                amiga_pod.CLASS_LEVELS + amiga_pod.CLASS_LEVEL_COUNT])
        heads += raw[amiga_pod.ICON_HEAD] == want[0]
        bodies += raw[amiga_pod.ICON_BODY] == want[1]
        colours += raw[amiga_pod.ICON_COLOURS:
                       amiga_pod.ICON_COLOURS
                       + amiga_pod.ICON_COLOUR_COUNT] == (
            amiga_pod.ICON_COLOURS_DEFAULT)
    if len(records) == 19:
        assert (heads, bodies, colours) == (15, 11, 10)
    else:
        # A player with some of the disks has some of the records, and the
        # counts above are only true of all of them. A count still cannot
        # exceed the records present.
        assert max(heads, bodies, colours) <= len(records)


@pytest.mark.parametrize("race,size", (
    ("DWARF", 1), ("GNOME", 1), ("HALFLING", 1),
    ("ELF", 2), ("HALF-ELF", 2), ("HUMAN", 2),
))
def test_the_engine_sizes_each_race_by_name(race, size):
    """`0x00E552`'s jump table: the three small races write 1, the other
    three 2. Checked by name because the disks hold one dwarf and no gnome or
    halfling."""
    assert amiga_pod.engine_size_for_race(amiga_pod.RACES.index(race)) == size


def test_the_writers_icon_body_colours_and_figure_can_be_overridden():
    """A source that does have a choice for these three writes it and not the
    engine's default."""
    colours = bytes((1, 2, 3, 4, 5, 6))
    out = amiga_pod.PodWriter(
        name="PICK", icon_head=2, icon_body=9, icon_colours=colours,
        combat_figure=4).to_bytes()
    assert out[amiga_pod.ICON_HEAD] == 2
    assert out[amiga_pod.ICON_BODY] == 9
    assert out[amiga_pod.ICON_COLOURS:
               amiga_pod.ICON_COLOURS + amiga_pod.ICON_COLOUR_COUNT] == colours
    assert out[amiga_pod.COMBAT_FIGURE] == 4


def test_the_unnamed_pair_at_0c5_is_two_two_without_any_disk():
    """`02 02` is what creation writes and what the Silver Blades importer
    forces, so a writer with nothing to go on emits it."""
    out = amiga_pod.PodWriter(name="PAIR").to_bytes()
    assert out[amiga_pod.UNNAMED_1A4:amiga_pod.UNNAMED_1A4 + 2] == bytes(
        (amiga_pod.UNNAMED_1A4_DEFAULT,) * 2) == bytes((2, 2))


def test_the_size_byte_is_the_one_the_race_routine_writes():
    """`0x00E552` sets `0x0BE` from race: 1 for the dwarf, the gnome and the
    halfling, 2 for the other three. 19 of 19 records agree, and the writer
    falls back on it for a source that keeps no size of its own."""
    for name, raw in pc_records():
        assert raw[amiga_pod.SIZE] == amiga_pod.engine_size_for_race(
            raw[amiga_pod.RACE]), name
    out = amiga_pod.PodWriter(
        name="DWARF", race=amiga_pod.RACES.index("DWARF")).to_bytes()
    assert out[amiga_pod.SIZE] == 1
    out = amiga_pod.PodWriter(
        name="HUMAN", race=amiga_pod.RACES.index("HUMAN")).to_bytes()
    assert out[amiga_pod.SIZE] == 2


def test_an_effect_duration_is_byte_swapped_into_the_amiga_node():
    """DOS keeps the duration little-endian at 1 and the `.pc` node big-endian
    at 2, so 0x0102 is the bytes `02 01` in one and `01 02` in the other.
    Every genuine node holds a duration of zero, so only a synthetic one can
    tell the two orders apart."""
    dos = bytes((7, 0x02, 0x01, 0xFF, 0x00, 0, 0, 0, 0))
    node = amiga_pod.pod_effect_from_dos(dos)
    assert node[2:4] == bytes((0x01, 0x02))
    assert amiga_pod.pod_effect_to_dos(node)[:5] == dos[:5]


# --- the negative result, which is the state of the Amiga end ----------------

def test_a_caster_read_out_of_a_pc_reaches_dos_with_his_spellbook():
    """A caster read off an Amiga disk reaches DOS with his own spellbook.

    The book is the sixteen-byte mask at `0x159` and the ids are the DOS
    array's own, so the two ports' lists compare directly. The four casters
    with a DOS record of the same class and the same levels are checked
    **against that record's spellbook**, which is the strongest form the
    claim has: the ids that come out of the Amiga mask are the ids the other
    port stores for the same character.
    """
    seen = casters = 0
    for name, raw in pc_records():
        out = amiga_pod.pod_to_neutral(raw)
        rec, itm, spc, _report = dos_codec.write(out)
        assert len(rec) == POD.record_size, name
        # He arrives carrying what the `.pc` holds: every file on the disks
        # has items, and `tests/amiga/test_podamiga_regions.py` is where the
        # `.THG` and the `.EFX` are checked field by field.
        assert itm != b"", name
        back = dos_codec.DosCharacter(rec)
        assert back.spells_known == out.get("spells_known"), name
        assert back.get("thac0_base") == out.get("thac0_base"), name
        if back.spells_known:
            casters += 1
        seen += 1
    assert seen >= 12
    assert casters >= 4, casters


def test_the_amiga_spellbook_is_the_dos_spellbook_for_the_same_character():
    """The ids, against the other port's own record of the same class and
    levels: nine of the ten pairs agree exactly, id for id.

    The tenth is the cleric 14s, which carry seventeen ids their DOS
    counterparts do not -- the magic-user's whole level-1 group and the
    druid's -- and it is a fact about those three shipped characters rather
    than about the encoding, so it is named and counted rather than rounded
    away (`#462`).
    """
    peers: dict[tuple, set] = {}
    for path in dos_records():
        char = dos_codec.read_character(path)
        key = (char.get("char_class"), tuple(char.raw("class_levels")))
        peers.setdefault(key, set()).add(frozenset(char.spells_known))
    exact = extra = 0
    for name, raw in pc_records():
        pc = amiga_pod.PodCharacter.from_bytes(raw)
        key = (pc.character_class, tuple(pc.class_levels))
        if key not in peers:
            continue
        mine = frozenset(pc.spells_known)
        if mine in peers[key]:
            exact += 1
            continue
        # Always the same seventeen ids more than the DOS peer, whichever
        # peer: the magic-user's level-1 group and the druid's. What the DOS
        # side has and this does not is DOMINIC's single id 118, which
        # FLORENTZ, the other DOS cleric 14, has not got either.
        for other in peers[key]:
            assert sorted(mine - other) == list(range(9, 22)) + [77, 78, 79,
                                                                 80], name
            assert other - mine <= {118}, (name, sorted(other - mine))
        extra += 1
    assert exact >= 7, exact
    assert extra == 3, extra


def test_the_reader_has_nothing_left_to_say_to_a_player():
    """The reader puts no sentence in front of a player, and a sentence in
    place of the thing it describes is what `.claude/rules/conversions.md`
    forbids in the first place.

    What it reports instead is eleven names on `pod_read_dropped()`, which
    goes to `wish/debuglog.py`: nine fields this title has on neither port,
    `innate_effects` -- a label rather than a byte, since everything that
    never expires is converted as a grant -- and `attack_level`, which this
    title's engine works out from the class level and keeps nowhere.
    """
    dropped = dict(amiga_pod.pod_read_dropped())
    assert len(dropped) == 11, sorted(dropped)
    assert "inventory" not in dropped
    assert "granted_effects" not in dropped
    assert {"innate_effects", "attack_level"} <= set(dropped)
    for name, raw in pc_records():
        out = amiga_pod.pod_to_neutral(raw)
        assert [w for w in out.warnings if "(NOT APPROVED)" in w] == [], name
        assert out.warnings == [], name


def test_the_reader_fills_sixty_four_of_the_neutral_records_fields():
    """The count that says how far the Amiga decode has got, pinned so it
    moves when somebody decodes another region rather than drifting.

    64 of the 78, and 65 for a character with an effect that never expires,
    since `granted_effects` is set only when there is one -- the same way the
    Curse and Silver Blades reader sets it. On this machine that is ten
    characters at 64 and nine at 65.

    The names it does not fill for a character on these disks:
    `npc_control_byte`, which is set only for a companion and so is absent
    from a player character rather than dropped, exactly as it is absent from
    a DOS one; `granted_effects` for a character with nothing at duration
    zero; and `running_effects`, which no disk's node can fill because every
    duration word is zero.
    """
    counts: dict[int, int] = {}
    for _name, raw in pc_records():
        out = amiga_pod.pod_to_neutral(raw)
        effects = amiga_pod.PodCharacter.from_bytes(raw).effects
        assert len(out.fields) == 64 + bool(effects), sorted(out.fields)
        named = set(out.fields) | {n for n, _ in amiga_pod.pod_read_dropped()}
        assert set(neutral.FIELDS) - named == (
            {"npc_control_byte", "running_effects"} if effects
            else {"npc_control_byte", "running_effects", "granted_effects"})
        counts[len(out.fields)] = counts.get(len(out.fields), 0) + 1
    assert sum(counts.values()) >= 12, counts
    assert counts.get(64), counts


# --- the engine's own account of its record, read off the player's disk ------

def test_every_offset_matches_the_engines_own_silver_blades_importer():
    """The decode `#462` rests on, re-derived rather than quoted.

    Amiga Pools of Darkness carries a routine that turns an Amiga *Secret of
    the Silver Blades* record into one of its own, at file offset `0x026000`
    of `/Pools of Darkness` on disk 1. It is a field-by-field copy, and
    `goldbox.amiga_port.SILVER_BLADES_DELTAS` names every source offset because
    `#55` decoded that record -- so each instruction reads as "Silver Blades'
    *name* is at Pools of Darkness' `0xY`".

    `tools/amiga/podimportmap.py` decodes the routine and compares it with this
    module's constants. It is what caught two of them being wrong:
    `HP_CURRENT` was the word at 0x190 and is the byte at 0x191, and
    `PORTRAIT_BODY` was 0x0B8, which is `hp_rolled`.

    Needs `capstone` and the player's own Amiga disk images; skips without
    either, which is what CI does.
    """
    capstone = pytest.importorskip("capstone")
    assert capstone
    from automap import gamedisks
    from tools.amiga import podimportmap

    if not gamedisks.candidates("amiga"):
        pytest.skip("no Amiga disk images; set $AMIGA_DISKS")
    try:
        found = podimportmap.read(quiet=True)
    except SystemExit as why:
        pytest.skip(str(why))
    assert len(found) == 77, len(found)
    assert podimportmap.check(found) == 0


def test_this_title_reads_its_attack_table_at_the_class_level():
    """**The record has no `attack_level` because the engine keeps none.**

    Silver Blades keeps one at Amiga `0x080` and this title's importer copies
    nothing into it. The two routines that derive `thac0_base` at `0x07F` --
    the derived-fields rebuild at `0x03C238` and character creation at
    `0x00EF82` -- index one table with `22 * class + level` and neither reads
    any other byte of the record.

    **What the nineteen files prove is the table's address and the arithmetic
    over `class_levels`**: every one of them is zero in
    `former_class_levels`, so neither the gate on the former array
    (`dual_class_level_counts`) nor the engine's cap at level 21 is exercised
    by any record on this machine, and both come off the listing alone. Three
    of the nineteen are multi-classed -- BOHLO BART AB a fighter 9/thief 13
    and two fighter/magic-user/thieves -- which is what makes the "best row
    entry of the seven slots" half more than a single-class claim.

    Needs `capstone` and the player's own Amiga disk images; skips without
    either, which is what CI does.
    """
    capstone = pytest.importorskip("capstone")
    assert capstone
    from automap import gamedisks
    from tools.amiga import podimportmap

    if not gamedisks.candidates("amiga"):
        pytest.skip("no Amiga disk images; set $AMIGA_DISKS")
    try:
        table = podimportmap.thac0_table(podimportmap.executable(quiet=True))
    except SystemExit as why:
        pytest.skip(str(why))

    assert len(table) == len(amiga_pod.CLASS_LEVEL_SLOTS)
    for name, row in zip(amiga_pod.CLASS_LEVEL_SLOTS, table):
        assert len(row) == podimportmap.THAC0_TABLE_STRIDE, name
        # Stored `60 - THAC0`, so a row climbs with the level and never
        # passes the bias: a table read at the wrong address would not.
        assert row == sorted(row), name
        assert all(30 < b <= amiga_pod.COMBAT_BIAS for b in row), name
    fighter = table[amiga_pod.CLASS_LEVEL_SLOTS.index("FIGHTER")]
    wizard = table[amiga_pod.CLASS_LEVEL_SLOTS.index("MAGIC-USER")]
    assert fighter[14] > wizard[14]

    records = dict(pc_records())
    multi = [name for name, raw in records.items()
             if sum(1 for level in amiga_pod.PodCharacter.from_bytes(
                 raw).class_levels if level) > 1]
    former = [name for name, raw in records.items()
              if any(amiga_pod.PodCharacter.from_bytes(
                  raw).former_class_levels)]
    assert len(records) >= 12, len(records)
    assert len(multi) >= 3, multi
    assert former == [], former
    assert podimportmap.check_thac0(table, records) == 0
    exe = podimportmap.executable(quiet=True)
    from tools.amiga import amigarecordrefs
    start, end = amigarecordrefs.code_range(exe)
    assert podimportmap.check_attack_table_sites(
        podimportmap.attack_table_sites(exe, start, end)) == 0
    assert "attack_level" in dict(amiga_pod.pod_read_dropped())


def test_the_roster_tail_is_derived_and_not_dropped():
    """The nine bytes at `0x188` are the engine's to fill, so leaving them
    zero is not a loss and must not be counted as one.

    `.claude/rules/conversions.md`: *a field the destination recomputes on
    load* is not a drop and has its own list. Every byte of the block is
    written by a routine named in `DERIVED_SITES` or by the copy inside
    `DERIVED_REBUILD`, and the two the rebuild does not touch are filled by a
    fight's own setup loop.

    Needs no disk: it reads the writer's own declared tables.
    """
    dropped = dict(amiga_pod.POD_WRITE_DROPPED)
    derived = dict(amiga_pod.POD_WRITE_DERIVED)
    assert "roster_tail" not in dropped
    assert "roster_tail" in derived
    assert amiga_pod.pod_write_field_disposition()[
        "roster_tail"].startswith("derived:")
    for at in range(amiga_pod.ROSTER_TAIL,
                    amiga_pod.ROSTER_TAIL + amiga_pod.ROSTER_TAIL_LENGTH):
        assert at in amiga_pod.DERIVED, hex(at)
    assert amiga_pod.UNNAMED_0C9 in amiga_pod.DERIVED


def test_derived_holds_the_sixteen_offsets_the_engine_rebuilds():
    """Dropping an offset from `DERIVED` would make the writer's zero there
    look like an unaccounted byte, so the list is pinned by count and by the
    two ends the last change added.

    Needs no disk: it reads the writer's own declared table.
    """
    assert len(amiga_pod.DERIVED) == 16, len(amiga_pod.DERIVED)
    assert len(set(amiga_pod.DERIVED)) == 16
    for at in (amiga_pod.ITEM_COUNT_CACHE, amiga_pod.HANDS_USED,
               amiga_pod.UNNAMED_0C9):
        assert at in amiga_pod.DERIVED, hex(at)


def test_the_writer_leaves_every_byte_the_engine_rebuilds_alone():
    """A record this writer makes is zero at all sixteen `DERIVED` offsets,
    and at the low byte of the encumbrance word beside the first of them.

    The other half of the row above: a table saying a field is derived is only
    true while the writer actually declines to write it. Built from the writer
    rather than off a disk, and with a readied item and a saving-throw bonus
    in the source so the two item-fed bytes -- `hands_used` and
    `UNNAMED_0C9` -- have something they could have been filled from.
    """
    node = bytearray(amiga_pod.ITEM_FILE_SIZE)
    for field_name, value in (("type_index", 18), ("plus", 3),
                              ("plus_save", 2), ("readied", 1),
                              ("quantity", 1)):
        node[amiga_pod.ITEM_FIELD_AT[field_name]] = value
    at = amiga_pod.ITEM_FIELD_AT["weight"]
    node[at:at + 2] = (40).to_bytes(2, "big")
    built = amiga_pod.PodWriter(
        name="R", race=amiga_pod.RACES.index("HUMAN"),
        character_class=amiga_pod.CLASSES.index("FIGHTER"),
        class_levels=(0, 0, 8, 0, 0, 0, 0),
        attack_forms=(2, 0, 1, 0, 2, 0, 0, 0),
        items=(bytes(node),)).to_bytes()
    left = {at: built[at] for at in amiga_pod.DERIVED if built[at]}
    assert left == {}, {hex(k): v for k, v in left.items()}
    # `encumbrance` is a big-endian word and `DERIVED` names its high byte,
    # which stays zero under 256 whatever is written; the low byte is where
    # a weight would land.
    assert built[amiga_pod.ENCUMBRANCE:amiga_pod.ENCUMBRANCE + 2] == \
        bytes(2), built[amiga_pod.ENCUMBRANCE:amiga_pod.ENCUMBRANCE + 2].hex()
    # And `attack_forms`, which the fight setup fills `0x189` and `0x18A`
    # from, does reach the file -- otherwise the two bytes would be derived
    # from nothing.
    assert built[amiga_pod.ATTACK_FORMS:
                 amiga_pod.ATTACK_FORMS + amiga_pod.ATTACK_FORM_COUNT] == \
        bytes((2, 0, 1, 0, 2, 0, 0, 0))


def test_the_saving_throw_byte_is_the_readied_items_own_plus_save():
    """`gap_19a` at `0x0C9` is the sum of `plus_save` over the readied items,
    **19 of 19**, which is the pattern the files show and not the engine's
    whole rule.

    The rule is the code: `DERIVED_REBUILD` clears the byte at `0x0195C0` and
    `0x01891E`, called from its item loop, adds an item's `plus_save` in at
    `0x0189AC`-`0x0189B8` only when the item-table entry's byte 6 has bit 7
    set with its low seven bits zero and the item type is not 1. Five
    of the nineteen wear the one type-59 item that carries `plus_save` 2 and
    hold 2 here; the other fourteen hold 0, so nothing in these files
    separates a qualifying item from any other.

    Had the byte been anything the game does not rebuild, the writer's zero
    would be a loss rather than the state a loaded record leaves.
    """
    seen = carrying = 0
    for name, raw in pc_records():
        char = amiga_pod.PodCharacter.from_bytes(raw)
        total = sum(item.get("plus_save") for item in char.items
                    if item.get("readied"))
        assert raw[amiga_pod.UNNAMED_0C9] == total, name
        carrying += bool(total)
        seen += 1
    assert seen >= 12
    assert carrying >= 3, carrying


def test_the_two_attack_counts_are_zero_in_every_record_the_game_wrote():
    """`0x189` and `0x18A` are the only bytes of `roster_tail` the load-time
    rebuild does not touch, and they are **0 in 19 of 19**.

    That records what the shipped files hold and nothing more: they were saved
    outside a fight, so it is not an independent half of the argument for the
    writer's zero. The argument is the engine's setup order -- a fight's setup
    loop clears `$0A` and then fills both bytes from `attack_forms`
    (`DERIVED_SITES`), so a loaded value is overwritten before a fight reads
    it. The other three bytes asserted here are the second half of each damage
    pair, which the rebuild copies from `attack_forms` and which is zero in
    every record too.

    `0x18D` is the counter-example that shows the copy is not the last word:
    it holds a weapon's die size where its copy source `0x0AF` holds the
    unarmed 2, because `0x018778` overwrites it from the readied weapon.
    """
    seen = overwritten = 0
    for name, raw in pc_records():
        for at in amiga_pod.ROSTER_TAIL_ZERO:
            assert raw[at] == 0, (name, hex(at))
        assert raw[amiga_pod.ATTACK_FORMS + 4] == 2, name
        overwritten += raw[amiga_pod.ROSTER_TAIL + 5] != 2
        seen += 1
    assert seen >= 12
    assert overwritten == seen, (overwritten, seen)


def test_the_engine_writes_every_derived_byte_this_writer_leaves_zero():
    """`DERIVED_SITES` and the two calls of `DERIVED_REBUILD`, re-derived off
    the player's own disk 1 rather than quoted.

    Each site is one instruction of the engine's own rebuild, item loop or
    fight setup, and together they cover every byte of `DERIVED` no probe has
    watched: the item count and `hands_used` cleared and counted, the
    saving-throw byte cleared, accumulated and read back, the armour bonus,
    the two attack counts, and the `0x18B`-`0x190` copy loop with its source
    and destination bases and the weapon routine that overwrites three of the
    six. The calls put the rebuild on the `.pc` load path: *Add Character*
    calls it between the loader at `0x025806` and the roster join at
    `0x027394`, and the inter-title import path calls it too, which is what
    makes "the game fills it in" a claim about loading a file and not about a
    routine that merely exists.

    Needs `capstone` and the player's own Amiga disk images; skips without
    either, which is what CI does.
    """
    capstone = pytest.importorskip("capstone")
    from automap import gamedisks
    from tools.amiga import amiga68k, podimportmap

    if not gamedisks.candidates("amiga"):
        pytest.skip("no Amiga disk images; set $AMIGA_DISKS")
    try:
        data = podimportmap.executable(quiet=True)
    except SystemExit as why:
        pytest.skip(str(why))

    md = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_M68K_000)
    for where, instruction in amiga_pod.DERIVED_SITES:
        one = next(md.disasm(data[where:where + 12], where, count=1), None)
        found = f"{one.mnemonic} {one.op_str}" if one else None
        assert found == instruction, (hex(where), found)

    exe = amiga68k.Executable.parse(data)
    for call in (amiga_pod.DERIVED_LOAD_CALL, amiga_pod.DERIVED_IMPORT_CALL):
        assert data[call:call + 2] == b"\x4e\xac", hex(call)
        d16 = int.from_bytes(data[call + 2:call + 4], "big", signed=True)
        assert exe.resolve_a4(d16) == amiga_pod.DERIVED_REBUILD, hex(call)


def test_the_attack_table_check_fails_when_a_record_disagrees():
    """The failure path of `check_thac0`, which the run above never takes.

    Built from the format rather than off a disk: a seven-row table whose
    entries are the level, and a fighter 3 whose stored byte says 9. A check
    that could not come back non-zero would prove nothing about the 19.
    """
    from tools.amiga import podimportmap

    table = [list(range(podimportmap.THAC0_TABLE_STRIDE))
             for _ in amiga_pod.CLASS_LEVEL_SLOTS]
    right = amiga_pod.PodWriter(
        name="F", race=amiga_pod.RACES.index("HUMAN"),
        character_class=amiga_pod.CLASSES.index("FIGHTER"),
        class_levels=(0, 0, 3, 0, 0, 0, 0), thac0_base=3).to_bytes()
    wrong = bytearray(right)
    wrong[amiga_pod.THAC0_BASE] = 9

    assert podimportmap.check_thac0(table, {"RIGHT.pc": right}) == 0
    assert podimportmap.check_thac0(table, {"WRONG.pc": bytes(wrong)}) == 1


def test_the_attack_table_search_finds_a_small_data_reference_and_only_that(
        monkeypatch):
    """`attack_table_sites` is what the claim "no third routine indexes the
    table" rests on, so it has to find a reference and reject look-alikes.

    Built from the format on a synthetic buffer of `nop`s, with no disk:
    `lea.l -$621e(a4), a0` at 0x40 and one at a row inside the table
    (`-$6208`, the second class's row) at 0x80 are references; the same
    displacement off `a3` at 0xC0, and the word at an odd offset, are not.
    A reference outside the two routines fails the check, and so does a
    search that finds none.
    """
    pytest.importorskip("capstone")
    from tools.amiga import podimportmap

    def lea(displacement: int, register: int = 4) -> bytes:
        return (0x41E8 + register).to_bytes(2, "big") + (
            displacement & 0xFFFF).to_bytes(2, "big")

    buf = bytearray(b"\x4e\x71" * 0x100)
    buf[0x40:0x44] = lea(-0x621E)
    buf[0x80:0x84] = lea(-0x6208)
    buf[0xC0:0xC4] = lea(-0x621E, register=3)
    buf[0x101:0x103] = (-0x621E & 0xFFFF).to_bytes(2, "big")

    found = podimportmap.attack_table_sites(bytes(buf))
    assert [at for at, _ in found] == [0x40, 0x80]
    assert all("(a4)" in text for _at, text in found)

    monkeypatch.setattr(podimportmap, "THAC0_SITES", (0x50, 0x90))
    assert podimportmap.check_attack_table_sites(found) == 0
    monkeypatch.setattr(podimportmap, "THAC0_SITES", (0x50,))
    assert podimportmap.check_attack_table_sites(found) == 1
    assert podimportmap.check_attack_table_sites([]) == 1


def test_the_former_class_level_only_counts_when_the_engines_gate_opens():
    """`0x03D046` reads the former array only when `0x03D020` says so, and
    that is two tests rather than a bare `max` of the two arrays.

    Read off the listing, and no record on this machine exercises it: a human
    whose current level is above the byte at `0x08A` gets his old class's
    level into the arithmetic; a dwarf with the same arrays does not, because
    `0x03CFB2` returns zero for any race but the human; and neither does a
    human whose `former_level` is his current level or higher.
    """
    from tools.amiga import podimportmap

    def built(race: str, former_level: int):
        return amiga_pod.PodCharacter.from_bytes(amiga_pod.PodWriter(
            name="DUAL", race=amiga_pod.RACES.index(race),
            character_class=amiga_pod.CLASSES.index("MAGIC-USER"),
            class_levels=(0, 0, 0, 0, 0, 12, 0),
            former_class_levels=(11, 0, 0, 0, 0, 0, 0),
            former_level=former_level).to_bytes())

    assert podimportmap.dual_class_level_counts(built("HUMAN", 11)) is True
    assert podimportmap.dual_class_level_counts(built("HUMAN", 12)) is False
    assert podimportmap.dual_class_level_counts(built("DWARF", 11)) is False

    # Every row is the level itself except the cleric's, which is 50
    # throughout: so the answer is 50 when the old cleric level is allowed
    # into the arithmetic and the magic-user's own 12 when it is not.
    table = [list(range(podimportmap.THAC0_TABLE_STRIDE))
             for _ in amiga_pod.CLASS_LEVEL_SLOTS]
    table[amiga_pod.CLASS_LEVEL_SLOTS.index("CLERIC")] = [
        50] * podimportmap.THAC0_TABLE_STRIDE
    assert podimportmap.thac0_base(table, built("HUMAN", 11)) == 50
    assert podimportmap.thac0_base(table, built("HUMAN", 12)) == 12
    assert podimportmap.thac0_base(table, built("DWARF", 11)) == 12
