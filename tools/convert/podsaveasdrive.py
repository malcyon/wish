#!/usr/bin/env python3
"""Save As a Pools of Darkness slot through the editor's own route, and write the report and any disk 3 image.

The slot is opened and published by `tools.convert.saveasdrive.save_as`, so the bytes are what
`saveplan.prepare_save_as` produces for the Character Editor's Save As. `--set` and `--item`
change a member the way the sheet does before that. An Amiga destination is written to `--out`
as `disk3-<slot>.adf` under a name this tool chooses; nothing registered is written. A DOS
destination is the Save As folder under `--out`. The report is the one
`tools.amiga.acceptance.prepare_published_disk_three` reads, and `commit.txt` beside it holds
`git rev-parse HEAD` and `git status --porcelain` so the run can be tied to a tree.

    .venv/bin/python -m tools.convert.podsaveasdrive --specimen DIR/SAVGAMD.PTY \\
        --disk3 pod-disk3.adf --out OUT [--to amiga|dos] [--slot L] \\
        [--set 0:strength=18] [--item 0:2=5]

`MEMBER` is a zero-based roster row, `FIELD` a sheet field and `POS` an inventory position.
Runs offscreen and needs no emulator.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import traceback

from editor import convert
from goldbox import amiga_adf, amiga_savegame, dos_codec, dos_savegame

REPORT_NAME = "saveas-report.json"
COMMIT_NAME = "commit.txt"


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def commit_text(tree: pathlib.Path) -> str:
    """`git rev-parse HEAD` and `git status --porcelain` for `tree`, as the text of `commit.txt`."""
    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(tree), *args], check=True,
                              capture_output=True, text=True).stdout
    return f"{git('rev-parse', 'HEAD').strip()}\n{git('status', '--porcelain')}"


class ImageNotWritable(Exception):
    """The image's path is an input or a directory, so writing it would clobber or fail."""


def _write_image(image: pathlib.Path, data: bytes, inputs: tuple[pathlib.Path, ...]) -> None:
    """Write `data` to `image` through a temp file and `os.replace`, which swaps a link itself, not its target."""
    if image.resolve() in inputs:
        raise ImageNotWritable(f"{image} is one of the run's inputs")
    if image.is_dir() and not image.is_symlink():
        raise ImageNotWritable(f"{image} is a directory")
    fd, temp = tempfile.mkstemp(dir=image.parent, prefix=".disk3-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(temp, image)
    except BaseException:
        pathlib.Path(temp).unlink(missing_ok=True)
        raise


#: Errors the readers and writers raise for a save or disk they cannot take.
KNOWN_ERRORS = (convert.ConvertError, ImageNotWritable, dos_savegame.DosSaveError, dos_codec.DosRecordError,
                amiga_adf.AmigaDiskError, amiga_savegame.AmigaSaveError)

def _parse_edit(text: str, flag: str) -> tuple[int, str, int | str]:
    """`MEMBER:KEY=VALUE` as (member, key, value); a number stays a number."""
    try:
        head, value = text.split("=", 1)
        member, key = head.split(":", 1)
        return int(member), key, int(value) if value.lstrip("-").isdigit() else value
    except ValueError:
        raise ValueError(f"{flag} wants MEMBER:KEY=VALUE, got {text!r}") from None


def _edits(sets: tuple[str, ...], items: tuple[str, ...]):
    """The `edits` callback of `saveasdrive.save_as` for `--set` and `--item` values."""
    parsed = ([(m, k, v, False) for m, k, v in (_parse_edit(t, "--set") for t in sets)]
              + [(m, k, v, True) for m, k, v in (_parse_edit(t, "--item") for t in items)])

    def apply(party) -> None:
        for member, key, value, is_item in parsed:
            if not 0 <= member < len(party.members):
                raise convert.ConvertError(
                    f"no roster row {member}; the party has {len(party.members)} members")
            row = party.members[member]
            if is_item:
                row.inventory.set_quantity(int(key), int(value))
            else:
                row.record.set(key, value)
    return apply


@contextlib.contextmanager
def _pod_flag():
    """`WISH_EXPERIMENTAL_POD_CONVERT` on for the run, as the editor needs it to open this title."""
    before = os.environ.get(convert.POD_CONVERT_ENV)
    os.environ[convert.POD_CONVERT_ENV] = "1"
    try:
        yield
    finally:
        if before is None:
            os.environ.pop(convert.POD_CONVERT_ENV, None)
        else:
            os.environ[convert.POD_CONVERT_ENV] = before


def _save_as(specimen: pathlib.Path, disk3: pathlib.Path | None, folder: pathlib.Path, to: str,
             slot: str | None, edits) -> dict:
    """`saveasdrive.save_as` through an `EditorBinding`, which finds the game data as the editor does."""
    from PyQt6.QtWidgets import QApplication, QWidget

    from editor.window import EditorBinding
    from tools.convert import saveasdrive

    app = QApplication.instance() or QApplication([])  # noqa: F841
    window = EditorBinding(QWidget())
    try:
        return saveasdrive.save_as(window, specimen, to, folder, amiga_disk_three=disk3,
                                   source_slot=slot, edits=edits)
    finally:
        window.close()


def run(specimen: pathlib.Path, disk3: pathlib.Path | None, out: pathlib.Path,
        tree: pathlib.Path | None = None, *, to: str = "amiga", slot: str | None = None,
        sets: tuple[str, ...] = (), items: tuple[str, ...] = ()) -> dict:
    """Save As `specimen` to `to`, write the image or folder and the report into `out`, and return the report.

    A Save As that cannot be made leaves `save_as["stopped"]` set and writes nothing else.
    """
    specimen = pathlib.Path(specimen).resolve()
    disk3 = pathlib.Path(disk3).resolve() if disk3 else None
    out = pathlib.Path(out).resolve()
    report: dict = {"specimen": str(specimen), "specimen_sha256": _sha256(specimen),
                    "amiga_disk3": str(disk3) if disk3 else None, "written": [],
                    "written_sha256": {}, "dropped": [], "losses": [], "warnings": []}
    out.mkdir(parents=True, exist_ok=True)
    # The folder is this tool's own output: an image from an earlier run must not pass for this one's.
    # Never an input that happens to sit in `out` under such a name, a link, or a directory.
    for stale in out.glob("disk3-*.adf"):
        if (stale.is_file() and not stale.is_symlink()
                and stale.resolve() not in (specimen, disk3)):
            stale.unlink()
    outcome: dict = {"source": str(specimen), "to": to}
    report["save_as"] = outcome
    try:
        if to not in ("amiga", "dos"):
            raise convert.ConvertError(f"--to is amiga or dos, not {to!r}")
        if to == "amiga" and disk3 is None:
            raise convert.ConvertError("an Amiga destination needs --disk3")
        edits = _edits(tuple(sets), tuple(items)) if sets or items else None
        with _pod_flag(), tempfile.TemporaryDirectory(prefix="podsaveas-") as scratch:
            # An image is published under the temp folder and copied to `out` by the tool's
            # own rules; a DOS folder is published in `out` and stays there.
            folder = pathlib.Path(scratch) if to == "amiga" else out
            result = _save_as(specimen, disk3, folder, to, slot, edits)
            if result.get("stopped"):
                outcome["stopped"] = result["stopped"]
            elif to == "amiga":
                published = pathlib.Path(result["written"][0])
                image = out / f"disk3-{result['slot']}.adf"
                _write_image(image, published.read_bytes(), (specimen, disk3))
                written = [image]
            else:
                written = [pathlib.Path(p) for p in result["written"]]
    except (convert.ConvertError, ImageNotWritable, ValueError, OSError) as exc:
        if not isinstance(exc, KNOWN_ERRORS):
            # An unnamed ValueError or OSError may be a bug, so keep its traceback.
            traceback.print_exc()
        outcome["stopped"] = [type(exc).__name__, str(exc)]
    else:
        if not outcome.get("stopped"):
            for key in ("dropped", "losses", "warnings"):
                report[key] = [str(x) for x in result.get(key, [])]
            report["written"] = [str(p) for p in written]
            report["written_sha256"] = {p.name: _sha256(p) for p in written}
            outcome.update(slot=result["slot"], destination=(
                str(written[0]) if to == "amiga" else result["destination"]),
                written=report["written"], dropped=report["dropped"],
                losses=report["losses"], warnings=report["warnings"])
    (out / REPORT_NAME).write_text(json.dumps(report, indent=2) + "\n")
    tree = tree or pathlib.Path(__file__).resolve().parents[2]
    (out / COMMIT_NAME).write_text(commit_text(tree))
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--specimen", required=True, type=pathlib.Path,
                    help="a DOS SAVGAM<letter>.PTY, or an Amiga disk 3 image with --slot")
    ap.add_argument("--disk3", type=pathlib.Path, default=None,
                    help="the registered Amiga Pools of Darkness disk 3; read, never written")
    ap.add_argument("--out", required=True, type=pathlib.Path,
                    help="folder for the image, saveas-report.json and commit.txt")
    ap.add_argument("--to", choices=("amiga", "dos"), default="amiga")
    ap.add_argument("--slot", default=None, help="the saved game letter of an Amiga disk source")
    ap.add_argument("--set", dest="sets", action="append", default=[], metavar="MEMBER:FIELD=VALUE",
                    help="change a sheet field of a member before Save As; repeatable")
    ap.add_argument("--item", dest="items", action="append", default=[], metavar="MEMBER:POS=QTY",
                    help="change an item quantity of a member before Save As; repeatable")
    args = ap.parse_args(argv)
    inputs = [("specimen", args.specimen)]
    if args.disk3 is not None:
        inputs.append(("disk 3", args.disk3))
    for label, path in inputs:
        if not path.is_file():
            ap.error(f"no such {label}: {path}")
    if args.to == "amiga" and args.disk3 is None:
        ap.error("--to amiga needs --disk3")
    report = run(args.specimen, args.disk3, args.out, to=args.to, slot=args.slot,
                 sets=tuple(args.sets), items=tuple(args.items))
    print(json.dumps(report, indent=2))
    return 1 if "stopped" in report["save_as"] else 0


if __name__ == "__main__":
    sys.exit(main())
