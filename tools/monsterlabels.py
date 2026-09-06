#!/usr/bin/env python3
"""The combat map's monster labels: a table Donald edits, a draft to start
him off, and a document to read it by.

`#345` puts a letter above each combatant's health bar. A party member's is
the first letter of its name; a monster's is **at most two characters,
chosen by hand** -- Donald, 2026-09-06: *"A '7TH LVL DW FIGHTER' could be
'DF'. I could just review all these and we can make sure they are limited to
two characters."* No rule produces `DF` from that name, so the labels are a
table rather than a function, and every one of them is his.

The table is `tools/monsterlabels.yaml`, beside this file, in the shape
`tools/iconproposal.yaml` already has: one row per monster name, its label,
and a comment saying which titles carry it and what its record says it is.
Our judgement rather than the game's data, so it is committed.

    tools/monsterlabels.py                       # the report, to the terminal
    tools/monsterlabels.py --propose             # add a draft row for every name the YAML lacks
    tools/monsterlabels.py --markdown work/345/monster-labels.md

**`--propose` writes a first guess so he is correcting rather than starting
from nothing.** The guess is the first letter of each word, skipping ordinals,
numbers and `LVL`, and keeping the first and last when more than two remain
-- which gives `DF` for `7TH LVL DW FIGHTER` and `GL` for `GOBLIN LEADER`,
and is still a guess. Rows already in the file are never rewritten; new ones
are appended under a dated heading, so his edits and the draft's stay
distinguishable.

**`--markdown` is the form he reads down**, one table per title with every
monster on that title's disks, its files, its hit dice, its label, and which
other names share the label -- collisions are fine, he said, but a reader
should be able to see them. Regenerated from the YAML every time; the
document is never the thing edited.

The names come off the three C64 titles' `MON*` files, found through
`gamedisks.toml` the way every other tool finds them, and read at run time:
nothing of the game's is written anywhere. A title whose disks are not on the
machine is reported as missing and its rows in the YAML are kept.
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import datetime
import pathlib
import sys

import yaml

TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS.parent))
sys.path.insert(0, str(TOOLS))

import gamedisks  # noqa: E402

from goldbox.d64 import D64, split_load_address  # noqa: E402
from goldbox.layout import RECORD_SIZE  # noqa: E402
from goldbox.record import CharacterRecord  # noqa: E402

TABLE_PATH = TOOLS / "monsterlabels.yaml"

#: `gamedisks.toml` entry -> the short name the YAML comments use.
TITLES = (
    ("pool-of-radiance", "Pool"),
    ("curse-of-the-azure-bonds", "Curse"),
    ("secret-of-the-silver-blades", "Silver Blades"),
)

#: The most a label may be. Donald's number.
MOST = 2

#: Words the draft skips: a level marker and a number are not the monster.
SKIP = {"LVL", "LEVEL", "OF", "THE"}


@dataclasses.dataclass
class Monster:
    name: str
    titles: dict[str, list[str]]     # short title -> the MON files carrying it
    hit_dice: int | None = None


def _ordinal_or_number(word: str) -> bool:
    return word[:1].isdigit()


def draft(name: str) -> str:
    """A first guess at a label, for a row that has none yet."""
    words = [w for w in name.split() if w not in SKIP
             and not _ordinal_or_number(w)]
    if not words:
        words = name.split()
    if len(words) == 1 and 1 < len(words[0]) <= MOST:
        return words[0]
    letters = [w[0] for w in words if w[0].isalpha()] or [name[0]]
    if len(letters) > MOST:
        letters = [letters[0], letters[-1]]
    return "".join(letters)


def read_disks() -> tuple[dict[str, Monster], list[str]]:
    """Every distinct monster name on the three titles' disks, and the titles
    whose disks were not found."""
    monsters: dict[str, Monster] = {}
    missing = []
    for entry, short in TITLES:
        folder = gamedisks.find(entry)
        if folder is None:
            missing.append(short)
            continue
        globs = gamedisks.entry(entry).get(gamedisks.GLOB, [])
        disks = sorted({p for g in globs for p in folder.glob(g)})
        seen_files: set[str] = set()
        for disk in disks:
            img = D64.open(str(disk))
            for e in img.directory():
                filename = bytes(e.name).decode("latin-1")
                if not filename.startswith("MON") or not e.is_prg:
                    continue
                if filename in seen_files:
                    continue
                seen_files.add(filename)
                _, body = split_load_address(img.read_file(e))
                name = body[:20].split(b"\0")[0].decode("latin-1").strip()
                if not name:
                    continue
                m = monsters.setdefault(name, Monster(name, {}))
                m.titles.setdefault(short, []).append(filename)
                if m.hit_dice is None:
                    try:
                        record = CharacterRecord(
                            body + bytes(max(0, RECORD_SIZE - len(body))),
                            stored_size=len(body))
                        m.hit_dice = int(record.get("level"))
                    except Exception:
                        m.hit_dice = None
    return monsters, missing


def load_table(path: pathlib.Path = TABLE_PATH) -> dict[str, str]:
    """`name -> label`, as the YAML has it. Empty when there is no file."""
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    labels = data.get("labels") or {}
    return {str(k): str(v) for k, v in labels.items()}


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def row(m: Monster, label: str) -> str:
    where = ", ".join(f"{t} x{len(files)}" if len(files) > 1 else t
                      for t, files in m.titles.items())
    dice = "" if m.hit_dice is None else f"; {m.hit_dice} hit dice"
    key = _quote(m.name) + ":"
    return f"  {key:<24} {_quote(label):<6} # {where}{dice}"


HEADER = """\
# The combat map's monster labels for #345 (Draw a letter in each
# combat-map square saying what is standing there, instead of the index the
# backend counts with).
#
# One row per monster name as its MON* record spells it, and the label drawn
# above its health bar on the combat map: at most two characters, chosen by
# hand, because no rule turns `7TH LVL DW FIGHTER` into `DF`. Collisions are
# fine -- ORC and OGRE may both be `O`. The comment says which C64 titles
# carry the name (and in how many MON files) and the hit dice its record
# states.
#
# This is the single source: edit the labels here, never in the generated
# document. `tools/monsterlabels.py --propose` appends a draft row for any
# name on the disks that has none; `--markdown` writes the document to read
# them by. Both keys and labels are quoted, because a label like `ON` or `N`
# is a boolean to YAML unquoted.

labels:
"""


def propose(monsters: dict[str, Monster], path: pathlib.Path = TABLE_PATH
            ) -> list[str]:
    """Append a draft row for every name the table lacks; returns them."""
    have = load_table(path)
    new = [m for name, m in sorted(monsters.items()) if name not in have]
    if not new:
        return []
    lines = []
    if not path.is_file():
        lines.append(HEADER.rstrip("\n"))
    stamp = datetime.date.today().isoformat()
    lines.append(f"\n  # Drafted {stamp} by tools/monsterlabels.py --propose; "
                 f"every label below is a guess to correct.")
    for m in new:
        lines.append(row(m, draft(m.name)))
    with path.open("a") as f:
        f.write("\n".join(lines) + "\n")
    return [m.name for m in new]


def report(monsters: dict[str, Monster], labels: dict[str, str],
           missing: list[str]) -> list[str]:
    """The plain-text report: per title, then what is wrong."""
    out = []
    for _, short in TITLES:
        here = {n: m for n, m in monsters.items() if short in m.titles}
        if short in missing:
            out.append(f"{short}: disks not found")
            continue
        files = sum(len(m.titles[short]) for m in here.values())
        by_label = collections.defaultdict(list)
        for n in here:
            by_label[labels.get(n, "")].append(n)
        shared = {lab: sorted(ns) for lab, ns in by_label.items()
                  if lab and len(ns) > 1}
        out.append(f"{short}: {files} MON files, {len(here)} distinct names, "
                   f"{len(by_label) - ('' in by_label)} distinct labels, "
                   f"{len(shared)} shared by more than one name")
        for lab, ns in sorted(shared.items()):
            out.append(f"    {lab:<3} {', '.join(ns)}")
    unlabelled = sorted(n for n in monsters if n not in labels)
    if unlabelled:
        out.append(f"{len(unlabelled)} names on the disks with no row in "
                   f"{TABLE_PATH.name}: " + ", ".join(unlabelled))
    orphans = sorted(n for n in labels if n not in monsters and not missing)
    if orphans:
        out.append(f"{len(orphans)} rows naming no monster on any disk: "
                   + ", ".join(orphans))
    long = sorted((n, lab) for n, lab in labels.items() if len(lab) > MOST)
    if long:
        out.append(f"{len(long)} labels longer than {MOST} characters: "
                   + ", ".join(f"{n} -> {lab}" for n, lab in long))
    return out


def markdown(monsters: dict[str, Monster], labels: dict[str, str],
             missing: list[str], out: pathlib.Path) -> None:
    lines = [
        "# Monster labels for the combat map",
        "",
        "One row per monster name on the C64 disks, with the label drawn "
        "above its health bar on the combat map. **Edit "
        "`tools/monsterlabels.yaml`** and run "
        f"`tools/monsterlabels.py --markdown {out}` to redraw this; the "
        "labels here are whatever the YAML says, and a blank one is a name "
        "with no row yet. At most two characters each. Collisions are fine "
        "and are listed so they can be seen, not so they can be fixed.",
        "",
        "The draft labels were guessed by `--propose`: the first letter of "
        "each word, skipping ordinals, numbers and `LVL`, keeping the first "
        "and last when more than two remain. `7TH LVL DW FIGHTER` gives "
        "`DF`; `9 HEADED HYDRA` gives `HH`; `LEVEL 6 MU` gives `MU`.",
        "",
    ]
    for _, short in TITLES:
        lines.append(f"## {short}")
        lines.append("")
        if short in missing:
            lines.append("Disks not found on this machine; the rows in the "
                         "YAML for this title are kept unchanged.")
            lines.append("")
            continue
        here = {n: m for n, m in monsters.items() if short in m.titles}
        by_label = collections.defaultdict(list)
        for n in here:
            by_label[labels.get(n, "")].append(n)
        lines.append(f"{sum(len(m.titles[short]) for m in here.values())} "
                     f"`MON*` files, {len(here)} distinct names.")
        lines.append("")
        lines.append("| name | files | hit dice | label | shares it with |")
        lines.append("|---|---|---|---|---|")
        for name in sorted(here):
            m = here[name]
            lab = labels.get(name, "")
            others = [n for n in by_label.get(lab, []) if n != name] if lab else []
            flag = " **(too long)**" if len(lab) > MOST else ""
            dice = "" if m.hit_dice is None else str(m.hit_dice)
            lines.append(f"| {name} | {', '.join(m.titles[short])} | {dice} "
                         f"| `{lab}`{flag} | {', '.join(sorted(others))} |")
        lines.append("")
    problems = report(monsters, labels, missing)
    lines.append("## Checks")
    lines.append("")
    lines.extend(f"* {p}" if not p.startswith("    ") else f"  * {p.strip()}"
                 for p in problems)
    lines.append("")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="The combat map's monster labels: report, draft, "
                    "document.")
    ap.add_argument("--propose", action="store_true",
                    help="append a draft row to the YAML for every name "
                         "that has none")
    ap.add_argument("--markdown", metavar="PATH", type=pathlib.Path,
                    help="write the document to read the table by")
    ap.add_argument("--table", metavar="PATH", type=pathlib.Path,
                    default=TABLE_PATH, help="the YAML (default: %(default)s)")
    args = ap.parse_args(argv)

    monsters, missing = read_disks()
    if args.propose:
        added = propose(monsters, args.table)
        print(f"Added {len(added)} draft rows to {args.table}"
              if added else f"Nothing to add: every name has a row in "
                            f"{args.table}")
    labels = load_table(args.table)
    for line in report(monsters, labels, missing):
        print(line)
    if args.markdown:
        markdown(monsters, labels, missing, args.markdown)
        print(f"Wrote {args.markdown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
