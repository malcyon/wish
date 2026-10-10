#!/usr/bin/env python3
"""Run the frozen Windows build of Wish beside WinUAE in the Windows VM's desktop session.

The Windows guest has no Python, so the real window is the `frozen-windows`
artifact that `.github/workflows/release.yml` builds for a pushed SHA.  This
fetches it with `gh`, copies it to `C:\\Amiga\\wish\\<sha>\\`, starts `wish.exe`
through an Interactive scheduled task (an ssh login is session 0 and cannot show a
window; see `winuae.ps1`), grabs the Wish window, stops and restarts it, and brings
the debug log back.  `up` without `--df0` starts no WinUAE but still takes every lane.
WinUAE itself is started through `winuaesession.WinGuest`, so
the lane claim, the audio proof and the receipts are the ones every other WinUAE
run uses.

    winwish.py fetch  --sha SHA
    winwish.py up     --sha SHA --holder H --mute-proof FILE [--df0 C:\\Amiga\\Disks\\a.adf] [--wait-lanes SECONDS]
    winwish.py stage-save --holder H --save LOCAL --folder REL
    winwish.py start  --holder H [--open GUEST_PATH] [--reseed [--travel-targets KEY=ID[,ID]]]
    winwish.py shot   --holder H --window wish --out wish.png
    winwish.py restart --holder H
    winwish.py click  --holder H --automation-id card_1_level_up
    winwish.py click  --holder H --expand Save
    winwish.py click  --holder H File "Save As..." --shot-after PNG
    winwish.py click  --holder H File Save --type MenuItem --controls-after FILE
    winwish.py display --holder H (--read | --set 1920x1080 --scale 150 | --restore) --out FILE
    winwish.py log    --holder H --out DIR
    winwish.py down   --holder H

Wish runs with `WISH_EXPERIMENTAL_AMIGA_WINUAE=1` (`--no-flag` leaves it unset, for
the control; `--map-only` sets it but leaves the action and Fast Travel flags unset)
and `WISH_DEBUG=1`.  `up --travel-targets KEY=ID[,ID]` seeds
`fast_travel_targets`, because the tab cannot pick a destination from the drop-down.
Its `APPDATA` and `LOCALAPPDATA` point at a private folder per holder, seeded with `diagnostics: true` because `WISH_DEBUG`
alone does not open the log file.  Every guest call goes through `winvm`, which
sets `BatchMode` and `SSH_ASKPASS_REQUIRE`, so a failure is an error, never a prompt.
"""

from __future__ import annotations

import argparse
import base64
import binascii
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
#: The spelling of `automap.amigaactions.ACTIONS_ENV` and
#: `automap.amigafasttravel.FAST_TRAVEL_ENV`; a test pins them equal.
ACTIONS_FLAG = "WISH_EXPERIMENTAL_AMIGA_ACTIONS"
FAST_TRAVEL_FLAG = "WISH_EXPERIMENTAL_AMIGA_FAST_TRAVEL"
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
#: Seconds for a display change, which waits for the new mode to settle twice.
DISPLAY_SECONDS = 60.0


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


def parse_travel_targets(specs: list[str] | None) -> dict[str, list[int]]:
    """`KEY=ID[,ID]` specs as the `fast_travel_targets` table Wish's settings hold.

    The WinUAE tab cannot pick from the Fast Travel drop-down (UI Automation's Select
    does not commit a Qt combo), so a run stages the one destination it will click.
    """
    table: dict[str, list[int]] = {}
    for spec in specs or []:
        key, sep, ids = spec.partition("=")
        if not sep or not GAME_KEY.match(key) or not ids:
            raise WinwishError(f"not KEY=ID[,ID]: {spec!r}")
        try:
            found = sorted({int(i, 0) for i in ids.split(",")})
        except ValueError:
            raise WinwishError(f"not KEY=ID[,ID]: {spec!r}") from None
        if found[0] < 0:
            raise WinwishError(f"not KEY=ID[,ID]: {spec!r}")
        table[key] = found
    return table


def settings_json(game: str | None = None, folder: str | None = None,
                  travel_targets: dict[str, list[int]] | None = None) -> str:
    """The settings file Wish starts with: the log on, a game folder and Fast Travel destinations when given.

    `game` is a `game_folders` key (`c64_port.GAMES[i].key` or an Amiga-only title's)
    and `folder` the guest folder holding that title's ADFs; without them Wish says
    "No game disks found" and draws no map.
    """
    values: dict[str, Any] = {"diagnostics": True}
    if game:
        values["game_folders"] = {game: folder}
    if travel_targets:
        values["fast_travel_targets"] = travel_targets
    return json.dumps(values, indent=1) + "\n"


def environment(flag: bool, holder: str, features: bool = True) -> dict[str, str]:
    """What `wish.exe` is started with; the flag is left unset for the control.

    With `features` false the backend flag is set but the action and Fast Travel
    flags are not, so the map attaches with those controls greyed.
    """
    env = {"APPDATA": rf"{run_dir(holder)}\appdata",
           "LOCALAPPDATA": rf"{run_dir(holder)}\local",
           "WISH_DEBUG": "1"}
    if flag:
        env[FLAG] = "1"
    if flag and features:
        env[ACTIONS_FLAG] = "1"
        env[FAST_TRAVEL_FLAG] = "1"
    return env


#: Cleared in the task whatever the holder's own session has, so the window can
#: reach no other backend and the flag-off control really has no Amiga row.
CLEARED = ("WISH_EXPERIMENTAL_AMIGA_FSUAE", ACTIONS_FLAG, FAST_TRAVEL_FLAG, "POR_MONITOR", "WISH_EXPERIMENTAL_C64_ULTIMATE",
           "POR_ULTIMATE", "WISH_ULTIMATE", "POR_ULTIMATE_PASSWORD", "WISH_ULTIMATE_PASSWORD")


# -- PowerShell run on the guest ---------------------------------------------

def q(text: str) -> str:
    """`text` as a single-quoted PowerShell string."""
    return winvmguest._ps_quote(text)


def write_file(path: str, text: str) -> str:
    """A PowerShell statement that writes `text` to `path` on the guest.

    The text goes as base64 bytes, not nested inside a second `-EncodedCommand`: each
    encoding multiplies the size by about 2.7, and a command line past 32,767
    characters is blocked by Windows ("exec request failed").  The BOM lets Windows
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


def open_argument(path: str) -> str:
    """`path` as the one argument Wish opens: in embedded double quotes so spaces survive."""
    if not path or '"' in path or "\n" in path or "\r" in path:
        raise WinwishError(f"not a path Wish can be opened with: {path!r}")
    return f'"{path}"'


def _task_body(env: dict[str, str], build: str, flag: bool, open_path: str | None = None) -> str:
    """What the task runs in session 1: set the environment, start Wish, wait for it.

    `Start-Process -Wait` because `&` returns at once for a GUI program, which would
    end the task while Wish was still up.  With `open_path`, Wish gets that save as
    its positional argument and opens on the editor tab.
    """
    lines = [f"Remove-Item Env:{k} -ErrorAction SilentlyContinue" for k in CLEARED]
    if not flag:
        lines.append(f"Remove-Item Env:{FLAG} -ErrorAction SilentlyContinue")
    lines += [f"$env:{k} = {q(v)}" for k, v in env.items()]
    lines += [f"$exe = Get-ChildItem -LiteralPath {q(build)} -Recurse -Filter wish.exe | Select-Object -First 1",
              "Start-Process -Wait -FilePath $exe.FullName -WorkingDirectory $exe.DirectoryName"
              + (f" -ArgumentList {q(open_argument(open_path))}, '--tab', 'editor'" if open_path else "")]
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
                 reseed: bool = True, open_path: str | None = None,
                 travel_targets: dict[str, list[int]] | None = None) -> str:
    """Seed the private settings, start `wish.exe` in session 1, wait for its window.

    The reply is `ok pid=N session=S window=H` or `fail ...`.  Session 0 is a
    failure: a window there is invisible to a screenshot.  The window is looked for
    by a task in session 1 (`window_probe`), because the ssh session cannot see it; a
    failure lists every `wish` process and every window the probe found.

    `disks` are ADFs already on the guest; they are copied into `disks_dir` and, with
    `game`, the settings point that title's folder there.  A start with `reseed`
    false (`start`, `restart`) leaves the settings of an earlier `up` in place and
    writes them only when there are none.  `open_path` is a save already on the guest
    that Wish opens on its editor tab.

    The match assumes the title starts with "Wish": `WishWindow.setWindowTitle` and
    `wish/window.py`'s `_retitle` give "Wish" plus an optional " [logging]", and nothing
    calls `_retitle` with another base.
    """
    build, run = build_root(holder), run_dir(holder)
    task_file = rf"{run}\task.ps1"
    args = f'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{task_file}"'
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
        # json block the file, which falls back to defaults and no log.
        *copy_disks,
        "$settings = \"$run\\appdata\\wish\\automap.json\"",
        f"{guard}[IO.File]::WriteAllText($settings, {q(settings_json(game if disks else None, disks_dir(holder), travel_targets))}, (New-Object Text.UTF8Encoding $false)){tail}",
        "$p = New-ScheduledTaskPrincipal -UserId \"$env:COMPUTERNAME\\$env:USERNAME\" -LogonType Interactive",
        "$s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries",
        write_file(task_file, _task_body(env, build, FLAG in env, open_path)),
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
#: Seconds `stop` waits for Wish to exit after its window is closed, before forcing it.
CLOSE_SECONDS = 10


def ui_timeout(count: int, action: str = "click") -> float:
    """Seconds to wait for a `click` of `count` names: the wait per name plus a fixed start.

    `controls` starts slower, because it compiles the MSAA helper and walks each dialog.
    """
    if action in ("controls", "close"):
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


def _expand_function() -> list[str]:
    """The only way `click --expand` touches a control; no `Invoke` is reachable from it."""
    return [
        "  function Use-Control($e) {",
        "    $o = $null",
        "    if ($e.TryGetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern, [ref]$o)) { $o.Expand(); return 'expanded' }",
        "    throw 'the control cannot be expanded'",
        "  }",
    ]


def _use_functions() -> list[str]:
    """How `click` uses a control: invoke, select, toggle, expand or close, in that order."""
    return [
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
    ]


def ui_inner(build: str, action: str, names: tuple[str, ...], kind: str | None, out: str,
             prefix: bool = False, automation_id: str | None = None,
             expand: bool = False, shot_after: str | None = None,
             controls_after: str | None = None) -> str:
    """What the session 1 task runs: list the controls of this holder's Wish, or click some.

    `action` is `controls` (one line per control: `Type|Name|AutomationId|enabled=B|state|RuntimeId|IsOffscreen|
    BoundingRectangle`, optionally only `kind`), `click` (each name in turn, so a menu is `File`,
    `Preferences`) or `close` (close each top-level window of this holder's Wish with
    `WindowPattern.Close()` and wait up to `CLOSE_SECONDS` for the process to exit; the
    line is `closed`, or `gone` when none was running).  With `automation_id`, `click`
    takes the one control whose `AutomationId` equals it or ends with `.` and it, in
    place of a name; `names` is then that id, and `prefix` is not used.  A name matches a control's Name exactly for the whole wait; with
    `prefix`, a prefix match is tried once the wait has run out.  The line reports the
    control's full name.  A disabled control is never invoked, because `Invoke` on one
    returns without an error; but a control under a modal dialog can still read enabled,
    so a click that the dialog swallows is not an error.  With `expand`, a `click` only
    uses `ExpandCollapsePattern`, so a split button opens its menu and is not invoked;
    a control without it fails with "the control cannot be expanded", and the script
    carries no code that invokes anything.  Every top-level window of
    every `wish.exe` under `build` is searched, so an open menu or dialog is found.
    UI Automation shows a modal dialog with no children; `controls` then reads that
    window through MSAA, whose lines read `Type|Name|Value|state=N`.  The answer is
    `ok` then the lines, or one `fail ...` line.  With `shot_after`, a `click` grabs the
    desktop into that guest path once its last name is used, in this same task, because a
    popup it opened is gone by the time a later task looks.  With `controls_after`, a
    `click` also writes one line for every control of `kind` (all when none) to that guest
    path once its last name is used, before the picture: `Type|Name|AutomationId|enabled=B|
    state|RuntimeId|IsOffscreen|BoundingRectangle`, so duplicates of one element can be told
    from distinct ones.  It is a file of its own, not part of the answer, so nothing
    shortens it.
    """
    tmp = out + ".tmp"
    names_ps = ", ".join(q(n) for n in names) or "@()"
    by_id = automation_id is not None
    if by_id and names != (automation_id,):
        raise WinwishError("an automation id is clicked alone")
    if expand and action != "click":
        raise WinwishError("only a click can expand")
    if shot_after is not None and action != "click":
        raise WinwishError("only a click can take a shot after")
    if controls_after is not None and action != "click":
        raise WinwishError("only a click can dump controls after")
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
        f"  if ($procs.Count -eq 0 -and {q(action)} -ne 'close') {{ throw 'no wish.exe of this holder is running' }}",
        "  function Get-Controls {",
        "    $found = New-Object System.Collections.ArrayList",
        # UI Automation can list one element many times (a Qt menu entry came back 51 times); one RuntimeId is one
        # control. An element whose RuntimeId cannot be read is kept.
        "    $seen = @{}",
        "    $keep = {",
        "      param($e)",
        "      $rid = $null",
        "      try { $rid = ($e.GetRuntimeId() -join '.') } catch { $rid = $null }",
        "      if ($rid) { if ($seen.ContainsKey($rid)) { return }; $seen[$rid] = $true }",
        "      [void]$found.Add($e)",
        "    }",
        "    foreach ($proc in $procs) {",
        "      $mine = New-Object System.Windows.Automation.PropertyCondition($UIA::ProcessIdProperty, $proc.Id)",
        "      foreach ($top in $UIA::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children, $mine)) {",
        "        & $keep $top",
        "        foreach ($e in $top.FindAll([System.Windows.Automation.TreeScope]::Descendants, "
        "[System.Windows.Automation.Condition]::TrueCondition)) { & $keep $e }",
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
        # A stale element throws on these reads; each yields an empty field so the line still prints.
        "  function Get-Detail($e) {",
        "    $rid = ''; $off = ''; $rect = ''",
        "    try { $rid = ($e.GetRuntimeId() -join '.') } catch { $rid = '' }",
        "    try { $off = '' + $e.Current.IsOffscreen } catch { $off = '' }",
        "    try { $rect = '' + $e.Current.BoundingRectangle } catch { $rect = '' }",
        "    return (Get-Line $e) + '|' + $rid + '|offscreen=' + $off + '|' + $rect",
        "  }",
        *(_expand_function() if expand else _use_functions()),
        f"  if ({q(action)} -eq 'close') {{",
        "    if ($procs.Count -eq 0) { [void]$lines.Add('gone') } else {",
        "      $ids = @($procs | ForEach-Object { $_.Id })",
        "      foreach ($proc in $procs) {",
        "        $mine = New-Object System.Windows.Automation.PropertyCondition($UIA::ProcessIdProperty, $proc.Id)",
        "        foreach ($top in $UIA::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children, $mine)) {",
        "          $o = $null",
        "          if ($top.TryGetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern, [ref]$o)) { $o.Close() }",
        "        }",
        "      }",
        f"      $until = (Get-Date).AddSeconds({CLOSE_SECONDS})",
        "      while (@(Get-Process -Id $ids -ErrorAction SilentlyContinue).Count -gt 0 -and (Get-Date) -lt $until) { Start-Sleep -Milliseconds 200 }",
        f"      if (@(Get-Process -Id $ids -ErrorAction SilentlyContinue).Count -gt 0) {{ throw 'wish.exe still running {CLOSE_SECONDS}s after its window was closed' }}",
        "      [void]$lines.Add('closed')",
        "    }",
        f"  }} elseif ({q(action)} -eq 'controls') {{",
        "    foreach ($e in Get-Controls) {",
        "      if ($kind -eq '' -or (Get-Kind $e) -eq $kind) { [void]$lines.Add((Get-Detail $e)) }",
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
        *(["        $all = @(Get-Controls | Where-Object { $_.Current.AutomationId -ne '' -and ($kind -eq '' -or (Get-Kind $_) -eq $kind) })",
           "        $hit = @($all | Where-Object { $_.Current.AutomationId -eq $name -or $_.Current.AutomationId.EndsWith('.' + $name, [StringComparison]::OrdinalIgnoreCase) })"]
          if by_id else
          ["        $all = @(Get-Controls | Where-Object { $_.Current.Name -ne '' -and ($kind -eq '' -or (Get-Kind $_) -eq $kind) })",
           "        $hit = @($all | Where-Object { $_.Current.Name -eq $name })"]),
        "        if ($hit.Count -eq 0 -and $expired -and $prefix) { $hit = @($all | Where-Object { $_.Current.Name.StartsWith($name) }) }",
        "        if ($hit.Count -gt 0 -or $expired) { break }",
        "        if ((Get-Date) -gt $until) { if ($prefix) { $expired = $true } else { break } } else { Start-Sleep -Milliseconds 200 }",
        "      }",
        f"      if ($hit.Count -eq 0) {{ throw \"no control {'with automation id' if by_id else 'named'} $name\" }}",
        "      if ($hit.Count -gt 1) { throw \"$($hit.Count) controls match ${name}: \" + (($hit | ForEach-Object { Get-Line $_ }) -join ' ; ') }",
        "      if (-not $hit[0].Current.IsEnabled) { throw \"$($hit[0].Current.Name) is disabled\" }",
        "      [void]$lines.Add($hit[0].Current.Name + ' -> ' + (Use-Control $hit[0]))",
        "      Start-Sleep -Milliseconds 400",
        "    }",
        *(["    " + line for line in _dump_lines(controls_after)] if controls_after else []),
        *(["    " + line for line in winvmguest.grab_lines(shot_after)] if shot_after else []),
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


def _dump_lines(path: str) -> list[str]:
    """The guest PowerShell, inside `ui_inner`'s click branch, that writes the controls dump to `path`."""
    tmp = path + ".tmp"
    return [
        "$dump = New-Object System.Collections.ArrayList",
        "foreach ($e in Get-Controls) {",
        "  if ($kind -ne '' -and (Get-Kind $e) -ne $kind) { continue }",
        "  [void]$dump.Add((Get-Detail $e))",
        "}",
        "$dump = @($dump | ForEach-Object { [regex]::Replace($_, '[^\\x20-\\x7e]', "
        "{ param($m) '\\u' + ([int][char]$m.Value).ToString('x4') }) })",
        f"[IO.File]::WriteAllLines({q(tmp)}, [string[]]$dump)",
        f"Move-Item -Force {q(tmp)} {q(path)}",
    ]


def ui_file(token: str) -> str:
    """Where a `ui_inner` script is put on the guest, for the task to run with `-File`."""
    if not re.fullmatch(r"[A-Za-z0-9]{1,32}", token):
        raise WinwishError(f"not a usable token: {token!r}")
    return rf"C:\Users\Public\wish-ui-{token}.ps1"


def ui_shot_file(token: str) -> str:
    """Where a `click --shot-after` task leaves its desktop picture on the guest."""
    if not re.fullmatch(r"[A-Za-z0-9]{1,32}", token):
        raise WinwishError(f"not a usable token: {token!r}")
    return rf"C:\Users\Public\wish-ui-{token}.png"


def ui_dump_file(token: str) -> str:
    """Where a `click --controls-after` task leaves its controls dump on the guest."""
    if not re.fullmatch(r"[A-Za-z0-9]{1,32}", token):
        raise WinwishError(f"not a usable token: {token!r}")
    return rf"C:\Users\Public\wish-ui-{token}.dump.txt"


DUMP_BEGIN = "WISHUI-DUMP-BEGIN"
DUMP_END = "WISHUI-DUMP-END"

#: Added to a UI call's wait when it also takes a picture.
SHOT_EXTRA_SECONDS = 5


def ui_script(token: str, timeout: float, shot: bool = False, dump: bool = False) -> str:
    """What the ssh session runs: run the put `ui_file` in session 1 and print its answer between markers.

    The script itself is copied across with `winvm put` rather than carried in this
    command, because a command line over 32,767 characters is blocked.  With `shot`, the
    desktop picture the task took is printed after the lines, between
    `winvmguest.SHOT_BEGIN` and `SHOT_END`, and removed.  With `dump`, the controls dump
    follows between `DUMP_BEGIN` and `DUMP_END` as base64, so a line is never cut or
    re-encoded on the way, and is removed.
    """
    task = f"wish-ui-{token}"
    out = rf"C:\Users\Public\{task}.txt"
    file = ui_file(token)
    png = ui_shot_file(token)
    dump_file = ui_dump_file(token)
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
        *([f"  if (Test-Path {q(png)}) {{",
           f"    '{winvmguest.SHOT_BEGIN}'",
           f"    [Convert]::ToBase64String([IO.File]::ReadAllBytes({q(png)}), 'InsertLineBreaks')",
           f"    '{winvmguest.SHOT_END}'",
           "  }"] if shot else []),
        *([f"  if (Test-Path {q(dump_file)}) {{",
           f"    '{DUMP_BEGIN}'",
           f"    [Convert]::ToBase64String([IO.File]::ReadAllBytes({q(dump_file)}), 'InsertLineBreaks')",
           f"    '{DUMP_END}'",
           "  }"] if dump else []),
        "} finally {",
        "  Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue",
        "  Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue",
        f"  Remove-Item $out, \"$out.tmp\", {q(file)}"
        + (f", {q(png)}, {q(png + '.tmp')}" if shot else "")
        + (f", {q(dump_file)}, {q(dump_file + '.tmp')}" if dump else "") + " -ErrorAction SilentlyContinue",
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


def decode_dump(text: str) -> list[str]:
    """The controls dump between the markers in a `ui_script` reply, every line."""
    lines = [line.strip() for line in text.splitlines()]
    try:
        start = lines.index(DUMP_BEGIN)
        end = lines.index(DUMP_END, start + 1)
    except ValueError:
        raise WinwishError("the controls dump came back without its markers") from None
    try:
        data = base64.b64decode("".join(lines[start + 1:end]), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise WinwishError(f"the controls dump's base64 does not decode: {exc}") from None
    return data.decode("ascii").splitlines()


def session_one(guest: "Guest", holder: str, make_inner: Callable[[str], str],
                timeout: float, kind: str | None = None) -> list[str]:
    """Run a script in session 1 and return the lines after its `ok`.

    `make_inner` is given the guest path the script must write its answer to.  The
    script is put on the guest as a file and run by a task, because session 0 cannot
    see or change the console's desktop.
    """
    return _session_one(guest, holder, make_inner, timeout, kind, False)[0]


def _session_one(guest: "Guest", holder: str, make_inner: Callable[[str], str],
                 timeout: float, kind: str | None, shot: bool,
                 dump: list[str] | None = None) -> tuple[list[str], bytes | None]:
    """`session_one`; with `shot`, also the PNG the script left at `ui_shot_file`.

    When `dump` is a list, the controls dump the script left at `ui_dump_file` is put into it.
    """
    guest.holds_lane(holder)
    token = secrets.token_hex(6)
    inner = make_inner(rf"C:\Users\Public\wish-ui-{token}.txt")
    answered = False
    try:
        with tempfile.TemporaryDirectory() as tmp:
            local = pathlib.Path(tmp) / "ui.ps1"
            local.write_bytes(b"\xef\xbb\xbf" + inner.encode("utf-8"))
            guest.winvm("put", str(local), ui_file(token).replace("\\", "/"), timeout=CALL_SECONDS)
        rc, text = guest.run(["winvm", "ps", ui_script(token, timeout, shot, dump is not None)],
                             timeout + 20)
        lines = ui_lines(text, kind)
        png = None
        if shot:
            try:
                png = winvmguest.decode_shot(text)
            except winvmguest.WinvmError as exc:
                raise WinwishError(f"no picture came back after the click: {exc}") from None
        if dump is not None:
            dump[:] = decode_dump(text)
        answered = True
        return lines, png
    finally:
        if not answered:
            # The ssh script removes the file itself when it runs; this covers a put that
            # landed and a script that never did.
            _quietly(guest.ps, "Remove-Item -LiteralPath "
                     f"{q(ui_file(token))} -Force -ErrorAction SilentlyContinue\n'ok'")


def ui(guest: "Guest", holder: str, action: str, names: tuple[str, ...] = (),
       kind: str | None = None, prefix: bool = False,
       automation_id: str | None = None, expand: bool = False) -> list[str]:
    """List Wish's controls (`controls`), click `names` in turn or the one control with
    `automation_id` (`click`, or open its menu with `expand`), or close Wish's windows (`close`)."""
    return _ui(guest, holder, action, names, kind, prefix, automation_id, expand, False)[0]


def ui_shot(guest: "Guest", holder: str, names: tuple[str, ...] = (),
            kind: str | None = None, prefix: bool = False,
            automation_id: str | None = None) -> tuple[list[str], bytes]:
    """`ui` for a `click`, plus the desktop picture the same task took after its last name."""
    lines, png = _ui(guest, holder, "click", names, kind, prefix, automation_id, False, True)
    assert png is not None
    return lines, png


def ui_dump(guest: "Guest", holder: str, names: tuple[str, ...] = (),
            kind: str | None = None, prefix: bool = False,
            automation_id: str | None = None,
            shot: bool = False) -> tuple[list[str], list[str], bytes | None]:
    """`ui` for a `click`, plus every control of `kind` as the same task saw it after the
    last name (see `ui_inner`), and with `shot` the desktop picture too."""
    dump: list[str] = []
    lines, png = _ui(guest, holder, "click", names, kind, prefix, automation_id, False, shot, dump)
    return lines, dump, png


def _ui(guest: "Guest", holder: str, action: str, names: tuple[str, ...], kind: str | None,
        prefix: bool, automation_id: str | None, expand: bool,
        shot: bool, dump: list[str] | None = None) -> tuple[list[str], bytes | None]:
    if automation_id is not None:
        if names:
            raise WinwishError("give an automation id or names, not both")
        if prefix:
            raise WinwishError("--prefix matches names, so it cannot be used with --automation-id")
        names = (automation_id,)
    if len(names) > UI_MAX_NAMES:
        raise WinwishError(f"click at most {UI_MAX_NAMES} names at once, not {len(names)}")
    if shot and action != "click":
        raise WinwishError("only a click can take a shot after")
    extra = SHOT_EXTRA_SECONDS if shot else 0
    return _session_one(
        guest, holder,
        lambda out: ui_inner(build_root(holder), action, names, kind, out, prefix,
                             automation_id, expand,
                             out.removesuffix(".txt") + ".png" if shot else None,
                             out.removesuffix(".txt") + ".dump.txt" if dump is not None else None),
        ui_timeout(len(names), action) + extra, kind, shot, dump)


# -- the guest's display ---------------------------------------------------------

#: The percentages Windows offers in its scale list, in order; the Settings app and
#: `DisplayConfigGetDeviceInfo` count steps along it, 100 % being step 0.
SCALES = (100, 125, 150, 175, 200, 225, 250, 300, 350, 400, 450, 500)
MODE = re.compile(r"^(\d{3,5})x(\d{3,5})$")
DISPLAY_ACTIONS = ("read", "set", "restore", "sidecar")

#: Win32 and CCD calls for the display, from one compiled type.  The scale calls are
#: the undocumented `DisplayConfigGetDeviceInfo` type -3 (32 bytes) and
#: `DisplayConfigSetDeviceInfo` type -4 (24 bytes) that the Settings app uses; the
#: structures are plain byte buffers, so no layout is declared that Windows could
#: disagree with.
DISPLAY_CODE = r"""
using System; using System.Runtime.InteropServices; using System.Text;
public class WishDisp {
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
  public struct DEVMODE {
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst=32)] public string dmDeviceName;
    public ushort dmSpecVersion, dmDriverVersion, dmSize, dmDriverExtra;
    public uint dmFields;
    public int dmPositionX, dmPositionY;
    public uint dmDisplayOrientation, dmDisplayFixedOutput;
    public short dmColor, dmDuplex, dmYResolution, dmTTOption, dmCollate;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst=32)] public string dmFormName;
    public ushort dmLogPixels;
    public uint dmBitsPerPel, dmPelsWidth, dmPelsHeight, dmDisplayFlags, dmDisplayFrequency,
      dmICMMethod, dmICMIntent, dmMediaType, dmDitherType, dmReserved1, dmReserved2,
      dmPanningWidth, dmPanningHeight;
  }
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern bool EnumDisplaySettingsW(string dev, int mode, ref DEVMODE dm);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int ChangeDisplaySettingsExW(string dev, ref DEVMODE dm, IntPtr hwnd, uint flags, IntPtr lp);
  [DllImport("user32.dll")] static extern bool SetProcessDpiAwarenessContext(IntPtr c);
  [DllImport("user32.dll")] static extern IntPtr MonitorFromPoint(POINT p, uint flags);
  [DllImport("shcore.dll")] static extern int GetDpiForMonitor(IntPtr m, int type, out uint x, out uint y);
  [DllImport("user32.dll")] static extern uint GetDpiForWindow(IntPtr h);
  [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll", EntryPoint="SystemParametersInfoW")] static extern bool SpiBytes(uint a, uint b, byte[] p, uint f);
  [DllImport("user32.dll", EntryPoint="SystemParametersInfoW")] static extern bool SpiRect(uint a, uint b, out RECT p, uint f);
  [DllImport("user32.dll")] static extern int GetDisplayConfigBufferSizes(uint f, out uint np, out uint nm);
  [DllImport("user32.dll")] static extern int QueryDisplayConfig(uint f, ref uint np, byte[] paths, ref uint nm, byte[] modes, IntPtr topo);
  [DllImport("user32.dll")] static extern int DisplayConfigGetDeviceInfo(byte[] p);
  [DllImport("user32.dll")] static extern int DisplayConfigSetDeviceInfo(byte[] p);

  public static void Aware() { SetProcessDpiAwarenessContext(new IntPtr(-4)); }
  static DEVMODE Dm() { var d = new DEVMODE(); d.dmSize = (ushort)Marshal.SizeOf(typeof(DEVMODE)); return d; }

  // Mode(-1) is the current mode; Mode(n) the nth offered one, or null past the last.
  public static int[] Mode(int index) {
    var d = Dm();
    if (!EnumDisplaySettingsW(null, index, ref d)) return null;
    return new int[] { (int)d.dmPelsWidth, (int)d.dmPelsHeight, (int)d.dmBitsPerPel, (int)d.dmDisplayFrequency };
  }

  // The mode of this size nearest the wanted bit depth and refresh rate (0 meaning the
  // current one), applied dynamically: CDS flags 0 writes nothing to the registry.
  public static int SetMode(int w, int h, int bits, int hz) {
    var cur = Dm(); EnumDisplaySettingsW(null, -1, ref cur);
    if (bits > 0) cur.dmBitsPerPel = (uint)bits;
    if (hz > 0) cur.dmDisplayFrequency = (uint)hz;
    var best = Dm(); int bestScore = -1;
    for (int i = 0; ; i++) {
      var d = Dm();
      if (!EnumDisplaySettingsW(null, i, ref d)) break;
      if (d.dmPelsWidth != (uint)w || d.dmPelsHeight != (uint)h) continue;
      int score = (d.dmBitsPerPel == cur.dmBitsPerPel ? 2 : 0) + (d.dmDisplayFrequency == cur.dmDisplayFrequency ? 1 : 0);
      if (score > bestScore) { best = d; bestScore = score; }
    }
    if (bestScore < 0) return -100;
    best.dmFields = 0x80000 | 0x100000 | 0x40000 | 0x400000;
    return ChangeDisplaySettingsExW(null, ref best, IntPtr.Zero, 0, IntPtr.Zero);
  }

  static byte[] Header(int type, int size) {
    uint np, nm;
    if (GetDisplayConfigBufferSizes(2, out np, out nm) != 0) throw new Exception("GetDisplayConfigBufferSizes failed");
    var paths = new byte[np * 72]; var modes = new byte[nm * 64];
    if (QueryDisplayConfig(2, ref np, paths, ref nm, modes, IntPtr.Zero) != 0 || np == 0) throw new Exception("QueryDisplayConfig found no active path");
    var p = new byte[size];
    BitConverter.GetBytes(type).CopyTo(p, 0);
    BitConverter.GetBytes(size).CopyTo(p, 4);
    Array.Copy(paths, 0, p, 8, 8);
    Array.Copy(paths, 8, p, 16, 4);
    return p;
  }
  public static int[] ScaleRange() {
    var p = Header(-3, 32);
    int rc = DisplayConfigGetDeviceInfo(p);
    if (rc != 0) throw new Exception("DisplayConfigGetDeviceInfo returned " + rc);
    return new int[] { BitConverter.ToInt32(p, 20), BitConverter.ToInt32(p, 24), BitConverter.ToInt32(p, 28) };
  }
  public static int SetScale(int rel) {
    var p = Header(-4, 24);
    BitConverter.GetBytes(rel).CopyTo(p, 20);
    return DisplayConfigSetDeviceInfo(p);
  }

  public static uint MonitorDpi() { uint x, y; GetDpiForMonitor(MonitorFromPoint(new POINT(), 1), 0, out x, out y); return x; }
  public static int[] WorkArea() { RECT r; SpiRect(48, 0, out r, 0); return new int[] { r.L, r.T, r.R, r.B }; }
  // lfMessageFont of NONCLIENTMETRICS (504 bytes): the height at 408, the face name 28 bytes on.
  public static string MessageFont() {
    var b = new byte[504]; BitConverter.GetBytes(504).CopyTo(b, 0);
    if (!SpiBytes(0x29, 504, b, 0)) return "|0";
    var face = Encoding.Unicode.GetString(b, 408 + 28, 64);
    int nul = face.IndexOf('\0'); if (nul >= 0) face = face.Substring(0, nul);
    return face + "|" + BitConverter.ToInt32(b, 408);
  }
  public static int[] WindowRect(IntPtr h) { RECT r; GetWindowRect(h, out r); return new int[] { r.L, r.T, r.R, r.B }; }
  public static uint WindowDpi(IntPtr h) { return GetDpiForWindow(h); }
}
"""


def display_journal(holder: str) -> str:
    """Where the guest's display, as it was before the first `display --set`, is kept."""
    return rf"{run_dir(holder)}\display-original.json"


def display_pending_script(holder: str) -> str:
    """Say `ok journal` when a `display --set` left the display changed, else `ok none`."""
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        f"if (Test-Path -LiteralPath {q(display_journal(holder))}) {{ 'ok journal' }} else {{ 'ok none' }}",
    ])


#: The state of the display as one ordered table, which `ConvertTo-Json` prints.
#: The scale may fail on a build that does not take the calls; that is recorded as an
#: `error` so the rest of the read still comes back.
DISPLAY_STATE = [
    "  function Get-DisplayState {",
    "    $m = [WishDisp]::Mode(-1)",
    "    $modes = New-Object System.Collections.ArrayList",
    "    for ($i = 0; $i -lt 2000; $i++) {",
    "      $d = [WishDisp]::Mode($i)",
    "      if (-not $d) { break }",
    "      [void]$modes.Add([ordered]@{ w = $d[0]; h = $d[1]; bits = $d[2]; hz = $d[3] })",
    "    }",
    "    $a = [WishDisp]::WorkArea()",
    f"    $scales = @({', '.join(str(n) for n in SCALES)})",
    "    try {",
    "      $sr = [WishDisp]::ScaleRange()",
    "      $rec = [Math]::Abs($sr[0])",
    "      $scale = [ordered]@{ percent = $scales[$rec + $sr[1]]; allowed = @($scales[0..($rec + $sr[2])]); "
    "min_rel = $sr[0]; cur_rel = $sr[1]; max_rel = $sr[2] }",
    "    } catch { $scale = [ordered]@{ error = $_.Exception.Message } }",
    "    $ta = (Get-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Accessibility' -Name TextScaleFactor "
    "-ErrorAction SilentlyContinue).TextScaleFactor",
    "    if (-not $ta) { $ta = 100 }",
    "    $f = ([WishDisp]::MessageFont()) -split '\\|'",
    "    $cv = Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion'",
    "    return [ordered]@{",
    "      build = ('{0}.{1}' -f $cv.CurrentBuild, $cv.UBR)",
    "      mode = [ordered]@{ width = $m[0]; height = $m[1]; bits = $m[2]; hz = $m[3] }",
    "      modes = @($modes)",
    "      work_area = [ordered]@{ left = $a[0]; top = $a[1]; right = $a[2]; bottom = $a[3] }",
    "      scale = $scale",
    "      dpi = [int][WishDisp]::MonitorDpi()",
    "      text_scale = [int]$ta",
    "      font = [ordered]@{ face = $f[0]; height = [int]$f[1] }",
    "      observed_utc = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')",
    "    }",
    "  }",
    "  function ConvertTo-Line($x) { return ($x | ConvertTo-Json -Depth 6 -Compress) }",
]

#: Set the scale to `$pct` percent, or throw naming the percentages the mode allows.
DISPLAY_SET_SCALE = [
    "  function Set-Scale([int]$pct) {",
    f"    $scales = @({', '.join(str(n) for n in SCALES)})",
    "    $sr = [WishDisp]::ScaleRange()",
    "    $rec = [Math]::Abs($sr[0])",
    "    $at = [Array]::IndexOf($scales, $pct)",
    "    if ($at -lt 0 -or $at -gt ($rec + $sr[2])) { "
    "throw ('a scale of ' + $pct + '% is not allowed at this size; allowed: ' + (@($scales[0..($rec + $sr[2])]) -join ', ') + '%') }",
    "    $rc = [WishDisp]::SetScale($at - $rec)",
    "    if ($rc -ne 0) { throw ('DisplayConfigSetDeviceInfo returned ' + $rc) }",
    "  }",
    "  function Set-Size([int]$w, [int]$h, [int]$bits = 0, [int]$hz = 0) {",
    "    $rc = [WishDisp]::SetMode($w, $h, $bits, $hz)",
    "    if ($rc -ne 0) { throw ('ChangeDisplaySettingsEx returned ' + $rc + ' for ' + $w + 'x' + $h) }",
    "  }",
]


def display_inner(holder: str, action: str, out: str, width: int = 0, height: int = 0,
                  percent: int = 0) -> str:
    """What the session 1 task runs to read, set or restore the display.

    `read` prints the state as one JSON line, and `sidecar` adds the Wish window's
    rectangle, DPI and executable hash.  `set` writes the state to the journal first
    (unless an earlier `set` already did, so the journal always holds the original),
    then changes the mode, then the scale, reads back and fails if either differs.
    `restore` applies the journal's mode and scale, reads back, and deletes the
    journal only when both match.  The answer is `ok` and the line, or one `fail ...`.
    """
    if action not in DISPLAY_ACTIONS:
        raise WinwishError(f"not a display action: {action!r}")
    tmp = out + ".tmp"
    journal = display_journal(holder)
    body: list[str]
    if action == "read":
        body = ["    $line = ConvertTo-Line (Get-DisplayState)"]
    elif action == "sidecar":
        body = [
            "    $state = Get-DisplayState",
            f"    $root = {q(run_dir(holder))}",
            "    $w = Get-Process -Name wish -ErrorAction SilentlyContinue | "
            "Where-Object { $_.Path -like \"$root\\*\" -and $_.MainWindowHandle -ne 0 } | Select-Object -First 1",
            "    if ($w) {",
            "      $r = [WishDisp]::WindowRect($w.MainWindowHandle)",
            "      $state['wish'] = [ordered]@{ path = $w.Path; "
            "sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $w.Path).Hash.ToLower(); "
            "window = [ordered]@{ left = $r[0]; top = $r[1]; right = $r[2]; bottom = $r[3] }; "
            "dpi = [int][WishDisp]::WindowDpi($w.MainWindowHandle) }",
            "    } else { $state['wish'] = $null }",
            "    $line = ConvertTo-Line $state",
        ]
    elif action == "set":
        body = [
            f"    $journal = {q(journal)}",
            "    $before = Get-DisplayState",
            # The original goes to disk before anything is changed, so a failure half way
            # through still leaves what `restore` needs.
            "    if (-not (Test-Path -LiteralPath $journal)) { "
            "[IO.File]::WriteAllText($journal, (ConvertTo-Line $before), (New-Object Text.UTF8Encoding $false)) }",
            f"    Set-Size {int(width)} {int(height)}",
            "    Start-Sleep -Milliseconds 1500",
            f"    Set-Scale {int(percent)}",
            "    Start-Sleep -Milliseconds 1500",
            "    $after = Get-DisplayState",
            f"    if ($after.mode.width -ne {int(width)} -or $after.mode.height -ne {int(height)} -or $after.scale.percent -ne {int(percent)}) {{",
            "      throw ('the display reads back ' + $after.mode.width + 'x' + $after.mode.height + ' at ' + $after.scale.percent + "
            f"'%, not {int(width)}x{int(height)} at {int(percent)}%; offered sizes: ' + "
            "((@($after.modes | ForEach-Object { '' + $_.w + 'x' + $_.h }) | Select-Object -Unique) -join ', ') + "
            "'; allowed scales: ' + (@($after.scale.allowed) -join ', ') + '%')",
            "    }",
            "    $line = '{\"original\":' + (Get-Content -Raw -LiteralPath $journal).Trim() + ',\"after\":' + (ConvertTo-Line $after) + '}'",
        ]
    else:
        body = [
            f"    $journal = {q(journal)}",
            "    if (-not (Test-Path -LiteralPath $journal)) { throw 'there is no display journal to restore' }",
            "    $orig = Get-Content -Raw -LiteralPath $journal | ConvertFrom-Json",
            "    Set-Size ([int]$orig.mode.width) ([int]$orig.mode.height) ([int]$orig.mode.bits) ([int]$orig.mode.hz)",
            "    Start-Sleep -Milliseconds 1500",
            "    if ($orig.scale.percent) { Set-Scale ([int]$orig.scale.percent); Start-Sleep -Milliseconds 1500 }",
            "    $after = Get-DisplayState",
            "    if ($after.mode.width -ne $orig.mode.width -or $after.mode.height -ne $orig.mode.height -or "
            "($orig.mode.bits -and $after.mode.bits -ne $orig.mode.bits) -or "
            "($orig.mode.hz -and $after.mode.hz -ne $orig.mode.hz) -or "
            "($orig.scale.percent -and $after.scale.percent -ne $orig.scale.percent)) {",
            "      throw ('the display reads back ' + $after.mode.width + 'x' + $after.mode.height + ' at ' + $after.scale.percent + "
            "'%, not the recorded ' + $orig.mode.width + 'x' + $orig.mode.height + ' at ' + $orig.scale.percent + '%; the journal is kept')",
            "    }",
            "    Remove-Item -LiteralPath $journal -Force",
            "    $line = '{\"restored\":' + (ConvertTo-Line $after) + '}'",
        ]
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        "$lines = New-Object System.Collections.ArrayList",
        "try {",
        "  Add-Type -TypeDefinition @'",
        *DISPLAY_CODE.strip().splitlines(),
        "'@",
        "  [WishDisp]::Aware()",
        *DISPLAY_STATE,
        *DISPLAY_SET_SCALE,
        "  if ($true) {",
        *body,
        "    [void]$lines.Add($line)",
        "  }",
        "  $answer = @('ok') + $lines",
        "} catch {",
        "  $answer = @('fail ' + $_.Exception.Message)",
        "}",
        # ASCII only, as `ui_inner`: a non-ASCII character becomes a JSON `\u` escape.
        "$answer = @($answer | ForEach-Object { [regex]::Replace($_, '[^\\x20-\\x7e]', "
        "{ param($m) '\\u' + ([int][char]$m.Value).ToString('x4') }) })",
        f"[IO.File]::WriteAllLines({q(tmp)}, [string[]]$answer)",
        f"Move-Item -Force {q(tmp)} {q(out)}",
        "[Environment]::Exit(0)",
    ])


def offered_sizes(state: dict[str, Any]) -> list[str]:
    """The `WxH` sizes a display read lists, each once, smallest width first."""
    seen = {(m["w"], m["h"]) for m in state.get("modes", [])}
    return [f"{w}x{h}" for w, h in sorted(seen)]


def display(guest: "Guest", holder: str, action: str, width: int = 0, height: int = 0,
            percent: int = 0) -> dict[str, Any]:
    """Run a display `action` in session 1 and return its JSON answer.

    A `set` first reads the display and fails, before changing anything, when the
    size is not one the guest offers or the percentage is not in `SCALES`.
    """
    if action == "set":
        if percent not in SCALES:
            raise WinwishError(f"a scale of {percent}% is not one Windows lists; "
                               f"the list is {', '.join(str(n) for n in SCALES)}%")
        offered = offered_sizes(display(guest, holder, "read"))
        if f"{width}x{height}" not in offered:
            raise WinwishError(f"{width}x{height} is not an offered mode; "
                               f"offered: {', '.join(offered) or 'none'}")
    lines = session_one(guest, holder,
                        lambda out: display_inner(holder, action, out, width, height, percent),
                        DISPLAY_SECONDS)
    try:
        return json.loads(lines[0])
    except (IndexError, ValueError):
        raise WinwishError(f"the display {action} answered with no JSON: {lines[:1]}") from None


def restore_pending_display(guest: "Guest", holder: str) -> str:
    """Put the display back when a `display --set` changed it; says what it did.

    Only an exact `ok journal` from the guest counts, so a holder that never set the
    display costs one cheap call and no session 1 task.
    """
    if guest.ps(display_pending_script(holder)).strip() != "ok journal":
        return "ok unchanged"
    display(guest, holder, "restore")
    return "ok restored"


def sidecar(guest: "Guest", holder: str, window: str, png: pathlib.Path) -> pathlib.Path:
    """Write the display, DPI, font and Wish window beside `png` as `<png>.json`."""
    state = display(guest, holder, "sidecar")
    path = png.with_name(png.name + ".json")
    path.write_text(json.dumps({"holder": holder, "window": window, "png": png.name, **state},
                               indent=1) + "\n", encoding="utf-8")
    return path


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


SAVES_FOLDER = "saves"
#: Windows' `MAX_PATH` less the terminating NUL; a longer path needs the `\\?\` prefix,
#: which the Qt file dialog does not use.
MAX_GUEST_PATH = 259
BAD_FOLDER_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')


def save_guest_path(holder: str, folder: str, name: str) -> str:
    """Where `stage-save` puts `name`: `<run_dir>\\saves\\<folder>\\<name>`, checked.

    `folder` is relative, so it may hold neither `..`, a drive, nor a leading
    separator, and the whole path must fit in `MAX_GUEST_PATH` characters.
    """
    rel = folder.replace("/", "\\")
    if (not rel or ".." in rel or rel.startswith("\\") or BAD_FOLDER_CHARS.search(rel)
            or any(not part for part in rel.split("\\"))):
        raise WinwishError(f"not a folder under the holder's saves: {folder!r}")
    if BAD_FOLDER_CHARS.search(name) or "\\" in name or "/" in name or name in ("", ".", ".."):
        raise WinwishError(f"not a file name: {name!r}")
    path = rf"{run_dir(holder)}\{SAVES_FOLDER}\{rel}\{name}"
    if len(path) > MAX_GUEST_PATH:
        raise WinwishError(f"{path} is {len(path)} characters; Windows allows {MAX_GUEST_PATH}")
    return path


def hash_script(path: str, sha: str) -> str:
    """Say `ok sha256=...` when the guest's file hashes to `sha`, else `fail ...`."""
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        f"$got = (Get-FileHash -Algorithm SHA256 -LiteralPath {q(path)}).Hash.ToLower()",
        f"if ($got -ne {q(sha.lower())}) {{ \"fail the copy on the guest hashes to $got, not {sha.lower()}\"; exit 1 }}",
        "'ok sha256=' + $got",
    ])


def stage_save(guest: Guest, holder: str, local: pathlib.Path, folder: str) -> tuple[str, str]:
    """Copy a save to the guest under the holder's saves folder and check its hash there.

    Returns the guest path and the SHA-256, which the guest has confirmed equals the
    local file's.  Nothing is copied when the folder or the path length is not allowed.
    """
    if not local.is_file():
        raise WinwishError(f"{local} is not a file")
    path = save_guest_path(holder, folder, local.name)
    guest.holds_lane(holder)
    sha = file_sha256(local)
    here = path.rsplit("\\", 1)[0]
    guest.ps(mkdir_script(here))
    guest.winvm("put", str(local), here.replace("\\", "/") + "/", timeout=COPY_SECONDS)
    guest.ps(hash_script(path, sha))
    return path, sha


def probe_close_script(holder: str) -> str:
    """Remove the holder's probe task; for a start that ended without reaching its own cleanup."""
    return "\n".join([
        f"Unregister-ScheduledTask -TaskName {q(probe_task_name(holder))} -Confirm:$false -ErrorAction SilentlyContinue",
        "'ok'",
    ])


def start_wish(guest: Guest, holder: str, flag: bool = True, disks: tuple[str, ...] = (),
               game: str | None = None, reseed: bool = False,
               open_path: str | None = None,
               travel_targets: dict[str, list[int]] | None = None,
               features: bool = True) -> str:
    guest.holds_lane(holder)
    try:
        return guest.ps(start_script(holder, environment(flag, holder, features), disks=disks,
                                     game=game, reseed=reseed, open_path=open_path,
                                     travel_targets=travel_targets),
                        timeout=START_SECONDS + 30)
    except WinwishError:
        _quietly(guest.ps, probe_close_script(holder))
        raise


def stop_wish(guest: Guest, holder: str) -> str:
    """Close Wish's window and wait; force `wish.exe` only if that did not end it.

    A forced stop can land while Wish has a request to WinUAE's pipe unanswered, and
    WinUAE then closes the pipe for good; a window close ends Wish on its own thread
    between requests.  The reply is `ok closed` or `ok stopped (forced)`.  The forced
    script runs either way, to remove the holder's tasks and check no process is left.
    """
    guest.holds_lane(holder)
    try:
        closed = ui(guest, holder, "close")[-1:] in (["closed"], ["gone"])
    except WinwishError as exc:
        closed = False
        print(f"winwish: closing Wish's window failed, forcing the stop: {exc}", file=sys.stderr)
    guest.ps(stop_script(holder))
    return "ok closed" if closed else "ok stopped (forced)"


def restart_wish(guest: Guest, holder: str, flag: bool = True, open_path: str | None = None,
                 reseed: bool = False,
                 travel_targets: dict[str, list[int]] | None = None,
                 features: bool = True) -> str:
    stop_wish(guest, holder)
    return start_wish(guest, holder, flag, reseed=reseed, open_path=open_path,
                      travel_targets=travel_targets, features=features)


def shot(guest: Guest, holder: str, window: str, out: pathlib.Path) -> int:
    """Save a PNG of `window` (`wish` or `desktop`) to `out`, and the display it was taken on beside it.

    The sidecar `<out>.json` is read right after the picture: desktop size, scale, DPI,
    system font and the Wish window's rectangle, so a picture is never judged without
    the setting it came from.  Returns the PNG's size.
    """
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
    sidecar(guest, holder, window, out)
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
    """The ADFs for DF0 upward, none for a Wish-only run; a drive may not be given without the one before it."""
    given = [args.df0, args.df1, args.df2, args.df3]
    if not any(given):
        return []
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


def uae_options(values: list[str] | None) -> tuple[str, ...]:
    """The extra `-s` settings of `up`; each is interpolated unquoted into a guest shell command, so only a conservative character set is allowed."""
    for value in values or ():
        key, eq, setting = value.partition("=")
        if not eq or not re.fullmatch(r"[A-Za-z0-9_.]+", key) or not re.fullmatch(r"[A-Za-z0-9_.:/\\-]*", setting):
            raise WinwishError(f"--uae-option needs KEY=VALUE using only letters, digits and _ . : / \\ -: {value!r}")
    return tuple(values or ())


def up(guest: Guest, lane: Any, args: argparse.Namespace) -> dict[str, str]:
    """Fetch, stage, claim every lane, start WinUAE (when there are drives), start Wish, give lanes back.

    With no drive no WinUAE is started, but the claim is still exclusive and the mute
    proof still required. The claim takes every lane because Wish attaches to the
    lowest-numbered WinUAE pipe, whichever lane that belongs to: beside another running
    lane it can attach to that holder's emulator. With `--wait-lanes N` the claim
    reserves the lanes and waits up to N seconds for the other holders to release them.

    Once Wish is up and the run's own emulator owns the `WinUAE` pipe, every lane but
    that emulator's is released: an emulator started later takes `WinUAE_1` or higher,
    so Wish stays on its own. Wish alone, an emulator on another pipe name, or
    `--keep-lanes` keeps every lane until `down`.

    Anything that goes wrong between the claim and the end of `start_wish` -- an
    error, Ctrl-C or SIGTERM -- stops Wish (if it was attempted), stops WinUAE and
    releases the lane, in that order.
    """
    drives = floppy_paths(args)
    options = (*floppy_options(len(drives)), *uae_options(getattr(args, "uae_option", None)))
    targets = parse_travel_targets(getattr(args, "travel_targets", None))
    if args.game and not GAME_KEY.match(args.game):
        raise WinwishError(f"not a game key: {args.game!r}")
    if args.game and not drives:
        raise WinwishError("--game needs --df0: the game folder is built from the mounted ADFs")
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
            if args.wait_lanes > 0:
                result["claim"] = lane.claim_every_lane(args.holder, CALL_SECONDS, args.wait_lanes)
            else:
                result["claim"] = lane.claim(args.holder, CALL_SECONDS, exclusive=True)
            claimed = True
            # A display an earlier holder's dead agent left changed is put back before anything runs.
            restore_pending_display(guest, args.holder)
            if drives:
                result["winuae"] = lane.start(args.holder, *drives, timeout=START_SECONDS + 30,
                                              options=options)
                started = True
            wish_tried = True
            result["wish"] = start_wish(guest, args.holder, not args.no_flag,
                                        tuple(drives[:GAME_DISKS]), args.game, reseed=True,
                                        travel_targets=targets, features=not args.map_only)
            if drives and not args.keep_lanes and re.search(r"\bpipe=WinUAE(?![\w])", result["winuae"]):
                result["lanes"] = _give_back_lanes(lane, args.holder)
            done = True
        finally:
            if not done:
                _undo(guest, lane, args.holder, wish_tried, started, claimed)
    return result


def _held_lanes(lane: Any, holder: str) -> list[int]:
    """The lanes the guest's `status` shows `holder` holding."""
    held = []
    for line in lane.status(CALL_SECONDS).splitlines():
        found = re.match(r"\s*claim(?: (\d+))? = (\S+) since ", line)
        if found and found.group(2) == holder:
            held.append(int(found.group(1) or 1))
    return held


def _give_back_lanes(lane: Any, holder: str) -> str:
    """Release every lane but the emulator's own; on a failure say which lanes are still held."""
    try:
        kept = lane.lane(holder, CALL_SECONDS)
        freed = lane.release_other_lanes(holder, kept, CALL_SECONDS)
    except Exception as exc:  # noqa: BLE001 - holding too many lanes is the safe direction
        try:
            still = f"lanes still held: {', '.join(map(str, _held_lanes(lane, holder)))}"
        except Exception:  # noqa: BLE001
            still = "lanes still held: unknown, run `status`"
        return f"failed ({exc}); {still}"
    return f"ok kept lane {kept}, gave back {', '.join(map(str, freed)) or 'none'}"


def _undo(guest: Guest, lane: Any, holder: str, wish_tried: bool,
          started: bool, claimed: bool) -> None:
    """Stop Wish, put the display back, stop WinUAE, release the lane; a later step runs whatever an earlier one raised."""
    with _ignoring_sigterm():
        try:
            if wish_tried:
                _quietly(guest.ps, stop_script(holder))
        finally:
            try:
                if claimed:
                    _quietly(restore_pending_display, guest, holder)
            finally:
                try:
                    if started:
                        _quietly(lane.stop, holder, CALL_SECONDS)
                finally:
                    if claimed:
                        _quietly(lane.release, holder, CALL_SECONDS)


def down(guest: Guest, lane: Any, holder: str) -> dict[str, str]:
    """Stop Wish and remove its task, put the display back, stop WinUAE, release the lane; each step runs even if one before fails."""
    result: dict[str, str] = {}
    problems: list[str] = []
    for name, step in (("wish", lambda: stop_wish(guest, holder)),
                       ("display", lambda: restore_pending_display(guest, holder)),
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
    p.add_argument("--df0", help="a staged ADF on the guest for DF0; with no drive at all "
                   "WinUAE is not started and the lane is still claimed")
    p.add_argument("--df1", help="a staged ADF on the guest for DF1")
    p.add_argument("--df2", help="a staged ADF on the guest for DF2 (Pool of Radiance's save disk)")
    p.add_argument("--df3", help="a staged ADF on the guest for DF3; needs --df2")
    p.add_argument("--uae-option", action="append", default=[], metavar="KEY=VALUE",
                   help="a WinUAE setting added after the drive settings, such as fastmem_size=2; repeatable")
    p.add_argument("--game", help="a `game_folders` key such as pool-of-radiance: Wish's game "
                   "folder for that title is set to copies of the mounted ADFs, so it draws the map")
    p.add_argument("--travel-targets", action="append", default=[], metavar="KEY=ID[,ID]",
                   help="the Fast Travel destinations Wish's settings offer for a title, such as "
                   "pool-of-radiance=20; repeatable. The tab cannot pick from the drop-down")
    p.add_argument("--zip", help="use this zip rather than fetching")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--no-flag", action="store_true",
                   help=f"leave {FLAG} unset (the control)")
    g.add_argument("--map-only", action="store_true",
                   help="set the backend flag but not the action and Fast Travel flags, "
                   "so the map attaches with those controls greyed")
    p.add_argument("--wait-lanes", type=int, default=0, metavar="SECONDS",
                   help="reserve every lane and wait up to this long for the other holders "
                   "to release theirs (default: claim once and fail)")
    p.add_argument("--keep-lanes", action="store_true",
                   help="keep every lane until `down` instead of giving back the ones the "
                   "run's emulator is not in, for a run that restarts its pipe or uses `display --set`")

    p = sub.add_parser("stage-save", help="copy a save to the guest and check its hash there")
    holder(p)
    p.add_argument("--save", required=True, help="the save file on this machine")
    p.add_argument("--folder", required=True,
                   help="a relative folder under the holder's saves folder on the guest")

    for name, text in (("start", "start wish.exe"), ("restart", "stop and start wish.exe")):
        p = sub.add_parser(name, help=text)
        holder(p)
        p.add_argument("--open", metavar="GUEST_PATH",
                       help="a save on the guest (from stage-save) to open on the editor tab")
        p.add_argument("--reseed", action="store_true",
                       help="write fresh settings, so a window size saved at another scale is not kept")
        g = p.add_mutually_exclusive_group()
        g.add_argument("--no-flag", action="store_true",
                       help=f"leave {FLAG} unset (the control)")
        g.add_argument("--map-only", action="store_true",
                       help="set the backend flag but not the action and Fast Travel flags, "
                       "so the map attaches with those controls greyed")
        p.add_argument("--travel-targets", action="append", default=[], metavar="KEY=ID[,ID]",
                       help="with --reseed, the Fast Travel destinations the fresh settings hold, "
                       "as for `up`; repeatable")

    p = sub.add_parser("stop", help="close Wish's window; force wish.exe only if it stays up")
    holder(p)

    p = sub.add_parser("shot", help="save a screenshot")
    holder(p)
    p.add_argument("--window", choices=("wish", "desktop"), default="wish")
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
    p.add_argument("--expand", action="store_true",
                   help="only open the control's menu (ExpandCollapse); a split button is not invoked")
    p.add_argument("--shot-after", metavar="PNG",
                   help="after the last name, grab the desktop in the same task and save it "
                   "here, with its sidecar; a popup the click opened is gone by a later task")
    p.add_argument("--controls-after", metavar="FILE",
                   help="after the last name, in the same task, write every control of --type "
                   "(all when none) here, one line each with RuntimeId, IsOffscreen and "
                   "BoundingRectangle, uncut; a popup the click opened is gone by a later task")
    p.add_argument("--automation-id", help="click the one control whose UI Automation "
                   "AutomationId is this or ends with `.` and this, instead of naming it "
                   "(the six card buttons are all named Level up)")
    p.add_argument("names", nargs="*")

    p = sub.add_parser("display", help="read, set or restore the guest's display size and scale")
    holder(p)
    what = p.add_mutually_exclusive_group(required=True)
    what.add_argument("--read", action="store_true", help="print the display as JSON")
    what.add_argument("--set", metavar="WxH", help="change the size; needs --scale")
    what.add_argument("--restore", action="store_true",
                      help="put back the display recorded before the first --set")
    p.add_argument("--scale", type=int, metavar="PCT", help="the display scale for --set, such as 150")
    p.add_argument("--out", required=True, help="where to write the JSON answer")

    p = sub.add_parser("log", help="copy Wish's debug logs from the guest")
    holder(p)
    p.add_argument("--out", required=True)

    p = sub.add_parser("down", help="stop Wish, put the display back, stop WinUAE, release the lane")
    holder(p)
    return parser


def run_display(guest: Guest, args: argparse.Namespace) -> dict[str, Any]:
    """The `display` command: run its one action and write the answer to `--out`."""
    if args.set:
        match = MODE.match(args.set)
        if not match or args.scale is None:
            raise WinwishError("--set needs a size such as 1920x1080 and --scale PCT")
        state = display(guest, args.holder, "set", int(match[1]), int(match[2]), args.scale)
    elif args.scale is not None:
        raise WinwishError("--scale goes with --set")
    else:
        state = display(guest, args.holder, "restore" if args.restore else "read")
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(state, indent=1) + "\n", encoding="utf-8")
    return state


def main(argv: list[str] | None = None,
         guest: Guest | None = None, lane: Any = None) -> int:
    args = _parser().parse_args(argv)
    guest = guest or Guest()
    try:
        if args.cmd in ("start", "restart") and args.travel_targets and not args.reseed:
            raise WinwishError("--travel-targets needs --reseed")
        if args.cmd == "fetch":
            print(fetch(guest, args.sha, pathlib.Path(args.dest) if args.dest else None))
        elif args.cmd == "up":
            for key, value in up(guest, lane or WinGuest(), args).items():
                print(f"{key}: {value}")
        elif args.cmd == "start":
            print(start_wish(guest, args.holder, not args.no_flag, reseed=args.reseed,
                             open_path=args.open,
                             travel_targets=parse_travel_targets(args.travel_targets),
                             features=not args.map_only))
        elif args.cmd == "restart":
            print(restart_wish(guest, args.holder, not args.no_flag, args.open, args.reseed,
                               parse_travel_targets(args.travel_targets),
                               features=not args.map_only))
        elif args.cmd == "stage-save":
            path, digest = stage_save(guest, args.holder, pathlib.Path(args.save), args.folder)
            print(f"{path} sha256={digest}")
        elif args.cmd == "display":
            print(json.dumps(run_display(guest, args)))
        elif args.cmd == "stop":
            print(stop_wish(guest, args.holder))
        elif args.cmd == "shot":
            size = shot(guest, args.holder, args.window, pathlib.Path(args.out))
            print(f"{args.out} ({size} bytes)")
        elif args.cmd == "controls":
            print("\n".join(ui(guest, args.holder, "controls", (), args.type)))
        elif args.cmd == "click":
            if bool(args.names) == bool(args.automation_id):
                raise WinwishError("click needs names, or --automation-id and no names")
            if args.shot_after and args.expand:
                raise WinwishError("--shot-after and --expand are separate ways to click")
            if args.controls_after and args.expand:
                raise WinwishError("--controls-after and --expand are separate ways to click")
            if args.controls_after:
                lines, dump, png = ui_dump(guest, args.holder, tuple(args.names), args.type,
                                           args.prefix, args.automation_id, bool(args.shot_after))
                extra = []
                if png is not None:
                    target = pathlib.Path(args.shot_after)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(png)
                    sidecar(guest, args.holder, "desktop", target)
                    extra.append(f"{target} ({len(png)} bytes)")
                listing = pathlib.Path(args.controls_after)
                listing.parent.mkdir(parents=True, exist_ok=True)
                listing.write_text("".join(line + "\n" for line in dump), encoding="ascii")
                print("\n".join([*lines, *extra, f"{listing} ({len(dump)} controls)"]))
            elif args.shot_after:
                lines, png = ui_shot(guest, args.holder, tuple(args.names), args.type,
                                     args.prefix, args.automation_id)
                target = pathlib.Path(args.shot_after)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(png)
                sidecar(guest, args.holder, "desktop", target)
                print("\n".join([*lines, f"{target} ({len(png)} bytes)"]))
            else:
                print("\n".join(ui(guest, args.holder, "click", tuple(args.names), args.type,
                                  args.prefix, args.automation_id, args.expand)))
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
