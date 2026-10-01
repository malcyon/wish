#!/usr/bin/env python3
"""Find the words `.claude/rules/words.md` bans in the project's prose.

    tools/suite/bannedwords.py [PATH...]   # every hit, as path:line row: excerpt
    tools/suite/bannedwords.py --report    # counts per row per top-level directory
    tools/suite/bannedwords.py --baseline  # the per-file counts, as tests/suite/bannedwords_baseline.py

Prose is what a person reads: Python comments, docstrings and string literals,
Markdown outside code, `.ui` text and configuration lines. Backtick spans,
fenced blocks, path-like tokens, URLs and `#N (title)` citations are blanked
before matching, so an identifier, an API name or a quoted title never counts.

`census` also covers identifiers and file names (`Row.ident`), because `words.md`
says so. `refusal` has no exemption at all (`Row.raw`): it is matched as a
substring of every line of every tracked text file, in identifiers, keys,
quotations, backticks, JSON and file names alike. Set `raw=False` on that row
and it falls back to prose-only checking; that is the single switch.

Standard library only, so `tools/wishagent.py` can load it by file path.
"""

from __future__ import annotations

import argparse
import ast
import io
import re
import subprocess
import sys
import tokenize
from collections import Counter, namedtuple
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

Hit = namedtuple("Hit", "path line row kind excerpt")


class Row:
    """One banned term: the prose pattern, the contexts that are not the banned
    use, and for a few rows the identifier pattern.

    `terms` are the bold words in the first cell of the `words.md` table that
    this row stands for; `tests/suite/test_banned_words.py` checks the two
    agree.
    """

    def __init__(self, name, terms, pattern, context_ok=(), ident=None, flags=re.I,
                 raw=False):
        self.name = name
        self.terms = tuple(terms)
        self.pattern = re.compile(pattern, flags)
        # (pattern, reason): a hit overlapping a match is a literal use.
        self.context_ok = tuple((re.compile(p, re.I), why) for p, why in context_ok)
        self.ident = re.compile(ident, re.I) if ident else None
        # No exemption of any kind: matched on the raw text of every line.
        self.raw = raw


ROWS = (
    Row("corpus", ("corpus",), r"\bcorp(?:us|ora)\b"),
    Row("load-bearing", ("load-bearing",), r"\bload[- ]bearing\b"),
    Row("fair", ("fair",), r"\bfair\b"),
    Row("blast radius", ("blast radius",), r"\bblast\s+radius\b"),
    Row("elide", ("elide",), r"\belid(?:e|ed|es|ing)\b|\belision\b"),
    Row("obviate", ("obviate",), r"\bobviat(?:e|ed|es|ing)\b"),
    Row("retarget", ("retarget",), r"\bretarget(?:s|ed|ing)?\b"),
    # `DosShape`, `ElideRight` and `setTextElideMode` never match: the letter
    # before or after the word is a word character.
    Row("shape", ("shape",), r"\bshap(?:e|es|ed|ing)\b"),
    Row("bites", ("bites",), r"\bbit(?:e|es|ing)\b", context_ok=(
        (r"\d*d\d+\s+bite", "a monster's dice-rolled attack"),
        (r"(?:poison|acid|melee)\s+bit(?:e|es)", "a monster's attack"),
        (r"bite\s+and\s+hold", "a monster's attack"),
    )),
    Row("worth", ("worth",), r"\bworth\b"),
    Row("rating", ("says so out loud", "narrower than it looks", "earned its keep"), (
        r"says so out loud|the important thing|than it looks|worse than I said"
        r"|the interesting kind|look at hardest|this is the useful part"
        r"|earned its keep|paid for itself|was the right call"
        # "note that" only as an imperative: a noun ("a developer's note that
        # escaped") is ordinary English.
        r"|(?:^[ \t]*|[.;:!?(][ \t]*|\b(?:to|we|you|please)[ \t]+)note[ \t]+that\b"
    ), flags=re.I | re.M),
    Row("plain", ("plain",), r"\bplain(?:ly)?\b"),
    Row("floor", ("floor",), r"\bfloors?\b", context_ok=(
        (r"combat\s+floor", "the ground of the combat screen"),
        (r"on\s+the\s+floor", "the ground"),
        (r"floor\s+of\s+the", "the storey or ground of a place"),
        (r"castle,\s+a\s+floor", "a storey of a castle"),
        (r"=\s*floor", "an assignment of a floor value"),
    )),
    # A bare "carry" is the 6502 flag and the inventory verb, and stays.
    Row("carried", ("carried",), (
        r"\bnot\s+(?:be\s+)?carried\b|\bnowhere\s+to\s+carry\b"
        r"|\bcarr(?:y|ies|ied|ying)\s+(?:it\s+|them\s+|that\s+|this\s+)?(?:across|over)\b"
    )),
    Row("census", ("census",), r"census", ident=r"census"),
    Row("refusal", ("refusal", "refusals"), r"refusal", raw=True),
)

# Most segments hold no banned word at all; one alternation rules them out.
_ANY_ROW = re.compile("|".join(f"(?im:{r.pattern.pattern})" for r in ROWS if not r.raw))
_PROSE_ROWS = tuple(r for r in ROWS if not r.raw)
_RAW_ROWS = tuple(r for r in ROWS if r.raw)
_IDENT_ROWS = tuple(r for r in ROWS if r.ident)
_ANY_IDENT = re.compile("|".join(r.ident.pattern for r in _IDENT_ROWS), re.I).search

#: Rows of `words.md` no pattern can tell from the allowed use; a person
#: reviews them. name -> (terms in the table's first cell, reason).
UNCHECKED = {
    "follows": (('"X follows Y"',), 'Most uses mean "comes after", which is allowed.'),
    "walks": ((), 'Who walks, arrives or stands is a judgement about the subject.'),
}

#: Files that state or test the rule, and so must name the words.
EXEMPT_PATHS = frozenset({
    ".claude/rules/words.md",
    "LICENSE",
    "THIRD_PARTY_LICENSES.md",
    "tools/suite/bannedwords.py",
    "tests/suite/test_banned_words.py",
    "tests/suite/bannedwords_baseline.py",
})

#: Exact historical text that is kept: (path, row, text on the line, reason).
#: The text must lie inside the prose segment (a comment, one string or one
#: Markdown paragraph), not merely on the same source line. An entry that
#: suppresses nothing is stale, and a test says so.
ALLOWED = (
    ("CHANGELOG.md", "shape", "colors and shape.",
     "A released note: the published text is a quotation."),
    ("goldbox/yaml_io.py", "shape", "      shape: ",
     "The export key `wish import` reads back; renaming it breaks existing exports."),
    ("goldbox/icons.py", "shape", "<Icon shape=",
     "The repr of the `shape` attribute, which names the field."),
)

#: A full citation: `#137 (Its title)`. Allows one level of nested parentheses.
ISSUE_CITATION = re.compile(r"#\d{1,4} \((?:[^()]|\([^()]*\))*\)")

_BLANKERS = (
    ISSUE_CITATION,
    re.compile(r"`[^`\n]*`"),
    re.compile(r"https?://\S+"),
    re.compile(r"\]\([^)\n]*\)"),
    re.compile(r"(?<![\w-])[\w-]*\w[./]\w[\w./-]*"),
)
_KEY = re.compile(r"[\w./-]*")


def _blank(text):
    """Replace every quotation or code-like token with spaces, keeping offsets."""
    for pattern in _BLANKERS:
        text = pattern.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
    return text


def _match_segment(path, text, first_line, kind, hits, used):
    text = re.sub(r"\\[ntr]", "  ", text)
    if not _ANY_ROW.search(text):
        return  # blanking only removes text, so nothing here can match
    blanked = _blank(text)
    source_lines = None
    for row in _PROSE_ROWS:
        literal = [
            m.span() for ctx, _why in row.context_ok for m in ctx.finditer(blanked)
        ]
        for m in row.pattern.finditer(blanked):
            if any(a < m.end() and m.start() < b for a, b in literal):
                continue
            line = first_line + blanked.count("\n", 0, m.start())
            if source_lines is None:
                source_lines = text.splitlines() or [""]
            source = source_lines[min(line - first_line, len(source_lines) - 1)]
            allowed = next(
                (a for a in ALLOWED
                 if a[0] == path and a[1] == row.name and a[2] in source),
                None,
            )
            if allowed:
                used.add(allowed)
                continue
            hits.append(Hit(path, line, row.name, kind, source.strip()[:120]))


def _python(path, text, hits, used):
    fstring_middle = getattr(tokenize, "FSTRING_MIDDLE", None)
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        _lines(path, text, hits, used)
        return
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            _match_segment(path, " " + tok.string[1:], tok.start[0], "comment", hits, used)
        elif tok.type == tokenize.STRING or (
            fstring_middle is not None and tok.type == fstring_middle
        ):
            if tok.type == tokenize.STRING:
                try:
                    value = ast.literal_eval(tok.string)
                    if isinstance(value, bytes) or _KEY.fullmatch(value):
                        continue
                except (ValueError, SyntaxError):
                    pass
            elif _KEY.fullmatch(tok.string):
                continue
            kind = "docstring" if tok.string[:3] in ('"""', "'''") else "string"
            _match_segment(path, tok.string, tok.start[0], kind, hits, used)
        elif tok.type == tokenize.NAME:
            if not _ANY_IDENT(tok.string):
                continue
            for row in _IDENT_ROWS:
                if row.ident.search(tok.string):
                    hits.append(Hit(path, tok.start[0], row.name, "identifier", tok.string))


def _markdown(path, text, hits, used):
    fence = None
    out = []
    for line in text.split("\n"):
        stripped = line.lstrip()
        marker = stripped[:3] if stripped[:3] in ("```", "~~~") else None
        if fence is None and marker:
            fence = marker
            out.append("")
        elif fence is not None:
            if marker == fence:
                fence = None
            out.append("")
        else:
            out.append(line)
    _match_segment(path, "\n".join(out), 1, "markdown", hits, used)


def _ui(path, text, hits, used):
    for m in re.finditer(r"<string[^>]*>(.*?)</string>", text, re.S):
        first = text.count("\n", 0, m.start(1)) + 1
        _match_segment(path, m.group(1), first, "ui", hits, used)


def _lines(path, text, hits, used):
    _match_segment(path, text, 1, "config", hits, used)


_SEGMENTERS = {
    ".py": _python,
    ".md": _markdown, ".rst": _markdown, ".txt": _markdown,
    ".ui": _ui,
    ".yml": _lines, ".yaml": _lines, ".j2": _lines, ".toml": _lines,
    ".sh": _lines, ".ps1": _lines,
}


def _raw_hits(path, text, hits):
    for row in _RAW_ROWS:
        for m in row.pattern.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            hits.append(Hit(path, line, row.name, "raw", text.split("\n")[line - 1].strip()[:120]))


def scan_text(text, suffix=".md", path="<text>"):
    """The hits in one body of text, as if it were a file ending in `suffix`."""
    hits, used = [], set()
    _SEGMENTERS.get(suffix, _lines)(path, text, hits, used)
    _raw_hits(path, text, hits)
    return hits


def _path_hits(rel):
    return [
        Hit(rel, 0, row.name, "path", rel)
        for row in ROWS
        if (row.pattern if row.raw else row.ident or re.compile("(?!)")).search(rel)
    ]


def tracked_files(root=ROOT):
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True, text=True,
    ).stdout
    return sorted(p for p in out.split("\0") if p)


def scan(root=ROOT, rels=None, return_used=False):
    """Every hit in the tracked files (or `rels`), sorted by path and line."""
    root = Path(root)
    hits, used = [], set()
    for rel in rels if rels is not None else tracked_files(root):
        if rel in EXEMPT_PATHS:
            continue
        full = root / rel
        if full.is_symlink() or not full.is_file():
            continue
        hits.extend(_path_hits(rel))
        try:
            text = full.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        _raw_hits(rel, text, hits)
        segmenter = _SEGMENTERS.get(full.suffix)
        if segmenter is not None:
            segmenter(rel, text, hits, used)
    hits.sort(key=lambda h: (h.path, h.line, h.row))
    return (hits, used) if return_used else hits


def counts(hits):
    """{path: {row: n}}"""
    table = {}
    for h in hits:
        table.setdefault(h.path, Counter())[h.row] += 1
    return {p: dict(sorted(c.items())) for p, c in sorted(table.items())}


def baseline_source(hits):
    lines = [
        '"""Banned-word hits per file that exist today, which may only shrink.',
        "",
        "Generated by `tools/suite/bannedwords.py --baseline`; a batch deletes or",
        "lowers its own lines and never raises one.",
        '"""',
        "",
        "BASELINE = {",
    ]
    for path, row_counts in counts(hits).items():
        lines.append(f"    {path!r}: {row_counts!r},")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("paths", nargs="*", help="tracked paths or directory prefixes")
    parser.add_argument("--report", action="store_true", help="counts per row per directory")
    parser.add_argument("--baseline", action="store_true", help="print the baseline module")
    args = parser.parse_args(argv)
    rels = tracked_files()
    if args.paths:
        prefixes = [p.rstrip("/") for p in args.paths]
        rels = [r for r in rels if any(r == p or r.startswith(p + "/") for p in prefixes)]
    hits = scan(ROOT, rels)
    if args.baseline:
        sys.stdout.write(baseline_source(hits))
    elif args.report:
        table = Counter((h.path.split("/")[0], h.row) for h in hits)
        for (top, row), n in sorted(table.items()):
            print(f"{top}\t{row}\t{n}")
        print(f"total\t{len(hits)}")
    else:
        for h in hits:
            print(f"{h.path}:{h.line} {h.row}: {h.excerpt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
