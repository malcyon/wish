#!/usr/bin/env python3
"""Convert a save to an Amiga save disk through `File ▸ Convert…`'s own code
path, with the dialog's modals stubbed, and hash what came out.

Written for `#52 (File ▸ Import and File ▸ Export for every direction the
library supports)`, whose walks of `DosToAmiga` (Secret of the Silver Blades
and Curse of the Azure Bonds) and `C64ToAmiga` (Silver Blades) each needed
the same driver: `EditorBinding.convert` is called the way the window calls
it, `ConvertDialog.exec` returns Accepted, and the post-write
`QMessageBox.information` and the `.critical`/`.warning` pair
(`#542 (tools/convert/convertrun.py hangs forever on any successful C64 write,
because it never patches EditorBinding.convert's post-write
QMessageBox.information)`) record what they were asked to show instead of
blocking on a real `exec()` loop under the offscreen platform, the way
`tests/test_convert.py` does. Those three walks were three copies of this one
script that differed only in the constants now passed as arguments.

What it writes, under `--out-dir`: the converted files in a `wish-<date>/`
subfolder, and a JSON report (`--report`) of the specimen and its SHA-256, the
Amiga disk 2, the note `convert` returned, every popup it would have shown and
the SHA-256 of every file written. The report is also printed.

`--tree` runs the conversion from another checkout, such as a detached
worktree pinned to the commit under test; it defaults to this one. `--disks`
is the C64 game-disks folder a C64 source needs (`--c64-game` looks it up in
`tools/registry/gamedisks.py` instead); a DOS source needs neither.

    .venv/bin/python -m tools.convert.convertdialogdrive \\
        --specimen ~/wish-specimens/por-dos/WISH-SPEC-ssb-234-party-pair/SAVGAMC.DAT \\
        --amiga-disk2 /path/to/SecretOfTheSilverBlades_B.adf

Runs offscreen; nothing opens on the desktop.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--specimen", required=True, type=pathlib.Path,
                    help="the DOS SAVGAM file or C64 disk to convert")
    ap.add_argument("--amiga-disk2", required=True, type=pathlib.Path,
                    help="the title's Amiga disk 2, the one carrying ecl.dax")
    ap.add_argument("--out-dir", type=pathlib.Path,
                    default=None,
                    help="folder Convert writes its wish-<date> subfolder into "
                         "(default: this tool's scratch directory)")
    ap.add_argument("--report", type=pathlib.Path,
                    help="where to write the JSON report "
                         "(default: <out-dir>/convert-report.json)")
    ap.add_argument("--disks", type=pathlib.Path,
                    help="C64 game-disks folder, for a C64 source")
    ap.add_argument("--c64-game",
                    help="look the C64 disks up in tools/registry/gamedisks.py by this "
                         "title key, e.g. secret-of-the-silver-blades")
    ap.add_argument("--tree", type=pathlib.Path, default=ROOT,
                    help="checkout to run the conversion from (default: this "
                         "one)")
    args = ap.parse_args(argv)

    os.environ.pop("WAYLAND_DISPLAY", None)
    os.environ.pop("XDG_SESSION_TYPE", None)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["GDK_BACKEND"] = "x11"
    os.environ.setdefault("POR_HEADLESS", "1")

    sys.path.insert(0, str(args.tree.resolve()))

    from PyQt6.QtWidgets import QApplication, QDialog, QWidget

    from editor import convert as convert_mod
    from editor.window import EditorBinding
    from tools.registry import gamedisks, scratch

    out = args.out_dir or scratch.scratch_dir("convertdialogdrive")
    report_path = args.report or out / "convert-report.json"

    report: dict = {}

    specimen = args.specimen.expanduser()
    if not specimen.exists():
        ap.error(f"no such specimen: {specimen}")
    report["specimen"] = str(specimen)
    report["specimen_sha256"] = hashlib.sha256(specimen.read_bytes()).hexdigest()

    amiga_disk2 = args.amiga_disk2.expanduser()
    if not amiga_disk2.exists():
        ap.error(f"no such Amiga disk 2: {amiga_disk2}")
    report["amiga_disk2"] = str(amiga_disk2)

    c64_disks = args.disks
    if c64_disks is None and args.c64_game:
        c64_disks = gamedisks.find(args.c64_game)
    report["c64_disks_dir"] = str(c64_disks) if c64_disks else None

    # --- drive the dialog's own code path ----------------------------------
    app = QApplication.instance() or QApplication([])  # noqa: F841
    root = QWidget()
    window = EditorBinding(root,
                           disks=str(c64_disks) if c64_disks else None)

    shown: list = []

    def _stub_information(parent, title, text):
        shown.append(("information", title, text))

    def _stub_critical(parent, title, text):
        shown.append(("critical", title, text))

    def _stub_warning(parent, title, text):
        shown.append(("warning", title, text))

    orig_exec = convert_mod.ConvertDialog.exec
    orig_information = convert_mod.QMessageBox.information
    orig_critical = convert_mod.QMessageBox.critical
    orig_warning = convert_mod.QMessageBox.warning

    convert_mod.ConvertDialog.exec = lambda self: QDialog.DialogCode.Accepted
    convert_mod.QMessageBox.information = _stub_information
    convert_mod.QMessageBox.critical = _stub_critical
    convert_mod.QMessageBox.warning = _stub_warning

    scratch.ensure(out)
    try:
        note = window.convert(source=str(specimen), destination="amiga",
                              disk=str(amiga_disk2), folder=str(out))
    finally:
        convert_mod.ConvertDialog.exec = orig_exec
        convert_mod.QMessageBox.information = orig_information
        convert_mod.QMessageBox.critical = orig_critical
        convert_mod.QMessageBox.warning = orig_warning

    report["note"] = note
    report["popups"] = shown

    written = sorted(p for p in out.glob("wish-*/*") if p.is_file())
    report["written"] = [str(p) for p in written]
    report["written_sha256"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in written}

    print(json.dumps(report, indent=2))
    report_path.write_text(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
