#!/usr/bin/env python3
"""Drive the Windows guest from inside the agent guest, over ssh alone.

On the desktop, `winvm` (installed by `ansible/roles/windows-vm`) drives the
Windows guest through libvirt: it starts and stops it, holds leases on it and
grabs its framebuffer.  None of that exists inside the Ubuntu agent guest, which
has no libvirt and no business with the Windows guest's lifecycle.  The agent
guest reaches Windows over one ssh endpoint instead, with an identity of its own
and a pinned host key (`ansible/roles/agent-winvm-access`), and this is the
`winvm` it runs there:

    winvm ssh 'hostname'                  run a command; PowerShell is the shell
    winvm ps 'Get-Date'                   run PowerShell, sent as -EncodedCommand
    winvm put a.ps1 b.uae C:/Amiga/       copy to Windows
    winvm get C:/Amiga/send.log .         copy from Windows
    winvm scp x win11:C:/Amiga/x          scp with the pinned options
    winvm shot /tmp/win11.png             the console screen, taken on Windows
    winvm status                          reachability, boot time, the WinUAE lane
    winvm lane [--expect HOLDER|free]     who holds the WinUAE lane

`ssh`, `scp` and `shot` take the same arguments as the desktop's `winvm`, so the
tools that call it (`amigadrive.py`, `winvmsettle.py` and the rest) run
unchanged.  `acquire`, `release`, `up`, `down`, `save`, `promote`, `revert` and
`guest-setup` are refused: the Windows guest autostarts with the host and only
the desktop changes its state.  Who may drive WinUAE is decided on Windows, by
`winuae.ps1 claim`, and read here through `winuae.ps1 status`.

The screenshot is taken in the console session (session 1) by a one-off
scheduled task with an Interactive principal, because an ssh login lands in
session 0 and cannot see the screen; the PNG comes back base64-encoded on the
same ssh call and the task and file are removed before it returns.

Every ssh call runs with `BatchMode=yes`, `StrictHostKeyChecking=yes` and
`SSH_ASKPASS_REQUIRE=never`, so a failure is an error on stderr and never a
prompt.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import dataclasses
import os
import pathlib
import re
import secrets
import subprocess
import sys
import tempfile

#: The ssh client configuration the Ansible role writes: host, account,
#: identity and the pinned known_hosts file.  Passed with `-F`, so nothing in
#: the account's own `~/.ssh/config` can loosen it.
DEFAULT_CONFIG = "/etc/ssh/ssh_config.d/wish-winvm.conf"

#: The `Host` name that configuration answers to.
DEFAULT_HOST = "win11"

#: Given on every ssh and scp command line after `-F`, so they hold whatever
#: the configuration file says.
FORCED_OPTIONS = ("-o", "BatchMode=yes",
                  "-o", "StrictHostKeyChecking=yes",
                  "-o", "UpdateHostKeys=no")

#: The WinUAE driver on the Windows guest.
WINUAE_PS1 = r"C:\Amiga\winuae.ps1"

#: How PowerShell is started for anything this sends.  The guest's execution
#: policy is Restricted, so `-ExecutionPolicy Bypass` is needed for `-File`.
POWERSHELL = "powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass"

#: The desktop `winvm` commands that change the Windows guest's state or rely
#: on libvirt, with the reason each is refused here.
REFUSED = {
    "acquire": "leases are libvirt's, on the desktop; take the WinUAE lane "
               "with `winuae.ps1 claim -Holder <id>` instead",
    "release": "leases are libvirt's, on the desktop; give the WinUAE lane "
               "back with `winuae.ps1 release -Holder <id>` instead",
    "up": "the Windows guest autostarts with the host; this tool refuses "
          "to start it",
    "down": "this tool refuses to stop the Windows guest",
    "save": "this tool refuses to suspend the Windows guest",
    "promote": "this tool refuses to change the Windows guest's golden image; "
               "that runs from the desktop",
    "revert": "this tool refuses to revert the Windows guest; that runs "
              "from the desktop",
    "guest-setup": "the first-logon script is re-run from the desktop, "
                   "off the UNATTEND volume",
}

SHOT_BEGIN = "WINVM-SHOT-BEGIN"
SHOT_END = "WINVM-SHOT-END"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

#: A holder name as `winuae.ps1 claim` accepts one.
HOLDER = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class WinvmError(RuntimeError):
    """A failure to report in one line, not as a traceback."""


# -- command lines ------------------------------------------------------------

def ssh_argv(config: str, host: str, command: list[str] | None = None,
             tty: bool = False) -> list[str]:
    """The ssh command line for `command` on the Windows guest."""
    argv = ["ssh", "-F", config, *FORCED_OPTIONS]
    if tty:
        argv.append("-t")
    argv.append(host)
    return argv + list(command or [])


def remote_path(path: str) -> str:
    r"""A Windows path as scp's remote side wants it: `C:\Amiga` -> `C:/Amiga`.

    A backslash is an escape to the shell scp starts on the far side, and a
    forward slash is a separator to Windows, so forward slashes are the one
    spelling that survives both.
    """
    return path.replace("\\", "/")


class ScpArgumentError(WinvmError):
    """A source or target that scp would read as an option."""


def _check_not_option(paths: list[str]) -> None:
    for path in paths:
        if path.startswith("-"):
            raise ScpArgumentError(
                f"'{path}' starts with '-' and scp would read it as an option; "
                "prefix it with './' if that is really the path")


def scp_argv(config: str, sources: list[str], target: str,
             recursive: bool = False) -> list[str]:
    """The scp command line copying `sources` to `target`."""
    _check_not_option([*sources, target])
    argv = ["scp", "-F", config, *FORCED_OPTIONS]
    if recursive:
        argv.append("-r")
    return argv + ["--"] + list(sources) + [target]


def put_argv(config: str, host: str, sources: list[str], remote: str,
             recursive: bool = False) -> list[str]:
    """scp from this guest to `remote` on Windows."""
    if not sources:
        raise WinvmError("put needs at least one local file and a remote path")
    return scp_argv(config, sources, f"{host}:{remote_path(remote)}", recursive)


def get_argv(config: str, host: str, remote: str, local: str,
             recursive: bool = False) -> list[str]:
    """scp from `remote` on Windows to `local` in this guest."""
    return scp_argv(config, [f"{host}:{remote_path(remote)}"], local, recursive)


def encode_powershell(script: str) -> str:
    """`script` as PowerShell's `-EncodedCommand` wants it: UTF-16LE, base64.

    Nothing in it is quoted by bash, ssh or the PowerShell login shell on the
    far side, which is what a script passed as text runs into -- that shell
    expands `$name` inside double quotes before the inner PowerShell sees it.
    """
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def powershell_command(script: str) -> str:
    """The one-line command that runs `script` on the Windows guest."""
    return f"{POWERSHELL} -EncodedCommand {encode_powershell(script)}"


# -- the screenshot -----------------------------------------------------------

def _ps_quote(text: str) -> str:
    """`text` as a single-quoted PowerShell string."""
    return "'" + text.replace("'", "''") + "'"


def capture_script(out: str) -> str:
    """What the session 1 task runs: grab the whole desktop into `out`.

    DPI-aware, so a scaled display is captured at its real pixel size and the
    grab has the same pitch as the framebuffer `winvm shot` reads on the
    desktop.  The short sleep lets the task's own hidden console go away before
    the grab.  Written under a temporary name and renamed, so the poller never
    reads half a PNG.
    """
    tmp = out + ".tmp"
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        "Add-Type -AssemblyName System.Windows.Forms, System.Drawing",
        "Add-Type -Namespace WishShot -Name Dpi -MemberDefinition "
        "'[DllImport(\"user32.dll\")] public static extern bool SetProcessDPIAware();'",
        "[void][WishShot.Dpi]::SetProcessDPIAware()",
        "Start-Sleep -Milliseconds 400",
        "$b = [System.Windows.Forms.SystemInformation]::VirtualScreen",
        "$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height",
        "$g = [System.Drawing.Graphics]::FromImage($bmp)",
        "$g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)",
        f"$bmp.Save({_ps_quote(tmp)}, [System.Drawing.Imaging.ImageFormat]::Png)",
        "$g.Dispose(); $bmp.Dispose()",
        f"Move-Item -Force {_ps_quote(tmp)} {_ps_quote(out)}",
    ])


def shot_script(token: str, timeout: int = 20) -> str:
    """What the ssh session runs: start the capture in session 1, return it.

    `token` names the task and the file, so two agents taking a screenshot at
    once do not collide.  The task and the file are removed whatever happens.
    """
    if not re.fullmatch(r"[A-Za-z0-9]{1,32}", token):
        raise WinvmError(f"not a usable token: {token!r}")
    task = f"winvm-shot-{token}"
    out = rf"C:\Users\Public\{task}.png"
    inner = encode_powershell(capture_script(out))
    args = f"-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -EncodedCommand {inner}"
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        f"$task = {_ps_quote(task)}",
        f"$out = {_ps_quote(out)}",
        "Remove-Item $out, \"$out.tmp\" -ErrorAction SilentlyContinue",
        f"$a = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument {_ps_quote(args)}",
        "$p = New-ScheduledTaskPrincipal -UserId \"$env:COMPUTERNAME\\$env:USERNAME\" -LogonType Interactive",
        "$s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2) "
        "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries",
        "Register-ScheduledTask -TaskName $task -Action $a -Principal $p -Settings $s -Force | Out-Null",
        "try {",
        "  Start-ScheduledTask -TaskName $task",
        f"  $deadline = (Get-Date).AddSeconds({int(timeout)})",
        "  while (-not (Test-Path $out) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 200 }",
        "  if (-not (Test-Path $out)) {",
        "    $info = Get-ScheduledTaskInfo -TaskName $task",
        "    $why = ''",
        # 0x41303: the task never ran, which is what an Interactive principal
        # reports when nobody is logged on at the console.
        "    if ($info.LastTaskResult -eq 267011) { $why = ' -- nobody is logged on at the console, so an Interactive task cannot run' }",
        f"    'fail no screenshot after {int(timeout)}s; lastResult=0x' + ('{{0:X}}' -f $info.LastTaskResult) + $why",
        "    exit 1",
        "  }",
        f"  '{SHOT_BEGIN}'",
        "  [Convert]::ToBase64String([IO.File]::ReadAllBytes($out), 'InsertLineBreaks')",
        f"  '{SHOT_END}'",
        "} finally {",
        "  Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue",
        "  Remove-Item $out, \"$out.tmp\" -ErrorAction SilentlyContinue",
        "}",
    ])


def decode_shot(output: str) -> bytes:
    """The PNG between the markers in the shot script's output."""
    lines = [line.strip() for line in output.splitlines()]
    try:
        start = lines.index(SHOT_BEGIN)
        end = lines.index(SHOT_END, start + 1)
    except ValueError:
        fail = next((line for line in lines if line.startswith("fail")), "")
        raise WinvmError(fail or "the screenshot came back without its markers: "
                         + (output.strip()[:200] or "no output")) from None
    try:
        data = base64.b64decode("".join(lines[start + 1:end]), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise WinvmError(f"the screenshot's base64 does not decode: {exc}") from None
    if not data.startswith(PNG_SIGNATURE):
        raise WinvmError("the screenshot is not a PNG")
    return data


# -- status and the WinUAE lane -----------------------------------------------

def status_script() -> str:
    """The guest's name, account and boot time, then `winuae.ps1 status`."""
    return "\n".join([
        "\"host=$env:COMPUTERNAME\"",
        "\"user=$env:USERNAME\"",
        "\"boot=\" + (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString('o')",
        f"if (Test-Path {_ps_quote(WINUAE_PS1)}) {{",
        f"  & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File {_ps_quote(WINUAE_PS1)} status",
        "} else { 'driver=absent' }",
    ])


@dataclasses.dataclass
class Status:
    """What `status_script` printed, read back."""

    host: str = ""
    user: str = ""
    boot: str = ""
    driver: bool = True
    holder: str | None = None
    since: str = ""
    run: str = ""
    emulators: list[str] = dataclasses.field(default_factory=list)
    other: list[str] = dataclasses.field(default_factory=list)

    @property
    def lane(self) -> str:
        """The lane in one line."""
        if not self.driver:
            return f"unknown: {WINUAE_PS1} is not on the Windows guest"
        if self.holder is None:
            return "free"
        return f"held by {self.holder} since {self.since}"


_CLAIM = re.compile(r"^claim\s*=\s*(?P<holder>\S+)(?:\s+since\s+(?P<since>.*))?$")
_RUN = re.compile(r"^run\s*=\s*(?P<run>.*)$")


def parse_status(text: str) -> Status:
    """Read `status_script`'s output, `winuae.ps1 status` included.

    A claim line that is missing altogether leaves the driver's answer unknown,
    which is reported as a driver that did not answer rather than a free lane.
    """
    st = Status()
    saw_claim = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line == "driver=absent":
            st.driver = False
        elif line.startswith(("host=", "user=", "boot=")):
            key, _, value = line.partition("=")
            setattr(st, key, value)
        elif (m := _CLAIM.match(line)):
            saw_claim = True
            holder = m.group("holder")
            if holder != "none":
                st.holder, st.since = holder, (m.group("since") or "").strip()
        elif (m := _RUN.match(line)):
            st.run = m.group("run").strip()
        elif line.startswith("pid="):
            st.emulators.append(line)
        else:
            st.other.append(line)
    if st.driver and not saw_claim:
        raise WinvmError("winuae.ps1 status printed no claim line, so the lane "
                         "is unknown: " + (text.strip()[:200] or "no output"))
    return st


def lane_matches(st: Status, expect: str) -> bool:
    """True when the lane is `expect`: a holder's name, or `free`."""
    if not st.driver:
        return False
    if expect == "free":
        return st.holder is None
    return st.holder == expect


# -- running it ----------------------------------------------------------------

def _env() -> dict[str, str]:
    return dict(os.environ, SSH_ASKPASS_REQUIRE="never")


def _run(argv: list[str], capture: bool = False,
         stdin=None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, env=_env(), text=True, stdin=stdin,
                              capture_output=capture)
    except FileNotFoundError as exc:
        raise WinvmError(f"{argv[0]} is not installed: {exc}") from None


def _remote(config: str, host: str, script: str) -> subprocess.CompletedProcess:
    proc = _run(ssh_argv(config, host, [powershell_command(script)]),
                capture=True, stdin=subprocess.DEVNULL)
    if proc.returncode == 255:
        raise WinvmError("ssh to the Windows guest failed: "
                         + (proc.stderr.strip() or "exit 255"))
    return proc


def take_shot(config: str, host: str, out: pathlib.Path,
              timeout: int = 20) -> int:
    """Grab the console screen into `out`.  Returns its size in bytes."""
    proc = _remote(config, host, shot_script(secrets.token_hex(6), timeout))
    data = decode_shot(proc.stdout)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=out.parent, delete=False,
                                     prefix=f".{out.name}.") as fh:
        fh.write(data)
    os.replace(fh.name, out)
    return len(data)


def read_status(config: str, host: str) -> Status:
    proc = _remote(config, host, status_script())
    if proc.returncode != 0:
        raise WinvmError("the status script failed on the Windows guest: "
                         + (proc.stderr.strip() or proc.stdout.strip()))
    return parse_status(proc.stdout)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="winvm", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=os.environ.get(
        "WINVM_SSH_CONFIG", DEFAULT_CONFIG),
        help=f"ssh client configuration (default {DEFAULT_CONFIG}, "
             "or $WINVM_SSH_CONFIG)")
    parser.add_argument("--host", default=os.environ.get(
        "WINVM_HOST", DEFAULT_HOST),
        help=f"its Host name (default {DEFAULT_HOST}, or $WINVM_HOST)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ssh", help="run a command on Windows, or log in")
    p.add_argument("command", nargs=argparse.REMAINDER)

    p = sub.add_parser("ps", help="run a PowerShell script, - for stdin")
    p.add_argument("script")

    p = sub.add_parser("put", help="copy files to Windows")
    p.add_argument("-r", "--recursive", action="store_true")
    p.add_argument("paths", nargs="+", metavar="PATH",
                   help="local files, then the remote path")

    p = sub.add_parser("get", help="copy a file from Windows")
    p.add_argument("-r", "--recursive", action="store_true")
    p.add_argument("remote")
    p.add_argument("local")

    p = sub.add_parser("scp", help="scp with the pinned options; "
                       "the remote side is HOST:PATH")
    p.add_argument("args", nargs=argparse.REMAINDER)

    p = sub.add_parser("shot", help="screenshot of the console session")
    p.add_argument("file", nargs="?",
                   default=os.path.join(tempfile.gettempdir(), "win11.png"))
    p.add_argument("--timeout", type=int, default=20,
                   help="seconds to wait for the capture (default 20)")

    sub.add_parser("status", help="reachability, boot time and the WinUAE lane")

    p = sub.add_parser("lane", help="who holds the WinUAE lane")
    p.add_argument("--expect", metavar="HOLDER|free",
                   help="exit 1 unless the lane is held by HOLDER, or free")

    for name, why in REFUSED.items():
        p = sub.add_parser(name, help=f"refused here: {why}")
        p.add_argument("rest", nargs="*", help=argparse.SUPPRESS)
    return parser


def _split_scp_argv(argv: list[str]) -> tuple[list[str], list[str] | None]:
    """`argv` split at a bare `scp`, so its own arguments never reach argparse.

    `argparse.REMAINDER` mis-parses a `scp` argument that starts with `-` as
    an unrecognized option of the top-level parser rather than as part of the
    positional -- a known argparse limitation -- which would let a source or
    target such as `-oProxyCommand=x` escape `scp_argv`'s own check by
    failing earlier, for the wrong reason. Splitting `scp` out by hand keeps
    every one of its arguments, however they are spelled, in the list that
    `scp_argv` checks.
    """
    i = 0
    while i < len(argv):
        if argv[i] in ("--config", "--host"):
            i += 2
            continue
        if argv[i] == "scp":
            return argv[:i + 1], argv[i + 1:]
        i += 1
    return argv, None


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    before_scp, scp_rest = _split_scp_argv(raw)
    args = _parser().parse_args(before_scp)
    if scp_rest is not None:
        args.args = scp_rest
    cfg, host = args.config, args.host
    try:
        if args.cmd in REFUSED:
            print(f"winvm {args.cmd}: not available in the agent guest -- "
                  f"{REFUSED[args.cmd]}.", file=sys.stderr)
            return 2
        if args.cmd == "ssh":
            tty = not args.command and sys.stdin.isatty()
            return _run(ssh_argv(cfg, host, args.command, tty=tty)).returncode
        if args.cmd == "ps":
            script = sys.stdin.read() if args.script == "-" else args.script
            return _run(ssh_argv(cfg, host, [powershell_command(script)]),
                        stdin=subprocess.DEVNULL).returncode
        if args.cmd == "put":
            if len(args.paths) < 2:
                raise WinvmError("put needs at least one local file and a remote path")
            return _run(put_argv(cfg, host, args.paths[:-1], args.paths[-1],
                                 args.recursive)).returncode
        if args.cmd == "get":
            return _run(get_argv(cfg, host, args.remote, args.local,
                                 args.recursive)).returncode
        if args.cmd == "scp":
            if not args.args:
                raise WinvmError("scp needs its arguments")
            try:
                argv = scp_argv(cfg, args.args[:-1], args.args[-1])
            except ScpArgumentError as exc:
                print(f"winvm: {exc}", file=sys.stderr)
                return 2
            return _run(argv).returncode
        if args.cmd == "shot":
            size = take_shot(cfg, host, pathlib.Path(args.file), args.timeout)
            print(f"{args.file} ({size} bytes)")
            return 0
        st = read_status(cfg, host)
        if args.cmd == "status":
            print(f"windows: {st.host} as {st.user}, booted {st.boot}")
            print(f"lane:    {st.lane}")
            print(f"run:     {st.run or 'none'}")
            print(f"winuae:  {len(st.emulators)} running")
            for line in st.emulators + st.other:
                print(f"  {line}")
            return 0
        print(st.lane)
        if args.expect is not None:
            if args.expect != "free" and not HOLDER.match(args.expect):
                raise WinvmError(f"'{args.expect}' is not a holder name winuae.ps1 accepts")
            return 0 if lane_matches(st, args.expect) else 1
        return 0
    except WinvmError as exc:
        print(f"winvm: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
