from __future__ import annotations

"""The files the program reads at run time reach the frozen build.

Nothing failed when the Windows package shipped without the artist's SVGs
(`#351`): `QSvgRenderer` on a missing file returns an empty renderer, the
icon painter drew its own ground and nothing on it, and About drew nothing.
Three things here would each have caught it.

* `goldbox.assets.asset_path` is the one place a run-time file's path is
  built, and it finds the file in a checkout *and* under a simulated
  `sys._MEIPASS`.
* Every `asset_path("...")` call in the shipping packages names a file that
  exists in the checkout and is listed in `wish.spec`'s `datas`.
* No module in those packages builds a path to the checkout root from
  `__file__` on its own, which is how both readers got it wrong.
"""

import pathlib
import re
import shutil
import sys

import pytest

from goldbox import assets
from tests.test_packaging import _run_spec

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: The packages a frozen build carries -- `pyproject.toml`'s wheel list.
PACKAGES = ("goldbox", "editor", "automap", "wish", "tools", "ui")

#: `asset_path("assets", "logo", "mark.svg")` -- literal string arguments
#: only, which is what the module's docstring asks of callers so this can
#: read them.
CALL = re.compile(r'asset_path\(\s*((?:"[^"]+"\s*,?\s*)+)\)')


def _sources() -> list[pathlib.Path]:
    return [path for package in PACKAGES
            for path in (ROOT / package).rglob("*.py")]


def _asked_for() -> dict[pathlib.Path, list[str]]:
    """Every run-time file the source asks for, and who asks."""
    found: dict[pathlib.Path, list[str]] = {}
    for path in _sources():
        for match in CALL.finditer(path.read_text(encoding="utf-8")):
            parts = re.findall(r'"([^"]+)"', match.group(1))
            found.setdefault(pathlib.Path(*parts), []).append(
                str(path.relative_to(ROOT)))
    return found


def _datas() -> list[tuple[str, str]]:
    analysis, = _run_spec("win32")["Analysis"]
    return list(analysis.kwargs.get("datas", []))


def _shipped(relative: pathlib.Path, datas) -> bool:
    """Does a `(source, destination)` pair put `relative` under `_MEIPASS`
    at the same relative path a checkout has it at?

    `source` may be a file or a directory; either way PyInstaller writes it
    into `destination`, so the file's frozen path is `destination / name`.
    """
    for source, destination in datas:
        source = pathlib.Path(source)
        if source == relative:
            landed = pathlib.Path(destination) / source.name
        elif source in relative.parents:
            landed = pathlib.Path(destination) / relative.relative_to(source)
        else:
            continue
        if landed == relative:
            return True
    return False


# --- the resolver -----------------------------------------------------------


def test_in_a_checkout_it_is_the_checkout():
    assert not assets.frozen()
    assert assets.root() == ROOT
    assert assets.asset_path("assets", "logo", "mark.svg").is_file()


def test_frozen_it_is_meipass(monkeypatch, tmp_path):
    """The shape PyInstaller's bootloader leaves: `sys.frozen` set,
    `sys._MEIPASS` naming the unpacked `datas`."""
    (tmp_path / "assets" / "logo").mkdir(parents=True)
    shutil.copy(ROOT / "assets" / "logo" / "mark.svg",
                tmp_path / "assets" / "logo" / "mark.svg")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert assets.frozen()
    assert assets.root() == tmp_path
    assert assets.asset_path("assets", "logo", "mark.svg").is_file()


def test_frozen_without_meipass_is_not_frozen(monkeypatch):
    """A `frozen` flag with no unpack directory sends nobody to a directory
    that does not exist."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert not assets.frozen()
    assert assets.root() == ROOT


def test_the_readers_resolve_through_it(monkeypatch, tmp_path):
    """The two files `#351` shipped without, asked for under a frozen root.

    Both module constants are built at import time, so this reloads them
    under the simulated `_MEIPASS` rather than reading the constants as they
    stand.
    """
    import importlib

    pytest.importorskip("PyQt6.QtSvg")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    import wish.about
    from ui import appicon
    try:
        appicon = importlib.reload(appicon)
        about = importlib.reload(wish.about)
        assert appicon.ASSET == tmp_path / "assets" / "logo" / "mark.svg"
        for side, path in appicon.RASTERS.items():
            assert path == tmp_path / "assets" / "logo" / f"mark-{side}.png"
        assert about.PICTURE_ASSET == (
            tmp_path / "assets" / "logo" / "combo-mark-color.svg")
    finally:
        monkeypatch.undo()
        importlib.reload(appicon)
        importlib.reload(wish.about)


# --- the package ------------------------------------------------------------


def test_something_is_asked_for():
    """The scan finds the two readers `#351` is about, and the four PNGs the
    taskbar icon is scaled from; an empty result would mean the regex has
    stopped matching and the checks below pass vacuously."""
    asked = _asked_for()
    assert pathlib.Path("assets/logo/mark.svg") in asked
    assert pathlib.Path("assets/logo/combo-mark-color.svg") in asked
    for side in (80, 150, 200, 500):
        assert pathlib.Path(f"assets/logo/mark-{side}.png") in asked, side


@pytest.mark.parametrize("relative", sorted(_asked_for()),
                         ids=lambda p: str(p))
def test_every_asset_the_code_asks_for_exists(relative):
    assert (ROOT / relative).is_file(), f"{relative} asked for by " \
        f"{_asked_for()[relative]} is not in the checkout"


@pytest.mark.parametrize("relative", sorted(_asked_for()),
                         ids=lambda p: str(p))
def test_every_asset_the_code_asks_for_is_in_the_package(relative):
    """The check that was missing when the Windows build shipped."""
    assert _shipped(relative, _datas()), (
        f"{relative} is read by {_asked_for()[relative]} and is not in "
        f"wish.spec's DATAS, so a frozen build does not carry it")


def test_every_data_file_the_spec_lists_exists():
    """The other direction: a `datas` entry naming a file that is not there
    fails `pyinstaller` at build time, which is later than here."""
    for source, _destination in _datas():
        assert (ROOT / source).exists(), source


def test_the_spec_lists_it_on_both_platforms():
    assert _run_spec("linux")["Analysis"][0].kwargs["datas"] == _datas()


# --- nobody else builds the path ------------------------------------------

#: `Path(__file__)...parent.parent` outside `goldbox/assets.py` is a reader
#: that will not find its file in a frozen build. Two are known and allowed:
#: `wish/__main__.py` and `tools/wish.py` put the checkout on `sys.path` for
#: a run from a checkout, which is not a file read. `goldbox/iconparts.py`
#: is the open one -- `#315 (A frozen Wish cannot convert a combat figure,
#: because the table it needs lives outside the package)` -- and comes off
#: this list when that closes.
ROOT_FROM_FILE = re.compile(r"__file__\)[^\n]*\.parent\.parent")
ALLOWED = {
    "goldbox/assets.py",
    "wish/__main__.py",
    "tools/wish.py",
    "goldbox/iconparts.py",     # #315
}


def test_no_other_module_builds_a_path_to_the_checkout_root():
    offenders = []
    for path in _sources():
        #: `as_posix()`, not `str()`: on Windows this renders as
        #: `goldbox\\assets.py`, which matches neither the `tools/` prefix
        #: below nor anything in `ALLOWED` -- so every module is reported and
        #: the test fails on both Windows jobs while passing on Linux.
        #: `tests/test_repository_contents.py` carries the same note, having
        #: been bitten first.
        name = path.relative_to(ROOT).as_posix()
        if name.startswith("tools/") and name not in ("tools/wish.py",):
            continue        # developer scripts run from a checkout by design
        if name in ALLOWED:
            continue
        if ROOT_FROM_FILE.search(path.read_text(encoding="utf-8")):
            offenders.append(name)
    assert offenders == [], (
        f"{offenders} build a path from __file__ to the checkout root; "
        "use goldbox.assets.asset_path, which a frozen build can follow")
