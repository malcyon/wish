"""The combat-figure table has to reach a Wish that was installed (#315).

`#315 (A frozen Wish cannot convert a combat figure, because the table it
needs lives outside the package)`: `goldbox.iconparts.PROPOSAL_PATH` used to
resolve to `<package parent>/tools/iconproposal.yaml`, so what a user got
when he imported a DOS save depended on how his copy of Wish was built. He
picks `File > Import`, chooses his DOS party, and either every character
arrives with his own figure or the conversion stops with `the combat-figure
table is not at ...` and no party at all.

Two build shapes, both now carrying the file:

* **The wheel carries it.**  `pyproject.toml` lists `tools` among the wheel's
  packages and hatchling ships every file in a package directory, so
  `tools/iconproposal.yaml` is in the built wheel and `<site-packages>/tools`
  is exactly where `PROPOSAL_PATH` looks.  Unpacked onto `sys.path`,
  `dos_icon_tables()` read 32 weapon rows and 14 head rows.
* **The PyInstaller build now does too.**  `PROPOSAL_PATH` resolves through
  `goldbox.assets.asset_path`, the resolver `#351 (The Windows build shows no
  logo in About and a black square on the taskbar, because the artist's SVGs
  are not in the package)` added, and `wish.spec`'s `DATAS` carries
  `("tools/iconproposal.yaml", "tools")` -- so `dist/wish/tools/` has the
  file and a frozen import converts a figure the way a checkout always has.

So what these tests hold: the table stays inside a directory both builds
ship, a frozen import resolves it under a simulated `sys._MEIPASS`, and a
build that has genuinely lost it still says where it should have been rather
than raising something a packager cannot act on.
"""

from __future__ import annotations

import importlib
import pathlib
import shutil
import sys
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


def test_the_frozen_build_carries_the_table():
    """The half `#315 (A frozen Wish cannot convert a combat figure, because
    the table it needs lives outside the package)` left open: a PyInstaller
    `dist/wish/` had no `tools/` directory at all, because `wish.spec`
    declared no `datas`. `goldbox.assets.asset_path` is the resolver added
    for `#351`; this checks the file `PROPOSAL_PATH` names is one
    `wish.spec`'s `DATAS` actually carries, not merely one that exists in
    this checkout.
    """
    from goldbox import assets
    from tests.test_packaging import _run_spec

    relative = pathlib.Path(iconparts.PROPOSAL_PATH).resolve().relative_to(
        assets.CHECKOUT)
    analysis, = _run_spec("win32")["Analysis"]
    datas = analysis.kwargs.get("datas", [])
    assert any(pathlib.Path(source) == relative for source, _dest in datas), (
        f"{relative} is not in wish.spec's DATAS, so a frozen build would "
        f"not carry it and dos_icon_tables would raise FileNotFoundError")


def test_it_resolves_under_a_frozen_root(monkeypatch, tmp_path):
    """`PROPOSAL_PATH` is a module-level constant, so this reloads
    `goldbox.iconparts` under a simulated `sys._MEIPASS` rather than reading
    the constant as it stands -- the shape PyInstaller's bootloader leaves,
    per `tests/test_assets.py`.

    **Restored from a snapshot, not by reloading again.** `importlib.reload`
    redefines every class in the module in place, so `goldbox.iconparts.
    IconParts` after even the "restoring" reload is a *third* class object,
    still not the one `goldbox.dos` already holds a reference to from its own
    `from .iconparts import IconParts` at import time. Any `IconParts`
    instance built after that -- `tests/test_ssbconvert.py`'s `ssb_parts`
    fixture makes one straight off a disk -- then fails every `isinstance`
    check `goldbox/dos.py` runs against its own, older reference, and a
    combat icon comes back as the unconverted `IconParts` object instead of
    36 bytes. That is what was failing only inside a full parallel run in
    `#374 (The Silver Blades figure test fails only inside a full parallel
    suite run, so the same commit can be green locally and red in CI)` --
    this test's own reload, whichever worker it landed in, leaking a
    permanently mismatched `IconParts` into every test that ran after it in
    that worker. A snapshot taken before the first reload and written back
    verbatim leaves every class the exact object it was, which a second
    reload cannot.
    """
    (tmp_path / "tools").mkdir()
    shutil.copy(iconparts.PROPOSAL_PATH, tmp_path / "tools" / "iconproposal.yaml")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    original = dict(vars(iconparts))
    try:
        reloaded = importlib.reload(iconparts)
        assert reloaded.PROPOSAL_PATH == tmp_path / "tools" / "iconproposal.yaml"
        assert reloaded.PROPOSAL_PATH.is_file()
    finally:
        monkeypatch.undo()
        vars(iconparts).clear()
        vars(iconparts).update(original)


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
