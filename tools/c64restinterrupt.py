#!/usr/bin/env python3
"""What decides whether a C64 rest is interrupted, read from the code and driven.

`#250 (Does a C64 party resting in the Slums ever get interrupted without the
murder flag?)`. The rest loop lives in the `CAMP` overlay, one tick per five
minutes of game time, and its interruption check is gated on a single byte:

    $1E0F  AD D2 6D   LDA $6DD2      ; ticks between checks
    $1E12  F0 20      BEQ $1E34      ; zero: never check at all
    $1E14  CE DC 28   DEC $28DC      ; passes since the last check
    $1E17  D0 1B      BNE $1E34
    $1E19  8D DC 28   STA $28DC
    $1E1C  A0 64      LDY #$64       ; d100
    $1E1E  20 E0 2D   JSR $2DE0
    $1E21  CA         DEX
    $1E22  EC D3 6D   CPX $6DD3      ; roll-1 < chance: interrupted
    $1E25  B0 0D      BCS $1E34

`$6DD2` is zeroed by `DUNGEON $10A6` on every ENCAMP, immediately before
`DUNGEON $19F5` runs the area script's entry 2 -- so the script is the only
thing that can make it non-zero, and each area's entry 2 decides whether a
rest there can be interrupted at all.

    tools/c64restinterrupt.py code                the static reading
    tools/c64restinterrupt.py drive --rests 12    the measurement

`code` needs no emulator: it re-derives the gate out of `CAMP` and `DUNGEON`
on the player's own disks, then walks every area script's entry 2 with
`tools/eclwalk.py` -- **from entry 2**, so a conditional pair is reported as
the values each arm reaches rather than whichever came first in address order.
It also walks both arms of every conditional through the statements that leave
no trace (`COMPARE`, `IF`, `GOTO`) and says which arrive at the same single
statement, which is how the Slums' two dead tests are told from the other
twenty-nine scripts' live ones.

`drive` claims a pool slot, boots a save made in the area, and counts three
things with non-stopping VICE checkpoints while the party rests: passes
(`$1E0F`), checks made (`$1E1C`) and interruptions taken (`$1E27`), with the
game's own clock at `$49C6`-`$49CB` read either side of every rest as a second
witness to the pass count. It rests in two-hour blocks, which is exactly one
check's worth when the pair is (24, 24), so the count of checks is the count of
rests. Three camp sessions, `--phases`: the flag clear, the flag set with the
chance held at zero so the checks can be counted without the first
interruption ending the session, and the flag set with the chance the script
wrote. Nothing is written to the player's disks: the sides and the save are
staged into the slot.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import struct
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap.paths import find_disks  # noqa: E402
from automap.vice import CMD_CHECKPOINT_GET  # noqa: E402

DISKS = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")

#: The rest loop's own addresses in `CAMP`, which `LINKER` loads at $0800.
TICK = 0x1E0F           # LDA $6DD2 -- once per five minutes of game time
CHECK = 0x1E1C          # LDY #$64  -- the d100 is about to be rolled
INTERRUPT = 0x1E27      # LDA #$FF  -- the roll won; the rest ends

#: The five bytes `TICK` must hold before a checkpoint there means anything.
#: `DUNGEON` also runs at $0800, so an address alone does not say which
#: overlay is resident.
TICK_BYTES = bytes((0xAD, 0xD2, 0x6D, 0xF0, 0x20))

#: `DUNGEON`'s ENCAMP handler: zero the pair, then run script entry 2.
ENCAMP_HANDLER = 0x10A1
ENCAMP_BYTES = bytes((0xA9, 0x01, 0x8D, 0xAB, 0x6D,     # STA $6DAB
                      0xA9, 0x00, 0x8D, 0xD2, 0x6D,     # STA $6DD2
                      0x8D, 0xD3, 0x6D,                 # STA $6DD3
                      0x20, 0xF5, 0x19))                # JSR $19F5 (entry 2)

#: The rest-interruption interval and chance, live.
INTERVAL = 0x6DD2
CHANCE = 0x6DD3

#: The Slums' murder penalty, in the area scratch page `DUNGEON $202A` zeroes.
MURDER = 0x4A0B

#: The game clock: sub-minute, minute units, minute tens, hour, day, month
#: (`docs/141-dos-savegame.md`, `$49C6`-`$49CB`, "exactly the C64's six
#: bytes"). Read either side of a rest, it counts the five-minute passes
#: independently of the checkpoint that counts them.
CLOCK = 0x49C6

#: `CAMP`'s rest-time field: minutes in steps of five, hours, days.
REST_MINS, REST_HRS, REST_DAYS = 0x2898, 0x2899, 0x289A

#: Where the resident area script is, and the entry-2 vector inside it.
SCRIPT = 0x9900
ENTRY2_VECTOR = 0x9908

#: The three camp sessions `drive` runs, and what each one stages.
#: `flag-set-no-win` holds the chance at zero so `$1E22`'s compare can never
#: succeed, which is what lets the checks be counted without the first
#: interruption ending the session.
PHASES = {
    "flag-clear": {"murder": 0, "chance": None},
    "flag-set-no-win": {"murder": 255, "chance": 0},
    "flag-set": {"murder": 255, "chance": None},
}


# -- the static reading -----------------------------------------------------


def overlay_bytes(name: str, root: str, base: int = 0x0800) -> tuple[int, bytes]:
    """A named overlay's run-time base and payload, off whichever side has it."""
    from tools import overlay as O

    declared, payload = O.load(name, root)
    return (base if base is not None else declared), payload


def at(payload: bytes, base: int, addr: int, length: int) -> bytes:
    off = addr - base
    return payload[off:off + length]


def read_gate(root: str) -> dict:
    """The three facts the answer rests on, checked against the disks."""
    base, camp = overlay_bytes("CAMP", root)
    _, dungeon = overlay_bytes("DUNGEON", root)
    return {
        "camp_gate": at(camp, base, TICK, 5).hex(" "),
        "camp_gate_expected": TICK_BYTES.hex(" "),
        "camp_gate_ok": at(camp, base, TICK, 5) == TICK_BYTES,
        "encamp_handler": at(dungeon, base, ENCAMP_HANDLER, 16).hex(" "),
        "encamp_handler_expected": ENCAMP_BYTES.hex(" "),
        "encamp_handler_ok": at(dungeon, base, ENCAMP_HANDLER,
                                len(ENCAMP_BYTES)) == ENCAMP_BYTES,
    }


def _script(name: str, root: str):
    """One walked area script, off whichever side carries it."""
    import pathlib as _p

    from tools import eclwalk

    eclwalk.DISKS = _p.Path(root)
    found = eclwalk.scripts()
    if name not in found:
        raise SystemExit(f"no script {name} on any side under {root}")
    side, body = found[name]
    return eclwalk.Script(eclwalk.Machine(), name, side, body), body


def entry2_statements(script) -> list:
    """Only the statements entry 2 can reach, in address order.

    A walk and not a sweep, and started at entry 2 rather than at the head of
    the file: the pair is written in two places in the Slums' script and which
    one runs is the whole question, so a listing that reports whichever came
    first in address order answers nothing.
    """
    start = script.entries[2]
    if start is None:
        return []
    seen, work = set(), [start]
    while work:
        i = work.pop()
        if i in seen or i not in script.statements:
            continue
        seen.add(i)
        for successor, _ in script._successors(script.statements[i]):
            work.append(successor)
    return [script.statements[i] for i in sorted(seen)]


def entry2_writes(name: str, root: str) -> list[dict]:
    """Every `SAVE n, [$6DD2]` and `SAVE n, [$6DD3]` an area's entry 2 makes."""
    script, _ = _script(name, root)
    out = []
    for st in entry2_statements(script):
        text = str(st)
        if "$6DD2" in text or "$6DD3" in text or "$4A0B" in text:
            out.append({"at": st.address, "text": text})
    return out


# -- the measurement --------------------------------------------------------


class Counter:
    """A non-stopping VICE checkpoint, read back by its hit count.

    `automap.vice.Monitor` sets checkpoints and lists their numbers; it does
    not read the count, which is bytes 13-16 of the checkpoint response. A
    stopping breakpoint would answer the same question and would have to be
    resumed on every tick of a 288-tick rest, so the count is the instrument
    and the machine is never stopped by it.
    """

    def __init__(self, mon, addr: int, name: str):
        self.addr, self.name = addr, name
        self.number = mon.checkpoint_set(addr, exec_=True, stop=False)

    def raw(self, mon) -> str:
        """The whole checkpoint response, hex, so the offsets are on record."""
        return mon.command(CMD_CHECKPOINT_GET,
                           struct.pack("<I", self.number)).hex(" ")

    def read(self, mon) -> int:
        body = mon.command(CMD_CHECKPOINT_GET, struct.pack("<I", self.number))
        if len(body) < 17:
            raise RuntimeError(
                f"checkpoint response is {len(body)} bytes, too short to "
                f"carry a hit count: {body.hex(' ')}")
        number, _, start = struct.unpack("<IBH", body[:7])
        if number != self.number or start != self.addr:
            raise RuntimeError(
                f"checkpoint {self.number} answered for ${start:04X}, "
                f"not ${self.addr:04X}")
        return struct.unpack("<I", body[13:17])[0]

    def delete(self, mon) -> None:
        mon.checkpoint_delete(self.number)


def camp_is_resident(sess) -> bool:
    """Whether the bytes at the gate are `CAMP`'s and not another overlay's."""
    with sess.mon(5) as m:
        return m.read(TICK, len(TICK_BYTES)) == TICK_BYTES


def read_pair(sess) -> tuple[int, int]:
    with sess.mon(5) as m:
        return tuple(m.read(INTERVAL, 2))


def clock_minutes(raw: bytes) -> int:
    """The clock's six digit bytes as one running count of minutes."""
    _, units, tens, hour, day, month = raw
    return units + 10 * tens + 60 * hour + 1440 * day + 43200 * month


def script_matches(sess, name: str, root: str) -> dict:
    """Whether the resident script is the one this run claims to be in.

    Entry 2 is what decides the pair, so entry 2 is what is compared -- 64
    bytes of it, live against the file on the disk. A screenshot of a corridor
    says nothing about which script the engine loaded.
    """
    _, body = _script(name, root)
    with sess.mon(5) as m:
        head = m.read(ENTRY2_VECTOR, 4)
        target = struct.unpack("<H", head[2:4])[0]
        block = m.read(target, 64) if SCRIPT <= target < SCRIPT + len(body) - 64 \
            else b""
    want = body[target - SCRIPT:target - SCRIPT + 64] if block else b""
    return {"entry2": target, "matches": bool(block) and block == want}


class Log:
    def __init__(self, out: pathlib.Path, quiet: bool = False):
        out.mkdir(parents=True, exist_ok=True)
        self.dir = out
        self.file = open(out / "rest.jsonl", "w")
        self.quiet = quiet
        self.trials: list[dict] = []

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


def open_camp(sess, log: Log) -> bool:
    """`ENCAMP` from the world bar, waited for by the camp bar's own words."""
    if not sess.select_bar("ENCAMP"):
        log.say("  ENCAMP was not on the world bar")
        return False
    return sess.wait_text("MAGIC", timeout=60)[0] is not None


def leave_camp(sess) -> bool:
    return sess.select_bar("EXIT")


def reach_world(sess, log: Log, seconds: float = 600.0) -> bool:
    """`BEGIN ADVENTURING`, then answer whatever stands between it and the bar.

    `Session.begin_adventuring` gives up after 240 seconds with the screen
    still saying `OUTWARD BOUND ...`, and the screen is the only record of
    why -- so this logs every distinct screen it sees while it waits. A save
    loaded into a scene can also ask `YES NO`, which `wait_for_world` does not
    answer (`tools/savecheck.py`'s `answer_bars`).
    """
    if not sess.select_row("BEGIN ADVENTURING"):
        log.say("  BEGIN ADVENTURING was not on the menu")
        return False
    deadline, last = time.time() + seconds, None
    while time.time() < deadline:
        s = sess.screen()
        if s is None:
            time.sleep(1.0)
            continue
        if sess.handle_prompt(s):
            continue
        row = s.row(24)
        if "MOVE" in row and "ENCAMP" in row:
            return True
        shown = [ln.strip() for ln in s.rows() if ln.strip(" $@[")]
        if shown != last:
            last = shown
            log.emit("arriving", screen=shown)
            log.say("  arriving: " + " | ".join(shown[-3:])[:110])
        if "PRESS" in row:
            sess.kbd.key("Return")
        elif "YES" in row and "NO" in row:
            sess.select_bar("NO", timeout=8)
        time.sleep(1.2)
    return False


def one_rest(sess, log: Log, hours: int, counters: dict,
             still_for: int = 10) -> dict | None:
    """One `REST` of *hours* hours, with the three counters read either side.

    The duration is written into `CAMP`'s own rest-time field rather than
    driven with `INCREASE`, because the default is whatever the party has left
    to memorise and INCREASE's step grows while the key is held. The field is
    an input the engine then counts down five minutes at a time; nothing about
    the interruption check is touched by writing it.
    """
    if not sess.select_bar("REST"):
        log.say("  REST was not on the camp bar")
        return None
    if sess.wait_text("INCREASE", timeout=30)[0] is None:
        log.say("  the rest-time bar never appeared")
        return None
    with sess.mon(5) as m:
        before = {n: c.read(m) for n, c in counters.items()}
        clock_before = m.read(CLOCK, 6)
        m.write(REST_MINS, bytes((0, hours, 0)))
        staged = tuple(m.read(REST_MINS, 3))
    if staged != (0, hours, 0):
        log.say(f"  the rest time read back {staged}, not (0, {hours}, 0)")
        return None
    if not sess.select_bar("REST"):
        log.say("  REST was not on the rest-time bar")
        return None
    # The rest is over when the tick counter stops moving. The screen is not
    # the signal: the camp bar is still drawn under the clock while the party
    # rests, so a poll for one of its words answers before the first tick.
    # **No key is sent while the loop runs** -- `$1E44` reads the keyboard on
    # every tick and SPACE there ends the rest early.
    #
    # `still_for` is ten seconds and not four because of the pass on which the
    # clock turns a day: `CAMP $1E09` calls `$1FB6`, which ends in `$0F96` --
    # `LDA $49FC / JSR $2E1F`, a wait the length of the game-speed setting --
    # before the pass reaches `$1E0F`. At four seconds that pause read as the
    # end of the rest, and the twelfth two-hour rest of every run came back
    # one pass short.
    deadline, still, last = time.time() + 300, 0, None
    while time.time() < deadline and still < still_for:
        time.sleep(1.0)
        with sess.mon(5) as m:
            now = counters["tick"].read(m)
        still = still + 1 if now == last else 0
        last = now
    with sess.mon(5) as m:
        after = {n: c.read(m) for n, c in counters.items()}
        pair = tuple(m.read(INTERVAL, 2))
        clock_after = m.read(CLOCK, 6)
    s = sess.screen()
    text = " ".join(s.rows()).upper() if s else ""
    return {
        "ticks": after["tick"] - before["tick"],
        "checks": after["check"] - before["check"],
        "interruptions": after["interrupt"] - before["interrupt"],
        "minutes": clock_minutes(clock_after) - clock_minutes(clock_before),
        "clock": [clock_before.hex(" "), clock_after.hex(" ")],
        "pair_after": pair,
        "interrupted_text": "RUDELY INTERRUPTED" in text,
    }


def phase(sess, log: Log, name: str, rests: int, hours: int,
          murder: int | None, chance: int | None,
          still_for: int = 10) -> list[dict]:
    """One camp session: set the flag, ENCAMP, then rest *rests* times."""
    log.say(f"\n{name}")
    if murder is not None:
        with sess.mon(5) as m:
            m.write(MURDER, bytes((murder,)))
    with sess.mon(5) as m:
        flag = m.peek(MURDER)
    log.say(f"  $4A0B = {flag}")
    if not open_camp(sess, log):
        raise RuntimeError(f"{name}: could not open the camp menu")
    pair = read_pair(sess)
    log.say(f"  entry 2 wrote $6DD2/$6DD3 = {pair[0]}, {pair[1]}")
    log.emit("camp", phase=name, murder=flag, pair=pair)
    if not camp_is_resident(sess):
        raise RuntimeError(f"{name}: CAMP is not the resident overlay")
    if chance is not None:
        with sess.mon(5) as m:
            m.write(CHANCE, bytes((chance,)))
        log.say(f"  $6DD3 held at {chance} so a check can never win")
    counters = {}
    with sess.mon(5) as m:
        counters["tick"] = Counter(m, TICK, "tick")
        counters["check"] = Counter(m, CHECK, "check")
        counters["interrupt"] = Counter(m, INTERRUPT, "interrupt")
        log.emit("checkpoints", phase=name,
                 raw={n: c.raw(m) for n, c in counters.items()})
    rows = []
    try:
        for n in range(1, rests + 1):
            row = one_rest(sess, log, hours, counters, still_for)
            if row is None:
                break
            row.update(trial=n, phase=name, murder=flag, pair=pair)
            rows.append(row)
            log.emit("rest", **row)
            log.say(f"  rest {n:2d}  passes {row['ticks']:4d}  "
                    f"clock +{row['minutes']:4d} min  "
                    f"checks {row['checks']}  "
                    f"interruptions {row['interruptions']}  "
                    f"pair now {row['pair_after']}")
            if row["interruptions"] or row["interrupted_text"]:
                try:
                    sess.kbd.screenshot(str(log.dir / f"{name}-interrupted.png"))
                except Exception:
                    pass
                log.say("  the rest was interrupted; the camp session is over")
                break
    finally:
        try:
            with sess.mon(5) as m:
                for c in counters.values():
                    c.delete(m)
        except Exception:
            pass
    return rows


def drive(args) -> int:
    from tools import session as S

    out = pathlib.Path(args.out) if args.out else ROOT / "work" / "issue250" / "run"
    log = Log(out, args.quiet)
    slot = S.claim_slot(args.slot, f"c64restinterrupt/{args.save}")
    log.say(f"slot {slot.n} display {slot.display}  out {out}")
    rc, sess = 0, None
    try:
        sess = S.Session(S.stage_disks(slot, pathlib.Path(args.disks), args.save),
                         slot=slot)
        if not sess.boot():
            raise RuntimeError("boot failed")
        if not sess.load_save():
            raise RuntimeError("load_save failed")
        if not reach_world(sess, log, args.arrive):
            raise RuntimeError("never reached the world bar")
        sess.settle(3)
        where = sess.position()
        log.say(f"in the world at {where}")
        ident = script_matches(sess, args.script, args.disks)
        log.emit("start", position=where, script=args.script, **ident)
        log.say(f"resident entry 2 at ${ident['entry2']:04X}; "
                f"matches {args.script}: {ident['matches']}")
        if not ident["matches"] and not args.any_script:
            raise RuntimeError(
                f"the resident script is not {args.script}; pass --any-script "
                f"to measure anyway")

        rows = []
        wanted = [w.strip() for w in args.phases.split(",") if w.strip()]
        for n, name in enumerate(wanted):
            if n:
                leave_camp(sess)
                sess.settle(4)
            rows += phase(sess, log, name, args.rests, args.hours,
                          still_for=args.still, **PHASES[name])

        log.emit("summary", trials=rows)
        log.say("")
        for name in wanted:
            got = [r for r in rows if r["phase"] == name]
            if not got:
                continue
            log.say(f"{name:<16} {len(got)} rests  "
                    f"pair {got[0]['pair']}  "
                    f"passes {sum(r['ticks'] for r in got)}  "
                    f"clock {sum(r['minutes'] for r in got)} min  "
                    f"checks {sum(r['checks'] for r in got)}  "
                    f"interruptions {sum(r['interruptions'] for r in got)}")
    except Exception as exc:
        import traceback
        try:
            s = sess and sess.screen()
            screen = [ln.rstrip() for ln in s.rows()] if s else []
        except Exception:
            screen = []
        log.emit("failed", error=repr(exc), screen=screen)
        log.say(f"failed: {exc!r}")
        for line in screen:
            log.say(f"  |{line}|")
        traceback.print_exc()
        rc = 1
    finally:
        log.close()
        try:
            if sess is not None:
                sess.terminate()
            else:
                slot.teardown()
        except Exception:
            pass
    return rc


def _reaches(script, start: int) -> set[int]:
    """Every value `$6DD2` can hold once the script has run on from *start*."""
    seen, work, values = set(), [start], set()
    while work:
        i = work.pop()
        if i in seen or i not in script.statements:
            continue
        seen.add(i)
        st = script.statements[i]
        if st.name == "SAVE" and st.operands[-1][1] == INTERVAL \
                and st.operands[0][0] == 0x00:
            values.add(st.operands[0][1])
        for successor, _ in script._successors(st):
            work.append(successor)
    return values


def _settles_at(script, start: int) -> frozenset[int]:
    """The first statements with an effect that *start* can reach.

    A `COMPARE`, an `IF` and a `GOTO` change nothing a later statement can
    read, so a walk through them says where a branch really goes. Everything
    else stops the walk and is reported as a destination.
    """
    from tools import eclwalk

    passthrough = {0x03, 0x01} | eclwalk.CONDITIONS   # COMPARE, GOTO, IF*
    seen, work, out = set(), [start], set()
    while work:
        i = work.pop()
        if i in seen:
            continue
        seen.add(i)
        st = script.statements.get(i)
        if st is None or st.op not in passthrough:
            out.add(i)
            continue
        for successor, _ in script._successors(st):
            work.append(successor)
    return frozenset(out)


def inert_tests(name: str, root: str) -> list[dict]:
    """Conditionals in entry 2 whose two arms arrive at the same place.

    A test whose outcomes cannot be told apart afterwards decides nothing, and
    that is what makes the Slums' block a defect rather than a design. Both
    arms are walked through `COMPARE`, `IF` and `GOTO` -- statements that leave
    no trace -- so a branch that jumps over another test to the same
    destination is caught as well as one that jumps to its own next statement.
    Reported for every area, so the Slums can be compared with the other
    twenty-one conditional ones rather than judged on its own.
    """
    from tools import eclwalk

    script, _ = _script(name, root)
    out = []
    for st in entry2_statements(script):
        if st.op not in eclwalk.CONDITIONS:
            continue
        arms = [succ for succ, _ in script._successors(st)]
        if len(arms) != 2:
            continue
        first, second = (_settles_at(script, a) for a in arms)
        if first != second:
            continue
        # Equal *sets* is not enough on its own: `ECL1C $B628` has both arms
        # reaching the same three statements and is a real branch, because
        # tests further down pick a different one on each arm. One shared
        # destination is the exact case -- there is nothing left to pick.
        out.append({
            "at": st.address, "text": str(st),
            "arrives": sorted(SCRIPT + i for i in first),
            "decides_nothing": len(first) == 1,
        })
    return out


def _intervals(name: str, root: str) -> tuple[set[int], list[dict]]:
    """Every value entry 2 can leave in `$6DD2`, and the statements around it."""
    script, _ = _script(name, root)
    values, lines = set(), []
    for st in entry2_statements(script):
        text = str(st)
        if "$6DD2" in text or "$6DD3" in text or "$4A0B" in text:
            lines.append({"at": st.address, "text": text})
        if st.name == "SAVE" and st.operands[-1][1] == INTERVAL \
                and st.operands[0][0] == 0x00:
            values.add(st.operands[0][1])
    return values, lines


def show_code(args) -> int:
    root = args.disks
    gate = read_gate(root)
    print("the gate, read off the disks")
    print(f"  CAMP    ${TICK:04X}  {gate['camp_gate']}   "
          f"{'as expected' if gate['camp_gate_ok'] else 'DIFFERENT'}")
    print(f"  DUNGEON ${ENCAMP_HANDLER:04X}  {gate['encamp_handler']}   "
          f"{'as expected' if gate['encamp_handler_ok'] else 'DIFFERENT'}")
    print()
    chosen = args.scripts
    if chosen == ["all"]:
        import pathlib as _p

        from tools import eclwalk
        eclwalk.DISKS = _p.Path(root)
        chosen = sorted(eclwalk.scripts())
    print("what each area script's entry 2 leaves in $6DD2, the ticks "
          "between checks")
    for script in chosen:
        try:
            values, lines = _intervals(script, root)
        except Exception as exc:
            print(f"  {script:<6} could not be walked: {exc}")
            continue
        shape = ("never checked" if values == {0}
                 else "always checked" if 0 not in values
                 else "conditional")
        dead = [x for x in inert_tests(script, root) if x["decides_nothing"]]
        note = (f"   -- {len(dead)} test(s) here decide nothing"
                if dead else "")
        print(f"  {script:<6} $6DD2 in "
              f"{{{', '.join(str(v) for v in sorted(values)) or '-'}}}"
              f"   {shape}{note}")
        for x in dead:
            print(f"           ${x['at']:04X}  {x['text']:<8s} both arms "
                  f"arrive at ${x['arrives'][0]:04X}")
        if args.verbose:
            for w in lines:
                print(f"           ${w['at']:04X}  {w['text']}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--disks", default=str(DISKS),
                   help="where the player's disks are; read, never written")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("code", help="the static reading; no emulator")
    c.add_argument("scripts", nargs="*", default=["ECL14"],
                   help="area scripts to walk, or `all` (default ECL14, "
                        "the Slums)")
    c.add_argument("--verbose", action="store_true",
                   help="print every statement entry 2 reaches that names "
                        "the pair or the murder flag")

    d = sub.add_parser("drive", help="drive a rest and count the checks")
    d.add_argument("--save", default="PORSAVE13.D64",
                   help="the save disk to load, inside --disks")
    d.add_argument("--script", default="ECL14",
                   help="which area script the save should be in")
    d.add_argument("--any-script", action="store_true",
                   help="measure even when the resident script is another one")
    d.add_argument("--slot", type=int, default=None,
                   help="demand this pool slot rather than the first free one")
    d.add_argument("--phases", default=",".join(PHASES),
                   help="which camp sessions to run, in order: "
                        + ", ".join(PHASES))
    d.add_argument("--still", type=int, default=10,
                   help="seconds the pass counter must sit still before a "
                        "rest counts as finished")
    d.add_argument("--rests", type=int, default=12,
                   help="how many rests per phase")
    d.add_argument("--arrive", type=float, default=600.0,
                   help="seconds to give BEGIN ADVENTURING")
    d.add_argument("--hours", type=int, default=2,
                   help="hours per rest; 2 is one check when the pair is 24")
    d.add_argument("--out", default=None, help="run directory")
    d.add_argument("--quiet", action="store_true")

    args = p.parse_args(argv)
    if args.cmd == "code":
        return show_code(args)
    return drive(args)


if __name__ == "__main__":
    raise SystemExit(main())
