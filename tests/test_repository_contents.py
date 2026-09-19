from __future__ import annotations

"""The repository must not carry the game.

`AGENTS.md` forbids committing Pool of Radiance's code, art, music, manuals or
data files. That rule was broken once by accident -- four fixtures, one of them
6502 machine code -- because a test fixture does not feel like a copy while you
are adding it. It is one, so this checks.

The check runs against `git ls-files`, not the working tree: what matters is
what is committed.
"""


import ast
import pathlib
import re
import subprocess
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Extensions the game's content would arrive in. `.bin` is deliberately not
#: here -- see `ALLOWED_FIXTURES`, which is stricter.
FORBIDDEN_SUFFIXES = {
    ".adf",                                             # Amiga disk images
    ".d64", ".d71", ".d81", ".g64", ".t64", ".tap",     # disk and tape images
    ".prg", ".p00", ".crt", ".rom",                     # executables
    ".sid", ".psid", ".mod", ".wav", ".mp3", ".ogg",    # music and sound
    ".pdf",                                             # manuals and cluebooks
}

# Images are **not** on that list. The rule is about the game's content, and a
# blanket ban on `.png` caught our own screenshots and would have caught the
# application icon -- neither of which is SSI's. Donald: "You need to remove
# that test that blocks all pngs. We don't need that."
#
# What still applies is judgement rather than a suffix: a scan of a manual or a
# cluebook map is the game's, whatever it is saved as, and does not belong here.

#: The only binaries allowed in `tests/fixtures/`, and why.
#:
#: Every one is **the player's own saved game**, produced by playing, not
#: content SSI shipped. A capture of live machine memory is not a saved game --
#: it carries whatever code was resident at the time -- so `combat-arena.bin`
#: was taken out of the repository and the combat tests build an arena instead.
#: Several capture states no disk still holds, so they
#: cannot be regenerated. Anything the publisher shipped -- a GEO, an overlay,
#: the party on POOL1 -- is read from the player's disks at run time instead;
#: `tests/gamedata.py` does that.
#:
#: **Do not add to this list.** If a test needs game data, use
#: `gamedata.game_file`, or generate what you need with `gamedata.synthetic_geo`.
ALLOWED_FIXTURES = {
    "savedgame0.bin",
    "savedgame1.bin",
    "party6_savedgame0.bin",
    "party6_after_combat.bin",
    "brutus.chr",
    "lady_katherine.chr",
    "malcyon.chr",
}


def tracked() -> list[pathlib.Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                         capture_output=True, text=True, check=True)
    return [pathlib.Path(p) for p in out.stdout.split("\0") if p]


@pytest.fixture(scope="module")
def files():
    try:
        return tracked()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("not a git checkout")


def test_no_disk_image_executable_or_media_is_committed(files):
    """Whole categories, by extension. A disk image is the obvious one."""
    bad = [str(p) for p in files if p.suffix.lower() in FORBIDDEN_SUFFIXES]
    assert not bad, (
        "these must not be committed -- see 'What must never enter this "
        f"repository' in AGENTS.md: {bad}")


def test_only_the_players_own_saves_live_in_fixtures(files):
    """The rule that actually caught the four.

    A new binary under `tests/fixtures/` is presumed to be game content until
    somebody argues otherwise, because that is how the last four arrived.
    """
    here = [p for p in files if p.parts[:2] == ("tests", "fixtures")]
    unexpected = sorted(p.name for p in here
                        if p.name not in ALLOWED_FIXTURES)
    assert not unexpected, (
        "new fixtures must not be slices of the game's files. Read them from "
        "the player's disks with tests/gamedata.py instead, or generate them: "
        f"{unexpected}")


def test_the_licence_is_present(files):
    """PyQt6 is GPL, so this is too, and the text has to ship with it."""
    assert pathlib.Path("LICENSE") in files
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "GNU GENERAL PUBLIC LICENSE" in text
    assert "Version 3" in text


def test_no_hardcoded_user_paths(files):
    """Fails on a string literal containing a hardcoded home path."""
    import ast
    bad = []
    py_files = [p for p in files if p.suffix == ".py"]
    for path in py_files:
        if path.name in ("test_instance.py", "test_repository_contents.py"):
            continue
        try:
            content = (ROOT / path).read_text(encoding="utf-8")
            tree = ast.parse(content, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    val = node.value.lower()
                    if "/home/ada" in val:
                        continue
                    if "/home/" + "donald" in val or "/users/" + "donald" in val or "c:\\users\\" + "donald" in val:
                        bad.append(f"{path}:{node.lineno}")
        except SyntaxError:
            pass

    # `gamedisks.yaml.example` (#212) is a committed list of absolute paths,
    # which is exactly what this test polices -- and it is not Python, so the
    # walk above never sees it.  A candidate under somebody's home directory
    # has to be written `~/...`, which works on every machine; spelling the
    # home out names one person's and nobody else's.
    for path in (p for p in files
                 if p.suffix == ".toml" or p.name.endswith(".yaml.example")):
        # `.codex/agents/<name>.toml` (#506) is generated verbatim from
        # `.claude/agents/<name>.md`'s body by `tools/generate/gencodex.py`, so a line
        # this loop would otherwise flag is only a problem if it is *new* --
        # if the same text is not already sitting, unflagged, in the source
        # `.md` (this test does not walk `.md` at all). This is narrower than
        # exempting the whole directory: a hardcoded path introduced by the
        # generator itself, rather than copied from its source, still fails.
        source_text = None
        if path.parent.as_posix() == ".codex/agents":
            source_md = ROOT / ".claude" / "agents" / f"{path.stem}.md"
            if source_md.exists():
                source_text = source_md.read_text(encoding="utf-8").lower()
        for n, line in enumerate((ROOT / path).read_text(encoding="utf-8").splitlines(), 1):
            val = line.lower()
            if "/home/ada" in val:
                continue
            if ("/home/" + "donald" in val or "/users/" + "donald" in val
                    or "c:\\users\\" + "donald" in val):
                if source_text is not None and val in source_text:
                    continue
                bad.append(f"{path}:{n}")

    assert not bad, f"Hardcoded developer paths found in string literals: {bad}"



# -- where a tool or test may look for game data (#575) -------------------------

#: A string in code that names where one machine keeps its data, rather than
#: asking `gamedisks.yaml`, `automap.paths` or `$WISH_SPECIMENS`. Docstrings
#: and comments may say where things are; only a string that is used is flagged.
_MACHINE_PATH = ("/mnt/", "~/downloads", "~/dos_por_play", "fr-archives")

#: (file, text the string starts with) for a string that looks like a machine
#: path and is not a lookup. By string, not by file, so a new lookup in the
#: same file is still caught.
_NOT_A_LOOKUP = {
    # Fake paths handed to a parser that only reads their names.
    ("tests/test_carryceiling.py", "/mnt/roms/c64/PORSAVE.D64"):
        "a fake save path the census parses",
    ("tests/test_enccensus.py", "/home/x/Downloads/fr-archives"):
        "a fake path the census classifies by its name",
    ("tests/test_spellbookcensus.py", "/x/fr-archives"):
        "a fake path the census classifies by its name",
    # A `[Version]` config file inside a string, which contains `/mnt/`.
    ("tests/test_instance.py", "    [Version]"): "VICE config text",
    # The text of a dialog a screenshot shows, not a path it opens.
    ("tools/convert/convertshots.py", "~/dos_por_play/wish-2026-09-10"):
        "a dialog's folder text",
}


def _docstring_ids(tree):
    ids = set()
    for node in ast.walk(tree):
        if (isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                              ast.AsyncFunctionDef)) and node.body):
            first = node.body[0]
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                ids.add(id(first.value))
    return ids


def test_no_machine_path_is_looked_up_in_code(files):
    """A path to one machine's game data, written in code, is the thing
    `gamedisks.yaml` exists to remove: on any other machine it finds nothing
    and each file has its own place to edit (#575). Ask the registry, or
    `automap.paths`, or `$WISH_SPECIMENS`."""
    bad = []
    for path in (p for p in files if p.suffix == ".py"):
        name = path.as_posix()
        if name in ("tests/test_repository_contents.py",
                    "tests/test_gamedisks.py"):
            continue
        try:
            tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        docstrings = _docstring_ids(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant)
                    and isinstance(node.value, str)) or id(node) in docstrings:
                continue
            low = node.value.lower()
            if any(part in low for part in _MACHINE_PATH):
                if any(name == f and node.value.startswith(text)
                       for f, text in _NOT_A_LOOKUP):
                    continue
                bad.append(f"{name}:{node.lineno}: {node.value[:60]!r}")
    assert not bad, (
        "Game data reached by a path written in code instead of the registry:\n"
        + "\n".join(bad))


#: The rule files, and the page holding the incidents behind them. Both are
#: cited by path from tests, package code, `docs/` and the agent definitions,
#: and none of those citations is checked by anything else.
RULES_DIR = ".claude/rules"
WHY = "docs/160-why-these-rules.md"

#: A citation of a rule file or of the incidents page, anywhere in the tree.
RULE_CITATION = re.compile(r"`?\.claude/rules/([a-z0-9_-]+\.md)`?")


def test_no_citation_points_at_a_rule_file_that_is_not_there(files):
    """A `.claude/rules/X.md` citation names a file that exists.

    `#208 (Split CLAUDE.md into .claude/rules, so 21,800 tokens do not load
    before every task)` turned one file into thirteen and rewrote eighteen
    citations to point at them. That trades a file everybody knew for a set of
    paths nothing verifies -- rename `gui-text.md` and the tooltip rule in
    `goldbox/dos_codec.py` quietly points at nothing.

    Scoped to tracked `.md` and `.py` files, and to the two paths the split
    created, because those are the ones with no other guard.
    """
    bad = []
    for rel in files:
        if rel.suffix not in (".md", ".py"):
            continue
        for i, line in enumerate((ROOT / rel).read_text(encoding="utf-8").splitlines()):
            for name in RULE_CITATION.findall(line):
                if not (ROOT / RULES_DIR / name).is_file():
                    bad.append(f"{rel.as_posix()}:{i + 1}  {RULES_DIR}/{name}")
            if WHY in line and not (ROOT / WHY).is_file():
                bad.append(f"{rel.as_posix()}:{i + 1}  {WHY}")
    assert not bad, (
        "these cite a rule file that is not there:\n  " + "\n  ".join(bad)
        + "\n\nRenaming a rule file means rewriting what points at it.")


def test_every_rule_file_points_at_a_heading_that_exists(files):
    """Each rule file ends by naming its section of the incidents page.

    The pointer is the only thing joining a rule to the evidence for it, and a
    heading renamed on one side of that link breaks it silently -- the rule
    still reads correctly, and the reason for it simply cannot be found.
    """
    why = ROOT / WHY
    assert why.is_file(), (
        f"{WHY} is not there, and every rule file cites a section of it.")
    headings = {
        line[3:].strip()
        for line in why.read_text(encoding="utf-8").splitlines()
        if line.startswith("## ")
    }
    rules = sorted(p for p in files if p.parent.as_posix() == RULES_DIR)
    assert rules, f"nothing is tracked under {RULES_DIR}"
    bad = []
    for rule in rules:
        text = (ROOT / rule).read_text(encoding="utf-8")
        named = re.findall(rf'{re.escape(WHY)}`?,\s*"([^"]+)"', text)
        if not named:
            bad.append(f"{rule.name} names no section of {WHY}")
            continue
        for heading in named:
            if heading not in headings:
                bad.append(f'{rule.name} points at "{heading}", which is not a heading there')
    assert not bad, "\n  ".join(
        ["broken links to the incidents page:"] + bad
        + ["", f"Rename a heading in {WHY} and the rule citing it must change too."])


def test_every_rule_file_has_a_row_in_the_routing_table(files):
    """A file under `.claude/rules/` with no row in `AGENTS.md`'s table is
    unreachable by anything that is not Claude Code.

    Six of the thirteen load into a Claude Code session at launch and seven
    load when Claude Code reads a matching file, but neither mechanism exists
    for a tool with no `paths:` frontmatter and no launch-time rule loader --
    `AGENTS.md`'s table is the only route it has to any of them, which is why
    every one of the thirteen needs a row.

    This only checks that the filename is *named* somewhere in the table; it
    says nothing about whether the trigger sentence beside it is honest about
    the situation that should send a reader to the file.
    """
    agents_md = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    start = agents_md.index("| Before you |")
    end = agents_md.index("\n\n", start)
    table = agents_md[start:end]
    named = set(re.findall(r"`([a-z0-9_-]+\.md)`", table))

    rules = {p.name for p in files if p.parent.as_posix() == RULES_DIR}
    assert rules, f"nothing is tracked under {RULES_DIR}"

    missing = sorted(rules - named)
    assert not missing, (
        "these .claude/rules/ files have no row in AGENTS.md's routing "
        "table:\n  " + "\n  ".join(missing)
        + "\n\nA tool with no paths: mechanism has no other way to find them.")


#: Phrases that drifted out of step with `AGENTS.md` once each, inside a
#: `.claude/agents/*.md` file that had retyped rather than pointed at it --
#: `junior-dev.md` told an agent to commit its own work and to run the whole
#: suite, against the shared rules that subagents never commit and scope a run
#: to the files they touched; `backlog-auditor.md` carried a label rule
#: `.claude/rules/issues.md` retired on 2026-09-09; several files repeated the
#: false "a subagent does not inherit `.claude/rules/`" premise.
#:
#: A literal match against wording that has already drifted once, not a
#: general redundancy check. It catches one of these phrases coming back,
#: including a rewritten agent file resurrecting an old one; it will not catch
#: a *new* paraphrase of a prohibition `AGENTS.md` already makes, and it says
#: nothing about whether an agent file is otherwise redundant with `AGENTS.md`.
DRIFTED_PROHIBITIONS = (
    "does not inherit",
    "Commit your work.",
    "Run the suite before you report",
    "Never propose removing or changing a label somebody else set",
)


def test_no_agent_definition_restates_a_prohibition_agents_md_already_makes(files):
    """A subagent definition that retypes `AGENTS.md` drifts away from it.

    `junior-dev.md` once said "Commit your work" where `AGENTS.md` says
    subagents never commit, and "Run the suite before you report" where
    `AGENTS.md` scopes a subagent's run to the files it touched -- both typed
    once and never touched again while the shared rule moved on.
    """
    bad = []
    for rel in files:
        if rel.parent.as_posix() != ".claude/agents" or rel.suffix != ".md":
            continue
        text = (ROOT / rel).read_text(encoding="utf-8")
        for phrase in DRIFTED_PROHIBITIONS:
            if phrase in text:
                bad.append(f"{rel.as_posix()}: {phrase!r}")
    assert not bad, (
        "these agent definitions restate a prohibition AGENTS.md already "
        "makes, or a sentence that drifted away from it before:\n  "
        + "\n  ".join(bad))


#: Everything under `.agents/rules/` is a symlink to the one copy in
#: `.claude/rules/` -- see `#209 (Give Antigravity the same rules as Claude
#: Code, without a second copy of them)`.
SHARED_LINKS = (".agents/rules",)

#: `CLAUDE.md` holds no rules of its own. It imports the file that does, which
#: Google's tools read directly.
IMPORTED = "AGENTS.md"


def test_every_shared_rule_link_resolves(files):
    """The links Antigravity reads point at files that are still there.

    Claude Code reads `CLAUDE.md` and `.claude/rules/`; Antigravity reads
    `AGENTS.md` and `.agents/rules/`. They are the same bytes because the second
    set is symlinks, which is what keeps there being one copy. Nothing else
    notices when a rule file is renamed and its link is left pointing at a name
    that has gone -- Claude Code carries on working, and only the Google side
    breaks, which is the half nobody is looking at.

    **Skipped where the checkout has no symlinks.** `git` on Windows writes a
    symlink as a plain file holding its target's path unless `core.symlinks` is
    on, so on those runners there is nothing to resolve and nothing to check.
    """
    links = [
        p for p in files
        if (p.as_posix() in SHARED_LINKS or p.parent.as_posix() in SHARED_LINKS)
    ]
    assert links, "nothing tracked at " + ", ".join(SHARED_LINKS)

    real = [p for p in links if (ROOT / p).is_symlink()]
    if not real:
        pytest.skip("this checkout has no symlinks, so there is nothing to resolve")

    bad = [
        f"{p.as_posix()} -> {(ROOT / p).readlink()}"
        for p in real
        if not (ROOT / p).resolve().is_file()
    ]
    assert not bad, (
        "these links point at a file that is not there:\n  " + "\n  ".join(bad)
        + "\n\nRenaming a rule file means moving the link that points at it.")


def test_the_shared_rule_links_point_inside_this_repository(files):
    """A link out of the tree would be one machine's, not the project's.

    A symlink is committed as its target path, so one resolving to somebody's
    home directory is a path that means something different on every machine --
    and it would resolve on the machine it was written on, which is what makes
    it easy to miss.
    """
    bad = []
    for p in files:
        if p.as_posix() not in SHARED_LINKS and p.parent.as_posix() not in SHARED_LINKS:
            continue
        if not (ROOT / p).is_symlink():
            continue
        target = (ROOT / p).resolve()
        if not target.is_relative_to(ROOT):
            bad.append(f"{p.as_posix()} -> {target}")
    assert not bad, (
        "these links leave the repository:\n  " + "\n  ".join(bad)
        + "\n\nA link's target is committed verbatim, so it has to be relative "
          "and inside the tree.")


def test_claude_md_imports_the_file_that_holds_the_rules():
    """`CLAUDE.md` is an import line and a few Claude-only paragraphs.

    The rules live in `AGENTS.md` because Antigravity reads that name and not
    this one. Claude Code reaches them through the `@AGENTS.md` import, so **the
    import is the only thing carrying 200 lines of rules into a Claude session**
    -- delete the line, or rename the target, and every session silently starts
    with almost no rules and nothing says so.
    """
    claude = ROOT / "CLAUDE.md"
    assert claude.is_file(), "CLAUDE.md is not there"
    text = claude.read_text(encoding="utf-8")

    assert f"@{IMPORTED}" in text, (
        f"CLAUDE.md no longer imports {IMPORTED}, so a Claude session gets none "
        f"of the rules. The import is a bare `@{IMPORTED}` on its own line.")
    assert (ROOT / IMPORTED).is_file(), (
        f"CLAUDE.md imports {IMPORTED}, which is not there.")

    # "Banned Words" is the one exception: it lists the jargon Claude
    # reaches for, so it belongs in Claude's file. Moved 2026-09-10.
    assert "## Banned Words" in text, (
        "CLAUDE.md no longer holds the words table. It lives here rather than "
        f"in {IMPORTED} because it corrects this model's own habits.")
    assert "## Banned Words" not in (ROOT / IMPORTED).read_text(encoding="utf-8"), (
        f"the words table is Claude-only and belongs in CLAUDE.md, not {IMPORTED}.")


# -- a bare issue number is a lookup the reader has to go and do -------------

#: A full citation: `#137 (Its title)`. Allows one level of nested parens --
#: `#215 (Nothing checks that a frame halve() is about to halve was really
#: line-doubled)` is a real title -- but no more, which keeps it from
#: swallowing a second citation on the same line. Stripped out first so what
#: remains is only the bare mentions.
FULL_CITATION = re.compile(r"#\d{1,4} \((?:[^()]|\([^()]*\))*\)")

#: A number that could be an issue reference: 1-4 digits, not the tail of a
#: longer run of digits or hex letters (so `#555555` and `#2f7d4f`, a CSS
#: colour, never match), and not preceded by a word character or `/` (so a
#: URL fragment like `.../issues/136` does not).
BARE_ISSUE_NUMBER = re.compile(r"(?<![\w/])#(\d{1,4})(?![\da-fA-F])")

#: Where this rule applies: `docs/`, the listed READMEs and `tools/*/README.md`,
#: the prose that cites issues as project documentation. Three kinds of tracked
#: `.md` stay outside it, because a bare number is the content there or is
#: written another way:
#:
#: * `AGENTS.md` writes a bare `#123` only as the example of what *not* to
#:   write -- scanning it would delete the example.
#: * `.claude/agents/*.md` quote a bare `#59` or `#78` the same way, and
#:   `junior-dev.md` cites issues in its own worked examples rather than in
#:   project prose.
#: * `CHANGELOG.md` uses a written-out markdown link,
#:   `[#78](https://github.com/.../issues/78)`, because GitHub does not
#:   auto-link a bare number off the release page; see
#:   `.claude/agents/changelog-writer.md`.
CITED_ISSUE_SCOPE = ("docs",)
CITED_ISSUE_FILES = {
    pathlib.PurePosixPath("tools/README.md"),
    pathlib.PurePosixPath("goldbox/README.md"),
    pathlib.PurePosixPath("editor/README.md"),
    pathlib.PurePosixPath("ui/README.md"),
}


def test_no_bare_issue_number_where_a_citation_belongs(files):
    """Every issue citation carries its title: `#137 (Its title)`, not `#137`.

    `.claude/rules/issues.md`: *"A bare number is a lookup Donald has to go and
    do."* His own words are the reason it is a rule at all -- *"When you only
    reference a number, it never means anything to me."* A commit message and
    the body of a GitHub issue are the two places a bare number is read where
    it hovers into a title on its own; nothing tracked in this repository is
    either.
    """
    bad = []
    for rel in files:
        if rel.suffix != ".md":
            continue
        in_scope = (rel.parts[0] in CITED_ISSUE_SCOPE
                    or pathlib.PurePosixPath(rel.as_posix()) in CITED_ISSUE_FILES
                    or pathlib.PurePosixPath(rel.as_posix()).match("tools/*/README.md"))
        if not in_scope or rel.parts[:2] == (".github", "ISSUE_TEMPLATE"):
            continue
        text = (ROOT / rel).read_text(encoding="utf-8")
        # A generated page's citations come from the source it is built from --
        # `goldbox/layout.py`'s field notes, `goldbox/memory.py`'s regions --
        # so a bare number here means the source was never swept, not that
        # this page needs its own exemption: a generated page is scanned like
        # any other.
        # Fenced code carries a commit-message example verbatim (the one place
        # AGENTS.md itself allows a bare number) and must not be scanned.
        text = re.sub(r"```.*?```", lambda m: re.sub(r"[^\n]", " ", m.group(0)),
                       text, flags=re.S)
        text = FULL_CITATION.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
        for m in BARE_ISSUE_NUMBER.finditer(text):
            line_no = text[:m.start()].count("\n") + 1
            bad.append(f"{rel.as_posix()}:{line_no}  {m.group(0)}")
    assert not bad, (
        "these cite an issue by bare number instead of `#N (Title)`:\n  "
        + "\n  ".join(bad)
        + "\n\nTake the title from `gh issue view N --json number,title`.")


# -- nothing tracked may name the scratch directory --------------------------
#
# Donald, 2026-09-18: the gitignored scratch directory at the repository root
# is deleted for good, and nothing in the repository may name it as an input or
# an output. Two scans, because a path is written two ways: as text anywhere, and
# as a path segment in Python where the text has no slash to find. The checkers
# take text or source so the tests below can hand them a violation.

#: A repo-relative path into the scratch directory. The lookbehind lets a longer
#: path through: `network/x`, `homework/x`, `a/work/b`, `~/.cache/work/x` and
#: `my-work/x` all have a word character, slash, dot, tilde or hyphen in front
#: of the name, so they are somebody else's. The lookahead wants a path
#: character after the slash, so `work/` at the end of a line or before a space
#: is prose about the directory and is not matched -- which is also why the
#: `.gitignore` line for it is not the thing this reports.
WORK_PATH = re.compile(r"(?<![\w/.~-])work/[\w.<{$*-]")

#: Not scanned: this file, whose fixtures below are violations on purpose.
WORK_SCAN_SKIPS = {"tests/test_repository_contents.py"}

#: A `Path(...)` or a `join` is how Python builds a path from a segment.
_PATH_BUILDERS = {"Path", "PurePath", "PosixPath", "WindowsPath",
                  "PurePosixPath", "PureWindowsPath", "joinpath", "join"}

#: How many `path:line` entries a failure lists before it says how many more.
WORK_REPORT_CAP = 40


def work_path_lines(text: str) -> list[int]:
    """Line numbers (from 1) of `text` that name a path into the scratch dir."""
    return [n for n, line in enumerate(text.splitlines(), 1)
            if WORK_PATH.search(line)]


def _is_work_constant(node) -> bool:
    return isinstance(node, ast.Constant) and node.value == "work"


def _callee_name(func) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def work_segment_lines(source: str) -> list[int]:
    """Line numbers where Python source uses the string "work" as a path
    segment: `x / "work"`, `Path("work")`, `Path(root, "work")`,
    `os.path.join(root, "work")`, `root.joinpath("work")`.

    A `"work"` that is a dict key, a word in prose or a comparison is not a path
    segment and is not reported. Source that does not parse reports nothing:
    another test owns that failure.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    lines = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            if _is_work_constant(node.right) or _is_work_constant(node.left):
                lines.add(node.lineno)
        elif isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Div):
            if _is_work_constant(node.value):
                lines.add(node.lineno)
        elif isinstance(node, ast.Call):
            if (_callee_name(node.func) in _PATH_BUILDERS
                    and any(_is_work_constant(a) for a in node.args)):
                lines.add(node.lineno)
    return sorted(lines)


def _readable_text(root: pathlib.Path, rel: pathlib.Path) -> str | None:
    """The file's text, or None for anything that is not a text file: a binary,
    a symlink to nowhere, a directory, or a file tracked but deleted from the
    working tree (which is a change somebody has not committed yet)."""
    path = root / rel
    if not path.is_file():
        return None
    data = path.read_bytes()
    if b"\0" in data:
        return None
    return data.decode("utf-8", errors="replace")


def scan_for_work_paths(root: pathlib.Path, rels) -> list[str]:
    """`path:line` for every text file in `rels` that names a path into the
    scratch directory, as text."""
    hits = []
    for rel in rels:
        if rel.as_posix() in WORK_SCAN_SKIPS:
            continue
        text = _readable_text(root, rel)
        if text is not None:
            hits += [f"{rel.as_posix()}:{n}" for n in work_path_lines(text)]
    return hits


def scan_for_work_segments(root: pathlib.Path, rels) -> list[str]:
    """`path:line` for every `.py` in `rels` that builds a path through the
    scratch directory."""
    hits = []
    for rel in rels:
        if rel.suffix != ".py" or rel.as_posix() in WORK_SCAN_SKIPS:
            continue
        text = _readable_text(root, rel)
        if text is not None:
            hits += [f"{rel.as_posix()}:{n}" for n in work_segment_lines(text)]
    return hits


def _listing(hits: list[str]) -> str:
    shown = "\n  ".join(hits[:WORK_REPORT_CAP])
    more = len(hits) - WORK_REPORT_CAP
    return shown + (f"\n  ... and {more} more" if more > 0 else "")


def test_no_tracked_file_names_the_scratch_directory(files):
    hits = scan_for_work_paths(ROOT, files)
    assert not hits, (
        f"{len(hits)} places name a path into the deleted scratch directory. "
        "A run's output goes to a temp directory (tools/registry/scratch.py) and a "
        "finding goes in a comment on its issue or in docs/:\n  "
        + _listing(hits))


def test_no_python_file_builds_a_path_through_the_scratch_directory(files):
    hits = scan_for_work_segments(ROOT, files)
    assert not hits, (
        f"{len(hits)} places build a path through the deleted scratch "
        "directory in code:\n  " + _listing(hits))


def test_the_scratch_directory_does_not_exist():
    """Fails the moment anything recreates it. `pytest_sessionfinish` in
    `tests/conftest.py` covers a test that makes it after this one has run."""
    import conftest
    found = conftest.scratch_directory_present(ROOT)
    assert found is None, (
        f"{found} exists. It is deleted for good; something wrote there, or a "
        "worktree was given a link to it.")


# -- the guard itself ---------------------------------------------------------

@pytest.mark.parametrize("text", [
    "work/foo",
    "cd work/issue12 && ls",
    "see `work/<n>/out.txt`",
    "open('work/{name}.log')",
    "ls work/*",
    "work/.hidden",
    "out = \"work/x\"",
    "and/or work/school",      # prose is matched too: the regex cannot tell
])
def test_the_text_check_flags_a_path_into_the_scratch_directory(text):
    assert work_path_lines(text) == [1]


@pytest.mark.parametrize("text", [
    "network/foo",
    "homework/x",
    "~/.cache/work/x",
    "a/work/b",                # a longer path: the slash in front lets it through
    "my-work/x",
    "x.work/y",
    "~work/x",
    "the work/",               # nothing after the slash
    "work/ is deleted",
    "work",
    "at work",
])
def test_the_text_check_leaves_other_paths_alone(text):
    assert work_path_lines(text) == []


def test_the_text_check_reports_the_right_line():
    assert work_path_lines("fine\nfine\nrm -r work/tmp\nfine") == [3]


@pytest.mark.parametrize("source", [
    'p = root / "work"',
    'p = "work" / root',
    'p = root / "work" / "out"',
    'p = Path("work")',
    'p = pathlib.Path("work")',
    'p = PurePath("work")',
    'p = pathlib.PurePosixPath("work", "x")',
    'p = Path(root, "work")',
    'p = os.path.join(root, "work", "x")',
    'p = join("work", "x")',
    'p = root.joinpath("work")',
    'p /= "work"',
])
def test_the_source_check_flags_work_as_a_path_segment(source):
    assert work_segment_lines(source) == [1]


@pytest.mark.parametrize("source", [
    'd = {"work": 1}',
    'msg = "the work is done"',
    'if kind == "work":\n    pass',
    'p = root / "network"',
    'p = Path("homework")',
    'p = os.path.join(root, "homework")',
    'print("work")',
    'x = ["work", "play"]',
    'p = ", ".join(["work", "play"])',
])
def test_the_source_check_leaves_other_uses_of_the_word_alone(source):
    assert work_segment_lines(source) == []


def test_the_source_check_reports_the_right_line():
    assert work_segment_lines('a = 1\nb = 2\np = root / "work"\n') == [3]


def test_a_scan_over_files_reports_path_and_line_and_skips_what_it_should(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "bad.md").write_text("fine\nrun work/x\n")
    (tmp_path / "bad.py").write_text('p = root / "work"\nq = "work/y"\n')
    (tmp_path / "ok.md").write_text("network/x and ~/.cache/work/y\n")
    (tmp_path / "blob.bin").write_bytes(b"\0work/x\0")
    # The guard's own fixtures are violations on purpose.
    (tmp_path / "tests" / "test_repository_contents.py").write_text("work/x\n")
    rels = [pathlib.Path(n) for n in (
        "bad.md", "bad.py", "ok.md", "blob.bin", "gone.md",
        "tests/test_repository_contents.py")]

    assert scan_for_work_paths(tmp_path, rels) == [
        "bad.md:2", "bad.py:2"]
    assert scan_for_work_segments(tmp_path, rels) == ["bad.py:1"]


def test_a_long_report_says_how_many_it_left_out():
    hits = [f"f.md:{n}" for n in range(WORK_REPORT_CAP + 5)]
    listing = _listing(hits)
    assert f"f.md:{WORK_REPORT_CAP - 1}" in listing
    assert f"f.md:{WORK_REPORT_CAP}" not in listing
    assert "and 5 more" in listing


def test_the_session_hook_fails_a_run_that_leaves_the_directory(tmp_path, monkeypatch):
    import conftest
    monkeypatch.setattr(conftest, "_REPO_ROOT", tmp_path)

    class Reporter:
        lines: list[str] = []

        def write_line(self, line, **_):
            self.lines.append(line)

    def session(reporter=None, worker=False):
        config = types.SimpleNamespace(
            pluginmanager=types.SimpleNamespace(get_plugin=lambda _: reporter))
        if worker:
            config.workerinput = {}
        return types.SimpleNamespace(config=config, exitstatus=0)

    # Absent: silent, and the exit status is untouched.
    quiet = session(Reporter())
    conftest.pytest_sessionfinish(quiet, 0)
    assert quiet.exitstatus == 0 and Reporter.lines == []

    (tmp_path / conftest._SCRATCH_NAME).mkdir()
    assert conftest.scratch_directory_present(tmp_path) is not None

    # Present: says so and fails the run.
    failing = session(Reporter())
    conftest.pytest_sessionfinish(failing, 0)
    assert failing.exitstatus == 1
    assert len(Reporter.lines) == 1 and "exists at the end" in Reporter.lines[0]

    # An xdist worker leaves it to the controller.
    worker = session(Reporter(), worker=True)
    conftest.pytest_sessionfinish(worker, 0)
    assert worker.exitstatus == 0 and len(Reporter.lines) == 1

    # A run that already failed keeps its own status.
    interrupted = session(Reporter())
    interrupted.exitstatus = 2
    conftest.pytest_sessionfinish(interrupted, 2)
    assert interrupted.exitstatus == 2


def test_the_session_hook_prints_when_there_is_no_terminal_reporter(
        tmp_path, monkeypatch, capsys):
    import conftest
    monkeypatch.setattr(conftest, "_REPO_ROOT", tmp_path)
    (tmp_path / conftest._SCRATCH_NAME).mkdir()
    config = types.SimpleNamespace(
        pluginmanager=types.SimpleNamespace(get_plugin=lambda _: None))
    session = types.SimpleNamespace(config=config, exitstatus=0)
    conftest.pytest_sessionfinish(session, 0)
    assert "exists at the end" in capsys.readouterr().err
    assert session.exitstatus == 1


def test_a_file_or_a_missing_directory_is_not_the_scratch_directory(tmp_path):
    import conftest
    assert conftest.scratch_directory_present(tmp_path) is None
    (tmp_path / conftest._SCRATCH_NAME).write_text("x")
    assert conftest.scratch_directory_present(tmp_path) is None
