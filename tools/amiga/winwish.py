#!/usr/bin/env python3
"""Run the frozen Windows build of Wish beside WinUAE in the Windows VM's desktop session.

The Windows guest has no Python, so the real window is the `frozen-windows`
artifact that `.github/workflows/release.yml` builds for a pushed SHA.  This
fetches it with `gh`, copies it to `C:\\Amiga\\wish\\<sha>\\`, starts `wish.exe`
through an Interactive scheduled task (an ssh login is session 0 and cannot show a
window; see `winuae.ps1`), grabs the Wish window, stops and restarts it, and brings
the debug log back.  WinUAE itself is started through `winuaesession.WinGuest`, so
the lane claim, the audio proof and the receipts are the ones every other WinUAE
run uses.

    winwish.py fetch  --sha SHA
    winwish.py up     --sha SHA --holder H --mute-proof FILE --df0 C:\\Amiga\\Disks\\a.adf
    winwish.py shot   --holder H --window wish --out wish.png
    winwish.py restart --holder H
    winwish.py log    --holder H --out DIR
    winwish.py down   --holder H

Wish runs with `WISH_EXPERIMENTAL_AMIGA_WINUAE=1` (`--no-flag` leaves it unset, for
the control) and `WISH_DEBUG=1`.  Its `APPDATA` and `LOCALAPPDATA` point at a
private folder per holder, seeded with `diagnostics: true` because `WISH_DEBUG`
alone does not open the log file.  Every guest call goes through `winvm`, which
sets `BatchMode` and `SSH_ASKPASS_REQUIRE`, so a failure is an error, never a prompt.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import os
import pathlib
import re
import secrets
import signal
import subprocess
import sys
import tempfile
from typing import Any, Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.amiga import winvmguest  # noqa: E402
from tools.amiga.winuaesession import (  # noqa: E402
    RouteError,
    WinGuest,
    _mute_proof,
    terminating,
)
from tools.registry import scratch  # noqa: E402

ROOT = r"C:\Amiga\wish"
ARTIFACT = "frozen-windows"
WORKFLOW = "release.yml"
FLAG = "WISH_EXPERIMENTAL_AMIGA_WINUAE"
HOLDER = winvmguest.HOLDER
#: DF0 and DF1 hold a title's game disks; Wish reads its maps from those. DF2 and up
#: are the save disk and extras, which the game writes and Wish never reads maps from.
GAME_DISKS = 2
GAME_KEY = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SHA = re.compile(r"^[0-9a-fA-F]{7,40}$")
#: Seconds for one guest call; a download or an unzip is the slow one.
CALL_SECONDS = 60.0
COPY_SECONDS = 300.0
START_SECONDS = 45


class WinwishError(RuntimeError):
    """A failure to report in one line."""


# -- paths and the settings Wish starts with ---------------------------------

def short_sha(sha: str) -> str:
    """The folder name for a build: the first twelve hex digits, lower case."""
    if not SHA.match(sha):
        raise WinwishError(f"not a commit SHA: {sha!r}")
    return sha.lower()[:12]


def task_name(holder: str) -> str:
    """The scheduled task that holds this holder's Wish; two holders never share one."""
    if not HOLDER.match(holder):
        raise WinwishError(f"not a holder name winuae.ps1 accepts: {holder!r}")
    return f"wish-run-{holder}"


def build_root(holder: str) -> str:
    """Where the holder's zips are unpacked, each into a folder of its own."""
    return rf"{run_dir(holder)}\build"


def run_dir(holder: str) -> str:
    """The holder's private APPDATA/LOCALAPPDATA parent."""
    if not HOLDER.match(holder):
        raise WinwishError(f"not a holder name winuae.ps1 accepts: {holder!r}")
    return rf"{ROOT}\run-{holder}"


def log_dir(holder: str) -> str:
    """Where `wish/debuglog.py` writes: `<APPDATA>\\wish\\logs`."""
    return rf"{run_dir(holder)}\appdata\wish\logs"


def disks_dir(holder: str) -> str:
    """Where the holder's copies of the game's ADFs sit, for Wish to read the maps from."""
    return rf"{run_dir(holder)}\disks"


def settings_json(game: str | None = None, folder: str | None = None) -> str:
    """The settings file Wish starts with: the log on, and a game folder when given.

    `game` is a `game_folders` key (`c64_port.GAMES[i].key` or an Amiga-only title's)
    and `folder` the guest folder holding that title's ADFs; without them Wish says
    "No game disks found" and draws no map.
    """
    values: dict[str, Any] = {"diagnostics": True}
    if game:
        values["game_folders"] = {game: folder}
    return json.dumps(values, indent=1) + "\n"


def environment(flag: bool, holder: str) -> dict[str, str]:
    """What `wish.exe` is started with; the flag is left unset for the control."""
    env = {"APPDATA": rf"{run_dir(holder)}\appdata",
           "LOCALAPPDATA": rf"{run_dir(holder)}\local",
           "WISH_DEBUG": "1"}
    if flag:
        env[FLAG] = "1"
    return env


#: Cleared in the task whatever the holder's own session has, so the window can
#: reach no other backend and the flag-off control really has no Amiga row.
CLEARED = ("WISH_EXPERIMENTAL_AMIGA_FSUAE", "POR_MONITOR", "WISH_EXPERIMENTAL_C64_ULTIMATE",
           "POR_ULTIMATE", "WISH_ULTIMATE", "POR_ULTIMATE_PASSWORD", "WISH_ULTIMATE_PASSWORD")


# -- PowerShell run on the guest ---------------------------------------------

def q(text: str) -> str:
    """`text` as a single-quoted PowerShell string."""
    return winvmguest._ps_quote(text)


def write_file(path: str, text: str) -> str:
    """A PowerShell statement that writes `text` to `path` on the guest.

    The text goes as base64 bytes, not nested inside a second `-EncodedCommand`: each
    encoding multiplies the size by about 2.7, and a command line past 32,767
    characters is refused by Windows ("exec request failed").  The BOM lets Windows
    PowerShell 5.1 read non-ASCII text as UTF-8.
    """
    data = base64.b64encode(b"\xef\xbb\xbf" + text.encode("utf-8")).decode("ascii")
    return f"[IO.File]::WriteAllBytes({q(path)}, [Convert]::FromBase64String('{data}'))"


def stage_script(holder: str, zip_path: str, zip_sha: str) -> str:
    """Unpack the copied zip into a fresh folder named by its hash; say where `wish.exe` is.

    The holder's whole build folder is cleared first, so no earlier build's files
    survive; that fails, rather than half-deleting, if a Wish is running from it.
    The zip's hash is checked on the guest before it is unpacked.
    """
    root = build_root(holder)
    dest = rf"{root}\{zip_sha[:12]}"
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        "$ProgressPreference = 'SilentlyContinue'",
        f"$z = {q(zip_path)}",
        "$got = (Get-FileHash -Algorithm SHA256 -LiteralPath $z).Hash.ToLower()",
        f"if ($got -ne {q(zip_sha.lower())}) {{ \"fail the copied zip hashes to $got, not {zip_sha.lower()}\"; exit 1 }}",
        f"$b = {q(root)}",
        "if (Test-Path $b) { Remove-Item -LiteralPath $b -Recurse -Force }",
        f"Expand-Archive -LiteralPath $z -DestinationPath {q(dest)} -Force",
        f"$exe = Get-ChildItem -LiteralPath {q(dest)} -Recurse -Filter wish.exe | Select-Object -First 1",
        f"if (-not $exe) {{ \"fail no wish.exe under {dest}\"; exit 1 }}",
        "'ok exe=' + $exe.FullName + ' sha256=' + (Get-FileHash -Algorithm SHA256 -LiteralPath $exe.FullName).Hash",
    ])


def mkdir_script(path: str) -> str:
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        f"New-Item -ItemType Directory -Force -Path {q(path)} | Out-Null",
        "'ok'",
    ])


def _task_body(env: dict[str, str], build: str, flag: bool) -> str:
    """What the task runs in session 1: set the environment, start Wish, wait for it.

    `Start-Process -Wait` because `&` returns at once for a GUI program, which would
    end the task while Wish was still up.
    """
    lines = [f"Remove-Item Env:{k} -ErrorAction SilentlyContinue" for k in CLEARED]
    if not flag:
        lines.append(f"Remove-Item Env:{FLAG} -ErrorAction SilentlyContinue")
    lines += [f"$env:{k} = {q(v)}" for k, v in env.items()]
    lines += [f"$exe = Get-ChildItem -LiteralPath {q(build)} -Recurse -Filter wish.exe | Select-Object -First 1",
              "Start-Process -Wait -FilePath $exe.FullName -WorkingDirectory $exe.DirectoryName"]
    return "\n".join(lines)


def probe_task_name(holder: str) -> str:
    """The session 1 task that lists Wish's windows; one per holder."""
    task_name(holder)  # raises for a holder winuae.ps1 would not accept
    return f"wish-probe-{holder}"


def window_probe(out: str, build: str) -> str:
    """What the probe task runs in session 1: one line per top-level window of a `wish` process under `build`.

    Each line is `hwnd|pid|visible|class|title`.  `Get-Process`'s `MainWindowHandle`
    only sees windows on the caller's own desktop, so a call made over ssh (session 0)
    reads 0 for a window in session 1; only a process in session 1 can list them.  A
    `wish` whose path is not under `build` belongs to another holder and is not listed.
    """
    tmp = out + ".tmp"
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        "Add-Type -Namespace WishProbe -Name Win -MemberDefinition @'",
        "public delegate bool EnumProc(IntPtr h, IntPtr l);",
        "[DllImport(\"user32.dll\")] public static extern bool EnumWindows(EnumProc p, IntPtr l);",
        "[DllImport(\"user32.dll\")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint p);",
        "[DllImport(\"user32.dll\")] public static extern bool IsWindowVisible(IntPtr h);",
        "[DllImport(\"user32.dll\", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h, System.Text.StringBuilder s, int n);",
        "[DllImport(\"user32.dll\", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, System.Text.StringBuilder s, int n);",
        "'@",
        f"$script:build = {q(build)}",
        "$script:ids = @(Get-Process -Name wish -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Path -like \"$script:build\\*\" } | ForEach-Object { $_.Id })",
        "$script:rows = New-Object System.Collections.ArrayList",
        "$cb = [WishProbe.Win+EnumProc]{",
        "  param($h, $l)",
        "  $owner = [uint32]0",
        "  [void][WishProbe.Win]::GetWindowThreadProcessId($h, [ref]$owner)",
        "  if ($script:ids -contains [int]$owner) {",
        "    $c = New-Object System.Text.StringBuilder 256",
        "    $t = New-Object System.Text.StringBuilder 512",
        "    [void][WishProbe.Win]::GetClassName($h, $c, 256)",
        "    [void][WishProbe.Win]::GetWindowText($h, $t, 512)",
        "    $v = if ([WishProbe.Win]::IsWindowVisible($h)) { 1 } else { 0 }",
        "    [void]$script:rows.Add(($h.ToInt64().ToString() + '|' + $owner + '|' + $v + '|' + $c + '|' + $t))",
        "  }",
        "  return $true",
        "}",
        "[void][WishProbe.Win]::EnumWindows($cb, [IntPtr]::Zero)",
        f"[IO.File]::WriteAllLines({q(tmp)}, [string[]]$script:rows)",
        f"Move-Item -Force {q(tmp)} {q(out)}",
    ])


def start_script(holder: str, env: dict[str, str], wait: int = START_SECONDS,
                 disks: tuple[str, ...] = (), game: str | None = None,
                 reseed: bool = True) -> str:
    """Seed the private settings, start `wish.exe` in session 1, wait for its window.

    The reply is `ok pid=N session=S window=H` or `fail ...`.  Session 0 is a
    failure: a window there is invisible to a screenshot.  The window is looked for
    by a task in session 1 (`window_probe`), because the ssh session cannot see it; a
    failure lists every `wish` process and every window the probe found.

    `disks` are ADFs already on the guest; they are copied into `disks_dir` and, with
    `game`, the settings point that title's folder there.  A start with `reseed`
    false (`start`, `restart`) leaves the settings of an earlier `up` in place and
    writes them only when there are none.

    The match assumes the title starts with "Wish": `WishWindow.setWindowTitle` and
    `wish/window.py`'s `_retitle` give "Wish" plus an optional " [logging]", and nothing
    calls `_retitle` with another base.
    """
    build, run = build_root(holder), run_dir(holder)
    body = winvmguest.encode_powershell(_task_body(env, build, FLAG in env))
    args = f"-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -EncodedCommand {body}"
    probe_out = rf"{run}\windows.txt"
    folder = disks_dir(holder)
    copy_disks = [f"New-Item -ItemType Directory -Force -Path {q(folder)} | Out-Null",
                  # An earlier run's copies would otherwise stay in the folder Wish scans.
                  f"Remove-Item -Path {q(folder + chr(92) + '*')} -Recurse -Force -ErrorAction SilentlyContinue",
                  *(f"Copy-Item -LiteralPath {q(d)} -Destination {q(rf'{folder}\df{n}-{pathlib.PureWindowsPath(d).name}')} -Force"
                    for n, d in enumerate(disks))] if disks else []
    guard = "" if reseed else "if (-not (Test-Path -LiteralPath $settings)) { "
    tail = "" if reseed else " }"
    probe_file = rf"{run}\probe.ps1"
    probe_args = f'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{probe_file}"'
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        f"$build = {q(build)}",
        f"$run = {q(run)}",
        f"$task = {q(task_name(holder))}",
        f"$probe = {q(probe_task_name(holder))}",
        f"$probeOut = {q(probe_out)}",
        "$exe = Get-ChildItem -LiteralPath $build -Recurse -Filter wish.exe | Select-Object -First 1",
        "if (-not $exe) { \"fail no wish.exe under $build; stage it first\"; exit 1 }",
        "$all = @(Get-Process -Name wish -ErrorAction SilentlyContinue)",
        # A process whose path cannot be read might be ours; passing it would start a second.
        "$blind = @($all | Where-Object { -not $_.Path })",
        "if ($blind.Count -gt 0) { \"fail cannot tell whether wish.exe pid=$($blind[0].Id) is running from ${run}: its path is unreadable\"; exit 1 }",
        "$mine = @($all | Where-Object { $_.Path -like \"$run\\*\" })",
        "if ($mine.Count -gt 0) { \"fail wish.exe already running pid=$($mine[0].Id); stop it first\"; exit 1 }",
        "New-Item -ItemType Directory -Force -Path \"$run\\appdata\\wish\", \"$run\\local\" | Out-Null",
        # No byte-order mark: `Settings.load` reads UTF-8 strictly, and a BOM makes
        # json refuse the file, which falls back to defaults and no log.
        *copy_disks,
        "$settings = \"$run\\appdata\\wish\\automap.json\"",
        f"{guard}[IO.File]::WriteAllText($settings, {q(settings_json(game if disks else None, disks_dir(holder)))}, (New-Object Text.UTF8Encoding $false)){tail}",
        "$p = New-ScheduledTaskPrincipal -UserId \"$env:COMPUTERNAME\\$env:USERNAME\" -LogonType Interactive",
        "$s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries",
        f"$a = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument {q(args)}",
        "Register-ScheduledTask -TaskName $task -Action $a -Principal $p -Settings $s -Force | Out-Null",
        write_file(probe_file, window_probe(probe_out, build)),
        f"$pa = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument {q(probe_args)}",
        "Register-ScheduledTask -TaskName $probe -Action $pa -Principal $p -Settings $s -Force | Out-Null",
        # One probe at a time: starting a task that is still running does nothing, and
        # a late finish would delete the next answer.  `$seconds` bounds the whole call.
        "function Get-WishWindows([double]$seconds) {",
        "  $until = (Get-Date).AddSeconds($seconds)",
        "  while ((Get-ScheduledTask -TaskName $probe).State -ne 'Ready' -and (Get-Date) -lt $until) { Start-Sleep -Milliseconds 100 }",
        "  if ((Get-ScheduledTask -TaskName $probe).State -ne 'Ready') { return @('the window probe was still running') }",
        "  Remove-Item -LiteralPath $probeOut -ErrorAction SilentlyContinue",
        "  Start-ScheduledTask -TaskName $probe",
        "  while (-not (Test-Path -LiteralPath $probeOut) -and (Get-Date) -lt $until) { Start-Sleep -Milliseconds 100 }",
        "  if (Test-Path -LiteralPath $probeOut) { return @(Get-Content -LiteralPath $probeOut) }",
        "  return @(\"the window probe gave no answer in $([int]$seconds)s\")",
        "}",
        "function Close-Probe { Unregister-ScheduledTask -TaskName $probe -Confirm:$false -ErrorAction SilentlyContinue }",
        "try {",
        "  Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue",
        "  Start-ScheduledTask -TaskName $task",
        f"  $deadline = (Get-Date).AddSeconds({int(wait)})",
        "  while ($true) {",
        "    $left = ($deadline - (Get-Date)).TotalSeconds",
        "    if ($left -lt 1) { break }",
        "    $w = @(Get-Process -Name wish -ErrorAction SilentlyContinue | Where-Object { $_.Path -like \"$build\\*\" })",
        "    if ($w.Count -gt 0) {",
        "      foreach ($row in @(Get-WishWindows ([Math]::Min(10, $left)))) {",
        "        $f = $row -split '\\|', 5",
        "        if ($f.Count -eq 5 -and $f[2] -eq '1' -and $f[4] -like 'Wish*') {",
        "          $owner = Get-Process -Id ([int]$f[1]) -ErrorAction SilentlyContinue",
        "          if (-not $owner) { continue }",
        "          if ($owner.SessionId -eq 0) { \"fail wish.exe pid=$($owner.Id) is in session 0, where no screenshot can see it\"; exit 1 }",
        "          \"ok pid=$($owner.Id) session=$($owner.SessionId) window=$($f[0])\"; exit 0",
        "        }",
        "      }",
        "    } else { Start-Sleep -Milliseconds 250 }",
        "  }",
        "  $info = Get-ScheduledTaskInfo -TaskName $task",
        "  $why = ''",
        "  if ($info.LastTaskResult -eq 267011) { $why = ' -- nobody is logged on at the console, so an Interactive task cannot run' }",
        "  $procs = @(Get-Process -Name wish -ErrorAction SilentlyContinue | ForEach-Object { \"  wish pid=$($_.Id) session=$($_.SessionId) path=$($_.Path)\" })",
        "  if ($procs.Count -eq 0) { $procs = @('  no wish process') }",
        # Diagnostics only, after the budget: a fixed 5 s, not part of `wait`.
        "  $seen = @(Get-WishWindows 5 | ForEach-Object { \"  window $_\" })",
        "  if ($seen.Count -eq 0) { $seen = @('  no top-level window belongs to a wish process') }",
        f"  \"fail no wish.exe window titled Wish after {int(wait)}s; lastResult=0x\" + ('{{0:X}}' -f $info.LastTaskResult) + $why",
        "  $procs",
        "  $seen",
        "  exit 1",
        "} finally { Close-Probe }",
    ])


def stop_script(holder: str) -> str:
    """End the holder's task and the `wish.exe` under its own folder, then remove the task.

    This holder's readable processes are stopped first. Another holder's Wish, or a
    process whose path cannot be read, is never stopped; an unreadable one is
    reported only once none of this holder's is left, because it may be this
    holder's.
    """
    run = run_dir(holder)
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        f"$run = {q(run)}",
        f"$task = {q(task_name(holder))}",
        f"Unregister-ScheduledTask -TaskName {q(probe_task_name(holder))} -Confirm:$false -ErrorAction SilentlyContinue",
        "Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue",
        "for ($i = 0; $i -lt 40; $i++) {",
        "  $all = @(Get-Process -Name wish -ErrorAction SilentlyContinue)",
        "  $mine = @($all | Where-Object { $_.Path -like \"$run\\*\" })",
        "  if ($mine.Count -gt 0) {",
        "    if ($i -eq 4) { $mine | Stop-Process -Force -ErrorAction SilentlyContinue }",
        "    Start-Sleep -Milliseconds 250",
        "    continue",
        "  }",
        "  Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue",
        "  $blind = @($all | Where-Object { -not $_.Path })",
        "  if ($blind.Count -gt 0) { \"fail cannot tell whether wish.exe pid=$($blind[0].Id) is this holder's: its path is unreadable\"; exit 1 }",
        "  'ok stopped'; exit 0",
        "}",
        "'fail wish.exe still running 10s after stop'; exit 1",
    ])


def window_capture(out: str, holder: str) -> str:
    """What the session 1 task runs: draw Wish's own window into `out`.

    `PrintWindow` with PW_RENDERFULLCONTENT, so a window another one overlaps still
    comes out whole.  DPI-aware, so the size is the real pixel size.
    """
    tmp = out + ".tmp"
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        "Add-Type -AssemblyName System.Drawing",
        "Add-Type -Namespace WishShot -Name Win -MemberDefinition @'",
        "[DllImport(\"user32.dll\")] public static extern bool SetProcessDPIAware();",
        "[DllImport(\"user32.dll\")] public static extern bool GetWindowRect(IntPtr h, out RECT r);",
        "[DllImport(\"user32.dll\")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);",
        "[StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }",
        "'@",
        "[void][WishShot.Win]::SetProcessDPIAware()",
        f"$root = {q(run_dir(holder))}",
        "$w = Get-Process -Name wish -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Path -like \"$root\\*\" -and $_.MainWindowHandle -ne 0 } | Select-Object -First 1",
        "if (-not $w) { throw 'no wish.exe window' }",
        "$r = New-Object WishShot.Win+RECT",
        "[void][WishShot.Win]::GetWindowRect($w.MainWindowHandle, [ref]$r)",
        "$bmp = New-Object System.Drawing.Bitmap ($r.R - $r.L), ($r.B - $r.T)",
        "$g = [System.Drawing.Graphics]::FromImage($bmp)",
        "$dc = $g.GetHdc()",
        "$ok = [WishShot.Win]::PrintWindow($w.MainWindowHandle, $dc, 2)",
        "$g.ReleaseHdc($dc)",
        "if (-not $ok) { throw 'PrintWindow failed' }",
        f"$bmp.Save({q(tmp)}, [System.Drawing.Imaging.ImageFormat]::Png)",
        "$g.Dispose(); $bmp.Dispose()",
        f"Move-Item -Force {q(tmp)} {q(out)}",
    ])


# -- clicking Wish through UI Automation -------------------------------------

UI_BEGIN = "WISHUI-BEGIN"
UI_END = "WISHUI-END"
#: Seconds a name is searched for: a menu's items exist only once it is open.
UI_WAIT = 4


#: At most this many names in one `click`: each may wait `UI_WAIT` seconds, and the
#: task is stopped after two minutes.
UI_MAX_NAMES = 8


def ui_timeout(count: int, action: str = "click") -> float:
    """Seconds to wait for a `click` of `count` names: the wait per name plus a fixed start.

    `controls` starts slower, because it compiles the MSAA helper and walks each dialog.
    """
    if action == "controls":
        return 50.0
    return 20.0 + (UI_WAIT + 2) * max(1, count)


#: Reads a window through MSAA (oleacc), which Qt answers while a modal dialog is up
#: and its UI Automation provider reports no children.
#: The role of the row that says the walk stopped early.
MSAA_TRUNCATED = -1

MSAA_CODE = r"""
using System; using System.Runtime.InteropServices;
public class WishOa {
  [DllImport("oleacc.dll")] public static extern int AccessibleObjectFromWindow(IntPtr h, uint id, ref Guid riid, [MarshalAs(UnmanagedType.IUnknown)] out object acc);
  [DllImport("oleacc.dll")] public static extern int AccessibleChildren([MarshalAs(UnmanagedType.IDispatch)] object p, int start, int n, [Out, MarshalAs(UnmanagedType.LPArray, ArraySubType=UnmanagedType.Struct)] object[] kids, out int got);
}
"""

#: The walk itself is PowerShell on the COM object, because a C# `IAccessible` declaration
#: read garbage child counts from Qt's objects where late binding read them correctly.
MSAA_WALK = [
    "  function Get-Msaa($hwnd) {",
    "    $script:cut = $false",
    "    $g = [Guid]'618736E0-3C3D-11CF-810C-00AA00389B71'; $root = $null",
    "    [void][WishOa]::AccessibleObjectFromWindow([IntPtr]$hwnd, [uint32]4294967292, [ref]$g, [ref]$root)",
    "    $rows = New-Object System.Collections.ArrayList",
    "    if ($root) { Read-Msaa $root $rows 0 }",
    f"    if ($script:cut) {{ [void]$rows.Add('{MSAA_TRUNCATED}|||0') }}",
    "    return $rows",
    "  }",
    "  function Read-Msaa($parent, $rows, $depth) {",
    "    if ($depth -gt 12 -or $rows.Count -gt 400) { $script:cut = $true; return }",
    "    $n = 0; try { $n = [int]$parent.accChildCount } catch { $script:cut = $true; return }",
    "    if ($n -le 0) { return }",
    "    if ($n -gt 500) { $script:cut = $true; return }",
    "    $kids = New-Object object[] $n; $got = 0",
    "    try { [void][WishOa]::AccessibleChildren($parent, 0, $n, $kids, [ref]$got) } catch { $script:cut = $true; return }",
    "    $got = [Math]::Min($got, $n)",
    "    for ($i = 0; $i -lt $got; $i++) {",
    "      $k = $kids[$i]",
    "      if ($k -is [int]) { $self = $parent; $id = $k } else { $self = $k; $id = 0 }",
    "      $name = ''; $value = ''; $role = 0; $state = 0",
    "      try { $name = [string]$self.accName($id) } catch {}",
    "      try { $value = [string]$self.accValue($id) } catch {}",
    "      try { $role = [int]$self.accRole($id) } catch {}",
    "      try { $state = [int]$self.accState($id) } catch {}",
    "      [void]$rows.Add([string]$role + '|' + ($name -replace '[\r\n]', ' ' -replace '\\|', '\\u007c') + '|' + ($value -replace '[\r\n]', ' ' -replace '\\|', '\\u007c') + '|' + $state)",
    "      if ($id -eq 0) { Read-Msaa $self $rows ($depth + 1) }",
    "    }",
    "  }",
]

#: MSAA `ROLE_SYSTEM_*` numbers (oleacc.h) to the UI Automation type names `controls --type` takes.
MSAA_ROLES = {9: "Window", 11: "Menu", 12: "MenuItem", 20: "Group", 22: "ToolBar", 28: "Row",
              33: "List", 34: "ListItem", 37: "TabItem", 41: "Text", 42: "Edit", 43: "Button",
              44: "CheckBox", 45: "RadioButton", 46: "ComboBox", 47: "ComboBox", 60: "Tab"}


def msaa_line(row: str) -> tuple[str, str]:
    """A `role|name|value|state` row from the MSAA walk as (type, `controls` line).

    A `|` in a name or value arrives as `\\u007c`.  State bit 1 is unavailable (disabled)
    and bit 16 is checked.  An unknown role reads `Role<n>`; the truncation row
    reads `...truncated`.
    """
    role, name, value, state = (row.split("|") + ["", "", "", "0"])[:4]
    if int(role) == MSAA_TRUNCATED:
        return "", "...truncated"
    kind = MSAA_ROLES.get(int(role), f"Role{role}")
    name, value = (x.replace("\\u007c", "|") for x in (name, value))
    bits = int(state or 0)
    return kind, f"{kind}|{name}|{value}|enabled={not bits & 1}|checked={bool(bits & 16)} (MSAA)"



def ui_inner(build: str, action: str, names: tuple[str, ...], kind: str | None, out: str,
             prefix: bool = False) -> str:
    """What the session 1 task runs: list the controls of this holder's Wish, or click some.

    `action` is `controls` (one line per control: `Type|Name|AutomationId|enabled=B|state`,
    optionally only `kind`) or `click` (each name in turn, so a menu is `File`,
    `Preferences`).  A name matches a control's Name exactly for the whole wait; with
    `prefix`, a prefix match is tried once the wait has run out.  The line reports the
    control's full name.  A disabled control is never invoked, because `Invoke` on one
    returns without an error; but a control under a modal dialog can still read enabled,
    so a click that the dialog swallows is not an error.  Every top-level window of
    every `wish.exe` under `build` is searched, so an open menu or dialog is found.
    UI Automation shows a modal dialog with no children; `controls` then reads that
    window through MSAA, whose lines read `Type|Name|Value|state=N`.  The answer is
    `ok` then the lines, or one `fail ...` line.
    """
    tmp = out + ".tmp"
    names_ps = ", ".join(q(n) for n in names) or "@()"
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        f"$build = {q(build)}",
        f"$names = @({names_ps})",
        f"$kind = {q(kind or '')}",
        f"$prefix = ${'true' if prefix else 'false'}",
        "$lines = New-Object System.Collections.ArrayList",
        "try {",
        "  Add-Type -AssemblyName UIAutomationClient",
        "  Add-Type -AssemblyName UIAutomationTypes",
        "  Add-Type -TypeDefinition @'",
        *MSAA_CODE.strip().splitlines(),
        "'@",
        *MSAA_WALK,
        "  $UIA = [System.Windows.Automation.AutomationElement]",
        "  $procs = @(Get-Process -Name wish -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Path -like \"$build\\*\" })",
        "  if ($procs.Count -eq 0) { throw 'no wish.exe of this holder is running' }",
        "  function Get-Controls {",
        "    $found = New-Object System.Collections.ArrayList",
        "    foreach ($proc in $procs) {",
        "      $mine = New-Object System.Windows.Automation.PropertyCondition($UIA::ProcessIdProperty, $proc.Id)",
        "      foreach ($top in $UIA::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children, $mine)) {",
        "        [void]$found.Add($top)",
        "        foreach ($e in $top.FindAll([System.Windows.Automation.TreeScope]::Descendants, "
        "[System.Windows.Automation.Condition]::TrueCondition)) { [void]$found.Add($e) }",
        "      }",
        "    }",
        "    return $found",
        "  }",
        "  function Get-Kind($e) { return ($e.Current.ControlType.ProgrammaticName -replace '^ControlType\\.', '') }",
        "  function Get-State($e) {",
        "    $o = $null",
        "    if ($e.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$o)) { return 'selected=' + $o.Current.IsSelected }",
        "    if ($e.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern, [ref]$o)) { return 'toggle=' + $o.Current.ToggleState }",
        "    return ''",
        "  }",
        "  function Get-Line($e) { return ((Get-Kind $e) + '|' + $e.Current.Name + '|' + $e.Current.AutomationId + '|enabled=' + $e.Current.IsEnabled + '|' + (Get-State $e)) }",
        # `Invoke` on an item that opens a modal dialog does not return until the dialog
        # closes, which would hold this task until it was killed; so it runs on its own
        # thread, and a call still running after a moment is reported rather than waited for.
        "  function Start-Async($pattern) {",
        "    $ps = [PowerShell]::Create()",
        "    [void]$ps.AddScript('param($p) $p.Invoke()').AddArgument($pattern)",
        "    $handle = $ps.BeginInvoke()",
        "    Start-Sleep -Milliseconds 400",
        "    if (-not $handle.IsCompleted) { return 'invoked (still running: modal?)' }",
        "    try {",
        "      [void]$ps.EndInvoke($handle)",
        "      if ($ps.HadErrors) { throw ($ps.Streams.Error | Select-Object -First 1).ToString() }",
        "    } finally { $ps.Dispose() }",
        "    return 'invoked'",
        "  }",
        "  function Use-Control($e) {",
        "    $o = $null",
        # A menu opens by Expand; Invoke on a menu bar item does not show its popup.
        "    if ((Get-Kind $e) -eq 'MenuItem' -and $e.TryGetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern, [ref]$o)) { $o.Expand(); return 'expanded' }",
        "    if ($e.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$o)) { return (Start-Async $o) }",
        "    if ($e.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$o)) { $o.Select(); return 'selected' }",
        "    if ($e.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern, [ref]$o)) { $o.Toggle(); return 'toggled' }",
        "    if ($e.TryGetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern, [ref]$o)) { $o.Expand(); return 'expanded' }",
        # A dialog has no button of its own in the tree to some builds; closing its window is the exit.
        "    if ($e.TryGetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern, [ref]$o)) { $o.Close(); return 'closed' }",
        "    throw 'the control offers no way to be clicked'",
        "  }",
        f"  if ({q(action)} -eq 'controls') {{",
        "    foreach ($e in Get-Controls) {",
        "      if ($kind -eq '' -or (Get-Kind $e) -eq $kind) { [void]$lines.Add((Get-Line $e)) }",
        "      if ((Get-Kind $e) -eq 'Window' -and $e.Current.NativeWindowHandle -ne 0 -and "
        "$e.FindAll([System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition).Count -eq 0) {",
        "        foreach ($row in Get-Msaa $e.Current.NativeWindowHandle) {",
        "          [void]$lines.Add('MSAA|' + $row)",
        "        }",
        "      }",
        "    }",
        "  } else {",
        "    if ($names.Count -eq 0) { throw 'click needs at least one name' }",
        "    foreach ($name in $names) {",
        f"      $until = (Get-Date).AddSeconds({UI_WAIT})",
        "      $hit = @()",
        "      $expired = $false",
        "      while ($true) {",
        "        $all = @(Get-Controls | Where-Object { $_.Current.Name -ne '' -and ($kind -eq '' -or (Get-Kind $_) -eq $kind) })",
        "        $hit = @($all | Where-Object { $_.Current.Name -eq $name })",
        "        if ($hit.Count -eq 0 -and $expired -and $prefix) { $hit = @($all | Where-Object { $_.Current.Name.StartsWith($name) }) }",
        "        if ($hit.Count -gt 0 -or $expired) { break }",
        "        if ((Get-Date) -gt $until) { if ($prefix) { $expired = $true } else { break } } else { Start-Sleep -Milliseconds 200 }",
        "      }",
        "      if ($hit.Count -eq 0) { throw \"no control named $name\" }",
        "      if ($hit.Count -gt 1) { throw \"$($hit.Count) controls match ${name}: \" + (($hit | ForEach-Object { Get-Line $_ }) -join ' ; ') }",
        "      if (-not $hit[0].Current.IsEnabled) { throw \"$($hit[0].Current.Name) is disabled\" }",
        "      [void]$lines.Add($hit[0].Current.Name + ' -> ' + (Use-Control $hit[0]))",
        "      Start-Sleep -Milliseconds 400",
        "    }",
        "  }",
        "  $answer = @('ok') + $lines",
        "} catch {",
        "  $answer = @('fail ' + $_.Exception.Message)",
        "}",
        # ASCII only: the ssh reply is read as UTF-8, and a menu's "..." may be one character.
        "$answer = @($answer | ForEach-Object { [regex]::Replace($_, '[^\\x20-\\x7e]', "
        "{ param($m) '\\u' + ([int][char]$m.Value).ToString('x4') }) })",
        f"[IO.File]::WriteAllLines({q(tmp)}, [string[]]$answer)",
        f"Move-Item -Force {q(tmp)} {q(out)}",
        # A thread left in a blocked `Invoke` would keep this process, and the task, alive.
        "[Environment]::Exit(0)",
    ])


def ui_file(token: str) -> str:
    """Where a `ui_inner` script is put on the guest, for the task to run with `-File`."""
    if not re.fullmatch(r"[A-Za-z0-9]{1,32}", token):
        raise WinwishError(f"not a usable token: {token!r}")
    return rf"C:\Users\Public\wish-ui-{token}.ps1"


def ui_script(token: str, timeout: float) -> str:
    """What the ssh session runs: run the put `ui_file` in session 1 and print its answer between markers.

    The script itself is copied across with `winvm put` rather than carried in this
    command, because a command line over 32,767 characters is refused.
    """
    task = f"wish-ui-{token}"
    out = rf"C:\Users\Public\{task}.txt"
    file = ui_file(token)
    args = f'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{file}"'
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        f"$task = {q(task)}",
        f"$out = {q(out)}",
        "Remove-Item $out, \"$out.tmp\" -ErrorAction SilentlyContinue",
        f"$a = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument {q(args)}",
        "$p = New-ScheduledTaskPrincipal -UserId \"$env:COMPUTERNAME\\$env:USERNAME\" -LogonType Interactive",
        "$s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2) "
        "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries",
        "Register-ScheduledTask -TaskName $task -Action $a -Principal $p -Settings $s -Force | Out-Null",
        "try {",
        "  Start-ScheduledTask -TaskName $task",
        f"  $deadline = (Get-Date).AddSeconds({int(timeout)})",
        "  while (-not (Test-Path $out) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 200 }",
        "  if (-not (Test-Path $out)) { 'fail the Wish window did not answer in ' + " f"{int(timeout)}" " + 's'; exit 1 }",
        f"  '{UI_BEGIN}'",
        "  Get-Content -LiteralPath $out",
        f"  '{UI_END}'",
        "} finally {",
        "  Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue",
        "  Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue",
        f"  Remove-Item $out, \"$out.tmp\", {q(file)} -ErrorAction SilentlyContinue",
        "}",
        "exit 0",
    ])


def ui_lines(text: str, kind: str | None = None) -> list[str]:
    """The lines between the markers of a `ui_script` reply; a `fail` line is an error."""
    lines = [line.strip() for line in text.splitlines()]
    try:
        body = lines[lines.index(UI_BEGIN) + 1:lines.index(UI_END)]
    except ValueError:
        fail = next((line for line in lines if line.startswith("fail")), "")
        raise WinwishError(fail or "the window answered with nothing: "
                           + (text.strip()[:200] or "no output")) from None
    if not body or body[0] != "ok":
        raise WinwishError(body[0] if body else "the window answered with nothing")
    lines = []
    for line in body[1:]:
        if not line.startswith("MSAA|"):
            lines.append(line)
            continue
        found, text = msaa_line(line[len("MSAA|"):])
        if not kind or not found or found == kind:
            lines.append(text)
    return lines


def ui(guest: "Guest", holder: str, action: str, names: tuple[str, ...] = (),
       kind: str | None = None, prefix: bool = False) -> list[str]:
    """List Wish's controls (`controls`) or click `names` in turn (`click`)."""
    if len(names) > UI_MAX_NAMES:
        raise WinwishError(f"click at most {UI_MAX_NAMES} names at once, not {len(names)}")
    guest.holds_lane(holder)
    token = secrets.token_hex(6)
    timeout = ui_timeout(len(names), action)
    inner = ui_inner(build_root(holder), action, names, kind,
                     rf"C:\Users\Public\wish-ui-{token}.txt", prefix)
    answered = False
    try:
        with tempfile.TemporaryDirectory() as tmp:
            local = pathlib.Path(tmp) / "ui.ps1"
            local.write_bytes(b"\xef\xbb\xbf" + inner.encode("utf-8"))
            guest.winvm("put", str(local), ui_file(token).replace("\\", "/"), timeout=CALL_SECONDS)
        rc, text = guest.run(["winvm", "ps", ui_script(token, timeout)], timeout + 20)
        lines = ui_lines(text, kind)
        answered = True
        return lines
    finally:
        if not answered:
            # The ssh script removes the file itself when it runs; this covers a put that
            # landed and a script that never did.
            _quietly(guest.ps, "Remove-Item -LiteralPath "
                     f"{q(ui_file(token))} -Force -ErrorAction SilentlyContinue\n'ok'")


# -- talking to the guest and to gh ------------------------------------------

def _run(argv: list[str], timeout: float) -> tuple[int, str]:
    env = dict(os.environ, SSH_ASKPASS_REQUIRE="never")
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, env=env,
                              encoding="utf-8", errors="replace",
                              timeout=timeout, stdin=subprocess.DEVNULL)
    except FileNotFoundError as exc:
        raise WinwishError(f"{argv[0]} is not installed: {exc}") from None
    except subprocess.TimeoutExpired:
        raise WinwishError(f"{argv[0]} {argv[1] if len(argv) > 1 else ''} "
                           f"exceeded its {timeout:.0f}s limit") from None
    return proc.returncode, (proc.stdout + proc.stderr).strip()


class Guest:
    """The `winvm` and `gh` calls, behind one seam so a test can fake them."""

    def __init__(self, run: Callable[[list[str], float], tuple[int, str]] = _run):
        self.run = run

    def winvm(self, *args: str, timeout: float = CALL_SECONDS) -> str:
        rc, out = self.run(["winvm", *args], timeout)
        if rc:
            raise WinwishError(f"winvm {args[0]} failed: {out}")
        return out

    def ps(self, script: str, timeout: float = CALL_SECONDS) -> str:
        """Run `script` on the guest; its reply must open with `ok`."""
        rc, out = self.run(["winvm", "ps", script], timeout)
        if rc or not out.startswith("ok"):
            raise WinwishError(f"the guest said: {out or 'nothing'}")
        return out

    def holds_lane(self, holder: str) -> None:
        rc, out = self.run(["winvm", "lane", "--expect", holder], CALL_SECONDS)
        if rc:
            raise WinwishError(f"{holder} does not hold the WinUAE lane ({out})")

    def gh(self, *args: str, timeout: float = CALL_SECONDS) -> str:
        rc, out = self.run(["gh", *args], timeout)
        if rc:
            raise WinwishError(f"gh {args[0]} failed: {out}")
        return out


# -- the steps ---------------------------------------------------------------

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
#: Written beside the downloaded zip, so a zip given with `--zip` can be checked.
COMMIT_FILE = "commit.txt"


def full_sha(guest: Guest, sha: str) -> str:
    """`sha` as 40 lower-case hex digits; a short one is resolved with `git rev-parse`."""
    short_sha(sha)
    if FULL_SHA.match(sha.lower()):
        return sha.lower()
    rc, out = guest.run(["git", "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"],
                        CALL_SECONDS)
    if rc or not FULL_SHA.match(out.strip()):
        raise WinwishError(f"git cannot resolve {sha!r} to one commit: {out or 'no output'}")
    return out.strip()


def pick_run(listing: str, sha: str) -> int:
    """The newest finished, successful release run for `sha`, from `gh run list --json`."""
    try:
        runs = json.loads(listing)
    except ValueError as exc:
        raise WinwishError(f"gh run list did not print JSON: {exc}") from None
    good = [r for r in runs if r.get("conclusion") == "success"
            and str(r.get("headSha", "")).lower() == sha.lower()]
    if not good:
        raise WinwishError(
            f"no successful {WORKFLOW} run for {sha}; start one with "
            f"`gh workflow run {WORKFLOW} --ref <branch>` and wait for it")
    return int(max(good, key=lambda r: r.get("createdAt", ""))["databaseId"])


def fetch(guest: Guest, sha: str, dest: pathlib.Path | None = None) -> pathlib.Path:
    """Download the `frozen-windows` artifact of `sha` and return its zip.

    Safe to run again: the zips and the commit note from an earlier download are
    removed first, so a second call never finds two zips.
    """
    sha = full_sha(guest, sha)
    listing = guest.gh("run", "list", "--workflow", WORKFLOW, "--commit", sha,
                       "--limit", "20", "--json",
                       "databaseId,headSha,conclusion,createdAt")
    run_id = pick_run(listing, sha)
    dest = dest or scratch.cache_dir("winwish", sha[:12])
    scratch.ensure(dest)
    for old in [*dest.rglob("*.zip"), dest / COMMIT_FILE]:
        old.unlink(missing_ok=True)
    guest.gh("run", "download", str(run_id), "--name", ARTIFACT, "--dir",
             str(dest), timeout=COPY_SECONDS)
    zips = sorted(dest.rglob("*.zip"))
    if len(zips) != 1:
        raise WinwishError(f"expected one zip in the {ARTIFACT} artifact, "
                           f"found {[z.name for z in zips]}")
    (dest / COMMIT_FILE).write_text(sha + "\n")
    return zips[0]


@contextlib.contextmanager
def _ignoring_sigterm():
    """SIGTERM does nothing inside, so an undo that has begun finishes."""
    previous = signal.signal(signal.SIGTERM, signal.SIG_IGN)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def check_zip_commit(zipped: pathlib.Path, sha: str) -> None:
    """A zip that carries a commit note must name `sha`; one without cannot be checked."""
    note = zipped.parent / COMMIT_FILE
    if not note.exists():
        print(f"winwish: {zipped} has no {COMMIT_FILE} beside it, so it cannot be "
              f"checked against {sha}", file=sys.stderr)
    elif note.read_text().strip() != sha:
        raise WinwishError(f"{zipped} was downloaded for {note.read_text().strip()}, "
                           f"not {sha}")


def file_sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage(guest: Guest, holder: str, zipped: pathlib.Path) -> str:
    """Copy the zip to the guest and unpack it afresh; returns the guest's `ok exe=...` line."""
    root = run_dir(holder)
    zip_sha = file_sha256(zipped)
    guest.ps(mkdir_script(root))
    guest.winvm("put", str(zipped), root.replace("\\", "/") + "/", timeout=COPY_SECONDS)
    return guest.ps(stage_script(holder, rf"{root}\{zipped.name}", zip_sha),
                    timeout=COPY_SECONDS)


def probe_close_script(holder: str) -> str:
    """Remove the holder's probe task; for a start that ended without reaching its own cleanup."""
    return "\n".join([
        f"Unregister-ScheduledTask -TaskName {q(probe_task_name(holder))} -Confirm:$false -ErrorAction SilentlyContinue",
        "'ok'",
    ])


def start_wish(guest: Guest, holder: str, flag: bool = True, disks: tuple[str, ...] = (),
               game: str | None = None, reseed: bool = False) -> str:
    guest.holds_lane(holder)
    try:
        return guest.ps(start_script(holder, environment(flag, holder), disks=disks,
                                     game=game, reseed=reseed),
                        timeout=START_SECONDS + 30)
    except WinwishError:
        _quietly(guest.ps, probe_close_script(holder))
        raise


def stop_wish(guest: Guest, holder: str) -> str:
    guest.holds_lane(holder)
    return guest.ps(stop_script(holder))


def restart_wish(guest: Guest, holder: str, flag: bool = True) -> str:
    stop_wish(guest, holder)
    return start_wish(guest, holder, flag)


def shot(guest: Guest, holder: str, window: str, out: pathlib.Path) -> int:
    """Save a PNG of `window` (`wish`, `winuae` or `desktop`) to `out`; returns its size."""
    guest.holds_lane(holder)
    capture = (lambda path: window_capture(path, holder)) if window == "wish" else None
    script = winvmguest.shot_script(secrets.token_hex(6), 20, capture=capture)
    rc, text = guest.run(["winvm", "ps", script], 40.0)
    # The exit code is not read: a PowerShell script whose last statement set `$?`
    # false exits 1 with the whole PNG already printed, so only the PNG decides.
    try:
        data = winvmguest.decode_shot(text)
    except winvmguest.WinvmError as exc:
        raise WinwishError(f"no screenshot came back (winvm exit {rc}): {exc}") from None
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    if window == "winuae":
        from tools.amiga import amigashots  # noqa: PLC0415
        try:
            amigashots.crop(out, out)
        except LookupError as exc:
            raise WinwishError(f"{exc} (the whole-desktop grab is kept at {out})") from None
    return len(data)


def collect_log(guest: Guest, holder: str, out: pathlib.Path) -> list[str]:
    """Copy the holder's `logs` folder to `out`; returns the file names found."""
    guest.holds_lane(holder)
    scratch.ensure(out)
    guest.winvm("get", "-r", log_dir(holder), str(out), timeout=COPY_SECONDS)
    files = sorted(p.name for p in out.rglob("*") if p.is_file())
    if not any(name.startswith("wish-") for name in files):
        raise WinwishError("no wish-*.log came back; either Wish did not start "
                           "with its settings or it wrote nothing yet")
    return files


def floppy_paths(args: argparse.Namespace) -> list[str]:
    """The ADFs for DF0 upward; a drive may not be given without the one before it."""
    given = [args.df0, args.df1, args.df2, args.df3]
    if not args.df0:
        raise WinwishError("--df0 needs the path of an ADF on the guest")
    count = max(n for n, path in enumerate(given) if path) + 1
    if not all(given[:count]):
        raise WinwishError("the drives must be given without a gap: "
                           "--df1 needs --df0, --df2 needs --df1, --df3 needs --df2")
    return given[:count]


def floppy_options(count: int) -> tuple[str, ...]:
    """The WinUAE settings a third or fourth drive needs; `goldbox-a500.uae` has two.

    A drive past the template's `nr_floppies=2` is not present until the count is
    raised, and its type is set to a 3.5 inch drive as `route_pool.py` does for DF2.
    """
    if count <= 2:
        return ()
    return (f"nr_floppies={count}", *(f"floppy{n}type=0" for n in range(2, count)))


def up(guest: Guest, lane: Any, args: argparse.Namespace) -> dict[str, str]:
    """Fetch, stage, claim the lane, start WinUAE, start Wish.

    Anything that goes wrong between the claim and the end of `start_wish` -- an
    error, Ctrl-C or SIGTERM -- stops Wish (if it was attempted), stops WinUAE and
    releases the lane, in that order.
    """
    drives = floppy_paths(args)
    options = floppy_options(len(drives))
    if args.game and not GAME_KEY.match(args.game):
        raise WinwishError(f"not a game key: {args.game!r}")
    if not _mute_proof(pathlib.Path(args.mute_proof)):
        raise WinwishError(f"{args.mute_proof} is not a fresh muted-endpoint proof; "
                           "run winuaemute.ps1 first")
    sha = full_sha(guest, args.sha)
    zipped = pathlib.Path(args.zip) if args.zip else fetch(guest, sha)
    check_zip_commit(zipped, sha)
    result: dict[str, str] = {"staged": stage(guest, args.holder, zipped)}
    claimed = started = wish_tried = done = False
    with terminating():
        try:
            result["claim"] = lane.claim(args.holder, CALL_SECONDS)
            claimed = True
            result["winuae"] = lane.start(args.holder, *drives, timeout=START_SECONDS + 30,
                                          options=options)
            started = True
            wish_tried = True
            result["wish"] = start_wish(guest, args.holder, not args.no_flag,
                                        tuple(drives[:GAME_DISKS]), args.game, reseed=True)
            done = True
        finally:
            if not done:
                _undo(guest, lane, args.holder, wish_tried, started, claimed)
    return result


def _undo(guest: Guest, lane: Any, holder: str, wish_tried: bool,
          started: bool, claimed: bool) -> None:
    """Stop Wish, stop WinUAE, release the lane; a later step runs whatever an earlier one raised."""
    with _ignoring_sigterm():
        try:
            if wish_tried:
                _quietly(guest.ps, stop_script(holder))
        finally:
            try:
                if started:
                    _quietly(lane.stop, holder, CALL_SECONDS)
            finally:
                if claimed:
                    _quietly(lane.release, holder, CALL_SECONDS)


def down(guest: Guest, lane: Any, holder: str) -> dict[str, str]:
    """Stop Wish and remove its task, stop WinUAE, release the lane; each step runs even if one before fails."""
    result: dict[str, str] = {}
    problems: list[str] = []
    for name, step in (("wish", lambda: stop_wish(guest, holder)),
                       ("winuae", lambda: lane.stop(holder, CALL_SECONDS)),
                       ("release", lambda: lane.release(holder, CALL_SECONDS))):
        try:
            result[name] = step()
        except (RouteError, WinwishError) as exc:
            problems.append(f"{name}: {exc}")
    if problems:
        raise WinwishError("; ".join(problems))
    return result


def _quietly(step: Callable[..., Any], *args: Any) -> None:
    try:
        step(*args)
    except (RouteError, WinwishError):
        pass


# -- the command line --------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    def holder(p):
        p.add_argument("--holder", required=True,
                       help="the WinUAE lane holder, as in `winuae.ps1 claim -Holder`")

    def sha(p):
        p.add_argument("--sha", required=True, help="the pushed commit to run")

    p = sub.add_parser("fetch", help="download the frozen-windows artifact of a SHA")
    sha(p)
    p.add_argument("--dest", help="folder for the download "
                   "(default ~/.cache/wish/winwish/<sha12>)")

    p = sub.add_parser("up", help="fetch, stage, claim, start WinUAE and Wish")
    sha(p)
    holder(p)
    p.add_argument("--mute-proof", required=True,
                   help="the JSON that winuaemute.ps1 printed, under five minutes old")
    p.add_argument("--df0", required=True, help="a staged ADF on the guest for DF0")
    p.add_argument("--df1", help="a staged ADF on the guest for DF1")
    p.add_argument("--df2", help="a staged ADF on the guest for DF2 (Pool of Radiance's save disk)")
    p.add_argument("--df3", help="a staged ADF on the guest for DF3; needs --df2")
    p.add_argument("--game", help="a `game_folders` key such as pool-of-radiance: Wish's game "
                   "folder for that title is set to copies of the mounted ADFs, so it draws the map")
    p.add_argument("--zip", help="use this zip rather than fetching")
    p.add_argument("--no-flag", action="store_true",
                   help=f"leave {FLAG} unset (the control)")

    for name, text in (("start", "start wish.exe"), ("restart", "stop and start wish.exe")):
        p = sub.add_parser(name, help=text)
        holder(p)
        p.add_argument("--no-flag", action="store_true",
                       help=f"leave {FLAG} unset (the control)")

    p = sub.add_parser("stop", help="stop wish.exe only")
    holder(p)

    p = sub.add_parser("shot", help="save a screenshot")
    holder(p)
    p.add_argument("--window", choices=("wish", "winuae", "desktop"), default="wish")
    p.add_argument("--out", required=True)

    p = sub.add_parser("controls", help="list Wish's controls, from a session 1 task")
    holder(p)
    p.add_argument("--type", help="only this UI Automation type, such as RadioButton or MenuItem")

    p = sub.add_parser("click", help="click Wish's controls by name, in order (a menu path is "
                       "`File` `Preferences...`)")
    holder(p)
    p.add_argument("--type", help="only this UI Automation type")
    p.add_argument("--prefix", action="store_true",
                   help="when no control has exactly the name, accept one that starts with it")
    p.add_argument("names", nargs="+")

    p = sub.add_parser("log", help="copy Wish's debug logs from the guest")
    holder(p)
    p.add_argument("--out", required=True)

    p = sub.add_parser("down", help="stop Wish, stop WinUAE, release the lane")
    holder(p)
    return parser


def main(argv: list[str] | None = None,
         guest: Guest | None = None, lane: Any = None) -> int:
    args = _parser().parse_args(argv)
    guest = guest or Guest()
    try:
        if args.cmd == "fetch":
            print(fetch(guest, args.sha, pathlib.Path(args.dest) if args.dest else None))
        elif args.cmd == "up":
            for key, value in up(guest, lane or WinGuest(), args).items():
                print(f"{key}: {value}")
        elif args.cmd == "start":
            print(start_wish(guest, args.holder, not args.no_flag))
        elif args.cmd == "restart":
            print(restart_wish(guest, args.holder, not args.no_flag))
        elif args.cmd == "stop":
            print(stop_wish(guest, args.holder))
        elif args.cmd == "shot":
            size = shot(guest, args.holder, args.window, pathlib.Path(args.out))
            print(f"{args.out} ({size} bytes)")
        elif args.cmd == "controls":
            print("\n".join(ui(guest, args.holder, "controls", (), args.type)))
        elif args.cmd == "click":
            print("\n".join(ui(guest, args.holder, "click", tuple(args.names), args.type, args.prefix)))
        elif args.cmd == "log":
            print("\n".join(collect_log(guest, args.holder, pathlib.Path(args.out))))
        elif args.cmd == "down":
            for key, value in down(guest, lane or WinGuest(), args.holder).items():
                print(f"{key}: {value}")
    except (WinwishError, RouteError) as exc:
        print(f"winwish: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
