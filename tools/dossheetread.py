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

**Two stagings, and `--save` is the stronger one.**  `--container` plus
`--records` puts our six `CHRDAT` files beside a `SAVGAM<slot>.DAT` the
engine wrote, which is all that was possible before
`#299 (goldbox.dos.write builds only Pool of Radiance's record, so nothing
can be converted to DOS for the later titles)` closed.  `--save` installs a
**whole** save this project wrote -- container and records together, nothing
borrowed from a specimen -- which is what a conversion out of the Convert
dialog produces.  A `CHRDAT` in a `--container` directory is deliberately
not copied, so a stale effect or item file from the container's own party
can never be read as one of ours.

`--walk` presses `BEGIN ADVENTURING` and walks the party, so the save is
proven to be a game rather than a file that loads
(`.claude/rules/conversions.md`: "A conversion is not proven until it
runs"), and `--engine-save <letter>` then has the game's own `ENCAMP ▸ SAVE`
write the party back.  `--resave` is the older route to the same place, a
comma-separated key sequence pressed wherever the run has got to.  Either
copies the whole `SAVE` directory out, so the engine's own rewrite of our
records can be diffed against what we handed it -- the measurement that says
which bytes the loader recomputed.

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


def install_whole(save: pathlib.Path, save_dir: pathlib.Path,
                  letter: str, source: str) -> dict:
    """Put a whole save this project wrote into a clean `SAVE` (#299).

    The other half of :func:`install`: here the container is **ours too**,
    built from nothing by `goldbox.dos.new_dos_save`, so every file of the
    slot comes from `save` and nothing is borrowed from a specimen.  The
    slot letter is kept as written unless `letter` differs from `source`,
    and Silver Blades refuses a save installed under a different letter from
    the one it was written as, so pass the same letter for it.
    """
    letter, source = letter.upper(), source.upper()
    took = {"container": None, "records": []}
    for path in sorted(save.iterdir()):
        name = path.name.upper()
        if name == f"SAVGAM{source}.DAT":
            dest = save_dir / f"SAVGAM{letter}.DAT"
            dest.write_bytes(path.read_bytes())
            took["container"] = f"{path.name} ({path.stat().st_size} bytes)"
        elif name.startswith(f"CHRDAT{source}"):
            dest = save_dir / f"CHRDAT{letter}{name[7:]}"
            dest.write_bytes(path.read_bytes())
            took["records"].append(f"{name} -> {dest.name} "
                                   f"({path.stat().st_size} bytes)")
    if took["container"] is None:
        raise FileNotFoundError(f"no SAVGAM{source}.DAT in {save}")
    return took


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


def press_keys(session, keys: str, quiet: float = 0.5,
               timeout: float = 25.0) -> None:
    """Press a comma-separated key list, settling after each."""
    for key in keys.split(","):
        if key.strip():
            session.key(key.strip())
            session.settle(quiet=quiet, timeout=timeout)


def walk(session, steps: int, note, begin: str = "b",
         engine_save: str = "", move_mode: str = "",
         move_exit: str = "Escape") -> dict:
    """Leave the party menu, walk `steps` squares, and let the engine save.

    **A save that loads is not yet a game** (`.claude/rules/conversions.md`:
    "A conversion is not proven until it runs"), and this is the half that
    says so: the party moves under the engine's own movement code, and the
    engine's own `ENCAMP ▸ SAVE` afterwards carries the square it reached.

    `LOAD SAVED GAME` leaves the party standing at `CHOOSE A FUNCTION` with
    the roster drawn, which is where the sheets are read -- so `BEGIN
    ADVENTURING` has to be pressed before anything can move.  A walk driven
    without it presses arrow keys at a menu that has none, which reads as
    six blocked steps rather than as an error.

    `tools/dosbox.py`'s `PoolOfRadiance` is the driver, and nothing in the
    part of it used here is Pool of Radiance's: `move` presses a key and
    waits for the command bar recorded on arrival to come back, and
    `save_game` believes the save only once `SAVGAM<letter>.DAT` changes on
    disk.  Both are the same in all three titles.
    """
    por = dosbox.PoolOfRadiance(session)
    for key in begin.split(","):
        if key.strip():
            session.key(key.strip())
    screen = session.settle(quiet=0.8, timeout=60.0)
    por.world_bar = screen.ink(dosbox.BAR)
    por.world_glyphs = screen.glyphs(dosbox.BAR)
    session.shot("6-walk-00-arrived")
    out = {"asked": steps, "walked": 0, "turned": 0,
           "status_on_arrival": por.status()}
    map_bar, map_glyphs = por.world_bar, por.world_glyphs
    if move_mode:
        # **Silver Blades does not walk on the arrow keys.**  Its map bar
        # reads `MOVE AREA CAST VIEW ENCAMP SEARCH LOOK` where Pool of
        # Radiance's and Curse's start at `AREA`, and that first word is a
        # mode: until it is pressed the arrows do nothing at all, and six
        # steps in a dungeon read as six walls.  Pressed, the bar becomes
        # `EXIT` alone and the arrows move the party a square -- 3,3 to 3,4
        # with the clock going 04:16 to 04:17, watched.  So the bar every
        # step waits for is that one, not the map's.
        session.key(move_mode)
        screen = session.settle(quiet=0.6, timeout=30.0)
        por.world_bar = screen.ink(dosbox.BAR)
        por.world_glyphs = screen.glyphs(dosbox.BAR)
        session.shot("6-walk-00-moving")
        out["move_mode"] = move_mode
    for i in range(steps):
        before = por.status()
        moved = por.step()
        after = por.status()
        session.shot(f"6-walk-{i + 1:02d}", allow_blank=True)
        if moved and after != before:
            out["walked"] += 1
            note(event="step", n=i + 1, moved=True)
            continue
        # A wall, or a step into something that put a prompt up.  Turning is
        # a move the engine makes too, so a party that cannot go forward is
        # still being driven rather than stuck.
        por.turn_right()
        out["turned"] += 1
        note(event="step", n=i + 1, moved=False, turned=True)
    out["status_after"] = por.status()
    if move_mode:
        session.key(move_exit)
        session.settle(quiet=0.6, timeout=30.0)
        por.world_bar, por.world_glyphs = map_bar, map_glyphs
        session.shot("6-walk-98-back-on-the-map", allow_blank=True)
        out["back_on_the_map"] = por.bar() == map_bar
    if engine_save:
        # `save_game` believes the save only once `SAVGAM<letter>.DAT` has
        # changed on disk, and *then* walks back out of camp.  Curse's camp
        # menu is not Pool of Radiance's and `leave_camp` times out at it --
        # after the file is written.  Losing the run's whole evidence to a
        # menu the party has finished with is the wrong trade, so the way
        # out is reported and the files are kept.
        try:
            por.save_game(engine_save)
            out["engine_saved_to"] = engine_save
        except TimeoutError as e:
            out["engine_saved_to"] = engine_save
            out["left_in_camp"] = str(e)
            note(event="left_in_camp", why=str(e))
        session.shot("6-walk-99-saved", allow_blank=True)
    return out


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
        if args.save:
            took = install_whole(pathlib.Path(args.save), session.save_dir,
                                 args.slot, args.from_slot)
        else:
            took = install(pathlib.Path(args.container),
                           pathlib.Path(args.records),
                           session.save_dir, args.slot, args.from_slot,
                           args.level)
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
            if args.sheet_open:
                press_keys(session, args.sheet_open if i == 0
                           else (args.sheet_reopen or args.sheet_open))
                session.shot(f"3-highlight-{i + 1}")
                # **The picker's highlight is where the last pick left it**,
                # not back at the top: pressing `i` downs on the i-th
                # character walks 0, 1, 3, 6, 10, 15 down a list of six and
                # reads GUY, PAINE, MALACHITE, GUY, DOMINIC, MALACHITE --
                # measured, by six screen digests of which two pairs matched.
                # One down per character after the first is what walks it.
                press_keys(session, args.pick_down if i else "")
                press_keys(session, args.pick_select)
            else:
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
        if args.walk:
            note(event="walk", **walk(session, args.walk, note,
                                      args.begin, args.engine_save,
                                      args.move_mode, args.move_exit))
        for n, press in enumerate(args.press):
            session.key(press)
            session.settle(quiet=0.6, timeout=30.0)
            session.shot(f"6-press-{n:02d}-{press}")
            note(event="pressed", key=press, digest=session.capture().digest())
        if args.resave or args.engine_save:
            for k in (args.resave or "").split(","):
                if not k.strip():
                    continue
                session.key(k.strip())
                session.settle(quiet=0.6, timeout=40.0)
                session.shot(f"7-save-{k.strip()}", allow_blank=True)
            dosbox.settle_files(session.save_dir, quiet=1.0, timeout=30.0)
            dest = out / "resave"
            shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(session.save_dir, dest)
            note(event="resaved", to=str(dest),
                 files=sorted(p.name for p in dest.iterdir()))
        note(event="done", shots=str(out / "shots"))
    finally:
        # **A specimen dies with the emulator slot that made it**
        # (`.claude/rules/testing.md`), so the shots come out however the
        # run ended.  One `TimeoutError` at a menu used to take six
        # character sheets and a walk with it.
        try:
            shots = out / "shots"
            shots.mkdir(parents=True, exist_ok=True)
            for png in sorted((session.dir / "shots").glob("*.png")):
                shutil.copy(png, shots / png.name)
        except OSError as e:
            print(f"could not keep the shots: {e}", file=sys.stderr)
        session.close()
        slot.release()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--game", default="CURSE", help="the game directory stem")
    ap.add_argument("--container",
                    help="a specimen directory holding SAVGAM<from-slot>.DAT")
    ap.add_argument("--records",
                    help="a directory of CHRDAT* files to install")
    ap.add_argument("--save",
                    help="a whole save this project wrote -- SAVGAM and "
                         "CHRDAT files together -- installed instead of "
                         "--container and --records (#299)")
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
    ap.add_argument("--sheet-open", default="",
                    help="Silver Blades and anything else whose party menu "
                         "is a highlight list rather than letter keys: the "
                         "keys that take the *first* character's sheet from "
                         "the party menu, comma separated. Given, this "
                         "replaces --advance/--view entirely")
    ap.add_argument("--sheet-reopen", default="",
                    help="the same for the second and later characters, when "
                         "leaving a sheet does not put the menu highlight "
                         "back where it started (default: --sheet-open)")
    ap.add_argument("--pick-down", default="Down",
                    help="the key that moves the character picker on by one")
    ap.add_argument("--pick-select", default="Return",
                    help="the key that opens the picked character's sheet")
    ap.add_argument("--walk", type=int, default=0,
                    help="steps to walk after the sheets, before --resave, "
                         "so the save is proven to be a game rather than a "
                         "file that loads")
    ap.add_argument("--begin", default="b",
                    help="the BEGIN ADVENTURING keys, comma separated, "
                         "pressed before the walk")
    ap.add_argument("--move-mode", default="",
                    help="Silver Blades: the MOVE key that puts the party "
                         "into movement mode, without which the arrow keys "
                         "do nothing at all in a dungeon")
    ap.add_argument("--move-exit", default="Escape",
                    help="the key that leaves movement mode again")
    ap.add_argument("--engine-save", default="",
                    help="have the game's own ENCAMP > SAVE write the party "
                         "back to this slot letter after the walk")
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
    args = ap.parse_args(argv)
    if not args.save and not (args.container and args.records):
        ap.error("give --save, or both --container and --records")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
