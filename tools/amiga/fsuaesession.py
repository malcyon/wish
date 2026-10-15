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
                   "darkness-reload": 259.0, "darkness-unstarted": 259.0,
                   "darkness-vault": 259.0}
#: Seconds a key is held; the game does not see a shorter press.
HOLD = 0.12
#: Seconds the emulator waits for the debugger client before it carries on alone.
CLIENT_WAIT = 120
#: A game save reaches the disk image about ten seconds after its key; `stop` leaves a little more.
SAVE_REACHES_DISK = 12.0
#: Seconds between the reads of a disk image `get_live` compares.
LIVE_COPY_INTERVAL = 1.0
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
#: The F12 menu's savestate slots; a new snapshot name takes the lowest one no name holds.
STATE_SLOTS = tuple(range(1, 10))
#: Up presses that take the menu's top list past its first row onto the window's close button,
#: more than the list has rows; the Down after them lands on PAUSE. Return on the close button
#: quits the emulator, so no walk presses Return straight after an Up.
MENU_PAST_TOP = 20
#: Down presses that take the top list to its last row, RESET, more than the list has rows.
MENU_TO_LAST = 20
#: Seconds the emulator may take to write the log line of a state save, a load or a reset.
STATE_LOG_WAIT = 30.0
#: Seconds a restored picture has to come back before the receipt records that it did not.
REDRAW_WAIT = 10.0
#: A frame is the black picture a load leaves while fewer than `BLACK_SHARE` of its pixels have
#: a channel above `BLACK_LEVEL`. Measured on Curse: 2.0% for the black frame after a load (only
#: the top border), 54% to 99% for the game's own screens.
BLACK_LEVEL = 40
BLACK_SHARE = 0.05
#: Seconds the emulator may take to log the F12 menu opening or closing.
MENU_LOG_WAIT = 5.0
#: More BackSpaces than the menu has levels: the top list, SAVESTATES, a slot and its
#: "Overwrite savestate N?" question make four.
MENU_MAX_DEPTH = 5
#: The route step kinds this guest carries out; `fsuaewishaccept.guest_gaps` reads `supports`.
SUPPORTED_STEPS = frozenset({"insert", "snapshot", "restore", "reset"})


class FsuaeGuest:
    """One holder's FS-UAE run: a pool slot, its Xvfb and emulator, and the one debugger connection."""

    #: `acceptance.run_recon` stops a run that needs a snapshot before it claims a slot. It stays
    #: False although `snapshot` and `restore` work: on the default guard-only binary the picture
    #: stays black after a load until the game draws, so a restore followed by a screen guard fails.
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
        #: The newest screenshot taken, as `Controller._capture` records it; None before the first.
        self.last_shot: dict[str, str] | None = None
        self._started = 0.0
        self._last_key: float | None = None
        self._keyed = False
        self._screened = False
        self._mounted: list[pathlib.Path] = []
        #: The swap list entry in DF0. `start` lists the mounted disks first and mounts the first
        #: in DF0, so that disk is entry 0 until an `insert` changes it.
        self._drive_zero = 0
        #: Whether the frame on display matched a screen guard; `note_recognised` sets it and each
        #: new frame clears it.
        self._recognised = False
        self._hashes_before: dict[str, str] = {}
        #: How many menus deep the F12 menu reopens: 1 is its top list. A soft reset leaves 1,
        #: `insert` 2 and a state save or load 3; None after a walk that did not finish or whose
        #: log line did not come, until `_recover_menu` closes the menu on its top list.
        self._menu_depth: int | None = 1
        #: Slots the menu believes hold a state. It reads the files once at start and marks a
        #: slot after a save, never after a file is deleted, so a discarded slot stays here.
        self._menu_full: set[int] = set()

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

    def get_live(self, remote: str, local: pathlib.Path, timeout: float) -> str:
        """Copy `remote` while the emulator runs, once a save has had time to reach the image.

        Waits until `SAVE_REACHES_DISK` after the last key, then reads the image until two
        consecutive reads are identical and writes that one to `local`. Two equal reads do not
        prove the image complete: the emulator writes a track through a buffered file and
        nothing flushes it, so the end of the last track written can stay in the buffer until
        the drive writes another track or the emulator stops. A caller that needs the saved
        image exactly compares this copy with the one `get` takes after `stop`.
        """
        path = self._staged(remote)
        if self.emulator is None or self.emulator.poll() is not None:
            return self.get(remote, local, timeout)
        left = 0.0 if self._last_key is None else (
            self._last_key + SAVE_REACHES_DISK - time.monotonic())
        if left + 2 * LIVE_COPY_INTERVAL > timeout:
            raise RouteError(f"{remote} needs {left:.0f}s more for the last save to reach it and "
                             f"two reads after, and the call has {timeout:.0f}s")
        if left > 0:
            time.sleep(left)
        end = time.monotonic() + timeout - max(left, 0.0)
        previous = None
        while True:
            data = path.read_bytes()
            if data == previous:
                local.write_bytes(data)
                return f"ok {remote}"
            if time.monotonic() >= end:
                raise RouteError(f"{remote} was still changing after {timeout:.0f}s")
            previous = data
            time.sleep(LIVE_COPY_INTERVAL)

    def get(self, remote: str, local: pathlib.Path, timeout: float) -> str:
        path = self._staged(remote)
        if self.emulator is not None and self.emulator.poll() is None:
            raise RouteError(f"{remote} is still open in a running emulator; stop it first")
        shutil.copyfile(path, local)
        return f"ok {remote}"

    # -- starting and stopping --------------------------------------------------

    def start(self, holder: str, *drives: str | None, timeout: float,
              options: tuple[str, ...] = (), config: str | None = None, attach: bool = True) -> str:
        """Start the emulator with `drives` in DF0 upward, every other staged disk in the swap list.

        `attach=False` leaves the debugger connection to Wish's helper: the emulator closes its
        listening socket when its client leaves, so this guest must not connect.
        """
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
        self._forget_states()
        self._menu_full = {slot for slot in STATE_SLOTS if self._state_file(slot).exists()}
        self.xvfb, self.emulator = fsuaegdb.start_processes(args, True)
        self._started = time.monotonic()
        try:
            if attach:
                self._attach(timeout)
            self._require_silence(work)
        except BaseException:
            self._take_down()
            raise
        return f"ok pid={self.emulator.pid} display={self.slot.display} port={self.slot.port}"

    def _attach(self, timeout: float) -> None:
        """Connect the debugger, continue the machine, and read the raster as proof it runs."""
        from automap import amiga  # noqa: PLC0415

        end = time.monotonic() + timeout
        while True:
            if self.emulator.poll() is not None:
                raise RouteError("the emulator exited before the debugger connected")
            try:
                self.gdb = amiga.FsuaeGdb(port=self.slot.port, resume=False)
                break
            except (amiga.FsuaeError, OSError) as exc:
                if time.monotonic() >= end:
                    raise RouteError(f"the debugger did not connect within {timeout:.0f}s: {exc}") from exc
                time.sleep(0.5)
        try:
            fsuaegdb.continue_machine(self.gdb)
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

    def _require_running(self, what: str) -> None:
        if self.emulator is not None and self.emulator.poll() is not None:
            raise RouteError(f"no emulator is running to {what}")

    def shot(self, path: pathlib.Path, timeout: float = 30.0) -> None:
        """Copy the emulator's own screenshot (Alt+S) to `path` uncut, as WinUAE's pipe shot is."""
        self._need_slot("shot")
        self._require_running("shoot")
        self._recognised = False
        found = self._shoot(timeout)
        if found is None:
            raise RouteError(f"FS-UAE wrote no screenshot within {timeout:.0f}s")
        self.last_shot = {"source": "fsuae-alt-s", "file": found.name}
        shutil.copyfile(found, path)

    def grab(self, state: str, raw: pathlib.Path, cropped: pathlib.Path, timeout: float) -> bool:
        """One screenshot, cut to the Amiga screen; False while the emulator has drawn nothing yet
        or the frame is not an exact capture (hires), with `raw` kept and no crop."""
        from tools.amiga import fsuaepor  # noqa: PLC0415

        self._need_slot("grab")
        self._require_running(f"grab {state} from")
        self._recognised = False
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
        self.last_shot = {"source": "fsuae-alt-s", "file": path.name}
        shutil.copyfile(path, raw)
        try:
            screens.canonical_file(raw, cropped)
        except screens.NotExactCapture:
            cropped.unlink(missing_ok=True)
            return False
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
        window = fsuaegdb.largest_window(self.slot.display, fsuaepor.find_windows(self.slot.display))
        fsuaepor.keys(argparse.Namespace(display=self.slot.display, key=[keysym],
                                         hold=HOLD, settle=0.0, window=window))
        self._last_key = time.monotonic()

    def note_recognised(self) -> None:
        """The frame on display matched a screen guard, so a key sent to it is not held to the first-key age."""
        self._recognised = True

    def _wait_for_first_key(self, timeout: float) -> None:
        """Hold the first key until the title's emulator age, unless it answers a recognised screen."""
        if self._keyed or self.first_key_after is None:
            return
        wait = self.first_key_after - (time.monotonic() - self._started)
        if wait <= 0:
            self._keyed = True
            return
        if self._recognised:
            return
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
        # The game may leave the recognised screen on this key. The F12 menu keys of `insert`
        # go through `_send` alone and keep the mark: the menu covers the screen without
        # changing it, and the route's key after a swap answers the screen it recognised.
        self._recognised = False
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
        if index == self._drive_zero:
            raise RouteError(f"{remote} is already in DF0")
        recovered = self._recover_menu()
        log = self._log()
        since = log.stat().st_size if log.exists() else 0
        # The swap walk opens the menu on its first key and counts from PAUSE; the return to
        # the top replaces that key, so the walk starts on PAUSE wherever the menu was left.
        sequence = " ".join([*self._top_keys(), fsuaegdb.DEFAULT_SWAP_SEQUENCE.removeprefix("F12 ")])
        _no_return_after_up(sequence.split())
        self._menu_depth = None
        keys = fsuaegdb.insert_floppy(
            sequence, index,
            lambda key: self._send(key), lambda label: time.sleep(SWAP_STEP), self._drive_zero)
        self._menu_depth = 2
        end = time.monotonic() + min(SWAP_LOG_WAIT, timeout)
        while True:
            lines = fsuaegdb.swap_log_lines(log, since)
            if any(_changes_drive_zero_to(line, path) for line in lines):
                self._drive_zero = index
                return {"index": index, "keys": [*recovered, *keys], "log": lines, "staged": str(path),
                        "sha256": digest}
            if time.monotonic() >= end:
                self._menu_depth = None
                error = RouteError(f"the emulator log shows no change to {path} after the swap keys")
                error.receipt = {"index": index, "keys": [*recovered, *keys], "log": lines}
                raise error
            time.sleep(0.5)

    # -- machine states and reset, through the F12 menu -----------------------------------

    def supports(self, kind: str) -> bool:
        """Whether this guest carries out a route step of `kind`."""
        return kind in SUPPORTED_STEPS

    def _log(self) -> pathlib.Path:
        return self._need_slot("read the emulator log") / "base" / "Cache" / "Logs" / "fs-uae.log.txt"

    def _log_size(self) -> int:
        log = self._log()
        return log.stat().st_size if log.exists() else 0

    def _log_since(self, since: int) -> str:
        log = self._log()
        return log.read_bytes()[since:].decode("utf-8", "replace") if log.exists() else ""

    def _state_file(self, slot: int) -> pathlib.Path:
        return self._need_slot("name a state file") / "base" / "Save States" / "Default" / f"FS-UAE_{slot}.uss"

    def _table_path(self) -> pathlib.Path:
        return self._need_slot("read the snapshot table") / "snapshots.json"

    def _table(self) -> dict[str, int]:
        path = self._table_path()
        return json.loads(path.read_text()) if path.exists() else {}

    def _forget_states(self) -> None:
        """Delete the snapshot table, its receipts and the slots' state files an earlier boot left."""
        work = self._need_slot("clear the snapshots")
        self._table_path().unlink(missing_ok=True)
        for slot in STATE_SLOTS:
            (work / f"snapshot-{slot}.json").unlink(missing_ok=True)
            self._state_file(slot).unlink(missing_ok=True)

    def _menu_open_in_log(self) -> bool:
        """Whether the emulator log's last word on the F12 menu is that it opened."""
        text = self._log_since(0)
        return text.rfind(_MENU_OPEN) > text.rfind(_MENU_CLOSE)

    def _recover_menu(self) -> list[str]:
        """After a walk that went wrong, close the menu on its top list so its depth is 1 again.

        The emulator logs every opening and closing of the menu. A closed menu is opened with
        F12; then BackSpace pops one level at a time until the log shows the menu closing, which
        only BackSpace on the top list does, so no BackSpace reaches the game. Returns the keys
        sent, none when the depth is known.
        """
        if self._menu_depth is not None:
            return []
        keys: list[str] = []
        if not self._menu_open_in_log():
            since = self._log_size()
            self._send("F12")
            keys.append("F12")
            if self._await_log(since, lambda t: _MENU_OPEN in t, MENU_LOG_WAIT) is None:
                raise RouteError("the emulator log shows the F12 menu did not open to be closed on its top list")
        for _ in range(MENU_MAX_DEPTH):
            since = self._log_size()
            self._send("BackSpace")
            keys.append("BackSpace")
            if self._await_log(since, lambda t: _MENU_CLOSE in t, MENU_LOG_WAIT) is not None:
                self._menu_depth = 1
                return keys
        raise RouteError(f"the F12 menu was still open after {MENU_MAX_DEPTH} BackSpaces")

    def _top_keys(self) -> list[str]:
        """F12, then back up to the top list and onto PAUSE, from wherever the menu was left.

        BackSpace pops one menu, and on the top list it closes the menu, so the walk sends one
        fewer than the depth; a BackSpace with the menu closed would reach the game.
        """
        if self._menu_depth is None:
            raise RouteError("an F12 menu walk did not finish, so how deep the menu reopens is not known")
        return ["F12", *["BackSpace"] * (self._menu_depth - 1), *["Up"] * MENU_PAST_TOP, "Down"]

    def _walk(self, walk: list[str], depth_after: int) -> list[str]:
        """Send the return to the top, then `walk` from PAUSE; the menu reopens `depth_after` deep."""
        keys = [*self._top_keys(), *walk]
        _no_return_after_up(keys)
        self._menu_depth = None
        for key in keys:
            self._send(key)
            time.sleep(SWAP_STEP)
        self._menu_depth = depth_after
        return keys

    def _await_log(self, since: int, done, timeout: float) -> str | None:
        """The log text after byte `since` once `done(text)` holds, or None at `timeout`."""
        end = time.monotonic() + timeout
        while True:
            text = self._log_since(since)
            if done(text):
                return text
            if time.monotonic() >= end:
                return None
            time.sleep(0.5)

    def _named(self, name: str) -> int:
        try:
            return self._table()[name]
        except KeyError:
            raise RouteError(f"no snapshot is called {name!r}") from None

    def snapshot(self, name: str, holder: str) -> dict[str, Any]:
        """Save the machine state to a savestate slot through the F12 menu, under `name`.

        Proven by the emulator log's `Save of '<file>' complete`. The receipt keeps the keys,
        the log lines, the state file's SHA-256 and the Alt+S frame taken just before the keys.
        """
        self._require_running("save a machine state")
        table = self._table()
        if name in table:
            slot = table[name]
        else:
            free = [s for s in STATE_SLOTS if s not in table.values()]
            if not free:
                raise RouteError(f"all {len(STATE_SLOTS)} savestate slots hold snapshots; discard one first")
            slot = free[0]
        path = self._state_file(slot)
        recovered = self._recover_menu()
        frame = self._shoot(30.0)
        since = self._log_size()
        walk = ["Down", "Down", "Return", *["Down"] * (slot - 1), "Return", "Return"]
        # A state file there means the menu marked the slot when it saved it, even for a save
        # whose log line never came; "Overwrite savestate N?" then opens on Confirm overwrite.
        if slot in self._menu_full or path.exists():
            walk.append("Return")
        keys = [*recovered, *self._walk(walk, 3)]
        markers = {f"Save of '{p}' complete" for p in (path, path.resolve())}
        text = self._await_log(since, lambda t: any(m in t for m in markers), STATE_LOG_WAIT)
        receipt: dict[str, Any] = {"name": name, "slot": slot, "keys": keys,
                                   "frame": None if frame is None else frame.name}
        if text is None:
            receipt["log"] = _state_lines(self._log_since(since))
            self._menu_depth = None
            error = RouteError(f"the emulator log shows no save of {path.name} after the menu keys")
            error.receipt = receipt
            raise error
        self._menu_full.add(slot)
        receipt["log"] = _state_lines(text)
        receipt["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        if frame is not None:
            receipt["frame_sha256"] = hashlib.sha256(frame.read_bytes()).hexdigest()
        table[name] = slot
        self._table_path().write_text(json.dumps(table, indent=1, sort_keys=True))
        (self._table_path().parent / f"snapshot-{slot}.json").write_text(json.dumps(receipt, indent=1))
        return receipt

    def restore(self, name: str, holder: str, fresh: bool = False,
                redraw_keys: tuple[str, ...] = ()) -> dict[str, Any]:
        """Load snapshot `name` through the F12 menu, then wait for the picture to come back.

        Proven by `STATERESTORE: '<file>'` and then `State restored` in the emulator log. The
        guard-only binary leaves the picture black until the game draws again, so the frames
        are read until one is not black; `redraw_keys`, if given, are pressed once the wait runs
        out, for a screen whose own key redraws it. The receipt records `picture_redrawn` and
        whether the frame equals the one taken at the save. `fresh` is WinGuest's argument for a
        machine just booted; the menu walk is the same either way.
        """
        self._require_running("load a machine state")
        slot = self._named(name)
        path = self._state_file(slot)
        if not path.exists():
            raise RouteError(f"snapshot {name!r} has no state file {path.name}")
        recovered = self._recover_menu()
        since = self._log_size()
        keys = [*recovered,
                *self._walk(["Down", "Down", "Return", *["Down"] * (slot - 1), "Return", "Down", "Return"], 3)]
        starts = {f"STATERESTORE: '{p}'" for p in (path, path.resolve())}

        def restored(text: str) -> bool:
            return any(m in text and "State restored" in text[text.index(m):] for m in starts)

        text = self._await_log(since, restored, STATE_LOG_WAIT)
        receipt: dict[str, Any] = {"name": name, "slot": slot, "keys": keys}
        if text is None:
            receipt["log"] = _state_lines(self._log_since(since))
            self._menu_depth = None
            error = RouteError(f"the emulator log shows no load of {path.name} after the menu keys")
            error.receipt = receipt
            raise error
        receipt["log"] = _state_lines(text)
        frame = self._redrawn_frame(REDRAW_WAIT)
        if frame is None and redraw_keys:
            for key in redraw_keys:
                self.press(holder, key, 30.0)
            receipt["redraw_keys"] = list(redraw_keys)
            frame = self._redrawn_frame(REDRAW_WAIT)
        receipt["picture_redrawn"] = frame is not None
        if frame is not None:
            receipt["frame"] = frame.name
            saved = self._receipt_of(slot).get("frame_sha256")
            receipt["matches_snapshot_frame"] = (
                saved is not None and hashlib.sha256(frame.read_bytes()).hexdigest() == saved)
        return receipt

    def _receipt_of(self, slot: int) -> dict[str, Any]:
        path = self._table_path().parent / f"snapshot-{slot}.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def _redrawn_frame(self, timeout: float) -> pathlib.Path | None:
        """The first Alt+S frame within `timeout` that is not the black picture a load leaves."""
        end = time.monotonic() + timeout
        while True:
            frame = self._shoot(max(1.0, end - time.monotonic()))
            if frame is not None and not _is_black(frame):
                return frame
            if time.monotonic() >= end:
                return None
            time.sleep(SETTLE_INTERVAL)

    def discard(self, name: str, holder: str) -> dict[str, Any]:
        """Delete snapshot `name`'s state file and free its slot for another name."""
        table = self._table()
        slot = self._named(name)
        path = self._state_file(slot)
        path.unlink(missing_ok=True)
        del table[name]
        self._table_path().write_text(json.dumps(table, indent=1, sort_keys=True))
        (self._table_path().parent / f"snapshot-{slot}.json").unlink(missing_ok=True)
        return {"name": name, "slot": slot, "deleted": path.name}

    def reset(self, holder: str, timeout: float) -> dict[str, Any]:
        """Soft-reset the Amiga through the F12 menu's RESET and SOFT RESET, as Ctrl-Amiga-Amiga does.

        Proven by a `Reset at ` line in the emulator log with neither a load nor a hard reset
        after the keys. When Wish's connection helper was alive before the reset it must be
        alive after it, since it holds the emulator's one debugger connection.
        """
        self._need_slot("reset")
        self._require_running("reset")
        port = self.slot.port
        helper_before = fsuaegdb.helper_row(port)["alive"]
        recovered = self._recover_menu()
        since = self._log_size()
        keys = [*recovered, *self._walk([*["Down"] * MENU_TO_LAST, "Return", "Return"], 1)]
        text = self._await_log(since, lambda t: _SOFT_RESET.search(t) is not None, min(STATE_LOG_WAIT, timeout))
        receipt: dict[str, Any] = {"keys": keys, "helper_before": helper_before}
        lines = _state_lines(self._log_since(since) if text is None else text)
        receipt["log"] = lines
        if text is None or "STATERESTORE" in text or "hardreset, memory cleared" in text:
            self._menu_depth = None
            error = RouteError("the emulator log shows no soft reset after the menu keys")
            error.receipt = receipt
            raise error
        receipt["helper_after"] = fsuaegdb.helper_row(port)["alive"]
        if helper_before and not receipt["helper_after"]:
            error = RouteError("Wish's connection helper was alive before the reset and is gone after it")
            error.receipt = receipt
            raise error
        return receipt

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


_MENU_OPEN = "[FSE] [OSM] Open on-screen menu"
_MENU_CLOSE = "[FSE] [OSM] Close on-screen menu"
_SOFT_RESET = re.compile(r"^Reset at [0-9A-F]{8}\.", re.MULTILINE)
_STATE_LINE = re.compile(r"^(?:Save of '|STATESAVE |STATERESTORE: |State restored|Reset at |hardreset)")


def _state_lines(text: str) -> list[str]:
    """The log lines that say what a state save, a load or a reset did."""
    return [line for line in text.splitlines() if _STATE_LINE.match(line)]


def _no_return_after_up(keys: list[str]) -> None:
    """RouteError for a walk that presses Return straight after Up, which can quit the emulator."""
    if any(a == "Up" and b == "Return" for a, b in zip(keys, keys[1:])):
        raise RouteError("an F12 menu walk presses Return after Up, where the close button can be")


def _is_black(path: pathlib.Path) -> bool:
    """Whether the frame is the black picture a load leaves (`BLACK_LEVEL`, `BLACK_SHARE`)."""
    from PIL import Image, ImageChops  # noqa: PLC0415

    with Image.open(path) as image:
        red, green, blue = image.convert("RGB").split()
    brightest = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    lit = sum(brightest.histogram()[BLACK_LEVEL + 1:])
    return lit < BLACK_SHARE * brightest.width * brightest.height


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
