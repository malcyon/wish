"""A live Amiga, read through WinUAE's own debugger.

`ViceTarget` talks to a socket. WinUAE has no socket, but it has two doors on
the same debugger and they are not the same to whoever is at the machine.

**`WinuaePipe` is the one to reach for.** Every WinUAE process creates
`\\\\.\\pipe\\WinUAE` at startup, and a message beginning `DBG ` is handed to
`debug_parser`, which points the debugger's console output at a buffer and hands
the buffer back as the reply. So a read costs one frame, opens no window, takes
no focus and does not stop the emulated machine -- measured on 2026-09-08 at a
median of 2.3 ms a command with the emulator holding 49.9 FPS throughout, on
`#37 (Automap the Amiga version, not just the C64)`.

**`WinuaeDebugger` is the older route and the one every driven tool uses.** It
presses F11 -- the `SPC_ENTERDEBUGGER` input event, which is the only way into
the *interactive* debugger, since `use_debugger=true` cannot start it on Windows
at all -- and types `S <file> <addr> <n>` and `g` into the emulator's console.
That halts the machine for the length of the batch and puts a console in front
of whoever is playing, so it belongs to a driven run and not to a player's
session. It stays because its `W` and its single-stepping reach parts of the
debugger the pipe deliberately refuses to send.

**One `ssh` call does the whole of either**, which is the design decision this
module is built around. `winuae.ps1` and `winuae-send.ps1` are three separate
guest commands -- write the batch file, press F11, inject the batch -- and each
run on its own would be an `ssh` round trip of about half a second. They are
composed here into a single PowerShell script, base64'd into
`powershell -EncodedCommand`, so a poll is one round trip whatever it reads.
`-EncodedCommand` also removes every quoting question between `winvm ssh`,
whatever shell the guest hands it to, and PowerShell; a batch full of
backslashed Windows paths is not something to send through three quoting
layers by hand.

**The `ssh` is this project's test rig, not the shape of the product.** Wish and
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

    **`WinuaePipe` is the other transport and the faster one.** This one is
    what every driven tool uses and is kept working: it needs no pipe, and its
    `W` and its single-stepping reach parts of the debugger the pipe refuses to
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


#: A debugger command that can reach `activate_debugger()`, and through it
#: `open_console()` -- a console window in front of whoever is playing, which
#: is the one thing this route exists to avoid. `m`, `S`, `W` and `T` stay
#: inside `debug_parser` and are safe; the rest of the command set has not been
#: read, so the refusal is a list of the ones known to be dangerous plus
#: `IPC_QUIT`, which quits the emulator outright (`uaeipc.cpp:38`).
UNSAFE_COMMANDS = frozenset("g t f b w z q x".split())


class PipeError(GuestError):
    """The pipe would not open, or the guest could not be reached.

    Separate from a plain `GuestError` because the caller may want to fall back
    to the console route -- `WinuaeDebugger` -- when the pipe is not reachable,
    and that is a different decision from a debugger command failing.
    """


def _pieces(cmd: str) -> list[str]:
    """One line as `debug_line` splits it: on unquoted `;`.

    **The emulator runs every piece in the same message.** `debug.cpp`'s
    `debug_line` walks the string tracking quotes and hands each `;`-separated
    piece to `debug_line_2`, so `m 0 1;g` is a read *and* a go, and a guard
    reading only the first word of the whole string sees `m` and lets it
    through. That was true here until 2026-09-08.
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
    """Refuse anything that could put a console in front of the player.

    Checked here rather than in the caller because every route into this
    transport goes through one function, and a batch is composed from several
    places.

    **Tokenised the way the emulator tokenises, not the way a line looks.**
    Two things defeated an earlier version of this guard, and both are how
    `debug.cpp` actually reads a line rather than anything exotic:

    * `debug_line` splits on unquoted `;` and runs every piece, so the head of
      each piece is checked and not merely the head of the string;
    * `ignore_ws` skips anything `_istspace`, so `g\tc00000` is a go with a
      tab in it -- `split()` with no argument splits on any whitespace, which
      `split(" ")` does not.

    Case is deliberately not folded. `debug_line_2`'s `switch (cmd)` is
    case-sensitive and has no `case 'G'`; `T` and `t` are two different
    commands and both are already classified. `IPC_QUIT` is the one thing
    compared case-insensitively, because `uaeipc.cpp` uses `_tcsicmp` for it.
    """
    for cmd in commands:
        for piece in _pieces(cmd):
            words = piece.strip().split()
            if not words:
                continue
            head = words[0]
            if head.lower() == "ipc_quit":
                raise ValueError(
                    "IPC_QUIT quits the emulator; it is never sent")
            if head in UNSAFE_COMMANDS:
                raise ValueError(
                    f"`{head}` can reach activate_debugger(), which opens a "
                    "console window in front of the player; this transport "
                    "sends reading commands only")


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
                 pipe: str = "WinUAE", connection: str = "ssh"):
        self._run = runner or _run
        self.timeout = self.TIMEOUT if timeout is None else timeout
        self.pipe = pipe
        if connection not in ("ssh", "local"):
            raise ValueError(f"connection {connection!r} is neither 'ssh' nor "
                             "'local'")
        self.connection = connection
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
        encoded = ",".join(
            "'" + base64.b64encode(f"DBG {c}".encode("ascii")).decode("ascii")
            + "'" for c in commands)
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
        return f"""$ErrorActionPreference='Stop'
$sw=[Diagnostics.Stopwatch]::StartNew()
try {{
  $p=New-Object IO.Pipes.NamedPipeClientStream '.','{self.pipe}','InOut'
  $p.Connect({self.CONNECT_MS})
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

    def batch(self, lines: list[str],
              fetch: list[tuple[str, str]] | None = None
              ) -> tuple[str, dict[str, bytes | None]]:
        """`WinuaeDebugger.batch`'s shape, so `AmigaTarget` needs neither told.

        The two transports answer the same call and differ in one thing a
        caller can see: `halts_machine`. **Nothing here appends a `g`**, and a
        caller must not send one -- there is no halt to resume, and `g` is one
        of the commands that can reach `activate_debugger()`.
        """
        fetch = fetch or []
        self.sent += list(lines)
        out = self._execute(self.script(lines, fetch=fetch))
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

    #: **The transport decides this, not the target.** The console route holds
    #: the emulation thread at the debugger's `>` prompt, so a read there stops
    #: the machine; the pipe route runs a command between two emulated
    #: instructions and stops nothing. The class attribute is the older, safer
    #: answer, and `__init__` replaces it with the transport's own.
    halts_on_read = True

    def __init__(self, debugger, layout: AmigaLayout,
                 data_base: int | None = None):
        self.debugger = debugger
        self.layout = layout
        self.data_base = data_base
        self._open = True
        # `getattr` rather than the attribute, because a test's fake transport
        # predates it and "assume it halts" is the answer that costs nothing
        # but time.
        self.halts_on_read = getattr(debugger, "halts_machine", True)

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

        The console route enters the debugger by pressing F11, which stops the
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
