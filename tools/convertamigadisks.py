#!/usr/bin/env python3
"""Drive `File > Convert...` offscreen and write the two POOLSAVE.ADF disks
step 4 of `#36 (Write an Amiga disk image, not just the character files)`
loads in WinUAE -- one from a C64 source, one from a DOS source.

    .venv/bin/python tools/convertamigadisks.py --disk POR2.ADF \\
        [--out DIR]

`--disk` is the Amiga Pool of Radiance disk 2 the conversion writes into (it
is not in the repository and there is no default). The sources are two
specimens in `$WISH_SPECIMENS` (default `~/wish-specimens`):
`por-c64/WISH-SPEC-por-party-twin-pair.d64` and
`por-dos/WISH-SPEC-por-item-granted/SAVGAMD.DAT`. Output goes to `c64/` and
`dos/` under `--out`.

No picker ever opens: `EditorBinding.convert` takes every row as an
argument. Prints each conversion's own report so the WinUAE run has something
to check the screen against. `tools/convertsourcesheet.py` prints the source
records' own sheets for the same comparison. Offscreen.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication, QDialog, QWidget  # noqa: E402

from editor import convert as convert_mod  # noqa: E402
from editor.window import EditorBinding  # noqa: E402
from tools import scratch  # noqa: E402

SPECS = pathlib.Path(os.environ.get("WISH_SPECIMENS",
                                    os.path.expanduser("~/wish-specimens")))


def run(tag: str, source: pathlib.Path, disk: pathlib.Path,
        here: pathlib.Path) -> None:
    out = here / tag
    out.mkdir(parents=True, exist_ok=True)
    window = EditorBinding(QWidget())
    seen = {}

    real_exec = convert_mod.ConvertDialog.exec

    def fake_exec(self):
        seen["dialog"] = self
        return QDialog.DialogCode.Accepted

    convert_mod.ConvertDialog.exec = fake_exec
    try:
        note = window.convert(source=str(source), destination="amiga",
                              disk=str(disk), folder=str(out))
    finally:
        convert_mod.ConvertDialog.exec = real_exec
        window.close()

    dialog = seen["dialog"]
    print(f"=== {tag}")
    print(f"source     {source}")
    print(f"status     {note}")
    print(f"slot       {dialog.slot!r}")
    report = getattr(dialog.rehearsal, "report", None)
    if report is not None:
        for w in getattr(report, "warnings", []) or []:
            print(f"warning    {w}")
        for d in getattr(report, "dropped", []) or []:
            print(f"dropped    {d}")
    for c in dialog.rehearsal.party:
        print("character  {:<16} {}".format(
            c.get("name", "?"), c.get("class_name", c.get("class", ""))))
    for p in sorted(out.rglob("*")):
        if p.is_file():
            print(f"wrote      {p}  {p.stat().st_size}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--disk", type=pathlib.Path, required=True,
                    help="the Amiga Pool of Radiance disk 2 image to write into")
    ap.add_argument("--out", type=pathlib.Path,
                    default=scratch.scratch_dir("convertamigadisks", "dialog"),
                    help="directory for the c64/ and dos/ output")
    args = ap.parse_args(argv)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication([])  # noqa: F841 -- kept alive for the run
    if not args.disk.exists():
        print(f"no Amiga disk 2 at {args.disk}", file=sys.stderr)
        return 2
    run("c64", SPECS / "por-c64" / "WISH-SPEC-por-party-twin-pair.d64",
        args.disk, args.out)
    run("dos", SPECS / "por-dos" / "WISH-SPEC-por-item-granted" / "SAVGAMD.DAT",
        args.disk, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
