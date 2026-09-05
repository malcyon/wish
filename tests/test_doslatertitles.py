from __future__ import annotations

"""Writing a DOS record for a title that is not Pool of Radiance (#299).

`tests/test_doswriter.py` proves the writer against the 285-byte record.  This
module proves the same writer against the **422-byte Curse of the Azure Bonds
record and the 439-byte Secret of the Silver Blades one**, which is the whole
of `#299 (goldbox.dos.write builds only Pool of Radiance's record, so nothing
can be converted to DOS for the later titles)`: before it, a Curse or Silver
Blades character handed to `goldbox.dos.write` came back as 285 bytes of Pool
of Radiance, silently, and no Curse or Silver Blades game could ever have
loaded it.

Three kinds of test here, in order of how much they are worth.

* **The round trip**, over every record on the machine -- a DOS record read
  into the neutral middle and written out again, byte for byte outside the
  writer's own declared mask.  The mask is `goldbox.dos.WRITE_UNSOURCED`,
  `WRITE_UNSOURCED_LATER`, `WRITE_DEFAULTS` and `WRITE_DERIVED`, never
  whatever happened to differ.
* **The shape**, which needs no save at all: the width of every field the
  writer fills comes off `goldbox/dos_layout.py`'s table for the title, so a
  63-byte item stride or a 56-spell book cannot be hard-coded back in.
* **The tables**, which say the writer accounts for every field of every
  title it will write.

**The saves are Donald's, not the repository's.**  The specimen tree is
`~/wish-specimens`, `tests/gamedata.py` reaches it, and everything here skips
without it -- which is what CI does.
"""

import pathlib

import pytest
from gamedata import specimen, specimen_root
from test_dossave import _save_dir

from goldbox import c64_codec, dos, dos_layout, items, neutral
from goldbox.d64 import D64
from goldbox.savegame import load_save

CURSE = dos_layout.CURSE_OF_THE_AZURE_BONDS
SSB = dos_layout.SECRET_OF_THE_SILVER_BLADES
POOL = dos_layout.POOL_OF_RADIANCE
POD = dos_layout.POOLS_OF_DARKNESS

LATER = (CURSE, SSB)


# --- the tables: every field of every title has a target ---------------------

@pytest.mark.parametrize("shape", dos.WRITES, ids=lambda s: s.key)
def test_write_targets_tile_every_title_this_writer_writes(shape):
    """The promise `test_write_targets_tile_the_dos_layout` makes for Pool of
    Radiance, made for all three: a field a title declares and the writer
    names nowhere is a byte written or zeroed in silence."""
    declared = {f.name for f in dos_layout.LAYOUTS[shape.key]
                if not f.name.startswith("gap_")}
    targets = dos.write_targets(shape)
    assert declared - set(targets) == set()
    assert set(targets) - declared == set()


def test_pool_of_radiances_targets_are_the_module_constant():
    """`WRITE_TARGETS` is still Pool of Radiance's account, unchanged, so
    nothing that read it before #299 changed meaning."""
    assert dos.write_targets(POOL) == dos.WRITE_TARGETS
    assert dos.write_targets() == dos.WRITE_TARGETS


@pytest.mark.parametrize("shape", dos.WRITES, ids=lambda s: s.key)
def test_every_neutral_field_has_a_write_disposition_in_every_title(shape):
    assert neutral.undeclared(neutral.FIELDS,
                              dos.write_field_disposition(shape)) \
        == (set(), set())


@pytest.mark.parametrize("shape", LATER, ids=lambda s: s.key)
def test_the_later_titles_convert_what_pool_of_radiance_drops(shape):
    """Two fields are a loss in Pool of Radiance and a conversion here: the
    second copy of each ability score, and the class a dual-classed character
    left."""
    later = dos.write_field_disposition(shape)
    pool = dos.write_field_disposition(POOL)
    for name in ("abilities_second", "former_levels"):
        assert pool[name].startswith("dropped:"), name
        assert not later[name].startswith("dropped:"), name


# --- which record gets built --------------------------------------------------

def _neutral(game, **fields) -> neutral.NeutralCharacter:
    """A neutral character for `game` carrying only what a test names."""
    char = neutral.NeutralCharacter("test", source="made up", game=game)
    for name, value in fields.items():
        char.set(name, value, "made up for the test")
    return char


@pytest.mark.parametrize("shape", dos.WRITES, ids=lambda s: s.key)
def test_the_record_is_the_characters_own_titles(shape):
    """The bug #299 names, at its root: the title comes off the character,
    not off the writer.  A Curse character used to come back as 285 bytes."""
    rec, _itm, _spc, _rep = dos.write(_neutral(shape.key, name="TESTER"))
    assert len(rec) == shape.record_size


def test_a_character_with_no_title_is_pool_of_radiances():
    """`game=None` is what a caller with no title in hand means, and it has
    always meant Pool of Radiance."""
    rec, _, _, _ = dos.write(_neutral(None, name="TESTER"))
    assert len(rec) == POOL.record_size


def test_a_games_object_names_the_title_as_well_as_its_key():
    from goldbox import games

    rec, _, _, _ = dos.write(_neutral(games.BY_KEY[CURSE.key], name="X"))
    assert len(rec) == CURSE.record_size


def test_pools_of_darkness_is_refused_rather_than_written():
    """Its shape reads and nobody has written one; there is no C64 Pools of
    Darkness to convert from, so a request for one is a caller's mistake."""
    with pytest.raises(dos.WrongTitleError) as exc:
        dos.write(_neutral(POD.key, name="X"))
    assert POD.title in str(exc.value)


def test_a_title_with_no_dos_record_says_so():
    with pytest.raises(dos_layout.DosShapeError):
        dos.write(_neutral("champions-of-krynn", name="X"))


def test_an_explicit_shape_overrides_the_characters_own():
    rec, _, _, _ = dos.write(_neutral(None, name="X"), shape=SSB)
    assert len(rec) == SSB.record_size


# --- the widths that are the title's and not the writer's ---------------------

def test_the_spellbook_is_the_titles_own_id_space():
    """56 ids in Pool of Radiance, 100 in Curse, 117 in Silver Blades --
    `goldbox/spells.py`'s three id spaces.  Spell 100 fits in Curse's book and
    is warned about in Pool of Radiance's."""
    rec, _, _, rep = dos.write(_neutral(CURSE.key, spells_known=[1, 100]))
    book = dos_layout.FIELDS_BY_NAME_FOR[CURSE.key]["spellbook"]
    assert book.size == 100
    assert rec[book.offset] == 1 and rec[book.end - 1] == 1
    assert not any("outside" in w for w in rep.warnings)

    _rec, _, _, rep = dos.write(_neutral(POOL.key, spells_known=[1, 100]))
    assert any("Spell id 100 is outside" in w for w in rep.warnings)


def test_the_memorised_list_fills_from_the_end_of_the_titles_own_run():
    """16 slots in Pool of Radiance, 84 in Curse, 75 in Silver Blades, and
    the ids go against the *end* in every one of them."""
    for shape, slots in ((POOL, 16), (CURSE, 84), (SSB, 75)):
        f = dos_layout.FIELDS_BY_NAME_FOR[shape.key]["spells_memorised"]
        assert f.size == slots
        rec, _, _, _ = dos.write(_neutral(shape.key, spells_memorised=[9, 3]))
        assert rec[f.end - 2:f.end] == bytes((3, 9))
        assert rec[f.offset:f.end - 2] == bytes(slots - 2)


def test_the_level_array_is_seven_slots_in_silver_blades():
    """It drops the monk's, so a monk level is reported by name rather than
    written over the byte that follows the array."""
    monk = _neutral(SSB.key, levels={"monk": 5})
    rec, _, _, rep = dos.write(monk)
    f = dos_layout.FIELDS_BY_NAME_FOR[SSB.key]["class_levels"]
    assert f.size == 7
    assert rec[f.offset:f.end] == bytes(7)
    assert any("monk level 5" in w and "no monk slot" in w
               for w in rep.warnings), rep.warnings
    # Curse keeps eight, so the same character loses nothing there.
    rec, _, _, rep = dos.write(_neutral(CURSE.key, levels={"monk": 5}))
    g = dos_layout.FIELDS_BY_NAME_FOR[CURSE.key]["class_levels"]
    assert rec[g.offset + 7] == 5
    assert not rep.warnings


def test_the_spell_slot_arrays_are_three_five_and_seven_levels_deep():
    slots = {"cleric": (5, 4, 3, 2, 1, 1, 1), "druid": (1, 1, 0, 0, 0, 0, 0),
             "magic-user": (4, 3, 2, 1, 0, 0, 0)}
    for shape, depth in ((POOL, 3), (CURSE, 5), (SSB, 7)):
        rec, _, _, rep = dos.write(_neutral(shape.key, spells_castable=slots))
        table = dos_layout.FIELDS_BY_NAME_FOR[shape.key]
        f = table["spells_castable_cleric"]
        assert f.size == depth
        assert rec[f.offset:f.end] == bytes(slots["cleric"][:depth])
        if shape is POOL:
            # Pool of Radiance has no druid array and says so.
            assert "spells_castable_druid" not in table
            assert any("no druid spell-slot array" in d for d in rep.dropped)
            assert any("5 levels deep" in w or "7 levels deep" in w
                       for w in rep.warnings), rep.warnings
        else:
            d = table["spells_castable_druid"]
            assert rec[d.offset:d.end] == bytes(slots["druid"][:depth])


def test_silver_blades_items_are_sixty_seven_bytes_with_a_measured_zero_tail():
    """`#113 (Play DOS Curse far enough to save a party with items)` is the
    trap this writer must not walk into: the stride is 63 in three titles and
    67 in Silver Blades, and it comes off the shape."""
    one = bytes(range(16))
    for shape in dos.WRITES:
        _rec, itm, _spc, _rep = dos.write(
            _neutral(shape.key, inventory=[one]))
        assert len(itm) == shape.item_size, shape.key
    _rec, itm, _, _ = dos.write(_neutral(SSB.key, inventory=[one]))
    assert len(itm) == 67
    at, size = dos.ITEM_TAIL
    assert itm[at:at + size] == bytes(size)
    # Every field below the tail is where the other titles put it, so the
    # 63-byte projection is a prefix of the 67-byte one.
    _rec, short, _, _ = dos.write(_neutral(CURSE.key, inventory=[one]))
    assert itm[:63] == short


def test_experience_is_four_bytes_in_the_later_titles():
    """Three in Pool of Radiance and four after, so a total Pool of Radiance
    cannot hold survives in the titles that can."""
    big = 0x00FF_FFFF + 1
    rec, _, _, _ = dos.write(_neutral(CURSE.key, experience=big))
    f = dos_layout.FIELDS_BY_NAME_FOR[CURSE.key]["experience"]
    assert f.size == 4
    assert int.from_bytes(rec[f.offset:f.end], "little") == big
    with pytest.raises(ValueError):
        dos.write(_neutral(POOL.key, experience=big))


# --- the fields only the later titles have ------------------------------------

def test_each_ability_is_written_as_a_current_and_base_pair():
    """From Curse on, every ability is two bytes.  `abilities_second` fills
    the second; a source with none writes the one value into both, which is
    what every record measured holds."""
    for shape in LATER:
        table = dos_layout.FIELDS_BY_NAME_FOR[shape.key]
        rec, _, _, _ = dos.write(_neutral(shape.key, strength=15))
        f = table["strength"]
        assert f.size == 2
        assert rec[f.offset:f.end] == bytes((15, 15))

        rec, _, _, _ = dos.write(_neutral(
            shape.key, strength=12, abilities_second={"strength": 18}))
        assert rec[f.offset:f.end] == bytes((12, 18))


def test_a_second_ability_copy_is_reported_where_the_title_keeps_one():
    _rec, _, _, rep = dos.write(_neutral(
        POOL.key, strength=12, abilities_second={"strength": 18}))
    assert any("abilities_second" in d and "one copy" in d
               for d in rep.dropped), rep.dropped


def test_the_class_a_dual_classed_character_left_is_written_twice():
    """`#234 (A dual-classed Curse or Silver Blades character converted to
    DOS loses the class he trained out of)`: the later titles keep it in a
    second level array *and* in the byte after `level`, and both come from
    the one neutral value."""
    for shape in LATER:
        table = dos_layout.FIELDS_BY_NAME_FOR[shape.key]
        rec, _, _, rep = dos.write(_neutral(
            shape.key, levels={"cleric": 1}, former_levels={"paladin": 5}))
        array = table["former_class_levels"]
        assert rec[array.offset + 3] == 5          # the paladin's slot
        assert rec[table["former_level"].offset] == 5
        assert not rep.warnings


def test_two_former_classes_keep_the_array_and_say_the_byte_holds_one():
    rec, _, _, rep = dos.write(_neutral(
        CURSE.key, levels={"cleric": 1},
        former_levels={"paladin": 5, "fighter": 3}))
    table = dos_layout.FIELDS_BY_NAME_FOR[CURSE.key]
    array = table["former_class_levels"]
    assert rec[array.offset + 3] == 5 and rec[array.offset + 2] == 3
    assert rec[table["former_level"].offset] == 5
    assert any("holds one" in w for w in rep.warnings), rep.warnings


def test_pool_of_radiance_reports_a_former_class_it_cannot_hold():
    _rec, _, _, rep = dos.write(_neutral(
        POOL.key, levels={"cleric": 1}, former_levels={"paladin": 5}))
    assert any("former_levels" in d and "no former-class level array" in d
               for d in rep.dropped), rep.dropped


@pytest.mark.parametrize("shape", LATER, ids=lambda s: s.key)
def test_a_paladin_gets_the_byte_every_engine_written_paladin_holds(shape):
    """`paladin_cures` is 1 for every paladin in every engine-written record
    and 0 for everybody else, and the C64 has no byte to convert it from, so
    the writer derives it from the class.

    **The rule is "write what the engine writes"** rather than "give the
    paladin his cure back": staged 0 and staged 2 on a paladin in the running
    Silver Blades game, the sheet offers CURE either way and one use ends the
    offer, so the byte does not gate the command in that title (#299).  What
    it does do there is get cleared by a cure -- a staged 2 came back 0 in the
    engine's own resave.
    """
    f = dos_layout.FIELDS_BY_NAME_FOR[shape.key]["paladin_cures"]
    paladin, _, _, _ = dos.write(_neutral(shape.key, levels={"paladin": 5}))
    assert paladin[f.offset] == 1
    fighter, _, _, _ = dos.write(_neutral(shape.key, levels={"fighter": 5}))
    assert fighter[f.offset] == 0
    # And it stays set for a paladin who has been through HUMAN CHANGE
    # CLASSES, which is what DEMELTINA's own record does.
    former, _, _, _ = dos.write(_neutral(
        shape.key, levels={"cleric": 1}, former_levels={"paladin": 5}))
    assert former[f.offset] == 1


def test_pool_of_radiance_has_no_paladin_cures_byte():
    assert "paladin_cures" not in dos_layout.FIELDS_BY_NAME


def test_silver_blades_fourth_slot_array_is_written_zero_and_declared():
    """Zero in 44 of 44 records and attributed to nobody, so it is named in
    `WRITE_UNSOURCED_LATER` and masked by that name rather than by luck."""
    f = dos_layout.FIELDS_BY_NAME_FOR[SSB.key]["spells_castable_unattributed"]
    rec, _, _, _ = dos.write(_neutral(SSB.key, name="X"))
    assert rec[f.offset:f.end] == bytes(f.size)
    assert "spells_castable_unattributed" in {
        n for n, _ in dos.WRITE_UNSOURCED_LATER}


def test_the_later_titles_draw_no_sheet_portrait():
    """`portrait_head` and `portrait_body` are 0 in all 32 Curse and all 44
    Silver Blades records here, so a menu position written there would be a
    number the sheet never draws."""
    for shape in LATER:
        table = dos_layout.FIELDS_BY_NAME_FOR[shape.key]
        rec, _, _, rep = dos.write(_neutral(shape.key, portrait_head=0x2D,
                                            portrait_body=0x01))
        assert rec[table["portrait_head"].offset] == 0
        assert rec[table["portrait_body"].offset] == 0
        assert any("draws no portrait" in d for d in rep.dropped), rep.dropped


def test_the_identity_byte_is_digested_at_the_titles_own_offset():
    """`unnamed_0ab` is at 0x0AB, 0x126 and 0x12B; a Pool of Radiance offset
    used on a Curse record would blank a byte of the money block."""
    for shape in dos.WRITES:
        f = dos_layout.FIELDS_BY_NAME_FOR[shape.key]["unnamed_0ab"]
        rec, _, _, _ = dos.write(_neutral(shape.key, name="DUPLICO"))
        assert rec[f.offset] == dos.identity_byte(rec, shape)
        assert rec[f.offset] == dos.identity_byte(rec)     # size names it


def test_the_report_accounts_for_every_byte_of_every_title():
    """Every byte of the record and of both payloads has a provenance line,
    for a character carrying something in every field the writer takes."""
    from test_neutral import _filled

    for shape in dos.WRITES:
        char = _filled(shape.key)
        char.set("abilities_second", {"strength": 18}, "made up")
        char.set("former_levels", {"paladin": 5}, "made up")
        _rec, itm, spc, rep = dos.write(char)
        assert rep.unaccounted == [], (shape.key, rep.unaccounted[:8])
        assert rep.total == shape.record_size + len(itm) + len(spc)


# --- the sibling files carry the title's own names ---------------------------

def test_the_item_and_effect_files_are_named_per_title():
    """Curse keeps items in `.SWG` and effects in `.FX`, Silver Blades in
    `.STF` and `.SFX`, and the report names the file rather than saying
    `.ITM` for all three."""
    assert (CURSE.item_suffix, CURSE.effect_suffix) == (".SWG", ".FX")
    assert (SSB.item_suffix, SSB.effect_suffix) == (".STF", ".SFX")
    _rec, _itm, _spc, rep = dos.write(
        _neutral(SSB.key, inventory=[bytes(16)], race=3))
    assert any(".STF" in s for s in rep.sources.values())
    assert any(".SFX" in s for s in rep.sources.values())


# --- the round trip, over every record on the machine ------------------------

SPECIMENS = ("curse-234-before", "curse-234-dualclassed",
             "curse-234-party-dualclassed", "ssb-234-before",
             "ssb-234-dualclassed", "ssb-234-party-pair",
             "ssb-slote-zeroed140")


def _mask(shape, original: bytes) -> set[int]:
    """The offsets the writer declares it does not take from the source, plus
    the name bytes past the count byte.

    Built from the writer's own tables and never from the diff, which is what
    `.claude/rules/conversions.md` requires: a new difference has to fail.
    The name padding is masked because the neutral record carries a *name* and
    not the bytes the engine left after it -- Curse's shipped TRAVIS has a
    space at the seventh byte over a count of six.
    """
    table = dos_layout.FIELDS_BY_NAME_FOR[shape.key]
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


def _records_of(shape, dirs):
    for where in dirs:
        for path in sorted(where.rglob("*")):
            if path.is_file() and path.stat().st_size == shape.record_size:
                yield path


def _specimen_dirs():
    return [specimen(name) for name in SPECIMENS]


@pytest.mark.parametrize("shape", LATER, ids=lambda s: s.key)
def test_every_engine_written_record_of_a_later_title_round_trips(shape):
    """DOS -> `to_neutral` -> `write`, against the original bytes.

    **Curse: 8 of 8 identical outside the mask.  Silver Blades: 17 of 20**,
    and the three that differ are the same character -- MALACHITE, whose
    treasure-share byte inside `field_83_87` reads 0 where every other record
    of the title reads 1 (`#304 (field_83_87 is written as a constant that the
    characters we rolled ourselves do not hold)`).  Every record here was
    written by the DOS engine under DOSBox for `#234` and `#256`.
    """
    if specimen_root() is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    seen = clean = 0
    exceptions: list[str] = []
    for path in _records_of(shape, _specimen_dirs()):
        char = dos.read_character(path)
        rec, itm, spc, _rep = dos.write(dos.to_neutral(char))
        assert len(rec) == shape.record_size
        assert len(itm) == len(char.items) * shape.item_size
        assert len(spc) % dos_layout.EFFECT_SIZE == 0
        original = char.to_bytes()
        mask = _mask(shape, original)
        differs = {i for i in range(len(original))
                   if original[i] != rec[i] and i not in mask}
        seen += 1
        if not differs:
            clean += 1
            continue
        fields = {f.name for f in dos_layout.LAYOUTS[shape.key]
                  for i in differs if f.offset <= i < f.end}
        exceptions.append(f"{char.name} ({path.name}): {sorted(fields)}")
        assert fields == {"field_83_87"}, exceptions[-1]
        assert char.name == "MALACHITE", exceptions[-1]
    assert seen >= 8, f"{seen} {shape.title} records"
    if shape is CURSE:
        assert clean == seen, exceptions
    else:
        assert clean == seen - len(exceptions)
        assert len(exceptions) <= 3, exceptions


def test_the_shipped_records_of_the_later_titles_round_trip_too():
    """The archives are a template rather than evidence -- nobody knows who
    wrote them -- but what goes in comes back out, and the input's provenance
    does not enter that claim.  24 of 24 Curse records and 22 of 24 Silver
    Blades ones, the two exceptions being MALACHITE again.

    **Only the two titles' own directories**, and by name: Gateway to the
    Savage Frontier's `.GUY` exports are 422 bytes and Treasures of the
    Savage Frontier's records are 510, so a sweep of the whole archive by
    size reads two games this project does not convert (`shape_for`'s own
    docstring says the size names the shape and the directory names the
    game).
    """
    if _save_dir() is None:
        pytest.skip("needs the DOS archives; set FR_ARCHIVES")
    from test_dossave import _game_dirs

    where = _game_dirs()
    roots = {CURSE.key: where.get("CURSE"), SSB.key: where.get("SECRET")}
    if not all(roots.values()):
        pytest.skip("needs the CURSE and SECRET archive folders")
    counts = {CURSE.key: [0, 0], SSB.key: [0, 0]}
    for shape in LATER:
        for path in _records_of(shape, [roots[shape.key]]):
            char = dos.read_character(path)
            if char.shape is not shape:
                continue
            rec, _itm, _spc, _rep = dos.write(dos.to_neutral(char))
            original = char.to_bytes()
            mask = _mask(shape, original)
            differs = {i for i in range(len(original))
                       if original[i] != rec[i] and i not in mask}
            counts[shape.key][1] += 1
            if not differs:
                counts[shape.key][0] += 1
            else:
                fields = {f.name for f in dos_layout.LAYOUTS[shape.key]
                          for i in differs if f.offset <= i < f.end}
                assert fields == {"field_83_87"}, (path, sorted(fields))
    for key, (clean, seen) in counts.items():
        assert seen >= 12, f"{key}: only {seen} records"
        assert clean >= seen - 3, f"{key}: {clean} of {seen}"


# --- the C64 to DOS direction, which did not exist before #299 ---------------

def _c64_disk(name: str):
    root = specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    found = [p for p in (root / "por-c64").glob(f"WISH-SPEC-{name}.[dD]64")]
    if not found:
        pytest.skip(f"needs the C64 specimen WISH-SPEC-{name}")
    return found[0]


def _c64_party(path: pathlib.Path):
    disk = D64.open(str(path))
    game, sg0, sg1 = load_save(disk)
    out = []
    for slot in sg0.characters:
        block = sg1.roster(slot.index) if sg1 is not None else None
        inv = [i.raw for i in items.items_for_slot(sg0.to_bytes(), slot.index)]
        out.append(c64_codec.read(slot.record, roster=block, inventory=inv,
                                  game=game, source=f"slot {slot.index}"))
    return game, out


@pytest.mark.parametrize("name, shape, expect_items", [
    ("curse-h-engine-resave", CURSE, False),
    ("ssb-d-engine-resave", SSB, True),
])
def test_a_c64_party_converts_to_its_own_titles_dos_records(
        name, shape, expect_items):
    """The four directions `#51 (Every permutation of DOS, C64 and Amiga, in
    both directions)` ends at, measured on the two C64 saves the **C64 engine
    itself** wrote after loading a party this project converted (`#192`,
    `#193`).

    Before #299 every one of these came back as 285 bytes of Pool of
    Radiance, which no Curse or Silver Blades game could load.
    """
    _game, party = _c64_party(_c64_disk(name))
    assert len(party) == 6
    carried = 0
    for char in party:
        rec, itm, spc, _rep = dos.write(char)
        assert len(rec) == shape.record_size, char.get("name")
        assert len(itm) % shape.item_size == 0
        assert len(spc) % dos_layout.EFFECT_SIZE == 0
        carried += bool(itm)
        if itm:
            # Silver Blades' twelve magic items are 804 bytes at 67 apiece,
            # which is the number #113 measured in the running game and which
            # 63 does not divide.
            assert len(itm) // shape.item_size == len(char.get("inventory"))
    assert bool(carried) is expect_items


def test_a_silver_blades_party_carries_its_items_at_the_measured_stride():
    _game, party = _c64_party(_c64_disk("ssb-d-engine-resave"))
    sizes = [len(dos.write(c)[1]) for c in party]
    assert 804 in sizes, sizes
    assert all(n % 67 == 0 for n in sizes), sizes
