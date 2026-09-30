"""The half of `tools/c64/acceptance.py` a machine with no emulator can check.

The driver stages effect rows, trait slots, item bytes, record bytes and roster
status into a copy of a C64 save, then reads the camp lists and a character's
ITEMS list. These tests assert that staging changes only named bytes, that a
bad step is refused before a slot is claimed, and that the screen readers use
the game's own strings: the camp list (`CAMP $16C3`-`$1797`,
" IS AFFECTED BY:" and "PRESS ANY KEY TO CONTINUE") and the item list, where
Detect Magic prints a `*` before a magic item's name (`LIBRARY $39B7`-`$39C3`).

The composed screens are built from those strings and the Pool item-list
capture `cited/252/probe4/screen.txt`, not from a live run. The fixture save is
the committed `tests/fixtures/savedgame0.bin` party written as a disk by
`dos_codec.save_disk`, the way `tests/convert/test_runningeffects.py` builds
one. Two tests read the player's `PORSAVE13.D64` and skip without it.
"""

from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import re
import subprocess
import sys
import time
from types import SimpleNamespace

import gamedata
import pytest

from goldbox import c64_save, dos_codec, effects
from goldbox.c64_port import POOL_OF_RADIANCE
from goldbox.d64 import D64, split_load_address
from goldbox.items import ITEM_AREA_BASE, ITEM_BLOCK_STRIDE, ITEM_SIZE
from goldbox.savegame import SaveGame0, SaveGame1
from tools.c64 import acceptance as A
from tools.c64 import drive
from tools.pool_of_radiance import fleedrive

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"


def _fixture_disk(tmp_path: pathlib.Path) -> pathlib.Path:
    payload = SaveGame0.from_prg((FIXTURES / "savedgame0.bin").read_bytes()).to_bytes()
    save1 = SaveGame1.from_prg((FIXTURES / "savedgame1.bin").read_bytes()).to_bytes()
    path = tmp_path / "fixture-source.d64"
    path.write_bytes(dos_codec.save_disk(payload, save1, POOL_OF_RADIANCE).to_bytes())
    return path


def _payload(path: pathlib.Path) -> bytes:
    image = D64.open(str(path))
    return split_load_address(image.read_file(POOL_OF_RADIANCE.save_file))[1]


def _roster(path: pathlib.Path) -> bytes:
    image = D64.open(str(path))
    return split_load_address(image.read_file(b"SAVEDGAME1"))[1]


# --- parsing -----------------------------------------------------------------

def test_a_row_stage_is_read_as_effectdrive_reads_it():
    assert A.parse_rows(["63=05:FF:0A:03"]) == [(63, 5, 0xFF, 0x0A, 0x03)]
    assert A.parse_rows(["63=05:FF:0A:03,62=01:00:2F:01"]) == [
        (63, 5, 0xFF, 0x0A, 0x03), (62, 1, 0, 0x2F, 1)]


@pytest.mark.parametrize("text", ["63=05:FF:0A", "64=05:FF:0A:03",
                                  "63=105:FF:0A:03"])
def test_a_row_stage_out_of_range_is_refused(text):
    with pytest.raises(ValueError):
        A.parse_rows([text])


def test_trait_and_item_stages():
    assert A.parse_traits(["0:9=38"]) == [(0, 9, 38)]
    assert A.parse_items(["1:2:4=1", "0:15:10=0x20"]) == [(1, 2, 4, 1),
                                                         (0, 15, 10, 0x20)]
    for bad in ("0:10=38", "8:0=1"):
        with pytest.raises(ValueError):
            A.parse_traits([bad])
    for bad in ("1:16:4=1", "1:2:16=1", "1:2:4=256", "1:2=1"):
        with pytest.raises(ValueError):
            A.parse_items([bad])


def test_a_malformed_trait_stage_is_a_value_error_and_exits_two(capsys):
    with pytest.raises(ValueError):
        A.parse_traits(["0:9"])
    with pytest.raises(SystemExit) as e:
        A.main(["--title", "pool", "--save", "x.D64", "--steps", "load",
                "--stage-trait", "0:9"])
    assert e.value.code == 2


def test_record_and_status_stages_parse_one_byte_at_a_time():
    assert A.parse_record_bytes(["0:0xCA=5", "1:0x20=36"]) == [
        (0, 0xCA, 5), (1, 0x20, 36)]
    assert A.parse_statuses(["2=0x83", "3=3"]) == [(2, 0x83), (3, 3)]
    for bad in ("8:0=1", "0:0x100=1", "0:0=256", "0:0"):
        with pytest.raises(ValueError):
            A.parse_record_bytes([bad])
    for bad in ("8=0x83", "0=256", "0"):
        with pytest.raises(ValueError):
            A.parse_statuses([bad])


def test_the_steps_parse_and_keep_their_arguments():
    steps = A.parse_steps(["load", "camp-list", "items LADY KATHERINE",
                           "items 2", "rest 8h", "rest 1h30m", "peek $4900 64",
                           "fight 90", "save"])
    assert [(s.verb, s.arg) for s in steps] == [
        ("load", ""), ("camp-list", ""), ("items", "LADY KATHERINE"),
        ("items", "2"), ("rest", "8h"), ("rest", "1h30m"),
        ("peek", "$4900 64"), ("fight", "90"), ("save", "")]
    assert A.parse_rest("8h") == (0, 8)
    assert A.parse_rest("1h30m") == (30, 1)
    assert A.parse_peek("$4900 64") == (0x4900, 64)


def test_temple_probe_step_takes_an_optional_heal():
    assert A.parse_steps(["load", "temple-probe BRUTUS HEAL"])[1] == (
        A.Step("temple-probe", "BRUTUS HEAL"))
    for bad in ("temple-probe BRUTUS RAISE HEAL", "temple-probe HEAL",
                "temple-probe BAKSHI HEAL", "temple-probe BRUTUS HEAL HEAL"):
        with pytest.raises(ValueError):
            A.parse_steps(["load", bad])


def test_temple_probe_step_takes_raise_for_brutus_only():
    assert A.parse_steps(["load", "temple-probe BRUTUS RAISE"])[1] == (
        A.Step("temple-probe", "BRUTUS RAISE"))
    for bad in ("temple-probe BAKSHI RAISE", "temple-probe RAISE",
                "temple-probe BRUTUS RAISE RAISE"):
        with pytest.raises(ValueError):
            A.parse_steps(["load", bad])


_RAISE_STAGING = ["--stage-record", "5:0x018=18,5:0x0C1=0x70,5:0x0C2=0x17"]


def _raise_argv(tmp_path, *extra, step="temple-probe BRUTUS RAISE"):
    return ["--title", "pool", "--save", str(_fixture_disk(tmp_path)),
            "--disks", str(tmp_path), "--issue", "700",
            "--run", "temple-raise-a", "--max-seconds", "1500",
            "--steps", "load", step, *extra,
            "--out", str(tmp_path / "out")]


def test_temple_probe_main_accepts_raise_with_exactly_the_staging(
        tmp_path, monkeypatch):
    observed = []
    monkeypatch.setattr(A, "temple_source_guard", lambda path: A.TEMPLE_BRUTUS_SHA256)
    monkeypatch.setattr(A, "run", lambda args, steps, out, selected: observed.append(
        (steps, args.stage_record)) or 0)
    assert A.main(_raise_argv(tmp_path, *_RAISE_STAGING)) == 0
    assert observed == [([A.Step("load"), A.Step("temple-probe", "BRUTUS RAISE")],
                         [_RAISE_STAGING[1]])]


@pytest.mark.parametrize("extra,step", [
    (["--stage-record", "5:0x018=18,5:0x0C1=0x70"], None),
    (["--stage-record", "5:0x018=17,5:0x0C1=0x70,5:0x0C2=0x17"], None),
    (["--stage-record", "4:0x018=18,4:0x0C1=0x70,4:0x0C2=0x17"], None),
    ([*_RAISE_STAGING, "--stage-record", "5:0x20=1"], None),
    ([*_RAISE_STAGING, "--stage-status", "5=3"], None),
    ([], None),
    (_RAISE_STAGING, "temple-probe BRUTUS HEAL"),
    (_RAISE_STAGING, "temple-probe BRUTUS"),
])
def test_temple_probe_refuses_other_staging_before_a_slot_is_claimed(
        tmp_path, monkeypatch, extra, step):
    monkeypatch.setattr(A, "temple_source_guard", lambda path: A.TEMPLE_BRUTUS_SHA256)
    kwargs = {} if step is None else {"step": step}
    _refused_before_a_slot(tmp_path, monkeypatch, _raise_argv(
        tmp_path, *extra, **kwargs)[:-2])


def test_temple_probe_step_names_only_brutus():
    assert A.parse_steps(["load", "temple-probe BRUTUS"])[1] == (
        A.Step("temple-probe", "BRUTUS"))
    for bad in ("temple-probe", "temple-probe BAKSHI",
                "temple-probe 6", "temple-probe BRUTUS>HEAL"):
        with pytest.raises(ValueError):
            A.parse_steps(["load", bad])


@pytest.mark.parametrize("extra", [
    ["--title", "curse"], ["--issue", "699"],
    ["--stage-record", "2:0x20=41"], ["--stage-row", "63=20:05:00:05"],
    ["--stage-trait", "5:9=32"], ["--stage-item", "5:0:4=1"],
    ["--stage-status", "5=3"], ["--checkpoint", "408F"],
    ["--stage-only"], ["--preserve-specimen"], ["--capture-ready"],
    ["--probe-step"], ["--joy"], ["--pool", "0"],
    ["--attack-by", "ROLAND"], ["--walk", "MIIJI"],
    ["--max-seconds", "1600"],
])
def test_temple_probe_rejects_other_modes_before_guest_claim(
        tmp_path, monkeypatch, extra):
    source = _fixture_disk(tmp_path)
    monkeypatch.setattr(A, "temple_source_guard", lambda path: A.TEMPLE_BRUTUS_SHA256)
    _refused_before_a_slot(tmp_path, monkeypatch, [
        "--save", str(source), "--disks", str(tmp_path), "--issue", "700",
        "--steps", "load", "temple-probe BRUTUS", *extra])


def test_temple_probe_refuses_unregistered_or_changed_source_before_guest_claim(
        tmp_path, monkeypatch):
    source = _fixture_disk(tmp_path)
    monkeypatch.setattr(A.S, "claim_slot", lambda *a, **k: pytest.fail("claimed"))
    with pytest.raises(SystemExit) as error:
        A.main(["--title", "pool", "--save", str(source),
                "--disks", str(tmp_path), "--issue", "700",
                "--steps", "load", "temple-probe BRUTUS",
                "--out", str(tmp_path / "out")])
    assert error.value.code == 2
    assert not (tmp_path / "out").exists()


def test_temple_probe_accepts_only_the_bounded_command(tmp_path, monkeypatch):
    source = _fixture_disk(tmp_path)
    observed = []
    monkeypatch.setattr(A, "temple_source_guard", lambda path: A.TEMPLE_BRUTUS_SHA256)
    monkeypatch.setattr(A, "run", lambda args, steps, out, selected: observed.append(
        (args, steps, out, selected)) or 0)
    assert A.main(["--title", "pool", "--save", str(source),
                   "--disks", str(tmp_path), "--issue", "700",
                   "--run", "temple-route-a", "--max-seconds", "1500",
                   "--steps", "load", "temple-probe BRUTUS",
                   "--out", str(tmp_path / "out")]) == 0
    args, steps, out, selected = observed[0]
    assert steps == [A.Step("load"), A.Step("temple-probe", "BRUTUS")]
    assert args.max_seconds == 1500 and selected == source
    assert out == tmp_path / "out"
    assert "'temple-probe BRUTUS'" in args.command


def test_temple_probe_main_accepts_the_heal_command(tmp_path, monkeypatch):
    source = _fixture_disk(tmp_path)
    observed = []
    monkeypatch.setattr(A, "temple_source_guard", lambda path: A.TEMPLE_BRUTUS_SHA256)
    monkeypatch.setattr(A, "run", lambda args, steps, out, selected: observed.append(
        steps) or 0)
    assert A.main(["--title", "pool", "--save", str(source),
                   "--disks", str(tmp_path), "--issue", "700",
                   "--run", "temple-route-g", "--max-seconds", "1500",
                   "--steps", "load", "temple-probe BRUTUS HEAL",
                   "--out", str(tmp_path / "out")]) == 0
    assert observed == [[A.Step("load"), A.Step("temple-probe", "BRUTUS HEAL")]]


def test_temple_input_guard_stops_boot_and_prompt_keys_at_cleanup_reserve():
    events = []
    now = SimpleNamespace(value=1399)
    keyboard = SimpleNamespace(
        key=lambda key: events.append(("key", key)),
        text=lambda text: events.append(("text", text)))
    session = SimpleNamespace(
        kbd=keyboard,
        press_kernal=lambda code: events.append(("kernal", code)),
        handle_prompt=lambda screen=None: events.append(("prompt", screen)))
    original_press = session.press_kernal
    original_prompt = session.handle_prompt
    restore = A.guard_temple_input(session, lambda: now.value, 1400)
    session.kbd.key("Return")
    session.kbd.text("aaaaaa")
    session.press_kernal(0x0D)
    session.handle_prompt("side3")
    assert len(events) == 4
    now.value = 1400
    for send in (lambda: session.kbd.key("Return"),
                 lambda: session.kbd.text("aaaaaa"),
                 lambda: session.press_kernal(0x0D),
                 lambda: session.handle_prompt("side3")):
        with pytest.raises(A.StepFailed, match="temple input deadline"):
            send()
    assert len(events) == 4
    restore()
    assert session.kbd is keyboard
    assert session.press_kernal is original_press
    assert session.handle_prompt is original_prompt


def test_temple_source_guard_requires_registry_path_and_recorded_hash(
        tmp_path, monkeypatch):
    source = _fixture_disk(tmp_path)
    digest = A.specimens.sha256_file(source)
    monkeypatch.setattr(A, "TEMPLE_SOURCES", {
        digest: A.TEMPLE_SOURCES[A.TEMPLE_BRUTUS_SHA256]})
    entry = {"platform": "c64", "title": "Pool of Radiance",
             "_files": [source], "sha256": {source.name: digest}}
    monkeypatch.setattr(A.specimens, "list_specimens", lambda: [entry])
    assert A.temple_source_guard(source) == digest
    duplicate = tmp_path / "not-registered.D64"
    duplicate.write_bytes(source.read_bytes())
    with pytest.raises(ValueError, match="not a registered"):
        A.temple_source_guard(duplicate)
    source.write_bytes(source.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="SHA-256"):
        A.temple_source_guard(source)


_BAR_WORDS = [(0, 4), (5, 4), (10, 4), (15, 8), (24, 4)]
#: The bar once the party's money is pooled: the live frame 17 of the D3b
#: POOL boot carried SHARE between POOL and APPRAISE.
_POOLED_BAR_WORDS = [(0, 4), (5, 4), (10, 4), (15, 4), (20, 5), (26, 8),
                     (35, 4)]


def _framed(text):
    """A service-list row as the live screen draws it."""
    return "$" + (" " + text).ljust(38) + "$"


class _TempleScreen:
    def __init__(self, rows, bar_highlight=None, party_highlight=None,
                 list_highlight=None):
        self._rows = [row.ljust(40)[:40] for row in rows]
        self.codes = bytes(ord(char) for row in self._rows for char in row)
        colours = bytearray(1000)
        if bar_highlight is not None:
            start, width = bar_highlight
            colours[24 * 40 + start:24 * 40 + start + width] = bytes([1]) * width
        if party_highlight is not None:
            colours[party_highlight * 40 + A.S.PARTY_COLUMN] = 1
        if list_highlight is not None:
            colours[list_highlight * 40 + 2:list_highlight * 40 + 8] = (
                bytes([1]) * 6)
        self.colours = bytes(colours)

    def row(self, n):
        return self._rows[n]

    def text(self):
        return "\n".join(self._rows)

    def highlighted_rows(self, colour=1, column=None):
        from automap.screen import Screen
        return Screen.highlighted_rows(self, colour, column)


class _TempleMonitor:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        self.session.paused = True
        return self

    def __exit__(self, *_):
        self.session.paused = False

    def resume(self):
        if self.session.question_state_lag:
            self.session.question_state_lag -= 1
        if self.session.cursor_reads:
            self.session.cursor_reads -= 1

    def read(self, address, count):
        s = self.session
        if s.short_monitor:
            return b""
        place = (s._question_lag_place
                 if s.question_state_lag and s._question_lag_place is not None
                 else s.place)
        if address == 0x6E1B:
            return bytes([place[0] | (0x80 if s.pending_area else 0)])
        if address == 0x6E11:
            if s.unsafe == "encounter" and s.moves:
                return bytes([A.S.COMBAT])
            # `572b9ca0ee-temple-route-d` frame 10: the temple arrival
            # screen reads `$6E11` = 5, not `S.DUNGEON`.
            if s.phase == "temple":
                return bytes([A.TEMPLE_ARRIVAL_MODE])
            return bytes([A.S.DUNGEON])
        if address == A.TEMPLE_POOL_COINS:
            if getattr(s, "pool_read_error", False):
                raise OSError("monitor gone")
            return b"".join(w.to_bytes(2, "little") for w in s.pool_coins)
        if address == 0x49E6:
            return b"\x01"
        if address == 0x49C0:
            return bytes((15, 4, 3))  # The game's save copy lags movement.
        if address == 0xC04B:
            if s.cursor_reads:
                return bytes(s.cursor_triple)
            return bytes(place[1:])
        raise AssertionError(f"unexpected monitor read ${address:04X}")


class _TempleSession:
    def __init__(self, out, *, unsafe=None, after_side3="arrival-text",
                 cursor_after_side3=0):
        self.place = (0x14, 15, 4, 3)
        self.phase = "move"
        self.moves = []
        self.keys = []
        self.unsafe = unsafe
        self.after_side3 = after_side3
        self.short_monitor = unsafe == "short-monitor"
        self.pending_area = False
        self.out = out
        self.kbd = self
        # A renderer cursor glitch (#715): Pool's 3D renderer moves
        # `$C04B`-`$C04D` off the party's square while it draws, so one read
        # taken mid-render can return a plausible but wrong triple.
        # `cursor_after_side3` sets how many monitor pauses after the
        # crossing key's answer the cursor returns `cursor_triple` instead
        # of the true place.
        self.cursor_after_side3 = cursor_after_side3
        self.cursor_triple = (1, 4, 1)
        self.cursor_reads = 0
        self.heal_never_draws = unsafe == "heal-never-draws"
        self.heal_blank_reads = 0
        self.heal_old_bar_reads = 0
        self.glitch_reads = 0
        self.heal_reads = 0
        # Reads (0.3 s apart in the fakes) the welcome stands alone for.
        self.list_after_reads = {"heal-late-list": 40, "heal-cut": 10**9
                                 }.get(unsafe, 10)
        self.paused = False
        # The live run crossing the area edge showed the memory triple
        # ahead of the redrawn screen for one poll; `crossing_lag` makes
        # one screen() call after the crossing key still render the
        # pre-crossing place and move bar, as that run did.
        self._pre_crossing_place = None
        self.crossing_lag = 0
        # `question-lag` models the same one-poll memory lag for the
        # healing question: `_question_lag_place` is what the memory read
        # returns for `question_state_lag` further polls after the question
        # screen appears, before it catches up with `self.place`.
        self._question_lag_place = None
        self.question_state_lag = 0
        # `temple-route-b` then read the new place under a quiet screen: the
        # old status line, row 24 and the message window blank, before
        # `INSERT SIDE # 3` appeared. `crossing_quiet` counts those reads.
        self.crossing_quiet = 0
        self.quiet_reads = 2
        self.quiet_text = ""
        # `temple-route-c` then read a further quiet screen after the side-3
        # answer, followed by Pool typing the gateway square's arrival text a
        # character at a time with row 24 blank; `typing` models that as a
        # queue of message-window strings, one per `screen()` call, and
        # `window_text` is what remains on row 17 once typing finishes, until
        # the next `move_key` clears it.
        self.post_answer_quiet = 0
        self.typing = []
        self.window_text = ""
        self._typed_text = ""
        self._question_answered_once = False
        # RAISE DEAD purchase: the list's highlight index (row 9 + this),
        # and the invented price and result texts of the `price` and
        # `result` phases.
        self.list_cursor = 0
        self.result_text = "BRUTUS IS ALIVE"
        # The temple bar's highlighted word, as an index into `_BAR_WORDS`,
        # and what row 24 says over the unchanged price screen after YES.
        self.bar_at = 0
        self.result_bar = None
        # The pool's five coin words; the price screen's YES takes the fee.
        self.pool_coins = [0, 0, 0, 6000, 0]
        # Frames the result phase shows in turn, one per screen read, before
        # the last stands; None shows `result_text` throughout.
        self.result_frames = None
        self._result_reads = 0
        # The result frame's `PRESS <RETURN> OR BUTTON TO CONTINUE` line, and
        # how many blank frames the temple bar's EXIT shows before the world
        # bar. The screen after that Return is invented; `after_continue`
        # names it: "list", "bar" or "unknown".
        self.press_line = False
        self.after_continue = "list"
        self.leaving_reads = 3
        # How many times EXIT on the pooled bar shows the treasure prompt
        # before the world bar (the live boot showed it once), what SHARE
        # shows ("bar", or "prompt" for a question), and how many shares
        # have been made.
        self.treasure_prompts = 0
        self.after_share = "bar"

    def key(self, name, *timing):
        if self.phase == "temple":
            # The bar's highlight: HEAL, VIEW, POOL, APPRAISE, EXIT.
            assert name in ("Right", "Left"), name
            self.keys.append(name)
            self.bar_at += 1 if name == "Right" else -1
            return
        if self.phase == "result":
            assert name == "Return" and self.press_line, (self.phase, name)
            self.keys.append(name)
            self.bar_at = 0
            self.list_cursor = 0
            self.heal_reads = 0
            self.phase = {"list": "heal", "bar": "temple",
                          "unknown": "unknown"}[self.after_continue]
            return
        assert self.phase == "heal", self.phase
        self.keys.append(name)
        if name == "Down" and self.unsafe != "list-stuck":
            self.list_cursor += 1
        elif name == "Return":
            self.phase = ("price" if 9 + self.list_cursor == 15
                          else "temple" if 9 + self.list_cursor == 18
                          else "heal-blank")

    def _bar_words(self):
        return _POOLED_BAR_WORDS if "pool-YES" in self.keys else _BAR_WORDS

    def mon(self, _timeout):
        return _TempleMonitor(self)

    def screen(self):
        if self.phase == "leaving":
            if self.leaving_reads:
                self.leaving_reads -= 1
                return _TempleScreen([""] * 25)
            self.phase = getattr(self, "after_leaving", "world")
        if self.phase == "heal" and self.heal_blank_reads:
            # Blank bar frames before the list draws, as the transition
            # screens between temple and service do.
            self.heal_blank_reads -= 1
            return _TempleScreen([""] * 25)
        if self.phase == "heal" and self.unsafe == "heal-glitch":
            # A half-drawn frame that persists ~0.9 s of reads (three
            # 0.3 s polls) before the list is drawn.
            self.glitch_reads += 1
            if self.glitch_reads > 3:
                self.unsafe = None
                return self.screen()
            rows = [""] * 25
            rows[2] = "BRUTUS"
            rows[3] = "WELCOME TO THE TEMPLE,"
            return _TempleScreen(rows)
        if self.phase == "heal" and self.heal_old_bar_reads:
            # The arrival screen lingers for a few reads after the key.
            self.heal_old_bar_reads -= 1
            self.phase = "temple"
            try:
                return self.screen()
            finally:
                self.phase = "heal"
        if self.crossing_lag:
            place, phase = self._pre_crossing_place, "move"
            self.crossing_lag -= 1
        elif self.crossing_quiet:
            place, phase = self._pre_crossing_place, "quiet"
            self.crossing_quiet -= 1
        elif self.post_answer_quiet:
            place = (self._pre_crossing_place
                     if self._pre_crossing_place is not None else self.place)
            phase = "quiet"
            self.post_answer_quiet -= 1
        elif self.typing:
            place = (self._pre_crossing_place
                     if self._pre_crossing_place is not None else self.place)
            phase = "typing"
            self._typed_text = self.typing.pop(0)
            if not self.typing:
                self.window_text = self._typed_text
        else:
            place, phase = self.place, self.phase
        rows = [""] * 25
        rows[14] = (f"{'NESW'[place[3]]} 00:00 "
                    f"{place[1]},{place[2]}")
        if phase == "move":
            rows[24] = "I,J,K,M, RETURN OR BUTTON"
            if self.window_text:
                rows[17] = self.window_text
        elif phase == "typing":
            rows[17] = self._typed_text
        elif phase in ("side3", "side4"):
            rows[20] = ("INSERT SIDE # 3" if phase == "side3"
                        else "INSERT SIDE # 4")
            rows[24] = "AND PRESS ANY KEY."
        elif phase == "quiet":
            rows[20] = self.quiet_text
        elif phase == "continue":
            rows[24] = "PRESS BUTTON OR RETURN TO CONTINUE."
        elif phase == "yes-no":
            rows[24] = "YES NO"
        elif phase == "question":
            rows[18] = "DO YOU SEEK HEALING?"
            rows[24] = "YES NO"
        elif phase == "unknown":
            rows[24] = "TRAIN CHARACTER"
        elif phase == "unknown-disk":
            rows[20] = "INSERT DISK B"
            rows[24] = "I,J,K,M, RETURN OR BUTTON"
        elif phase == "temple":
            # Frame 10 of `572b9ca0ee-temple-route-d`: no greeting text and
            # no status line, BRUTUS still in the roster; the arrival
            # screen is identified only by its command bar, `HEAL VIEW
            # POOL APPRAISE EXIT`.
            rows[14] = ""
            rows[3] = " " * A.S.PARTY_COLUMN + "NAME        AC HP"
            names = ["BRUTUS", "BAKSHI", "SHARA", "MARK", "PHILIPPE", "ROLAND"]
            if self.unsafe == "other-top":
                names[0], names[5] = names[5], names[0]
            for offset, name in enumerate(names):
                rows[4 + offset] = " " * A.S.PARTY_COLUMN + name
            rows[24] = ("HEAL VIEW POOL APPRAISE EXIT"
                        if self.unsafe != "wrong-menu" else "EXIT GIVE")
            if "pool-YES" in self.keys and self.unsafe != "wrong-menu":
                rows[24] = "HEAL VIEW TAKE POOL SHARE APPRAISE EXIT"
            # The row 24 highlight is where the last key left it; the party
            # panel's own rows are read from the same snapshot.
            self.bar_span = self._bar_words()[self.bar_at]
            if self.unsafe == "stale-greeting-status":
                # A status line that is present but reads the wrong place:
                # no live capture has shown one here, but the transition
                # must never treat this as settled if it appears.
                rows[14] = "N 00:00 99,99"
        elif phase == "world":
            rows[24] = "MOVE VIEW ENCAMP"
        elif phase == "treasure":
            # Frame 18 of the D3b POOL boot.
            rows[10] = "$THERE IS STILL TREASURE LEFT".ljust(39) + "$"
            rows[24] = "GO BACK LEAVE TREASURE"
        elif phase == "heal-blank":
            rows[14] = ""  # Cleared while the next screen loads.
        elif phase == "heal":
            rows[14] = ""
            # `0546662ef7-temple-route-h`: the welcome alone is drawn at
            # once and stands for a few seconds; then the list of
            # `8e1934def7-temple-route-g` frame 11 appears. Row 24 is blank.
            self.heal_reads += 1
            rows[2] = "BRUTUS"
            rows[3] = "WELCOME TO THE TEMPLE,"
            rows[4] = "HOW MAY WE HELP YOU"
            if self.heal_reads > self.list_after_reads:
                for row, text in enumerate(
                        ("CURE BLINDNESS", "CURE DISEASE",
                         "CURE LIGHT WOUNDS", "CURE SERIOUS WOUNDS",
                         "CURE CRITICAL WOUNDS", "NEUTRALIZE POISON",
                         "RAISE DEAD" if self.unsafe != "list-no-raise"
                         else "RESURRECT",
                         "REMOVE CURSE", "STONE TO FLESH",
                         "EXIT"), 9):
                    # The live rows carry the frame glyph at both ends.
                    rows[row] = _framed(text)
        elif phase == "price":
            # Invented text holding the needles the probe reads; the price
            # screen has not been seen live.
            rows[11] = "IT WILL COST 5500 GOLD PIECES"
            rows[13] = ("PAY FOR CURE" if self.unsafe != "price-wrong"
                        else "SOMETHING ELSE")
            if self.unsafe == "price-no-cost":
                rows[11] = "IT WILL COST 4000 GOLD PIECES"
            rows[24] = "YES NO"
        elif phase == "poolq":
            # Invented text holding the needle the probe reads; the POOL
            # question has not been seen live.
            rows[11] = "POOL MONEY :"
            rows[24] = "YES NO"
        elif phase == "result":
            if self.result_bar is not None:
                # The price screen left up, its bar row replaced.
                rows[11] = "IT WILL COST 5500 GOLD PIECES"
                rows[13] = "PAY FOR CURE"
                rows[24] = self.result_bar
            elif self.result_frames is not None:
                at = min(self._result_reads // 3, len(self.result_frames) - 1)
                self._result_reads += 1
                rows[12] = self.result_frames[at]
            else:
                rows[12] = self.result_text
            if self.press_line:
                rows[22] = "PRESS <RETURN> OR BUTTON TO CONTINUE"
        else:
            raise AssertionError(phase)
        if phase == "question":
            return _TempleScreen(rows, (0, 3))
        if phase == "temple":
            return _TempleScreen(rows, self.bar_span,
                                 5 if self.unsafe == "highlight-row-5" else 4)
        if phase in ("price", "poolq"):
            return _TempleScreen(rows, (0, 3))
        if phase == "treasure":
            return _TempleScreen(rows, (0, 7))
        if phase == "heal" and rows[15]:
            return _TempleScreen(rows, list_highlight=9 + self.list_cursor)
        return _TempleScreen(rows)

    def screenshot(self, path, timeout=None):
        pathlib.Path(path).write_bytes(b"fake-png")
        return True

    def move_key(self, move):
        self.moves.append(move)
        if self.unsafe == "deadline":
            raise AssertionError("key after input deadline")
        expected = "KKIIJI"[len(self.moves) - 1]
        assert move == expected
        n = len(self.moves)
        # A new key clears whatever text the previous square left typed on
        # row 17, as `run5/02` shows.
        self.window_text = ""
        if n == 1:
            self.place = (9 if self.unsafe == "wrong-area" else 0x14,
                          15, 4, 2 if self.unsafe == "wrong-facing" else 0)
            self.pending_area = self.unsafe == "pending-area"
            self.phase = ("yes-no" if self.unsafe == "yes-no" else
                          "unknown" if self.unsafe == "unknown-event" else "move")
            if self.unsafe == "unknown-disk":
                self.phase = "unknown-disk"
        elif n == 2:
            self.place = (0x14, 15, 4, 1)
        elif n == 3:
            # The crossing key: the live run showed the position triple
            # change at the key, one poll before the screen redraws.
            self._pre_crossing_place = self.place
            self.place = (0, 0, 4, 1)
            self.crossing_lag = 1
            self.crossing_quiet = self.quiet_reads
            self.phase = "side4" if self.unsafe == "other-side" else "side3"
        elif n == 4:
            self.place = (0, 1, 4, 1)
            if self.unsafe == "early-question":
                self.phase = "yes-no"
        elif n == 5:
            self.place = (0, 1, 4, 0)
        elif self.unsafe == "question-wrong-place":
            # The question screen appears, but the memory place stays at
            # the pre-move reading and never catches up.
            self.phase = "question"
        elif self.unsafe == "question-lag":
            # The question screen appears with the memory place one poll
            # behind, catching up on the reread the fix added.
            self._question_lag_place = self.place
            self.place = (0, 1, 3, 0)
            self.question_state_lag = 1
            self.phase = "question"
        else:
            self.place = (0, 1, 3, 0)
            if self.unsafe == "wrong-question":
                self.phase = "yes-no"
            else:
                # `temple-route-c` also typed the priestess's greeting
                # before the healing question; use invented text, not the
                # game's own string.
                self.typing = ["A PR", "A PRIESTESS GREETS YOU."]
                self.phase = "question"

    def wanted_disk(self, screen):
        return "SIDE3.D64" if "INSERT SIDE # 3" in screen.text() else None

    def handle_prompt(self, screen):
        assert list(self.out.glob("*boundary-side3-before-answer.png"))
        self.keys.append("side3")
        self.cursor_reads = self.cursor_after_side3
        if self.unsafe == "duplicate-side":
            self.phase = "side3"
            return True
        if self.after_side3 == "continue":
            self.phase = "continue"
            return True
        # `temple-route-c`: after the side-3 answer, one further quiet
        # screen, then Pool types the gateway square's arrival text a
        # character at a time before the move bar redraws. Invented text,
        # not the game's own string.
        self.post_answer_quiet = 1
        self.typing = ["A GATE B", "A GATE BY THE WALL."]
        self.phase = "move"
        return True

    def press_kernal(self, code):
        self.keys.append("continue")
        assert code == 0x0D and self.phase == "continue"
        # The crossing key already moved the party; the continuation
        # only clears the prompt.
        self.phase = "move"

    def confirm_bar(self, row, was):
        if self.phase == "temple" and self.bar_at == 2:
            assert row == 24 and "POOL" in was
            self.keys.append("POOL")
            self.phase = "poolq"
            return
        if self.phase == "poolq":
            assert row == 24 and "YES" in was
            self.keys.append("pool-YES")
            self.phase = "temple"
            return
        if self.phase == "treasure":
            assert row == 24 and "GO BACK" in was
            self.keys.append("GO BACK")
            self.bar_at = 0
            self.phase = "temple"
            return
        if (self.phase == "temple" and "pool-YES" in self.keys
                and self.bar_at == 4):
            assert row == 24 and "SHARE" in was
            self.keys.append("SHARE")
            self.pool_coins = [0] * 5
            self.phase = {"prompt": "yes-no", "unknown": "unknown"}.get(
                self.after_share, "temple")
            return
        if self.phase == "temple" and self.bar_at == len(self._bar_words()) - 1:
            assert row == 24 and "EXIT" in was
            self.keys.append("EXIT")
            self.leaving_reads = 3
            self.phase = "leaving"
            self.after_leaving = getattr(self, "after_leaving", "world")
            if self.treasure_prompts and "pool-YES" in self.keys:
                self.treasure_prompts -= 1
                self.after_leaving = "treasure"
            elif self.after_leaving == "treasure":
                self.after_leaving = "world"
            return
        if self.phase == "temple":
            assert row == 24 and "HEAL" in was and self.bar_at == 0
            self.keys.append("HEAL")
            self.phase = "heal-blank" if self.heal_never_draws else "heal"
            if not self.heal_never_draws:
                self.heal_blank_reads = 3
                self.heal_old_bar_reads = 3 if self.unsafe == "heal-slow" else 0
            return
        if self.phase == "price":
            assert row == 24 and "YES" in was
            self.keys.append("YES")
            self.phase = "result"
            self.pool_coins[3] -= 5500 if "POOL" in self.keys else 0
            return
        assert self.phase == "question" and row == 24 and "YES" in was
        self.keys.append("YES")
        if self.unsafe == "question-twice" and not self._question_answered_once:
            self._question_answered_once = True
            # The question lingers: one more typed line, then the same
            # question again, which the second answer must refuse.
            self.typing = ["ANOTHER GROUP APPROACHES."]
            self.phase = "question"
        else:
            self.phase = "temple"


def _temple_reading():
    return {"party": [{"slot": 5, "name": "BRUTUS", "status": 3,
                       "traits": [0] * 9 + [32], "creature_type": 4,
                       "record_bytes": {"0xA3": 2}}],
            "effect_rows": [None] * 63 + [[63, 32, 5, 0, 5]],
            "effects": [[63, 32, 5, 0, 5]]}


def _temple_fake_run(tmp_path, monkeypatch, *, unsafe=None,
                     after_side3="arrival-text", cursor_after_side3=0):
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(A.time, "sleep", lambda seconds: setattr(
        clock, "now", clock.now + seconds))
    # `temple_sample()` (#715) reads the screen and the PC through the
    # monitor, alongside memory; route both through the fake session so a
    # poll uses exactly one fake `screen()` call, as `crossing_lag`,
    # `quiet_reads`, `post_answer_quiet` and `typing` assume.
    monkeypatch.setattr(A.S, "is_bitmap", lambda m: False)
    monkeypatch.setattr(A.S, "read_screen", lambda m: m.session.screen())
    monkeypatch.setattr(A.S, "_pc_id_of", lambda *a, **k: 1)
    monkeypatch.setattr(A.S, "_pc_of", lambda *a, **k: 0x10C2)
    session = _TempleSession(tmp_path, unsafe=unsafe, after_side3=after_side3,
                             cursor_after_side3=cursor_after_side3)
    events = []
    log = SimpleNamespace(emit=lambda *args, **kwargs: events.append((args, kwargs)))
    run = A.PoolRun(session, log, tmp_path, A.c64_port.POOL_OF_RADIANCE, {})
    run.clock = lambda: clock.now
    run.deadline = 1500
    run.temple_input_deadline = 0 if unsafe == "deadline" else 1400
    if unsafe == "bad-identity":
        wrong = _temple_reading()
        wrong["effect_rows"][63] = [63, 0, 5, 0, 5]
        run.reading = lambda: wrong
    else:
        run.reading = _temple_reading
    if unsafe == "late-after-first":
        original_move = session.move_key

        def late_move(move):
            original_move(move)
            clock.now = 1400

        session.move_key = late_move
    return run, session, events


@pytest.mark.parametrize("after_side3", ["arrival-text", "continue"])
def test_temple_probe_reaches_and_captures_arrival_then_stops(
        tmp_path, monkeypatch, after_side3):
    """The probe stops at the temple arrival screen and captures it; it
    never navigates into the HEAL service list, which has never been seen
    live (#700)."""
    run, session, events = _temple_fake_run(tmp_path, monkeypatch,
                                            after_side3=after_side3)
    result = run.temple_probe("BRUTUS")
    assert result["arrival"] == run.temple_checkpoints[-1]["stem"]
    assert result["side3_prompts"] == 1
    assert result["questions"] == 1
    assert session.moves == list("KKIIJI")
    assert run.temple_checkpoints[-1]["state"]["save_copy"] == [15, 4, 3]
    assert run.temple_checkpoints[-1]["state"]["x"] == 1
    assert run.temple_checkpoints[-1]["tag"] == "temple-arrival"
    assert session.phase == "temple"
    assert "HEAL" not in session.keys
    if after_side3 == "arrival-text":
        assert result["continuations"] == 0
        assert session.keys == ["side3", "YES"]
        assert [x["tag"] for x in run.temple_checkpoints] == [
            "loaded-source", "move-1-settled", "move-2-settled",
            "boundary-side3-before-answer", "move-3-settled",
            "move-4-settled", "move-5-settled",
            "temple-question-before-answer", "temple-arrival"]
        assert [kwargs for args, kwargs in events
                if args[0] == "temple-quiet-screen"] == [
            {"move": 3, "place": (0, 0, 4, 1)}]
        assert [kwargs for args, kwargs in events
                if args[0] == "temple-text-screen"] == [
            {"move": 3, "place": (0, 0, 4, 1)},
            {"move": 6, "place": (0, 1, 3, 0)}]
    else:
        assert result["continuations"] == 1
        assert session.keys == ["side3", "continue", "YES"]
        assert [x["tag"] for x in run.temple_checkpoints] == [
            "loaded-source", "move-1-settled", "move-2-settled",
            "boundary-side3-before-answer", "continuation-before-answer",
            "move-3-settled", "move-4-settled", "move-5-settled",
            "temple-question-before-answer", "temple-arrival"]
    assert all((tmp_path / (x["stem"] + ext)).is_file()
               for x in run.temple_checkpoints for ext in (".txt", ".png", ".json"))
    assert any(args[0] == "temple-checkpoint" for args, _ in events)


def test_temple_probe_heal_selects_it_once_and_keeps_the_next_drawn_screen(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    result = run.temple_probe("BRUTUS HEAL")
    assert session.keys == ["side3", "YES", "HEAL"]
    assert session.phase == "heal"
    assert run.temple_checkpoints[-1]["tag"] == "heal-screen"
    got = result["heal_screen"]
    assert got["stem"] == run.temple_checkpoints[-1]["stem"]
    assert result["arrival"] != got["stem"]
    assert (tmp_path / f"{got['stem']}.png").is_file()
    assert got["rows"][4] == "HOW MAY WE HELP YOU"
    assert got["rows"][15] == _framed("RAISE DEAD")
    assert got["rows"][24] == ""
    assert got["settled"] is True and got["held"] >= A.HEAL_SETTLE
    welcome, listing = result["heal_screens"]
    assert welcome[15] == "" and welcome[3] == "WELCOME TO THE TEMPLE,"
    assert listing == got["rows"]
    frames = [kw["rows"] for args, kw in events if args[0] == "temple-heal-frame"]
    assert [f[15] for f in frames] == ["", "", _framed("RAISE DEAD")]


def test_temple_probe_heal_stops_at_ninety_seconds_keeping_the_blank_frame(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch,
                                            unsafe="heal-never-draws")
    with pytest.raises(A.StepFailed, match="90 second limit"):
        run.temple_probe("BRUTUS HEAL")
    assert session.keys[-1] == "HEAL"
    assert run.temple_checkpoints[-1]["tag"] == "lost-heal"
    assert run.clock() >= 90


def test_temple_probe_heal_stops_when_the_highlight_is_not_on_brutus_row(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch,
                                            unsafe="highlight-row-5")
    with pytest.raises(A.StepFailed, match="highlighted top row"):
        run.temple_probe("BRUTUS HEAL")
    assert "HEAL" not in session.keys
    assert run.temple_checkpoints[-1]["tag"] == "lost-member"


def test_temple_probe_heal_does_not_keep_the_lingering_temple_bar(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch,
                                            unsafe="heal-slow")
    run.temple_probe("BRUTUS HEAL")
    kept = run.temple_checkpoints[-1]
    assert kept["tag"] == "heal-screen"
    assert (tmp_path / f"{kept['stem']}.json").is_file()
    assert session.phase == "heal" and session.heal_old_bar_reads == 0


def test_temple_probe_heal_keeps_only_a_bar_seen_twice_running(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch,
                                            unsafe="heal-glitch")
    kept = []
    real = run.temple_checkpoint
    run.temple_checkpoint = lambda tag, sample=None: (
        kept.append((tag, sample and sample.screen.text())) or real(tag, sample))
    run.temple_probe("BRUTUS HEAL")
    assert kept[-1][0] == "heal-screen"
    assert "HOW MAY WE HELP YOU" in kept[-1][1]
    assert "HELP" not in "".join(
        text for tag, text in kept[:-1] if text)
    assert [k for k in kept if k[0] == "heal-screen"] == [kept[-1]]
    frames = [kw["rows"] for args, kw in events if args[0] == "temple-heal-frame"]
    assert len(frames) == 4 and not any(frames[0])
    assert frames[1][4] == "" and frames[2][4] == "HOW MAY WE HELP YOU"
    assert frames[2][15] == "" and frames[3][15] == _framed("RAISE DEAD")
    assert "RAISE DEAD" in kept[-1][1]


def test_temple_probe_heal_settle_is_fifteen_seconds():
    assert A.HEAL_SETTLE == 15.0


def test_temple_probe_heal_waits_out_a_list_that_draws_after_twelve_seconds(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch,
                                            unsafe="heal-late-list")
    result = run.temple_probe("BRUTUS HEAL")
    got = result["heal_screen"]
    assert got["rows"][15] == _framed("RAISE DEAD")
    assert got["settled"] is True and got["held"] >= A.HEAL_SETTLE
    assert len(result["heal_screens"]) == 2
    assert got["stem"] == run.temple_checkpoints[-1]["stem"]


def test_temple_probe_heal_cut_after_a_steady_welcome_keeps_it_unsettled(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch,
                                            unsafe="heal-cut")
    original = session.confirm_bar
    fake_now = run.clock
    offset = [0.0]
    run.clock = lambda: fake_now() + offset[0]

    def late(row, was):
        heal = session.phase == "temple"
        original(row, was)
        if heal:
            offset[0] = 1385.0 - fake_now()

    session.confirm_bar = late
    result = run.temple_probe("BRUTUS HEAL")
    got = result["heal_screen"]
    assert got["settled"] is False and 1 <= got["held"] < A.HEAL_SETTLE
    assert got["rows"][3] == "WELCOME TO THE TEMPLE,"
    assert got["rows"][15] == ""
    assert not [c for c in run.temple_checkpoints
                if c["tag"].startswith("lost-")]
    assert run.temple_checkpoints[-1]["tag"] == "heal-screen"
    assert run.clock() < 1450


def test_temple_probe_heal_stops_at_the_input_deadline_not_ninety_seconds(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch,
                                            unsafe="heal-never-draws")
    original = session.confirm_bar
    fake_now = run.clock
    offset = [0.0]
    run.clock = lambda: fake_now() + offset[0]

    def late(row, was):
        heal = session.phase == "temple"
        original(row, was)
        if heal:
            offset[0] = 1350.0 - fake_now()

    session.confirm_bar = late
    with pytest.raises(A.StepFailed, match="temple input deadline"):
        run.temple_probe("BRUTUS HEAL")
    assert run.temple_checkpoints[-1]["tag"] == "lost-heal"
    assert 1400 <= run.clock() < 1450


def test_temple_probe_heal_stops_before_heal_when_another_member_is_on_top(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch,
                                            unsafe="other-top")
    with pytest.raises(A.StepFailed, match="highlighted top row"):
        run.temple_probe("BRUTUS HEAL")
    assert "HEAL" not in session.keys
    assert run.temple_checkpoints[-1]["tag"] == "lost-member"


@pytest.mark.parametrize("unsafe,maximum_moves", [
    ("yes-no", 1), ("other-side", 3), ("duplicate-side", 3),
    ("wrong-facing", 1), ("wrong-menu", 6),
    ("deadline", 0), ("late-after-first", 1),
    ("short-monitor", 0), ("bad-identity", 0),
    ("wrong-area", 1), ("pending-area", 1), ("unknown-event", 1),
    ("unknown-disk", 1), ("encounter", 1),
    ("early-question", 4), ("wrong-question", 6), ("question-twice", 6),
])
def test_temple_probe_stops_at_unsafe_screen_or_state_before_more_input(
        tmp_path, monkeypatch, unsafe, maximum_moves):
    run, session, _ = _temple_fake_run(tmp_path, monkeypatch, unsafe=unsafe)
    with pytest.raises(A.StepFailed):
        run.temple_probe("BRUTUS")
    assert len(session.moves) <= maximum_moves
    assert "HEAL" not in session.keys
    assert session.keys.count("side3") <= 1
    assert session.keys.count("YES") <= 1
    if unsafe in ("early-question", "wrong-question"):
        assert "YES" not in session.keys
    assert not any(x["tag"] == "temple-arrival" for x in run.temple_checkpoints)




def test_temple_probe_pins_the_lost_stop_the_live_m_route_hit(
        tmp_path, monkeypatch):
    """Pins the exact stop `temple-route-a` hit at `42b8d40a12`: the old
    route's first key, `M`, was meant to turn the party in place, but in
    Pool of Radiance `M` steps one square backward, crossing the area edge
    immediately. The driver's own guard stopped rather than guessing.

    This reconstructs the historical `M`-based route via monkeypatch to
    freeze that old failure message; it does not exercise the current
    default BRUTUS route. The happy-path test asserting
    `session.moves == list("KKIIJI")` is what proves the current route."""
    old_route = (
        ("M", (0x14, 15, 4, 3), (0x14, 15, 4, 1)),
        ("I", (0x14, 15, 4, 1), (0, 0, 4, 1)),
        ("I", (0, 0, 4, 1), (0, 1, 4, 1)),
        ("J", (0, 1, 4, 1), (0, 1, 4, 0)),
        ("I", (0, 1, 4, 0), (0, 1, 3, 0)),
    )
    monkeypatch.setattr(A, "TEMPLE_SOURCES", {
        A.TEMPLE_BRUTUS_SHA256: dataclasses.replace(
            A.TEMPLE_SOURCES[A.TEMPLE_BRUTUS_SHA256], route=old_route)})
    run, session, _ = _temple_fake_run(tmp_path, monkeypatch)

    def move_key(move):
        session.moves.append(move)
        assert move == "M"
        session.place = (0, 0, 4, 1)  # what `M` actually did, live

    session.move_key = move_key
    with pytest.raises(A.StepFailed) as info:
        run.temple_probe("BRUTUS")
    assert ("movement 1 reached (0, 0, 4, 1), expected (20, 15, 4, 1)"
            in str(info.value))


def test_temple_quiet_screen_that_never_resolves_stops_at_the_transition_limit(
        tmp_path, monkeypatch):
    """A quiet screen gets a wait, not an unbounded one: with the side-3
    prompt never drawn, the crossing stops at the 90-second transition limit
    and sends nothing further."""
    run, session, _ = _temple_fake_run(tmp_path, monkeypatch)
    session.quiet_reads = 10 ** 6
    with pytest.raises(A.StepFailed) as info:
        run.temple_probe("BRUTUS")
    assert "movement 3 did not settle within 90 seconds" in str(info.value)
    assert session.moves == list("KKI")
    assert "side3" not in session.keys


def test_temple_text_with_a_bar_never_drawn_stops_at_the_transition_limit(
        tmp_path, monkeypatch):
    """A frame with text and a blank bar gets a wait, not an unbounded one:
    with the bar never drawn, the crossing stops at the 90-second transition
    limit and sends nothing further."""
    run, session, _ = _temple_fake_run(tmp_path, monkeypatch)
    session.quiet_text = "A GROUP OF KOBOLDS"
    session.quiet_reads = 10 ** 6
    with pytest.raises(A.StepFailed) as info:
        run.temple_probe("BRUTUS")
    assert "movement 3 did not settle within 90 seconds" in str(info.value)
    assert session.moves == list("KKI")
    assert "side3" not in session.keys


def test_temple_arrival_settles_without_a_status_line(tmp_path, monkeypatch):
    """`572b9ca0ee-temple-route-d` frame 10 confirms the temple arrival
    screen carries no status line: a menu or picture screen replaces it
    there, and the settle must not wait forever on one that never
    reappears. The rebuilt fake models this as the default arrival
    screen, so this is the ordinary case rather than an opt-in one."""
    run, session, _ = _temple_fake_run(tmp_path, monkeypatch)
    result = run.temple_probe("BRUTUS")
    assert result["arrival"] == "09-temple-temple-arrival"


def test_temple_arrival_never_settles_on_a_stale_greeting_status_line(
        tmp_path, monkeypatch):
    """A status line that is present but wrong is not the same gap as a
    missing one: unlike `test_temple_arrival_settles_without_a_status_line`,
    a wrong reading must keep the transition waiting rather than settling."""
    run, session, _ = _temple_fake_run(tmp_path, monkeypatch)
    session.unsafe = "stale-greeting-status"
    with pytest.raises(A.StepFailed) as info:
        run.temple_probe("BRUTUS")
    assert "movement 6 did not settle within 90 seconds" in str(info.value)
    assert session.moves == list("KKIIJI")


def test_temple_question_at_a_lagging_place_waits_then_answers(
        tmp_path, monkeypatch):
    """A one-poll memory lag at the healing question, the same kind
    `crossing_lag` models for an area crossing, must not stop the run: the
    reread the fix added has to catch up with the screen."""
    run, session, _ = _temple_fake_run(tmp_path, monkeypatch)
    session.unsafe = "question-lag"
    result = run.temple_probe("BRUTUS")
    assert result["arrival"] == "09-temple-temple-arrival"
    assert session.moves == list("KKIIJI")
    assert session.keys.count("YES") == 1


def test_temple_question_at_the_wrong_place_waits_then_stops(
        tmp_path, monkeypatch):
    """The healing question can appear before the memory read of the
    arrival place catches up (the same one-poll lag `crossing_lag` models
    for an area crossing); a mismatch that never resolves still stops,
    with the same message an immediate stop gave before that wait was
    added."""
    run, session, _ = _temple_fake_run(tmp_path, monkeypatch)
    session.unsafe = "question-wrong-place"
    with pytest.raises(A.StepFailed) as info:
        run.temple_probe("BRUTUS")
    assert "healing question at the wrong place" in str(info.value)
    assert session.moves == list("KKIIJI")
    assert "YES" not in session.keys


def test_temple_text_with_a_blank_bar_waits_then_stops_on_an_unapproved_bar(
        tmp_path, monkeypatch):
    """Text in the message window with row 24 blank gets a wait, the same as
    a quiet screen: `temple-route-c` showed this is Pool typing an ordinary
    square's arrival text (`YOU ARE B`, then `YOU ARE BY`). What still stops
    the route is an unrecognised bar drawn once typing ends."""
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    session.quiet_text = "A GROUP OF KOBOLDS"
    original_move_key = session.move_key

    def move_key(move):
        original_move_key(move)
        if len(session.moves) == 3:
            session.phase = "unknown"

    session.move_key = move_key
    with pytest.raises(A.StepFailed) as info:
        run.temple_probe("BRUTUS")
    assert "unexpected screen after movement" in str(info.value)
    assert session.moves == list("KKI")
    assert "side3" not in session.keys
    assert [kwargs for args, kwargs in events
            if args[0] == "temple-text-screen"] == [
        {"move": 3, "place": (0, 0, 4, 1)}]
    lost = next(c for c in run.temple_checkpoints if c["tag"] == "lost-event")
    assert "TRAIN CHARACTER" in (tmp_path / (lost["stem"] + ".txt")).read_text()


@pytest.mark.parametrize("quiet_text", ["", "SOME TEXT"])
def test_temple_quiet_screen_at_an_unplanned_place_still_stops(
        tmp_path, monkeypatch, quiet_text):
    """The wait covers only the place before the key and the one expected
    after it; a quiet or blank-bar-with-text screen anywhere else stops at
    once."""
    run, session, _ = _temple_fake_run(tmp_path, monkeypatch)
    session.quiet_text = quiet_text

    def move_key(move):
        session.moves.append(move)
        session._pre_crossing_place = session.place
        session.place = (0, 0, 4, 1)
        session.crossing_quiet = 10 ** 6

    session.move_key = move_key
    with pytest.raises(A.StepFailed) as info:
        run.temple_probe("BRUTUS")
    assert ("movement 1 reached (0, 0, 4, 1), expected (20, 15, 4, 0)"
            in str(info.value))
    assert session.moves == ["K"]


@pytest.mark.parametrize("prompt", ["INSERT SIDE # 3", "YES NO",
                                    "PRESS ANY KEY TO CONTINUE"])
def test_temple_move_rechecks_prompt_with_retained_move_bar_before_key(
        tmp_path, monkeypatch, prompt):
    run, session, _ = _temple_fake_run(tmp_path, monkeypatch)
    clean = session.screen()
    rows = [clean.row(n) for n in range(25)]
    rows[20] = prompt
    unsafe = _TempleScreen(rows)
    calls = 0

    def next_screen():
        nonlocal calls
        calls += 1
        return clean if calls == 1 else unsafe

    session.screen = next_screen
    with pytest.raises(A.StepFailed):
        run._temple_move("K", (0x14, 15, 4, 3))
    assert session.moves == []


def test_temple_one_poll_renderer_cursor_after_the_crossing_does_not_stop(
        tmp_path, monkeypatch):
    """Pool's 3D renderer moves `$C04B`-`$C04D` off the party's square while
    it draws (#715, `temple-route-e`'s cause): a single glitched read of the
    triple right after the crossing must not stop the route, the way it did
    live. `cursor_after_side3=1` reproduces that one-poll glitch exactly."""
    run, session, _ = _temple_fake_run(tmp_path, monkeypatch,
                                       cursor_after_side3=1)
    result = run.temple_probe("BRUTUS")
    assert result["arrival"] == run.temple_checkpoints[-1]["stem"]
    assert session.moves == list("KKIIJI")


def test_temple_renderer_cursor_on_two_samples_still_stops(
        tmp_path, monkeypatch):
    """A cursor glitch held for two consecutive samples is not a one-poll
    render artefact and must still stop the route (#715); the retained
    checkpoint is the judged sample itself, not a fresh re-read."""
    run, session, _ = _temple_fake_run(tmp_path, monkeypatch,
                                       cursor_after_side3=2)
    with pytest.raises(A.StepFailed) as info:
        run.temple_probe("BRUTUS")
    assert ("movement 3 reached (0, 1, 4, 1), expected (0, 0, 4, 1)"
            in str(info.value))
    assert session.moves == list("KKI")
    lost = next(c for c in run.temple_checkpoints if c["tag"] == "lost-place")
    assert lost["judged"] is True
    assert lost["state"]["x"] == 1
    assert lost["pc"] == "$10C2"


def test_temple_move_clears_a_one_poll_cursor_glitch_before_sending_a_key(
        tmp_path, monkeypatch):
    """The two tests above only glitch the cursor after the crossing key's
    side-3 answer, inside `_temple_transition`; `_temple_move`'s own poll,
    taken before every movement key including the crossing itself, has no
    coverage there. `_temple_steady`'s first sample is what `_temple_move`
    calls right before `K` (#715): a one-poll glitch on it must not stop the
    move, the same as a one-poll glitch after the crossing does not."""
    run, session, _ = _temple_fake_run(tmp_path, monkeypatch)
    session.cursor_reads = 1
    run._temple_move("K", (0x14, 15, 4, 3))
    assert session.moves == ["K"]


def test_temple_move_stops_when_the_cursor_never_settles_before_a_key(
        tmp_path, monkeypatch):
    """A glitch that never returns the same triple twice never lets two
    consecutive samples agree, so `_temple_steady` itself times out and
    stops with its own "unsteady" failure (read from the function, not
    invented) before `_temple_move` ever sends `K` (#715)."""
    run, session, _ = _temple_fake_run(tmp_path, monkeypatch)
    real_read = _TempleMonitor.read
    calls = {"n": 0}

    def jittering_read(self, address, count):
        if address == 0xC04B:
            calls["n"] += 1
            return bytes((1, 4, calls["n"] % 4))
        return real_read(self, address, count)

    monkeypatch.setattr(_TempleMonitor, "read", jittering_read)
    with pytest.raises(A.StepFailed) as info:
        run._temple_move("K", (0x14, 15, 4, 3))
    assert "place unsteady before K" in str(info.value)
    assert session.moves == []
    lost = next(c for c in run.temple_checkpoints if c["tag"] == "lost-unsteady")
    assert lost["judged"] is True


def test_temple_guards_read_the_screen_only_inside_a_monitor_pause(
        tmp_path, monkeypatch):
    """Every temple guard reads the screen through `temple_sample()`'s one
    paused monitor pause (#715), never through a bare `Session.screen()`
    call taken outside one."""
    run, session, _ = _temple_fake_run(tmp_path, monkeypatch)
    real_screen = session.screen

    def guarded_screen():
        assert session.paused, "screen read outside a monitor pause"
        return real_screen()

    session.screen = guarded_screen
    result = run.temple_probe("BRUTUS")
    assert result["arrival"] == run.temple_checkpoints[-1]["stem"]




@pytest.mark.parametrize("steps", [
    [],                                   # nothing to do
    ["camp-list"],                        # load must come first
    ["load", "load"],                     # one boot, one load
    ["load", "dance"],                    # not a step
    ["load", "items"],                    # whose items?
    ["load", "save now"],                 # save takes nothing
    ["load", "rest 8"],                   # a unit is required
    ["load", "rest 61m"],                 # the minutes byte is under an hour
    ["load", "peek 4900"],                # and how many bytes?
    ["load", "fight 0"],
])
def test_a_step_list_the_driver_cannot_run_is_refused(steps):
    with pytest.raises(ValueError):
        A.parse_steps(steps)


def _refused_before_a_slot(tmp_path, monkeypatch, argv):
    def no_slot(*a, **k):
        raise AssertionError("a slot was claimed")
    monkeypatch.setattr(A.S, "claim_slot", no_slot)
    with pytest.raises(SystemExit) as info:
        A.main(argv + ["--out", str(tmp_path / "out")])
    assert info.value.code == 2


def test_a_run_with_no_save_is_refused_before_a_slot_is_claimed(tmp_path, monkeypatch):
    _refused_before_a_slot(tmp_path, monkeypatch, ["--title", "ssb",
                           "--disks", str(tmp_path), "--steps", "load"])


def test_a_run_with_no_game_disks_is_refused_before_a_slot_is_claimed(
        tmp_path, monkeypatch):
    monkeypatch.setattr(A, "tool_disks", lambda: None)
    monkeypatch.setattr(A.gamedisks, "find", lambda name: None)
    _refused_before_a_slot(tmp_path, monkeypatch, [
        "--title", "ssb", "--save", str(_fixture_disk(tmp_path)),
        "--steps", "load", "camp-list"])


def test_a_bad_step_list_is_refused_before_a_slot_is_claimed(tmp_path, monkeypatch):
    _refused_before_a_slot(tmp_path, monkeypatch, [
        "--title", "ssb", "--save", str(_fixture_disk(tmp_path)),
        "--disks", str(tmp_path), "--steps", "camp-list"])


# --- staging -----------------------------------------------------------------

def test_staging_writes_exactly_the_named_bytes(tmp_path):
    src = _fixture_disk(tmp_path)
    dest = tmp_path / "staged-copy.d64"
    before = _payload(src)
    before_roster = _roster(src)
    took = A.stage(src, dest, "pool-of-radiance",
                   rows=[(63, 5, 0xFF, 0x0A, 0x03)],
                   traits=[(0, 9, 38)],
                   items=[(0, 2, 4, 1)],
                   record_bytes=[(0, 0xCA, 5), (0, 0x20, 36)],
                   statuses=[(1, 0x83)])
    after = _payload(dest)
    after_roster = _roster(dest)
    box = c64_save.CONTAINERS["pool-of-radiance"]
    wanted = {
        effects.EFFECT_ID_OFFSET + 63: 5,
        effects.EFFECT_OWNER_OFFSET + 63: 0xFF,
        effects.EFFECT_DURATION_OFFSET + 63: 0x0A,
        effects.EFFECT_MAGNITUDE_OFFSET + 63: 0x03,
        box.slot(0) + A.TRAIT_SLOT + 9: 38,
        box.items(0) + 2 * ITEM_SIZE + 4: 1,
        box.slot(0) + 0xCA: 5,
        box.slot(0) + 0x20: 36,
    }
    changed = {i: after[i] for i in range(len(after)) if after[i] != before[i]}
    assert changed == {i: v for i, v in wanted.items() if before[i] != v}
    assert all(after[i] == v for i, v in wanted.items())
    assert len(after) == len(before)
    assert _payload(src) == before, "the source was written"
    roster_at = box.roster_offset + box.roster_stride
    roster_changed = {i: after_roster[i] for i in range(len(after_roster))
                      if after_roster[i] != before_roster[i]}
    assert roster_changed == ({roster_at: 0x83}
                              if before_roster[roster_at] != 0x83 else {})
    assert _roster(src) == before_roster, "the source roster was written"
    assert took["record_bytes"] == [
        {"slot": 0, "byte": 0xCA, "offset": box.slot(0) + 0xCA,
         "was": before[box.slot(0) + 0xCA], "now": 5},
        {"slot": 0, "byte": 0x20, "offset": box.slot(0) + 0x20,
         "was": before[box.slot(0) + 0x20], "now": 36}]
    assert took["statuses"] == [{"slot": 1, "file": "SAVEDGAME1",
                                   "offset": roster_at,
                                   "was": before_roster[roster_at], "now": 0x83}]
    assert took["rows"] == [{"slot": 63, "was": [before[i + 63] for i in (
        effects.EFFECT_ID_OFFSET, effects.EFFECT_OWNER_OFFSET,
        effects.EFFECT_DURATION_OFFSET, effects.EFFECT_MAGNITUDE_OFFSET)],
        "now": [5, 0xFF, 0x0A, 0x03]}]
    assert took["effects"] == [[63, 5, 0xFF, 0x0A, 0x03]]
    assert took["magic_items"]["0"] == [2]


def test_staging_refuses_a_save_of_another_title(tmp_path):
    with pytest.raises(ValueError, match="Pool of Radiance"):
        A.stage(_fixture_disk(tmp_path), tmp_path / "staged-copy.d64",
                "curse-of-the-azure-bonds")


def test_stage_only_writes_the_evidence_and_claims_no_slot(tmp_path, monkeypatch):
    def no_slot(*a, **k):
        raise AssertionError("a slot was claimed")
    monkeypatch.setattr(A.S, "claim_slot", no_slot)
    out = tmp_path / "evidence"
    rc = A.main(["--title", "pool", "--save", str(_fixture_disk(tmp_path)),
                 "--stage-row", "63=05:FF:0A:03", "--stage-only",
                 "--steps", "load", "items BRUTUS", "--out", str(out)])
    assert rc == 0
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["staged"]["effects"] == [[63, 5, 0xFF, 0x0A, 0x03]]
    assert summary["completed"] is True and summary["results"] == []
    assert (out / "staged.D64").is_file()


def test_stage_only_accepts_the_pool_zombie_inputs_and_decodes_all_slots(
        tmp_path, monkeypatch):
    monkeypatch.setattr(A.S, "claim_slot", lambda *a, **k: pytest.fail("claimed a slot"))
    out = tmp_path / "animate"
    rc = A.main(["--title", "pool", "--save", str(_fixture_disk(tmp_path)),
                 "--stage-record", "0:0xCA=5", "--stage-record", "0:0x20=36",
                 "--stage-record", "1:0xD7=4", "--stage-trait", "1:9=32",
                 "--stage-status", "1=0x83", "--stage-only", "--steps", "load",
                 "--out", str(out)])
    assert rc == 0
    staged = json.loads((out / "summary.json").read_text(encoding="utf-8"))["staged"]
    saved = A.decode_save(out / "staged.D64", staged)
    assert len(saved["party"]) == 8
    assert saved["party"][1]["status"] == 0x83
    assert saved["party"][1]["creature_type"] == 4
    assert saved["party"][1]["traits"][9] == 32
    assert saved["statuses"][0]["saved"] == 0x83
    assert [item["saved"] for item in saved["record_bytes"]] == [5, 36, 4]


def test_pool_checkpoints_name_brutus_and_keep_a_cleared_rows_other_bytes():
    record = bytearray(0x100)
    record[:6] = b"BRUTUS"
    for offset, value in {0x9F: 6, 0xA3: 2, 0xA4: 0, 0xB6: 32,
                          0xB8: 0xFE, 0xCC: 3, 0xD7: 4, 0xEC: 0xFF}.items():
        record[offset] = value
    roster = bytearray(8 * 0x20)
    roster[5 * 0x20] = 0x03
    roster[5 * 0x20 + 0x0C] = 0x01
    party = A._party_reading([bytes(0x100)] * 5 + [record] +
                             [bytes(0x100)] * 2, roster, 0x20)
    member = party[5]
    assert member["name"] == "BRUTUS"
    assert (member["status"], member["side"]) == (0x03, 0x01)
    assert (member["movement"], member["fighter_level"]) == (6, 3)
    assert member["record_bytes"] == {
        "0xA3": 2, "0xA4": 0, "0xB6": 32, "0xB8": 0xFE,
        "0xD7": 4, "0xEC": 0xFF}
    assert member["traits"] == [0] * 9 + [32]

    payload = bytearray(0x300)
    payload[effects.EFFECT_OWNER_OFFSET + 63] = 5
    payload[effects.EFFECT_MAGNITUDE_OFFSET + 63] = 5
    rows = A._effect_rows(payload)
    assert len(rows) == 64
    assert rows[63] == [63, 0, 5, 0, 5]
    assert A._effect_list(payload) == []


def test_an_evidence_directory_is_never_reused(tmp_path):
    out = tmp_path / "evidence"
    out.mkdir()
    (out / "run.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(SystemExit) as info:
        A.main(["--title", "pool", "--save", str(_fixture_disk(tmp_path)),
                "--stage-only", "--steps", "load", "--out", str(out)])
    assert info.value.code == 2


def test_staging_matches_the_two_drivers_it_stands_in_for(tmp_path):
    """On a real Pool save, the same stage through `effectdrive.stage_effects`
    and `traitdrive.stage_traits` gives the same disk byte for byte."""
    porsave = gamedata.save_disk("PORSAVE13")
    from tools.c64 import effectdrive, traitdrive
    from tools.c64 import session as S
    ours = tmp_path / "ours.d64"
    theirs = tmp_path / "theirs.d64"
    A.stage(porsave, ours, "pool-of-radiance",
            rows=[(63, 5, 0xFF, 0x0A, 0x03), (62, 5, 2, 0x0A, 0x03)],
            traits=[(1, 9, 38)])
    S.stage_writable(porsave, theirs)
    effectdrive.stage_effects(theirs, [(63, 5, 0xFF, 0x0A, 0x03),
                                       (62, 5, 2, 0x0A, 0x03)])
    traitdrive.stage_traits(theirs, [(1, 9, 38)])
    assert ours.read_bytes() == theirs.read_bytes()


def test_porsave13_holds_no_magic_item_so_a_run_must_stage_one(tmp_path):
    """The reading needs an item Detect Magic marks: bonus byte `+4` not 0
    (`LIBRARY $39BC`). PORSAVE13's six characters hold 55 items and none."""
    porsave = gamedata.save_disk("PORSAVE13")
    took = A.stage(porsave, tmp_path / "porsave13-copy.d64", "pool-of-radiance")
    assert took["magic_items"] == {}
    took = A.stage(porsave, tmp_path / "porsave13-item.d64", "pool-of-radiance",
                   items=[(1, 2, 4, 1)])
    assert took["magic_items"] == {"1": [2]}


# --- the screens ---------------------------------------------------------------

def _window(lines: dict[int, str], bar: str = "") -> list[str]:
    """A 25-row screen in the frame the Pool capture shows: `@[[..[@` top and
    bottom, `$` down both sides, text from column 1, and the bar on row 24."""
    rows = []
    for r in range(25):
        if r in (0, 23):
            rows.append("@" + "[" * 38 + "@")
        elif r == 24:
            rows.append(bar.ljust(40))
        else:
            rows.append("$" + lines.get(r, "").ljust(38) + "$")
    return rows


def test_a_camp_list_page_names_who_and_what():
    rows = _window({1: "THE WHOLE PARTY  IS AFFECTED BY:",
                    3: "DETECT MAGIC", 4: "BLESS"},
                   bar="PRESS ANY KEY TO CONTINUE")
    page = A.camp_list_page(rows)
    assert page == A.CampPage("THE WHOLE PARTY", ["DETECT MAGIC", "BLESS"], True)


def test_a_curse_list_page_leaves_its_bottom_border_out():
    rows = _window({1: "SHARA IS AFFECTED BY:", 3: "ENLARGE"}, A.CONTINUE)
    rows[23] = "[=;[[[[[[[[&[[[[[;=[[[[[[[[[[;[[[[[[[[&%"
    assert A.camp_list_page(rows) == A.CampPage("SHARA", ["ENLARGE"], True)


def test_an_empty_camp_list_page_lists_nothing():
    rows = _window({1: "MALCYON IS AFFECTED BY:"},
                   bar="PRESS ANY KEY TO CONTINUE")
    assert A.camp_list_page(rows) == A.CampPage("MALCYON", [], True)


def _whom_screen(names=("BRUTUS", "LADY KATHERINE", "MALCYON")) -> list[str]:
    """The whom menu as PORSAVE13's capture draws it: the party panel, from
    column 17 under `NAME  AC HP`, with `THE WHOLE PARTY` and `EXIT` under the
    names and the question on row 24."""
    rows = [" " * 40 for _ in range(24)]

    def put(r, text):
        rows[r] = rows[r][:17] + text.ljust(23)[:23]
    put(2, "NAME            AC HP")
    for i, name in enumerate([*names, "THE WHOLE PARTY", "EXIT"]):
        put(4 + i, name.ljust(17) + ("6 5" if i < len(names) else ""))
    return rows + ["DISPLAY SPELLS ON WHOM?".ljust(40)]


def test_the_whom_menu_is_read_off_the_party_panel():
    rows = _whom_screen()
    assert A.camp_list_page(rows) is None
    assert A.whom_entries(rows) == ["BRUTUS", "LADY KATHERINE", "MALCYON",
                                    "THE WHOLE PARTY"]


def test_the_world_panel_is_not_a_whom_menu():
    rows = _whom_screen()
    rows[24] = WORLD_BAR.ljust(40)
    assert A.whom_entries(rows) == []


PROBE4 = {1: "MALCYON", 3: "EQUIPPED ITEM", 5: " YES CLOAK",
          6: " YES 13 DART", 7: " NO  DAGGER", 8: " EXIT"}


def test_the_item_list_reads_the_pool_capture():
    rows = _window(PROBE4, bar="READY TRADE DROP EXIT")
    entries = A.item_entries(rows)
    assert [(e["readied"], e["text"], e["marked"]) for e in entries] == [
        (True, "CLOAK", False), (True, "13 DART", False),
        (False, "DAGGER", False)]


def test_a_detect_magic_mark_is_read_where_the_game_prints_it():
    rows = _window({**PROBE4, 6: " YES 13 *DART +1"},
                   bar="READY TRADE DROP EXIT")
    entries = A.item_entries(rows)
    assert [e["marked"] for e in entries] == [False, True, False]
    assert entries[1]["text"] == "13 *DART +1"


def test_compare_names_the_rows_that_differ_only_by_the_mark(tmp_path):
    def summary(where, dart):
        rows = _window({**PROBE4, 6: dart}, bar="READY TRADE DROP EXIT")
        where.mkdir()
        (where / "summary.json").write_text(json.dumps({"results": [
            {"step": "items MALCYON", "verb": "items", "who": "MALCYON",
             "entries": A.item_entries(rows)},
            {"step": "camp-list", "verb": "camp-list",
             "lists": {"MALCYON": ["DETECT MAGIC"] if "*" in dart else []}},
        ]}), encoding="utf-8")
        return where
    got = A.compare(summary(tmp_path / "control", " YES 13 DART +1"),
                    summary(tmp_path / "staged", " YES 13 *DART +1"))
    assert got["items"] == [{"who": "MALCYON", "row": 1,
                             "a": "YES 13 DART +1", "b": "YES 13 *DART +1",
                             "only_the_mark": True}]
    assert got["camp_list"] == [{"who": "MALCYON", "only_a": [],
                                 "only_b": ["DETECT MAGIC"]}]


# --- the steps, on a session that serves the screens the game draws ------------

WORLD_BAR = "MOVE VIEW CAST AREA ENCAMP SEARCH LOOK"
CAMP = "ENCAMP:SAVE VIEW MAGIC REST ALTER EXIT"
MAGIC = "CAST MEMORIZE SCRIBE DISPLAY REST EXIT"


class FakeScreen:
    def __init__(self, rows):
        self._rows = rows

    def row(self, r):
        return self._rows[r]

    def text(self):
        return "\n".join(self._rows)


class FakeKeyboard:
    def __init__(self, session):
        self.session = session

    def key(self, name, *timing):
        return self.session._go(("key", name))

    def screenshot(self, path):
        pathlib.Path(path).write_bytes(b"")
        return True


class FakeSession:
    """The screens `CAMP $16C3` and `LIBRARY $4424` put up, as a state machine
    moved by the keys the driver sends. A key with no transition fails the
    test, so a step that presses anything the game would not take is seen."""

    def __init__(self, screens, moves, start):
        self.screens, self.moves, self.state = screens, moves, start
        self.kbd = FakeKeyboard(self)
        self.sent = []
        self.here = "/slot"
        self.attaches = []
        self.prompts_handled = 0

    def walk_stop(self, s=None, wait=0.0):
        """No stop screen: these fakes never put up a question."""
        return None

    def attach(self, path, unit=8, **kw):
        self.attaches.append(path)
        return True

    def _go(self, what):
        self.sent.append(what)
        key = (self.state, what)
        assert key in self.moves, f"no transition for {key}"
        self.state = self.moves[key]
        return True

    def screen(self):
        return FakeScreen(self.screens[self.state])

    def handle_prompt(self, s=None):
        self.prompts_handled += 1
        return False

    def settle(self, seconds=0):
        pass

    def select_bar(self, label, row=24, timeout=0):
        return self._go(("bar", label))

    def select_row(self, label, timeout=0, column=None):
        return self._go(("row", label))

    def select_party(self, index, timeout=0):
        return self._go(("party", index))

    def press_kernal(self, code):
        return self._go(("key", code))

    def leave_sheet(self):
        return self._go(("leave",))


def test_curse_attack_records_the_named_fighters_row_transition(monkeypatch):
    from types import SimpleNamespace

    row = [[62, 25, 0, 0, 5]]
    actors = [SimpleNamespace(name="SHARA", index=1),
              SimpleNamespace(name="PHILIPPE", index=0)]

    class FightSession:
        def battle(self):
            return object()

        def acting(self, battle):
            return actors.pop(0)

    def strike(sess, state):
        if not actors:
            row.clear()
        return A.S.ATTACK

    monkeypatch.setattr(A.S.Session, "melee_turn", strike)
    run = A.CurseRun.__new__(A.CurseRun)
    run.attack_by = "PHILIPPE"
    run.attack_owner = 0
    run.attack_evidence = None
    run.first_effect_loss = None
    run.last_effect_row = None
    run.reading = lambda: {"effects": row.copy()}
    captures = []
    run.capture = lambda tag: captures.append(tag)
    run.log = SimpleNamespace(emit=lambda *a, **k: None)
    sess = FightSession()
    bar = SimpleNamespace(text="MOVE VIEW AIM USE QUICK DONE")

    assert run._named_melee(sess, bar) == A.S.ATTACK
    assert run.attack_evidence is None
    assert run._named_melee(sess, bar) == A.S.ATTACK
    assert run.attack_evidence == {
        "actor": "PHILIPPE", "index": 0, "owner": 0,
        "bar": bar.text, "chosen": A.S.ATTACK,
        "before": [62, 25, 0, 0, 5], "after": None}
    assert captures.index("attack-before-PHILIPPE") < captures.index(
        "attack-after-PHILIPPE")
    assert captures.count("tactic-before") == captures.count("tactic-after") == 2


@pytest.mark.parametrize("loss_phase", ["route-step", "combat-setup", "tactic-after"])
def test_curse_keeps_the_first_effect_loss_when_no_attack_was_returned(
        monkeypatch, loss_phase):
    from types import SimpleNamespace

    row = [[62, 25, 0, 0, 5]]
    events = []
    actors = iter((SimpleNamespace(name="PHILIPPE", index=0, x=4, y=5, hp=33),
                   SimpleNamespace(name="PHILIPPE", index=0, x=5, y=5, hp=33),
                   SimpleNamespace(name="SHARA", index=1, x=6, y=5, hp=20),
                   SimpleNamespace(name="PHILIPPE", index=0, x=5, y=5, hp=28)))
    answers = iter(("MOVE", "GUARD", "QUIT", A.S.ATTACK))

    class FightSession:
        combat = False

        def battle(self):
            return object()

        def acting(self, battle):
            return next(actors)

        def mode(self):
            return 2 if self.combat else 1

    def choose(*args):
        answer = next(answers)
        if answer == "QUIT" and loss_phase == "tactic-after":
            row.clear()
        return answer

    monkeypatch.setattr(A.S.Session, "melee_turn", choose)
    run = A.CurseRun.__new__(A.CurseRun)
    run.sess = FightSession()
    run.attack_by = "PHILIPPE"
    run.attack_owner = 0
    run.attack_evidence = None
    run.first_effect_loss = None
    run.last_effect_row = None
    run.reading = lambda: {"effects": [r.copy() for r in row], "clock": [0] * 6}
    run.capture = lambda tag: [tag]
    run.log = SimpleNamespace(emit=lambda kind, **kw: events.append((kind, kw)))
    if loss_phase == "route-step":
        run.observe_curse("route-before")
        row.clear()
        run.observe_curse("route-step")
        row.append([62, 25, 0, 0, 5])
    elif loss_phase == "combat-setup":
        run.observe_curse("route-after")
        row.clear()
        run.observe_curse("combat-setup")
        row.append([62, 25, 0, 0, 5])

    run.sess.combat = True
    bar = SimpleNamespace(text="MOVE VIEW AIM QUICK DONE")
    assert run._named_melee(run.sess, bar) == "MOVE"
    assert run._named_melee(run.sess, bar) == "GUARD"
    assert run._named_melee(run.sess, bar) == "QUIT"
    assert run._named_melee(run.sess, bar) == A.S.ATTACK
    observed = [kw for kind, kw in events if kind == "curse-observation"]
    assert [kw["chosen"] for kw in observed if "chosen" in kw] == [
        "MOVE", "GUARD", "QUIT", A.S.ATTACK]
    assert any((kw.get("actor") or {}).get("name") == "SHARA" for kw in observed)
    assert run.first_effect_loss["phase"] == loss_phase
    assert any(kw.get("first_effect_loss") == run.first_effect_loss
               for kw in observed)
    assert run.attack_evidence is None


def test_curse_quit_control_uses_only_done_and_quit():
    from types import SimpleNamespace

    sent = []

    class Session:
        def combat_bar(self, word, timeout):
            sent.append(word)
            return True

        def await_bar(self, kinds, timeout):
            assert kinds == (A.S.BAR_DONE,)
            return object()

        def combat_state(self):
            return SimpleNamespace(text="GUARD DELAY QUIT SPEED EXIT")

    assert A.CurseRun._quit_turn(Session()) == "QUIT"
    assert sent == ["DONE", "QUIT"]


def test_curse_plain_fight_keeps_plain_route_and_tactic(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from tools.c64 import laterbattle
    from tools.curse_of_the_azure_bonds import cursethac0

    calls = []

    class Route:
        last_goto_steps = 3

        def __init__(self, out, quiet):
            self.file = SimpleNamespace(close=lambda: None)
            calls.append("plain-route")

        def goto(self, target, steps, geo):
            return True

    class Session:
        def in_combat(self):
            return True

        def await_bar(self, kinds, timeout, interval):
            calls.append("optional-command-wait")
            return None

        def fight(self, *, budget, tactic):
            calls.append(("fight", tactic))
            return A.S.FightResult("ended", 1, 1.0, [], [])

    monkeypatch.setattr(laterbattle, "Battle", Route)
    monkeypatch.setattr(cursethac0, "area_geo", lambda *a: ("GEO01", object()))
    run = A.CurseRun.__new__(A.CurseRun)
    run.attack_by = ""
    run.attack_owner = None
    run.attack_evidence = None
    run.quit_evidence = None
    run.sess = Session()
    run.out = tmp_path
    run.staged_disk = tmp_path / "staged.D64"
    run.disks = "unused"
    run.to_world = lambda: True
    run.await_combat = lambda: True
    run.capture = lambda tag: calls.append(tag)
    run.observe_curse = lambda *a, **k: pytest.fail("diagnostic observation")
    got = run.fight("10", "I", 5)
    assert got["walked"] == 3
    assert calls[0] == "plain-route"
    assert calls[-3] == "optional-command-wait"
    assert calls[-2] == ("fight", A.S.Session.melee_turn)


def test_curse_fight_fails_through_capture_when_the_route_square_never_settles(
        monkeypatch, tmp_path):
    from types import SimpleNamespace

    from tools.c64 import laterbattle
    from tools.curse_of_the_azure_bonds import cursethac0

    class Route:
        last_goto_steps = 0

        def __init__(self, out, quiet):
            self.file = SimpleNamespace(close=lambda: None)

        def goto(self, target, steps, geo):
            raise cursethac0.Unsettled("the party's square did not settle")

    monkeypatch.setattr(laterbattle, "Battle", Route)
    monkeypatch.setattr(cursethac0, "area_geo", lambda *a: ("GEO01", object()))
    captured = []
    run = A.CurseRun.__new__(A.CurseRun)
    run.attack_by = ""
    run.attack_owner = None
    run.sess = SimpleNamespace()
    run.out = tmp_path
    run.staged_disk = tmp_path / "staged.D64"
    run.disks = "unused"
    run.to_world = lambda: True
    run.spent = lambda: False
    run.capture = captured.append
    with pytest.raises(A.StepFailed, match="the party's square did not settle"):
        run.fight("10", "I", 5)
    assert captured == ["lost-square"]


@pytest.mark.parametrize("advance", ["rejected", "actor", "combat-ended"])
def test_curse_quit_requires_turn_advancement(advance):
    from types import SimpleNamespace

    philippe = SimpleNamespace(name="PHILIPPE", index=0, x=5, y=5, hp=33)
    shara = SimpleNamespace(name="SHARA", index=1, x=6, y=5, hp=20)
    events = []

    class Session:
        calls = 0

        def battle(self):
            return object()

        def acting(self, battle):
            self.calls += 1
            return shara if advance == "actor" and self.calls > 1 else philippe

        def mode(self):
            return 1 if advance == "combat-ended" and self.calls > 0 else 2

        def combat_state(self):
            return SimpleNamespace(text="MOVE VIEW AIM QUICK DONE")

        def settle(self, seconds):
            pass

    run = A.CurseRun.__new__(A.CurseRun)
    run.sess = Session()
    run.attack_by = "PHILIPPE"
    run.attack_owner = 0
    run.attack_evidence = None
    run.quit_evidence = None
    run.quit_nonattacking = True
    run.first_effect_loss = None
    run._quit_turn = lambda sess: "QUIT"
    run.capture = lambda tag: []
    run.observe_curse = lambda phase, **kw: (
        events.append((phase, kw)) or {"row": [62, 25, 0, 0, 5]})
    run.log = SimpleNamespace(emit=lambda *a, **k: None)
    assert run._named_melee(run.sess, SimpleNamespace(text="MOVE VIEW AIM")) == "QUIT"
    if advance != "rejected":
        assert run.quit_evidence["advanced_to"] == (
            "SHARA" if advance == "actor" else "combat-ended")
        assert run.quit_evidence["persisted"] is True
        assert any(phase == "quit-confirmed" for phase, _ in events)
    else:
        assert run.quit_evidence is None
        assert sum(phase == "quit-await" for phase, _ in events) == 8


def test_curse_one_step_skips_wall_edge_and_occupant_and_checks_landing():
    from types import SimpleNamespace

    actor = SimpleNamespace(name="PHILIPPE", index=0, x=5, y=5, hp=33)
    other = SimpleNamespace(name="SHARA", index=1, x=5, y=6, hp=20)
    picked = []

    class Battle:
        shape = SimpleNamespace(holds=lambda x, y: x >= 5 and y >= 5)
        combatants = (actor, other)

        @staticmethod
        def square(x, y):
            return 1 if (x, y) == (6, 5) else 0

        @staticmethod
        def at(x, y):
            return other if (x, y) == (5, 6) else None

    class Session:
        kbd = SimpleNamespace(key=lambda key, *args: picked.append(key))

        def battle(self):
            return Battle()

        def acting(self, battle):
            return actor

        def combat_bar(self, word, timeout):
            return True

        def await_bar(self, kinds, timeout):
            return object()

        def settle(self, seconds):
            pass

    run = A.CurseRun.__new__(A.CurseRun)
    run.sess = Session()
    run.observe_curse = lambda phase, **kw: {}
    with pytest.raises(A.StepFailed, match="did not reach"):
        run.probe_one_step()
    assert picked == ["KP_3"]  # The only open, unoccupied in-bounds square.


def test_curse_missing_first_command_bar_keeps_screen_and_fails():
    class Session:
        def await_bar(self, kinds, timeout, interval):
            return None

    run = A.CurseRun.__new__(A.CurseRun)
    run.sess = Session()
    captures = []
    run.capture = lambda tag: captures.append(tag)
    with pytest.raises(A.StepFailed, match="first command bar"):
        run.first_command_bar()
    assert captures == ["lost-first-command-bar"]


def test_curse_observes_done_branch_outside_tactic_and_restores_end_turn():
    from types import SimpleNamespace

    row = [[62, 25, 0, 0, 5]]
    events = []

    class Session(A.S.Session):
        done = False

        def in_combat(self):
            return True

        def mode(self):
            return 2

        def screen(self):
            return SimpleNamespace(text=lambda: "GUARD DELAY QUIT",
                                   row=lambda n: "GUARD DELAY QUIT",
                                   colours=bytes(1000), codes=bytes(1000))

        def combat_state(self, screen=None):
            return A.S.CombatBar(A.S.BAR_DONE if not self.done else "idle",
                                 "GUARD DELAY QUIT")

        def handle_prompt(self, screen=None):
            pass

        def idle(self, seconds):
            import time
            time.sleep(0.03)

        def battle(self):
            return object()

        def mon(self, timeout):
            class Monitor:
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    pass

                def read(self, address, length):
                    return bytes(length)

                def resume(self):
                    pass

            return Monitor()

        def acting(self, battle):
            return SimpleNamespace(name="PHILIPPE", index=0, x=5, y=5, hp=33)

        def end_turn(self):
            row.clear()
            self.done = True
            return "GUARD"

    sess = Session.__new__(Session)
    run = A.CurseRun.__new__(A.CurseRun)
    run.sess = sess
    run.attack_owner = 0
    run.first_effect_loss = None
    run.last_effect_row = None
    run.reading = lambda: {"effects": [r.copy() for r in row], "clock": [0] * 6}
    run.capture = lambda tag: [tag]
    run.log = SimpleNamespace(emit=lambda kind, **kw: events.append((kind, kw)))
    result = run.observed_fight(0.02)
    assert result.blows == 0
    assert "end_turn" not in vars(sess)
    observed = [kw for kind, kw in events if kind == "curse-observation"]
    assert [kw["phase"] for kw in observed] == ["done-before", "done-after"]
    assert observed[-1]["chosen"] == "GUARD"
    assert run.first_effect_loss["phase"] == "done-after"


def test_curse_quit_control_validates_persistence_without_an_attack():
    row = [62, 25, 0, 0, 5]
    quit_evidence = {"actor": "PHILIPPE", "chosen": "QUIT",
                     "before": row, "after": row, "advanced_to": "SHARA"}
    A.validate_curse_quit(quit_evidence, "PHILIPPE")
    with pytest.raises(A.StepFailed, match="no confirmed QUIT"):
        A.validate_curse_quit(None, "PHILIPPE")
    with pytest.raises(A.StepFailed, match="no confirmed QUIT"):
        A.validate_curse_quit({**quit_evidence, "advanced_to": None}, "PHILIPPE")
    with pytest.raises(A.StepFailed, match="absent after"):
        A.validate_curse_quit({**quit_evidence, "after": None}, "PHILIPPE")


def test_curse_quit_control_completes_without_named_attack(tmp_path, monkeypatch):
    import contextlib
    from types import SimpleNamespace

    from tools.curse_of_the_azure_bonds import curserun

    source = _fixture_disk(tmp_path)
    slot = _Slot(tmp_path)
    monkeypatch.setattr(A.runlog, "catch_signals", lambda: None)
    monkeypatch.setattr(A.S, "claim_slot", lambda *a, **k: slot)
    monkeypatch.setattr(A, "stage", lambda *a, **k: {"effects": [],
                                                    "magic_items": []})
    monkeypatch.setattr(curserun, "stage", lambda *a, **k: "first")

    class Session:
        save_disk = "disk"

        def __init__(self, *a, **k):
            pass

        def watching_dialogs(self):
            return contextlib.nullcontext()

        def terminate(self):
            pass

    monkeypatch.setattr(curserun, "CurseSession", Session)

    class Run:
        attack_evidence = None
        quit_evidence = {"actor": "PHILIPPE", "chosen": "QUIT",
                         "before": [62, 25, 0, 0, 5],
                         "after": [62, 25, 0, 0, 5], "persisted": True,
                         "advanced_to": "SHARA"}
        first_effect_loss = None

        def __init__(self, *args):
            pass

        def load(self):
            return {}

        def fight(self, *args):
            return {"named_attack": None, "named_quit": self.quit_evidence}

        def reading(self):
            return {"effects": [[62, 25, 0, 0, 5]]}

        def capture(self, tag):
            pass

    monkeypatch.setattr(A, "CurseRun", Run)
    args = SimpleNamespace(title="curse", max_seconds=120, stage_row=[],
                           stage_trait=[], stage_item=[], stage_only=False,
                           checkpoint=[], pool=None, issue="671", run="fake-quit",
                           disks="unused", attack_by="PHILIPPE", walk="I",
                           walk_steps=60, quit_nonattacking=True, probe_step=False)
    out = tmp_path / "evidence"
    assert A.run(args, A.parse_steps(["load", "fight 30"]), out, source) == 0
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["completed"] is True
    assert summary["named_attack"] is None
    assert summary["named_quit"]["persisted"] is True


@pytest.mark.parametrize("before,after,saved,expected", [
    ([], [], [], 1),
    (["INVISIBILITY"], ["INVISIBILITY"], [], 1),
    (["INVISIBILITY"], [], [[62, 25, 0, 0, 5]], 1),
    (["INVISIBILITY"], [], [], 0),
])
def test_curse_attack_needs_both_status_lists_and_the_engine_save(
        tmp_path, monkeypatch, before, after, saved, expected):
    import contextlib
    from types import SimpleNamespace

    from tools.curse_of_the_azure_bonds import curserun

    source = _fixture_disk(tmp_path)
    slot = _Slot(tmp_path)
    monkeypatch.setattr(A.runlog, "catch_signals", lambda: None)
    monkeypatch.setattr(A.S, "claim_slot", lambda *a, **k: slot)
    monkeypatch.setattr(A, "stage", lambda *a, **k: {"effects": [],
                                                    "magic_items": []})
    monkeypatch.setattr(curserun, "stage", lambda *a, **k: "first")

    class Session:
        save_disk = "disk"

        def __init__(self, *a, **k):
            pass

        def watching_dialogs(self):
            return contextlib.nullcontext()

        def terminate(self):
            pass

    monkeypatch.setattr(curserun, "CurseSession", Session)

    class Run:
        attack_evidence = {"actor": "PHILIPPE", "index": 0, "owner": 0,
                           "chosen": A.S.ATTACK, "before": [62, 25, 0, 0, 5],
                           "after": None}

        def __init__(self, *a, **k):
            self.lists = iter((before, after))

        def load(self):
            return {}

        def camp_list(self, who):
            return {"lists": {who: next(self.lists)}}

        def fight(self, *a):
            return {"named_attack": self.attack_evidence}

        def save(self, staged):
            return {"effects": saved, "kept": "saved.D64"}

        def reading(self):
            return {"effects": []}

        def capture(self, tag):
            pass

    monkeypatch.setattr(A, "CurseRun", Run)
    args = SimpleNamespace(title="curse", max_seconds=120, stage_row=[],
                           stage_trait=[], stage_item=[], stage_only=False,
                           checkpoint=[], pool=None, issue="671", run="fake",
                           disks="unused", attack_by="PHILIPPE", walk="I",
                           walk_steps=60)
    out = tmp_path / "evidence"
    rc = A.run(args, A.parse_steps(["load", "camp-list PHILIPPE", "fight 600",
                                    "camp-list PHILIPPE", "save"]), out, source)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert rc == expected and summary["completed"] is (expected == 0)
    assert ("lost" in summary) is (expected == 1)


def test_curse_unreadable_brawl_acknowledgement_is_answered_once():
    class Session:
        def __init__(self):
            self.keys = []
            self.looks = 0

        def in_combat(self):
            return bool(self.keys)

        def screen(self):
            self.looks += 1
            return None

        def press_kernal(self, code):
            self.keys.append(code)

        def settle(self, seconds):
            pass

    run = A.CurseRun.__new__(A.CurseRun)
    run.sess = Session()
    run.capture = lambda tag: None
    assert run.await_combat() is True
    assert run.sess.keys == [0x0D]
    assert run.sess.looks == 1


def _pool_run(tmp_path, sess):
    log = A.Log(tmp_path)
    return A.PoolRun(sess, log, tmp_path, POOL_OF_RADIANCE, {}), log


def test_camp_list_reads_every_name_page_by_page_and_goes_back_to_the_world(tmp_path):
    whom = _whom_screen(("MALCYON",))
    screens = {
        "world": _window({}, WORLD_BAR), "camp": _window({}, CAMP),
        "magic": _window({}, MAGIC), "whom": whom,
        "on-m": whom, "on-p": whom, "on-x": whom,
        "m": _window({1: "MALCYON IS AFFECTED BY:", 3: "DETECT MAGIC"}, A.CONTINUE),
        "p1": _window({1: "THE WHOLE PARTY  IS AFFECTED BY:", 3: "DETECT MAGIC",
                       4: "BLESS"}, A.CONTINUE),
        "p2": _window({1: "THE WHOLE PARTY  IS AFFECTED BY:", 3: "PRAYER"},
                      A.CONTINUE),
    }
    moves = {
        ("world", ("bar", "ENCAMP")): "camp", ("camp", ("bar", "MAGIC")): "magic",
        ("magic", ("bar", "DISPLAY")): "whom",
        ("whom", ("party", 0)): "on-m", ("on-m", ("key", "Return")): "m",
        ("m", ("key", 0x0D)): "whom",
        ("whom", ("party", 1)): "on-p", ("on-p", ("key", "Return")): "p1",
        ("p1", ("key", 0x0D)): "p2", ("p2", ("key", 0x0D)): "whom",
        ("whom", ("party", 2)): "on-x", ("on-x", ("key", "Return")): "magic",
        ("magic", ("bar", "EXIT")): "camp",
        ("camp", ("bar", "EXIT")): "world",
    }
    sess = FakeSession(screens, moves, "world")
    run, log = _pool_run(tmp_path, sess)
    got = run.camp_list("")
    log.close()
    assert got == {"offered": ["MALCYON", "THE WHOLE PARTY"],
                   "lists": {"MALCYON": ["DETECT MAGIC"],
                             "THE WHOLE PARTY": ["DETECT MAGIC", "BLESS", "PRAYER"]}}
    assert sess.state == "world"
    assert len(list(tmp_path.glob("*-camp-list-*.txt"))) == 3


@pytest.mark.parametrize("exit_result", ["magic", "whom", "unknown"])
def test_curse_camp_list_exits_whom_and_reaches_world_or_fails(
        tmp_path, exit_result):
    whom = _whom_screen(("PHILIPPE",))
    screens = {
        "world": _window({}, WORLD_BAR), "camp": _window({}, CAMP),
        "magic": _window({}, MAGIC), "whom": whom, "on-p": whom,
        "on-x": whom, "unknown": _window({}, "UNKNOWN EXIT MENU"),
        "p": _window({1: "PHILIPPE IS AFFECTED BY:", 3: "INVISIBILITY"},
                     A.CONTINUE),
    }
    moves = {
        ("world", ("bar", "ENCAMP")): "camp",
        ("camp", ("bar", "MAGIC")): "magic",
        ("magic", ("bar", "DISPLAY")): "whom",
        ("whom", ("party", 0)): "on-p",
        ("on-p", ("key", "Return")): "p",
        ("p", ("key", 0x0D)): "whom",
        ("whom", ("party", 2)): "on-x",
        ("on-x", ("key", "Return")): exit_result,
        ("magic", ("bar", "EXIT")): "camp",
        ("camp", ("bar", "EXIT")): "world",
    }

    class CurseSession(FakeSession):
        def press_bar(self, label, row=24, timeout=0):
            return self._go(("bar", label))

        def to_world_bar(self, timeout=0):
            return self.state == "world"

    sess = CurseSession(screens, moves, "world")
    run = A.CurseRun.__new__(A.CurseRun)
    run.sess = sess
    run.out = tmp_path
    run.log = A.Log(tmp_path)
    run.shots = 0
    try:
        if exit_result == "magic":
            got = run.camp_list("PHILIPPE")
            assert got["lists"] == {"PHILIPPE": ["INVISIBILITY"]}
            assert sess.state == "world"
            assert sess.sent[-4:] == [
                ("party", 2), ("key", "Return"),
                ("bar", "EXIT"), ("bar", "EXIT"),
            ]
            route = sorted(tmp_path.glob("*-exit-*.txt"))
            assert [p.name.split("-", 1)[1] for p in route] == [
                "exit-whom.txt", "exit-magic.txt", "exit-camp.txt"]
            assert [p.read_text(encoding="utf-8").splitlines()[-1].strip()
                    for p in route] == [MAGIC, CAMP, WORLD_BAR]
        else:
            with pytest.raises(A.StepFailed, match="world bar never came back"):
                run.camp_list("PHILIPPE")
            assert sess.state == exit_result
            if exit_result == "unknown":
                assert sess.sent[-2:] == [("party", 2), ("key", "Return")]
                assert any("UNKNOWN EXIT MENU" in p.read_text(encoding="utf-8")
                           for p in tmp_path.glob("*lost-world-route.txt"))
    finally:
        run.log.close()


class _CurseCampFake(FakeSession):
    """Curse's camp: DISPLAY first puts up the list of the member under the
    panel highlight, and a key on its last page brings up the whom menu."""

    def press_bar(self, label, row=24, timeout=0):
        return self._go(("bar", label))

    def to_world_bar(self, timeout=0):
        return self.state == "world"


CURSE_PANEL = ("MATHEW", "MARK", "TRAVIS", "LEDERA", "SHARA", "PHILIPPE")


def _curse_page(lines):
    """A Curse list page, whose window border on rows 0 and 23 is a mixed
    run of glyphs rather than one repeated."""
    rows = _window(lines, A.CONTINUE)
    rows[0] = "@;[[[[[[;[[[[&[[[;[[[[[[[=[[[[[[[&[[[;[$"
    rows[23] = "[=;[[[[[[[[&[[[[[;=[[[[[[[[[[;[[[[[[[[&%"
    return rows


def _curse_camp_list(tmp_path, first_pages, who):
    """DISPLAY's first list as FIRST_PAGES, then the whom menu, where MATHEW
    and SHARA each have one page; returns the result, the session and the
    events logged."""
    whom = _whom_screen(CURSE_PANEL)
    screens = {"world": _window({}, WORLD_BAR), "camp": _window({}, CAMP),
               "magic": _window({}, MAGIC), "whom": whom,
               "on-m": whom, "on-s": whom, "on-x": whom,
               "m": _curse_page({1: "MATHEW IS AFFECTED BY:", 3: "HASTE",
                                 4: "PROTECTION FROM EVIL"}),
               "s": _curse_page({1: "SHARA IS AFFECTED BY:", 3: "ENLARGE"})}
    moves = {("world", ("bar", "ENCAMP")): "camp", ("camp", ("bar", "MAGIC")): "magic",
             ("magic", ("bar", "DISPLAY")): "first-1",
             ("whom", ("party", 0)): "on-m", ("on-m", ("key", "Return")): "m",
             ("m", ("key", 0x0D)): "whom",
             ("whom", ("party", 4)): "on-s", ("on-s", ("key", "Return")): "s",
             ("s", ("key", 0x0D)): "whom",
             ("whom", ("party", 7)): "on-x", ("on-x", ("key", "Return")): "magic",
             ("magic", ("bar", "EXIT")): "camp", ("camp", ("bar", "EXIT")): "world"}
    for n, page in enumerate(first_pages, 1):
        screens[f"first-{n}"] = page
        moves[(f"first-{n}", ("key", 0x0D))] = (
            f"first-{n + 1}" if n < len(first_pages) else "whom")
    sess = _CurseCampFake(screens, moves, "world")
    run = A.CurseRun.__new__(A.CurseRun)
    run.sess, run.out, run.shots = sess, tmp_path, 0
    run.log = A.Log(tmp_path)
    try:
        got = run.camp_list(who)
    finally:
        run.log.close()
    events = [json.loads(line) for line in
              (tmp_path / "run.jsonl").read_text(encoding="utf-8").splitlines()]
    return got, sess, events


def test_curse_camp_list_reads_the_highlighted_list_then_the_whom_menu(tmp_path):
    first = _curse_page({1: "MATHEW IS AFFECTED BY:", 3: "HASTE",
                         4: "PROTECTION FROM EVIL"})
    got, sess, events = _curse_camp_list(tmp_path, [first], "MATHEW,SHARA")
    assert got == {"offered": [*CURSE_PANEL, "THE WHOLE PARTY"],
                   "lists": {"MATHEW": ["HASTE", "PROTECTION FROM EVIL"],
                             "SHARA": ["ENLARGE"]}}
    assert sess.state == "world"
    assert sess.sent[:4] == [("bar", "ENCAMP"), ("bar", "MAGIC"),
                             ("bar", "DISPLAY"), ("key", 0x0D)]
    assert [(e["who"], e["spells"]) for e in events
            if e["kind"] == "camp-list-highlighted"] == [
        ("MATHEW", ["HASTE", "PROTECTION FROM EVIL"])]


def test_curse_camp_list_pages_the_highlighted_list_to_its_end(tmp_path):
    pages = [_curse_page({1: "TRAVIS IS AFFECTED BY:", 3: "BLESS"}),
             _curse_page({1: "TRAVIS IS AFFECTED BY:", 3: "INVISIBILITY"})]
    got, sess, events = _curse_camp_list(tmp_path, pages, "SHARA")
    assert got["lists"] == {"SHARA": ["ENLARGE"]}
    assert sess.sent[3:5] == [("key", 0x0D), ("key", 0x0D)]
    assert [(e["who"], e["spells"]) for e in events
            if e["kind"] == "camp-list-highlighted"] == [
        ("TRAVIS", ["BLESS", "INVISIBILITY"])]


def test_curse_camp_list_fails_when_display_puts_up_neither_screen(tmp_path, monkeypatch):
    screens = {"world": _window({}, WORLD_BAR), "camp": _window({}, CAMP),
               "magic": _window({}, MAGIC), "other": _window({}, "SOMETHING ELSE")}
    moves = {("world", ("bar", "ENCAMP")): "camp", ("camp", ("bar", "MAGIC")): "magic",
             ("magic", ("bar", "DISPLAY")): "other"}
    sess = _CurseCampFake(screens, moves, "world")
    run = A.CurseRun.__new__(A.CurseRun)
    run.sess, run.out, run.shots = sess, tmp_path, 0
    run.log = A.Log(tmp_path)
    monkeypatch.setattr(A.time, "sleep", lambda s: None)
    ticks = iter(range(0, 10_000))
    run.clock = lambda: next(ticks)
    try:
        with pytest.raises(A.StepFailed,
                           match="DISPLAY put up neither a whom menu nor a list"):
            run.camp_list("MATHEW")
    finally:
        run.log.close()
    assert sess.state == "other"


def test_items_reads_the_list_of_the_member_asked_for_and_leaves_it(tmp_path):
    screens = {
        "world": _window({}, WORLD_BAR),
        "sheet": _window({1: "LADY KATHERINE"}, "VIEW:ITEMS SPELLS TRADE DROP EXIT"),
        "items": _window({**PROBE4, 1: "LADY KATHERINE", 6: " YES 13 *DART"},
                         "READY TRADE DROP EXIT"),
    }
    moves = {
        ("world", ("party", 1)): "world", ("world", ("bar", "VIEW")): "sheet",
        ("sheet", ("bar", "ITEMS")): "items", ("items", ("bar", "EXIT")): "sheet",
        ("sheet", ("leave",)): "world",
    }
    sess = FakeSession(screens, moves, "world")
    run, log = _pool_run(tmp_path, sess)
    got = run.items("2")
    log.close()
    assert got["marked"] == ["YES 13 *DART"]
    assert [e["row"] for e in got["entries"]] == ["YES CLOAK", "YES 13 *DART",
                                                  "NO  DAGGER"]
    assert sess.state == "world"


def test_open_sheet_answers_a_portrait_disk_prompt_with_side_3_not_the_side_it_names(
        tmp_path):
    """The sheet's own portrait load asks for the *area's* side (`#694`),
    which is the side already in the drive when the character's art is not
    on it -- so answering as asked loops forever. `open_sheet` must attach
    `SIDE3.D64` instead, and must not call `handle_prompt` for that prompt."""
    screens = {
        "world": _window({}, WORLD_BAR),
        "prompt": _window({}, "INSERT SIDE # 2, AND PRESS ANY KEY."),
        "sheet": _window({1: "BAKSHI"}, "VIEW:ITEMS SPELLS TRADE DROP EXIT"),
    }
    moves = {
        ("world", ("party", 0)): "world", ("world", ("bar", "VIEW")): "prompt",
        ("prompt", ("key", "space")): "sheet",
    }
    sess = FakeSession(screens, moves, "world")
    run, log = _pool_run(tmp_path, sess)
    got = run.open_sheet("1")
    log.close()
    assert sess.attaches == [os.path.join(sess.here, "SIDE3.D64")]
    assert sess.prompts_handled == 0
    assert any("BAKSHI" in r for r in got)


def test_side_3_carries_every_portrait_the_creation_menu_can_choose():
    """Answering a sheet's portrait prompt with side 3 is a complete fix and
    not a special case for BAKSHI's `HEAD35`/`BODY07`: `POOL3.D64` carries a
    `HEAD<xx>`/`BODY<xx>` file for every one of the fourteen heads and twelve
    bodies the creation menu offers (`#694`)."""
    from goldbox.portraits import POOL_OF_RADIANCE_MENU

    path = gamedata.game_disk("POOL3")
    image = D64(path.read_bytes())
    names = {entry.name.decode("latin1") for entry in image.directory()}
    for head in POOL_OF_RADIANCE_MENU.heads:
        assert f"HEAD{head:02X}" in names
    for body in POOL_OF_RADIANCE_MENU.bodies:
        assert f"BODY{body:02X}" in names


# --- the run's deadline and clean-up -------------------------------------------

class _Slot:
    n, display = 1, ":99"

    def __init__(self, dir_):
        self.dir = dir_
        self.torn = False

    def teardown(self):
        self.torn = True


class _Sess:
    def __init__(self, *a, **k):
        self.save_disk = "x"
        self.kbd = SimpleNamespace(key=lambda *a, **k: None,
                                   text=lambda *a, **k: None)

    def press_kernal(self, code):
        pass

    def handle_prompt(self, screen=None):
        return False

    def watching_dialogs(self):
        import contextlib
        return contextlib.nullcontext()

    fail_terminate = False

    def terminate(self):
        if _Sess.fail_terminate:
            raise RuntimeError("terminate failed")


class _Pool:
    def __init__(self, *a, **k):
        self.ticks = k.get("ticks")

    def load(self):
        return {}

    def peek(self, arg):
        _Pool.clock[0] += 100
        return {}

    def reading(self):
        return {}

    def capture(self, *a):
        pass


def _drive(tmp_path, monkeypatch, steps, max_seconds=150.0, claim=None, slot=None,
           pool=_Pool, title="pool", catch=lambda: None, stage_only=False,
           capture_ready=False, preserve_specimen=False, read_at=()):
    import types
    slot = slot or _Slot(tmp_path)
    _Pool.clock = [0.0]
    monkeypatch.setattr(A.runlog, "catch_signals", catch)
    monkeypatch.setattr(A.S, "claim_slot", claim or (lambda *a, **k: slot))
    monkeypatch.setattr(A.S, "stage_disks", lambda *a, **k: "first")
    monkeypatch.setattr(A.S, "stage_writable",
                        lambda src, dest: __import__("shutil").copyfile(src, dest))
    monkeypatch.setattr(A.S, "Session", _Sess)
    monkeypatch.setattr(A, "PoolRun", pool)
    args = types.SimpleNamespace(
        title=title, stage_row=[], stage_trait=[], stage_item=[],
        stage_only=stage_only, checkpoint=[], pool=None,
        issue="703" if capture_ready else "700" if preserve_specimen else "i",
        run="r", disks=None,
        walk="I", walk_steps=1, max_seconds=max_seconds,
        capture_ready=capture_ready, preserve_specimen=preserve_specimen,
        read_at=list(read_at))
    out = tmp_path / "out"
    rc = A.run(args, A.parse_steps(steps), out, _fixture_disk(tmp_path),
               clock=lambda: _Pool.clock[0])
    return rc, slot, out


def test_temple_probe_run_records_hashes_checkpoints_and_cleanup(
        tmp_path, monkeypatch):
    class Probe(_Pool):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.temple_checkpoints = [{"tag": "heal-services"}]

        def temple_probe(self, who):
            assert who == "BRUTUS"
            assert self.temple_input_deadline == 1400
            return {"resident": {"slot": 5, "name": "BRUTUS"}}

    monkeypatch.setattr(A, "temple_source_guard", lambda source: A.TEMPLE_BRUTUS_SHA256)
    rc, slot, out = _drive(tmp_path, monkeypatch,
                           ["load", "temple-probe BRUTUS"],
                           max_seconds=1500, pool=Probe)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert rc == 0 and slot.torn and summary["completed"]
    assert summary["source_sha256"] == summary["staged_sha256"]
    assert summary["temple_checkpoints"] == [{"tag": "heal-services"}]
    assert summary["results"][-1]["resident"] == {"slot": 5, "name": "BRUTUS"}
    assert summary["cleanup"] == {"watchers": "closed", "session": "terminated",
                                  "slot": "released"}


@pytest.mark.parametrize("broken", ["restore", "watchers"])
def test_temple_cleanup_still_terminates_session_after_earlier_error(
        tmp_path, monkeypatch, broken):
    import contextlib

    class Probe(_Pool):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.temple_checkpoints = []

        def temple_probe(self, who):
            return {}

    terminated = []
    monkeypatch.setattr(_Sess, "terminate", lambda self: terminated.append(True))
    if broken == "restore":
        def bad_guard(*args):
            def restore():
                raise RuntimeError("restore failed")
            return restore
        monkeypatch.setattr(A, "guard_temple_input", bad_guard)
    else:
        @contextlib.contextmanager
        def bad_watcher(self):
            yield
            raise RuntimeError("watchers failed")
        monkeypatch.setattr(_Sess, "watching_dialogs", bad_watcher)
    monkeypatch.setattr(A, "temple_source_guard", lambda source: A.TEMPLE_BRUTUS_SHA256)
    slot = _Slot(tmp_path)
    with pytest.raises(RuntimeError, match="restore failed|watchers failed"):
        _drive(tmp_path, monkeypatch, ["load", "temple-probe BRUTUS"],
               max_seconds=1500, pool=Probe, slot=slot)
    summary = json.loads((tmp_path / "out" / "summary.json").read_text(
        encoding="utf-8"))
    assert terminated == [True] and slot.torn
    assert summary["cleanup"]["session"] == "terminated"
    assert summary["cleanup"]["slot"] == "released"
    assert ("restore_input_error" if broken == "restore"
            else "watchers_error") in summary["cleanup"]


def test_a_run_past_its_deadline_is_lost_and_releases_the_slot(tmp_path, monkeypatch):
    rc, slot, out = _drive(tmp_path, monkeypatch,
                           ["load", "peek 1000 1", "peek 1000 1", "peek 1000 1"], 150.0)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert rc == 1 and not summary["completed"]
    assert "seconds were spent" in summary["lost"]
    assert len(summary["results"]) == 3
    assert slot.torn


def test_a_failing_terminate_still_releases_the_slot(tmp_path, monkeypatch):
    slot = _Slot(tmp_path)
    monkeypatch.setattr(_Sess, "fail_terminate", True)
    with pytest.raises(RuntimeError, match="terminate failed"):
        _drive(tmp_path, monkeypatch, ["load"], 1e9, slot=slot)
    assert slot.torn


def test_a_failing_claim_closes_the_log(tmp_path, monkeypatch):
    closed = []
    monkeypatch.setattr(A.Log, "close", lambda self: closed.append(True))

    def boom(*a, **k):
        raise RuntimeError("no slot")
    with pytest.raises(RuntimeError, match="no slot"):
        _drive(tmp_path, monkeypatch, ["load"], claim=boom)
    assert closed


def test_capture_ready_registers_and_checks_the_game_written_disk_before_teardown(
        tmp_path, monkeypatch):
    from tools.registry import specimens

    events = []

    class Slot(_Slot):
        def teardown(self):
            events.append("teardown")
            super().teardown()

    class Run(_Pool):
        def ready(self, arg):
            return {"who": "BAKSHI"}

        def save(self, staged):
            (tmp_path / "out" / "saved.D64").write_bytes(b"saved")
            return {"kept": str(tmp_path / "out" / "saved.D64")}

    def add(platform, name, sources, **kw):
        events.append("add")
        assert platform == "c64" and name.startswith("por-703-")
        assert sources == [tmp_path / "out" / "saved.D64"]
        assert kw["title"] == "Pool of Radiance" and "#703 (" in kw["issue"]
        return tmp_path / "registered.D64"

    def check():
        events.append("check")
        return []

    monkeypatch.setattr(specimens, "add", add)
    monkeypatch.setattr(specimens, "check_specimens", check)
    slot = Slot(tmp_path)
    rc, _, out = _drive(tmp_path, monkeypatch,
                         ["load", "ready BAKSHI>LABEL", "save",
                          "ready BAKSHI>LABEL"], pool=Run,
                         slot=slot, capture_ready=True)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert rc == 0 and slot.torn
    assert events == ["add", "check", "teardown"]
    assert summary["registered_specimen"] == str(tmp_path / "registered.D64")


def test_capture_ready_registration_failure_is_recorded_and_still_tears_down(
        tmp_path, monkeypatch):
    from tools.registry import specimens

    class Run(_Pool):
        def ready(self, arg):
            return {"who": "BAKSHI"}

        def save(self, staged):
            (tmp_path / "out" / "saved.D64").write_bytes(b"saved")
            return {"kept": str(tmp_path / "out" / "saved.D64")}

    monkeypatch.setattr(specimens, "add", lambda *a, **k: tmp_path / "registered.D64")
    monkeypatch.setattr(specimens, "check_specimens", lambda: ["hash mismatch"])
    rc, slot, out = _drive(tmp_path, monkeypatch,
                           ["load", "ready BAKSHI>LABEL", "save"], pool=Run,
                           capture_ready=True)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert rc == 1 and slot.torn
    assert "hash mismatch" in summary["lost"]
    assert summary["registered_specimen"] == str(tmp_path / "registered.D64")


def test_ordinary_save_does_not_register_a_diagnostic_specimen(tmp_path, monkeypatch):
    from tools.registry import specimens

    class Run(_Pool):
        def save(self, staged):
            (tmp_path / "out" / "saved.D64").write_bytes(b"saved")
            return {"kept": str(tmp_path / "out" / "saved.D64")}

    monkeypatch.setattr(specimens, "add", lambda *a, **k: pytest.fail("registered"))
    rc, slot, out = _drive(tmp_path, monkeypatch, ["load", "save"], pool=Run)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert rc == 0 and slot.torn and summary["completed"]
    assert "registered_specimen" not in summary


def test_capture_ready_rejects_save_before_first_ready_even_if_ready_follows(
        tmp_path, monkeypatch):
    from tools.registry import specimens

    monkeypatch.setattr(A.S, "claim_slot", lambda *a, **k: pytest.fail("claimed a slot"))
    with pytest.raises(SystemExit) as exc:
        A.main(["--title", "pool", "--save", str(_fixture_disk(tmp_path)),
                "--issue", "703", "--capture-ready", "--steps", "load", "save",
                "ready BAKSHI>LABEL", "--out", str(tmp_path / "reversed")])
    assert exc.value.code == 2
    assert not (tmp_path / "reversed").exists()
    assert A.main(["--title", "pool", "--save", str(_fixture_disk(tmp_path)),
                   "--issue", "703", "--capture-ready", "--stage-only",
                   "--steps", "load", "ready BAKSHI>LABEL", "save",
                   "ready BAKSHI>LABEL", "--out", str(tmp_path / "allowed")]) == 0

    class Run(_Pool):
        def ready(self, arg):
            return {"who": "BAKSHI"}

        def save(self, staged):
            (tmp_path / "out" / "saved.D64").write_bytes(b"saved")
            return {"kept": str(tmp_path / "out" / "saved.D64")}

    monkeypatch.setattr(specimens, "add", lambda *a, **k: pytest.fail("registered"))
    rc, slot, out = _drive(tmp_path, monkeypatch,
                           ["load", "save", "ready BAKSHI>LABEL"], pool=Run,
                           capture_ready=True)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert rc == 1 and slot.torn
    assert "READY" in summary["lost"] and "registered_specimen" not in summary


def _brutus_zombie_state():
    rows = [[n, 0, 0, 0, 0] for n in range(64)]
    rows[63] = [63, 32, 5, 0, 5]
    return {"party": [{"slot": 5, "name": "BRUTUS", "status": 0x03,
                       "traits": [0] * 9 + [32], "creature_type": 4,
                       "hp_current": 8}],
            "effect_rows": rows,
            "record_sha256": ["other"] * 5 + ["brutus-record"] + ["other"] * 2}


class _SpecimenPool(_Pool):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.out = args[2]

    def reading(self):
        return _brutus_zombie_state()

    def view(self, who):
        return {"who": who}

    def cast(self, arg):
        return {"spell": "DISPEL MAGIC", "target": "BRUTUS"}

    def save(self, staged):
        kept = self.out / "saved.D64"
        kept.write_bytes(b"saved")
        return {"kept": str(kept), **_brutus_zombie_state()}


@pytest.mark.parametrize("mode,steps", [
    ("dispel", ["load", "view BRUTUS", "cast ROLAND:DISPEL MAGIC>BRUTUS",
                "view BRUTUS", "save"]),
    ("control", ["load", "view BRUTUS", "save"]),
])
def test_pool_specimen_modes_register_and_check_before_teardown(
        tmp_path, monkeypatch, mode, steps):
    from tools.registry import specimens

    events = []

    class Slot(_Slot):
        def teardown(self):
            events.append("teardown")
            super().teardown()

    def add(platform, name, sources, **kw):
        events.append("add")
        assert platform == "c64" and name.startswith(f"por-700-{mode}-")
        assert sources == [tmp_path / "out" / "saved.D64"]
        assert kw["title"] == "Pool of Radiance" and "#700 (" in kw["issue"]
        assert mode in kw["what"]
        return tmp_path / "registered.D64"

    monkeypatch.setattr(specimens, "add", add)
    monkeypatch.setattr(specimens, "check_specimens",
                        lambda: events.append("check") or [])
    monkeypatch.setattr(A, "validate_pool_dispel", lambda results: None)
    slot = Slot(tmp_path)
    rc, _, out = _drive(tmp_path, monkeypatch, steps, pool=_SpecimenPool, slot=slot,
                         preserve_specimen=True)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert rc == 0 and slot.torn
    assert events == ["add", "check", "teardown"]
    assert summary["specimen_mode"] == mode
    assert summary["specimen_validation"] == "passed"
    assert summary["registered_specimen"] == str(tmp_path / "registered.D64")


def test_pool_specimen_registry_failure_marks_run_lost_and_tears_down(
        tmp_path, monkeypatch):
    from tools.registry import specimens

    monkeypatch.setattr(specimens, "add", lambda *a, **k: tmp_path / "registered.D64")
    monkeypatch.setattr(specimens, "check_specimens", lambda: ["hash mismatch"])
    rc, slot, out = _drive(tmp_path, monkeypatch,
                           ["load", "view BRUTUS", "save"], pool=_SpecimenPool,
                           preserve_specimen=True)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert rc == 1 and slot.torn
    assert summary["specimen_mode"] == "control"
    assert "hash mismatch" in summary["lost"]
    assert summary["registered_specimen"] == str(tmp_path / "registered.D64")


def test_pool_specimen_add_refusal_marks_run_lost_and_tears_down(tmp_path, monkeypatch):
    from tools.registry import specimens

    def refuse(*a, **k):
        raise FileExistsError("specimen name is taken")

    monkeypatch.setattr(specimens, "add", refuse)
    monkeypatch.setattr(specimens, "check_specimens", lambda: pytest.fail("checked"))
    rc, slot, out = _drive(tmp_path, monkeypatch,
                           ["load", "view BRUTUS", "save"], pool=_SpecimenPool,
                           preserve_specimen=True)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert rc == 1 and slot.torn
    assert "specimen name is taken" in summary["lost"]
    assert "registered_specimen" not in summary


@pytest.mark.parametrize("fault", [
    "loaded", "saved", "saved_row", "saved_row_payload", "saved_record",
    "saved_unreported_record",
])
def test_pool_control_rejects_an_unmatched_animated_state(tmp_path, monkeypatch,
                                                           fault):
    from tools.registry import specimens

    class Run(_SpecimenPool):
        def reading(self):
            state = super().reading()
            if fault == "loaded":
                state["effect_rows"][63][1] = 0
            return state

        def save(self, staged):
            saved = super().save(staged)
            if fault == "saved":
                saved["party"][0]["traits"][-1] = 0
            elif fault == "saved_row":
                saved["effect_rows"][63][2] = 3
            elif fault == "saved_row_payload":
                saved["effect_rows"][63][4] = 6
            elif fault == "saved_record":
                saved["party"][0]["hp_current"] = 9
            elif fault == "saved_unreported_record":
                saved["record_sha256"][5] = "different-record"
            return saved

    added = []
    monkeypatch.setattr(specimens, "add", lambda *a, **k: added.append(k)
                        or tmp_path / "registered.D64")
    monkeypatch.setattr(specimens, "check_specimens", lambda: [])
    rc, slot, out = _drive(tmp_path, monkeypatch,
                           ["load", "view BRUTUS", "save"], pool=Run,
                           preserve_specimen=True)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert rc == 1 and slot.torn
    assert "control" in summary["lost"]
    assert summary["specimen_validation"] == "failed"
    assert len(added) == 1 and "validation failed" in added[0]["what"]


def test_pool_dispel_post_save_validation_failure_has_failure_provenance(
        tmp_path, monkeypatch):
    from tools.registry import specimens

    def fail(_results):
        raise A.StepFailed("saved Dispel row was restored")

    added = []
    monkeypatch.setattr(A, "validate_pool_dispel", fail)
    monkeypatch.setattr(specimens, "add", lambda platform, name, sources, **kw:
                        added.append((name, kw["what"]))
                        or tmp_path / "registered.D64")
    monkeypatch.setattr(specimens, "check_specimens", lambda: [])
    rc, slot, out = _drive(
        tmp_path, monkeypatch,
        ["load", "view BRUTUS", "cast ROLAND:DISPEL MAGIC>BRUTUS",
         "view BRUTUS", "save"],
        pool=_SpecimenPool, preserve_specimen=True)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert rc == 1 and slot.torn
    assert "saved Dispel row was restored" in summary["lost"]
    assert summary["specimen_validation"] == "failed"
    assert len(added) == 1 and "-failed-" in added[0][0]
    assert "validation failed" in added[0][1]


@pytest.mark.parametrize("steps", [
    ["load", "view BRUTUS", "cast ROLAND:DISPEL MAGIC>BRUTUS",
     "view BRUTUS", "save"],
    ["load", "view BRUTUS", "save"],
])
def test_pool_specimen_modes_parse_and_stage_without_claim(tmp_path, monkeypatch,
                                                           steps):
    monkeypatch.setattr(A.S, "claim_slot", lambda *a, **k: pytest.fail("claimed a slot"))
    assert A.main(["--title", "pool", "--save", str(_fixture_disk(tmp_path)),
                   "--issue", "700", "--run", "preserved-control",
                   "--preserve-specimen", "--stage-only", "--steps", *steps,
                   "--out", str(tmp_path / "prepared")]) == 0


@pytest.mark.parametrize("steps", [
    ["load", "save", "cast ROLAND:DISPEL MAGIC>BRUTUS"],
    ["load", "view BRUTUS", "save", "save"],
    ["load", "save"],
    ["load", "view BRUTUS", "cast ROLAND:ANIMATE DEAD", "save"],
    ["load", "view BRUTUS", "cast ROLAND:DISPEL MAGIC>BRUTUS",
     "cast ROLAND:DISPEL MAGIC>BRUTUS", "save"],
    ["view BRUTUS", "save"],
    ["load", "view BRUTUS", "cast ROLAND:DISPEL MAGIC>BRUTUS",
     "load", "save"],
    ["load", "view BRUTUS", "load", "save"],
    ["load", "walk I", "view BRUTUS", "save"],
    ["load", "view BRUTUS", "items BRUTUS", "save"],
])
def test_pool_specimen_rejects_ambiguous_steps_before_guest_claim(
        tmp_path, monkeypatch, steps):
    monkeypatch.setattr(A.S, "claim_slot", lambda *a, **k: pytest.fail("claimed a slot"))
    with pytest.raises(SystemExit) as exc:
        A.main(["--title", "pool", "--save", str(_fixture_disk(tmp_path)),
                "--issue", "700", "--disks", str(tmp_path),
                "--preserve-specimen", "--steps", *steps,
                "--out", str(tmp_path / "rejected")])
    assert exc.value.code == 2
    assert not (tmp_path / "rejected").exists()


@pytest.mark.parametrize("flags", [
    ["--issue", "703", "--preserve-specimen"],
    ["--issue", "700", "--capture-ready", "--preserve-specimen"],
])
def test_pool_specimen_rejects_mismatched_preservation_modes_before_claim(
        tmp_path, monkeypatch, flags):
    monkeypatch.setattr(A.S, "claim_slot", lambda *a, **k: pytest.fail("claimed a slot"))
    with pytest.raises(SystemExit) as exc:
        A.main(["--title", "pool", "--save", str(_fixture_disk(tmp_path)),
                *flags, "--steps", "load", "view BRUTUS", "save",
                "--out", str(tmp_path / "rejected")])
    assert exc.value.code == 2
    assert not (tmp_path / "rejected").exists()


def test_pool_specimen_does_not_register_a_save_before_its_cast_for_direct_run(
        tmp_path, monkeypatch):
    from tools.registry import specimens

    class Run(_Pool):
        def cast(self, arg):
            return {"spell": "DISPEL MAGIC", "target": "BRUTUS"}

        def save(self, staged):
            (tmp_path / "out" / "saved.D64").write_bytes(b"saved")
            return {"kept": str(tmp_path / "out" / "saved.D64")}

    monkeypatch.setattr(A, "validate_pool_dispel", lambda results: None)
    monkeypatch.setattr(specimens, "add", lambda *a, **k: pytest.fail("registered"))
    rc, slot, out = _drive(tmp_path, monkeypatch,
                           ["load", "save", "cast ROLAND:DISPEL MAGIC>BRUTUS"],
                           pool=Run, preserve_specimen=True)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert rc == 1 and slot.torn
    assert "no validated #700" in summary["lost"]
    assert "registered_specimen" not in summary


def test_pool_specimen_does_not_register_stale_save_after_failed_cast(
        tmp_path, monkeypatch):
    from tools.registry import specimens

    kept = tmp_path / "out" / "saved.D64"
    kept.parent.mkdir()
    kept.write_bytes(b"previous run")
    added = []

    class Run(_Pool):
        def view(self, who):
            return {"who": who}

        def cast(self, arg):
            raise A.StepFailed("cast stopped before game input")

        def save(self, staged):
            pytest.fail("the save step ran")

    monkeypatch.setattr(specimens, "add", lambda *a, **k: added.append(True))
    rc, slot, out = _drive(
        tmp_path, monkeypatch,
        ["load", "view BRUTUS", "cast ROLAND:DISPEL MAGIC>BRUTUS", "save"],
        pool=Run, preserve_specimen=True)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert rc == 1 and slot.torn
    assert not added and "registered_specimen" not in summary
    assert "cast stopped before game input" in summary["lost"]


# --- the camp cures (Curse: CURE BLINDNESS and the paladin's CURE) ---------------

@pytest.mark.parametrize("step", [
    "cast SHARA CURE BLINDNESS>PHILIPPE",       # no colon
    "cast SHARA:CURE BLINDNESS PHILIPPE",       # no arrow
    "cast SHARA:FIREBALL>PHILIPPE",             # not a camp cure
    "cast SHARA:CURE BLINDNESS>",               # nobody
    "cure MARK",                                # nobody
    "cure >LEDERA",                             # no paladin
])
def test_cast_and_cure_steps_parse_and_bad_ones_are_refused(step):
    with pytest.raises(ValueError):
        A.parse_steps(["load", step])


@pytest.mark.parametrize("step", [
    "ready BAKSHI",                       # no label
    "ready >GAUNTLETS OF OGRE POWER",     # nobody
])
def test_ready_step_parses_and_bad_ones_are_refused(step):
    with pytest.raises(ValueError):
        A.parse_steps(["load", step])


def test_cast_and_cure_steps_keep_their_names_and_the_pool_refuses_them(tmp_path):
    steps = A.parse_steps(["load", "camp-list PHILIPPE,LEDERA",
                           "cast SHARA:cure blindness>PHILIPPE", "cure MARK>LEDERA"])
    assert A.parse_cast(steps[2].arg) == ("SHARA", "CURE BLINDNESS", "PHILIPPE")
    assert A.parse_cure(steps[3].arg) == ("MARK", "LEDERA")
    with pytest.raises(SystemExit) as info:
        A.main(["--title", "pool", "--save", str(_fixture_disk(tmp_path)),
                "--stage-only", "--steps", "load", "cure MARK>LEDERA",
                "--out", str(tmp_path / "out")])
    assert info.value.code == 2


def test_pool_cast_accepts_animate_dead_without_a_target_and_refuses_other_forms(
        tmp_path):
    assert A.parse_cast("BRUTUS:animate dead") == ("BRUTUS", "ANIMATE DEAD", None)
    assert A.parse_cast("ROLAND:dispel magic>BRUTUS") == (
        "ROLAND", "DISPEL MAGIC", "BRUTUS")
    steps = A.parse_steps(["load", "cast BRUTUS:ANIMATE DEAD", "save"])
    assert steps[1].arg == "BRUTUS:ANIMATE DEAD"
    for bad in ("BRUTUS:ANIMATE DEAD>BAKSHI", "BRUTUS:CURE BLINDNESS",
                "ROLAND:DISPEL MAGIC"):
        with pytest.raises(ValueError):
            A.parse_cast(bad)
    assert A.main(["--title", "pool", "--save", str(_fixture_disk(tmp_path)),
                   "--stage-only", "--steps", "load", "cast BRUTUS:ANIMATE DEAD",
                   "save", "--out", str(tmp_path / "cast")]) == 0
    assert A.main(["--title", "pool", "--save", str(_fixture_disk(tmp_path)),
                   "--stage-only", "--steps", "load",
                   "cast ROLAND:DISPEL MAGIC>BRUTUS", "save",
                   "--out", str(tmp_path / "dispel")]) == 0


@pytest.mark.parametrize("cast", ["2:DISPEL MAGIC>BRUTUS",
                                        "ROLAND:DISPEL MAGIC>5"])
def test_pool_dispel_numeric_selectors_are_rejected_before_claim(tmp_path,
                                                                 monkeypatch, cast):
    with pytest.raises(ValueError, match="named caster and target"):
        A.parse_cast(cast)
    monkeypatch.setattr(A.S, "claim_slot", lambda *a, **k: pytest.fail("claimed a slot"))
    with pytest.raises(SystemExit) as exc:
        A.main(["--title", "pool", "--save", str(_fixture_disk(tmp_path)),
                "--steps", "load", f"cast {cast}", "save",
                "--out", str(tmp_path / "numeric")])
    assert exc.value.code == 2


def test_bad_cast_form_is_rejected_before_claiming_a_slot(tmp_path, monkeypatch):
    monkeypatch.setattr(A.S, "claim_slot", lambda *a, **k: pytest.fail("claimed a slot"))
    with pytest.raises(SystemExit) as exc:
        A.main(["--title", "pool", "--save", str(_fixture_disk(tmp_path)),
                "--steps", "load", "cast BRUTUS:ANIMATE DEAD>BRUTUS", "save",
                "--out", str(tmp_path / "bad-cast")])
    assert exc.value.code == 2


def test_ready_step_keeps_its_name_and_curse_refuses_it(tmp_path):
    steps = A.parse_steps(["load", "ready BAKSHI>GAUNTLETS OF OGRE POWER"])
    assert A.parse_ready(steps[1].arg) == ("BAKSHI", "GAUNTLETS OF OGRE POWER")
    with pytest.raises(SystemExit) as info:
        A.main(["--title", "curse", "--save", str(_fixture_disk(tmp_path)),
                "--stage-only", "--steps", "load",
                "ready BAKSHI>GAUNTLETS OF OGRE POWER",
                "--out", str(tmp_path / "out")])
    assert info.value.code == 2


class _ReadyMonitor:
    """A fake debugger monitor: each `(address, length)` gives one queued
    reading, popped in the order `ready()` reads it -- before, then after."""

    def __init__(self, script):
        self.script = script

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def read(self, address, length):
        return self.script[(address, length)].pop(0)

    def resume(self):
        pass


def test_ready_step_reaches_the_list_through_camp_toggles_once_and_reads_around_it(
        tmp_path, monkeypatch):
    """A magical item's READY toggle is refused with `NOT HERE` unless camp
    has set `$6DE4`; the world's own `VIEW` never sets it (#694). `ready`
    must reach the item list through `traitask.open_items` (which goes
    `ENCAMP > VIEW > ITEMS`) and leave through `traitask.leave_items`, never
    through the world's `VIEW` directly."""
    screens = {"world": _window({}, WORLD_BAR)}
    moves = {}
    sess = FakeSession(screens, moves, "world")

    slot_before = bytes(A.route_pool.SLOT_STRIDE)
    slot_after = bytes([0x26]) + bytes(A.route_pool.SLOT_STRIDE - 1)
    fx_before = bytes(A.route_pool.EFFECTS[1])
    fx_after = bytes([0x26]) + bytes(A.route_pool.EFFECTS[1] - 1)
    item_block = bytes(ITEM_BLOCK_STRIDE)

    script = {}
    for slot in range(8):
        key = (A.route_pool.SLOT_BASE + slot * A.route_pool.SLOT_STRIDE,
              A.route_pool.SLOT_STRIDE)
        script[key] = [slot_before, slot_after if slot == 4 else slot_before]
    script[A.route_pool.EFFECTS] = [fx_before, fx_after]
    for slot in range(8):
        key = (ITEM_AREA_BASE + slot * ITEM_BLOCK_STRIDE, ITEM_BLOCK_STRIDE)
        script[key] = [item_block, item_block]
    sess.mon = lambda timeout: _ReadyMonitor(script)

    calls = []

    def fake_open_items(s, log, name, label, tag):
        calls.append(("open_items", name, label, tag))
        return True

    def fake_toggle(s, log, label, tag):
        calls.append(("toggle_item", label, tag))
        return True

    def fake_leave_items(s, log):
        calls.append(("leave_items",))

    monkeypatch.setattr(A.route_pool, "open_items", fake_open_items)
    monkeypatch.setattr(A.route_pool, "toggle_item", fake_toggle)
    monkeypatch.setattr(A.route_pool, "leave_items", fake_leave_items)
    run, log = _pool_run(tmp_path, sess)
    got = run.ready("BAKSHI>GAUNTLETS OF OGRE POWER")
    log.close()

    assert calls == [
        ("open_items", "BAKSHI", "GAUNTLETS OF OGRE POWER", "ready"),
        ("toggle_item", "GAUNTLETS OF OGRE POWER", "ready"),
        ("leave_items",)]
    assert (got["who"], got["label"], got["screen_changed"], got["flipped"]) == (
        "BAKSHI", "GAUNTLETS OF OGRE POWER", True, True)
    assert got["record_diff"][4] == A.route_pool.diff_bytes(
        slot_before, slot_after,
        A.route_pool.SLOT_BASE + 4 * A.route_pool.SLOT_STRIDE)
    assert all(got["record_diff"][s] == [] for s in range(8) if s != 4)
    assert got["effects_diff"] == A.route_pool.diff_bytes(
        fx_before, fx_after, A.route_pool.EFFECTS[0])
    assert set(got["item_diff"]) == set(range(8))
    assert all(diff == [] for diff in got["item_diff"].values())
    assert got["memory_changed"] is True
    assert sess.state == "world"


def _ready_fake_reading(tmp_path, monkeypatch, *, screen_changed: bool,
                        record_changed: bool, effect_changed: bool,
                        item_changed: bool, second_item_changed: bool = False):
    sess = FakeSession({"world": _window({}, WORLD_BAR)}, {}, "world")
    script = {}
    for slot in range(8):
        record_before = bytearray(A.route_pool.SLOT_STRIDE)
        record_after = record_before.copy()
        item_before = bytearray(ITEM_BLOCK_STRIDE)
        item_after = item_before.copy()
        if slot == 4:
            record_before[0x1A] = 0x64
            record_after[0x1A] = 0x5A if record_changed else 0x64
            item_before[6] = 0x80
            item_after[6] = 0 if item_changed else 0x80
        if slot == 7 and second_item_changed:
            item_before[0x0A] = 0x80
        script[(A.route_pool.SLOT_BASE + slot * A.route_pool.SLOT_STRIDE,
                A.route_pool.SLOT_STRIDE)] = [bytes(record_before), bytes(record_after)]
        script[(ITEM_AREA_BASE + slot * ITEM_BLOCK_STRIDE,
                ITEM_BLOCK_STRIDE)] = [bytes(item_before), bytes(item_after)]
    effect_before = bytearray(A.route_pool.EFFECTS[1])
    effect_after = effect_before.copy()
    effect_before[0x3D] = 0x26
    effect_after[0x3D] = 0 if effect_changed else 0x26
    script[A.route_pool.EFFECTS] = [bytes(effect_before), bytes(effect_after)]
    sess.mon = lambda timeout: _ReadyMonitor(script)
    monkeypatch.setattr(A.route_pool, "open_items", lambda *a: True)
    monkeypatch.setattr(A.route_pool, "toggle_item", lambda *a: screen_changed)
    monkeypatch.setattr(A.route_pool, "leave_items", lambda *a: None)
    run, log = _pool_run(tmp_path, sess)
    try:
        return run.ready("BAKSHI>GAUNTLETS OF OGRE POWER")
    finally:
        log.close()


def test_ready_unchanged_yes_screen_still_reports_record_and_effect_changes(
        tmp_path, monkeypatch):
    got = _ready_fake_reading(tmp_path, monkeypatch, screen_changed=False,
                              record_changed=True, effect_changed=True,
                              item_changed=False)
    assert got["screen_changed"] is False and got["flipped"] is False
    assert got["memory_changed"] is True
    assert got["record_diff"][4] == [{"addr": 0x511A, "was": 0x64, "now": 0x5A}]
    assert got["effects_diff"] == [{"addr": 0x493D, "was": 0x26, "now": 0}]
    assert set(got["item_diff"]) == set(range(8))
    assert all(diff == [] for diff in got["item_diff"].values())


def test_ready_effect_only_delta_sets_memory_changed(tmp_path, monkeypatch):
    got = _ready_fake_reading(tmp_path, monkeypatch, screen_changed=False,
                              record_changed=False, effect_changed=True,
                              item_changed=False)
    assert got["screen_changed"] is False
    assert got["memory_changed"] is True
    assert all(diff == [] for diff in got["record_diff"].values())
    assert got["effects_diff"] == [{"addr": 0x493D, "was": 0x26, "now": 0}]
    assert set(got["item_diff"]) == set(range(8))
    assert all(diff == [] for diff in got["item_diff"].values())


def test_ready_post_save_item_bit_change_reports_item_address(tmp_path, monkeypatch):
    got = _ready_fake_reading(tmp_path, monkeypatch, screen_changed=True,
                              record_changed=False, effect_changed=False,
                              item_changed=True)
    assert got["screen_changed"] is True and got["flipped"] is True
    assert got["memory_changed"] is True
    assert all(diff == [] for diff in got["record_diff"].values())
    assert got["effects_diff"] == []
    assert set(got["item_diff"]) == set(range(8))
    assert got["item_diff"][4] == [{"addr": 0x5D06, "was": 0x80, "now": 0}]
    assert all(diff == [] for slot, diff in got["item_diff"].items() if slot != 4)


def test_ready_item_diff_uses_each_slots_absolute_address(tmp_path, monkeypatch):
    got = _ready_fake_reading(tmp_path, monkeypatch, screen_changed=False,
                              record_changed=False, effect_changed=False,
                              item_changed=True, second_item_changed=True)
    assert got["memory_changed"] is True
    assert set(got["item_diff"]) == set(range(8))
    assert got["item_diff"][4] == [{"addr": 0x5D06, "was": 0x80, "now": 0}]
    assert got["item_diff"][7] == [{"addr": 0x600A, "was": 0x80, "now": 0}]
    assert all(diff == [] for slot, diff in got["item_diff"].items()
               if slot not in (4, 7))


def test_ready_blank_redraw_with_no_memory_change_is_only_a_screen_change(
        tmp_path, monkeypatch):
    got = _ready_fake_reading(tmp_path, monkeypatch, screen_changed=True,
                              record_changed=False, effect_changed=False,
                              item_changed=False)
    assert got["screen_changed"] is True and got["flipped"] is True
    assert got["memory_changed"] is False
    assert all(diff == [] for diff in got["record_diff"].values())
    assert got["effects_diff"] == []
    assert set(got["item_diff"]) == set(range(8))
    assert all(diff == [] for diff in got["item_diff"].values())


def test_ready_sample_keeps_screen_colour_png_and_live_ram_in_one_pause(
        tmp_path, monkeypatch):
    events = []

    class Monitor:
        def __enter__(self):
            events.append("pause")
            return self

        def __exit__(self, *exc):
            events.append("close")

        def read(self, address, length):
            events.append(("read", address, length))
            return bytes([address >> 8]) * length

        def resume(self):
            events.append("resume")

    class Keyboard:
        def screenshot(self, path, *, timeout=None):
            events.append(("png", timeout))
            pathlib.Path(path).write_bytes(b"PNG")
            return True

    class Session:
        kbd = Keyboard()

        def mon(self, timeout):
            return Monitor()

    screen = Screen(bytes(1000), bytes([5]) * 1000, 0xCC00)
    monkeypatch.setattr(A.S, "is_bitmap", lambda m: events.append("bitmap") or False)
    monkeypatch.setattr(A.S, "read_screen", lambda m: events.append("screen") or screen)
    run, log = _pool_run(tmp_path, Session())
    try:
        got = run.sample_ready("before", lambda s: s is screen)
    finally:
        log.close()

    assert got is screen
    assert events == [
        "pause", "bitmap", "screen",
        ("read", 0x4900, 0x300),
        ("read", 0x5100, 0x100),
        ("read", 0x5D00, 0x100),
        ("png", 10.0), "resume", "close",
    ]
    captures = list(tmp_path.glob("*-ready-before.json"))
    assert len(captures) == 1
    payload = json.loads(captures[0].read_text(encoding="utf-8"))
    assert payload["screen_address"] == "$CC00"
    assert payload["colours"] == (bytes([5]) * 1000).hex()
    assert payload["effects"] == (bytes([0x49]) * 0x300).hex()
    assert payload["record"] == (bytes([0x51]) * 0x100).hex()
    assert payload["items"] == (bytes([0x5D]) * 0x100).hex()
    stem = captures[0].stem
    assert (tmp_path / f"{stem}.txt").exists()
    assert (tmp_path / f"{stem}.png").read_bytes() == b"PNG"


def test_ready_sample_screenshot_timeout_is_recorded_and_resumes_vice(
        tmp_path, monkeypatch):
    events = []

    class Monitor:
        def __enter__(self):
            events.append("pause")
            return self

        def __exit__(self, *exc):
            events.append("close")

        def read(self, address, length):
            events.append(("read", address, length))
            return bytes(length)

        def resume(self):
            events.append("resume")
            raise A.S.MonitorError("resume failed")

    class Session:
        kbd = drive.Keyboard(":99")

        def mon(self, timeout):
            return Monitor()

    def hung_import(args, **kwargs):
        events.append(("import", kwargs["timeout"]))
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    screen = Screen(bytes(1000), bytes(1000), 0xCC00)
    monkeypatch.setattr(drive.subprocess, "run", hung_import)
    monkeypatch.setattr(A.S, "is_bitmap", lambda m: events.append("bitmap") or False)
    monkeypatch.setattr(A.S, "read_screen", lambda m: events.append("screen") or screen)
    run, log = _pool_run(tmp_path, Session())
    try:
        with pytest.raises(A.StepFailed, match="READY before PNG capture failed"):
            run.sample_ready("before", lambda s: True)
    finally:
        log.close()

    assert events == [
        "pause", "bitmap", "screen",
        ("read", 0x4900, 0x300),
        ("read", 0x5100, 0x100),
        ("read", 0x5D00, 0x100),
        ("import", 10.0), "resume", "close",
    ]
    captures = list(tmp_path.glob("*-ready-before.json"))
    assert len(captures) == 1
    assert json.loads(captures[0].read_text(encoding="utf-8"))[
        "png_captured"] is False


def test_keyboard_screenshot_preserves_default_oserror_and_bounds_capture(
        monkeypatch):
    calls = []

    def missing_import(args, **kwargs):
        calls.append(kwargs)
        raise FileNotFoundError("import is missing")

    monkeypatch.setattr(drive.subprocess, "run", missing_import)
    keyboard = drive.Keyboard(":99")

    with pytest.raises(FileNotFoundError, match="import is missing"):
        keyboard.screenshot("/tmp/default.png")
    assert "timeout" not in calls[0]
    assert keyboard.screenshot("/tmp/ready.png", timeout=10.0) is False
    assert calls[1]["timeout"] == 10.0


def test_ready_sample_records_a_monitor_read_failure_and_keeps_polling(
        tmp_path, monkeypatch):
    events = []

    class Monitor:
        def __enter__(self):
            events.append("pause")
            return self

        def __exit__(self, *exc):
            events.append("close")

        def resume(self):
            events.append("resume")

    class Session:
        def mon(self, timeout):
            return Monitor()

    def failed_screen(_):
        raise A.S.MonitorError("screen read failed")

    monkeypatch.setattr(A.S, "is_bitmap", failed_screen)
    run, log = _pool_run(tmp_path, Session())
    try:
        assert run.sample_ready("change", lambda s: True) is None
    finally:
        log.close()

    assert events == ["pause", "resume", "close"]
    assert len(run.ready_sample_errors) == 1
    assert run.ready_sample_errors[0]["stage"] == "change"
    assert run.ready_sample_errors[0]["error"] == (
        "MonitorError('screen read failed')")
    assert isinstance(run.ready_sample_errors[0]["monotonic"], float)
    assert not list(tmp_path.glob("*-ready-change.json"))


def test_camp_list_reads_each_named_member(tmp_path):
    whom = _whom_screen(("PHILIPPE", "LEDERA"))
    screens = {
        "world": _window({}, WORLD_BAR), "camp": _window({}, CAMP),
        "magic": _window({}, MAGIC), "whom": whom,
        "on-p": whom, "on-l": whom, "on-x": whom,
        "p": _window({1: "PHILIPPE IS AFFECTED BY:", 3: "BLIND"}, A.CONTINUE),
        "l": _window({1: "LEDERA IS AFFECTED BY:", 3: "DISEASE"}, A.CONTINUE),
    }
    moves = {
        ("world", ("bar", "ENCAMP")): "camp", ("camp", ("bar", "MAGIC")): "magic",
        ("magic", ("bar", "DISPLAY")): "whom",
        ("whom", ("party", 0)): "on-p", ("on-p", ("key", "Return")): "p",
        ("p", ("key", 0x0D)): "whom",
        ("whom", ("party", 1)): "on-l", ("on-l", ("key", "Return")): "l",
        ("l", ("key", 0x0D)): "whom",
        ("whom", ("party", 3)): "on-x", ("on-x", ("key", "Return")): "magic",
        ("magic", ("bar", "EXIT")): "camp", ("camp", ("bar", "EXIT")): "world",
    }
    sess = FakeSession(screens, moves, "world")
    run, log = _pool_run(tmp_path, sess)
    got = run.camp_list("PHILIPPE,LEDERA")
    log.close()
    assert got["lists"] == {"PHILIPPE": ["BLIND"], "LEDERA": ["DISEASE"]}
    assert sess.state == "world"


CAST_LIST = "CAST MEMORIZE SCRIBE NEXT PREV EXIT"
CAST_SCREENS = {
    "camp": _window({}, CAMP), "magic": _window({}, MAGIC),
    "list": _window({3: "CURE BLINDNESS"}, CAST_LIST),
    "picking": _window({3: "CURE BLINDNESS"}, "PICK A SPELL TO CAST"),
    "whom": [*_whom_screen(("PHILIPPE", "SHARA", "LEDERA"))[:24],
             "CAST SPELL ON WHOM?".ljust(40)],
    "on": _whom_screen(("PHILIPPE",)),
    "msg": _window({2: "PHILIPPE CAN SEE AGAIN"}, A.CONTINUE),
    "unknown": _window({}, "SOMETHING ELSE"),
}


def _cast_moves(pick):
    """The moves up to the pick key, then whatever `pick` says the keys do."""
    return {
        ("camp", ("party", 1)): "camp", ("camp", ("bar", "MAGIC")): "magic",
        ("magic", ("bar", "CAST")): "list", ("list", ("bar", "CAST")): "picking",
        ("whom", ("party", 0)): "on", ("on", ("key", "Return")): "msg",
        ("msg", ("key", 0x0D)): "magic", **pick,
    }


def _curse_run(tmp_path, sess, rows=(), joy=False):
    run = A.CurseRun.__new__(A.CurseRun)
    run.sess = sess
    run.out = tmp_path
    run.log = A.Log(tmp_path)
    run.shots = 0
    run.names = ["PHILIPPE", "SHARA", "LEDERA", "TRAVIS", "MARK", "MATHEW"]
    run.panel = list(reversed(run.names))
    run.joy = joy
    run.pick_wait = run.bar_wait = run.whom_wait = 0.3
    run.panel_index = lambda who: {"SHARA": 1, "MARK": 4}[who]
    readings = iter(rows)
    run.reading = lambda: {"effects": [r.copy() for r in next(readings)]}
    return run


class _CurseFake(FakeSession):
    def press_bar(self, label, row=24, timeout=0):
        return self._go(("bar", label))


def _cast(tmp_path, pick, joy=False, rows=None):
    blind, disease = [62, 33, 0, 0, 5], [61, 34, 2, 0, 0x85]
    rows = rows or [[blind, disease], [disease]]
    sess = _CurseFake(CAST_SCREENS, _cast_moves(pick), "camp")
    run = _curse_run(tmp_path, sess, rows, joy)
    return run, sess


def test_curse_cast_records_the_targets_row_transition(tmp_path):
    run, sess = _cast(tmp_path, {("picking", ("key", "Return")): "whom"})
    try:
        got = run.cast("SHARA:CURE BLINDNESS>PHILIPPE")
    finally:
        run.log.close()
    assert got["row_before"] == [62, 33, 0, 0, 5] and got["row_after"] is None
    assert got["effects_after"] == [[61, 34, 2, 0, 0x85]]
    assert (got["id"], got["owner"], got["key"]) == (33, 0, "xtest-return")
    assert got["messages"] == [["PHILIPPE CAN SEE AGAIN"]]
    assert sess.sent == [("party", 1), ("bar", "MAGIC"), ("bar", "CAST"),
                         ("bar", "CAST"), ("key", "Return"), ("party", 0),
                         ("key", "Return"), ("key", 0x0D)]


def _animate_party(status: int, *, animated: bool = False) -> list[dict]:
    party = [{"slot": slot, "status": 0, "traits": [0] * 10,
              "creature_type": 0} for slot in range(8)]
    party[1]["status"] = status
    if animated:
        party[1]["traits"][9] = 32
        party[1]["creature_type"] = 4
    return party


def test_pool_cast_reads_party_before_and_after_without_waiting_for_a_target(
        tmp_path):
    screens = {**CAST_SCREENS,
               "list": _window({3: "ANIMATE DEAD"}, CAST_LIST),
               "picking": _window({3: "ANIMATE DEAD"}, A.PICK_SPELL),
               "msg": _window({2: "THE DEAD RISE"}, A.CONTINUE)}
    moves = _cast_moves({("picking", ("key", "Return")): "msg"})
    moves[("camp", ("party", 1))] = "camp"
    moves[("msg", ("key", 0x0D))] = "magic"
    sess = _CurseFake(screens, moves, "camp")
    run, log = _pool_run(tmp_path, sess)
    run.panel_index = lambda who: 1
    before, after = _animate_party(0x83), _animate_party(0x03, animated=True)
    run.reading = lambda: {"party": before if sess.state == "picking" else after,
                           "effects": []}
    try:
        got = run.cast("BRUTUS:ANIMATE DEAD")
    finally:
        log.close()
    assert got["spell"] == "ANIMATE DEAD"
    assert got["party_before"] == before and got["party_after"] == after
    assert got["messages"] == [["THE DEAD RISE"]]
    assert sess.sent == [("party", 1), ("bar", "MAGIC"), ("bar", "CAST"),
                         ("bar", "CAST"), ("key", "Return"), ("key", 0x0D)]
    assert list(tmp_path.glob("*cast-result.txt"))


def _dispel_readings():
    party = _animate_party(0x01)
    party[1].update(name="ROLAND", memorised=[41], cleric_level=5)
    party[5].update(name="BRUTUS", status=0x03, creature_type=4)
    party[5]["traits"][9] = 32
    rows = [[slot, 0, 0, 0, 0] for slot in range(64)]
    rows[63] = [63, 32, 5, 0, 5]
    before = {"party": party, "effects": [rows[63]], "effect_rows": rows}
    after_party = [member.copy() for member in party]
    after_party[1]["memorised"] = []
    after_rows = [row.copy() for row in rows]
    after_rows[63][1] = 0
    after = {"party": after_party, "effects": [], "effect_rows": after_rows}
    return before, after


def _dispel_run(tmp_path, before, after):
    screens = {**CAST_SCREENS,
               "list": _window({3: "DISPEL MAGIC"}, CAST_LIST),
               "picking": _window({3: "DISPEL MAGIC", 4: "EXIT"}, A.PICK_SPELL),
               "whom": [*_whom_screen(("BRUTUS", "ROLAND"))[:24],
                        "CAST SPELL ON WHOM?".ljust(40)],
               "msg": _window({2: "THE MAGIC IS DISPELLED"}, A.CONTINUE)}
    moves = _cast_moves({("picking", ("key", "Return")): "whom"})
    sess = _CurseFake(screens, moves, "camp")
    run, log = _pool_run(tmp_path, sess)
    run.panel_index = lambda who: {"ROLAND": 1}[who]
    run.reading = lambda: after if sess.state == "magic" else before
    return run, log, sess


def test_pool_dispel_picks_the_named_target_and_keeps_raw_row_checkpoints(tmp_path):
    before, after = _dispel_readings()
    run, log, sess = _dispel_run(tmp_path, before, after)
    try:
        got = run.cast("ROLAND:DISPEL MAGIC>BRUTUS")
    finally:
        log.close()
    assert (got["spell_id"], got["target"], got["slot"]) == (41, "BRUTUS", 5)
    assert got["row_before"] == [63, 32, 5, 0, 5]
    assert got["row_after"] == [63, 0, 5, 0, 5]
    assert got["effect_rows_before"] == before["effect_rows"]
    assert got["effect_rows_after"] == after["effect_rows"]
    assert got["party_before"] == before["party"]
    assert got["party_after"] == after["party"]
    assert got["messages"] == [["THE MAGIC IS DISPELLED"]]
    assert sess.sent == [("party", 1), ("bar", "MAGIC"), ("bar", "CAST"),
                         ("bar", "CAST"), ("key", "Return"), ("party", 0),
                         ("key", "Return"), ("key", 0x0D)]


def test_pool_dispel_waits_past_blank_announcement_without_a_key(tmp_path,
                                                                   monkeypatch):
    before, after = _dispel_readings()
    run, log, sess = _dispel_run(tmp_path, before, after)
    sess.screens["announcement"] = _window(
        {2: "ROLAND CASTS", 3: "DISPEL MAGIC"}, "")
    sess.moves[("on", ("key", "Return"))] = "announcement"
    elapsed = [0.0]
    run.clock = lambda: elapsed[0]

    def advance(seconds):
        elapsed[0] += seconds
        if elapsed[0] >= 2 and sess.state == "announcement":
            sess.state = "msg"

    monkeypatch.setattr(A.time, "sleep", advance)
    run.reading = lambda: after if sess.state == "magic" else before
    try:
        got = run.cast("ROLAND:DISPEL MAGIC>BRUTUS")
    finally:
        log.close()
    assert got["row_after"] == [63, 0, 5, 0, 5]
    assert ("key", 0x0D) in sess.sent
    assert sess.sent.count(("key", 0x0D)) == 1
    assert list(tmp_path.glob("*-dispel-observe-*.txt"))


def test_pool_dispel_blank_announcement_times_out_with_pc_and_no_key(
        tmp_path, monkeypatch):
    before, after = _dispel_readings()
    run, log, sess = _dispel_run(tmp_path, before, after)
    sess.screens["announcement"] = _window(
        {2: "ROLAND CASTS", 3: "DISPEL MAGIC"}, "")
    sess.moves[("on", ("key", "Return"))] = "announcement"
    sess.stall_capture = lambda: "CPU PC=$1234"
    elapsed = [0.0]
    run.clock = lambda: elapsed[0]
    monkeypatch.setattr(A.time, "sleep", lambda seconds: elapsed.__setitem__(
        0, elapsed[0] + seconds))
    try:
        with pytest.raises(A.StepFailed, match="pending"):
            run.cast("ROLAND:DISPEL MAGIC>BRUTUS")
    finally:
        log.close()
    assert ("key", 0x0D) not in sess.sent
    assert "CPU PC=$1234" in (tmp_path / "run.jsonl").read_text()


def test_pool_dispel_consumed_spell_with_unchanged_row_is_failed_roll(
        tmp_path):
    before, after = _dispel_readings()
    after["effect_rows"] = before["effect_rows"]
    after["effects"] = before["effects"]
    run, log, sess = _dispel_run(tmp_path, before, after)
    try:
        with pytest.raises(A.StepFailed, match="unsuccessful roll"):
            run.cast("ROLAND:DISPEL MAGIC>BRUTUS")
    finally:
        log.close()
    assert sess.state == "magic"


def test_pool_dispel_row_can_clear_only_after_exiting_spell_list(tmp_path):
    before, after = _dispel_readings()
    run, log, sess = _dispel_run(tmp_path, before, after)
    listed = {**before, "party": after["party"]}
    sess.moves[("msg", ("key", 0x0D))] = "list"
    sess.moves[("list", ("bar", "EXIT"))] = "magic"
    run.reading = lambda: (after if sess.state == "magic" else
                           listed if sess.state == "list" else before)
    try:
        got = run.cast("ROLAND:DISPEL MAGIC>BRUTUS")
    finally:
        log.close()
    assert got["row_after"] == [63, 0, 5, 0, 5]
    assert ("bar", "EXIT") in sess.sent


def test_pool_dispel_menu_with_spell_still_present_waits_for_deadline(
        tmp_path, monkeypatch):
    before, after = _dispel_readings()
    run, log, sess = _dispel_run(tmp_path, before, after)
    sess.stall_capture = lambda: "CPU PC=$5678"
    run.reading = lambda: before
    elapsed = [0.0]
    run.clock = lambda: elapsed[0]
    monkeypatch.setattr(A.time, "sleep", lambda seconds: elapsed.__setitem__(
        0, elapsed[0] + seconds))
    try:
        with pytest.raises(A.StepFailed, match="pending"):
            run.cast("ROLAND:DISPEL MAGIC>BRUTUS")
    finally:
        log.close()
    assert elapsed[0] >= 60
    assert "CPU PC=$5678" in (tmp_path / "run.jsonl").read_text()


def test_pool_dispel_does_not_acknowledge_after_observation_deadline(tmp_path):
    run, log, sess = _dispel_run(tmp_path, *_dispel_readings())
    sess.state = "msg"
    elapsed = [0.0]
    run.clock = lambda: elapsed[0]
    sess.settle = lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds)
    try:
        with pytest.raises(A.StepFailed, match="deadline"):
            run._acknowledge(label="dispel", until=0.5)
    finally:
        log.close()
    assert ("key", 0x0D) not in sess.sent


def test_pool_dispel_refuses_wrong_member_before_input_and_wrong_spell_before_pick(
        tmp_path):
    before, after = _dispel_readings()
    before["party"][5]["name"] = "SILAS"
    run, log, sess = _dispel_run(tmp_path, before, after)
    try:
        with pytest.raises(A.StepFailed, match="BRUTUS"):
            run.cast("ROLAND:DISPEL MAGIC>BRUTUS")
    finally:
        log.close()
    assert sess.sent == []

    before, after = _dispel_readings()
    run, log, sess = _dispel_run(tmp_path, before, after)
    sess.screens["picking"] = _window({3: "ANIMATE DEAD", 4: "EXIT"}, A.PICK_SPELL)
    try:
        with pytest.raises(A.StepFailed, match="DISPEL MAGIC"):
            run.cast("ROLAND:DISPEL MAGIC>BRUTUS")
    finally:
        log.close()
    assert ("key", "Return") not in sess.sent


def test_pool_dispel_refuses_a_resistant_row_before_game_input(tmp_path):
    before, after = _dispel_readings()
    before["effect_rows"][63][4] = 6
    run, log, sess = _dispel_run(tmp_path, before, after)
    try:
        with pytest.raises(A.StepFailed, match="not eligible"):
            run.cast("ROLAND:DISPEL MAGIC>BRUTUS")
    finally:
        log.close()
    assert sess.sent == []


def test_pool_dispel_saved_checkpoint_requires_the_cleared_row_and_member():
    _, after = _dispel_readings()
    act = {"verb": "cast", "spell": "DISPEL MAGIC", "target": "BRUTUS", "slot": 5,
           "row_after": after["effect_rows"][63],
           "effect_rows_after": after["effect_rows"], "party_after": after["party"]}
    saved = {"verb": "save", "effect_rows": after["effect_rows"],
             "party": after["party"]}
    A.validate_pool_dispel([act, saved])
    with pytest.raises(A.StepFailed, match="save followed"):
        A.validate_pool_dispel([act])
    changed = json.loads(json.dumps(saved))
    changed["effect_rows"][63][1] = 32
    with pytest.raises(A.StepFailed, match="Dispel Magic row"):
        A.validate_pool_dispel([act, changed])
    changed = json.loads(json.dumps(saved))
    changed["party"][5]["status"] = 1
    with pytest.raises(A.StepFailed, match="BRUTUS"):
        A.validate_pool_dispel([act, changed])


def test_curse_cast_reads_row_after_only_once_the_spell_list_is_exited(tmp_path):
    """When the acknowledged cure leaves the spell list still up, the game's
    row for the cured id clears only once EXIT is chosen -- reading it any
    earlier still shows the cured condition as active."""
    blind, disease = [62, 33, 0, 0, 5], [61, 34, 2, 0, 0x85]
    moves = _cast_moves({("picking", ("key", "Return")): "whom"})
    moves[("msg", ("key", 0x0D))] = "list"
    moves[("list", ("bar", "EXIT"))] = "magic"
    sess = _CurseFake(CAST_SCREENS, moves, "camp")
    run = _curse_run(tmp_path, sess, [[blind, disease]])
    run.reading = lambda: {"effects": [disease] if sess.state == "magic"
                           else [blind, disease]}
    try:
        got = run.cast("SHARA:CURE BLINDNESS>PHILIPPE")
    finally:
        run.log.close()
    assert got["row_before"] == [62, 33, 0, 0, 5]
    assert got["row_after"] is None
    assert sess.state == "magic"


def test_curse_cast_polls_briefly_when_the_row_clears_a_reading_behind_the_bar(
        tmp_path, monkeypatch):
    """The live effect row can still carry the cured id for a reading or two
    after the bar already shows the spell list left -- the step waits
    briefly for it to clear rather than reporting that stale reading."""
    monkeypatch.setattr(A.time, "sleep", lambda s: None)
    blind, disease = [62, 33, 0, 0, 5], [61, 34, 2, 0, 0x85]
    run, sess = _cast(tmp_path, {("picking", ("key", "Return")): "whom"})
    calls: list[int] = []

    def reading():
        calls.append(1)
        return {"effects": [blind, disease] if len(calls) < 3 else [disease]}

    run.reading = reading
    try:
        got = run.cast("SHARA:CURE BLINDNESS>PHILIPPE")
    finally:
        run.log.close()
    assert got["row_after"] is None
    assert len(calls) == 3  # the row-before read, one stale row-after, one retry


def test_curse_cast_reports_the_row_as_stale_once_the_poll_bound_is_spent(
        tmp_path, monkeypatch):
    """A row that never clears is a real failure, not a stale read, so the
    poll gives up after a bounded number of tries and reports what it saw."""
    monkeypatch.setattr(A.time, "sleep", lambda s: None)
    blind, disease = [62, 33, 0, 0, 5], [61, 34, 2, 0, 0x85]
    run, sess = _cast(tmp_path, {("picking", ("key", "Return")): "whom"})
    calls: list[int] = []

    def reading():
        calls.append(1)
        return {"effects": [blind, disease]}

    run.reading = reading
    try:
        got = run.cast("SHARA:CURE BLINDNESS>PHILIPPE")
    finally:
        run.log.close()
    assert got["row_after"] == blind
    assert len(calls) == 6  # the row-before read, then a bounded five tries


def test_curse_cast_settle_row_sleeps_for_its_pause_constant(tmp_path, monkeypatch):
    """Each retry waits for `_settle_row`'s own `pause` default -- recording
    the real durations passed to `time.sleep` rather than stubbing it away,
    so a changed pause value would show up here."""
    slept: list[float] = []
    monkeypatch.setattr(A.time, "sleep", lambda s: slept.append(s))
    blind, disease = [62, 33, 0, 0, 5], [61, 34, 2, 0, 0x85]
    run, sess = _cast(tmp_path, {("picking", ("key", "Return")): "whom"})
    run.reading = lambda: {"effects": [blind, disease]}
    try:
        run.cast("SHARA:CURE BLINDNESS>PHILIPPE")
    finally:
        run.log.close()
    # `_settle_row`'s own `pause: float = 0.3` default.
    assert slept == [0.3, 0.3, 0.3, 0.3]


def test_curse_cast_stops_polling_the_row_once_the_runs_deadline_is_spent(
        tmp_path, monkeypatch):
    """A row poll that never clears must still give up once the run's own
    deadline is spent, rather than running its full bound of tries."""
    slept: list[float] = []
    monkeypatch.setattr(A.time, "sleep", lambda s: slept.append(s))
    blind, disease = [62, 33, 0, 0, 5], [61, 34, 2, 0, 0x85]
    run, sess = _cast(tmp_path, {("picking", ("key", "Return")): "whom"})
    calls: list[int] = []

    def reading():
        calls.append(1)
        return {"effects": [blind, disease]}

    run.reading = reading
    # The deadline check only matters once the poll starts, after the
    # row-before read and the reading passed into `_settle_row` -- before
    # that, treating the run as spent would fail an earlier step outright.
    run.spent = lambda: len(calls) >= 2
    try:
        got = run.cast("SHARA:CURE BLINDNESS>PHILIPPE")
    finally:
        run.log.close()
    assert got["row_after"] == blind
    assert len(calls) == 2
    assert slept == []


def test_curse_cast_recognises_a_one_spell_list_and_selects_cast(tmp_path):
    one = "CAST EXIT"
    screens = {**CAST_SCREENS,
               "list": _window({1: "SHARA'S MEMORIZED SPELLS", 3: "3RD LEVEL",
                                4: "  CURE BLINDNESS"}, one),
               "picking": _window({3: "CURE BLINDNESS"}, "PICK A SPELL TO CAST")}
    blind, disease = [62, 33, 0, 0, 5], [61, 34, 2, 0, 0x85]
    sess = _CurseFake(screens, _cast_moves({("picking", ("key", "Return")): "whom"}),
                      "camp")
    run = _curse_run(tmp_path, sess, [[blind, disease], [disease]])
    try:
        got = run.cast("SHARA:CURE BLINDNESS>PHILIPPE")
    finally:
        run.log.close()
    assert got["row_after"] is None
    # CAST is highlighted when the list opens, so the bar walk sends one Return.
    assert sess.sent[2:5] == [("bar", "CAST"), ("bar", "CAST"), ("key", "Return")]


def test_curse_cast_tries_the_kernal_key_when_the_first_did_nothing(tmp_path):
    run, sess = _cast(tmp_path, {("picking", ("key", "Return")): "picking",
                                 ("picking", ("key", 0x0D)): "whom"})
    try:
        got = run.cast("SHARA:CURE BLINDNESS>PHILIPPE")
    finally:
        run.log.close()
    assert got["key"] == "kernal-return"
    assert sess.sent[4:6] == [("key", "Return"), ("key", 0x0D)]


def test_curse_cast_sends_fire_only_with_the_joystick(tmp_path):
    both_dead = {("picking", ("key", "Return")): "picking",
                 ("picking", ("key", 0x0D)): "picking"}
    run, sess = _cast(tmp_path, both_dead)
    with pytest.raises(A.StepFailed, match="none of"):
        run.cast("SHARA:CURE BLINDNESS>PHILIPPE")
    run.log.close()
    assert sess.sent[4:] == [("key", "Return"), ("key", 0x0D)]
    assert list(tmp_path.glob("*lost-pick.txt"))

    (tmp_path / "joy").mkdir()
    run, sess = _cast(tmp_path / "joy",
                      {**both_dead, ("picking", ("key", "KP_0")): "whom"}, joy=True)
    try:
        got = run.cast("SHARA:CURE BLINDNESS>PHILIPPE")
    finally:
        run.log.close()
    assert got["key"] == "joystick-fire"
    assert sess.sent[4:7] == [("key", "Return"), ("key", 0x0D), ("key", "KP_0")]


class _RedrawFake(_CurseFake):
    """Serves the `redraw` screen for two reads, then moves on to `whom`."""

    reads = 0

    def screen(self):
        if self.state == "redraw":
            self.reads += 1
            if self.reads > 2:
                self.state = "whom"
        return super().screen()


# The camp picture with an empty right panel, the old prompt still on row 24.
_REDRAW = _window({}, "PICK A SPELL TO CAST")


def test_curse_cast_waits_through_the_redraw_after_a_pick(tmp_path):
    screens = {**CAST_SCREENS, "redraw": _REDRAW}
    sess = _RedrawFake(screens, _cast_moves({("picking", ("key", "Return")): "redraw"}),
                       "camp")
    run = _curse_run(tmp_path, sess, [[[62, 33, 0, 0, 5]], []])
    run.whom_wait = 1.5
    try:
        got = run.cast("SHARA:CURE BLINDNESS>PHILIPPE")
    finally:
        run.log.close()
    assert got["key"] == "xtest-return"
    assert [k for k in sess.sent if k[0] == "key" and k[1] != 0x0D].count(
        ("key", "Return")) == 2  # one pick, one target Return
    assert sess.sent[4:6] == [("key", "Return"), ("party", 0)]


def test_curse_cast_fails_when_a_changed_screen_never_asks_the_question(tmp_path):
    screens = {**CAST_SCREENS, "redraw": _REDRAW}
    sess = _CurseFake(screens, _cast_moves({("picking", ("key", "Return")): "unknown"}),
                      "camp")
    run = _curse_run(tmp_path, sess, [], joy=True)
    with pytest.raises(A.StepFailed, match="never came up"):
        run.cast("SHARA:CURE BLINDNESS>PHILIPPE")
    run.log.close()
    assert sess.sent[4:] == [("key", "Return")] and sess.state == "unknown"
    assert list(tmp_path.glob("*lost-pick-no-whom.txt"))


def test_curse_cure_names_its_target_and_leaves_the_sheet(tmp_path):
    dis, timer = [61, 34, 2, 0, 0x85], [59, 141, 4, 199, 199]
    screens = {
        "camp": _window({}, CAMP),
        "sheet": _window({1: "MARK"}, "VIEW:ITEMS SPELLS TRADE DROP CURE EXIT"),
        "whom": CAST_SCREENS["whom"], "on": CAST_SCREENS["on"],
        "sheet2": _window({1: "MARK"}, "VIEW:ITEMS SPELLS TRADE DROP EXIT"),
    }
    moves = {
        ("camp", ("party", 4)): "camp", ("camp", ("bar", "VIEW")): "sheet",
        ("sheet", ("bar", "CURE")): "whom", ("whom", ("party", 2)): "on",
        ("on", ("key", "Return")): "sheet2", ("sheet2", ("bar", "EXIT")): "camp",
    }
    sess = _CurseFake(screens, moves, "camp")
    run = _curse_run(tmp_path, sess, [[dis], [timer]])
    try:
        got = run.cure("MARK>LEDERA")
    finally:
        run.log.close()
    assert got["row_before"] == dis and got["row_after"] is None
    assert got["effects_after"] == [timer] and (got["id"], got["owner"]) == (34, 2)
    assert sess.state == "camp"


def _cure_run(tmp_path, sess, rows=()):
    dis = [61, 34, 2, 0, 0x85]
    screens = {
        "camp": _window({}, CAMP),
        "sheet": _window({1: "MARK"}, "VIEW:ITEMS SPELLS TRADE DROP CURE EXIT"),
        "whom": CAST_SCREENS["whom"], "on": CAST_SCREENS["on"],
        "sheet2": _window({1: "MARK"}, "VIEW:ITEMS SPELLS TRADE DROP EXIT"),
    }
    moves = {
        ("camp", ("party", 4)): "camp", ("camp", ("bar", "VIEW")): "sheet",
        ("sheet", ("bar", "CURE")): "whom", ("whom", ("party", 2)): "on",
        ("on", ("key", "Return")): "sheet2", ("sheet2", ("bar", "EXIT")): "camp",
    }
    sess = sess(screens, moves, "camp")
    run = _curse_run(tmp_path, sess, rows)
    return run, sess, dis


def test_curse_cure_polls_briefly_when_the_new_row_lags_a_reading_behind_the_bar(
        tmp_path, monkeypatch):
    """The cure's own new effect row can still be missing for a reading or
    two after the message it just showed on screen -- the step waits
    briefly for it to appear rather than reporting a row-less reading."""
    monkeypatch.setattr(A.time, "sleep", lambda s: None)
    timer = [59, 141, 4, 199, 199]
    run, sess, dis = _cure_run(tmp_path, _CurseFake)
    calls: list[int] = []

    def reading():
        calls.append(1)
        return {"effects": [dis] if len(calls) < 3 else [timer]}

    run.reading = reading
    try:
        got = run.cure("MARK>LEDERA")
    finally:
        run.log.close()
    assert got["effects_after"] == [timer]
    assert len(calls) == 3  # the row-before read, one stale post-ack read, one retry


def test_curse_cure_reports_no_new_row_once_the_poll_bound_is_spent(
        tmp_path, monkeypatch):
    """A new row that never shows up is a real failure, not a stale read, so
    the poll gives up after a bounded number of tries and reports what it saw."""
    monkeypatch.setattr(A.time, "sleep", lambda s: None)
    run, sess, dis = _cure_run(tmp_path, _CurseFake)
    calls: list[int] = []

    def reading():
        calls.append(1)
        return {"effects": [dis]}

    run.reading = reading
    try:
        got = run.cure("MARK>LEDERA")
    finally:
        run.log.close()
    assert got["effects_after"] == [dis]
    assert len(calls) == 6  # the row-before read, then a bounded five tries


def test_curse_cure_fails_with_a_capture_when_the_sheet_offers_no_cure(tmp_path):
    screens = {"camp": _window({}, CAMP),
               "sheet": _window({}, "VIEW:ITEMS SPELLS TRADE DROP EXIT")}
    sess = _CurseFake(screens, {("camp", ("party", 4)): "camp",
                                ("camp", ("bar", "VIEW")): "sheet"}, "camp")
    run = _curse_run(tmp_path, sess, [])
    with pytest.raises(A.StepFailed, match="offers no CURE"):
        run.cure("MARK>LEDERA")
    run.log.close()
    assert list(tmp_path.glob("*lost-cure-not-offered.txt"))


def _evidence():
    base = [[60, 45, 4, 0, 255], [63, 141, 5, 199, 199]]
    blind, dis, timer = [62, 33, 0, 0, 5], [61, 34, 2, 0, 0x85], [59, 141, 4, 199, 199]
    return [
        {"verb": "camp-list", "lists": {"PHILIPPE": ["BLIND"], "LEDERA": ["DISEASE"]}},
        {"verb": "cast", "caster": "SHARA", "caster_owner": 1, "spell": "CURE BLINDNESS",
         "target": "PHILIPPE", "owner": 0, "id": 33, "word": "BLIND",
         "row_before": blind, "row_after": None,
         "effects_before": [*base, blind, dis], "effects_after": [*base, dis]},
        {"verb": "cure", "paladin": "MARK", "caster_owner": 4, "target": "LEDERA",
         "owner": 2, "id": 34, "word": "DISEASE",
         "row_before": dis, "row_after": None,
         "effects_before": [*base, dis], "effects_after": [*base, timer]},
        {"verb": "camp-list", "lists": {"PHILIPPE": [], "LEDERA": []}},
        {"verb": "save", "kept": "saved.D64", "effects": [*base, timer]},
    ]


def _party(memorised=(0,)):
    return lambda path: {"SHARA": {"owner": 1, "memorised": list(memorised)}}


def test_curse_cures_pass_on_the_complete_evidence():
    A.validate_curse_cures(_evidence(), "saved.D64", _party())


def _mutate(fn):
    def change(results):
        fn(results)
        return results
    return change


@pytest.mark.parametrize("mutation,match", [
    (lambda r: r[1].update(row_before=None), "already absent"),
    (lambda r: r[1].update(row_after=[62, 33, 0, 0, 5]), "refuted"),
    (lambda r: r[2].update(row_after=[61, 34, 2, 0, 0x85]), "refuted"),
    (lambda r: r[0]["lists"].update(PHILIPPE=[]), "did not show PHILIPPE"),
    (lambda r: r[3]["lists"].update(LEDERA=["DISEASE"]), "still showed LEDERA"),
    (lambda r: r[4]["effects"].append([62, 33, 0, 0, 5]), "still held PHILIPPE"),
    (lambda r: r[1]["effects_after"].pop(0), "also took away"),
    (lambda r: r[2]["effects_after"].pop(), "add one id-141"),
    (lambda r: r[4]["effects"].pop(), "lost MARK's id-141"),
    (lambda r: r[1]["effects_after"].append([58, 141, 1, 9, 9]), "added"),
])
def test_curse_cures_need_every_piece_of_evidence(mutation, match):
    results = _evidence()
    mutation(results)
    with pytest.raises(A.StepFailed, match=match):
        A.validate_curse_cures(results, "saved.D64", _party())


def test_curse_cures_need_the_spell_gone_from_the_saved_memorised_list():
    with pytest.raises(A.StepFailed, match="memorised"):
        A.validate_curse_cures(_evidence(), "saved.D64", _party((37, 0)))


def _animate_evidence() -> list[dict]:
    before, after = _animate_party(0x83), _animate_party(0x03, animated=True)
    return [{"verb": "cast", "spell": "ANIMATE DEAD", "caster": "BRUTUS",
             "party_before": before, "party_after": after},
            {"verb": "save", "party": _animate_party(0x03, animated=True)}]


def test_pool_animate_dead_accepts_only_the_game_written_zombie():
    A.validate_pool_party_spells(_animate_evidence())
    for field, value, message in (("status", 0x83, "status"),
                                  ("creature_type", 0, "creature")):
        results = _animate_evidence()
        results[1]["party"][1][field] = value
        with pytest.raises(A.StepFailed, match=message):
            A.validate_pool_party_spells(results)
    results = _animate_evidence()
    results[1]["party"][1]["traits"][9] = 0
    with pytest.raises(A.StepFailed, match="trait"):
        A.validate_pool_party_spells(results)


def test_pool_animate_dead_needs_one_dead_victim_and_a_later_save():
    results = _animate_evidence()
    results[0]["party_before"][1]["status"] = 0x01
    with pytest.raises(A.StepFailed, match="dead victim"):
        A.validate_pool_party_spells(results)
    with pytest.raises(A.StepFailed, match="save"):
        A.validate_pool_party_spells(_animate_evidence()[:1])


def test_pool_cast_run_checks_the_saved_zombie_without_an_emulator(tmp_path, monkeypatch):
    evidence = _animate_evidence()
    checked = []

    class Run(_Pool):
        def cast(self, arg):
            return {k: v for k, v in evidence[0].items() if k != "verb"}

        def save(self, staged):
            return {"kept": "saved.D64", **{
                k: v for k, v in evidence[1].items() if k != "verb"}}

    original = A.validate_pool_party_spells

    def checked_validate(results):
        checked.append([r["verb"] for r in results])
        original(results)

    monkeypatch.setattr(A, "validate_pool_party_spells", checked_validate)
    rc, slot, out = _drive(tmp_path, monkeypatch,
                           ["load", "cast BRUTUS:ANIMATE DEAD", "save"], pool=Run)
    assert rc == 0 and slot.torn
    assert checked == [["load", "cast", "save"]]
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["completed"] is True


def test_pool_dispel_run_checks_the_saved_cleared_row_without_an_emulator(
        tmp_path, monkeypatch):
    _, after = _dispel_readings()

    class Run(_Pool):
        def cast(self, arg):
            return {"spell": "DISPEL MAGIC", "target": "BRUTUS", "slot": 5,
                    "row_after": after["effect_rows"][63],
                    "effect_rows_after": after["effect_rows"],
                    "party_after": after["party"]}

        def save(self, staged):
            rows = json.loads(json.dumps(after["effect_rows"]))
            rows[63][1] = 32
            return {"kept": "saved.D64", "effect_rows": rows,
                    "party": after["party"]}

    rc, slot, out = _drive(tmp_path, monkeypatch,
                           ["load", "cast ROLAND:DISPEL MAGIC>BRUTUS", "save"], pool=Run)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert rc == 1 and slot.torn
    assert "Dispel Magic row" in summary["lost"]


def test_saved_characters_reads_each_name_slot_and_memorised_list(tmp_path):
    from goldbox.savegame import load_save
    disk = _fixture_disk(tmp_path)
    got = A.saved_characters(disk)
    _, sg0, _ = load_save(D64.open(str(disk)))
    assert set(got) == {s.record.name.upper() for s in sg0.characters}
    assert all(set(v) == {"owner", "memorised"} for v in got.values())


def _seeding(slot, template):
    """Give a fake slot the real `seed_vicerc`, run over `template`."""
    from tools.registry import instance

    slot.port, slot.text_port = 6510, 6511
    slot.vicerc = pathlib.Path(slot.dir) / "vicerc"
    slot.seed_vicerc = lambda: instance.seed_vicerc(slot, template)
    slot.seed_vicerc()


@pytest.mark.parametrize("template", [
    "[C64SC]\nSound=0\nJoyDevice2=0\n[Other]\nX=1\n",
    "[C64SC]\nSound=0\n[Other]\nX=1\n",
    "[Other]\nX=1\n",
    "[Other]\nX=1\n[C64SC]\nSound=0\n",
])
def test_the_joystick_line_lands_in_the_c64sc_section_only(tmp_path, template):
    t = tmp_path / "template"
    t.write_text(template, encoding="utf-8")
    slot = _Slot(tmp_path)
    _seeding(slot, t)
    A.give_joystick(slot.vicerc)
    text = slot.vicerc.read_text(encoding="utf-8")
    sections = {}
    name = ""
    for line in text.splitlines():
        if line.startswith("["):
            name = line.strip("[]")
        sections.setdefault(name, []).append(line)
    assert sections["C64SC"].count("JoyDevice2=1") == 1
    assert text.count("JoyDevice2") == 1
    assert "X=1" in sections["Other"] and "JoyDevice2=1" not in sections["Other"]
    assert not list(tmp_path.glob("vicerc.tmp"))


def test_a_curse_run_with_cures_gives_the_slot_a_joystick_and_validates_them(
        tmp_path, monkeypatch):
    from types import SimpleNamespace

    from tools.curse_of_the_azure_bonds import curserun

    slot = _Slot(tmp_path)
    template = tmp_path / "template"
    template.write_text("[C64SC]\nSound=0\n[Other]\nX=1\n", encoding="utf-8")
    _seeding(slot, template)
    monkeypatch.setattr(A.runlog, "catch_signals", lambda: None)
    monkeypatch.setattr(A.S, "claim_slot", lambda *a, **k: slot)
    monkeypatch.setattr(A, "stage", lambda *a, **k: {"effects": [], "magic_items": []})
    monkeypatch.setattr(curserun, "stage", lambda *a, **k: slot.seed_vicerc() and "first")
    monkeypatch.setattr(curserun, "CurseSession", _Sess)
    evidence = _evidence()
    seen = []
    monkeypatch.setattr(A, "validate_curse_cures",
                        lambda results, path: seen.append((results[-1]["verb"], path)))

    class Run:
        joy = False

        def __init__(self, *a, **k):
            text = slot.vicerc.read_text(encoding="utf-8")
            seen.append("joystick at build: " + str(
                text.split("[C64SC]")[1].split("[Other]")[0].count("JoyDevice2=1\n")))

        def load(self):
            return {}

        def cast(self, arg):
            return {k: v for k, v in evidence[1].items() if k != "verb"}

        def cure(self, arg):
            return {k: v for k, v in evidence[2].items() if k != "verb"}

        def save(self, staged):
            return {"kept": "saved.D64", "effects": []}

        def reading(self):
            return {"effects": []}

        def capture(self, tag):
            pass

    monkeypatch.setattr(A, "CurseRun", Run)
    args = SimpleNamespace(title="curse", max_seconds=120, stage_row=[],
                           stage_trait=[], stage_item=[], stage_only=False,
                           checkpoint=[], pool=None, issue="671", run="joy",
                           disks="unused", joy=True)
    steps = ["load", "cast SHARA:CURE BLINDNESS>PHILIPPE", "cure MARK>LEDERA", "save"]
    assert A.run(args, A.parse_steps(steps), tmp_path / "evidence",
                 _fixture_disk(tmp_path)) == 0
    assert seen == ["joystick at build: 1",
                    ("save", "saved.D64")]


# --- the place a save holds, the walk judged by it, and the save's wait ---------------

def _moved_copy(tmp_path, src, dx=0, turn=0):
    """A copy of `src` with the party's square and facing moved in the payload,
    as the game's own resave after a walk would hold them."""
    image = D64.open(str(src))
    addr, body = split_load_address(image.read_file(POOL_OF_RADIANCE.save_file))
    body = bytearray(body)
    at = c64_save.CONTAINERS[POOL_OF_RADIANCE.key].position
    body[at] += dx
    body[at + 2] = (body[at + 2] + turn) % 4
    image.write_file_inplace(POOL_OF_RADIANCE.save_file,
                             addr.to_bytes(2, "little") + bytes(body))
    dest = tmp_path / f"moved-{dx}-{turn}.d64"
    image.save(str(dest))
    return dest


def _staged_fixture(tmp_path):
    src = _fixture_disk(tmp_path)
    return src, A.stage(src, tmp_path / "staged.d64", "pool-of-radiance")


def test_the_staged_place_is_kept_beside_the_bytes_written(tmp_path):
    _, staged = _staged_fixture(tmp_path)
    assert set(staged["place"]) == {"area", "x", "y", "facing"}


def test_a_save_read_reports_whether_the_place_changed(tmp_path):
    _, staged = _staged_fixture(tmp_path)
    same = A.decode_save(tmp_path / "staged.d64", staged)
    assert same["place_changed"] is False and same["facing_changed"] is False
    assert same["place_before"] == same["place_after"] == staged["place"]

    stepped = A.decode_save(_moved_copy(tmp_path, tmp_path / "staged.d64", dx=1), staged)
    assert stepped["place_changed"] is True
    assert stepped["place_after"]["x"] == staged["place"]["x"] + 1


def test_a_turn_changes_the_facing_and_not_the_place(tmp_path):
    _, staged = _staged_fixture(tmp_path)
    turned = A.decode_save(_moved_copy(tmp_path, tmp_path / "staged.d64", turn=1), staged)
    assert turned["place_changed"] is False and turned["facing_changed"] is True
    assert turned["place_after"]["facing"] == (staged["place"]["facing"] + 1) % 4


class WalkSession(FakeSession):
    """A party on a grid whose every move advances the clock, so the status
    line changes on a bump and `walk_one` answers True for all of them."""

    def __init__(self, x=5, y=5, facing=0, walls=(), doors=()):
        super().__init__({"world": _window({}, WORLD_BAR)}, {}, "world")
        self.x, self.y, self.facing, self.walls = x, y, facing, set(walls)
        self.doors = set(doors)
        self.clock = 0
        self.walk_refused = None
        self.pressed = []
        self.drift = 0
        self.prompts = 0
        self.settles = 0

    def position(self):
        return self.x, self.y, self.facing

    def combat_state(self, s=None):
        return A.S.Session.combat_state(self, s)

    def handle_prompt(self, s=None):
        self.prompts += 1
        return False

    def settle(self, seconds=0):
        self.settles += 1

    def wanted_disk(self, s):
        return "SIDE2.D64" if "INSERT SIDE" in s.row(24) else None

    def walk_one(self, move, *a, **k):
        self.pressed.append(move)
        self.clock += 1
        if move in ("I", "M"):
            # `M` tries the edge behind the facing: open, it steps back and
            # keeps the facing; an open door there, it steps back and reverses
            # the facing; a wall there, it stays and reverses the facing.
            facing = self.facing if move == "I" else (self.facing + 2) % 4
            dx, dy = ((0, -1), (1, 0), (0, 1), (-1, 0))[facing]
            if (self.x + dx, self.y + dy) not in self.walls:
                self.x, self.y = self.x + dx, self.y + dy
                if move == "M" and (self.x, self.y) in self.doors:
                    self.facing = (self.facing + 2) % 4
            elif move == "M":
                self.facing = (self.facing + 2) % 4
        else:
            self.facing = (self.facing + {"J": -1, "K": 1}[move]) % 4
        self.facing = (self.facing + self.drift) % 4
        return True


def _walk_run(tmp_path, sess, clock):
    run, log = _pool_run(tmp_path, sess)
    run.clock = clock
    return run, log


def test_walk_one_step_moves_one_square_judged_by_the_square(tmp_path, monkeypatch):
    sess = WalkSession()
    run, log = _walk_run(tmp_path, sess, _Clock(monkeypatch))
    got = run.walk("I")
    log.close()
    assert got["position"] == [5, 4, 0] and got["squares_moved"] == 1
    assert got["blocked"] == [] and got["asked_forward"] == 1


def test_a_bump_that_ticks_the_clock_is_blocked_and_not_a_step(tmp_path, monkeypatch):
    sess = WalkSession(walls={(5, 4)})
    run, log = _walk_run(tmp_path, sess, _Clock(monkeypatch))
    got = run.walk("I")
    log.close()
    assert sess.pressed == ["I"]
    assert got["moves"][0]["status_moved"] is True
    assert got["blocked"] == [0] and got["squares_moved"] == 0
    assert got["position"] == [5, 5, 0]


def test_walk_k_is_the_control_it_turns_and_stays_on_the_square(tmp_path, monkeypatch):
    sess = WalkSession()
    run, log = _walk_run(tmp_path, sess, _Clock(monkeypatch))
    got = run.walk("K")
    log.close()
    assert got["position"] == [5, 5, 1] and got["squares_moved"] == 0
    assert got["asked_forward"] == 0 and got["expected_facing"] == 1


def test_a_turn_that_leaves_the_wrong_facing_is_lost(tmp_path, monkeypatch):
    sess = WalkSession()
    sess.drift = 1
    run, log = _walk_run(tmp_path, sess, _Clock(monkeypatch))
    with pytest.raises(A.StepFailed, match="should leave the party facing 1"):
        run.walk("K")
    log.close()


_FACING_STEP = ((0, -1), (1, 0), (0, 1), (-1, 0))


def _m_outcome(tmp_path):
    events = [json.loads(line) for line in
              (tmp_path / "run.jsonl").read_text().splitlines()]
    return [e["m_outcome"] for e in events if e["kind"] == "move"]


@pytest.mark.parametrize("facing", range(4))
def test_walk_m_steps_backward_and_keeps_the_facing(tmp_path, monkeypatch, facing):
    """With no wall art or door behind the party `M` steps one square back and
    keeps the facing it started with."""
    sess = WalkSession(x=3, y=7, facing=facing)
    run, log = _walk_run(tmp_path, sess, _Clock(monkeypatch))
    got = run.walk("M")
    log.close()
    dx, dy = _FACING_STEP[(facing + 2) % 4]
    assert got["position"] == [3 + dx, 7 + dy, facing]
    assert got["squares_moved"] == 1 and got["asked_forward"] == 0
    assert got["expected_facing"] == facing
    assert _m_outcome(tmp_path) == ["back-kept"]


@pytest.mark.parametrize("facing", range(4))
def test_walk_m_through_an_open_door_steps_back_and_reverses_the_facing(
        tmp_path, monkeypatch, facing):
    """With an open door behind the party `M` steps one square back and the
    facing reverses too."""
    dx, dy = _FACING_STEP[(facing + 2) % 4]
    sess = WalkSession(x=3, y=7, facing=facing, doors={(3 + dx, 7 + dy)})
    run, log = _walk_run(tmp_path, sess, _Clock(monkeypatch))
    got = run.walk("M")
    log.close()
    assert got["position"] == [3 + dx, 7 + dy, (facing + 2) % 4]
    assert got["squares_moved"] == 1
    assert got["expected_facing"] == (facing + 2) % 4
    assert _m_outcome(tmp_path) == ["back-reversed"]


@pytest.mark.parametrize("facing", range(4))
def test_walk_m_held_by_wall_art_reverses_the_facing(tmp_path, monkeypatch, facing):
    """With wall art behind the party `M` stays on the square and reverses the
    facing."""
    dx, dy = _FACING_STEP[(facing + 2) % 4]
    sess = WalkSession(x=3, y=7, facing=facing, walls={(3 + dx, 7 + dy)})
    run, log = _walk_run(tmp_path, sess, _Clock(monkeypatch))
    got = run.walk("M")
    log.close()
    assert got["position"] == [3, 7, (facing + 2) % 4]
    assert got["squares_moved"] == 0
    assert got["expected_facing"] == (facing + 2) % 4
    assert _m_outcome(tmp_path) == ["turned"]


class BrokenMSession(WalkSession):
    """Fakes `M` outcomes the engine never produces: sideways, two squares
    back, and staying put while keeping the facing."""

    def __init__(self, break_mode, **kw):
        super().__init__(**kw)
        self.break_mode = break_mode

    def walk_one(self, move, *a, **k):
        self.pressed.append(move)
        self.clock += 1
        if move == "M":
            back = _FACING_STEP[(self.facing + 2) % 4]
            side = _FACING_STEP[(self.facing + 1) % 4]
            if self.break_mode == "sideways":
                self.x, self.y = self.x + side[0], self.y + side[1]
            elif self.break_mode == "two_back":
                self.x, self.y = self.x + 2 * back[0], self.y + 2 * back[1]
        return True


def test_walk_m_that_leaves_a_facing_neither_kept_nor_reversed_is_lost(
        tmp_path, monkeypatch):
    """`M` may end facing only where it started or exactly reversed; anything
    else is a glitch the walk must catch."""
    sess = WalkSession(x=3, y=7)
    sess.drift = 1
    run, log = _walk_run(tmp_path, sess, _Clock(monkeypatch))
    with pytest.raises(A.StepFailed, match="should face 0 or 2, it faces 1"):
        run.walk("M")
    log.close()


@pytest.mark.parametrize("facing", range(4))
def test_walk_m_that_moves_sideways_is_lost(tmp_path, monkeypatch, facing):
    sess = BrokenMSession("sideways", x=3, y=7, facing=facing)
    run, log = _walk_run(tmp_path, sess, _Clock(monkeypatch))
    with pytest.raises(A.StepFailed, match="not one square behind"):
        run.walk("M")
    log.close()


@pytest.mark.parametrize("facing", range(4))
def test_walk_m_that_moves_two_squares_is_lost(tmp_path, monkeypatch, facing):
    sess = BrokenMSession("two_back", x=3, y=7, facing=facing)
    run, log = _walk_run(tmp_path, sess, _Clock(monkeypatch))
    with pytest.raises(A.StepFailed, match="not one square behind"):
        run.walk("M")
    log.close()


@pytest.mark.parametrize("facing", range(4))
def test_walk_m_that_stays_put_and_keeps_the_facing_is_lost(
        tmp_path, monkeypatch, facing):
    """A held square must reverse the facing, never keep it."""
    sess = BrokenMSession("held_and_kept", x=3, y=7, facing=facing)
    run, log = _walk_run(tmp_path, sess, _Clock(monkeypatch))
    with pytest.raises(
            A.StepFailed,
            match=f"should reverse facing to {(facing + 2) % 4}, it faces {facing}"):
        run.walk("M")
    log.close()


class PressSession(WalkSession):
    """A `walk_one` that honours `tries` as the base does: it presses again
    while nothing changed, and `script` says what each press does."""

    def __init__(self, script, **kw):
        super().__init__(**kw)
        self.script = list(script)

    def walk_one(self, move, *a, tries=4, **k):
        for _ in range(tries):
            self.pressed.append(move)
            changed = self.script.pop(0)(self)
            if changed:
                return True
        return False


def _gateway_text(sess):
    sess.screens["world"] = _window({17: "THE WEST GATEWAY OPENS"}, WORLD_BAR)
    return False


def _step_off_the_map(sess):
    sess.x, sess.y = 15, 4
    return True


def _nothing(sess):
    return False


def _step(sess):
    sess.y -= 1
    sess.clock += 1
    return True


def test_a_move_that_puts_up_text_is_pressed_once(tmp_path, monkeypatch):
    sess = PressSession([_gateway_text, _step_off_the_map], x=0, y=4, facing=3)
    run, log = _walk_run(tmp_path, sess, _Clock(monkeypatch))
    got = run.walk("I")
    log.close()
    assert sess.pressed == ["I"]
    assert got["blocked"] == [0] and got["position"] == [0, 4, 3]


def test_a_key_the_game_did_not_take_is_sent_once_more(tmp_path, monkeypatch):
    sess = PressSession([_nothing, _step], x=5, y=5, facing=0)
    run, log = _walk_run(tmp_path, sess, _Clock(monkeypatch))
    got = run.walk("I")
    log.close()
    assert sess.pressed == ["I", "I"]
    assert got["moves"][0]["resent"] is True and got["squares_moved"] == 1


def test_a_move_that_brings_up_a_disk_prompt_fails_the_walk_and_answers_nothing(
        tmp_path, monkeypatch):
    def prompt(sess):
        sess.screens["world"] = _window({}, "INSERT SIDE # 2, AND PRESS ANY KEY.")
        return True

    sess = PressSession([prompt], x=0, y=4, facing=3)
    run, log = _walk_run(tmp_path, sess, _Clock(monkeypatch))
    with pytest.raises(A.StepFailed, match="ran the square's event"):
        run.walk("I")
    log.close()
    assert sess.prompts == 0 and sess.settles == 0
    assert sess.pressed == ["I"]


class _Text:
    """A screen of rows, with the reads `Session.walk_one` makes of one."""

    def __init__(self, rows):
        self._rows = rows

    def row(self, r):
        return self._rows[r]

    def text(self):
        return "\n".join(self._rows)

    def contains(self, needle):
        return needle in self.text()


class RealWalk(A.S.Session):
    """The real `Session.walk_one`, `leave_move` and `select_bar` over a screen
    that the test's clock moves: `prompt_after` is how many seconds after the
    move key the disk prompt goes up (None for never)."""

    PROMPT = "INSERT SIDE # 2, AND PRESS ANY KEY."

    def __init__(self, clock, prompt_after=0.0, x=5, y=5, facing=0):
        self.clock = clock
        self.prompt_after = prompt_after
        self.x, self.y, self.facing = x, y, facing
        self.keyed_at = None
        self.returned_at = None
        self.keys, self.kernal, self.attaches = [], [], []
        self.here, self.attached = "/slot", "/slot/SIDE1.D64"
        self.save_disk = "/slot/SIDE0.D64"
        self._last_prompt = 0.0
        self.bar = WORLD_BAR
        self.ticks = 0
        self.moved_by = 0.0     # how long `position` takes, as the clock sees it

        class Kbd:
            def key(kself, name, *timing):
                self.keys.append(name)
                if name in ("i", "j", "k", "m"):
                    if self.keyed_at is None:
                        self.keyed_at = self.clock.now
                    self.ticks += 1
                    if name == "i":
                        self.y -= 1
                elif name == "Return":
                    self.bar = WORLD_BAR
                    self.returned_at = self.clock.now

            def screenshot(kself, path):
                pathlib.Path(path).write_bytes(b"")
                return True

        self.kbd = Kbd()

    def screen(self):
        up = (self.prompt_after is not None and self.keyed_at is not None
              and self.clock.now >= self.keyed_at + self.prompt_after)
        return _Text(_window({}, self.PROMPT if up else self.bar))

    def indoors(self):
        return True

    def live_triple(self):
        return (self.x, self.y, self.facing)

    def select_bar(self, label, row=24, timeout=30.0, answer_prompts=True):
        """`MOVE` chosen; the highlight walk itself is `test_sideprompt.py`'s."""
        self.bar = A.S.MOVE_SUBBAR
        return True

    def status(self):
        return self.ticks

    def position(self):
        self.clock.advance(self.moved_by)
        return self.x, self.y, self.facing

    def attach(self, path, unit=8, settle=None):
        self.attaches.append(path)

    def press_kernal(self, code, *a, **k):
        self.kernal.append(code)

    def await_change(self, text, timeout=6.0):
        return False

    def log(self, *a):
        pass

    def settle(self, seconds=0):
        pass


class ScriptedMoveWalk(RealWalk):
    """Taking `MOVE` prints the square's text at once and brings up `I,J,K,M`
    1.5 s later; a direction key before then is lost, as `drop_next` more are
    even at the sub-bar."""

    TEXT = "YOU ARE BY THE GATEWAY TO THE"
    DX = {0: (0, -1), 1: (1, 0), 2: (0, 1), 3: (-1, 0)}

    def __init__(self, clock, drop_next=0, taken_clears_text=False,
                 tickless=False, **kw):
        super().__init__(clock, prompt_after=None, **kw)
        self.taken_clears_text = taken_clears_text
        self.tickless = tickless
        self.subbar_at = None
        self.text_up = False
        self.drop_next = drop_next
        self.lost = []

        class Kbd:
            def key(kself, name, *timing):
                self.keys.append(name)
                if name == "Return":
                    self.subbar_at, self.text_up = None, False
                    self.returned_at = self.clock.now
                elif name in ("i", "j", "k", "m"):
                    ready = (self.subbar_at is not None
                             and self.clock.now >= self.subbar_at)
                    if not ready or self.drop_next:
                        if ready:
                            self.drop_next -= 1
                        self.lost.append(name)
                        return
                    if self.taken_clears_text:
                        self.text_up = False
                    if self.tickless:
                        return
                    self.ticks += 1
                    if name == "k":
                        self.facing = (self.facing + 1) % 4
                    elif name == "i":
                        dx, dy = self.DX[self.facing]
                        self.x, self.y = self.x + dx, self.y + dy

            def screenshot(kself, path):
                pathlib.Path(path).write_bytes(b"")
                return True

        self.kbd = Kbd()

    def select_bar(self, label, row=24, timeout=30.0, answer_prompts=True):
        self.text_up = True
        self.subbar_at = self.clock.now + 1.5
        return True

    def screen(self):
        up = self.subbar_at is not None and self.clock.now >= self.subbar_at
        return _Text(_window({17: self.TEXT} if self.text_up else {},
                             A.S.MOVE_SUBBAR if up else WORLD_BAR))

    def status(self):
        return self.ticks, self.facing

    def position(self):
        return self.x, self.y, self.facing


def _scripted_walk(tmp_path, monkeypatch, **kw):
    clock = _Clock(monkeypatch)
    sess = ScriptedMoveWalk(clock, x=0, y=4, facing=3, **kw)
    run, log = _walk_run(tmp_path, sess, clock)
    return sess, run, log


def _move_records(tmp_path):
    rows = [json.loads(line) for line in
            (tmp_path / "run.jsonl").read_text().splitlines()]
    return [r for r in rows if r.get("kind") == "move"]


def test_a_turn_on_a_square_whose_text_comes_up_with_move_is_pressed_at_the_subbar(
        tmp_path, monkeypatch):
    sess, run, log = _scripted_walk(tmp_path, monkeypatch)
    got = run.walk("KI")
    log.close()
    assert got["position"] == [0, 3, 0]
    assert _move_records(tmp_path)[0]["after"] == [0, 4, 0]
    assert sess.keys == ["k", "Return", "i", "Return"] and sess.lost == []
    assert not any(m["resent"] for m in got["moves"])


def test_a_key_lost_at_the_subbar_is_resent_although_move_put_up_text(
        tmp_path, monkeypatch):
    sess, run, log = _scripted_walk(tmp_path, monkeypatch, drop_next=1)
    got = run.walk("K")
    log.close()
    assert got["moves"][0]["resent"] is True
    assert got["position"][2] == 0
    assert sess.lost == ["k"] and sess.keys.count("k") == 2


def test_a_key_the_game_took_is_not_resent_when_only_the_text_box_changed(
        tmp_path, monkeypatch):
    # The key was read (the text cleared) but the status line did not move.
    # Judged by the whole move's screen, as before, this would be resent.
    sess, run, log = _scripted_walk(tmp_path, monkeypatch,
                                    taken_clears_text=True, tickless=True)
    with pytest.raises(A.StepFailed, match="should leave the party facing"):
        run.walk("K")
    log.close()
    assert _move_records(tmp_path)[0]["resent"] is False
    assert sess.keys.count("k") == 1 and sess.lost == []


def test_a_walk_that_hits_the_deadline_while_waiting_for_the_subbar_presses_nothing(
        tmp_path, monkeypatch):
    sess, run, log = _scripted_walk(tmp_path, monkeypatch)
    sess.select_bar = lambda *a, **k: (setattr(sess, "text_up", True),
                                       setattr(sess, "subbar_at", 1000.0), True)[2]
    run.deadline = 3.0
    with pytest.raises(A.StepFailed, match="seconds were spent"):
        run.walk("I")
    log.close()
    assert "i" not in sess.keys
    assert run.clock() < 5.0, "the wait ran on past the run's deadline"


def test_a_refused_walk_writes_its_move_record_with_keyed_false(
        tmp_path, monkeypatch):
    sess, run, log = _scripted_walk(tmp_path, monkeypatch)
    sess.select_bar = lambda *a, **k: (setattr(sess, "subbar_at", 1000.0), True)[1]
    with pytest.raises(A.StepFailed, match="pressed nothing"):
        run.walk("I")
    log.close()
    recs = _move_records(tmp_path)
    assert [r["keyed"] for r in recs] == [False]


def test_the_move_record_keeps_the_text_the_game_showed_at_the_key(
        tmp_path, monkeypatch):
    sess, run, log = _scripted_walk(tmp_path, monkeypatch)
    run.walk("K")
    log.close()
    rec = _move_records(tmp_path)[0]
    assert ScriptedMoveWalk.TEXT in " ".join(rec["text"]) and rec["keyed"] is True


def _real_walk(tmp_path, monkeypatch, **kw):
    clock = _Clock(monkeypatch)
    sess = RealWalk(clock, **kw)
    run, log = _walk_run(tmp_path, sess, clock)
    return sess, run, log


class TempleQuestionWalk(RealWalk):
    """A step onto a square that asks `DO YOU SEEK HEALING?`: after the last
    `i` the screen is the question over `YES NO` and the status line has not
    moved, so a Return would answer YES."""

    QUESTION = "SUNE.' DO YOU SEEK HEALING?'"

    def __init__(self, clock, **kw):
        super().__init__(clock, prompt_after=None, **kw)
        self.asked = False
        base = self.kbd.key

        class Kbd:
            def key(kself, name, *timing):
                if name == "i":
                    self.asked = True
                    self.keys.append(name)
                    self.keyed_at = self.clock.now
                    return
                base(name, *timing)

            screenshot = self.kbd.screenshot

        self.kbd = Kbd()

    def screen(self):
        if self.asked:
            return _Text(_window({21: self.QUESTION}, "YES NO"))
        return super().screen()


def test_a_step_onto_a_question_square_fails_the_walk_and_answers_nothing(
        tmp_path, monkeypatch):
    clock = _Clock(monkeypatch)
    sess = TempleQuestionWalk(clock)
    run, log = _walk_run(tmp_path, sess, clock)
    with pytest.raises(A.StepFailed, match="YES NO"):
        run.walk("I")
    log.close()
    assert sess.keys == ["i"] and sess.kernal == []
    record = _move_records(tmp_path)[-1]
    assert record["keyed"] is True
    assert TempleQuestionWalk.QUESTION in " ".join(record["stop_screen"])


def test_pool_fight_asks_the_walk_to_take_an_encounter_menu_only_while_it_walks():
    seen = []

    class Session:
        walk_encounter = None
        combat = False

        def in_combat(self):
            return self.combat

        def walk_one(self, move):
            seen.append(self.walk_encounter)
            self.combat = True

        def handle_prompt(self):
            pass

        def fight(self, *, budget, tactic):
            return A.S.FightResult(A.S.WON, 1, 1.0, [], [])

    run = A.PoolRun.__new__(A.PoolRun)
    run.sess = Session()
    run.to_world = lambda: True
    run.spent = lambda: False
    run.capture = lambda name: None
    run.fight("60", "I", 5)
    assert seen == [A.S.ENCOUNTER_FIGHT]
    assert run.sess.walk_encounter is None


def test_the_real_walk_one_does_not_answer_a_prompt_the_move_raised(
        tmp_path, monkeypatch):
    sess, run, log = _real_walk(tmp_path, monkeypatch, prompt_after=0.0)
    with pytest.raises(A.StepFailed, match="ran the square's event"):
        run.walk("I")
    log.close()
    assert sess.keys == ["i"], "a Return or a space went to the prompt"
    assert sess.kernal == [] and sess.attaches == []


class PromptAfterLookWalk(RealWalk):
    """The disk prompt goes up on the first screen read after `_walk`'s own
    `walk_stop(wait=12.0)` returns, which follows its look loop, so the prompt
    opens after the look and before the next move, whatever the clock.
    `walk_one`'s own `walk_stop` calls pass no `wait`."""

    def __init__(self, clock, **kw):
        super().__init__(clock, prompt_after=None, **kw)
        self.look_over = False

    def walk_stop(self, s=None, wait=0.0):
        got = super().walk_stop(s, wait)
        if wait:
            self.look_over = True
        return got

    def screen(self):
        if self.look_over:
            return _Text(_window({}, self.PROMPT))
        return super().screen()


def test_a_prompt_that_opens_after_the_look_is_not_answered_by_the_next_move(
        tmp_path, monkeypatch):
    # The first move ends by leaving move mode; the prompt opens after the
    # look window, so only the check before the next move can see it.
    clock = _Clock(monkeypatch)
    sess = PromptAfterLookWalk(clock)
    run, log = _walk_run(tmp_path, sess, clock)
    with pytest.raises(A.StepFailed, match="move 0 \\(I\\).*before the next move"):
        run.walk("II")
    log.close()
    assert sess.keys == ["i", "Return"], sess.keys
    assert sess.kernal == [] and sess.attaches == []


def test_a_prompt_that_opens_while_the_end_is_read_fails_the_walk(
        tmp_path, monkeypatch):
    sess, run, log = _real_walk(tmp_path, monkeypatch, prompt_after=4.0)
    sess.moved_by = 3.0
    with pytest.raises(A.StepFailed, match="ran the square's event"):
        run.walk("I")
    log.close()
    assert sess.kernal == [] and sess.attaches == []


def _look_run(tmp_path, monkeypatch, after_return):
    """A walk whose prompt opens `after_return` seconds after the key that
    left move mode, which is when `walk_one` returns."""
    sess, run, log = _real_walk(tmp_path, monkeypatch, prompt_after=None)
    real_key = sess.kbd.key

    def key(name, *timing):
        real_key(name, *timing)
        if name == "Return":
            sess.prompt_after = None
            sess.prompt_at = sess.clock.now + 0.6 + after_return

    sess.kbd.key = key
    real_screen = sess.screen

    def screen():
        at = getattr(sess, "prompt_at", None)
        if at is not None and sess.clock.now >= at:
            return _Text(_window({}, sess.PROMPT))
        return real_screen()

    sess.screen = screen
    return sess, run, log


def test_the_look_lasts_two_seconds_from_both_sides(tmp_path, monkeypatch):
    sess, run, log = _look_run(tmp_path, monkeypatch, 1.7)
    with pytest.raises(A.StepFailed, match="ran the square's event"):
        run.walk("I")
    log.close()
    sess, run, log = _look_run(tmp_path, monkeypatch, 2.6)
    assert run.walk("I")["squares_moved"] == 1
    log.close()


def test_a_move_on_the_travel_grid_is_not_re_sent(tmp_path, monkeypatch):
    sess, run, log = _real_walk(tmp_path, monkeypatch, prompt_after=None)
    sess.indoors = lambda: False
    pressed = []
    sess.walk_outdoors = lambda move, hold, gap: pressed.append(move) or False
    run.walk("I")
    log.close()
    assert pressed == ["I"]


def test_a_forward_move_that_lands_off_the_next_square_fails_the_walk(
        tmp_path, monkeypatch):
    sess = PressSession([_step_off_the_map], x=0, y=4, facing=3)
    run, log = _walk_run(tmp_path, sess, _Clock(monkeypatch))
    with pytest.raises(A.StepFailed, match="not one square ahead"):
        run.walk("I")
    log.close()


def test_every_key_is_logged_with_its_time(tmp_path, monkeypatch):
    sess = WalkSession()
    run, log = _walk_run(tmp_path, sess, _Clock(monkeypatch))
    run.walk("KI")
    log.close()
    moves = [json.loads(line) for line in
             (tmp_path / "run.jsonl").read_text().splitlines()]
    moves = [m for m in moves if m["kind"] == "move"]
    assert [m["move"] for m in moves] == ["K", "I"]
    assert all(m["t"] > 0 and "row24" in m for m in moves)


@pytest.mark.parametrize("arg", ["", "X", "IQ", "walk"])
def test_a_walk_of_anything_but_the_four_moves_is_refused(arg):
    with pytest.raises(ValueError):
        A.parse_steps(["load", f"walk {arg}".strip()])


def _walked(route, moved, position, blocked=()):
    return {"verb": "walk", "route": route, "asked_forward": route.count("I"),
            "squares_moved": int(moved),
            "position": position, "blocked": list(blocked)}


def _saved(before, after):
    return {"verb": "save", **A.place_verdict(before, after)}


P = {"area": 0, "x": 5, "y": 5, "facing": 0}


def test_a_forward_walk_whose_saved_square_is_the_staged_one_is_lost():
    results = [_walked("I", False, [5, 5, 0], blocked=[0]), _saved(P, P)]
    with pytest.raises(A.StepFailed, match="did not move.*blocked at moves \\[0\\]"):
        A.validate_walks(results)


def test_a_forward_walk_and_a_saved_square_one_on_pass():
    after = {**P, "y": 4}
    A.validate_walks([_walked("I", True, [5, 4, 0]), _saved(P, after)])


def test_the_turn_control_passes_when_the_square_is_the_same_and_fails_when_it_is_not():
    turned = {**P, "facing": 1}
    A.validate_walks([_walked("K", False, [5, 5, 1]), _saved(P, turned)])
    with pytest.raises(A.StepFailed, match="only turns were asked"):
        A.validate_walks([_walked("K", False, [5, 5, 1]),
                          _saved(P, {**turned, "y": 4})])


def test_a_walk_m_that_stepped_back_passes_the_save_check(tmp_path, monkeypatch):
    sess = WalkSession(x=3, y=12, facing=3)
    run, log = _walk_run(tmp_path, sess, _Clock(monkeypatch))
    walked = run.walk("M")
    log.close()
    before = {"area": 1, "x": 3, "y": 12, "facing": 3}
    after = {**before, "x": walked["position"][0], "y": walked["position"][1]}
    assert after["x"] == 4
    A.validate_walks([{"verb": "walk", **walked}, _saved(before, after)])


def test_a_walk_m_that_held_still_does_not_excuse_a_moved_save():
    held = {**_walked("M", False, [5, 5, 2]), "back_moved": 0}
    with pytest.raises(A.StepFailed, match="only turns were asked"):
        A.validate_walks([held, _saved(P, {**P, "y": 4, "facing": 2})])


def test_a_route_that_returns_to_its_start_passes_when_the_save_agrees():
    A.validate_walks([_walked("IMI", True, [5, 5, 0]), _saved(P, P)])


def test_a_route_that_returns_to_its_start_fails_when_the_save_differs():
    with pytest.raises(A.StepFailed, match="the screen showed"):
        A.validate_walks([_walked("IMI", True, [5, 5, 0]), _saved(P, {**P, "y": 3})])


def test_the_saved_place_must_be_the_one_the_screen_showed():
    with pytest.raises(A.StepFailed, match="the screen showed"):
        A.validate_walks([_walked("I", True, [5, 4, 0]), _saved(P, {**P, "y": 3})])


def test_a_walk_with_no_save_after_it_is_lost():
    with pytest.raises(A.StepFailed, match="no save was read"):
        A.validate_walks([_walked("I", True, [5, 4, 0])])


class _WalkedPool(_Pool):
    def walk(self, arg):
        return _walked("I", False, [5, 5, 0], blocked=[0])

    def save(self, staged):
        return {"kept": "x", **A.place_verdict(P, P)}


def test_a_run_whose_walk_did_not_move_the_saved_party_exits_one(tmp_path, monkeypatch):
    rc, _, out = _drive(tmp_path, monkeypatch, ["load", "walk I", "save"], 1e9,
                        pool=_WalkedPool)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert rc == 1 and not summary["completed"]
    assert summary["lost"].startswith("did not move")


# --- the save's wait ---------------------------------------------------------------

class SaveFake(FakeSession):
    """Curse's camp with a write that shows `SAVING GAME` for a while."""

    def __init__(self, writing_polls=4):
        super().__init__({}, {}, "camp")
        self.polls = writing_polls
        self.log = []
        self.save_disk = "SIDE0.D64"

    def save_game(self, *a):
        raise AssertionError("the fixed-sleep save_game was used")

    def bar_now(self):
        return {"camp": "ENCAMP:SAVE VIEW MAGIC REST ALTER FIX EXIT",
                "save": "SAVE GAME  EXIT", "writing": "",
                "back": "ENCAMP:SAVE VIEW MAGIC REST ALTER FIX EXIT"}[self.state]

    def screen(self):
        if self.state == "writing":
            self.polls -= 1
            if self.polls <= 0:
                self.state = "back"
        rows = _window({10: "SAVING GAME..."} if self.state == "writing" else {},
                       self.bar_now())
        return FakeScreen(rows)

    def wait_bar(self, word, timeout=0):
        for _ in range(50):
            if word in self.screen().row(24):
                return True
        return False

    def wait_text(self, needle, timeout=0):
        for _ in range(50):
            s = self.screen()
            if any(needle in s.row(r) for r in range(25)):
                return needle, s
        return None, None

    def press_bar(self, label, row=24, timeout=0):
        self.log.append(("press", label))
        self.state = {"SAVE": "save", "SAVE GAME": "writing"}.get(label, self.state)
        return True

    def attach(self, path):
        self.log.append(("attach", path))


def _save_run(tmp_path, sess):
    run = A.CurseRun.__new__(A.CurseRun)
    run.sess = sess
    run.out = tmp_path
    run.log = A.Log(tmp_path)
    run.shots = 0
    run.game = POOL_OF_RADIANCE
    run.to_world = lambda tries=10: True
    return run


def test_a_curse_save_copies_only_after_saving_game_is_gone_and_the_camp_bar_is_back(
        tmp_path, monkeypatch):
    _, staged = _staged_fixture(tmp_path)
    sess = SaveFake()
    run = _save_run(tmp_path, sess)
    seen = []

    def copy(src, dest, **kw):
        s = sess.screen()
        seen.append((s.row(24).strip(), any("SAVING GAME" in s.row(r) for r in range(25)), kw))
        dest.write_bytes((tmp_path / "staged.d64").read_bytes())
        return "copied"

    monkeypatch.setattr(A.S, "copy_closed_disk", copy)
    try:
        got = run.save(staged)
    finally:
        run.log.close()
    assert seen == [("ENCAMP:SAVE VIEW MAGIC REST ALTER FIX EXIT", False,
                     {"attempts": 30, "backoff": 1.0})]
    assert sess.log == [("press", "SAVE"), ("attach", "SIDE0.D64"),
                        ("press", "SAVE GAME")]
    assert got["place_changed"] is False


def test_a_curse_save_that_never_shows_saving_game_is_lost_before_any_copy(
        tmp_path, monkeypatch):
    sess = SaveFake()
    sess.wait_text = lambda needle, timeout=0: (None, None)
    run = _save_run(tmp_path, sess)
    monkeypatch.setattr(A.S, "copy_closed_disk",
                        lambda *a, **k: pytest.fail("a disk was copied"))
    try:
        with pytest.raises(A.StepFailed, match="SAVING GAME never came up"):
            run.write_save()
    finally:
        run.log.close()


def test_a_curse_save_with_saving_game_still_up_at_the_camp_bar_is_lost_before_any_copy(
        tmp_path, monkeypatch):
    class Lingering(SaveFake):
        def screen(self):
            s = super().screen()
            if self.state == "back":
                return FakeScreen(_window({10: "SAVING GAME..."}, self.bar_now()))
            return s

    run = _save_run(tmp_path, Lingering())
    monkeypatch.setattr(A.S, "copy_closed_disk",
                        lambda *a, **k: pytest.fail("a disk was copied"))
    try:
        with pytest.raises(A.StepFailed, match="still up when the camp bar returned"):
            run.write_save()
    finally:
        run.log.close()


def _events(tmp_path, *kinds):
    events = [json.loads(line) for line in
              (tmp_path / "run.jsonl").read_text(encoding="utf-8").splitlines()]
    return [e for e in events if e["kind"] in kinds]


def test_a_curse_save_records_rows_18_and_24_on_every_change(tmp_path):
    run = _save_run(tmp_path, SaveFake())
    try:
        run.write_save()
    finally:
        run.log.close()
    watch = _events(tmp_path, "save-watch")
    assert [w["row24"] for w in watch] == [
        "ENCAMP:SAVE VIEW MAGIC REST ALTER FIX EXIT", "SAVE GAME  EXIT", "",
        "ENCAMP:SAVE VIEW MAGIC REST ALTER FIX EXIT"]
    for w in watch:
        assert "t" in w and "png_ms" in w and "row18" in w
        assert list(tmp_path.glob(f"{w['stem']}-save-watch-{w['n']}.txt"))
        assert list(tmp_path.glob(f"{w['stem']}-save-watch-{w['n']}.png"))


def test_a_curse_save_records_every_key_and_attach_and_restores_the_session(tmp_path):
    class Keying(SaveFake):
        def press_bar(self, label, row=24, timeout=0):
            self.kbd.key("Return")
            return super().press_bar(label, row, timeout)

    class Keys:
        def __init__(self):
            self.sent = []

        def key(self, name, *timing):
            self.sent.append(name)

        def screenshot(self, path):
            pathlib.Path(path).write_bytes(b"")

    sess = Keying()
    sess.kbd = Keys()
    run = _save_run(tmp_path, sess)
    try:
        run.write_save()
    finally:
        run.log.close()
    order = [(e["kind"], e.get("key") or e.get("image"))
             for e in _events(tmp_path, "save-key", "save-attach")]
    assert order == [("save-key", "Return"), ("save-attach", "SIDE0.D64"),
                     ("save-key", "Return")]
    assert sess.kbd.sent == ["Return", "Return"]
    for name in ("screen", "press_kernal", "attach"):
        assert name not in vars(sess)
    assert "key" not in vars(sess.kbd)


@pytest.mark.parametrize("exc", [RuntimeError("drive still open"),
                                 OSError("disk unreadable")])
def test_a_lost_save_whose_disk_copy_fails_is_still_lost_the_same_way(
        tmp_path, monkeypatch, exc):
    class NoBar(SaveFake):
        def press_bar(self, label, row=24, timeout=0):
            self.state = "writing"
            return True

    def copy(src, dest, **kw):
        raise exc

    monkeypatch.setattr(A.S, "copy_closed_disk", copy)
    run = _save_run(tmp_path, NoBar())
    try:
        with pytest.raises(A.StepFailed, match="SAVE GAME never appeared on row 24"):
            run.write_save()
    finally:
        run.log.close()
    (lost,) = _events(tmp_path, "lost-copy")
    assert lost["error"] == type(exc).__name__ and lost["why"] == str(exc)


def test_a_change_of_row_18_alone_is_recorded(tmp_path):
    class Prompting(SaveFake):
        seen = 0

        def screen(self):
            s = super().screen()
            self.seen += 1
            if self.state == "camp" and self.seen == 2:
                return FakeScreen(_window({18: "INSERT YOUR SAVE GAME DISK"},
                                          self.bar_now()))
            return s

    run = _save_run(tmp_path, Prompting())
    try:
        run.write_save()
    finally:
        run.log.close()
    watch = _events(tmp_path, "save-watch")
    assert "INSERT YOUR SAVE GAME DISK" in watch[0]["row18"]
    assert watch[0]["row24"] == "ENCAMP:SAVE VIEW MAGIC REST ALTER FIX EXIT"


def test_the_watch_is_undone_when_the_save_raises(tmp_path):
    sess = SaveFake()
    sess.wait_text = lambda needle, timeout=0: (None, None)
    run = _save_run(tmp_path, sess)
    try:
        with pytest.raises(A.StepFailed):
            run.write_save()
    finally:
        run.log.close()
    assert "screen" not in vars(sess) and "attach" not in vars(sess)


def test_a_save_whose_bar_never_comes_keeps_watching_to_the_camp_bar_then_is_lost(
        tmp_path, monkeypatch):
    class NoBar(SaveFake):
        def press_bar(self, label, row=24, timeout=0):
            self.log.append(("press", label))
            self.state = "writing"
            return True

    copied = []
    monkeypatch.setattr(A.S, "copy_closed_disk",
                        lambda src, dest, **kw: copied.append(dest.name))
    run = _save_run(tmp_path, NoBar())
    try:
        with pytest.raises(A.StepFailed, match="SAVE GAME never appeared on row 24"):
            run.write_save()
    finally:
        run.log.close()
    assert copied == ["lost-saved.D64"]
    watch = _events(tmp_path, "save-watch")
    assert watch[-1]["row24"] == "ENCAMP:SAVE VIEW MAGIC REST ALTER FIX EXIT"
    assert "SAVE GAME  EXIT" not in [w["row24"] for w in watch]


# --- deadline inside a wait ----------------------------------------------------------

class _Clock:
    def __init__(self, monkeypatch):
        self.now = 0.0
        monkeypatch.setattr(A.time, "sleep", lambda s: self.advance(s))

    def advance(self, seconds):
        self.now += seconds

    def __call__(self):
        return self.now


def test_a_wait_that_would_outlast_the_run_ends_at_the_deadline_with_the_screen_kept(
        tmp_path, monkeypatch):
    clock = _Clock(monkeypatch)
    run, log = _pool_run(tmp_path, FakeSession({"w": _window({}, "NOTHING")}, {}, "w"))
    run.clock, run.deadline = clock, 5.0
    with pytest.raises(A.StepFailed, match="seconds were spent.*waiting for the bar"):
        run.wait_rows(lambda r: False, 1000, "the bar")
    log.close()
    assert 5.0 <= clock.now < 6.0
    assert len(list(tmp_path.glob("*-lost-deadline.txt"))) == 1


def test_a_bar_wait_is_never_given_more_than_the_run_has_left(tmp_path, monkeypatch):
    clock = _Clock(monkeypatch)
    clock.now = 100.0
    sess = FakeSession({"w": _window({}, WORLD_BAR)}, {}, "w")
    asked = []
    sess.select_bar = lambda label, row=24, timeout=0: asked.append(timeout) or True
    run, log = _pool_run(tmp_path, sess)
    run.clock, run.deadline = clock, 103.0
    assert run.choose_bar("ENCAMP", timeout=20) is True
    assert asked == [3.0]
    clock.now = 103.0
    with pytest.raises(A.StepFailed, match="seconds were spent, before ENCAMP"):
        run.choose_bar("ENCAMP", timeout=20)
    log.close()
    assert asked == [3.0]


# --- the sheet on the later titles ------------------------------------------------------

class SheetFake(_CurseFake):
    def wait_bar(self, word, timeout=0):
        return word in self.screen().row(24)


def _sheet_screens(named):
    return {"camp": _window({}, "ENCAMP:SAVE VIEW MAGIC REST ALTER FIX EXIT"),
            "sheet": _window({1: named}, "EXIT")}


def _sheet_run(tmp_path, named, monkeypatch):
    sess = SheetFake(_sheet_screens(named),
                     {("camp", ("party", 4)): "camp", ("camp", ("bar", "VIEW")): "sheet",
                      ("sheet", ("bar", "EXIT")): "camp"}, "camp")
    run = _curse_run(tmp_path, sess)
    run.panel_index = lambda who: int(who) - 1
    run.to_world = lambda tries=10: True
    run.clock = _Clock(monkeypatch)
    return run, sess


def test_a_curse_view_waits_for_exit_and_the_members_name_and_returns_to_camp(
        tmp_path, monkeypatch):
    run, sess = _sheet_run(tmp_path, "SHARA  FEMALE ELF", monkeypatch)
    try:
        got = run.view("5")
    finally:
        run.log.close()
    assert got["who"] == "5" and any("SHARA" in r for r in got["sheet"])
    assert sess.state == "camp"


def test_a_sheet_that_names_someone_else_is_not_taken_for_the_member_asked_for(
        tmp_path, monkeypatch):
    run, sess = _sheet_run(tmp_path, "PHILIPPE  MALE HUMAN", monkeypatch)
    try:
        with pytest.raises(A.StepFailed, match="no sheet naming SHARA"):
            run.view("5")
    finally:
        run.log.close()


# --- Silver Blades -----------------------------------------------------------------------

def test_silver_blades_is_driven_and_its_run_is_a_later_title_run(tmp_path, monkeypatch):
    from tools.secret_of_the_silver_blades import ssbsession

    built = []

    class _Silver(_Pool):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            built.append(a[-2:])

    monkeypatch.setattr(A, "SilverRun", _Silver)
    monkeypatch.setattr(A, "stage", lambda *a, **k: {"effects": [], "magic_items": {}})
    monkeypatch.setattr(ssbsession, "stage", lambda *a, **k: "first")
    monkeypatch.setattr(ssbsession, "silver_session_class", lambda: _Sess)
    rc, _, _ = _drive(tmp_path, monkeypatch, ["load"], 1e9, title="ssb")
    assert rc == 0 and len(built) == 1


def test_a_silver_blades_run_names_the_party_in_slot_order(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "marching_names", lambda path: ["ANNA", "ZED"])
    monkeypatch.setattr(A, "saved_characters", lambda path: {
        "ANNA": {"owner": 1, "memorised": []}, "ZED": {"owner": 0, "memorised": []}})
    run = A.SilverRun(None, None, tmp_path, POOL_OF_RADIANCE, {}, "d", "s.D64")
    assert run.names == ["ZED", "ANNA"]
    assert run.attack_by == "" and run.deadline is None


@pytest.mark.parametrize("key", [[], ["--first-bar-key", "SPACE"]])
def test_the_fight_step_and_its_first_bar_key_are_accepted_for_silver_blades(
        tmp_path, monkeypatch, key):
    ran = []
    monkeypatch.setattr(A, "run", lambda args, steps, out, source: ran.append(
        (args.title, [s.text for s in steps], args.first_bar_key)) or 0)
    assert A.main(["--title", "ssb", "--save", str(_fixture_disk(tmp_path)),
                   "--disks", str(tmp_path), "--steps", "load", "fight 600",
                   *key, "--out", str(tmp_path / "out")]) == 0
    assert ran == [("ssb", ["load", "fight 600"], "SPACE" if key else None)]


def test_the_one_retry_does_not_answer_a_prompt_the_key_raised(
        tmp_path, monkeypatch):
    # The first press changes nothing; the prompt opens only once the retry's
    # key has gone, so the retry's `enter_move`/`walk_one` is what sees it.
    sess, run, log = _real_walk(tmp_path, monkeypatch, prompt_after=None)
    real_key = sess.kbd.key
    presses = []

    def key(name, *timing):
        real_key(name, *timing)
        if name == "i":
            presses.append(name)
            sess.y += 1          # the game took nothing: status and place hold
            sess.ticks -= 1
            if len(presses) == 2:
                sess.prompt_after = 0.0

    sess.kbd.key = key
    with pytest.raises(A.StepFailed, match="ran the square's event"):
        run.walk("I")
    log.close()
    assert presses == ["i", "i"]
    assert sess.kernal == [] and sess.attaches == []
    # The first press ends by leaving move mode; the retry's key is the last
    # thing sent, because a Return after it would land on the prompt.
    assert sess.keys == ["i", "Return", "i"], sess.keys


# --- the later titles' walk, judged by the live triple ------------------------------------

MOVE_BAR = "I,J,K,M, RETURN OR BUTTON"


class LaterWalkSession(WalkSession):
    """Curse's walk: the live triple is the truth, the status line shows the
    triple as it stood before the latest move, the first key changes row 24,
    and a bump costs nothing."""

    def __init__(self, walls=(), lose=0, **kw):
        super().__init__(walls=walls, **kw)
        self.lose = lose
        self.lagged = (self.x, self.y, self.facing)
        self.moving = False

    def screen(self):
        return FakeScreen(_window({}, MOVE_BAR if self.moving else WORLD_BAR))

    def position(self):
        return self.lagged

    def live_triple(self):
        return (self.x, self.y, self.facing)

    def steady_triple(self):
        return self.live_triple()

    def walk_one(self, move, *a, **k):
        self.pressed.append(move)
        self.moving = True
        if self.lose:
            self.lose -= 1
            return False
        before = self.live_triple()
        if move in ("I", "M"):
            # #708: no wall art in this fake, so `M` steps back keeping
            # the facing it started with.
            facing = self.facing if move == "I" else (self.facing + 2) % 4
            dx, dy = ((0, -1), (1, 0), (0, 1), (-1, 0))[facing]
            if (self.x + dx, self.y + dy) not in self.walls:
                self.x, self.y = self.x + dx, self.y + dy
        else:
            self.facing = (self.facing + {"J": -1, "K": 1}[move]) % 4
        self.lagged = before
        return self.live_triple() != before


def _later_run(tmp_path, sess, monkeypatch):
    log = A.Log(tmp_path)
    run = A.CurseRun.__new__(A.CurseRun)
    A.PoolRun.__init__(run, sess, log, tmp_path, POOL_OF_RADIANCE, {})
    run.clock = _Clock(monkeypatch)
    return run, log


def test_a_curse_walk_is_judged_by_the_live_triple_while_the_status_line_lags(
        tmp_path, monkeypatch):
    sess = LaterWalkSession(x=4, y=4)
    run, log = _later_run(tmp_path, sess, monkeypatch)
    got = run.walk("JI")
    log.close()
    assert got["position"] == [3, 4, 3] and got["squares_moved"] == 1
    assert got["blocked"] == []


def test_a_later_title_key_the_game_did_not_take_is_resent_though_move_mode_changed_the_screen(
        tmp_path, monkeypatch):
    sess = LaterWalkSession(x=4, y=4, lose=1)
    run, log = _later_run(tmp_path, sess, monkeypatch)
    got = run.walk("JI")
    log.close()
    assert sess.pressed == ["J", "J", "I"]
    assert got["moves"][0]["resent"] is True
    assert got["position"] == [3, 4, 3]


def test_a_later_title_bump_is_pressed_twice_and_stays_blocked(tmp_path, monkeypatch):
    sess = LaterWalkSession(x=4, y=4, walls={(3, 4)})
    run, log = _later_run(tmp_path, sess, monkeypatch)
    got = run.walk("JI")
    log.close()
    assert sess.pressed == ["J", "I", "I"]
    assert got["blocked"] == [1] and got["moves"][1]["resent"] is True


def test_a_curse_run_reads_its_position_as_the_steady_triple(tmp_path, monkeypatch):
    sess = SimpleNamespace(steady_triple=lambda: (3, 4, 2))
    run, log = _later_run(tmp_path, sess, monkeypatch)
    log.close()
    assert run.position() == [3, 4, 2]
    assert run.took_nothing([3, 4, 2], [], []) is True
    assert run.took_nothing([3, 5, 2], [], []) is False


class UnsteadyCurseSession(LaterWalkSession):
    """A party whose square settles for the first SETTLED reads and never
    again, and whose `walk_one` refuses the move for that reason."""

    def __init__(self, settled, **kw):
        super().__init__(**kw)
        self.settled = settled
        self.walk_refused = None

    def steady_triple(self):
        if self.settled > 0:
            self.settled -= 1
            return self.live_triple()
        return None

    def walk_one(self, move, *a, **k):
        self.pressed.append(move)
        self.walk_refused = "the party's square did not settle"
        return False


def test_a_curse_run_stops_when_the_party_square_never_settles(tmp_path, monkeypatch):
    sess = UnsteadyCurseSession(settled=0, x=4, y=4)
    run, log = _later_run(tmp_path, sess, monkeypatch)
    with pytest.raises(A.StepFailed, match="did not settle"):
        run.position()
    log.close()
    assert any("lost-square" in p.name for p in tmp_path.iterdir())


def test_a_refused_curse_step_reports_the_refusal_and_keeps_the_screen(
        tmp_path, monkeypatch):
    # The walk's start and the move's `before` settle; the third read, the one
    # `took_nothing` asks for, does not, which is also when `walk_one` refuses.
    sess = UnsteadyCurseSession(settled=2, x=4, y=4)
    run, log = _later_run(tmp_path, sess, monkeypatch)
    with pytest.raises(A.StepFailed, match="walk JI: .*did not settle"):
        run.walk("JI")
    log.close()
    assert sess.pressed == ["J"]
    assert any("lost-walk" in p.name for p in tmp_path.iterdir())
    events = [json.loads(line) for line in
              (tmp_path / "run.jsonl").read_text().splitlines()]
    move = [e for e in events if e.get("kind") == "move"]
    assert move and move[0]["keyed"] is False and move[0]["after"] is None


def test_the_silver_blades_session_reads_the_live_triple():
    from tools.curse_of_the_azure_bonds import curserun
    from tools.secret_of_the_silver_blades import ssbsession

    assert (ssbsession.silver_session_class().live_triple
            is curserun.CurseSession.live_triple)


def test_marching_names_lists_the_party_as_the_panel_draws_it():
    from tests.c64.test_c64nametable import specimen_disk

    assert A.marching_names(specimen_disk("curse-party-with-items")) == [
        "MALE ELF MAGE", "FEMALE MAGE", "CLERIC", "F/T", "RANGER", "PALADIN"]


def test_a_curse_view_of_panel_row_1_waits_for_the_highest_slot(tmp_path, monkeypatch):
    run, sess = _sheet_run(tmp_path, "MATHEW  MALE HUMAN", monkeypatch)
    sess.moves[("camp", ("party", 0))] = "camp"
    run.panel = ["MATHEW", "MARK", "TRAVIS", "LEDERA", "SHARA", "PHILIPPE"]
    try:
        got = run.view("1")
    finally:
        run.log.close()
    assert any("MATHEW" in r for r in got["sheet"])


def test_a_view_waits_for_a_mixed_case_name_as_the_c64_draws_it(tmp_path, monkeypatch):
    run, sess = _sheet_run(tmp_path, "G59 $% V!,/)3      STATUS OK", monkeypatch)
    sess.moves[("camp", ("party", 0))] = "camp"
    run.panel = ["Guy de Valois", "PAINE"]
    try:
        got = run.view("1")
    finally:
        run.log.close()
    assert got["who"] == "1"


def _fake_disk(monkeypatch, marching):
    monkeypatch.setattr(A, "marching_names", lambda path: list(marching))
    monkeypatch.setattr(A, "saved_characters", lambda path: {
        "ANNA": {"owner": 0, "memorised": []}, "ZED": {"owner": 1, "memorised": []},
        "MAE": {"owner": 2, "memorised": []}})


def test_a_curse_run_takes_its_panel_from_the_marching_order(tmp_path, monkeypatch):
    _fake_disk(monkeypatch, ["MAE", "ANNA", "ZED"])
    run = A.CurseRun(None, None, tmp_path, POOL_OF_RADIANCE, {}, "d", "s.D64")
    assert run.panel == ["MAE", "ANNA", "ZED"] and run.names == ["ANNA", "ZED", "MAE"]


def test_a_silver_blades_run_takes_its_panel_from_the_marching_order(
        tmp_path, monkeypatch):
    monkeypatch.setattr(A, "marching_names", lambda path: ["Zed", "Anna"])
    monkeypatch.setattr(A, "saved_characters", lambda path: {
        "ANNA": {"owner": 0, "memorised": []}, "ZED": {"owner": 1, "memorised": []}})
    run = A.SilverRun(None, None, tmp_path, POOL_OF_RADIANCE, {}, "d", "s.D64")
    assert run.panel == ["Zed", "Anna"] and run.panel != run.names


def test_a_curse_run_keeps_slot_indices_across_an_empty_slot(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "marching_names", lambda path: ["BAR PATRON"])
    monkeypatch.setattr(A, "saved_characters", lambda path: {
        "ANNA": {"owner": 0, "memorised": []}, "MAE": {"owner": 3, "memorised": []},
        "ZED": {"owner": 2, "memorised": []}})
    run = A.CurseRun(None, None, tmp_path, POOL_OF_RADIANCE, {}, "d", "s.D64",
                     attack_by="zed")
    assert run.names == ["ANNA", "", "ZED", "MAE"]
    assert run.owner_of("zed") == 2 and run.attack_owner == 2


def test_a_curse_run_names_the_party_of_a_save_whose_name_table_is_scratch(tmp_path):
    from goldbox.c64_port import CURSE_OF_THE_AZURE_BONDS
    from tests.c64.test_c64nametable import specimen_disk

    disk = specimen_disk("curse-671-invisibility-removed-after-fight")
    run = A.CurseRun(None, None, tmp_path, CURSE_OF_THE_AZURE_BONDS, {}, "d", disk)
    assert run.names == ["PHILIPPE", "SHARA", "LEDERA", "TRAVIS", "MARK", "MATHEW"]
    assert run.owner_of("PHILIPPE") == 0


def test_a_curse_run_on_the_specimen_panel_is_the_marching_order(tmp_path):
    from goldbox.c64_port import CURSE_OF_THE_AZURE_BONDS
    from tests.c64.test_c64nametable import specimen_disk

    disk = specimen_disk("curse-party-with-items")
    run = A.CurseRun(None, None, tmp_path, CURSE_OF_THE_AZURE_BONDS, {}, "d", disk)
    assert run.panel == A.marching_names(disk) == [
        "MALE ELF MAGE", "FEMALE MAGE", "CLERIC", "F/T", "RANGER", "PALADIN"]


# --- the save's gap after a disk prompt -----------------------------------------

from automap.screen import Screen  # noqa: E402
from tools.curse_of_the_azure_bonds import curserun as _curserun  # noqa: E402
from tools.secret_of_the_silver_blades import ssbsession as _ssbsession  # noqa: E402

_CAMP = "SAVE VIEW MAGIC REST ALTER FIX EXIT"
_PRESS = "PRESS ANY KEY TO CONTINUE"


def _text_screen(row18: str, row24: str) -> Screen:
    codes = bytearray(0x20 for _ in range(1000))
    for row, text in ((18, row18), (24, row24)):
        for i, ch in enumerate(text.upper()):
            codes[row * 40 + i] = ord(ch) - 0x40 if "A" <= ch <= "Z" else ord(ch)
    return Screen(bytes(codes), bytes(1000), 0xCC00)


class _StepClock:
    """A clock that only `sleep` moves."""

    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now

    monotonic = time

    def sleep(self, seconds):
        self.now += seconds


class _GapKeys:
    def __init__(self, sess):
        self.sess = sess

    def key(self, name, *timing):
        if name == "space":
            self.sess.answer()

    def screenshot(self, path):
        pathlib.Path(path).write_bytes(b"")


def _boot_session(base, tmp_path, clock, save_bar):
    """A real driver's `wait_bar`, `handle_prompt` and `to_world_bar` in front of
    the screens Silver Blades drew on the C64 boot of #679: camp, the save-disk
    prompt, a gap of 0.9 s with row 18 blank and `PRESS ANY KEY` still up,
    then (SAVE_BAR) `SAVE GAME  EXIT` or straight to `SAVING GAME...`, 33 s of
    writing, the game-disk prompt, the camp bar."""
    for name in ("SIDE0.D64", "SIDE1.D64", "SIDE10.D64"):
        (tmp_path / name).touch()

    class Scripted(base):
        def __init__(self):
            self.save_disk = str(tmp_path / "SIDE0.D64")
            self.here = str(tmp_path)
            self.attached = ""
            self._last_prompt = 0.0
            self._last_want = None
            self.kbd = _GapKeys(self)
            self.state, self.since = "camp", 0.0
            self.kernal, self.pressed = [], []

        def answer(self):
            if self.state == "prompt":
                self.state, self.since = "gap", clock.now
            elif self.state == "gameprompt":
                self.state = "back"

        def log(self, *a):
            pass

        def attach(self, path, unit=8, settle=None):
            self.attached = path

        def press_kernal(self, code):
            self.kernal.append(code)
            if code == 0x20:
                self.answer()

        def press_bar(self, label, row=24, timeout=30.0, answer_prompts=True):
            self.pressed.append(label)
            self.state, self.since = {"SAVE": ("prompt", 0.0),
                                      "SAVE GAME": ("saving", clock.now)}[label]
            return True

        def settle(self, seconds=0):
            clock.sleep(seconds)

        def wait_text(self, needle, timeout=0):
            for _ in range(50):
                s = self.screen()
                if any(needle in s.row(r) for r in range(25)):
                    return needle, s
                clock.sleep(0.6)
            return None, None

        def screen(self):
            age = clock.now - self.since
            if self.state == "gap" and age >= 0.9:
                self.state, self.since = ("savebar", clock.now) if save_bar \
                    else ("saving", clock.now)
            if self.state == "saving" and age >= 33:
                self.state = "gameprompt"
            return {"camp": _text_screen("YOU SET UP CAMP...", _CAMP),
                    "back": _text_screen("", _CAMP),
                    "prompt": _text_screen("INSERT YOUR SAVE GAME DISK", _PRESS),
                    "gap": _text_screen("", _PRESS),
                    "savebar": _text_screen("", "SAVE GAME  EXIT"),
                    "saving": _text_screen("", "SAVING GAME..."),
                    "gameprompt": _text_screen("INSERT YOUR GAME DISK A", _PRESS),
                    }[self.state]

    return Scripted()


def _both_drivers():
    from tools.secret_of_the_silver_blades import ssbsession
    return [pytest.param(ssbsession.silver_session_class(), id="silver"),
            pytest.param(_curserun.CurseSession, id="curse")]


def _fake_time(monkeypatch):
    clock = _StepClock()
    for module in (_curserun, _ssbsession):
        monkeypatch.setattr(module, "time", clock)
    return clock


def _boot_save(tmp_path, monkeypatch, base, save_bar):
    clock = _fake_time(monkeypatch)
    sess = _boot_session(base, tmp_path, clock, save_bar)
    run = _save_run(tmp_path, sess)
    run.clock = clock.time
    copied = []

    def copy(src, dest, **kw):
        copied.append(dest.name)
        dest.write_bytes(b"")

    monkeypatch.setattr(A.S, "copy_closed_disk", copy)
    try:
        run.write_save()
    finally:
        run.log.close()
    return sess, copied


@pytest.mark.parametrize("base", _both_drivers())
def test_no_return_is_sent_in_the_gap_after_the_save_disk_is_answered(
        tmp_path, monkeypatch, base):
    sess, _ = _boot_save(tmp_path, monkeypatch, base, save_bar=False)
    assert 0x0D not in sess.kernal
    assert sess.pressed == ["SAVE"]
    assert sess.state == "back"


@pytest.mark.parametrize("base", _both_drivers())
def test_a_save_bar_drawn_after_the_gap_is_pressed_once(tmp_path, monkeypatch, base):
    sess, _ = _boot_save(tmp_path, monkeypatch, base, save_bar=True)
    assert 0x0D not in sess.kernal
    assert sess.pressed == ["SAVE", "SAVE GAME"]
    assert sess.state == "back"


@pytest.mark.parametrize("base", _both_drivers())
def test_to_world_bar_sends_no_return_in_the_gap_and_wait_bar_still_does_later(
        tmp_path, monkeypatch, base):
    clock = _fake_time(monkeypatch)
    sess = _boot_session(base, tmp_path, clock, save_bar=False)
    sess.state, sess.since = "gap", clock.now
    sess._disk_answered = clock.now
    assert sess.to_world_bar(timeout=0.5) is False
    assert 0x0D not in sess.kernal
    # No disk prompt answered lately: the same row gets its Return.
    sess.state, sess._disk_answered = "gap", None
    sess.since = clock.now + 1e6
    assert sess.to_world_bar(timeout=0.5) is False
    assert 0x0D in sess.kernal


# --- the command line -----------------------------------------------------------------

def _entry_points():
    import sys
    repo = pathlib.Path(A.__file__).resolve().parents[2]
    return [[sys.executable, str(repo / "tools" / "c64" / "acceptance.py")],
            [sys.executable, "-m", "tools.c64.acceptance"]], repo


def _run_entry(cmd, repo, *args):
    import subprocess
    return subprocess.run(cmd + list(args), cwd=repo, capture_output=True, text=True,
                          timeout=120)


def test_the_command_line_answers_help():
    cmds, repo = _entry_points()
    for cmd in cmds:
        got = _run_entry(cmd, repo, "--help")
        assert got.returncode == 0 and "--stage-only" in got.stdout


def test_the_command_line_stages_the_same_evidence_either_way(tmp_path):
    cmds, repo = _entry_points()
    seen = []
    for i, cmd in enumerate(cmds):
        out = tmp_path / f"out{i}"
        got = _run_entry(cmd, repo, "--title", "pool", "--save",
                         str(_fixture_disk(tmp_path)), "--stage-row", "63=05:FF:0A:03",
                         "--stage-only", "--steps", "load", "--out", str(out))
        assert got.returncode == 0, got.stderr
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        staged = {k: v for k, v in summary["staged"].items()
                  if k not in ("source", "staged")}
        seen.append((sorted(summary), staged))
    assert seen[0] == seen[1]
    assert seen[0][1]["effects"] == [[63, 5, 0xFF, 0x0A, 0x03]]


def test_the_command_line_refuses_a_bad_step_list_with_2(tmp_path):
    cmds, repo = _entry_points()
    for i, cmd in enumerate(cmds):
        got = _run_entry(cmd, repo, "--title", "pool", "--save",
                         str(_fixture_disk(tmp_path)), "--stage-only",
                         "--steps", "nonsense", "--out", str(tmp_path / f"bad{i}"))
        assert got.returncode == 2, got.stderr


def test_the_command_line_compares_two_runs(tmp_path):
    cmds, repo = _entry_points()
    runs = []
    for name in ("a", "b"):
        out = tmp_path / name
        got = _run_entry(cmds[0], repo, "--title", "pool", "--save",
                         str(_fixture_disk(tmp_path)), "--stage-only",
                         "--steps", "load", "--out", str(out))
        assert got.returncode == 0, got.stderr
        runs.append(str(out))
    outputs = []
    for cmd in cmds:
        got = _run_entry(cmd, repo, "--compare", *runs)
        assert got.returncode == 0, got.stderr
        outputs.append(got.stdout)
    assert outputs[0] == outputs[1]


def test_a_terminating_signal_mid_step_is_lost_and_releases_the_slot(tmp_path, monkeypatch):
    class _Killed(_Pool):
        def load(self):
            raise A.runlog.Terminated("signal 15")

    rc, slot, out = _drive(tmp_path, monkeypatch, ["load"], 1e9, pool=_Killed)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert rc == 1 and not summary["completed"]
    assert "Terminated" in summary["lost"]
    assert slot.torn


def test_a_run_installs_the_signal_handler_once_after_staging_and_before_its_steps(
        tmp_path, monkeypatch):
    events = []
    real_stage = A.stage

    def stage(*a, **k):
        events.append("stage")
        return real_stage(*a, **k)

    class _Ordered(_Pool):
        def load(self):
            events.append("load")
            return {}

    monkeypatch.setattr(A, "stage", stage)
    slot = _Slot(tmp_path)
    claim = lambda *a, **k: (events.append("claim"), slot)[1]   # noqa: E731
    rc, _, _ = _drive(tmp_path, monkeypatch, ["load"], 1e9, pool=_Ordered, claim=claim,
                      catch=lambda: events.append("catch"))
    assert rc == 0
    assert events == ["stage", "catch", "claim", "load"]


def test_no_signal_handler_is_installed_when_nothing_is_run(tmp_path, monkeypatch):
    calls = []

    def refuse(*a, **k):
        raise ValueError("no such row")

    monkeypatch.setattr(A, "stage", refuse)
    rc, _, _ = _drive(tmp_path, monkeypatch, ["load"], 1e9,
                      catch=lambda: calls.append(1))
    assert rc == 1 and calls == []
    monkeypatch.undo()
    (tmp_path / "b").mkdir()
    rc, _, _ = _drive(tmp_path / "b", monkeypatch, ["load"], 1e9,
                      catch=lambda: calls.append(1), stage_only=True)
    assert rc == 0 and calls == []


def test_the_silver_session_class_is_built_fresh_on_every_call():
    from tools.secret_of_the_silver_blades import ssbsession

    assert ssbsession.silver_session_class() is not ssbsession.silver_session_class()


def test_the_silver_session_borrows_from_the_curse_session_as_patched_at_call_time(
        monkeypatch):
    from tools.curse_of_the_azure_bonds import curserun
    from tools.secret_of_the_silver_blades import ssbsession

    class Patched(curserun.CurseSession):
        def live_triple(self):
            return "patched"

    monkeypatch.setattr(curserun, "CurseSession", Patched)
    assert ssbsession.silver_session_class().live_triple is Patched.live_triple


def test_pool_fight_that_runs_out_of_budget_fails_the_step_with_a_fight_capture(
        tmp_path):
    class Session:
        def in_combat(self):
            return True

        def fight(self, *, budget, tactic):
            return A.S.FightResult(A.S.BUDGET, 5, 60.0, [], [])

    run = A.PoolRun.__new__(A.PoolRun)
    run.sess = Session()
    run.to_world = lambda: True
    run.spent = lambda: False
    captured = []
    run.capture = captured.append
    with pytest.raises(A.StepFailed, match="budget"):
        run.fight("60", "I", 5)
    assert captured == ["fight-start", "fight-end", "lost-fight"]


def test_curse_fight_that_runs_out_of_budget_fails_the_step_with_a_fight_capture(
        monkeypatch, tmp_path):
    from types import SimpleNamespace

    from tools.c64 import laterbattle
    from tools.curse_of_the_azure_bonds import cursethac0

    class Route:
        last_goto_steps = 3

        def __init__(self, out, quiet):
            self.file = SimpleNamespace(close=lambda: None)

        def goto(self, target, steps, geo):
            return True

    class Session:
        def in_combat(self):
            return True

        def await_bar(self, kinds, timeout, interval):
            return None

        def fight(self, *, budget, tactic):
            return A.S.FightResult(A.S.BUDGET, 5, 60.0, [], [])

    monkeypatch.setattr(laterbattle, "Battle", Route)
    monkeypatch.setattr(cursethac0, "area_geo", lambda *a: ("GEO01", object()))
    run = A.CurseRun.__new__(A.CurseRun)
    run.attack_by = ""
    run.attack_owner = None
    run.attack_evidence = None
    run.quit_evidence = None
    run.sess = Session()
    run.out = tmp_path
    run.staged_disk = tmp_path / "staged.D64"
    run.disks = "unused"
    run.to_world = lambda: True
    run.await_combat = lambda: True
    run.spent = lambda: False
    captured = []
    run.capture = captured.append
    with pytest.raises(A.StepFailed, match="budget"):
        run.fight("60", "I", 5)
    assert captured[-2:] == ["fight-end", "lost-fight"]


def test_a_budget_ended_fight_keeps_the_checkpoint_reading(tmp_path):
    class Session:
        def in_combat(self):
            return True

        def fight(self, *, budget, tactic):
            return A.S.FightResult(A.S.BUDGET, 5, 1.0, [], [])

    run = A.PoolRun.__new__(A.PoolRun)
    run.sess = Session()
    run.to_world = lambda: True
    run.spent = lambda: False
    run.capture = lambda tag: None
    run.reading = lambda: {"counts": {"x": 3}}
    with pytest.raises(A.StepFailed):
        run.fight("1", "I", 5)
    assert run.lost_reading == {"step": "fight", "after": {"counts": {"x": 3}}}


def test_the_budget_failure_message_names_seconds_and_turns(tmp_path):
    run = A.PoolRun.__new__(A.PoolRun)
    run.spent = lambda: False
    run.capture = lambda tag: None
    run.reading = lambda: {}
    err = run.fight_over_budget("60", A.S.FightResult(A.S.BUDGET, 5, 60.0, [], []))
    assert str(err) == "the fight ran out of its 60 second budget after 5 turns"


def test_a_budget_ended_fight_before_save_loses_the_run_at_the_fight(
        tmp_path, monkeypatch):
    class Fighter(_Pool):
        saved = False

        def fight(self, arg, walk, steps):
            self.lost_reading = {"step": "fight", "after": {"counts": {"x": 2}}}
            raise A.StepFailed("the fight ran out of its 1 second budget "
                               "after 5 turns")

        def save(self, staged):
            Fighter.saved = True
            return {}

    rc, slot, out = _drive(tmp_path, monkeypatch, ["load", "fight 1", "save"],
                           pool=Fighter)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert rc != 0 and not Fighter.saved
    assert "budget" in summary["lost"]
    assert summary["lost_reading"]["after"] == {"counts": {"x": 2}}
    assert [r["verb"] for r in summary["results"]] == ["load"]


def _pool_run_fighting(outcome):
    class Session:
        def in_combat(self):
            return True

        def fight(self, *, budget, tactic):
            return A.S.FightResult(outcome, 7, 1.0, [], [])

    run = A.PoolRun.__new__(A.PoolRun)
    run.sess = Session()
    run.to_world = lambda: True
    run.spent = lambda: False
    run.captured = []
    run.capture = run.captured.append
    run.reading = lambda: {"counts": {"x": 4}}
    return run


def test_pool_fight_the_party_loses_fails_the_step_and_keeps_the_reading():
    run = _pool_run_fighting(A.S.LOST)
    with pytest.raises(A.StepFailed) as err:
        run.fight("60", "I", 5)
    assert str(err.value) == "the party lost the fight after 7 turns"
    assert run.captured == ["fight-start", "fight-end", "lost-fight"]
    assert run.lost_reading == {"step": "fight", "after": {"counts": {"x": 4}}}


def test_pool_fight_the_party_wins_passes_the_step():
    run = _pool_run_fighting(A.S.WON)
    assert run.fight("60", "I", 5)["outcome"] == A.S.WON
    assert run.captured == ["fight-start", "fight-end"]


def test_curse_fight_the_party_loses_fails_the_step_with_a_fight_capture(
        monkeypatch, tmp_path):
    from types import SimpleNamespace

    from tools.c64 import laterbattle
    from tools.curse_of_the_azure_bonds import cursethac0

    class Route:
        last_goto_steps = 3

        def __init__(self, out, quiet):
            self.file = SimpleNamespace(close=lambda: None)

        def goto(self, target, steps, geo):
            return True

    class Session:
        def in_combat(self):
            return True

        def await_bar(self, kinds, timeout, interval):
            return None

        def fight(self, *, budget, tactic):
            return A.S.FightResult(A.S.LOST, 7, 1.0, [], [])

    monkeypatch.setattr(laterbattle, "Battle", Route)
    monkeypatch.setattr(cursethac0, "area_geo", lambda *a: ("GEO01", object()))
    run = A.CurseRun.__new__(A.CurseRun)
    run.attack_by = ""
    run.attack_owner = None
    run.attack_evidence = None
    run.quit_evidence = None
    run.sess = Session()
    run.out = tmp_path
    run.staged_disk = tmp_path / "staged.D64"
    run.disks = "unused"
    run.to_world = lambda: True
    run.await_combat = lambda: True
    run.spent = lambda: False
    captured = []
    run.capture = captured.append
    run.reading = lambda: {"counts": {"x": 4}}
    with pytest.raises(A.StepFailed, match="lost the fight after 7 turns"):
        run.fight("60", "I", 5)
    assert captured[-2:] == ["fight-end", "lost-fight"]
    assert run.lost_reading == {"step": "fight", "after": {"counts": {"x": 4}}}


def test_a_lost_fight_before_save_loses_the_run_at_the_fight(tmp_path, monkeypatch):
    lost = _pool_run_fighting(A.S.LOST)

    class Fighter(_Pool):
        saved = False

        def fight(self, arg, walk, steps):
            raise lost.fight_lost(A.S.FightResult(A.S.LOST, 7, 1.0, [], []))

        def save(self, staged):
            Fighter.saved = True
            return {}

    rc, slot, out = _drive(tmp_path, monkeypatch, ["load", "fight 60", "save"],
                           pool=Fighter)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert rc != 0 and not Fighter.saved
    assert "lost the fight after 7 turns" in summary["lost"]
    assert [r["verb"] for r in summary["results"]] == ["load"]


BANNED_EXPERIMENT_IMPORTS = {"traitask", "effectdrive", "inventorycheck",
                             "traitdrive", "traitquery", "cursewarp",
                             "ssbwarp"}


def test_acceptance_imports_no_experiment_module_that_route_pool_replaced():
    """The Pool camp, sheet, item and rest actions live in `route_pool`, so
    acceptance takes them from there and not from the experiments."""
    import ast

    tree = ast.parse(pathlib.Path(A.__file__).read_text())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            parts = node.module.split(".")
            if parts[:2] in (["tools", "c64"],
                             ["tools", "curse_of_the_azure_bonds"],
                             ["tools", "secret_of_the_silver_blades"]) \
                    and len(parts) > 2:
                found.add(parts[2])
            elif node.module in ("tools.c64",
                                 "tools.curse_of_the_azure_bonds",
                                 "tools.secret_of_the_silver_blades"):
                found.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            found.update(a.name.split(".")[-1] for a in node.names)
    assert found.isdisjoint(BANNED_EXPERIMENT_IMPORTS), \
        found & BANNED_EXPERIMENT_IMPORTS


def test_route_pool_imports_no_experiment_module():
    """Importing `route_pool` must not pull in the experiments it was moved
    out of."""
    code = ("import sys; import tools.c64.route_pool; "
            "bad = [m for m in ('tools.c64.traitask', 'tools.c64.traitdrive',"
            " 'tools.c64.effectdrive') if m in sys.modules]; "
            "sys.exit(1 if bad else 0)")
    root = pathlib.Path(A.__file__).resolve().parents[2]
    done = subprocess.run([sys.executable, "-c", code], cwd=root,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


# --- warp ------------------------------------------------------------------------

class _WarpMonitor:
    def __init__(self, sess):
        self.sess = sess

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, addr, length):
        assert (addr, length) == (0xC04B, 3)
        return bytes(self.sess.triple)

    def registers(self):
        return {0: self.sess.pc}


class _WarpSession:
    def __init__(self, triple=(0, 4, 1)):
        self.triple = triple
        self.pc = A.fasttravel.POOL_OF_RADIANCE.key_wait[0]

    def mon(self, timeout=5.0):
        return _WarpMonitor(self)

    def settle(self, seconds=0):
        pass


def _warp_run(tmp_path, monkeypatch, triple=(0, 4, 1), legal=True):
    calls = []

    class Verdict:
        ok = legal
        reason = "the party is busy"

    class FakeTravel:
        def legality(self, target, row):
            calls.append(("legality", row.id))
            return Verdict()

        def current_area(self, target):
            return 5

    monkeypatch.setattr(A.auto_actions, "FastTravel", FakeTravel)
    monkeypatch.setattr(A.auto_actions, "pc_register", lambda m: 0)
    monkeypatch.setattr(A.auto_actions, "_write_all",
                        lambda target, writes: calls.append(("write", tuple(writes))))
    monkeypatch.setattr(A.auto_actions, "jump",
                        lambda target, addr: calls.append(("jump", addr)) or True)
    sess = _WarpSession(triple)
    run, _ = _pool_run(tmp_path, sess)
    run.to_world = lambda tries=10: True
    run.capture = lambda tag, rows=None: []
    run.position = lambda: list(sess.triple)
    return run, calls


def test_warp_writes_the_new_area_then_sets_the_program_counter(tmp_path, monkeypatch):
    run, calls = _warp_run(tmp_path, monkeypatch)
    got = run.warp("10")
    row = A.auto_actions.area_by_id(10)
    writes = A.auto_actions.newecl_writes(5, 10, getattr(row, "disk", None), None)
    assert calls == [("legality", 10), ("write", tuple(writes)),
                     ("jump", A.fasttravel.POOL_OF_RADIANCE.tail)]
    assert got["triple"] == [0, 4, 1] and got["area"] == 10


def test_warp_refused_by_legality_writes_and_jumps_nothing(tmp_path, monkeypatch):
    run, calls = _warp_run(tmp_path, monkeypatch, legal=False)
    with pytest.raises(A.StepFailed, match="the party is busy"):
        run.warp("10")
    assert calls == [("legality", 10)]


def test_warp_fails_naming_a_facing_other_than_east(tmp_path, monkeypatch):
    run, _ = _warp_run(tmp_path, monkeypatch, triple=(0, 4, 3))
    with pytest.raises(A.StepFailed, match=r"\$C04D read 3"):
        run.warp("10")


def test_warp_parses_any_listed_area_and_refuses_the_rest():
    assert A.parse_steps(["load", "warp 10"])[1] == A.Step("warp", "10")
    assert A.parse_steps(["load", "warp 9"])[1] == A.Step("warp", "9")
    for bad in ("warp", "warp x", "warp 99", "warp 12"):
        with pytest.raises(ValueError):
            A.parse_steps(["load", bad])
    with pytest.raises(ValueError, match="not an area"):
        A.parse_warp("99")


def test_warp_refuses_wilderness_and_non_fast_travelable_areas_at_parse():
    for area in (25, 26, 27):
        with pytest.raises(ValueError, match="wilderness"):
            A.parse_warp(str(area))
    with pytest.raises(ValueError, match="fast travel cannot"):
        A.parse_warp("30")


def test_warp_to_an_area_without_an_arrival_facing_runs_unchecked(tmp_path, monkeypatch):
    run, calls = _warp_run(tmp_path, monkeypatch, triple=(0, 4, 3))
    said = []
    run.log = type("L", (), {"say": staticmethod(said.append)})()
    got = run.warp("9")
    assert got["area"] == 9 and ("jump", A.fasttravel.POOL_OF_RADIANCE.tail) in calls
    assert any("facing not checked" in line for line in said)


def test_the_warp_step_is_refused_for_curse_and_silver_blades(tmp_path, capsys):
    for title in ("curse", "ssb"):
        with pytest.raises(SystemExit) as info:
            A.main(["--title", title, "--save", str(_fixture_disk(tmp_path)),
                    "--disks", str(tmp_path), "--steps", "load", "warp 10",
                    "--out", str(tmp_path / "out")])
        assert info.value.code == 2
        assert "warp step: Pool of Radiance only" in capsys.readouterr().err
    for cls in (A.CurseRun, A.SilverRun):
        run = cls.__new__(cls)
        run.fail = lambda tag, why: A.StepFailed(why)
        with pytest.raises(A.StepFailed, match="Pool of Radiance only"):
            run.warp("10")


# --- walk-fight ------------------------------------------------------------------

def _stop_rows(bar):
    return [""] * 24 + [bar]


class FightWalk(WalkSession):
    """A grid walk whose moves can raise an encounter menu, a `YES NO` or a
    fight.  `script` maps the number of the `walk_one` call (from 0) to what
    that key starts: "fight", "fight-stay" (the fight leaves the party where it
    was), "encounter", "yesno" or ("teleport", x, y)."""

    ENCOUNTER = "COMBAT WAIT FLEE ADVANCE"
    YESNO = "YES NO"

    def __init__(self, script, outcome=A.S.WON, **kw):
        super().__init__(**kw)
        self.script, self.outcome = script, outcome
        self.calls = 0
        self.combat = False
        self.pending = None
        self.walk_stop_screen = None
        self.selected = []
        self.tactics = []
        self.encounter_words = []

    def in_combat(self):
        return self.combat

    def walk_stop(self, s=None, wait=0.0):
        return self.pending

    def select_bar(self, label, row=24, timeout=0, **kw):
        self.selected.append(label)
        if label == "COMBAT":
            self.combat, self.pending = True, None
        elif label == "NO":
            self.combat, self.pending = True, None
        elif label == "FLEE":
            self.combat, self.pending = self.flee_fails, None
        return True

    flee_fails = False

    def walk_one(self, move, *a, **k):
        self.encounter_words.append(self.walk_encounter)
        event = self.script.get(self.calls)
        self.calls += 1
        before = (self.x, self.y)
        if event == "unread":
            self.pressed.append(move)
            return False
        super().walk_one(move)
        if event == "fight":
            self.combat = True
        elif event == "fight-stay":
            self.combat = True
            self.x, self.y = before
        elif event == "encounter":
            self.pending = _stop_rows(self.ENCOUNTER)
        elif event == "yesno":
            self.pending = _stop_rows(self.YESNO)
        elif isinstance(event, tuple):
            self.x, self.y = event[1:]
        return True

    def fight(self, budget, tactic, stop=None):
        self.combat = False
        self.tactics.append((budget, tactic))
        return A.S.FightResult(self.outcome, 3, 1.0, [], [])


def _fight_walk_run(tmp_path, monkeypatch, sess):
    run, log = _walk_run(tmp_path, sess, _Clock(monkeypatch))
    run.capture = lambda tag, rows=None: []
    run.reading = lambda: {}
    run.position = lambda: list(sess.position())
    return run, log


def test_walk_fight_fights_an_encounter_mid_route_and_resumes(tmp_path, monkeypatch):
    sess = FightWalk({1: "fight"})
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    got = run.walk_fight("III")
    log.close()
    assert sess.tactics == [(A.WALK_FIGHT_SECONDS, A.S.Session.melee_turn)]
    assert sess.pressed == ["I", "I", "I"]
    assert got["position"] == [5, 2, 0]
    assert [f["at_move"] for f in got["fights"]] == [1]
    assert got["fights"][0]["square"] == [5, 3, 0]
    assert sess.encounter_words == [A.S.ENCOUNTER_FIGHT] * 3
    assert sess.walk_encounter is None


class SideFightWalk(FightWalk):
    """A `FightWalk` whose moves in `prompts` (numbered from 0 by `walk_one`
    call) behave as the real session's do at the encounter square: the game
    puts `INSERT SIDE # 2, AND PRESS ANY KEY.` up, `walk_one` returns False
    with the party still on its square and no encounter flag, and the fight
    opens (and the step lands) only `fight_delay` `in_combat` reads after the
    answer.  `handle_prompt` attaches the side's image and presses a key; the
    text then stays for `linger` more screen reads."""

    PROMPT = "INSERT SIDE # 2, AND PRESS ANY KEY."

    def __init__(self, prompts, script=None, linger=0, fight_delay=3, **kw):
        super().__init__(script or {}, **kw)
        self.prompts_at, self.linger = set(prompts), linger
        self.fight_delay = fight_delay
        self.prompt_up, self.attaches, self.keys_sent = False, [], 0
        self.cleared_in = None
        self.opening = None
        self.landing = None
        # Options: the prompt returns once, long after it clears (with the text
        # `reprompt_text`); the party's live square moves at the answer; the
        # status line `status` is drawn under the world bar; the answer does
        # not start a fight by itself.
        self.reprompt = False
        self.polls = 0
        self.reprompt_text = None
        self.land_early = False
        self.status = None
        self.fight_on_answer = True

    def walk_one(self, move, *a, **k):
        if self.calls in self.prompts_at:
            self.calls += 1
            self.pressed.append(move)
            self.prompt_up, self.cleared_in = True, None
            self.landing = move
            # The key's own window shows no change, as the real one's does.
            self.walk_screens = ("same", "same")
            return False
        return super().walk_one(move, *a, **k)

    def screen(self):
        if self.prompt_up and self.cleared_in is not None:
            if self.cleared_in <= 0:
                self.prompt_up = False
            else:
                self.cleared_in -= 1
        if self.prompt_up:
            return _Text(_window({}, self.PROMPT))
        if self.status and self.keys_sent:
            return _Text(_window({14: self.status}, WORLD_BAR))
        return _Text(_window({}, WORLD_BAR))

    def handle_prompt(self, s=None):
        self.prompts += 1
        self.attaches.append(self.wanted_disk(s))
        self.keys_sent += 1
        self.cleared_in = self.linger
        if self.fight_on_answer:
            self.opening = self.fight_delay
        if self.land_early and self.landing is not None:
            self.x, self.y = self.x, self.y - 1
            self.landing = None
        return True

    def in_combat(self):
        if self.reprompt and self.keys_sent:
            # Long after the look for a fight has ended, so it is the wait
            # for the load that sees the prompt.
            self.polls += 1
            if self.polls == 40:
                self.reprompt, self.prompt_up, self.cleared_in = False, True, None
                if self.reprompt_text:
                    self.PROMPT = self.reprompt_text
        if self.opening is not None and not self.combat:
            self.opening -= 1
            if self.opening <= 0:
                self.opening = None
                if self.landing is not None:
                    self.x, self.y = self.x, self.y - 1
                    self.landing = None
                self.combat = True
        return self.combat


@pytest.mark.parametrize("verb", ["walk_fight", "walk_flee"])
def test_walk_fight_answers_a_side_prompt_once_and_goes_on_to_the_fight(
        tmp_path, monkeypatch, verb):
    sess = SideFightWalk({1}, linger=2)
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    got = getattr(run, verb)("III")
    log.close()
    assert sess.attaches == ["SIDE2.D64"] and sess.keys_sent == 1
    assert sess.pressed == ["I", "I", "I"]
    assert [f["at_move"] for f in got["fights"]] == [1]
    assert got["position"] == [5, 2, 0]
    assert got["side_prompts"] == [{"side": "2", "at_move": 1, "fight": True}]


def test_walk_fight_stops_on_a_side_prompt_that_comes_back_in_the_same_move_keeping_the_frame(
        tmp_path, monkeypatch):
    sess = SideFightWalk({0}, linger=1, fight_delay=10 ** 6)
    sess.reprompt = True
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    shots = []
    run.capture = lambda tag, rows=None: shots.append(tag) or []
    with pytest.raises(A.StepFailed, match="side 2 prompt came back"):
        run.walk_fight("I")
    log.close()
    assert sess.keys_sent == 1
    assert shots == ["side2-before-answer", "lost-walk"]


def test_walk_fight_answers_side_2_again_for_the_next_encounter(tmp_path, monkeypatch):
    sess = SideFightWalk({0, 1}, linger=1)
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    got = run.walk_fight("II")
    log.close()
    assert sess.keys_sent == 2
    assert [f["at_move"] for f in got["fights"]] == [0, 1]
    assert [(p["at_move"], p["fight"]) for p in got["side_prompts"]] == [
        (0, True), (1, True)]


def test_walk_fight_names_a_different_disk_prompt_that_comes_up_while_the_load_waits(
        tmp_path, monkeypatch):
    sess = SideFightWalk({0}, linger=1, fight_delay=10 ** 6)
    sess.reprompt, sess.reprompt_text = True, "INSERT SIDE # 3, AND PRESS ANY KEY."
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    with pytest.raises(A.StepFailed, match="asks for side 3 mid-walk"):
        run.walk_fight("I")
    log.close()
    assert sess.keys_sent == 1


def test_walk_fight_does_not_take_the_live_square_for_the_end_of_the_load(
        tmp_path, monkeypatch):
    """The game moves the live square before it draws the encounter, so with
    no status line on screen a changed square is not a landing."""
    sess = SideFightWalk({0}, fight_delay=int(A.LOOK_SECONDS / 0.3) + 20)
    sess.land_early = True
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    got = run.walk_fight("I")
    log.close()
    assert [f["at_move"] for f in got["fights"]] == [0]


def test_walk_fight_takes_a_new_square_read_twice_under_the_world_bar_as_no_fight(
        tmp_path, monkeypatch):
    sess = SideFightWalk({0})
    sess.fight_on_answer = False
    sess.land_early, sess.status = True, "N 4:00 5,4"
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    got = run.walk_fight("I")
    log.close()
    assert got["fights"] == [] and got["position"] == [5, 4, 0]
    assert got["side_prompts"] == [{"side": "2", "at_move": 0, "fight": False}]


def test_walk_fight_waits_out_and_fights_a_load_that_a_prompt_after_the_last_key_starts(
        tmp_path, monkeypatch):
    sess = SideFightWalk(set())
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    emit = log.emit

    def late(tag, **kw):
        emit(tag, **kw)
        if tag == "move":
            sess.prompt_up, sess.cleared_in, sess.landing = True, None, "I"

    log.emit = late
    got = run.walk_fight("I")
    log.close()
    assert sess.keys_sent == 1
    assert [f["at_move"] for f in got["fights"]] == [0]
    assert got["side_prompts"] == [{"side": "2", "at_move": 0, "fight": True}]


def test_walk_fight_flags_only_the_prompts_answered_during_the_key_that_fought(
        tmp_path, monkeypatch):
    """A prompt up before move 1 is answered before its key; the fight that
    key starts does not follow it."""
    sess = SideFightWalk(set(), {1: "fight"})
    sess.fight_on_answer = False
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    emit = log.emit

    def late(tag, **kw):
        emit(tag, **kw)
        if tag == "move" and kw["n"] == 0:
            sess.prompt_up, sess.cleared_in = True, None

    log.emit = late
    got = run.walk_fight("II")
    log.close()
    assert [f["at_move"] for f in got["fights"]] == [1]
    assert got["side_prompts"] == [{"side": "2", "at_move": 1, "fight": False}]


def test_walk_fight_stops_on_a_side_prompt_that_never_clears(tmp_path, monkeypatch):
    sess = SideFightWalk({0}, linger=10 ** 6)
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    with pytest.raises(A.StepFailed, match="stayed up"):
        run.walk_fight("I")
    log.close()
    assert sess.keys_sent == 1


@pytest.mark.parametrize("side", ["1", "3", "4"])
def test_walk_fight_stops_on_a_side_it_does_not_answer_saying_which(
        tmp_path, monkeypatch, side):
    sess = SideFightWalk({0})
    sess.PROMPT = f"INSERT SIDE # {side}, AND PRESS ANY KEY."
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    with pytest.raises(A.StepFailed, match=f"asks for side {side} mid-walk"):
        run.walk_fight("I")
    log.close()
    assert sess.keys_sent == 0


def test_walk_fight_resends_a_key_the_fight_left_unfinished_once(tmp_path, monkeypatch):
    sess = FightWalk({0: "fight-stay"})
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    got = run.walk_fight("I")
    log.close()
    assert sess.pressed == ["I", "I"]
    assert got["position"] == [5, 4, 0] and got["moves"][0]["resent"] is True


def test_walk_fight_that_stays_after_the_resend_fails(tmp_path, monkeypatch):
    sess = FightWalk({0: "unread", 1: "unread"})
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    with pytest.raises(A.StepFailed, match="sent twice"):
        run.walk_fight("I")
    log.close()
    assert sess.pressed == ["I", "I"]


def test_walk_fight_resends_a_key_the_game_did_not_read(tmp_path, monkeypatch):
    sess = FightWalk({0: "unread"})
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    got = run.walk_fight("I")
    log.close()
    assert sess.pressed == ["I", "I"] and got["position"] == [5, 4, 0]


def test_walk_fight_does_not_resend_a_bump_the_game_read(tmp_path, monkeypatch):
    sess = FightWalk({}, walls={(5, 4)})
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    with pytest.raises(A.StepFailed, match="sent once"):
        run.walk_fight("I")
    log.close()
    assert sess.pressed == ["I"]


def test_walk_fight_does_not_resend_a_move_a_lagging_position_did_not_show(
        tmp_path, monkeypatch):
    """A squareless status line: `walk_one` saw the party move by the live
    square, and `position()` still reads the old one."""
    sess = FightWalk({})
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    run.position = lambda: [5, 5, 0]
    with pytest.raises(A.StepFailed, match="sent once"):
        run.walk_fight("I")
    log.close()
    assert sess.pressed == ["I"], "a second step was taken"


def test_walk_fight_with_no_facing_fails_the_step_and_does_not_crash(
        tmp_path, monkeypatch):
    for facing in ((None, 0), (0, None)):
        sess = FightWalk({})
        run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
        reads = iter([[5, 5, facing[0]]] + [[5, 4, facing[1]]] * 20)
        run.position = lambda: next(reads)
        with pytest.raises(A.StepFailed, match="facing was not read"):
            run.walk_fight("I")
        log.close()


def test_walk_fight_takes_combat_on_an_encounter_menu_and_never_flee(
        tmp_path, monkeypatch):
    sess = FightWalk({0: "encounter"})
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    got = run.walk_fight("II")
    log.close()
    assert sess.selected == ["COMBAT"]
    assert len(got["fights"]) == 1 and got["position"] == [5, 3, 0]


def test_walk_flee_answers_an_encounter_menu_with_flee_and_records_the_escape(
        tmp_path, monkeypatch):
    sess = FightWalk({0: "encounter"})
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    got = run.walk_flee("II")
    log.close()
    assert sess.selected == ["FLEE"]
    flee = got["flees"][0]
    assert (flee["at_move"], flee["escaped"], flee["fight"]) == (0, True, None)
    assert got["fights"] == [] and sess.tactics == []
    assert sess.encounter_words == [A.ENCOUNTER_FLEE] * 2
    assert sess.walk_encounter is None


def test_walk_flee_escape_that_leaves_the_move_key_wait_bar_is_an_escape(
        tmp_path, monkeypatch):
    """After "THE PARTY FLEES" the game shows `I,J,K,M, RETURN OR BUTTON`, not
    the world bar; the route goes on and presses only its own move keys."""
    sess = FightWalk({0: "encounter"})
    select = sess.select_bar

    def flee_leaves_subbar(label, *a, **k):
        select(label, *a, **k)
        if label == "FLEE":
            sess.screens = {"world": _window({}, "I,J,K,M, RETURN OR BUTTON")}
        return True

    sess.select_bar = flee_leaves_subbar
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    got = run.walk_flee("II")
    log.close()
    assert sess.selected == ["FLEE"]
    assert got["flees"][0]["escaped"] is True
    assert sess.pressed == ["I", "I"]


def _subbar_after_flee(sess):
    select = sess.select_bar

    def flee_leaves_subbar(label, *a, **k):
        select(label, *a, **k)
        if label == "FLEE":
            sess.screens = {"world": _window({}, "I,J,K,M, RETURN OR BUTTON")}
        return True

    sess.select_bar = flee_leaves_subbar


def test_walk_flee_move_bar_seen_once_before_a_fight_is_not_an_escape(
        tmp_path, monkeypatch):
    """The move bar lingers while a caught party's fight loads."""
    sess = FightWalk({0: "encounter"})
    _subbar_after_flee(sess)
    looks = []

    def in_combat():
        if "FLEE" not in sess.selected:
            return False
        looks.append(1)
        # The bar is up with no fight for the first two looks, which a caller
        # that read the bar once and asked again would take as an escape; the
        # fight is loaded by the third.
        return len(looks) >= 3

    sess.in_combat = in_combat
    fight = sess.fight

    def fight_then_world(*a, **k):
        sess.screens = {"world": _window({}, WORLD_BAR)}
        return fight(*a, **k)

    sess.fight = fight_then_world
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    got = run.walk_flee("I")
    log.close()
    assert got["flees"][0]["escaped"] is False
    assert len(got["fights"]) == 1


def test_walk_flee_writes_its_flee_line_to_the_log_when_the_step_later_fails(
        tmp_path, monkeypatch):
    sess = FightWalk({0: "encounter"}, walls={(5, 3)})
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    with pytest.raises(A.StepFailed):
        run.walk_flee("II")
    log.close()
    events = [json.loads(line) for line in
              (tmp_path / "run.jsonl").read_text().splitlines()]
    assert [(e["at_move"], e["escaped"]) for e in events
            if e["kind"] == "flee"] == [(0, True)]


def test_walk_flee_that_fails_opens_a_fight_and_reports_its_result(
        tmp_path, monkeypatch):
    sess = FightWalk({0: "encounter"})
    sess.flee_fails = True
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    got = run.walk_flee("II")
    log.close()
    assert sess.selected == ["FLEE"]
    assert len(got["fights"]) == 1
    assert got["flees"][0]["escaped"] is False
    assert got["flees"][0]["fight"] == got["fights"][0]


def test_walk_flee_that_ends_in_neither_fight_nor_world_bar_fails_not_hangs(
        tmp_path, monkeypatch):
    sess = FightWalk({0: "encounter"})
    sess.flee_fails = False
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    world = run.at_world
    run.at_world = lambda bar: not sess.selected and world(bar)
    with pytest.raises(A.StepFailed, match="answered FLEE and neither a fight"):
        run.walk_flee("I")
    log.close()


def test_walk_flee_records_where_each_flee_left_the_party(tmp_path, monkeypatch):
    sess = FightWalk({0: "encounter"})
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    got = run.walk_flee("I")
    log.close()
    assert got["flees"][0]["before"] == [5, 5, 0]
    assert got["flees"][0]["after"] == [5, 4, 0]


def test_walk_flee_an_escape_with_no_facing_read_fails_the_step(
        tmp_path, monkeypatch):
    sess = FightWalk({0: "encounter"})
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    run.position = lambda: [9, 9, None] if sess.selected else [5, 5, 0]
    with pytest.raises(A.StepFailed, match="facing was not read"):
        run.walk_flee("I")
    log.close()


def test_walk_flee_a_caught_flee_is_judged_as_walk_fight_judges_it(
        tmp_path, monkeypatch):
    sess = FightWalk({0: "encounter"})
    sess.flee_fails = True

    def fight(budget, tactic, stop=None):
        sess.combat = False
        sess.x, sess.y = 9, 9
        return A.S.FightResult(A.S.WON, 3, 1.0, [], [])

    sess.fight = fight
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    with pytest.raises(A.StepFailed, match="an exit or a teleport"):
        run.walk_flee("I")
    log.close()


class PressAfterFlee(FightWalk):
    """FLEE brings up a `PRESS` page; a Return leads back to the world."""

    def __init__(self, script, **kw):
        super().__init__(script, **kw)
        self.screens["press"] = _window({3: "YOU GET AWAY."}, ARRIVAL_BAR)
        self.moves[("press", ("key", 0x0D))] = "world"

    def select_bar(self, label, row=24, timeout=0, **kw):
        if label == "FLEE":
            self.selected.append(label)
            self.pending, self.state = None, "press"
            return True
        return super().select_bar(label, row, timeout, **kw)


def test_walk_flee_answers_a_press_page_after_flee(tmp_path, monkeypatch):
    sess = PressAfterFlee({0: "encounter"})
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    got = run.walk_flee("I")
    log.close()
    assert sess.sent == [("key", 0x0D)]
    assert got["flees"][0]["escaped"] is True


def test_walk_flee_an_encounter_menu_without_flee_fails_and_presses_nothing(
        tmp_path, monkeypatch):
    sess = FightWalk({0: "encounter"})
    sess.ENCOUNTER = "COMBAT WAIT ADVANCE"
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    with pytest.raises(A.StepFailed, match="does not answer"):
        run.walk_flee("I")
    log.close()
    assert sess.selected == []


class AmbushWalk(FightWalk):
    """A move key can bring up a `PRESS` page with no encounter menu:
    "ambush" then a Return opens a fight, "ambush-stay" leaves the party on
    its square and a Return returns to the world bar, "late-ambush" draws the
    bar only after several screen reads; "ambush-menu" follows the Return
    with an encounter menu.  Runs are Curse's (`walk_encounters` False)."""

    def __init__(self, script, **kw):
        super().__init__(script, **kw)
        self.screens["press"] = _window({3: "SKELETONS SILENTLY ATTACK."},
                                        ARRIVAL_BAR)
        self.moves[("press", ("key", 0x0D))] = "world"
        self.opens_fight = False
        self.menu_after = False
        self.late_reads = None

    def screen(self):
        if self.late_reads is not None:
            self.late_reads -= 1
            if self.late_reads <= 0:
                self.late_reads, self.state = None, "press"
        return super().screen()

    def walk_one(self, move, *a, **k):
        event = self.script.get(self.calls)
        before = (self.x, self.y)
        moved = super().walk_one(move, *a, **k)
        if event == "late-ambush":
            self.late_reads, self.opens_fight = 9, True
        if event == "ambush-menu":
            self.state, self.menu_after = "press", True
        if event in ("ambush", "ambush-stay"):
            self.state = "press"
            self.opens_fight = event == "ambush"
            if event == "ambush-stay":
                self.x, self.y = before
        return moved

    def press_kernal(self, code):
        super().press_kernal(code)
        if self.opens_fight:
            self.combat, self.opens_fight = True, False
        if self.menu_after:
            self.pending, self.menu_after = _stop_rows(self.ENCOUNTER), False


class TreasureAfterFightWalk(AmbushWalk):
    """A won fight on the first move; the second move's `PRESS` page, once
    answered, puts up a treasure screen (mode 5) whose bar is `bar`, and EXIT
    puts the world bar back."""

    def __init__(self, bar="VIEW POOL EXIT", then=None, exit_works=True,
                 exit_clears=True, **kw):
        super().__init__({0: "fight"}, **kw)
        self.screens["treasure"] = _window({3: "THE POOL HOLDS GOLD."}, bar)
        self.screens["treasure2"] = _window({3: "MORE GOLD."}, then or "")
        self.then, self.exit_works, self.exit_clears = then, exit_works, exit_clears
        self.moves[("press", ("key", 0x0D))] = "treasure"

    def mode(self):
        return (A.TREASURE_MODE if self.state in ("treasure", "treasure2")
                else A.S.DUNGEON)

    def walk_one(self, move, *a, **k):
        moved = FightWalk.walk_one(self, move, *a, **k)
        if self.calls == 2:
            self.state = "press"
        return moved

    def select_bar(self, label, row=24, timeout=0, **kw):
        if label == "EXIT" and self.exit_works and self.exit_clears:
            if self.state == "treasure" and self.then:
                self.state = "treasure2"
            elif self.state in ("treasure", "treasure2"):
                self.state = "world"
        super().select_bar(label, row, timeout, **kw)
        return self.exit_works


@pytest.mark.parametrize("verb", ["walk_fight", "walk_flee"])
def test_walk_fight_leaves_a_treasure_screen_met_on_the_walk_after_a_fight(
        tmp_path, monkeypatch, verb):
    sess = TreasureAfterFightWalk()
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    got = getattr(run, verb)("II")
    log.close()
    assert sess.selected[-1] == "EXIT" and sess.state == "world"
    assert [f["at_move"] for f in got["fights"]] == [0]
    assert got["treasure_screens"] == [
        {"at_move": 1, "bar": "VIEW POOL EXIT", "mode": A.TREASURE_MODE}]
    assert sess.pressed == ["I", "I"]


def test_walk_fight_leaves_a_second_treasure_screen_in_the_same_key(
        tmp_path, monkeypatch):
    sess = TreasureAfterFightWalk(then="VIEW TAKE POOL SHARE EXIT")
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    got = run.walk_fight("II")
    log.close()
    assert [t["bar"] for t in got["treasure_screens"]] == [
        "VIEW POOL EXIT", "VIEW TAKE POOL SHARE EXIT"]
    assert sess.state == "world"


def test_walk_fight_fails_naming_the_treasure_bar_when_exit_cannot_be_chosen(
        tmp_path, monkeypatch):
    sess = TreasureAfterFightWalk(exit_works=False)
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    with pytest.raises(A.StepFailed, match=r"'VIEW POOL EXIT' and EXIT could not"):
        run.walk_fight("II")
    log.close()
    assert run.walk_treasures == []


def test_walk_fight_fails_naming_the_treasure_bar_that_exit_does_not_clear(
        tmp_path, monkeypatch):
    sess = TreasureAfterFightWalk(exit_clears=False)
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    with pytest.raises(A.StepFailed, match="row 24 reads 'VIEW POOL EXIT', mode 5"):
        run.walk_fight("II")
    log.close()
    assert sess.selected.count("EXIT") == 1


def test_walk_fight_waits_out_a_slow_encounter_load_after_a_side_prompt_and_sends_one_key(
        tmp_path, monkeypatch):
    """The real `walk_one` returns False at the prompt with the party still
    on its square, and the fight can take longer than the look for one; the
    key was read, so it is not sent again into the loading encounter, and the
    move is judged only once the fight is up."""
    sess = SideFightWalk({0}, fight_delay=int(A.LOOK_SECONDS / 0.3) + 20)
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    got = run.walk_fight("I")
    log.close()
    assert sess.pressed == ["I"]
    assert [f["at_move"] for f in got["fights"]] == [0]
    assert got["position"] == [5, 4, 0]


def test_walk_fight_fails_naming_the_side_2_answer_when_nothing_follows_it(
        tmp_path, monkeypatch):
    sess = SideFightWalk({0}, fight_delay=10 ** 6)
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    with pytest.raises(A.StepFailed, match="answered the side 2 prompt and no fight"):
        run.walk_fight("I")
    log.close()
    assert sess.pressed == ["I"]


class SideAmbushWalk(AmbushWalk):
    """An ambush whose PRESS bar, once answered, puts the side 2 prompt up
    before the fight opens."""

    PROMPT = SideFightWalk.PROMPT

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.prompt_up, self.attaches = False, []

    def screen(self):
        if self.prompt_up:
            return _Text(_window({}, self.PROMPT))
        return super().screen()

    def press_kernal(self, code):
        self.opens_fight = False
        super().press_kernal(code)
        self.prompt_up = True

    def handle_prompt(self, s=None):
        self.attaches.append(self.wanted_disk(s))
        self.prompt_up, self.combat = False, True
        return True


@pytest.mark.parametrize("verb", ["walk_fight", "walk_flee"])
def test_walk_fight_answers_a_side_prompt_that_comes_up_after_an_ambush_press_bar(
        tmp_path, monkeypatch, verb):
    sess = SideAmbushWalk({0: "ambush"})
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    got = getattr(run, verb)("I")
    log.close()
    assert sess.attaches == ["SIDE2.D64"]
    assert [f["at_move"] for f in got["fights"]] == [0]
    assert got["side_prompts"][0]["fight"] is True


@pytest.mark.parametrize("verb", ["walk_fight", "walk_flee"])
def test_an_ambush_press_bar_opens_a_fight_that_is_fought_and_the_route_goes_on(
        tmp_path, monkeypatch, verb):
    sess = AmbushWalk({0: "ambush"})
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    got = getattr(run, verb)("II")
    log.close()
    assert sess.sent == [("key", 0x0D)]
    assert [f["at_move"] for f in got["fights"]] == [0]
    assert got["position"] == [5, 3, 0] and sess.pressed == ["I", "I"]
    if verb == "walk_flee":
        assert [(f["at_move"], f["escaped"], f["ambush"], f["fight"])
                for f in got["flees"]] == [(0, False, True, got["fights"][0])]


@pytest.mark.parametrize("verb", ["walk_fight", "walk_flee"])
def test_an_ambush_press_bar_that_returns_to_the_same_square_sends_the_move_again(
        tmp_path, monkeypatch, verb):
    sess = AmbushWalk({0: "ambush-stay"})
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    run.walk_encounters = False
    got = getattr(run, verb)("I")
    log.close()
    assert sess.pressed == ["I", "I"]
    assert got["moves"][0]["resent"] is True
    assert got["position"] == [5, 4, 0] and got["fights"] == []


def test_a_press_bar_that_draws_after_the_first_look_is_answered_and_fought(
        tmp_path, monkeypatch):
    sess = AmbushWalk({0: "late-ambush"})
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    run.walk_encounters = False
    got = run.walk_fight("II")
    log.close()
    assert sess.sent == [("key", 0x0D)]
    assert [f["at_move"] for f in got["fights"]] == [0]
    assert sess.pressed == ["I", "I"]


def test_an_ambush_page_on_a_square_the_party_entered_is_not_sent_again(
        tmp_path, monkeypatch):
    sess = AmbushWalk({0: "ambush-stay"})
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    run.walk_encounters = False
    run.took_nothing = lambda *a: False
    with pytest.raises(A.StepFailed, match="left the party on"):
        run.walk_fight("I")
    log.close()
    assert sess.pressed == ["I"]


def test_curse_walk_fight_does_not_opt_in_and_keeps_the_ambush_handling(
        tmp_path, monkeypatch):
    assert A.CurseRun.walk_encounters is False
    sess = AmbushWalk({0: "ambush-stay"})
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    run.walk_encounters = A.CurseRun.walk_encounters
    run.walk_fight("I")
    log.close()
    assert sess.pressed == ["I", "I"]


def test_a_narration_page_then_a_flee_menu_records_one_flee_with_its_fight(
        tmp_path, monkeypatch):
    sess = AmbushWalk({0: "ambush-menu"})
    sess.flee_fails = True
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    got = run.walk_flee("I")
    log.close()
    assert sess.selected == ["FLEE"]
    assert len(got["flees"]) == 1
    flee = got["flees"][0]
    assert flee["fight"] == got["fights"][0] and "ambush" not in flee
    assert flee["before"] == [5, 5, 0] and flee["after"] == [5, 4, 0]


def test_walk_flee_parses_and_is_refused_for_curse_and_silver_blades(
        tmp_path, capsys):
    assert A.parse_steps(["load", "walk-flee IIK/NO"])[1] == A.Step(
        "walk-flee", "IIK/NO")
    with pytest.raises(ValueError):
        A.parse_steps(["load", "walk-flee"])
    for cls in (A.CurseRun, A.SilverRun):
        run = cls.__new__(cls)
        run.fail = lambda tag, why: A.StepFailed(why)
        with pytest.raises(A.StepFailed, match="Pool of Radiance only"):
            run.walk_flee("I")


@pytest.mark.parametrize("outcome, match", [
    (A.S.LOST, "the party lost the fight after 3 turns"),
    (A.S.BUDGET, "ran out of its 900 second budget")])
def test_walk_fight_a_lost_or_overlong_fight_fails_the_step(
        tmp_path, monkeypatch, outcome, match):
    sess = FightWalk({0: "fight"}, outcome=outcome)
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    with pytest.raises(A.StepFailed, match=match):
        run.walk_fight("II")
    log.close()
    assert sess.walk_encounter is None


def test_walk_fight_answers_no_only_on_the_last_key(tmp_path, monkeypatch):
    sess = FightWalk({1: "yesno"})
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    got = run.walk_fight("II/NO")
    log.close()
    assert sess.selected == ["NO"] and len(got["fights"]) == 1
    assert got["answer"] == "NO"


@pytest.mark.parametrize("route, script", [("III/NO", {0: "yesno"}),
                                           ("II", {1: "yesno"})])
def test_walk_fight_refuses_a_yes_no_anywhere_else_and_presses_nothing(
        tmp_path, monkeypatch, route, script):
    sess = FightWalk(script)
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    with pytest.raises(A.StepFailed, match="nothing was pressed"):
        run.walk_fight(route)
    log.close()
    assert sess.selected == []


def test_walk_fight_a_position_after_the_fight_that_is_not_ahead_is_a_teleport(
        tmp_path, monkeypatch):
    sess = FightWalk({0: ("teleport", 1, 6)})
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    with pytest.raises(A.StepFailed, match="an exit or a teleport"):
        run.walk_fight("I")
    log.close()


def test_walk_fight_parses_its_route_and_answer():
    assert A.parse_steps(["load", "walk-fight IIK"])[1] == A.Step("walk-fight", "IIK")
    assert A.parse_walk_fight("iik/no") == ("IIK", "NO")
    assert A.parse_walk_fight("IIK") == ("IIK", None)
    for bad in ("walk-fight", "walk-fight IIX", "walk-fight IIK/YES",
                "walk-fight IIK/"):
        with pytest.raises(ValueError):
            A.parse_steps(["load", bad])


def test_the_walk_fight_step_is_refused_for_curse_and_silver_blades(tmp_path, capsys):
    for title in ("curse", "ssb"):
        with pytest.raises(SystemExit) as info:
            A.main(["--title", title, "--save", str(_fixture_disk(tmp_path)),
                    "--disks", str(tmp_path), "--steps", "load", "walk-fight I",
                    "--out", str(tmp_path / "out")])
        assert info.value.code == 2
        assert "walk-fight step: Pool of Radiance only" in capsys.readouterr().err
    for cls in (A.CurseRun, A.SilverRun):
        run = cls.__new__(cls)
        run.fail = lambda tag, why: A.StepFailed(why)
        with pytest.raises(A.StepFailed, match="Pool of Radiance only"):
            run.walk_fight("I")


def _drain_fields(level=5, drained=0, lost=0, hp=40, classes=(0, 0, 0, 5)):
    return [{"slot": 0, "name": "AVA", "level": level, "levels_drained": drained,
             "hp_lost_to_drain": lost, "hp_max": hp,
             "class_levels": list(classes) + [0] * (8 - len(classes))}]


@pytest.mark.parametrize("drop", [1, 2])
def test_the_drain_pass_line_accepts_a_drop_of_one_or_two_levels(drop):
    after = _drain_fields(5 - drop, drop, 7, 33, (0, 0, 0, 5 - drop))
    verdict = A.drain_verdict(_drain_fields(), after)
    assert verdict["passed"] is True
    assert verdict["characters"][0]["problems"] == []


def test_the_drain_pass_line_refuses_no_drop():
    verdict = A.drain_verdict(_drain_fields(), _drain_fields())
    assert verdict["passed"] is False
    assert any("not exactly one entry by 1 or 2" in p
               for p in verdict["characters"][0]["problems"])


def test_the_drain_pass_line_refuses_a_drop_with_zero_drain_bytes():
    after = _drain_fields(4, 0, 0, 40, (0, 0, 0, 4))
    verdict = A.drain_verdict(_drain_fields(), after)
    assert verdict["passed"] is False
    problems = verdict["characters"][0]["problems"]
    assert any("levels_drained is 0" in p for p in problems)
    assert any("hp_lost_to_drain is zero" in p for p in problems)


def test_the_drain_pass_line_refuses_a_drop_of_three_and_a_wrong_hit_point_fall():
    assert A.drain_verdict(_drain_fields(),
                           _drain_fields(2, 3, 9, 31, (0, 0, 0, 2)))["passed"] is False
    assert A.drain_verdict(_drain_fields(),
                           _drain_fields(4, 1, 7, 30, (0, 0, 0, 4)))["passed"] is False


def test_the_drain_fields_read_the_offsets_the_layout_names():
    rec = A.CharacterRecord.blank()
    rec.set("name", "AVA")
    rec.set("level", 4)
    rec.set("levels_drained", 1)
    rec.set("hp_lost_to_drain", 6)
    rec.set("hp_max", 300)
    data = bytearray(rec.to_bytes())
    data[0xCC] = 4
    got = A.drain_fields([bytes(data), bytes(len(data))])
    assert got == [{"slot": 0, "name": "AVA", "level": 4, "levels_drained": 1,
                    "hp_lost_to_drain": 6, "hp_max": 300,
                    "class_levels": [0, 0, 0, 4, 0, 0, 0, 0]}]


def test_the_drain_pass_line_accepts_a_lower_class_drained_with_the_level_unchanged():
    before = _drain_fields(7, 0, 0, 60, (5, 0, 0, 7))
    after = _drain_fields(7, 1, 6, 54, (4, 0, 0, 7))
    assert A.drain_verdict(before, after)["passed"] is True


def test_the_drain_pass_line_accepts_one_of_two_equal_classes_with_the_level_unchanged():
    before = _drain_fields(6, 0, 0, 60, (6, 0, 0, 6))
    after = _drain_fields(6, 1, 6, 54, (5, 0, 0, 6))
    assert A.drain_verdict(before, after)["passed"] is True


def test_the_drain_pass_line_needs_the_level_to_fall_when_the_top_class_drained():
    before = _drain_fields(7, 0, 0, 60, (5, 0, 0, 7))
    after = _drain_fields(7, 1, 6, 54, (5, 0, 0, 6))
    verdict = A.drain_verdict(before, after)
    assert verdict["passed"] is False
    assert any("the drained class was the highest" in p
               for p in verdict["characters"][0]["problems"])


def test_the_drain_pass_line_refuses_two_classes_drained():
    before = _drain_fields(7, 0, 0, 60, (5, 0, 0, 7))
    after = _drain_fields(6, 2, 6, 54, (4, 0, 0, 6))
    assert A.drain_verdict(before, after)["passed"] is False


def test_the_drain_summary_takes_the_first_save_after_the_last_walk_fight():
    staged = {"drain_fields": _drain_fields()}
    good = _drain_fields(4, 1, 7, 33, (0, 0, 0, 4))
    results = [{"verb": "save", "drain_fields": _drain_fields()},
               {"verb": "walk-fight"},
               {"verb": "save", "drain_fields": good},
               {"verb": "save", "drain_fields": _drain_fields()}]
    assert A.drain_summary(results, staged)["passed"] is True
    got = A.drain_summary(results[:2], staged)
    assert got["passed"] is None and "no save step" in got["why"]
    assert A.drain_summary([{"verb": "walk-fight"}] + results[:1],
                           staged)["passed"] is False


# --- an encounter the move started, measured on the C64 ------------------------------

class EncounterWalk(WalkSession):
    """The measured sequence after a step onto an encounter square: the status
    line and row 24 (the old move bar) stay as they were for 12 s while
    `$C04B` already holds the new square, then a `PRESS` bar (kind "press") or
    the sneak-up menu (kind "menu") is drawn and waits for an answer; 22 s
    after the answer row 24 is blank and LINKER's byte reads 4 (COM.PREP), then
    2.  Kind "none" is a step whose encounter ends without a fight: the world
    bar and the compass catch up together.  `script` maps the `walk_one` call
    number to a kind; other calls are ordinary steps."""

    OLD_BAR = A.S.MOVE_SUBBAR + ", RETURN OR BUTTON"
    MENU = "COMBAT WAIT FLEE PARLAY"
    DRAW, PREP = 12.0, 22.0

    def __init__(self, script, clock, **kw):
        super().__init__(**kw)
        self.script, self.timer = script, clock
        self.calls = 0
        self.opted_in = None
        self.kind = self.started = self.answered = self.new = None
        self.done = False
        self.walk_encounter_started = False
        self.walk_stop_screen = None
        self.presses = []
        self.left = []
        self.tactics = []

    def _live_square(self, steady=False):
        return self.live_triple()[:2]

    def leave_move(self, *a, **k):
        self.left.append(self.phase())
        if self.kind is not None and not self.done:
            self.x, self.y = self.new
            self.done = True
        return True

    def phase(self):
        if self.kind is None or self.done:
            return "idle"
        t = self.timer() - self.started
        if self.answered is not None:
            return "fight" if self.timer() - self.answered >= self.PREP else "prep"
        if self.kind == "none":
            return "idle" if t >= 3 else "stale"
        return "stale" if t < self.DRAW else (
            "press" if self.kind == "text" else self.kind)

    def walk_one(self, move, *a, **k):
        self.opted_in = k.get("encounters", False)
        self.walk_encounter_started = False
        event = self.script.get(self.calls)
        self.calls += 1
        if event is None:
            return super().walk_one(move)
        self.pressed.append(move)
        self.kind, self.started, self.answered, self.done = (
            event, self.timer(), None, False)
        self.text_only = event == "text"
        self.new = (self.x, self.y - 1)
        self.walk_encounter_started = True
        return True

    def mode(self):
        return {"prep": 4, "fight": 2}.get(self.phase(), 1)

    def in_combat(self):
        return self.mode() == 2

    def live_triple(self):
        assert self.mode() == 1, "the live square was read outside mode 1"
        if self.kind is not None and not self.done:
            return (*self.new, self.facing)
        return (self.x, self.y, self.facing)

    def screen(self):
        phase = self.phase()
        if phase == "none":
            phase = "idle"
        if phase == "idle" and self.kind == "none" and not self.done:
            self.x, self.y = self.new
            self.done = True
        bar = {"stale": self.OLD_BAR, "press": ARRIVAL_BAR, "menu": self.MENU,
               "idle": WORLD_BAR}.get(phase, "")
        text = {"press": {3: "SKELETONS SILENTLY ATTACK."},
                "menu": {3: "YOU HAVE MANAGED TO SNEAK UP."},
                "prep": {3: "THE PARTY ATTACKS"}}.get(phase, {})
        return FakeScreen(_window(text, bar))

    def press_kernal(self, code):
        self.presses.append((code, self.phase()))
        if self.phase() == "press":
            self.answered = self.timer()
            if self.kind == "text":
                self.x, self.y = self.new
                self.done = True

    def select_bar(self, label, row=24, timeout=0, **kw):
        self.presses.append((label, self.phase()))
        if self.phase() == "menu" and label in ("COMBAT", "FLEE"):
            self.answered = self.timer()
            return True
        return False

    def fight(self, budget, tactic, stop=None):
        self.tactics.append(budget)
        self.x, self.y = self.new
        self.done = True
        return A.S.FightResult(A.S.WON, 3, 1.0, [], [])


def _encounter_run(tmp_path, monkeypatch, script):
    sess = EncounterWalk(script, None)
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    sess.timer = run.clock
    return sess, run, log


def test_an_encounter_step_presses_nothing_until_the_press_bar_then_one_return(
        tmp_path, monkeypatch):
    sess, run, log = _encounter_run(tmp_path, monkeypatch, {0: "press"})
    got = run.walk_fight("I")
    log.close()
    assert sess.presses == [(0x0D, "press")]
    assert sess.pressed == ["I"]
    assert got["moves"][0]["resent"] is False
    assert [f["at_move"] for f in got["fights"]] == [0]
    assert got["position"] == [5, 4, 0] and sess.tactics == [A.WALK_FIGHT_SECONDS]


def test_an_encounter_step_answers_the_sneak_up_menu_combat_once(tmp_path, monkeypatch):
    sess, run, log = _encounter_run(tmp_path, monkeypatch, {0: "menu"})
    got = run.walk_fight("I")
    log.close()
    assert sess.presses == [("COMBAT", "menu")]
    assert sess.pressed == ["I"] and len(got["fights"]) == 1


def test_an_encounter_step_answers_the_sneak_up_menu_flee_for_walk_flee(
        tmp_path, monkeypatch):
    sess, run, log = _encounter_run(tmp_path, monkeypatch, {0: "menu"})
    got = run.walk_flee("I")
    log.close()
    assert sess.presses == [("FLEE", "menu")]
    assert sess.pressed == ["I"]
    assert [(f["at_move"], f["escaped"]) for f in got["flees"]] == [(0, False)]


def test_an_encounter_that_ends_without_a_fight_is_not_resent(tmp_path, monkeypatch):
    sess, run, log = _encounter_run(tmp_path, monkeypatch, {0: "none"})
    got = run.walk_fight("I")
    log.close()
    assert sess.presses == [] and sess.pressed == ["I"]
    assert got["fights"] == [] and got["position"] == [5, 4, 0]


class EncounterTreasureWalk(EncounterWalk):
    """An encounter square whose `PRESS` page, once answered, leads to a
    treasure screen (mode 5) instead of a fight: `VIEW TAKE POOL SHARE EXIT`,
    and with `leave_prompt` EXIT opens `GO BACK LEAVE TREASURE` before the
    world comes back."""

    TREASURE = "VIEW TAKE POOL SHARE EXIT"
    LEAVE = "GO BACK LEAVE TREASURE"

    def __init__(self, script, clock, leave_prompt=False, refuse=None,
                 sticky=False, blink=False, **kw):
        super().__init__(script, clock, **kw)
        self.leave_prompt = leave_prompt
        self.refuse, self.sticky, self.blink = refuse, sticky, blink
        self.reads = 0
        self.stage = None
        self.chosen = []

    def phase(self):
        if self.stage is not None and not self.done:
            return self.stage
        phase = super().phase()
        if phase == "prep":
            self.stage = "treasure"
        return self.stage if self.stage and not self.done else phase

    def mode(self):
        return 5 if self.phase() == "treasure" else super().mode()

    def screen(self):
        phase = self.phase()
        if phase in ("treasure", "leave"):
            self.reads += 1
            bar = self.TREASURE if phase == "treasure" else self.LEAVE
            if self.blink and self.reads % 2:
                bar = ""
            return FakeScreen(_window({3: "THE ROOM HOLDS GOLD."}, bar))
        return super().screen()

    def select_bar(self, label, row=24, timeout=0, **kw):
        phase = self.phase()
        self.chosen.append((label, phase))
        if label == self.refuse:
            return False
        if self.sticky and phase in ("treasure", "leave"):
            return True
        if phase == "treasure" and label == "EXIT":
            if self.leave_prompt:
                self.stage = "leave"
            else:
                self._finish()
            return True
        if phase == "leave" and label == "LEAVE":
            self._finish()
            return True
        return super().select_bar(label, row, timeout, **kw)

    def _finish(self):
        self.stage = None
        self.x, self.y = self.new
        self.done = True


def _treasure_encounter_run(tmp_path, monkeypatch, **kw):
    sess = EncounterTreasureWalk({0: "press"}, None, **kw)
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    sess.timer = run.clock
    return sess, run, log


def test_a_treasure_screen_after_an_encounter_squares_press_bar_is_left_and_recorded(
        tmp_path, monkeypatch):
    sess, run, log = _treasure_encounter_run(tmp_path, monkeypatch)
    got = run.walk_fight("II")
    log.close()
    assert sess.chosen == [("EXIT", "treasure")]
    assert got["treasure_screens"] == [
        {"at_move": 0, "bar": sess.TREASURE, "mode": A.TREASURE_MODE}]
    assert got["fights"] == [] and sess.pressed == ["I", "I"]
    assert got["position"] == [5, 3, 0]


def test_exit_that_opens_the_leave_treasure_prompt_is_answered_with_leave(
        tmp_path, monkeypatch):
    sess, run, log = _treasure_encounter_run(tmp_path, monkeypatch,
                                             leave_prompt=True)
    got = run.walk_fight("II")
    log.close()
    assert sess.chosen == [("EXIT", "treasure"), ("LEAVE", "leave")]
    assert [t["bar"] for t in got["treasure_screens"]] == [
        sess.TREASURE, sess.LEAVE]
    assert got["position"] == [5, 3, 0]


@pytest.mark.parametrize("mode, row", [
    (4, "COMBAT WAIT FLEE PARLAY"),
    (5, "COMBAT WAIT FLEE PARLAY"),
    (1, "PRESS <RETURN> OR BUTTON TO CONTINUE"),
    (5, ""),
    (1, "GO BACK LEAVE"),
    (4, "VIEW TAKE POOL SHARE EXIT"),
])
def test_only_a_treasure_bar_is_taken_for_one(mode, row):
    assert A.PoolRun._walk_treasure_word(mode, row) is None


def test_the_treasure_words_are_told_apart():
    word = A.PoolRun._walk_treasure_word
    assert word(5, "VIEW TAKE POOL SHARE EXIT") == "EXIT"
    assert word(1, "GO BACK LEAVE TREASURE") == "LEAVE"


@pytest.mark.parametrize("refuse, leave_prompt, bar, word", [
    ("EXIT", False, "VIEW TAKE POOL SHARE EXIT", "EXIT"),
    ("LEAVE", True, "GO BACK LEAVE TREASURE", "LEAVE"),
])
def test_an_unchoosable_treasure_word_fails_naming_the_bar_and_the_word(
        tmp_path, monkeypatch, refuse, leave_prompt, bar, word):
    sess, run, log = _treasure_encounter_run(
        tmp_path, monkeypatch, refuse=refuse, leave_prompt=leave_prompt)
    with pytest.raises(A.StepFailed,
                       match=rf"treasure screen '{bar}' and {word} could not"):
        run.walk_fight("II")
    log.close()


@pytest.mark.parametrize("blink", [False, True])
def test_a_treasure_bar_that_stays_up_is_chosen_once_even_across_blank_redraws(
        tmp_path, monkeypatch, blink):
    sess, run, log = _treasure_encounter_run(
        tmp_path, monkeypatch, sticky=True, blink=blink)
    with pytest.raises(A.StepFailed, match="no fight opened"):
        run.walk_fight("II")
    log.close()
    assert sess.chosen == [("EXIT", "treasure")]
    assert sess.reads > 5
    assert len(run.walk_treasures) == 1


def test_walk_fight_answers_the_leave_treasure_prompt_met_after_a_press_bar(
        tmp_path, monkeypatch):
    class Leaving(TreasureAfterFightWalk):
        def select_bar(self, label, row=24, timeout=0, **kw):
            if label == "LEAVE" and self.state == "treasure2":
                self.state = "world"
            return super().select_bar(label, row, timeout, **kw)

    sess = Leaving(then="GO BACK LEAVE TREASURE")
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    got = run.walk_fight("II")
    log.close()
    assert sess.selected[-2:] == ["EXIT", "LEAVE"] and sess.state == "world"
    assert [t["bar"] for t in got["treasure_screens"]] == [
        "VIEW POOL EXIT", "GO BACK LEAVE TREASURE"]


def test_a_route_goes_on_after_an_encounter_step(tmp_path, monkeypatch):
    sess, run, log = _encounter_run(tmp_path, monkeypatch, {0: "press"})
    got = run.walk_fight("II")
    log.close()
    assert sess.pressed == ["I", "I"] and got["position"] == [5, 3, 0]


def test_an_encounter_that_never_draws_a_bar_fails_the_step(tmp_path, monkeypatch):
    sess, run, log = _encounter_run(tmp_path, monkeypatch, {0: "press"})
    sess.DRAW, sess.OLD_BAR = 1000.0, ""
    with pytest.raises(A.StepFailed, match="drew no bar or menu"):
        run.walk_fight("I")
    log.close()
    assert sess.presses == [] and sess.pressed == ["I"]


def test_an_ordinary_step_is_unchanged_by_the_encounter_wait(tmp_path, monkeypatch):
    sess, run, log = _encounter_run(tmp_path, monkeypatch, {})
    got = run.walk_fight("II")
    log.close()
    assert sess.presses == [] and got["fights"] == []
    assert got["position"] == [5, 3, 0]


def test_a_press_bar_with_no_fight_ends_the_move_at_the_world_bar(
        tmp_path, monkeypatch):
    sess, run, log = _encounter_run(tmp_path, monkeypatch, {0: "text"})
    start = run.clock()
    got = run.walk_fight("I")
    log.close()
    assert sess.presses == [(0x0D, "press")] and sess.pressed == ["I"]
    assert got["fights"] == [] and got["position"] == [5, 4, 0]
    assert run.clock() - start < 30, "waited out the fight-opens limit"


def test_a_move_bar_that_outlasts_the_draw_time_is_left_and_judged_by_position(
        tmp_path, monkeypatch):
    sess, run, log = _encounter_run(tmp_path, monkeypatch, {0: "press"})
    sess.DRAW = 1000.0
    got = run.walk_fight("I")
    log.close()
    assert sess.left == ["stale"] and sess.presses == []
    assert sess.pressed == ["I"] and got["fights"] == []
    assert got["position"] == [5, 4, 0]


def test_the_stale_bar_cutoff_counts_from_the_key_and_the_fallback_is_logged(
        tmp_path, monkeypatch):
    sess, run, log = _encounter_run(tmp_path, monkeypatch, {0: "press"})
    sess.DRAW = 1000.0
    sess.walk_encounter_age = 15.0
    start = run.clock()
    run.walk_fight("I")
    log.close()
    assert run.clock() - start < 6.0
    assert "encounter-stale-bar" in (tmp_path / "run.jsonl").read_text()


def test_only_pool_asks_walk_one_to_detect_encounters(tmp_path, monkeypatch):
    sess, run, log = _encounter_run(tmp_path, monkeypatch, {0: "none"})
    run.walk_fight("I")
    assert sess.opted_in is True
    sess2, run2, log2 = _encounter_run(tmp_path, monkeypatch, {0: "none"})
    run2.walk_encounters = False
    run2.walk_fight("I")
    log.close()
    log2.close()
    assert A.CurseRun.walk_encounters is False and A.SilverRun.walk_encounters is False
    assert sess2.opted_in is False


def test_the_walk_fight_budget_is_the_runs_own(tmp_path, monkeypatch):
    sess, run, log = _encounter_run(tmp_path, monkeypatch, {0: "press"})
    run.walk_fight_seconds = 1800.0
    run.walk_fight("I")
    log.close()
    assert sess.tactics == [1800.0] and A.WALK_FIGHT_SECONDS == 900.0


# --- the arrival text a warp leaves up ---------------------------------------------

ARRIVAL_BAR = "PRESS <RETURN> OR BUTTON TO CONTINUE"


class ArrivalWalk(FightWalk):
    """Starts on the first of `pages` identical arrival pages; each Return
    turns one, and the last leads to the world.  `pages` 0 never clears.
    Records the state the first move key found and when each Return came."""

    def __init__(self, pages, **kw):
        super().__init__({}, **kw)
        names = [f"press{i}" for i in range(max(pages, 1))]
        self.moves = {}
        for i, name in enumerate(names):
            self.screens[name] = _window({3: "YOU ARRIVE."}, ARRIVAL_BAR)
            after = (names[i + 1] if i + 1 < len(names)
                     else "world" if pages else name)
            self.moves[(name, ("key", 0x0D))] = after
        self.state = names[0]
        self.state_at_first_key = None
        self.walk_encounter = None
        self.stamp = lambda: None
        self.return_times = []

    def press_kernal(self, code):
        self.return_times.append(self.stamp())
        return super().press_kernal(code)

    def walk_one(self, move, *a, **k):
        if self.state_at_first_key is None:
            self.state_at_first_key = self.state
        return super().walk_one(move, *a, **k)


def test_walk_fight_answers_the_arrival_bar_once_before_its_first_key(
        tmp_path, monkeypatch):
    sess = ArrivalWalk(1)
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    run.walk_fight("I")
    log.close()
    assert sess.sent == [("key", 0x0D)]
    assert sess.state_at_first_key == "world" and sess.pressed == ["I"]


def test_walk_fight_answers_two_identical_arrival_pages_before_its_first_key(
        tmp_path, monkeypatch):
    sess = ArrivalWalk(2)
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    sess.stamp = run.clock
    run.walk_fight("I")
    log.close()
    assert sess.sent == [("key", 0x0D)] * 2
    # Identical pages cannot be told apart, so the first is given its whole
    # wait before the second Return; the first move key follows the second.
    assert sess.return_times[1] - sess.return_times[0] >= A.ARRIVAL_PAGE_SECONDS
    assert sess.state_at_first_key == "world" and sess.pressed == ["I"]


def test_walk_answers_the_arrival_bar_once_before_its_first_key(
        tmp_path, monkeypatch):
    sess = ArrivalWalk(1)
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    run.walk("I")
    log.close()
    assert sess.sent == [("key", 0x0D)]
    assert sess.state_at_first_key == "world"


def test_walk_fight_fails_naming_row_24_when_the_arrival_bar_never_clears(
        tmp_path, monkeypatch):
    sess = ArrivalWalk(0)
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    with pytest.raises(A.StepFailed, match="still reads 'PRESS <RETURN> OR BUTTON"):
        run.walk_fight("I")
    log.close()
    assert sess.sent == [("key", 0x0D)] * A.ARRIVAL_PRESSES
    assert sess.pressed == []


class LateMenuWalk(RealWalk):
    """The real `walk_one` over a party whose second step was taken normally
    (the compass moved) and whose encounter menu draws `DRAW` seconds after
    `MOVE` is taken on the next key, while the sub-bar never comes up.  The
    first step is ordinary."""

    MENU = "COMBAT WAIT FLEE ADVANCE"
    DRAW = 3.0

    def __init__(self, clock, **kw):
        super().__init__(clock, prompt_after=None, **kw)
        self.moves_taken = 0
        self.taken_at = None
        self.combat = False
        self.selected = []
        self.tactics = []

    def select_bar(self, label, row=24, timeout=30.0, answer_prompts=True):
        self.selected.append(label)
        if label == "MOVE":
            self.moves_taken += 1
            if self.moves_taken == 1:
                self.bar = A.S.MOVE_SUBBAR
            else:
                self.taken_at = self.clock.now
            return True
        if label in ("COMBAT", "FLEE") and self.bar == self.MENU:
            self.combat, self.bar = True, ""
            return True
        return False

    def screen(self):
        if (self.taken_at is not None and not self.combat
                and self.clock.now >= self.taken_at + self.DRAW):
            self.bar = self.MENU
        return super().screen()

    def mode(self):
        return A.S.COMBAT if self.combat else A.S.DUNGEON

    def in_combat(self):
        return self.combat

    def fight(self, budget, tactic, stop=None):
        self.tactics.append(tactic)
        self.combat, self.bar = False, WORLD_BAR
        self.y -= 1
        return A.S.FightResult(A.S.WON, 3, 1.0, [], [])


def test_an_encounter_menu_drawn_while_move_waits_for_its_sub_bar_is_answered_combat(
        tmp_path, monkeypatch):
    sess, run, log = _real_walk_with(LateMenuWalk, tmp_path, monkeypatch)
    got = run.walk_fight("II")
    log.close()
    assert sess.selected == ["MOVE", "MOVE", "COMBAT"]
    # The first step's own key and its Return; nothing at the menu.
    assert sess.keys == ["i", "Return"]
    assert [f["at_move"] for f in got["fights"]] == [1]
    assert sess.tactics == [A.S.Session.melee_turn]
    assert got["position"] == [5, 3, 0]


def test_the_same_late_menu_is_answered_flee_for_walk_flee(tmp_path, monkeypatch):
    sess, run, log = _real_walk_with(LateMenuWalk, tmp_path, monkeypatch)
    run._flee_settles = lambda: True
    run.walk_flee("II")
    log.close()
    assert sess.selected == ["MOVE", "MOVE", "FLEE"]
    assert sess.keys == ["i", "Return"]


def _real_walk_with(cls, tmp_path, monkeypatch, **kw):
    clock = _Clock(monkeypatch)
    sess = cls(clock, **kw)
    run, log = _walk_run(tmp_path, sess, clock)
    run.capture = lambda tag, rows=None: []
    run.reading = lambda: {}
    return sess, run, log


class RefusalFreeAmbush(AmbushWalk):
    """`walk_one` returns False with no refusal and no stop screen while an
    ambush's `PRESS` bar is up and the party has not moved."""

    def walk_one(self, move, *a, **k):
        if self.calls == 0:
            self.calls += 1
            self.state, self.opens_fight = "press", True
            self.walk_refused = self.walk_stop_screen = None
            self.walk_unsent_press_bar = True
            return False
        self.walk_unsent_press_bar = False
        return super().walk_one(move, *a, **k)


def test_walk_fight_answers_a_press_bar_walk_one_left_fights_and_resends_once(
        tmp_path, monkeypatch):
    sess = RefusalFreeAmbush({})
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    got = run.walk_fight("I")
    log.close()
    assert sess.sent == [("key", 0x0D)]
    assert [f["at_move"] for f in got["fights"]] == [0]
    assert sess.pressed == ["I"]
    assert got["moves"][0]["resent"] is False and got["position"] == [5, 4, 0]


class UnsentPressBar(AmbushWalk):
    """The square's text comes up at `MOVE` before the direction key is sent
    (drain boot 8, key 31).  Its `PRESS` bar is answered by one Return; row 24
    is then blank with the mode byte at 1 for `gap_seconds` of the run's clock,
    at 4 for `prep_seconds`, and then the mode byte reads 2 (`fight` True) or,
    with no fight, the world bar returns after the gap.  `walk_one` on a screen
    with no move bar presses nothing and refuses, as the real one does.
    `unsent_calls` says which `walk_one` calls send nothing."""

    TEXT = {17: "DARK, BENT CREATURES RUSH SWIFTLY AT", 18: "YOU."}
    REFUSAL = ("the driver pressed nothing for I: taking MOVE never brought "
               "up I,J,K,M; this is a driver error, not a wall")

    def __init__(self, script=None, fight=True, unsent_calls=(0,),
                 prep_seconds=20.8, gap_seconds=2.4, **kw):
        super().__init__(script or {}, **kw)
        self.screens["press"] = _window(self.TEXT, ARRIVAL_BAR)
        self.screens["prep"] = _window(self.TEXT, "")
        self.moves[("press", ("key", 0x0D))] = "prep"
        self.fight_follows, self.unsent_calls = fight, set(unsent_calls)
        self.prep_seconds, self.gap_seconds = prep_seconds, gap_seconds
        self.now = lambda: 0.0
        self.returned_at = None

    def screen(self):
        if (self.state == "prep" and not self.fight_follows
                and self.now() >= self.returned_at + self.gap_seconds):
            self.state = "world"
        return super().screen()

    def walk_one(self, move, *a, **k):
        self.walk_screens = self.walk_stop_screen = self.walk_refused = None
        self.walk_unsent_press_bar = False
        if self.calls in self.unsent_calls or "all" in self.unsent_calls:
            self.calls += 1
            self.state = "press"
            self.walk_unsent_press_bar = True
            return False
        row = self.screen().row(24)
        if not row.strip():
            self.walk_refused = self.REFUSAL
            return False
        return WalkSession.walk_one(self, move, *a, **k)

    def press_kernal(self, code):
        FakeSession.press_kernal(self, code)
        if self.state == "prep":
            self.returned_at = self.now()

    def mode(self):
        if self.returned_at is None:
            return A.S.DUNGEON
        if self.in_combat():
            return A.S.COMBAT
        since = self.now() - self.returned_at
        if since < self.gap_seconds or not self.fight_follows:
            return A.S.DUNGEON
        return A.COMBAT_PREP

    def in_combat(self):
        return (self.returned_at is not None and self.fight_follows
                and self.now() >= self.returned_at + self.gap_seconds
                + self.prep_seconds)

    def fight(self, budget, tactic, stop=None):
        self.returned_at, self.state = None, "world"
        self.fought = getattr(self, "fought", 0) + 1
        return A.S.FightResult(self.outcome, 3, 1.0, [], [])


def _run_events(tmp_path, kind):
    return [e for e in (json.loads(line) for line in
                        (tmp_path / "run.jsonl").read_text().splitlines())
            if e["kind"] == kind]


def test_walk_fight_answers_a_press_bar_that_came_up_at_move_and_waits_out_the_whole_load(
        tmp_path, monkeypatch):
    sess = UnsentPressBar()
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    sess.now = run.clock
    got = run.walk_fight("I")
    log.close()
    assert sess.sent == [("key", 0x0D)]
    assert [f["at_move"] for f in got["fights"]] == [0] and sess.fought == 1
    assert sess.pressed == ["I"]
    assert got["moves"][0]["resent"] is False and got["position"] == [5, 4, 0]
    modes = [e["mode"] for e in _run_events(tmp_path, "fight-wait")]
    assert modes == [1, 4, 2]


def test_walk_fight_with_an_unsent_press_bar_and_no_fight_sends_the_key(
        tmp_path, monkeypatch):
    sess = UnsentPressBar(fight=False)
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    sess.now = run.clock
    got = run.walk_fight("I")
    log.close()
    assert sess.sent == [("key", 0x0D)] and got["fights"] == []
    assert sess.pressed == ["I"] and got["position"] == [5, 4, 0]


def test_walk_fight_fails_when_the_load_after_a_press_never_opens_a_fight(
        tmp_path, monkeypatch):
    sess = UnsentPressBar(prep_seconds=1000.0)
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    sess.now = run.clock
    with pytest.raises(A.StepFailed,
                       match=r"in 60 seconds; row 24 reads '', mode 4"):
        run.walk_fight("I")
    log.close()
    assert sess.pressed == []


def test_walk_fight_will_not_send_walk_one_into_a_blank_row_24(tmp_path, monkeypatch):
    sess = UnsentPressBar()
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    sess.now = run.clock
    run._await_fight_after_press = lambda *a: None
    with pytest.raises(A.StepFailed, match=r"will not take MOVE while row 24 "
                                           r"reads '' \(mode 1\)"):
        run.walk_fight("I")
    log.close()
    assert sess.pressed == [] and sess.calls == 1


def test_the_blank_row_guard_lets_a_fresh_press_page_through_to_walk_one(
        tmp_path, monkeypatch):
    sess = UnsentPressBar()
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    sess.now = run.clock
    run._await_fight_after_press = lambda *a: None
    run._answer_press_bar = lambda *a: True
    got = run.walk_fight("I")
    log.close()
    assert sess.pressed == ["I"] and got["position"] == [5, 4, 0]


class PagedAmbush(UnsentPressBar):
    """Each Return is followed by a blank second and then another `PRESS` page,
    `pages_left` times."""

    def __init__(self, pages_left, **kw):
        super().__init__(**kw)
        self.pages_left = pages_left

    def screen(self):
        if (self.state == "prep" and self.pages_left
                and self.now() >= self.returned_at + 1.0):
            self.state = "press"
            self.pages_left -= 1
        return super().screen()


def test_a_second_press_page_during_the_load_is_answered_and_the_fight_fought(
        tmp_path, monkeypatch):
    sess = PagedAmbush(1)
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    sess.now = run.clock
    got = run.walk_fight("I")
    log.close()
    assert sess.sent == [("key", 0x0D)] * 2
    assert [f["at_move"] for f in got["fights"]] == [0]
    assert sess.pressed == ["I"]


def test_a_fourth_press_page_fails_after_three_returns_counted_across_the_wait(
        tmp_path, monkeypatch):
    sess = PagedAmbush(10)
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    sess.now = run.clock
    with pytest.raises(A.StepFailed, match="sent 3 Returns and another PRESS"):
        run.walk_fight("I")
    log.close()
    assert sess.sent == [("key", 0x0D)] * 3 and sess.pressed == []


class MenuAfterPress(UnsentPressBar):
    """After the gap the blank row 24 becomes `bar`, an encounter menu or a
    `YES NO`; answering it opens the fight."""

    def __init__(self, bar, **kw):
        super().__init__(**kw)
        self.screens["menu"] = _window(self.TEXT, bar)

    def screen(self):
        if (self.state == "prep"
                and self.now() >= self.returned_at + self.gap_seconds):
            self.state = "menu"
        return super().screen()

    def in_combat(self):
        return self.combat

    def fight(self, budget, tactic, stop=None):
        self.combat = False
        return super().fight(budget, tactic, stop)


@pytest.mark.parametrize("bar, route, chosen", [
    ("COMBAT WAIT FLEE ADVANCE", "I", "COMBAT"), ("YES NO", "I/NO", "NO")])
def test_a_menu_or_yes_no_after_the_press_is_answered_not_waited_out(
        tmp_path, monkeypatch, bar, route, chosen):
    sess = MenuAfterPress(bar)
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    sess.now = run.clock
    got = run.walk_fight(route)
    log.close()
    assert sess.selected == [chosen]
    assert [f["at_move"] for f in got["fights"]] == [0]
    assert sess.pressed == ["I"]


def test_walk_fight_fails_naming_a_key_that_was_never_sent_after_three_unsent_passes(
        tmp_path, monkeypatch):
    sess = UnsentPressBar(fight=False, unsent_calls=("all",))
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    sess.now = run.clock
    with pytest.raises(A.StepFailed, match="move 0 .I. was never sent"):
        run.walk_fight("I")
    log.close()
    assert sess.pressed == [] and sess.calls == 4
    assert len(_run_events(tmp_path, "move-unsent")) == 4


# --- --read-at and the treasure capture -----------------------------------------

class _ReadMachine:
    """One fake C64 behind every `_ReadMon`: memory, the checkpoints set on it, and
    the stops the test raises with `hit`."""

    def __init__(self):
        self.mem = bytearray(0x10000)
        self.checkpoints = {}
        self.hits = {}
        self.next_cp = 1
        self.pc = 0
        self.resumes = 0
        self.halted = False     # VICE halts at a stop until a resume or EXIT
        # Stops that fire once the machine runs again, in the gap between a
        # connection's EXIT and VICE seeing its socket close.
        self.after_exit = []

    def fire_after_exit(self):
        """The next queued stop fires; the machine is then halted, so the rest wait."""
        if self.after_exit:
            self.hit(self.after_exit.pop(0))

    def hit(self, pc):
        self.pc = pc
        self.halted = True
        for n, cp in self.checkpoints.items():
            if cp == pc:
                self.hits[n] = self.hits.get(n, 0) + 1


class _ReadMon:
    def __init__(self, machine):
        self.m = machine

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.m.halted = False       # EXIT
        self.m.fire_after_exit()
        if self.m.halted:
            # The dying connection's close resumes a stop that halted on it.
            self.m.halted = False
            self.m.pc = 0x2E25
        return False

    def hang_up(self):
        # Closed while halted: VICE resumes with the connection already gone,
        # so a stop after that halts with no connection open.
        self.m.halted = False
        self.m.fire_after_exit()

    def read(self, start, length, bank=0):
        return bytes(self.m.mem[start:start + length])

    def registers(self):
        return {0: 0x12, 1: 0x34, 2: 0x56, 3: self.m.pc}

    def checkpoint_set(self, start, end=None, *, load=False, store=False,
                       exec_=False, stop=True, temporary=False):
        n = self.m.next_cp
        self.m.next_cp += 1
        self.m.checkpoints[n] = start
        return n

    def checkpoint_delete(self, n):
        self.m.checkpoints.pop(n, None)

    def checkpoint_hits(self, n):
        return self.m.hits.get(n, 0)

    def checkpoints_clear(self):
        self.m.checkpoints.clear()

    def resume(self):
        self.m.resumes += 1
        self.m.halted = False


class _ReadSess:
    def __init__(self, machine):
        self.machine = machine

    def mon(self, timeout=5.0):
        return _ReadMon(self.machine)


class _EventLog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def say(self, text):
        pass

    def of(self, kind):
        return [kw for k, kw in self.events if k == kind]


def _read_at_run(tmp_path, specs):
    machine = _ReadMachine()
    machine.mem[0x09DD:0x09E0] = bytes.fromhex("CD782B")
    machine.mem[0x2B78:0x2B7A] = b"\x03\x05"
    machine.mem[0x6E3E] = 7
    run = A.PoolRun.__new__(A.PoolRun)
    run.sess, run.log, run.out = _ReadSess(machine), _EventLog(), tmp_path
    run.read_ats = tuple(A.parse_read_at(specs))
    run.arm_read_at()
    machine.resumes = 0         # arming resumes once; count only the stops'
    return run, machine


def _connect(run):
    with run.sess.mon(5):
        pass


def test_read_at_parses_the_plans_option_and_refuses_a_malformed_one():
    got, = A.parse_read_at(["09DD=CD782B:2B78:2,6E3E:1,6BBB:14"])
    assert (got.pc, got.guard, got.reads) == (
        0x09DD, bytes.fromhex("CD782B"), ((0x2B78, 2), (0x6E3E, 1), (0x6BBB, 0x14)))
    for bad in ("09DD", "09DD=CD782B", "09DD=:2B78:2", "09DD=CD78:2B78", "GG=CD:2B78:2",
                "09DD=CD:FFFF:2"):
        with pytest.raises(ValueError, match="read-at"):
            A.parse_read_at([bad])


def test_read_at_with_a_matching_guard_logs_the_reads_and_resumes(tmp_path):
    run, machine = _read_at_run(tmp_path, ["09DD=CD782B:2B78:2,6E3E:1"])
    machine.hit(0x09DD)
    _connect(run)
    got, = run.log.of("read-at")
    assert got["guard_matched"] is True and got["hit"] == 1 and got["pc"] == 0x09DD
    assert got["reads"] == {"2B78": "0305", "6E3E": "07"}
    assert (got["a"], got["x"], got["y"]) == (0x12, 0x34, 0x56)
    assert machine.resumes == 1
    assert run.read_at_counts["read-at-09DD"] == {
        "hits": 1, "foreign": 0, "late": 0, "merged": 0}


def test_a_stop_that_fires_during_a_connection_is_read_by_that_connection(tmp_path):
    run, machine = _read_at_run(tmp_path, ["09DD=CD782B:2B78:2"])
    with run.sess.mon(5):
        machine.hit(0x09DD)
    got, = run.log.of("read-at")
    assert got["pc"] == 0x09DD and got["late"] is False and got["fires"] == 1
    assert machine.resumes == 0     # EXIT resumes; the trap does not
    assert not machine.halted
    machine.pc = 0x2E25
    _connect(run)
    assert len(run.log.of("read-at")) == 1


def test_a_stop_that_fires_as_a_connection_closes_is_read_at_its_stop(tmp_path):
    run, machine = _read_at_run(tmp_path, ["0764=CD782B:2B78:2"])
    machine.mem[0x0764:0x0767] = bytes.fromhex("CD782B")
    machine.hit(0x0764)
    machine.after_exit = [0x0764]
    _connect(run)
    _connect(run)
    first, second = run.log.of("read-at")
    assert (first["pc"], second["pc"]) == (0x0764, 0x0764)
    assert (second["late"], second["fires"]) == (False, 1)
    assert run.read_at_counts["read-at-0764"]["late"] == 0


def test_a_second_stop_that_fires_as_a_connection_closes_is_not_merged_into_the_first(tmp_path):
    run, machine = _read_at_run(tmp_path, ["0764=CD782B:2B78:2", "076D=CD782B:2B78:2"])
    machine.mem[0x0764:0x0767] = machine.mem[0x076D:0x0770] = bytes.fromhex("CD782B")
    machine.hit(0x0764)
    machine.after_exit = [0x076D]
    _connect(run)
    _connect(run)
    records = run.log.of("read-at")
    assert [(r["pc"], r["late"]) for r in records] == [
        (0x0764, False), (0x076D, False)]
    assert run.read_at_counts["read-at-076D"]["hits"] == 1
    assert run.read_at_counts["read-at-076D"]["late"] == 0


def test_a_stop_that_fires_before_the_callers_resume_is_read_before_it(tmp_path):
    run, machine = _read_at_run(tmp_path, ["09DD=CD782B:2B78:2"])
    with run.sess.mon(5) as m:
        machine.hit(0x09DD)
        m.resume()
        assert len(run.log.of("read-at")) == 1 and machine.resumes == 1
    assert run.log.of("read-at")[0]["pc"] == 0x09DD


def test_a_stop_during_a_body_that_raises_is_still_read_and_the_machine_freed(tmp_path):
    run, machine = _read_at_run(tmp_path, ["09DD=CD782B:2B78:2"])
    with pytest.raises(RuntimeError):
        with run.sess.mon(5):
            machine.hit(0x09DD)
            raise RuntimeError("the caller broke")
    assert run.log.of("read-at")[0]["pc"] == 0x09DD
    assert not machine.halted


def test_a_handler_that_raises_at_exit_still_frees_the_machine(tmp_path):
    run, machine = _read_at_run(tmp_path, ["09DD=CD782B:2B78:2"])
    real = _ReadMon.read

    def broken(self, start, length, bank=0):
        raise RuntimeError("monitor broke")

    try:
        with run.sess.mon(5):
            machine.hit(0x09DD)
            _ReadMon.read = broken
    finally:
        _ReadMon.read = real
    assert run.traps.degraded and not machine.halted


def test_an_interrupt_in_the_exit_check_still_sends_exit(tmp_path):
    run, machine = _read_at_run(tmp_path, ["09DD=CD782B:2B78:2"])

    def interrupted(m, resume=True):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        with run.sess.mon(5):
            machine.hit(0x09DD)
            run.traps.check = interrupted
    assert not machine.halted


class _Sock:
    def __init__(self, live):
        self.live = live

    def getpeername(self):
        if not self.live:
            raise OSError("not connected")
        return ("127.0.0.1", 6510)


def test_a_body_oserror_on_a_live_monitor_still_runs_the_exit_check(tmp_path):
    run, machine = _read_at_run(tmp_path, ["09DD=CD782B:2B78:2"])
    with pytest.raises(OSError):
        with run.sess.mon(5) as m:
            m._m.sock = _Sock(True)
            machine.hit(0x09DD)
            raise OSError("the caller's own")
    assert run.log.of("read-at")[0]["pc"] == 0x09DD
    assert run.log.of("exit_check_skipped") == [] and not machine.halted


@pytest.mark.parametrize("sock", [None, _Sock(False)])
def test_a_gone_monitor_skips_the_exit_check_and_says_so(tmp_path, sock):
    run, machine = _read_at_run(tmp_path, ["09DD=CD782B:2B78:2"])
    with run.sess.mon(5) as m:
        machine.hit(0x09DD)
        m._m.sock = sock
        run.traps.check = lambda m, resume=True: pytest.fail("checked")
    assert len(run.log.of("exit_check_skipped")) == 1
    assert not machine.halted


def test_an_entry_check_that_raises_still_sends_exit(tmp_path):
    run, machine = _read_at_run(tmp_path, ["09DD=CD782B:2B78:2"])
    machine.hit(0x09DD)

    def interrupted(m, resume=True):
        raise KeyboardInterrupt

    run.traps.check = interrupted
    with pytest.raises(KeyboardInterrupt):
        run.sess.mon(5).__enter__()
    assert not machine.halted


def test_a_read_at_another_pc_than_its_stop_is_marked_late(tmp_path):
    run, machine = _read_at_run(tmp_path, ["09DD=CD782B:2B78:2"])
    machine.hit(0x09DD)
    machine.pc = 0x2E25
    _connect(run)
    got, = run.log.of("read-at")
    assert got["late"] is True and got["pc"] == 0x2E25
    assert run.read_at_counts["read-at-09DD"]["late"] == 1


def test_two_fires_between_scans_log_a_count_of_two(tmp_path):
    run, machine = _read_at_run(tmp_path, ["09DD=CD782B:2B78:2"])
    machine.hit(0x09DD)
    machine.hit(0x09DD)
    _connect(run)
    got, = run.log.of("read-at")
    assert got["fires"] == 2 and got["hit"] == 1
    assert run.read_at_counts["read-at-09DD"]["merged"] == 1


def test_read_at_with_another_overlay_at_the_pc_reads_nothing_and_resumes(tmp_path):
    run, machine = _read_at_run(tmp_path, ["09DD=CD782B:2B78:2"])
    machine.mem[0x09DD:0x09E0] = b"\xA9\x00\x8D"
    machine.hit(0x09DD)
    _connect(run)
    assert run.log.of("read-at") == []
    assert len(run.log.of("read-at-foreign")) == 1
    assert machine.resumes == 1
    assert run.read_at_counts["read-at-09DD"] == {
        "hits": 0, "foreign": 1, "late": 0, "merged": 0}


def test_release_read_at_deletes_every_stop(tmp_path):
    run, machine = _read_at_run(tmp_path, ["09DD=CD782B:2B78:2", "0C8C=20:6BBB:14"])
    assert len(machine.checkpoints) == 2
    got = run.release_read_at()
    assert machine.checkpoints == {} and set(got["stops"]) == {"read-at-09DD", "read-at-0C8C"}


def test_release_read_at_handles_a_pending_twentieth_foreign_hit(tmp_path):
    run, machine = _read_at_run(tmp_path, ["09DD=CD782B:2B78:2"])
    machine.mem[0x09DD] = 0x00
    run.read_at_counts["read-at-09DD"]["foreign"] = A.READ_AT_FOREIGN_MAX - 1
    machine.hit(0x09DD)
    run.release_read_at()
    assert machine.checkpoints == {}
    assert run.log.of("read-at-release-failed") == []
    assert len(run.log.of("read-at-retired")) == 1


def test_release_read_at_does_not_raise_when_the_emulator_is_gone(tmp_path):
    run, machine = _read_at_run(tmp_path, ["09DD=CD782B:2B78:2"])

    def dead(timeout=5.0):
        raise ConnectionError("gone")

    run.sess.mon = dead
    run.traps._mon = dead
    run.release_read_at()
    assert run.log.of("read-at-release-failed")


def test_read_at_reports_a_degraded_trap_and_the_counters_it_cleared(tmp_path):
    run, machine = _read_at_run(tmp_path, ["09DD=CD782B:2B78:2"])
    run.armed = {"purse": 0x0C8C}
    run.box = SimpleNamespace(save_load_address=0x100, clock=0, roster_base=0,
                              roster_stride=1)
    run.game = SimpleNamespace(key="other")
    said = []
    run.log.say = said.append
    machine.mem[0x09DD] = 0x00
    machine.hit(0x09DD)
    real = _ReadMon.read

    def broken(self, start, length, bank=0):
        raise RuntimeError("monitor broke")

    _ReadMon.read = broken
    try:
        _connect(run)
    finally:
        _ReadMon.read = real
    assert run.traps.degraded
    assert run.reading()["counts"] == {"purse": "cleared"}
    got = run.release_read_at()
    assert got["degraded"] is True and any("degraded" in line for line in said)


def test_read_at_retires_a_stop_after_too_many_foreign_hits(tmp_path):
    run, machine = _read_at_run(tmp_path, ["09DD=CD782B:2B78:2"])
    machine.mem[0x09DD] = 0x00
    for _ in range(A.READ_AT_FOREIGN_MAX):
        machine.hit(0x09DD)
        _connect(run)
    assert machine.checkpoints == {}
    retired, = run.log.of("read-at-retired")
    assert retired["foreign"] == A.READ_AT_FOREIGN_MAX
    assert run.read_at_counts["read-at-09DD"]["retired"] is True


def _read_at_pool(machine):
    class Pool(A.PoolRun):
        def __init__(self, sess, log, out, game, points):
            self.sess, self.log, self.out = _ReadSess(machine), log, out
            self.explode = False

        def load(self):
            self.arm_read_at()
            return {}

        def peek(self, arg):
            raise RuntimeError("the step broke")

        def reading(self):
            return {}

        def capture(self, *a):
            pass
    return Pool


def test_the_run_deletes_its_read_at_stops_on_a_normal_exit(tmp_path, monkeypatch):
    machine = _ReadMachine()
    rc, _, out = _drive(tmp_path, monkeypatch, ["load"], pool=_read_at_pool(machine),
                        read_at=["09DD=CD782B:2B78:2"])
    assert rc == 0 and machine.checkpoints == {}
    assert json.loads((out / "summary.json").read_text())["read_at"] == {
        "stops": {"read-at-09DD": {
            "hits": 0, "foreign": 0, "late": 0, "merged": 0}}, "degraded": False}


def test_the_run_deletes_its_read_at_stops_when_a_step_raises(tmp_path, monkeypatch):
    machine = _ReadMachine()
    rc, _, out = _drive(tmp_path, monkeypatch, ["load", "peek 2B78 2"],
                        pool=_read_at_pool(machine), read_at=["09DD=CD782B:2B78:2"])
    assert rc == 1 and machine.checkpoints == {}
    assert "the step broke" in json.loads((out / "summary.json").read_text())["lost"]


def test_read_at_is_refused_outside_pool(tmp_path, capsys):
    with pytest.raises(SystemExit):
        A.main(["--title", "curse", "--save", str(_fixture_disk(tmp_path)),
                "--disks", str(tmp_path), "--read-at", "09DD=CD:2B78:2",
                "--steps", "load", "--out", str(tmp_path / "out")])
    assert "Pool of Radiance only" in capsys.readouterr().err


TREASURE_BAR = "VIEW  TAKE  POOL  SHARE  EXIT"


def test_walk_fight_keeps_the_treasure_screen_before_the_fight_answers_it(
        tmp_path, monkeypatch):
    sess = FightWalk({0: "fight"})
    shown = []

    def fight(budget, tactic, stop=None):
        sess.combat = False
        for bar in ("COMBAT SPEED", TREASURE_BAR, TREASURE_BAR):
            rows = ["THERE IS TREASURE"] + [""] * 23 + [bar]
            shown.append(stop(sess, FakeScreen(rows)))
        return A.S.FightResult(A.S.WON, 3, 1.0, [], [])

    sess.fight = fight
    run, log = _fight_walk_run(tmp_path, monkeypatch, sess)
    taken = []
    run.capture = lambda tag, rows=None: taken.append((tag, rows)) or []
    run.walk_fight("I")
    log.close()
    assert shown == [False, False, False]
    treasure = [(t, r) for t, r in taken if t == "treasure"]
    assert len(treasure) == 1 and treasure[0][1][24] == TREASURE_BAR
    assert sess.pressed == ["I"]


# --- a later title's combat side, the bar log and the first-bar key -------------

_SIDE_SPECIMENS = {"curse": ("curse-h-engine-resave-walked", "curse-of-the-azure-bonds"),
                   "ssb": ("ssb-joined-arrow-c64-672", "secret-of-the-silver-blades")}


def _roster_and_payload(path):
    from goldbox import c64_port, c64_save

    image = D64.open(str(path))
    game = c64_port.detect(image)
    box = c64_save.CONTAINERS[game.key]
    _, payload = A._payload(image, game)
    if box.roster_file is None:
        return box, bytes(payload), bytes(payload)
    return box, bytes(payload), bytes(split_load_address(
        image.read_file(box.roster_file))[1])


def _diff(before: bytes, after: bytes) -> list[int]:
    assert len(before) == len(after)
    return [i for i, (a, b) in enumerate(zip(before, after)) if a != b]


@pytest.mark.parametrize("title", sorted(_SIDE_SPECIMENS))
def test_a_staged_side_goes_into_the_later_roster_block_and_nothing_else(
        title, tmp_path):
    from tests.c64.test_c64nametable import specimen_disk

    name, key = _SIDE_SPECIMENS[title]
    source = specimen_disk(name)
    dest = tmp_path / "staged.D64"
    took = A.stage(source, dest, key, sides=[(2, 0xC0)])
    box, payload0, roster0 = _roster_and_payload(source)
    _, payload1, roster1 = _roster_and_payload(dest)
    at = box.roster_offset + 2 * box.roster_stride + A.ROSTER_COMBAT_SIDE
    assert took["sides"] == [{"slot": 2, "offset": at, "was": roster0[at],
                              "now": 0xC0}]
    assert roster1[at] == 0xC0
    if box.roster_file is None:
        assert _diff(payload0, payload1) == [at]
    else:
        assert payload1 == payload0
        assert _diff(roster0, roster1) == [at]


def test_a_staged_side_for_an_empty_roster_slot_is_refused(tmp_path):
    from tests.c64.test_c64nametable import specimen_disk

    name, key = _SIDE_SPECIMENS["curse"]
    with pytest.raises(ValueError, match="empty"):
        A.stage(specimen_disk(name), tmp_path / "s.D64", key, sides=[(7, 0x80)])


def test_a_side_and_a_key_are_parsed():
    assert A.parse_sides(["2=0xC0", "3=0x80,4=0"]) == [(2, 0xC0), (3, 0x80), (4, 0)]
    for bad in ("2", "8=1", "2=0x100"):
        with pytest.raises(ValueError):
            A.parse_sides([bad])
    assert A.parse_key("SPACE") == 0x20 and A.parse_key("space") == 0x20
    assert A.parse_key("m") == A.parse_key("M") == ord("M")
    with pytest.raises(ValueError):
        A.parse_key("ESC")


def test_a_first_bar_key_without_a_fight_step_is_refused(tmp_path):
    with pytest.raises(SystemExit) as info:
        A.main(["--title", "curse", "--save", str(_fixture_disk(tmp_path)),
                "--disks", str(tmp_path), "--steps", "load",
                "--first-bar-key", "SPACE", "--out", str(tmp_path / "out")])
    assert info.value.code == 2


def test_a_first_bar_key_or_side_is_refused_where_it_cannot_apply(tmp_path):
    base = ["--save", str(_fixture_disk(tmp_path)), "--disks", str(tmp_path),
            "--steps", "load", "--out", str(tmp_path / "out")]
    for extra in (["--title", "pool", "--stage-side", "1=0x80"],
                  ["--title", "pool", "--first-bar-key", "SPACE"],
                  ["--title", "curse", "--first-bar-key", "SPACE",
                   "--attack-by", "ANNA"],
                  ["--title", "curse", "--first-bar-key", "ESC"],
                  ["--title", "ssb", "--first-bar-key", "SPACE"]):
        with pytest.raises(SystemExit) as info:
            A.main([*extra, *base])
        assert info.value.code == 2


class _BarFight:
    """A fight of three command bars, read the way `Session.fight` reads them."""

    def __init__(self, names):
        self.names = names
        self.pressed = []
        self.turns = []

    def battle(self):
        member = lambda i, n, x: SimpleNamespace(  # noqa: E731
            name=f"{n} ", index=i, slot=i, x=x, y=1, on_map=True, hp=9,
            side=0x80 if n == "K" else 0, is_party=True)
        foe = SimpleNamespace(name="ORC", index=8, slot=0, x=5, y=5, on_map=True,
                              hp=4, side=1, is_party=False)
        return SimpleNamespace(combatants=(member(0, "K", 1), member(1, "J", 2), foe))

    def acting(self, battle, s=None):
        return next(c for c in battle.combatants
                    if c.name.strip() == self.names[len(self.turns) - 1])

    def press_kernal(self, code):
        self.pressed.append(code)

    def settle(self, seconds=6.0):
        pass

    def bars(self, run, n):
        tactic = run.bar_tactic()
        out = []
        for _ in range(n):
            self.turns.append(1)
            out.append(tactic(self, SimpleNamespace(text="MOVE DONE")))
        return out


def _bar_run(monkeypatch, key=None):
    events, captures = [], []
    run = A.CurseRun.__new__(A.CurseRun)
    run.log = SimpleNamespace(emit=lambda kind, **kw: events.append((kind, kw)))
    run.capture = captures.append
    run.first_bar_key = key
    monkeypatch.setattr(A.S.Session, "melee_turn",
                        lambda sess, bar: sess.pressed.append("melee") or "MOVE")
    return run, events, captures


def test_every_bar_logs_its_actor_and_the_first_logs_where_everyone_stands(monkeypatch):
    run, events, _ = _bar_run(monkeypatch)
    sess = _BarFight(["K", "J", "K"])
    sess.bars(run, 3)
    bars = [kw["actor"]["name"] for kind, kw in events if kind == "bar"]
    assert bars == ["K", "J", "K"]
    placements = [kw for kind, kw in events if kind == "placement"]
    assert len(placements) == 1
    who = {c["name"]: c for c in placements[0]["combatants"]}
    assert who["K"]["side"] == 0x80 and who["K"]["position"] == [1, 1]
    assert who["ORC"]["party"] is False
    assert sess.pressed == ["melee"] * 3


def test_the_key_and_placement_fire_once_per_run_across_fight_steps(monkeypatch):
    run, events, _ = _bar_run(monkeypatch, key=0x20)
    first, second = _BarFight(["K", "K"]), _BarFight(["K", "K"])
    first.bars(run, 2)
    second.bars(run, 2)
    assert first.pressed == [0x20, "melee"] and second.pressed == ["melee"] * 2
    assert [k for k, _ in events].count("placement") == 1


def test_a_member_who_never_gets_a_bar_does_not_fail_the_log(monkeypatch):
    run, events, _ = _bar_run(monkeypatch)
    _BarFight(["J", "J"]).bars(run, 2)
    assert [kw["actor"]["name"] for kind, kw in events if kind == "bar"] == ["J", "J"]


def test_the_first_bar_key_is_pressed_once_at_the_first_bar_and_captured(monkeypatch):
    run, events, captures = _bar_run(monkeypatch, key=0x20)
    sess = _BarFight(["K", "K", "J"])
    got = sess.bars(run, 3)
    assert sess.pressed == [0x20, "melee", "melee"]
    assert captures == ["first-bar-key"]
    assert got[0] == "KEY 0x20" and got[1:] == ["MOVE", "MOVE"]
    assert [k for k, _ in events].count("first-bar-key") == 1


def test_a_plain_fight_uses_the_logging_tactic_only_when_asked(monkeypatch, tmp_path):
    from tools.c64 import laterbattle
    from tools.curse_of_the_azure_bonds import cursethac0

    class Route:
        last_goto_steps = 1

        def __init__(self, out, quiet):
            self.file = SimpleNamespace(close=lambda: None)

        def goto(self, target, steps, geo):
            return True

    tactics = []

    class Session:
        def in_combat(self):
            return True

        def await_bar(self, *a, **k):
            return None

        def fight(self, *, budget, tactic):
            tactics.append(tactic)
            return A.S.FightResult("ended", 1, 1.0, [], [])

    monkeypatch.setattr(laterbattle, "Battle", Route)
    monkeypatch.setattr(cursethac0, "area_geo", lambda *a: ("GEO01", object()))
    for log_bars in (False, True):
        run = A.CurseRun.__new__(A.CurseRun)
        run.attack_by, run.attack_owner = "", None
        run.attack_evidence = run.quit_evidence = None
        run.log_bars = log_bars
        run.log = SimpleNamespace(emit=lambda *a, **k: None)
        run.sess, run.out = Session(), tmp_path
        run.staged_disk, run.disks = tmp_path / "s.D64", "unused"
        run.to_world = lambda: True
        run.await_combat = lambda: True
        run.capture = lambda tag: None
        run.fight("10", "I", 5)
    assert tactics[0] is A.S.Session.melee_turn
    assert tactics[1] is not A.S.Session.melee_turn


# --- Silver Blades' fight: a wandering monster in New Verdigris -------------------

class _SilverFight(_BarFight):
    """A New Verdigris walk that commits to a fight after COMMIT move keys,
    then three command bars read the way `Session.fight` reads them, then the
    mode readings POLLS offered to the fight's stop, each once; the machine is
    left in the mode the outcome leaves it in (the world after a win, the party
    menu after a loss or a wipe, COMBAT when the budget ran out)."""

    MOVE_BAR = "I,J,K,M, RETURN OR BUTTON"
    WORLD_BAR = "MOVE VIEW CAST AREA ENCAMP SEARCH LOOK"
    AFTER = {A.S.WON: A.S.DUNGEON, A.S.LOST: A.SILVER_GEN, A.S.BUDGET: A.S.COMBAT,
             A.S.ENDED: A.SILVER_GEN}

    def __init__(self, commit=5, prep_reads=2, outcome=A.S.WON, loading=0,
                 wiped=False, polls=(), idle=True, sticky_gate=False):
        super().__init__(["K", "J", "K"])
        self.memory = {A.SILVER_WANDER_GATE: 0}
        self.gate_writes = []
        self.moves = []
        self.moves_at_commit = None
        self.commit, self.prep_reads = commit, prep_reads
        self.outcome = A.S.ENDED if wiped else outcome
        self.after = self.AFTER[self.outcome]
        self.polls = list(polls or ((A.SILVER_GEN, A.SILVER_GEN) if wiped else ()))
        self.poll_mode = None
        #: Readings, after the move that starts the encounter, for which the
        #: move bar stays drawn while `SETUPMON` loads and no key is waited on.
        self.loading, self.idle = loading, idle
        #: A gate the monitor cannot write once the fight is over.
        self.sticky_gate = sticky_gate
        self.fought = []

    def mode(self):
        if self.poll_mode is not None:
            return self.poll_mode
        if self.fought:
            return self.after
        if len(self.moves) < self.commit or self.loading:
            return A.S.DUNGEON
        if self.moves_at_commit is None:
            self.moves_at_commit = len(self.moves)
        if self.prep_reads:
            self.prep_reads -= 1
            return A.COMBAT_PREP
        return A.S.COMBAT

    def key_idle(self):
        if len(self.moves) >= self.commit and self.loading:
            self.loading -= 1
            return False
        return self.idle

    def screen(self):
        if self.mode() != A.S.DUNGEON:
            return FakeScreen([""] * 25)
        return FakeScreen([""] * 24 + [self.WORLD_BAR if self.fought else self.MOVE_BAR])

    def mon(self, timeout):
        sess = self

        class Mon:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, addr, n):
                return bytes([sess.memory.get(addr, 0)])

            def write(self, addr, data):
                sess.gate_writes.append((addr, data[0], sess.mode()))
                if not (sess.sticky_gate and sess.fought):
                    sess.memory[addr] = data[0]

            def resume(self):
                pass

        return Mon()

    def await_bar(self, *a, **k):
        return None

    def fight(self, *, budget, tactic, stop=None):
        self.fought.append((tactic, stop))
        for _ in range(3):
            self.turns.append(1)
            tactic(self, SimpleNamespace(text="MOVE VIEW AIM TURN QUICK DONE"))
        self.stopped_at = None
        for n, mode in enumerate(self.polls):
            self.poll_mode = mode
            if stop(self, self.screen()):
                self.stopped_at = n
                break
        self.poll_mode = None
        return A.S.FightResult(self.outcome, 3, 1.0, [], [])


def _silver_run(monkeypatch, tmp_path, sess, key=None, area="GEO10"):
    from tools.c64 import laterbattle
    from tools.curse_of_the_azure_bonds import cursethac0

    class Route:
        """`laterbattle.Battle`'s walk: one forward key a square, asking
        `in_combat` before each, as `goto` does."""

        def __init__(self, out, quiet):
            self.file = SimpleNamespace(close=lambda: None)
            self.last_goto_steps = 0

        def goto(self, target, budget, geo=None, accept=False):
            took = 0
            for _ in range(budget):
                took += 1
                if self.in_combat():
                    break
                self.press("I")
            self.last_goto_steps = took
            return self.in_combat()

        def press(self, key):
            self.sess.moves.append(key)
            return True

        def clear_bar(self, accept=False):
            return None

    monkeypatch.setattr(laterbattle, "Battle", Route)
    monkeypatch.setattr(cursethac0, "area_geo", lambda *a: (area, object()))
    monkeypatch.setattr(A.S.Session, "melee_turn",
                        lambda sess, bar: sess.pressed.append("melee") or "MOVE")
    events, captures = [], []
    run = A.SilverRun.__new__(A.SilverRun)
    run.sess, run.out = sess, tmp_path
    run.staged_disk, run.disks = tmp_path / "s.D64", "unused"
    run.log = SimpleNamespace(emit=lambda kind, **kw: events.append((kind, kw)))
    run.capture = lambda tag, rows=None: captures.append(tag)
    run.to_world = lambda: True
    run.key_idle = sess.key_idle
    run.log_bars, run.first_bar_key = True, key
    return run, events, captures


def test_a_silver_blades_fight_walks_with_the_gate_on_and_logs_every_bar(
        monkeypatch, tmp_path):
    sess = _SilverFight()
    run, events, captures = _silver_run(monkeypatch, tmp_path, sess)
    got = run.fight("600", "I", 40)
    assert sess.moves == ["I"] * 5 and got["walked"] == 6
    assert sess.gate_writes == [(A.SILVER_WANDER_GATE, 1, A.S.DUNGEON),
                                (A.SILVER_WANDER_GATE, 0, A.S.DUNGEON)]
    assert got["wander_gate"] == {"address": "$4C2D", "was": 0, "now": 1,
                                  "restored": 0, "mode": A.S.DUNGEON}
    assert [kw["actor"]["name"] for kind, kw in events if kind == "bar"] == \
        ["K", "J", "K"]
    assert [k for k, _ in events].count("placement") == 1
    assert sess.pressed == ["melee"] * 3
    assert sess.fought[0][1] == run.world_again
    assert captures == ["fight-route", "fight-start", "fight-end"]


def test_a_silver_blades_first_bar_key_is_pressed_once_and_no_move_key_follows_the_commit(
        monkeypatch, tmp_path):
    sess = _SilverFight()
    run, events, captures = _silver_run(monkeypatch, tmp_path, sess, key=0x20)
    run.fight("600", "I", 40)
    assert sess.moves_at_commit == 5 and len(sess.moves) == 5
    assert sess.pressed == [0x20, "melee", "melee"]
    assert "first-bar-key" in captures
    assert [k for k, _ in events].count("first-bar-key") == 1


def test_a_silver_blades_walk_with_no_fight_fails_and_puts_the_gate_back(
        monkeypatch, tmp_path):
    sess = _SilverFight(commit=10_000)
    run, _, captures = _silver_run(monkeypatch, tmp_path, sess)
    run.clock = iter(range(0, 10_000, 5)).__next__
    run.deadline = None
    with pytest.raises(A.StepFailed, match="no fight in 12 steps of GEO10"):
        run.fight("600", "I", 12)
    assert len(sess.moves) == 12
    assert sess.memory[A.SILVER_WANDER_GATE] == 0
    assert "lost-fight" in captures and not sess.fought


def test_a_silver_blades_fight_outside_new_verdigris_is_refused_before_the_gate(
        monkeypatch, tmp_path):
    sess = _SilverFight()
    run, _, _ = _silver_run(monkeypatch, tmp_path, sess, area="GEO11")
    run.capture = lambda tag, rows=None: None
    with pytest.raises(A.StepFailed, match="the party is in GEO11"):
        run.fight("600", "I", 40)
    assert sess.gate_writes == [] and sess.moves == []


@pytest.mark.parametrize("outcome, match, mode", [
    (A.S.LOST, "lost the fight", A.SILVER_GEN),
    (A.S.BUDGET, "ran out of its 600 second budget", A.S.COMBAT)])
def test_a_lost_or_overlong_silver_blades_fight_still_puts_the_gate_back(
        monkeypatch, tmp_path, outcome, match, mode):
    sess = _SilverFight(outcome=outcome)
    run, events, _ = _silver_run(monkeypatch, tmp_path, sess)
    run.reading = lambda: {}
    with pytest.raises(A.StepFailed, match=match):
        run.fight("600", "I", 40)
    assert sess.memory[A.SILVER_WANDER_GATE] == 0
    assert sess.gate_writes[-1] == (A.SILVER_WANDER_GATE, 0, mode)
    last = [kw for kind, kw in events if kind == "wander-gate"][-1]
    assert last["restored"] == 0 and last["mode"] == mode


def test_a_silver_blades_walk_sends_no_key_while_an_encounter_loads_under_the_move_bar(
        monkeypatch, tmp_path):
    sess = _SilverFight(loading=4)
    run, _, _ = _silver_run(monkeypatch, tmp_path, sess)
    run.clock = iter(range(0, 10_000)).__next__
    run.fight("600", "I", 40)
    assert sess.moves == ["I"] * 5 and sess.moves_at_commit == 5


def test_a_silver_blades_party_wiped_to_the_party_menu_fails_the_fight_at_once(
        monkeypatch, tmp_path):
    sess = _SilverFight(wiped=True)
    run, events, captures = _silver_run(monkeypatch, tmp_path, sess)
    run.reading = lambda: {}
    assert run.world_again(sess, None) is False
    with pytest.raises(A.StepFailed, match="went back to the party menu"):
        run.fight("600", "I", 40)
    assert [kw["wiped"] for kind, kw in events if kind == "silver-fight"] == [True]
    assert sess.memory[A.SILVER_WANDER_GATE] == 0
    assert sess.gate_writes[-1] == (A.SILVER_WANDER_GATE, 0, A.SILVER_GEN)
    assert [kw for kind, kw in events if kind == "wander-gate"][-1]["restored"] == 0


def test_one_reading_of_the_party_menu_mode_while_a_won_fight_ends_is_not_a_wipe(
        monkeypatch, tmp_path):
    sess = _SilverFight(polls=(A.S.COMBAT, A.SILVER_GEN, A.S.DUNGEON))
    run, events, _ = _silver_run(monkeypatch, tmp_path, sess)
    got = run.fight("600", "I", 40)
    assert sess.stopped_at == 2
    assert got["outcome"] == A.S.WON and got["wander_gate"]["restored"] == 0
    assert [kw["wiped"] for kind, kw in events if kind == "silver-fight"] == [False]


def test_a_walk_that_finds_no_idle_move_bar_sends_nothing_and_does_not_call_it_a_wall(
        monkeypatch, tmp_path):
    sess = _SilverFight(idle=False)
    run, _, captures = _silver_run(monkeypatch, tmp_path, sess)
    run.clock = iter(range(0, 10_000)).__next__
    with pytest.raises(A.NoMoveKeySent, match="no key was sent"):
        run.fight("600", "I", 40)
    assert sess.moves == [] and not sess.fought
    assert sess.memory[A.SILVER_WANDER_GATE] == 0
    assert "lost-move-bar" in captures


def test_a_gate_that_will_not_go_back_fails_a_won_fight(monkeypatch, tmp_path):
    sess = _SilverFight(sticky_gate=True)
    run, _, _ = _silver_run(monkeypatch, tmp_path, sess)
    with pytest.raises(A.StepFailed, match=r"\$4C2D was not put back to 0: it reads 1"):
        run.fight("600", "I", 40)


def _raise_tags(run):
    return [x["tag"] for x in run.temple_checkpoints]


def test_temple_probe_raise_buys_raise_dead_and_records_the_result(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    result = run.temple_probe("BRUTUS RAISE")
    assert session.keys == (["side3", "YES", "HEAL"] + ["Down"] * 6
                            + ["Return", "YES"])
    assert _raise_tags(run)[-3:] == ["heal-screen", "raise-price",
                                     "raise-result"]
    assert "PAY FOR CURE" in "\n".join(result["raise_price"]["rows"])
    assert result["raise_result"]["rows"][12] == "BRUTUS IS ALIVE"
    assert result["raise_result"]["settled"] is True
    assert result["outcome"] == "alive"
    assert result["heal_screen"]["rows"][15] == _framed("RAISE DEAD")
    assert session.phase == "result"


@pytest.mark.parametrize("text,outcome", [
    ("BRUTUS FAILED", "failed"), ("NOT ENOUGH MONEY !", "no-money"),
    ("SOMETHING UNSEEN", "unknown")])
def test_temple_probe_raise_records_each_outcome_and_sends_nothing_after_yes(
        tmp_path, monkeypatch, text, outcome):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    session.result_text = text
    result = run.temple_probe("BRUTUS RAISE")
    assert result["outcome"] == outcome
    assert session.keys[-1] == "YES" and session.keys.count("YES") == 2
    assert session.keys.count("Return") == 1


def test_temple_probe_heal_sends_no_key_after_the_list(tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    result = run.temple_probe("BRUTUS HEAL")
    assert session.keys == ["side3", "YES", "HEAL"]
    assert "outcome" not in result and "raise_price" not in result


def test_temple_probe_raise_without_the_row_stops_before_any_down(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch,
                                            unsafe="list-no-raise")
    with pytest.raises(A.StepFailed, match="RAISE DEAD absent"):
        run.temple_probe("BRUTUS RAISE")
    assert session.keys == ["side3", "YES", "HEAL"]
    assert run.temple_checkpoints[-1]["tag"] == "lost-list"


def test_temple_probe_raise_stops_after_one_down_when_the_highlight_is_stuck(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch,
                                            unsafe="list-stuck")
    with pytest.raises(A.StepFailed, match="did not move"):
        run.temple_probe("BRUTUS RAISE")
    assert session.keys[3:] == ["Down"]
    assert run.temple_checkpoints[-1]["tag"] == "lost-list"


def test_temple_probe_raise_stops_on_a_price_screen_without_pay_for_cure(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch,
                                            unsafe="price-wrong")
    with pytest.raises(A.StepFailed, match="price screen"):
        run.temple_probe("BRUTUS RAISE")
    assert session.keys[-1] == "Return"
    assert "raise-price" in _raise_tags(run)
    assert run.temple_checkpoints[-1]["tag"] == "lost-price"


@pytest.mark.parametrize("unsafe", ["highlight-row-5", "other-top"])
def test_temple_probe_raise_refuses_a_member_other_than_the_top_row(
        tmp_path, monkeypatch, unsafe):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch,
                                            unsafe=unsafe)
    with pytest.raises(A.StepFailed, match="highlighted top row"):
        run.temple_probe("BRUTUS RAISE")
    assert session.keys == ["side3", "YES"]
    assert run.temple_checkpoints[-1]["tag"] == "lost-member"


def test_temple_probe_raise_classifies_the_outcome_from_the_last_screen_only(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    real = session.confirm_bar

    def confirm(row, was):
        real(row, was)
        if session.phase == "result":
            # The fast window (about 120 reads) and the first settled reads see
            # IS ALIVE; the last screen says FAILED.
            session.result_text = "BRUTUS IS ALIVE"
            reads = [0]
            original = session.screen

            def screen():
                reads[0] += 1
                if reads[0] > int(
                        A.TEMPLE_RESULT_WINDOW / A.TEMPLE_RESULT_POLL) + 20:
                    session.result_text = "BRUTUS FAILED"
                return original()
            session.screen = screen

    session.confirm_bar = confirm
    result = run.temple_probe("BRUTUS RAISE")
    assert any("IS ALIVE" in "\n".join(kw["rows"]) for a, kw in events
               if a[0] == "temple-heal-frame")
    assert any("IS ALIVE" in "\n".join(kw["rows"]) for a, kw in events
               if a[0] == "temple-result-frame")
    assert result["raise_result"]["rows"][12] == "BRUTUS FAILED"
    assert result["outcome"] == "failed"


def test_temple_probe_raise_keeps_a_result_frame_that_gives_way_to_the_menu(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    real = session.confirm_bar

    def reading():
        value = _temple_reading()
        paid = session.keys.count("YES") > 1
        value["party"][0]["gold"] = 500 if paid else 6000
        return value

    def confirm(row, was):
        real(row, was)
        if session.phase == "result":
            # The live run: the message stood under a second, then the menu.
            shown = [0]
            original = session.screen

            def screen():
                shown[0] += 1
                if shown[0] > 5:
                    session.phase = "temple"
                return original()
            session.screen = screen

    session.confirm_bar = confirm
    run.reading = reading
    result = run.temple_probe("BRUTUS RAISE")
    assert result["outcome"] == "alive"
    assert any("BRUTUS IS ALIVE" in f["rows"][12]
               for f in result["result_frames"])
    assert not any(f["is_price"] for f in result["result_frames"])
    assert result["raise_result"]["rows"][12] == ""
    assert result["gold_before"] == {"5:BRUTUS": 6000}
    assert result["gold_after"] == {"5:BRUTUS": 500}
    assert session.keys[-1] == "YES" and session.keys.count("YES") == 2


def test_temple_probe_raise_says_when_the_deadline_cut_the_result_window(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    real = session.confirm_bar

    def confirm(row, was):
        real(row, was)
        if session.phase == "result":
            run.temple_input_deadline = run.clock() + 1.0

    session.confirm_bar = confirm
    with pytest.raises(A.StepFailed, match="no steady screen"):
        run.temple_probe("BRUTUS RAISE")
    window = run.temple_result_window
    assert window["cut"] is True
    assert window["end"] - window["start"] < A.TEMPLE_RESULT_WINDOW
    assert [kw for a, kw in events if a[0] == "temple-result-window"] == [window]
    assert session.keys[-1] == "YES" and session.keys.count("YES") == 2


def test_temple_probe_raise_with_no_frame_in_the_window_reads_the_settled_screen(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    real = session.confirm_bar

    def confirm(row, was):
        real(row, was)
        if session.phase == "result":
            # The price screen stands for the whole window; the result
            # arrives only afterwards.
            session.phase = "price"
            reads = [0]
            original = session.screen

            def screen():
                reads[0] += 1
                if reads[0] > 200:
                    session.phase = "result"
                return original()
            session.screen = screen

    session.confirm_bar = confirm
    result = run.temple_probe("BRUTUS RAISE")
    assert result["result_frames"] == []
    assert result["result_window"]["cut"] is False
    assert result["result_window"]["frames"] == 1
    assert result["outcome"] == "alive"
    assert session.keys[-1] == "YES" and session.keys.count("YES") == 2


def test_temple_probe_raise_records_a_fault_inside_the_result_window(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    real = session.confirm_bar
    run.temple_result_window = {"stale": True}

    def confirm(row, was):
        real(row, was)
        if session.phase == "result":
            def broken():
                raise A.StepFailed("temple state unreadable: gone")
            run.temple_sample = broken

    session.confirm_bar = confirm
    with pytest.raises(A.StepFailed, match="unreadable"):
        run.temple_probe("BRUTUS RAISE")
    window = run.temple_result_window
    assert "stale" not in window and "unreadable" in window["faulted"]
    assert window["seconds"] == window["end"] - window["start"]
    assert session.keys[-1] == "YES" and session.keys.count("YES") == 2


@pytest.mark.parametrize("unsafe,missing", [
    ("price-wrong", "PAY FOR CURE"), ("price-no-cost", "the 5500 price")])
def test_temple_probe_raise_price_stop_names_the_missing_text(
        tmp_path, monkeypatch, unsafe, missing):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch,
                                            unsafe=unsafe)
    with pytest.raises(A.StepFailed, match=f"missing {missing}$"):
        run.temple_probe("BRUTUS RAISE")


def _staged_temple_pair(tmp_path, records):
    source = _fixture_disk(tmp_path)
    staged = tmp_path / "staged.D64"
    A.stage(source, staged, "pool-of-radiance", record_bytes=records)
    return source, staged


def test_temple_staging_check_takes_the_sanctioned_records_only(tmp_path):
    source, staged = _staged_temple_pair(
        tmp_path, list(A.TEMPLE_RAISE_STAGING))
    A.temple_staging_check(source, staged, list(A.TEMPLE_RAISE_STAGING),
                           A.TEMPLE_RAISE_STAGING)
    extra, staged2 = _staged_temple_pair(
        tmp_path, [*A.TEMPLE_RAISE_STAGING, (5, 0x20, 41)])
    with pytest.raises(ValueError, match="changed payload byte"):
        A.temple_staging_check(extra, staged2, list(A.TEMPLE_RAISE_STAGING),
                               A.TEMPLE_RAISE_STAGING)
    with pytest.raises(ValueError, match="is not"):
        A.temple_staging_check(source, staged, [(5, 0x18, 18)],
                               A.TEMPLE_RAISE_STAGING)


def test_temple_staging_check_refuses_a_wrong_value_and_a_changed_hash(
        tmp_path):
    source, staged = _staged_temple_pair(
        tmp_path, [(5, 0x018, 17), (5, 0x0C1, 0x70), (5, 0x0C2, 0x17)])
    with pytest.raises(ValueError, match="not 0x12"):
        A.temple_staging_check(source, staged, list(A.TEMPLE_RAISE_STAGING),
                               A.TEMPLE_RAISE_STAGING)
    source2, staged2 = _staged_temple_pair(tmp_path, [(5, 0x20, 41)])
    with pytest.raises(ValueError, match="changed the source bytes"):
        A.temple_staging_check(source2, staged2, (), A.TEMPLE_RAISE_STAGING)
    same = tmp_path / "same.D64"
    same.write_bytes(source2.read_bytes())
    A.temple_staging_check(source2, same, (), A.TEMPLE_RAISE_STAGING)


class _Claimed(Exception):
    pass


def _run_raise(tmp_path, monkeypatch, extra_byte=None, staging=True):
    monkeypatch.setattr(A, "temple_source_guard", lambda path: A.TEMPLE_BRUTUS_SHA256)
    real = A.stage

    def stage(*args, **kwargs):
        got = real(*args, **kwargs)
        if extra_byte is not None:
            image = D64.open(str(args[1]))
            addr, payload = A._payload(image, A.c64_port.POOL_OF_RADIANCE)
            payload[extra_byte] ^= 0xFF
            image.write_file_inplace(
                A.c64_port.POOL_OF_RADIANCE.save_file,
                addr.to_bytes(2, "little") + bytes(payload))
            image.save(str(args[1]))
        return got
    monkeypatch.setattr(A, "stage", stage)

    def claim(*a, **k):
        raise _Claimed
    monkeypatch.setattr(A.S, "claim_slot", claim)
    out = tmp_path / "out"
    argv = _raise_argv(tmp_path, *(_RAISE_STAGING if staging else []),
                       step="temple-probe BRUTUS " + ("RAISE" if staging
                                                       else "HEAL"))
    return A.main(argv), out


def test_temple_run_proceeds_to_the_claim_with_the_sanctioned_records(
        tmp_path, monkeypatch):
    with pytest.raises(_Claimed):
        _run_raise(tmp_path, monkeypatch)


def test_temple_run_refuses_an_extra_differing_byte_before_the_claim(
        tmp_path, monkeypatch):
    code, out = _run_raise(tmp_path, monkeypatch, extra_byte=0x400)
    assert code == 1
    assert "changed payload byte" in json.loads(
        (out / "summary.json").read_text())["lost"]


def test_temple_run_with_no_records_still_refuses_a_changed_hash(
        tmp_path, monkeypatch):
    code, out = _run_raise(tmp_path, monkeypatch, extra_byte=0x400,
                           staging=False)
    assert code == 1
    assert "changed the source bytes" in json.loads(
        (out / "summary.json").read_text())["lost"]


def _menu_after(session, reads):
    """Make the fake's result screen give way to the temple menu after READS
    screen reads, as the live refusal did."""
    original = session.screen
    shown = [0]

    def screen():
        shown[0] += 1
        if session.phase == "result" and shown[0] > reads:
            session.phase = "temple"
        return original()
    session.screen = screen


def test_temple_probe_keeps_a_refusal_drawn_on_row_24_over_the_price_screen(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    session.result_bar = "NOT ENOUGH MONEY !"
    real = session.confirm_bar

    def confirm(row, was):
        real(row, was)
        if session.phase == "result":
            _menu_after(session, 5)

    session.confirm_bar = confirm
    result = run.temple_probe("BRUTUS RAISE")
    refusal = [f for f in result["result_frames"]
               if f["rows"][24] == "NOT ENOUGH MONEY !"]
    assert len(refusal) == 1
    assert refusal[0]["rows"][:24] == result["raise_price"]["rows"][:24]
    assert result["outcome"] == "no-money"


def test_temple_probe_still_drops_a_frame_that_is_the_price_screen_itself(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    session.result_bar = "YES NO"
    real = session.confirm_bar

    def confirm(row, was):
        real(row, was)
        if session.phase == "result":
            _menu_after(session, 5)

    session.confirm_bar = confirm
    result = run.temple_probe("BRUTUS RAISE")
    assert not any(f["is_price"] for f in result["result_frames"])
    assert result["outcome"] == "unknown"


@pytest.mark.parametrize("text,outcome", [
    ("CURED", "cured"), ("BRUTUS IS ALIVE", "alive"),
    ("CURED\nBRUTUS FAILED", "failed"),
    ("THAT SPELL CAN NOT HELP YOU", "cannot-help")])
def test_temple_outcome_reads_the_cure_and_refusal_texts(text, outcome):
    assert A.PoolRun._temple_outcome(text) == outcome


_POOL_KEYS = ["side3", "YES", "Right", "Right", "POOL", "pool-YES",
              "Left", "Left", "HEAL"] + ["Down"] * 6 + ["Return", "YES"]


def test_temple_probe_pools_the_money_then_raises_and_sends_nothing_after_yes(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    result = run.temple_probe("BRUTUS RAISE POOL")
    assert session.keys == _POOL_KEYS
    assert session.keys[-1] == "YES" and session.keys.count("YES") == 2
    assert _raise_tags(run)[-5:] == ["pool-question", "pool-done",
                                     "heal-screen", "raise-price",
                                     "raise-result"]
    assert result["pool"]["question"] and result["pool"]["done"]
    assert result["outcome"] == "alive"


def test_temple_probe_plain_raise_never_touches_pool(tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    run.temple_probe("BRUTUS RAISE")
    assert "POOL" not in session.keys and "pool-YES" not in session.keys


def test_temple_probe_stops_when_pool_asks_something_else(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    original = session.screen

    def screen():
        got = original()
        if session.phase == "poolq":
            rows = [got.row(n) for n in range(25)]
            rows[11] = "SOMETHING ELSE"
            return _TempleScreen(rows, (0, 3))
        return got
    session.screen = screen
    with pytest.raises(A.StepFailed, match="no POOL question"):
        run.temple_probe("BRUTUS RAISE POOL")
    assert "pool-YES" not in session.keys and "HEAL" not in session.keys
    assert run.temple_checkpoints[-1]["tag"] == "lost-pool"


def _control_reading(status=0x83, flags=0x01):
    return {"party": [{"slot": 5, "name": "BRUTUS", "status": status,
                       "traits": [0] * 10, "creature_type": 0,
                       "record_bytes": {"0xB8": flags}}],
            "effect_rows": [None] * 64, "effects": []}


def test_temple_probe_control_raises_an_ordinary_dead_member_without_pool(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    run.reading = _control_reading
    result = run.temple_probe("BRUTUS RAISE CONTROL")
    assert session.keys == (["side3", "YES", "HEAL"] + ["Down"] * 6
                            + ["Return", "YES"])
    assert "pool" not in result and result["outcome"] == "alive"


@pytest.mark.parametrize("reading", [
    _temple_reading(), _control_reading(status=3),
    _control_reading(flags=0xFF)])
def test_temple_probe_control_refuses_a_member_that_is_not_status_83(
        tmp_path, monkeypatch, reading):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    run.reading = lambda: reading
    with pytest.raises(A.StepFailed, match="control BRUTUS"):
        run.temple_probe("BRUTUS RAISE CONTROL")
    assert session.keys == []


_POOL_STAGING = ["--stage-record", "0:0x0C1=0x70,0:0x0C2=0x17,5:0x018=18"]


def test_temple_probe_step_takes_pool_and_control_for_raise_only():
    for good in ("BRUTUS RAISE POOL", "BRUTUS RAISE CONTROL"):
        assert A.parse_steps(["load", f"temple-probe {good}"])[1] == (
            A.Step("temple-probe", good))
    for bad in ("BRUTUS POOL", "BRUTUS HEAL POOL", "BRUTUS RAISE POOL POOL",
                "BRUTUS RAISE POOL CONTROL"):
        with pytest.raises(ValueError):
            A.parse_steps(["load", f"temple-probe {bad}"])


def test_temple_probe_main_accepts_pool_with_exactly_its_staging(
        tmp_path, monkeypatch):
    observed = []
    monkeypatch.setattr(A, "temple_source_guard", lambda path: A.TEMPLE_BRUTUS_SHA256)
    monkeypatch.setattr(A, "run", lambda args, steps, out, selected: observed.append(
        (steps, args.stage_record)) or 0)
    assert A.main(_raise_argv(tmp_path, *_POOL_STAGING,
                              step="temple-probe BRUTUS RAISE POOL")) == 0
    assert observed == [([A.Step("load"),
                          A.Step("temple-probe", "BRUTUS RAISE POOL")],
                         [_POOL_STAGING[1]])]


@pytest.mark.parametrize("extra,step", [
    (_RAISE_STAGING, "temple-probe BRUTUS RAISE POOL"),
    (["--stage-record", "0:0x0C1=0x70,0:0x0C2=0x17"], "temple-probe BRUTUS RAISE POOL"),
    (["--stage-record", "0:0x0C1=0x70,0:0x0C2=0x17,5:0x018=17"],
     "temple-probe BRUTUS RAISE POOL"),
    (["--stage-record", "1:0x0C1=0x70,1:0x0C2=0x17,5:0x018=18"],
     "temple-probe BRUTUS RAISE POOL"),
    ([*_POOL_STAGING, "--stage-record", "5:0x20=1"],
     "temple-probe BRUTUS RAISE POOL"),
    ([], "temple-probe BRUTUS RAISE POOL"),
    (_POOL_STAGING, "temple-probe BRUTUS RAISE"),
    (_POOL_STAGING, "temple-probe BRUTUS RAISE CONTROL"),
    (_POOL_STAGING, "temple-probe BRUTUS HEAL"),
])
def test_temple_probe_pool_refuses_other_staging_before_a_slot_is_claimed(
        tmp_path, monkeypatch, extra, step):
    monkeypatch.setattr(A, "temple_source_guard", lambda path: A.TEMPLE_BRUTUS_SHA256)
    _refused_before_a_slot(tmp_path, monkeypatch, _raise_argv(
        tmp_path, *extra, step=step)[:-2])


def test_temple_staging_check_takes_the_pool_records_only(tmp_path):
    source, staged = _staged_temple_pair(
        tmp_path, list(A.TEMPLE_POOL_STAGING))
    A.temple_staging_check(source, staged, list(A.TEMPLE_POOL_STAGING),
                           A.TEMPLE_POOL_STAGING)
    with pytest.raises(ValueError, match="is not"):
        A.temple_staging_check(source, staged, list(A.TEMPLE_POOL_STAGING),
                               A.TEMPLE_RAISE_STAGING)
    extra, staged2 = _staged_temple_pair(
        tmp_path, [*A.TEMPLE_POOL_STAGING, (5, 0x20, 41)])
    with pytest.raises(ValueError, match="changed payload byte"):
        A.temple_staging_check(extra, staged2, list(A.TEMPLE_POOL_STAGING),
                               A.TEMPLE_POOL_STAGING)


def test_guard_temple_source_passes_the_control_hash_only_for_a_control_step(
        monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(A, "temple_source_guard",
                        lambda path, expected=None: seen.append(expected)
                        or A.TEMPLE_BRUTUS_SHA256)
    A._guard_temple_source(tmp_path, [A.Step("load"), A.Step(
        "temple-probe", "BRUTUS RAISE CONTROL")])
    A._guard_temple_source(tmp_path, [A.Step("load"), A.Step(
        "temple-probe", "BRUTUS RAISE POOL")])
    assert seen == [A.TEMPLE_CONTROL_SHA256, None]


_CONTROL_STAGING = ["--stage-record", "5:0x018=18,5:0x0C1=0x70,5:0x0C2=0x17"]


def test_temple_probe_main_accepts_control_with_exactly_its_staging(
        tmp_path, monkeypatch):
    observed = []
    guards = []
    monkeypatch.setattr(A, "temple_source_guard",
                        lambda path, expected=None: guards.append(expected))
    monkeypatch.setattr(A, "run", lambda args, steps, out, selected: observed.append(
        (steps, args.stage_record)) or 0)
    assert A.main(_raise_argv(tmp_path, *_CONTROL_STAGING,
                              step="temple-probe BRUTUS RAISE CONTROL")) == 0
    assert observed == [([A.Step("load"),
                          A.Step("temple-probe", "BRUTUS RAISE CONTROL")],
                         [_CONTROL_STAGING[1]])]
    assert sorted(A.TEMPLE_CONTROL_STAGING) == [
        (5, 0x018, 18), (5, 0x0C1, 0x70), (5, 0x0C2, 0x17)]


@pytest.mark.parametrize("frames,outcome", [
    (["CURED", "BRUTUS IS ALIVE"], "alive"),
    (["CURED"], "cured")])
def test_temple_probe_reads_the_cure_frames_into_an_outcome(
        tmp_path, monkeypatch, frames, outcome):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    session.result_frames = frames
    real = session.confirm_bar

    def confirm(row, was):
        real(row, was)
        if session.phase == "result":
            _menu_after(session, 10)

    session.confirm_bar = confirm
    result = run.temple_probe("BRUTUS RAISE")
    seen = ["\n".join(f["rows"]) for f in result["result_frames"]]
    assert any("CURED" in text for text in seen)
    assert result["outcome"] == outcome


def test_temple_probe_pool_keeps_the_pool_coins_before_yes_and_after(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    result = run.temple_probe("BRUTUS RAISE POOL")
    assert result["pool_before"]["words"] == [0, 0, 0, 6000, 0]
    assert result["pool_after"]["words"] == [0, 0, 0, 500, 0]
    (tmp_path / "b").mkdir()
    plain = _temple_fake_run(tmp_path / "b", monkeypatch)
    assert "pool_before" not in plain[0].temple_probe("BRUTUS RAISE")


def test_temple_probe_pool_records_an_unreadable_pool_and_still_finishes(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    session.pool_read_error = True
    result = run.temple_probe("BRUTUS RAISE POOL")
    assert list(result["pool_before"]) == ["error"]
    assert "monitor gone" in result["pool_before"]["error"]
    assert list(result["pool_after"]) == ["error"]
    assert result["outcome"] == "alive"
    assert session.keys == _POOL_KEYS



WATCH_EVENT = _window({17: "YOU ARE ROUSTED BY THE CITY WATCH AND",
                       18: "TOLD TO MOVE ALONG. WHAT DO YOU DO?"}, "GO STAY")
POOL_REST_BAR = "REST  INCREASE  DECREASE  EXIT"


class _RestSession(FakeSession):
    """A party whose square is read from `squares`, one per call, and whose
    screens in `later` are replaced by the game itself after that many reads,
    with no key: `{state: (reads, next state)}`."""

    squares = None
    later: dict = {}
    reads = 0
    #: States in which LINKER's mode byte reads COMBAT.
    combat_states: frozenset = frozenset()

    def position(self):
        return self.squares.pop(0)

    def in_combat(self):
        return self.state in self.combat_states

    def screen(self):
        if self.state in self.later:
            reads, following = self.later[self.state]
            self.reads += 1
            if self.reads > reads:
                self.state, self.reads = following, 0
        return super().screen()


def _watch_rest(tmp_path, monkeypatch, *, end="event", before=(0, 3, 0, 0, 0, 0),
                after=(0, 8, 0, 0, 0, 0), arg="5h", moves=None, extra=None,
                squares=([10, 4, 2], [11, 4, 2]), marker=None, later=None):
    """A rest whose route_pool half ends on screen END, driven by MOVES and
    replaced by the game as LATER says.

    MARKER, when given, is the `$6DD3` value the Pool rest read after an
    interrupted rest, returned the way `route_pool.rest` returns one; 0 is
    the live New Phlan reading, with `CAMP` already gone from `$0800`."""
    screens = {"world": _window({}, WORLD_BAR), "camp": _window({}, CAMP),
               "event": WATCH_EVENT, "event2": WATCH_EVENT,
               "restbar": _window({}, POOL_REST_BAR),
               "rudely": _window({18: "YOUR REST IS RUDELY INTERRUPTED!"},
                                 A.CONTINUE),
               "stuck": _window({}, "SOMETHING ELSE"),
               "world-late": _window({}, WORLD_BAR),
               "patrol": _window({18: "A PATROL CONFRONTS YOU"},
                                 "COMBAT WAIT FLEE ADVANCE"),
               "blank": _window({}, "")}
    screens.update(extra or {})
    table = {("world", ("bar", "ENCAMP")): "camp",
             ("event", ("bar", "GO")): "world"}
    table.update(moves or {})
    sess = _RestSession(screens, table, "world")
    sess.squares = list(squares)
    sess.later = dict(later or {})

    def fake_rest(s, log, minutes, hours, cp):
        s.state = end
        got = {"before": {"clock": list(before)}, "after": {"clock": list(after)}}
        if marker is not None:
            got.update(ended="interrupted", interrupted=True,
                       bar=POOL_REST_BAR, rest_marker=marker,
                       camp_resident=marker == 0xFF)
        return got

    monkeypatch.setattr(A.route_pool, "rest", fake_rest)
    run, log = _pool_run(tmp_path, sess)
    return run, log, sess


def test_rest_answers_the_city_watch_go_stay_and_reports_the_unfinished_rest(
        tmp_path, monkeypatch):
    """A rest that ends on the watch's GO STAY bar is answered GO, the event is
    logged, the rest is reported short, and the world bar is found after it."""
    run, log, sess = _watch_rest(tmp_path, monkeypatch)
    got = run.rest("5h")
    assert run.to_world()
    log.close()

    assert sess.sent[-1] == ("bar", "GO")
    assert ("bar", "STAY") not in sess.sent
    assert got["rest_completed"] is False and got["elapsed_minutes"] == 5
    assert [e["event"] for e in got["events"]] == ["go_stay"]
    assert got["events"][0]["text"][0].startswith("YOU ARE ROUSTED")
    assert '"random_event"' in (tmp_path / "run.jsonl").read_text()
    assert got["position_before"] == [10, 4, 2]
    assert got["position_after"] == [11, 4, 2]
    assert sess.state == "world"


def test_rest_with_no_event_is_completed_and_the_party_has_not_moved(
        tmp_path, monkeypatch):
    run, log, sess = _watch_rest(
        tmp_path, monkeypatch, end="world", arg="5m",
        before=(0, 3, 0, 0, 0, 0), after=(0, 8, 0, 0, 0, 0))
    sess.squares = [[10, 4, 2], [10, 4, 2]]
    got = run.rest("5m")
    log.close()
    assert got["events"] == [] and got["rest_completed"] is True
    assert got["position_before"] == got["position_after"] == [10, 4, 2]
    assert set(got) == {"asked", "before_clock", "after_clock",
                        "elapsed_minutes", "rest_completed", "events",
                        "position_before", "position_after"}


def test_rest_rounds_the_asked_time_up_to_the_five_minute_pass(
        tmp_path, monkeypatch):
    run, log, _ = _watch_rest(
        tmp_path, monkeypatch, end="world",
        before=(0, 0, 0, 0, 0, 0), after=(0, 5, 0, 0, 0, 0))
    assert run.rest("7m")["rest_completed"] is False     # 7m runs to 10
    run, log2, _ = _watch_rest(
        tmp_path, monkeypatch, end="world",
        before=(0, 0, 0, 0, 0, 0), after=(0, 0, 1, 0, 0, 0))
    assert run.rest("7m")["rest_completed"] is True
    log.close()
    log2.close()


def test_rest_measures_a_rest_across_midnight_by_hour_and_day(
        tmp_path, monkeypatch):
    # 23:00 on day 3 to 01:00 on day 4 is two hours.
    run, log, _ = _watch_rest(
        tmp_path, monkeypatch, end="world", arg="2h",
        before=(0, 0, 0, 23, 3, 1), after=(0, 0, 0, 1, 4, 1))
    got = run.rest("2h")
    log.close()
    assert got["elapsed_minutes"] == 120 and got["rest_completed"] is True


def test_rest_across_a_month_wrap_does_not_say_whether_it_completed(
        tmp_path, monkeypatch):
    run, log, _ = _watch_rest(
        tmp_path, monkeypatch, end="world", arg="2h",
        before=(0, 0, 0, 23, 30, 1), after=(0, 0, 0, 1, 1, 2))
    got = run.rest("2h")
    log.close()
    assert got["elapsed_minutes"] < 0 and got["rest_completed"] is None


def test_rest_answers_two_events_and_fails_on_a_third(tmp_path, monkeypatch):
    run, log, sess = _watch_rest(
        tmp_path, monkeypatch,
        moves={("event", ("bar", "GO")): "event2",
               ("event2", ("bar", "GO")): "event"})
    with pytest.raises(A.StepFailed, match="still up after 2 answers"):
        run.rest("5h")
    log.close()
    assert sess.sent.count(("bar", "GO")) == 2


def test_rest_two_events_then_the_map_is_answered_twice(tmp_path, monkeypatch):
    run, log, sess = _watch_rest(
        tmp_path, monkeypatch,
        moves={("event", ("bar", "GO")): "event2",
               ("event2", ("bar", "GO")): "world"})
    got = run.rest("5h")
    log.close()
    assert len(got["events"]) == 2 and sess.state == "world"


def test_rest_fails_when_go_cannot_be_chosen(tmp_path, monkeypatch):
    run, log, sess = _watch_rest(tmp_path, monkeypatch)
    sess.select_bar = lambda label, row=24, timeout=0: (
        False if label == "GO" else FakeSession.select_bar(sess, label))
    with pytest.raises(A.StepFailed, match="GO could not be chosen"):
        run.rest("5h")
    log.close()


def test_rest_fails_when_the_world_bar_does_not_return_after_go(
        tmp_path, monkeypatch):
    run, log, sess = _watch_rest(
        tmp_path, monkeypatch, moves={("event", ("bar", "GO")): "stuck"})
    with pytest.raises(A.StepFailed, match="world bar never came back"):
        run.rest("5h")
    log.close()


def test_rest_interrupted_waits_without_a_key_and_answers_the_watch(
        tmp_path, monkeypatch):
    """The live New Phlan rest: the check stops it after one pass and the game
    leaves camp by itself, with the rest-time bar still drawn while it loads;
    the watch's GO STAY comes up with no key, is answered GO, and the step
    says the rest was cut short."""
    run, log, sess = _watch_rest(
        tmp_path, monkeypatch, end="restbar", marker=0x00, arg="1h",
        before=(0, 2, 0, 0, 0, 0), after=(0, 7, 0, 0, 0, 0),
        later={"restbar": (3, "event")})
    got = run.rest("1h")
    log.close()
    assert sess.sent == [("bar", "ENCAMP"), ("bar", "GO")]
    assert sess.state == "world"
    assert got["ended"] == "interrupted" and got["interrupted"] is True
    assert got["bar"] == "GO STAY" and got["prompts"] == ["GO STAY"]
    assert got["rest_completed"] is False and got["elapsed_minutes"] == 5
    assert [e["event"] for e in got["events"]] == ["go_stay"]
    assert got["events"][0]["text"][0].startswith("YOU ARE ROUSTED")
    assert got["watch_seen"] is True
    assert got["state_cleared"] == ["$4A07", "$4A0F", "$4A10", "$4A11"]
    logged = (tmp_path / "run.jsonl").read_text()
    assert '"rest_interrupted"' in logged and '"random_event"' in logged


def test_rest_interrupted_answers_a_press_bar_before_the_watch(
        tmp_path, monkeypatch):
    run, log, sess = _watch_rest(
        tmp_path, monkeypatch, end="restbar", marker=0xFF,
        later={"restbar": (2, "rudely")},
        moves={("rudely", ("key", 0x0D)): "event"})
    got = run.rest("1h")
    log.close()
    assert sess.sent == [("bar", "ENCAMP"), ("key", 0x0D), ("bar", "GO")]
    assert got["prompts"] == [A.CONTINUE, "GO STAY"]
    assert got["bar"] == "GO STAY" and sess.state == "world"


def test_rest_interrupted_with_no_prompt_is_reported_once_the_world_is_back(
        tmp_path, monkeypatch):
    run, log, sess = _watch_rest(
        tmp_path, monkeypatch, end="restbar", marker=0x00,
        later={"restbar": (2, "world")})
    got = run.rest("1h")
    log.close()
    assert got["interrupted"] is True and got["events"] == []
    assert got["bar"] == "" and got["prompts"] == []
    assert got["watch_seen"] is False and "state_cleared" not in got
    assert sess.sent == [("bar", "ENCAMP")] and sess.state == "world"


def test_rest_interrupted_answers_a_watch_drawn_after_the_world_bar_held(
        tmp_path, monkeypatch):
    """The world bar holds through the wait and is found again, and only then
    does GO STAY come up: the step's last read still sees and answers it."""
    run, log, sess = _watch_rest(
        tmp_path, monkeypatch, end="restbar", marker=0x00,
        later={"restbar": (2, "world-late"), "world-late": (3, "event")})
    got = run.rest("1h")
    log.close()
    assert sess.sent == [("bar", "ENCAMP"), ("bar", "GO")]
    assert sess.state == "world"
    assert got["watch_seen"] is True
    assert got["bar"] == "GO STAY" and got["prompts"] == ["GO STAY"]
    assert [e["event"] for e in got["events"]] == ["go_stay"]
    assert got["state_cleared"] == ["$4A07", "$4A0F", "$4A10", "$4A11"]


@pytest.mark.parametrize("state, combat", [("patrol", ()), ("blank", ("blank",))])
def test_rest_interrupted_by_a_fight_fails_at_once_and_sends_no_key(
        tmp_path, monkeypatch, state, combat):
    """An encounter's COMBAT menu on row 24, or the mode byte reading COMBAT,
    stops the step at once: the rest step does not fight, and the fight step
    cannot start from a fight already under way."""
    monkeypatch.setattr(A, "REST_LEAVE_SECONDS", 5)
    run, log, sess = _watch_rest(
        tmp_path, monkeypatch, end="restbar", marker=0x00,
        later={"restbar": (2, state)})
    sess.combat_states = frozenset(combat)
    started = time.monotonic()
    with pytest.raises(A.StepFailed, match="a fight"):
        run.rest("1h")
    log.close()
    assert time.monotonic() - started < 3
    assert sess.sent == [("bar", "ENCAMP")]


@pytest.mark.parametrize("later, named", [
    ({"restbar": (2, "stuck")}, "SOMETHING ELSE"),
    ({}, "REST  INCREASE  DECREASE  EXIT"),
])
def test_rest_interrupted_by_a_screen_it_cannot_answer_fails_naming_it(
        tmp_path, monkeypatch, later, named):
    """A prompt the step does not know, or the rest-time bar never giving way,
    stops the run naming row 24, and no key is sent at either."""
    monkeypatch.setattr(A, "REST_LEAVE_SECONDS", 0.5)
    run, log, sess = _watch_rest(
        tmp_path, monkeypatch, end="restbar", marker=0x00, later=later)
    with pytest.raises(A.StepFailed, match=re.escape(repr(named))):
        run.rest("1h")
    log.close()
    assert sess.sent == [("bar", "ENCAMP")]


def test_rest_leaves_a_take_stay_bar_alone(tmp_path, monkeypatch):
    other = _window({}, "TAKE STAY")
    run, log, sess = _watch_rest(
        tmp_path, monkeypatch, end="other", extra={"other": other},
        moves={("other", ("key", 0x0D)): "world"})
    got = run.rest("5h")
    log.close()
    assert got["events"] == [] and ("bar", "GO") not in sess.sent


LATER_EVENT = _window({17: "THE BLACK CIRCLE SENDS MONSTERS",
                       18: "AGAINST THE TOWN. TOWNSMEN RUSH TO",
                       19: "YOUR AID."}, "PRESS BUTTON OR RETURN TO CONTINUE.")
LATER_COMBAT_BAR = "MOVE VIEW AIM USE QUICK DONE"


class _LaterRestSession(_RestSession):
    """`_RestSession` with the later titles' `press_bar`, `to_world_bar`
    answering a PRESS bar with Return as the real one does, and a square that
    never moves."""

    def press_bar(self, label, row=24, timeout=0):
        return self._go(("bar", label))

    def to_world_bar(self, timeout=0):
        if "PRESS" in self.screens[self.state][24]:
            self._go(("key", 0x0D))
        return A.PoolRun.at_world(self.screens[self.state][24])

    def steady_triple(self):
        return (0, 5, 3)


def _later_rest(tmp_path, monkeypatch, *, end, later=None, moves=None,
                ended="interrupted", with_text=True):
    """A Silver Blades rest whose `route_pool.rest_later` half ends on screen
    END with `ended` as given, 8 hours of a 10-hour rest run."""
    screens = {"world": _window({}, WORLD_BAR), "camp": _window({}, CAMP),
               "event": LATER_EVENT, "prep": _window({}, ""),
               "combat": _window({}, LATER_COMBAT_BAR),
               "stuck": _window({}, "SOMETHING ELSE"),
               "event2": _window({17: "THE TOWNSMEN FALL BACK."},
                                 "PRESS BUTTON OR RETURN TO CONTINUE.")}
    table = {("world", ("bar", "ENCAMP")): "camp",
             ("camp", ("bar", "EXIT")): "world"}
    table.update(moves or {})
    sess = _LaterRestSession(screens, table, "world")
    sess.later = dict(later or {})

    def fake_rest(s, log, minutes, hours, cp):
        s.state = end
        rows = screens[end]
        got = {"before": {"clock": [0, 7, 2, 5, 0, 0]},
               "after": {"clock": [0, 7, 2, 13, 0, 0]},
               "ended": ended, "interrupted": ended == "interrupted",
               "rest_left": [0, 2, 0] if ended == "interrupted" else [0, 0, 0],
               "bar": rows[24].rstrip(), "rest_interrupt": [96, 30]}
        if ended == "interrupted" and with_text:
            got["text"] = [r.strip("$%& ") for r in rows[17:23]
                           if r.strip("$%& ")]
        return got

    monkeypatch.setattr(A.route_pool, "rest", fake_rest)
    run = A.SilverRun.__new__(A.SilverRun)
    run.sess, run.out, run.log = sess, tmp_path, A.Log(tmp_path)
    run.shots, run.armed, run.attack_by = 0, {}, ""
    run.game = SimpleNamespace(key="secret-of-the-silver-blades")
    return run, run.log, sess


@pytest.mark.parametrize("combat", [(), ("prep",)])
def test_a_later_rest_an_event_turns_into_a_fight_fails_at_once_naming_it(
        tmp_path, monkeypatch, combat):
    """The live Silver Blades rest: at 8 hours of 10 the Black Circle's text
    comes up over `PRESS BUTTON OR RETURN TO CONTINUE.`, and after Return a
    fight begins -- the combat command bar, or a blank row 24 with the mode
    byte reading COMBAT.  The step answers the page, then stops at once
    naming the event, rather than returning into a step that cannot work."""
    monkeypatch.setattr(A, "REST_LEAVE_SECONDS", 5)
    run, log, sess = _later_rest(
        tmp_path, monkeypatch, end="event", later={"prep": (2, "combat")},
        moves={("event", ("key", 0x0D)): "prep"})
    sess.combat_states = frozenset(combat)
    started = time.monotonic()
    with pytest.raises(A.StepFailed, match="a fight") as caught:
        run.rest("10h")
    log.close()
    assert time.monotonic() - started < 4
    assert "THE BLACK CIRCLE SENDS MONSTERS" in str(caught.value)
    assert sess.sent == [("bar", "ENCAMP"), ("key", 0x0D)]
    logged = (tmp_path / "run.jsonl").read_text()
    assert '"rest_interrupted"' in logged and '"rest_prompt"' in logged


def test_a_later_rest_an_event_ends_back_in_camp_is_reported_and_left(
        tmp_path, monkeypatch):
    """An event page that gives way to the camp bar, not a fight, is answered
    and reported with its text, and the step goes on to the world."""
    run, log, sess = _later_rest(
        tmp_path, monkeypatch, end="event",
        moves={("event", ("key", 0x0D)): "camp"})
    got = run.rest("10h")
    log.close()
    assert sess.sent == [("bar", "ENCAMP"), ("key", 0x0D), ("bar", "EXIT")]
    assert sess.state == "world"
    assert got["ended"] == "interrupted" and got["interrupted"] is True
    assert got["bar"] == "PRESS BUTTON OR RETURN TO CONTINUE."
    assert got["prompts"] == ["PRESS BUTTON OR RETURN TO CONTINUE."]
    assert got["text"] == ["THE BLACK CIRCLE SENDS MONSTERS",
                           "AGAINST THE TOWN. TOWNSMEN RUSH TO", "YOUR AID."]
    assert got["rest_completed"] is False and got["elapsed_minutes"] == 480
    assert "watch_seen" not in got and "state_cleared" not in got


def test_a_later_rest_interrupted_by_a_screen_it_cannot_answer_fails_naming_it(
        tmp_path, monkeypatch):
    monkeypatch.setattr(A, "REST_LEAVE_SECONDS", 0.5)
    run, log, sess = _later_rest(
        tmp_path, monkeypatch, end="event",
        moves={("event", ("key", 0x0D)): "stuck"})
    with pytest.raises(A.StepFailed, match=re.escape(repr("SOMETHING ELSE"))):
        run.rest("10h")
    log.close()
    assert sess.sent == [("bar", "ENCAMP"), ("key", 0x0D)]


def test_a_later_rest_with_more_pages_than_the_cap_fails_naming_them(
        tmp_path, monkeypatch):
    """Pages that keep coming are answered up to `REST_LEAVE_PROMPTS`, and the
    next one fails the step rather than being answered."""
    monkeypatch.setattr(A, "REST_LEAVE_SECONDS", 1)
    run, log, sess = _later_rest(
        tmp_path, monkeypatch, end="event",
        moves={("event", ("key", 0x0D)): "event2",
               ("event2", ("key", 0x0D)): "event"})
    with pytest.raises(A.StepFailed,
                       match=f"more than {A.REST_LEAVE_PROMPTS} pages"):
        run.rest("10h")
    log.close()
    assert sess.sent.count(("key", 0x0D)) == A.REST_LEAVE_PROMPTS


def test_a_later_rest_page_that_does_not_change_after_return_is_capped(
        tmp_path, monkeypatch):
    """A page the game does not take the Return for is pressed again once the
    wait for it to change runs out, and the cap still ends the step."""
    monkeypatch.setattr(A, "REST_LEAVE_SECONDS", 1)
    monkeypatch.setattr(A, "ARRIVAL_PAGE_SECONDS", 0.2)
    run, log, sess = _later_rest(
        tmp_path, monkeypatch, end="event",
        moves={("event", ("key", 0x0D)): "event"})
    with pytest.raises(A.StepFailed,
                       match=f"more than {A.REST_LEAVE_PROMPTS} pages"):
        run.rest("10h")
    log.close()
    assert sess.sent == [("bar", "ENCAMP")] + [("key", 0x0D)] * A.REST_LEAVE_PROMPTS


def test_a_later_rest_fight_over_the_event_page_names_the_event(
        tmp_path, monkeypatch):
    """With no text from the rest's own read, a fight found while the event's
    page is still drawn is named from that page."""
    monkeypatch.setattr(A, "REST_LEAVE_SECONDS", 1)
    run, log, sess = _later_rest(tmp_path, monkeypatch, end="event",
                                 with_text=False)
    sess.combat_states = frozenset({"event"})
    with pytest.raises(A.StepFailed, match="a fight") as caught:
        run.rest("10h")
    log.close()
    assert "THE BLACK CIRCLE SENDS MONSTERS" in str(caught.value)
    assert sess.sent == [("bar", "ENCAMP")]


def test_rest_interrupted_on_the_combat_command_bar_fails_as_a_fight(
        tmp_path, monkeypatch):
    """A Pool interrupted rest that meets the fight's command bar is a fight
    even when the mode byte does not read COMBAT."""
    monkeypatch.setattr(A, "REST_LEAVE_SECONDS", 5)
    run, log, sess = _watch_rest(
        tmp_path, monkeypatch, end="restbar", marker=0x00,
        later={"restbar": (2, "command")},
        extra={"command": _window({}, LATER_COMBAT_BAR)})
    assert not sess.in_combat()
    with pytest.raises(A.StepFailed, match="a fight"):
        run.rest("1h")
    log.close()
    assert sess.sent == [("bar", "ENCAMP")]


def test_a_later_rest_that_completes_is_unchanged(tmp_path, monkeypatch):
    """A later-title rest that ran its time returns the keys and fields a
    Pool rest with no event does, and sends nothing but ENCAMP and EXIT."""
    run, log, sess = _later_rest(tmp_path, monkeypatch, end="camp",
                                 ended="completed")
    got = run.rest("8h")
    log.close()
    assert sess.sent == [("bar", "ENCAMP"), ("bar", "EXIT")]
    assert set(got) == {"asked", "before_clock", "after_clock",
                        "elapsed_minutes", "rest_completed", "events",
                        "position_before", "position_after"}


_LEAVE_STEPS = [["load", "temple-probe BRUTUS RAISE POOL", "save"],
                ["load", "temple-probe BRUTUS RAISE CONTROL", "save"]]


def _leave_argv(tmp_path, arg, *steps):
    staging = ("0:0x0C1=0x70,0:0x0C2=0x17,5:0x018=18" if arg.endswith("POOL")
               else "5:0x018=18,5:0x0C1=0x70,5:0x0C2=0x17")
    return ["--title", "pool", "--save", str(_fixture_disk(tmp_path)),
            "--disks", str(tmp_path), "--issue", "700",
            "--run", "temple-raise-save", "--max-seconds", "1500",
            "--stage-record", staging, "--steps", *steps,
            "--out", str(tmp_path / "out")]


@pytest.mark.parametrize("steps", _LEAVE_STEPS)
def test_temple_probe_main_accepts_a_save_after_a_pool_or_control_raise(
        tmp_path, monkeypatch, steps):
    observed = []
    monkeypatch.setattr(A, "temple_source_guard", lambda *a: A.TEMPLE_BRUTUS_SHA256)
    monkeypatch.setattr(A, "run", lambda args, got, out, source: observed.append(
        got) or 0)
    assert A.main(_leave_argv(tmp_path, steps[1], *steps)) == 0
    assert observed == [[A.Step("load"), A.Step("temple-probe", steps[1][13:]),
                         A.Step("save")]]


@pytest.mark.parametrize("steps", [
    ["load", "temple-probe BRUTUS", "save"],
    ["load", "temple-probe BRUTUS HEAL", "save"],
    ["load", "temple-probe BRUTUS RAISE", "save"],
    ["load", "temple-probe BRUTUS RAISE POOL", "peek 0", "save"],
    ["load", "temple-probe BRUTUS RAISE POOL", "save", "save"],
    ["load", "save", "temple-probe BRUTUS RAISE POOL"],
    ["load", "temple-probe BRUTUS RAISE CONTROL", "rest 1"],
])
def test_temple_probe_main_still_refuses_anything_else_after_the_probe(
        tmp_path, monkeypatch, steps):
    monkeypatch.setattr(A, "temple_source_guard", lambda path: A.TEMPLE_BRUTUS_SHA256)
    arg = "BRUTUS RAISE POOL" if "POOL" in " ".join(steps) else (
        "BRUTUS RAISE CONTROL")
    _refused_before_a_slot(tmp_path, monkeypatch, _leave_argv(
        tmp_path, arg, *steps)[:-2])


def _result_before_continued(run):
    tags = _raise_tags(run)
    assert "raise-result" in tags and (
        tags.index("raise-result") < tags.index("raise-continued"))


@pytest.mark.parametrize("who", ["BRUTUS RAISE POOL", "BRUTUS RAISE CONTROL"])
def test_temple_probe_leave_walks_the_list_and_the_bar_out_to_the_world(
        tmp_path, monkeypatch, who):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    session.press_line = True
    if who.endswith("CONTROL"):
        run.reading = _control_reading
    result = run.temple_probe(who, leave=True)
    tail = (["Right"] * 4 + ["SHARE"] + ["Right"] * 2 if who.endswith("POOL")
            else ["Right"] * 4)
    assert session.keys[-(13 + len(tail)):] == (
        ["YES", "Return"] + ["Down"] * 9 + ["Return"] + tail + ["EXIT"])
    assert session.keys[-1] == "EXIT" and session.phase == "world"
    assert _raise_tags(run)[-4:] == (
        ["raise-continued", "list-exit", "leave-share", "outside"]
        if who.endswith("POOL")
        else ["raise-result", "raise-continued", "list-exit", "outside"])
    _result_before_continued(run)
    assert result["leave"]["stem"] and result["outcome"] == "alive"


def test_temple_probe_leave_takes_the_temple_bar_when_return_shows_it(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    session.press_line, session.after_continue = True, "bar"
    run.temple_probe("BRUTUS RAISE POOL", leave=True)
    assert session.keys[-10:] == (["YES", "Return"] + ["Right"] * 4
                                  + ["SHARE"] + ["Right"] * 2 + ["EXIT"])
    assert _raise_tags(run)[-3:] == ["raise-continued", "leave-share",
                                     "outside"]
    _result_before_continued(run)


def test_temple_probe_without_leave_sends_nothing_after_the_result(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    session.press_line = True
    run.temple_probe("BRUTUS RAISE POOL")
    assert session.keys[-1] == "YES" and "EXIT" not in session.keys


def test_temple_probe_leave_stops_and_keeps_the_frame_on_an_unknown_screen(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    session.press_line, session.after_continue = True, "unknown"
    with pytest.raises(A.StepFailed, match="neither the service list"):
        run.temple_probe("BRUTUS RAISE POOL", leave=True)
    assert run.temple_checkpoints[-1]["tag"] == "lost-exit"
    assert session.keys[-1] == "Return" and "EXIT" not in session.keys


def test_temple_probe_leave_sends_no_key_without_the_continue_frame(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    with pytest.raises(A.StepFailed, match="no PRESS"):
        run.temple_probe("BRUTUS RAISE POOL", leave=True)
    assert session.keys[-1] == "YES"
    assert run.temple_checkpoints[-1]["tag"] == "lost-exit"


def test_temple_probe_leave_keeps_the_first_frame_under_continued(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    session.press_line = True
    result = run.temple_probe("BRUTUS RAISE POOL", leave=True)
    first = next(c for c in run.temple_checkpoints
                 if c["tag"] == "raise-continued")
    assert result["leave"]["continued"] == first["stem"]
    assert result["leave"]["continued"] != next(
        c for c in run.temple_checkpoints if c["tag"] == "list-exit")["stem"]


@pytest.mark.parametrize("text", ["BRUTUS FAILED", "NOT ENOUGH MONEY !",
                                  "SOMETHING UNSEEN"])
def test_temple_probe_leave_stops_when_the_raise_did_not_end_alive(
        tmp_path, monkeypatch, text):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    session.press_line, session.result_text = True, text
    with pytest.raises(A.StepFailed, match="not leaving"):
        run.temple_probe("BRUTUS RAISE POOL", leave=True)
    assert session.keys[-1] == "YES"
    assert run.temple_checkpoints[-1]["tag"] == "lost-exit"


def _leave_with_disk_prompt(tmp_path, monkeypatch, phase):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    session.press_line = True
    session.after_leaving = phase

    entry = session.handle_prompt

    def handle_prompt(screen):
        if "EXIT" not in session.keys:
            return entry(screen)
        session.keys.append("leave-side3")
        session.after_leaving = session.phase = "world"
        return True
    session.handle_prompt = handle_prompt
    return run, session


def test_temple_probe_leave_answers_one_side_3_prompt_before_the_world_bar(
        tmp_path, monkeypatch):
    run, session = _leave_with_disk_prompt(tmp_path, monkeypatch, "side3")
    result = run.temple_probe("BRUTUS RAISE POOL", leave=True)
    assert session.keys[-2:] == ["EXIT", "leave-side3"]
    assert _raise_tags(run)[-2:] == ["leave-side3-before-answer", "outside"]
    assert result["leave"]["stem"]


def test_temple_probe_leave_stops_on_another_disk_prompt_keeping_the_frame(
        tmp_path, monkeypatch):
    run, session = _leave_with_disk_prompt(tmp_path, monkeypatch, "side4")
    with pytest.raises(A.StepFailed, match="disk prompt"):
        run.temple_probe("BRUTUS RAISE POOL", leave=True)
    assert session.keys[-1] == "EXIT"
    assert run.temple_checkpoints[-1]["tag"] == "lost-exit"


def _leave_with_scripted_reads(tmp_path, monkeypatch, script):
    """After the side 3 answer, each screen read shows the next item of
    SCRIPT ("side3", "blank" or "world"); "world" stands once it is reached."""
    run, session = _leave_with_disk_prompt(tmp_path, monkeypatch, "side3")
    answered_at = {}
    original = session.handle_prompt

    def handle_prompt(screen):
        got = original(screen)
        if "EXIT" in session.keys:
            answered_at["yes"] = True
            session.phase = "world"
        return got
    session.handle_prompt = handle_prompt
    read = session.screen
    queue = list(script)

    def screen():
        if answered_at and queue:
            shown = queue.pop(0)
            if shown == "blank":
                return _TempleScreen([""] * 25)
            session.phase = shown
        return read()
    session.screen = screen
    return run, session


def test_temple_probe_leave_waits_out_a_side_3_prompt_that_lingers_after_the_answer(
        tmp_path, monkeypatch):
    run, session = _leave_with_scripted_reads(
        tmp_path, monkeypatch, ["side3", "side3", "world"])
    result = run.temple_probe("BRUTUS RAISE POOL", leave=True)
    assert session.keys.count("leave-side3") == 1
    assert _raise_tags(run)[-1] == "outside" and result["leave"]["stem"]


def test_temple_probe_leave_stops_on_a_side_3_prompt_that_returns_after_another_screen(
        tmp_path, monkeypatch):
    run, session = _leave_with_scripted_reads(
        tmp_path, monkeypatch, ["side3", "blank", "side3"])
    with pytest.raises(A.StepFailed, match="repeated disk prompt"):
        run.temple_probe("BRUTUS RAISE POOL", leave=True)
    assert session.keys.count("leave-side3") == 1
    assert run.temple_checkpoints[-1]["tag"] == "lost-exit"


def test_temple_probe_leave_timeout_names_the_bound_that_expired(
        tmp_path, monkeypatch):
    run, session = _leave_with_scripted_reads(tmp_path, monkeypatch, [])
    read = session.screen
    session.screen = lambda: (_TempleScreen([""] * 25)
                              if "EXIT" in session.keys else read())
    with pytest.raises(A.StepFailed, match="before the 90 second limit"):
        run.temple_probe("BRUTUS RAISE POOL", leave=True)


def test_temple_probe_leave_shares_the_pool_before_exit_and_reaches_outside(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    session.press_line = True
    result = run.temple_probe("BRUTUS RAISE POOL", leave=True)
    assert session.keys.index("SHARE") < session.keys.index("EXIT")
    assert session.keys.count("SHARE") == 1 and "GO BACK" not in session.keys
    assert _raise_tags(run)[-3:] == ["list-exit", "leave-share", "outside"]
    _result_before_continued(run)
    (share,) = result["leave"]["share"]
    assert share["stem"] and share["pool_before"]["words"][3] == 500
    assert share["pool_after"]["words"] == [0] * 5


def test_temple_probe_control_leave_never_chooses_share(tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    session.press_line = True
    run.reading = _control_reading
    result = run.temple_probe("BRUTUS RAISE CONTROL", leave=True)
    assert "SHARE" not in session.keys and "share" not in result["leave"]


def test_temple_probe_leave_answers_the_treasure_prompt_with_go_back_once(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    session.press_line, session.treasure_prompts = True, 1
    result = run.temple_probe("BRUTUS RAISE POOL", leave=True)
    assert session.keys[session.keys.index("EXIT"):] == (
        ["EXIT", "GO BACK"] + ["Right"] * 4 + ["SHARE"] + ["Right"] * 2
        + ["EXIT"])
    assert "LEAVE TREASURE" not in session.keys
    assert _raise_tags(run)[-4:] == ["leave-share", "leave-treasure",
                                     "leave-share", "outside"]
    assert result["leave"]["treasure"]
    first, second = result["leave"]["share"]
    assert first["pool_before"]["words"][3] == 500
    assert first["pool_after"]["words"] == [0] * 5
    assert second["pool_before"]["words"] == [0] * 5
    assert second["pool_after"]["words"] == [0] * 5
    assert first["stem"] != second["stem"]


def test_temple_probe_leave_stops_when_the_treasure_prompt_comes_back(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    session.press_line, session.treasure_prompts = True, 2
    with pytest.raises(A.StepFailed, match="again after GO BACK and SHARE"):
        run.temple_probe("BRUTUS RAISE POOL", leave=True)
    assert session.keys.count("GO BACK") == 1
    assert session.keys.count("EXIT") == 2
    assert run.temple_checkpoints[-1]["tag"] == "lost-exit"


def test_temple_probe_leave_stops_when_share_shows_a_prompt(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    session.press_line, session.after_share = True, "prompt"
    with pytest.raises(A.StepFailed, match="unexpected prompt after SHARE"):
        run.temple_probe("BRUTUS RAISE POOL", leave=True)
    assert "EXIT" not in session.keys
    assert run.temple_checkpoints[-1]["tag"] == "lost-exit"


def test_temple_probe_leave_share_timeout_names_the_bound_that_expired(
        tmp_path, monkeypatch):
    run, session, events = _temple_fake_run(tmp_path, monkeypatch)
    session.press_line, session.after_share = True, "unknown"
    with pytest.raises(A.StepFailed, match="before the 30 second limit"):
        run.temple_probe("BRUTUS RAISE POOL", leave=True)


# --- --stage-var -------------------------------------------------------------

def test_a_staged_variable_lands_at_its_address_in_savedgame0(tmp_path):
    src = _fixture_disk(tmp_path)
    plain = A.stage(src, tmp_path / "plain.d64", "pool-of-radiance")
    took = A.stage(src, tmp_path / "var.d64", "pool-of-radiance",
                   variables=[(0x4A07, 1)])
    was = _payload(tmp_path / "plain.d64")[0x107]
    assert took["variables"] == [{"address": 0x4A07, "offset": 0x107,
                                  "was": was, "now": 1}]
    assert plain["variables"] == []
    expect = bytearray(_payload(tmp_path / "plain.d64"))
    expect[0x107] = 1
    assert _payload(tmp_path / "var.d64") == bytes(expect)
    assert _roster(tmp_path / "var.d64") == _roster(tmp_path / "plain.d64")


@pytest.mark.parametrize("address", [0x6DD2, 0x6500, 0x48FF])
def test_a_staged_variable_outside_savedgame0_is_refused(tmp_path, address):
    with pytest.raises(ValueError, match="outside the save file"):
        A.stage(_fixture_disk(tmp_path), tmp_path / "s.d64", "pool-of-radiance",
                variables=[(address, 1)])


def test_a_staged_variable_at_the_last_byte_of_savedgame0_is_accepted(tmp_path):
    took = A.stage(_fixture_disk(tmp_path), tmp_path / "s.d64",
                   "pool-of-radiance", variables=[(0x64FF, 1)])
    assert took["variables"][0]["offset"] == 0x1BFF
    assert _payload(tmp_path / "s.d64")[0x1BFF] == 1


def test_a_stage_var_line_parses_hex_and_refuses_bad_lines(tmp_path, capsys):
    assert A.parse_vars(["4A07=01"]) == [(0x4A07, 1)]
    assert A.parse_vars(["4A07=1,4AC5=ff"]) == [(0x4A07, 1), (0x4AC5, 0xFF)]
    for bad in ("4A07=100", "4A07", "XYZ=1", "=1", "4A07="):
        with pytest.raises(ValueError):
            A.parse_vars([bad])
        with pytest.raises(SystemExit) as e:
            A.main(["--title", "pool", "--save", str(_fixture_disk(tmp_path)),
                    "--stage-var", bad, "--stage-only", "--steps", "load",
                    "--out", str(tmp_path / "evidence")])
        assert e.value.code == 2
    capsys.readouterr()


def test_stage_var_reaches_the_staged_disk_through_the_command_line(
        tmp_path, monkeypatch):
    monkeypatch.setattr(A.S, "claim_slot", lambda *a, **k: pytest.fail("claimed a slot"))
    out = tmp_path / "evidence"
    rc = A.main(["--title", "pool", "--save", str(_fixture_disk(tmp_path)),
                 "--stage-var", "4A07=1", "--stage-only", "--steps", "load",
                 "--out", str(out)])
    assert rc == 0
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["staged"]["variables"][0]["offset"] == 0x107
    assert _payload(out / "staged.D64")[0x107] == 1


# --- remove: the party menu's REMOVE CHARACTER FROM PARTY ----------------------
#
# The screens are composed from the Pool of Radiance captures kept under
# `cited/258/run3` (the list is the panel with `EXIT` under it, `REMOVE
# CHARACTER ?` on row 24, a blank row 24 while the member is written out) and
# `cited/439/readd1` (`MAKE SAVE GAME DISK ? YES NO` when the write is refused).

_PANEL = ["BRUTUS                           9 11", "MAGNUS                           9 9",
          "SILAS                           10 9", "ROLAND                          10 7",
          "LADY KATHERINE                   8 5", "MALCYON                          8 4"]
_HEAD = "NAME                            AC HP"
_MENU_ROWS = (" CREATE NEW CHARACTER", " VIEW CHARACTER", " ADD CHARACTER TO PARTY",
              " REMOVE CHARACTER FROM PARTY", " SAVE CURRENT GAME",
              " BEGIN ADVENTURING")


def _party_menu(panel):
    lines = {2: _HEAD, **{4 + i: name for i, name in enumerate(panel)}}
    lines.update({13 + i: row for i, row in enumerate(_MENU_ROWS)})
    return _window(lines)


def _remove_screen(panel, bar="REMOVE CHARACTER ?"):
    lines = {2: _HEAD, **{4 + i: name for i, name in enumerate(panel)}}
    lines[4 + len(panel)] = "EXIT"
    return _window(lines, bar)


class _RemoveSession(FakeSession):
    """`FakeSession` whose AUTO states give way to the next on their own after
    one read, as the game's list does once the drive has finished, writing
    WRITES' file to the save disk as it does."""

    def __init__(self, screens, moves, start, disk, auto=(), writes=()):
        super().__init__(screens, moves, start)
        self.save_disk = str(disk)
        self.auto, self.writes = dict(auto), dict(writes)

    def screen(self):
        shown = FakeScreen(self.screens[self.state])
        if self.state in self.auto:
            self.state = self.auto[self.state]
            if self.state in self.writes:
                image = D64.open(self.save_disk)
                image.write_file(self.writes[self.state], b"\x00\x6b" + bytes(580))
                image.save(self.save_disk)
        return shown


def _remove_run(tmp_path, monkeypatch, sess):
    monkeypatch.setattr(A.time, "sleep", lambda s: None)
    run, log = _pool_run(tmp_path, sess)
    run.drive_error = lambda: {"text": "00, OK,00,00"}
    run.at_menu = True
    run.directory = A.disk_directory(pathlib.Path(sess.save_disk))
    return run, log


def test_the_remove_step_parses_after_load_or_another_remove():
    steps = A.parse_steps(["load", "remove 3", "remove J,R",
                           "remove LADY KATHERINE", "view 1"])
    assert [(s.verb, s.arg) for s in steps][1:4] == [
        ("remove", "3"), ("remove", "J,R"), ("remove", "LADY KATHERINE")]


@pytest.mark.parametrize("steps", [
    ["load", "remove"],                   # whom?
    ["load", "remove 0"],                 # panel numbers count from 1
    ["load", "remove 9"],                 # and stop at eight
    ["load", "view 1", "remove 2"],       # the party menu is behind the world
])
def test_a_remove_the_party_menu_cannot_take_is_refused(steps):
    with pytest.raises(ValueError):
        A.parse_steps(steps)


def test_the_remove_list_is_read_under_the_heading_down_to_exit():
    assert A.remove_list(_remove_screen(_PANEL)) == _PANEL
    assert A.remove_list(_remove_screen(_PANEL[:2], A.REMOVE_ROW)) == _PANEL[:2]
    assert A.listed_name(_PANEL[4]) == "LADY KATHERINE"
    # The menu offers the same words; the drive writing leaves row 24 blank.
    assert A.remove_list(_party_menu(_PANEL)) is None
    assert A.remove_list(_remove_screen(_PANEL, "")) is None


def test_remove_picks_the_numbered_row_waits_for_the_write_and_keeps_the_disk(
        tmp_path, monkeypatch):
    disk = _fixture_disk(tmp_path)
    left = _PANEL[:2] + _PANEL[3:]
    screens = {"menu": _party_menu(_PANEL), "list": _remove_screen(_PANEL),
               "writing": _remove_screen(_PANEL, ""), "shorter": _remove_screen(left),
               "back": _party_menu(left)}
    moves = {("menu", ("row", A.REMOVE_ROW)): "list",
             ("list", ("row", _PANEL[2])): "writing",
             ("shorter", ("row", "EXIT")): "back"}
    sess = _RemoveSession(screens, moves, "menu", disk, auto={"writing": "shorter"},
                          writes={"shorter": b"\x01SILAS"})
    run, log = _remove_run(tmp_path, monkeypatch, sess)
    got = run.remove("3")
    log.close()
    assert sess.sent == [("row", A.REMOVE_ROW), ("row", _PANEL[2]), ("row", "EXIT")]
    assert got["row"] == _PANEL[2] and got["left"] == left
    assert got["refused"] is None
    assert got["added"] == ["\\x01SILAS"] and got["gone"] == []
    assert got["closed"] and not got["reattached"]
    assert pathlib.Path(got["kept"]).name == "removed-1.D64"
    assert D64.open(got["kept"]).find(b"\x01SILAS") is not None
    assert got["drive_error"] == {"text": "00, OK,00,00"}
    assert run.at_menu and sess.state == "back"


def test_remove_finds_a_member_by_the_whole_name_the_row_draws(tmp_path, monkeypatch):
    disk = _fixture_disk(tmp_path)
    left = _PANEL[:4] + _PANEL[5:]
    screens = {"menu": _party_menu(_PANEL), "list": _remove_screen(_PANEL),
               "shorter": _remove_screen(left), "back": _party_menu(left)}
    moves = {("menu", ("row", A.REMOVE_ROW)): "list",
             ("list", ("row", _PANEL[4])): "shorter",
             ("shorter", ("row", "EXIT")): "back",
             ("back", ("row", A.REMOVE_ROW)): "shorter"}
    sess = _RemoveSession(screens, moves, "menu", disk)
    run, log = _remove_run(tmp_path, monkeypatch, sess)
    assert run.remove("LADY KATHERINE")["row"] == _PANEL[4]
    with pytest.raises(A.StepFailed):
        run.remove("LADY")              # not a whole name
    log.close()


def test_a_refused_write_is_answered_no_and_kept(tmp_path, monkeypatch):
    disk = _fixture_disk(tmp_path)
    asked = A.MAKE_SAVE_DISK + " ? YES NO"
    screens = {"menu": _party_menu(_PANEL), "list": _remove_screen(_PANEL),
               "asked": _remove_screen(_PANEL, asked), "back": _party_menu(_PANEL)}
    moves = {("menu", ("row", A.REMOVE_ROW)): "list",
             ("list", ("row", _PANEL[0])): "asked",
             ("asked", ("bar", "NO")): "list",
             ("list", ("row", "EXIT")): "back"}
    sess = _RemoveSession(screens, moves, "menu", disk)
    run, log = _remove_run(tmp_path, monkeypatch, sess)
    with pytest.raises(A.StepFailed, match="refused the write"):
        run.remove("1")
    log.close()
    assert ("bar", "YES") not in sess.sent
    assert sess.sent[2:] == [("bar", "NO"), ("row", "EXIT")]
    kept = [json.loads(line) for line in (tmp_path / "run.jsonl").read_text(
        encoding="utf-8").splitlines()]
    got = next(e for e in kept if e["kind"] == "remove-not-taken")
    assert got["refused"] == asked and got["left"] == _PANEL
    assert got["added"] == got["gone"] == got["changed"] == []
    assert (tmp_path / "removed-1.D64").is_file()


def test_the_disk_copy_tries_no_longer_than_the_run_has_left(tmp_path, monkeypatch):
    sess = _RemoveSession({"w": _window({})}, {}, "w", _fixture_disk(tmp_path))
    run, log = _remove_run(tmp_path, monkeypatch, sess)
    run.deadline, run.clock = 4.5, lambda: 0.0
    tries = []

    def copy(src, dest, *, attempts, backoff):
        tries.append(attempts)
        raise RuntimeError("open directory entry 'SAVEAZURE'")

    monkeypatch.setattr(A.S, "copy_closed_disk", copy)
    got = run.keep_save_disk("removed-1.D64")
    log.close()
    assert tries == [4, 4] and not got["closed"]


def test_the_drive_message_is_cut_where_the_stale_tail_of_an_older_one_begins():
    # The buffer a Curse remove left: `00, OK` over the end of `FILES SCRATCHED`.
    raw = b"00, OK,00,00RATCHED,00,000" + bytes(11) + b"w\x00\x02"
    assert A.drive_message(raw) == "00, OK,00,00"
    assert A.drive_message(b"26,WRITE PROTECT ON,18,00\r") == "26,WRITE PROTECT ON,18,00"
    assert A.drive_message(bytes(4)) == "...."


def test_a_disk_still_open_after_a_menu_write_is_attached_again_before_the_copy(
        tmp_path, monkeypatch):
    sess = _RemoveSession({"w": _window({})}, {}, "w", _fixture_disk(tmp_path))
    run, log = _remove_run(tmp_path, monkeypatch, sess)
    tries = []

    def copy(src, dest, **kw):
        tries.append(len(sess.attaches))
        if not sess.attaches:
            raise RuntimeError("open directory entry 'SAVEAZURE'")
        pathlib.Path(dest).write_bytes(pathlib.Path(src).read_bytes())

    monkeypatch.setattr(A.S, "copy_closed_disk", copy)
    got = run.keep_save_disk("removed-1.D64")
    log.close()
    assert tries == [0, 1] and sess.attaches == [sess.save_disk]
    assert got["reattached"] and got["closed"]


def test_a_load_followed_by_remove_stops_on_the_party_menu_until_another_step(
        tmp_path, monkeypatch):
    calls = []

    class Menu(_Pool):
        at_menu = False

        def load(self):
            calls.append("load")
            return {}

        def load_party(self):
            calls.append("load_party")
            self.at_menu = True
            return {"at": "party menu"}

        def remove(self, who):
            calls.append(f"remove {who}")
            return {"who": who}

        def enter_world(self):
            calls.append("enter_world")
            self.at_menu = False
            return {"position": [1, 2, 3]}

        def view(self, who):
            calls.append(f"view {who}")
            return {}

    rc, _, out = _drive(tmp_path, monkeypatch,
                        ["load", "remove 2", "remove 1", "view 1"], pool=Menu)
    assert rc == 0
    assert calls == ["load_party", "remove 2", "remove 1", "enter_world", "view 1"]
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["results"][-1]["entered_world"] == {"position": [1, 2, 3]}
    calls.clear()
    (tmp_path / "plain").mkdir()
    _drive(tmp_path / "plain", monkeypatch, ["load", "view 1"], pool=Menu)
    assert calls == ["load", "view 1"]


class _LoadSession:
    """Records the front-end calls a load makes, in order."""

    def __init__(self):
        self.calls = []
        self.save_disk = "/nonexistent/SIDE0.D64"
        self.game = None

    def boot(self):
        self.calls.append("boot")
        return True

    def load_save(self):
        self.calls.append("load_save")
        return True

    def begin_adventuring(self):
        self.calls.append("begin_adventuring")
        return True

    def patch_disk_prompt(self):
        self.calls.append("patch_disk_prompt")
        return True

    def settle(self, seconds=0):
        pass

    def mon(self, timeout=0):
        import contextlib

        return contextlib.nullcontext(SimpleNamespace(
            checkpoint_set=lambda *a, **k: 1, resume=lambda: None))


def _load_run(cls, monkeypatch, sess):
    reads = []
    monkeypatch.setattr(A, "disk_directory", lambda path: reads.append(path) or [])
    run = cls.__new__(cls)
    run.sess, run.points, run.armed = sess, {}, {}
    run.game, run.disks, run.attack_by, run.attack_owner = None, None, "", None
    run.log = SimpleNamespace(emit=lambda *a, **k: None)
    run.captures = []
    run.capture = lambda tag, rows=None: run.captures.append(tag)
    run.position = lambda: [1, 2, 3]
    run.bar = lambda: "ENCAMP"
    return run, reads


def _later_front_ends(monkeypatch, sess):
    from tools.curse_of_the_azure_bonds import curseload
    from tools.secret_of_the_silver_blades import ssbsession

    def note(name, result=True):
        return lambda *a, **k: sess.calls.append(name) or result

    monkeypatch.setattr(curseload, "load_saved_game", note("load_save", "loaded"))
    monkeypatch.setattr(curseload, "Addresses", lambda *a, **k: None)
    monkeypatch.setattr(curseload, "enter_world", note("begin_adventuring"))
    monkeypatch.setattr(curseload, "clear_messages", lambda *a, **k: "")
    monkeypatch.setattr(ssbsession, "load_party", note("load_save"))
    monkeypatch.setattr(ssbsession, "Addresses", lambda *a, **k: None)
    monkeypatch.setattr(ssbsession, "enter_world", note("begin_adventuring"))
    monkeypatch.setattr(ssbsession, "clear_messages", lambda *a, **k: "")


@pytest.mark.parametrize("cls", [A.PoolRun, A.CurseRun, A.SilverRun])
def test_a_plain_load_boots_loads_and_enters_the_world_reading_no_directory(
        monkeypatch, cls):
    sess = _LoadSession()
    _later_front_ends(monkeypatch, sess)
    run, reads = _load_run(cls, monkeypatch, sess)
    got = run.load()
    front = [c for c in sess.calls if c != "patch_disk_prompt"]
    assert front == ["boot", "load_save", "begin_adventuring"]
    assert run.at_menu is False and got["position"] == [1, 2, 3]
    assert reads == [] and run.captures == ["world"]


@pytest.mark.parametrize("cls", [A.PoolRun, A.CurseRun, A.SilverRun])
def test_load_party_stops_on_the_menu_and_enter_world_leaves_it(monkeypatch, cls):
    sess = _LoadSession()
    _later_front_ends(monkeypatch, sess)
    run, reads = _load_run(cls, monkeypatch, sess)
    assert run.load_party()["at"] == "party menu"
    assert run.at_menu is True and "begin_adventuring" not in sess.calls
    assert reads == [pathlib.Path(sess.save_disk)] and run.captures == ["party-menu"]
    run.enter_world()
    assert run.at_menu is False and sess.calls.count("begin_adventuring") == 1


def test_a_run_with_removes_enters_the_world_once(tmp_path, monkeypatch):
    calls = []

    class Menu(_Pool):
        at_menu = False

        def load_party(self):
            calls.append("load_party")
            self.at_menu = True
            return {}

        def remove(self, who):
            calls.append("remove")
            return {}

        def enter_world(self):
            calls.append("enter_world")
            self.at_menu = False
            return {}

        def view(self, who):
            calls.append("view")
            return {}

        def save(self, staged):
            calls.append("save")
            return {}

    rc, _, _ = _drive(tmp_path, monkeypatch,
                      ["load", "remove 1", "view 1", "view 2", "save"], pool=Menu)
    assert rc == 0 and calls.count("enter_world") == 1
    assert calls == ["load_party", "remove", "enter_world", "view", "view", "save"]


@pytest.mark.parametrize("probe", [["--checkpoint", "408F"],
                                   ["--read-at", "09DD=CD:2B78:2"]])
def test_a_probe_armed_in_the_world_is_refused_when_the_run_ends_on_the_party_menu(
        tmp_path, monkeypatch, probe):
    _refused_before_a_slot(tmp_path, monkeypatch, [
        "--title", "pool", "--save", str(_fixture_disk(tmp_path)),
        "--disks", str(tmp_path), *probe, "--steps", "load", "remove 2", "remove 1"])


def test_a_probe_is_accepted_when_a_step_after_the_removes_enters_the_world(
        tmp_path, monkeypatch):
    monkeypatch.setattr(A.S, "claim_slot", lambda *a, **k: pytest.fail("claimed a slot"))
    rc = A.main(["--title", "pool", "--save", str(_fixture_disk(tmp_path)),
                 "--disks", str(tmp_path), "--checkpoint", "408F", "--stage-only",
                 "--steps", "load", "remove 2", "view 1",
                 "--out", str(tmp_path / "evidence")])
    assert rc == 0


def test_no_reading_is_taken_on_the_party_menu_and_the_world_step_takes_one(
        tmp_path, monkeypatch):
    readings = []

    class Menu(_Pool):
        at_menu = False

        def load_party(self):
            self.at_menu = True
            return {}

        def remove(self, who):
            return {}

        def enter_world(self):
            self.at_menu = False
            return {}

        def view(self, who):
            return {}

        def reading(self):
            assert not self.at_menu, "a reading was taken on the party menu"
            readings.append(True)
            return {"clock": [0] * 6}

    rc, _, out = _drive(tmp_path, monkeypatch, ["load", "remove 2", "view 1"],
                        pool=Menu)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert rc == 0, summary.get("lost")
    assert ["after" in r for r in summary["results"]] == [False, False, True]
    assert summary["results"][-1]["after"] == {"clock": [0] * 6}
    assert readings == [True]


class _JISession(_TempleSession):
    """WISHFTR's disk: two moves, `J` then `I`, from the square before the
    temple, crossing no area. `side3` makes the last move draw a side-3
    prompt, which nothing on this route approves."""

    def __init__(self, out, *, side3=False, **kwargs):
        super().__init__(out, **kwargs)
        self.place = (0, 1, 4, 1)
        self.side3 = side3

    def move_key(self, move):
        self.moves.append(move)
        assert move == "JI"[len(self.moves) - 1]
        self.window_text = ""
        if len(self.moves) == 1:
            self.place = (0, 1, 4, 0)
            return
        self.place = (0, 1, 3, 0)
        if self.side3:
            self.phase = "side3"
        else:
            self.typing = ["A PR", "A PRIESTESS GREETS YOU."]
            self.phase = "question"


def _ji_run(tmp_path, monkeypatch, *, side3=False):
    run, _, events = _temple_fake_run(tmp_path, monkeypatch)
    session = _JISession(tmp_path, side3=side3)
    run.sess = session
    reading = _temple_reading()
    reading["party"][0]["name"] = "WISHFTR"
    run.reading = lambda: reading
    return run, session, events


def test_temple_probe_wishftr_runs_two_moves_and_meets_no_side3_prompt(
        tmp_path, monkeypatch):
    run, session, _ = _ji_run(tmp_path, monkeypatch)
    result = run.temple_probe("WISHFTR")
    assert session.moves == list("JI")
    assert result["route"] == "JI"
    assert result["movement_keys"] == 2
    assert result["side3_prompts"] == 0
    assert result["questions"] == 1
    assert session.keys == ["YES"]
    assert run.temple_checkpoints[-1]["tag"] == "temple-arrival"


def test_temple_probe_side3_prompt_on_a_route_with_no_crossing_stops(
        tmp_path, monkeypatch):
    run, session, _ = _ji_run(tmp_path, monkeypatch, side3=True)
    with pytest.raises(A.StepFailed, match="unexpected or repeated disk"):
        run.temple_probe("WISHFTR")
    assert "side3" not in session.keys


def test_temple_probe_refuses_a_member_the_source_does_not_hold(
        tmp_path, monkeypatch):
    run, _, _ = _ji_run(tmp_path, monkeypatch)
    run.reading = _temple_reading  # BRUTUS is in the party, WISHFTR is not
    with pytest.raises(A.StepFailed, match="loaded WISHFTR"):
        run.temple_probe("WISHFTR")


def test_temple_source_table_lists_each_route_and_its_crossing():
    brutus = A.TEMPLE_SOURCES[A.TEMPLE_BRUTUS_SHA256]
    wishftr = A.TEMPLE_SOURCES[A.TEMPLE_WISHFTR_SHA256]
    assert brutus.route == A.TEMPLE_ROUTE
    assert (brutus.crossing_index, brutus.last_index) == (2, 5)
    assert wishftr.route == A.TEMPLE_ROUTE[4:]
    assert (wishftr.crossing_index, wishftr.last_index) == (None, 1)
    assert (wishftr.name, wishftr.slot, wishftr.row) == (
        "WISHFTR", 5, (63, 32, 5, 0, 5))
    assert A.TEMPLE_STAGING["WISHFTR RAISE POOL"] == A.TEMPLE_POOL_STAGING
    assert "WISHFTR RAISE POOL" in A.TEMPLE_SAVE_ARGS
    assert A.parse_steps(["load", "temple-probe WISHFTR RAISE POOL"])[1] == (
        A.Step("temple-probe", "WISHFTR RAISE POOL"))


def test_temple_route_with_two_crossings_is_refused():
    two = (("I", (1, 0, 0, 0), (2, 0, 0, 0)), ("I", (2, 0, 0, 0), (3, 0, 0, 0)))
    with pytest.raises(ValueError, match="at most one"):
        A.temple_crossing_index(two)
    assert A.temple_crossing_index(two[:1]) == 0


def test_temple_source_guard_accepts_each_table_hash_and_refuses_others(
        tmp_path, monkeypatch):
    source = _fixture_disk(tmp_path)
    digest = A.specimens.sha256_file(source)
    entry = {"platform": "c64", "title": "Pool of Radiance",
             "_files": [source], "sha256": {source.name: digest}}
    monkeypatch.setattr(A.specimens, "list_specimens", lambda: [entry])
    with pytest.raises(ValueError, match="SHA-256"):
        A.temple_source_guard(source)
    monkeypatch.setattr(A, "TEMPLE_SOURCES", {
        digest: A.TEMPLE_SOURCES[A.TEMPLE_WISHFTR_SHA256]})
    assert A.temple_source_guard(source) == digest
    assert A._guard_temple_source(
        source, [A.Step("load"), A.Step("temple-probe", "WISHFTR")]) == digest
    with pytest.raises(ValueError, match="holds WISHFTR, not BRUTUS"):
        A._guard_temple_source(
            source, [A.Step("load"), A.Step("temple-probe", "BRUTUS")])


def test_temple_probe_wishftr_argument_refused_before_a_slot_is_claimed(
        tmp_path, monkeypatch):
    """The disk is BRUTUS's, so a step naming WISHFTR stops at the guard."""
    monkeypatch.setattr(A, "temple_source_guard",
                        lambda path: A.TEMPLE_BRUTUS_SHA256)
    _refused_before_a_slot(tmp_path, monkeypatch, _raise_argv(
        tmp_path, "--stage-record", "0:0x0C1=0x70,0:0x0C2=0x17,5:0x018=18",
        step="temple-probe WISHFTR RAISE POOL")[:-2])


def test_temple_probe_on_an_unknown_hash_is_refused_before_a_slot_is_claimed(
        tmp_path, monkeypatch):
    _refused_before_a_slot(tmp_path, monkeypatch, _raise_argv(
        tmp_path, "--stage-record", "0:0x0C1=0x70,0:0x0C2=0x17,5:0x018=18",
        step="temple-probe WISHFTR RAISE POOL")[:-2])


def test_temple_probe_usage_error_lists_every_mode_and_its_staging(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(A, "temple_source_guard",
                        lambda path: A.TEMPLE_BRUTUS_SHA256)
    with pytest.raises(SystemExit):
        A.main(_raise_argv(tmp_path)[:-2] + ["--out", str(tmp_path / "out")])
    err = capsys.readouterr().err
    assert "WISHFTR RAISE POOL takes 0:0x0c1=0x70" in err.replace("0x0C1", "0x0c1")
    assert "BRUTUS RAISE CONTROL takes" in err


def test_a_view_waits_for_punctuation_the_c64_draws_as_other_characters(
        tmp_path, monkeypatch):
    run, sess = _sheet_run(tmp_path, "A;B<C=D>E      STATUS OK", monkeypatch)
    sess.moves[("camp", ("party", 0))] = "camp"
    run.panel = ["A{B|C}D~E", "PAINE"]
    try:
        got = run.view("1")
    finally:
        run.log.close()
    assert got["who"] == "1"


def test_a_backslash_is_drawn_as_a_pound_sign_and_a_backquote_blank():
    from tools.c64 import screens

    assert screens.as_drawn("A\\B`C") == "A£B C"


def _disks_given_to(monkeypatch, tmp_path, argv):
    seen = {}
    monkeypatch.setattr(A.S, "claim_slot", lambda *a, **k: (_ for _ in ()).throw(
        SystemExit("stop")))
    monkeypatch.setattr(A, "tool_disks", lambda: "POOL-SEARCH")
    monkeypatch.setattr(A.gamedisks, "find",
                        lambda name: seen.setdefault("find", name) and "REGISTRY")
    real_parse = A.argparse.ArgumentParser.parse_args

    def capture(self, *a, **k):
        ns = real_parse(self, *a, **k)
        seen["ns"] = ns
        return ns
    monkeypatch.setattr(A.argparse.ArgumentParser, "parse_args", capture)
    try:
        A.main(argv + ["--out", str(tmp_path / "out")])
    except SystemExit:
        pass
    return seen


def test_a_curse_run_without_disks_takes_them_from_the_registry(
        tmp_path, monkeypatch):
    seen = _disks_given_to(monkeypatch, tmp_path, [
        "--title", "curse", "--save", str(_fixture_disk(tmp_path)),
        "--steps", "load"])
    assert seen["find"] == "curse-of-the-azure-bonds"
    assert seen["ns"].disks == "REGISTRY"


def test_a_pool_run_without_disks_keeps_its_own_search(tmp_path, monkeypatch):
    seen = _disks_given_to(monkeypatch, tmp_path, [
        "--title", "pool", "--save", str(_fixture_disk(tmp_path)),
        "--steps", "load"])
    assert "find" not in seen and seen["ns"].disks == "POOL-SEARCH"


def test_the_registry_holds_the_curse_disks_the_driver_would_look_up():
    disks = A.gamedisks.find(A.TITLES["curse"])
    if disks is None:
        pytest.skip("no Curse of the Azure Bonds disks in the registry")
    assert disks.is_dir()


def test_the_no_disks_refusal_names_the_variable_of_the_title(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(A, "tool_disks", lambda: None)
    monkeypatch.setattr(A.gamedisks, "find", lambda name: None)
    monkeypatch.setattr(A.gamedisks, "entry", lambda name: {"env": "CURSE_DISKS"})
    for title, wanted in (("pool", "$POR_DISKS"), ("curse", "$CURSE_DISKS")):
        _refused_before_a_slot(tmp_path, monkeypatch, [
            "--title", title, "--save", str(_fixture_disk(tmp_path)),
            "--steps", "load", "camp-list"])
        err = capsys.readouterr().err
        assert f"set {wanted} or pass --disks" in err
    monkeypatch.setattr(A.gamedisks, "entry", lambda name: {})
    _refused_before_a_slot(tmp_path, monkeypatch, [
        "--title", "ssb", "--save", str(_fixture_disk(tmp_path)),
        "--steps", "load", "camp-list"])
    assert "found; pass --disks" in capsys.readouterr().err


# --- scribe (#745) ----------------------------------------------------------------
# The Silver Blades screens `MAGIC > SCRIBE` put up, as captured in the
# measuring boot (`~/.cache/wish/745-c64scribe/measure1`, 09- to 14-).
SSB_CAMP = "SAVE VIEW MAGIC REST ALTER FIX EXIT"
_SCROLL = {2: "MORGAINE'S SCROLL SPELLS", 4: "1ST LEVEL",
           5: "  PROTECTION FROM GOOD", 7: "6TH LEVEL", 8: "  DISINTEGRATE",
           9: "  STONE TO FLESH"}
SCRIBE_SCREENS = {
    "camp": _window({}, SSB_CAMP), "magic": _window({}, MAGIC),
    "list": _window(_SCROLL, "SCRIBE EXIT"),
    "pick": _window({**_SCROLL, 10: "  EXIT"}, A.PICK_SCRIBE),
    "picked": _window({**_SCROLL, 10: "  EXIT"}, A.PICK_SCRIBE),
    "refused": _window({**_SCROLL, 10: "  EXIT", 18: "MORGAINE CAN'T SCRIBE",
                        19: "STONE TO FLESH"}, A.PICK_SCRIBE),
    "listexit": _window({**_SCROLL, 10: "  EXIT"}, "SCRIBE EXIT"),
    "chosen": _window({2: "MORGAINE'S CHOSEN SPELLS", 7: "6TH LEVEL",
                       8: "  DISINTEGRATE"}, "EXIT"),
    "confirm": _window({2: "MORGAINE'S CHOSEN SPELLS", 7: "6TH LEVEL",
                        8: "  DISINTEGRATE", 18: "ARE YOU SURE ABOUT",
                        19: "YOUR CHOICE OF SPELLS?"}, "CONFIRM: OKAY  CANCEL"),
    "magic2": _window({}, MAGIC), "camp2": _window({}, SSB_CAMP),
}
SCRIBE_MOVES = {
    ("camp", ("party", 5)): "camp", ("camp", ("bar", "MAGIC")): "magic",
    ("magic", ("bar", "SCRIBE")): "list", ("list", ("bar", "SCRIBE")): "pick",
    ("pick", ("key", "Return")): "picked",
    ("picked", ("key", "Return")): "listexit",
    ("listexit", ("bar", "EXIT")): "chosen", ("chosen", ("bar", "EXIT")): "confirm",
    ("confirm", ("bar", "OKAY")): "magic2", ("magic2", ("bar", "EXIT")): "camp2",
}
#: The queue count `$7D02` in each state: the pick raises it to 1.
SCRIBED = {"picked", "listexit", "chosen", "confirm", "magic2", "camp2"}


class _ColourScreen(FakeScreen):
    """A screen whose list highlight is white at column 3 of row HOT, the
    other cells green, and column 1 white on every row, as the pick prompt
    after a refusal draws the `EXIT` row."""

    def __init__(self, rows, hot):
        super().__init__(rows)
        self.colours = bytearray([5] * 1000)
        for r in range(25):
            self.colours[r * 40 + 1] = 1
        if hot is not None:
            self.colours[hot * 40 + 3] = 1


class _ScribeMon:
    def __init__(self, sess):
        self.sess = sess

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, addr, n):
        return self.sess.memory(addr, n)

    def resume(self):
        pass


class _ScribeFake(_CurseFake):
    """The scribe screens moved by keys; Down and Up move the highlight over
    the list's entry rows on the pick prompt, and a Return there is asserted
    to land on the row the move table expects."""

    def __init__(self, moves=None, start="camp", scribed=SCRIBED, name=b"MORGAINE"):
        super().__init__(SCRIBE_SCREENS, {**SCRIBE_MOVES, **(moves or {})}, start)
        self.hot = 5
        self.scribed = scribed
        self.name = name
        self.picked_on = None

    def _entries(self):
        rows = self.screens[self.state]
        return [r for r in range(3, 23)
                if rows[r][1:39].startswith("  ") and rows[r][1:39].strip()]

    def _go(self, what):
        if self.state in ("pick", "picked") and what in (("key", "Down"), ("key", "Up")):
            self.sent.append(what)
            rows = self._entries()
            at = rows.index(self.hot) + (1 if what[1] == "Down" else -1)
            self.hot = rows[max(0, min(at, len(rows) - 1))]
            return True
        if self.state == "pick" and what == ("key", "Return"):
            self.picked_on = self.hot
        if self.state == "picked" and what == ("key", "Return"):
            assert self.hot == 10, "EXIT was chosen off the EXIT row"
        return super()._go(what)

    def screen(self):
        hot = self.hot if self.state in ("pick", "picked", "refused") else None
        return _ColourScreen(self.screens[self.state], hot)

    def mon(self, timeout=0):
        return _ScribeMon(self)

    def steady_triple(self):
        return (3, 4, 2)

    def memory(self, addr, n):
        mem = {0x7C00: self.name.ljust(15, b"\0"),
               0x7D00: bytes([1, 0, 1 if self.state in self.scribed else 0]),
               0xA945: bytes([0x10])}
        return mem[addr][:n]


def _scribe_run(tmp_path, sess):
    from goldbox import c64_port

    run = A.SilverRun.__new__(A.SilverRun)
    run.sess, run.out, run.log, run.shots = sess, tmp_path, A.Log(tmp_path), 0
    run.game = c64_port.by_key("secret-of-the-silver-blades")
    run.panel_index = lambda who: {"MORGAINE": 5}[who]
    return run


@pytest.mark.parametrize("step", ["scribe MORGAINE>PROTECTION FROM GOOD",
                                  "scribe 6>stone to flesh"])
def test_scribe_step_parses_who_and_the_spell(step):
    steps = A.parse_steps(["load", step, "rest 8h", "save"])
    who, spell = A.parse_scribe(steps[1].arg)
    assert steps[1].verb == "scribe"
    assert spell == spell.upper() and ">" not in who + spell


@pytest.mark.parametrize("step", ["scribe MORGAINE", "scribe", "scribe >FOO",
                                  "scribe MORGAINE>"])
def test_scribe_step_without_who_and_spell_is_refused(step):
    with pytest.raises(ValueError):
        A.parse_steps(["load", step])


def test_scribe_list_reads_the_spells_under_their_levels_without_the_exit_row():
    assert A.scribe_list(SCRIBE_SCREENS["pick"]) == [
        {"level": "1ST LEVEL", "spell": "PROTECTION FROM GOOD"},
        {"level": "6TH LEVEL", "spell": "DISINTEGRATE"},
        {"level": "6TH LEVEL", "spell": "STONE TO FLESH"}]


def test_scribe_highlight_reads_the_list_column_even_when_column_one_is_white():
    rows = SCRIBE_SCREENS["pick"]
    assert A.scribe_highlight(_ColourScreen(rows, 10), rows) == 10
    assert A.scribe_row(rows, "EXIT") == 10
    assert A.scribe_highlight(_ColourScreen(rows, None), rows) is None


def test_scribe_walks_to_the_spell_picks_it_confirms_and_ends_on_the_camp_bar(tmp_path):
    sess = _ScribeFake()
    run = _scribe_run(tmp_path, sess)
    try:
        got = run.scribe("MORGAINE>DISINTEGRATE")
    finally:
        run.log.close()
    assert sess.picked_on == 8 and sess.state == "camp2"
    assert sess.sent == [("party", 5), ("bar", "MAGIC"), ("bar", "SCRIBE"),
                         ("bar", "SCRIBE"), ("key", "Down"), ("key", "Return"),
                         ("key", "Down"), ("key", "Down"), ("key", "Return"),
                         ("bar", "EXIT"), ("bar", "EXIT"), ("bar", "OKAY"),
                         ("bar", "EXIT")]
    assert [s["spell"] for s in got["list"]] == [
        "PROTECTION FROM GOOD", "DISINTEGRATE", "STONE TO FLESH"]
    assert got["chosen"] == ["DISINTEGRATE"] and got["key"] == "xtest-return"
    assert (got["queue_before"], got["queue_after_pick"], got["queue_after"]) == (
        [0, 0], [0, 1], [0, 1])
    assert got["queue_entries"] == [0x10] and got["record_name"] == "MORGAINE"
    assert run.scribing and run.scribe_square == [3, 4, 2]


def test_scribe_tries_the_kernal_return_when_the_first_key_left_the_count(
        tmp_path, monkeypatch):
    monkeypatch.setattr(A, "SCRIBE_PICK_SECONDS", 0.5)
    sess = _ScribeFake({("pick", ("key", "Return")): "pick",
                        ("pick", ("key", 0x0D)): "picked"})
    run = _scribe_run(tmp_path, sess)
    try:
        got = run.scribe("MORGAINE>PROTECTION FROM GOOD")
    finally:
        run.log.close()
    assert got["key"] == "kernal-return"
    assert sess.sent[4:6] == [("key", "Return"), ("key", 0x0D)]


def test_scribe_fails_when_no_key_raises_the_queue_count(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "SCRIBE_PICK_SECONDS", 0.5)
    sess = _ScribeFake({("pick", ("key", "Return")): "pick",
                        ("pick", ("key", 0x0D)): "pick"})
    run = _scribe_run(tmp_path, sess)
    with pytest.raises(A.StepFailed, match="raised the queue count"):
        run.scribe("MORGAINE>PROTECTION FROM GOOD")
    run.log.close()
    assert not run.scribing
    assert list(tmp_path.glob("*lost-scribe-pick.txt"))


def test_scribe_fails_on_the_games_refusal_without_a_second_key(tmp_path):
    sess = _ScribeFake({("pick", ("key", "Return")): "refused"})
    run = _scribe_run(tmp_path, sess)
    with pytest.raises(A.StepFailed, match="CAN'T SCRIBE STONE TO FLESH"):
        run.scribe("MORGAINE>STONE TO FLESH")
    run.log.close()
    assert sess.sent[-1] == ("key", "Return") and ("key", 0x0D) not in sess.sent


def test_scribe_fails_when_the_count_is_zero_at_the_end(tmp_path):
    sess = _ScribeFake(scribed={"picked", "listexit", "chosen", "confirm"})
    run = _scribe_run(tmp_path, sess)
    with pytest.raises(A.StepFailed, match="zero at the end"):
        run.scribe("MORGAINE>PROTECTION FROM GOOD")
    run.log.close()


def test_scribe_refuses_a_spell_that_is_not_on_the_scroll(tmp_path):
    sess = _ScribeFake()
    run = _scribe_run(tmp_path, sess)
    with pytest.raises(A.StepFailed, match="FIREBALL is not on the scroll list"):
        run.scribe("MORGAINE>FIREBALL")
    run.log.close()
    assert sess.state == "list"


def test_scribe_refuses_when_the_working_record_is_someone_else(tmp_path):
    sess = _ScribeFake(name=b"DOMINIC")
    run = _scribe_run(tmp_path, sess)
    with pytest.raises(A.StepFailed, match="'DOMINIC', not MORGAINE"):
        run.scribe("MORGAINE>PROTECTION FROM GOOD")
    run.log.close()
    assert sess.state == "magic"


def _camp_rest(tmp_path, monkeypatch, scribing):
    seen = {}

    def fake_rest(s, log, minutes, hours, cp):
        seen["state"], seen["sent"] = s.state, list(s.sent)
        return {"before": {"clock": [0, 0, 0, 4, 0, 0]},
                "after": {"clock": [0, 0, 0, 12, 0, 0]}}

    monkeypatch.setattr(A.route_pool, "rest", fake_rest)
    sess = _RestSession({"world": _window({}, WORLD_BAR), "camp": _window({}, CAMP)},
                        {("camp", ("bar", "EXIT")): "world",
                         ("world", ("bar", "ENCAMP")): "camp"}, "camp")
    sess.squares = [[3, 4, 2], [3, 4, 2]]
    run, log = _pool_run(tmp_path, sess)
    run.scribing = scribing
    run.scribe_square = [3, 4, 2]
    try:
        got = run.rest("8h")
    finally:
        log.close()
    return got, seen, run


def test_rest_after_a_scribe_rests_in_the_same_camp(tmp_path, monkeypatch):
    got, seen, run = _camp_rest(tmp_path, monkeypatch, scribing=True)
    assert seen == {"state": "camp", "sent": []}
    assert got["stayed_in_camp"] is True and got["rest_completed"] is True
    assert got["position_before"] == [3, 4, 2]
    assert not run.scribing


def test_rest_without_a_scribe_still_leaves_camp_first(tmp_path, monkeypatch):
    got, seen, _ = _camp_rest(tmp_path, monkeypatch, scribing=False)
    assert seen["sent"] == [("bar", "EXIT"), ("bar", "ENCAMP")]
    assert "stayed_in_camp" not in got


def test_scribe_does_not_send_the_second_key_after_a_refusal_flash_between_polls(
        tmp_path, monkeypatch):
    monkeypatch.setattr(A, "SCRIBE_PICK_SECONDS", 0.5)

    class Flash(_ScribeFake):
        def _go(self, what):
            if self.state == "pick" and what == ("key", "Return"):
                self.hot = 10  # the refusal moved the highlight to EXIT
            return super()._go(what)

    sess = Flash({("pick", ("key", "Return")): "pick"})
    run = _scribe_run(tmp_path, sess)
    with pytest.raises(A.StepFailed, match="may have refused"):
        run.scribe("MORGAINE>STONE TO FLESH")
    run.log.close()
    assert ("key", 0x0D) not in sess.sent
    assert list(tmp_path.glob("*lost-scribe-pick.txt"))


def test_scribe_does_not_send_the_second_key_when_the_prompt_was_replaced(
        tmp_path, monkeypatch):
    monkeypatch.setattr(A, "SCRIBE_PICK_SECONDS", 0.5)
    # The first key replaced the pick prompt: no spell row, no highlight.
    sess = _ScribeFake({("pick", ("key", "Return")): "chosen"}, scribed=set())
    run = _scribe_run(tmp_path, sess)
    with pytest.raises(A.StepFailed, match="may have refused"):
        run.scribe("MORGAINE>PROTECTION FROM GOOD")
    run.log.close()
    assert ("key", 0x0D) not in sess.sent


def test_scribe_asks_again_when_the_monitor_did_not_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "SCRIBE_PICK_SECONDS", 0.5)
    monkeypatch.setattr(A.time, "sleep", lambda s: None)

    class Silent(_ScribeFake):
        silent = False

        def screen(self):
            if self.silent:
                self.silent = False
                return None
            return super().screen()

    sess = Silent({("pick", ("key", "Return")): "pick",
                   ("pick", ("key", 0x0D)): "picked"})
    run = _scribe_run(tmp_path, sess)
    real = run._scribe_untouched

    def arm(spell):
        sess.silent = True
        real(spell)

    run._scribe_untouched = arm
    try:
        got = run.scribe("MORGAINE>PROTECTION FROM GOOD")
    finally:
        run.log.close()
    assert got["key"] == "kernal-return"
    assert ("key", 0x0D) in sess.sent


def test_scribe_refuses_a_list_with_next_or_prev(tmp_path):
    screens = {**SCRIBE_SCREENS, "list": _window(_SCROLL, "SCRIBE NEXT EXIT")}
    sess = _ScribeFake()
    sess.screens = screens
    run = _scribe_run(tmp_path, sess)
    with pytest.raises(A.StepFailed, match="more than one page"):
        run.scribe("MORGAINE>PROTECTION FROM GOOD")
    run.log.close()
    assert ("bar", "SCRIBE") in sess.sent and ("key", "Return") not in sess.sent


def test_scribe_addresses_of_each_title():
    got = {k: (v.record, v.roster, v.queue) for k, v in A.SCRIBE_ADDRESSES.items()}
    assert got == {
        "pool-of-radiance": (0x6B00, 0x6C00, 0x2939),
        "curse-of-the-azure-bonds": (0x7C00, 0x7D00, 0xA945),
        "secret-of-the-silver-blades": (0x7C00, 0x7D00, 0xA945)}


def test_a_scribe_pending_is_dropped_by_any_step_but_rest(tmp_path, monkeypatch):
    import contextlib
    from types import SimpleNamespace

    from tools.curse_of_the_azure_bonds import curserun

    source = _fixture_disk(tmp_path)
    slot = _Slot(tmp_path)
    monkeypatch.setattr(A.runlog, "catch_signals", lambda: None)
    monkeypatch.setattr(A.S, "claim_slot", lambda *a, **k: slot)
    monkeypatch.setattr(A, "stage", lambda *a, **k: {"effects": [],
                                                    "magic_items": []})
    monkeypatch.setattr(curserun, "stage", lambda *a, **k: "first")

    class Session:
        save_disk = "disk"

        def __init__(self, *a, **k):
            pass

        def watching_dialogs(self):
            return contextlib.nullcontext()

        def terminate(self):
            pass

    monkeypatch.setattr(curserun, "CurseSession", Session)
    seen = []

    class Run:
        scribing = False

        def __init__(self, *args):
            pass

        def load(self):
            return {}

        def scribe(self, arg):
            self.scribing = True
            return {}

        def camp_list(self, arg):
            return {}

        def rest(self, arg):
            seen.append(self.scribing)
            return {}

        def reading(self):
            return {}

        def capture(self, tag):
            pass

    monkeypatch.setattr(A, "CurseRun", Run)

    def go(steps, run_name):
        args = SimpleNamespace(title="curse", max_seconds=120, stage_row=[],
                               stage_trait=[], stage_item=[], stage_only=False,
                               checkpoint=[], pool=None, issue="745", run=run_name,
                               disks="unused", attack_by="", walk="I",
                               walk_steps=60, quit_nonattacking=False,
                               probe_step=False)
        return A.run(args, A.parse_steps(steps), tmp_path / run_name, source)

    assert go(["load", "scribe MORGAINE>DISINTEGRATE", "camp-list", "rest 8h"],
              "apart") == 0
    assert go(["load", "scribe MORGAINE>DISINTEGRATE", "rest 8h"], "straight") == 0
    assert seen == [False, True]


class _LaterItemsFake(_CurseFake):
    def wait_bar(self, word, timeout=0):
        return word in self.screens[self.state][24]


def test_later_title_items_leave_the_list_and_the_sheet_for_the_world(tmp_path):
    screens = {
        "camp": _window({}, SSB_CAMP), "world": _window({}, WORLD_BAR),
        "sheet": _window({1: "MORGAINE           STATUS OK"}, "ITEMS EXIT"),
        "items": _window({1: "MORGAINE", 5: " NO  MAGE SCROLL 3 SPELLS"},
                         "READY USE TRADE DROP HALVE JOIN EXIT"),
    }
    moves = {("camp", ("party", 5)): "camp", ("camp", ("bar", "VIEW")): "sheet",
             ("sheet", ("bar", "ITEMS")): "items", ("items", ("bar", "EXIT")): "sheet",
             ("sheet", ("bar", "EXIT")): "camp", ("camp", ("bar", "EXIT")): "world"}
    sess = _LaterItemsFake(screens, moves, "camp")
    run = _scribe_run(tmp_path, sess)
    run.panel = ["GUY DE VALOIS", "PAINE", "EPONA", "MALACHITE", "DOMINIC", "MORGAINE"]
    try:
        got = run.items("MORGAINE")
    finally:
        run.log.close()
    assert [e["row"] for e in got["entries"]] == ["NO  MAGE SCROLL 3 SPELLS"]
    assert sess.state == "world"
    assert not list(tmp_path.glob("*lost-world-route.txt"))


def _flee_run(outcome, slots_before, slots_after, tactics):
    class Session:
        def in_combat(self):
            return True

        def fight(self, *, budget, tactic):
            tactics.append(tactic)
            return A.S.FightResult(outcome, 4, 1.0, [], [])

    reads = iter([slots_before, slots_after])
    run = A.PoolRun.__new__(A.PoolRun)
    run.sess = Session()
    run.log = object()
    run.game = SimpleNamespace(key="unmeasured")
    run.to_world = lambda: True
    run.spent = lambda: False
    run.captured = []
    run.capture = run.captured.append
    run.reading = lambda: {"counts": {"x": 1}}
    run.party_slots = lambda: next(reads)
    return run


def _slots(*named):
    return [{"slot": i, "name": name, "status": status}
            for i, (name, status) in enumerate(named)]


def test_fight_flee_step_parses_with_an_optional_budget():
    steps = A.parse_steps(["load", "fight-flee", "fight-flee 900"])
    assert [(s.verb, s.arg) for s in steps[1:]] == [
        ("fight-flee", ""), ("fight-flee", "900")]
    with pytest.raises(ValueError, match="seconds"):
        A.parse_steps(["load", "fight-flee 0"])


def test_fight_flee_records_who_got_away_and_who_was_left_behind():
    tactics = []
    run = _flee_run(A.S.RAN,
                    _slots(("ROLAND", 1), ("BRUTUS", 0x85), ("", 0)),
                    _slots(("ROLAND", 1), ("BRUTUS", 0), ("", 0)), tactics)
    got = run.fight("900", "I", 5, flee=True)
    assert got["got_away"] == [
        {"slot": 0, "name": "ROLAND", "status_before": 1, "status_after": 1}]
    assert got["left_behind"] == [
        {"slot": 1, "name": "BRUTUS", "status_before": 0x85,
         "status_after": 0}]
    assert got["outcome"] == A.S.RAN
    assert isinstance(tactics[0], fleedrive.Flight)
    assert run.captured == ["fight-start", "fight-end"]


@pytest.mark.parametrize("outcome", [A.S.BUDGET, A.S.WON, A.S.LOST])
def test_fight_flee_that_does_not_run_away_fails_naming_the_step(outcome):
    run = _flee_run(outcome, _slots(("ROLAND", 0)), _slots(("ROLAND", 0)), [])
    with pytest.raises(A.StepFailed, match="fight-flee") as err:
        run.fight("60", "I", 5, flee=True)
    if outcome == A.S.BUDGET:
        assert "60 second budget" in str(err.value)
    assert run.captured[-1] == "lost-fight-flee"


def test_fight_flee_leaves_behind_a_member_whose_status_the_drop_zeroed_though_the_name_stays():
    """`POST.COM $0DF8` writes 0 into the roster status; the record's name is
    not what marks the slot, and a dead member is dropped like any other."""
    run = _flee_run(A.S.RAN,
                    _slots(("ROLAND", 1), ("BRUTUS", 0x83), ("LADY", 1)),
                    _slots(("ROLAND", 1), ("BRUTUS", 0), ("LADY", 0)), [])
    got = run.fight("60", "I", 5, flee=True)
    assert [m["name"] for m in got["got_away"]] == ["ROLAND"]
    assert [(m["name"], m["status_before"]) for m in got["left_behind"]] == [
        ("BRUTUS", 0x83), ("LADY", 1)]


def test_fight_flee_party_slots_reads_names_and_statuses_from_a_monitor():
    box = A.c64_save.CONTAINERS["pool-of-radiance"]
    memory = {}
    for slot, (name, status) in enumerate([("ROLAND", 1), ("", 0x83)]):
        record = bytearray(box.slot_stride)
        record[1:1 + len(name)] = name.encode()
        memory[box.slot_area_base + slot * box.slot_stride] = bytes(record)
        memory[box.roster_base + slot * box.roster_stride] = bytes([status])

    class Mon:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, addr, n):
            out = bytearray(n)
            for at, blob in memory.items():
                for i, b in enumerate(blob):
                    if 0 <= at + i - addr < n:
                        out[at + i - addr] = b
            return bytes(out)

        def resume(self):
            pass

    run = A.PoolRun.__new__(A.PoolRun)
    run.box = box
    run.sess = SimpleNamespace(mon=lambda timeout: Mon())
    got = run.party_slots()
    assert [s["status"] for s in got[:3]] == [1, 0x83, 0]
    assert [s["slot"] for s in got] == list(range(A.PARTY_SLOTS))
    rec = memory[box.slot_area_base]
    assert got[0]["name"] == A.CharacterRecord(
        rec.ljust(A.RECORD_SIZE, b"\0"), stored_size=len(rec)).name


def test_curse_fight_flee_records_the_drop_and_reads_the_mercy_byte(
        monkeypatch, tmp_path):
    from tools.c64 import laterbattle
    from tools.curse_of_the_azure_bonds import cursethac0

    tactics = []

    class Route:
        last_goto_steps = 2

        def __init__(self, out, quiet):
            self.file = SimpleNamespace(close=lambda: None)

        def goto(self, target, steps, geo):
            return True

    class Mon:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, addr, n):
            assert addr == 0x7EE6
            return bytes([0])

    class Session:
        def in_combat(self):
            return True

        def await_bar(self, *a, **k):
            return None

        def mon(self, timeout):
            return Mon()

        def fight(self, *, budget, tactic):
            tactics.append(tactic)
            return A.S.FightResult(A.S.RAN, 2, 1.0, [], [])

    monkeypatch.setattr(laterbattle, "Battle", Route)
    monkeypatch.setattr(cursethac0, "area_geo", lambda *a: ("GEO01", object()))
    reads = iter([_slots(("A", 1), ("B", 1)), _slots(("A", 1), ("B", 0))])
    run = A.CurseRun.__new__(A.CurseRun)
    run.attack_by, run.attack_owner = "", None
    run.sess, run.out, run.log = Session(), tmp_path, object()
    run.game = SimpleNamespace(key="curse-of-the-azure-bonds")
    run.staged_disk, run.disks = tmp_path / "s.D64", "unused"
    run.to_world = lambda: True
    run.await_combat = lambda: True
    run.capture = lambda tag: None
    run.party_slots = lambda: next(reads)
    got = run.fight("10", "I", 5, flee=True)
    assert isinstance(tactics[0], fleedrive.Flight)
    assert [m["name"] for m in got["left_behind"]] == ["B"]
    assert (got["mercy_before"], got["mercy_after"]) == (0, 0)


def test_curse_fight_flee_is_refused_under_the_attack_diagnostic():
    run = A.CurseRun.__new__(A.CurseRun)
    run.attack_by, run.attack_owner = "ROLAND", 0
    run.capture = lambda tag: None
    run.spent = lambda: False
    with pytest.raises(A.StepFailed, match="fight-flee"):
        run.fight("10", "I", 5, flee=True)


@pytest.mark.parametrize("outcome, dropped, ok, seen", [
    (A.S.RAN, False, True, True),
    (A.S.ENDED, True, True, False),
    (A.S.ENDED, False, False, False)])
def test_silver_fight_flee_counts_the_world_bar_first_only_with_a_member_dropped(
        monkeypatch, tmp_path, outcome, dropped, ok, seen):
    sess = _SilverFight()
    sess.outcome, sess.after = outcome, A.S.DUNGEON
    run, events, captures = _silver_run(monkeypatch, tmp_path, sess)
    run.game = SimpleNamespace(key="secret-of-the-silver-blades")
    run.flight_tactic = lambda: lambda s, bar: "MOVE"
    run.keep_fight_reading = lambda: None
    run.spent = lambda: False
    after = _slots(("A", 1), ("B", 0 if dropped else 1))
    reads = iter([_slots(("A", 1), ("B", 1)), after, after])
    run.party_slots = lambda: next(reads)
    if not ok:
        with pytest.raises(A.StepFailed, match="fight-flee"):
            run.fight("600", "I", 40, flee=True)
        return
    got = run.fight("600", "I", 40, flee=True)
    assert got["ran_line_seen"] is seen
    assert got["outcome_seen"] == outcome
    assert got["outcome"] == A.S.RAN
    assert [m["name"] for m in got["left_behind"]] == (["B"] if dropped else [])


@pytest.mark.parametrize("status", [0x83, 0x84, 3])
def test_silver_fight_flee_does_not_count_a_dead_or_dying_member_as_a_run(
        monkeypatch, tmp_path, status):
    sess = _SilverFight()
    sess.outcome, sess.after = A.S.ENDED, A.S.DUNGEON
    run, events, captures = _silver_run(monkeypatch, tmp_path, sess)
    run.game = SimpleNamespace(key="secret-of-the-silver-blades")
    run.flight_tactic = lambda: lambda s, bar: "MOVE"
    run.keep_fight_reading = lambda: None
    run.spent = lambda: False
    reads = iter([_slots(("A", 1), ("B", 1)), _slots(("A", 1), ("B", status))])
    run.party_slots = lambda: next(reads)
    with pytest.raises(A.StepFailed, match="fight-flee"):
        run.fight("600", "I", 40, flee=True)
