"""One key leaves a Gold Box command bar, and it is not `EXIT`.

`#444 (A driven session cannot leave a Curse or Silver Blades character sheet,
so each sheet costs its own boot)`.  Reading six characters' sheets used to
cost six boots on the later titles, at roughly two and a half minutes each,
because the sheet's `EXIT` is on a command bar rather than in a list and the
press did not take.

The finding these tests hold in place: **every command bar in all three C64
titles is driven by one key interpreter, and it reads PETSCII `$5F` -- the
`<-` key at the top left of a C64 keyboard -- as "leave, wherever the
highlight is".**  `Session.leave_sheet` sends that instead of walking to
`EXIT`, and on 2026-09-08 that read four sheets in one boot on Curse and four
on Silver Blades, 6 leaves out of 6, each landing on `VIEW WHICH CHARACTER?`
inside 0.9 seconds (`work/issue444/curse-proof`, `work/issue444/ssb-proof`).

Two halves, and only one of them needs the game:

* the interpreter itself, read out of each title's own `LIBRARY`.  Those
  skip without the player's disks, which CI has none of.
* what `Session.leave_sheet` sends, which is checked against a stand-in and
  runs everywhere.  Those are the ones that would have caught the old
  behaviour: the old method never sent a key through the KERNAL buffer at all.
"""

import pathlib

import pytest

from tools import gamedisks, portraitdraw, sheetexit
from tools import session as por

#: The three titles, and the one measurement each has to agree on.
TITLES = ("pool-of-radiance", "curse-of-the-azure-bonds",
          "secret-of-the-silver-blades")

#: Where the interpreter sits in each title, measured on 2026-09-08 off the
#: player's own disks.  A test that only said "it is somewhere" would pass on
#: a file that had moved out from under us.
INTERPRETER_AT = {
    "pool-of-radiance": 0x306D,
    "curse-of-the-azure-bonds": 0x31F1,
    "secret-of-the-silver-blades": 0x46F1,
}


def library_for(title: str) -> bytes:
    root = gamedisks.find(title)
    if root is None or not pathlib.Path(root).is_dir():
        pytest.skip(f"no {title} disks here; set $POR_DISKS")
    _side, data = portraitdraw.read_named(
        portraitdraw.sides_of(title, None), b"LIBRARY")
    if data is None:
        pytest.skip(f"no LIBRARY on any {title} side")
    return data


# --- the interpreter, out of the game ----------------------------------------

@pytest.mark.parametrize("title", TITLES)
def test_one_interpreter_reads_every_command_bar(title):
    """Exactly one, or the shape this rests on is not the shape it found.

    Three of three titles, one hit each.  A second match would mean the
    prologue is not the discriminator it is being used as, and every address
    below it would be a guess.
    """
    got = sheetexit.read_library(library_for(title))
    assert got["interpreters"] == 1
    assert got["interpreter"] == INTERPRETER_AT[title]


@pytest.mark.parametrize("title", TITLES)
def test_the_back_arrow_leaves_and_return_selects(title):
    """`$5F` reaches the tail that returns `$FF`; `$0D` reaches the other one.

    Named from the code rather than assumed: the select tail is
    `LDX <highlight> / LDA <ids>,X / SEC / RTS` and the leave tail is
    `LDA #$FF / SEC / RTS`, and this asserts which key branches to which.
    """
    got = sheetexit.read_library(library_for(title))
    assert got["cancel_key"] == por.BAR_CANCEL == 0x5F
    assert got["select_key"] == 0x0D


@pytest.mark.parametrize("title", TITLES)
def test_the_sheet_leaves_on_a_negative_answer(title):
    """`BPL <carry on> / RTS` closes the sheet's loop.

    This is what turns the leave tail's `$FF` into an exit, and without it
    `$5F` would only redraw the bar.  Two bytes and a third: it is looked for
    in the forty after the menu table is handed over, so a title that closed
    its loop some other way would fail here rather than be assumed into
    agreement.
    """
    got = sheetexit.read_library(library_for(title))
    loop = got["loop"]
    assert loop["rts"] == loop["bpl"] + 2


@pytest.mark.parametrize("title", TITLES)
def test_the_menu_table_is_found_without_knowing_its_label(title):
    """Pool of Radiance's table carries a `VIEW:` the later two dropped.

    The count byte is five bytes further from `ITEMS` there than in Curse, so
    a reader that stepped back a fixed distance would find Pool of Radiance's
    table and neither of the others, or the reverse.
    """
    got = sheetexit.read_library(library_for(title))
    assert got["menu_table"] is not None
    assert got["table_pushed_at"] is not None
    # The `LDX #lo / LDY #hi / JSR` is seven bytes, and the `LDA abs` after it
    # is where the sheet reads back the index it remembers between visits.
    assert got["remembered_index"] is not None


def test_the_later_titles_put_the_reader_in_the_same_place():
    """Curse and Silver Blades relocate `LIBRARY` alike; the addresses differ.

    The interpreter moved `$306D` -> `$31F1` -> `$46F1` across the three, which
    is no constant at all -- so a reader that took one title's address and
    added a delta would be wrong on both the others.  That is the reason
    `tools/sheetexit.py` finds it by shape.
    """
    seen = {t: sheetexit.read_library(library_for(t))["interpreter"]
            for t in TITLES}
    assert len(set(seen.values())) == 3, seen


# --- what the driver sends ---------------------------------------------------

class FakeScreen:
    def __init__(self, row24: str):
        self._row = row24

    def row(self, _n: int) -> str:
        return self._row.ljust(40)


class FakeSession:
    """Enough of `Session` for `leave_sheet`, and it counts what it was sent.

    `row24` is a list of what row 24 reads on each successive look, so a test
    can say "the bar changed after the key" or "it never did".
    """

    def __init__(self, rows):
        self.rows = list(rows)
        self.kernal: list[int] = []
        self.bars: list[str] = []
        self.moves = 0

    def screen(self):
        row = self.rows[0] if len(self.rows) == 1 else self.rows.pop(0)
        return FakeScreen(row)

    def press_kernal(self, code: int) -> None:
        self.kernal.append(code)

    def select_bar(self, label: str, **_kw) -> bool:
        self.bars.append(label)
        return False

    def cancel_bar(self, timeout: float = 1.0, row: int = 24) -> bool:
        """The real method, with a timeout a test can wait out.

        Delegating rather than faking it keeps `leave_sheet` and `cancel_bar`
        under one test: a `leave_sheet` that stopped calling it would fail
        below rather than pass against a stand-in that agreed with it.

        **The 1.0 second is deliberately not the real 8.0**, and it is what
        keeps the fallback test near two seconds instead of near sixteen:
        `leave_sheet` calls `self.cancel_bar()` with no timeout, so Python
        resolves this stand-in's default.  Matching it to the base class
        would slow that test by fourteen seconds with nothing failing to say
        why.
        """
        return por.Session.cancel_bar(self, timeout=timeout, row=row)

    def leave_move(self, *_a, **_kw) -> None:
        self.moves += 1

    def log(self, *_a) -> None:
        pass


def test_leave_sheet_sends_the_cancel_key_and_stops_there():
    """The sheet's bar gives way, so nothing else is tried.

    Without the fix this fails at the first assertion: the old method sent no
    KERNAL key at all, it walked the highlight to `EXIT` and pressed Return.
    """
    sess = FakeSession(["ITEMS TRADE DROP EXIT", "VIEW WHICH CHARACTER?"])
    assert por.Session.leave_sheet(sess) is True
    assert sess.kernal == [por.BAR_CANCEL]
    assert sess.bars == []          # `EXIT` was never asked for
    assert sess.moves == 0


def test_leave_sheet_falls_back_when_the_bar_does_not_give_way():
    """A bar that ignores the cancel key still gets the old route.

    The fallback is what makes this change safe on a screen nobody has
    measured: `select_bar("EXIT")` is asked for exactly as it was before.
    """
    sess = FakeSession(["ITEMS TRADE DROP EXIT"])
    assert por.Session.leave_sheet(sess, tries=2) is False
    assert sess.kernal == [por.BAR_CANCEL, por.BAR_CANCEL]
    assert sess.bars == ["EXIT", "EXIT"]
    assert sess.moves == 2


def test_cancel_bar_answers_the_bar_rather_than_the_keypress():
    """A key that was sent is not a command that took.

    Three `EXIT` presses came back `True` with the sheet still up, which is
    what `#444` was filed about, so this asserts the *bar* moved.
    """
    unchanged = FakeSession(["ITEMS TRADE DROP EXIT"])
    assert por.Session.cancel_bar(unchanged, timeout=1.0) is False
    changed = FakeSession(["EXIT", "VIEW WHICH CHARACTER?"])
    assert por.Session.cancel_bar(changed, timeout=1.0) is True


# --- the parser, without the game --------------------------------------------

def test_the_key_chain_stops_at_the_joystick():
    """`CMP #imm / BEQ` up to `LDA $03F0`, and not one test past it.

    The interpreter tests five joystick values in the same shape immediately
    afterwards, and reading those as keys would name `$0F` as a key nobody can
    press.
    """
    body = (bytes.fromhex("a2048e957fca")          # the prologue
            + bytes.fromhex("c90df030")            # CMP #$0D / BEQ +$30
            + bytes.fromhex("c95ff037")            # CMP #$5F / BEQ +$37
            + sheetexit.JOYSTICK                   # LDA $03F0
            + bytes.fromhex("c90ff019"))           # the joystick's own tests
    chain = sheetexit.key_chain(body, 0x0800, 0x0806)
    assert [k for _at, k, _t in chain] == [0x0D, 0x5F]


class BlindSession(FakeSession):
    """A session whose first screen reads never answer.

    `Session.screen()` gives `None` for a bitmap, for a monitor that would
    not read, and for a screen whose base could not be located.
    """

    def __init__(self, rows: list[str], blind: int) -> None:
        super().__init__(rows)
        self.blind = blind
        self.reads = 0

    def screen(self):
        self.reads += 1
        if self.reads <= self.blind:
            return None
        return super().screen()


def test_an_unreadable_screen_is_not_a_bar_giving_way():
    """`cancel_bar` says no when it never read the bar it is watching.

    Without the fix this passes for the wrong reason: the before-image is
    `None`, the first row that does read back is not `None`, and an unchanged
    bar answers `True` -- the false success `#444` was filed about, one layer
    down.  The key is not sent either, because there is nothing to compare a
    change against.
    """
    sess = BlindSession(["ITEMS TRADE DROP EXIT"], blind=99)
    assert por.Session.cancel_bar(sess, timeout=1.0) is False
    assert sess.kernal == []


def test_a_screen_that_reads_on_the_second_try_still_answers():
    """One unreadable probe is retried rather than taken as a before-image."""
    sess = BlindSession(["ITEMS TRADE DROP EXIT", "VIEW WHICH CHARACTER?"], blind=1)
    assert por.Session.cancel_bar(sess, timeout=4.0) is True
    assert sess.kernal == [por.BAR_CANCEL]
