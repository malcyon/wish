#!/usr/bin/env python3
"""Convert a save through `File ▸ Convert…`'s own code path, then play it.

Step D of `work/reports/52-plan.md` -- the plan on
`#52 (File ▸ Import and File ▸ Export for every direction the library
supports)` -- and the one thing the flag's removal condition 5 asks for:
*each registered direction has been loaded and walked in its emulator from a
save the dialog's own code path wrote*.

`tools/dosdisk.py` and `tools/dosnewsave.py` already prove `goldbox.dos`.
They are not this: they call `goldbox.dos.new_save` and
`goldbox.dos.new_dos_save` directly, where a player presses Convert and the
bytes come out of `editor.window.EditorBinding.convert` ▸
`editor.convert.ConvertDialog` ▸ `Direction.rehearse` ▸ `Direction.write`.
`tests/test_convert.py`'s three transfer tests assert those two routes are
byte-identical, so this run is expected to pass -- and a byte-identity test
is not a loaded game (`.claude/rules/conversions.md`: "A conversion is not
proven until it runs").

    tools/convertrun.py --source ~/wish-specimens/por-dos/WISH-SPEC-por-party-l1-intown \
                        --to c64 --out work/issue52/dos-to-c64 --walk II
    tools/convertrun.py --source work/issue52/dos-to-c64/wish-2026-09-05/PORSAVEE.D64 \
                        --to dos --out work/issue52/c64-to-dos --steps 2

What it does, in order:

1. builds a `ConvertDialog` with every row pre-filled and prints the pane
   text a player would be reading before they press Convert;
2. calls `EditorBinding.convert(source=…, destination=…, folder=…, game=…)`,
   which is the method `File ▸ Convert…` calls -- given every argument no
   picker opens, the way `tests/test_convert.py` drives it. `exec()` is the
   one thing replaced: it is the modal wait for a person to press Convert,
   and there is no person here;
3. boots what came out. A C64 destination goes to `tools/savecheck.py`,
   which reads the party panel and the `VIEW` sheets off the C64's own
   screen memory; a DOS destination is copied into a `tools.dosbox` staged
   game tree and loaded through the game's own `LOAD SAVED GAME`, walked,
   and saved back by `ENCAMP ▸ SAVE` so the engine's own rewrite can be
   diffed against ours.

Nothing here writes to the player's disks: the C64 sides are copied into the
pool slot by `tools.session.stage_disks`, and the DOS game tree is
`tools.dosbox.Session.stage`'s copy. `POR_HEADLESS` is the slot's own
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

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap.paths import find_disks  # noqa: E402
from goldbox import dos_savegame as sg  # noqa: E402
from tools import dosbox  # noqa: E402


def disks_dir(named: str | None = None) -> pathlib.Path:
    """Where the player keeps the C64 game disks. Read, never written."""
    if named:
        return pathlib.Path(named).expanduser()
    return pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")


# ---------------------------------------------------------------------------
# The dialog's own path
# ---------------------------------------------------------------------------

def write_via_dialog(source: pathlib.Path, to: str, folder: pathlib.Path,
                     game: pathlib.Path | None,
                     disks: pathlib.Path) -> dict:
    """Press Convert, and say what the pane said and what landed.

    `to` is `"c64"` or `"dos"` -- `Direction.destination_port`, which is what
    `ConvertDialog`'s destination combo carries as its item data.
    """
    from PyQt6.QtWidgets import QApplication, QDialog, QWidget

    from editor import convert as convert_mod
    from editor.window import EditorBinding

    app = QApplication.instance() or QApplication([])
    _ = app
    root = QWidget()
    window = EditorBinding(root, disks=str(disks))
    folder.mkdir(parents=True, exist_ok=True)

    report: dict = {"source": str(source), "to": to, "folder": str(folder)}

    # What a player would be reading before they press Convert.  Built here
    # rather than reached inside `EditorBinding.convert`, which owns its own
    # dialog: this is the same class with the same arguments, rehearsing the
    # same conversion, and it writes nothing.
    preview = convert_mod.ConvertDialog(
        str(source), window.party, window.game_files_for,
        destination=to, game=str(game) if game else None,
        folder=str(folder))
    try:
        report["pane"] = preview.ui.convert_report.toPlainText()
        report["destinations"] = [
            preview.ui.convert_destination.itemText(i)
            for i in range(preview.ui.convert_destination.count())]
        report["slot"] = preview.slot
        ok = preview.buttons.button(
            preview.buttons.StandardButton.Ok)
        report["convert_enabled"] = ok.isEnabled()
        report["dropped"] = list(
            getattr(preview.rehearsal.report, "dropped", [])
            if preview.rehearsal is not None else [])
    finally:
        preview.close()

    if not report["convert_enabled"]:
        report["error"] = "the dialog would not let a player press Convert"
        window.close()
        return report

    # The modal wait for a person, and nothing else.  Everything after it --
    # `fresh_folder`, the `mkdir`, `Direction.write`, opening a C64 result in
    # the editor -- is `EditorBinding.convert`'s own code, unpatched.
    original_exec = convert_mod.ConvertDialog.exec
    convert_mod.ConvertDialog.exec = (
        lambda self: QDialog.DialogCode.Accepted)
    try:
        note = window.convert(source=str(source), destination=to,
                              folder=str(folder),
                              game=str(game) if game else None)
    finally:
        convert_mod.ConvertDialog.exec = original_exec

    report["note"] = note
    written = sorted(p for p in folder.glob("wish-*/*") if p.is_file())
    report["written"] = [str(p) for p in written]
    report["opened_in_editor"] = (
        None if window.party is None else str(window.party.path))
    window.close()
    return report


# ---------------------------------------------------------------------------
# Playing a C64 result
# ---------------------------------------------------------------------------

def play_c64(disk: pathlib.Path, out: pathlib.Path, disks: pathlib.Path,
             walk: str, view: bool, resave: str | None) -> dict:
    """Hand the written `.d64` to `tools/savecheck.py` and read its log."""
    log = out / "savecheck.jsonl"
    argv = [str(ROOT / ".venv" / "bin" / "python"), str(TOOLS / "savecheck.py"),
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

    `tools/dosnewsave.py`'s `describe`, repeated rather than imported: that
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
    whole point of the run. `goldbox.dos.new_dos_save` clears the slot's
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
                   help="where the conversion and the run's files go; under "
                        "work/")
    p.add_argument("--game", default=None,
                   help="the DOS game folder, for a DOS destination "
                        "(default: tools.dosbox.find_game())")
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

    out = pathlib.Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    disks = disks_dir(args.disks)
    game = pathlib.Path(args.game) if args.game else (
        dosbox.find_game() if args.to == "dos" else None)

    report = {"direction": f"{args.source} -> {args.to}"}
    report["write"] = write_via_dialog(
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
        rc = 0 if report["play"].get("walked") == args.steps else 1

    (out / "convertrun.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return rc


if __name__ == "__main__":
    sys.exit(main())
