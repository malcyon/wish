from __future__ import annotations

"""The DOS combat driver, and the one signal that says a party fought.

Three kinds of test, and only the last needs an emulator.

* **What the files say.** `fought()` reads experience and nothing else,
  because monsters do not kill each other -- so a rise names the party as the
  killer. Hit points falling is the trap #163 was filed about and is asserted
  here to be no proof at all.
* **What the driver presses.** `fight()` is driven against a scripted stand-in
  for `Session`, so the key it sends at each screen is checked with no DOSBox
  anywhere.
* **A driven fight**, behind `WISH_DOSBOX_DRIVE=1`: load, fight, save, and
  assert experience rose.

Nothing here is copied out of the game. The bar digests are hashes of the
game's pixels, which is a measurement of them rather than a copy.
"""

import os
import pathlib
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools import dosbox, dosfightrun  # noqa: E402

BAR_W, BAR_H = dosbox.BAR[2], dosbox.BAR[3]

# --------------------------------------------------------------------------
# The offsets this tool reads are the layout's own
# --------------------------------------------------------------------------


def test_the_record_offsets_are_the_layouts_and_not_a_second_copy():
    """#76's rule: one byte map, `goldbox/`'s, never a harness copy of it.

    `tools/dosbox.py` already held a second `AREA_ID` that had drifted out of
    the map's units, so a reader who fixed one side would never have found the
    other. These three are read raw for speed and are pinned to the table.
    """
    from goldbox.dos_layout import FIELDS_BY_NAME

    assert FIELDS_BY_NAME["experience"].offset == dosfightrun.XP
    assert FIELDS_BY_NAME["experience"].size == 3
    assert FIELDS_BY_NAME["hp_current"].offset == dosfightrun.HP_CURRENT
    assert FIELDS_BY_NAME["hp_current"].size == 1


# --------------------------------------------------------------------------
# What says a fight was fought
# --------------------------------------------------------------------------


def _snapshot(pairs, slums=0):
    """A `party_state`-shaped dict from `(experience, hp_current)` pairs."""
    chars = []
    for n, (xp, hp) in enumerate(pairs, start=1):
        rec = bytearray(285)
        rec[dosfightrun.XP:dosfightrun.XP + 3] = xp.to_bytes(3, "little")
        rec[dosfightrun.HP_CURRENT] = hp
        chars.append(
            {
                "file": f"CHRDATC{n}.SAV",
                "experience": xp,
                "hp_current": hp,
                "quickfight_candidate": rec[dosfightrun.QUICKFIGHT_BYTE],
                "mtime": 0.0,
                "raw": bytes(rec).hex(),
            }
        )
    save = bytearray(13137)
    off = dosbox._sav.word_offset(dosfightrun.SLUMS_FIGHTS) * 2
    save[off:off + 2] = slums.to_bytes(2, "little")
    return {
        "slot": "C",
        "chars": chars,
        "save": {
            "file": "SAVGAMC.DAT",
            "position": [14, 5, 4],
            "area_id": 20,
            "slums_fights": slums,
            "mtime": 0.0,
            "raw": bytes(save).hex(),
        },
    }


def test_hit_points_falling_is_never_proof_that_the_party_fought():
    """The #163 trap, in the place it can be made harmless.

    A party that stands through a fight and is beaten on loses hit points and
    strikes nobody. On the C64 the message band printed `HITS` and `MISSES`
    for both sides in the same words and could not tell those apart; here the
    files can, and this pins that they do.
    """
    before = _snapshot([(48, 11), (15, 4)])
    after = _snapshot([(48, 3), (15, 1)])
    diff = dosfightrun.state_diff(before, after)
    assert diff["hit_points_fell"] is True
    assert diff["experience_rose"] is False
    assert dosfightrun.fought(diff) is False


def test_experience_rising_says_the_party_killed_something():
    before = _snapshot([(48, 11), (15, 4)])
    after = _snapshot([(70, 11), (15, 4)])
    assert dosfightrun.fought(dosfightrun.state_diff(before, after)) is True


def test_a_miss_lowers_nothing_so_an_unchanged_party_is_not_a_fought_fight():
    """Every field the same is not evidence either way, and must not read as one."""
    same = _snapshot([(48, 11)])
    diff = dosfightrun.state_diff(same, _snapshot([(48, 11)]))
    assert dosfightrun.fought(diff) is False
    assert diff["hit_points_fell"] is False


def test_the_slums_counter_is_read_at_the_address_ecl14_increments():
    before = _snapshot([(48, 11)], slums=3)
    after = _snapshot([(70, 11)], slums=4)
    diff = dosfightrun.state_diff(before, after)
    assert diff["save"]["slums_fights"] == [3, 4]


# --------------------------------------------------------------------------
# What the driver presses, with no DOSBox anywhere
# --------------------------------------------------------------------------
#
# `fight()` talks to a `Session` through four methods, so a stand-in for those
# four is enough to check every key it sends.  This is the part of the driver
# that can be wrong silently: a key pressed at a bar that does not carry it
# spins to the full timeout -- 441 of 605 seconds of one C64 fight -- and a
# key pressed twice at a bar that has already moved on is a command given to
# whatever came next.


class _Screen:
    """One frame: what each width of the bar row hashes to, and the frame.

    A width is a separate value because that is how the real screen works:
    two command bars that differ after the fourth word hash the same over the
    leftmost 136 pixels and differently over the whole strip, and the driver
    recognises them by the first.
    """

    def __init__(self, bar: str, frame: str, prefixes: dict | None = None):
        self._bar, self._frame = bar, frame
        self._prefixes = prefixes or {}

    def ink(self, rect=None) -> str:
        return self._bar

    def glyphs(self, rect=None) -> str:
        width = BAR_W if rect is None else rect[2]
        if width == BAR_W:
            return self._bar
        return self._prefixes.get(width, f"no {width}px prefix")

    def digest(self, rect=None) -> str:
        return self._frame


class _ScriptedSession:
    """A `Session` that plays a written-down sequence of frames.

    The last frame repeats for ever, so a script says "and then it stays like
    that" without padding.
    """

    def __init__(self, frames):
        self.frames = list(frames)
        self.last = self.frames[-1]
        self.pressed: list[str] = []
        self.shots: list[str] = []

    def capture(self) -> _Screen:
        if len(self.frames) > 1:
            self.last = self.frames.pop(0)
        elif self.frames:
            self.last = self.frames[0]
        return _Screen(*self.last)

    def key(self, *keys, gap=0.0) -> None:
        self.pressed.extend(keys)

    def wait_for(self, pred, timeout=30.0) -> bool:
        for _ in range(len(self.frames)):
            if pred(self.capture()):
                return True
        return pred(self.capture())

    def wait_while_ink(self, rect, same, timeout=30.0) -> bool:
        return self.wait_for(lambda s: s.ink(rect) != same, timeout)

    def wait_while_glyphs(self, rect, same, timeout=30.0) -> bool:
        return self.wait_for(lambda s: s.glyphs(rect) != same, timeout)

    def shot(self, name, allow_blank=False):
        self.shots.append(name)
        return None


def _por(frames, world="world"):
    por = dosbox.PoolOfRadiance(_ScriptedSession(frames))
    por.world_bar = por.world_glyphs = world
    return por


def _label(name):
    """The `(width, digest)` `COMBAT_BARS` recognises `name` by."""
    return next((w, d) for w, d, lbl in dosbox.PoolOfRadiance.COMBAT_BARS
                if lbl == name)


COMMAND_W, COMMAND_D = _label("command")
ENCOUNTER_W, ENCOUNTER_D = _label("encounter")
BLANK = _label("blank")[1]


def command(n: int) -> tuple[str, str, dict]:
    """One frame of a combat command bar, variant `n`.

    Each variant has its own whole-strip digest -- a fighter's bar and a
    cleric's really are different bars -- and they share the prefix.
    """
    return (f"command bar variant {n}", f"frame {n}", {COMMAND_W: COMMAND_D})


def encounter(n: int) -> tuple[str, str, dict]:
    """One frame of an encounter menu, variant `n` -- ADVANCE or PARLAY."""
    return (f"encounter menu variant {n}", f"frame e{n}",
            {ENCOUNTER_W: ENCOUNTER_D})


def test_the_driver_answers_an_encounter_with_combat_and_a_turn_with_quick():
    por = _por([
        encounter(1),
        command(1),
        command(2),           # a cleric's turn: a different bar, same prefix
        ("world", "f4"),
    ])
    assert por.fight(budget=5.0, settled=0.0) is True
    assert por.s.pressed == ["c", "q"]


def test_the_driver_presses_nothing_at_a_bar_it_has_not_recognised():
    """A monster's turn, an animation, or a screen nobody has labelled.

    `A BATTLE BEGINS...` is the real one: it occupies the bar row and carries
    no commands at all, and a driver that pressed at it would be giving an
    order to whatever the game drew next.
    """
    por = _por([("unlabelled", "f1"), ("unlabelled", "f2"), ("world", "f3")])
    assert por.fight(budget=5.0, settled=0.0) is True
    assert por.s.pressed == []


def test_the_driver_gives_up_with_a_screenshot_rather_than_hanging():
    por = _por([command(1)])
    assert por.fight(budget=0.6, settled=0.0) is False
    assert por.s.shots == ["fight_stuck"]


def test_the_world_bar_has_to_hold_before_the_fight_is_called_finished():
    """One frame of the world bar is not the end of a fight.

    The bar blanks and redraws between screens, so a single capture that
    happens to match is not evidence -- the C64 side called a half-redrawn bar
    the end of a turn and starved a fight of them.
    """
    por = _por([("world", "f1"), command(1), command(2), ("world", "f4")])
    assert por.fight(budget=5.0, settled=1.0) is True
    # The first frame was the world bar and the fight was not over: a `q` was
    # pressed after it, which could not have happened had one frame ended it.
    assert por.s.pressed == ["q"]


def test_a_fight_needs_the_world_bar_load_game_recorded():
    por = dosbox.PoolOfRadiance(_ScriptedSession([("world", "f1")]))
    try:
        por.fight(budget=1.0)
    except RuntimeError as e:
        assert "world bar" in str(e)
    else:
        raise AssertionError("fight() ran with no world bar to come back to")


def test_every_label_the_driver_presses_at_is_a_bar_it_can_recognise():
    """A key mapped to a label nothing produces is a key nothing ever sends."""
    labels = {lbl for _, _, lbl in dosbox.PoolOfRadiance.COMBAT_BARS}
    assert set(dosbox.PoolOfRadiance.COMBAT_KEYS) <= labels


def test_the_two_bars_that_carry_no_commands_get_no_key():
    """`A BATTLE BEGINS...` and a bar caught mid-redraw are not command bars.

    Both occupy the bar row and neither offers anything, so a key sent at
    either is a command given to whatever the game draws next.
    """
    labels = {lbl for _, _, lbl in dosbox.PoolOfRadiance.COMBAT_BARS}
    for label in ("message", "blank"):
        assert label in labels
        assert label not in dosbox.PoolOfRadiance.COMBAT_KEYS


def test_the_bars_are_all_distinct():
    """Two labels on one digest would make the driver's choice arbitrary."""
    bars = dosbox.PoolOfRadiance.COMBAT_BARS
    assert len({lbl for _, _, lbl in bars}) == len(bars)
    assert len({(w, d) for w, d, _ in bars}) == len(bars)


def test_a_prefix_is_only_ever_looked_for_after_the_whole_strip():
    """A flat bar has a flat prefix, so the order in the table is the rule."""
    widths = [w for w, _, _ in dosbox.PoolOfRadiance.COMBAT_BARS]
    assert widths == sorted(widths, reverse=True)


# --------------------------------------------------------------------------
# Why the fight reads the bar with `glyphs` and not with `ink`
# --------------------------------------------------------------------------


def _strip(paper, pen, lit):
    """A 320x7 PPM: `paper` everywhere, `pen` at the pixel indexes in `lit`."""
    px = bytearray(bytes(paper) * (320 * 7))
    for i in lit:
        px[i * 3:i * 3 + 3] = bytes(pen)
    return b"P6\n320 7\n255\n" + bytes(px)


def test_ink_cannot_tell_two_combat_bars_apart_and_glyphs_can():
    """The defect a driven fight found, in the smallest form that shows it.

    `Screen.ink` calls a pixel lit when its channels sum over 120. The combat
    screen's paper is `#555555`, which sums to 255, so the whole bar strip is
    lit and every bar on that screen hashes to the sha1 of 2240 ones --
    `MOVE VIEW AIM USE QUICK DONE` and `CONTINUE BATTLE : YES NO` came back as
    the same number, and the driver pressed `QUICK` at a yes-or-no question
    and went on pressing it.
    """
    grey, white = (0x55, 0x55, 0x55), (0xFF, 0xFF, 0xFF)
    one = dosbox.Screen.from_ppm(_strip(grey, white, range(0, 200)))
    two = dosbox.Screen.from_ppm(_strip(grey, white, range(400, 900)))
    assert one.ink() == two.ink()
    assert one.glyphs() != two.glyphs()


def test_glyphs_still_ignores_the_colour_the_world_bar_is_drawn_in():
    """The property `ink` was written for, which `glyphs` must not lose.

    The world bar is white for one frame after the party arrives somewhere and
    green thereafter, with not a glyph moved. Both must read as one bar or
    every step would end at a screen that never comes back.
    """
    black = (0, 0, 0)
    lit = range(0, 200)
    white = dosbox.Screen.from_ppm(_strip(black, (0xFF, 0xFF, 0xFF), lit))
    green = dosbox.Screen.from_ppm(_strip(black, (0x00, 0xAA, 0x00), lit))
    assert white.glyphs() == green.glyphs()


def test_no_recorded_combat_bar_is_a_strip_of_one_colour():
    """A digest that is all-ink or all-paper is not a bar, it is a mistake.

    Both got into the table on the first pass and one of them was labelled
    `command`, which is what sent `QUICK` at `CONTINUE BATTLE : YES NO`.
    """
    import hashlib

    degenerate = {
        hashlib.sha1(bytes([1]) * (w * BAR_H)).hexdigest()[:16]
        for w, _, _ in dosbox.PoolOfRadiance.COMBAT_BARS
    } | {
        hashlib.sha1(bytes(w * BAR_H)).hexdigest()[:16]
        for w, _, _ in dosbox.PoolOfRadiance.COMBAT_BARS
    }
    pressed = {d for _, d, label in dosbox.PoolOfRadiance.COMBAT_BARS
               if label in dosbox.PoolOfRadiance.COMBAT_KEYS}
    assert not (pressed & degenerate)



# --------------------------------------------------------------------------
# A fight actually driven, which is the only thing that proves any of it
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("WISH_DOSBOX_DRIVE") != "1",
    reason="set WISH_DOSBOX_DRIVE=1 to boot DOSBox; a fight takes a few minutes",
)
def test_a_driven_fight_raises_experience_in_the_records():
    """Walk into a wandering fight, `fight()` it, and read the files after.

    Experience rising is the assertion because it is the only field that says
    the party did the killing. Hit points are not asserted on in either
    direction: a fight the party wins without being touched moves none of
    them, and a fight it stands through moves plenty.
    """
    if dosbox.missing_tools():
        pytest.skip("needs " + ", ".join(dosbox.missing_tools()))
    try:
        dosbox.find_game()
    except FileNotFoundError as e:
        pytest.skip(str(e))
    out = dosfightrun.fight_run(save="J", rounds=1)
    run = out["runs"][0]
    assert run.get("fight") is True, run
    assert run["fought"] is True, run["diff"]["chars"]


def test_a_clerics_command_bar_is_recognised_though_it_is_a_different_bar():
    """The run this cost: a fighter is offered `MOVE VIEW AIM USE QUICK DONE`
    and a cleric `MOVE VIEW AIM USE CAST TURN QUICK DONE`. Those are different
    bars by any whole-strip hash, and a driver holding a list of whole-strip
    hashes met the second one and stood at it until its budget ran out.
    """
    por = _por([command(7), ("world", "f2")])
    assert por.fight(budget=5.0, settled=0.0) is True
    assert por.s.pressed == ["q"]


def test_a_bar_nobody_has_labelled_gives_up_naming_its_digest():
    """Giving up quickly is what leaves the evidence to add the row.

    Standing at an unknown bar until a fifteen-minute budget expires throws
    away the one thing the next reader needs, which is a picture of it.
    """
    por = _por([("a bar nobody has seen", "f1")])
    assert por.fight(budget=5.0, settled=0.0, patience=0.0) is False
    assert por.s.shots == ["fight_unknown_bar_a bar nobody has seen"]


def test_a_flat_bar_is_blank_and_not_a_command_bar():
    """Order matters in `bar_kind`: a strip of one colour has a flat prefix
    too, so the whole-strip table has to be consulted first or a bar caught
    mid-redraw would be answered with `QUICK`.
    """
    por = _por([(BLANK, "f1", {COMMAND_W: COMMAND_D}), ("world", "f2")])
    assert por.fight(budget=5.0, settled=0.0) is True
    assert por.s.pressed == []


def test_an_orc_encounter_is_recognised_though_its_menu_reads_differently():
    """The other run this cost: goblins are met with
    `COMBAT WAIT FLEE ADVANCE` and orcs, who will talk, with
    `COMBAT WAIT FLEE PARLAY`. Different bars by any whole-strip hash, one
    menu to the driver.
    """
    por = _por([encounter(2), command(1), command(2), ("world", "f3")])
    assert por.fight(budget=5.0, settled=0.0) is True
    assert por.s.pressed == ["c", "q"]


# --------------------------------------------------------------------------
# The save is seven files, and the one the harness watches is not the last
# --------------------------------------------------------------------------


def test_waiting_for_a_save_waits_for_the_whole_directory(tmp_path):
    """`SAVGAM<slot>.DAT` changing does not mean the records are on disk.

    Measured on both slots of three runs: the six `CHRDAT<slot><n>.SAV` land 1
    to 11 milliseconds after it. Nothing has lost that race yet, and eleven
    milliseconds is not a margin to rely on -- a caller reading experience the
    moment `save_game` returns would be reading the previous fight's number.
    """
    (tmp_path / "SAVGAMC.DAT").write_bytes(b"x")
    assert dosbox.settle_files(tmp_path, quiet=0.05, timeout=5.0) is True


def test_a_directory_being_written_to_is_not_called_quiet(tmp_path,
                                                          monkeypatch):
    """A save still in flight must not be called finished.

    **This was a background thread scribbling every 20 ms, and it went red on
    CI within the hour.** The thread has to be scheduled inside the quiet
    window for the test to mean anything, and on a loaded runner it was not:
    `settle_files` saw an unchanged mtime for the whole 200 ms and answered
    True. The test was measuring the runner, not the function.

    So the writing is driven by the polling instead. `settle_files` sleeps
    between reads; every sleep stamps the file forward, which is exactly what
    a save in flight looks like from the outside and cannot be starved out.
    `os.utime` with counted stamps rather than a real write, so no filesystem's
    mtime granularity can make two writes look like one.
    """
    save = tmp_path / "SAVGAMC.DAT"
    save.write_bytes(b"x")
    stamps = iter(range(1, 100_000))
    real_sleep = time.sleep

    def write_then_sleep(seconds):
        n = next(stamps)
        os.utime(save, (n, n))
        real_sleep(0.01)

    monkeypatch.setattr(dosbox.time, "sleep", write_then_sleep)
    assert dosbox.settle_files(tmp_path, quiet=0.2, timeout=1.0) is False
