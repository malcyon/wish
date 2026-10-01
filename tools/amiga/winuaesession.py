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
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from tools.amiga import amigadrive, amigashots, winvmsettle

BOOT_CONFIG = r"C:\Amiga\configs\goldbox-a500.uae"
LOCAL_BOOT_CONFIG = pathlib.Path(__file__).with_name("goldbox-a500.uae")
WINUAE_PS = r"powershell -NoProfile -ExecutionPolicy Bypass -File C:\Amiga\winuae.ps1"
# One `winvm shot` measured 5.6-7.8 s round trip; the capture script caps itself at 20 s.
SHOT_SECONDS = 20.0
HOLDER = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RouteError(RuntimeError):
    """A source, screen, lane action or fetched image failed its guard."""

class Terminated(BaseException):
    """The wrapper's `timeout` sent SIGTERM; a `BaseException` so a `finally` still runs."""

class WinGuest:
    """One holder's WinUAE commands through the agent guest's `winvm`."""

    def __init__(self) -> None:
        #: The Windows paths this instance copied to the guest; a floppy change may name only these.
        self.staged: set[str] = set()

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
        output = self._run("ssh", f"{WINUAE_PS} {command} -Holder {holder}",
                           timeout=timeout)
        if not output.startswith("ok"):
            raise RouteError(f"winuae.ps1 {command} returned {output!r}")
        return output

    def claim(self, holder: str, timeout: float) -> str:
        return self._lane(holder, "claim", timeout)

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
            raise RouteError("diagnose refused an unapproved read")
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

    def capture(self, state: str, raw: pathlib.Path, cropped: pathlib.Path,
                timeout: float) -> None:
        """Grab until two consecutive crops of the Amiga screen are identical."""
        started, previous, made, shots = time.monotonic(), None, False, 0
        try:
            while True:
                left = timeout - (time.monotonic() - started)
                # A short shot risks a timeout, so only the first one is allowed to be
                # short: a failure capture with little time left must still leave a frame.
                if left <= 0 or (left < SHOT_SECONDS and shots):
                    raise RouteError(f"{state} did not settle inside {timeout:.0f}s")
                allowed = min(SHOT_SECONDS, left)
                made = False
                shots += 1
                self._run("shot", str(raw), "--timeout", str(max(1, int(allowed))),
                          timeout=allowed)
                try:
                    amigashots.crop(raw, cropped)
                except LookupError:
                    # The WinUAE window is not up yet; the desktop is not a screen.
                    previous = None
                else:
                    made = True
                    frame = cropped.read_bytes()
                    if previous == frame:
                        return
                    previous = frame
                left = timeout - (time.monotonic() - started)
                if left > 0:
                    time.sleep(min(winvmsettle.INTERVAL, left))
        finally:
            if not made and raw.exists() and sys.exc_info()[0] is not None:
                try:
                    amigashots.crop(raw, cropped)
                except Exception:
                    pass

    def grab(self, state: str, raw: pathlib.Path, cropped: pathlib.Path,
             timeout: float) -> bool:
        """One grab, cropped to the Amiga screen; False when WinUAE's window is not up.

        A guard reads a static box, so an animated screen needs no settling.
        """
        if timeout <= 0:
            raise RouteError(f"no time left to grab {state}")
        allowed = min(SHOT_SECONDS, timeout)
        self._run("shot", str(raw), "--timeout", str(max(1, int(allowed))),
                  timeout=allowed)
        try:
            amigashots.crop(raw, cropped)
        except LookupError:
            return False
        return True

    def press(self, holder: str, key: str, timeout: float) -> str:
        name = key.upper()
        code = amigadrive.KEYS.get(name)
        if code is None:
            raise RouteError(f"{name} has no WinUAE key code")
        extended = " -Extended" if name in amigadrive.EXTENDED else ""
        return self._lane(holder, f"key {code:02X}{extended}", timeout)

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
            and timedelta() <= age <= timedelta(minutes=5))
