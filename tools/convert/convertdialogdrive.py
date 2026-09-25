#!/usr/bin/env python3
"""Convert a save to an Amiga save disk through Save As, and hash what came out.

`tools/convert/saveasdrive.py` opens the specimen as the editor does and calls
`saveplan.prepare_save_as` and `saveplan.publish`, so the hashed bytes are the
rehearsed output Save As publishes. It serves the walks of `DosToAmiga` (Secret
of the Silver Blades and Curse of the Azure Bonds) and `C64ToAmiga` (Silver
Blades), which differ only in the constants passed as arguments. A conversion
Save As refuses is reported under `refused` and writes nothing.

What it writes, under `--out-dir`: the converted files in a `wish-<date>/`
subfolder, and a JSON report (`--report`) of the specimen and its SHA-256, the
Amiga disk 2, the outcome Save As reported (`slot`, `losses`, `dropped` or `refused`) and
the SHA-256 of every file written. The report is also printed.

`--tree` runs the conversion from another checkout, such as a detached
worktree pinned to the commit under test; it defaults to this one. `--disks`
is the C64 game-disks folder a C64 source needs (`--c64-game` looks it up in
`automap/gamedisks.py` instead); a DOS source needs neither.

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
                    help="look the C64 disks up in automap/gamedisks.py by this "
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

    from PyQt6.QtWidgets import QApplication, QWidget

    from automap import gamedisks
    from editor.window import EditorBinding
    from tools.convert import saveasdrive
    from tools.registry import scratch

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

    # --- drive Save As ----------------------------------------------------
    app = QApplication.instance() or QApplication([])  # noqa: F841
    root = QWidget()
    window = EditorBinding(root,
                           disks=str(c64_disks) if c64_disks else None)

    scratch.ensure(out)
    try:
        result = saveasdrive.save_as(window, specimen, "amiga", out,
                                     c64_folder=None, amiga_disk=amiga_disk2)
    finally:
        window.close()

    report["save_as"] = result

    written = sorted(p for p in out.glob("wish-*/*") if p.is_file())
    report["written"] = [str(p) for p in written]
    report["written_sha256"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in written}

    print(json.dumps(report, indent=2))
    report_path.write_text(json.dumps(report, indent=2))
    return 1 if "refused" in result else 0


if __name__ == "__main__":
    raise SystemExit(main())
