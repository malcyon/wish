"""Finding the emulator's screen inside a grab of the whole guest desktop.

`tools/amigashots.py` cuts a 720x568 Amiga screen out of a 1920x1080 `winvm
shot` by looking for WinUAE's status bar underneath it.  What it must not do is
cut somewhere near it: a crop that is seven rows out looks like a screenshot
and is a picture of the wrong thing, which is the failure a person reading the
result cannot see.

The desktops here are built rather than captured -- `AGENTS.md` keeps the
game's own bytes out of the repository, and a synthetic desktop tests the rule
rather than one machine's window position.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools import amigashots  # noqa: E402

Image = pytest.importorskip("PIL.Image", reason="Pillow reads the grabs")

#: A desktop big enough to put the window somewhere other than the corner.
DESKTOP = (1920, 1080)

#: Where the window is put in these tests.  Nothing may read it back out of a
#: constant -- the point of the search is that the tool does not know it.
AT = (137, 43)


def _desktop(bottom_row, left=AT[0], top=AT[1]):
    """A wallpaper, an Amiga screen whose last row is `bottom_row`, a bar."""
    width, height = amigashots.CLIENT
    image = Image.new("RGB", DESKTOP, (31, 98, 176))
    screen = Image.new("RGB", (width, height), (0, 0, 34))
    for x in range(width):
        screen.putpixel((x, height - 1), bottom_row)
    image.paste(screen, (left, top))
    edge = Image.new("RGB", (width, 1), (215, 215, 215))
    image.paste(edge, (left, top + height))
    bar = Image.new("RGB", (width, 22), amigashots.STATUS_GREY)
    image.paste(bar, (left, top + height + 1))
    return image


def test_the_window_is_found_wherever_it_sits():
    assert amigashots.find_client(_desktop((0, 0, 34))) == AT


def test_a_white_bottom_row_does_not_pull_the_crop_up_into_the_picture():
    """Kickstart's insert-disk screen is white to the client's last row.

    Read as "walk up while the row is light", that white swallowed seven rows
    of the Amiga's own screen and pulled seven rows of desktop in underneath.
    """
    assert amigashots.find_client(_desktop((255, 255, 255))) == AT


def test_a_desktop_with_no_emulator_on_it_is_refused():
    """Rather than cropped to a guess, which would look like a screenshot."""
    plain = Image.new("RGB", DESKTOP, (31, 98, 176))
    with pytest.raises(LookupError):
        amigashots.find_client(plain)


def test_the_crop_is_the_emulator_screen_and_nothing_else(tmp_path):
    source, out = tmp_path / "grab.png", tmp_path / "screen.png"
    _desktop((255, 255, 255)).save(source)
    assert amigashots.crop(source, out) == AT
    cut = Image.open(out)
    assert cut.size == amigashots.CLIENT
    assert cut.getpixel((0, 0)) == (0, 0, 34)
    assert cut.getpixel((0, amigashots.CLIENT[1] - 1)) == (255, 255, 255)
