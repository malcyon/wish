#!/usr/bin/env python3
"""The VICE instance pool: six resources per slot, held by one lease.

`docs/123-parallel-sessions.md` is the design.  Two things in it are the whole
reason this module exists.

**Nothing here ever kills a process by name.**  `tools/session.py` and
`tools/porlaunch.sh` used to `pkill -x x64sc` on every launch and every close,
which under a pool is not a bug but a massacre: one agent starting a run killed
every other agent's emulator and Donald's own game with it.  Teardown is
`os.killpg` on the process group *this slot* started, and reclaiming somebody
else's wreckage kills the pgid recorded in *that slot's* lease file.  Nothing
else, ever.

**The lease is an `fcntl.flock`.**  The kernel drops it when the holding
process dies, however it dies, so a crashed run frees its slot with no cleanup
script, no timestamp heuristic and no stale-lock policy.  A slot whose flock is
held is somebody's however dead it looks; that is the whole discipline in one
line.

**The pool allocates 6520 upwards and never touches 6502 or 6510.**  That is
deliberate: after this, anything on 6502 is a game a human started from the
desktop menu.  It restores the property the old `ss -tnp | grep 6502` rule
depended on instead of destroying it.

The six resources, because four was the number the plan started with and it was
two short: the binary-monitor port, the *text*-monitor port, `session.py`'s
command-server port, the X display, the disk copies, and the `vicerc`.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time

try:
    import fcntl  # POSIX only
except ImportError:                 # pragma: no cover - Windows
    # The pool drives VICE on Linux and nothing else needs it, but the module
    # still has to *import* everywhere: CI runs the suite on Windows and an
    # unimportable module fails at collection time, which is how
    # `tools/dosbox.py` was caught.  Same guard, same reason.
    fcntl = None
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: #233 (The test suite takes the emulator displays agents need, and eight
#: slots is no longer enough): eight was too few for the agent count this
#: project now runs.  Sixteen keeps the port arithmetic comfortable --
#: `BIN_BASE`, `TEXT_BASE` and `CMD_BASE` land at 6520-6535, 6540-6555 and
#: 6560-6575, none of them touching the next -- where twenty leaves the
#: binary monitor's top one port below `TEXT_BASE` and twenty-four overlaps
#: it outright.
SLOTS = 16
# Bases, not offsets from 6502: the gap is the point.  See the module docstring.
BIN_BASE = 6520
TEXT_BASE = 6540
CMD_BASE = 6560
#: Unmoved by #233's re-spacing: at sixteen slots this is :10-:25, which
#: already clears `tools/dosbox.py`'s old :30 with room to spare.  Only
#: DOSBox and DOSBox-X had to move -- see their own modules.
DISPLAY_BASE = 10

# What a human's session uses, and what the pool must therefore never allocate.
RESERVED_PORTS = (6502, 6510, 6600)
RESERVED_DISPLAY = ":7"

DEFAULT_TEMPLATE = (
    Path.home() / ".var/app/net.sf.VICE/config/vice/vicerc"
)

# Overridden in every seeded `vicerc`, and nothing else is.  `SaveResourcesOnExit`
# is first because it is the one that protects Donald's own file: with it on,
# the last instance to exit would leave his configuration pointing at whatever
# port it happened to use.
OVERRIDES = {
    "SaveResourcesOnExit": "0",
    "BinaryMonitorServer": "1",
    "MonitorServer": "1",
    # The pool attaches by path (`Session.attach`), so a fliplist inherited from
    # the template would only put the player's own disks a keystroke away.
    "FliplistName": '""',
}


class PoolFull(RuntimeError):
    """Every instance slot is leased by another process."""


class PoolUnavailable(RuntimeError):
    """No `fcntl`, so no lease, so no pool. POSIX only."""


def pool_root() -> Path:
    """Where the slots live. `$POR_INST` overrides, which is how tests isolate."""
    return Path(os.environ.get("POR_INST") or (REPO / "work" / "inst"))


def template_vicerc() -> Path:
    """Donald's `vicerc`, read as a template and never opened for writing.

    It carries the JiffyDOS kernal paths, and `Session.boot()` answers the
    fastloader prompt `Y` unconditionally -- under a stock kernal that answer is
    wrong and the symptom looks like a corrupt disk image.  Seeding by *copying*
    rather than writing fresh is what keeps those two lines.
    """
    return Path(os.environ.get("POR_VICERC_TEMPLATE") or DEFAULT_TEMPLATE)


@dataclass
class Slot:
    """One leased instance and the six things it owns.

    The lease is an `fcntl.flock` on `<dir>/lease`, held by this process for as
    long as it lives.  `release()` is a courtesy; exiting does the same thing.
    """

    n: int
    dir: Path
    _fd: int
    _xfd: int = -1

    # -- the six resources -------------------------------------------------

    _display_num: int = -1
    
    @property
    def port(self) -> int:
        """Binary monitor. VICE serves exactly one connection to this."""
        return BIN_BASE + self.n

    @property
    def text_port(self) -> int:
        """Text monitor -- `Session.attach` swaps disks over it."""
        return TEXT_BASE + self.n

    @property
    def cmd_port(self) -> int:
        """`tools/session.py serve()`'s command port."""
        return CMD_BASE + self.n

    @property
    def display(self) -> str:
        return f":{self._display_num}"

    @property
    def vicerc(self) -> Path:
        return self.dir / "vicerc"

    # -- the lease ---------------------------------------------------------

    def record(self, **fields: object) -> dict:
        """Update the lease file's informational JSON, in place.

        Informational: the flock is the lease.  But `reap()` reads `pgid` out of
        here to know what to kill, so it is the one field that matters.
        """
        info = self.info()
        info.update(fields)
        os.lseek(self._fd, 0, os.SEEK_SET)
        os.ftruncate(self._fd, 0)
        os.write(self._fd, json.dumps(info).encode())
        os.fsync(self._fd)
        return info

    def info(self) -> dict:
        return _read_lease(self.dir)

    def release(self) -> None:
        if self._fd >= 0:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = -1
        if self._xfd >= 0:
            fcntl.flock(self._xfd, fcntl.LOCK_UN)
            os.close(self._xfd)
            self._xfd = -1

    def __enter__(self) -> Slot:
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()

    # -- what an instance is made of --------------------------------------

    def monflags(self) -> str:
        """The launch flags `porlaunch.sh` passes through as `$MONFLAGS`."""
        return (
            f"-binarymonitor -binarymonitoraddress 127.0.0.1:{self.port} "
            f"-remotemonitor -remotemonitoraddress 127.0.0.1:{self.text_port}"
        )

    def env(self) -> dict[str, str]:
        """What a launcher needs in its environment to be this slot.

        `POR_HEADLESS` defaults to `"1"` here rather than in every caller
        (#147) -- a slot is by definition something an agent claimed, and an
        agent must not put a window, or its sound, on Donald's screen. Every
        caller that builds a launch environment does
        `dict(os.environ, **slot.env())` (`tools/session.py:281-283`,
        `tools/instance.py main()`), so `slot.env()`'s own values win over
        whatever `os.environ` already held -- an unconditional `"1"` here
        would silently overrule a human who exported `POR_HEADLESS=0` to
        watch a run. Reading it from `os.environ` first, and only defaulting
        when it is absent, is what lets that override reach `porlaunch.sh`.
        """
        return {
            "POR_SLOT": str(self.n),
            "POR_DISPLAY": self.display,
            "POR_VICERC": str(self.vicerc),
            "POR_MONITOR": f"127.0.0.1:{self.port}",
            "MONFLAGS": self.monflags(),
            "POR_HEADLESS": os.environ.get("POR_HEADLESS", "1"),
        }

    def seed_vicerc(self, template: Path | None = None) -> Path:
        return seed_vicerc(self, template)

    def teardown(self, timeout: float = 8.0) -> bool:
        """Kill the process group this slot launched. Nothing else.

        Returns True if something was killed.  The pgid comes out of this slot's
        own lease file, so a slot that never launched anything tears down to a
        no-op rather than guessing.
        """
        pgid = self.info().get("pgid")
        killed = _killpg(pgid, timeout)
        if killed:
            self.record(pgid=None, x64sc=None)
        return killed


# --------------------------------------------------------------------------
# Claiming
# --------------------------------------------------------------------------


def claim(game: str = "por", note: str = "", slots: int = SLOTS) -> Slot:
    """Lease the first free slot, reaping wreckage on the way, or raise `PoolFull`.

    Allocation is `LOCK_EX | LOCK_NB` on each slot in turn, first success wins.
    Reaping happens *while holding the lock*, which is the only moment at which
    "this slot is nobody's" is a fact rather than a race.
    """
    if fcntl is None:
        raise PoolUnavailable("the instance pool needs flock, so it is POSIX only")
    root = pool_root()
    root.mkdir(parents=True, exist_ok=True)
    for n in range(slots):
        d = root / str(n)
        d.mkdir(exist_ok=True)
        fd = os.open(d / "lease", os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            continue
            
        display_num = -1
        display_fd = -1
        # `SLOTS`, never the caller's `slots`: that argument bounds how many
        # **leases** to try, and a caller running a smaller worker pool must
        # not thereby narrow the band this module advertises everywhere else
        # (#213).  The two counts are the same by default and are not the
        # same thing.
        for i in range(SLOTS):
            x = DISPLAY_BASE + i
            xfd = os.open(f"/tmp/.wish-x11-{x}.lock", os.O_RDWR | os.O_CREAT, 0o644)
            try:
                fcntl.flock(xfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if not _server_on(f":{x}"):
                    display_num = x
                    display_fd = xfd
                    break
                fcntl.flock(xfd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(xfd)

        if display_num == -1:
            # The band, not the lease count, is what is exhausted here (#213):
            # a display can be taken by something outside the pool -- Xwayland,
            # a hand-started Xvfb -- while a slot lease still sits free.  That
            # divergence is why this raises on the spot rather than moving to
            # the next `n`: whether the band is full does not depend on which
            # slot asked, so trying another slot cannot change the answer.
            os.close(fd)
            raise PoolFull(
                f"the VICE display band :{DISPLAY_BASE}-:{DISPLAY_BASE + SLOTS - 1} is full"
            )

        slot = Slot(n=n, dir=d, _fd=fd, _xfd=display_fd, _display_num=display_num)
        _reap_held(slot)
        if _listening(slot.port):
            # Reaping found something and could not free the port: the lease
            # named no pgid, or the kill did not take.  Step over the slot
            # rather than launch into a port that is already bound -- and
            # emphatically rather than go hunting for the process by name.
            slot.release()
            continue
        slot.record(
            slot=n,
            pid=os.getpid(),
            game=game,
            note=note or os.environ.get("POR_AGENT", ""),
            at=time.time(),
            port=slot.port,
            text_port=slot.text_port,
            cmd_port=slot.cmd_port,
            display=slot.display,
        )
        return slot
    raise PoolFull(f"all {slots} instance slots are leased")


# --------------------------------------------------------------------------
# Reaping -- §3.4's table, and nothing outside it
# --------------------------------------------------------------------------


HELD, CLEAN, ORPHAN, WRECKAGE = "held", "clean", "orphan", "wreckage"


def inspect(n: int) -> str:
    """Which row of §3.4's table this slot is on, without changing anything.

    | lease flock | port answers | greeting | conclusion |
    | held        | --           | --       | somebody's. Do not touch it |
    | free        | no           | --       | clean       |
    | free        | yes          | yes      | orphan -- a healthy VICE nobody owns |
    | free        | yes          | no       | wreckage -- frozen or half-attached |
    """
    d = pool_root() / str(n)
    if not _lease_free(d):
        return HELD
    port = BIN_BASE + n
    if not _listening(port):
        return CLEAN
    return ORPHAN if _greets(port) else WRECKAGE


def reap(n: int, timeout: float = 8.0) -> str:
    """Free slot *n* if it is nobody's. Returns the row of the table it was on.

    Kills **the pgid recorded in that slot's lease file** and nothing else.  A
    slot whose flock is held is somebody's however dead it looks, and this
    refuses it: that refusal is the rule that replaces `ss -tnp | grep 6502`.
    """
    if fcntl is None:
        raise PoolUnavailable("the instance pool needs flock, so it is POSIX only")
    root = pool_root()
    d = root / str(n)
    d.mkdir(parents=True, exist_ok=True)
    fd = os.open(d / "lease", os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return HELD
    slot = Slot(n=n, dir=d, _fd=fd)
    try:
        return _reap_held(slot, timeout)
    finally:
        slot.release()


def _reap_held(slot: Slot, timeout: float = 8.0) -> str:
    """`reap` with the lock already held. Callers must hold it.

    The port decides which row of the table this is; the *lease* decides whether
    anything may be killed, and it already has -- a free flock means the group
    is nobody's.  So a recorded pgid is killed whichever row it is on.

    That is a correction to `docs/123` §3.4, which killed only on the two rows
    where the port answers.  `porlaunch.sh` passes `--die-with-parent`, so a
    crashed holder's *VICE* goes with it and the port falls silent -- but the
    Xvfb or Xephyr it started has no such link and survives, and under the old
    reading nothing ever collected it.
    """
    port = slot.port
    if _listening(port):
        state = ORPHAN if _greets(port) else WRECKAGE
    else:
        state = CLEAN
    if _killpg(slot.info().get("pgid"), timeout):
        slot.record(pgid=None, x64sc=None, reaped=state, reaped_at=time.time())
    return state


#: Which of the lease file's informational fields are still true of the
#: present, per row of the table.  The lease JSON is never cleared -- the flock
#: is the lease, and a release path that writes to disk is a release path that
#: can fail -- so on a released slot the record is the *last* holder's, and
#: reporting it unqualified made every idle slot name a dead owner (#74).
#:
#: * `held`: the holder is alive by definition, so all four are its own.
#: * `orphan`, `wreckage`: the *holder* is gone -- the flock is free -- but the
#:   group it started is still on the port, so the pgid is the live thing
#:   `reap` kills and `game`/`note` say what it is.  `pid` is not: that process
#:   is what the kernel dropped the flock for.
#: * `clean`: nothing is there.  Every field is stale.
LEASE_FIELDS: dict[str, tuple[str, ...]] = {
    HELD: ("pid", "pgid", "game", "note"),
    ORPHAN: ("pgid", "game", "note"),
    WRECKAGE: ("pgid", "game", "note"),
    CLEAN: (),
}


def status(slots: int = SLOTS) -> list[dict]:
    """One row per slot, carrying only what is true of the slot *now*.

    A field the state does not vouch for is `None` rather than the last
    holder's value; `LEASE_FIELDS` says which those are and why.

    `held_for`, `idle_for`, `owner_pgid` and `shared_pgid` are answered only
    for `HELD` rows, and only from evidence that does not disturb the slot --
    see `idle_seconds` and `_owner_pgid`.  A slot somebody else holds is
    somebody's; this reports on it without touching it.
    """
    root = pool_root()
    out = []
    for n in range(slots):
        d = root / str(n)
        state = inspect(n) if d.is_dir() else CLEAN
        info = _read_lease(d) if d.is_dir() else {}
        live = LEASE_FIELDS[state]
        row = {
            "slot": n,
            "state": state,
            "port": BIN_BASE + n,
            "text_port": TEXT_BASE + n,
            "cmd_port": CMD_BASE + n,
            "display": info.get("display") or f":{DISPLAY_BASE + n}",
            **{f: info.get(f) if f in live else None
               for f in ("pid", "pgid", "game", "note")},
        }
        if state == HELD:
            row["held_for"] = _held_for(info)
            row["idle_for"] = idle_seconds(n)
            row["owner_pgid"] = _owner_pgid(row["pid"])
        else:
            row["held_for"] = None
            row["idle_for"] = None
            row["owner_pgid"] = None
        out.append(row)
    shared = _shared_pgids(out)
    for row in out:
        row["shared_pgid"] = row["owner_pgid"] in shared
    return out


# --------------------------------------------------------------------------
# A held slot that is doing nothing -- report it, never reap it
# --------------------------------------------------------------------------
#
# `_reap_held` is for a slot whose *holder* is gone.  This is the other case:
# the holder is alive, the flock says so, and the slot may still be sitting
# untouched for hours -- an agent that claimed it, hit a problem, claimed
# another, and never came back.  Found by a person asking, because nothing
# said it was odd.  `docs/123-parallel-sessions.md` §3.5 is the design; the
# two rules that bound it are the same ones that bound everything else here:
# no attaching to a monitor an agent may be using, and no lock taken to see
# if one is free.


def idle_seconds(n: int) -> float | None:
    """Seconds since anything but the lease file itself changed in slot *n*'s
    own directory, or `None` if nothing but the lease has ever been written.

    `vicerc` and a disk copy land there once, near the start of a run;
    `vice.log` grows for as long as VICE has something to say on stdout; a
    screenshot lands at `<slot>/shot.png` whenever a driver takes one.  The
    lease file is excluded on purpose -- `record()` rewrites it on its own
    schedule (claim, launch, teardown), which is bookkeeping about the lease
    and not evidence that anything happened *in* the slot.

    A plain `stat()` on files already on disk: no monitor connection, no
    lock attempt, nothing written.  It is the one thing safe to read on a
    slot somebody else holds.

    **Evidence, not a verdict.** A session driven by nothing but monitor
    reads -- no screenshot taken, no save made -- writes nothing here and
    reads as idle while it may not be.  `held_for` alongside it is what
    makes the case: a lease held for hours with this number the same size.
    """
    d = pool_root() / str(n)
    try:
        mtimes = [f.stat().st_mtime for f in d.iterdir()
                  if f.is_file() and f.name != "lease"]
    except OSError:
        return None
    if not mtimes:
        return None
    return time.time() - max(mtimes)


def _held_for(info: dict) -> float | None:
    """Seconds since this lease was claimed, from the `at` `record()` always
    sets. `None` if the lease carries no `at` -- a lease from before this
    field existed, or a hand-edited one."""
    at = info.get("at")
    if not isinstance(at, (int, float)):
        return None
    return time.time() - at


def _owner_pgid(pid: object) -> int | None:
    """The process group of the pid a lease names, or `None`.

    `os.getpgid` is a query, not a lock or a connection, so it is safe to
    call on a pid somebody else's process owns. `None` for anything that is
    not a plausible pid, or for a pid the kernel no longer knows about -- the
    lease's `pid` is informational, the same as everything else in it.
    """
    if not isinstance(pid, int) or pid <= 0:
        return None
    try:
        return os.getpgid(pid)
    except OSError:
        return None


def _shared_pgids(rows: list[dict]) -> set[int]:
    """Which `owner_pgid`s these rows found holding more than one slot --
    one process that claimed twice and released neither, the leak
    `docs/123-parallel-sessions.md` §3.5 was written for."""
    counts: dict[int, int] = {}
    for row in rows:
        pgid = row.get("owner_pgid")
        if pgid is not None:
            counts[pgid] = counts.get(pgid, 0) + 1
    return {pgid for pgid, c in counts.items() if c > 1}


def _fmt_duration(seconds: float | None) -> str:
    """`None` as `-`; otherwise the coarsest unit a person reads at a glance."""
    if seconds is None:
        return "-"
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


# --------------------------------------------------------------------------
# The display bands -- what /tmp actually holds, without touching it
# --------------------------------------------------------------------------
#
# #233 (The test suite takes the emulator displays agents need, and eight
# slots is no longer enough), part 3: `/tmp/.wish-x11-<n>.lock` files
# accumulate and outlive the processes that created them -- a claim opens
# one with `O_CREAT` and never unlinks it, because the lock is what matters
# and the kernel drops that on its own.  Twenty-seven such files existed on
# Donald's machine with exactly one display genuinely in use, and finding
# that out took a `fuser` on each by hand.  What follows answers the same
# question by reading `/proc/locks`, which the kernel already keeps.
#
# **This must never take a lock to find out whether one is free** -- taking
# it is not a test of it, in this codebase specifically: the lock lives on
# the file's *inode*, not its path, so a sweeper that unlinked a path a
# process still held would leave that process holding an now-orphaned
# inode while the next `claim()` opened a fresh file at the same path and
# locked *that* -- two emulators, each believing it owns the display.
# `Slot`'s own docstring already gives the reason there is no sweeper: the
# kernel drops the flock when the holder dies however it dies, so there is
# no stale-lock policy to get right.  Reading, never writing, is what keeps
# this view from becoming one.


def _lock_holder(path: Path) -> int | None:
    """The pid holding an `flock` on `path`, or `None` if nothing does.

    Answered from `/proc/locks` rather than by attempting the lock, because
    attempting it is not read-only.  `flock()` locks are listed there as
    `FLOCK` entries keyed by the file's device and inode, which is what is
    matched here -- not the path, so a path whose original inode was
    unlinked and recreated is correctly read as unheld even while the old
    inode is still locked by whoever has it open.

    `None` for a file that does not exist, for a kernel with no
    `/proc/locks` (anything but Linux), and for any other read failure: the
    caller then reports "free", and a human still has `fuser`/`lsof` to
    reach for if that default is ever wrong for what they are looking at.
    """
    try:
        st = path.stat()
    except OSError:
        return None
    try:
        lines = Path("/proc/locks").read_text().splitlines()
    except OSError:
        return None
    target = f"{os.major(st.st_dev):02x}:{os.minor(st.st_dev):02x}:{st.st_ino}"
    for line in lines:
        fields = line.split()
        # A pending request -- one process blocked waiting for another's
        # lock -- prints as `<id>: -> FLOCK ...`, one field further along
        # than a held one, and names the *waiter*, not the holder.
        if len(fields) < 6 or fields[1] == "->" or fields[1] != "FLOCK":
            continue
        if fields[5] == target:
            try:
                return int(fields[4])
            except ValueError:
                continue
    return None


def display_rows() -> list[dict]:
    """Every display number in all three pools' bands, and who -- if
    anyone -- holds its `/tmp/.wish-x11-<n>.lock`. Read-only: see the
    section docstring above for why it must stay that way.
    """
    from tools import dosbox, dosboxx  # local: instance.py stays importable alone

    out = []
    for pool_name, base, slots in (
        ("vice", DISPLAY_BASE, SLOTS),
        ("dosbox", dosbox.DISPLAY_BASE, dosbox.SLOTS),
        ("dosboxx", dosboxx.DISPLAY_BASE, dosboxx.SLOTS),
    ):
        for i in range(slots):
            n = base + i
            path = Path(f"/tmp/.wish-x11-{n}.lock")
            pid = _lock_holder(path)
            out.append({
                "pool": pool_name,
                "display": f":{n}",
                "path": str(path),
                "exists": path.exists(),
                "held": pid is not None,
                "pid": pid,
            })
    return out


# --------------------------------------------------------------------------
# The per-instance vicerc
# --------------------------------------------------------------------------


def seed_vicerc(slot: Slot, template: Path | None = None) -> Path:
    """Write `<slot>/vicerc`: Donald's file, with six lines overridden.

    Copying rather than writing fresh keeps `KernalName` and `DosName1541ii` --
    the JiffyDOS ROMs the unconditional `Y` at the fastloader prompt assumes.
    The template is opened read-only; nothing in the pool ever writes to it.

    A missing template is not an error.  A machine with no VICE config yet still
    gets a valid rc, it just has no JiffyDOS in it -- and then the fastloader
    answer is the caller's problem, which is what `docs/131-fastloader.md` is
    measuring.
    """
    src = Path(template) if template is not None else template_vicerc()
    lines = src.read_text(encoding="utf-8").splitlines() if src.is_file() else ["[C64SC]"]
    overrides = dict(OVERRIDES)
    overrides["BinaryMonitorServerAddress"] = f'"127.0.0.1:{slot.port}"'
    overrides["MonitorServerAddress"] = f'"127.0.0.1:{slot.text_port}"'

    out: list[str] = []
    section = ""
    written = False

    def flush() -> None:
        nonlocal written
        if not written:
            out.extend(f"{k}={v}" for k, v in overrides.items())
            written = True

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            if section == "C64SC":
                flush()
            section = stripped.strip("[]")
            out.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if section == "C64SC" and key in overrides:
            continue                    # replaced below, in one block
        out.append(line)
    if section == "C64SC":
        flush()
    if not written:                     # a template with no [C64SC] at all
        out.append("[C64SC]")
        flush()

    slot.dir.mkdir(parents=True, exist_ok=True)
    slot.vicerc.write_text("\n".join(out) + "\n")
    return slot.vicerc


# --------------------------------------------------------------------------
# The disk copies
# --------------------------------------------------------------------------


def copy_disks(slot: Slot, sources) -> list[Path]:
    """Copy each disk image into the slot's own directory and return the copies.

    The game **writes** to the disks it is given, so the player's own images are
    never in the drive -- and under a pool two instances sharing one copy would
    corrupt each other's saves.  Sources are opened read-only.
    """
    slot.dir.mkdir(parents=True, exist_ok=True)
    out = []
    for src in sources:
        src = Path(src)
        dst = slot.dir / src.name
        shutil.copyfile(src, dst)
        dst.chmod(0o644)
        out.append(dst)
    return out


# --------------------------------------------------------------------------
# Plumbing
# --------------------------------------------------------------------------


def _read_lease(d: Path) -> dict:
    try:
        return json.loads((d / "lease").read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError):
        return {}


def _lease_free(d: Path) -> bool:
    """Could this slot be locked right now? Does not keep the lock."""
    if fcntl is None or not (d / "lease").exists():
        return True
    fd = os.open(d / "lease", os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


def _listening(port: int, host: str = "127.0.0.1", timeout: float = 0.25) -> bool:
    try:
        socket.create_connection((host, port), timeout).close()
        return True
    except OSError:
        return False


def _greets(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    """Does a binary monitor on this port answer a ping?

    A VICE that accepts the connection and never answers has another client
    attached or a checkpoint armed on a socket that no longer exists.  From the
    outside the two are identical, which is exactly why the *lease* and not the
    socket decides whether a slot may be reclaimed.
    """
    sys.path.insert(0, str(REPO))
    from automap.vice import Monitor  # noqa: PLC0415 - optional, and slow to import
    try:
        with Monitor(host=host, port=port, timeout=timeout) as m:
            m.ping()
        return True
    except Exception:
        return False


def _server_on(display: str) -> bool:
    n = display.lstrip(":").split(".")[0]
    if not hasattr(socket, "AF_UNIX"):
        return False
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(1.0)
        sock.connect(f"/tmp/.X11-unix/X{n}")
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _killpg(pgid: object, timeout: float = 8.0) -> bool:
    """SIGTERM a process group, then SIGKILL what is left. By pgid, never by name.

    Refuses our own group and anything that is not a plausible pgid, because the
    one time the by-name rule was broken what died was Donald's own window.
    """
    if not isinstance(pgid, int) or pgid <= 1:
        return False
    if pgid == os.getpgid(0):
        raise ValueError(f"refusing to kill our own process group {pgid}")
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            os.killpg(pgid, 0)
        except OSError:
            return True
        time.sleep(0.2)
    with contextlib.suppress(OSError):
        os.killpg(pgid, signal.SIGKILL)
    return True


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="the VICE instance pool")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("claim", help="lease a slot and run a command inside it")
    p.add_argument("--game", default="por")
    p.add_argument("--note", default="")
    p.add_argument("--seed", action="store_true", help="write the slot's vicerc")
    p.add_argument("exec", nargs="*", help="command to run while holding the lease")

    p = sub.add_parser("status", help="every slot, and which row of the table it is on")
    p.add_argument("--json", action="store_true")
    p.add_argument("--displays", action="store_true",
                   help="every display in all three bands, and who -- if anyone -- "
                        "holds its lock; read-only, takes no lock itself")

    p = sub.add_parser("reap", help="free a slot that is nobody's")
    p.add_argument("slot", nargs="?", type=int)

    args = ap.parse_args(argv)

    if args.cmd == "status" and args.displays:
        rows = display_rows()
        if args.json:
            print(json.dumps(rows, indent=2))
        else:
            print(f"{'display':>8} {'pool':<8} {'state':<7} pid")
            for r in rows:
                state = "held" if r["held"] else ("free" if r["exists"] else "no file")
                print(f"{r['display']:>8} {r['pool']:<8} {state:<7} {r['pid'] or '-'}")
        return 0

    if args.cmd == "status":
        rows = status()
        if args.json:
            print(json.dumps(rows, indent=2))
        else:
            print(f"{'slot':>4} {'state':<9} {'bin':>5} {'text':>5} {'cmd':>5} "
                  f"{'disp':>5}  {'pid':<8} {'pgid':<8} {'held':>7} {'idle':>7} game")
            for r in rows:
                print(f"{r['slot']:>4} {r['state']:<9} {r['port']:>5} "
                      f"{r['text_port']:>5} {r['cmd_port']:>5} {r['display']:>5}  "
                      f"{str(r['pid'] or '-'):<8} {str(r['pgid'] or '-'):<8} "
                      f"{_fmt_duration(r['held_for']):>7} {_fmt_duration(r['idle_for']):>7} "
                      f"{r['game'] or '-'}")
            groups: dict[int, list[int]] = {}
            for r in rows:
                if r["shared_pgid"]:
                    groups.setdefault(r["owner_pgid"], []).append(r["slot"])
            for pgid, slots_held in groups.items():
                print(f"warning: pgid {pgid} holds slots "
                      f"{', '.join(map(str, slots_held))} -- one process, "
                      f"several slots", file=sys.stderr)
        return 0

    if args.cmd == "reap":
        targets = [args.slot] if args.slot is not None else range(SLOTS)
        for n in targets:
            print(f"slot {n}: {reap(n)}")
        return 0

    with claim(game=args.game, note=args.note) as slot:
        if args.seed or args.exec:
            slot.seed_vicerc()
        if not args.exec:
            # Without a command the lease dies with this process, which makes a
            # bare `claim` useful only for seeing what a slot would be.
            print(json.dumps({**slot.env(), "dir": str(slot.dir)}, indent=2))
            print("# the lease is released as this process exits; use "
                  "`claim -- <command>` to hold it", file=sys.stderr)
            return 0
        env = dict(os.environ, **slot.env())
        proc = subprocess.Popen(args.exec, env=env, start_new_session=True)
        slot.record(pgid=os.getpgid(proc.pid), cmd=args.exec)
        try:
            return proc.wait()
        finally:
            slot.teardown()


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(main())
