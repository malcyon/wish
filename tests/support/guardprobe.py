"""The name the conftest guard's throwaway probe files carry, in one place.

`tests/suite/test_conftest_state_guard.py` writes a probe file into
`tests/suite/` and deletes it again; any other collection of this tree has to
skip that file, because it can be deleted between the directory listing and
the import.
"""

from __future__ import annotations

#: Every probe file's name starts with this, followed by a uuid4 hex.
PREFIX = "test_zzz_conftest_guard_probe_"

#: Matched with `fnmatch` against the whole path, so no separator appears in it.
IGNORE_GLOB = f"*{PREFIX}*.py"
