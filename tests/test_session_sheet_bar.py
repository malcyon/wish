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
