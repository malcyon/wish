#!/usr/bin/env python3
"""What a Curse of the Azure Bonds save holds before the party begins adventuring.

`#301 (A DOS Curse save standing in area 0 is refused by the import, because
no row of the area table names area 0)` is the ticket.  A DOS Curse save whose
area word is 0 is one the player made from the party-formation menu, before
pressing `BEGIN ADVENTURING`; Curse has no `ECL00` and no `GEO00`, so 0 is not
a place at all.  This tool takes the C64 half of that measurement, which is
what says whether a conversion of such a save should write 0 too.

Three things, each a flag, because they answer three different questions:

    tools/curseareazero.py --pool 3
        Boot to the party menu and read `$4B00`-`$4DDF` -- the header of
        the save `SAVE CURRENT GAME` would write for a party that has not
        begun adventuring.  Nothing is loaded and nothing is pressed.

    tools/curseareazero.py --pool 3 --save WISH-SPEC-curse-h-engine-resave.D64
        The control: the same page again after `LOAD SAVED GAME` has put an
        area-1 party in, so the two readings differ by one known thing.

    tools/curseareazero.py --pool 3 --save DISK --begin
        And then walk the menu to `BEGIN ADVENTURING` and photograph where the
        party lands, which is how a save's area word is read back off the
        screen the game draws.

`--doctor SRC DST` is offline and takes no slot: it copies a save disk and
writes the never-adventured header into the copy -- area, resident map, the
disk hint and all twenty-five cache slots -- so the *loader's* behaviour on an
area-0 save can be measured before any converter is able to write one.  It
never touches the source, and the source is never one of the player's own
disks: pass a specimen or something under `work/`.

Every reading goes to `work/issue301/<run>/run.jsonl` as one line per event,
because a `timeout` around a driven session skips whatever a `finally` was
going to write.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOLS))

import gamedisks  # noqa: E402

from goldbox import c64_save  # noqa: E402
from goldbox.d64 import D64, split_load_address  # noqa: E402

#: Where Curse's `SAVEAZURE` payload loads, and how much of it this tool reads.
#: The whole payload is 7424 bytes; the first page carries every word the
#: loader consults -- the clock, the resident map, the indoors flag, the disk
#: hint and the script id -- and the twenty-five loaded-files slots run from
#: `+$2C0`, so `$2E0` bytes covers both.
PAYLOAD_AT = 0x4B00
HEADER_BYTES = 0x2E0

#: The name the engine loads and saves under.  `GEN $1F66`.
SAVE_NAME = b"SAVEAZURE"

#: What an empty loaded-files cache slot holds.  `goldbox.dos.FILE_CACHE_EMPTY`
#: says the same; it is repeated rather than imported so that `--doctor` works
#: with no `goldbox.dos` import at all.
CACHE_EMPTY = 0xFF

#: The status line the game draws once the party is in an area: square,
#: facing letter and the clock.  Matching it is how a save's area word is read
#: back off the screen rather than out of our own reader.
RE_STATUS = re.compile(r"(?:\d+,\d+ [NESW]|[NESW] \d\d:\d\d \d+,\d+)"
                       r"(?: +\d\d:\d\d)?")


def fields(page: bytes, container) -> dict:
    """The named bytes of a Curse payload header, as a JSON-able dict."""
    at, slots = container.cache
    return {
        "area": page[container.current_script],
        "geo": page[container.current_geo],
        "indoors": page[container.indoors],
        "disk_hint": page[container.disk_hint],
        "clock": list(page[0xC6:0xCC]),
        "cache": page[at:at + slots].hex() if at + slots <= len(page) else "",
        "f0_ff": page[0xF0:0x100].hex(),
    }


#: What `--zero` can take away, and what each one is.  Named separately
#: because a run that changes four bytes at once and crashes has proved
#: nothing about any of them.
ZEROABLE = ("area", "geo", "cache", "fdfe")

#: `goldbox.dos.apply_file_cache`'s own recipe, repeated here as three slot
#: numbers so `--recipe` can build the disk the converter *would* write
#: without importing the module that currently refuses to write it.  Curse
#: sets bit 7 in every slot it fills (`Container.cache_bit7`).
CACHE_GEO, CACHE_ECL, CACHE_ANIMATE = 2, 8, 11
CACHE_RELOAD, ANIMATE_RESIDENT = 0x80, 0x00


def doctor(src: pathlib.Path, dst: pathlib.Path, hint: int = 2,
           cache: int = CACHE_EMPTY, zero: tuple[str, ...] = ZEROABLE,
           recipe: bool = False) -> dict:
    """Write the never-adventured header into a copy of a save disk.

    The four bytes the DOS differential named -- area, resident map and the
    two the arriving script refills -- plus a cache of `cache` in all
    twenty-five slots.  Everything else in the payload is left exactly as the
    engine wrote it, so what changes between the source disk and this one is
    only the answer to "where is the party".

    **`hint` defaults to 2 and zero is a measured mistake.**  The disk hint at
    `+$EE` reads 2 at the C64 party menu and `dax_number` reads 2 in a DOS save
    made there, because side 2 is where `ECL01` and `GEO01` live and that is
    the first thing `BEGIN ADVENTURING` needs.  A copy doctored with 0 loaded
    and then drew `INSERT SIDE # 0, AND PRESS ANY KEY.` for a side that does
    not exist (`#301`).
    """
    shutil.copy(src, dst)
    os.chmod(dst, 0o644)
    image = D64.open(dst)
    raw = image.read_file(SAVE_NAME)
    addr, payload = split_load_address(raw)
    if addr != PAYLOAD_AT:
        raise SystemExit(f"{src} loads at ${addr:04X}, not ${PAYLOAD_AT:04X}")
    c = c64_save.CURSE_OF_THE_AZURE_BONDS
    before = fields(payload, c)
    buf = bytearray(payload)
    at, slots = c.cache
    if "cache" in zero:
        buf[at:at + slots] = bytes([cache]) * slots
    if "area" in zero:
        buf[c.current_script] = 0
    if "geo" in zero:
        buf[c.current_geo] = 0
    if "fdfe" in zero:
        buf[0xFD] = 0
        buf[0xFE] = 0
    if recipe:
        buf[at:at + slots] = bytes([CACHE_EMPTY]) * slots
        buf[at + CACHE_GEO] = buf[c.current_geo] | CACHE_RELOAD
        buf[at + CACHE_ECL] = buf[c.current_script] | CACHE_RELOAD
        buf[at + CACHE_ANIMATE] = ANIMATE_RESIDENT | CACHE_RELOAD
    buf[c.disk_hint] = hint
    image.write_file_inplace(SAVE_NAME, bytes([PAYLOAD_AT & 0xFF,
                                               PAYLOAD_AT >> 8]) + bytes(buf))
    image.save(dst)
    after = fields(bytes(buf), c)
    return {"src": str(src), "dst": str(dst), "zeroed": list(zero),
            "recipe": recipe,
            "before": before, "after": after}


#: The KERNAL's `SETNAM` state: length at `$B7`, name pointer at `$BB`/`$BC`.
#: Reading it while the game is asking for a disk names the file whose load
#: failed, which is the difference between "it wants side 2" and "it wants
#: `GEO00`, which is on no side".
SETNAM_LEN, SETNAM_PTR = 0xB7, 0xBB


def wanted_file(sess) -> dict:
    """Whatever name the last `SETNAM` pointed at, out of the running machine."""
    with sess.mon(5) as m:
        length = m.read(SETNAM_LEN, 1)[0]
        ptr = m.read(SETNAM_PTR, 2)
        at = ptr[0] | (ptr[1] << 8)
        raw = m.read(at, length) if 0 < length <= 32 else b""
    return {"setnam_len": length, "setnam_ptr": f"${at:04X}",
            "setnam": raw.decode("latin1")}


def read_header(sess) -> dict:
    """`$4B00`-`$4DDF` out of the running machine, decoded."""
    with sess.mon(5) as m:
        page = m.read(PAYLOAD_AT, HEADER_BYTES)
    c = c64_save.CURSE_OF_THE_AZURE_BONDS
    out = fields(page, c)
    out["page"] = page.hex()
    return out


def run(args) -> int:
    from tools import curseload, curserun, dualclassagain  # noqa: PLC0415
    from tools import session as por  # noqa: PLC0415

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    log = (out / "run.jsonl").open("a")

    def note(**kw):
        kw["t"] = round(time.time(), 2)
        log.write(json.dumps(kw) + "\n")
        log.flush()
        print(json.dumps(kw), flush=True)

    def shot(tag: str) -> None:
        sess.kbd.screenshot(str(out / f"{tag}.png"))
        s = sess.screen()
        text = "(bitmap)" if s is None else "\n".join(s.row(r)
                                                      for r in range(25))
        (out / f"{tag}.txt").write_text(text + "\n")

    disks = args.disks or str(gamedisks.find("curse-of-the-azure-bonds") or "")
    slot = por.claim_slot(args.pool, note=os.environ.get("POR_AGENT", "i301"))
    note(event="slot", n=slot.n, monitor=slot.port, cmd=slot.cmd_port,
         display=slot.display, dir=str(slot.dir))
    disk = curserun.stage(slot, disks, args.save)
    save_disk = str(pathlib.Path(slot.dir) / "SIDE0.D64")
    os.chmod(save_disk, 0o644)
    sess = curserun.CurseSession(disk, slot=slot)
    sess.save_disk = save_disk
    try:
        note(event="booting")
        if not sess.boot():
            note(event="boot-failed")
            return 1
        note(event="booted")
        shot("00-party-menu")
        note(event="header", when="party-menu", **read_header(sess))
        if not args.save:
            return 0

        sess.attach(save_disk)
        outcome = curseload.load_saved_game(sess, note=note, shot=shot,
                                            wait=args.wait, tag="01-load")
        note(event="load", outcome=outcome)
        if outcome != "loaded":
            return 1
        note(event="header", when="loaded", **read_header(sess))
        if not args.begin:
            return 0

        # The side prompt is a loop with two exits neither of which this
        # harness can reach, so it has to be patched.  Patching when the
        # prompt is on the screen is what has been measured to work (`#301`,
        # runs 9 and 10); patching at the party menu was suspected of killing
        # the machine and is **not** implicated -- the same disk crashed with
        # no patch at all, and `--patch-early` is kept so the comparison can
        # be taken again rather than because it is known to be wrong.
        patched = sess.patch_disk_prompt() if args.patch_early else False
        note(event="patch-disk-prompt", when="before-begin", applied=patched)
        # **Put the side the arriving script needs in the drive first.**  The
        # save disk is what the load left there, so `BEGIN ADVENTURING` asks
        # for another side and the prompt is a loop this harness cannot
        # answer.  Attaching the side named by the save's own disk hint means
        # the load succeeds and the prompt is never drawn.
        if args.side:
            here = pathlib.Path(slot.dir) / f"SIDE{args.side}.D64"
            sess.attach(str(here))
            note(event="attached-side", side=args.side)
        if not dualclassagain.walk_menu(sess, "BEGIN ADVENTURING"):
            note(event="begin-miss")
            shot("02-begin-miss")
            return 1
        # `BEGIN ADVENTURING` from a never-adventured save has to load the
        # arriving script off another side, so the side prompt is part of the
        # measurement rather than an interruption to it: keep answering it,
        # and stop on the status line, which is what says where the party is.
        deadline, landed = time.time() + args.wait, ""
        while time.time() < deadline:
            time.sleep(2.0)
            s = sess.screen()
            if s is None:
                continue
            text = s.text()
            if "INSERT SIDE" in text and not patched:
                note(event="wanted", **wanted_file(sess))
                patched = sess.patch_disk_prompt()
                note(event="patch-disk-prompt", when="at-prompt",
                     applied=patched)
            sess.handle_prompt(s)
            hit = RE_STATUS.search(text)
            if hit:
                landed = hit.group(0)
                break
        shot("03-begun")
        note(event="begun", status=landed,
             screen=("(bitmap)" if sess.screen() is None
                     else sess.screen().text()))
        return 0 if landed else 1
    finally:
        note(event="done")
        sess.close()
        slot.teardown()
        log.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--doctor", nargs=2, metavar=("SRC", "DST"),
                    help="write the never-adventured header into a copy")
    ap.add_argument("--save", default="",
                    help="a save disk to load before the second reading")
    ap.add_argument("--begin", action="store_true",
                    help="and then press BEGIN ADVENTURING")
    ap.add_argument("--disks", default="", help="where the Curse sides are")
    ap.add_argument("--pool", type=int, default=None)
    ap.add_argument("--side", type=int, default=2,
                    help="attach this side before BEGIN ADVENTURING, so the "
                         "arriving script's load needs no disk prompt; 0 for "
                         "none")
    ap.add_argument("--patch-early", action="store_true",
                    help="patch the side prompt at the party menu instead of "
                         "when it is drawn; not measured to be harmful, and "
                         "not measured to help either")
    ap.add_argument("--hint", type=int, default=2,
                    help="doctor: what to put in the disk hint at +$EE")
    ap.add_argument("--zero", default=",".join(ZEROABLE),
                    help="doctor: which of " + ",".join(ZEROABLE) + " to take "
                         "away; one at a time is how a crash is attributed")
    ap.add_argument("--recipe", action="store_true",
                    help="doctor: build the cache the converter would write "
                         "-- $FF in all twenty-five, then slot 2 the map, "
                         "slot 8 the area and slot 11 ANIMATE00, each with "
                         "bit 7 set")
    ap.add_argument("--cache", default="ff",
                    help="doctor: the byte for all twenty-five cache slots")
    ap.add_argument("--wait", type=float, default=120.0)
    ap.add_argument("--out", default=str(ROOT / "work" / "issue301" / "c64"))
    args = ap.parse_args(argv)
    if args.doctor:
        src, dst = (pathlib.Path(p) for p in args.doctor)
        want = tuple(w for w in args.zero.split(",") if w)
        bad = [w for w in want if w not in ZEROABLE]
        if bad:
            raise SystemExit(f"--zero: {', '.join(bad)} is not one of "
                             f"{', '.join(ZEROABLE)}")
        print(json.dumps(doctor(src, dst, args.hint, int(args.cache, 16),
                                want, args.recipe), indent=2))
        return 0
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
