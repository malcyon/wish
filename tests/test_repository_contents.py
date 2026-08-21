"""The repository must not carry the game.

`CLAUDE.md` forbids committing Pool of Radiance's code, art, music, manuals or
data files. That rule was broken once by accident -- four fixtures, one of them
6502 machine code -- because a test fixture does not feel like a copy while you
are adding it. It is one, so this checks.

The check runs against `git ls-files`, not the working tree: what matters is
what is committed. Untracked scratch under `work/` is ignored and fine.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Extensions the game's content would arrive in. `.bin` is deliberately not
#: here -- see `ALLOWED_FIXTURES`, which is stricter.
FORBIDDEN_SUFFIXES = {
    ".d64", ".d71", ".d81", ".g64", ".t64", ".tap",     # disk and tape images
    ".prg", ".p00", ".crt", ".rom",                     # executables
    ".sid", ".psid", ".mod", ".wav", ".mp3", ".ogg",    # music and sound
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp",   # art and scans
    ".pdf",                                             # manuals and cluebooks
}

#: The only binaries allowed in `tests/fixtures/`, and why.
#:
#: Every one is **the player's own saved game**, produced by playing, not
#: content SSI shipped. A capture of live machine memory is not a saved game --
#: it carries whatever code was resident at the time -- so `combat-arena.bin`
#: was moved to `work/captures/` and the combat tests build an arena instead. Several capture states no disk still holds, so they
#: cannot be regenerated. Anything the publisher shipped -- a GEO, an overlay,
#: the party on POOL1 -- is read from the player's disks at run time instead;
#: `tests/gamedata.py` does that.
#:
#: **Do not add to this list.** If a test needs game data, use
#: `gamedata.game_file`, or generate what you need with `gamedata.synthetic_geo`.
ALLOWED_FIXTURES = {
    "savedgame0.bin",
    "savedgame1.bin",
    "party6_savedgame0.bin",
    "party6_after_combat.bin",
    "brutus.chr",
    "lady_katherine.chr",
    "malcyon.chr",
}


def tracked() -> list[pathlib.Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                         capture_output=True, text=True, check=True)
    return [pathlib.Path(p) for p in out.stdout.split("\0") if p]


@pytest.fixture(scope="module")
def files():
    try:
        return tracked()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("not a git checkout")


def test_no_disk_image_executable_or_media_is_committed(files):
    """Whole categories, by extension. A disk image is the obvious one."""
    bad = [str(p) for p in files if p.suffix.lower() in FORBIDDEN_SUFFIXES]
    assert not bad, (
        "these must not be committed -- see 'What must never enter this "
        f"repository' in CLAUDE.md: {bad}")


def test_only_the_players_own_saves_live_in_fixtures(files):
    """The rule that actually caught the four.

    A new binary under `tests/fixtures/` is presumed to be game content until
    somebody argues otherwise, because that is how the last four arrived.
    """
    here = [p for p in files if p.parts[:2] == ("tests", "fixtures")]
    unexpected = sorted(p.name for p in here
                        if p.name not in ALLOWED_FIXTURES)
    assert not unexpected, (
        "new fixtures must not be slices of the game's files. Read them from "
        "the player's disks with tests/gamedata.py instead, or generate them: "
        f"{unexpected}")


def test_the_licence_is_present(files):
    """PyQt6 is GPL, so this is too, and the text has to ship with it."""
    assert pathlib.Path("LICENSE") in files
    text = (ROOT / "LICENSE").read_text()
    assert "GNU GENERAL PUBLIC LICENSE" in text
    assert "Version 3" in text
