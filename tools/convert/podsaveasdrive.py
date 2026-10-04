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
import pathlib
import subprocess
import sys

from editor import convert
from goldbox import amiga_adf

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
    for stale in out.glob("disk3-*.adf"):
        stale.unlink()
    outcome: dict = {"source": str(specimen), "to": "amiga"}
    report["save_as"] = outcome
    try:
        source = convert.Source.detect(specimen)
        rehearsal = convert.PodDosToAmiga().rehearse(
            source, source.slot, None, disk_three=amiga_adf.AmigaDisk.open(disk3),
            replace=replace)
    except (convert.ConvertError, ValueError, OSError) as exc:
        # ValueError covers the DOS save, DOS record and Amiga disk errors; OSError an unreadable file.
        outcome["stopped"] = [type(exc).__name__, str(exc)]
    else:
        image = out / f"disk3-{rehearsal.slot}.adf"
        image.write_bytes(rehearsal.disk)
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
