"""Every state `editor.convert.ConvertDialog` can reach, rendered to PNGs so
Donald can look at them without running anything.

`.claude/rules/gui-text.md`: "any UI decision requires a screenshot" -- a
hex colour or a field name is not a picture, and `QWidget.grab()` works
under `QT_QPA_PLATFORM=offscreen`, so there is never a reason to reason about
a layout instead of looking at it. This is `#52 (File ▸ Import and File ▸
Export for every direction the library supports)` step B's own tool,
`tools/iconsheet.py`'s pattern applied to a dialog instead of a custom-painted
canvas.

Four states need nothing but synthetic inputs -- a fake `game_files` lookup
and hand-built `SAVGAM?.*`/`CHRDAT?1.SAV` pairs, the same specimens
`tests/test_convert.py` uses -- and are always produced. The two "ready to
write" states need a rehearsal to actually succeed, which needs the
player's own DOS save and C64/DOS game files; those two are skipped, with a
line saying so, on a machine that has neither. A seventh, `_modal_state`, is
not the dialog at all: the report pane it used to draw on is gone
(2026-09-10), so a refusal or a name DOS's own field could not hold whole
now shows in a modal `QMessageBox` instead, and that box is what this one
renders -- built directly rather than through `QMessageBox.warning`, which
blocks on `.exec()` waiting for somebody to click it.

    env -u WAYLAND_DISPLAY -u XDG_SESSION_TYPE QT_QPA_PLATFORM=offscreen \\
        GDK_BACKEND=x11 .venv/bin/python tools/convertshots.py work/convertshots
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse  # noqa: E402
import pathlib  # noqa: E402
import tempfile  # noqa: E402

from PyQt6.QtWidgets import QApplication  # noqa: E402

from editor import convert  # noqa: E402
from goldbox import dos, dos_layout, games  # noqa: E402


def _dos_folder(root: pathlib.Path, shape, slot: str = "A",
                suffix: str = "DAT") -> pathlib.Path:
    """A folder just real enough for `Source.detect` to name its shape --
    the same synthetic specimen `tests/test_convert.py` builds, never a
    slice of a real save (`.claude/rules/testing.md`)."""
    folder = root / shape.key
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"SAVGAM{slot}.{suffix}").write_bytes(b"\x00")
    (folder / f"CHRDAT{slot}1.SAV").write_bytes(b"\x00" * shape.record_size)
    return folder


def _por_disk(root: pathlib.Path) -> pathlib.Path:
    """A real, readable -- but entirely zeroed -- Pool of Radiance C64
    save disk. Enough for `Source.detect` and the "no game folder yet"
    state; not enough for a rehearsal to succeed."""
    save0 = bytes(games.POOL_OF_RADIANCE.save_size)
    save1 = bytes(games.POOL_OF_RADIANCE.roster_size)
    disk = dos.save_disk(save0, save1)
    path = root / "PORSAVEA.D64"
    path.write_bytes(disk.to_bytes())
    return path


def _no_disks(_game):
    return None


def _synthetic_states(root: pathlib.Path):
    """The four states no real specimen is needed for."""
    empty = convert.ConvertDialog("", None, _no_disks)

    pod_folder = _dos_folder(root, dos_layout.POOLS_OF_DARKNESS, suffix="PTY")
    refused = convert.ConvertDialog(
        str(pod_folder / "SAVGAMA.PTY"), None, _no_disks)

    dos_folder = _dos_folder(root, dos_layout.POOL_OF_RADIANCE)
    no_disks_state = convert.ConvertDialog(
        str(dos_folder / "SAVGAMA.DAT"), None, _no_disks, folder=str(root))

    c64_disk = _por_disk(root)
    no_game_folder = convert.ConvertDialog(str(c64_disk), None, _no_disks)

    return [
        ("01-empty", empty),
        ("02-cannot-convert", refused),
        ("03-no-c64-disks", no_disks_state),
        ("04-no-dos-game-folder", no_game_folder),
    ]


def _ready_states(root: pathlib.Path):
    """The two states that need a rehearsal to actually succeed -- the
    player's own DOS save and game disks. `[]` when this machine has
    neither, which is correct rather than a failure
    (`.claude/rules/testing.md`: "a test that skips is not a test that
    passes", said here about a screenshot instead)."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent
                           / "tests"))
    from gamedata import disk_dir  # noqa: E402
    from test_dossave import _save_dir  # noqa: E402

    save_dir = _save_dir()
    disks = disk_dir()
    if save_dir is None or disks is None:
        print("skipping the two 'ready to write' states: needs $FR_ARCHIVES "
             "and the player's own POOL*.D64 disks")
        return []

    from PyQt6.QtWidgets import QWidget

    from editor.window import EditorBinding

    window = EditorBinding(QWidget(), disks=str(disks))
    ready_c64 = convert.ConvertDialog(
        str(save_dir / "SAVGAMA.DAT"), None, window.game_files_for,
        folder=str(root))

    c64_disk = None
    for candidate in sorted(pathlib.Path(disks).glob("POOL*.[dD]64")):
        try:
            convert.Source.detect(candidate)
        except convert.ConvertError:
            continue
        c64_disk = candidate
        break
    if c64_disk is None:
        window.close()
        print("skipping '06-ready-to-write-dos': no readable POOL*.D64 save "
             "disk here")
        return [("05-ready-to-write-c64", ready_c64)]

    ready_dos = convert.ConvertDialog(
        str(c64_disk), None, window.game_files_for,
        game=str(save_dir.parent), folder=str(root))
    window.close()
    return [("05-ready-to-write-c64", ready_c64),
           ("06-ready-to-write-dos", ready_dos)]


def _modal_state():
    """The one place left that a refusal or a name warning is shown, now
    that the report pane is gone: a modal `QMessageBox`. One example of
    each icon `ConvertDialog._maybe_warn` uses -- `.critical` for the five
    refusals, `.warning` for a name DOS's own field could not hold whole --
    built directly so nothing here blocks on a click."""
    from PyQt6.QtWidgets import QMessageBox

    warning = QMessageBox(
        QMessageBox.Icon.Warning, convert.DIALOG_TITLE,
        "SOVELISS: Name 'Soveliss the Magnificent' is longer than the DOS "
        "15 characters; truncated",
        QMessageBox.StandardButton.Ok)
    critical = QMessageBox(
        QMessageBox.Icon.Critical, convert.NO_DISKS_TITLE, convert.NO_DISKS,
        QMessageBox.StandardButton.Ok)
    return [("07-name-warning-modal", warning),
           ("08-refusal-modal", critical)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out_dir", nargs="?", default="work/convertshots",
                    help="where the PNGs go (default: %(default)s)")
    args = ap.parse_args(argv)
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication(["convertshots"])
    assert app is not None

    with tempfile.TemporaryDirectory(prefix="wish-convertshots-") as tmp:
        root = pathlib.Path(tmp)
        states = _synthetic_states(root) + _ready_states(root) \
            + _modal_state()
        for name, dialog in states:
            dialog.resize(dialog.sizeHint())
            dialog.show()
            app.processEvents()
            image = dialog.grab()
            path = out_dir / f"{name}.png"
            image.save(str(path))
            print(f"{path}  {image.width()}x{image.height()}")
            dialog.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
