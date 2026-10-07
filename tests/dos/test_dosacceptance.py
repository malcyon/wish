"""`tools/dos/acceptance.py`: the step list, the rest keys and the reading.

The driven half needs DOSBox and the player's archives and is proven by a
run.  What is pinned here: that the rest-menu keys reach the asked time from
any time the camp presets, on a fake that does the rest menu's arithmetic as
`GAME.OVR` 0x244ED and 0x24246 do it; that the camp bar is recognised
whichever word is highlighted; and that the reading names a node that lost
minutes, one that vanished, and one that the expectation accepts.  The one
test that converts the fixture party skips without the archives or the C64
disks.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import signal as _signal
import threading

import pytest

from tools.dos import acceptance as da
from tools.dos import dosbox, dospod, route_silver_blades, screens, staging

# Sending SIGTERM to the test process ends it on Windows, which has no POSIX signals.
posix_signals = pytest.mark.skipif(
    not hasattr(_signal, "pthread_sigmask"), reason="POSIX signals")

W, H = 320, 200
BAR_Y = dosbox.BAR[1]
#: The rest menu's letters as each title's `GAME.OVR` reads them, written out
#: here rather than taken from the driver, so a fake driven with the wrong
#: letters fails: days, hours, minutes, add, subtract, rest.
_POOL_REST = da.RestKeys("y", "h", "m", "i", "d", "r")      # 0x244ED
_LATER_REST = da.RestKeys("d", "h", "m", "a", "s", "r")     # 0x2B4A7, 0x2BD63
# Pools of Darkness: `Rest Days Hours Mins Add Subtract Exit`, `GAME.EXE` 0xBB26.
TITLE_KEYS = {"pool": _POOL_REST, "curse": _LATER_REST, "ssb": _LATER_REST,
              "darkness": _LATER_REST}


def _screen(bar: bytes, text: bytes, block: tuple[int, int] | None = None) -> dosbox.Screen:
    """A frame whose bar row carries `bar` as lit cells and whose text window
    carries `text`, a byte per pixel of row 136.  `block` is a range of bar
    cells drawn knocked out of a filled block, the way the game highlights a
    word."""
    px = bytearray(W * H * 3)
    for x, v in enumerate(text[:W]):
        at = (136 * W + x) * 3
        px[at:at + 3] = bytes((v, v, v))
    for cell, pattern in enumerate(bar[:W // screens.CELL]):
        inside = block is not None and block[0] <= cell < block[1]
        for dy in range(dosbox.BAR[3]):
            for dx in range(screens.CELL):
                lit = bool(pattern >> ((dx + dy) % 8) & 1)
                at = ((BAR_Y + dy) * W + cell * screens.CELL + dx) * 3
                if inside:
                    px[at:at + 3] = b"\x00\x00\x00" if lit else b"\xaa\x00\xaa"
                else:
                    px[at:at + 3] = b"\x55\xff\x55" if lit else b"\x00\x00\x00"
    return dosbox.Screen(W, H, bytes(px))


#: The synthetic question's prompt: six cells of ink left of what is typed.
_PROMPT = bytes((0x11, 0x22, 0x44, 0x88, 0x12, 0x24))


def _journal_frame(typed: int = 0) -> dosbox.Screen:
    """A synthetic stand-in for Pools of Darkness' journal question: `_PROMPT`
    and one lit cell per typed key on the bar row, and sparse ink across
    `dospod.JOURNAL_LINE_RECT`.  The `pod_journal` fixture makes the driver
    know it by this frame's own digests."""
    frame = _screen(_PROMPT + b"\x81" * typed, b"")
    px = bytearray(frame.px)
    x0, y0, w, h = dospod.JOURNAL_LINE_RECT
    for x in range(x0, x0 + w, 3):
        at = ((y0 + x % h) * W + x) * 3
        px[at:at + 3] = b"\x55\xff\x55"
    return dosbox.Screen(W, H, bytes(px))


@pytest.fixture
def pod_journal(monkeypatch):
    frame = _journal_frame()
    monkeypatch.setattr(dospod, "JOURNAL_PROMPT",
                        frame.glyphs(dospod.JOURNAL_PROMPT_RECT))
    monkeypatch.setattr(dospod, "JOURNAL_LINE",
                        frame.glyphs(dospod.JOURNAL_LINE_RECT))


# -- the bar, blind to its highlight -------------------------------------------


def test_the_bar_signature_ignores_which_word_is_highlighted():
    # Fewer lit pixels than paper in every cell, as a letter is.
    words = bytes((0x18, 0x24, 0, 0x81, 0x07, 0, 0x03))
    ordinary = _screen(words, b"")
    for block in ((0, 2), (3, 5), (6, 7)):
        lit = _screen(words, b"", block)
        # The whole-bar digest `glyphs` is fooled by the block, and the
        # signature is not.
        assert lit.glyphs(dosbox.BAR) != ordinary.glyphs(dosbox.BAR)
        assert screens.bar_signature(lit) == screens.bar_signature(ordinary)
    assert screens.bar_signature(_screen(bytes((0x18, 0x24, 0, 0x81, 0x05)), b"")) \
        != screens.bar_signature(ordinary)


# -- a fake DOS Pool of Radiance camp ------------------------------------------


class FakePool:
    """Camp, the rest menu and the camp save, as the overlay does them.

    The rest time is the game's digits: minute units, minute tens, hours,
    days.  `Inc` on minutes adds five to the units and carries; `Dec` takes
    five, borrowing from a higher field, and zeroes the whole time when
    nothing above has anything to borrow (`GAME.OVR` 0x24246).  `R` rests the
    time off and adds it to the clock.
    """

    BARS = {"map": b"\x11\x22", "camp": b"\x33\x44\x55", "rest": b"\x66\x77",
            "save": b"\x88", "quit": b"\x99\x0f",
            "watch": b"\xaa\x0f\x33", "fight": b"\x5a\xa5"}

    def __init__(self, tmp: pathlib.Path, preset: int = 0, swallow: bool = False,
                 dead: str = "", watches: int = 0, fight: bool = False,
                 keys: da.RestKeys | None = None):
        self.fight = fight
        #: The rest menu's letters: Pool's by default, `da.LATER_REST` for
        #: Curse and Silver Blades.
        self.rk = keys or TITLE_KEYS["pool"]
        self.mode = "map"
        #: Random events the next rest ends in, one after another.
        self.watches = watches
        self.answers: list[str] = []
        self.preset = preset
        self.total = 0
        self.field = 2
        self.clock = 0
        self.rested: list[int] = []
        self.swallow = swallow
        self.armed = False
        self.dead = dead
        self.save_dir = tmp / "SAVE"
        self.save_dir.mkdir()
        self.keys: list[str] = []

    # -- the game's arithmetic ------------------------------------------

    def digits(self) -> tuple[int, int, int, int]:
        days, rest = divmod(self.total, 1440)
        hours, mins = divmod(rest, 60)
        return mins % 10, mins // 10, hours, days

    def inc(self) -> None:
        self.total += {2: 5, 3: 60, 4: 1440}[self.field]
        self.total = min(self.total, 99 * 1440 + 1439)

    def dec(self) -> None:
        units, tens, hours, days = self.digits()
        idx = {2: 1, 3: 3, 4: 4}[self.field]
        amount, unit = {2: (5, 1), 3: (1, 60), 4: (1, 1440)}[self.field]
        have = {1: units, 3: hours, 4: days}[idx]
        higher = {1: (tens, hours, days), 3: (days,), 4: ()}[idx]
        if self.total == 0:
            return
        if amount <= have or any(higher):
            self.total -= amount * unit
        else:
            self.total = 0

    # -- the session's surface -------------------------------------------

    def key(self, k: str, gap: float = 0.0) -> None:
        self.keys.append(k)
        if self.armed:
            self.armed = False
            return
        before = self.mode
        if k == self.dead:
            return
        if self.mode == "map" and k == "e":
            self.mode = "camp"
        elif self.mode == "camp" and k == "r":
            self.mode, self.total, self.field = "rest", self.preset, 2
        elif self.mode == "camp" and k == "s":
            self.mode = "save"
        elif self.mode == "rest":
            rk = self.rk
            if k in (rk.days, rk.hours, rk.mins):
                self.field = {rk.days: 4, rk.hours: 3, rk.mins: 2}[k]
            elif k == rk.inc:
                self.inc()
            elif k == rk.dec:
                self.dec()
            elif k == rk.go:
                self.rested.append(self.total)
                self.clock += self.total
                self.total, self.mode = 0, "camp"
                if self.watches:
                    self.mode = "watch"
                if self.fight:
                    self.mode = "fight"
            elif k == "e":
                self.mode = "camp"
        elif self.mode == "watch" and k in "gs":
            self.answers.append(k)
            self.watches -= 1
            self.mode = "fight" if k == "s" else "watch" if self.watches else "map"
        elif self.mode == "save" and k.upper() in "ABCDEFGHIJ":
            (self.save_dir / f"SAVGAM{k.upper()}.DAT").write_bytes(
                bytes((self.clock % 256,)))
            self.mode = "quit"
        elif self.mode == "quit" and k == "n":
            self.mode = "camp"
        if self.mode != before and self.swallow:
            self.armed = True

    def capture(self) -> dosbox.Screen:
        text = b""
        if self.mode == "rest":
            text = bytes((1 + self.field, *(d + 1 for d in self.digits())))
        return _screen(self.BARS[self.mode], text)

    def settle(self, quiet: float = 0.6, timeout: float = 30.0) -> dosbox.Screen:
        return self.capture()

    def wait_for(self, pred, timeout: float = 30.0) -> bool:
        return bool(pred(self.capture()))

    def wait_while_ink(self, rect, same, timeout: float = 30.0) -> bool:
        return self.capture().ink(rect) != same

    def wait_until_ink(self, rect, want, timeout: float = 30.0) -> bool:
        return self.capture().ink(rect) == want

    def shot(self, name: str, allow_blank: bool = False) -> pathlib.Path:
        return self.save_dir.parent / f"{name}.png"

    def save_file(self, letter: str) -> pathlib.Path:
        return self.save_dir / f"SAVGAM{letter.upper()}.DAT"


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    monkeypatch.setattr(da.time, "sleep", lambda s: None)
    monkeypatch.setattr(dosbox, "settle_files", lambda *a, **k: True)


@pytest.fixture(autouse=True)
def _items_bar_measured(monkeypatch):
    """The fakes' `items` bar stands in for the measured `READY` head of
    `ITEMS_BAR_HEAD`, whose real value a capture test checks."""
    monkeypatch.setattr(screens, "ITEMS_BAR_HEAD", screens.bar_signature(
        _screen(b"\x2b\x2c", b""), screens.ITEMS_BAR_HEAD_CELLS))


@pytest.fixture(autouse=True)
def _pod_map_measured(monkeypatch):
    """The fakes' map bar stands in for the measured `dungeon` one of
    `POD_MAP_BARS`, whose real values the tests at the end check against
    captures."""
    monkeypatch.setattr(da, "POD_MAP_BARS", {
        "dungeon": screens.bar_signature(_screen(FakePool.BARS["map"], b""))})


@pytest.fixture
def pool_map_measured(monkeypatch):
    """The fakes' map bar stands in for the measured `town` one of
    `POOL_MAP_BARS`, the only bars Pool's `load` and `camp` take for the map,
    for the tests that camp or load a Pool fake from its map; the capture
    tests check the real values."""
    monkeypatch.setattr(da, "POOL_MAP_BARS", {
        "town": screens.bar_signature(_screen(FakePool.BARS["map"], b""))})


def _camped(tmp_path, title="pool", **kw) -> tuple[FakePool, da.Driver]:
    game = FakePool(tmp_path, keys=TITLE_KEYS[title], **kw)
    d = da.Driver(game, lambda **k: None, "A", title)
    d.logged = []
    d.note = lambda **k: d.logged.append(k)
    d.camp()
    return game, d


@pytest.mark.parametrize("title", sorted(da.TITLES))
@pytest.mark.parametrize("preset", [0, 7, 4 * 60 + 30, 1440 + 65, 3 * 1440])
@pytest.mark.parametrize("asked", [5, 90, 1445])
@pytest.mark.usefixtures("pool_map_measured")
def test_the_rest_keys_set_the_asked_time_from_any_preset(tmp_path, title, preset,
                                                          asked):
    game, d = _camped(tmp_path, title, preset=preset)
    got = d.rest(asked)
    assert game.rested == [asked]
    assert got["asked"] == asked
    assert game.mode == "camp"


@pytest.mark.usefixtures("pool_map_measured")
def test_a_swallowed_key_after_each_redraw_is_pressed_again(tmp_path):
    game, d = _camped(tmp_path, preset=4 * 60 + 30, swallow=True)
    d.rest(5)
    assert game.rested == [5]


@pytest.mark.usefixtures("pool_map_measured")
def test_nothing_is_pressed_while_the_party_rests(tmp_path):
    # Any key during a rest asks `Stop Resting?`: the last key before camp
    # returns is the rest key itself.
    game, d = _camped(tmp_path)
    d.rest(5)
    assert game.keys[-1] == da.REST_GO


@pytest.mark.usefixtures("pool_map_measured")
def test_a_key_that_changes_nothing_stops_the_run(tmp_path):
    game, d = _camped(tmp_path, dead=da.REST_INC)
    with pytest.raises(da.StepFailed, match="Inc on minutes"):
        d.rest(5)
    assert game.rested == []


def test_rest_and_save_block_before_camp(tmp_path):
    d = da.Driver(FakePool(tmp_path), lambda **k: None, "A")
    with pytest.raises(da.StepFailed, match="camp first"):
        d.rest(5)
    with pytest.raises(da.StepFailed, match="camp first"):
        d.save("D")


@pytest.mark.usefixtures("pool_map_measured")
def test_the_camp_save_is_believed_by_the_file_and_declines_the_quit(tmp_path):
    game, d = _camped(tmp_path)
    got = d.save("D")
    assert (game.save_dir / "SAVGAMD.DAT").is_file()
    assert got["back_in_camp"] and game.mode == "camp"
    assert game.keys[-2:] == ["d", da.QUIT_NO]


# -- camp MAGIC > DISPLAY, read as text -------------------------------------------

#: A stand-in font: glyph i lights row 1 with i + 1 and row 2 with 0x81, so
#: every glyph is sparse, distinct, and neither blank nor solid.
_FONT_BLOCK = b"".join(bytes((0, i + 1, 0x81, 0, 0, 0, 0, 0)) for i in range(da.FONT_GLYPHS))
_FONT = da.font_table(_FONT_BLOCK)
_NAME_INK, _EFFECT_INK = b"\x55\xff\xff", b"\x55\xff\x55"
_DISPLAY_KEYS = {"magic": b"\x12\x45\x78", "exit": b"\x13\x46\x79",
                 "next": b"\x15\x48\x7b", "prev": b"\x16\x49\x7c", "wrong": b"\x14\x47\x7a"}


def _draw(px: bytearray, block: bytes, row: int, col: int, text: str, ink: bytes) -> None:
    for i, ch in enumerate(text):
        glyph = block[(ord(ch.upper()) % 0x40) * 8:][:8]
        for dy, bits in enumerate(glyph):
            for dx in range(8):
                if bits & (0x80 >> dx):
                    at = (((row * 8) + dy) * W + (col + i) * 8 + dx) * 3
                    px[at:at + 3] = ink


def _party_lines(members: list[tuple[str, list[str]]], none: str) -> list[str]:
    """The list the game builds: a blank line, then each member's name, an
    indented line an effect (or `none`), and a blank line."""
    lines = [""]
    for name, effects in members:
        lines += [name] + [" " + e for e in (effects or [none])] + [""]
    return lines


class FakeDisplay(FakePool):
    """Camp, the Magic bar and the Display list as the three titles draw it:
    rows 4 to 22 of the list at a time, ` NEXT EXIT` while more is below,
    `n` scrolling `scroll` lines on (a page by default, one in Silver
    Blades) but never past the last full window, `p` back.  `Return` leaves
    a list only where `returns` says it does.  `stuck` makes `n` change the
    frame without scrolling, `n_leaves` makes it open an unknown screen."""

    BARS = {**FakePool.BARS, "magic": _DISPLAY_KEYS["magic"],
            "wrong": _DISPLAY_KEYS["wrong"]}

    def __init__(self, tmp, lines: list[str], *, returns: bool = True,
                 pointer: bool = False, failure: str = "", scroll: int = 0,
                 stuck: bool = False, n_leaves: bool = False, **kw):
        super().__init__(tmp, **kw)
        self.lines, self.returns, self.pointer = lines, returns, pointer
        self.failure = failure
        self.scroll = scroll or self.window()
        self.stuck, self.n_leaves = stuck, n_leaves
        self.top = 0
        self.turned = 0

    def window(self) -> int:
        return len(da.DISPLAY_ROWS)

    def page_bar(self) -> str:
        if len(self.lines) <= self.window():
            return "exit"
        return "next" if self.top + self.window() < len(self.lines) else "prev"

    def key(self, k, gap=0.0):
        if self.mode == "display" and k == self.dead:
            self.keys.append(k)
        elif self.mode == "camp" and k == "m":
            self.keys.append(k)
            self.mode = "wrong" if self.failure == "magic" else "magic"
        elif self.mode == "magic" and k == "d":
            self.keys.append(k)
            self.mode = "wrong" if self.failure == "display" else "display"
        elif self.mode == "display" and k == "n":
            self.keys.append(k)
            self.turned += 1
            if self.n_leaves:
                self.mode = "wrong"
            elif not self.stuck:
                self.top = min(self.top + self.scroll, len(self.lines) - self.window())
        elif self.mode == "display" and k == "p":
            self.keys.append(k)
            self.top = max(0, self.top - self.window())
        elif self.mode == "display" and (k == "e" or k == "Return" and self.returns):
            self.keys.append(k)
            self.mode = "wrong" if self.failure == "back_magic" else "magic"
        elif self.mode == "display":
            self.keys.append(k)
        elif self.mode == "magic" and k == "e":
            self.keys.append(k)
            self.mode = "wrong" if self.failure == "back_camp" else "camp"
        else:
            super().key(k, gap)

    def capture(self):
        if self.mode != "display":
            return super().capture()
        frame = _screen(_DISPLAY_KEYS[self.page_bar()], b"")
        px = bytearray(frame.px)
        # A pixel of the frame, above the list, that `n` changes when stuck.
        at = (8 * W + self.turned % W) * 3
        px[at:at + 3] = b"\x55\x55\x55"
        for i, line in enumerate(self.lines[self.top:self.top + self.window()]):
            row = da.DISPLAY_ROWS[0] + i
            if line.startswith(" "):
                _draw(px, _FONT_BLOCK, row, 2, line[1:], _EFFECT_INK)
            elif line:
                _draw(px, _FONT_BLOCK, row, 1, line, _NAME_INK)
        if self.pointer:
            # Silver Blades' arrow: white, over paper, across a text cell and
            # into two cells of its own.
            for dy in range(14):
                for dx in range(dy // 2 + 1):
                    x, y = 8 * 12 + 1 + dx, 8 * 9 + 3 + dy
                    at = (y * W + x) * 3
                    if px[at:at + 3] == b"\x00\x00\x00":
                        px[at:at + 3] = da.POINTER_INK
        return dosbox.Screen(W, H, bytes(px))


@pytest.fixture
def display_measured(monkeypatch, tmp_path):
    """The fakes' Magic and Display bars stand in for the measured ones, and
    the stand-in font for the title's own, found in an empty directory in
    place of the archives, so no test here needs them."""
    sig = {k: screens.bar_signature(_screen(v, b"")) for k, v in _DISPLAY_KEYS.items()}
    monkeypatch.setattr(da, "POOL_MAGIC_BAR", sig["magic"])
    monkeypatch.setattr(da, "POOL_DISPLAY_BAR", sig["exit"])
    monkeypatch.setattr(da, "DISPLAY_NEXT_BAR", sig["next"])
    monkeypatch.setattr(da, "DISPLAY_PREV_BAR", sig["prev"])
    monkeypatch.setattr(da, "DISPLAY_BARS", {sig["exit"]: "exit", sig["next"]: "next",
                                             sig["prev"]: "prev"})
    monkeypatch.setattr(dosbox, "find_game", lambda stem="POOLRAD": tmp_path)
    monkeypatch.setattr(da, "load_font", lambda game: _FONT)
    return sig


_POOL_PARTY = [(f"WISH{n}", ["PRAYER"]) for n in ("FTR", "CLE", "MAG", "THI", "DWF", "HEL")]
#: #666's `7080ae935c-curse-display-measure`, as the page read.
_CURSE_PARTY = [("MATHEW", ["PROTECTION FROM EVIL"]), ("MARK", ["PROTECTION FROM EVIL"]),
                ("TRAVIS", []), ("LEDERA", []), ("SHARA", ["ENLARGE"]), ("PHILIPPE", [])]
#: #666's `7080ae935c-ssb-display-measure`: twenty lines, one more than the window.
_SSB_PARTY = [("GUY DE VALOIS", ["PROTECTED FROM EVIL", "AFFECTED BY PRAYER"]),
              ("PAINE", ["AFFECTED BY PRAYER"]), ("EPONA", ["AFFECTED BY PRAYER"]),
              ("MALACHITE", ["AFFECTED BY PRAYER"]), ("DOMINIC", ["AFFECTED BY PRAYER"]),
              ("MORGAINE", ["AFFECTED BY PRAYER"])]


def _display_camp(tmp_path, title, party, none="<NO SPELL EFFECTS>", **kw):
    game = FakeDisplay(tmp_path, _party_lines(party, none), keys=TITLE_KEYS[title], **kw)
    d = da.Driver(game, lambda **k: None, "A", title, party_size=len(party))
    d.camp()
    game.keys.clear()
    return game, d


def _members(party):
    return [{"name": n, "effects": list(e)} for n, e in party]


@pytest.mark.parametrize("failure", ("", "magic", "display", "five", "back_magic",
                                          "back_camp"))
@pytest.mark.usefixtures("pool_map_measured")
def test_pool_display_captures_every_member_and_returns_to_camp_before_save(
        tmp_path, display_measured, failure):
    party = _POOL_PARTY[:5] if failure == "five" else _POOL_PARTY
    game = FakeDisplay(tmp_path, _party_lines(party, "<NO SPELL EFFECTS>"),
                       failure=failure)
    d = da.Driver(game, lambda **k: None, "A")
    d.camp()
    if failure:
        with pytest.raises(da.StepFailed):
            d.display()
        assert not game.save_file("D").exists()
        return
    got = d.display()
    assert got["visible_members"] == 6
    assert got["members"] == _members(_POOL_PARTY)
    assert got["back_in_camp"] and game.mode == "camp"
    assert game.keys[-4:] == ["m", "d", "Return", "e"]
    d.save("D")
    assert game.save_file("D").is_file()


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_display_of_a_one_member_party_passes_with_one_name_row(
        tmp_path, display_measured):
    party = _POOL_PARTY[:1]
    game = FakeDisplay(tmp_path, _party_lines(party, "<NO SPELL EFFECTS>"))
    d = da.Driver(game, lambda **k: None, "A", party_size=1)
    d.camp()
    got = d.display()
    assert got["visible_members"] == 1
    assert got["members"] == _members(party)


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_display_of_a_six_member_party_showing_five_rows_still_fails(
        tmp_path, display_measured):
    game = FakeDisplay(tmp_path, _party_lines(_POOL_PARTY[:5], "<NO SPELL EFFECTS>"))
    d = da.Driver(game, lambda **k: None, "A", party_size=6)
    d.camp()
    with pytest.raises(da.StepFailed, match="showed 5 member rows"):
        d.display()


def test_curse_display_names_each_members_effects_on_one_page(tmp_path, display_measured):
    game, d = _display_camp(tmp_path, "curse", _CURSE_PARTY)
    got = d.display()
    assert got["members"] == _members(_CURSE_PARTY)
    assert got["members"][4] == {"name": "SHARA", "effects": ["ENLARGE"]}
    assert [p["bar"] for p in got["pages"]] == ["exit"] and got["unreadable"] == []
    assert game.keys == ["m", "d", "Return", "e"] and game.mode == "camp"
    assert got["left_with"] == "Return"


def test_silver_blades_display_pages_with_next_and_leaves_with_exit(tmp_path,
                                                                   display_measured):
    game, d = _display_camp(tmp_path, "ssb", _SSB_PARTY, "<NO MAGICAL EFFECTS>",
                            returns=False, pointer=True)
    got = d.display()
    assert got["members"] == _members(_SSB_PARTY)
    assert [p["bar"] for p in got["pages"]] == ["next", "prev"]
    assert got["unreadable"] == []
    # Return is not tried on a paged bar; `e` is the word's own key.
    assert game.keys == ["m", "d", "n", "e", "e"] and game.mode == "camp"
    assert got["left_with"] == "e"


def test_a_list_of_three_pages_is_merged_without_losing_a_line(tmp_path, display_measured):
    party = [(f"MEMBER{n}", [f"EFFECT {n}{k}" for k in range(n + 2)]) for n in range(6)]
    game, d = _display_camp(tmp_path, "ssb", party, returns=False)
    got = d.display()
    assert len(got["pages"]) == 3 and got["pages"][-1]["bar"] == "prev"
    assert got["members"] == _members(party)
    assert got["lines"] == _party_lines(party, "<NO SPELL EFFECTS>")


def test_a_return_that_leaves_nothing_is_followed_by_exit(tmp_path, display_measured):
    game, d = _display_camp(tmp_path, "ssb", _CURSE_PARTY, returns=False)
    got = d.display()
    assert game.keys == ["m", "d", "Return", "e", "e"] and game.mode == "camp"
    assert got["left_with"] == "e"


def test_a_display_naming_fewer_members_than_the_party_fails_back_in_camp(
        tmp_path, display_measured):
    game, d = _display_camp(tmp_path, "curse", _CURSE_PARTY)
    d.party_size = 7
    with pytest.raises(da.StepFailed, match="named 6 members, not the party's 7"):
        d.display()
    assert game.keys == ["m", "d", "Return", "e"] and game.mode == "camp"


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_passes_on_six_rows_and_only_reports_the_names(tmp_path, display_measured):
    game = FakeDisplay(tmp_path, _party_lines(_POOL_PARTY, "<NO SPELL EFFECTS>"))
    d = da.Driver(game, lambda **k: None, "A", party_size=6)
    d.camp()
    got = d.display()
    assert got["visible_members"] == 6 and got["members"] == _members(_POOL_PARTY)
    assert game.mode == "camp"


@pytest.mark.parametrize("title", ("pool", "curse"))
@pytest.mark.usefixtures("pool_map_measured")
def test_a_missing_font_is_a_report_in_pool_and_a_failure_before_any_key_elsewhere(
        tmp_path, display_measured, monkeypatch, title):
    def nowhere(stem="POOLRAD"):
        raise FileNotFoundError(f"no DOS {stem}")
    monkeypatch.setattr(dosbox, "find_game", nowhere)
    party = _POOL_PARTY if title == "pool" else _CURSE_PARTY
    game, d = _display_camp(tmp_path, title, party)
    if title == "curse":
        with pytest.raises(da.StepFailed, match="cannot read curse's text font"):
            d.display()
        assert game.keys == [] and game.mode == "camp"
        return
    got = d.display()
    assert got["members"] is None and "no DOS POOLRAD" in got["font_error"]
    assert got["visible_members"] == 6 and game.mode == "camp"


def test_a_list_scrolled_a_line_at_a_time_reads_to_its_end_past_eight_pages(
        tmp_path, display_measured):
    # 31 lines, one `n` a line: 13 pages, as Silver Blades would draw them.
    party = [(f"MEMBER{n}", [f"EFFECT {n}{k}" for k in range(3)]) for n in range(6)]
    game, d = _display_camp(tmp_path, "ssb", party, returns=False, scroll=1)
    got = d.display()
    assert len(got["lines"]) == 31 and len(got["pages"]) == 13
    assert got["members"] == _members(party) and got["stopped"] is None
    assert game.keys == ["m", "d"] + ["n"] * 12 + ["e", "e"] and game.mode == "camp"


def test_paging_stops_when_a_page_adds_no_line(tmp_path, display_measured):
    game, d = _display_camp(tmp_path, "ssb", _SSB_PARTY, returns=False, stuck=True)
    got = d.display()
    assert got["stopped"] == "no new line" and len(got["pages"]) == 2
    assert got["members"][0]["name"] == "GUY DE VALOIS"
    assert game.keys == ["m", "d", "n", "e", "e"] and got["left_with"] == "e"


def test_a_next_that_changes_nothing_fails_back_in_camp(tmp_path, display_measured):
    game, d = _display_camp(tmp_path, "ssb", _SSB_PARTY, returns=False, dead="n")
    with pytest.raises(da.StepFailed, match="NEXT changed nothing"):
        d.display()
    assert game.keys == ["m", "d", "n", "e", "e"] and game.mode == "camp"


def test_a_next_that_opens_an_unknown_screen_presses_nothing_more(tmp_path,
                                                                 display_measured):
    game, d = _display_camp(tmp_path, "ssb", _SSB_PARTY, returns=False, n_leaves=True)
    with pytest.raises(da.StepFailed, match="NEXT left the paged DISPLAY list"):
        d.display()
    assert game.keys == ["m", "d", "n"] and game.mode == "wrong"


def test_display_is_blocked_in_pools_of_darkness_before_any_key(tmp_path, display_measured):
    game, d = _display_camp(tmp_path, "curse", _CURSE_PARTY)
    d.title = da.TITLES["darkness"]
    with pytest.raises(da.StepFailed, match="curse, pool, ssb only"):
        d.display()
    assert game.keys == []


def test_a_cell_reads_heavy_glyphs_under_the_pointer_and_blank_when_only_pointer():
    # A glyph with more ink than paper, as `H` is in the real font: the
    # commonest colour is its ink, so it matches through its complement.
    heavy = bytes((0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x0F, 0, 0))
    font = {**_FONT, heavy: "H"}
    block = bytearray(_FONT_BLOCK)
    block[8 * 8:9 * 8] = heavy
    px = bytearray(W * H * 3)
    _draw(px, bytes(block), 4, 1, "ABH", _EFFECT_INK)
    for y in range(32, 40):       # the pointer on B's paper, and alone in cell 5
        for x in (17, 40, 41):
            at = (y * W + x) * 3
            if px[at:at + 3] == b"\x00\x00\x00":
                px[at:at + 3] = da.POINTER_INK
    screen = dosbox.Screen(W, H, bytes(px))
    assert [da.read_cell(screen, c * 8, 32, font) for c in range(1, 7)] == \
        ["A", "B", "H", " ", " ", " "]


def test_a_member_line_after_an_effect_starts_a_new_member_and_an_orphan_effect_is_blocked():
    assert da.display_members(["", "A", " X", " Y", "", "B", " <NO MAGICAL EFFECTS>"]) == \
        [{"name": "A", "effects": ["X", "Y"]}, {"name": "B", "effects": []}]
    with pytest.raises(ValueError, match="before any name"):
        da.display_members(["", " X"])


def test_merged_pages_take_the_reading_without_a_question_mark():
    assert da.merge_pages([["", "A", " X?Y"], [" XZY", "", "B"]]) == \
        ["", "A", " XZY", "", "B"]


def test_an_unreadable_or_blank_page_is_never_laid_over_real_lines():
    # An unreadable page matches anything through its `?`s and would vanish.
    assert da.merge_pages([["A", "B"], ["??", "??"]]) == ["A", "B", "??", "??"]
    # Real lines must not replace unreadable ones on a blank-only match.
    assert da.merge_pages([["A", "???", "???"], ["C", "D"]]) == \
        ["A", "???", "???", "C", "D"]
    assert da.merge_pages([["A", " X", ""], ["", "", "B"]]) == ["A", " X", "", "", "", "B"]


@pytest.mark.parametrize("stem", ("POOLRAD", "CURSE", "SECRET"))
def test_each_titles_font_reads_its_own_letters_back(stem):
    try:
        game = dosbox.find_game(stem)
    except FileNotFoundError:
        pytest.skip("needs the DOS archives ($FR_ARCHIVES)")
    font = da.load_font(game)
    assert set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<>-") <= set(font.values())
    block = bytearray(8 * da.FONT_GLYPHS)
    for bits, ch in font.items():
        i = ord(ch) % 0x40
        block[i * 8:i * 8 + 8] = bits
    px = bytearray(W * H * 3)
    _draw(px, bytes(block), 4, 1, "SHARA", _NAME_INK)
    _draw(px, bytes(block), 5, 2, "AFFECTED BY PRAYER", _EFFECT_INK)
    lines = da.display_lines(dosbox.Screen(W, H, bytes(px)), font)
    assert lines[:2] == ["SHARA", " AFFECTED BY PRAYER"]


# -- a camp cast in Pool ---------------------------------------------------------

#: The fake camp's members, and the spell list it opens by default: a level
#: heading, then spells, as Pool draws them.
_CAST_NAMES = ("WISHFTR", "WISHCLE", "WISHMAG", "WISHTHI", "WISHDWF", "WISHHEL")
_CAST_ROWS = (("level", "1ST LEVEL"), ("spell", "BLESS"), ("spell", "CURE LIGHT WOUNDS"),
              ("spell", "CURE LIGHT WOUNDS"), ("level", "2ND LEVEL"),
              ("spell", "HOLD PERSON"))
_CAST_LIST_GREEN, _CAST_HEAD = b"\x55\xff\x55", b"\xaa\x55\xff"


def _cast_rows(*spells: str, level: str = "1ST LEVEL") -> list[tuple[str, str]]:
    return [("level", level)] + [("spell", s) for s in spells]


class CastPool(FakePool):
    """Pool's camp `MAGIC > CAST` as the live boots showed it: the roster
    highlight (the white name) picks the caster and `End` moves it; `m` opens
    the Magic bar and `c` the caster's list, `<NAME>'S SPELLS IN MEMORY` over
    `CHOOSE SPELL: CAST EXIT`, a heading per level at column 1 and each spell
    at column 3, the current row white, opening on the last row; `End` moves
    it a spell on, skipping headings and wrapping; `c` casts.  A spell types
    a message window (`<NAME> CASTS`, the spell) over the list's foot for a
    few frames, with no highlight, then redraws the list without its row; a
    spell in `TARGETED` first shows the camp roster over `CAST SPELL ON WHOM
    SELECT EXIT`, where `End` moves the highlight and `Return` picks; one in
    `COMBAT_ONLY` asks `LOSE IT`.  `e` leaves the list for the Magic bar and
    that for camp.  With `EMPTY_TO_MAGIC`, casting the last row goes back to
    the Magic bar, where `c` changes nothing while nothing is memorised, as
    the live boot measured."""

    BAR_TEXT = {"camp": "SAVE VIEW MAGIC REST FIX EXIT",
                "magic": "CAST MEMORIZE SCRIBE DISPLAY REST EXIT",
                "list": "CHOOSE SPELL: CAST EXIT",
                "message": "CHOOSE SPELL: CAST EXIT",
                "target": "CAST SPELL ON WHOM SELECT EXIT",
                "lose": "LOSE IT? YES NO",
                "wrong": "PRESS ANY KEY TO CONTINUE",
                "prompt": "CHOOSE WHOM: PICK EXIT"}
    TARGETED = {"CURE LIGHT WOUNDS", "RESIST COLD", "SLOW POISON"}
    COMBAT_ONLY = {"HOLD PERSON"}
    EMPTY_TO_MAGIC = False
    #: The Magic bar's screen shows the animated camp fire, which lies in the
    #: spell list's region: each capture of it differs there.
    FIRE = False
    _fire = 0

    def __init__(self, *a, failure: str = "", rows=None, flip_at=None, **k):
        super().__init__(*a, **k)
        self.failure = failure
        # `flip_at` is (mode, position, n): the screen becomes an unknown one
        # after the nth capture of that mode with the list highlight, or the
        # target line, at that position; `flipped_at` is how many keys had
        # been pressed by then.
        self.flip_at, self.seen, self.flipped_at = flip_at, 0, None
        # The caster's roster line, and the target prompt's highlight, which
        # opens on the caster and leaves the caster highlighted after it.
        self.line = self.aim = 1
        self.rows = list(rows or _CAST_ROWS)
        self.hl = self.last_spell()
        self.message = 0
        self.pending: str | None = None
        self.cast: list[tuple[str, int | None]] = []

    def spell_rows(self) -> list[int]:
        return [i for i, (kind, _) in enumerate(self.rows) if kind == "spell"]

    def last_spell(self) -> int | None:
        spells = self.spell_rows()
        return spells[-1] if spells else None

    def finish(self, target: int | None) -> None:
        self.message = 0 if self.failure == "no_return" else 3
        self.mode = "message"
        self.cast.append((self.pending, target))

    def key(self, k, gap=0.0):
        handled = True
        if self.mode == "camp" and k == "End":
            self.line = self.line % 6 + 1
        elif self.mode == "target" and k == "End":
            self.aim = self.aim % 6 + 1
        elif self.mode == "camp" and k == "m":
            self.mode = "wrong" if self.failure == "magic" else "magic"
        elif self.mode == "magic" and k == "c":
            if self.cast and self.failure == "no_reopen":
                self.mode = "wrong"
            elif self.spell_rows() or not self.EMPTY_TO_MAGIC:
                self.mode, self.hl = "list", self.last_spell()
        elif self.mode == "list" and k == "End":
            spells = self.spell_rows()
            self.hl = spells[(spells.index(self.hl) + 1) % len(spells)]
        elif self.mode == "list" and k == "c":
            self.pending = self.rows[self.hl][1]
            if self.failure == "unknown":
                self.mode = "wrong"
            elif self.pending in self.COMBAT_ONLY:
                self.mode = "lose"
            elif self.pending in self.TARGETED:
                self.mode = "prompt" if self.failure == "prompt" else "target"
                self.aim = self.line
            else:
                self.finish(None)
        elif self.mode == "target" and k == "Return":
            self.finish(self.aim)
        elif self.mode == "list" and k == "e":
            self.mode = "magic"
        elif self.mode == "magic" and k == "e":
            self.mode = "magic" if self.failure == "exit" else "camp"
        elif self.mode in ("magic", "list", "message", "target", "lose", "wrong",
                           "prompt"):
            pass
        else:
            handled = False
        if handled:
            self.keys.append(k)
        else:
            super().key(k, gap)

    def _frame(self, mode: str) -> bytearray:
        px = bytearray(W * H * 3)
        _text(px, da.BAR_ROW, 0, self.BAR_TEXT[mode])
        return px

    def _roster(self, px: bytearray) -> dosbox.Screen:
        x, y = screens.POD_ROSTER["camp"]
        lit = self.aim if self.mode == "target" else self.line
        for n, name in enumerate(_CAST_NAMES, 1):
            _text(px, y // 8 + n - 1, x // 8, name, _WHITE if n == lit else _CYAN)
        return dosbox.Screen(W, H, bytes(px))

    def _list_frame(self, highlight: bool, hide: str | None = None) -> dosbox.Screen:
        px = self._frame("list")
        who = 1 if self.failure == "wrong_title" else self.line
        _text(px, 1, 1, f"{_CAST_NAMES[who - 1]}'S SPELLS IN MEMORY")
        for i, (kind, text) in enumerate(self.rows):
            row = da.SCRIBE_LIST[1] // 8 + i
            if kind == "level":
                _text(px, row, 1, text, _CAST_HEAD)
            elif text != hide:
                shown = text
                if (self.failure == "unreadable" and text == "BLESS") or (
                        self.failure == "garbled_after" and self.cast
                        and text == self.pending):
                    shown = text[:2] + "?" + text[3:]
                _text(px, row, 3, shown, _WHITE if highlight and i == self.hl
                      else _CAST_LIST_GREEN)
        if self.mode == "message":
            # The message window over the list's foot.
            _text(px, 18, 1, f"{_CAST_NAMES[self.line - 1]} CASTS")
            _text(px, 19, 1, self.pending or "")
        return dosbox.Screen(W, H, bytes(px))

    def _magic_frame(self) -> dosbox.Screen:
        px = self._frame("magic")
        if self.FIRE:
            CastPool._fire += 1
            _draw_name(px, 40, 48 + 8 * (self._fire % 5), b"\x0f\x33", _WHITE)
        return self._roster(px)

    def capture(self):
        if self.mode == "magic":
            return self._magic_frame()
        if self.mode == "message":
            hide = None
            if self.message:
                self.message -= 1
                # The message window hides the row, then the full list comes
                # back: nothing was cast.
                hide = self.pending if self.failure == "hidden_row" else None
                if not self.message:
                    if self.failure not in ("hidden_row", "blocked", "garbled_after"):
                        del self.rows[next(i for i, r in enumerate(self.rows)
                                           if r == ("spell", self.pending))]
                    self.mode, self.hl = "list", self.last_spell()
                    if self.EMPTY_TO_MAGIC and (not self.spell_rows() or self.failure
                                                in ("blocked", "garbled_after")):
                        self.mode = "magic"
            if self.mode == "magic":
                return self._magic_frame()
            return self._list_frame(highlight=False, hide=hide)
        if self.mode in ("list", "target"):
            here = self.hl if self.mode == "list" else self.aim
            if self.flip_at and self.flip_at[:2] == (self.mode, here):
                self.seen += 1
            frame = (self._list_frame(highlight=True) if self.mode == "list" else
                     self._roster(self._frame("target")))
            if self.flip_at and self.seen == self.flip_at[2]:
                self.seen = -1
                self.mode, self.flipped_at = "wrong", len(self.keys)
            return frame
        if self.mode in ("camp", "lose", "wrong", "prompt"):
            return self._roster(self._frame(self.mode))
        return super().capture()

    def wait_for(self, pred, timeout: float = 30.0) -> bool:
        return any(pred(self.capture()) for _ in range(10))


@pytest.fixture
def _cast_measured(monkeypatch, tmp_path):
    """The fake's bars stand in for the measured ones, and the stand-in font
    for the title's own."""
    game = dosbox.PoolOfRadiance
    (tmp_path / "probe").mkdir()
    probe = CastPool(tmp_path / "probe")
    for attr, mode in (("CAMP_BAR", "camp"), ("MAGIC_BAR", "magic"),
                       ("SPELL_LIST_BAR", "list"), ("TARGET_BAR", "target"),
                       ("LOSE_IT_BAR", "lose")):
        monkeypatch.setattr(game, attr, screens.bar_signature(
            dosbox.Screen(W, H, bytes(probe._frame(mode)))))
    monkeypatch.setattr(dosbox, "find_game", lambda stem="POOLRAD": tmp_path)
    monkeypatch.setattr(da, "load_font", lambda game: _FONT)
    now = [0.0]

    def tick():
        now[0] += 1.0
        return now[0]

    # Time moves a second per look, so the settling check needs no waiting.
    monkeypatch.setattr(dosbox, "time", type("T", (), {
        "time": staticmethod(tick), "sleep": staticmethod(lambda s: None)}))


def _cast_camp(tmp_path, **kw) -> tuple[CastPool, da.Driver]:
    (tmp_path / "game").mkdir()
    game = CastPool(tmp_path / "game", **kw)
    d = da.Driver(game, lambda **k: None, "A")
    d.camp()
    return game, d


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_cast_bless_picks_the_caster_casts_once_and_returns_to_camp(
        tmp_path, _cast_measured):
    game, d = _cast_camp(tmp_path)
    got = d.cast(2, "BLESS")
    assert game.keys == ["e", "End", "m", "c", "End", "c", "e", "e"]
    assert game.cast == [("BLESS", None)]
    assert got["rows_before"] == 1 and got["rows_after"] == 0
    assert got["line"] == 2 and got["name"] == "WISHCLE" and got["target"] is None
    assert got["asked_target"] is False and "confirmed" not in got
    assert got["listed"] == ["BLESS", "CURE LIGHT WOUNDS", "CURE LIGHT WOUNDS",
                             "HOLD PERSON"]
    assert game.mode == "camp" and d.where == "camp"
    d.save("D")
    assert game.save_file("D").is_file()


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_cast_a_targeted_spell_picks_the_target_with_end_and_return(
        tmp_path, _cast_measured):
    game, d = _cast_camp(tmp_path)
    got = d.cast(2, "CURE-LIGHT-WOUNDS", 4)
    # End twice from the last row to the first CLW, End twice at the target
    # screen from the caster's line (2) to line 4.
    assert game.keys == ["e", "End", "m", "c", "End", "End", "c", "End", "End",
                         "Return", "e", "e"]
    assert game.cast == [("CURE LIGHT WOUNDS", 4)]
    assert got["rows_before"] == 2 and got["rows_after"] == 1
    assert got["asked_target"] is True and got["target"] == 4
    assert game.mode == "camp"


@pytest.mark.parametrize("text,cast", [
    ("cast 2 RESIST-COLD 3", ("RESIST COLD", 3)),
    ("cast 2 resist cold 3", ("RESIST COLD", 3)),
    ("cast 2 DETECT-MAGIC", ("DETECT MAGIC", None)),
    ("cast 2 PROTECTION FROM EVIL 10' RADIUS", ("PROTECTION FROM EVIL 10' RADIUS", None)),
])
@pytest.mark.usefixtures("pool_map_measured")
def test_pool_cast_takes_any_spell_on_the_list_and_the_target_only_when_asked(
        tmp_path, _cast_measured, text, cast):
    rows = _cast_rows("DETECT MAGIC", "RESIST COLD", "PROTECTION FROM EVIL 10' RADIUS",
                      "RESIST COLD")
    game, d = _cast_camp(tmp_path, rows=rows)
    step = da.parse_step(text)
    got = d.cast(step.line, step.name, step.row or None)
    assert game.cast == [cast]
    assert got["asked_target"] is (cast[1] is not None)
    assert got["rows_after"] == got["rows_before"] - 1
    assert game.mode == "camp"


@pytest.mark.parametrize("failure,rows,why", [
    ("magic", None, "Magic bar"),
    ("wrong_title", None, "WISHFTR'S SPELLS IN MEMORY"),
    ("", _cast_rows("CURE LIGHT WOUNDS", "HOLD PERSON"), "BLESS is not in the caster's"),
    ("unreadable", None, "do not read"),
    ("unknown", None, "a screen it does not know: 'PRESS ANY KEY TO CONTINUE'"),
    ("no_return", None, "never came back"),
    ("hidden_row", None, "did not settle"),
])
@pytest.mark.usefixtures("pool_map_measured")
def test_pool_cast_stops_at_an_unexpected_screen_before_any_save(
        tmp_path, _cast_measured, failure, rows, why):
    game, d = _cast_camp(tmp_path, failure=failure, rows=rows)
    with pytest.raises(da.StepFailed, match=why):
        d.cast(2, "BLESS")
    assert not game.save_file("D").exists()
    if failure in ("magic", "wrong_title", "unreadable") or rows:
        assert game.cast == []                  # stopped before any cast key
    assert "e" not in game.keys[1:]             # never pressed Exit anywhere


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_cast_the_message_window_naming_the_spell_is_not_a_row(
        tmp_path, _cast_measured, monkeypatch):
    # The window draws the spell's name at column 3, where a row would be:
    # while it shows, the list still reads as many rows as before the key.
    game, d = _cast_camp(tmp_path)
    frames = []
    real = game._list_frame

    def spy(highlight, hide=None):
        frame = real(highlight, hide)
        if game.mode == "message":
            px = bytearray(frame.px)
            _text(px, 20, 3, game.pending)
            frame = dosbox.Screen(W, H, bytes(px))
            frames.append(frame)
        return frame
    monkeypatch.setattr(game, "_list_frame", spy)
    got = d.cast(2, "CURE-LIGHT-WOUNDS", 3)
    assert frames and got["rows_after"] == 1


@pytest.mark.parametrize("spell,target,at", [
    # Mid-loop, then at the capture made just before the key that ends it:
    # the list at its first and its second End (the second is the row cast),
    # the target roster at line 3 and at line 4 (the line picked).
    ("CURE-LIGHT-WOUNDS", 4, ("list", 1, 1)),
    ("CURE-LIGHT-WOUNDS", 4, ("list", 2, 1)),
    ("CURE-LIGHT-WOUNDS", 4, ("list", 2, 2)),
    ("CURE-LIGHT-WOUNDS", 4, ("target", 3, 1)),
    ("CURE-LIGHT-WOUNDS", 4, ("target", 4, 1)),
    ("CURE-LIGHT-WOUNDS", 4, ("target", 4, 2)),
])
@pytest.mark.usefixtures("pool_map_measured")
def test_pool_cast_rechecks_the_screen_before_every_key_after_the_first(
        tmp_path, _cast_measured, spell, target, at):
    game, d = _cast_camp(tmp_path, flip_at=at)
    with pytest.raises(da.StepFailed, match="changed under the keys"):
        d.cast(2, spell, target)
    assert game.flipped_at is not None
    assert game.flipped_at == len(game.keys)       # nothing pressed after it
    assert game.cast == []


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_cast_a_target_prompt_with_no_target_named_presses_nothing_more(
        tmp_path, _cast_measured):
    game, d = _cast_camp(tmp_path)
    with pytest.raises(da.StepFailed, match="asks CAST SPELL ON WHOM and the step "
                       "names no target"):
        d.cast(2, "CURE-LIGHT-WOUNDS")
    assert game.mode == "target" and game.keys[-1] == "c" and game.cast == []


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_cast_a_target_named_for_a_spell_that_asks_none_fails_after_it(
        tmp_path, _cast_measured):
    game, d = _cast_camp(tmp_path)
    with pytest.raises(da.StepFailed, match="went off without asking"):
        d.cast(2, "BLESS", 3)
    assert game.cast == [("BLESS", None)]
    assert "Return" not in game.keys and "e" not in game.keys[1:]


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_cast_a_target_prompt_on_another_bar_is_named_and_not_answered(
        tmp_path, _cast_measured):
    game, d = _cast_camp(tmp_path, failure="prompt")
    with pytest.raises(da.StepFailed, match="asks for a target on a screen it does "
                       "not know: 'CHOOSE WHOM: PICK EXIT'"):
        d.cast(2, "CURE-LIGHT-WOUNDS", 4)
    assert game.mode == "prompt" and game.keys[-1] == "c"


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_cast_the_last_memorised_spell_needs_no_highlight_to_be_believed(
        tmp_path, _cast_measured):
    game, d = _cast_camp(tmp_path, rows=_cast_rows("BLESS"))
    got = d.cast(2, "BLESS")
    assert game.rows == [("level", "1ST LEVEL")] and got["rows_after"] == 0
    assert "confirmed" not in got and game.mode == "camp"


@pytest.mark.parametrize("spell,target", [("ANIMATE-DEAD", None), ("SLOW-POISON", 1)])
@pytest.mark.usefixtures("pool_map_measured")
def test_pool_cast_the_only_spell_back_at_the_magic_bar_is_checked_by_cast_again(
        tmp_path, _cast_measured, monkeypatch, spell, target):
    monkeypatch.setattr(CastPool, "EMPTY_TO_MAGIC", True)
    game, d = _cast_camp(tmp_path, rows=_cast_rows(da.spell_key(spell)))
    got = d.cast(2, spell, target)
    assert got["confirmed"] == "memory-empty" and got["rows_after"] == 0
    assert game.cast == [(da.spell_key(spell), target)]
    # CAST twice at the Magic bar opens nothing, and EXIT goes to camp.
    assert game.keys.count("m") == 1 and game.keys[-3:] == ["c", "c", "e"]
    assert game.mode == "camp"


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_cast_settles_although_the_camp_fire_moves_in_the_list_region(
        tmp_path, _cast_measured, monkeypatch):
    monkeypatch.setattr(CastPool, "EMPTY_TO_MAGIC", True)
    monkeypatch.setattr(CastPool, "FIRE", True)
    game, d = _cast_camp(tmp_path, rows=_cast_rows("ANIMATE DEAD", level="3RD LEVEL"))
    assert d.cast(2, "ANIMATE-DEAD")["confirmed"] == "memory-empty"
    assert game.mode == "camp"


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_cast_a_rejection_back_at_the_magic_bar_fails_on_the_reopened_list(
        tmp_path, _cast_measured, monkeypatch):
    monkeypatch.setattr(CastPool, "EMPTY_TO_MAGIC", True)
    game, d = _cast_camp(tmp_path, rows=_cast_rows("BLESS"), failure="blocked")
    with pytest.raises(da.StepFailed, match="opened again still holds 1 BLESS"):
        d.cast(2, "BLESS")
    assert game.mode == "list" and game.keys[-1] == "c"


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_cast_an_unreadable_row_after_the_cast_is_never_counted_as_one_fewer(
        tmp_path, _cast_measured):
    # The game keeps both rows, one of them unreadable: counting only the rows
    # that read would take it for a cast.
    game, d = _cast_camp(tmp_path, failure="garbled_after")
    with pytest.raises(da.StepFailed, match="the spell list after the cast has rows "
                       "that do not read: \\['CU\\?E LIGHT WOUNDS'"):
        d.cast(2, "CURE-LIGHT-WOUNDS", 3)
    assert game.keys[-1] == "Return"


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_cast_an_unreadable_row_on_the_reopened_list_is_blocked(
        tmp_path, _cast_measured, monkeypatch):
    monkeypatch.setattr(CastPool, "EMPTY_TO_MAGIC", True)
    game, d = _cast_camp(tmp_path, rows=_cast_rows("BLESS"), failure="garbled_after")
    with pytest.raises(da.StepFailed, match="the spell list opened again has rows "
                       "that do not read: \\['BL\\?SS'\\]"):
        d.cast(2, "BLESS")
    assert game.mode == "list" and game.keys[-1] == "c"


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_cast_a_reopened_list_under_another_title_is_blocked(
        tmp_path, _cast_measured, monkeypatch):
    monkeypatch.setattr(CastPool, "EMPTY_TO_MAGIC", True)
    game, d = _cast_camp(tmp_path, rows=_cast_rows("BLESS"), failure="blocked")
    real = game._list_frame

    def other_title(highlight, hide=None):
        frame = real(highlight, hide)
        if game.cast and game.mode == "list":
            px = bytearray(frame.px)
            for y in range(8, 16):
                px[y * W * 3:(y + 1) * W * 3] = bytes(W * 3)
            _text(px, 1, 1, "WISHCLE'S SPELLS ON SCROLLS")
            frame = dosbox.Screen(W, H, bytes(px))
        return frame
    monkeypatch.setattr(game, "_list_frame", other_title)
    with pytest.raises(da.StepFailed, match="the spell list opened again is titled "
                       "\"WISHCLE'S SPELLS ON SCROLLS\""):
        d.cast(2, "BLESS")


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_cast_a_reopen_that_opens_no_list_stops_there(
        tmp_path, _cast_measured, monkeypatch):
    monkeypatch.setattr(CastPool, "EMPTY_TO_MAGIC", True)
    game, d = _cast_camp(tmp_path, rows=_cast_rows("BLESS"), failure="no_reopen")
    with pytest.raises(da.StepFailed, match="CAST again reached a screen it does not "
                       "know: 'PRESS ANY KEY TO CONTINUE'"):
        d.cast(2, "BLESS")
    assert game.mode == "wrong" and game.keys[-1] == "c"


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_cast_with_rows_left_is_never_believed_through_the_magic_bar(
        tmp_path, _cast_measured, monkeypatch):
    monkeypatch.setattr(CastPool, "EMPTY_TO_MAGIC", True)
    game, d = _cast_camp(tmp_path, rows=_cast_rows("BLESS", "BLESS"), failure="blocked")
    with pytest.raises(da.StepFailed, match="never came back one BLESS shorter"):
        d.cast(2, "BLESS")


# -- a camp cast in Curse and Silver Blades ------------------------------------

#: The keys each later title's camp cast takes, written out here rather than
#: taken from the driver: the roster's and the spell list's move key, and
#: `SELECT` at the target prompt.
_LATER_CAST_KEYS = {"curse": ("End", "End", "s"), "ssb": ("Down", "Down", "s")}
#: Strength twice between a first- and a third-level spell, so the list opens
#: on another row and has to be walked to it.
_LATER_CAST_ROWS = [("level", "1ST LEVEL"), ("spell", "SHIELD"), ("level", "2ND LEVEL"),
                    ("spell", "STRENGTH"), ("spell", "STRENGTH"), ("level", "3RD LEVEL"),
                    ("spell", "HASTE")]


class CastLater(CastPool):
    """Curse's and Silver Blades' camp `MAGIC > CAST`, as the live casts
    showed them: Pool's screens and bars but for the camp bar, copies of one
    spell drawn as one row `STRENGTH (2)`, the title's own roster and list
    keys, and `S` picking the target, where `Return` leaves the prompt for the
    list without casting.  Casting the last memorised spell goes back to the
    Magic bar, where `CAST` opens nothing."""

    EMPTY_TO_MAGIC = True
    TARGETED = CastPool.TARGETED | {"STRENGTH"}

    def __init__(self, tmp, title: str, **kw):
        super().__init__(tmp, **kw)
        self.title = title
        self.roster_key, self.list_key, self.select = _LATER_CAST_KEYS[title]
        self.BAR_TEXT = {**CastPool.BAR_TEXT,
                         "camp": {"curse": "CAMP:SAVE VIEW MAGIC REST ALTER FIX EXIT",
                                  "ssb": "SAVE VIEW MAGIC REST ALTER FIX EXIT"}[title]}

    def groups(self) -> list[tuple[str, str, list[int]]]:
        """The rows as drawn: a heading, or a spell with the copies it stands for."""
        out: list[tuple[str, str, list[int]]] = []
        for i, (kind, text) in enumerate(self.rows):
            if kind == "spell" and out and out[-1][:2] == ("spell", text):
                out[-1][2].append(i)
            else:
                out.append((kind, text, [i]))
        return out

    def spell_rows(self) -> list[int]:
        return [ix[0] for kind, _, ix in self.groups() if kind == "spell"]

    def key(self, k, gap=0.0):
        mode = self.mode
        if mode in ("camp", "target") and k == self.roster_key:
            super().key("End")
        elif mode == "list" and k == self.list_key:
            super().key("End")
        elif mode == "target" and k == self.select:
            super().key("Return")
        elif k in ("End", "Return") and mode in ("camp", "target", "list"):
            if mode == "target" and k == "Return":
                self.mode = "list"
            self.keys.append(k)
            return
        else:
            super().key(k, gap)
            return
        self.keys[-1] = k

    def _list_frame(self, highlight: bool, hide: str | None = None) -> dosbox.Screen:
        px = self._frame("list")
        _text(px, 1, 1, f"{_CAST_NAMES[self.line - 1]}'S SPELLS IN MEMORY")
        for row, (kind, text, ix) in enumerate(self.groups()):
            y = da.SCRIBE_LIST[1] // 8 + row
            if kind == "level":
                _text(px, y, 1, text, _CAST_HEAD)
            else:
                shown = text if len(ix) == 1 else f"{text} ({len(ix)})"
                _text(px, y, 3, shown, _WHITE if highlight and self.hl in ix
                      else _CAST_LIST_GREEN)
        return dosbox.Screen(W, H, bytes(px))


def _later_cast_camp(tmp_path, title, **kw) -> tuple[CastLater, da.Driver]:
    (tmp_path / "game").mkdir()
    game = CastLater(tmp_path / "game", title, keys=TITLE_KEYS[title], **kw)
    d = da.Driver(game, lambda **k: None, "A", title)
    d.camp()
    return game, d


@pytest.mark.parametrize("title", ["curse", "ssb"])
def test_the_cast_step_parses_and_is_taken_in_camp_in_curse_and_silver_blades(title):
    step = da.parse_step("cast 6 strength 2")
    assert (step.kind, step.line, step.name, step.row) == ("cast", 6, "STRENGTH", 2)
    da.validate_steps(_steps("load", "begin", "camp", "snapshot c0", "cast 6 STRENGTH 2",
                             "cast 6 STRENGTH 3", "save B", "read"), title)
    with pytest.raises(ValueError, match="cast needs camp first"):
        da.validate_steps(_steps("load", "begin", "cast 6 STRENGTH 2"), title)


def test_the_cast_step_is_blocked_in_pools_of_darkness():
    with pytest.raises(ValueError, match="cast is driven in curse, pool, ssb only"):
        da.validate_steps(_steps("load", "begin", "camp", "cast 6 STRENGTH 2"),
                          "darkness")


@pytest.mark.parametrize("title", ["curse", "ssb"])
def test_later_cast_walks_the_counted_row_picks_the_target_with_select(
        tmp_path, _cast_measured, title):
    roster, down, select = _LATER_CAST_KEYS[title]
    game, d = _later_cast_camp(tmp_path, title, rows=_LATER_CAST_ROWS)
    got = d.cast(6, "STRENGTH", 2)
    # Line 1 to 6 on the roster; the list opens on HASTE, its last row, and
    # wraps to SHIELD then STRENGTH; the target prompt opens on the caster
    # (6) and wraps to 2; SELECT casts; EXIT twice to camp.
    assert game.keys == ["e", *[roster] * 5, "m", "c", down, down, "c", roster, roster,
                         select, "e", "e"]
    assert game.cast == [("STRENGTH", 2)]
    assert got["listed"] == ["SHIELD", "STRENGTH", "STRENGTH", "HASTE"]
    assert got["rows_before"] == 2 and got["rows_after"] == 1
    assert got["name"] == "WISHHEL" and got["target"] == 2 and got["asked_target"]
    assert "confirmed" not in got and game.mode == "camp" and d.where == "camp"
    d.save("B")
    assert game.save_file("B").is_file()


@pytest.mark.parametrize("title", ["curse", "ssb"])
def test_later_cast_of_the_last_copy_is_checked_by_cast_again_at_the_magic_bar(
        tmp_path, _cast_measured, title):
    roster, _, select = _LATER_CAST_KEYS[title]
    game, d = _later_cast_camp(tmp_path, title, rows=_cast_rows("STRENGTH",
                                                                level="2ND LEVEL"))
    got = d.cast(1, "STRENGTH", 3)
    assert game.keys == ["e", "m", "c", "c", roster, roster, select, "c", "c", "e"]
    assert got["confirmed"] == "memory-empty" and got["rows_after"] == 0
    assert game.cast == [("STRENGTH", 3)] and game.mode == "camp"


def test_later_cast_with_pools_return_never_casts(tmp_path, _cast_measured, monkeypatch):
    # Pool's `Return` at the prompt leaves it in Curse's fake: the step must
    # send `S`, and with `Return` it stops rather than believing a cast.
    monkeypatch.setitem(da.CAST_SELECT, "curse", "Return")
    game, d = _later_cast_camp(tmp_path, "curse", rows=_LATER_CAST_ROWS)
    with pytest.raises(da.StepFailed, match="never came back one STRENGTH shorter"):
        d.cast(6, "STRENGTH", 2)
    assert game.cast == [] and not game.save_file("B").exists()


@pytest.mark.parametrize("title", ["pool", "curse", "ssb"])
@pytest.mark.usefixtures("pool_map_measured")
def test_cast_passes_the_recorded_camp_bar_only_in_curse_and_silver_blades(
        tmp_path, _cast_measured, monkeypatch, title):
    # Pool keeps the measured `PoolOfRadiance.CAMP_BAR`: the step passes no
    # camp bar there, so `cast` falls back to the constant.
    if title == "pool":
        game, d = _cast_camp(tmp_path)
    else:
        game, d = _later_cast_camp(tmp_path, title, rows=_LATER_CAST_ROWS)
    seen = {}
    real = d.game.cast

    def spy(*a, **k):
        seen.update(k)
        return real(*a, **k)
    monkeypatch.setattr(d.game, "cast", spy)
    d.cast(2 if title == "pool" else 6, "BLESS" if title == "pool" else "STRENGTH",
           None if title == "pool" else 2)
    if title == "pool":
        assert seen["camp_bar"] is None
        assert dosbox.PoolOfRadiance.CAMP_BAR == screens.bar_signature(
            dosbox.Screen(W, H, bytes(game._frame("camp"))))
    else:
        assert seen["camp_bar"] == d.camp_sig != dosbox.PoolOfRadiance.CAMP_BAR


@pytest.mark.parametrize("title", ["curse", "ssb"])
def test_later_cast_of_a_spell_not_on_the_list_presses_nothing_after_cast(
        tmp_path, _cast_measured, title):
    game, d = _later_cast_camp(tmp_path, title, rows=_LATER_CAST_ROWS)
    with pytest.raises(da.StepFailed, match="BLESS is not in the caster's memory"):
        d.cast(6, "BLESS", 2)
    assert game.keys[-2:] == ["m", "c"] and game.mode == "list"
    assert game.cast == [] and not game.save_file("B").exists()


@pytest.mark.parametrize("drawn,spells", [
    ("STRENGTH (1)", ((1, "STRENGTH"),)),
    ("STRENGTH", ((1, "STRENGTH"),)),
    # No copy is not a count: the row keeps its words, which no spell matches.
    ("STRENGTH (0)", ((1, "STRENGTH (0)"),)),
])
def test_a_list_row_reads_as_its_count_of_copies(drawn, spells):
    px = bytearray(W * H * 3)
    _text(px, 1, 1, "WISHHEL'S SPELLS IN MEMORY")
    _text(px, da.SCRIBE_LIST[1] // 8, 1, "2ND LEVEL", _CAST_HEAD)
    _text(px, da.SCRIBE_LIST[1] // 8 + 1, 3, drawn, _WHITE)
    assert da.cast_list(dosbox.Screen(W, H, bytes(px)), _FONT).spells == spells


def test_a_counted_row_reads_as_that_many_copies_on_one_row(tmp_path):
    game = CastLater(tmp_path, "ssb", rows=_LATER_CAST_ROWS)
    game.mode = "list"
    got = da.cast_list(game._list_frame(highlight=True), _FONT)
    assert got.head == "WISHFTR'S SPELLS IN MEMORY"
    assert got.spells == ((1, "SHIELD"), (3, "STRENGTH"), (3, "STRENGTH"), (5, "HASTE"))


def test_the_measured_cast_screens_read_as_text():
    """`667/aed7e96fc4-sp1-list`: WISHCLE's list holding Slow Poison alone,
    read with Pool's own font, and the target prompt it opened."""
    try:
        font = da.load_font(dosbox.find_game("POOLRAD"))
    except FileNotFoundError:
        pytest.skip("needs the DOS archives ($FR_ARCHIVES)")
    listed = _capture("aed7e96fc4-sp1-list", "007-sp-list", "667")
    got = da.cast_list(listed, font)
    assert screens.bar_signature(listed) == dosbox.PoolOfRadiance.SPELL_LIST_BAR
    assert got.head == "WISHCLE'S SPELLS IN MEMORY"
    assert got.bar == "CHOOSE SPELL: CAST EXIT"
    assert got.spells == ((1, "SLOW POISON"),) and listed.highlight_row(
        dosbox.PoolOfRadiance.SPELL_LIST) == 1
    target = _capture("aed7e96fc4-sp1-list", "009-sp-target", "667")
    assert screens.bar_signature(target) == dosbox.PoolOfRadiance.TARGET_BAR
    assert da.cast_list(target, font).bar == "CAST SPELL ON WHOM SELECT EXIT"


@pytest.mark.parametrize("stem,run,caster", [
    ("CURSE", "6e6a1b0e90-curse-cast", "PHILIPPE"),
    ("SECRET", "6e6a1b0e90-ssb-cast", "MORGAINE"),
])
def test_the_measured_later_cast_screens_read_as_text(stem, run, caster):
    """The `cast` step's live runs in Curse and Silver Blades under DOSBox-X:
    Pool's Magic, list and target bars, the list opening on its last row with
    Strength memorised twice drawn as one counted row, and one copy fewer
    after the first cast."""
    try:
        font = da.load_font(dosbox.find_game(stem))
    except FileNotFoundError:
        pytest.skip("needs the DOS archives ($FR_ARCHIVES)")
    game = dosbox.PoolOfRadiance
    shot = {"CURSE": ("007-cast-magic", "008-cast-list", "009-cast-spell",
                      "010-cast-target", "011-cast-done"),
            "SECRET": ("008-cast-magic", "009-cast-list", "010-cast-spell",
                       "011-cast-target", "012-cast-done")}[stem]
    magic, listed, spell, target, done = (_capture(run, n, "274", size="50%")
                                          for n in shot)
    assert screens.bar_signature(magic) == game.MAGIC_BAR
    got = da.cast_list(listed, font)
    assert screens.bar_signature(listed) == game.SPELL_LIST_BAR
    assert got.head == f"{caster}'S SPELLS IN MEMORY"
    assert got.spells == ((1, "READ MAGIC"), (3, "STRENGTH"), (3, "STRENGTH"),
                          (5, "HASTE"))
    assert listed.highlight_row(game.SPELL_LIST) == 5
    assert spell.highlight_row(game.SPELL_LIST) == 3
    assert screens.bar_signature(target) == game.TARGET_BAR
    assert da.cast_list(target, font).bar == "CAST SPELL ON WHOM SELECT EXIT"
    assert da.cast_list(done, font).spells == ((1, "READ MAGIC"), (3, "STRENGTH"),
                                               (5, "HASTE"))


def test_the_measured_magic_bar_screen_has_picture_in_the_spell_list_region():
    """`5bd423dc82-run2-animate/010-lost-cast-2`: the Magic bar after the cast
    shows the camp fire where the list's rows are read, so only its bar is
    compared from one capture to the next."""
    screen = _capture("5bd423dc82-run2-animate", "010-lost-cast-2", "700")
    game = dosbox.PoolOfRadiance
    assert screens.bar_signature(screen) == game.MAGIC_BAR
    x, y, w, h = game.SPELL_LIST
    assert not screen.flat((x, y, w, h))


def test_expect_accepts_a_decimal_with_a_leading_zero():
    assert da.parse_expect("WISHFTR:32:0:05") == da.Expect("WISHFTR", 32, 0, 5)
    assert da.parse_expect("WISHFTR:32:0:010").data == 10
    assert da.parse_expect("WISHFTR:32:0:0xB3").data == 0xB3


def test_pool_cast_animate_dead_step_parses_and_save_and_read_may_follow():
    step = da.parse_step("cast 2 animate-dead")
    assert (step.kind, step.line, step.name, step.row) == ("cast", 2, "ANIMATE-DEAD", 0)
    assert da.parse_step("cast 2 Animate Dead").name == "ANIMATE-DEAD"
    da.validate_steps(_steps("load", "sheet 1", "camp", "cast 2 ANIMATE-DEAD",
                             "save D", "read"), "pool")


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_cast_a_target_line_outside_the_party_is_blocked_before_any_key(
        tmp_path, _cast_measured):
    game, d = _cast_camp(tmp_path)
    with pytest.raises(da.StepFailed, match="target line 8 is not in a party of 6"):
        d.cast(2, "CURE-LIGHT-WOUNDS", 8)
    assert game.keys == ["e"] and game.mode == "camp"     # only camp's ENCAMP
    with pytest.raises(ValueError, match="target line 7 is not in a party of 6"):
        d.game.cast("CURE LIGHT WOUNDS", 7, read=lambda sc: None)
    assert game.keys == ["e"]


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_cast_stops_when_exit_never_reaches_camp(tmp_path, _cast_measured):
    game, d = _cast_camp(tmp_path, failure="exit")
    with pytest.raises(da.StepFailed, match="camp bar did not come back"):
        d.cast(2, "BLESS")
    assert game.mode == "magic" and not game.save_file("D").exists()


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_cast_never_answers_lose_it(tmp_path, _cast_measured):
    game, d = _cast_camp(tmp_path)
    with pytest.raises(da.StepFailed, match="LOSE IT"):
        d.cast(2, "HOLD-PERSON")
    assert game.mode == "lose" and game.keys[-1] == "c"


def test_pool_cast_steps_parse_and_a_bad_one_is_blocked():
    step = da.parse_step("cast 2 bless")
    assert (step.kind, step.line, step.name, step.row) == ("cast", 2, "BLESS", 0)
    step = da.parse_step("cast 2 CURE-LIGHT-WOUNDS 5")
    assert (step.line, step.name, step.row) == (2, "CURE-LIGHT-WOUNDS", 5)
    step = da.parse_step("cast 3 Invisibility 10' Radius")
    assert (step.line, step.name, step.row) == (3, "INVISIBILITY-10'-RADIUS", 0)
    step = da.parse_step("cast 2 protection from evil 6")
    assert (step.name, step.row) == ("PROTECTION-FROM-EVIL", 6)
    for bad, why in (("cast 2 BLESS 9", "lines 1 to 8"),
                     ("cast 9 BLESS", "not a step"),
                     ("cast 2", "not a step")):
        with pytest.raises(ValueError, match=why):
            da.parse_step(bad)


@pytest.mark.parametrize("title,steps,why", [
    ("pool", ("load", "camp", "cast 2 BLESS", "cast 2 BLESS", "save D", "read"), None),
    ("pool", ("load", "cast 2 BLESS"), "cast needs camp first"),
    ("curse", ("load", "begin", "camp", "cast 2 BLESS", "save D", "read"), None),
    ("darkness", ("load", "begin", "camp", "cast 2 BLESS"), "curse, pool, ssb only"),
])
def test_pool_cast_step_orders(title, steps, why):
    if why is None:
        da.validate_steps(_steps(*steps), title)
        return
    with pytest.raises(ValueError, match=why):
        da.validate_steps(_steps(*steps), title)


@pytest.mark.parametrize("failure", ("", "caster", "wrong_member", "repeated_page",
                                     "unknown_return", "moved_highlight",
                                     "unmeasured", "unmeasured_sheet"))
def test_pool_sheet_selects_named_member_and_returns_to_map_before_save(
        tmp_path, monkeypatch, failure):
    class SheetPool(FakePool):
        BARS = {**FakePool.BARS, "sheet": b"\x15\x48\x7b", "wrong": b"\x16\x49\x7c",
                "caster": b"\x17\x4a\x7d"}

        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.line = 1

        def key(self, k, gap=0.0):
            self.keys.append(k)
            if self.mode == "map" and k == "End":
                self.line = self.line % 6 + 1
            elif self.mode == "map" and k == "v":
                self.mode = "sheet"
            elif self.mode == "sheet" and k == "Escape":
                self.mode = "wrong" if failure == "unknown_return" else "map"
                if failure == "moved_highlight":
                    self.line = self.line % 6 + 1

        def capture(self):
            frame = super().capture()
            if self.mode == "map":
                return _with_roster(frame, "camp", 6, self.line)
            if self.mode == "sheet":
                who = 1 if failure == "wrong_member" else self.line
                bar = "caster" if failure == "caster" else "sheet"
                return _with_roster(_screen(self.BARS[bar], b""), "camp", 6, 0, sheet=who)
            return frame

    monkeypatch.setattr(da, "POOL_MAP_BARS", {} if failure == "unmeasured" else
                        {"town": screens.bar_signature(_screen(SheetPool.BARS["map"], b""))})
    monkeypatch.setattr(da, "POOL_SHEET_BARS", {"town": screens.bar_signature(
        _screen(SheetPool.BARS["wrong"], b""))} if failure == "unmeasured_sheet" else
                        {"town": screens.bar_signature(_screen(SheetPool.BARS["sheet"], b"")),
                         "caster": screens.bar_signature(_screen(SheetPool.BARS["caster"], b""))})
    game = SheetPool(tmp_path)
    d = da.Driver(game, lambda **k: None, "A")
    d.where = "map"
    if failure == "unmeasured":
        with pytest.raises(da.StepFailed, match="map bar is not showing"):
            d.sheet(3)
        assert game.keys == []
        assert not game.save_file("D").exists()
        return
    if failure == "repeated_page":
        # The name check passes (both sides read as one digest) and the
        # frame is the same one both times.
        monkeypatch.setattr(da, "_cell_digest", lambda cells: "name")
        monkeypatch.setattr(SheetPool, "capture", lambda self: (
            _screen(self.BARS["sheet"], b"") if self.mode == "sheet"
            else _with_roster(_screen(self.BARS[self.mode], b""), "camp", 6, self.line)))
        d.sheet(2)
        with pytest.raises(da.StepFailed, match="same frame"):
            d.sheet(3)
        assert not game.save_file("D").exists()
        return
    if failure and failure != "caster":
        # Each names the guard it claims to reach, so a StepFailed from the
        # darkness path or another guard cannot pass for it.
        why = {"wrong_member": "name is not roster line",
               "unknown_return": "map bar did not return",
               "moved_highlight": "highlight is not on the member",
               "unmeasured_sheet": "VIEW did not open the sheet bar"}[failure]
        with pytest.raises(da.StepFailed, match=why):
            d.sheet(3)
        assert not game.save_file("D").exists()
        if failure == "moved_highlight":
            assert game.keys[-1] == "Escape"     # stopped there, no SAVE
        return
    # "" is the town/outdoor bar; "caster" is the third, cleric-sheet bar --
    # both open and both return to the map the same way.
    got = d.sheet(3)
    assert game.keys == ["End", "End", "v", "Escape"]
    assert got["line"] == 3 and game.mode == "map"


@pytest.mark.parametrize("sheet_name", ("npc", "longer", "shorter"))
def test_pool_sheet_opens_an_npcs_sheet_with_the_measured_bar(tmp_path, monkeypatch,
                                                            sheet_name):
    """`POOL_SHEET_BARS` as shipped knows the bar an NPC's sheet shows
    (`VIEW:ITEMS EXIT`, digest measured off SKULLCRUSHER's sheet), and the
    name check takes the sheet's `SKULLCRUSHER (NPC)` as the roster's
    `SKULLCRUSHER`: the roster name's cells, then a blank one.  A sheet
    whose name runs on a letter past the roster's, or stops short of it
    (`SKULL`), is another member's.  The
    fake bar stands in for the measured digest, the one thing a fake cannot
    draw."""
    npc_bar = b"\x18\x4b\x7e"
    real = da.bar_signature
    stand_in = real(_screen(npc_bar, b""))

    def signature(screen, *a, **k):
        got = real(screen, *a, **k)
        return "90b53c9e64947226" if got == stand_in else got

    def short(n: int) -> bytes:
        return _pod_name(n)[:6]

    after = {"npc": b"\x00\x18\x24\x42\x81", "longer": b"\x42",
             "shorter": b"\x00\x18\x24\x42\x81"}[sheet_name]
    keep = 3 if sheet_name == "shorter" else 6

    class NpcPool(FakePool):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.line = 1

        def key(self, k, gap=0.0):
            self.keys.append(k)
            if self.mode == "map" and k == "End":
                self.line = self.line % 6 + 1
            elif self.mode == "map" and k == "v":
                self.mode = "sheet"
            elif self.mode == "sheet" and k == "Escape":
                self.mode = "map"

        def capture(self):
            if self.mode == "sheet":
                px = bytearray(_screen(npc_bar, b"").px)
                _draw_name(px, *screens.POD_SHEET_NAME, short(self.line)[:keep] + after, _WHITE)
                return dosbox.Screen(W, H, bytes(px))
            px = bytearray(super().capture().px)
            x, y = screens.POD_ROSTER["camp"]
            for n in range(1, 7):
                _draw_name(px, x, y + screens.CELL * (n - 1), short(n),
                           _WHITE if n == self.line else _CYAN)
            return dosbox.Screen(W, H, bytes(px))

    monkeypatch.setattr(da, "bar_signature", signature)
    monkeypatch.setattr(da, "POOL_MAP_BARS",
                        {"town": real(_screen(FakePool.BARS["map"], b""))})
    game = NpcPool(tmp_path)
    d = da.Driver(game, lambda **k: None, "A")
    d.where = "map"
    if sheet_name != "npc":
        with pytest.raises(da.StepFailed, match="name is not roster line 1"):
            d.sheet(1)
        return
    got = d.sheet(1)
    assert game.keys == ["v", "Escape"]
    assert got["sheet_bar"] == "90b53c9e64947226" and game.mode == "map"


class WordSheetPool(FakePool):
    """Pool's map and one member's sheet, whose bar is drawn as `words` in the
    stand-in font, so the driver can read it as text."""

    def __init__(self, tmp, words, **kw):
        super().__init__(tmp, **kw)
        self.words, self.line = words, 1

    def key(self, k, gap=0.0):
        self.keys.append(k)
        if self.mode == "map" and k == "v":
            self.mode = "sheet"
        elif self.mode == "sheet" and k == "Escape":
            self.mode = "map"

    def capture(self):
        if self.mode != "sheet":
            return _with_roster(super().capture(), "camp", 6, self.line)
        px = bytearray(_screen(b"", b"").px)
        _draw(px, _FONT_BLOCK, da.BAR_ROW, 0, self.words, _WHITE)
        return _with_roster(dosbox.Screen(W, H, bytes(px)), "camp", 6, 0, sheet=self.line)


@pytest.mark.parametrize("words,opens", [
    # MALCYON, a magic-user carrying nothing (WISH-22 route 6).
    ("VIEW:SPELLS TRADE DROP EXIT", True),
    # A bar of a class with no measured digest, words the game might add.
    ("VIEW:ITEMS SPELLS TRADE DROP CURE EXIT", True),
    ("VIEW:EXIT", True),
    # The treasure bar opens VIEW too, with no colon.
    ("VIEW TAKE POOL SHARE EXIT", False),
    ("AREA CAST VIEW ENCAMP SEARCH LOOK", False),
])
def test_a_pool_sheet_of_any_class_opens_by_its_words(tmp_path, monkeypatch, words, opens):
    monkeypatch.setattr(da, "POOL_MAP_BARS",
                        {"town": screens.bar_signature(_screen(FakePool.BARS["map"], b""))})
    game = WordSheetPool(tmp_path, words)
    d = da.Driver(game, lambda **k: None, "A")
    d._font = _FONT
    d.where = "map"
    game.mode = "sheet"
    assert screens.bar_signature(game.capture()) not in da.POOL_SHEET_BARS.values()
    game.mode = "map"
    if not opens:
        with pytest.raises(da.StepFailed, match="VIEW did not open the sheet bar"):
            d.sheet(1)
        return
    got = d.sheet(1)
    assert game.keys == ["v", "Escape"] and game.mode == "map"
    assert got["line"] == 1


@pytest.mark.parametrize("words,offered", [
    ("VIEW:SPELLS TRADE DROP EXIT", False),
    ("VIEW:TRADE DROP EXIT", False),
    ("VIEW:ITEMS SPELLS TRADE DROP EXIT", True),
    ("VIEW:ITEMS EXIT", True),
])
def test_a_pool_sheet_offers_items_by_its_words_when_unmeasured(tmp_path, words, offered):
    game = WordSheetPool(tmp_path, words)
    d = da.Driver(game, lambda **k: None, "A")
    d._font = _FONT
    game.mode = "sheet"
    assert d.on_pool_sheet(game.capture())
    assert d.pool_sheet_offers_items(game.capture()) is offered


@pytest.mark.parametrize("key,offered", [(k, k not in da.POOL_SHEET_NO_ITEMS)
                                         for k in da.POOL_SHEET_BARS])
def test_a_measured_pool_sheet_bar_offers_items_by_its_entry(tmp_path, monkeypatch, key,
                                                              offered):
    d = da.Driver(FakePool(tmp_path), lambda **k: None, "A")
    monkeypatch.setattr(da, "bar_signature", lambda sc: da.POOL_SHEET_BARS[key])
    assert d.on_pool_sheet(None)
    assert d.pool_sheet_offers_items(None) is offered


def test_the_captured_magic_user_sheet_bar_is_measured_and_reads_as_a_sheet():
    """MALCYON's sheet (WISH-22 route 6), which a `sheet` step stopped at
    before any class's bar was taken by its words."""
    screen = _capture("dos-6", "003-lost-sheet-1-open", "22", ("boot1",), size="320x200!")
    assert screens.bar_signature(screen) == da.POOL_SHEET_BARS["caster_no_items"]
    try:
        font = da.load_font(da.TITLES["pool"].find_game())
    except FileNotFoundError:
        pytest.skip("needs the DOS archives ($FR_ARCHIVES)")
    text = da.text_row(screen, da.BAR_ROW, font).strip()
    assert text == "VIEW:SPELLS TRADE DROP EXIT"
    assert da.POOL_SHEET_BAR_TEXT.fullmatch(text)


def test_pool_sheet_bars_include_the_npc_entries():
    """The measured digests of an NPC's `VIEW:ITEMS EXIT` bar and an NPC
    caster's `VIEW:ITEMS SPELLS EXIT` bar are in `POOL_SHEET_BARS`."""
    assert da.POOL_SHEET_BARS["npc_items"] == "90b53c9e64947226"
    assert da.POOL_SHEET_BARS["npc_caster"] == "740a10d0bc93a12a"


# -- a random event ends the rest ------------------------------------------------


@pytest.fixture
def _watch_and_clock(monkeypatch):
    """The fake's watch bar stands in for the real one, and time moves per call."""
    monkeypatch.setattr(da, "WATCH_BAR", screens.bar_signature(
        _screen(FakePool.BARS["watch"], b"")))
    now = [0.0]

    def tick():
        now[0] += 1.0
        return now[0]

    monkeypatch.setattr(da, "time", type("T", (), {"time": staticmethod(tick),
                                                   "sleep": staticmethod(lambda s: None)}))


@pytest.mark.usefixtures("pool_map_measured")
def test_the_watch_bar_is_answered_go_and_logged(tmp_path, _watch_and_clock):
    game, d = _camped(tmp_path, watches=1)
    got = d.rest(5)
    assert game.answers == ["g"] and game.mode == "map"
    assert got["left_camp"] is True
    assert [e["kind"] for e in d.events] == ["go_stay"]
    assert [k["event"] for k in d.logged if k["event"] == "random"] == ["random"]


@pytest.mark.usefixtures("pool_map_measured")
def test_a_second_watch_is_answered_too(tmp_path, _watch_and_clock):
    game, d = _camped(tmp_path, watches=2)
    d.rest(5)
    assert game.answers == ["g", "g"] and len(d.events) == 2


@pytest.mark.usefixtures("pool_map_measured")
def test_a_third_watch_stops_the_run_without_pressing(tmp_path, _watch_and_clock):
    game, d = _camped(tmp_path, watches=3)
    with pytest.raises(da.StepFailed, match="lost-rest-events"):
        d.rest(5)
    assert game.answers == ["g", "g"]


@pytest.mark.usefixtures("pool_map_measured")
def test_stay_is_never_pressed(tmp_path, _watch_and_clock):
    game, d = _camped(tmp_path, watches=2)
    d.rest(5)
    assert "s" not in game.keys[game.keys.index("g"):]


@pytest.mark.usefixtures("pool_map_measured")
def test_a_fight_after_the_rest_stops_the_run(tmp_path, _watch_and_clock):
    game, d = _camped(tmp_path, fight=True)
    with pytest.raises(da.StepFailed, match="lost-rest-end"):
        d.rest(5)
    assert game.answers == []


@pytest.mark.usefixtures("pool_map_measured")
def test_save_camps_again_after_the_party_was_moved_along(tmp_path, _watch_and_clock):
    game, d = _camped(tmp_path, watches=1)
    d.rest(5)
    got = d.save("D")
    assert got["back_in_camp"] and game.keys[-2:] == ["d", da.QUIT_NO]
    assert game.keys.count("e") == 2
    assert (game.save_dir / "SAVGAMD.DAT").is_file()


# -- the step list and its arguments --------------------------------------------


@pytest.mark.parametrize("text,minutes", [("5m", 5), ("8h", 480), ("2d", 2880),
                                          ("1h30m", 90), ("1d0h5m", 1445)])
def test_durations(text, minutes):
    assert da.parse_duration(text) == minutes


@pytest.mark.parametrize("text", ["", "5", "m", "5s", "h5"])
def test_a_duration_that_is_not_one_is_blocked(text):
    with pytest.raises(ValueError):
        da.parse_duration(text)


def test_rest_presses_split_the_time_the_way_the_menu_holds_it():
    assert da.rest_presses(5) == (0, 0, 1)
    assert da.rest_presses(90) == (0, 1, 6)
    assert da.rest_presses(1445) == (1, 0, 1)
    for bad in (0, 7, 100 * 1440):
        with pytest.raises(ValueError):
            da.rest_presses(bad)


def test_steps_parse_and_a_bad_one_is_blocked():
    assert da.parse_step("save d").letter == "D"
    assert da.parse_step("rest 5m").minutes == 5
    assert da.parse_step("rest 8d").minutes == 8 * 1440
    assert da.parse_step("train 3").line == 3
    assert da.parse_step("shot rest-screen").name == "rest-screen"
    assert da.parse_step("press Return").key == "Return"
    assert da.parse_step("walk MI").key == "MI"
    assert da.parse_step("walk I").key == "I"
    assert da.parse_step("display").kind == "display"
    for bad in ("walk 2", "walk N", "save", "save K", "rest 7m", "load now", "train",
                "train 9", "begin now", "press", "press a;b"):
        with pytest.raises(ValueError):
            da.parse_step(bad)


def test_the_command_line_blocks_a_bad_step_before_any_boot():
    with pytest.raises(SystemExit):
        da.main(["--save", ".", "--steps", "load", "rest 3m"])


def test_rows_and_expectations_parse():
    assert da.parse_row("3F=01:00:2F:01") == (63, 1, 0, 0x2F, 1)
    assert da.parse_expect("brutus:1:42:1") == da.Expect("BRUTUS", 1, 42, 1)
    assert da.parse_expect("BRUTUS:1:0x2A") == da.Expect("BRUTUS", 1, 42, None)
    for bad in ("40=01:00:2F:01", "3F=01:00:2F", "3F=100:00:2F:01"):
        with pytest.raises(ValueError):
            da.parse_row(bad)


# -- staging and reading ---------------------------------------------------------


def test_install_keeps_only_the_one_slot_under_its_own_letter(tmp_path):
    # Distinct names: "save" and "SAVE" are one directory on Windows.
    save, dest = tmp_path / "staged", tmp_path / "play"
    save.mkdir()
    dest.mkdir()
    # Lower-case archive names must count as the same slot as upper-case ones.
    for name in ("savgama.dat", "CHRDATA1.SAV", "chrdata1.spc", "NOTES.TXT"):
        (save / name).write_bytes(name.encode())
    (dest / "SAVGAMJ.DAT").write_bytes(b"someone else's")
    took = staging.install(save, dest, "a")
    assert sorted(p.name for p in dest.iterdir()) == [
        "CHRDATA1.SAV", "CHRDATA1.SPC", "SAVGAMA.DAT"]
    assert (dest / "CHRDATA1.SPC").read_bytes() == b"chrdata1.spc"
    assert took["from_slot"] == "A" and took["as_slot"] == "A"


def test_the_clock_difference_crosses_midnight():
    before = (0, 7, 5, 23, 3, 1)       # 23:57, day 3
    after = (0, 2, 0, 0, 4, 1)         # 00:02, day 4
    assert da.clock_total(after) - da.clock_total(before) == 5


def _slot(*chars):
    return {"characters": [{"name": n, "nodes": [
        {"id": i, "minutes": m, "data": dt} for i, m, dt in nodes]}
        for n, nodes in chars]}


def test_compare_names_a_node_that_aged_one_that_vanished_and_a_new_one():
    before = _slot(("BRUTUS", [(1, 47, 1), (17, 2, 0x0B)]), ("GUY", [(5, 10, 3)]))
    after = _slot(("BRUTUS", [(1, 42, 1)]), ("GUY", [(5, 10, 3), (9, 3, 0)]))
    rows = {(r["name"], r["id"]): r for r in da.compare_nodes(before, after)}
    assert rows[("BRUTUS", 1)]["lost"] == 5
    assert rows[("BRUTUS", 17)]["after"] is None
    assert rows[("GUY", 5)]["lost"] == 0
    assert rows[("GUY", 9)]["before"] is None


def test_judge_accepts_only_the_named_node_at_the_named_minutes():
    after = _slot(("BRUTUS", [(1, 42, 1)]))
    assert da.judge(da.Expect("BRUTUS", 1, 42, 1), after)["verdict"] == "accepts"
    unchanged = da.judge(da.Expect("BRUTUS", 1, 42, 1), _slot(("BRUTUS", [(1, 47, 1)])))
    assert unchanged["verdict"] == "refutes" and "47 minutes" in unchanged["why"]
    assert da.judge(da.Expect("BRUTUS", 1, 42), _slot(("BRUTUS", [])))["verdict"] \
        == "refutes"
    assert da.judge(da.Expect("BRUTUS", 1, 42), _slot())["verdict"] == "refutes"


def test_the_evidence_goes_under_the_acceptance_cache():
    out = da.evidence.default_out("661", "bless", "0123456789abcdef")
    assert out.parts[-4:] == ("wish", "acceptance", "661", "0123456789-bless")


def test_the_fixture_party_converts_with_its_bless_and_reads_back(tmp_path):
    """Save As DOS of the fixture party with a 47-minute Bless on slot 0:
    nothing dropped, `01 2F 00 01 00` in BRUTUS's `.SPC`, and the reading
    the run's `read` step makes of it accepts BRUTUS at 47."""
    from editor import saveplan
    try:
        built = da.build_source([(63, 1, 0, 0x2F, 1)], tmp_path)
    except FileNotFoundError:
        pytest.skip("needs the DOS Pool of Radiance archives ($FR_ARCHIVES)")
    except saveplan.MissingAssets:
        pytest.skip("needs Pool of Radiance's own C64 disks")
    assert built["dropped"] == [] and built["losses"] == []
    assert [n["raw"] for n in built["nodes"]["CHRDATA1.SPC"]] == ["012f000100"]
    slot = da.read_slot(tmp_path / "source", "A")
    assert da.judge(da.Expect("BRUTUS", 1, 47, 1), slot)["verdict"] == "accepts"


class _Slot:
    def __init__(self, log):
        self.log = log

    def release(self):
        self.log.append("release")


class _Session:
    """Stands in for dosbox.Session; `fail_on` names the method that raises."""

    def __init__(self, tmp_path, log, fail_on=None):
        self.dir = tmp_path / "session"
        self.save_dir = self.dir / "SAVE"
        self.log, self.fail_on = log, fail_on

    def stage(self, fresh=True):
        self.save_dir.mkdir(parents=True, exist_ok=True)

    def boot(self, fresh=False):
        pass

    def close(self):
        self.log.append("close")
        if self.fail_on == "close":
            raise RuntimeError("close broke")


def _run_args(tmp_path, steps):
    import argparse
    return argparse.Namespace(
        title="pool", slot="A", steps=steps, expect=[], fixture_row=[], save=None,
        out=str(tmp_path / "out"), issue="661", run="t", note="t")


def _fake_run(monkeypatch, tmp_path, *, find_game=None, session_fail=None,
              menu_error=None):
    log: list[str] = []
    monkeypatch.setattr(da.evidence, "git_state", lambda repo: {"sha": "0" * 40, "dirty": False})
    monkeypatch.setattr(da, "install", lambda *a: {})

    def find(stem):
        if find_game:
            raise find_game
        return tmp_path / "game"

    def claim(note=""):
        log.append("claim")
        return _Slot(log)

    monkeypatch.setattr(dosbox, "find_game", find)
    # A Pool walk boots DOSBox-X; a test that cares which one patches it again.
    for module, session in ((dosbox, "Session"), (da.dosboxx, "XSession")):
        monkeypatch.setattr(module, "claim", claim)
        monkeypatch.setattr(module, session,
                            lambda slot, game: _Session(tmp_path, log, session_fail))

    class Game:
        def to_main_menu(self):
            raise menu_error

    class D:
        where = "boot"
        #: The labels `journal` and `yes_no` were asked with, before each step.
        asked: list[str] = []
        declined: list[str] = []
        continued: list[str] = []

        def __init__(self, session, note, letter, *rest, **kw):
            self.game = Game()

        def journal(self, label):
            self.asked.append(label)
            return False

        def yes_no(self, label):
            self.declined.append(label)
            return 0

        def press_continue(self, label):
            self.continued.append(label)
            return 0

        def step_begins(self, kind):
            pass

        def shot(self, name):
            (tmp_path / "session" / "shots").mkdir(parents=True, exist_ok=True)
            (tmp_path / "session" / "shots" / f"{name}.png").write_bytes(b"x")
            return name

        def fail(self, label, why):
            return da.StepFailed(f"{why}; see {self.shot('lost-' + label)}.png")

        def load(self):
            self.game.to_main_menu()

    monkeypatch.setattr(da, "Driver", D)
    return log


def test_a_missing_game_is_found_before_a_slot_is_claimed(monkeypatch, tmp_path):
    log = _fake_run(monkeypatch, tmp_path, find_game=FileNotFoundError("no game"))
    with pytest.raises(FileNotFoundError):
        da.run(_run_args(tmp_path, ["load"]))
    assert "claim" not in log


def test_a_timeout_before_the_load_writes_the_lost_shot_and_reason(monkeypatch, tmp_path):
    import json
    _fake_run(monkeypatch, tmp_path, menu_error=TimeoutError("no menu"))
    assert da.run(_run_args(tmp_path, ["load"])) == 1
    out = tmp_path / "out"
    assert (out / "shots" / "lost-timeout.png").is_file()
    assert "no menu" in json.loads((out / "summary.json").read_text())["lost"]


def test_a_failed_close_still_releases_the_slot_and_the_log(monkeypatch, tmp_path):
    log = _fake_run(monkeypatch, tmp_path, session_fail="close",
                    menu_error=TimeoutError("x"))
    with pytest.raises(RuntimeError, match="close broke"):
        da.run(_run_args(tmp_path, ["load"]))
    assert log == ["claim", "close", "release"]
    assert (tmp_path / "out" / "summary.json").is_file()


def test_a_bad_step_order_is_blocked_before_a_slot_is_claimed(monkeypatch, tmp_path, capsys):
    log = _fake_run(monkeypatch, tmp_path)
    with pytest.raises(SystemExit):
        da.main(["--save", str(tmp_path), "--steps", "load", "rest 5m"])
    assert log == []
    assert "needs camp first" in capsys.readouterr().err


# -- a walk that did not happen never passes -----------------------------------


def _walk_run(monkeypatch, tmp_path, read):
    """`_fake_run`'s driver made to take every step of a walk run, and
    `read_step` to return `read` (None: the read step is not in the list)."""
    log = _fake_run(monkeypatch, tmp_path)
    for name, fn in (("load", lambda self: {}), ("camp", lambda self: {}),
                     ("walk", lambda self, key: {"route": key}),
                     ("save", lambda self, letter: {})):
        monkeypatch.setattr(da.Driver, name, fn, raising=False)
    monkeypatch.setattr(da, "read_step", lambda *a, **k: read)
    return log


def _summary(tmp_path):
    import json
    return json.loads((tmp_path / "out" / "summary.json").read_text())


_WALK_STEPS = ["load", "walk MI", "camp", "save D", "read"]


def _read(changed=True, **slot):
    place = {"x": 1, "y": 2, "area": 0}
    return {"slots": {"D": {"place": place, "place_changed": changed, **slot}},
            "saved": ["D"]}


def test_a_walk_whose_saved_place_is_the_installed_one_fails_the_run(monkeypatch, tmp_path):
    _walk_run(monkeypatch, tmp_path, _read(changed=False))
    assert da.run(_run_args(tmp_path, _WALK_STEPS)) == 1
    got = _summary(tmp_path)
    assert got["completed"] is False
    assert "did not move" in got["lost"]
    assert got["read"]["slots"]["D"]["place_changed"] is False


def test_a_walk_with_no_computed_place_change_fails_the_run(monkeypatch, tmp_path):
    read = _read()
    del read["slots"]["D"]["place_changed"]
    _walk_run(monkeypatch, tmp_path, read)
    assert da.run(_run_args(tmp_path, _WALK_STEPS)) == 1
    assert "not computed" in _summary(tmp_path)["lost"]


def test_a_walk_whose_save_place_could_not_be_decoded_fails_the_run(monkeypatch, tmp_path):
    read = _read()
    read["slots"]["D"]["place"] = {"error": "ValueError: short"}
    _walk_run(monkeypatch, tmp_path, read)
    assert da.run(_run_args(tmp_path, _WALK_STEPS)) == 1
    assert "not computed" in _summary(tmp_path)["lost"]


def test_a_walk_judged_on_a_save_taken_before_it_fails_the_run(monkeypatch, tmp_path):
    read = {"slots": {"D": _read()["slots"]["D"], "B": _read(False)["slots"]["D"]},
            "saved": ["D", "B"]}
    _walk_run(monkeypatch, tmp_path, read)
    assert da.run(_run_args(tmp_path, _WALK_STEPS)) == 1
    assert "slot B" in _summary(tmp_path)["lost"]


def test_a_walk_with_no_read_step_fails_the_run(monkeypatch, tmp_path):
    _walk_run(monkeypatch, tmp_path, None)
    assert da.run(_run_args(tmp_path, _WALK_STEPS[:-1])) == 1
    assert "no read step" in _summary(tmp_path)["lost"]


def test_a_walk_that_moved_the_party_passes(monkeypatch, tmp_path):
    _walk_run(monkeypatch, tmp_path, _read(changed=True))
    assert da.run(_run_args(tmp_path, _WALK_STEPS)) == 0
    assert _summary(tmp_path)["completed"] is True


def test_a_run_with_no_walk_is_not_failed_for_an_unchanged_place(monkeypatch, tmp_path):
    _walk_run(monkeypatch, tmp_path, _read(changed=False))
    assert da.run(_run_args(tmp_path, ["load", "camp", "save D", "read"])) == 0


# -- the deadline, the failure capture and the wrapper's signal ----------------


class _Clock:
    """A clock the test moves, or that moves `step` seconds per reading."""

    def __init__(self, step=0.0):
        self.t, self.step = 0.0, step

    def __call__(self):
        self.t += self.step
        return self.t


def test_a_deadline_leaves_the_route_window_and_keeps_the_cleanup_window():
    clock = _Clock()
    deadline = da.Deadline(clock, 900.0, 120.0)
    assert deadline.left() == 780.0
    clock.t = 780.0 - da.ACTION_SECONDS
    deadline.check("walk")
    clock.t += 0.5
    with pytest.raises(da.DeadlineReached, match="walk"):
        deadline.check("walk")


def test_a_deadline_never_gives_the_cleanup_more_than_half_of_it():
    assert da.Deadline(_Clock(), 100.0, 120.0).left() == 50.0


def test_a_clock_past_the_deadline_between_steps_still_writes_lost_and_the_shots(
        monkeypatch, tmp_path):
    clock = _Clock()
    _walk_run(monkeypatch, tmp_path, _read())

    def load(self):
        clock.t = 10_000.0
        return {}

    monkeypatch.setattr(da.Driver, "load", load)
    assert da.run(_run_args(tmp_path, _WALK_STEPS), clock=clock) == 1
    got = _summary(tmp_path)
    assert got["completed"] is False and "deadline" in got["lost"]
    assert (tmp_path / "out" / "shots" / "lost-timeout.png").is_file()


def test_a_deadline_reached_inside_a_step_still_writes_lost_and_the_shots(
        monkeypatch, tmp_path):
    _walk_run(monkeypatch, tmp_path, _read())

    def load(self):
        raise da.DeadlineReached("the run's deadline is reached during load")

    monkeypatch.setattr(da.Driver, "load", load)
    assert da.run(_run_args(tmp_path, _WALK_STEPS)) == 1
    assert "deadline is reached during load" in _summary(tmp_path)["lost"]
    assert (tmp_path / "out" / "shots" / "lost-timeout.png").is_file()


def test_the_run_takes_its_deadline_from_the_argument(monkeypatch, tmp_path):
    _walk_run(monkeypatch, tmp_path, _read())
    seen = []
    real = da.Driver.__init__

    def init(self, *a, **kw):
        seen.append(kw["deadline"].left())
        real(self, *a, **kw)

    monkeypatch.setattr(da.Driver, "__init__", init)
    args = _run_args(tmp_path, _WALK_STEPS)
    args.deadline = 400.0
    da.run(args, clock=_Clock())
    assert seen == [400.0 - da.CLEANUP_SECONDS]


@posix_signals
def test_a_termination_signal_still_writes_lost_and_the_shots(monkeypatch, tmp_path):
    import os
    import signal
    _walk_run(monkeypatch, tmp_path, _read())
    before = signal.getsignal(signal.SIGTERM)

    def load(self):
        os.kill(os.getpid(), signal.SIGTERM)
        return {}

    monkeypatch.setattr(da.Driver, "load", load)
    assert da.run(_run_args(tmp_path, _WALK_STEPS)) == 1
    assert "signal 15" in _summary(tmp_path)["lost"]
    assert (tmp_path / "out" / "shots" / "lost-timeout.png").is_file()
    assert signal.getsignal(signal.SIGTERM) == before


def test_a_step_that_raises_something_else_still_ends_with_lost(monkeypatch, tmp_path):
    import subprocess
    _walk_run(monkeypatch, tmp_path, _read())

    def load(self):
        raise subprocess.CalledProcessError(1, "import")

    monkeypatch.setattr(da.Driver, "load", load)
    assert da.run(_run_args(tmp_path, _WALK_STEPS)) == 1
    assert "CalledProcessError" in _summary(tmp_path)["lost"]


def test_a_failing_failure_capture_leaves_the_original_reason(tmp_path):
    import subprocess
    game = FakePool(tmp_path)
    notes = []
    d = da.Driver(game, lambda **k: notes.append(k), "A")

    def broken(name, allow_blank=False):
        raise subprocess.CalledProcessError(1, "import")

    game.shot = broken
    error = d.fail("walk", "the map bar did not return")
    assert isinstance(error, da.StepFailed)
    assert str(error).startswith("the map bar did not return")
    assert "CalledProcessError" in d.capture_error
    assert any(n.get("event") == "failure_capture_error" for n in notes)


def test_a_failing_failure_capture_is_recorded_beside_lost(monkeypatch, tmp_path):
    _walk_run(monkeypatch, tmp_path, _read())

    def load(self):
        self.capture_error = "CalledProcessError: import"
        raise da.StepFailed("the map bar did not return")

    monkeypatch.setattr(da.Driver, "load", load)
    assert da.run(_run_args(tmp_path, _WALK_STEPS)) == 1
    got = _summary(tmp_path)
    assert got["lost"] == "the map bar did not return"
    assert got["failure_capture_error"] == "CalledProcessError: import"


def _bounded(tmp_path, left, title="curse", **kw):
    """A camped driver whose route window has `left` seconds in it."""
    game, d = _camped(tmp_path, title, **kw)
    clock = _Clock()
    d.deadline = da.Deadline(clock, 900.0, 120.0)
    clock.t = 780.0 - left
    return game, d, clock


def test_wait_file_hands_no_short_remainder_to_the_file_settle(tmp_path, monkeypatch):
    game, d, _ = _bounded(tmp_path, left=da.ACTION_SECONDS - 1)
    calls = []
    monkeypatch.setattr(dosbox, "settle_files", lambda *a, **k: calls.append(k))
    path = game.save_dir / "SAVGAMD.DAT"
    path.write_bytes(b"new")
    with pytest.raises(da.DeadlineReached):
        d.wait_file(path, b"old", "save-file")
    assert calls == []


def test_wait_file_limits_the_file_settle_to_the_time_left(tmp_path, monkeypatch):
    game, d, _ = _bounded(tmp_path, left=12.0)
    calls = []
    monkeypatch.setattr(dosbox, "settle_files", lambda *a, **k: calls.append(k))
    path = game.save_dir / "SAVGAMD.DAT"
    path.write_bytes(b"new")
    d.wait_file(path, b"old", "save-file")
    assert calls == [{"quiet": 1.0, "timeout": 12.0}]


def test_wait_file_stops_at_the_deadline_while_the_file_stays_the_same(tmp_path):
    game, d, clock = _bounded(tmp_path, left=30.0)
    clock.step = 10.0
    path = game.save_dir / "SAVGAMD.DAT"
    path.write_bytes(b"old")
    with pytest.raises(da.DeadlineReached, match="save-file"):
        d.wait_file(path, b"old", "save-file")


def test_a_rest_stops_at_the_deadline_and_presses_nothing_more(tmp_path):
    game, d, clock = _bounded(tmp_path, left=60.0)
    game.mode = "fight"
    clock.step = 20.0
    pressed = len(game.keys)
    with pytest.raises(da.DeadlineReached):
        d.after_rest(600.0, "rest")
    assert len(game.keys) == pressed


# -- the later titles: keys, order, staging ----------------------------------------


def test_the_later_titles_rest_on_their_own_letters():
    """`Rest Days Hours Mins Add Subtract Exit` (Curse `GAME.OVR` 0x2B4A7,
    Silver Blades 0x2BD63): Pool's `Y`, `I` and `D` are not its keys, and
    `D` selects the days field there rather than subtracting."""
    for title in ("curse", "ssb"):
        keys = da.TITLES[title].rest_keys()
        assert (keys.days, keys.inc, keys.dec) == ("d", "a", "s")
    assert TITLE_KEYS["pool"] == da.RestKeys("y", "h", "m", "i", "d", "r")


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_keys_do_not_rest_a_later_title(tmp_path):
    # The Curse menu driven with Pool's letters: `y` selects nothing, so the
    # first key of the zeroing changes nothing and the run stops there.
    game = FakePool(tmp_path, keys=TITLE_KEYS["curse"], preset=90)
    d = da.Driver(game, lambda **k: None, "A", "pool")
    d.camp()
    with pytest.raises(da.StepFailed, match="days field"):
        d.rest(5)
    assert game.rested == []


def test_a_rest_that_ends_on_a_still_screen_stops_the_run(tmp_path, _watch_and_clock,
                                                           monkeypatch):
    # Eight days is 2,304 passes, so the bar's own deadline is over an hour
    # away; a screen that has stopped changing ends the run long before it.
    monkeypatch.setattr(da, "REST_STALL", 20.0)
    game, d = _camped(tmp_path, "curse", fight=True)
    calls = []
    real = game.capture
    game.capture = lambda: calls.append(1) or real()
    with pytest.raises(da.StepFailed, match="nothing under the viewport"):
        d.rest(8 * 1440)
    assert game.rested == [8 * 1440]
    assert len(calls) < 100


def _steps(*texts):
    return [da.parse_step(t) for t in texts]


@pytest.mark.parametrize("title,steps", [
    ("pool", ("load", "walk MI", "camp", "rest 5m", "save D", "read")),
    ("pool", ("load", "camp", "display", "save D", "read")),
    ("curse", ("load", "begin", "camp", "display", "save D", "read")),
    ("ssb", ("load", "begin", "camp", "display", "rest 5m", "display")),
    ("curse", ("load", "save B", "train 1", "save C", "read")),
    ("curse", ("load", "begin", "camp", "rest 8d")),
    ("ssb", ("load", "begin", "camp", "rest 5m", "save D", "read")),
    ("ssb", ("load", "shot party", "begin", "camp", "save B", "read")),
    ("ssb", ("load", "press Down", "press Return", "shot menu", "press t", "read")),
    ("curse", ("load", "view 2", "begin", "walk MI", "camp", "save D", "read")),
    ("curse", ("load", "view 2", "begin", "turn 2", "camp", "save D", "read")),
    ("ssb", ("load", "view 2", "begin", "walk 1", "camp", "save E", "read")),
    ("ssb", ("load", "view 2", "begin", "turn 4", "camp", "save E", "read")),
])
def test_orders_the_game_allows(title, steps):
    da.validate_steps(_steps(*steps), title)


class PoolMap(FakePool):
    """Pool's map with the `x,y` token, the facing and the clock on the status
    line, as `status_square` reads them.  `status_on=False` leaves the line
    blank, as a shop or an arrival does."""

    def __init__(self, tmp, status_on=True, **kw):
        super().__init__(tmp, **kw)
        self.x, self.facing, self.clock_ticks = 0, 3, 0
        self.status_on = status_on
        self.hide_square = False

    def capture(self):
        frame = super().capture()
        if not self.status_on or self.mode != "map":
            return frame
        px = bytearray(frame.px)
        y = dosbox.STATUS[1]
        token = bytes(((1 << self.x % 8) | 0x80, 0x18, 0x21))
        # With the `x,y` hidden the facing letter opens the line, as in
        # `E 03:59`.
        shift = 4 * screens.CELL * self.hide_square
        if not self.hide_square:
            _draw_name(px, screens.STATUS_TEXT_X, y, token, _WHITE)
        _draw_name(px, screens.STATUS_TEXT_X + screens.CELL * 4 - shift, y,
                   bytes(((1 << self.facing) | 0x40,)), _WHITE)
        _draw_name(px, screens.STATUS_TEXT_X + screens.CELL * 6 - shift, y,
                   bytes(((1 << self.clock_ticks % 8) | 0x20,)), _WHITE)
        return dosbox.Screen(W, H, bytes(px))


class PoolMovement:
    """Stands in for `PoolOfRadiance`'s movement on a `PoolMap`: a turn changes
    the facing, a step changes x unless `blocked`, and every step ticks the
    clock, a wall's bump included."""

    def __init__(self, game, blocked=False, tick_on_turn=False):
        self.game, self.blocked, self.tick_on_turn = game, blocked, tick_on_turn
        self.keys = []

    def status(self):
        return self.game.capture().ink(dosbox.STATUS)

    def turn_right(self):
        self.keys.append("Right")
        self.game.facing = (self.game.facing + 1) % 4
        if self.tick_on_turn:
            self.game.clock_ticks += 1
        return True

    def step(self):
        self.keys.append("Up")
        self.game.clock_ticks += 1
        if not self.blocked:
            self.game.x += 1
        return True


def _pool_walker(tmp_path, blocked=False, tick_on_turn=False, title="pool", **kw):
    game = PoolMap(tmp_path, **kw)
    d = da.Driver(game, lambda **k: None, "A", title)
    d.where = "map"
    d.world_ink = game.capture().ink(dosbox.BAR)
    d.world_sig = screens.bar_signature(game.capture())
    d.game = PoolMovement(game, blocked, tick_on_turn)
    return game, d


def test_pool_walk_mi_turns_twice_then_steps_and_records_each_map_state(tmp_path):
    game, d = _pool_walker(tmp_path)
    got = d.walk("MI")
    assert d.game.keys == ["Right", "Right", "Up"]
    # `status_square` of the tokens `PoolMap` draws for x = 0 and x = 1.
    assert got["square_before"] == "0bcb75efaa7a593d"
    assert got["square_after"] == "11c0be6f8ad8d9fc"
    assert got["status_before"] != got["status_after"]
    assert len(got["screens"]) == 4
    assert d.where == "map"


def _hide_on_turns(game, d, shown_on=()):
    """Turns hide the `x,y` except the numbered ones in `shown_on`; `x_after`
    nothing else changes."""
    turn, calls = d.game.turn_right, []

    def turn_hides():
        calls.append(1)
        game.hide_square = len(calls) not in shown_on
        return turn()

    d.game.turn_right = turn_hides


def test_pool_walk_mi_goes_on_when_a_turn_leaves_the_line_without_x_y(tmp_path):
    game, d = _pool_walker(tmp_path)
    _hide_on_turns(game, d, shown_on=(2,))
    got = d.walk("MI")
    assert d.game.keys == ["Right", "Right", "Up"]
    assert got["square_before"] != got["square_after"]
    assert got["screens"][1]["square"] is None


def test_pool_turn_fails_when_the_square_never_reads_after_hidden_turns(tmp_path):
    game, d = _pool_walker(tmp_path)
    _hide_on_turns(game, d)
    with pytest.raises(da.StepFailed, match="walk-status|no x,y"):
        d.turn(2)


def test_pool_walk_fails_when_the_square_never_reads_after_hidden_turns(tmp_path):
    game, d = _pool_walker(tmp_path)
    _hide_on_turns(game, d)
    with pytest.raises(da.StepFailed, match="no x,y"):
        d.walk("MI")
    assert d.game.keys == ["Right", "Right"]


def test_pool_turn_fails_when_a_hidden_turn_moved_the_party(tmp_path):
    game, d = _pool_walker(tmp_path)
    _hide_on_turns(game, d, shown_on=(2,))
    turn = d.game.turn_right

    def moving():
        game.x += 1
        return turn()

    d.game.turn_right = moving
    with pytest.raises(da.StepFailed, match="square changed"):
        d.turn(2)


def test_pool_turn_passes_when_the_square_reads_as_origin_after_hidden_turns(tmp_path):
    game, d = _pool_walker(tmp_path)
    _hide_on_turns(game, d, shown_on=(2,))
    got = d.turn(2)
    assert got["square_after"] == got["square_before"]


class PoolMapMemory(PoolMap):
    """`PoolMap` with the DOSBox-X debugger's memory calls: the game's data
    segment holds the variable-array pointer `LiveVariables` checks and, at
    `POOL_PLACE`, the party's x, y and doubled facing as the fake moves."""

    DS = 0x149E

    def __init__(self, tmp, **kw):
        super().__init__(tmp, **kw)
        self.y = 5
        self.mem = bytearray(0x100000)
        ptr = da.dosboxx.linear((self.DS, da.dosnoencounters.ENGINE[
            da.dosnoencounters.POOL].pointer))
        self.mem[ptr:ptr + 4] = bytes((0, 0, 0x00, 0x30))  # 3000:0000
        self.mem[0x30000] = 1  # a block that is not all zeros
        self.halts = 0

    def attach(self):
        self.halts += 1
        return True

    def run(self):
        pass

    def regs(self, *names):
        return {"DS": self.DS}

    def read(self, addr, n):
        at = da.dosboxx.linear((self.DS, da.POOL_PLACE))
        # The fake's facing counts from W (3); the game's from N, doubled.
        self.mem[at:at + 3] = bytes((self.x, self.y, 2 * ((self.facing + 1) % 4)))
        lin = da.dosboxx.linear(addr)
        return bytes(self.mem[lin:lin + n])


def _memory_walker(tmp_path):
    game = PoolMapMemory(tmp_path)
    d = da.Driver(game, lambda **k: None, "A", "pool")
    d.where = "map"
    d.world_ink = game.capture().ink(dosbox.BAR)
    d.world_sig = screens.bar_signature(game.capture())
    d.game = PoolMovement(game)
    return game, d


def test_pool_place_reads_x_y_and_a_doubled_facing():
    assert da.pool_place(bytes((6, 5, 0, 9, 0))) == {"x": 6, "y": 5, "facing": 0}
    assert da.pool_place(bytes((6, 5, 6))) == {"x": 6, "y": 5, "facing": 3}
    assert da.pool_place(bytes((6, 5, 3))) is None
    assert da.pool_place(bytes((0xC0, 5, 2))) is None


def test_pool_reads_the_square_from_memory_only_with_a_debugger(tmp_path):
    _, d = _pool_walker(tmp_path)
    assert d.place_reader is None
    (tmp_path / "c").mkdir()
    _, d = _pool_walker(tmp_path / "c", title="curse")
    assert d.place_reader is None
    (tmp_path / "m").mkdir()
    game, d = _memory_walker(tmp_path / "m")
    assert d.party_place("x") == {"x": 0, "y": 5, "facing": 0, "area": 0,
                                  "raw": "0005000000", "ds": "149E"}
    assert game.halts == 1


def test_pool_walk_mi_reads_the_hidden_square_from_memory(tmp_path):
    # As at 6,5 on the New Phlan map: both turns leave `S 03:59` and the line
    # never shows the `x,y` again, so only memory can show the turns kept the
    # party on its square.
    game, d = _memory_walker(tmp_path)
    notes = []
    d.note = lambda **k: notes.append(k)
    _hide_on_turns(game, d)
    got = d.walk("MI")
    assert d.game.keys == ["Right", "Right", "Up"]
    assert [(n["label"], n["x"], n["facing"]) for n in notes
            if n["event"] == "place"] == [("walk-before", 0, 0), ("walk-turn-1", 0, 1),
                                         ("walk-turn-2", 0, 2), ("walk-step", 1, 2)]
    assert got["place_before"]["x"] == 0 and got["place_after"]["x"] == 1
    assert [s["square"] for s in got["screens"][1:3]] == [None, None]
    assert [s["place"]["facing"] for s in got["screens"][:3]] == [0, 1, 2]


def test_pool_walk_reads_a_hidden_step_from_memory(tmp_path):
    game, d = _memory_walker(tmp_path)
    _hide_on_turns(game, d)
    real_step = d.game.step

    def hidden_step():
        game.hide_square = True
        return real_step()

    d.game.step = hidden_step
    got = d.walk("MI")
    assert got["square_after"] is None
    assert (got["place_after"]["x"], got["place_after"]["y"]) == (1, 5)


def test_pool_walk_blocked_behind_a_hidden_line_is_read_from_memory(tmp_path):
    game, d = _memory_walker(tmp_path)
    d.game.blocked = True
    _hide_on_turns(game, d)
    with pytest.raises(da.StepFailed, match="walk-blocked"):
        d.walk("MI")


def test_pool_turn_passes_on_memory_when_the_line_never_shows_x_y(tmp_path):
    game, d = _memory_walker(tmp_path)
    _hide_on_turns(game, d)
    got = d.turn(2)
    assert got["square_after"] == got["square_before"]
    assert (got["place_after"]["x"], got["place_after"]["y"]) == (0, 5)


def test_pool_turn_fails_when_memory_shows_a_hidden_turn_moved_the_party(tmp_path):
    game, d = _memory_walker(tmp_path)
    _hide_on_turns(game, d)
    turn = d.game.turn_right

    def moving():
        game.x += 1
        return turn()

    d.game.turn_right = moving
    with pytest.raises(da.StepFailed, match="memory reads 1,5, it was 0,5"):
        d.turn(2)


def test_pool_walk_i_takes_its_origin_from_memory_when_the_line_hides_x_y(tmp_path):
    game, d = _memory_walker(tmp_path)
    game.hide_square = True
    got = d.walk("I")
    assert d.game.keys == ["Up"]
    assert got["square_before"] is None
    assert (got["place_before"]["x"], got["place_after"]["x"]) == (0, 1)


def test_pool_walk_i_with_a_hidden_origin_fails_when_memory_does_not_read(tmp_path):
    game, d = _memory_walker(tmp_path)
    game.hide_square = True
    game.attach = lambda: False
    with pytest.raises(da.StepFailed, match="no starting square"):
        d.walk("I")


def test_pool_walk_falls_back_to_the_line_when_memory_does_not_read(tmp_path):
    game, d = _memory_walker(tmp_path)
    notes = []
    d.note = lambda **k: notes.append(k)
    game.attach = lambda: False
    _hide_on_turns(game, d)
    with pytest.raises(da.StepFailed, match="no x,y"):
        d.walk("MI")
    assert any(n["event"] == "place-unread" for n in notes)


def test_a_short_status_line_is_still_a_square_outside_pool(tmp_path):
    game, d = _pool_walker(tmp_path, title="curse")
    game.hide_square = True
    screen = game.capture()
    shot = []
    _, square = d.map_status("x", shot)
    assert square == da.status_square(screen, da.status_column("curse"))
    assert square is not None


def test_pool_walk_i_steps_once_without_turning(tmp_path):
    game, d = _pool_walker(tmp_path)
    got = d.walk("I")
    assert d.game.keys == ["Up"]
    assert got["route"] == "I"
    assert got["square_before"] != got["square_after"]
    assert len(got["screens"]) == 2
    assert d.where == "map"


def test_pool_walk_i_that_hits_a_wall_fails_the_walk(tmp_path):
    game, d = _pool_walker(tmp_path, blocked=True)
    with pytest.raises(da.StepFailed, match="walk-blocked"):
        d.walk("I")
    assert d.game.keys == ["Up"]


def test_walk_i_is_pool_only(tmp_path):
    game, d = _pool_walker(tmp_path, title="curse")
    with pytest.raises(da.StepFailed, match="walk I needs Pool of Radiance"):
        d.walk("I")
    da.validate_steps(_steps("load", "walk I"), "pool")
    with pytest.raises(ValueError, match=r"curse's walk is 'walk MI', not 'walk I'"):
        da.validate_steps(_steps("load", "walk I"), "curse")
    with pytest.raises(ValueError, match=r"pool's walk is 'walk MI' or 'walk I', not 'walk 1'"):
        da.validate_steps(_steps("load", "walk 1"), "pool")


def test_curse_walk_mi_turns_twice_then_steps_on_the_map(tmp_path):
    game, d = _pool_walker(tmp_path, title="curse")
    got = d.walk("MI")
    assert d.game.keys == ["Right", "Right", "Up"]
    assert got["square_before"] != got["square_after"]
    assert d.where == "map"


def test_a_curse_step_that_hits_a_wall_fails_the_walk(tmp_path):
    game, d = _pool_walker(tmp_path, title="curse", blocked=True)
    with pytest.raises(da.StepFailed, match="walk-blocked"):
        d.walk("MI")


def test_a_curse_walk_with_a_blank_status_line_has_no_baseline(tmp_path):
    game, d = _pool_walker(tmp_path, title="curse", status_on=False)
    with pytest.raises(da.StepFailed, match="blank"):
        d.walk("MI")
    assert d.game.keys == []


def test_pool_walk_mi_stops_before_camp_when_step_enters_combat(tmp_path):
    game, d = _pool_walker(tmp_path)
    real = d.game.step

    def step():
        real()
        game.mode = "fight"
        return True

    d.game.step = step
    with pytest.raises(da.StepFailed, match="map bar did not return"):
        d.walk("MI")
    assert d.game.keys == ["Right", "Right", "Up"]
    assert d.where == "map"


def test_pool_walk_mi_stops_before_camp_when_step_hits_a_wall(tmp_path):
    game, d = _pool_walker(tmp_path, blocked=True)
    with pytest.raises(da.StepFailed, match="did not change") as raised:
        d.walk("MI")
    assert "lost-walk-blocked" in str(raised.value)
    assert d.game.keys == ["Right", "Right", "Up"]
    assert d.where == "map"


def test_a_bump_that_ticks_the_clock_is_not_a_pool_step(tmp_path):
    """The step against a wall advances the clock, so the whole status strip
    differs from before it and the square does not."""
    game, d = _pool_walker(tmp_path, blocked=True)
    before = d.game.status()
    d.game.step()
    assert d.game.status() != before
    with pytest.raises(da.StepFailed, match="did not change"):
        d.walk("MI")


def test_a_clock_tick_on_a_turn_is_not_a_changed_square(tmp_path):
    game, d = _pool_walker(tmp_path, tick_on_turn=True)
    got = d.walk("MI")
    assert got["square_before"] != got["square_after"]


class StoryMap(PoolMap):
    """A `PoolMap` whose step can land on `boxes` chained `PRESS
    <ENTER>/<RETURN> TO CONTINUE` story boxes, each left with `Return`; after
    the last one the screen is `then` (the map, or a fight)."""

    BARS = {**PoolMap.BARS, "story": b"\x3c\x5b\x7e"}

    def __init__(self, tmp, boxes=1, then="map", **kw):
        super().__init__(tmp, **kw)
        self.boxes, self.then = boxes, then

    def key(self, k, gap=0.0):
        if self.mode == "story":
            self.keys.append(k)
            if k == "Return":
                self.boxes -= 1
                if not self.boxes:
                    self.mode = self.then
            return
        super().key(k, gap)


def _story_walker(tmp_path, monkeypatch, title, boxes=1, then="map"):
    game = StoryMap(tmp_path, boxes=boxes, then=then)
    d = da.Driver(game, lambda **k: None, "A", title)
    d.where = "map"
    d.world_ink = game.capture().ink(dosbox.BAR)
    d.world_sig = screens.bar_signature(game.capture())
    d.game = PoolMovement(game)
    real = d.game.step

    def step():
        # The step moves the party and the box covers the bar, so the map
        # bar `move` waits for never comes back: False, as the game gives.
        real()
        game.mode = "story" if game.boxes else game.then
        return game.mode == "map"

    d.game.step = step
    monkeypatch.setattr(da, "WALK_CONTINUE_BARS", {
        title: _screen(StoryMap.BARS["story"], b"").glyphs(dosbox.BAR)})
    return game, d


@pytest.mark.parametrize("title", ["pool", "curse"])
@pytest.mark.parametrize("boxes", [1, 3])
def test_a_walk_step_onto_a_story_box_answers_it_and_carries_on(tmp_path, monkeypatch,
                                                               title, boxes):
    game, d = _story_walker(tmp_path, monkeypatch, title, boxes=boxes)
    got = d.walk("MI")
    assert d.game.keys == ["Right", "Right", "Up"]
    assert game.keys == ["Return"] * boxes and game.mode == "map"
    assert got["square_before"] != got["square_after"]
    assert [(e["kind"], e["step"]) for e in d.events] == [("press_continue", "walk-step")] * boxes
    assert d.where == "map"


def test_a_story_box_that_leads_into_a_fight_still_stops_the_walk(tmp_path, monkeypatch):
    game, d = _story_walker(tmp_path, monkeypatch, "curse", then="fight")
    with pytest.raises(da.StepFailed, match="map bar did not return after the step"):
        d.walk("MI")
    assert game.keys == ["Return"] and game.mode == "fight"


def test_a_step_straight_into_a_fight_presses_nothing(tmp_path, monkeypatch):
    game, d = _story_walker(tmp_path, monkeypatch, "curse", boxes=0, then="fight")
    with pytest.raises(da.StepFailed, match="map bar did not return after the step"):
        d.walk("MI")
    assert game.keys == []


def test_story_boxes_past_the_bound_stop_the_walk(tmp_path, monkeypatch):
    game, d = _story_walker(tmp_path, monkeypatch, "curse",
                            boxes=da.WALK_CONTINUE_ROUNDS + 1)
    with pytest.raises(da.StepFailed, match="still showing after 5 were answered"):
        d.walk("MI")
    assert game.keys == ["Return"] * da.WALK_CONTINUE_ROUNDS


def test_the_walk_story_bars_are_the_titles_measured_continue_bars():
    assert da.WALK_CONTINUE_BARS == {"pool": da.POOL_CONTINUE_BAR,
                                     "curse": da.CURSE_CONTINUE_BAR}


def test_the_captured_gharri_story_box_is_the_curse_walk_story_bar():
    """Route 12's step from 3,14 onto 2,14 in Curse's town, whose box the
    walk stopped at before it answered story boxes."""
    screen = _capture("dos-12", "011-lost-walk-step", "22", ("boot1",), size="320x200!")
    assert screen.glyphs(dosbox.BAR) == da.WALK_CONTINUE_BARS["curse"]


def test_a_square_that_changes_on_a_pool_turn_stops_the_walk(tmp_path):
    game, d = _pool_walker(tmp_path)
    real = d.game.turn_right

    def turn_right():
        real()
        game.x += 1
        return True

    d.game.turn_right = turn_right
    with pytest.raises(da.StepFailed, match="square changed on a turn"):
        d.walk("MI")
    assert d.game.keys == ["Right"]


def test_a_blank_status_line_is_never_the_pool_walk_baseline(tmp_path):
    game, d = _pool_walker(tmp_path, status_on=False)
    with pytest.raises(da.StepFailed, match="blank"):
        d.walk("MI")
    assert d.game.keys == []


@pytest.mark.parametrize("title,steps,why", [
    ("pool", ("load", "rest 5m"), "needs camp first"),
    ("pool", ("load", "camp", "begin"), "puts the party on the map"),
    ("pool", ("load", "save D"), "needs camp first"),
    ("pool", ("load", "camp", "walk MI"), "walk needs the map"),
    ("pool", ("load", "display"), "display needs camp first"),
    ("curse", ("load", "display"), "display needs camp first"),
    ("curse", ("load", "begin", "walk 1"), "walk MI"),
    ("ssb", ("load", "begin", "walk MI"), "walk 1"),
    ("curse", ("load", "camp"), "needs begin first"),
    ("curse", ("load", "begin", "train 1"), "party menu"),
    ("curse", ("camp",), "needs load first"),
    ("curse", ("load", "begin", "camp", "camp"), "already camped"),
    ("ssb", ("load", "train 1"), "curse only"),
    ("ssb", ("load", "load"), "the first"),
    ("ssb", ("press Return",), "needs load first"),
    ("curse", ("load", "press Return", "begin"), "only press, shot and read"),
])
def test_orders_the_game_does_not_allow(title, steps, why):
    with pytest.raises(ValueError, match=why):
        da.validate_steps(_steps(*steps), title)


def test_silver_blades_is_installed_under_its_own_letter(tmp_path):
    save, dest = tmp_path / "staged", tmp_path / "play"
    save.mkdir()
    dest.mkdir()
    for name in ("SAVGAMA.DAT", "CHRDATA1.SAV"):
        (save / name).write_bytes(b"x")
    with pytest.raises(ValueError, match="install A as A"):
        staging.install(save, dest, "D")
    assert list(dest.iterdir()) == []
    assert staging.install(save, dest, "a")["as_slot"] == "A"


def test_a_folder_of_two_slots_needs_the_one_named(tmp_path):
    for name in ("SAVGAMA.DAT", "savgamb.dat", "CHRDATA1.SAV", "CHRDATB1.SAV"):
        (tmp_path / name).write_bytes(name.encode())
    with pytest.raises(FileNotFoundError, match="--from-slot"):
        staging.source_slot(tmp_path)
    assert staging.source_slot(tmp_path, "b") == "B"
    with pytest.raises(FileNotFoundError, match="holds no SAVGAMC"):
        staging.source_slot(tmp_path, "C")
    dest = tmp_path / "play"
    dest.mkdir()
    took = staging.install(tmp_path, dest, "B", "B")
    assert sorted(p.name for p in dest.iterdir()) == ["CHRDATB1.SAV", "SAVGAMB.DAT"]
    assert (dest / "CHRDATB1.SAV").read_bytes() == b"CHRDATB1.SAV"
    assert took["from_slot"] == "B"


def test_install_blocks_a_letter_the_container_does_not_name(tmp_path):
    """The engine loads by the saved game's own file list, so a slot renamed
    from J to A loaded no party in the Curse boot that tried it."""
    save, dest = tmp_path / "staged", tmp_path / "play"
    save.mkdir()
    dest.mkdir()
    for name in ("SAVGAMJ.DAT", "CHRDATJ1.SAV"):
        (save / name).write_bytes(b"x")
    (dest / "KEEP.ME").write_bytes(b"untouched")
    with pytest.raises(ValueError, match="install J as J"):
        staging.install(save, dest, "A")
    assert [p.name for p in dest.iterdir()] == ["KEEP.ME"]


def test_a_run_asked_for_another_letter_is_blocked_before_a_slot_is_claimed(
        tmp_path, monkeypatch, capsys):
    save = tmp_path / "staged"
    save.mkdir()
    for name in ("SAVGAMJ.DAT", "CHRDATJ1.SAV"):
        (save / name).write_bytes(b"x")

    def claimed(*a, **k):
        raise AssertionError("an emulator slot was claimed")

    monkeypatch.setattr(da.dosbox, "claim", claimed)
    # `main` turns the rejection into a usage error.
    with pytest.raises(SystemExit):
        da.main(["--title", "curse", "--save", str(save), "--slot", "A",
                 "--steps", "load", "--out", str(tmp_path / "out")])
    assert "pass --slot J" in capsys.readouterr().err


def _curse_record(name: bytes = b"MATHEW") -> bytes:
    from goldbox import dos_port
    size = dos_port.deltas_for("curse-of-the-azure-bonds").record_size
    data = bytearray(size)
    data[0] = len(name)
    data[1:1 + len(name)] = name
    return bytes(data)


def test_the_stages_write_what_they_log(tmp_path):
    from goldbox import dos_codec
    (tmp_path / "SAVGAMJ.DAT").write_bytes(bytes(0xE00))
    (tmp_path / "CHRDATJ1.SAV").write_bytes(_curse_record())
    (tmp_path / "CHRDATJ1.FX").write_bytes(bytes.fromhex("080000ff00") + bytes(4))
    hall = staging.stage_hall(tmp_path, "j")
    assert (tmp_path / "SAVGAMJ.DAT").read_bytes()[0xD51:0xD53] == b"\xff\x00"
    assert (hall["before"], hall["after"]) == ("0000", "ff00")
    xp = staging.stage_xp(tmp_path, "J", 1, 5000)
    assert dos_codec.read_character(tmp_path / "CHRDATJ1.SAV").get("experience") == 5000
    assert xp["name"] == "MATHEW"
    line, node = da.parse_node("1=141:10080:1:1")
    got = staging.stage_node(tmp_path, "J", line, node)
    fx = (tmp_path / "CHRDATJ1.FX").read_bytes()
    assert len(fx) == 18 and fx[9:14] == bytes((141, 0x60, 0x27, 1, 1))
    assert got["file"] == "CHRDATJ1.FX" and got["node"]["minutes"] == 10080
    assert [n.hex()[:10] for n in dos_codec.read_character(
        tmp_path / "CHRDATJ1.SAV").effects] == ["080000ff00", "8d60270101"]


@pytest.mark.parametrize("bad", ["0=1:2:3:4", "1=1:2:3", "1=256:0:0:0",
                                 "1=1:65536:0:0", "x"])
def test_a_bad_node_is_blocked(bad):
    with pytest.raises(ValueError):
        da.parse_node(bad)


def test_a_stage_control_line_parses_control_alone_or_with_share():
    assert da.parse_control("1=0xB1") == (1, 0xB1, None)
    assert da.parse_control("2=0xB1:3") == (2, 0xB1, 3)
    assert da.parse_control("3=177:1") == (3, 177, 1)


@pytest.mark.parametrize("bad", ["0=1", "1=1:2:3", "1=256", "1=1:256", "x"])
def test_a_bad_stage_control_line_is_blocked(bad):
    with pytest.raises(ValueError):
        da.parse_control(bad)


def test_read_slot_reports_the_control_and_treasure_share_bytes(tmp_path):
    """`read_slot`'s control and share bytes are `field_83_87`, indexed the
    way `goldbox.dos_codec.to_neutral` does: control at index 1 and share at
    index 2 of Curse's five-byte field (#529)."""
    (tmp_path / "SAVGAMJ.DAT").write_bytes(bytes(13149))
    record = bytearray(_curse_record())
    from goldbox import dos_port
    f83 = dos_port.FIELDS_BY_NAME_FOR["curse-of-the-azure-bonds"]["field_83_87"]
    record[f83.offset + 1] = 0xB1
    record[f83.offset + 2] = 3
    (tmp_path / "CHRDATJ1.SAV").write_bytes(bytes(record))
    out = da.read_slot(tmp_path, "J")
    mathew = out["characters"][0]
    assert (mathew["control"], mathew["treasure_share"]) == (0xB1, 3)


def test_compare_shares_flags_only_a_changed_control_or_share():
    before = {"characters": [{"name": "MATHEW", "control": 0xB1, "treasure_share": 1},
                             {"name": "GUY", "control": 0, "treasure_share": 0}]}
    after = {"characters": [{"name": "MATHEW", "control": 0xB1, "treasure_share": 1},
                            {"name": "GUY", "control": 0, "treasure_share": 5}]}
    rows = {r["name"]: r for r in da.compare_shares(before, after)}
    assert rows["MATHEW"]["matches"] is True
    assert rows["GUY"]["matches"] is False
    assert (rows["GUY"]["share_before"], rows["GUY"]["share_after"]) == (0, 5)


def test_share_verdict_names_the_character_whose_byte_drifted():
    read = {"slots": {"D": {"shares": [
        {"name": "GUY", "present": True, "matches": False,
         "control_before": 0, "control_after": 0,
         "share_before": 0, "share_after": 5}]}}}
    assert "GUY" in da.share_verdict(read)


def test_share_verdict_is_none_when_every_share_matches():
    read = {"slots": {"D": {"shares": [
        {"name": "GUY", "present": True, "matches": True,
         "control_before": 0, "control_after": 0,
         "share_before": 0, "share_after": 0}]}}}
    assert da.share_verdict(read) is None
    assert da.share_verdict(None) is None


def _node(minutes=0):
    return {"id": 32, "minutes": minutes, "data": 0}


_RAISED_BEFORE = {"characters": [{"name": "WISHFTR", "control": 0, "treasure_share": 1},
                                 {"name": "GUY", "control": 0, "treasure_share": 0}]}


def _raised_after(guy_control=0, nodes=True, name="WISHFTR"):
    return {"characters": [
        {"name": name, "control": 179, "treasure_share": 1,
         "nodes": [_node()] if nodes else []},
        {"name": "GUY", "control": guy_control, "treasure_share": 0, "nodes": []}]}


_ANIMATE_STEPS = ["cast 1 ANIMATE-DEAD"]


def _animated(steps, expects, slot):
    return da.animated_members([da.parse_step(t) for t in steps],
                               [da.parse_expect(t) for t in expects], slot)


def test_the_member_an_animate_dead_run_raised_may_change_control_to_179():
    animated = _animated(_ANIMATE_STEPS, ["wishftr:32:0"], _raised_after())
    rows = {r["name"]: r for r in da.compare_shares(
        _RAISED_BEFORE, _raised_after(), animated)}
    assert rows["WISHFTR"]["matches"] is True
    assert rows["WISHFTR"]["control_changed"] == {"WISHFTR": [0, 179],
                                                  "reason": "animated"}
    assert "control_changed" not in rows["GUY"]


def test_a_mixed_case_roster_name_is_exempt():
    slot = _raised_after(name="Wishftr")
    before = {"characters": [{"name": "Wishftr", "control": 0, "treasure_share": 1}]}
    animated = _animated(_ANIMATE_STEPS, ["WISHFTR:32:0"], slot)
    assert da.compare_shares(before, slot, animated)[0]["matches"] is True


def test_another_members_control_change_still_fails_in_an_animate_dead_run():
    slot = _raised_after(guy_control=179)
    animated = _animated(_ANIMATE_STEPS, ["WISHFTR:32:0"], slot)
    rows = {r["name"]: r for r in da.compare_shares(_RAISED_BEFORE, slot, animated)}
    assert rows["GUY"]["matches"] is False


def test_a_run_without_an_animate_dead_step_fails_on_any_control_change():
    slot = _raised_after()
    animated = _animated(["cast 1 BLESS"], ["WISHFTR:32:0"], slot)
    assert animated == set()
    assert da.compare_shares(_RAISED_BEFORE, slot, animated)[0]["matches"] is False


def test_a_refuted_id_32_expectation_exempts_nobody():
    slot = _raised_after(nodes=False)
    assert _animated(_ANIMATE_STEPS, ["WISHFTR:32:0"], slot) == set()


def test_an_expectation_for_another_node_exempts_nobody():
    slot = _raised_after()
    slot["characters"][0]["nodes"].append({"id": 5, "minutes": 9, "data": 0})
    assert _animated(_ANIMATE_STEPS, ["WISHFTR:5:9"], slot) == set()


def test_the_raised_member_may_not_change_share_or_take_another_control():
    animated = {"WISHFTR"}
    after = _raised_after()
    after["characters"][0]["treasure_share"] = 5
    assert da.compare_shares(_RAISED_BEFORE, after, animated)[0]["matches"] is False
    after = _raised_after()
    after["characters"][0]["control"] = 7
    assert da.compare_shares(_RAISED_BEFORE, after, animated)[0]["matches"] is False


def _charm_rows(before_nodes, after_nodes, before_control=179, after_control=0,
                title="curse", share_after=1, animated=frozenset()):
    before = {"characters": [{"name": "RANGER", "control": before_control,
                              "treasure_share": 1, "nodes": before_nodes}]}
    after = {"characters": [{"name": "RANGER", "control": after_control,
                             "treasure_share": share_after, "nodes": after_nodes}]}
    return da.compare_shares(before, after, animated, title)[0]


_CHARM = {"id": 11, "minutes": 0, "data": 0x26}


def test_a_charm_the_game_ended_may_reset_control_to_0():
    row = _charm_rows([_CHARM], [])
    assert row["matches"] is True
    assert row["control_changed"] == {"RANGER": [179, 0], "reason": "charm ended"}


def test_a_fear_the_game_ended_may_reset_control_to_0():
    row = _charm_rows([{"id": 142, "minutes": 0, "data": 0}], [])
    assert row["matches"] is True
    assert row["control_changed"]["reason"] == "fear ended"


def test_silver_blades_fear_may_reset_control_on_a_silver_blades_run():
    row = _charm_rows([{"id": 111, "minutes": 0, "data": 0}], [], title="ssb")
    assert row["matches"] is True
    assert row["control_changed"]["reason"] == "fear ended"


def test_a_control_reset_fails_while_the_charm_node_remains():
    assert _charm_rows([_CHARM], [_CHARM])["matches"] is False


def test_a_control_reset_fails_when_no_node_was_held_before():
    assert _charm_rows([], [])["matches"] is False


def test_a_control_reset_fails_when_the_share_changed():
    assert _charm_rows([_CHARM], [], share_after=2)["matches"] is False


def test_a_control_reset_fails_from_a_control_other_than_b3():
    assert _charm_rows([_CHARM], [], before_control=0xB2)["matches"] is False


def test_a_control_reset_fails_to_a_control_other_than_0():
    assert _charm_rows([_CHARM], [], after_control=5)["matches"] is False


def test_a_control_reset_fails_when_a_node_of_another_id_left():
    assert _charm_rows([{"id": 12, "minutes": 0, "data": 0}], [])["matches"] is False


def test_the_other_titles_fear_id_does_not_excuse_a_control_reset():
    node = [{"id": 111, "minutes": 0, "data": 0}]
    assert _charm_rows(node, [], title="curse")["matches"] is False
    assert _charm_rows([{"id": 142, "minutes": 0, "data": 0}], [],
                       title="ssb")["matches"] is False


def test_an_animated_member_gets_no_charm_ended_exception():
    assert _charm_rows([_CHARM], [], animated={"RANGER"})["matches"] is False


def test_read_step_exempts_the_raised_member_and_the_run_passes(monkeypatch, tmp_path):
    # The installed slot and the resave are the same mock, so the control
    # change is staged by giving read_slot a different answer per folder.
    (tmp_path / "save").mkdir()
    slots = {"installed": {"characters": [dict(c, nodes=[]) for c in
                                          _RAISED_BEFORE["characters"]]},
             "resave": _raised_after()}
    monkeypatch.setattr(da, "read_slot", lambda folder, letter: {
        "slot": letter, "clock": [0] * 6, "clock_minutes": 0,
        **slots["installed" if folder.name == "installed" else "resave"]})
    got = da.read_step(tmp_path / "save", tmp_path / "out", "A", ["D"],
                       [da.parse_step(t) for t in _ANIMATE_STEPS],
                       [da.parse_expect("WISHFTR:32:0")])
    assert got["verdicts"][0]["verdict"] == "accepts"
    assert da.share_verdict(got) is None and da.expect_verdict(got) is None


def test_read_step_passes_its_title_to_the_share_check(monkeypatch, tmp_path):
    fear = {"id": 111, "minutes": 0, "data": 0}
    member = {"name": "RANGER", "treasure_share": 1}
    slots = {"installed": {"characters": [dict(member, control=0xB3, nodes=[fear])]},
             "resave": {"characters": [dict(member, control=0, nodes=[])]}}
    (tmp_path / "save").mkdir()
    monkeypatch.setattr(da, "read_slot", lambda folder, letter: {
        "slot": letter, "clock": [0] * 6, "clock_minutes": 0,
        **slots["installed" if folder.name == "installed" else "resave"]})
    got = da.read_step(tmp_path / "save", tmp_path / "out", "A", ["D"], [], [],
                       title="ssb")
    assert da.share_verdict(got) is None


def test_the_run_passes_its_title_to_read_step(monkeypatch, tmp_path):
    seen = []
    _walk_run(monkeypatch, tmp_path, _read())
    monkeypatch.setattr(da, "read_step",
                        lambda *a, **k: seen.append((a, k)) or _read())
    args = _run_args(tmp_path, _WALK_STEPS)
    args.title = "ssb"
    da.run(args)
    (a, k), = seen
    assert k.get("title", a[7] if len(a) > 7 else None) == "ssb"


def test_no_title_or_the_pool_title_grants_no_fear_exception():
    node = [{"id": 111, "minutes": 0, "data": 0}]
    assert _charm_rows(node, [], title=None)["matches"] is False
    assert _charm_rows(node, [], title="pool")["matches"] is False


def test_a_refuted_expectation_fails_the_run_and_exempts_nobody(monkeypatch, tmp_path):
    slots = {"installed": {"characters": [dict(c, nodes=[]) for c in
                                          _RAISED_BEFORE["characters"]]},
             "resave": _raised_after(nodes=False)}
    (tmp_path / "save").mkdir()
    monkeypatch.setattr(da, "read_slot", lambda folder, letter: {
        "slot": letter, "clock": [0] * 6, "clock_minutes": 0,
        **slots["installed" if folder.name == "installed" else "resave"]})
    got = da.read_step(tmp_path / "save", tmp_path / "out", "A", ["D"],
                       [da.parse_step(t) for t in _ANIMATE_STEPS],
                       [da.parse_expect("WISHFTR:32:0")])
    assert "WISHFTR" in da.expect_verdict(got)
    assert "WISHFTR" in da.share_verdict(got)


def test_stage_control_writes_the_control_and_share_bytes(tmp_path):
    (tmp_path / "CHRDATJ1.SAV").write_bytes(_curse_record())
    got = staging.stage_control(tmp_path, "J", 1, 0xB1, 3)
    from goldbox import dos_codec
    c = dos_codec.read_character(tmp_path / "CHRDATJ1.SAV")
    control_raw = c.raw("field_83_87")
    assert (control_raw[1], control_raw[2]) == (0xB1, 3)
    assert got["after"] == "b1" and got["share_after"] == "03"


def test_stage_control_leaves_the_share_byte_alone_when_not_given(tmp_path):
    (tmp_path / "CHRDATJ1.SAV").write_bytes(_curse_record())
    got = staging.stage_control(tmp_path, "J", 1, 0xB1)
    assert "share_after" not in got
    from goldbox import dos_codec
    c = dos_codec.read_character(tmp_path / "CHRDATJ1.SAV")
    assert c.raw("field_83_87")[2] == 0


def test_the_command_line_wires_stage_control_into_staging(tmp_path):
    (tmp_path / "CHRDATJ1.SAV").write_bytes(_curse_record())
    args = _run_args(tmp_path, [])
    args.stage_control = ["1=0xB1:1"]
    done = da.stage(tmp_path, "J", args)
    assert len(done) == 1
    assert done[0]["stage"] == "control"
    assert (done[0]["after"], done[0]["share_after"]) == ("b1", "01")
    from goldbox import dos_codec
    control_raw = dos_codec.read_character(tmp_path / "CHRDATJ1.SAV").raw("field_83_87")
    assert (control_raw[1], control_raw[2]) == (0xB1, 1)


def test_check_staging_blocks_a_stage_control_line_with_no_chrdat(tmp_path):
    args = _run_args(tmp_path, [])
    args.stage_control = ["1=0xB1:1"]
    with pytest.raises(ValueError, match="line 1"):
        da.check_staging(args, tmp_path, "J")


def test_experience_is_compared_by_name():
    before = {"characters": [{"name": "GUY", "experience": 200000},
                             {"name": "PAINE", "experience": None}]}
    after = {"characters": [{"name": "GUY", "experience": 202750}]}
    rows = {r["name"]: r for r in da.compare_experience(before, after)}
    assert rows["GUY"]["gained"] == 2750
    assert rows["PAINE"]["gained"] is None


# -- Curse's party menu: load, save, train -------------------------------------------


class FakeCurseMenu(FakePool):
    """Curse from the title menu to the party menu, its save and its training.

    `trainable` names the roster lines the school takes; `learns` is how many
    `LEARN` screens a training leaves; `asks_quit` puts a `QUIT TO DOS`
    question after a party-menu save.
    """

    BARS = {**FakePool.BARS, "title": b"\x01", "which": b"\x02\x03",
            "party": b"\x04\x05\x06", "offer": b"\x07", "learn": b"\x08\x09",
            "psave": b"\x0a", "pquit": b"\x0b\x0c", "sheet": b"\x0d\x0e",
            "pick": b"\x0f\x10"}

    def __init__(self, tmp, trainable=(1,), learns=1, asks_quit=False, size=6,
                 loads=True, sheet_shows=None):
        super().__init__(tmp, keys=TITLE_KEYS["curse"])
        #: The line a sheet draws the name of, when it is not the highlighted one.
        self.sheet_shows = sheet_shows
        self.mode, self.line, self.size = "title", 1, size
        # A slot the engine cannot load leaves the empty menu, which draws no
        # roster.
        self.loads = self.drawn = loads
        self.trainable, self.learns, self.asks_quit = set(trainable), learns, asks_quit
        self.trained: list[int] = []
        self.left = 0

    def key(self, k, gap=0.0):
        self.keys.append(k)
        m = self.mode
        if m == "title" and k == "l":
            self.mode = "which"
        elif m == "which" and k.upper() in "ABCDEFGHIJ":
            self.mode = "party"
            self.drawn = self.loads
        elif m == "party" and k == "End":
            self.line = self.line % self.size + 1
        elif m == "party" and k == "t" and self.line in self.trainable:
            self.mode = "offer"
        elif m == "offer" and k == "y":
            self.trained.append(self.line)
            self.left = self.learns
            self.mode = "learn" if self.left else "party"
        elif m == "learn" and k == "l":
            self.left -= 1
            self.mode = "learn" if self.left else "party"
        elif m == "party" and k == "s":
            self.mode = "psave"
        elif m == "psave" and k.upper() in "ABCDEFGHIJ":
            (self.save_dir / f"SAVGAM{k.upper()}.DAT").write_bytes(
                bytes((len(self.trained),)))
            self.mode = "pquit" if self.asks_quit else "party"
        elif m == "pquit" and k == "n":
            self.mode = "party"
        elif m == "party" and k == "b":
            self.mode = "map"
        elif m == "party" and k == "v":
            self.mode = "sheet"
        elif m == "pick" and k == "Down":
            self.line = self.line % self.size + 1
        elif m == "pick" and k == "s":
            self.mode = "sheet"
        elif m == "sheet" and k == "e":
            self.mode = "party"
        else:
            super().key(k, gap)

    def capture(self):
        if self.mode in FakePool.BARS:
            return super().capture()
        text = bytes((self.line,)) if self.mode in ("party", "pick") else b""
        frame = _screen(self.BARS[self.mode], text)
        if self.mode == "sheet":
            return _with_roster(frame, "party", self.size, self.line,
                                sheet=self.sheet_shows or self.line)
        if self.mode in ("party", "pick") and self.drawn:
            return _with_roster(frame, "party", self.size, self.line)
        return frame

    def press_until_change(self, key, tries=5, gap=0.8):
        before = self.capture().digest()
        for _ in range(tries):
            self.key(key)
            if self.capture().digest() != before:
                return True
        return False


_MEASURED_CURSE_PARTY_BAR = da.CURSE_PARTY_BAR


@pytest.fixture(autouse=True)
def _curse_party_bar_measured(monkeypatch):
    """The fake's party bar stands in for Curse's measured `CURSE_PARTY_BAR`,
    which a capture test checks."""
    monkeypatch.setattr(da, "CURSE_PARTY_BAR", screens.bar_signature(
        _screen(FakeCurseMenu.BARS["party"], b"")))


def _curse_loaded(tmp_path, **kw):
    game = FakeCurseMenu(tmp_path, **kw)
    d = da.Driver(game, lambda **k: None, "J", "curse", party_size=game.size)
    d.game.to_main_menu = lambda timeout=120.0: None
    got = d.load()
    assert game.mode == "party" and d.where == "party" and got["slot"] == "J"
    return game, d


def test_curse_loads_to_the_party_menu_pressing_the_letter_once(tmp_path):
    game, d = _curse_loaded(tmp_path)
    assert game.keys == ["l", "j"]


def test_a_curse_load_that_shows_another_bar_is_lost_at_load(tmp_path, monkeypatch):
    monkeypatch.setattr(da, "CURSE_PARTY_BAR", "0" * 16)
    game = FakeCurseMenu(tmp_path)
    d = da.Driver(game, lambda **k: None, "J", "curse", party_size=game.size)
    d.game.to_main_menu = lambda timeout=120.0: None
    with pytest.raises(da.StepFailed, match="did not leave the party menu's bar"):
        d.load()
    assert d.party_sig is None


def test_a_curse_load_that_draws_no_roster_is_lost_at_load(tmp_path):
    game = FakeCurseMenu(tmp_path, loads=False)
    d = da.Driver(game, lambda **k: None, "J", "curse", party_size=game.size)
    d.game.to_main_menu = lambda timeout=120.0: None
    with pytest.raises(da.StepFailed, match="loaded no party"):
        d.load()
    assert d.party_sig is None and game.keys == ["l", "j"]


def test_a_silver_blades_load_that_draws_no_roster_is_lost_at_load(tmp_path):
    game = FakeCurseMenu(tmp_path, loads=False)
    game.mode = "title"

    class Ssb:
        def to_party_menu(self, deadline=None):
            pass

        def menu(self, row, label):
            game.key("l")
            game.key("j")
            game.mode = "party"

        def bar(self, screen=None):
            return "party_menu"

        def wait_bar(self, want, timeout=45.0, deadline=None):
            return game.capture()

    d = da.Driver(game, lambda **k: None, "J", "ssb", party_size=game.size)
    d._ssb = Ssb()
    d.s.wait_for = lambda pred, timeout=0.0: True
    with pytest.raises(da.StepFailed, match="loaded no party"):
        d.load()
    assert d.party_sig is None


def test_curse_view_picks_with_end_views_with_v_and_leaves_with_e(tmp_path):
    game, d = _curse_loaded(tmp_path)
    got = d.view(2)
    assert game.keys[2:] == ["End", "v", "e"]
    assert got["name"] == screens.roster_name(game.capture(), "party", 2)
    assert got["pages"] == [] and got["line"] == 2
    assert d.where == "party" and game.mode == "party" and d.on_party_menu()


def test_a_curse_sheet_of_another_member_stops_the_view(tmp_path):
    game, d = _curse_loaded(tmp_path, sheet_shows=3)
    with pytest.raises(da.StepFailed, match="not roster line 2"):
        d.view(2)
    assert "e" not in game.keys


def test_a_curse_pick_that_never_lands_names_the_key_it_pressed(tmp_path):
    """`End` moving two lines at a time from line 1 never reaches line 2."""
    game, d = _curse_loaded(tmp_path)
    game.key = lambda k, gap=0.0: (game.keys.append(k),
                                   setattr(game, "line", (game.line + 1) % 6 + 1))
    with pytest.raises(da.StepFailed, match="presses of End never brought"):
        d.view(2)


def test_curse_trains_the_line_asked_for_and_learns_its_spell(tmp_path):
    game, d = _curse_loaded(tmp_path, trainable=(3,), learns=2)
    got = d.train(3)
    assert game.trained == [3] and game.mode == "party"
    assert game.keys.count("End") == 2 and got["after"] == ["l", "l"]
    # The highlight stays where the last command left it, and End wraps.
    game.trainable = {2}
    d.train(2)
    assert game.trained == [3, 2] and game.keys.count("End") == 2 + 5


def test_a_school_that_blocks_stops_the_run(tmp_path):
    game, d = _curse_loaded(tmp_path, trainable=())
    with pytest.raises(da.StepFailed, match="train-blocked"):
        d.train(1)
    assert game.trained == []


@pytest.mark.parametrize("asks_quit", [False, True])
def test_the_party_menu_save_is_believed_by_the_file(tmp_path, asks_quit):
    game, d = _curse_loaded(tmp_path, asks_quit=asks_quit)
    got = d.save("B")
    assert (game.save_dir / "SAVGAMB.DAT").is_file() and game.mode == "party"
    assert got["at"] == "party menu"
    assert (da.QUIT_NO in game.keys) is asks_quit


def _ssb_view_driver(tmp_path):
    game = FakeCurseMenu(tmp_path)
    game.mode = "party"
    asked = []

    class Ssb:
        def menu(self, row, label):
            asked.append(row)
            game.mode = "pick"

        def wait_bar(self, want, timeout=45.0):
            asked.append(want)
            return game.capture()

    d = da.Driver(game, lambda **k: None, "J", "ssb", party_size=game.size)
    d._ssb = Ssb()
    d.where = "party"
    d.party_sig = screens.bar_signature(game.capture())
    return game, d, asked


def test_silver_blades_view_selects_at_pick_character(tmp_path):
    game, d, asked = _ssb_view_driver(tmp_path)
    got = d.view(2)
    assert asked == [route_silver_blades.MENU_AFTER["view"], "pick_character"]
    assert game.keys == ["Down", "s", "e"]
    assert got["name"] == screens.roster_name(game.capture(), "party", 2)
    assert got["pages"] == [] and d.where == "party" and game.mode == "party"


def test_a_silver_blades_sheet_of_another_member_stops_the_view(tmp_path):
    game, d, _ = _ssb_view_driver(tmp_path)
    game.sheet_shows = 4
    with pytest.raises(da.StepFailed, match="not roster line 2"):
        d.view(2)


def test_ssb_intro_leaves_move_mode_with_e_not_escape(monkeypatch):
    keys = []
    frames = iter([_screen(b"\x01", b""), _screen(b"\x02", b"")])

    class Session:
        def settle(self, quiet=1.0, timeout=40.0):
            return next(frames)

        def key(self, k, gap=0.0):
            keys.append(k)

    move_glyphs = _screen(b"\x01", b"").glyphs(dosbox.BAR)
    map_glyphs = _screen(b"\x02", b"").glyphs(dosbox.BAR)
    ssb = route_silver_blades.Route(Session(), lambda **k: None)
    ssb.shot = lambda label: label
    monkeypatch.setitem(route_silver_blades.BARS, move_glyphs, "move_mode")
    monkeypatch.setitem(route_silver_blades.BARS, map_glyphs, "map")
    ssb.intro()
    assert keys == ["e"]


def test_curse_begins_and_camps(tmp_path):
    game, d = _curse_loaded(tmp_path)
    d.begin()
    assert game.mode == "map" and d.where == "map"
    d.camp()
    assert game.mode == "camp"
    d.rest(5)
    assert game.rested == [5]


# -- the later titles' conversion, off the player's disks ---------------------------


@pytest.mark.parametrize("title,name,effect_file", [
    ("curse", "PHILIPPE", "CHRDATA6.FX"),
    ("ssb", "MORGAINE", "CHRDATA6.SFX"),
])
def test_a_later_title_party_converts_with_its_bless_and_reads_back(
        tmp_path, title, name, effect_file):
    """Save As DOS of the title's engine-written C64 specimen with a Bless
    row for party slot 0 whose duration byte leaves 47 minutes at the
    save's own clock: nothing dropped, `01 2F 00 05 00` in the first
    character's effect file, and the reading the run's `read` step makes of
    it accepts him at 47."""
    from editor import saveplan
    base = da.c64_base(title)
    if not base.is_file():
        pytest.skip(f"needs {base.name} in $WISH_SPECIMENS/por-c64")
    try:
        built = da.build_source([(63, 1, 0, 0x2F, 5)], tmp_path, title)
    except FileNotFoundError:
        pytest.skip("needs the DOS archives ($FR_ARCHIVES)")
    except saveplan.MissingAssets:
        pytest.skip("needs the title's own C64 disks")
    assert built["dropped"] == [] and built["losses"] == []
    assert built["minutes_left"] == [47]
    assert [n["raw"] for n in built["nodes"][effect_file]] == ["012f000500"]
    slot = built["read"]["A"]
    assert da.judge(da.Expect(name, 1, 47, 5), slot)["verdict"] == "accepts"
    assert slot["place"]["set_out"] is True


# -- --convert: any C64 or Amiga save, through Save As DOS -------------------


def test_main_calls_build_saveas_source_with_the_convert_path_slot_and_title(
        tmp_path, monkeypatch):
    """`--convert PATH` calls `build_saveas_source(PATH, "A", out, title)`,
    and a blocked result stops the run with `summary["lost"]` set."""
    calls = []

    def fake(path, slot, out, title, names=None):
        calls.append((path, slot, out, title))
        return {"stopped": "not this title"}

    monkeypatch.setattr(da, "build_saveas_source", fake)
    rc = da.main(["--title", "curse", "--convert", "X", "--out", str(tmp_path / "out"),
                 "--issue", "1", "--run", "t"])
    assert rc == 1
    assert calls == [("X", "A", tmp_path / "out", "curse")]
    summary = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert summary["lost"]


def test_convert_and_save_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        da.main(["--title", "curse", "--convert", "X", "--save", "."])


def test_convert_blocks_darkness():
    with pytest.raises(SystemExit):
        da.main(["--title", "darkness", "--convert", "X"])


def test_name_options_parse_into_positions():
    assert da.parse_names(["0=Wren", "3=A B"], "pool") == {0: "Wren", 3: "A B"}


@pytest.mark.parametrize("names, message", [
    (["Wren"], "not POSITION=NAME"),
    (["x=Wren"], "not POSITION=NAME"),
    (["0="], "printable ASCII"),
    (["--name=-1=Wren"], "not POSITION=NAME"),
    (["0=Wr\u00e9n"], "printable ASCII"),
    (["0=Wren", "0=Bran"], "position 0 twice"),
    (["1=" + "W" * 16], "over the 15"),
    (["--name=1=" + "W" * 16], "over the 15")])
def test_a_bad_name_option_is_blocked_before_any_boot(
        names, message, tmp_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("reached the conversion")
    monkeypatch.setattr(da, "build_saveas_source", boom)
    argv = ["--title", "pool", "--convert", "X", "--out", str(tmp_path / "o")]
    for n in names:
        argv += [n] if n.startswith("--name=") else ["--name", n]
    with pytest.raises(SystemExit):
        da.main(argv)
    assert message in capsys.readouterr().err


def test_name_needs_convert(capsys):
    with pytest.raises(SystemExit):
        da.main(["--title", "pool", "--save", ".", "--name", "0=Wren"])
    assert "--name goes with --convert" in capsys.readouterr().err


def test_a_good_name_with_convert_does_not_exit_at_parsing(tmp_path, monkeypatch):
    monkeypatch.setattr(da, "build_saveas_source",
                        lambda *a, **k: {"stopped": "stop"})
    assert da.main(["--title", "pool", "--convert", "X", "--name", "0=Wren",
                    "--out", str(tmp_path / "o"), "--issue", "1", "--run", "t"]) == 1


def test_main_hands_the_chosen_names_to_the_conversion(tmp_path, monkeypatch):
    calls = []

    def fake(path, slot, out, title, names=None):
        calls.append(names)
        return {"stopped": "stop here"}

    monkeypatch.setattr(da, "build_saveas_source", fake)
    rc = da.main(["--title", "pool", "--convert", "X", "--name", "0=Wren",
                  "--name", "2=Bran", "--out", str(tmp_path / "out"),
                  "--issue", "1", "--run", "t"])
    assert rc == 1
    assert calls == [{0: "Wren", 2: "Bran"}]


def test_save_as_dos_passes_names_and_blocks_cleanly(tmp_path, monkeypatch):
    """A fake `prepare_save_as` records `names`; an out-of-party position and a
    name still too long are `blocked` reports, and any other SaveAsError
    still raises."""
    from types import SimpleNamespace

    from editor import saveplan
    from editor.convert import Source
    from tools.convert import convertdrops
    seen = []
    raises = []

    def fake_prepare(party, port, dest, assets, **kw):
        seen.append(kw)
        raise raises[0]

    monkeypatch.setattr(saveplan, "prepare", lambda party: None)
    monkeypatch.setattr(Source, "of_snapshot", staticmethod(lambda snap: None))
    monkeypatch.setattr(saveplan, "resolve_assets", lambda *a, **k: None)
    monkeypatch.setattr(convertdrops, "game_files", None, raising=False)
    monkeypatch.setattr(da.dosbox, "find_game", lambda stem: None)
    monkeypatch.setattr(saveplan, "prepare_save_as", fake_prepare)
    party = SimpleNamespace(members=[object(), object()])

    built = da._save_as_dos(party, tmp_path, "pool", {}, {2: "X"})
    assert "position 2" in built["stopped"] and seen == []

    raises.append(saveplan.NamesDoNotFit(((1, "L" * 18),), 15))
    built = da._save_as_dos(party, tmp_path, "pool", {}, {0: "Wren"})
    assert "position 1" in built["stopped"] and seen == [{"names": {0: "Wren"}}]
    built = da._save_as_dos(party, tmp_path, "pool", {})
    assert "position 1" in built["stopped"] and seen[1] == {}

    raises[0] = saveplan.SaveAsError("other")
    with pytest.raises(saveplan.SaveAsError):
        da._save_as_dos(party, tmp_path, "pool", {}, {0: "Wren"})


def test_build_saveas_source_blocks_a_title_mismatch(tmp_path):
    """A Pool of Radiance disk built the way `build_source`'s fallback builds
    one, offered to `--convert` for curse, is blocked rather than converted."""
    from goldbox import dos_codec
    from goldbox.c64_port import POOL_OF_RADIANCE
    from goldbox.savegame import SaveGame0, SaveGame1

    fixtures = da.REPO / "tests" / "fixtures"
    payload = SaveGame0.from_prg((fixtures / "savedgame0.bin").read_bytes()).to_bytes()
    save1 = SaveGame1.from_prg((fixtures / "savedgame1.bin").read_bytes()).to_bytes()
    disk = tmp_path / "pool.d64"
    disk.write_bytes(dos_codec.save_disk(payload, save1, POOL_OF_RADIANCE).to_bytes())

    out = tmp_path / "out"
    out.mkdir()
    built = da.build_saveas_source(disk, "A", out, "curse")
    assert "stopped" in built


def test_build_saveas_source_converts_a_c64_curse_or_ssb_specimen(tmp_path):
    """`--convert` on `ssb-c64`'s Amiga-to-C64 walk-resave specimen: nothing
    dropped or lost, and the read-back holds the six characters' shares,
    matching what #639's and #529's plans record for this disk."""
    from editor import saveplan
    from tools.registry import specimens

    disk = (specimens.tree_root() / "ssb-c64"
            / "WISH-SPEC-ssb-512-amigatoc64-walk-resave.D64")
    if not disk.is_file():
        pytest.skip("needs $WISH_SPECIMENS/ssb-c64/"
                     "WISH-SPEC-ssb-512-amigatoc64-walk-resave.D64")
    try:
        built = da.build_saveas_source(disk, "A", tmp_path, "ssb")
    except FileNotFoundError:
        pytest.skip("needs the DOS archives ($FR_ARCHIVES)")
    except saveplan.MissingAssets:
        pytest.skip("needs Silver Blades' own C64 disks")
    assert built["dropped"] == [] and built["losses"] == []
    read = built["read"]["A"]
    assert [c["control"] for c in read["characters"]] == [0, 0, 0, 0, 0, 0]
    assert [c["treasure_share"] for c in read["characters"]] == [1, 1, 1, 0, 1, 1]


class _FakeCurseContinue(FakeCurseMenu):
    """Curse whose BEGIN lands on `screens` continue screens before the map."""

    BARS = {**FakeCurseMenu.BARS, "cont": b"\x12\x13"}

    def __init__(self, tmp, screens=1):
        super().__init__(tmp)
        self.screens = screens

    def key(self, k, gap=0.0):
        if self.mode == "party" and k == "b":
            self.keys.append(k)
            self.mode = "cont"
        elif self.mode == "cont":
            self.keys.append(k)
            if k == "Return":
                self.screens -= 1
                self.mode = "cont" if self.screens > 0 else "map"
        else:
            super().key(k, gap)


def _curse_continue_driver(tmp_path, monkeypatch, screens_up):
    game = _FakeCurseContinue(tmp_path, screens_up)
    monkeypatch.setattr(da, "CURSE_CONTINUE_BAR",
                        _screen(game.BARS["cont"], b"").glyphs(dosbox.BAR))
    d = da.Driver(game, lambda **k: None, "J", "curse", party_size=game.size)
    d.game.to_main_menu = lambda timeout=120.0: None
    d.load()
    return game, d


def test_curse_begin_returns_past_a_continue_screen_then_camps(tmp_path, monkeypatch):
    game, d = _curse_continue_driver(tmp_path, monkeypatch, 1)
    d.begin()
    assert game.keys.count("Return") == 1 and d.where == "map"
    d.camp()
    assert game.mode == "camp"


def test_curse_begin_stops_when_the_continue_screen_never_clears(tmp_path, monkeypatch):
    game, d = _curse_continue_driver(tmp_path, monkeypatch, 99)
    shots = []
    real = game.shot
    game.shot = lambda name, allow_blank=False: (shots.append(name), real(name))[1]
    with pytest.raises(da.StepFailed,
                       match=r"continue screen is still showing after 3 were "
                             r"answered; see \d+-lost-begin-continue\.png"):
        d.begin()
    assert da.CONTINUE_ROUNDS == 3
    assert game.keys.count("Return") == 3
    assert shots[-1].endswith("lost-begin-continue")


class _FakePoolContinue(FakePool):
    """Pool whose load lands on `screens` continue screens before the map."""

    BARS = {**FakePool.BARS, "cont": b"\x14\x15"}

    def __init__(self, tmp, screens=1):
        super().__init__(tmp)
        self.mode = "cont" if screens else "map"
        self.screens = screens

    def key(self, k, gap=0.0):
        if self.mode == "cont":
            self.keys.append(k)
            if k == "Return":
                self.screens -= 1
                self.mode = "cont" if self.screens > 0 else "map"
        else:
            super().key(k, gap)


def _pool_continue_driver(tmp_path, monkeypatch, screens_up):
    game = _FakePoolContinue(tmp_path, screens_up)
    monkeypatch.setattr(da, "POOL_CONTINUE_BAR",
                        _screen(game.BARS["cont"], b"").glyphs(dosbox.BAR))
    d = da.Driver(game, lambda **k: None, "A", "pool")
    d.game.to_main_menu = lambda timeout=120.0: None
    d.game.load_game = lambda letter, timeout=90.0: None
    return game, d


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_load_presses_return_past_a_continue_screen_then_camps(tmp_path, monkeypatch):
    game, d = _pool_continue_driver(tmp_path, monkeypatch, 1)
    d.load()
    assert game.keys.count("Return") == 1 and d.where == "map"
    assert [e["kind"] for e in d.events] == ["press_continue"]
    assert d.events[0]["step"] == "load"
    d.camp()
    assert game.mode == "camp"


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_load_presses_through_rolfs_tour_to_the_map(tmp_path, monkeypatch):
    # A party that has never taken Rolf's opening tour (clock zero at area 0,
    # 15,1: any party freshly made in the Amiga or C64 game) loads into eight
    # chained continue screens, "GREETINGS, COURAGEOUS ONES" through "YOUR
    # TOUR IS ENDED", before the map (#631, run dce274bcca-tour-count-cap25).
    game, d = _pool_continue_driver(tmp_path, monkeypatch, 8)
    d.load()
    assert game.keys.count("Return") == 8 and d.where == "map"
    assert [e["kind"] for e in d.events] == ["press_continue"] * 8
    assert da.CONTINUE_ROUNDS == 3


def test_pool_load_stops_when_the_continue_screen_never_clears(tmp_path, monkeypatch):
    game, d = _pool_continue_driver(tmp_path, monkeypatch, 99)
    with pytest.raises(da.StepFailed,
                       match=r"continue screen is still showing after 10 were "
                             r"answered; see \d+-lost-load-continue\.png"):
        d.load()
    assert da.POOL_LOAD_CONTINUE_ROUNDS == 10
    assert game.keys.count("Return") == 10


def test_curse_begin_presses_nothing_when_no_continue_screen_shows(tmp_path):
    game, d = _curse_loaded(tmp_path)
    d.begin()
    assert "Return" not in game.keys


def test_encamp_is_never_pressed_at_the_party_menu(tmp_path):
    # `E` is exit to DOS at Curse's party menu: a BEGIN that did not take
    # leaves the run stopped there, not pressing on into camp.
    game, d = _curse_loaded(tmp_path)
    game.key = lambda k, gap=0.0: game.keys.append(k)
    with pytest.raises(da.StepFailed):
        d.begin()
    with pytest.raises(da.StepFailed, match="lost-camp"):
        d.camp()
    assert "e" not in game.keys


# -- review findings: rejections before a slot is claimed, and the log handle -----------


def test_hall_is_blocked_for_a_title_whose_hall_word_is_not_documented(capsys):
    with pytest.raises(SystemExit):
        da.main(["--title", "darkness", "--save", ".", "--hall", "--steps", "load"])
    assert "--hall" in capsys.readouterr().err


def test_hall_blocks_a_save_too_short_to_hold_the_word(tmp_path):
    (tmp_path / "SAVGAMA.DAT").write_bytes(bytes(0x100))
    with pytest.raises(ValueError, match="too short"):
        staging.stage_hall(tmp_path, "A")
    assert (tmp_path / "SAVGAMA.DAT").stat().st_size == 0x100


def test_hall_is_no_longer_blocked_for_ssb(tmp_path):
    """Silver Blades' hall word is now measured at the same offset as Pool's
    and Curse's (`docs/194-the-dos-training-ladder.md`), so `--hall` staging
    is no longer blocked for it before a slot is claimed."""
    import argparse
    (tmp_path / "SAVGAMA.DAT").write_bytes(bytes(staging.HALL_WORD + 2))
    args = argparse.Namespace(title="ssb", hall=True, xp=[], add_node=[], stage_control=[])
    da.check_staging(args, tmp_path, "A")


def _staged_run(monkeypatch, tmp_path, **extra):
    log = _fake_run(monkeypatch, tmp_path)
    saves = tmp_path / "saves"
    saves.mkdir()
    (saves / "SAVGAMA.DAT").write_bytes(bytes(0xE00))
    (saves / "CHRDATA1.SAV").write_bytes(b"x")
    args = _run_args(tmp_path, ["load"])
    args.save = str(saves)
    for k, v in extra.items():
        setattr(args, k, v)
    return log, args


@pytest.mark.parametrize("extra", [{"xp": ["3=100"]}, {"add_node": ["3=1:2:3:4"]}])
def test_a_line_with_no_record_is_blocked_before_a_slot_is_claimed(
        monkeypatch, tmp_path, extra):
    log, args = _staged_run(monkeypatch, tmp_path, **extra)
    with pytest.raises(ValueError, match="CHRDATA3.SAV"):
        da.run(args)
    assert "claim" not in log


def test_a_short_save_is_blocked_for_hall_before_a_slot_is_claimed(monkeypatch, tmp_path):
    log, args = _staged_run(monkeypatch, tmp_path, hall=True)
    (tmp_path / "saves" / "SAVGAMA.DAT").write_bytes(bytes(0x100))
    with pytest.raises(ValueError, match="too short"):
        da.run(args)
    assert "claim" not in log


@pytest.mark.parametrize("key", ["e", "E", "Escape", "escape"])
def test_press_blocks_exit_to_dos_and_escape(key):
    with pytest.raises(ValueError):
        da.parse_step(f"press {key}")


def test_the_log_is_closed_when_the_save_has_no_such_slot(monkeypatch, tmp_path):
    _fake_run(monkeypatch, tmp_path)
    opened = []
    real = pathlib.Path.open

    def spy(self, *a, **k):
        h = real(self, *a, **k)
        opened.append(h)
        return h

    monkeypatch.setattr(pathlib.Path, "open", spy)
    empty = tmp_path / "empty"
    empty.mkdir()
    args = _run_args(tmp_path, ["load"])
    args.save = str(empty)
    with pytest.raises(FileNotFoundError):
        da.run(args)
    assert opened and all(h.closed for h in opened)


def test_begin_presses_b_once_so_a_slow_boot_cannot_press_it_on_the_map(tmp_path):
    game, d = _curse_loaded(tmp_path)
    seen = []
    real = d.press_screen_changes
    d.press_screen_changes = lambda key, **kw: (seen.append((key, kw)), real(key, **kw))[1]
    d.begin()
    assert seen == [(da.PARTY_BEGIN, {"tries": 1, "wait": 30.0})]


# -- Pools of Darkness: an Amiga slot converted, installed, read and driven -------------


def _pod_node(**fields) -> bytes:
    """One twenty-byte Amiga item node, big-endian, from `amiga_pod`'s own map."""
    from goldbox import amiga_pod
    raw = bytearray(amiga_pod.ITEM_FILE_SIZE)
    for name, value in fields.items():
        f, at = amiga_pod.ITEM_FIELDS[name], amiga_pod.ITEM_FIELD_AT[name]
        raw[at:at + f.size] = value.to_bytes(f.size, "big")
    return bytes(raw)


def _pod_block(name: str, thief: tuple[int, ...], nodes: list[bytes],
               heads: int) -> bytes:
    """A character block of an Amiga saved game: `amiga_pod.PodWriter`'s
    404-byte record, its head-item count, then the nodes after it."""
    import struct

    from goldbox import amiga_pod, amiga_savegame
    record = bytearray(amiga_pod.PodWriter(
        name=name, hit_points_max=30, thief_skills=thief,
        character_class=amiga_pod.CLASSES.index("THIEF"),
        class_levels=(0, 0, 0, 0, 0, 0, 20),
        class_bits=amiga_pod.CLASS_BIT["thief"]).to_bytes()[
            :amiga_savegame.POD_RECORD_BYTES])
    struct.pack_into(">I", record, amiga_savegame.POD_ITEM_COUNT_AT, heads)
    struct.pack_into(">I", record, amiga_savegame.POD_EFFECT_HEAD_AT, 0)
    return bytes(record) + b"".join(nodes)


#: INA's pick pockets as the Amiga engine wrote it for a level 29 thief
#: (#650), and TRIPEL's under 128, which both readings agree on.
INA_THIEF = (135, 90, 80, 70, 60, 50, 40, 30)
TRIPEL_THIEF = (120, 1, 2, 3, 4, 5, 6, 7)


def _pod_disk(tmp_path: pathlib.Path, slot: str = "C",
             vault: bytes | None = None) -> pathlib.Path:
    """A blank Amiga save disk holding one Pools of Darkness saved game,
    built from the documented format: INA with a readied scroll case of two
    scrolls and a sword, and TRIPEL with nothing.  No game file is read.

    `vault`, if given, is written as `Vault<slot>.DAT` beside the save."""
    import struct

    from goldbox import amiga_savegame, dos_savegame
    from goldbox.amiga_adf import AmigaDisk
    case = _pod_node(type_index=0x49, quantity=2, readied=1, weight=2)
    mage = _pod_node(type_index=39, charges=5, effect=6, power=7, weight=1, quantity=1)
    cleric = _pod_node(type_index=40, charges=8, effect=9, power=10, weight=1, quantity=1)
    sword = _pod_node(type_index=1, weight=60, quantity=1, readied=1)
    blocks = [_pod_block("INA", INA_THIEF, [case, mage, cleric, sword], 2),
              _pod_block("TRIPEL", TRIPEL_THIEF, [], 0)]
    data = bytearray(amiga_savegame.POD_VAR_BYTES)
    data[dos_savegame.POD_PARTY_COUNT - 1] = len(blocks)
    data += bytes((3, 4, 2, 5, 137, 0))
    data += bytes((dos_savegame.POD_MODE_DUNGEON, dos_savegame.POD_MODE_DUNGEON))
    data += struct.pack(">HHH", 6, 0, len(blocks))
    for block in blocks:
        data += block
    data += bytes(amiga_savegame.POD_SAVEGAME_SIZE - len(data))
    disk = AmigaDisk.blank("PDARKSAVE")
    disk.make_dir(f"/{amiga_savegame.SAVE_DRAWER}")
    disk.write_file(amiga_savegame.pod_slot_path(slot), bytes(data))
    if vault is not None:
        disk.write_file(amiga_savegame.pod_vault_path(slot), vault)
    path = tmp_path / "pod-save.adf"
    path.write_bytes(disk.to_bytes())
    return path


def test_an_amiga_vault_reaches_the_dos_folder_with_each_case_split(tmp_path):
    """The vault beside the converted slot: coins, a sword, a scroll case
    split into its two scrolls, and an Amiga type-105 item that becomes DOS
    type 73 (#678). Before the fix `VAULTA.DAT` was 12 zero bytes; a red run
    that only raises `AttributeError` on a missing name does not count."""
    import struct

    from goldbox import amiga_pod

    sword = _pod_node(type_index=1, weight=60, quantity=1)
    case = _pod_node(type_index=0x49, quantity=2, weight=2)
    mage = _pod_node(type_index=39, charges=5, effect=6, power=7,
                     weight=1, quantity=1)
    cleric = _pod_node(type_index=40, charges=8, effect=9, power=10,
                       weight=1, quantity=1)
    longsword = _pod_node(type_index=105, weight=80, quantity=1)
    body = sword + case + mage + cleric + longsword
    vault = (struct.pack(">III", 1, 2, 3) + struct.pack(">HH", 0xFFFF, 3)
             + body)
    vault += bytes(4016 - len(vault))

    out = tmp_path / "out"
    out.mkdir()
    disk_path = _pod_disk(tmp_path, slot="A", vault=vault)
    built = da.build_amiga_source(str(disk_path), "SavGamA.pty", out)
    assert "stopped" not in built, built.get("stopped")

    heads = [amiga_pod.PodItem.from_bytes(sword),
             amiga_pod.PodItem.from_bytes(case),
             amiga_pod.PodItem.from_bytes(longsword)]
    expected_items = amiga_pod.unbundle(heads, [mage, cleric])
    expected = (struct.pack("<III", 1, 2, 3)
               + b"".join(it.to_dos_bytes() for it in expected_items))

    got = (out / "source" / "VAULTA.DAT").read_bytes()
    assert got == expected
    assert [(i["type_index"], i["spells"], i["weight"])
           for i in built["read"]["A"]["vault"]["items"]] == [
        (1, [0, 0, 0], 60), (39, [5, 6, 7], 2), (40, [8, 9, 10], 2),
        (73, [0, 0, 0], 80)]


@pytest.fixture
def pod_source(tmp_path, monkeypatch):
    """The synthetic disk converted by `build_amiga_source`, with the flag
    unset beforehand so the test sees the driver set it and put it back."""
    import os

    from editor import convert
    monkeypatch.delenv(convert.POD_CONVERT_ENV, raising=False)
    out = tmp_path / "out"
    out.mkdir()
    built = da.build_amiga_source(str(_pod_disk(tmp_path)), "SavGamC.pty", out)
    assert convert.POD_CONVERT_ENV not in os.environ
    return out, built


def test_an_amiga_slot_converts_by_the_convert_route_and_reads_back(pod_source):
    """The product route with the flag set for the conversion only: nothing
    dropped or lost, INA's pick pockets 135 and TRIPEL's 120, and the case
    replaced by its two scrolls with their spell ids, all as `read` reports
    them."""
    out, built = pod_source
    assert "stopped" not in built, built.get("stopped")
    assert built["direction"] == "PodAmigaToDos"
    assert built["dropped"] == [] and built["losses"] == []
    assert built["amiga_slot"] == "SavGamC.pty" and built["dos_slot"] == "A"
    assert len(built["adf_sha256"]) == 64
    assert built["files"] == ["CHRDATA1.SAV", "CHRDATA1.THG", "CHRDATA2.SAV",
                              "SAVGAMA.PTY", "VAULTA.DAT"]
    slot = da.read_slot(out / "source", "A")
    assert slot == built["read"]["A"]
    who = {c["name"]: c for c in slot["characters"]}
    assert who["INA"]["thief"] == dict(zip(da.THIEF_FIELDS, INA_THIEF))
    assert who["TRIPEL"]["thief"]["thief_pick_pockets"] == 120
    assert who["INA"]["item_count"] == 3
    assert [(i["type_index"], i["spells"]) for i in who["INA"]["items"]] == [
        (39, [5, 6, 7]), (40, [8, 9, 10]), (1, [0, 0, 0])]
    assert slot["vault_bytes"] == 12 and slot["place"]["x"] == 3


def test_a_loss_only_the_debug_log_hears_of_is_listed_among_the_warnings(
        tmp_path, monkeypatch):
    """The DOS writer sends some losses to `wish.goldbox.dos_codec`'s log and
    to neither `dropped` nor `losses` (a spell id past the book, #509), so the
    run's report lists every warning the conversion logged.  The warning is
    raised here by a wrapper, so the test does not rest on which losses the
    writer logs today."""
    from goldbox import dos_codec
    real = dos_codec.new_pod_save_from

    def logging_one(*a, **k):
        dos_codec._log.warning("spells_known: id %s is outside the book", 126)
        return real(*a, **k)

    monkeypatch.setattr(dos_codec, "new_pod_save_from", logging_one)
    out = tmp_path / "out"
    out.mkdir()
    built = da.build_amiga_source(str(_pod_disk(tmp_path)), "C", out)
    assert built["dropped"] == [] and built["losses"] == []
    assert built["warnings"] == [
        "wish.goldbox.dos_codec: spells_known: id 126 is outside the book"]


def test_a_slot_the_disk_does_not_hold_is_blocked_before_anything_is_written(
        tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    built = da.build_amiga_source(str(_pod_disk(tmp_path)), "D", out)
    assert "slot D" in built["stopped"]
    assert not (out / "source").exists()


def test_a_pools_of_darkness_slot_installs_its_container_vault_and_records(
        pod_source, tmp_path):
    """`SAVGAMA.PTY`, `VAULTA.DAT` and every `CHRDATA*`, which is what
    `new_pod_save_from` writes.  Before this title, `source_slot` blocked the
    folder: it holds 0 SAVGAM?.DAT files."""
    out, _ = pod_source
    dest = tmp_path / "play"
    dest.mkdir()
    (dest / "SAVGAMB.PTY").write_bytes(b"the archives' own")
    took = staging.install(out / "source", dest, "A")
    assert sorted(took["files"]) == sorted(p.name for p in dest.iterdir()) == [
        "CHRDATA1.SAV", "CHRDATA1.THG", "CHRDATA2.SAV", "SAVGAMA.PTY", "VAULTA.DAT"]
    with pytest.raises(ValueError, match="install A as A"):
        staging.install(out / "source", dest, "D")


def test_the_read_step_sets_each_members_skills_and_items_side_by_side(
        pod_source, tmp_path):
    import shutil
    out, _ = pod_source
    shutil.copytree(out / "source", out / "installed")
    result = da.read_step(out / "source", out, "A", ["A"], [], [])
    rows = {r["name"]: r for r in result["slots"]["A"]["members"]}
    assert rows["INA"]["changed"] == [] and rows["TRIPEL"]["present"]
    assert rows["INA"]["thief"]["after"]["thief_pick_pockets"] == 135
    lines = da.describe(result)
    assert any(line.startswith("  INA: pick pockets 135, 3 items (3 read)")
               for line in lines)


def test_the_title_reads_the_archives_own_container_and_records():
    """A control on a container the engine wrote: the archives' shipped slot
    A, read in place and never written.  Its provenance is unknown
    (`.claude/rules/testing.md`), so only the reading's own invariants are
    asserted: six characters, eight thief skills each, and an item count
    that matches the items read."""
    try:
        save = dospod.find_game() / "SAVE"
    except FileNotFoundError:
        pytest.skip("needs the DOS Pools of Darkness archives ($FR_ARCHIVES)")
    slot = da.read_slot(save, "A")
    assert len(slot["characters"]) == 6
    for c in slot["characters"]:
        assert len(c["thief"]) == 8
        assert c["item_count"] == len(c["items"])


@pytest.mark.parametrize("steps", [
    ("load", "begin", "camp", "sheet 4", "items 4", "sheet 6", "save D", "read"),
    ("load", "begin", "walk 1", "shot walked", "camp", "save D", "read"),
    ("load", "save B", "begin", "camp", "rest 5m", "save D", "read"),
])
def test_orders_pools_of_darkness_allows(steps):
    da.validate_steps(_steps(*steps), "darkness")


@pytest.mark.parametrize("title,steps,why", [
    ("darkness", ("load", "train 1"), "curse only"),
    ("darkness", ("load", "camp"), "needs begin first"),
    ("darkness", ("load", "begin", "walk MI"), "walk 1"),
    ("darkness", ("load", "begin", "sheet 1"), "sheet needs camp first"),
    ("darkness", ("load", "items 1"), "items needs camp first"),
    ("darkness", ("load", "begin", "camp", "display"), "curse, pool, ssb only"),
    ("pool", ("load", "walk 1"), "walk MI"),
    ("pool", ("load", "camp", "sheet 1"), "loaded map"),
    ("curse", ("load", "begin", "camp", "items 2"), "darkness only"),
    ("darkness", ("load", "halve 1 1"), "halve needs camp first"),
    ("darkness", ("load", "begin", "join 1 1"), "join needs camp first"),
    ("darkness", ("load", "begin", "camp", "press v", "join 1 1"),
     "only press, shot and read"),
    ("pool", ("load", "camp", "halve 1 1"), "darkness only"),
])
def test_orders_pools_of_darkness_does_not_allow(title, steps, why):
    with pytest.raises(ValueError, match=why):
        da.validate_steps(_steps(*steps), title)


def test_the_new_steps_parse_and_bad_ones_are_blocked():
    assert da.parse_step("sheet 4").line == 4
    assert (da.parse_step("items 8").kind, da.parse_step("items 8").line) == ("items", 8)
    assert da.parse_step("walk 1").key == "1"
    for bad in ("sheet", "sheet 9", "items 0", "walk 3"):
        with pytest.raises(ValueError):
            da.parse_step(bad)
    assert [da.parse_amiga_slot(s) for s in ("SavGamA.pty", "savgamh.PTY", "c")] \
        == ["A", "H", "C"]
    for bad in ("SavGamK.pty", "savgam.dat", "AB"):
        with pytest.raises(ValueError):
            da.parse_amiga_slot(bad)


@pytest.mark.parametrize("argv,why", [
    (["--title", "darkness", "--fixture-row", "3F=01:00:2F:01"], "no C64 port"),
    (["--title", "curse", "--amiga-slot", "A", "--amiga-disk", "x.adf"],
     "--title darkness"),
    (["--title", "darkness", "--amiga-slot", "A"], "needs --amiga-disk"),
    (["--title", "darkness", "--amiga-slot", "K", "--amiga-disk", "x.adf"],
     "not an Amiga"),
])
def test_the_command_line_blocks_a_bad_source_before_any_boot(argv, why, capsys):
    with pytest.raises(SystemExit):
        da.main(argv)
    assert why in capsys.readouterr().err


#: The current character's name colour and another's, EGA 15 and 11
#: (`GAME.OVR` 0x34825 and 0x35AC0).
_WHITE, _CYAN = b"\xff\xff\xff", b"\x55\xff\xff"


def _pod_name(n: int) -> bytes:
    """Member `n`'s synthetic name: fifteen cells, the first different for
    every member, each with fewer lit pixels than paper, as a letter has."""
    return bytes((1 << (n - 1) % 8,)) + bytes((0x11, 0x22, 0x00, 0x44)) * 3 + b"\x81\x00"


def _draw_name(px: bytearray, x: int, y: int, name: bytes, colour: bytes) -> None:
    for cell, pattern in enumerate(name):
        for dy in range(screens.POD_NAME_ROWS):
            for dx in range(screens.CELL):
                if pattern >> ((dx + dy) % 8) & 1:
                    at = ((y + dy) * W + x + cell * screens.CELL + dx) * 3
                    px[at:at + 3] = colour


def _with_roster(frame: dosbox.Screen, where: str, size: int, current: int,
                 sheet: int | None = None) -> dosbox.Screen:
    """`frame` with the roster drawn where the game draws it, the current
    member white; or, with `sheet`, that member's name where a sheet has it."""
    px = bytearray(frame.px)
    if sheet is not None:
        _draw_name(px, *screens.POD_SHEET_NAME, _pod_name(sheet), _WHITE)
    else:
        x, y = screens.POD_ROSTER[where]
        for n in range(1, size + 1):
            _draw_name(px, x, y + screens.CELL * (n - 1), _pod_name(n),
                       _WHITE if n == current else _CYAN)
    return dosbox.Screen(W, H, bytes(px))


class FakePod(FakePool):
    """DOS Pools of Darkness from its title screens to camp, as `GAME.EXE`'s
    strings and its load routine (`GAME.OVR` 0x12887) describe it: an
    optional copy-protection question that echoes a typed key and takes
    `Return`; Silver Blades' party-menu rows (`Down` moves, `Return` picks;
    row 0 is `Create New Character` before a load, row 2 `Load Saved Game`);
    `LOAD FROM WHERE? POOLS SECRET EXIT`, where only `P` leads on and a slot
    letter does nothing; `LOAD WHICH GAME:` listing only the letters whose
    `SAVGAM<L>.PTY` exists; after a load row 3 views, row 6 saves and row 7
    begins, or 5, 8 and 9 when the save's byte 0x2F adds `Train` and `Human
    Change`; the roster with the current character in white, which `Down`
    moves a member on and wraps and `End` does not move (the selector at
    0x2680C), in camp and at `View`'s `PICK CHARACTER`, where `S` views;
    the sheet's name, `ITEMS` with `Next`, and `Exit` back to where `View`
    was pressed."""

    BARS = {**FakePool.BARS, "title": b"\x21", "question": b"\x22", "menu": b"\x23\x24",
            "which": b"\x25", "party": b"\x26\x27", "create": b"\x28",
            "sheet": b"\x29\x2a", "items": b"\x2b\x2c", "psave": b"\x2d",
            "from": b"\x2e\x2f", "secret": b"\x30", "tour": b"\x31\x32",
            "story": b"\x34", "cont": b"\x35\x36", "overland": b"\x37\x38",
            "town": b"\x3a\x3b\x3c", "pick": b"\x3d\x3e"}

    def __init__(self, tmp, question=True, pages=3, size=6, journal=False,
                 swallow_p=False, tours=0, after_tour="map", dead_n=False,
                 continues=0, dead_return=False, late_return=False,
                 late_n=False, after_town="map", swallow_down=False,
                 dead_down=False, same_sheet=False, pick_opens=True,
                 animated=False, item_lists=None, dead_item_down=False,
                 dead_halve=False):
        super().__init__(tmp, keys=TITLE_KEYS["darkness"])
        #: Each member's `ITEMS` rows as quantities, when given: the list is
        #: drawn (a readied-column mark and, on the current row, the white
        #: band), `Down` moves the current row unless `dead_item_down`, `h`
        #: halves a stack above 1 into a new row after it while the list is
        #: under 16 items unless `dead_halve`, and `j` joins the current row
        #: with another of the same quantity.
        self.item_lists = item_lists
        self.dead_item_down, self.dead_halve, self.item_row = (
            dead_item_down, dead_halve, 0)
        #: The roster selector drops the first `Down` (`swallow_down`), or
        #: every one (`dead_down`); the sheet always draws member 1
        #: (`same_sheet`), the game not viewing whom the highlight is on;
        #: `View` at the party menu opens nothing (`not pick_opens`); the
        #: camp picture changes every capture (`animated`), as the fire does.
        self.swallow_down, self.dead_down = swallow_down, dead_down
        self.same_sheet, self.pick_opens, self.animated = same_sheet, pick_opens, animated
        self.frame, self.view_from, self.into_pick = 0, "camp", []
        self.mode = "title"
        #: `YES NO` bars the arrival asks, one after another, after `Begin`
        #: and the journal question; each draws its own text, takes `N`
        #: (`into_tour` has every key typed at one) unless `dead_n`, and the
        #: last leads to `after_tour`.
        self.tours, self.after_tour, self.dead_n = tours, after_tour, dead_n
        self.into_tour: list[str] = []
        #: Story dialogs after the last bar, each drawing its own text, taking
        #: `Return` (`into_cont` has every key typed at one) unless
        #: `dead_return`; the last leads to the map.
        self.continues, self.dead_return, self.into_cont = continues, dead_return, []
        #: The first `Return` takes effect only after one more capture, as a
        #: redraw that lands after the driver's wait has run out.
        self.late_return, self.late_wait = late_return, 0
        #: The first `N` takes effect only after one more capture.
        self.late_n, self.late_n_wait = late_n, False
        #: A town services screen: every key typed at it (`into_town`), and
        #: where `M` leads.
        self.after_town, self.into_town = after_town, []
        #: Keys typed at the map, where a stray `Return` or `N` would land.
        self.into_map: list[str] = []
        #: `Begin` leads to the journal question, which draws every key
        #: typed into it (`into_journal`) and leaves for the map on `Return`
        #: after something was typed (`GAME.OVR` 0x3603).
        self.journal, self.into_journal, self.journal_typed = journal, [], 0
        #: `LOAD FROM WHERE?` drops the first `p`.
        self.swallow_p = swallow_p
        self.titles, self.question, self.typed = 2, question, 0
        self.row, self.line, self.size = 0, 1, size
        self.page, self.pages = 1, pages
        self.loaded = False
        self.train = False
        #: The archives' stub is 1,364 bytes with byte 0x2F zero.
        (self.save_dir / "SAVGAMA.PTY").write_bytes(bytes(1364))

    def key(self, k, gap=0.0):
        self.keys.append(k)
        m = self.mode
        if m == "tour":
            self.into_tour.append(k)
            if k == "n" and self.late_n:
                self.late_n, self.late_n_wait = False, True
            elif k == "n" and not self.dead_n:
                self._decline()
        elif m == "town":
            self.into_town.append(k)
            if k == "m":
                self.mode = self.after_town
        elif m == "cont":
            self.into_cont.append(k)
            if k == "Return" and self.late_return:
                self.late_return, self.late_wait = False, 1
            elif k == "Return" and not self.dead_return:
                self._next_cont()
        elif m == "map" and k in ("Return", "n"):
            self.into_map.append(k)
        elif m == "overland" and k == da.ENCAMP:
            self.mode = "camp"
        elif m == "journal":
            self.into_journal.append(k)
            if k == "Return" and self.journal_typed:
                self.mode, self.journal_typed = self.arrival(), 0
            elif len(k) == 1:
                self.journal_typed += 1
        elif m == "from" and k == "p" and self.swallow_p:
            self.swallow_p = False
        elif m == "title":
            if k == "Escape":
                self.titles -= 1
                if self.titles == 0:
                    self.mode = "question" if self.question else "menu"
        elif m == "question" and k == "Return" and self.typed:
            self.mode, self.question = "menu", False
        elif m == "question" and k not in ("Escape", "Return"):
            self.typed += 1
        elif m in ("menu", "party") and k == "Down":
            self.row = (self.row + 1) % 11
        elif m in ("menu", "party") and k == "Return":
            shift = 2 * self.train
            begin = "journal" if self.journal else self.arrival()
            picked = {("menu", 0): "create", ("menu", 2): "from",
                      ("party", 6 + shift): "psave", ("party", 7 + shift): begin}
            if self.pick_opens:
                picked[("party", 3 + shift)] = "pick"
            self.mode = picked.get((m, self.row), m)
        elif m == "pick":
            self.into_pick.append(k)
            if k in ("Down", "Up"):
                self._roster(k)
            elif k == "s":
                self.mode, self.view_from = "sheet", "party"
            elif k == "Escape":
                self.mode = "party"
        elif m == "from" and k.upper() in "PSE":
            self.mode = {"P": "which", "S": "secret", "E": "menu"}[k.upper()]
        elif m == "which" and (self.save_dir / f"SAVGAM{k.upper()}.PTY").is_file():
            got = (self.save_dir / f"SAVGAM{k.upper()}.PTY").read_bytes()
            self.train = len(got) > 0x2F and got[0x2F] != 0
            self.mode, self.row, self.loaded = "party", 0, True
        elif m == "psave" and k.upper() in "ABCDEFGHIJ":
            (self.save_dir / f"SAVGAM{k.upper()}.PTY").write_bytes(b"p")
            self.mode = "party"
        elif m == "camp" and k in ("Down", "Up"):
            self._roster(k)
        elif m == "camp" and k == "v":
            self.mode, self.view_from = "sheet", "camp"
        elif m == "sheet" and k == "i":
            self.mode, self.page, self.item_row = "items", 1, 0
        elif m == "items" and self.item_lists is not None and k in ("Down", "h", "j"):
            self._item_key(k)
        elif m == "sheet" and k == "e":
            self.mode = self.view_from
        elif m == "items" and k == "n" and self.page < self.pages:
            self.page += 1
        elif m == "items" and k == "e":
            self.mode = "sheet"
        elif m == "save" and k.upper() in "ABCDEFGHIJ":
            (self.save_dir / f"SAVGAM{k.upper()}.PTY").write_bytes(b"c")
            self.mode = "quit"
        elif m in FakePool.BARS:
            self.keys.pop()     # `FakePool.key` records it again
            super().key(k, gap)

    def _item_key(self, k: str) -> None:
        rows = self.item_lists[self.line]
        at = self.item_row
        if k == "Down" and not self.dead_item_down:
            self.item_row = min(at + 1, len(rows) - 1)
        elif k == "h" and not self.dead_halve and rows[at] > 1 and len(rows) < 16:
            rows[at:at + 1] = [rows[at] - rows[at] // 2, rows[at] // 2]
        elif k == "j":
            other = next((i for i, q in enumerate(rows) if i != at and q == rows[at]),
                         None)
            if other is not None:
                rows[at] += rows[other]
                del rows[other]
                self.item_row = at - 1 if other < at else at

    def _draw_items(self, frame: dosbox.Screen) -> dosbox.Screen:
        """The member's rows, at most `ITEM_ROWS`, as the game draws them."""
        px = bytearray(frame.px)
        x, y, w, _ = screens.ITEM_LIST_RECT
        for k, _q in enumerate(self.item_lists[self.line][:da.ITEM_ROWS]):
            top = y + k * screens.CELL
            at = ((top + 3) * W + x + 4) * 3
            px[at:at + 3] = b"\xaa\xaa\xaa"
            if k == self.item_row:
                for dx in range(60, 60 + 200):
                    at = ((top + 3) * W + x + dx) * 3
                    px[at:at + 3] = b"\xff\xff\xff"
        return dosbox.Screen(W, H, bytes(px))

    def _roster(self, k: str) -> None:
        """The selector: `Down` a member on, `Up` one back, both wrapping."""
        if self.dead_down:
            return
        if self.swallow_down:
            self.swallow_down = False
            return
        step = 1 if k == "Down" else -1
        self.line = (self.line - 1 + step) % self.size + 1

    def _decline(self) -> None:
        self.tours -= 1
        self.mode = "tour" if self.tours else self.after_tour
        if self.mode == "map" and self.continues:
            self.mode = "cont"

    def _next_cont(self) -> None:
        self.continues -= 1
        self.mode = "cont" if self.continues else "map"

    def arrival(self) -> str:
        """Where the party is once the journal question is behind it."""
        return "tour" if self.tours else "cont" if self.continues else "map"

    def capture(self):
        if self.late_n_wait and self.mode == "tour":
            # This capture still shows the old dialog; the next shows the new.
            self.late_n_wait = False
            shown = _screen(self.BARS["tour"], bytes((self.tours + 1,)))
            self._decline()
            return shown
        if self.late_wait and self.mode == "cont":
            # This capture still shows the old screen; the next shows the new.
            self.late_wait = 0
            shown = _screen(self.BARS["cont"], bytes((self.continues + 1,)))
            self._next_cont()
            return shown
        if self.mode == "journal":
            return _journal_frame(self.journal_typed)
        if self.mode in FakePool.BARS and self.mode not in ("camp",):
            return super().capture()
        text = {"title": (self.titles,), "question": (1, self.typed),
                "menu": (self.row,), "party": (self.row,),
                "camp": (self.line,),
                "sheet": (1 if self.same_sheet else self.line,),
                "items": (self.line, self.page),
                "tour": (self.tours,), "cont": (self.continues,)}.get(self.mode, ())
        bar = FakePool.BARS["camp"] if self.mode == "camp" else self.BARS[self.mode]
        frame = _screen(bar, bytes(t + 1 for t in text))
        if self.mode == "camp" and self.animated:
            self.frame += 1
            px = bytearray(frame.px)
            px[(70 * W + 60) * 3:(70 * W + 60) * 3 + 3] = bytes((self.frame % 250 + 1,)) * 3
            frame = dosbox.Screen(W, H, bytes(px))
        if self.mode == "camp" or self.mode == "pick" or (self.mode == "party"
                                                            and self.loaded):
            where = "camp" if self.mode == "camp" else "party"
            return _with_roster(frame, where, self.size, self.line)
        if self.mode == "sheet":
            return _with_roster(frame, "party", self.size, self.line,
                                sheet=1 if self.same_sheet else self.line)
        if self.mode == "items" and self.item_lists is not None:
            return self._draw_items(frame)
        return frame

    def walk_highlight(self, rect, want, key="End", timeout=20.0):
        assert rect == da.POD_MENU_RECT
        for _ in range(11):
            if self.row == want:
                return want
            self.key(key)
        return None

    def press_until_change(self, key, tries=5, gap=0.8):
        before = self.capture().digest()
        for _ in range(tries):
            self.key(key)
            if self.capture().digest() != before:
                return True
        return False


def _pod_driver(tmp_path, **kw):
    game = FakePod(tmp_path, **kw)
    d = da.Driver(game, lambda **k: None, "A", "darkness", party_size=game.size)
    return game, d


@pytest.mark.parametrize("question", [True, False])
def test_pools_of_darkness_loads_through_its_party_menu(tmp_path, question):
    """The question, when there is one, gets the probe key and `Return`; the
    party menu gets the probe key and no `Return` at `Create New Character`;
    then row 2, `Return`, `P` for POOLS at LOAD FROM WHERE?, and the slot
    letter once."""
    game, d = _pod_driver(tmp_path, question=question)
    got = d.load()
    assert game.mode == "party" and game.loaded and d.where == "party"
    assert got["questions_answered"] == int(question)
    assert got["menu_rows"] == {"view": 3, "save": 6, "begin": 7}
    assert [k for k in game.keys if k != "Escape"] == (
        ["1", "Return"] if question else []) + ["1", "Down", "Down", "Return",
                                                 "p", "a"]


def test_a_slot_letter_at_load_from_where_loads_nothing(tmp_path):
    """Run 0's stop: the letter pressed at `LOAD FROM WHERE?` changes nothing."""
    game, d = _pod_driver(tmp_path, question=False)
    game.mode = "menu"
    d.pod_menu(da.POD_LOAD_ROW, "load")
    assert game.mode == "from"
    assert not d.press_screen_changes("a", tries=1, wait=0.1)
    assert d.press_screen_changes(da.POD_LOAD_FROM, tries=1, wait=0.1)
    assert game.mode == "which"


def test_a_slot_that_is_not_installed_is_not_listed_and_stops_the_run(tmp_path):
    game = FakePod(tmp_path, question=False)
    d = da.Driver(game, lambda **k: None, "C", "darkness", party_size=game.size)
    with pytest.raises(da.StepFailed, match="slot C never loaded"):
        d.load()
    assert game.mode == "which" and not game.loaded


@pytest.mark.parametrize("savgam,rows", [
    (bytes(1364), (3, 6, 7)),
    (bytes(0x2F) + b"\x01" + bytes(1364 - 0x30), (5, 8, 9)),
    (bytes(0x2F) + b"\x80", (5, 8, 9)),
    (bytes(0x2F), (3, 6, 7)),
    (None, (3, 6, 7)),
], ids=["stub", "set", "high-bit", "short", "missing"])
def test_the_party_menu_rows_move_two_lower_when_the_training_byte_is_set(savgam, rows):
    got = da.pod_menu_after(savgam)
    assert (got["view"], got["save"], got["begin"]) == rows


_SSB_SAVGAM = 5469
_SSB_WORD = route_silver_blades.TRAIN_WORD


def _ssb_savgam(word: int) -> bytes:
    data = bytearray(_SSB_SAVGAM)
    data[_SSB_WORD:_SSB_WORD + 2] = word.to_bytes(2, "little")
    return bytes(data)


@pytest.mark.parametrize("savgam,rows", [
    (_ssb_savgam(0), (3, 6, 7)),
    (_ssb_savgam(20), (5, 8, 9)),
    (_ssb_savgam(0x00FF), (5, 8, 9)),
    (_ssb_savgam(0x0100), (5, 8, 9)),
    (bytes(0x2F) + b"\x01" + bytes(_SSB_SAVGAM - 0x30), (3, 6, 7)),
    (bytes(_SSB_WORD) + b"\x14", (3, 6, 7)),
    (None, (3, 6, 7)),
], ids=["zero", "hall-20", "staged-hall", "high-byte", "pod-byte-only",
        "short", "missing"])
def test_silver_blades_menu_rows_move_two_lower_when_the_hall_word_is_set(savgam, rows):
    """`GAME.OVR` 0x1D793 and 0x1D7B5 enable `Train Character` and `Human
    Change Classes` on one test of the word at 0xD51, never on Pools of
    Darkness' byte 0x2F."""
    got = route_silver_blades.menu_after(savgam)
    assert (got["view"], got["save"], got["begin"]) == rows


def _lit_band(top: int) -> dosbox.Screen:
    """A 320x200 frame with the menu's columns near-white from `top` for 8 rows."""
    px = bytearray(320 * 200 * 3)
    x, _, w, _ = route_silver_blades.MENU_RECT
    for y in range(top, top + 8):
        px[(y * 320 + x) * 3:(y * 320 + x + w) * 3] = b"\xff" * (w * 3)
    return dosbox.Screen(320, 200, bytes(px))


@pytest.mark.parametrize("row", [0, 8, 9, 10])
def test_the_silver_blades_menu_highlight_is_read_on_all_eleven_rows(row):
    """The long menu's `Begin Adventuring` is row 9 and `Exit to DOS` row 10.
    #628's first fixed run walked the highlight onto row 9 at y=168 and read
    None, because the rectangle stopped at nine rows."""
    screen = _lit_band(96 + 8 * row)
    assert screen.highlight_row(route_silver_blades.MENU_RECT) == row


def test_the_frame_under_the_silver_blades_menu_is_not_a_row():
    """The band from y=184 carries 79 near-white pixels of frame in every
    Silver Blades party-menu capture, with no highlight on it."""
    screen = _lit_band(184)
    assert screen.highlight_row(route_silver_blades.MENU_RECT) is None


class _SsbAsked(Exception):
    pass


def _ssb_loaded(tmp_path, word):
    """A Silver Blades driver loaded from a slot whose hall word is `word`;
    any later party-menu row it asks for stops it with `_SsbAsked`."""
    game = FakeCurseMenu(tmp_path)
    game.mode = "title"
    game.save_dir.mkdir(parents=True, exist_ok=True)
    game.save_file("J").write_bytes(_ssb_savgam(word))
    asked = []

    class Ssb:
        def to_party_menu(self, deadline=None):
            pass

        def menu(self, row, label):
            if label == "load":
                game.key("l")
                game.key("j")
                game.mode = "party"
                return
            asked.append((label, row))
            raise _SsbAsked(label)

        def bar(self, screen=None):
            return "party_menu"

        def wait_bar(self, want, timeout=45.0, deadline=None):
            return game.capture()

    d = da.Driver(game, lambda **k: None, "J", "ssb", party_size=game.size)
    d._ssb = Ssb()
    d.s.wait_for = lambda pred, timeout=0.0: True
    return d, asked


@pytest.mark.parametrize("word,rows", [(0, (3, 6, 7)), (20, (5, 8, 9))],
                         ids=["short-menu", "long-menu"])
def test_silver_blades_views_saves_and_begins_at_the_rows_its_save_draws(
        tmp_path, word, rows):
    """`WISH-SPEC-ssb-234-party-pair` slot C holds 20 there, and #628's run
    found its menu two rows longer than the fixed rows assumed."""
    d, asked = _ssb_loaded(tmp_path, word)
    got = d.load()
    for step in (lambda: d.view(1), lambda: d.save("B"), d.begin):
        with pytest.raises(_SsbAsked):
            step()
    assert asked == [("view-1", rows[0]), ("save", rows[1]), ("begin", rows[2])]
    assert got["menu_rows"] == dict(zip(("view", "save", "begin"), rows))


def test_a_save_with_the_training_byte_begins_and_saves_two_rows_lower(tmp_path):
    """`Train Character` and `Human Change Classes` sit above `View`, so a save
    with byte 0x2F set moves `Save` to row 8 and `Begin` to row 9."""
    game, d = _pod_driver(tmp_path, question=False)
    staged = bytearray(game.save_dir.joinpath("SAVGAMA.PTY").read_bytes())
    staged[da.POD_TRAIN_BYTE] = 1
    game.save_dir.joinpath("SAVGAMA.PTY").write_bytes(bytes(staged))
    assert d.load()["menu_rows"] == {"view": 5, "save": 8, "begin": 9}
    assert game.train
    d.save("B")
    assert game.keys[-10:] == ["Down"] * 8 + ["Return", "b"] and game.mode == "party"
    game.row = 0
    d.begin()
    assert game.keys[-10:] == ["Down"] * 9 + ["Return"] and game.mode == "map"


def test_pools_of_darkness_begins_camps_views_and_saves(tmp_path):
    game, d = _pod_driver(tmp_path, question=False, pages=3)
    d.load()
    d.begin()
    assert game.mode == "map" and d.where == "map"
    assert game.keys[-8:] == ["Down"] * 7 + ["Return"]
    d.camp()
    game.keys.clear()
    sheet = d.sheet(4)
    assert game.keys == ["Down"] * 3 + ["v", "e"] and game.mode == "camp"
    assert sheet["line"] == 4 and game.line == 4
    assert sheet["name"] == screens.roster_name(
        _with_roster(_screen(b"", b""), "camp", 6, 1), "camp", 4)
    game.keys.clear()
    items = d.items(4)
    assert game.keys == ["v", "i", "n", "n", "n", "e", "e"]
    assert len(items["pages"]) == 3 and game.mode == "camp"
    game.keys.clear()
    d.sheet(2)
    assert game.keys.count("Down") == 4 and "End" not in game.keys
    saved = d.save("D")
    assert saved["file"] == "SAVGAMD.PTY" and (game.save_dir / "SAVGAMD.PTY").is_file()
    assert game.mode == "camp"


def test_exit_is_never_pressed_on_the_camp_bar_itself(tmp_path):
    """`Exit` on the camp bar breaks camp: leaving a sheet looks first."""
    game, d = _pod_driver(tmp_path, question=False)
    d.load()
    d.begin()
    d.camp()
    game.keys.clear()
    d.back_to_camp("x")
    assert game.keys == [] and game.mode == "camp"


def test_an_items_list_that_never_ends_stops_the_run(tmp_path):
    game, d = _pod_driver(tmp_path, question=False, pages=da.ITEMS_PAGES + 2)
    d.load()
    d.begin()
    d.camp()
    with pytest.raises(da.StepFailed, match="Next still turns"):
        d.items(1)


def test_the_party_menu_save_writes_the_pty(tmp_path):
    game, d = _pod_driver(tmp_path, question=False)
    d.load()
    got = d.save("B")
    assert got["file"] == "SAVGAMB.PTY" and game.mode == "party"
    assert game.keys[-8:] == ["Down"] * 6 + ["Return", "b"]


# -- choosing the character: the roster highlight -------------------------------


def _camped_pod(tmp_path, **kw):
    game, d = _pod_driver(tmp_path, question=False, **kw)
    d.load()
    d.begin()
    d.camp()
    game.keys.clear()
    return game, d


def test_the_roster_key_is_down_and_never_end():
    """`End` is what run `88eac43064-run1-cleric` of #650 pressed, and the
    selector at `GAME.OVR` 0x2680C answers only 0x48 and 0x50."""
    assert da.POD_ROSTER_NEXT == "Down"
    assert da.POD_PICK == "s"


@pytest.mark.parametrize("line", [1, 4, 6])
def test_a_camp_sheet_is_the_line_asked_for_even_with_the_fire_animating(tmp_path,
                                                                          line):
    """Run 1's defect: `End` moved nothing and the campfire changed the frame,
    so `sheet 4` and `sheet 6` both showed member 1."""
    game, d = _camped_pod(tmp_path, animated=True)
    got = d.sheet(line)
    assert game.keys == ["Down"] * (line - 1) + ["v", "e"]
    assert got["presses"] == line - 1 and game.line == line and game.mode == "camp"


def test_a_swallowed_down_is_pressed_again(tmp_path):
    game, d = _camped_pod(tmp_path, swallow_down=True)
    d.sheet(3)
    assert game.keys == ["Down"] * 3 + ["v", "e"] and game.line == 3


def test_a_down_that_moves_nothing_stops_before_view(tmp_path):
    game, d = _camped_pod(tmp_path, dead_down=True)
    with pytest.raises(da.StepFailed, match="did not move the roster highlight.*"
                                            "lost-select-4"):
        d.sheet(4)
    assert game.keys == ["Down", "Down"] and game.mode == "camp"


def test_a_sheet_of_another_character_stops_the_run(tmp_path):
    """The game viewing member 1 whatever the highlight says is the failure
    the name check exists for."""
    game, d = _camped_pod(tmp_path, same_sheet=True)
    d.sheet(1)
    with pytest.raises(da.StepFailed, match="not roster line 4's.*lost-sheet-4-name"):
        d.sheet(4)


def test_two_lines_showing_one_sheet_frame_stop_the_run(tmp_path, monkeypatch):
    """The second guard, with the name check made to pass."""
    game, d = _camped_pod(tmp_path, same_sheet=True)
    monkeypatch.setattr(da, "sheet_name", lambda screen: screens.roster_name(
        _with_roster(_screen(b"", b""), "camp", 6, 1), "camp", d.line))
    d.sheet(2)
    with pytest.raises(da.StepFailed, match="line 5's sheet is the same frame as "
                                            "line 2's"):
        d.sheet(5)


def test_a_line_past_the_party_is_blocked_before_a_key(tmp_path):
    game, d = _camped_pod(tmp_path, size=4)
    with pytest.raises(da.StepFailed, match="not in a party of 4"):
        d.sheet(5)
    assert game.keys == []


@pytest.mark.parametrize("line", [1, 4])
def test_view_opens_the_asked_character_from_the_party_menu_and_comes_back(
        tmp_path, line):
    game, d = _pod_driver(tmp_path, question=False, pages=2)
    d.load()
    game.keys.clear()
    got = d.view(line)
    assert game.keys == (["Down"] * 3 + ["Return"] + ["Down"] * (line - 1)
                         + ["s", "i", "n", "n", "e", "e"])
    assert game.into_pick == ["Down"] * (line - 1) + ["s"]
    assert game.mode == "party" and d.where == "party" and game.line == line
    assert got["line"] == line and len(got["pages"]) == 2
    assert got["name"] == screens.roster_name(
        _with_roster(_screen(b"", b""), "party", 6, 1), "party", line)


def test_view_counts_from_where_the_last_view_left_the_highlight(tmp_path):
    game, d = _pod_driver(tmp_path, question=False, pages=1)
    d.load()
    d.view(4)
    game.keys.clear()
    d.view(2)
    assert game.into_pick[-5:] == ["Down"] * 4 + ["s"] and game.line == 2


def test_view_then_the_party_menu_save(tmp_path):
    """The runner's order for a party that starts in a town."""
    game, d = _pod_driver(tmp_path, question=False, pages=1)
    d.load()
    d.view(1)
    saved = d.save("D")
    assert saved["file"] == "SAVGAMD.PTY" and game.mode == "party"
    assert game.into_pick == ["s"]


def test_view_of_another_character_stops_the_run(tmp_path):
    game, d = _pod_driver(tmp_path, question=False, same_sheet=True)
    d.load()
    with pytest.raises(da.StepFailed, match="not roster line 3's.*lost-view-3-name"):
        d.view(3)


def test_view_stops_when_pick_character_does_not_open(tmp_path):
    game, d = _pod_driver(tmp_path, question=False, pick_opens=False)
    d.load()
    with pytest.raises(da.StepFailed, match="left the party menu showing.*lost-pick-2"):
        d.view(2)
    assert game.keys[-4:] == ["Down"] * 3 + ["Return"] and game.into_pick == []


def test_exit_is_never_pressed_on_the_party_menu_itself(tmp_path):
    game, d = _pod_driver(tmp_path, question=False)
    d.load()
    game.keys.clear()
    d.back_to_party("x")
    assert game.keys == [] and game.mode == "party"


@pytest.mark.parametrize("steps", [
    ("load", "view 1", "save D", "read"),
    ("load", "view 4", "view 6", "begin", "camp", "sheet 4"),
    ("load", "save B", "view 2"),
])
def test_orders_with_view_allowed(steps):
    da.validate_steps(_steps(*steps), "darkness")


@pytest.mark.parametrize("title,steps,why", [
    ("darkness", ("load", "begin", "view 1"), "view needs the party menu"),
    ("darkness", ("load", "begin", "camp", "view 1"), "view needs the party menu"),
    ("darkness", ("view 1",), "needs load first"),
    # Pool's load puts the party on the map; its party menu is `add`'s.
    ("pool", ("load", "view 1"), "view needs the party menu"),
])
def test_orders_with_view_blocked(title, steps, why):
    with pytest.raises(ValueError, match=why):
        da.validate_steps(_steps(*steps), title)


def test_view_parses_and_a_bad_line_is_blocked():
    assert (da.parse_step("view 3").kind, da.parse_step("view 3").line) == ("view", 3)
    for bad in ("view", "view 0", "view 9", "view x"):
        with pytest.raises(ValueError):
            da.parse_step(bad)


def test_an_empty_line_has_the_blank_signature():
    empty = _screen(b"", b"")
    assert screens.roster_name(empty, "party", 1) == screens.BLANK_NAME
    assert screens.sheet_name(empty) == screens.BLANK_NAME


def test_the_name_signature_is_blind_to_the_highlight_colour():
    white = _with_roster(_screen(b"", b""), "camp", 6, 2)
    cyan = _with_roster(_screen(b"", b""), "camp", 6, 3)
    assert screens.roster_name(white, "camp", 2) == screens.roster_name(cyan, "camp", 2)
    assert screens.roster_line(white, "camp", 6) == 2
    assert screens.roster_line(cyan, "camp", 6) == 3
    assert len({screens.roster_name(white, "camp", n) for n in range(1, 7)}) == 6


def _capture(run: str, name: str, issue: str = "650",
             sub: tuple[str, ...] = (), size: str | None = None) -> dosbox.Screen:
    import shutil
    import subprocess

    from tools.registry.scratch import cache_dir
    shot = cache_dir("acceptance", issue, run, *sub, "shots", f"{name}.png")
    if not shot.exists() or shutil.which("convert") is None:
        pytest.skip(f"the captured screen {run}/{name} is not on this machine")
    resize = ["-sample", size] if size else []
    ppm = subprocess.run(["convert", str(shot), *resize, "-depth", "8", "ppm:-"],
                         check=True, capture_output=True).stdout
    return dosbox.Screen.from_ppm(ppm)


@pytest.mark.parametrize("run,roster,where,sheets", [
    ("88eac43064-run1-cleric", "004-loaded", "party",
     ("009-sheet-4", "011-sheet-4", "014-sheet-6")),
    ("88eac43064-run1-cleric", "007-camp", "camp",
     ("009-sheet-4", "011-sheet-4", "014-sheet-6")),
    ("840311866e-run0-control", "004-loaded", "party", ("012-sheet-1", "014-sheet-1")),
    ("840311866e-run0-control", "010-camp", "camp", ("012-sheet-1", "014-sheet-1")),
])
def test_the_captured_sheets_are_roster_line_one_and_no_other(run, roster, where,
                                                             sheets):
    """Every sheet those runs opened showed member 1, the highlighted line,
    whatever line the step asked for."""
    screen = _capture(run, roster)
    assert screens.roster_line(screen, where, 6) == 1
    names = [screens.roster_name(screen, where, n) for n in range(1, 7)]
    assert len(set(names)) == 6 and screens.BLANK_NAME not in names
    for sheet in sheets:
        assert [n for n in range(1, 7)
                if names[n - 1] == screens.sheet_name(_capture(run, sheet))] == [1]


@pytest.mark.parametrize("shot", ["008-line-4", "010-line-4", "013-line-6"])
def test_run_one_s_end_never_moved_the_highlight(shot):
    assert screens.roster_line(_capture("88eac43064-run1-cleric", shot), "camp", 6) == 1


# -- ITEMS: `halve` and `join` -----------------------------------------------


def _seven():
    """TURBO K's seven rows: 50 arrows first, as run `eafdbfabb0-m-itemskeys`."""
    return [50, 1, 1, 1, 1, 1, 1]


def _itemed(tmp_path, **kw):
    lists = {1: _seven(), 4: list(range(1, 22))}
    game, d = _camped_pod(tmp_path, item_lists=lists, **kw)
    return game, d


def test_the_item_steps_parse_with_a_line_and_a_row():
    for kind in ("halve", "join"):
        got = da.parse_step(f"{kind} 4 15")
        assert (got.kind, got.line, got.row) == (kind, 4, 15)
    assert da.parse_step("join 8 18").row == 18
    for bad in ("join 4 19", "join 4 21", "halve 1 0", "join 9 1", "join 4",
                "halve 1 1 1", "join 0 1"):
        with pytest.raises(ValueError):
            da.parse_step(bad)
    with pytest.raises(ValueError, match="need Next"):
        da.parse_step("join 4 19")


def test_the_item_steps_are_allowed_in_camp_after_a_walk_and_before_a_save():
    da.validate_steps(_steps("load", "begin", "camp", "halve 1 1", "save C",
                             "join 1 1", "join 4 15", "sheet 4", "save D", "read"),
                      "darkness")


def test_halve_then_join_reads_seven_eight_seven_rows_and_ends_in_camp(tmp_path):
    game, d = _itemed(tmp_path)
    halved = d.halve(1, 1)
    assert (halved["rows_before"], halved["rows_after"]) == (7, 8)
    assert halved["highlight_before"] == halved["highlight_after"] == 0
    assert game.item_lists[1] == [25, 25, 1, 1, 1, 1, 1, 1] and game.mode == "camp"
    assert game.keys.count("h") == 1 and "j" not in game.keys
    joined = d.join(1, 1)
    assert (joined["rows_before"], joined["rows_after"]) == (8, 7)
    assert game.item_lists[1] == _seven() and game.mode == "camp"
    assert game.keys.count("j") == 1


def test_join_on_row_fifteen_of_twenty_one_presses_down_fourteen_times(tmp_path):
    game, d = _itemed(tmp_path)
    game.keys.clear()
    got = d.join(4, 15)
    assert game.keys == ["Down"] * 3 + ["v", "i"] + ["Down"] * 14 + ["j", "e", "e"]
    assert (got["rows_before"], got["rows_after"]) == (18, 18)
    assert got["highlight_before"] == 14 and got["presses"] == 14
    assert len(game.item_lists[4]) == 21 and game.mode == "camp"


def test_pick_item_reads_the_highlight_after_every_press(tmp_path, monkeypatch):
    game, d = _itemed(tmp_path)
    d.open_sheet(1)
    game.key("i")
    reads = []
    real = screens.item_highlight
    monkeypatch.setattr(da, "item_highlight",
                        lambda sc: reads.append(1) or real(sc))
    game.keys.clear()
    d.pick_item(4, "x")
    assert game.keys == ["Down"] * 3 and game.item_row == 3
    assert len(reads) >= 1 + 3


def test_a_row_past_the_list_is_blocked_before_a_key(tmp_path):
    game, d = _itemed(tmp_path)
    d.open_sheet(1)
    game.key("i")
    game.keys.clear()
    with pytest.raises(da.StepFailed, match="row 8 is past the list's 7 rows"):
        d.pick_item(8, "x")
    assert game.keys == []


def test_a_dead_down_stops_join_at_the_highlight_before_any_j(tmp_path):
    game, d = _itemed(tmp_path, dead_item_down=True)
    with pytest.raises(da.StepFailed, match="did not move the ITEMS highlight off "
                                            "row 1"):
        d.join(1, 4)
    assert "j" not in game.keys and game.mode == "items"


def test_a_dead_halve_stops_the_run_on_the_items_screen_before_any_save(tmp_path):
    game, d = _itemed(tmp_path, dead_halve=True)
    with pytest.raises(da.StepFailed, match="halve left 7 rows.*from 7 rows"):
        d.halve(1, 1)
    assert game.mode == "items" and "e" not in game.keys[-1:]
    assert not list(game.save_dir.glob("SAVGAM[B-J].PTY"))


def test_halve_that_moves_the_highlight_stops_the_run(tmp_path, monkeypatch):
    game, d = _itemed(tmp_path)
    real = game._item_key

    def moving(k):
        real(k)
        if k == "h":
            game.item_row = 1
    monkeypatch.setattr(game, "_item_key", moving)
    with pytest.raises(da.StepFailed, match="halve left 8 rows with the highlight "
                                            "on 1, from 7 rows with it on 0"):
        d.halve(1, 1)


def test_halve_on_a_full_list_is_blocked_before_h(tmp_path):
    game, d = _itemed(tmp_path)
    game.keys.clear()
    with pytest.raises(da.StepFailed, match="already draws 18 rows.*not measured"):
        d.halve(4, 15)
    assert "h" not in game.keys and len(game.item_lists[4]) == 21
    assert game.mode == "items"


def test_pick_item_blocks_a_highlight_already_past_the_row(tmp_path):
    game, d = _itemed(tmp_path)
    d.open_sheet(1)
    game.key("i")
    game.item_row = 3
    game.keys.clear()
    with pytest.raises(da.StepFailed, match="highlight is on row 4, past row 2"):
        d.pick_item(2, "x")
    assert game.keys == []


def test_the_item_readers_read_only_an_items_list():
    """A sheet reads as a one-row list with its highlight on band 12."""
    list_frame = _screen(b"\x2b\x2c", b"")
    px = bytearray(list_frame.px)
    x, y, w, _ = screens.ITEM_LIST_RECT
    for band in (0, 1, 2, 4):            # band 3 is empty: the count stops there
        at = ((y + band * 8 + 3) * W + x + 4) * 3
        px[at:at + 3] = b"\xaa\xaa\xaa"
    for dx in range(120):
        at = ((y + 2 * 8 + 3) * W + x + 60 + dx) * 3
        px[at:at + 3] = b"\xff\xff\xff"
    for dx in range(22):                 # the mouse arrow: 22 near-white pixels
        at = ((y + 6 * 8 + 3) * W + x + 150 + dx) * 3
        px[at:at + 3] = b"\xff\xff\xff"
    frame = dosbox.Screen(W, H, bytes(px))
    assert screens.item_rows(frame) == 3 and screens.item_highlight(frame) == 2
    sheet = _screen(b"\x29\x2a", b"")
    sheet_px = bytearray(frame.px)
    for i, b in enumerate(sheet.rows(dosbox.BAR)):
        sheet_px[(dosbox.BAR[1] * W) * 3 + i] = b
    off = dosbox.Screen(W, H, bytes(sheet_px))
    assert screens.item_rows(off) is None and screens.item_highlight(off) is None
    only_arrow = bytearray(list_frame.px)
    for dx in range(22):
        at = ((y + 3) * W + x + 150 + dx) * 3
        only_arrow[at:at + 3] = b"\xff\xff\xff"
    assert screens.item_highlight(dosbox.Screen(W, H, bytes(only_arrow))) is None


@pytest.mark.parametrize("run,shot,rows,highlight", [
    ("eafdbfabb0-m-itemskeys", "010-items-1-1", 7, 0),
    ("eafdbfabb0-m-itemskeys", "012-press-i", 7, 0),
    ("eafdbfabb0-m-itemskeys", "013-press-h", 8, 0),
    ("eafdbfabb0-m-itemskeys", "014-press-j", 7, 0),
    ("eafdbfabb0-m-itemskeys", "015-press-Down", 7, 1),
    ("eafdbfabb0-m-itemskeys", "016-press-Down", 7, 2),
    ("eafdbfabb0-m-itemskeys", "017-press-Up", 7, 1),
    ("eafdbfabb0-m-itemskeys", "018-press-End", 7, 1),
    ("eafdbfabb0-m-itemskeys", "019-press-Home", 7, 1),
    ("79aa61820e-p2-savgama", "008-view-4-items-1", 18, 0),
    ("79aa61820e-p2-savgama", "009-view-4-items-2", 18, 0),
    ("79aa61820e-p2-savgama", "014-view-6-items-1", 16, 0),
    ("79aa61820e-p2-savgama", "021-items-4-1", 18, 0),
    ("79aa61820e-p2-savgama", "022-items-4-2", 18, 0),
])
def test_the_captured_items_lists_read_as_the_screen_shows_them(run, shot, rows,
                                                                highlight, monkeypatch):
    """14 captures of two runs of #650 (this player's own, not committed)."""
    monkeypatch.undo()
    screen = _capture(run, shot)
    assert (screens.item_rows(screen), screens.item_highlight(screen)) == (rows, highlight)


@pytest.mark.parametrize("shot", ["009-sheet-1", "011-press-v"])
def test_a_captured_sheet_is_not_read_as_an_items_list(shot, monkeypatch):
    monkeypatch.undo()
    screen = _capture("eafdbfabb0-m-itemskeys", shot)
    assert screens.item_rows(screen) is None and screens.item_highlight(screen) is None


def test_read_reports_the_current_movement_of_each_character(pod_source):
    out, _ = pod_source
    slot = da.read_slot(out / "source", "A")
    assert all(isinstance(c["movement_current"], int) for c in slot["characters"])
    assert "movement_current" in da.MEMBER_FIELDS


def test_compare_members_lists_movement_current_when_it_differs():
    base = {"name": "CLERIC", "thief": {}, "item_count": 21, "encumbrance": 1478,
            "movement": 12, "movement_current": 9, "book_0x130": 0, "items": []}
    before = {"characters": [base]}
    after = {"characters": [{**base, "movement_current": 6}]}
    assert da.compare_members(before, after)[0]["changed"] == ["movement_current"]
    assert da.compare_members(before, before)[0]["changed"] == []


def test_read_reports_the_record_byte_that_holds_spell_126(pod_source):
    """`book_0x130` is the byte itself, read off each resaved record, and a
    change to it is listed and printed.  INA's byte is set here after the
    conversion, as a DOS mage who learnt the spell has it."""
    import shutil
    out, _ = pod_source
    shutil.copytree(out / "source", out / "installed")
    record = out / "source" / "CHRDATA1.SAV"
    raw = bytearray(record.read_bytes())
    assert raw[da.POD_BOOK_126] == 0
    raw[da.POD_BOOK_126] = 1
    record.write_bytes(bytes(raw))
    result = da.read_step(out / "source", out, "A", ["A"], [], [])
    who = {c["name"]: c for c in result["slots"]["A"]["characters"]}
    assert (who["INA"]["book_0x130"], who["TRIPEL"]["book_0x130"]) == (1, 0)
    rows = {r["name"]: r for r in result["slots"]["A"]["members"]}
    assert rows["INA"]["changed"] == ["book_0x130"] and rows["TRIPEL"]["changed"] == []
    assert rows["INA"]["book_0x130"] == {"before": 0, "after": 1}
    assert any(line.startswith("  INA: ") and "byte 0x130 1; changed: book_0x130"
               in line for line in da.describe(result))


# -- MAGIC > MEMORIZE: the grimoire ---------------------------------------------


#: The synthetic bars: the Magic bar, and the grimoire's 21-cell head with
#: each page's words after it.
_MAGIC_BAR = b"\x03\x05\x06"
_HEAD = bytes((0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40)) * 3
_GRIMOIRE_BARS = {"first": _HEAD + b"\x11", "middle": _HEAD + b"\x11\x22",
                  "last": _HEAD + b"\x22", "only": _HEAD}
#: The `'S` after the name in the title, and what follows it.
_POSSESSIVE = b"\x09\x12"


def _row(n: int) -> bytes:
    """A synthetic list row: nineteen cells, different for every `n`."""
    return bytes((n % 7 + 1, n // 7 % 7 + 1 << 3, 0x05)) + b"\x11" * 16


_NINTH, _S124, _S125, _S126 = _row(90), _row(91), _row(92), _row(93)


def _book(rows: int, with_126: bool = True) -> list[bytes]:
    """`rows` rows of lower levels, then the ninth level's header and 124,
    125 and, when `with_126`, 126."""
    return [_row(k) for k in range(rows)] + [_NINTH, _S124, _S125] + (
        [_S126] if with_126 else [])


def _row_signature(row: bytes) -> str:
    frame = bytearray(W * H * 3)
    _draw_name(frame, *da.GRIMOIRE_ROWS_AT, row, b"\x55\xff\x55")
    return da.grimoire_rows(dosbox.Screen(W, H, bytes(frame)))[0]


@pytest.fixture
def grimoire_measured(monkeypatch):
    """The fake's bars and rows stand in for the measured values, which the
    capture tests below check against the #509 runs."""
    sig = screens.bar_signature
    monkeypatch.setattr(da, "POD_MAGIC_BAR", sig(_screen(_MAGIC_BAR, b"")))
    monkeypatch.setattr(da, "POD_GRIMOIRE_HEAD", sig(
        _screen(_GRIMOIRE_BARS["first"], b""), da.POD_GRIMOIRE_HEAD_CELLS))
    monkeypatch.setattr(da, "POD_GRIMOIRE_NEXT_BARS", frozenset(
        sig(_screen(_GRIMOIRE_BARS[k], b"")) for k in ("first", "middle")))
    import hashlib
    frame = bytearray(W * H * 3)
    _draw_name(frame, 0, 0, _POSSESSIVE, _WHITE)
    cells = da._cells(dosbox.Screen(W, H, bytes(frame)), 0, 0, 2)
    monkeypatch.setattr(da, "GRIMOIRE_POSSESSIVE",
                        hashlib.sha1("".join(cells).encode()).hexdigest()[:16])
    monkeypatch.setattr(da, "NINTH_LEVEL_ROW", _row_signature(_NINTH))
    spells = {_row_signature(r): i for r, i in ((_S124, 124), (_S125, 125),
                                                 (_S126, 126))}
    monkeypatch.setattr(da, "GRIMOIRE_SPELLS", spells)
    monkeypatch.setattr(da, "SPELL_126_ROW", _row_signature(_S126))


class FakeMagic(FakePod):
    """Camp's `MAGIC` and `MEMORIZE`, as the #509 runs showed them: `M` on
    the camp bar opens the Magic bar over the camp; `M` there opens the
    current member's grimoire, titled with the name and `'S`, eleven rows a
    page, the last page ending with the list's last row; `N` turns a page
    while the bar offers `NEXT` and does nothing on the last; `E` goes back
    a screen; `M` on the grimoire memorizes the highlighted spell."""

    def __init__(self, tmp, books, title_of=None, swallow_next=False,
                 dead_next=False, **kw):
        super().__init__(tmp, question=False, size=7, **kw)
        #: Each member's grimoire rows; a member without one opens nothing.
        self.books = books
        #: The grimoire titled with this member's name whoever is current.
        self.title_of = title_of
        self.swallow_next, self.dead_next = swallow_next, dead_next
        self.page = 0
        self.memorized: list[int] = []
        self.into_camp: list[str] = []

    def pages_of(self) -> int:
        return max(1, -(-len(self.books[self.line]) // da.GRIMOIRE_ROW_COUNT))

    def key(self, k, gap=0.0):
        m = self.mode
        if m == "camp" and k == da.POD_MAGIC:
            self.keys.append(k)
            self.mode = "magic"
        elif m == "camp" and k == da.LEAVE:
            self.keys.append(k)
            self.into_camp.append(k)
        elif m == "magic":
            self.keys.append(k)
            if k == da.POD_MEMORIZE and self.line in self.books:
                self.mode, self.page = "grimoire", 0
            elif k == da.LEAVE:
                self.mode = "camp"
        elif m == "grimoire":
            self.keys.append(k)
            if k == "n" and self.swallow_next:
                self.swallow_next = False
            elif k == "n" and not self.dead_next:
                self.page = min(self.page + 1, self.pages_of() - 1)
            elif k == da.LEAVE:
                self.mode = "magic"
            elif k == da.POD_MEMORIZE:
                self.memorized.append(self.line)
        else:
            super().key(k, gap)

    def capture(self):
        if self.mode == "magic":
            return _with_roster(_screen(_MAGIC_BAR, b""), "camp", self.size, self.line)
        if self.mode != "grimoire":
            return super().capture()
        book, pages = self.books[self.line], self.pages_of()
        kind = ("only" if pages == 1 else "first" if self.page == 0
                else "last" if self.page == pages - 1 else "middle")
        start = (max(0, len(book) - da.GRIMOIRE_ROW_COUNT) if kind == "last"
                 else self.page * da.GRIMOIRE_ROW_COUNT)
        px = bytearray(_screen(_GRIMOIRE_BARS[kind], b"").px)
        owner = self.title_of or self.line
        _draw_name(px, *da.GRIMOIRE_TITLE, _pod_name(owner)[:14] + _POSSESSIVE, _WHITE)
        x, y = da.GRIMOIRE_ROWS_AT
        for k, row in enumerate(book[start:start + da.GRIMOIRE_ROW_COUNT]):
            _draw_name(px, x, y + screens.CELL * k, row, b"\x55\xff\x55")
        return dosbox.Screen(W, H, bytes(px))


def _magic_driver(tmp_path, **kw):
    books = kw.pop("books", {5: _book(26), 1: _book(19, with_126=False)})
    game = FakeMagic(tmp_path, books, **kw)
    d = da.Driver(game, lambda **k: None, "A", "darkness", party_size=game.size)
    d.load()
    d.begin()
    d.camp()
    game.keys.clear()
    return game, d


def test_memorize_parses_and_a_bad_line_is_blocked():
    got = da.parse_step("memorize 5")
    assert (got.kind, got.line) == ("memorize", 5)
    for bad in ("memorize", "memorize 0", "memorize 9", "memorize x", "memorize 1 2"):
        with pytest.raises(ValueError):
            da.parse_step(bad)


def test_memorize_is_allowed_in_camp_before_and_after_a_save():
    da.validate_steps(_steps("load", "begin", "camp", "memorize 5", "memorize 1",
                             "save D", "memorize 5", "read"), "darkness")


@pytest.mark.parametrize("title,steps,why", [
    ("darkness", ("load", "begin", "memorize 5"), "memorize needs camp first"),
    ("darkness", ("load", "memorize 5"), "memorize needs camp first"),
    ("curse", ("load", "begin", "camp", "memorize 1"), "darkness only"),
    ("pool", ("load", "camp", "memorize 1"), "darkness only"),
])
def test_memorize_is_blocked_where_the_driver_cannot_reach_it(title, steps, why):
    with pytest.raises(ValueError, match=why):
        da.validate_steps(_steps(*steps), title)


def test_memorize_shoots_every_page_and_sees_spell_126(tmp_path, grimoire_measured):
    """HILDE's run in the fake: 30 rows are three pages, the last one ending
    with 126; the keys are the roster moves, `M` twice, `N` until the bar
    stops offering it, and `E` twice, and nothing is memorized."""
    game, d = _magic_driver(tmp_path)
    got = d.memorize(5)
    assert game.keys == ["Down"] * 4 + ["m", "m", "n", "n", "e", "e"]
    assert game.mode == "camp" and game.memorized == [] and game.into_camp == []
    assert len(got["pages"]) == 3 and got["lists_126"] is True
    assert got["ninth_level"] == [124, 125, 126]
    assert got["pages"][-1]["rows"][-1] == da.SPELL_126_ROW


def test_a_book_without_126_is_read_as_one(tmp_path, grimoire_measured):
    """The control: the same book with byte 0x130 clear, as the zeroed run of
    #509 drew it."""
    game, d = _magic_driver(tmp_path, books={5: _book(26, with_126=False)})
    got = d.memorize(5)
    assert got["lists_126"] is False and got["ninth_level"] == [124, 125]
    assert game.mode == "camp" and game.memorized == []


def test_a_one_page_grimoire_presses_no_next(tmp_path, grimoire_measured):
    game, d = _magic_driver(tmp_path, books={5: _book(3)})
    got = d.memorize(5)
    assert "n" not in game.keys and len(got["pages"]) == 1 and got["lists_126"]


def test_a_swallowed_next_is_pressed_again_and_no_page_is_missed(tmp_path,
                                                                 grimoire_measured):
    """A swallowed `N` read as the end would hide the ninth level."""
    game, d = _magic_driver(tmp_path, swallow_next=True)
    got = d.memorize(5)
    assert game.keys.count("n") == 3 and len(got["pages"]) == 3
    assert got["lists_126"] is True


def test_a_dead_next_on_a_bar_that_offers_it_stops_the_run(tmp_path,
                                                          grimoire_measured):
    game, d = _magic_driver(tmp_path, dead_next=True)
    with pytest.raises(da.StepFailed, match="NEXT changed nothing.*lost-memorize-5"):
        d.memorize(5)
    assert game.keys.count("n") == 2 and game.memorized == []


def test_a_grimoire_of_another_character_stops_the_run(tmp_path, grimoire_measured):
    game, d = _magic_driver(tmp_path, title_of=1)
    with pytest.raises(da.StepFailed, match="not roster line 5's name"):
        d.memorize(5)
    assert "n" not in game.keys and game.memorized == []


def test_memorize_is_pressed_once_when_no_grimoire_opens(tmp_path, grimoire_measured):
    """A second `M` on a grimoire that opened late would memorize a spell."""
    game, d = _magic_driver(tmp_path)
    with pytest.raises(da.StepFailed, match="did not open a grimoire"):
        d.memorize(3)
    assert game.keys == ["Down"] * 2 + ["m", "m"] and game.memorized == []


def test_memorize_twice_counts_from_where_the_first_left_the_highlight(
        tmp_path, grimoire_measured):
    game, d = _magic_driver(tmp_path)
    assert d.memorize(5)["lists_126"]
    game.keys.clear()
    got = d.memorize(1)
    assert game.keys[:3] == ["Down"] * 3 and got["lists_126"] is False
    assert game.mode == "camp"


#: The #509 runs, this player's own and not committed: SavGamB of `Pools of
#: Darkness3.adf` converted to DOS, HILDE on line 5 with byte 0x130 = 1, and
#: the same folder with that byte zeroed before the boot.
_HILDE = "0c78037a28-memorize-hilde"
_ZEROED = "0c78037a28-memorize-hilde-0x130-zeroed"


@pytest.mark.parametrize("run,shot,kind", [
    (_HILDE, "009-memorize-5-magic", "magic"),
    (_HILDE, "019-memorize-1-magic", "magic"),
    (_HILDE, "010-memorize-5-page-1", "next"),
    (_HILDE, "013-memorize-5-page-4", "next"),
    (_HILDE, "016-memorize-5-page-7", "last"),
    (_HILDE, "020-memorize-1-page-1", "next"),
    (_HILDE, "023-memorize-1-page-4", "last"),
    (_ZEROED, "016-memorize-5-page-7", "last"),
])
def test_the_captured_magic_and_grimoire_bars_read_as_measured(run, shot, kind):
    screen = _capture(run, shot, issue="509")
    assert (screens.bar_signature(screen) == da.POD_MAGIC_BAR) == (kind == "magic")
    assert da.on_grimoire(screen) == (kind != "magic")
    assert (screens.bar_signature(screen) in da.POD_GRIMOIRE_NEXT_BARS) == (
        kind == "next")


@pytest.mark.parametrize("run,camp,line,page,ninth", [
    (_HILDE, "008-memorize-5-line", 5, "016-memorize-5-page-7", [124, 125, 126]),
    (_HILDE, "018-memorize-1-line", 1, "023-memorize-1-page-4", []),
    (_ZEROED, "008-memorize-5-line", 5, "016-memorize-5-page-7", [124, 125]),
])
def test_the_captured_last_pages_read_as_the_screen_shows_them(run, camp, line, page,
                                                               ninth):
    """HILDE's ninth level is METEOR SWARM, POWER WORD KILL and MONSTER
    SUMMONING with the byte set and the first two without it; TROND AAGE L
    has no ninth level.  Each title is its own line's and no other's."""
    roster = _capture(run, camp, issue="509")
    last = _capture(run, page, issue="509")
    assert da.ninth_level(da.grimoire_rows(last)) == ninth
    assert (da.SPELL_126_ROW in da.grimoire_rows(last)) == (126 in ninth)
    assert [n for n in range(1, 8)
            if da.grimoire_is_for(last, da.roster_cells(roster, n))] == [line]


class FakeDungeon(FakePod):
    """Pools of Darkness' dungeon map: `Up` and `Down` at the map bar go to
    the roster selector, `m` enters a move mode whose bar is `EXIT` alone,
    where `Up` steps (unless `walls` say otherwise), `Right` turns and
    `Escape` leaves.  The status line is `x,y`, a blank cell, the facing.

    `ignore_m` makes `m` do nothing; `up_roster` sends move mode's `Up` to the
    roster; `blank_status` leaves the status line blank until a key other
    than `m` is pressed, as the game's move mode does; `never_status` keeps it
    blank whatever is pressed; `blank_after_up` blanks it
    once `Up` has been pressed in move mode; `no_highlight` draws the roster
    with no white line."""

    MOVE_BAR = b"\x41"

    def __init__(self, tmp, walls=0, ignore_m=False, up_roster=False,
                 blank_status=False, blank_after_up=False, no_highlight=False,
                 never_status=False, exit_key="Escape", **kw):
        super().__init__(tmp, **kw)
        self.mode = "dmap"
        self.exit_key = exit_key
        self.blank_after_up, self.no_highlight = blank_after_up, no_highlight
        self.x, self.facing, self.walls = 1, 1, walls
        self.ignore_m, self.up_roster = ignore_m, up_roster
        self.status_on = not blank_status
        self.never_status = never_status

    def key(self, k, gap=0.0):
        self.keys.append(k)
        if k != "m" and not self.never_status:
            self.status_on = True
        if self.mode == "dmap":
            if k == "m" and not self.ignore_m:
                self.mode = "move"
            elif k in ("Up", "Down"):
                self._roster(k)
        elif self.mode == "move":
            if k == "Up" and self.up_roster:
                self._roster(k)
            elif k == "Up" and self.walls:
                self.walls -= 1
            elif k == "Up":
                self.x += 1
            elif k == "Right":
                self.facing = (self.facing + 1) % 4
            elif k == self.exit_key:
                self.mode = "dmap"
            if k == "Up" and self.blank_after_up:
                self.status_on = False

    def capture(self):
        bar = self.MOVE_BAR if self.mode == "move" else FakePool.BARS["map"]
        frame = _with_roster(_screen(bar, b""), "camp", self.size,
                             0 if self.no_highlight else self.line)
        if not self.status_on:
            return frame
        px = bytearray(frame.px)
        x, y = screens.STATUS_TEXT_X, dosbox.STATUS[1]
        token = bytes(((1 << self.x % 8) | 0x80, 0x18, 0x21))
        _draw_name(px, x, y, token, _WHITE)
        _draw_name(px, x + screens.CELL * 4, y, bytes(((1 << self.facing) | 0x40,)), _WHITE)
        return dosbox.Screen(W, H, bytes(px))


def _dungeon_driver(tmp_path, title="darkness", **kw):
    game = FakeDungeon(tmp_path, **kw)
    d = da.Driver(game, lambda **k: None, "A", title, party_size=game.size)
    d.where = "map"
    d.world_ink = game.capture().ink(dosbox.BAR)
    d.world_sig = screens.bar_signature(game.capture())
    return game, d


@pytest.mark.parametrize("walls", [0, 2])
def test_pools_of_darkness_walks_one_square_turning_past_walls(tmp_path, walls):
    game, d = _dungeon_driver(tmp_path, walls=walls)
    map_ink = d.world_ink
    got = d.walk("1")
    assert game.keys == ["m"] + ["Up", "Right"] * walls + ["Up", "Escape"]
    assert got["turns"] == walls and game.x == 2 and game.line == 1
    assert got["square_before"] != got["square_after"]
    assert game.mode == "dmap" and d.game.world_bar == map_ink


def test_silver_blades_walks_in_move_mode_and_leaves_it_with_e(tmp_path):
    game, d = _dungeon_driver(tmp_path, title="ssb", exit_key="e")
    map_ink = d.world_ink
    got = d.walk("1")
    assert game.keys == ["m", "Up", "e"]
    assert got["square_before"] != got["square_after"]
    assert game.mode == "dmap" and d.game.world_bar == map_ink


def test_silver_blades_move_mode_is_not_left_with_escape(tmp_path, monkeypatch):
    """The game ignores `Escape` there (#672's first run), so a driver that
    pressed it would find the move bar still showing."""
    game, d = _dungeon_driver(tmp_path, title="ssb", exit_key="e")
    monkeypatch.setitem(da.MOVE_KEYS, "ssb", ("m", "Escape"))
    with pytest.raises(da.StepFailed, match="did not return to the map bar"):
        d.walk("1")
    assert game.keys[-1] == "Escape" and game.mode == "move"


def test_pools_of_darkness_stops_when_every_facing_is_a_wall(tmp_path):
    game, d = _dungeon_driver(tmp_path, walls=99)
    with pytest.raises(da.StepFailed, match="no facing"):
        d.walk("1")
    assert game.keys == ["m"] + ["Up", "Right"] * 3 + ["Up"]


def test_a_move_mode_with_no_status_line_takes_its_baseline_from_a_full_circle(tmp_path):
    """The game draws no status line on entering move mode; the first turn
    draws it, and four turns leave the party facing as it started."""
    game, d = _dungeon_driver(tmp_path, blank_status=True)
    got = d.walk("1")
    assert game.keys == ["m"] + ["Right"] * 4 + ["Up", "Escape"]
    assert game.facing == 1 and game.x == 2
    assert got["square_before"] is not None
    assert got["square_before"] != got["square_after"]
    assert game.mode == "dmap"


def test_a_status_line_that_stays_blank_after_a_turn_is_never_the_baseline(tmp_path):
    game, d = _dungeon_driver(tmp_path, blank_status=True, never_status=True)
    with pytest.raises(da.StepFailed, match="stayed blank after a turn"):
        d.walk("1")
    assert game.keys == ["m", "Right"]


def test_a_square_that_changes_on_the_circle_stops_the_walk(tmp_path):
    game, d = _dungeon_driver(tmp_path, blank_status=True)
    real = game.key

    def key(k, gap=0.0):
        real(k, gap)
        if k == "Right" and game.keys.count("Right") == 2:
            game.x += 1

    game.key = key
    with pytest.raises(da.StepFailed, match="square changed on a turn") as raised:
        d.walk("1")
    assert "lost-walk-circle-2.png" in str(raised.value)
    assert "Up" not in game.keys


def test_walls_on_every_side_after_a_blank_baseline_stop_the_walk_blocked(tmp_path):
    game, d = _dungeon_driver(tmp_path, blank_status=True, walls=99)
    with pytest.raises(da.StepFailed, match="no facing") as raised:
        d.walk("1")
    assert game.keys == ["m"] + ["Right"] * 4 + ["Up", "Right"] * 3 + ["Up"]
    assert "lost-walk-blocked.png" in str(raised.value)


def test_an_up_that_moves_the_roster_stops_the_walk(tmp_path):
    game, d = _dungeon_driver(tmp_path, up_roster=True)
    with pytest.raises(da.StepFailed, match="roster"):
        d.walk("1")
    assert game.keys == ["m", "Up"]


def test_a_blank_status_after_a_step_is_reported_as_that_and_turns_nothing(tmp_path):
    game, d = _dungeon_driver(tmp_path, blank_after_up=True)
    with pytest.raises(da.StepFailed, match="blank after the step"):
        d.walk("1")
    assert game.keys == ["m", "Up"]


def test_a_map_with_no_highlighted_roster_line_stops_before_any_step(tmp_path):
    game, d = _dungeon_driver(tmp_path, no_highlight=True)
    with pytest.raises(da.StepFailed, match="roster"):
        d.walk("1")
    assert game.keys == []


def test_a_failed_walk_still_puts_the_map_bar_back(tmp_path):
    game, d = _dungeon_driver(tmp_path, up_roster=True)
    map_ink = d.world_ink
    with pytest.raises(da.StepFailed, match="roster"):
        d.walk("1")
    assert d.game.world_bar == map_ink


def test_a_move_key_that_changes_nothing_stops_before_any_arrow(tmp_path):
    game, d = _dungeon_driver(tmp_path, ignore_m=True)
    with pytest.raises(da.StepFailed):
        d.walk("1")
    assert game.keys == ["m"]


def test_status_square_reads_the_coordinates_and_nothing_else():
    before = _capture("591c0bf9ce-run3-walk", "012-walk-before", issue="678")
    step = _capture("591c0bf9ce-run3-walk", "013-walk-step-1", issue="678")
    camp = _capture("591c0bf9ce-run3-walk", "014-camp", issue="678")
    other = _capture("840311866e-run0-control", "009-map")
    assert screens.status_square(before) is None
    assert screens.status_square(step) == screens.status_square(camp) is not None
    assert screens.status_square(other) not in (None, screens.status_square(step))
    assert screens.roster_line(before, "camp", 6) == 4
    assert screens.roster_line(step, "camp", 6) == 3


def test_describe_says_whether_the_party_moved():
    here = {"place": {"x": 1, "y": 2, "dungeon_map": 2, "facing": 1,
                      "in_dungeon": True}}
    slot = {**here, "clock_advanced": 0, "compare": [], "experience": [],
            "members": []}
    same = describe_result(here, {**slot, "place_changed": False})
    assert "  did not move" in same
    moved_to = {"place": {**here["place"], "x": 2}}
    got = describe_result(here, {**slot, **moved_to, "place_changed": True})
    assert "  moved from 1,2 to 2,2" in got


def describe_result(installed, slot):
    return da.describe({"installed": installed, "rested_minutes": 0,
                        "slots": {"D": slot}})


def test_the_run_boots_start_bat_from_the_title_own_directory(monkeypatch, pod_source):
    """`dospod.find_game`, not the `START.EXE` search, and `START.BAT` as
    the launcher; a container of the wrong title is blocked before a claim."""
    out, _ = pod_source
    tmp_path = out.parent
    log = _fake_run(monkeypatch, tmp_path, menu_error=TimeoutError("stopped here"))
    booted = {}

    def session(slot, game, exe="START.EXE"):
        booted.update(game=game, exe=exe)
        return _Session(tmp_path, log)

    monkeypatch.setattr(dosbox, "Session", session)
    monkeypatch.setattr(dospod, "find_game", lambda stem="DARKNESS": tmp_path / stem)
    args = _run_args(tmp_path, ["load"])
    args.title, args.save = "darkness", str(out / "source")
    da.run(args)
    assert booted == {"game": tmp_path / "DARKNESS", "exe": "START.BAT"}
    args.title = "pool"
    log.clear()
    with pytest.raises(ValueError, match="SAVGAMA.PTY, not the SAVGAMA.DAT pool"):
        da.run(args)
    assert "claim" not in log


# -- Pools of Darkness' journal question -------------------------------------------


def test_the_journal_question_after_begin_is_answered_and_the_steps_after_it_work(
        tmp_path, pod_journal):
    """Run 0's stop: `Begin` led to the question, and the driver took it for
    the map and typed `camp`'s and `sheet`'s keys into it.  Now the question
    gets `x` and `Return` and nothing else, and camp, a sheet, its items and
    the camp save run as they would without it."""
    game, d = _pod_driver(tmp_path, question=False, journal=True, pages=2)
    d.load()
    d.begin()
    assert game.mode == "map" and d.where == "map"
    assert game.into_journal == [dospod.JOURNAL_ANSWER, "Return"]
    assert [e["kind"] for e in d.events] == ["journal"]
    d.camp()
    assert game.mode == "camp"
    d.sheet(1)
    items = d.items(1)
    assert len(items["pages"]) == 2 and game.mode == "camp"
    assert d.save("D")["file"] == "SAVGAMD.PTY"
    assert game.into_journal == [dospod.JOURNAL_ANSWER, "Return"]


def test_the_question_is_answered_before_a_step_finds_it(tmp_path, pod_journal):
    """Wherever a step starts, the question showing is answered first, so the
    step's own keys land on the map rather than in the answer box."""
    game, d = _pod_driver(tmp_path, question=False)
    d.load()
    d.begin()
    game.mode = "journal"
    assert d.journal("camp")
    assert game.mode == "map"
    assert not d.journal("camp")
    d.camp()
    assert game.into_journal == [dospod.JOURNAL_ANSWER, "Return"]


def test_exit_is_never_typed_into_the_question(tmp_path, pod_journal):
    """Leaving a sheet presses `Exit` until the camp bar is back; on the
    question that key would be an answer, so it is answered and the run stops."""
    game, d = _pod_driver(tmp_path, question=False)
    d.load()
    d.begin()
    d.camp()
    game.mode = "journal"
    with pytest.raises(da.StepFailed, match="journal question interrupted"):
        d.back_to_camp("sheet-1-back")
    assert game.into_journal == [dospod.JOURNAL_ANSWER, "Return"]
    assert da.LEAVE not in game.into_journal


def test_other_titles_never_look_for_the_question(tmp_path, pod_journal):
    game = FakePool(tmp_path)
    d = da.Driver(game, lambda **k: None, "A", "curse")
    game.capture = lambda: pytest.fail("the question was looked for")
    assert not d.journal("camp")


def test_the_answer_is_no_key_the_driver_presses_on_the_map_camp_or_sheet():
    """Should a frame ever be misread as the question, `x` is none of the map
    bar's, the camp bar's or the sheet bar's commands."""
    driven = {da.ENCAMP, da.CAMP_SAVE, da.CAMP_REST, da.VIEW, da.SHEET_ITEMS,
              da.LEAVE, da.ITEMS_NEXT, *da.LATER_REST.__dict__.values()}
    assert dospod.JOURNAL_ANSWER not in driven


def test_the_run_looks_for_the_question_before_every_step(monkeypatch, tmp_path):
    _fake_run(monkeypatch, tmp_path, menu_error=TimeoutError("stopped"))
    da.run(_run_args(tmp_path, ["load"]))
    assert da.Driver.asked == ["load"]
    assert da.Driver.declined == ["load"]
    assert da.Driver.continued == ["load"]


def test_pools_at_load_from_where_is_pressed_once(tmp_path):
    """A `p` the screen drops is not pressed again: the run stops at
    `lost-load-from` rather than send a key the next screen might take."""
    game, d = _pod_driver(tmp_path, question=False, swallow_p=True)
    with pytest.raises(da.StepFailed, match="POOLS at LOAD FROM WHERE"):
        d.load()
    assert game.keys.count(da.POD_LOAD_FROM) == 1 and game.mode == "from"


# -- Pools of Darkness' YES NO bars after Begin -----------------------------------


@pytest.fixture
def pod_yes_no(monkeypatch):
    """The driver knows the fake's `YES NO` bar by its own signature, as it
    knows the real one by `POD_YES_NO_BAR`."""
    monkeypatch.setattr(da, "POD_YES_NO_BAR",
                        screens.bar_signature(_screen(FakePod.BARS["tour"], b"")))


def test_the_arrival_question_after_begin_is_declined_and_the_steps_after_it_work(
        tmp_path, pod_journal, pod_yes_no):
    """Run 0's stop at 75e0c741: `Begin` led through the journal question to a
    `YES NO` bar, the driver took the bar for the map, and `camp`'s `E` changed
    nothing.  Now the bar gets `N` and nothing else, and camp, a sheet, its
    items and the camp save run behind it."""
    game, d = _pod_driver(tmp_path, question=False, journal=True, tours=1, pages=2)
    d.load()
    d.begin()
    assert game.mode == "map" and d.where == "map"
    assert game.into_tour == [da.POD_DECLINE]
    assert [e["kind"] for e in d.events] == ["journal", "yes_no"]
    assert d.events[1]["answered"] == "N" and d.events[1]["step"] == "begin"
    d.camp()
    d.sheet(1)
    assert len(d.items(1)["pages"]) == 2 and game.mode == "camp"
    assert d.save("D")["file"] == "SAVGAMD.PTY"
    assert game.into_tour == [da.POD_DECLINE]
    assert "y" not in game.keys and "Y" not in game.keys


def test_the_decline_key_is_the_first_letter_of_no():
    """The menu routine keys a word by its first capital (`GAME.OVR` 0x3A220)
    and puts the key pressed through `UpCase` (0x3A90F)."""
    assert da.POD_DECLINE.upper() == "NO"[0] != "YES"[0]


def test_without_a_measured_map_bar_begin_stops_at_the_screen_it_reached(
        tmp_path, monkeypatch, pod_yes_no):
    """With no measured bar, whatever follows the answer, the map included,
    stops `begin` with a shot; `camp` never runs."""
    monkeypatch.setattr(da, "POD_MAP_BARS", {})
    game, d = _pod_driver(tmp_path, question=False, tours=1)
    d.load()
    with pytest.raises(da.StepFailed, match="no Pools of Darkness map bar.*"
                       "lost-begin-screen"):
        d.begin()
    assert game.mode == "map" and d.where == "party"
    assert game.keys[-1] == da.POD_DECLINE and da.ENCAMP not in game.keys


def test_the_yes_no_bar_is_never_taken_for_the_map(tmp_path, pod_yes_no):
    """A bar `N` does not change is pressed twice and stops the run, rather
    than being recorded as the map and given `camp`'s key."""
    game, d = _pod_driver(tmp_path, question=False, tours=1, dead_n=True)
    d.load()
    with pytest.raises(da.StepFailed, match="NO changed nothing"):
        d.begin()
    assert game.into_tour == [da.POD_DECLINE] * 2 and game.mode == "tour"


def test_a_screen_after_the_answer_that_is_not_the_map_stops_begin(tmp_path,
                                                                  pod_yes_no):
    """A story screen after the answer is shot, and nothing is typed into it."""
    game, d = _pod_driver(tmp_path, question=False, tours=1, after_tour="story")
    d.load()
    with pytest.raises(da.StepFailed, match="not a measured map bar"):
        d.begin()
    assert game.mode == "story" and game.keys[-1] == da.POD_DECLINE


@pytest.mark.parametrize("tours", [2, da.POD_YES_NO_ROUNDS])
def test_bars_one_after_another_are_each_declined_and_shot(tmp_path, pod_yes_no,
                                                           tours):
    game, d = _pod_driver(tmp_path, question=False, tours=tours)
    d.load()
    d.begin()
    assert game.mode == "map"
    assert game.into_tour == [da.POD_DECLINE] * tours
    assert [e["kind"] for e in d.events] == ["yes_no"] * tours
    assert len({e["shot"] for e in d.events}) == tours


def test_bars_that_keep_coming_stop_the_run(tmp_path, pod_yes_no):
    game, d = _pod_driver(tmp_path, question=False, tours=da.POD_YES_NO_ROUNDS + 1)
    d.load()
    with pytest.raises(da.StepFailed, match=f"after {da.POD_YES_NO_ROUNDS} were"):
        d.begin()
    assert game.into_tour == [da.POD_DECLINE] * da.POD_YES_NO_ROUNDS


def test_a_yes_no_bar_found_before_a_step_is_declined_first(tmp_path, pod_yes_no):
    game, d = _pod_driver(tmp_path, question=False)
    d.load()
    d.begin()
    game.mode, game.tours = "tour", 1
    assert d.yes_no("camp") == 1
    assert game.mode == "map"
    assert d.yes_no("camp") == 0
    d.camp()
    assert game.mode == "camp" and game.into_tour == [da.POD_DECLINE]


def test_other_titles_never_look_for_a_yes_no_bar(tmp_path, pod_yes_no):
    game = FakePool(tmp_path)
    d = da.Driver(game, lambda **k: None, "A", "curse")
    game.capture = lambda: pytest.fail("the bar was looked for")
    assert d.yes_no("camp") == 0



# -- Pools of Darkness' story dialogs that say to press a button or Enter -------


def test_a_late_first_n_is_not_followed_by_a_blind_second(tmp_path, pod_yes_no):
    """The screen changed just after the wait ran out: the second `N` would
    land on the map as a command key."""
    game, d = _pod_driver(tmp_path, question=False, tours=1, late_n=True)
    d.load()
    d.begin()
    assert game.into_tour == ["n"] and game.into_map == [] and game.mode == "map"


def test_a_late_n_onto_another_yes_no_bar_is_declined_by_the_loop(tmp_path,
                                                                 pod_yes_no):
    """The second dialog is shot and declined once, visibly, and counted."""
    game, d = _pod_driver(tmp_path, question=False, tours=2, late_n=True)
    d.load()
    d.begin()
    assert game.into_tour == ["n"] * 2 and game.mode == "map"
    assert [e["kind"] for e in d.events] == ["yes_no"] * 2
    assert len({e["shot"] for e in d.events}) == 2


@pytest.fixture
def pod_continue(monkeypatch, pod_yes_no):
    """The driver knows the fake's continue bar by its own signature."""
    monkeypatch.setattr(da, "POD_CONTINUE_BAR",
                        screens.bar_signature(_screen(FakePod.BARS["cont"], b"")))


def test_the_continue_bar_is_not_another_known_bar():
    assert da.POD_CONTINUE_BAR != da.POD_YES_NO_BAR
    assert da.POD_CONTINUE == "Return" and da.POD_CONTINUE_ROUNDS == 5


@pytest.mark.parametrize("continues", [1, da.POD_CONTINUE_ROUNDS])
def test_continue_screens_after_the_answer_get_return_and_nothing_else(
        tmp_path, pod_continue, continues):
    game, d = _pod_driver(tmp_path, question=False, tours=1, continues=continues)
    d.load()
    d.begin()
    assert game.mode == "map" and d.where == "map"
    assert game.into_cont == ["Return"] * continues
    assert [e["kind"] for e in d.events] == ["yes_no"] + ["press_continue"] * continues
    assert len({e["shot"] for e in d.events}) == continues + 1
    assert "y" not in game.keys and "Y" not in game.keys


def test_a_sixth_continue_screen_stops_the_run(tmp_path, pod_continue):
    game, d = _pod_driver(tmp_path, question=False,
                          continues=da.POD_CONTINUE_ROUNDS + 1)
    d.load()
    with pytest.raises(da.StepFailed, match="after 5 were answered.*lost-continue-begin"):
        d.begin()
    assert game.into_cont == ["Return"] * da.POD_CONTINUE_ROUNDS


def test_a_return_that_changes_nothing_stops_the_run(tmp_path, pod_continue):
    game, d = _pod_driver(tmp_path, question=False, continues=1, dead_return=True)
    d.load()
    with pytest.raises(da.StepFailed, match="Return changed nothing"):
        d.begin()
    assert game.into_cont == ["Return"] * 2


def test_with_no_measured_map_the_screen_after_the_last_continue_stops_begin(
        tmp_path, monkeypatch, pod_continue):
    monkeypatch.setattr(da, "POD_MAP_BARS", {})
    game, d = _pod_driver(tmp_path, question=False, tours=1, continues=2)
    d.load()
    with pytest.raises(da.StepFailed, match="lost-begin-screen"):
        d.begin()
    assert game.keys[-1] == "Return" and da.ENCAMP not in game.keys


def test_begin_gives_up_after_too_many_interstitials(tmp_path, monkeypatch,
                                                     pod_continue):
    """The bound is on screens: with 2 allowed, a third is not answered."""
    monkeypatch.setattr(da, "POD_INTERSTITIALS", 2)
    game, d = _pod_driver(tmp_path, question=False, continues=4)
    d.load()
    with pytest.raises(da.StepFailed, match="lost-begin-interstitials"):
        d.begin()
    assert game.into_cont == ["Return"] * 2


def test_the_bound_counts_screens_across_the_helpers_not_passes(
        tmp_path, monkeypatch, pod_continue):
    """A pass can answer a bar, then continues; 4 screens in one pass must not
    get past a bound of 3."""
    monkeypatch.setattr(da, "POD_INTERSTITIALS", 3)
    game, d = _pod_driver(tmp_path, question=False, tours=2, continues=3)
    d.load()
    with pytest.raises(da.StepFailed, match="lost-begin-interstitials"):
        d.begin()
    assert game.into_tour == [da.POD_DECLINE] * 2 and game.into_cont == ["Return"]


def test_a_full_allowance_is_still_enough(tmp_path, monkeypatch, pod_continue):
    monkeypatch.setattr(da, "POD_INTERSTITIALS", 4)
    game, d = _pod_driver(tmp_path, question=False, tours=2, continues=2)
    d.load()
    d.begin()
    assert game.mode == "map" and len(d.events) == 4


def test_a_late_first_return_is_not_followed_by_a_blind_second(tmp_path,
                                                               pod_continue):
    """The screen changed just after the wait ran out: the second `Return`
    would dismiss the next screen unseen."""
    game, d = _pod_driver(tmp_path, question=False, continues=1, late_return=True)
    d.load()
    d.begin()
    assert game.into_cont == ["Return"] and game.mode == "map"
    assert game.into_map == []


def test_a_late_return_onto_another_continue_screen_is_answered_by_the_loop(
        tmp_path, pod_continue):
    game, d = _pod_driver(tmp_path, question=False, continues=2, late_return=True)
    d.load()
    d.begin()
    assert game.into_cont == ["Return"] * 2 and game.mode == "map"
    assert [e["kind"] for e in d.events] == ["press_continue"] * 2


def test_a_continue_screen_found_before_a_step_is_answered_first(tmp_path,
                                                                 pod_continue):
    game, d = _pod_driver(tmp_path, question=False)
    d.load()
    d.begin()
    game.mode, game.continues = "cont", 1
    assert d.press_continue("camp") == 1 and game.mode == "map"
    assert d.press_continue("camp") == 0


def test_other_titles_never_look_for_a_continue_screen(tmp_path, pod_continue):
    game = FakePool(tmp_path)
    d = da.Driver(game, lambda **k: None, "A", "curse")
    game.capture = lambda: pytest.fail("the bar was looked for")
    assert d.press_continue("camp") == 0


@pytest.fixture
def two_map_bars(monkeypatch, pod_yes_no):
    """The fakes' dungeon map and overland bars stand in for the two
    measured ones."""
    monkeypatch.setattr(da, "POD_MAP_BARS", {
        "dungeon": screens.bar_signature(_screen(FakePool.BARS["map"], b"")),
        "overland": screens.bar_signature(_screen(FakePod.BARS["overland"], b""))})


@pytest.mark.parametrize("kind, after", [("dungeon", "map"), ("overland", "overland")])
def test_begin_takes_each_measured_map_bar_and_says_which(tmp_path, two_map_bars,
                                                          kind, after):
    notes = []
    game = FakePod(tmp_path, question=False, tours=1, after_tour=after)
    d = da.Driver(game, lambda **k: notes.append(k), "A", "darkness",
                  party_size=game.size)
    d.load()
    got = d.begin()
    assert got["map_kind"] == kind and d.where == "map"
    assert [n["map"] for n in notes if n.get("event") == "map_bar"] == [kind]


def test_camp_works_from_the_overland_bar(tmp_path, two_map_bars):
    game, d = _pod_driver(tmp_path, question=False, tours=1, after_tour="overland")
    d.load()
    d.begin()
    d.camp()
    assert game.mode == "camp" and d.where == "camp"


def test_an_unmeasured_bar_still_stops_begin(tmp_path, two_map_bars):
    game, d = _pod_driver(tmp_path, question=False, tours=1, after_tour="story")
    d.load()
    with pytest.raises(da.StepFailed, match="not a measured map bar"):
        d.begin()
    assert da.ENCAMP not in game.keys


def test_the_measured_pod_map_bars_are_sixteen_hex_digits(monkeypatch):
    monkeypatch.undo()
    assert set(da.POD_MAP_BARS) == {"dungeon", "overland"}
    assert len(set(da.POD_MAP_BARS.values())) == 2
    for bar in da.POD_MAP_BARS.values():
        assert len(bar) == 16
        int(bar, 16)


def test_the_measured_pod_map_bar_matches_the_captured_map(monkeypatch):
    """The value was read off a live run's map screen; that capture is in the
    player's cache, not the repository, so this skips without it."""
    import shutil
    import subprocess

    from tools.registry.scratch import cache_dir
    shot = cache_dir("acceptance", "650", "e38a1bb514-run0-control", "shots",
                     "009-lost-begin-screen.png")
    if not shot.exists() or shutil.which("convert") is None:
        pytest.skip("the captured Pools of Darkness map is not on this machine")
    monkeypatch.undo()
    ppm = subprocess.run(["convert", str(shot), "-depth", "8", "ppm:-"],
                         check=True, capture_output=True).stdout
    assert screens.bar_signature(dosbox.Screen.from_ppm(ppm)) == da.POD_MAP_BARS["dungeon"]


def test_the_measured_overland_bar_matches_the_captured_screen(monkeypatch):
    """Read off the Amiga cleric run's screen; that capture is in the player's
    cache, so this skips without it."""
    import shutil
    import subprocess

    from tools.registry.scratch import cache_dir
    shot = cache_dir("acceptance", "650", "840311866e-run1-cleric", "shots",
                     "006-lost-begin-screen.png")
    if not shot.exists() or shutil.which("convert") is None:
        pytest.skip("the captured overland screen is not on this machine")
    monkeypatch.undo()
    ppm = subprocess.run(["convert", str(shot), "-depth", "8", "ppm:-"],
                         check=True, capture_output=True).stdout
    assert screens.bar_signature(dosbox.Screen.from_ppm(ppm)) == da.POD_MAP_BARS["overland"]


def test_pool_map_bars_distinguish_the_measured_screens(monkeypatch):
    """The overland and town captures each match their own `POOL_MAP_BARS`
    entry and nothing else, and the #620 continue prompt matches neither --
    it is a story screen, not a map, and this is why the guard stays a
    measured set rather than widening to any bar."""
    monkeypatch.undo()
    overland = _capture("ca4bbff4fa-dos-pool-rebuild", "003-party_before_view",
                        issue="634", sub=("boot",))
    town = _capture("ca4bbff4fa-dos-pool-sheet-live", "002-loaded", issue="666")
    continue_prompt = _capture("02a339fe5c-trainer-flag-b", "003-lost-sheet-1-map",
                               issue="620")

    assert screens.bar_signature(overland) == da.POOL_MAP_BARS["overland"]
    assert screens.roster_line(overland, "camp", 6) == 1
    assert screens.bar_signature(town) == da.POOL_MAP_BARS["town"]
    assert screens.bar_signature(continue_prompt) not in da.POOL_MAP_BARS.values()


# -- the town services screen ---------------------------------------------------


@pytest.fixture
def pod_town(monkeypatch, pod_yes_no):
    """The driver knows the fake's town bar by its own signature."""
    monkeypatch.setattr(da, "POD_ELMINSTER_BAR",
                        screens.bar_signature(_screen(FakePod.BARS["town"], b"")))


def test_the_measured_town_bar_is_sixteen_hex_digits_and_not_a_map():
    assert len(da.POD_ELMINSTER_BAR) == 16 and int(da.POD_ELMINSTER_BAR, 16) >= 0
    assert da.POD_ELMINSTER_BAR not in da.POD_MAP_BARS.values()
    assert not hasattr(da, "POD_TOWN_LEAVE")


def test_a_town_bar_stops_begin_with_a_shot_and_presses_nothing(tmp_path,
                                                               pod_town):
    game, d = _pod_driver(tmp_path, question=False, tours=1, after_tour="town")
    d.load()
    with pytest.raises(da.StepFailed, match="Elminster's menu.*lost-begin-screen"):
        d.begin()
    assert game.into_town == [] and d.where == "party"


def test_a_town_screen_after_the_journal_question_is_a_town_stop(tmp_path,
                                                                pod_town,
                                                                pod_journal):
    game, d = _pod_driver(tmp_path, question=False, journal=True, tours=1,
                          after_tour="town")
    d.load()
    with pytest.raises(da.StepFailed, match="Elminster's menu.*lost-begin-screen"):
        d.begin()
    assert [e["kind"] for e in d.events] == ["journal", "yes_no"]
    assert game.into_town == []


def test_an_unknown_bar_is_not_taken_for_the_town(tmp_path, pod_yes_no):
    """Without a measured town bar the fake's town screen stops `begin` with
    nothing pressed on it."""
    game, d = _pod_driver(tmp_path, question=False, tours=1, after_tour="town")
    d.load()
    with pytest.raises(da.StepFailed, match="lost-begin-screen"):
        d.begin()
    assert game.into_town == []


# -- vault: Elminster's STORAGE in Limbo ------------------------------------------

_BAR_INK = b"\x55\xff\x55"


def _vault_record(n: int) -> bytes:
    """A 63-byte record whose cached name (bytes 0x00-0x29) is `Item n `."""
    name = f"Item {n} ".encode()
    return (bytes((len(name),)) + name).ljust(63, b"\0")


def _vault_file(items: int, coins=(0, 0, 0)) -> bytes:
    """A DOS `VAULT<L>.DAT`: three u32le coins and `items` 63-byte records."""
    import struct
    return struct.pack("<III", *coins) + b"".join(_vault_record(n + 1)
                                                  for n in range(items))


class FakeVault(FakePod):
    """Pools of Darkness from `Begin` on, for a party saved in area 18:
    Elminster's menu (`STORAGE` unless `storage` is False), whose `S` opens
    the vault and `R` the camp loop; the vault's bar as the menu builder at
    `GAME.OVR` 0x330D draws it, `TAKE` only with something stored; `T` asks
    `TAKE: MONEY ITEMS EXIT` when coins and items are both stored, and opens
    the item list at once when only items are; the list draws 22 names a
    window, `NEXT` moving it 22 on but never past the last full window, as
    the game's did; `E` backs out of each, and leaving
    the vault writes `TMPVAULT.DAT`, which a camp `SAVE` renames to the
    slot's `VAULT<L>.DAT`.  Every bar is drawn as text in the stand-in font."""

    def __init__(self, tmp, vault: bytes | None, *, storage=True, rest_opens=True,
                 misread=None, **kw):
        super().__init__(tmp, question=False, **kw)
        if vault is not None:
            (self.save_dir / "VAULTA.DAT").write_bytes(vault)
        self.storage, self.rest_opens = storage, rest_opens
        self.vault_page, self.from_elminster = 0, False
        #: An item number the list draws under another name.
        self.misread = misread

    def top(self) -> int:
        items, _ = self.stored()
        return max(0, min(self.vault_page * da.VAULT_WINDOW, items - da.VAULT_WINDOW))

    def arrival(self) -> str:
        return "town"

    def stored(self) -> tuple[int, int]:
        path = self.save_dir / "VAULTA.DAT"
        if not path.is_file():
            return 0, 0
        data = path.read_bytes()
        return (len(data) - 12) // 63, sum(data[:12])

    def key(self, k, gap=0.0):
        m = self.mode
        items, coins = self.stored()
        if m == "town":
            self.keys.append(k)
            self.into_town.append(k)
            if k == "s" and self.storage:
                self.mode = "vault"
            elif k == "r" and self.rest_opens:
                self.mode, self.from_elminster = "camp", True
        elif m == "vault":
            self.keys.append(k)
            if k == "t" and items:
                self.mode = "take" if coins else "vlist"
                self.vault_page = 0
            elif k == "e":
                (self.save_dir / "TMPVAULT.DAT").write_bytes(
                    (self.save_dir / "VAULTA.DAT").read_bytes()
                    if (self.save_dir / "VAULTA.DAT").is_file() else bytes(12))
                self.mode = "town"
        elif m == "take":
            self.keys.append(k)
            if k == "i":
                self.mode, self.vault_page = "vlist", 0
            elif k == "e":
                self.mode = "vault"
        elif m == "vlist":
            self.keys.append(k)
            if k == "n" and self.top() + da.VAULT_WINDOW < items:
                self.vault_page += 1
            elif k == "e":
                self.mode = "take" if coins else "vault"
        elif m == "save" and k.upper() in "ABCDEFGHIJ":
            tmp = self.save_dir / "TMPVAULT.DAT"
            if tmp.is_file():
                tmp.rename(self.save_dir / f"VAULT{k.upper()}.DAT")
            super().key(k, gap)
        else:
            super().key(k, gap)

    def bar_text(self) -> str:
        items, coins = self.stored()
        if self.mode == "town":
            return ("HEAL TRAIN STORAGE REST MOVE ON" if self.storage
                    else "HEAL TRAIN REST MOVE ON")
        if self.mode == "vault":
            return "VIEW " + ("TAKE " if items else "") + "POOL MONEY ITEMS EXIT"
        if self.mode == "take":
            return "TAKE: MONEY ITEMS EXIT"
        if self.mode == "vlist":
            more = self.top() + da.VAULT_WINDOW < items
            back = " PREV" if self.vault_page else ""
            return "ITEMS : TAKE" + (" NEXT" if more else back) + " EXIT"
        return "SAVE VIEW MAGIC ALTER EXIT"

    def capture(self):
        if self.mode not in ("town", "vault", "take", "vlist") and not (
                self.mode == "camp" and self.from_elminster):
            return super().capture()
        px = bytearray(W * H * 3)
        _draw(px, _FONT_BLOCK, da.BAR_ROW, 0, self.bar_text(), _BAR_INK)
        if self.mode == "vlist":
            items, _ = self.stored()
            first = self.top()
            for i, n in enumerate(range(first, min(first + da.VAULT_WINDOW, items))):
                name = "ITEM X" if n + 1 == self.misread else f"ITEM {n + 1}"
                _draw(px, _FONT_BLOCK, 1 + i, 1, name, _NAME_INK)
        return dosbox.Screen(W, H, bytes(px))


@pytest.fixture
def elminster(monkeypatch):
    """The driver knows the fake's Elminster menu by its own signature."""
    def sig(text):
        px = bytearray(W * H * 3)
        _draw(px, _FONT_BLOCK, da.BAR_ROW, 0, text, _BAR_INK)
        return screens.bar_signature(dosbox.Screen(W, H, bytes(px)))
    monkeypatch.setattr(da, "POD_ELMINSTER_BAR", sig("HEAL TRAIN STORAGE REST MOVE ON"))
    return sig


def _vault_driver(tmp_path, vault, **kw):
    game = FakeVault(tmp_path, vault, **kw)
    d = da.Driver(game, lambda **k: None, "A", "darkness", party_size=game.size)
    d._font = _FONT
    d.elminster_ok = True
    d.load()
    d.begin()
    game.keys.clear()
    return game, d


def test_vault_is_a_darkness_step_straight_after_begin():
    steps = [da.parse_step(t) for t in ("load", "begin", "vault", "camp", "save D", "read")]
    da.validate_steps(steps, "darkness")
    assert steps[2].kind == "vault"
    shot = [da.parse_step(t) for t in ("load", "begin", "shot x", "vault")]
    da.validate_steps(shot, "darkness")
    for bad, title, match in (
            (("load", "vault"), "darkness", "follows begin"),
            (("load", "begin", "camp", "vault"), "darkness", "follows begin"),
            (("load", "begin", "vault"), "curse", "darkness only"),
            (("load", "begin", "vault", "walk 1"), "darkness", "needs the map"),
            (("load", "begin", "vault", "vault"), "darkness", "follows begin")):
        with pytest.raises(ValueError, match=match):
            da.validate_steps([da.parse_step(t) for t in bad], title)


def test_begin_takes_elminsters_menu_as_its_end_only_for_a_vault_run(tmp_path, elminster):
    game = FakeVault(tmp_path, _vault_file(3))
    d = da.Driver(game, lambda **k: None, "A", "darkness", party_size=game.size)
    d.load()
    with pytest.raises(da.StepFailed, match="Elminster's menu.*lost-begin-screen"):
        d.begin()
    assert game.into_town == [] and d.where == "party"
    (tmp_path / "second").mkdir()
    game, d = _vault_driver(tmp_path / "second", _vault_file(3))
    assert d.where == "elminster" and game.mode == "town" and game.into_town == []


def test_vault_lists_every_page_and_leaves_through_each_exit(tmp_path, elminster):
    """SavGamH's vault: 40 items and coins, so `TAKE` asks first and the list
    runs to three pages."""
    game, d = _vault_driver(tmp_path, _vault_file(40, (1750, 495, 82)))
    got = d.vault()
    assert game.keys == ["s", "t", "i", "n", "e", "e", "e"]
    assert game.mode == "town" and d.where == "elminster"
    assert [len(p["items"]) for p in got["pages"]] == [22, 22]
    assert got["pages"][0]["items"][0] == "ITEM 1" and got["pages"][1]["items"][0] == "ITEM 19"
    assert got["window"] == {"tops": [0, 18], "covered": True}
    assert got["listed"] == 40 and got["matches"] and got["take_prompt"]
    assert got["expected"] == {"file": "VAULTA.DAT", "items": 40, "platinum": 1750,
                               "gems": 495, "jewelry": 82}
    assert got["tmpvault"]["items"] == 40 and got["tmpvault"]["platinum"] == 1750
    assert da.vault_verdict([{"step": "vault", **got}], None) is None


@pytest.mark.parametrize("items, keys", [(22, ["s", "t", "i", "e", "e", "e"]),
                                         (23, ["s", "t", "i", "n", "e", "e", "e"]),
                                         (66, ["s", "t", "i", "n", "n", "e", "e", "e"])])
def test_the_list_window_is_checked_at_each_size(tmp_path, elminster, items, keys):
    game, d = _vault_driver(tmp_path, _vault_file(items, (1, 0, 0)))
    got = d.vault()
    assert game.keys == keys and got["matches"] and got["listed"] == items


def test_a_list_that_reads_another_name_does_not_match(tmp_path, elminster):
    game, d = _vault_driver(tmp_path, _vault_file(40, (1750, 495, 82)), misread=30)
    got = d.vault()
    assert not got["matches"] and got["window"]["page"] == 2
    assert "page 2 of the vault's list" in da.vault_verdict([{"step": "vault", **got}],
                                                            None)


def test_items_with_no_coins_open_the_list_at_once(tmp_path, elminster):
    game, d = _vault_driver(tmp_path, _vault_file(5))
    got = d.vault()
    assert game.keys == ["s", "t", "e", "e"]
    assert got["listed"] == 5 and got["matches"] and not got["take_prompt"]


@pytest.mark.parametrize("vault", [bytes(12), None])
def test_an_empty_vault_offers_no_take_and_lists_nothing(tmp_path, elminster, vault):
    game, d = _vault_driver(tmp_path, vault)
    got = d.vault()
    assert game.keys == ["s", "e"] and "TAKE" not in got["vault_bar"]
    assert got["listed"] == 0 and got["matches"] and got["pages"] == []
    assert got["tmpvault"]["items"] == 0 and got["tmpvault"]["size"] == 12


def test_a_menu_without_storage_stops_with_the_stage_var_and_presses_nothing(
        tmp_path, elminster, monkeypatch):
    game = FakeVault(tmp_path, _vault_file(3), storage=False)
    monkeypatch.setattr(da, "POD_ELMINSTER_BAR", elminster("HEAL TRAIN REST MOVE ON"))
    d = da.Driver(game, lambda **k: None, "A", "darkness", party_size=game.size)
    d._font, d.elminster_ok = _FONT, True
    d.load()
    d.begin()
    game.keys.clear()
    with pytest.raises(da.StepFailed, match="--stage-var A2=0.*lost-vault-storage"):
        d.vault()
    assert game.keys == []


def test_camp_from_elminster_presses_rest_and_the_save_stores_the_vault(
        tmp_path, elminster):
    game, d = _vault_driver(tmp_path, _vault_file(40, (1750, 495, 82)))
    d.vault()
    got = d.camp()
    assert game.keys[-1] == "r" and got["from"] == "elminster"
    assert got["words"] == ["SAVE", "VIEW", "MAGIC", "ALTER", "EXIT"]
    saved = d.save("D")
    assert saved["back_in_camp"]
    assert (game.save_dir / "VAULTD.DAT").read_bytes() == _vault_file(40, (1750, 495, 82))


def test_rest_that_opens_no_camp_stops(tmp_path, elminster):
    game, d = _vault_driver(tmp_path, _vault_file(3), rest_opens=False)
    with pytest.raises(da.StepFailed, match="changed nothing.*lost-camp-elminster"):
        d.camp()


def test_vault_needs_elminsters_menu(tmp_path):
    game, d = _pod_driver(tmp_path, question=False)
    d.load()
    with pytest.raises(da.StepFailed, match="Elminster's menu"):
        d.vault()


def _vault_result(listed=40, items=40, tmp=40, coins=(1750, 495, 82)):
    want = {"file": "VAULTA.DAT", "items": items, "platinum": coins[0],
            "gems": coins[1], "jewelry": coins[2]}
    # `listed` is how many names the screen covered, or None.
    t = None if tmp is None else {"file": "TMPVAULT.DAT", "items": tmp,
                                  "platinum": coins[0], "gems": coins[1],
                                  "jewelry": coins[2]}
    return [{"step": "vault", "listed": listed, "expected": want,
             "matches": listed == items, "tmpvault": t}]


def _read_vault(items=40, coins=(1750, 495, 82)):
    return {"saved": ["D"], "slots": {"D": {"vault": {
        "platinum": coins[0], "gems": coins[1], "jewelry": coins[2],
        "items": [{}] * items}}}}


def test_the_window_check_reads_a_pointer_cell_as_any_character():
    names = [f"ITEM {n}" for n in range(1, 41)]
    first, last = names[:22], names[18:]
    assert da.vault_window_check([first, last], names) == {"tops": [0, 18],
                                                           "covered": True}
    blurred = ["IT?M 1"] + first[1:]
    assert da.vault_window_check([blurred, last], names)["covered"]
    assert not da.vault_window_check([first], names)["covered"]
    assert da.vault_window_check([first, names[22:]], names)["page"] == 2
    assert da.vault_window_check([], []) == {"tops": [], "covered": True}
    assert da.record_name(_vault_record(7)) == "ITEM 7"


def test_the_vault_verdict():
    assert da.vault_verdict([{"step": "load"}], None) is None
    assert da.vault_verdict(_vault_result(), _read_vault()) is None
    assert "listed 39 items" in da.vault_verdict(_vault_result(listed=39), None)
    assert "no TMPVAULT.DAT" in da.vault_verdict(_vault_result(tmp=None), None)
    assert "does not hold" in da.vault_verdict(_vault_result(tmp=12), None)
    assert "VAULTD.DAT holds" in da.vault_verdict(_vault_result(), _read_vault(items=39))
    assert "VAULTD.DAT holds" in da.vault_verdict(
        _vault_result(), _read_vault(coins=(0, 495, 82)))
    lost = {"saved": ["D"], "slots": {"D": {}}}
    assert "no VAULTD.DAT" in da.vault_verdict(_vault_result(), lost)


def _pod_save(tmp_path, area=18, storage=0, dungeon=1) -> pathlib.Path:
    from goldbox import dos_savegame
    saves = tmp_path / "saves"
    saves.mkdir(exist_ok=True)
    data = bytearray(1364)
    dos_savegame.put_pod_var(data, da.POD_AREA_VAR, area)
    dos_savegame.put_pod_var(data, da.POD_STORAGE_VAR, storage)
    dos_savegame.put_pod_var(data, dos_savegame.POD_IN_DUNGEON, dungeon)
    dos_savegame.put_position(data, 7, 0, 3)
    (saves / "SAVGAMA.PTY").write_bytes(bytes(data))
    (saves / "CHRDATA1.SAV").write_bytes(b"x")
    return saves


def _vault_args(tmp_path, saves, **extra):
    args = _run_args(tmp_path, ["load", "begin", "vault", "camp", "save D", "read"])
    args.title, args.save = "darkness", str(saves)
    for k, v in extra.items():
        setattr(args, k, v)
    return args


def test_a_vault_run_needs_area_18_and_storage_before_a_slot_is_claimed(
        monkeypatch, tmp_path):
    log = _fake_run(monkeypatch, tmp_path)
    da.check_staging(_vault_args(tmp_path, _pod_save(tmp_path)),
                     tmp_path / "saves", "A")
    saves = _pod_save(tmp_path, area=17)
    with pytest.raises(ValueError, match="area 18.*names area 17"):
        da.check_staging(_vault_args(tmp_path, saves), saves, "A")
    with pytest.raises(ValueError, match="area 18"):
        da.run(_vault_args(tmp_path, saves))
    saves = _pod_save(tmp_path, storage=1)
    with pytest.raises(ValueError, match="--stage-var A2=0"):
        da.check_staging(_vault_args(tmp_path, saves), saves, "A")
    da.check_staging(_vault_args(tmp_path, saves, stage_var=["A2=0"]), saves, "A")
    assert "claim" not in log


def test_a_tmpvault_in_the_specimen_or_the_play_directory_never_reaches_the_run(tmp_path):
    # `vault_verdict` takes TMPVAULT.DAT to be the game's write; install empties
    # the play directory and copies only the slot's own files, so none can be there.
    saves = _pod_save(tmp_path)
    (saves / "TMPVAULT.DAT").write_bytes(b"from the specimen")
    play = tmp_path / "play"
    play.mkdir()
    (play / "TMPVAULT.DAT").write_bytes(b"from an earlier run")
    took = staging.install(saves, play, "A")
    assert "TMPVAULT.DAT" not in {p.name.upper() for p in play.iterdir()}
    assert da.tmpvault(play) is None
    assert "TMPVAULT.DAT" not in took["files"]


def test_a_vault_step_with_no_slot_to_load_does_not_name_a_slot_none(tmp_path):
    saves = _pod_save(tmp_path)
    args = _vault_args(tmp_path, saves)
    with pytest.raises(ValueError) as e:
        da.check_vault(args, saves, None)
    assert "None" not in str(e.value)


def test_stage_var_writes_one_byte_of_a_pools_of_darkness_save(tmp_path):
    saves = _pod_save(tmp_path, storage=1)
    before = (saves / "SAVGAMA.PTY").read_bytes()
    args = _vault_args(tmp_path, saves, stage_var=["A2=0"], stage_record=[])
    da.check_staging(args, saves, "A")
    done = da.stage(saves, "A", args)
    after = (saves / "SAVGAMA.PTY").read_bytes()
    assert done == [{"stage": "var", "file": "SAVGAMA.PTY", "address": "0xa2",
                     "offset": "0xa1", "before": "01", "after": "00"}]
    assert [i for i in range(1364) if before[i] != after[i]] == [0xA1]


@pytest.mark.parametrize("bad, error", [("A2=256", ValueError), ("0=1", Exception),
                                        ("401=1", Exception)])
def test_a_pools_of_darkness_stage_var_outside_one_byte_or_the_array_is_blocked(
        tmp_path, bad, error):
    saves = _pod_save(tmp_path)
    args = _vault_args(tmp_path, saves, stage_var=[bad])
    args.steps = ["load"]
    with pytest.raises(error):
        da.check_staging(args, saves, "A")


def test_stage_place_moves_a_pools_of_darkness_dungeon_party(tmp_path):
    saves = _pod_save(tmp_path)
    before = (saves / "SAVGAMA.PTY").read_bytes()
    args = _vault_args(tmp_path, saves, stage_var=[], stage_record=[],
                       stage_place="5,9,1")
    args.steps = ["load"]
    da.check_staging(args, saves, "A")
    done = da.stage(saves, "A", args)
    after = (saves / "SAVGAMA.PTY").read_bytes()
    assert done == [{"stage": "place", "file": "SAVGAMA.PTY", "before": [7, 0, 3],
                     "after": [5, 9, 1]}]
    assert [i for i in range(1364) if before[i] != after[i]] == [1024, 1025, 1026]


def test_stage_place_blocks_a_pools_of_darkness_wilderness_save(tmp_path):
    saves = _pod_save(tmp_path, dungeon=0)
    args = _vault_args(tmp_path, saves, stage_place="5,9,1")
    args.steps = ["load"]
    with pytest.raises(ValueError, match="wilderness"):
        da.check_staging(args, saves, "A")
    with pytest.raises(ValueError, match="wilderness"):
        da.stage_pod_place(saves, "A", 5, 9, 1)


def test_read_reports_a_pools_of_darkness_staged_byte(tmp_path, monkeypatch):
    save = _pod_save(tmp_path)
    (save / "SAVGAMD.PTY").write_bytes((save / "SAVGAMA.PTY").read_bytes())
    monkeypatch.setattr(da, "read_slot", lambda *a: {"clock_minutes": 0, "nodes": [],
                                                    "characters": []})
    got = da.read_step(save, tmp_path / "out", "A", ["D"], [], [], [(0xA2, 0)],
                       "darkness")
    assert got["staged_vars"] == {"A2": {"slot": "D", "staged": 0, "saved": 0,
                                         "held": True}}


# -- turn N: the control of a walk ---------------------------------------------


def test_a_pool_turn_presses_right_n_times_and_leaves_the_square_alone(tmp_path):
    game, d = _pool_walker(tmp_path)
    got = d.turn(4)
    assert d.game.keys == ["Right"] * 4
    assert got["square_before"] == got["square_after"] == "0bcb75efaa7a593d"
    assert got["turns"] == 4 and len(got["screens"]) == 5
    assert d.where == "map" and game.x == 0


def test_a_pool_turn_that_changes_the_square_fails_as_lost_walk_turn(tmp_path):
    game, d = _pool_walker(tmp_path)
    real = d.game.turn_right

    def turn_right():
        real()
        if len(d.game.keys) == 3:
            game.x += 1
        return True

    d.game.turn_right = turn_right
    with pytest.raises(da.StepFailed, match="square changed on a turn") as raised:
        d.turn(4)
    assert "lost-walk-turn-3" in str(raised.value)
    assert d.game.keys == ["Right"] * 3


def test_a_pool_turn_with_a_blank_status_line_has_no_baseline(tmp_path):
    game, d = _pool_walker(tmp_path, status_on=False)
    with pytest.raises(da.StepFailed, match="blank"):
        d.turn(4)
    assert d.game.keys == []


def test_pools_of_darkness_turns_in_move_mode_and_leaves_it(tmp_path):
    game, d = _dungeon_driver(tmp_path)
    map_ink = d.world_ink
    got = d.turn(4)
    assert game.keys == ["m"] + ["Right"] * 4 + ["Escape"]
    assert game.x == 1 and game.mode == "dmap" and game.line == 1
    assert got["square_before"] == got["square_after"] is not None
    assert d.where == "map" and d.game.world_bar == map_ink


def test_a_blank_move_mode_takes_its_baseline_from_the_first_turn(tmp_path):
    game, d = _dungeon_driver(tmp_path, blank_status=True)
    got = d.turn(4)
    assert game.keys == ["m"] + ["Right"] * 4 + ["Escape"]
    assert got["square_before"] is not None and got["square_after"] == got["square_before"]


def test_one_turn_from_a_blank_move_mode_compares_nothing_and_stops(tmp_path):
    game, d = _dungeon_driver(tmp_path, blank_status=True)
    with pytest.raises(da.StepFailed, match="nothing to compare"):
        d.turn(1)
    assert d.game.world_bar == d.world_ink


def test_a_darkness_turn_that_changes_the_square_fails_as_lost_walk_turn(tmp_path):
    game, d = _dungeon_driver(tmp_path)
    real = game.key

    def key(k, gap=0.0):
        real(k, gap)
        if k == "Right" and game.keys.count("Right") == 2:
            game.x += 1

    game.key = key
    with pytest.raises(da.StepFailed, match="square changed on a turn") as raised:
        d.turn(4)
    assert "lost-walk-turn-2" in str(raised.value)
    assert game.keys == ["m", "Right", "Right"]
    assert d.game.world_bar == d.world_ink


def test_a_darkness_turn_whose_key_moves_the_roster_stops(tmp_path):
    game, d = _dungeon_driver(tmp_path)
    real = game.key

    def key(k, gap=0.0):
        real(k, gap)
        if k == "Right":
            game._roster("Down")

    game.key = key
    with pytest.raises(da.StepFailed, match="roster"):
        d.turn(4)


def test_a_curse_turn_control_keeps_the_square(tmp_path):
    game, d = _pool_walker(tmp_path, title="curse")
    got = d.turn(2)
    assert d.game.keys == ["Right", "Right"]
    assert got["square_before"] == got["square_after"] is not None
    da.validate_steps(_steps("load", "begin", "turn 2"), "curse")


def test_a_silver_blades_turn_control_uses_m_and_e(tmp_path):
    game, d = _dungeon_driver(tmp_path, title="ssb", exit_key="e")
    got = d.turn(4)
    assert game.keys == ["m"] + ["Right"] * 4 + ["e"]
    assert game.x == 1 and game.mode == "dmap"
    assert got["square_before"] == got["square_after"] is not None
    da.validate_steps(_steps("load", "begin", "turn 4"), "ssb")


@pytest.mark.parametrize("text", ["turn", "turn 0", "turn 5", "turn x", "turn 1 2"])
def test_a_turn_takes_one_to_four(text):
    with pytest.raises(ValueError):
        da.parse_step(text)


def test_orders_a_turn_control_allows():
    da.validate_steps(_steps("load", "turn 4", "camp", "save D", "read"), "pool")
    da.validate_steps(_steps("load", "begin", "turn 4", "camp", "save D", "read"),
                      "darkness")
    with pytest.raises(ValueError, match="turn needs the map"):
        da.validate_steps(_steps("load", "turn 4"), "darkness")


def test_the_measured_titles_share_one_status_column_and_status_square_takes_it(tmp_path):
    assert {t: da.status_column(t) for t in ("pool", "curse", "ssb", "darkness")} == {
        "pool": 136, "curse": 136, "ssb": 136, "darkness": 136}
    game = PoolMap(tmp_path)
    frame = game.capture()
    assert screens.status_square(frame, 136) == screens.status_square(frame) == "0bcb75efaa7a593d"
    assert screens.status_square(frame, 144) != screens.status_square(frame, 136)


_TURN_STEPS = ["load", "turn 4", "camp", "save D", "read"]


def _turn_run(monkeypatch, tmp_path, read):
    _walk_run(monkeypatch, tmp_path, read)
    monkeypatch.setattr(da.Driver, "turn", lambda self, n: {"route": "turn"},
                        raising=False)


def test_a_turn_control_whose_saved_place_is_unchanged_passes(monkeypatch, tmp_path):
    _turn_run(monkeypatch, tmp_path, _read(changed=False))
    assert da.run(_run_args(tmp_path, _TURN_STEPS)) == 0
    assert _summary(tmp_path)["completed"] is True


def test_a_turn_control_whose_saved_place_moved_fails(monkeypatch, tmp_path):
    _turn_run(monkeypatch, tmp_path, _read(changed=True))
    assert da.run(_run_args(tmp_path, _TURN_STEPS)) == 1
    assert "the turn moved the party" in _summary(tmp_path)["lost"]


def test_a_turn_control_with_no_read_or_no_computed_place_fails(monkeypatch, tmp_path):
    _turn_run(monkeypatch, tmp_path, None)
    assert da.run(_run_args(tmp_path, _TURN_STEPS[:-1])) == 1
    assert "no read step" in _summary(tmp_path)["lost"]


def test_a_walk_with_turns_that_did_not_move_still_fails_the_run(monkeypatch, tmp_path):
    _turn_run(monkeypatch, tmp_path, _read(changed=False))
    steps = ["load", "turn 4", "walk MI", "camp", "save D", "read"]
    assert da.run(_run_args(tmp_path, steps)) == 1
    assert "did not move the party" in _summary(tmp_path)["lost"]


def test_read_reports_did_not_move_after_turns_only(monkeypatch, tmp_path, capsys):
    (tmp_path / "save").mkdir()
    slot = {"slot": "D", "clock": [0] * 6, "clock_minutes": 0, "characters": [],
            "place": {"x": 1, "y": 2, "area": 0, "facing": 1, "set_out": True}}
    monkeypatch.setattr(da, "read_slot", lambda folder, letter: dict(slot))
    got = da.read_step(tmp_path / "save", tmp_path / "out", "A", ["D"],
                       _steps("turn 4"), [])
    assert got["slots"]["D"]["place_changed"] is False
    assert "did not move" in capsys.readouterr().out


def test_a_run_whose_expectation_the_read_refutes_is_lost(monkeypatch, tmp_path):
    read = _read(changed=True)
    read["verdicts"] = [{"expect": {"name": "WISHFTR", "id": 32, "minutes": 0,
                                    "data": None},
                         "verdict": "refutes", "why": "WISHFTR holds no node with id 32"}]
    _walk_run(monkeypatch, tmp_path, read)
    assert da.run(_run_args(tmp_path, _WALK_STEPS)) == 1
    assert "WISHFTR:32:0 refuted" in _summary(tmp_path)["lost"]


def test_every_refuted_expectation_is_named_with_its_data():
    def refuted(name, data):
        return {"expect": {"name": name, "id": 32, "minutes": 0, "data": data},
                "verdict": "refutes", "why": "no node"}
    got = da.expect_verdict({"verdicts": [refuted("A", None), refuted("B", 7)]})
    assert "A:32:0 refuted" in got and "B:32:0:7 refuted" in got


# -- the signal, the interrupt and the wrapper's margin --------------------------


def test_terminated_is_not_an_exception_so_no_handler_swallows_it():
    assert not issubclass(da.Terminated, Exception)


def test_a_sigterm_inside_the_failure_capture_is_not_swallowed(tmp_path):
    game = FakePool(tmp_path)
    d = da.Driver(game, lambda **k: None, "A")

    def broken(name, allow_blank=False):
        raise da.Terminated("signal 15")

    game.shot = broken
    with pytest.raises(da.Terminated):
        d.fail("walk", "the map bar did not return")
    assert d.capture_error is None


@posix_signals
def test_a_sigterm_right_after_the_lease_still_releases_the_slot(monkeypatch, tmp_path):
    import signal
    log = _fake_run(monkeypatch, tmp_path)
    before = signal.getsignal(signal.SIGTERM)

    def claim(note=""):
        log.append("claim")
        # Thread-directed: a process-directed kill can land on another thread,
        # which does not block SIGTERM, and then races the deferral under xdist.
        signal.pthread_kill(threading.get_ident(), signal.SIGTERM)
        return _Slot(log)

    monkeypatch.setattr(dosbox, "claim", claim)
    with pytest.raises(da.Terminated):
        da.run(_run_args(tmp_path, ["load"]))
    assert log == ["claim", "release"]
    assert signal.getsignal(signal.SIGTERM) == before
    assert signal.pthread_sigmask(signal.SIG_BLOCK, set()) & {signal.SIGTERM} == set()


@posix_signals
def test_deferred_sigterm_restores_the_callers_mask():
    import signal
    signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
    try:
        with da.deferred_sigterm():
            pass
        assert signal.SIGTERM in signal.pthread_sigmask(signal.SIG_BLOCK, set())
    finally:
        signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGTERM})


def test_the_deadline_help_names_the_kill_escalation(capsys):
    with pytest.raises(SystemExit):
        da.main(["--help"])
    assert "timeout -k" in " ".join(capsys.readouterr().out.split())


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(3)])
def test_an_interrupt_or_exit_is_recorded_as_lost_and_still_raised(
        monkeypatch, tmp_path, error):
    _walk_run(monkeypatch, tmp_path, _read())

    def load(self):
        raise error

    monkeypatch.setattr(da.Driver, "load", load)
    with pytest.raises(type(error)):
        da.run(_run_args(tmp_path, _WALK_STEPS))
    got = _summary(tmp_path)
    assert got["completed"] is False and type(error).__name__ in got["lost"]


def test_a_cleanup_window_the_wrappers_margin_cannot_hold_is_blocked():
    da.Deadline(_Clock(), 900.0)
    with pytest.raises(ValueError, match="wrapper"):
        da.Deadline(_Clock(), 900.0, cleanup=da.WRAPPER_MARGIN)


def _passes_deadline(call):
    """Whether an `ast.Call` hands a deadline on: a `deadline` keyword, a
    `deadline` name or `.deadline` attribute argument, or `**kwargs`."""
    import ast
    args = [*call.args, *(k.value for k in call.keywords)]
    return any(k.arg in (None, "deadline") for k in call.keywords) or any(
        (isinstance(a, ast.Name) and a.id == "deadline")
        or (isinstance(a, ast.Attribute) and a.attr == "deadline") for a in args)


def _unrouted_waits(source, roots=None, bare=()):
    """The numeric `timeout=` literals and `timeout` defaults in `source`'s
    functions that are not routed through a deadline.

    `roots` names the functions to start from (all when `None`); calls to
    other functions of the same source, as `self.<name>(` or `<name>(`, are
    followed.  A function is routed when it takes a `deadline` parameter and
    its body uses it beyond comparing it with `None`; the `timeout=` literals
    in its body are then bounded by it, and its own `timeout` default counts
    only when a caller reachable from the roots (or named in `bare`) passes no
    deadline, because that call runs on the default.  Numeric literals only,
    not computed timeouts; calls through other receivers (`self.s.settle`, a
    callable passed in, `getattr`) or into other modules are not followed.
    """
    import ast
    functions = {}
    for fn in ast.walk(ast.parse(source)):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.setdefault(fn.name, []).append(fn)
    todo = list(functions if roots is None else roots)
    seen, bare, values = set(), set(bare), []
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        for fn in functions.get(name, []):
            for n in ast.walk(fn):
                if isinstance(n, ast.Call):
                    f = n.func
                    callee = f.attr if isinstance(f, ast.Attribute) and isinstance(
                        f.value, ast.Name) and f.value.id == "self" else (
                        f.id if isinstance(f, ast.Name) else None)
                    if callee in functions:
                        todo.append(callee)
                        if not _passes_deadline(n):
                            bare.add(callee)
    for name in seen:
        for fn in functions.get(name, []):
            args = fn.args
            params = args.posonlyargs + args.args + args.kwonlyargs
            compared = {id(n) for c in ast.walk(fn) if isinstance(c, ast.Compare)
                        for n in ast.walk(c)}
            routed = any(a.arg == "deadline" for a in params) and any(
                isinstance(n, ast.Name) and n.id == "deadline"
                and isinstance(n.ctx, ast.Load) and id(n) not in compared
                for n in ast.walk(fn))
            defaults = dict(zip(reversed(args.posonlyargs + args.args),
                                reversed(args.defaults)))
            defaults.update({a: d for a, d in zip(args.kwonlyargs, args.kw_defaults)})
            if not routed or name in bare:
                values += [d.value for a, d in defaults.items()
                           if a.arg == "timeout" and isinstance(d, ast.Constant)]
            if not routed:
                values += [kw.value.value for n in ast.walk(fn) if isinstance(n, ast.Call)
                           for kw in n.keywords if kw.arg == "timeout"
                           and isinstance(kw.value, ast.Constant)]
    return [float(v) for v in values]


def _borrowed_roots(module):
    import re
    prefix = "dospod" if module is da.dospod else "ssb"
    return set(re.findall(rf"\b{prefix}\.(\w+)\(", pathlib.Path(da.__file__).read_text()))


def _borrowed_bare(module):
    """The `ssb.<name>(` / `dospod.<name>(` calls in the driver that pass no
    deadline, by function name."""
    import ast
    prefix = "dospod" if module is da.dospod else "ssb"
    names = set()
    for n in ast.walk(ast.parse(pathlib.Path(da.__file__).read_text())):
        f = n.func if isinstance(n, ast.Call) else None
        if not isinstance(f, ast.Attribute):
            continue
        r = f.value
        if (isinstance(r, ast.Name) and r.id == prefix) or (
                isinstance(r, ast.Attribute) and r.attr == prefix
                and isinstance(r.value, ast.Name) and r.value.id == "self"):
            if not _passes_deadline(n):
                names.add(f.attr)
    return names


def test_no_numeric_timeout_literal_in_the_driver_outruns_the_margin():
    """Every unrouted `timeout=` literal and `timeout` default fits the
    margin, in the driver and in what it calls as `ssb.<name>(` or
    `dospod.<name>(`, following calls between a module's own functions; a
    function is routed only if it takes a `deadline` and uses it."""
    longest = max(
        [*_unrouted_waits(pathlib.Path(da.__file__).read_text())]
        + [w for m in (route_silver_blades, da.dospod)
           for w in _unrouted_waits(pathlib.Path(m.__file__).read_text(),
                                    _borrowed_roots(m), _borrowed_bare(m))])
    assert longest <= da.LONGEST_UNBOUNDED_WAIT
    assert da.CLEANUP_SECONDS + da.LONGEST_UNBOUNDED_WAIT <= da.WRAPPER_MARGIN


def test_the_guard_sees_an_unused_deadline_parameter_and_a_helper_behind_a_helper():
    source = pathlib.Path(route_silver_blades.__file__).read_text()
    roots = _borrowed_roots(route_silver_blades)
    bare = _borrowed_bare(route_silver_blades)
    assert max(_unrouted_waits(source, roots, bare),
               default=0) <= da.LONGEST_UNBOUNDED_WAIT
    behind = source.replace(
        "    def intro(self", "    def slow(self):\n"
        "        self.s.settle(quiet=0.6, timeout=120.0)\n\n    def intro(self").replace(
        "            kind = self.bar(screen)\n            if kind == \"map\"",
        "            kind = self.bar(screen)\n            self.slow()\n"
        "            if kind == \"map\"")
    assert 120.0 in _unrouted_waits(behind, roots)
    unread = source.replace(
        "        screen = self.s.settle(quiet=0.6, timeout=timeout)\n        while",
        "        screen = self.s.settle(quiet=0.6, timeout=120.0)\n        while"
    ).replace("deadline.bound(timeout, label)", "timeout").replace(
        "deadline.bound(wait, label)", "wait").replace("deadline.check(label)", "None")
    assert 120.0 in _unrouted_waits(unread, roots)
    assert "wait_bar" in bare
    raised = source.replace("timeout: float = 45.0, deadline=None",
                            "timeout: float = 120.0, deadline=None")
    assert raised != source
    assert 120.0 in _unrouted_waits(raised, roots, bare)
    menu = source.replace("timeout: float = 120.0, deadline=None",
                          "timeout: float = 121.0, deadline=None")
    assert menu != source
    assert 121.0 not in _unrouted_waits(menu, roots, bare)
    called = menu.replace(
        "    def intro(self", "    def again(self):\n"
        "        self.to_party_menu()\n\n    def intro(self").replace(
        "            kind = self.bar(screen)\n            if kind == \"map\"",
        "            kind = self.bar(screen)\n            self.again()\n"
        "            if kind == \"map\"")
    assert called != menu
    assert 121.0 in _unrouted_waits(called, roots, bare)


class _WaitingSession:
    """A session whose every settle takes its whole timeout on the injected
    clock, over screens that are never the one the route wants."""

    def __init__(self, clock, error=None):
        self.clock, self.error = clock, error
        self.waits, self.keys, self.n = [], [], 0

    def settle(self, quiet=0.5, timeout=30.0):
        if self.error:
            raise self.error
        self.waits.append(timeout)
        self.clock.t += timeout
        self.n += 1
        return _Unmoving(self.n)

    def key(self, k, gap=0.0):
        self.keys.append(k)


class _Unmoving:
    def __init__(self, n):
        self.n = n

    def glyphs(self, rect):
        return b"never a known bar"

    def digest(self, rect=None):
        return str(self.n)


def _ssb_waiting(monkeypatch, error=None):
    monkeypatch.setattr(route_silver_blades.time, "sleep", lambda s: None)
    monkeypatch.setattr(da.dospod.time, "sleep", lambda s: None)
    clock = _Clock()
    session = _WaitingSession(clock, error)
    ssb = route_silver_blades.Route(session, lambda **k: None)
    ssb.shot = lambda label: label
    return session, ssb, da.Deadline(clock, 900.0, 120.0)


def test_a_silver_blades_title_that_never_shows_ends_at_the_deadline(monkeypatch):
    session, ssb, deadline = _ssb_waiting(monkeypatch)
    with pytest.raises(da.DeadlineReached, match="reaching the PLAY DEMO|reading the bar"):
        ssb.to_party_menu(deadline=deadline)
    assert deadline.left() < da.ACTION_SECONDS
    assert max(session.waits) <= 30.0


def test_a_silver_blades_intro_that_never_reaches_the_map_ends_at_the_deadline(
        monkeypatch):
    session, ssb, deadline = _ssb_waiting(monkeypatch)
    monkeypatch.setitem(route_silver_blades.BARS, _Unmoving(0).glyphs(None), "continue")
    with pytest.raises(da.DeadlineReached, match="intro"):
        ssb.intro(deadline=deadline)
    assert deadline.left() < da.ACTION_SECONDS


def test_a_wait_for_a_bar_is_cut_to_the_route_time_left(monkeypatch):
    session, ssb, deadline = _ssb_waiting(monkeypatch)
    deadline.clock.t = deadline.route_end - 12.0
    with pytest.raises(da.DeadlineReached):
        ssb.wait_bar("party_menu", timeout=90.0, deadline=deadline)
    assert session.waits[0] == pytest.approx(12.0)


def test_a_pools_route_that_never_settles_ends_at_the_deadline(monkeypatch):
    session, _ssb, _ = _ssb_waiting(monkeypatch)
    deadline = da.Deadline(session.clock, 300.0, 120.0)
    with pytest.raises(da.DeadlineReached, match="Escape"):
        da.dospod.to_party_menu(session, deadline=deadline)
    assert deadline.left() < da.ACTION_SECONDS
    assert max(session.waits) <= 8.0


def test_a_timeout_from_a_settle_is_not_what_a_passed_deadline_reports(monkeypatch):
    """A deadline already over ends the step before any settle can time out."""
    session, ssb, deadline = _ssb_waiting(monkeypatch, error=TimeoutError("settle"))
    deadline.clock.t = deadline.route_end
    with pytest.raises(da.DeadlineReached):
        ssb.to_party_menu(deadline=deadline)
    with pytest.raises(da.DeadlineReached):
        ssb.intro(deadline=deadline)
    with pytest.raises(da.DeadlineReached):
        da.dospod.to_party_menu(session, deadline=deadline)


def _ssb_on_the_real_clock(monkeypatch, left):
    """The waiting fake with `time.time` on the deadline's own clock and
    `left` seconds of the route window remaining."""
    session, ssb, deadline = _ssb_waiting(monkeypatch)
    monkeypatch.setattr(route_silver_blades.time, "time", session.clock)
    session.clock.t = deadline.route_end - left
    return session, ssb, deadline


def test_a_bar_wait_that_runs_out_the_route_window_names_the_deadline(monkeypatch):
    session, ssb, deadline = _ssb_on_the_real_clock(monkeypatch, 12.0)
    with pytest.raises(da.DeadlineReached, match="waiting for the party_menu bar"):
        ssb.wait_bar("party_menu", timeout=90.0, deadline=deadline)


def test_a_bar_wait_without_a_deadline_still_reports_the_missing_bar(monkeypatch):
    session, ssb, _ = _ssb_on_the_real_clock(monkeypatch, 12.0)
    with pytest.raises(route_silver_blades.RouteLost, match="expected the party_menu bar"):
        ssb.wait_bar("party_menu", timeout=10.0)


def test_a_press_with_the_route_window_over_sends_no_key(monkeypatch):
    session, ssb, deadline = _ssb_waiting(monkeypatch)
    deadline.clock.t = deadline.route_end
    with pytest.raises(da.DeadlineReached):
        ssb.press("x", deadline=deadline)
    assert session.keys == []


def test_a_press_cuts_its_settle_to_the_route_time_left(monkeypatch):
    session, ssb, deadline = _ssb_waiting(monkeypatch)
    deadline.clock.t = deadline.route_end - 12.0
    ssb.press("x", deadline=deadline)
    assert session.waits == [pytest.approx(12.0)]


def test_a_press_gives_its_deadline_to_the_bar_wait_it_starts(monkeypatch):
    session, ssb, deadline = _ssb_waiting(monkeypatch)
    deadline.clock.t = deadline.route_end - 12.0
    with pytest.raises(da.DeadlineReached):
        ssb.press("p", "party_menu", deadline=deadline)
    assert session.waits[0] == pytest.approx(12.0)


def test_reading_the_bar_cuts_its_settle_to_the_route_time_left(monkeypatch):
    session, ssb, deadline = _ssb_waiting(monkeypatch)
    deadline.clock.t = deadline.route_end - 12.0
    ssb.bar(deadline=deadline)
    assert session.waits == [pytest.approx(12.0)]


def test_the_press_after_the_title_is_cut_to_the_route_time_left(monkeypatch):
    session, ssb, deadline = _ssb_waiting(monkeypatch)
    monkeypatch.setitem(route_silver_blades.BARS, _Unmoving(0).glyphs(None), "title")
    deadline.clock.t = deadline.route_end - 40.0
    with pytest.raises(da.DeadlineReached):
        ssb.to_party_menu(deadline=deadline)
    assert session.keys == ["p"]
    assert session.waits[-1] <= 10.0 + 1e-9


def test_the_driver_gives_its_deadline_to_the_borrowed_route_calls(monkeypatch):
    import types
    seen = {}
    d = da.Driver.__new__(da.Driver)
    d.deadline = object()
    ssb = route_silver_blades.Route(None, lambda **k: None)
    d._ssb = ssb

    def stop(name):
        def f(*a, **k):
            seen[name] = k.get("deadline")
            raise da.StepFailed("stop")
        return f

    monkeypatch.setattr(ssb, "to_party_menu", stop("ssb"))
    d.slot = "A"
    monkeypatch.setattr(d, "save_path", lambda slot: pathlib.Path("/nonexistent"))
    with pytest.raises(da.StepFailed):
        d._load_ssb()
    # Past the party menu, to the 90 s wait for the loaded party.
    monkeypatch.setattr(ssb, "to_party_menu", lambda **k: None)
    monkeypatch.setattr(ssb, "menu", lambda row, label: None)
    monkeypatch.setattr(ssb, "bar", lambda sc=None, deadline=None: "x")
    monkeypatch.setattr(ssb, "wait_bar", stop("load_wait"))
    d.slot = "A"
    d.s = types.SimpleNamespace(wait_for=lambda pred, t: True,
                                settle=lambda **k: None)
    monkeypatch.setattr(d, "shot", lambda label: label)
    monkeypatch.setattr(d, "press_screen_changes", lambda *a, **k: True)
    with pytest.raises(da.StepFailed):
        d._load_ssb()
    monkeypatch.setattr(d, "save_path", lambda slot: pathlib.Path("/nonexistent"))
    monkeypatch.setattr(da, "pod_menu_after", lambda data: {})
    monkeypatch.setattr(da.dospod, "to_party_menu", stop("pod"))
    with pytest.raises(da.StepFailed):
        d._load_pod()
    d.where, d.title = "party", types.SimpleNamespace(key="ssb")
    monkeypatch.setattr(ssb, "intro", stop("intro"))
    with pytest.raises(da.StepFailed):
        d.begin()
    assert seen == {"ssb": d.deadline, "load_wait": d.deadline,
                    "pod": d.deadline, "intro": d.deadline}


def test_the_measured_curse_and_silver_blades_screens_read_as_recorded():
    """Values read off the player's own #679 boots (skipped without them)."""
    run = "b0a2c904ad-curse-measure-walk"
    party = _capture("b0a2c904ad-curse-measure-sheet", "003-loaded", issue="679")
    assert screens.bar_signature(party) == _MEASURED_CURSE_PARTY_BAR == "31286bfc4a3695fc"
    assert screens.roster_line(party, "party", 6) == 1
    before = _capture(run, "005-map", issue="679")
    after = _capture(run, "009-press-Up", issue="679")
    assert screens.status_square(before, da.status_column("curse")) == "370bef4cdc05b677"
    assert screens.status_square(after, da.status_column("curse")) == "8702eeb23e8a764b"
    ssb = _capture("b0a2c904ad-ssb-measure-walk", "005-map", issue="679")
    assert screens.status_square(ssb, da.status_column("ssb")) == "ee4e8a47d7175485"
    sheet = _capture("b0a2c904ad-ssb-measure-sheet", "008-press-s", issue="679")
    assert screens.sheet_name(sheet) == "55a6494e457686aa"


# -- the command line -----------------------------------------------------------

ROOT = pathlib.Path(__file__).resolve().parents[2]
IMPLEMENTATION = ROOT / "tools" / "dos" / "acceptance.py"


def _cli(*args, cwd=ROOT):
    import subprocess
    import sys
    return subprocess.run([sys.executable, *map(str, args)], cwd=cwd,
                          capture_output=True, text=True, timeout=120)


ENTRY_POINTS = [
    pytest.param([IMPLEMENTATION], id="script"),
    pytest.param(["-m", "tools.dos.acceptance"], id="module"),
]


@pytest.mark.parametrize("command", ENTRY_POINTS)
def test_the_command_prints_help(command):
    done = _cli(*command, "--help")
    assert done.returncode == 0, done.stderr
    assert "--slot" in done.stdout


@pytest.mark.parametrize("command", ENTRY_POINTS)
def test_the_command_blocks_a_slot_that_is_not_a_letter(command, tmp_path):
    done = _cli(*command, "--save", tmp_path, "--slot", "K")
    assert done.returncode == 2
    assert "--slot is one letter, A to J" in done.stderr


@pytest.mark.parametrize("command", ENTRY_POINTS)
def test_the_command_with_no_steps_writes_only_a_summary(command, tmp_path):
    import json
    out = tmp_path / "out"
    done = _cli(*command, "--save", tmp_path, "--out", out)
    assert done.returncode == 0, done.stderr
    summary = json.loads((out / "summary.json").read_text())
    assert set(summary) == {"title", "slot", "steps", "sha", "dirty",
                            "completed", "elapsed_seconds"}
    assert summary["completed"] is True


@pytest.mark.parametrize("command", ENTRY_POINTS)
def test_the_command_with_steps_on_an_empty_save_stops_before_any_summary(
        command, tmp_path):
    """Measured: the missing slot raises `FileNotFoundError` out of `main`, so
    the process exits 1 having logged only `start`."""
    import json
    save = tmp_path / "save"
    save.mkdir()
    out = tmp_path / "out"
    done = _cli(*command, "--save", save, "--out", out, "--steps", "load")
    assert done.returncode == 1
    assert "FileNotFoundError" in done.stderr
    assert not (out / "summary.json").exists()
    events = [json.loads(line)["event"]
              for line in (out / "run.jsonl").read_text().splitlines()]
    assert events == ["start"]


_SIGTERM_CHILD = r'''
import os, pathlib, runpy, sys, time
sys.path.insert(0, sys.argv[1])
work = pathlib.Path(sys.argv[2])
shim = sys.argv[3]
from tools.dos import dosbox, dospod

class Slot:
    def release(self):
        (work / "released").write_text("yes")

class Session:
    def __init__(self, slot, game, exe=None):
        self.dir = work / "session"
        self.save_dir = self.dir / "SAVE"
        self.dir.mkdir(exist_ok=True)
    def stage(self, fresh=False):
        (work / "staging").write_text("yes")
        # Short sleeps, as the real waits are: the kernel may hand the signal
        # to a thread other than the main one, and Python then runs its handler
        # only when the main thread next returns to the interpreter.
        while True:
            time.sleep(0.05)
    def close(self):
        pass

# `run_path` executes the script afresh, so its own `Title` is not `a.Title`:
# the archive lookup is faked where both classes reach it, in the modules.
dosbox.find_game = lambda stem: work
dospod.find_game = lambda stem: work
dosbox.claim = lambda note: Slot()
dosbox.Session = Session
sys.argv = [shim, "--save", str(work / "save"), "--out", str(work / "out"),
            "--steps", "load"]
runpy.run_path(shim, run_name="__main__")
'''


@posix_signals
def test_a_termination_signal_ends_the_command_with_lost_and_the_slot_released(
        tmp_path):
    import json
    import subprocess
    import sys
    import time
    save = tmp_path / "save"
    save.mkdir()
    (save / "SAVGAMA.DAT").write_bytes(bytes(1024))
    child = subprocess.Popen(
        [sys.executable, "-c", _SIGTERM_CHILD, str(ROOT), str(tmp_path), str(IMPLEMENTATION)],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 60
        while not (tmp_path / "staging").exists():
            assert child.poll() is None, child.communicate()
            assert time.monotonic() < deadline, "the run never reached stage"
            time.sleep(0.05)
        child.terminate()
        try:
            _, err = child.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            child.kill()
            _, err = child.communicate()
            pytest.fail(f"the run ignored SIGTERM: {err}")
    finally:
        if child.poll() is None:
            child.kill()
    assert child.returncode == 1, err
    summary = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert summary["lost"] == "Terminated('signal 15')"
    assert (tmp_path / "released").read_text() == "yes"


# -- the camp sheet's HEAL and CURE, HUMAN CHANGE CLASSES, a rest the guards end ----


def _words_bar(text: str) -> bytes:
    """A bar row carrying `text`: each letter's own code as its cell's pattern,
    so equal letters draw equal cells, and a space as a blank cell."""
    return bytes(0 if ch == " " else ord(ch) for ch in text)


def test_the_bar_is_split_into_words_blind_to_the_highlight():
    bar = _words_bar("TRADE DROP HEAL CURE EXIT")
    ordinary = da.bar_words(_screen(bar, b""))
    lit = da.bar_words(_screen(bar, b"", block=(0, 6)))
    assert [len(w) for w in ordinary] == [5, 4, 4, 4, 4] and lit == ordinary


@pytest.mark.parametrize("title,text,heal,cure", [
    ("curse", "TRADE DROP HEAL CURE EXIT", True, True),
    ("curse", "TRADE DROP CURE EXIT", False, True),
    ("curse", "ITEMS SPELLS TRADE DROP HEAL EXIT", True, False),
    ("ssb", "HEAL EXIT", True, False),
    ("ssb", "SPELLS EXIT", False, False),
    ("darkness", "ITEMS SPELLS TRADE DROP LAY CURE EXIT", True, True),
    ("darkness", "ITEMS SPELLS TRADE DEPOSIT DROP EXIT", False, False),
    ("darkness", "ITEMS TRADE DROP CURE EXIT", False, True),
])
def test_the_sheet_bar_offers_heal_and_cure_by_its_letters(title, text, heal, cure):
    words = da.bar_words(_screen(_words_bar(text), b""))
    assert da.sheet_offers(words, title) == {"heal": heal, "cure": cure}


def test_a_bar_that_does_not_end_in_a_four_letter_word_is_no_sheet():
    words = da.bar_words(_screen(_words_bar("HEAL WHOM? SELECT EXITS"), b""))
    assert da.sheet_offers(words, "curse") is None
    assert da.yes_no_words(da.bar_words(_screen(_words_bar("CURE ANYWAY: YES NO"), b"")))


_SHEET_WORDS = {"curse": ("HEAL", "CURE"), "ssb": ("HEAL", "CURE"),
                "darkness": ("LAY", "CURE")}


class FakeSheetCamp(FakePool):
    """A camp whose roster names the current member, `VIEW` opening his sheet,
    as the three titles' `GAME.OVR` sheet loops do (see `da.SHEET_KEYS`).

    `members` maps a roster line to `(may heal, cure uses)`.  The sheet's bar
    is `TRADE DROP [HEAL] [CURE] EXIT`, `HEAL` being `LAY` in Pools of
    Darkness; its key opens `<WORD> WHOM? SELECT EXIT`, whose `S` spends the
    use (unless `select_exits`, which leaves as `EXIT` does), shows the
    message for one capture, and redraws the sheet.  The cure asks `CURE
    ANYWAY: YES NO` first when `anyway`.
    """

    CAMP = _words_bar("SAVE VIEW MAGIC REST ALTER FIX EXIT")

    def __init__(self, tmp, title="curse", members=None, anyway=False,
                 select_exits=False, size=6):
        super().__init__(tmp, keys=TITLE_KEYS[title])
        self.title, self.size, self.line, self.mode = title, size, 1, "camp"
        self.members = members if members is not None else {1: (True, 1)}
        self.anyway, self.select_exits = anyway, select_exits
        self.acting, self.healed, self.cured = None, [], []

    def bar_text(self) -> str:
        heal, cure = _SHEET_WORDS[self.title]
        may, uses = self.members.get(self.line, (False, 0))
        return " ".join(["TRADE", "DROP"] + ([heal] if may else [])
                        + ([cure] if uses else []) + ["EXIT"])

    def key(self, k, gap=0.0):
        self.keys.append(k)
        keys = da.SHEET_KEYS[self.title]
        m = self.mode
        if m == "camp" and k == da.CAMP_ROSTER_NEXT[self.title]:
            self.line = self.line % self.size + 1
        elif m == "camp" and k == "v":
            self.mode = "sheet"
        elif m == "sheet" and k == "e":
            self.mode = "camp"
        elif m == "sheet" and k in keys.values():
            act = "heal" if k == keys["heal"] else "cure"
            word = _SHEET_WORDS[self.title][act == "cure"]
            if word in self.bar_text().split():
                self.mode, self.acting = "prompt", act
        elif m == "prompt" and k == "e":
            self.mode = "sheet"
        elif m == "prompt" and k == "s":
            if self.select_exits:
                self.mode = "sheet"
            elif self.acting == "cure" and self.anyway:
                self.mode = "anyway"
            else:
                self._act()
        elif m == "anyway" and k == "y":
            self._act()
        else:
            self.keys.pop()
            super().key(k, gap)

    def _act(self):
        may, uses = self.members[self.line]
        if self.acting == "heal":
            self.members[self.line] = (False, uses)
            self.healed.append(self.line)
        else:
            self.members[self.line] = (may, uses - 1)
            self.cured.append(self.line)
        self.mode = "message"

    def capture(self):
        if self.mode == "message":
            self.mode = "sheet"
            return _screen(_words_bar("FEELS BETTER"), b"")
        if self.mode == "camp":
            return _with_roster(_screen(self.CAMP, bytes((self.line,))), "camp",
                                self.size, self.line)
        if self.mode in ("sheet", "prompt", "anyway"):
            text = {"sheet": self.bar_text(), "anyway": "CURE ANYWAY: YES NO",
                    "prompt": f"{_SHEET_WORDS[self.title][self.acting == 'cure']} "
                              "WHOM? SELECT EXIT"}[self.mode]
            return _with_roster(_screen(_words_bar(text), b""), "party", self.size,
                                self.line, sheet=self.line)
        return super().capture()


def _sheet_camp(tmp_path, title="curse", **kw):
    game = FakeSheetCamp(tmp_path, title, **kw)
    d = da.Driver(game, lambda **k: None, "J", title, party_size=game.size)
    d.logged = []
    d.note = lambda **k: d.logged.append(k)
    d.camp_sig = screens.bar_signature(game.capture())
    d.where = "camp"
    return game, d


@pytest.mark.parametrize("title,next_key", [("curse", "End"), ("ssb", "Down"),
                                            ("darkness", "Down")])
def test_a_camp_sheet_logs_whether_heal_and_cure_are_offered(tmp_path, title, next_key):
    game, d = _sheet_camp(tmp_path, title, members={2: (True, 0), 3: (False, 2)})
    got = d.sheet(2)
    assert game.keys == [next_key, "v", "e"] and game.mode == "camp"
    assert (got["heal_offered"], got["cure_offered"]) == (True, False)
    got = d.sheet(3)
    assert (got["heal_offered"], got["cure_offered"]) == (False, True)
    sheets = [e for e in d.logged if e.get("event") == "sheet"]
    assert [(e["line"], e["heal_offered"], e["cure_offered"]) for e in sheets] == [
        (2, True, False), (3, False, True)]


@pytest.mark.parametrize("title", ["curse", "ssb", "darkness"])
def test_heal_spends_the_use_and_the_sheet_comes_back_without_it(tmp_path, title):
    game, d = _sheet_camp(tmp_path, title, members={1: (True, 1), 2: (True, 1)})
    got = d.heal(2)
    heal_key = {"curse": "h", "ssb": "h", "darkness": "l"}[title]
    assert game.keys[-4:] == ["v", heal_key, "s", "e"] and game.mode == "camp"
    assert game.healed == [2] and game.members[2] == (False, 1)
    assert (got["heal_offered"], got["heal_offered_after"]) == (True, False)
    assert got["cure_offered_after"] is True


def test_heal_is_not_pressed_on_a_sheet_that_does_not_offer_it(tmp_path):
    game, d = _sheet_camp(tmp_path, members={1: (False, 1)})
    with pytest.raises(da.StepFailed, match="does not offer HEAL"):
        d.heal(1)
    assert "h" not in game.keys and game.healed == []


def test_a_select_that_leaves_heal_on_the_sheet_stops_the_run(tmp_path):
    game, d = _sheet_camp(tmp_path, select_exits=True)
    with pytest.raises(da.StepFailed, match="still offering HEAL"):
        d.heal(1)
    assert game.healed == []


@pytest.mark.parametrize("anyway", [False, True])
def test_cure_answers_cure_anyway_with_yes_and_keeps_a_use_left(tmp_path, anyway):
    game, d = _sheet_camp(tmp_path, members={1: (True, 2)}, anyway=anyway)
    got = d.cure(1)
    assert game.cured == [1] and game.members[1] == (True, 1) and game.mode == "camp"
    assert got["answered"] == (["y"] if anyway else [])
    assert game.keys.count("y") == int(anyway)
    assert got["cure_offered_after"] is True


def test_the_last_cure_takes_cure_off_the_sheet(tmp_path):
    game, d = _sheet_camp(tmp_path, members={1: (False, 1)})
    got = d.cure(1)
    assert game.cured == [1] and got["cure_offered_after"] is False


# -- HUMAN CHANGE CLASSES ---------------------------------------------------------


def _class_segment() -> bytes:
    """A data segment holding Curse's four tables as the code reads them:
    names for classes 0-7; human (race 7) listing cleric, fighter,
    magic-user, thief, paladin, ranger; each class's minima; and each
    class's alignments.  The values are this test's, not the game's."""
    ds = bytearray(0x4400)
    names = ("Cleric", "Druid", "Fighter", "Paladin", "Ranger", "Magic-User",
             "Thief", "Monk")
    for cid, name in enumerate(names):
        at = da.CLASS_NAMES_AT + da.CLASS_NAME_SIZE * cid
        ds[at] = len(name)
        ds[at + 1:at + 1 + len(name)] = name.encode()
    human = da.RACE_CLASSES_AT + da.RACE_CLASSES_SIZE * da.HUMAN_RACE
    ds[human:human + 7] = bytes((6, 0, 2, 5, 6, 3, 4))
    minima = {0: (0, 0, 9, 0, 0, 0), 2: (9, 0, 0, 0, 0, 0), 3: (12, 9, 13, 0, 9, 17),
              4: (13, 13, 14, 0, 14, 0), 5: (0, 9, 0, 0, 0, 0), 6: (0, 0, 0, 9, 0, 0)}
    for cid, row in minima.items():
        at = da.CLASS_MINIMA_AT + da.CLASS_MINIMA_SIZE * cid
        ds[at:at + 6] = bytes(row)
    aligned = {0: range(9), 2: range(9), 3: (0,), 4: (0, 3, 6), 5: range(9),
               6: (1, 2, 3, 4, 5, 7, 8)}
    for cid, allowed in aligned.items():
        at = da.CLASS_ALIGNMENTS_AT + da.CLASS_ALIGNMENTS_SIZE * cid
        ds[at] = len(allowed)
        ds[at + 1:at + 1 + len(allowed)] = bytes(allowed)
    return bytes(ds)


def _change_record(race=7, klass=3, level=5, abilities=(18, 17, 16, 17, 17, 17),
                   alignment=0, former=None) -> bytes:
    from goldbox import dos_port
    fields = dos_port.FIELDS_BY_NAME_FOR["curse-of-the-azure-bonds"]
    data = bytearray(_curse_record(b"MARK"))
    data[fields["race"].offset] = race
    data[fields["class_levels"].offset + klass] = level
    if former is not None:
        data[fields["former_class_levels"].offset + former] = 5
    for name, value in zip(da.ABILITIES, abilities):
        data[fields[name].offset] = value
    data[fields["alignment"].offset] = alignment
    return bytes(data)


def test_the_class_test_reads_the_engines_offsets():
    """0x3B99E reads `0x10 + 2k`, `0x74`, `0x109`, `0x111` and `0x11B`."""
    from goldbox import dos_port
    fields = dos_port.FIELDS_BY_NAME_FOR["curse-of-the-azure-bonds"]
    assert [fields[a].offset for a in da.ABILITIES] == [0x10, 0x12, 0x14, 0x16, 0x18,
                                                       0x1A]
    assert [fields[f].offset for f in ("race", "class_levels", "former_class_levels",
                                       "alignment")] == [0x74, 0x109, 0x111, 0x11B]


@pytest.mark.parametrize("record,expected", [
    # A lawful good paladin 5, wisdom 16: fighter and magic-user, not cleric or
    # ranger (wisdom), thief (alignment) or paladin (his own class).
    ({}, ["FIGHTER", "MAGIC-USER"]),
    ({"abilities": (18, 17, 17, 17, 17, 17)},
     ["CLERIC", "FIGHTER", "MAGIC-USER", "RANGER"]),
    # Charisma 14 fails a paladin's own requisite, so he may take nothing.
    ({"abilities": (18, 17, 16, 17, 17, 14)}, []),
    # A neutral fighter may take thief, not paladin.
    ({"klass": 2, "alignment": 4, "abilities": (17, 12, 12, 17, 12, 12)}, ["THIEF"]),
    ({"race": 1}, []),
    ({"former": 3, "klass": 5, "level": 1}, []),
], ids=["paladin", "wise-paladin", "paladin-charisma-14", "neutral-fighter",
        "dwarf", "changed-before"])
def test_the_class_list_is_the_engines_test_in_the_races_order(record, expected):
    got = da.class_choices(_change_record(**record), _class_segment())
    assert [name for _, name in got] == expected


class FakeChangeMenu(FakeCurseMenu):
    """Curse's party menu with `HUMAN CHANGE CLASSES`: `h` opens a list whose
    header takes row 0 and whose classes take the rows after it, the first
    highlighted; `End` moves the highlight down and wraps, `Home` up; `s`
    takes the class and returns to the party menu."""

    BARS = {**FakeCurseMenu.BARS, "classes": b"\x17\x18"}

    def __init__(self, tmp, classes=("FIGHTER", "MAGIC-USER"), shown=None,
                 hall=True):
        super().__init__(tmp)
        self.classes, self.hall = list(classes), hall
        self.shown = len(self.classes) if shown is None else shown
        self.row, self.changed = 0, []

    def key(self, k, gap=0.0):
        if self.mode == "party" and k == da.PARTY_CHANGE:
            self.keys.append(k)
            if self.hall:
                self.mode, self.row = "classes", 0
        elif self.mode == "classes":
            self.keys.append(k)
            if k == "End":
                self.row = (self.row + 1) % self.shown
            elif k == "Home":
                self.row = (self.row - 1) % self.shown
            elif k == "s":
                self.changed.append((self.line, self.classes[self.row]))
                self.mode = "party"
        else:
            super().key(k, gap)

    def capture(self):
        if self.mode != "classes":
            return super().capture()
        px = bytearray(_screen(self.BARS["classes"], b"").px)
        top = da.CHANGE_LIST[1] + screens.CELL * (1 + self.row)
        for y in range(top, top + screens.CELL):
            for x in range(40, 200):
                px[(y * W + x) * 3:(y * W + x) * 3 + 3] = b"\xff\xff\xff"
        return dosbox.Screen(W, H, bytes(px))

    walk_highlight = dosbox.Session.walk_highlight


def _changing(tmp_path, record, **kw):
    (tmp_path / "game").mkdir()
    game = FakeChangeMenu(tmp_path / "game", **kw)
    d = da.Driver(game, lambda **k: None, "J", "curse", party_size=game.size)
    d.game.to_main_menu = lambda timeout=120.0: None
    d.load()
    (game.save_dir / "CHRDATJ2.SAV").write_bytes(record)
    d._class_ds = _class_segment()
    return game, d


@pytest.mark.parametrize("wanted,ends", [("FIGHTER", 0), ("MAGIC-USER", 1)])
def test_change_takes_the_row_the_engines_test_puts_the_class_on(tmp_path, wanted,
                                                                  ends):
    game, d = _changing(tmp_path, _change_record())
    got = d.change(2, wanted)
    assert game.changed == [(2, wanted)] and game.mode == "party" and d.on_party_menu()
    assert game.keys[2:4] == ["End", "h"]
    assert got["choices"] == ["FIGHTER", "MAGIC-USER"] and got["row"] == 1 + ends


def test_a_list_longer_than_the_engines_test_stops_before_select(tmp_path):
    game, d = _changing(tmp_path, _change_record(),
                        classes=("FIGHTER", "MAGIC-USER", "THIEF"))
    with pytest.raises(da.StepFailed, match="not the 2 consecutive rows"):
        d.change(2, "FIGHTER")
    assert game.changed == [] and "s" not in game.keys[2:]


def test_a_class_the_engine_does_not_offer_is_blocked_before_a_key(tmp_path):
    game, d = _changing(tmp_path, _change_record())
    with pytest.raises(da.StepFailed, match="may not change to CLERIC"):
        d.change(2, "CLERIC")
    assert game.keys == ["l", "j"]


def test_a_shut_hall_stops_the_change(tmp_path):
    game, d = _changing(tmp_path, _change_record(), hall=False)
    with pytest.raises(da.StepFailed, match="stage --hall"):
        d.change(2, "FIGHTER")
    assert game.changed == []


# -- a Curse rest that a message ends ------------------------------------------------


class _FakeCurseGuards(FakeCurseMenu):
    """Curse whose rests end, `guards` times, on a message over the continue
    bar; `Return` puts the party on the map, out of camp."""

    BARS = {**FakeCurseMenu.BARS, "guards": b"\x19\x1a"}

    def __init__(self, tmp, guards=1, back="map"):
        super().__init__(tmp)
        self.guards, self.back = guards, back

    def key(self, k, gap=0.0):
        if self.mode == "guards":
            self.keys.append(k)
            if k == "Return":
                self.mode = self.back
            return
        super().key(k, gap)
        if self.mode == "camp" and self.keys[-1] == "r" and self.rested and self.guards:
            self.guards -= 1
            self.mode = "guards"


def _guarded(tmp_path, monkeypatch, **kw):
    game = _FakeCurseGuards(tmp_path, **kw)
    monkeypatch.setattr(da, "CURSE_CONTINUE_BAR",
                        _screen(game.BARS["guards"], b"").glyphs(dosbox.BAR))
    d = da.Driver(game, lambda **k: None, "J", "curse", party_size=game.size)
    d.game.to_main_menu = lambda timeout=120.0: None
    d.load()
    d.begin()
    d.camp()
    return game, d


def test_a_curse_rest_the_guards_end_continues_and_camps_again(tmp_path, monkeypatch):
    game, d = _guarded(tmp_path, monkeypatch)
    got = d.rest(5)
    assert got["ended_by_message"] is True and game.rested == [5]
    # `FakeCurseMenu` hands camp keys on to `FakePool`, which logs them again.
    after = game.keys[game.keys.index("Return"):]
    assert after[0] == "Return" and set(after[1:]) == {da.ENCAMP}
    assert game.keys.count("Return") == 1 and game.mode == "camp"
    assert d.where == "camp" and d.in_camp()
    assert [e["kind"] for e in d.events] == ["press_continue"]
    d.save("D")
    assert (game.save_dir / "SAVGAMD.DAT").is_file()


def test_a_rest_message_that_does_not_lead_to_the_map_stops_the_run(tmp_path,
                                                                     monkeypatch):
    game, d = _guarded(tmp_path, monkeypatch, back="party")
    with pytest.raises(da.StepFailed, match="map bar did not come back"):
        d.rest(5)


def test_a_curse_rest_that_ends_in_camp_is_not_a_message(tmp_path, monkeypatch):
    game, d = _guarded(tmp_path, monkeypatch, guards=0)
    got = d.rest(5)
    assert got["ended_by_message"] is False and "Return" not in game.keys


# -- the new steps' words and orders --------------------------------------------------


def test_heal_cure_and_change_parse_and_bad_ones_are_blocked():
    assert (da.parse_step("heal 2").kind, da.parse_step("heal 2").line) == ("heal", 2)
    assert (da.parse_step("cure 8").kind, da.parse_step("cure 8").line) == ("cure", 8)
    step = da.parse_step("change 2 magic-user")
    assert (step.kind, step.line, step.name) == ("change", 2, "MAGIC-USER")
    for bad in ("heal", "heal 9", "cure 0", "change 2", "change 2 WIZARD",
                "change 9 FIGHTER"):
        with pytest.raises(ValueError):
            da.parse_step(bad)


@pytest.mark.parametrize("title,steps", [
    ("curse", ("load", "begin", "camp", "sheet 2", "rest 1h", "save C", "rest 1d",
               "sheet 2", "heal 2", "save D", "read")),
    ("curse", ("load", "train 2", "begin", "camp", "rest 5m", "save C", "cure 2",
               "save D", "read")),
    ("curse", ("load", "change 2 FIGHTER", "save E", "read")),
    ("ssb", ("load", "begin", "camp", "sheet 1", "heal 1", "save D", "read")),
    ("darkness", ("load", "begin", "camp", "sheet 4", "heal 4", "save D", "read")),
])
def test_orders_the_camp_sheet_steps_allow(title, steps):
    da.validate_steps(_steps(*steps), title)


@pytest.mark.parametrize("title,steps,why", [
    ("curse", ("load", "heal 1"), "heal needs camp first"),
    ("curse", ("load", "begin", "sheet 1"), "sheet needs camp first"),
    ("ssb", ("load", "begin", "camp", "cure 1"), "cure is driven in curse only"),
    ("pool", ("load", "camp", "heal 1"), "heal is driven in curse, darkness, ssb only"),
    ("pool", ("load", "camp", "cure 1"), "cure is driven in curse only"),
    ("curse", ("load", "begin", "change 1 FIGHTER"), "change needs the party menu"),
    ("ssb", ("load", "change 1 FIGHTER"), "change is driven in curse only"),
])
def test_orders_the_camp_sheet_steps_block(title, steps, why):
    with pytest.raises(ValueError, match=why):
        da.validate_steps(_steps(*steps), title)


# -- the same readings on the captures and the player's own tables ------------------


@pytest.mark.parametrize("issue,run,shot,title,lengths,heal,cure", [
    # DEMELTINA, a Curse paladin 5, `TRADE DROP HEAL CURE EXIT`.
    ("597", "5466354e7a-xp-ceiling", "005-view-1-sheet", "curse", [5, 4, 4, 4, 4],
     True, True),
    # TURBO K, a Pools of Darkness paladin 12, `ITEMS SPELLS TRADE DROP LAY CURE EXIT`.
    ("650", "eafdbfabb0-m-itemskeys", "009-sheet-1", "darkness",
     [5, 6, 5, 4, 3, 4, 4], True, True),
    ("678", "591c0bf9ce-run3-walk", "007-view-4-sheet", "darkness", [5, 6, 5, 4, 4],
     False, False),
    # PAINE, a Silver Blades ranger, `SPELLS EXIT`.
    ("683", "6e377388d6-run", "006-view-2-sheet", "ssb", [6, 4], False, False),
])
def test_the_captured_sheets_offer_what_their_bars_say(issue, run, shot, title,
                                                       lengths, heal, cure):
    words = da.bar_words(_capture(run, shot, issue))
    assert [len(w) for w in words] == lengths
    assert da.sheet_offers(words, title) == {"heal": heal, "cure": cure}


@pytest.mark.parametrize("run", ["8f554ce380-curse-crash", "8f554ce380-curse-crash-2"])
def test_the_captured_guards_message_is_the_curse_continue_bar(run):
    screen = _capture(run, "009-lost-rest-end", "649")
    assert screen.glyphs(dosbox.BAR) == da.CURSE_CONTINUE_BAR


def test_the_players_curse_tables_list_a_humans_classes_in_order():
    try:
        game = dosbox.find_game("CURSE")
    except FileNotFoundError:
        pytest.skip("needs the DOS archives ($FR_ARCHIVES)")
    ds = da.class_tables((game / "START.EXE").read_bytes())
    human = da.RACE_CLASSES_AT + da.RACE_CLASSES_SIZE * da.HUMAN_RACE
    assert [da.class_name(ds, c) for c in ds[human + 1:human + 1 + ds[human]]] == [
        "CLERIC", "FIGHTER", "MAGIC-USER", "THIEF", "PALADIN", "RANGER"]
    assert tuple(da.class_name(ds, c) for c in range(8)) == da.CHANGE_CLASSES


def test_the_players_curse_tables_offer_mark_fighter_and_magic_user():
    """`WISH-SPEC-curse-131-dualclassed-in-area-1` slot J: MARK, a lawful good
    human paladin 5 with wisdom 16, is offered FIGHTER and MAGIC-USER, the
    two his twin MATHEW was offered when he took MAGIC-USER in the game's own
    screen; MATHEW, having changed, and the dwarf TRAVIS are offered none."""
    from tools.registry import specimens
    folder = specimens.tree_root() / "por-dos" / "WISH-SPEC-curse-131-dualclassed-in-area-1"
    if not folder.is_dir():
        pytest.skip("needs WISH-SPEC-curse-131-dualclassed-in-area-1")
    try:
        game = dosbox.find_game("CURSE")
    except FileNotFoundError:
        pytest.skip("needs the DOS archives ($FR_ARCHIVES)")
    ds = da.class_tables((game / "START.EXE").read_bytes())

    def offered(n):
        return [name for _, name in da.class_choices(
            (folder / f"CHRDATJ{n}.SAV").read_bytes(), ds)]
    assert offered(2) == ["FIGHTER", "MAGIC-USER"]
    assert offered(1) == [] and offered(3) == []


# -- Pool's ITEMS list, from camp ------------------------------------------------

#: Synthetic bars for the sheet, the sheet with no ITEMS, and the list.
_POOL_ITEMS_BARS = {"sheet": b"\x15\x48\x7b", "no_items": b"\x16\x49\x7c",
                    "list": b"\x1b\x1c\x1d"}
_MARK = b"\x5a"


class PoolItems(FakePool):
    """Pool's camp `VIEW` > `ITEMS` as the live boot showed it: `End` moves the
    roster, `v` opens the sheet, `i` the list, `Escape` steps back one screen.
    `rows` is what the list draws, each entry `(marked)`."""

    BARS = {**FakePool.BARS, **_POOL_ITEMS_BARS}

    def __init__(self, *a, rows=(False, False), sheet="sheet", back="camp", **k):
        super().__init__(*a, **k)
        self.line, self.rows, self.sheet, self.back = 1, rows, sheet, back

    def key(self, k, gap=0.0):
        if self.mode == "camp" and k == "End":
            self.keys.append(k)
            self.line = self.line % 6 + 1
        elif self.mode == "camp" and k == "v":
            self.keys.append(k)
            self.mode = "sheet"
        elif self.mode == "sheet" and k == "i":
            self.keys.append(k)
            self.mode = "list" if self.sheet == "sheet" else "sheet"
        elif self.mode == "list" and k == "Escape":
            self.keys.append(k)
            self.mode = "sheet"
        elif self.mode == "sheet" and k == "Escape":
            self.keys.append(k)
            self.mode = "camp" if self.back == "camp" else "sheet"
        else:
            super().key(k, gap)

    def capture(self):
        if self.mode == "camp":
            return _with_roster(_screen(self.BARS["camp"], b""), "camp", 6, self.line)
        if self.mode == "sheet":
            return _with_roster(_screen(self.BARS[self.sheet], b""), "camp", 6, 0,
                                sheet=self.line)
        if self.mode == "list":
            px = bytearray(_screen(self.BARS["list"], b"").px)
            for k, marked in enumerate(self.rows):
                _draw_name(px, 16, 40 + 8 * k, b"\x18\x24\x42", _GREEN)
                if marked:
                    _draw_name(px, da.POOL_ITEM_MARK_X, 40 + 8 * k, _MARK, _GREEN)
            return dosbox.Screen(W, H, bytes(px))
        return super().capture()


def _pool_items(tmp_path, monkeypatch, **kw) -> tuple[PoolItems, da.Driver]:
    def sig(name):
        return screens.bar_signature(_screen(_POOL_ITEMS_BARS[name], b""))

    monkeypatch.setattr(da, "POOL_SHEET_BARS", {"items": sig("sheet"),
                                                "no_items": sig("no_items")})
    monkeypatch.setattr(screens, "POOL_ITEMS_BAR", sig("list"))
    marked = _screen(b"", b"")
    px = bytearray(marked.px)
    _draw_name(px, da.POOL_ITEM_MARK_X, 40, _MARK, _GREEN)
    monkeypatch.setattr(da, "POOL_ITEM_MARK", hashlib.sha1(dosbox.Screen(
        W, H, bytes(px)).glyphs((da.POOL_ITEM_MARK_X, 40, 8, 8)).encode()).hexdigest()[:16])
    game = PoolItems(tmp_path, **kw)
    d = da.Driver(game, lambda **k: None, "A")
    d.camp()
    return game, d


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_items_reads_the_rows_and_which_are_marked_and_returns_to_camp(
        tmp_path, monkeypatch):
    game, d = _pool_items(tmp_path, monkeypatch, rows=(True, False, True))
    got = d.items(2)
    assert game.keys[1:] == ["End", "v", "i", "Escape", "Escape"]     # never `e`
    assert got["rows"] == 3 and got["marked"] == [1, 3] and got["line"] == 2
    assert game.mode == "camp" and d.where == "camp"


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_items_reports_no_marked_row_on_an_unmarked_list(tmp_path, monkeypatch):
    game, d = _pool_items(tmp_path, monkeypatch, rows=(False, False))
    got = d.items(1)
    assert got["rows"] == 2 and got["marked"] == []


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_items_blocks_a_sheet_with_no_items_before_pressing_i(tmp_path, monkeypatch):
    game, d = _pool_items(tmp_path, monkeypatch, sheet="no_items")
    with pytest.raises(da.StepFailed, match="offers no ITEMS"):
        d.items(1)
    assert "i" not in game.keys


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_items_stops_when_the_list_bar_is_not_showing(tmp_path, monkeypatch):
    game, d = _pool_items(tmp_path, monkeypatch, rows=(True,))
    monkeypatch.setattr(screens, "POOL_ITEMS_BAR", "0" * 16)
    with pytest.raises(da.StepFailed, match="list bar"):
        d.items(1)
    assert "Escape" not in game.keys


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_items_stops_when_escape_does_not_reach_camp(tmp_path, monkeypatch):
    game, d = _pool_items(tmp_path, monkeypatch, back="sheet")
    with pytest.raises(da.StepFailed, match="camp bar did not return"):
        d.items(1)
    assert not game.save_file("D").exists()


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_items_a_list_that_fills_the_readable_rows_stops(tmp_path, monkeypatch):
    game, d = _pool_items(tmp_path, monkeypatch, rows=(False,) * da.ITEM_ROWS)
    with pytest.raises(da.StepFailed, match="next page"):
        d.items(1)


def test_the_pool_items_bar_is_recognised_as_a_list_and_a_sheet_is_not(monkeypatch):
    bar = screens.bar_signature(_screen(_POOL_ITEMS_BARS["list"], b""))
    monkeypatch.setattr(screens, "POOL_ITEMS_BAR", bar)
    px = bytearray(_screen(_POOL_ITEMS_BARS["list"], b"").px)
    _draw_name(px, 16, 40, b"\x18\x24\x42", _GREEN)
    listed = dosbox.Screen(W, H, bytes(px))
    assert screens.on_items_list(listed) and screens.item_rows(listed) == 1
    sheet = _screen(_POOL_ITEMS_BARS["sheet"], b"")
    assert not screens.on_items_list(sheet) and screens.item_rows(sheet) is None
    # Pools of Darkness' head still names its own list.
    pod = _screen(b"\x2b\x2c", b"")
    assert screens.on_items_list(pod)


def test_the_measured_pool_items_constants():
    assert da.POOL_ITEMS_BAR == screens.POOL_ITEMS_BAR == "0a653b8b1d7793d7"
    assert da.POOL_ITEM_MARK == "4590f6541a365c32" and da.POOL_ITEM_MARK_X == 56


def test_validate_steps_takes_pool_items_in_camp_only():
    da.validate_steps(_steps("load", "camp", "items 2", "save D", "read"), "pool")
    with pytest.raises(ValueError, match="items needs camp first"):
        da.validate_steps(_steps("load", "items 2"), "pool")
    with pytest.raises(ValueError, match="driven in darkness only"):
        da.validate_steps(_steps("load", "begin", "camp", "items 2"), "curse")
    da.validate_steps(_steps("load", "begin", "camp", "items 2"), "darkness")


def _pool_record(name: bytes = b"WISHFTR") -> bytes:
    from goldbox import dos_port
    size = dos_port.deltas_for("pool-of-radiance").record_size
    data = bytearray(size)
    data[0] = len(name)
    data[1:1 + len(name)] = name
    return bytes(data)


def test_a_stage_record_line_parses_hex_and_decimal_and_lists():
    assert da.parse_record_bytes(["1:0x10C=1"]) == [(1, 0x10C, 1)]
    assert da.parse_record_bytes(["1:0x84=0xB3,2:114=6", "1:159=4"]) == [
        (1, 0x84, 0xB3), (2, 114, 6), (1, 159, 4)]


@pytest.mark.parametrize("bad", ["1:0x10C", "1=3", "0:5=1", "9:5=1", "1:5=256",
                                 "1:-1=1", "1:5=", "x:5=1"])
def test_a_bad_stage_record_line_is_blocked(bad):
    with pytest.raises(ValueError):
        da.parse_record_bytes([bad])


def test_stage_record_changes_exactly_the_named_byte(tmp_path):
    original = _pool_record()
    (tmp_path / "CHRDATD1.SAV").write_bytes(original)
    got = staging.stage_record(tmp_path, "D", 1, 0x10C, 6)
    after = (tmp_path / "CHRDATD1.SAV").read_bytes()
    assert len(after) == len(original)
    assert [i for i in range(len(after)) if after[i] != original[i]] == [0x10C]
    assert after[0x10C] == 6
    assert got == {"stage": "record", "file": "CHRDATD1.SAV", "name": "WISHFTR",
                   "offset": "0x10c", "before": "00", "after": "06"}


def test_stage_record_blocks_an_offset_past_the_record(tmp_path):
    original = _pool_record()
    (tmp_path / "CHRDATD1.SAV").write_bytes(original)
    with pytest.raises(ValueError, match="outside"):
        staging.stage_record(tmp_path, "D", 1, len(original), 1)
    assert (tmp_path / "CHRDATD1.SAV").read_bytes() == original


def test_the_command_line_wires_stage_record_after_stage_control(tmp_path):
    (tmp_path / "CHRDATD1.SAV").write_bytes(_pool_record())
    args = _run_args(tmp_path, [])
    args.stage_control = ["1=0xB3"]
    args.stage_record = ["1:0x10C=1", "1:0x9F=4"]
    done = da.stage(tmp_path, "D", args)
    assert [d["stage"] for d in done] == ["control", "record", "record"]
    data = (tmp_path / "CHRDATD1.SAV").read_bytes()
    assert (data[0x10C], data[0x9F]) == (1, 4)


def test_check_staging_blocks_a_stage_record_before_the_boot(tmp_path):
    args = _run_args(tmp_path, [])
    args.stage_record = ["1:0x10C=1"]
    with pytest.raises(ValueError, match="line 1"):
        da.check_staging(args, tmp_path, "D")
    (tmp_path / "CHRDATD1.SAV").write_bytes(_pool_record())
    da.check_staging(args, tmp_path, "D")
    args.stage_record = ["1:0x2000=1"]
    with pytest.raises(ValueError, match="outside"):
        da.check_staging(args, tmp_path, "D")


def test_read_slot_reports_the_status_bytes_and_the_turning_readings(tmp_path):
    (tmp_path / "SAVGAMD.DAT").write_bytes(bytes(13149))
    record = bytearray(_pool_record())
    for offset, value in ((0x10C, 1), (0x10F, 1), (0x9F, 4), (0x76, 2), (0x72, 6)):
        record[offset] = value
    (tmp_path / "CHRDATD1.SAV").write_bytes(bytes(record))
    out = da.read_slot(tmp_path, "D")["characters"][0]
    assert out["status_bytes"] == [1, 0, 0, 1]
    assert (out["creature_type"], out["turn_class"], out["movement"]) == (4, 2, 6)


@pytest.mark.parametrize("bad", ["1:010=1", "1:0x10=01", "1:1_0=1", "1:+5=1",
                                 "1:0b11=1", "1:0o7=1", "1:0xZZ=1", "1:5=1.5"])
def test_a_record_number_that_is_not_plain_decimal_or_hex_is_blocked_by_item(bad):
    with pytest.raises(ValueError) as e:
        da.parse_record_bytes(["1:2=3", bad])
    assert repr(bad) in str(e.value)


def test_a_repeated_record_offset_keeps_the_last_value(tmp_path):
    (tmp_path / "CHRDATD1.SAV").write_bytes(_pool_record())
    args = _run_args(tmp_path, [])
    args.stage_record = ["1:0x10C=1", "1:0x10C=6"]
    da.stage(tmp_path, "D", args)
    assert (tmp_path / "CHRDATD1.SAV").read_bytes()[0x10C] == 6


def test_read_slot_gives_none_for_a_byte_a_title_has_not_mapped(tmp_path):
    (tmp_path / "SAVGAMJ.DAT").write_bytes(bytes(13149))
    (tmp_path / "CHRDATJ1.SAV").write_bytes(_curse_record())
    out = da.read_slot(tmp_path, "J")["characters"][0]
    assert out["creature_type"] is None
    assert out["status_bytes"] == [0, 0, 0, 0]
    assert (out["turn_class"], out["movement"]) == (0, 0)


def test_a_stage_record_names_a_lowercase_source_file_and_any_slot_letter(tmp_path):
    (tmp_path / "chrdatj1.sav").write_bytes(_pool_record())
    args = _run_args(tmp_path, [])
    args.stage_record = ["1:0x10C=1"]
    da.check_staging(args, tmp_path, "J")
    (tmp_path / "chrdatj1.sav").rename(tmp_path / "CHRDATJ1.SAV")
    assert da.stage(tmp_path, "j", args)[0]["file"] == "CHRDATJ1.SAV"
    assert (tmp_path / "CHRDATJ1.SAV").read_bytes()[0x10C] == 1


@pytest.mark.parametrize("option, bad", [("--stage-record", "1:010=1"),
                                         ("--stage-control", "1=0xZZ")])
def test_main_blocks_a_bad_stage_value_before_anything_is_built(
        tmp_path, monkeypatch, capsys, option, bad):
    def claimed(*a, **k):
        raise AssertionError("an emulator slot was claimed")

    monkeypatch.setattr(da.dosbox, "claim", claimed)
    with pytest.raises(SystemExit):
        da.main(["--save", str(tmp_path), "--steps", "load", option, bad,
                 "--out", str(tmp_path / "out")])
    err = capsys.readouterr().err
    assert bad.partition("=")[2] in err if option == "--stage-control" else repr(bad) in err


# -- fight: Curse and Silver Blades, read through the debugger ---------------

#: One cell pattern per letter, each a different byte of at most three bits,
#: so `bar_words` reads a word's cells as distinct glyphs and a letter repeated
#: across words as the same glyph.
_LETTER = {c: b for c, b in zip(
    "MOVEWIAUSCQKDNTBFLRXHPYG",
    (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x03, 0x05, 0x09, 0x11,
     0x21, 0x41, 0x81, 0x06, 0x0A, 0x12, 0x22, 0x42, 0x82, 0x0C, 0x14, 0x24))}


def _bar(text: str) -> bytes:
    """`text` as bar cells, a flat cell between words."""
    return bytes(0 if c == " " else _LETTER[c] for c in text)


def _words(text: str) -> list[list[str]]:
    return da.bar_words(_screen(_bar(text), b""))


def test_the_command_bar_is_known_by_its_letters_whatever_the_member_is_offered():
    for text in ("MOVE VIEW AIM USE CAST TURN QUICK DONE",   # Curse's, whole
                 "MOVE VIEW AIM USE CAST QUICK DONE",        # Silver Blades'
                 "MOVE VIEW AIM QUICK DONE"):                # nothing to use
        assert da.command_words(_words(text)), text
    for text in ("MOVE AREA CAST VIEW ENCAMP SEARCH LOOK",   # the map bar
                 "MOVE VIEW ARM", "COMBAT WAIT FLEE ADVANCE", "EXIT"):
        assert not da.command_words(_words(text)), text


def test_the_encounter_and_treasure_bars_are_known_by_their_letters():
    assert da.encounter_words(_words("COMBAT WAIT FLEE ADVANCE"))
    assert da.encounter_words(_words("COMBAT WAIT FLEE PARLAY"))
    assert not da.encounter_words(_words("MOVE VIEW AIM USE CAST QUICK DONE"))
    assert not da.encounter_words(_words("CAMBOT WAIT FLEE"))
    assert da.treasure_words(_words("VIEW TAKE POOL SHARE EXIT"))
    assert not da.treasure_words(_words("VIEW TAKE POOL SHARE EXIT DONE"))
    assert not da.treasure_words(_words("SAVE VIEW MAGIC REST EXIT"))


def test_the_fight_step_parses_for_pool_curse_and_silver_blades_only():
    assert da.parse_step("fight").seconds == 0
    assert da.parse_step("fight 900").seconds == 900
    for bad in ("fight 0", "fight x", "fight 9 9"):
        with pytest.raises(ValueError):
            da.parse_step(bad)
    for title in ("curse", "ssb"):
        da.validate_steps([da.parse_step(s) for s in
                           ("load", "begin", "fight", "camp", "save E", "read")], title)
        with pytest.raises(ValueError, match="needs the map"):
            da.validate_steps([da.parse_step(s) for s in ("load", "fight")], title)
    da.validate_steps([da.parse_step(s) for s in ("load", "fight", "read")], "pool")
    with pytest.raises(ValueError, match="curse, pool, ssb only"):
        da.validate_steps([da.parse_step(s) for s in ("load", "begin", "fight")],
                          "darkness")


def test_the_first_bar_key_is_space_or_one_letter_or_digit():
    assert da.parse_key("SPACE") == "space"
    assert da.parse_key("space") == "space"
    assert da.parse_key("Q") == "q"
    assert da.parse_key("7") == "7"
    for bad in ("", "QQ", "-", "Return"):
        with pytest.raises(ValueError):
            da.parse_key(bad)


@pytest.mark.parametrize("extra, error", [
    (["--first-bar-key", "SPACE"], "add a fight step"),
    (["--first-bar-key", "QQ"], "SPACE or one letter"),
])
def test_main_blocks_a_first_bar_key_it_cannot_press(tmp_path, monkeypatch, capsys,
                                                      extra, error):
    def claimed(*a, **k):
        raise AssertionError("an emulator slot was claimed")

    monkeypatch.setattr(da.dosbox, "claim", claimed)
    monkeypatch.setattr(da.dosboxx, "claim", claimed)
    with pytest.raises(SystemExit):
        da.main(["--title", "ssb", "--save", str(tmp_path), "--steps", "load",
                 "begin", "camp", *extra, "--out", str(tmp_path / "out")])
    assert error in capsys.readouterr().err


def test_a_fight_run_boots_dosbox_x_and_a_run_without_one_does_not(monkeypatch,
                                                                  tmp_path):
    log = _fake_run(monkeypatch, tmp_path, menu_error=TimeoutError("x"))
    x_log: list[str] = []

    def x_claim(note=""):
        x_log.append("x-claim")
        return _Slot(x_log)

    monkeypatch.setattr(da.dosboxx, "claim", x_claim)
    monkeypatch.setattr(da.dosboxx, "XSession",
                        lambda slot, game: _Session(tmp_path, x_log))
    args = _run_args(tmp_path, ["load", "begin", "fight"])
    args.title = "ssb"
    da.run(args)
    assert x_log[0] == "x-claim" and "claim" not in log
    x_log.clear()
    args = _run_args(tmp_path, ["load", "begin", "walk 1"])
    args.title = "ssb"
    da.run(args)
    assert x_log == [] and log[0] == "claim"


@pytest.mark.parametrize("walk", ["walk MI", "turn 2"])
def test_a_pool_walk_run_boots_dosbox_x_for_the_memory_square(monkeypatch,
                                                             tmp_path, walk):
    log = _fake_run(monkeypatch, tmp_path, menu_error=TimeoutError("x"))
    x_log: list[str] = []

    def x_claim(note=""):
        x_log.append("x-claim")
        return _Slot(x_log)

    monkeypatch.setattr(da.dosboxx, "claim", x_claim)
    monkeypatch.setattr(da.dosboxx, "XSession",
                        lambda slot, game: _Session(tmp_path, x_log))
    args = _run_args(tmp_path, ["load", walk])
    args.title = "pool"
    da.run(args)
    assert x_log[0] == "x-claim" and "claim" not in log


# The Silver Blades layout, and a fight held in fake memory.
_DS = 0x1F00


def _ssb():
    """The Silver Blades layout, looked up when a test runs rather than at import."""
    return da.COMBAT_LAYOUTS["ssb"]


def _record_size() -> int:
    return max(_ssb().hp_at, _ssb().next_at + 3) + 1


def _record(name: str, side: int, quick: int, control: int, hp: int,
            after: tuple[int, int] = (0, 0)) -> bytearray:
    rec = bytearray(_record_size())
    rec[0] = len(name)
    rec[1:1 + len(name)] = name.encode()
    rec[_ssb().status_at:_ssb().status_at + 4] = bytes((0, 1, side, quick))
    rec[_ssb().control_at] = control
    rec[_ssb().hp_at] = hp
    seg, off = after
    rec[_ssb().next_at:_ssb().next_at + 4] = (off.to_bytes(2, "little")
                                          + seg.to_bytes(2, "little"))
    return rec


def _fight_memory() -> tuple[bytearray, dict]:
    """Three party members and one monster: GUY and PAINE the player's,
    EPONA under the computer (control 0xB3, quickfight 1), an ORC on side 1.
    The list from the party head runs on into the ORC, as the game's does."""
    ptrs = {"GUY": (0x3000, 0x10), "PAINE": (0x3000, 0x200),
            "EPONA": (0x3000, 0x400), "ORC": (0x3100, 0x10)}
    records = {
        ptrs["GUY"]: _record("GUY", 0, 0, 0, 30, ptrs["PAINE"]),
        ptrs["PAINE"]: _record("PAINE", 0, 1, 0, 25, ptrs["EPONA"]),
        ptrs["EPONA"]: _record("EPONA", 0, 1, 0xB3, 20, ptrs["ORC"]),
        ptrs["ORC"]: _record("ORC", 1, 1, 0xB2, 8),
    }
    ds = bytearray(0x10000)
    order = ("GUY", "PAINE", "EPONA", "ORC")
    # One more than the count, as the game's setup leaves it.
    ds[_ssb().map_at + 3] = len(order) + 1
    for i, who in enumerate(order, 1):
        x, y = (5 + i, 7) if who != "ORC" else (6, 2)
        ds[_ssb().map_at + 4 * i:_ssb().map_at + 4 * i + 4] = bytes((x, y, i, 1))
        seg, off = ptrs[who]
        ds[_ssb().array_at + 4 * i:_ssb().array_at + 4 * i + 4] = (
            off.to_bytes(2, "little") + seg.to_bytes(2, "little"))
    seg, off = ptrs["GUY"]
    ds[_ssb().party_at:_ssb().party_at + 4] = off.to_bytes(2, "little") + seg.to_bytes(2, "little")
    return ds, {"records": records, "ptrs": ptrs}


def _select(ds: bytearray, ptr: tuple[int, int]) -> None:
    seg, off = ptr
    ds[_ssb().selected_at:_ssb().selected_at + 4] = (off.to_bytes(2, "little")
                                                 + seg.to_bytes(2, "little"))


def test_the_combat_window_reads_every_combatant_and_who_is_selected():
    ds, mem = _fight_memory()
    _select(ds, mem["ptrs"]["PAINE"])
    lo, n = da.combat_window(_ssb())
    got = da.read_combat(bytes(ds[lo:lo + n]), lo, _ssb())
    assert got["count"] == 4 and got["selected"] == 2
    assert [c["position"] for c in got["combatants"]] == [[6, 7], [7, 7], [8, 7], [6, 2]]
    assert got["party_head"] == [0x3000, 0x10]
    orc = da.combatant_record(bytes(mem["records"][mem["ptrs"]["ORC"]]), _ssb())
    assert (orc["name"], orc["side"], orc["quickfight"], orc["control"], orc["hp"]) \
        == ("ORC", 1, 1, 0xB2, 8)


def test_a_window_that_is_not_a_fight_is_blocked():
    lo, n = da.combat_window(_ssb())
    with pytest.raises(da.CombatUnread, match="count is 0"):
        da.read_combat(bytes(n), lo, _ssb())
    ds, _ = _fight_memory()
    ds[_ssb().array_at + 8:_ssb().array_at + 12] = bytes(4)
    with pytest.raises(da.CombatUnread, match="no record"):
        da.read_combat(bytes(ds[lo:lo + n]), lo, _ssb())
    odd = da.combatant_record(bytes(_record_size()), _ssb())
    assert odd["name"] is None and odd["raw_name"] == "00" * 16


#: The Silver Blades fight in New Verdigris as a debugger read it at the
#: first command bar (`DS` 1604): each combatant's name, square, record
#: pointer, side, quickfight, control and hit points, in map order.  Six
#: party members, six townsmen fighting beside them, and six monsters.
_VERDIGRIS = (
    ("Guy de Valois", 27, 13, (0x5E98, 0x0E), 0, 0, 0x00, 95),
    ("PAINE", 28, 13, (0x5EEA, 0x0C), 0, 0, 0x00, 74),
    ("EPONA", 26, 13, (0x6027, 0x06), 0, 0, 0x00, 91),
    ("MALACHITE", 29, 13, (0x6042, 0x0D), 0, 1, 0xB3, 58),
    ("DOMINIC", 25, 13, (0x605E, 0x04), 0, 0, 0x00, 78),
    ("MORGAINE", 30, 13, (0x6079, 0x0B), 0, 0, 0x00, 35),
    ("TOWNSMAN", 28, 14, (0x6713, 0x0E), 0, 1, 0xB2, 24),
    ("TOWNSMAN", 29, 14, (0x67B0, 0x09), 0, 1, 0xB2, 24),
    ("TOWNSMAN", 27, 14, (0x67D4, 0x06), 0, 1, 0xB2, 24),
    ("TOWNSMAN", 30, 14, (0x63C6, 0x02), 0, 1, 0xB2, 24),
    ("TOWNSMAN", 26, 14, (0x63E1, 0x09), 0, 1, 0xB2, 24),
    ("TOWNSMAN", 31, 14, (0x63FD, 0x00), 0, 1, 0xB2, 24),
    ("BC LORD", 27, 12, (0x6418, 0x07), 1, 1, 0x80, 78),
    ("MEDUSA", 26, 12, (0x653D, 0x02), 1, 1, 0x80, 27),
    ("MEDUSA", 28, 12, (0x68FA, 0x0B), 1, 1, 0x80, 27),
    ("MEDUSA", 26, 11, (0x6916, 0x02), 1, 1, 0x80, 27),
    ("MEDUSA", 25, 11, (0x6931, 0x09), 1, 1, 0x80, 27),
    ("MEDUSA", 27, 11, (0x694D, 0x00), 1, 1, 0x80, 27),
)


def _verdigris(game: "FakeFight") -> None:
    """Put the New Verdigris fight in a fake session's memory.

    Entry 0's fourth byte held 0x13, one more than the 18 combatants, and
    entry 19 was all zeros; the list from the party head ran through all 18
    in map order; the selected pointer was MORGAINE's.
    """
    game.ds[:] = bytes(len(game.ds))
    game.records = {}
    ptrs = [row[3] for row in _VERDIGRIS]
    for i, (name, x, y, ptr, side, quick, control, hp) in enumerate(_VERDIGRIS, 1):
        after = ptrs[i] if i < len(ptrs) else (0, 0)
        game.records[ptr] = _record(name, side, quick, control, hp, after)
        at = _ssb().map_at + 4 * i
        game.ds[at:at + 4] = bytes((x, y, i, 1))
        seg, off = ptr
        at = _ssb().array_at + 4 * i
        game.ds[at:at + 4] = off.to_bytes(2, "little") + seg.to_bytes(2, "little")
    game.ds[_ssb().map_at + 3] = 0x13
    seg, off = ptrs[0]
    game.ds[_ssb().party_at:_ssb().party_at + 4] = (off.to_bytes(2, "little")
                                                   + seg.to_bytes(2, "little"))
    _select(game.ds, ptrs[5])


def test_the_new_verdigris_fight_reads_as_its_eighteen_combatants(tmp_path):
    game, d = _fighter(tmp_path)
    d.party_size = 6
    game.state = "bar1"
    _verdigris(game)
    snap = d.combat_memory(True, {})
    assert snap["count"] == 18 and snap["selected"] == 6 and game.halts == 1
    got = [(c["name"], *c["position"], c["side"], c["control"], c["hp"])
           for c in snap["combatants"]]
    assert got == [(n, x, y, side, control, hp)
                   for n, x, y, _, side, _, control, hp in _VERDIGRIS]
    # The six members are the party, in their order; the townsmen after
    # them in the same list fight on the party's side but are not in it.
    assert [c["slot"] for c in snap["combatants"]] == [0, 1, 2, 3, 4, 5] + [None] * 12
    assert [c["party"] for c in snap["combatants"]] == [True] * 6 + [False] * 12


def test_the_explorer_leaves_a_dead_end_for_a_square_it_has_not_stood_on():
    # A corridor A - B - C, walls everywhere else; the walk starts at A
    # facing B and must end at C, never turning back while C is untried.
    grid = {("A", 0): "B", ("B", 0): "C", ("B", 2): "A", ("C", 2): "B"}
    walker = da.Explorer()
    walker.at("A")
    for _ in range(40):
        d = walker.choose()
        for k in walker.turn_keys(d):
            walker.turned(k)
        walker.stepped(grid.get((walker.square, walker.facing), walker.square))
        if walker.square == "C":
            break
    assert walker.square == "C"
    assert walker.steps == 2


class FakeFight:
    """A Silver Blades session from the map to a fight's end, with memory.

    `m` opens move mode; `Up` steps twice and walks into an encounter; `c`
    starts the fight at GUY's command bar; `space` there clears the
    quickfight byte of every party member whose control is below 0x80, as
    the menu's handler does, and leaves the bar showing; `q` moves on to
    PAINE's bar and then to the treasure; `e` and `n` return to the map.
    """

    FRAMES = {"map": "MOVE AREA CAST VIEW ENCAMP SEARCH LOOK", "move": "EXIT",
              "encounter": "COMBAT WAIT FLEE ADVANCE",
              "bar": "MOVE VIEW AIM USE CAST QUICK DONE",
              "treasure": "VIEW TAKE POOL SHARE EXIT", "left": "YES NO",
              "archway": "YES NO", "blank1": "",
              "lost": "PRESS ANY KEY TO CONTINUE",
              # The colon between the words is drawn as one more cell.
              "confirm": "CONTINUE BATTLEHYES NO"}

    def __init__(self, tmp_path, archway=False, endless=False, odd=False,
                 swallow=False):
        #: With `archway`, the first step lands on square 5 under a `YES NO`
        #: question whose picture animates, so every `capture` of it tears.
        #: With `endless` every step moves and none meets a fight; with `odd`
        #: the first step shows a bar nobody classifies, drawn differently on
        #: every look; with `swallow` the first `q` at GUY's bar is lost.
        self.archway, self.endless, self.odd, self.swallow = archway, endless, odd, swallow
        #: With `twice`, GUY's first `QUICK` is followed by a monster's turn
        #: (a blank bar) and then GUY's own bar again: a second turn.
        self.twice = False
        #: Whether Alt+X at a command bar ends the fight (the game took the
        #: cheat); with `lose`, `q` at GUY's bar ends it in a defeat, whose
        #: first text row is drawn only with `line`.
        self.cheat, self.lose, self.line = True, False, True
        #: With `prompt`, the cheat's end of the fight asks `CONTINUE BATTLE`
        #: first, and only `n` gets past it.
        self.prompt = False
        self.looks = 0
        self.fought = False
        self.map_after = 0
        #: With `flicker` N, the N-th look at the map after the fight shows
        #: the `YES NO` question again instead.
        self.flicker = 0
        self.dses: list[int] = []
        self.dir = tmp_path / "session"
        (self.dir / "shots").mkdir(parents=True)
        self.save_dir = self.dir / "SAVE"
        self.state, self.square, self.actor = "map", 1, None
        self.keys: list[str] = []
        self.halts = 0
        self.ds, mem = _fight_memory()
        self.records, self.ptrs = mem["records"], mem["ptrs"]

    def frame(self) -> dosbox.Screen:
        if self.state == "odd":
            self.looks += 1
            bar = bytes((self.looks % 250 + 1, 0x03, 0x05, 0x09))
        else:
            bar = _bar(self.FRAMES["bar" if self.state.startswith("bar") else self.state])
        screen = _screen(bar, b"")
        if self.state == "lost" and self.line:
            px = bytearray(screen.px)
            x, y, w, h = da.PARTY_DESTROYED_LINE
            for dy in range(h):
                for dx in range(0, w, 3):
                    at = ((y + dy) * W + x + dx) * 3
                    px[at:at + 3] = b"\xff\xff\xff"
            screen = dosbox.Screen(W, H, bytes(px))
        if self.state in ("map", "move"):
            px = bytearray(screen.px)
            col = da.status_column("ssb")
            y0 = dosbox.STATUS[1]
            for dy in range(8):
                for dx in range(8):
                    if (self.square >> ((dx + dy) % 8)) & 1:
                        at = ((y0 + dy) * W + col + dx) * 3
                        px[at:at + 3] = b"\xff\xff\xff"
            screen = dosbox.Screen(W, H, bytes(px))
        return screen

    def capture(self):
        if self.state == "archway":
            raise da.dosboxx.NotLineDoubled("block at (80,100) is not one pixel")
        if self.state == "map" and self.fought:
            self.map_after += 1
            if self.map_after == self.flicker:
                # The question comes back once, after the map showed briefly.
                self.state, self.flicker = "left", 0
        if self.state == "blank1":
            # One look at a monster's turn, and GUY's bar is back.
            frame = self.frame()
            self.state = "bar1"
            return frame
        return self.frame()

    def grab(self):
        return self.frame()

    def settle(self, quiet=0.6, timeout=30.0):
        return self.frame()

    def wait_for(self, pred, timeout=30.0):
        return pred(self.frame())

    def wait_until_ink(self, rect, want, timeout=30.0):
        return self.frame().ink(rect) == want

    def wait_while_ink(self, rect, same, timeout=30.0):
        return self.frame().ink(rect) != same

    def wait_while_glyphs(self, rect, same, timeout=30.0):
        return self.frame().glyphs(rect) != same

    def shot(self, name, allow_blank=False):
        path = self.dir / "shots" / f"{name}.png"
        path.write_bytes(b"x")
        return path

    def key(self, *keys, gap=0.35):
        for k in keys:
            self.keys.append(k)
            s = self.state
            if s == "map" and k == "m":
                self.state = "move"
            elif s == "move" and k == "Up" and self.endless:
                self.square = 4 - self.square
            elif s == "move" and k == "Up" and self.odd:
                self.state = "odd"
            elif s == "move" and k == "Up":
                if self.square == 1 and self.archway:
                    self.square, self.state = 5, "archway"
                elif self.square == 1:
                    self.square = 3
                else:
                    self.state = "encounter"
            elif s == "archway" and k == "n":
                self.state = "move"
            elif s == "encounter" and k == "c":
                self.state, self.actor, self.fought = "bar1", "GUY", True
            elif s.startswith("bar") and k == "alt+x":
                if self.cheat:
                    self.state = "confirm" if self.prompt else "treasure"
            elif s == "confirm" and k == "n":
                self.state = "treasure"
            elif s == "bar1" and k == "q" and self.lose:
                self.state = "lost"
            elif s == "bar1" and k == "q" and self.swallow:
                self.swallow = False
            elif s == "bar1" and k == "q" and self.twice:
                self.state, self.twice = "blank1", False
            elif s.startswith("bar") and k == "space":
                for rec in self.records.values():
                    if rec[_ssb().control_at] < 0x80 and rec[_ssb().status_at + 2] == 0:
                        rec[_ssb().status_at + 3] = 0
            elif s == "bar1" and k == "q":
                self.state, self.actor = "bar2", "PAINE"
            elif s == "bar2" and k == "q":
                self.state = "treasure"
            elif s == "treasure" and k == "e":
                self.state = "left"
            elif s == "left" and k == "n":
                self.state = "map"
            if self.actor:
                _select(self.ds, self.ptrs[self.actor])

    # -- the debugger ------------------------------------------------------

    def attach(self):
        self.halts += 1
        return True

    def regs(self, *names):
        return {"DS": _DS}

    def read(self, addr, n):
        seg, off = addr
        self.dses.append(seg)
        if seg == _DS:
            return bytes(self.ds[off:off + n])
        if (seg, off) not in self.records:
            # The debugger's answer to a dump it could not take.
            raise da.dosboxx.NotHalted(f"MEMDUMPBIN {seg:04X}:{off:04X} answered ''")
        return bytes(self.records[(seg, off)][:n])

    def run(self):
        pass


@pytest.fixture
def fight_now(monkeypatch):
    monkeypatch.setattr(da, "FIGHT_SETTLED", 0.0)


def _fighter(tmp_path, key=None, archway=False, intervene=False):
    game = FakeFight(tmp_path, archway)
    d = da.Driver(game, lambda **k: None, "D", "ssb", party_size=3)
    d.logged = []
    d.note = lambda **k: d.logged.append(k)
    d.record_world(game.capture())
    d.where = "map"
    d.first_bar_key = key
    d.intervene = intervene
    return game, d


def _events(d, name):
    return [e for e in d.logged if e.get("event") == name]


def test_a_fight_logs_placement_and_who_acts_at_each_bar_and_ends_on_the_map(
        tmp_path, fight_now):
    game, d = _fighter(tmp_path)
    got = d.fight()
    assert d.where == "map" and game.state == "map"
    assert game.keys == ["m", "Up", "Up", "c", "q", "q", "e", "n"]
    assert [e["actor"]["name"] for e in _events(d, "bar")] == ["GUY", "PAINE"]
    placement = _events(d, "placement")
    assert len(placement) == 1
    rows = {c["name"]: c for c in placement[0]["combatants"]}
    assert (rows["EPONA"]["side"], rows["EPONA"]["control"],
            rows["EPONA"]["quickfight"], rows["EPONA"]["slot"]) == (0, 0xB3, 1, 2)
    assert (rows["ORC"]["side"], rows["ORC"]["party"], rows["ORC"]["slot"],
            rows["ORC"]["position"]) == (1, False, None, [6, 2])
    assert rows["GUY"]["position"] == [6, 7] and rows["GUY"]["party"]
    assert _events(d, "first-bar-key") == []
    assert (got["bars"], got["walked"], got["walked_before_fight"],
            got["encounters"]) == (2, 1, 1, 1)
    assert got["first_bar_key"] is None and got["ds"] == f"{_DS:04X}"


def test_the_first_bar_key_is_pressed_once_and_the_bar_after_it_reads_every_record(
        tmp_path, fight_now):
    game, d = _fighter(tmp_path, key="space")
    got = d.fight()
    assert game.keys == ["m", "Up", "Up", "c", "space", "q", "q", "e", "n"]
    assert game.keys.count("space") == 1
    assert [e["actor"]["name"] for e in _events(d, "bar")] == ["GUY", "GUY", "PAINE"]
    assert [e["key"] for e in _events(d, "first-bar-key")] == ["space"]
    before = {c["name"]: c["quickfight"] for c in _events(d, "placement")[0]["combatants"]}
    after = {c["name"]: c["quickfight"]
             for c in _events(d, "after-first-bar-key")[0]["combatants"]}
    # PAINE (control 0) is handed back; EPONA (0xB3) and the ORC are not.
    assert before == {"GUY": 0, "PAINE": 1, "EPONA": 1, "ORC": 1}
    assert after == {"GUY": 0, "PAINE": 0, "EPONA": 1, "ORC": 1}
    assert got["first_bar_key"] == "space" and got["bars"] == 3


def test_a_fight_needs_the_debugger_and_the_map(tmp_path, monkeypatch):
    game, d = _fighter(tmp_path)
    d.where = "camp"
    with pytest.raises(da.StepFailed, match="needs the map"):
        d.fight()
    d.where = "map"
    monkeypatch.delattr(FakeFight, "attach")
    with pytest.raises(da.StepFailed, match="DOSBox-X debugger"):
        d.fight()


def test_a_fight_whose_combatants_never_read_true_stops_the_run(tmp_path, fight_now):
    game, d = _fighter(tmp_path)
    game.ds[_ssb().map_at + 3] = 0
    with pytest.raises(da.StepFailed, match="never read as a fight"):
        d.fight()
    assert game.halts == da.FIGHT_PRESSES


def test_a_torn_frame_during_the_walk_is_read_again_not_a_lost_run(tmp_path, fight_now):
    game, d = _fighter(tmp_path)
    real = game.capture
    torn = []

    def capture():
        if game.state == "move" and not torn:
            torn.append(1)
            raise da.dosboxx.NotLineDoubled("block at (0,0) is not one pixel")
        return real()

    game.capture = capture
    game.grab = lambda: None
    got = d.fight()
    assert torn and got["torn_frames"] == 1
    assert [e["actor"]["name"] for e in _events(d, "bar")] == ["GUY", "PAINE"]


def test_a_question_under_an_animated_picture_is_answered_through_torn_grabs(
        tmp_path, fight_now):
    game, d = _fighter(tmp_path, archway=True)
    got = d.fight()
    assert game.keys == ["m", "Up", "n", "Up", "c", "q", "q", "e", "n"]
    assert got["loose_frames"] >= 1
    assert got["walked"] == 1 and got["walked_before_fight"] == 1


def test_a_step_that_showed_a_question_records_where_it_led():
    walker = da.Explorer()
    walker.at("A")
    walker.stepping()
    walker.square = None           # the step's bar did not come back
    walker.at("B")                 # read again once the question was answered
    assert walker.edges[("A", 0)] == "B" and walker.steps == 1
    walker.stepping()
    walker.square = None
    walker.at("B")                 # a question that left the party where it stood
    assert walker.edges[("B", 0)] == da.Explorer.BLOCKED
    assert walker.choose() != 0


def test_a_torn_dosbox_x_grab_halves_loosely_to_the_frame_it_doubled():
    small = _screen(_bar("YES NO"), bytes(range(200)))
    row = bytearray()
    for y in range(H):
        line = bytearray()
        for x in range(W):
            line += small.px[(y * W + x) * 3:(y * W + x) * 3 + 3] * 2
        row += line + line
    torn = bytearray(row)
    # The second line of one pair, in the picture, from a later blit.
    at = (2 * 50 + 1) * W * 2 * 3 + 80 * 2 * 3
    torn[at:at + 6] = b"\x55\xff\x55" * 2
    big = dosbox.Screen(2 * W, 2 * H, bytes(torn))
    with pytest.raises(da.dosboxx.NotLineDoubled):
        da.dosboxx.halve(big)
    assert da.loose_halve(big).px == small.px
    assert da.loose_halve(small) is small


@pytest.fixture
def clock(monkeypatch):
    """A clock that moves a second each time the step reads it."""
    now = [1000.0]

    def tick():
        now[0] += 1.0
        return now[0]

    monkeypatch.setattr(da.time, "time", tick)


def test_a_monster_record_with_no_name_still_reaches_the_first_bar(tmp_path, fight_now):
    game, d = _fighter(tmp_path)
    orc = game.records[game.ptrs["ORC"]]
    orc[0:4] = b"\x1f\x01\xfe\x00"
    got = d.fight()
    rows = {c["index"]: c for c in _events(d, "placement")[0]["combatants"]}
    assert rows[4]["name"] is None and rows[4]["raw_name"].startswith("1f01fe00")
    assert rows[4]["side"] == 1
    assert [e["pointer"] for e in _events(d, "fight-odd-record")] == [[0x3100, 0x10]]
    assert got["bars"] == 2


def test_a_wrong_cached_ds_is_dropped_and_the_halt_reads_it_afresh(tmp_path):
    game, d = _fighter(tmp_path)
    game.state = "bar1"
    _select(game.ds, game.ptrs["GUY"])
    d.combat_ds = 0xBEEF
    snap = d.combat_memory(True, {})
    assert snap["ds"] == _DS and d.combat_ds == _DS
    assert game.halts == 2 and game.dses[0] == 0xBEEF


def test_a_ds_that_never_reads_as_a_fight_is_named_when_the_run_stops(tmp_path,
                                                                    monkeypatch):
    game, d = _fighter(tmp_path)
    game.state = "bar1"
    monkeypatch.setattr(game, "regs", lambda *n: {"DS": 0xBEEF})
    with pytest.raises(da.StepFailed, match="DS BEEF: NotHalted"):
        d.combat_memory(True, {})
    assert game.halts == da.FIGHT_PRESSES


def test_a_walk_that_never_meets_a_fight_ends_at_the_budget(tmp_path, clock):
    game, d = _fighter(tmp_path)
    game.endless = True
    with pytest.raises(da.StepFailed, match=r"no fight in 30 s: \d+ steps"):
        d.fight(30)
    assert game.keys.count("Up") > 1 and "c" not in game.keys


def test_a_bar_nobody_classifies_stops_the_run_after_the_patience(tmp_path, clock):
    game, d = _fighter(tmp_path)
    game.odd = True
    with pytest.raises(da.StepFailed, match=f"stayed {da.FIGHT_PATIENCE:.0f} s"):
        d.fight(600)
    assert game.looks > da.FIGHT_PATIENCE / 4
    # A new unclassified digest on every look, and only the first few shot.
    unknown = [e for e in _events(d, "fight-screen") if e["kind"] is None]
    assert len(unknown) > da.FIGHT_UNKNOWN_SHOTS
    assert sum(e["shot"] is not None for e in unknown) == da.FIGHT_UNKNOWN_SHOTS


def test_the_step_waits_for_the_map_bar_to_hold_after_the_fight(tmp_path, clock):
    game, d = _fighter(tmp_path)
    game.flicker = 3
    d.fight()
    # The map showed for less than FIGHT_SETTLED before the question came
    # back, so the step answered it again rather than ending at the map.
    assert game.keys[-3:] == ["e", "n", "n"] and game.state == "map"


def test_a_walled_in_walk_stops_the_run():
    walker = da.Explorer()
    walker.at("A")
    for d in range(4):
        walker.edges[("A", d)] = da.Explorer.BLOCKED
    with pytest.raises(da.StepFailed, match="walled in"):
        walker.choose()


def test_a_quick_the_game_did_not_take_is_pressed_again_and_logged_once(
        tmp_path, fight_now):
    game, d = _fighter(tmp_path)
    game.swallow = True
    got = d.fight()
    assert [e["actor"]["name"] for e in _events(d, "bar")] == ["GUY", "PAINE"]
    assert got["repeated_bars"] == 1
    assert game.keys == ["m", "Up", "Up", "c", "q", "q", "q", "e", "n"]


def test_y_is_blocked_as_the_first_bar_key():
    for key in ("y", "Y"):
        with pytest.raises(ValueError, match="YES"):
            da.parse_key(key)


def test_a_window_with_no_named_record_is_not_a_fight(tmp_path):
    game, d = _fighter(tmp_path)
    game.state = "bar1"
    _select(game.ds, game.ptrs["GUY"])
    for rec in game.records.values():
        rec[0:3] = b"\x1f\x01\xfe"
    with pytest.raises(da.StepFailed,
                       match="DS 1F00: CombatUnread: no combatant's record holds a name"):
        d.combat_memory(True, {})
    assert game.halts == da.FIGHT_PRESSES and d.combat_ds is None
    assert _events(d, "fight-odd-record") == []


def test_a_window_with_no_party_member_and_no_one_acting_is_not_a_fight(tmp_path):
    game, d = _fighter(tmp_path)
    game.state = "bar1"
    _select(game.ds, (0x5555, 0x5555))
    game.ds[_ssb().party_at:_ssb().party_at + 4] = bytes(4)
    known: dict = {}
    with pytest.raises(da.StepFailed, match="none is the one acting"):
        d.combat_memory(True, known)
    assert known == {}


def test_a_member_acting_again_after_a_monsters_turn_is_a_new_bar(tmp_path, fight_now):
    game, d = _fighter(tmp_path)
    game.twice = True
    got = d.fight()
    assert [e["actor"]["name"] for e in _events(d, "bar")] == ["GUY", "GUY", "PAINE"]
    assert got["repeated_bars"] == 0
    assert game.keys == ["m", "Up", "Up", "c", "q", "q", "q", "e", "n"]


# -- --stage-var: a script-variable word of SAVGAM -----------------------------

_SSB_SPECIMEN = "WISH-SPEC-ssb-299-whole-engine-resave"


def _ssb_specimen():
    from tools.registry import specimens
    folder = specimens.tree_root() / "por-dos" / _SSB_SPECIMEN
    if not folder.is_dir():
        pytest.skip(f"needs {_SSB_SPECIMEN}")
    return folder


def _ssb_copy(tmp_path):
    import shutil
    dest = tmp_path / "save"
    shutil.copytree(_ssb_specimen(), dest)
    for f in dest.iterdir():
        f.chmod(0o644)
    return dest


def _synthetic_ssb_save(tmp_path):
    (tmp_path / "SAVGAMD.DAT").write_bytes(bytes(5469))
    (tmp_path / "CHRDATD1.SAV").write_bytes(b"record one")
    (tmp_path / "CHRDATD2.SAV").write_bytes(b"record two")
    (tmp_path / "CHRDATD2.SFX").write_bytes(b"effects")
    return {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_stage_var_changes_exactly_the_named_word(tmp_path):
    from goldbox import dos_savegame
    source = _synthetic_ssb_save(tmp_path)
    got = staging.stage_var(tmp_path, "D", 0x4C2D, 1)
    assert got["offset"] == "0x25b" and (got["before"], got["after"]) == ("0000", "0100")
    after = (tmp_path / "SAVGAMD.DAT").read_bytes()
    assert len(after) == 5469
    assert [i for i in range(5469) if after[i] != source["SAVGAMD.DAT"][i]] == [0x25B]
    container = dos_savegame.container_for(5469)
    assert dos_savegame.word(after, dos_savegame.pool_address(0x4C2D, container),
                             container) == 1
    for name, data in source.items():
        if name != "SAVGAMD.DAT":
            assert (tmp_path / name).read_bytes() == data


def test_stage_var_on_the_specimen_touches_only_the_gate_word(tmp_path):
    save = _ssb_copy(tmp_path)
    before = {p.name: p.read_bytes() for p in save.iterdir()}
    staging.stage_var(save, "D", 0x4C2D, 1)
    for p in save.iterdir():
        if p.name == "SAVGAMD.DAT":
            diff = [i for i, (a, b) in enumerate(zip(before[p.name], p.read_bytes()))
                    if a != b]
            assert diff and set(diff) <= {0x25B, 0x25C}
        else:
            assert p.read_bytes() == before[p.name]


@pytest.mark.parametrize("bad", ["4C2D", "4C2D=", "=1", "zz=1", "4C2D=0x10000",
                                 "4C2D=01", "4C2D=-1", "12345=1"])
def test_a_bad_stage_var_line_is_blocked(bad):
    with pytest.raises(ValueError):
        da.parse_var(bad)


def test_a_stage_var_line_parses_hex_addresses_and_values():
    assert da.parse_var("4C2D=1") == (0x4C2D, 1)
    assert da.parse_var("$4c2d=0xFF") == (0x4C2D, 255)
    assert da.parse_var("0x4C2D=65535") == (0x4C2D, 65535)


def test_stage_var_blocks_an_address_outside_the_array_and_a_bad_value(tmp_path):
    from goldbox import dos_savegame
    _synthetic_ssb_save(tmp_path)
    with pytest.raises(dos_savegame.DosSaveError):
        staging.stage_var(tmp_path, "D", 0x1000, 1)
    with pytest.raises(ValueError, match="one word"):
        staging.stage_var(tmp_path, "D", 0x4C2D, 0x10000)
    assert (tmp_path / "SAVGAMD.DAT").read_bytes() == bytes(5469)


def test_stage_var_outside_the_pools_of_darkness_array_is_blocked_before_a_slot_is_claimed(
        monkeypatch, tmp_path):
    log, args = _staged_run(monkeypatch, tmp_path, stage_var=["4C2D=1"])
    saves = tmp_path / "saves"
    (saves / "SAVGAMA.DAT").unlink()
    (saves / "SAVGAMA.PTY").write_bytes(bytes(1364))
    args.title = "darkness"
    with pytest.raises(ValueError, match="outside the 1024"):
        da.check_staging(args, saves, "A")
    with pytest.raises(ValueError, match="outside the 1024"):
        da.run(args)
    assert "claim" not in log
    (saves / "SAVGAMA.PTY").unlink()
    args.stage_var = ["A2=0"]
    with pytest.raises(ValueError, match="--stage-var needs a SAVGAMA.PTY"):
        da.check_staging(args, saves, "A")


def test_the_command_line_wires_stage_var_after_stage_record(tmp_path):
    _synthetic_ssb_save(tmp_path)
    args = _run_args(tmp_path, [])
    args.stage_record = []
    args.stage_var = ["4C2D=1"]
    done = da.stage(tmp_path, "D", args)
    assert [d["stage"] for d in done] == ["var"]
    assert (tmp_path / "SAVGAMD.DAT").read_bytes()[0x25B] == 1


def test_main_blocks_a_bad_stage_var_before_a_slot_is_claimed(tmp_path, monkeypatch, capsys):
    def claimed(*a, **k):
        raise AssertionError("an emulator slot was claimed")

    monkeypatch.setattr(da.dosbox, "claim", claimed)
    with pytest.raises(SystemExit):
        da.main(["--save", str(tmp_path), "--steps", "load", "--stage-var", "4C2D",
                 "--out", str(tmp_path / "out")])
    assert "4C2D" in capsys.readouterr().err


# -- --stage-place: the party's square in an indoor SAVGAM ---------------------

def _synthetic_curse_save(tmp_path, indoors=True):
    from goldbox import dos_savegame
    data = bytearray(13149)
    container = dos_savegame.container_for(13149)
    dos_savegame.put_position(data, 3, 4, 3, container)
    if indoors:
        data[dos_savegame.word_offset(dos_savegame.INDOORS, container)] = 1
    (tmp_path / "SAVGAMC.DAT").write_bytes(bytes(data))
    return bytes(data)


def test_stage_place_changes_exactly_the_square_and_facing(tmp_path):
    from goldbox import dos_savegame
    source = _synthetic_curse_save(tmp_path)
    got = staging.stage_place(tmp_path, "C", 6, 14, 0)
    assert got["before"] == [3, 4, 3] and got["after"] == [6, 14, 0]
    after = (tmp_path / "SAVGAMC.DAT").read_bytes()
    c = dos_savegame.container_for(13149)
    assert [i for i in range(len(after)) if after[i] != source[i]] == sorted(
        {c.pos_x, c.pos_y, c.pos_facing})
    assert (after[c.pos_x], after[c.pos_y], after[c.pos_facing]) == (
        6, 14, 0 * dos_savegame.FACING_SCALE)
    staging.stage_place(tmp_path, "C", 5, 13, 3)
    assert (tmp_path / "SAVGAMC.DAT").read_bytes()[c.pos_facing] == 3 * dos_savegame.FACING_SCALE


@pytest.mark.parametrize("place", [(16, 14, 0), (6, 16, 0), (6, 14, 4), (-1, 14, 0)])
def test_stage_place_blocks_a_square_or_facing_out_of_range(tmp_path, place):
    source = _synthetic_curse_save(tmp_path)
    with pytest.raises(ValueError, match="0 to 15"):
        staging.stage_place(tmp_path, "C", *place)
    assert (tmp_path / "SAVGAMC.DAT").read_bytes() == source


def test_stage_place_blocks_an_outdoor_save(tmp_path):
    source = _synthetic_curse_save(tmp_path, indoors=False)
    with pytest.raises(ValueError, match="outdoors"):
        staging.stage_place(tmp_path, "C", 6, 14, 0)
    assert (tmp_path / "SAVGAMC.DAT").read_bytes() == source


@pytest.mark.parametrize("bad", ["6,14", "6,14,0,1", "6;14;0", "a,14,0", "6,14,4",
                                 "16,14,0", "6,14,-1", "6,014,0", ""])
def test_a_bad_stage_place_is_blocked(bad):
    with pytest.raises(ValueError):
        da.parse_place(bad)


def test_a_stage_place_parses_decimal_and_hex():
    assert da.parse_place("6,14,0") == (6, 14, 0)
    assert da.parse_place(" 0x6 , 0xE,3 ") == (6, 14, 3)


def test_the_command_line_stages_the_place_after_the_var_stages(tmp_path):
    _synthetic_curse_save(tmp_path)
    args = _run_args(tmp_path, [])
    args.stage_record = []
    args.stage_var = []
    args.stage_place = "6,14,0"
    done = da.stage(tmp_path, "C", args)
    assert [d["stage"] for d in done] == ["place"]
    assert done[0]["after"] == [6, 14, 0]


def test_main_blocks_a_bad_stage_place_before_a_slot_is_claimed(tmp_path, monkeypatch, capsys):
    def claimed(*a, **k):
        raise AssertionError("an emulator slot was claimed")

    monkeypatch.setattr(da.dosbox, "claim", claimed)
    with pytest.raises(SystemExit):
        da.main(["--save", str(tmp_path), "--steps", "load", "--stage-place", "6,14",
                 "--out", str(tmp_path / "out")])
    assert "6,14" in capsys.readouterr().err


def test_stage_place_blocks_a_pools_of_darkness_wilderness_save_before_a_slot_is_claimed(
        monkeypatch, tmp_path):
    log, args = _staged_run(monkeypatch, tmp_path, stage_place="6,14,0")
    saves = tmp_path / "saves"
    (saves / "SAVGAMA.DAT").unlink()
    (saves / "SAVGAMA.PTY").write_bytes(bytes(1364))
    args.title = "darkness"
    with pytest.raises(ValueError, match="--stage-place.*wilderness"):
        da.check_staging(args, saves, "A")
    with pytest.raises(ValueError, match="--stage-place.*wilderness"):
        da.run(args)
    assert "claim" not in log
    (saves / "SAVGAMA.PTY").unlink()
    with pytest.raises(ValueError, match="--stage-place needs a SAVGAMA.PTY"):
        da.check_staging(args, saves, "A")


@pytest.mark.parametrize("size, match", [(13149, "outdoors"),
                                            (1234, "known saved-game size")])
def test_stage_place_blocks_an_outdoor_or_unknown_save_before_a_slot_is_claimed(
        monkeypatch, tmp_path, size, match):
    log, args = _staged_run(monkeypatch, tmp_path, stage_place="6,14,0")
    (tmp_path / "saves" / "SAVGAMA.DAT").write_bytes(bytes(size))
    with pytest.raises(ValueError, match=match):
        da.check_staging(args, tmp_path / "saves", "A")
    with pytest.raises(ValueError, match=match):
        da.run(args)
    assert "claim" not in log


def test_a_silver_blades_fight_in_area_16_is_blocked_without_the_gate(
        monkeypatch, tmp_path):
    from goldbox import dos_savegame
    save = _ssb_copy(tmp_path)
    data = (save / "SAVGAMD.DAT").read_bytes()
    assert dos_savegame.current_area(data) == 16
    log = _fake_run(monkeypatch, tmp_path)
    args = _run_args(tmp_path, ["load", "begin", "fight"])
    args.title, args.slot, args.save, args.from_slot = "ssb", "D", str(save), "D"
    with pytest.raises(ValueError, match="--stage-var 4C2D=1"):
        da.check_staging(args, save, "D")
    with pytest.raises(ValueError, match="--stage-var 4C2D=1"):
        da.run(args)
    assert "claim" not in log
    args.stage_var = ["4C2D=1"]
    da.check_staging(args, save, "D")
    args.stage_var = ["4C2D=0"]
    with pytest.raises(ValueError, match="--stage-var 4C2D=1"):
        da.check_staging(args, save, "D")
    args.steps, args.stage_var = ["load", "begin"], []
    da.check_staging(args, save, "D")


def test_read_reports_each_staged_word_as_the_saved_slot_holds_it(tmp_path, monkeypatch):
    _synthetic_ssb_save(tmp_path)
    save = tmp_path / "SAVE"
    save.mkdir()
    (save / "SAVGAME.DAT").write_bytes(bytes(5469))
    staging.stage_var(save, "E", 0x4C2D, 1)
    monkeypatch.setattr(da, "read_slot", lambda *a: {"clock_minutes": 0, "nodes": [], "characters": []})
    got = da.read_step(save, tmp_path / "out", "D", ["E"], [], [], [(0x4C2D, 1)])
    assert got["staged_vars"] == {"4C2D": {"slot": "E", "staged": 1, "saved": 1,
                                           "held": True}}
    assert not any("staged variable" in line for line in da.describe(got))
    (save / "SAVGAME.DAT").write_bytes(bytes(5469))
    got = da.read_step(save, tmp_path / "out", "D", ["E"], [], [], [(0x4C2D, 1)])
    assert got["staged_vars"]["4C2D"]["held"] is False
    assert any("staged variable $4C2D" in line for line in da.describe(got))


def test_the_dos_new_verdigris_script_is_the_c64_one():
    """Area 16's DOS script is `ECL10` on the C64, so the gate `$4C2D` its
    wandering roll reads is a DOS fact and not a C64 one reused here."""
    from automap import paths
    from goldbox import c64_port, dos_savegame
    from tools.c64 import coldread
    disks = paths.tool_disks(c64_port.SECRET_OF_THE_SILVER_BLADES)
    if disks is None:
        pytest.skip("needs the Silver Blades C64 disks")
    try:
        game = dosbox.find_game("SECRET")
    except FileNotFoundError:
        pytest.skip("needs the DOS archives ($FR_ARCHIVES)")
    try:
        c64 = coldread.every_file(c64_port.SECRET_OF_THE_SILVER_BLADES,
                                  str(disks))["ECL10"]
    except SystemExit:
        pytest.skip("needs the Silver Blades C64 disks")
    dos = dos_savegame.dax_block((game / "ECL1.DAX").read_bytes(), 16)
    assert dos[2:] == c64
    assert c64[0x592:0x594] == c64[0x5AE:0x5B0] == bytes((0x2D, 0x4C))


def test_the_prayer_watch_step_parses_its_two_ids_and_takes_49_in_three_titles():
    assert da.parse_step("prayer-watch 49").node == 49
    assert da.parse_step("prayer-watch 35").node == 35
    for bad in ("prayer-watch", "prayer-watch 5", "prayer-watch 49 49", "prayer-watch x"):
        with pytest.raises(ValueError):
            da.parse_step(bad)
    steps = [da.parse_step(s) for s in ("load", "prayer-watch 49", "shot end", "read")]
    da.validate_steps(steps, "pool")
    for title in ("curse", "ssb"):
        later = [da.parse_step(s) for s in ("load", "begin", "prayer-watch 49", "read")]
        da.validate_steps(later, title)
        with pytest.raises(ValueError, match="prayer-watch 35 is driven in pool only"):
            da.validate_steps([da.parse_step(s) for s in
                               ("load", "begin", "prayer-watch 35")], title)
    with pytest.raises(ValueError, match="curse, pool, ssb only, not darkness"):
        da.validate_steps(steps, "darkness")
    with pytest.raises(ValueError, match="needs the map"):
        da.validate_steps([da.parse_step(s) for s in ("load", "camp", "prayer-watch 49")],
                          "pool")
    with pytest.raises(ValueError, match="only press, shot and read"):
        da.validate_steps([da.parse_step(s) for s in
                           ("load", "prayer-watch 49", "camp")], "pool")


def test_a_prayer_watch_run_boots_dosbox_x_and_ends_inconclusive_not_lost(monkeypatch,
                                                                         tmp_path):
    _fake_run(monkeypatch, tmp_path)
    x_log: list[str] = []
    monkeypatch.setattr(da.dosboxx, "claim", lambda note="": _Slot(x_log))
    monkeypatch.setattr(da.dosboxx, "XSession",
                        lambda slot, game: _Session(tmp_path, x_log))
    base = da.Driver

    class Watching(base):
        def load(self):
            return {}

        def prayer_watch(self, node):
            return {"node": node, "conclusive": False,
                    "why": ["no party member carried a node with id 49"]}

    monkeypatch.setattr(da, "Driver", Watching)
    args = _run_args(tmp_path, ["load", "prayer-watch 49"])
    assert da.run(args) == 2
    summary = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert summary["completed"] is False and "lost" not in summary
    assert "id 49" in summary["inconclusive"]

    class Passing(Watching):
        def prayer_watch(self, node):
            return {"node": node, "conclusive": True, "why": []}

    monkeypatch.setattr(da, "Driver", Passing)
    assert da.run(_run_args(tmp_path, ["load", "prayer-watch 49"])) == 0


def test_inconclusive_watch_names_only_the_watches_that_say_so():
    assert da.inconclusive_watch([{"step": "load"}, {"step": "fight", "conclusive": True}]) is None
    said = da.inconclusive_watch([{"step": "prayer-watch 35", "conclusive": False,
                                   "why": ["a", "b"]}])
    assert said == "prayer-watch 35: a; b"


def test_the_prayer_watch_needs_its_title_the_map_and_the_debugger(tmp_path, monkeypatch):
    game, d = _fighter(tmp_path)
    with pytest.raises(da.StepFailed) as blocked:
        d.prayer_watch(35)
    assert str(blocked.value) == ("prayer-watch 35 is driven in pool only: id 35 is "
                                  "Prayer's +1 half there, and a ssb Prayer is id 49")
    d.title = da.TITLES["darkness"]
    with pytest.raises(da.StepFailed) as blocked:
        d.prayer_watch(49)
    assert str(blocked.value) == ("prayer-watch is driven in curse, pool, ssb only, "
                                  f"not {d.title.key}")
    d.title = da.TITLES["pool"]
    d.where = "camp"
    with pytest.raises(da.StepFailed, match="needs the map"):
        d.prayer_watch(49)
    d.where = "map"
    monkeypatch.delattr(FakeFight, "attach")
    with pytest.raises(da.StepFailed, match="DOSBox-X debugger"):
        d.prayer_watch(49)


def test_a_prayer_watch_that_fails_mid_fight_still_releases_the_debugger(tmp_path,
                                                                        monkeypatch):
    game, d = _fighter(tmp_path)
    d.title = da.TITLES["pool"]
    d.where = "map"
    d.s.source = tmp_path
    (tmp_path / "START.EXE").write_bytes(b"")
    (tmp_path / "GAME.OVR").write_bytes(b"")
    monkeypatch.setattr(da.unexepack, "unpack", lambda exe: (b"", {}))
    monkeypatch.setattr(da.dosfightwatch, "walk_to_encounter",
                        lambda por, steps: {"met": True})
    calls: list[str] = []

    class Watch:
        def __init__(self, *a, **k):
            pass

        def attach(self):
            calls.append("attach")
            return {}

        def party(self):
            return []

        def stub_load(self):
            return None

        def arm(self):
            calls.append("arm")
            return {"armed": []}

        def run_fight(self, seconds, idle):
            raise da.dosboxx.NotHalted("EV answered nothing")

        def finish(self):
            calls.append("finish")

    monkeypatch.setattr(da.dosfightwatch, "PrayerWatch", Watch)
    monkeypatch.setattr(d, "shot", lambda label: label)
    with pytest.raises(da.StepFailed, match="EV answered nothing"):
        d.prayer_watch(49)
    assert calls == ["attach", "arm", "finish"]
    # Keys were pressed, so the party's place is not known to later steps.
    assert d.where == "pressed"


class _LaterWatch:
    """`dosfightwatch.PrayerWatch` as the step drives it: what it was made
    with, the order of its calls, and a fight `idle` answers to the end."""

    made: list[dict] = []

    def __init__(self, s, ovr, image, note=None, node_id=None, **kw):
        self.calls: list[str] = []
        self.ds = None
        _LaterWatch.made.append({"node_id": node_id, **kw, "watch": self})

    def attach(self):
        self.calls.append(f"attach {self.ds:04X}")
        return {"table_ok": True}

    def party(self):
        return [{"name": "GUY", "side": 0, "nodes": []}]

    def stub_load(self):
        return None

    def arm(self):
        self.calls.append("arm")
        return {"armed": ["stub49"]}

    def run_fight(self, seconds, idle):
        self.calls.append("run")
        for _ in range(20):
            if idle():
                return "fight over"
        return "budget"

    def finish(self):
        self.calls.append("finish")
        return []

    def summary(self, node, at_encounter, at_stop):
        return {"node": node, "conclusive": False, "why": ["x"]}


def test_a_later_prayer_watch_walks_as_fight_does_and_arms_at_the_first_command_bar(
        tmp_path, monkeypatch, fight_now):
    game, d = _fighter(tmp_path)
    d.s.source = tmp_path
    (tmp_path / "START.EXE").write_bytes(b"")
    (tmp_path / "GAME.OVR").write_bytes(b"")
    monkeypatch.setattr(da.unexepack, "unpack", lambda exe: (b"", {}))
    monkeypatch.setattr(da.dosfightwatch, "walk_to_encounter",
                        lambda *a, **k: pytest.fail("Pool's walk"))
    _LaterWatch.made = []
    monkeypatch.setattr(da.dosfightwatch, "PrayerWatch", _LaterWatch)
    monkeypatch.setattr(da.time, "sleep", lambda s: None)
    got = d.prayer_watch(49)
    made = _LaterWatch.made[0]
    assert made["title"] == "ssb" and made["until_penalty"] is True
    assert made["node_id"] == 49
    watch = made["watch"]
    # Armed on the DS the placement read true, after it, and only once.
    assert d.combat_ds == _DS
    assert watch.calls == [f"attach {_DS:04X}", "arm", "run", "finish"]
    events = [e["event"] for e in d.logged]
    assert events.index("placement") < events.index("prayer-table")
    assert events.index("prayer-walk") < events.index("prayer-table")
    party = next(e for e in d.logged if e["event"] == "prayer-party")
    assert party["where"] == "first-bar"
    # The walk and the first bar are fight's own; the rest of the bars are
    # answered by the idle look: QUICK, then the treasure's EXIT and NO.
    assert game.keys == ["m", "Up", "Up", "c", "q", "q", "e", "n"]
    assert got["walk"]["walked"] == 1 and got["walk"]["encounters"] == 1
    assert got["stop"] == "fight over" and d.where == "pressed"
    assert d.fights == 1


def test_a_later_prayer_watch_fails_when_no_fight_comes_in_its_budget(
        tmp_path, monkeypatch):
    game, d = _fighter(tmp_path)
    game.endless = True
    d.s.source = tmp_path
    (tmp_path / "START.EXE").write_bytes(b"")
    (tmp_path / "GAME.OVR").write_bytes(b"")
    monkeypatch.setattr(da.unexepack, "unpack", lambda exe: (b"", {}))
    _LaterWatch.made = []
    monkeypatch.setattr(da.dosfightwatch, "PrayerWatch", _LaterWatch)
    monkeypatch.setattr(da, "FIGHT_SECONDS", 0.2)
    monkeypatch.setattr(d, "shot", lambda label: label)
    with pytest.raises(da.StepFailed, match="no fight in"):
        d.prayer_watch(49)
    assert _LaterWatch.made[0]["watch"].calls == []


def test_a_silver_blades_prayer_watch_in_area_16_is_blocked_without_the_gate(
        monkeypatch, tmp_path):
    save = _ssb_copy(tmp_path)
    _fake_run(monkeypatch, tmp_path)
    args = _run_args(tmp_path, ["load", "begin", "prayer-watch 49"])
    args.title, args.slot, args.save, args.from_slot = "ssb", "D", str(save), "D"
    with pytest.raises(ValueError, match="--stage-var 4C2D=1"):
        da.check_staging(args, save, "D")
    args.stage_var = ["4C2D=1"]
    da.check_staging(args, save, "D")


def test_intervene_boots_silver_blades_with_its_cheat_arguments(monkeypatch, tmp_path):
    _fake_run(monkeypatch, tmp_path, menu_error=TimeoutError("x"))
    made: list[dict] = []
    x_log: list[str] = []
    monkeypatch.setattr(da.dosboxx, "claim", lambda note="": _Slot(x_log))

    def x_session(slot, game, **kw):
        made.append(kw)
        return _Session(tmp_path, x_log)

    monkeypatch.setattr(da.dosboxx, "XSession", x_session)
    for intervene in (True, False):
        args = _run_args(tmp_path, ["load", "begin", "fight"])
        args.title, args.intervene = "ssb", intervene
        da.run(args)
    assert made == [{"exe": "START.EXE X Gem"}, {}]


@pytest.mark.parametrize("steps, emulator", [
    (["load", "snapshot a"], "x"), (["load"], "dosbox")])
def test_pools_of_darkness_starts_with_its_own_batch_file_in_both_emulators(
        monkeypatch, tmp_path, steps, emulator):
    _fake_run(monkeypatch, tmp_path, menu_error=TimeoutError("x"))
    monkeypatch.setattr(da.dospod, "find_game", lambda stem: tmp_path / "game")
    made: list[tuple[str, dict]] = []
    log: list[str] = []

    def session(name):
        def make(slot, game, **kw):
            made.append((name, kw))
            return _Session(tmp_path, log)
        return make

    monkeypatch.setattr(da.dosboxx, "claim", lambda note="": _Slot(log))
    monkeypatch.setattr(da.dossnapshot, "SnapshotSession", session("x"))
    monkeypatch.setattr(dosbox, "Session", session("dosbox"))
    args = _run_args(tmp_path, steps)
    args.title = "darkness"
    da.run(args)
    assert made == [(emulator, {"exe": "START.BAT"})]


def test_launch_args_name_only_a_launcher_other_than_start_exe():
    assert da.launch_args(da.TITLES["pool"]) == {}
    assert da.launch_args(da.TITLES["darkness"]) == {"exe": "START.BAT"}
    assert da.launch_args(da.TITLES["ssb"], intervene=True) == {"exe": "START.EXE X Gem"}


def test_intervene_is_pressed_once_at_the_bar_after_the_first_bar_key(tmp_path, fight_now):
    game, d = _fighter(tmp_path, key="space", intervene=True)
    got = d.fight()
    assert game.keys == ["m", "Up", "Up", "c", "space", "alt+x", "e", "n"]
    assert d.where == "map" and got["intervened"]
    names = [e["event"] for e in d.logged
             if e.get("event") in ("placement", "first-bar-key",
                                   "after-first-bar-key", "intervene")]
    assert names == ["placement", "first-bar-key", "after-first-bar-key", "intervene"]
    assert _events(d, "intervene")[0]["actor"]["name"] == "GUY"


def test_intervene_without_a_first_bar_key_is_pressed_at_the_first_bar(tmp_path, fight_now):
    game, d = _fighter(tmp_path, intervene=True)
    got = d.fight()
    assert game.keys == ["m", "Up", "Up", "c", "alt+x", "e", "n"]
    assert got["intervened"] and len(_events(d, "placement")) == 1
    assert len(_events(d, "intervene")) == 1


def test_a_command_bar_after_intervene_stops_the_run(tmp_path, fight_now):
    game, d = _fighter(tmp_path, intervene=True)
    game.cheat = False
    with pytest.raises(da.StepFailed, match="Alt.X did not end the fight"):
        d.fight()
    assert "q" not in game.keys and game.keys.count("alt+x") == 1


@pytest.mark.parametrize("extra, title, error", [
    ([], "ssb", "add a fight step"),
    (["fight"], "curse", "ssb only"),
    (["fight"], "darkness", "ssb only"),
])
def test_main_blocks_intervene_it_cannot_use(tmp_path, monkeypatch, capsys,
                                              extra, title, error):
    def claimed(*a, **k):
        raise AssertionError("an emulator slot was claimed")

    monkeypatch.setattr(da.dosbox, "claim", claimed)
    monkeypatch.setattr(da.dosboxx, "claim", claimed)
    steps = ["load", "begin", *extra] if title != "darkness" else ["load", "begin"]
    with pytest.raises(SystemExit):
        da.main(["--title", title, "--save", str(tmp_path), "--steps", *steps,
                 "--intervene", "--out", str(tmp_path / "out")])
    err = capsys.readouterr().err
    assert error in err


def test_the_continue_battle_bar_is_known_by_its_letters():
    assert da.continue_battle_words(_words("CONTINUE BATTLEHYES NO"))
    for text in ("CONTINUE BATTLEHYES", "MOVE VIEW AIM USE CAST QUICK DONE",
                 "CONTINUE BATTLEHYES YES", "CONTINUE BATTLEHYNS NO",
                 "CONTINUE BATTLEHYES YO", "CONTINUE BASTLEHYES NO"):
        assert not da.continue_battle_words(_words(text)), text
    screen = _screen(_bar("CONTINUE BATTLEHYES NO"), b"")
    assert da.fight_bar_kind(screen) == "continue_battle"
    assert da.FIGHT_KEYS["continue_battle"] == "n"


def test_the_captured_continue_battle_bar_is_not_the_command_bar():
    prompt = _capture("5713d952cb-f1-dos-won",
                      "016-lost-fight-unknown-40c63b73f7556db4", issue="733")
    assert da.fight_bar_kind(da.loose_halve(prompt)) == "continue_battle"
    command = _capture("5713d952cb-f1-dos-won", "013-first-bar-key", issue="733")
    assert da.fight_bar_kind(da.loose_halve(command)) == "command"


def test_the_silver_blades_treasure_bar_is_known_by_its_letters():
    assert da.treasure_words(_words("VIEW TAKE POOL EXIT"))
    for text in ("VIEW TAKE POOL DONE", "VIEW TAKE POOL EXIT DONE",
                 "VIEW TAKE POLL EXIT", "SAVE VIEW MAGIC EXIT",
                 "VIEW TAKE POOL EXIS"):
        assert not da.treasure_words(_words(text)), text
    assert da.fight_bar_kind(_screen(_bar("VIEW TAKE POOL EXIT"), b"")) == "treasure"
    assert da.FIGHT_KEYS["treasure"] == "e"


def test_the_captured_silver_blades_treasure_bar_is_the_treasure():
    shot = _capture("d7100643cb-f1-dos-won",
                    "017-lost-fight-unknown-943e966bb706d247", issue="733")
    assert da.fight_bar_kind(da.loose_halve(shot)) == "treasure"


def test_no_at_continue_battle_then_the_silver_blades_treasure_is_left_and_the_step_ends(
        tmp_path, fight_now):
    game, d = _fighter(tmp_path, intervene=True)
    game.prompt = True
    game.FRAMES = {**game.FRAMES, "treasure": "VIEW TAKE POOL EXIT"}
    d.fight()
    assert game.keys[-3:] == ["n", "e", "n"] and d.where == "map"


def test_continue_battle_after_intervene_is_answered_no_and_read_once(
        tmp_path, fight_now):
    game, d = _fighter(tmp_path, intervene=True)
    game.prompt = True
    got = d.fight()
    assert game.keys == ["m", "Up", "Up", "c", "alt+x", "n", "e", "n"]
    assert "Return" not in game.keys and got["intervened"]
    after = _events(d, "after-intervene")
    assert len(after) == 1
    assert {c["name"] for c in after[0]["combatants"]} >= {"GUY", "ORC"}
    assert [e["event"] for e in d.logged
            if e.get("event") in ("intervene", "after-intervene")] == [
        "intervene", "after-intervene"]


def test_an_unreadable_after_intervene_read_is_logged_and_the_prompt_still_answered(
        tmp_path, fight_now):
    game, d = _fighter(tmp_path, intervene=True)
    game.prompt = True
    real = game.read

    def read(addr, n):
        if game.state == "confirm":
            raise da.dosboxx.NotHalted("MEMDUMPBIN answered ''")
        return real(addr, n)

    game.read = read
    d.fight()
    assert game.keys == ["m", "Up", "Up", "c", "alt+x", "n", "e", "n"]
    assert _events(d, "after-intervene") == []
    assert len(_events(d, "after-intervene-unread")) == 1


def _destroyed_digests(monkeypatch, tmp_path):
    game, _ = _fighter(tmp_path / "digest")
    game.state = "lost"
    screen = game.frame()
    assert da.fight_bar_kind(screen) is None
    digests = (screen.glyphs(dosbox.BAR), screen.glyphs(da.PARTY_DESTROYED_LINE))
    monkeypatch.setattr(da, "PARTY_DESTROYED", digests)


def test_a_destroyed_party_stops_the_fight_at_once_with_its_reason(
        tmp_path, monkeypatch, clock):
    _destroyed_digests(monkeypatch, tmp_path)
    game, d = _fighter(tmp_path)
    game.lose = True
    with pytest.raises(da.StepFailed, match="party was destroyed"):
        d.fight(600)
    assert [e["outcome"] for e in _events(d, "fight-outcome")] == ["destroyed"]
    assert game.looks < da.FIGHT_PATIENCE


def test_the_defeat_bar_alone_stays_unclassified(tmp_path, monkeypatch, clock):
    _destroyed_digests(monkeypatch, tmp_path)
    game, d = _fighter(tmp_path)
    game.lose, game.line = True, False
    with pytest.raises(da.StepFailed, match=f"stayed {da.FIGHT_PATIENCE:.0f} s"):
        d.fight(600)
    assert _events(d, "fight-outcome") == []


def test_silver_blades_gates_alt_x_on_its_second_argument():
    from tools.dos import dosspellslots
    try:
        game = da.TITLES["ssb"].find_game()
    except (FileNotFoundError, OSError):
        pytest.skip("needs the DOS Secret of the Silver Blades archive")
    if not (game / "GAME.OVR").is_file() or not (game / "START.EXE").is_file():
        pytest.skip("no START.EXE and GAME.OVR in the Silver Blades archive")
    image = dosspellslots.image_of(game, "START.EXE")
    at = dosspellslots.data_segment(image) * 16 + 0x190F
    assert image[at:at + 4] == b"\x03Gem"
    assert da.CHEAT_ARGS["ssb"].split()[1].encode() == b"Gem"
    ovr = (game / "GAME.OVR").read_bytes()
    assert ovr[0xC06D:0xC072] == bytes.fromhex("3C2D75349A")
    handler = ovr[0x18D17:0x18DEC]
    assert bytes.fromhex("2680BDA80101") in handler
    assert bytes.fromhex("26C685A60106") in handler


# -- a Curse sheet headed `(NPC)` ----------------------------------------------

#: Six members' names, drawn in the test font on the roster and the sheet.
_FONT_NAMES = {1: "MATHEW", 2: "RANGER", 3: "TRAVIS", 4: "LEDERA", 5: "SHARA",
               6: "PHIL"}
_GREEN = b"\x55\xff\x55"


class FakeCurseHeader(FakeCurseMenu):
    """Curse's party menu with the names drawn in the test font, and a sheet
    that draws `header` two cells after the name, where `GAME.OVR`
    0x27112-0x27140 draws `(NPC)` for a control byte above 0x7F."""

    def __init__(self, tmp, header="(NPC)", shows=None, **kw):
        super().__init__(tmp, **kw)
        self.header, self.shows = header, shows

    def capture(self):
        if self.mode not in ("party", "pick", "sheet"):
            return super().capture()
        text = b"" if self.mode == "sheet" else bytes((self.line,))
        px = bytearray(_screen(self.BARS[self.mode], text).px)
        if self.mode == "sheet":
            name = _FONT_NAMES[self.shows or self.line]
            x, y = screens.POD_SHEET_NAME
            _draw(px, _FONT_BLOCK, y // 8, x // 8, name, _WHITE)
            if self.header:
                _draw(px, _FONT_BLOCK, y // 8, x // 8 + len(name) + 2, self.header,
                      _GREEN)
        else:
            x, y = screens.POD_ROSTER["party"]
            for n in range(1, self.size + 1):
                _draw(px, _FONT_BLOCK, y // 8 + n - 1, x // 8, _FONT_NAMES[n],
                      _WHITE if n == self.line else _CYAN)
        return dosbox.Screen(W, H, bytes(px))


def _curse_header(tmp_path, monkeypatch, **kw):
    monkeypatch.setattr(dosbox, "find_game", lambda stem="CURSE": tmp_path)
    monkeypatch.setattr(da, "load_font", lambda game: _FONT)
    game = FakeCurseHeader(tmp_path, **kw)
    d = da.Driver(game, lambda **k: None, "J", "curse", party_size=game.size)
    d.game.to_main_menu = lambda timeout=120.0: None
    d.load()
    return game, d


@pytest.mark.parametrize("header", ["(NPC)", None])
def test_a_curse_sheet_is_the_members_with_or_without_an_npc_header(
        tmp_path, monkeypatch, header):
    game, d = _curse_header(tmp_path, monkeypatch, header=header)
    got = d.view(2)
    assert game.keys[2:] == ["End", "v", "e"]
    assert got["name"] == screens.roster_name(game.capture(), "party", 2)
    assert got["header"] == header
    assert d.where == "party" and game.mode == "party"


@pytest.mark.parametrize("kw", [{"header": "(XPC)"}, {"shows": 4}])
def test_an_npc_header_does_not_excuse_another_name_or_another_header(
        tmp_path, monkeypatch, kw):
    game, d = _curse_header(tmp_path, monkeypatch, **kw)
    with pytest.raises(da.StepFailed, match="not roster line 2"):
        d.view(2)
    assert "e" not in game.keys


def test_the_captured_npc_sheet_is_the_rangers_with_its_header():
    """#667's `1bf7cf2dad-l51-subject`: roster line 5, the Ranger staged with
    control 0xB3, drew `(NPC)` after his name, and the name check blocked it."""
    try:
        game = da.TITLES["curse"].find_game()
    except (FileNotFoundError, OSError):
        pytest.skip("needs the DOS Curse of the Azure Bonds archive")
    font = da.load_font(game)
    run = "1bf7cf2dad-l51-subject"
    roster = da.dosboxx.halve(_capture(run, "004-view-line-5", issue="667"))
    sheet = da.dosboxx.halve(_capture(run, "005-lost-view-5-name", issue="667"))
    assert screens.roster_line(roster, "party", 6) == 5
    assert screens.sheet_name(sheet) != screens.roster_name(roster, "party", 5)
    assert da.sheet_header(sheet, da.name_cells(roster, "party", 5), font) == "(NPC)"
    for other in (1, 2, 3, 4, 6):
        assert da.sheet_header(sheet, da.name_cells(roster, "party", other), font) is None


# -- the locked door the fight's walk meets ------------------------------------

#: `.`, a cell pattern no letter of `_LETTER` uses.
_DOT = 0x30


def _locked(rest: str) -> bytes:
    return _bar("LOCKED") + bytes((_DOT,)) + _bar(" " + rest)


def test_the_locked_door_bar_is_known_by_its_letters_whatever_it_offers():
    for rest in ("BASH PICK EXIT", "BASH PICK KNOCK EXIT", "BASH EXIT"):
        words = da.bar_words(_screen(_locked(rest), b""))
        assert da.locked_words(words), rest
        assert da.fight_bar_kind(_screen(_locked(rest), b"")) == "locked"
    # `LOCKAD.` has seven different cells, but its fifth is not `EXIT`'s `E`;
    # a prompt and `EXIT` alone offer nothing to choose.
    for bar in (_locked("BASH PICK"), _bar("VIEW TAKE POOL SHARE EXIT"),
                _bar("MOVE AREA CAST VIEW ENCAMP SEARCH LOOK"),
                _bar("MOVE VIEW AIM USE CAST QUICK DONE"), _bar("LOCKED EXIT"),
                _bar("LOCKAD") + bytes((_DOT,)) + _bar(" BASH PICK EXIT"),
                _locked("EXIT")):
        assert not da.locked_words(da.bar_words(_screen(bar, b"")))
    assert da.FIGHT_KEYS["locked"] == "e"


def test_the_captured_locked_door_bar_is_classified():
    """#667's `1bf7cf2dad-l51-subject2` stopped at `LOCKED. BASH PICK EXIT`."""
    screen = da.dosboxx.halve(_capture("1bf7cf2dad-l51-subject2",
                                       "007-lost-fight-unknown-8ae8d1b0c9a980bf",
                                       issue="667"))
    assert da.fight_bar_kind(screen) == "locked"


class LockedFight(FakeFight):
    """`FakeFight` whose first step from square 1 meets a locked door, which
    `e` leaves with the party where it stood."""

    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        self.door = True

    def frame(self):
        if self.state == "locked":
            return _screen(_locked("BASH PICK EXIT"), b"")
        return super().frame()

    def key(self, *keys, gap=0.35):
        for k in keys:
            if self.state == "move" and k == "Up" and self.square == 1 and self.door:
                self.keys.append(k)
                self.state, self.door = "locked", False
            elif self.state == "locked":
                self.keys.append(k)
                if k == "e":
                    self.state = "move"
            else:
                super().key(k, gap=gap)


def test_a_locked_door_on_the_walk_is_left_with_exit_and_the_walk_goes_on(
        tmp_path, clock):
    game = LockedFight(tmp_path)
    d = da.Driver(game, lambda **k: None, "D", "ssb", party_size=3)
    d.logged = []
    d.note = lambda **k: d.logged.append(k)
    d.record_world(game.capture())
    d.where = "map"
    got = d.fight()
    assert game.keys == ["m", "Up", "e", "Right", "Up", "Up", "c", "q", "q", "e", "n"]
    assert got["bumps"] == 1 and got["bars"] == 2 and d.where == "map"
    assert "locked" in [e["kind"] for e in _events(d, "fight-screen")]


# -- a second fight in one boot, after a camp save -----------------------------


class CampFight(FakeFight):
    """`FakeFight` with Silver Blades' camp: `e` on the map encamps, `s` and a
    letter save and ask to quit, `n` declines, and `e` in camp leaves it, the
    party then walking from square 1 again.  With `stuck`, `e` in camp does
    nothing."""

    FRAMES = {**FakeFight.FRAMES, "camp": "SAVE VIEW MAGIC REST ALTER FIX EXIT",
              "which": "A B C D", "quit": "QUIT TO DOS YES NO"}

    def __init__(self, tmp_path, stuck=False):
        super().__init__(tmp_path)
        self.save_dir.mkdir()
        self.stuck = stuck

    def save_file(self, letter):
        return self.save_dir / f"SAVGAM{letter.upper()}.DAT"

    def key(self, *keys, gap=0.35):
        for k in keys:
            s = self.state
            if s == "map" and k == "e":
                self.state = "camp"
            elif s == "camp" and k == "s":
                self.state = "which"
            elif s == "which" and k.upper() in "ABCDEFGHIJ":
                self.save_file(k).write_bytes(bytes((len(self.keys),)))
                self.state = "quit"
            elif s == "quit" and k == "n":
                self.state = "camp"
            elif s == "camp" and k == "e" and not self.stuck:
                self.state, self.square = "map", 1
            else:
                super().key(k, gap=gap)
                continue
            self.keys.append(k)


def test_two_fights_in_one_boot_with_a_camp_save_between(tmp_path, clock):
    game = CampFight(tmp_path)
    d = da.Driver(game, lambda **k: None, "D", "ssb", party_size=3)
    d.logged = []
    d.note = lambda **k: d.logged.append(k)
    d.record_world(game.capture())
    d.where = "map"
    d.first_bar_key = "space"
    first = d.fight()
    d.camp()
    d.save("C")
    left = d.leave()
    second = d.fight()
    fight = ["m", "Up", "Up", "c", "q", "q", "e", "n"]
    # The first fight's `space` is the first-bar key; the second's is the
    # hand-back, pressed at its first command bar before `QUICK`.
    assert game.keys == (fight[:4] + ["space"] + fight[4:] + ["e", "s", "c", "n", "e"]
                         + fight[:4] + ["space"] + fight[4:])
    assert (game.save_dir / "SAVGAMC.DAT").is_file()
    assert (first["fight"], second["fight"]) == (1, 2)
    # The first-bar key is the first fight's only.
    assert first["first_bar_key"] == "space" and second["first_bar_key"] is None
    assert second["bars"] == 2 and d.where == "map" and left["map_bar"] == d.world_sig
    assert [e["actor"]["name"] for e in _events(d, "bar")] == [
        "GUY", "GUY", "PAINE", "GUY", "PAINE"]
    assert len(_events(d, "placement")) == 2


def test_a_camp_exit_that_leaves_camp_showing_stops_the_run(tmp_path, clock):
    game = CampFight(tmp_path, stuck=True)
    d = da.Driver(game, lambda **k: None, "D", "ssb", party_size=3)
    d.record_world(game.capture())
    d.where = "map"
    d.camp()
    with pytest.raises(da.StepFailed, match="leave-camp"):
        d.leave()
    assert game.keys == ["e", "e", "e"] and d.where == "camp"


def test_leave_parses_and_goes_from_camp_to_the_map_in_curse_and_silver_blades():
    assert da.parse_step("leave").kind == "leave"
    with pytest.raises(ValueError):
        da.parse_step("leave 1")
    steps = ("load", "begin", "fight", "camp", "save C", "leave", "fight", "camp",
             "save D", "read")
    for title in ("curse", "ssb"):
        da.validate_steps([da.parse_step(s) for s in steps], title)
        with pytest.raises(ValueError, match="leave needs camp first"):
            da.validate_steps([da.parse_step(s) for s in ("load", "begin", "leave")],
                              title)
        with pytest.raises(ValueError, match="save needs camp first"):
            da.validate_steps([da.parse_step(s) for s in
                               ("load", "begin", "camp", "leave", "save C")], title)
    with pytest.raises(ValueError, match="curse, ssb only, not pool"):
        da.validate_steps([da.parse_step(s) for s in ("load", "camp", "leave")], "pool")


# -- --stage-side: the combat side and quickfight bytes ------------------------


def test_a_stage_side_line_parses_the_side_alone_or_with_quickfight():
    assert da.parse_side("5=0") == (5, 0, None)
    assert da.parse_side("5=1:1") == (5, 1, 1)
    assert da.parse_side("1=0x01:0x00") == (1, 1, 0)


@pytest.mark.parametrize("bad", ["0=1", "9=1", "5=256", "5=1:256", "5", "5=1:2:3",
                                 "5=", "x"])
def test_a_bad_stage_side_line_is_blocked(bad):
    with pytest.raises(ValueError):
        da.parse_side(bad)


@pytest.mark.parametrize("key,side_at", [
    ("pool-of-radiance", 0x10E),
    ("curse-of-the-azure-bonds", 0x197),
    ("secret-of-the-silver-blades", 0x1A8),
])
def test_stage_side_writes_the_bytes_the_codec_reads_as_side_and_quickfight(
        tmp_path, key, side_at):
    from goldbox import dos_codec, dos_port
    record = bytearray(dos_port.deltas_for(key).record_size)
    record[0], record[1:6] = 5, b"GUARD"
    path = tmp_path / "CHRDATJ5.SAV"
    path.write_bytes(bytes(record))
    got = da.stage_side(tmp_path, "J", 5, 1, 1)
    data = path.read_bytes()
    assert data[side_at:side_at + 2] == b"\x01\x01"
    assert data[:side_at] == bytes(record[:side_at])
    assert data[side_at + 2:] == bytes(record[side_at + 2:])
    assert (got["side_offset"], got["quickfight_offset"]) == (hex(side_at),
                                                              hex(side_at + 1))
    assert (got["side_before"], got["side_after"]) == ("00", "01")
    neutral = dos_codec.to_neutral(dos_codec.read_character(path))
    assert neutral.get("hostile") is True and neutral.get("quickfight") is True


def test_stage_side_leaves_quickfight_alone_when_not_given(tmp_path):
    path = tmp_path / "CHRDATJ5.SAV"
    path.write_bytes(_curse_record())
    got = da.stage_side(tmp_path, "J", 5, 1)
    assert path.read_bytes()[0x197:0x199] == b"\x01\x00"
    assert "quickfight_after" not in got


def test_the_command_line_stages_the_side_after_control_and_before_record(tmp_path):
    (tmp_path / "CHRDATJ5.SAV").write_bytes(_curse_record())
    args = _run_args(tmp_path, [])
    args.stage_control = ["5=0xB3"]
    args.stage_side = ["5=0:1"]
    args.stage_record = ["5:0x197=1"]
    done = da.stage(tmp_path, "J", args)
    assert [s["stage"] for s in done] == ["control", "side", "record"]
    assert (tmp_path / "CHRDATJ5.SAV").read_bytes()[0x197:0x199] == b"\x01\x01"


def test_check_staging_blocks_a_stage_side_line_with_no_chrdat(tmp_path):
    args = _run_args(tmp_path, [])
    args.stage_side = ["3=1"]
    with pytest.raises(ValueError, match="line 3"):
        da.check_staging(args, tmp_path, "J")


def test_main_blocks_a_bad_stage_side_before_any_slot(tmp_path, monkeypatch, capsys):
    def claimed(*a, **k):
        raise AssertionError("an emulator slot was claimed")

    monkeypatch.setattr(da.dosbox, "claim", claimed)
    monkeypatch.setattr(da.dosboxx, "claim", claimed)
    with pytest.raises(SystemExit):
        da.main(["--title", "curse", "--save", str(tmp_path), "--steps", "load",
                 "--stage-side", "5=256", "--out", str(tmp_path / "out")])
    err = capsys.readouterr().err
    assert "5=256" in err and "LINE=SIDE[:QUICKFIGHT]" in err


def test_only_a_fight_after_the_first_hands_the_party_back_before_its_first_bar(
        tmp_path, clock):
    game = CampFight(tmp_path)
    d = da.Driver(game, lambda **k: None, "D", "ssb", party_size=3)
    d.logged = []
    d.note = lambda **k: d.logged.append(k)
    d.record_world(game.capture())
    d.where = "map"
    first = d.fight()
    assert "space" not in game.keys
    assert first["handed_back"] is False and first["handed_back_to"] is None
    d.camp()
    d.save("C")
    d.leave()
    at = len(game.keys)
    second = d.fight()
    fight2 = game.keys[at:]
    assert fight2 == ["m", "Up", "Up", "c", "space", "q", "q", "e", "n"]
    assert fight2.count("space") == 1
    assert [e["kind"] for e in _events(d, "hand-back")] == ["command"]
    # SPACE applies to the members whose control byte is below 0x80: EPONA,
    # at 0xB3, stays under the computer.
    assert second["handed_back"] is True
    assert second["handed_back_to"] == ["GUY", "PAINE"]
    after = {c["name"]: c["quickfight"] for c in second["placement"]}
    assert after["PAINE"] == 0 and after["EPONA"] == 1


class LaterFight(CampFight):
    """`CampFight` whose second walk shows, with `detour`, an unclassified
    screen and then a blank bar on its first step, each for two captures (a
    shot captures too), before the party stands on square 3; and whose second fight, with `quick`,
    opens on a blank bar (a computer turn) before GUY's command bar.  With
    `straight` the second fight has no encounter menu: the step from square
    3 starts it at once, the combat setup moves GUY in the combat map, and
    with QUICK carried over only an unclassified message bar shows until
    `space` hands GUY back at his command bar."""

    def __init__(self, tmp_path, detour=False, quick=False, straight=False):
        super().__init__(tmp_path)
        self.detour, self.quick, self.second = detour, quick, False
        self.straight = straight

    def frame(self):
        if self.state == "all_quick":
            return _screen(_bar("GUY HIT ORC"), b"")
        if self.state == "pre_unknown":
            return _screen(_bar("DOOR"), b"")
        if self.state == "pre_blank":
            return _screen(b"", b"")
        return super().frame()

    def capture(self):
        if self.state.startswith("pre_"):
            frame = self.frame()
            self.state = self.pre.pop(0)
            return frame
        return super().capture()

    def key(self, *keys, gap=0.35):
        for k in keys:
            s = self.state
            if s == "camp" and k == "e":
                self.second = True
            if (self.second and self.detour and s == "move" and k == "Up"
                    and self.square == 1):
                self.keys.append(k)
                self.state, self.square, self.detour = "pre_unknown", 3, False
                self.pre = ["pre_unknown", "pre_blank", "pre_blank", "move"]
            elif (self.second and self.straight and s == "move" and k == "Up"
                  and self.square == 3):
                self.keys.append(k)
                self.state = "all_quick"
                layout = _ssb()
                self.ds[layout.map_at + 4] += 1
            elif s == "all_quick" and k == "space":
                self.state, self.actor, self.fought = "bar1", "GUY", True
                _select(self.ds, self.ptrs["GUY"])
                super().key(k, gap=gap)
            elif self.second and self.quick and s == "encounter" and k == "c":
                self.keys.append(k)
                self.state, self.actor, self.fought = "blank1", "GUY", True
                _select(self.ds, self.ptrs["GUY"])
            else:
                super().key(k, gap=gap)


def _later(tmp_path, **kw):
    game = LaterFight(tmp_path, **kw)
    d = da.Driver(game, lambda **k: None, "D", "ssb", party_size=3)
    d.logged = []
    d.note = lambda **k: d.logged.append(k)
    d.record_world(game.capture())
    d.where = "map"
    d.fight()
    d.camp()
    d.save("C")
    d.leave()
    at = len(game.keys)
    return game, d, d.fight(), game.keys[at:]


def test_no_hand_back_on_a_walk_screen_before_the_encounter(tmp_path, clock):
    game, d, got, keys = _later(tmp_path, detour=True)
    kinds = [e["kind"] for e in _events(d, "fight-screen")]
    assert None in kinds and "blank" in kinds
    assert keys == ["m", "Up", "Up", "c", "space", "q", "q", "e", "n"]
    assert [e["kind"] for e in _events(d, "hand-back")] == ["command"]
    assert got["handed_back"] is True


def test_the_hand_back_goes_out_at_the_first_combat_screen_after_the_encounter(
        tmp_path, clock):
    game, d, got, keys = _later(tmp_path, quick=True)
    assert keys == ["m", "Up", "Up", "c", "space", "q", "q", "e", "n"]
    assert [e["kind"] for e in _events(d, "hand-back")] == ["blank"]
    # The state before SPACE is logged: PAINE (control 0) still on the
    # computer, and handed back by the time the placement is read.
    before = {c["name"]: c["quickfight"] for c in _events(d, "before-hand-back")[0][
        "combatants"]}
    assert before["PAINE"] == 1 and before["EPONA"] == 1
    assert {c["name"]: c["quickfight"] for c in got["before_hand_back"]} == before
    after = {c["name"]: c["quickfight"] for c in got["placement"]}
    assert after["PAINE"] == 0 and after["EPONA"] == 1
    assert got["handed_back_to"] == ["GUY", "PAINE"]


def test_a_later_fight_with_no_encounter_menu_gets_its_hand_back_once_combat_begins(
        tmp_path, clock):
    game, d, got, keys = _later(tmp_path, detour=True, straight=True)
    # The walk's own screens come first and are left alone; the message bar
    # of the all-computer fight gets SPACE once the combat window changed.
    assert keys == ["m", "Up", "Up", "space", "q", "q", "e", "n"]
    assert [e["kind"] for e in _events(d, "hand-back")] == [None]
    probes = _events(d, "combat-probe")
    assert [p["begun"] for p in probes][-1] is True
    assert any(p["why"] == "unchanged" for p in probes)
    assert got["encounters"] == 0 and got["handed_back"] is True
    assert got["handed_back_to"] == ["GUY", "PAINE"]


# -- camp MAGIC > SCRIBE ---------------------------------------------------------

_SCRIBE_NAMES = ("GUY DE VALOIS", "PAINE", "EPONA", "MALACHITE", "DOMINIC", "MORGAINE")
#: MORGAINE's scroll as Silver Blades listed it (#745's boot 2): two sixth-level
#: spells and the first-level one she scribed.
_SCROLL = (("6TH LEVEL", ("STONE TO FLESH", "DISINTEGRATE")),
           ("1ST LEVEL", ("PROTECTION FROM GOOD",)))
_BLACK, _GREEN = b"\x00\x00\x00", b"\x55\xff\x55"


def _text(px: bytearray, row: int, col: int, text: str, ink: bytes = _GREEN,
          reverse: int = 0) -> None:
    """`text` in the stand-in font at a text cell; `reverse` cells from `col`
    filled white first and the text drawn black on them, as a highlight."""
    if reverse:
        for dy in range(8):
            for x in range(col * 8, (col + reverse) * 8):
                at = ((row * 8 + dy) * W + x) * 3
                px[at:at + 3] = _WHITE
        ink = _BLACK
    _draw(px, _FONT_BLOCK, row, col, text, ink)


class FakeScribe(FakePool):
    """Camp, the Magic bar and `SCRIBE`, as Silver Blades drew them in #745's
    boot 2: the roster with the current member highlighted, which the title's
    camp key moves on; `MAGIC`'s `S` opens `<NAME>'S SPELLS ON SCROLLS` over
    `CHOOSE SPELL: SCRIBE EXIT`, a heading per level at column 1 and each spell
    at column 3, the highlight a white block the title's list key moves down
    the spells and wraps; `S` there redraws the highlighted spell as `*SPELL`
    at column 2, or, for a spell in `block`, shows a message for one capture
    and changes nothing; `E` opens `<NAME>'S SPELLS TO SCRIBE` over `EXIT`
    when a spell is marked, else goes back to the Magic bar; its `E` asks
    `SCRIBE THESE SPELLS?YES NO`, whose `Y` scribes and returns to the Magic
    bar.  `E` on the Magic bar returns to camp; on the camp bar it is Pool's
    exit to DOS, recorded in `exited`.

    `start` is the list row the highlight opens on (the first spell by
    default), `swallow_pick` drops the first `S` on the list, `head` draws
    another name on the list's title, and `marked` spells are drawn `*`
    already.  `flicker` changes one pixel outside the text on every capture,
    as the camp picture and Silver Blades' pointer can; `unseen` blocks
    without drawing anything a capture can see; `late` draws a rejection's
    message only on the second capture after the key; `lag` keeps the
    confirmation on screen for that many captures after `Y`; `after_yes`
    puts up an unknown `PRESS ANY KEY TO CONTINUE` screen instead of the
    Magic bar; `stuck_list` makes the list key move nothing.  `copyable=False`
    is Curse with no scroll it can read, as measured: `S` on the Magic bar
    clears `THE PARTY MAKES CAMP...` from the message window, draws nothing and
    stays on the Magic bar; `notice` draws that many captures of `notice_text`
    there as well (the game's string is `<NAME> has no copyable scrolls`);
    `deaf_magic` makes that `S` change nothing at all; `lose_first` drops the
    first `S` on the Magic bar while an unrelated line appears in the message
    window, as a lost key beside another draw would."""

    CAMP = "SAVE VIEW MAGIC REST ALTER FIX EXIT"
    MAGIC = "CAST MEMORIZE SCRIBE DISPLAY REST EXIT"

    def __init__(self, tmp, title="ssb", start=None, swallow_pick=False, block=(),
                 marked=(), head=None, flicker=False, unseen=False, late=False,
                 lag=0, after_yes=False, stuck_list=False, copyable=True,
                 notice=0, notice_text="HAS NO COPYABLE SCROLLS", deaf_magic=False,
                 lose_first=False):
        super().__init__(tmp, keys=TITLE_KEYS[title])
        self.title, self.mode, self.line, self.size = title, "camp", 1, 6
        self.rows: list[tuple[str, str]] = []
        for level, spells in _SCROLL:
            self.rows.append(("level", level))
            self.rows += [("spell", s) for s in spells]
        self.spell_rows = [k for k, (kind, _) in enumerate(self.rows) if kind == "spell"]
        self.start = self.spell_rows[0] if start is None else start
        self.hl = self.start
        self.swallow_pick, self.block, self.head = swallow_pick, set(block), head
        self.marked = set(marked)
        self.message = False
        self.scribed: list[str] = []
        self.exited = False
        self.flicker, self.unseen, self.late = flicker, unseen, late
        self.lag, self.after_yes, self.stuck_list = lag, after_yes, stuck_list
        self.delay, self.pending, self.captures = 0, None, 0
        self.copyable, self.deaf_magic = copyable, deaf_magic
        self.camp_text, self.notice, self.notices = True, 0, notice
        self.notice_text = notice_text
        self.lose_first, self.noise = lose_first, False

    def key(self, k, gap=0.0):
        m = self.mode
        handled = True
        if m == "camp" and k == da.CAMP_ROSTER_NEXT.get(self.title, da.POOL_ROSTER_NEXT):
            self.line = self.line % self.size + 1
        elif m == "camp" and k == "m":
            self.mode = "magic"
        elif m == "camp" and k == "e":
            self.exited = True
        elif m == "magic" and k == "s" and self.lose_first:
            self.lose_first, self.noise = False, True
        elif m == "magic" and k == "s" and self.deaf_magic:
            pass
        elif m == "magic" and k == "s" and not self.copyable:
            self.camp_text, self.notice = False, self.notices
        elif m == "magic" and k == "s":
            self.mode, self.hl = "list", self.start
        elif m == "magic" and k == "e":
            self.mode = "camp"
        elif m == "list" and k == da.SCRIBE_LIST_DOWN[self.title] and self.stuck_list:
            pass
        elif m == "list" and k == da.SCRIBE_LIST_DOWN[self.title]:
            at = self.spell_rows.index(self.hl)
            self.hl = self.spell_rows[(at + 1) % len(self.spell_rows)]
        elif m == "list" and k == "s":
            spell = self.rows[self.hl][1]
            if self.swallow_pick:
                self.swallow_pick = False
            elif spell in self.block:
                self.message = not self.unseen
                self.delay = 1 if self.late else 0
            else:
                self.marked.add(spell)
        elif m == "list" and k == "e":
            self.mode = "chosen" if self.marked else "magic"
        elif m == "chosen" and k == "e":
            self.mode = "confirm"
        elif m == "confirm" and k == "y":
            self.scribed += sorted(self.marked)
            if self.after_yes:
                self.mode = "unknown"
            elif self.lag:
                self.pending = "magic"
            else:
                self.mode = "magic"
        else:
            handled = False
        if handled:
            self.keys.append(k)
        else:
            super().key(k, gap)

    def name(self) -> str:
        return self.head or _SCRIBE_NAMES[self.line - 1]

    def capture(self):
        self.captures += 1
        if self.pending is not None:
            if self.lag:
                self.lag -= 1
            else:
                self.mode, self.pending = self.pending, None
        if self.mode == "unknown":
            px = bytearray(W * H * 3)
            _text(px, da.BAR_ROW, 0, "PRESS ANY KEY TO CONTINUE")
            return dosbox.Screen(W, H, bytes(px))
        if self.mode not in ("camp", "magic", "list", "chosen", "confirm"):
            return super().capture()
        px = bytearray(W * H * 3)
        if self.flicker:
            at = ((22 * 8 + 3) * W + 30 * 8 + self.captures % 8) * 3
            px[at:at + 3] = b"\x55\x55\x55"
        if self.mode in ("camp", "magic"):
            _text(px, da.BAR_ROW, 0, self.CAMP if self.mode == "camp" else self.MAGIC)
            if self.notice:
                self.notice -= 1
                _text(px, 18, 1, f"{_SCRIBE_NAMES[self.line - 1]} {self.notice_text}")
            elif self.camp_text:
                _text(px, 18, 1, "THE PARTY MAKES CAMP...")
            if self.noise:
                _text(px, 20, 1, "SOMETHING ELSE WAS DRAWN")
            x, y = screens.POD_ROSTER["camp"]
            for n, name in enumerate(_SCRIBE_NAMES, 1):
                _text(px, y // 8 + n - 1, x // 8, name, _CYAN,
                      reverse=screens.POD_NAME_CELLS if n == self.line else 0)
            return dosbox.Screen(W, H, bytes(px))
        chosen = self.mode != "list"
        _text(px, 1, 1, f"{self.name()}'S SPELLS {'TO SCRIBE' if chosen else 'ON SCROLLS'}")
        _text(px, da.BAR_ROW, 0, {"list": "CHOOSE SPELL: SCRIBE EXIT", "chosen": "EXIT",
                                  "confirm": "SCRIBE THESE SPELLS?YES NO"}[self.mode])
        rows = self.rows if not chosen else [
            r for r in self.rows if r[0] == "level" or r[1] in self.marked]
        for k, (kind, text) in enumerate(rows):
            row = da.SCRIBE_LIST[1] // 8 + k
            if kind == "level":
                _text(px, row, 1, text, b"\xaa\x55\xff")
            elif text in self.marked:
                _text(px, row, 2, "*" + text, reverse=30 if k == self.hl and not chosen
                      else 0)
            else:
                _text(px, row, 3, text, reverse=30 if k == self.hl else 0)
        if self.message and self.delay:
            self.delay -= 1
        elif self.message:
            self.message = False
            _text(px, 20, 1, "YOU ALREADY KNOW THAT SPELL")
        return dosbox.Screen(W, H, bytes(px))


@pytest.fixture
def scribe_measured(monkeypatch, tmp_path):
    """The stand-in font for the title's own, and the fake's Magic bar for the
    measured one."""
    (tmp_path / "probe").mkdir()
    probe = FakeScribe(tmp_path / "probe")
    probe.mode = "magic"
    monkeypatch.setattr(da, "POOL_MAGIC_BAR", screens.bar_signature(probe.capture()))
    monkeypatch.setattr(dosbox, "find_game", lambda stem="POOLRAD": tmp_path)
    monkeypatch.setattr(da, "load_font", lambda game: _FONT)


def _scribe_camp(tmp_path, title="ssb", **kw) -> tuple[FakeScribe, da.Driver]:
    (tmp_path / "game").mkdir()
    game = FakeScribe(tmp_path / "game", title, **kw)
    d = da.Driver(game, lambda **k: None, "D", title, party_size=game.size)
    d.logged = []
    d.note = lambda **k: d.logged.append(k)
    d.camp_sig = screens.bar_signature(game.capture())
    d.where = "camp"
    return game, d


def test_the_scribe_step_parses_a_line_and_a_spell_of_several_words():
    step = da.parse_step("scribe 5 Protection from good")
    assert (step.kind, step.line, step.name) == ("scribe", 5, "PROTECTION FROM GOOD")
    assert da.parse_step("scribe 6 CURE-LIGHT-WOUNDS").name == "CURE LIGHT WOUNDS"


@pytest.mark.parametrize("text", ["scribe 5", "scribe 9 SLEEP", "scribe X SLEEP",
                                  "scribe 5 *SLEEP"])
def test_the_scribe_step_blocks_a_malformed_argument(text):
    assert da.parse_step("scribe 5 SLEEP").name == "SLEEP"
    with pytest.raises(ValueError):
        da.parse_step(text)


@pytest.mark.parametrize("title", ["pool", "curse", "ssb"])
def test_scribe_is_taken_in_camp_in_the_three_titles(title):
    begin = [] if title == "pool" else ["begin"]
    steps = ["load", *begin, "camp", "scribe 6 SLEEP", "save D", "rest 8h", "save E",
             "read"]
    da.validate_steps([da.parse_step(s) for s in steps], title)
    with pytest.raises(ValueError, match="scribe needs camp first"):
        da.validate_steps([da.parse_step(s) for s in ["load", *begin, "scribe 6 SLEEP"]],
                          title)


def test_scribe_is_blocked_in_pools_of_darkness():
    steps = [da.parse_step(s) for s in ("load", "begin", "camp", "scribe 6 SLEEP")]
    with pytest.raises(ValueError, match="scribe is driven in curse, pool, ssb only"):
        da.validate_steps(steps, "darkness")


@pytest.mark.parametrize("title,roster,down", [("pool", "End", "End"),
                                               ("curse", "End", "End"),
                                               ("ssb", "Down", "Down")])
def test_scribe_picks_the_spell_confirms_it_and_ends_in_camp(
        tmp_path, scribe_measured, title, roster, down):
    game, d = _scribe_camp(tmp_path, title)
    got = d.scribe(6, "PROTECTION FROM GOOD")
    assert game.keys == [roster] * 5 + ["m", "s", down, down, "s", "e", "e", "y", "e"]
    assert game.scribed == ["PROTECTION FROM GOOD"]
    assert game.mode == "camp" and not game.exited
    assert got["name"] == "MORGAINE" and got["head"] == "MORGAINE'S SPELLS ON SCROLLS"
    assert [e["spell"] for e in got["list"]] == ["STONE TO FLESH", "DISINTEGRATE",
                                                 "PROTECTION FROM GOOD"]
    assert [e["level"] for e in got["list"]] == ["6TH LEVEL", "6TH LEVEL", "1ST LEVEL"]
    assert [e["marked"] for e in got["list_after_pick"]] == [False, False, True]
    assert [(e["spell"], e["marked"]) for e in got["chosen"]] == [
        ("PROTECTION FROM GOOD", True)]
    assert (got["walk_presses"], got["pick_presses"]) == (2, 1)
    assert d.scribing


def test_a_list_that_opens_on_the_spell_is_scribed_without_moving(tmp_path,
                                                                    scribe_measured):
    game, d = _scribe_camp(tmp_path, start=4)
    d.scribe(6, "PROTECTION FROM GOOD")
    assert game.keys == ["Down"] * 5 + ["m", "s", "s", "e", "e", "y", "e"]


def test_a_swallowed_scribe_key_is_sent_once_more(tmp_path, scribe_measured):
    game, d = _scribe_camp(tmp_path, start=4, swallow_pick=True)
    got = d.scribe(6, "PROTECTION FROM GOOD")
    assert game.keys[5:9] == ["m", "s", "s", "s"]
    assert got["pick_presses"] == 2 and game.scribed == ["PROTECTION FROM GOOD"]


def test_the_games_rejection_fails_the_step_after_one_key(tmp_path, scribe_measured):
    game, d = _scribe_camp(tmp_path, start=4, block={"PROTECTION FROM GOOD"})
    with pytest.raises(da.StepFailed, match="YOU ALREADY KNOW THAT SPELL"):
        d.scribe(6, "PROTECTION FROM GOOD")
    assert game.keys[5:] == ["m", "s", "s"]
    assert game.scribed == [] and not d.scribing


def test_a_scribe_the_game_takes_with_no_list_fails_after_two_keys(
        tmp_path, scribe_measured):
    """Curse, with no scroll it can read: SCRIBE clears the message window,
    draws nothing and leaves the Magic bar up; the key is sent once more before
    the step fails."""
    game, d = _scribe_camp(tmp_path, "curse", copyable=False)
    with pytest.raises(da.StepFailed, match="cleared the message window and drew "
                       "nothing.*Read Magic") as e:
        d.scribe(6, "PROTECTION FROM GOOD")
    assert game.keys[5:] == ["m", "s", "s"] and game.mode == "magic"
    assert "scribe-6-list-none" in str(e.value)
    assert game.scribed == [] and not d.scribing


def test_the_no_copyable_scrolls_words_are_read_while_the_list_is_awaited(
        tmp_path, scribe_measured):
    game, d = _scribe_camp(tmp_path, "curse", copyable=False, notice=1)
    with pytest.raises(da.StepFailed, match="drew 'MORGAINE HAS NO COPYABLE "
                       "SCROLLS'.*Read Magic"):
        d.scribe(6, "PROTECTION FROM GOOD")
    assert game.keys[5:] == ["m", "s", "s"]


def test_other_words_drawn_instead_of_the_list_are_named_without_the_hint(
        tmp_path, scribe_measured):
    game, d = _scribe_camp(tmp_path, "curse", copyable=False, notice=1,
                           notice_text="IS IN NO CONDITION TO SCRIBE ANY SCROLLS")
    with pytest.raises(da.StepFailed, match="IN NO CONDITION") as e:
        d.scribe(6, "PROTECTION FROM GOOD")
    assert "Read Magic" not in str(e.value) and game.keys[5:] == ["m", "s", "s"]


def test_a_scribe_key_that_changes_nothing_is_sent_twice(tmp_path, scribe_measured):
    """Pins the behaviour from before the message window was watched: both
    presses go out and the step says nothing changed."""
    game, d = _scribe_camp(tmp_path, "curse", deaf_magic=True)
    with pytest.raises(da.StepFailed, match="SCRIBE changed nothing"):
        d.scribe(6, "PROTECTION FROM GOOD")
    assert game.keys[5:] == ["m", "s", "s"] and not d.scribing


def test_a_lost_scribe_key_beside_an_unrelated_message_change_is_sent_again(
        tmp_path, scribe_measured):
    game, d = _scribe_camp(tmp_path, "pool", lose_first=True)
    d.scribe(6, "PROTECTION FROM GOOD")
    assert game.keys[5:8] == ["m", "s", "s"] and game.scribed


def test_the_read_magic_sentence_is_only_for_curse(tmp_path, scribe_measured):
    for title, hinted in (("curse", True), ("pool", False), ("ssb", False)):
        (tmp_path / title).mkdir()
        game, d = _scribe_camp(tmp_path / title, title, copyable=False)
        with pytest.raises(da.StepFailed, match="cleared the message window") as e:
            d.scribe(6, "PROTECTION FROM GOOD")
        assert ("likely lists nothing until Read Magic" in str(e.value)) is hinted


def test_a_spell_not_on_the_scroll_list_is_blocked_before_any_pick(tmp_path,
                                                                    scribe_measured):
    game, d = _scribe_camp(tmp_path)
    with pytest.raises(da.StepFailed, match="SLEEP is not on the scroll list"):
        d.scribe(6, "SLEEP")
    assert game.keys[5:] == ["m", "s"]


def test_a_spell_already_being_scribed_is_blocked_before_any_pick(tmp_path,
                                                                   scribe_measured):
    game, d = _scribe_camp(tmp_path, marked={"PROTECTION FROM GOOD"})
    with pytest.raises(da.StepFailed, match="already drawn"):
        d.scribe(6, "PROTECTION FROM GOOD")
    assert game.keys[5:] == ["m", "s"]


def test_another_members_scroll_list_is_blocked_before_any_pick(tmp_path,
                                                                 scribe_measured):
    game, d = _scribe_camp(tmp_path, head="PAINE")
    with pytest.raises(da.StepFailed, match="not roster line 6's"):
        d.scribe(6, "PROTECTION FROM GOOD")
    assert game.keys[5:] == ["m", "s"]


def test_scribe_is_blocked_outside_its_titles_and_before_camp(tmp_path, scribe_measured):
    game, d = _scribe_camp(tmp_path, "darkness")
    with pytest.raises(da.StepFailed, match="scribe is driven in"):
        d.scribe(6, "SLEEP")
    (tmp_path / "uncamped").mkdir()
    d = da.Driver(FakeScribe(tmp_path / "uncamped"), lambda **k: None, "D", "ssb")
    with pytest.raises(da.StepFailed, match="camp first"):
        d.scribe(6, "SLEEP")
    assert game.keys == []


def test_a_rest_after_a_scribe_rests_in_the_same_camp_and_says_it_was_pending(
        tmp_path, scribe_measured):
    game, d = _scribe_camp(tmp_path)
    d.scribe(6, "PROTECTION FROM GOOD")
    done = len(game.keys)
    d.step_begins("save")
    d.save("D")
    d.step_begins("rest")
    got = d.rest(5)
    assert got["scribe_pending"] is True and game.rested == [5]
    # Nothing between the scribe and the rest leaves camp or camps again.
    assert da.ENCAMP not in game.keys[done:] and game.mode == "camp" and not game.exited
    assert d.rest(5)["scribe_pending"] is False


def test_a_step_that_may_leave_camp_forgets_the_scribe(tmp_path, scribe_measured):
    game, d = _scribe_camp(tmp_path)
    d.scribe(6, "PROTECTION FROM GOOD")
    d.step_begins("display")
    assert d.rest(5)["scribe_pending"] is False


def test_a_frame_that_changes_outside_the_text_is_not_a_rejection(tmp_path,
                                                                 scribe_measured):
    game, d = _scribe_camp(tmp_path, start=4, swallow_pick=True, flicker=True)
    got = d.scribe(6, "PROTECTION FROM GOOD")
    assert got["pick_presses"] == 2 and game.scribed == ["PROTECTION FROM GOOD"]


def test_a_rejection_no_capture_saw_fails_saying_it_may_be_one(tmp_path, scribe_measured):
    game, d = _scribe_camp(tmp_path, start=4, block={"PROTECTION FROM GOOD"},
                           unseen=True)
    with pytest.raises(da.StepFailed, match="no mark and no change was seen, possibly "
                       "a rejection"):
        d.scribe(6, "PROTECTION FROM GOOD")
    assert game.keys[5:] == ["m", "s", "s", "s"] and game.scribed == []


def test_a_rejection_drawn_after_the_wait_is_read_before_a_second_key(tmp_path,
                                                                     scribe_measured):
    game, d = _scribe_camp(tmp_path, start=4, block={"PROTECTION FROM GOOD"},
                           late=True)
    with pytest.raises(da.StepFailed, match="YOU ALREADY KNOW THAT SPELL"):
        d.scribe(6, "PROTECTION FROM GOOD")
    assert game.keys[5:] == ["m", "s", "s"]


def test_a_wanted_screen_that_comes_late_is_taken_without_another_key(
        tmp_path, scribe_measured):
    game, d = _scribe_camp(tmp_path, start=4, lag=1)
    d.scribe(6, "PROTECTION FROM GOOD")
    assert game.keys[5:] == ["m", "s", "s", "e", "e", "y", "e"]
    assert game.mode == "camp" and game.scribed == ["PROTECTION FROM GOOD"]


def test_an_unknown_screen_after_yes_stops_the_step_with_nothing_more_pressed(
        tmp_path, scribe_measured):
    game, d = _scribe_camp(tmp_path, start=4, after_yes=True)
    with pytest.raises(da.StepFailed, match="YES put up a screen that is not magic"):
        d.scribe(6, "PROTECTION FROM GOOD")
    assert game.keys[-1] == "y" and not d.scribing


@pytest.mark.parametrize("kind,pending", [
    ("save", True), ("shot", True), ("read", True), ("scribe", True),
    ("camp", False), ("leave", False), ("display", False), ("walk", False),
    ("cast", False), ("press", False)])
def test_only_the_steps_that_keep_camp_keep_a_scribe_pending(tmp_path, scribe_measured,
                                                            kind, pending):
    game, d = _scribe_camp(tmp_path)
    d.scribing = True
    d.step_begins(kind)
    assert d.rest(5)["scribe_pending"] is pending


@pytest.mark.parametrize("title,said", [("ssb", True), ("pool", False)])
def test_a_list_key_that_moves_nothing_fails_naming_silver_blades_unmeasured_down(
        tmp_path, scribe_measured, title, said):
    game, d = _scribe_camp(tmp_path, title, stuck_list=True)
    with pytest.raises(da.StepFailed) as failed:
        d.scribe(6, "PROTECTION FROM GOOD")
    assert ("may not wrap there" in str(failed.value)) is said
    assert "s" not in game.keys[7:]


# -- Pool's ADD CHARACTER TO PARTY and the party menu's VIEW --------------------


#: The shipped `CHARLIST.TXT`, as the list drew it in #791's probe boot.
_ADD_LISTED = ("ARRONEL", "ARGORA", "KLYTUS RYTON", "FLORENTZ", "ORATISI NOMOON",
               "BRYTWYN")
_ADD_ITEMS = ("LONG SWORD", "SHIELD", "BANDED MAIL")


class FakeAddPool(FakePool):
    """Pool of Radiance from its title screens to the party menu and `ADD
    CHARACTER TO PARTY`, as #791's probe boot drew them: `Return` past two
    title screens; the menu over `CHOOSE A FUNCTION`, the roster from text row
    4 at column 1 with the current member highlighted and `End` moving it on,
    the functions from row 12 at column 2 (`VIEW CHARACTER` only with a
    member), `a` opening `ADD A CHARACTER: ADD EXIT`, the names from row 2,
    `End` and `Home` moving the highlight and wrapping, the arrows doing
    nothing and any other key picking: a picked row redraws as `* NAME` and
    the member joins unless named in `block`; `e` back to the menu.  `v`
    opens the current member's sheet, its bar offering `ITEMS` when `items`
    is not empty, `i` the list `<NAME>'S ITEMS` over `READY ...`, and
    `Escape` goes back a screen each time.

    `after_a` names a mode `a` opens instead of the list, `ignore_pick`
    makes the pick change nothing, `no_add` draws a menu without `ADD
    CHARACTER TO PARTY` and `sheet_of` draws another name on the sheet."""

    EMPTY = ("CREATE NEW CHARACTER", "ADD CHARACTER TO PARTY", "LOAD SAVED GAME",
             "EXIT TO DOS")
    FULL = ("CREATE NEW CHARACTER", "DROP CHARACTER", "MODIFY CHARACTER",
            "VIEW CHARACTER", "ADD CHARACTER TO PARTY", "REMOVE CHARACTER FROM PARTY",
            "SAVE CURRENT GAME", "BEGIN ADVENTURING", "EXIT TO DOS")

    def __init__(self, tmp, listed=_ADD_LISTED, block=(), ignore_pick=False,
                 after_a=None, no_add=False, items=_ADD_ITEMS, sheet_of=None,
                 encumbrance=True):
        super().__init__(tmp)
        self.mode, self.titles = "title", 2
        self.listed, self.block, self.ignore_pick = list(listed), set(block), ignore_pick
        self.after_a, self.no_add, self.items, self.sheet_of = after_a, no_add, items, sheet_of
        #: False draws the sheet without its ENCUMBRANCE row.
        self.encumbrance = encumbrance
        self.starred: set[str] = set()
        self.party: list[str] = []
        self.hl, self.line = 0, 1

    def key(self, k, gap=0.0):
        self.keys.append(k)
        m = self.mode
        if m == "title" and k == "Return":
            self.titles -= 1
            if self.titles <= 0:
                self.mode = "menu"
        elif m == "menu" and k == "a" and not self.no_add:
            self.mode, self.hl = self.after_a or "list", 0
        elif m == "menu" and k == "End" and self.party:
            self.line = self.line % len(self.party) + 1
        elif m == "menu" and k == "v" and self.party:
            self.mode = "sheet"
        elif m == "list" and k in ("End", "Home"):
            self.hl = (self.hl + (1 if k == "End" else -1)) % len(self.listed)
        elif m == "list" and k == "e":
            self.mode = "menu"
        elif m == "list" and k not in ("Up", "Down", "Left", "Right"):
            name = self.listed[self.hl]
            if not self.ignore_pick and name not in self.starred:
                self.starred.add(name)
                if name not in self.block:
                    self.party.append(name)
        elif m == "sheet" and k == "i" and self.items:
            self.mode = "items"
        elif m == "sheet" and k == "Escape":
            self.mode = "menu"
        elif m == "items" and k == "Escape":
            self.mode = "sheet"

    def member(self) -> str:
        return self.party[self.line - 1]

    def capture(self):
        px = bytearray(W * H * 3)
        m = self.mode
        if m == "title":
            _text(px, 10, 10, "POOL OF RADIANCE")
        elif m == "menu":
            _text(px, da.BAR_ROW, 0, "CHOOSE A FUNCTION")
            for n, name in enumerate(self.party, 1):
                _text(px, 3 + n, 1, name, _CYAN,
                      reverse=screens.POD_NAME_CELLS if n == self.line else 0)
            menu = self.FULL if self.party else self.EMPTY
            for r, entry in enumerate(e for e in menu
                                      if not (self.no_add and e.startswith("ADD"))):
                _text(px, 12 + r, 2, entry)
        elif m == "list":
            _text(px, da.BAR_ROW, 0, "ADD A CHARACTER: ADD EXIT")
            for r, name in enumerate(self.listed):
                text = ("* " if name in self.starred else "") + name
                _text(px, 2 + r, 1, text, reverse=38 if r == self.hl else 0)
        elif m == "sheet":
            _text(px, da.BAR_ROW, 0, "VIEW:ITEMS TRADE DROP EXIT" if self.items
                  else "VIEW:TRADE DROP EXIT")
            _text(px, 1, 1, self.sheet_of or self.member())
            _text(px, 7, 1, "STR 16         GOLD 83")
            _text(px, 17, 1, "AC 0    THAC0 20" + ("     ENCUMBRANCE 593"
                                                    if self.encumbrance else ""))
        elif m == "items":
            _text(px, da.BAR_ROW, 0, "READY TRADE DROP HALVE JOIN EXIT")
            _text(px, 1, 1, f"{self.member()}'S ITEMS")
            _text(px, 3, 1, "READY ITEM")
            for r, item in enumerate(self.items):
                _text(px, 5 + r, 2, f"YES  {item}")
        else:
            _text(px, da.BAR_ROW, 0, "PRESS ANY KEY TO CONTINUE")
        return dosbox.Screen(W, H, bytes(px))


@pytest.fixture
def add_measured(monkeypatch, tmp_path):
    """The stand-in font for Pool's own, found in a directory standing in for
    the archives."""
    monkeypatch.setattr(dosbox, "find_game", lambda stem="POOLRAD": tmp_path)
    monkeypatch.setattr(da, "load_font", lambda game: _FONT)


def _add_boot(tmp_path, **kw) -> tuple[FakeAddPool, da.Driver]:
    (tmp_path / "game").mkdir()
    game = FakeAddPool(tmp_path / "game", **kw)
    d = da.Driver(game, lambda **k: None, "A", "pool")
    d.logged = []
    d.note = lambda **k: d.logged.append(k)
    return game, d


def _after_menu(game: FakeAddPool) -> list[str]:
    """The keys pressed after the title screens' `Return`s."""
    keys = list(game.keys)
    while keys and keys[0] == "Return":
        keys.pop(0)
    return keys


def test_the_add_step_parses_a_name_of_several_words_and_blocks_a_bad_one():
    step = da.parse_step("add klytus ryton")
    assert (step.kind, step.name) == ("add", "KLYTUS RYTON")
    for bad in ("add", "add *ARRONEL", "add ABCDEFGHIJKLMNOP"):
        with pytest.raises(ValueError):
            da.parse_step(bad)


@pytest.mark.parametrize("title,steps,why", [
    ("pool", ("load", "add ARRONEL"), "add needs the party menu before any load"),
    ("pool", ("add ARRONEL", "begin"), "begin is for the titles"),
    ("pool", ("add ARRONEL", "camp"), "camp needs begin first"),
    ("pool", ("view 1",), "view needs load first"),
    ("curse", ("add ARRONEL",), "add is driven in pool only"),
])
def test_add_is_the_first_step_of_a_pool_run_at_the_party_menu(title, steps, why):
    da.validate_steps([da.parse_step(s) for s in
                       ("add ARRONEL", "add ARGORA", "view 2", "save D")], "pool")
    with pytest.raises(ValueError, match=why):
        da.validate_steps([da.parse_step(s) for s in steps], title)


def test_add_walks_to_the_named_row_picks_it_and_finds_him_on_the_roster(
        tmp_path, add_measured):
    game, d = _add_boot(tmp_path)
    got = d.add("KLYTUS RYTON")
    assert _after_menu(game) == ["a", "End", "End", "Return", "e"]
    assert game.party == ["KLYTUS RYTON"] and game.mode == "menu"
    assert got["list"] == list(_ADD_LISTED) and got["row"] == 3
    assert got["picked"][2] == "* KLYTUS RYTON" and got["roster"] == ["KLYTUS RYTON"]
    assert (d.where, d.party_size, d.line) == ("party", 1, 1)
    assert d.on_party_menu()


def test_a_second_add_starts_at_the_party_menu_and_the_view_reads_it(
        tmp_path, add_measured):
    game, d = _add_boot(tmp_path)
    d.add("ARRONEL")
    game.keys.clear()
    got = d.add("ARGORA")
    assert game.keys == ["a", "End", "Return", "e"]
    assert got["roster"] == ["ARRONEL", "ARGORA"] and d.party_size == 2
    game.keys.clear()
    seen = d.view(2)
    assert game.keys == ["End", "v", "i", "Escape", "Escape"]
    assert seen["name"] == "ARGORA" and game.mode == "menu"


@pytest.mark.parametrize("kw,why,last", [
    ({"after_a": "wrong"}, "not 'ADD A CHARACTER: ADD EXIT'", "a"),
    ({"listed": ("ARGORA", "BRYTWYN")}, "ARRONEL is not on the list", "a"),
    ({"ignore_pick": True}, "never redrew as '\\* ARRONEL'", "Return"),
    ({"block": ("ARRONEL",)}, "left him out of the party", "e"),
    ({"no_add": True}, "not the party menu offering ADD CHARACTER TO PARTY", "Return"),
])
def test_add_stops_at_the_screen_that_is_not_the_one_its_key_belongs_to(
        tmp_path, add_measured, kw, why, last):
    game, d = _add_boot(tmp_path, **kw)
    with pytest.raises(da.StepFailed, match=why):
        d.add("ARRONEL")
    assert game.keys[-1] == last
    if last == "Return" and "no_add" in kw:
        assert _after_menu(game) == []


def test_pool_view_reads_the_sheet_and_the_items_and_returns_to_the_party_menu(
        tmp_path, add_measured):
    game, d = _add_boot(tmp_path)
    d.add("ARRONEL")
    game.keys.clear()
    got = d.view(1)
    assert game.keys == ["v", "i", "Escape", "Escape"]
    assert got["encumbrance"] == 593 and got["items_offered"]
    assert [i["name"] for i in got["items"]] == list(_ADD_ITEMS)
    assert all(i["ready"] and not i["marked"] for i in got["items"])
    assert game.mode == "menu" and d.where == "party"


def test_pool_view_of_a_member_carrying_nothing_leaves_the_sheet_at_once(
        tmp_path, add_measured):
    game, d = _add_boot(tmp_path, items=())
    d.add("ARRONEL")
    game.keys.clear()
    got = d.view(1)
    assert game.keys == ["v", "Escape"]
    assert got["items"] is None and not got["items_offered"]


def test_pool_view_blocks_a_sheet_drawing_another_name(tmp_path, add_measured):
    game, d = _add_boot(tmp_path, sheet_of="ARGORA")
    d.add("ARRONEL")
    game.keys.clear()
    with pytest.raises(da.StepFailed, match="the sheet's name is 'ARGORA'"):
        d.view(1)
    assert game.keys == ["v"]


def _shipped_save(folder: pathlib.Path) -> pathlib.Path:
    folder.mkdir(parents=True)
    for name in ("ARRONEL.CHA", "ARRONEL.ITM", "ARRONEL.SPC", "ARGORA.CHA",
                 "CHRDATA1.SAV", "CHRDATA1.ITM", "SAVGAMA.DAT"):
        (folder / name).write_bytes(name.encode())
    (folder / "CHARLIST.TXT").write_bytes(b"ARRONEL\r\nARGORA\r\n")
    return folder


def test_the_exports_and_their_list_are_staged_without_the_saved_games(tmp_path):
    shipped = _shipped_save(tmp_path / "shipped")
    (tmp_path / "SAVE").mkdir()
    got = da.stage_exports(tmp_path / "SAVE", shipped)
    assert sorted(p.name for p in (tmp_path / "SAVE").iterdir()) == [
        "ARGORA.CHA", "ARRONEL.CHA", "ARRONEL.ITM", "ARRONEL.SPC", "CHARLIST.TXT"]
    assert got["listed"] == ["ARRONEL", "ARGORA"]
    da.check_exports(shipped, ["ARRONEL"])
    with pytest.raises(ValueError, match="lists \\['ARRONEL', 'ARGORA'\\]"):
        da.check_exports(shipped, ["BRYTWYN"])


def test_a_run_that_begins_with_add_stages_the_exports_into_an_emptied_save(
        monkeypatch, tmp_path):
    log = _fake_run(monkeypatch, tmp_path)
    _shipped_save(tmp_path / "game" / "SAVE")
    stale = tmp_path / "session" / "SAVE" / "SAVGAMB.DAT"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"archives")
    seen = {}

    def add(self, name):
        seen[name] = sorted(p.name for p in (tmp_path / "session" / "SAVE").iterdir())
        return {"name": name}

    monkeypatch.setattr(da.Driver, "add", add, raising=False)
    assert da.run(_run_args(tmp_path, ["add ARRONEL"])) == 0
    assert seen["ARRONEL"] == ["ARGORA.CHA", "ARRONEL.CHA", "ARRONEL.ITM",
                               "ARRONEL.SPC", "CHARLIST.TXT"]
    summary = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert summary["exports"]["listed"] == ["ARRONEL", "ARGORA"]
    assert log == ["claim", "close", "release"]


def test_an_add_the_shipped_list_lacks_is_blocked_before_a_slot_is_claimed(
        monkeypatch, tmp_path):
    log = _fake_run(monkeypatch, tmp_path)
    _shipped_save(tmp_path / "game" / "SAVE")
    with pytest.raises(ValueError, match="add BRYTWYN: .*CHARLIST.TXT lists"):
        da.run(_run_args(tmp_path, ["add BRYTWYN"]))
    assert log == []


@pytest.mark.parametrize("argv,why", [
    (["--steps", "load"], "one of --save"),
    (["--steps", "add ARRONEL", "read"], "installs none"),
    (["--xp", "1=5", "--steps", "add ARRONEL"], "nothing to stage"),
])
def test_only_a_run_that_begins_with_add_takes_no_save(monkeypatch, capsys, argv, why):
    ran = []
    monkeypatch.setattr(da, "run", lambda args: ran.append(args) or 0)
    assert da.main(["--steps", "add ARRONEL", "view 1", "save D"]) == 0
    assert len(ran) == 1
    with pytest.raises(SystemExit):
        da.main(argv)
    assert why in capsys.readouterr().err and len(ran) == 1


def test_an_add_is_blocked_before_the_claim_when_the_save_folder_is_missing(
        monkeypatch, tmp_path):
    log = _fake_run(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="SAVE is not a directory"):
        da.run(_run_args(tmp_path, ["add ARRONEL"]))
    assert log == []


def test_an_add_is_blocked_when_the_list_names_the_character_twice(tmp_path):
    shipped = _shipped_save(tmp_path / "shipped")
    (shipped / "CHARLIST.TXT").write_bytes(b"ARRONEL\r\nARGORA\r\nARRONEL\r\n")
    da.check_exports(shipped, ["ARGORA"])
    with pytest.raises(ValueError, match="lists it 2 times"):
        da.check_exports(shipped, ["ARRONEL"])


def test_pool_view_fails_on_a_sheet_with_no_encumbrance_row(tmp_path, add_measured):
    game, d = _add_boot(tmp_path, encumbrance=False)
    d.add("ARRONEL")
    game.keys.clear()
    with pytest.raises(da.StepFailed, match="no ENCUMBRANCE row"):
        d.view(1)
    assert game.keys == ["v"]


def test_the_add_walk_stops_at_the_deadline_before_moving(tmp_path, add_measured):
    now = [0.0]
    game, d = _add_boot(tmp_path)
    d.deadline = da.Deadline(lambda: now[0], 300)
    now[0] = 1000.0
    with pytest.raises(da.DeadlineReached, match="walk"):
        d.add("KLYTUS RYTON")
    assert _after_menu(game) == ["a"]


@pytest.mark.parametrize("extra", [["--from-slot", "B"], ["--first-bar-key", "q"]])
def test_a_run_with_no_save_blocks_a_slot_or_a_fight_key(monkeypatch, capsys, extra):
    monkeypatch.setattr(da, "run", lambda args: 0)
    with pytest.raises(SystemExit):
        da.main([*extra, "--steps", "add ARRONEL", "view 1"])
    assert "a run with no save has neither" in capsys.readouterr().err


# -- Pool's ITEMS list bar, in each of the forms the game draws --------------

def _lettered_bar(text: str, monkeypatch) -> dosbox.Screen:
    """A frame whose bar spells `text`, each letter its own synthetic cell,
    with `BAR_LETTERS` pointed at those cells."""
    pattern = {c: 0 if c == " " else 0x11 + 7 * i
               for i, c in enumerate(sorted(set(" ABCDEFGHIJKLMNOPQRSTUVWXYZ")))}
    bar = bytes(pattern[c] for c in text)
    cells = {pattern[c]: c for c in pattern}
    letters = {}
    for p, c in cells.items():
        sample = _screen(bytes([p]), b"")
        letters[sample.glyphs((0, dosbox.BAR[1], screens.CELL, dosbox.BAR[3]))] = c
    monkeypatch.setattr(screens, "BAR_LETTERS", letters)
    return _screen(bar, b"")


@pytest.mark.parametrize("bar", [
    "READY USE TRADE DROP HALVE JOIN EXIT",
    "READY USE TRADE DROP JOIN EXIT",
    "READY USE DROP HALVE JOIN EXIT",
])
def test_every_pool_items_bar_form_is_an_items_list(bar, monkeypatch):
    screen = _lettered_bar(bar, monkeypatch)
    assert screens.bar_words(screen) == bar.split()
    assert screens.on_items_list(screen)


@pytest.mark.parametrize("bar", [
    "ITEMS TRADE DROP EXIT",               # a sheet's bar
    "READY USE TRADE DROP HALVE JOIN",     # no EXIT
    "USE TRADE DROP JOIN EXIT",            # no READY
    "READY DROP USE EXIT",                 # out of order
    "READY USE SHOP EXIT",                 # a word Pool's list never draws
    "",
])
def test_other_bars_are_not_pool_items_lists(bar, monkeypatch):
    screen = _lettered_bar(bar.ljust(3), monkeypatch)
    assert not screens.on_items_list(screen)


def test_an_unread_cell_is_not_an_items_list(monkeypatch):
    screen = _lettered_bar("READY USE EXIT", monkeypatch)
    monkeypatch.setattr(screens, "BAR_LETTERS", {})
    assert screens.bar_words(screen) is None and not screens.on_items_list(screen)


@pytest.mark.parametrize("run,name,issue", [
    ("type0", "005-lost-items-2-list", "790"),
    ("type0b", "008-fatima-items", "790"),
    ("df335e745f-pool-dm-permanent", "005-items-2-list", "666"),
])
def test_the_captured_pool_items_lists_are_recognised(run, name, issue):
    screen = _capture(run, name, issue)
    assert screens.on_items_list(screen)
    assert screens.is_pool_items_bar(screen)


@pytest.mark.parametrize("run,name,issue", [
    ("type0", "004-items-2-sheet", "790"),
    ("type0", "003-camp", "790"),
    ("type0", "001-menu", "790"),
])
def test_a_captured_pool_sheet_camp_and_menu_are_not_items_lists(run, name, issue):
    assert not screens.on_items_list(_capture(run, name, issue))


def test_every_items_bar_word_is_spelled_by_the_real_letter_table():
    letters = set(screens.BAR_LETTERS.values())
    for word in screens.POOL_ITEMS_WORDS:
        assert set(word) <= letters, word


def test_a_captured_drop_prompt_is_not_an_items_list():
    import shutil
    import subprocess

    from tools.registry.scratch import cache_dir
    shot = cache_dir("790", "drop-in-camp", "shots", "009-after-d.png")
    if not shot.exists() or shutil.which("convert") is None:
        pytest.skip("the captured drop prompt is not on this machine")
    screen = dosbox.Screen.from_ppm(subprocess.run(
        ["convert", str(shot), "-depth", "8", "ppm:-"], check=True,
        capture_output=True).stdout)
    assert not screens.on_items_list(screen)


# -- Pool's load onto the party menu ------------------------------------------


_POOL_LADDER = ("WISHFTR", "WISHCLE", "WISHMAG", "WISHTHI", "WISHDWF", "WISHHEL")


class FakePartyLoadPool(FakeAddPool):
    """Pool of Radiance whose `LOAD SAVED GAME` puts the party back on the
    party menu, as #736's cast boot 1 drew it for a save made there: `l` opens
    `LOAD WHICH GAME`, the slot letter fills the roster and leaves `CHOOSE A
    FUNCTION` up, `b` (`BEGIN ADVENTURING`) opens the map, and `e` at the
    menu (`EXIT TO DOS`) asks `QUIT TO DOS YES NO`.  `lands` names what the
    slot letter opens instead of the menu, and `begins` what `b` opens
    instead of the map."""

    MAP = "AREA CAST VIEW ENCAMP SEARCH LOOK"

    def __init__(self, tmp, lands="menu", begins="map"):
        super().__init__(tmp)
        self.mode, self.titles = "menu", 0
        self.lands, self.begins = lands, begins

    def key(self, k, gap=0.0):
        m = self.mode
        if m == "menu" and k == "l":
            self.keys.append(k)
            self.mode = "which"
        elif m == "which" and k == "d":
            self.keys.append(k)
            self.party = list(_POOL_LADDER)
            self.mode = self.lands
        elif m == "menu" and k == "b" and self.party:
            self.keys.append(k)
            self.mode = self.begins
        elif m == "menu" and k == "e":
            self.keys.append(k)
            self.mode = "quit"
        elif m == "map" and k == "e":
            self.keys.append(k)
            self.mode = "camp"
        elif m in ("which", "quit", "map", "camp", "other"):
            self.keys.append(k)
        else:
            super().key(k, gap)

    def capture(self):
        bars = {"which": "LOAD WHICH GAME: D", "quit": "QUIT TO DOS YES NO",
                "map": self.MAP, "camp": "CAMP: SAVE VIEW MAGIC REST ALTER EXIT",
                "other": "PRESS ANY KEY TO CONTINUE"}
        if self.mode not in bars:
            return super().capture()
        px = bytearray(W * H * 3)
        _text(px, da.BAR_ROW, 0, bars[self.mode])
        return dosbox.Screen(W, H, bytes(px))


def _map_sig() -> str:
    px = bytearray(W * H * 3)
    _text(px, da.BAR_ROW, 0, FakePartyLoadPool.MAP)
    return screens.bar_signature(dosbox.Screen(W, H, bytes(px)))


def _party_load(tmp_path, monkeypatch, **kw) -> tuple[FakePartyLoadPool, da.Driver]:
    monkeypatch.setattr(da, "POOL_MAP_BARS", {"town": _map_sig()})
    (tmp_path / "game").mkdir()
    game = FakePartyLoadPool(tmp_path / "game", **kw)
    d = da.Driver(game, lambda **k: None, "D", "pool")
    d.logged = []
    d.note = lambda **k: d.logged.append(k)
    d.game.to_main_menu = lambda timeout=120.0: None
    return game, d


def test_a_pool_load_onto_the_party_menu_is_not_the_map_and_camp_presses_nothing(
        tmp_path, monkeypatch, add_measured):
    """#736's cast boot 1: slot D loaded onto the party menu, the load took
    it for the map, and `camp` pressed `e`, which there is EXIT TO DOS."""
    game, d = _party_load(tmp_path, monkeypatch)
    got = d.load()
    assert game.mode == "menu" and game.keys == ["l", "d"]
    assert got["landed"] == "party" and d.where == "party"
    assert got["roster"] == list(_POOL_LADDER)
    assert "BEGIN ADVENTURING" in got["functions"]
    assert "map_bar" not in got and d.world_sig is None
    with pytest.raises(da.StepFailed, match="party menu is showing, not the map"):
        d.camp()
    assert game.keys == ["l", "d"] and game.mode == "menu"


def test_pool_begin_after_a_party_menu_load_reaches_the_map_and_camps(
        tmp_path, monkeypatch, add_measured):
    game, d = _party_load(tmp_path, monkeypatch)
    d.load()
    got = d.begin()
    assert game.keys == ["l", "d", "b"] and game.mode == "map"
    assert d.where == "map" and got["map_kind"] == "town"
    assert got["map_bar"] == _map_sig()
    d.camp()
    assert game.mode == "camp" and game.keys[-1] == da.ENCAMP


def test_pool_begin_stops_on_a_screen_that_is_not_a_measured_map(
        tmp_path, monkeypatch, add_measured):
    game, d = _party_load(tmp_path, monkeypatch, begins="quit")
    d.load()
    with pytest.raises(da.StepFailed, match="'QUIT TO DOS YES NO'.*lost-begin-screen"):
        d.begin()
    assert game.keys == ["l", "d", "b"]


def test_a_pool_load_onto_an_unknown_screen_stops_naming_its_bar(
        tmp_path, monkeypatch, add_measured):
    game, d = _party_load(tmp_path, monkeypatch, lands="other")
    with pytest.raises(da.StepFailed, match="neither a measured map bar.*"
                       "'PRESS ANY KEY TO CONTINUE'.*lost-load-screen"):
        d.load()
    assert game.keys == ["l", "d"] and d.where == "boot"


def test_pool_camp_presses_nothing_off_a_measured_map_bar(
        tmp_path, monkeypatch, add_measured):
    """Whatever the step before claimed, ENCAMP goes out only on a bar of
    `POOL_MAP_BARS`: the quit prompt here is where the party menu's `e` led."""
    game, d = _party_load(tmp_path, monkeypatch)
    game.mode, d.where = "quit", "map"
    with pytest.raises(da.StepFailed, match="'QUIT TO DOS YES NO'.*lost-camp"):
        d.camp()
    assert game.keys == []


def test_pool_begin_is_accepted_only_straight_after_load():
    ok = [da.parse_step(s) for s in ("load", "shot party", "begin", "camp", "save D", "read")]
    da.validate_steps(ok, "pool")
    for steps in (("load", "camp", "begin"), ("load", "turn 1", "begin"),
                  ("add ARRONEL", "begin")):
        with pytest.raises(ValueError, match="begin is for the titles"):
            da.validate_steps([da.parse_step(s) for s in steps], "pool")


def test_the_captured_party_menu_load_reads_as_the_party_menu(monkeypatch):
    """#736's cast boot 1 shots, read with Pool's own font: the loaded screen
    is the party menu offering BEGIN ADVENTURING, on no map bar, and the
    screen its `e` opened is the quit prompt.  Skips without the captures or
    the archives."""
    monkeypatch.undo()
    loaded = _capture("cast", "002-loaded", issue="736", sub=("boot1",))
    quit_prompt = _capture("cast", "003-camp", issue="736", sub=("boot1",))
    try:
        font = da.load_font(dosbox.find_game("POOLRAD"))
    except (OSError, LookupError) as e:
        pytest.skip(f"Pool of Radiance's archives are not on this machine: {e}")
    assert screens.bar_signature(loaded) not in da.POOL_MAP_BARS.values()
    assert "BEGIN ADVENTURING" in da.party_menu_entries(loaded, font)
    assert da.party_roster(loaded, font) == list(_POOL_LADDER)
    assert da.text_row(quit_prompt, da.BAR_ROW, font).strip() == "QUIT TO DOS YES NO"


class _RedrawingPool(FakePool):
    """Pool whose map is still being redrawn for the first `redraws`
    captures: the bar row shows something else until then."""

    BARS = {**FakePool.BARS, "redraw": b"\x42\x24\x18"}

    def __init__(self, tmp, redraws=1):
        super().__init__(tmp)
        self.redraws = redraws

    def capture(self):
        if self.redraws > 0:
            self.redraws -= 1
            return _screen(self.BARS["redraw"], b"")
        return super().capture()


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_camp_waits_out_a_redraw_before_judging_the_map(tmp_path):
    """A capture taken while the map is still being drawn is not the screen
    camp judges: once the map bar is up, ENCAMP goes out."""
    game = _RedrawingPool(tmp_path)
    d = da.Driver(game, lambda **k: None, "A", "pool")
    d.where = "map"
    got = d.camp()
    assert game.keys == [da.ENCAMP] and game.mode == "camp"
    assert got["camp_bar"] == screens.bar_signature(_screen(FakePool.BARS["camp"], b""))


@pytest.mark.usefixtures("pool_map_measured")
def test_pool_begin_after_a_load_onto_the_map_presses_nothing(tmp_path, monkeypatch):
    game, d = _pool_continue_driver(tmp_path, monkeypatch, 0)
    d.load()
    assert d.where == "map"
    with pytest.raises(da.StepFailed, match="this load put the party on the map"):
        d.begin()
    assert game.keys == []


# -- Silver Blades' ITEMS at the party menu: `join` and `trade` -----------------


class FakeSsbItems(FakeCurseMenu):
    """Silver Blades' party menu, `PICK CHARACTER`, the sheet and its `ITEMS`,
    as a driven boot met them: `i` opens
    the list on row 1 with every row drawn `NO` and its name; `Down` moves the
    highlight; `j` joins the row with the next one of the same name; `t` asks
    `TRADE WITH WHOM?` over the roster with the trader highlighted, where
    `Down` moves and `s` gives the item away and brings the list back; `e`
    leaves the list for the sheet.  `dead_trade` makes `t` do nothing."""

    BARS = {**FakeCurseMenu.BARS, "items": b"\x2b\x2c", "whom": b"\x3d\x3f\x41"}

    def __init__(self, tmp, lists, dead_trade=False):
        super().__init__(tmp)
        self.lists, self.dead_trade = lists, dead_trade
        self.item_row, self.whom = 0, 1

    def key(self, k, gap=0.0):
        m = self.mode
        if m == "sheet" and k == "i":
            self.keys.append(k)
            self.mode, self.item_row = "items", 0
        elif m == "items":
            self.keys.append(k)
            rows = self.lists[self.line]
            if k == "Down":
                self.item_row = min(self.item_row + 1, len(rows) - 1)
            elif k == "j":
                at = self.item_row
                other = next((i for i in range(at + 1, len(rows))
                              if rows[i] == rows[at]), None)
                if other is not None:
                    rows[at] = "JOINED " + rows[at]
                    del rows[other]
            elif k == "t" and not self.dead_trade:
                self.mode, self.whom = "whom", self.line
            elif k == "e":
                self.mode = "sheet"
        elif m == "whom":
            self.keys.append(k)
            if k == "Down":
                self.whom = self.whom % self.size + 1
            elif k == "s":
                self.lists[self.whom].append(self.lists[self.line].pop(self.item_row))
                self.mode, self.item_row = "items", 0
        else:
            super().key(k, gap)

    def capture(self):
        if self.mode == "whom":
            return _with_roster(_screen(self.BARS["whom"], bytes((self.whom,))),
                                "party", self.size, self.whom)
        if self.mode != "items":
            return super().capture()
        px = bytearray(_screen(self.BARS["items"], b"").px)
        for k, name in enumerate(self.lists[self.line]):
            row = da.ITEM_TEXT_ROW + k
            _draw(px, _FONT_BLOCK, row, 2, "NO", _EFFECT_INK)
            _draw(px, _FONT_BLOCK, row, 7, name, _EFFECT_INK)
            if k == self.item_row:
                for dx in range(16, 16 + 200):
                    at = ((row * 8 + 5) * W + dx) * 3
                    px[at:at + 3] = da.POINTER_INK
        return dosbox.Screen(W, H, bytes(px))


@pytest.fixture
def ssb_trade_bar(monkeypatch):
    """The fake's `TRADE WITH WHOM?` bar stands in for the measured one."""
    monkeypatch.setattr(da, "SSB_TRADE_BAR", screens.bar_signature(
        _screen(FakeSsbItems.BARS["whom"], b"")))


def _ssb_items_driver(tmp_path, **kw):
    lists = {1: ["ARROWS", "ARROWS", "QUARTER STAFF"],
             2: ["DARTS"] * 3 + ["MAGE SCROLL", "MAGE SCROLL"],
             3: [], 4: [], 5: [], 6: []}
    game = FakeSsbItems(tmp_path, lists, **kw)
    game.mode = "party"
    asked = []

    class Ssb:
        def menu(self, row, label):
            asked.append(row)
            game.mode = "pick"

        def wait_bar(self, want, timeout=45.0):
            asked.append(want)
            return game.capture()

    d = da.Driver(game, lambda **k: None, "A", "ssb", party_size=game.size)
    d._ssb, d._font = Ssb(), _FONT
    d.where = "party"
    d.party_sig = screens.bar_signature(game.capture())
    return game, d, asked


def test_the_trade_step_parses_with_a_line_a_row_and_a_member():
    got = da.parse_step("trade 1 3 2")
    assert (got.kind, got.line, got.row, got.to) == ("trade", 1, 3, 2)
    for bad, why in (("trade 1 3 1", "trade with itself"), ("trade 1 19 2", "rows 1 to"),
                     ("trade 9 1 2", "not a step"), ("trade 1 1", "not a step"),
                     ("trade 1 1 9", "not a step")):
        with pytest.raises(ValueError, match=why):
            da.parse_step(bad)


def test_silver_blades_joins_and_trades_at_the_party_menu_and_saves_there():
    da.validate_steps(_steps("load", "join 2 4", "trade 1 3 2", "view 2", "save B",
                             "read"), "ssb")
    with pytest.raises(ValueError, match="join needs the party menu"):
        da.validate_steps(_steps("load", "begin", "camp", "join 2 4"), "ssb")
    with pytest.raises(ValueError, match="trade needs the party menu"):
        da.validate_steps(_steps("load", "begin", "trade 1 3 2"), "ssb")


@pytest.mark.parametrize("title,steps,why", [
    ("pool", ("load", "camp", "join 1 1"), "join is driven in darkness, ssb only"),
    ("curse", ("load", "join 1 1"), "join is driven in darkness, ssb only"),
    ("darkness", ("load", "begin", "camp", "trade 1 1 2"), "trade is driven in ssb only"),
    ("ssb", ("load", "halve 1 1"), "halve is driven in darkness only"),
])
def test_join_and_trade_are_blocked_where_they_are_not_driven(title, steps, why):
    with pytest.raises(ValueError, match=why):
        da.validate_steps(_steps(*steps), title)


def test_silver_blades_join_reads_the_rows_as_text_and_ends_at_the_party_menu(tmp_path):
    game, d, asked = _ssb_items_driver(tmp_path)
    got = d.join(2, 4)
    assert asked == [route_silver_blades.MENU_AFTER["view"], "pick_character"]
    assert game.keys == ["Down", "s", "i"] + ["Down"] * 3 + ["j", "e", "e"]
    assert (got["rows_before"], got["rows_after"]) == (5, 4)
    assert got["highlight_before"] == got["highlight_after"] == 3
    assert got["texts_before"] == ["NO DARTS"] * 3 + ["NO MAGE SCROLL"] * 2
    assert got["texts_after"] == ["NO DARTS"] * 3 + ["NO JOINED MAGE SCROLL"]
    assert game.mode == "party" and d.where == "party"


def test_silver_blades_trade_gives_the_row_to_the_member_picked(tmp_path, ssb_trade_bar):
    game, d, _ = _ssb_items_driver(tmp_path)
    got = d.trade(1, 3, 2)
    assert game.keys == ["s", "i", "Down", "Down", "t", "Down", "s", "e", "e"]
    assert game.lists[1] == ["ARROWS", "ARROWS"]
    assert game.lists[2][-1] == "QUARTER STAFF"
    assert (got["rows_before"], got["rows_after"], got["to"]) == (3, 2, 2)
    assert got["texts_after"] == ["NO ARROWS", "NO ARROWS"]
    assert got["whom_presses"] == 1 and game.mode == "party"


def test_a_trade_that_asks_nothing_stops_before_any_select(tmp_path, ssb_trade_bar):
    game, d, _ = _ssb_items_driver(tmp_path, dead_trade=True)
    with pytest.raises(da.StepFailed, match="did not ask TRADE WITH WHOM"):
        d.trade(1, 1, 2)
    assert game.keys[-1] == "t" and game.mode == "items"


def test_join_off_the_party_menu_is_blocked_before_a_key(tmp_path):
    game, d, _ = _ssb_items_driver(tmp_path)
    d.where = "map"
    with pytest.raises(da.StepFailed, match="party menu"):
        d.join(2, 4)
    assert game.keys == []


@pytest.mark.parametrize("shot,rows,highlight,last", [
    ("035-control-before-join", 3, 0, "NO QUARTER STAFF"),
    ("039-control-after-join", 2, 0, "NO QUARTER STAFF"),
    ("080-scroll-before-join", 16, 14, "NO MAGE SCROLL"),
    ("084-scroll-after-join", 15, 14, "NO BUNDLE OF 2 SCROLLS"),
    ("131-last", 1, 0, "NO 20 ARROWS"),
    ("149-paine-16-heads-after-trade", 16, 0, "NO QUARTER STAFF"),
])
def test_the_dosjoin_items_lists_read_as_rows_and_text(shot, rows, highlight, last):
    """A driven boot: Guy's two stacks of ten arrows joined
    into one, PAINE's two mage scrolls into a bundle, and Guy's staff traded
    to PAINE, which made her sixteen rows."""
    from tools.dos import dosbox as real
    screen = _capture("cbea7c9243-dosjoin", shot, issue="432")
    try:
        font = da.load_font(real.find_game("SECRET"))
    except (FileNotFoundError, OSError):
        pytest.skip("needs the DOS Silver Blades archive for its font")
    assert screens.item_rows(screen) == rows
    assert screens.item_highlight(screen) == highlight
    texts = [" ".join(da.text_row(screen, da.ITEM_TEXT_ROW + k, font,
                                  da.DISPLAY_COLUMNS).split()) for k in range(rows)]
    assert texts[-1] == last


@pytest.mark.parametrize("shot,line", [("125-last", 1), ("128-last", 2)])
def test_the_trade_prompt_is_known_by_its_bar_and_draws_the_party_roster(shot, line):
    screen = _capture("cbea7c9243-dosjoin", shot, issue="432")
    assert screens.bar_signature(screen) == da.SSB_TRADE_BAR
    assert screens.roster_line(screen, "party", 6) == line


# -- snapshot and restore steps --------------------------------------------------


def test_snapshot_and_restore_steps_parse_and_name_a_snapshot():
    got = _steps("snapshot leg-1", "restore leg-1")
    assert [(s.kind, s.name) for s in got] == [("snapshot", "leg-1"), ("restore", "leg-1")]
    for bad in ("snapshot", "restore a b", "snapshot a/b", "snapshot "):
        with pytest.raises(ValueError):
            da.parse_step(bad)


def test_a_restore_needs_its_snapshot_and_no_save_between():
    da.validate_steps(_steps("load", "snapshot a", "walk I", "restore a",
                             "camp", "save D"), "pool")
    with pytest.raises(ValueError, match="no snapshot 'a'"):
        da.validate_steps(_steps("load", "restore a"), "pool")
    with pytest.raises(ValueError, match="a save came between"):
        da.validate_steps(_steps("load", "snapshot a", "camp", "save D", "restore a"),
                          "pool")
    # A snapshot taken after the save is clean again.
    da.validate_steps(_steps("load", "camp", "save D", "snapshot a", "restore a"),
                      "pool")
    with pytest.raises(ValueError, match="load first"):
        da.validate_steps(_steps("snapshot a"), "pool")


class _SnapSession(_Session):
    def __init__(self, tmp_path, log, changed=()):
        super().__init__(tmp_path, log)
        self.changed = list(changed)

    def snapshot(self, name):
        self.log.append(f"snapshot {name}")
        return self.dir / f"{name}.sav"

    def restore(self, name):
        self.log.append(f"restore {name}")
        return self.changed

    def settle(self, *a, **k):
        self.log.append("settle")


def _snap_driver(tmp_path, session):
    notes: list[dict] = []
    d = da.Driver(session, lambda **kw: notes.append(kw), "A", "pool")
    return d, notes


def test_the_driver_snapshots_and_restores_by_name_and_logs_the_changed_saves(tmp_path):
    log: list[str] = []
    d, notes = _snap_driver(tmp_path, _SnapSession(tmp_path, log, ["SAVGAMD.DAT"]))
    d.where, d.line, d.left_camp, d.scribing = "map", 2, False, False
    d.fights, d.combat_ds, d.sheets = 0, None, {1: "a"}
    first = d.snapshot("leg")
    d.where, d.line, d.left_camp, d.scribing = "camp", 5, True, True
    d.fights, d.combat_ds, d.sheets = 1, 0x1F00, {1: "a", 2: "b"}
    second = d.restore("leg")
    assert log == ["snapshot leg", "restore leg", "settle"]
    assert (d.where, d.line, d.left_camp, d.scribing) == ("map", 2, False, False)
    assert (d.fights, d.combat_ds, d.sheets) == (0, None, {1: "a"})
    assert first["name"] == "leg" and second["changed_saves"] == ["SAVGAMD.DAT"]
    assert [(n["event"], n["name"]) for n in notes] == [("snapshot", "leg"),
                                                         ("restore", "leg")]
    assert notes[1]["changed_saves"] == ["SAVGAMD.DAT"]


def test_plain_dosbox_stops_a_snapshot_step_with_a_message(tmp_path):
    d, _ = _snap_driver(tmp_path, _Session(tmp_path, []))
    with pytest.raises(da.StepFailed, match="needs DOSBox-X"):
        d.snapshot("leg")
    with pytest.raises(da.StepFailed, match="needs DOSBox-X"):
        d.restore("leg")


def test_a_snapshot_run_boots_snapshot_session_and_records_each_step(monkeypatch,
                                                                    tmp_path):
    _fake_run(monkeypatch, tmp_path)
    x_log: list[str] = []
    monkeypatch.setattr(da.dosboxx, "claim", lambda note="": _Slot(x_log))
    monkeypatch.setattr(da.dossnapshot, "SnapshotSession",
                        lambda slot, game: _SnapSession(tmp_path, x_log, ["SAVGAMD.DAT"]))

    class Snap:
        where = "boot"
        events: list = []

        def __init__(self, session, note, letter, *a, **k):
            self.s, self.note = session, note

        def step_begins(self, kind):
            pass

        def journal(self, label):
            return False

        def yes_no(self, label):
            return 0

        def press_continue(self, label):
            return 0

        def load(self):
            return {}

        def snapshot(self, name):
            return {"name": name, "path": str(self.s.snapshot(name))}

        def restore(self, name):
            return {"name": name, "changed_saves": self.s.restore(name)}

    monkeypatch.setattr(da, "Driver", Snap)
    args = _run_args(tmp_path, ["load", "snapshot s", "restore s"])
    assert da.run(args) == 0
    assert x_log[:2] == ["snapshot s", "restore s"]
    summary = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert [r["step"] for r in summary["results"]] == ["load", "snapshot s", "restore s"]
    assert summary["results"][2]["changed_saves"] == ["SAVGAMD.DAT"]


# -- --no-encounters ---------------------------------------------------------

class FakeEncounters:
    """Stands in for `dosnoencounters.NoEncounters`, logging into `events`."""

    def __init__(self, events, blocked=False):
        self.events, self.blocked = events, blocked

    def before_move(self):
        self.events.append("before_move")
        return []

    def check_save(self):
        self.events.append("check_save")
        if self.blocked:
            raise da.dosnoencounters.SaveBlocked("no_encounters is on")


def _walker_with_moves(tmp_path, monkeypatch, encounters=None):
    """A Pool map walker over the real `PoolOfRadiance.move`, replaced by a
    function that logs the key into `encounters.events` and moves the map."""
    events = [] if encounters is None else encounters.events
    game = PoolMap(tmp_path)

    def move(self, key, timeout=20.0):
        events.append(key)
        if key == "Up":
            game.x += 1
        else:
            game.facing = (game.facing + 1) % 4
        return True

    monkeypatch.setattr(dosbox.PoolOfRadiance, "move", move)
    d = da.Driver(game, lambda **k: None, "A", "pool", encounters=encounters)
    d.where = "map"
    d.world_ink = game.capture().ink(dosbox.BAR)
    d.world_sig = screens.bar_signature(game.capture())
    return events, d


def test_no_encounters_calls_before_move_before_every_move_key_of_a_walk(tmp_path, monkeypatch):
    events: list = []
    events, d = _walker_with_moves(tmp_path, monkeypatch, FakeEncounters(events))
    d.walk("MI")
    assert events == ["before_move", "Right", "before_move", "Right",
                      "before_move", "Up"]


def test_without_the_flag_no_encounter_call_is_made(tmp_path, monkeypatch):
    events, d = _walker_with_moves(tmp_path, monkeypatch)
    d.walk("MI")
    assert events == ["Right", "Right", "Up"]
    assert type(d.game) is dosbox.PoolOfRadiance


@pytest.mark.usefixtures("pool_map_measured")
def test_save_stops_the_run_while_the_switch_is_on_and_presses_nothing(tmp_path):
    events: list = []
    game = FakePool(tmp_path, keys=TITLE_KEYS["pool"])
    d = da.Driver(game, lambda **k: None, "A", "pool",
                  encounters=FakeEncounters(events, blocked=True))
    d.camp()
    pressed = list(game.keys)
    with pytest.raises(da.StepFailed, match="save stopped: no_encounters is on"):
        d.save("D")
    assert events == ["check_save"] and game.keys == pressed
    assert not (game.save_dir / "SAVGAMD.DAT").exists()


def test_the_flag_goes_with_a_title_that_has_a_switch_and_into_the_summary(
        monkeypatch, tmp_path):
    import json
    for bad in (["--speculative-encounters"],):
        with pytest.raises(SystemExit):
            da.main(["--save", ".", "--steps", "load", *bad])

    made = []

    class Switch:
        def __init__(self, session, title, save=None, log=None, speculative=False):
            made.append((title, save, speculative))

        def on(self):
            made.append("on")

        def report(self):
            return {"pointer": "2F00:0010", "writes": [], "resets": 0}

    log = _fake_run(monkeypatch, tmp_path, menu_error=TimeoutError("no menu"))
    monkeypatch.setattr(da.dosnoencounters, "NoEncounters", Switch)
    monkeypatch.setattr(da.dosboxx, "claim", dosbox.claim)
    monkeypatch.setattr(da.dosboxx, "XSession",
                        lambda slot, game: _Session(tmp_path, log))
    args = _run_args(tmp_path, ["load"])
    args.no_encounters, args.speculative_encounters = True, False
    assert da.run(args) == 1
    assert made == [("pool-of-radiance", None, False), "on"]
    summary = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert summary["no_encounters"] is True
    assert summary["no_encounters_report"] == {
        "pointer": "2F00:0010", "writes": [], "resets": 0}


def _real_switch(words, area=0x14):
    """A real `NoEncounters` over a dict of script words, standing in for the
    live variable array."""
    class Live:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def peek(self, address):
            return words.get(address, 0)

        def poke(self, address, value):
            words[address] = value

        def area(self):
            return area

    enc = da.dosnoencounters.NoEncounters.__new__(da.dosnoencounters.NoEncounters)
    enc.live = Live()
    enc.switch = da.dosnoencounters.EncounterSwitch(
        da.dosnoencounters.POOL, enc.live.peek, enc.live.poke, enc.live.area,
        lambda line: None)
    enc.writes, enc.areas, enc.resets = [], {}, 0
    enc.arming, enc.yield_history = 1, []
    return enc


def test_a_restore_re_arms_the_switch_so_the_next_walk_still_forces_the_gate(
        tmp_path, monkeypatch):
    gate = 0x4A80
    words = {gate: 4}
    log: list[str] = []

    class Session(_SnapSession):
        def restore(self, name):
            words[gate] = 4            # the machine holds the original again
            return super().restore(name)

    monkeypatch.setattr(dosbox.PoolOfRadiance, "move",
                        lambda self, key, timeout=20.0: True)
    enc = _real_switch(words)
    enc.on()
    notes: list[dict] = []
    d = da.Driver(Session(tmp_path, log), lambda **kw: notes.append(kw), "A",
                  "pool", encounters=enc)
    d.game.step()                       # walk: the gate is written
    assert words[gate] == 15
    d.snapshot("leg")
    d.restore("leg")
    assert words[gate] == 4
    d.game.step()                       # walk again: forced again, not yielded
    assert words[gate] == 15
    assert enc.switch.yielded == set()
    assert any(n["event"] == "no-encounters-reset" for n in notes)


@pytest.mark.parametrize("key", ["s", "S"])
def test_press_blocks_a_save_key_while_the_switch_is_on(tmp_path, key):
    events: list = []
    game = FakePool(tmp_path)
    d = da.Driver(game, lambda **k: None, "A", "pool",
                  encounters=FakeEncounters(events, blocked=True))
    with pytest.raises(da.StepFailed, match="save stopped"):
        d.press(key)
    assert events == ["check_save"] and game.keys == []


def test_press_of_another_key_is_not_stopped(tmp_path):
    events: list = []
    game = FakePool(tmp_path)
    d = da.Driver(game, lambda **k: None, "A", "pool",
                  encounters=FakeEncounters(events, blocked=True))
    d.press("Down")
    assert events == [] and game.keys == ["Down"]


def test_silver_blades_needs_the_speculative_flag_and_an_installed_save(capsys):
    with pytest.raises(SystemExit):
        da.main(["--title", "ssb", "--save", ".", "--steps", "load",
                 "--no-encounters"])
    assert "--speculative-encounters" in capsys.readouterr().err


def test_a_pool_item_row_with_no_name_reads_beside_the_named_rows(monkeypatch):
    rows = {5: "YES  LONG SWORD", 6: "NO", 7: "NO  * POTION", 8: "YES *", 9: ""}
    monkeypatch.setattr(da, "text_row", lambda screen, row, font, cols=None: rows[row])
    assert da.pool_item_list(None, {}) == [
        {"ready": True, "marked": False, "name": "LONG SWORD"},
        {"ready": False, "marked": False, "name": ""},
        {"ready": False, "marked": True, "name": "POTION"},
        {"ready": True, "marked": True, "name": ""},
    ]


def test_pool_party_place_logs_a_pty_error_as_unread(tmp_path):
    game, d = _memory_walker(tmp_path)
    notes = []
    d.note = lambda **k: notes.append(k)

    def broken():
        raise OSError(5, "Input/output error")

    d.place_reader = broken
    assert d.party_place("x") is None
    assert [n["event"] for n in notes] == ["place-unread"]


@pytest.mark.parametrize("steps, installed", [
    (["load", "prayer-watch 49"], False),
    (["load", "walk MI"], True),
    (["load", "turn 2"], True)])
def test_pool_run_installs_the_place_reader_only_for_a_walk_or_turn(
        monkeypatch, tmp_path, steps, installed):
    _fake_run(monkeypatch, tmp_path)
    made = []
    fake = da.Driver

    class Recording(fake):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.place_reader = object()
            made.append(self)

    for name in ("load", "walk", "turn", "prayer_watch"):
        monkeypatch.setattr(Recording, name, lambda self, *a: {}, raising=False)
    monkeypatch.setattr(da, "Driver", Recording)
    da.run(_run_args(tmp_path, steps))
    assert (made[0].place_reader is not None) is installed


def test_pool_walk_reads_memory_once_at_the_origin_and_once_per_hidden_screen(tmp_path):
    game, d = _memory_walker(tmp_path)
    d.walk("MI")
    assert game.halts == 1
    (tmp_path / "h").mkdir()
    game, d = _memory_walker(tmp_path / "h")
    _hide_on_turns(game, d)
    got = d.walk("MI")
    hidden = sum(s["square"] is None for s in got["screens"])
    assert hidden >= 2
    assert game.halts == 1 + hidden


def test_pool_walk_mi_with_a_hidden_origin_compares_each_turn_with_memory(tmp_path):
    game, d = _memory_walker(tmp_path)
    game.hide_square = True
    _hide_on_turns(game, d, shown_on=(1,))
    got = d.walk("MI")
    assert d.game.keys == ["Right", "Right", "Up"]
    assert [s["square"] is None for s in got["screens"][:3]] == [True, False, True]
    assert (got["place_before"]["x"], got["place_after"]["x"]) == (0, 1)


def test_pool_walk_mi_with_a_hidden_origin_fails_blocked_when_the_step_is_blocked(tmp_path):
    game, d = _memory_walker(tmp_path)
    game.hide_square = True
    d.game.blocked = True
    _hide_on_turns(game, d, shown_on=(1,))
    with pytest.raises(da.StepFailed, match="walk-blocked"):
        d.walk("MI")


def test_pool_walk_mi_with_a_hidden_origin_fails_when_a_turn_moved_the_party(tmp_path):
    game, d = _memory_walker(tmp_path)
    game.hide_square = True
    _hide_on_turns(game, d, shown_on=(1,))
    turn = d.game.turn_right

    def moving():
        game.x += 1
        return turn()

    d.game.turn_right = moving
    with pytest.raises(da.StepFailed, match="memory reads 1,5, it was 0,5"):
        d.walk("MI")


def test_pool_walk_i_with_a_hidden_origin_compares_a_shown_step_with_memory(tmp_path):
    game, d = _memory_walker(tmp_path)
    game.hide_square = True
    step = d.game.step

    def shown_step():
        game.hide_square = False
        return step()

    d.game.step = shown_step
    got = d.walk("I")
    assert got["square_before"] is None and got["square_after"] is not None
    assert (got["place_before"]["x"], got["place_after"]["x"]) == (0, 1)


# -- Pool's fight and `fight first-bar` (WISH-303) ------------------------------


def test_fight_first_bar_parses_for_every_fight_title():
    step = da.parse_step("fight first-bar")
    assert (step.kind, step.name, step.seconds) == ("fight", da.FIRST_BAR, 0)
    da.validate_steps([da.parse_step(s) for s in
                       ("load", "fight first-bar", "shot after", "read")], "pool")
    for title in ("curse", "ssb"):
        da.validate_steps([da.parse_step(s) for s in
                           ("load", "begin", "fight first-bar", "read")], title)
    with pytest.raises(ValueError, match="curse, pool, ssb only"):
        da.validate_steps([da.parse_step(s) for s in
                           ("load", "begin", "fight first-bar")], "darkness")


@pytest.mark.parametrize("after", ["camp", "press Return", "fight", "walk I",
                                   "snapshot x"])
def test_only_shot_and_read_may_follow_fight_first_bar(after):
    with pytest.raises(ValueError, match="only shot and read may come after fight"):
        da.validate_steps([da.parse_step(s) for s in
                           ("load", "fight first-bar", after)], "pool")


def test_a_second_pool_fight_in_one_boot_is_blocked():
    with pytest.raises(ValueError, match="hand-back key is unread"):
        da.validate_steps([da.parse_step(s) for s in ("load", "fight", "fight")],
                          "pool")


def test_a_first_bar_key_needs_a_fight_that_reaches_a_second_bar(tmp_path, monkeypatch,
                                                                  capsys):
    def claimed(*a, **k):
        raise AssertionError("an emulator slot was claimed")

    monkeypatch.setattr(da.dosbox, "claim", claimed)
    monkeypatch.setattr(da.dosboxx, "claim", claimed)
    with pytest.raises(SystemExit):
        da.main(["--title", "ssb", "--save", str(tmp_path), "--steps", "load",
                 "begin", "fight first-bar", "--first-bar-key", "SPACE",
                 "--out", str(tmp_path / "out")])
    assert "other than fight first-bar" in capsys.readouterr().err


def _pool_layout():
    return da.COMBAT_LAYOUTS["pool"]


def _layout_record(layout, name: str, side: int, quick: int, control: int, hp: int,
                   after: tuple[int, int] = (0, 0)) -> bytearray:
    rec = bytearray(max(layout.hp_at, layout.next_at + 3) + 1)
    rec[0] = len(name)
    rec[1:1 + len(name)] = name.encode()
    rec[layout.status_at:layout.status_at + 4] = bytes((0, 1, side, quick))
    rec[layout.control_at] = control
    rec[layout.hp_at] = hp
    seg, off = after
    rec[layout.next_at:layout.next_at + 4] = (off.to_bytes(2, "little")
                                              + seg.to_bytes(2, "little"))
    return rec


def _far(ptr: tuple[int, int]) -> bytes:
    seg, off = ptr
    return off.to_bytes(2, "little") + seg.to_bytes(2, "little")


def _pool_fight_memory() -> tuple[bytearray, dict, dict]:
    """A Pool fight in fake memory at Pool's own offsets: GUY and PAINE the
    player's, BRUTUS run by the computer (control 0xB3), a KOBOLD on side 1;
    the list from the party head runs on into the KOBOLD."""
    lay = _pool_layout()
    ptrs = {"GUY": (0x3000, 0x10), "PAINE": (0x3000, 0x200),
            "BRUTUS": (0x3000, 0x400), "KOBOLD": (0x3100, 0x10)}
    records = {
        ptrs["GUY"]: _layout_record(lay, "GUY", 0, 0, 0, 30, ptrs["PAINE"]),
        ptrs["PAINE"]: _layout_record(lay, "PAINE", 0, 0, 0, 25, ptrs["BRUTUS"]),
        ptrs["BRUTUS"]: _layout_record(lay, "BRUTUS", 0, 1, 0xB3, 9, ptrs["KOBOLD"]),
        ptrs["KOBOLD"]: _layout_record(lay, "KOBOLD", 1, 1, 0x80, 4),
    }
    ds = bytearray(0x10000)
    order = ("GUY", "PAINE", "BRUTUS", "KOBOLD")
    ds[lay.map_at + 3] = len(order) + 1
    for i, who in enumerate(order, 1):
        x, y = (9 + i, 12) if who != "KOBOLD" else (10, 6)
        ds[lay.map_at + 4 * i:lay.map_at + 4 * i + 4] = bytes((x, y, i, 1))
        ds[lay.array_at + 4 * i:lay.array_at + 4 * i + 4] = _far(ptrs[who])
    ds[lay.party_at:lay.party_at + 4] = _far(ptrs["GUY"])
    ds[lay.selected_at:lay.selected_at + 4] = _far(ptrs["PAINE"])
    return ds, records, ptrs


def test_pools_layout_is_the_one_its_game_ovr_combat_setup_writes():
    # Pool `GAME.OVR` 0xE1C2-0xE3D9: [0x5F2A] = 1, the list from [0x5D96]
    # through record +0x104, the pointer at 0x65B9+4i, the index at
    # 0x5F29+4i and the size at 0x5F2A+4i; `les di, [0x5D92]` at 202 sites.
    assert _pool_layout() == da.CombatLayout(
        map_at=0x5F27, array_at=0x65B9, selected_at=0x5D92, party_at=0x5D96,
        next_at=0x104, control_at=0x84, status_at=0x10C, hp_at=0x11B)
    assert da.dosfightwatch.PRAYER_LAYOUTS["pool"].party_list == _pool_layout().party_at
    assert da.dosfightwatch.PRAYER_LAYOUTS["pool"].next_record == _pool_layout().next_at
    assert da.dosfightwatch.PRAYER_LAYOUTS["pool"].side == _pool_layout().status_at + 2


def test_pools_layout_decodes_a_combat_window():
    ds, records, ptrs = _pool_fight_memory()
    lay = _pool_layout()
    lo, n = da.combat_window(lay)
    got = da.read_combat(bytes(ds[lo:lo + n]), lo, lay)
    assert got["count"] == 4 and got["selected"] == 2
    assert [c["position"] for c in got["combatants"]] == [[10, 12], [11, 12],
                                                          [12, 12], [10, 6]]
    assert got["party_head"] == list(ptrs["GUY"])
    brutus = da.combatant_record(bytes(records[ptrs["BRUTUS"]]), lay)
    assert (brutus["name"], brutus["side"], brutus["quickfight"], brutus["control"],
            brutus["hp"]) == ("BRUTUS", 0, 1, 0xB3, 9)


class FakePoolFight:
    """A DOS Pool session at the map, with a fight in memory.

    The walk is `dosfightwatch.walk_to_encounter`'s, replaced in the tests;
    it ends on the encounter menu.  `c` there opens GUY's command bar, `q`
    moves on to PAINE's and then to the win message, `Return` to the
    treasure, and `e` to the map.  Its bars are told apart by `kind`, which
    stands in for `PoolOfRadiance.bar_kind`'s measured digests.
    """

    BARS = {"map": b"\x11\x22\x33\x44", "encounter": b"\x51\x52",
            "bar1": b"\x61\x62\x63", "bar2": b"\x61\x62\x63",
            "won": b"\x71", "treasure": b"\x72\x73"}
    KINDS = {"encounter": "encounter", "bar1": "command", "bar2": "command",
             "won": "press_return", "treasure": "treasure"}

    def __init__(self, tmp_path):
        self.dir = tmp_path / "session"
        (self.dir / "shots").mkdir(parents=True)
        self.save_dir = self.dir / "SAVE"
        self.state, self.actor = "map", None
        self.keys: list[str] = []
        self.halts = 0
        self.ds, self.records, self.ptrs = _pool_fight_memory()

    def frame(self) -> dosbox.Screen:
        return _screen(self.BARS[self.state], b"")

    def kind(self, screen=None) -> str | None:
        screen = screen if screen is not None else self.frame()
        glyphs = screen.glyphs(dosbox.BAR)
        for state, bar in self.BARS.items():
            if _screen(bar, b"").glyphs(dosbox.BAR) == glyphs:
                return self.KINDS.get(state)
        return None

    def capture(self):
        return self.frame()

    grab = capture

    def settle(self, quiet=0.6, timeout=30.0):
        return self.frame()

    def wait_for(self, pred, timeout=30.0):
        return pred(self.frame())

    def wait_until_ink(self, rect, want, timeout=30.0):
        return self.frame().ink(rect) == want

    def wait_while_ink(self, rect, same, timeout=30.0):
        return self.frame().ink(rect) != same

    def wait_while_glyphs(self, rect, same, timeout=30.0):
        return self.frame().glyphs(rect) != same

    def shot(self, name, allow_blank=False):
        path = self.dir / "shots" / f"{name}.png"
        path.write_bytes(b"x")
        return path

    def key(self, *keys, gap=0.35):
        for k in keys:
            self.keys.append(k)
            step = {("encounter", "c"): ("bar1", "GUY"), ("bar1", "q"): ("bar2", "PAINE"),
                    ("bar2", "q"): ("won", None), ("won", "Return"): ("treasure", None),
                    ("treasure", "e"): ("map", None)}.get((self.state, k))
            if step is not None:
                self.state, actor = step
                if actor:
                    at = _pool_layout().selected_at
                    self.ds[at:at + 4] = _far(self.ptrs[actor])

    def attach(self):
        self.halts += 1
        return True

    def regs(self, *names):
        return {"DS": _DS}

    def read(self, addr, n):
        seg, off = addr
        if seg == _DS:
            return bytes(self.ds[off:off + n])
        return bytes(self.records[(seg, off)][:n])

    def run(self):
        pass


def _pool_fighter(tmp_path, monkeypatch, met=True):
    game = FakePoolFight(tmp_path)
    d = da.Driver(game, lambda **k: None, "D", "pool", party_size=3)
    d.logged = []
    d.note = lambda **k: d.logged.append(k)
    d.record_world(game.capture())
    d.where = "map"
    d.game.bar_kind = game.kind
    walks = []

    def walk(por, steps, **kw):
        walks.append(steps)
        if not met:
            return {"met": False, "why": "no encounter in the steps asked",
                    "walked": steps, "blocked": 0, "prompts": 0}
        game.state = "encounter"
        return {"met": True, "at_step": 3, "bar": "encounter", "walked": 2,
                "blocked": 1, "prompts": 0}

    monkeypatch.setattr(da.dosfightwatch, "walk_to_encounter", walk)
    return game, d, walks


def test_a_pool_fight_first_bar_logs_placement_and_stops_pressing_nothing_there(
        tmp_path, monkeypatch, fight_now):
    game, d, walks = _pool_fighter(tmp_path, monkeypatch)
    got = d.fight(first_bar=True)
    assert walks == [da.POOL_FIGHT_WALK_STEPS]
    assert game.keys == ["c"] and game.state == "bar1"
    assert d.where == "pressed"
    assert got["first_bar"] and got["bars"] == 1 and got["actor"]["name"] == "GUY"
    assert got["first_bar_shot"] is not None and got["ds"] == f"{_DS:04X}"
    rows = {c["name"]: c for c in got["placement"]}
    assert (rows["BRUTUS"]["control"], rows["BRUTUS"]["slot"], rows["BRUTUS"]["party"],
            rows["BRUTUS"]["position"]) == (0xB3, 2, True, [12, 12])
    assert (rows["KOBOLD"]["side"], rows["KOBOLD"]["party"]) == (1, False)
    assert len(_events(d, "placement")) == 1


def test_a_pool_fight_answers_its_bars_and_ends_on_the_map(tmp_path, monkeypatch,
                                                           fight_now):
    game, d, _ = _pool_fighter(tmp_path, monkeypatch)
    got = d.fight()
    assert game.keys == ["c", "q", "q", "Return", "e"] and game.state == "map"
    assert d.where == "map"
    assert got["actors"] == ["GUY", "PAINE"] and got["encounters"] == 1
    assert got["walked_before_fight"] == 2


def test_a_pool_fight_with_no_encounter_stops_the_run(tmp_path, monkeypatch):
    game, d, _ = _pool_fighter(tmp_path, monkeypatch, met=False)
    with pytest.raises(da.StepFailed, match="no encounter"):
        d.fight(first_bar=True)
    assert game.keys == []


def test_a_curse_or_silver_blades_fight_first_bar_stops_at_its_first_bar(
        tmp_path, fight_now):
    game, d = _fighter(tmp_path, key="space", intervene=True)
    got = d.fight(first_bar=True)
    # The walk, COMBAT, and nothing at the bar: no QUICK, no first-bar key,
    # no Alt+X, and move mode is not left.
    assert game.keys == ["m", "Up", "Up", "c"] and game.state == "bar1"
    assert d.where == "pressed"
    assert got["first_bar"] and got["actor"]["name"] == "GUY"
    assert len(got["placement"]) == 4 and got["walked_before_fight"] == 1


# -- Pool's I, J and K walk and `temple raise N` (WISH-303) ---------------------


class FakeTextScreen:
    """A frame as text rows (40 columns each), with the digests and the
    highlights the driver reads named after its state."""

    def __init__(self, state: str, rows: dict[int, str], list_row: int | None = None,
                 roster_row: int | None = 0):
        self.state, self.text_rows = state, rows
        self.list_row, self.roster_row = list_row, roster_row
        self.width, self.height = W, H

    def row_text(self, row: int, columns) -> str:
        line = self.text_rows.get(row, "")
        return "".join(line[c] if c < len(line) else " " for c in columns).rstrip()

    def ink(self, rect) -> str:
        return f"ink-{self.state}"

    def glyphs(self, rect) -> str:
        return f"glyphs-{self.state}"

    def flat(self, rect) -> bool:
        return False

    def digest(self, rect=None) -> str:
        return f"digest-{self.state}-{self.list_row}"

    def highlight_row(self, rect, row_height=8, minimum=10):
        if rect == da.TEMPLE_LIST_RECT:
            return self.list_row
        return self.roster_row


class FakeTextSession:
    """What the driver asks of a session, over `FakeTextScreen` frames that
    the subclass's `screen` draws and its `press` changes."""

    def __init__(self, tmp_path):
        self.dir = tmp_path / "session"
        (self.dir / "shots").mkdir(parents=True)
        self.save_dir = self.dir / "SAVE"
        self.keys: list[str] = []

    def capture(self):
        return self.screen()

    grab = capture

    def settle(self, quiet=0.6, timeout=30.0):
        return self.screen()

    def wait_for(self, pred, timeout=30.0):
        return pred(self.screen())

    def wait_until_ink(self, rect, want, timeout=30.0):
        return self.screen().ink(rect) == want

    def wait_while_ink(self, rect, same, timeout=30.0):
        return self.screen().ink(rect) != same

    def shot(self, name, allow_blank=False):
        path = self.dir / "shots" / f"{name}.png"
        path.write_bytes(b"x")
        return path

    def key(self, *keys, gap=0.35):
        for k in keys:
            self.keys.append(k)
            self.press(k)

    def attach(self):
        return True

    def run(self):
        pass


@pytest.fixture
def text_rows(monkeypatch):
    """`text_row` reads a `FakeTextScreen`'s rows, and no font is loaded."""
    monkeypatch.setattr(da, "text_row",
                        lambda screen, row, font, columns=range(40):
                        screen.row_text(row, columns))


def _text_driver(game) -> da.Driver:
    d = da.Driver(game, lambda **k: None, "D", "pool", party_size=6)
    d.logged = []
    d.note = lambda **k: d.logged.append(k)
    d._font = {}
    d.record_world(game.capture())
    d.where = "map"
    return d


class FakeWalk(FakeTextSession):
    """The map, with the party's place from a script: `places[i]` after the
    i-th move (x, y, area, facing); the step that is move `arrive` lands on
    the temple's question instead of the map."""

    def __init__(self, tmp_path, places, arrive=None):
        super().__init__(tmp_path)
        self.places, self.arrive, self.moves = list(places), arrive, 0
        self.state = "map"

    def screen(self):
        if self.state == "arrival":
            return FakeTextScreen("arrival", {17: "YOU ARE WELCOMED BY PRIESTESS JOY OF",
                                              18: "SUNE.' DO YOU SEEK HEALING?'",
                                              24: "YES NO"})
        return FakeTextScreen("map", {15: f"{self.moves},4 N 21:16", 24: "AREA CAST"})

    def press(self, key):
        pass

    def move(self, letter):
        self.keys.append(letter)
        self.moves += 1
        if letter == "I" and self.moves == self.arrive:
            self.state = "arrival"
            return False
        return True

    def place(self):
        x, y, area, facing = self.places[min(self.moves, len(self.places) - 1)]
        return {"x": x, "y": y, "area": area, "facing": facing}


def _walker(tmp_path, places, arrive=None):
    game = FakeWalk(tmp_path, places, arrive)
    d = _text_driver(game)
    d.place_reader = game.place
    d.game.step = lambda: game.move("I")
    d.game.turn_left = lambda: game.move("J")
    d.game.turn_right = lambda: game.move("K")
    return game, d


#: The C64 temple route's places from the Slums square, as (x, y, area,
#: facing), which DOS captures matched: two right turns, a step east into
#: New Phlan, a step, a left turn, and the step onto the temple's square.
_TEMPLE_WALK = [(15, 4, 20, 3), (15, 4, 20, 0), (15, 4, 20, 1), (0, 4, 0, 1),
                (1, 4, 0, 1), (1, 4, 0, 0), (1, 3, 0, 0)]


def test_pool_walk_letters_parse_and_validate():
    assert da.parse_step("walk KKIIJI").key == "KKIIJI"
    assert da.parse_step("walk kkiiji").key == "KKIIJI"
    da.validate_steps([da.parse_step(s) for s in ("load", "walk KKIIJI", "walk J",
                                                  "walk I", "walk MI")], "pool")
    with pytest.raises(ValueError, match="not a step"):
        da.parse_step("walk KX")
    with pytest.raises(ValueError, match="curse's walk is 'walk MI'"):
        da.validate_steps([da.parse_step(s) for s in ("load", "begin", "walk KKIIJI")],
                          "curse")


def test_a_pool_letter_walk_judges_each_move_by_the_place_in_memory(tmp_path,
                                                                   text_rows):
    game, d = _walker(tmp_path, _TEMPLE_WALK)
    got = d.walk("KKIIJI")
    assert game.keys == list("KKIIJI") and d.where == "map"
    assert [m["move"] for m in got["moves"]] == list("KKIIJI")
    assert got["crossings"] == [3]
    assert got["moves"][2]["before"] == [15, 4, 20] and got["moves"][2]["after"] == [0, 4, 0]
    assert got["arrival"] is None


def test_a_turn_that_moves_the_square_fails_the_walk(tmp_path, text_rows):
    places = [(15, 4, 20, 3), (15, 5, 20, 0)]
    game, d = _walker(tmp_path, places)
    with pytest.raises(da.StepFailed, match="square changed on a turn"):
        d.walk("KI")
    assert game.keys == ["K"]


def test_a_turn_that_changes_the_area_fails_the_walk(tmp_path, text_rows):
    game, d = _walker(tmp_path, [(15, 4, 20, 3), (15, 4, 0, 0)])
    with pytest.raises(da.StepFailed, match="square changed on a turn"):
        d.walk("KI")


def test_a_step_that_stays_on_its_square_fails_the_walk(tmp_path, text_rows):
    game, d = _walker(tmp_path, [(15, 4, 20, 3), (15, 4, 20, 3)])
    with pytest.raises(da.StepFailed, match="blocked step"):
        d.walk("IK")


def test_a_letter_walk_needs_the_place_from_memory(tmp_path, text_rows):
    game, d = _walker(tmp_path, _TEMPLE_WALK)
    d.place_reader = None
    with pytest.raises(da.StepFailed, match="DOSBox-X debugger"):
        d.walk("KKIIJI")
    assert game.keys == []


def test_only_the_last_step_may_end_off_the_map_and_it_is_the_arrival(tmp_path,
                                                                     text_rows):
    game, d = _walker(tmp_path, _TEMPLE_WALK, arrive=6)
    got = d.walk("KKIIJI")
    assert d.where == "arrival"
    assert "DO YOU SEEK HEALING" in got["arrival"]["text"]
    assert got["arrival"]["bar"] == "YES NO"
    game, d = _walker(tmp_path / "early", _TEMPLE_WALK[:5], arrive=3)
    with pytest.raises(da.StepFailed, match="map bar did not return after the step"):
        d.walk("KKII")
    assert game.keys == ["K", "K", "I"]


def test_temple_raise_parses_and_needs_the_map():
    step = da.parse_step("temple raise 1")
    assert (step.kind, step.name, step.line) == ("temple", "raise", 1)
    for bad in ("temple raise 9", "temple raise", "temple heal 1"):
        with pytest.raises(ValueError):
            da.parse_step(bad)
    da.validate_steps([da.parse_step(s) for s in
                       ("load", "walk KKIIJI", "temple raise 1", "sheet 1", "camp",
                        "save D", "read")], "pool")
    with pytest.raises(ValueError, match="temple raise needs the map"):
        da.validate_steps([da.parse_step(s) for s in
                           ("load", "camp", "temple raise 1")], "pool")
    with pytest.raises(ValueError, match="pool only"):
        da.validate_steps([da.parse_step(s) for s in
                           ("load", "begin", "temple raise 1")], "curse")


def test_temple_raise_at_runtime_needs_the_arrival_question(tmp_path, text_rows):
    game, d = _walker(tmp_path, _TEMPLE_WALK)
    with pytest.raises(da.StepFailed, match="arrival question"):
        d.temple_raise(1)
    assert game.keys == []


def _temple_args(**kw):
    import argparse
    base = dict(xp=[], add_node=[], stage_control=[], stage_side=[], stage_record=[],
                stage_var=[], stage_place=None)
    base.update(kw)
    return argparse.Namespace(**base)


def test_a_temple_run_stages_only_gold_and_constitution():
    steps = [da.parse_step(s) for s in ("load", "walk KKIIJI", "temple raise 1")]
    ok = _temple_args(stage_record=["1:0x8E=0x70,1:0x8F=0x17,1:0x14=18"])
    assert da.temple_staging_rejection(ok, steps) is None
    why = da.temple_staging_rejection(_temple_args(stage_record=["1:0x15=18"]), steps)
    assert "only gold (0x08E, 0x08F) and constitution (0x014)" in why
    assert "1:0x015" in why
    assert "--stage-control" in da.temple_staging_rejection(
        _temple_args(stage_control=["1=0x80"]), steps)
    assert "--stage-var" in da.temple_staging_rejection(
        _temple_args(stage_var=["4C2D=1"]), steps)
    assert "--stage-place" in da.temple_staging_rejection(
        _temple_args(stage_place="6,14,0"), steps)
    # Without a temple step nothing here limits the staging.
    assert da.temple_staging_rejection(_temple_args(stage_record=["1:0x15=18"]),
                                       steps[:2]) is None


def test_main_blocks_other_staging_with_temple_raise_before_any_boot(tmp_path,
                                                                    monkeypatch, capsys):
    def claimed(*a, **k):
        raise AssertionError("an emulator slot was claimed")

    monkeypatch.setattr(da.dosbox, "claim", claimed)
    monkeypatch.setattr(da.dosboxx, "claim", claimed)
    with pytest.raises(SystemExit):
        da.main(["--title", "pool", "--save", str(tmp_path), "--steps", "load",
                 "walk KKIIJI", "temple raise 1", "--stage-record", "1:0x10=18",
                 "--out", str(tmp_path / "out")])
    assert "temple raise stages only gold" in capsys.readouterr().err


_SERVICES = ["CURE BLINDNESS", "CURE DISEASE", "CURE LIGHT WOUNDS",
             "CURE SERIOUS WOUNDS", "CURE CRITICAL WOUNDS", "NEUTRALIZE POISON",
             "RAISE DEAD", "REMOVE CURSE", "STONE TO FLESH", "EXIT"]


class FakeTemple(FakeTextSession):
    """DOS Pool's temple as the captures drew it, from the arrival question.

    `y` there opens the temple bar; `v` the highlighted member's sheet and
    `Escape` back; `h` the service list (highlight on row 0, `End` moves it
    down); `h` on RAISE DEAD the price; `y` there pays, draws `result` for
    two looks and the list again; `e` from the list to the bar and from the
    bar to the map.  With `pays` the raise happens, as the game draws it:
    no message, hit points 1 on the roster and the money changed; without,
    `message` is drawn and nothing changes.
    """

    def __init__(self, tmp_path, pays=True, message=""):
        super().__init__(tmp_path)
        self.state, self.row, self.message, self.looks = "arrival", 0, message, 0
        self.pays, self.raised = pays, False

    def screen(self):
        s = self.state
        roster = {4: " " * 17 + f"BRUTUS           3  {1 if self.raised else 11:>2}",
                  5: " " * 17 + "MAGNUS           2   9"}
        if s == "map":
            return FakeTextScreen("map", {15: "1,3 N 21:18", 24: "AREA CAST"})
        if s == "arrival":
            return FakeTextScreen(s, {17: "YOU ARE WELCOMED BY PRIESTESS JOY OF",
                                      18: "SUNE.' DO YOU SEEK HEALING?'", 24: "YES NO"})
        if s == "bar":
            return FakeTextScreen(s, {**roster, 24: da.TEMPLE_BAR})
        if s == "sheet":
            # As drawn: the money ends at column 25 or before, and the
            # portrait's frame is column 27.
            money = " PLATINUM 101" if self.raised else "     GOLD 6000"
            return FakeTextScreen(s, {1: " BRUTUS", 7: f" STR 18(98){money}  |",
                                      8: " INT 16       SILVER 102" if not self.raised
                                      else " INT 16", 24: "VIEW:ITEMS TRADE DROP EXIT"})
        rows = {1: " BRUTUS, HOW CAN WE HELP YOU?", 24: da.TEMPLE_LIST_BAR,
                **{4 + i: f" {name}" for i, name in enumerate(_SERVICES)}}
        if s == "price":
            rows.update({17: " RAISE DEAD WILL ONLY COST 5500 GOLD",
                         18: " PIECES.", 24: da.TEMPLE_PRICE_BAR})
            return FakeTextScreen(s, rows, list_row=None)
        if s == "result":
            self.looks += 1
            if self.looks > 2:
                self.state = "list"
            if self.message:
                rows.update({18: f" {self.message}"})
        return FakeTextScreen("list", rows, list_row=self.row)

    def press(self, key):
        s = "list" if self.state == "result" else self.state
        step = {("arrival", "y"): "bar", ("bar", "v"): "sheet", ("sheet", "Escape"): "bar",
                ("bar", "h"): "list", ("list", "e"): "bar", ("bar", "e"): "map"}
        if (s, key) in step:
            self.state = step[(s, key)]
            if self.state == "list":
                self.row = 0
        elif s == "list" and key == "End":
            self.row += 1
        elif s == "list" and key == "h" and _SERVICES[self.row] == "RAISE DEAD":
            self.state = "price"
        elif s == "price" and key == "y":
            self.state, self.looks = "result", 0
            self.raised = self.pays


@pytest.fixture
def temple_now(monkeypatch):
    monkeypatch.setattr(da, "TEMPLE_RESULT_HOLD", 0.0)


def _temple(tmp_path, pays=True, message=""):
    game = FakeTemple(tmp_path, pays, message)
    game.state = "map"
    d = _text_driver(game)
    game.state = "arrival"
    d.where = "arrival"
    return game, d


def test_temple_raise_buys_raise_dead_and_leaves_to_the_map(tmp_path, text_rows,
                                                            temple_now):
    game, d = _temple(tmp_path)
    got = d.temple_raise(1)
    assert game.keys == ["y", "v", "Escape", "h"] + ["End"] * 6 + [
        "h", "y", "e", "v", "Escape", "e"]
    assert d.where == "map" and game.state == "map"
    assert (got["member"], got["price"], got["price_coin"], got["outcome"]) == (
        "BRUTUS", 5500, "GOLD", "alive")
    assert got["list_presses"] == 6 and got["messages"] == []
    assert (got["gold_before"], got["gold_after"]) == (6000, 0)
    assert got["money_before"] == {"GOLD": 6000, "SILVER": 102}
    assert got["money_after"] == {"PLATINUM": 101}
    assert got["roster_before"].endswith("11") and got["roster_after"].endswith(" 1")


@pytest.mark.parametrize("message, outcome", [
    ("NOT ENOUGH MONEY.", "no-money"), ("", "unknown"),
    ("THE GODS ARE SILENT", "unknown")])
def test_a_raise_that_did_not_happen_is_not_called_alive(tmp_path, text_rows,
                                                         temple_now, message, outcome):
    game, d = _temple(tmp_path, pays=False, message=message)
    got = d.temple_raise(1)
    assert got["outcome"] == outcome and got["roster_after"].endswith("11")


def test_temple_raise_stops_at_a_screen_it_does_not_know(tmp_path, text_rows,
                                                        temple_now):
    game, d = _temple(tmp_path)
    game.state = "bar"
    with pytest.raises(da.StepFailed, match="arrival question"):
        d.temple_raise(1)
    assert game.keys == []


def test_map_lets_camp_and_save_follow_a_press_in_darkness():
    with pytest.raises(ValueError, match="may come after a press"):
        da.validate_steps(_steps("load", "press j", "camp", "save E", "read"),
                          "darkness")
    da.validate_steps(_steps("load", "press j", "map", "camp", "save E", "read"),
                      "darkness")


@pytest.mark.parametrize("title,steps,text", [
    ("pool", ("load", "press j", "map"), "may come after a press"),
    ("curse", ("load", "press j", "map"), "may come after a press"),
    ("darkness", ("load", "map"), "map follows a press"),
    ("darkness", ("load", "press j", "map", "map"), "map follows a press"),
])
def test_map_is_for_darkness_straight_after_a_press(title, steps, text):
    with pytest.raises(ValueError, match=text):
        da.validate_steps(_steps(*steps), title)


def test_at_map_stops_on_a_bar_that_is_not_a_measured_map_bar(tmp_path):
    game, d = _pod_driver(tmp_path)
    game.mode = "camp"
    with pytest.raises(da.StepFailed, match="map"):
        d.at_map()
    assert d.where != "map"


def test_at_map_takes_the_dungeon_bar_as_the_world_bar(tmp_path):
    game, d = _pod_driver(tmp_path)
    d.logged = []
    d.note = lambda **k: d.logged.append(k)
    d.where = "pressed"
    game.mode = "map"
    got = d.at_map()
    assert d.where == "map" and got["map_kind"] == "dungeon"
    assert d.world_sig == da.POD_MAP_BARS["dungeon"] == got["map_bar"]
    assert [n["map"] for n in d.logged if n.get("event") == "map_bar"] == ["dungeon"]
