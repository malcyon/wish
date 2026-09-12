#!/usr/bin/env python3
"""Stage one combat-figure row into a DOS party and convert it, to see what
arrives (`#335`).

A row of `tools/iconproposal.yaml` says which C64 option a DOS body or head
becomes.  Reading the row proves nothing about a *converted character*: the
table is merged from four levels, the merge takes a title and a size, and a
caller that forgets either gets the base answer and a complete, plausible
figure that is simply not the one the player made.  This drives the whole
path the import dialog drives -- `goldbox.dos_codec.convert_save`, which reads the
party and the place off the folder and calls `write_c64_save` -- and then
reads each C64 icon back into the menu choices that drew it, through
`IconParts.recognise`.

So the output is what the *game* would show, in the game's own vocabulary:
this character arrived as C64 small weapon 1, drawing arm, body, hair and
leg, and nothing of the weapon class.

    tools/iconrowproof.py --specimen ssb-299-engine-resave --slot D \\
        --title secret-of-the-silver-blades --body 11 --size small \\
        --stage work/issue335/staged-body11 --control

`--specimen` names a directory under the specimen tree
(`tools/specimens.py`), `--from` a save folder anywhere; either is **copied**
into `--stage` and only the copy is edited, because a specimen is evidence
and this rewrites a field.  `--body` and `--head` are the DOS `icon_body` and
`icon_head` to stage, and `--size small` or `--size large` picks which
characters get them -- editing an *input* and watching the program compute
from it, which is the valid half of the distinction
`.claude/rules/testing.md` draws.  With neither `--body` nor `--head` the
party is converted as it stands.

`--control` converts a second time with the title's own `overrides:` section
ignored, and prints both, so a row's effect is a difference rather than an
assertion.

`--home` reads each arriving C64 icon straight back into DOS through
`IconParts.dos_icon_from_c64` -- the other direction, `tools/iconreverse.yaml`
(`#320`) -- twice: once through `goldbox.iconparts.c64_icon_tables()` with no
title, the base table, and once with the title this run staged for, which is
what `goldbox.dos_codec.c64_party` itself now passes
(`#452 (A Silver Blades combat figure does not survive a round trip through
the C64, because the reverse table has no per-title rows)`).  Comparing the
two against what was staged shows the fix's effect, not a reading of either
table in isolation.

Nothing is written outside `--stage`, and that belongs under `work/`.  The
C64 art is read off the title's own disk at run time and none of it is
printed: the output is option numbers and part-class names.
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox import c64_port, c64_save, dos_codec, dos_port  # noqa: E402
from goldbox.iconparts import (  # noqa: E402
    PART_CLASSES,
    SPACE,
    IconParts,
    c64_icon_tables,
    dos_icon_tables,
)
from tools import iconproposal as ip  # noqa: E402

#: The three titles whose DOS-to-C64 conversion this can drive.  Pools of
#: Darkness has no C64 port at all, and its combat art is a different
#: encoding (`docs/168-dos-dax-and-combat-icons.md`).
TITLES = ("pool-of-radiance", "curse-of-the-azure-bonds",
          "secret-of-the-silver-blades")


def stage(source: pathlib.Path, into: pathlib.Path, slot: str, title: str,
          body: int | None, head: int | None, size: str | None) -> list[dict]:
    """Copy `source` into `into` and rewrite the named icon fields.

    Returns one row per character the copy holds, saying what was staged on
    it and what it held before.  The copy is writable even when the source
    is not: a specimen directory is read-only on purpose.
    """
    fields = dos_port.FIELDS_BY_NAME_FOR[title]
    into.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.iterdir()):
        if path.is_file() and path.name != "provenance.toml":
            shutil.copy(path, into / path.name)
            (into / path.name).chmod(0o644)
    #: The same walk `goldbox.dos_codec.read_party` makes -- `CHRDAT<slot><n>.SAV`
    #: for n in 1..6, skipping the ones that are not there -- so a party of
    #: fewer than six is edited on the file each character actually came
    #: from rather than on the nth existing one.
    rows = []
    for n in range(1, 7):
        path = into / f"CHRDAT{slot}{n}.SAV"
        if not path.exists():
            continue
        char = dos_codec.read_character(path)
        which = "small" if char.get("size") == 1 else "large"
        row = {"file": path.name, "name": char.name, "size": which,
               "was": (char.get("icon_head"), char.get("icon_body"))}
        if (size is None or size == which) and (body is not None
                                                or head is not None):
            raw = bytearray(path.read_bytes())
            for name, value in (("icon_head", head), ("icon_body", body)):
                if value is not None:
                    span = fields[name].span
                    raw[span] = bytes([value] * fields[name].size)
            path.write_bytes(bytes(raw))
            row["staged"] = True
        rows.append(row)
    return rows


def arrivals(folder: pathlib.Path, slot: str, title: str,
             parts: IconParts) -> tuple[list[dict], bytes, bytes | None]:
    """Convert the party and read each C64 icon back into menu choices.

    Returns the rows, and the `save0`/`save1` the conversion wrote --
    a real converted save, so :func:`homecoming` can read it back through
    `goldbox.dos_codec.c64_party` itself rather than through a reimplementation of
    what that function does.
    """
    game = c64_port.by_key(title)
    container = c64_save.container_for(game)
    save0 = bytearray(container.payload_size)
    save1 = (bytearray() if container.roster_in_payload
             else bytearray(container.game.roster_size))
    dos_codec.convert_save(folder, slot, save0, save1 or None, icon=parts, game=game)
    out = []
    party = dos_codec.read_party(folder, slot)
    for index, char in enumerate(party):
        place = dos_codec.marching_slot(index, len(party))
        at = container.icon(place)
        icon = bytes(save0[at:at + 36])
        choice = parts.recognise(icon[:18])
        out.append({
            "name": char.name,
            "size": "small" if char.get("size") == 1 else "large",
            "head": char.get("icon_head"), "body": char.get("icon_body"),
            "c64": f"{choice.weapon_size} weapon {choice.weapon}, "
                   f"{choice.head_size} head {choice.head}",
            "draws": sorted({PART_CLASSES[parts.part_class(g)]
                             for g in icon[:18] if g != SPACE}),
            "icon": icon,
        })
    return out, bytes(save0), (bytes(save1) if save1 else None)


def homecoming(rows: list[dict], save0: bytes, save1: bytes | None,
              title: str, parts: IconParts) -> list[dict]:
    """Read the just-converted save back into DOS two ways (`#320`, `#452`).

    **`goldbox.dos_codec.c64_party` itself**, the exact call a real C64-to-DOS
    conversion makes, against the same title this run staged for -- what
    this project calls "wired" below. And the base, title-less table read
    directly through `IconParts.dos_icon_from_c64`, which is what
    `c64_party` read for every title before #452 and is what a caller with
    no title to give still gets. A character whose staged `head`/`body`
    differs from the base reading is the round trip #452 was about; one
    whose staged pair still differs from the *wired* reading is a row that
    YAML file does not yet have.
    """
    game = c64_port.by_key(title)
    _chars, wired_icons = dos_codec.c64_party(save0, save1, game, icon_parts=parts)
    untitled = c64_icon_tables()
    out = []
    for row, wired in zip(rows, wired_icons):
        base = parts.dos_icon_from_c64(row["icon"], untitled)
        out.append({**row,
                    "today": (base.head, base.body),
                    "fixed": ((wired.head, wired.body)
                             if wired is not None else None)})
    return out


def report_home(rows: list[dict]) -> None:
    print("the round trip home:")
    for row in rows:
        staged = (row["head"], row["body"])
        print(f"    {row['name']:<14} {row['size']:<5} staged {staged}  "
              f"base table (no title) {str(row['today']):<10} "
              f"{'matches' if row['today'] == staged else 'differs'}  "
              f"through c64_party (wired) {str(row['fixed']):<10} "
              f"{'matches' if row['fixed'] == staged else 'differs'}")


def without_overrides(title: str, tmp: pathlib.Path) -> pathlib.Path:
    """A copy of the table with `overrides:` emptied, for `--control`.

    Written rather than patched in memory because `dos_icon_tables` reads
    the file itself, and the point of the control is that it goes through
    the same reader.
    """
    import yaml

    data = yaml.safe_load(ip.TABLE_PATH.read_text())
    data["overrides"] = {}
    path = tmp / "iconproposal-no-overrides.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def report(rows: list[dict], heading: str) -> None:
    print(heading)
    for row in rows:
        print(f"    {row['name']:<14} {row['size']:<5} head {row['head']:>2} "
              f"body {row['body']:>2}  ->  C64 {row['c64']:<34} "
              f"draws {', '.join(row['draws'])}")


def source_folder(specimen: str | None, given: str | None) -> pathlib.Path:
    """`--from`, or a specimen directory by name. Read, never written."""
    if given:
        return pathlib.Path(given).expanduser()
    if not specimen:
        raise SystemExit("pass --specimen or --from")
    from tools import specimens

    where = specimens.tree_root() / "por-dos" / f"WISH-SPEC-{specimen}"
    if not where.is_dir():
        raise SystemExit(f"no specimen at {where}; tools/specimens.py list")
    return where


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--title", default="secret-of-the-silver-blades",
                    choices=TITLES)
    ap.add_argument("--specimen", help="a WISH-SPEC- directory name, without "
                                       "the prefix")
    ap.add_argument("--from", dest="source", help="a DOS save folder instead")
    ap.add_argument("--slot", default="D", help="the DOS save slot letter")
    ap.add_argument("--stage", default="work/issue335/staged",
                    help="where to copy the party and edit it, under work/")
    ap.add_argument("--body", type=int, help="the DOS icon_body to stage")
    ap.add_argument("--head", type=int, help="the DOS icon_head to stage")
    ap.add_argument("--size", choices=("small", "large"),
                    help="stage only the characters of this size")
    ap.add_argument("--disk", help="the C64 side carrying SPELLE64, SPELLN64 "
                                   "and CHARPIC00")
    ap.add_argument("--control", action="store_true",
                    help="also convert with the title's overrides ignored")
    ap.add_argument("--home", action="store_true",
                    help="also read each arriving icon back into DOS, with "
                         "and without a title on the reverse table (#452)")
    args = ap.parse_args(argv)

    into = pathlib.Path(args.stage).expanduser()
    rows = stage(source_folder(args.specimen, args.source), into, args.slot,
                 args.title, args.body, args.head, args.size)
    for row in rows:
        if row.get("staged"):
            print(f"staged {row['name']} ({row['size']}): head/body "
                  f"{row['was'][0]}/{row['was'][1]} -> {args.head}/{args.body}")

    disk = ip.title_c64_disk(args.title, args.disk)
    if disk is None:
        raise SystemExit(f"no {c64_port.by_key(args.title).title} C64 disk here; "
                         f"pass --disk")
    parts = IconParts.load(str(disk))
    print(f"{into}  <-  {c64_port.by_key(args.title).title}, {disk.name}")
    arrived, save0, save1 = arrivals(into, args.slot, args.title, parts)
    report(arrived, "the table as it stands:")
    if args.home:
        report_home(homecoming(arrived, save0, save1, args.title, parts))
    if args.control:
        import goldbox.iconparts as iconparts

        was = iconparts.PROPOSAL_PATH
        try:
            iconparts.PROPOSAL_PATH = without_overrides(args.title, into)
            control_rows, _save0, _save1 = arrivals(
                into, args.slot, args.title, parts)
            report(control_rows,
                   "the control, with this title's overrides ignored:")
        finally:
            iconparts.PROPOSAL_PATH = was
    # `--size` picks which characters were staged; with none given, both were,
    # so both rows are the ones the run actually touched.
    sizes = (args.size,) if args.size else ("small", "large")
    if args.body is not None:
        for size in sizes:
            weapon = dos_icon_tables(title=args.title, size=size).weapons[
                args.body]
            print(f"row: DOS body {args.body} -> C64 {size} weapon "
                  f"{weapon} for {args.title}")
    if args.head is not None:
        for size in sizes:
            head = dos_icon_tables(title=args.title, size=size).heads[
                args.head]
            print(f"row: DOS head {args.head} -> C64 {size} head "
                  f"{head} for {args.title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
