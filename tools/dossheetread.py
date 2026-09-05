#!/usr/bin/env python3
"""Load a converted DOS party in the running game and photograph every sheet.

The proof half of
`#234 (A dual-classed Curse or Silver Blades character converted to DOS loses
the class he trained out of)`.  Records matching byte for byte is necessary
and not sufficient: the question that closes that issue is what the **DOS
engine** prints for a character this project converted, so this stages the
records beside a container the engine wrote, boots the game, loads the slot,
and takes one screenshot per character with `VIEW CHARACTER` open.

    tools/dossheetread.py --game CURSE \\
        --container ~/wish-specimens/por-dos/WISH-SPEC-curse-234-party-dualclassed \\
        --records work/issue234/from-c64 \\
        --out work/issue234/dosrun

**The container is the engine's and the records are ours.**  Nothing here can
write `SAVGAM<slot>.DAT` for Curse or Silver Blades -- see
`docs/180-writing-a-later-dos-record.md` -- so the container comes from a
specimen and only the six `CHRDAT` files are replaced.  That is the same
staging `#299 (goldbox.dos.write builds only Pool of Radiance's record, so
nothing can be converted to DOS for the later titles)` used for Silver Blades.

`--resave` presses `SAVE CURRENT GAME` at the end and copies the whole `SAVE`
directory out, so the engine's own rewrite of our records can be diffed
against what we handed it -- the measurement that says which bytes the loader
recomputed.

Nothing outside the instance directory is written and the player's archives
are opened read only.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS.parent))

from tools import dosbox  # noqa: E402

#: The training hall's maximum level, at this file offset of
#: `SAVGAM<slot>.DAT` in Pool of Radiance, Curse and Silver Blades alike
#: (`#234`).  Left alone unless `--level` is given: this tool wants the sheets
#: rather than the hall, and a container nobody poked is a cleaner exhibit.
TRAIN_LEVEL = 0xD51


def install(container: pathlib.Path, records: pathlib.Path,
            save_dir: pathlib.Path, letter: str, source: str,
            train_level: int | None) -> dict:
    """Put the engine's container and our records into a clean `SAVE`.

    Only `SAVGAM<source>.DAT` is taken from `container`; every `CHRDAT` file
    comes from `records`.  A `CHRDAT` in the container is deliberately **not**
    copied, so a stale effect or item file from the container's own party can
    never be read as one of ours.
    """
    letter, source = letter.upper(), source.upper()
    took = {"container": None, "records": []}
    src = container / f"SAVGAM{source}.DAT"
    data = bytearray(src.read_bytes())
    if train_level is not None:
        data[TRAIN_LEVEL:TRAIN_LEVEL + 2] = int(train_level).to_bytes(2, "little")
    (save_dir / f"SAVGAM{letter}.DAT").write_bytes(bytes(data))
    took["container"] = f"{src.name} ({len(data)} bytes)"
    for path in sorted(records.iterdir()):
        name = path.name.upper()
        if not name.startswith("CHRDAT") or len(name) < 8:
            continue
        (save_dir / f"CHRDAT{letter}{name[7:]}").write_bytes(path.read_bytes())
        took["records"].append(f"{name} -> CHRDAT{letter}{name[7:]} "
                               f"({path.stat().st_size} bytes)")
    return took


def run(args) -> int:
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    log = (out / "run.jsonl").open("a")

    def note(**kw):
        kw["t"] = round(time.time(), 2)
        log.write(json.dumps(kw) + "\n")
        log.flush()
        print(json.dumps(kw), flush=True)

    slot = dosbox.claim(args.note)
    session = dosbox.Session(slot, dosbox.find_game(args.game))
    try:
        session.stage(fresh=True)
        shutil.rmtree(session.dir / "shots", ignore_errors=True)
        (session.dir / "shots").mkdir(parents=True, exist_ok=True)
        for old in session.save_dir.glob("*"):
            old.unlink()
        took = install(pathlib.Path(args.container), pathlib.Path(args.records),
                       session.save_dir, args.slot, args.from_slot, args.level)
        note(event="staged", slot=args.slot, **took)
        session.boot(fresh=False)
        if args.probe:
            for i in range(args.probe):
                session.key("Return")
                session.settle(quiet=0.4, timeout=10.0)
                session.shot(f"boot-{i:02d}", allow_blank=True)
        else:
            dosbox.PoolOfRadiance(session).to_main_menu()
        session.shot("0-menu")
        for i, k in enumerate(args.load_keys.split(",")):
            session.key(k.strip())
            session.settle(quiet=0.5, timeout=25.0)
            session.shot(f"1-load-{i}", allow_blank=True)
        session.settle(quiet=0.8, timeout=60.0)
        session.shot("2-party")
        note(event="loaded", digest=session.capture().digest())
        for i in range(args.characters):
            for k in args.advance.split(","):
                session.key(k)
            session.settle(quiet=0.5, timeout=20.0)
            session.shot(f"3-highlight-{i + 1}")
            session.key(args.view)
            session.settle(quiet=0.6, timeout=25.0)
            shot = session.shot(f"4-sheet-{i + 1}")
            note(event="sheet", n=i + 1, shot=shot.name,
                 digest=session.capture().digest())
            for k in args.leave.split(","):
                session.key(k.strip())
                session.settle(quiet=0.5, timeout=20.0)
            session.shot(f"5-back-{i + 1}", allow_blank=True)
        for n, press in enumerate(args.press):
            session.key(press)
            session.settle(quiet=0.6, timeout=30.0)
            session.shot(f"6-press-{n:02d}-{press}")
            note(event="pressed", key=press, digest=session.capture().digest())
        if args.resave:
            for k in args.resave.split(","):
                session.key(k.strip())
                session.settle(quiet=0.6, timeout=40.0)
                session.shot(f"7-save-{k.strip()}", allow_blank=True)
            dosbox.settle_files(session.save_dir, quiet=1.0, timeout=30.0)
            dest = out / "resave"
            shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(session.save_dir, dest)
            note(event="resaved", to=str(dest),
                 files=sorted(p.name for p in dest.iterdir()))
        shots = out / "shots"
        shots.mkdir(parents=True, exist_ok=True)
        for png in sorted((session.dir / "shots").glob("*.png")):
            shutil.copy(png, shots / png.name)
        note(event="done", shots=str(shots))
    finally:
        session.close()
        slot.release()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--game", default="CURSE", help="the game directory stem")
    ap.add_argument("--container", required=True,
                    help="a specimen directory holding SAVGAM<from-slot>.DAT")
    ap.add_argument("--records", required=True,
                    help="a directory of CHRDAT* files to install")
    ap.add_argument("--slot", default="D", help="which letter to install as")
    ap.add_argument("--from-slot", default="D",
                    help="which slot of the container to take")
    ap.add_argument("--level", type=lambda s: int(s, 0), default=None,
                    help="poke the hall's maximum level; left alone by default")
    ap.add_argument("--characters", type=int, default=6)
    ap.add_argument("--advance", default="End",
                    help="keys that move the roster highlight on by one")
    ap.add_argument("--view", default="v", help="the VIEW CHARACTER key")
    ap.add_argument("--leave", default="e",
                    help="keys that leave the sheet, comma separated")
    ap.add_argument("--load-keys", default="l,D",
                    help="the LOAD SAVED GAME keys, comma separated")
    ap.add_argument("--press", action="append", default=[],
                    help="an extra key to press at the end, repeatable")
    ap.add_argument("--resave", default="",
                    help="keys for SAVE CURRENT GAME, comma separated")
    ap.add_argument("--probe", type=int, default=0,
                    help="press Return this many times instead of "
                         "to_main_menu, for a title screen that will not "
                         "settle")
    ap.add_argument("--note", default="issue234 converted sheets")
    ap.add_argument("--out", default="work/issue234/dosrun")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
