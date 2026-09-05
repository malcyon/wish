#!/usr/bin/env python3
"""Photograph the automapper's own map while a driven party walks.

The question `#198 (Does the automapper draw a live party on the travel grid,
or leave the marker where it entered?)` asks is not what memory says -- it is
what a player looking at the map window sees.  So this drives a real session
with `tools/session.py`, builds the **real** map tab offscreen against the same
emulator, ticks it, and saves a PNG of the window and of the map canvas after
every step.

    env -u WAYLAND_DISPLAY -u XDG_SESSION_TYPE QT_QPA_PLATFORM=offscreen \\
        GDK_BACKEND=x11 .venv/bin/python tools/mapmarker.py \\
        --disk work/p50-outdoor/OUTC.D64 --slot 2 --walk 1357

Three things make it a fair reproduction of what a player has rather than a
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

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap import actions  # noqa: E402
from automap.paths import find_disks  # noqa: E402
from tools import session as S  # noqa: E402
from tools.savecheck import Log, answer_bars  # noqa: E402

#: Where the player keeps the C64 disks.  Read, never written -- the sides are
#: copied into the slot and the game only ever sees the copies.
DISKS = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")

#: The bytes worth writing down beside every screenshot, and why each one is
#: here.  `$49E6` says which of the two worlds the party is in; `$49C0` is the
#: dungeon triple, which freezes outdoors at the square the party left the grid
#: on; `$49C3` is the live travel square; `$C04B` is `Game.live_position`, the
#: engine's own triple and what `party_fix` falls back to.
PROBES = {
    "indoors_49E6": (0x49E6, 1),
    "dungeon_49C0": (0x49C0, 3),
    "travel_49C3": (0x49C3, 2),
    "live_C04B": (0xC04B, 3),
    "area_6E1B": (0x6E1B, 1),
}


class SessionTarget:
    """A `Target` over a `Session`'s monitor, opened per burst.

    `ViceTarget` holds one connection for a whole session, which is right for
    the shipped window and wrong here: `Session` needs the monitor too, for
    the screen reads that drive the menus, and VICE serves exactly one
    binary-monitor connection.  Opening per burst is what lets one process do
    both.

    `fix` is the method `read_fix` prefers, and it is deliberately the same
    call `ViceTarget.fix` makes -- `party_fix` over a monitor `read`, inside
    one stop/resume.  If that is wrong out here, it is wrong in the shipped
    window in exactly the same way.
    """

    def __init__(self, sess):
        self.sess = sess

    def read(self, addr: int, length: int) -> bytes:
        with self.sess.mon(5) as m:
            return m.read(addr, length)

    def write(self, addr: int, data: bytes) -> None:
        with self.sess.mon(5) as m:
            m.write(addr, data)

    def read_blocks(self, blocks):
        with self.sess.mon(5) as m:
            return [m.read(addr, length) for addr, length in blocks]

    def fix(self, game=None):
        from automap.target import party_fix
        with self.sess.mon(5) as m:
            return party_fix(m.read, game)

    def close(self) -> None:
        pass

    # -- what Fast Travel asks for, and only that -------------------------
    # `automap.actions` reaches the CPU either through a target's own `pc` and
    # `set_pc` or through a `ViceTarget`'s held monitor.  This target has no
    # held monitor, so it offers the pair -- the same two monitor commands,
    # made on a connection that is opened and closed around them.

    def pc(self):
        from automap.actions import pc_register
        with self.sess.mon(5) as m:
            return m.registers().get(pc_register(m))

    def set_pc(self, address: int) -> None:
        from automap.actions import pc_register
        with self.sess.mon(5) as m:
            m.set_registers({pc_register(m): address})


def probes(sess) -> dict:
    """The addresses in `PROBES`, as hex, in one stop of the machine."""
    try:
        with sess.mon(5) as m:
            return {name: m.read(addr, length).hex()
                    for name, (addr, length) in PROBES.items()}
    except Exception as exc:                       # a read that failed is data
        # Every key still comes back, because `look` writes them into its own
        # line.  Returning only the error truncated a whole run on the first
        # transient timeout, minutes after the boot that paid for it.
        failed = {name: None for name in PROBES}
        failed["error"] = f"{type(exc).__name__}: {exc}"
        return failed


def status_row(sess) -> str:
    """Row 14 verbatim -- the line `party_fix` matches against."""
    s = sess.screen()
    return "" if s is None else s.row(14)


def clear_bars(sess, log: Log, answers=("STAY", "NO"), seconds: float = 180.0,
               want_outdoors: bool | None = None) -> str:
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
        if ("MOVE" in row and "ENCAMP" in row) or S.OUTDOOR_PROMPT in row:
            # `is (not want_outdoors)` rather than `is not want_outdoors`, so
            # a failed read -- `Session.indoors` answers None for one -- waits
            # rather than counting as an arrival.
            if want_outdoors is None or sess.indoors() is (not want_outdoors):
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
    `tools/shotstrip.py` and `tools/shotwindow.py` use: set it to look at the
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
    for var, name in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data")):
        os.environ[var] = str((out / name).resolve())


def build_window(target, disks: str, out: pathlib.Path):
    """The real map tab, offscreen, with its own settings and notes."""
    private_settings(out)
    from PyQt6.QtWidgets import QApplication, QMainWindow

    from automap.maps import load_maps_titled
    from automap.state import Automapper
    from automap.window import AutomapBinding
    from wish.ui_window import Ui_WishWindow

    app = QApplication.instance() or QApplication([])
    maps, game = load_maps_titled(disks)
    root = QMainWindow()
    ui = Ui_WishWindow()
    ui.setupUi(root)
    root.ui = ui
    mapper = Automapper(target, maps,
                        title=game.title if game is not None else None)
    # `drive=False` is how `wish/window.py` builds it: the host owns the
    # connection and calls `tick()`, so nothing polls behind this script's back
    # while `Session` is driving the game's menus.
    binding = AutomapBinding(root, mapper, drive=False, disks=disks)
    root.resize(1500, 950)
    root.show()
    app.processEvents()
    return app, root, binding, maps


def shot(app, widget, path: pathlib.Path) -> None:
    app.processEvents()
    widget.grab().save(str(path))


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
    seen = {
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
        "row14": status_row(sess),
    }
    seen.update(probes(sess))
    log.emit("look", **seen)
    log.say(f"  [{tag}] map says {seen['where_label']!r} / {seen['area_strip']!r}"
            f"  source={st.source!r} geo={seen['geo_loaded']}"
            f"  row14={seen['row14'].strip()!r}")
    log.say(f"        {seen['dungeon_49C0']=} {seen['travel_49C3']=} "
            f"{seen['live_C04B']=} {seen['indoors_49E6']=}")
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
    the ordinary `FastTravel`, whose own refusal then no longer fires because
    it re-reads the byte.  Whether the loader is satisfied by that is the
    measurement, and either answer is worth writing down -- what this run
    needs it for is the only crossing the offscreen tests cannot make, a
    party walking back into the area it left.

    `$49E6` is written for exactly this call.  `automap/actions.py` reads it
    and never writes it, and nothing here changes that.
    """
    from goldbox.areas import AREAS_BY_ID
    area = AREAS_BY_ID[args.home]
    before = target.read(actions.FASTTRAVEL_INDOORS, 1)
    target.write(actions.FASTTRAVEL_INDOORS, b"\x01")
    after = target.read(actions.FASTTRAVEL_INDOORS, 1)
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


def run(args, log: Log) -> int:
    import shutil

    out = pathlib.Path(args.out)
    slot = S.claim_slot(args.slot, f"mapmarker/{pathlib.Path(args.disk).name}")
    log.say(f"slot {slot.n} display {slot.display}")
    sess = None
    try:
        boot = S.stage_disks(slot, pathlib.Path(args.disks))
        shutil.copy(args.disk, pathlib.Path(slot.dir) / "SIDE0.D64")
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

        target = SessionTarget(sess)
        app, root, binding, maps = build_window(target, args.disks, out)
        log.say(f"the map window has {len(maps)} maps loaded")
        look(app, binding, f"{args.tag}-step0", out, log, sess)

        step = 0
        for move in args.walk:
            step += 1
            moved = sess.walk_one(move)
            log.say(f"Walk {move}: moved={moved}")
            log.emit("walk", move=move, moved=moved)
            time.sleep(1.0)
            look(app, binding, f"{args.tag}-step{step}", out, log, sess)

        if args.travel is not None:
            # The window's own Fast Travel, which is how a party can be put on
            # the travel grid without an afternoon of play.  It is the action
            # the button drives, not a reimplementation of it, and the guards
            # are its own -- `$6E11`, the program counter, and the refusal to
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
                target.write(actions.FASTTRAVEL_TRAVEL_X,
                             bytes(args.place[:2]))
                log.say(f"placed the party at {tuple(args.place)} on the grid")
                log.emit("place", x=args.place[0], y=args.place[1])
            for move in args.after:
                step += 1
                moved = sess.walk_one(move)
                log.say(f"Walk {move}: moved={moved}")
                log.emit("walk", move=move, moved=moved)
                time.sleep(1.0)
                look(app, binding, f"{args.tag}-step{step}", out, log, sess)

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


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--disk", required=True, help="the save .d64 to boot")
    p.add_argument("--disks", default=str(DISKS),
                   help="where the player's game disks are; read, never written")
    p.add_argument("--slot", type=int, default=None, help="the pool slot")
    p.add_argument("--walk", default="",
                   help="Moves: I J K M in a dungeon, the compass digits 1-8 "
                        "on the travel grid")
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
    p.add_argument("--out", default="work/mapmarker",
                   help="where the screenshots and the log go")
    p.add_argument("--tag", default=None, help="prefix for the screenshots")
    p.add_argument("--arrive", type=float, default=240.0,
                   help="seconds to wait for the world bar after BEGIN "
                        "ADVENTURING")
    args = p.parse_args(argv)
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
