#!/usr/bin/env python3
"""Walk a C64-to-DOS Pool of Radiance conversion in DOSBox, one hand-made step
at a time, and record every attempt.

Written for `#52 (File ▸ Import and File ▸ Export for every direction the
library supports)`, the `C64ToDos` Pool of Radiance walk. It replaces
`tools/convert/convertrun.py`'s automatic `play_dos()` step count, whose
`step()`/`turn_right()` retry cycled through all four headings with nothing
found open: the converted save's starting square (New Phlan, 0,4) is walled on
the side its own facing points, as the sibling `DosToC64` walk had found. That
walk found an opening by turning the party about before stepping; this does
the same by hand and records every attempt rather than trusting the first one
that succeeds.

The positional arguments are the converted `CHRDAT<slot>*` files (as
`convertrun.py` writes them); the tool clears any stale ones of that slot from
a freshly staged game folder, copies them in, loads the slot, opens one sheet,
walks, then saves over slot `D` with the engine's own `SAVE` and keeps what it
wrote.

`before`/`after` in each attempt are `por.status()`'s screen digest, not the
save file on disk -- the file only reflects the party's position as of the
last ENCAMP > SAVE, not live during play. An earlier draft re-read the save
file mid-walk and always saw the arrival square, which was the file's
staleness, not a wall.

Claims one DOSBox pool slot; the run is `--out` (screenshots, the resaved
`SAVGAMD.DAT`, the character files and `walk-report.json`).

    .venv/bin/python -m tools.c64.c64todoswalk --slot A --out DIR \\
        path/to/SAVGAMA.DAT path/to/CHRDATA1.SAV ...
"""
import argparse
import json
import os
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from goldbox import dos_savegame as sg  # noqa: E402
from tools.dos import dosbox  # noqa: E402


def describe(save: bytes) -> dict:
    x, y, facing = sg.position(save)
    hour, minute, day, month = sg.clock(save)
    return {"area": sg.current_area(save), "square": [x, y, facing],
            "clock": f"{hour}:{minute:02d} day {day} month {month}",
            "party_size": sg.party_size(save), "files": sg.character_files(save)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("written", nargs="+", type=pathlib.Path,
                    help="the converted files to copy into the save folder")
    ap.add_argument("--slot", required=True,
                    help="the save slot letter the conversion wrote")
    ap.add_argument("--out", required=True, type=pathlib.Path,
                    help="folder for screenshots, the resave and the report")
    args = ap.parse_args(argv)

    os.environ.pop("WAYLAND_DISPLAY", None)
    os.environ.pop("XDG_SESSION_TYPE", None)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["GDK_BACKEND"] = "x11"
    os.environ.setdefault("POR_HEADLESS", "1")

    written = args.written
    out = args.out
    slot = args.slot
    out.mkdir(parents=True, exist_ok=True)

    report: dict = {"slot": slot}
    with dosbox.claim("c64todos-pool-walk") as claimed:
        s = dosbox.Session(claimed, dosbox.find_game())
        try:
            s.stage(fresh=True)
            for n in range(1, sg.PARTY_ENTRIES + 1):
                for suffix in (".SAV", ".ITM", ".SPC"):
                    stale = s.save_dir / f"CHRDAT{slot}{n}{suffix}"
                    if stale.exists():
                        stale.unlink()
            for p in written:
                shutil.copyfile(p, s.save_dir / p.name)

            ours = s.save_file(slot).read_bytes()
            report["built"] = describe(ours)

            s.boot(fresh=False)
            por = dosbox.PoolOfRadiance(s)
            por.to_main_menu()
            por.load_game(slot)
            shutil.copyfile(s.shot("01-loaded"), out / "01-loaded.png")
            report["status_after_load"] = por.status()
            report["arrived"] = describe(s.save_file(slot).read_bytes())

            world = por.world_bar
            por.s.key("v")
            por.s.settle()
            shutil.copyfile(s.shot("02-sheet"), out / "02-sheet.png")
            for _ in range(4):
                por.s.key("Escape")
                if por.s.wait_until_ink(dosbox.BAR, world, 5.0):
                    break

            # The starting square from this specimen's own trail (New Phlan,
            # 0,4 facing west) is walled the way the sibling walk found; turn
            # about before stepping, the same fix that walk used.
            por.turn_right()
            por.turn_right()
            attempts = []
            moved = False
            for i in range(8):
                before = por.status()
                ok = por.step()
                after = por.status()
                attempts.append({"i": i, "move_ok": ok, "before": before,
                                 "after": after})
                if ok and after != before:
                    moved = True
                    shutil.copyfile(s.shot(f"03-walked-{i}"),
                                out / f"03-walked-{i}.png")
                    break
                por.turn_right()
            report["attempts"] = attempts
            report["moved"] = moved

            engine = por.save_game("D")
            report["resaved"] = describe(engine)
            (out / "RESAVE-SAVGAMD.DAT").write_bytes(engine)
            kept = []
            for letter in (slot, "D"):
                for p in sorted(s.save_dir.glob(f"CHRDAT{letter}?.*")):
                    shutil.copyfile(p, out / p.name)
                    kept.append(p.name)
            report["kept"] = kept
        finally:
            s.close()

    (out / "walk-report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
