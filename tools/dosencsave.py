#!/usr/bin/env python3
"""Ask which screen, if any, makes DOS Pool of Radiance rewrite a character's
stored encumbrance -- with the spoiled value in the file **before the boot**,
so the engine actually reads it.

`#323 (The encumbrance identity does not survive the training fee, so failing
it is not evidence of an edited record)` had two measurements that could not
both be read the way they were written:

* the training ladder, where nine load-and-save cycles left a stored total up
  to 11,000 above the purse and the engine never corrected it;
* `docs/213-the-dos-shopping-trip.md`'s control, where a spoiled 999 came back
  as the right sum after an ordinary camp save with no shop and no trainer.

**They differ in when the spoiled value reached the file.**
`tools/dosshop.py --encumbrance` writes it *after* `open_loaded` has already
booted the game and pressed `LOAD SAVED GAME`, so the engine had the party in
memory before the poke landed and its save wrote its own numbers back over it.
This tool writes the poke between `install` and `boot`, which is the only
order in which a value coming back changed says the engine changed it.

Three modes, and the first two need no emulator:

    tools/dosencsave.py --rungs $WISH_SPECIMENS/por-dos/WISH-SPEC-por-party-ladder-rung*
    tools/dosencsave.py --boots work/issue249/ladder*/rung* work/issue249/thresh/rung*
    tools/dosencsave.py --party $WISH_SPECIMENS/por-dos/WISH-SPEC-por-party-ladder-rung1 \\
        --spoil 999 --menu-save A --camp-save B --view-save D

`--rungs` re-runs `tools/dostrainprobe.install`'s own arithmetic over a chain
of ladder specimens.  **Staging gold moves stored encumbrance with it**, so a
rung's input is balanced before the boot and the drift the ladder shows is one
1000 gp fee per boot plus our own restaging, not an engine that adds 1000.

`--boots` reads a driven run's `before/` and `after/` snapshots and reports
what moved inside one boot, per slot letter.  That is the differential the
ladder actually made: the trainer takes the coins and the record the engine
saves afterwards still holds the number it was loaded with.

The driving mode boots once and takes up to three saves off one spoiled load:
a `SAVE CURRENT GAME` straight off the party menu, a camp save from the map,
and a save after `VIEW`.  Order matters -- the first save that recomputes
destroys the spoiled value for every test after it, so the cheapest screens go
first and a later save is only evidence while the value is still spoiled.

Output goes under `work/`, which is gitignored and has been lost twice.
**Copy anything you mean to keep into `$WISH_SPECIMENS` with
`tools/specimens.py add` before the slot goes down.**
"""

from __future__ import annotations

import argparse
import atexit
import pathlib
import shutil
import signal
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from goldbox import dos_codec  # noqa: E402
from tools import dosbox  # noqa: E402
from tools.dosparty import wipe_roster  # noqa: E402
from tools.dosshop import ENCUMBRANCE_AT, stage_encumbrance  # noqa: E402
from tools.dostrainprobe import install  # noqa: E402

#: What every ladder rung was restaged to, `tools/dosladder.py --gold`.
LADDER_GOLD = 20000


def read(folder: pathlib.Path, letter: str | None = None
         ) -> list[tuple[str, str, int, int, int, int]]:
    """Every record in `folder`: name, coins, stored, computed, items."""
    pat = f"CHRDAT{letter.upper()}?.SAV" if letter else "CHRDAT*.SAV"
    out = []
    for p in sorted(folder.glob(pat)):
        c = dos_codec.read_character(p)
        out.append((p.name, c.name.strip(), sum(c.money.values()),
                    c.get("encumbrance"), c.expected_encumbrance(),
                    c.get("item_count")))
    return out


def show(rows: list[tuple[str, str, int, int, int, int]], indent: str = "  ") -> None:
    for name, who, coins, stored, want, items in rows:
        mark = "ok" if stored == want else f"{stored - want:+d}"
        print(f"{indent}{name} {who:8s} coins={coins:6d} items={items:2d} "
              f"stored={stored:6d} computed={want:6d} {mark}")


def rungs(dirs: list[pathlib.Path]) -> int:
    """Does `install`'s gold poke account for the ladder's climbing total?

    `tools/dostrainprobe.install` writes `enc - was + gold` when it restages
    gold, so a rung whose party came out of the last boot holding 19,000 has
    1000 added to its stored encumbrance before the next boot starts.  The
    prediction is exact: the next rung's saved total is the previous rung's
    plus whatever gold the restaging put back.  Where it holds, the climb is
    ours and the engine only ever contributed the single fee of that boot.
    """
    chain: dict[str, list[tuple[int, int, int]]] = {}
    for n, d in enumerate(dirs):
        for _, who, coins, stored, want, _ in read(d):
            chain.setdefault(who, []).append((n, coins, stored))
        print(f"-- {d.name}")
        show(read(d))
    print()
    match = differ = 0
    for who, seen in sorted(chain.items()):
        for (n, coins, stored), (m, _, nxt) in zip(seen, seen[1:]):
            staged = stored + (LADDER_GOLD - coins)
            ok = staged == nxt
            match += ok
            differ += not ok
            print(f"{who:8s} {dirs[n].name} stored={stored:6d} coins={coins:6d}"
                  f" -> restaged {staged:6d}; {dirs[m].name} holds {nxt:6d}"
                  f"  {'MATCH' if ok else 'DIFFER'}")
    print(f"\n{match} of {match + differ} transitions are our own restaging "
          f"plus one fee; {differ} are not")
    return 0


def boots(dirs: list[pathlib.Path]) -> int:
    """What moved inside one boot, reading a run's `before/` and `after/`.

    `before/` is the staged party as the boot started and `after/` holds every
    slot the run saved, so a character appears once per save letter.  The
    question this answers is the only one a ladder rung can answer: between
    the trainer taking the fee and `SAVE CURRENT GAME` writing the record, did
    anything touch stored encumbrance?
    """
    moved = held = paid = 0
    for d in dirs:
        b, a = d / "before", d / "after"
        if not (b.is_dir() and a.is_dir()):
            continue
        was = {who: (coins, stored) for _, who, coins, stored, _, _ in read(b)}
        print(f"-- {d}")
        for name, who, coins, stored, want, _ in read(a):
            if who not in was:
                continue
            wc, ws = was[who]
            tag = ("stored moved" if ws != stored else "stored held")
            if ws != stored:
                moved += 1
            else:
                held += 1
            paid += wc != coins
            print(f"   {name} {who:8s} coins {wc:6d} -> {coins:6d}   "
                  f"stored {ws:6d} -> {stored:6d}   computed {want:6d}   {tag}")
    print(f"\n{held} records saved inside a boot held the stored value they "
          f"were loaded with; {moved} moved")
    print(f"{paid} of them had coins taken off them inside that same boot")
    return 0


def open_spoiled(party: pathlib.Path, out: pathlib.Path, letter: str,
                 spoil: int | None) -> tuple[dosbox.Session, dosbox.Slot]:
    """Stage the party, spoil the field, **then** boot and load it.

    This is `tools/dostrain.open_loaded` with one line moved, and the moved
    line is the whole experiment: `tools/dosshop.py --encumbrance` pokes the
    records after the game has loaded them, so the engine never reads the
    poke and its own save writes the in-memory value back.  Nothing is staged
    but the encumbrance -- no experience, no gold -- so the record loads
    exactly as its own last save left it, one field apart.
    """
    out.mkdir(parents=True, exist_ok=True)
    slot = dosbox.claim("issue323 encumbrance save path")
    session = dosbox.Session(slot, dosbox.find_game())

    def cleanup(*_: object) -> None:
        session.close()
        slot.release()

    atexit.register(cleanup)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    session.stage(fresh=True)
    shutil.rmtree(session.dir / "shots", ignore_errors=True)
    (session.dir / "shots").mkdir(parents=True, exist_ok=True)
    wipe_roster(session.save_dir)
    install(party, session.save_dir, letter, None, None, None)
    if spoil is not None:
        stage_encumbrance(session.save_dir, letter, spoil)
        print(f"staged encumbrance {spoil} into every record "
              f"BEFORE the boot (0x{ENCUMBRANCE_AT:03X})", flush=True)
    snap(session, out, "staged")
    session.boot(fresh=False)
    dosbox.PoolOfRadiance(session).to_main_menu()
    session.key("l")
    time.sleep(1.0)
    session.settle(quiet=0.5, timeout=15.0)
    session.key(letter.lower())
    time.sleep(4.0)
    session.settle(quiet=0.8, timeout=60.0)
    session.shot("000-loaded")
    return session, slot


def snap(session: dosbox.Session, out: pathlib.Path, tag: str) -> pathlib.Path:
    d = out / "snaps" / tag
    d.mkdir(parents=True, exist_ok=True)
    for p in sorted(session.save_dir.iterdir()):
        if p.name.upper() == "EXPLORED.DAT" or p.is_dir():
            continue
        shutil.copy(p, d / p.name)
    return d


def menu_save(session: dosbox.Session, letter: str, timeout: float = 60.0
              ) -> bool:
    """`SAVE CURRENT GAME` from the party menu, the ladder's own save path.

    Verified by effect: the save is not believed until `SAVGAM<letter>.DAT`
    changes on disk, and `settle_files` waits for the six records, which land
    milliseconds after the container.
    """
    path = session.save_file(letter)
    was = path.read_bytes() if path.is_file() else None
    session.key("s")
    time.sleep(1.0)
    session.settle(quiet=0.5, timeout=20.0)
    session.shot(f"menu-save-{letter}-list", allow_blank=True)
    session.key(letter.lower())
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.is_file() and path.read_bytes() != was:
            dosbox.settle_files(session.save_dir, timeout=20.0)
            session.shot(f"menu-save-{letter}-done", allow_blank=True)
            return True
        time.sleep(0.3)
    session.shot(f"menu-save-{letter}-failed", allow_blank=True)
    return False


def to_map(session: dosbox.Session, game: dosbox.PoolOfRadiance,
           tries: int = 4) -> str | None:
    """`BEGIN ADVENTURING` until the command bar is the map's."""
    before = game.bar()
    for _ in range(tries):
        session.key("b")
        time.sleep(1.0)
        session.settle(quiet=0.5, timeout=20.0)
        now = game.bar()
        session.shot("begin-adventuring", allow_blank=True)
        if now != before:
            return now
    return None


def drive(args: argparse.Namespace) -> int:
    out = args.out
    session, slot = open_spoiled(args.party, out, args.slot, args.spoil)
    game = dosbox.PoolOfRadiance(session)
    results: list[tuple[str, str, pathlib.Path]] = []
    try:
        if args.menu_save:
            ok = menu_save(session, args.menu_save)
            print(f"party-menu SAVE CURRENT GAME to {args.menu_save}: "
                  f"{'written' if ok else 'FAILED'}", flush=True)
            if ok:
                results.append(("party menu, where the load left us",
                                args.menu_save,
                                snap(session, out, f"menu-{args.menu_save}")))
        if args.camp_save:
            bar = to_map(session, game)
            print(f"BEGIN ADVENTURING: {'on the map' if bar else 'FAILED'}",
                  flush=True)
            if bar:
                game.world_bar = bar
                game.save_game(args.camp_save)
                print(f"camp ENCAMP > SAVE to {args.camp_save}: written",
                      flush=True)
                results.append(("camp, from the map", args.camp_save,
                                snap(session, out, f"camp-{args.camp_save}")))
        if args.view_save:
            # **The party has to be on the map first**, and after a camp save
            # it already is -- `BEGIN ADVENTURING` there changes no bar, and
            # waiting for one to change is what lost the first run's `VIEW`.
            world = game.world_bar or to_map(session, game) or game.bar()
            game.world_bar = world
            session.key("v")
            time.sleep(1.5)
            session.settle(quiet=0.5, timeout=20.0)
            session.shot("view-sheet", allow_blank=True)
            for _ in range(4):
                session.key("Escape")
                time.sleep(1.0)
                session.settle(quiet=0.5, timeout=20.0)
                if game.bar() == world:
                    break
            session.shot("view-left", allow_blank=True)
            game.save_game(args.view_save)
            print(f"camp save after VIEW to {args.view_save}: written",
                  flush=True)
            results.append(("after VIEW drew a sheet", args.view_save,
                            snap(session, out, f"view-{args.view_save}")))
    finally:
        shots = out / "shots"
        shots.mkdir(parents=True, exist_ok=True)
        for png in sorted((session.dir / "shots").glob("*.png")):
            shutil.copy(png, shots / png.name)
        session.close()
        slot.release()
    print(f"\n-- staged, before the boot (slot {args.slot})")
    show(read(out / "snaps" / "staged", args.slot))
    for what, letter, folder in results:
        print(f"-- saved to {letter}: {what}")
        show(read(folder, letter))
    print("\nshots in", out / "shots", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rungs", nargs="*", type=pathlib.Path,
                    help="ladder specimen directories, in order: check the "
                         "climb against install's own gold arithmetic")
    ap.add_argument("--boots", nargs="*", type=pathlib.Path,
                    help="driven run directories holding before/ and after/")
    ap.add_argument("--party", type=pathlib.Path,
                    help="a specimen directory holding SAVGAM*.DAT and CHRDAT*")
    ap.add_argument("--slot", default="E",
                    help="the letter the party is already installed under; a "
                         "different one renames the files out from under the "
                         "names in SAVGAM's party table")
    ap.add_argument("--spoil", type=lambda s: int(s, 0), default=999,
                    help="stored encumbrance to write before the boot")
    ap.add_argument("--menu-save", default=None,
                    help="slot letter for a SAVE CURRENT GAME off the party "
                         "menu, taken before anything else happens")
    ap.add_argument("--camp-save", default=None,
                    help="slot letter for ENCAMP > SAVE from the map")
    ap.add_argument("--view-save", default=None,
                    help="slot letter for a camp save after VIEW drew a sheet")
    ap.add_argument("--out", type=pathlib.Path,
                    default=REPO / "work" / "issue323" / "savepath")
    args = ap.parse_args(argv)
    if args.rungs:
        return rungs(list(args.rungs))
    if args.boots:
        return boots(list(args.boots))
    if not args.party:
        ap.error("one of --rungs, --boots or --party is required")
    return drive(args)


if __name__ == "__main__":
    raise SystemExit(main())
