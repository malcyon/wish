#!/usr/bin/env python3
"""Fast-travel a *Secret of the Silver Blades* party, to confirm the area
table against the running machine.

`#20 (Build an area table for Silver Blades)` is the ticket. `tools/newecl.py`
found the addresses off this title's own overlays and `tools/areatable.py`
built the table off its own scripts; both are static readings, so every row of
`goldbox.areas.AREAS_SILVER_BLADES` is PROBABLE. **A party warped into an area
that then draws that area's map is what makes a row CONFIRMED**, and that is
what this measures.

    tools/ssbwarp.py --pool 3 --probe --out work/issue20/probe
    tools/ssbwarp.py --pool 3 --to 0x22 --disk 2 --out work/issue20/run1

`--probe` boots, loads a party and reports what the machine holds without
warping; it is what to run first, because the current area and the indoors
flag both decide whether a warp is legal.

**Six writes, not five.** Silver Blades' `NEWECL` zeroes `$4BFB` as well as the
32 bytes of scratch, which Pool of Radiance's and Curse's do not -- read off
the handler by `#19`. Eighteen of the twenty-two scripts set that byte again in
their own entry 4, so a driver that skipped it would be right by accident most
of the time; `ECL11`, `ECL44`, `ECL61` and `ECL62` never touch it and are where
it would show. The write is made here because the game makes it.

**Do not read the status line to check a step.** `$4BFB` is what suppresses the
coordinates on it -- `DUNGEON $0A0E` is `LDA $4BFB / BNE` over the block that
prints them -- and eleven of the twenty-two areas set it to 1 on arrival. The
live triple `$C04B`-`$C04D` is the only reliable reader, which is what `#19`
found the hard way in Curse.

Nothing is written to the player's disks: the six sides are copied into the
pool slot and every other byte this writes goes to RAM.
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

import newecl  # noqa: E402
import session as por  # noqa: E402

from automap.actions import pc_register  # noqa: E402
from goldbox import areas, games  # noqa: E402
from goldbox.d64 import D64  # noqa: E402

#: The live party square. **Not relocated in any title read so far**: page
#: `$C0` is `GDRIVE00`, and `DUNGEON`'s own position flush reads `$C04B,X`
#: here exactly as it does in Pool of Radiance and Curse.
LIVE_X, LIVE_Y, LIVE_FACING = 0xC04B, 0xC04C, 0xC04D

#: How long to give an arrival that comes off a floppy. A ceiling on a poll of
#: the program counter, not a fixed settle -- a fixed settle is a measurement
#: of the harness rather than of the game.
ARRIVAL_TIMEOUT = 240.0

#: `SILVER-1.D64` ... `SILVER-6.D64`, staged as `SIDE1` ... `SIDE6`. The digit
#: in the name is the side the loader prompts for: `tools/areatable.py` finds
#: 29 of 29 static disk writes agreeing with it, none disagreeing.
SIDE_GLOBS = ("SILVER-?.D64", "SILVER?.D64", "*Disk?.d64")

#: What this title draws when it wants another side, and when it wants the
#: save disk. Both are widened from Pool of Radiance's, because the wording is
#: not known to be the same and an unanswered prompt is a run that hangs
#: politely for its whole budget.
#: **`[1-6]`, not `[1-9A-F]`.** Curse's needle allows a hex letter because its
#: sides might have been lettered; this title has six numbered sides and
#: nothing else. Widening it cost a run: the loader drew a line the `A` branch
#: matched, `handle_prompt` attached `SIDE10.D64`, which does not exist, and
#: the game sat waiting for a disk that could never arrive
#: (`work/issue20/probe4`).
RE_SSB_SIDE = re.compile(
    r"INSERT\s+(?:YOUR\s+)?(?:GAME\s+)?(?:DISK|SIDE)\s*#?\s*([1-6])\b")
SAVE_PROMPT = "SAVE DISK"

#: A release check that names the character it wants, as Curse's does. Kept
#: because it costs nothing and its absence is itself a finding.
RE_START_CHECK = re.compile(r'TYPE THE CHARACTER "(.)"')


class Addresses:
    """Every address the warp needs, read out of this title's own overlays.

    Built by `tools/newecl.py`'s finders rather than written down, so the trap
    `#17` names -- an address taken from a PRG header, `$3800` out in this
    title -- has no way in. Silver Blades' `DUNGEON` header claims `$4000` and
    it runs at `$0800`.
    """

    def __init__(self, game: games.Game, disks: str, base: int = 0x0800):
        _, body = newecl.load("DUNGEON", disks, game)
        self.base, self.body = base, body
        call, lo_t, hi_t, opcode_at = newecl.dispatch_tables(body, base)
        self.opcode_byte = opcode_at
        self.handler = newecl.handler(body, base, lo_t, hi_t,
                                      newecl.NEWECL_OPCODE)
        lines = newecl.instructions(body, base, self.handler, 0x40)
        self.tail = newecl.newecl_tail(lines)
        # The handler's own operands are the writes. `LDA $xxxx / AND #$7F /
        # STA $yyyy` opens it: the first is the cache slot, the second where
        # the departing id is left.
        self.slot = int(lines[0][2][5:], 16)
        self.came_from = int(lines[2][2][5:], 16)
        # Two stores, not one, and this is the difference `#19` warned about.
        # `STA $4C00,X` is the 32-byte scratch wipe; the plain `STA $4BFB`
        # beside it is Silver Blades' own and has no counterpart in Pool of
        # Radiance or Curse. Both are taken from the handler rather than
        # assumed, so a title that makes five writes reports `extra` as None.
        self.scratch = next(int(t[5:9], 16) for _, _, t in lines
                            if t.startswith("STA $") and t.endswith(",X"))
        zeroed = [i for i, (_, _, t) in enumerate(lines) if t == "LDA #$00"]
        self.extra = None
        if zeroed:
            after = lines[zeroed[0] + 1:zeroed[0] + 4]
            self.extra = next((int(t[5:9], 16) for _, _, t in after
                               if t.startswith("STA $")
                               and not t.endswith(",X")), None)
        test = newecl.find_window(body, base, newecl.KEY_WAIT_SIG, "key-wait")
        if not test:
            raise SystemExit("DUNGEON's key-wait loop is not where its page-3 "
                             "signature says; nothing below can be trusted.")
        self.key_wait = newecl.loop_start(body, base, test)
        flush = int(lines[[i for i, ln in enumerate(lines)
                           if ln[0] == self.tail][0]][2][5:], 16)
        self.indoors = int(newecl.instructions(body, base, flush, 4)[0][2][5:],
                           16)
        _, lk = newecl.load("LINKER", disks, game)
        loads = [t for _, _, t in newecl.instructions(lk, 0, 0, 0x20)
                 if t.startswith(("LDA $", "STA $")) and "," not in t]
        self.mode = int(loads[0][5:], 16)
        self.disk = next((int(t[5:], 16) for t in loads[1:]
                          if int(t[5:], 16) == self.mode + 1), self.mode + 1)
        _, lib = newecl.load("LIBRARY", disks, game)
        called = next(int(t[5:], 16) for _, _, t
                      in newecl.instructions(body, base, self.key_wait[0], 0x10)
                      if t.startswith("JSR $"))
        off = lib.find(newecl.KEY_FETCH_SIG)
        self.key_fetch = (called, newecl.reachable_end(lib, called - off,
                                                       called))

    def as_dict(self) -> dict:
        return {"handler": self.handler, "tail": self.tail, "slot": self.slot,
                "came_from": self.came_from, "scratch": self.scratch,
                "extra": self.extra, "indoors": self.indoors,
                "mode": self.mode, "disk": self.disk,
                "key_wait": list(self.key_wait),
                "key_fetch": list(self.key_fetch),
                "opcode_byte": self.opcode_byte}

    def describe(self) -> str:
        extra = f"${self.extra:04X}" if self.extra else "none"
        return (f"mode ${self.mode:04X}  disk ${self.disk:04X}  "
                f"slot ${self.slot:04X}  came-from ${self.came_from:04X}  "
                f"scratch ${self.scratch:04X}  sixth write {extra}  "
                f"indoors ${self.indoors:04X}  "
                f"NEWECL ${self.handler:04X} tail ${self.tail:04X}  "
                f"key-wait ${self.key_wait[0]:04X}-${self.key_wait[1]:04X}  "
                f"fetch ${self.key_fetch[0]:04X}-${self.key_fetch[1]:04X}")


def stage(slot, disks: str, save: str = "") -> str:
    """Copy the six sides into the slot and put a save disk in `SIDE0`.

    The player's disks are read and never written; `Session.attach` refuses
    any path outside the slot's directory, so the only images the game is ever
    shown are these copies.

    **`SIDE0.D64` is always replaced.** A pool slot is reused, and the image
    the previous tenant left in it is another game's save disk -- which is how
    a Curse run once wrote four characters beside Pool of Radiance's.
    """
    slot.seed_vicerc()
    here = pathlib.Path(slot.dir)
    src = pathlib.Path(disks)
    sides: list[pathlib.Path] = []
    for pattern in SIDE_GLOBS:
        sides = sorted(src.glob(pattern))
        if len(sides) >= 6:
            break
    if len(sides) < 6:
        raise SystemExit(f"{disks} holds {len(sides)} Silver Blades sides, "
                         f"not six")
    for i, want in enumerate(sides[:6], start=1):
        shutil.copy(want, here / f"SIDE{i}.D64")
    target = here / "SIDE0.D64"
    if save:
        shutil.copy(save, target)
    else:
        # **The shipped party is `SAVEDBASH` on side 6**, and this title's
        # save file has that name, so a copy of side 6 is a save disk with a
        # party already on it. It is SSI's own demo party rather than one we
        # watched being written, and nothing here rests on what it *holds*:
        # it supplies six bodies to stand somewhere, and the evidence is the
        # map the running game loads.
        shutil.copy(here / "SIDE6.D64", target)
    return str(here / "SIDE1.D64")


class SSBSession(por.Session):
    """Pool of Radiance's driver with this title's prompts and boot."""

    def handle_prompt(self, s=None) -> bool:
        if time.time() - self._last_prompt < 2.0:
            return False
        if s is None:
            s = self.screen()
        if s is None:
            return False
        text = s.text()
        want = None
        if SAVE_PROMPT in text:
            want = self.save_disk
        else:
            m = RE_SSB_SIDE.search(text)
            if m:
                self.log(f"  prompt text: {m.group(0)!r}")
                want = f"{self.here}/SIDE{m.group(1)}.D64"
        if want is None:
            return False
        if not os.path.exists(want):
            # A needle that matches the wrong thing is worse than one that
            # matches nothing: attaching a missing image leaves the drive
            # holding whatever it held and the game waiting forever.
            self.log(f"  prompt names {os.path.basename(want)}, which is not "
                     f"staged -- not attaching")
            return False
        self._last_prompt = time.time()
        if os.path.abspath(want) != self.attached:
            self.log(f"  prompt -> {os.path.basename(want)}")
            self.attach(want)
        self.kbd.key("space")
        return True

    #: What to press at a screen nothing recognises, in turn. **This rip opens
    #: with a cracker intro** -- a scroller reading "Of The Silver Blades -
    #: FORGOTTEN REALM..." over the group's logo -- which is not the game and
    #: answers to none of the game's own keys. `KP_0` and `KP_5` are joystick
    #: port 2's fire on the keyset the pool seeds, which is how an intro of
    #: that vintage usually expects to be dismissed; `space` and `Return` are
    #: the ordinary answers. Pressing at an unrecognised screen is normally
    #: how a run ends up somewhere nobody can name, so it is confined to the
    #: boot, before any party exists to be moved.
    ANY_KEY = ("space", "Return", "KP_0", "KP_5")

    #: How long to leave the machine alone after the drive starts, and again
    #: after the fastloader is answered. **Measured, both directions.** With
    #: no quiet period the first keypress lands in the autostart and the run
    #: ends at `JIFFYDOS V6.01 ... READY.` with the game never loaded; with 20
    #: seconds the intro comes up and takes the key. A key pressed into a
    #: loader is not a key the game ever sees.
    QUIET = 25.0

    def boot(self, timeout: float = 480.0) -> bool:
        """Launch and get as far as the game's own party menu.

        Written to report rather than to guess: it logs every screen it does
        not recognise and gives up saying what it last saw.

        **The fastloader prompt comes after the intro, not before it.** In
        Pool of Radiance and Curse `DISABLE FASTLOADER (Y/N) ?` is the first
        thing on screen, so both drivers wait for it and then start. Here the
        cracker intro is first and the game's own title screen -- `SECRET OF
        THE SILVER BLADES / FORGOTTEN REALMS. / VERSION 1.0 / DISABLE
        FASTLOADER (Y/N)?` -- only appears once the intro has been dismissed.
        Waiting for it up front is a wait that cannot end, so the prompt is
        answered inside the loop like any other screen.
        """
        self.launch()
        deadline = time.time() + timeout
        quiet_until = time.time() + self.QUIET
        seen = ""
        n = 0
        while time.time() < deadline:
            s = self.screen()
            text = s.text() if s is not None else "(bitmap)"
            blank = not text.strip("@ \n")
            if "CREATE NEW CHARACTER" in text or "LOAD SAVED GAME" in text:
                self.log("reached the party menu")
                return True
            check = RE_START_CHECK.search(text)
            if "DISABLE FASTLOADER" in text:
                self.kbd.key(self.fastloader, 0.15, 0.28)
                self.log(f"fastloader: {self.fastloader.upper()}")
                quiet_until = time.time() + self.QUIET
            elif check:
                self.log(f"start-up check wants {check.group(1)!r}")
                self.press_kernal(ord(check.group(1)))
            elif self.handle_prompt(s):
                pass
            elif blank or time.time() < quiet_until:
                pass                    # a loader, or an area drawing itself
            else:
                key = self.ANY_KEY[n % len(self.ANY_KEY)]
                n += 1
                self.kbd.key(key)
                if n % len(self.ANY_KEY) == 0:
                    self.press_kernal(0x20)
            summary = text.strip()[:70].replace("\n", " ")
            if summary != seen:
                self.log(f"  boot: {summary!r}")
                seen = summary
            time.sleep(2.0)
        self.log(f"never reached the party menu; last screen {seen!r}")
        return False


def load_party(sess, timeout: float = 300.0) -> bool:
    """Get a party off the save disk and as far as the formation menu.

    Curse's two lessons are applied blind here, because they cost `#19` most
    of a session and neither is expensive to be wrong about: the save disk
    goes in the drive **before** the menu row is picked, since the game reads
    its save file off whatever is in unit 8 rather than prompting; and the
    confirmation is answered through the KERNAL buffer, because an XTEST
    Return does not move it.
    """
    if sess.wait_text("LOAD SAVED GAME", timeout)[0] is None:
        return False
    sess.attach(sess.save_disk)
    if not sess.select_row("LOAD SAVED GAME"):
        return False
    deadline = time.time() + timeout
    seen = ""
    while time.time() < deadline:
        s = sess.screen()
        if s is None:
            time.sleep(0.5)
            continue
        text = s.text()
        if "BEGIN ADVENTURING" in text:
            return True
        if sess.handle_prompt(s):
            time.sleep(1.0)
            continue
        bar = s.row(24).strip()
        if bar != seen:
            sess.log(f"  load: {bar!r}")
            seen = bar
        if "YES" in bar:
            sess.select_bar("YES")
            sess.press_kernal(0x0D)
        time.sleep(1.0)
    return False


#: What the loader draws when it wants a side, with the number in hex -- so
#: side 10 prints as `A`. Measured: `INSERT SIDE A, AND PRESS ANY KEY.`
RE_ANY_SIDE = re.compile(r"INSERT\s+SIDE\s+([0-9A-F])\b")


def impossible_side(sess, addr, text: str, fix: bool) -> dict | None:
    """Report -- and optionally correct -- a prompt for a side that is not one.

    **The shipped `SAVEDBASH` is a roster, not a party standing anywhere**:
    its whole world header is zero and the area byte at payload `0x2C2` is
    `$FF`. Loaded, the game draws the adventure screen with its six characters
    and then asks for `INSERT SIDE A` -- side 10 of six. So the run stops at a
    prompt no disk can answer, and what the loader thinks is worth reading
    before anything is done about it.

    With `fix`, the disk byte is set to a side that exists and a key is
    pressed, which is an edit to an *input* the game then computes from
    rather than a value read back and believed.
    """
    m = RE_ANY_SIDE.search(text)
    if not m:
        return None
    side = int(m.group(1), 16)
    if 1 <= side <= 6:
        return None
    state = snapshot(sess, addr)
    sess.log(f"  impossible side {side}: {json.dumps(state)}")
    if not fix:
        return state
    # **The disk byte is not what the prompt is printing.** `$7F12` reads 1
    # while the prompt says `A`, so writing 1 to it changes nothing and the
    # loop runs forever -- measured, `work/issue20/probe6`. What is left is
    # the ordinary answer to a disk prompt: put a disk in and press a key.
    # The staged sides are offered in turn, because which one it wants is
    # exactly what the prompt is failing to say.
    n = getattr(sess, "_side_rotation", 0)
    sess._side_rotation = n + 1
    want = f"{sess.here}/SIDE{(n % 6) + 1}.D64"
    sess.log(f"  offering {os.path.basename(want)}")
    sess.attach(want)
    sess.kbd.key("space")
    time.sleep(1.5)
    sess.press_kernal(0x20)
    return state


def enter_world(sess, addr, timeout: float = 600.0, fix: bool = True) -> bool:
    """Take a loaded party from the formation menu into the world.

    Act only on what is on screen, press nothing at a blank one -- 1024
    zeroes is an area drawing itself, not a menu waiting for a keypress --
    and back out with Escape only when some *other* menu has sat unchanged.
    """
    STUCK = 15.0
    deadline = time.time() + timeout
    seen, since = "", time.time()
    while time.time() < deadline:
        s = sess.screen()
        if s is None:
            time.sleep(0.5)
            continue
        text = s.text()
        if "ENCAMP" in text:
            return True
        if impossible_side(sess, addr, text, fix) is not None:
            time.sleep(2.0)
            continue
        if sess.handle_prompt(s):
            time.sleep(1.5)
            continue
        state = ("BEGIN" if "BEGIN ADVENTURING" in text
                 else "(blank)" if not text.strip("@ \n")
                 else s.row(24).strip())
        if state != seen:
            sess.log(f"  world: {state!r}")
            seen, since = state, time.time()
        if state == "BEGIN":
            sess.select_row("BEGIN ADVENTURING")
            sess.press_kernal(0x0D)
        elif "EXIT" in state and state != "ENCAMP":
            # The prologue hands the party its starting treasure and puts up
            # `VIEW TAKE POOL SHARE EXIT`. Nothing here wants the treasure --
            # the party only has to be somewhere -- so take the way out.
            sess.select_bar("EXIT", timeout=10)
            sess.press_kernal(0x0D)
            since = time.time()
        elif any(w in state for w in ("CONTINUE", "MORE", "PRESS")):
            # **The party arrives inside a script, not at a command bar.**
            # `ECL11` -- where the shipped save starts -- is four screens of
            # prologue, each closed by a one-option menu, and then
            # `SAVE 1, [$7F12] / NEWECL 16`. Escaping out of those is how a
            # run ends up with the party still in the prologue.
            sess.press_kernal(0x0D)
            since = time.time()
        elif state != "(blank)" and time.time() - since > STUCK:
            sess.log("  world: backing out with Escape")
            sess.kbd.key("Escape")
            since = time.time()
        time.sleep(1.5)
    return False


def ssb_maps(disks: str) -> dict:
    """Every `GEO` on every side, by name. Read once and reused."""
    from goldbox.geo import load_geo_files
    out: dict = {}
    for path in sorted(pathlib.Path(disks).glob("*.[dD]64")):
        try:
            out.update(load_geo_files(D64.open(str(path))))
        except Exception:
            continue
    return out


def resident_geo(sess, maps: dict) -> dict:
    """Which map is the one drawn at `$0400`, if any.

    `automap/area.py`'s verdict: an exact match against the disk copies
    first, then reciprocity and shared walled edges. A warp that lands has to
    change this, and a warp that only *looks* like it landed will not.
    """
    from automap.area import ResidentGeo

    class _Block:
        def __init__(self, data):
            self.data = data

        def read(self, addr, length):
            return self.data[addr - 0x0400:addr - 0x0400 + length]

    try:
        with sess.mon(8) as m:
            block = m.read(0x0400, 1024)
        verdict, name = ResidentGeo(_Block(block)).verdict(maps)
        return {"verdict": verdict, "name": name}
    except Exception as exc:                                # pragma: no cover
        return {"verdict": "unreadable", "name": None, "error": str(exc)}


def snapshot(sess, addr: Addresses) -> dict:
    """What the machine holds, in one monitor round trip."""
    with sess.mon(8) as m:
        return {
            "mode": m.peek(addr.mode),
            "disk": m.peek(addr.disk),
            "slot": m.peek(addr.slot),
            "area": m.peek(addr.slot) & 0x7F,
            "came_from": m.peek(addr.came_from),
            "indoors": m.peek(addr.indoors),
            "status_flag": m.peek(addr.extra) if addr.extra else None,
            "square": list(m.read(LIVE_X, 3)),
            "pc": m.registers().get(pc_register(m)),
        }


def wait_idle(sess, addr: Addresses, timeout: float = ARRIVAL_TIMEOUT):
    """Poll until the PC is back in the key-wait loop or its fetcher."""
    windows = (addr.key_wait, addr.key_fetch)
    deadline = time.time() + timeout
    pc = None
    while time.time() < deadline:
        try:
            with sess.mon(6) as m:
                pc = m.registers().get(pc_register(m))
        except Exception:
            pc = None
        if pc is not None and any(lo <= pc < hi for lo, hi in windows):
            return True, pc
        sess.handle_prompt()
        time.sleep(0.5)
    return False, pc


def warp(sess, addr: Addresses, target: int, disk: int,
         square: tuple[int, int, int] | None) -> dict:
    """`NEWECL`'s own writes, made from outside, then its tail.

    The order is the handler's, with the operand fetch left out because there
    is no script stream to fetch from. **Six writes**: the sixth is
    `addr.extra`, which the handler zeroes and Pool of Radiance's does not.
    """
    made = {}
    with sess.mon(10) as m:
        m.write(addr.disk, bytes([disk]))
        made["disk"] = disk
        if square is not None:
            m.write(LIVE_X, bytes(square))
            made["square"] = list(square)
        here = m.peek(addr.slot) & 0x7F
        m.write(addr.came_from, bytes([here]))
        made["came_from"] = here
        m.write(addr.slot, bytes([target | 0x80]))
        made["slot"] = target | 0x80
        m.write(addr.scratch, bytes(32))
        made["scratch_zeroed"] = 32
        if addr.extra:
            m.write(addr.extra, b"\x00")
            made["extra_zeroed"] = addr.extra
        rid = pc_register(m)
        m.set_registers({rid: addr.tail})
        made["pc"] = addr.tail
        m.resume()
    return made


def clear_messages(sess, timeout: float = 150.0) -> str:
    """Answer the arriving script's messages until the command bar is back."""
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


def walk_proof(sess, keys: str = "JIKI") -> dict:
    """Can the party that arrived actually move?

    One key, one reading, and the command bar read before each: a key sent an
    unknown number of times cannot be read off a table, and the session
    leaves MOVE mode after the first key.
    """
    out = {"bar": clear_messages(sess)}

    def triple():
        with sess.mon(8) as m:
            return list(m.read(LIVE_X, 3))

    out["triple_before"] = triple()
    steps = []
    for key in keys:
        s = sess.screen()
        bar = s.row(24).strip() if s is not None else ""
        if "I,J,K,M" not in bar:
            sess.select_bar("MOVE", timeout=10)
            time.sleep(0.8)
            s = sess.screen()
            bar = s.row(24).strip() if s is not None else ""
        sess.kbd.key(key.lower(), 0.15, 0.30)
        time.sleep(1.4)
        steps.append({"key": key, "bar": bar, "triple": triple()})
    out["steps"] = steps
    out["triple_after"] = steps[-1]["triple"] if steps else out["triple_before"]
    out["moved"] = out["triple_after"][:2] != out["triple_before"][:2]
    out["turned"] = any(s["triple"][2] != out["triple_before"][2]
                        for s in steps)
    sess.leave_move()
    return out


def screen_text(sess, path: pathlib.Path | None = None) -> str:
    """What the screen says now, saved beside the capture if asked."""
    s = sess.screen()
    text = s.text() if s is not None else "(bitmap or unreadable)"
    if path is not None:
        path.write_text(text)
    return text


def run(args) -> int:
    game = games.SECRET_OF_THE_SILVER_BLADES
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    addr = Addresses(game, args.disks)
    print("addresses:", addr.describe(), flush=True)
    (out / "addresses.json").write_text(json.dumps(addr.as_dict(), indent=1))

    row = areas.area_in(args.to, areas.SECRET_OF_THE_SILVER_BLADES)
    if row is None:
        print(f"no area ${args.to:02X} in the Silver Blades table", flush=True)
        return 2
    disk = args.disk or row.disk
    print(f"target ${args.to:02X}: {row.label}, disk {disk}", flush=True)

    maps = ssb_maps(args.disks)
    print(f"{len(maps)} maps read off the sides", flush=True)

    slot = por.claim_slot(args.pool, note=os.environ.get("POR_AGENT", "ssb20"))
    print(f"slot {slot.n}: monitor {slot.port} display {slot.display} "
          f"dir {slot.dir}", flush=True)
    sess = None
    try:
        save = args.save
        if save:
            staged = pathlib.Path(slot.dir) / "SAVE_IN.D64"
            shutil.copy(save, staged)
            save = str(staged)
        # `tools/session.py` carries Pool of Radiance's `$49E6` as a module
        # constant and `walk_one` reads it to choose which keys to press. In a
        # running Silver Blades that address is somebody else's bytes. Point
        # it at this title's own for this process only; the file is another
        # ticket's -- `#29 (The live reader uses Pool of Radiance's addresses
        # on every title)` -- and is not edited.
        por.INDOORS_AT = addr.indoors
        first = stage(slot, args.disks, save)
        sess = SSBSession(first, slot=slot)
        if not sess.boot():
            print("boot incomplete; the screen says:", flush=True)
            print(screen_text(sess, out / "stuck-boot.txt"), flush=True)
            sess.kbd.screenshot(str(out / "stuck-boot.png"))
            return 3
        if not load_party(sess):
            print("could not load a party; the screen says:", flush=True)
            print(screen_text(sess, out / "stuck-load.txt"), flush=True)
            sess.kbd.screenshot(str(out / "stuck-load.png"))
            return 3
        if not enter_world(sess, addr, fix=not args.no_fix_disk):
            print("never reached the world; the screen says:", flush=True)
            print(screen_text(sess, out / "stuck-world.txt"), flush=True)
            sess.kbd.screenshot(str(out / "stuck-world.png"))
            return 3
        sess.settle(4)
        ok, pc = wait_idle(sess, addr, 120)
        before = snapshot(sess, addr)
        before["resident"] = resident_geo(sess, maps)
        before["idle"] = ok
        s = sess.screen()
        before["screen"] = s.text() if s is not None else None
        print("before:", json.dumps({k: v for k, v in before.items()
                                     if k != "screen"}), flush=True)
        (out / "before.json").write_text(json.dumps(before, indent=1))
        sess.kbd.screenshot(str(out / "before.png"))
        if before["screen"]:
            (out / "before-screen.txt").write_text(before["screen"])

        if args.probe:
            return 0
        if not before["idle"]:
            print(f"the PC is ${pc:04X} and not in a key window; refusing",
                  flush=True)
            return 4
        if before["mode"] != 1:
            print(f"${addr.mode:04X} is {before['mode']}, not 1: DUNGEON is "
                  f"not resident and the tail is somebody else's code",
                  flush=True)
            return 4
        if not before["indoors"] and not args.force:
            print(f"${addr.indoors:04X} is 0, so the party is not indoors. "
                  f"Pool of Radiance wedges its loader warping out of the "
                  f"travel grid; pass --force to test that here.", flush=True)
            return 4
        if before["area"] == args.to:
            print(f"the party is already in area ${args.to:02X}", flush=True)
            return 4

        square = None
        if args.square:
            square = tuple(int(v, 0) for v in args.square.split(","))
        elif row.arrival is not None and args.place:
            a = row.arrival
            square = (a.x, a.y, a.facing or 0)
        print(f"arrival square: {square}", flush=True)

        made = warp(sess, addr, args.to, disk, square)
        print("wrote:", json.dumps(made), flush=True)
        (out / "writes.json").write_text(json.dumps(made, indent=1))

        landed, pc = wait_idle(sess, addr)
        sess.settle(3)
        after = snapshot(sess, addr)
        after["resident"] = resident_geo(sess, maps)
        after["idle"] = landed
        after["expected_geo"] = list(row.geos)
        if landed:
            after["walk"] = walk_proof(sess)
            after["resident_after_walk"] = resident_geo(sess, maps)
        s = sess.screen()
        after["screen"] = s.text() if s is not None else None
        print("after:", json.dumps({k: v for k, v in after.items()
                                    if k != "screen"}), flush=True)
        (out / "after.json").write_text(json.dumps(after, indent=1))
        sess.kbd.screenshot(str(out / "after.png"))
        if after["screen"]:
            (out / "after-screen.txt").write_text(after["screen"])
        return 0 if landed else 5
    finally:
        if sess is not None:
            sess.terminate()
        else:
            slot.teardown()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pool", type=int, default=None,
                    help="which pool slot to claim (default: any free one)")
    ap.add_argument("--disks", default=os.environ.get("POR_DISKS"),
                    help="where the six Silver Blades sides are")
    ap.add_argument("--save", default="",
                    help="a save disk to stage as SIDE0 (default: a copy of "
                         "side 6, which carries the shipped SAVEDBASH party)")
    ap.add_argument("--to", type=lambda v: int(v, 0), default=0x22,
                    help="the target area id, the ECL number")
    ap.add_argument("--disk", type=int, default=0,
                    help="which side carries that ECL (default: the table's)")
    ap.add_argument("--place", action="store_true",
                    help="write the table's arrival square before the warp; "
                         "omitted, the arriving script places the party")
    ap.add_argument("--square", default="",
                    help="write this x,y,facing instead")
    ap.add_argument("--probe", action="store_true",
                    help="boot and report, warp nothing")
    ap.add_argument("--no-fix-disk", action="store_true",
                    help="leave a prompt for a side that does not exist alone,"
                         " rather than writing a legal one and pressing a key")
    ap.add_argument("--force", action="store_true",
                    help="warp even when the indoors flag is clear")
    ap.add_argument("--out", default="work/issue20/run",
                    help="where captures go (default: %(default)s)")
    args = ap.parse_args(argv[1:])
    if not args.disks or not os.path.isdir(args.disks):
        # `tools/gamedisks.py` is the registry; `automap.paths.find_disks`
        # looks for a directory named after the game and nobody names one
        # that -- `#251 (Curse's and Silver Blades' disks are where nothing
        # looks for them, so every per-title test skips)`.
        import gamedisks
        found = gamedisks.find("secret-of-the-silver-blades")
        args.disks = str(found) if found else ""
    if not args.disks or not os.path.isdir(args.disks):
        print("No Silver Blades disks. Set $POR_DISKS or pass --disks.",
              file=sys.stderr)
        return 2
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
