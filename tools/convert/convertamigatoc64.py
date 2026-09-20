#!/usr/bin/env python3
"""Produce an `AmigaToC64` Pool of Radiance conversion through the dialog's own
code path, `editor.window.EditorBinding.convert`, and hash what it wrote.

Written for `#52 (File ▸ Import and File ▸ Export for every direction the
library supports)`. `ConvertDialog.exec` is patched to Accepted and the three
`QMessageBox` calls are patched to do nothing, the way the Curse and Silver
Blades walks and `tests/convert/test_convert.py`'s `_no_real_modals` fixture do:
`EditorBinding.convert`'s own success pop-up and `ConvertDialog._maybe_warn`'s
`.critical`/`.warning` all block on a real `exec()` loop nobody can dismiss
under the offscreen platform. `tools/convert/convertdialogdrive.py` is the same
driver for the Amiga-destination directions and records each popup instead of
dropping it.

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
    tree = pathlib.Path(args.tree).resolve()
    sys.path.insert(0, str(tree))

    from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget

    QApplication.instance() or QApplication([])

    from editor import convert as convert_mod
    from editor.window import EditorBinding

    orig_exec = convert_mod.ConvertDialog.exec
    convert_mod.ConvertDialog.exec = lambda self: QDialog.DialogCode.Accepted
    orig_critical = QMessageBox.critical
    orig_warning = QMessageBox.warning
    orig_information = QMessageBox.information
    QMessageBox.critical = staticmethod(lambda *a, **k: None)
    QMessageBox.warning = staticmethod(lambda *a, **k: None)
    QMessageBox.information = staticmethod(lambda *a, **k: None)

    root = QWidget()
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    window = EditorBinding(root, disks=args.disks)
    try:
        result = window.convert(source=args.specimen, destination="c64",
                                folder=str(out_dir))
    finally:
        convert_mod.ConvertDialog.exec = orig_exec
        QMessageBox.critical = orig_critical
        QMessageBox.warning = orig_warning
        QMessageBox.information = orig_information
        window.close()

    print("convert() ->", result)

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
        "convert_result": result,
        "out_dir": str(out_dir),
        "produced_sha256": produced,
    }
    pathlib.Path(args.summary).write_text(json.dumps(summary, indent=2))
    print("wrote", args.summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
