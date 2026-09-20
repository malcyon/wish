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
  shrug. It was 38 of the 75 neutral fields when this file was written and 37
  had no located home in the `.pc`, so a character converted *out* of the
  Amiga arrived in DOS with no spellbook and no possessions; `#462` decoded
  the record off the engine's own Silver Blades importer and then taught the
  reader the item region and the effect chain, and the count is pinned here so
  that it moves when somebody decodes another region rather than drifting.

**The specimens are the twelve genuine `.pc` files in the `Save` drawer of
Amiga Pools of Darkness disk 3**, read out of the player's own `.adf` at run
time through `gamedisks.yaml`'s `amiga` entry -- the same route
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


def test_the_reader_drops_a_strict_subset_of_what_the_writer_drops():
    """The reader's list was computed from the writer's until `#462` and is
    its own now, so this is what stops the two drifting apart the wrong way.

    **Reading a byte and writing one are not the same undertaking**, which is
    why they may differ at all: `#462` decoded the record off the engine's own
    Silver Blades importer, so the reader can take a field the writer must not
    fill in until somebody has watched the loader accept it. What must never
    happen is the reverse -- a name the reader drops and the writer does not
    -- because that would be a field this module claims to convert in a
    direction it cannot even read.
    """
    writer = {n for n, _ in amiga_pod.POD_WRITE_DROPPED}
    reader = {n for n, _ in amiga_pod.pod_read_dropped()}
    assert reader < writer
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

    **11 of 12 identical at every decoded offset, and the twelfth differs
    only in the name bytes past its NUL terminator**: `?T.pc` stores
    `3F 54 00 3F 3F ...`, so the engine left rubbish after the terminator and
    the writer NUL-pads. That is the same thing the DOS round trip masks for
    `name_text` past the count byte, and it is not a loss.

    The whole 484 bytes are **not** compared, and that is the honest
    boundary: only about 38 of the neutral record's fields have a located
    home in this record, so the writer zeroes the rest and the report says
    so. `Report.unaccounted` is the writer's own guarantee and is asserted
    empty here.
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
        # `0x0B3` is `armour_class_base` since #462, not `armour_class` --
        # the neutral `armour_class` is read from `ARMOUR_CLASS_CURRENT`
        # (`0x187`) now. The span passed under the old name only because
        # `PodWriter` writes the unarmoured constant to `0x0B3` whatever the
        # source holds, so both sides of the comparison were the same number
        # and a wrong name could not show. There is no `armour_class_current`
        # span to sit beside it until the writer fills `0x187` -- #475.
        "armour_class_base": (amiga_pod.ARMOUR_CLASS, 1),
        "hp_current": (amiga_pod.HP_CURRENT, 1),
        "saving_throws": (amiga_pod.SAVING_THROWS, amiga_pod.SAVING_THROW_COUNT),
        "level": (amiga_pod.LEVEL, 1),
        "thief_skills": (amiga_pod.THIEF_SKILLS, amiga_pod.THIEF_SKILL_COUNT),
        "class_bits": (amiga_pod.CLASS_BITS, 1),
        "name": (amiga_pod.NAME, amiga_pod.NAME_LENGTH),
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
        assert len(pc) == amiga_pod.RECORD_LENGTH, path.name
        assert report.unaccounted(pc) == [], path.name
        back = amiga_pod.PodCharacter.from_bytes(pc)
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


def test_a_dual_classed_character_arrives_as_the_class_he_is():
    """**ABAGAIL is a magic-user 12 who was a cleric 11 and PAINE a
    magic-user 13 who was a ranger 9**, and they are the two characters this
    route could not carry before.

    The neutral class mask holds a dual-classed character's old class as well
    as his current one, because the C64 needs it. Copied straight into the
    Amiga's single class code that made ABAGAIL a `CLERIC/MAGIC-USER`, a
    class she is not, and it refused PAINE outright -- Pools of Darkness has
    no magic-user/ranger code, and no character can be both at once.

    The old class is on `goldbox.amiga_pod.POD_WRITE_DROPPED` as
    `former_levels`, so what
    is asserted here is that it is reported rather than silently lost.
    """
    seen = 0
    for path in dos_records():
        char = dos_codec.read_character(path)
        out = dos_codec.to_neutral(char)
        former = {k: v for k, v in (out.get("former_levels") or {}).items()
                  if v}
        pc, report = amiga_pod.to_pc(out)
        back = amiga_pod.PodCharacter.from_bytes(pc)
        held = {k for k, v in out.get("levels").items() if v}
        named = {p.strip().lower() for p in
                 amiga_pod.CLASSES[back.character_class]
                 .replace("M-U", "MAGIC-USER").split("/")}
        assert named == held, (path.name, named, held)
        if former:
            seen += 1
            for gone in former:
                assert any(gone in w and "left behind" in w
                           for w in report.warnings), (path.name, gone)
    assert seen == 2, f"{seen} dual-classed characters, expected ABAGAIL and PAINE"


# --- the negative result, which is the state of the Amiga end ----------------

def test_a_caster_read_out_of_a_pc_reaches_dos_with_his_spellbook():
    """The loss this ticket was opened for, measured on both sides of it.

    **Before `#462` this test asserted the opposite** -- `assert not
    any(back.raw("spellbook"))`, because nobody had found the spellbook and a
    magic-user 14 arrived in DOS with an empty one and a THAC0 the sheet
    printed as 60. The spellbook is the sixteen-byte mask at `0x159` and the
    ids are the DOS array's own, so what arrives now is his own book.

    The four casters in the corpus with a DOS record of the same class and
    the same levels are checked **against that record's spellbook**, which is
    the strongest form the claim has: the ids that come out of the Amiga mask
    are the ids the other port stores for the same character.
    """
    seen = casters = 0
    for name, raw in pc_records():
        out = amiga_pod.pod_to_neutral(raw)
        rec, itm, spc, _report = dos_codec.write(out)
        assert len(rec) == POD.record_size, name
        # **`itm` and `spc` were both empty until the second half of `#462`**,
        # when this reader learned to walk the item region and the effect
        # chain; `tests/amiga/test_podamiga_regions.py` is where the two are
        # checked field by field.
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
    """**The one unapproved warning is gone, and nothing replaced it.**

    It said the part of the file holding possessions and running magic had
    not been read. The reader walks the item region and the effect chain
    now, so the sentence had stopped being true -- and a sentence to a player
    in place of the thing it describes is what
    `.claude/rules/conversions.md` forbids in the first place.

    What is left is eleven names on `pod_read_dropped()`, which goes to
    `wish/debuglog.py`: nine fields this title has on neither port,
    `innate_effects` -- a label rather than a byte, since everything that
    never expires is converted as a grant -- and `attack_level`, the one
    field of the record still unlocated.
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


def test_the_reader_fills_sixty_three_of_the_neutral_records_fields():
    """The count that says how far the Amiga decode has got, pinned so it
    moves when somebody decodes another region rather than drifting.

    **38 when this reader was written, 62 when `#462` decoded the record and
    63 now the tail is walked**, of 75 -- 64 for a character with an effect
    running on him, since `granted_effects` is set only when there is one,
    the same way the Curse and Silver Blades reader sets it. On this machine
    that is twelve characters at 63 and seven at 64.

    The two it never fills: `npc_control_byte`, which is set only for a
    companion and so is absent from a player character rather than dropped,
    exactly as it is absent from a DOS one, and `granted_effects` for a
    character with nothing running on him.
    """
    counts: dict[int, int] = {}
    for _name, raw in pc_records():
        out = amiga_pod.pod_to_neutral(raw)
        effects = amiga_pod.PodCharacter.from_bytes(raw).effects
        assert len(out.fields) == 63 + bool(effects), sorted(out.fields)
        named = set(out.fields) | {n for n, _ in amiga_pod.pod_read_dropped()}
        assert set(neutral.FIELDS) - named == (
            {"npc_control_byte"} if effects
            else {"npc_control_byte", "granted_effects"})
        counts[len(out.fields)] = counts.get(len(out.fields), 0) + 1
    assert sum(counts.values()) >= 12, counts
    assert counts.get(63), counts


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
    """**The last unlocated field of the record is not in the record.**

    `attack_level` was the one field `#462` could not place: Silver Blades
    keeps it at Amiga `0x080` and this title's importer does not copy it. The
    reason is that Pools of Darkness has no such field. Two routines fill
    `thac0_base` at `0x07F` -- the derived-fields rebuild at `0x03C238` and
    character creation at `0x00EF82` -- and both index one table with
    `22 * class + level`, where `level` is `max(class_levels[i],
    former_class_levels[i])` capped at 21 (`0x03D046`), and neither reads any
    other byte of the record.

    The arithmetic reproduces the stored `thac0_base` of **19 of 19** `.pc`
    files on this machine, single-classed, dual-classed and multi-classed
    alike, which is the corroboration the two listings on their own would
    not be.

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

    seen = 0
    for name, raw in pc_records():
        char = amiga_pod.PodCharacter.from_bytes(raw)
        assert podimportmap.thac0_base(
            table, char.class_levels, char.former_class_levels) == \
            char.thac0_base, name
        seen += 1
    assert seen >= 12, seen
    assert "attack_level" in dict(amiga_pod.pod_read_dropped())
