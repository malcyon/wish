#!/usr/bin/env python3
"""Build a DOS saved game from a C64 one with no template, and play it.

The acceptance check behind `#26 (Write a DOS save, not just read one)`, and
the DOS-side twin of `tools/dosdisk.py` and `tools/savecheck.py`.
`goldbox.dos.new_dos_save` builds all 13137 bytes of `SAVGAM<slot>.DAT` and
every `CHRDAT<slot><n>` beside it from a C64 save disk and the player's own
DOS game files -- no existing DOS save is opened at any point -- and this
boots the result under DOSBox and reads the party off the game's own screens.

    tools/dosnewsave.py --c64 PORSAVE13.D64 --slot A --steps 2

Why the run and not the bytes: every byte of the file now has a declared
source, and 4070 of them are declared *zero* on the strength of a census of
the engine-written specimens -- nine indoor ones, since eight of the twelve
lived under `work/` and are gone, which is why that grade is PROBABLE rather
than CONFIRMED.  A census says what a saved party held; only
the running game says what the load path reads.  This is the same bar #118
held the C64 direction's 193 zeroed header bytes to.

What it does, in order:

1. `goldbox.dos.new_dos_save` writes the slot into a **staged copy** of the
   game tree -- `tools.dosbox.Session.stage` makes it, so the archives stay
   read-only and nothing of Donald's is touched;
2. DOSBox boots and the game's own `LOAD SAVED GAME` is asked for the slot;
3. the party panel and the first character's `VIEW` sheet are captured, which
   is where a wrong AC or a garbage weapon line shows up;
4. `--steps` walks the party, which is what proves the map, the wallset and
   the staged script are the party's own and not a stranger's;
5. the game's own `ENCAMP > SAVE` writes the slot back, and the resave is
   diffed against what we wrote -- the engine's own rewrite is the oracle for
   which of the zeroed bytes it fills in for itself.

Screenshots and both saves go to `--out`, which should be under `work/`.
Run with `--check` first: it needs `dosbox`, `Xvfb`, `xdotool` and
ImageMagick's `import`, and says which are absent rather than half-running.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import dos  # noqa: E402
from goldbox import dos_savegame as sg  # noqa: E402
from goldbox.d64 import load_payload  # noqa: E402
from goldbox.games import POOL_OF_RADIANCE  # noqa: E402
from tools import dosbox  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent


def find_c64_save(name: str | None) -> pathlib.Path:
    """A C64 save disk: what `--c64` named, or the newest `PORSAVE*.D64`.

    The player's disks are found the way every other tool here finds them --
    `$POR_DISKS`, then `automap.paths.find_disks()` -- and are read only.
    """
    if name:
        return pathlib.Path(name).expanduser()
    from automap.paths import find_disks
    disks = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")
    found = sorted(disks.glob("PORSAVE*.D64"))
    if not found:
        raise SystemExit("No C64 save disk found; name one with --c64")
    return found[-1]


def c64_payloads(path: pathlib.Path) -> tuple[bytes, bytes | None]:
    """`SAVEDGAME0` and `SAVEDGAME1` out of a save disk."""
    save0 = load_payload(str(path), POOL_OF_RADIANCE.save_file)
    try:
        save1 = load_payload(str(path), POOL_OF_RADIANCE.roster_file)
    except Exception:
        save1 = None
    return save0, save1


def describe(save: bytes) -> dict:
    """What a reader needs to see to believe the file is the party's own."""
    x, y, facing = sg.position(save)
    hour, minute, day, month = sg.clock(save)
    return {
        "area": sg.current_area(save),
        "square": [x, y, facing],
        "clock": f"{hour}:{minute:02d} day {day} month {month}",
        "party_size": sg.party_size(save),
        "files": sg.character_files(save),
        "dax_byte": save[0],
        "outdoors": sg.outdoors(save),
    }


def word_diff(ours: bytes, theirs: bytes) -> list[str]:
    """Which VM words the engine's own resave changed, as `$ADDR ours->theirs`."""
    out = []
    for addr in range(sg.VAR_BASE, sg.VAR_LAST + 1):
        a, b = sg.word(ours, addr), sg.word(theirs, addr)
        if a != b:
            out.append(f"${addr:04X} {a}->{b}")
    return out


def make(*, c64: pathlib.Path, slot: str = "A", steps: int = 2,
         resave: str = "D", out: pathlib.Path | None = None) -> dict:
    """Build, boot, load, walk, resave.  Returns everything measured."""
    out = pathlib.Path(out or REPO / "work" / "p26")
    out.mkdir(parents=True, exist_ok=True)
    game = dosbox.find_game()
    save0, save1 = c64_payloads(c64)
    report: dict = {"c64": str(c64), "slot": slot, "steps_asked": steps}

    with dosbox.claim("dosnewsave") as claimed:
        # Not `with Session(...)`: its `__enter__` boots, and the save has to
        # be built into the staged tree before DOSBox reads the directory.
        s = dosbox.Session(claimed, game)
        try:
            s.stage(fresh=True)
            written = dos.new_dos_save(save0, save1, s.save_dir, slot,
                                       s.game_dir)
            report["accounted"] = f"{len(written.sources)}/{written.total}"
            report["unwritten"] = len(written.unwritten)
            report["converted"] = written.converted
            report["warnings"] = written.warnings
            ours = s.save_file(slot).read_bytes()
            (out / f"BUILT-SAVGAM{slot.upper()}.DAT").write_bytes(ours)
            report["built"] = describe(ours)

            s.boot(fresh=False)
            por = dosbox.PoolOfRadiance(s)
            por.to_main_menu()
            por.load_game(slot)
            shutil.copy(s.shot("new-loaded"), out / "loaded.png")
            report["status_line"] = por.status()

            # `v` on the map opens the first character's sheet and `i` there
            # opens the item list.  Bytes matching is necessary and not
            # sufficient: an AC of 9 shown as 51 and a garbage weapon line
            # both passed every byte check this project had.
            world = por.world_bar or por.bar()
            por.s.key("v")
            por.s.settle()
            shutil.copy(s.shot("new-sheet"), out / "sheet.png")
            por.s.key("i")
            por.s.settle()
            shutil.copy(s.shot("new-items"), out / "items.png")
            for _ in range(4):
                por.s.key("Escape")
                if por.s.wait_until_ink(dosbox.BAR, world, 5.0):
                    break
            report["back_on_the_map"] = por.bar() == world

            # A step that does not bring the world bar back has walked into
            # something, and on the Slums' streets that is usually a wandering
            # encounter.  Fighting it is better evidence than avoiding it --
            # combat is the part of the engine that fills in most of what a
            # from-nothing save leaves zero -- so the fight is fought and
            # counted rather than treated as a failed step.
            walked, fights, blocked = 0, 0, 0
            for i in range(steps):
                before = por.status()
                if por.step():
                    # A blocked step comes back on the same command bar and
                    # the same status line: the engine simply refuses it, and
                    # counting it as a walk would claim eight squares for a
                    # party that never left the first one.  Turn instead, so
                    # the walk goes somewhere and can meet something.
                    if por.status() == before:
                        blocked += 1
                        por.turn_right()
                        continue
                    walked += 1
                    continue
                if por.in_combat() or por.bar_kind() is None:
                    if not por.fight():
                        report["step_failed_at"] = i + 1
                        shutil.copy(s.shot("new-stuck", allow_blank=True),
                                    out / "stuck.png")
                        break
                    fights += 1
                    walked += 1
                    continue
                report["step_failed_at"] = i + 1
                break
            report["walked"] = walked
            report["fights"] = fights
            report["blocked"] = blocked
            if walked:
                shutil.copy(s.shot("new-walked"), out / "walked.png")
                report["status_after_walk"] = por.status()

            engine = por.save_game(resave)
            (out / f"RESAVE-SAVGAM{resave.upper()}.DAT").write_bytes(engine)
            report["resaved"] = describe(engine)
            report["engine_rewrote"] = word_diff(ours, engine)
            for n in range(1, 7):
                for p in sorted(s.save_dir.glob(f"CHRDAT{slot.upper()}{n}.*")):
                    shutil.copy(p, out / p.name)
        finally:
            s.close()

    report["out"] = str(out)
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="Report whether the emulator tooling is installed")
    ap.add_argument("--c64", default=None,
                    help="The C64 save disk to convert")
    ap.add_argument("--slot", default="A", help="The DOS slot to write")
    ap.add_argument("--resave", default="D",
                    help="The slot the game writes its own copy back to")
    ap.add_argument("--steps", type=int, default=2,
                    help="Steps to walk after loading")
    ap.add_argument("--out", default=None, help="Where the run's files go")
    args = ap.parse_args(argv)

    if args.check:
        absent = dosbox.missing_tools()
        print("Tools missing:", ", ".join(absent) if absent else "none")
        return 1 if absent else 0

    report = make(c64=find_c64_save(args.c64), slot=args.slot,
                  steps=args.steps, resave=args.resave, out=args.out)
    print(json.dumps(report, indent=2))
    return 0 if report.get("walked") == report["steps_asked"] else 1


if __name__ == "__main__":
    sys.exit(main())
