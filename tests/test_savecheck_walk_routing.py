"""A walked step routes through whatever the game puts up next, always (#275).

`tools/savecheck.py`'s walk loop only ran `answer_bars` -- the function that
presses through a room description, `PRESS <RETURN>`, a load and a `YES NO`
back to the world bar -- when `--route` was passed.  The training hall
answers a step with exactly that sequence and nothing had asked for routing,
so a run under `#257 (A DOS save made in the training hall converts as though
the party were in New Phlan)` read `moved: false, status: null` once every
118 seconds, four tries in a row, on a game that was only waiting for an
answer.

`walk_step_routed` is what the walk loop now calls after every move, with no
flag gating it.  Nothing here needs an emulator: `FakeSession` hands back a
fixed sequence of screens, one call to `.screen()` at a time.
"""

from conftest import load_tools_module

savecheck = load_tools_module("savecheck")
walk_step_routed = savecheck.walk_step_routed
Log = savecheck.Log


class FakeScreen:
    def __init__(self, row24: str):
        self.row24 = row24

    def row(self, r: int) -> str:
        return self.row24 if r == 24 else ""


class FakeKeyboard:
    def __init__(self):
        self.sent: list[str] = []

    def key(self, name, hold=0.0, gap=0.0):
        self.sent.append(name)


class FakeSession:
    """The training hall's own sequence: a room description already dealt
    with, `PRESS <RETURN>` twice (a slow load), then one `YES NO`, then the
    world bar back."""

    def __init__(self):
        self.rows = [
            "PRESS <RETURN> OR BUTTON TO CONTINUE",
            "PRESS <RETURN> OR BUTTON TO CONTINUE",
            "TRAIN CHARACTER?         YES  NO",
            "MOVE VIEW CAST AREA ENCAMP SEARCH LOOK",
        ]
        self.kbd = FakeKeyboard()
        self.selected: list[str] = []
        self.prompts_handled = 0

    def handle_prompt(self, s=None) -> bool:
        self.prompts_handled += 1
        return False

    def screen(self):
        row = self.rows.pop(0) if len(self.rows) > 1 else self.rows[0]
        return FakeScreen(row)

    def select_bar(self, label, row=24, timeout=30.0):
        self.selected.append(label)
        return True


class FakeLog(Log):
    def __init__(self):
        self.said: list[str] = []

    def say(self, *a) -> None:
        self.said.append(" ".join(str(x) for x in a))


def test_a_walked_step_is_routed_through_press_and_yes_no_to_the_world_bar():
    sess = FakeSession()
    outcome = walk_step_routed(sess, FakeLog(), "NO")
    assert outcome == "world"
    assert sess.selected == ["NO"]
    assert sess.prompts_handled >= 1
