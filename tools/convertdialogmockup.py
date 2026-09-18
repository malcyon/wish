#!/usr/bin/env python3
"""Mock-up only, for step 1 of `#413 (The Convert window changes shape depending
on which platforms you are converting between)`.

Draws `editor/convert.py`'s `ConvertDialog` as Donald's chosen design would have
it -- four rows that never move, the third one changing its label and its
picker with the destination -- for all six directions, plus the two things
still open: where the `Slot` row goes, and what the third row shows for a C64
destination, which needs nothing from the player.

**Nothing here is built.** `editor/convert.py` and `editor/convert.ui` are
untouched; this builds widgets from the compiled `editor.ui_convert` shell
and adds new ones locally. Every string that has not been ruled on carries
` (NOT APPROVED)` in the image itself. `DOS game folder` carries
` (APPROVAL UNRECORDED)` instead. The paths drawn in the fields are made up.

    env -u WAYLAND_DISPLAY -u XDG_SESSION_TYPE QT_QPA_PLATFORM=offscreen \\
        GDK_BACKEND=x11 .venv/bin/python tools/convertdialogmockup.py [--out work/issue413]

`tools/convertdialogbuiltshot.py` is the same sheet drawn from the real,
built `ConvertDialog`. Needs Pillow and the DejaVu fonts.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from editor.ui_convert import Ui_ConvertDialog  # noqa: E402

#: Set by `main`, before anything draws.
app = None
OUT = str(ROOT / "work" / "issue413")
FONT = SMALL = TITLE = None

W, H = 700, 380

# Approved already: `From`, `To`, `Write to`, `Slot`, `Slot {slot}`,
# `Choose…`, `Convert`, `Convert Log`, `This writes:`, `Commodore 64`,
# `DOS`, `Amiga`, `Amiga game disk 2`, `Choose Amiga game disk 2.`,
# `Choose the DOS game folder.`
UNAPPROVED = " (NOT APPROVED)"
UNRECORDED = " (APPROVAL UNRECORDED)"

LABEL_DOS_GAME = "DOS game folder" + UNRECORDED
LABEL_AMIGA_DISK = "Amiga game disk 2"
LABEL_C64_DISKS = "C64 game disks" + UNAPPROVED
VALUE_PREFERENCES = "Set in Preferences" + UNAPPROVED
BUTTON_PREFERENCES = "Preferences…" + UNAPPROVED

SOURCES = {
    "c64": ("Commodore 64", "/home/ada/pool-of-radiance/PORSAVEA.D64"),
    "dos": ("DOS", "/home/ada/dos_por/SAVE/SAVGAMA.DAT"),
    "amiga": ("Amiga", "/home/ada/amiga-por/PoolSave.adf"),
}

DEST_NAME = {"c64": "Commodore 64", "dos": "DOS", "amiga": "Amiga"}

WRITES = {
    "c64": ["/home/ada/wish-out/wish-2026-09-07/PORSAVEA.D64"],
    "dos": ["/home/ada/wish-out/wish-2026-09-07/SAVGAMA.DAT",
            "/home/ada/wish-out/wish-2026-09-07/CHRDATA1.SAV"],
    "amiga": ["/home/ada/wish-out/wish-2026-09-07/POOLSAVE.ADF"],
}


def shell(source_port: str, dest_port: str):
    """The dialog as it is today, with the approved strings in place and a
    sample path standing in for what a player would have chosen."""
    dlg = QDialog()
    ui = Ui_ConvertDialog()
    ui.setupUi(dlg)
    dlg.setWindowTitle("Convert a save")

    ui.label_source.setText("From")
    ui.label_to.setText("To")
    ui.label_folder.setText("Write to")
    ui.label_slot.setText("Slot")

    # `Convert Log`, Donald's own words of 2026-09-07 from the `#316`
    # mock-up round. It is in the main checkout and not yet in this
    # worktree's HEAD, so the mock-up adds it rather than editing
    # `editor/convert.ui`.
    heading = QLabel("Convert Log")
    font = heading.font()
    font.setBold(True)
    heading.setFont(font)
    ui.outer_layout.insertWidget(1, heading)
    for i, stretch in enumerate((0, 0, 0, 1, 0)):
        ui.outer_layout.setStretch(i, stretch)

    ui.convert_source.setText(SOURCES[source_port][1])
    ui.convert_choose_source.setText("Choose…")
    ui.convert_choose_game.setText("Choose…")
    ui.convert_choose_folder.setText("Choose…")
    ui.convert_folder.setText("/home/ada/wish-out")

    for port in ("c64", "dos", "amiga"):
        if port != source_port:
            ui.convert_destination.addItem(DEST_NAME[port], port)
    ui.convert_destination.setCurrentIndex(
        ui.convert_destination.findData(dest_port))

    ui.convert_report.setPlainText(
        "\n".join(["This writes:", ""]
                  + [f"  {p}" for p in WRITES[dest_port]]))
    ui.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Convert")

    ui.form.setRowVisible(ui.convert_slot, False)
    dlg.resize(W, H)
    return dlg, ui


LABEL_COLUMN = 250


def pin_label_column(ui) -> None:
    """Hold the label column the same width in every tile, so the value
    column does not jump about between pictures. Without it the ` (NOT
    APPROVED)` markers -- which are not part of the design -- would be the
    thing moving the form, and the layout is what is being looked at."""
    for label in (ui.label_source, ui.label_to, ui.label_game,
                  ui.label_folder):
        label.setMinimumWidth(LABEL_COLUMN)


def third_row(ui, dest_port: str, c64_option: str = "c") -> None:
    """The one row that changes with the destination, in place at row 3."""
    if dest_port == "dos":
        ui.label_game.setText(LABEL_DOS_GAME)
        ui.convert_game.setText("/home/ada/dos_por")
        return
    if dest_port == "amiga":
        ui.label_game.setText(LABEL_AMIGA_DISK)
        ui.convert_game.setText("/home/ada/amiga-por/PoolOfRadiance2.adf")
        return
    # C64: nothing is needed from the player, and this is the open question.
    if c64_option == "a":                      # blank
        ui.label_game.setText("")
        ui.convert_game.setText("")
        ui.convert_choose_game.hide()
    elif c64_option == "b":                    # a sentence, nothing to press
        ui.label_game.setText(LABEL_C64_DISKS)
        ui.convert_game.setText(VALUE_PREFERENCES)
        ui.convert_choose_game.hide()
    else:                                      # c: offer Preferences
        ui.label_game.setText(LABEL_C64_DISKS)
        ui.convert_game.setText(VALUE_PREFERENCES)
        ui.convert_choose_game.setText(BUTTON_PREFERENCES)


def _slot_combo() -> QComboBox:
    combo = QComboBox()
    for letter in "ABCD":
        combo.addItem(f"Slot {letter}", letter)
    combo.setCurrentIndex(0)
    return combo


def slot_on_source_row(ui) -> None:
    """Option A -- the slot combo rides on the `From` row, so the form is
    four rows whether the source holds one saved game or six."""
    ui.source_row.addWidget(_slot_combo())


def slot_in_third_position(ui) -> None:
    """Option B -- the slot gets the varying row's own position, under
    `To`."""
    holder = QWidget()
    box = QHBoxLayout(holder)
    box.setContentsMargins(0, 0, 0, 0)
    box.addWidget(_slot_combo())
    box.addStretch(1)
    label = QLabel("Slot")
    label.setMinimumWidth(LABEL_COLUMN)
    ui.form.insertRow(3, label, holder)


def grab(dlg: QDialog, name: str) -> "Image.Image":
    dlg.show()
    app.processEvents()
    path = os.path.join(OUT, f"_{name}.png")
    dlg.grab().save(path)
    dlg.hide()
    return Image.open(path).convert("RGB")


# ---------------------------------------------------------------- composing

PAPER = (250, 249, 246)
INK = (20, 20, 20)
QUIET = (95, 95, 95)
RULE = (170, 170, 170)


def sheet(title: str, subtitle, cells, columns: int, path: str) -> None:
    """Captioned tiles on one page, `columns` across, so the options being
    chosen between are side by side and each says which it is."""
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


def six_combinations() -> None:
    cells = []
    for src in ("c64", "dos", "amiga"):
        for dst in ("c64", "dos", "amiga"):
            if src == dst:
                continue
            dlg, ui = shell(src, dst)
            third_row(ui, dst, c64_option="c")
            pin_label_column(ui)
            if src == "amiga":
                slot_on_source_row(ui)
            cells.append((f"{SOURCES[src][0]}  →  {DEST_NAME[dst]}",
                          grab(dlg, f"six-{src}-{dst}")))
    sheet(
        "#413 step 1 — the same four rows in all six directions",
        ["Four rows, always: From, To, the destination's own game files, "
         "Write to. Only the third row's label and its picker change.",
         "Drawn with the Slot combo on the From row (option A of picture 2) "
         "and with option C for a C64 destination (picture 3).",
         "Every string not yet ruled on is marked in the image itself. The "
         "Convert Log text is illustrative."],
        cells, 2, os.path.join(OUT, "413-1-six-combinations.png"))


def slot_options() -> None:
    cells = []

    dlg, ui = shell("amiga", "dos")
    third_row(ui, "dos")
    pin_label_column(ui)
    slot_on_source_row(ui)
    cells.append(("A — Slot on the From row.   Amiga → DOS: "
                  "four rows", grab(dlg, "slot-a-dos")))

    dlg, ui = shell("amiga", "dos")
    third_row(ui, "dos")
    pin_label_column(ui)
    slot_in_third_position(ui)
    cells.append(("B — Slot in the third-row position.   Amiga → "
                  "DOS: five rows", grab(dlg, "slot-b-dos")))

    dlg, ui = shell("amiga", "c64")
    third_row(ui, "c64", c64_option="c")
    pin_label_column(ui)
    slot_on_source_row(ui)
    cells.append(("A — Slot on the From row.   Amiga → C64: "
                  "four rows", grab(dlg, "slot-a-c64")))

    dlg, ui = shell("amiga", "c64")
    ui.form.setRowVisible(ui.game_row, False)
    pin_label_column(ui)
    slot_in_third_position(ui)
    cells.append(("B — Slot in the third-row position.   Amiga → "
                  "C64: four rows", grab(dlg, "slot-b-c64")))

    sheet(
        "#413 step 1 — where the Slot row goes",
        ["Slot varies by source rather than destination, and only an Amiga "
         ".adf has more than one saved game today.",
         "Top pair is the deciding case: going to DOS the third-row "
         "position is already taken, so B grows the window to five rows.",
         "Bottom pair is where B costs nothing, because a C64 destination "
         "asks the player for nothing and leaves that row free."],
        cells, 2, os.path.join(OUT, "413-2-slot-row.png"))


def c64_options() -> None:
    cells = []
    for key, caption in (
            ("a", "A — blank. No label, no value, no button"),
            ("b", "B — a sentence, nothing to press"),
            ("c", "C — the same sentence, and a way to change it")):
        dlg, ui = shell("dos", "c64")
        third_row(ui, "c64", c64_option=key)
        pin_label_column(ui)
        cells.append((caption, grab(dlg, f"c64-{key}")))
    sheet(
        "#413 step 1 — what the third row shows for a C64 destination",
        ["A C64 destination needs nothing from the player: Preferences "
         "already holds each title's Game disks folder.",
         "All three keep the window the same height. They differ in what "
         "the row says and whether there is anything to press.",
         "`C64 game disks` borrows Preferences' own words but is a new "
         "label, so it is marked unapproved, as are the value and button."],
        cells, 3, os.path.join(OUT, "413-3-c64-destination.png"))



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
                        help="where the sheets are written (default work/issue413)")
    args = parser.parse_args(argv)
    OUT = args.out
    os.makedirs(OUT, exist_ok=True)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(sys.argv[:1])
    load_fonts()

    six_combinations()
    slot_options()
    c64_options()

    for stray in sorted(os.listdir(OUT)):
        if stray.startswith("_") and stray.endswith(".png"):
            os.remove(os.path.join(OUT, stray))
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
