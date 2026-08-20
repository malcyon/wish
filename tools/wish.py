#!/usr/bin/env python3
"""wish-cli — read and edit Pool of Radiance (C64) save disks via YAML.

    wish-cli --export PORSAVE.D64 --output party.yaml
    vi party.yaml
    wish-cli --import party.yaml  --output PORSAVE-EDITED.D64

The mode flag carries the file being read; --output is what gets written.

An existing save disk is never modified. `import` always writes a **new** disk,
so a mistake costs nothing.

Only fields we understand are written back. Everything else — the party header,
everything in SAVEDGAME1 past its first page, and the majority of each character
record that is still unidentified — is carried through untouched.
"""
from __future__ import annotations

import argparse
import glob
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import yaml

from por.yaml_io import ValueError_, export_save, import_into, to_yaml

GAME_DISK_ENV = "POR_GAME_DISK"


def find_game_disk(explicit: str | None, save: str | None) -> str | None:
    """Locate a game disk, used only to turn item indices into names.

    Tried in order: the flag, $POR_GAME_DISK, then any POOL*.D64 sitting beside
    the save disk — which is how the disks are normally kept. Returns None if
    none is found; items are then listed without names rather than failing.
    """
    if explicit:
        return explicit
    env = os.environ.get(GAME_DISK_ENV)
    if env:
        return env
    if save:
        folder = pathlib.Path(save).resolve().parent
        for pattern in ("POOL1.D64", "POOL*.D64", "pool1.d64", "pool*.d64"):
            hits = sorted(glob.glob(str(folder / pattern)))
            if hits:
                return hits[0]
    return None


def cmd_export(args: argparse.Namespace) -> int:
    if not pathlib.Path(args.export).exists():
        print(f"no such save disk: {args.export}", file=sys.stderr)
        return 2
    game = find_game_disk(args.game_disk, args.export)
    data = export_save(args.export, game)
    out = args.output or str(pathlib.Path(args.export).with_suffix(".yaml"))
    pathlib.Path(out).write_text(to_yaml(data))
    print(f"exported {len(data['party'])} characters -> {out}")
    if game is None:
        print(f"  (no game disk found, so items are unnamed; pass --game-disk "
              f"or set ${GAME_DISK_ENV})")
    flagged = [e for e in data["party"] if e.get("_warnings")]
    for entry in flagged:
        print(f"  {entry['name']}: " + "; ".join(entry["_warnings"]))
    if flagged:
        print("  (the combat numbers are cached and go stale after an ability "
              "edit; details are in the YAML)")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    doc = pathlib.Path(args.import_file)
    if not doc.exists():
        print(f"no such YAML file: {doc}", file=sys.stderr)
        return 2
    data = yaml.safe_load(doc.read_text())

    # The YAML holds only the fields we understand; the original disk supplies
    # everything else, so one is always required.
    original = args.original_save or data.get("source_path")
    if not original:
        print("no original save given, and the YAML records none.\n"
              "  pass --original-save <disk.d64>", file=sys.stderr)
        return 2
    if not pathlib.Path(original).exists():
        print(f"original save not found: {original}\n"
              f"  pass --original-save <disk.d64> to point somewhere else",
              file=sys.stderr)
        return 2

    try:
        return _do_import(args, data, original)
    except ValueError_ as exc:
        print(exc, file=sys.stderr)
        return 2


def _do_import(args, data, original) -> int:
    # Only needed to turn item words into indices when building a new item.
    game = find_game_disk(args.game_disk, original)
    if args.dry_run:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".d64") as tmp:
            changes = import_into(original, data, tmp.name, game_disk=game)
    else:
        if pathlib.Path(args.output).resolve() == pathlib.Path(original).resolve():
            print("--output must differ from the original save; refusing to "
                  "overwrite it", file=sys.stderr)
            return 2
        changes = import_into(original, data, args.output, game_disk=game)

    print(f"based on {original}")
    if not changes:
        print("no changes")
    else:
        for c in changes:
            print(f"  {c}")
        print(f"\n{len(changes)} change(s)"
              + (" (dry run, nothing written)" if args.dry_run
                 else f" written to {args.output}"))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="wish-cli",
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)

    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--export", metavar="SAVE.D64",
                      help="read this save disk and write YAML")
    # `import` is a keyword, hence the explicit dest
    mode.add_argument("--import", dest="import_file", metavar="PARTY.YAML",
                      help="read this YAML and write a new save disk")

    ap.add_argument("--output", "-o", metavar="FILE",
                    help="with --export, the YAML to write (default: beside "
                         "the disk); with --import, the new save disk")
    ap.add_argument("--original-save", "-s", metavar="DISK.D64",
                    help="--import only: the disk to build on; defaults to the "
                         "one recorded in the YAML when it was exported")
    ap.add_argument("--game-disk", metavar="POOL1.D64",
                    help=f"a game disk. With --export it names items and "
                         f"describes their type; with --import it is needed "
                         f"only to turn item words into indices when you build "
                         f"a new item. Otherwise ${GAME_DISK_ENV} or a "
                         f"POOL*.D64 beside the save")
    ap.add_argument("--dry-run", "-n", action="store_true",
                    help="--import only: report the changes without writing")

    args = ap.parse_args()
    if args.export:
        for attr, flag in (("original_save", "--original-save"),
                           ("dry_run", "--dry-run")):
            if getattr(args, attr):
                ap.error(f"{flag} only applies to --import")
        return cmd_export(args)

    if not args.dry_run and not args.output:
        ap.error("--import needs --output (or --dry-run to just see the changes)")
    return cmd_import(args)


if __name__ == "__main__":
    raise SystemExit(main())
