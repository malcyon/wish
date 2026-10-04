"""The FS-UAE lane session: the calls `acceptance.run_recon` makes of `winuaesession.WinGuest`, answered by a patched FS-UAE in an instance-pool slot."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import shutil
import time
from typing import Any

from tools.amiga import amigakeys, fsuaegdb, screens
from tools.amiga.winuaesession import RouteError
from tools.registry import instance

#: Emulator age, in seconds, before the first key of each title is sent. Each is when that title's first
#: screen that takes a key was first seen with `--floppy_drive_speed=0`; a key sent earlier is dropped.
#: Curse is the code wheel, not the party menu (seen at 122 s), because its first key is the wheel's ESC.
FIRST_KEY_AFTER = {"pool": 42.0, "curse": 45.0, "ssb": 48.0, "darkness": 259.0,
                   "darkness-reload": 259.0, "darkness-unstarted": 259.0}
#: Seconds a key is held; the game does not see a shorter press.
HOLD = 0.12
#: Seconds the emulator waits for the debugger client before it carries on alone.
CLIENT_WAIT = 120
#: A game save reaches the disk image about ten seconds after its key; `stop` leaves a little more.
SAVE_REACHES_DISK = 12.0
#: Seconds between a grab and the next one while a screen settles, and between menu keys of a swap.
SETTLE_INTERVAL = 1.0
SWAP_STEP = 1.5
#: Seconds the emulator may take to write the log line of a disk change.
SWAP_LOG_WAIT = 10.0
#: The options WinUAE routes carry as `name=value`, as FS-UAE command lines. An empty list is an option with
#: no FS-UAE counterpart: `floppy2type=0` makes the third drive a 3.5-inch one, which every FS-UAE drive is.
OPTIONS = {"nr_floppies": lambda value: [f"--floppy_drive_count={value}"],
           "floppy2type": lambda value: []}
#: What every run is started with beyond the launcher's own options.
BASE_OPTIONS = ("--amiga_model=A500", "--writable_floppy_images=1", "--floppy_drive_speed=0",
                "--automatic_input_grab=0", "--initial_input_grab=0")
STAGED_NAME = re.compile(r"[A-Za-z0-9._-]+\.adf")
SILENT_ENVIRONMENT = {"SDL_AUDIODRIVER": "dummy", "ALSOFT_DRIVERS": "null"}


class FsuaeGuest:
    """One holder's FS-UAE run: a pool slot, its Xvfb and emulator, and the one debugger connection."""

    #: `acceptance.run_recon` stops a run that needs a snapshot before it claims a slot.
    can_snapshot = False

    def __init__(self, game: str = "amiga", first_key_after: float | None = None) -> None:
        self.game = game
        self.first_key_after = first_key_after
        self.slot: Any = None
        self.work: pathlib.Path | None = None
        #: Disk name as the route knows it -> its copy in the slot; mounted disks first, then spares.
        self.staged: dict[str, pathlib.Path] = {}
        self.xvfb: Any = None
        self.emulator: Any = None
        self.gdb: Any = None
        self._started = 0.0
        self._last_key: float | None = None
        self._keyed = False
        self._screened = False
        self._mounted: list[pathlib.Path] = []
        self._hashes_before: dict[str, str] = {}

    @staticmethod
    def remote_path(issue: str, holder: str, key: str) -> str:
        """The name disk `key` of `holder`'s run for ticket `issue` has in the slot's work directory."""
        return f"wish{issue}-{holder}-{key}.adf"

    # -- the lease and the disks ------------------------------------------------

    def claim(self, holder: str, timeout: float) -> str:
        try:
            self.slot = instance.claim(game=self.game, note=holder)
        except (instance.PoolFull, instance.PoolUnavailable) as exc:
            raise RouteError(f"no instance slot: {exc}") from exc
        self.work = self.slot.dir / f"fsuae-{holder}"
        (self.work / "shots").mkdir(parents=True, exist_ok=True)
        return f"ok claimed by {holder}"

    def _need_slot(self, what: str) -> pathlib.Path:
        if self.slot is None or self.work is None:
            raise RouteError(f"{what} before the slot was claimed")
        return self.work

    def put(self, local: pathlib.Path, remote: str, timeout: float) -> str:
        work = self._need_slot("put")
        if not STAGED_NAME.fullmatch(remote):
            raise RouteError(f"{remote!r} is not a disk name this lane stages")
        dest = work / remote
        shutil.copyfile(local, dest)
        dest.chmod(0o644)
        self.staged[remote] = dest
        return f"ok {remote}"

    def _staged(self, remote: str) -> pathlib.Path:
        try:
            return self.staged[remote]
        except KeyError:
            raise RouteError(f"{remote} was not staged by this run") from None

    def get(self, remote: str, local: pathlib.Path, timeout: float) -> str:
        path = self._staged(remote)
        if self.emulator is not None and self.emulator.poll() is None:
            raise RouteError(f"{remote} is still open in a running emulator; stop it first")
        shutil.copyfile(path, local)
        return f"ok {remote}"

    # -- starting and stopping --------------------------------------------------

    def start(self, holder: str, *drives: str | None, timeout: float,
              options: tuple[str, ...] = (), config: str | None = None) -> str:
        """Start the emulator with `drives` in DF0 upward, every other staged disk in the swap list."""
        work = self._need_slot("start")
        if self.emulator is not None:
            raise RouteError("the emulator was already started")
        if None in drives:
            raise RouteError("FS-UAE mounts drives from DF0 upward, so a drive cannot be left empty")
        mounted = [self._staged(d) for d in drives if d is not None]
        spares = [p for p in self.staged.values() if p not in mounted]
        extra = list(BASE_OPTIONS)
        for option in options:
            name, _, value = option.partition("=")
            if name not in OPTIONS:
                raise RouteError(f"option {option!r} has no FS-UAE counterpart")
            extra += OPTIONS[name](value)
        args = argparse.Namespace(
            fs_uae=str(_binary()), out=str(work), display=self.slot.display,
            kickstart=str(_kickstart()), floppy=[str(p) for p in mounted],
            swap=[str(p) for p in spares], foreground=True, wait=CLIENT_WAIT,
            port=self.slot.port, extra=extra, screenshots=str(work / "shots"))
        self._mounted = mounted
        self._hashes_before = self._digests()
        self.xvfb, self.emulator = fsuaegdb.start_processes(args, True)
        self._started = time.monotonic()
        try:
            self._attach(timeout)
            self._require_silence(work)
        except BaseException:
            self._take_down()
            raise
        return f"ok pid={self.emulator.pid} display={self.slot.display} port={self.slot.port}"

    def _attach(self, timeout: float) -> None:
        """Connect the debugger, which continues the machine, and read the raster as proof it runs."""
        from automap import amiga  # noqa: PLC0415

        end = time.monotonic() + timeout
        while True:
            if self.emulator.poll() is not None:
                raise RouteError("the emulator exited before the debugger connected")
            try:
                self.gdb = amiga.FsuaeGdb(port=self.slot.port, resume=True)
                break
            except (amiga.FsuaeError, OSError) as exc:
                if time.monotonic() >= end:
                    raise RouteError(f"the debugger did not connect within {timeout:.0f}s: {exc}") from exc
                time.sleep(0.5)
        try:
            self.gdb.read_memory(fsuaegdb.VHPOSR, 2)
        except (amiga.FsuaeError, OSError) as exc:
            raise RouteError(f"the machine did not answer after it was continued: {exc}") from exc

    def _environment(self) -> dict[str, str]:
        raw = pathlib.Path(f"/proc/{self.emulator.pid}/environ").read_bytes()
        pairs = (item.partition(b"=") for item in raw.split(b"\0") if item)
        return {k.decode("latin-1"): v.decode("latin-1") for k, _, v in pairs}

    def _require_silence(self, work: pathlib.Path) -> None:
        env = self._environment()
        found = {name: env.get(name) for name in SILENT_ENVIRONMENT}
        (work / "environ.txt").write_text("".join(f"{k}={v}\n" for k, v in found.items()))
        if found != SILENT_ENVIRONMENT:
            raise RouteError(f"the emulator is not silent: {found}")

    def silence(self, proof: Any = None) -> bool:
        """True before a start, where the launcher fixes the environment; after one, whether the process has it."""
        if self.emulator is None:
            return True
        try:
            env = self._environment()
        except OSError:
            return False
        return all(env.get(k) == v for k, v in SILENT_ENVIRONMENT.items())

    def _digests(self) -> dict[str, str]:
        return {name: hashlib.sha256(path.read_bytes()).hexdigest()
                for name, path in self.staged.items() if path.exists()}

    def _take_down(self) -> None:
        if self.gdb is not None:
            try:
                self.gdb.close()
            except Exception:
                pass
            self.gdb = None
        fsuaegdb.terminate(self.emulator, self.xvfb)

    def stop(self, holder: str, timeout: float) -> str:
        """End the emulator after a game save has had time to reach the disk image; record each image's hash."""
        if self.emulator is None:
            if self.slot is None:
                raise RouteError("stop: no emulator was started")
            return "ok stopped; nothing was running"
        if self._last_key is not None:
            left = self._last_key + SAVE_REACHES_DISK - time.monotonic()
            if left > 0:
                time.sleep(min(left, timeout / 2))
        before = self._digests()
        self._take_down()
        after = self._digests()
        record = {"before_stop": before, "after_stop": after, "at_start": self._hashes_before}
        (self._need_slot("stop") / "adf-sha256.json").write_text(json.dumps(record, indent=1, sort_keys=True))
        changed = sorted(name for name in after if after[name] != self._hashes_before.get(name))
        return f"ok stopped; changed on disk: {', '.join(changed) or 'none'}"

    def release(self, holder: str, timeout: float) -> str:
        if self.slot is not None:
            self.slot.release()
            self.slot = None
        return "ok released"

    # -- the screen ---------------------------------------------------------------

    def _shoot(self, timeout: float) -> pathlib.Path | None:
        """Ask for the emulator's own screenshot (Alt+S) and return the new file, or None if none came."""
        from PIL import Image  # noqa: PLC0415

        shots = self._need_slot("grab") / "shots"
        seen = set(shots.glob("FS-UAE_Full_*.png"))
        fsuaegdb.press(self.slot.display, "alt+s", 0.0)
        end = time.monotonic() + timeout
        while True:
            for path in sorted(set(shots.glob("FS-UAE_Full_*.png")) - seen):
                try:
                    with Image.open(path) as image:
                        image.load()
                except (OSError, SyntaxError, ValueError):
                    continue  # still being written
                return path
            if time.monotonic() >= end:
                return None
            time.sleep(0.2)

    def grab(self, state: str, raw: pathlib.Path, cropped: pathlib.Path, timeout: float) -> bool:
        """One screenshot, cut to the Amiga screen; False while the emulator has drawn nothing yet."""
        from tools.amiga import fsuaepor  # noqa: PLC0415

        self._need_slot("grab")
        if timeout <= 0:
            raise RouteError(f"no time left to grab {state}")
        if not fsuaepor.find_windows(self.slot.display, 5):
            return False
        path = self._shoot(timeout)
        if path is None:
            if self._screened:
                raise RouteError(f"FS-UAE wrote no screenshot for {state} within {timeout:.0f}s")
            return False
        self._screened = True
        shutil.copyfile(path, raw)
        screens.canonical_file(raw, cropped)
        return True

    def capture(self, state: str, raw: pathlib.Path, cropped: pathlib.Path, timeout: float) -> None:
        """Grab until two consecutive frames are identical."""
        started, previous = time.monotonic(), None
        while True:
            left = timeout - (time.monotonic() - started)
            if left <= 0:
                raise RouteError(f"{state} did not settle inside {timeout:.0f}s")
            if self.grab(state, raw, cropped, left):
                frame = cropped.read_bytes()
                if frame == previous:
                    return
                previous = frame
            else:
                previous = None
            time.sleep(min(SETTLE_INTERVAL, max(0.0, timeout - (time.monotonic() - started))))

    # -- the keyboard ---------------------------------------------------------------

    def _keysym(self, key: str) -> str:
        try:
            row = amigakeys.lookup(key)
        except KeyError:
            raise RouteError(f"{key.upper()} has no key row") from None
        if row.keysym is None:
            raise RouteError(f"{row.name} has no FS-UAE key")
        return row.keysym

    def _send(self, keysym: str) -> None:
        from tools.amiga import fsuaepor  # noqa: PLC0415

        fsuaegdb.check_shift_letter(keysym)
        fsuaepor.keys(argparse.Namespace(display=self.slot.display, key=[keysym],
                                         hold=HOLD, settle=0.0))
        self._last_key = time.monotonic()

    def _wait_for_first_key(self, timeout: float) -> None:
        if self._keyed or self.first_key_after is None:
            return
        wait = self.first_key_after - (time.monotonic() - self._started)
        if wait > timeout:
            raise RouteError(f"the first key needs {wait:.0f}s more of emulator age and the call has "
                             f"{timeout:.0f}s")
        if wait > 0:
            time.sleep(wait)
        self._keyed = True

    def press(self, holder: str, key: str, timeout: float) -> str:
        keysym = self._keysym(key)
        self._wait_for_first_key(timeout)
        self._send(keysym)
        return f"ok {key.upper()}"

    # -- a disk change ----------------------------------------------------------------

    def insert(self, holder: str, drive: int, remote: str, timeout: float, sha256: str) -> dict[str, Any]:
        """Put the staged disk `remote` in DF0 through the F12 menu and prove from the emulator's log that it went in."""
        path = self._staged(remote)
        if drive != 0:
            raise RouteError("the FS-UAE swap sequence inserts into DF0 only")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != sha256:
            raise RouteError(f"staged {remote} has SHA-256 {digest}, not the manifest's {sha256}")
        index = [*self._mounted, *(p for p in self.staged.values() if p not in self._mounted)].index(path)
        log = self._need_slot("insert") / "base" / "Cache" / "Logs" / "fs-uae.log.txt"
        since = log.stat().st_size if log.exists() else 0
        keys = fsuaegdb.insert_floppy(
            fsuaegdb.DEFAULT_SWAP_SEQUENCE, index,
            lambda key: self._send(key), lambda label: time.sleep(SWAP_STEP))
        end = time.monotonic() + min(SWAP_LOG_WAIT, timeout)
        while True:
            lines = fsuaegdb.swap_log_lines(log, since)
            if any(_changes_drive_zero_to(line, path) for line in lines):
                return {"index": index, "keys": keys, "log": lines, "staged": str(path), "sha256": digest}
            if time.monotonic() >= end:
                error = RouteError(f"the emulator log shows no change to {path} after the swap keys")
                error.receipt = {"index": index, "keys": keys, "log": lines}
                raise error
            time.sleep(0.5)

    # -- not available yet -------------------------------------------------------------

    def snapshot(self, name: str, holder: str) -> Any:
        raise RouteError("a machine snapshot is not available on FS-UAE yet")

    def restore(self, name: str, holder: str) -> Any:
        raise RouteError("a machine restore is not available on FS-UAE yet")

    def discard(self, name: str, holder: str) -> Any:
        raise RouteError("a machine snapshot is not available on FS-UAE yet")

    def answer_io(self, holder: str, settle: float = 1.0) -> tuple[Any, Any]:
        """The `(capture, press)` pair the journal answerer reads and types with."""
        def capture(path: pathlib.Path) -> None:
            raw = path.with_suffix(".raw.png")
            if not self.grab("journal", raw, path, 30.0):
                raise RouteError("no emulator window to read the journal from")

        def press(key: str) -> None:
            self.press(holder, key, 30.0)
            time.sleep(settle)

        return capture, press


_DRIVE_CHANGE = re.compile(r"gui_disk_image_change drive (\d+) name (.+?)(?: write protected \d+)?\s*$")


def _changes_drive_zero_to(line: str, path: pathlib.Path) -> bool:
    """Whether a log line puts `path` in DF0, matching the path as logged or resolved."""
    match = _DRIVE_CHANGE.match(line)
    if match is None or match.group(1) != "0":
        return False
    logged = match.group(2)
    return logged in (str(path), str(path.resolve())) or pathlib.Path(logged).resolve() == path.resolve()


def _binary() -> pathlib.Path:
    from tools.amiga import installfsuae  # noqa: PLC0415

    path = installfsuae.install_dir(installfsuae.default_dir()) / installfsuae.BINARY
    if not path.exists():
        raise RouteError(f"the patched FS-UAE is not at {path}; tools/amiga/installfsuae.py installs it")
    return path


def _kickstart() -> pathlib.Path:
    from tools.amiga import fsuaepor  # noqa: PLC0415

    try:
        return fsuaepor.kickstart()
    except SystemExit as exc:
        raise RouteError(str(exc)) from exc
