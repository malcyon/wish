#!/usr/bin/env python3
"""Get a Curse party in through `LOAD SAVED GAME`, and measure any rejection.

`#291 (A Curse save disk will not load through the game's own front end in a
pooled session, so no C64 Curse party can be got in)` is the ticket, and three
separate faults were live at once behind one sentence --
`UNABLE TO LOAD SAVED GAME.`  `docs/179-loading-a-curse-save.md` has all three;
`load_saved_game()` below is the sequence that avoids them, for any other tool
that needs a Curse party.

**The routine that fails is `LIBRARY $3159`, and it is a KERNAL `LOAD`**:

    $3159  JSR $31A6        save A / X / Y
    $315C  JSR $319F        SETNAM, name length A, pointer self-modified
    $315F  LDA #$0F / LDX $038E / LDY #$00 / JSR $FFBA     SETLFS
    $3169  JSR $31B0        restore A / X / Y
    $316C  LDA #$00 / JSR $FFD5                            LOAD
    $3177  JMP $401E        turn the result into a number

The caller writes the *name pointer into the instruction*: `GEN $1F38` stores
`$66` at `$31A0` and `$1F` at `$31A2`, which are the operands of `LDX #$FF` /
`LDY #$FF` inside `$319F`, so the name is `GEN $1F66` -- `SAVEAZURE`.

`$401E` is where the answer comes from, and it has two arms:

    $401E  LDA $7E9F / BEQ $402D      the fastloader flag
    $4023  LDA #$00 / BCC $4029 / LDA #$3E / STA $03F1 / RTS
    $402D  ... TALK 8, TKSA 15, read the error channel, parse the number

`$7E9F` is 1 while the game's own fastloader is installed (`GEN $16F9`, after
`JSR $B700`) and 0 while it is not (`GEN $0840`, which also puts the KERNAL's
`$0330` vector back).  So on the party-formation menu, where no fastloader is
installed, **the number the game prints its rejection on is the 1541's own error
number**, and reading `$03F1` after the failure says which one.

That is what this tool does: it boots Curse in a pooled slot, attaches a save
disk in whichever way is being tested, drives the menu, and photographs the
outcome together with the bytes that name the cause -- `$03F1`, `$7E9F`,
`$03B4`, `$038E`, the KERNAL status at `$90`, the first bytes of the load
target at `$4B00`, and the drive's own error-message buffer read out of
memspace 1 at `$02D5`.

    tools/curse_of_the_azure_bonds/curseload.py --save ~/wish-specimens/por-c64/WISH-SPEC-...D64
    tools/curse_of_the_azure_bonds/curseload.py --save ... --repair            # close a splat entry first
    tools/curse_of_the_azure_bonds/curseload.py --save ... --serve             # and hand the session over

The rest of the flags are the differentials that separated the three faults
and are kept so the measurement can be taken again.  `--attach` says how the
save disk gets into the drive -- `plain` before the command, `detach` with a
detach in front of it, `prompt` only when the game asks.  `--prompt` says how
`INSERT CURSE SAVE DISK` is answered: `attach` the disk and press a key,
press a `key` with whatever is in the drive, or leave it alone with `none`.
`--pre-fail` takes one load with the game side still in the drive first, and
`--count` counts the four instructions that say what the game actually did.

Nothing outside the slot's own directory is written, and the player's disks
are opened read only.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import struct
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS.parent))

from automap import gamedisks  # noqa: E402
from automap.actions import pc_register  # noqa: E402
from goldbox import c64_port  # noqa: E402
from tools.areas import newecl  # noqa: E402
from tools.registry import scratch  # noqa: E402
from tools.secret_of_the_silver_blades.ssbsession import (  # noqa: E402
    GEN,
    MAX_BACKOUTS,
    MAX_WALKS,
    ModeReader,
    at_picker,
    choose_verified,
    cursor_on_begin,
    disk_prompt_up,
    leave_picker,
    load_started,
)

#: Every byte to read when the load has just failed, and why.
PROBES = {
    "03F1_error": (0x03F1, "what $401E returned: 0 is success, $3E is the "
                           "fastloader's failure, anything else is the "
                           "drive's own error number"),
    "7E9F_fastloader": (0x7E9F, "1 while the game's own loader is installed"),
    "03B4_disk": (0x03B4, "which disk the game believes is in the drive; 2 is "
                          "the save disk, and GEN $182D skips its prompt when "
                          "it already reads 2"),
    "038E_device": (0x038E, "the device number SETLFS is given"),
    "90_status": (0x90, "the KERNAL's I/O status byte"),
    "BA_device": (0xBA, "the KERNAL's current device"),
    "31A0_name_lo": (0x31A0, "the self-modified name pointer, low"),
    "31A2_name_hi": (0x31A2, "the self-modified name pointer, high"),
}

#: The 1541's error-message buffer, in the drive's own RAM.  It holds the
#: sentence the drive would send up its command channel -- `00, OK,00,00`,
#: `62,FILE NOT FOUND,00,00`, `73,CBM DOS V2.6 1541,00,00` -- so it says what
#: went wrong without the C64 having to be persuaded to ask.
DRIVE_ERROR_BUFFER = (0x02D5, 40)

CMD_MEM_GET = 0x01

#: The four instructions to count, all in `GEN` at `$0800`.  Counting
#: them settles what a screen poll is too slow to see: whether the save-disk
#: prompt was drawn at all, and how many times the load was actually taken.
COUNTERS = {
    "1F30_ask_for_disk": 0x1F30,   # JSR $182D, the save loader's disk check
    "183A_prompt_drawn": 0x183A,   # the arm $182D takes when $03B4 is not 2
    "1F48_load": 0x1F48,           # JSR $3159
    "1F4D_refused": 0x1F4D,        # the UNABLE TO LOAD message
}


def drive_read(m, start: int, length: int, memspace: int = 1) -> bytes:
    """Read the drive's memory.

    `Monitor.read` hardcodes memspace 0 (the C64), and the one thing to
    read here lives in the 1541.  The body is the same as the monitor's own
    `MEM_GET`, with the memspace byte filled in.
    """
    body = struct.pack("<BHHBH", 0, start, start + length - 1, memspace, 0)
    rid = m._send(CMD_MEM_GET, body)
    _, _, resp = m._read_response(rid)
    n = struct.unpack("<H", resp[:2])[0]
    return resp[2:2 + n]


def petscii(raw: bytes) -> str:
    return "".join(chr(b) if 32 <= b < 127 else "." for b in raw)


def probe(sess) -> dict:
    """Every diagnostic byte, in one monitor connection."""
    out: dict[str, object] = {}
    with sess.mon(8) as m:
        for name, (addr, _why) in PROBES.items():
            out[name] = m.peek(addr)
        out["4B00"] = m.read(0x4B00, 16).hex()
        try:
            raw = drive_read(m, *DRIVE_ERROR_BUFFER)
            out["drive_error"] = petscii(raw)
        except Exception as exc:                     # noqa: BLE001
            out["drive_error"] = f"({type(exc).__name__}: {exc})"
    return out


def highlighted(sess, column: int) -> list[int]:
    """Rows whose colour RAM reads white at `column`, which is the highlight.

    Measured with the party-formation menu up: the highlighted
    line's text is colour 1 and the other lines' is colour 5, over identical
    screen codes -- there is no inverse video anywhere on this screen, so
    reading bit 7 finds nothing.  The column matters because every border row
    is white too, and `Session.select_row`'s dominant-colour scan therefore
    answers rows that are not menu lines at all.
    """
    return [r for r in range(25) if sess.colours(r)[column] == 1]


def walk_menu(sess, label: str, timeout: float = 40.0) -> bool:
    """Move the menu highlight onto `label` and press Return.

    Return goes through the KERNAL buffer: this front end does not read an
    XTEST Return, which is the same finding
    `tools/curse_of_the_azure_bonds/cursewarp.py` records for the
    `LOAD SAVED GAME ? YES NO` bar.  The arrows *are* read from XTEST.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = sess.screen()
        if s is None:
            time.sleep(0.3)
            continue
        hit = s.find(label)
        if hit is None:
            sess.handle_prompt(s)
            time.sleep(0.3)
            continue
        hot = highlighted(sess, hit[1])
        if not hot:
            time.sleep(0.3)
            continue
        cur = min(hot, key=lambda r: abs(r - hit[0]))
        if cur == hit[0]:
            sess.press_kernal(0x0D)
            return True
        sess.kbd.key("Down" if cur < hit[0] else "Up")
        time.sleep(0.2)
    return False


def answer_yes(sess, word: str = "YES", row: int = 24,
               timeout: float = 25.0) -> bool:
    """Put the bar highlight on `word` and answer with **one** key.

    `Session.select_bar` walks the highlight and then presses Return over
    XTEST.  Curse does not read Return from XTEST -- but the KERNAL's own
    interrupt still puts it in the buffer at `$0277`, so a `select_bar`
    followed by a `press_kernal` leaves **two** Returns queued.  The bar
    takes the first, and `INSERT CURSE SAVE DISK, PRESS A KEY` -- which
    `LIBRARY $2FF8` waits for with any key at all -- takes the second, in
    less time than it takes to poll the screen.  That is how a driven session
    loads with the game side still in the drive.

    So the walk is XTEST, which Curse does read, and the answer is one
    `press_kernal` and nothing else.
    """
    from tools.c64.session import span_in  # noqa: PLC0415

    deadline = time.time() + timeout
    while time.time() < deadline:
        s = sess.screen()
        if s is None:
            time.sleep(0.3)
            continue
        col = s.row(row).find(word.upper())
        span = span_in(s, row)
        if col < 0 or span is None:
            time.sleep(0.3)
            continue
        if span[0] == col:
            sess.press_kernal(0x0D)
            return True
        sess.kbd.key("Right" if span[0] < col else "Left")
        time.sleep(0.25)
    return False


def arm(sess) -> dict:
    """A non-stopping execute checkpoint on each of `COUNTERS`."""
    with sess.mon(8) as m:
        armed = {k: m.checkpoint_set(a, exec_=True, stop=False)
                 for k, a in COUNTERS.items()}
        m.resume()
    return armed


def counts(sess, armed: dict) -> dict:
    with sess.mon(8) as m:
        got = {k: m.checkpoint_hits(n) for k, n in armed.items()}
        m.resume()
    return got


def detach(sess, unit: int = 8) -> None:
    """Take the image out of the drive and let the drive notice.

    VICE signals a disk change by pulsing the write-protect line, which is
    what a 1541 watches to know its BAM is stale.  An `attach` over an image
    that is already there has been seen not to produce one (`#192`'s second
    `ENCAMP > SAVE` came back `--SAVE ERROR--` until the image was detached
    and put back), so this is the other half of that differential.
    """
    with sess.mon(5):
        sess.text.sendall(f"detach {unit}\n".encode())
        time.sleep(0.6)
        try:
            sess.text.recv(65536)
        except Exception:                            # noqa: BLE001
            pass
    sess.attached = ""
    sess.log(f"  detached unit {unit}")


def close_splat(path: str) -> list[dict]:
    """Close any unclosed file in a **copy** of a disk image, in place.

    A 1541 marks a file open for writing with the top bit of its directory
    type byte clear -- `$02` rather than `$82`, which a directory listing
    shows as `*PRG` -- and fills the block count in only when the file is
    closed.  A disk pulled out of an emulator before the drive finished
    closing looks exactly like that, and the game will not read one: the load
    comes back `60, WRITE FILE OPEN`.

    The payload is already on the disk, because the data blocks are written
    before the directory entry is finished, so setting the bit and the count
    is enough to make the image loadable.  It is done to the staged copy in
    the pool slot and never to the file it was copied from.

    Returns one dict per entry changed, which is what a report needs.
    """
    from goldbox.d64 import D64  # noqa: PLC0415

    image = D64.open(path)
    raw = bytearray(image.to_bytes())
    changed = []
    for entry in image.iter_directory():
        if entry.is_empty or entry.is_closed:
            continue
        payload = len(image.read_file(entry.name))
        blocks = D64.blocks_needed(payload)
        at = entry.offset
        was = (raw[at], raw[at + 28] | (raw[at + 29] << 8))
        raw[at] |= 0x80
        raw[at + 28], raw[at + 29] = blocks & 0xFF, blocks >> 8
        changed.append({"name": entry.name.decode("latin1"),
                        "type_was": f"${was[0]:02X}", "type_now":
                        f"${raw[at]:02X}", "blocks_was": was[1],
                        "blocks_now": blocks, "bytes": payload})
    if changed:
        pathlib.Path(path).write_bytes(bytes(raw))
    return changed


def refuse_open_entries(path: str) -> None:
    """Refuse a disk image with a directory entry the drive never closed.

    Closing such an entry by hand cannot show whether its data chain holds the
    game's write or the save before it: the two images differ only in payload
    bytes, so a staged disk built on one could carry the old party.  The way
    out is to re-drive the save until the drive has flushed and closed it.
    Writes nothing.
    """
    from goldbox.d64 import D64  # noqa: PLC0415

    open_names = [e.display_name for e in D64.open(path).iter_directory()
                  if not e.is_empty and not e.is_closed]
    if open_names:
        raise SystemExit(
            f"{path} has an open directory entry ({', '.join(open_names)}): "
            "the drive never finished writing the file, so its data chain "
            "may still hold the previous save and cannot be checked. "
            "Re-drive the save until the drive has closed the file; do not "
            "close the entry by hand.")


def answer_prompt(sess, how: str = "attach", note=None) -> bool:
    """Deal with `INSERT CURSE SAVE DISK, PRESS A KEY`.

    Three answers, on purpose.  `attach` puts the save disk in the drive and
    then presses a key, which is the only one that loads anything; `key`
    presses a key with whatever is already in the drive, which is the state a
    hand-driven session reaches when the person answers the prompt before
    swapping the image; `none` leaves the prompt standing.

    The key goes through the KERNAL buffer, because `LIBRARY $2FD7` -- what
    the wait at `$2FF8` polls -- reads `$C6` and `$0277`.  It also reads
    `$DC00` for a joystick, so a run with one mapped can get past this prompt
    with nobody pressing anything.
    """
    if how == "none":
        return False
    if time.time() - sess._last_prompt < 2.0:
        return False
    last_want = getattr(sess, "_last_want", None)
    if (last_want == sess.save_disk
            and time.time() - sess._last_prompt < sess.PROMPT_HOLD):
        return False
    sess._last_want = sess.save_disk
    sess._last_prompt = time.time()
    if how == "attach":
        sess.attach(sess.save_disk)      # and `Session.attach` settles
    if note:
        note(event="save-disk-prompt", how=how,
             attached=os.path.basename(sess.attached))
    sess.press_kernal(0x20)
    sess._last_prompt = time.time()
    return True


def bar_up(sess, budget: float) -> bool:
    """Wait for `LOAD SAVED GAME ? YES NO` to be the thing on row 24.

    A rejection prints `UNABLE TO LOAD SAVED GAME.` there first and puts the
    question back a moment later, so a retry that looks once looks at the
    message and decides the bar is not there.
    """
    deadline = time.time() + budget
    while time.time() < deadline:
        s = sess.screen()
        if s is not None and "LOAD SAVED GAME ?" in s.row(24):
            return True
        time.sleep(0.5)
    return False


def load_saved_game(sess, *, note=None, shot=None, wait: float = 90.0,
                    prompt: str = "attach", retry: bool = False,
                    tag: str = "load") -> str:
    """Get a Curse party in through the game's own front end.

    **This is the sequence, and the order of it is the whole of it**
    (`#291`):

    1. walk the party menu to `LOAD SAVED GAME` and press Return once,
       through the KERNAL buffer;
    2. answer `LOAD SAVED GAME ? YES NO` with **one** key -- see
       `answer_yes`, because two queue up and the second one answers the next
       question before anybody has read it;
    3. answer `INSERT CURSE SAVE DISK, PRESS A KEY` by attaching
       `sess.save_disk` and *then* pressing a key.  `Session.attach` waits
       out the drive's own settling time, without which the load comes back
       `74, DRIVE NOT READY`;
    4. watch for `BEGIN ADVENTURING`, which is the party being in.

    Returns `loaded`, `failed`, `timeout`, `menu-miss` or `bar-miss`.  Call it
    again with `retry=True` after a `failed`: the rejection leaves the question
    up rather than the menu, and this answers whichever of the two is there.
    """
    def say(**kw):
        if note:
            note(**kw)

    def picture(name: str):
        if shot:
            shot(name)

    # **A rejection leaves the question up, not the menu.**  `GEN $1F52` is
    # `JMP $1F1E`, which redraws `LOAD SAVED GAME ? YES NO` -- so a retry
    # answers the bar that is already there, and walking the menu for a label
    # that is only the bar's own text never presses anything.
    if bar_up(sess, 25.0 if retry else 2.0):
        say(event="bar-already-up", attempt=tag)
    elif not walk_menu(sess, "LOAD SAVED GAME"):
        say(event="menu-miss", attempt=tag)
        picture(f"{tag}-menu-miss")
        return "menu-miss"
    time.sleep(1.0)
    picture(f"{tag}-bar")
    if not answer_yes(sess):
        say(event="bar-miss", attempt=tag)
        return "bar-miss"
    say(event="yes", attempt=tag)

    outcome, deadline = "timeout", time.time() + wait
    while time.time() < deadline:
        time.sleep(1.5)
        s = sess.screen()
        if s is None:
            continue
        text = s.text()
        if "UNABLE TO LOAD" in text:
            outcome = "failed"
            break
        if "BEGIN ADVENTURING" in text:
            outcome = "loaded"
            break
        if "SAVE DISK" in text:
            answer_prompt(sess, prompt, note)
        else:
            sess.handle_prompt(s)        # a side prompt is still a prompt
    picture(f"{tag}-{outcome}")
    return outcome


class Addresses:
    """Every address the warp needs, read out of this title's own overlays.

    Built by `tools/areas/newecl.py`'s finders rather than written down, so the one
    trap `#17` names -- an address taken from a PRG header, `$800` out -- has
    no way in.  The `save` base is `Game.save_load_address`, which is the only
    number here that comes from a table, and the two fields derived from it
    are checked against the operands `NEWECL` itself uses.
    """

    def __init__(self, game: c64_port.C64Container, disks: str, base: int = 0x0800):
        _, body = newecl.load("DUNGEON", disks, game)
        self.base, self.body = base, body
        call, lo_t, hi_t, opcode_at = newecl.dispatch_tables(body, base)
        self.opcode_byte = opcode_at
        self.handler = newecl.handler(body, base, lo_t, hi_t,
                                      newecl.NEWECL_OPCODE)
        lines = newecl.instructions(body, base, self.handler, 0x40)
        self.tail = newecl.newecl_tail(lines)
        # The handler's own operands are the writes, so take them from there.
        # `LDA $xxxx / AND #$7F / STA $yyyy` opens it: the first is the cache
        # slot, the second where the departing id is left.
        self.slot = int(lines[0][2][5:], 16)
        self.came_from = int(lines[2][2][5:], 16)
        self.scratch = next(int(t[5:9], 16) for _, _, t in lines
                            if t.startswith("STA $") and t.endswith(",X"))
        test = newecl.find_window(body, base, newecl.KEY_WAIT_SIG, "key-wait")
        if not test:
            raise SystemExit("DUNGEON's key-wait loop is not where its page-3 "
                             "signature says; nothing below can be trusted.")
        self.key_wait = newecl.loop_start(body, base, test)
        # The indoors flag is what the position flush tests before copying
        # `$C04B` into the save, and the flush is the handler's own tail call.
        flush = int(lines[[i for i, ln in enumerate(lines)
                           if ln[0] == self.tail][0]][2][5:], 16)
        self.indoors = int(newecl.instructions(body, base, flush, 4)[0][2][5:],
                           16)
        # `LINKER`'s first two absolute operands are the mode flag and the
        # disk byte; they are base-independent, so `LINKER`'s own load address
        # never has to be known.
        _, lk = newecl.load("LINKER", disks, game)
        loads = [t for _, _, t in newecl.instructions(lk, 0, 0, 0x20)
                 if t.startswith(("LDA $", "STA $")) and "," not in t]
        self.mode = int(loads[0][5:], 16)
        # The disk byte is the flag's neighbour -- `$6E11`/`$6E12` in Pool of
        # Radiance, `$7F11`/`$7F12` here -- and Curse's `LINKER` names it in
        # its own prologue, which Pool of Radiance's does not have. Prefer
        # what the file says and fall back to the neighbour, recording which.
        self.disk = next((int(t[5:], 16) for t in loads[1:]
                          if int(t[5:], 16) == self.mode + 1), self.mode + 1)
        self.disk_named = any(t.endswith(f"${self.disk:04X}") for t in loads[1:])
        _, lib = newecl.load("LIBRARY", disks, game)
        called = next(int(t[5:], 16) for _, _, t
                      in newecl.instructions(body, base, self.key_wait[0], 0x10)
                      if t.startswith("JSR $"))
        off = lib.find(newecl.KEY_FETCH_SIG)
        self.key_fetch = (called, newecl.reachable_end(lib, called - off,
                                                       called))

    def as_dict(self) -> dict:
        return {
            "handler": self.handler, "tail": self.tail, "slot": self.slot,
            "came_from": self.came_from, "scratch": self.scratch,
            "indoors": self.indoors, "mode": self.mode, "disk": self.disk,
            "key_wait": list(self.key_wait), "key_fetch": list(self.key_fetch),
            "opcode_byte": self.opcode_byte,
        }

    def describe(self) -> str:
        return (f"mode ${self.mode:04X}  disk ${self.disk:04X}  "
                f"slot ${self.slot:04X}  came-from ${self.came_from:04X}  "
                f"scratch ${self.scratch:04X}  indoors ${self.indoors:04X}  "
                f"NEWECL ${self.handler:04X} tail ${self.tail:04X}  "
                f"key-wait ${self.key_wait[0]:04X}-${self.key_wait[1]:04X}  "
                f"fetch ${self.key_fetch[0]:04X}-${self.key_fetch[1]:04X}")


def idle_in_key_window(sess, addr: Addresses) -> int | None:
    """The PC, if the machine is sitting in a key window right now.

    A single read rather than `tools/secret_of_the_silver_blades/ssbwarp.py`'s multi-sample poll of the
    same name. `ssbwarp.py` needs several readings with the screen unchanged
    across them because it uses a confirmed idle PC to *warp* -- jump the
    party's own execution -- and its worry is the ECL interpreter's own print
    routine passing through the key-wait window as ordinary control flow
    while it is still printing, which a single sample could not tell apart
    from genuinely parking there.

    This function only ever gates a single Escape keypress, and the failure
    it exists to rule out (`#568 (cursewarp.py and ssbwarp.py can abort a
    mid-load ECL script by sending Escape to a screen that is merely slow,
    not stuck)`) is a KERNAL `LOAD` still running underneath an unchanged
    screen -- not a print in progress. A `LOAD` runs entirely in KERNAL ROM,
    nowhere near `DUNGEON`'s own `key_wait`/`key_fetch` addresses, so a PC
    reading that lands inside either window cannot be a load caught
    mid-flight; it is the game's own code actually waiting there. That is a
    different question from `ssbwarp.py`'s, which is why the same window
    pair is answered here with one read rather than four.

    `enter_world` also only calls this after its own `STUCK` wait has the
    screen sitting unchanged for fifteen seconds, and keeps calling it every
    pass of its loop for as long as that holds -- so a reading here is never
    the first look at a freshly-stalled screen.

    `DUNGEON`'s key-wait loop and `LIBRARY`'s fetcher are the two windows
    `NEWECL`'s tail can safely be entered from -- the same ones `wait_idle`
    polls for after a warp -- so the same pair of ranges answers this too.
    """
    windows = (addr.key_wait, addr.key_fetch)
    try:
        with sess.mon(6) as m:
            pc = m.registers().get(pc_register(m))
    except Exception:
        return None
    if pc is None or not any(lo <= pc < hi for lo, hi in windows):
        return None
    return pc


def enter_world(sess, addr: Addresses | None = None, timeout: float = 300.0
                ) -> bool:
    """Take a loaded party from the formation menu into the world.

    `Session.begin_adventuring` picks the row once and then waits, and two
    things get in the way of that here, both recorded rather than guessed:

    * **A disk prompt can be up when the row is picked.**  Loading the party
      pulls in side 2, so `INSERT SIDE # 2, AND PRESS ANY KEY.` sits over the
      menu; a pick made then opened a submenu and lost `BEGIN ADVENTURING`
      off the screen entirely (a capture in scratch, deleted).
    * **The screen goes blank while the area draws.**  1024 zeroes is not a
      menu that needs a keypress, and pressing one into it is how a run ends
      up somewhere nobody can name.

    So: act only on what is on screen, press nothing at a blank screen, and
    back out with Escape only when some *other* menu has been sitting there
    unchanged for `STUCK` seconds -- and, with `addr` given, only once the PC
    is confirmed sitting in a key window rather than mid-load (#568): Escape
    is VICE's RUN/STOP, which aborts a KERNAL LOAD in progress, and a screen
    can sit unchanged for `STUCK` seconds either because a menu is waiting or
    because a disk load has not finished drawing anything yet.

    A failed walk onto BEGIN ADVENTURING sends no Return, because one then
    chooses whichever entry is white; a list the menu opens on the party is
    left through its own EXIT row.

    **`addr` is optional only for the callers that do not yet pass one** --
    `tools/gui/livecheck.py`, `tools/c64/inventorycheck.py` and `tools/curse_of_the_azure_bonds/cursecheck.py`
    all call this without an `Addresses`, and giving `addr` no default would
    break them outright; without it, this falls back to the old unconditional
    Escape and cannot tell a stuck menu from a slow load.
    """
    STUCK = 15.0
    deadline = time.time() + timeout
    seen, since = "", time.time()
    walk_failures = backouts = 0
    modes = ModeReader(sess, addr) if addr is not None else None
    while time.time() < deadline:
        if modes is not None:
            if modes.dead:
                sess.log(f"  world: LINKER's mode byte ${addr.mode:04X} "
                         f"could not be read {modes.failures} times running; "
                         f"giving up rather than guess which overlay is "
                         f"running")
                return False
            modes.new_pass()
        if sess.iec_stall_check():
            # It has logged where the machine was; the rest of the timeout
            # would only wait on a drive the C64 has stopped listening to.
            return False
        s = sess.screen()
        if s is None:
            time.sleep(0.5)
            continue
        text = s.text()
        if "ENCAMP" in text:
            return True
        picker_mode = (GEN if modes is None else modes()) \
            if at_picker(s) else None
        if at_picker(s) and picker_mode is None:
            # The words are up but the mode byte could not be read: press
            # nothing, neither the EXIT walk nor the STUCK branch's Escape,
            # until a read says whose screen it is.
            time.sleep(1.5)
            continue
        if picker_mode == GEN:
            # `MODIFY WHICH CHARACTER?` and `VIEW WHICH CHARACTER?`, the
            # lists the party menu opens on the party: left through their own
            # EXIT row, never with the Escape the STUCK branch below would
            # send. `GEN` is the only file on Curse's disks carrying the
            # words; the mode byte, when `addr` gives it, confirms GEN runs.
            bar = s.row(24).strip()
            if backouts >= MAX_BACKOUTS:
                sess.log(f"  world: still at {bar!r} after {backouts} tries "
                         f"to leave it through EXIT; giving up")
                return False
            backouts += 1
            sess.log(f"  world: {bar!r} is a party-menu list, not the "
                     f"world; leaving it through EXIT")
            leave_picker(sess, s)
            seen, since = "", time.time()
            time.sleep(1.5)
            continue
        if sess.handle_prompt(s):
            time.sleep(1.5)
            continue
        state = ("BEGIN" if "BEGIN ADVENTURING" in text
                 else "(blank)" if not text.strip("@ \n") else s.row(24).strip())
        if state != seen:
            sess.log(f"  world: {state!r}")
            seen, since = state, time.time()
        if state == "BEGIN":
            # The menu stays drawn through the load and the side 2 prompt
            # that interrupts it; only a menu with an entry still white is
            # waiting for a key.
            if not load_started(s) and not choose_verified(
                    sess, "BEGIN ADVENTURING", cursor_on_begin):
                walk_failures += 1
                sess.log(f"  world: no Return sent, because the highlight "
                         f"is not on BEGIN ADVENTURING "
                         f"({walk_failures} of {MAX_WALKS})")
                if walk_failures >= MAX_WALKS:
                    sess.log("  world: giving up rather than choose "
                             "whichever entry is highlighted")
                    return False
        elif any(w in state for w in ("CONTINUE", "MORE", "PRESS")) \
                and not disk_prompt_up(text):
            # Not a disk prompt `handle_prompt` is holding back from
            # answering twice: its PRESS ANY KEY wants a disk first.
            # Curse's own opening page -- row 24 reads "PRESS BUTTON OR
            # RETURN TO CONTINUE." -- is a one-option menu behind which the
            # world has already loaded, the same kind of screen
            # `ssbsession.enter_world` dismisses for Silver Blades' own
            # prologue. Left unhandled this falls through to the STUCK
            # branch below and burns the whole timeout in silence.
            sess.press_kernal(0x0D)
            since = time.time()
        elif state != "(blank)" and time.time() - since > STUCK:
            idle = idle_in_key_window(sess, addr) if addr is not None else True
            if idle is not None:
                sess.log("  world: backing out with Escape" +
                         (f" (idle at ${idle:04X})" if addr is not None else ""))
                sess.kbd.key("Escape")
                since = time.time()
            else:
                # A stuck-but-not-idle state (a firmware wait, a submenu
                # this loop's own state matching does not otherwise cover)
                # now runs out the clock on `timeout` in silence instead of
                # ever getting an Escape -- traded deliberately, because
                # Escape aborting a load that was only slow was the more
                # common and more damaging failure (#568).
                sess.log("  world: screen stuck but not idle in a key "
                         "window; assuming a slow load and waiting")
        time.sleep(1.5)
    sess.log(f"  world: never reached; where the machine was: "
             f"{sess.stall_capture()}")
    return False


def clear_messages(sess, timeout: float = 120.0) -> str:
    """Answer the arriving script's messages until the command bar is back.

    An arrival has a scene in front of it -- warping into area `$03` printed
    four lines about the Tilverton sewers and then
    `PRESS BUTTON OR RETURN TO CONTINUE.` -- and a party behind a message is
    not yet a party that can be shown to walk.  Returns whatever row 24 says
    when it stops.
    """
    deadline = time.time() + timeout
    seen = ""
    while time.time() < deadline:
        s = sess.screen()
        if s is None:
            time.sleep(0.5)
            continue
        bar = s.row(24).strip()
        if bar != seen:
            sess.log(f"  bar: {bar!r}")
            seen = bar
        if "ENCAMP" in bar:
            return bar
        if sess.handle_prompt(s):
            time.sleep(1.0)
            continue
        if "CONTINUE" in bar or "MORE" in bar or "PRESS" in bar:
            sess.press_kernal(0x0D)
        time.sleep(1.0)
    return f"(never got the command bar back; last {seen!r})"


def run(args) -> int:
    from tools.c64 import session as por  # noqa: PLC0415
    from tools.curse_of_the_azure_bonds import curserun  # noqa: PLC0415

    found = args.disks or gamedisks.find("curse-of-the-azure-bonds")
    if not found:
        raise SystemExit("no Curse disks; pass --disks")
    disks = str(found)

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
        text = "(bitmap)" if s is None else "\n".join(s.row(r) for r in range(25))
        (out / f"{tag}.txt").write_text(text + "\n")

    def attempt(tag: str, retry: bool = False) -> str:
        outcome = load_saved_game(sess, note=note, shot=shot, wait=args.wait,
                                  prompt=args.prompt, retry=retry, tag=tag)
        note(event=outcome, attempt=tag, **probe(sess),
             **(counts(sess, armed) if armed else {}))
        return outcome

    slot = por.claim_slot(args.pool, note=os.environ.get("POR_AGENT", "i291"))
    note(event="slot", n=slot.n, monitor=slot.port, cmd=slot.cmd_port,
         display=slot.display, dir=str(slot.dir), attach_mode=args.attach)
    disk = curserun.stage(slot, disks, args.save)
    save_disk = str(pathlib.Path(slot.dir) / "SIDE0.D64")
    os.chmod(save_disk, 0o644)   # the specimen tree is read-only; the copy is ours
    if args.repair:
        # Before the boot: the staged copy is not in the drive yet, and
        # rewriting an image VICE has attached is a different kind of mistake.
        note(event="repaired", entries=close_splat(save_disk))
    sess = curserun.CurseSession(disk, slot=slot)
    sess.save_disk = save_disk
    outcome, armed = "not reached", {}
    try:
        note(event="booting", save=args.save)
        if not sess.boot():
            note(event="boot-failed")
            return 1
        note(event="booted", **probe(sess))
        shot("00-party-menu")
        if args.count:
            armed.update(arm(sess))
            note(event="armed", **armed)

        if args.pre_fail:
            # The control: enter the command with the *game* side still in the
            # drive.  What the game does next is the whole question, because a
            # hand-driven session reaches this state by accident.
            note(event="pre-fail", attached=os.path.basename(sess.attached))
            note(event="pre-fail-outcome", outcome=attempt("01-prefail"))

        if args.attach == "plain":
            sess.attach(save_disk)
        elif args.attach == "detach":
            detach(sess)
            sess.attach(save_disk)
        elif args.attach == "prompt":
            pass                       # answer_prompt does it when asked
        note(event="attached", how=args.attach, **probe(sess))

        if args.poke_03b4 is not None:
            with sess.mon(5) as m:
                m.write(0x03B4, bytes([args.poke_03b4]))
            note(event="poked", addr="03B4", value=args.poke_03b4)

        outcome = attempt("02-load", retry=args.pre_fail)
        if args.serve:
            por.serve(sess)
        return 0 if outcome == "loaded" else 1
    finally:
        note(event="done", outcome=outcome)
        if not args.serve:
            sess.close()
            slot.teardown()
        log.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--save", required=True, help="the save disk to load")
    ap.add_argument("--disks", default="", help="where the Curse sides are")
    ap.add_argument("--pool", type=int, default=None)
    ap.add_argument("--attach", default="plain",
                    choices=("plain", "detach", "prompt"),
                    help="how the save disk gets into the drive")
    ap.add_argument("--poke-03b4", type=lambda s: int(s, 0), default=None,
                    help="write this at $03B4 before the command is entered")
    ap.add_argument("--pre-fail", action="store_true",
                    help="take LOAD SAVED GAME once with the game side still "
                         "in the drive, as the control")
    ap.add_argument("--prompt", default="attach",
                    choices=("attach", "key", "none"),
                    help="what to do at INSERT CURSE SAVE DISK: attach the "
                         "save disk and press a key, press a key with "
                         "whatever is in the drive, or leave it standing")
    ap.add_argument("--repair", action="store_true",
                    help="close any splat file in the staged copy of the save "
                         "disk, which the drive otherwise refuses with 60")
    ap.add_argument("--count", action="store_true",
                    help="count GEN $1F30, $183A, $1F48 and $1F4D, which says "
                         "whether the save-disk prompt was drawn at all")
    ap.add_argument("--wait", type=float, default=90.0,
                    help="seconds to wait for the load to say something")
    ap.add_argument("--serve", action="store_true",
                    help="hand the session over on the command port at the end")
    ap.add_argument("--out", default=str(scratch.scratch_dir("curseload")))
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
