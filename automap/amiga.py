"""A live Amiga, read through WinUAE's own debugger.

`ViceTarget` talks to a socket. There is no socket here and there is not going
to be one: `docs/143-winuae-debugger.md` §11 checked WinUAE master for a `gdb`
server and there is none, `use_debugger=true` cannot start the debugger on
Windows at all, and the only way in is the `SPC_ENTERDEBUGGER` input event
bound to F11. So a read is: press F11, type `S <file> <addr> <n>` and `g` into
the emulator's console, and take the bytes off the guest's filesystem.

**One `ssh` call does the whole of that**, which is the design decision this
module is built around. `winuae.ps1` and `winuae-send.ps1` are three separate
guest commands -- write the batch file, press F11, inject the batch -- and each
run on its own would be an `ssh` round trip of about two seconds. They are
composed here into a single PowerShell script, base64'd into
`powershell -EncodedCommand`, so a poll is one round trip whatever it reads.
`-EncodedCommand` also removes every quoting question between `winvm ssh`,
whatever shell the guest hands it to, and PowerShell; a batch full of
backslashed Windows paths is not something to send through three quoting
layers by hand.

**The bytes come back base64 on stdout rather than over `scp`.** `docs/143` §6
proposes `S` then `scp`, and that is a second round trip for every block. The
guest reads its own dump file and prints it, in the same script that wrote it.

**Every dump file is named for a token this call generated**, the way
`winuae.ps1` stamps its receipts, because the failure that costs a night here
is reading the *previous* call's file and believing it. A missing file is an
error; a stale one cannot be mistaken for a fresh one.

## What this reads, and how the address is found

The addresses are not written down anywhere and cannot be: these are
relocatable AmigaDOS hunks, so the party's x byte is at a different address on
every boot. `locate()` finds the base by searching the machine's memory for a
string the game's own data hunk carries, at an offset read out of the
executable on the player's own disk -- so the base is **computed at run time**
and the layout table holds only offsets, which are a property of the build.

`AmigaLayout` is the per-title table. A title with no row is refused rather
than given another title's numbers, which is the same rule
`goldbox.games.Game.live_position` follows on the C64 side.

Nothing here writes to the player's disks and nothing claims or releases the
Amiga lane: `winuae.ps1 claim` is the caller's, exactly as it is for
`tools/amigadrive.py`, because a claim that ends with the process that took it
cannot be handed between the several runs one experiment needs.
"""

from __future__ import annotations

import base64
import logging
import os
import pathlib
import re
import struct
import subprocess
import uuid
from dataclasses import dataclass, field

from goldbox.geo import GEO_SIZE, Geo

from .target import Fix, NotConnected

#: A child of the `wish` logger, like every other module here.
_log = logging.getLogger("wish.automap.amiga")

#: F11, the virtual key `tools/goldbox-a500.uae` binds `SPC_ENTERDEBUGGER` to.
#: The debugger has no other way in -- `docs/143-winuae-debugger.md` §5.
DEBUGGER_KEY = 0x7A

#: Where `winuae.ps1` and its helpers live on the guest, and where a dump goes.
#: `docs/143` §6: the path an `S` command is given **must be absolute**, or
#: WinUAE resolves it against its own data directory and reports success.
GUEST_ROOT = r"C:\Amiga"
GUEST_DUMP = GUEST_ROOT + r"\dump"

#: The Amiga's memory, as the ranges a whole-machine search has to cover, for
#: the A500 `tools/goldbox-a500.uae` describes: 512K of chip at 0 and 512K of
#: slow memory at `$C00000` (`bogomem_size=2`). The game is in the second of
#: them -- `docs/143` §5.2 -- but a search that assumed so would answer
#: "not found" on a machine configured any other way, so both are swept and
#: the slow memory is swept first because that is where it has always been.
CHIP = (0x000000, 0x080000)
SLOW = (0xC00000, 0x080000)
MEMORY = (SLOW, CHIP)

#: The debugger prints an `S` receipt like
#: `Wrote 00040000 - 0004000F (16 bytes) to '...'.` -- not parsed, because the
#: file either has the bytes or it does not. This is what a *failed* command
#: looks like, and it is worth telling apart from a silent one.
RE_UNKNOWN = re.compile(r"Unknown command", re.I)


@dataclass(frozen=True)
class AmigaLayout:
    """Where one title keeps the automapper's three inputs, as offsets.

    Every offset is into the executable's **data hunk**, which is how
    `tools/amiga68k.py` names a small-data global: `g57a0` is data hunk offset
    `0x57a0`, and `a4` is that hunk plus `0x7FFE`. Only the base moves from
    boot to boot, so these are constants of the build and the base is measured.

    `anchor` and `anchor_offset` are the string the base is found by, and
    where the executable carries it. `tools/amigatarget.py --verify` re-derives
    both off the player's own disk, so a different release with the string
    somewhere else is caught rather than silently misread.

    `width` is 1 where the title stores x, y and facing as bytes and 2 where it
    stores them as `u16be`. Curse does the second and Silver Blades the first,
    which is why this is a field and not an assumption.
    """

    title: str
    #: The file in the ADF's root, as `tools/amiga68k.py --exe` wants it.
    executable: str
    anchor: bytes
    anchor_offset: int
    party_x: int
    party_y: int
    party_facing: int
    width: int
    #: A **pointer**, not the map: the 32-bit address of the resident 1024-byte
    #: `GEO` block, which the engine's own two indexing routines dereference.
    geo_pointer: int
    #: Anything else measured for this title, so a finding has somewhere to
    #: land that is not a new field nobody else uses.
    notes: dict[str, int] = field(default_factory=dict)


#: The titles whose offsets have been read out of their executables.
#:
#: **Pool of Radiance is deliberately absent.** Its Amiga build is not a
#: small-data one: `docs/165-amiga-savegame.md` puts its party struct at
#: `h32+0x176f`, an offset into hunk 32 of a many-hunk executable with absolute
#: relocations, so there is no single base to find and the anchor trick above
#: locates the wrong hunk. Adding it needs the hunk's own load address, which
#: is a different measurement -- see `#37 (Automap the Amiga version, not
#: just the C64)`.
LAYOUTS: dict[str, AmigaLayout] = {
    # `blades.cfg` is the string `docs/143` §5.2 already used to find `a4` in
    # this title, so the anchor is the one with a run behind it.
    "secret-of-the-silver-blades": AmigaLayout(
        title="Secret of the Silver Blades",
        executable="/Secret",
        anchor=b"blades.cfg",
        anchor_offset=0x303C,
        party_x=0x57A0,
        party_y=0x57A1,
        party_facing=0x57A2,
        width=1,
        geo_pointer=0x7BF8,
        # The two bytes after the facing, which the step routine recomputes
        # from the map on every step: the wall type in the facing direction and
        # the square's own attribute byte (`docs/165-amiga-savegame.md`).
        #
        # `array_pointer` and `array_offset` are where the saved game's own
        # `$49xx` array is resident: the longword at that data-hunk offset,
        # plus `array_offset`, is the array as `u16be` words, one per DOS byte.
        # Nothing reads them -- see `AmigaTarget.fix` on why the clock is not
        # fetched -- and they are PROBABLE on one boot (`#37`).
        notes={"wall_ahead": 0x57A3, "square_attribute": 0x57A4,
               "array_pointer": 0x5160, "array_offset": 0x508},
    ),
    "curse-of-the-azure-bonds": AmigaLayout(
        title="Curse of the Azure Bonds",
        executable="/Curse",
        anchor=b"Area Cast View Encamp Search Look",
        anchor_offset=0x1C9E,
        party_x=0x3F5E,
        party_y=0x3F60,
        party_facing=0x3F62,
        width=2,
        geo_pointer=0x5EB6,
        notes={"wall_ahead": 0x3F63, "square_attribute": 0x3F64},
    ),
}


class GuestError(NotConnected):
    """The guest refused, or the emulator was not there to be read.

    A subclass of `NotConnected` so `automap/window.py` keeps retrying rather
    than falling over: an Amiga that is booting, or a lane somebody else holds,
    is a state to wait out and not a crash.
    """


def _run(argv: list[str], timeout: float) -> str:
    """`winvm`, with the options that stop `ssh` asking a human anything.

    `winvm` sets `BatchMode` and `SSH_ASKPASS_REQUIRE` itself; setting the
    second here as well costs nothing and means a caller who has exported
    neither still cannot make `ssh` reach for a dialog. With no tty and
    `DISPLAY` set, OpenSSH draws a KDE credential prompt on whoever's desktop
    is in front of it -- `AGENTS.md`, "The machine".
    """
    env = dict(os.environ, SSH_ASKPASS_REQUIRE="never")
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, env=env)
    except FileNotFoundError as exc:
        raise GuestError(f"{argv[0]} is not on this machine: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise GuestError(f"{' '.join(argv[:2])} did not answer in "
                         f"{timeout:.0f}s") from exc
    if proc.returncode != 0:
        raise GuestError(f"{' '.join(argv[:2])} failed: "
                         f"{(proc.stdout + proc.stderr).strip()[-500:]}")
    return proc.stdout


def encode(script: str) -> str:
    """A PowerShell script as `-EncodedCommand` wants it: UTF-16LE, base64.

    This is what keeps the batch out of three quoting layers. A debugger batch
    is full of `C:\\Amiga\\dump\\...` and single quotes, and `winvm ssh` hands
    its argument to whatever shell the guest's OpenSSH is configured with
    before PowerShell ever sees it.
    """
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


class WinuaeDebugger:
    """The transport: one `ssh` round trip runs a whole debugger batch.

    Not a `Target`. It knows about consoles, tokens and base64; it knows
    nothing about the Amiga's memory map, which is `AmigaTarget`'s half.

    `runner` is the thing that actually runs `winvm`, injected so the tests can
    drive every path with no VM at all. It takes the argument list and the
    timeout and gives back stdout.
    """

    #: Long, because the batch waits 700 ms after every typed line, `winuae.ps1
    #: send` polls for its receipt, and a 512K dump has to be base64'd by
    #: PowerShell. Measured cost is in `docs/143` §12.
    TIMEOUT = 300.0

    def __init__(self, holder: str, runner=None, timeout: float | None = None):
        if not holder:
            raise ValueError("a WinUAE lane claim is required: "
                             "`winuae.ps1 claim -Holder <name>` first")
        self.holder = holder
        self._run = runner or _run
        self.timeout = self.TIMEOUT if timeout is None else timeout
        #: Every batch this session sent, for a run log. Cheap and it is the
        #: thing you want when a poll came back wrong.
        self.batches: list[list[str]] = []

    # -- building the guest script ---------------------------------------

    def _script(self, lines: list[str], fetch: list[tuple[str, str]]) -> str:
        """The PowerShell the guest runs: write the batch, F11, inject, print.

        `fetch` is `(name, guest path)`; each file is printed as
        `<<name>> <base64>` on its own line, and a file that is not there is
        printed as `<<name>> MISSING` rather than throwing, so one absent dump
        does not lose the console output that says why.
        """
        ps = r"powershell -NoProfile -ExecutionPolicy Bypass -File "
        text = "\n".join(lines) + "\n"
        batch = base64.b64encode(text.encode("ascii")).decode("ascii")
        parts = [
            "$ErrorActionPreference='Continue'",
            # The batch file is written as raw bytes rather than through
            # Set-Content: a UTF-8 BOM at the head of a debugger batch is typed
            # into the console as rubbish before the first command, and
            # `winuae-send.ps1` types every character it reads.
            f"[IO.File]::WriteAllBytes('{GUEST_ROOT}\\wish-batch.txt',"
            f"[Convert]::FromBase64String('{batch}'))",
            f"New-Item -ItemType Directory -Force -Path '{GUEST_DUMP}' "
            "| Out-Null",
            "Write-Output '<<key>>'",
            f"& {ps}{GUEST_ROOT}\\winuae.ps1 key {DEBUGGER_KEY:02X} "
            f"-Holder {self.holder}",
            "Write-Output '<<send>>'",
            f"& {ps}{GUEST_ROOT}\\winuae.ps1 send "
            f"'-File {GUEST_ROOT}\\wish-batch.txt' -Holder {self.holder}",
        ]
        for name, path in fetch:
            parts.append(f"Write-Output '<<{name}>>'")
            parts.append(
                f"if (Test-Path -LiteralPath '{path}') {{ "
                f"Write-Output ([Convert]::ToBase64String("
                f"[IO.File]::ReadAllBytes('{path}'))); "
                f"Remove-Item -LiteralPath '{path}' -Force }} "
                "else { Write-Output 'MISSING' }")
        parts.append("Write-Output '<<end>>'")
        return "\n".join(parts)

    def batch(self, lines: list[str],
              fetch: list[tuple[str, str]] | None = None
              ) -> tuple[str, dict[str, bytes | None]]:
        """Run one debugger batch. Returns the guest's output and the files.

        **The caller supplies the `g`.** Nothing here appends one, because a
        batch that forgets to resume leaves the emulator halted and that has to
        be visible in the batch a reader is looking at rather than hidden in a
        helper. `AmigaTarget` always appends one; a tool single-stepping
        deliberately would not.
        """
        fetch = fetch or []
        self.batches.append(list(lines))
        out = self._run(["winvm", "ssh",
                         "powershell -NoProfile -EncodedCommand "
                         + encode(self._script(lines, fetch))],
                        self.timeout)
        if "<<end>>" not in out:
            raise GuestError("the guest script did not finish; its output "
                             f"ended: {out.strip()[-400:]}")
        blobs: dict[str, bytes | None] = {}
        for name, _path in fetch:
            blobs[name] = _blob(out, name)
        return out, blobs


def _blob(out: str, name: str) -> bytes | None:
    """The base64 the guest printed under `<<name>>`, or None if it was not
    there. Lenient about what sits between the marker and the payload: the
    guest's own line endings arrive as `\\r\\n` through `ssh`."""
    marker = f"<<{name}>>"
    at = out.find(marker)
    if at < 0:
        return None
    rest = out[at + len(marker):]
    for line in rest.splitlines():
        line = line.strip()
        if not line:
            continue
        if line == "MISSING" or line.startswith("<<"):
            return None
        try:
            return base64.b64decode(line, validate=True)
        except (ValueError, base64.binascii.Error):
            return None
    return None


def find_anchor(memory: bytes, base: int, anchor: bytes,
                offset: int) -> list[int]:
    """Every data-hunk base this dump is consistent with.

    Returned rather than reduced to one on purpose. A string can appear twice
    -- a copy in a buffer, a second instance in another loaded thing -- and a
    locator that took the first hit would be right most of the time and wrong
    silently. The caller checks each candidate against what the game should
    hold there and refuses when more than one survives.
    """
    out, at = [], memory.find(anchor)
    while at >= 0:
        out.append(base + at - offset)
        at = memory.find(anchor, at + 1)
    return out


# -- the maps, off the player's own disk --------------------------------------
#
# The C64 keeps one `GEO<id>` file per area in the disk's own directory, so
# `goldbox.geo.load_geo_files` walks the directory and is the whole of it. The
# Amiga keeps all of them in one `GLIB` container, `GEO.GLB`, on the second
# disk of each title -- `/DISK2/GEO.GLB` on Silver Blades and `/DISKB/GEO.GLB`
# on Curse, which is why nothing here hard-codes the path.

#: The container's name on both titles' disks, whatever directory it sits in.
GEO_LIBRARY = "GEO.GLB"


def glib_blocks(data: bytes) -> list[bytes]:
    """Every block of a `GLIB` container, in order.

    The magic, a `u32` total size, a `u16` block count, a `u16`, a four-byte
    tag naming what the blocks are, then `count + 1` big-endian `u32` offsets,
    block *i* being `[off[i], off[i + 1])`.

    **The same six lines are in `tools/amigaenum.py`, deliberately.** Nothing
    under `automap/` may import `tools/` -- that is a shipped package reaching
    into a directory no wheel carries -- and a reader with no container parse
    could not open the Amiga's maps at all. `tools/amigatarget.py` imports
    *this* copy, so the two that answer this question in the automapper cannot
    drift apart.
    """
    if data[:4] != b"GLIB":
        raise ValueError(f"not a GLIB container: it opens {data[:4]!r}")
    count = struct.unpack(">H", data[8:10])[0]
    offsets = struct.unpack(f">{count + 1}I", data[16:16 + 4 * (count + 1)])
    return [data[offsets[i]:offsets[i + 1]] for i in range(count)]


def geo_library(data: bytes) -> dict[int, bytes]:
    """`GEO.GLB` as `{id: 1024 bytes}`.

    Block 0 is a 70-byte index -- a `u16be` count and then that many
    `(id, block)` pairs -- and blocks 1 upwards are the maps. The **id** is
    what a saved game holds at `$49C5` and what the engine hands its loader,
    so it is the same number the C64 spells into a filename.

    A pair naming a block that is not `GEO_SIZE` bytes is dropped rather than
    returned short: the index is the container's own claim about itself and a
    block of another shape is not a map, whatever the index says.
    """
    blocks = glib_blocks(data)
    if not blocks:
        return {}
    index = blocks[0]
    count = int.from_bytes(index[:2], "big")
    out: dict[int, bytes] = {}
    for i in range(count):
        at = 2 + 4 * i
        ident = int.from_bytes(index[at:at + 2], "big")
        block = int.from_bytes(index[at + 2:at + 4], "big")
        if block < len(blocks) and len(blocks[block]) == GEO_SIZE:
            out[ident] = blocks[block]
    return out


def library_path(disk) -> str | None:
    """Where `GEO.GLB` is on this disk image, or None if it is not there.

    Searched rather than tabulated: the two titles keep it in differently
    named directories and a third would keep it in a third.
    """
    for path, _entry in disk.walk():
        if path.upper().endswith(GEO_LIBRARY):
            return path
    return None


def load_maps(image) -> dict[str, Geo]:
    """Every map on one Amiga disk image, keyed the way the C64 names them.

    `{"GEO10": Geo, ...}` -- `GEO{id:02X}`, which is the C64's own filename
    for the same area and what `goldbox.areas` and the automapper's notes
    files are keyed by. So an Amiga party's map is drawn on the same sheet its
    C64 counterpart would be, and `tools/geoports.py` has already measured
    that the blocks themselves are the same bytes: all seventeen of Silver
    Blades' and thirteen of Curse's sixteen are byte-identical across the two
    ports.

    Empty for a disk with no library on it, which is every title's disk A --
    the caller reads both sides and takes whichever answers.
    """
    from goldbox.amiga_adf import AmigaDisk
    disk = AmigaDisk.open(str(image))
    where = library_path(disk)
    if where is None:
        return {}
    return {f"GEO{ident:02X}": Geo(block)
            for ident, block in sorted(geo_library(disk.read_file(where)).items())}


def load_maps_in(folder) -> tuple[dict[str, Geo], pathlib.Path | None]:
    """The maps off the first disk image in this folder that carries any.

    Returns them and the image they came from, so a run can say which disk it
    read. `automap/maps.py`'s C64 loader merges every disk in the folder
    because the C64 spreads its maps over six of them; one Amiga disk carries
    the lot, so the first that answers is the answer.
    """
    folder = pathlib.Path(folder)
    for image in sorted(folder.glob("*.adf")) + sorted(folder.glob("*.ADF")):
        try:
            maps = load_maps(image)
        except Exception as exc:                # not a disk, or not readable
            _log.debug("%s is not a disk this can read: %s", image, exc)
            continue
        if maps:
            return maps, image
    return {}, None


class AmigaTarget:
    """A running Amiga Gold Box title, as the automapper's `Target`.

    Two methods and no more, like every other backend -- plus `fix`, which the
    protocol already looks for with `getattr`, because the C64's status-line
    reader in `automap/screen.py` reads a 40x25 text screen out of fixed
    memory and the Amiga has no such thing. The Amiga's answer is better than
    the C64's fallback rather than worse: it is the engine's own live x, y and
    facing, which `docs/143` §5.2 measured moving with the party while the
    screen had not been redrawn at all.

    **No `banks()`.** The 68000 has one memory and nothing is banked over
    anything, so the optional capability `#421 (The automapper reads the screen
    through the CPU's banking, so it reads the wrong memory while the game
    loads)` added is absent and
    `screen_banks` hands back the one reader, which is right here rather than
    a compromise.

    `data_base` is the load address of the title's data hunk and must be
    measured with `locate()` before any read means anything. It is not cached
    across boots and must not be: AmigaDOS relocates on every `LoadSeg`.
    """

    #: A poll is a whole `ssh` round trip and a typed console batch, so this is
    #: not `ViceTarget`'s 200 ms. Measured on the first live run; see the
    #: module's row in `tools/README.md` for how to re-take it.
    halts_on_read = True

    def __init__(self, debugger: WinuaeDebugger, layout: AmigaLayout,
                 data_base: int | None = None):
        self.debugger = debugger
        self.layout = layout
        self.data_base = data_base
        self._open = True

    # -- Target ----------------------------------------------------------

    def read(self, addr: int, length: int) -> bytes:
        """One block, through `S` and back as base64."""
        return self.read_blocks([(addr, length)])[0]

    def write(self, addr: int, data: bytes) -> None:
        """`W <addr> <bytes>`, in hex, one command.

        The debugger's own `W` takes a list of byte values; `docs/143` §7 has
        the eight-byte proof. Split into lines of sixteen so a long write does
        not become a console line nothing can type.
        """
        self._require_open()
        lines = []
        for i in range(0, len(data), 16):
            chunk = data[i:i + 16]
            lines.append(f"W {addr + i:x} "
                         + " ".join(f"{b:02x}" for b in chunk))
        lines.append("g")
        out, _ = self.debugger.batch(lines)
        if RE_UNKNOWN.search(out):
            raise GuestError("the debugger did not recognise a `W`; the "
                             "batch may have been typed at the game instead")

    def read_blocks(self, blocks) -> list[bytes]:
        """Several ranges, in one round trip. This is the design, not a tune.

        `ViceTarget.read_blocks` batches to save 14 ms of emulated time per
        resume. Here a round trip is an `ssh`, a foreground-window keypress, a
        scheduled task and a console batch typed at 700 ms a line, so reading
        the party and the resident map separately costs twice a poll rather
        than a few percent of one.

        A block may name its memory -- `(addr, length, "io")` -- because the
        C64 side's callers pass that shape. **The name is ignored**, which is
        the documented behaviour for a backend that cannot tell two memories
        apart, and here it is not a limitation: there is only one memory.
        """
        self._require_open()
        want = [(b[0], b[1]) for b in blocks]
        token = uuid.uuid4().hex[:8]
        lines, fetch = [], []
        for i, (addr, length) in enumerate(want):
            if length <= 0:
                raise ValueError(f"a read of {length} bytes is not a read")
            path = f"{GUEST_DUMP}\\wish-{token}-{i}.bin"
            lines.append(f"S {path} {addr:x} {length:x}")
            fetch.append((f"b{i}", path))
        lines.append("g")
        out, blobs = self.debugger.batch(lines, fetch)
        result = []
        for i, (addr, length) in enumerate(want):
            blob = blobs.get(f"b{i}")
            if blob is None:
                raise GuestError(
                    f"the debugger wrote no dump for {addr:#x}+{length:#x}; "
                    f"the batch's own output ended: {out.strip()[-400:]}")
            if len(blob) != length:
                raise GuestError(
                    f"asked for {length} bytes at {addr:#x} and the guest "
                    f"returned {len(blob)}")
            result.append(blob)
        return result

    def close(self) -> None:
        self._open = False

    def _require_open(self) -> None:
        if not self._open:
            raise GuestError("this target was closed")

    # -- finding the base ------------------------------------------------

    def locate(self, memory=MEMORY) -> int:
        """Measure the data hunk's load address, and remember it.

        Dumps the machine's memory a region at a time and searches **on this
        side** rather than through the debugger's own `s` command. Three
        reasons, and the first is the one that matters:

        * `s` prints its hits to the console, so reading them means parsing
          the debugger's output format -- and a search that finds *two* copies
          of the anchor has to be seen to have found two. A dump makes that a
          fact about bytes here rather than a fact about a text format;
        * `s` gives up after 64K whatever range it is given (`docs/143` §5.2
          measured `Aborted at 0000FFFE`), so a sweep is eight commands per
          512K anyway;
        * the same dump answers the next question, whatever it turns out to
          be, without another boot.

        Raises rather than guessing when the anchor is missing or ambiguous.
        """
        self._require_open()
        found: list[int] = []
        for base, length in memory:
            blob = self.read(base, length)
            found += find_anchor(blob, base, self.layout.anchor,
                                 self.layout.anchor_offset)
            if found:
                break                   # the game is in one region, not two
        if not found:
            raise GuestError(
                f"{self.layout.anchor!r} is nowhere in the Amiga's memory, so "
                f"{self.layout.title} is not the title that is running (or it "
                "has not finished loading)")
        if len(set(found)) > 1:
            raise GuestError(
                f"{self.layout.anchor!r} appears at more than one place: "
                + ", ".join(f"{b:#x}" for b in sorted(set(found)))
                + " -- pick the base with a second known constant rather than "
                  "taking the first")
        self.data_base = found[0]
        _log.info("%s: data hunk at %#x, a4 = %#x", self.layout.title,
                  self.data_base, self.data_base + 0x7FFE)
        return self.data_base

    def _at(self, offset: int) -> int:
        if self.data_base is None:
            raise GuestError("the data hunk's address has not been measured; "
                             "call locate() first")
        return self.data_base + offset

    # -- what the automapper asks for ------------------------------------

    def fix(self, game=None) -> Fix | None:
        """Where the party is, from the engine's own bytes.

        `game` is accepted and ignored: `read_fix` passes it, and the C64
        addresses in a `goldbox.games.Game` mean nothing on a 68000. What
        decides the addresses here is `self.layout`.

        Returns None when the reading cannot be true -- x or y outside the
        16x16 grid, a facing that is not one of the four the engine writes --
        which is what a party in a menu, in camp, or mid-load looks like, and
        is an ordinary state rather than an error. The map holds its last fix,
        exactly as it does on the C64.

        **`Fix.clock` is None here, and deliberately.** The game clock is not
        in the data hunk at all: 36,736 bytes of it dumped across a step that
        moved the status line from `00:03` to `00:04` hold no byte that moved
        with it. It is in the resident copy of the saved game's `$49xx` array,
        which `layout.notes` names -- one round trip past a pointer, on top of
        a poll that already costs fifteen seconds. And nothing would read it:
        `Automapper._refused` is the one caller, and it requires *both* fixes
        to come from the status line, which no fix from this backend ever
        does. `#37 (Automap the Amiga version, not just the C64)` has the
        measurement.
        """
        span = self.layout.width
        lo = min(self.layout.party_x, self.layout.party_y,
                 self.layout.party_facing)
        hi = max(self.layout.party_x, self.layout.party_y,
                 self.layout.party_facing) + span
        blob = self.read(self._at(lo), hi - lo)

        def at(offset: int) -> int:
            start = offset - lo
            return int.from_bytes(blob[start:start + span], "big")

        x, y, doubled = (at(self.layout.party_x), at(self.layout.party_y),
                         at(self.layout.party_facing))
        # The engine stores the facing **doubled** -- 0 north, 2 east, 4 south,
        # 6 west -- because its own jump table indexes on it (`docs/165`). The
        # automapper's `Fix` is 0-3, the same order.
        if doubled % 2 or doubled > 6:
            _log.debug("facing %d is not one the engine writes", doubled)
            return None
        if not (0 <= x < 16 and 0 <= y < 16):
            _log.debug("square %d,%d is off the 16x16 grid", x, y)
            return None
        return Fix(x, y, doubled // 2, "memory")

    def resident_geo_address(self) -> int | None:
        """Where the 1024-byte `GEO` block the game is drawing lives.

        A pointer, dereferenced: the title's two map-indexing routines both do
        `movea.l d16(a4), a0` and then index `16*y + x`, `+0x100` and `+0x200`
        off it, so the map moves with whatever the loader allocated and the
        global is the only fixed thing. Silver Blades `0x3b78c`/`0x3b8a6` and
        Curse `0x37a22`/`0x37b3c` are those routines.

        None when the pointer is null or is not a plausible address, which is
        what it holds before an area has been loaded.

        Hand the answer to `automap.area.ResidentGeo(target, address)`, which
        already takes the address as an argument and needs nothing else: the
        Amiga's block is the same four 256-byte planes as the C64's.
        """
        raw = self.read(self._at(self.layout.geo_pointer), 4)
        addr = int.from_bytes(raw, "big")
        # A null pointer is what the global holds before an area has loaded,
        # and zero is *inside* chip memory -- it is the 68000's exception
        # vector table, which is never a map. So it is refused by name rather
        # than by the range test below.
        if addr == 0 or not any(base <= addr and addr + 0x400 <= base + length
                                for base, length in MEMORY):
            _log.debug("the GEO pointer holds %#x, which is in no memory this "
                       "machine has", addr)
            return None
        return addr

    def geo(self) -> bytes | None:
        """The resident map itself, 1024 bytes, or None if none is loaded."""
        addr = self.resident_geo_address()
        if addr is None:
            return None
        return self.read(addr, 0x400)
