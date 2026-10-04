"""The banned words in `.claude/rules/words.md` stay out of the tracked files.

A term is banned in the scope `SCOPES` gives it: every tracked text file,
Markdown only, or `None` for a ban that depends on meaning and is left to review.
Citations (`#N (title)`, `WISH-N (title)`) are blanked first because a
citation quotes an issue's own title. While the sweep of the stem `refus` is
unfinished, `LIMITS_EVERY` and `LIMITS_MARKDOWN` hold the most matches each
file may still carry; a limit only ever goes down, and both dicts are deleted
when the sweep is done.
"""
import collections
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[2]
WORDS = ".claude/rules/words.md"

#: The scope of every bold term in the first cell of a row of the words table;
#: a term missing here fails `test_every_banned_term_has_a_scope`, so a new row
#: cannot be added without deciding where it is checked.
SCOPES = {
    "corpus": "every", "load-bearing": "every", "fair": "every",
    "blast radius": "every", "obviate": "every", "retarget": "every",
    "worth": "every", "census": "every",
    "refuse": "every", "refuses": "every", "refused": "every",
    "refusing": "every", "refusal": "every", "refusals": "every",
    # Code uses these as names: numpy `.shape`, `math.floor`, Qt's ElideRight.
    "shape": "markdown", "plain": "markdown", "floor": "markdown",
    "elide": "markdown",
    # The ban depends on meaning ("carry" is the 6502 flag, "bite" a monster
    # attack), so a reviewer reads for these.
    "carried": None, '"X follows Y"': None, '"bites"': None,
}
#: Self-rating phrases of the words table's sentence row; Markdown only.
PHRASES = ("says so out loud", "the important thing here",
           "narrower than it looks", "worse than it looks", "worse than I said",
           "the interesting kind", "earned its keep", "paid for itself",
           "was the right call")
#: The forms of the stem, whose identifiers are banned too (camelCase included).
STEM = {"refuse", "refuses", "refused", "refusing", "refusal", "refusals"}

#: Third-party text, the table itself and this file, which names the words.
EXCLUDED = (WORDS, "tests/suite/test_banned_words.py", "LICENSE",
            "THIRD_PARTY_LICENSES.md")
#: Python's own name for a socket error.
TOKEN_EXEMPT = ("ConnectionRefusedError",)
#: Lines a ban cannot reach, as (path, text of the line); none now.
ALLOWED_LINES: tuple[tuple[str, str], ...] = ()

# Most matches each file may carry until the sweep removes them (path: count).
LIMITS_EVERY: dict[str, int] = {
    "automap/amiga.py": 0,
    "automap/winuae.py": 0,
    "docs/125-bug-notes.md": 1,
    "docs/160-why-these-rules.md": 9,
    "tests/amiga/fakes.py": 0,
    "tests/amiga/test_amiga.py": 0,
    "tests/amiga/test_amiga68k.py": 0,
    "tests/amiga/test_amiga_adf.py": 0,
    "tests/amiga/test_amiga_savegame.py": 0,
    "tests/amiga/test_amigaacceptance.py": 0,
    "tests/amiga/test_amigaacceptance_accept.py": 0,
    "tests/amiga/test_amigaacceptance_camp.py": 0,
    "tests/amiga/test_amigaacceptance_campitems.py": 0,
    "tests/amiga/test_amigaacceptance_measure.py": 0,
    "tests/amiga/test_amigaacceptance_poolrest.py": 0,
    "tests/amiga/test_amigaacceptance_snapshot.py": 0,
    "tests/amiga/test_amigaacceptance_ssbjoin.py": 0,
    "tests/amiga/test_amigaacceptance_ssbsubstitute.py": 0,
    "tests/amiga/test_amigaacceptance_staged.py": 0,
    "tests/amiga/test_amigaacceptance_stageplace.py": 0,
    "tests/amiga/test_amigaacceptance_title.py": 0,
    "tests/amiga/test_amigaacceptance_titles.py": 0,
    "tests/amiga/test_amigabackstab.py": 0,
    "tests/amiga/test_amigabladesjournal.py": 0,
    "tests/amiga/test_amigacontainercheck.py": 0,
    "tests/amiga/test_amigadarknesssubstitute.py": 0,
    "tests/amiga/test_amigadrivecheck.py": 0,
    "tests/amiga/test_amigaeffectreader.py": 0,
    "tests/amiga/test_amigaglobal.py": 0,
    "tests/amiga/test_amigajournalgates.py": 0,
    "tests/amiga/test_amigalaterproof.py": 0,
    "tests/amiga/test_amigalaterslot.py": 0,
    "tests/amiga/test_amigalaterwrite.py": 0,
    "tests/amiga/test_amigaparty.py": 0,
    "tests/amiga/test_amigapipe.py": 0,
    "tests/amiga/test_amigapool.py": 0,
    "tests/amiga/test_amigaporsavegame.py": 0,
    "tests/amiga/test_amigaporsavegameboundaries.py": 0,
    "tests/amiga/test_amigaroutepool.py": 0,
    "tests/amiga/test_amigasavedisk.py": 0,
    "tests/amiga/test_amigasavegame.py": 0,
    "tests/amiga/test_amigashots.py": 0,
    "tests/amiga/test_amigastaging.py": 0,
    "tests/amiga/test_amigastagingsubstitute.py": 0,
    "tests/amiga/test_amigatarget.py": 0,
    "tests/amiga/test_fsuaegdb.py": 0,
    "tests/amiga/test_fsuaepor.py": 0,
    "tests/amiga/test_guardmaps.py": 0,
    "tests/amiga/test_installfsuae.py": 0,
    "tests/amiga/test_m68dis.py": 0,
    "tests/amiga/test_noencounters_winuae.py": 0,
    "tests/amiga/test_podamiga.py": 0,
    "tests/amiga/test_podderived.py": 0,
    "tests/amiga/test_podsavegame.py": 0,
    "tests/amiga/test_savegamelosses.py": 0,
    "tests/amiga/test_winuaeps1.py": 0,
    "tests/amiga/test_winvmguest.py": 0,
    "tests/amiga/test_winwish.py": 0,
    "tools/amiga/acceptance.py": 0,
    "tools/amiga/amigabladesjournal.py": 0,
    "tools/amiga/amigacontainercheck.py": 0,
    "tools/amiga/amigadrive.py": 0,
    "tools/amiga/amigadrivecheck.py": 0,
    "tools/amiga/amigalaterproof.py": 0,
    "tools/amiga/amigalaterslot.py": 0,
    "tools/amiga/amigalaterwrite.py": 0,
    "tools/amiga/fromamigapor.py": 0,
    "tools/amiga/fsuaegdb.py": 0,
    "tools/amiga/fsuaepor.py": 0,
    "tools/amiga/installfsuae.py": 0,
    "tools/amiga/m68dis.py": 0,
    "tools/amiga/m68discheck.py": 0,
    "tools/amiga/noencounters.py": 0,
    "tools/amiga/route.py": 0,
    "tools/amiga/route_camp.py": 0,
    "tools/amiga/route_pool.py": 0,
    "tools/amiga/route_silver_blades.py": 0,
    "tools/amiga/screens.py": 0,
    "tools/amiga/staging.py": 0,
    "tools/amiga/toamigapor.py": 0,
    "tools/amiga/winuae-lanecheck.ps1": 0,
    "tools/amiga/winuae-send.ps1": 0,
    "tools/amiga/winuae.ps1": 0,
    "tools/amiga/winuaepipe.py": 0,
    "tools/amiga/winuaesession.py": 0,
    "tools/amiga/winvmguest.py": 0,
    "tools/amiga/winwish.py": 0,
    "tools/c64/c64recordoperandsweep.py": 1,
}
LIMITS_MARKDOWN: dict[str, int] = {
    ".agents/skills/caveman/SKILL.md": 2,
    "CHANGELOG.md": 2,
    "docs/109-icon-choices.md": 2,
    "docs/114-party-strength.md": 2,
    "docs/118-debug-mode.md": 2,
    "docs/126-forum-findings.md": 6,
    "docs/128-guide-and-scripting.md": 4,
    "docs/144-decoding-a-new-title.md": 2,
    "docs/160-why-these-rules.md": 8,
    "docs/166-amiga-records-from-the-code.md": 2,
    "docs/192-curse-dual-class.md": 1,
    "docs/224-the-dos-thac0-lower-limit.md": 1,
    "docs/50-experiments.md": 8,
    "docs/88-map-files.md": 1,
    "docs/95-wish-cli.md": 1,
    "docs/97-editor.md": 1,
    "docs/98-automap-notes.md": 1,
}


def terms_in_table(text):
    found = []
    for line in text.splitlines():
        if line.startswith("| **"):
            found += re.findall(r"\*\*(.+?)\*\*", line.split("|")[1])
    return found


def _word(term):
    return re.escape(term).replace(r"\ ", "[ -]").replace(r"\-", "[ -]")


def pattern(terms):
    """The regex for `terms`: whole words, and words after an underscore (a
    word character, so `\\b` would pass a name joined by one); the stem's forms
    also after a lowercase letter (camelCase)."""
    plain = "|".join(_word(t) for t in terms)
    text = rf"(?i:(?:(?<![A-Za-z0-9])|_)(?:{plain})(?![a-z]))"
    if any(t in STEM for t in terms):
        forms = "|".join(sorted(t[len("refus"):] for t in STEM))
        text += rf"|[a-z]Refus(?:{forms})(?![a-z])"
    return text


def _blank_citations(text):
    """Blank every `#N (...)` and `WISH-N (...)` span, parentheses balanced
    across line breaks, keeping each newline so line numbers stay put."""
    out, i = [], 0
    for m in re.finditer(r"(?:#|WISH-)\d+ \(", text):
        if m.start() < i:
            continue
        depth, j = 1, m.end()
        while j < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[j], 0)
            j += 1
        out.append(text[i:m.start()])
        out.append(re.sub(r"[^\n]", " ", text[m.start():j]))
        i = j
    out.append(text[i:])
    return "".join(out)


def _allowed(path, line):
    return any(path == p and fragment in line for p, fragment in ALLOWED_LINES)


def scan(root, terms, pathspec=()):
    """Return `{path: [(line number, line), ...]}` for matches of `terms` in the
    tracked files of `root`, after the exemptions. `git grep` finds the lines;
    Python reads only those, because a regex over every line is ten times slower."""
    regex = pattern(terms)
    exclude = [f":(exclude){p}" for p in EXCLUDED]
    listed = subprocess.run(
        ["git", "grep", "-I", "-n", "-P", "-e", regex, "--", *(pathspec or ["."]), *exclude],
        cwd=root, capture_output=True, text=True, errors="replace", check=False)
    if listed.returncode not in (0, 1):
        raise RuntimeError(listed.stderr)
    candidates = collections.defaultdict(list)
    for row in listed.stdout.splitlines():
        path, number, _ = row.split(":", 2)
        candidates[path].append(int(number))
    compiled = re.compile(regex)
    found = {}
    for path, numbers in candidates.items():
        text = (pathlib.Path(root) / path).read_text(encoding="utf-8", errors="replace")
        lines = text.split("\n")
        for token in TOKEN_EXEMPT:
            text = text.replace(token, " " * len(token))
        blanked = _blank_citations(text).split("\n")
        hits = []
        for n in numbers:
            if not _allowed(path, lines[n - 1]):
                hits += [(n, lines[n - 1])] * len(compiled.findall(blanked[n - 1]))
        if hits:
            found[path] = hits
    return found


def _terms(scope):
    terms = [t for t, s in SCOPES.items() if s == scope]
    return terms + (list(PHRASES) if scope == "markdown" else [])


def _check(found, limits):
    over = {p: (len(h), limits.get(p, 0), h[0]) for p, h in found.items()
            if len(h) > limits.get(p, 0)}
    assert not over, "banned words past a file's limit (path: found, allowed, first):\n" + "\n".join(
        f"  {p}: {n}, {m}, line {first[0]}: {first[1].strip()[:100]}"
        for p, (n, m, first) in sorted(over.items()))


def test_every_banned_term_has_a_scope():
    table = set(terms_in_table((ROOT / WORDS).read_text(encoding="utf-8")))
    assert table - set(SCOPES) == set(), "give each new term of the table a scope in SCOPES"
    assert set(SCOPES) - table == set(), "a term in SCOPES is no longer in the table"


def test_banned_words_stay_out_of_every_tracked_text_file():
    _check(scan(ROOT, _terms("every")), LIMITS_EVERY)


def test_banned_words_stay_out_of_markdown():
    _check(scan(ROOT, _terms("markdown"), ["*.md"]), LIMITS_MARKDOWN)


def _repo(tmp_path, name, text):
    (tmp_path / name).write_text(text, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", name], cwd=tmp_path, check=True)
    return tmp_path


def test_the_scan_catches_the_stem_in_identifiers_and_ignores_the_exempt(tmp_path):
    text = ("walk_refused = 1\nLOSS_REFUSED = 2\nisRefused = 3\nrefusing = 4\n"
            "except ConnectionRefusedError: pass\n"
            "# See #5 (a title that says refused,\n#   across two lines) here\n"
            "AIABJREFUs = 5\nREFUSAL_X = 6\n")
    found = scan(_repo(tmp_path, "sample.py", text), _terms("every"))
    assert [n for n, _ in found["sample.py"]] == [1, 2, 3, 4, 9]
