#!/usr/bin/env python3
"""Photograph the automapper's own map while a driven party walks.

The question `#198 (Does the automapper draw a live party on the travel grid,
or leave the marker where it entered?)` asks is not what memory says -- it is
what a player looking at the map window sees.  So this drives a real session
with `tools/c64/session.py`, builds the **real** map tab offscreen against the same
emulator, ticks it, and saves a PNG of the window and of the map canvas after
every step.

    env -u WAYLAND_DISPLAY -u XDG_SESSION_TYPE QT_QPA_PLATFORM=offscreen \\
        GDK_BACKEND=x11 .venv/bin/python tools/gui/mapmarker.py \\
        --disk OUTC.D64 --slot 2 --walk 1357

Three things make it an accurate reproduction of what a player has rather than a
model of it:

* the widgets are `wish/window.ui`'s own, wired by `automap.window`
  `AutomapBinding` exactly as `wish/window.py` wires them -- the same canvas,
  the same bottom strip, the same Messages panel;
* the fix comes from `automap.target.party_fix`, over the same monitor, in one
  stop/resume, which is what `ViceTarget.fix` does.  Nothing here reimplements
  the reading;
* the moves go through `Session.walk_one`, so the party is moved by the game's
  own keys and not by writing memory.

`--slot` is a pool slot, and `POR_HEADLESS=1` keeps the emulator off the
desktop.  `_offscreen()` forces the Python side offscreen as well, so the
environment above is belt and braces rather than the only thing standing
between a run and a window on somebody's desktop.

Its settings and its notes go to `--out/config` and `--out/data`, so a run
never writes into the player's own automapper notes.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap import actions, fasttravel  # noqa: E402
from automap.paths import tool_disks  # noqa: E402
from tools.c64 import session as S  # noqa: E402
from tools.c64.runlog import Log  # noqa: E402
from tools.c64.savecheck import answer_bars  # noqa: E402
from tools.gui.livecheck import SessionTarget  # noqa: E402
from tools.pool_of_radiance.fleedrive import Flight  # noqa: E402
from tools.registry import scratch  # noqa: E402

#: Where the player keeps the C64 disks.  Read, never written -- the sides are
#: copied into the slot and the game only ever sees the copies.
DISKS: pathlib.Path | None = tool_disks()

#: The bytes to write down beside every screenshot, and why each one is
#: here.  `$49E6` says which of the two worlds the party is in; `$49C0` is the
#: dungeon triple, which freezes outdoors at the square the party left the grid
#: on; `$49C3` is the live travel square; `$C04B` is the machine's own
#: `live_position`, the
#: engine's own triple and what `party_fix` falls back to; `$033D` is the travel
#: heading the game stores before every step, and combat borrows the same byte.
PROBES = {
    "indoors_49E6": (0x49E6, 1),
    "dungeon_49C0": (0x49C0, 3),
    "travel_49C3": (0x49C3, 2),
    "heading_033D": (0x033D, 1),
    "live_C04B": (0xC04B, 3),
    "area_6E1B": (0x6E1B, 1),
}


def probes(sess, names=None) -> dict:
    """The addresses in `PROBES` (or just `names`), as hex, in one stop of the machine."""
    wanted = {n: PROBES[n] for n in (names or PROBES)}
    try:
        with sess.mon(5) as m:
            return {name: m.read(addr, length).hex()
                    for name, (addr, length) in wanted.items()}
    except Exception as exc:                       # a read that failed is data
        # Every key still comes back, because `look` writes them into its own
        # line.  Returning only the error truncated a whole run on the first
        # transient timeout, minutes after the boot that paid for it.
        failed = {name: None for name in wanted}
        failed["error"] = f"{type(exc).__name__}: {exc}"
        return failed


def status_row(sess) -> str:
    """Row 14 verbatim -- the line `party_fix` matches against."""
    s = sess.screen()
    return "" if s is None else s.row(14)


def clear_bars(sess, log: Log, answers=("STAY", "NO"), seconds: float = 180.0,
               want_outdoors: bool | None = None,
               stop_on_encounter: bool = False) -> str:
    """Press through an arrival until the party can move again.

    **`savecheck.answer_bars` is not enough for the wilderness**, and that is
    a fact about the game rather than about that function: arriving on the
    middle window's (7,29) draws a boat and asks `WILL YOU TAKE IT?` over a
    bar reading `TAKE BOAT  STAY`, not `YES  NO`.  A run that only answered
    `YES NO` bars sat in front of it until it timed out, with the *old* area's
    status line still on the screen -- so the map had a stale line to read and
    the crossing never actually happened.

    Answers the first label in `answers` that is on row 24, and stops on
    either bar the world uses: the command bar, or the travel grid's own
    `1-8, RETURN OR BUTTON`.

    **`want_outdoors` is what makes it wait for the trip to happen at all.**
    A fast travel sets the program counter and returns at once, so for a
    second or two the *departing* area's command bar is still on the screen
    and `$49E6` still says indoors -- and a loop that stopped at the first
    world bar stopped there, before the disk was even asked for.  With
    `want_outdoors` the world only counts once `$49E6` agrees.

    With `stop_on_encounter`, an outdoor encounter's menu on row 24 ends the
    wait at once with `"encounter"`, since nothing here answers it and the
    wait would otherwise run out its whole budget in front of it.
    """
    deadline = time.time() + seconds
    while time.time() < deadline:
        s = sess.screen()
        if s is None:
            time.sleep(1.0)
            continue
        if sess.handle_prompt(s):
            continue
        row = s.row(24)
        unread = object()
        indoors_read = unread               # one `$49E6` read per pass, if any

        def indoors_now():
            nonlocal indoors_read
            if indoors_read is unread:
                indoors_read = _read_indoors(sess, log)
            return indoors_read

        if stop_on_encounter and encounter_menu(row, indoors_now()) is not None:
            return "encounter"
        if ("MOVE" in row and "ENCAMP" in row) or S.OUTDOOR_PROMPT in row:
            # `is (not want_outdoors)` rather than `is not want_outdoors`, so
            # a failed read -- `Session.indoors` answers None for one -- waits
            # rather than counting as an arrival.
            if want_outdoors is None or indoors_now() is (not want_outdoors):
                return "world"
        if "PRESS" in row:
            sess.kbd.key("Return")
        else:
            for label in answers:
                if label in row:
                    log.say(f"    answering {label} to |{row.strip()}|")
                    if not sess.select_bar(label, timeout=8):
                        sess.kbd.key("Return")
                    break
        time.sleep(1.2)
    return "stuck"


def _offscreen() -> None:
    """Make it impossible for this process to draw on the user's desktop.

    Forced rather than defaulted, and `WAYLAND_DISPLAY` unset.  This was a
    `setdefault` and that is a no-op for the one person most likely to run it:
    a desktop session exports `QT_QPA_PLATFORM` for its own compositor --
    COSMIC and KDE both do, and this machine reads `wayland;xcb` -- so the
    default never applied and `build_window` would have opened a real window
    on the live session.  `tests/conftest.py` records the same mistake being
    made and fixed in the suite.  A Qt child also prefers Wayland over
    whatever is set for X, so unsetting `WAYLAND_DISPLAY` is what makes a
    private X display a sandbox rather than a suggestion.

    `WISH_SHOT_PLATFORM` is the escape hatch, and it is the same name
    `tools/gui/shotstrip.py` and `tools/gui/shotwindow.py` use: set it to look at the
    window while it runs.
    """
    os.environ["QT_QPA_PLATFORM"] = os.environ.get("WISH_SHOT_PLATFORM",
                                                   "offscreen")
    if "WISH_SHOT_PLATFORM" not in os.environ:
        os.environ.pop("WAYLAND_DISPLAY", None)
        os.environ.pop("XDG_SESSION_TYPE", None)
        os.environ["GDK_BACKEND"] = "x11"


def private_settings(out: pathlib.Path) -> None:
    """Keep this run's settings and notes out of the player's own.

    **Set here and not at start-up**, which cost a run: `flatpak` finds a user
    installation under `$XDG_DATA_HOME/flatpak`, so pointing that at a scratch
    directory before `Session.launch` made VICE fail to start at all --
    `app/net.sf.VICE/x86_64/master not installed`, and 60 s later "VICE never
    came up".  Nothing after the emulator is up looks at `$XDG_DATA_HOME`
    except the automapper.
    """
    # `automap.paths` reads the XDG pair on Linux and APPDATA/LOCALAPPDATA on
    # Windows; macOS derives both from the home directory, so there is nothing
    # to set and the run would use the player's own folder.
    if sys.platform == "darwin":
        raise RuntimeError("Private settings are not supported on macOS.")
    for var, name in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                      ("APPDATA", "config"), ("LOCALAPPDATA", "data")):
        os.environ[var] = str((out / name).resolve())


def build_window(target, disks: str, out: pathlib.Path,
                 amiga_only: bool = False):
    """The real map tab, offscreen, with its own settings and notes.

    `amiga_only` loads the maps the way a player's window does for a title that
    exists only on the Amiga, which `load_maps_titled` names only when asked.
    """
    private_settings(out)
    from PyQt6.QtWidgets import QApplication, QMainWindow

    from automap.maps import load_maps_titled
    from automap.state import Automapper
    from automap.window import AutomapBinding
    from wish.ui_window import Ui_WishWindow

    app = QApplication.instance() or QApplication([])
    maps, game = load_maps_titled(disks, amiga_only=amiga_only)
    root = QMainWindow()
    ui = Ui_WishWindow()
    ui.setupUi(root)
    root.ui = ui
    mapper = Automapper(target, maps,
                        title=game.title if game is not None else None)
    # This script owns the connection and calls `tick()` itself, the way
    # `wish/window.py` does -- nothing here polls behind its own back while
    # driving the game's menus.
    binding = AutomapBinding(root, mapper, disks=disks)
    root.resize(1500, 950)
    root.show()
    app.processEvents()
    return app, root, binding, maps


def shot(app, widget, path: pathlib.Path) -> None:
    app.processEvents()
    widget.grab().save(str(path))


def resident_paint(binding) -> list[list[int]]:
    """`[x, y, code]` for each square where the game's resident grid differs
    from the disk's grid for the same window, which the map does not draw."""
    from goldbox.world import GRID_SIZE, STRIDE
    world = binding.mapper._world
    read = binding.mapper._block
    if world is None or read is None or read[2] is None:
        return []
    disk = world.windows[read[2][0]].to_bytes()[:GRID_SIZE]
    block = read[1]
    return [[i % STRIDE, i // STRIDE, block[i]]
            for i in range(GRID_SIZE) if block[i] != disk[i]]


def reading(binding, tag: str) -> dict:
    """What the map tab says about the party now: the half of `look` that
    touches no emulator, so an Amiga run records the same fields."""
    st = binding.state
    return {
        "tag": tag,
        "x": st.x, "y": st.y, "facing": st.facing, "source": st.source,
        "area": st.area, "area_label": st.area_label,
        "where_label": binding.strip.where.text() if binding.strip.where else None,
        "area_strip": binding.strip.area.text() if binding.strip.area else None,
        "status_bar": binding.status_text(),
        # `waiting_text()` went with `#214 (The automapper's empty grid never
        # says there are no game disks, though the code and a test believe it
        # does)` -- nothing painted it, so this field had no source but the
        # method's own string. What it reported is in "messages" below,
        # which is where a player actually sees it now.
        "title_check": str(binding.mapper.title_check),
        # Counted here as well as read off the status bar, which shows it only
        # when it is non-zero: "no contradictions" is the claim a crossing back
        # into the area the party left has to support, and a missing string is
        # weaker evidence than a zero.
        #
        # The counter alone is not enough, and #205 is why. `_narrow` counts a
        # contradiction only when an observation would leave **no** candidate;
        # while the set is still wide it drops the map that no longer fits and
        # says nothing, which is what a bogus edge does -- 20 candidates down
        # to 15 with the right one gone, and the counter at 0 throughout. So
        # record what the set actually holds: a run whose candidates shrink
        # while this reads zero is the fault, not the absence of one.
        "contradictions": (binding.mapper.fingerprint.contradictions
                           if binding.mapper.fingerprint else None),
        "candidates": (sorted(binding.mapper.fingerprint.names)
                       if binding.mapper.fingerprint else None),
        "seen_squares": len(st.exploration),
        "geo_loaded": st.geo is not None,
        "messages": binding.messages.lines()[-6:],
    }


def look(app, binding, tag: str, out: pathlib.Path, log: Log, sess) -> dict:
    """Tick the map, photograph it, and write down what it says."""
    for _ in range(binding.LIVE_EVERY + 1):
        try:
            binding.tick()
        except Exception as exc:
            log.say(f"  the poll raised: {type(exc).__name__}: {exc}")
            log.emit("poll_raised", tag=tag, error=f"{type(exc).__name__}: {exc}")
        app.processEvents()
    st = binding.state
    seen = reading(binding, tag)
    seen["row14"] = status_row(sess)
    # What the mapper concluded from those bytes, beside the bytes: a heading
    # or window that disagrees with `$033D` and `$49C3` is the mapper's
    # reading, not the game's.
    seen["mapper_window"] = st.window
    seen["mapper_paint"] = resident_paint(binding)
    seen["mapper_heading"] = st.heading
    seen.update(probes(sess))
    log.emit("look", **seen)
    log.say(f"  [{tag}] map says {seen['where_label']!r} / {seen['area_strip']!r}"
            f"  source={st.source!r} geo={seen['geo_loaded']}"
            f"  row14={seen['row14'].strip()!r}")
    log.say(f"        {seen['dungeon_49C0']=} {seen['travel_49C3']=} "
            f"{seen['live_C04B']=} {seen['indoors_49E6']=}")
    log.say(f"        {seen['heading_033D']=} {seen['mapper_window']=} "
            f"{seen['mapper_heading']=}")
    shot(app, binding.root, out / f"{tag}-window.png")
    shot(app, binding.canvas, out / f"{tag}-map.png")
    sess.kbd.screenshot(str(out / f"{tag}-game.png"))
    return seen


def wait_indoors(sess, log: Log, seconds: float) -> str:
    """Wait for a trip *off* the travel grid to actually finish.

    **Not `clear_bars(want_outdoors=False)`, and the difference cost a run.**
    That one asks `Session.indoors`, which reads `$49E6` -- the byte
    `come_home` has just written -- so it answered "arrived" straight away,
    while the game had not yet so much as asked for the disk.  Four looks
    later the emulator was still sitting on `INSERT SIDE # 2, AND PRESS ANY
    KEY` with the wilderness status line frozen on the screen, which the map
    faithfully went on reporting.

    What says the trip is over is the screen: an indoor command bar, and the
    word `OUTDOORS` gone from row 14.  Disk prompts are answered on the way.
    """
    deadline = time.time() + seconds
    while time.time() < deadline:
        s = sess.screen()
        if s is None:
            time.sleep(1.0)
            continue
        if sess.handle_prompt(s):
            continue
        row = s.row(24)
        if "OUTDOORS" not in s.row(14):
            # Either bar counts, and the second one is why this says "bar"
            # rather than "world": a party put back indoors by `come_home`
            # lands on the dungeon's own movement prompt, `I,J,K,M, RETURN OR
            # BUTTON`, not on the command bar -- the same thing
            # `Session.outdoor_key` says about a walked exit on to the grid.
            # A run that waited for `MOVE ENCAMP` alone reported `stuck` for a
            # party that was standing in the Slums.
            if ("MOVE" in row and "ENCAMP" in row) or "I,J,K,M" in row:
                return "bar"
        if "PRESS" in row:
            sess.kbd.key("Return")
        else:
            for label in ("STAY", "NO"):
                if label in row:
                    log.say(f"    answering {label} to |{row.strip()}|")
                    if not sess.select_bar(label, timeout=8):
                        sess.kbd.key("Return")
                    break
        time.sleep(1.2)
    return "stuck"


def write_square(target, square) -> None:
    """Write the travel square `$49C3`/`$49C4`, which is all `FastTravel` writes for a window."""
    target.write(fasttravel.POOL_OF_RADIANCE.travel_square, bytes(square[:2]))


def come_home(args, sess, target, app, binding, out, log, step: int) -> int:
    """Bring the party back off the travel grid, into `--home`'s area.

    **There is no supported way to do this and that is the point.**  A fast
    travel out of an overland area into an indoors one wedges the loader for
    ever -- `LOADFILES` dispatches on `$49E6` and asks for a `SQRDATA` the
    indoor area has not got, and the game sits on `INSERT SIDE # n` with the
    PC in the KERNAL's serial routines (`docs/50-experiments.md`).  That is
    why `FastTravel.legality` refuses the trip outright, and why this is a
    probe in a tool rather than anything the window offers.

    The same experiment ends "so `$49E6` has to be right **before** `$2034`",
    which was never tried.  This tries it: write `1` into `$49E6`, then make
    the ordinary `FastTravel`, whose own rejection then no longer fires because
    it re-reads the byte.  Whether the loader is satisfied by that is the
    measurement, and either answer should be written down -- what this run
    needs it for is the only crossing the offscreen tests cannot make, a
    party walking back into the area it left.

    `$49E6` is written for exactly this call.  `automap/actions.py` reads it
    and never writes it, and nothing here changes that.
    """
    from goldbox.areas import AREAS_BY_ID
    area = AREAS_BY_ID[args.home]
    before = target.read(fasttravel.POOL_OF_RADIANCE.indoors, 1)
    target.write(fasttravel.POOL_OF_RADIANCE.indoors, b"\x01")
    after = target.read(fasttravel.POOL_OF_RADIANCE.indoors, 1)
    log.say(f"$49E6 {before.hex()} -> {after.hex()}, so LOADFILES will ask for "
            f"a GEO rather than a SQRDATA")
    log.emit("indoors_poke", before=before.hex(), after=after.hex())
    for _ in range(8):                       # the busy retry `--travel` makes
        outcome = actions.FastTravel().apply(target, area=area,
                                             arrival=args.arrival)
        if outcome.ok or "busy" not in outcome.message:
            break
        time.sleep(1.0)
    log.say(f"Fast Travel home to {area.name}: ok={outcome.ok} {outcome.message}")
    log.emit("fasttravel_home", area=area.name, ok=outcome.ok,
             message=outcome.message)
    if outcome.ok:
        answered = wait_indoors(sess, log, seconds=args.arrive)
        log.say(f"after the trip home the game is showing: {answered}")
        log.emit("fasttravel_home_arrival", outcome=answered)
        sess.settle(3)
    step += 1
    look(app, binding, f"{args.tag}-step{step}", out, log, sess)
    return step


#: How many encounters a run fights before it stops answering them, so a party
#: that keeps meeting monsters cannot hold a slot for ever.
MAX_ENCOUNTERS = 5

#: How long a chosen `COMBAT` waits for the combat grid before the fight is
#: given up, in seconds.
FIGHT_GRID_WAIT = 60.0

#: How long the encounter menu's `FLEE` waits for the travel prompt or the
#: combat grid, in seconds; the same budget as a chosen `COMBAT`'s grid.
FLEE_SETTLE_WAIT = FIGHT_GRID_WAIT

#: The other words on an outdoor encounter's opening menu; one of them must be
#: on row 24 beside `COMBAT` for it to be taken for that menu.
ENCOUNTER_OTHERS = ("FLEE", "PARLAY")


def encounter_bar(sess, log: Log | None = None) -> str | None:
    """Row 24 when it is an outdoor encounter's opening menu, else None.

    `COMBAT` alone is not enough: a message row can carry the word, and the
    session's own `walk_one` never answers an outdoor menu (`walk_outdoors`
    does not consult `walk_encounter`), so this is the detector.  The menu
    also offers `FLEE` and `PARLAY`, which a message does not, and the travel
    grid's direction prompt carries none of them.
    """
    row = encounter_row(sess, log)
    return None if row is None else row.strip()


def _read_indoors(sess, log: Log | None = None):
    """`Session.indoors`, or None when the read failed (logged).

    `Session.indoors` raises on a monitor timeout, and one transient timeout
    must not end a run minutes after its boot.
    """
    try:
        return sess.indoors()
    except Exception as exc:
        if log is not None:
            log.say(f"  the indoors read failed: {type(exc).__name__}: {exc}")
            log.emit("indoors_read_failed",
                     error=f"{type(exc).__name__}: {exc}")
        return None


def encounter_menu(row: str, indoors) -> str | None:
    """`row` (screen row 24) when it is an encounter menu on the travel grid, else None.

    Anything but a definite `indoors is False`, including a failed read, is
    no encounter for this look.
    """
    if indoors is not False:
        return None
    if S.OUTDOOR_PROMPT in row or S.word_column(row, S.ENCOUNTER_FIGHT) < 0:
        return None
    if all(S.word_column(row, w) < 0 for w in ENCOUNTER_OTHERS):
        return None
    return row


def encounter_row(sess, log: Log | None = None) -> str | None:
    """Row 24 when it is an encounter menu on the travel grid, else None."""
    s = sess.screen()
    if s is None:
        return None
    return encounter_menu(s.row(24), _read_indoors(sess, log))


def encounter_after_press(sess, looks: int = 3, gap: float = 1.0,
                          log: Log | None = None) -> str | None:
    """The encounter bar, if one comes up just after a press.

    One look while the travel prompt is up, because a step that lands on the
    grid has not got an encounter coming; the few seconds of polling are for
    a step that ends in an encounter and has not drawn its menu yet, which is
    a screen that is not the prompt.
    """
    for n in range(looks):
        s = sess.screen()
        if s is not None and S.OUTDOOR_PROMPT in s.row(24):
            return None
        row = encounter_bar(sess, log)
        if row is not None:
            return row
        if n + 1 < looks:
            time.sleep(gap)
    return None


def press_state(sess) -> dict:
    """`$033D` and the travel square, in one stop, for a press's before and after."""
    return probes(sess, ("heading_033D", "travel_49C3"))


def fight_encounter(args, sess, log: Log, bar: str, move: str,
                    step: int) -> str | None:
    """Take an outdoor encounter's `COMBAT`, fight it out, wait for the grid.

    Returns None when the party won or ran and the travel prompt is back, else
    the reason the walk cannot go on.  A lost fight is not resumed even if the
    grid comes back.
    """
    log.say(f"Encounter at step {step} (after {move}): |{bar}|")
    log.emit("encounter", step=step, move=move, bar=bar,
             **press_state(sess))
    if args.on_encounter == "flee" and sess.select_bar("FLEE", timeout=8):
        log.say("  FLEE selected")
        log.emit("encounter_choice", step=step, choice="flee")
        tactic = Flight(log)
        settled, row = _after_menu_flee(sess, log)
        log.say(f"  after FLEE: {settled} |{row}|")
        log.emit("encounter_flee", step=step, outcome=settled, row=row)
        if settled == "grid":
            # The bar's own FLEE got the party away without a fight.
            log.emit("encounter_outcome", step=step, outcome=S.RAN, turns=0)
            return _wait_for_grid(args, sess, log, step)
        if settled != "combat":
            log.emit("encounter_outcome", step=step, outcome="unsettled",
                     row=row)
            return (f"FLEE ended on neither the combat grid nor the travel "
                    f"prompt in {FLEE_SETTLE_WAIT:.0f}s (row 24 |{row}|)")
        # The monsters caught the party: the fight is run off the map.
    else:
        choice = "fight" if args.on_encounter == "fight" else "flee-unavailable"
        log.emit("encounter_choice", step=step, choice=choice)
        if not sess.select_bar(S.ENCOUNTER_FIGHT, timeout=8):
            log.say("  COMBAT could not be selected")
            log.emit("encounter_outcome", step=step, outcome="not-selected")
            return "COMBAT could not be selected"
        # Flight is the tactic that steps off the combat map, so a run asked
        # to flee that has to fight still tries to.
        tactic = S.Session.melee_turn if args.on_encounter == "fight" else Flight(log)
        # `sess.fight` reports NOT_FIGHTING when no combat grid is up yet, and
        # a grid can take longer than 20 s to draw, so it is asked only once
        # the grid is there.
        if not _fight_began(sess, FIGHT_GRID_WAIT):
            log.say("  the combat grid never appeared")
            log.emit("fight_not_begun", step=step, waited=FIGHT_GRID_WAIT)
            return "the combat grid never appeared"
    result = sess.fight(budget=args.fight_budget, tactic=tactic)
    log.say(f"  fight: {result.outcome} in {result.turns} turns, "
            f"{result.seconds:.0f}s")
    log.emit("encounter_outcome", step=step, outcome=result.outcome,
             turns=result.turns, blows=result.blows,
             seconds=round(result.seconds, 1), bars=result.bars[-12:])
    if result.outcome in (S.NOT_FIGHTING, S.LOST, S.BUDGET):
        return f"the fight ended {result.outcome}"
    return _wait_for_grid(args, sess, log, step)


def _after_menu_flee(sess, log: Log,
                     wait: float | None = None) -> tuple[str, str]:
    """Where the encounter menu's FLEE left the game: `("grid" | "combat" | "unsettled", row 24)`.

    A FLEE the party gets away with returns to the travel prompt; one the
    monsters answer with combat goes to the combat grid, which outdoors can
    take longer than 20 s to draw.  Only those two screens settle it, so a
    slow grid is never taken for an escape.  On the way a disk prompt is
    answered and a `PRESS` row gets Return; nothing else is pressed.
    """
    wait = FLEE_SETTLE_WAIT if wait is None else wait
    deadline = time.time() + wait
    row = ""
    while time.time() < deadline:
        if sess.in_combat():
            return "combat", row
        s = sess.screen()
        if s is None:
            time.sleep(1.0)
            continue
        if sess.handle_prompt(s):
            continue
        row = s.row(24).strip()
        if S.OUTDOOR_PROMPT in row and _read_indoors(sess, log) is False:
            return "grid", row
        if "PRESS" in row:
            sess.kbd.key("Return")
        time.sleep(1.0)
    return "unsettled", row


def _fight_began(sess, wait: float = 20.0) -> bool:
    """Wait up to `wait` seconds for the combat grid; False when the game never drew it."""
    deadline = time.time() + wait
    while not sess.in_combat():
        if time.time() >= deadline:
            return False
        time.sleep(1.0)
    return True


def answer_disk_prompt(args, sess, log: Log, step: int,
                       moved: bool | None = None) -> tuple[bool, str | None]:
    """Answer an `INSERT SIDE # n` prompt on row 24 and wait for the travel prompt.

    Returns `(answered, reason)`.  `(False, None)` means there was no prompt,
    or it went away while the answer was being retried.  `(True, None)` means
    the prompt was answered and the travel prompt is back.  `(True, reason)`
    means it was answered but the grid did not come back, for instance after a
    wrong grid.  `(False, reason)` means the prompt was not answered: the side
    is not in the slot, the attach raised, or the retries ran out.
    """
    s = sess.screen()
    want = None if s is None else sess.wanted_disk(s)
    if want is None:
        return False, None
    name = os.path.basename(want)
    row = s.row(24).strip()
    log.say(f"Disk prompt at step {step}: |{row}| -> {name}")
    if not os.path.exists(want):
        log.emit("disk_prompt", step=step, side=name, bar=row, moved=moved,
                 outcome="no-such-disk")
        return False, f"the game asked for {name}, which is not in the slot"
    answered = False
    try:
        # `handle_prompt` holds off for two seconds after an earlier answer.
        for _ in range(3):
            if sess.handle_prompt(s):
                answered = True
                break
            time.sleep(2.1)
            s = sess.screen() or s
            if sess.wanted_disk(s) is None:
                return False, None                  # the prompt went away by itself
    except Exception as exc:                        # an attach that raised
        log.emit("disk_prompt", step=step, side=name, bar=row, moved=moved,
                 outcome=f"attach-failed: {type(exc).__name__}: {exc}")
        return False, f"{name} could not be attached ({type(exc).__name__}: {exc})"
    if not answered:
        log.emit("disk_prompt", step=step, side=name, bar=row, moved=moved,
                 outcome="not-answered")
        return False, f"the prompt for {name} was not answered"
    grid = clear_bars(sess, log, seconds=args.encounter_wait, want_outdoors=True,
                      stop_on_encounter=True)
    log.emit("disk_prompt", step=step, side=name, bar=row, moved=moved,
             outcome=grid)
    if grid == "encounter":
        # The step the prompt interrupted ended in an encounter; it is met as
        # any other one is, and the walk resumes from the grid it leaves.
        bar = encounter_bar(sess, log)
        if bar is None:
            return True, f"no travel prompt after {name} (the encounter bar went away)"
        if args.on_encounter == "stop" or args.encounters >= MAX_ENCOUNTERS:
            log.say(f"Encounter after {name}: |{bar}| -- stopping the walk")
            log.emit("encounter", step=step, move=name, bar=bar,
                     handled="stop", **press_state(sess))
            return True, ("the encounter limit was reached"
                          if args.on_encounter != "stop"
                          else "--on-encounter stop")
        args.encounters += 1
        return True, fight_encounter(args, sess, log, bar, name, step)
    return True, None if grid == "world" else f"no travel prompt after {name} ({grid})"


def _wait_for_grid(args, sess, log: Log, step: int) -> str | None:
    """None once the travel prompt is back, else why the walk cannot go on."""
    _, reason = answer_disk_prompt(args, sess, log, step)
    if reason is not None:
        return reason
    grid = clear_bars(sess, log, seconds=args.encounter_wait, want_outdoors=True)
    log.emit("encounter_grid", step=step, outcome=grid)
    return None if grid == "world" else f"no travel prompt after the fight ({grid})"


def _prompt_ate_the_press(sess, log: Log, before: dict, step: int) -> bool:
    """True when the travel square is still what it was before the press.

    Read after the answer, because the game finishes a step the prompt
    interrupted once the side is in.  A failed read is logged and is no
    evidence the press was lost, so it never repeats.
    """
    now = press_state(sess)
    square = now.get("travel_49C3")
    if square is None:
        log.emit("walk_repeat_unread", step=step, error=now.get("error"))
        return False
    return square == before.get("travel_49C3")


def walk_moves(args, sess, log: Log, moves: str, step: int, after_step) -> int:
    """Press each of `moves`, answering an outdoor encounter as `--on-encounter` says.

    `after_step(step)` photographs and logs the map after each press, and
    after an encounter ends -- the first travel tick before any key, which is
    where a stale combat heading in `$033D` would show.  Each press logs
    `$033D` and `$49C3` before and after it, so a press into a blocked square
    can be told from a step.  The interrupted press is not repeated.  Returns
    the last step number used; `args.stopped` is set to the reason when the walk ended early.
    """
    for move in moves:
        if args.stopped:
            break
        step += 1
        before = press_state(sess)
        moved = sess.walk_one(move)
        after = press_state(sess)
        log.say(f"Walk {move}: moved={moved}")
        log.emit("walk", move=move, moved=moved,
                 before=before, after=after)
        time.sleep(1.0)
        moved_square = before.get("travel_49C3") != after.get("travel_49C3")
        fought_before = args.encounters
        answered, reason = answer_disk_prompt(args, sess, log, step,
                                              moved=moved_square)
        # `answer_disk_prompt` counts an encounter it fights, so a rise says it did.
        fought = args.encounters > fought_before
        if fought:
            # Same look as after a fight of the walk's own: the first travel
            # tick before any key.
            step += 1
            after_step(step)
        if reason is not None:
            args.stopped = reason
            if not fought:
                after_step(step)
            break
        if fought:
            continue
        # An encounter only fires on a step that moved, so a fight means the
        # press was not eaten.
        if answered and _prompt_ate_the_press(sess, log, before, step):
            log.emit("walk_repeated", move=move, step=step)
            sess.walk_one(move)
        bar = encounter_after_press(sess, log=log)
        if bar is None:
            after_step(step)
            continue
        if args.on_encounter == "stop" or args.encounters >= MAX_ENCOUNTERS:
            log.say(f"Encounter at step {step}: |{bar}| -- stopping the walk")
            log.emit("encounter", step=step, move=move, bar=bar,
                     handled="stop", **press_state(sess))
            args.stopped = ("the encounter limit was reached"
                            if args.on_encounter != "stop"
                            else "--on-encounter stop")
            break
        args.encounters += 1
        reason = fight_encounter(args, sess, log, bar, move, step)
        step += 1
        after_step(step)
        if reason is not None:
            args.stopped = reason
    return step


def stopped_run(args, app, binding, out, log: Log, sess, step: int) -> int:
    """End a run whose walk stopped early: one last look, the reason, non-zero.

    Fast Travel, `--after`, `--home` and `--linger` would otherwise act on a
    party still sitting in an encounter, and the run would report success.
    """
    step += 1
    look(app, binding, f"{args.tag}-step{step}", out, log, sess)
    log.say(f"The walk stopped: {args.stopped}")
    log.emit("walk_stopped", reason=args.stopped, step=step)
    return 1


def run(args, log: Log) -> int:
    out = pathlib.Path(args.out)
    slot = S.claim_slot(args.slot, f"mapmarker/{pathlib.Path(args.disk).name}")
    log.say(f"slot {slot.n} display {slot.display}")
    sess = None
    try:
        boot = S.stage_disks(slot, pathlib.Path(args.disks))
        S.stage_writable(args.disk, pathlib.Path(slot.dir) / "SIDE0.D64")
        sess = S.Session(boot, slot=slot)
        if not sess.boot():
            raise RuntimeError("boot failed")
        if not sess.load_save():
            raise RuntimeError("the game did not load the save")
        if not sess.select_row("BEGIN ADVENTURING"):
            raise RuntimeError("BEGIN ADVENTURING could not be selected")
        arrived = answer_bars(sess, log, args.answer, seconds=args.arrive)
        if arrived != "world":
            raise RuntimeError(f"no world bar {args.arrive}s after BEGIN ADVENTURING")
        sess.settle(3)
        where = sess.status()
        log.say(f"Status line: {'none' if where is None else where.where()}")
        log.emit("arrived", status=None if where is None else where.where())

        target = SessionTarget(sess, timeout=5.0)
        app, root, binding, maps = build_window(target, args.disks, out)
        log.say(f"the map window has {len(maps)} maps loaded")
        look(app, binding, f"{args.tag}-step0", out, log, sess)

        def looker(n):
            look(app, binding, f"{args.tag}-step{n}", out, log, sess)

        step = 0
        if args.start is not None:
            # Written before the first press so a run can begin beside the
            # square it is after and give random encounters fewer steps to
            # happen in. The screen redraws only on a step, hence the look
            # after the first press rather than a claim about this one.
            # The travel square means nothing indoors, where the same two
            # bytes belong to something else, so a party that is not known to
            # be on the grid is left where it is.
            try:
                inside = sess.indoors()
            except Exception as e:  # noqa: BLE001 -- a failed read is a rejection
                inside, why = None, f"the indoors read failed: {e}"
            else:
                why = "the party is indoors" if inside else "the indoors read gave no answer"
            if inside is not False:
                log.say(f"--start refused: {why}")
                log.emit("start_refused", reason=why)
                args.stopped = f"--start refused: {why}"
                return stopped_run(args, app, binding, out, log, sess, step)
            square = bytes(args.start[:2])
            write_square(target, args.start)
            back = target.read(fasttravel.POOL_OF_RADIANCE.travel_square, 2)
            log.say(f"started the party at {tuple(args.start)}; read back {back.hex()}")
            log.emit("start", x=args.start[0], y=args.start[1], read_back=back.hex())
            if bytes(back) != square:
                log.say(f"--start wrote {square.hex()} and read back {bytes(back).hex()}")
                log.emit("start_mismatch", wrote=square.hex(), read_back=bytes(back).hex())
                args.stopped = f"--start read back {bytes(back).hex()}, not {square.hex()}"
                return stopped_run(args, app, binding, out, log, sess, step)
            step += 1
            look(app, binding, f"{args.tag}-step{step}", out, log, sess)
        if args.turn:
            step = walk_moves(args, sess, log, args.turn * args.turns, step,
                              looker)
        step = walk_moves(args, sess, log, args.walk, step, looker)
        if args.stopped:
            return stopped_run(args, app, binding, out, log, sess, step)

        if args.travel is not None:
            # The window's own Fast Travel, which is how a party can be put on
            # the travel grid without an afternoon of play.  It is the action
            # the button drives, not a reimplementation of it, and the guards
            # are its own -- `$6E11`, the program counter, and the bar on
            # travel *off* the grid into an area with a disk to load.
            from goldbox.areas import AREAS_BY_ID
            area = AREAS_BY_ID[args.travel]
            # Retried, because one of its guards is where the 6502 happens to
            # be: about 3% of samples land in the KERNAL's interrupt path with
            # the party standing still, which the button waits out rather than
            # greying itself out (#152).
            for _ in range(8):
                outcome = actions.FastTravel().apply(target, area=area)
                if outcome.ok or "busy" not in outcome.message:
                    break
                time.sleep(1.0)
            log.say(f"Fast Travel to {area.name}: ok={outcome.ok} {outcome.message}")
            log.emit("fasttravel", area=area.name, ok=outcome.ok,
                     message=outcome.message)
            if outcome.ok:
                answered = clear_bars(sess, log, seconds=args.arrive,
                                      want_outdoors=area.outdoors)
                log.say(f"after the trip the game is showing: {answered}")
                log.emit("fasttravel_arrival", outcome=answered)
                sess.settle(3)
            step += 1
            look(app, binding, f"{args.tag}-step{step}", out, log, sess)
            if args.place is not None:
                # Put the party on a chosen travel square without walking to
                # it. `#189` did this to measure the compass and it is the
                # same two bytes `FastTravel` writes for a trip to a window,
                # so the mechanism is proven; what it buys here is a *chosen*
                # outdoor square, which is what makes the square the party
                # comes back to next door to the one it left from. The screen
                # does not redraw until a step, so a `--place` is only useful
                # with an `--after` move behind it.
                write_square(target, args.place)
                log.say(f"placed the party at {tuple(args.place)} on the grid")
                log.emit("place", x=args.place[0], y=args.place[1])
            step = walk_moves(args, sess, log, args.after, step, looker)
            if args.stopped:
                return stopped_run(args, app, binding, out, log, sess, step)

        if args.home is not None:
            step = come_home(args, sess, target, app, binding, out, log, step)

        for _ in range(args.linger):
            step += 1
            time.sleep(2.0)
            look(app, binding, f"{args.tag}-step{step}", out, log, sess)
        return 0
    finally:
        for what, fn in (("session close", lambda: sess and sess.close()),
                         ("slot teardown", slot.teardown),
                         ("slot release", slot.release)):
            try:
                fn()
            except Exception as exc:
                log.say(f"  {what} raised {type(exc).__name__}: {exc}")


def _pair(text: str) -> tuple[int, ...]:
    """`x,y` or `x,y,facing`, for the two options that name a square."""
    got = tuple(int(part) for part in text.split(","))
    if len(got) not in (2, 3):
        raise argparse.ArgumentTypeError("give x,y or x,y,facing")
    return got


def _square(text: str) -> tuple[int, int]:
    """`x,y` as two bytes, since `$49C3`/`$49C4` are one byte each."""
    got = tuple(int(part) for part in text.split(","))
    if len(got) != 2 or not all(0 <= n <= 255 for n in got):
        raise argparse.ArgumentTypeError("give x,y, each 0-255")
    return got


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--disk", required=True, help="the save .d64 to boot")
    p.add_argument("--disks", default=None,
                   help="where the player's game disks are; read, never written")
    p.add_argument("--slot", type=int, default=None, help="the pool slot")
    p.add_argument("--walk", default="",
                   help="Moves: I J K M in a dungeon, the compass digits 1-8 "
                        "on the travel grid")
    p.add_argument("--turn", default="", metavar="DIGIT",
                   help="Press this one compass digit at the start, before "
                        "--walk, logging $033D and $49C3 around each press: "
                        "into a blocked square it shows whether the heading "
                        "changes while the square does not")
    p.add_argument("--turns", type=int, default=1,
                   help="How many times --turn is pressed")
    p.add_argument("--on-encounter", choices=("fight", "stop", "flee"), default="fight",
                   help="What to do when a press lands on an outdoor "
                        "encounter: fight it out with melee and resume the "
                        "walk, log it and stop the walk, or take FLEE "
                        "(fighting with the flee tactic when the bar does "
                        "not offer it or the party is caught); a fight can "
                        "take --fight-budget seconds and a run fights up to "
                        f"{MAX_ENCOUNTERS} encounters, so the worst case is "
                        "that many budgets plus the waits after each")
    p.add_argument("--fight-budget", type=float, default=300.0,
                   help="Seconds --on-encounter fight gives one fight")
    p.add_argument("--encounter-wait", type=float, default=120.0,
                   help="Seconds to wait for the travel prompt after a fight")
    p.add_argument("--travel", type=int, default=None,
                   help="After the walk, Fast Travel to this area id -- 26 is "
                        "the wilderness's middle window, which is how a party "
                        "reaches the travel grid without playing there")
    p.add_argument("--after", default="",
                   help="Moves to make after the Fast Travel")
    p.add_argument("--home", type=int, default=None,
                   help="After those moves, come back off the travel grid "
                        "into this area id -- 20 is the Slums, which is the "
                        "area a party fast travelled to 26 left. $49E6 is "
                        "written to 1 first; see `come_home`")
    p.add_argument("--place", type=_pair,
                   help="Write $49C3/$49C4 after the Fast Travel: `x,y` on "
                        "the travel grid, so the next `--after` move ends on "
                        "a chosen square")
    p.add_argument("--start", type=_square,
                   help="`x,y` written to $49C3/$49C4 once the party is on the "
                        "travel grid and before --turn and --walk, so the walk "
                        "begins beside a chosen square")
    p.add_argument("--arrival", type=_pair,
                   help="`x,y` or `x,y,facing` for `--home` to land on, "
                        "written to $C04B: an area with no arrival square of "
                        "its own otherwise lands wherever its script leaves "
                        "the party")
    p.add_argument("--linger", type=int, default=0,
                   help="Extra looks after the last move, one every two "
                        "seconds: an area change is a disk load and the map "
                        "settles a poll or two after the game does")
    p.add_argument("--answer", default="NO",
                   help="what to answer a YES NO bar the arrival puts up")
    p.add_argument("--out", default=str(scratch.scratch_dir("mapmarker")),
                   help="where the screenshots and the log go")
    p.add_argument("--tag", default=None, help="prefix for the screenshots")
    p.add_argument("--arrive", type=float, default=240.0,
                   help="seconds to wait for the world bar after BEGIN "
                        "ADVENTURING")
    args = p.parse_args(argv)
    if len(args.turn) > 1 or (args.turn and args.turn not in "12345678"):
        p.error("--turn takes one compass digit, 1-8")
    args.encounters = 0
    args.stopped = False
    if args.disks is None:
        if DISKS is None:
            raise SystemExit("No game disks found. Set $POR_DISKS.")
        args.disks = str(DISKS)
    args.tag = args.tag or pathlib.Path(args.disk).stem.lower()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    _offscreen()
    log = Log(out / f"{args.tag}.jsonl")
    try:
        return run(args, log)
    finally:
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
