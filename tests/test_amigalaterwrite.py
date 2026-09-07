"""The Amiga Curse and Silver Blades writer: a neutral character becomes a block.

`#384 (Write an Amiga Curse or Silver Blades character, so a C64 or DOS party
has an Amiga to arrive on)` built the third Amiga writer.  `tests/test_amiga.py`
proves the *reader* understood those records; this proves the writer is its
inverse, in the two forms that direction can have:

* **the round trip** -- a record read into the neutral middle and written out
  again is byte for byte the block it came from, everywhere a byte *can*
  survive.  The mask is the writer's own declared lists --
  `goldbox.amiga.LATER_WRITE_UNSOURCED`, `LATER_ITEM_WRITE_UNSOURCED`,
  `LATER_EFFECT_WRITE_UNSOURCED` and `goldbox.dos`'s five -- and never
  whatever happened to differ, so a new difference fails rather than being
  absorbed;
* **nothing unexplained** -- every byte of the block has a provenance line.

The corpus is the 21 records on the game's own disks plus the parties inside
the engine-written saved games in `$WISH_SPECIMENS`.  Nothing is committed:
the disks are read at run time and the tests skip on a machine without them.

**A conversion is not proven until it runs.**  Nothing here has been in front
of Amiga Curse or Amiga Silver Blades, which `#384` says is what would close
it; these tests are what keeps the bytes true once it has.
"""

from __future__ import annotations

import pathlib

import pytest
from gamedata import specimen_root
from test_amiga import curse_characters, silver_blades_characters

from goldbox import amiga, dos, dos_layout, games, neutral
from goldbox.layout import Confidence

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


# ---------------------------------------------------------------------------
# The corpus
# ---------------------------------------------------------------------------
#
# `gamedata.specimen` cannot reach these: it resolves a name under
# `por-<platform>`, and the two later Amiga titles live in `coab-amiga` and
# `ssb-amiga`.  So the walk is local, and it verifies each specimen against
# its own manifest exactly as that helper does -- a changed specimen is not
# evidence and must fail rather than skip.

#: Saved games in the specimen tree **this project wrote**, not the engine.
#: Each is named in its own `provenance.toml`, and each is excluded from any
#: claim about what the game holds -- the same exclusion
#: `tools/dostailcensus.py` makes by name, for the same reason: our bytes read
#: back as the engine's is how a measurement quietly becomes circular.
OURS = {
    # `--strip-items 2`: IILANDA's item chain emptied, and her stored
    # encumbrance left at what it was with three items in it.
    "WISH-SPEC-coab-amiga-resave/savgamD.dat",
    # `--keep 4 --rename 0=TALWYN`
    "WISH-SPEC-ssb-amiga-resave/savgamB.sav",
    # `--square 5,9,6`
    "WISH-SPEC-ssb-amiga-moved/savgamC.sav",
}

#: Which shape each specimen drawer's saved games are.
_DRAWERS = (("coab-amiga", amiga.CURSE_SHAPE, ".dat"),
            ("ssb-amiga", amiga.SILVER_BLADES_SHAPE, ".sav"))


def _verified(where: pathlib.Path) -> None:
    """Fail if a specimen no longer hashes to what its manifest recorded."""
    from tools import specimens

    prov = where / "provenance.toml"
    if not prov.is_file():
        pytest.fail(f"{where}: no provenance.toml -- not a specimen")
    for filename, expected in specimens.read_provenance(prov).get(
            "sha256", {}).items():
        path = where / filename
        if not path.is_file():
            pytest.fail(f"{where.name}: {filename} is missing; "
                        f"run tools/specimens.py check")
        actual = specimens.sha256_file(path)
        if actual != expected:
            pytest.fail(f"{where.name}: {filename} has changed -- recorded "
                        f"{expected[:12]}, now {actual[:12]}; it is no longer "
                        f"evidence. Run tools/specimens.py check")


def engine_written_parties():
    """`(label, character)` for every Amiga later character the engine wrote.

    Empty rather than skipping, so a caller can add it to the disk corpus on
    a machine that has one and not the other.
    """
    root = specimen_root()
    if root is None:
        return []
    out = []
    for drawer, shape, suffix in _DRAWERS:
        for where in sorted((root / drawer).glob("WISH-SPEC-*")):
            if not where.is_dir():
                continue
            _verified(where)
            for path in sorted(where.glob(f"savgam*{suffix}")):
                if f"{where.name}/{path.name}" in OURS:
                    continue
                for char in amiga.party_in_savegame(path.read_bytes(), shape):
                    out.append((f"{where.name}/{path.name}", char))
    return out


def disk_characters():
    """The 21 records on the game's own disks, `(label, character)`."""
    return ([("Curse disk 1", c) for c in curse_characters()]
            + [("Silver Blades disk 1", c) for c in silver_blades_characters()])


# ---------------------------------------------------------------------------
# The mask, built from what the writers declare
# ---------------------------------------------------------------------------

def _record_mask(shape: amiga.AmigaShape) -> set[int]:
    """Amiga record offsets a round trip may differ in, by declared list.

    The DOS writer's own five tables, mapped through this title's shift map:
    the live-heap runs it zeroes, the constants it writes, the defaults it
    substitutes and the fields it derives.  Naming the tables rather than the
    offsets is what makes a *new* entry in one of them visible here instead
    of silently widening the mask.
    """
    names = {n for n, _ in dos.WRITE_UNSOURCED}
    names |= {n for n, _ in dos.WRITE_UNSOURCED_LATER}
    names |= {n for n, _ in dos.WRITE_DERIVED}
    names |= {n for n, _ in dos.WRITE_DERIVED_LATER}
    names |= {n for n, _, _ in dos.WRITE_CONSTANTS}
    names |= {n for n, _, _, _ in dos.WRITE_DEFAULTS}
    out: set[int] = set()
    for f in dos_layout.layout_for(shape.dos):
        if f.name not in names:
            continue
        try:
            at = shape.offset(f.offset)
        except amiga.AmigaRecordError:
            continue
        out.update(range(at, at + f.size))
    return out


def _block_mask(char: amiga.AmigaCharacter) -> set[int]:
    """The same over a whole block: record, item nodes, effect chain."""
    shape = char.shape
    out = _record_mask(shape)
    at = shape.record_size
    for _ in char.items:
        for offset, size, _why in amiga.LATER_ITEM_WRITE_UNSOURCED:
            out.update(range(at + offset, at + offset + size))
        at += shape.item_size
    for _ in char.effects:
        for offset, size, _why in amiga.LATER_EFFECT_WRITE_UNSOURCED:
            out.update(range(at + offset, at + offset + size))
        at += shape.effect_size
    return out


# ---------------------------------------------------------------------------
# The tables, which need no game data
# ---------------------------------------------------------------------------

def test_the_unsourced_list_is_the_shift_maps_own_gaps():
    """A pad the shift map creates and the writer's table forgets would be a
    byte written from nothing and explained by nothing.  Computed from the
    map, compared with the list, both directions."""
    for shape in amiga.AMIGA_SHAPES:
        declared = tuple(sorted(
            offset for at, size, _ in amiga.LATER_WRITE_UNSOURCED[shape.key]
            for offset in range(at, at + size)))
        assert declared == amiga.later_unsourced_offsets(shape), shape.title


def test_curse_has_six_unsourced_bytes_and_silver_blades_three():
    """The counts the record unpackers put there, so a shift map edited
    without its evidence fails here.

    Curse: the pad ahead of the money block, the sixth byte of each of the
    three six-byte spell-slot arrays, the pad before the item pointer array,
    and the trailing byte that makes 427 into 428.  Silver Blades: three
    pads, and no trailing byte because 340 is already even.
    """
    assert amiga.later_unsourced_offsets(amiga.CURSE_SHAPE) == (
        0x0FB, 0x133, 0x139, 0x13F, 0x151, 0x1AB)
    assert amiga.later_unsourced_offsets(amiga.SILVER_BLADES_SHAPE) == (
        0x095, 0x0C7, 0x0FD)


def test_the_writer_refuses_a_title_it_has_no_record_for():
    """Pool of Radiance is refused **by name**, since it has an Amiga writer
    of its own and a caller who lands here has picked the wrong one."""
    por = neutral.NeutralCharacter("test",
                                   game=games.by_key("pool-of-radiance"))
    with pytest.raises(amiga.AmigaRecordError, match="write_por"):
        amiga.write_later(por)
    with pytest.raises(amiga.AmigaRecordError, match="has been decoded"):
        amiga.later_write_shape(neutral.NeutralCharacter("test"),
                                shape="krynn")


def test_the_title_is_the_characters_own():
    """A conversion is between two ports of the same title and never between
    titles, so the shape comes off the character rather than the caller."""
    for shape in amiga.AMIGA_SHAPES:
        char = neutral.NeutralCharacter("test", game=games.by_key(shape.key))
        assert amiga.later_write_shape(char) is shape


def test_the_silver_blades_spellbook_packs_the_way_the_reader_unpacks_it():
    """Least significant bit first, id 1 in bit 0 of the first byte.

    The bit order is `/Secret`'s own mask table at `g234e`, and the test that
    it is the same one both ways is a book written and read back.
    """
    shape = amiga.SILVER_BLADES_SHAPE
    book = shape.dos_field("spellbook")
    ids = [1, 8, 9, 29, 77, 78, 79, 80, 117]
    record = bytearray(shape.dos.record_size)
    for spell in ids:
        record[book.offset + spell - dos_layout.SPELLBOOK_FIRST_ID] = 1
    mask = amiga._later_spellbook_bytes(bytes(record), shape)
    assert len(mask) == amiga.AMIGA_SSB_SPELLBOOK_BYTES
    out = bytearray(shape.record_size)
    out[amiga.AMIGA_SSB_SPELLBOOK_AT:
        amiga.AMIGA_SSB_SPELLBOOK_AT + len(mask)] = mask
    assert amiga.AmigaCharacter.from_bytes(bytes(out), shape).spellbook == ids


# ---------------------------------------------------------------------------
# The empty case and the extreme one, which need no game data either
# ---------------------------------------------------------------------------

def _bare(shape: amiga.AmigaShape) -> neutral.NeutralCharacter:
    """A character with a name and six scores and nothing else.

    Both are here because the saved game's party is found by scanning for
    the record signature -- 16 bytes of NUL-terminated printable ASCII and
    six equal, legal ability pairs -- so a character with neither is one
    `party_in_savegame` cannot find, whatever the writer did with it.
    """
    char = neutral.NeutralCharacter("test", game=games.by_key(shape.key))
    ok = Confidence.CONFIRMED
    char.set("name", "TESTER", "a test name", ok)
    for ability in neutral.ABILITIES:
        char.set(ability, 12, "a test score", ok)
    return char


def test_a_character_who_owns_nothing_gets_a_block_that_is_only_the_record():
    """`#62 (A converted character who owns nothing gets a corrupt sheet, and
    DOS then invents a garbage item)` is where this case was found on the DOS
    side, after that conversion had been declared proven.

    Here it is the loader that would suffer: it decides whether a node
    follows by testing the head the record carries, and every character is
    read off one file descriptor in sequence -- so a non-zero head with
    nothing behind it would leave the stream mid-block and every later
    character in the party would read rubbish.
    """
    for shape in amiga.AMIGA_SHAPES:
        built, report = amiga.write_later(_bare(shape))
        block = built.block_bytes()
        assert len(block) == shape.record_size
        assert built.get("item_count") == 0
        assert built.item_chain == 0
        assert built.effect_chain == 0
        assert report.unaccounted == []


def _loaded(shape: amiga.AmigaShape, items: int = 16
            ) -> neutral.NeutralCharacter:
    char = _bare(shape)
    ok = Confidence.CONFIRMED
    char.set("inventory", [bytes([n + 1]) + bytes(15) for n in range(items)],
             "a test inventory", ok)
    char.set("granted_effects", [bytes((61, 0, 0, 5, 1)) + bytes(4)],
             "a ring's grant", ok)
    char.set("innate_effects", [26, 47], "two innate ids", ok)
    return char


def test_a_character_carrying_everything_chains_every_node():
    """Sixteen items, three effects, and the loader's own two tests.

    The head is non-zero because nodes follow, every node's `next` is
    non-zero but the last one's, and the block is exactly
    `record + 16 x item + 3 x effect` -- which is the arithmetic the loader
    does to find where the next character in the party begins.
    """
    for shape in amiga.AMIGA_SHAPES:
        built, report = amiga.write_later(_loaded(shape))
        block = built.block_bytes()
        assert len(block) == (shape.record_size + 16 * shape.item_size
                              + 3 * shape.effect_size)
        assert built.get("item_count") == 16
        assert built.item_chain != 0
        assert built.effect_chain != 0
        nexts = [item.next for item in built.items]
        assert all(nexts[:-1]) and nexts[-1] == 0
        ends = [int.from_bytes(node[amiga.AMIGA_LATER_EFFECT_NEXT:][:4], "big")
                for node in built.effects]
        assert all(ends[:-1]) and ends[-1] == 0
        assert report.unaccounted == []


def test_a_written_block_reads_back_as_the_party_it_is():
    """The block the writer hands `tools/amigasavegame.py` has to be one the
    reader finds: a scan for the record signature and a walk of the counts."""
    for shape in amiga.AMIGA_SHAPES:
        built, _ = amiga.write_later(_loaded(shape))
        blocks = amiga.party_block_bytes([built, built])
        found = amiga.party_in_savegame(blocks, shape)
        assert len(found) == 2
        assert [len(c.items) for c in found] == [16, 16]
        assert [len(c.effects) for c in found] == [3, 3]


def test_the_effect_chain_is_the_neutral_records_and_not_the_races():
    """The measurement behind `LATER_EFFECTS_FROM_NEUTRAL`.

    `to_neutral_later` cannot tell an innate effect from an item's grant in
    these titles, so it calls them all grants; `goldbox.dos.write` then adds
    the racial ids from its own table as well.  Taking its `.SPC` payload
    would put a dwarf's infravision in the chain twice, and the three Curse
    dwarves and gnomes come back with 7, 7 and 8 records where the game wrote
    3, 3 and 4.  So this writer builds the chain itself, and a character with
    three effect records gets three nodes.
    """
    for shape in amiga.AMIGA_SHAPES:
        built, _ = amiga.write_later(_loaded(shape))
        assert [node[0] for node in built.effects] == [61, 26, 47]


def test_only_silver_blades_reports_the_byte_nobody_has_attributed():
    """`#387 (The Amiga Silver Blades effect node keeps a byte DOS has not
    got, and a converted character loses it)`.

    Zero in 24 of 24 Curse nodes, so Curse loses nothing and says nothing;
    non-zero in 3 of the 5 Silver Blades nodes anywhere, so Silver Blades
    reports it.  A character with no effects has nothing to lose either way.
    """
    said = amiga.LATER_EFFECT_UNKNOWN_PLAYER_TEXT
    _, curse_report = amiga.write_later(_loaded(amiga.CURSE_SHAPE))
    _, ssb_report = amiga.write_later(_loaded(amiga.SILVER_BLADES_SHAPE))
    _, empty_report = amiga.write_later(_bare(amiga.SILVER_BLADES_SHAPE))
    assert said not in curse_report.dropped
    assert said in ssb_report.dropped
    assert said not in empty_report.dropped


def test_no_line_a_player_reads_carries_an_offset():
    """`.claude/rules/gui-text.md`: a memory address, a record offset or a
    bare issue number has no place in anything shown in the interface, and
    the tables behind this writer carry all three on purpose."""
    for shape in amiga.AMIGA_SHAPES:
        _, report = amiga.write_later(_loaded(shape))
        for line in report.dropped:
            assert "0x" not in line and "#" not in line, line


# ---------------------------------------------------------------------------
# The round trip, over every Amiga later record on this machine
# ---------------------------------------------------------------------------

def _round_trip(label: str, char: amiga.AmigaCharacter) -> None:
    built, report = amiga.write_later(amiga.to_neutral_later(char))
    got, want = built.block_bytes(), char.block_bytes()
    assert len(got) == len(want), f"{label} {char.name}: block length"
    assert report.unaccounted == [], f"{label} {char.name}: unexplained bytes"
    mask = _block_mask(char)
    differ = [n for n, (a, b) in enumerate(zip(want, got))
              if a != b and n not in mask]
    assert differ == [], (
        f"{label} {char.name}: {len(differ)} bytes differ outside the "
        f"declared lists, first at {differ[0]:#05x}" if differ else "")


def test_every_record_on_the_disks_round_trips():
    """21 of 21: the eleven Curse `.guy` pregens, the four played Curse
    characters and the six shipped Silver Blades ones."""
    corpus = disk_characters()
    assert len(corpus) == 21, [c.name for _, c in corpus]
    for label, char in corpus:
        _round_trip(label, char)


def test_every_engine_written_specimen_round_trips():
    """The parties inside the saved games the two games themselves wrote.

    Stronger evidence than the disks, because nobody has to argue about who
    wrote them: `provenance.toml` says which run each came out of, and the
    three files **this project** wrote are excluded by name (`OURS`).
    """
    corpus = engine_written_parties()
    if not corpus:
        pytest.skip("no Amiga Curse or Silver Blades specimens; "
                    "see tools/specimens.py and $WISH_SPECIMENS")
    for label, char in corpus:
        _round_trip(label, char)


# ---------------------------------------------------------------------------
# The direction this writer exists for: a C64 party arriving on the Amiga
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, shape, expect_items", [
    ("curse-h-engine-resave", amiga.CURSE_SHAPE, False),
    ("ssb-d-engine-resave", amiga.SILVER_BLADES_SHAPE, True),
])
def test_a_c64_party_becomes_amiga_records_of_its_own_title(
        name, shape, expect_items):
    """Both C64 saves the **C64 engine itself** wrote, converted.

    The same two specimens `tests/test_doslatertitles.py` uses for C64 to
    DOS, which is what makes this the same measurement one port further on.
    Every block has to be the length the loader will compute -- record plus
    `item_count` nodes plus the effect chain -- or the character after it in
    the party reads rubbish.
    """
    from test_doslatertitles import _c64_disk, _c64_party

    _game, party = _c64_party(_c64_disk(name))
    assert len(party) == 6
    carried = 0
    for char in party:
        built, report = amiga.write_later(char)
        block = built.block_bytes()
        assert built.shape is shape, char.get("name")
        assert len(block) == (shape.record_size
                              + len(built.items) * shape.item_size
                              + len(built.effects) * shape.effect_size)
        assert built.get("item_count") == len(built.items)
        assert bool(built.item_chain) is bool(built.items)
        assert bool(built.effect_chain) is bool(built.effects)
        assert report.unaccounted == []
        assert amiga.party_in_savegame(block, shape)
        carried += bool(built.items)
    assert bool(carried) is expect_items


def test_a_converted_silver_blades_party_agrees_with_its_own_amiga_twins():
    """SSI shipped the same six people on the C64 and the Amiga, so the
    conversion can be checked against the answer.

    150 field comparisons -- 25 fields for each of the six: race, class,
    alignment, sex, age, the seven class levels, hit points, all seven money
    fields, armour class, THAC0 base, size, level and the seven abilities --
    and **0 of 150 differ**.  The effect ids agree 6 of 6 as well, which is
    an independent thing: the C64 keeps them in ten trait slots and the
    Amiga in a chain of ten-byte nodes, and nothing in the conversion
    consults the Amiga side.

    The names agree too, bar one trailing space: the Amiga's own record reads
    `'Guy de Valois '` and the C64's `'Guy de Valois'`.  Whether Amiga Pool
    of Radiance and its sequels keep or drop a trailing space in a name is
    `#308 (Does Amiga Pool of Radiance drop the space out of a character's
    name when it saves?)`, still open.

    What this is **not** is proof the game will load it: no converted Silver
    Blades block has been in front of Amiga Silver Blades, and `#384` says so.
    """
    from test_doslatertitles import _c64_disk, _c64_party

    twins = {c.name.strip().upper(): c for c in silver_blades_characters()}
    _game, party = _c64_party(_c64_disk("ssb-d-engine-resave"))
    fields = ["race", "char_class", "alignment", "sex", "age", "class_levels",
              "hp_max", "copper", "silver", "electrum", "gold", "platinum",
              "gems", "jewelry", "armour_class", "thac0_base", "size",
              "level"] + list(neutral.ABILITIES)
    compared = 0
    for char in party:
        twin = twins[str(char.get("name")).strip().upper()]
        built, _report = amiga.write_later(char)
        for field in fields:
            assert built.get(field) == twin.get(field), (twin.name, field)
            compared += 1
        assert [node[0] for node in built.effects] == [
            node[0] for node in twin.effects], twin.name
        assert built.name == twin.name.rstrip()
    assert compared == 150


def test_the_engine_agrees_with_the_encumbrance_this_writer_computes():
    """The one disagreement in the whole corpus, and it is agreement.

    `WISH-SPEC-coab-amiga-resave/savgamD.dat` is ours -- IILANDA's item chain
    emptied by `tools/amigalaterslot.py --strip-items 2`, which left her
    stored encumbrance at the 782 she had with three items.  This writer
    recomputes 282 from her money and her (now empty) inventory, so a round
    trip against *that* file differs by two bytes.  `savgamE.dat` is Amiga
    Curse's own resave of it and holds **282**, which is our number.

    So encumbrance is money plus item weight times quantity in the Amiga
    engine too, and a converted character's recomputed value is the engine's
    own answer rather than a loss.
    """
    root = specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    where = root / "coab-amiga" / "WISH-SPEC-coab-amiga-resave"
    if not where.is_dir():
        pytest.skip("needs WISH-SPEC-coab-amiga-resave")
    _verified(where)
    ours = {c.name: c for c in amiga.party_in_savegame(
        (where / "savgamD.dat").read_bytes(), amiga.CURSE_SHAPE)}
    theirs = {c.name: c for c in amiga.party_in_savegame(
        (where / "savgamE.dat").read_bytes(), amiga.CURSE_SHAPE)}
    stripped = ours["IILANDA"]
    assert stripped.items == ()
    assert stripped.get("encumbrance") == 782
    written, _ = amiga.write_later(amiga.to_neutral_later(stripped))
    assert written.get("encumbrance") == theirs["IILANDA"].get("encumbrance")
    assert written.get("encumbrance") == 282
