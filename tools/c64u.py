#!/usr/bin/env python3
"""Drive a C64 Ultimate from this project's side: mount, read, dump, time.

The Ultimate is an FPGA recreation rather than an emulator, so a reading taken
off it is genuinely independent of VICE -- which is the point.  Everything this
project believes about the C64 (the automapper's addresses, the record
offsets, the trainer tables, the ECL decoding) came out of one emulator's
account of the machine, and this wrapper exists so that account can be checked
against hardware.  `docs/161-c64-ultimate.md` is the write-up.

It shells out to the `c64u` CLI (v0.9.4 here) over the device's REST API.  Four
things it does that a bare CLI call does not, each of them a rule from
`docs/161-c64-ultimate.md` made mechanical:

1. **Refuses the commands that are not ours to run.**  `config save-to-flash`
   persists a setting past power-off, `config load-from-flash` replaces the
   live settings wholesale, `config reset-to-default` cannot be undone from
   the CLI, `machine poweroff` turns off a machine on somebody's desk, and
   `streams`/`ui` open a window on it.  `Refused` is raised before anything
   reaches the wire.
2. **`paused()` always resumes.**  A 64K dump is many HTTP round-trips, so it
   has to be taken with the machine paused or it is a smear across time; a
   failure mid-dump must not leave a paused machine on the desk.
3. **Every dump carries a sidecar saying which bank state it was taken in.**
   DMA follows the CPU's *current* banking, so the same address reads ROM or
   the RAM underneath depending on what the running program last wrote to
   `$01` -- and `$01` itself reads as the RAM under the processor port, so the
   dump cannot say.  A dump with no recorded bank state is a dump nobody can
   interpret later.
4. **Reads the disks the way every other tool here does** -- `$POR_DISKS`,
   then `automap.paths.find_disks()`, never a path in the source.  The image
   is staged into `work/c64u/` and uploaded from there, so the player's own
   directory is never opened for writing, exactly as `tools/session.py` stages
   `SIDE1.D64` for VICE.

Nothing read off the machine is ever committed: dumps land under `work/`,
which is gitignored, and stay there.

    tools/c64u.py info                     device identity
    tools/c64u.py disks                    which images we would mount
    tools/c64u.py boot                     stage disk 1, mount it, reset
    tools/c64u.py read 4900 --length 32    hex dump of one range
    tools/c64u.py dump --start 0 --to ffff --banking default
    tools/c64u.py poll -o work/c64u/run1   the automapper's own read, once
    tools/c64u.py time-reads --count 100   how many polls a second this gives
    tools/c64u.py probe-key SPACE          does the game read the KERNAL buffer

With no device answering, every subcommand exits 3 and says so, so a script
can tell "no hardware" from "hardware disagreed".
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import pathlib
import shutil
import statistics
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from automap.live import memory_blocks  # noqa: E402
from automap.paths import disk_globs, find_disks  # noqa: E402
from goldbox import games  # noqa: E402

#: Exit code for "no C64 Ultimate answered", distinct from a failed check.
NO_DEVICE = 3

#: The KERNAL keyboard buffer and its count.  `sendkey` writes PETSCII into
#: the first and the length into the second; a program reading through the
#: KERNAL drains them, and one polling the matrix at `$DC00`/`$DC01` does not.
KEY_BUFFER = 0x0277
KEY_COUNT = 0x00C6

#: Commands this wrapper will not issue, and why.  Checked against the leading
#: words of the argument list before anything is sent.
REFUSED = {
    ("config", "save-to-flash"):
        "persists a device setting past power-off",
    ("config", "reset-to-default"):
        "cannot be undone from the CLI",
    ("config", "load-from-flash"):
        "replaces the live settings wholesale",
    ("machine", "poweroff"):
        "turns off a machine on somebody's desk",
    ("streams",):
        "needs wired Ethernet, and `listen video` opens a window",
    ("ui",):
        "a full-screen TUI, and a window on the desktop",
}


class UltimateError(RuntimeError):
    """The CLI ran and said no."""


class NotReachable(UltimateError):
    """No device answered, or the CLI is not installed."""


class Refused(UltimateError):
    """A command on the `REFUSED` list, stopped before it reached the wire."""


def find_cli() -> str | None:
    """The `c64u` binary: `$C64U_CLI`, then `$PATH`, then where it installs."""
    explicit = os.environ.get("C64U_CLI")
    if explicit:
        return explicit if os.path.exists(explicit) else None
    found = shutil.which("c64u")
    if found:
        return found
    fallback = pathlib.Path.home() / ".local/bin/c64u"
    return str(fallback) if fallback.exists() else None


def mask_vic_colour(value: int) -> int:
    """A VIC colour register, with the unused upper bits taken off.

    `$D020` reads back as `FE` rather than `0E`: the VIC colour registers and
    colour RAM are four bits wide and the top four float high.  Comparing a
    hardware read against a VICE read without this is a difference that is
    entirely ours.
    """
    return value & 0x0F


#: How long a CLI call may run before this wrapper gives up on it, in
#: seconds.  Generous, because a paused 64K dump is a single CLI invocation
#: doing many round trips over WiFi -- but finite, because "no timeout" is
#: what turned a slow or flaky device into a `pytest` collection that could
#: not be interrupted.  `$C64U_TIMEOUT` overrides it.
DEFAULT_TIMEOUT_S = 120.0


def _subprocess_timeout() -> float:
    raw = os.environ.get("C64U_TIMEOUT")
    if not raw:
        return DEFAULT_TIMEOUT_S
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_S


def _run_subprocess(argv: list[str], binary: bool) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=not binary,
                          timeout=_subprocess_timeout())


class Ultimate:
    """One C64 Ultimate, driven through the `c64u` CLI.

    `runner` is the seam the tests use: it takes `(argv, binary)` and returns
    something with `returncode`, `stdout` and `stderr`, so every argument this
    class builds can be checked without a device on the network.
    """

    def __init__(self, host: str | None = None, cli: str | None = None,
                 runner=None) -> None:
        self.cli = cli if cli is not None else find_cli()
        self.host = host or os.environ.get("C64U_HOST")
        self._runner = runner or _run_subprocess

    # -- the wire ----------------------------------------------------------

    def argv(self, *args: str) -> list[str]:
        if not self.cli:
            raise NotReachable("no c64u CLI found: set $C64U_CLI, or install it")
        head = [self.cli]
        if self.host:
            head += ["--host", self.host]
        return head + list(args)

    def _check_allowed(self, args: tuple[str, ...]) -> None:
        for banned, why in REFUSED.items():
            if args[:len(banned)] == banned:
                raise Refused(f"`c64u {' '.join(banned)}` is not ours to run: {why}")

    def run(self, *args: str, binary: bool = False) -> bytes | str:
        """One CLI call.  Raises on a non-zero exit; returns stdout."""
        self._check_allowed(args)
        done = self._runner(self.argv(*args), binary)
        if done.returncode != 0:
            err = done.stderr
            if isinstance(err, bytes):
                err = err.decode("utf-8", "replace")
            raise UltimateError(f"c64u {' '.join(args)}: {(err or '').strip()}")
        return done.stdout

    def json(self, *args: str):
        return json.loads(self.run(*args, "--json"))

    # -- identity ----------------------------------------------------------

    def info(self) -> dict:
        return self.json("info")

    def available(self) -> bool:
        """Does a device answer?  False rather than an exception, so a caller
        can skip instead of failing -- CI has no C64 Ultimate."""
        try:
            self.info()
        except (UltimateError, OSError, ValueError, subprocess.TimeoutExpired):
            return False
        return True

    # -- memory ------------------------------------------------------------

    @staticmethod
    def addr(value: int | str) -> str:
        return value if isinstance(value, str) else f"{value:04x}"

    def read_mem(self, address: int | str, length: int) -> bytes:
        """`length` bytes from `address`, as bytes.

        This is a DMA cycle, so it reaches live I/O -- `$D012` moves between
        two calls -- and it follows whatever banking the CPU is in.
        """
        out = self.run("machine", "read-mem", self.addr(address),
                       "--length", str(length), "--raw", binary=True)
        if len(out) != length:
            raise UltimateError(
                f"read-mem {self.addr(address)} asked for {length} bytes, "
                f"got {len(out)}")
        return out

    def write_mem(self, address: int | str, data: bytes) -> None:
        """Write bytes over DMA.

        Two traps, both from `docs/161-c64-ultimate.md`: the hex is **one**
        argument (spaces split it into several and the CLI refuses), and 128
        bytes is the per-call limit.  And a write only persists where nothing
        else drives the address -- `$D020` and `$0400` stick, `$DC00` is gone
        within a frame because the KERNAL keyboard scan rewrites it.
        """
        if not data:
            raise ValueError("nothing to write")
        if len(data) > 128:
            raise ValueError(
                f"{len(data)} bytes: write-mem takes at most 128 per call, "
                "use write-mem-file for more")
        self.run("machine", "write-mem", self.addr(address), data.hex())

    @contextlib.contextmanager
    def paused(self):
        """Hold the machine still for the length of a dump, and always resume.

        `pause` pulls the DMA line low, so a multi-round-trip read is coherent
        rather than a smear across time.  The `finally` is the whole point:
        a failure mid-dump must not leave a paused machine on the desk.
        """
        self.run("machine", "pause")
        try:
            yield self
        finally:
            self.run("machine", "resume")

    def dump(self, start: int, end: int, path: str | os.PathLike,
             banking: str = "unknown", note: str = "") -> pathlib.Path:
        """A paused dump of `start`..`end` inclusive, with its sidecar.

        `banking` is the caller's statement of what `$01` held while the dump
        was taken, and it cannot be measured: `$00`/`$01` read as the RAM under
        the 6510 processor port, so DMA never sees the port itself.  A dump
        with no recorded bank state cannot be interpreted afterwards, which is
        why it is a parameter rather than a guess.
        """
        path = pathlib.Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        wanted = end - start + 1
        with self.paused():
            self.run("machine", "read-mem", self.addr(start),
                     "--to", self.addr(end), "-o", str(path))
        got = path.stat().st_size
        if got != wanted:
            raise UltimateError(
                f"dump {self.addr(start)}..{self.addr(end)} asked for "
                f"{wanted} bytes, got {got} in {path} -- no sidecar written, "
                "the file cannot be trusted")
        self.write_sidecar(path, start=start, end=end, length=wanted,
                           banking=banking, note=note)
        return path

    def write_sidecar(self, path: str | os.PathLike, **fields) -> pathlib.Path:
        """The JSON beside a dump: what it is, and which state it was taken in.

        `info()` only enriches the record with device identity, and a broken
        CLI binary raises a bare `OSError` from `subprocess.run()` rather than
        `UltimateError` -- the same set `available()` catches, below.  The
        core fields are built first so a failure enriching the record cannot
        cost the sidecar its bank state, which is the only thing that matters.
        """
        path = pathlib.Path(path)
        body = {
            "tool": "tools/c64u.py",
            "taken": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "banking_note": (
                "DMA follows the CPU's current banking and $01 reads as the "
                "RAM underneath, so this bank state is recorded rather than "
                "measured."),
            **fields,
        }
        try:
            body["device"] = self.info()
        except (UltimateError, OSError, ValueError, subprocess.TimeoutExpired):
            body["device"] = {}
        side = path.with_suffix(path.suffix + ".json")
        side.write_text(json.dumps(body, indent=2) + "\n")
        return side

    # -- the automapper's own read ----------------------------------------

    def poll(self, game: games.Game | None = None) -> list[bytes]:
        """Read exactly what one `automap` poll reads, in the same ranges.

        For Pool of Radiance that is two blocks: the `$4900` payload and the
        `$8300` roster page.  Taking them here rather than by hand is what
        makes a hardware reading comparable with a VICE one byte for byte.
        """
        return [self.read_mem(addr, length)
                for addr, length in memory_blocks(game)]

    def time_reads(self, count: int = 100, game: games.Game | None = None,
                   length: int | None = None) -> dict:
        """How long a poll takes, `count` times over.

        With no `length` it times the automapper's real poll -- every block,
        one round trip each -- because that is the number that decides whether
        the Ultimate can back a live tab or only a stop-and-dump measurement.
        """
        blocks = ([(memory_blocks(game)[0][0], length)] if length
                  else list(memory_blocks(game)))
        times = []
        for _ in range(count):
            began = time.perf_counter()
            for addr, size in blocks:
                self.read_mem(addr, size)
            times.append(time.perf_counter() - began)
        total = sum(times)
        return {
            "polls": count,
            "blocks_per_poll": len(blocks),
            "bytes_per_poll": sum(size for _, size in blocks),
            "seconds_total": round(total, 3),
            "ms_mean": round(1000 * statistics.fmean(times), 1),
            "ms_median": round(1000 * statistics.median(times), 1),
            "ms_min": round(1000 * min(times), 1),
            "ms_max": round(1000 * max(times), 1),
            "polls_per_second": round(count / total, 2) if total else None,
        }

    # -- keyboard ----------------------------------------------------------

    def sendkey(self, keys: str, delay: int | None = None) -> None:
        """PETSCII into the KERNAL buffer at `$0277`, count at `$00C6`.

        This drives BASIC and the KERNAL.  A program polling the keyboard
        matrix through CIA 1 never sees it, so whether it drives the game is a
        question for `probe_key` rather than an assumption.
        """
        args = ["machine", "sendkey", keys]
        if delay is not None:
            args += ["--delay", str(delay)]
        self.run(*args)

    def probe_key(self, keys: str, settle: float = 0.5) -> dict:
        """Send a key and report whether anything drained the KERNAL buffer.

        The experiment for "can this program be driven at all".  `$00C6` is the
        buffer count and is plain RAM, so DMA reads it whatever the banking.
        Send a key, wait, read the count back:

        * back to `0` -- something called the KERNAL's `GETIN`, so the program
          reads through the buffer and `sendkey` can drive it;
        * still non-zero -- nothing is reading the buffer, so the program polls
          the matrix and `sendkey` cannot drive it.

        One caveat, and it is why this returns the raw counts rather than a
        verdict alone: a program that has banked the KERNAL out may be using
        `$00C6` for its own purposes, in which case the number means something
        else entirely.  Corroborate a "drained" reading with an effect on
        screen before believing it.
        """
        before = self.read_mem(KEY_COUNT, 1)[0]
        self.sendkey(keys)
        after_write = self.read_mem(KEY_COUNT, 1)[0]
        time.sleep(settle)
        after_settle = self.read_mem(KEY_COUNT, 1)[0]
        drained = after_write > 0 and after_settle == 0
        return {
            "keys": keys,
            "count_before": before,
            "count_after_sendkey": after_write,
            "count_after_settle": after_settle,
            "drained": drained,
            "reading": ("the KERNAL buffer is being read, so sendkey can drive this"
                        if drained else
                        "nothing drained the buffer: this stage most likely polls "
                        "the keyboard matrix, and sendkey cannot drive it"),
        }

    # -- disks -------------------------------------------------------------

    def mount(self, image: str | os.PathLike, drive: str = "a",
              mode: str = "readonly") -> None:
        """Upload a local image and mount it.

        `readonly` by default: a mounted image the game can write to is a
        second copy of the player's disk drifting from the original, and
        nothing here needs one.  Pass `readwrite` deliberately when a run has
        to save.
        """
        self.run("drives", "mount-upload", drive, str(image), "--mode", mode)

    def unmount(self, drive: str = "a") -> None:
        self.run("drives", "unmount", drive)

    def reset(self) -> None:
        self.run("machine", "reset")


# -- where the disks are ----------------------------------------------------


def disk_dir(game: games.Game | None = None) -> str:
    """`$POR_DISKS`, then wherever the title's disks actually are."""
    env = os.environ.get("POR_DISKS")
    return env if env else str(find_disks(game) or "")


def game_disks(game: games.Game | None = None, root: str | None = None) -> list[str]:
    """Every disk image of one title, each of them once.

    `disk_globs` gives an upper- and a lower-cased pattern, and on a
    case-insensitive filesystem both match the same file -- so dedupe, or the
    same image is offered twice.
    """
    root = root if root is not None else disk_dir(game)
    seen: dict[str, str] = {}
    if root:
        for pattern in disk_globs(game):
            for path in pathlib.Path(root).glob(pattern):
                seen.setdefault(os.path.normcase(str(path.resolve())), str(path))
    return sorted(seen.values())


def boot_disk(game: games.Game | None = None, number: int = 1,
              root: str | None = None) -> str:
    """Disk `number` of the title, the one VICE boots from.

    `game_disks()` already lists every image of a title correctly, sorted --
    disk numbering follows that order rather than a filename guessed from
    `disk_glob`.  A prefix guess broke on Champions of Krynn and Death Knights
    of Krynn, whose globs are `*[cC]hampions*.[dD]64` and
    `*[dD]eath*[kK]nights*.[dD]64`: both start with a wildcard, so the guessed
    prefix was empty and the search always missed.

    `tools/session.py` stages `POOL1.D64` as `SIDE1.D64` and boots that; sorted
    order puts `POOL1.D64` first among Pool of Radiance's disks, so this picks
    the same image.
    """
    game = game or games.DEFAULT
    disks = game_disks(game, root)
    if 1 <= number <= len(disks):
        return disks[number - 1]
    raise FileNotFoundError(
        f"no disk {number} of {game.title} under "
        f"{root if root is not None else disk_dir(game)!r} -- set $POR_DISKS "
        "to the directory holding the game disks")


def work_dir() -> pathlib.Path:
    """Where staged images and dumps go: gitignored, and never the player's."""
    return pathlib.Path(__file__).resolve().parent.parent / "work" / "c64u"


def stage(image: str | os.PathLike, into: str | os.PathLike | None = None) -> str:
    """Copy an image into `work/` and give back the copy's path.

    The player's disk directory is read-only to everything in this repository.
    `mount-upload` only reads the local file, but a run that later wants a
    writable mount must have a copy to write to, and staging every time is one
    rule rather than two.
    """
    into = pathlib.Path(into) if into is not None else work_dir()
    into.mkdir(parents=True, exist_ok=True)
    dest = into / pathlib.Path(image).name
    shutil.copy(image, dest)
    return str(dest)


# -- command line -----------------------------------------------------------


def _device(args) -> Ultimate:
    return Ultimate(host=getattr(args, "host", None))


def _require(dev: Ultimate) -> None:
    if not dev.available():
        raise NotReachable(
            "no C64 Ultimate answered -- check it is powered on, on the "
            "network, and that Web Remote Control is enabled in its menu")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", help="device address (default $C64U_HOST or the "
                                   "c64u config file)")
    ap.add_argument("--game", default=None,
                    help="title key, default Pool of Radiance")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="device identity")
    sub.add_parser("disks", help="which images we would mount")

    p = sub.add_parser("mount", help="stage a disk under work/ and mount it")
    p.add_argument("--disk", type=int, default=1)
    p.add_argument("--drive", default="a")
    p.add_argument("--mode", default="readonly",
                   choices=["readonly", "readwrite", "unlinked"])

    p = sub.add_parser("boot", help="mount disk N and reset the machine")
    p.add_argument("--disk", type=int, default=1)

    p = sub.add_parser("read", help="hex dump one range")
    p.add_argument("address")
    p.add_argument("--length", type=int, default=16)

    p = sub.add_parser("dump", help="a paused dump, with its bank state recorded")
    p.add_argument("--start", default="0000")
    p.add_argument("--to", default="ffff")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--banking", default="unknown",
                   help="what $01 held, e.g. 'default 37' or 'ROMs out 53' -- "
                        "it cannot be measured over DMA, so it is stated")
    p.add_argument("--note", default="")

    p = sub.add_parser("poll", help="the automapper's own read, once")
    p.add_argument("-o", "--out", required=True, help="directory for the blocks")
    p.add_argument("--banking", default="unknown")

    p = sub.add_parser("time-reads", help="how many automapper polls a second")
    p.add_argument("--count", type=int, default=100)
    p.add_argument("--length", type=int, default=None,
                   help="time a single read of this size instead of a poll")

    p = sub.add_parser("probe-key", help="does this stage read the KERNAL buffer")
    p.add_argument("keys")
    p.add_argument("--settle", type=float, default=0.5)

    args = ap.parse_args(argv)
    game = games.by_key(args.game) if args.game else None
    dev = _device(args)

    try:
        if args.cmd == "disks":
            print(f"directory  {disk_dir(game) or '(none found)'}")
            for path in game_disks(game):
                print(f"           {path}")
            return 0

        _require(dev)

        if args.cmd == "info":
            print(json.dumps(dev.info(), indent=2))
        elif args.cmd in ("mount", "boot"):
            local = stage(boot_disk(game, getattr(args, "disk", 1)))
            dev.mount(local, drive=getattr(args, "drive", "a"),
                      mode=getattr(args, "mode", "readonly"))
            print(f"mounted {local}")
            if args.cmd == "boot":
                dev.reset()
                print("reset -- the game boots from drive 8")
        elif args.cmd == "read":
            data = dev.read_mem(args.address, args.length)
            base = int(str(args.address).lstrip("$").replace("0x", ""), 16)
            for off in range(0, len(data), 16):
                row = data[off:off + 16]
                print(f"${base + off:04X}  {row.hex(' ')}")
        elif args.cmd == "dump":
            path = dev.dump(int(args.start, 16), int(args.to, 16), args.out,
                            banking=args.banking, note=args.note)
            print(f"{path} ({path.stat().st_size} bytes), sidecar beside it")
        elif args.cmd == "poll":
            out = pathlib.Path(args.out)
            out.mkdir(parents=True, exist_ok=True)
            for (addr, length), data in zip(memory_blocks(game), dev.poll(game)):
                name = out / f"block-{addr:04x}.bin"
                name.write_bytes(data)
                dev.write_sidecar(name, start=addr, end=addr + length - 1,
                                  length=length, banking=args.banking,
                                  note="one automap poll block, read over DMA")
                print(f"${addr:04X}  {length} bytes  {name}")
        elif args.cmd == "time-reads":
            print(json.dumps(dev.time_reads(args.count, game, args.length),
                             indent=2))
        elif args.cmd == "probe-key":
            print(json.dumps(dev.probe_key(args.keys, args.settle), indent=2))
    except NotReachable as exc:
        print(f"c64u: {exc}", file=sys.stderr)
        return NO_DEVICE
    except (UltimateError, FileNotFoundError) as exc:
        print(f"c64u: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
