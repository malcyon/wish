"""The combat-figure table has to reach a Wish that was installed (#315).

`#315 (A frozen Wish cannot convert a combat figure, because the table it
needs lives outside the package)`: `goldbox.iconparts.PROPOSAL_PATH` resolves
to `<package parent>/tools/iconproposal.yaml`, so what a user gets when he
imports a DOS save depends on how his copy of Wish was built.  He picks
`File > Import`, chooses his DOS party, and either every character arrives
with his own figure or the conversion stops with `the combat-figure table is
not at ...` and no party at all.

Two build shapes, measured on 2026-09-05:

* **The wheel carries it.**  `pyproject.toml` lists `tools` among the wheel's
  packages and hatchling ships every file in a package directory, so
  `tools/iconproposal.yaml` is in the built wheel and `<site-packages>/tools`
  is exactly where `PROPOSAL_PATH` looks.  Unpacked onto `sys.path`,
  `dos_icon_tables()` read 32 weapon rows and 14 head rows.
* **The PyInstaller build does not.**  `wish.spec` declares no `datas` at all
  and says so in a comment, and PyInstaller copies no file that is not a
  module, so `dist/wish/` has no `tools/` directory.  That is the open half
  of `#315 (A frozen Wish cannot convert a combat figure, because the table
  it needs lives outside the package)` and the fix is a decision about where
  the file lives, which is not made here.

So what these tests hold is the half that works: the table stays inside a
directory a build ships, and a build that has lost it says where it should
have been rather than raising something a packager cannot act on.
"""

from __future__ import annotations

import pathlib
import tomllib

import pytest
from gamedata import disk_dir

from goldbox import iconparts

ROOT = pathlib.Path(__file__).resolve().parent.parent


def wheel_packages() -> list[str]:
    """The directories `pyproject.toml` puts in the wheel."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return data["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]


def test_the_combat_figure_table_is_inside_a_directory_the_wheel_ships():
    """Move the table out of a shipped package and an installed Wish breaks.

    Not a restatement of where the file is: it is the one check that fails
    the day somebody tidies `tools/iconproposal.yaml` into `work/`, `docs/`
    or the repository root, all of which leave a checkout working and every
    installed copy raising on the first DOS import.
    """
    inside = pathlib.Path(iconparts.PROPOSAL_PATH).resolve().relative_to(ROOT)
    assert inside.parts[0] in wheel_packages(), (
        f"{inside} is not inside any of {wheel_packages()}, so a wheel would "
        f"not carry it and an installed Wish could not convert a figure")


def test_the_table_is_read_from_wherever_it_is_put():
    """`dos_icon_tables` takes a path, so a build may put the file elsewhere.

    Whichever way `#315 (A frozen Wish cannot convert a combat figure,
    because the table it needs lives outside the package)` is settled, the
    reader has to work from a path handed to it rather than from the
    repository's own layout -- otherwise the fix would have to be a second
    copy of the table, which is the thing `goldbox/iconparts.py` exists to
    avoid.
    """
    tables = iconparts.dos_icon_tables(iconparts.PROPOSAL_PATH)
    assert tables.weapons and tables.heads
    assert len(tables.ega_to_c64) == 16


def test_a_build_that_lost_the_table_says_where_it_should_have_been(tmp_path):
    """The error a packager reads has to name the file, not just fail.

    This is what a frozen build raises today, and the message is the whole of
    what somebody debugging a `dist/wish/` has to go on.
    """
    missing = tmp_path / "nowhere" / "iconproposal.yaml"
    with pytest.raises(FileNotFoundError) as caught:
        iconparts.dos_icon_tables(missing)
    assert str(missing) in str(caught.value)


def test_the_small_counts_the_mixed_row_tool_uses_are_the_files_own():
    """`tools/dosmixedicon.py` hardcodes 28 and 14 so it can run disk-less.

    They are `SPELLE64`'s, read off the player's own disk by `IconParts`, and
    a copy that drifted would make the tool name the wrong rows as mixed.
    Checked against the disk when there is one, skipped when there is not.
    """
    import sys

    sys.path.insert(0, str(ROOT / "tools"))
    import dosmixedicon  # noqa: E402

    disks = disk_dir()
    if disks is None:
        pytest.skip("no game disks on this machine")
    loaded = None
    for path in sorted(pathlib.Path(disks).glob("*.[dD]64")):
        try:
            loaded = iconparts.IconParts.load(str(path))
            break
        except Exception:
            continue
    if loaded is None:
        pytest.skip("no SPELLE64/SPELLN64 on any disk here")
    assert dosmixedicon.SMALL_WEAPONS == loaded.count("small", "weapon")
    assert dosmixedicon.SMALL_HEADS == loaded.count("small", "head")
