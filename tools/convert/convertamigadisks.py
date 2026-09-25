#!/usr/bin/env python3
"""Drive Save As offscreen and write the two POOLSAVE.ADF disks
step 4 of `#36 (Write an Amiga disk image, not just the character files)`
loads in WinUAE -- one from a C64 source, one from a DOS source.

    .venv/bin/python tools/convert/convertamigadisks.py --disk POR2.ADF \\
        [--out DIR]

`--disk` is the Amiga Pool of Radiance disk 2 the conversion writes into (it
is not in the repository and there is no default). The sources are two
specimens in `$WISH_SPECIMENS` (default `~/wish-specimens`):
`por-c64/WISH-SPEC-por-party-twin-pair.d64` and
`por-dos/WISH-SPEC-por-item-granted/SAVGAMD.DAT`. Output goes to `c64/` and
`dos/` under `--out`.

No picker ever opens: `tools/convert/saveasdrive.py` calls
`saveplan.prepare_save_as` and `saveplan.publish` with every row as an
argument. Prints each conversion's own report so the WinUAE run has something
to check the screen against. `tools/convert/convertsourcesheet.py` prints the source
records' own sheets for the same comparison. Offscreen.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

from editor.window import EditorBinding  # noqa: E402
from tools.convert import saveasdrive  # noqa: E402
from tools.registry import scratch  # noqa: E402

SPECS = pathlib.Path(os.environ.get("WISH_SPECIMENS",
                                    os.path.expanduser("~/wish-specimens")))


def run(tag: str, source: pathlib.Path, disk: pathlib.Path,
        here: pathlib.Path) -> None:
    out = here / tag
    out.mkdir(parents=True, exist_ok=True)
    window = EditorBinding(QWidget())
    try:
        report = saveasdrive.save_as(window, source, "amiga", out,
                                     amiga_disk=disk)
    finally:
        window.close()

    print(f"=== {tag}")
    print(f"source     {source}")
    print(f"slot       {report.get('slot')!r}")
    if "refused" in report:
        print(f"refused    {report['refused'][0]}: {report['refused'][1]}")
    for line in report.get("losses", []):
        print(f"loss       {line}")
    for line in report.get("dropped", []):
        print(f"dropped    {line}")
    for path in report.get("written", []):
        print(f"wrote      {path}  {pathlib.Path(path).stat().st_size}")


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
