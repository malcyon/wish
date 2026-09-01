from __future__ import annotations

import subprocess
import sys


def test_generated_ui_is_current():
    """Fail if UI files were changed but tools/genui.py wasn't run."""
    result = subprocess.run([sys.executable, "tools/genui.py", "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, f"Generated UI files are out of date: {result.stdout}\nRun tools/genui.py to update them."

#: Each pair is a generator and the one file under docs/ it writes. Limited
#: to generators that run from code already in the repository -- gendocs.py
#: reads goldbox/layout.py, genmemory.py reads goldbox/memory.py, genlevels.py
#: reads goldbox/levels.py, and none of the three needs a game disk, so this
#: test behaves the same with or without one.
#:
#: tools/genitems.py, genmaps.py, genspells.py and gentemplates.py also write
#: into docs/, but each reads a game disk to do it. Checking them here would
#: make a machine with no disks skip instead of pass, which is not the same
#: thing -- so they are deliberately left out; a maintainer regenerates them
#: by hand when the disk-derived tables need it.
GENERATED_DOCS = (
    ("tools/gendocs.py", "docs/20-character-record.md"),
    ("tools/genmemory.py", "docs/41-memory-regions.md"),
    ("tools/genlevels.py", "docs/89-level-tables.md"),
)


def test_generated_docs_are_current():
    """Fail if a generated doc was hand-edited, or its generator not re-run.

    Diffs only the files the three generators above write, not the whole of
    docs/ -- a hand-written document left uncommitted must not fail this.
    """
    for script, _ in GENERATED_DOCS:
        subprocess.run([sys.executable, script], check=True)

    for script, doc in GENERATED_DOCS:
        result = subprocess.run(["git", "diff", "--exit-code", "--", doc],
                                capture_output=True, text=True)
        assert result.returncode == 0, (
            f"{doc} is out of date with its generator. Run {script} and "
            f"commit the result:\n{result.stdout}")
