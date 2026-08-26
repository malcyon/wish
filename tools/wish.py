"""`wish export` and `wish import` — read and edit Gold Box save disks via YAML.

    wish export PORSAVE.D64 -o party.yaml
    vi party.yaml
    wish import party.yaml  -o PORSAVE-EDITED.D64

The subcommand names the direction; `-o` is what gets written.

An existing save disk is never modified. `import` always writes a **new** disk,
so a mistake costs nothing.

Only fields we understand are written back. Everything else — the party header,
everything in SAVEDGAME1 past its first page, and the majority of each character
record that is still unidentified — is carried through untouched.

This module is no longer a program of its own. `wish/__main__.py` dispatches on
the first argument and calls `subcommand()`; see docs/129-one-binary.md.
"""
from __future__ import annotations

import argparse
import glob
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import yaml

from automap.paths import disk_globs
from goldbox.d64 import D64
from goldbox.games import detect
from goldbox.yaml_io import ValueError_, export_save, import_into, to_yaml

GAME_DISK_ENV = "POR_GAME_DISK"


def find_game_disk(explicit: str | None, save: str | None) -> str | None:
    """Locate a game disk, used only to turn item indices into names.

    Tried in order: the flag, $POR_GAME_DISK, then a game disk of the save's
    own title sitting beside it — `POOL*.D64` for Pool of Radiance, `CURSE*.D64`
    for Curse — which is how the disks are normally kept. Returns None if none
    is found; items are then listed without names rather than failing.
    """
    if explicit:
        return explicit
    env = os.environ.get(GAME_DISK_ENV)
    if env:
        return env
    if save:
        folder = pathlib.Path(save).resolve().parent
        # An undetectable disk falls back to Pool of Radiance, which is what
        # `disk_globs(None)` means and what this has always assumed.
        for pattern in disk_globs(game_of(save)):
            hits = sorted(glob.glob(str(folder / pattern)))
            if hits:
                return hits[0]
    return None


def game_of(save: str):
    """The title this save disk belongs to, or None if it cannot be told."""
    try:
        return detect(D64.open(save))
    except Exception:
        return None


def cmd_export(args: argparse.Namespace) -> int:
    if not pathlib.Path(args.save).exists():
        print(f"no such save disk: {args.save}", file=sys.stderr)
        return 2
    game = find_game_disk(args.game_disk, args.save)
    data = export_save(args.save, game)
    out = args.output or str(pathlib.Path(args.save).with_suffix(".yaml"))
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


#: `--game-disk` is worth the same sentence in both subcommands, and it drifted
#: between them once already.
_GAME_DISK = (f"a game disk, for item names. Otherwise ${GAME_DISK_ENV} or one "
              "of the title's own disks beside the save")


def _export_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="wish export",
        description="Read a save disk and write the party as YAML.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("save", metavar="SAVE.D64", help="the save disk to read")
    ap.add_argument("--output", "-o", metavar="FILE",
                    help="the YAML to write (default: beside the disk)")
    ap.add_argument("--game-disk", metavar="POOL1.D64",
                    help=f"{_GAME_DISK}. It names items and describes their "
                         f"type; without one items are listed unnamed")
    return ap


def _import_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="wish import",
        description="Read an edited YAML and write a NEW save disk. The "
                    "original is never modified.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("import_file", metavar="PARTY.YAML",
                    help="the YAML to read")
    ap.add_argument("--output", "-o", metavar="NEW.D64",
                    help="the new save disk to write")
    ap.add_argument("--original-save", "-s", metavar="DISK.D64",
                    help="the disk to build on; defaults to the one recorded "
                         "in the YAML when it was exported")
    ap.add_argument("--game-disk", metavar="POOL1.D64",
                    help=f"{_GAME_DISK}. Needed only to turn item words into "
                         f"indices when you build a new item")
    ap.add_argument("--dry-run", "-n", action="store_true",
                    help="report the changes without writing anything")
    return ap


def subcommand(name: str, argv: list[str]) -> int:
    """Run `wish export` or `wish import`; *name* says which.

    Called from `wish/__main__.py`, which owns the decision that the first
    argument is a subcommand at all. There is no `--version` here: the one
    binary has one version and `wish --version` prints it.
    """
    if name == "export":
        return cmd_export(_export_parser().parse_args(argv))
    ap = _import_parser()
    args = ap.parse_args(argv)
    if not args.dry_run and not args.output:
        ap.error("import needs -o/--output (or --dry-run to just see the "
                 "changes)")
    return cmd_import(args)
