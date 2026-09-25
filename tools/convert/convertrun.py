#!/usr/bin/env python3
"""Convert a save through the editor's Save As route, then play it.

Each registered direction is loaded and walked in its emulator from the bytes
Save As publishes: `tools/convert/saveasdrive.py` opens the source as the
editor does and calls `saveplan.prepare_save_as` and `saveplan.publish`, so
what boots is the rehearsed output, and a conversion that would lose a field
is refused here as it is in the editor. `tools/dos/dosdisk.py` and
`tools/dos/dosnewsave.py` prove `goldbox.dos_codec` by calling it directly;
this run does not. A byte-identity test is not a loaded game
(`.claude/rules/conversions.md`: "A conversion is not proven until it runs").

    tools/convert/convertrun.py --source ~/wish-specimens/por-dos/WISH-SPEC-por-party-l1-intown \
                        --to c64 --out DIR --walk II
    tools/convert/convertrun.py --source DIR/wish-2026-09-05/WISHSAVE.D64 \
                        --to dos --out DIR2 --steps 2

What it does, in order:

1. opens the source and Save As it to `--to` under `--out`, in a dated
   `wish-<date>` folder, with the game data the route needs; a refusal is
   reported as `refused` and the run stops without booting anything;
2. boots what came out. A C64 destination goes to the reader that knows
   its title -- `tools/c64/savecheck.py` for Pool of Radiance,
   `tools/curse_of_the_azure_bonds/cursecheck.py` for Curse of the Azure Bonds -- which reads the
   party panel and the `VIEW` sheets off the C64's own
   screen memory; a DOS destination is copied into a `tools.dos.dosbox` staged
   game tree and loaded through the game's own `LOAD SAVED GAME`, walked,
   and saved back by `ENCAMP ▸ SAVE` so the engine's own rewrite can be
   diffed against ours.

Nothing here writes to the player's disks: the C64 sides are copied into the
pool slot by `tools.c64.session.stage_disks`, and the DOS game tree is
`tools.dos.dosbox.Session.stage`'s copy. `POR_HEADLESS` is the slot's own
default, so no window lands on the desktop, and this module unsets
`WAYLAND_DISPLAY` and forces `QT_QPA_PLATFORM=offscreen` before PyQt6 is
imported for the same reason.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys

# Before PyQt6 is imported anywhere below.  Donald works at this desktop
# while agents run, and a Qt child prefers Wayland over whatever is set for
# X, so unsetting `WAYLAND_DISPLAY` is the half that is easy to miss.
# `setdefault` is not enough for the two Qt variables: this desktop exports
# `QT_QPA_PLATFORM=wayland;xcb` and `GDK_BACKEND=wayland,x11` already, so a
# default is never reached and Qt goes looking for a display.
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("XDG_SESSION_TYPE", None)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["GDK_BACKEND"] = "x11"
os.environ.setdefault("POR_HEADLESS", "1")

TOOLS = pathlib.Path(__file__).resolve().parent.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap.paths import tool_disks  # noqa: E402
from goldbox import dos_savegame as sg  # noqa: E402
from tools.dos import dosbox  # noqa: E402


def disks_dir(named: str | None = None) -> pathlib.Path | None:
    """Where the player keeps the C64 game disks, or `None` when there are
    none. Read, never written."""
    if named:
        return pathlib.Path(named).expanduser()
    return tool_disks()


# ---------------------------------------------------------------------------
# The Save As route
# ---------------------------------------------------------------------------

def write_via_save_as(source: pathlib.Path, to: str, folder: pathlib.Path,
                      game: pathlib.Path | None,
                      disks: pathlib.Path) -> dict:
    """Save As the source to `to` and say what landed.

    `to` is `"c64"` or `"dos"`, the destination port. The report is
    `saveasdrive.save_as`'s: `written`, `slot`, `losses` and `dropped`, or
    `refused` and `error` when Save As would not publish it.
    """
    from PyQt6.QtWidgets import QApplication, QWidget

    from editor.window import EditorBinding
    from tools.convert import saveasdrive

    app = QApplication.instance() or QApplication([])
    _ = app
    root = QWidget()
    window = EditorBinding(root, disks=str(disks))
    folder.mkdir(parents=True, exist_ok=True)
    try:
        report = saveasdrive.save_as(
            window, source, to, folder,
            c64_folder=disks if to == "c64" else None,
            dos_folder=game if to == "dos" else None)
    finally:
        window.close()
    return report


# ---------------------------------------------------------------------------
# Playing a C64 result
# ---------------------------------------------------------------------------

def c64_title(disk: pathlib.Path) -> str:
    """Which title the written `.d64` is, off the disk's own directory.

    `goldbox.savegame.load_save` identifies it the same way the editor does,
    so this asks the disk rather than the command line -- a wrong answer here
    would boot the wrong game and take an hour to say so.
    """
    from goldbox.d64 import D64
    from goldbox.savegame import load_save

    game, _sg0, _sg1 = load_save(D64.from_bytes(disk.read_bytes()))
    return game.key


def play_c64(disk: pathlib.Path, out: pathlib.Path, disks: pathlib.Path,
             walk: str, view: bool, resave: str | None) -> dict:
    """Hand the written `.d64` to whichever reader knows its title.

    `tools/c64/savecheck.py` boots through `tools/c64/session.py`, which knows Pool of
    Radiance's fastloader prompt, main menu and copy protection and none of
    Curse's -- so a Curse disk goes to `tools/curse_of_the_azure_bonds/cursecheck.py`, which boots
    through `tools/curse_of_the_azure_bonds/curserun.py` and reads the same things off the same kinds
    of screen.  Secret of the Silver Blades has no such tool yet and falls
    through to `savecheck.py`, where it will not boot; that is the row this
    file cannot run unattended.
    """
    curse = c64_title(disk) == "curse-of-the-azure-bonds"
    log = out / ("cursecheck.jsonl" if curse else "savecheck.jsonl")
    if curse:
        argv = [str(ROOT / ".venv" / "bin" / "python"),
                str(TOOLS / "curse_of_the_azure_bonds" / "cursecheck.py"),
                "--disk", str(disk), "--disks", str(disks),
                "--out", str(out / "cursecheck")]
        if walk:
            argv += ["--walk", walk]
        if not view:
            argv += ["--no-view"]
        if resave:
            argv += ["--resave", str(out / resave)]
        log = out / "cursecheck" / "cursecheck.jsonl"
    else:
        argv = [str(ROOT / ".venv" / "bin" / "python"),
                str(TOOLS / "c64" / "savecheck.py"),
                "--disk", str(disk), "--disks", str(disks),
                "--out", str(log), "--tag", disk.stem]
        if walk:
            argv += ["--walk", walk]
        if view:
            argv += ["--view"]
        if resave:
            argv += ["--resave", str(out / resave)]
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=3600)
    events = []
    if log.exists():
        for line in log.read_text().splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    events.append(json.loads(line))
                except ValueError:
                    pass
    return {"returncode": proc.returncode, "log": str(log),
            "tail": proc.stdout[-4000:], "stderr": proc.stderr[-2000:],
            "events": events}


# ---------------------------------------------------------------------------
# Playing a DOS result
# ---------------------------------------------------------------------------

def describe_dos(save: bytes) -> dict:
    """What a reader needs to believe the file is this party's own.

    `tools/dos/dosnewsave.py`'s `describe`, repeated rather than imported: that
    module's `make()` builds the save itself, which is the thing this run
    exists not to do.
    """
    x, y, facing = sg.position(save)
    hour, minute, day, month = sg.clock(save)
    return {"area": sg.current_area(save),
            "square": [x, y, facing],
            "clock": f"{hour}:{minute:02d} day {day} month {month}",
            "party_size": sg.party_size(save),
            "files": sg.character_files(save),
            "outdoors": sg.outdoors(save)}


def word_diff(ours: bytes, theirs: bytes) -> list[str]:
    """Which VM words the engine's own resave changed."""
    out = []
    for addr in range(sg.VAR_BASE, sg.VAR_LAST + 1):
        a, b = sg.word(ours, addr), sg.word(theirs, addr)
        if a != b:
            out.append(f"${addr:04X} {a}->{b}")
    return out


def play_dos(written: list[pathlib.Path], slot: str, out: pathlib.Path,
             steps: int, resave: str) -> dict:
    """Copy the dialog's files into a staged game tree and load them.

    The files are copied verbatim -- nothing is rebuilt here, which is the
    whole point of the run. `goldbox.dos_codec.new_dos_save` clears the slot's
    stale `CHRDAT<slot><n>.*` before it moves its own files in, and a copy
    into a freshly staged tree has to do the same or a shipped party's
    record could outlive the one being loaded.
    """
    report: dict = {"slot": slot, "steps_asked": steps}
    with dosbox.claim("convertrun") as claimed:
        s = dosbox.Session(claimed, dosbox.find_game())
        try:
            s.stage(fresh=True)
            cleared = []
            for n in range(1, sg.PARTY_ENTRIES + 1):
                for suffix in (".SAV", ".ITM", ".SPC"):
                    stale = s.save_dir / f"CHRDAT{slot}{n}{suffix}"
                    if stale.exists():
                        stale.unlink()
                        cleared.append(stale.name)
            report["cleared_from_the_staged_tree"] = cleared
            for p in written:
                shutil.copy(p, s.save_dir / p.name)
            report["copied"] = [p.name for p in written]

            ours = s.save_file(slot).read_bytes()
            (out / f"BUILT-SAVGAM{slot}.DAT").write_bytes(ours)
            report["built"] = describe_dos(ours)

            s.boot(fresh=False)
            por = dosbox.PoolOfRadiance(s)
            por.to_main_menu()
            por.load_game(slot)
            shutil.copy(s.shot("loaded"), out / "loaded.png")
            report["status_line"] = por.status()

            world = por.world_bar or por.bar()
            por.s.key("v")
            por.s.settle()
            shutil.copy(s.shot("sheet"), out / "sheet.png")
            por.s.key("i")
            por.s.settle()
            shutil.copy(s.shot("items"), out / "items.png")
            for _ in range(4):
                por.s.key("Escape")
                if por.s.wait_until_ink(dosbox.BAR, world, 5.0):
                    break
            report["back_on_the_map"] = por.bar() == world

            walked = fights = blocked = 0
            for i in range(steps):
                before = por.status()
                if por.step():
                    if por.status() == before:
                        blocked += 1
                        por.turn_right()
                        continue
                    walked += 1
                    continue
                if por.in_combat() or por.bar_kind() is None:
                    if not por.fight():
                        report["step_failed_at"] = i + 1
                        shutil.copy(s.shot("stuck", allow_blank=True),
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
                shutil.copy(s.shot("walked"), out / "walked.png")
                report["status_after_walk"] = por.status()

            engine = por.save_game(resave)
            (out / f"RESAVE-SAVGAM{resave}.DAT").write_bytes(engine)
            report["resaved"] = describe_dos(engine)
            report["engine_rewrote"] = word_diff(ours, engine)
            # The per-step count above can undercount a step that crossed
            # into another area (#341): the status digest it is built from
            # can still be reading the departed square when it is sampled.
            # The engine's own resave is read straight out of the save
            # file, never the screen, so it is the one number a report can
            # be believed on without opening the screenshots.
            report["moved"] = dosbox.run_walked(report["built"],
                                                 report["resaved"])
            # Both slots' records, not just the container.  The slot dies with
            # the session (`.claude/rules/testing.md`: "A specimen dies with
            # the emulator slot that made it"), and a `SAVGAM<slot>.DAT` with
            # no `CHRDAT<slot><n>` beside it is a saved game whose party is
            # missing -- which is how the first of these was kept and had to
            # be thrown away.
            kept = []
            for letter in (slot, resave):
                for p in sorted(s.save_dir.glob(f"CHRDAT{letter}?.*")):
                    shutil.copy(p, out / p.name)
                    kept.append(p.name)
            report["kept"] = kept
        finally:
            s.close()
    return report


# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--source", required=True,
                   help="the save to convert: a DOS folder, a SAVGAM<slot>."
                        "DAT/.PTY, or a .d64")
    p.add_argument("--to", required=True, choices=("c64", "dos"),
                   help="the destination port")
    p.add_argument("--out", required=True,
                   help="where the conversion and the run's files go")
    p.add_argument("--game", default=None,
                   help="the DOS game folder, for a DOS destination "
                        "(default: tools.dos.dosbox.find_game())")
    p.add_argument("--disks", default=None,
                   help="the player's C64 game disks; read, never written")
    p.add_argument("--walk", default="II",
                   help="C64: the moves savecheck walks after arriving")
    p.add_argument("--steps", type=int, default=2,
                   help="DOS: steps to walk after loading")
    p.add_argument("--resave", default=None,
                   help="have the game's own save write the party back "
                        "(C64: a .d64 name; DOS: a slot letter)")
    p.add_argument("--no-view", action="store_true",
                   help="C64: skip the VIEW sheets")
    p.add_argument("--no-play", action="store_true",
                   help="write the conversion and stop before the emulator")
    args = p.parse_args(argv)

    # Both destinations read C64 disks: a C64 destination for its icon and
    # `ANIMATE00` tables, and a C64 source going to DOS for the source title's
    # icon table (`saveplan.resolve_assets`).
    disks = disks_dir(args.disks)
    if disks is None:
        raise SystemExit("No game disks found. Set $POR_DISKS.")
    out = pathlib.Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    game = pathlib.Path(args.game) if args.game else (
        dosbox.find_game() if args.to == "dos" else None)

    report = {"direction": f"{args.source} -> {args.to}"}
    report["write"] = write_via_save_as(
        pathlib.Path(args.source).expanduser(), args.to, out, game, disks)
    written = [pathlib.Path(p) for p in report["write"].get("written", [])]
    if not written:
        print(json.dumps(report, indent=2))
        return 1

    if args.no_play:
        print(json.dumps(report, indent=2))
        return 0

    if args.to == "c64":
        disk = next(p for p in written if p.suffix.upper() == ".D64")
        report["play"] = play_c64(disk, out, disks, args.walk,
                                  not args.no_view, args.resave)
        rc = report["play"]["returncode"]
    else:
        report["play"] = play_dos(written, report["write"]["slot"] or "A",
                                  out, args.steps, args.resave or "D")
        # `moved` is read out of the built and resaved files, not the
        # per-step digest count, so a step that crossed into another area
        # cannot read as a failure here the way it could in `walked` (#341
        # (A DOS run reports a party that walked into another area as never
        # having walked)).  Asking for no steps at all is not a claim that
        # any would be taken.
        rc = 0 if args.steps == 0 or report["play"].get("moved") else 1

    (out / "convertrun.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return rc


if __name__ == "__main__":
    sys.exit(main())
