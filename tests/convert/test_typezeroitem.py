"""The C64 writer reports a type-0 item as dropped; a Pool Save As leaves it out first.

The C64 counts a slot whose type byte is 0 as empty.  No game data creates
such a record; a DOS Pool party Wish converted from the C64 before it read the
empty slot that way holds ten of them.
"""

from __future__ import annotations

import pathlib

import pytest
from gamedata import specimen_root
from PyQt6.QtWidgets import QApplication
from support import packoverflow
from support.doslatertitles import _c64_party
from support.neutralrecords import FILLED_ITEM, _filled

from automap import gamedisks
from editor import convert, roster, saveplan
from goldbox import c64_codec, c64_port, dos_codec
from goldbox.neutral import NeutralCharacter, ScrollBundle


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


TYPE_ZERO = "has type 0"
# One named word and type 0: the record the old C64 reader wrote to DOS.
TYPE_ZERO_RECORD = bytes((0, 5)) + bytes(14)

# Type-0 records per member, read off each specimen: 10 in all.
EXPECTED = {"SIMON": 4, "PRINCESS FATIMA": 2, "MAD MAN": 1, "DIRTEN": 3}


def _type_zero_lines(report) -> list[str]:
    return [x for x in report.dropped if TYPE_ZERO in x]


def _specimen(name: str) -> pathlib.Path:
    root = specimen_root()
    found = list(root.glob(f"*-dos/WISH-SPEC-{name}")) if root else []
    if not found:
        pytest.skip(f"needs WISH-SPEC-{name} (tools/registry/specimens.py)")
    return found[0]


def test_a_type_zero_record_is_written_and_reported():
    char = _filled()
    char.set("inventory", [FILLED_ITEM, TYPE_ZERO_RECORD], "made up")
    rec, report = c64_codec.write(char)
    assert len(_type_zero_lines(report)) == 1
    assert "item 1 " in _type_zero_lines(report)[0]
    assert report.losses == []
    slots = rec.get_raw("inventory")
    # The list is in screen order, top row first, so the second of two items
    # is in slot 0.
    assert slots[:16] == TYPE_ZERO_RECORD
    assert slots[16:32] == FILLED_ITEM


def test_a_party_with_no_type_zero_record_has_no_such_line():
    char = _filled()
    char.set("inventory", [FILLED_ITEM], "made up")
    _rec, report = c64_codec.write(char)
    assert _type_zero_lines(report) == []


@pytest.mark.parametrize("name, slot", [
    ("por-790-scribe-complete-stale-count", "E"),
    ("issue641-dirten-seven-resave", "B"),
])
def test_the_wish_made_specimens_count_ten_type_zero_records(name, slot):
    folder = _specimen(name)
    counts = {}
    for n in range(1, 8):
        dos = dos_codec.read_character(folder / f"CHRDAT{slot}{n}.SAV")
        _rec, report = dos_codec.to_c64_record(dos)
        counts[dos.name] = len(_type_zero_lines(report))
    assert {k: v for k, v in counts.items() if v} == EXPECTED
    assert sum(counts.values()) == 10


def _game_files(game):
    """The disks' files with Pool's `ITEMS` table, which the editor reads and
    `convertdrops.game_files` leaves out; without it the writer cannot tell a
    readied weapon from readied armour."""
    where = gamedisks.find(game.key)
    if where is None:
        return None
    return convert._game_files_from_folder(where, game)


def _assets(party):
    try:
        return saveplan.resolve_assets(party.source, "c64",
                                       game_files=_game_files)
    except saveplan.MissingAssets:
        pytest.skip("needs Pool of Radiance's own C64 disks, found through "
                    "automap/gamedisks.py")


def _written_member(plan, tmp_path, name):
    (image,) = plan.files
    written = tmp_path / "read-back.d64"
    written.write_bytes(plan.files[image])
    _game, chars = _c64_party(written)
    (char,) = [c for c in chars if c.get("name") == name]
    return char


def _lines(plan, who):
    return [w for w in plan.report.warnings
            if who in w and "type 0, left out" in w]


def _source_pack(folder, slot):
    for n in range(1, 8):
        dos = dos_codec.read_character(folder / f"CHRDAT{slot}{n}.SAV")
        if dos.name == "THRENDER GRONE":
            return [bytes(i) for i in dos_codec.to_neutral(dos).get("inventory")]
    raise AssertionError("THRENDER GRONE is not in the specimen")


@pytest.mark.parametrize("name, slot, readied", [
    ("por-793-type0-readied", "E", True),
    ("por-793-treasure-type0-item", "C", False),
])
def test_save_as_to_the_c64_leaves_the_type_zero_item_out(
        app, tmp_path, name, slot, readied):
    source = _source_pack(_specimen(name), slot)
    zero = [i for i in source if not i[0]]
    assert len(zero) == 1 and bool(zero[0][6] & 0x80) == readied
    party = roster.Party(str(_specimen(name)))
    plan = saveplan.prepare_save_as(party, "c64", tmp_path / "out.d64",
                                    _assets(party))
    assert saveplan.losses(plan.report) == []
    assert _type_zero_lines(plan.report) == []
    assert len(_lines(plan, "THRENDER GRONE")) == 1
    char = _written_member(plan, tmp_path, "THRENDER GRONE")
    held = [bytes(i) for i in char.get("inventory")]
    assert len(held) == 2 and all(i[0] for i in held)
    assert held == [i for i in source if i[0]]
    if readied:
        tail = bytes(char.get("roster_tail"))
        want = bytearray(bytes(char.get("attack_forms"))[2:8])
        want[4] = (want[4] + c64_codec.c64_strength_damage_step(
            char.get("strength"), char.get("exceptional_strength"))) & 0xFF
        assert tail[3:9] == bytes(want)
        hit = c64_codec.c64_strength_hit_step(
            char.get("strength"), char.get("exceptional_strength"))
        assert char.get("thac0_current") == (char.get("thac0_base") + hit) & 0xFF


def test_save_as_to_the_c64_converts_the_issue641_party(app, tmp_path):
    party = roster.Party(str(_specimen("issue641-dirten-seven-resave")))
    plan = saveplan.prepare_save_as(party, "c64", tmp_path / "out.d64",
                                    _assets(party))
    assert saveplan.losses(plan.report) == []
    assert len([w for w in plan.report.warnings if "type 0, left out" in w]) == 10
    char = _written_member(plan, tmp_path, "SIMON")
    assert len(char.get("inventory")) == 12
    assert any(bytes(i)[6] & 0x80 for i in char.get("inventory"))


def test_the_convert_rehearsal_finds_nothing_lost(app):
    party = roster.Party(str(_specimen("por-793-treasure-type0-item")))
    assets = _assets(party)
    source = convert.Source.of_snapshot(saveplan.prepare(party))
    rehearsal, _slot = saveplan.rehearse(saveplan.route(source, "c64"),
                                         source, assets)
    assert saveplan.losses(rehearsal.report) == []


def _pool_member(items, bundles=()):
    char = NeutralCharacter("test", source="made up",
                            game=c64_port.POOL_OF_RADIANCE)
    char.set("name", "ALPHA", "made up")
    char.set("inventory", items, "made up")
    char.set("scroll_bundles", tuple(bundles), "made up")
    return char


def test_without_type_zero_shifts_a_joined_scroll_down_by_one():
    items = [packoverflow.ordinary(0), TYPE_ZERO_RECORD,
             packoverflow.ordinary(1), packoverflow.scroll(5),
             packoverflow.scroll(6)]
    bundle = ScrollBundle(3, 2, packoverflow.head(2))
    char, gone = dos_codec._without_type_zero(_pool_member(items, [bundle]))
    assert gone == [1]
    assert char.get("inventory") == [items[0], items[2], items[3], items[4]]
    assert [b.first for b in char.get("scroll_bundles")] == [2]


def test_pack_overflow_does_not_count_a_type_zero_item():
    items = ([packoverflow.ordinary(n) for n in range(14)]
             + [TYPE_ZERO_RECORD, packoverflow.scroll(5),
                packoverflow.scroll(6)])
    char = _pool_member(items, [ScrollBundle(15, 2, packoverflow.head(2))])
    assert len(items) == 17
    assert len(dos_codec.pack_overflow([char])) == 1
    assert dos_codec.pack_overflow([char], drop_type_zero=True) == ()


def test_a_neutral_pool_party_loses_its_type_zero_item_in_write_c64_save():
    from goldbox import world_state
    from goldbox.savegame import SaveGame0
    fx = pathlib.Path(__file__).resolve().parents[1] / "fixtures"
    payload = bytearray(SaveGame0.from_prg(
        (fx / "savedgame0.bin").read_bytes()).to_bytes())
    state = world_state.from_c64(bytes(payload), game=c64_port.POOL_OF_RADIANCE)
    party, _ = dos_codec.c64_party(bytes(payload), None,
                                   game=c64_port.POOL_OF_RADIANCE)
    char = party[0]
    items = [bytes(i) for i in char.get("inventory")]
    char.set("inventory", [*items, TYPE_ZERO_RECORD], "built here")
    report = dos_codec.write_c64_save(bytearray(payload), None, state, [char],
                                      game=c64_port.POOL_OF_RADIANCE)
    assert _type_zero_lines(report) == []
    assert len([w for w in report.warnings if "type 0, left out" in w]) == 1
