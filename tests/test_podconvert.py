from __future__ import annotations

"""Converting a DOS Pools of Darkness character, both directions (#194).

The title has no C64 port and never will, so this is not `#192`'s and
`#193`'s work over again: the second port is the **Amiga**, and what
`#194 (Import and export a Pools of Darkness save between DOS and the Amiga)`
needed first was a route between the 510-byte DOS record and the neutral
record, which refused this title by name until 2026-09-08.

Three kinds of test, hardest evidence first.

* **The round trip** over every Pools of Darkness record on this machine --
  read into the neutral record and written back, byte for byte outside the
  writer's own declared mask. The mask is `goldbox.dos.WRITE_UNSOURCED`,
  `WRITE_UNSOURCED_LATER`, `WRITE_DEFAULTS` and `WRITE_DERIVED`, never
  whatever happened to differ, and the two records that do differ are named
  and counted here rather than masked away.
* **The measurements this title needed that no earlier one did**: two
  undecoded runs that are not zero, an innate-effect set that is not Pool of
  Radiance's, and a race table `goldbox/games.py` has never had.
* **The tables**, which need no save: what the writer says it does with
  every field, and what this record has no field for at all.

**The records are Donald's, not the repository's**: the archives under
`$FR_ARCHIVES`, read at run time. Everything here skips without them, which
is what CI does. They are a *template* rather than evidence, in
`.claude/rules/testing.md`'s sense -- nobody watched them being written -- and
that is fine for a round trip, where what goes in comes back out and the
input's provenance does not enter the claim. It is **not** fine for the
racial and innate tables, and their tests say what they rest on.
"""

import pathlib

import pytest
from test_dossave import _game_dirs

from goldbox import dos, dos_layout, neutral

POD = dos_layout.POOLS_OF_DARKNESS
POOL = dos_layout.POOL_OF_RADIANCE
SSB = dos_layout.SECRET_OF_THE_SILVER_BLADES

#: Every neutral field the 510-byte record has no byte for at all.
ABSENT = ("copper", "silver", "electrum", "gold", "levels_drained",
          "hp_lost_to_drain", "experience_per_hit_point")


def _records() -> list[pathlib.Path]:
    """The Pools of Darkness records in the archives, by directory and size.

    **By directory and not by size alone**: Treasures of the Savage Frontier's
    records are 510 bytes too, so a sweep of the whole archive reads a game
    this project does not convert -- the same trap `tests/test_doslatertitles.
    py` names for Gateway's 422-byte exports.
    """
    where = _game_dirs().get("Pools of Darkness")
    if where is None:
        pytest.skip("needs the Pools of Darkness archive; set FR_ARCHIVES")
    out = [p for p in sorted(where.rglob("*.SAV"))
           if p.stat().st_size == POD.record_size]
    if not out:
        pytest.skip("no Pools of Darkness records in the archive")
    return out


def _mask(original: bytes) -> set[int]:
    """The offsets the writer declares it does not take from the source.

    Built from the writer's own tables, so a new difference fails -- the
    thing `.claude/rules/conversions.md` asks for. The name padding past the
    count byte goes in too: the neutral record carries a *name*, not the
    bytes the engine left after it.
    """
    table = dos_layout.FIELDS_BY_NAME_FOR[POD.key]
    out: set[int] = set()
    named = ([n for n, _ in dos.WRITE_UNSOURCED + dos.WRITE_UNSOURCED_LATER]
             + [n for n, _, _, _ in dos.WRITE_DEFAULTS
                if n != "field_10c_10f"]
             + [n for n, _ in dos.WRITE_DERIVED])
    for name in named:
        if name in table:
            out.update(range(table[name].offset, table[name].end))
    text = table["name_text"]
    out.update(range(text.offset + original[table["name_length"].offset],
                     text.end))
    return out


# --- the title is convertible at all -----------------------------------------

def test_the_title_reads_and_writes_now_that_it_has_a_second_port():
    """`to_neutral` and `write` both refused this title by name until the
    Amiga became its destination."""
    assert POD in dos.CONVERTS
    assert POD in dos.WRITES
    rec, _itm, _spc, _rep = dos.write(
        neutral.NeutralCharacter("test", source="made up", game=POD.key))
    assert len(rec) == POD.record_size


# --- the round trip ----------------------------------------------------------

def test_every_shipped_record_round_trips_outside_the_declared_mask():
    """**12 of 12 read and write back**, and the two that differ do so in one
    field each and are named:

    * eight records differ in `field_83_87`'s treasure-share byte, which the
      writer writes as the documented constant `1`. The split is by save
      slot -- four of slot A's six hold 1 and none of slot B's -- which is
      the same shape Pool of Radiance's own corpus has, where the byte
      records that somebody pressed KEEP in MODIFY CHARACTER and reads 0 in
      45 of the 54 records this project rolled itself (`FIELD_83_87`).
    * **PAINE differs in `spellbook`**, at the one byte in the whole DOS
      corpus that is neither 0 nor 1: spell 118 holds 8, where all 4,016 set
      spellbook bytes in 476 records hold 1. The neutral `spells_known` is a
      list of ids and has nowhere to keep an 8.
    """
    seen = clean = share = book = 0
    for path in _records():
        char = dos.read_character(path)
        rec, itm, spc, _rep = dos.write(dos.to_neutral(char))
        assert len(rec) == POD.record_size
        assert len(itm) == len(char.items) * POD.item_size
        original = char.to_bytes()
        differs = {i for i in range(len(original))
                   if original[i] != rec[i] and i not in _mask(original)}
        seen += 1
        if not differs:
            clean += 1
            continue
        fields = {f.name for f in dos_layout.LAYOUTS[POD.key]
                  for i in differs if f.offset <= i < f.end}
        assert fields <= {"field_83_87", "spellbook"}, (path.name,
                                                        sorted(fields))
        share += "field_83_87" in fields
        book += "spellbook" in fields
        if "spellbook" in fields:
            assert char.name == "PAINE", path.name
    assert seen >= 12, f"{seen} Pools of Darkness records"
    assert clean + share + book == seen
    assert book <= 1, f"{book} records differ in the spellbook"


def test_the_effect_file_comes_back_byte_for_byte():
    """12 of 12, and it was 1 of 12 before this title got its own innate set
    and its own (empty) racial table.

    Six of the twelve have an `.EFX` at all and the other six have none --
    which is a state the writer has to reproduce, since `#62` measured that
    an empty file and no file are not the same thing to the DOS engine.
    """
    seen = exact = withfile = 0
    for path in _records():
        char = dos.read_character(path)
        _rec, _itm, spc, _rep = dos.write(dos.to_neutral(char))
        efx = path.with_suffix(POD.effect_suffix)
        original = efx.read_bytes() if efx.exists() else b""
        seen += 1
        withfile += bool(original)
        exact += spc == original
        assert spc == original, (path.name, original.hex(), spc.hex())
    assert seen >= 12
    assert exact == seen
    assert withfile, "no record here carries an effect file at all"


def test_the_item_records_come_back_past_their_text():
    """The same claim `tests/test_doswriter.py` makes for Pool of Radiance:
    everything from `type_index` on is the source's own, record for record.

    **The 42 bytes of item text are not converted, in any title**, because
    the neutral inventory is the shared sixteen-byte item shape and has no
    room for the DOS engine's rendered name. That is not this title's
    problem and is not fixed here.
    """
    seen = 0
    for path in _records():
        char = dos.read_character(path)
        _rec, itm, _spc, _rep = dos.write(dos.to_neutral(char))
        for n, item in enumerate(char.items):
            ours = itm[n * POD.item_size:(n + 1) * POD.item_size]
            assert ours[0x02E:] == item.to_bytes()[0x02E:], (path.name, n)
        seen += 1
    assert seen >= 12


# --- the two undecoded runs that are not zero --------------------------------

def test_the_two_unnamed_runs_are_declared_rather_than_left_as_gaps():
    """A `gap_` is written zero, and no Pools of Darkness record holds zero
    at `0x1A4`. Naming them is what puts them in front of the writer."""
    table = dos_layout.FIELDS_BY_NAME_FOR[POD.key]
    assert table["unnamed_1a4"].offset == 0x1A4
    assert table["unnamed_1a4"].size == 2
    assert table["unnamed_1e0"].offset == 0x1E0
    assert table["unnamed_1e0"].size == 1
    # Only this title has either, so no other title's record moves.
    for shape in (POOL, dos_layout.CURSE_OF_THE_AZURE_BONDS, SSB):
        other = dos_layout.FIELDS_BY_NAME_FOR[shape.key]
        assert "unnamed_1a4" not in other
        assert "unnamed_1e0" not in other


def test_the_pair_at_0x1a4_is_the_measured_constant_in_every_record():
    """`02 02` in 24 of 24 -- twelve characters found under both archive
    paths -- and the writer puts the same pair back rather than the zero a
    gap would get.

    **Not the icon's size**: ABAGAIL is the one character of the twelve whose
    `size` byte is 1 rather than 2, and she holds `02 02` like everybody
    else.
    """
    f = dos_layout.FIELDS_BY_NAME_FOR[POD.key]["unnamed_1a4"]
    small = 0
    for path in _records():
        raw = path.read_bytes()
        assert raw[f.span] == b"\x02\x02", path.name
        char = dos.read_character(path)
        if char.get("size") == 1:
            small += 1
            _rec, _itm, _spc, _rep = dos.write(dos.to_neutral(char))
    assert small, "no small character here, so the size reading is untested"
    assert ("unnamed_1a4", b"\x02\x02") in [
        (n, v) for n, v, _ in dos.write_constants(POD)]
    assert "unnamed_1a4" not in [n for n, _, _ in dos.write_constants(POOL)]


def test_the_byte_at_0x1e0_is_written_at_the_value_twenty_of_them_hold():
    """0 in 20 of 24 and 2 in the four that are ABAGAIL and BRYTWYN. One
    byte, two characters, no third value, so it is a measured default rather
    than a constant -- and a default is masked out of the round trip, which
    is why the two who hold 2 do not show up as a failure above.
    """
    f = dos_layout.FIELDS_BY_NAME_FOR[POD.key]["unnamed_1e0"]
    held: dict[str, set[int]] = {}
    for path in _records():
        char = dos.read_character(path)
        held.setdefault(char.name, set()).add(path.read_bytes()[f.offset])
    values = {v for s in held.values() for v in s}
    assert values <= {0, 2}, sorted(values)
    assert {n for n, s in held.items() if s != {0}} == {"ABAGAIL", "BRYTWYN"}
    assert ("unnamed_1e0", b"\x00") in [
        (n, v) for n, v, _, _ in dos.WRITE_DEFAULTS]


# --- the race table this title never had -------------------------------------

def test_the_race_is_read_through_the_titles_own_numbering():
    """The defect this closed: `goldbox/games.py` has never heard of Pools of
    Darkness, so `games.BY_KEY` answered `None` and `games.race_table` then
    handed back **Pool of Radiance's** numbering -- under which this title's
    race 5, the human ten of its twelve pregens are, read as a halfling and
    collected the halfling's two innate records.

    `#470 (Give the project a neutral title beside its neutral character
    record, with one port per platform a title shipped on)`'s stage 2 points
    `_race_combat_effects` at `goldbox.titles.race_table`, which -- unlike
    `games.race_table` -- has a Pools of Darkness row, so the bug is closed
    even with no `DosShape` in hand: passing one is no longer what makes
    this title's own numbering apply, it is what lets the record's own byte
    win at the handful of codes where a title's rules-level `races` and its
    DOS executable's own string table disagree (`goldbox.dos_layout.DosShape.
    race_numbers`, `#237`) -- and Pools of Darkness has no such disagreement,
    its `races` tuple being built from that very table. This is `#293`'s bug
    one title along.
    """
    from goldbox import games
    assert games.BY_KEY.get(POD.key) is None
    # Correct without a shape now: titles.py knows this title's race 5 is
    # the human, who gets nothing.
    assert dos._race_combat_effects(POD.key, 5) == ()
    assert dos._race_combat_effects(POD.key, 5, POD) == ()
    # And the change is inert for the three titles `games` does know.
    for shape in (POOL, dos_layout.CURSE_OF_THE_AZURE_BONDS, SSB):
        for race in range(len(shape.race_numbers)):
            assert dos._race_combat_effects(shape.key, race, shape) == \
                dos._race_combat_effects(shape.key, race), (shape.key, race)


def test_no_racial_record_is_invented_for_this_title():
    """The empty table is the finding. Six of the twelve records have an
    `.EFX` and every one holds a single id that is a class ability or the
    elf's -- 8 for the two paladins, 105 for the four rangers, 95 for the one
    elf -- and the six with no file at all include a half-elf, whom both
    earlier titles' tables give an id.

    So the claim is negative and narrow: nothing measured supports handing a
    converted Pools of Darkness character a racial record. What would build a
    table is `#84`'s experiment run against this title -- roll one character
    of each race in its own creation screens and read the `.EFX`.
    """
    assert dos.RACE_COMBAT_EFFECTS_POOLS_OF_DARKNESS == {}
    for race in range(len(POD.race_numbers)):
        assert dos._race_combat_effects(POD.key, race, POD) == ()


def test_the_innate_ids_are_the_later_engines_and_not_pool_of_radiances():
    """8 the paladin's, 105 the ranger's -- both already Silver Blades' --
    and 95 the elf's, which is Silver Blades' own elf seed. PROBABLE: twelve
    shipped records with no chain of custody, one elf and one half-elf
    between them.
    """
    ours = dos._innate_effects(POD.key)
    assert {8, 95, 105} <= ours
    assert dos.INNATE_EFFECTS <= ours
    assert 95 not in dos.INNATE_EFFECTS
    seen: set[int] = set()
    for path in _records():
        efx = path.with_suffix(POD.effect_suffix)
        if not efx.exists():
            continue
        raw = efx.read_bytes()
        assert len(raw) % dos_layout.EFFECT_SIZE == 0, path.name
        for at in range(0, len(raw), dos_layout.EFFECT_SIZE):
            seen.add(raw[at])
            # Every one is the innate payload, which is what lets the writer
            # put the record back from an id alone.
            assert raw[at + 1:at + 5] == dos.INNATE_PAYLOAD, path.name
    assert seen == {8, 95, 105}, sorted(seen)


# --- the tables, which need no save ------------------------------------------

def test_the_record_has_no_field_for_seven_neutral_names():
    """The one reason `.claude/rules/conversions.md` allows -- the
    destination has no such field -- established by reading the layout rather
    than assumed. The later engine keeps three money slots where the earlier
    three keep seven, keeps no drained-level pair, and drops the creature's
    experience-per-hit-point rate.
    """
    absent = dict(dos.write_absent(POD))
    assert set(absent) == set(ABSENT)
    for name, why in absent.items():
        assert why.startswith(POD.title), name
    # Nothing is absent from the three titles that declare everything.
    for shape in (POOL, dos_layout.CURSE_OF_THE_AZURE_BONDS, SSB):
        assert dos.write_absent(shape) == ()


def test_an_absent_field_is_reported_as_dropped_and_never_copied():
    """A neutral character carrying gold and a drained level converts into
    this title's record without raising, and the seven names come back as
    drops rather than as bytes written over the field that follows.

    **No conversion reaches this today**: the only other Pools of Darkness
    port is the Amiga and `goldbox.amiga.PodCharacter` reads only platinum,
    gems and jewelry too, so a source carrying gold into this title would
    have to be a fourth port nobody has. It is tested because the writer must
    not be the thing that discovers it.
    """
    char = neutral.NeutralCharacter("test", source="made up", game=POD.key)
    char.set("name", "TESTER", "made up")
    for name in ABSENT:
        char.set(name, 7, "made up")
    rec, _itm, _spc, rep = dos.write(char)
    assert len(rec) == POD.record_size
    for name in ABSENT:
        assert any(line.startswith(f"{name}:") for line in rep.dropped), name
    disposition = dos.write_field_disposition(POD)
    for name in ABSENT:
        assert disposition[name].startswith("dropped:"), name
        assert dos.write_field_disposition(POOL)[name].startswith("copied")


def test_every_field_and_every_neutral_name_is_accounted_for():
    """The two completeness checks the other titles get, asked of this one:
    a DOS field named nowhere would be a byte written in silence, and a
    neutral field named nowhere would be one dropped in silence.
    """
    declared = {f.name for f in dos_layout.LAYOUTS[POD.key]
                if not f.name.startswith("gap_")}
    assert declared - set(dos.write_targets(POD)) == set()
    assert declared - set(dos.field_disposition(POD)) == set()
    assert set(dos.field_disposition(POD)) - declared == set()
    assert neutral.undeclared(neutral.FIELDS,
                              dos.write_field_disposition(POD)) == (set(),
                                                                    set())


def test_no_sheet_portrait_is_reported_for_a_title_that_has_none():
    """Pools of Darkness has no sheet portrait on either port -- neither
    ships the art, the 510-byte shape gives the pair a width of zero, and the
    creation menu is cut out of the Amiga engine's own copy of the data block
    that carries it (`#194`, `#451`).

    So a converted character must not be told a portrait could not be
    matched, which is a sentence about a feature the game does not have.
    """
    table = dos_layout.FIELDS_BY_NAME_FOR[POD.key]
    assert "portrait_head" not in table
    assert "portrait_body" not in table
    for path in _records():
        out = dos.to_neutral(dos.read_character(path))
        assert not any("portrait" in line.lower() for line in out.dropped), \
            path.name
