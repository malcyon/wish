#!/usr/bin/env python3
"""Rehearse a DOS Pools of Darkness slot onto the player's Amiga disk 3 and write the disk and a report.

The disk is `editor.convert.PodDosToAmiga().rehearse`'s own image, written to `--out` under a
name this tool chooses; nothing registered is written. The report is the one
`tools.amiga.acceptance.prepare_published_disk_three` reads, and `commit.txt` beside it holds
`git rev-parse HEAD` and `git status --porcelain` so the run can be tied to a tree.

    .venv/bin/python -m tools.convert.podsaveasdrive --specimen DIR/SAVGAMD.PTY \\
        --disk3 pod-disk3.adf --out OUT

Runs offscreen and needs no emulator.
"""
from __future__ import annotations

import argparse
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

def run(specimen: pathlib.Path, disk3: pathlib.Path, out: pathlib.Path,
        replace: bool = False, tree: pathlib.Path | None = None) -> dict:
    """Write the rehearsed disk 3 and the report into `out`, and return the report.

    A rehearsal that cannot be made leaves `save_as["stopped"]` set and writes no image.
    """
    specimen = pathlib.Path(specimen).resolve()
    disk3 = pathlib.Path(disk3).resolve()
    out = pathlib.Path(out).resolve()
    report: dict = {"specimen": str(specimen), "specimen_sha256": _sha256(specimen),
                    "amiga_disk3": str(disk3), "written": [], "written_sha256": {},
                    "dropped": [], "losses": [], "warnings": []}
    out.mkdir(parents=True, exist_ok=True)
    # The folder is this tool's own output: an image from an earlier run must not pass for this one's.
    # Never an input that happens to sit in `out` under such a name, a link, or a directory.
    for stale in out.glob("disk3-*.adf"):
        if (stale.is_file() and not stale.is_symlink()
                and stale.resolve() not in (specimen, disk3)):
            stale.unlink()
    outcome: dict = {"source": str(specimen), "to": "amiga"}
    report["save_as"] = outcome
    try:
        source = convert.Source.detect(specimen)
        rehearsal = convert.PodDosToAmiga().rehearse(
            source, source.slot, None, disk_three=amiga_adf.AmigaDisk.open(disk3),
            replace=replace)
        image = out / f"disk3-{rehearsal.slot}.adf"
        _write_image(image, rehearsal.disk, (specimen, disk3))
    except (convert.ConvertError, ImageNotWritable, ValueError, OSError) as exc:
        if not isinstance(exc, KNOWN_ERRORS):
            # An unnamed ValueError or OSError may be a bug, so keep its traceback.
            traceback.print_exc()
        outcome["stopped"] = [type(exc).__name__, str(exc)]
    else:
        report["dropped"] = [str(x) for x in rehearsal.report.dropped]
        report["losses"] = [str(x) for x in rehearsal.report.losses]
        report["warnings"] = [str(x) for x in rehearsal.report.warnings]
        report["written"] = [str(image)]
        report["written_sha256"] = {image.name: _sha256(image)}
        outcome.update(slot=rehearsal.slot, destination=str(image),
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
                    help="the DOS SAVGAM<letter>.PTY of the slot to convert")
    ap.add_argument("--disk3", required=True, type=pathlib.Path,
                    help="the registered Amiga Pools of Darkness disk 3; read, never written")
    ap.add_argument("--out", required=True, type=pathlib.Path,
                    help="folder for the image, saveas-report.json and commit.txt")
    ap.add_argument("--replace", action="store_true",
                    help="replace the slot when disk 3 already holds that letter")
    args = ap.parse_args(argv)
    for label, path in (("specimen", args.specimen), ("disk 3", args.disk3)):
        if not path.is_file():
            ap.error(f"no such {label}: {path}")
    report = run(args.specimen, args.disk3, args.out, replace=args.replace)
    print(json.dumps(report, indent=2))
    return 1 if "stopped" in report["save_as"] else 0


if __name__ == "__main__":
    sys.exit(main())
