"""The per-title tables: races, class bits, and where ITEMNAMES loads.

`goldbox/yaml_io.py` used to hold one race table and one class-bit table for all
six titles, and they were Pool of Radiance's. Silver Blades moves human from 7
to 6, the Krynn titles number a different list from 0, and Curse's `ITEMNAMES`
loads at $9E00 rather than $6F00 -- so the shared tables were wrong for four
titles and the item names on five. They now live on the `Game` descriptor.

The evidence is on the player's disks, so the tests that check it read them and
skip when they are absent. Nothing here is a fixture.
"""

from __future__ import annotations

import dataclasses
import functools
import pathlib

import pytest

from goldbox import games, items, yaml_io
from goldbox.d64 import D64, split_load_address

KEYS = [g.key for g in games.GAMES]


# --- finding the player's disks ---------------------------------------------
# `tests/gamedata.py` knows where Pool of Radiance's and Curse's disks are;
# nothing knows where the other four are, and their published directory names
# ("SecretOfTheSilverBlades-Lithium") are nothing a fixed list would guess. So
# look one level down from the places disks live and match `Game.disk_glob`,
# which is already per-title and already right.

def _roots() -> list[pathlib.Path]:
    home = pathlib.Path.home()
    repo = pathlib.Path(__file__).resolve().parent.parent
    bases = [pathlib.Path.cwd(), repo / "work", home, home / "c64",
             home / "Documents", home / "Games", home / "roms",
             home / "Downloads"]
    out: list[pathlib.Path] = []
    for base in bases:
        out.append(base)
        try:
            out += [p for p in sorted(base.iterdir()) if p.is_dir()]
        except OSError:
            continue
    return out


@functools.lru_cache(maxsize=None)
def disks_for(key: str) -> tuple[pathlib.Path, ...]:
    """Every disk image of one title that this machine holds.

    Every root, not the first that hits: `~/c64` holds both a loose
    `Death Knights of Krynn Monitor [the sir].d64` and the real disks a
    directory below, and stopping at the first match found only the monitor.
    """
    glob = games.by_key(key).disk_glob
    out: list[pathlib.Path] = []
    for root in _roots():
        try:
            out += sorted(root.glob(glob))
        except OSError:
            continue
    return tuple(dict.fromkeys(out))


def payloads(key: str, name: bytes):
    """Every copy of a named file across a title's sides, largest first.

    Largest first because a cracked directory can leave a stale short entry
    with a real name -- Gateway's `GATE2` carries a 582-byte `SAVEGATEWAY`
    that decodes as nothing at all.
    """
    out = []
    for path in disks_for(key):
        try:
            disk = D64.open(str(path))
        except Exception:
            continue                       # one Champions side is a 40-track rip
        entry = disk.find(name)
        if entry is None:
            continue
        try:
            out.append(split_load_address(disk.read_file(entry))[1])
        except Exception:
            continue
    return sorted(out, key=len, reverse=True)


def need(key: str, name: bytes) -> bytes:
    found = payloads(key, name)
    if not found:
        pytest.skip(f"no {key} disk here carries {name.decode()}")
    return found[0]


# --- the tables themselves, no disks needed ---------------------------------

def test_every_title_names_its_races_and_classes():
    """All six are known. A title whose list we could not derive would carry
    None here and the editor would show the raw number -- that is the designed
    failure, and there is currently no title in it."""
    for game in games.GAMES:
        assert game.races is not None, game.key
        assert game.class_bits is not None, game.key
        assert game.item_names_load_address is not None, game.key


@pytest.mark.parametrize("key", KEYS)
def test_race_names_are_unique_within_a_title(key):
    """Two codes sharing one name would let an import rewrite one as the other:
    the YAML carries the name, and `_encode` returns the first code that
    matches. This is why Curse's 6 is left unnamed rather than called `human`
    alongside 7."""
    names = [n for _, n in games.by_key(key).races]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("key", KEYS)
def test_every_race_code_survives_the_yaml_round_trip(key):
    game = games.by_key(key)
    table = yaml_io.race_table(game)
    for code in table:
        text = yaml_io._decode(table, code, "race")
        assert yaml_io._encode(table, text, "race") == code


@pytest.mark.parametrize("key", KEYS)
def test_class_bits_are_single_bits_with_distinct_names(key):
    game = games.by_key(key)
    seen = set()
    for bit, name in game.class_bits:
        assert bit and not bit & (bit - 1), f"{name} is not one bit"
        assert bit not in seen and name not in seen
        seen |= {bit, name}


def test_the_module_level_tables_are_pool_of_radiances():
    """`editor/enums.py` and `editor/roster.py` import `RACES` and `CLASS_BITS`
    from `yaml_io` and have no game in hand. They must keep getting the table
    they always got."""
    assert yaml_io.RACES == games.POOL_OF_RADIANCE.race_names
    assert yaml_io.CLASS_BITS == list(games.POOL_OF_RADIANCE.class_bits)
    assert yaml_io.RACES[7] == "human" and yaml_io.RACES[6] == "half-orc"


def test_silver_blades_moves_human_from_seven_to_six():
    ssb = games.SECRET_OF_THE_SILVER_BLADES.race_names
    assert ssb[6] == "human"
    assert 7 not in ssb
    assert ssb[3] == "dwarf"            # not `gnome`, which is Pool's 3


def test_the_krynn_titles_number_their_races_from_zero():
    """Death Knights' CELESTE is race 0, and 0 is a Silvanesti elf there --
    not the `monster` it means in the Realms titles."""
    for game in (games.CHAMPIONS_OF_KRYNN, games.DEATH_KNIGHTS_OF_KRYNN):
        table = game.race_names
        assert table[0] == "silvanesti elf"
        assert table[5] == "kender"
        assert table[6] == "human"
        assert 7 not in table


def test_curse_leaves_race_six_unnamed():
    """Curse's own label table points both 6 and 7 at HUMAN. Naming 6
    `half-orc` would contradict what the game prints and naming it `human`
    would break the round trip, so it stays a number."""
    table = games.CURSE_OF_THE_AZURE_BONDS.race_names
    assert 6 not in table
    assert table[7] == "human"
    assert yaml_io._decode(table, 6, "race") == 6


def test_gateway_keeps_pool_of_radiances_race_list():
    assert (games.GATEWAY_TO_THE_SAVAGE_FRONTIER.races
            == games.POOL_OF_RADIANCE.races)


@pytest.mark.parametrize("key, bits, expected", [
    ("pool-of-radiance", 0x40, [0x40]),          # no paladin: keep the number
    ("curse-of-the-azure-bonds", 0x40, ["paladin"]),
    ("curse-of-the-azure-bonds", 0x80, ["ranger"]),
    ("secret-of-the-silver-blades", 0x40, ["paladin"]),
    ("champions-of-krynn", 0x10, ["knight"]),
    ("death-knights-of-krynn", 0x82, ["cleric", "ranger"]),
])
def test_classes_to_names_is_per_title(key, bits, expected):
    assert yaml_io.classes_to_names(bits, games.by_key(key)) == expected


def test_names_to_classes_refuses_a_class_the_title_lacks():
    with pytest.raises(yaml_io.ValueError_):
        yaml_io.names_to_classes(["paladin"], games.POOL_OF_RADIANCE)
    assert yaml_io.names_to_classes(
        ["paladin"], games.CURSE_OF_THE_AZURE_BONDS) == 0x40


def test_an_unknown_table_degrades_to_the_raw_number():
    """The designed failure: no names at all, rather than wrong ones."""
    blank = dataclasses.replace(games.POOL_OF_RADIANCE, races=None,
                                class_bits=None)
    assert blank.race_names is None and blank.class_bit_names is None
    assert yaml_io.race_table(blank) == {}
    assert yaml_io._decode(yaml_io.race_table(blank), 7, "race") == 7
    assert yaml_io.classes_to_names(8, blank) == [8]


def test_the_yaml_comment_lists_the_title_that_wrote_the_file():
    pool = yaml_io.comments_for(games.POOL_OF_RADIANCE)
    krynn = yaml_io.comments_for(games.CHAMPIONS_OF_KRYNN)
    assert "half-orc" in pool["race"] and "kender" not in pool["race"]
    assert "kender" in krynn["race"] and "half-orc" not in krynn["race"]
    assert "knight" in krynn["classes"] and "knight" not in pool["classes"]
    blank = dataclasses.replace(games.POOL_OF_RADIANCE, races=None,
                                class_bits=None)
    assert "not known" in yaml_io.comments_for(blank)["race"]


def test_a_game_descriptor_is_still_hashable():
    """The tables are pairs rather than dicts for exactly this reason."""
    assert len({g for g in games.GAMES}) == len(games.GAMES)


# --- item names -------------------------------------------------------------

def test_pool_of_radiance_is_the_only_title_at_the_old_address():
    assert games.POOL_OF_RADIANCE.item_names_load_address == 0x6F00
    assert items.NAMES_LOAD_ADDRESS == 0x6F00
    for game in games.GAMES:
        if game is games.POOL_OF_RADIANCE:
            continue
        assert game.item_names_load_address == 0x9E00, game.key


def test_no_address_means_no_names_and_no_disk_read():
    """The path is nonsense on purpose: an unknown address must not even open
    the disk, let alone name items after Pool of Radiance's table."""
    blank = dataclasses.replace(games.CURSE_OF_THE_AZURE_BONDS,
                                item_names_load_address=None)
    assert items.load_item_names("/no/such/disk.d64", blank) == {}


def item_names_disk(key: str) -> str:
    """A side of this title's disks that carries a readable `ITEMNAMES`.

    Skips otherwise -- one Champions side is a 40-track rip `goldbox/d64.py`
    refuses, and it may be the only side holding the file.
    """
    for path in disks_for(key):
        try:
            disk = D64.open(str(path))
        except Exception:
            continue
        if disk.find(b"ITEMNAMES") is not None:
            return str(path)
    pytest.skip(f"no readable {key} disk carries ITEMNAMES")


@pytest.mark.parametrize("key", KEYS)
def test_item_names_decode_on_every_title_whose_disks_are_here(key):
    """Entry 1 is BATTLE AXE in all six, at payload offset $201. That single
    string is what fixes the load address: at any other base it comes out
    truncated or as rubbish."""
    names = items.load_item_names(item_names_disk(key), games.by_key(key))
    assert names[1] == "BATTLE AXE"
    assert names[2] == "HAND AXE"
    assert len(names) > 100, f"{key} decoded only {len(names)} names"


def test_curse_item_names_used_to_come_out_as_indices():
    """P32's headline. Pool of Radiance's $6F00 against Curse's table leaves
    every pointer below the base, so every name is dropped and the editor shows
    a number. The descriptor's $9E00 is what makes them words."""
    disk = item_names_disk("curse-of-the-azure-bonds")
    assert items.load_item_names(disk, games.CURSE_OF_THE_AZURE_BONDS)[1] \
        == "BATTLE AXE"
    assert items.load_item_names(disk, games.POOL_OF_RADIANCE) == {}


# --- the shipped parties ----------------------------------------------------
# Every title ships a six-character pre-generated party inside its own save
# file, and that is the only real character data for four of them. A race code
# that is not in the table, or a class bit with no name, means the table is
# wrong.

def _characters(key: str) -> list[bytes]:
    """The first 256 bytes of every character in every save on the disks.

    Every save, because a title's shipped party can sit on any side and a
    cracked directory can name a truncated one the same thing.
    """
    game = games.by_key(key)
    need(key, game.save_file)
    out = []
    for payload in payloads(key, game.save_file):
        if len(payload) != game.save_size:
            continue
        for slot in range(game.slot_count):
            base = games.HEADER_SIZE + slot * games.SLOT_STRIDE
            record = payload[base:base + games.SLOT_STRIDE]
            if record[0] and record[0] != 0xFF:
                out.append(record)
    if not out:
        pytest.skip(f"{key}: no full save on these disks")
    return out


RACE_BYTE = 0x072
CLASS_BITS_BYTE = 0x0EB
LEVEL_ARRAY = 0x0C9          # eight slots, 0x0C9-0x0D0, one per class bit


@pytest.mark.parametrize("key", KEYS)
def test_class_bits_are_one_bit_per_non_zero_level_slot(key):
    """The cross-title check, and it is uniform: a class's bit number is its
    slot number in the eight-byte level array, knights, paladins and rangers
    included. Reading only the first four slots is what made this look like a
    Pool of Radiance quirk."""
    for record in _characters(key):
        slots = record[LEVEL_ARRAY:LEVEL_ARRAY + 8]
        expected = sum(1 << i for i, value in enumerate(slots) if value)
        assert record[CLASS_BITS_BYTE] == expected, (
            f"{key} {record[:16].split(b'\\x00')[0].decode('latin1')}: "
            f"class bits {record[CLASS_BITS_BYTE]:#04x} against slots "
            f"{list(slots)}")


@pytest.mark.parametrize("key, cls, field", [
    ("pool-of-radiance", "paladin", None),           # no paladins in Pool
    ("curse-of-the-azure-bonds", "paladin", "level_paladin"),
    ("curse-of-the-azure-bonds", "ranger", "level_ranger"),
    ("champions-of-krynn", "knight", "level_knight"),
])
def test_a_titles_extra_classes_get_their_own_level(key, cls, field):
    """They have a slot each, so the YAML must expose one each -- not fold
    them into the single `level` byte."""
    assert yaml_io.level_fields(games.by_key(key)).get(cls) == field


@pytest.mark.parametrize("key", KEYS)
def test_the_shipped_party_uses_races_the_title_names(key):
    table = games.by_key(key).race_names
    party = _characters(key)
    assert party, f"{key} ships no party"
    unnamed = {r[RACE_BYTE] for r in party} - set(table)
    assert not unnamed, f"{key} ships races {sorted(unnamed)} with no name"


@pytest.mark.parametrize("key", KEYS)
def test_the_shipped_party_uses_class_bits_the_title_names(key):
    game = games.by_key(key)
    known = 0
    for bit, _ in game.class_bits:
        known |= bit
    for record in _characters(key):
        bits = record[CLASS_BITS_BYTE]
        assert bits, "a shipped character with no class at all"
        assert not bits & ~known, (
            f"{game.key}: class bits {bits:#04x} include "
            f"{bits & ~known:#04x}, which nothing names")


@pytest.mark.parametrize("key, name, race", [
    # The rule cases: a paladin or a Knight of Solamnia must be human, a ranger
    # human or half-elf, and a kender is a kender.
    ("secret-of-the-silver-blades", b"GUY DE VALOIS", "human"),   # paladin
    ("champions-of-krynn", b"TRAPSPRINGER", "kender"),
    ("champions-of-krynn", b"STRONGSWORD", "human"),              # knight
    ("champions-of-krynn", b"ISTAN HORBIN", "half-elf"),          # ranger
    ("death-knights-of-krynn", b"SIR DRYDEN", "human"),           # knight
    ("death-knights-of-krynn", b"CELESTE", "silvanesti elf"),     # race 0
    ("curse-of-the-azure-bonds", b"MALE ELF MAGE", "elf"),        # says so
])
def test_the_named_specimens_that_pin_each_table_down(key, name, race):
    table = games.by_key(key).race_names
    for record in _characters(key):
        if record[:len(name)] == name:
            assert table[record[RACE_BYTE]] == race
            return
    pytest.skip(f"{key} here ships no {name.decode()}")
