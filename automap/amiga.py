"""A live Amiga, read through the emulator's own debugger.

`ViceTarget` talks to a socket. WinUAE has no socket, but it has two doors on
the same debugger and they are not the same to whoever is at the machine. A
patched FS-UAE does have one, and it is the third transport here.

**`WinuaePipe` is the one to reach for.** Every WinUAE process creates
`\\\\.\\pipe\\WinUAE` at startup, and a message beginning `DBG ` is handed to
`debug_parser`, which points the debugger's console output at a buffer and hands
the buffer back as the reply. So a read costs one frame, opens no window, takes
no focus and does not stop the emulated machine -- measured on 2026-09-08 at a
median of 2.3 ms a command with the emulator holding 49.9 FPS throughout, on
`#37 (Automap the Amiga version, not just the C64)`.

**`WinuaeDebugger` is the older route and the one every driven tool uses.** It
sends `CFG AKS_ENTERDEBUGGER 1` over the copy's own pipe -- no key press and no
focus, which is how the driver enters the *interactive* debugger, since
`use_debugger=true` cannot start it on Windows at all -- and types `S <file> <addr> <n>` and `g` into the emulator's console.
That halts the machine for the length of the batch and puts a console in front
of whoever is playing, so it belongs to a driven run and not to a player's
session. It stays because its `W` and its single-stepping reach parts of the
debugger the pipe deliberately will not send.

**`FsuaeGdb` is the Linux route, and the only one a player on Linux can use.**
The patched FS-UAE at `grahambates/fs-uae`, branch `remote_debugger_prb28`,
carries `src/barto_gdbserver.cpp`, a GDB-remote server that answers a memory
read from the frame handler of a **running** machine: `vsync_pre()` ends
`if(debugger_state == state::connected && data_available()) handle_packet();`,
and the `m` branch reads through `get_mem_bank(adr)->bget(adr)` with no state
check and no call to `activate_debugger()`. So there is no console, no
keypress, no halt and no `ssh` -- a socket on loopback, like the C64's. What it
costs, what it blocks and what it cannot do is on the class.

**One `ssh` call does the whole of either WinUAE route**, which is the design
decision this module is built around. `winuae.ps1` and `winuae-send.ps1` are three separate
guest commands -- write the batch file, enter the debugger, inject the batch -- and each
run on its own would be an `ssh` round trip of about half a second. They are
composed here into a single PowerShell script, base64'd into
`powershell -EncodedCommand`, so a poll is one round trip whatever it reads.
`-EncodedCommand` also removes every quoting question between `winvm ssh`,
whatever shell the guest hands it to, and PowerShell; a batch full of
backslashed Windows paths is not something to send through three quoting
layers by hand.

**The `ssh` is this project's test rig, not the design of the product.** Wish and
WinUAE on one Windows machine is a local pipe opened by a local process, which
is `WinuaePipe(connection="local")`; the Linux-to-VM arrangement is the awkward
case and it is where the round trip comes from.

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

`AmigaMachine` is the per-title table. A title with no row is blocked rather
than given another title's numbers, which is the same rule
`automap.c64.C64Machine.live_position` follows on the C64 side.

Nothing here writes to the player's disks and nothing claims or releases the
Amiga lane: `winuae.ps1 claim` is the caller's, exactly as it is for
`tools/amiga/amigadrive.py`, because a claim that ends with the process that took it
cannot be handed between the several runs one experiment needs.
"""

from __future__ import annotations

import base64
import logging
import os
import pathlib
import re
import socket
import struct
import subprocess
import time
import uuid
from collections.abc import Collection
from dataclasses import dataclass, field

from goldbox.geo import GEO_SIZE, Geo

from .target import WINDOW_H, WINDOW_W, Fix, NotConnected

#: A child of the `wish` logger, like every other module here.
_log = logging.getLogger("wish.automap.amiga")

#: Where `winuae.ps1` and its helpers live on the guest, and where a dump goes.
#: `docs/143` §6: the path an `S` command is given **must be absolute**, or
#: WinUAE resolves it against its own data directory and reports success.
GUEST_ROOT = r"C:\Amiga"
GUEST_DUMP = GUEST_ROOT + r"\dump"

#: The Amiga's memory, as the ranges a whole-machine search has to cover, for
#: the A500 `tools/amiga/goldbox-a500.uae` describes: 512K of chip at 0 and 512K of
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
#: looks like, and it needs telling apart from a silent one.
RE_UNKNOWN = re.compile(r"Unknown command", re.I)


@dataclass(frozen=True)
class Segments:
    """A title whose anchor and data are in different hunks of a many-hunk
    executable, so there is no single base to find.

    `LoadSeg` stores each hunk's allocation length at `base - 8` and the BPTR
    of the next hunk at `base - 4`; both are measured to be the declared size
    plus 8, which is what `data_base_for` checks before it trusts a hop.
    """

    anchor_hunk: int
    data_hunk: int
    anchor_size: int
    data_size: int


@dataclass(frozen=True)
class TravelGrid:
    """Where a title keeps the state of its outdoor travel grid, as offsets
    into the data hunk (`block_pointer` is a pointer to a block, and `x`, `y`
    and `indoors` are `u16be` offsets into that block).

    `views[i]` is the view byte of window `i` (0 west, 1 middle, 2 east) and
    `areas[i]` the area byte for it. The block's own area word lags a crossing
    by one, so nothing reads it.
    """

    view: int
    views: tuple[int, ...]
    area: int
    areas: tuple[int, ...]
    block_pointer: int
    x: int
    y: int
    indoors: int


@dataclass(frozen=True)
class WorldMap:
    """Where a title keeps the state of its world map, which has no squares.

    `script` is the data-hunk offset of the byte naming the area script in
    the buffer; the script-change opcode sets it before the new script loads,
    so it names the world map from the moment the party enters or leaves.
    `variables` is the data-hunk offset of a pointer to the script variables:
    the variable at C64 address `A` is the `u16be` at `[pointer] + 2 * A`.
    `area`, `node` and `leg` are C64 addresses: the area id, which is written
    only after the arriving script's entry returns, the place the party
    stands at, and the place it is going to.
    """

    script: int
    variables: int
    areas: tuple[int, ...]
    area: int = 0x4BF2
    node: int = 0x4C9B
    leg: int = 0x4C9C


@dataclass(frozen=True)
class AmigaMachine:
    """Where one title keeps the automapper's three inputs, as offsets.

    Every offset is into the executable's **data hunk**, which is how
    `tools/amiga/amiga68k.py` names a small-data global: `g57a0` is data hunk offset
    `0x57a0`, and `a4` is that hunk plus `0x7FFE`. Only the base moves from
    boot to boot, so these are constants of the build and the base is measured.

    `anchor` and `anchor_offset` are the string the base is found by, and
    where the executable carries it. `tools/amiga/amigatarget.py --verify` re-derives
    both off the player's own disk, so a different release with the string
    somewhere else is caught rather than silently misread.

    `width` is the size of x and y: 1 where the title stores them as bytes and
    2 where it stores them as `u16be`. Curse does the second and Silver Blades
    the first, which is why this is a field and not an assumption. The facing is
    one byte on every title, and the byte after it is the wall type ahead
    (`notes["wall_ahead"]`), so it is never read at `width`.
    """

    title: str
    #: The file in the ADF's root, as `tools/amiga/amiga68k.py --exe` wants it.
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
    #: Pools of Darkness only: the data-hunk offset of a pointer to the record
    #: whose byte at `overland_flag` is 1 while the party is on the 38 x 15
    #: overland, where `party_x`..`party_facing` are not written (the overland
    #: step routine at `0x2C9BA` keeps its cell at +0x25/+0x26 instead).
    overland_pointer: int | None = None
    overland_flag: int = 0x24
    #: Curse only: the Dalelands map, travelled by menu.
    world_map: WorldMap | None = None
    #: Pool of Radiance only: the anchor is in one hunk and the data in another.
    segments: Segments | None = None
    #: Pool of Radiance only: the square-engine travel grid.
    travel_grid: TravelGrid | None = None
    #: Anything else measured for this title, so a finding has somewhere to
    #: land that is not a new field nobody else uses.
    notes: dict[str, int] = field(default_factory=dict)


#: The titles whose offsets have been read out of their executables.
#:
#: Pool of Radiance is not a small-data build: its party struct is at
#: `h32+0x176f`, an offset into hunk 32 of a many-hunk executable, while its
#: anchor is in hunk 31. Its row says so with `segments`, and `data_base_for`
#: hops from the anchor's hunk to the data hunk.
MACHINES: dict[str, AmigaMachine] = {
    # `blades.cfg` is the string `docs/143` §5.2 already used to find `a4` in
    # this title, so the anchor is the one with a run behind it.
    "secret-of-the-silver-blades": AmigaMachine(
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
    # The camp bar. The map bar this row used to anchor on is also in the
    # code hunks of `/Secret`, `/Pools of Darkness` and Pool of Radiance's
    # `/program`, so a machine running any of those matched this row too; the
    # camp bar is in no other file on any Gold Box disk (Silver Blades' says
    # `Alt Fix Load`).
    "curse-of-the-azure-bonds": AmigaMachine(
        title="Curse of the Azure Bonds",
        executable="/Curse",
        anchor=b"Save View Magic Rest Alter Fix Exit",
        anchor_offset=0xC05,
        party_x=0x3F5E,
        party_y=0x3F60,
        party_facing=0x3F62,
        width=2,
        geo_pointer=0x5EB6,
        world_map=WorldMap(script=0x5CE1, variables=0x3D00,
                           areas=(0x50, 0x51)),
        notes={"wall_ahead": 0x3F63, "square_attribute": 0x3F64,
               "mode": 0x3D56},
    ),
    # The string is the spell-level name table, present once in this
    # executable and in neither `/Secret` nor `/Curse`. The party's square is
    # the six-byte struct `docs/124-amiga-port.md` §1.20 describes, and the map
    # pointer is the one global the code offsets by `+$100`, `+$200` and
    # `+$300` (`tests/amiga/test_amigatarget.py` pins it by that usage).
    "pools-of-darkness": AmigaMachine(
        title="Pools of Darkness",
        executable="/Pools of Darkness",
        anchor=b"Special" + bytes(34) + b"1st Level",
        anchor_offset=0x2FE6,
        party_x=0x5F20,
        party_y=0x5F21,
        party_facing=0x5F22,
        width=1,
        geo_pointer=0x7D7C,
        overland_pointer=0x57AC,
        notes={"wall_ahead": 0x5F23, "square_attribute": 0x5F24,
               "mode": 0x5B12, "previous_mode": 0x743C,
               "dungeon_map": 0x5F2C},
    ),
    # The weapon-name table in hunk 31. The block's own area word at `+0x1E4`
    # lags one crossing behind the area byte and must not be read. The facing
    # is already even on the grid and travel is four-way, so the heading is
    # the byte itself.
    "pool-of-radiance": AmigaMachine(
        title="Pool of Radiance",
        executable="/program",
        anchor=b"Bec De Corbin" + bytes(8) + b"Bill-Guisarme",
        anchor_offset=0x3D7,
        party_x=0x176F,
        party_y=0x1770,
        party_facing=0x1771,
        width=1,
        geo_pointer=0x171E,
        segments=Segments(anchor_hunk=31, data_hunk=32,
                          anchor_size=0x351C, data_size=0x2F84),
        travel_grid=TravelGrid(view=0xC1, views=(2, 3, 4), area=0x2F73,
                               areas=(25, 26, 27), block_pointer=0x98,
                               x=0x186, y=0x188, indoors=0x1CC),
        notes={"wall_ahead": 0x1772, "square_attribute": 0x1773},
    ),
}


class GuestError(NotConnected):
    """The guest blocked, or the emulator was not there to be read.

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

    **`WinuaePipe` is the other transport and the faster one.** This one is
    what every driven tool uses and is kept working: it needs no pipe, and its
    `W` and its single-stepping reach parts of the debugger the pipe will not
    send. Use it when the machine is nobody's to disturb.
    """

    #: The debugger this route enters holds the emulation thread at its `>`
    #: prompt, so a batch must resume the machine itself and a caller has to
    #: design around the pause. `WinuaePipe` sets this False.
    halts_machine = True

    #: Long, because the batch waits 700 ms after every typed line, `winuae.ps1
    #: send` polls for its receipt, and a 512K dump has to be base64'd by
    #: PowerShell. Measured cost is in `docs/143` §12.
    TIMEOUT = 300.0

    def __init__(self, holder: str, runner=None, timeout: float | None = None):
        if not holder:
            raise ValueError("a WinUAE lane claim is required: "
                             "`winuae.ps1 claim -Holder <name>` first")
        if not _HOLDER.fullmatch(holder):
            raise ValueError(f"not a holder name: {holder!r}")
        self.holder = holder
        #: Per holder, so two holders on the console route never overwrite
        #: each other's batch.
        self.batch_path = f"{GUEST_ROOT}\\wish-batch-{holder}.txt"
        self._run = runner or _run
        self.timeout = self.TIMEOUT if timeout is None else timeout
        #: Every batch this session sent, for a run log. Cheap and it is the
        #: thing you want when a poll came back wrong.
        self.batches: list[list[str]] = []

    # -- building the guest script ---------------------------------------

    def _script(self, lines: list[str], fetch: list[tuple[str, str]]) -> str:
        """The PowerShell the guest runs: write the batch, enter the debugger, inject, print.

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
            f"[IO.File]::WriteAllBytes('{self.batch_path}',"
            f"[Convert]::FromBase64String('{batch}'))",
            f"New-Item -ItemType Directory -Force -Path '{GUEST_DUMP}' "
            "| Out-Null",
            "Write-Output '<<key>>'",
            f"& {ps}{GUEST_ROOT}\\winuae.ps1 debugger "
            f"-Holder {self.holder}",
            "Write-Output '<<send>>'",
            f"& {ps}{GUEST_ROOT}\\winuae.ps1 send "
            f"'-File {self.batch_path}' -Holder {self.holder}",
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


#: The leading characters of the debugger commands this transport may send:
#: `m` (dump memory), `S` (save memory to a file), `W` (write memory) and `T`
#: (list tasks). `debug_line`'s `switch` selects a command by its first
#: character alone -- `qq`, `quit` and `q` are all `q`, which quits the
#: emulator, and `fs 1`, `fc 10` and `wd 1` reach the cycle and memory
#: watchpoint code that halts it -- so the guard compares that character and
#: never the whole first word. Every other character is blocked, including the
#: ones that can reach `activate_debugger()` and open a console window in front
#: of whoever is playing, which is the one thing this route exists to avoid.
SAFE_COMMANDS = frozenset("mSWT")


class PipeError(GuestError):
    """The pipe would not open, or the guest could not be reached.

    Separate from a bare `GuestError` because the caller may want to fall back
    to the console route -- `WinuaeDebugger` -- when the pipe is not reachable,
    and that is a different decision from a debugger command failing.
    """


def _pieces(cmd: str) -> list[str]:
    """One line split on unquoted `;`, as the emulator's master branch does.

    **WinUAE 6.0.3 does not split a line**: `debug_line` hands the whole string
    to one `switch` on its first character, so `m 0 1;g` is one `m`. The master
    branch walks the string tracking quotes and runs each `;`-separated piece.
    The guard checks every piece anyway, so a build that splits cannot have a
    go hidden behind a read, and a `;` inside quotes stays in one piece.
    """
    out, piece, quoted = [], [], False
    for ch in cmd:
        if ch == '"':
            quoted = not quoted
        if ch == ";" and not quoted:
            out.append("".join(piece))
            piece = []
            continue
        piece.append(ch)
    out.append("".join(piece))
    return out


def _check_commands(commands: list[str]) -> None:
    """Block every debugger command except the reading ones in `SAFE_COMMANDS`.

    Checked here rather than in the caller because every route into this
    transport goes through one function, and a batch is composed from several
    places.

    **Decided by the character `debug_line` switches on, not by the first
    word.** `ignore_ws` skips anything `_istspace`, so `g\tc00000` is a go with
    a tab in it, and `next_char` then takes one character: `qq` and `quit` are
    both a quit, and `wd 1` is a `w`. Each piece (see `_pieces`) is checked.

    Case is not folded. `debug_line`'s `switch (cmd)` is case-sensitive, so `T`
    and `t` are two different commands. `IPC_QUIT` is the one thing compared
    case-insensitively, because `uaeipc.cpp` uses `_tcsicmp` for it.
    """
    for cmd in commands:
        for piece in _pieces(cmd):
            text = piece.strip()
            if not text:
                continue
            head = text.split()[0]
            if head.lower() == "ipc_quit":
                raise ValueError(
                    "IPC_QUIT quits the emulator; it is never sent")
            if text[0] == "q":
                raise ValueError(
                    f"`{head}` starts with `q`, which quits the emulator; "
                    "it is never sent")
            if text[0] not in SAFE_COMMANDS:
                raise ValueError(
                    f"`{head}` starts with `{text[0]}`, which can halt the "
                    "emulator or open a console window in front of the "
                    "player; this transport sends reading commands only")


#: What a staged floppy path looks like: a file `WinGuest` copied into the disks
#: folder, named for an issue, its holder and a disk key. Dots only sit between
#: non-empty segments, so `..` cannot match.
FLOPPY_PATH = re.compile(
    r"C:\\Amiga\\Disks\\wish[0-9]+-[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\.adf")
FLOPPY_PATH_MAX = 200
_HOLDER = re.compile(r"[A-Za-z0-9._-]{1,64}")
_SHA256 = re.compile(r"[0-9A-Fa-f]{64}")
_TOKEN = re.compile(r"[0-9A-Fa-f]{12}")
_FLOPPY_PREFIX = re.compile(r"C:\\Amiga\\Disks\\wish[0-9]+-")
_DRIVE_LINE = re.compile(
    r"^DEBUG: drive ([0-3]) motor (?:off| on) cylinder\s*\d+ sel (?:yes|no) "
    r"(ro|rw) mfmpos \d+/\d+$", re.M)

#: How long the guest polls a drive after the setter, and how far apart.
FLOPPY_POLL_SECONDS = 10.0


class FloppyError(GuestError):
    """A floppy change was blocked, unanswered or not proved.

    `receipt` holds whatever the guest returned, so the raw replies survive a
    failure; the caller must not press a key on after one.
    """

    def __init__(self, message: str, receipt: dict | None = None):
        super().__init__(message)
        self.receipt = receipt or {}


class GuestRejection(FloppyError):
    """The lane script itself answered `fail ...`; `line` is that line, unchanged."""

    def __init__(self, line: str, receipt: dict | None = None):
        super().__init__("The guest blocked the floppy change: " + line[5:], receipt)
        self.line = line


def _guest_fail_line(text: str) -> str | None:
    """The `fail ...` first line of the output inside a failed run's error text, if it has one."""
    _, sep, output = text.partition(" failed: ")
    lines = [line.strip() for line in output.splitlines() if line.strip()] if sep else []
    return lines[0] if lines and lines[0].startswith("fail ") else None


@dataclass
class FloppyReceipt:
    """What one `drives` or `insert` verb did, with every raw reply kept."""

    verb: str
    holder: str
    drive: int | None
    path: str | None
    sha256: str | None
    status: str = ""
    output: str = ""
    seconds: float = 0.0
    pid: str | None = None
    started: str | None = None
    exe: str | None = None
    server_pid: str | None = None
    connect_ms: float | None = None
    #: `(seq, label)` -> `(guest milliseconds, raw reply bytes)`. Sequence 0 is
    #: the read before the setter (and the setter's own reply, label `set`);
    #: 1 upwards are the polls.
    replies: dict = field(default_factory=dict)
    #: The path was already in the target drive, so nothing was sent.
    already: bool = False
    #: Milliseconds from the setter's reply to the second `rw` poll.
    applied_ms: float | None = None
    #: Polls taken after the setter.
    polls: int = 0
    #: Each drive's path and `ro`/`rw` before the setter.
    before: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        """A form a run log can hold: raw replies as base64, one entry each."""
        return {
            "verb": self.verb, "holder": self.holder, "drive": self.drive,
            "path": self.path, "sha256": self.sha256, "status": self.status,
            "seconds": round(self.seconds, 3), "pid": self.pid,
            "started": self.started, "exe": self.exe,
            "server_pid": self.server_pid, "connect_ms": self.connect_ms,
            "already": self.already, "applied_ms": self.applied_ms,
            "polls": self.polls, "before": self.before,
            "replies": [
                {"seq": seq, "label": label, "ms": ms,
                 "raw": base64.b64encode(raw).decode("ascii")}
                for (seq, label), (ms, raw) in sorted(self.replies.items())],
        }

    def drive_state(self) -> dict:
        """Each drive's path and `ro`/`rw` at the read before any setter, parsed."""
        return _state_of(self, 0)

    def __str__(self) -> str:
        return self.status


def check_floppy_change(drive, path, holder, sha256) -> tuple[int, str, str, str]:
    """The request as it may be sent, or a `ValueError` before anything leaves.

    Only DF0 and DF1 may change, the path must be one file staged for `holder`
    in the disks folder, and nothing that could carry a second token, a
    directory climb or a network path gets through.
    """
    if isinstance(drive, bool) or not isinstance(drive, int) or drive not in (0, 1):
        raise ValueError(f"Floppy drive {drive!r} is not allowed: only DF0 and DF1 "
                         "may be changed")
    holder = _floppy_holder(holder)
    if not isinstance(path, str):
        raise ValueError(f"Floppy path {path!r} is not a disk this run staged "
                         f"for {holder}")
    reason = None
    if len(path) > FLOPPY_PATH_MAX:
        reason = f"it is longer than {FLOPPY_PATH_MAX} characters"
    elif any(ord(ch) < 32 or ord(ch) > 126 for ch in path):
        reason = "it holds a control or non-ASCII character"
    elif any(ch in ' "\';=%' for ch in path):
        reason = "it holds a space, quote, semicolon, equals sign or percent sign"
    elif ".." in path:
        reason = "it holds .."
    elif not FLOPPY_PATH.fullmatch(path):
        reason = "it is not a staged ADF under C:\\Amiga\\Disks"
    if reason:
        raise ValueError(f"Floppy path {path!r} is not allowed: {reason}")
    prefix = _FLOPPY_PREFIX.match(path)
    if not path[prefix.end():].startswith(holder + "-") \
            or len(path) == prefix.end() + len(holder) + 1 + len(".adf"):
        raise ValueError(f"Floppy path {path!r} belongs to another holder")
    if not isinstance(sha256, str) or not _SHA256.fullmatch(sha256):
        raise ValueError(f"SHA-256 {sha256!r} is not allowed: it is not 64 "
                         "hexadecimal digits")
    return drive, path, holder, sha256.lower()


def _floppy_holder(holder) -> str:
    if not isinstance(holder, str) or not _HOLDER.fullmatch(holder):
        raise ValueError(f"Holder {holder!r} is not allowed: it is not a lane-safe name")
    return holder


def _nul_text(raw: bytes, message: str, encoding: str) -> str:
    """One reply as text: exactly one NUL, at the end, and decodable."""
    if raw.count(b"\0") != 1 or not raw.endswith(b"\0"):
        raise FloppyError(f"Reply to {message} is not one NUL-terminated "
                          f"string: {raw.hex()}")
    try:
        return raw[:-1].decode(encoding)
    except UnicodeDecodeError as exc:
        raise FloppyError(f"Reply to {message} is not {encoding} text: "
                          f"{raw.hex()}") from exc


def _query_value(text: str, drive: int) -> str:
    """The value a `CFG floppy<N>` query read: `404` is an empty drive."""
    if text == "404":
        return ""
    if text.startswith("200 \n") and "\n" not in text[5:]:
        return text[5:]
    raise FloppyError(f"WinUAE answered CFG floppy{drive} with {text!r}, which "
                      "is neither 404 nor one 200 line")


def parse_drive_dump(text: str) -> dict[int, str]:
    """`ro` or `rw` for DF0 and DF1 out of a `DBG c` reply, one line each."""
    lines = [line.rstrip("\r") for line in text.split("\n")]
    found: dict[int, list[str]] = {0: [], 1: []}
    for line in lines:
        m = _DRIVE_LINE.match(line)
        if m and int(m.group(1)) in found:
            found[int(m.group(1))].append(m.group(2))
    for drive, modes in found.items():
        if len(modes) != 1:
            raise FloppyError(f"The drive dump has {'no' if not modes else 'more than one'}"
                              f" line for DF{drive}")
    return {drive: modes[0] for drive, modes in found.items()}


def _read_guest(out: str, verb: str, holder: str, drive, path, sha256,
                seconds: float) -> FloppyReceipt:
    """The guest's `<<tag>>` lines as a receipt; nothing is judged yet."""
    receipt = FloppyReceipt(verb, holder, drive, path, sha256, output=out,
                            seconds=seconds)
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    if lines:
        receipt.status = lines[0]
    ended = False
    for line in lines[1:]:
        if line == "<<end>>":
            ended = True
            continue
        if line.startswith("<<r>> "):
            bits = line.split(" ", 4)
            if len(bits) == 4:
                # An empty reply prints no payload, and the line loses its trailing space.
                bits.append("")
            try:
                _tag, seq, label, ms, payload = bits
                receipt.replies[(int(seq), label)] = (
                    float(ms), base64.b64decode(payload, validate=True))
            except (ValueError, base64.binascii.Error) as exc:
                raise FloppyError(f"The guest printed a malformed reply line: "
                                  f"{line[:120]}", receipt.as_dict()) from exc
            continue
        for tag in ("pid", "started", "exe", "server_pid", "connect_ms"):
            if line.startswith(f"<<{tag}>> "):
                value = line.split(" ", 1)[1]
                setattr(receipt, tag,
                        float(value) if tag == "connect_ms" else value)
    if not receipt.status.startswith("fail") and not ended:
        raise FloppyError("The guest script did not finish; its output ended: "
                          f"{out.strip()[-400:]}", receipt.as_dict())
    return receipt


def _check_status(receipt: FloppyReceipt) -> None:
    """Stop on the guest's own `fail` reply; anything but `ok` or `fail` is an error."""
    status = receipt.status
    if status.startswith("fail"):
        raise FloppyError("The guest blocked the floppy change: "
                          + status[5:], receipt.as_dict())
    if not status.startswith("ok"):
        raise FloppyError(f"The guest answered {status!r}, which is neither ok "
                          "nor fail", receipt.as_dict())


def _state_of(receipt: FloppyReceipt, seq: int, gate: bool = False) -> dict:
    """Each drive's path and `ro`/`rw` at one read, parsed from its raw replies."""
    try:
        got = {label: receipt.replies[(seq, label)][1]
               for label in ("q0", "q1", "dbg")}
    except KeyError as exc:
        raise FloppyError(f"The guest reported no {exc.args[0][1]} reply for "
                          f"read {seq}", receipt.as_dict()) from exc
    try:
        first = _nul_text(got["q0"], "CFG floppy0", "ascii")
        if gate and first in ("404", "501"):
            raise FloppyError("The WinUAE pipe is not answering configuration "
                              f"queries ({first}); nothing was sent")
        paths = {0: _query_value(first, 0),
                 1: _query_value(_nul_text(got["q1"], "CFG floppy1", "ascii"), 1)}
        modes = parse_drive_dump(_nul_text(got["dbg"], "DBG c", "latin-1"))
    except FloppyError as exc:
        exc.receipt = receipt.as_dict()
        raise
    return {"paths": paths, "modes": modes}


def _judge_insert(receipt: FloppyReceipt) -> None:
    """Decide from the raw replies alone whether the disk went in."""
    d, path = receipt.drive, receipt.path
    o = 1 - d

    def fail(text: str):
        raise FloppyError(text, receipt.as_dict())

    before = _state_of(receipt, 0, gate=True)
    receipt.before = {"paths": {f"DF{n}": v for n, v in before["paths"].items()},
                      "modes": {f"DF{n}": v for n, v in before["modes"].items()}}
    setter = receipt.replies.get((0, "set"))
    if before["paths"][o] == path:
        fail(f"{path} is already in DF{o}")
    if before["paths"][d] == path:
        if setter is not None:
            fail(f"The guest sent a setter although DF{d} already named {path}")
        if before["modes"][d] != "rw":
            fail(f"DF{d} names {path} but holds no disk")
        receipt.already = True
        return
    if setter is None:
        fail("The guest sent no setter and reported no reply to one")
    said = _nul_text(setter[1], f"the DF{d} change", "ascii")
    if said != "404":
        fail(f"WinUAE answered the DF{d} change with {said}; a setter answers 404")
    seqs = sorted({seq for seq, _ in receipt.replies if seq > 0})
    if not seqs:
        fail(f"DF{d} was never read after the change")
    seen_path = seen_ro = False
    run = 0
    last = ""
    for seq in seqs:
        now = _state_of(receipt, seq)
        last = now["paths"][d]
        if now["paths"][o] != before["paths"][o] or now["modes"][o] != before["modes"][o]:
            fail(f"DF{o} changed from {before['paths'][o] or '(empty)'} "
                 f"{before['modes'][o]} to {now['paths'][o] or '(empty)'} "
                 f"{now['modes'][o]} while DF{d} was being changed")
        if not seen_path and now["paths"][d] == path:
            seen_path = True
        if seen_path and not seen_ro:
            if now["modes"][d] == "ro":
                seen_ro = True
        elif seen_ro and receipt.applied_ms is None:
            if now["modes"][d] == "rw" and now["paths"][d] == path:
                run += 1
                if run == 2:
                    receipt.applied_ms = receipt.replies[(seq, "dbg")][0] - setter[0]
            else:
                run = 0
    receipt.polls = len(seqs)
    if not seen_path:
        fail(f"DF{d} never took {path} in {FLOPPY_POLL_SECONDS:.0f} s; it reads "
             f"{last or '(empty)'}")
    if not seen_ro:
        fail(f"DF{d} took {path} but was never seen empty, so the old disk may "
             "still be in it")
    if receipt.applied_ms is None:
        fail(f"DF{d} names {path} but holds no disk after "
             f"{FLOPPY_POLL_SECONDS:.0f} s")


# -- whole-machine snapshots, through the lane script --------------------------

#: Where `winuae.ps1` keeps each holder's machine snapshots on the guest.
STATE_ROOT = GUEST_ROOT + r"\States"

#: A snapshot name becomes a directory and a file name, so it is a word.
SNAPSHOT_NAME = re.compile(r"[A-Za-z0-9_-]{1,32}")

#: A Windows device name, in any case and with any extension: a path through one
#: opens the device rather than a file or folder.
WINDOWS_DEVICE = re.compile(r"(?i)(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?")

#: The names WinUAE gives its copies' pipes; the lane script records the one its own
#: emulator's boot log names.
LANE_PIPE_NAME = re.compile(r"WinUAE(?:_[1-9])?")

#: The lane script's `lane` reply: the lane, the emulator's pid and start time, and its pipe.
LANE_REPLY = re.compile(r"(?m)^ok lane=(\d+) pid=(\d+) started=\S+ pipe=(WinUAE(?:_[1-9])?)\s*$")

#: The completion marker's name; `~` cannot be in a snapshot name, so no snapshot
#: shares its path.
STATE_MARKER = "complete~"

#: How long the guest waits for WinUAE to write a state file; one took 1.3 s.
STATE_WAIT_SECONDS = 15.0

#: The first four bytes of every WinUAE state file.
STATE_HEADER = b"ASF "


class SnapshotError(GuestError):
    """A snapshot, restore or discard was blocked or not proved.

    `receipt` holds whatever the guest returned, so its raw replies survive.
    """

    def __init__(self, message: str, receipt: dict | None = None):
        super().__init__(message)
        self.receipt = receipt or {}


def snapshot_place(holder: str, name: str) -> tuple[str, str]:
    """The guest directory a snapshot lives in, and the state file inside it.

    WinUAE names the file it writes after the last component of
    `statefile_path`, so each snapshot has a directory of its own named like it.
    The guest writes into `_part_folder` and moves that to `<folder>` once the
    state and its `complete~` marker are in it. A holder of `.`, or one holding
    `..` or ending in a dot, is blocked, because Windows would resolve its
    folder to another one, and so is a Windows device name (`CON`, `NUL`,
    `COM1` and the rest, in any case) as a holder or a name.
    """
    holder = _floppy_holder(holder)
    if holder == "." or ".." in holder or holder.endswith("."):
        raise ValueError(f"Holder {holder!r} is not allowed: Windows would read it as "
                         "another folder")
    if WINDOWS_DEVICE.fullmatch(holder):
        raise ValueError(f"Holder {holder!r} is not allowed: it is a Windows device name")
    if not isinstance(name, str) or not SNAPSHOT_NAME.fullmatch(name):
        raise ValueError(f"Snapshot name {name!r} is not allowed: it is not 1-32 "
                         "letters, digits, - and _")
    if WINDOWS_DEVICE.fullmatch(name):
        raise ValueError(f"Snapshot name {name!r} is not allowed: it is a Windows device name")
    folder = f"{STATE_ROOT}\\{holder}\\{name}"
    return folder, f"{folder}\\{name}"


def _part_folder(holder: str, name: str) -> str:
    """Where the guest writes a snapshot before it replaces the old one.

    The last component has no dot: WinUAE wrote no file for a folder named
    `<name>.part`. `~` cannot be in a holder or a name, so it collides with neither.
    """
    return f"{STATE_ROOT}\\{holder}\\part~\\{name}"


@dataclass
class StateReceipt:
    """What one `snapshot`, `restore` or `discard-snapshot` verb did, raw replies kept."""

    verb: str
    holder: str
    name: str
    file: str
    status: str = ""
    output: str = ""
    seconds: float = 0.0
    #: Every `<<tag>> value` line but the replies and messages.
    tags: dict = field(default_factory=dict)
    #: `(seq, label)` -> `(guest milliseconds, raw reply bytes)`.
    replies: dict = field(default_factory=dict)
    #: `(seq, label)` -> the message text the guest sent.
    messages: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        """A form a run log can hold: raw replies as base64."""
        return {
            "verb": self.verb, "holder": self.holder, "name": self.name,
            "file": self.file, "status": self.status,
            "seconds": round(self.seconds, 3), "tags": dict(self.tags),
            "messages": [{"seq": s, "label": label, "text": text}
                         for (s, label), text in sorted(self.messages.items())],
            "replies": [{"seq": s, "label": label, "ms": ms,
                         "raw": base64.b64encode(raw).decode("ascii")}
                        for (s, label), (ms, raw) in sorted(self.replies.items())],
        }

    def __str__(self) -> str:
        return self.status


def _read_state(out: str, receipt: StateReceipt) -> StateReceipt:
    """Fill `receipt` from the guest's lines; a `fail` verdict raises `SnapshotError`."""
    receipt.output = out
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    receipt.status = lines[0] if lines else ""
    ended = False
    for line in lines[1:]:
        if line == "<<end>>":
            ended = True
            continue
        try:
            if line.startswith(("<<r>> ", "<<m>> ")):
                bits = line.split(" ", 4)
                if len(bits) == 4:
                    bits.append("")
                tag, seq, label, ms, payload = bits
                raw = base64.b64decode(payload, validate=True)
                if tag == "<<r>>":
                    receipt.replies[(int(seq), label)] = (float(ms), raw)
                else:
                    receipt.messages[(int(seq), label)] = raw.decode("ascii")
                continue
        except (ValueError, base64.binascii.Error, UnicodeDecodeError) as exc:
            raise SnapshotError(f"The guest printed a malformed line: {line[:120]}",
                                receipt.as_dict()) from exc
        m = re.match(r"<<([a-z0-9_]+)>> (.*)\Z", line)
        if m:
            receipt.tags[m.group(1)] = m.group(2)
    status = receipt.status
    if status.startswith("fail "):
        raise SnapshotError(f"The guest blocked the {receipt.verb}: {status[5:]}",
                            receipt.as_dict())
    if not status.startswith("ok"):
        raise SnapshotError(f"The guest answered {status!r}, which is neither ok "
                            "nor fail", receipt.as_dict())
    if not ended:
        raise SnapshotError("The guest script did not finish; its output ended: "
                            f"{out.strip()[-400:]}", receipt.as_dict())
    return receipt


def _judge_messages(receipt: StateReceipt, wanted: list[tuple[str, str]]) -> None:
    """The guest sent exactly `wanted`, in order, and WinUAE answered each `404`.

    A `CFG` setter answers `404` whether it worked or not, so the reply proves
    only that the message arrived; the file or the settle proves the rest.
    """
    sent = [(label, text) for (_seq, label), text in sorted(receipt.messages.items())]
    if sent != wanted:
        raise SnapshotError(f"The guest sent {sent}, not {wanted}", receipt.as_dict())
    for seq, (label, text) in enumerate(wanted):
        reply = receipt.replies.get((seq, label))
        if reply is None:
            raise SnapshotError(f"The guest reported no reply to {text!r}",
                                receipt.as_dict())
        if reply[1] != b"404\0":
            raise SnapshotError(f"WinUAE answered {text!r} with {reply[1]!r}; a "
                                "setter answers 404", receipt.as_dict())


class WinuaePipe:
    """The transport that does not touch the console: WinUAE's own named pipe.

    Every WinUAE process creates `\\\\.\\pipe\\WinUAE` at startup
    (`od-win32/win32.cpp`, `createIPC` with no condition on it), and a message
    beginning `DBG ` is handed to `debug_parser`, which points the debugger's
    console output at a buffer and hands the buffer back as the reply
    (`debug.cpp:8288`). The emulation thread services the pipe from
    `handle_msgpump`, so a command runs between two emulated instructions and
    the machine carries straight on: **no F11, no console, no focus change and
    no halt.**

    **The local case is the ordinary one.** Wish and WinUAE on one Windows
    machine is a local pipe opened by a local process; `connection="ssh"` is
    how this project drives its test VM from Linux and is the awkward case, not
    the base one. The two differ only in where the PowerShell runs, so the
    measured guest-side cost is the same number for both and the round trip is
    what the `ssh` adds.

    **Over `ssh` a debugger command goes to the lane `holder` claims.** The test
    VM runs one WinUAE per lane, and a second copy serves `WinUAE_1` rather than
    `WinUAE`, in start order, so the pipe is the one the lane's run receipt names,
    which the lane script's `lane` verb reports after it has checked the claim
    (`_open_by_lane`). A local pipe with no holder is opened by `pipe`.

    The framing is 8-bit text with no byte-order mark, and that is not a
    preference: a UTF-16 request takes a reply path that `_tcscpy`s into a
    16384-**byte** buffer while bounding at 16384 **characters**
    (`uaeipc.cpp:339`), so a long reply overruns it.

    A reply is capped near 16 KB whatever the framing, which is about 3 KB of
    memory through `m`. Anything larger goes through `S <file> <addr> <n>` to a
    file on the host, exactly as the console route already does.
    """

    #: The machine keeps running: the command is executed from
    #: `handle_msgpump`, between two emulated instructions, and nothing sets
    #: `debugger_active` or `SPCFLAG_BRK`. Measured on 2026-09-08 -- Exec's
    #: `DispCount` rose monotonically across twelve commands sent over one open
    #: handle, and the emulator's own status bar read 49.9 FPS throughout.
    halts_machine = False

    #: One client at a time: the pipe is created with `nMaxInstances` 1. Long
    #: enough that another agent's poll can finish, short enough that a dead
    #: emulator is reported rather than waited on.
    CONNECT_MS = 5000

    #: The guest waits this long for one reply before giving up. A read is
    #: milliseconds; this is only there so a lost message cannot hang the ssh.
    READ_MS = 10000

    #: The whole round trip, `ssh` included.
    TIMEOUT = 60.0

    def __init__(self, runner=None, timeout: float | None = None,
                 pipe: str = "WinUAE", connection: str = "ssh",
                 holder: str | None = None):
        self._run = runner or _run
        self.timeout = self.TIMEOUT if timeout is None else timeout
        self.pipe = pipe
        if connection not in ("ssh", "local"):
            raise ValueError(f"connection {connection!r} is neither 'ssh' nor "
                             "'local'")
        self.connection = connection
        if holder is not None and not _HOLDER.fullmatch(holder):
            raise ValueError(f"the lane holder {holder!r} is not a lane holder name")
        #: The lane claim whose emulator a debugger command goes to; over ssh the
        #: guest has several WinUAE copies, and only the lane script knows whose is whose.
        self.holder = holder
        #: Every command this session sent, for a run log.
        self.sent: list[str] = []

    # -- the guest script ------------------------------------------------

    def script(self, commands: list[str], repeat: int = 1,
               fetch: list[tuple[str, str]] | None = None) -> str:
        """The PowerShell that opens the pipe, sends, reads and times.

        Each command is carried to the guest as base64, so nothing in it -- a
        `S C:\\Amiga\\dump\\x.bin` with its backslashes, a quote -- has to
        survive `ssh`, the guest's shell and PowerShell's own parser.

        `repeat` sends the whole list that many times over **one** open handle,
        which is how the local cost is measured with no connection setup and no
        `ssh` in the number.

        `fetch` is `(name, path)`, and each file is printed after the last
        reply as `<<name>>` and then its base64 -- the same markers
        `WinuaeDebugger` uses, so `_blob` reads either transport's output. A
        file that is not there prints `MISSING` rather than throwing, because
        one absent dump must not lose the replies that say why.
        """
        _check_commands(commands)
        if self.connection == "ssh" and self.holder is None:
            raise ValueError("a debugger command over ssh needs the lane holder, because "
                             "a pipe opened by name can be another lane's emulator")
        return self._framed([f"DBG {c}" for c in commands], repeat, fetch)

    def _open_by_name(self) -> str:
        """The PowerShell that opens the pipe by its name: one WinUAE, no lanes."""
        return f"""  $p=New-Object IO.Pipes.NamedPipeClientStream '.','{self.pipe}','InOut'
  $p.Connect({self.CONNECT_MS})"""

    def _open_by_lane(self) -> str:
        """The PowerShell that opens the pipe the holder's own emulator serves.

        Each copy takes the first free of `WinUAE`, `WinUAE_1`..`WinUAE_9`, so the name
        says nothing about whose emulator it is. The lane script's `lane` verb checks
        the claim, the run receipt and the executable, and names the pid and the pipe the
        lane's run receipt records. Only that pipe is opened, and its server process
        must be that pid.
        """
        script = r"""  $lane=(& powershell.exe -NoProfile -ExecutionPolicy Bypass -File '@SCRIPT@' lane -Holder '@HOLDER@' 2>&1 | Out-String).Trim()
  if ($lane -notmatch '@REPLY@') { throw [InvalidOperationException]::new(($lane -replace '\s+',' ')) }
  [uint32]$lanePid=$Matches[2]
  $name=$Matches[3]
  Write-Output ('<<lane>> ' + $Matches[1] + ' ' + $lanePid + ' ' + $name)
  if (-not ('WishPipe.Info' -as [type])) {
    Add-Type -Namespace WishPipe -Name Info -MemberDefinition '[DllImport("kernel32.dll", SetLastError=true)] public static extern bool GetNamedPipeServerProcessId(IntPtr Pipe, out uint ServerProcessId);'
  }
  $live=@([IO.Directory]::GetFiles('\\.\pipe\') | ForEach-Object { [IO.Path]::GetFileName($_) })
  if ($live -cnotcontains $name) { throw [InvalidOperationException]::new("\\.\pipe\$name, which @HOLDER@'s winuae64 pid=$lanePid opened, is gone") }
  $p=New-Object IO.Pipes.NamedPipeClientStream '.',$name,'InOut'
  $p.Connect(@CONNECT@)
  try {
    $p.ReadMode=[IO.Pipes.PipeTransmissionMode]::Message
    [uint32]$owner=0
    if (-not ([WishPipe.Info]::GetNamedPipeServerProcessId($p.SafePipeHandle.DangerousGetHandle(),[ref]$owner) -and $owner -eq $lanePid)) {
      throw [InvalidOperationException]::new("\\.\pipe\$name is served by pid=$owner, not by @HOLDER@'s winuae64 pid=$lanePid; stop the lane and start it again")
    }
  } catch {
    # A pipe closed with no request sent is closed for good by WinUAE, so one read goes first.
    try {
      $q=[Text.Encoding]::ASCII.GetBytes('CFG floppy0')
      $m=New-Object byte[] ($q.Length+1)
      [Array]::Copy($q,$m,$q.Length)
      $p.Write($m,0,$m.Length)
      $p.Flush()
      $p.ReadAsync((New-Object byte[] 65536),0,65536).Wait(@READ@) | Out-Null
    } catch { }
    $p.Dispose()
    throw
  }"""
        return (script.replace("@SCRIPT@", self.LANE_SCRIPT)
                .replace("@HOLDER@", self.holder or "")
                .replace("@REPLY@", LANE_REPLY.pattern)
                .replace("@CONNECT@", str(self.CONNECT_MS))
                .replace("@READ@", str(self.READ_MS)))

    def _framed(self, messages: list[str], repeat: int = 1,
                fetch: list[tuple[str, str]] | None = None) -> str:
        """The PowerShell for messages that already carry their prefix.

        `script` prefixes `DBG ` after `_check_commands`, so a debugger command
        can never go down as `CFG `. The one `CFG` message this project sends
        is built in `winuae.ps1`, never here.
        """
        if not messages:
            raise ValueError("a pipe opened with no message to send is closed with nothing sent, "
                             "which makes WinUAE close it for good")
        encoded = ",".join(
            "'" + base64.b64encode(m.encode("ascii")).decode("ascii")
            + "'" for m in messages)
        tail = []
        for name, path in (fetch or []):
            tail.append(f"Write-Output '<<{name}>>'")
            tail.append(
                f"if (Test-Path -LiteralPath '{path}') {{ "
                f"Write-Output ([Convert]::ToBase64String("
                f"[IO.File]::ReadAllBytes('{path}'))); "
                f"Remove-Item -LiteralPath '{path}' -Force }} "
                "else { Write-Output 'MISSING' }")
        fetched = "\n".join(tail)
        opened = self._open_by_lane() if self.holder is not None else self._open_by_name()
        return f"""$ErrorActionPreference='Stop'
$sw=[Diagnostics.Stopwatch]::StartNew()
try {{
{opened}
  $p.ReadMode=[IO.Pipes.PipeTransmissionMode]::Message
}} catch {{
  $e=$_.Exception
  Write-Output ('<<error>> ' + $e.GetType().FullName)
  Write-Output ('<<message>> ' + $e.Message)
  Write-Output ('<<hresult>> ' + ('0x{{0:X8}}' -f $e.HResult))
  Write-Output ('<<win32>> ' + ($e.HResult -band 0xffff))
  Write-Output '<<end>>'
  exit 1
}}
Write-Output ('<<connect_ms>> ' + $sw.ElapsedMilliseconds)
$cmds=@({encoded})
$buf=New-Object byte[] 65536
for ($r=0; $r -lt {repeat}; $r++) {{
  foreach ($c in $cmds) {{
    $b=[Convert]::FromBase64String($c)
    $msg=New-Object byte[] ($b.Length+1)
    [Array]::Copy($b,$msg,$b.Length)
    $t0=$sw.Elapsed.TotalMilliseconds
    $p.Write($msg,0,$msg.Length)
    $p.Flush()
    $ms=New-Object IO.MemoryStream
    do {{
      $task=$p.ReadAsync($buf,0,$buf.Length)
      if (-not $task.Wait({self.READ_MS})) {{
        Write-Output '<<timeout>>'
        Write-Output '<<end>>'
        exit 1
      }}
      $n=$task.Result
      if ($n -gt 0) {{ $ms.Write($buf,0,$n) }}
      if ($n -eq 0) {{ break }}
    }} while (-not $p.IsMessageComplete)
    $t1=$sw.Elapsed.TotalMilliseconds
    Write-Output ('<<reply>> ' + [Math]::Round($t1-$t0,3) + ' ' +
      [Convert]::ToBase64String($ms.ToArray()))
  }}
}}
$p.Dispose()
{fetched}
Write-Output '<<end>>'
"""

    # -- sending ---------------------------------------------------------

    def send(self, commands: list[str], repeat: int = 1,
             with_timings: bool = False):
        """Send debugger commands and give back `(command, reply)` pairs.

        With `with_timings`, a second value comes back: the milliseconds the
        **guest** spent on each write-and-read, measured on the guest's own
        stopwatch, so an `ssh` round trip is not in the number.
        """
        self.sent += list(commands)
        out = self._execute(self.script(commands, repeat=repeat))
        replies, timings = self._replies(out, list(commands) * repeat)
        return (replies, timings) if with_timings else replies

    FLOPPY_PATH = FLOPPY_PATH

    #: The lane script that owns the ownership checks and the pipe for a floppy
    #: change, as it is deployed on the guest.
    LANE_SCRIPT = "C:\\Amiga\\winuae.ps1"

    def drives(self, holder: str, token: str | None = None) -> FloppyReceipt:
        """Read what each drive holds: the path WinUAE accepted and `ro` or `rw`.

        The guest checks the lane claim, the run receipt, the executable and the
        pipe's server process before it reads, in the one process that holds the
        pipe. Nothing is changed.
        """
        holder = _floppy_holder(holder)
        out, seconds = self.lane_verb("drives", holder, token, [])
        receipt = _read_guest(out, "drives", holder, None, None, None, seconds)
        _check_status(receipt)
        _state_of(receipt, 0, gate=True)
        return receipt

    def insert_floppy(self, drive: int, path: str, holder: str, sha256: str,
                      token: str | None = None,
                      staged: Collection[str] | None = None) -> FloppyReceipt:
        """Put a staged ADF into DF0 or DF1 of the running machine, and prove it went in.

        The setter is `CFG floppy<N> <path>`; it answers `404` whether it worked
        or not, and the query `CFG floppy<N>` only shows the name WinUAE
        accepted. So success is a poll over one connection: the query shows the
        path, the drive reads `ro`, then two consecutive polls read `rw` with
        the path unchanged, and the other drive never moves. The guest does the
        connecting, the ownership checks, the send and the poll; this blocks a
        bad request before anything leaves and judges the raw replies afterwards.

        A drive is 0 or 1 (an `int`, never a `bool`); `path` is the Windows form
        of a disk staged for `holder`; `sha256` is the staged file's hash, which
        the guest compares before it sends anything. A path already in the
        target drive sends nothing. When `staged` is given, `path` must be one of
        the paths this run copied to the guest. Any failure raises `FloppyError`,
        whose `receipt` keeps every reply, and the caller must not press a key on.
        """
        drive, path, holder, sha256 = check_floppy_change(
            drive, path, holder, sha256)
        if staged is not None and path not in staged:
            raise ValueError(f"Floppy path {path!r} is not a disk this run staged "
                             f"for {holder}")
        out, seconds = self.lane_verb("insert", holder, token,
                                  [str(drive), path, sha256])
        receipt = _read_guest(out, "insert", holder, drive, path, sha256, seconds)
        _check_status(receipt)
        _judge_insert(receipt)
        return receipt

    def lane_verb(self, verb: str, holder: str, token: str | None,
                  args: list[str]) -> tuple[str, float]:
        """Run one `winuae.ps1` verb on the guest: its output and the seconds it took.

        `insert_floppy` and `drives` are the callers; a control that must reach the
        guest's own checks with a request Python would block calls this directly.
        """
        if not LANE_PIPE_NAME.fullmatch(self.pipe):
            raise ValueError(f"The pipe {self.pipe!r} is not allowed: the lane script "
                             "reaches a WinUAE pipe only")
        words = [verb, "-Holder", holder]
        if token is not None:
            if not _TOKEN.fullmatch(token):
                raise ValueError(f"Claim token {token!r} is not allowed: it is not "
                                 "twelve hexadecimal digits")
            words += ["-Token", token]
        words += args
        if self.connection == "local":
            argv = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", self.LANE_SCRIPT, *words]
        else:
            argv = ["winvm", "ssh", "powershell -NoProfile -ExecutionPolicy Bypass "
                    f"-File {self.LANE_SCRIPT} " + " ".join(words)]
        begun = time.monotonic()
        try:
            return self._run(argv, self.timeout), time.monotonic() - begun
        except GuestError as exc:
            # The lane script exits 1 on a `fail` reply made before it opened the pipe.
            text = str(exc)
            line = _guest_fail_line(text)
            if line is not None:
                raise GuestRejection(line, {"output": text}) from exc
            raise FloppyError(f"The guest could not be run: {text}",
                              {"output": text}) from exc

    def blocked_verb_reason(self, verb: str, holder: str, args: list[str]) -> str:
        """Run a lane verb that a control expects the guest to block; give its first line.

        A `fail` first line raises `GuestRejection` with the guest's line, whether the
        guest exited 1 before opening the pipe or 0 after it, exactly as
        `insert_floppy` reads a verdict. Any other first line is returned so the
        caller can record what the guest said instead. A transport or PowerShell
        failure stays a bare `FloppyError`, never a `GuestRejection`.
        """
        out, _seconds = self.lane_verb(verb, holder, None, args)
        lines = [line.strip() for line in out.splitlines() if line.strip()]
        status = lines[0] if lines else ""
        if status.startswith("fail "):
            raise GuestRejection(status, {"output": out})
        return status

    # -- whole-machine snapshots -----------------------------------------

    def _state_verb(self, verb: str, holder: str, name: str,
                    token: str | None, extra: tuple[str, ...] = ()) -> StateReceipt:
        """Run one snapshot verb and read its receipt; nothing is judged but the verdict."""
        _folder, file = snapshot_place(holder, name)
        receipt = StateReceipt(verb, holder, name, file)
        try:
            out, receipt.seconds = self.lane_verb(verb, holder, token, [name, *extra])
        except GuestRejection as exc:
            raise SnapshotError(f"The guest blocked the {verb}: {exc.line[5:]}",
                                exc.receipt) from exc
        except FloppyError as exc:
            raise SnapshotError(str(exc), exc.receipt) from exc
        return _read_state(out, receipt)

    def snapshot(self, name: str, holder: str,
                 token: str | None = None) -> StateReceipt:
        """Save the whole running machine under `name`, and prove the file was written.

        The guest checks the lane claim and the pipe's server process, reads
        Exec's idle and dispatch counts, then sends `CFG statefile_save x` and
        `CFG statefile_path <holder folder>\\part~\\<name>`: the first leaves a
        save pending, the second points it at `part~\\<name>\\<name>` and the
        save completes (a last component with a dot in it got no file). `CFG statefile_save <name>` alone writes nothing. The guest
        waits up to `STATE_WAIT_SECONDS` for a file that starts `ASF ` and has
        stopped growing, writes a `complete~` marker with its hash
        and the count, and only then replaces any older snapshot of the name: the old folder
        is renamed to a backup, the new one moved in, and the backup deleted, or
        renamed back if the move fails.
        On a failure the temporary folder is removed and the older snapshot is
        kept. The machine runs on.

        **A failure after `statefile_save x` was sent leaves that save pending
        in WinUAE**, and the next `statefile_path` sent to the process completes
        it; the error says so.

        The state holds each drive's image path and mechanics, not the disk's
        contents, and `statefile_path` stays at the temporary folder for the life
        of the emulator process.
        """
        receipt = self._state_verb("snapshot", holder, name, token)
        folder, file = snapshot_place(holder, name)
        _judge_messages(receipt, [("save", "CFG statefile_save x"),
                                  ("path", "CFG statefile_path " + _part_folder(holder, name))])
        tags = receipt.tags
        if "appeared_ms" not in tags:
            raise SnapshotError(f"The state file {file} did not appear within "
                                f"{STATE_WAIT_SECONDS:.0f} s, and WinUAE still holds "
                                "the pending state save", receipt.as_dict())
        if tags.get("marker") != f"{folder}\\{STATE_MARKER}":
            raise SnapshotError(f"The snapshot {file} has no completion marker",
                                receipt.as_dict())
        if not tags.get("count_snapshot", "").isdigit():
            raise SnapshotError(f"The snapshot {file} recorded no Exec count to "
                                "verify a restore against", receipt.as_dict())
        if tags.get("file") != file:
            raise SnapshotError(f"The guest watched {tags.get('file')!r}, not {file}",
                                receipt.as_dict())
        if tags.get("header", "").lower() != STATE_HEADER.hex():
            raise SnapshotError(f"The state file {file} does not start with ASF",
                                receipt.as_dict())
        if not tags.get("bytes", "").isdigit() or int(tags["bytes"]) <= 0:
            raise SnapshotError(f"The state file {file} is empty", receipt.as_dict())
        return receipt

    def restore(self, name: str, holder: str,
                token: str | None = None, fresh: bool = False) -> StateReceipt:
        """Put the machine back as `snapshot(name)` left it, and prove it went back.

        The guest blocks a snapshot with no `complete~` marker or whose file
        does not hash as the marker says. It reads Exec's idle and dispatch
        counts, sends `CFG statefile <file>`, and reads them again until they
        fall to between the snapshot's value and the value read before the
        restore: both counts only rise while the machine runs, so only a
        machine that went back reads lower. A read that fails during the 5 s
        counts as not back yet, and the error names the last one. It then waits
        `RestoreSettleMs`, so a key pressed after this reaches the restored
        machine.

        The proof fails safe when the counts do not move (a machine stopped in
        the debugger, or a program that stops Exec switching tasks), and it
        cannot tell a restore from a reset: a snapshot taken in the first
        seconds after a boot has a count so small that a reset during the
        restore could pass it. `docs/70-driving-the-game.md` has the
        measurements.

        Each drive gets the image path the state recorded put back in it, and an
        image written since the snapshot keeps that write: a game save made
        between the snapshot and the restore stays on the disk while memory goes
        back, so the run must treat that image as changed.

        The proof is chosen from the counts. Where `before < snap` (a machine
        just booted, or at an earlier machine time than the snapshot) it is
        `before < snap <= after`, which a reset during the restore cannot pass
        because a reset reads below `before`; where `before > snap` it is the
        range above; where they are equal nothing is proven. `fresh` is still
        sent to the guest and changes nothing.
        """
        folder, file = snapshot_place(holder, name)
        receipt = self._state_verb("restore", holder, name, token,
                                   ("-Fresh",) if fresh else ())
        _judge_messages(receipt, [("restore", f"CFG statefile {file}")])
        tags = receipt.tags
        if tags.get("marker") != f"{folder}\\{STATE_MARKER}":
            raise SnapshotError(f"The snapshot {file} has no completion marker",
                                receipt.as_dict())
        try:
            snap, before, after = (int(tags[k]) for k in
                                   ("count_snapshot", "count_before", "count_after"))
        except (KeyError, ValueError) as exc:
            raise SnapshotError(f"The restore of {file} reported no Exec counts, so "
                                "it was not verified", receipt.as_dict()) from exc
        if before == snap:
            raise SnapshotError(f"The restore of {name} is unproven: Exec's count reads "
                                f"{before}, the snapshot's own", receipt.as_dict())
        if before < snap:
            if after < snap:
                raise SnapshotError(f"The machine was not seen to go back to {name}: "
                                    f"Exec's count read {after}, not {snap} or more",
                                    receipt.as_dict())
        elif not snap <= after < before:
            raise SnapshotError(f"The machine was not seen to go back to {name}: "
                                f"Exec's count read {after}, not between {snap} "
                                f"and {before}", receipt.as_dict())
        return receipt

    def stage_snapshot(self, name: str, holder: str, sha256: str, count: int,
                       token: str | None = None) -> StateReceipt:
        """Install a state file put in the guest's disk folder as snapshot `name`.

        The guest needs the holder's claim but no running emulator. It checks the
        `ASF ` header and the hash before it writes the completion marker, so a
        later `restore(fresh=True)` in a new process finds the snapshot as if it
        had been taken here.
        """
        folder, file = snapshot_place(holder, name)
        receipt = self._state_verb("stage-snapshot", holder, name, token,
                                   (sha256, str(count)))
        tags = receipt.tags
        if tags.get("marker") != f"{folder}\\{STATE_MARKER}" or tags.get("file") != file:
            raise SnapshotError(f"The guest staged {tags.get('file')!r}, not {file}",
                                receipt.as_dict())
        if tags.get("sha256", "").lower() != sha256.lower():
            raise SnapshotError(f"The staged state hashes to {tags.get('sha256')}, "
                                f"not {sha256}", receipt.as_dict())
        return receipt

    def discard_snapshot(self, name: str, holder: str,
                         token: str | None = None) -> StateReceipt:
        """Delete the snapshot `name` and its folder; a name never saved is not an error."""
        receipt = self._state_verb("discard-snapshot", holder, name, token)
        if receipt.messages or receipt.replies:
            raise SnapshotError("The guest sent a message to WinUAE for a discard",
                                receipt.as_dict())
        return receipt

    def batch(self, lines: list[str],
              fetch: list[tuple[str, str]] | None = None
              ) -> tuple[str, dict[str, bytes | None]]:
        """`WinuaeDebugger.batch`'s interface, so `AmigaTarget` needs neither told.

        The two transports answer the same call and differ in one thing a
        caller can see: `halts_machine`. **Nothing here appends a `g`**, and a
        caller must not send one -- there is no halt to resume, and `g` is one
        of the commands that can reach `activate_debugger()`.
        """
        fetch = fetch or []
        script = self.script(lines, fetch=fetch)
        if fetch:
            # `S` opens its file for writing and cannot create the directory
            # above it, so a guest without `GUEST_DUMP` answers every dump with
            # `Couldn't open file`. It is made at the head of every dumping
            # script: idempotent, no extra round trip, and `-ErrorAction Stop`
            # makes PowerShell exit non-zero, so `_run` raises `GuestError`.
            script = (f"New-Item -ItemType Directory -Force -Path "
                      f"'{GUEST_DUMP}' -ErrorAction Stop | Out-Null\n{script}")
        self.sent += list(lines)
        out = self._execute(script)
        replies, _timings = self._replies(out, list(lines))
        text = "\n".join(f"--- {cmd}\n{reply}" for cmd, reply in replies)
        return text, {name: _blob(out, name) for name, _path in fetch}

    def _execute(self, script: str) -> str:
        """Run one script on the guest and check it got to the end."""
        out = self._run(self._argv(script), self.timeout)
        if "<<error>>" in out:
            raise PipeError(self._error(out))
        if "<<timeout>>" in out:
            raise PipeError("the pipe accepted a command and never replied "
                            f"in {self.READ_MS} ms")
        if "<<end>>" not in out:
            raise PipeError("the guest script did not finish; its output "
                            f"ended: {out.strip()[-400:]}")
        return out

    @staticmethod
    def _replies(out: str, wanted: list[str]):
        """The guest's `<<reply>>` lines, paired back up with their commands.

        The reply carries the debugger's own text with the trailing NUL that
        `checkIPC` writes; `latin-1` rather than `ascii` because a memory dump's
        character column is whatever bytes were there.
        """
        replies, timings = [], []
        for line in out.splitlines():
            line = line.strip()
            if not line.startswith("<<reply>> "):
                continue
            _tag, ms, payload = line.split(" ", 2)
            timings.append(float(ms))
            text = base64.b64decode(payload).decode("latin-1").rstrip("\x00")
            replies.append((wanted[len(replies)] if len(replies) < len(wanted)
                            else "", text))
        if len(replies) != len(wanted):
            raise PipeError(f"sent {len(wanted)} commands and the guest "
                            f"reported {len(replies)} replies")
        return replies, timings

    def _argv(self, script: str) -> list[str]:
        """How the guest is reached, and `local` is the ordinary case.

        `local` is Wish and WinUAE on one Windows machine, which is how a
        player would run it: no network and no session boundary, just a local
        pipe. `ssh` is this project's Linux test rig reaching the Windows VM,
        and it is the arrangement that costs the round trip.
        """
        encoded = encode(script)
        if self.connection == "local":
            return ["powershell", "-NoProfile", "-EncodedCommand", encoded]
        return ["winvm", "ssh", "powershell -NoProfile -EncodedCommand "
                + encoded]

    @staticmethod
    def _error(out: str) -> str:
        """The guest's exception, as one line a person can act on."""
        bits = {}
        for line in out.splitlines():
            line = line.strip()
            for tag in ("error", "message", "hresult", "win32"):
                if line.startswith(f"<<{tag}>> "):
                    bits[tag] = line.split(" ", 1)[1]
        return (f"the pipe would not open: {bits.get('error', '?')}: "
                f"{bits.get('message', '?')} "
                f"(HRESULT {bits.get('hresult', '?')}, "
                f"Win32 {bits.get('win32', '?')})")

    # -- reading memory --------------------------------------------------

    def memory(self, addr: int, length: int) -> bytes:
        """Bytes, through `m`, parsed out of the debugger's own dump format.

        `m` prints `<addr> <8 hex words> <16 characters>` a line, 16 bytes to
        the line, so a read is `ceil(length / 16)` lines and the caller's start
        is found by address rather than by counting: the debugger rounds the
        address it was given down to an even one.

        **The line count is hex**, like the address: `lines = readhex(&inptr)`
        in `debug.cpp`'s `m`. Passing it in decimal asks for more lines than
        were wanted, which is harmless to the bytes and wastes the budget
        below.

        Two limits, and the second is the one that surprises people:

        * a reply is capped near 16 KB, which is about 3 KB of memory. Past
          that this raises rather than coming back short.
        * **`m` stops printing after `MAX_LINECOUNTER` lines and never starts
          again**, for the life of the emulator process. `debug_out` counts to
          1000 and then returns 0, and `debug_linecounter` is reset in exactly
          one place -- `debug_1`, at the interactive `>` prompt, which this
          route deliberately never reaches. Each dumped line costs two
          `debug_out` calls, so the whole budget is about **500 lines, or 8 KB
          of memory, per emulator process**. Measured on 2026-09-08: a fresh
          process answered `m 0 40` with 64 lines, and after 548 more lines the
          same `m 0 4` came back with one.

        So **`S <file> <addr> <n>` is the read path for anything repeated**,
        and it is what `AmigaTarget` uses: `S` prints its one receipt line
        through `console_out_f` and a 512 KB dump still worked after 1200
        commands. `m` is for a probe, and this raises rather than lying when
        the budget has gone.
        """
        if length <= 0:
            raise ValueError(f"a read of {length} bytes is not a read")
        if length > 3072:
            raise ValueError(
                f"{length} bytes is more than one 16 KB reply can carry; use "
                "`S <file> <addr> <n>` and read the file back")
        start = addr & ~1
        lines = (length + (addr - start) + 15) // 16
        (_cmd, reply), = self.send([f"m {start:x} {lines:x}"])
        got = parse_memory_dump(reply)
        out = bytearray()
        for i in range(addr, addr + length):
            if i not in got:
                raise PipeError(
                    f"`m {start:x} {lines:x}` printed {len(got)} of the "
                    f"{length} bytes asked for and stopped before {i:#x}. "
                    "After about 500 dumped lines WinUAE's `m` prints one "
                    "line and no more, for the life of the process, because "
                    "`debug_linecounter` is only reset at the interactive "
                    "prompt this route never opens. Read through `S <file> "
                    "<addr> <n>` instead, or restart the emulator.")
            out.append(got[i])
        return bytes(out)


#: One line of the debugger's `m` output: an eight-digit address, then the hex.
RE_DUMP_LINE = re.compile(r"^([0-9A-Fa-f]{8})\s+((?:[0-9A-Fa-f]{2,4}\s+){1,8})")


def parse_memory_dump(text: str) -> dict[int, int]:
    """`{address: byte}` out of what the debugger's `m` command printed.

    Written as a dictionary keyed by address rather than a flat block because
    the debugger decides for itself where a line starts, and a reader that
    assumed the first line began at the address it asked for would be off by
    one byte whenever it asked for an odd one.

    The ASCII column is not parsed and cannot be: it holds spaces, so it is not
    separable from the hex by whitespace. The regex takes the address and the
    hex groups that follow it and stops.
    """
    out: dict[int, int] = {}
    for line in text.splitlines():
        m = RE_DUMP_LINE.match(line.strip())
        if not m:
            continue
        addr = int(m.group(1), 16)
        for word in m.group(2).split():
            for i in range(0, len(word), 2):
                out[addr] = int(word[i:i + 2], 16)
                addr += 1
    return out


#: The port `barto_gdbserver.cpp` listens on when `remote_debugger_port` is not
#: given: `#define DEFAULT_PORT 2345`. The WinUAE sibling hard-codes the same
#: number; on FS-UAE it is configurable, which is what lets two runs coexist.
FSUAE_PORT = 2345

#: Packets that would stop the machine or end the run, blocked by name. Each is
#: read off `barto_gdbserver.cpp`'s own dispatch rather than guessed:
#:
#: * `k` -- kill, and the emulator goes with it;
#: * `D` -- detach, which drops the connection, and this server closes its
#:   *listening* socket when a connection goes, so the door does not come back;
#: * `s`, `S` and `vCont;s` -- single-step, which sets `state::debugging` and
#:   leaves the machine stopped at a `>` that nothing here will ever type at;
#: * `vCont;t` -- stop, the same;
#: * `\\x03` -- the interrupt byte, which calls `activate_debugger()`.
#:
#: This transport reads a machine somebody is playing. Everything it needs is
#: `qSupported`, `vCont;c` and `m`, so the check is on the packet's **first
#: character**, which is what the server's own dispatch switches on.
UNSAFE_PACKETS = frozenset("kDsS") | {"\x03"}

#: The `vCont` actions that stop the machine. `vCont;c` is the only one sent.
UNSAFE_ACTIONS = ("vCont;s", "vCont;S", "vCont;t")


def _console_output(body: str) -> bool:
    """Is this packet the guest printing, rather than an answer to us?

    `barto_gdbserver.cpp` forwards the Amiga's own `KPutChar` output as
    `$O<hex>`, unasked, so one can land between a request and its reply. The
    test is the payload: hex-encoded text, an even number of digits. `OK`
    fails it on both counts and is a reply.
    """
    payload = body[1:]
    return (body[:1] == "O" and len(payload) > 0 and len(payload) % 2 == 0
            and all(c in "0123456789abcdefABCDEF" for c in payload))


class FsuaeError(NotConnected):
    """The patched FS-UAE was not there, or would not answer.

    A `NotConnected` for the same reason `GuestError` is one: an emulator that
    has not been started yet is a state to wait out rather than a crash. It is
    **not** a `GuestError`, because there is no guest -- nothing here shells
    out, and a caller distinguishing "the VM is unreachable" from "the socket
    is not open" is asking two different questions.
    """


class FsuaeGdb:
    """The transport that speaks GDB-remote to a patched FS-UAE on this machine.

    Not a `Target`. It knows about packets and checksums; `AmigaTarget` owns
    the Amiga's memory map, exactly as it does for the two WinUAE routes.

    **What makes it usable while somebody is playing**: `vsync_pre()` handles
    one packet per frame once the client has said `vCont;c`, and the `m` branch
    reads memory with no state check, so a read costs the wait for the next
    frame and stops nothing. `halts_machine` is False and `AmigaTarget` picks
    that up on its own.

    **Writes are `M` packets**, `write_memory` below. The installed
    `fs-uae-gdb` accepts them, and the connection helper forwards one to 64
    bytes inside chip or slow memory. The developer harness's `poke` verb sends
    the same packet and reads the bytes back.

    **Four limits a caller has to design around**, all of them the fork's:

    * the emulator **starts halted and in warp** until a client connects and
      continues it, so `__init__` sends `vCont;c` unless told not to. A player
      cannot start the game and then decide to open Wish;
    * **one connection per run.** `handle_packet` ends
      `if(!is_connected()) { ... close(); ... }` and `close()` shuts the
      *listening* socket, not just the connection -- so `close()` here ends the
      debugging for the life of that emulator process;
    * **loopback only** -- `listen()` has `constexpr auto name =
      _T("127.0.0.1")`;
    * the server `recv`s into a 512-byte buffer and parses **one** packet out
      of it, so requests are never pipelined here: send one, read its reply.

    `opener` is what actually makes the socket, injected so the tests can drive
    every path with no emulator at all. It takes no arguments and gives back
    something with `sendall`, `recv`, `settimeout` and `close`.
    """

    #: The machine keeps running: the read is served from `vsync_pre()`, which
    #: is a frame handler of a machine that is executing. Measured -- `VHPOSR`
    #: comes back at the *same* raster position on every poll, which is what a
    #: frame handler looks like and is not what a halted debugger looks like.
    halts_machine = False

    #: One packet's round trip, for the handshake and for a read big enough to
    #: be a sweep. Generous: this is only here so a dead emulator is reported
    #: rather than waited on.
    TIMEOUT = 20.0

    #: A read a poll makes -- the party's few bytes, a pointer, the 1 KB map --
    #: is milliseconds (the median measured through `tools/amiga/fsuaegdb.py
    #: automap` is 20 ms), and the caller is a timer slot on the window's own
    #: thread, so a paused emulator must cost a poll about a second and not
    #: twenty. The value is a choice, not a measurement of the slowest frame.
    POLL_TIMEOUT = 1.0

    #: The most one `M` carries: the server `recv`s into a 512-byte buffer, and
    #: the connection helper forwards no more than this.
    MAX_WRITE = 64

    #: Whether the other end takes an `M`. The window sets it False for a helper
    #: whose greeting does not say it forwards writes.
    can_write = True

    #: Reads up to this many bytes get `POLL_TIMEOUT`; longer ones, which are
    #: `locate_machines`' half-megabyte regions, get the full `TIMEOUT`,
    #: because the server copies the range a byte at a time and how long that
    #: takes has not been measured.
    POLL_READ_LIMIT = 0x1000

    #: Opening the socket. Short, because the emulator either has the door open
    #: or has already given it away to somebody else.
    CONNECT_TIMEOUT = 10.0

    def __init__(self, host: str = "127.0.0.1", port: int | None = None,
                 timeout: float | None = None, opener=None,
                 resume: bool = True):
        self.host = host
        self.port = FSUAE_PORT if port is None else port
        self.timeout = self.TIMEOUT if timeout is None else timeout
        self._opener = opener or self._socket
        self.sock = None
        self._buf = b""
        #: True once the connection itself has failed -- the peer closed it, or
        #: a send or receive raised. **A timeout does not set it**: the socket
        #: is still the emulator's only debugging door and dropping it for a
        #: slow frame would end the run's debugging for good. `wish.fsuae`
        #: reads this to decide whether a cached transport can be reused.
        self.lost = False
        #: True after a request timed out and before the next reply is read.
        #: GDB-remote has no request ids, so the reply that was merely late
        #: would otherwise be read as the answer to the *next* request, and
        #: every read after it would lag one behind (or fail its length check)
        #: until the transport was dropped. `_write` clears the socket first.
        #: Whether the fork drops or answers a request that arrives while it is
        #: paused has not been measured; this handles both.
        self._unresolved = False
        #: What the server advertised, kept for a run log: this build answers
        #: `PacketSize=512;...;QStartNoAckMode+;vContSupported+;`.
        self.greeting = ""
        #: Every packet this session sent, the way `WinuaePipe.sent` is kept.
        self.sent: list[str] = []
        self.connect(resume=resume)

    # -- the socket ------------------------------------------------------

    def _socket(self):
        return socket.create_connection((self.host, self.port),
                                        timeout=self.CONNECT_TIMEOUT)

    def connect(self, resume: bool = True) -> None:
        """Open the socket, greet, and start the machine.

        **The `vCont;c` is not optional in the ordinary case.** The emulator
        sits at its first instruction in warp mode until a client sends one, so
        a transport that connected and did not continue would leave the player
        looking at a black screen. `resume=False` is for a caller that means to
        read a stopped machine and knows it is stopped.
        """
        try:
            self.sock = self._opener()
        except OSError as exc:
            raise FsuaeError(
                f"nothing is listening on {self.host}:{self.port}: {exc}. "
                "The patched FS-UAE opens that port once per run and closes "
                "it for good when a client disconnects, so a second "
                "connection needs the emulator started again") from exc
        self.sock.settimeout(self.timeout)
        try:
            self.greeting = self.ask("qSupported")
            if resume:
                self.resume()
        except FsuaeError:
            # The caller never gets the transport, so nothing else can close it.
            self.close()
            raise

    def close(self) -> None:
        """Drop the connection, which **ends the debugging for this run.**

        Not a tidy-up: `handle_packet` reaches `close()` on the listening
        socket when the connection goes, so the emulator carries on playing the
        game and no client can ever attach to it again.
        """
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    # -- packets ---------------------------------------------------------

    @staticmethod
    def _frame(body: str) -> bytes:
        """`$<body>#<checksum>`, the checksum being the low byte of the sum."""
        return f"${body}#{sum(body.encode()) & 0xFF:02x}".encode()

    def _write(self, body: str) -> None:
        if self.sock is None:
            raise FsuaeError("this transport is closed")
        if body[:1] in UNSAFE_PACKETS or body.startswith(UNSAFE_ACTIONS):
            raise ValueError(
                f"`{body}` stops the machine or ends the run; this transport "
                "reads a game somebody is playing")
        self.sent.append(body)
        self._discard_late_reply()
        try:
            self.sock.sendall(self._frame(body))
        except OSError as exc:
            self.lost = True
            raise FsuaeError(f"the emulator would not take `{body}`: "
                             f"{exc}") from exc

    def _discard_late_reply(self) -> None:
        """After a timeout, throw away whatever the socket holds.

        The reply to the request that timed out may have arrived since, and
        nothing in a packet says which request it answers, so it is dropped
        rather than read as the next answer. The socket is read without
        waiting; a reply that arrives after this drain is not caught.
        """
        if not self._unresolved:
            return
        self._unresolved = False
        self._buf = b""
        try:
            self.sock.settimeout(0.0)
            while True:
                chunk = self.sock.recv(1 << 16)
                if not chunk:
                    self.lost = True
                    raise FsuaeError(
                        "the emulator closed the connection; it will not "
                        "listen again until it is restarted")
        except (BlockingIOError, socket.timeout):
            return                          # nothing more is waiting
        except OSError as exc:
            self.lost = True
            raise FsuaeError(f"the connection failed: {exc}") from exc
        finally:
            if self.sock is not None:
                self.sock.settimeout(self.timeout)

    def _packet(self, timeout: float | None = None) -> str:
        """The next `$...#xx` the emulator sends, without its framing.

        Acks are stripped and none are sent back. That is what the server
        expects: `useAck` governs only the acks it *writes*, and the one place
        it reads ours is a loop at the head of `handle_packet` that discards
        `+` and `-` before looking for a `$`.

        `O`-packets -- the guest's own console output, which this server
        forwards from `KPutChar` -- are skipped rather than returned: they
        arrive unasked between a request and its reply. **`OK` is not one of
        them**, and telling the two apart is the payload rather than the
        letter: an output packet carries hex-encoded text, so an even number of
        hex digits after the `O` is console output and anything else is a
        reply that happens to start with the same letter.
        """
        if self.sock is None:
            raise FsuaeError("this transport is closed")
        limit = self.timeout if timeout is None else timeout
        self.sock.settimeout(limit)
        deadline = time.monotonic() + limit
        while True:
            while self._buf[:1] in (b"+", b"-"):
                self._buf = self._buf[1:]
            if self._buf and not self._buf.startswith(b"$"):
                # Half of a console packet left by an earlier drain: skip to
                # the next packet start rather than wait behind it for ever.
                start = self._buf.find(b"$")
                self._buf = self._buf[start:] if start != -1 else b""
            if self._buf.startswith(b"$"):
                end = self._buf.find(b"#")
                if end != -1 and len(self._buf) >= end + 3:
                    body = self._buf[1:end].decode("latin-1")
                    self._buf = self._buf[end + 3:]
                    if _console_output(body):
                        continue            # the guest printing, not our reply
                    return body
            if time.monotonic() > deadline:
                self._unresolved = True
                raise FsuaeError(
                    f"the emulator sent no reply in {limit:.0f}s; what did "
                    f"arrive was {self._buf[:80]!r}")
            try:
                chunk = self.sock.recv(1 << 16)
            except socket.timeout as exc:
                self._unresolved = True
                raise FsuaeError(f"the emulator sent no reply in "
                                 f"{limit:.0f}s") from exc
            except OSError as exc:
                self.lost = True
                raise FsuaeError(f"the connection failed: {exc}") from exc
            if not chunk:
                self.lost = True
                raise FsuaeError(
                    "the emulator closed the connection; it will not listen "
                    "again until it is restarted")
            self._buf += chunk

    def ask(self, body: str, timeout: float | None = None) -> str:
        """Send one packet and give back the reply's body."""
        self._write(body)
        return self._packet(timeout)

    def resume(self) -> None:
        """`vCont;c` -- run the machine, and **expect no reply**.

        The server answers a continue with an ack and returns; the next packet
        it sends is whenever the machine next stops, which for a game nobody
        is debugging is never. Waiting for one here would hang the poll.
        """
        self._write("vCont;c")

    def drain_idle(self) -> bool:
        """Read and throw away whatever the emulator sent unasked; False once it is gone.

        For a caller that holds the connection between requests and must notice
        the emulator closing it. Only valid with no request in flight: anything
        read here is taken to be console output, which nobody is waiting for.
        """
        if self.lost or self.sock is None:
            return False
        self._buf = b""
        try:
            self.sock.settimeout(0.0)
            while True:
                if not self.sock.recv(1 << 16):
                    self.lost = True
                    break
        except (BlockingIOError, socket.timeout):
            pass                            # nothing more is waiting
        except OSError:
            self.lost = True
        finally:
            if self.sock is not None:
                self.sock.settimeout(self.timeout)
        return not self.lost

    # -- reading memory --------------------------------------------------

    def read_memory(self, addr: int, length: int,
                    timeout: float | None = None) -> bytes:
        """Bytes, out of a running machine, in one packet.

        The optional capability `AmigaTarget.read_blocks` looks for: a
        transport that has this needs no dump file and no `S`. Named
        `read_memory` rather than `memory` on purpose -- `WinuaePipe.memory`
        exists, reads through the debugger's `m` command, and is capped at
        3 KB and at about 500 dumped lines for the life of the emulator, so a
        capability check that matched it would quietly route every Amiga poll
        through the one reader that runs out.

        There is no cap here and none is imposed: `PacketSize=512` is what the
        server advertises for GDB's benefit, and the reply is written back
        whatever its length -- 512 KB has been read in one packet. The cost of
        a big one is not this side's: the server copies the range a byte at a
        time inside the frame handler, so a 512 KB read makes the emulated
        machine miss a frame. Once per boot, for `locate()`, that is invisible;
        it is not a thing to poll with.

        `timeout` is how long to wait for the reply. Left out, a read of at
        most `POLL_READ_LIMIT` bytes waits `POLL_TIMEOUT` and a longer one
        waits `TIMEOUT`, never more than the transport's own `timeout`.
        """
        if length <= 0:
            raise ValueError(f"a read of {length} bytes is not a read")
        if timeout is None:
            timeout = (min(self.POLL_TIMEOUT, self.timeout)
                       if length <= self.POLL_READ_LIMIT else self.timeout)
        reply = self.ask(f"m{addr:x},{length:x}", timeout)
        if reply.startswith("E") and len(reply) <= 3:
            # `E01` is every failure this server has: one unreadable byte
            # anywhere in the range clears the whole reply.
            raise FsuaeError(
                f"the emulator would not read {length:#x} bytes at "
                f"{addr:#x} ({reply}); some address in that range is not "
                "memory this machine has")
        try:
            data = bytes.fromhex(reply)
        except ValueError as exc:
            raise FsuaeError(
                f"the reply to `m{addr:x},{length:x}` is not hex: "
                f"{reply[:80]!r}") from exc
        if len(data) != length:
            raise FsuaeError(f"asked for {length} bytes at {addr:#x} and the "
                             f"emulator sent {len(data)}")
        return data

    def write_memory(self, addr: int, data: bytes,
                     timeout: float | None = None, verify: bool = True) -> None:
        """Write `data` with `M` packets of at most `MAX_WRITE` bytes, each `OK`.

        Data longer than `MAX_WRITE` goes out as several packets, one at a
        time, since the server parses one packet per receive; a failure part
        way leaves the earlier pieces written. Anything but `OK` raises
        `GuestError` naming the address: `E01` for an address outside memory,
        and the empty reply an older helper gives to an `M` it does not forward.

        `verify` is accepted so a caller can treat both emulators alike, and
        changes nothing here: the emulator's `OK` is the only receipt there is.
        """
        data = bytes(data)
        if not data:
            raise ValueError("A write of 0 bytes is not a write.")
        if not any(base <= addr and addr + len(data) <= base + size
                   for base, size in MEMORY):
            raise ValueError(f"A write of {len(data)} bytes at {addr:#x} is "
                             "outside chip and slow memory.")
        for i in range(0, len(data), self.MAX_WRITE):
            piece = data[i:i + self.MAX_WRITE]
            try:
                reply = self.ask(
                    f"M{addr + i:x},{len(piece):x}:{piece.hex()}", timeout)
            except FsuaeError as exc:
                raise FsuaeError(f"{str(exc).rstrip('.')}; {i} of {len(data)} "
                                 "bytes were written before it") from exc
            if reply != "OK":
                raise GuestError(
                    f"the emulator answered {reply!r} to a write of "
                    f"{len(piece)} bytes at {addr + i:#x}; {i} of {len(data)} "
                    "bytes were written before it")


def find_anchor(memory: bytes, base: int, anchor: bytes,
                offset: int) -> list[int]:
    """Every data-hunk base this dump is consistent with.

    Returned rather than reduced to one on purpose. A string can appear twice
    -- a copy in a buffer, a second instance in another loaded thing -- and a
    locator that took the first hit would be right most of the time and wrong
    silently. The caller checks each candidate against what the game should
    hold there and blocks when more than one survives.
    """
    out, at = [], memory.find(anchor)
    while at >= 0:
        out.append(base + at - offset)
        at = memory.find(anchor, at + 1)
    return out


#: ExecBase is the long at address 4; `ex_ChkBase` (`+0x26`) holds its
#: complement, which tells a real one from garbage; `ex_MemList` (`+0x142`) is
#: the list of `MemHeader`s whose `mh_Lower` (`+0x14`) and `mh_Upper`
#: (`+0x18`) bound each region the machine has.
EXEC_BASE_AT = 4
#: ExecBase's pointer is read as the head of this much chip RAM, the size of
#: the sweep's own pieces, so a piece-by-piece reader fetches it as one of them
#: and the sweep reuses it.
EXEC_PAGE = 0x10000
EXEC_CHK_BASE = 0x26
EXEC_MEM_LIST = 0x142
MEM_LOWER = 0x14
MEM_UPPER = 0x18
MEM_NODES = 64
#: The 68000 addresses 24 bits, and nothing below the vector table is a node.
_LOW_POINTER = 0x100
_HIGH_POINTER = 0x1000000


def _pointer(value: int) -> bool:
    return value & 1 == 0 and _LOW_POINTER <= value < _HIGH_POINTER


def memory_regions(read) -> tuple[tuple[int, int], ...]:
    """The `(base, size)` regions this machine has, highest address first.

    Walks the `MemHeader` list in ExecBase, so fast RAM, extra chip RAM and a
    machine with no slow RAM are all swept where they are. Duplicate regions
    are kept once. `MEMORY` -- the A500 the project's configuration describes --
    when ExecBase fails its complement check, a node is not a plausible
    `MemHeader`, the list is longer than `MEM_NODES`, or the regions add up to
    more than the 24-bit address space (a garbage list, not a machine). That
    includes a 32-bit ExecBase and fast RAM above 16 MB, which the 24-bit
    pointer test cannot tell from garbage. A read that raises is not caught: it
    says something about the emulator and not about the machine's memory.
    """
    exec_base = int.from_bytes(
        read(0, EXEC_PAGE)[EXEC_BASE_AT:EXEC_BASE_AT + 4], "big")
    if not _pointer(exec_base):
        return MEMORY
    if _long(read, exec_base + EXEC_CHK_BASE) != ~exec_base & 0xFFFFFFFF:
        return MEMORY
    list_at = exec_base + EXEC_MEM_LIST
    node, regions = _long(read, list_at), []
    for _ in range(MEM_NODES):
        if node == list_at + 4:
            break
        if not _pointer(node):
            return MEMORY
        head = read(node, MEM_UPPER + 4)
        lower = int.from_bytes(head[MEM_LOWER:MEM_LOWER + 4], "big")
        upper = int.from_bytes(head[MEM_UPPER:], "big")
        if lower >= upper or upper > _HIGH_POINTER:
            return MEMORY
        regions.append((lower, upper - lower))
        node = int.from_bytes(head[:4], "big")
    else:
        return MEMORY
    regions = sorted(set(regions), reverse=True)
    if sum(size for _base, size in regions) > _HIGH_POINTER:
        return MEMORY
    return tuple(regions) or MEMORY


def locate_machines(read, machines, memory=MEMORY,
                    sweep_all: bool = False) -> dict[str, list[int]]:
    """Which of these titles is in memory, and at which base: `{title: bases}`.

    **One sweep for any number of titles.** Each region of `memory` is read
    once through `read(addr, length)` and searched for every machine's anchor,
    so asking after two titles costs what asking after one does -- half a
    megabyte a region is not something to fetch twice. By default the sweep
    stops at the first region where any anchor is found, because a game is in
    one region and not two, and a locate of one known title should cost one
    read. **`sweep_all=True` reads every region and collects every hit**, for
    the caller asking which title is running: stopping early would report one
    of two titles loaded in different regions (SLOW comes first) and leave it
    believing that one was alone.

    A title with no hit is absent from the result, and an empty result means
    none of them is loaded (or the one that is has not finished loading). A
    title with more than one base is returned with all of them, for the caller
    to block: see `find_anchor` on why a second copy is reported rather than
    resolved here. Because every row is tried, each anchor must be in its own
    executable and no other one, or a running title is also reported as a
    second; `tests/amiga/test_amigatarget.py` checks every pair on the
    player's disks.

    **A read that raises ends the whole sweep, and `MEMORY` puts SLOW first.**
    `FsuaeGdb.read_memory` raises on the server's `E01`, so on a machine with
    no slow memory the first read may abort before CHIP is tried, and a game
    running from chip-only would be reported as not loaded. **Unknown, and not
    changed here:** whether `barto_gdbserver.cpp`'s `m` handler answers `E01`
    for a range the machine has not mapped, or returns zeros or garbage for it.
    Reading the fork's `m` branch settles it; so does one `m c00000,10` sent to
    an FS-UAE started with no `bogomem_size` (or `slow_memory`) line in its
    configuration. If it is `E01`, the sweep has to try each region on its own
    and treat an `E01` reply as "nothing here"; if it is not, this is not a defect.
    """
    machines = list(machines)
    found: dict[str, list[int]] = {}
    for base, length in memory:
        blob = read(base, length)
        for machine in machines:
            hits = find_anchor(blob, base, machine.anchor,
                               machine.anchor_offset)
            if hits:
                found.setdefault(machine.title, []).extend(hits)
        if found and not sweep_all:
            break
    return {title: sorted(set(bases)) for title, bases in found.items()}


def _long(read, addr: int) -> int:
    return int.from_bytes(read(addr, 4), "big")


def _in_memory(addr: int, length: int = 1, memory=MEMORY) -> bool:
    return any(base <= addr and addr + length <= base + size
               for base, size in memory)


def data_base_for(read, machine: AmigaMachine, anchor_base: int,
                  memory=MEMORY) -> int:
    """The load address of the hunk the offsets are into.

    `anchor_base` unchanged, with no read, for a title without `segments`.
    Otherwise walk the BPTR links `LoadSeg` stores before each hunk from the
    anchor's hunk to the data hunk, checking at both ends that the allocation
    length stored before the hunk is the declared size plus 8. A zero link, a
    link outside memory or a disagreeing guard raises `GuestError` naming what
    was expected and found, because a wrong hop would read another hunk's bytes
    as the party.
    """
    seg = machine.segments
    if seg is None:
        return anchor_base
    _check_guard(read, anchor_base, seg.anchor_size, machine, memory)
    base = anchor_base
    for _ in range(seg.data_hunk - seg.anchor_hunk):
        link = _long(read, base - 4)
        if link == 0 or not _in_memory(4 * link + 4, 1, memory):
            raise GuestError(
                f"the link before {base:#x} holds {link:#x}, which is not "
                f"the next hunk of {machine.title}")
        base = 4 * link + 4
    _check_guard(read, base, seg.data_size, machine, memory)
    return base


def _check_guard(read, base: int, size: int, machine: AmigaMachine,
                 memory=MEMORY) -> None:
    if not _in_memory(base - 8, 8, memory):
        raise GuestError(
            f"the allocation length before {base:#x} is outside the Amiga's "
            f"memory, so it is not a hunk of {machine.title}")
    found = _long(read, base - 8)
    if found != size + 8:
        raise GuestError(
            f"the allocation length before {base:#x} is {found:#x}, expected "
            f"{size + 8:#x} for {machine.title}")


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

    **The same six lines are in `tools/amiga/amigaenum.py`, deliberately.** Nothing
    under `automap/` may import `tools/` -- that is a shipped package reaching
    into a directory no wheel carries -- and a reader with no container parse
    could not open the Amiga's maps at all. `tools/amiga/amigatarget.py` imports
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
    block of another kind is not a map, whatever the index says.

    **An index too short for the count it declares is an error, not an empty
    library.** Slicing past the end of `bytes` gives `b""`, which reads as id
    0 naming block 0 -- the index itself -- and is then dropped for being the
    wrong size, so a truncated file used to come back as a container with no
    maps in it. That is indistinguishable from the disk that genuinely has
    none, which is the ordinary case this reader skips past, and it sends
    whoever hit it looking at disk selection rather than at a bad transfer.
    `glib_blocks` above raises on a short offset table for the same reason.
    """
    blocks = glib_blocks(data)
    if not blocks:
        return {}
    index = blocks[0]
    count = int.from_bytes(index[:2], "big")
    if len(index) < 2 + 4 * count:
        raise ValueError(
            f"the GEO.GLB index declares {count} maps, which needs "
            f"{2 + 4 * count} bytes, and the block is {len(index)}")
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
    C64 counterpart would be, and `tools/records/geoports.py` has already measured
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

    #: **The transport decides this, not the target.** The console route holds
    #: the emulation thread at the debugger's `>` prompt, so a read there stops
    #: the machine; the pipe route runs a command between two emulated
    #: instructions and stops nothing. The class attribute is the older, safer
    #: answer, and `__init__` replaces it with the transport's own.
    halts_on_read = True

    #: An optional capability, read with `getattr(target, "c64_memory", True)`
    #: the way `halts_on_read` is. The window's roster, action bar, Fast Travel
    #: row and combat reader all read Commodore 64 addresses, which on a 68000
    #: are ordinary chip RAM: the reads succeed and decode the game's own
    #: unrelated bytes. A target that says False is never handed to them.
    c64_memory = False

    #: How often `fix` re-reads the anchor (and a `segments` row's hunk guards).
    #: AmigaDOS relocates the game on every `LoadSeg`, so a player who quits
    #: and starts it again in the same emulator leaves this target reading the
    #: old addresses, with nothing else to say so. Between checks a poll reads
    #: no more than it did before.
    REVALIDATE_EVERY = 5.0

    def __init__(self, debugger, layout: AmigaMachine,
                 data_base: int | None = None,
                 anchor_base: int | None = None, clock=time.monotonic,
                 memory=MEMORY):
        self._clock = clock
        #: The `(base, size)` regions the machine has, as `memory_regions`
        #: measured them; every range check below is against these.
        self.memory = tuple(memory)
        self._checked_at = clock()
        self.debugger = debugger
        self.layout = layout
        self.data_base = data_base
        #: Where the anchor was found. For a title without `segments` this is
        #: also the data hunk.
        self.anchor_base = anchor_base
        #: The square bytes read while the world map was last up, or None.
        self._world_square: bytes | None = None
        self._open = True
        # `getattr` rather than the attribute, because a test's fake transport
        # predates it and "assume it halts" is the answer that costs nothing
        # but time.
        self.halts_on_read = getattr(debugger, "halts_machine", True)
        if anchor_base is not None:
            self.data_base = data_base_for(self.read, layout, anchor_base,
                                           self.memory)

    @property
    def can_write(self) -> bool:
        """Whether `write` can reach the machine, as `amigaactions` asks.

        The transport's own `can_write` where it has one, so a helper that
        forwards no `M` can say so; otherwise whether either route exists.
        """
        own = getattr(self.debugger, "can_write", None)
        if own is not None:
            return bool(own)
        return (getattr(self.debugger, "write_memory", None) is not None
                or getattr(self.debugger, "batch", None) is not None)

    # -- Target ----------------------------------------------------------

    def read(self, addr: int, length: int) -> bytes:
        """One block, through `S` and back as base64."""
        return self.read_blocks([(addr, length)])[0]

    def write(self, addr: int, data: bytes, verify: bool = True) -> None:
        """Write `data` into the running machine, by the transport's own route.

        A transport with a `write_memory` (`FsuaeGdb` with an `M` packet,
        `WinuaeLocalPipe` with `W` lines) is used first. One to 64 bytes per
        call on WinUAE; `FsuaeGdb` splits longer data. Otherwise the console
        route sends `W <addr> <bytes>` in hex, in lines of sixteen so a long
        write does not become a console line nothing can type.

        **`verify=False` is for a write the game consumes within a frame**, such
        as the key buffer or the message link: WinUAE's read-back would find
        the bytes already changed. The caller proves that write another way, by
        the effect it was meant to have. The default checks WinUAE's memory
        after the write; FS-UAE has no read-back, only the emulator's `OK`.
        """
        self._require_open()
        direct = getattr(self.debugger, "write_memory", None)
        if direct is not None:
            direct(addr, data, verify=verify)
            return
        if getattr(self.debugger, "batch", None) is None:
            raise GuestError(
                f"{type(self.debugger).__name__} has no way to write memory")
        lines = []
        for i in range(0, len(data), 16):
            chunk = data[i:i + 16]
            lines.append(f"W {addr + i:x} "
                         + " ".join(f"{b:02x}" for b in chunk))
        self._resume(lines)
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
        C64 side's callers pass that form. **The name is ignored**, which is
        the documented behaviour for a backend that cannot tell two memories
        apart, and here it is not a limitation: there is only one memory.

        **A transport that answers memory in its reply skips all of that.**
        GDB-remote has no dump-to-file command and needs none -- the bytes come
        back in the `m` packet -- so a transport carrying a `read_memory` is
        asked for each block directly and no file is ever named. It is one
        packet per block rather than one round trip for the batch, which is the
        honest design: batching bought the WinUAE routes a keypress, a scheduled
        task and a console batch typed at 700 ms a line, and here it would buy
        one frame's wait. `FsuaeGdb.read_memory` says why the capability is not
        simply "has a `memory` method".
        """
        self._require_open()
        want = [(b[0], b[1]) for b in blocks]
        for addr, length in want:
            if length <= 0:
                raise ValueError(f"a read of {length} bytes is not a read")
        direct = getattr(self.debugger, "read_memory", None)
        if direct is not None:
            return [direct(addr, length) for addr, length in want]
        token = uuid.uuid4().hex[:8]
        lines, fetch = [], []
        for i, (addr, length) in enumerate(want):
            path = f"{GUEST_DUMP}\\wish-{token}-{i}.bin"
            lines.append(f"S {path} {addr:x} {length:x}")
            fetch.append((f"b{i}", path))
        self._resume(lines)
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

    def _resume(self, lines: list[str]) -> None:
        """Add the `g` that starts the machine again, where there was a halt.

        The console route enters the debugger over the pipe, which stops the
        emulation thread, so every batch has to end by resuming it -- a batch
        that forgets leaves the emulator halted, which is the whole of
        `#95 (A WinUAE debugger batch can stop half-way through and leave the
        emulator halted)`. The pipe route never stopped anything, and `g` is
        one of the commands that can reach `activate_debugger()` and put a
        console in front of the player, so it must not be sent there.
        """
        if getattr(self.debugger, "halts_machine", True):
            lines.append("g")

    def close(self) -> None:
        """Block further reads. **The transport is left alone.**

        Nothing to close on either WinUAE route -- each call is its own `ssh`
        -- and on `FsuaeGdb` closing would be worse than a leak: the emulator
        shuts its *listening* socket when a client goes, so a target that
        closed the connection would take the game's only debugging door with
        it, and a caller that closed one target and opened another would find
        nothing listening. Whoever opened the transport closes it.
        """
        self._open = False

    def _require_open(self) -> None:
        if not self._open:
            raise GuestError("this target was closed")

    # -- finding the base ------------------------------------------------

    def locate(self, memory=None) -> int:
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
        `memory` is the regions to sweep, and replaces the ones the target
        holds for its range checks; by default it sweeps the ones it holds.
        """
        self._require_open()
        self._checked_at = self._clock()
        if memory is not None:
            self.memory = tuple(memory)
        bases = locate_machines(self.read, [self.layout], self.memory).get(
            self.layout.title, [])
        if not bases:
            raise GuestError(
                f"{self.layout.anchor!r} is nowhere in the Amiga's memory, so "
                f"{self.layout.title} is not the title that is running (or it "
                "has not finished loading)")
        if len(bases) > 1:
            raise GuestError(
                f"{self.layout.anchor!r} appears at more than one place: "
                + ", ".join(f"{b:#x}" for b in bases)
                + " -- pick the base with a second known constant rather than "
                  "taking the first")
        self.anchor_base = bases[0]
        self.data_base = data_base_for(self.read, self.layout,
                                       self.anchor_base, self.memory)
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
        addresses in a `goldbox.c64_save.C64Container` mean nothing on a 68000. What
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
        `Automapper._blocked_step` is the one caller, and it requires *both* fixes
        to come from the status line, which no fix from this backend ever
        does. `#37 (Automap the Amiga version, not just the C64)` has the
        measurement.

        **A title with an `overland_pointer` costs two more reads a poll**
        (the pointer, then the flag), about a frame each over `FsuaeGdb`. While
        the flag is set the party is on the overland, where the square bytes
        keep the last indoor square, so the answer is a world-map fix.
        """
        self._revalidate()
        if self._on_overland():
            return Fix(0, 0, None, "memory", None, world_map=True)
        world = self._world_map_fix()
        if world is not None:
            return world
        grid = self.layout.travel_grid
        if grid is not None:
            # The four fixed-offset reads in one round trip; only the block
            # read waits for the pointer. Costs the indoor poll three reads it
            # does not use, and saves the outdoor one three round trips.
            view, pointer, area, facing = self.read_blocks([
                (self._at(grid.view), 1), (self._at(grid.block_pointer), 4),
                (self._at(grid.area), 1),
                (self._at(self.layout.party_facing), 1)])
            if view[0] in grid.views:
                return self._travel_fix(grid, view[0], int.from_bytes(
                    pointer, "big"), area[0], facing[0])
        span = self.layout.width
        lo = min(self.layout.party_x, self.layout.party_y,
                 self.layout.party_facing)
        hi = max(self.layout.party_x + span, self.layout.party_y + span,
                 self.layout.party_facing + 1)
        blob = self.read(self._at(lo), hi - lo)

        def at(offset: int, size: int) -> int:
            start = offset - lo
            return int.from_bytes(blob[start:start + size], "big")

        # The facing is a byte on every title, and the byte after it is the
        # wall type ahead, so a word-wide read would fold that in.
        x, y, doubled = (at(self.layout.party_x, span),
                         at(self.layout.party_y, span),
                         at(self.layout.party_facing, 1))
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

    def _revalidate(self) -> None:
        """Raise `GuestError` once the title is no longer where it was measured.

        Only a target whose anchor base was measured is checked, and only every
        `REVALIDATE_EVERY` seconds: one batch reading the anchor and, for a
        `segments` row, the two allocation lengths and the link between the
        hunks. The error is a `NotConnected`, so the session detaches and
        reconnects through the locator, which sweeps again.
        """
        if self.anchor_base is None:
            return
        now = self._clock()
        if now - self._checked_at < self.REVALIDATE_EVERY:
            return
        self._checked_at = now
        layout, base = self.layout, self.anchor_base
        blocks = [(base + layout.anchor_offset, len(layout.anchor))]
        seg = layout.segments
        if seg is not None:
            blocks += [(base - 8, 8), (self.data_base - 8, 4)]
        got = self.read_blocks(blocks)
        moved = got[0] != layout.anchor
        if seg is not None and not moved:
            moved = (int.from_bytes(got[1][:4], "big") != seg.anchor_size + 8
                     or int.from_bytes(got[2], "big") != seg.data_size + 8
                     or 4 * int.from_bytes(got[1][4:], "big") + 4
                     != self.data_base)
        if moved:
            raise GuestError(f"{layout.title} is no longer at {base:#x}; it "
                             "was started again, or another title was")

    def _travel_fix(self, grid: TravelGrid, view: int, pointer: int,
                    area: int, facing: int) -> Fix | None:
        """The fix on the travel grid, or None while the engine's bytes
        disagree.

        None while the indoors word is set (the stale indoor square would be
        recorded on whatever map is loaded) and while the area byte is not the
        one the view byte implies (the interval between the script's area
        change and the area-entry routine). The block's own area word is never
        read: it lags a crossing.
        """
        window = grid.views.index(view)
        span = grid.indoors + 2 - grid.x
        if pointer == 0 or not _in_memory(pointer + grid.x, span,
                                                self.memory):
            return None
        blob = self.read(pointer + grid.x, span)
        if int.from_bytes(blob[grid.indoors - grid.x:], "big") != 0:
            return None
        if area not in grid.areas or grid.areas.index(area) != window:
            return None
        x = int.from_bytes(blob[:2], "big")
        y = int.from_bytes(blob[grid.y - grid.x:grid.y - grid.x + 2], "big")
        if not (0 <= x < WINDOW_W and 0 <= y < WINDOW_H):
            return None
        return Fix(x, y, None, "memory", None, outdoors=True, window=window,
                   heading=facing if facing < 8 else None)

    def _world_map_fix(self) -> Fix | None:
        """A world-map fix while the party is on the title's world map.

        The script byte is 0 at the party menu after a load, so the area id
        stands in for it there. On leaving, the script byte changes seconds
        before the arriving script puts the party on its square, and the
        square bytes still hold the last one before the map; so the map lasts
        while the area id still names it and the square is the one it had on
        the map. A script that lands the party on that same square keeps the
        map up until its entry returns and the area id changes.
        """
        world = self.layout.world_map
        if world is None:
            return None
        square = self.layout.party_facing + 1 - self.layout.party_x
        script, pointer, here = self.read_blocks([
            (self._at(world.script), 1), (self._at(world.variables), 4),
            (self._at(self.layout.party_x), square)])
        base = int.from_bytes(pointer, "big")
        span = 2 * (world.leg - world.node) + 2
        if (base == 0 or not _in_memory(base + 2 * world.area, 2, self.memory)
                or not _in_memory(base + 2 * world.node, span, self.memory)):
            self._world_square = None
            return None
        area, places = self.read_blocks([(base + 2 * world.area, 2),
                                         (base + 2 * world.node, span)])
        area_id = int.from_bytes(area, "big")
        current = script[0] or area_id
        if current in world.areas:
            self._world_square = here
        elif area_id not in world.areas or here != self._world_square:
            self._world_square = None
            return None
        return Fix(0, 0, None, "memory", None, world_map=True,
                   world_node=int.from_bytes(places[:2], "big"),
                   world_leg=int.from_bytes(places[-2:], "big"))

    def _on_overland(self) -> bool:
        """True when the title's overland flag is 1; a bad pointer is False."""
        if self.layout.overland_pointer is None:
            return False
        addr = int.from_bytes(
            self.read(self._at(self.layout.overland_pointer), 4), "big")
        flag_at = addr + self.layout.overland_flag
        if addr == 0 or not any(base <= flag_at < base + length
                                for base, length in self.memory):
            return False
        return self.read(flag_at, 1)[0] == 1

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
        # vector table, which is never a map. So it is blocked by name rather
        # than by the range test below.
        if addr == 0 or not any(base <= addr and addr + 0x400 <= base + length
                                for base, length in self.memory):
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
