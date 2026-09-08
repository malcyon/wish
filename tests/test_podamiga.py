from __future__ import annotations

"""Reading an Amiga Pools of Darkness `.pc`, and the DOS route (#194).

`goldbox.amiga.PodWriter` has turned a neutral character into a `Save/NAME.pc`
since `#7`, and **nothing turned one back**: `PodCharacter` had no caller
anywhere in `goldbox/`, `editor/` or `tools/`, so the Amiga end of
`#194 (Import and export a Pools of Darkness save between DOS and the Amiga)`
had one direction of two. `goldbox.amiga.pod_to_neutral` is the other, and
this is its proof.

What is tested, hardest evidence first.

* **The two ports' tables are the same tables.** Race, class code, class-level
  slots and alignment all index identically on the Amiga `.pc` and the DOS
  510-byte record, so a same-title conversion copies rather than looks up.
  That is the claim everything else rests on and it is checked against both
  ports' own files.
* **The round trips**, each with its own count: a `.pc` read and written back,
  and a DOS record converted into a `.pc`.
* **The negative result**, stated as a number rather than a shrug: 37 of the
  75 neutral fields have no located home in the `.pc`, so a character
  converted *out* of the Amiga arrives in DOS with no spellbook and no
  possessions. It is a test because a later reader must not mistake the route
  existing for the route being finished.

**The specimens are the twelve genuine `.pc` files in the `Save` drawer of
Amiga Pools of Darkness disk 3**, read out of the player's own `.adf` at run
time through `gamedisks.toml`'s `amiga` entry -- the same route
`tests/test_amiga.py` uses for the Amiga Pool of Radiance records, and for the
same reason: they are not loose files on any machine. Everything here skips
without the disks, which is what CI does.
"""

import pathlib

import pytest

from goldbox import amiga, dos, dos_layout, neutral

POD = dos_layout.POOLS_OF_DARKNESS

#: The names the reader fills and the two the writer drops but it does not.
READ_ONLY = ("armour_class", "armour_class_base")


def pc_bytes() -> dict[str, bytes]:
    """Every `Save/*.pc` on an Amiga disk we can see, by file name.

    `tools/amigasaves.py`'s `images` is the shared discovery -- it opens
    loose `.adf` files and the Gold Box zips inside an Amiga ROM library --
    and this narrows to the `.pc` files, which its own `specimens` does not
    yield: that one keeps to the 288-byte Pool of Radiance record.

    **They are not loose files on any machine and `gamedisks.toml`'s
    `pod-saves` entry says so**, which is true of an *exported* `.pc` and
    left the twelve the game itself ships unused. Same shape as `#211 (103
    tests skip on the machine that has the game files, and the game files
    are not why)`, and the same answer `amiga-por-saves` already got: read
    them out of the disk images instead of skipping.

    Returns empty rather than skipping, so a caller that has its own
    fallback can use one.
    """
    from goldbox.amiga_adf import AmigaDisk, AmigaDiskError
    from tools import amigasaves, gamedisks

    if not gamedisks.candidates("amiga"):
        return {}
    out: dict[str, bytes] = {}
    for _label, data in amigasaves.images():
        try:
            disk = AmigaDisk(data)
            entries = list(disk.walk())
        except (AmigaDiskError, ValueError):
            continue
        for path, _entry in entries:
            if not path.lower().endswith(".pc"):
                continue
            try:
                out.setdefault(path.rsplit("/", 1)[-1], disk.read_file(path))
            except AmigaDiskError:
                continue
    return out


def pc_records() -> list[tuple[str, bytes]]:
    """:func:`pc_bytes`, sorted, skipping when there are none."""
    found = pc_bytes()
    if not found:
        pytest.skip("no Amiga Pools of Darkness .pc files; set $AMIGA_DISKS")
    return sorted(found.items())


def dos_records() -> list[pathlib.Path]:
    """The shipped DOS Pools of Darkness records, by directory and size."""
    from test_dossave import _game_dirs

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
    """`goldbox.amiga.RACES` and `goldbox.dos_layout
    .POOLS_OF_DARKNESS_RACE_NUMBERS` are the same six names in the same
    order, with `monster` after them on the DOS side only.

    This is what makes `race` a copy rather than a lookup, and it is also
    what `goldbox/games.py`'s Pools of Darkness entry would have to say --
    it has none, and its default is Pool of Radiance's numbering, under which
    race 5 is a halfling rather than the human it is here.
    """
    ours = tuple(name.lower() for name in amiga.RACES)
    theirs = tuple(POD.race_numbers)
    assert ours == theirs[:len(ours)]
    assert theirs[len(ours):] == ("monster",)
    assert theirs[5] == "human"


def test_the_class_codes_and_level_slots_are_the_same_on_both_ports():
    """A class code read off a DOS record names the same class in
    `goldbox.amiga.CLASSES`, and the seven level slots are in one order.

    Checked against both ports' own files rather than by reading the two
    tuples side by side: every DOS record's class code, looked up in the
    Amiga table, has to agree with the classes its own level array holds.
    """
    assert tuple(n.lower() for n in amiga.CLASS_LEVEL_SLOTS) == \
        tuple(name for _n, name, _f in dos.CLASS_LEVEL_SLOTS[:7])
    seen = 0
    for path in dos_records():
        char = dos.read_character(path)
        code = char.get("char_class")
        assert 0 <= code < len(amiga.CLASSES), (path.name, code)
        held = {name for n, name, _f in dos.CLASS_LEVEL_SLOTS
                if n < len(char.raw("class_levels"))
                and char.raw("class_levels")[n]}
        named = {p.strip().lower() for p in
                 amiga.CLASSES[code].replace("M-U", "MAGIC-USER").split("/")}
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
        char = dos.read_character(path)
        if amiga.CLASSES[char.get("char_class")] == "PALADIN":
            assert char.get("alignment") == 0, path.name
            paladins += 1
    for name, raw in pc_records():
        c = amiga.PodCharacter.from_bytes(raw)
        if c.class_name == "PALADIN":
            assert c.alignment == 0, name
            paladins += 1
    assert paladins >= 4


# --- the reader --------------------------------------------------------------

def test_every_neutral_field_has_a_reader_disposition():
    """A field `goldbox/neutral.py` declares and `pod_field_disposition`
    names nowhere would be one dropped in silence."""
    assert neutral.undeclared(neutral.FIELDS,
                              amiga.pod_field_disposition()) == (set(), set())


def test_the_reader_drops_what_the_writer_drops_but_for_two_names():
    """`pod_read_dropped` is computed from the writer's `DROPPED` rather than
    listed again, so the two lists cannot drift.

    The two names that differ are the point of the docstring there:
    `armour_class` and `armour_class_base` are readable -- the record holds
    the byte -- and not writable, because the game recomputes armour class on
    load and ignores what the file says.
    """
    writer = {n for n, _ in amiga.DROPPED}
    reader = {n for n, _ in amiga.pod_read_dropped()}
    assert reader < writer
    assert writer - reader == set(READ_ONLY)
    for name in READ_ONLY:
        assert amiga.pod_field_disposition()[name].startswith("copied")


def test_every_genuine_record_reads_to_a_coherent_character():
    """The cross-checks that would fail on a wrong offset rather than
    restating one field: the level is the highest of the class levels, the
    class code decomposes to the classes the level array holds, every
    ability is a legal score, and the alignment is one the game has a word
    for.
    """
    seen = 0
    for name, raw in pc_records():
        out = amiga.pod_to_neutral(raw)
        assert out.get("name"), name
        assert str(out.get("name")).isprintable(), name
        levels = {k: v for k, v in out.get("levels").items() if v}
        assert levels, name
        assert out.get("level") == max(levels.values()), name
        for ability in neutral.ABILITIES:
            if ability == "exceptional_strength":
                continue
            assert 3 <= out.get(ability) <= 25, (name, ability)
        assert 0 <= out.get("alignment") < len(amiga.ALIGNMENTS), name
        assert out.get("sex") in (0, 1), name
        assert 0 <= out.get("race") < len(amiga.RACES), name
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
        c = amiga.PodCharacter.from_bytes(raw)
        out = amiga.pod_to_neutral(raw)
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
        "experience": (amiga.EXPERIENCE, 4),
        "platinum": (amiga.PLATINUM, 2),
        "gems": (amiga.GEMS, 2),
        "jewelry": (amiga.JEWELRY, 2),
        "age": (amiga.AGE, 2),
        "race": (amiga.RACE, 1),
        "char_class": (amiga.CLASS, 1),
        "sex": (amiga.SEX, 1),
        "alignment": (amiga.ALIGNMENT, 1),
        "abilities": (amiga.ABILITIES, 2 * amiga.ABILITY_COUNT),
        "exceptional_strength": (amiga.EXCEPTIONAL_STRENGTH, 2),
        "hp_max": (amiga.HP_MAX, 1),
        "movement": (amiga.MOVEMENT, 1),
        "class_levels": (amiga.CLASS_LEVELS, amiga.CLASS_LEVEL_COUNT),
        "armour_class": (amiga.ARMOUR_CLASS, 1),
        "hp_current": (amiga.HP_CURRENT, 2),
        "saving_throws": (amiga.SAVING_THROWS, amiga.SAVING_THROW_COUNT),
        "level": (amiga.LEVEL, 1),
        "thief_skills": (amiga.THIEF_SKILLS, amiga.THIEF_SKILL_COUNT),
        "class_bits": (amiga.CLASS_BITS, 1),
        "name": (amiga.NAME, amiga.NAME_LENGTH),
    }
    seen = clean = 0
    exceptions: list[str] = []
    for name, raw in pc_records():
        out, report = amiga.to_pc(amiga.pod_to_neutral(raw))
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
        stem = raw[amiga.NAME:amiga.NAME + amiga.NAME_LENGTH].split(b"\0")[0]
        assert out[amiga.NAME:amiga.NAME + len(stem)] == stem, name
        exceptions.append(name)
    assert seen >= 12
    assert clean == seen - len(exceptions)
    assert exceptions == ["T.pc"], exceptions


def test_every_dos_record_converts_into_a_pc():
    """DOS -> `dos.to_neutral` -> `amiga.to_pc`, 12 of 12.

    The route this ticket asked for, in the direction that has both ends: the
    DOS reader learned this title today and the Amiga writer has always had
    it. Each output is read back with `PodCharacter` and checked against the
    DOS record it came from, which is stronger than checking it is 484 bytes.
    """
    seen = 0
    for path in dos_records():
        char = dos.read_character(path)
        out = dos.to_neutral(char)
        pc, report = amiga.to_pc(out)
        assert len(pc) == amiga.RECORD_LENGTH, path.name
        assert report.unaccounted(pc) == [], path.name
        back = amiga.PodCharacter.from_bytes(pc)
        # The writer cuts trailing blanks, which DOS counts into its own
        # length byte: Guy de Valois is stored `Guy de Valois ` there.
        assert back.name == char.name[:amiga.NAME_LENGTH].rstrip(), path.name
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

    The old class is on `goldbox.amiga.DROPPED` as `former_levels`, so what
    is asserted here is that it is reported rather than silently lost.
    """
    seen = 0
    for path in dos_records():
        char = dos.read_character(path)
        out = dos.to_neutral(char)
        former = {k: v for k, v in (out.get("former_levels") or {}).items()
                  if v}
        pc, report = amiga.to_pc(out)
        back = amiga.PodCharacter.from_bytes(pc)
        held = {k for k, v in out.get("levels").items() if v}
        named = {p.strip().lower() for p in
                 amiga.CLASSES[back.character_class]
                 .replace("M-U", "MAGIC-USER").split("/")}
        assert named == held, (path.name, named, held)
        if former:
            seen += 1
            for gone in former:
                assert any(gone in w and "left behind" in w
                           for w in report.warnings), (path.name, gone)
    assert seen == 2, f"{seen} dual-classed characters, expected ABAGAIL and PAINE"


# --- the negative result, which is the state of the Amiga end ----------------

def test_a_character_read_out_of_a_pc_reaches_dos_without_spells_or_items():
    """**The Amiga-to-DOS direction is not finished, and this is what is
    missing rather than a claim that it works.**

    A `.pc` converts into a 510-byte DOS record today -- the writer takes it
    without raising, and the sheet's name, race, class, level, hit points,
    armour class, abilities, saving throws, thief skills, money, age,
    alignment and movement all arrive. What does not is everything whose home
    in the 484-byte record nobody has decoded: the spellbook, the memorised
    list, the item region, the effect region and the combat block. A
    magic-user 14 arriving with an empty spellbook is a loss a player sees on
    the first screen.

    So nothing offers this direction: `editor/convert.py` builds its list
    from `goldbox.games`, which has no Pools of Darkness entry at all. This
    test is here so that a reader who finds `pod_to_neutral` does not mistake
    its existence for the work being done.
    """
    seen = 0
    for name, raw in pc_records():
        out = amiga.pod_to_neutral(raw)
        rec, itm, spc, _report = dos.write(out)
        assert len(rec) == POD.record_size, name
        assert itm == b"" and spc == b"", name
        back = dos.DosCharacter(rec)
        assert not any(back.raw("spellbook")), name
        assert back.get("thac0_base") == 0, name
        assert back.get("item_count") == 0, name
        seen += 1
    assert seen >= 12


def test_the_reader_says_out_loud_what_it_could_not_read():
    """One sentence, not thirty-seven, and it is marked as awaiting Donald's
    wording. A conversion that says nothing about a character arriving
    without his spells is the silence `.claude/rules/conversions.md`
    forbids.
    """
    dropped = amiga.pod_read_dropped()
    assert len(dropped) == 37, len(dropped)
    for name, raw in pc_records():
        out = amiga.pod_to_neutral(raw)
        said = [w for w in out.warnings if "not been decoded" in w]
        assert len(said) == 1, name
        assert "(NOT APPROVED)" in said[0], name
        break


def test_the_reader_fills_thirty_eight_of_the_neutral_records_fields():
    """The count that says how far the Amiga decode has got, pinned so it
    moves when somebody decodes another region rather than drifting.

    38 filled and 37 not, of 75. `docs/124-amiga-port.md` §1 is how the 38
    were found.
    """
    for _name, raw in pc_records():
        out = amiga.pod_to_neutral(raw)
        assert len(out.fields) == 38, sorted(out.fields)
        assert len(out.fields) + len(amiga.pod_read_dropped()) == \
            len(neutral.FIELDS)
        break
