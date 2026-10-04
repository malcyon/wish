#!/usr/bin/env python3
"""Edit a copy of a native save through the Character Editor's own Save, and report.

Copies `--base` to `--out`, opens it in `editor.window.EditorBinding` (offscreen),
changes one member's gold, strength and one item quantity the way the editor's
widgets and inventory model do, and calls `save(interactive=False)`. The report
(JSON, also printed) gives each field before and after, read back from the
written file with `Party`, the backup Save wrote under `backups/` and whether it
equals the pre-edit bytes, and the SHA-256 of base, out and backup. Nothing
else writes the disk, so the bytes are what a player's Save produces.

    .venv/bin/python tools/convert/nativesavedrive.py --base curse.adf \\
        --out /tmp/edited/curse.adf --who 1 --gold 5000 --strength 18 \\
        --item 0=3 [--slot B] [--report report.json]

`--who` is a zero-based roster row, `--item POSITION=QUANTITY` is repeatable and
names an inventory position of that member, and `--slot` picks the saved game on
a disk or folder that holds several.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_back(path: pathlib.Path, slot: str | None, who: int,
               items: dict[int, int]) -> dict:
    """The member's gold, strength and the named item quantities in `path`."""
    from editor.convert import Source
    from editor.roster import Party

    source = Source.detect(str(path), slot=slot) if slot else str(path)
    member = Party(source).members[who]
    return {"gold": member.record.get("gold"),
            "strength": member.record.get("strength"),
            "quantities": {str(pos): member.inventory.raws[pos][10]
                           for pos in items}}


def _commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
            capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def drive(base: pathlib.Path, out: pathlib.Path, who: int, gold: int,
          strength: int, items: dict[int, int],
          slot: str | None = None) -> dict:
    """Copy `base` to `out`, edit and save through the editor, and report."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.pop("WAYLAND_DISPLAY", None)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from PyQt6.QtWidgets import QApplication, QMainWindow

    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(base, out)
    out.chmod(0o644)
    pre_edit = out.read_bytes()
    before = _read_back(out, slot, who, items)

    app = QApplication.instance() or QApplication([])
    from editor.convert import Source
    from editor.roster import Party
    from editor.window import EditorBinding
    from wish.ui_window import Ui_WishWindow

    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    if slot:
        # `EditorBinding.load` asks a dialog which slot; hand it the answer.
        binding = EditorBinding(root)
        source = Source.detect(str(out), slot=slot)
        binding._adopt(Party(source), str(source.path))
    else:
        binding = EditorBinding(root, str(out))
    if binding.party is None:
        raise SystemExit(f"{out}: nothing opened")
    if not 0 <= who < len(binding.party.members):
        raise SystemExit(f"{out}: no roster row {who}; the party has "
                         f"{len(binding.party.members)} members")

    # `save()` flushes the widgets of the current row, so select it first.
    binding.roster.selectRow(who)
    binding._widgets["gold"].setValue(gold)
    binding._widgets["strength"].setValue(strength)
    inventory = binding.party.members[who].inventory
    for pos, qty in items.items():
        inventory.set_quantity(pos, qty)
    binding._edited()
    note = binding.save(interactive=False)
    app.processEvents()

    backups = sorted((out.parent / "backups").glob(out.name + ".*"))
    return {
        "base": str(base), "out": str(out), "who": who, "slot": slot,
        "save_said": note,
        "before": before,
        "after": _read_back(out, slot, who, items),
        "backups": [{"path": str(b), "sha256": sha256(b),
                     "equals_pre_edit": b.read_bytes() == pre_edit}
                    for b in backups],
        "sha256": {"base": sha256(base), "out": sha256(out)},
        "commit": _commit(),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True, type=pathlib.Path,
                    help="the save to copy and leave untouched")
    ap.add_argument("--out", required=True, type=pathlib.Path,
                    help="the copy to edit; its backups/ folder sits beside it")
    ap.add_argument("--slot", help="saved-game slot, for a disk holding several")
    ap.add_argument("--who", required=True, type=int,
                    help="zero-based roster row to edit")
    ap.add_argument("--gold", required=True, type=int)
    ap.add_argument("--strength", required=True, type=int)
    ap.add_argument("--item", action="append", required=True,
                    metavar="POSITION=QUANTITY",
                    help="inventory position and its new quantity; repeatable")
    ap.add_argument("--report", type=pathlib.Path,
                    help="also write the JSON report here")
    args = ap.parse_args(argv)

    items: dict[int, int] = {}
    for spec in args.item:
        pos, sep, qty = spec.partition("=")
        if not sep or not pos.isdigit() or not qty.isdigit():
            ap.error(f"--item wants POSITION=QUANTITY, got {spec!r}")
        items[int(pos)] = int(qty)

    report = drive(args.base, args.out, args.who, args.gold, args.strength,
                   items, args.slot)
    text = json.dumps(report, indent=2)
    if args.report:
        args.report.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
