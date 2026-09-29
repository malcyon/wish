#!/usr/bin/env python3
"""Watch a converted party's `WRITE_UNSOURCED` bytes through a DOS fight.

The measurement `#69 (No WRITE_UNSOURCED zero has been tested during combat)`
asks for.  `goldbox.dos_codec.write` leaves nine fields zero on the grounds that the
engine supplies its own value, and every measurement behind that is a load, a
`VIEW` and a resave **outside a fight**.  `tools/dos/dosfightrun.py` proved the
fight can be driven; this puts the debugger on the record while it happens.

**There is no read watchpoint.**  DOSBox-X's three memory breakpoints -- `BPM`,
`BPLM`, `BPPM` -- are all "memory change" (`docs/142-dosbox-x-debugger.md`),
so the direct question "is this byte read during a round" cannot be asked of
this emulator.  What can be asked, and is what this tool measures, is
**when the engine writes over our zero, relative to the fight's own phases**:
a field the engine rewrites before the first character's command bar appears
is a field whose zero no combat routine can have consumed as combat state,
because it was gone before any character acted.

How it runs, in order:

1. `goldbox.dos_codec.new_dos_save` builds a save from a C64 disk into a staged
   game tree -- no template, every `WRITE_UNSOURCED` byte zero;
2. DOSBox-X boots, the game loads the slot, and the party walks until a
   wandering encounter stops it at `COMBAT WAIT FLEE ADVANCE`;
3. Alt+Pause, a megabyte dumped, and each `CHRDAT<slot><n>.SAV` matched
   against it to find that character's live record -- the same recipe
   `docs/142-dosbox-x-debugger.md` used for the ECL variable array, and for
   the same reason: there is no symbol table;
4. the watched bytes are read live, `BPM`s are armed on them, and the
   spurious first hit each nonzero one owes is absorbed and counted;
5. `c` starts the fight, and the fight is driven with `q` while every hit is
   logged with the bar that was on screen when it fired and the `CS:IP` that
   wrote it.

Ground truth for "the party fought" is still the save file and never the
screen: experience rising in `CHRDAT<slot><n>.SAV`, as
`docs/149-driving-a-dos-fight.md` sets out.

Output -- a JSON report, the memory image and the PNGs -- goes under
a scratch directory (`--out`; by default `scratch.scratch_dir("dosfightwatch")`), never into the repository.

    tools/dos/dosfightwatch.py watch --c64 PORSAVE13.D64 --slot A
    tools/dos/dosfightwatch.py locate --slot A     # stop after step 3
    tools/dos/dosfightwatch.py truth --c64 PORSAVE13.D64 --slot A --engine-slot B

    tools/dos/dosfightwatch.py pile --folder /mnt/specimens/por-dos/WISH-SPEC-por-hireling-evoker-ff \\
        --place-like /mnt/specimens/por-dos/WISH-SPEC-por-amiga-slums-dos-resave/SAVGAMD.DAT --steps 60

`pile` measures the treasure split.  It installs a DOS save folder as it stands
(no conversion), walks to an encounter, watches the seven coin piles at `DS:0x67F4`
through a fight, reporting the split per pile, and reads the companion and party parts `C` and `A` at the
split's counting breakpoint in a second fight; see `measure_split`.  A folder
saved where no wandering encounter happens (the Training Hall) is moved to where
a donor save the DOS game wrote stands by `--place-like`, which rewrites the
area, resident map, DAX number, wallset and wallmap, zeroes and restages the ECL
buffer, and sets the square and the tail bytes, all in `SAVGAM?.DAT`; the report
counts the bytes that still differ from the donor.  The run stops before
booting if any character file of the installed slot then differs from the
folder's.

`truth` is the other half of the comparison: the same party saved back by the
game's own `ENCAMP > SAVE` before it is walked anywhere, then reloaded and
taken to an encounter menu, so what the engine holds at the moment a fight
starts can be set beside what a conversion holds there.

**The party has to be somewhere wandering encounters happen.**  Every save
disk on the player's shelf but two puts the party in New Phlan, area 0, which
has none; `PORSAVE13.D64` and `PORSAVE14.D64` are in the Slums, area 20, and
are the ones to convert for this.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from goldbox import (
    dos_codec,  # noqa: E402
    dos_savegame,  # noqa: E402
)
from goldbox import dos_port as dl  # noqa: E402
from goldbox.c64_port import POOL_OF_RADIANCE  # noqa: E402
from goldbox.d64 import load_payload  # noqa: E402
from tools.dos import dosbox, dosboxx, staging  # noqa: E402
from tools.dos.dosparty import wipe_roster  # noqa: E402
from tools.dos.dostrain import move_to  # noqa: E402
from tools.registry import scratch  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent.parent

#: Where a run's report, memory image and frames land.  Scratch, outside the
#: repository: a frame of the game is the game's own art.
OUT = scratch.scratch_dir("dosfightwatch")

#: `CHRDAT` offsets read directly, as `tools/dos/dosfightrun.py` does.
XP = 0x0AC
HP_CURRENT = 0x11B

#: Every bar that means a fight has started, and at which the walk must stop.
#:
#: **`encounter` is not the only one.**  A run that stopped only at
#: `COMBAT WAIT FLEE ADVANCE` walked into a fight, was handed `MOVE VIEW AIM
#: USE ... QUICK DONE`, pressed `q` at it because `PoolOfRadiance.COMBAT_KEYS`
#: has a key for it, and fought the whole encounter with no watchpoint armed --
#: counting it as one of ten "prompts".  The party then reached the *next*
#: encounter with `hands_used` already 2 rather than the conversion's zero,
#: which is precisely the state `#69 (No WRITE_UNSOURCED zero has been tested
#: during combat)` exists to observe.
#:
#: `claim_treasure` is deliberately absent: its digest is a bare `YES NO`, and
#: the world map asks one of those too -- the boat back to Phlan, the inn --
#: so it is answered `n` and walked past.
FIGHT_BARS = frozenset({"encounter", "message", "command",
                        "continue_battle", "treasure"})


#: `BASH PICK EXIT`, the bar a locked door raises when the party steps into
#: it; `PoolOfRadiance.COMBAT_BARS` has no label for it.  Digest of the bar
#: row, as `screen.glyphs(dosbox.BAR)` gives it.  `e` is EXIT, which leaves
#: the party where it was.
LOCKED_BAR = "a0cec1d006a329cb"
LOCKED_EXIT_KEY = "e"


class Evidence:
    """Screenshots a run keeps in its `--out` folder, and their names.

    The pool's own shot directory goes when the slot is released, so a screen
    nobody looked at during the run is lost.  `files` is what the report
    names.  The DOS tooling compares pixels by digest and has no way to read
    a screen's text, so a shot is the only record of what a bar said.
    """

    def __init__(self, out: pathlib.Path):
        self.out = out
        self.files: list[str] = []
        self.errors: list[str] = []

    def take(self, s, name: str) -> str | None:
        """Keep one shot; a failed one is recorded and never stops the run."""
        try:
            path = s.shot(name, allow_blank=True)
            if path is None:
                return None
            self.out.mkdir(parents=True, exist_ok=True)
            shutil.copy(path, self.out / f"{name}.png")
        except (OSError, subprocess.SubprocessError) as e:
            self.errors.append(f"{name}: {e}")
            return None
        if f"{name}.png" not in self.files:
            self.files.append(f"{name}.png")
        return f"{name}.png"


def _shot(s, name: str, evidence: Evidence | None) -> None:
    """The pool's own shot, and a copy in `--out` when the run keeps evidence."""
    if evidence is None:
        s.shot(name, allow_blank=True)
    else:
        evidence.take(s, name)


def unsourced_fields() -> list[tuple[str, int, int]]:
    """`(name, offset, size)` for every field `goldbox.dos_codec.write` zeroes.

    Read out of the layout rather than written down here, so a field added to
    or removed from `WRITE_UNSOURCED` changes what this watches without
    anybody remembering to edit a second list.
    """
    return [(n, dl.FIELDS_BY_NAME[n].offset, dl.FIELDS_BY_NAME[n].size)
            for n, _ in dos_codec.WRITE_UNSOURCED]


def find_c64_save(name: str | None) -> pathlib.Path:
    """A C64 save disk: what `--c64` named, or the newest `PORSAVE*.D64`."""
    if name:
        return pathlib.Path(name).expanduser()
    from automap.paths import tool_disks
    disks = tool_disks()
    found = sorted(disks.glob("PORSAVE*.D64")) if disks is not None else []
    if not found:
        raise SystemExit("No C64 save disk found; name one with --c64")
    return found[-1]


def records(save_dir: pathlib.Path, letter: str) -> dict[int, bytes]:
    """Every `CHRDAT<letter><n>.SAV` in the staged save directory."""
    out = {}
    for n in range(1, 7):
        p = save_dir / f"CHRDAT{letter.upper()}{n}.SAV"
        if p.is_file():
            out[n] = p.read_bytes()
    return out


#: How many of `dosboxx.locate`'s windows must agree before an address is
#: believed enough to arm a watchpoint on it.
#:
#: `locate` votes with 12-byte windows two bytes apart over a 285-byte record,
#: so about 136 windows are cast and one coincidental match anywhere in a
#: megabyte scores 1.  Every record found in this issue's five runs -- 30 of
#: them -- scored between **31 and 45**, so eight is a wide margin below the
#: worst real one and far above a fluke.
#:
#: The guard matters because of what happens without it: `arm()` would put a
#: `BPM` on a stranger's address, the fight would report hits on a byte that
#: was never a character record, and nothing in the report would say so. The
#: docstring here promised this check before it existed.
MIN_VOTES = 8


def locate_records(image: bytes, recs: dict[int, bytes]) -> dict[int, dict]:
    """Where each character's live record sits in a memory image.

    One `locate` per record.  A record found by fewer than `MIN_VOTES` windows
    is marked `trusted: False` and its `base` is **not** returned, so a caller
    cannot arm a watchpoint on it by checking `base is not None` -- which is
    the only check both callers here ever made.  The vote count and the
    address are still reported, under `weak_base`, because a rejected match is
    worth reading.
    """
    found: dict[int, dict] = {}
    for n, data in recs.items():
        hit = dosboxx.locate(image, data)
        if hit is None:
            found[n] = {"base": None, "votes": 0, "matching": 0,
                        "trusted": False}
            continue
        base, votes, same = hit
        seg, ofs = dosboxx.seg_off(base)
        row = {"base": base, "votes": votes, "matching": same,
               "of": len(data), "at": f"{seg:04X}:{ofs:04X}",
               "trusted": votes >= MIN_VOTES}
        if not row["trusted"]:
            row["weak_base"] = base
            row["base"] = None
        found[n] = row
    return found


def field_values(image: bytes, base: int) -> dict[str, str]:
    """The watched fields, read out of a memory image at a record's base."""
    return {name: image[base + off:base + off + size].hex()
            for name, off, size in unsourced_fields()}


class Watcher:
    """Watchpoints on one or more record bytes, and the hits they produced.

    Kept as a class because the fight loop and the arming step both need the
    address-to-name map, and a hit read out of the log carries nothing but an
    address.
    """

    def __init__(self, s: dosboxx.XSession):
        self.s = s
        self.names: dict[int, str] = {}
        self.hits: list[dict] = []
        self.cursor = 0

    def arm(self, addr: int, label: str) -> None:
        seg, ofs = dosboxx.seg_off(addr)
        self.s.dbg(f"BPM {seg:X}:{ofs:X}", expect=r"Set memory breakpoint",
                   timeout=8.0)
        self.names[addr] = label

    def drain(self) -> list[dosboxx.Break]:
        """Every memory-breakpoint line the log has grown since last asked."""
        text = self.s.log_text()
        fresh = dosboxx.parse_breaks(text[self.cursor:])
        self.cursor = len(text)
        return fresh

    def note(self, hit: dosboxx.Break, **extra) -> dict:
        row = {"field": self.names.get(hit.addr, "?"),
               "at": f"{hit.seg:04X}:{hit.ofs:04X}",
               "addr": hit.addr,
               "old": hit.old, "new": hit.new}
        row.update(extra)
        self.hits.append(row)
        return row


def absorb_spurious(w: Watcher, expected: int, timeout: float = 40.0) -> list:
    """Let every watchpoint on a nonzero byte fire its one false hit.

    **A fresh `BPM` remembers the value 00**, so a watchpoint armed on a byte
    that is not zero fires the instant the emulator runs, reporting
    `00 -> <what was already there>`.  Arming them all and then running is
    cheaper than absorbing one at a time, and the count is predictable: it is
    exactly the number of watched bytes that read nonzero when armed.
    """
    got: list[dosboxx.Break] = []
    deadline = time.time() + timeout
    while len(got) < expected and time.time() < deadline:
        w.s.run()
        time.sleep(0.4)
        got += w.drain()
    w.drain()
    return got


def _grab(por: dosbox.PoolOfRadiance, tries: int | None = None):
    """`(screen, bar kind)` of a fresh capture, or `(None, None)` for a frame
    the grab could not read.

    The debugger halts the emulator on a watchpoint between two blits, and a
    frame captured then is torn; `dosboxx.halve` refuses it, and it stays
    torn until the emulator runs again.  That is a frame to skip, not the end
    of the run, so the caller keeps polling.  `tries` replaces the session's
    `CAPTURE_TRIES` for this one grab: a grab retried while the emulator is
    still halted sees the same torn frame every time, so the caller that is
    halted asks for one.
    """
    had = por.s.__dict__.get("CAPTURE_TRIES")
    if tries is not None:
        por.s.CAPTURE_TRIES = tries
    try:
        screen = por.s.capture()
    except dosboxx.NotLineDoubled as e:
        print(f"unreadable frame ({e}); polling on")
        return None, None
    finally:
        if tries is not None:
            if had is None:
                del por.s.CAPTURE_TRIES
            else:
                por.s.CAPTURE_TRIES = had
    return screen, por.bar_kind(screen)


def fight_watching(por: dosbox.PoolOfRadiance, w: Watcher, *,
                   budget: float = 900.0, settled: float = 4.0,
                   dwell: float = 1.2, patience: float = 90.0,
                   max_hits: int = 4000, on_hit=None,
                   evidence: Evidence | None = None) -> dict:
    """`PoolOfRadiance.fight`, with the emulator's halts handled.

    A watchpoint firing stops the emulator, so the screen freezes and the
    driver's own waits would run to their timeouts against a picture that
    cannot change.  The log says it happened immediately -- `DEBUG_ShowMsg`
    writes unbuffered -- so every turn of this loop reads the log first and
    resumes before it looks at the screen at all.

    The bar recorded against a hit is the frame that was on screen when the
    emulator stopped, which is what makes a hit's *phase* readable: a write
    that lands while `COMBAT WAIT FLEE ADVANCE` is up happened before any
    character acted.

    `on_hit(row)` is called for every hit while the emulator is still halted,
    so a caller can read memory at the moment of the write.
    """
    s = por.s
    if por.world_glyphs is None:
        raise RuntimeError("fight_watching needs the world bar load_game recorded")
    started = time.time()
    deadline = started + budget
    world_since: float | None = None
    unknown_since: float | None = None
    resumes = 0
    last_bar = "?"
    unreadable_since: float | None = None
    while time.time() < deadline:
        fresh = w.drain()
        if fresh:
            # The emulator is halted, so a torn frame here stays torn: one
            # try, and the last bar read stands in for the one not seen.
            screen, kind = _grab(por, tries=1)
            if screen is not None:
                last_bar = kind or "?"
            bar = last_bar
            rows = [w.note(hit, bar=bar, t=round(time.time() - started, 2),
                           cs_ip=None) for hit in fresh]
            if on_hit is not None or len(w.hits) <= 40:
                # `EV` is the only way a register reaches the log, and it
                # costs a round trip -- so the writing address is recorded for
                # the first hits, which are the ones that say what the engine
                # did with our zero, and not for a thousandth repeat.  A
                # caller with `on_hit` needs every one.  One halt has one
                # `CS:IP`, and a word write can trip two watched bytes in it.
                try:
                    regs = s.regs("CS", "IP")
                    at = f"{regs.get('CS', 0):04X}:{regs.get('IP', 0):04X}"
                    for row in rows:
                        row["cs_ip"] = at
                except Exception:
                    pass
            if on_hit is not None:
                for row in rows:
                    on_hit(row)
            resumes += 1
            s.run()
            if len(w.hits) >= max_hits:
                return {"result": False, "why": "hit budget", "resumes": resumes,
                        "seconds": round(time.time() - started, 1)}
            continue

        try:
            screen = s.capture()
        except dosboxx.NotLineDoubled as e:
            print(f"unreadable frame ({e}); polling on")
            unreadable_since = unreadable_since or time.time()
            if time.time() - unreadable_since >= patience:
                _shot(s, "watch_unreadable_screen", evidence)
                return {"result": False, "why": "unreadable screen",
                        "resumes": resumes,
                        "seconds": round(time.time() - started, 1)}
            time.sleep(0.25)
            continue
        unreadable_since = None
        bar = screen.glyphs(dosbox.BAR)
        if bar == por.world_glyphs:
            world_since = world_since or time.time()
            if time.time() - world_since >= settled:
                return {"result": True, "resumes": resumes, "last_bar": last_bar,
                        "seconds": round(time.time() - started, 1)}
            time.sleep(0.25)
            continue
        world_since = None
        kind = por.bar_kind(screen)
        key = por.COMBAT_KEYS.get(kind or "")
        if key is None:
            if unknown_since is None and evidence is not None and kind is None:
                # Taken on first sight: the screen may change before
                # `patience` runs out, and the first frame is the one that
                # names what the fight asked.  It is a fresh grab, not the
                # frame the bar was read from, and a bar in the table
                # (`blank`, `message`, `move_attack`) is skipped as
                # `_await_bar` skips it.
                evidence.take(s, f"unknown_bar_{bar}")
            unknown_since = unknown_since or time.time()
            if time.time() - unknown_since >= patience:
                _shot(s, f"watch_unknown_bar_{bar}", evidence)
                return {"result": False, "why": f"unknown bar {bar}",
                        "resumes": resumes,
                        "seconds": round(time.time() - started, 1)}
            time.sleep(0.25)
            continue
        unknown_since = None
        s.key(key)
        s.wait_while_glyphs(dosbox.BAR, bar, timeout=dwell)
    _shot(s, "watch_stuck", evidence)
    return {"result": False, "why": "budget", "resumes": resumes,
            "seconds": round(time.time() - started, 1)}


def _await_bar(por: dosbox.PoolOfRadiance, patience: float,
               evidence: Evidence | None = None) -> tuple[str | None, bool]:
    """Wait out a bar with no key, the way `PoolOfRadiance.fight()` does.

    `blank` -- the bar row caught mid-redraw -- is carried in
    `PoolOfRadiance.COMBAT_BARS` on purpose so a flat strip is never mistaken
    for a command bar, and it is given no key on purpose because there is
    nothing on it to press.  One appearance of it is a frame; a `blank` that
    lasts is a stuck game, and the two are only told apart by waiting.  So
    this keeps looking rather than judging the first frame: `(kind, True)`
    once the bar resolves into one the walk can act on, `(kind, False)`, with
    a screenshot named for the digest already taken, once `patience` seconds
    pass with it still unresolved.
    A frame still unreadable when `patience` runs out gives `("unreadable", False)`.
    """
    deadline = time.time() + patience
    first_sight = True
    while True:
        screen, kind = _grab(por)
        if screen is not None:
            if screen.glyphs(dosbox.BAR) == LOCKED_BAR:
                return "locked", True
            if kind in FIGHT_BARS or por.COMBAT_KEYS.get(kind or "") is not None:
                return kind, True
            if kind is None and first_sight and evidence is not None:
                # `blank` is a frame caught mid-redraw and is not kept; a bar
                # in no table is.
                evidence.take(por.s, f"unknown_bar_{screen.glyphs(dosbox.BAR)}")
            first_sight = False
        if time.time() >= deadline:
            if screen is None:
                _shot(por.s, "walk_unreadable_screen", evidence)
                return "unreadable", False
            # The shot is named for **this** capture's bar, the one the walk
            # actually gave up on.  Capturing again here to name it would let
            # the emulator redraw in between and save a picture of some other
            # frame -- which is the hazard this whole function exists for.
            _shot(por.s, f"walk_unknown_bar_{screen.glyphs(dosbox.BAR)}",
                  evidence)
            return kind, False
        time.sleep(0.25)


def walk_to_encounter(por: dosbox.PoolOfRadiance, steps: int, *,
                      patience: float = 90.0,
                      evidence: Evidence | None = None) -> dict:
    """Walk until the encounter menu comes up, dismissing whatever else does.

    A blocked step returns to the same bar with the same status line; the
    party turns rather than counting it, so the walk goes somewhere it can
    meet something.

    **Not every step that fails to come back on the world bar is a fight.**
    A `YES NO` prompt -- the boat back to Phlan is the one the Slums offers --
    stops the world bar exactly as an encounter does, and answering it `n` and
    walking on is what this wants.  The first run of this tool armed its
    watchpoints at one of those, pressed `n`, watched the world bar come back
    in 4.7 seconds and reported a fight that never happened.

    **A bar with no key is given `patience` seconds before it is called
    stuck** -- see `_await_bar`.  Without it, one captured frame landing on
    `blank` mid-redraw threw away a whole run one frame before the encounter
    it was walking towards.

    The default is `fight_watching()`'s 90 rather than `fight()`'s 60, and
    deliberately: giving up here throws away the booting, converting and
    walking that got the party this far, where giving up in a fight throws
    away the fight.  #217's body says `fight()` grants 90 and it grants 60;
    the number here was never the one that ticket meant to copy.
    """
    walked = blocked = prompts = 0
    i = -1
    tries = 0
    while walked + blocked < steps and tries < steps * 4:
        i += 1
        tries += 1
        before = por.status()
        if por.step():
            if por.status() == before:
                blocked += 1
                por.turn_right()
                continue
            walked += 1
            continue
        # No guard here: `_await_bar` returns at once on a bar the walk can
        # already act on, and one copy of that test is easier to keep true
        # than two.
        kind, resolved = _await_bar(por, patience, evidence)
        if not resolved:
            return {"met": False,
                    "why": ("unreadable screen" if kind == "unreadable"
                            else f"a bar nobody has labelled ({kind})"),
                    "at_step": i + 1, "walked": walked,
                    "blocked": blocked, "prompts": prompts}
        if kind in FIGHT_BARS:
            return {"met": True, "at_step": i + 1, "bar": kind, "walked": walked,
                    "blocked": blocked, "prompts": prompts}
        if kind == "locked":
            # A locked door is a wall that asks a question: EXIT leaves the
            # party unchanged, and the square is blocked like a bump.
            por.s.key(LOCKED_EXIT_KEY)
            if not por.s.wait_until_ink(dosbox.BAR, por.world_bar or "",
                                        timeout=20.0):
                return {"met": False, "why": "locked door did not clear",
                        "at_step": i + 1, "walked": walked,
                        "blocked": blocked, "prompts": prompts}
            blocked += 1
            por.turn_right()
            continue
        # Something answerable that is not the encounter menu: answer it and
        # keep walking.  `n` is the decline on every `YES NO` the map offers.
        # **Turn afterwards.**  Declining the inn's "IT WILL COST YOU 1
        # PLATINUM PIECE TO REST HERE" leaves the party facing the same door,
        # so the next step walks into it again -- 67 prompts and 10 squares
        # walked, in the run that found this out.
        prompts += 1
        por.s.key(por.COMBAT_KEYS[kind])
        por.s.wait_until_ink(dosbox.BAR, por.world_bar or "", timeout=20.0)
        por.turn_right()
    return {"met": False, "why": "no encounter in the steps asked",
            "walked": walked, "blocked": blocked, "prompts": prompts}


def run(*, c64: pathlib.Path | None, slot: str, steps: int, out: pathlib.Path,
        stop_after_locate: bool, watch_chars: tuple[int, ...],
        only: tuple[str, ...] = (), resave: str = "E") -> dict:
    """The whole measurement.  Everything it learned comes back in the dict."""
    out.mkdir(parents=True, exist_ok=True)

    def checkpoint() -> None:
        """Write what is known so far.  A run that dies late still reports."""
        (out / "report.json").write_text(json.dumps(report, indent=1,
                                                   default=str))

    game = dosbox.find_game()
    report: dict = {"slot": slot, "steps_asked": steps,
                    "fields": [n for n, _, _ in unsourced_fields()]}

    disk = find_c64_save(c64 if c64 is None else str(c64))
    report["c64"] = str(disk)
    save0 = load_payload(str(disk), POOL_OF_RADIANCE.save_file)
    try:
        save1 = load_payload(str(disk), POOL_OF_RADIANCE.roster_file)
    except Exception:
        save1 = None

    with dosboxx.claim("issue69 fight watch") as claimed:
        s = dosboxx.XSession(claimed, game)
        try:
            s.stage(fresh=True)
            written = dos_codec.new_dos_save(save0, save1, s.save_dir, slot,
                                       s.game_dir)
            report["accounted"] = f"{len(written.sources)}/{written.total}"
            report["warnings"] = written.warnings
            built = records(s.save_dir, slot)
            report["built_records"] = {
                n: {"len": len(d),
                    "unsourced": field_values(d, 0)} for n, d in built.items()}
            for n, d in built.items():
                (out / f"BUILT-CHRDAT{slot.upper()}{n}.SAV").write_bytes(d)

            s.boot(fresh=False)
            por = dosbox.PoolOfRadiance(s)
            por.to_main_menu()
            por.load_game(slot)
            shutil.copy(s.shot("loaded"), out / "loaded.png")
            report["status_at_load"] = por.status()
            checkpoint()

            report["walk"] = walk_to_encounter(por, steps)
            checkpoint()
            if not report["walk"]["met"]:
                return report
            shutil.copy(s.shot("encounter", allow_blank=True),
                        out / "encounter.png")

            report["attached"] = s.attach()
            if not report["attached"]:
                return report
            image = s.read(0, 0x100000)
            (out / "memory-at-encounter.bin").write_bytes(image)
            report["dumped"] = len(image)
            where = locate_records(image, built)
            report["records"] = {n: dict(v) for n, v in where.items()}
            # Named in the report rather than left to a reader counting rows:
            # a record `MIN_VOTES` rejected is a character this run will not
            # watch, and a run that silently watches five of six looks exactly
            # like one that watched all six.
            report["untrusted_records"] = [n for n, v in where.items()
                                           if not v["trusted"]]
            report["live_at_encounter"] = {
                n: field_values(image, v["base"])
                for n, v in where.items() if v["base"] is not None}
            checkpoint()
            if stop_after_locate:
                return report

            # -- arm ------------------------------------------------------
            w = Watcher(s)
            nonzero = 0
            for n in watch_chars:
                base = where.get(n, {}).get("base")
                if base is None:
                    continue
                for name, off, _size in unsourced_fields():
                    if only and name not in only:
                        continue
                    addr = base + off
                    w.arm(addr, f"c{n}.{name}")
                    if image[addr] != 0:
                        nonzero += 1
            report["watchpoints"] = len(w.names)
            report["expected_spurious"] = nonzero
            w.drain()
            got = absorb_spurious(w, nonzero)
            report["absorbed"] = [
                {"field": w.names.get(h.addr, "?"), "old": h.old, "new": h.new}
                for h in got]
            report["breakpoint_list"] = s.breakpoints()
            checkpoint()

            # -- fight ----------------------------------------------------
            s.run()
            report["fight"] = fight_watching(por, w)
            report["hits"] = w.hits
            report["hit_counts"] = _counts(w.hits)
            checkpoint()

            # The emulator may be halted at a last hit; let it run so the
            # game can be saved through its own menus.
            for _ in range(6):
                if not s.halted(timeout=2.0):
                    break
                w.drain()
                s.run()

            # What the fields hold at the end of the fight, read out of memory
            # rather than out of a file.  This is what separates "the engine
            # wrote it during the fight" from "the engine wrote it while
            # saving": a byte that is still our zero here and is not zero in
            # the resave was written by `ENCAMP > SAVE` and by nothing else.
            if s.attach():
                after_image = s.read(0, 0x100000)
                (out / "memory-after-fight.bin").write_bytes(after_image)
                where2 = locate_records(after_image, built)
                report["records_after_fight"] = {n: dict(v)
                                                 for n, v in where2.items()}
                report["live_after_fight"] = {
                    n: field_values(after_image, v["base"])
                    for n, v in where2.items() if v["base"] is not None}
                checkpoint()
                s.clear_breakpoints()
                s.run()
            else:
                report["live_after_fight"] = None

            try:
                engine = por.save_game(resave)
                (out / f"RESAVE-SAVGAM{resave.upper()}.DAT").write_bytes(engine)
                report["resaved"] = True
            except Exception as e:
                # The fight's hits are the finding; the resave is the check on
                # top of it.  Losing the whole run because ENCAMP did not open
                # is how the first attempt reported nothing at all.
                report["resaved"] = False
                report["resave_error"] = f"{type(e).__name__}: {e}"
                checkpoint()
            # **The records to read back are the ones `save_game` just wrote,
            # and they are not in `slot`.**  This read `records(s.save_dir,
            # slot)` -- the converted slot, which the game never writes -- so
            # it compared the conversion against itself: `experience_rose` was
            # `0` for every character of every run and `fought` was always
            # False.  The first fight this tool actually drove reported
            # `fought: false` while the engine's own slot E held 16 more
            # experience points for all six.
            after = records(s.save_dir, resave)
            report["after_records"] = {
                n: {"experience": int.from_bytes(d[XP:XP + 4], "little"),
                    "hp_current": d[HP_CURRENT],
                    "unsourced": field_values(d, 0)}
                for n, d in after.items()}
            report["experience_rose"] = {
                n: int.from_bytes(after[n][XP:XP + 4], "little")
                - int.from_bytes(built[n][XP:XP + 4], "little")
                for n in after if n in built}
            report["fought"] = any(v > 0 for v in
                                   report["experience_rose"].values())
            for n, d in after.items():
                (out / f"AFTER-CHRDAT{resave.upper()}{n}.SAV").write_bytes(d)
        finally:
            checkpoint()
            s.close()
    return report


def truth(*, c64: pathlib.Path | None, slot: str, engine_slot: str, steps: int,
          out: pathlib.Path) -> dict:
    """What the engine's *own* party holds at an encounter menu (#69).

    The comparison `#69 (No WRITE_UNSOURCED zero has been tested during
    combat)` asks for and that no run has made: not the engine's resave after
    a fight, but the engine's live records **at the same point in the same
    place** as a converted party's.

    The trick is that the party is the same one either way.  A converted save
    is written to `slot`, loaded, and immediately saved back to `engine_slot`
    through `ENCAMP > SAVE`, which makes the engine author all seven files for
    a party it did not convert.  The emulator is restarted so the load is a
    real load rather than a party still in memory, `engine_slot` is loaded,
    and the walk to an encounter and the megabyte dump are the ones `locate`
    takes.  Every field that then differs from the converted run's is a field
    where our zero is not what the engine would have had when the fight began.

    **Run once, `cited/69/truth13`.**  It reached a wandering encounter at
    step 44 and found all six records at 285 of 285 bytes -- a cleaner match
    than the `watch` runs get, because the needle is the engine's own save of
    the state it is being matched against rather than the file we wrote before
    the game touched it.

    **And the one thing it cannot answer, which that run is what showed.**  For
    a field the engine only ever *carries*, an `ENCAMP > SAVE` hands back
    whatever it was given: `hands_used`, the four portrait and icon bytes and
    `unnamed_0ab` -- which this no longer watches, because #216 measured what
    its zero costs and `goldbox.dos_codec.write` now derives it -- all came back
    `00` in `engine_slot`, because they were `00` in the conversion it
    loaded.  So this says what the engine holds when a
    fight begins, and says nothing about what it would have chosen for a
    character it created itself.  For that, read the records the game ships.
    """
    out.mkdir(parents=True, exist_ok=True)
    game = dosbox.find_game()
    report: dict = {"mode": "truth", "slot": slot, "engine_slot": engine_slot,
                    "steps_asked": steps,
                    "fields": [n for n, _, _ in unsourced_fields()]}

    def checkpoint() -> None:
        (out / "report.json").write_text(json.dumps(report, indent=1,
                                                   default=str))

    disk = find_c64_save(c64 if c64 is None else str(c64))
    report["c64"] = str(disk)
    save0 = load_payload(str(disk), POOL_OF_RADIANCE.save_file)
    try:
        save1 = load_payload(str(disk), POOL_OF_RADIANCE.roster_file)
    except Exception:
        save1 = None

    with dosboxx.claim("issue69 engine truth") as claimed:
        s = dosboxx.XSession(claimed, game)
        try:
            s.stage(fresh=True)
            written = dos_codec.new_dos_save(save0, save1, s.save_dir, slot,
                                       s.game_dir)
            report["accounted"] = f"{len(written.sources)}/{written.total}"
            built = records(s.save_dir, slot)
            report["built_records"] = {
                n: {"unsourced": field_values(d, 0)} for n, d in built.items()}

            s.boot(fresh=False)
            por = dosbox.PoolOfRadiance(s)
            por.to_main_menu()
            por.load_game(slot)
            report["status_at_load"] = por.status()
            checkpoint()

            # The engine authors the party.  Nothing has been fought and
            # nothing walked: this is the same party, one `ENCAMP > SAVE`
            # later, with every `WRITE_UNSOURCED` byte the engine's own.
            por.save_game(engine_slot)
            engine = records(s.save_dir, engine_slot)
            report["engine_records"] = {
                n: {"unsourced": field_values(d, 0)} for n, d in engine.items()}
            for n, d in engine.items():
                (out / f"ENGINE-CHRDAT{engine_slot.upper()}{n}.SAV").write_bytes(d)
            checkpoint()

            # A restart, so the party is loaded off disk rather than still in
            # the heap the conversion was read into.
            s.restart()
            por = dosbox.PoolOfRadiance(s)
            por.to_main_menu()
            por.load_game(engine_slot)
            shutil.copy(s.shot("engine-loaded"), out / "engine-loaded.png")
            checkpoint()

            report["walk"] = walk_to_encounter(por, steps)
            checkpoint()
            if not report["walk"]["met"]:
                return report
            shutil.copy(s.shot("engine-encounter", allow_blank=True),
                        out / "engine-encounter.png")

            report["attached"] = s.attach()
            if not report["attached"]:
                return report
            image = s.read(0, 0x100000)
            (out / "engine-memory-at-encounter.bin").write_bytes(image)
            where = locate_records(image, engine)
            report["records"] = {n: dict(v) for n, v in where.items()}
            report["untrusted_records"] = [n for n, v in where.items()
                                           if not v["trusted"]]
            report["live_at_encounter"] = {
                n: field_values(image, v["base"])
                for n, v in where.items() if v["base"] is not None}
            checkpoint()
            s.clear_breakpoints()
            s.run()
        finally:
            checkpoint()
            s.close()
    return report


# -- the treasure split (#743) ------------------------------------------------

#: `DS` offset of the seven longint coin piles the fight fills and the split
#: reduces, and the gold pile's place in it (copper, silver, electrum, gold, ...).
#: Only the first four are named; the last three are not identified.
PILE_BASE = 0x67F4
GOLD_PILE = PILE_BASE + 4 * 3
PILE_NAMES = ("copper", "silver", "electrum", "gold", "pile4", "pile5", "pile6")

#: `GAME.OVR` offsets of the instructions the measurement is keyed on: the
#: store that fills a pile, the store that reduces it in the split, and the
#: point in the split where `C` and `A` are final.
FILL_OFFSET = 0x005634
SPLIT_OFFSET = 0x006943
COUNT_OFFSET = 0x0068D8

#: A watchpoint reports `CS:IP` of the instruction *after* the write, so the
#: bytes before it are read back and matched to the overlay file to learn how
#: long that instruction was.
CODE_WINDOW = 8
MIN_INSTRUCTION = 2


def find_ovr(game: pathlib.Path) -> bytes:
    """`GAME.OVR` of a DOS game directory, whatever its case."""
    for p in game.iterdir():
        if p.name.upper() == "GAME.OVR":
            return p.read_bytes()
    raise FileNotFoundError(f"no GAME.OVR in {game}")


#: Offset of the treasure share in a DOS `CHRDAT` record.
SHARE_OFFSET = 0x085

#: `(A, C)` the split divides and multiplies by, for the hireling's treasure
#: share: `$03` and `$FB` take 3 parts of 9 (the C64 rule), `$FF` takes 7 of 13.
#: A share not listed has no rule here, so no verdict is given for it.
SHARE_RULES = {0x03: (9, 3), 0xFB: (9, 3), 0xFF: (13, 7)}


def hireling_share(save_dir: pathlib.Path, letter: str) -> int | None:
    """The share of the one record holding a value `SHARE_RULES` has a rule
    for, or None when no record or several do.

    Player characters carry other values here (`0x01` on most engine-written
    saves), so only ruled values are counted, one per record.  `records` stops
    at six and the hireling is the seventh file, so the directory is scanned.
    """
    ruled = []
    for p in save_dir.iterdir():
        name = p.name.upper()
        if name.startswith(f"CHRDAT{letter.upper()}") and name.endswith(".SAV"):
            data = p.read_bytes()
            if len(data) > SHARE_OFFSET and data[SHARE_OFFSET] in SHARE_RULES:
                ruled.append(data[SHARE_OFFSET])
    return ruled[0] if len(ruled) == 1 else None


def expected_cut(pile: int, c: int, a: int) -> int:
    """What the split takes from a pile: `cwd(((pile div A) & 0xFF) * C)`."""
    cut = ((pile // a) & 0xFF) * c
    cut &= 0xFFFF
    return cut - 0x10000 if cut & 0x8000 else cut


def instruction_end(code: bytes, ovr: bytes, offset: int) -> int | None:
    """How many bytes of `ovr[offset:]` end exactly at the end of `code`.

    `code` is what precedes the reported `IP`.  The smallest length of at
    least `MIN_INSTRUCTION` that matches is taken; None when none does, which
    is how a hit from some other routine is told apart.
    """
    for k in range(MIN_INSTRUCTION, min(len(code), CODE_WINDOW) + 1):
        if code[-k:] == ovr[offset:offset + k]:
            return k
    return None


def classify_hit(hit: dict, ovr: bytes) -> dict:
    """The hit with `phase` (`fill`, `split` or None) and the overlay's linear
    base (`bias`, so that `bias + file offset` is the runtime address)."""
    out = dict(hit)
    out["phase"] = None
    out["bias"] = None
    if not hit.get("cs_ip") or not hit.get("code"):
        return out
    seg, ofs = (int(x, 16) for x in hit["cs_ip"].split(":"))
    code = bytes.fromhex(hit["code"])
    for phase, offset in (("split", SPLIT_OFFSET), ("fill", FILL_OFFSET)):
        k = instruction_end(code, ovr, offset)
        if k is not None:
            out["phase"] = phase
            out["bias"] = dosboxx.linear((seg, ofs)) - k - offset
            return out
    return out


def pile_change(initial: bytes, hits: list[dict], base: int) -> dict | None:
    """The gold pile before and after the first split, from the hits.

    `hits` are classified and in order; each names one byte of the pile
    (`addr` is linear, `base` the pile's first byte).  The pile is rebuilt
    from `initial` by applying every hit, so what it held just before the
    first `split` hit and just after the last of that unbroken run is exact.
    Only the low word's store is classified: the high-word `sbb`/`adc` is
    not, so a pile of 65,536 or more is not measured.
    """
    state = bytearray(initial)
    before = after = None
    in_split = False
    for h in hits:
        i = h["addr"] - base
        if 0 <= i < len(state):
            if h["phase"] == "split" and not in_split and before is None:
                before = int.from_bytes(state, "little")
                in_split = True
            elif h["phase"] != "split":
                in_split = False
            state[i] = h["new"]
            if in_split:
                after = int.from_bytes(state, "little")
    if before is None:
        return None
    return {"before": before, "after": after}


def derive_bias(hits: list[dict]) -> dict:
    """The overlay's runtime linear base, from the split hits.

    The split's own hits give it; the fill hits are compared, because an
    overlay swapped in twice puts the two at different bases.
    """
    split = sorted({h["bias"] for h in hits if h["phase"] == "split"})
    fill = sorted({h["bias"] for h in hits if h["phase"] == "fill"})
    out = {"split_biases": split, "fill_biases": fill, "bias": None,
           "fill_agrees": None}
    if len(split) == 1:
        out["bias"] = split[0]
        out["fill_agrees"] = bool(fill) and fill == split
    return out


def summarize(initial: bytes, hits: list[dict], ovr: bytes, base: int,
              counts: dict | None, share: int | None = None) -> dict:
    """The JSON report of a split measurement, from its raw hits and counts.

    `initial` is the 28 bytes of the seven piles at `base`.  `piles` has one
    entry per pile whose split was seen, with its `before`, `after`, `taken`
    and, once `share` names a rule in `SHARE_RULES`, `expected_cut`,
    `expected_after` and `matches`.  `counts` is the count read at
    `COUNT_OFFSET`, reported as data and not used: it has read values the code
    cannot produce.  `pile`, `expected_cut`, `taken` and `expected_after` are the
    gold pile's own, and `matches` is true only if at least one pile was measured, none that
    held coins at the encounter is missing (`unmeasured_piles`) and every
    measured pile's split equals the rule's.  `gold_split_seen` says whether
    the gold keys above are the gold pile's own.
    """
    classified = [classify_hit(h, ovr) for h in hits]
    bias = derive_bias(classified)
    piles: dict[str, dict] = {}
    rule = SHARE_RULES.get(share)
    for i, name in enumerate(PILE_NAMES):
        start = base + 4 * i
        own = [h for h in classified if 0 <= h["addr"] - start < 4]
        change = pile_change(initial[4 * i:4 * i + 4], own, start)
        if change is None:
            continue
        row = {**change, "taken": change["before"] - (change["after"] or 0)}
        if rule:
            cut = expected_cut(change["before"], rule[1], rule[0])
            row["expected_cut"] = cut
            row["expected_after"] = change["before"] - cut
            row["matches"] = cut == row["taken"]
        piles[name] = row
    gold = piles.get("gold")
    out: dict = {"hits": classified, **bias, "pile": (
        {"before": gold["before"], "after": gold["after"]} if gold else None),
        "piles": piles, "counts": counts, "share": share,
        "rule": {"a": rule[0], "c": rule[1]} if rule else None}
    if bias["bias"] is not None:
        seg, ofs = dosboxx.seg_off(bias["bias"] + COUNT_OFFSET)
        out["count_break"] = f"{seg:04X}:{ofs:04X}"
    if gold and "expected_cut" in gold:
        for key in ("expected_cut", "taken", "expected_after"):
            out[key] = gold[key]
    out["gold_split_seen"] = gold is not None
    out["unmeasured_piles"] = [
        name for i, name in enumerate(PILE_NAMES)
        if name not in piles and any(initial[4 * i:4 * i + 4])]
    if rule:
        out["matches"] = (bool(piles) and not out["unmeasured_piles"]
                          and all(p["matches"] for p in piles.values()))
        if not piles:
            out["why"] = "no pile's split was measured"
        elif out["unmeasured_piles"]:
            out["why"] = ("a pile held coins at the encounter but its split "
                          "was not seen: " + ", ".join(out["unmeasured_piles"]))
    return out


def require_pool(data: bytes, what: str) -> None:
    """`ValueError` unless `data` is a Pool of Radiance saved game."""
    try:
        pool = (dos_savegame.container_for(len(data))
                is dos_savegame.SAVE_POOL_OF_RADIANCE)
    except dos_savegame.DosSaveError:
        pool = False
    if not pool:
        raise ValueError(f"The {what} is not a Pool of Radiance saved game")


def rewritten_offsets() -> set[int]:
    """Every `SAVGAM` byte `place_like` writes: the script buffer, the header
    byte, the words `retarget` and `place_like` set, and the square and tail."""
    container = dos_savegame.SAVE_POOL_OF_RADIANCE
    start, end = dos_savegame.ECL_BUFFER
    out = set(range(start, end)) | {container.head}
    for address in (dos_savegame.AREA, dos_savegame.SCRIPT, dos_savegame.DISK,
                    dos_savegame.INDOORS,
                    *range(dos_savegame.WALLSET, dos_savegame.WALLSET + 3),
                    *range(dos_savegame.WALLMAP, dos_savegame.WALLMAP + 3)):
        offset = dos_savegame.word_offset(address, container)
        out |= {offset, offset + 1}
    return out | set(range(12801, 12808))


def surviving_differences(placed: bytes, donor: bytes) -> dict:
    """How many bytes of `placed` still differ from `donor` outside what
    `place_like` rewrites, as `[first, last]` offset ranges, so a reader can
    see how much of the original save's state came along."""
    skip = rewritten_offsets()
    offsets = [i for i in range(min(len(placed), len(donor)))
               if i not in skip and placed[i] != donor[i]]
    ranges: list[list[int]] = []
    for i in offsets:
        if ranges and ranges[-1][1] == i - 1:
            ranges[-1][1] = i
        else:
            ranges.append([i, i])
    return {"count": len(offsets), "ranges": ranges}


def place_like(save: pathlib.Path, donor: bytes, script: bytes) -> dict:
    """Move the staged `SAVGAM?.DAT` at `save` to where `donor` stands.

    `donor` is a Pool of Radiance saved game the DOS engine wrote in an indoor
    area with encounters, and `script` that area's `ECL` DAX block.  Every
    area value comes from the donor, so nothing here is invented: the area,
    resident map, DAX number, wallset, square and the script buffer.  Only
    `SAVGAM?.DAT` is written; the character files are not touched.
    """
    require_pool(save.read_bytes(), "staged save")
    require_pool(donor, "donor")
    if dos_savegame.outdoors(donor):
        raise ValueError("The donor stands on the overland map; a wandering "
                         "encounter there needs a different area's script")
    out = bytearray(save.read_bytes())
    start, end = dos_savegame.ECL_BUFFER
    out[start:end] = bytes(end - start)
    area, dax = dos_savegame.current_area(donor), dos_savegame.dax_number(donor)
    geo, wallset = dos_savegame.geo_block(donor), dos_savegame.wall_triple(donor)
    dos_savegame.retarget(out, area=area, dax=dax, wallset=wallset,
                          script=script, geo=geo)
    x, y, facing = dos_savegame.position(donor)
    dos_savegame.put_word(out, dos_savegame.INDOORS, 1)
    dos_savegame.put_position(out, x, y, facing)
    dos_savegame.put_tail_state(out, indoors=True)
    save.write_bytes(bytes(out))
    return {"area": area, "geo": geo, "dax": dax, "position": [x, y, facing],
            "wallset": list(wallset),
            "differs_from_donor": surviving_differences(bytes(out), donor)}


def check_donor_script(donor: bytes, script: bytes) -> None:
    """Refuse a script that is not the one the donor's own buffer holds.

    The engine stages the area's `ECL` block into the save with the rest of
    the buffer zero, so a mismatch means the wrong DAX block was read.
    """
    start, end = dos_savegame.ECL_BUFFER
    body = script[dos_savegame.ECL_HEADER:]
    if donor[start:end] != body + bytes(end - start - len(body)):
        raise ValueError("The donor's script buffer is not the given area "
                         "script followed by zeros")


def check_records_unchanged(folder: pathlib.Path, save_dir: pathlib.Path,
                            letter: str) -> dict:
    """SHA-256 of each staged `CHRDAT<letter>*` against the folder's file of
    that name; the folder's other slots are not installed and not compared.

    Raises `ValueError` naming every file that differs or is missing, so a run
    that claims the game's own characters cannot start on altered ones.
    """
    def digests(directory: pathlib.Path) -> dict[str, str]:
        return {p.name.upper(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in directory.iterdir()
                if p.is_file()
                and p.name.upper().startswith(f"CHRDAT{letter.upper()}")}
    want, got = digests(folder), digests(save_dir)
    bad = sorted(n for n in want.keys() | got.keys() if want.get(n) != got.get(n))
    if bad:
        raise ValueError("Character files differ from the folder's: "
                         + ", ".join(bad))
    return {"records_unchanged": True, "record_hashes": got}


def check_at(at: str) -> None:
    """`ValueError` unless `at` is `X,Y,F` with `F` one of N, E, S, W."""
    parts = at.split(",")
    if (len(parts) != 3 or not parts[0].strip().isdigit()
            or not parts[1].strip().isdigit()
            or parts[2].strip().upper() not in ("N", "E", "S", "W")):
        raise ValueError(f"--at {at!r} must be X,Y,F with F one of the letters "
                         "N, E, S or W (a facing number is not accepted)")


def install_folder(save_dir: pathlib.Path, folder: pathlib.Path,
                   at: str | None = None, source: str | None = None,
                   place: tuple[bytes, bytes] | None = None) -> str:
    """Put a DOS-native save folder into a staged `SAVE` tree, unconverted.

    Returns the slot letter.  `place` is `(donor, script)` for `place_like`,
    applied before `at`, which pokes the party's square as
    `tools/dos/dostrain.py --at` does within the area it then stands in.
    Without `place` the area is not changed, so the folder has to stand where
    fights happen already.
    """
    if at:
        check_at(at)
    wipe_roster(save_dir)
    chosen = staging.source_slot(folder, source)
    took = staging.install(folder, save_dir, chosen, chosen)
    letter = took["as_slot"]
    if place is not None:
        place_like(save_dir / f"SAVGAM{letter}.DAT", *place)
    if at:
        move_to(save_dir / f"SAVGAM{letter}.DAT", at)
    return letter


def check_piles(s, ds: int) -> str | None:
    """None when the seven coin piles at `ds` look like a fight's start.

    A `DS` read from wherever Alt+Pause stopped is only the game's if the
    piles there are longints below 65,536 (the split measures the low word
    only); otherwise a message says what was found.
    """
    raw = s.read((ds, PILE_BASE), 28)
    piles = [int.from_bytes(raw[i:i + 4], "little") for i in range(0, 28, 4)]
    if any(p >= 0x10000 for p in piles):
        return (f"DS {ds:04X} is probably not the game's data segment: the "
                f"coin piles at DS:{PILE_BASE:04X} read {piles}; "
                f"name the segment with --ds")
    return None


def arm_pile(w: Watcher, ds: int) -> tuple[int, int]:
    """A `BPM` on each byte of all seven coin piles; returns the first pile's
    linear base and how many of the 28 bytes read nonzero (each owes one
    spurious first hit).  A fight can drop any coin kind, and the split cuts
    whichever piles it was given, so the gold pile alone can miss it."""
    base = dosboxx.linear((ds, PILE_BASE))
    nonzero = 0
    for p, name in enumerate(PILE_NAMES):
        for i in range(4):
            w.arm(base + 4 * p + i, f"{name}[{i}]")
            if w.s.read(base + 4 * p + i, 1) != b"\x00":
                nonzero += 1
    return base, nonzero


def read_code_before(s, row: dict) -> None:
    """Record on a hit row the bytes that precede its `CS:IP`."""
    if not row.get("cs_ip"):
        return
    seg, ofs = (int(x, 16) for x in row["cs_ip"].split(":"))
    lin = dosboxx.linear((seg, ofs))
    row["code"] = s.read(lin - CODE_WINDOW, CODE_WINDOW).hex()


def read_counts(s) -> dict:
    """`C` and `A` from the split's frame: `[bp-5]` and `[bp-6]`."""
    r = s.regs("SS", "BP")
    raw = s.read(dosboxx.linear((r["SS"], (r["BP"] - 6) & 0xFFFF)), 2)
    return {"a": raw[0], "c": raw[1]}


def count_fight(por: dosbox.PoolOfRadiance, brk_lin: int, *,
                budget: float = 900.0) -> dict | None:
    """Fight on until the code breakpoint halts the emulator; read `C` and `A`.

    **A code breakpoint prints nothing**, so it is found by asking whether the
    emulator is halted (`XSession.halted`).
    """
    s = por.s
    deadline = time.time() + budget
    s.run()
    while time.time() < deadline:
        if s.halted(timeout=1.5):
            r = s.regs("CS", "IP")
            if dosboxx.linear((r["CS"], r["IP"])) == brk_lin:
                return read_counts(s)
            s.run()
        bar = por.bar_kind()
        key = por.COMBAT_KEYS.get(bar or "")
        if key is not None:
            s.key(key)
        time.sleep(0.25)
    return None


def measure_split(por: dosbox.PoolOfRadiance, ovr: bytes, *, steps: int,
                  ds: int | None = None, fight_kw: dict | None = None,
                  walk=walk_to_encounter, share: int | None = None,
                  evidence: Evidence | None = None) -> dict:
    """Watch the seven coin piles through one fight, then read `C` and `A` in another.

    The party is already loaded.  Fight one: walk to an encounter, arm a
    `BPM` on each byte of the coin piles, fight, and classify every hit by the
    overlay bytes before its `CS:IP` (fill or split), which also gives the
    overlay's runtime base.  Fight two: the same walk with a `BP` at
    `COUNT_OFFSET` in that overlay, where `C` and `A` are read.  `ds` is read
    from the halted emulator unless given; it is the game's data segment only
    if the emulator halted in game code.  `share` is the hireling's treasure
    share, which picks the rule each pile's cut is judged against; the count
    read is reported and not used.
    """
    s = por.s
    report: dict = {"mode": "pile"}
    report["walk"] = walk(por, steps)
    if not report["walk"]["met"]:
        return report
    if evidence is not None:
        evidence.take(s, "encounter1")
    if not s.attach():
        return report
    if ds is None:
        ds = s.regs("DS")["DS"]
        bad = check_piles(s, ds)
        if bad:
            report["ds"] = ds
            report["why"] = bad
            return report
    report["ds"] = ds
    w = Watcher(s)
    base, nonzero = arm_pile(w, report["ds"])
    initial = s.read(base, 4 * len(PILE_NAMES))
    report["piles_at_encounter"] = {
        name: int.from_bytes(initial[4 * i:4 * i + 4], "little")
        for i, name in enumerate(PILE_NAMES)}
    report["pile_at_encounter"] = report["piles_at_encounter"]["gold"]
    w.drain()
    absorb_spurious(w, nonzero)
    s.run()
    report["fight"] = fight_watching(por, w, on_hit=lambda row: read_code_before(s, row),
                                     evidence=evidence, **(fight_kw or {}))
    report.update(summarize(initial, w.hits, ovr, base, None, share))
    if report.get("bias") is None:
        report["why"] = "no unambiguous split hit, so no overlay base"
        return report

    if not s.attach():
        return report
    s.clear_breakpoints()
    s.run()
    report["walk2"] = walk(por, steps)
    if not report["walk2"]["met"]:
        return report
    if evidence is not None:
        evidence.take(s, "encounter2")
    if not s.attach():
        return report
    s.clear_breakpoints()
    brk = report["bias"] + COUNT_OFFSET
    seen = s.read(brk, 8)
    report["count_code_matches"] = seen == ovr[COUNT_OFFSET:COUNT_OFFSET + 8]
    if not report["count_code_matches"]:
        report["why"] = "the overlay is not at the derived base in the second fight"
        return report
    s.brk(brk)
    counts = count_fight(por, brk)
    if counts is None:
        report["why"] = "the count breakpoint was not reached in the second fight"
    report.update(summarize(initial, w.hits, ovr, base, counts, share))
    return report


def pile(*, folder: pathlib.Path, source: str | None, at: str | None,
         steps: int, out: pathlib.Path, ds: int | None,
         place_like_path: pathlib.Path | None = None) -> dict:
    """`measure_split` on a folder installed into a fresh DOSBox-X."""
    if at:
        check_at(at)
    out.mkdir(parents=True, exist_ok=True)
    game = dosbox.find_game()
    evidence = Evidence(out)
    report: dict = {"mode": "pile", "folder": str(folder)}
    place = None
    if place_like_path is not None:
        donor = place_like_path.read_bytes()
        require_pool(donor, "donor")
        dax = dos_savegame.dax_number(donor)
        name = f"ECL{dax}.DAX"
        script = dos_savegame.dax_block(
            (game / name).read_bytes(), dos_savegame.current_area(donor), name=name)
        check_donor_script(donor, script)
        place = (donor, script)
        report["place_like"] = str(place_like_path)
    with dosboxx.claim("issue743 treasure split") as claimed:
        s = dosboxx.XSession(claimed, game)
        try:
            s.stage(fresh=True)
            letter = install_folder(s.save_dir, folder, at, source, place)
            if place is not None:
                report["placed"] = dos_savegame_summary(s.save_dir, letter)
                report["placed"]["differs_from_donor"] = surviving_differences(
                    (s.save_dir / f"SAVGAM{letter}.DAT").read_bytes(), donor)
            report.update(check_records_unchanged(folder, s.save_dir, letter))
            share = hireling_share(s.save_dir, letter)
            s.boot(fresh=False)
            por = dosbox.PoolOfRadiance(s)
            por.to_main_menu()
            por.load_game(letter)
            evidence.take(s, "loaded")
            report["status_at_load"] = por.status()
            report.update(measure_split(
                por, find_ovr(game), steps=steps, ds=ds, evidence=evidence, share=share,
                walk=functools.partial(walk_to_encounter, evidence=evidence)))
        finally:
            report["screenshots"] = evidence.files
            if evidence.errors:
                report["evidence_errors"] = evidence.errors
            (out / "report.json").write_text(json.dumps(report, indent=1,
                                                       default=str))
            s.close()
    return report


def dos_savegame_summary(save_dir: pathlib.Path, letter: str) -> dict:
    """Where the staged save stands, for the report."""
    data = (save_dir / f"SAVGAM{letter}.DAT").read_bytes()
    return {"area": dos_savegame.current_area(data),
            "geo": dos_savegame.geo_block(data),
            "dax": dos_savegame.dax_number(data),
            "position": list(dos_savegame.position(data)),
            "wallset": list(dos_savegame.wall_triple(data))}


def _counts(hits: list[dict]) -> dict:
    """How many hits each watched field took, and on which bars."""
    out: dict[str, dict] = {}
    for h in hits:
        row = out.setdefault(h["field"], {"n": 0, "bars": {}, "first": None})
        row["n"] += 1
        row["bars"][h.get("bar", "?")] = row["bars"].get(h.get("bar", "?"), 0) + 1
        if row["first"] is None:
            row["first"] = {"bar": h.get("bar"), "t": h.get("t"),
                            "old": h["old"], "new": h["new"],
                            "cs_ip": h.get("cs_ip")}
    return out


# -- Prayer's combat handlers, caught in a live fight ------------------------
#
# Pool's id-49 handler, its bonus test, the +1 helper (also id 35's handler)
# and the penalty live in one overlay unit that is **not in memory at the
# encounter menu**: the handler table points at a stub that reads `INT 3Fh`
# until the first call loads the unit, and `EA off seg`, a far jump into it,
# afterwards.  So the addresses are read at run time, from the table and then
# from the stub's jump, never written down.

#: `START.EXE` data-segment offsets: the far-pointer table of check-list
#: handlers (four bytes an id), and the head of the party's record list.
HANDLER_TABLE = 0x6828
PARTY_LIST = 0x5D96
#: Offsets inside a combatant record: the next record, the head of its effect
#: nodes, and its side (0 the party's).  A node is five bytes: id, minutes
#: (word), data, flag; the next-node pointer follows.
NEXT_RECORD = 0x104
NODE_LIST = 0x7F
SIDE = 0x10E
#: `DS` words the attack roll keeps: the saving-throw roll and the attack roll,
#: which the +1 helper raises together.
ROLL_WORDS = 0x6816
ATTACK_ROLL = 0x6822
#: The unit's stub segment relative to the image base, the stub entries of the
#: id-49 and id-35 handlers inside it, and where the unit's code sits in
#: `GAME.OVR`.
PRAYER_UNIT = 0x41
STUB_ID_49 = 0xED
STUB_ID_35 = 0xB6
PRAYER_UNIT_FILE = 0xEC5B
#: The four routines `GAME.OVR` offsets, by what they are.
PRAYER_ROUTINES = {"handler": 0xFF0D, "bonus": 0xFF30,
                   "penalty": 0xFF48, "helper": 0xF861}
#: The check list the attack roll walks, and the offset in its overlay unit
#: the list walker returns to (`GAME.OVR` 0x2BBE2 less that unit's 0x2AEEA).
ATTACK_LIST = 10
ATTACK_RETURN = 0x0CF8
#: How many frames of the `BP` chain are read, and how many bytes of each.
CHAIN_FRAMES = 4
FRAME_BYTES = 0x14
CODE_BYTES = 8
#: The most records the party list is followed through; a list that loops
#: stops here.
MAX_RECORDS = 24
MAX_NODES = 24


class PrayerWatchError(RuntimeError):
    """The debugger's view of the game is not the one this watch was measured on."""


def _w16(data: bytes, at: int) -> int:
    return int.from_bytes(data[at:at + 2], "little")


def _far(data: bytes, at: int) -> tuple[int, int]:
    """`(segment, offset)` of the far pointer at `at`."""
    return _w16(data, at + 2), _w16(data, at)


class PrayerWatch:
    """Break on Prayer's two stubs, follow the unit to where it loads, and log
    every halt with the registers, the stack and the combatant.

    `s` is a halted `dosboxx.XSession`; `ovr` is `GAME.OVR` and `image` the
    unpacked `START.EXE`, which the live bytes are checked against.
    """

    def __init__(self, s, ovr: bytes, image: bytes, note=None,
                 clock=time.time):
        self.s, self.ovr, self.image = s, ovr, image
        self.note = note or (lambda **kw: None)
        self.clock = clock
        self.ds: int | None = None
        self.stub: int | None = None
        #: Where the overlay is now, or None while it is out of memory.
        self.load: int | None = None
        #: The load segment the four routines are armed at, or None.
        self.armed_at: int | None = None
        self.halts: list[dict] = []
        #: Routines whose code did not match `GAME.OVR`, where they were armed
        #: or where a halt claimed one.
        self.mismatched: list[str] = []
        #: Whether any party attack reached a stub, counted or not.
        self.party_attack = False
        #: The party attack whose routines are being followed: set at a stub
        #: halt with the routines armed, replaced by the next stub halt.
        #: The first call loads the overlay before anything in it is armed,
        #: so it is never one.
        self.round: dict | None = None
        #: The round that completed, or None.
        self.completed: dict | None = None
        self.began = clock()

    def rd(self, seg: int, off: int, n: int) -> bytes:
        return self.s.read((seg, off & 0xFFFF), n)

    # -- the handler table, stubs and the unit's load segment ------------------

    def resolve(self, ds: int) -> dict:
        """The table's id-49 and id-35 entries and the stub bytes behind them;
        `table_ok` is False unless both name the unit's two stubs."""
        e49 = _far(self.rd(ds, HANDLER_TABLE + 49 * 4, 4), 0)
        e35 = _far(self.rd(ds, HANDLER_TABLE + 35 * 4, 4), 0)
        out = {"ds": f"{ds:04X}", "table49": f"{e49[0]:04X}:{e49[1]:04X}",
               "table35": f"{e35[0]:04X}:{e35[1]:04X}"}
        ok = e49[0] == e35[0] and (e49[1], e35[1]) == (STUB_ID_49, STUB_ID_35)
        out["table_ok"] = ok
        if not ok:
            return out
        seg = e49[0]
        want = self.image[PRAYER_UNIT * 16:PRAYER_UNIT * 16 + 12]
        out["descriptor_matches_image"] = self.rd(seg, 0, 12) == want
        out["stub49_bytes"] = self.rd(seg, STUB_ID_49, 5).hex()
        out["stub35_bytes"] = self.rd(seg, STUB_ID_35, 5).hex()
        self.ds, self.stub = ds, seg
        return out

    def stub_load(self) -> int | None:
        """The segment in the id-49 stub's far jump, or None while the stub
        still reads `INT 3Fh`; anything else is refused."""
        entry = self.rd(self.stub, STUB_ID_49, 5)
        if entry[0] == 0xEA:
            return _w16(entry, 3)
        if entry[:2] != b"\xcd\x3f":
            raise PrayerWatchError(
                f"the id-49 stub reads {entry.hex()}, neither INT 3Fh nor a far jump")
        return None

    def attach(self, tries: int = 6) -> dict:
        """Halt the running game and find a `DS` whose handler table reads
        right, running on between tries; raises when none does."""
        last: dict = {}
        for _ in range(tries):
            if not self.s.halted(timeout=1.0) and not self.s.attach():
                continue
            ds = self.ds if self.ds is not None else self.s.regs("DS")["DS"]
            last = self.resolve(ds)
            if last["table_ok"]:
                if not last["descriptor_matches_image"]:
                    raise PrayerWatchError(
                        "the unit's stub descriptor is not the one in START.EXE: "
                        f"{last}")
                return last
            self.s.run()
            time.sleep(0.7)
        raise PrayerWatchError(f"no data segment held Prayer's handler table: {last}")

    # -- the party and its nodes ----------------------------------------------

    def record_brief(self, seg: int, off: int) -> dict:
        rec = self.rd(seg, off, SIDE + 1)
        return {"at": f"{seg:04X}:{off:04X}",
                "name": rec[1:1 + min(rec[0], 15)].decode("latin-1", "replace"),
                "side": rec[SIDE]}

    def party(self) -> list[dict]:
        """Every record on the party list with its effect nodes."""
        rows: list[dict] = []
        seg, off = _far(self.rd(self.ds, PARTY_LIST, 4), 0)
        seen: set[tuple[int, int]] = set()
        while (seg, off) != (0, 0) and (seg, off) not in seen and len(rows) < MAX_RECORDS:
            seen.add((seg, off))
            rec = self.rd(seg, off, SIDE + 1)
            nodes: list[dict] = []
            nseg, noff = _far(rec, NODE_LIST)
            while (nseg, noff) != (0, 0) and len(nodes) < MAX_NODES:
                nd = self.rd(nseg, noff, 9)
                nodes.append({"at": f"{nseg:04X}:{noff:04X}", "id": nd[0],
                              "minutes": _w16(nd, 1), "data": nd[3], "flag": nd[4]})
                nseg, noff = _far(nd, 5)
            rows.append({"at": f"{seg:04X}:{off:04X}",
                         "name": rec[1:1 + min(rec[0], 15)].decode("latin-1", "replace"),
                         "side": rec[SIDE], "nodes": nodes})
            seg, off = _far(rec, NEXT_RECORD)
        return rows

    @staticmethod
    def holders(party: list[dict], node_id: int) -> list[str]:
        """Names of the party members carrying a node with this id."""
        return [m["name"] for m in party
                if m["side"] == 0 and any(n["id"] == node_id for n in m["nodes"])]

    # -- breakpoints ------------------------------------------------------------

    def arm(self) -> dict:
        """Break on both stubs and, once the unit has a load segment, on the
        four routines in it whose code matches `GAME.OVR`."""
        self.s.clear_breakpoints()
        self.s.brk((self.stub, STUB_ID_49))
        self.s.brk((self.stub, STUB_ID_35))
        armed = [f"{self.stub:04X}:{STUB_ID_49:04X} stub49",
                 f"{self.stub:04X}:{STUB_ID_35:04X} stub35"]
        if self.load is not None:
            for name, at in PRAYER_ROUTINES.items():
                off = at - PRAYER_UNIT_FILE
                if self.rd(self.load, off, CODE_BYTES) == self.ovr[at:at + CODE_BYTES]:
                    self.s.brk((self.load, off))
                    armed.append(f"{self.load:04X}:{off:04X} {name}")
                elif name not in self.mismatched:
                    self.mismatched.append(name)
        self.armed_at = self.load
        return {"armed": armed, "mismatched": list(self.mismatched),
                "bplist": self.s.breakpoints()}

    def routine_at(self, cs: int, ip: int) -> str | None:
        if self.armed_at is None or cs != self.armed_at:
            return None
        for name, at in PRAYER_ROUTINES.items():
            if ip == at - PRAYER_UNIT_FILE:
                return name
        return None

    # -- one halt -----------------------------------------------------------------

    def chain(self, ss: int, bp: int) -> list[dict]:
        out = []
        for _ in range(CHAIN_FRAMES):
            fr = self.rd(ss, bp, FRAME_BYTES)
            out.append({"bp": f"{bp:04X}", "frame": fr.hex(),
                        "ret": f"{_w16(fr, 4):04X}:{_w16(fr, 2):04X}"})
            nxt = _w16(fr, 0)
            if nxt <= bp:
                break
            bp = nxt
        return out

    def handle(self) -> dict:
        """Read and log the halt the emulator is stopped at."""
        r = self.s.regs("CS", "IP", "SS", "SP", "BP", "ES", "DI", "AX", "ZF")
        cs, ip, ss, sp, bp = r["CS"], r["IP"], r["SS"], r["SP"], r["BP"]
        stack = self.rd(ss, sp, 16)
        routine = self.routine_at(cs, ip)
        matches = None
        if routine:
            at = PRAYER_ROUTINES[routine]
            matches = self.rd(cs, ip, CODE_BYTES) == self.ovr[at:at + CODE_BYTES]
        was_armed = self.armed_at is not None
        stub = ip if cs == self.stub and ip in (STUB_ID_49, STUB_ID_35) else None
        h: dict = {"n": len(self.halts), "t": round(self.clock() - self.began, 2),
                   "cs_ip": f"{cs:04X}:{ip:04X}", "ss_sp": f"{ss:04X}:{sp:04X}",
                   "bp": f"{bp:04X}", "es_di": f"{r['ES']:04X}:{r['DI']:04X}",
                   "ax": f"{r['AX']:04X}", "zf": r["ZF"], "stack": stack.hex(),
                   "kind": ("stub49" if stub == STUB_ID_49 else "stub35" if stub
                            else routine or "other")}
        if routine and not matches:
            # Not the routine this address was armed for: never a hit.
            h["code_matches"] = False
            h["kind"] = "other"
            if routine not in self.mismatched:
                self.mismatched.append(routine)
            routine = None
        h["chain"] = ch = self.chain(ss, bp)
        # A far Pascal call: the combatant is asked about first and the node
        # second, so at an entry they sit at SP+0Ah and SP+6; inside the
        # handler, after its prologue, at BP+0Ch and BP+8.
        if stub or routine in ("handler", "helper"):
            cseg, coff, nseg, noff = _w16(stack, 12), _w16(stack, 10), _w16(stack, 8), _w16(stack, 6)
        elif routine in ("bonus", "penalty"):
            fr = self.rd(ss, bp, 0x10)
            cseg, coff, nseg, noff = _w16(fr, 0xE), _w16(fr, 0xC), _w16(fr, 0xA), _w16(fr, 8)
            h["node_data_bit4"] = self.rd(ss, bp - 1, 1)[0]
            h["es_di_combatant"] = self.record_brief(r["ES"], r["DI"])
        else:
            cseg = None
        if cseg is not None:
            h["combatant"] = self.record_brief(cseg, coff)
            h["node"] = {"at": f"{nseg:04X}:{noff:04X}",
                         "bytes": self.rd(nseg, noff, 5).hex()}
        h["ds_6816_6822"] = {"6816": self.rd(self.ds, ROLL_WORDS, 1).hex(),
                             "6822": self.rd(self.ds, ATTACK_ROLL, 1).hex()}
        if routine:
            h["code_matches"] = True
        if stub:
            self.round = None
            # Frames: the dispatcher (id at BP+10h), the query, the list walker
            # (list at BP+0Ah) and the attack roll (attacker at BP+0Ch).
            try:
                frames = [bytes.fromhex(f["frame"]) for f in ch]
                h["id"] = frames[0][0x10]
                h["list"] = frames[2][0x0A]
                ret = int(ch[2]["ret"].split(":")[1], 16)
                h["walker_returns_to_unit_offset"] = f"{ret:04X}"
                attacker = self.record_brief(_w16(frames[3], 0xE), _w16(frames[3], 0xC))
                h["attacker"] = attacker
                if (h["list"] == ATTACK_LIST and ret == ATTACK_RETURN
                        and attacker["side"] == 0):
                    self.party_attack = True
                    h["party_attack"] = True
                    h["routines_armed"] = was_armed
                    if was_armed:
                        party = self.party()
                        mine = next((m for m in party if m["at"] == attacker["at"]), None)
                        h["attacker_nodes"] = None if mine is None else mine["nodes"]
                        self.round = {"attacker": attacker["at"], "party": party,
                                      "attacker_nodes": h["attacker_nodes"]}
            except (IndexError, ValueError) as e:
                h["chain_error"] = f"{type(e).__name__}: {e}"
            entry = self.rd(self.stub, STUB_ID_49, 5)
            h["stub49_bytes_now"] = entry.hex()
            now = self.stub_load()
            h["load_now"] = None if now is None else f"{now:04X}"
            if now != self.armed_at:
                # Loaded, moved, or unloaded again: routine breakpoints at
                # the old segment would halt in whatever is there now.
                self.load = now
                h["rearmed"] = self.arm()
        self.halts.append(h)
        self.note(event="prayer-halt", **h)
        return h

    def round_done(self, h: dict) -> bool:
        """The counted party attack's own helper or penalty ran, before any
        other stub halt: a monster's helper halt is somebody else's roll."""
        if (self.round is None or h["kind"] not in ("helper", "penalty")
                or h.get("combatant", {}).get("at") != self.round["attacker"]):
            return False
        self.completed = self.round
        return True

    # -- the fight ------------------------------------------------------------------

    def run_fight(self, seconds: float, idle) -> str:
        """Resume and log halts until one attack round has run, the fight is
        over (`idle()` returns True) or `seconds` have passed; returns why."""
        end = self.clock() + seconds
        self.s.run()
        while self.clock() < end:
            if self.s.halted(timeout=1.0):
                h = self.handle()
                if self.round_done(h):
                    return "one attack round"
                self.s.run()
            elif idle():
                return "fight over"
        return "budget"

    def finish(self) -> list[dict] | None:
        """Read the party at the stop, then take every breakpoint off and let
        the game run; each step is its own attempt, so one failing leaves the
        others done.  Returns the party, or None when it could not be read."""
        at_stop = None
        try:
            if self.s.halted(timeout=1.0) or self.s.attach():
                at_stop = self.party()
        except Exception as e:  # noqa: BLE001 -- the release below must still run
            self.note(event="prayer-finish-error", step="read", error=repr(e))
        for label, act in (("clear", self.s.clear_breakpoints), ("run", self.s.run)):
            try:
                act()
            except Exception as e:  # noqa: BLE001
                self.note(event="prayer-finish-error", step=label, error=repr(e))
        return at_stop

    def summary(self, node_id: int, at_encounter: list[dict],
                at_stop: list[dict] | None) -> dict:
        """What the run shows, and whether it may be called conclusive.

        A run is inconclusive when no member carried the tested node at the
        encounter menu, when one that did no longer does at the stop (a
        Prayer lasts ten minutes and every square walked costs one), or when
        an armed routine's code did not match `GAME.OVR`, when no party attack
        armed at the stubs ran its helper or penalty to the end, when the
        tested node was not on the attacker (id 49) or anywhere in the party
        (id 35) at that attack's stub halt, or when the stop-time party was
        not read.
        """
        why = []
        carriers = self.holders(at_encounter, node_id)
        if not carriers:
            why.append(f"no party member carried a node with id {node_id} at the "
                       "encounter menu, so it expired or was never there")
        elif at_stop is None:
            why.append("the party was not read at the stop, so the node's "
                       "survival is unknown")
        else:
            lost = [n for n in carriers if n not in self.holders(at_stop, node_id)]
            if lost:
                why.append(f"{', '.join(lost)} carried the id-{node_id} node at "
                           "the encounter menu and not at the stop")
        if self.completed is None:
            why.append("no party attack armed at the stubs ran its helper or "
                       "penalty: the first call loads the overlay before its "
                       "routines are armed, so a round needs a later attack")
        else:
            done = self.completed
            if node_id == 49:
                ok = any(n["id"] == 49 for n in done["attacker_nodes"] or [])
            else:
                ok = bool(self.holders(done["party"], node_id))
            if not ok:
                why.append(f"the id-{node_id} node was not "
                           f"{'on the attacker' if node_id == 49 else 'in the party'} "
                           "at the attack's stub halt")
        if self.mismatched:
            why.append("the code at the resolved segment did not match GAME.OVR for "
                       + ", ".join(self.mismatched))
        kinds = [h["kind"] for h in self.halts]
        return {"node": node_id, "conclusive": not why, "why": why,
                "carriers": carriers, "halts": len(self.halts),
                "party_attack": self.party_attack,
                "round_completed": self.completed is not None,
                "helper_hits": kinds.count("helper"),
                "penalty_hits": kinds.count("penalty"),
                "load_segment": None if self.load is None else f"{self.load:04X}"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=("locate", "watch", "truth", "pile"))
    ap.add_argument("--c64", default=None, help="the C64 save disk to convert")
    ap.add_argument("--slot", default="A", help="the DOS slot to write")
    ap.add_argument("--steps", type=int, default=40,
                    help="how many steps to try before giving up on a fight")
    ap.add_argument("--chars", default="1",
                    help="which party slots to watch, comma separated")
    ap.add_argument("--only", default="",
                    help="watch only these fields, comma separated")
    ap.add_argument("--out", default=None, help="where the run's files go")
    ap.add_argument("--engine-slot", default="B",
                    help="the slot `truth` has the engine write for itself")
    ap.add_argument("--folder", type=pathlib.Path, default=None,
                    help="`pile`: the DOS save folder to install as it stands")
    ap.add_argument("--from-slot", default=None,
                    help="`pile`: which slot of the folder, when it holds several")
    ap.add_argument("--place-like", type=pathlib.Path, default=None,
                    help="`pile`: a `SAVGAM?.DAT` the DOS game wrote in an "
                         "indoor area; the party is moved to where it stands")
    ap.add_argument("--at", default=None, metavar="X,Y,FACING",
                    help="`pile`: poke the party's square before loading")
    ap.add_argument("--ds", type=lambda x: int(x, 16), default=None,
                    help="`pile`: the game's data segment, hex; the fallback when "
                         "the DS read at the encounter fails its check")
    args = ap.parse_args(argv)

    chars = tuple(int(x) for x in args.chars.split(",") if x.strip())
    only = tuple(x for x in args.only.split(",") if x.strip())
    out = pathlib.Path(args.out or OUT)
    if args.command == "pile":
        if args.folder is None:
            ap.error("pile needs --folder")
        report = pile(folder=args.folder, source=args.from_slot, at=args.at,
                      steps=args.steps, out=out, ds=args.ds,
                      place_like_path=args.place_like)
    elif args.command == "truth":
        report = truth(c64=args.c64, slot=args.slot,
                       engine_slot=args.engine_slot, steps=args.steps,
                       out=out)
    else:
        report = run(c64=args.c64, slot=args.slot, steps=args.steps, out=out,
                     stop_after_locate=args.command == "locate",
                     watch_chars=chars, only=only)
    text = json.dumps(report, indent=1, default=str)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
