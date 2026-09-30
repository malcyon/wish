"""Getting a Curse of the Azure Bonds save disk loaded in a driven session.

Three things went wrong on the way to `#291 (A Curse save disk will not load
through the game's own front end in a pooled session, so no C64 Curse party
can be got in)`, and the engine printed the same sentence --
`UNABLE TO LOAD SAVED GAME.` -- for all three. These are the two that can be
proved without an emulator, plus the disk repair.
"""

from __future__ import annotations

import contextlib
import os
import sys
import time

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))

from support.partymenu import (  # noqa: E402
    MODIFY,
    ONWARD,
    SIDE_2,
    WORLD_BAR,
    bar_screen,
    menu_screen,
)

from goldbox.d64 import D64  # noqa: E402
from tools.c64 import session as por  # noqa: E402
from tools.curse_of_the_azure_bonds import curseload  # noqa: E402


class FakeMonitor:
    """A monitor connection that records when it is open.

    The real one stops the emulated machine for as long as it is open, which
    is the whole point of the test below: a `sleep` inside the block passes
    no emulated cycles at all.
    """

    def __init__(self, log):
        self.log = log

    def __enter__(self):
        self.log.append("machine stopped")
        return self

    def __exit__(self, *exc):
        self.log.append("machine running")


class FakeText:
    def __init__(self, log):
        self.log = log

    def sendall(self, data):
        self.log.append(data.decode().strip())

    def recv(self, n):
        raise TimeoutError


class AttachSession(por.Session):
    """Enough of a session for `attach`, with every step in order."""

    def __init__(self, tmp_path, monkeypatch):
        self.here = str(tmp_path)
        self.events: list[str] = []
        self.text = FakeText(self.events)
        self.attached = ""
        monkeypatch.setattr(time, "sleep",
                            lambda s: self.events.append(f"sleep {s}"))

    def mon(self, timeout: float = 5.0):
        return FakeMonitor(self.events)

    @staticmethod
    def log(*a) -> None:
        pass


def test_the_wait_after_a_disk_goes_in_happens_while_the_machine_is_running(
        tmp_path, monkeypatch):
    """A disk swap has to be followed by time the *drive* can count.

    You attach a Curse save disk, take `LOAD SAVED GAME`, and the game says
    `UNABLE TO LOAD SAVED GAME.` with the right disk in the drive. The 1541
    answers `74, DRIVE NOT READY` for about a second of its own clock after an
    image is attached -- that is how it says the disk changed -- and Curse
    reads that number straight off the command channel (`LIBRARY $402D`) and
    turns it into the refusal.

    `attach` used to do all its waiting inside a monitor connection, and the
    machine is stopped for as long as one is open, so the wait passed no
    emulated cycles and the drive never settled. Measured on 2026-09-05: the
    same tool, the same specimen, `$03F1` = 74 and a refusal without the wait,
    `$03F1` = 0 and a party on the screen with it.
    """
    sess = AttachSession(tmp_path, monkeypatch)
    (tmp_path / "SIDE0.D64").write_bytes(b"")
    sess.attach(str(tmp_path / "SIDE0.D64"))

    assert "machine running" in sess.events, sess.events
    after = sess.events[sess.events.index("machine running") + 1:]
    settled = [e for e in after if e.startswith("sleep")]
    assert settled, f"nothing waits after the monitor lets go: {sess.events}"
    assert sum(float(e.split()[1]) for e in settled) >= 1.5, sess.events


class Bar:
    """The `LOAD SAVED GAME ? YES NO` bar, and a keyboard that records."""

    def __init__(self, on: str = "NO", row: int = 24):
        self.words = ["YES", "NO"]
        self.on = self.words.index(on)
        self.row_text = "LOAD SAVED GAME ? YES NO".ljust(40)
        self.row_number = row
        self.xtest: list[str] = []
        self.kernal: list[int] = []
        self.kbd = self

    # -- what a Session gives the walker --------------------------------
    def screen(self):
        return self

    def row(self, r: int) -> str:
        return self.row_text if r == self.row_number else " " * 40

    def key(self, name, hold=0.1, gap=0.14):
        self.xtest.append(name)
        if name == "Right":
            self.on = min(self.on + 1, len(self.words) - 1)
        elif name == "Left":
            self.on = max(self.on - 1, 0)

    def press_kernal(self, code: int) -> None:
        self.kernal.append(code)


@pytest.fixture(autouse=True)
def _no_sleeping(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)


def _span(bar):
    lo = bar.row_text.index(bar.words[bar.on])
    return lo, lo + len(bar.words[bar.on]) - 1


def test_answering_the_question_sends_exactly_one_key(monkeypatch):
    """Two keys answer two questions, and the second one is not on screen yet.

    You pick `YES` at `LOAD SAVED GAME ? YES NO`, and the game loads from
    whatever disk is already in the drive -- so the save disk you were about
    to put in never gets a chance, and the drive answers `62, FILE NOT
    FOUND`. `INSERT CURSE SAVE DISK, PRESS A KEY` was drawn and taken in less
    time than it takes to read the screen; counted in the running game on
    2026-09-05, `GEN $183A` fired and `GEN $1F48` fired straight after it.

    The cause is two keypresses for one answer: `Session.select_bar` presses
    Return over XTEST, which Curse's own key fetcher does not read but the
    KERNAL's interrupt still puts in the buffer at `$0277`, and a
    `press_kernal` after it queues a second. So `answer_yes` walks with the
    arrows, which Curse does read from XTEST, and answers with one key.
    """
    monkeypatch.setattr(por, "span_in", lambda s, row: _span(s))
    bar = Bar(on="NO")
    assert curseload.answer_yes(bar) is True
    assert bar.kernal == [0x0D]
    assert "Return" not in bar.xtest, bar.xtest
    assert bar.xtest == ["Left"], bar.xtest


def test_the_walk_to_yes_is_still_a_walk(monkeypatch):
    """Nothing is pressed until the highlight is on the word asked for."""
    monkeypatch.setattr(por, "span_in", lambda s, row: _span(s))
    bar = Bar(on="YES")
    assert curseload.answer_yes(bar) is True
    assert bar.xtest == []
    assert bar.kernal == [0x0D]


def test_a_save_disk_the_drive_never_closed_is_repaired_in_place(tmp_path):
    """A save disk copied out of a slot too early will not load at all.

    Two of the five Curse specimens in `~/wish-specimens/por-c64/` hold
    `SAVEAZURE` with directory type `$02` and a block count of zero -- a file
    the drive still thinks is open for writing, which a listing shows as
    `*PRG`. The payload is all there, because the data blocks are written
    before the entry is finished, but the drive refuses to open one and Curse
    reports `60, WRITE FILE OPEN` as `UNABLE TO LOAD SAVED GAME.`

    Setting the bit and the count is enough: the repaired copy of
    `WISH-SPEC-curse-dual-classed.D64` loaded its party in the running game
    on 2026-09-05, where the specimen itself had not.
    """
    disk = D64.blank(b"CURSE SAVE")
    payload = bytes(range(256)) * 29          # 7424 bytes, a Curse save's size
    disk.write_file(b"SAVEAZURE", payload)
    entry = disk.entry(b"SAVEAZURE")
    raw = bytearray(disk.to_bytes())
    raw[entry.offset] &= 0x7F                 # what the drive leaves behind
    raw[entry.offset + 28] = raw[entry.offset + 29] = 0
    path = tmp_path / "SIDE0.D64"
    path.write_bytes(bytes(raw))

    assert not D64.open(path).entry(b"SAVEAZURE").is_closed
    changed = curseload.close_splat(str(path))

    assert [c["name"] for c in changed] == ["SAVEAZURE"]
    assert changed[0]["type_was"] == "$02" and changed[0]["type_now"] == "$82"
    assert changed[0]["blocks_now"] == D64.blocks_needed(len(payload))
    after = D64.open(path)
    assert after.entry(b"SAVEAZURE").is_closed
    assert after.read_file(b"SAVEAZURE") == payload
    assert curseload.close_splat(str(path)) == []   # and it is not a rewrite


def test_a_disk_the_drive_did_close_is_left_alone(tmp_path):
    """The repair is for a broken entry and must not touch a good one."""
    disk = D64.blank(b"CURSE SAVE")
    disk.write_file(b"SAVEAZURE", b"\x00\x4B" + bytes(7424))
    path = tmp_path / "SIDE0.D64"
    disk.save(path)
    before = path.read_bytes()

    assert curseload.close_splat(str(path)) == []
    assert path.read_bytes() == before


def test_nothing_here_writes_outside_the_slot(tmp_path, monkeypatch):
    """`attach` refuses a path that is not the session's own copy.

    The player's disks are read and never written, and the way that is
    enforced is that the game is only ever shown an image inside the pool
    slot's directory.
    """
    sess = AttachSession(tmp_path, monkeypatch)
    outside = tmp_path.parent / "somebody-elses.D64"
    outside.write_bytes(b"")
    with pytest.raises(AssertionError):
        sess.attach(str(outside))
    with contextlib.suppress(AssertionError):
        sess.attach(str(outside))


def test_a_save_disk_prompt_still_up_after_the_key_is_not_answered_again(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(curseload.time, "time", lambda: now[0])

    class Session(por.Session):
        def __init__(self):
            self.save_disk = "/slot/SIDE0.D64"
            self.attached = "/slot/SIDE1.D64"
            self._last_prompt = 0.0
            self.kernal = []

        def attach(self, path, *a, **k):
            now[0] += 3.5
            self.attached = os.path.abspath(path)

        def press_kernal(self, code, *a, **k):
            self.kernal.append(code)

    sess = Session()
    assert curseload.answer_prompt(sess) is True
    # Past the cooldown but inside the hold (2.5 s), 5 s after the key (pins
    # the restamp), 7.5 s (pins the hold's length), then 8.5 s answers again.
    for step in (0.35, 2.15, 2.5, 2.5):
        now[0] += step
        assert curseload.answer_prompt(sess) is False
    now[0] += 1.0
    assert curseload.answer_prompt(sess) is True
    assert sess.kernal == [0x20, 0x20]


class Menu:
    """A party menu with a highlight, and a keyboard that records."""

    def __init__(self, rows: dict[int, str], hot: int, column: int = 5,
                 also_hot: tuple[int, ...] = ()):
        self.rows, self.hot, self.column = rows, hot, column
        self.also_hot = also_hot
        self.xtest: list[str] = []
        self.kernal: list[int] = []
        self.prompts = 0
        self.kbd = self

    def screen(self):
        return self

    def find(self, label):
        for r, text in self.rows.items():
            if label in text:
                return (r, text.index(label))
        return None

    def colours(self, r):
        cols = [5] * 40
        cols[self.column] = 1 if r == self.hot or r in self.also_hot else 5
        return cols

    def key(self, name, hold=0.1, gap=0.14):
        self.xtest.append(name)

    def press_kernal(self, code):
        self.kernal.append(code)

    def handle_prompt(self, s):
        self.prompts += 1


def test_highlighted_returns_only_rows_white_at_the_column():
    menu = Menu({}, hot=7, column=5)
    assert curseload.highlighted(menu, 5) == [7]
    assert curseload.highlighted(menu, 6) == []


def test_walk_menu_moves_down_then_presses_return_through_the_kernal():
    menu = Menu({9: "     GO"}, hot=7)
    seen = []
    menu.key = lambda name, hold=0.1, gap=0.14: (
        seen.append(name), setattr(menu, "hot", menu.hot + 1))
    assert curseload.walk_menu(menu, "GO") is True
    assert seen == ["Down", "Down"]
    assert menu.kernal == [0x0D]


def test_walk_menu_moves_up_to_a_label_above_the_highlight():
    menu = Menu({5: "     GO"}, hot=6)
    seen = []
    menu.key = lambda name, hold=0.1, gap=0.14: (
        seen.append(name), setattr(menu, "hot", menu.hot - 1))
    assert curseload.walk_menu(menu, "GO") is True
    assert seen == ["Up"]
    assert menu.kernal == [0x0D]


def test_walk_menu_answers_a_prompt_when_the_label_is_absent(monkeypatch):
    clock = iter([0.0, 1.0, 2.0, 100.0, 100.0, 100.0])
    monkeypatch.setattr(curseload.time, "time", lambda: next(clock))
    menu = Menu({}, hot=1)
    assert curseload.walk_menu(menu, "GO") is False
    assert menu.prompts == 2
    assert menu.kernal == [] and menu.xtest == []


def test_walk_menu_counts_the_arrows_from_the_nearest_highlighted_row():
    """Border rows are white too, so the walk trusts the highlight nearest the label."""
    menu = Menu({10: "     GO"}, hot=2, also_hot=(11,))
    seen = []
    menu.key = lambda name, hold=0.1, gap=0.14: (
        seen.append(name), setattr(menu, "hot", 10), setattr(menu, "also_hot", ()))
    assert curseload.walk_menu(menu, "GO") is True
    assert seen == ["Up"]
    assert menu.kernal == [0x0D]


def test_walk_menu_gives_up_after_forty_seconds_and_not_before(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(curseload.time, "time", lambda: now[0])
    monkeypatch.setattr(curseload.time, "sleep",
                        lambda s: now.__setitem__(0, now[0] + s))
    menu = Menu({}, hot=1)
    assert curseload.walk_menu(menu, "GO") is False
    # The absent-label loop sleeps 0.3 s per pass, so the call ends within one
    # pass of the deadline.
    assert 40.0 <= now[0] <= 40.0 + 0.3 + 1e-6, now[0]


def _save_disk(tmp_path, *, closed: bool, name="save.d64"):
    """A generated Curse save disk, with `SAVEAZURE` closed or left open.

    An open one is what the drive leaves behind when the image is copied out
    before the file is finished: type `$02` and a block count of zero.
    """
    disk = D64.blank(b"CURSE SAVE")
    body = bytearray(7424)
    body[0xC00:0xC00 + 6] = b"MATHEW"
    disk.write_file(b"SAVEAZURE", (0x4B00).to_bytes(2, "little") + bytes(body))
    raw = bytearray(disk.to_bytes())
    entry = disk.entry(b"SAVEAZURE")
    if not closed:
        raw[entry.offset] &= 0x7F
        raw[entry.offset + 28] = raw[entry.offset + 29] = 0
    path = tmp_path / name
    path.write_bytes(bytes(raw))
    return path


def test_refuse_open_entries_names_every_open_entry(tmp_path):
    path = _save_disk(tmp_path, closed=False)
    disk = D64.open(path)
    disk.write_file(b"OTHER", b"x")
    raw = bytearray(disk.to_bytes())
    other = disk.entry(b"OTHER")
    raw[other.offset] &= 0x7F
    path.write_bytes(bytes(raw))
    before = path.read_bytes()

    with pytest.raises(SystemExit) as refused:
        curseload.refuse_open_entries(str(path))

    assert "SAVEAZURE" in str(refused.value) and "OTHER" in str(refused.value)
    assert path.read_bytes() == before


def test_refuse_open_entries_passes_a_closed_disk(tmp_path):
    path = _save_disk(tmp_path, closed=True)
    before = path.read_bytes()

    assert curseload.refuse_open_entries(str(path)) is None
    assert path.read_bytes() == before


def _stage_modules():
    from tools.curse_of_the_azure_bonds import (  # noqa: PLC0415
        cursepaladin,
        cursethac0,
        cursetrain,
    )

    return {"cursepaladin": cursepaladin, "cursetrain": cursetrain,
            "cursethac0": cursethac0}


@pytest.mark.parametrize("name", ["cursepaladin", "cursetrain", "cursethac0"])
def test_no_stage_command_accepts_a_save_disk_the_drive_never_closed(
        tmp_path, name):
    base = _save_disk(tmp_path, closed=False)
    out = tmp_path / "out.d64"

    with pytest.raises(SystemExit) as refused:
        _stage_modules()[name].main(
            ["stage", "--base", str(base), "--out", str(out)])

    assert "SAVEAZURE" in str(refused.value)
    assert not out.exists()


@pytest.mark.parametrize("name", ["cursepaladin", "cursetrain"])
def test_no_stage_command_takes_repair(tmp_path, capsys, name):
    """`--repair` was how an open disk got closed over a possibly stale chain.

    The base is closed, so only the argument parser can refuse the flag.
    """
    base = _save_disk(tmp_path, closed=True)
    out = tmp_path / "out.d64"

    with pytest.raises(SystemExit) as refused:
        _stage_modules()[name].main(
            ["stage", "--base", str(base), "--out", str(out), "--repair"])

    assert refused.value.code == 2
    assert "unrecognized arguments: --repair" in capsys.readouterr().err
    assert not out.exists()


def test_refuse_open_entries_passes_an_empty_disk(tmp_path):
    path = tmp_path / "empty.d64"
    path.write_bytes(D64.blank(b"EMPTY").to_bytes())

    assert curseload.refuse_open_entries(str(path)) is None


def test_refuse_open_entries_names_only_the_open_one_among_closed(tmp_path):
    disk = D64.blank(b"MIXED")
    for name in (b"ONE", b"TWO", b"THREE", b"FOUR"):
        disk.write_file(name, b"x" * 300)
    raw = bytearray(disk.to_bytes())
    four = disk.entry(b"FOUR")
    raw[four.offset] &= 0x7F
    raw[four.offset + 28] = raw[four.offset + 29] = 0
    path = tmp_path / "mixed.d64"
    path.write_bytes(bytes(raw))

    with pytest.raises(SystemExit) as refused:
        curseload.refuse_open_entries(str(path))

    message = str(refused.value)
    assert "FOUR" in message
    for closed in ("ONE", "TWO", "THREE"):
        assert closed not in message


@pytest.mark.parametrize("name", ["cursepaladin", "cursetrain", "cursethac0"])
def test_a_closed_base_still_stages(tmp_path, name):
    base = _save_disk(tmp_path, closed=True)
    out = tmp_path / "out.d64"

    assert _stage_modules()[name].main(
        ["stage", "--base", str(base), "--out", str(out)]) == 0

    assert D64.open(out).entry(b"SAVEAZURE").is_closed


class WorldSess:
    """Plays one screen for `enter_world`, and records every key it sends."""

    def __init__(self, bar: str, hot: list[int], stall_after: int = 10**9):
        self.bar, self.hot, self.stall_after = bar, hot, stall_after
        self.stall_checks = 0
        self.selected: list[str] = []
        self.kernal: list[int] = []
        self.logged: list[str] = []

    def iec_stall_check(self):
        self.stall_checks += 1
        return self.stall_checks > self.stall_after

    def stall_capture(self):
        return "captured"

    def screen(self):
        return menu_screen(3 if self.hot else None,
                           row24="" if self.hot else self.bar)

    def handle_prompt(self, s):
        return False

    def select_row(self, label):
        self.selected.append(label)

    def press_kernal(self, code):
        self.kernal.append(code)

    def log(self, *a):
        self.logged.append(" ".join(str(x) for x in a))


def _clock(monkeypatch):
    t = [0.0]
    monkeypatch.setattr(curseload.time, "time", lambda: t[0])
    monkeypatch.setattr(curseload.time, "sleep",
                        lambda s: t.__setitem__(0, t[0] + s))


def test_a_stalled_load_makes_enter_world_give_up_at_once(monkeypatch):
    _clock(monkeypatch)
    sess = WorldSess("ONWARD BOUND", hot=[], stall_after=3)
    assert curseload.enter_world(sess, timeout=300.0) is False
    assert sess.stall_checks == 4


def test_a_started_load_gets_no_walk_and_no_return(monkeypatch):
    _clock(monkeypatch)
    sess = WorldSess("ONWARD BOUND", hot=[])
    assert curseload.enter_world(sess, timeout=30.0) is False
    assert sess.selected == [] and sess.kernal == []
    assert "captured" in sess.logged[-1]


def test_a_menu_waiting_for_a_key_is_still_chosen(monkeypatch):
    _clock(monkeypatch)
    sess = WorldSess("ONWARD BOUND", hot=[3])
    curseload.enter_world(sess, timeout=5.0)
    assert sess.selected and sess.kernal


class LoadSess(WorldSess):
    """Plays a Curse load pass by pass, as a live boot drew it: the menu
    waiting with MODIFY CHARACTER white, `ONWARD BOUND` under a menu with no
    entry white, the side 2 prompt drawn over row 24 and answered, the prompt
    still drawn on the next pass, row 24 blank under the same menu, then the
    world's bar."""

    def __init__(self, passes, answered_on):
        super().__init__("", hot=[])
        self.passes, self.answered_on, self.at = passes, answered_on, -1

    def screen(self):
        self.at = min(self.at + 1, len(self.passes) - 1)
        return self.passes[self.at]

    def handle_prompt(self, s):
        return self.at == self.answered_on


def test_nothing_is_sent_into_a_load_after_its_disk_prompt(monkeypatch):
    _clock(monkeypatch)
    passes = ([menu_screen(MODIFY)] + [menu_screen(None, ONWARD)] * 4
              + [menu_screen(None, SIDE_2)] * 2 + [menu_screen(None)] * 6
              + [bar_screen(WORLD_BAR)])
    sess = LoadSess(passes, answered_on=5)
    assert curseload.enter_world(sess, timeout=300.0) is True
    assert sess.selected == ["BEGIN ADVENTURING"]
    assert sess.kernal == [0x0D]


def test_an_uncoloured_first_pass_delays_the_choice_and_does_not_lose_it(
        monkeypatch):
    class Recording(LoadSess):
        def select_row(self, label):
            super().select_row(label)
            self.chosen_on = self.at

    _clock(monkeypatch)
    passes = ([menu_screen(None)] + [menu_screen(MODIFY)]
              + [menu_screen(None, ONWARD)] * 4 + [bar_screen(WORLD_BAR)])
    sess = Recording(passes, answered_on=-1)
    assert curseload.enter_world(sess, timeout=300.0) is True
    assert sess.selected == ["BEGIN ADVENTURING"]
    assert sess.chosen_on > 0
    assert sess.kernal == [0x0D]
