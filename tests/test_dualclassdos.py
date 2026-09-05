"""The pure parts of the `#234` dual-class kit: attribution and alignment.

Three claims, none of which needs the player's disks:

* `tools/dualclassdos.py`'s `source_title` names the **game tree** a record
  came out of, and refuses rather than guesses.  A record is grouped by its
  *size*, which only ever names four titles, and six exist on this machine --
  OUGO is a Treasures of the Savage Frontier record read as Pools of Darkness,
  and before this the census printed him under the wrong title in as many
  words.
* `tools/dosdis16.py`'s `listing` puts an instruction boundary **on** the
  offset asked for.  A listing that starts mid-instruction decodes to
  plausible nonsense, which is the one failure mode that costs a day.
* `tools/doscurse.py`'s `PANES` all lie inside the 320x200 frame DOSBox is
  configured to give, so a crop cannot silently come back empty.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from tools import doscurse, dosdis16, dualclassdos  # noqa: E402

# --------------------------------------------------------------------------
# Which game a record came out of
# --------------------------------------------------------------------------


@pytest.mark.parametrize("parts, expect", [
    (("games", "CURSE", "GAME", "CURSE", "SAVE", "CHRDATA1.SAV"),
     "Curse of the Azure Bonds"),
    (("games", "Treasures of the Savage Frontier", "GAME", "TREASURE",
      "SAVE", "CHRDATA7.SAV"),
     "Treasures of the Savage Frontier"),
    (("games", "Gateway to the Savage Frontier", "GAME", "GATEWAY",
      "OGRE.GUY"),
     "Gateway to the Savage Frontier"),
])
def test_source_title_names_the_game_tree(parts, expect):
    assert dualclassdos.source_title(pathlib.Path(*parts)) == expect


def test_the_deepest_game_directory_wins():
    """`Pools of Darkness/GAME/SECRET/` holds a *Silver Blades* party.

    It is where Pools of Darkness looks for one to import, so the outer
    directory is the wrong answer and the inner one is right.
    """
    path = pathlib.Path("games", "Pools of Darkness", "GAME", "SECRET",
                        "SAVE", "CHRDATA1.SAV")
    assert dualclassdos.source_title(path) == "Secret of the Silver Blades"


@pytest.mark.parametrize("parts", [
    ("SavesDir", "76561197971030711", "1882370", "English", "CHRDATA1.SAV"),
    ("work", "curse", "234-before", "CHRDATA1.SAV"),
])
def test_a_path_that_names_no_game_tree_refuses(parts):
    """`?` rather than a guess: a Steam app id names the whole collection."""
    assert dualclassdos.source_title(pathlib.Path(*parts)) == "?"


# --------------------------------------------------------------------------
# The listing lands on the offset it was asked for
# --------------------------------------------------------------------------


#: `mov ax, 0x1234` (3 bytes), `nop`, `mov es:[di+0x111], al` (6 bytes), `ret`.
#: Written here rather than sliced out of an overlay: the game's bytes are not
#: a test fixture, and what is under test is the alignment search, which needs
#: only some instruction stream with a known boundary in it.
STREAM = bytes.fromhex("b83412" "90" "2688851101" "c3")
SITE = 4                                     # the `mov es:[di+...]`


def test_listing_puts_a_boundary_on_the_site():
    capstone = pytest.importorskip("capstone")
    assert capstone                          # used only to skip without it
    lines = dosdis16.listing(STREAM, SITE, before=8, window=8)
    marked = [ln for ln in lines if ln.rstrip().endswith("<<<")]
    assert len(marked) == 1, lines
    assert marked[0].lstrip().startswith(f"{SITE:06X}"), marked


def test_listing_refuses_rather_than_printing_an_empty_window():
    """Past the end of the image there is no boundary, and it says so."""
    pytest.importorskip("capstone")
    lines = dosdis16.listing(STREAM, len(STREAM) + 16, before=4, window=8)
    assert lines == ["  (no alignment within 4 bytes lands on 0x1a)"], lines


def test_strings_in_finds_a_run_and_reports_its_offset():
    image = b"\x00\x01Free training on\x00\xff"
    assert dosdis16.strings_in(image, "training") == [(2, "Free training on")]


# --------------------------------------------------------------------------
# The panes are inside the frame
# --------------------------------------------------------------------------


def test_every_pane_lies_inside_a_320x200_frame():
    for name, geometry in doscurse.PANES.items():
        w, h, x, y = (int(v) for v in
                      geometry.replace("x", " ").replace("+", " ").split())
        assert w > 0 and h > 0, name
        assert x + w <= 320 and y + h <= 200, f"{name}: {geometry}"
