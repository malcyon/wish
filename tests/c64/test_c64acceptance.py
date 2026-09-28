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

import json
import os
import pathlib
import subprocess
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
    monkeypatch.setattr(A, "temple_source_guard", lambda path: "checked")
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
    monkeypatch.setattr(A, "temple_source_guard", lambda path: "checked")
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
    monkeypatch.setattr(A, "TEMPLE_SOURCE_SHA256", digest)
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


class _TempleScreen:
    def __init__(self, rows, bar_highlight=None, party_highlight=None):
        self._rows = [row.ljust(40)[:40] for row in rows]
        self.codes = bytes(ord(char) for row in self._rows for char in row)
        colours = bytearray(1000)
        if bar_highlight is not None:
            start, width = bar_highlight
            colours[24 * 40 + start:24 * 40 + start + width] = bytes([1]) * width
        if party_highlight is not None:
            colours[party_highlight * 40 + A.S.PARTY_COLUMN] = 1
        self.colours = bytes(colours)

    def row(self, n):
        return self._rows[n]

    def text(self):
        return "\n".join(self._rows)


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

    def mon(self, _timeout):
        return _TempleMonitor(self)

    def screen(self):
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
            names = ["ROLAND", "BAKSHI", "SHARA", "MARK", "PHILIPPE", "BRUTUS"]
            for offset, name in enumerate(names):
                rows[4 + offset] = " " * A.S.PARTY_COLUMN + name
            rows[24] = ("HEAL VIEW POOL APPRAISE EXIT"
                        if self.unsafe != "wrong-menu" else "EXIT GIVE")
            if self.unsafe == "stale-greeting-status":
                # A status line that is present but reads the wrong place:
                # no live capture has shown one here, but the transition
                # must never treat this as settled if it appears.
                rows[14] = "N 00:00 99,99"
        else:
            raise AssertionError(phase)
        if phase == "question":
            return _TempleScreen(rows, (0, 3))
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
    default `TEMPLE_ROUTE`. The happy-path test asserting
    `session.moves == list("KKIIJI")` is what proves the current route."""
    old_route = (
        ("M", (0x14, 15, 4, 3), (0x14, 15, 4, 1)),
        ("I", (0x14, 15, 4, 1), (0, 0, 4, 1)),
        ("I", (0, 0, 4, 1), (0, 1, 4, 1)),
        ("J", (0, 1, 4, 1), (0, 1, 4, 0)),
        ("I", (0, 1, 4, 0), (0, 1, 3, 0)),
    )
    monkeypatch.setattr(A, "TEMPLE_ROUTE", old_route)
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
           capture_ready=False, preserve_specimen=False):
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
        capture_ready=capture_ready, preserve_specimen=preserve_specimen)
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

    monkeypatch.setattr(A, "temple_source_guard", lambda source: "checked")
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
    monkeypatch.setattr(A, "temple_source_guard", lambda source: "checked")
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

    slot_before = bytes(A.traitask.SLOT_STRIDE)
    slot_after = bytes([0x26]) + bytes(A.traitask.SLOT_STRIDE - 1)
    fx_before = bytes(A.traitask.EFFECTS[1])
    fx_after = bytes([0x26]) + bytes(A.traitask.EFFECTS[1] - 1)
    item_block = bytes(ITEM_BLOCK_STRIDE)

    script = {}
    for slot in range(8):
        key = (A.traitask.SLOT_BASE + slot * A.traitask.SLOT_STRIDE,
              A.traitask.SLOT_STRIDE)
        script[key] = [slot_before, slot_after if slot == 4 else slot_before]
    script[A.traitask.EFFECTS] = [fx_before, fx_after]
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

    monkeypatch.setattr(A.traitask, "open_items", fake_open_items)
    monkeypatch.setattr(A.traitask, "toggle_item", fake_toggle)
    monkeypatch.setattr(A.traitask, "leave_items", fake_leave_items)
    run, log = _pool_run(tmp_path, sess)
    got = run.ready("BAKSHI>GAUNTLETS OF OGRE POWER")
    log.close()

    assert calls == [
        ("open_items", "BAKSHI", "GAUNTLETS OF OGRE POWER", "ready"),
        ("toggle_item", "GAUNTLETS OF OGRE POWER", "ready"),
        ("leave_items",)]
    assert (got["who"], got["label"], got["screen_changed"], got["flipped"]) == (
        "BAKSHI", "GAUNTLETS OF OGRE POWER", True, True)
    assert got["record_diff"][4] == A.traitask.diff_bytes(
        slot_before, slot_after,
        A.traitask.SLOT_BASE + 4 * A.traitask.SLOT_STRIDE)
    assert all(got["record_diff"][s] == [] for s in range(8) if s != 4)
    assert got["effects_diff"] == A.traitask.diff_bytes(
        fx_before, fx_after, A.traitask.EFFECTS[0])
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
        record_before = bytearray(A.traitask.SLOT_STRIDE)
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
        script[(A.traitask.SLOT_BASE + slot * A.traitask.SLOT_STRIDE,
                A.traitask.SLOT_STRIDE)] = [bytes(record_before), bytes(record_after)]
        script[(ITEM_AREA_BASE + slot * ITEM_BLOCK_STRIDE,
                ITEM_BLOCK_STRIDE)] = [bytes(item_before), bytes(item_after)]
    effect_before = bytearray(A.traitask.EFFECTS[1])
    effect_after = effect_before.copy()
    effect_before[0x3D] = 0x26
    effect_after[0x3D] = 0 if effect_changed else 0x26
    script[A.traitask.EFFECTS] = [bytes(effect_before), bytes(effect_after)]
    sess.mon = lambda timeout: _ReadyMonitor(script)
    monkeypatch.setattr(A.traitask, "open_items", lambda *a: True)
    monkeypatch.setattr(A.traitask, "toggle_item", lambda *a: screen_changed)
    monkeypatch.setattr(A.traitask, "leave_items", lambda *a: None)
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

    def __init__(self, x=5, y=5, facing=0, walls=()):
        super().__init__({"world": _window({}, WORLD_BAR)}, {}, "world")
        self.x, self.y, self.facing, self.walls = x, y, facing, set(walls)
        self.clock = 0
        self.walk_refused = None
        self.pressed = []
        self.drift = 0
        self.prompts = 0
        self.settles = 0

    def position(self):
        return self.x, self.y, self.facing

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
            # #708: `M` tries the edge behind the original facing -- this
            # fake steps back keeping the facing when the edge is open, and
            # reverses the facing in place when the edge is walled (wall
            # art), the two genuine engine outcomes.
            facing = self.facing if move == "I" else (self.facing + 2) % 4
            dx, dy = ((0, -1), (1, 0), (0, 1), (-1, 0))[facing]
            if (self.x + dx, self.y + dy) not in self.walls:
                self.x, self.y = self.x + dx, self.y + dy
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


def test_walk_m_steps_backward_and_keeps_the_facing(tmp_path, monkeypatch):
    """#708: `M` is not the about-turn `TURNS` once assumed -- with no wall
    art behind the party it steps one square back and keeps the facing it
    started with, as all four live Pool of Radiance readings on an open
    square showed."""
    sess = WalkSession()
    run, log = _walk_run(tmp_path, sess, _Clock(monkeypatch))
    got = run.walk("M")
    log.close()
    assert got["position"] == [5, 6, 0] and got["squares_moved"] == 1
    assert got["asked_forward"] == 0 and got["expected_facing"] == 0


def test_walk_m_that_leaves_a_facing_neither_kept_nor_reversed_is_lost(
        tmp_path, monkeypatch):
    """#708: the engine's own rule allows `M` to end facing only where it
    started or exactly reversed; anything else is a glitch the walk must
    catch rather than silently accept."""
    sess = WalkSession()
    sess.drift = 1
    run, log = _walk_run(tmp_path, sess, _Clock(monkeypatch))
    with pytest.raises(A.StepFailed, match="should keep facing 0, it faces 1"):
        run.walk("M")
    log.close()


def test_walk_m_held_by_wall_art_reverses_the_facing(tmp_path, monkeypatch):
    """#708: the wall-art row of the engine's own rule -- `M` stays on the
    square and the facing reverses, the pairing's other genuine outcome."""
    sess = WalkSession(walls={(5, 6)})
    run, log = _walk_run(tmp_path, sess, _Clock(monkeypatch))
    got = run.walk("M")
    log.close()
    assert got["position"] == [5, 5, 2] and got["squares_moved"] == 0
    assert got["expected_facing"] == 2


class BrokenMSession(WalkSession):
    """Fakes each of the two impossible `M` outcomes #708 rules out: moving
    back while also reversing the facing, and staying put while keeping the
    facing unchanged."""

    def __init__(self, break_mode, **kw):
        super().__init__(**kw)
        self.break_mode = break_mode

    def walk_one(self, move, *a, **k):
        self.pressed.append(move)
        self.clock += 1
        if move == "M":
            if self.break_mode == "moved_and_reversed":
                self.y += 1
                self.facing = (self.facing + 2) % 4
            elif self.break_mode == "held_and_kept":
                pass
        return True


def test_walk_m_that_moves_back_and_also_reverses_the_facing_is_lost(
        tmp_path, monkeypatch):
    """#708: the two outcomes are paired -- a moved square must keep the
    facing, never reverse it too."""
    sess = BrokenMSession("moved_and_reversed")
    run, log = _walk_run(tmp_path, sess, _Clock(monkeypatch))
    with pytest.raises(A.StepFailed, match="should keep facing 0, it faces 2"):
        run.walk("M")
    log.close()


def test_walk_m_that_stays_put_and_keeps_the_facing_is_lost(tmp_path, monkeypatch):
    """#708: the two outcomes are paired -- a held square must reverse the
    facing, never keep it."""
    sess = BrokenMSession("held_and_kept")
    run, log = _walk_run(tmp_path, sess, _Clock(monkeypatch))
    with pytest.raises(A.StepFailed, match="should reverse facing to 2, it faces 0"):
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


def test_the_real_walk_one_does_not_answer_a_prompt_the_move_raised(
        tmp_path, monkeypatch):
    sess, run, log = _real_walk(tmp_path, monkeypatch, prompt_after=0.0)
    with pytest.raises(A.StepFailed, match="ran the square's event"):
        run.walk("I")
    log.close()
    assert sess.keys == ["i"], "a Return or a space went to the prompt"
    assert sess.kernal == [] and sess.attaches == []


def test_a_prompt_that_opens_after_the_look_is_not_answered_by_the_next_move(
        tmp_path, monkeypatch):
    # The first move ends by leaving move mode; the prompt opens 4 s after
    # its key, past the two-second look.
    sess, run, log = _real_walk(tmp_path, monkeypatch, prompt_after=3.95)
    sess.moved_by = 0.1
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
    from tools.secret_of_the_silver_blades import ssbsession, ssbwarp

    built = []

    class _Silver(_Pool):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            built.append(a[-2:])

    monkeypatch.setattr(A, "SilverRun", _Silver)
    monkeypatch.setattr(A, "stage", lambda *a, **k: {"effects": [], "magic_items": {}})
    monkeypatch.setattr(ssbwarp, "stage", lambda *a, **k: "first")
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


def test_the_fight_step_is_refused_for_silver_blades(tmp_path):
    with pytest.raises(SystemExit) as info:
        A.main(["--title", "ssb", "--save", str(_fixture_disk(tmp_path)),
                "--disks", str(tmp_path), "--steps", "load", "fight",
                "--out", str(tmp_path / "out")])
    assert info.value.code == 2


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
from tools.secret_of_the_silver_blades import ssbwarp as _ssbwarp  # noqa: E402

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
    for module in (_curserun, _ssbwarp):
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
