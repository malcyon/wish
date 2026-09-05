#!/usr/bin/env python3
"""Lose a Pool of Radiance fight on purpose, and read what the game prints.

Every fight this project has driven, the party won, so `tools/session.py`'s
`LOST_TEXT` was a guess with no specimen behind it and `fight()` reported
`ended` for a defeat it could not name (`#128`).  This drives the other
outcome.

The engine will not let a party lose on request, so the loss is arranged the
way `tools/statusdrive.py` arranged a single character's status: **hit points
are set through the monitor and the engine's own damage code reacts**.  Here
it is every occupied roster slot rather than one, at `$8300 + N*$20 + 0x19`,
and then every turn is passed so nobody strikes back.  Nothing else is
touched: the status byte at `+0x00`, the messages, the outcome byte and
whatever the game does next are all the game's.

    tools/defeatdrive.py --save PORSAVE13.D64 --slot 3
    tools/defeatdrive.py --save PORSAVE13.D64 --hp 1 --after 90

`PORSAVE13.D64` three steps into the Slums is the one-ambush reproduction the
combat harness was built on: six characters, eight orcs, everybody in contact
on turn 1.

**Three things are recorded that a screenshot cannot carry.**

* Every distinct screen, with the frame count that saw it, so the message can
  be transcribed as the game spells it rather than as anybody expects it to
  be spelled.  `POST.COM`'s own table has `THE PARTY HAS LOST`,
  `THE PARTY RUNS AWAY` and `THE PARTY HAS WON !`, and the status words it
  leaves behind include `UNCONSIOUS`, which is the game's spelling.
* **The program counter**, sampled after the outcome line appears.  The losing
  branch at `POST.COM $0938` ends at `$0957`, which is `JMP $0957` -- a jump
  to itself -- on two of its three exits, and nothing on the disk side writes
  those bytes.  Whether a player is really left looking at a locked machine
  cannot be read off the code; a PC that stays at `$0957` says it and one that
  moves refutes it.
* **Whether the save was touched.**  The staged save disk is hashed before the
  fight and again after, so "the game wrote nothing" is a measurement rather
  than an assumption.

Everything goes to `--out`: `run.jsonl` one event per line, `screens.txt` the
distinct screens in order, `hang.json` the PC samples.  Nothing here writes to
the player's disks -- `stage_disks` copies the eight sides and the save into
the pool slot, and `Session.attach` refuses any path outside it.

Written for `#128 (Nothing has ever read what the game prints when the party
loses a fight)`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap import actions as A  # noqa: E402
from automap.paths import find_disks  # noqa: E402
from goldbox import savegame  # noqa: E402
from tools import session as S  # noqa: E402

#: The player's disks: `$POR_DISKS`, then the search every other tool does.
DISKS = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")

#: `SAVEDGAME1`'s roster page, live.  Eight blocks of `$20`, one per save
#: slot; `goldbox/savegame.py` names the fields inside one.
ROSTER = savegame.SAVE1_LOAD_ADDRESS                            # $8300
ROSTER_BYTES = savegame.ROSTER_STRIDE * savegame.ROSTER_COUNT   # $100
STATUS = 0x00                       # record 0x100, the status byte
HP = savegame.ROSTER_HP_CURRENT     # 0x19, the 16-bit current hit points

#: The result byte `POST.COM $091A` writes and the ECL scripts read:
#: 0 and 1 won, 128 lost, 129 ran away.  `docs/128-guide-and-scripting.md`.
RESULT = 0x6DC7

#: The party size `LIBRARY $3EAD` counts up while it draws the party panel,
#: which the losing branch compares its dead against.
PARTY_SIZE = 0x6E3E

#: `POST.COM $0957`, the jump-to-itself the losing branch can reach.  The
#: overlay base is `$0800`, not the `$1000` the PRG header claims.
SPIN = 0x0957

#: What the low three bits of record `0x100` name, read out of `LIBRARY
#: $38BE` -- `AND #$07 / ADC #$29` into LIBRARY's own string table.  Zero is
#: not a status; it is an empty roster slot.
STATUS_WORDS = {0: "(empty)", 1: "OK", 2: "GONE", 3: "DEAD", 4: "DYING",
                5: "UNCONSIOUS", 6: "RUNNING", 7: "STONED"}

#: The three lines `POST.COM` can print when a fight ends, from its own
#: pointer table (lo `$2A8D`, hi `$2AC5`, entries 2, 3 and 4).
OUTCOME_LINES = {
    "lost": "THE PARTY HAS LOST",
    "ran": "THE PARTY RUNS AWAY",
    "won": "THE PARTY HAS WON",
}


def describe(value: int) -> str:
    """`$84 DYING` -- the byte and the word `LIBRARY $38BE` would draw."""
    return f"${value:02X} {STATUS_WORDS.get(value & 7, '?')}" + (
        " (down)" if value & 0x80 else "")


class Log:
    """One line of JSON per event, and a running transcript on stdout."""

    def __init__(self, out: pathlib.Path, quiet: bool = False):
        out.mkdir(parents=True, exist_ok=True)
        self.dir = out
        self.file = open(out / "run.jsonl", "w")
        self.quiet = quiet

    def emit(self, kind: str, **kw) -> None:
        kw["kind"] = kind
        kw["t"] = round(time.time(), 3)
        self.file.write(json.dumps(kw, default=str) + "\n")
        self.file.flush()

    def say(self, *a) -> None:
        if not self.quiet:
            print(*a, flush=True)

    def close(self) -> None:
        self.file.close()


def roster_page(sess) -> bytes:
    with sess.mon(5) as m:
        return m.read(ROSTER, ROSTER_BYTES)


def statuses(page: bytes) -> list[int]:
    return [page[i * savegame.ROSTER_STRIDE + STATUS]
            for i in range(savegame.ROSTER_COUNT)]


def hitpoints(page: bytes) -> list[int]:
    out = []
    for i in range(savegame.ROSTER_COUNT):
        at = i * savegame.ROSTER_STRIDE + HP
        out.append(page[at] | page[at + 1] << 8)
    return out


def wound_all(sess, slots: list[int], to: int) -> None:
    """Set every named slot's current hit points, and touch nothing else.

    One monitor block for the lot, so the party is wounded between two of the
    engine's own instructions rather than across several stops -- a fight that
    resolves a blow in the gap would see half a wounded party.
    """
    with sess.mon(5) as m:
        for i in slots:
            at = ROSTER + i * savegame.ROSTER_STRIDE + HP
            m.write(at, bytes([to & 0xFF, to >> 8]))


def digest(path: str | os.PathLike) -> str | None:
    p = pathlib.Path(path)
    if not p.exists():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()


class Frames:
    """Distinct screens, in order, deduplicated against the one before.

    The screen is a rectangle that gets overwritten rather than a stream, so
    two consecutive readings that are equal are the same screen still showing
    -- `automap/combatlog.py` makes the same distinction for the message band.
    """

    def __init__(self):
        self.seen: list[tuple[list[str], int, float]] = []

    def add(self, rows: list[str]) -> bool:
        """True when this reading is a screen not already pending."""
        if self.seen and self.seen[-1][0] == rows:
            self.seen[-1] = (rows, self.seen[-1][1] + 1, self.seen[-1][2])
            return False
        self.seen.append((rows, 1, time.time()))
        return True

    def write(self, path: pathlib.Path, started: float) -> None:
        out = []
        for rows, count, when in self.seen:
            out.append(f"--- +{when - started:6.1f}s, {count} reading(s) ---")
            out += [f"{i:2d} |{r}|" for i, r in enumerate(rows) if r.strip()]
        path.write_text("\n".join(out) + "\n")

    def text(self) -> str:
        return "\n".join("\n".join(rows) for rows, _, _ in self.seen)


def rows_of(s) -> list[str]:
    return [s.row(r).rstrip() for r in range(25)]


def drive(sess, log: Log, frames: Frames, budget: float,
          poll: float) -> str | None:
    """Pass every turn and watch, until one of the three outcome lines shows.

    This is `Session.fight`'s loop with two differences that matter here: it
    records every distinct screen rather than only row 24, and it stops on the
    outcome *line* rather than on the mode byte -- because the whole question
    is whether the game ever gets back to the mode byte at all.
    """
    end = time.time() + budget
    outcome = None
    while time.time() < end:
        s = sess.screen()
        if s is not None:
            rows = rows_of(s)
            if frames.add(rows):
                log.emit("screen", rows=rows)
            text = "\n".join(rows)
            for name, line in OUTCOME_LINES.items():
                if line in text and outcome is None:
                    outcome = name
                    log.emit("outcome_line", outcome=name, line=line)
                    log.say(f"  outcome line on screen: {line!r}")
                    return outcome
        state = sess.combat_state(s)
        if state.kind == S.BAR_COMMAND:
            sess.combat_turn()
        elif state.kind == S.BAR_DONE:
            sess.end_turn()
        elif state.kind == S.BAR_CONTINUE:
            # `CONTINUE BATTLE : YES NO`.  `YES` here, not `NO`: `NO` is how a
            # driven fight walks away, and walking away is the outcome this
            # tool exists to avoid.
            sess.combat_bar("YES", timeout=12.0)
        elif state.kind == S.BAR_YESNO:
            sess.combat_bar("NO", timeout=12.0)
        elif state.kind == S.BAR_MOVE:
            sess.press_kernal(0x0D)
        elif state.kind == S.BAR_PRESS:
            sess.press_kernal(0x0D)
            sess.await_change(state.text, timeout=4.0)
        else:
            sess.idle(poll)
    return outcome


def watch_after(sess, log: Log, frames: Frames, seconds: float,
                poll: float, knock_at: float = 0.0) -> list[int]:
    """Sample the screen and the program counter after the outcome line.

    The program counter is the point.  `POST.COM $0957` is `JMP $0957`, and a
    PC that keeps reading back as `$0957` is a machine going nowhere; a PC
    that moves says the branch was not taken and the game went on.

    `knock_at` seconds in, Return and the space bar are put in the keyboard
    buffer once.  A screen that does not move afterwards is what says a player
    sitting at this message cannot get past it by pressing anything -- which
    is a different claim from "the loop has no exit" and needs its own
    evidence.  Before that moment nothing is pressed, so a prompt this is
    trying to see is never answered by accident.
    """
    pcs: list[int] = []
    started = time.time()
    end = started + seconds
    knocked = knock_at <= 0
    while time.time() < end:
        if not knocked and time.time() - started >= knock_at:
            knocked = True
            for code in (0x0D, 0x20, 0x0D):
                sess.press_kernal(code)
            log.emit("knocked", after=round(time.time() - started, 1))
            log.say("  pressed Return, space, Return at the message")
        try:
            with sess.mon(5) as m:
                pc = m.registers().get(A.pc_register(m))
                mode = m.read(S.MODE, 1)[0]
                result = m.read(RESULT, 1)[0]
                size = m.read(PARTY_SIZE, 1)[0]
        except Exception as exc:
            log.emit("sample_failed", error=repr(exc))
            time.sleep(poll)
            continue
        if pc is not None:
            pcs.append(pc)
        s = sess.screen()
        if s is not None and frames.add(rows_of(s)):
            log.emit("screen", rows=rows_of(s))
        log.emit("after", pc=pc, mode=mode, result=result, party_size=size)
        time.sleep(poll)
    return pcs


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--save", default="PORSAVE13.D64",
                   help="the save disk to load, inside --disks")
    p.add_argument("--disks", default=str(DISKS),
                   help="where the player's disks are; read, never written")
    p.add_argument("--slot", type=int, default=None,
                   help="demand this pool slot rather than the first free one")
    p.add_argument("--hp", type=int, default=1,
                   help="hit points to leave every character on (default 1)")
    p.add_argument("--budget", type=float, default=420.0,
                   help="seconds to give the fight")
    p.add_argument("--after", type=float, default=90.0,
                   help="seconds to watch after the outcome line appears")
    p.add_argument("--poll", type=float, default=1.0,
                   help="seconds between readings")
    p.add_argument("--knock", type=float, default=20.0,
                   help="seconds into the watch to press Return and space "
                        "once, to see whether the screen can be got past; "
                        "0 presses nothing")
    p.add_argument("--walk", default="I",
                   help="the move to repeat while looking for a fight")
    p.add_argument("--steps", type=int, default=400,
                   help="give up after this many steps with no fight")
    p.add_argument("--out", default=None, help="run directory")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    disks = pathlib.Path(args.disks)
    out = pathlib.Path(args.out) if args.out else (
        ROOT / "work" / "issue128" / pathlib.Path(args.save).stem)
    log = Log(out, args.quiet)
    frames = Frames()
    started = time.time()
    slot = S.claim_slot(args.slot, f"defeatdrive/{args.save}")
    log.say(f"slot {slot.n} display {slot.display}  out {out}")
    rc, sess = 0, None
    try:
        sess = S.Session(S.stage_disks(slot, disks, args.save), slot=slot)
        before_disk = digest(sess.save_disk)
        log.emit("save_disk", when="staged", sha256=before_disk)
        if not sess.boot():
            raise RuntimeError("boot failed")
        if not sess.load_save():
            raise RuntimeError("load_save failed")
        if not sess.begin_adventuring():
            raise RuntimeError("begin_adventuring failed")
        sess.settle(3)
        log.say(f"in the world at {sess.position()}")
        page = roster_page(sess)
        before = statuses(page)
        occupied = [i for i, v in enumerate(before) if v]
        log.emit("roster", when="in the world", status=before,
                 hp=hitpoints(page), occupied=occupied)
        log.say("  before: " + "  ".join(
            f"{i}:{describe(before[i])}" for i in occupied))

        steps = 0
        while not sess.in_combat():
            if steps > args.steps:
                raise RuntimeError("route exhausted with no fight")
            sess.walk_one(args.walk)
            sess.handle_prompt()
            steps += 1
        log.say(f"ambushed after {steps} steps")
        log.emit("fight_start", steps=steps)
        sess.settle(2)

        wound_all(sess, occupied, args.hp)
        page = roster_page(sess)
        log.emit("wounded", slots=occupied, hp=args.hp,
                 status=statuses(page), current=hitpoints(page))
        log.say(f"wounded {len(occupied)} character(s) down to {args.hp} "
                "hit point(s) each")

        outcome = drive(sess, log, frames, args.budget, args.poll)
        log.say(f"fight ended: {outcome or 'no outcome line seen'}")

        # Everything the run is *for* is read here, before the long watch,
        # because a run that is cut short loses whatever comes after it.  The
        # only DOS item-granted specimen this project ever had went that way
        # (`.claude/rules/testing.md`), and so did the first attempt at this
        # measurement.
        page = roster_page(sess)
        after = statuses(page)
        log.emit("roster", when="outcome", status=after, hp=hitpoints(page))
        log.say("  after:  " + "  ".join(
            f"{i}:{describe(after[i])}" for i in occupied))
        with sess.mon(5) as m:
            result = m.read(RESULT, 1)[0]
            size = m.read(PARTY_SIZE, 1)[0]
        log.emit("result", byte=result, party_size=size)
        log.say(f"  $6DC7 = ${result:02X}   party size $6E3E = {size}")
        after_disk = digest(sess.save_disk)
        log.emit("save_disk", when="outcome", sha256=after_disk,
                 changed=after_disk != before_disk)
        log.say("  the save disk "
                + ("CHANGED" if after_disk != before_disk
                   else "was not written"))
        if sess.save_disk and pathlib.Path(sess.save_disk).exists():
            shutil.copy(sess.save_disk, out / "save-after.d64")
        frames.write(out / "screens.txt", started)
        try:
            sess.kbd.screenshot(str(out / "outcome.png"))
        except Exception as exc:
            log.emit("shot_failed", error=repr(exc))

        pcs = watch_after(sess, log, frames, args.after, args.poll,
                          knock_at=args.knock)

        spun = sum(1 for pc in pcs if pc == SPIN)
        (out / "hang.json").write_text(json.dumps(
            {"samples": len(pcs), "at_spin": spun, "spin": SPIN,
             "pcs": [f"${pc:04X}" for pc in pcs]}, indent=1) + "\n")
        log.say(f"  program counter: {spun} of {len(pcs)} readings at "
                f"${SPIN:04X}")

        frames.write(out / "screens.txt", started)
        log.say(f"  {len(frames.seen)} distinct screens -> "
                + str(out / "screens.txt"))

        # And again at the end, because a knock that *did* move the game on
        # would have written the save between the two readings.  The copy
        # travels out of the slot whatever happened: a slot's directory goes
        # with the slot, and a specimen nobody copied out is a specimen
        # nobody has (`.claude/rules/testing.md`).
        last_disk = digest(sess.save_disk)
        log.emit("save_disk", when="end", sha256=last_disk,
                 changed=last_disk != before_disk)
        if last_disk != after_disk and pathlib.Path(sess.save_disk).exists():
            shutil.copy(sess.save_disk, out / "save-end.d64")
            log.say("  the save disk changed again during the watch")
    except Exception as exc:
        import traceback
        try:
            s = sess and sess.screen()
            screen = rows_of(s) if s else []
        except Exception:
            screen = []
        if screen:
            (out / "failed-screen.txt").write_text("\n".join(screen) + "\n")
            log.say("\n".join(ln for ln in screen if ln.strip()))
        log.emit("failed", error=repr(exc), screen=screen,
                 traceback=traceback.format_exc())
        traceback.print_exc()
        rc = 1
    finally:
        try:
            frames.write(out / "screens.txt", started)
        except Exception:
            pass
        for what, step in (("session close", lambda: sess and sess.close()),
                           ("slot teardown", slot.teardown),
                           ("slot release", slot.release)):
            try:
                step()
            except Exception as exc:
                log.emit("cleanup_failed", step=what, error=repr(exc))
                log.say(f"Cleanup failed at {what}: {exc!r}")
                rc = rc or 1
        log.close()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
