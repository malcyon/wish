"""`tools/c64/overlay.py` finds an overlay on the disks of the title asked for.

The Curse cases skip without the Curse disks, and the Pool case without Pool's.
"""
from __future__ import annotations

import pytest
from conftest import load_tools_module
from support.coldread import CURSE, POOL, _root

overlay = load_tools_module("overlay")


def test_pool_lookup_is_the_default():
    root = _root(POOL)
    declared, body = overlay.load("DUNGEON", root)
    assert body
    assert (declared, body) == overlay.load("DUNGEON", root, POOL)


def test_curse_overlay_is_found_by_title():
    root = _root(CURSE)
    game = overlay.title_game("curse")
    assert game is CURSE
    declared, body = overlay.load("ECL65", root, game)
    assert body


def test_missing_overlay_is_reported_by_name():
    with pytest.raises(SystemExit, match="No file called NOSUCH"):
        overlay.load("NOSUCH", _root(POOL))


def test_unknown_title_is_refused():
    with pytest.raises(SystemExit, match="No title called nope"):
        overlay.title_game("nope")


def test_cli_title_and_disks_select_the_curse_disks(capsys):
    root = _root(CURSE)
    assert overlay.main(["overlay.py", "--title", "curse", "--disks", root,
                         "refs", "ECL65", "0x0800"]) in (0, None)
    assert "mention" in capsys.readouterr().out


def test_cli_bogus_title_is_refused():
    with pytest.raises(SystemExit, match="No title called bogus"):
        overlay.main(["overlay.py", "--title", "bogus", "hex", "X", "0"])


def test_pool_without_disks_falls_back_to_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("POR_DISKS", str(tmp_path))
    assert overlay.title_root(POOL, None) == tmp_path
