"""The Silver Blades C64 session, the way in to its world, and the addresses it needs."""
from __future__ import annotations

import json
import os
import pathlib
import re
import time

from automap.actions import pc_register
from goldbox import c64_port
from tools.areas import newecl
from tools.c64 import session as por

#: The live party square. **Not relocated in any title read so far**: page
#: `$C0` is `GDRIVE00`, and `DUNGEON`'s own position flush reads `$C04B,X`
#: here exactly as it does in Pool of Radiance and Curse.
LIVE_X, LIVE_Y, LIVE_FACING = 0xC04B, 0xC04C, 0xC04D


#: `SILVER-1.D64` ... `SILVER-6.D64`, staged as `SIDE1` ... `SIDE6`. The digit
#: in the name is the side the loader prompts for: `tools/areas/areatable.py` finds
#: 29 of 29 static disk writes agreeing with it, none disagreeing.
SIDE_GLOBS = ("SILVER-?.D64", "SILVER?.D64", "*Disk?.d64")

#: What this title draws when it wants another side, and when it wants the
#: save disk.
#:
#: **Silver Blades letters its sides, and that is what `A` was.** The loader
#: drew `INSERT SIDE A, AND PRESS ANY KEY.` at the moment it wanted the side
#: carrying `ECL11`, which `goldbox.areas.AREAS_SILVER_BLADES` puts on side 1,
#: and attaching `SILVER-1` got past it (`issue20/warp1`, scratch, deleted). Read as hex
#: that token is side 10, which is what an earlier run did before attaching a
#: `SIDE10.D64` that does not exist (`issue20/probe4`, scratch, deleted); read as a letter
#: it is side 1 and the disk that answered it. Digits stay accepted because
#: nothing says the loader never prints one.
RE_SSB_SIDE = re.compile(
    r"INSERT\s+(?:YOUR\s+)?(?:GAME\s+)?(?:DISK|SIDE)\s*#?\s*([1-6A-F])\b")


def side_wanted(text: str) -> tuple[int | None, str]:
    """Which of the six sides a prompt is asking for, and the line it read.

    `A`-`F` are sides 1-6; `1`-`6` are themselves. A token that lands outside
    1-6 comes back None **with** the line, so a caller can report a prompt no
    staged disk can answer rather than attaching a file that is not there.
    """
    m = RE_SSB_SIDE.search(text)
    if not m:
        return None, ""
    tok = m.group(1)
    side = int(tok) if tok.isdigit() else ord(tok) - ord("A") + 1
    return (side if 1 <= side <= 6 else None), m.group(0)


#: Silver Blades draws two different save-disk prompts. Camp's -- `INSERT
#: YOUR SAVE GAME DISK` -- is the same wording Pool of Radiance and Curse
#: draw, so it is `session.SAVE_PROMPT` ("SAVE GAME DISK"), imported rather
#: than copied so the two cannot drift apart again (#539, where
#: `"SAVE DISK"` alone matched neither this nor that). The party-menu loader
#: draws a second, different prompt for the same disk: `INSERT BLADES SAVE
#: DISK. PRESS A KEY.`, confirmed at `SILVER-1.D64` offset `0x23A21` on all
#: six sides. Neither wording is a substring of the other, so both are
#: checked.
LOADER_SAVE_PROMPT = "BLADES SAVE DISK"


def save_disk_wanted(text: str) -> bool:
    """Whether *text* is either of Silver Blades' two save-disk prompts."""
    return por.SAVE_PROMPT in text or LOADER_SAVE_PROMPT in text


#: A release check that names the character it wants, as Curse's does. Kept
#: because it costs nothing and its absence is itself a finding.
RE_START_CHECK = re.compile(r'TYPE THE CHARACTER "(.)"')


class Addresses:
    """Every address the warp needs, read out of this title's own overlays.

    Built by `tools/areas/newecl.py`'s finders rather than written down, so the trap
    `#17` names -- an address taken from a PRG header, `$3800` out in this
    title -- has no way in. Silver Blades' `DUNGEON` header claims `$4000` and
    it runs at `$0800`.
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
        # `por.stage_writable` unlinks the destination first and restores the
        # write bit after: a slot keeps its images after a teardown, and a
        # side left read-only by a run from before #455 and #469 cannot be
        # opened for writing at all otherwise.
        por.stage_writable(want, here / f"SIDE{i}.D64")
    target = here / "SIDE0.D64"
    if save:
        # A specimen out of `$WISH_SPECIMENS` is read-only by design
        # (`tools/registry/specimens.py` makes it so).  Staged unchanged, that gives
        # the game a write-protected save disk, and nothing says so: the run
        # boots, the party loads, and every write the game makes is silently
        # refused (#455, #469).
        por.stage_writable(save, target)
    else:
        # **The shipped party is `SAVEDBASH` on side 6**, and this title's
        # save file has that name, so a copy of side 6 is a save disk with a
        # party already on it. It is SSI's own demo party rather than one we
        # watched being written, and nothing here rests on what it *holds*:
        # it supplies six bodies to stand somewhere, and the evidence is the
        # map the running game loads.
        por.stage_writable(here / "SIDE6.D64", target)
    return str(here / "SIDE1.D64")


class SSBSession(por.Session):
    """Pool of Radiance's driver with this title's prompts and boot."""

    #: When `handle_prompt` last answered a disk prompt, on `time.time()`;
    #: `wait_bar` and `to_world_bar` press no Return for `PROMPT_HOLD` after.
    _disk_answered: float | None = None

    #: What makes `Session.indoors()` and `Session.square_and_world()` answer
    #: this title's question rather than Pool of Radiance's.  Silver Blades
    #: has no travel grid, and `$49E6` in a running Silver Blades is
    #: `LIBRARY` code that reads zero -- so the driver used to route every
    #: walk to the compass keys and press nothing (`#360 (The session driver
    #: will not walk a Curse or Silver Blades party in a dungeon, because it
    #: reads Pool of Radiance's indoors flag)`, `#426 (The session driver will
    #: not walk a Silver Blades party, because SSBSession never says which
    #: title it is)`).
    game = c64_port.SECRET_OF_THE_SILVER_BLADES

    def sheet_is_up(self, s) -> bool:
        """Silver Blades' sheet bar has no `VIEW:` on it either.

        Measured against GUY DE VALOIS, a level 8 paladin with nothing
        readied, on 2026-09-14: the sheet bar reads `EXIT` alone, followed by
        36 spaces and nothing else on the row --
        `cited/52/walk-amigatoc64-ssb/ssbcheck2/ssbcheck2.jsonl`
        (`sheet_bar_probe`) and
        `cited/52/walk-dostoc64-ssb/ssbcheck.jsonl` (`sheet`, last line),
        with a screenshot at `02-sheet-0.png` in the DOS-to-C64 walk
        directory. The world bar on the same walk reads `MOVE VIEW CAST AREA
        ENCAMP SEARCH LOOK`, `ENCAMP` spelled in full -- identical to
        Curse's, so `CurseSession.sheet_is_up`'s own test transfers unchanged:
        the world bar has no `EXIT` on it, the camp bar begins `ENCAMP:` and
        is excluded by the second clause, and `EXIT` is the one word every
        version of the sheet bar ends with. `tools/curse_of_the_azure_bonds/curserun.py`'s method is
        not reused directly, so this driver does not gain a dependency on
        Curse's.
        """
        row = s.row(24)
        return "EXIT" in row and "ENCAMP" not in row

    def wanted_disk(self, s) -> str | None:
        """The image Silver Blades' `insert a disk` prompt asks for, or None."""
        text = s.text()
        if save_disk_wanted(text):
            return self.save_disk
        side, line = side_wanted(text)
        if line:
            self.log(f"  prompt text: {line!r} -> side {side}")
        if side is not None:
            return os.path.join(self.here, f"SIDE{side}.D64")
        return None

    def handle_prompt(self, s=None) -> bool:
        if time.time() - self._last_prompt < 2.0:
            return False
        if s is None:
            s = self.screen()
        if s is None:
            return False
        want = self.wanted_disk(s)
        if want is None:
            return False
        if not os.path.exists(want):
            # A needle that matches the wrong thing is worse than one that
            # matches nothing: attaching a missing image leaves the drive
            # holding whatever it held and the game waiting forever.
            self.log(f"  prompt names {os.path.basename(want)}, which is not "
                     f"staged -- not attaching")
            return False
        if (want == self._last_want
                and time.time() - self._last_prompt < self.PROMPT_HOLD):
            return False
        self._last_want = want
        self._last_prompt = time.time()
        if os.path.abspath(want) != self.attached:
            self.log(f"  prompt -> {os.path.basename(want)}")
            self.attach(want)
        self.kbd.key("space")
        self._last_prompt = time.time()
        self._disk_answered = self._last_prompt
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


def impossible_side(sess, addr, text: str, fix: bool) -> dict | None:
    """Report -- and optionally correct -- a prompt no staged disk answers.

    `side_wanted` reads `A`-`F` as sides 1-6, so the `INSERT SIDE A` that
    stopped every earlier run reaches `handle_prompt` and is answered there.
    This is what is left: a prompt naming something outside 1-6, which would
    be a reading of the loader nobody has, and it is reported with the whole
    machine state rather than guessed at.

    With `fix`, the staged sides are offered in turn and a key is pressed.
    """
    side, line = side_wanted(text)
    if not line or side is not None:
        return None
    state = snapshot(sess, addr)
    sess.log(f"  unanswerable side prompt {line!r}: {json.dumps(state)}")
    if not fix:
        return state
    # **The disk byte is not what the prompt is printing.** `$7F12` read 1
    # while the prompt said `A`, so writing 1 to it changed nothing and the
    # loop ran forever -- measured, `cited/20/probe6`. What is left is
    # the ordinary answer to a disk prompt: put a disk in and press a key.
    n = getattr(sess, "_side_rotation", 0)
    sess._side_rotation = n + 1
    want = os.path.join(sess.here, f"SIDE{(n % 6) + 1}.D64")
    sess.log(f"  offering {os.path.basename(want)}")
    sess.attach(want)
    sess.kbd.key("space")
    time.sleep(1.5)
    sess.press_kernal(0x20)
    return state


def idle_in_key_window(sess, addr, samples: int = 4, gap: float = 0.8
                       ) -> int | None:
    """The PC, if the machine has been sitting in a key window and nothing
    else for `samples` readings, with the screen unchanged across them.

    **This is the whole of what makes warping out of the prologue safe**, and
    it is not a guess about menus. `NEWECL`'s tail is
    `JSR $1AF9 / INC $7EDD / LDX $03BF / TXS / JMP $0809`: it rebuilds the
    stack pointer from `$03BF` and re-enters `DUNGEON` at the top, so whatever
    the script VM had in flight is discarded either way. What must *not* be in
    flight is disk I/O, and the guard against that is the same one
    `FastTravel.legality` applies -- the PC inside `DUNGEON`'s key-wait loop
    or the `LIBRARY` fetcher it calls. A script's own one-option menu waits
    for a key in that fetcher exactly as the command bar does, which is why
    the prologue is a legal place to leave from and the treasure menu never
    has to be answered at all.

    The screen has to be still as well. A key window can be passed through
    while text is being printed, and a single sample there would be a warp
    made mid-draw.
    """
    windows = (addr.key_wait, addr.key_fetch)
    last_text = None
    pc = None
    for i in range(samples):
        if i:
            time.sleep(gap)
        try:
            with sess.mon(6) as m:
                pc = m.registers().get(pc_register(m))
        except Exception:
            return None
        if pc is None or not any(lo <= pc < hi for lo, hi in windows):
            return None
        s = sess.screen()
        text = s.text() if s is not None else None
        if i and text != last_text:
            return None
        last_text = text
    return pc


def enter_world(sess, addr, timeout: float = 600.0, fix: bool = True,
                stop_at_idle: bool = True) -> bool:
    """Take a loaded party from the formation menu into somewhere warpable.

    Act only on what is on screen, press nothing at a blank one -- 1024
    zeroes is an area drawing itself, not a menu waiting for a keypress --
    and back out with Escape only when some *other* menu has sat unchanged.

    **`stop_at_idle` is what got past the prologue.** Eight earlier sessions
    tried to answer the starting-treasure bar `VIEW TAKE POOL SHARE EXIT` and
    ended on a character sheet instead. Nothing needed that bar answered: the
    party is already in the world, `$7F11` reads 1 and `$4BE6` reads 1, and a
    warp made from the fetcher the menu is waiting in is the same six writes
    and the same jump. So the first moment the machine is demonstrably idle
    is the moment to leave from, whatever menu happens to be on screen.
    """
    STUCK = 15.0
    deadline = time.time() + timeout
    seen, since = "", time.time()
    began = entered = False
    while time.time() < deadline:
        s = sess.screen()
        if s is None:
            time.sleep(0.5)
            continue
        text = s.text()
        if "ENCAMP" in text:
            return True
        if entered and stop_at_idle and not side_wanted(text)[1] \
                and not save_disk_wanted(text):
            # Not while a disk prompt is up: that waits in `LIBRARY` too, at
            # its own loop rather than in the fetcher, and a warp made with
            # the drive half-way through a file is the one thing the PC guard
            # exists to prevent.
            pc = idle_in_key_window(sess, addr)
            if pc is not None:
                sess.log(f"  world: idle at ${pc:04X}, which is warpable")
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
            began = True
            sess.select_row("BEGIN ADVENTURING")
            sess.press_kernal(0x0D)
        elif began and not entered:
            # Past the formation menu and not a disk prompt: the party is in
            # the world and a script is running it. Only now is an idle PC
            # worth anything -- before it, the same fetcher is what the menus
            # of the front end wait in.
            entered = True
            sess.log("  world: the party is in the world")
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
            # A screen unchanged for STUCK seconds is what a stuck menu and a
            # slow ECL load off floppy both look like, and Escape is VICE's
            # RUN/STOP -- which aborts a KERNAL LOAD in progress. Silver
            # Blades' scripts run 26-31 blocks and can sit with the screen
            # unchanged the whole time, so this checks the PC is actually in
            # DUNGEON's key-wait loop or LIBRARY's fetcher -- the same guard
            # `enter_world`'s own idle branch above applies -- before sending
            # Escape (#568).
            pc = idle_in_key_window(sess, addr)
            if pc is not None:
                sess.log(f"  world: backing out with Escape (idle at "
                         f"${pc:04X})")
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
    return False


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


def silver_session_class():
    """`SSBSession` with `CurseSession`'s bar helpers.

    The camp, sheet and rest steps wait for and press bars the same way
    in both later titles; `curserun.CurseSession` holds those helpers and
    Silver Blades' session does not, so they are borrowed rather than
    copied.
    """
    from tools.curse_of_the_azure_bonds import curserun

    class SilverCureSession(SSBSession):
        BLANK = curserun.CurseSession.BLANK
        press_bar = curserun.CurseSession.press_bar
        wait_bar = curserun.CurseSession.wait_bar
        to_world_bar = curserun.CurseSession.to_world_bar
        live_triple = curserun.CurseSession.live_triple

    return SilverCureSession
