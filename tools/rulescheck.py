#!/usr/bin/env python3
"""Check that splitting CLAUDE.md lost none of its rules or quotations.

`CLAUDE.md` was 1595 lines until #208 split it into `.claude/rules/*.md` plus
`docs/160-why-these-rules.md`.  A split done by hand across three agents can
drop a paragraph and look tidy afterwards, which is exactly the failure nobody
notices, so this reads the old file straight out of git and asks where each
piece of it went.

Two kinds of fragment are extracted from the old file:

* **quotations** -- anything in `*"..."*`, which is how Donald is quoted.
  These are evidence and must survive character for character, so a missing
  one is an error.
* **imperatives** -- the `**bold**` spans, which is how a rule is stated.
  These are expected to be reworded by the split, so a missing one is a
  prompt to go and look rather than a failure.

Run it from the repository root, naming the revision to compare against:

    python3 tools/rulescheck.py --base 186d62a~1   # the commit before the split

**`--base` is required on purpose.** It defaulted to `HEAD` once, which reads
the *post-split* file and compares it against a corpus that contains it -- so
the tool answered "3 of 3 quotations carried over" and looked like a pass. A
check that cannot fail is worse than no check.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

# Where the old file's content is allowed to have landed.
CORPUS = ("CLAUDE.md", ".claude/rules/*.md", "docs/160-why-these-rules.md")

BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)

#: A quotation is `*"..."*`.  A bold-wrapped one, `**"..."**`, is invisible
#: here: the `**` is stripped below and nothing is left for this to match.  That
#: is deliberate.  Every `**"` in the old file opened a rule statement -- `**"X
#: follows Y"**` -- rather than an attribution, and treating those as evidence
#: would make an error out of the rewording a split is supposed to do.
#:
#: Bold markers are stripped before this runs,
#: because `**"Follows" is ...` opens with `**"` and a pattern that allows
#: anything inside then runs from there to a closing quote paragraphs away --
#: which reported six whole sections as one missing quotation.  Forbidding a
#: `"` inside stops the match at the end of the quotation it started in.
QUOTE = re.compile(r'\*"([^"]+)"\*')


def normalise(text: str) -> str:
    """Collapse whitespace, so a fragment rewrapped to a new width still matches."""
    return " ".join(text.split())


def old_claude_md(base: str) -> str:
    out = subprocess.run(
        ["git", "show", f"{base}:CLAUDE.md"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if out.returncode:
        sys.exit(f"Cannot read CLAUDE.md at {base}: {out.stderr.strip()}")
    return out.stdout


def corpus_text(root: pathlib.Path) -> str:
    parts = []
    for pattern in CORPUS:
        if "*" in pattern:
            parts.extend(sorted(root.glob(pattern)))
        else:
            parts.append(root / pattern)
    found = [p for p in parts if p.is_file()]
    if not found:
        sys.exit("Found none of the files the split was supposed to produce.")
    return normalise("\n".join(p.read_text(encoding="utf-8") for p in found))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--base",
        required=True,
        help="Revision holding the pre-split CLAUDE.md, e.g. 186d62a~1",
    )
    args = ap.parse_args()

    root = pathlib.Path(__file__).resolve().parent.parent
    old = old_claude_md(args.base)
    new = corpus_text(root)

    bolds = {normalise(m) for m in BOLD.findall(old)}
    quotes = {normalise(m) for m in QUOTE.findall(old.replace("**", ""))}

    lost_quotes = sorted(q for q in quotes if q not in new)
    lost_bolds = sorted(b for b in bolds if b not in new)

    print(f"Comparing against CLAUDE.md at {args.base}.")
    print(f"Quotations: {len(quotes) - len(lost_quotes)} of {len(quotes)} carried over.")
    print(f"Imperatives: {len(bolds) - len(lost_bolds)} of {len(bolds)} carried over.")

    if lost_quotes:
        print("\nQuotations that no longer appear anywhere. These are evidence:")
        for q in lost_quotes:
            print(f'  "{q}"')

    if lost_bolds:
        print("\nImperatives that no longer appear verbatim. Reworded, or dropped?")
        for b in lost_bolds:
            print(f"  {b[:110]}{'...' if len(b) > 110 else ''}")

    return 1 if lost_quotes else 0


if __name__ == "__main__":
    raise SystemExit(main())
