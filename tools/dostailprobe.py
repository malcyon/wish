#!/usr/bin/env python3
"""Does the DOS engine keep, show or recompute `0x10C`-`0x10F`?

`tools/dostailcensus.py` established that Pool of Radiance's `0x10C`-`0x10F`
is not the constant `goldbox/dos.py` writes back: the engine's own resave
after a fight holds `00 01 00 01`, and a character at zero hit points holds
`04 00 00 00`.  What a census cannot say is what happens on the way **in** --
whether a value staged into a save survives a load, whether the game shows it,
and whether the engine rewrites it from something else.  That decides whether
`#235 (Two unattributed DOS byte ranges in the combat tail are dropped
converting to C64, and nobody knows what they hold)` is a defect a player sees
or a field the engine rebuilds.

So this stages one value per character into a real save, loads it in the game,
photographs the party panel, and takes the engine's own `ENCAMP > SAVE` back:

    tools/dostailprobe.py                  # the default six-value pattern
    tools/dostailprobe.py --pattern 0:04000000,1:06000000
    tools/dostailprobe.py --field field_83_87 --pattern 0:0000FF0000

Three readings come out of one boot, and they are independent of each other:

* **kept** -- the byte the engine resaved equals the byte that was staged, so
  the field is stored state the save carries and a conversion that writes a
  constant is throwing a player's value away;
* **rewritten** -- the resave disagrees with what was staged, and what it says
  instead is the interesting part: a field recomputed on load costs the
  conversion nothing;
* **shown** -- the party panel names a status beside a character whose only
  difference from the rest is the staged byte.

The party is Donald's own slot A, copied into the staged tree, so every
character starts from a record the game wrote.  **Nothing is written back to
the archives**: `Session.stage` copies the game tree into the instance's own
work directory and the copy is what is tampered with.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from goldbox import dos  # noqa: E402
from goldbox import dos_layout as dl  # noqa: E402
from tools import dosbox  # noqa: E402

#: Where a run's report and frames land.  Under `work/`, gitignored, because
#: a frame of the game is the game's own art.
OUT = REPO / "work" / "p235"

#: One value per party slot, as hex, for `field_10c_10f`.  Slot 0 is left at
#: the constant every record on this machine holds, so the run carries its own
#: control: if slot 0 comes back changed, the engine rewrites the field for
#: everybody and none of the other five readings mean anything.
#:
#: The four values chosen are the ones the census and the third-party
#: workbooks put in play -- `Status` 4 Unconscious and 6 Dead,
#: `IsQuickFight` 1, and `IsActive` 0 on its own, which no specimen holds
#: apart from the unconscious character and which separates the two.
DEFAULT_PATTERN = {
    0: "00010000",      # control: what every engine-written record holds
    1: "04000000",      # Status 4 (Unconscious), IsActive 0 -- MAGNUS's value
    2: "06000000",      # Status 6 (Dead) by the workbook enum
    3: "00010001",      # IsQuickFight 1, the after-a-fight value
    4: "00000000",      # IsActive 0 alone, with Status still Okay
    5: "05010000",      # Status 5 (Dying) with IsActive still 1
}


def parse_pattern(text: str | None) -> dict[int, str]:
    """`0:04000000,1:06000000` into `{0: "04000000", 1: "06000000"}`."""
    if not text:
        return dict(DEFAULT_PATTERN)
    out: dict[int, str] = {}
    for part in text.split(","):
        slot, _, value = part.partition(":")
        out[int(slot)] = value.strip().replace(" ", "")
    return out


def stage_pattern(save_dir: pathlib.Path, letter: str, field: str,
                  pattern: dict[int, str]) -> list[dict]:
    """Write one value into each `CHRDAT<letter><n>.SAV`, and say what."""
    f = dl.FIELDS_BY_NAME[field]
    staged = []
    for index, value in sorted(pattern.items()):
        path = save_dir / f"CHRDAT{letter.upper()}{index + 1}.SAV"
        data = bytearray(path.read_bytes())
        raw = bytes.fromhex(value)
        if len(raw) != f.size:
            raise SystemExit(
                f"{field} is {f.size} bytes; slot {index} was given "
                f"{len(raw)} ({value})")
        before = bytes(data[f.offset:f.offset + f.size])
        data[f.offset:f.offset + f.size] = raw
        path.write_bytes(bytes(data))
        staged.append({
            "slot": index + 1,
            "file": path.name,
            "name": dos.read_character(path).name,
            "before": before.hex(),
            "staged": raw.hex(),
            "hp_current": data[dl.FIELDS_BY_NAME["hp_current"].offset],
        })
    return staged


def read_back(save_dir: pathlib.Path, letter: str, field: str) -> list[dict]:
    """What the engine's own resave holds in `field`, per character."""
    f = dl.FIELDS_BY_NAME[field]
    out = []
    for n in range(1, 7):
        path = save_dir / f"CHRDAT{letter.upper()}{n}.SAV"
        if not path.is_file():
            continue
        data = path.read_bytes()
        out.append({
            "slot": n,
            "file": path.name,
            "name": dos.read_character(path).name,
            "value": data[f.offset:f.offset + f.size].hex(),
            "hp_current": data[dl.FIELDS_BY_NAME["hp_current"].offset],
        })
    return out


def run(field: str, pattern: dict[int, str], source: str, resave: str,
        label: str, keep: bool) -> dict:
    shots = OUT / label
    shots.mkdir(parents=True, exist_ok=True)
    result: dict = {"field": field, "source_slot": source,
                    "resave_slot": resave, "label": label}

    slot = dosbox.claim(f"issue235 {label}")
    session = dosbox.Session(slot, dosbox.find_game())
    try:
        session.stage(fresh=True)
        # The resave slot must be one the archives do not use, so anything
        # named for it afterwards can only be a file this run's engine wrote.
        for stale in session.save_dir.glob(f"CHRDAT{resave.upper()}*"):
            stale.unlink()
        for stale in session.save_dir.glob(f"SAVGAM{resave.upper()}*"):
            stale.unlink()
        result["staged"] = stage_pattern(session.save_dir, source, field,
                                         pattern)

        session.boot(fresh=False)
        game = dosbox.PoolOfRadiance(session)
        game.to_main_menu()
        session.shot("00-main-menu")
        game.load_game(source)
        session.settle()
        result["loaded_shot"] = str(session.shot("01-loaded"))
        session.key("v")               # VIEW the first character's sheet
        session.settle()
        result["view_shot"] = str(session.shot("02-view"))
        session.key("Escape")
        session.settle()

        game.save_game(resave)
        result["resaved"] = read_back(session.save_dir, resave, field)
        result["after_source"] = read_back(session.save_dir, source, field)
        session.shot("03-after-save", allow_blank=True)

        # Only this run's own named frames.  A slot's `shots/` directory
        # survives `stage(fresh=True)`, so copying all of it drags in every
        # frame whichever tool held the slot last took, and the run's
        # evidence goes in among four hundred of somebody else's.
        for name in ("00-main-menu", "01-loaded", "02-view", "03-after-save"):
            png = session.dir / "shots" / f"{name}.png"
            if png.is_file():
                shutil.copy(png, shots / png.name)
    finally:
        session.close()
        if not keep:
            slot.release()

    staged = {s["slot"]: s["staged"] for s in result["staged"]}
    result["verdict"] = [
        {"slot": r["slot"], "name": r["name"], "staged": staged.get(r["slot"]),
         "resaved": r["value"],
         "kept": staged.get(r["slot"]) == r["value"]}
        for r in result["resaved"]]
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--field", default="field_10c_10f",
                    help="the layout field to stage (default field_10c_10f)")
    ap.add_argument("--pattern",
                    help="slot:hex pairs, comma separated; slots are 0-based")
    ap.add_argument("--source", default="A", help="save slot to load (A)")
    ap.add_argument("--resave", default="D",
                    help="save slot to write back to; must be one the "
                         "archives do not use (D)")
    ap.add_argument("--label", default="probe", help="output subdirectory")
    ap.add_argument("--keep", action="store_true",
                    help="hold the instance slot after the run")
    args = ap.parse_args(argv)

    result = run(args.field, parse_pattern(args.pattern), args.source,
                 args.resave, args.label, args.keep)
    OUT.mkdir(parents=True, exist_ok=True)
    report = OUT / f"{args.label}.json"
    report.write_text(json.dumps(result, indent=1))
    for row in result["verdict"]:
        mark = "kept" if row["kept"] else "REWRITTEN"
        print(f"  {row['name']:16s} staged {row['staged']} -> "
              f"{row['resaved']}  {mark}")
    print(f"\n{report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
