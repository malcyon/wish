"""The two ports' combat-icon option lists do not line up (#130).

`#130 (A converted DOS party arrives with six identical combat figures, not
its own)` asks whether DOS body `n` is C64 weapon `n`.  It is not, and this
is where that measurement is kept, because the tempting thing for a later
reader to do is exactly the wrong one: write `icon=parts.compose(size,
record.icon_body, record.icon_head)` and ship a party wearing somebody
else's figures.

Two claims, and each has a test:

* **the lists are different lengths.**  DOS offers 32 bodies and 14 heads in
  each of its two sizes; the C64 offers 28 weapons and 14 heads small, 35 and
  23 large.  So a DOS `icon_body` of 28 to 31 has no small-list counterpart
  at all, whatever a mapping did with the rest;
* **same-index art does not match.**  Rendering both ports' options and
  scoring every pairing, the same index is the best match once or twice in
  each of the four lists -- 32, 14, 32 and 14 options long -- which is what a
  list of unrelated figures scores by chance, and two of those are ties.

The art is Donald's and stays on his disks, so every test here skips without
them, and nothing is asserted about any particular figure's pixels.
"""

from __future__ import annotations

import pathlib
import sys

import pytest
from gamedata import disk_dir

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))

import iconcorrespond as ic  # noqa: E402

from goldbox import icons  # noqa: E402
from goldbox.iconparts import IconParts  # noqa: E402


def _dos_game():
    """The DOS game directory with `CBODY.DAX` in it, or skip."""
    try:
        return ic.dos_game(None)
    except SystemExit:
        pytest.skip("needs the DOS game files; set POR_DOS_GAME")


def _c64_disk():
    if disk_dir() is None:
        pytest.skip("needs the C64 game disks")
    return ic.c64_disk(None)


@pytest.fixture(scope="module")
def game():
    return _dos_game()


@pytest.fixture(scope="module")
def parts():
    return IconParts.load(str(_c64_disk()))


@pytest.fixture(scope="module")
def charset():
    return icons.load_icon_charset(str(_c64_disk()))


# -- the arithmetic, which needs no game files ------------------------------
def test_an_overlap_with_itself_is_one():
    mask = [[1 if x == y else 0 for x in range(ic.FIGURE)]
            for y in range(ic.FIGURE)]
    assert ic.overlap(mask, mask, 0, 0) == 1.0


def test_two_figures_a_row_apart_score_one_once_the_search_finds_them():
    """The search window is what stops a placement difference reading as art."""
    a = [[1 if y == 5 else 0 for _ in range(ic.FIGURE)]
         for y in range(ic.FIGURE)]
    b = [[1 if y == 6 else 0 for _ in range(ic.FIGURE)]
         for y in range(ic.FIGURE)]
    assert ic.overlap(a, b, 0, 0) == 0.0
    assert ic.best_overlap(a, b) == 1.0


def test_a_block_renders_as_many_pixels_as_its_header_declares():
    """Rows from byte 0, two pixels a byte from `block[2] * 4` of them."""
    block = bytes([2, 0, 3, 0] + [0] * 13) + bytes([0x12] * 24)
    pixels = ic.dos_pixels(block)
    assert len(pixels) == 2
    assert pixels[0] == [1, 2] * 12


# -- the finding -------------------------------------------------------------
@pytest.mark.parametrize("size,heads,bodies", [("small", 14, 32),
                                               ("large", 14, 32)])
def test_dos_offers_fourteen_heads_and_thirty_two_bodies(game, size, heads,
                                                         bodies):
    """`CHEAD.DAX` and `CBODY.DAX`, counted by block id rather than assumed."""
    assert len(ic.dos_options(game, "CHEAD", size)) == heads
    assert len(ic.dos_options(game, "CBODY", size)) == bodies


def test_the_two_ports_offer_different_numbers_of_options(game, parts):
    """Three of the four counts differ, so no mapping can be the identity.

    The C64's small head list is the one that happens to be 14 as well; every
    other pairing has one port offering options the other cannot name.
    """
    mismatched = [
        (size, kind)
        for size in ("small", "large")
        for kind, stem in (("weapon", "CBODY"), ("head", "CHEAD"))
        if len(ic.dos_options(game, stem, size)) != parts.count(size, kind)
    ]
    assert mismatched == [("small", "weapon"), ("large", "weapon"),
                          ("large", "head")]


@pytest.mark.parametrize("size,stem,kind", [("large", "CBODY", "weapon"),
                                            ("large", "CHEAD", "head"),
                                            ("small", "CBODY", "weapon"),
                                            ("small", "CHEAD", "head")])
def test_the_same_index_is_not_the_same_figure(game, parts, charset, size,
                                               stem, kind):
    """Over every option of one kind, how often index `n` matches index `n`.

    One or two of every list, which is what chance gives -- and two of them
    are ties the sort decides rather than the art.  Asserting a bound rather
    than the exact count, so that a rendering change moving one figure by a
    pixel does not fail a test about whether the lists correspond.
    """
    most = 2
    dos = {n: ic.mask(px)
           for n, px in ic.dos_options(game, stem, size).items()}
    c64 = {o: ic.mask(ic.c64_option(parts, charset, size, kind, o))
           for o in range(parts.count(size, kind))}
    hits = 0
    for n, left in dos.items():
        if n not in c64:
            continue
        best = max(c64, key=lambda o: ic.best_overlap(left, c64[o]))
        hits += best == n
    assert hits <= most, (
        f"{hits} of {len(dos)} {size} {kind} options are their own best "
        f"match, which would mean the two ports' lists do correspond")


def test_no_pair_of_figures_is_the_same_art(game, parts, charset):
    """The plain unarmed figure is obviously the same design in both ports.

    It is still only a 0.78 overlap, and it is the highest of all 1120
    pairings, so the C64 art is a redrawing rather than the DOS bitmaps at a
    different resolution -- which is why no threshold picks a mapping out.
    """
    dos = {n: ic.mask(px)
           for n, px in ic.dos_options(game, "CBODY", "large").items()}
    c64 = {o: ic.mask(ic.c64_option(parts, charset, "large", "weapon", o))
           for o in range(parts.count("large", "weapon"))}
    best = max(ic.best_overlap(left, right)
               for left in dos.values() for right in c64.values())
    assert 0.7 < best < 0.9
