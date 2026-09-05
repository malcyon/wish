#!/usr/bin/env python3
"""Watch DOS Pool of Radiance expire, keep, and grant `.SPC` effect records.

The instrument behind `#232 (An item-granted effect is dropped on the way
through the neutral record, with no report)`.  The disassembly of `GAME.OVR`
says the engine's only test for "does this effect run out" is the sixteen-bit
duration at record bytes 1-2 -- zero is skipped for ever, anything else is
counted down as the clock advances -- and that readying an item appends a
record `id 00 00 0C 00`.  This puts both claims to the running game:

    tools/dosspcexpiry.py chain --slot J --steps 4
    tools/dosspcexpiry.py ready --slot J --char 1 --item 1 --effect 61

`chain` loads a save, breaks in, reads every party member's effect chain off
the heap -- the far pointer at record `0x7F`, nine bytes a node -- walks the
party `--steps` squares so the clock moves, and reads the chains again beside
the clock.  A `BLESS` at two minutes should be gone and every zero-duration
record still there.

`ready` rewrites one item of one character **in the staged copy** so that its
effect byte (`0x3D`) names an effect and its power byte (`0x3E`) is `0x80`
-- bit 7 is what the ready routine reads as "magical", the low seven bits
select the kind of effect and zero means "grant byte 0x3D" --
then drives `VIEW > ITEMS > READY` in the game, reads the chain, saves the
slot back and reads the `.SPC` the engine wrote.  That is the DOS
item-granted specimen the issue was missing.

Every run needs the DOSBox-X debugger build (`docs/142-dosbox-x-debugger.md`)
and reads the game out of the player's archives through `tools/dosbox.py`;
the archives are never written.  Output goes under `--out`, which should be
in `work/`.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import dos as pordos  # noqa: E402
from tools import dosbox, dosboxx  # noqa: E402

#: Where a DOS character record keeps the far pointer to its first effect node.
EFFECT_HEAD = 0x7F
#: A node: id, u16 duration, data, flag, far next.
NODE = 9


class claim_free:
    """Lease a DOSBox-X slot whose X display nobody is holding.

    The pool leases by `flock`, but a display can be held by an orphaned Xvfb
    from a run that lost its lease, and `XSession.boot` refuses to share one.
    Skip past those rather than fail on the first, and hand back every busy
    lease on the way out.  Nothing here kills anything: a display something
    else answers on is somebody else's until its owner tears it down.
    """

    def __init__(self, note: str):
        self.note = note
        self.busy: list[dosboxx.Slot] = []
        self.slot: dosboxx.Slot | None = None

    def __enter__(self) -> dosboxx.Slot:
        while True:
            slot = dosboxx.claim(self.note)
            if not dosboxx.server_on(slot.display):
                self.slot = slot
                for b in self.busy:
                    b.release()
                self.busy = []
                return slot
            print(f"slot {slot.n} display {slot.display} is held by another X server; skipping")
            self.busy.append(slot)

    def __exit__(self, *exc: object) -> None:
        for b in self.busy:
            b.release()
        if self.slot is not None:
            self.slot.release()


def boot_retry(s: dosboxx.XSession, fresh: bool = True, tries: int = 6, gap: float = 20.0) -> None:
    """Boot, waiting out a display that something else is holding for a moment.

    `tests/test_dosboxx.py` claims a synthetic slot on a fixed display, so a
    suite run elsewhere on the machine can put an Xvfb on this pool's first
    display for a couple of minutes.  `XSession.boot` refuses to share it,
    rightly; this waits and asks again rather than failing the whole run.
    """
    for n in range(tries):
        try:
            s.boot(fresh=fresh)
            return
        except RuntimeError as e:
            if "already has an X server" not in str(e) or n == tries - 1:
                raise
            print(f"{s.display} is busy ({e.args[0].split('.')[0]}); waiting {gap:.0f}s")
            time.sleep(gap)


def save_slot(s: dosboxx.XSession, letter: str, timeout: float = 90.0) -> bytes:
    """`ENCAMP > SAVE > <letter>`, believed only when the file changes.

    `PoolOfRadiance.save_game` does this with `settle()`, and under DOSBox-X a
    capture taken while "THE PARTY MAKES CAMP" is still being drawn is not
    line-doubled and `capture()` refuses it.  This version waits on the clock
    and the file instead of the screen, and leaves camp with the same `n` /
    `Escape` pair `leave_camp` uses.
    """
    path = s.save_file(letter)
    was = path.read_bytes() if path.is_file() else None
    s.key("e")
    time.sleep(3.0)
    s.key("s")
    time.sleep(2.0)
    s.key(letter.lower())
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.is_file() and path.read_bytes() != was:
            break
        time.sleep(0.3)
    else:
        raise TimeoutError(f"{path.name} never changed")
    dosbox.settle_files(s.save_dir, timeout=timeout)
    data = path.read_bytes()
    time.sleep(1.0)
    for k in ("n", "Escape", "Escape"):
        s.key(k)
        time.sleep(1.0)
    return data


def read_spc(save_dir: pathlib.Path, letter: str, records: list[tuple[int, bytes]]) -> dict:
    spc = {}
    for n, _ in records:
        p = save_dir / f"CHRDAT{letter.upper()}{n}.SPC"
        spc[n] = p.read_bytes().hex(" ") if p.is_file() else None
    return spc


def on_screen(fn, tries: int = 6, gap: float = 1.0):
    """Call `fn`, retrying when a capture lands on a half-drawn frame.

    `XSession.capture` halves the line-doubled DOSBox-X frame and raises
    `NotLineDoubled` when a row is not its twin, which happens when the grab
    lands mid-redraw.  The game has not gone anywhere; ask again.
    """
    for n in range(tries):
        try:
            return fn()
        except dosboxx.NotLineDoubled as e:
            if n == tries - 1:
                raise
            print(f"half-drawn frame ({e}); retrying")
            time.sleep(gap)


def party_records(save_dir: pathlib.Path, letter: str) -> list[tuple[int, bytes]]:
    """`(slot, raw 285-byte record)` for each `CHRDAT<letter><n>.SAV`."""
    out = []
    for n in range(1, 7):
        p = save_dir / f"CHRDAT{letter.upper()}{n}.SAV"
        if p.is_file():
            out.append((n, p.read_bytes()))
    return out


def name_key(record: bytes) -> bytes:
    """The Pascal-string name at the front of a record, length byte included."""
    n = record[0]
    return record[:1 + n]


def find_records(image: bytes, key: bytes) -> list[int]:
    hits, at = [], 0
    while True:
        at = image.find(key, at)
        if at < 0:
            return hits
        hits.append(at)
        at += 1


def walk_chain(image: bytes, head: int, limit: int = 40) -> list[dict]:
    """Follow far pointers from `head` (a linear address) through 9-byte nodes."""
    nodes, seen = [], set()
    ptr = head
    while ptr and ptr not in seen and len(nodes) < limit:
        seen.add(ptr)
        if ptr + NODE > len(image):
            break
        raw = image[ptr:ptr + NODE]
        off = int.from_bytes(raw[5:7], "little")
        seg = int.from_bytes(raw[7:9], "little")
        nodes.append(dict(
            at=f"{ptr:05X}", id=raw[0],
            duration=int.from_bytes(raw[1:3], "little"),
            data=raw[3], flag=raw[4], raw=raw.hex(" "),
        ))
        ptr = (seg << 4) + off if (seg or off) else 0
    return nodes


def read_party(s: dosboxx.XSession, records: list[tuple[int, bytes]]) -> dict:
    """Dump the megabyte and read every party member's chain out of it."""
    image = s.read(0, 0x100000)
    out: dict = {}
    for n, rec in records:
        key = name_key(rec)
        name = key[1:].decode("ascii", "replace")
        found = []
        for at in find_records(image, key):
            off = int.from_bytes(image[at + EFFECT_HEAD:at + EFFECT_HEAD + 2], "little")
            seg = int.from_bytes(image[at + EFFECT_HEAD + 2:at + EFFECT_HEAD + 4], "little")
            head = (seg << 4) + off if (seg or off) else 0
            found.append(dict(record=f"{at:05X}", head=f"{seg:04X}:{off:04X}",
                              chain=walk_chain(image, head) if head else []))
        out[f"{n}:{name}"] = found
    return out, image


def clock_minutes(s: dosboxx.XSession, image: bytes, save: bytes) -> int | None:
    vm = save[dosboxx.VM_OFFSET:dosboxx.VM_OFFSET + dosboxx.VM_SIZE]
    found = dosboxx.locate(image, vm)
    if found is None:
        return None
    base = found[0]
    return image[base + dosboxx.vm_slot(dosboxx.CLOCK_MINUTES)]


def summarise(party: dict) -> list[str]:
    lines = []
    for who, found in party.items():
        best = max(found, key=lambda f: len(f["chain"]), default=None)
        if best is None:
            lines.append(f"{who}: record not found in memory")
            continue
        chain = " | ".join(
            f"{n['id']:3d} dur={n['duration']:<5d} data={n['data']:02X} flag={n['flag']}"
            for n in best["chain"]) or "(no nodes)"
        lines.append(f"{who}: record {best['record']} head {best['head']}: {chain}")
    return lines


def walk(por: dosbox.PoolOfRadiance, steps: int) -> int:
    """Step forward `steps` times, turning when a step does not move."""
    done = 0
    for _ in range(steps * 3):
        if done >= steps:
            break
        if on_screen(por.step):
            done += 1
        else:
            on_screen(por.turn_right)
    return done


def cmd_chain(args: argparse.Namespace) -> int:
    game = dosbox.find_game("POOLRAD")
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    result: dict = {"slot": args.slot, "steps": args.steps}
    with claim_free("dosspcexpiry chain") as slot:
        # Not `with XSession(...)`: its `__enter__` boots, and a second boot
        # finds its own Xvfb on the display and refuses to share it.
        s = dosboxx.XSession(slot, game)
        try:
            boot_retry(s)
            records = party_records(s.save_dir, args.slot)
            save = s.save_file(args.slot).read_bytes()
            por = dosbox.PoolOfRadiance(s)
            on_screen(por.to_main_menu)
            on_screen(lambda: por.load_game(args.slot))
            s.shot("loaded")
            if not s.attach():
                print("could not attach the debugger")
                return 1
            party, image = read_party(s, records)
            result["before"] = party
            result["clock_before"] = clock_minutes(s, image, save)
            print("== before, clock minute", result["clock_before"])
            for line in summarise(party):
                print("  ", line)
            s.run()
            time.sleep(1.0)
            result["walked"] = walk(por, args.steps)
            s.shot("walked")
            if not s.attach():
                print("could not re-attach the debugger")
                return 1
            party, image = read_party(s, records)
            result["after"] = party
            result["clock_after"] = clock_minutes(s, image, save)
            print("== after", result["walked"], "steps, clock minute", result["clock_after"])
            for line in summarise(party):
                print("  ", line)
            s.run()
            time.sleep(0.5)
            if args.save:
                save_slot(s, args.save)
                result["resaved_spc"] = read_spc(s.save_dir, args.save, records)
                print("== .SPC files the engine wrote to slot", args.save)
                for n, h in result["resaved_spc"].items():
                    print("  ", n, h)
        finally:
            for png in (s.dir / "shots").glob("*.png"):
                (out / png.name).write_bytes(png.read_bytes())
            (out / "chain.json").write_text(json.dumps(result, indent=1))
            s.close()
    return 0


def cmd_ready(args: argparse.Namespace) -> int:
    game = dosbox.find_game("POOLRAD")
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    result: dict = {"slot": args.slot, "char": args.char, "item": args.item,
                    "effect": args.effect}
    with claim_free("dosspcexpiry ready") as slot:
        s = dosboxx.XSession(slot, game)
        try:
            s.stage(fresh=True)
            itm = s.save_dir / f"CHRDAT{args.slot.upper()}{args.char}.ITM"
            data = bytearray(itm.read_bytes())
            base = (args.item - 1) * pordos.ITEM_SIZE
            before = bytes(data[base:base + pordos.ITEM_SIZE])
            data[base + 0x3D] = args.effect
            data[base + 0x3E] = args.power
            data[base + 0x34] = 0          # not readied yet
            itm.write_bytes(bytes(data))
            result["item_before"] = before.hex(" ")
            result["item_after"] = bytes(data[base:base + pordos.ITEM_SIZE]).hex(" ")
            boot_retry(s, fresh=False)
            records = party_records(s.save_dir, args.slot)
            por = dosbox.PoolOfRadiance(s)
            on_screen(por.to_main_menu)
            on_screen(lambda: por.load_game(args.slot))
            s.shot("loaded")
            for i, k in enumerate(args.keys):
                s.key(k)
                on_screen(s.settle)
                s.shot(f"key{i:02d}_{k}")
            if not s.attach():
                print("could not attach the debugger")
                return 1
            party, image = read_party(s, records)
            result["after_keys"] = party
            print("== after keys", args.keys)
            for line in summarise(party):
                print("  ", line)
            s.run()
            time.sleep(0.5)
            if args.save:
                for k in args.leave:
                    s.key(k)
                    time.sleep(1.0)
                s.shot("back")
                save_slot(s, args.save)
                result["resaved_spc"] = read_spc(s.save_dir, args.save, records)
                print("== .SPC files the engine wrote to slot", args.save)
                for n, h in result["resaved_spc"].items():
                    print("  ", n, h)
        finally:
            for png in (s.dir / "shots").glob("*.png"):
                (out / png.name).write_bytes(png.read_bytes())
            (out / "ready.json").write_text(json.dumps(result, indent=1))
            # Copy the slot the engine just wrote out before the instance
            # goes.  `s.close()` takes the staged tree with it, and the first
            # run of this command lost the only engine-written DOS
            # item-granted `.SPC` this project has ever had that way -- the
            # incident behind `.claude/rules/testing.md`'s "A specimen dies
            # with the emulator slot that made it".  `work/` is a staging
            # post, not a home: `tools/specimens.py add` is what makes it
            # keep.
            if args.save:
                saved = out / "save"
                saved.mkdir(parents=True, exist_ok=True)
                letter = args.save.upper()
                # `CHRDAT<letter><n>.SAV/.ITM/.SPC` and `SAVGAM<letter>.DAT`
                # both carry the slot letter at the seventh character.
                for src in sorted(s.save_dir.glob("*")):
                    if src.is_file() and src.name[6:7] == letter:
                        (saved / src.name).write_bytes(src.read_bytes())
                print("== copied to", saved)
                for p in sorted(saved.glob("*")):
                    print("  ", p.name, p.stat().st_size)
            s.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("chain", help="read the chains, walk, read them again")
    c.add_argument("--slot", default="J")
    c.add_argument("--steps", type=int, default=4)
    c.add_argument("--save", default=None, help="then save to this slot and read its .SPC")
    c.add_argument("--out", default="work/issue232/chain")
    c.set_defaults(func=cmd_chain)
    r = sub.add_parser("ready", help="grant an item an effect and ready it")
    r.add_argument("--slot", default="J")
    r.add_argument("--char", type=int, default=1)
    r.add_argument("--item", type=int, default=1)
    r.add_argument("--effect", type=int, default=61)
    r.add_argument("--power", type=lambda v: int(v, 0), default=0x80,
                   help="byte 0x3E; bit 7 marks the item magical, which is what "
                        "gates the effect grant, and the low bits must be zero")
    r.add_argument("--keys", nargs="*", default=[], help="keys to press after loading")
    r.add_argument("--leave", nargs="*", default=["Escape", "Escape"],
                   help="keys that get back to the map before saving")
    r.add_argument("--save", default=None)
    r.add_argument("--out", default="work/issue232/ready")
    r.set_defaults(func=cmd_ready)
    args = ap.parse_args(argv)
    if dosboxx.unavailable():
        print(dosboxx.unavailable())
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
