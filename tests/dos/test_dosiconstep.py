"""`tools/dos/acceptance.py`'s `icon N` step and its `--stage-icon` staging.

The step is driven on a fake camp that draws each bar of the route as text in
a stand-in font, as the ICON editor's code in each title's `GAME.OVR` runs
it: `EXIT` asks `Is this icon ok?`, `Y` returns to the Alter bar and any
other answer opens the editor again.  What is pinned: the keys go out in
order and only on the bar they belong to, nothing that opens `Parts`, a
colour or `Size` (or saves) is pressed, and any screen the route does not
know stops the step with no further key.  The staging writes each title's
figure at the offsets its own overlay reads, written out here from the code
rather than taken from `goldbox.dos_port`.
"""

from __future__ import annotations

import pathlib

import pytest

from goldbox import dos_port
from tools.dos import acceptance as da
from tools.dos import dosbox, dospod, screens

W, H = 320, 200
#: A stand-in font: glyph i lights row 1 with i + 1 and row 2 with 0x81.
_FONT_BLOCK = b"".join(bytes((0, i + 1, 0x81, 0, 0, 0, 0, 0))
                       for i in range(da.FONT_GLYPHS))
_FONT = da.font_table(_FONT_BLOCK)
_WHITE, _CYAN, _GREEN = b"\xff\xff\xff", b"\x55\xff\xff", b"\x55\xff\x55"

#: Each title's bars as `START.EXE` spells them, upper-cased as the font
#: reads them.
BARS = {
    "pool": {"camp": "SAVE VIEW MAGIC REST ALTER EXIT",
             "alter": "ALTER:ORDER DROP SPEED ICON PICS EXIT",
             "icon": "ICON:PARTS COLOR-1 COLOR-2 SIZE EXIT"},
    "curse": {"camp": "SAVE VIEW MAGIC REST ALTER FIX EXIT",
              "alter": "ORDER DROP SPEED ICON PICS EXIT",
              "icon": "PARTS 1ST-COLOR 2ND-COLOR SIZE EXIT"},
    "ssb": {"camp": "SAVE VIEW MAGIC REST ALTER FIX EXIT",
            "alter": "ORDER DROP SPEED ICON LEVEL EXIT",
            "icon": "PARTS 1ST-COLOR 2ND-COLOR SIZE EXIT"},
    # Pools of Darkness spells its bars in `GAME.EXE`; its camp bar has no
    # `REST` (measured, `s10s-dev-darkness`).
    "darkness": {"camp": "SAVE VIEW MAGIC ALTER EXIT",
                 "alter": "ORDER DROP SPEED ICON LEVEL EXIT",
                 "icon": "PARTS 1ST-COLOR 2ND-COLOR SIZE EXIT"},
}
QUESTION = "IS THIS ICON OK? YES NO"
NEXT_KEY = {"pool": da.POOL_ROSTER_NEXT, "curse": da.CAMP_ROSTER_NEXT["curse"],
            "ssb": da.CAMP_ROSTER_NEXT["ssb"], "darkness": da.POD_ROSTER_NEXT}
NAMES = ("BRUTUS", "MAGNUS", "ROLAND")
#: The record sizes of the four titles, which name their layouts.
SIZES = {"pool": 285, "curse": 422, "ssb": 439, "darkness": 510}


def _draw(px: bytearray, row: int, col: int, text: str, ink: bytes) -> None:
    for i, ch in enumerate(text):
        glyph = _FONT_BLOCK[(ord(ch.upper()) % 0x40) * 8:][:8]
        for dy, bits in enumerate(glyph):
            for dx in range(8):
                if bits & (0x80 >> dx):
                    at = (((row * 8) + dy) * W + (col + i) * 8 + dx) * 3
                    px[at:at + 3] = ink


def _record(title: str, name: str) -> bytes:
    data = bytearray(SIZES[title])
    data[0] = len(name)
    data[1:1 + len(name)] = name.encode()
    return bytes(data)


class FakeIcon:
    """A camp with `ALTER > ICON` as the four overlays run it.

    `failure` breaks one screen of the route: `alter` (ALTER opens some other
    bar), `icon` (ICON does), `question` (EXIT asks nothing and goes back to
    camp), `direct` (Y returns to camp, not the Alter bar), `writes` (Y
    writes a file into the save folder), `differs` (the NEW figures are not
    the OLD ones), `alter-writes` (ALTER writes a file into the save folder
    and opens some other bar).
    """

    def __init__(self, tmp: pathlib.Path, title: str, failure: str = "",
                 names=NAMES):
        self.title, self.failure = title, failure
        self.bars = BARS[title]
        self.save_dir = tmp / "SAVE"
        self.save_dir.mkdir()
        for n, name in enumerate(names, 1):
            (self.save_dir / f"CHRDATA{n}.SAV").write_bytes(_record(title, name))
        self.names = list(names)
        self.mode = "camp"
        self.current = 1
        self.keys: list[str] = []
        self.opened: list[str] = []

    def key(self, k: str, gap: float = 0.0) -> None:
        self.keys.append(k)
        m = self.mode
        if m == "camp" and k == NEXT_KEY[self.title]:
            self.current = self.current % len(self.names) + 1
        elif m == "camp" and k == "a":
            if self.failure == "alter-writes":
                (self.save_dir / "SAVGAMA.DAT").write_bytes(b"\x01")
            self.mode = "wrong" if self.failure in ("alter", "alter-writes") else "alter"
        elif m == "alter" and k == "i":
            self.mode = "wrong" if self.failure == "icon" else "icon"
        elif m == "alter" and k == "e":
            self.mode = "camp"
        elif m == "icon" and k == "e":
            self.mode = "camp" if self.failure == "question" else "question"
        elif m == "icon":
            # `Parts`, a colour or `Size`: a sub-menu the step must never open.
            self.opened.append(k)
            self.mode = "wrong"
        elif m == "question" and k == "y":
            if self.failure == "writes":
                (self.save_dir / "SAVGAMA.DAT").write_bytes(b"\x01")
            self.mode = "camp" if self.failure == "direct" else "alter"
        elif m == "question":
            self.mode = "icon"

    def capture(self) -> dosbox.Screen:
        px = bytearray(W * H * 3)
        bar = {"question": QUESTION, "wrong": "SOMETHING ELSE ENTIRELY"}.get(
            self.mode) or self.bars[self.mode]
        _draw(px, da.BAR_ROW, 0, bar, _GREEN)
        if self.mode in ("camp", "alter"):
            for n, name in enumerate(self.names, 1):
                _draw(px, da.ICON_ROSTER_ROW + n - 1, da.ICON_ROSTER_COLUMN, name,
                      _WHITE if n == self.current else _CYAN)
        if self.mode in ("icon", "question"):
            # The four figures, OLD above NEW, the same unless `differs`.
            old, new = da.ICON_FIGURES[self.title]
            for x0, y0, w, h in (old, new):
                for x in range(x0, x0 + w, 3):
                    at = ((y0 + 5) * W + x) * 3
                    px[at:at + 3] = b"\xaa\x00\xaa"
            if self.failure == "differs":
                at = ((new[1] + 9) * W + new[0] + 4) * 3
                px[at:at + 3] = b"\xff\x55\x55"
        return dosbox.Screen(W, H, bytes(px))

    def settle(self, quiet: float = 0.6, timeout: float = 30.0) -> dosbox.Screen:
        return self.capture()

    def wait_for(self, pred, timeout: float = 30.0) -> bool:
        return bool(pred(self.capture()))

    def shot(self, name: str, allow_blank: bool = False) -> pathlib.Path:
        return self.save_dir.parent / f"{name}.png"


@pytest.fixture(autouse=True)
def _font(monkeypatch, tmp_path):
    monkeypatch.setattr(da.time, "sleep", lambda s: None)
    # A screen the route does not know is given this long, spun through.
    monkeypatch.setattr(da, "ICON_WAIT", 0.3)
    monkeypatch.setattr(dosbox, "find_game", lambda stem="POOLRAD": tmp_path)
    # Pools of Darkness finds its game folder through `dospod.find_game`.
    monkeypatch.setattr(dospod, "find_game", lambda stem=dospod.STEM: tmp_path)
    monkeypatch.setattr(da, "load_font", lambda game: _FONT)


def _camped(tmp_path, title, **kw) -> tuple[FakeIcon, da.Driver]:
    game = FakeIcon(tmp_path, title, **kw)
    d = da.Driver(game, lambda **k: None, "A", title, party_size=len(game.names))
    d.where = "camp"
    d.camp_sig = screens.bar_signature(game.capture())
    return game, d


# -- the route ---------------------------------------------------------------


@pytest.mark.parametrize("title", sorted(BARS))
@pytest.mark.parametrize("line", (1, 3))
def test_icon_shoots_the_lines_screen_and_comes_back_to_camp(tmp_path, title, line):
    game, d = _camped(tmp_path, title)
    got = d.icon(line)
    moves = [NEXT_KEY[title]] * (line - 1)
    assert game.keys == moves + ["a", "i", "e", "y", "e"]
    assert game.mode == "camp" and game.current == line
    assert got["name"] == NAMES[line - 1]
    assert got["record"]["file"] == f"CHRDATA{line}.SAV"
    assert got["answered"] == "Y" and got["via"] == "alter"
    assert got["save_unchanged"] is True
    assert got["icon"].endswith(f"icon-{line}")


@pytest.mark.parametrize("title", sorted(BARS))
def test_icon_presses_nothing_that_edits_the_figure_or_saves(tmp_path, title):
    game, d = _camped(tmp_path, title)
    for line in (1, 2, 3):
        d.icon(line)
    assert game.opened == []
    assert set(game.keys) <= {NEXT_KEY[title], "a", "i", "e", "y"}
    # `S` is Size on the ICON bar and Save on the camp bar.
    assert "s" not in game.keys


def test_a_y_that_returns_straight_to_camp_gets_no_exit(tmp_path):
    game, d = _camped(tmp_path, "pool", failure="direct")
    got = d.icon(2)
    assert game.keys[-1] == "y" and got["via"] == "camp"
    assert game.mode == "camp"


@pytest.mark.parametrize("failure, last", (("alter", "a"), ("icon", "i"),
                                           ("question", "e")))
def test_an_unknown_screen_stops_the_step_with_nothing_more_pressed(
        tmp_path, failure, last):
    game, d = _camped(tmp_path, "curse", failure=failure)
    with pytest.raises(da.StepFailed):
        d.icon(1)
    assert game.keys[-1] == last
    assert "y" not in game.keys


def test_new_figures_that_are_not_the_old_ones_stop_before_exit(tmp_path):
    game, d = _camped(tmp_path, "pool", failure="differs")
    with pytest.raises(da.StepFailed, match="NEW figures differ"):
        d.icon(1)
    assert game.keys[-1] == "i"


def test_a_roster_name_no_record_holds_stops_before_alter(tmp_path):
    game, d = _camped(tmp_path, "ssb")
    (game.save_dir / "CHRDATA2.SAV").write_bytes(_record("ssb", "SOMEONE"))
    with pytest.raises(da.StepFailed, match="names no CHRDATA record"):
        d.icon(2)
    assert "a" not in game.keys


def test_two_members_of_one_name_stop_before_alter(tmp_path):
    game, d = _camped(tmp_path, "pool", names=("BRUTUS", "BRUTUS", "ROLAND"))
    with pytest.raises(da.StepFailed, match="CHRDATA1.SAV, CHRDATA2.SAV"):
        d.icon(2)
    assert "a" not in game.keys


def test_a_stop_on_the_route_says_the_save_folder_is_unchanged(tmp_path):
    game, d = _camped(tmp_path, "curse", failure="icon")
    with pytest.raises(da.StepFailed, match="the save folder is unchanged"):
        d.icon(1)


def test_a_stop_on_the_route_names_the_files_that_changed(tmp_path):
    game, d = _camped(tmp_path, "curse", failure="alter-writes")
    with pytest.raises(da.StepFailed,
                       match=r"the save folder changed: \['SAVGAMA.DAT'\]"):
        d.icon(1)
    assert game.keys[-1] == "a"


def test_a_save_folder_that_changed_stops_the_step(tmp_path):
    game, d = _camped(tmp_path, "pool", failure="writes")
    with pytest.raises(da.StepFailed, match="save folder changed"):
        d.icon(1)


def test_icon_is_not_driven_outside_camp(tmp_path):
    game, d = _camped(tmp_path, "pool")
    d.where = "map"
    with pytest.raises(da.StepFailed, match="camp first"):
        d.icon(1)
    assert game.keys == []


# -- reading the screens -------------------------------------------------------


def _rows(bar: str, *, extra: str = "") -> list[str]:
    rows = [""] * (da.BAR_ROW + 1)
    rows[3] = extra
    rows[da.BAR_ROW] = bar
    return rows


@pytest.mark.parametrize("title", sorted(BARS))
def test_each_bar_of_the_route_is_read_as_its_own_screen(title):
    for kind, bar in BARS[title].items():
        assert da.icon_screen_kind(_rows(bar), title) == kind
    assert da.icon_screen_kind(_rows(QUESTION), title) == "question"
    assert da.icon_screen_kind(_rows("YES NO", extra="IS THIS ICON OK?"), title) == "question"


@pytest.mark.parametrize("bar", (
    "", "SAVE VIEW MAGIC REST EXIT",                    # no ALTER
    "SAVE VIEW REST ALTER EXIT",                        # no MAGIC
    "ORDER DROP SPEED PICS EXIT",                       # no ICON
    "PARTS SIZE EXIT",                                  # no colour word
    "ICON:PARTS COLOR-1 COLOR-2 SIZE",                  # does not end in EXIT
    "HEAD WEAPON EXIT", "KEEP EXIT", "SMALL LARGE KEEP EXIT",
    "YES NO",                                           # some other question
    "?A?E VIEW MAGIC REST ALTER EXIT",                  # unreadable cells
))
def test_any_other_bar_is_no_screen_of_the_route(bar):
    assert da.icon_screen_kind(_rows(bar), "pool") is None


@pytest.mark.parametrize("title", ("pool", "curse", "ssb"))
def test_a_camp_bar_without_rest_is_no_camp_where_the_game_has_rest(title):
    assert da.icon_screen_kind(_rows("SAVE VIEW MAGIC ALTER EXIT"), title) is None


def test_pools_of_darkness_camp_bar_has_no_rest():
    bar = "SAVE VIEW MAGIC ALTER EXIT"
    assert da.icon_screen_kind(_rows(bar), "darkness") == "camp"
    assert da.icon_screen_kind(_rows("SAVE VIEW MAGIC REST ALTER EXIT"), "darkness") == "camp"


# -- steps and staging ---------------------------------------------------------


def test_icon_parses_and_is_ordered_after_camp():
    step = da.parse_step("icon 4")
    assert (step.kind, step.line) == ("icon", 4)
    for bad in ("icon", "icon 0", "icon 9", "icon 1 2"):
        with pytest.raises(ValueError):
            da.parse_step(bad)
    da.validate_steps([da.parse_step(s) for s in ("load", "camp", "icon 1", "icon 6")],
                      "pool")
    da.validate_steps([da.parse_step(s) for s in ("load", "begin", "camp", "icon 2")],
                      "ssb")
    with pytest.raises(ValueError, match="camp first"):
        da.validate_steps([da.parse_step(s) for s in ("load", "begin", "icon 1")],
                          "curse")
    da.validate_steps([da.parse_step(s) for s in ("load", "begin", "camp", "icon 1",
                                                  "icon 6")], "darkness")


#: Where each title's ICON editor reads and writes the figure: head, body,
#: size and the first colour byte (Pool `GAME.OVR` 0x1D235-0x1D24B and
#: 0x1D1F7, Curse 0x24509-0x24532, Silver Blades 0x219F7-0x21A20, Pools of
#: Darkness 0x183E9-0x18420).
OVERLAY_OFFSETS = {"pool": (0x0BD, 0x0BE, 0x0C0, 0x0C1),
                   "curse": (0x141, 0x142, 0x144, 0x145),
                   "ssb": (0x153, 0x154, 0x156, 0x157),
                   "darkness": (0x19A, 0x19B, 0x19D, 0x19E)}


@pytest.mark.parametrize("title", sorted(OVERLAY_OFFSETS))
def test_stage_icon_writes_the_figure_where_the_titles_editor_reads_it(tmp_path, title):
    (tmp_path / "CHRDATA2.SAV").write_bytes(_record(title, "MAGNUS"))
    before = (tmp_path / "CHRDATA2.SAV").read_bytes()
    got = da.stage_icon(tmp_path, "A", title, *da.parse_stage_icon("2=10:11:0e8e66c478f7"))
    after = (tmp_path / "CHRDATA2.SAV").read_bytes()
    head, body, size, colours = OVERLAY_OFFSETS[title]
    assert after[head] == 10 and after[body] == 11
    assert after[colours:colours + 6] == bytes.fromhex("0e8e66c478f7")
    assert after[size] == before[size]
    changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    assert set(changed) <= {head, body, *range(colours, colours + 6)}
    assert got["name"] == "MAGNUS" and got["after"]["icon_body"] == "0b"


def test_stage_icon_writes_nothing_into_another_titles_record(tmp_path):
    (tmp_path / "CHRDATA1.SAV").write_bytes(_record("curse", "ARGORA"))
    before = (tmp_path / "CHRDATA1.SAV").read_bytes()
    with pytest.raises(ValueError, match="not the pool-of-radiance record"):
        da.stage_icon(tmp_path, "A", "pool", 1, 0, 0, bytes(6))
    assert (tmp_path / "CHRDATA1.SAV").read_bytes() == before


def test_a_figure_staged_into_another_titles_record_stops_before_the_boot(tmp_path):
    import argparse
    (tmp_path / "SAVGAMA.DAT").write_bytes(bytes(0x100))
    (tmp_path / "CHRDATA1.SAV").write_bytes(_record("curse", "ARGORA"))
    (tmp_path / "CHRDATA2.SAV").write_bytes(_record("pool", "BRUTUS"))
    args = argparse.Namespace(title="pool", stage_icon=["2=0:0:91a2b3c4e6f7"])
    da.check_staging(args, tmp_path, "A")
    args.stage_icon.append("1=0:0:91a2b3c4e6f7")
    with pytest.raises(ValueError, match="not the pool-of-radiance record"):
        da.check_staging(args, tmp_path, "A")


def test_the_layouts_agree_with_the_overlays():
    for title, offsets in OVERLAY_OFFSETS.items():
        fields = dos_port.FIELDS_BY_NAME_FOR[da.ICON_LAYOUTS[title]]
        assert (fields["icon_head"].offset, fields["icon_body"].offset,
                fields["size"].offset, fields["icon_colours"].offset) == offsets


@pytest.mark.parametrize("text", ("2=14:0:91a2b3c4e6f7", "2=0:32:91a2b3c4e6f7",
                                  "9=0:0:91a2b3c4e6f7", "2=0:0:91a2b3c4e6",
                                  "2=0:0", "2:0:0:91a2b3c4e6f7", "2=-1:0:91a2b3c4e6f7"))
def test_a_staged_figure_outside_the_editors_choices_is_blocked(text):
    with pytest.raises(ValueError):
        da.parse_stage_icon(text)


def test_the_command_line_blocks_a_bad_staged_figure(tmp_path, capsys):
    with pytest.raises(SystemExit):
        da.main(["--title", "pool", "--save", str(tmp_path), "--stage-icon",
                 "1=20:0:91a2b3c4e6f7", "--steps", "load", "camp", "icon 1"])
    assert "the head is 0 to 13" in capsys.readouterr().err
