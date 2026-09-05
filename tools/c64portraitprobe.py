#!/usr/bin/env python3
"""Ask the running C64 game whether it draws a character's sheet portrait.

The DOS half of `#57 (Carry the character portrait across ports)` is settled:
`portrait_head`/`portrait_body` are a one-based position in a fourteen- and a
twelve-entry creation menu, the C64 record stores the art id the menu chose,
and `SAVGAM<slot>.DAT` word `$49FF` gates whether DOS draws the picture at
all.  Nobody had looked at the **C64** sheet, so nothing said whether the C64
has the same gate -- and `goldbox.dos.HEADER_ZEROED` writes zero at `$49FF` of
a converted `SAVEDGAME0`, which is exactly the value that made a converted DOS
party faceless.

This is the instrument for that question, and it does not rely on looking at a
picture.  The C64 loads a portrait through the **loaded-files cache** -- one
byte per file kind at `$6E13` while the game runs, slot 13 `BODY<xx>` and slot
14 `HEAD<xx>` (`docs/140-loaded-files-cache.md`) -- so "did the game go and
fetch this character's art" is a byte, not a judgement about pixels.  The run
reads those two slots before and after a `VIEW`, photographs the sheet, and
hashes the two load addresses so a *changed* portrait can be told from an
unchanged one.

    tools/c64portraitprobe.py --disk PORSAVE12.D64 --view 0 5
    tools/c64portraitprobe.py --disk PORSAVE12.D64 --words 49FF=0
    tools/c64portraitprobe.py --disk PORSAVE12.D64 --portrait 0=2D/25

`--words` and `--portrait` patch the **staged copy** of the save disk, never
the player's own: `--words 49FF=0` writes one byte of `SAVEDGAME0` and
`--portrait SLOT=HH/BB` writes `0x0FE`/`0x0FF` of one slot record.  Together
they are the two-run differential -- one thing different, everything else the
same boot path.

Nothing here opens a window (`POR_HEADLESS=1`), and the player's disks are
read and never written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import session as S  # noqa: E402

from automap.paths import find_disks  # noqa: E402
from automap.vice import MonitorError  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.dos import SAVE0_BASE, SLOT_AREA, SLOT_STRIDE  # noqa: E402

#: The loaded-files cache while the game runs, and the two slots that hold a
#: portrait.  `docs/140-loaded-files-cache.md`: twenty-five slots, one per file
#: kind, each holding the two hex digits of the resident file's name, `$FF`
#: for empty and bit 7 a reload marker.
CACHE = 0x6E13
CACHE_LEN = 0x19
CACHE_BODY = 13
CACHE_HEAD = 14

#: Where the two files land, from the same table.  Hashed rather than dumped:
#: what the run needs is whether the bytes *changed*, and the art itself is
#: the game's and stays on the player's disk.
BODY_AT = 0x8C00
HEAD_AT = 0x9000
ART_LEN = 0x0400

#: The player's own disks: `$POR_DISKS` first, then wherever the rest of the
#: program looks.  Never a path spelled out -- that names one machine.
DISKS = os.environ.get("POR_DISKS", str(find_disks() or ""))

#: The word that gates the sheet portrait on DOS, at the same address in the
#: C64's `SAVEDGAME0`.  Fourteen of Donald's nineteen C64 saves hold 1 there
#: and five hold `$81`; a conversion writes zero.
PORTRAIT_DRAWN = 0x49FF


def _load_address(data: bytes) -> int:
    return data[0] | (data[1] << 8)


def patch_save(path: pathlib.Path, words: dict[int, int],
               portraits: dict[int, tuple[int, int]]) -> list[str]:
    """Rewrite `SAVEDGAME0` inside a **copied** disk image, in place.

    Returns one line per change, for the log.  `write_file_inplace` keeps the
    sector chain, so nothing but the bytes named here moves.
    """
    notes: list[str] = []
    if not words and not portraits:
        return notes
    image = D64(bytearray(path.read_bytes()))
    raw = bytearray(image.read_file(b"SAVEDGAME0"))
    base = _load_address(raw)
    if base != SAVE0_BASE:
        raise SystemExit(f"{path.name}: SAVEDGAME0 loads at ${base:04X}, "
                         f"not ${SAVE0_BASE:04X}")
    body = raw[2:]
    for address, value in sorted(words.items()):
        at = address - SAVE0_BASE
        notes.append(f"${address:04X}: ${body[at]:02X} -> ${value:02X}")
        body[at] = value
    for slot, (head, art_body) in sorted(portraits.items()):
        at = SLOT_AREA - SAVE0_BASE + slot * SLOT_STRIDE
        name = bytes(body[at:at + 20]).split(b"\x00")[0].decode("latin1")
        notes.append(
            f"slot {slot} ({name}): portrait "
            f"${body[at + 0xFE]:02X}/${body[at + 0xFF]:02X} -> "
            f"${head:02X}/${art_body:02X}")
        body[at + 0xFE] = head
        body[at + 0xFF] = art_body
    raw[2:] = body
    image.write_file_inplace(b"SAVEDGAME0", bytes(raw))
    image.save(path)
    return notes


def answer_bars(sess, answer: str = "NO", seconds: float = 240.0) -> str:
    """Press through whatever the game puts up until the world bar is back.

    `Session.wait_for_world` answers a `PRESS <RETURN>` and nothing else, and
    a save loaded into a scene can also ask `YES NO` -- which is what a run
    that waited 240 seconds on PORSAVE12 was sitting in front of.  The same
    loop `tools/savecheck.py` uses, kept short here because this tool wants
    the world bar and nothing about how it got there.
    """
    deadline = time.time() + seconds
    while time.time() < deadline:
        s = sess.screen()
        if s is None:
            time.sleep(1.0)
            continue
        if sess.handle_prompt(s):
            continue
        row = s.row(24)
        if "MOVE" in row and "ENCAMP" in row:
            return "world"
        if "PRESS" in row:
            sess.kbd.key("Return")
        elif "YES" in row and "NO" in row:
            print(f"    answering {answer} to |{row.strip()}|")
            if not sess.select_bar(answer, timeout=8):
                sess.kbd.key("Return")
        time.sleep(1.2)
    return "stuck"


def read_cache(sess) -> dict:
    """The loaded-files cache and the two portrait load areas, hashed."""
    try:
        with sess.mon(8) as m:
            cache = m.read(CACHE, CACHE_LEN)
            body = m.read(BODY_AT, ART_LEN)
            head = m.read(HEAD_AT, ART_LEN)
    except (OSError, MonitorError) as e:
        return {"error": str(e)}
    return {
        "cache": cache.hex(),
        "body_slot": cache[CACHE_BODY],
        "head_slot": cache[CACHE_HEAD],
        "body_art_sha": hashlib.sha256(body).hexdigest()[:16],
        "head_art_sha": hashlib.sha256(head).hexdigest()[:16],
    }


def describe_slot(value: int) -> str:
    if value == 0xFF:
        return "empty"
    return f"${value & 0x7F:02X}" + (" (reload)" if value & 0x80 else "")


def sheet(sess, index: int, shot: pathlib.Path, log,
          poke: dict[int, int] | None = None, wait: float = 90.0,
          art_side: int | None = None) -> dict:
    """Open one character's `VIEW` sheet and measure it while it is up.

    `Session.character_sheet` photographs and then leaves, which is the right
    shape for reading text and the wrong one here: the cache has to be read at
    the moment the sheet is on the screen, and that is a moment the caller
    never holds.

    `poke` is written into RAM immediately before the sheet opens, which is
    the only way to test a saved-game word the arriving area's own script
    overwrites: `$49EB` patched in the file came back 0 whatever it was set
    to, because the area prologue writes it on load.
    """
    out: dict = {"index": index}
    if poke:
        with sess.mon(8) as m:
            for address, value in sorted(poke.items()):
                was = m.read(address, 1)[0]
                m.write(address, bytes([value]))
                log(f"  poked ${address:04X}: ${was:02X} -> ${value:02X}")
        out["poked"] = {f"{a:04X}": v for a, v in sorted(poke.items())}
    if not sess.select_party(index):
        sess.kbd.screenshot(str(shot.with_name(shot.stem + "-nopanel.png")))
        out["error"] = "the party panel would not highlight that slot"
        return out
    if not sess.select_bar("VIEW", timeout=20):
        sess.kbd.screenshot(str(shot.with_name(shot.stem + "-noview.png")))
        out["error"] = "VIEW could not be selected on the world bar"
        return out
    # `handle_prompt` inside the wait, not only outside it.  Opening a sheet
    # is what makes the game fetch a portrait, and the art lives on the game
    # sides rather than the save disk -- so the first thing an indoor party's
    # `VIEW` does is ask for a disk.  Without this the sheet never arrives and
    # the run reports "no character sheet" for what is really a swap nobody
    # answered.
    deadline = time.time() + wait
    trail: list[dict] = []
    last = None
    swapped = 0.0
    while time.time() < deadline:
        s = sess.screen()
        # A sheet's disk prompt is answered with the side the caller names
        # rather than the side the game asks for.  The game asked for side 2
        # in the Slums and side 2 carries `HEAD08` but not `BODY07`, so
        # answering it as asked is a loop; `--prompt-side 3` puts in the side
        # that carries every portrait and lets the fetch finish.
        if art_side and s is not None and time.time() - swapped > 2.0:
            if S.RE_GAME_SIDE.search(s.text()):
                swapped = time.time()
                want = f"{sess.here}/SIDE{art_side}.D64"
                log(f"  sheet prompt -> SIDE{art_side}.D64")
                sess.attach(want)
                sess.kbd.key("space")
                continue
        if not art_side and s is not None and sess.handle_prompt(s):
            continue
        # Sample the cache all the way through the wait, not only at the end.
        # The Slums run sat for ninety seconds with the drive light on and
        # reported "no character sheet", and what it was doing was fetching
        # the portrait -- which is the thing being measured.
        now = read_cache(sess)
        if now.get("cache") != last:
            last = now.get("cache")
            trail.append({"t": round(time.time() - (deadline - wait), 1),
                          "head_slot": now.get("head_slot"),
                          "body_slot": now.get("body_slot")})
        if s is not None and S.SHEET_BAR in s.row(24) and s.row(1).strip():
            break
        time.sleep(0.5)
    else:
        out["trail"] = trail
        out["settled"] = read_cache(sess)
        sess.kbd.screenshot(str(shot.with_name(shot.stem + "-nosheet.png")))
        out["error"] = (f"no VIEW:ITEMS bar {wait}s after VIEW; the cache "
                        f"ended at head "
                        f"{describe_slot(out['settled']['head_slot'])} body "
                        f"{describe_slot(out['settled']['body_slot'])}")
        log("  " + out["error"])
        sess.leave_sheet()
        return out
    out["trail"] = trail
    # The sheet's text lands before any disk load behind it finishes, so the
    # reading is taken twice: once as soon as the bar is up and once after
    # long enough for a 1541 to have fetched two files.  A portrait that
    # arrives late is still a portrait, and one that never arrives is the
    # answer this run is for.
    time.sleep(0.8)
    out["at_bar"] = read_cache(sess)
    out["rows"] = [line.rstrip() for line in sess.screen().rows() if line.strip()]
    time.sleep(8.0)
    out["settled"] = read_cache(sess)
    sess.kbd.screenshot(str(shot))
    out["shot"] = str(shot)
    log(f"  slot {index}: body slot {describe_slot(out['settled']['body_slot'])}, "
        f"head slot {describe_slot(out['settled']['head_slot'])}")
    sess.leave_sheet()
    return out


def run(args) -> int:
    disks = pathlib.Path(args.disks)
    save = pathlib.Path(args.disk)
    if not save.is_absolute():
        save = disks / save
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    words = {}
    for spec in args.words:
        addr, _, value = spec.partition("=")
        words[int(addr, 16)] = int(value, 0)
    portraits = {}
    for spec in args.portrait:
        slot, _, pair = spec.partition("=")
        head, _, body = pair.partition("/")
        portraits[int(slot)] = (int(head, 16), int(body, 16))

    report: dict = {"disk": save.name, "words": args.words,
                    "portrait": args.portrait, "views": []}
    slot = S.claim_slot(args.slot, f"c64portraitprobe/{save.name}")
    print(f"slot {slot.n} display {slot.display}")
    sess = None
    try:
        boot = S.stage_disks(slot, disks)
        staged = pathlib.Path(slot.dir) / "SIDE0.D64"
        shutil.copy(save, staged)
        report["patched"] = patch_save(staged, words, portraits)
        for line in report["patched"]:
            print(f"  patched {line}")

        sess = S.Session(boot, slot=slot)
        if not sess.boot():
            raise RuntimeError("boot failed")
        if not sess.load_save():
            raise RuntimeError("the game did not accept the disk as a save")
        if not sess.select_row("BEGIN ADVENTURING"):
            raise RuntimeError("BEGIN ADVENTURING could not be selected")
        arrived = answer_bars(sess, seconds=args.arrive)
        if arrived != "world":
            sess.kbd.screenshot(str(out / "stuck.png"))
            raise RuntimeError(
                f"no world bar {args.arrive}s after BEGIN; "
                f"screen photographed to {out / 'stuck.png'}")
        sess.settle(3)
        where = sess.status()
        report["status"] = None if where is None else where.where()
        print(f"  status: {report['status']}")
        report["on_arrival"] = read_cache(sess)
        print(f"  on arrival: body slot "
              f"{describe_slot(report['on_arrival']['body_slot'])}, head slot "
              f"{describe_slot(report['on_arrival']['head_slot'])}")
        sess.kbd.screenshot(str(out / "world.png"))

        poke = {}
        for spec in args.poke:
            addr, _, value = spec.partition("=")
            poke[int(addr, 16)] = int(value, 0)
        for index in args.view:
            report["views"].append(
                sheet(sess, index, out / f"sheet-{index}.png", print, poke,
                      args.wait, args.prompt_side))
    finally:
        if sess is not None:
            sess.terminate()
        slot.release()
    (out / "report.json").write_text(json.dumps(report, indent=2))
    print(f"  wrote {out / 'report.json'}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--disk", required=True,
                   help="the save disk to boot; a bare name is looked for "
                        "beside the game sides")
    p.add_argument("--disks", default=DISKS,
                   help="where POOL1-8.D64 are")
    p.add_argument("--view", type=int, nargs="*", default=[0],
                   help="party slots to open VIEW on")
    p.add_argument("--words", nargs="*", default=[],
                   help="SAVEDGAME0 patches, ADDR=VALUE in hex, e.g. 49FF=0")
    p.add_argument("--portrait", nargs="*", default=[],
                   help="record patches, SLOT=HEAD/BODY in hex, e.g. 0=2D/25")
    p.add_argument("--poke", nargs="*", default=[],
                   help="RAM patches applied just before each VIEW, "
                        "ADDR=VALUE in hex, e.g. 49EB=1")
    p.add_argument("--slot", type=int, default=None, help="pool slot to claim")
    p.add_argument("--arrive", type=float, default=240.0)
    p.add_argument("--prompt-side", type=int, default=None,
                   help="answer a disk prompt raised by VIEW with this side, "
                        "whichever side the game asked for")
    p.add_argument("--wait", type=float, default=90.0,
                   help="seconds to wait for the sheet's own bar to come back")
    p.add_argument("--out", default="work/p57-c64probe")
    args = p.parse_args(argv)
    os.environ.setdefault("POR_HEADLESS", "1")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
