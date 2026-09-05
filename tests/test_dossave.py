from __future__ import annotations

"""What a real DOS Pool of Radiance save says about its own layout.

`docs/117-save-conversion.md` carried a predicted DOS field table taken from
community notes and labelled PROBABLE because nobody had checked it against a
file. There is now a played DOS party to check it against, and these tests are
the check: every claim here is measured off the saves rather than asserted.

**Two corpora, and they are not interchangeable.**

*The specimen tree*, `$WISH_SPECIMENS` or `~/wish-specimens` -- Pool of
Radiance characters rolled in the game's own CREATE NEW CHARACTER screens
under DOSBox and written by the game's own SAVE CURRENT GAME, for
`#249 (Build a DOS party from creation and level it ourselves, so DOS
measurements rest on records we watched being written)` and
`#84 (Roll a gnome in DOS and read the two innate effect ids nobody has
seen)`. **Every test below that derives a fact about the game reads this**,
because a fact is only as good as the provenance of the bytes it came from.

*The archives*, `$FR_ARCHIVES` -- Donald's unpacked copy of *Forgotten
Realms: The Archives*. Its `SAVE` folder was opened in Gold Box Companion's
character editor on 2026-08-17 and its `Default files/Saves` is a download
with no chain of custody, so **nothing here may take a measurement off it**.
It stays as a *template* for the writer and converter round trips in
`tests/test_doswriter.py` and the rest, where what goes in comes back out and
the input's provenance does not enter the claim.

`#246 (Nothing tells an engine-written DOS record from one edited with Gold
Box Companion, and conclusions already rest on edited ones)` is why the split
exists, and `.claude/rules/testing.md`'s "A specimen is only evidence if we
know who wrote it" is the rule. Nothing is copied into the repository either
way. With neither tree the module skips, which is what CI does.

Findings and their reasoning: `work/reports/dos-saves.md`.
"""


import functools
import struct

import pytest
from gamedata import (
    have_specimen,
    needs_specimens,
    specimen,
    specimen_files,
)

#: The 285-byte Pool of Radiance record. Offsets confirmed in
#: `work/reports/dos-saves.md` section 3.
RECORD_SIZE = 285
NAME_LEN = 0x000            # length byte, then up to 15 ASCII
ABILITIES = 0x010           # STR INT WIS DEX CON CHA
EXC_STRENGTH = 0x016
SPELLBOOK = 0x033           # 56 bytes, one per spell
THAC0_BASE = 0x02D          # 60 - THAC0
RACE = 0x02E
CHAR_CLASS = 0x02F
AGE = 0x030                 # u16le
HP_MAX = 0x032              # one byte; 0x033 is the spellbook
SAVES = 0x06D               # five saving throws
LEVEL = 0x073
THIEF_SKILLS = 0x077        # eight percentages
MONEY = 0x088               # 7 x u16le: cp sp ep gp pp gems jewelry
CLASS_LEVELS = 0x096        # eight, indexed by the class number
SEX = 0x09E
EXPERIENCE = 0x0AC          # u24le
CLASS_BITS = 0x0B0          # 1 mage, 2 cleric, 4 thief, 8 fighter
COMBAT_ICON_SLOT = 0x0BF    # `party_order` in the tables: #305
ITEM_COUNT = 0x0C7
ENCUMBRANCE = 0x102         # u16le
HP_CURRENT = 0x11B

ITEM_SIZE = 63
ITEM_WEIGHT = 0x37          # u16le
ITEM_QUANTITY = 0x39
EFFECT_SIZE = 9

#: `SAVGAM?.DAT` is one header byte then a u16le array of the engine's
#: variable space, indexed by the address the ECL bytecode uses.
SAVGAM_SIZE = 13137
SAVGAM_BASE = 0x4900
SAVGAM_WORDS = 2560
#: The persistent quest flags, `work/reports/quest-flags.md`.
FLAGS_FIRST, FLAGS_LAST = 0x4A20, 0x4AF8

#: GBC's table, `Games/01. Pool of Radiance/Game.dat`. Index is the byte.
RACES = ("monster", "dwarf", "elf", "gnome", "half-elf", "halfling",
         "half-orc", "human")
CLASSES = ("cleric", "druid", "fighter", "paladin", "ranger", "mage", "thief",
           "monk", "cleric/fighter", "cleric/fighter/mage", "cleric/ranger",
           "cleric/mage", "cleric/thief", "fighter/mage", "fighter/thief",
           "fighter/mage/thief", "mage/thief", "monster")

def _candidates():
    """`gamedisks.toml`'s own search list for the DOS archives (#212)."""
    from tools import gamedisks
    return gamedisks.candidates("dos-archives")


@functools.lru_cache(maxsize=1)
def _save_dir():
    """The directory holding a played DOS Pool of Radiance party, or None.

    Steam redirects the game's save directory into `SavesDir`, so the party is
    not under the game folder. Recognise it by the files rather than the path,
    and by the record size rather than by the file names: every title in the
    family writes `CHRDAT??.SAV` beside a `SAVGAM?.DAT`, and only Pool of
    Radiance writes 285 bytes. Prefer the directory with the most records, so
    a played party wins over the shipped one.
    """
    best = None
    for root in _candidates():
        try:
            if not root.is_dir():
                continue
            for path in root.rglob("SAVGAM[ABJ].DAT"):
                records = [p for p in path.parent.glob("CHRDAT*.SAV")
                           if p.stat().st_size == RECORD_SIZE]
                if records and (best is None or len(records) > best[0]):
                    best = (len(records), path.parent)
        except OSError:
            continue
    return best[1] if best else None


@functools.lru_cache(maxsize=1)
def _game_dirs():
    """`Default files/Saves` for every DOS Gold Box title present, by title."""
    out = {}
    for root in _candidates():
        if not root.is_dir():
            continue
        for path in root.glob("*/games/*/Default files/Saves"):
            if path.is_dir():
                out.setdefault(path.parent.parent.name, path)
    return out


def _records():
    """Every 285-byte Pool of Radiance record, saved and exported, by name."""
    where = _save_dir()
    if where is None:
        pytest.skip("needs a DOS save; set FR_ARCHIVES to the archives")
    out = {}
    for path in sorted(where.glob("*.SAV")) + sorted(where.glob("*.CHA")):
        data = path.read_bytes()
        if len(data) == RECORD_SIZE:
            out[path.name] = data
    if not out:
        pytest.skip("no DOS Pool of Radiance character records here")
    return out


def _savgam(slot: str = "A") -> bytes:
    where = _save_dir()
    if where is None:
        pytest.skip("needs a DOS save; set FR_ARCHIVES to the archives")
    path = where / f"SAVGAM{slot}.DAT"
    if not path.exists():
        pytest.skip(f"no SAVGAM{slot}.DAT here")
    return path.read_bytes()


def _words(save: bytes):
    """The saved game as the engine sees it: address -> value."""
    count = min(SAVGAM_WORDS, (len(save) - 1) // 2)
    return list(struct.unpack_from(f"<{count}H", save, 1))


def _name(record: bytes) -> str:
    return record[1:1 + record[NAME_LEN]].decode("ascii")


def _u16(data: bytes, at: int) -> int:
    return struct.unpack_from("<H", data, at)[0]


def _experience(record: bytes) -> int:
    return int.from_bytes(record[EXPERIENCE:EXPERIENCE + 3], "little")


needs_dos_saves = pytest.mark.skipif(
    _save_dir() is None, reason="needs a DOS save; set FR_ARCHIVES")


# --- the clean corpus ---------------------------------------------------------
# Records this project watched being written, from character creation onward.
# `tools/specimens.py list` describes them; `tests/gamedata.py`'s `specimen`
# re-hashes one against its own manifest before a test reads it.

#: The `#249` party, in three states: as the game wrote it to slot C at the
#: roster, as it wrote it to slot E after the New Phlan tour, and as the six
#: loose `.CHA` records that existed for one moment between CREATE NEW
#: CHARACTER and ADD CHARACTER TO PARTY. Six characters, eighteen records,
#: covering human fighter, human cleric, elf magic-user, halfling thief, dwarf
#: fighter/thief and half-elf cleric/fighter/magic-user.
CLEAN_PARTY = ("por-party-l1", "por-party-l1-intown", "por-party-l1-rolled")

#: `#84`'s eight rolls, one per race: three gnomes, a dwarf, a halfling, an
#: elf, a human and a half-elf. Exports, so no items and no `.ITM`.
CLEAN_ROLLS = ("gnomf1", "gnomt2", "gnomft3", "dwarfc4", "halfl5", "elf6",
               "human7", "halfe8")

#: The two states of the training run. Their experience, gold and encumbrance
#: went in as *ours* -- `tools/dostrainprobe.py`'s `install` writes all three --
#: so nothing money-shaped in them is the game's arithmetic. Everything the
#: trainer itself wrote is: level, the per-class levels, hit points, the spell
#: slots, and the experience it left behind.
CLEAN_TRAINED = ("por-party-trained-c2", "por-train-clamp")

#: The only clean Pool of Radiance record that carries items: THRENDER GRONE
#: with a flail and banded mail, saved by the engine on `#232`.
CLEAN_WITH_ITEMS = "por-item-granted"

def _clean_records(*groups):
    """Every 285-byte record in the named specimen groups, keyed
    `<specimen>/<filename>`.

    Defaults to the corpus a layout claim may rest on: the `#249` party in its
    three states plus `#84`'s eight rolls -- 26 records over 14 distinct
    characters.
    """
    names = []
    for group in (groups or (CLEAN_PARTY, CLEAN_ROLLS)):
        names += list(group) if isinstance(group, tuple) else [group]
    return specimen_files(names, (".SAV", ".CHA"), size=RECORD_SIZE)


needs_clean_party = pytest.mark.skipif(
    not all(have_specimen(name) for name in CLEAN_PARTY),
    reason="needs the #249 specimen party; see tools/specimens.py")


# --- the record ---------------------------------------------------------------

@needs_specimens
def test_record_is_285_bytes():
    """A saved character and an exported one are the same record.

    That is the fact the whole conversion plan rests on: DOS's export is the
    slot copied out, not a reduced form, exactly as on the C64.

    Measured on the same six characters in both forms -- `CHRDATC1-6.SAV` as
    the game saved the party, and `WISHFTR.CHA` and its five siblings as the
    game wrote them at creation -- so the two lengths are one party's, not two
    parties' coincidence. 26 records.
    """
    records = _clean_records()
    assert len(records) >= 26
    assert {len(r) for r in records.values()} == {RECORD_SIZE}
    assert any(n.endswith(".CHA") for n in records)
    assert any(n.endswith(".SAV") for n in records)
    saved = {_name(r) for n, r in records.items() if n.endswith(".SAV")}
    exported = {_name(r) for n, r in records.items() if n.endswith(".CHA")}
    assert saved & exported, (sorted(saved), sorted(exported))


@needs_specimens
def test_name_is_length_prefixed_ascii():
    """`0x000` is a length byte and 15 bytes of name -- `docs/117` predicted it.

    The C64 spends 20 NUL-padded bytes on the same field, which is where the
    four-byte offset between the two layouts comes from.
    """
    for filename, record in _clean_records().items():
        length = record[NAME_LEN]
        assert 1 <= length <= 15, filename
        name = record[1:1 + length]
        assert name.decode("ascii").strip(), filename
        assert all(32 <= c < 127 for c in name), filename
        assert record[1 + length:0x10] == b"\x00" * (15 - length), filename


@needs_specimens
def test_abilities_and_exceptional_strength():
    """Six abilities at `0x010`, exceptional strength at `0x016`.

    The C64's order, four bytes earlier. Exceptional strength is nonzero only
    where strength is 18 -- the AD&D rule, so a wrong offset would show.

    Every one of the 26 was the first roll the creation screen offered and was
    kept, so the spread is the game's own generator rather than a party
    anybody arranged.
    """
    for filename, record in _clean_records().items():
        abilities = record[ABILITIES:ABILITIES + 6]
        assert all(3 <= a <= 19 for a in abilities), (filename, list(abilities))
        exceptional = record[EXC_STRENGTH]
        assert 0 <= exceptional <= 100, filename
        if exceptional:
            assert abilities[0] == 18, filename


@needs_specimens
def test_race_and_class_are_legal_pairs():
    """`0x02E` race, `0x02F` class, against GBC's tables -- and AD&D's rules.

    Only demihumans multi-class, and each combination is restricted by race.
    Every specimen obeys it, which no wrong pair of offsets would.

    Six races over the 26 records -- human, elf, half-elf, halfling, dwarf and
    gnome -- and six classes, including the dwarf's fighter/thief and the
    half-elf's cleric/fighter/magic-user, which are the pairs a wrong table
    would break first.
    """
    legal_multiclass = {"half-elf", "elf", "dwarf", "gnome", "halfling",
                        "half-orc"}
    for filename, record in _clean_records().items():
        race, char_class = record[RACE], record[CHAR_CLASS]
        assert race < len(RACES), filename
        assert char_class < len(CLASSES), filename
        if "/" in CLASSES[char_class]:
            assert RACES[race] in legal_multiclass, (filename,
                                                     RACES[race],
                                                     CLASSES[char_class])


@needs_specimens
def test_class_bits_agree_with_the_class_byte():
    """`0x0B0` is the class bitmask, same bit order as the C64's `0x0EB`.

    bit 0 mage, bit 1 cleric, bit 2 thief, bit 3 fighter. Every multi-class
    value decomposes into the parts its class name spells out.
    """
    for filename, record in _clean_records().items():
        parts = CLASSES[record[CHAR_CLASS]].split("/")
        names = {"mage": 0x01, "cleric": 0x02, "thief": 0x04, "fighter": 0x08}
        if not set(parts) <= set(names):
            continue                    # druid, paladin, ranger, monk, monster
        expected = 0
        for part in parts:
            expected |= names[part]
        assert record[CLASS_BITS] == expected, (filename, parts)


@needs_specimens
def test_per_class_levels_are_eight_wide_and_class_indexed():
    """`0x096` is an eight-byte array indexed by the class number.

    The C64's equivalent at `0x0C9` is eight wide too, but ordered by the class
    *bits* rather than the class number -- so the array does not transfer
    slot for slot even though both are eight bytes.

    `CLEAN_TRAINED` is in the corpus because it holds the only records above
    level 1: the clerics' school of area 11 took WISHCLE to cleric 2 and
    WISHHEL to cleric 2 / fighter 1 / magic-user 1, so `0x073` equalling the
    maximum of the array is a claim about a record where the maximum is not
    trivially 1.
    """
    for filename, record in _clean_records(
            CLEAN_PARTY, CLEAN_ROLLS, CLEAN_TRAINED).items():
        levels = record[CLASS_LEVELS:CLASS_LEVELS + 8]
        assert all(level <= 12 for level in levels), (filename, list(levels))
        parts = CLASSES[record[CHAR_CLASS]].split("/")
        by_name = {name: index for index, name in enumerate(CLASSES[:8])}
        for part in parts:
            if part in by_name:
                assert levels[by_name[part]] >= 1, (filename, part)
        # The highest of them is the level at 0x073.
        assert record[LEVEL] == max(levels), filename


@needs_specimens
def test_thac0_base_and_saving_throws_carry_the_biased_encoding():
    """`0x02D` is `60 - THAC0`, the same bias the C64 uses.

    Gold Box Companion's `Levels.txt` states `thac0_base = 40` for a first
    level cleric and 42 from level 4 -- the stored number, not the printed
    one.

    **The clean corpus holds 40 and nothing else**, because every record in it
    is level 1 or 2 and 40 is what the table gives for both. 42 and 43 were
    measured on the archives' parties, whose provenance is unknown, so this no
    longer asserts them; a specimen carrying either needs a character trained
    to level 4, which nothing here has yet.
    """
    for filename, record in _clean_records(
            CLEAN_PARTY, CLEAN_ROLLS, CLEAN_TRAINED).items():
        base = record[THAC0_BASE]
        assert 30 <= base <= 60, filename
        assert 1 <= 60 - base <= 20, filename
        throws = record[SAVES:SAVES + 5]
        assert all(1 <= t <= 20 for t in throws), (filename, list(throws))


@needs_specimens
def test_hit_points_maximum_is_one_byte():
    """`0x032` -- and there is no room for a second, because `0x033` is the
    spellbook. The C64's field is genuinely two bytes wide; DOS's is not.

    `CLEAN_TRAINED` carries the only records where the field moved: the
    trainer took WISHCLE from 6 to 10 and WISHHEL from 7 to 9, and both wrote
    into one byte."""
    for filename, record in _clean_records(
            CLEAN_PARTY, CLEAN_ROLLS, CLEAN_TRAINED).items():
        assert 1 <= record[HP_MAX] <= 255, filename
        assert record[HP_CURRENT] <= record[HP_MAX], filename


@needs_specimens
def test_spellbook_is_one_byte_per_spell():
    """`0x033`-`0x06A`, 56 entries, against the C64's 7 bytes of bits at
    `0x078`. A converter has to transpose the field, not copy it.

    Non-casters have an empty book; casters have a non-empty one and every
    entry is a flag rather than a count.

    Fourteen distinct characters, six of them casters and eight not, so the
    "empty book exactly when the class does not cast" half is a claim about
    both sides rather than about the casters alone.
    """
    for filename, record in _clean_records().items():
        book = record[SPELLBOOK:SPELLBOOK + 56]
        assert all(b <= 1 for b in book), (filename, sorted(set(book)))
        casts = bool({"cleric", "mage"} & set(
            CLASSES[record[CHAR_CLASS]].split("/")))
        assert bool(sum(book)) == casts, filename


@needs_specimens
def test_age_is_plausible_and_elves_are_old():
    """`0x030` as `u16le`. Its high byte is zero in every specimen held, so
    the width is inferred from the C64 rather than measured.

    The engine rolled these ages itself in the creation screens: 16 to 164
    across the 26 records, and the two oldest are the elf at 164 and the
    half-elf at 48."""
    for filename, record in _clean_records().items():
        age = _u16(record, AGE)
        assert 1 <= age <= 2000, filename
        assert record[AGE + 1] == 0, filename
        if RACES[record[RACE]] == "elf":
            assert age >= 100, filename


@needs_specimens
def test_the_combat_icon_slot_numbers_the_six_files():
    """`0x0BF`. A six-character save numbers its files 0 to 5 in order.

    Four saves of one party -- slot C at the roster, slot E after the tour and
    slot F twice out of the training hall -- and the six characters went in in
    a known order, WISHFTR first and WISHHEL last, because we chose it at ADD
    CHARACTER TO PARTY. So this checks the field against the order we watched
    rather than against itself.

    **The byte is the combat-icon slot rather than the marching order**
    (#305): LOAD SAVED GAME allocates the lowest free one of eight as it
    reads the six filenames, so a party nobody has reordered comes out
    numbered by file position and this assertion holds either way.  What it
    does not prove is which of the two the byte *is*; the engine's own
    allocation loop in `GAME.OVR` does that.

    A `.CHA` written at creation holds 0: no icon has been handed out to a
    character who is on the roster and in no party.
    """
    for name in CLEAN_PARTY[:2] + CLEAN_TRAINED:
        where = specimen(name)
        paths = sorted(where.glob("CHRDAT??.SAV"))
        assert len(paths) == 6, name
        order = [p.read_bytes()[COMBAT_ICON_SLOT] for p in paths]
        assert order == [0, 1, 2, 3, 4, 5], name
    for filename, record in specimen_files(
            ["por-party-l1-rolled"], (".CHA",), size=RECORD_SIZE).items():
        assert record[COMBAT_ICON_SLOT] == 0, filename


# --- items --------------------------------------------------------------------

@needs_specimens
def test_item_count_predicts_the_item_file_exactly():
    """`0x0C7` x 63 is the size of the character's `.ITM`, with no header.

    **The stride rests on one record.** The `#249` party never picked anything
    up, so its twenty-four saved records say only that a count of 0 comes with
    no `.ITM` at all -- which pins the absent-file case and nothing about 63.
    THRENDER GRONE of `WISH-SPEC-por-item-granted` is the only clean Pool of
    Radiance character carrying items: count 2, and the `.ITM` the engine
    wrote beside him is 126 bytes. A stride of 62 or 64 would miss it.

    The claim that an *export* zeroes the field is **not** tested here any
    more. Every clean `.CHA` we hold was written at creation by a character
    who had never owned an item, so a zero in it is not evidence of zeroing.
    Settling it needs an export taken from a character with items in hand.
    """
    checked = with_items = 0
    for name in CLEAN_PARTY[:2] + CLEAN_TRAINED + (CLEAN_WITH_ITEMS,):
        where = specimen(name)
        for path in sorted(where.glob("CHRDAT*.SAV")):
            record = path.read_bytes()
            if len(record) != RECORD_SIZE:
                continue
            items = path.with_suffix(".ITM")
            size = items.stat().st_size if items.exists() else 0
            assert size == record[ITEM_COUNT] * ITEM_SIZE, f"{name}/{path.name}"
            checked += 1
            with_items += record[ITEM_COUNT] > 0
    assert checked >= 25
    assert with_items == 1, "the item stride rests on THRENDER GRONE alone"


@needs_specimens
def test_effect_files_are_a_multiple_of_nine():
    """`.SPC` is a list of 9-byte effect records and is simply absent when
    the character has none.

    Twenty-four files across the clean corpus, at 9, 18, 36 and 54 bytes -- and
    the absence half is measured too: the engine wrote the two humans of the
    `#249` party no `.SPC` at all, which is `#84`'s finding reproduced by a
    party rolled a fortnight later.
    """
    seen = humans = 0
    for name in CLEAN_PARTY + CLEAN_ROLLS + CLEAN_TRAINED + (
            CLEAN_WITH_ITEMS,):
        where = specimen(name)
        for path in sorted(where.glob("*.SPC")):
            size = path.stat().st_size
            assert size and size % EFFECT_SIZE == 0, f"{name}/{path.name}"
            seen += 1
    assert seen >= 24
    for filename, record in _clean_records(CLEAN_PARTY[2]).items():
        stem = filename.split("/")[1].rsplit(".", 1)[0]
        effects = specimen(CLEAN_PARTY[2]) / f"{stem}.SPC"
        if RACES[record[RACE]] == "human":
            assert not effects.exists(), filename
            humans += 1
        else:
            assert effects.exists(), filename
    assert humans == 2, "the #249 party has two humans"


@needs_dos_saves
def test_item_names_are_spelled_out_in_the_item_record():
    """The DOS item record carries its name as ASCII; the C64's 16-byte record
    carries an index into `ITEMNAMES`.

    That is why "do the item ids agree between the ports" is the wrong
    question here: DOS stores no id at all.

    **This one still reads the archives, and could not be moved.** The clean
    corpus holds two item records in total -- THRENDER GRONE's flail and
    banded mail -- and `seen >= 10` is what stops this passing on a corpus too
    small to have found anything. Dropping it to two to reach the specimen
    tree would leave the test green and saying nothing, which is worse than
    reading records whose provenance is unknown for a claim about the *shape*
    of a field rather than its value. What would move it is a `#249` party
    driven through a shop in New Phlan: ten items bought and saved, added to
    the specimen tree.
    """
    where = _save_dir()
    seen = 0
    for path in sorted(where.glob("*.ITM")):
        data = path.read_bytes()
        for at in range(0, len(data), ITEM_SIZE):
            record = data[at:at + ITEM_SIZE]
            text = record[1:1 + record[0]]
            assert record[0] <= 41, path.name
            assert all(32 <= c < 127 for c in text), path.name
            assert text.strip(), path.name
            seen += 1
    assert seen >= 10


def _encumbrance_delta(where, path):
    """Stored encumbrance minus (coins + gems + jewelry + carried weight)."""
    record = path.read_bytes()
    coins = sum(_u16(record, MONEY + 2 * n) for n in range(7))
    items = path.with_suffix(".ITM")
    carried = 0
    if items.exists():
        data = items.read_bytes()
        for at in range(0, len(data), ITEM_SIZE):
            item = data[at:at + ITEM_SIZE]
            carried += _u16(item, ITEM_WEIGHT) * (item[ITEM_QUANTITY] or 1)
    return _u16(record, ENCUMBRANCE) - coins - carried


@needs_specimens
def test_encumbrance_balances_against_money_and_item_weights():
    """`0x102` = coins + gems + jewelry + sum of weight x quantity.

    Self-contained arithmetic across three separate structures, so it fixes
    the money block at `0x088`, the 63-byte item stride and the weight at
    `+0x37` at once.

    **27 of 27 balance exactly**, with no tolerance: the eighteen records of
    the `#249` party in its three states, `#84`'s eight rolls, and THRENDER
    GRONE. The tolerance of two this test used to carry was calibrated on the
    archives' edited party, where ASTRID and GILES miss by -65 and -20, and
    `#246` retracted the reading that explained them.

    Twenty-six of the twenty-seven carry no items, so they fix the money term
    and nothing else. The item term rests on THRENDER GRONE alone: 646 stored
    against 146 in coins and 500 in a flail and banded mail.
    """
    exact = total = 0
    for name in CLEAN_PARTY[:2] + (CLEAN_WITH_ITEMS,):
        where = specimen(name)
        for path in sorted(where.glob("CHRDAT*.SAV")):
            if path.stat().st_size != RECORD_SIZE:
                continue
            total += 1
            exact += _encumbrance_delta(where, path) == 0
    for name in CLEAN_ROLLS + (CLEAN_PARTY[2],):
        where = specimen(name)
        for path in sorted(where.glob("*.CHA")):
            if path.stat().st_size != RECORD_SIZE:
                continue
            total += 1
            exact += _encumbrance_delta(where, path) == 0
    assert total >= 27
    assert exact == total, f"{exact} of {total} balanced"


@needs_specimens
def test_the_stored_encumbrance_is_one_debit_behind_after_the_trainer_charges():
    """A character the training hall has just charged carries an encumbrance
    1000 too high, and 1000 gold pieces is exactly the fee it paid.

    This is `#225 (A shopped Curse character's stored encumbrance is three
    tenths above the sum)`'s finding on a second title and a second kind of
    transaction: the engine debits the purse and writes the record without
    recomputing `0x102`, so the stored weight is the purse as it stood before
    the charge.

    The differential is inside one specimen pair. Both runs went in with the
    same poked 20000 gold and matching encumbrance -- ours, written by
    `tools/dostrainprobe.py`, so no reading here is of a number we wrote. In
    `WISH-SPEC-por-party-trained-c2` the clerics' school trained WISHCLE and
    WISHHEL and took 1000 gold from each: those two come out at +1000 and the
    four it never touched at 0. In `WISH-SPEC-por-train-clamp`, where TRAIN
    CHARACTER was pressed and refused, no fee was charged and all six are 0.
    """
    charged = {"WISHCLE", "WISHHEL"}
    trained = {}
    for path in sorted(specimen("por-party-trained-c2").glob("CHRDAT*.SAV")):
        record = path.read_bytes()
        trained[_name(record)] = _encumbrance_delta(
            specimen("por-party-trained-c2"), path)
    assert len(trained) == 6, trained
    for who, delta in trained.items():
        assert delta == (1000 if who in charged else 0), (who, delta)

    for path in sorted(specimen("por-train-clamp").glob("CHRDAT*.SAV")):
        delta = _encumbrance_delta(specimen("por-train-clamp"), path)
        assert delta == 0, (_name(path.read_bytes()), delta)


@needs_specimens
def test_an_exported_character_carries_only_the_weight_of_its_coins():
    """The same identity with the item term empty. Exact, for all fourteen
    exports the game wrote for us.

    The six of the `#249` party plus `#84`'s eight, every one a `.CHA` the
    creation screen wrote before the character had been anywhere. That is why
    it says nothing about whether an export *drops* an item: none of these
    ever had one.
    """
    checked = 0
    for filename, record in _clean_records(
            CLEAN_ROLLS, (CLEAN_PARTY[2],)).items():
        coins = sum(_u16(record, MONEY + 2 * n) for n in range(7))
        assert _u16(record, ENCUMBRANCE) == coins, filename
        checked += 1
    assert checked >= 14


# --- byte order ---------------------------------------------------------------

@needs_specimens
def test_the_dos_record_is_little_endian():
    """`docs/117` asserted it; the Amiga proved the assertion needed checking.

    **Two readings, not the three this test used to make.**

    *Experience.* The five numbers the training hall itself wrote -- 3000 and
    5000 in `WISH-SPEC-por-party-trained-c2`, 5000, 2500 and 4000 in
    `WISH-SPEC-por-train-clamp` -- are level-2 and level-3 thresholds read
    little-endian, and eight to thirteen million read the other way round.
    The party's own saved records hold experience 0, which reads the same
    either way, so the reading rests on the engine's five rather than on
    twenty-six zeroes.

    *Age.* WISHMAG the elf is 164, and 41984 byte-swapped.

    *The encumbrance identity is not the third reading, and never was.*
    Swapping the bytes of both sides of `encumbrance == coins` preserves the
    equality whenever the purse holds one denomination, which is every clean
    record: 26 of the 27 pass the swapped check as well as the straight one.
    The old assertion that no record survived a byte swap held only because
    every record in the archives' party carried items, which makes
    `encumbrance == coins` false read either way round. It was measuring the
    item term, not the byte order.
    """
    absurd = 0
    for filename, record in _clean_records(
            CLEAN_PARTY, CLEAN_ROLLS, CLEAN_TRAINED).items():
        little = int.from_bytes(record[EXPERIENCE:EXPERIENCE + 3], "little")
        assert little < 500_000 or little == 300_000, (filename, little)
        if RACES[record[RACE]] == "elf":
            assert _u16(record, AGE) < 1000, filename
            assert struct.unpack_from(">H", record, AGE)[0] > 1000, filename
    for filename, record in _clean_records(CLEAN_TRAINED).items():
        little = int.from_bytes(record[EXPERIENCE:EXPERIENCE + 3], "little")
        big = int.from_bytes(record[EXPERIENCE:EXPERIENCE + 3], "big")
        if little == 300_000:
            continue                    # went in as ours, not the game's
        assert little in (2500, 3000, 4000, 5000), (filename, little)
        absurd += big >= 1_000_000
    assert absurd == 5, "five experience values the trainer wrote itself"


@pytest.mark.skip(reason="no clean specimen holds two saves of one party "
                         "with experience earned between them (#246)")
@needs_dos_saves
def test_experience_rises_between_the_two_saves_of_one_party():
    """Slot B is the earlier save of the same six characters, and Gold Box
    splits experience evenly -- so all six gained the same amount.

    **Skipped rather than moved, and the reason is the point.** The only
    corpus this has ever run against is the archives' A and B slots, which
    Gold Box Companion had open on 2026-08-17; all six characters there
    gained exactly 2337, which is equally the shape of a party that fought
    together and the shape of one edit applied to six records. `#246 (Nothing
    tells an engine-written DOS record from one edited with Gold Box
    Companion, and conclusions already rest on edited ones)` found nothing
    else on this machine that supports it.

    The `#249` party cannot replace it yet: its slot C and slot E saves
    bracket the New Phlan tour, which awards nothing, so both hold experience
    0. What would settle it is two saves of that party with one driven fight
    between them, added to the specimen tree, and this test re-pointed at
    them.
    """
    where = _save_dir()
    gains = []
    for n in range(1, 7):
        early = where / f"CHRDATB{n}.SAV"
        late = where / f"CHRDATA{n}.SAV"
        if not (early.exists() and late.exists()):
            pytest.skip("needs both the A and B slots of one party")
        a, b = late.read_bytes(), early.read_bytes()
        if _name(a) != _name(b):
            pytest.skip("the A and B slots hold different parties")
        gains.append(_experience(a) - _experience(b))
    assert all(gain >= 0 for gain in gains), gains
    assert len(set(gains)) == 1, gains


# --- the saved game -----------------------------------------------------------

def _clean_savgams():
    """Every `SAVGAM?.DAT` in the clean corpus, keyed `<specimen>/<filename>`.

    Five saves the game wrote for us: slot C at the roster, slot E after the
    New Phlan tour, slot F twice out of the training hall, and slot D from
    `#232`'s readied item.
    """
    return specimen_files(
        CLEAN_PARTY[:2] + CLEAN_TRAINED + (CLEAN_WITH_ITEMS,), (".DAT",))


@needs_specimens
def test_savgam_is_a_word_array_of_the_engines_variable_space():
    """One header byte, then `u16le` per ECL address from `$4900`.

    The mechanism is in the Curse reimplementation: `vm_SetMemoryValue` ends
    in `field_6A00_Set(0x6A00 + (location * 2), value)`, and `ovr021.cs`
    annotates the same array `// as WORD[]`.

    Five saves the game wrote for us, all 13137 bytes.
    """
    saves = _clean_savgams()
    assert len(saves) >= 5
    for filename, save in saves.items():
        assert len(save) == SAVGAM_SIZE, filename
        assert (len(save) - 1) % 2 == 0, filename
        assert len(_words(save)) == SAVGAM_WORDS, filename


@needs_specimens
def test_the_quest_flags_are_where_the_ecl_addresses_say_they_are():
    """`$4A20`-`$4AF8`, at file offset `1 + 2 * (address - $4900)`.

    Every nonzero entry in the 217-entry window is a value a C64 flag byte
    could hold -- the region is the C64's bytes widened to words, so nothing
    in it may exceed 255.

    And a differential the archives could not give: the same party saved
    twice, once from the roster before BEGIN ADVENTURING and once after
    Rolf's tour of New Phlan, with nothing else done in between. The first
    save has all 217 words zero, so nothing in the window is set by merely
    existing; the second has exactly one, `$4AC5` at 1. Twelve words changed
    in the whole 2560-word array over that tour, and one of the twelve landed
    inside the window this test claims.
    """
    for filename, save in _clean_savgams().items():
        window = _words(save)[FLAGS_FIRST - SAVGAM_BASE:
                              FLAGS_LAST - SAVGAM_BASE + 1]
        assert len(window) == 217, filename
        assert max(window) <= 255, (filename, max(window))

    def window_of(name, filename):
        words = _words((specimen(name) / filename).read_bytes())
        return words[FLAGS_FIRST - SAVGAM_BASE:FLAGS_LAST - SAVGAM_BASE + 1]

    roster = window_of("por-party-l1", "SAVGAMC.DAT")
    toured = window_of("por-party-l1-intown", "SAVGAME.DAT")
    assert not any(roster), "a party that has never adventured has no flags set"
    set_by_the_tour = [(FLAGS_FIRST + n, value)
                       for n, value in enumerate(toured) if value]
    assert set_by_the_tour == [(0x4AC5, 1)], set_by_the_tour


@needs_dos_saves
def test_the_slums_flags_are_set_together():
    """`$4ACA`-`$4AD0` is one run of seven `SAVE 255` sites in `ECL14`
    (`work/reports/quest-flags.md`), so a save either has all seven or none.

    A base address off by one would straddle the run, which is what fixes it
    at `$4900` rather than near it.

    **This one still reads the archives, and it is the corpus that is wrong
    with it.** The run is seven zeroes in every save the `#249` party has
    made, because that party has not been near the slums, and seven zeroes in
    a row prove nothing about where the run starts. The positive evidence --
    seven words all holding 255 -- exists on this machine only in the party
    Gold Box Companion had open. It is corroborated independently by the
    seven `SAVE 255` sites in `ECL14` (`work/reports/quest-flags.md`), which
    is code rather than a save and cannot have been edited, so the claim
    stands; what is missing is a specimen. Driving a party through the slums
    and saving would supply one (`#246`).
    """
    for slot in "ABJ":
        words = _words(_savgam(slot))
        run = words[0x4ACA - SAVGAM_BASE:0x4AD1 - SAVGAM_BASE]
        assert len(run) == 7
        assert len(set(run)) == 1, (slot, run)
        assert run[0] in (0, 255), (slot, run)


# --- the rest of the family ---------------------------------------------------

@needs_dos_saves
def test_the_dos_record_grows_with_every_title():
    """285, 422, 439, 510 -- Pool of Radiance, Curse, Secret, Pools of
    Darkness. The C64 record does not grow: Curse reuses Pool of Radiance's
    580 bytes at the same offsets.

    So "the record transfers between titles" is a C64 fact. A DOS reader is
    per title, and anything aimed at Pools of Darkness that assumes the
    285-byte record is wrong by 225 bytes.

    **The corpus is the archives and stays there.** What is measured is a file
    length, which is the one property a character editor cannot change without
    the game refusing the record, so an edited save is as good a witness as any
    for it. Pool of Radiance's 285 is corroborated directly by the specimen
    tree: every record `#249` and `#84` watched the game write is 285 bytes.
    Curse, Silver Blades and Pools of Darkness have no clean specimen at all
    -- `#249` built a Pool of Radiance party only.
    """
    expected = {"POOLRAD": 285, "CURSE": 422, "SECRET": 439,
                "Pools of Darkness": 510}
    dirs = _game_dirs()
    if not dirs:
        pytest.skip("no DOS Gold Box game folders here")
    checked = 0
    for title, size in expected.items():
        where = dirs.get(title)
        if where is None:
            continue
        records = sorted(where.glob("CHRDAT*.SAV"))
        if not records:
            continue
        assert {p.stat().st_size for p in records} == {size}, title
        checked += 1
    assert checked >= 2, "expected at least two DOS titles to measure"


@needs_dos_saves
def test_item_and_effect_strides_are_constant_across_the_family():
    """63 bytes an item and 9 an effect in the archives' own files.

    The suffix changes per title -- `.ITM` for Pool of Radiance, `.SWG` for
    Curse, `.STF` for Silver Blades, `.THG` for Pools of Darkness; `.SPC`,
    `.FX`, `.SFX`, `.EFX` for the effects -- and **Silver Blades' item is 67
    bytes, not 63** (#113). This walks the archives, which ship no `.STF` at
    all because no shipped Silver Blades character carries anything, so the
    63 it asserts is the other three titles'; the 67 is pinned by
    `test_silver_blades_items_are_67_bytes_in_a_stf_file`.

    Archives again, and for the same reason as the test above: a stride is a
    file length divided by a count, and no editor moves it. Pool of Radiance's
    63 is corroborated on a clean record by
    `test_item_count_predicts_the_item_file_exactly`.
    """
    dirs = _game_dirs()
    if not dirs:
        pytest.skip("no DOS Gold Box game folders here")
    items = effects = 0
    for where in dirs.values():
        for suffix in (".ITM", ".THG", ".SWG"):
            for path in where.glob(f"*{suffix}"):
                assert path.stat().st_size % ITEM_SIZE == 0, path.name
                items += 1
        for suffix in (".SPC", ".FX", ".SFX", ".EFX"):
            for path in where.glob(f"*{suffix}"):
                assert path.stat().st_size % EFFECT_SIZE == 0, path.name
                effects += 1
    assert items and effects


@needs_dos_saves
def test_the_later_titles_store_each_ability_twice():
    """From Curse onwards `0x010`-`0x01B` is six (base, current) pairs and
    `0x01C`-`0x01D` exceptional strength twice. Pool of Radiance stores each
    once at `0x010`-`0x016`, which is why every field after it moves.

    **Unmoved, and this is the weakest of the three that stay.** Unlike a file
    length, a doubled ability is a *value*, and a character editor that wrote
    one half of a pair and not the other would show up here as a record that
    does not double -- which is what `doubled >= len(records) - 1` already
    tolerates one of. The clean corpus cannot help: it is Pool of Radiance,
    which is the title that does *not* double. A Curse or Silver Blades party
    rolled the way `#249` rolled this one is what would settle it."""
    dirs = _game_dirs()
    for title in ("CURSE", "SECRET", "Pools of Darkness"):
        where = dirs.get(title)
        if where is None:
            continue
        records = sorted(where.glob("CHRDAT*.SAV"))
        if not records:
            continue
        doubled = 0
        for path in records:
            block = path.read_bytes()[ABILITIES:ABILITIES + 12]
            if all(block[n] == block[n + 1] for n in range(0, 12, 2)):
                doubled += 1
        assert doubled >= len(records) - 1, title


# --- what a Curse character's items are called ---------------------------------
# Measured in the running game rather than assumed: the party bought a battle
# axe at the Weaponers of Cormyr and the file that appeared beside
# `CHRDATI1.SAV` was `CHRDATI1.SWG` (#113). No archives are needed for the
# test, and no save is copied into the repository -- the record and the item
# below are built here from the documented layout.

def _synthetic_curse_character(items: int) -> bytearray:
    """A 422-byte Curse record carrying nothing but a name and an item count."""
    from goldbox import dos_layout

    record = bytearray(dos_layout.CURSE_OF_THE_AZURE_BONDS.record_size)
    name = b"SHOPPER"
    record[0] = len(name)
    record[1:1 + len(name)] = name
    fields = {f.name: f for f in dos_layout.layout_for("curse-of-the-azure-bonds")}
    record[fields["item_count"].offset] = items
    return record


def _synthetic_battle_axe() -> bytearray:
    """One 63-byte item record: type 1, 7.5 lb, 5 gold, nothing else set."""
    from goldbox import dos_layout

    item = bytearray(dos_layout.ITEM_SIZE)
    line = b"Battle Axe "
    item[0] = len(line)
    item[1:1 + len(line)] = line
    item[0x02E] = 1                       # type index
    item[0x037] = 75                      # weight, tenths of a pound
    item[0x03A] = 5                       # value, gold
    return item


def test_a_curse_character_keeps_its_items_in_a_swg_file(tmp_path):
    """The suffix is `.SWG`, and a reader looking for `.ITM` finds nothing.

    This is the failure it guards against and the reason it went unnoticed
    for so long: `_sibling` reads a missing file as empty, so a character
    whose record says three items reads back as carrying none -- exactly
    what every shipped pregen looks like.
    """
    from goldbox import dos

    record = tmp_path / "CHRDATC1.SAV"
    record.write_bytes(_synthetic_curse_character(1))
    (tmp_path / "CHRDATC1.SWG").write_bytes(_synthetic_battle_axe())

    character = dos.read_character(record)
    assert character.get("item_count") == 1
    assert len(character.items) == 1, "the .SWG file was not read"
    assert character.items[0].get("type_index") == 1
    assert character.items[0].get("weight") == 75
    assert character.items[0].get("value") == 5


def test_a_curse_item_file_under_the_old_name_is_not_read(tmp_path):
    """`.ITM` beside a Curse record is not that character's item file.

    The counterpart of the test above: with the suffix restored to `.ITM`
    the first test passes and this one fails, so the pair pins the direction
    rather than merely the fact that some suffix works.
    """
    from goldbox import dos

    record = tmp_path / "CHRDATC1.SAV"
    record.write_bytes(_synthetic_curse_character(1))
    (tmp_path / "CHRDATC1.ITM").write_bytes(_synthetic_battle_axe())

    character = dos.read_character(record)
    assert character.get("item_count") == 1
    assert not character.items, "an .ITM beside a Curse record was read"


# --- and Silver Blades', which are a different length in a different file ------
# Also measured in the running game: Silver Blades' opening gives the party
# twelve magic items, and `CHRDATC1.STF` came to 804 bytes for an item count
# of 12 -- 12 x 67, and not divisible by 63 (#113).

SILVER_BLADES_ITEM_SIZE = 67


def _synthetic_silver_blades_character(items: int) -> bytearray:
    from goldbox import dos_layout

    record = bytearray(dos_layout.SECRET_OF_THE_SILVER_BLADES.record_size)
    name = b"TAKER"
    record[0] = len(name)
    record[1:1 + len(name)] = name
    fields = {f.name: f
              for f in dos_layout.layout_for("secret-of-the-silver-blades")}
    record[fields["item_count"].offset] = items
    return record


def _synthetic_silver_blades_items() -> bytearray:
    """Two 67-byte records: a 6 lb sword worth 2000, then 30 arrows worth 50.

    The second one is what pins the stride. Sliced at 63 its fields land four
    bytes into the wrong place and the quantity reads 0 instead of 30.
    """
    out = bytearray()
    for line, type_index, weight, quantity, value in (
            (b"Long Sword +1 ", 18, 60, 0, 2000),
            (b"30 Arrows +1 ", 30, 4, 30, 50)):
        item = bytearray(SILVER_BLADES_ITEM_SIZE)
        item[0] = len(line)
        item[1:1 + len(line)] = line
        item[0x02E] = type_index
        item[0x032] = 1                                   # plus
        item[0x037:0x039] = weight.to_bytes(2, "little")
        item[0x039] = quantity
        item[0x03A:0x03C] = value.to_bytes(2, "little")
        out += item
    return out


def test_silver_blades_items_are_67_bytes_in_a_stf_file(tmp_path):
    """`.STF`, stride 67, and every field still at Pool of Radiance's offset."""
    from goldbox import dos

    record = tmp_path / "CHRDATC1.SAV"
    record.write_bytes(_synthetic_silver_blades_character(2))
    (tmp_path / "CHRDATC1.STF").write_bytes(_synthetic_silver_blades_items())

    character = dos.read_character(record)
    assert len(character.items) == 2, "the .STF file was not read"
    first, second = character.items
    assert first.get("type_index") == 18 and first.get("value") == 2000
    # The second record is the one a 63-byte stride gets wrong.
    assert second.get("type_index") == 30
    assert second.get("quantity") == 30
    assert second.get("weight") == 4
    assert second.get("value") == 50


# --- an item file present and the wrong shape is a defect, not a gap (#221) ----
# `min(count, len(itm) // stride)` used to paper over exactly this: a sibling
# file that exists but does not reconcile with the record's own item count
# read back as fewer items, with nothing to say why. #113's fix was to find
# the *file*; this is the fix for the file being the wrong length.

def test_an_item_file_short_of_a_whole_number_of_items_is_refused(tmp_path):
    """63 x 1 - 1 = 62 bytes: not a whole number of 63-byte items."""
    from goldbox import dos

    record = tmp_path / "CHRDATC1.SAV"
    record.write_bytes(_synthetic_curse_character(1))
    truncated = _synthetic_battle_axe()[:-1]
    assert len(truncated) == 62
    (tmp_path / "CHRDATC1.SWG").write_bytes(truncated)

    with pytest.raises(dos.DosRecordError, match=r"CHRDATC1\.SWG.*62.*63"):
        dos.read_character(record)


def test_an_item_file_that_is_present_and_empty_is_refused(tmp_path):
    """Present and zero bytes is the case the absent-file silence must not cover.

    `#221 (An item file that does not match its own count is read silently)`
    turns on telling "no sibling file" from "a sibling file that is the wrong
    shape", and a zero-byte file is the one that looks like both.  `_sibling`
    handed back `b""` for either, which is why the check had to move out of it.
    """
    from goldbox import dos

    record = tmp_path / "CHRDATC1.SAV"
    record.write_bytes(_synthetic_curse_character(1))
    (tmp_path / "CHRDATC1.SWG").write_bytes(b"")

    with pytest.raises(dos.DosRecordError, match=r"CHRDATC1\.SWG.*0.*1"):
        dos.read_character(record)


def test_an_item_file_short_of_the_records_own_count_is_refused(tmp_path):
    """The record claims two items; the sibling file only holds one."""
    from goldbox import dos

    record = tmp_path / "CHRDATC1.SAV"
    record.write_bytes(_synthetic_curse_character(2))
    (tmp_path / "CHRDATC1.SWG").write_bytes(_synthetic_battle_axe())

    with pytest.raises(dos.DosRecordError, match=r"CHRDATC1\.SWG.*1.*2"):
        dos.read_character(record)


def test_an_absent_item_file_is_still_read_quietly(tmp_path):
    """No sibling at all is the documented, deliberate case: an export."""
    from goldbox import dos

    record = tmp_path / "CHRDATC1.SAV"
    record.write_bytes(_synthetic_curse_character(1))

    character = dos.read_character(record)
    assert character.get("item_count") == 1
    assert not character.items
