from __future__ import annotations

"""The tables a title keeps outside the character record.

Level caps, experience thresholds, racial class limits, spell names, item
names, and where each of those lives once the overlay that owns it is
resident. Everything here is read off the player's own disks at run time and
skips when they are absent -- `AGENTS.md` forbids the game's tables in this
repository, test fixture or not.

**Every address here was fitted or read out of the game's own code, never out
of a PRG header**, because every overlay lies about its load address. The two
that matter:

* `GEN` -- character generation and the training hall -- is resident at
  `$0800` in both Pool of Radiance and Curse. Fixed by a table landing exactly
  on its own file offset at that base, then corroborated by the instructions
  two bytes away that read it.
* `LIBRARY` is at `$2C48` in Pool of Radiance and `$2DC8` in every later
  title. `test_the_library_base_is_fitted_not_read` re-derives both here.

Disk lookup is borrowed rather than duplicated: `tests/gamedata.py` for Pool of
Radiance and Curse, `tests/test_silverblades.py` for Silver Blades. Champions
of Krynn has no finder anywhere yet, so there is one below, and it identifies
the disk by what its `ITEMNAMES` says rather than by a file name -- Death
Knights of Krynn carries the same race labels and would otherwise match.
"""


import functools
import os
import pathlib

import pytest

from goldbox import games, items, levels, spells
from goldbox.d64 import D64
from tests import gamedata
from tests.test_silverblades import ssb_dir

_REPO = pathlib.Path(__file__).resolve().parent.parent

POOL = games.POOL_OF_RADIANCE
CURSE = games.CURSE_OF_THE_AZURE_BONDS
SSB = games.SECRET_OF_THE_SILVER_BLADES
COK = games.CHAMPIONS_OF_KRYNN
DKK = games.DEATH_KNIGHTS_OF_KRYNN

#: `GEN` declares $1000 (Pool of Radiance) or $1220 (Curse) and runs at neither.
GEN_BASE = 0x0800

#: Where `LIBRARY` really is. Pool of Radiance alone is at $2C48.
LIBRARY_BASE_POOL = 0x2C48
LIBRARY_BASE_LATER = 0x2DC8

#: Pool of Radiance's class-level ceiling table, and the racial limits beside
#: it. Both addresses come from the instructions that read them, three bytes
#: apart, in the routine that raises a level.
POOL_CLASS_CAPS = 0x1E5C
POOL_RACIAL_LIMITS = 0x1E60

#: Curse's three, all in `GEN`: the ceiling per class, the racial limits, and
#: the experience thresholds. Curse's racial rows are eight wide where Pool of
#: Radiance's are four, because Curse implements two more classes.
CURSE_CLASS_CAPS = 0x15A1
CURSE_RACIAL_LIMITS = 0x15A9
CURSE_EXPERIENCE = 0x136E
CURSE_XP_ROW = 39           # 13 levels x 3 bytes
CURSE_XP_LEVELS = 13

#: Curse's spell-name strings load here. `COMBAT2` is strings first, then a
#: high-byte array, then a low-byte array -- the reverse of `SPELLN00`'s order.
CURSE_SPELL_BASE = 0xE000
CURSE_SPELL_TEXT_END = 0x7DB
CURSE_SPELL_ENTRIES = 170

#: 99 is the game's "no limit". Humans read it in every class they may take.
UNLIMITED = 99

#: Silver Blades and the Krynn titles index the race label as a string in
#: `ITEMNAMES`'s own pool rather than keeping one in `LIBRARY`.
RACE_LABEL_POOL_INDEX = 140


# --- finding the disks -------------------------------------------------------

def _shallow_roots():
    home = pathlib.Path.home()
    out = [pathlib.Path.cwd(), home / "Documents", home / "Games",
           home / "c64", home / "roms", home / "Downloads", _REPO / "work"]
    for env in ("POR_DISKS", "COAB_DISKS", "SSB_DISKS", "COK_DISKS"):
        where = os.environ.get(env)
        if where:
            out.append(pathlib.Path(where))
    return out


@functools.lru_cache(maxsize=1)
def _champions_side_a():
    """The Champions of Krynn side carrying `ITEMNAMES`, or None.

    Identified by content. Champions and Death Knights of Krynn ship the same
    seven Krynn race labels, so the race table cannot tell them apart; the coin
    names can, because Death Knights makes every coin STEEL.
    """
    for root in _shallow_roots():
        for pattern in ("*.[dD]64", "*/*.[dD]64", "*/*/*.[dD]64"):
            try:
                paths = sorted(root.glob(pattern))
            except OSError:
                continue
            for path in paths:
                try:
                    disk = D64.open(path)
                except Exception:
                    continue
                if disk.find(b"ITEMNAMES") is None or disk.find(b"LIBRARY") is None:
                    continue
                try:
                    names = items.load_item_names(str(path), COK)
                except Exception:
                    continue
                if names.get(145) == "KENDER" and names.get(174) == "SILVER":
                    return path
    return None


@functools.lru_cache(maxsize=1)
def _death_knights_side():
    """The Death Knights of Krynn side carrying `ITEMNAMES`, or None."""
    for root in _shallow_roots():
        for pattern in ("*.[dD]64", "*/*.[dD]64", "*/*/*.[dD]64"):
            try:
                paths = sorted(root.glob(pattern))
            except OSError:
                continue
            for path in paths:
                try:
                    disk = D64.open(path)
                except Exception:
                    continue
                if disk.find(b"ITEMNAMES") is None:
                    continue
                try:
                    names = items.load_item_names(str(path), DKK)
                except Exception:
                    continue
                if names.get(145) == "KENDER" and names.get(174) == "STEEL":
                    return path
    return None


def champions_disk() -> pathlib.Path:
    path = _champions_side_a()
    if path is None:
        pytest.skip("needs a Champions of Krynn side carrying ITEMNAMES; "
                    "set COK_DISKS to where the disks are")
    return path


def death_knights_disk() -> pathlib.Path:
    path = _death_knights_side()
    if path is None:
        pytest.skip("needs a Death Knights of Krynn side carrying ITEMNAMES")
    return path


def silver_blades_disk(stem_file: bytes = b"LIBRARY") -> pathlib.Path:
    where = ssb_dir()
    if where is None:
        pytest.skip("needs the Silver Blades disks; set SSB_DISKS")
    for path in sorted(where.glob("SILVER*.[dD]64")):
        try:
            disk = D64.open(path)
        except Exception:
            continue
        if disk.find(stem_file) is not None:
            return path
    pytest.skip(f"no Silver Blades side here carries {stem_file!r}")


def _curse_payload(name: str) -> bytes:
    """`gamedata.curse_file` hands back the whole PRG, load address and all,
    where `gamedata.game_file` peels it off. Every address here is a payload
    offset, so the two have to be made to agree."""
    return gamedata.curse_file(name)[2:]


def _payload(path, name: bytes) -> bytes:
    disk = D64.open(path)
    entry = disk.find(name)
    if entry is None:
        pytest.skip(f"{pathlib.Path(path).name} carries no {name!r}")
    return disk.read_file(entry)[2:]


def _at(payload: bytes, base: int, address: int, count: int) -> bytes:
    """The `count` bytes at a live address, given the overlay's real base."""
    start = address - base
    assert 0 <= start <= len(payload) - count, (
        f"${address:04X} is outside a {len(payload)}-byte overlay at ${base:04X}")
    return payload[start:start + count]


# --- level ceilings ----------------------------------------------------------

def test_pool_of_radiance_stops_at_six_six_nine_eight():
    """The ceiling `docs/89-level-tables.md` shows, as a table in the game.

    Eight bytes in class-bit order -- magic-user, cleric, thief, fighter, then
    four the game does not implement. `goldbox/spells.py` and `goldbox/layout.py`
    already read `class_bits` that way; this is the same order in the game's
    own data, which is what makes the reading more than a convention.
    """
    gen = gamedata.game_file("GEN")
    caps = _at(gen, GEN_BASE, POOL_CLASS_CAPS, 8)
    assert list(caps) == [6, 6, 9, 8, 0, 0, 0, 0]
    for name, table in (("magic-user", levels.MAGIC_USER), ("cleric", levels.CLERIC),
                        ("thief", levels.THIEF), ("fighter", levels.FIGHTER)):
        index = {"magic-user": 0, "cleric": 1, "thief": 2, "fighter": 3}[name]
        assert caps[index] == table[-1].level, name


def test_the_pool_of_radiance_ceiling_is_cited_not_guessed():
    """`CMP $1E5C,X` sits in the routine that raises a level. Without this the
    table above is eight plausible bytes at an address nothing reads."""
    gen = gamedata.game_file("GEN")
    read = bytes([0xDD, POOL_CLASS_CAPS & 0xFF, POOL_CLASS_CAPS >> 8])   # CMP abs,X
    load = bytes([0xBD, POOL_CLASS_CAPS & 0xFF, POOL_CLASS_CAPS >> 8])   # LDA abs,X
    assert read in gen and load in gen


def test_curse_raises_every_ceiling_and_adds_two_classes():
    """Curse's own numbers: magic-user 11, cleric 10, thief 12, fighter 12,
    paladin 11, ranger 11 -- and nothing at bits 4 and 5, which is how the
    array says Curse has no knight where the Krynn titles do."""
    gen = _curse_payload("GEN")
    caps = _at(gen, GEN_BASE, CURSE_CLASS_CAPS, 8)
    assert list(caps) == [11, 10, 12, 12, 0, 0, 11, 11]
    pool = _at(gamedata.game_file("GEN"), GEN_BASE, POOL_CLASS_CAPS, 8)
    for bit in (0, 1, 2, 3):
        assert caps[bit] > pool[bit], f"class bit {bit} did not rise"


def test_the_curse_ceiling_is_read_beside_the_per_class_level_array():
    """`LDA $7CC9,X : CMP $15A1,X`. `$7C00` is Curse's character record and
    `0x0C9` is the eight-byte per-class level array, so the instruction pair
    ties the ceiling table to the exact field an editor would write."""
    gen = _curse_payload("GEN")
    pair = bytes([0xBD, 0xC9, 0x7C,                     # LDA $7CC9,X
                  0xDD, CURSE_CLASS_CAPS & 0xFF, CURSE_CLASS_CAPS >> 8])
    assert pair in gen


# --- racial limits -----------------------------------------------------------

def test_pool_of_radiance_carries_the_add_racial_limits():
    """Four bytes a race, in the same class-bit order, indexed `race * 4`.

    Checked against AD&D 1st edition rather than against itself: half-orc
    cleric 4 / thief 8 / fighter 10 and half-elf 8/5/unlimited/8 are the two
    rows no other reading of the table would produce.
    """
    gen = gamedata.game_file("GEN")
    rows = {race: list(_at(gen, GEN_BASE, POOL_RACIAL_LIMITS + race * 4, 4))
            for race in range(8)}
    assert rows[0] == [0, 0, 0, 0]                       # race 0 is nobody
    assert rows[1] == [0, 8, UNLIMITED, 9]               # dwarf
    assert rows[2] == [11, 7, UNLIMITED, 7]              # elf
    assert rows[4] == [8, 5, UNLIMITED, 8]               # half-elf
    assert rows[6] == [0, 4, 8, 10]                      # half-orc
    assert rows[7] == [UNLIMITED] * 4                    # human
    for code, name in POOL.races:
        if name == "monster":
            continue
        assert code in rows, name


def test_curse_widens_the_racial_rows_to_eight_and_tightens_the_cleric():
    """Two changes, and the second is the interesting one.

    The rows are eight wide because Curse implements paladin and ranger, and
    half-elf ranger 8 is where that shows. And Curse zeroes the cleric column
    for dwarf, elf and gnome, where Pool of Radiance carried 8, 7 and 7 --
    those are the *Dungeon Master's Guide* NPC limits, and clerics of those
    three races are not player characters in the *Players Handbook* at all. So
    Curse is the stricter reading of the same rule, not a different rule.
    """
    gen = _curse_payload("GEN")
    rows = {race: list(_at(gen, GEN_BASE, CURSE_RACIAL_LIMITS + (race - 1) * 8, 8))
            for race in range(1, 8)}
    assert rows[7] == [UNLIMITED, UNLIMITED, UNLIMITED, UNLIMITED,
                       0, 0, UNLIMITED, UNLIMITED]       # human
    assert rows[4] == [8, 5, UNLIMITED, 8, 0, 0, 0, 8]   # half-elf, ranger at 7
    assert rows[6] == [0, 4, 8, 10, 0, 0, 0, 0]          # half-orc
    assert rows[1][2:4] == [UNLIMITED, 9]                # dwarf thief/fighter
    assert rows[2][0] == 11                              # elf magic-user

    pool = gamedata.game_file("GEN")
    for race in (1, 2, 3):                               # dwarf, elf, gnome
        was = _at(pool, GEN_BASE, POOL_RACIAL_LIMITS + race * 4, 4)[1]
        assert was > 0 and rows[race][1] == 0, f"race {race} cleric column"


def test_the_racial_limit_is_indexed_by_the_records_own_race_byte():
    """`LDA $7C72` is record offset `0x072`, which `goldbox/layout.py` calls race.
    The three shifts after it are the `* 8` that makes the row."""
    gen = _curse_payload("GEN")
    assert bytes([0xAE, 0x72, 0x7C, 0xCA, 0x8A, 0x0A, 0x0A, 0x0A]) in gen


# --- experience --------------------------------------------------------------

def _curse_xp(gen: bytes, row: int) -> list[int]:
    """One class's thresholds. Three bytes each, **big-endian**, unlike every
    other multi-byte number in the family -- the reader walks the entry
    backwards from `level * 3 + 2`, which is what makes the high byte last."""
    at = CURSE_EXPERIENCE - GEN_BASE + row * CURSE_XP_ROW
    return [int.from_bytes(gen[at + k * 3:at + k * 3 + 3], "big")
            for k in range(CURSE_XP_LEVELS)]


CURSE_XP_ROWS = ("magic-user", "cleric", "thief", "fighter", "paladin", "ranger")


@pytest.mark.parametrize("row,name", list(enumerate(CURSE_XP_ROWS)))
def test_curses_experience_table_is_thirteen_rising_thresholds(row, name):
    gen = _curse_payload("GEN")
    values = _curse_xp(gen, row)
    assert values[0] == 0
    assert values == sorted(values)
    assert len(set(values)) == len(values)
    assert values[-1] > 600_000                 # every class passes level 12


@pytest.mark.parametrize("row,name", [(0, "magic-user"), (1, "cleric"),
                                      (2, "thief"), (3, "fighter")])
def test_curse_agrees_with_pool_of_radiance_where_the_tables_overlap(row, name):
    """The strongest thing available without a second specimen: Curse's own
    table reproduces, threshold for threshold, the one `goldbox/levels.py` already
    holds -- so the levels an imported character keeps mean the same number of
    experience points in both games."""
    gen = _curse_payload("GEN")
    values = _curse_xp(gen, row)
    for entry in levels.table(name):
        if entry.level == 1:
            continue
        assert values[entry.level - 1] == entry.experience, (name, entry.level)


def test_the_paladin_and_ranger_rows_are_the_add_tables():
    """Neither class exists in Pool of Radiance, so neither has a control in
    this repository. AD&D 1st edition is the control."""
    gen = _curse_payload("GEN")
    assert _curse_xp(gen, 4)[1:4] == [2751, 5501, 12001]      # paladin
    # 2250, not 2251. Every other threshold in every row of this table is the
    # rulebook's number plus one; the ranger's first is the only one that is
    # not, so a ranger reaches level 2 exactly on the published 2250.
    assert _curse_xp(gen, 5)[1:4] == [2250, 4501, 10001]


def test_the_hit_dice_tables_stand_beside_the_experience_one():
    """Three eight-byte arrays in class-bit order: the die, the level after
    which hit dice stop being rolled, and the flat hit points a level adds
    from then on. d4/d8/d6/d10 and +1/+2/+2/+3 are AD&D's, and paladin d10 +3
    and ranger d8 +2 are the two rows Pool of Radiance has no opinion on."""
    gen = _curse_payload("GEN")
    sides = list(_at(gen, GEN_BASE, 0x161E, 8))
    last = list(_at(gen, GEN_BASE, 0x1626, 8))
    after = list(_at(gen, GEN_BASE, 0x162E, 8))
    assert sides == [4, 8, 6, 10, 0, 0, 10, 8]
    assert after == [1, 2, 2, 3, 0, 0, 3, 2]
    for bit in (0, 1, 2, 3, 6, 7):
        assert 10 <= last[bit] <= 12


# --- spell names -------------------------------------------------------------

def _curse_spell_table(combat2: bytes) -> dict[int, str]:
    """`COMBAT2` decoded: strings, then 170 high bytes, then 170 low bytes.

    Spell id `n` is table index `n - 1`. The strings **overlap** -- SHIELD is
    the tail of FIRE SHIELD, INVISIBILITY the tail of DETECT INVISIBILITY --
    so reading them in order rather than through the pointers silently shifts
    every id above the first shared string.
    """
    high = CURSE_SPELL_TEXT_END
    low = high + CURSE_SPELL_ENTRIES
    out = {}
    for index in range(CURSE_SPELL_ENTRIES):
        address = combat2[low + index] | combat2[high + index] << 8
        offset = address - CURSE_SPELL_BASE
        if not 0 <= offset < CURSE_SPELL_TEXT_END:
            continue
        end = combat2.find(b"\x00", offset)
        if end < 0:
            continue
        out[index + 1] = combat2[offset:end].decode("latin1")
    return out


def test_curse_keeps_its_spell_names_in_combat2_not_in_a_spelln_file():
    """Curse ships no `SPELLN00`. It does ship `SPELLN64`, and so does Pool of
    Radiance, and in neither game is that a spell-name table -- it is the
    icon-editing menu. The spell names are the first two kilobytes of
    `COMBAT2`, which loads at `$E000`."""
    for disk in gamedata.curse_disks():
        assert disk.find(b"SPELLN00") is None
    menu = _curse_payload("SPELLN64")
    assert b"BLESS" not in menu and b"FIREBALL" not in menu
    assert b"WEAPON" in menu and b"SMALL" in menu and b"LARGE" in menu


def test_the_curse_spell_table_resolves_and_its_strings_overlap():
    combat2 = _curse_payload("COMBAT2")
    names = _curse_spell_table(combat2)
    assert len(names) >= 165
    assert names[1] == "BLESS"
    assert names[19] == "SHIELD"
    assert names[85] == "FIRE SHIELD"
    # SHIELD is not a string start: it is the last six bytes of FIRE SHIELD,
    # which is the whole reason the pointer table exists.
    text = combat2[:CURSE_SPELL_TEXT_END]
    at = text.find(b"SHIELD\x00")
    assert at > 0 and text[at - 1] != 0


def test_the_first_fifty_six_spell_ids_are_pool_of_radiances_exactly():
    """`docs/116` claimed this from the item tables; here it is from the spell
    table itself. It is what makes an imported spellbook mean what it said."""
    mine = _curse_spell_table(_curse_payload("COMBAT2"))
    theirs = spells.load_spell_names(str(gamedata.game_disk("POOL1")))
    for spell_id in range(1, spells.LAST_SPELL + 1):
        assert mine.get(spell_id) == theirs.get(spell_id), spell_id


def test_curse_adds_fourth_and_fifth_level_spells_above_fifty_six():
    """Where Pool of Radiance's table turns into combat messages at 57,
    Curse's carries on with the spells its higher ceilings let a caster
    reach."""
    names = _curse_spell_table(_curse_payload("COMBAT2"))
    for spell_id, name in ((71, "CURE CRITICAL WOUNDS"), (74, "FLAME STRIKE"),
                           (82, "CONFUSION"), (91, "CLOUD KILL"),
                           (92, "CONE OF COLD")):
        assert names[spell_id] == name
    assert names[143] == "AND MISSES..."           # the message tail, moved up


# --- item names and the labels folded in with them ---------------------------

def _library_reads(payload: bytes, address: int) -> bool:
    """Is there an `LDA address,X : STA $07` -- the game setting up a pointer
    to a string in that table?"""
    return bytes([0xBD, address & 0xFF, address >> 8, 0x85, 0x07]) in payload


ITEM_NAME_TITLES = [
    pytest.param(POOL, "pool", id="pool-of-radiance"),
    pytest.param(CURSE, "curse", id="curse-of-the-azure-bonds"),
    pytest.param(SSB, "silver", id="secret-of-the-silver-blades"),
    pytest.param(COK, "champions", id="champions-of-krynn"),
]


def _library_of(which: str) -> bytes:
    if which == "pool":
        return gamedata.game_file("LIBRARY")
    if which == "curse":
        return _curse_payload("LIBRARY")
    if which == "silver":
        return _payload(silver_blades_disk(), b"LIBRARY")
    return _payload(champions_disk(), b"LIBRARY")


def _item_names_of(which: str, game) -> dict[int, str]:
    if which == "pool":
        return items.load_item_names(str(gamedata.game_disk("POOL1")), game)
    if which == "curse":
        where = gamedata.curse_dir()
        if where is None:
            pytest.skip("needs the Curse disks")
        for path in sorted(where.glob("CURSE*.[dD]64")):
            try:
                if D64.open(path).find(b"ITEMNAMES") is not None:
                    return items.load_item_names(str(path), game)
            except Exception:
                continue
        pytest.skip("no Curse side here carries ITEMNAMES")
    if which == "silver":
        return items.load_item_names(str(silver_blades_disk(b"ITEMNAMES")), game)
    return items.load_item_names(str(champions_disk()), game)


@pytest.mark.parametrize("game,which", ITEM_NAME_TITLES)
def test_the_item_name_base_is_the_one_the_game_itself_loads(game, which):
    """`$6F00` and `$9E00` were fitted by requiring entry 1 to be BATTLE AXE.
    They are also the literal operand of the instruction in `LIBRARY` that
    reads the table, which is a second and independent line of evidence."""
    assert _library_reads(_library_of(which), game.item_names_load_address)


@pytest.mark.parametrize("game,which", ITEM_NAME_TITLES)
def test_every_title_names_its_first_item_battle_axe(game, which):
    names = _item_names_of(which, game)
    assert names[1] == "BATTLE AXE"
    assert names[2] == "HAND AXE"
    assert len(names) >= 220


@pytest.mark.parametrize("game,which", [
    pytest.param(SSB, "silver", id="secret-of-the-silver-blades"),
    pytest.param(COK, "champions", id="champions-of-krynn"),
])
def test_the_later_titles_fold_the_race_labels_into_the_item_name_pool(game, which):
    """`LDA $9E8C,X` is `$9E00 + 140`: the race label is pool entry
    `140 + race`, read straight out of `ITEMNAMES` with no table in `LIBRARY`
    at all. Pool of Radiance and Curse keep theirs in `LIBRARY` instead, and
    the same instruction is absent there."""
    folded = games.NAMES_LOAD_ADDRESS_LATER + RACE_LABEL_POOL_INDEX
    assert _library_reads(_library_of(which), folded)
    names = _item_names_of(which, game)
    for code, label in game.races:
        assert names[RACE_LABEL_POOL_INDEX + code] == label.upper()


@pytest.mark.parametrize("which", ["pool", "curse"])
def test_the_earlier_titles_keep_their_labels_in_library(which):
    folded = games.NAMES_LOAD_ADDRESS_LATER + RACE_LABEL_POOL_INDEX
    assert not _library_reads(_library_of(which), folded)


def test_champions_race_table_is_death_knights_race_table():
    """Both Krynn titles, read from their own disks and compared to each other
    rather than to `goldbox/games.py`. If they ever disagree this fails and
    `RACES_KRYNN` has to split in two."""
    champions = _item_names_of("champions", COK)
    death = items.load_item_names(str(death_knights_disk()), DKK)
    for code, label in games.RACES_KRYNN:
        index = RACE_LABEL_POOL_INDEX + code
        assert champions[index] == death[index] == label.upper(), code


def test_the_krynn_race_codes_start_at_zero_on_champions_own_disk():
    """Race 0 is a real race in the Krynn titles, which is why `RACES_KRYNN`
    could not keep the Realms titles' "0 means monster"."""
    names = _item_names_of("champions", COK)
    assert names[RACE_LABEL_POOL_INDEX] == "SILVANESTI ELF"
    assert names[RACE_LABEL_POOL_INDEX + 5] == "KENDER"
    assert names[RACE_LABEL_POOL_INDEX + 6] == "HUMAN"


def test_champions_keeps_its_file_stems_where_no_pointer_reaches_them():
    """Why Champions resolves 227 names where Death Knights resolves 250: the
    entries above 227 point at the file-stem table, which is packed with no
    NUL between one stem and the next. `goldbox/items.py` finds no terminator and
    drops them, which is the honest answer -- a stem is not an item name."""
    disk = champions_disk()
    payload = _payload(disk, b"ITEMNAMES")
    assert b"WALLDEF00ANIMATE00" in payload
    names = _item_names_of("champions", COK)
    assert 228 not in names


# --- the resident base of LIBRARY -------------------------------------------

def _fit_library_base(payload: bytes, low: int = 0x2A00, high: int = 0x3000):
    """Score each candidate base by how many `JSR`/`JMP` targets land on a
    routine entry -- the byte after an `RTS`, an `RTI` or a `JMP`.

    Counting targets that merely land *inside* the file gives a plateau
    hundreds of bytes wide, because the window slides with the base. Requiring
    the target to look like the start of a routine collapses it to a spike.
    """
    targets = [payload[i + 1] | payload[i + 2] << 8
               for i in range(len(payload) - 2) if payload[i] in (0x20, 0x4C)]
    scored = []
    for base in range(low, high):
        hits = 0
        for target in targets:
            at = target - base
            if 0 < at < len(payload):
                if payload[at - 1] in (0x60, 0x40, 0x6C):
                    hits += 1
                elif at >= 3 and payload[at - 3] in (0x4C, 0x6C):
                    hits += 1
        scored.append((hits, base))
    scored.sort(reverse=True)
    best = scored[0]
    runner_up = next(s for s in scored if abs(s[1] - best[1]) > 8)
    return best, runner_up


@pytest.mark.parametrize("which,expected", [
    pytest.param("pool", LIBRARY_BASE_POOL, id="pool-of-radiance"),
    pytest.param("curse", LIBRARY_BASE_LATER, id="curse-of-the-azure-bonds"),
    pytest.param("silver", LIBRARY_BASE_LATER, id="secret-of-the-silver-blades"),
    pytest.param("champions", LIBRARY_BASE_LATER, id="champions-of-krynn"),
])
def test_the_library_base_is_fitted_not_read(which, expected):
    """Pool of Radiance's `LIBRARY` declares `$1000` and the rest declare
    `$1220`; none of them runs there. The fit wins by better than three to one
    in every title, which is the bar `docs/144-decoding-a-new-title.md` sets for a
    fitted base."""
    (score, base), (other, _) = _fit_library_base(_library_of(which))
    assert base == expected
    assert score >= 3 * other, f"margin only {score} to {other}"


def test_silver_blades_library_has_no_label_table_to_fit():
    """The fold has a consequence worth asserting: there is nothing in Silver
    Blades' `LIBRARY` for the label-pointer fit to score, because the labels
    are not there. Only the two reads of `ITEMNAMES` remain."""
    payload = _library_of("silver")
    reads = [payload[i + 1] | payload[i + 2] << 8
             for i in range(len(payload) - 5)
             if payload[i] == 0xBD and payload[i + 3] == 0x85
             and payload[i + 4] == 0x07]
    assert reads
    assert all(address >= games.NAMES_LOAD_ADDRESS_LATER for address in reads)
