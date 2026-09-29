#!/usr/bin/env python3
"""Boot the generated test party in VICE and read all six sheets off the screen.

`docs/119-test-party.md` §6's third gate, and the only one that is evidence
about the game: `tools/suite/testparty.py` builds a party out of our own tables, and
a test that reads those bytes back through the same tables passes whether or
not the game agrees.  This asks the C64 instead.  The name, class, level, hit
points, armour class and THAC0 come back through the game's own character-sheet
routine and its own charset, which shares nothing with `goldbox/layout.py`.

    tools/suite/testpartyrun.py --disk path/to/TESTPARTY.D64

**Nothing is written to the player's disks.**  `--disk` is a copy
`tools/suite/testparty.py` already made; `tools/c64/session.stage_disks` copies the eight
sides and that save into the pool slot's own directory, and `Session.attach`
refuses any path outside it.  `POR_HEADLESS` is the slot's default, so no
window lands on the desktop.

Every event goes to `run.jsonl` as it happens rather than into a summary a
killed run never reaches, and each sheet is photographed while it is up --
which is the only moment it can be, since `Session.character_sheet` leaves the
sheet before it returns.

**Interrupt this with SIGINT and not SIGTERM**, so the `finally` gets to free
the slot.

`--full` adds the four remaining `#10 (Finish the high-level test party)`
questions the 2026-09-09T03:00:20Z comment named as sharing one boot:

    tools/suite/testpartyrun.py --disk path/to/TESTPARTY-ARMED.D64 --full \\
        --out DIR

1. the six sheets (as above), now armed;
2. `REMOVE CHARACTER FROM PARTY` on BULWARK, from the party menu, before
   `BEGIN ADVENTURING` -- the file the game writes is the `0x119` evidence,
   and he is re-added with `ADD CHARACTER TO PARTY` so the world portion still
   has all six (`docs/121-silver-blades.md` names the same two commands on
   the sibling engine; the party menu cannot be reached again once
   adventuring has begun, so this has to happen first);
3. un-ready then re-ready PILFER's `LEATHER ARMOR +4`, and ready then
   un-ready BULWARK's `TWO-HANDED SWORD +1 +3 VS UNDEAD`, each read at
   `$8300 + slot * 0x20` for 32 bytes before and after
   (`goldbox.savegame.RosterBlock`, `tools/c64/traitask.py`'s own item-list
   driving);
4. walk until something ambushes the party and screenshot the fight, which is
   the only way to see the icons `tools/suite/testparty.py --disk` wrote
   actually drawn; the shot waits for a party member's command bar.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap.paths import tool_disks  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.savegame import SLOT_AREA_BASE, SLOT_STRIDE  # noqa: E402
from tools.areas import geowalk  # noqa: E402
from tools.c64 import savecheck  # noqa: E402
from tools.c64 import session as S  # noqa: E402
from tools.c64.c64addprobe import answer as answer_yn  # noqa: E402
from tools.c64.c64nametable import character_files  # noqa: E402
from tools.c64.hallmenu import area as resident_area  # noqa: E402
from tools.c64.route_pool import leave_items, open_items, toggle_item  # noqa: E402
from tools.c64.traitask import ROSTER_STRIDE, SAVE1_LOAD  # noqa: E402
from tools.pool_of_radiance import dirtenicon  # noqa: E402
from tools.registry import scratch  # noqa: E402

DISKS: pathlib.Path | None = tool_disks()

#: Pool of Radiance's own prefix byte for a parked character's filename
#: (`tools/c64/c64nametable.py`'s `PREFIX`).
POR_PREFIX = 0x01


#: The Slums' area number, and the New Phlan square whose step off the west
#: edge (`ECL00` entry 0) puts the party at `SLUMS_ENTRY` in it.
SLUMS_AREA = 20
NEW_PHLAN_EXIT = (0, 4)
SLUMS_ENTRY = (15, 4)
#: The Slums squares a route to a fight may step on: unscripted (0), or the
#: one text square (4).  Any other id runs a script that can menu or fight.
SLUMS_PLAIN_IDS = (0, 4)


class Log:
    """One JSON line per event, written as it happens."""

    def __init__(self, out: pathlib.Path, quiet: bool = False) -> None:
        out.mkdir(parents=True, exist_ok=True)
        self.dir = out
        self.file = open(out / "run.jsonl", "w")
        self.quiet = quiet

    def emit(self, kind: str, **what) -> None:
        self.file.write(json.dumps({"t": round(time.time(), 3),
                                    "event": kind, **what}) + "\n")
        self.file.flush()

    def say(self, line: str) -> None:
        if not self.quiet:
            print(line, flush=True)

    def close(self) -> None:
        self.file.close()


# -- the four extra questions -------------------------------------------------

def dump(sess, out: pathlib.Path, log: Log, tag: str) -> None:
    """A screenshot and the screen text, named for the step that made it."""
    s = sess.screen()
    rows = [] if s is None else [r.rstrip() for r in s.rows()]
    log.emit("screen", tag=tag, rows=rows)
    sess.kbd.screenshot(str(out / f"{tag}.png"))


def remove_and_readd(sess, log: Log, out: pathlib.Path, name: str) -> bytes | None:
    """`REMOVE CHARACTER FROM PARTY` on `name`, keep the file the game wrote,
    then `ADD CHARACTER TO PARTY` to put him straight back.

    **This has to happen before `BEGIN ADVENTURING`.**  The party menu that
    offers both commands is the one `LOAD SAVED GAME` returns to; once the
    party has set out there is no route back to it short of a fresh load, so
    this is the one of the four questions that cannot share the *world*
    portion of the boot, only the disk and the party.

    Returns the exported `.CHR` bytes (the file `\\x01BULWARK` on the C64,
    `tools/c64/c64nametable.py`'s `PREFIX` for Pool of Radiance), or None if the
    remove never produced one.
    """
    dump(sess, out, log, "party-menu")
    if not sess.select_row("REMOVE CHARACTER FROM PARTY", timeout=25.0):
        log.say("  REMOVE CHARACTER FROM PARTY not found on the party menu")
        return None
    sess.settle(3)
    dump(sess, out, log, "remove-list")
    if not sess.select_row(name, timeout=25.0):
        log.say(f"  {name} not found on the remove list")
        return None
    sess.settle(3)
    dump(sess, out, log, f"asked-{name}")
    # NO keeps the disk that is already in the drive; YES would format a
    # fresh one, which is not the disk this run staged.
    answer_yn(sess, "NO")
    sess.settle(4)
    dump(sess, out, log, f"removed-{name}")

    disk = D64.open(sess.save_disk)
    files = character_files(disk, POR_PREFIX)
    raw = None
    if name in files:
        for entry in disk.iter_directory():
            if entry.name.decode("latin1").rstrip("\xa0 ")[1:] == name:
                raw = disk.read_file(entry)
                break
    log.emit("removed", name=name, parked_files=files, exported=raw is not None)
    log.say(f"  parked files after remove: {files}; exported {name}: "
            f"{raw is not None}")

    if not sess.select_row("EXIT", timeout=15.0):
        log.say("  EXIT off the remove list did not take")
    sess.settle(3)
    dump(sess, out, log, "after-remove-exit")

    if not sess.select_row("ADD CHARACTER TO PARTY", timeout=25.0):
        log.say("  ADD CHARACTER TO PARTY not found on the party menu")
        return raw
    sess.settle(4)
    dump(sess, out, log, "add-bar")
    # The bar offers a source game each add list is read from -- Pool of
    # Radiance keeps no such choice; if one is on row 24 it is answered by
    # whatever word is not EXIT.
    s = sess.screen()
    bar = "" if s is None else s.row(24).strip()
    if bar and "EXIT" in bar and bar != "EXIT":
        word = next((w for w in bar.split() if w != "EXIT"), None)
        if word:
            sess.select_bar(word, timeout=15.0)
            sess.settle(3)
    dump(sess, out, log, "add-list")
    if not sess.select_row(name, timeout=25.0):
        log.say(f"  {name} not offered on the add list")
        return raw
    sess.settle(3)
    dump(sess, out, log, f"asked-add-{name}")
    answer_yn(sess, "NO")
    sess.settle(4)
    dump(sess, out, log, f"added-{name}")
    if not sess.select_row("EXIT", timeout=15.0):
        log.say("  EXIT off the party menu did not take")
    log.say(f"  re-added {name}")
    return raw


def roster_bytes(sess, slot_index: int) -> bytes:
    """The 32-byte roster block at `$8300 + slot_index * 0x20`."""
    with sess.mon(8) as m:
        raw = m.read(SAVE1_LOAD + slot_index * ROSTER_STRIDE, ROSTER_STRIDE)
        m.resume()
    return raw


def slot_index_for(sess, name: str) -> int | None:
    """Which save slot (0-7) holds `name`, read live off `SAVEDGAME0`.

    Independent of the party panel's marching order, and independent of
    whatever `REMOVE`/`ADD CHARACTER` did to the slot layout -- this reads the
    name each slot's own record stores.
    """
    with sess.mon(8) as m:
        raw = m.read(SLOT_AREA_BASE, SLOT_STRIDE * 8)
        m.resume()
    for i in range(8):
        chunk = raw[i * SLOT_STRIDE:i * SLOT_STRIDE + 16]
        stored = chunk.split(b"\0", 1)[0].decode("ascii", "replace").strip()
        if stored == name:
            return i
    return None


def item_toggle_pair(sess, log: Log, out: pathlib.Path, name: str,
                     label: str, tag: str,
                     sequence: "list[str] | None" = None) -> list[dict]:
    """Toggle READY for `name`, reading the roster block at
    `$8300 + slot * 0x20` before and after each press.

    `sequence` names one label per press, in order; the default is `label`
    twice, which leaves that item's readied state as it started -- an
    un-ready/re-ready pair for something already readied, a ready/un-ready
    pair for something that was not.  A longer sequence is for a character
    whose target item cannot be readied on its own, such as a two-handed
    weapon while a shield is already worn: un-ready the shield, ready the
    weapon, then reverse both, and every step is still a before/after roster
    read rather than an assumption about why the direct toggle refused.
    """
    diffs: list[dict] = []
    steps = sequence or [label, label]
    slot = slot_index_for(sess, name)
    if slot is None:
        log.say(f"  {name} not found in the live roster; cannot toggle {label}")
        return diffs
    # A screenshot of whatever the game is showing right before this tries
    # to put the party-panel highlight on `name` -- diagnostic only, no keys
    # sent, so a failure below can be read back rather than guessed at.
    dump(sess, out, log, f"{tag}-precheck")
    # `leave_items`'s last `EXIT` targets camp's own bar to leave camp
    # entirely, and after one character's item list that bar reads
    # `ENCAMP:SAVE VIEW MAGIC REST ALTER EXIT` -- **camp's own command bar**,
    # a compound word exactly like the sheet's own `VIEW:ITEMS`, not the
    # plain world bar `MOVE VIEW CAST AREA ENCAMP SEARCH LOOK`.  Pool of
    # Radiance was measured on 2026-09-16 to leave the game sitting there
    # rather than back on the world, so the next `open_items` call reads
    # `ENCAMP` in that compound word, presses it, and opens the wrong menu.
    # Leaving by name rather than assuming the last call already did.
    s = sess.screen()
    if s is not None and s.row(24).strip().startswith("ENCAMP:"):
        log.say("  still on camp's own bar; leaving by EXIT before "
                f"opening {name}'s items")
        sess.select_bar("EXIT", timeout=10)
        sess.settle(2)
        dump(sess, out, log, f"{tag}-left-camp")
    opened = open_items(sess, log, name, steps[0], tag)
    if not opened:
        # One retry, after a longer settle: `panel_index` reads a live
        # screenshot, and the world panel has come back not-yet-redrawn
        # often enough in this run that a second try costs little against
        # losing the whole measurement to one slow frame.
        dump(sess, out, log, f"{tag}-open-failed-1")
        sess.settle(4)
        opened = open_items(sess, log, name, steps[0], tag)
    if not opened:
        dump(sess, out, log, f"{tag}-open-failed-2")
        log.say(f"  could not open the item list for {name}")
        return diffs
    for n, step_label in enumerate(steps):
        before = roster_bytes(sess, slot)
        ok = toggle_item(sess, log, step_label, f"{tag}{n}")
        sess.settle(1)
        after = roster_bytes(sess, slot)
        diff = [{"offset": f"0x{i:02X}", "was": b, "now": a}
                for i, (b, a) in enumerate(zip(before, after)) if b != a]
        rec = {"name": name, "label": step_label, "n": n, "pressed": ok,
              "slot": slot, "before": before.hex(), "after": after.hex(),
              "diff": diff}
        diffs.append(rec)
        log.emit("toggle", **rec)
        log.say(f"  {name} {step_label} toggle {n}: pressed={ok} diff={diff}")
    leave_items(sess, log)
    sess.settle(1)
    return diffs


def slums_avoid(slums, blocked=()):
    """The Slums squares a route keeps off: every id outside
    `SLUMS_PLAIN_IDS`, and any square already found blocked this walk."""
    return {(x, y) for x in range(16) for y in range(16)
            if slums.script_id(x, y) not in SLUMS_PLAIN_IDS} | set(blocked)


def slums_replanner(slums, target):
    """A `walk_route` `replan` for the Slums: a path from where the party
    stands to `target` that avoids every square reported locked so far.

    `geowalk.route` exempts its goal from `avoid`, so a locked `target` has no
    route and gets None.
    """
    blocked = set()

    def replan(here, square):
        blocked.add(tuple(square))
        if tuple(square) == tuple(target):
            return None
        return geowalk.route(slums, tuple(here), tuple(target),
                             avoid=slums_avoid(slums, blocked))

    return replan


def plan_fight_route(new_phlan, slums, start, target):
    """The two legs to a Slums square: New Phlan `start` to its west exit, then
    `SLUMS_ENTRY` to `target`.

    Both come from the map files, so a script's square is known before it is
    stepped on: the first leg touches none but the exit, the second only
    squares whose id is in `SLUMS_PLAIN_IDS`.  Raises `SystemExit` when either
    leg has no route.
    """
    scripted = {(x, y) for x in range(16) for y in range(16)
                if new_phlan.script_id(x, y)}
    other = slums_avoid(slums)
    out = geowalk.route(new_phlan, tuple(start), NEW_PHLAN_EXIT, avoid=scripted)
    if out is None:
        raise SystemExit(f"no unscripted New Phlan route from {tuple(start)} "
                         f"to {NEW_PHLAN_EXIT}")
    into = geowalk.route(slums, SLUMS_ENTRY, tuple(target), avoid=other)
    if into is None:
        raise SystemExit(f"no Slums route from {SLUMS_ENTRY} to "
                         f"{tuple(target)} over ids {SLUMS_PLAIN_IDS} only")
    return out, into


#: The facing letter and clock of a status line, with or without the
#: coordinates the Slums' line lacks (`S 8:07`).
RE_FACING = re.compile(r"(?<![A-Z])([NESW])(?![A-Z]) +\d+:\d+")


def _status_line(sess):
    """`(facing, square)` read off the status line's text alone.

    Never `sess.position()`: with no coordinates on the line (the Slums) it
    retries for seconds and then falls back to the memory copy, which lags a
    move.  Both come from the last screen row that shows a facing letter and a
    clock, because the status row sits below the message rows and a message such
    as `... E 1:30` must not be taken for it.  Either part is None when the line
    does not show it.
    """
    text = sess.screen_text() or ""
    rows = [r for r in text.split(" / ") if RE_FACING.search(r)]
    row = rows[-1] if rows else text
    m = RE_FACING.search(row)
    at = S.parse_status(row)
    return (S.FACING[m.group(1)] if m else None,
            (at.x, at.y) if at else None)


MAX_EXITS = 4


def _row24(sess) -> str:
    s = sess.screen()
    return "" if s is None else s.row(24).strip()


def _leavable(row: str) -> bool:
    """True when row 24 is a menu the walk must leave with EXIT: the item view
    the READY toggles leave up, or camp's own bar."""
    return row.startswith("ENCAMP:") or (row.startswith("VIEW:")
                                         and "EXIT" in row)


def to_world(sess, log: Log, timeout: float = 30,
             need_square: bool = False) -> bool:
    """Leave the item view and camp if the game is in either, then wait for the
    world bar.

    Leaving the item list lands on camp's own bar (`ENCAMP:SAVE VIEW ...`), so
    the exit is a chain.  Whenever row 24 is such a menu, EXIT is pressed, at
    most once per distinct row 24 and at most `MAX_EXITS` times in all, and each
    press is logged with the row and what `select_bar` returned.  The world is
    polled for throughout -- the bar is `MOVE` and the status line shows a
    facing, and a square too when `need_square`.  Raises `RuntimeError` naming
    the last row 24 and every EXIT result when the world bar does not come
    within `timeout`, and otherwise returns True.
    """
    seen = None
    pressed = []
    results = []
    deadline = time.monotonic() + timeout
    while True:
        row = _row24(sess)
        if row != seen:
            log.emit("to_world", row24=row)
            seen = row
        if (_leavable(row) and row not in pressed
                and len(pressed) < MAX_EXITS):
            pressed.append(row)
            results.append(sess.select_bar("EXIT", timeout=10))
            log.emit("to_world_exit", row24=row, returned=results[-1])
            continue
        if "MOVE" in row:
            face, square = _status_line(sess)
            if face is not None and (square is not None or not need_square):
                return True
        if time.monotonic() >= deadline:
            raise RuntimeError("the game never reached the world bar; row 24 "
                               f"reads {row!r}; select_bar('EXIT') returned "
                               + (", ".join(repr(r) for r in results)
                                  or "None"))
        time.sleep(0.5)


def _turn_key(sess, log: Log, key: str, expected: int, leg: str, here, there):
    """Send a turn key; return a `not_pressed`, `no_status_line` or
    `turn_not_seen` desync, or None.

    A turn does not always change the status tuple `walk_one` compares, so its
    return value says nothing; only `walk_refused`, set when the driver pressed
    nothing, does.  The facing the status line then reports is the check, and a
    line with no facing is a desync too, because both the New Phlan and Slums
    lines carry one.
    """
    sess.walk_one(key.upper())
    sess.handle_prompt()
    if sess.in_combat():
        seen = None
    else:
        refused = sess.walk_refused
        if refused is not None:
            log.emit("route_key", leg=leg, key=key, to=list(there), turn=True,
                     facing=None, expected=expected, refused=refused)
            return {"leg": leg, "key": key, "from": list(here),
                    "to": list(there), "reason": "not_pressed",
                    "refused": refused, "row24": _row24(sess)}
        # The line can be blank for a moment while the screen redraws after a
        # turn, so it is read again for about a second before it counts as gone.
        seen = _status_line(sess)[0]
        for _ in range(3):
            if seen is not None or sess.in_combat():
                break
            time.sleep(0.35)
            seen = _status_line(sess)[0]
    log.emit("route_key", leg=leg, key=key, to=list(there), turn=True,
             facing=seen, expected=expected)
    if seen is None and not sess.in_combat():
        return {"leg": leg, "key": key, "from": list(here), "to": list(there),
                "reason": "no_status_line", "row24": _row24(sess)}
    if seen is not None and seen != expected:
        return {"leg": leg, "key": key, "from": list(here), "to": list(there),
                "reason": "turn_not_seen", "facing": seen, "expected": expected}
    return None


#: Seconds `settle_step` gives a square's script to hand the game back after
#: a key: a wandering encounter loads its monster and, on a surprise, the
#: fight itself from disk.  A limit, not a measurement.
STEP_SETTLE_WAIT = 120.0

#: Seconds between `settle_step`'s reads of row 24.
SETTLE_POLL = 0.5

#: Reads in a row a walkable bar must hold before the next key goes, and a
#: bar the walk does not answer must hold before it counts as a choice
#: rather than a bar caught half drawn.
WALKABLE_READS = 2
CHOICE_READS = 4

#: Returns `settle_step` sends at one unchanged `PRESS` bar before it gives
#: up on it.
MAX_PRESSES = 3

#: Seconds the walkable bar must hold, with the combat icon and the menu
#: read again, before the last step of a route counts as having met no fight:
#: the bar left over from before a square's script is indistinguishable from
#: the live one until the script has had time to blank it.
FINAL_QUIET = 3.0


def settle_step(sess, log: Log, key: str, there,
                timeout: float = STEP_SETTLE_WAIT,
                taken: bool = False, quiet: float = 0.0) -> tuple[str, str]:
    """Wait until what a square's script put up after `key` has cleared.

    Returns `(outcome, row24)`: `"ready"` once the world bar or the move
    sub-bar has held for `WALKABLE_READS` reads, `"fight"` once the combat
    icon is up, `"choice"` for a bar the walk does not answer that held for
    `CHOICE_READS` reads (nothing is pressed at it), and `"unsettled"` when
    `timeout` runs out first.  A `PRESS` bar that `MAX_PRESSES` Returns did not
    clear is `"unsettled"`.  An encounter menu still up after the word was
    taken is a `"choice"` only once it has held `CHOICE_READS` reads counted
    from the press and a combat poll has found no fight since.  With `quiet` set, `"ready"` also
    needs the walkable bar to have held that many seconds, so a stale bar
    cannot be taken for the end of a script.

    A Slums script rolls a wandering encounter on every unscripted square
    (`ECL14` entry 1, id 0).  Row 24 goes blank while its monster loads; a
    surprise then prints its line over a `PRESS` bar and goes straight to
    the fight, and any other roll opens `COMBAT WAIT FLEE ADVANCE`.  A key
    sent in that time is refused by `walk_one`.  So a `PRESS` bar is
    answered, a disk prompt handled, and the caller's `walk_encounter` word
    taken once on a menu that
    carries it, as `walk_one` itself does, unless `taken` says it already
    was; a blank row is waited on.  Each change of row 24 after the first
    read is logged as `step_screen`.
    """
    word = getattr(sess, "walk_encounter", None)
    seen = None
    walkable = held = presses = 0
    row = ""
    next_combat = 0.0
    ready_since = None
    polled = False
    deadline = time.monotonic() + timeout
    while True:
        now = time.monotonic()
        if now >= deadline:
            return "unsettled", row
        if now >= next_combat:
            next_combat = now + COMBAT_POLL
            if sess.in_combat():
                return "fight", row
            # A poll that finds no fight after the menu has held is what
            # lets it be called a choice: a fight loading from disk leaves
            # the menu drawn.
            polled = polled or (taken and held >= CHOICE_READS)
        s = sess.screen()
        row = "" if s is None else s.row(24).strip()
        if seen is not None and row != seen:
            log.emit("step_screen", key=key, to=list(there), row24=row)
        held = held + 1 if row == seen else 1
        seen = row
        if S.MOVE_SUBBAR in row or _world_bar(row):
            walkable += 1
            if walkable >= WALKABLE_READS:
                if ready_since is None:
                    ready_since = now
                if now - ready_since >= quiet:
                    return ("fight" if quiet and sess.in_combat()
                            else "ready"), row
        else:
            walkable = 0
            ready_since = None
            state = sess.combat_state(s) if s is not None else None
            kind = state.kind if state is not None else S.BAR_BLANK
            if kind == S.BAR_DISK:
                sess.handle_prompt(s)
            elif kind == S.BAR_PRESS:
                if held > 1 and presses >= MAX_PRESSES:
                    return "unsettled", row
                presses = presses + 1 if held > 1 else 1
                log.emit("step_press", key=key, to=list(there), row24=row)
                sess.press_kernal(0x0D)
                sess.await_change(state.text, timeout=6)
                continue
            elif row and word and S.word_column(row, word) >= 0:
                if taken:
                    if held >= CHOICE_READS and polled:
                        return "choice", row
                else:
                    log.say(f"  an encounter after {key} at {tuple(there)}: "
                            f"{row!r}; taking {word}")
                    log.emit("step_encounter", key=key, to=list(there),
                             row24=row)
                    sess.select_bar(word, timeout=8)
                    taken = True
                    held = 0
            elif row and held >= CHOICE_READS:
                return "choice", row
        time.sleep(SETTLE_POLL)


def _encounter_taken(sess) -> bool:
    """Whether the last `walk_one` stopped at an encounter menu and took the
    caller's `walk_encounter` word on it, as `_stop_walk` does."""
    word = getattr(sess, "walk_encounter", None)
    rows = getattr(sess, "walk_stop_screen", None)
    return bool(word and rows and S.word_column(rows[24], word) >= 0)


#: Seconds `walk_route` waits after a key that was sent and did not move the
#: party, for an encounter menu.  A limit, not a measurement: a wall answers
#: with the world bar at once, so only an encounter or a script uses it.
UNMOVED_SETTLE_WAIT = 10.0


def _fight_square(sess, log: Log, here) -> tuple:
    """The square a fight found after an unmoved key belongs to: the live
    square read as `walk_one` reads it on a line with no square, else `here`,
    logged as assumed.  A Slums encounter can be rolled on arrival, so `here`
    is not always right."""
    try:
        triple = sess.steady_triple()
    except (OSError, S.MonitorError) as error:
        triple = None
        why = str(error)
    else:
        why = "the live square never steadied"
    if triple is None:
        log.emit("fight_square_assumed", square=list(here), why=why)
        return tuple(here)
    return tuple(triple[:2])


def _stopped(sess, log: Log, out, leg: str, key: str, here, there,
             outcome: str, row: str) -> dict:
    """The desync for a `settle_step` that did not hand the game back."""
    log.say(f"  after {key} towards {tuple(there)} row 24 reads {row!r}; "
            f"{'a choice the walk does not make' if outcome == 'choice' else 'it never cleared'}")
    if out is not None:
        dump(sess, out, log, f"{leg}-{outcome}-{there[0]}-{there[1]}")
    return {"leg": leg, "key": key, "from": list(here), "to": list(there),
            "reason": outcome, "row24": row}


def _locked_door(row: str) -> bool:
    """The bar a locked door opens: `BASH PICKLOCK QUIT`."""
    return all(S.word_column(row, w) >= 0 for w in ("BASH", "PICKLOCK", "QUIT"))


def _answer_locked_door(sess, log: Log, out, leg: str, key: str, here, there,
                        row: str, replan):
    """Take QUIT at a locked door and plan around `there`.

    Returns `("replanned", path)`; `("fight", here)` when a fight came up
    after QUIT; or `("stopped", desync)` when QUIT was not selectable, the
    game did not come back to a walkable bar, or `replan` has no route.  BASH
    and PICKLOCK are never chosen.  The replan starts from `here`, the planned
    square: the Slums' status line has no square to check it against, so the
    party is assumed not to have moved.
    """
    log.say(f"  a locked door at {tuple(there)}: {row!r}; taking QUIT")
    log.emit("locked_door", leg=leg, key=key, square=list(there), row24=row)
    record = {"leg": leg, "key": key, "from": list(here), "to": list(there),
              "reason": "locked_door", "square": list(there), "row24": row}
    if not sess.select_bar("QUIT", timeout=8):
        record["refused"] = "QUIT could not be selected on the door's bar"
        return "stopped", record
    outcome, after = settle_step(sess, log, key, here)
    if outcome == "fight":
        return "fight", here
    if outcome != "ready":
        return "stopped", _stopped(sess, log, out, leg, key, here, there,
                                   outcome, after)
    path = replan(tuple(here), tuple(there)) if replan is not None else None
    if path is None:
        record["refused"] = (f"the door at {tuple(there)} is locked and no "
                             f"route from {tuple(here)} avoids it")
        return "stopped", record
    log.emit("route_replanned", leg=leg, blocked=list(there),
             path=[list(q) for q in path])
    return "replanned", path


def walk_route(sess, log: Log, path, facing: int, leg: str, out=None,
               replan=None):
    """Walk `path` one square at a time, answering prompts, and stop in combat.

    Returns `(facing, stopped_at, desync)`.  `stopped_at` is the planned square
    a fight was found on, or None if the path finished; a fight found after the
    turn key of a two-key step belongs to the square the party was still on.
    `desync` is None, or the first forward key `walk_one` reported as not moved
    or after which a status line with coordinates (New Phlan's) shows a square
    other than the planned one (`reason` is `square_not_reached`) -- with the
    planned step --, or a turn after which the status line reports the
    wrong facing (`reason` is `turn_not_seen`) -- the walk stops there, because
    every key after it was planned from a square or facing the party is not
    on.  A turn's own `walk_one` result is ignored, since a turn moves no
    square.  Facing is tracked from the keys sent, as `geowalk.keys_for` does,
    because the Slums' status line carries no coordinates to check a step
    against.

    After every key that took, `settle_step` waits for the game to come back
    to a bar the next key can go at, because a square's script can still be
    running.  That wait cannot tell a bar left over from before the script
    from a live one, so a key `walk_one` refused without pressing
    (`not_pressed`) is followed by the same wait and sent once more when a
    walkable bar comes back.  Either wait can find a fight, which stops the
    walk on the square the party stands on.  A key that was sent but did not
    move the party gets the same wait, for `UNMOVED_SETTLE_WAIT` seconds,
    because a square's script can put up an encounter menu after `walk_one`
    has stopped looking; the wait takes the word and the fight is returned
    with the live square, or the planned one when it cannot be read.  Any
    other outcome leaves the desync as it was.  A choice it offers, or a
    screen that never clears, stops the walk with a screenshot under `out`
    when one is given: after a key that took, `reason` is `choice` or
    `unsettled`;
    after a refused key, `reason` stays `not_pressed` and `after` names
    which of the two held.

    A `BASH PICKLOCK QUIT` bar, a locked door on the square being stepped on,
    is answered with QUIT and never BASH or PICKLOCK.  `replan(here, square)`
    then gives a path from where the party stands that avoids `square`, and
    the walk goes on along it; with no `replan` or no route the walk stops
    with `reason` `locked_door` and the square named.
    """
    steps = list(zip(path, path[1:]))
    for number, (here, there) in enumerate(steps, 1):
        keys = geowalk.keys_for([here, there], facing, reverse="turn")
        want = geowalk.STEP.index((there[0] - here[0], there[1] - here[1]))
        for index, key in enumerate(keys):
            turn = key != "i"
            if turn:
                facing = (facing + (1 if key == "k" else -1)) % 4
            landed = here if turn else there
            last = number == len(steps) and index == len(keys) - 1
            quiet = FINAL_QUIET if last else 0.0
            for attempt in range(2):
                if turn:
                    bad = _turn_key(sess, log, key, facing, leg, here, there)
                    if sess.in_combat():
                        return want, here, None
                else:
                    moved = bool(sess.walk_one(key.upper()))
                    sess.handle_prompt()
                    log.emit("route_key", leg=leg, key=key, to=list(there),
                             moved=moved)
                    if sess.in_combat():
                        return want, (there if moved else here), None
                    bad = None
                    if not moved:
                        bad = {"leg": leg, "key": key,
                               "from": list(here), "to": list(there)}
                        if sess.walk_refused is not None:
                            bad.update(reason="not_pressed",
                                       refused=sess.walk_refused,
                                       row24=_row24(sess))
                if bad is None:
                    break
                if "reason" not in bad:
                    # The key was sent and the status did not change: a wall,
                    # or a square whose script put up an encounter menu after
                    # `walk_one` stopped looking.  The wait takes the menu's
                    # `walk_encounter` word once and finds the fight; on
                    # anything else the desync stands as it was.
                    outcome, row = settle_step(sess, log, key, here,
                                               timeout=UNMOVED_SETTLE_WAIT,
                                               taken=False)
                    if outcome == "fight":
                        return want, _fight_square(sess, log, here), None
                    if outcome != "ready":
                        log.emit("unmoved_key_unsettled", leg=leg, key=key,
                                 to=list(there), outcome=outcome, row24=row)
                if bad.get("reason") != "not_pressed" or attempt:
                    return want, None, bad
                # Nothing was pressed: wait out whatever is up, and send the
                # key again only when a walkable bar comes back.
                outcome, row = settle_step(sess, log, key, here,
                                           taken=_encounter_taken(sess),
                                           quiet=quiet)
                if outcome == "fight":
                    return want, here, None
                if outcome == "choice" and not turn and _locked_door(row):
                    kind, got = _answer_locked_door(
                        sess, log, out, leg, key, here, there, row, replan)
                    if kind == "fight":
                        return want, got, None
                    if kind == "replanned":
                        return walk_route(sess, log, got, want, leg, out,
                                          replan)
                    return want, None, got
                if outcome != "ready":
                    # The refusal stays the reason; the wait says what held.
                    stop = _stopped(sess, log, out, leg, key, here, there,
                                    outcome, row)
                    bad.update(after=outcome, row24=stop["row24"])
                    return want, None, bad
                log.emit("route_retry", leg=leg, key=key, to=list(there),
                         refused=bad["refused"])
            outcome, row = settle_step(sess, log, key, landed, quiet=quiet)
            if outcome == "fight":
                return want, landed, None
            if outcome == "choice" and not turn and _locked_door(row):
                kind, got = _answer_locked_door(
                    sess, log, out, leg, key, here, there, row, replan)
                if kind == "fight":
                    return want, got, None
                if kind == "replanned":
                    return walk_route(sess, log, got, want, leg, out, replan)
                return want, None, got
            if outcome != "ready":
                return want, None, _stopped(sess, log, out, leg, key, here,
                                            there, outcome, row)
            if turn:
                continue
            seen, square = _status_line(sess)
            if leg == "slums":
                log.emit("slums_status", key=key, to=list(there), facing=seen,
                         square=list(square) if square else None)
            if square is not None and square != tuple(there):
                return want, None, {"leg": leg, "key": key,
                                    "from": list(here), "to": list(there),
                                    "reason": "square_not_reached",
                                    "square": list(square)}
        facing = want
    return facing, None, None


#: Seconds `await_slums` gives the Slums to come up after the edge key has
#: been answered.  Measured: row 24 blank until 55 s after the step on to the
#: exit with no fight, and a fight's menu at 64 s; a limit, not a measurement.
SLUMS_ARRIVAL_WAIT = 180.0

#: Seconds between `await_slums`' reads of the combat icon.
COMBAT_POLL = 2.0


def _world_bar(row: str) -> bool:
    """The world's command bar, not camp's `ENCAMP:` header bar."""
    return "ENCAMP" in row and "ENCAMP:" not in row


def await_slums(sess, log: Log, out: pathlib.Path, area_before,
                timeout: float = SLUMS_ARRIVAL_WAIT) -> str:
    """Wait out the Slums' load after the step off the edge; `"move"`,
    `"world"`, `"fight"` or `"fight_before_edge"`.

    The load reads side 2 for about a minute.  The screen keeps New Phlan's
    last view and status line (`0,4`) with row 24 blank, while the area byte
    already reads the Slums, so neither the byte nor a world bar alone says
    the Slums are up.  The load counts as started once row 24 has gone blank
    or a disk prompt has been seen, or when, on two polls running, the area has changed from
    `area_before` and the status line parses and has left the exit; only then is a bar
    taken as the Slums'.  With no fight the load ends on the move sub-bar
    (`I,J,K,M, RETURN OR BUTTON`, `"move"`), because the edge was a step
    taken from it, and the world bar never shows; `walk_one` steps from the
    sub-bar as it stands.  The Slums can roll a fight on arrival
    (`COMBAT WAIT FLEE ADVANCE`): COMBAT is taken once, as `walk_encounter`
    asks of every step, and the call returns `"fight"` when the fight is up.
    A fight already up before the load has been seen is New Phlan's, rolled by
    the edge step itself: it returns `"fight_before_edge"`, because the Slums
    are not up and the party never crossed.
    A `PRESS` bar is answered and a disk prompt handled, as `wait_for_world`
    does.  Each change of row 24 is logged with the area; at the limit a
    screenshot is taken and `RuntimeError` names row 24 and the area.
    """
    started = taken = pressed = False
    seen = None
    row, area = "", None
    slums_polls = 0
    next_combat = 0.0
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # The combat icon is a memory read; twice a second is more than a
        # fight needs, and the screen poll below stays at 0.5 s.
        if time.monotonic() >= next_combat:
            next_combat = time.monotonic() + COMBAT_POLL
            if sess.in_combat():
                return "fight" if started else "fight_before_edge"
        s = sess.screen()
        row = "" if s is None else s.row(24).strip()
        area = resident_area(sess, log)
        if row != seen:
            log.emit("slums_arrival", row24=row, area=area)
            seen = row
        if s is not None:
            if not row or sess.wanted_disk(s) is not None:
                started = True
            else:
                # The stale New Phlan view keeps its status line at the exit
                # while the area byte already reads the Slums, so the route
                # needs two consecutive polls with a status line that parses
                # (a facing) and has left the exit.
                face, square = _status_line(sess)
                if (area == SLUMS_AREA and area_before != SLUMS_AREA
                        and face is not None and square != NEW_PHLAN_EXIT):
                    slums_polls += 1
                    if slums_polls >= 2:
                        started = True
                else:
                    slums_polls = 0
            state = sess.combat_state(s)
            if state.kind == S.BAR_DISK:
                sess.handle_prompt(s)
            elif state.kind == S.BAR_PRESS:
                sess.press_kernal(0x0D)
                sess.await_change(state.text, timeout=6)
                continue
            elif started and S.MOVE_SUBBAR in row:
                return "move"
            elif started and _world_bar(row):
                return "world"
            elif (started and not taken
                  and S.word_column(row, S.ENCOUNTER_FIGHT) >= 0):
                log.say(f"  a fight on arrival: {row!r}; taking "
                        f"{S.ENCOUNTER_FIGHT}")
                log.emit("slums_arrival_fight", row24=row)
                pressed = bool(sess.select_bar(S.ENCOUNTER_FIGHT, timeout=8))
                taken = True
            else:
                sess.handle_prompt(s)
        time.sleep(0.5)
    log.emit("slums_arrival_failed", row24=row, area=area, started=started,
             fight_taken=taken)
    dump(sess, out, log, "slums-arrival-failed")
    raise RuntimeError(
        f"the Slums never came up after the step off the edge: row 24 reads "
        f"{row!r}, area {area}; the load was "
        f"{'seen' if started else 'never seen'} starting"
        + ("; COMBAT was pressed and no fight came up" if pressed else
           "; COMBAT was attempted and did not land" if taken else ""))


FIGHT_WAIT = 180.0        # a limit, not a measurement
FIGHT_POLL = 0.5
FIGHT_PRESS_LIMIT = 3


def score_party_icons(sess, log: Log, roll: dict, disks=None) -> None:
    """Log how each drawn party figure scores against the creation default.

    `roll` is the fight's `savecheck.roll_call`, read once by the caller.  Each
    figure it puts on a party member's square is compared, by
    `savecheck.icon_evidence`, with both poses (unmirrored and mirrored) of
    `dirtenicon.native_default().icon`, which the generator writes into all
    eight icon entries.  `exact` is whether some pose matched all nine glyphs
    and `exact_colours` whether its colours matched too; a member with no
    figure is listed under `not_drawn`.  `disks` is where `CHARPIC00` is read
    from; `native_default` takes no path and reads `$POR_DISKS` or the
    registry, so the two are the same directory only when the run was started
    that way.  Logs `icon_score_unavailable` and returns when `roll` is empty
    or the game's own default or glyphs cannot be read.
    """
    if not roll:
        log.emit("icon_score_unavailable", why="no battle could be read")
        return
    try:
        icon = dirtenicon.native_default().icon
        charset = savecheck.icon_charset(pathlib.Path(disks or DISKS))
        slots = [{"slot": n, "occupied": True, "shape": icon[:18].hex(),
                  "colours": icon[18:].hex()} for n in range(8)]
        evidence = savecheck.icon_evidence(sess, icon, slots=slots,
                                           charset=charset, roll=roll)
    except (Exception, SystemExit) as error:
        log.emit("icon_score_unavailable", why=repr(error))
        return
    figures = [{"name": f["who"], "row": f["row"], "col": f["col"],
                "best": f["best"], "exact": bool(f["exact"]),
                "exact_colours": bool(f["exact_colours"])}
               for f in evidence.get("figures", []) if f["who"] is not None]
    drawn = {f["name"] for f in figures}
    log.emit("icon_score", figures=figures,
             not_drawn=[c["name"] for c in roll["party"]
                        if c["name"] not in drawn])
    for f in figures:
        log.say(f"  {f['name']}: best {f['best']} of 9 glyphs against the "
                f"creation default, exact {f['exact']}")


def photograph_fight(sess, out: pathlib.Path, log: Log,
                     timeout: float = FIGHT_WAIT, disks=None) -> bool:
    """Wait for a party member's turn, then take the `combat-icon` screenshot.

    The battlefield and every figure are drawn only once a party member has a
    command bar, or a move bar the side pane names a party member for: the
    game shows the same `MOVE/ATTACK, MOVE LEFT = n` bar while a monster moves,
    with the monster in the pane, and the camera is then on the monster.  A
    shot taken when `in_combat` first answers shows two empty panes.  A PRESS
    bar on the way gets a Return, at most `FIGHT_PRESS_LIMIT` times, and is
    waited out before the next read; a disk prompt goes to `handle_prompt`.  At
    the limit the screenshot is taken anyway and `fight_screen` records
    `battlefield: false`, so a missing bar is a finding and not a crash.
    `fight_screen` also carries the camera and each member's screen cell, and
    `icon_score` follows the shot.  Returns whether the party's turn appeared.
    """
    deadline = time.monotonic() + timeout
    presses, state, ready = 0, None, False
    while True:
        screen = sess.screen()
        state = sess.combat_state(screen)
        if state.kind == S.BAR_COMMAND:
            ready = True
            break
        if state.kind == S.BAR_MOVE and sess.acting(sess.battle(),
                                                    screen) is not None:
            ready = True
            break
        if screen is not None and sess.wanted_disk(screen) is not None:
            # A disk prompt is answered by the disk handler; Return would not do.
            sess.handle_prompt(screen)
        elif state.kind == S.BAR_PRESS and presses < FIGHT_PRESS_LIMIT:
            sess.press_kernal(0x0D)
            presses += 1
            # The prompt stays up a moment after the key is taken: pressing at
            # every poll would send a second Return into the next bar.
            sess.await_change(state.text, timeout=6)
        if time.monotonic() >= deadline:
            break
        time.sleep(FIGHT_POLL)
    # One read of the combatant table serves the log and the icon score.  A
    # member off the map (`$FF`) has no cell and is logged as off the map.
    roll = savecheck.roll_call(sess)
    what = {"battlefield": ready, "presses": presses}
    camera = tuple(roll["camera"]) if roll else None
    party = []
    for c in roll.get("party", ()):
        member = {"name": c["name"], "square": [c["x"], c["y"]],
                  "on_map": c["on_map"], "in_window": c["in_window"]}
        if c["on_map"] and camera is not None:
            member["cell"] = list(savecheck.where_drawn(c["x"], c["y"],
                                                        camera))
        party.append(member)
    if camera is not None:
        what["camera"] = list(camera)
    what["party"] = party
    if not ready:
        what["row24"] = state.text
    log.emit("fight_screen", **what)
    log.say(f"  fight screen: battlefield {'drawn' if ready else 'not seen'}"
            f"; party {party}")
    dump(sess, out, log, "combat-icon")
    score_party_icons(sess, log, roll, disks)
    return ready


def walk_to_fight(sess, log: Log, out: pathlib.Path, target, new_phlan,
                  slums, disks=None) -> dict:
    """New Phlan to the Slums and on to `target`, stopping in combat.

    A fight found before `target` (the Slums roll a wandering fight on
    unscripted squares) is logged as on the way, not as the target.  A key the
    game did not act on ends the walk with `desynced` set, and `at_target` is
    only ever true for a walk on which every key moved.
    """
    if sess.in_combat():
        # A fight already up has no world bar to wait for, so waiting would
        # burn `to_world`'s whole timeout and then raise.
        _, here = _status_line(sess)
        began = list(here) if here is not None else None
        log.emit("walked", leg="start", in_combat=True, began_at=began,
                 at_target=False, desynced=None)
        log.say(f"  a fight is already up at {began}; not walking")
        photograph_fight(sess, out, log, disks=disks)
        return {"in_combat": True, "began_at": began, "at_target": False,
                "desynced": None}
    to_world(sess, log, need_square=True)
    face, square = _status_line(sess)
    if face is None or square is None:
        raise RuntimeError("the status line gave no facing and square to "
                           "plan from")
    start = (*square, face)
    first, second = plan_fight_route(new_phlan, slums, start[:2], target)
    log.emit("fight_plan", start=list(start[:2]), target=list(target),
             new_phlan=[list(q) for q in first], slums=[list(q) for q in second])
    log.say(f"  {len(first) - 1} steps to {NEW_PHLAN_EXIT}, then "
            f"{len(second) - 1} in the Slums to {tuple(target)}")
    sess.walk_encounter = S.ENCOUNTER_FIGHT
    facing, hit, desync = walk_route(sess, log, first, start[2], "new-phlan",
                                      out)
    leg = "new-phlan"
    if hit is None and desync is None:
        at = tuple(sess.position()[:2])
        if at != tuple(first[-1]):
            raise RuntimeError(f"the party is at {at}, not the planned "
                               f"{tuple(first[-1])}, at the edge")
        # `ECL00` entry 0 is on the west edge, so the step must face west.
        keys = geowalk.keys_for([NEW_PHLAN_EXIT, (-1, NEW_PHLAN_EXIT[1])],
                                facing, reverse="turn")
        turning = facing
        for key in keys[:-1]:
            turning = (turning + (1 if key == "k" else -1)) % 4
            desync = _turn_key(sess, log, key, turning, "new-phlan",
                               NEW_PHLAN_EXIT, (-1, NEW_PHLAN_EXIT[1]))
            if sess.in_combat():
                # A fight found by the turn belongs to the edge square, and the
                # step off the edge must not be sent into it.
                hit = NEW_PHLAN_EXIT
                break
            if desync:
                break
        if hit is None and desync:
            dump(sess, out, log, "desynced")
            fighting = bool(sess.in_combat())
            log.emit("walked", leg=leg, in_combat=fighting, began_at=None,
                     at_target=False, desynced=desync)
            log.say(f"  the turn at the edge was not seen: {desync}")
            return {"in_combat": fighting, "began_at": None,
                    "at_target": False, "desynced": desync}
    if hit is None and desync is None:
        area_before = resident_area(sess, log)
        moved = sess.walk_one(keys[-1].upper())
        sess.handle_prompt()
        arrived = await_slums(sess, log, out, area_before)
        area = resident_area(sess, log)
        log.emit("edge", moved=bool(moved), area=area, arrived=arrived)
        log.say(f"  stepped off the edge; area {area}; {arrived} up")
        # A fight's own script is resident while it runs, so its area is not
        # the Slums' and only a move or a world bar is checked against it.
        if arrived in ("move", "world") and area != SLUMS_AREA:
            raise RuntimeError(f"expected area {SLUMS_AREA} after the edge, "
                               f"read {area}")
        if arrived == "fight_before_edge":
            # The edge step rolled a fight in New Phlan: no load was seen, so
            # the party is still on the exit square.
            log.say(f"  the edge was not crossed: a fight is up at "
                    f"{NEW_PHLAN_EXIT}")
            hit = NEW_PHLAN_EXIT
        elif arrived == "fight":
            # Rolled on arrival: the party never left the entry square.
            leg = "slums"
            hit = SLUMS_ENTRY
        else:
            leg = "slums"
            # `ECL00` entry 0 steps forward, so the party leaves facing west.
            west = geowalk.STEP.index((-1, 0))
            facing, hit, desync = walk_route(
                sess, log, second, west, "slums", out,
                slums_replanner(slums, target))
    if (desync is not None and "after" not in desync
            and desync.get("reason") not in ("choice", "unsettled")):
        # `_stopped` has already photographed a wait that did not clear.
        dump(sess, out, log, "desynced")
    fighting = bool(sess.in_combat())
    began = list(hit) if hit else None
    at_target = fighting and desync is None and hit == tuple(target)
    log.emit("walked", leg=leg, in_combat=fighting, began_at=began,
             at_target=at_target, desynced=desync)
    log.say(f"  in combat: {fighting}; began at {began}; "
            f"{'the target' if at_target else 'not the target'}"
            + (f"; a key did not move the party: {desync}" if desync else ""))
    if fighting:
        photograph_fight(sess, out, log, disks=disks)
    return {"in_combat": fighting, "began_at": began, "at_target": at_target,
            "desynced": desync}


def pick_a_fight(sess, log: Log, out: pathlib.Path, steps: int = 150,
                 fight_at=None, maps=None, disks=None) -> dict:
    """Walk until the party is ambushed, and photograph the fight.

    Wall-following rather than a fixed pattern: go forward while it works,
    turn (alternating left and right so a dead end does not send this back
    the way it came) the moment a step is refused.  A first attempt with a
    fixed `IIIIJIIII` cycle spent 80 moves getting from (9, 13) to (8, 13) --
    one tile -- because most of the forward presses were walls and the turns
    never pointed it anywhere new twice in a row (a scratch run directory,
    2026-09-16, deleted).  A wall refusing a step is not an error here, just the
    signal to turn.

    `fight_at` is a Slums square `(x, y)`: the walk is then planned from the
    map files to that square instead of wandering (`walk_to_fight`); `maps` is
    the New Phlan and Slums `Geo` pair, loaded by the caller before the boot.
    """
    if fight_at is not None:
        return walk_to_fight(sess, log, out, fight_at, *maps, disks=disks)
    # A fight already up (an encounter menu the last step opened) is the fight;
    # its bar is not the world's, so waiting for that would time out.
    if not sess.in_combat():
        to_world(sess, log)
    taken = 0
    turn = "J"
    sess.walk_encounter = S.ENCOUNTER_FIGHT
    while taken < steps and not sess.in_combat():
        moved = sess.walk_one("I")
        sess.handle_prompt()
        taken += 1
        if not moved and taken < steps and not sess.in_combat():
            sess.walk_one(turn)
            sess.handle_prompt()
            taken += 1
            turn = "K" if turn == "J" else "J"
    fighting = sess.in_combat()
    log.emit("walked", steps=taken, in_combat=bool(fighting),
             position=list(sess.position()))
    log.say(f"  walked {taken} steps; in combat: {bool(fighting)}")
    if fighting:
        photograph_fight(sess, out, log, disks=disks)
    return {"steps": taken, "in_combat": bool(fighting)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--disk", required=True, type=pathlib.Path,
                   help="the generated save disk, already a copy")
    p.add_argument("--disks", default=DISKS,
                   help="where the player's game sides are; read, never "
                        "written")
    p.add_argument("--slot", type=int, default=None,
                   help="demand this pool slot rather than the first free one")
    p.add_argument("--party", type=int, default=6,
                   help="how many sheets to read")
    p.add_argument("--out", default=None, help="run directory")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--full", action="store_true",
                   help="also do the four #10 questions the last comment "
                        "asked for in one boot: remove/re-add BULWARK, "
                        "toggle READY on PILFER and BULWARK, and pick a fight")
    p.add_argument("--fight-only", action="store_true",
                   help="skip the remove/re-add and the item toggles -- just "
                        "boot, load, begin adventuring and pick a fight, for "
                        "re-running the slow part of --full on its own")
    p.add_argument("--fight-at", default=None, metavar="X,Y",
                   help="walk to this Slums square, over the maps, instead of "
                        "wandering for a fight")
    args = p.parse_args(argv)
    fight_at = None
    if args.fight_at is not None:
        try:
            fight_at = tuple(int(v) for v in args.fight_at.split(","))
        except ValueError:
            fight_at = ()
        if len(fight_at) != 2 or not all(0 <= v < 16 for v in fight_at):
            raise SystemExit("--fight-at takes X,Y, each 0 to 15")

    disks = pathlib.Path(args.disks) if args.disks else DISKS
    if disks is None:
        raise SystemExit("No game disks found. Set $POR_DISKS.")
    out = pathlib.Path(args.out) if args.out else scratch.scratch_dir("testpartyrun", "run")
    # Both maps are read before the emulator boots, so a missing disk fails
    # here rather than after the slow part of the run.
    maps = None
    if fight_at is not None:
        maps = (geowalk.load_geo("GEO00", "pool-of-radiance"),
                geowalk.load_geo("GEO14", "pool-of-radiance"))
    log = Log(out, args.quiet)
    log.emit("start", disk=str(args.disk), sides=str(disks))

    # The staging directory holds the generated save beside symlinks to the
    # player's own sides, so `stage_disks` copies all nine into the slot and
    # the originals are only ever read -- the way `tools/c64/turndrive.py` does it.
    staging = out / "disks"
    staging.mkdir(parents=True, exist_ok=True)
    S.stage_writable(args.disk, staging / "STAGED.D64")
    for i in range(1, 9):
        src = disks / f"POOL{i}.D64"
        link = staging / f"POOL{i}.D64"
        if src.exists() and not link.exists():
            link.symlink_to(src.resolve())

    slot = S.claim_slot(args.slot, f"testpartyrun/{args.disk.name}")
    log.say(f"slot {slot.n} display {slot.display}  out {out}")
    sess, rc = None, 0
    findings: dict = {}
    try:
        sess = S.Session(S.stage_disks(slot, staging, "STAGED.D64"), slot=slot)
        for step in ("boot", "load_save"):
            log.say(f"{step} ...")
            if not getattr(sess, step)():
                log.emit("failed", step=step)
                raise RuntimeError(f"{step} failed")
            log.emit("done", step=step)

        if args.full:
            log.say("remove/re-add BULWARK, from the party menu ...")
            raw = remove_and_readd(sess, log, out, "BULWARK")
            findings["bulwark_export"] = raw is not None
            if raw is not None:
                (out / "BULWARK-exported.CHR").write_bytes(raw)
                log.say(f"  wrote {len(raw)} bytes to BULWARK-exported.CHR")

        if args.fight_only:
            args.party = 0

        log.say("begin_adventuring ...")
        if not sess.begin_adventuring():
            log.emit("failed", step="begin_adventuring")
            raise RuntimeError("begin_adventuring failed")
        log.emit("done", step="begin_adventuring")
        sess.settle(3)
        log.emit("world", position=list(sess.position()))
        log.say(f"in the world at {sess.position()}")

        for index in range(args.party):
            shot = str(out / f"sheet{index}.png")
            lines = sess.character_sheet(index, shot=shot)
            log.emit("sheet", index=index, lines=lines, shot=shot)
            if lines is None:
                log.say(f"  slot {index}: no sheet")
                rc = 1
                continue
            (out / f"sheet{index}.txt").write_text("\n".join(lines) + "\n")
            log.say(f"  slot {index}: {lines[0][:60] if lines else ''}")
            for line in lines[:6]:
                log.say(f"      {line}")

        if args.full:
            sess.settle(3)
            log.say("toggling PILFER's LEATHER ARMOR +4 ...")
            findings["pilfer_armour"] = item_toggle_pair(
                sess, log, out, "PILFER", "LEATHER ARMOR", "pilfer-armour")
            sess.settle(3)
            log.say("toggling BULWARK's TWO-HANDED SWORD (shield and long "
                    "sword off first -- both already readied, and readying "
                    "the two-handed sword with the shield alone off still "
                    "read NO on 2026-09-16) ...")
            findings["bulwark_sword"] = item_toggle_pair(
                sess, log, out, "BULWARK", "TWO-HANDED SWORD", "bulwark-sword",
                sequence=["SHIELD", "LONG SWORD", "TWO-HANDED SWORD",
                         "TWO-HANDED SWORD", "LONG SWORD", "SHIELD"])
        if args.full or args.fight_only or fight_at:
            log.say("picking a fight ...")
            findings["fight"] = pick_a_fight(sess, log, out, fight_at=fight_at,
                                            maps=maps, disks=disks)
            (out / "findings.json").write_text(json.dumps(findings, indent=1))
    except Exception as exc:                       # noqa: BLE001
        log.emit("error", why=repr(exc))
        log.say(f"ERROR {exc!r}")
        rc = 2
    finally:
        if sess is not None:
            sess.terminate()
        else:
            slot.teardown()
        log.emit("end", rc=rc)
        log.close()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
