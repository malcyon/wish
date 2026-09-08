#!/usr/bin/env python3
"""Train a DOS Curse dual-classed human past the level he left his old class
at, and keep the record the engine writes.

`#408 (What does a DOS record hold once a dual-classed character regains his
old class, since our conversion writes his old level into both arrays)` had no
engine-written specimen past that threshold on any port but the C64: every DOS
dual-classed record anybody here has is one action after the change, with the
new class at level 1.  This makes one.

**What is staged and what is measured.**  `.claude/rules/testing.md` draws the
line: editing an *input* and watching the engine compute from it is a valid
experiment; reading back a value we wrote is not.  So the run writes three
numbers into the character record before the boot --

| written by us | why |
|---|---|
| `class_levels[<his class>]` and `level` | so one training crosses the threshold instead of five |
| `experience` | so the trainer will advance him at all |
| `SAVGAM<slot>.DAT+0xD51` | the hall's class filter, so `TRAIN CHARACTER` works wherever the party stands (`docs/194-the-dos-training-ladder.md`) |

-- and everything read afterwards is the engine's: `class_levels[old]`,
`former_class_levels`, `char_class`, `class_bits`, `thac0_base`, `turn_class`,
`hp_max` and `hp_rolled`.  The two the ticket turns on are `class_levels[old]`
and `class_bits`, and **both go in holding the answer that would refute the
prediction**: the old slot is 0 and the mask carries the new class alone, so
anything else read back is something the engine did.

    tools/curseregain.py --party $WISH_SPECIMENS/por-dos/WISH-SPEC-curse-131-dualclassed-in-area-1 \
        --from-slot J --slot J --who 1,6 --set-level 5 --xp 45000 --save-to K

`--who` is a comma-separated list of roster lines to stage and train, counted
from 1, and **more than one is the point**: the party above holds MATHEW at
line 1, a magic-user 1 whose former array holds paladin 5, and PHILIPPE at
line 6, a magic-user of the same level with an empty former array.  Trained
side by side in one boot off the same staged numbers, the only difference
between the two records afterwards is the dual class, so anything else that
moved is the harness rather than the finding.

The highlight is moved with `End`, which wraps and which the game swallows
once after a redraw, so the run photographs every press.  `--dry-run` stages
into `--out/staged` and stops, for checking the poke without a slot.

Output goes under `work/`, which is gitignored.  **Copy anything to keep into
`$WISH_SPECIMENS` with `tools/specimens.py add` before the slot goes down.**
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from goldbox import dos  # noqa: E402
from tools import dosbox  # noqa: E402
from tools.dualclassagain import install  # noqa: E402

#: What to write at `SAVGAM<slot>.DAT+0xD51`.  The low byte is ANDed with the
#: per-class bit table at `DS:0x3EAA` to decide which classes this school
#: teaches (Curse `GAME.OVR:0x24D84`, `0x252B2`), so `0x00FF` is every class.
#: Pool of Radiance's own halls write `0x70 | class_bit`
#: (`docs/194-the-dos-training-ladder.md`); nothing needs that precision here.
EVERY_CLASS = 0x00FF

#: The record fields this run reports, in the order they answer the question.
WATCH = ("char_class", "level", "former_level", "class_bits", "thac0_base",
         "turn_class", "hp_max", "hp_rolled", "experience")


def describe(path: pathlib.Path) -> dict:
    """One character record, as the fields `#408` turns on."""
    c = dos.read_character(path)
    out = {"file": path.name, "name": c.name,
           "class_levels": list(c.raw("class_levels"))}
    if "former_class_levels" in c.fields:
        out["former_class_levels"] = list(c.raw("former_class_levels"))
    for f in WATCH:
        if f in c.fields:
            out[f] = c.get(f)
    return out


def stage_record(path: pathlib.Path, set_level: int | None,
                 xp: int | None) -> dict:
    """Write the run's inputs into one character record, in place.

    `set_level` goes into the slot of the class the record already holds --
    the one non-zero entry of `class_levels` -- and into `level` beside it, so
    the two agree the way every engine-written record does.  A record with no
    live class, or more than one, is refused rather than guessed at: this run
    is about a dual-classed character, who has exactly one.
    """
    c = dos.read_character(path)
    data = bytearray(path.read_bytes())
    levels = c.fields["class_levels"]
    live = [n for n, v in enumerate(c.raw("class_levels")) if v]
    changed = {}
    if set_level is not None:
        if len(live) != 1:
            raise SystemExit(f"{path.name}: {len(live)} live classes, "
                             "so there is no single slot to set")
        data[levels.offset + live[0]] = set_level
        data[c.fields["level"].offset] = set_level
        changed["class_levels[%d]" % live[0]] = set_level
        changed["level"] = set_level
    if xp is not None:
        f = c.fields["experience"]
        data[f.offset:f.offset + f.size] = int(xp).to_bytes(f.size, "little")
        changed["experience"] = xp
    path.write_bytes(bytes(data))
    return changed


def snapshot(save_dir: pathlib.Path, out: pathlib.Path, tag: str) -> list[dict]:
    d = out / "snaps" / tag
    d.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in sorted(save_dir.iterdir()):
        if p.name.upper() == "EXPLORED.DAT":
            continue
        shutil.copy(p, d / p.name)
    for p in sorted(d.glob("CHRDAT*.SAV")):
        rows.append(describe(p))
    return rows


def run(args: argparse.Namespace) -> int:
    party = pathlib.Path(args.party).expanduser()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    log = (out / "run.jsonl").open("a")

    def note(**kw):
        kw["t"] = round(time.time(), 2)
        log.write(json.dumps(kw, default=str) + "\n")
        log.flush()
        print(json.dumps(kw, default=str), flush=True)

    who = [int(n) for n in str(args.who).split(",")]

    def stage_all(save_dir: pathlib.Path) -> None:
        install(party, save_dir, args.slot, args.level, args.from_slot)
        for line in who:
            rec = save_dir / f"CHRDAT{args.slot.upper()}{line}.SAV"
            note(event="staged", record=rec.name, line=line,
                 changed=stage_record(rec, args.set_level, args.xp))

    if args.dry_run:
        staged = out / "staged"
        shutil.rmtree(staged, ignore_errors=True)
        staged.mkdir(parents=True)
        stage_all(staged)
        for row in sorted(staged.glob("CHRDAT*.SAV")):
            note(event="record", **describe(row))
        return 0

    slot = dosbox.claim("issue408 curse regain")
    session = dosbox.Session(slot, dosbox.find_game(args.game))
    try:
        session.stage(fresh=True)
        shutil.rmtree(session.dir / "shots", ignore_errors=True)
        (session.dir / "shots").mkdir(parents=True, exist_ok=True)
        for old in session.save_dir.glob("*"):
            old.unlink()
        stage_all(session.save_dir)
        note(event="hall", train_level=args.level)
        for row in snapshot(session.save_dir, out, "before"):
            note(event="before", **row)

        session.boot(fresh=False)
        dosbox.PoolOfRadiance(session).to_main_menu()
        session.shot("00-main-menu")
        session.key("l")
        session.settle(quiet=0.5, timeout=20.0)
        session.shot("01-load-which")
        session.key(args.slot.lower())
        time.sleep(3.0)
        session.settle(quiet=0.8, timeout=90.0)
        session.shot("02-party-menu")
        note(event="loaded", digest=session.capture().digest())

        # The roster highlight starts on line 1 and `End` wraps from the last
        # line back to it, so the count from any line to any other is
        # `(want - here) % size` -- tracked across the whole boot, because a
        # menu that closes and reopens leaves it where the last one did
        # (`docs/194-the-dos-training-ladder.md`).
        here = 1
        for line in who:
            for n in range((line - here) % args.party_size):
                session.key("End")
                session.settle(quiet=0.5, timeout=20.0)
                session.shot(f"03-line{line}-end{n + 1}")
            here = line
            note(event="highlight", line=line,
                 digest=session.capture().digest())
            for n, press in enumerate(args.steps):
                if press.startswith("~"):
                    time.sleep(float(press[1:]))
                else:
                    session.key(press)
                session.settle(quiet=0.6, timeout=40.0)
                shot = session.shot(f"04-line{line}-{n:02d}-{press}",
                                    allow_blank=True)
                note(event="pressed", line=line, key=press, shot=shot.name,
                     digest=session.capture().digest())

        if args.save_to:
            # `PoolOfRadiance.save_game` is not used here: its ENCAMP > SAVE
            # is verified by `SAVGAM<letter>.DAT` changing, and Curse's camp
            # menu takes a different path to the slot list.  The keys are
            # pressed and photographed one at a time instead, and the file is
            # polled afterwards, so a run that misses says which screen it
            # was looking at when it did.
            session.key("b")
            session.settle(quiet=0.8, timeout=90.0)
            session.shot("05-adventuring")
            path = session.save_file(args.save_to)
            was = path.read_bytes() if path.is_file() else None
            for n, press in enumerate(args.after):
                if press.startswith("~"):
                    time.sleep(float(press[1:]))
                else:
                    session.key(press)
                session.settle(quiet=0.6, timeout=40.0)
                shot = session.shot(f"06-save-{n:02d}-{press}",
                                    allow_blank=True)
                note(event="saving", key=press, shot=shot.name,
                     digest=session.capture().digest())
            deadline = time.time() + 60.0
            while time.time() < deadline:
                if path.is_file() and path.read_bytes() != was:
                    break
                time.sleep(0.3)
            dosbox.settle_files(session.save_dir, timeout=60.0)
            note(event="saved", slot=args.save_to,
                 changed=path.is_file() and path.read_bytes() != was)
        note(event="done")
    finally:
        # The snapshot and the shots are taken here rather than at the end of
        # the try, because a run that falls over between the training and the
        # save still wrote records worth reading -- and the slot's directory
        # goes with the next run's `stage(fresh=True)`.  One boot was lost
        # that way.
        try:
            for row in snapshot(session.save_dir, out, "after"):
                note(event="after", **row)
            shots = out / "shots"
            shots.mkdir(parents=True, exist_ok=True)
            for png in sorted((session.dir / "shots").glob("*.png")):
                shutil.copy(png, shots / png.name)
            note(event="kept", shots=str(shots))
        except Exception as exc:                             # noqa: BLE001
            note(event="keeping-failed", error=repr(exc))
        session.close()
        slot.release()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--party", required=True,
                    help="a save tree holding SAVGAM*.DAT and CHRDAT*")
    ap.add_argument("--game", default="CURSE", help="the game directory stem")
    ap.add_argument("--slot", default="J", help="which letter to install as")
    ap.add_argument("--from-slot", default="J",
                    help="which slot of the source tree is the party")
    ap.add_argument("--who", default="1",
                    help="roster lines to stage and train, counted from 1")
    ap.add_argument("--party-size", type=int, default=6,
                    help="how many lines the roster has, for End's wrap")
    ap.add_argument("--level", type=lambda s: int(s, 0), default=EVERY_CLASS,
                    help="what to write at 0xD51; 0 leaves the hall shut")
    ap.add_argument("--set-level", type=int, default=None,
                    help="the class level to stage before the boot")
    ap.add_argument("--xp", type=lambda s: int(s, 0), default=None,
                    help="the experience to stage before the boot")
    ap.add_argument("--steps", nargs="*",
                    default=["t", "y", "l", "l", "l"],
                    help="keys to press from the party menu; ~N sleeps")
    ap.add_argument("--save-to", default=None,
                    help="BEGIN ADVENTURING, then run --after and expect this "
                         "slot's SAVGAM to change")
    ap.add_argument("--after", nargs="*",
                    default=["e", "s", "k", "Return", "Escape", "n"],
                    help="keys pressed after BEGIN ADVENTURING; ~N sleeps")
    ap.add_argument("--dry-run", action="store_true",
                    help="stage into --out/staged and stop, with no emulator")
    ap.add_argument("--out", default=str(REPO / "work" / "issue408" / "run"))
    args = ap.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
