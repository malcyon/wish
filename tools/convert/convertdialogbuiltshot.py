#!/usr/bin/env python3
"""The real, built `ConvertDialog` for all six directions, for `#413 (The Convert
window changes shape depending on which platforms you are converting between)`,
once every decision on it was made and the four-row form was built.

Unlike `tools/convert/convertdialogmockup.py`, this drives the actual
`editor.convert.ConvertDialog` class -- no shell built from `ui_convert` by hand,
no strings typed into widgets. The C64 destination's row is shown prefilled from
a fake `game_folder` callable standing in for Preferences, proving that path
draws correctly without needing real Preferences plumbing. It draws seven
dialogs: the six directions, and an Amiga source holding three saved games so
the `Slot` combo and the DOS game folder show together.

    env -u WAYLAND_DISPLAY -u XDG_SESSION_TYPE QT_QPA_PLATFORM=offscreen \\
        GDK_BACKEND=x11 .venv/bin/python tools/convert/convertdialogbuiltshot.py [--out DIR]

The synthetic DOS and C64 sources are built from `tests/fixtures`; the Amiga
disk comes from `tests/convert/test_amigatoc64` and the three-slot one from the
`por-amiga-outdoor` specimen (`$WISH_SPECIMENS`), so the last case needs that
specimen. Needs Pillow and the DejaVu fonts. The paths drawn in the fields are
made up.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from editor import convert  # noqa: E402
from goldbox import dos_port  # noqa: E402
from tools.registry import scratch  # noqa: E402

#: Set by `main`, before anything draws.
app = None
OUT = str(scratch.scratch_dir("convertdialogbuiltshot"))
FONT = SMALL = TITLE = None

W, H = 680, 305


def _synthetic_dos_folder(tmp_path, shape, slot="A"):
    folder = tmp_path / "dos"
    folder.mkdir(exist_ok=True)
    (folder / f"SAVGAM{slot}.DAT").write_bytes(b"\x00")
    (folder / f"CHRDAT{slot}1.SAV").write_bytes(b"\x00" * shape.record_size)
    return folder / f"SAVGAM{slot}.DAT"


def _por_c64_disk(tmp_path):
    from goldbox import dos_codec
    from goldbox.savegame import SaveGame0, SaveGame1

    fixtures = ROOT / "tests" / "fixtures"
    save0 = SaveGame0.from_prg((fixtures / "savedgame0.bin").read_bytes())
    save1 = SaveGame1.from_prg((fixtures / "savedgame1.bin").read_bytes())
    disk = dos_codec.save_disk(save0.to_bytes(), save1.to_bytes())
    path = tmp_path / "PORSAVEA.D64"
    path.write_bytes(disk.to_bytes())
    return path


def _amiga_disk(tmp_path):
    from support.amigatoc64 import _pool_of_radiance_disk_1

    disk = _pool_of_radiance_disk_1()
    path = tmp_path / "por1.adf"
    path.write_bytes(disk.to_bytes())
    return path


def _amiga_disk_three_slots(tmp_path):
    """The one specimen with more than one saved game -- so the `Slot`
    combo actually has something to show, on the `From` row, at the same
    time as the DOS game folder needs its own row (`#413`'s comment of
    2026-09-09: the case that settled where the combo goes)."""
    from gamedata import specimen

    where = specimen("por-amiga-outdoor", "amiga")
    path = tmp_path / "por1-outdoor.adf"
    path.write_bytes((where / "por1-outdoor.adf").read_bytes())
    return path


def _no_disks(_game):
    return None


def _game_folder(_game):
    return "/home/ada/pool-of-radiance"


def build(source, destination):
    return convert.ConvertDialog(
        str(source), None, _no_disks, destination=destination,
        folder="/home/ada/wish-out", game_folder=_game_folder)


def grab(dlg, name):
    dlg.resize(W, H)
    dlg.show()
    app.processEvents()
    path = os.path.join(OUT, f"_{name}.png")
    dlg.grab().save(path)
    dlg.hide()
    return Image.open(path).convert("RGB")


PAPER = (250, 249, 246)
INK = (20, 20, 20)
QUIET = (95, 95, 95)
RULE = (170, 170, 170)


def sheet(title, subtitle, cells, columns, path):
    pad, gap, cap = 26, 22, 30
    rows = (len(cells) + columns - 1) // columns
    head = 52 + 20 * len(subtitle) + 6
    width = pad * 2 + columns * W + (columns - 1) * gap
    height = head + pad + rows * (cap + H) + (rows - 1) * gap + pad

    page = Image.new("RGB", (width, height), PAPER)
    draw = ImageDraw.Draw(page)
    draw.text((pad, 18), title, font=TITLE, fill=INK)
    y = 54
    for line in subtitle:
        draw.text((pad, y), line, font=SMALL, fill=QUIET)
        y += 20
    draw.line([(pad, head - 6), (width - pad, head - 6)], fill=RULE, width=1)

    for i, (caption, image) in enumerate(cells):
        col, row = i % columns, i // columns
        x = pad + col * (W + gap)
        top = head + pad + row * (cap + H + gap)
        draw.text((x, top + 4), caption, font=FONT, fill=INK)
        page.paste(image, (x, top + cap))
        draw.rectangle([x - 1, top + cap - 1, x + W, top + cap + H],
                       outline=RULE)
    page.save(path)
    print(path, page.size)


def load_fonts() -> None:
    global FONT, SMALL, TITLE
    FONT = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 17)
    SMALL = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
    TITLE = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)


def main(argv=None) -> int:
    global app, OUT
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=OUT,
                        help="where the sheet is written (default: wish/convertdialogbuiltshot under the temp directory)")
    args = parser.parse_args(argv)
    OUT = args.out
    scratch.ensure(OUT)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(sys.argv[:1])
    load_fonts()

    tmp = tempfile.TemporaryDirectory()
    tmp_path = pathlib.Path(tmp.name)

    dos_source = _synthetic_dos_folder(tmp_path, dos_port.POOL_OF_RADIANCE)
    c64_source = _por_c64_disk(tmp_path)
    amiga_source = _amiga_disk(tmp_path)
    amiga_three_slots = _amiga_disk_three_slots(tmp_path)

    cases = [
        ("DOS  →  Commodore 64", dos_source, "c64"),
        ("DOS  →  Amiga", dos_source, "amiga"),
        ("Commodore 64  →  DOS", c64_source, "dos"),
        ("Commodore 64  →  Amiga", c64_source, "amiga"),
        ("Amiga  →  Commodore 64", amiga_source, "c64"),
        ("Amiga  →  DOS", amiga_source, "dos"),
        ("Amiga (3 saves)  →  DOS -- Slot AND DOS folder together",
         amiga_three_slots, "dos"),
    ]
    cells = []
    for caption, source, destination in cases:
        dlg = build(source, destination)
        cells.append((caption, grab(dlg, caption.replace(" ", "_"))))
        dlg.close()

    sheet(
        "#413 built -- the same four rows in all six directions",
        ["From (with the slot combo when the source holds more than one "
         "saved game), To, the destination's own game files, Write to.",
         "The C64 destination's row is prefilled from a fake Preferences "
         "stand-in here -- '/home/ada/pool-of-radiance' -- to show the "
         "real picker rather than a mock-up of one.",
         "No row appears or vanishes between any of the six."],
        cells, 2, os.path.join(OUT, "413-5-built.png"))

    for stray in sorted(os.listdir(OUT)):
        if stray.startswith("_") and stray.endswith(".png"):
            os.remove(os.path.join(OUT, stray))
    tmp.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
