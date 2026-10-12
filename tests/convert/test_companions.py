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

from goldbox.companions import (
    CURSE_KEY,
    JOINABLE,
    MON_SIZE,
    SILVER_BLADES_KEY,
    Companions,
    Monster,
)
from goldbox.d64 import D64, split_load_address

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
    """A control-flow walk of every C64 area script, as stage 1 read it."""
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


def test_a_picture_for_a_missing_file_raises():
    with pytest.raises(KeyError):
        _table().picture_for(0x01)


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
