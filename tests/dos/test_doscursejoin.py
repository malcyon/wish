"""`tools/dos/acceptance.py`'s route to a Curse scripted join: `--stage-area`,
a `walk` that ends on a script's bar, and `answer WORD KEY [map]`.

The fake draws the map, the status line and each script bar as text in a
stand-in font, as DOS Curse draws them, with a line of the text window that
differs on every screen.  What is pinned: an answer presses its key only
when its word is read on the bar, and a bar without it stops the run with
nothing pressed; the last answer with `map` needs the map bar back and
counts the roster again; a walk ends on a script's bar only when an answer
comes next; the step orders that allow it; and `--stage-area`'s writes,
on built saves and on the player's own Curse archives and specimens.
"""

from __future__ import annotations

import math
import pathlib
import shutil

import pytest

from goldbox import areas, dos_savegame
from tools.dos import acceptance as da
from tools.dos import dosbox

W, H = 320, 200
#: A stand-in font: glyph i lights row 1 with i + 1 and row 2 with 0x81.
_FONT_BLOCK = b"".join(bytes((0, i + 1, 0x81, 0, 0, 0, 0, 0))
                       for i in range(da.FONT_GLYPHS))
_FONT = da.font_table(_FONT_BLOCK)
_WHITE, _GREEN = b"\xff\xff\xff", b"\x55\xff\x55"

MAP_BAR = "AREA CAST VIEW ENCAMP SEARCH LOOK"
#: The Pit join's bars after the walk's step, each with the key that answers
#: it, as `ECL11` $8A9B to $8D85 asks them.
SCRIPT = [("COMBAT ADVANCE WAIT FLEE PARLAY", "p"),
          ("HAUGHTY SLY NICE MEEK ABUSIVE", "n"),
          ("PRESS RETURN TO CONTINUE", "Return"),
          ("SELECT", "Return"),
          ("PRESS RETURN TO CONTINUE", "Return"),
          ("YES NO", "y"),
          ("PRESS RETURN TO CONTINUE", "Return")]
STEP = {0: (0, -1), 1: (1, 0), 2: (0, 1), 3: (-1, 0)}
#: A bar the fake draws as cells no glyph of the font matches.
NOISE = "#noise"
BOX = ("PRESS RETURN TO CONTINUE", "Return")
PARTY = ["ONE", "TWO", "THREE", "FOUR", "FIVE"]
JOINED = ["ALIAS", "DRAGONBAIT"]


def _draw(px: bytearray, row: int, col: int, text: str, ink: bytes) -> None:
    for i, ch in enumerate(text):
        if ch == " ":
            continue
        glyph = _FONT_BLOCK[(ord(ch.upper()) % 0x40) * 8:][:8]
        for dy, bits in enumerate(glyph):
            for dx in range(8):
                if bits & (0x80 >> dx):
                    at = (((row * 8) + dy) * W + (col + i) * 8 + dx) * 3
                    px[at:at + 3] = ink


class FakePit:
    """The Pit from 1,3 facing north: arrows turn, `Up` steps, and the step
    onto 1,4 runs `SCRIPT`, one bar at a time; only the bar's own key moves
    it on, and the last puts the two joined members on the roster."""

    def __init__(self, tmp_path, script=SCRIPT):
        self.x, self.y, self.f = 1, 3, 0
        self.script = list(script)
        self.at: int | None = None
        self.party = list(PARTY)
        self.keys: list[str] = []
        self.dir = tmp_path / "session"
        (self.dir / "shots").mkdir(parents=True)
        self.save_dir = self.dir / "SAVE"

    def frame(self) -> dosbox.Screen:
        px = bytearray(W * H * 3)
        if self.at is None:
            _draw(px, da.BAR_ROW, 0, MAP_BAR, _GREEN)
            _draw(px, da.STATUS_ROW, da.STATUS_CELLS[0] + 1,
                  f"{self.x},{self.y} {'NESW'[self.f]} 01:15", _WHITE)
            x, y = da.POD_ROSTER["camp"]
            for line, name in enumerate(self.party):
                _draw(px, y // 8 + line, x // 8, name, _WHITE)
        elif self.script[self.at][0] == NOISE:
            # Cells lit everywhere but one pixel: no glyph of the font.
            for at in range(da.BAR_ROW * 8 * W, (da.BAR_ROW * 8 + 8) * W):
                if at % W < 24 and at % 7:
                    px[at * 3:at * 3 + 3] = _WHITE
            _draw(px, 17, 1, f"SCREEN {chr(0x41 + self.at)}", _WHITE)
        else:
            _draw(px, da.BAR_ROW, 0, self.script[self.at][0], _WHITE)
            _draw(px, 17, 1, f"SCREEN {chr(0x41 + self.at)}", _WHITE)
        return dosbox.Screen(W, H, bytes(px))

    def capture(self):
        return self.frame()

    def frame_at(self, at):
        was, self.at = self.at, at
        try:
            return self.frame()
        finally:
            self.at = was

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

    def shot(self, name, allow_blank=False):
        path = self.dir / "shots" / f"{name}.png"
        path.write_bytes(b"x")
        return path

    def key(self, *keys, gap=0.35):
        for k in keys:
            self.keys.append(k)
            if self.at is None and k in ("Left", "Right"):
                self.f = (self.f + (1 if k == "Right" else -1)) % 4
            elif self.at is None and k == "Up":
                dx, dy = STEP[self.f]
                self.x, self.y = self.x + dx, self.y + dy
                if (self.x, self.y) == (1, 4):
                    self.at = 0
            elif self.at is not None and k == self.script[self.at][1]:
                self.at += 1
                if self.at == len(self.script):
                    self.at = None
                    self.party += JOINED


@pytest.fixture
def font(monkeypatch):
    monkeypatch.setattr(da.Driver, "display_font", lambda self: _FONT, raising=False)


def _driver(game):
    d = da.Driver(game, lambda **k: None, "A", "curse", party_size=len(PARTY))
    d.logged = []
    d.note = lambda **k: d.logged.append(k)
    d.record_world(game.capture())
    d.where = "map"
    return d


def _on_script(tmp_path, script=SCRIPT):
    game = FakePit(tmp_path, script)
    d = _driver(game)
    game.at = 0
    d.where = "script"
    return game, d


# -- answer WORD KEY [map] ---------------------------------------------------

def test_an_answer_parses_its_word_key_and_map():
    step = da.parse_step("answer parlay p")
    assert (step.kind, step.name, step.key, step.then) == ("answer", "PARLAY", "p", "")
    step = da.parse_step("answer CONTINUE Return map")
    assert (step.name, step.key, step.then) == ("CONTINUE", "Return", da.ANSWER_MAP)


@pytest.mark.parametrize("bad", ["answer", "answer YES", "answer YES y camp",
                                 "answer YES y map now", "answer YES e",
                                 "answer NO Escape", "answer Y,ES y"])
def test_a_bad_answer_is_blocked(bad):
    with pytest.raises(ValueError):
        da.parse_step(bad)


JOIN_ROUTE = ["load", "begin", "walk MI", "answer PARLAY p", "answer NICE n",
              "answer CONTINUE Return", "answer SELECT Return", "answer YES y",
              "answer CONTINUE Return map", "camp", "save D", "sheet 6", "read"]


def test_the_join_route_validates_in_curse():
    da.validate_steps([da.parse_step(s) for s in JOIN_ROUTE], "curse")
    # A shot between the walk and the first answer is a capture, not a step.
    route = JOIN_ROUTE[:3] + ["shot pit"] + JOIN_ROUTE[3:]
    da.validate_steps([da.parse_step(s) for s in route], "curse")


@pytest.mark.parametrize("steps, title, match", [
    (JOIN_ROUTE, "pool", "answer is driven in curse only"),
    (["load", "begin", "answer YES y map"], "curse", "follows a walk"),
    (["load", "begin", "walk MI", "camp", "answer YES y map"], "curse",
     "follows a walk"),
    (["load", "begin", "walk MI", "answer YES y", "camp"], "curse",
     "only answer, shot and read"),
    (["load", "begin", "walk MI", "answer YES y", "press Return"], "curse",
     "only answer, shot and read"),
    (["load", "begin", "walk MI", "answer YES y map", "answer NO n map"], "curse",
     "follows a walk"),
])
def test_an_answer_out_of_order_is_blocked(steps, title, match):
    with pytest.raises(ValueError, match=match):
        da.validate_steps([da.parse_step(s) for s in steps], title)


@pytest.mark.parametrize("steps, index, follows", [
    (["walk MI", "answer YES y"], 0, True),
    (["walk MI", "shot a", "shot b", "answer YES y"], 0, True),
    (["walk MI", "camp"], 0, False),
    (["walk MI"], 0, False),
])
def test_a_walk_may_end_on_a_script_only_before_an_answer(steps, index, follows):
    assert da.answer_follows([da.parse_step(s) for s in steps], index) is follows


def test_the_answers_take_the_pit_join_to_the_map_and_count_the_roster(
        tmp_path, font):
    game, d = _on_script(tmp_path)
    for word, key in [("PARLAY", "p"), ("NICE", "n"), ("CONTINUE", "Return"),
                      ("SELECT", "Return"), ("CONTINUE", "Return"), ("YES", "y")]:
        got = d.answer(word, key)
        assert got["word"] == word and d.where == "script"
    got = d.answer("CONTINUE", "Return", da.ANSWER_MAP)
    assert game.keys == ["p", "n", "Return", "Return", "Return", "y", "Return"]
    assert d.where == "map" and game.at is None
    assert got["roster"] == PARTY + JOINED and d.party_size == 7


def test_a_bar_without_the_word_stops_the_run_with_nothing_pressed(tmp_path, font):
    game, d = _on_script(tmp_path)
    with pytest.raises(da.StepFailed, match="NICE is not on the bar"):
        d.answer("NICE", "n")
    assert game.keys == [] and game.at == 0


def test_an_answer_whose_key_changes_nothing_stops_the_run(tmp_path, font):
    game, d = _on_script(tmp_path)
    with pytest.raises(da.StepFailed, match="x changed nothing"):
        d.answer("PARLAY", "x")
    assert game.keys == ["x"] and game.at == 0


def test_an_answer_with_map_needs_the_map_bar_back(tmp_path, font):
    game, d = _on_script(tmp_path)
    with pytest.raises(da.StepFailed, match="map bar did not come back"):
        d.answer("PARLAY", "p", da.ANSWER_MAP)
    assert game.keys == ["p"] and game.at == 1


def test_an_answer_needs_a_script_bar_and_curse(tmp_path, font):
    game, d = _on_script(tmp_path)
    d.where = "map"
    with pytest.raises(da.StepFailed, match="needs a script's bar"):
        d.answer("PARLAY", "p")
    assert game.keys == []


# -- walk MI onto a scripted square -------------------------------------------

def _walker(tmp_path, monkeypatch):
    game = FakePit(tmp_path)
    d = _driver(game)
    squares = iter(["1,3", "1,3", "1,3", "1,4"])
    monkeypatch.setattr(d, "map_status", lambda label, screens: (
        screens.append({"label": label}) or ("status", next(squares))))
    return game, d


def test_a_walk_before_an_answer_ends_on_the_scripts_bar(tmp_path, monkeypatch, font):
    game, d = _walker(tmp_path, monkeypatch)
    got = d.walk("MI", onto_script=True)
    assert game.keys == ["Right", "Right", "Up"] and (game.x, game.y) == (1, 4)
    assert d.where == "script" and got["script_bar"] == SCRIPT[0][0].split()
    assert got["square_before"] == "1,3"


def test_a_walk_onto_a_script_answers_a_continue_box_before_the_first_menu(
        tmp_path, monkeypatch, font):
    game = FakePit(tmp_path, [BOX, BOX] + SCRIPT)
    d = _driver(game)
    game.at = 0
    monkeypatch.setitem(da.WALK_CONTINUE_BARS, "curse",
                        game.frame().glyphs(dosbox.BAR))
    got = d.walked_onto_script(game.frame(), "MI", "status", "1,3")
    assert game.keys == ["Return", "Return"] and game.at == 2
    assert got["script_bar"] == SCRIPT[0][0].split() and d.where == "script"


def _walk_onto(tmp_path, monkeypatch, script):
    game = FakePit(tmp_path, script)
    d = _driver(game)
    game.at = 0
    monkeypatch.setitem(da.WALK_CONTINUE_BARS, "curse",
                        FakePit(tmp_path / "box", [BOX]).frame_at(0).glyphs(dosbox.BAR))
    return game, d


@pytest.mark.parametrize("bar, why", [
    ("", "the bar stayed blank"),
    ("MOVE VIEW AIM USE CAST TURN QUICK DONE", "the step started combat"),
    (NOISE, "not a script's menu"),
])
def test_a_walk_onto_a_screen_that_is_no_scripts_menu_still_stops(
        tmp_path, monkeypatch, font, bar, why):
    game, d = _walk_onto(tmp_path, monkeypatch, [(bar, "Return")])
    with pytest.raises(da.StepFailed, match=why):
        d.walked_onto_script(game.frame(), "MI", "status", "1,3")
    assert game.keys == [] and d.where == "map"


def test_a_walk_answers_exactly_the_last_round_of_boxes_and_reaches_the_menu(
        tmp_path, monkeypatch, font):
    game, d = _walk_onto(tmp_path, monkeypatch, [BOX] * da.WALK_CONTINUE_ROUNDS + SCRIPT)
    got = d.walked_onto_script(game.frame(), "MI", "status", "1,3")
    assert game.keys == ["Return"] * da.WALK_CONTINUE_ROUNDS
    assert got["script_bar"] == SCRIPT[0][0].split() and d.where == "script"


def test_a_walk_whose_continue_boxes_outlast_the_rounds_stops(
        tmp_path, monkeypatch, font):
    game, d = _walk_onto(tmp_path, monkeypatch,
                         [BOX] * (da.WALK_CONTINUE_ROUNDS + 1) + SCRIPT)
    with pytest.raises(da.StepFailed, match="continue box is still showing"):
        d.walked_onto_script(game.frame(), "MI", "status", "1,3")
    assert game.keys == ["Return"] * da.WALK_CONTINUE_ROUNDS and d.where == "map"


class FakeBegin(FakePit):
    """The party menu, `PARTY_BEGIN`, then `boxes` continue boxes and the map."""

    def __init__(self, tmp_path, boxes):
        super().__init__(tmp_path, [("PARTY MENU", da.PARTY_BEGIN)] + [BOX] * boxes)
        self.at = 0


class FakeLoading(FakeBegin):
    """`FakeBegin` with the bars `loading` names after `PARTY_BEGIN`, each
    drawn for its number of frames before the boxes: by default
    `LOADING...PLEASE`, `WAIT` and a blank bar, three frames each."""

    def __init__(self, tmp_path, boxes, loading=(("LOADING...PLEASE", 3),
                                                  ("     WAIT", 3), ("", 3))):
        super().__init__(tmp_path, boxes)
        self.script[1:1] = [(bar, None) for bar, _ in loading]
        self.holds = [n for _, n in loading]
        self.frames = 0

    def frame(self):
        if self.at is not None and self.script[self.at][1] is None:
            self.frames += 1
            if self.frames > self.holds[self.at - 1]:
                self.frames = 0
                self.at += 1
        return super().frame()

    def wait_for(self, pred, timeout=30.0):
        """Poll every quarter second of `timeout`, as `Session.wait_for` does,
        with each poll one frame."""
        return any(pred(self.frame()) for _ in range(max(1, math.ceil(timeout / 0.25))))


def test_curse_begin_waits_out_the_loading_bar_before_the_boxes(
        tmp_path, monkeypatch, font):
    game = FakeLoading(tmp_path, 5)
    monkeypatch.setattr(da, "CURSE_CONTINUE_BAR", game.frame_at(4).glyphs(dosbox.BAR))
    d = da.Driver(game, lambda **k: None, "A", "curse", party_size=len(PARTY))
    d.logged = []
    d.note = lambda **k: d.logged.append(k)
    d.where = "party"
    d.begin()
    assert game.keys == [da.PARTY_BEGIN] + ["Return"] * 5
    assert game.at is None and d.where == "map"


def test_curse_begin_does_not_take_one_passing_frame_for_the_loaded_screen(
        tmp_path, monkeypatch, font):
    # BEGIN into the Pit draws `LOADING...PLEASE`, then `WAIT` alone on a
    # still frame; a frame caught mid-redraw (`...PLEASE` here) reads as
    # neither and must not end the wait.
    game = FakeLoading(tmp_path, 5, (("LOADING...PLEASE", 3), ("...PLEASE", 1),
                                     ("     WAIT", 6), ("", 3)))
    monkeypatch.setattr(da, "CURSE_CONTINUE_BAR", game.frame_at(5).glyphs(dosbox.BAR))
    d = da.Driver(game, lambda **k: None, "A", "curse", party_size=len(PARTY))
    d.logged = []
    d.note = lambda **k: d.logged.append(k)
    d.where = "party"
    d.begin()
    assert game.keys == [da.PARTY_BEGIN] + ["Return"] * 5
    assert game.at is None and d.where == "map"


def test_curse_begin_stops_when_the_bar_stays_on_wait(tmp_path, monkeypatch, font):
    game = FakeLoading(tmp_path, 5, (("LOADING...PLEASE", 3), ("     WAIT", 10 ** 6)))
    monkeypatch.setattr(da, "CURSE_LOAD_SECONDS", 2.0)
    d = da.Driver(game, lambda **k: None, "A", "curse", party_size=len(PARTY))
    d.logged = []
    d.note = lambda **k: d.logged.append(k)
    d.where = "party"
    with pytest.raises(da.StepFailed, match="still blank, LOADING or WAIT") as got:
        d.begin()
    assert "lost-begin-loading" in str(got.value)
    assert game.keys == [da.PARTY_BEGIN] and d.where == "party"


def test_curse_begin_answers_the_pits_five_arrival_boxes(tmp_path, monkeypatch, font):
    game = FakeBegin(tmp_path, 5)
    monkeypatch.setattr(da, "CURSE_CONTINUE_BAR", game.frame_at(1).glyphs(dosbox.BAR))
    d = da.Driver(game, lambda **k: None, "A", "curse", party_size=len(PARTY))
    d.logged = []
    d.note = lambda **k: d.logged.append(k)
    d.where = "party"
    d.begin()
    assert game.keys == [da.PARTY_BEGIN] + ["Return"] * 5
    assert game.at is None and d.where == "map"


def test_a_walk_with_no_answer_after_it_still_stops_off_the_map(
        tmp_path, monkeypatch, font):
    game, d = _walker(tmp_path, monkeypatch)
    with pytest.raises(da.StepFailed, match="map bar did not return after the step"):
        d.walk("MI")
    assert d.where == "map"


def test_the_run_tells_the_walk_an_answer_follows(monkeypatch, tmp_path):
    from tests.dos.test_dosacceptance import _fake_run, _run_args
    _fake_run(monkeypatch, tmp_path)
    walks, answers = [], []

    class Recording(da.Driver):
        def walk(self, route, **kw):
            walks.append(kw)
            return {}

        def answer(self, word, key, then=""):
            answers.append((word, key, then))
            return {}

    for name in ("load", "begin", "camp", "save"):
        monkeypatch.setattr(Recording, name, lambda self, *a: {}, raising=False)
    monkeypatch.setattr(da, "Driver", Recording)
    args = _run_args(tmp_path, ["load", "begin", "walk MI", "answer PARLAY p",
                                "answer YES y map", "camp", "walk MI"])
    args.title = "curse"
    da.run(args)
    assert walks == [{"onto_script": True}, {}]
    assert answers == [("PARLAY", "p", ""), ("YES", "y", da.ANSWER_MAP)]


# -- --stage-area ---------------------------------------------------------------

@pytest.mark.parametrize("text, area", [("11", 0x11), ("$11", 0x11), ("0x31", 0x31),
                                        ("A", 0x0A)])
def test_a_stage_area_parses_hex(text, area):
    assert da.parse_area(text) == area


@pytest.mark.parametrize("bad", ["", "0", "100", "G1", "1 1", "-1"])
def test_a_bad_stage_area_is_blocked(bad):
    with pytest.raises(ValueError):
        da.parse_area(bad)


def _script(*statements: bytes, tail: bytes = b"\x00" * 40) -> bytes:
    return bytes(dos_savegame.ECL_HEADER) + b"\x00" * 8 + b"".join(statements) + tail


#: `LOADFILES` and `LOADPIECES` as the Curse scripts number them, written
#: out here rather than taken from the driver.
LOADFILES, LOADPIECES = 0x21, 0x37


def _loadfiles(geo):
    return bytes((LOADFILES, 0, geo, 0, 2, 0, 255))


def _loadpieces(a, b, c):
    return bytes((LOADPIECES, 0, a, 0, b, 0, c))


def test_area_pieces_reads_the_map_and_wallset_the_script_loads():
    script = _script(_loadfiles(17), _loadpieces(3, 6, 7), b"\x01\x02",
                     _loadfiles(17), _loadpieces(3, 6, 7))
    assert da.area_pieces(script) == (17, (3, 6, 7))
    assert da.area_pieces(_script(_loadfiles(50), _loadpieces(12, 255, 255))) == (
        50, (12, dos_savegame.EMPTY, dos_savegame.EMPTY))


@pytest.mark.parametrize("statements", [
    (_loadfiles(17),),
    (_loadpieces(3, 6, 7),),
    (_loadfiles(17), _loadpieces(3, 6, 7), _loadpieces(3, 6, 8)),
    (_loadfiles(17), _loadfiles(18), _loadpieces(3, 6, 7)),
])
def test_area_pieces_blocks_a_script_without_one_map_and_one_wallset(statements):
    with pytest.raises(ValueError, match="one of each is wanted"):
        da.area_pieces(_script(*statements))


PIT = areas.area_in(0x11, areas.CURSE_OF_THE_AZURE_BONDS)
PIT_SCRIPT = _script(_loadfiles(17), _loadpieces(3, 6, 7), tail=b"\x5a" * 64)


def _curse_save(folder: pathlib.Path, letter="D", indoors=True) -> bytes:
    container = dos_savegame.SAVE_CURSE_OF_THE_AZURE_BONDS
    data = bytearray(container.size)
    dos_savegame.move_to_area(data, area=1, dax=2, geo=1, wallset=(1, 2, 3),
                              script=_script(_loadfiles(1), _loadpieces(1, 2, 3)),
                              container=container)
    dos_savegame.put_position(data, 3, 4, 3, container)
    dos_savegame.put_word(data, dos_savegame.INDOORS, int(indoors), container)
    (folder / f"SAVGAM{letter}.DAT").write_bytes(bytes(data))
    (folder / f"CHRDAT{letter}1.SAV").write_bytes(b"record")
    return bytes(data)


@pytest.fixture
def pit_script(monkeypatch, tmp_path):
    monkeypatch.setattr(da, "area_script", lambda game, area: (PIT, PIT_SCRIPT))
    monkeypatch.setattr(dosbox, "find_game", lambda stem: tmp_path / "game")


def test_stage_area_moves_the_save_into_the_pit(tmp_path, pit_script):
    container = dos_savegame.SAVE_CURSE_OF_THE_AZURE_BONDS
    _curse_save(tmp_path)
    got = da.stage_area(tmp_path, "D", 0x11, tmp_path / "game")
    data = (tmp_path / "SAVGAMD.DAT").read_bytes()
    assert dos_savegame.current_area(data) == 0x11
    assert dos_savegame.geo_block(data) == 17
    assert data[container.head] == PIT.disk == 3
    assert dos_savegame.word(data, dos_savegame.DISK, container) == 3
    assert dos_savegame.wall_block(data, container) == ((3, 6, 7), (1, 2, 3))
    assert not dos_savegame.outdoors(data)
    start, end = container.script_buffer
    body = PIT_SCRIPT[dos_savegame.ECL_HEADER:]
    assert data[start:start + len(body)] == body
    assert data[start + len(body):end] == bytes(end - start - len(body))
    assert dos_savegame.position(data, container)[:2] == (3, 4)
    assert got["after"] == {"area": 0x11, "geo": 17, "dax": 3, "wallset": [3, 6, 7]}
    assert got["before"]["area"] == 1
    assert (tmp_path / "CHRDATD1.SAV").read_bytes() == b"record"


def test_stage_area_blocks_a_pool_save(tmp_path, pit_script):
    (tmp_path / "SAVGAMD.DAT").write_bytes(bytes(13137))
    with pytest.raises(ValueError, match="moves a Curse save"):
        da.stage_area(tmp_path, "D", 0x11, tmp_path / "game")
    assert (tmp_path / "SAVGAMD.DAT").read_bytes() == bytes(13137)


def test_stage_area_blocks_a_script_whose_map_is_not_the_areas(tmp_path, monkeypatch):
    monkeypatch.setattr(da, "area_script", lambda game, area: (
        PIT, _script(_loadfiles(18), _loadpieces(3, 6, 7))))
    source = _curse_save(tmp_path)
    with pytest.raises(ValueError, match="loads GEO 18, not the GEO11"):
        da.stage_area(tmp_path, "D", 0x11, tmp_path / "game")
    assert (tmp_path / "SAVGAMD.DAT").read_bytes() == source


def test_the_command_line_stages_the_area_before_the_vars_and_the_place(
        tmp_path, pit_script):
    from tests.dos.test_dosacceptance import _run_args
    _curse_save(tmp_path, indoors=False)
    args = _run_args(tmp_path, [])
    args.title, args.stage_record = "curse", []
    args.stage_area, args.stage_var, args.stage_place = "11", ["4BF2=0x11"], "1,3,0"
    done = da.stage(tmp_path, "D", args)
    assert [d["stage"] for d in done] == ["area", "var", "place"]
    data = (tmp_path / "SAVGAMD.DAT").read_bytes()
    container = dos_savegame.SAVE_CURSE_OF_THE_AZURE_BONDS
    assert dos_savegame.current_area(data) == 0x11
    assert dos_savegame.word(data, dos_savegame.pool_address(0x4BF2, container),
                             container) == 0x11
    assert dos_savegame.position(data, container)[:2] == (1, 3)


@pytest.mark.parametrize("title, size, match", [
    ("pool", 13149, "--stage-area is driven in curse only"),
    ("curse", 13137, "not Curse of the Azure Bonds"),
    ("curse", 1234, "known saved-game size"),
])
def test_a_stage_area_the_save_cannot_take_is_blocked_before_a_slot_is_claimed(
        monkeypatch, tmp_path, title, size, match):
    from tests.dos.test_dosacceptance import _staged_run
    log, args = _staged_run(monkeypatch, tmp_path, stage_area="11")
    monkeypatch.setattr(da, "area_script", lambda game, area: (PIT, PIT_SCRIPT))
    args.title = title
    (tmp_path / "saves" / "SAVGAMA.DAT").write_bytes(bytes(size))
    with pytest.raises(ValueError, match=match):
        da.check_staging(args, tmp_path / "saves", "A")
    with pytest.raises(ValueError, match=match):
        da.run(args)
    assert "claim" not in log


def test_main_blocks_a_bad_stage_area_before_a_slot_is_claimed(
        tmp_path, monkeypatch, capsys):
    def claimed(*a, **k):
        raise AssertionError("an emulator slot was claimed")

    monkeypatch.setattr(da.dosbox, "claim", claimed)
    with pytest.raises(SystemExit):
        da.main(["--title", "curse", "--save", str(tmp_path), "--steps", "load",
                 "--stage-area", "G1", "--out", str(tmp_path / "out")])
    assert "G1" in capsys.readouterr().err


# -- the player's own archives and specimens -----------------------------------

def _curse_game() -> pathlib.Path:
    try:
        return dosbox.find_game("CURSE")
    except FileNotFoundError:
        pytest.skip("needs the DOS archives ($FR_ARCHIVES)")


@pytest.mark.parametrize("area, geo, wallset", [(0x11, 17, (3, 6, 7)),
                                                (0x01, 1, (1, 2, 3)),
                                                (0x02, 1, (1, 2, 4))])
def test_the_players_area_scripts_name_the_map_and_wallset(area, geo, wallset):
    where, script = da.area_script(_curse_game(), area)
    assert da.area_pieces(script) == (geo, wallset)
    assert geo in da._geo_numbers(where.geos)


def _curse_specimens() -> list[pathlib.Path]:
    from tools.registry import specimens
    root = specimens.tree_root() / "coab-dos"
    saves = sorted(root.glob("*/SAVGAM?.DAT")) if root.is_dir() else []
    saves = [p for p in saves if p.stat().st_size == 13149]
    if not saves:
        pytest.skip("needs $WISH_SPECIMENS/coab-dos")
    return saves


def test_every_indoor_curse_specimen_holds_its_scripts_wallset():
    game = _curse_game()
    held = 0
    for path in _curse_specimens():
        data = path.read_bytes()
        if dos_savegame.outdoors(data):
            continue
        _, script = da.area_script(game, dos_savegame.current_area(data))
        container = dos_savegame.SAVE_CURSE_OF_THE_AZURE_BONDS
        assert dos_savegame.wall_block(data, container)[0] == da.area_pieces(script)[1], path
        held += 1
    assert held


def test_stage_area_on_a_specimen_copy_names_the_pit(tmp_path):
    game = _curse_game()
    source = next(p for p in _curse_specimens()
                  if not dos_savegame.outdoors(p.read_bytes()))
    letter = source.stem[-1]
    folder = tmp_path / "save"
    folder.mkdir()
    shutil.copyfile(source, folder / source.name)
    was = source.read_bytes()
    da.stage_area(folder, letter, 0x11, game)
    data = (folder / source.name).read_bytes()
    container = dos_savegame.SAVE_CURSE_OF_THE_AZURE_BONDS
    _, script = da.area_script(game, 0x11)
    start, _ = container.script_buffer
    body = script[dos_savegame.ECL_HEADER:]
    assert data[start:start + len(body)] == body
    assert (dos_savegame.current_area(data), dos_savegame.geo_block(data)) == (0x11, 17)
    assert dos_savegame.wall_block(data, container)[0] == (3, 6, 7)
    assert source.read_bytes() == was
