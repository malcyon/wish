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

import argparse
import os
import pathlib
import re
import shutil
import stat
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
        writable(shutil.copy(want, here / f"SIDE{i}.D64"))
    # **Always replace `SIDE0.D64`.**  A pool slot is reused, and the image
    # left in it by the previous tenant is somebody else's game: this staged
    # over a Pool of Radiance save disk, whose `SAVEDGAME0`/`SAVEDGAME1` were
    # still there when Curse wrote four characters beside them, and
    # `ADD CHARACTER TO PARTY` then listed none of them.
    target = here / "SIDE0.D64"
    # A slot keeps its images after a teardown, so the one to stage over may
    # be a read-only copy an earlier run left -- which `shutil.copy` cannot
    # open for writing.  Unlinking is what the directory's own permissions
    # allow whatever the file's are.
    target.unlink(missing_ok=True)
    if save:
        # `shutil.copy` brings the source's mode with it, and a specimen out
        # of `$WISH_SPECIMENS` is read-only by design (`tools/specimens.py`
        # makes it so).  Staged unchanged, that gives the game a
        # write-protected save disk, and nothing says so: the run boots, the
        # party loads, and every write the game makes is silently refused.
        # A driven `REMOVE CHARACTER FROM PARTY` went the whole way through
        # its menus that way and left no file on the disk
        # (`work/issue439/readd1`, #439).  It also breaks the *next* run in
        # this slot, since a read-only `SIDE0.D64` cannot be staged over.
        writable(shutil.copy(save, target))
    else:
        D64.blank(b"CURSE SAVE").save(target)
    return str(here / "SIDE1.D64")


def writable(path) -> str:
    """Give a staged copy the user's write bit back, and hand the path back.

    Everything in a slot's directory is a throwaway copy the emulator owns;
    the mode that came with it belongs to the file it was copied from.
    """
    path = pathlib.Path(path)
    path.chmod(path.stat().st_mode | stat.S_IWUSR)
    return str(path)


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
    """Pool of Radiance's driver with Curse's disk prompt, boot and keys."""

    #: What makes `Session.indoors()` and `Session.square_and_world()` answer
    #: Curse's question rather than Pool of Radiance's.  Curse has no travel
    #: grid, and `$49E6` in a running Curse is `LIBRARY` code that reads zero
    #: -- so the driver used to route every walk to the compass keys and press
    #: nothing (`#360 (The session driver will not walk a Curse or Silver
    #: Blades party in a dungeon, because it reads Pool of Radiance's indoors
    #: flag)`).
    game = por.G.CURSE_OF_THE_AZURE_BONDS

    #: How long a blank row 24 is left alone before `to_world_bar` presses
    #: Return at it.  Long enough that a redraw finishes on its own.
    BLANK = 6.0

    def move_key(self, move: str, hold=0.15, gap=0.30) -> None:
        """Curse's move handler answers **only** the KERNAL buffer.

        An XTEST `I`, `J`, `K` or `M` moves the party not at all and does not
        even turn it, which from outside looks exactly like a party walled in
        on every side; `press_kernal(0x4A)` turned it from west to south on
        the first try, 2026-09-05
        (`#192 (Convert a Curse of the Azure Bonds DOS save into a C64 one,
        which the importer refuses today)`).  So the same key goes in through
        `$0277` here, the way Return already does at this title's `YES NO`
        bars.
        """
        self.press_kernal(ord(move.upper()[:1]))
        time.sleep(gap)

    def sheet_is_up(self, s) -> bool:
        """Curse's sheet bar has no `VIEW:` on it.

        `LIBRARY $4600`'s menu string is
        `ITEMS SPELLS TRADE DROP CURE HEAL EXIT`
        (`docs/188-the-sheet-portrait-per-title.md`), and the game draws only
        the commands the character can use -- a paladin's `CURE` and `HEAL`
        are not on a magic-user's -- so no word on it is safe to wait for
        except the one every version ends with.  What makes `EXIT` enough is
        that the world's own bar,
        `MOVE VIEW CAST AREA ENCAMP SEARCH LOOK`, has no `EXIT` on it: the
        pair says the sheet has replaced the world rather than that some word
        happens to be on the row.
        """
        row = s.row(24)
        return "EXIT" in row and "ENCAMP" not in row

    def live_triple(self) -> tuple[int, ...]:
        """`$C04B`-`$C04D`: x, y and facing, as the running game holds them.

        A turn changes only the third of the three, so all three are read --
        a caller comparing x and y alone cannot tell a turn from a wall.
        """
        with self.mon(8) as m:
            return tuple(m.read(self.game.live_position, 3))

    def walk_one(self, move: str, hold=0.15, gap=0.30, tries: int = 4,
                 patience: float = 12.0) -> bool:
        """One move, pressed **once** and judged in memory rather than on the
        status line.

        `Session.walk_one` re-sends the key until the status line changes,
        which is right for Pool of Radiance and wrong here twice over.
        Curse's status line **lags the step**: the first move of the
        2026-09-07 run took the party from 3,12 to 2,12 in `$C04B` while the
        line still read `W 0:06 3,12`, so the base class called a step that
        landed a wall and pressed the key three more times.  And Curse does
        not print the square in every area at all -- area `$03` draws
        `E 3:44` and no coordinates -- so there are areas where the line
        could never answer.

        `$C04B` is the triple the game itself walks, and
        `tools/cursewarp.py` has judged Curse's steps by it since
        `#19 (Can Curse be fast-travelled at all, or is the mechanism Pool of
        Radiance's alone?)`.  A wall is then a real reading: the party tried
        and the triple did not move.
        """
        self.walk_refused = None
        if not self.enter_move():
            self.walk_refused = (
                "the driver pressed nothing: it could not get the game to "
                "the move sub-bar, so there was nothing to send a direction "
                "at. That is a driver error and not a wall")
            self.log("  never reached I,J,K,M; nothing sent")
            return False
        before = self.live_triple()
        self.move_key(move, hold, gap)
        deadline = time.time() + patience
        after = before
        while time.time() < deadline:
            now = self.live_triple()
            if now != before:
                after = now
                break
            time.sleep(0.5)
        return after != before

    def press_bar(self, label: str, row: int = 24,
                  timeout: float = 30.0) -> bool:
        """Choose a word on a command bar, whichever Return this screen reads.

        Curse reads Return from the KERNAL buffer on some screens and from
        XTEST on others, and which is which is a per-screen fact rather than
        a per-title one: on 2026-09-07 `select_bar("MOVE")` walked the world
        bar and its XTEST Return entered move mode, while the same call on
        `ENCAMP` moved the highlight and did nothing at all.  Queueing both
        every time is not the answer either -- two Returns is what took the
        `INSERT CURSE SAVE DISK` prompt before anybody could read it
        (`docs/179-loading-a-curse-save.md`).

        So the highlight is walked, the XTEST Return `select_bar` sends is
        given four seconds to change row 24, and only a row that has not
        moved gets the KERNAL one.
        """
        if not self.select_bar(label, row=row, timeout=timeout):
            return False
        s = self.screen()
        was = "" if s is None else s.row(row)
        deadline = time.time() + 4.0
        while time.time() < deadline:
            s = self.screen()
            if s is not None and s.row(row) != was:
                return True
            time.sleep(0.5)
        self.press_kernal(0x0D)
        return True

    def save_game(self, to: str | None = None) -> bool:
        """`ENCAMP ▸ SAVE`, in Curse's own words.

        Three of the four bars are not Pool of Radiance's.  Camp is
        `CAMP:SAVE VIEW MAGIC REST ALTER FIX EXIT` where Pool of Radiance
        draws `ENCAMP:SAVE VIEW MAGIC ...`, and every one of them wants
        `press_bar` rather than `select_bar` because the XTEST Return does
        not reach them.

        **The save disk goes back in the drive first.**  Walking pulls in the
        side the area lives on, so by the time the party makes camp the drive
        is holding a game side; the game then asks for the save disk with a
        prompt that is gone in under a second, and a run that waits to be
        asked has already missed it.
        """
        if to:
            self.save_disk = os.path.abspath(to)
        if not self.to_world_bar():
            self.log("  never got back to the world bar, so ENCAMP could not "
                     "be reached; nothing was saved")
            return False
        # Each step waits for the bar it is about to press.  **`SAVE` and
        # `SAVE GAME` are two commands with a screen between them**: choosing
        # `SAVE` in camp puts up `PRESS ANY KEY TO CONTINUE` -- the game
        # asking for the save disk -- and only then draws `SAVE GAME  EXIT`.
        # `settle` answers a disk prompt and nothing else, so a run that went
        # straight from one to the other spent its whole timeout in front of
        # that key press and reported that SAVE GAME could not be chosen.
        for word in ("ENCAMP", "SAVE", "SAVE GAME"):
            if not self.wait_bar(word):
                self.log(f"  {word} never appeared on row 24")
                return False
            if word == "SAVE GAME" and \
                    os.path.abspath(self.save_disk) != self.attached:
                # `handle_prompt` has usually put the save disk back by now,
                # because the game asks for it by name; this is the belt to
                # that brace, and it costs one attach.
                self.attach(self.save_disk)
            if not self.press_bar(word):
                self.log(f"  {word} could not be chosen")
                return False
        hit, _ = self.wait_text("SAVING GAME", 30)
        self.settle(12)          # the write, then `INSERT YOUR GAME DISK #n`
        return hit is not None

    def wait_bar(self, word: str, timeout: float = 45.0) -> bool:
        """Wait for `word` to be on row 24, answering what stands in the way.

        A disk prompt, a `PRESS ANY KEY TO CONTINUE`, a `MORE` -- none of them
        is the bar, all of them are between two bars, and `select_bar` answers
        only the first.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            s = self.screen()
            if s is None:
                time.sleep(0.4)
                continue
            row = s.row(24)
            if word in row:
                return True
            if self.handle_prompt(s):
                continue
            if "PRESS" in row or "CONTINUE" in row or "MORE" in row:
                self.press_kernal(0x0D)
            time.sleep(0.6)
        return False

    def to_world_bar(self, timeout: float = 90.0) -> bool:
        """Get back to `MOVE VIEW CAST AREA ENCAMP SEARCH LOOK`.

        A walk does not end on the command bar.  It ends wherever the last
        step left the game -- the move sub-bar, a room description, a
        shopkeeper's `YES NO`, a side being loaded -- and `ENCAMP` is on none
        of those, so a `select_bar("ENCAMP")` there spends its whole timeout
        looking for a word that is not on the row and reports that camp could
        not be reached.
        """
        deadline = time.time() + timeout
        blank_since = None
        while time.time() < deadline:
            s = self.screen()
            if s is None:
                time.sleep(0.4)
                continue
            row = s.row(24)
            if "ENCAMP" in row:
                return True
            if self.handle_prompt(s):
                blank_since = None
                continue
            if por.MOVE_SUBBAR in row:
                self.leave_move(2)
            elif "YES" in row and "NO" in row:
                self.press_bar("NO", timeout=8)
            elif "PRESS" in row or "CONTINUE" in row or "MORE" in row:
                self.press_kernal(0x0D)
            elif not row.strip():
                # **A blank row 24 is a screen nobody has read, so nothing is
                # pressed at it straight away** -- that is how a run ends up
                # somewhere nobody can name.  But a walk does end on one and
                # it does not clear itself: on 2026-09-07 the sixth step left
                # the bar blank and the whole ninety seconds went by with the
                # driver waiting politely.  So it is given `BLANK` seconds and
                # then one Return, which is what got the command bar back by
                # hand.
                blank_since = blank_since or time.time()
                if time.time() - blank_since > self.BLANK:
                    self.press_kernal(0x0D)
                    blank_since = None
                time.sleep(0.6)
                continue
            blank_since = None
            time.sleep(0.6)
        return False

    def enter_move(self, timeout: float = 25.0) -> bool:
        """Get the game as far as `I,J,K,M, RETURN OR BUTTON`, and stay there.

        **Move mode is not left between steps**, which is the opposite of
        what `Session.walk_one` does and is the same thing
        `tools/cursewarp.py` learned: `leave_move` presses Return up to eight
        times, and a Return on Curse's own command bar *runs the command the
        highlight is sitting on* rather than backing out of anything.  On
        2026-09-07 that left a driven session on a screen nobody had asked
        for after the first successful step, and the five steps after it were
        refused for want of a bar.

        So the state is entered once and re-entered only when something has
        taken it away -- a disk prompt, a room description, a
        `PRESS <RETURN> OR BUTTON TO CONTINUE`.  The caller leaves it when it
        is finished walking; `ENCAMP` cannot be reached from inside it.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            s = self.screen()
            if s is None:
                time.sleep(0.4)
                continue
            row = s.row(24)
            if por.MOVE_SUBBAR in row:
                return True
            if self.handle_prompt(s):
                continue
            if "ENCAMP" in row:
                if self.select_bar("MOVE", timeout=10):
                    time.sleep(0.8)
                    continue
            elif "YES" in row and "NO" in row:
                # A walked step lands on the game's own scripts: the square
                # west of 3,12 in Tilverton is an armourer, and
                # `WE HAVE A SELECTION OF THE FINEST CORMYR STEEL.
                # INTERESTED?` waits on a `YES NO` for as long as anybody
                # will watch.  `NO` is the answer that leaves the party where
                # it is with nothing else changed.
                self.log(f"  answering NO to |{row.strip()}|")
                self.press_bar("NO", timeout=8)
            elif "PRESS" in row or "CONTINUE" in row or "MORE" in row:
                self.press_kernal(0x0D)
            time.sleep(0.6)
        return False

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


#: A sentinel distinct from every valid `--pool` value, including the `None`
#: `argparse` hands back for a bare `--pool` with no number after it -- so
#: "the flag was never given" and "the flag was given with no number" (claim
#: the next free slot) are still two different things once `main` reads
#: `args.pool` (`#403 (A tool with no argument parser reads --help as input
#: and boots an emulator)`).
_NO_POOL = object()


def main(argv: list[str] | None = None) -> int:
    """`--pool [N]` claims slot *N*, or the next free one with no number.

    Everything below the title screen -- the monitor, the keyboard, the
    screen reader -- is `tools/session.py`'s; what this adds is Curse's own
    sides, save disk and start-up check, in the class above.
    """
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--watch", action="store_true",
                    help="launch and serve with no boot, to read a screen "
                         "the disk-prompt wording does not recognise yet")
    ap.add_argument("--stock-kernal", dest="stock", action="store_true",
                    help="remove JiffyDOS from this slot's vicerc (needs "
                         "--pool)")
    ap.add_argument("--pool", nargs="?", type=int, const=None,
                    default=_NO_POOL, metavar="N",
                    help="claim an instance-pool slot: a specific one, or "
                         "the next free one with no number")
    ap.add_argument("--disks", default="",
                    help="stage the Curse sides into the slot first (needs "
                         "--pool)")
    ap.add_argument("--save", default="",
                    help="the save disk to copy in alongside --disks")
    ap.add_argument("disk", nargs="?", default=None,
                    help="the disk image CurseSession() boots; replaced by "
                         "the staged copy when --disks is given")
    args = ap.parse_args(argv)

    slot = None
    if args.pool is not _NO_POOL:
        slot = por.claim_slot(args.pool,
                              note=os.environ.get("POR_AGENT", "curse"))
        slot.seed_vicerc()
        print(f"slot {slot.n}: monitor {slot.port} text {slot.text_port} "
              f"cmd {slot.cmd_port} display {slot.display} dir {slot.dir}",
              flush=True)

    disk_arg = args.disk
    if args.disks:
        assert slot is not None, "--disks needs --pool"
        disk_arg = stage(slot, args.disks, args.save)
    if args.stock:
        assert slot is not None, "--stock-kernal needs --pool"
        stock_kernal(slot)
        print("JiffyDOS removed from this slot's vicerc", flush=True)
    sess = CurseSession(disk_arg, slot=slot)
    if args.watch:
        sess.launch()
    elif not sess.boot():
        print("boot incomplete")
    por.serve(sess)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
