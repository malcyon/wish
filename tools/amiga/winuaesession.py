"""The WinUAE lane session: `winvm` commands, key presses, screen captures and the SIGTERM handling around a run."""

from __future__ import annotations

import base64
import binascii
import contextlib
import hashlib
import json
import os
import pathlib
import re
import signal
import subprocess
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from tools.amiga import amigadrive, amigakeys

BOOT_CONFIG = r"C:\Amiga\configs\goldbox-a500.uae"
LOCAL_BOOT_CONFIG = pathlib.Path(__file__).with_name("goldbox-a500.uae")
WINUAE_PS = r"powershell -NoProfile -ExecutionPolicy Bypass -File C:\Amiga\winuae.ps1"
# The longest one `winuae.ps1 shot` round trip may take before it is cut off.
SHOT_SECONDS = 20.0
# Seconds between two calls of a waiting `claim -Exclusive -Wait`.
CLAIM_POLL_SECONDS = 5.0
# The reservation lasts this long after each poll, so a waiter that dies frees the lanes
# within it; it must exceed one call plus one poll interval.
RESERVATION_LEASE_SECONDS = 180
EXCLUSIVE_WAITING = "fail an exclusive claim"
# What an ordinary `claim` prints when it cannot have a lane yet: every lane held, or an
# exclusive reservation waiting. Anything else it prints is a real failure.
LANE_BUSY = ("one Amiga lane at a time", "every Amiga lane is in use",
             "reserved for an exclusive claim")
SSH_FAILED = "winvm ssh failed: "
HOLDER = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RouteError(RuntimeError):
    """A source, screen, lane action or fetched image failed its guard."""

class Terminated(BaseException):
    """The wrapper's `timeout` sent SIGTERM; a `BaseException` so a `finally` still runs."""

class WinGuest:
    """One holder's WinUAE commands through the agent guest's `winvm`."""

    can_snapshot = True

    def __init__(self) -> None:
        #: The Windows paths this instance copied to the guest; a floppy change may name only these.
        self.staged: set[str] = set()
        self._pipe: Any = None
        #: The lane holder of the last lane action; the screenshot verb is claim-checked and `grab` takes none.
        self.holder: str | None = None
        #: Where the last frame came from: `source`, the emulator `pid` and WinUAE's shot `counter`.
        self.last_shot: dict[str, Any] | None = None

    @staticmethod
    def remote_path(issue: str, holder: str, key: str) -> str:
        """Where the guest keeps disk `key` of `holder`'s run for ticket `issue`."""
        return f"C:/Amiga/Disks/wish{issue}-{holder}-{key}.adf"

    @staticmethod
    def silence(proof: pathlib.Path | None) -> bool:
        """Whether the Windows VM's audio endpoint was read back muted in the last five minutes."""
        return proof is not None and _mute_proof(pathlib.Path(proof))

    def _machine(self) -> Any:
        if self._pipe is None:
            from automap import amiga  # noqa: PLC0415

            self._pipe = amiga.WinuaePipe()
        return self._pipe

    def snapshot(self, name: str, holder: str) -> Any:
        """Save the whole running machine under `name` through WinUAE's pipe."""
        return self._machine().snapshot(name, holder)

    def restore(self, name: str, holder: str, fresh: bool = False) -> Any:
        """Put the machine back as snapshot `name` left it; `fresh` for a machine just booted."""
        return self._machine().restore(name, holder, fresh=fresh)

    def stage_snapshot(self, name: str, holder: str, sha256: str, count: int) -> Any:
        """Install the state file put for `holder` as snapshot `name`, with no emulator running."""
        return self._machine().stage_snapshot(name, holder, sha256, count)

    def drives(self, holder: str) -> Any:
        """What each drive holds, read through WinUAE's pipe."""
        return self._machine().drives(holder)

    def discard(self, name: str, holder: str) -> Any:
        """Delete snapshot `name`."""
        return self._machine().discard_snapshot(name, holder)

    def answer_io(self, holder: str, settle: float = 1.0) -> tuple[Any, Any]:
        """The `(capture, press)` pair the journal answerer reads and types with."""
        def capture(path: pathlib.Path) -> None:
            self._take(holder, path, path, SHOT_SECONDS)

        def press(key: str) -> None:
            amigadrive.press(holder, key, settle)

        return capture, press

    @staticmethod
    def _run(*args: str, timeout: float) -> str:
        proc = subprocess.Popen(
            ["winvm", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
            env=dict(os.environ, SSH_ASKPASS_REQUIRE="never"))
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.communicate()
            raise RouteError(f"winvm {args[0]} exceeded its {timeout:.1f}s limit") from exc
        output = (stdout + stderr).strip()
        if proc.returncode:
            raise RouteError(f"winvm {args[0]} failed: {output}")
        return output

    def _lane(self, holder: str, command: str, timeout: float) -> str:
        self.holder = holder
        output = self._run("ssh", f"{WINUAE_PS} {command} -Holder {holder}",
                           timeout=timeout)
        if not output.startswith("ok"):
            raise RouteError(f"winuae.ps1 {command} returned {output!r}")
        return output

    def claim(self, holder: str, timeout: float, exclusive: bool = False,
              wait: float = 0.0) -> str:
        """Claim a lane; `exclusive` takes every lane, for work that needs the whole desktop.

        With `wait` seconds the claim is asked again every `CLAIM_POLL_SECONDS` while the guest
        says no lane is free or an exclusive reservation is waiting; any other failure raises
        at once, and on the deadline the error names the guest's last line.
        """
        command = "claim -Exclusive" if exclusive else "claim"
        if wait <= 0 or exclusive:
            return self._claim_once(holder, command, timeout)
        deadline = time.monotonic() + wait
        while True:
            try:
                return self._claim_once(holder, command, timeout)
            except RouteError as exc:
                last = str(exc)
                if not any(busy in last for busy in LANE_BUSY):
                    raise
            if time.monotonic() >= deadline:
                raise RouteError(f"no lane within {wait:.0f}s: {last}")
            time.sleep(CLAIM_POLL_SECONDS)

    def _claim_once(self, holder: str, command: str, timeout: float) -> str:
        """One claim call; any failure but a busy line releases the holder before it propagates.

        The guest may have granted the lane and lost the reply (a timeout, an interrupt), and
        the caller never learns it holds one. The guest's `release` checks the holder, so this
        cannot free another runner's lane.
        """
        try:
            return self._lane(holder, command, timeout)
        except RouteError as exc:
            if not any(busy in str(exc) for busy in LANE_BUSY):
                self._release_quietly(holder, timeout)
            raise
        except BaseException:
            self._release_quietly(holder, timeout)
            raise

    def _release_quietly(self, holder: str, timeout: float) -> None:
        with contextlib.suppress(Exception):
            self.release(holder, timeout)

    def claim_every_lane(self, holder: str, timeout: float, wait: float) -> str:
        """Reserve and take every lane, polling the guest for up to `wait` seconds.

        The guest exits 1 while another holder's reservation is waiting; that is polled
        again. The reservation lasts `RESERVATION_LEASE_SECONDS` after each poll.

        The guest's `claim -Exclusive -Wait` keeps each lane it takes and blocks ordinary
        claims meanwhile, so lanes other runners free are not taken again before this
        holder has all of them. On the deadline the reservation is released.
        """
        self.holder = holder
        deadline = time.monotonic() + wait
        last = ""
        try:
            while True:
                lease = max(1, int(min(wait, RESERVATION_LEASE_SECONDS)))
                try:
                    last = self._run(
                        "ssh", f"{WINUAE_PS} claim -Exclusive -Wait {lease} -Holder {holder}",
                        timeout=timeout)
                except RouteError as exc:
                    if not str(exc).startswith(SSH_FAILED + EXCLUSIVE_WAITING):
                        raise
                    last = str(exc)[len(SSH_FAILED):]
                if last.startswith("ok"):
                    return last
                if not last.startswith(("wait", EXCLUSIVE_WAITING)):
                    raise RouteError(f"winuae.ps1 claim -Exclusive -Wait returned {last!r}")
                if time.monotonic() >= deadline:
                    raise RouteError(f"no exclusive claim within {wait:.0f}s: {last}")
                time.sleep(CLAIM_POLL_SECONDS)
        except BaseException:
            # The lanes taken so far and the reservation are held in the guest, so every way
            # out that is not success, an interrupt included, gives them back.
            with contextlib.suppress(RouteError):
                self.release(holder, timeout)
            raise

    def lane(self, holder: str, timeout: float) -> int:
        """The lane number `holder`'s running emulator is in, from the `lane` verb."""
        receipt = self._lane(holder, "lane", timeout)
        found = re.match(r"ok lane=(\d+) ", receipt + " ")
        if not found:
            raise RouteError(f"winuae.ps1 lane names no lane: {receipt!r}")
        return int(found.group(1))

    def release_other_lanes(self, holder: str, keep: int, timeout: float) -> list[int]:
        """Release every lane `holder` holds except `keep`; lanes held by anyone else stay.

        The lanes come from the guest's `status` lines (`claim = H since ...` is lane 1,
        `claim N = H since ...` is lane N), and each is released with `-Lane N`, which
        frees that lane alone. Returns the lanes freed.
        """
        freed = []
        for line in self.status(timeout).splitlines():
            found = re.match(r"\s*claim(?: (\d+))? = (\S+) since ", line)
            if not found or found.group(2) != holder:
                continue
            number = int(found.group(1) or 1)
            if number == keep:
                continue
            self._lane(holder, f"release -Lane {number}", timeout)
            freed.append(number)
        return freed

    def put(self, local: pathlib.Path, remote: str, timeout: float) -> str:
        receipt = self._run("put", str(local), remote, timeout=timeout)
        self.staged.add(remote.replace("/", "\\"))
        return receipt

    def start(self, holder: str, *drives: str | None, timeout: float,
              options: tuple[str, ...] = (), config: str = BOOT_CONFIG) -> str:
        """Start WinUAE with `drives` in DF0 upward; None ejects a drive the template fills."""
        settings = [f"-s floppy{n}=" + ("" if path is None else path.replace("/", "\\"))
                    for n, path in enumerate(drives)]
        settings += [f"-s {option}" for option in options]
        settings += ["-s joyport1=none", "-s sound_output=interrupts"]
        if config != BOOT_CONFIG and config != self.private_config_path(holder):
            raise RouteError("start config is not this holder's private config")
        return self._lane(holder, f"start -f {config} {' '.join(settings)}", timeout)

    @staticmethod
    def private_config_path(holder: str) -> str:
        if not HOLDER.fullmatch(holder):
            raise RouteError("private config needs a lane-safe holder")
        return rf"C:\Amiga\configs\wish705-{holder}.uae"

    def stage_private_config(self, holder: str, timeout: float) -> dict[str, str]:
        remote = self.private_config_path(holder)
        local_hash = hashlib.sha256(LOCAL_BOOT_CONFIG.read_bytes()).hexdigest()
        self.put(LOCAL_BOOT_CONFIG, remote, timeout)
        receipt = self._lane(holder, f"config-hash {remote}", timeout)
        if receipt != f"ok {local_hash}":
            raise RouteError(f"private config guest SHA-256 mismatch: {receipt!r}")
        return {"path": remote, "sha256": local_hash, "receipt": receipt}

    def remove_private_config(self, holder: str, timeout: float) -> str:
        return self._lane(holder, f"config-remove {self.private_config_path(holder)}", timeout)

    def diagnose(self, holder: str, section: str, key: str,
                 timeout: float, address: int | None = None) -> dict[str, Any]:
        if (section, key) not in {("CFG", "gfx_api"), ("CFG", "floppy0"),
                                  ("CFG", "floppy1"), ("DBG", "c"), ("DBG", "m")}:
            raise RouteError("diagnose blocked an unapproved read")
        if (section, key) == ("DBG", "m"):
            if address is None or not 0 <= address <= 0xFFFFFFFF:
                raise RouteError("diagnose memory address is outside 32 bits")
            command = f"diagnose DBG m {address:x}"
        elif address is None:
            command = f"diagnose {section} {key}"
        else:
            raise RouteError("diagnose address belongs only to DBG m")
        raw = self._lane(holder, command, timeout)
        lines = raw.splitlines()
        replies = [line.split(" ", 4)[4] for line in lines if line.startswith("<<r>> ")]
        pids = [line.split(" ", 1)[1] for line in lines if line.startswith("<<pid>> ")]
        servers = [line.split(" ", 1)[1] for line in lines if line.startswith("<<server_pid>> ")]
        if len(replies) != 1 or len(pids) != 1 or servers != pids:
            raise RouteError(f"diagnose returned incomplete ownership proof: {raw!r}")
        try:
            reply = base64.b64decode(replies[0], validate=True).rstrip(b"\0").decode("latin-1")
        except (ValueError, UnicodeError, binascii.Error) as exc:
            raise RouteError("diagnose returned an invalid pipe reply") from exc
        return {"query": command, "pid": int(pids[0]), "reply": reply, "raw": raw}

    def status(self, timeout: float) -> str:
        return self._run("ssh", f"{WINUAE_PS} status", timeout=timeout)

    def insert(self, holder: str, drive: int, remote: str, timeout: float,
               sha256: str) -> dict[str, Any]:
        """Put the staged disk at `remote` in DF0 or DF1 of the running game and prove it went in.

        The pipe's guest verb checks this holder's claim and emulator before it sends, and
        `sha256` is the staged file's hash from the manifest. A rejection or an unproved
        change raises `RouteError` carrying the raw replies as `.receipt`; the caller sends
        no key after one.
        """
        from automap.amiga import FloppyError, WinuaePipe  # noqa: PLC0415

        try:
            return WinuaePipe(timeout=timeout).insert_floppy(
                drive, remote.replace("/", "\\"), holder, sha256,
                staged=self.staged).as_dict()
        except FloppyError as exc:
            error = RouteError(str(exc))
            error.receipt = exc.receipt
            raise error from exc

    def _take(self, holder: str, raw: pathlib.Path, cropped: pathlib.Path, allowed: float) -> None:
        """WinUAE's own frame into `raw` and its Amiga screen into `cropped`."""
        # Imported here because `screens` imports `RouteError` from this module.
        from tools.amiga import screens  # noqa: PLC0415

        try:
            info = amigadrive.shot(holder, raw, run=self._run, timeout=allowed)
        except amigadrive.ShotError as exc:
            raise RouteError(str(exc)) from exc
        self.last_shot = {"source": "winuae-pipe", "pid": info["pid"], "counter": info["counter"]}
        screens.canonical_file(raw, cropped)

    def _holder(self) -> str:
        if self.holder is None:
            raise RouteError("no lane holder is known yet; claim the lane before taking a screenshot")
        return self.holder

    def capture(self, state: str, raw: pathlib.Path, cropped: pathlib.Path,
                timeout: float) -> None:
        """Grab until two consecutive crops of the Amiga screen are identical."""
        started, previous, shots = time.monotonic(), None, 0
        holder = self._holder()
        while True:
            left = timeout - (time.monotonic() - started)
            # A short shot risks a timeout, so only the first one is allowed to be
            # short: a failure capture with little time left must still leave a frame.
            if left <= 0 or (left < SHOT_SECONDS and shots):
                raise RouteError(f"{state} did not settle inside {timeout:.0f}s")
            shots += 1
            self._take(holder, raw, cropped, min(SHOT_SECONDS, left))
            frame = cropped.read_bytes()
            if previous == frame:
                return
            previous = frame

    def grab(self, state: str, raw: pathlib.Path, cropped: pathlib.Path,
             timeout: float) -> bool:
        """One grab, cut to the Amiga screen; False, with `raw` kept and no crop, for a frame
        that is not an exact capture, such as the hires AmigaDOS window while a disk loads.

        A guard reads a static box, so an animated screen needs no settling, and a frame
        with no crop is one no guard can match.
        """
        # Imported here because `screens` imports `RouteError` from this module.
        from tools.amiga import screens  # noqa: PLC0415

        if timeout <= 0:
            raise RouteError(f"no time left to grab {state}")
        try:
            self._take(self._holder(), raw, cropped, min(SHOT_SECONDS, timeout))
        except screens.NotExactCapture:
            cropped.unlink(missing_ok=True)
            return False
        return True

    def press(self, holder: str, key: str, timeout: float) -> str:
        try:
            row = amigakeys.lookup(key)
        except KeyError:
            raise RouteError(f"{key.upper()} has no Amiga key code") from None
        if row.amiga is None:
            raise RouteError(f"{row.name} is an emulator key ({row.host}), not an Amiga key")
        return self._lane(holder, f"press {row.amiga:02X}", timeout)

    def stop(self, holder: str, timeout: float) -> str:
        return self._lane(holder, "stop", timeout)

    def get(self, remote: str, local: pathlib.Path, timeout: float) -> str:
        return self._run("get", remote, str(local), timeout=timeout)

    def release(self, holder: str, timeout: float) -> str:
        return self._lane(holder, "release", timeout)

def _terminate(signum, frame):
    raise Terminated(f"signal {signum}")

@contextlib.contextmanager
def terminating():
    """SIGTERM raises `Terminated`, so a wrapper's `timeout` still reaches `run_recon`'s `finally`."""
    previous = signal.signal(signal.SIGTERM, _terminate)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)

# The Windows VM's clock reads this far ahead of the agent VM's, so a fresh readback has a small negative age.
MUTE_CLOCK_TOLERANCE = timedelta(seconds=5)


def _mute_proof(path: pathlib.Path) -> bool:
    """Require a recent UTC readback of the Windows VM's muted endpoint."""
    try:
        proof = json.loads(path.read_text())
        observed = datetime.fromisoformat(proof["observed_utc"].replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - observed
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        return False
    return (proof.get("vm") == "WIN11-DEV" and proof.get("muted") is True
            and proof.get("readback") is True
            and proof.get("method") == "Windows Core Audio endpoint mute readback"
            and isinstance(proof.get("endpoint_id"), str)
            and bool(proof["endpoint_id"].strip())
            and observed.utcoffset() == timedelta(0)
            and -MUTE_CLOCK_TOLERANCE <= age <= timedelta(minutes=5))
