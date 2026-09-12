#!/usr/bin/env python3
"""Walk a DOS Pool of Radiance party into one of New Phlan's four shops, and
buy something in the game's own shop screen.

`#249 (Build a DOS party from creation and level it ourselves, so DOS
measurements rest on records we watched being written)` step 4 wants a
**shopped** character: one whose items the engine put in the record, so that
`#323 (The encumbrance identity does not survive the training fee, so failing
it is not evidence of an edited record)` can ask whether buying an item makes
the engine recompute stored encumbrance.  The training ladder answered the
other half -- 42 trainings took 1000 gp each and never touched the field.

**Where the shops are, and how that was found.**  New Phlan is area 0 and its
script is `ECL00`, whose `ONGOTO` dispatches twenty-eight arms on the square's
own script id (`GEO00`'s attribute byte).  Four of those arms end in the same
five statements:

    TREASURE 0,0,0,0,0,0,0,<shop>
    SAVE 1, [$6E6C]        the "a shop instead of a fight" side channel
    SAVE 1, [$6EF6]
    SAVE 16, [$6E6D]
    COMBAT

`docs/128-guide-and-scripting.md` names `$6E6C` in `$24 COMBAT`'s side
channel, so a shop is the combat opcode entered with that byte set and the
stock preloaded by `TREASURE`.  Arms 19, 21, 22 and 23 are the four, carrying
shop ids 54, 52, 53 and 55.  `--map` re-derives all of it from the player's
own files and prints it, on both ports, with no emulator.

    tools/dosshop.py --map
    tools/dosshop.py --party $WISH_SPECIMENS/por-dos/WISH-SPEC-por-party-l1-intown \\
        --shop 53 --interactive --cmd work/issue249/shop/cmd.txt
    tools/dosshop.py --party ... --shop 53 --steps Up '~4' y '~3' --save-to F

**The party is put down one square short and walks the last one**, the same as
the training hall: `ECL00` dispatches on the *departing* square's attribute
byte, so a save dropped on the shop's own square and stepped off fires
nothing.  `--shop` picks the approach square and the facing out of the table
below; nothing else about the save is touched, so a run on
`WISH-SPEC-por-party-l1-intown` buys with the gold the engine rolled.

Output goes under `work/`, which is gitignored and has been lost twice.
**Copy anything you mean to keep into `$WISH_SPECIMENS` with
`tools/specimens.py add` before the slot goes down.**
"""

from __future__ import annotations

import argparse
import atexit
import pathlib
import re
import shutil
import signal
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automap import maps  # noqa: E402
from goldbox import dos_codec  # noqa: E402
from goldbox.dos_savegame import dax_block  # noqa: E402
from goldbox.geo import Geo  # noqa: E402
from tools import dosbox  # noqa: E402
from tools.dosparty import wipe_roster  # noqa: E402
from tools.dostrain import Runner, collect, move_to, snapshot  # noqa: E402
from tools.dostrainprobe import install  # noqa: E402

#: Where a `ECL` script is loaded on the C64, `docs/140-loaded-files-cache.md`
#: slot 8.  The DOS block carries two bytes in front of the same code, so its
#: base is two lower; `ecl_base` measures that rather than assuming it.
SCRIPT_BASE = 0x9900

#: New Phlan's four shops.  Key is the square's `GEO00` script id, which is
#: the `ONGOTO` arm `ECL00` runs; `shop` is the id its `TREASURE` preloads.
#: `squares` are every square carrying that id -- a shopfront is a run of
#: them -- and `approach` is an inert square one step away with the facing
#: that walks in.  Derived by `shop_arms()` and `check_shops()` re-derives it.
SHOPS: dict[int, dict] = {
    19: {"shop": 54,
         "squares": [(15, 8), (9, 10), (12, 10), (9, 11), (11, 11)],
         "approach": ((9, 12), "N", (9, 11))},
    21: {"shop": 52,
         "squares": [(8, 10)],
         "approach": ((9, 10), "W", (8, 10))},
    22: {"shop": 53,
         "squares": [(13, 8), (8, 11), (11, 12), (8, 13), (9, 13)],
         "approach": ((7, 11), "E", (8, 11))},
    23: {"shop": 55,
         "squares": [(11, 10), (10, 13)],
         "approach": ((11, 9), "S", (11, 10))},
}

#: Which `.DAX` container holds area 0's map and script in the DOS build, and
#: which block id inside it.  Both are `--map`'s to check, not to assume.
DOS_GEO_DAX, DOS_ECL_DAX, AREA0 = "GEO3.DAX", "ECL3.DAX", 0

#: `SAVE 1, [$6E6C]` -- the statement that follows a shop's `TREASURE`.  Both
#: ports name the same script variable, so this is the same bytes on each.
SHOP_CHANNEL = bytes((0x09, 0x00, 0x01, 0x01, 0x6C, 0x6E))
#: `TREASURE 0,0,0,0,0,0,0,<shop>` -- opcode `$27`, eight one-byte immediates,
#: each a `$00` kind byte and its value.  The shop id is the last of them.
TREASURE_SHOP = re.compile(rb"\x27(?:\x00\x00){7}\x00(.)", re.S)
#: `ONGOTO [$9800], 28, ...` -- opcode `$25`, the variable, the count, then
#: that many address operands of three bytes each.
ONGOTO_28 = bytes((0x25, 0x01, 0x00, 0x98, 0x00, 0x1C))
ARMS = 28


def geo00_c64() -> Geo:
    """New Phlan's map off the player's own C64 disks."""
    found = maps.load_maps()
    if "GEO00" not in found:
        raise SystemExit("no GEO00 on the disks -- set POR_DISKS")
    return found["GEO00"]


def geo00_dos(game: pathlib.Path) -> Geo:
    """The same map out of the DOS build's own `GEO3.DAX`."""
    data = (game / DOS_GEO_DAX).read_bytes()
    return Geo.from_bytes(dax_block(data, AREA0, DOS_GEO_DAX))


def ecl00_dos(game: pathlib.Path) -> bytes:
    """Area 0's script out of the DOS build's own `ECL3.DAX`."""
    data = (game / DOS_ECL_DAX).read_bytes()
    return dax_block(data, AREA0, DOS_ECL_DAX)


def ecl_base(script: bytes) -> int:
    """What to add to a file offset in `script` to get a script address.

    Every area script opens with five `GOTO`s, each `$01` and one address
    operand, and the first of them is at `SCRIPT_BASE`.  The DOS block carries
    two bytes in front of that, so measuring is a byte cheaper than a comment
    explaining why the constant is two lower than the C64's.
    """
    for start in range(0, 8):
        run = script[start:start + 20]
        if all(run[4 * i:4 * i + 2] == b"\x01\x01" for i in range(5)):
            return SCRIPT_BASE - start
    raise ValueError("no five-GOTO opener: not an area script")


def arm_table(script: bytes) -> list[int]:
    """The addresses `ECL00`'s twenty-eight-way `ONGOTO` jumps to."""
    at = script.find(ONGOTO_28)
    if at < 0:
        raise ValueError("no 28-way ONGOTO: not New Phlan's script")
    body = script[at + len(ONGOTO_28):]
    return [body[3 * k + 1] | (body[3 * k + 2] << 8) for k in range(ARMS)]


def shop_arms(script: bytes) -> dict[int, int]:
    """Which `ONGOTO` arms are shops, and which shop id each preloads.

    A shop arm is one whose statements include `TREASURE` with a shop id and
    then the `$6E6C` side channel.  Returns `{arm: shop id}`, and the arm is
    the square's `GEO00` script id.
    """
    base = ecl_base(script)
    arms = arm_table(script)
    found: dict[int, int] = {}
    for m in TREASURE_SHOP.finditer(script):
        if script[m.end():m.end() + len(SHOP_CHANNEL)] != SHOP_CHANNEL:
            continue
        where = m.start() + base
        before = [k for k, a in enumerate(arms) if a <= where]
        if before:
            found[max(before, key=lambda k: arms[k])] = m.group(1)[0]
    return dict(sorted(found.items()))


def check_shops(geo: Geo) -> list[str]:
    """Compare `SHOPS` against a `GEO00`, and report the disagreements.

    An empty list is a free corroboration of every square a run walks to.
    Anything in it means the map being routed over is not the map this table
    was written against, and the run should stop rather than walk into a wall.
    """
    bad = []
    for script_id, shop in SHOPS.items():
        for square in shop["squares"]:
            got = geo.script_id(*square)
            if got != script_id:
                bad.append(f"{square} script {got}, expected {script_id}")
        here, facing, target = shop["approach"]
        if geo.script_id(*here) not in (0, *SHOPS):
            bad.append(f"approach {here} is script {geo.script_id(*here)}")
        if target not in shop["squares"]:
            bad.append(f"approach {here} faces {target}, not a shop square")
        direction = "NESW".index(facing)
        if not geo.is_passable(here[0], here[1], direction):
            bad.append(f"approach {here} cannot step {facing}")
    return bad


def by_shop(shop_id: int) -> tuple[int, dict]:
    """The table row for a shop id, e.g. 53."""
    for script_id, row in SHOPS.items():
        if row["shop"] == shop_id:
            return script_id, row
    raise SystemExit(f"no shop {shop_id}; known: "
                     f"{sorted(r['shop'] for r in SHOPS.values())}")


#: `goldbox.dos_port`'s stored encumbrance, quoted here so the poke says
#: what it is.
ENCUMBRANCE_AT = 0x102


def stage_encumbrance(save_dir: pathlib.Path, letter: str, value: int) -> None:
    """Write `value` into every installed record's stored encumbrance.

    **An input, and it proves nothing on its own.**  It is here to spoil the
    field with a number the engine's own arithmetic cannot produce, so that a
    record coming back holding the right sum is the engine having recomputed
    it rather than the engine having left our staging alone -- which is what
    a run staged at the correct value could never tell apart.

    **It has to run before `session.boot()`, or it proves nothing at all.**
    `#429 (tools/dosshop.py stages its spoiled encumbrance after the load, so
    the engine never reads it)` was this call landing after `open_loaded` had
    already booted DOSBox and pressed `LOAD SAVED GAME`: the engine had the
    record in memory before the poke touched the file, so its own save wrote
    the untouched value back and a run that came back "correct" had measured
    nothing.  `open_loaded_spoiled` is the caller that gets the order right.
    """
    for path in sorted(save_dir.glob(f"CHRDAT{letter.upper()}?.SAV")):
        data = bytearray(path.read_bytes())
        data[ENCUMBRANCE_AT:ENCUMBRANCE_AT + 2] = \
            int(value).to_bytes(2, "little")
        path.write_bytes(bytes(data))


def open_loaded_spoiled(party: pathlib.Path, out: pathlib.Path, letter: str,
                        xp: int | None, gold: int | None, at: str | None,
                        encumbrance: int | None
                        ) -> tuple[dosbox.Session, dosbox.Slot]:
    """Stage, install, spoil encumbrance, then boot and LOAD SAVED GAME it.

    `tools.dostrain.open_loaded` with the one line `#429` found out of order:
    the encumbrance poke happens here **before** `session.boot()`, the same
    place `tools/dosencsave.open_spoiled` puts it, so the engine actually
    reads what was staged instead of overwriting it on its own save.
    """
    out.mkdir(parents=True, exist_ok=True)
    slot = dosbox.claim("issue249 shop, encumbrance staged before boot")
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
    install(party, session.save_dir, letter, None, xp, gold)
    if at:
        move_to(session.save_dir / f"SAVGAM{letter.upper()}.DAT", at)
    if encumbrance is not None:
        stage_encumbrance(session.save_dir, letter, encumbrance)
        print(f"staged encumbrance {encumbrance} into every record "
              f"BEFORE the boot (0x{ENCUMBRANCE_AT:03X})", flush=True)
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


def identity(folder: pathlib.Path) -> list[str]:
    """Stored encumbrance against `gold + sum(weight x quantity)`, per record.

    This is the whole point of a shopped specimen: the training ladder proved
    the engine leaves the field alone when it takes a fee, and what nobody has
    measured is whether it recomputes when an item arrives.
    """
    lines = []
    for path in sorted(folder.glob("CHRDAT*.SAV")):
        c = dos_codec.read_character(path)
        stored, want = c.get("encumbrance"), c.expected_encumbrance()
        mark = "ok" if stored == want else f"{stored - want:+d}"
        purse = " ".join(f"{k}={v}" for k, v in c.money.items() if v)
        lines.append(f"{path.name} {c.name:8s} "
                     f"coins={sum(c.money.values()):6d} "
                     f"items={c.get('item_count'):2d} stored={stored:6d} "
                     f"computed={want:6d} {mark}  [{purse}]")
        for it in c.items:
            lines.append(f"    item type={it.get('type_index'):3d} "
                         f"weight={it.get('weight'):5d} "
                         f"quantity={it.get('quantity'):3d} "
                         f"value={it.get('value'):5d} "
                         f"readied={it.get('readied')}")
    return lines


def show_map(game: pathlib.Path | None) -> int:
    """Print the shop table, re-derived from the player's own files."""
    c64 = geo00_c64()
    print(f"C64 GEO00: {len(c64.to_bytes())} bytes")
    bad = check_shops(c64)
    print("C64 GEO00 agrees with SHOPS" if not bad
          else "C64 GEO00 disagrees: " + "; ".join(bad))
    if game is not None and (game / DOS_GEO_DAX).exists():
        dosgeo = geo00_dos(game)
        same = dosgeo.to_bytes() == c64.to_bytes()
        print(f"DOS {DOS_GEO_DAX} block {AREA0}: "
              f"{'byte-identical to the C64 GEO00' if same else 'DIFFERENT'}")
        bad = check_shops(dosgeo)
        print("DOS GEO00 agrees with SHOPS" if not bad
              else "DOS GEO00 disagrees: " + "; ".join(bad))
        arms = shop_arms(ecl00_dos(game))
        print(f"DOS {DOS_ECL_DAX} block {AREA0}: shop arms {arms}")
        want = {k: v["shop"] for k, v in SHOPS.items()}
        print("the script agrees with SHOPS" if arms == want
              else f"the script disagrees: expected {want}")
    print()
    print(" shop  script id  squares                              approach")
    for script_id, row in sorted(SHOPS.items(), key=lambda kv: kv[1]["shop"]):
        here, facing, target = row["approach"]
        squares = " ".join(f"({x},{y})" for x, y in row["squares"])
        print(f"  {row['shop']:3d}  {script_id:9d}  {squares:36s}  "
              f"{here} facing {facing} -> {target}")
    return 0


def drive(args: argparse.Namespace) -> int:
    """Boot, load the party one square from the shop, and run the steps."""
    script_id, row = by_shop(args.shop)
    here, facing, target = row["approach"]
    geo = geo00_c64()
    bad = check_shops(geo)
    if bad:
        raise SystemExit("GEO00 disagrees with the shop table: "
                         + "; ".join(bad))
    at = f"{here[0]},{here[1]},{facing}"
    print(f"shop {args.shop} is script id {script_id} at {target}; "
          f"starting at {at}", flush=True)
    out = args.out
    session, slot = open_loaded_spoiled(args.party, out, args.slot,
                                        args.xp, args.gold, at,
                                        args.encumbrance)
    runner = Runner(session, out)
    try:
        snapshot(session, out, "before")
        if args.interactive:
            interactive(session, runner, out, args.cmd, args.gap)
        for step in args.steps or []:
            print(f"{step:14s} {runner.step(step, args.gap)}", flush=True)
        if args.save_to:
            game = dosbox.PoolOfRadiance(session)
            data = game.save_game(args.save_to)
            print(f"saved {len(data)} bytes to slot {args.save_to}", flush=True)
            session.shot("999-saved", allow_blank=True)
        snapshot(session, out, "after")
        collect(session, out)
    finally:
        session.close()
        slot.release()
    for tag in ("before", "after"):
        print(f"-- {tag}")
        for line in identity(out / "snaps" / tag):
            print(" ", line)
    print("shots in", out / "shots", flush=True)
    return 0


def interactive(session: dosbox.Session, runner: Runner, out: pathlib.Path,
                cmd: pathlib.Path, gap: float, idle: float = 900.0) -> None:
    """Run step lines as they are appended to `cmd`, so one boot maps many
    screens.

    The shop screens are unmapped and a boot costs about a minute, which is
    the same arithmetic `tools/dosgnome.py` made for the creation screens.
    Lines already in the file are run first, so a run can be scripted and then
    continued by hand.  `--quit` on a line of its own ends it.
    """
    cmd.parent.mkdir(parents=True, exist_ok=True)
    if not cmd.exists():
        cmd.write_text("")
    done, last = 0, time.time()
    while time.time() - last < idle:
        lines = [ln.strip() for ln in cmd.read_text().splitlines()]
        lines = [ln for ln in lines if ln and not ln.startswith(";")]
        if done >= len(lines):
            time.sleep(1.0)
            continue
        step = lines[done]
        last = time.time()
        if step == "--quit":
            print("quit", flush=True)
            return
        if step == "--report":
            snapshot(session, out, f"live{done:02d}")
            for line in identity(out / "snaps" / f"live{done:02d}"):
                print("  ", line, flush=True)
            done += 1
            continue
        print(f"{done:02d} {step:14s} {runner.step(step, gap)}", flush=True)
        shots = out / "shots"
        shots.mkdir(parents=True, exist_ok=True)
        for png in sorted((session.dir / "shots").glob("*.png")):
            shutil.copy(png, shots / png.name)
        done += 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--map", action="store_true",
                    help="print the shop table and check it, no emulator")
    ap.add_argument("--party", type=pathlib.Path,
                    help="a specimen directory holding SAVGAM*.DAT and CHRDAT*")
    ap.add_argument("--shop", type=int, default=53,
                    help="which shop id to walk into: 52, 53, 54 or 55")
    ap.add_argument("--out", type=pathlib.Path,
                    default=REPO / "work" / "issue249" / "shop" / "run")
    ap.add_argument("--slot", default="E", help="which letter to install as")
    ap.add_argument("--xp", type=lambda s: int(s, 0), default=None)
    ap.add_argument("--gold", type=lambda s: int(s, 0), default=None,
                    help="gold to write into every record before the boot; "
                         "omit it and the party shops with what it rolled")
    ap.add_argument("--encumbrance", type=lambda s: int(s, 0), default=None,
                    help="spoil stored encumbrance in every record before the "
                         "boot, so a right answer afterwards is a recompute")
    ap.add_argument("--gap", type=float, default=1.0)
    ap.add_argument("--steps", nargs="*", default=None)
    ap.add_argument("--interactive", action="store_true",
                    help="run step lines appended to --cmd, one boot, many "
                         "screens")
    ap.add_argument("--cmd", type=pathlib.Path,
                    default=REPO / "work" / "issue249" / "shop" / "cmd.txt")
    ap.add_argument("--save-to", default=None,
                    help="after the steps, ENCAMP > SAVE to this slot letter")
    args = ap.parse_args(argv)
    if args.map:
        try:
            game = dosbox.find_game()
        except Exception:                              # pragma: no cover
            game = None
        return show_map(game)
    if not args.party:
        ap.error("--party is required unless --map")
    return drive(args)


if __name__ == "__main__":
    raise SystemExit(main())
