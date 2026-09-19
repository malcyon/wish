"""A character who owns nothing still gets its sheet read (#280).

`Session.character_sheet` waited for the row-24 bar
`VIEW:ITEMS EXIT` -- the bar a character carrying something gets. A
character with an empty inventory gets `VIEW:EXIT`, with no `ITEMS` on it
because there is nothing to list, and the wait timed out on a sheet that was
already drawn, correctly, on screen.

Nothing here needs an emulator: `FakeSession` is a `Session` whose `screen`
is one fixed row-24 string and whose `select_bar`/`select_party`/`leave_sheet`
are stubbed to succeed at once, so the only thing under test is the
comparison against `SHEET_BAR` inside `character_sheet` itself.
"""

import pytest
from conftest import load_tools_module

S = load_tools_module("session")
Session = S.Session


class FakeScreen:
    def __init__(self, bar: str, name: str = "BRUTUS"):
        self.bar = bar
        self.name = name

    def row(self, r: int) -> str:
        if r == 24:
            return self.bar
        if r == 1:
            return self.name
        return ""

    def rows(self) -> list[str]:
        return [self.row(r) for r in range(25)]


class FakeSession(Session):
    """Only `character_sheet`'s own logic runs; everything around it is a
    single fixed answer."""

    def __init__(self, bar: str):
        self._screen = FakeScreen(bar)

    def screen(self):
        return self._screen

    def select_bar(self, label: str, row: int = 24, timeout: float = 30.0) -> bool:
        return True

    def select_party(self, index: int, timeout: float = 25.0) -> bool:
        return True

    def leave_sheet(self, tries: int = 3) -> bool:
        return True


def test_a_character_with_items_still_reads():
    """The bar this always worked for keeps working."""
    sess = FakeSession("VIEW:ITEMS EXIT")
    lines = sess.character_sheet(timeout=1.0)
    assert lines is not None
    assert lines[0].strip() == "BRUTUS"


def test_a_character_who_owns_nothing_reads_too():
    """`VIEW:EXIT`, no `ITEMS` on it -- the bar this ticket is about."""
    sess = FakeSession("VIEW:EXIT")
    lines = sess.character_sheet(timeout=1.0)
    assert lines is not None
    assert lines[0].strip() == "BRUTUS"


# -- Silver Blades' sheet bar has no `VIEW:` on it either (#540) -------------
#
# Two walks measured Silver Blades' own sheet bar as `EXIT` followed by 36
# spaces, nothing else on the row:
# `cited/52/walk-amigatoc64-ssb/ssbcheck2/ssbcheck2.jsonl` and
# `cited/52/walk-dostoc64-ssb/ssbcheck.jsonl`, with a screenshot
# `02-sheet-0.png` in one of those directories.  `Session.character_sheet`
# polls the base `sheet_is_up`, which looks for `VIEW:` and never finds it, so
# every Silver Blades sheet read timed out.  `SSBSession` had overridden
# `game`, `handle_prompt`, `boot`, `ANY_KEY` and `QUIET` and nothing about the
# sheet.

SSB = load_tools_module("ssbwarp")
Curse = load_tools_module("curserun")


class SSBFakeSession(SSB.SSBSession):
    """`SSBSession`'s own `character_sheet` path, everything around it fixed.

    Same shape as `FakeSession` above, over the real driver class instead of
    the base one -- loading the real class is what would have caught this
    ticket, the way `tests/test_session_indoors.py:142` did for #426."""

    def __init__(self, bar: str):
        self._screen = FakeScreen(bar)
        self._last_prompt = 0.0

    def screen(self):
        return self._screen

    def select_bar(self, label: str, row: int = 24, timeout: float = 30.0) -> bool:
        return True

    def select_party(self, index: int, timeout: float = 25.0) -> bool:
        return True

    def leave_sheet(self, tries: int = 3) -> bool:
        return True


def test_a_silver_blades_sheet_reads_instead_of_timing_out():
    """`EXIT` alone -- the bar this ticket is about."""
    sess = SSBFakeSession("EXIT".ljust(40))
    lines = sess.character_sheet(timeout=1.0)
    assert lines is not None
    assert lines[0].strip() == "BRUTUS"


def test_the_base_class_still_does_not_recognise_silver_blades_bar():
    """The control: the same `EXIT`-only row through the base `Session`
    (no override) still times out, so the difference above is the override
    and not something else about the fake."""
    sess = FakeSession("EXIT".ljust(40))
    lines = sess.character_sheet(timeout=1.0)
    assert lines is None


@pytest.mark.parametrize("module_name, class_name", [
    ("curserun", "CurseSession"),
    ("ssbwarp", "SSBSession"),
])
def test_every_per_title_sheet_bar_override_answers_exit_not_the_world_bar(
        module_name, class_name):
    """Both titles share one sheet bar: `EXIT`, and no `ENCAMP`."""
    module = load_tools_module(module_name)
    cls = getattr(module, class_name)
    sess = cls.__new__(cls)
    assert sess.sheet_is_up(FakeScreen("EXIT".ljust(40))) is True
    assert sess.sheet_is_up(
        FakeScreen("MOVE VIEW CAST AREA ENCAMP SEARCH LOOK")) is False
