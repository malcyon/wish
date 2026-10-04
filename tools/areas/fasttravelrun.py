#!/usr/bin/env python3
"""Drive the *shipped* `automap.actions.FastTravel().run()` through a real
`automap.target.ViceTarget`, and check that it ran the exit's own handler.

`#207 (Run an exit's own handler before Fast Travel warps out)`'s two
existing proofs are elsewhere: `tools/areas/exitreentry.py`'s `reenter()` rebuilds
the 6502 stack directly and calls it a re-entry point, and
`tools/areas/reentrypoints.py` checks the five addresses that rests on against a
shipped `DUNGEON` with no emulator at all. Neither calls the production code
path a player's own Fast Travel button runs. This does:
`automap.actions.FastTravel().run()`, unmodified, through `automap.target.
ViceTarget`, on a pool slot the way `tools/gui/livecheck.py` boards one.

The one case this has been run against is the one #207 was filed for:
warping out of the Kobold Caves (area 13) to the East Window (area 27) drops
Princess Fatima from the roster the same way walking out does, because
`ECL0D $9A84`'s own prologue runs before the warp. `--from-area`,
`--to-area` and `--member` generalise the check to another exit and NPC if
one is ever wanted, but only the Kobold Caves case has a save that carries
the NPC -- `npc_party.d64` -- and has actually been driven this way.

    tools/areas/fasttravelrun.py --disks $POR_DISKS --out DIR

The two-hop case is the Kobold Caves to New Phlan (area 0) and is driven with
a wait long enough to show the 120 s deadline. `--to-area 27` is a one-exit
route and never reaches the two-hop branch:

    .venv/bin/python tools/areas/fasttravelrun.py --from-area 13 --to-area 0 \\
        --answer-timeout 150 --out DIR

`--arrival-choice LARGE` or `SMALL` picks the arrival menu's entry that
walks the party back into the starting area, then watches the trip's second hop
for the deadline plus a margin and passes only when it said nothing. The party
comes back onto the exit square, which asks `DO YOU WANT TO LEAVE?`; the walk
answers `NO` first and records the question and answer as `settle_answers`.

A run saves four screenshots under `--out` (`1-before.png`, `2-question.png`,
`3-after-second-hop.png`, `4-after-walk.png`) and writes `result.json` with
`second_hop_seconds` -- the seconds from the area byte first reading the area
the exit leads to, to reading the destination; None when there was no second
hop -- and
`total_seconds`, which runs from before the slot is claimed to the landing and
so includes staging and boot. After a PASS the party walks a few steps each way and opens
and closes the first character's sheet before teardown; a walk that fails is
its own FAIL and leaves the earlier verdict as it was.

Nothing is written to the player's disks: `tools.c64.session.stage_disks` copies
the sides into the slot, and `--save` is copied in as `SIDE0.D64`. The pool
owns the emulator lifecycle throughout -- `tools.c64.session.claim_slot` leases
a slot through `tools.registry.instance.claim`, and the slot is torn down on every
exit path, including an exception, the same `finally` form
`tools/areas/exitreentry.py` and `tools/gui/livecheck.py` use.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import re
import sys
import threading
import time

TOOLS = pathlib.Path(__file__).resolve().parent.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap import actions as A  # noqa: E402
from automap.actions import _read, mode, program_counter  # noqa: E402
from automap.paths import tool_disks  # noqa: E402
from automap.target import ViceTarget  # noqa: E402
from tools.c64 import session as S  # noqa: E402
from tools.c64.session import parse_status  # noqa: E402
from tools.registry import scratch  # noqa: E402

DISKS: pathlib.Path | None = tool_disks()

CAVES, EAST = 13, 27
SLOT_RECORD, SLOT_ROSTER, SLOTS = 0x4D00, 0x8300, 8
#: `$6E1B`, masked to seven bits: `docs/163-dos-vm-address-map.md`'s area
#: byte, the same one `automap.actions.FastTravel.current_area` reads.
AREA_BYTE = 0x6E1B

#: The fixed screenshot names, one per checkpoint, saved under `--out`.
SHOTS = {"before": "1-before.png", "question": "2-question.png",
         "after_hop": "3-after-second-hop.png", "after_walk": "4-after-walk.png"}

#: Two steps in each of four directions. Outdoors those are compass digits
#: (north, east, south, west -- `tools.c64.session.COMPASS`); indoors a turn is
#: a move of its own, so `IIKIIKIIKII` goes forward twice, then turns three
#: times with two steps forward after each.
WALK_OUTDOORS = "11335577"
WALK_INDOORS = "IIKIIKIIKII"


def name(raw: bytes) -> str:
    """The first null-terminated run of *raw*, printable bytes as
    themselves and anything else as `.` -- `<empty>` for a zeroed slot."""
    if not raw or raw[0] == 0:
        return "<empty>"
    out = raw.split(b"\x00")[0]
    return "".join(chr(c) if 32 <= c < 127 else "." for c in out)


def party(sess) -> list[dict]:
    """The eight roster slots' name and status byte, read in one monitor
    session so the party cannot change mid-read."""
    rows = []
    with sess.mon(8) as m:
        for i in range(SLOTS):
            rec = m.read(SLOT_RECORD + i * 0x100, 0x100)
            ros = m.read(SLOT_ROSTER + i * 0x20, 0x20)
            rows.append({"slot": i, "name": name(rec[:16]), "status": ros[0]})
    return rows


def area_of(sess) -> int:
    with sess.mon(5) as m:
        return m.read(AREA_BYTE, 1)[0] & 0x7F


def has_member(rows: list[dict], substring: str) -> bool:
    """Whether any live roster row's name contains *substring*."""
    return any(substring in r["name"] for r in rows if r["name"] != "<empty>")


def verdict(before: list[dict], after: list[dict], area_before: int,
            area_after: int, from_area: int, to_area: int,
            member: str, two_hop: bool = False,
            second_hop_seconds: float | None = None) -> tuple[bool, str]:
    """The pass/fail judgement over four readings, with no monitor in it at
    all -- the part of this tool that can be proven right without a slot.

    `to_area` is the destination that was asked for, so a two-hop trip that
    stopped in the area its door leads to fails the second check rather than
    passing on the way through.

    `two_hop` says the trip had a pending second hop; it must then have been
    timed, so a run that reads the destination with no `second_hop_seconds`
    measured the wrong thing and fails rather than passing without a number.

    Four ways to fail, checked in the order a run would actually discover
    them: the save was not staged where the check assumes, the warp did not
    land, the named member was never in the party to begin with (a mistyped
    `--member`, not a finding), or -- the one #207 is about -- the member
    is still there, meaning the exit's own handler never ran.
    """
    if area_before != from_area:
        return False, f"the save is not in area {from_area}: read {area_before}"
    if area_after != to_area:
        return False, f"did not land in area {to_area}: read {area_after}"
    if two_hop and second_hop_seconds is None:
        return False, (f"area {to_area} was read but the second hop was never "
                        "timed, so this run measured nothing about it")
    if not has_member(before, member):
        return False, f"{member!r} was not in the party to begin with"
    if has_member(after, member):
        return False, (f"the handler did not drop {member!r} -- "
                        "the whole point of #207")
    return True, (f"the production FastTravel.run() ran the exit's own "
                  f"handler and dropped {member!r}")


def elapsed(start: float | None, end: float | None) -> float | None:
    """Seconds from *start* to *end*, rounded to a tenth; None when either
    moment never happened, so a missing measurement cannot read as zero."""
    if start is None or end is None:
        return None
    return round(end - start, 1)


def walk_verdict(steps: list[dict], sheet_opened: bool) -> tuple[bool, str]:
    """Whether the party is walkable after the trip, judged from the steps
    `walk_afterwards` recorded and with no monitor in it.

    A step that a wall stops is a fact about the map and is not a failure;
    what fails is a party whose square changed on none of its steps (a turn is
    not a move), a driver that
    pressed nothing, or a roster sheet that never came up -- each of which is
    what a wedged party looks like.
    """
    if not steps:
        return False, "no step was tried"
    rejected = [s for s in steps if s.get("stopped")]
    if rejected:
        return False, f"the driver rejected a step: {rejected[0]['stopped']}"
    walked = [s for s in steps if "move" in s]
    moved = sum(1 for s in walked
                if not s.get("interrupted")
                and s.get("before") is not None and s.get("after") is not None
                and s["after"] != s["before"])
    if not moved:
        return False, (f"the party did not move: its square did not change on "
                       f"any of {len(walked)} steps")
    if not sheet_opened:
        return False, "the character sheet did not open after the walk"
    return True, (f"the party changed square on {moved} of {len(walked)} "
                  "steps and the character sheet opened and closed")


def enable_debug_logging() -> None:
    """Send the automapper's own debug lines -- `FastTravel._idle_verdict`'s and
    `continue_pending`'s explanations of why they did nothing -- to stdout, the
    driver's log. Idempotent: a second call adds no second handler."""
    logger = logging.getLogger("wish.automap")
    logger.setLevel(logging.DEBUG)
    if not any(getattr(h, "_fasttravelrun", False) for h in logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler._fasttravelrun = True
        handler.setFormatter(logging.Formatter("  %(name)s: %(message)s"))
        logger.addHandler(handler)


def second_hop(ft, open_target, marks: dict | None = None,
               clock=time.monotonic):
    """One poll of a two-hop trip's second hop, the way the automapper's own
    poll makes it: `ft.continue_pending` through the real target.

    The target is opened for this one call and closed straight after, for the
    same reason `run` does it around `FastTravel.run`: VICE serves one monitor
    connection, and every `sess.mon()` call opens its own. `open_target` is
    required so that no caller falls back on the default monitor port, which
    is not where a pool slot's emulator listens.

    While a hop is pending, each poll prints what `continue_pending` decides
    on -- the raw area byte, the overlay mode and the program counter -- so a
    hop that never fires says which check rejected. `marks["through"]` is set
    to `clock()` on the first poll that reads the area the door leads to with the loader idle
    (bit 7 clear), before
    `continue_pending` can make the hop: the start of the second hop's own
    timing.
    """
    target = open_target()
    try:
        pending = ft.pending
        if pending is not None:
            raw = _read(target, AREA_BYTE, 1)
            print(f"  poll: $6E1B={raw.hex() if raw else None} "
                  f"mode={mode(target)} pc={program_counter(target)}",
                  flush=True)
            if (marks is not None and raw and "through" not in marks
                    and raw[0] == pending.through):
                marks["through"] = clock()
        return ft.continue_pending(target)
    finally:
        target.close()


#: The menus the driver knows how to answer: the words that must all be on row
#: 24, and the word to select. `YES`/`NO` is the exit handler's own question.
#: `LARGE SMALL LEAVE` is the wilderness square's arrival menu after a walk out
#: of the Kobold Caves; `LARGE` and `SMALL` walk the party back into the caves,
#: so only `LEAVE` keeps the trip going. Its entry here is the default pick,
#: and `choice_for`'s *arrival* replaces it. A row matching no entry is not
#: answered.
MENUS = ((("YES", "NO"), "YES"), (("LARGE", "SMALL", "LEAVE"), "LEAVE"))
ARRIVAL_CHOICES = ("LEAVE", "LARGE", "SMALL")


def choice_for(row: str, arrival: str = "LEAVE") -> str | None:
    """The word to select on the command bar *row*, or None when it is not a
    menu in `MENUS`. On the arrival menu that word is *arrival*."""
    words = row.split()
    for needed, pick in MENUS:
        if all(w in words for w in needed):
            return arrival if "LEAVE" in needed else pick
    return None


def answer_and_wait(sess, to_area: int, deadline_s: float = 60.0,
                    between=None, on_question=None, marks: dict | None = None,
                    clock=time.monotonic, arrival: str = "LEAVE",
                    land_after: str | None = None):
    """Answer whatever the exit's handler puts on row 24, the way a player
    would, until the area byte says the warp landed.

    Only the menus in `MENUS` are answered, each once; anything else times out
    rather than guessing at a menu this tool has never seen.

    `between`, when given, is called once a lap until it answers an `Outcome`
    -- a two-hop trip's `second_hop`. That outcome is returned at once when it
    is a failure (the trip gave up) and otherwise once the area byte lands.

    `on_question` is called once, when the game's `YES`/`NO` is up and before it
    is answered; the arrival menu does not call it. `marks["landed"]` is set to `clock()` at the moment the area
    byte reads `to_area`, which is the end of the second-hop timing.

    `arrival` is the word picked on the arrival menu. `land_after`, when given,
    is a choice that must have been answered before the area byte reading
    `to_area` counts as a landing: a trip that returns to the area it started
    in reads `to_area` before it has moved at all.
    """
    deadline = time.time() + deadline_s
    answered: set[str] = set()
    hop = None
    while time.time() < deadline:
        if between is not None and hop is None:
            hop = between()
            if hop is not None:
                print(f"  second hop: ok={hop.ok} message={hop.message}",
                      flush=True)
                if not hop.ok:
                    return hop
        s = sess.screen()
        row = s.row(24).strip() if s is not None else ""
        if row:
            print(f"  row 24: {row!r}", flush=True)
        pick = choice_for(row, arrival)
        if pick is not None and pick not in answered:
            if pick == "YES" and on_question is not None:
                on_question()
            sess.select_bar(pick, timeout=15)
            answered.add(pick)
            time.sleep(1.0)
            continue
        if area_of(sess) == to_area and (land_after is None
                                         or land_after in answered):
            if marks is not None:
                marks["landed"] = clock()
            return hop
        time.sleep(0.6)
    return hop


def watch_cancelled(ft, open_target, seconds: float, interval: float = 1.0,
                    clock=time.monotonic, sleep=time.sleep):
    """Poll a two-hop trip's second hop every *interval* seconds for *seconds*
    and return `(elapsed, message)` for every outcome it gives, which is none
    when the trip was cancelled silently."""
    start = clock()
    seen = []
    while clock() - start < seconds:
        outcome = second_hop(ft, open_target)
        if outcome is not None:
            seen.append((round(clock() - start, 1), outcome.message))
        sleep(interval)
    return seen


def returned_verdict(before: list[dict], after: list[dict], area_before: int,
                     area_after: int, from_area: int, member: str,
                     pending_after: bool, outcomes: list) -> tuple[bool, str]:
    """The judgement for a trip whose party came back to the area it started
    in: the handler ran, the party is back, and the trip was cancelled without
    a word. Fails on the first of those that does not hold."""
    if area_before != from_area:
        return False, f"the save is not in area {from_area}: read {area_before}"
    if area_after != from_area:
        return False, (f"the party did not come back to area {from_area}: "
                       f"read {area_after}")
    if not has_member(before, member):
        return False, f"{member!r} was not in the party to begin with"
    if has_member(after, member):
        return False, (f"the handler did not drop {member!r} -- "
                       "the exit's own handler never ran")
    if pending_after:
        return False, "the trip is still pending after the party came back"
    if outcomes:
        return False, (f"the trip said something after the party came back: "
                       f"{outcomes[0][1]!r}")
    return True, (f"the party went through, came back to area {from_area} and "
                  f"the trip was cancelled without a message")


def shoot(sess, out: pathlib.Path, key: str, shots: dict) -> None:
    """One checkpoint screenshot under *out*; `shots[key]` is the path, or
    None when the screenshot failed -- which never stops the run."""
    path = out / SHOTS[key]
    try:
        shots[key] = str(path) if sess.kbd.screenshot(str(path)) else None
    except Exception as e:                                # noqa: BLE001
        print(f"  screenshot {key} failed: {e}", flush=True)
        shots[key] = None


def row24(sess) -> str:
    """Row 24 of the screen, stripped; empty when there is no screen to read."""
    s = sess.screen()
    return s.row(24).strip() if s is not None else ""


def indoor_bar(row: str) -> bool:
    """Whether *row* is a bar the party rests on indoors: the world bar or the
    move sub-bar the game waits in after a step. The travel grid's direction
    prompt is not one."""
    return "ENCAMP" in row or S.MOVE_SUBBAR in row


#: The question the Kobold Caves put to a party that an arrival choice has
#: walked back onto the caves' exit square, and the answer that keeps it there:
#: `YES` walks it out again, so `NO` is what leaves it standing in the caves.
LEAVE_QUESTION = "DO YOU WANT TO LEAVE"
STAY = "NO"


def yes_no(row: str) -> bool:
    """Whether *row* is a `YES`/`NO` bar."""
    words = row.split()
    return "YES" in words and "NO" in words


def leave_question(sess) -> str | None:
    """The screen line holding `LEAVE_QUESTION`, stripped, or None when no
    line holds it."""
    screen = sess.screen()
    if screen is None:
        return None
    for line in screen.text().splitlines():
        if LEAVE_QUESTION in line:
            # `$` is the text reader's glyph for the message box's border.
            return line.strip().strip("$").strip()
    return None


def settle_world(sess, out: pathlib.Path, shots: dict,
                 rows: list | None = None, stay: bool = False,
                 answered: list | None = None) -> tuple[bool, str]:
    """Wait for the world's command bar before the walk, so the walk never
    starts on a disk prompt or a menu. On failure row 24 is recorded verbatim
    in the message and a screenshot is taken. Each distinct row 24 seen while
    waiting indoors is appended to *rows*.

    With *stay*, a `YES`/`NO` bar under `LEAVE_QUESTION` indoors is answered
    `STAY`, once, as a player who wants to stay would, and
    `{"question": ..., "answer": ...}` is appended to *answered*, with the
    answer None when `select_bar` did not report the word picked. Any other
    `YES`/`NO` question is left unanswered and fails the settle."""
    # A walked exit onto the travel grid lands on the direction prompt, which
    # `wait_for_world` never counts as the world and might press Return at;
    # `Session.outdoor_key` drives a step from it, so it is checked first and
    # again after the wait, in case the arrival settled there.
    # Indoors the settle is judged by row 24 through `indoor_bar`, so that
    # prompt, the stale travel-grid screen of a hop still loading, is rejected
    # there because it is not an indoor bar.
    # A failed read (None) is not the grid either, and the area byte is read
    # again after the wait, which is when a hop finishes loading.
    if sess.indoors() is True:
        # The move sub-bar is a resting state indoors, and `wait_for_world`
        # never counts it, so it is polled for through `settle_row`.
        accept = ((lambda r: indoor_bar(r) or yes_no(r)) if stay
                  else indoor_bar)
        row = settle_row(sess, 60, accept=accept, seen=rows)
        if stay and yes_no(row):
            question = leave_question(sess)
            if question is None:
                print(f"  question not recognised under row 24 {row!r}; "
                      "left unanswered", flush=True)
            else:
                print(f"  question: {question!r}; answering {STAY}",
                      flush=True)
                picked = sess.select_bar(STAY, timeout=15)
                if answered is not None:
                    answered.append({"question": question,
                                     "answer": STAY if picked else None})
                row = settle_row(sess, 60, accept=indoor_bar, seen=rows)
        if indoor_bar(row):
            print(f"  settled: row 24 {row!r}", flush=True)
            return True, ""
    else:
        if (sess.indoors() is False and S.OUTDOOR_PROMPT in row24(sess)) \
                or sess.wait_for_world(timeout=60):
            print(f"  settled: row 24 {row24(sess)!r}", flush=True)
            return True, ""
        row = row24(sess)
    if sess.indoors() is False and S.OUTDOOR_PROMPT in row:
        print(f"  settled: row 24 {row!r}", flush=True)
        return True, ""
    print(f"  not settled: row 24 {row!r}", flush=True)
    shoot(sess, out, "after_walk", shots)
    return False, f"the world's command bar never came up; row 24 reads {row!r}"


def recognised(row: str) -> bool:
    """Whether *row* is a bar the walk can drive from."""
    return ("ENCAMP" in row or S.MOVE_SUBBAR in row
            or S.OUTDOOR_PROMPT in row)


def settle_row(sess, timeout: float = 60.0, interval: float = 0.5,
               accept=None, seen: list | None = None) -> str:
    """Row 24 once *accept* (default `recognised`) takes it, or its last
    reading when *timeout* runs out. Each distinct reading is appended to
    *seen* when given.

    An empty row is a screen still being redrawn, as after a disk-side prompt
    is answered, so it is waited out without pressing anything. A row that
    says something else is handed to `Session.wait_for_world`, which answers
    disk and continue prompts. A fight bar is returned at once, because
    `wait_for_world` waits for a bar a fight never shows and would press Return
    at a prompt in the middle of one.
    """
    clock, sleep = time.monotonic, time.sleep
    accept = accept or recognised
    end = clock() + timeout
    row = row24(sess)
    while True:
        if seen is not None and row and row not in seen:
            seen.append(row)
        if accept(row) or clock() >= end or sess.in_combat():
            break
        if row:
            sess.wait_for_world(timeout=min(10.0, max(1.0, end - clock())))
        # Also after the wait: it returns at once when ENCAMP is elsewhere on
        # the screen while row 24 still says something else.
        sleep(interval)
        row = row24(sess)
    return row


RETRY_BUDGET = 12     # keys a walk may spend on retries, apart from its planned moves

TURN = {"J": -1, "K": 1}   # facing change of a turn key, in quarter turns


def _retry_groups(indoors: bool, move: str) -> list[list[tuple[str, str]]]:
    """The tries to make after a forward *move* that a wall stopped, each a list
    of `(key, kind)` with kind "turn", "step" or "undo"; [] for a turn, which
    is never retried.

    Indoors a try turns, steps once, and turns back if that step failed, so
    every failed try leaves the facing as it found it: left is J I (K); right
    is K I (J); behind is K K I (K K).  M is not used: docs/70 and session.py
    disagree about what it does.  Outdoors every compass digit is a step, so
    the tries are the other three digits.
    """
    if not indoors:
        return [[(d, "step")] for d in "1357" if d != move]
    if move != "I":
        return []
    return [[("J", "turn"), ("I", "step"), ("K", "undo")],
            [("K", "turn"), ("I", "step"), ("J", "undo")],
            [("K", "turn"), ("K", "turn"), ("I", "step"),
             ("K", "undo"), ("K", "undo")]]


def _is_step(indoors: bool, key: str) -> bool:
    """Whether *key* moves the party (a forward step or a compass digit), as
    opposed to a turn."""
    return key == "I" or not indoors


def where(sess, indoors: bool):
    """The party's square for the walk to compare. Indoors that is the status
    line, because `Session.square()` reads `$49C0`, which stays at the arrival
    square after a Fast Travel; outdoors the memory pair `square()` reads is
    live and the status line lags.

    Indoors the line is read here rather than through `Session.position()`,
    whose fallback when no line parses is a memory copy with a real-looking
    facing, and that copy is the stale square this exists to avoid. None means
    no line parsed in `position()`'s own twelve tries, and `walk_verdict` never
    counts a None as a move."""
    if not indoors:
        return sess.square()
    for _ in range(12):
        screen = sess.screen()
        if screen is not None:
            at = parse_status(screen.text())
            if at is not None:
                return at.x, at.y
        time.sleep(0.3)
    return None


#: An indoor status line with a facing and a time but no square, as the
#: Kobold Caves print it (`E 4:00`): an area that hides its map hides the
#: party's square too.
#: Matched against one screen row that ends after the minutes (a message box's
#: border glyph and blanks may follow), so a line still being drawn, such as
#: `N 12:00 1`, is not taken for one that hides its square.
RE_NO_SQUARE = re.compile(
    r"(?<![A-Z])[NESW](?![A-Z]) +\d+:\d\d[ $]*$")


def square_hidden(sess, tries: int = 12) -> bool:
    """Whether the indoor status line shows no square: True on the first read
    with a row that matches `RE_NO_SQUARE`, False on the first that `parse_status`
    reads a square from, and False when *tries* reads find neither."""
    for _ in range(tries):
        screen = sess.screen()
        if screen is not None:
            text = screen.text()
            if parse_status(text) is not None:
                return False
            if any(RE_NO_SQUARE.search(line) for line in text.splitlines()):
                return True
        time.sleep(0.3)
    return False


def fought(sess, steps: list[dict], row: str) -> bool:
    """Fight the fight the party is in, append `{"fight": ...}` to *steps*, and
    say whether the walk may go on. A `rejected` reason is recorded, and False
    returned, when the fight was lost, the world did not come back, or another
    fight is already on."""
    result = sess.fight(budget=300, tactic=S.Session.melee_turn)
    outcome = getattr(result, "outcome", str(result))
    back = bool(sess.wait_for_world())
    steps.append({"fight": outcome, "row": row, "world": back})
    print(f"  fight: {outcome} world={back}", flush=True)
    if outcome == S.LOST:
        steps[-1]["stopped"] = "the fight was lost"
    elif not back:
        steps[-1]["stopped"] = "the world did not come back after a fight"
    elif sess.in_combat():
        steps[-1]["stopped"] = "another fight began straight after a fight"
    return "stopped" not in steps[-1]


#: `ECL64`, the fight's script. PROBABLE: the game loads it into the `ECL`
#: slot of the loaded-files cache, which `AREA_BYTE` is, while it sets a fight
#: up, so a reading of 100 there would be a fight on its way and not an area
#: (`docs/140-loaded-files-cache.md`, and the `ECL64` row of the overlay
#: table in `docs/50-experiments.md`). A live read of `$6E1B` during a fight
#: load would confirm it.
COMBAT_ECL = 0x64

#: Seconds between the two readings `world_ready` must find identical.
READY_GAP = 1.0


def area_raw(sess) -> int | None:
    """`AREA_BYTE` with its reload bit, or None when the read failed."""
    try:
        with sess.mon(5) as m:
            return m.read(AREA_BYTE, 1)[0]
    except (OSError, S.MonitorError):
        return None


def world_ready(sess, timeout: float = 60.0,
                reads: list | None = None) -> tuple[str, int | None, str]:
    """Wait until the game takes keys again after a step or a fight.

    Returns `("combat", raw, row)` as soon as a fight is on, `("ready", raw,
    row)` once two readings `READY_GAP` apart agree on `AREA_BYTE` and the
    whole screen while row 24 is a bar the walk drives from, and `("timeout",
    raw, row)` with the last reading when *timeout* runs out. A reading with
    the reload bit set, or of `COMBAT_ECL` (PROBABLE, unconfirmed until a live
    read of `$6E1B` during a fight load), is a load and never ready: the
    command bar stays on screen while the fight loads, so row 24 alone
    cannot tell. Each distinct raw `AREA_BYTE` is appended to *reads*."""
    clock, sleep = time.monotonic, time.sleep
    end = clock() + timeout
    prior = None
    raw, row = None, ""
    while True:
        if sess.in_combat():
            return "combat", area_raw(sess), row24(sess)
        raw = area_raw(sess)
        screen = sess.screen()
        row = screen.row(24).strip() if screen is not None else ""
        if reads is not None and (not reads or reads[-1] != raw):
            reads.append(raw)
        loading = raw is None or raw & 0x80 or raw & 0x7F == COMBAT_ECL
        now = None if loading or screen is None else (raw, screen.text())
        if now is not None and now == prior and recognised(row):
            return "ready", raw, row
        if clock() >= end:
            return "timeout", raw, row
        prior = now
        sleep(READY_GAP)


def walk_afterwards(sess, timeout: float = 60.0,
                    stop_after_moves: int | None = None
                    ) -> tuple[list[dict], bool]:
    """A few steps in each direction, then the first character's sheet opened
    and closed -- the one action that is not a move. Returns every step's
    result and whether the sheet came up.

    With *stop_after_moves* the walk ends, and the sheet opens, after the step
    that makes that many steps change the square; every further step is a
    further chance of a random encounter, which the driver can only fight.

    A step that a wall stopped is retried from other directions
    (`_retry_groups`).  Its record describes the last attempt -- `move`, `ok`,
    `row` and `after` all come from it -- and a retried step also carries
    `planned`, the move the walk asked for, `attempts`, every key sent,
    `off_route` (a retry moved the party off the planned route, which ends the
    retries), `facing_restored`, and `capped` when the retry budget ended the walk.

    Row 24 is read before every step and stored in it. A fight is handed to
    `Session.fight` with `melee_turn` (the default tactic only passes, which
    never ends one) and recorded as `{"fight": ...}`. Any row that is neither
    the world bar, the move sub-bar nor the travel grid's direction prompt
    (walked with `Session.outdoor_key`, which sends the digit itself)
    stops the walk with a rejected step, because `walk_one` would press Return at it and pick a menu's first
    option.

    A rejected step ends the walk at once; an attempt carries `screens`, the rows
    `Session.walk_one` kept for its key, whenever it kept any.

    Indoors, `before` and `after` come from the status line and
    `shadow_before` and `shadow_after` from `square()`. In an area whose status
    line shows no square (`square_hidden`) the walk is judged from memory
    instead, and each step carries `"square_from": "memory"`; the choice is
    made once, so no step compares a status-line square with a memory one.
    There:

    * `before` and `after` are the live square, `Session.steady_triple`
      (`$C04B`), because `square()` (`$49C0`) keeps the old square while the
      party steps on the move sub-bar;
    * each key is sent once (`walk_one(key, tries=1)`), and whether it took is
      read from the live triple -- the square for a step, the facing for a
      turn -- because `walk_one` verifies a key by the status line's square
      and finds none; `ok` is that judgement, and the attempt also records
      `walk_one`, what `walk_one` itself returned, without using it;
    * before every key and before the sheet the walk waits for `world_ready`,
      so no key goes into a fight or an area still loading under a stale
      command bar; a game that never settles ends the walk with a rejected step;
    * each step carries `area_before`, `area_after` (read once the game has
      settled or a fight is on), `area_reads` (every raw `AREA_BYTE` seen
      while waiting) and `fight_after`. A step after which the area changed, a
      fight began or the game did not settle is marked `interrupted` and
      `walk_verdict` does not count it as a move. A reading taken during a
      load is waited out, not compared. Reading `COMBAT_ECL` as a fight
      loading is PROBABLE until a live read of `$6E1B` during a fight load
      confirms it.

    Called before teardown, because the session is gone once `run` returns.
    """
    indoors = sess.indoors()
    if indoors is None:
        return [], False
    from_memory = bool(indoors) and square_hidden(sess)
    if from_memory:
        print("  the status line shows no square; the walk reads $C04B",
              flush=True)

    def triple():
        return sess.steady_triple() if from_memory else None

    def at():
        if not from_memory:
            return where(sess, indoors)
        now = triple()
        return None if now is None else (now[0], now[1])

    steps: list[dict] = []

    def unsettled(state: str, raw, row: str) -> list[dict]:
        here = at()
        steps.append({"move": "wait", "ok": False, "row": row,
                      "before": here, "after": here,
                      "stopped": f"the game never settled: $6E1B reads "
                                 f"{raw} and row 24 {row!r}"})
        print(f"  walk: the game never settled ($6E1B={raw}, row 24 "
              f"{row!r})", flush=True)
        return steps

    def ready_or_fought(row: str) -> tuple[bool, str]:
        """In an area judged from memory, wait for `world_ready` and fight a
        fight it finds; True with row 24 once keys may go, False once a
        rejected step has been recorded."""
        if not from_memory:
            return True, row
        for _ in range(2):
            state, raw, row = world_ready(sess, timeout)
            if state == "ready":
                return True, row
            if state != "combat":
                unsettled(state, raw, row)
                return False, row
            if not fought(sess, steps, row):
                return False, row
        state, raw, row = world_ready(sess, timeout)
        if state == "ready":
            return True, row
        if state == "combat":
            here = at()
            steps.append({"move": "wait", "ok": False, "row": row,
                          "before": here, "after": here,
                          "stopped": "a fight is still going after two "
                                     "fights were fought"})
            print("  walk: a fight is still going after two fights",
                  flush=True)
        else:
            unsettled(state, raw, row)
        return False, row

    retry_used = moved = 0
    for move in (WALK_INDOORS if indoors else WALK_OUTDOORS):
        row = settle_row(sess, timeout)
        if sess.in_combat():
            if not fought(sess, steps, row):
                return steps, False
            row = settle_row(sess, timeout)
        go, row = ready_or_fought(row)
        if not go:
            return steps, False
        if not recognised(row):
            here = at()
            steps.append({"move": move, "ok": False, "row": row,
                          "before": here, "after": here,
                          "stopped": f"row 24 is not the world bar, the move "
                                     f"sub-bar or the direction prompt: {row!r}"})
            print(f"  walk {move}: stopped on row 24 {row!r}", flush=True)
            return steps, False
        before = at()
        shadow_before = sess.square()
        area_before = area_of(sess) if from_memory else None
        attempts: list[dict] = []
        facing = 0          # quarter turns away from the facing the step began with
        off_route = capped = False
        rejected = None
        first = [(move, "step" if _is_step(indoors, move) else "turn")]
        groups = [first] + _retry_groups(indoors, move)
        done = False
        for gi, group in enumerate(groups):
            if gi and retry_used + len(group) > RETRY_BUDGET:
                capped = True     # a try cut short would leave the facing turned
                break
            for key, kind in group:
                if attempts:
                    row = settle_row(sess, timeout)
                    if not sess.in_combat() and recognised(row) and from_memory:
                        state, _, row = world_ready(sess, timeout)
                        if state != "ready":
                            done = True   # the outer loop answers a fight or the stall
                            break
                    if sess.in_combat() or not recognised(row):
                        done = True   # the outer loop answers a fight; a prompt ends the walk
                        break
                if from_memory:
                    start3 = triple()
                    start = None if start3 is None else start3[:2]
                    verdict = sess.walk_one(key, tries=1)
                    end3 = triple()
                    part = slice(0, 2) if kind == "step" else slice(2, 3)
                    ok = (start3 is not None and end3 is not None
                          and end3[part] != start3[part])
                    after = None if end3 is None else end3[:2]
                    walk_one_said = bool(verdict)
                else:
                    walk_one_said = None
                    start = at()
                    ok = bool(sess.walk_one(key))
                    after = at()
                attempts.append({"move": key, "ok": ok, "row": row,
                                 "before": start, "after": after})
                if walk_one_said is not None:
                    attempts[-1]["walk_one"] = walk_one_said
                screens = getattr(sess, "walk_screens", None)
                if screens is not None:
                    attempts[-1]["screens"] = screens
                stop_screen = getattr(sess, "walk_stop_screen", None)
                if stop_screen is not None:
                    attempts[-1]["stop_screen"] = stop_screen
                if gi:
                    retry_used += 1
                rejected = getattr(sess, "walk_stopped", None)
                if rejected:
                    done = True
                    break
                if kind == "step":
                    if ok:
                        off_route = gi > 0
                        done = True
                        break
                elif not ok:
                    done = True    # a turn that did not take ends the retries
                    break
                else:
                    facing += TURN.get(key, 0)
            if done:
                break
        last = attempts[-1]
        step = {"move": last["move"], "ok": last["ok"], "row": last["row"],
                "before": before, "after": last["after"], "stopped": rejected,
                "shadow_before": shadow_before, "shadow_after": sess.square()}
        for key in ("screens", "stop_screen", "walk_one"):
            if key in last:
                step[key] = last[key]
        if len(attempts) > 1:
            # The last key may be a turn that worked, which must not read as a
            # step that moved the party.
            step["ok"] = any(a["ok"] for a in attempts
                             if _is_step(indoors, a["move"]))
            step["planned"] = move
            step["attempts"] = attempts
            step["off_route"] = off_route
            step["facing_restored"] = facing % 4 == 0
        if capped:
            step["capped"] = True
        if from_memory:
            reads: list = []
            state, _, _ = world_ready(sess, timeout, reads)
            timed_out = state == "timeout"
            step["square_from"] = "memory"
            step["area_before"] = area_before
            step["area_after"] = area_of(sess)
            step["area_reads"] = reads
            step["fight_after"] = state == "combat" or bool(sess.in_combat())
            if (step["area_after"] != area_before or step["fight_after"]
                    or timed_out):
                step["interrupted"] = True
        steps.append(step)
        print(f"  walk {last['move']}: ok={step['ok']} {before} -> {step['after']}"
              f" ({len(attempts)} attempt(s))", flush=True)
        if rejected:
            return steps, False
        if capped:
            break
        if step["before"] is not None and step["after"] is not None \
                and step["before"] != step["after"] \
                and not step.get("interrupted"):
            moved += 1
            if stop_after_moves is not None and moved >= stop_after_moves:
                break
    # A step can end on a prompt without `walk_stopped` being set, and the
    # sheet's keys must not be pressed into it.
    row = settle_row(sess, timeout)
    if sess.in_combat():
        # The walk's last step can start a fight, which the loop above only
        # answers at the start of the next step; `VIEW` pressed into it
        # opens the fight's own sheet rather than the world's.
        if not fought(sess, steps, row):
            return steps, False
        row = settle_row(sess, timeout)
    if steps and not sess.in_combat():
        go, row = ready_or_fought(row)
        if not go:
            return steps, False
    if steps and not sess.in_combat() and not recognised(row):
        here = at()
        steps.append({"move": "sheet", "ok": False, "row": row,
                      "before": here, "after": here,
                      "stopped": f"row 24 is not the world bar, the move "
                                 f"sub-bar or the direction prompt: {row!r}"})
        print(f"  sheet: stopped on row 24 {row!r}", flush=True)
        return steps, False
    sheet = sess.character_sheet(0)
    return steps, bool(sheet)


def capture_failure(sess, out: pathlib.Path,
                    screenshot_timeout: float = 20.0) -> str:
    """Write every screen row to `failure-screen.txt` and a screenshot to
    `failure.png` under *out*, before teardown destroys the evidence. Returns
    a sentence saying where they went; never raises, because it runs while
    another failure is already in flight. The screenshot is a subprocess with
    no timeout of its own, so it runs in a thread and is abandoned after
    *screenshot_timeout* seconds."""
    said = []
    if sess is None:
        return "no session had started, so no screen was captured"
    try:
        screen = sess.screen()
        if screen is None:
            text = "(no readable text screen: a bitmap, or the monitor did not answer)\n"
        else:
            text = "\n".join(f"{r:2d} |{screen.row(r)}|" for r in range(25)) + "\n"
        path = out / "failure-screen.txt"
        path.write_text(text)
        said.append(f"screen text in {path}")
    except Exception as e:                                # noqa: BLE001
        said.append(f"screen text unavailable ({e!r})")
    try:
        shot = out / "failure.png"
        taken: list = []
        worker = threading.Thread(
            target=lambda: taken.append(sess.kbd.screenshot(str(shot))),
            daemon=True)
        worker.start()
        worker.join(screenshot_timeout)
        if worker.is_alive():
            said.append(f"screenshot timed out after {screenshot_timeout}s")
        else:
            said.append(f"screenshot in {shot}" if taken and taken[0]
                        else "no screenshot taken")
    except Exception as e:                                # noqa: BLE001
        said.append(f"screenshot unavailable ({e!r})")
    return "; ".join(said)


def disks_of(args) -> pathlib.Path | None:
    """The disk folder to stage from: `--disks` when given, else the default."""
    return pathlib.Path(args.disks) if args.disks else DISKS


def walk_after(sess, out: pathlib.Path, shots: dict, result: dict,
               stay: bool = False) -> int:
    """The walk and sheet check after a passed trip, recorded into *result*;
    0 when the party walks. *stay* is `settle_world`'s: an arrival choice
    leaves the party on the exit square, under the question it asks."""
    # The walk is judged on its own: the trip's verdict above is already
    # final, and a party that cannot walk afterwards is a second finding.
    settle_rows: list[str] = []
    answered: list[dict] = []
    try:
        settled, why = settle_world(sess, out, shots, settle_rows,
                                    stay=stay, answered=answered)
        if settled:
            steps, sheet = walk_afterwards(sess, stop_after_moves=1)
            walk_ok, walk_message = walk_verdict(steps, sheet)
        else:
            steps, sheet, walk_ok, walk_message = [], False, False, why
    except Exception as e:                             # noqa: BLE001
        steps, sheet = [], False
        walk_ok, walk_message = False, f"the walk raised {e!r}"
    if "after_walk" not in shots:
        shoot(sess, out, "after_walk", shots)
    result.update({"walk_ok": walk_ok, "walk_message": walk_message,
                   "walk": steps, "sheet_opened": sheet,
                   "settle_rows": settle_rows, "screenshots": shots})
    if stay:
        result["settle_answers"] = answered
    if any(s.get("square_from") == "memory" for s in steps):
        result["memory_square"] = (
            "PROBABLE: the walk read the square from `$C04B` because the "
            "status line shows none and `$49C0` keeps the arrival square; "
            "that `$C04B` changes only on a real step awaits a live control")
    print(("PASS: walk: " if walk_ok else "FAIL: walk: ") + walk_message,
          flush=True)
    return 0 if walk_ok else 1


def run(args) -> int:
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    disks = disks_of(args)
    slot = S.claim_slot(args.slot, "issue207 fasttravelrun.py")
    print(f"slot {slot.n} display {slot.display}", flush=True)
    sess = None
    target = None
    result = {"ok": False, "message": "did not reach a verdict"}
    before = area_before = None
    shots: dict = {}
    marks: dict = {}
    started = time.monotonic()
    try:
        boot = S.stage_disks(slot, disks)
        # The save usually lives outside the disk directory -- the default
        # is the `npc-party-save` registry entry's file -- so it is staged by hand rather
        # than through `stage_disks`'s own `save` argument, which looks for
        # it alongside the eight sides.
        S.stage_writable(pathlib.Path(args.save).expanduser(),
                          pathlib.Path(slot.dir) / "SIDE0.D64")
        for p in pathlib.Path(slot.dir).glob("*.D64"):
            os.chmod(p, 0o644)
        sess = S.Session(boot, slot=slot)
        if not sess.boot():
            raise RuntimeError("boot failed")
        if not sess.load_save():
            raise RuntimeError("save not accepted")
        if not sess.select_row("BEGIN ADVENTURING"):
            raise RuntimeError("BEGIN ADVENTURING failed")
        if not sess.wait_for_world(timeout=args.arrive):
            raise RuntimeError("no command bar after BEGIN ADVENTURING")
        sess.settle(4)

        before = party(sess)
        area_before = area_of(sess)
        print(f"area before: {area_before}", flush=True)
        print("party before:",
              [r for r in before if r["name"] != "<empty>"], flush=True)

        shoot(sess, out, "before", shots)
        target = ViceTarget(port=sess.mon_port)
        ft = A.FastTravel()
        marks["run_start"] = time.monotonic()
        try:
            # `ViceTarget` holds one persistent monitor connection and VICE
            # serves exactly one, so it is opened only for the one call
            # that needs it and closed straight after -- every `sess.mon()`
            # call above and below opens and closes its own.
            outcome = ft.run(target, area=A.area_by_id(args.to_area))
        finally:
            target.close()
            target = None
        marks["run_returned"] = time.monotonic()
        print(f"run(): ok={outcome.ok} message={outcome.message}", flush=True)
        two_hop = ft.pending is not None
        if not outcome.ok:
            # The console has already printed both of these, so the file a
            # reader parses afterwards should carry them too.
            result = {"ok": False, "message": outcome.message,
                      "before": before, "area_before": area_before,
                      "screenshots": shots}
            return 1

        # A two-hop trip has walked the party out through the area's one door
        # and is waiting on the poll to make its second hop, so this loop is
        # that poll.
        choice = getattr(args, "arrival_choice", "LEAVE")
        if choice != "LEAVE":
            # LARGE and SMALL take the party back into the starting area, so
            # the wait is for that return and the trip's own outcomes are
            # watched for as long as the deadline plus a margin.
            hop = answer_and_wait(
                sess, args.from_area, deadline_s=args.answer_timeout,
                between=(lambda: second_hop(
                    ft, lambda: ViceTarget(port=sess.mon_port), marks)),
                on_question=lambda: shoot(sess, out, "question", shots),
                marks=marks, arrival=choice, land_after=choice)
            sess.settle(6)
            shoot(sess, out, "after_hop", shots)
            after = party(sess)
            watch_seconds = A.SECOND_HOP_SECONDS + 15
            outcomes = watch_cancelled(
                ft, lambda: ViceTarget(port=sess.mon_port), watch_seconds)
            area_after = area_of(sess)
            if hop is not None:
                outcomes.insert(0, (0.0, hop.message))
            ok, message = returned_verdict(
                before, after, area_before, area_after, args.from_area,
                args.member, ft.pending is not None, outcomes)
            result = {"ok": ok, "message": message, "before": before,
                      "after": after, "area_before": area_before,
                      "area_after": area_after, "screenshots": shots,
                      "arrival_choice": choice,
                      "pending_after": ft.pending is not None,
                      "outcomes_after": outcomes,
                      "watch_seconds": watch_seconds}
            print(("PASS: " if ok else "FAIL: ") + message, flush=True)
            if not ok:
                return 1
            return walk_after(sess, out, shots, result, stay=True)
        hop = answer_and_wait(
            sess, args.to_area, deadline_s=args.answer_timeout,
            between=(lambda: second_hop(
                ft, lambda: ViceTarget(port=sess.mon_port),
                marks)) if two_hop else None,
            on_question=lambda: shoot(sess, out, "question", shots),
            marks=marks)
        second_hop_seconds = (elapsed(marks.get("through"),
                                      marks.get("landed")) if two_hop else None)
        total_seconds = elapsed(started, marks.get("landed"))
        timing = {"second_hop_seconds": second_hop_seconds,
                  "total_seconds": total_seconds,
                  "first_hop_seconds": elapsed(marks["run_start"],
                                               marks["run_returned"]),
                  # The machine's share of the click-to-area-byte-leaves span.
                  "leave_seconds": elapsed(marks.get("run_returned"),
                                           marks.get("through"))}
        print(f"second_hop_seconds={second_hop_seconds} "
              f"total_seconds={total_seconds}", flush=True)
        if hop is not None and not hop.ok:
            result = {"ok": False, "message": hop.message,
                      "before": before, "area_before": area_before,
                      "screenshots": shots, **timing}
            return 1
        sess.settle(6)
        shoot(sess, out, "after_hop", shots)

        after = party(sess)
        area_after = area_of(sess)
        print(f"area after: {area_after}", flush=True)
        print("party after:",
              [r for r in after if r["name"] != "<empty>"], flush=True)

        ok, message = verdict(before, after, area_before, area_after,
                               args.from_area, args.to_area, args.member,
                               two_hop=two_hop,
                               second_hop_seconds=second_hop_seconds)
        result = {"ok": ok, "message": message, "before": before,
                  "after": after, "area_before": area_before,
                  "area_after": area_after, "screenshots": shots, **timing}
        print(("PASS: " if ok else "FAIL: ") + message, flush=True)
        if not ok:
            return 1

        return walk_after(sess, out, shots, result)
    except Exception as e:                                # noqa: BLE001
        result.update({"ok": False,
                       "message": f"{e}; {capture_failure(sess, out)}",
                       "screenshots": shots})
        if before is not None:
            result.update({"before": before, "area_before": area_before})
        raise
    finally:
        # A result that cannot be written must not stop the teardown below, or
        # the emulator slot leaks.
        try:
            (out / "result.json").write_text(json.dumps(result, indent=1))
        except Exception as e:                           # noqa: BLE001
            print(f"  result.json failed: {e}", flush=True)
        if target is not None:
            try:
                target.close()
            except Exception as e:                       # noqa: BLE001
                print(f"target close failed: {e}", flush=True)
        for what, fn in (("session", sess.terminate if sess else None),
                         ("slot teardown", slot.teardown),
                         ("slot release", slot.release)):
            if fn is None:
                continue
            try:
                fn()
            except Exception as e:                        # noqa: BLE001
                print(f"  {what} failed: {e}", flush=True)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--disks", default=DISKS,
                    help="the game disk directory ($POR_DISKS if unset)")
    p.add_argument("--save", default=str(S.npc_party_save()),
                    help="the save disk to load, staged in as SIDE0.D64")
    p.add_argument("--out", default=str(scratch.cache_dir("fasttravelrun", "live")))
    p.add_argument("--slot", type=int, default=None)
    p.add_argument("--from-area", type=int, default=CAVES)
    p.add_argument("--to-area", type=int, default=EAST)
    p.add_argument("--member", default="FATIMA")
    p.add_argument("--arrive", type=float, default=240.0,
                    help="seconds to wait for the command bar after "
                         "BEGIN ADVENTURING")
    p.add_argument("--answer-timeout", type=float, default=60.0,
                    help="seconds to wait for the handler's own prompt "
                         "and the warp to land")
    p.add_argument("--arrival-choice", choices=ARRIVAL_CHOICES,
                   default="LEAVE",
                   help="the pick on the two-hop trip's arrival menu; LARGE "
                        "and SMALL return the party to the starting area, and "
                        "the run then checks the trip was cancelled silently")
    args = p.parse_args(argv)
    enable_debug_logging()
    if disks_of(args) is None:
        raise SystemExit("No game disks found. Set $POR_DISKS.")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
