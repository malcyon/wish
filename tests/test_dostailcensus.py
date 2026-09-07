"""`tools/dostailcensus.py`'s finder does not fold another title in by size.

`#400 (The DOS record census counts Gateway and Treasures characters as Curse
and Pools of Darkness ones, because it identifies a title by record size)`:
Gateway to the Savage Frontier's `.GUY` export is 422 bytes, the same as
Curse of the Azure Bonds' record, and Treasures of the Savage Frontier's
record is 510, the same as Pools of Darkness'.  A finder keyed on size alone
reads one title's characters through another's table.

The synthetic tests below build the trap directly, on a machine with no game
on it.  The corpus test at the bottom is the finding itself, off the player's
own archives, and skips without them.
"""

from __future__ import annotations

import pathlib

import pytest

from goldbox import dos_layout as dl
from tools import dostailcensus


def _write(root: pathlib.Path, rel: str, size: int, tag: bytes = b"") -> pathlib.Path:
    """A record of `size` bytes, with `tag` at the front so two records of
    the same size are not the same bytes -- deduplication on the record
    bytes would otherwise collapse a foreign record onto a genuine one that
    happens to be all zero, and hide the bug this test is about."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (tag + bytes(size))[:size]
    path.write_bytes(data)
    return path


def test_foreign_title_names_a_gateway_or_treasures_directory():
    gateway = pathlib.Path("/archives/games/Gateway to the Savage Frontier/"
                            "SAVE/TARLREN.GUY")
    treasures = pathlib.Path("/archives/games/Treasures of the Savage "
                              "Frontier/Saves/CHRDATA1.SAV")
    curse = pathlib.Path("/archives/games/Curse of the Azure Bonds/"
                          "SAVE/CHRDATA1.CHA")
    assert dostailcensus.foreign_title(gateway) == "gateway to the savage frontier"
    assert dostailcensus.foreign_title(treasures) == "treasures of the savage frontier"
    assert dostailcensus.foreign_title(curse) is None


def test_a_gateway_record_is_not_counted_as_curse(tmp_path):
    """A 422-byte `.GUY` under a Gateway directory is Curse's own record
    size, and the bug this issue is about is reading it through Curse's
    table and counting it as one of Curse's own.
    """
    _write(tmp_path, "games/Gateway to the Savage Frontier/SAVE/TARLREN.GUY",
           dl.CURSE_OF_THE_AZURE_BONDS.record_size, tag=b"TARLREN")
    _write(tmp_path, "games/Curse of the Azure Bonds/SAVE/GENUINE.CHA",
           dl.CURSE_OF_THE_AZURE_BONDS.record_size, tag=b"GENUINE")

    specs, skipped = dostailcensus.collect([tmp_path], want_built=False)

    curse_names = {s.path.name for s in specs
                   if s.shape.key == "curse-of-the-azure-bonds"}
    assert curse_names == {"GENUINE.CHA"}
    assert "TARLREN.GUY" not in curse_names
    assert skipped["gateway to the savage frontier"] == 1


def test_a_treasures_record_is_not_counted_as_pools_of_darkness(tmp_path):
    _write(tmp_path, "games/Treasures of the Savage Frontier/Saves/"
                      "CHRDATA1.SAV", dl.POOLS_OF_DARKNESS.record_size,
           tag=b"TREASURE1")
    _write(tmp_path, "games/Pools of Darkness/Saves/GENUINE.SAV",
           dl.POOLS_OF_DARKNESS.record_size, tag=b"GENUINE2")

    specs, skipped = dostailcensus.collect([tmp_path], want_built=False)

    pod_names = {s.path.name for s in specs
                 if s.shape.key == "pools-of-darkness"}
    assert pod_names == {"GENUINE.SAV"}
    assert "CHRDATA1.SAV" not in pod_names
    assert skipped["treasures of the savage frontier"] == 1


def test_foreign_records_are_included_and_marked_when_asked_for(tmp_path):
    _write(tmp_path, "games/Gateway to the Savage Frontier/SAVE/TARLREN.GUY",
           dl.CURSE_OF_THE_AZURE_BONDS.record_size)

    excluded, skipped_default = dostailcensus.collect([tmp_path], False)
    assert excluded == []
    assert skipped_default["gateway to the savage frontier"] == 1

    included, skipped_foreign = dostailcensus.collect([tmp_path], False,
                                                       want_foreign=True)
    assert [s.path.name for s in included] == ["TARLREN.GUY"]
    assert skipped_foreign == {}


# --- the finding itself, off the player's own archives ----------------------

def _archives():
    arch = dostailcensus.archives()
    if arch is None:
        pytest.skip("needs the DOS archives ($FR_ARCHIVES)")
    return arch


def test_the_curse_pile_holds_no_gateway_record():
    specs, skipped = dostailcensus.collect([_archives()], want_built=False)
    curse = [s for s in specs if s.shape.key == "curse-of-the-azure-bonds"]
    from_gateway = [s for s in curse
                    if "gateway to the savage frontier" in s.path.as_posix().lower()]
    assert from_gateway == []
    assert skipped["gateway to the savage frontier"] > 0


def test_the_pools_of_darkness_pile_holds_no_treasures_record():
    specs, skipped = dostailcensus.collect([_archives()], want_built=False)
    pod = [s for s in specs if s.shape.key == "pools-of-darkness"]
    from_treasures = [s for s in pod
                      if "treasures of the savage frontier" in s.path.as_posix().lower()]
    assert from_treasures == []
    assert skipped["treasures of the savage frontier"] > 0
