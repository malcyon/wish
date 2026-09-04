from __future__ import annotations

"""The repository must not carry the game.

`CLAUDE.md` forbids committing Pool of Radiance's code, art, music, manuals or
data files. That rule was broken once by accident -- four fixtures, one of them
6502 machine code -- because a test fixture does not feel like a copy while you
are adding it. It is one, so this checks.

The check runs against `git ls-files`, not the working tree: what matters is
what is committed. Untracked scratch under `work/` is ignored and fine.
"""


import pathlib
import re
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Extensions the game's content would arrive in. `.bin` is deliberately not
#: here -- see `ALLOWED_FIXTURES`, which is stricter.
FORBIDDEN_SUFFIXES = {
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
#: was moved to `work/captures/` and the combat tests build an arena instead. Several capture states no disk still holds, so they
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
        f"repository' in CLAUDE.md: {bad}")


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
    assert not bad, f"Hardcoded developer paths found in string literals: {bad}"



# -- citations into gitignored scratch ---------------------------------------

#: How far either side of a citation to look for the words that mark it lost.
#: Three lines covers a citation wrapped across a sentence without reaching the
#: next paragraph, which would let an unrelated "lost" excuse it.
LOST_WINDOW = 3

#: Wording that marks a citation as pointing at something no longer there.
LOST = ("lost", "not currently present", "absent from", "no longer")

#: Places where `work/reports/...` is where a tool *writes*, not where evidence
#: *is*. These are not citations and the rule does not apply to them. Keep this
#: short: a new entry is a claim that the path is an output, and if it is really
#: a citation it belongs in `docs/` instead.
OUTPUT_PATHS = {
    "tools/iconsheet.py",
    "tools/shotwindow.py",
    "docs/109-icon-choices.md",       # the command line that runs iconsheet.py
}

CITING = ("docs", "automap", "goldbox", "editor", "wish", "ui", "tools")


def test_no_citation_points_at_a_write_up_that_is_not_there(files):
    """A `work/reports/` citation is a real file, or says it is lost.

    `work/` is gitignored, so a permanent citation into it survives exactly as
    long as one developer's scratch directory. `work/reports/` held 32
    write-ups and all 32 went when it was deleted, taking the evidence for 80
    citations across 29 documents with them (#136). `CLAUDE.md` now puts a
    write-up's permanent home in `docs/`; this is what stops the rule being
    forgotten.

    **Scoped to `work/reports/` on purpose.** There are ~300 other references
    to working directories -- `work/p60/`, `work/drive/`, the emulator's
    scratch -- and those are records of where something was *done*, not
    citations of reasoning. Widening this test to all of `work/` would fail
    306 times today and is its own piece of work, not this one's.
    """
    bad = []
    for rel in files:
        if rel.parts[0] not in CITING or rel.suffix not in (".md", ".py"):
            continue
        # `as_posix()`, not `str()`: on Windows a tracked path renders as
        # `tools\\iconsheet.py` and never matches the allowlist, which is how
        # this test went red on both Windows jobs and green on Linux.
        if rel.as_posix() in OUTPUT_PATHS:
            continue
        lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if "work/reports/" not in line:
                continue
            window = " ".join(lines[max(0, i - LOST_WINDOW):
                                    i + LOST_WINDOW + 1]).lower()
            if any(word in window for word in LOST):
                continue
            for cited in re.findall(r"work/reports/[A-Za-z0-9._/-]+", line):
                if not (ROOT / cited.rstrip(".,;:`)")).exists():
                    bad.append(f"{rel.as_posix()}:{i + 1}  {cited}")
    assert not bad, (
        "these cite a write-up under gitignored `work/reports/` without saying "
        "it is lost, and the file is not there:\n  " + "\n  ".join(bad)
        + "\n\nA write-up's permanent home is `docs/` -- see "
          "`.claude/rules/documentation.md`.")


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
    `goldbox/dos.py` quietly points at nothing.

    Scoped to tracked `.md` and `.py` files, and to the two paths the split
    created, because those are the ones with no other guard.
    """
    bad = []
    for rel in files:
        if rel.suffix not in (".md", ".py") or rel.parts[0] == "work":
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

    # The rules are meant to be in the imported file, not copied back here.
    assert "## Words to avoid" not in text, (
        f"the rules belong in {IMPORTED}; CLAUDE.md carries only what is true "
        "of Claude Code alone.")
    assert "## Words to avoid" in (ROOT / IMPORTED).read_text(encoding="utf-8"), (
        f"{IMPORTED} no longer holds the rules.")
