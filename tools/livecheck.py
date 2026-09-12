#!/usr/bin/env python3
"""Run the shipped automapper tab against a running game, feature by feature.

`#34 (Validate the live automapper tab per title)` asks for the live tab to be
validated on each title rather than on Pool of Radiance alone, in the order its
own body sets out: draw the map and walk it, cross an area boundary and read
the area byte either side, the roster cards, the condition and quickfight
badges, and each of the five live actions.

    tools/livecheck.py --title curse --pool 3 --out work/issue34/curse1
    tools/livecheck.py --title ssb --walk MMII --no-actions

**Everything it reports is read through the code the window ships.**
`automap.state.Automapper.poll()` is what moves the marker, `automap.live.
read_snapshot` is what fills a roster card, `automap.live.badges` is what
lights one, and `automap.actions.HealParty` and friends are what the five
buttons run. A tool that re-derived any of those would be measuring itself:
the point of this file is to be the *caller*, and nothing more.

**The screen is read through the banks, not through the processor's view.**
`SessionTarget.fix` builds `automap.vice.banked(mon)` and hands the pair to
`party_fix`, so `$D011`, `$D018` and `$DD00` come out of the chips even while
the loader has them banked out -- `#336` and `#421`. A target without that
answers a byte of RAM at each of those addresses and computes a screen nothing
is displaying, which reads as a frozen game.

**A staged byte is an input, not a result.** Three checks write before they
read: a wound before Heal party, the quickfight bit before Quickfight off, a
hidden-name bit before Identify. In each case the write is the *situation* the
button exists for and the button's own code is what is being measured -- the
alternative is a run that reports "nothing to heal" and calls it a pass.

Each check answers `pass`, `fail` or `unreached`, and `unreached` is a result:
a party with no items cannot exercise Identify, and saying so is the honest
answer rather than a fail. Output is one JSON line per event as it happens,
plus a `livecheck.json` at the end and an SVG of whatever map got drawn.

The player's disks are copied into the pool slot and read only; nothing is
written where they lie.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap import actions as act  # noqa: E402
from automap import live, render  # noqa: E402
from automap import state as mapstate  # noqa: E402
from automap.area import OURS, ResidentGeo  # noqa: E402
from automap.maps import load_maps  # noqa: E402
from automap.state import Automapper  # noqa: E402
from automap.target import party_fix  # noqa: E402
from automap.vice import banked  # noqa: E402
from goldbox import c64_port, items, savegame  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from tools import gamedisks  # noqa: E402
from tools import session as por  # noqa: E402

#: Where this run's notes and explored squares go.
#:
#: **Not `$XDG_DATA_HOME`, and that is the whole point of the note.** The first
#: version of this file assigned that variable, which is what `automap.paths.
#: data_dir` reads -- and every VICE this tool launches then failed to start
#: at all: `porlaunch.sh` runs the emulator under Flatpak, a Flatpak *user*
#: installation lives under `$XDG_DATA_HOME/flatpak`, and with the variable
#: moved `flatpak run net.sf.VICE` could not see the installed application. It
#: fell back to the system installation, defaulted to the `master` branch and
#: reported `app/net.sf.VICE/x86_64/master not installed` into the slot's
#: `vice.log`, three seconds into a three-minute boot.
#:
#: So the redirection is made where it is needed and nowhere else: this is the
#: one function `AutomapState.notes_path` goes through, and rebinding it here
#: leaves the environment the emulator inherits exactly as it was. Nothing
#: under test is replaced -- `save_notes`, `load_notes` and `migrate_flat_
#: notes` are the shipped ones and still run.
RUN_DATA = ROOT / "work" / "issue34" / "data"


def redirect_notes(root=RUN_DATA) -> None:
    """Point the notes at `root` instead of the player's own data directory.

    **Called from `main`, never at import.** It used to run at module level,
    and `tests/test_livecheck.py` imports this module at *its* module level --
    so under `pytest -n auto`, where every worker collects every file, the
    rebinding landed in every worker before a single test ran. From then on
    every note test in `tests/test_automap.py` read and wrote one shared
    directory rather than its own `tmp_path`, and eight of them failed by
    seeing each other's notes. `automap.paths.data_dir()` was never called,
    which is why instrumenting it found nothing: the redirection is one layer
    above it.

    `#428 (Ten automapper note tests fail under parallel load but pass alone,
    so a green suite depends on how busy the machine is)` has the whole
    account. The rule it leaves behind: **a tool may not rebind a shipped
    function at import time**, because a test that imports the tool imports
    the rebinding with it.
    """
    mapstate._data_dir = lambda: root           # noqa: SLF001

PASS, FAIL, UNREACHED = "pass", "fail", "unreached"

#: The specimen tree, where the engine-written save disks this boots live.
SPECIMENS = pathlib.Path(
    os.environ.get("WISH_SPECIMENS") or pathlib.Path.home() / "wish-specimens")


class SessionTarget:
    """`automap`'s Target over a driven session's monitor.

    One connection per call rather than one held open, because the session
    itself needs the monitor between polls -- it drives the keyboard, reads
    the screen and answers disk prompts -- and VICE serves exactly one binary
    monitor connection at a time.

    `fix` and `read_blocks` are the two optional capabilities `automap.target`
    looks for with `getattr`. Answering them is what keeps a poll to one
    connection each, and `fix` is where the banks come in: without it
    `read_fix` would fall through to `screen_banks(self)`, and this class's
    `banks()` would then be asked for readers that outlive the connection they
    were made on.
    """

    def __init__(self, sess, timeout: float = 8.0):
        self.sess = sess
        self.timeout = timeout
        self.reads = 0
        self.writes: list[tuple[int, int]] = []

    def read(self, addr: int, length: int) -> bytes:
        self.reads += 1
        with self.sess.mon(self.timeout) as m:
            return m.read(addr, length)

    def write(self, addr: int, data) -> None:
        self.writes.append((addr, len(data)))
        with self.sess.mon(self.timeout) as m:
            m.write(addr, bytes(data))

    def read_blocks(self, blocks) -> list[bytes]:
        """Several ranges in one connection, honouring a block's named bank."""
        with self.sess.mon(self.timeout) as m:
            pair = banked(m)
            out = []
            for block in blocks:
                addr, length = block[0], block[1]
                want = block[2] if len(block) > 2 else None
                if want is None or pair is None:
                    out.append(m.read(addr, length))
                else:
                    out.append(getattr(pair, want)(addr, length))
            return out

    def fix(self, game=None):
        """`party_fix` with the screen read through the chips.

        None where the banks cannot be got at at all, which is the answer
        `#336` asked for: the caller keeps its last reading rather than
        believing an address computed off the RAM under the registers.
        """
        with self.sess.mon(self.timeout) as m:
            pair = banked(m)
            if pair is None:
                return None
            return party_fix(m.read, game, pair)

    def banks(self):
        """The capability `automap.target.screen_banks` looks for.

        Each reader opens its own connection, so the pair survives being held
        past the call that made it. Slower than `fix`'s single connection and
        used only by callers that ask for the pair rather than for a fix.
        """
        from automap.screen import Banks

        def io_read(addr: int, length: int) -> bytes:
            with self.sess.mon(self.timeout) as m:
                pair = banked(m)
                return (pair.io if pair else m.read)(addr, length)

        def ram_read(addr: int, length: int) -> bytes:
            with self.sess.mon(self.timeout) as m:
                pair = banked(m)
                return (pair.ram if pair else m.read)(addr, length)

        return Banks(io_read, ram_read)

    # -- the CPU, which Fast Travel needs and `Target` does not carry ------
    #
    # `automap.actions.program_counter` reaches the CPU two ways: a target
    # with a `pc()` of its own, or the monitor a `ViceTarget` is holding on
    # `_mon`. This holds no monitor between calls, so it answers for itself --
    # and without these two, `FastTravel.legality` refuses with "this backend
    # cannot read the CPU", which is what the first Silver Blades run got.

    def pc(self):
        from automap.actions import pc_register
        with self.sess.mon(self.timeout) as m:
            return m.registers().get(pc_register(m))

    def set_pc(self, address: int) -> None:
        from automap.actions import pc_register
        with self.sess.mon(self.timeout) as m:
            m.set_registers({pc_register(m): address})


# -- booting each title -------------------------------------------------------


class Title:
    """One title's boot, which is the only genuinely per-release part.

    Everything below the title screen is `tools/session.py`'s, and everything
    above the monitor is `automap`'s; this class is the seam between them and
    holds nothing else.
    """

    def __init__(self, key: str, registry: str, save: str):
        self.key = key
        self.registry = registry
        self.save = save          # a file in the specimen tree

    @property
    def game(self):
        return c64_port.by_key(self.key)

    def disks(self, given: str = "") -> str:
        found = given or str(gamedisks.find(self.registry) or "")
        if not found:
            raise SystemExit(
                f"no {self.key} disks: pass --disks or set the registry entry")
        return found

    def default_save(self) -> str:
        for where in (SPECIMENS / "por-c64", SPECIMENS / "coab-c64",
                      SPECIMENS / "ssb-dos"):
            path = where / self.save
            if path.exists():
                return str(path)
        raise SystemExit(f"no save disk: {self.save} is not in {SPECIMENS}")

    def boot(self, slot, disks: str, save: str, note, wait: float):
        raise NotImplementedError


class PoolOfRadiance(Title):
    def boot(self, slot, disks, save, note, wait):
        first = por.stage_disks(slot, disks)
        save_disk = _stage_save(slot, save)
        sess = por.Session(first, slot=slot)
        sess.save_disk = save_disk
        _own_title(sess, self.game)
        if not sess.boot():
            return sess, "boot-failed"
        if not sess.load_save():
            return sess, "load-failed"
        if not sess.begin_adventuring():
            return sess, "world-failed"
        return sess, "world"


class Curse(Title):
    def boot(self, slot, disks, save, note, wait):
        from tools import curseload, curserun, cursewarp

        first = curserun.stage(slot, disks, save)
        save_disk = str(pathlib.Path(slot.dir) / "SIDE0.D64")
        os.chmod(save_disk, 0o644)      # the specimen tree copy is read-only
        sess = curserun.CurseSession(first, slot=slot)
        sess.save_disk = save_disk
        _own_title(sess, self.game)
        if not sess.boot():
            return sess, "boot-failed"
        outcome = curseload.load_saved_game(sess, note=note, wait=wait)
        if outcome != "loaded":
            return sess, f"load-{outcome}"
        sess.patch_disk_prompt()
        if not cursewarp.enter_world(sess, timeout=wait):
            return sess, "world-failed"
        cursewarp.clear_messages(sess)
        return sess, "world"


class SilverBlades(Title):
    def boot(self, slot, disks, save, note, wait):
        from tools import ssbwarp

        first = ssbwarp.stage(slot, disks, save)
        save_disk = str(pathlib.Path(slot.dir) / "SIDE0.D64")
        os.chmod(save_disk, 0o644)
        sess = ssbwarp.SSBSession(first, slot=slot)
        sess.save_disk = save_disk
        _own_title(sess, self.game)
        if not sess.boot():
            return sess, "boot-failed"
        if not ssbwarp.load_party(sess, timeout=wait):
            return sess, "load-failed"
        addr = ssbwarp.Addresses(self.game, disks)
        if not ssbwarp.enter_world(sess, addr, timeout=wait):
            return sess, "world-failed"
        return sess, "world"


def _own_title(sess, game) -> None:
    """Tell the driver which title it is driving.

    `Session.game` is what `indoors()` and `square_and_world()` ask, and it
    defaults to Pool of Radiance. `tools/curserun.py`'s subclass sets it;
    `tools/ssbwarp.py`'s `SSBSession` does not, so a Silver Blades party
    standing in a dungeon read as being on the travel grid and `walk_one`
    refused every key without pressing one -- `#360`'s defect, fixed for one
    of the two later titles. Setting it here makes this file right whichever
    driver it is handed, and the miss is filed rather than patched in a driver
    three other tools share.
    """
    sess.game = game


def _stage_save(slot, save: str) -> str:
    """`SIDE0.D64` is always replaced, and the copy is ours to be written.

    A pool slot is reused, so whatever the last tenant left in `SIDE0` is
    another game's save disk -- which is how a Curse run once wrote four
    characters beside Pool of Radiance's (`tools/curserun.py`).
    `por.stage_writable` unlinks it first and gives the copy the write bit
    back, since a specimen out of `$WISH_SPECIMENS` is read-only by design
    (`#472`).
    """
    return por.stage_writable(save, pathlib.Path(slot.dir) / "SIDE0.D64")


TITLES = {
    # **New Phlan rather than the Slums**, and it is not a preference: the
    # Slums party walked four squares into a wandering encounter on the first
    # run of this file, `$6E11` went to 2, and Heal party, Fast Travel and
    # Level up all refused -- correctly, and with nothing measured. A town map
    # has no wandering monsters. This save also carries seventeen items with
    # sixteen readied, which is what the Identify check and the roster card's
    # readied line need.
    "por": PoolOfRadiance("pool-of-radiance", "pool-of-radiance",
                          "WISH-SPEC-por-amiga-newphlan-c64-resave.D64"),
    # **The Curse default carries items and the other two do not.** It is
    # the only Curse save anybody has with an item area in it -- the shipped
    # Tilverton party after a shopping trip, `#32` -- and without one the
    # Identify check has nothing to work on and answers `unreached`.
    "curse": Curse("curse-of-the-azure-bonds", "curse-of-the-azure-bonds",
                   "WISH-SPEC-curse-party-with-items.D64"),
    "ssb": SilverBlades("secret-of-the-silver-blades",
                        "secret-of-the-silver-blades",
                        "WISH-SPEC-ssb-d-engine-resave-walked.D64"),
}


# -- the checks ---------------------------------------------------------------


class Run:
    """One title's validation: the checks, in the issue's own order."""

    #: How long to let the mapper look for the area before giving up on it.
    IDENTIFY_FOR = 40.0
    #: The poll interval the window itself uses, so the cadence being measured
    #: is the shipped one rather than a tighter one this file invented.
    INTERVAL = 0.2

    def __init__(self, title: Title, sess, out: pathlib.Path, note,
                 disks: str, save: str):
        self.title = title
        self.game = title.game
        self.sess = sess
        self.out = out
        self.note = note
        self.disks = disks
        self.save = save
        self.target = SessionTarget(sess)
        self.maps = load_maps(disks, self.game)
        self.mapper = Automapper(self.target, self.maps, title=self.game.title)
        self.names = live.item_names(disks, self.game)
        self.results: list[dict] = []

    # -- helpers ---------------------------------------------------------

    def record(self, id_: str, feature: str, result: str, **evidence) -> dict:
        row = {"check": id_, "feature": feature, "result": result, **evidence}
        self.results.append(row)
        self.note(event="check", **row)
        return row

    def safely(self, id_: str, feature: str, fn, *a) -> dict:
        """Run one check, turning a crash into that check's own result."""
        try:
            return fn(*a)
        except Exception as exc:                          # pragma: no cover
            import traceback
            return self.record(id_, feature, FAIL,
                               why=f"{type(exc).__name__}: {exc}",
                               traceback=traceback.format_exc()
                               .splitlines()[-6:])

    def poll_for(self, seconds: float) -> int:
        """Drive the shipped poller for a while, and say how many ticks ran."""
        ticks, deadline = 0, time.time() + seconds
        while time.time() < deadline:
            try:
                self.mapper.poll()
            except Exception as exc:                      # pragma: no cover
                self.note(event="poll-error", error=str(exc))
            ticks += 1
            time.sleep(self.INTERVAL)
        return ticks

    def snapshot(self):
        return live.read_snapshot(self.target, self.names, self.game)

    def snapshot_until(self, timeout: float = 30.0):
        """A snapshot, waiting out a menu or a load rather than failing on one.

        `read_snapshot` answers None in camp, in a menu, mid-load and at the
        title screen, all of which are ordinary. The window holds its last
        good one; a check has nothing to hold, so it waits.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            snap = self.snapshot()
            if snap is not None:
                return snap
            time.sleep(0.5)
        return None

    def wait_for_dungeon(self, timeout: float = 90.0) -> int | None:
        """Poll `LINKER`'s dispatch byte until it reads 1, answering prompts.

        Returns whatever it last read: 1 means DUNGEON is resident and every
        action and Fast Travel can act, 2 is a fight, None is a machine that
        would not answer.
        """
        deadline, state = time.time() + timeout, None
        while time.time() < deadline:
            state = act.mode(self.target, self.game)
            if state == 1:
                return state
            self.sess.handle_prompt()
            time.sleep(1.0)
        return state

    # -- 1. draw the map -------------------------------------------------

    def check_map(self) -> dict:
        """C7: the map is identified, drawn, and says whose it is."""
        deadline = time.time() + self.IDENTIFY_FOR
        while time.time() < deadline and not self.mapper.state.geo:
            self.mapper.poll()
            time.sleep(self.INTERVAL)
        state = self.mapper.state
        resident = ResidentGeo(self.target).identify(self.maps)
        verdict, named = ResidentGeo(self.target).verdict(self.maps)
        evidence = {
            "area": state.area, "label": state.area_label,
            "geo_drawn": state.geo is not None,
            "title_check": self.mapper.title_check,
            "resident_identify": resident, "verdict": verdict,
            "verdict_map": named, "maps_loaded": len(self.maps),
            "square": [state.x, state.y], "facing": state.facing_letter,
            "source": state.source,
            # `LINKER`'s own dispatch byte -- 1 DUNGEON, 2 COMBAT. Every
            # action and Fast Travel gate on it, so a run that finds it at 2
            # is a run whose refusals mean "in a fight" rather than
            # "unsupported".
            "mode_flag": act.mode(self.target, self.game),
        }
        if state.geo is not None:
            self.draw(state, "map")
            evidence["svg"] = "map.svg"
        result = PASS if (state.geo is not None
                          and self.mapper.title_check == OURS) else FAIL
        return self.record("C7", "the map is identified and drawn", result,
                           **evidence)

    def draw(self, state, tag: str) -> None:
        """The drawn map, as the shipped renderer draws it.

        `render.to_svg` is the same geometry the window paints and needs no
        Qt, so a run leaves behind a picture a person can look at rather than
        a claim that something was drawn.

        **Two pictures, because they answer different questions.** `<tag>.svg`
        is the whole map, which says the `GEO` decoded; `<tag>-explored.svg`
        draws only what the party has been shown, which is the reveal the
        window actually paints and is the one that changes as it walks.

        `visible` is `visible(x, y) -> bool` and not a set -- handing the set
        itself in raised `'set' object is not callable` inside
        `map_primitives`, silently, on the first run of this file.
        """
        seen = set(state.exploration.seen)
        pictures = {tag: None}
        if seen:
            pictures[f"{tag}-explored"] = lambda x, y: (x, y) in seen
        for name, visible in pictures.items():
            try:
                svg = render.to_svg(state.geo, visible=visible,
                                    party=(state.x, state.y, state.facing),
                                    notes=state.notes or None)
            except Exception as exc:                      # pragma: no cover
                self.note(event="draw-failed", tag=name, error=str(exc))
                continue
            (self.out / f"{name}.svg").write_text(svg, encoding="utf-8")

    # -- 2. walk it ------------------------------------------------------

    def check_walk(self, moves: str) -> dict:
        """C7: the marker follows the party and the explored set grows."""
        if not moves:
            return self.record("C7W", "the marker follows a walk", UNREACHED,
                               why="no --walk route given")
        state = self.mapper.state
        before = (state.x, state.y, state.facing)
        seen_before = len(state.exploration)
        steps = []
        for move in moves:
            was = (state.x, state.y, state.facing)
            took = self.sess.walk_one(move)
            self.poll_for(1.2)
            now = (state.x, state.y, state.facing)
            # **The driver's own reading of the same fact.** `Session.status`
            # parses the game's status line for itself; the automapper reaches
            # it through `party_fix`. Two readers of one line is what makes
            # "the marker followed" a measurement rather than the mapper
            # agreeing with itself, and it is the only comparison here that
            # could catch a marker one step behind.
            said = self.sess.status()
            steps.append({"key": move, "session_says_moved": bool(took),
                          "refused": self.sess.walk_refused,
                          "mapper": [state.x, state.y, state.facing_letter],
                          "status_line": None if said is None else said.where(),
                          "agrees": said is not None and not said.outdoors
                          and (said.x, said.y, said.facing) == now,
                          "mapper_changed": now != was,
                          "source": state.source})
            self.note(event="step", **steps[-1])
        after = (state.x, state.y, state.facing)
        seen_after = len(state.exploration)
        moved = after != before
        cand = state.candidates
        if state.geo is not None:
            self.draw(state, "walked")
        # **A step nobody asked for is not a wall**, and telling the two apart
        # is what makes this check about the automapper rather than about the
        # driver. `Session.walk_refused` is set when the driver decided not to
        # press a key at all; a key that was pressed and moved nothing is the
        # game refusing the step, which the mapper is entitled to see and is
        # itself evidence (`Automapper._refused`).
        unpressed = [s["key"] for s in steps if s["refused"]]
        # **A route can end where it started and still be followed.** `JIKI`
        # against a wall is turn, blocked, turn back, blocked -- the marker
        # tracked both turns and the start and the end are the same reading,
        # which the first Pool of Radiance run reported as a failure to
        # follow. So the verdict is per step: the marker changed whenever the
        # driver saw the game accept the input, and every step the marker and
        # the game's own status line agree.
        agree = [s for s in steps if s["agrees"]]
        followed = all(s["mapper_changed"] == s["session_says_moved"]
                       for s in steps)
        # **The verdict is the status-line agreement, not the driver's
        # boolean.** `walk_one` re-sends a move up to four times and answers
        # whether the status line moved during *its* retries, sampled before
        # this poll; the marker is read afterwards. So the two can honestly
        # disagree about one step -- a Curse run had the driver report a move
        # whose square was back where it started by the time the marker was
        # read -- and comparing them measures when each one looked rather
        # than whether the marker followed. What does answer that is the
        # marker against the game's own status line, read at the same moment,
        # which is `agrees`. `followed` stays in the record as evidence.
        result = (PASS if steps and len(agree) == len(steps)
                  and any(s["mapper_changed"] for s in steps)
                  and seen_after >= seen_before else FAIL)
        return self.record(
            "C7W", "the marker follows a walk", result,
            before=list(before), after=list(after), moved=moved,
            explored_before=seen_before, explored_after=seen_after,
            steps_where_the_marker_matched_the_status_line=len(agree),
            steps_taken=len(steps), marker_followed_every_step=followed,
            keys_the_driver_never_pressed=unpressed,
            whose_fault=("the driver, not the automapper" if unpressed
                         and not moved else None),
            candidates=str(cand) if cand else None, steps=steps,
            svg="walked.svg" if state.geo is not None else None)

    # -- 3. cross a boundary ---------------------------------------------

    def check_boundary(self, to_area: int | None) -> dict:
        """C6: the area byte and the resident map, either side of a crossing.

        The crossing is made with `automap.actions.FastTravel` -- the code a
        player clicking Fast Travel runs -- because a walked boundary needs a
        route somebody has already found, and this needs none.
        """
        rows = [r for r in act.area_rows(self.game.title) if r.fasttravelable]
        if not rows:
            return self.record("C6", "the area is re-read across a boundary",
                               UNREACHED, why="no fast-travel rows for this "
                                              "title")
        # **Wait for the loader to say DUNGEON before asking.** `FastTravel.
        # legality` refuses with "Fast travel cannot act right now" whenever
        # the mode flag is not 1, and a walk can leave the game on a script
        # menu or half-way through a load, which is what the first Curse run
        # hit. Waiting is not weakening the check: a player clicking the
        # button is a player who is looking at the world.
        settled = self.wait_for_dungeon()
        before = self.area_reading()
        # **The row has to be a different *map*, not a different area id.**
        # Silver Blades' areas 4 and 16 both draw `GEO10`, so the first run
        # here travelled from one to the other and the block at `$0400` never
        # changed -- which is not a boundary the automapper could see, and
        # reported as a failure of the reader rather than of the choice.
        here = before.get("resident")
        pick = None
        for row in rows:
            if to_area is not None and row.id != to_area:
                continue
            if row.id == before.get("area_byte") or not row.geos:
                continue
            if here is not None and here in row.geos:
                continue
            pick = row
            break
        if pick is None:
            return self.record("C6", "the area is re-read across a boundary",
                               UNREACHED,
                               why="no row that draws a different map",
                               before=before)
        ft = act.FastTravel(self.game)
        # **Wait for the button to become legal, rather than asking once.**
        # `FastTravel.legality` also requires the program counter to be inside
        # `DUNGEON`'s key-wait loop or the key fetcher it calls, and a walk
        # leaves the machine wherever the last keypress left it: the Pool of
        # Radiance run refused here with the mode flag reading 1, which is the
        # PC arm rather than the mode arm. A player clicking the button is a
        # player looking at the world, so waiting for that state is the check
        # rather than a way round it.
        deadline, verdict = time.time() + 120.0, ft.legality(self.target, pick)
        while not verdict and time.time() < deadline:
            self.sess.handle_prompt()
            time.sleep(1.0)
            verdict = ft.legality(self.target, pick)
        if not verdict:
            return self.record("C6", "the area is re-read across a boundary",
                               UNREACHED, why=f"Fast Travel refused: "
                                              f"{verdict.reason}",
                               before=before, to=pick.id,
                               mode_flag=settled)
        outcome = ft.apply(self.target, area=pick,
                           arrival=_arrival(pick))
        self.note(event="fasttravel", to=pick.id, ok=outcome.ok,
                  message=outcome.message)
        # A landing comes off a floppy: give the loader time and answer any
        # disk prompt it puts up on the way.
        deadline = time.time() + 300.0
        after = before
        while time.time() < deadline:
            self.sess.handle_prompt()
            self.mapper.poll()
            after = self.area_reading()
            if after.get("resident") in pick.geos:
                # **The machine arriving is not the mapper noticing.**
                # `Automapper._check_resident` runs every `RESIDENT_EVERY`
                # polls, so breaking on the first reading that shows the new
                # block asks the mapper about an area change it has not been
                # given a tick to see. The first Silver Blades run failed here
                # with `$0400` reading GEO20 and `state.area` still GEO10.
                self.poll_for(20.0)
                after = self.area_reading()
                break
            time.sleep(1.0)
        state = self.mapper.state
        if state.geo is not None:
            self.draw(state, "arrived")
        # **The resident map is what decides, and the header byte is
        # evidence.** `ResidentGeo` is an exact byte match of the block the
        # game is drawing against the disk copies, so it is the reading the
        # automapper itself runs on; `SaveGame0.area` is the save image's own
        # byte, which only says where the party was when the image was last
        # written and may still name the area it left.
        arrived = after.get("resident") in pick.geos
        changed = arrived and after.get("resident") != before.get("resident")
        return self.record(
            "C6", "the area is re-read across a boundary",
            PASS if changed and state.area == after.get("resident") else FAIL,
            before=before, after=after, to=pick.id,
            to_maps=list(pick.geos), mode_flag_before=settled,
            header_byte_followed=after.get("area_byte") == pick.id,
            mapper_area=state.area, label=state.area_label,
            travel_ok=outcome.ok, travel_message=outcome.message)

    def area_reading(self) -> dict:
        """The area byte the save image holds, and the map that is resident.

        Two independent answers to "where is the party": the header byte
        `SaveGame0.area_file` reads, and an exact byte match of the block at
        `$0400` against the disks. `#34` asks for the byte either side of a
        boundary; the resident map is the corroborator.
        """
        out: dict = {}
        try:
            save0_bytes, _ = live.read_blocks(self.target, self.game)
            sg0 = savegame.SaveGame0.from_bytes(bytes(save0_bytes), self.game)
            out["area_file"] = sg0.area_file
            out["area_byte"] = sg0.area
        except Exception as exc:
            out["error"] = str(exc)
        out["resident"] = ResidentGeo(self.target).identify(self.maps)
        return out

    # -- 4. the roster cards ---------------------------------------------

    def check_roster(self) -> dict:
        """C12: every card's numbers, against the save disk read cold."""
        snap = self.snapshot_until()
        if snap is None:
            return self.record("C12", "the roster cards read the party", FAIL,
                               why="read_snapshot answered None for 30s")
        cards = [{
            "slot": c.slot, "name": c.name, "class": c.class_text,
            "level": c.level_text, "hp": c.hp, "hp_max": c.hp_max,
            "ac": c.armour_class, "thac0": c.thac0,
            "experience": c.experience,
            "classes": [{"name": p.name, "level": p.level,
                         "experience": p.experience,
                         "fraction": p.fraction,
                         "next": p.next_threshold} for p in c.classes],
            "readied": list(c.readied), "quickfight": c.quickfight,
            "down": c.down, "drained": c.levels_drained,
        } for c in snap.characters]
        cold = self.cold_party()
        agree, disagree = _cross(cards, cold)
        classed = [c for c in cards if c["class"] != "?"]
        result = FAIL if (not cards or disagree or len(classed) != len(cards)) \
            else PASS
        return self.record(
            "C12", "the roster cards read the party", result,
            characters=len(cards), cards=cards, cold=cold,
            fields_agreeing=agree, disagreements=disagree,
            item_names_loaded=self.names is not None,
            readied_total=sum(len(c["readied"]) for c in cards))

    def cold_party(self) -> list[dict]:
        """The same party read straight off the save disk, as the oracle.

        A live read and a file read of the same party are two independent
        sources, which is what makes a matching name and hit point maximum
        evidence rather than an assertion that the reader is self-consistent.
        """
        try:
            disk = D64.open(self.save)
            _game, sg0, sg1 = savegame.load_save(disk, self.game)
        except Exception as exc:
            self.note(event="cold-read-failed", error=str(exc))
            return []
        out = []
        for slot in sg0.marching_order:
            block = sg1.roster(slot.index) if sg1 else None
            out.append({"slot": slot.index, "name": slot.record.name,
                        "hp_max": slot.record.get("hp_max"),
                        "experience": slot.record.get("experience"),
                        "hp": block.hit_points if block and block.occupied
                        else None})
        return out

    # -- 5. the badges ---------------------------------------------------

    #: The effect id staged in front of the badge check. **Hasted**, and it is
    #: the one glyph in `live.CONDITION_BADGES` that covers exactly one id, so
    #: a badge drawn from it can only have come from this row.
    BADGE_ID = 39

    def check_badges(self) -> dict:
        """C13: a badge, drawn from an effect staged into the party's own
        arrays -- and the refusal, where the title has no table.

        **Nothing else would draw one.** No save this project holds for any
        title has a spell running, so a badge check over what is there
        measures the corpus: it reports "no badge drawn", which is also what a
        broken `badges()` reports. So one effect row is written into the four
        arrays the way the game writes one -- id at `+$000`, owner at `+$040`,
        duration at `+$080`, magnitude at `+$280`, the offsets
        `goldbox/effects.py` carries and `#31` measured in all three titles --
        and the card is then read back through `live.read_snapshot`.

        On Silver Blades the pass is the *opposite* outcome: `live.
        BADGE_TABLES` gives that title no groups, so the id must land in
        `unbadged_effects` and no glyph may appear. That is `#196`'s deliberate
        refusal, and a glyph there would be a picture asserting a meaning
        nobody has read.
        """
        snap = self.snapshot_until()
        if snap is None:
            return self.record("C13", "the condition badges", FAIL,
                               why="no snapshot")
        groups = live.condition_badges(self.game)
        who = snap.characters[0]
        base = self.game.save_load_address
        rows = ((live.EFFECT_ID_OFFSET, self.BADGE_ID),
                (live.EFFECT_OWNER_OFFSET, who.slot),
                (live.EFFECT_DURATION_OFFSET, 8),
                (live.EFFECT_MAGNITUDE_OFFSET, 0))
        was = {at: self.target.read(base + at, 1)[0] for at, _v in rows}
        for at, value in rows:
            self.target.write(base + at, bytes([value]))
        lit = self.snapshot_until(10.0) or snap
        card = next((c for c in lit.characters if c.slot == who.slot), None)
        per = [{"name": c.name,
                "badges": [g for g, _ in c.conditions],
                "tooltips": [t for _, t in c.conditions],
                "effects": [e.id for e in c.effects],
                "unbadged": [e.id for e in c.unbadged_effects]}
               for c in lit.characters]
        party = {"badges": [g for g, _ in lit.party_badges],
                 "whole_party_effects": [e.id
                                         for e in lit.whole_party_effects],
                 "unbadged": [e.id for e in lit.unbadged_party_effects]}
        carried = bool(card and self.BADGE_ID in [e.id for e in card.effects])
        drew = bool(card and card.conditions)
        unbadged = bool(card and self.BADGE_ID
                        in [e.id for e in card.unbadged_effects])
        for at, value in was.items():
            self.target.write(base + at, bytes([value]))
        # With a table, the staged id has to reach a glyph; without one it has
        # to reach the debug log's list instead and draw nothing.
        result = PASS if carried and (drew if groups else
                                      unbadged and not drew) else FAIL
        return self.record(
            "C13", "the condition badges", result,
            groups=len(groups), refuses_by_design=not groups,
            staged_effect=self.BADGE_ID, staged_on=who.name,
            payload_offsets=[f"${base + at:04X}" for at, _v in rows],
            the_card_carries_it=carried, a_badge_was_drawn=drew,
            it_landed_in_unbadged=unbadged,
            badges_on_that_card=(list(per[0]["badges"]) if per else []),
            per_character=per, party=party)

    def check_quickfight(self) -> dict:
        """C14 and C19 together: light the badge, then clear it with the button.

        The bit is staged because no save this project holds has one set, and
        a check that reports "nobody was on quickfight" measures the corpus
        rather than the program. Staging it is `#34`'s own step 4 made
        reachable: the byte is the situation, `Character.quickfight` is the
        badge reading it, and `ClearQuickfight` is the button.
        """
        flag = act.quickfight_flag(self.game)
        if flag is None:
            return self.record("C14", "the quickfight badge", UNREACHED,
                               why="no roster page for this title")
        snap = self.snapshot_until()
        if snap is None:
            return self.record("C14", "the quickfight badge", FAIL,
                               why="no snapshot")
        slot = snap.characters[0].slot
        addr = flag.address(slot)
        was = self.target.read(addr, 1)[0]
        self.target.write(addr, bytes([was | live.QUICKFIGHT_BIT]))
        lit = self.snapshot_until(10.0)
        on = bool(lit and lit.characters[0].quickfight)
        action = act.ClearQuickfight(game=self.game)
        verdict = action.legality(self.target)
        outcome = action.apply(self.target) if verdict else None
        after = self.snapshot_until(10.0)
        off = bool(after and not after.characters[0].quickfight)
        if not (on and off):
            # Put the byte back however the run went: a staged bit left set is
            # a save disk that quickfights on the next resave.
            self.target.write(addr, bytes([was]))
        return self.record(
            "C14", "the quickfight badge, lit and cleared",
            PASS if on and off else FAIL,
            slot=slot, address=f"${addr:04X}", was=was, badge_lit=on,
            legality=bool(verdict), reason=verdict.reason,
            outcome=None if outcome is None else outcome.message,
            badge_cleared=off)

    # -- 6. the live actions ---------------------------------------------

    def check_heal(self) -> dict:
        """C16: wound somebody, press Heal party, and read the roster back."""
        party = act.read_party(self.target, self.game)
        if party is None or not len(party):
            return self.record("C16", "Heal party", FAIL, why="no party read")
        who = next((m for m in party if m.hp > 1), None)
        if who is None:
            return self.record("C16", "Heal party", UNREACHED,
                               why="nobody is above 1 hit point to wound")
        addr = who.roster_base + act.ROSTER_HP_CURRENT
        was = self.target.read(addr, 1)[0]
        self.target.write(addr, bytes([1]))
        hurt = self.snapshot_until(10.0)
        wounded = next((c for c in hurt.characters if c.slot == who.slot),
                       None) if hurt else None
        action = act.HealParty(game=self.game)
        verdict = action.legality(self.target)
        outcome = action.apply(self.target) if verdict else None
        healed = self.snapshot_until(10.0)
        back = next((c for c in healed.characters if c.slot == who.slot),
                    None) if healed else None
        ok = bool(outcome and outcome.ok and back
                  and back.hp == min(back.hp_max, 0xFF))
        if not ok:
            self.target.write(addr, bytes([was]))
        return self.record(
            "C16", "Heal party", PASS if ok else FAIL,
            who=who.name, slot=who.slot, address=f"${addr:04X}",
            was=was, staged_to=1,
            card_showed_wounded=None if wounded is None else wounded.hp,
            legality=bool(verdict), reason=verdict.reason,
            message=None if outcome is None else outcome.message,
            writes=0 if outcome is None else len(outcome.writes),
            hp_after=None if back is None else back.hp,
            hp_max=None if back is None else back.hp_max)

    def check_spells(self) -> dict:
        """C17: save the memorised list, spoil it, and restore it.

        The list is spoiled before the restore for the reason
        `.claude/rules` gives about reading back your own write: with the
        bytes left alone, `RestoreSpells` writes nothing and a read-back that
        matches is the store's own copy coming home.
        """
        from goldbox import c64_codec

        # A `pathlib.Path`, not a string: `SpellStore._load` calls
        # `self.path.read_text()`, so a string raises `AttributeError`
        # the moment anything is stored.
        store = act.SpellStore(path=self.out / "spells.json")
        party = act.read_party(self.target, self.game)
        if party is None or not len(party):
            return self.record("C17", "Save and Restore spells", FAIL,
                               why="no party read")
        mem_at, mem_size = c64_codec.memorised_span(self.game)
        caster = next((m for m in party
                       if any(c64_codec.get_memorised(m.record, self.game))),
                      None)
        # **A memorised list is staged where there is none**, the same way the
        # wound and the quickfight bit are: the Curse party that carries items
        # has nobody with a spell prepared, and a check that answers
        # "unreached" there is measuring the corpus rather than the button.
        # Nothing about this action goes through the engine -- `StoreSpells`
        # reads the list and `RestoreSpells` writes it -- so an id put there
        # from outside is the same input a night's rest would have left.
        staged_for = None
        if caster is None:
            caster = party.by_slot(min(m.slot for m in party)) or next(iter(party))
            self.target.write(caster.record_base + mem_at,
                              bytes([1]) + bytes(mem_size - 1))
            staged_for = caster.name
            party = act.read_party(self.target, self.game)
            caster = party.by_slot(caster.slot)
        original = bytes(c64_codec.get_memorised(caster.record, self.game))
        save_action = act.StoreSpells(store=store, game=self.game)
        saved = save_action.apply(self.target, disk=self.save)
        addr = caster.record_base + mem_at
        spoiled = bytes(mem_size)         # what the answer cannot be
        self.target.write(addr, spoiled)
        mid = self.target.read(addr, mem_size)
        restore = act.RestoreSpells(store=store, game=self.game)
        outcome = restore.apply(self.target, disk=self.save)
        back = self.target.read(addr, mem_size)
        ok = bool(saved.ok and outcome and outcome.ok
                  and mid == spoiled and back == original)
        if not ok:
            self.target.write(addr, original)
        return self.record(
            "C17", "Save and Restore spells", PASS if ok else FAIL,
            who=caster.name, memorised_list_staged_for=staged_for,
            address=f"${addr:04X}", span=mem_size,
            memorised=[b for b in original if b],
            save_message=saved.message, spoiled_ok=mid == spoiled,
            restore_message=None if outcome is None else outcome.message,
            restored_exactly=back == original,
            names=list(store.names(self.save)))

    def check_identify(self) -> dict:
        """C18: hide an item's name, press Identify, and read the bits back.

        The item area is a copy fed from a master elsewhere -- a poked weight
        was reverted by the game -- so the read-back is the whole check and it
        is taken through `live.read_blocks`, not out of the writer's own hands.
        """
        party = act.read_party(self.target, self.game)
        if party is None or not len(party):
            return self.record("C18", "Identify", FAIL, why="no party read")
        found = None
        for m in party:
            base = m.item_base - self.game.save_load_address
            block = party.save0_bytes[base:base
                                      + items.ITEM_BLOCK_STRIDE]
            for n in range(items.ITEMS_PER_CHARACTER):
                raw = block[n * items.ITEM_SIZE:
                            (n + 1) * items.ITEM_SIZE]
                if len(raw) == items.ITEM_SIZE and any(raw):
                    found = (m, n, raw)
                    break
            if found:
                break
        if found is None:
            return self.record("C18", "Identify", UNREACHED,
                               why="this party carries no items")
        member, n, raw = found
        addr = member.item_base + n * items.ITEM_SIZE + 6
        was = raw[6]
        self.target.write(addr, bytes([was | items.HIDDEN_NAME_MASK]))
        staged = self.target.read(addr, 1)[0]
        action = act.IdentifyItems(game=self.game)
        verdict = action.legality(self.target)
        outcome = action.apply(self.target) if verdict else None
        after = self.target.read(addr, 1)[0]
        # **The write may not stick**, and this is the one action where that
        # is a documented hazard: the item area is a copy fed from a master
        # elsewhere, and a poked weight was reverted by the game. So the byte
        # is read again after the machine has run for a few seconds, through
        # `live.read_blocks` rather than out of the writer's hands.
        self.sess.settle(4)
        payload, _roster = live.read_blocks(self.target, self.game)
        later = payload[addr - self.game.save_load_address]
        ok = bool(outcome and outcome.ok
                  and staged & items.HIDDEN_NAME_MASK
                  and not after & items.HIDDEN_NAME_MASK)
        if not ok:
            self.target.write(addr, bytes([was]))
        return self.record(
            "C18", "Identify", PASS if ok else FAIL,
            who=member.name, item=n, address=f"${addr:04X}",
            flags_were=was, flags_staged=staged, flags_after=after,
            flags_after_four_seconds=later,
            reverted_by_the_game=bool(later & items.HIDDEN_NAME_MASK),
            legality=bool(verdict), reason=verdict.reason,
            message=None if outcome is None else outcome.message,
            writes=0 if outcome is None else len(outcome.writes))

    def check_levelup(self) -> dict:
        """C20: Level up offers a level where the trainer is measured, and
        refuses where it is not.

        **Both directions, because either alone passes for the wrong
        reason.** A verdict of "legal" says nothing unless the title's trainer
        has actually been read -- `#16 (Level Up assumes Pool of Radiance, and
        silently corrupts a Curse character)` is what happens when it has not
        -- and a refusal says nothing unless it is the *unsupported* refusal
        rather than "you are in a fight". So the pass is the agreement between
        `goldbox.levels.trainer_measured` and what the button says.
        """
        from goldbox import levels

        measured = levels.trainer_measured(self.game.key)
        action = act.LevelUp(self.game)
        verdict = action.legality(self.target)
        party = act.read_party(self.target, self.game)
        offers, blockers = {}, []
        if party is not None:
            for m in party:
                try:
                    offers[m.name] = act.LevelUp.offers(m.record, self.game)
                except Exception as exc:
                    offers[m.name] = f"error: {exc}"
            blockers = list(act.level_up_blockers(
                next(iter(party)).record, self.game))
        # **The refusal is in `run`, not in `legality`, and that is where it
        # has to be checked.** `Action.legality` only asks the loader's mode
        # flag, so it answers True on a title whose trainer nobody has
        # measured; what refuses is `level_up_blockers` inside `run`, and the
        # window additionally never builds the button (`roster.levelling`).
        # So on an unmeasured title the action is actually *run* and the
        # measurement is that it wrote nothing -- `#16` is what a title that
        # wrote something would look like.
        wrote = None
        if not measured and party is not None:
            outcome = action.apply(self.target,
                                   slot=next(iter(party)).slot)
            wrote = {"ok": outcome.ok, "message": outcome.message,
                     "writes": len(outcome.writes)}
        fighting = "during a fight" in verdict.reason
        if fighting:
            agrees = True
        elif measured:
            agrees = bool(verdict) and not blockers
        else:
            agrees = bool(blockers) and wrote is not None \
                and not wrote["ok"] and wrote["writes"] == 0
        return self.record(
            "C20", "Level up", PASS if agrees else FAIL,
            trainer_measured=measured, legality_passes=bool(verdict),
            reason=verdict.reason, refused_for_the_fight=fighting,
            blockers=blockers, ran_and_wrote=wrote, offers=offers)


def _arrival(row):
    a = getattr(row, "arrival", None)
    return None if a is None else (a.x, a.y, a.facing)


def _cross(cards, cold) -> tuple[int, list]:
    """Live cards against the cold read of the same save, field by field."""
    by_slot = {c["slot"]: c for c in cold}
    agree, disagree = 0, []
    for card in cards:
        other = by_slot.get(card["slot"])
        if other is None:
            disagree.append({"slot": card["slot"], "field": "slot",
                             "live": card["name"], "file": None})
            continue
        for field in ("name", "hp_max", "experience"):
            if card[field] == other[field]:
                agree += 1
            else:
                disagree.append({"slot": card["slot"], "field": field,
                                 "live": card[field], "file": other[field]})
    return agree, disagree


# -- the runner ---------------------------------------------------------------


def run(args) -> int:
    title = TITLES[args.title]
    out = pathlib.Path(args.out or f"work/issue34/{args.title}")
    out.mkdir(parents=True, exist_ok=True)
    logfile = (out / "livecheck.jsonl").open("a")

    def note(**kw):
        kw["t"] = round(time.time(), 2)
        logfile.write(json.dumps(kw, default=str) + "\n")
        logfile.flush()
        print(json.dumps(kw, default=str), flush=True)

    disks = title.disks(args.disks)
    save = args.disk or title.default_save()
    slot = por.claim_slot(args.pool, note=os.environ.get("POR_AGENT", "i34"))
    note(event="slot", n=slot.n, monitor=slot.port, cmd=slot.cmd_port,
         display=slot.display, dir=str(slot.dir), title=args.title,
         disks=disks, save=save)
    report = {"title": title.key, "game": title.game.title, "save": save,
              "disks": disks, "slot": slot.n}
    sess = None
    try:
        sess, state = title.boot(slot, disks, save, note, args.wait)
        report["boot"] = state
        note(event="boot", state=state)
        if state != "world":
            report["checks"] = []
            return 1
        run_ = Run(title, sess, out, note, disks, save)
        # **One check crashing must not cost the boot.** A boot is three to
        # five minutes and every check after the one that raised would be
        # thrown away with it, so a raised exception becomes that check's own
        # `fail` with the traceback in the evidence and the run carries on.
        run_.safely("C7", "the map is identified and drawn", run_.check_map)
        run_.safely("C12", "the roster cards read the party", run_.check_roster)
        run_.safely("C13", "the condition badges", run_.check_badges)
        # **The actions go before the walk**, because a walk can start a
        # fight and every one of them is refused in one. The first Pool of
        # Radiance run walked four squares out of the Slums into a wandering
        # encounter and measured nothing: Heal party, Fast Travel and Level
        # up each answered "refused during a fight", which is the gate
        # working and is not what this is here to find out.
        if not args.no_actions:
            run_.safely("C16", "Heal party", run_.check_heal)
            run_.safely("C17", "Save and Restore spells", run_.check_spells)
            run_.safely("C18", "Identify", run_.check_identify)
            run_.safely("C14", "the quickfight badge, lit and cleared",
                        run_.check_quickfight)
            run_.safely("C20", "Level up", run_.check_levelup)
        run_.safely("C7W", "the marker follows a walk",
                    run_.check_walk, args.walk)
        # **Last, and deliberately.** A landing comes off a floppy and the
        # jump is into the engine's own script handler; if it goes wrong the
        # machine is not readable afterwards, and every check that ran after
        # it would report a failure that belongs to the warp.
        if args.boundary:
            run_.safely("C6", "the area is re-read across a boundary",
                        run_.check_boundary, args.to_area)
        report["checks"] = run_.results
        report["reads"] = run_.target.reads
        report["writes"] = len(run_.target.writes)
        return 0 if all(c["result"] != FAIL for c in run_.results) else 2
    finally:
        counts: dict[str, int] = {}
        for row in report.get("checks", []):
            counts[row["result"]] = counts.get(row["result"], 0) + 1
        report["summary"] = counts
        (out / "livecheck.json").write_text(json.dumps(report, indent=2,
                                                       default=str))
        note(event="done", summary=counts, boot=report.get("boot"))
        if sess is not None:
            if args.serve:
                por.serve(sess)
            sess.close()
        slot.teardown()
        logfile.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--title", choices=sorted(TITLES), required=True)
    ap.add_argument("--disk", default="",
                    help="the save .d64 to boot; copied into the slot and "
                         "never written where it lies")
    ap.add_argument("--disks", default="",
                    help="where the player's sides are; read, never written")
    ap.add_argument("--pool", type=int, default=None)
    ap.add_argument("--walk", default="",
                    help="dungeon keys to send -- I forward, J left, "
                         "K right, M about")
    ap.add_argument("--boundary", action="store_true",
                    help="cross an area boundary with Fast Travel and read "
                         "the area byte either side")
    ap.add_argument("--to-area", type=lambda s: int(s, 0), default=None,
                    help="which area id to travel to, if not the first that "
                         "differs")
    ap.add_argument("--no-actions", action="store_true",
                    help="skip the five live actions")
    ap.add_argument("--wait", type=float, default=300.0,
                    help="seconds to wait for the load and for the world")
    ap.add_argument("--serve", action="store_true",
                    help="hand the session over on the command port at the "
                         "end instead of tearing it down")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)
    # After `parse_args`, so `--help` and a mistyped argument reach neither
    # this nor the emulator, and never at import -- see `redirect_notes`.
    redirect_notes()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
