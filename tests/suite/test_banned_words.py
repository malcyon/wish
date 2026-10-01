"""`.claude/rules/words.md` bans words in the project's prose; this keeps new uses out.

The existing uses are counted per file in `bannedwords_baseline.py`. A count
may fall, never rise: a file above its count has gained a banned word, and a
file below it must have its line lowered so the baseline keeps shrinking.
The scanner is `tools/suite/bannedwords.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from bannedwords_baseline import BASELINE

from tools.suite import bannedwords
from tools.suite.bannedwords import ALLOWED, ROWS, UNCHECKED, scan, scan_text

ROOT = Path(__file__).resolve().parents[2]


def _rows(text, suffix):
    return sorted({h.row for h in scan_text(text, suffix)})


def test_no_banned_word_beyond_the_baseline():
    hits, _used = scan(ROOT, return_used=True)
    found = bannedwords.counts(hits)
    grew, shrank = [], []
    for path, rows in found.items():
        for row, n in rows.items():
            allowed = BASELINE.get(path, {}).get(row, 0)
            if n > allowed:
                where = [h for h in hits if h.path == path and h.row == row]
                grew.append(
                    f"{path}: {row} {n} > {allowed}\n    "
                    + "\n    ".join(f"{h.line}: {h.excerpt}" for h in where)
                )
    for path, rows in BASELINE.items():
        for row, allowed in rows.items():
            n = found.get(path, {}).get(row, 0)
            if n < allowed:
                shrank.append(f"{path}: {row} {n} < {allowed}")
    assert not grew, "banned words added (say it another way, or quote it in backticks):\n" + "\n".join(grew)
    assert not shrank, (
        "the baseline is higher than the hits; lower or delete these lines in "
        "tests/suite/bannedwords_baseline.py:\n" + "\n".join(shrank)
    )


def test_every_words_md_row_has_a_pattern_or_a_reason():
    table = [
        line for line in (ROOT / ".claude/rules/words.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("| ") and not line.startswith("| instead of")
    ]
    in_table = set()
    for line in table:
        first_cell = line.split("|")[1]
        in_table.update(t.strip('"') for t in re.findall(r"\*\*(.+?)\*\*", first_cell))
    covered = {t for row in ROWS for t in row.terms}
    for terms, _reason in UNCHECKED.values():
        covered.update(t.strip('"') for t in terms)
    assert in_table == covered, (
        f"words.md has {sorted(in_table - covered)} with no row; "
        f"bannedwords.py has {sorted(covered - in_table)} words.md does not"
    )


def test_every_unchecked_row_has_a_reason():
    assert all(reason for _terms, reason in UNCHECKED.values())


def test_every_exemption_has_a_reason():
    assert all(len(entry) == 4 and entry[3] for entry in ALLOWED)
    assert all(why for row in ROWS for _p, why in row.context_ok)


def test_no_allowed_quotation_is_stale():
    _hits, used = scan(ROOT, return_used=True)
    assert [a for a in ALLOWED if a not in used] == []


def test_the_baseline_names_only_rows_and_files_that_exist():
    names = {r.name for r in ROWS}
    for path, rows in BASELINE.items():
        assert (ROOT / path).exists(), path
        assert set(rows) <= names, path


# -- the scanner, on strings -------------------------------------------------

@pytest.mark.parametrize("text,suffix,row", [
    ("# the shape of the fix\n", ".py", "shape"),
    ('def f():\n    """A plain statement."""\n', ".py", "plain"),
    ('x = f"carries it across {y}"\n', ".py", "carried"),
    ("The census found three.\n", ".md", "census"),
    ("This is worth doing.\n", ".md", "worth"),
    ("<widget><string>The corpus</string></widget>\n", ".ui", "corpus"),
    ("note: it is not carried\n", ".yml", "carried"),
    ("# the refusal of the save\n", ".py", "refusal"),
    ("Two refusals happened.\n", ".md", "refusal"),
    ("It is smaller than it looks.\n", ".md", "rating"),
    ("To note that is useful.\n", ".md", "rating"),
])
def test_a_banned_word_in_prose_is_found(text, suffix, row):
    assert row in _rows(text, suffix)


def test_refusal_covers_the_noun_and_its_plural_but_not_the_verb():
    assert _rows("# a refusal\n", ".py") == ["refusal"]
    assert _rows("# two refusals\n", ".py") == ["refusal"]
    assert _rows("# it refused, then refuses\n", ".py") == []


def test_refusal_has_no_exemption():
    for text, suffix in [
        ("x = 'refusal'\n", ".py"),
        ("The `refusal` key.\n", ".md"),
        ("```\nrefusal\n```\n", ".md"),
        ('{"refusal": 1}\n', ".json"),
        ("See #137 (A refusal of the save) for it.\n", ".md"),
        ("# embrassed-energy refusal.zip\n", ".py"),
    ]:
        assert _rows(text, suffix) == ["refusal"], text


def test_refusal_and_census_are_found_in_identifiers():
    assert _rows("class GuestRefusal:\n    pass\n", ".py") == ["refusal"]
    assert _rows("REFUSALS = 1\n", ".py") == ["refusal"]
    assert _rows("def run_census():\n    pass\n", ".py") == ["census"]
    assert _rows("def shape_of():\n    pass\n", ".py") == []


@pytest.mark.parametrize("text,suffix", [
    ("x = tf.setTextElideMode\n", ".py"),
    ("class DosShape:\n    pass\n", ".py"),
    ("# ElideRight is the Qt name\n", ".py"),
    ("The `shape` field.\n", ".md"),
    ("```\nthe shape of it\n```\n", ".md"),
    ("See #137 (The shape of the fix) for it.\n", ".md"),
    ("Download embrassed-energy.zip now.\n", ".md"),
    ("x = 'plain-padlock'\n", ".py"),
    ("# a 2d6 bite and a poison bite\n", ".py"),
    ("# the combat floor's colour\n", ".py"),
    ("# the carry flag is set\n", ".py"),
    ("# a developer's note that escaped\n", ".py"),
    ("https://example.com/shape/worth\n", ".md"),
])
def test_an_established_name_or_quotation_is_accepted(text, suffix):
    assert scan_text(text, suffix) == []


def test_a_context_exemption_is_what_accepts_a_monster_bite():
    from tools.suite.bannedwords import Row
    bites = next(r for r in ROWS if r.name == "bites")
    bare = Row("bites", bites.terms, bites.pattern.pattern)
    assert bare.pattern.search("a 2d6 bite")
    assert bites.context_ok


def test_a_file_name_with_refusal_is_found():
    assert [h.row for h in bannedwords._path_hits("tests/editor/test_convertrefusal.py")] == ["refusal"]
    assert bannedwords._path_hits("tests/editor/test_convert.py") == []


def test_the_scanner_finds_a_new_use_in_a_tracked_file(tmp_path):
    (tmp_path / "a.py").write_text("# fine\n# the shape of it\n", encoding="utf-8")
    hits = scan(tmp_path, ["a.py"])
    assert [(h.path, h.line, h.row) for h in hits] == [("a.py", 2, "shape")]


# -- tools/wishagent.py ------------------------------------------------------

def _wishagent(monkeypatch, tmp_path, body, title="A title"):
    from tools import wishagent

    def no_network(*args, **kwargs):
        raise AssertionError("posted despite a banned word")

    monkeypatch.setattr(wishagent, "_api_call", no_network)
    body_file = tmp_path / "body.md"
    body_file.write_text(body, encoding="utf-8")
    return wishagent, body_file


@pytest.mark.parametrize("command", ["create", "comment", "edit", "edit-comment"])
def test_wishagent_refuses_a_banned_word_before_posting(monkeypatch, tmp_path, capsys, command):
    wishagent, body_file = _wishagent(monkeypatch, tmp_path, "The shape of the fix.\n")
    argv = {
        "create": ["create", "--title", "T", "--body-file", str(body_file)],
        "comment": ["comment", "5", "--body-file", str(body_file)],
        "edit": ["edit", "5", "--body-file", str(body_file)],
        "edit-comment": ["edit-comment", "5", "--body-file", str(body_file)],
    }[command]
    assert wishagent.main(argv) == 1
    assert "shape" in capsys.readouterr().err


def test_wishagent_checks_the_title_and_a_close_comment(monkeypatch, tmp_path, capsys):
    wishagent, body_file = _wishagent(monkeypatch, tmp_path, "Fine body.\n")
    assert wishagent.main(["create", "--title", "A plain title", "--body-file", str(body_file)]) == 1
    body_file.write_text("This is worth it.\n", encoding="utf-8")
    assert wishagent.main(["close", "5", "--comment-file", str(body_file)]) == 1
    assert wishagent.main(["reopen", "5", "--comment-file", str(body_file)]) == 1


def test_wishagent_lets_a_quoted_word_through(monkeypatch, tmp_path):
    wishagent, body_file = _wishagent(monkeypatch, tmp_path, "The `shape` field and #5 (A plain title).\n")
    assert wishagent.banned_word_hits(body_file.read_text(encoding="utf-8")) == []
