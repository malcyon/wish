#!/usr/bin/env python3
"""The exact bytes every registered `File ▸ Convert…` direction writes, hashed
per file, so two commits can be compared without an emulator.

`#52 (File ▸ Import and File ▸ Export for every direction the library
supports)`'s condition 5 -- every registered direction loaded and walked in
its emulator, from a save this dialog's own code path wrote -- was met on
2026-09-08 and nothing re-takes it when a writer changes.  A walk stays valid
exactly as long as the bytes it was taken on do, so the cheap check is to run
the same conversions in a detached worktree at the older commit and diff the
manifests:

    git worktree add -q --detach "$WT" <sha>
    ln -sfn "$PWD/work" "$WT/work"
    .venv/bin/python tools/convertbytes.py --tree "$WT" --out work/issue52/old.json
    .venv/bin/python tools/convertbytes.py --out work/issue52/new.json
    .venv/bin/python tools/convertbytes.py --diff work/issue52/old.json \
                                                  work/issue52/new.json

`--tree` puts another checkout's `goldbox/`, `editor/` and `tools/` in front
of this one on `sys.path`, so the *measuring* code is this file in both runs
and the *measured* code is each tree's own.

The conversions are `tools/convertdrops.py`'s: every specimen under
`$WISH_SPECIMENS` that `editor.convert.Source.detect` accepts, crossed
against `editor.convert.destinations_for`, rehearsed exactly as
`ConvertDialog._rehearse_and_report` rehearses -- the source title's own
combat-icon tables included.  Only `rehearse` is called; nothing is written
outside a temporary directory and no specimen is opened for writing.

**An Amiga destination is hashed by its contents, not by its image.**
`goldbox.amiga_adf.AmigaDisk.write_file` stamps wall-clock timestamps, so two
back-to-back builds of one input differ in about a dozen of 901,120 bytes
(`#36`, 2026-09-08).  Each file inside the built `POOLSAVE.ADF` is hashed
separately and the image itself is not.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import pathlib
import sys
import tempfile


def _load(tree: pathlib.Path | None):
    """Import the modules under test, out of `tree` when one is named."""
    root = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(tree.resolve() if tree else root))
    from editor import convert, dosimport
    from goldbox import c64_port, dos_codec
    from goldbox import portraits as portraits_mod
    from goldbox.d64 import load_payload
    from goldbox.iconparts import IconParts
    from tools import dosbox, gamedisks
    return dict(convert=convert, dosimport=dosimport, dos=dos_codec, games=c64_port,
                load_payload=load_payload, IconParts=IconParts,
                portraits=portraits_mod, dosbox=dosbox, gamedisks=gamedisks)


def specimen_root() -> pathlib.Path:
    return pathlib.Path(os.environ.get("WISH_SPECIMENS")
                        or pathlib.Path.home() / "wish-specimens")


DOS_DIRS = {
    "pool-of-radiance": "POOLRAD",
    "curse-of-the-azure-bonds": "CURSE",
    "secret-of-the-silver-blades": "SECRET",
}


def sources(root: pathlib.Path):
    """Every specimen path `editor.convert.Source.detect` accepts."""
    out = []
    for folder in sorted(root.glob("*-dos/WISH-SPEC-*")):
        if folder.is_dir():
            out.extend(sorted(folder.glob("SAVGAM?.DAT")))
    out.extend(sorted(root.glob("*-c64/WISH-SPEC-*.[dD]64")))
    out.extend(sorted(root.glob("*-amiga/WISH-SPEC-*/*.adf")))
    return out


def run(tree: pathlib.Path | None, dump: pathlib.Path | None = None,
        only: str | None = None, pick: str | None = None) -> dict:
    mod = _load(tree)
    convert, dosimport = mod["convert"], mod["dosimport"]
    dos_codec, c64_port = mod["dos"], mod["games"]
    from goldbox.amiga_adf import AmigaDisk

    cache: dict = {}

    def game_files(game):
        """`editor.window.EditorBinding.game_files_for`'s own search."""
        if game.key in cache:
            return cache[game.key]
        where = mod["gamedisks"].find(game.key)
        out = None
        if where is not None:
            icon = animate = None
            for disk in sorted(pathlib.Path(where).glob("*.[dD]64")):
                if icon is None:
                    try:
                        icon = mod["IconParts"].load(str(disk))
                    except Exception:
                        pass
                if animate is None:
                    try:
                        animate = mod["load_payload"](str(disk),
                                                      dos_codec.ANIMATE_FILE)
                    except Exception:
                        pass
            if icon is not None and animate is not None:
                portraits = None
                if game.key == c64_port.POOL_OF_RADIANCE.key:
                    try:
                        portraits = mod["portraits"].tables_from_disks(where)
                    except Exception:
                        portraits = None
                out = dosimport.GameFiles(icon=icon, animate=animate,
                                          portraits=portraits)
        cache[game.key] = out
        return out

    def ecl_disk(scratch: pathlib.Path):
        from tools import amigasaves
        for _label, data in amigasaves.images():
            try:
                AmigaDisk(bytearray(data)).read_file("/ecl.dax")
            except Exception:
                continue
            path = scratch / "amiga-disk-2.adf"
            path.write_bytes(data)
            return path
        return None

    def hashes(files: dict) -> dict:
        """`{name: sha256}`, an `.ADF` opened and hashed file by file."""
        out = {}
        for name, data in sorted(files.items()):
            if name.upper().endswith(".ADF"):
                disk = AmigaDisk(bytearray(data))
                for path, _entry in sorted(disk.walk()):
                    out[f"{name}!{path}"] = hashlib.sha256(
                        disk.read_file(path)).hexdigest()
                out[f"{name}!<size>"] = str(len(data))
            else:
                out[name] = hashlib.sha256(data).hexdigest()
        return out

    manifest: dict = {}
    failed: dict = collections.defaultdict(list)
    offered: dict = {}
    root = specimen_root()
    with tempfile.TemporaryDirectory(prefix="convertbytes-") as tmp:
        scratch = pathlib.Path(tmp)
        disk2 = ecl_disk(scratch)
        for path in sources(root):
            try:
                source = convert.Source.detect(path)
            except Exception as exc:
                failed["Source.detect"].append(f"{path.name}: {exc}")
                continue
            if pick and pick not in str(path):
                continue
            names = []
            for direction in convert.destinations_for(source):
                label = f"{type(direction).__name__} {direction.source_key}"
                names.append(label)
                if only and only != label:
                    continue
                if direction.destination_port == "c64":
                    slot = source.slot
                    options = game_files(direction.destination_game)
                elif direction.destination_port == "amiga":
                    slot, options = source.slot or "A", disk2
                else:
                    slot = "A"
                    stem = DOS_DIRS.get(direction.destination_game.key)
                    try:
                        options = mod["dosbox"].find_game(stem) if stem else None
                    except FileNotFoundError:
                        options = None
                if options is None or not slot:
                    failed[label].append(f"{path.name}: no game files")
                    continue
                try:
                    if (direction.source_port == "c64"
                            and direction.destination_port in ("dos", "amiga")):
                        files = game_files(direction.title)
                        try:
                            rehearsal = direction.rehearse(
                                source, slot, options,
                                icon_parts=files.icon if files else None)
                        except TypeError as exc:
                            # `icon_parts` reached `C64ToDos.rehearse` with
                            # #383 and `C64ToAmiga.rehearse` with #422; an
                            # older tree under `--tree` has neither, and its
                            # own dialog passed nothing either.
                            if "icon_parts" not in str(exc):
                                raise
                            rehearsal = direction.rehearse(source, slot,
                                                           options)
                    else:
                        rehearsal = direction.rehearse(source, slot, options)
                except Exception as exc:
                    failed[label].append(
                        f"{path.name}: {type(exc).__name__}: {exc}")
                    continue
                if dump is not None:
                    where = dump / label.replace(" ", "-") / path.name
                    where.mkdir(parents=True, exist_ok=True)
                    for name, data in rehearsal.files.items():
                        (where / name).write_bytes(data)
                        if name.upper().endswith(".ADF"):
                            inner = AmigaDisk(bytearray(data))
                            for ipath, _e in sorted(inner.walk()):
                                out = where / (name + ipath.replace("/", "_"))
                                out.write_bytes(inner.read_file(ipath))
                manifest.setdefault(label, {})[str(path)] = {
                    "files": hashes(rehearsal.files),
                    "dropped": sorted(rehearsal.report.dropped),
                }
            offered[str(path)] = sorted(names)
    return {"manifest": manifest, "failed": dict(failed), "offered": offered}


def diff(old: dict, new: dict) -> int:
    """Say, per direction, how many specimens' bytes moved and which."""
    o, n = old["manifest"], new["manifest"]
    print(f"{'direction':44} {'specimens':>9} {'same':>5} {'moved':>5} "
          f"{'only one side':>14}")
    worst = 0
    detail: list[str] = []
    for label in sorted(set(o) | set(n)):
        left, right = o.get(label, {}), n.get(label, {})
        both = sorted(set(left) & set(right))
        same = moved = 0
        for path in both:
            if left[path]["files"] == right[path]["files"]:
                same += 1
            else:
                moved += 1
                names = sorted(set(left[path]["files"])
                               | set(right[path]["files"]))
                changed = [x for x in names
                           if left[path]["files"].get(x)
                           != right[path]["files"].get(x)]
                detail.append(f"  {label}  {pathlib.Path(path).name}\n"
                              f"      {', '.join(changed)}")
        only = sorted(set(left) ^ set(right))
        worst = max(worst, moved)
        print(f"{label:44} {len(both):9} {same:5} {moved:5} {len(only):14}")
        for path in only:
            side = "old only" if path in left else "new only"
            detail.append(f"  {label}  {pathlib.Path(path).name}  ({side})")
    if detail:
        print("\nWhere they differ")
        print("\n".join(detail))
    ol, nl = old.get("offered", {}), new.get("offered", {})
    moved_offer = [p for p in sorted(set(ol) & set(nl)) if ol[p] != nl[p]]
    print(f"\nSpecimens offered a different set of directions: "
          f"{len(moved_offer)}")
    for p in moved_offer:
        print(f"  {pathlib.Path(p).name}: {ol[p]} -> {nl[p]}")
    for side, data in (("old", old), ("new", new)):
        if data.get("failed"):
            print(f"\nCould not run ({side})")
            for label in sorted(data["failed"]):
                for line in data["failed"][label][:6]:
                    print(f"  {label}  {line}")
    return 1 if worst else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tree", type=pathlib.Path,
                    help="a checkout to import goldbox/editor/tools from")
    ap.add_argument("--out", type=pathlib.Path, help="write the manifest here")
    ap.add_argument("--dump", type=pathlib.Path,
                    help="write every rehearsed file here, an .ADF's own "
                         "files beside it")
    ap.add_argument("--only", help="one direction label, as --diff prints it")
    ap.add_argument("--source", help="only specimens whose path holds this")
    ap.add_argument("--diff", nargs=2, type=pathlib.Path,
                    metavar=("OLD", "NEW"),
                    help="compare two manifests instead of taking one")
    args = ap.parse_args(argv)
    if args.diff:
        return diff(json.loads(args.diff[0].read_text()),
                    json.loads(args.diff[1].read_text()))
    out = run(args.tree, args.dump, args.only, args.source)
    text = json.dumps(out, indent=1, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
        ran = sum(len(v) for v in out["manifest"].values())
        print(f"{ran} conversions over {len(out['manifest'])} directions "
              f"-> {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
