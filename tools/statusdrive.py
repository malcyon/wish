#!/usr/bin/env python3
"""Knock a Pool of Radiance character down in the running game, and read the
status byte the engine wrote.

Record `0x100` -- roster `+0x00`, `$8300 + N*$20` in `SAVEDGAME1` -- reads 1 in
every occupied slot of every save anybody has looked at, so what it holds when
a character is *not* well has never been measured.  This drives the engine into
writing one:

  1. boot a pool slot, load the player's save, walk until something ambushes
     the party;
  2. **wound one character by hit points, and nothing else** -- roster `+0x19`
     is set to 1 through the monitor, so the byte at `+0x00` is written by the
     game's own damage code rather than by us;
  3. sample the whole roster page `$8300`-`$83FF` before the fight, on every
     turn, and after it;
  4. `ENCAMP > SAVE`, then read `SAVEDGAME1` back off the disk the game wrote,
     which is what says the status *persists* rather than only existing in RAM.

    tools/statusdrive.py --save PORSAVE13.D64 --slot 3 --victim 5
    tools/statusdrive.py --sheets --save-path work/p235c64/run1/saved.d64

`--sheets` is the other half of the same question and drives no fight: it loads
a save and reads every character's `VIEW` sheet, whose last line is the STATUS
word `LIBRARY $38BE` draws.  Run it on the disk the first mode wrote and the
byte and the word are measured on the same character.

`PORSAVE13.D64` three steps into the Slums is the one-ambush reproduction the
combat harness was built on: six characters, eight orcs, everybody in contact
on turn 1.  `--victim` is a save slot index, 0-7; the default is the last
occupied one, because the party's order is its marching order and the back rank
is the one a driven fight leaves standing still.

Everything goes to `--out`: `roster.jsonl` one sample per line, `sheet.txt` the
character sheet the game drew afterwards, and `saved.d64` the save it wrote.
Nothing here writes to the player's disks -- `stage_disks` copies the eight
sides and the save into the slot, and `Session.attach` refuses any path outside
it.  Written for `#235 (Two unattributed DOS byte ranges in the combat tail are
dropped converting to C64, and nobody knows what they hold)`.
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
sys.path.insert(0, str(TOOLS))

import session as S  # noqa: E402

from automap.paths import find_disks  # noqa: E402
from goldbox import savegame  # noqa: E402
from goldbox.d64 import D64, split_load_address  # noqa: E402

#: The player's disks: `$POR_DISKS`, then the search every other tool does.
DISKS = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")

#: `SAVEDGAME1`'s roster page, live.  Eight blocks of `$20`, one per save slot,
#: and `goldbox/savegame.py` names the fields inside one.
ROSTER = savegame.SAVE1_LOAD_ADDRESS          # $8300
ROSTER_BYTES = savegame.ROSTER_STRIDE * savegame.ROSTER_COUNT   # $100

#: Roster `+0x00`, the byte under test, and `+0x19`, the 16-bit hit points the
#: fight actually runs on.  Wounding is done here and nowhere else.
STATUS = 0x00
HP = savegame.ROSTER_HP_CURRENT               # 0x19


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


def wound(sess, index: int, to: int = 1) -> None:
    """Set one combatant's current hit points, and touch nothing else."""
    at = ROSTER + index * savegame.ROSTER_STRIDE + HP
    with sess.mon(5) as m:
        m.write(at, bytes([to & 0xFF, to >> 8]))


class Log:
    def __init__(self, out: pathlib.Path, quiet: bool = False):
        out.mkdir(parents=True, exist_ok=True)
        self.dir = out
        self.file = open(out / "roster.jsonl", "w")
        self.quiet = quiet
        self.samples: list[dict] = []

    def emit(self, kind: str, **kw) -> None:
        kw["kind"] = kind
        kw["t"] = round(time.time(), 3)
        self.file.write(json.dumps(kw, default=str) + "\n")
        self.file.flush()

    def say(self, *a) -> None:
        if not self.quiet:
            print(*a, flush=True)

    def sample(self, sess, when: str) -> list[int]:
        try:
            page = roster_page(sess)
        except Exception as exc:                       # a wedged monitor is
            self.emit("sample_failed", when=when, error=repr(exc))
            return []
        st, hp = statuses(page), hitpoints(page)
        self.emit("sample", when=when, status=st, hp=hp, page=page.hex())
        self.samples.append({"when": when, "status": st, "hp": hp})
        self.say(f"  {when:<18} status="
                 + " ".join(f"{v:02X}" for v in st)
                 + "  hp=" + " ".join(str(v) for v in hp))
        return st

    def close(self) -> None:
        self.file.close()


def stage_status(path: pathlib.Path,
                 wanted: dict[int, int]) -> list[tuple[int, int]]:
    """Put `slot: value` into record `0x100` of a copy of a save disk.

    This writes the byte rather than making the game write it, so what it can
    prove is what the engine does when it *reads* one -- which word the sheet
    draws for a value nobody has caught it writing.  The copy is the one under
    `--out`; the player's disks are never opened for writing.
    """
    image = D64.open(str(path))
    addr, body = split_load_address(image.read_file("SAVEDGAME1"))
    body = bytearray(body)
    written: list[tuple[int, int]] = []
    for i, value in sorted(wanted.items()):
        at = i * savegame.ROSTER_STRIDE
        body[at] = value & 0xFF
        written.append((i, body[at]))
    image.write_file_inplace("SAVEDGAME1",
                             addr.to_bytes(2, "little") + bytes(body))
    image.save(str(path))
    return written


def parse_stage(text: str) -> dict[int, int]:
    """`5=0x87,4=0x86` -- which slot gets which value."""
    out: dict[int, int] = {}
    for item in text.split(","):
        slot, _, value = item.partition("=")
        if not value:
            raise SystemExit("--stage wants slot=value pairs, e.g. 5=0x87")
        out[int(slot, 0)] = int(value, 0)
    return out


def read_saved(path: pathlib.Path) -> list[int] | None:
    """Roster `+0x00` for all eight slots of a `.d64` the game just wrote."""
    try:
        image = D64.open(str(path))
        _, body = split_load_address(image.read_file("SAVEDGAME1"))
    except Exception:
        return None
    return [body[i * savegame.ROSTER_STRIDE]
            for i in range(savegame.ROSTER_COUNT)]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--save", default="PORSAVE13.D64",
                   help="the save disk to load, inside --disks")
    p.add_argument("--save-path", default=None,
                   help="a save disk anywhere, rather than one inside --disks")
    p.add_argument("--sheets", action="store_true",
                   help="read every character's VIEW sheet and stop; no fight")
    p.add_argument("--stage", default=None, metavar="SLOT=VALUE,...",
                   help="write these bytes into record 0x100 of --save-path "
                        "before booting, and read the sheets back: what the "
                        "game draws for a value nobody has seen it write")
    p.add_argument("--disks", default=str(DISKS),
                   help="where the player's disks are; read, never written")
    p.add_argument("--slot", type=int, default=None,
                   help="demand this pool slot rather than the first free one")
    p.add_argument("--victim", type=int, default=None,
                   help="save slot 0-7 to wound (default: the last occupied)")
    p.add_argument("--hp", type=int, default=1,
                   help="hit points to leave the victim on (default 1)")
    p.add_argument("--budget", type=float, default=600.0,
                   help="seconds to give the fight")
    p.add_argument("--walk", default="I",
                   help="the move to repeat while looking for a fight")
    p.add_argument("--steps", type=int, default=400,
                   help="give up after this many steps with no fight")
    p.add_argument("--no-save", action="store_true",
                   help="skip ENCAMP > SAVE; sample RAM only")
    p.add_argument("--out", default=None,
                   help="run directory (default work/p235c64/<save>)")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    disks = pathlib.Path(args.disks)
    save = args.save
    out = pathlib.Path(args.out) if args.out else (
        ROOT / "work" / "p235c64" / pathlib.Path(args.save).stem)
    log = Log(out, args.quiet)
    if args.save_path:
        # `stage_disks` copies `disks/save` into the slot, so a save that is
        # not among the player's disks gets a directory of its own with the
        # eight sides linked rather than copied.  Nothing is written to the
        # player's directory either way.
        staging = out / "disks"
        staging.mkdir(parents=True, exist_ok=True)
        for i in range(1, 9):
            src, link = disks / f"POOL{i}.D64", staging / f"POOL{i}.D64"
            if src.exists() and not link.exists():
                link.symlink_to(src.resolve())
        save = "STAGED.D64"
        shutil.copy(args.save_path, staging / save)
        disks = staging
        if args.stage:
            written = stage_status(staging / save, parse_stage(args.stage))
            log.emit("staged", values=written)
            log.say("staged record 0x100: "
                    + ", ".join(f"slot {i} = ${v:02X}" for i, v in written))
    slot = S.claim_slot(args.slot, f"statusdrive/{save}")
    log.say(f"slot {slot.n} display {slot.display}  out {out}")
    rc, sess = 0, None
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
        before = log.sample(sess, "in the world")

        if args.sheets:
            # The sheet's last line inside the border is the STATUS word:
            # `LIBRARY $38BE` masks record 0x100 with 7 and indexes a
            # seven-name table with it, and `$38C7 LDA #$16` is the row.
            text = []
            for i in range(len([v for v in before if v])):
                lines = sess.character_sheet(i)
                log.emit("sheet", index=i, lines=lines)
                # The sheet is a box: rows drawn between two `$` columns, a
                # bottom border, then the bar.  The name is its first boxed
                # row and the status its last, so both are read by shape
                # rather than by counting rows a longer sheet would move.
                boxed = [ln.strip("$ ") for ln in (lines or [])
                         if ln.startswith("$") and ln.strip("$ ")]
                name = boxed[0] if boxed else "?"
                word = boxed[-1] if boxed else "?"
                log.say(f"  party {i}  {name:<16} STATUS {word}")
                text.append(f"--- party {i} ---\n"
                            + "\n".join(lines or ["(no sheet)"]))
            (out / "sheets.txt").write_text("\n".join(text) + "\n")
            log.say("sheets written to " + str(out / "sheets.txt"))
            return rc

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
        log.sample(sess, "fight begins")

        victim = args.victim
        if victim is None:
            occupied = [i for i, v in enumerate(before) if v]
            if not occupied:
                raise RuntimeError("no occupied roster slot to wound")
            victim = occupied[-1]
        wound(sess, victim, args.hp)
        log.emit("wounded", victim=victim, hp=args.hp)
        log.say(f"wounded slot {victim} down to {args.hp} hit point(s)")
        log.sample(sess, "wounded")

        turns = {"n": 0}

        def tactic(s, state):
            turns["n"] += 1
            log.sample(s, f"turn {turns['n']}")
            return s.melee_turn(state)

        r = sess.fight(budget=args.budget, tactic=tactic)
        log.emit("fight_end", outcome=r.outcome, turns=r.turns,
                 seconds=round(r.seconds, 1), acted=r.acted, blows=r.blows,
                 lines=r.lines, bars=r.bars)
        log.say(f"fight: {r.outcome} turns={r.turns} "
                f"seconds={round(r.seconds, 1)} blows={r.blows}")
        sess.settle(4)
        after = log.sample(sess, "fight over")

        # The sheet is the second source: `LIBRARY $38BE` masks this byte with
        # 7 and indexes a seven-name table with it, so the word the game draws
        # is what says which name the value carries.
        try:
            sheet = sess.character_sheet(victim)
            (out / "sheet.txt").write_text("\n".join(sheet or []) + "\n")
            log.emit("sheet", index=victim, lines=sheet)
            log.say("sheet written to " + str(out / "sheet.txt"))
            sess.leave_sheet()
        except Exception as exc:
            log.emit("sheet_failed", error=repr(exc))
            log.say(f"the sheet would not open: {exc!r}")

        if not args.no_save and after:
            if sess.save_game():
                sess.settle(4)
                shutil.copy(sess.save_disk, out / "saved.d64")
                on_disk = read_saved(out / "saved.d64")
                log.emit("saved", roster=on_disk)
                log.say("saved roster +0x00: "
                        + " ".join(f"{v:02X}" for v in (on_disk or [])))
            else:
                log.emit("save_failed")
                log.say("ENCAMP > SAVE did not complete")
    except Exception as exc:
        import traceback
        # What the screen said when it stopped.  A step that reports only
        # "begin_adventuring failed" cannot say whether the game was asking
        # something or had gone somewhere else entirely, and with a status
        # byte staged into a slot the second is exactly what happens.
        try:
            s = sess and sess.screen()
            screen = [ln.rstrip() for ln in s.rows()] if s else []
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
