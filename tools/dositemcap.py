#!/usr/bin/env python3
"""Prove DOS Pool of Radiance's sixteen-item ceiling in the running game.

`#52 (File ▸ Import and File ▸ Export for every direction the library
supports)` decision 13 asks what a conversion does when the destination has
no room, and named "seventeen items" as one of the cases.  Reading each
title's `GAME.OVR` says the case cannot arise -- every DOS Gold Box title
refuses a character a seventeenth item -- and this is the half of that claim
that runs.

**The experiment is a boundary, taken one action apart on one character.**
Three characters of an engine-written party are given item lists of 2, 15 and
16 by writing their `.ITM` files; then, from the first character's item
screen, the same item is offered by `TRADE` to a character holding 15 and to
a character holding 16.  The engine's answer to the second is the word
`Overloaded`, and after the 15-item character accepts one it refuses the next
-- so the only thing that changed between the acceptance and the refusal is
that its own count reached sixteen.

**Weight is kept out of it deliberately.**  The refusal routine sets one flag
from two tests, the item count *and* `encumbrance + weight x quantity`
against carrying capacity plus 1500, so a heavy inventory would prove
nothing about the count.  Every item this installs is the game's own `Sling`
template out of `ITEM1.DAX` at two tenths of a pound, sixteen of which weigh
3.2 lb against a limit no character is within 1500 units of.  The control --
the same item accepted by the 15-item character in the same breath -- is what
shows the weight branch never fires.

The item records are the game's own template bytes and the party is
`WISH-SPEC-por-party-l1-intown`, which the engine wrote; what this tool
supplies is the *input* (which items, how many), and what it measures is the
engine's answer.  `.claude/rules/testing.md` is the distinction.

    tools/dositemcap.py --interactive          # boot, then read step lines
    tools/dositemcap.py --counts 2,15,16       # install and boot only

Steps are `tools/dosgnome.py`'s vocabulary: a bare X keysym is a keypress,
`#text` types text, `~N` waits, `!tag` snapshots `SAVE/`.
"""

from __future__ import annotations

import argparse
import atexit
import pathlib
import shutil
import signal
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import dos_layout as dl  # noqa: E402
from goldbox.dos_savegame import dax_block  # noqa: E402
from tools import dosbox  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent.parent / "work" / "issue52-items"

#: The specimen this stands on: six characters rolled from creation under
#: `#249 (Build a DOS party from creation and level it ourselves, so DOS
#: measurements rest on records we watched being written)`, saved by the
#: game's own SAVE CURRENT GAME into slot E with the party in New Phlan.
SPECIMEN = "WISH-SPEC-por-party-l1-intown"
SLOT = "E"

#: `ITEM1.DAX` block 53 is the shop stock, 57 item records of 63 bytes.  Entry
#: 12 is `Sling`, weight 2 (0.2 lb) and quantity 0, which is the lightest
#: single item in the block.
ITEM_DAX, ITEM_BLOCK, SLING = "ITEM1.DAX", 53, 12


def specimen_dir(name: str = SPECIMEN) -> pathlib.Path:
    """Where the specimen tree keeps `name`.

    `$WISH_SPECIMENS` then `~/wish-specimens`, the same rule
    `tools/specimens.py` uses, searched one level down because the tree is
    grouped by title and port.
    """
    import os
    root = pathlib.Path(os.environ.get("WISH_SPECIMENS",
                                       pathlib.Path.home() / "wish-specimens"))
    for candidate in [root / name] + sorted(root.glob(f"*/{name}")):
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(f"{name} is not in {root}")


def sling(game: pathlib.Path) -> bytes:
    """One 63-byte `Sling` record, read out of the game's own item table."""
    block = dax_block((game / ITEM_DAX).read_bytes(), ITEM_BLOCK, ITEM_DAX)
    return block[SLING * dosbox.ITEM_SIZE:(SLING + 1) * dosbox.ITEM_SIZE]


def install(save_dir: pathlib.Path, game: pathlib.Path,
            counts: list[int]) -> list[tuple[str, int, int]]:
    """Copy the specimen into `save_dir` and give character *n* `counts[n]`
    slings.  Returns one row per character: name, count, stored encumbrance.

    Three bytes of the record are written: `item_count` at `0x0C7`, and
    `encumbrance` at `0x102`, which is a `u16le` and is the sum the engine
    itself recomputes -- gold plus item weight times quantity, one unit a
    coin.  Writing it keeps the sheet honest before the first recount; the
    engine overwrites it either way.
    """
    src = specimen_dir()
    for p in sorted(src.glob("*")):
        if p.name == "provenance.toml":
            continue
        dest = save_dir / p.name
        shutil.copy(p, dest)
        dest.chmod(0o644)
    item = sling(game)
    weight = int.from_bytes(item[dosbox.ITEM_WEIGHT:dosbox.ITEM_WEIGHT + 2],
                            "little")
    quantity = max(item[dosbox.ITEM_QUANTITY], 1)
    count_at = dl.FIELDS_BY_NAME["item_count"].offset
    enc_at = dl.FIELDS_BY_NAME["encumbrance"].offset
    gold_at = dl.FIELDS_BY_NAME["gold"].offset
    rows = []
    for n, count in enumerate(counts, start=1):
        rec = save_dir / f"CHRDAT{SLOT}{n}.SAV"
        raw = bytearray(rec.read_bytes())
        gold = int.from_bytes(raw[gold_at:gold_at + 2], "little")
        enc = gold + count * weight * quantity
        raw[count_at] = count
        raw[enc_at:enc_at + 2] = enc.to_bytes(2, "little")
        rec.write_bytes(bytes(raw))
        name = raw[1:1 + raw[0]].decode("latin-1")
        itm = save_dir / f"CHRDAT{SLOT}{n}.ITM"
        # A character carrying nothing gets *no* file, not an empty one --
        # `goldbox.dos.ITM_OMITTED_WHEN_EMPTY`.  Run 3 of 2026-09-05 wrote
        # zero-length files here by accident and reproduced the second half
        # of `#62 (A converted character who owns nothing gets a corrupt
        # sheet, and DOS then invents a garbage item)`: the engine's next
        # save invented a 63-byte `.ITM` of heap bytes for each of them.
        if count:
            itm.write_bytes(chain(item, count))
        elif itm.exists():
            itm.unlink()
        rows.append((name, count, enc))
    return rows


def chain(item: bytes, count: int) -> bytes:
    """`count` copies of `item`, with the `next` pointers the engine writes.

    The loader allocates every node itself, so the stored pointer's value is
    never dereferenced -- but a NULL where a node follows is what stops the
    Amiga's loader dead (`docs/167-amiga-neutral-and-party-writing.md`), and
    there is no reason to hand DOS a shape its own saves never have.  So the
    file gets what the engine's own `.ITM` files have: consecutive nodes
    `0x40` apart in one segment, and zero on the last.
    """
    out = bytearray()
    for n in range(count):
        node = bytearray(item)
        last = n == count - 1
        pointer = 0 if last else (0x0008 + (n + 1) * 0x40) | (0x44B4 << 16)
        node[dosbox.ITEM_NEXT:dosbox.ITEM_NEXT + 4] = \
            pointer.to_bytes(4, "little")
        out += node
    return bytes(out)


def read_counts(save_dir: pathlib.Path, slot: str = SLOT) -> list[str]:
    """One line per character: the stored count and the `.ITM` file's length.

    The two disagreeing is the whole point of reading both -- the engine
    rebuilds `item_count` from the chain it holds, so what it writes back is
    its own answer rather than the number this tool installed.
    """
    count_at = dl.FIELDS_BY_NAME["item_count"].offset
    out = []
    for n in range(1, 7):
        rec = save_dir / f"CHRDAT{slot}{n}.SAV"
        if not rec.is_file():
            continue
        raw = rec.read_bytes()
        itm = save_dir / f"CHRDAT{slot}{n}.ITM"
        size = itm.stat().st_size if itm.is_file() else 0
        name = raw[1:1 + raw[0]].decode("latin-1")
        out.append(f"{slot}{n} {name:10s} item_count={raw[count_at]:3d} "
                   f".ITM={size:5d} bytes = {size / dosbox.ITEM_SIZE:.2f} items")
    return out


def open_session(counts: list[int], note: str
                 ) -> tuple[dosbox.Session, dosbox.Slot]:
    """Claim a slot, stage the game, install the party, boot, load the save."""
    slot = dosbox.claim(note)
    session = dosbox.Session(slot, dosbox.find_game())

    def cleanup(*_: object) -> None:
        session.close()
        slot.release()

    atexit.register(cleanup)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    session.stage(fresh=True)
    for stale in sorted(session.save_dir.glob(f"CHRDAT{SLOT}*")) + \
            sorted(session.save_dir.glob(f"SAVGAM{SLOT}*")):
        stale.unlink()
    for row in install(session.save_dir, session.game_dir, counts):
        print(f"  {row[0]:10s} {row[1]:2d} items, encumbrance {row[2]}",
              flush=True)
    session.boot(fresh=False)
    game = dosbox.PoolOfRadiance(session)
    game.to_main_menu()
    session.shot("00-main-menu")
    game.load_game(SLOT)
    session.shot("01-loaded")
    return session, slot


def do_step(session: dosbox.Session, step: str, tag: str,
            gap: float = 1.0) -> str:
    """Run one step and shoot the screen it left.  Returns the shot's digest."""
    if step.startswith("!"):
        out = OUT / "snapshots" / step[1:]
        out.mkdir(parents=True, exist_ok=True)
        for p in sorted(session.save_dir.glob("*")):
            if p.is_file():
                shutil.copy(p, out / p.name)
        return "snapshot"
    if step.startswith("@"):
        # Press and shoot with no settle: the refusal message is drawn and
        # taken away again inside a second, so a `settle()` -- which waits for
        # two captures to agree -- is guaranteed to miss it.
        session.key(step[1:])
        safe = "".join(c if c.isalnum() else "_" for c in step)
        session.shot(f"{tag}-{safe}", allow_blank=True)
        return "flash"
    if step.startswith("~"):
        time.sleep(float(step[1:]))
    elif step.startswith("#"):
        for ch in step[1:]:
            session.key("space" if ch == " " else ch)
    else:
        session.key(step)
    time.sleep(gap)
    screen = session.settle(quiet=0.5, timeout=10.0)
    safe = "".join(c if c.isalnum() else "_" for c in step)
    session.shot(f"{tag}-{safe}", allow_blank=True)
    return screen.digest()


def interactive(counts: list[int], cmd: pathlib.Path, out: pathlib.Path,
                gap: float, idle: float = 900.0) -> int:
    """Boot once, then run step lines as they are appended to `cmd`."""
    out.mkdir(parents=True, exist_ok=True)
    cmd.parent.mkdir(parents=True, exist_ok=True)
    session, slot = open_session(counts, "issue52 item cap")
    if not cmd.exists():
        cmd.write_text("")
    done, last = 0, time.time()
    try:
        while time.time() - last < idle:
            lines = [ln.strip() for ln in cmd.read_text().splitlines()]
            lines = [ln for ln in lines if ln and not ln.startswith(";")]
            if done >= len(lines):
                time.sleep(1.0)
                continue
            step = lines[done]
            last = time.time()
            if step == "--quit":
                break
            if step == "--counts":
                for line in read_counts(session.save_dir):
                    print(line, flush=True)
                done += 1
                continue
            digest = do_step(session, step, f"{done:02d}", gap)
            print(f"{done:02d} {step:14s} {digest}", flush=True)
            for png in sorted((session.dir / "shots").glob("*.png")):
                shutil.copy(png, out / png.name)
            done += 1
        for line in read_counts(session.save_dir):
            print(line, flush=True)
        print("save dir", session.save_dir, flush=True)
    finally:
        for png in sorted((session.dir / "shots").glob("*.png")):
            shutil.copy(png, out / png.name)
        session.close()
        slot.release()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--counts", default="2,15,16",
                    help="items to install on characters 1..n")
    ap.add_argument("--cmd", type=pathlib.Path, default=OUT / "cmd.txt")
    ap.add_argument("--out", type=pathlib.Path, default=OUT / "shots")
    ap.add_argument("--gap", type=float, default=1.0)
    ap.add_argument("--interactive", action="store_true")
    ap.add_argument("--install-only", type=pathlib.Path,
                    help="write the party into this SAVE directory and stop")
    args = ap.parse_args(argv)
    counts = [int(n) for n in args.counts.split(",")]
    if args.install_only:
        game = dosbox.find_game()
        for row in install(args.install_only, game, counts):
            print(row)
        return 0
    if not args.interactive:
        ap.error("give --interactive or --install-only")
    return interactive(counts, args.cmd, args.out, args.gap)


if __name__ == "__main__":
    raise SystemExit(main())
