#!/usr/bin/env python3
"""The specimen tree: DOS and C64 records this project watched being written.

`#249 (Build a DOS party from creation and level it ourselves, so DOS
measurements rest on records we watched being written)` and `#246 (Nothing
tells an engine-written DOS record from one edited with Gold Box Companion,
and conclusions already rest on edited ones)` are why this exists.  On
2026-09-04 a single record in Donald's own play directory -- edited with Gold
Box Companion, and he is the only one who knew -- refuted a correct belief,
stopped `#232 (An item-granted effect is dropped on the way through the
neutral record, with no report)`, and sent a `deep-research` agent after a
discriminator that does not exist.  `.claude/rules/testing.md`'s "A specimen
is only evidence if we know who wrote it" has the whole account; read it
before adding anything here.

**The tree lives outside the repository, at `$WISH_SPECIMENS` or
`~/wish-specimens` by default** -- the same shape as `$POR_DISKS` and
`automap.paths.find_disks()`, not a fourth way.  `work/` is gitignored and has
been lost twice; this is not that.  The game's data must never be committed,
so only this tool and its tests live in `tools/` and `tests/` -- the tree
itself is never in git.

Two protections, both his call, 2026-09-04: **read-only on disk**, so Wish or
an editor can open a specimen but not save over it, and **a SHA-256 manifest**
in each specimen's `provenance.toml`, so a deliberate edit -- one that leaves
the file readable and writable again first -- is still caught.  `check` is the
part that does the actual work, because it does not depend on anybody
remembering to look.

**A file with no `provenance.toml` covering it is not a specimen.**  Every
specimen answers, in that file: who made it and how, when, which title and
platform, what was done to it in the game, whether it has ever been opened in
an editor, and the hash of every file it holds.  `add` refuses to create one
without the required fields; `check` and `list` flag any file in the tree
that no `provenance.toml` accounts for.

Shape:

    $WISH_SPECIMENS/
      DO-NOT-EDIT.md
      por-c64/WISH-SPEC-<name>.d64
      por-c64/WISH-SPEC-<name>.provenance.toml
      por-dos/WISH-SPEC-<name>/<files...>
      por-dos/WISH-SPEC-<name>/provenance.toml

A C64 specimen is one disk image, so its provenance sits beside it as a sibling
file -- `WISH-SPEC-<name>.provenance.toml` rather than a bare `provenance.toml`,
since many specimens share one flat directory.  A DOS specimen is usually
several files (`.CHA`, `.SPC`, `.SAV`, `.ITM`), so it gets its own directory
and `provenance.toml` sits inside it, unambiguous.

    tools/specimens.py add dos gnomf1 \\
        work/issue84/run1/halfelf-GNOMF1.CHA work/issue84/run1/halfelf-GNOMF1.SPC \\
        --title "Pool of Radiance" --issue "#84 (...)" \\
        --made-by "tools/dosgnome.py, driven under DOSBox from character creation" \\
        --what "Rolled a gnome fighter in the game's own creation screens"
    tools/specimens.py check
    tools/specimens.py list

`add` only copies -- it never moves or deletes a source, and it never
overwrites an existing specimen.  If a specimen needs correcting, that is a
deliberate `chmod` and a new commit to `provenance.toml` by hand outside this
tool, not a silent re-add.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import os
import pathlib
import stat
import sys
import tomllib

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

PROVENANCE_NAME = "provenance.toml"
PLATFORMS = ("c64", "dos")

#: Required fields for a specimen to count as one at all -- see the module
#: docstring's "who made it and how ... and its hash".  `sha256` is added by
#: `add` itself and is not something a caller supplies.
REQUIRED_FIELDS = ("name", "platform", "title", "issue", "made_by", "what",
                    "created", "added", "edited_afterwards")


def tree_root() -> pathlib.Path:
    """`$WISH_SPECIMENS`, or `~/wish-specimens` -- `automap.paths`'s shape,
    not a fourth way."""
    env = os.environ.get("WISH_SPECIMENS")
    return pathlib.Path(env) if env else pathlib.Path.home() / "wish-specimens"


DO_NOT_EDIT = """\
# Do not edit anything in this directory

Every file under `wish-specimens/` is a game record an agent watched being
written -- from character creation, or from an action driven in the running
game and read back off disk before anything else touched it. That is what
makes it usable as evidence about the game rather than about somebody's
editing session.

**Opening one in Gold Box Companion, or in Wish's own character editor, and
saving costs the whole reason it is here** -- the file would look exactly like
a specimen while no longer being one, and nothing outside `provenance.toml`
would say so. `tools/specimens.py check` catches a changed file, but only if
somebody runs it.

If you want to look at what is here: `tools/specimens.py list` describes every
specimen without touching one.

If you played a character you want kept safe, save it somewhere else. This
tree exists so an agent never has to guess where a save came from.
"""


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _toml_str(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def write_provenance(path: pathlib.Path, fields: dict, sha256: dict[str, str]) -> None:
    """Hand-rolled rather than a library: the schema is flat strings, one
    bool, and one table of hashes, and nothing here should need a TOML
    writer's opinion about quoting a path."""
    lines = []
    for key in REQUIRED_FIELDS + ("command", "source", "issue_note"):
        if key not in fields:
            continue
        value = fields[key]
        if isinstance(value, bool):
            lines.append(f"{key} = {'true' if value else 'false'}")
        else:
            lines.append(f"{key} = {_toml_str(str(value))}")
    lines.append("")
    lines.append("[sha256]")
    for name in sorted(sha256):
        lines.append(f"{_toml_str(name)} = {_toml_str(sha256[name])}")
    lines.append("")
    path.write_text("\n".join(lines))


def read_provenance(path: pathlib.Path) -> dict:
    with path.open("rb") as f:
        return tomllib.load(f)


def make_read_only(path: pathlib.Path) -> None:
    """A file loses its write bits; a directory loses write *and* the
    ability to add or remove an entry -- 0o555, so `ls` still works but
    nothing can be dropped into or taken out of it."""
    if path.is_dir():
        for child in path.iterdir():
            if child.is_file():
                child.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        path.chmod(stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP
                   | stat.S_IROTH | stat.S_IXOTH)
    else:
        path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)


def _slug_ok(name: str) -> bool:
    return bool(name) and all(c.isalnum() or c in "-_" for c in name) and name == name.lower()


def add(platform: str, name: str, sources: list[pathlib.Path], *,
        title: str, issue: str, made_by: str, what: str,
        command: str | None = None, created: str | None = None,
        edited_afterwards: bool = False, root: pathlib.Path | None = None
        ) -> pathlib.Path:
    """Copy `sources` into the tree as one specimen and write its
    `provenance.toml`.  Refuses rather than overwriting: an existing
    specimen is not replaced, because replacing it silently is exactly the
    failure this tree exists to prevent.
    """
    if platform not in PLATFORMS:
        raise ValueError(f"platform must be one of {PLATFORMS}, got {platform!r}")
    if not _slug_ok(name):
        raise ValueError(f"name must be lowercase alnum/-/_, got {name!r}")
    sources = [pathlib.Path(s) for s in sources]
    for s in sources:
        if not s.is_file():
            raise ValueError(f"not a file: {s}")
    root = root or tree_root()
    today = datetime.date.today().isoformat()
    fields = {
        "name": name,
        "platform": platform,
        "title": title,
        "issue": issue,
        "made_by": made_by,
        "what": what,
        "created": created or today,
        "added": today,
        "edited_afterwards": edited_afterwards,
        "source": ", ".join(str(s) for s in sources),
    }
    if command:
        fields["command"] = command

    if platform == "c64":
        if len(sources) != 1:
            raise ValueError("a C64 specimen is one disk image")
        platform_dir = root / "por-c64"
        platform_dir.mkdir(parents=True, exist_ok=True)
        dest = platform_dir / f"WISH-SPEC-{name}{sources[0].suffix}"
        prov = platform_dir / f"WISH-SPEC-{name}.{PROVENANCE_NAME}"
        if dest.exists() or prov.exists():
            raise FileExistsError(f"specimen already exists: {dest}")
        dest.write_bytes(sources[0].read_bytes())
        sha256 = {dest.name: sha256_file(dest)}
        write_provenance(prov, fields, sha256)
        make_read_only(dest)
        make_read_only(prov)
        return dest
    else:
        specimen_dir = root / "por-dos" / f"WISH-SPEC-{name}"
        if specimen_dir.exists():
            raise FileExistsError(f"specimen already exists: {specimen_dir}")
        specimen_dir.mkdir(parents=True)
        sha256 = {}
        for s in sources:
            dest = specimen_dir / s.name
            dest.write_bytes(s.read_bytes())
            sha256[dest.name] = sha256_file(dest)
        prov = specimen_dir / PROVENANCE_NAME
        write_provenance(prov, fields, sha256)
        make_read_only(specimen_dir)
        return specimen_dir


def _specimen_dirs(root: pathlib.Path) -> list[pathlib.Path]:
    """Every directory holding a `provenance.toml`, C64's platform directory
    included -- its specimens are flat files there, not subdirectories."""
    out = []
    for platform_dir in ("por-c64", "por-dos"):
        pdir = root / platform_dir
        if not pdir.is_dir():
            continue
        if platform_dir == "por-c64":
            out.append(pdir)
        else:
            out += [d for d in sorted(pdir.iterdir()) if d.is_dir()]
    return out


def _c64_specimens(pdir: pathlib.Path) -> list[str]:
    """C64 specimen names, from `WISH-SPEC-<name>.provenance.toml`."""
    names = []
    for prov in sorted(pdir.glob(f"WISH-SPEC-*.{PROVENANCE_NAME}")):
        names.append(prov.name[len("WISH-SPEC-"):-len(f".{PROVENANCE_NAME}")])
    return names


def list_specimens(root: pathlib.Path | None = None) -> list[dict]:
    """One dict per specimen -- provenance fields plus `_files`, the paths
    checked and hashed against it."""
    root = root or tree_root()
    out = []
    for pdir in _specimen_dirs(root):
        if pdir.name == "por-c64":
            for name in _c64_specimens(pdir):
                prov_path = pdir / f"WISH-SPEC-{name}.{PROVENANCE_NAME}"
                fields = read_provenance(prov_path)
                fields["_files"] = [pdir / n for n in fields.get("sha256", {})]
                fields["_provenance"] = prov_path
                out.append(fields)
        else:
            prov_path = pdir / PROVENANCE_NAME
            if not prov_path.is_file():
                out.append({"name": pdir.name, "_no_provenance": True,
                             "_dir": pdir})
                continue
            fields = read_provenance(prov_path)
            fields["_files"] = [pdir / n for n in fields.get("sha256", {})]
            fields["_provenance"] = prov_path
            out.append(fields)
    return out


def check_specimens(root: pathlib.Path | None = None) -> list[str]:
    """Verify every specimen against its recorded SHA-256.  Returns one line
    per problem found; an empty list means every specimen matches its
    manifest and every file in the tree is accounted for by one.
    """
    root = root or tree_root()
    problems = []
    covered: set[pathlib.Path] = set()
    for entry in list_specimens(root):
        if entry.get("_no_provenance"):
            problems.append(f"{entry['_dir']}: no provenance.toml -- not a specimen")
            continue
        name = entry.get("name", "?")
        sha256 = entry.get("sha256", {})
        if not sha256:
            problems.append(f"{name}: provenance.toml records no files")
        base = entry["_provenance"].parent
        for fname, expected in sha256.items():
            path = base / fname
            covered.add(path)
            if not path.is_file():
                problems.append(f"{name}: {fname} is missing")
                continue
            actual = sha256_file(path)
            if actual != expected:
                problems.append(
                    f"{name}: {fname} has changed -- recorded {expected[:12]}, "
                    f"now {actual[:12]}")
        covered.add(entry["_provenance"])
        for field in REQUIRED_FIELDS:
            if field not in entry:
                problems.append(f"{name}: provenance.toml is missing '{field}'")
    for pdir in _specimen_dirs(root):
        glob = pdir.glob("*") if pdir.name == "por-c64" else pdir.rglob("*")
        for path in glob:
            if path.is_file() and path not in covered:
                problems.append(f"{path}: not recorded by any provenance.toml")
    return problems


def _format_row(entry: dict) -> str:
    if entry.get("_no_provenance"):
        return f"{entry['name']:<20} NO PROVENANCE -- not a specimen"
    edited = "EDITED" if entry.get("edited_afterwards") else "clean"
    return (f"{entry.get('name', '?'):<20} {entry.get('platform', '?'):<5} "
            f"{entry.get('title', '?'):<20} {edited:<7} "
            f"{len(entry.get('sha256', {})):>2} file(s)  {entry.get('issue', '')}")


def cmd_add(args: argparse.Namespace) -> int:
    ensure_tree()
    try:
        dest = add(args.platform, args.name, args.sources,
                   title=args.title, issue=args.issue, made_by=args.made_by,
                   what=args.what, command=args.command, created=args.created,
                   edited_afterwards=args.edited)
    except (ValueError, FileExistsError) as exc:
        print(f"refused: {exc}")
        return 1
    print(f"added {dest}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    entries = list_specimens()
    if not entries:
        print(f"no specimens under {tree_root()}")
        return 0
    for entry in entries:
        print(_format_row(entry))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    root = tree_root()
    if not root.is_dir():
        print(f"no specimen tree at {root}")
        return 0
    problems = check_specimens(root)
    if not problems:
        n = len(list_specimens(root))
        print(f"{n} specimen(s), all match their manifest")
        return 0
    for p in problems:
        print(p)
    return 1


def ensure_tree(root: pathlib.Path | None = None) -> pathlib.Path:
    root = root or tree_root()
    root.mkdir(parents=True, exist_ok=True)
    do_not_edit = root / "DO-NOT-EDIT.md"
    if not do_not_edit.exists():
        do_not_edit.write_text(DO_NOT_EDIT)
    return root


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="copy a save into the tree with its provenance")
    a.add_argument("platform", choices=PLATFORMS)
    a.add_argument("name", help="lowercase slug, e.g. gnomf1")
    a.add_argument("sources", nargs="+")
    a.add_argument("--title", required=True, help="e.g. \"Pool of Radiance\"")
    a.add_argument("--issue", required=True,
                   help="e.g. \"#84 (Roll a gnome in DOS ...)\"")
    a.add_argument("--made-by", required=True, dest="made_by",
                   help="who/what produced it -- the tool, or 'watched in the "
                        "running game'")
    a.add_argument("--what", required=True,
                   help="what was done to it in the game")
    a.add_argument("--command", default=None, help="the exact command run, if any")
    a.add_argument("--created", default=None, help="ISO date; defaults to today")
    a.add_argument("--edited", action="store_true",
                   help="has ever been opened in an editor afterwards")
    a.set_defaults(func=cmd_add)

    sub.add_parser("list", help="what is in the tree").set_defaults(func=cmd_list)
    sub.add_parser("check", help="verify every specimen's SHA-256"
                   ).set_defaults(func=cmd_check)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
