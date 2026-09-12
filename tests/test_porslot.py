from __future__ import annotations

"""`tools/porslot.py` reading an Amiga save slot (#373).

You point `porslot.py` at a *Pool of Radiance* disk to put a slot our own
code wrote in front of the game's picker, and until this its `read_slot`
unpacked each character's `.sav`, `.itm` and `.spc` into a
`tempfile.TemporaryDirectory` and read them back with `read_amiga_por`,
because that reader wanted a path. `goldbox.amiga.read_por_slot` now reads
the same three files straight off the disk's own blocks, and `read_slot`
goes through that instead -- `#373 (tools/porslot.py reads an Amiga slot
through a temporary directory, where goldbox.amiga.read_por_slot now reads
the blocks)`.

**Reads the player's own Amiga disk**, through `tools/gamedisks.py`'s
`amiga` entry, and skips on a machine that has none. Nothing here is
committed: an Amiga disk image is the game's own code and data
(`AGENTS.md`).
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from test_amigatoc64 import _pool_of_radiance_disk_1  # noqa: E402

from goldbox import amiga_por, amiga_port, dos_codec  # noqa: E402
from goldbox.amiga_adf import AmigaDisk  # noqa: E402
from tools import porslot  # noqa: E402


@pytest.fixture(scope="module")
def shipped_disk() -> AmigaDisk:
    """Pool of Radiance Amiga disk 1, whose `save` drawer holds slot A."""
    return _pool_of_radiance_disk_1()


def test_read_slot_gives_what_read_por_slot_and_to_neutral_give(
        shipped_disk):
    """The same slot, the same six characters, the same saved game.

    `read_slot` is now nothing but `amiga.read_por_slot` plus
    `dos.to_neutral` over each of its characters -- this pins that shape
    directly, so a hand rewrite that quietly changed what it composes would
    be caught here rather than only by a byte-for-byte comparison downstream.
    """
    party, savegame = amiga_por.read_por_slot(shipped_disk, "A")
    want = [dos_codec.to_neutral(c) for c in party]

    got, got_savegame = porslot.read_slot(shipped_disk, "A")

    assert got_savegame == savegame
    assert len(got) == len(want) == amiga_por.POR_PARTY_MAX
    for w, g in zip(want, got):
        assert g.get("name") == w.get("name")
        assert g.fields.keys() == w.fields.keys()
        for name in w.fields:
            assert g.get(name) == w.get(name), name
        assert g.warnings == w.warnings
        assert g.dropped == w.dropped


def test_read_slot_creates_no_temporary_directory(shipped_disk, monkeypatch):
    """The detour this closes: `read_slot` used to write each character's
    `.sav`/`.itm`/`.spc` into a `tempfile.TemporaryDirectory()` and read
    them back from there. A test that only checked the output would still
    pass with that detour in place, so this asserts the *absence* instead --
    `tempfile.TemporaryDirectory` and `tempfile.mkdtemp` are made to blow up,
    and `read_slot` has to succeed without ever calling either.
    """
    import tempfile

    def _boom(*args, **kwargs):
        raise AssertionError(
            "read_slot must not create a temporary directory")

    monkeypatch.setattr(tempfile, "TemporaryDirectory", _boom)
    monkeypatch.setattr(tempfile, "mkdtemp", _boom)

    characters, savegame = porslot.read_slot(shipped_disk, "A")
    assert len(characters) == amiga_por.POR_PARTY_MAX
    assert len(savegame) == amiga_por.POR_SAVEGAME_SIZE


def test_read_slot_raises_amiga_record_error_for_an_absent_slot(
        shipped_disk):
    """Disk 1 ships slot A alone, so any other letter has no character
    files. `amiga.read_por_slot` is what names the missing file; `read_slot`
    no longer has its own `SystemExit` for this, so the same exception has
    to reach the caller."""
    with pytest.raises(amiga_port.AmigaRecordError):
        porslot.read_slot(shipped_disk, "F")
