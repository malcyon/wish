"""`tools/dos/dosspcexpiry.py`'s pure staging, with no emulator and no game
files: the C64-template item build for `#694 (A DOS Pool of Radiance
character wearing Gauntlets of Ogre Power loses his real strength for good
once converted to C64 and un-readied)`'s live-proof plan.

The driven `ready` command itself is exercised only by a running DOSBox-X
boot; nothing here claims a slot.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.dos import dosspcexpiry as D  # noqa: E402


def _c64_record(**kw) -> bytes:
    """A synthetic 16-byte C64 item record -- no game bytes, every field
    named so the test can check what `item_from_c64` did with it."""
    r = bytearray(16)
    r[0] = kw.get("type_index", 5)
    r[1:4] = bytes(kw.get("name", b"\x01\x02\x03"))
    r[4] = kw.get("plus", 0)
    r[5] = kw.get("plus_save", 0)
    r[6] = kw.get("readied_hidden", 0x80)  # readied bit set, no hidden bits
    r[7] = kw.get("cursed", 0)
    r[8], r[9] = kw.get("weight", (0, 5))
    r[10] = kw.get("quantity", 1)
    r[11], r[12] = kw.get("value", (0, 100))
    r[13] = kw.get("charges", 0)
    r[14] = kw.get("effect", 38)
    r[15] = kw.get("power", 0x83)
    return bytes(r)


def test_staged_item_carries_the_templates_effect_and_power():
    record = D.staged_item(_c64_record(effect=38, power=0x83))
    assert record[0x3D] == 38
    assert record[0x3E] == 0x83
    assert len(record) == D.pordos.ITEM_SIZE


def test_staged_item_is_never_readied_whatever_the_template_said():
    readied = D.staged_item(_c64_record(readied_hidden=0x80))
    unreadied = D.staged_item(_c64_record(readied_hidden=0x00))
    assert readied[0x34] == 0
    assert unreadied[0x34] == 0


def test_staged_item_matches_item_from_c64_apart_from_the_readied_byte():
    template = _c64_record()
    expected = bytearray(D.pordos.item_from_c64(template))
    expected[0x34] = 0
    assert D.staged_item(template) == bytes(expected)


def test_staged_item_takes_effect_and_power_from_the_template_alone():
    """`--template` takes the whole record off the game, not `cmd_ready`'s
    own `--effect`/`--power` defaults (61, 0x80)."""
    record = D.staged_item(_c64_record(effect=61, power=0x85))
    assert (record[0x3D], record[0x3E]) == (61, 0x85)
    other = D.staged_item(_c64_record(effect=38, power=0x83))
    assert (other[0x3D], other[0x3E]) == (38, 0x83)


def test_load_template_reads_the_named_item_off_the_registry_disks(monkeypatch):
    seen = {}

    def find(name):
        seen["name"] = name
        return "/disks"

    def load_item_templates(path):
        seen["path"] = path
        return {"GAUNTLETS OF OGRE POWER": b"\x00" * 16}

    monkeypatch.setattr(D.gamedisks, "find", find)
    monkeypatch.setattr(D.c64_items, "load_item_templates", load_item_templates)
    got = D.load_template("GAUNTLETS OF OGRE POWER")
    assert got == b"\x00" * 16
    assert seen["name"] == "pool-of-radiance"
    assert seen["path"] == str(pathlib.Path("/disks") / "POOL1.D64")


def test_load_template_blocks_an_unknown_name(monkeypatch):
    monkeypatch.setattr(D.gamedisks, "find", lambda name: "/disks")
    monkeypatch.setattr(D.c64_items, "load_item_templates", lambda path: {})
    with pytest.raises(SystemExit):
        D.load_template("NOTHING LIKE THAT")


def test_load_template_blocks_with_no_registered_disks(monkeypatch):
    monkeypatch.setattr(D.gamedisks, "find", lambda name: None)
    with pytest.raises(SystemExit):
        D.load_template("ANYTHING")
