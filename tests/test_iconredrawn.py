"""`tools/iconredrawn.py` draws the page `#335` is decided from.

`#335 (Two combat-figure rows describe Pool of Radiance's art, and Silver
Blades draws those two options differently)` is a judgement about two
pictures, so the tool that draws them has one job worth pinning: never to
show something that is no longer true.  Two ways it could:

* by **hard-coding which options diverge**, and going on describing a
  divergence a re-measured comparison no longer finds;
* by **hard-coding which C64 figure a row names**, and drawing the option
  Donald's table named last week rather than the one it names now.

So these check that both ends are read at run time.  What the figures *look*
like is Donald's to judge and nothing here asserts it.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))

import iconproposal as ip  # noqa: E402
import iconredrawn as ir  # noqa: E402

#: What Silver Blades re-drew, the same set `tests/test_iconparts.py` pins:
#: `(kind, option, size)`, both poses of each.
REDREW = {("head", 10, "large"), ("weapon", 11, "small")}


@pytest.fixture(scope="module")
def folders():
    """Pool of Radiance's and Silver Blades' DOS game directories, or skip."""
    gamedisks = pytest.importorskip("tools.gamedisks")
    root = gamedisks.find("dos-archives")
    if root is None or not root.is_dir():
        pytest.skip("needs the DOS games; set $FR_ARCHIVES")
    try:
        found = ir.dit.find_folders(root, [ir.REFERENCE, ir.SUBJECT])
    except SystemExit as exc:  # pragma: no cover - depends on the machine
        pytest.skip(str(exc))
    if ir.REFERENCE not in found or ir.SUBJECT not in found:
        pytest.skip("needs both Pool of Radiance and Silver Blades")
    return found


@pytest.fixture(scope="module")
def rows(folders):
    return ir.redrawn(folders[ir.REFERENCE], folders[ir.SUBJECT])


def test_the_two_redrawn_options_are_measured_rather_than_named(rows):
    """Nothing in the tool says *which* options diverge; the files do."""
    assert {(r["kind"], r["option"], r["size"]) for r in rows} == REDREW
    assert all(r["poses"] == 2 for r in rows), "both poses of each"


def test_the_head_gains_a_hat_and_the_body_loses_its_weapon(rows):
    """The two differences the page's sentences are chosen by."""
    by_kind = {r["kind"]: r for r in rows}
    assert "cap" in by_kind["head"]["gained"]
    assert "cap" not in by_kind["head"]["lost"]
    assert "weapon" in by_kind["weapon"]["lost"]
    assert "weapon" not in by_kind["weapon"]["gained"]


def test_the_page_names_the_option_the_table_names_now(folders):
    """The C64 number on the page comes out of the YAML, not out of here.

    A row Donald re-points has to move the page with it -- the whole reason
    the table is a file he edits by hand.
    """
    pytest.importorskip("PIL")
    gamedisks = pytest.importorskip("tools.gamedisks")
    disks = gamedisks.find(ir.SUBJECT)
    if disks is None or not (disks / "SILVER-1.D64").is_file():
        pytest.skip("needs the C64 Silver Blades disks; set $SSB_DISKS")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        html = ir.page(folders[ir.SUBJECT], folders[ir.REFERENCE],
                       disks / "SILVER-1.D64", ip.DEFAULT_COLOURS, 3,
                       pathlib.Path(tmp))
    assert f"Commodore 64 head {ip.HEADS[10]}," in html
    assert f"Commodore 64 weapon {ip.WEAPONS[11]}," in html
    assert html.count("src='data:image/png;base64,") == html.count("<img ")
