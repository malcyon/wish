#!/usr/bin/env python3
"""Drive a Curse of the Azure Bonds party into a fight and try to flee it, for `#445 (The game's third fight outcome, THE PARTY RUNS AWAY, has never been seen on a screen)`.

The Pool of Radiance half of that issue is `tools/pool_of_radiance/fleedrive.py`, which cannot be
reused whole for Curse: it boots `tools/c64/session.py`'s own `Session`, and Curse
boots through `tools/curse_of_the_azure_bonds/curserun.py`'s `CurseSession`.  What does reuse whole is
`Flight`, `tools/pool_of_radiance/fleedrive.py`'s tactic -- it is written against the generic
`Session` interface (`battle()`, `acting()`, `combat_bar()`, `await_bar()`,
`press_kernal()`, `kbd.key()`, `combat_turn()`), all of which `CurseSession`
already answers, with its own overrides where a bar needs the KERNAL buffer --
and `Session.fight(budget, tactic=...)` is already written to take it: its
`BAR_YESNO` branch names `Flight` and that issue.  So this file is the harness
around that pairing, not a second `Flight`.

**Reaching the fight is `tools/c64/laterbattle.py`'s `curse_fight`, not a fixed
walk**: `#648 (See THE PARTY RUNS AWAY on a Curse or Silver Blades screen, and
confirm the mercy heal on the losing side of a fight)` found that this file's
own fixed route from `cited/131-m1/CURSEI.D64` never met a fight at all, where
`curse_fight` already reaches Tilverton's tavern brawl over the area's own
`GEO` and `PUNCH BARKEEP` reliably, for `#334`'s own runs. So this file stages
a `laterbattle.Battle`, hands it to `curse_fight`, then waits for the combat
arena exactly as `laterbattle.main` does, and only then hands the fight to
`Flight`.

**The flee line is up for under half a second** (`tools/c64/session.py`'s own
comment above `RAN_TEXT`), so this file's `--poll` defaults to `0.12` rather
than `fight`'s own `1.0` -- a one-second poll is the reading `#648` says
missed it.

    POR_HEADLESS=1 .venv/bin/python tools/curse_of_the_azure_bonds/curseflee.py --slot 6 \\
        --save path/to/CURSEI.D64 --out DIR

`--save` is a Curse save disk (SIDE0) to copy into the slot.  The disks come
from `--disks`, else `$POR_DISKS`, else `automap/gamedisks.py`'s Curse entry.
Loads the save with `tools/curse_of_the_azure_bonds/curseload.py`, walks to Tilverton's tavern and
punches the barkeep, then fights it with `Flight` and writes a JSON log, a
screenshot and the final screen under `--out`.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from automap.vice import read_screen  # noqa: E402
from goldbox import savegame  # noqa: E402
from tools.c64 import laterbattle  # noqa: E402
from tools.c64 import session as S  # noqa: E402
from tools.pool_of_radiance.fleedrive import Flight, Log, rows_of  # noqa: E402
from tools.registry import scratch  # noqa: E402

#: `POST.COM $0906`, `STX $7EC7`: how the fight ended -- 0 and 1 won, `$80`
#: lost, `$81` ran away.  The only absolute store to it on any Curse disk, and
#: Pool of Radiance's `$6DC7` is a different byte.
RESULT = 0x7EC7
RAN_AWAY = 0x81

#: `POST.COM $0E18`, the drop loop's spare flag, Pool's `$6DE6` here.
MERCY = 0x7EE6

#: `POST.COM $0909`, where the machine stops when `RESULT` is written, and
#: `$091C`, the `JSR $0DF2` after the message call at `$0919`: the line has just
#: been drawn and the drop loop has not yet touched the party.  An exec stop at
#: `$091C` armed any earlier fires in `COMBAT`, which runs at the same address.
LINE_DRAWN = 0x091C

#: The combatant table, `automap/combat.py`'s Curse row; byte 0 of each
#: `savegame.ROSTER_STRIDE` block is the status, and the party is the first six.
ROSTER = 0x6700
PARTY = 6
RUNNING = 0x86


def party_status(m) -> list[int]:
    blob = m.read(ROSTER, PARTY * savegame.ROSTER_STRIDE)
    return [blob[i * savegame.ROSTER_STRIDE] for i in range(PARTY)]


def escaped(status: list[int]) -> int:
    """Characters `COMBAT $1719` marked as running, which is what `POST.COM $08C6` counts.

    `Flight` cannot say: `GOT AWAY` is on row 24 for a moment and it missed 3
    of 5 in the run that first read this.  The drop loop sets `$86` back to
    `$01` once the flee branch is taken, so the count is only good from before
    `$091C`.
    """
    return sum(1 for v in status if v == RUNNING)


class _Resumes:
    """The connection the caller sees: a `resume` first handles a stop that fired.

    VICE halts at a stop that fires while a connection is open, and resuming
    without asking would run the machine past it, so the handler would read a
    later moment.
    """

    def __init__(self, trap, m):
        self._trap, self._m = trap, m

    def resume(self):
        self._trap.check(self._m, resume=False)
        return self._m.resume()

    def __getattr__(self, name):
        return getattr(self._m, name)


class _Watched:
    """A `Monitor` context that runs the trap's check on entry and exit.

    The exit check does not resume: the machine is still at any stop that fired
    during the body, and EXIT resumes it after the handler has read.
    """

    def __init__(self, trap, inner):
        self.trap, self.inner = trap, inner
        self._m = None

    def __enter__(self):
        self._m = self.inner.__enter__()
        try:
            self.trap.check(self._m)
        except BaseException:
            self.inner.hang_up()
            raise
        return _Resumes(self.trap, self._m)

    def _gone(self) -> bool:
        """Whether the monitor's socket is closed or no longer connected."""
        sock = getattr(self.inner, "sock", True)
        if sock is None:
            return True
        probe = getattr(sock, "getpeername", None)
        try:
            if probe is not None:
                probe()
        except OSError:
            return True
        return False

    def __exit__(self, *exc):
        # A monitor that is gone would spend a full timeout on every read of
        # the check; the hang-up below must run whatever the check does.
        try:
            if self._gone():
                self.trap.log.emit("exit_check_skipped",
                                   note="the monitor is gone; a stop that fired "
                                        "is handled by the next connection")
            else:
                self.trap.check(self._m, resume=False)
        finally:
            self.inner.hang_up()
        return False


class Trap:
    """Stop the machine when `POST.COM` stores the fight's result, and read the line then.

    Polling cannot see THE PARTY RUNS AWAY: it is drawn and cleared in tens of
    milliseconds.  So a stop-on-store checkpoint on `RESULT` holds the machine
    at `$0909`; every monitor connection the fight opens is wrapped so the first
    thing it does is ask whether that fired.  On `$81` a one-shot exec stop at
    `$091C` is added *then* and the same connection waits for it, because VICE
    talks only to the connection that was open when it stopped
    (`automap/vice.py`'s `resume`).
    """

    def __init__(self, sess, log, out: pathlib.Path, wait: float = 10.0):
        self.sess, self.log, self.out, self.wait = sess, log, out, wait
        self.cp: int | None = None
        self.hits = 0
        self.result: int | None = None
        self.status_at_write: list[int] | None = None
        self.seen = False              # the screen was read at $091C
        self.degraded = False          # the monitor stopped answering
        self._mon = None
        self._busy = False

    def arm(self) -> None:
        self._mon = self.sess.mon
        with self._mon(10) as m:
            self.cp = m.checkpoint_set(RESULT, store=True, stop=True)
            m.hang_up()
        self.sess.mon = self.mon
        self.log.say(f"armed a stop on the write to ${RESULT:04X}")

    def mon(self, timeout: float = 5.0):
        return _Watched(self, self._mon(timeout))

    def check(self, m, resume: bool = True) -> None:
        if self.cp is None or self._busy or self.degraded:
            return
        self._busy = True
        try:
            hits = m.checkpoint_hits(self.cp)
            if hits <= self.hits:
                return
            self.hits = hits
            self.result = m.peek(RESULT)
            self.status_at_write = party_status(m)
            self.log.emit("result_write", value=self.result, hits=hits,
                          status=self.status_at_write,
                          escaped=escaped(self.status_at_write))
            self.log.say(f"  ${RESULT:04X} written: ${self.result:02X}, "
                         f"party status {self.status_at_write}")
            # Only here, on a hit of the store checkpoint: an `$81` sitting in
            # `RESULT` from an earlier fight is not this fight's write.
            if self.result == RAN_AWAY:
                self.capture(m)
            # The machine is stopped at the store or at `$091C`; say so
            # explicitly rather than leaving it to the connection's EXIT.
            if resume:
                m.resume()
        except Exception as exc:
            self.degraded = True
            self.log.emit("trap_failed", error=repr(exc), hits=self.hits)
            if resume:
                # The machine may be halted at the stop; the caller's body
                # goes on, and a dead monitor cannot be told anything.
                try:
                    m.resume()
                except Exception:
                    pass
            self.log.say(f"  the monitor stopped answering: {exc!r}; the "
                         f"store checkpoint stays armed until the run ends, "
                         f"and the trap makes no further reads")
        finally:
            self._busy = False

    def capture(self, m) -> None:
        m.checkpoint_set(LINE_DRAWN, exec_=True, stop=True, temporary=True)
        m.resume()
        pc = m.wait_stopped(self.wait)
        if pc is None:
            raise TimeoutError(f"no stop at ${LINE_DRAWN:04X}")
        if pc != LINE_DRAWN:
            # Some other stop (the store checkpoint again, say): the line has
            # not been drawn, so reading the screen would prove nothing.
            self.log.emit("wrong_stop", pc=pc, want=LINE_DRAWN,
                          result=self.result)
            self.log.say(f"  stopped at ${pc:04X}, not ${LINE_DRAWN:04X}; "
                         f"the screen was not read")
            return
        rows = rows_of(read_screen(m))
        (self.out / "ran-line.txt").write_text("\n".join(rows) + "\n")
        self.seen = any("RUNS AWAY" in r for r in rows)
        self.log.emit("outcome_line", pc=pc, result=self.result,
                      seen=self.seen, rows=rows)
        self.log.say(f"  stopped at ${pc:04X}; the line is "
                     f"{'on' if self.seen else 'NOT on'} the screen")
        # The X grab is taken while the machine is stopped, so it can show a
        # frozen frame buffer that VICE has not repainted; `ran-line.txt`,
        # read from screen memory, is the evidence.
        shot = self.out / "outcome-line.png"
        try:
            taken = self.sess.kbd.screenshot(str(shot), timeout=10)
        except Exception as exc:
            taken = False
            self.log.emit("shot_failed", error=repr(exc))
        if not taken:
            self.log.emit("shot_failed", error="no screenshot taken")
        self.log.say("  outcome-line.png was grabbed with the machine "
                     "stopped and may show a frozen frame")

    def finish(self) -> None:
        """Say what the checkpoint proved, then clear every checkpoint."""
        if self._mon is None:
            return
        self.sess.mon = self._mon
        try:
            with self._mon(10) as m:
                if self.cp is not None and not self.degraded:
                    try:
                        self.hits = max(self.hits, m.checkpoint_hits(self.cp))
                    except Exception as exc:
                        self.log.emit("hits_failed", error=repr(exc))
                m.checkpoints_clear()
                m.resume()
        except Exception as exc:
            self.log.emit("disarm_failed", error=repr(exc))
        if self.hits and self.result == RAN_AWAY and not self.seen:
            self.log.emit("line_printed_not_seen", hits=self.hits)
            self.log.say(f"  ${RESULT:04X} was written {self.hits} time(s) "
                         f"with $81: the line was printed, not seen")


def read_outcome(sess) -> dict:
    """`RESULT`, `MERCY` and the six status bytes, after the fight."""
    with sess.mon(5) as m:
        return {"result": m.peek(RESULT), "mercy": m.peek(MERCY),
                "status": party_status(m)}


def run(args) -> int:
    out = scratch.ensure(args.out)
    log = Log(out, args.quiet)
    flight = Flight(log)
    slot = S.claim_slot(args.slot, "curseflee/445")
    log.say(f"slot {slot.n} display {slot.display}  out {out}")
    battle = laterbattle.Battle(out, args.quiet)
    battle.slot = slot
    rc, sess, trap = 0, None, None
    try:
        fight_rc = laterbattle.curse_fight(battle, args, args.disks)
        battle.log("curse_fight", rc=fight_rc)
        if fight_rc:
            raise RuntimeError(f"curse_fight failed (rc={fight_rc})")
        sess = battle.sess
        log.say("reached the tavern script")

        # `laterbattle.main`'s own wait for the combat arena: `curse_fight`
        # only presses the script's word, and `YOU GET INTO A BRAWL.` draws
        # over a picture and waits on a keypress before the arena appears.
        for n in range(args.wait):
            if battle.in_combat():
                break
            s = sess.screen()
            state = sess.combat_state(s)
            battle.log("waiting-for-combat", look=n, mode=sess.mode(),
                       readable=s is not None, bar=state.kind,
                       row24=state.text.strip())
            if state.kind == S.BAR_PRESS or s is None:
                sess.press_kernal(0x0D)
            sess.settle(4.0)
        battle.dump("combat-arena")
        if not battle.in_combat():
            raise RuntimeError("never reached the combat arena")
        log.say("on the combat arena")

        b = sess.battle()
        if b is not None:
            log.say(f"  the map is {b.geometry.width} x {b.geometry.height}")
            for c in b.party:
                log.say(f"    {c.name.strip():<12} at {c.x},{c.y}  "
                        f"move {c.movement}")
        else:
            log.say("  battle() returned None at combat start")

        trap = Trap(sess, log, out)
        trap.arm()
        result = sess.fight(args.budget, tactic=flight, poll=args.poll)
        log.say(f"fight ended: outcome={result.outcome!r} turns={result.turns}"
                f" seconds={result.seconds:.1f}")
        log.emit("fight_result", outcome=result.outcome, turns=result.turns,
                  seconds=result.seconds, bars=result.bars,
                  lines=result.lines)
        try:
            sess.kbd.screenshot(str(out / "outcome.png"))
        except Exception as exc:
            log.emit("shot_failed", error=repr(exc))
        s = sess.screen()
        if s is not None:
            (out / "final-screen.txt").write_text(
                "\n".join(rows_of(s)) + "\n")
        try:
            after = read_outcome(sess)
        except Exception as exc:
            after = None
            log.emit("outcome_failed", error=repr(exc))
            log.say(f"  the outcome read failed: {exc!r}")
        if after is not None:
            log.emit("outcome_bytes", **after)
            log.say(f"  ${RESULT:04X}=${after['result']:02X} "
                    f"${MERCY:04X}=${after['mercy']:02X} "
                    f"party status {after['status']}")
        # The status byte, read at the write of the result when the trap saw
        # it: afterwards the drop loop has put `$86` back to `$01`.
        counted = (trap.status_at_write if trap.status_at_write is not None
                   else after["status"] if after is not None else [])
        log.emit("flee", attempts=flight.attempts,
                  got_away=flight.got_away, failed=dict(flight.failed),
                  escaped=escaped(counted),
                  escaped_from="write" if trap.status_at_write is not None
                  else "after" if after is not None else "none")
        log.say(f"  flee attempts {flight.attempts}, escaped "
                f"{escaped(counted)} by status byte (Flight logged "
                f"{sum(flight.got_away.values())}), failed "
                f"{dict(flight.failed)}")
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
        if trap is not None:
            trap.finish()
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


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--disks", default=os.environ.get("POR_DISKS") or None)
    p.add_argument("--save", required=True,
                   help="a Curse save disk (SIDE0) to copy in")
    p.add_argument("--slot", type=int, default=None)
    p.add_argument("--budget", type=float, default=900.0)
    p.add_argument("--poll", type=float, default=0.12,
                   help="Session.fight's poll interval; the flee line is up "
                        "for under half a second (tools/c64/session.py's "
                        "comment above RAN_TEXT), which fight's own 1.0s "
                        "default misses")
    p.add_argument("--steps", type=int, default=60,
                   help="goto budget for the walk to the tavern")
    p.add_argument("--world", type=float, default=240.0,
                   help="seconds to give BEGIN ADVENTURING to reach the world")
    p.add_argument("--look", type=float, default=8.0,
                   help="seconds between readings while waiting for the world")
    p.add_argument("--wait", type=int, default=15,
                   help="settles to give the combat screen to draw")
    p.add_argument("--accept", action="store_true",
                   help="take the YES half of a script's own YES/NO bar "
                        "instead of declining it, for a walker that is "
                        "trying to reach a fight (#334)")
    p.add_argument("--out", default=str(scratch.scratch_dir("curseflee", "run")))
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)
    if args.disks is None:
        from automap import gamedisks
        found = gamedisks.find("curse-of-the-azure-bonds")
        if not found:
            print("no Curse disks found; pass --disks")
            return 2
        args.disks = str(found)
    from tools.c64 import runlog
    runlog.catch_signals()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
