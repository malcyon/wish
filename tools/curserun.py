#!/usr/bin/env python3
"""A driven Curse of the Azure Bonds session, on a pooled VICE instance.

`tools/session.py` drives Pool of Radiance: its `boot()` knows that game's
fastloader prompt, its main menu and the address its copy protection compares
at, and `stage_disks` copies `POOL1.D64`-`POOL8.D64`.  None of that is Curse's.
What *does* transfer is everything below the title screen -- the monitor, the
keyboard, the screen reader, the menu walker, the disk-prompt answerer -- so
this is a thin subclass rather than a second harness.

Three things differ, and they are the whole file:

1. **The sides are `CURSE_A.D64`-`CURSE_F.D64`**, staged as `SIDE1`-`SIDE6`,
   and the save disk is a blank image this tool formats, because the rip
   ships no writable one and the player's disks are never written.
2. **The disk prompt has its own wording.**  `RE_CURSE_SIDE` is fitted to what
   the game actually draws; until it is confirmed, `--watch` launches and
   serves with no boot at all so the screen can be read.
3. **The boot sequence is the rip's, not the original's.**  This rip's
   start-up check does not stop an automated boot (`docs/120` §3).

Usage:

    tools/curserun.py --pool 3            claim slot 3, stage, boot, serve
    tools/curserun.py --pool 3 --watch    same, but do not attempt the boot

Then drive it with `POR_CMD_PORT=6563 tools/porcmd screen`, exactly as for
Pool of Radiance.
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import sys
import time

TOOLS = str(pathlib.Path(__file__).resolve().parent)
sys.path.insert(0, str(pathlib.Path(TOOLS).parent))

from goldbox.d64 import D64  # noqa: E402
from tools import session as por  # noqa: E402

SIDES = "ABCDEF"

#: Every published rip names its sides in the BAM header -- `CURSE DSKA1`,
#: `DSKA2`, `DSKB3`, `DSKB4`, `DSKC5`, `DSKC6` -- so side *n* is the *n*'th
#: image in name order and the mapping is not a guess.
SIDE_GLOBS = ("CURSE_?.D64", "CURSE?.D64", "*Disk?.d64")

#: What Curse draws when it wants another side.  Deliberately wider than Pool
#: of Radiance's: the wording is not the same and the digit may be a letter.
RE_CURSE_SIDE = re.compile(
    r"INSERT\s+(?:YOUR\s+)?(?:GAME\s+)?(?:DISK|SIDE)\s*#?\s*([1-9A-F])")
#: What Curse draws when it wants the save disk.  Pool of Radiance says
#: `INSERT YOUR SAVE GAME DISK`; Curse says `INSERT CURSE SAVE DISK, PRESS A
#: KEY`, so `tools/session.py`'s needle never matches and every save-disk
#: prompt in a Curse session goes unanswered.
SAVE_PROMPT = "SAVE DISK"

#: The release's start-up check names the character it wants, so the answer is
#: read off the screen rather than written down here.
RE_START_CHECK = re.compile(r'TYPE THE CHARACTER "(.)"')


def stock_kernal(slot) -> None:
    """Take JiffyDOS out of this slot's own `vicerc`.

    Donald's machine runs a JiffyDOS kernal and a JiffyDOS 1541-II, and
    `seed_vicerc` copies his file, so every pooled instance inherits both.
    That is right for speed and wrong for any question about the *drive* --
    a game that talks to the 1541 itself is talking to a different DOS.
    This edits the slot's own copy and never his.
    """
    path = pathlib.Path(slot.dir) / "vicerc"
    keep = [ln for ln in path.read_text().splitlines()
            if not ln.startswith(("KernalName=", "DosName1541"))]
    path.write_text("\n".join(keep) + "\n")


def stage(slot, disks: str, save: str = "") -> str:
    """Copy the six Curse sides into the slot and make a save disk.

    The player's own disks are read and never written; `Session.attach`
    refuses any path outside the slot's directory, so the only images the game
    is ever shown are these copies.
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
        raise SystemExit(f"{disks} holds {len(sides)} Curse sides, not six")
    for i, want in enumerate(sides[:6], start=1):
        shutil.copy(want, here / f"SIDE{i}.D64")
    # **Always replace `SIDE0.D64`.**  A pool slot is reused, and the image
    # left in it by the previous tenant is somebody else's game: this staged
    # over a Pool of Radiance save disk, whose `SAVEDGAME0`/`SAVEDGAME1` were
    # still there when Curse wrote four characters beside them, and
    # `ADD CHARACTER TO PARTY` then listed none of them.
    target = here / "SIDE0.D64"
    if save:
        shutil.copy(save, target)
    else:
        D64.blank(b"CURSE SAVE").save(target)
    return str(here / "SIDE1.D64")


#: The two branches that make Curse's `INSERT SIDE # n` prompt unanswerable
#: from this harness, and what they are replaced with.
#:
#: The routine at `$453B` draws the prompt and then loops, leaving only two
#: ways out: a key the game reads out of the KERNAL buffer at `$C6`/`$0277`
#: (`$2FD7`), or the joystick fire button (`$DC00 & $1F == $0F`).  Neither
#: reaches it here -- an XTEST keypress lands in `$0277`, and the loop still
#: does not take its exit -- so the game asks for a disk that is already in
#: the drive for as long as anybody is willing to watch.
#:
#: `$459A` is `BNE $4545`, the loop back when no key arrived; `$459F` is
#: `BNE $4545`, the loop back when the drive's error channel is not `00`.
#: With both `NOP`ped the routine falls through to the retry every pass, and
#: the retry succeeds as soon as the harness has attached the side the prompt
#: named -- which `handle_prompt` does the moment it sees it.
#:
#: This is a disk-swap confirmation, not the release's start-up check, and it
#: is applied to RAM in a driven session only.
DISK_PROMPT_PATCHES = {0x459A: b"\xEA\xEA", 0x459F: b"\xEA\xEA"}
DISK_PROMPT_ORIGINAL = {0x459A: b"\xD0\xA9", 0x459F: b"\xD0\xA4"}


class CurseSession(por.Session):
    """Pool of Radiance's driver with Curse's disk prompt and boot."""

    def patch_disk_prompt(self) -> bool:
        """Let the disk prompt fall through to its retry.  See the note above.

        The bytes are read back first: this address holds unrelated code
        before the world is entered, and patching whatever happens to be
        there would be a fault nobody could trace.
        """
        with self.mon(5) as m:
            for addr, want in DISK_PROMPT_ORIGINAL.items():
                got = m.read(addr, len(want))
                if got != want:
                    self.log(f"${addr:04X} is {got.hex()}, not {want.hex()}"
                             " -- not patching")
                    return False
            for addr, patch in DISK_PROMPT_PATCHES.items():
                m.write(addr, patch)
        self.log("disk prompt patched at $459A and $459F")
        return True

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
            m = RE_CURSE_SIDE.search(text)
            if m:
                digit = m.group(1)
                want = f"{self.here}/SIDE{int(digit, 16)}.D64"
        if want is None:
            return False
        self._last_prompt = time.time()
        if os.path.abspath(want) != self.attached:
            self.log(f"  prompt -> {os.path.basename(want)}")
            self.attach(want)
        self.kbd.key("space")
        return True

    def boot(self) -> bool:
        """Launch and get as far as the game's own party-formation menu.

        Four screens stand between the drive door and that menu, and only the
        first is one Pool of Radiance also has:

        1. `DISABLE FASTLOADER (Y/N) ?`, answered with `self.fastloader`;
        2. the title picture -- a bitmap, so `screen()` reads None through it;
        3. a credits screen, dismissed with Return;
        4. the release's own start-up check, which names the character it
           wants on screen.  **It does not read XTEST letters**: the same
           keypress that Pool of Radiance's code-word prompt ignores.  It is
           delivered through the KERNAL buffer, as `press_kernal` does for
           Return there.

        Pressing Return at an unread screen is how a run ends up somewhere
        nobody can name, so this presses Return only while the screen is one
        of the two it recognises, and gives up saying what it last saw.
        """
        self.launch()
        if self.wait_text("DISABLE FASTLOADER", 180)[0] is None:
            self.log("no fastloader prompt")
            return False
        self.kbd.key(self.fastloader, 0.15, 0.28)
        self.log(f"fastloader: {self.fastloader.upper()}")
        deadline = time.time() + 420
        last = ""
        while time.time() < deadline:
            s = self.screen()
            text = s.text() if s is not None else "(bitmap)"
            if "CREATE NEW CHARACTER" in text:
                self.log("reached the party menu")
                return True
            if RE_START_CHECK.search(text):
                want = RE_START_CHECK.search(text).group(1)
                self.log(f"start-up check wants {want!r}")
                self.press_kernal(ord(want))
            elif "SSI" in text or "BROKEN" in text or "PRESENTS" in text:
                self.kbd.key("Return")
            last = text.strip()[:60]
            time.sleep(2.0)
        self.log(f"never reached the party menu; last screen {last!r}")
        return False


if __name__ == "__main__":
    argv = sys.argv[1:]
    watch = "--watch" in argv
    stock = "--stock-kernal" in argv
    argv = [a for a in argv if a not in ("--watch", "--stock-kernal")]
    slot = None
    if argv and argv[0] == "--pool":
        argv = argv[1:]
        want = None
        if argv and argv[0].isdigit():
            want, argv = int(argv[0]), argv[1:]
        slot = por.claim_slot(want, note=os.environ.get("POR_AGENT", "curse"))
        slot.seed_vicerc()
        print(f"slot {slot.n}: monitor {slot.port} text {slot.text_port} "
              f"cmd {slot.cmd_port} display {slot.display} dir {slot.dir}",
              flush=True)
    disks = save = ""
    while len(argv) > 1 and argv[0] in ("--disks", "--save"):
        if argv[0] == "--disks":
            disks = argv[1]
        else:
            save = argv[1]
        argv = argv[2:]
    if disks:
        assert slot is not None, "--disks needs --pool"
        argv = [stage(slot, disks, save)] + list(argv)
    if stock:
        assert slot is not None, "--stock-kernal needs --pool"
        stock_kernal(slot)
        print("JiffyDOS removed from this slot's vicerc", flush=True)
    sess = CurseSession(argv[0] if argv else None, slot=slot)
    if watch:
        sess.launch()
    elif not sess.boot():
        print("boot incomplete")
    por.serve(sess)
