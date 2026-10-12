"""`goldbox/companions.py`: a C64 companion's `MON` file, picture and story
byte, read off the player's own Curse and Silver Blades disks.

The disk-backed tests skip where the disks are absent, as on CI. The expected
values are the integers `docs/241-a-companions-combat-figure-on-each-port.md`
records, so a wrong reader fails here against the game's own files.
"""

from __future__ import annotations

import functools

import gamedata
import pytest
from support import silverblades

from goldbox import companions
from goldbox.companions import (
    CURSE_KEY,
    JOINABLE,
    MON_SIZE,
    SILVER_BLADES_KEY,
    Companions,
    Monster,
)
from goldbox.d64 import D64, split_load_address
from goldbox.iconparts import (
    CLASSES_SIZE,
    COUNTS_OFFSET,
    DEFAULT_BACKGROUND,
    DEFAULT_PART_COLOURS,
    FILLERS_OFFSET,
    MULTICOLOUR,
    NOT_A_PART,
    PART_CLASSES,
    POINTERS_OFFSET,
    PRIMARY,
    SPACE,
    START_CELL,
    TABLE_STRIDE,
)

ADDNPC = 0x36

#: Where each title's `INIT` keeps the 36 bytes it seeds all eight icon
#: slots with: Curse `INIT $0B0A`, Silver Blades `INIT $0C1A`.
INIT_SEED = {CURSE_KEY: 0x30A, SILVER_BLADES_KEY: 0x41A}

#: The companions each title's scripts can add, by name, with the `MON` id
#: the name identifies and the story byte `0x0E5` of that `MON` file.
COMPANIONS = {
    CURSE_KEY: {
        "ALIAS": (0x16, 0x16),
        "DRAGONBAIT": (0x17, 0x17),
        "AKABAR BEL AKAS": (0x3B, 0x3B),
        "RAKSHASA": (0x43, 0xFF),
        "RUSTLE": (0x55, 0xFF),
        "CYNTHIA": (0x58, 0xFF),
        "GRENDEL": (0x5A, 0xFF),
    },
    SILVER_BLADES_KEY: {
        "SIEGLINDA": (0x32, 0x4D),
        "CAPET": (0x33, 0x4C),
        "AVEROES": (0x34, 0x42),
        "VALA": (0x4D, 0x4D),
        "SIR DERIC": (0x4E, 0x4E),
    },
}

#: Every other `MON` file's story byte: the authors' fill, `$FF` in Curse
#: and 0 in Silver Blades.
FILL = {CURSE_KEY: 0xFF, SILVER_BLADES_KEY: 0x00}

#: `MON` files per title, all 480 bytes.
MON_COUNT = {CURSE_KEY: 70, SILVER_BLADES_KEY: 71}

#: Names two `MON` files share. Only RAKSHASA has a joinable member.
SHARED_NAMES = {
    CURSE_KEY: {"DARK ELF LORD": None, "RAKSHASA": 0x43},
    SILVER_BLADES_KEY: {"ANCIENT DRAGON": None, "FROST GIANT": None},
}

TITLES = (CURSE_KEY, SILVER_BLADES_KEY)


def _disks(key: str) -> list[D64]:
    if key == CURSE_KEY:
        return gamedata.curse_disks()
    return silverblades.ssb_disks()


@functools.lru_cache(maxsize=None)
def _loaded(key: str) -> Companions:
    return Companions.load(key, _disks(key))


@pytest.fixture(params=TITLES)
def title(request):
    return request.param


@pytest.fixture
def table(title):
    return _loaded(title)


# -- read off the player's disks -------------------------------------------

def test_every_mon_file_is_read_once(title, table):
    assert len(table.monsters) == MON_COUNT[title]


@pytest.mark.parametrize("key, name", [
    (key, name) for key in TITLES for name in COMPANIONS[key]])
def test_a_companions_name_gives_his_mon_file_and_picture(key, name):
    table = _loaded(key)
    mon_id, _story = COMPANIONS[key][name]
    assert table.match(name) == mon_id
    assert table.picture_for(mon_id) == mon_id
    assert table.name_matches(mon_id, name.lower())


@pytest.mark.parametrize("key, name", [
    (key, name) for key in TITLES for name in COMPANIONS[key]])
def test_the_record_a_join_copies_matches_its_own_file(key, name):
    """`ADDNPC` copies the 480-byte payload, name at `0x000` included."""
    table = _loaded(key)
    mon_id, _story = COMPANIONS[key][name]
    for disk in _disks(key):
        if disk.find(f"MON{mon_id:02X}".encode()):
            payload = split_load_address(disk.read_file(f"MON{mon_id:02X}".encode()))[1]
            record = payload + bytes(580 - MON_SIZE)
            assert table.match(record) == mon_id
            return
    pytest.fail(f"no side carries MON{mon_id:02X}")


def test_the_story_bytes_are_exactly_the_known_set(title, table):
    want = {mon_id: story for mon_id, story in COMPANIONS[title].values()}
    got = {mon_id: table.story_byte(mon_id) for mon_id in table.monsters
           if table.story_byte(mon_id) != FILL[title]}
    assert got == {m: s for m, s in want.items() if s != FILL[title]}
    for mon_id, story in want.items():
        assert table.story_byte(mon_id) == story


def test_a_story_byte_is_not_a_mon_id():
    """SIEGLINDA's story byte is VALA's `MON` id; her picture is her own."""
    table = _loaded(SILVER_BLADES_KEY)
    assert table.story_byte(0x32) == 0x4D == table.story_byte(0x4D)
    assert table.match("SIEGLINDA") == table.picture_for(0x32) == 0x32
    assert table.match("VALA") == 0x4D


def test_a_shared_name_matches_only_its_joinable_file(title, table):
    for name, want in SHARED_NAMES[title].items():
        assert len([m for m in table.monsters.values()
                    if m.name == name]) == 2, name
        assert table.match(name) == want, name


def test_no_two_joinable_files_share_a_name(title, table):
    names = [table.monsters[m].name for m in JOINABLE[title]]
    assert len(set(names)) == len(names)


def test_the_joinable_set_is_every_addnpc_the_scripts_reach(title):
    """A control-flow walk of every C64 area script."""
    from automap import gamedisks
    if not gamedisks.find(title):
        pytest.skip(f"needs the {title} C64 disks")
    from tools.areas import ecllist
    from tools.areas.eclsweep import walk
    _game, _root, machine, base, bodies = ecllist.load(title)
    found = set()
    for name, body in bodies.items():
        for statement in walk(machine, body, base).values():
            if statement.op == ADDNPC:
                kind, value = statement.operands[0]
                assert kind == 0x00, (name, hex(statement.at + base))
                found.add(value)
    assert found == JOINABLE[title]


def test_the_default_icon_is_the_seed_init_gives_every_slot(title, table):
    offset = INIT_SEED[title]
    for disk in _disks(title):
        if disk.find(b"INIT"):
            payload = split_load_address(disk.read_file(b"INIT"))[1]
            assert payload[offset:offset + 36] == table.default_icon
            return
    pytest.fail("no side carries INIT")


# -- the rules, on synthetic tables ------------------------------------------

def _monster(mon_id: int, name: str, story: int = 0xFF) -> Monster:
    return Monster(mon_id, name, bytes([0xFF, story, 0xFF, 0xFF]))


def _table(extra=(), key=SILVER_BLADES_KEY) -> Companions:
    monsters = {m: _monster(m, f"JOINER {m:02X}") for m in JOINABLE[key]}
    monsters.update({m.mon_id: m for m in extra})
    return Companions(key, monsters, bytes(36))


@pytest.mark.parametrize("story, is_story", [
    (0x00, False), (0x01, True), (0x7F, True), (0x80, False), (0xFF, False)])
def test_com_prep_takes_a_story_byte_only_from_1_to_127(story, is_story):
    assert _monster(1, "X", story).is_story is is_story


def test_a_name_matches_whatever_its_padding_and_case():
    table = _table([_monster(0x01, "ONE")])
    assert table.match("one ") == 0x01
    assert table.match(b"ONE\0\0junk") == 0x01
    assert table.match("TWO") is None


def test_two_unjoinable_files_with_one_name_match_neither():
    table = _table([_monster(0x01, "TWIN"), _monster(0x02, "TWIN")])
    assert table.match("TWIN") is None


def test_a_table_without_a_joinable_file_raises():
    monsters = {m: _monster(m, f"J{m}") for m in sorted(JOINABLE[CURSE_KEY])[1:]}
    with pytest.raises(ValueError, match="MON16"):
        Companions(CURSE_KEY, monsters, bytes(36))


def test_a_title_with_no_companions_raises():
    with pytest.raises(ValueError):
        Companions("pool-of-radiance", {}, bytes(36))


def test_a_missing_file_has_no_picture_or_story_byte():
    with pytest.raises(KeyError, match="MON01"):
        _table().picture_for(0x01)
    with pytest.raises(KeyError, match="MON01"):
        _table().story_byte(0x01)


@pytest.mark.parametrize("name", [b"MON_1", b"MON+1", b"MON 1", b"MONXY", b"MON1", b"MON123"])
def test_only_mon_and_two_hex_digits_names_a_monster_file(name):
    assert companions._mon_id(name) is None


def test_a_monster_file_name_is_read_as_hex():
    assert companions._mon_id(b"MON4d") == 0x4D
    assert companions._mon_id(b"MON3B\xa0\xa0") == 0x3B


def test_a_path_that_is_not_a_disk_image_raises_naming_it(tmp_path):
    bad = tmp_path / "SIDE.D64"
    bad.write_bytes(b"not a disk")
    with pytest.raises(ValueError, match="SIDE.D64"):
        Companions.load(SILVER_BLADES_KEY, [str(bad)])


def _mon_prg(name: bytes, fill: int = 0) -> bytes:
    payload = bytearray([fill] * MON_SIZE)
    payload[:len(name) + 1] = name + b"\0"
    return bytes([0x00, 0x30]) + bytes(payload)


def test_a_mon_file_that_differs_between_sides_raises():
    one = D64.from_bytes(gamedata._disk_with([(b"MON01", _mon_prg(b"A"))]))
    two = D64.from_bytes(gamedata._disk_with([(b"MON01", _mon_prg(b"B"))]))
    with pytest.raises(ValueError, match="differs"):
        Companions.load(SILVER_BLADES_KEY, [one, two])


def test_a_mon_file_of_another_size_raises():
    short = bytes([0x00, 0x30]) + bytes(MON_SIZE - 1)
    disk = D64.from_bytes(gamedata._disk_with([(b"MON01", short)]))
    with pytest.raises(ValueError, match="479 bytes"):
        Companions.load(SILVER_BLADES_KEY, [disk])


def test_disks_without_the_icon_editor_raise():
    disk = D64.from_bytes(gamedata._disk_with([(b"MON01", _mon_prg(b"A"))]))
    with pytest.raises(ValueError, match="SPELLE64"):
        Companions.load(SILVER_BLADES_KEY, [disk])


# -- a whole load, on a disk built from made-up bytes -------------------------

#: Where the stub icon editor says its four option tables are: a page-aligned
#: base, then one table every $D0 bytes, clear of the filler strings.
STUB_BASE = 0x8E00
WEAPON_GLYPH, HAIR_GLYPH = 0x41, 0x42


def _stub_icon_files() -> tuple[bytes, bytes]:
    """`SPELLE64` and `SPELLN64` with two parts in them: large weapon 0 puts
    an arm glyph in cell 4 of each pose, large head 1 a hair glyph in cell 1."""
    parts = bytearray(FILLERS_OFFSET + 1)
    parts[:CLASSES_SIZE] = bytes([NOT_A_PART]) * CLASSES_SIZE
    parts[WEAPON_GLYPH] = PART_CLASSES.index("arm")
    parts[HAIR_GLYPH] = PART_CLASSES.index("hair")
    tables = [STUB_BASE + CLASSES_SIZE + n * 0xD0 for n in range(4)]
    for start, glyph, option, cell in ((tables[2] - STUB_BASE, WEAPON_GLYPH, 0, 4),
                                       (tables[3] - STUB_BASE, HAIR_GLYPH, 1, 1)):
        for pose in range(2):
            at = start + pose * TABLE_STRIDE
            parts[at + PRIMARY + option] = glyph
            parts[at + START_CELL + option] = cell
    editor = bytearray(POINTERS_OFFSET + 8)
    editor[COUNTS_OFFSET:COUNTS_OFFSET + 4] = bytes([2, 2, 2, 2])
    for n, address in enumerate(tables):
        editor[POINTERS_OFFSET + n * 2:POINTERS_OFFSET + n * 2 + 2] = (
            address.to_bytes(2, "little"))
    return bytes(parts), bytes(editor)


def _synthetic_mon(name: bytes, story: int) -> bytes:
    payload = bytearray(_mon_prg(name, fill=0xFF))
    payload[2 + companions.STORY_OFFSET] = story
    return bytes(payload)


def test_a_whole_load_reads_monsters_names_and_the_default_icon():
    parts, editor = _stub_icon_files()
    monsters = [(f"MON{m:02X}".encode(), _synthetic_mon(f"JOINER {m:02X}".encode(), m))
                for m in sorted(JOINABLE[SILVER_BLADES_KEY])]
    extra = [(b"MON01", _synthetic_mon(b"LONER", 0xFF)),
             (b"MONEY", _synthetic_mon(b"NOT A MONSTER", 0x00))]
    one = D64.from_bytes(gamedata._disk_with(monsters[:3] + extra))
    two = D64.from_bytes(gamedata._disk_with(
        monsters[2:] + [(b"SPELLE64", b"\x00\x8e" + parts),
                        (b"SPELLN64", b"\x00\x96" + editor)]))
    table = Companions.load(SILVER_BLADES_KEY, [one, two])

    assert sorted(table.monsters) == sorted(JOINABLE[SILVER_BLADES_KEY] | {0x01})
    assert table.match("loner") == 0x01
    assert table.name_matches(0x01, b"LONER\0")
    assert not table.name_matches(0x01, "JOINER 32")
    assert not table.name_matches(0x02, "LONER")
    for mon_id in JOINABLE[SILVER_BLADES_KEY]:
        assert table.match(f"JOINER {mon_id:02X}") == mon_id
        assert table.story_byte(mon_id) == mon_id
    assert not table.monsters[0x01].is_story

    figure = [SPACE] * 18
    figure[4] = figure[13] = WEAPON_GLYPH
    figure[1] = figure[10] = HAIR_GLYPH
    colours = [DEFAULT_BACKGROUND | MULTICOLOUR] * 18
    colours[4] = colours[13] = DEFAULT_PART_COLOURS[PART_CLASSES.index("arm")]
    colours[1] = colours[10] = DEFAULT_PART_COLOURS[PART_CLASSES.index("hair")]
    assert table.default_icon == bytes(figure + colours)
