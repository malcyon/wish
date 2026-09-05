#!/usr/bin/env python3
"""Read the combat command bar a C64 cleric is offered, in the running game.

`#288 (A converted cleric or paladin arrives on the C64 unable to turn undead,
because DOS keeps no turning byte and nothing computes one)`. `COMBAT $09CF`
builds the bar's mask from `$FF` and then clears one bit per command the
character may not take:

    $09D9  LDA $6BA4            turn_power
    $09DC  BNE $09E3            non-zero: leave TURN alone
    $09DE  LDA #$DF             zero: clear bit 5
    $09E0  JSR $133D            AND $48F8 / STA $48F8

`$0A24` hands that mask to the bar builder with the eight-word table at
`$1344` -- `MOVE VIEW AIM USE CAST TURN QUICK DONE` -- so bit 5 is the word
TURN, and a character holding zero at record `0x0A4` **is not offered the
command at all**. That is what a converted cleric holds, and this is the tool
that watches it happen rather than arguing it from the bytes.

    tools/turndrive.py --stage 2=0                 the bug: ROLAND cannot turn
    tools/turndrive.py                             the control: he can

One save, one byte, two runs. It stages `turn_power` into a **copy** of a save
disk, boots a pool slot, walks the party into the Slums ambush, and at every
command bar reads two things in one monitor stop: the acting character's name
and turning byte out of the working record at `$6B00`, and row 24 verbatim. So
each line of the log pairs the byte the engine read with the bar it drew, and
no reading depends on knowing whose turn it was from the outside.

Output goes to `--out` as `turn.jsonl` plus a PNG of every distinct bar.
Nothing is written to the player's disks: the sides and the save are staged
into the pool instance's own directory first.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap.paths import find_disks  # noqa: E402
from goldbox import savegame  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.layout import FIELDS_BY_NAME  # noqa: E402
from tools import session as S  # noqa: E402

DISKS = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")

#: The working character record while `COMBAT` runs, and the byte in it this
#: whole run is about. `tools/trainerscan.py` carries the same constant.
RECORD = 0x6B00
NAME_LENGTH = 20
TURN_POWER = FIELDS_BY_NAME["turn_power"].offset          # 0x0A4

#: Which word of the bar the byte gates.
TURN_WORD = "TURN"


def _name(raw: bytes) -> str:
    return raw.split(b"\x00")[0].decode("latin1", "replace").strip()


def acting(sess) -> dict:
    """Who the engine has in the working record, and what it holds at 0x0A4.

    One stop, two reads: a bar redrawn between two monitor connections would
    pair one character's name with another's byte.
    """
    with sess.mon(5) as m:
        head = m.read(RECORD, NAME_LENGTH)
        byte = m.read(RECORD + TURN_POWER, 1)
    return {"name": _name(head), "turn_power": byte[0]}


def stage(path: pathlib.Path, wanted: dict[int, int]) -> list[tuple[str, int]]:
    """Put `slot: value` into record `0x0A4` of a copy of a save disk.

    Writing the byte rather than making the game write it is the point: what
    it proves is what the engine does when it **reads** one, which is the half
    a converted save exercises.
    """
    disk = D64.open(str(path))
    game, sg0, sg1 = savegame.load_save(disk)
    written: list[tuple[str, int]] = []
    for index, value in sorted(wanted.items()):
        slot = sg0.slot(index)
        record = slot.record
        if record is None:
            raise SystemExit(f"save slot {index} is empty")
        record.set("turn_power", value)
        sg0.write_record(index, record)
        written.append((str(record.name), value))
    savegame.store_save(disk, sg0, sg1, game)
    disk.save(str(path))
    return written


def parse_stage(text: str) -> dict[int, int]:
    """`2=0,4=9` -- which save slot gets which turning byte."""
    out: dict[int, int] = {}
    for item in text.split(","):
        slot, _, value = item.partition("=")
        if not value:
            raise SystemExit("--stage wants slot=value pairs, e.g. 2=0")
        out[int(slot, 0)] = int(value, 0)
    return out


class Log:
    def __init__(self, out: pathlib.Path, quiet: bool = False):
        out.mkdir(parents=True, exist_ok=True)
        self.dir = out
        self.file = open(out / "turn.jsonl", "w")
        self.quiet = quiet
        self.bars: list[dict] = []

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


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--save", default="PORSAVE13.D64",
                   help="the save disk to load, inside --disks")
    p.add_argument("--stage", default=None, metavar="SLOT=VALUE,...",
                   help="write these turning bytes into a copy of the save "
                        "before booting")
    p.add_argument("--disks", default=str(DISKS),
                   help="where the player's disks are; read, never written")
    p.add_argument("--slot", type=int, default=None,
                   help="demand this pool slot rather than the first free one")
    p.add_argument("--walk", default="I",
                   help="the move to repeat while looking for a fight")
    p.add_argument("--steps", type=int, default=60,
                   help="give up after this many steps with no fight")
    p.add_argument("--turns", type=int, default=12,
                   help="how many command bars to read before stopping")
    p.add_argument("--budget", type=float, default=600.0,
                   help="seconds to give the fight")
    p.add_argument("--out", default=None, help="run directory")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    disks = pathlib.Path(args.disks)
    out = pathlib.Path(args.out) if args.out else (
        ROOT / "work" / "issue288" / "run")
    log = Log(out, args.quiet)

    save = args.save
    if args.stage:
        staging = out / "disks"
        staging.mkdir(parents=True, exist_ok=True)
        for i in range(1, 9):
            src, link = disks / f"POOL{i}.D64", staging / f"POOL{i}.D64"
            if src.exists() and not link.exists():
                link.symlink_to(src.resolve())
        shutil.copy(disks / args.save, staging / "STAGED.D64")
        save, disks = "STAGED.D64", staging
        written = stage(staging / save, parse_stage(args.stage))
        log.emit("staged", values=written)
        log.say("staged 0x0A4: "
                + ", ".join(f"{n} = {v}" for n, v in written))

    slot = S.claim_slot(args.slot, f"turndrive/{save}")
    log.say(f"slot {slot.n} display {slot.display}  out {out}")
    rc, sess, seen = 0, None, {}
    try:
        sess = S.Session(S.stage_disks(slot, disks, save), slot=slot)
        if not sess.boot():
            raise RuntimeError("boot failed")
        if not sess.load_save():
            raise RuntimeError("load_save failed")
        if not sess.begin_adventuring():
            raise RuntimeError("begin_adventuring failed")
        sess.settle(3)
        log.say(f"in the world at {sess.position()}")

        steps = 0
        while not sess.in_combat():
            if steps > args.steps:
                raise RuntimeError("route exhausted with no fight")
            sess.walk_one(args.walk)
            sess.handle_prompt()
            steps += 1
        log.emit("fight_start", steps=steps)
        log.say(f"ambushed after {steps} steps")
        sess.settle(2)

        turns = {"n": 0}

        def tactic(s, state):
            """Read the bar and who it belongs to, then pass the turn.

            The tactic is `melee_turn`'s, unchanged -- what this adds is the
            reading before it, because a fight that is fought differently is
            not the same measurement.
            """
            turns["n"] += 1
            who = acting(s)
            bar = state.text
            has_turn = TURN_WORD in bar.upper().split()
            row = {"turn": turns["n"], "bar": bar, "turn_offered": has_turn,
                   **who}
            log.emit("bar", **row)
            log.bars.append(row)
            log.say(f"  turn {turns['n']:2d}  {who['name']:<16} "
                    f"0x0A4={who['turn_power']:<3} "
                    f"{'TURN' if has_turn else 'no TURN':<8} |{bar}|")
            key = (who["name"], who["turn_power"], has_turn)
            if key not in seen:
                seen[key] = True
                try:
                    s.kbd.screenshot(str(
                        out / f"bar-{len(seen)}-{who['name'] or 'anon'}"
                              f"-{who['turn_power']}.png"))
                except Exception:
                    pass
            if turns["n"] >= args.turns:
                raise RuntimeError("read enough bars")
            return s.melee_turn(state)

        try:
            r = sess.fight(budget=args.budget, tactic=tactic)
            log.emit("fight_end", outcome=r.outcome, turns=r.turns,
                     bars=r.bars)
        except Exception as exc:
            log.emit("fight_stopped", why=repr(exc))

        offered = {row["name"]: (row["turn_power"], row["turn_offered"])
                   for row in log.bars}
        log.emit("summary", offered=offered)
        log.say("")
        for name, (byte, has) in sorted(offered.items()):
            log.say(f"{name:<16} 0x0A4 = {byte:<3} "
                    f"TURN on the bar: {'yes' if has else 'NO'}")
    except Exception as exc:
        import traceback
        try:
            s = sess and sess.screen()
            screen = [ln.rstrip() for ln in s.rows()] if s else []
        except Exception:
            screen = []
        log.emit("failed", error=repr(exc), screen=screen)
        log.say(f"failed: {exc!r}")
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


if __name__ == "__main__":
    raise SystemExit(main())
