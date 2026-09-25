#!/usr/bin/env python3
"""Produce an `AmigaToC64` Pool of Radiance conversion through Save As and hash what it wrote.

Save As is driven with no dialog: `tools/convert/saveasdrive.py` calls
`saveplan.prepare_save_as` and `saveplan.publish`, so the hashed bytes are the
rehearsed output Save As publishes. `tools/convert/convertdialogdrive.py` is the
same driver for the Amiga-destination directions.

`--tree` runs the conversion from another checkout, such as a detached
worktree pinned to the commit under test.

    .venv/bin/python -m tools.convert.convertamigatoc64 --tree . \\
        --specimen path/to/por1-outdoor.adf --disks path/to/c64-por-disks \\
        --out-dir OUT --summary OUT/summary.json

Runs offscreen; nothing opens on the desktop.
"""
import argparse
import hashlib
import json
import os
import pathlib
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tree", required=True,
                    help="checkout to run the conversion from")
    ap.add_argument("--specimen", required=True,
                    help="the Amiga Pool of Radiance disk to convert")
    ap.add_argument("--disks", required=True,
                    help="C64 Pool of Radiance game disks folder")
    ap.add_argument("--out-dir", required=True,
                    help="folder Convert writes its wish-YYYY-MM-DD subfolder "
                         "into")
    ap.add_argument("--summary", required=True)
    args = ap.parse_args(argv)

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    # Imported from this checkout before `--tree` goes first on the path,
    # so a tree that predates Save As still gets the driver; its own
    # `editor` package is what the driver then reaches.
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from tools.convert import saveasdrive

    tree = pathlib.Path(args.tree).resolve()
    sys.path.insert(0, str(tree))

    from PyQt6.QtWidgets import QApplication, QWidget

    QApplication.instance() or QApplication([])

    from editor.window import EditorBinding

    root = QWidget()
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    window = EditorBinding(root, disks=args.disks)
    try:
        result = saveasdrive.save_as(window, args.specimen, "c64", out_dir,
                                     c64_folder=args.disks)
    finally:
        window.close()

    print("save_as() ->", result)

    produced = {}
    for p in sorted(out_dir.glob("wish-*/*")):
        if p.is_file():
            produced[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
            print(f"  {p} sha256={produced[p.name]}")

    summary = {
        "specimen": args.specimen,
        "specimen_sha256": hashlib.sha256(
            pathlib.Path(args.specimen).read_bytes()).hexdigest(),
        "direction": "AmigaToC64 pool-of-radiance",
        "por_c64_disks": args.disks,
        "save_as_result": result,
        "out_dir": str(out_dir),
        "produced_sha256": produced,
    }
    pathlib.Path(args.summary).write_text(json.dumps(summary, indent=2))
    print("wrote", args.summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
