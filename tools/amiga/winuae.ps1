# WinUAE, driven from a Linux SSH shell. Runs on the Windows guest; copy it to
# C:\Amiga\winuae.ps1 and call it through `winvm ssh`.
#
# The guest's execution policy is Restricted, so -ExecutionPolicy Bypass is
# not decoration -- without it every one of these fails to load.
#
# `winvm ssh` shells out to ssh WITHOUT -o BatchMode=yes, so when authentication
# falls through OpenSSH does not fail: with no tty and DISPLAY set it runs
# SSH_ASKPASS, which on this desktop is ksshaskpass, and a KDE password dialog
# appears in front of whoever is sitting there. Export SSH_ASKPASS_REQUIRE=never
# for anything that can reach ssh or scp, so a failure stays a failure.
#
#   export SSH_ASKPASS_REQUIRE=never
#   ps='powershell -NoProfile -ExecutionPolicy Bypass -File C:\Amiga\winuae.ps1'
#   winvm ssh "$ps claim -Holder por-run"       # first: the VM is single-tenant
#   winvm ssh "$ps roms -Holder por-run"        # once, then winvm promote
#   winvm ssh "$ps start -Holder por-run -log -f C:\Amiga\configs\goldbox-a500.uae"
#   winvm ssh "$ps key 7A -Holder por-run"      # F11: enter the debugger
#   winvm ssh "$ps key 68 -Holder por-run"      # numeric keypad 8
#   winvm ssh "$ps key 26 -Extended -Holder por-run"   # the cursor key, not KP8
#   winvm ssh "$ps send '-File C:\Amiga\cmds.txt' -Holder por-run"
#   winvm ssh "$ps send '-DumpOnly -Tail 40' -Holder por-run"
#   winvm ssh "$ps front -Holder por-run"
#   winvm ssh "$ps drives -Holder por-run"      # what DF0 and DF1 hold, read over WinUAE's pipe
#   winvm ssh "$ps insert -Holder por-run 0 C:\Amiga\Disks\wish679-por-run-disk2.adf <sha256>"
#   winvm ssh "$ps snapshot -Holder por-run before-walk"   # the whole machine, to C:\Amiga\States
#   winvm ssh "$ps restore -Holder por-run before-walk"
#   winvm ssh "$ps discard-snapshot -Holder por-run before-walk"
#   winvm ssh "$ps status"
#   winvm ssh "$ps stop -Holder por-run"        # before clean, always
#   winvm ssh "$ps release -Holder por-run"     # let the next lane in
#   winvm ssh "$ps clean"                       # before winvm promote
#
# -log is not optional if you want the debugger: it is what makes WinUAE
# allocate a console, and the debugger has nowhere to talk without one.
#
# Why a scheduled task and not `Start-Process`: `winvm ssh` logs in over the
# network, which lands in Windows session 0. The VM's screen -- the only thing
# `winvm shot` can capture -- is session 1. Session 0 has its own window
# station, so a GUI process started there is invisible to the screenshot and
# no call from there can raise or focus a session 1 window. A scheduled task
# with an Interactive principal runs in whatever session the user is logged
# on to, which is session 1.
#
# Every action reports what it actually achieved, and exits non-zero when it
# did not. That is not politeness: `Start-ScheduledTask` on an Interactive
# principal succeeds and does nothing at all when nobody is logged on at the
# console, so a `key` that reported "pressed" would leave the debugger closed,
# a `send` typing into a console that was never created, and the whole run
# looking fine until somebody read the empty dumps hours later.
#
# THE VM IS SINGLE-TENANT, AND THAT IS WHAT `claim` SAYS OUT LOUD.
# There is one scheduled task, one interactive session and one winuae64 on this
# machine, and `key`, `send` and `front` find their target by process NAME. So a
# second driver does not get a second emulator: it gets yours. It types into
# your game, and its `stop` ends your run -- three Pools of Darkness sessions
# died that way in one night, and nothing in any output said so. So:
#
#   * `claim` refuses a second holder, and `start`, `stop`, `key`, `send`,
#     `front` and `roms` refuse a caller who is not the holder;
#   * `start` verifies that the emulator it found is running the command line
#     THIS call passed, and was started after this call was made -- so a
#     neighbour's emulator can never be reported as your own success;
#   * `start` writes a receipt naming the pid it launched, and `stop`, `key`,
#     `send` and `front` refuse a winuae64 that is not the one in it.
#
# See docs/143-winuae-debugger.md 1.1 and
# #116 (Two agents cannot share the WinUAE VM, and neither of them can tell).

param(
  [Parameter(Mandatory=$true)]
  [ValidateSet('start','stop','front','status','send','key','roms','clean','claim','release','drives','insert','diagnose','config-hash','config-remove','snapshot','restore','discard-snapshot')][string]$Cmd,
  [Parameter(ValueFromRemainingArguments=$true)][string[]]$Rest
)

# -Holder and -Override are read out of the remaining arguments by hand rather
# than declared as parameters, and that is not a matter of taste. PowerShell
# fills a positional parameter BEFORE it fills a ValueFromRemainingArguments
# one, wherever each is declared and whatever Position each is given -- so a
# declared -Holder eats the `7A` of `key 7A` and the quoted argument of `send`.
# Measured, with -Holder at Position 99 and $Rest at Position 1:
# `key 7A` bound cmd=[key] holder=[7A] rest=[], and the keypress was then
# refused for having no VK code. Reading them here leaves every existing call
# form exactly as it was.
#
# For the same family of reasons neither name may be abbreviated by the caller:
# PowerShell would match `-f` to -Holder-like names by prefix, and `-f`, `-log`
# and `-s` belong to WinUAE.
$Holder   = ''
$Override = $false
# `-Token` is the claim's own token, an optional second proof of the holder. It is
# not called $Token because PowerShell variable names ignore case and `claim`
# and `send` assign a local $token of their own.
$WantToken = ''
$WantTokenGiven = $false
# `key -Extended` sets KEYEVENTF_EXTENDEDKEY, which is what separates the four
# cursor keys from the four numeric-keypad keys: without it keybd_event turns
# VK_UP into scancode 0x48, and 0x48 with no E0 prefix is DIK_NUMPAD8. Every
# arrow this driver has ever pressed was really a keypad key.
$Extended = $false
# @($null) is an array of one $null, not an empty one, so a command with no
# remaining arguments at all -- `stop`, `status` -- has Count 1 and indexes into
# nothing. Measured: "Cannot index into a null array" on bare `stop`.
$given    = if ($Rest) { @($Rest) } else { @() }
$passthru = New-Object System.Collections.ArrayList
for ($i = 0; $i -lt $given.Count; $i++) {
  $a = $given[$i]
  if ($a -eq '-Holder') { $i++; if ($i -lt $given.Count) { $Holder = $given[$i] } }
  elseif ($a -eq '-Override') { $Override = $true }
  elseif ($a -eq '-Token') { $WantTokenGiven = $true; $i++; if ($i -lt $given.Count) { $WantToken = $given[$i] } }
  elseif ($a -eq '-Extended') { $Extended = $true }
  else { [void]$passthru.Add($a) }
}
$Rest = $passthru.ToArray()

$Exe     = 'C:\Program Files\WinUAE\winuae64.exe'
$Root    = 'C:\Amiga'
$Task    = 'winuae-run'
$Helpers = 'winuae-front','winuae-key','winuae-send'
$Receipt = "$Root\winuae-action.txt"    # what a session 1 helper writes back
$SendLog = "$Root\send.log"
$ClaimFile = "$Root\winuae-claim.txt"   # who holds the one Amiga lane
$RunFile   = "$Root\winuae-run.txt"     # which winuae64 `start` launched, for whom
$RomKey  = 'HKCU:\Software\Arabuusimiehet\WinUAE'
$RomDir  = "$Root\Kickstarts\"

# The injector appends to send.log while this script reads it ten times a
# second, and the two used to collide: Get-Content against an Add-Content
# writer raised IOException 16344 times in 20000 tight-loop reads, and every
# collision on the WRITER's side killed the injector outright -- #95. The
# injector now writes through a handle that shares the file; this reads through
# one too, so the poll never prints a red error into the caller's output, and
# a read that fails anyway is a null, which the poll treats as "not yet".
$script:readFailures = 0

function Read-SendLog {
  if (-not (Test-Path $SendLog)) { return $null }
  try {
    $fs = New-Object IO.FileStream($SendLog, [IO.FileMode]::Open, [IO.FileAccess]::Read,
            ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
    try {
      $r = New-Object IO.StreamReader($fs, [Text.Encoding]::UTF8)
      $text = $r.ReadToEnd()
    } finally { $fs.Close() }
  } catch {
    # Counted, because "not written yet" and "cannot be read at all" look the
    # same to the poll and one of them is a fault. A permissions problem or an
    # antivirus lock would otherwise spend the whole eleven-minute wait looking
    # exactly like an injector that had not started. `Say` keeps the matching
    # count on the writer's side; this is the reader's.
    $script:readFailures++
    return $null
  }
  return @(($text -split "\r?\n") | Where-Object { $_ -ne '' })
}

# The claim and the run receipt are `key=value` lines. Not ConvertFrom-StringData,
# which reads a backslash as an escape -- every path here is a Windows one, and
# `-s floppy0=C:\Amiga\Disks\...` carries a second `=` as well. Split on the
# first `=` and keep the rest of the line whole.
function Read-Kv([string]$Path) {
  $h = @{}
  foreach ($line in @(Get-Content -Path $Path -ErrorAction SilentlyContinue)) {
    $i = $line.IndexOf('=')
    if ($i -gt 0) { $h[$line.Substring(0, $i)] = $line.Substring($i + 1) }
  }
  $h
}

function Write-Kv([string]$Path, [hashtable]$H) {
  ($H.Keys | Sort-Object | ForEach-Object { "$_=$($H[$_])" }) | Set-Content -Path $Path -Encoding ASCII
}

function Boot-Stamp { (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString('o') }

# Creating the file IS the claim, and this is deliberately not a read-then-write.
# Two `claim` calls arriving together would both read an empty lane, both write
# it and both print "ok claimed by ...", which is exactly the belief #116 exists
# to destroy -- the same kind of race as `winvm acquire`, with a narrower
# window. [IO.File]::Open with CreateNew is one atomic NTFS operation: exactly
# one caller creates the file and every other gets an IOException and is told it
# lost.
#
# The guarantee, said plainly rather than left to be discovered: when `claim`
# prints ok, the claim file on disk carries THIS call's token -- the create was
# won and the result was read back and confirmed. Two callers cannot both see
# that. What it does not promise is anything about two callers both passing
# -Override: a steal deletes and re-creates, so two of them can take the lane
# from each other. -Override is for a lane whose holder has gone away, not for
# winning a race.
function Try-TakeClaim([hashtable]$Content) {
  try {
    $fs = [System.IO.File]::Open($ClaimFile, [System.IO.FileMode]::CreateNew,
                                 [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
  } catch { return $false }
  try {
    $sw = New-Object System.IO.StreamWriter($fs)
    foreach ($k in ($Content.Keys | Sort-Object)) { $sw.WriteLine("$k=$($Content[$k])") }
    $sw.Flush()
    $sw.Dispose()
  } catch {
    $fs.Dispose()
    return $false
  }
  $true
}

# Reading a claim has to tell "there is none" from "one is being written right
# now", and that distinction is not academic: Try-TakeClaim holds the file with
# FileShare::None while it writes, a reader in that instant gets nothing back,
# and the first version of this treated nothing-back as a free lane -- so the
# losers of a race deleted the winner's claim and took the lane themselves.
# Measured with six simultaneous claims: 2 and 3 holders granted out of six.
#
# A claim also cannot outlive the boot that made it: a restart takes every
# emulator and every run in flight with it, so what it recorded is gone. Any
# other stale claim is a person's to release or to steal with -Override,
# because nothing in the guest can see whether the Linux process that took it
# is still alive.
# UNKNOWN, and left as one deliberately: a held claim records `boot` and is
# treated as stale when that string no longer equals Boot-Stamp. If Windows
# recomputes LastBootUpTime as "now minus uptime", a clock step of any size
# would make every live claim read stale, and the next caller could take the
# lane without -Override. Not measured -- the experiment is to read Boot-Stamp
# either side of a deliberate clock step, or across a pause and resume of the
# VM. The wreck branch below no longer depends on the clock at all; this one
# still does, and the failure would be this issue reopened by clock skew.
function Read-Claim {
  for ($i = 0; $i -lt 10; $i++) {
    if (-not (Test-Path $ClaimFile)) { return @{ state = 'free' } }
    $c = Read-Kv $ClaimFile
    if ($c.ContainsKey('holder')) {
      if ($c['boot'] -ne (Boot-Stamp)) { return @{ state = 'stale'; claim = $c } }
      return @{ state = 'held'; claim = $c }
    }
    # No holder line. Either a write in flight -- Try-TakeClaim holds the file
    # with FileShare::None and writes `boot` before `holder`, so a reader in
    # that instant sees neither -- or the wreck of one that was killed
    # part-way, which is how this guest fails: an ssh drop takes the child
    # PowerShell's whole process tree. Left as merely unreadable, a wreck
    # deadlocks every command until a person passes -Override.
    #
    # Told apart by AGE, not against the boot time. Comparing the file's write
    # time with Boot-Stamp reads two different clock readings against each
    # other, and a clock stepped backwards past its own recorded boot -- an NTP
    # correction after a resume, a reverted snapshot -- would then make a live
    # write look stale and let a second holder take the lane with no -Override,
    # which is this issue reopened by clock skew. An age is one clock compared
    # with itself, and it fails in the safe direction: a backwards step makes
    # the age negative, the file reads as in flight, and the caller is refused
    # rather than let in. A write lasts milliseconds; ten seconds is the margin.
    $written = (Get-Item $ClaimFile -ErrorAction SilentlyContinue).LastWriteTime
    if ($written -and ((Get-Date) - $written).TotalSeconds -gt 10) { return @{ state = 'stale' } }
    Start-Sleep -Milliseconds 50
  }
  @{ state = 'unreadable' }
}

function Get-Claim {
  $r = Read-Claim
  if ($r['state'] -eq 'held') { return $r['claim'] }
  $null
}

# Every rejection says how to get unstuck, and that is not politeness either. An
# agent whose predecessor died without releasing reads only "claimed by
# dead-agent since 09:14" and has a lock nothing tells it how to clear. The
# second line is the way out; `fail` stays lowercase because it is the status
# token callers match on, not prose.
function Claim-Way-Out([hashtable]$c, [string]$Verb) {
  "If $($c['holder']) has gone, $Verb the lane with: winuae.ps1 claim -Holder <id> -Override"
}

function Claim-Denial {
  $c = Get-Claim
  if (-not $c) {
    return "fail the WinUAE lane is unclaimed; run: winuae.ps1 claim -Holder <id>"
  }
  if (-not $Holder) {
    return "fail the WinUAE lane is claimed by $($c['holder']) since $($c['since']); pass -Holder <id>`n$(Claim-Way-Out $c 'take')"
  }
  if ($Holder -ne $c['holder']) {
    return "fail the WinUAE lane is claimed by $($c['holder']) since $($c['since']), not by $Holder`n$(Claim-Way-Out $c 'take')"
  }
  $null
}

# The one winuae64 this lane started -- or why the caller must not touch the one
# that is there. `key`, `send` and `front` pick their target by process name, so
# without the receipt they drive whatever emulator is running, which on a shared
# VM is somebody else's game.
function Resolve-MyEmulator {
  $all = @(Get-Process -Name winuae64 -ErrorAction SilentlyContinue)
  if ($all.Count -eq 0) { return @{ err = 'fail no winuae64 process' } }
  if ($all.Count -gt 1) {
    return @{ err = ('fail ' + $all.Count + ' winuae64 processes: ' +
                     (($all | ForEach-Object { $_.Id }) -join ',') + '; stop all but one') }
  }
  $p = $all[0]
  $r = Read-Kv $RunFile
  if (-not $r.ContainsKey('pid')) {
    return @{ err = "fail winuae64 pid=$($p.Id) has no run receipt, so nothing here started it" }
  }
  if ([int]$r['pid'] -ne $p.Id) {
    return @{ err = "fail winuae64 pid=$($p.Id) is not the pid=$($r['pid']) this lane started" }
  }
  # A pid is reused within the hour on a busy guest, and the whole point here is
  # to be sure of the process rather than of the number.
  if ($r['started'] -and $r['started'] -ne $p.StartTime.ToString('o')) {
    return @{ err = "fail winuae64 pid=$($p.Id) started $($p.StartTime.ToString('o')), not $($r['started']) as the receipt says" }
  }
  if ($Holder -and $r['holder'] -and $r['holder'] -ne $Holder) {
    return @{ err = "fail winuae64 pid=$($p.Id) was started by $($r['holder']), not by $Holder" }
  }
  @{ proc = $p; run = $r }
}

# Register-ScheduledTask -Force is not to be trusted without reading the result
# back. It is documented not to end a running instance of the task, and the
# hijack in #116 was reported as -Force silently keeping the old action while
# one was running. That was measured NOT to happen on this guest -- three of
# three -Force calls over a running instance replaced the arguments -- but the
# check costs three lines and it is the difference between a wrong config and an
# error message on whatever Windows build does behave that way.
function Register-Session1Task {
  param([string]$Name, [string]$Program, [string]$Arguments, [TimeSpan]$Limit)
  $a = New-ScheduledTaskAction -Execute $Program -Argument $Arguments -WorkingDirectory $Root
  $p = New-ScheduledTaskPrincipal -UserId "$env:COMPUTERNAME\donald" -LogonType Interactive
  $s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit $Limit `
         -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
  Register-ScheduledTask -TaskName $Name -Action $a -Principal $p -Settings $s -Force | Out-Null
  $got = @((Get-ScheduledTask -TaskName $Name).Actions)[0]
  if ($got.Execute -ne $Program) {
    return "fail $Name runs '$($got.Execute)' after registering, not '$Program'"
  }
  if (($got.Arguments -replace '\s+', ' ').Trim() -ne ($Arguments -replace '\s+', ' ').Trim()) {
    return "fail $Name kept the arguments of an earlier call: '$($got.Arguments)' instead of '$Arguments'"
  }
  $null
}

# Task Scheduler's MultipleInstances is IgnoreNew and there is nothing else to
# ask for -- New-ScheduledTaskSettingsSet's enum offers only Parallel, Queue and
# IgnoreNew, with no StopExisting. So a Start while an earlier instance is still
# alive is silently dropped, and Register-ScheduledTask -Force does NOT end that
# instance either. Measured: caller A's helper was still running, caller B
# re-registered, started, and read A's receipt as its own after 12.3s -- the
# silent-success bug in another coat. Stop first, and wait for Running to clear.
function Start-Session1Task([string]$Name) {
  Stop-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
  for ($i = 0; $i -lt 50; $i++) {
    if ((Get-ScheduledTask -TaskName $Name).State -ne 'Running') { break }
    Start-Sleep -Milliseconds 100
  }
  Start-ScheduledTask -TaskName $Name
}

function Why-NotRun([string]$Name) {
  $info = Get-ScheduledTaskInfo -TaskName $Name
  $why = ''
  # 0x41303 is "the task has never run", which is what an Interactive principal
  # reports when there is no console logon to run in. It is the one failure
  # that looks exactly like success from the caller's side.
  if ($info.LastTaskResult -eq 267011) {
    $why = ' -- nobody is logged on at the console, so an Interactive task cannot run'
  }
  "state=$((Get-ScheduledTask -TaskName $Name).State) " +
  ("lastResult=0x{0:X}" -f $info.LastTaskResult) +
  " lastRun=$($info.LastRunTime)$why"
}

# Run a snippet in session 1 and wait for the receipt it writes. The snippet is
# passed as -EncodedCommand rather than dropped in a temp file: nothing to
# quote, nothing to clean up afterwards.
function Invoke-Session1 {
  param([string]$Name, [string]$Script, [int]$TimeoutSec = 30)
  # The token is this call's own. Waiting on the file merely EXISTING would
  # accept a receipt a previous call's helper wrote, and would also accept a
  # half-written one, since Set-Content is not atomic; waiting for our own
  # token in it accepts neither.
  $token = [guid]::NewGuid().ToString('N').Substring(0, 12)
  Remove-Item $Receipt -ErrorAction SilentlyContinue
  $enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes("`$Token = '$token'`r`n" + $Script))
  $bad = Register-Session1Task $Name 'powershell.exe' `
    "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -EncodedCommand $enc" `
    ([TimeSpan]::FromMinutes(1))
  if ($bad) { return $bad }
  Start-Session1Task $Name
  for ($i = 0; $i -lt $TimeoutSec * 10; $i++) {
    $r = (Get-Content -Raw $Receipt -ErrorAction SilentlyContinue)
    if ($r -and $r.Contains("token=$token")) { return ($r -replace "\s*token=$token\s*$", '').Trim() }
    Start-Sleep -Milliseconds 100
  }
  "fail $Name wrote no receipt in ${TimeoutSec}s: $(Why-NotRun $Name)"
}

# Every helper ends by writing one line: "ok ..." or "fail ...".
#
# Double every backtick below, comments included. This is a double-quoted
# here-string, so `r emits a carriage return -- PowerShell reads that as a
# line ending, and the rest of a comment becomes a command. It parses clean
# and fails only when that branch runs, which is the worst way to find it.
$Preamble = @"
`$Receipt = '$Receipt'
function Report([string]`$m) { "`$m token=`$Token" | Set-Content -Path `$Receipt -Encoding ASCII }
Add-Type @'
using System;using System.Runtime.InteropServices;
public class W {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int c);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, IntPtr extra);
}
'@
`$all = @(Get-Process -Name winuae64 -ErrorAction SilentlyContinue)
if (`$all.Count -eq 0) { Report 'fail no winuae64 process'; exit 1 }
if (`$all.Count -gt 1) {
  # ``Select-Object -First 1`` picked whichever the OS listed first, so a
  # keypress could land in a second emulator -- the ``roms`` scan used to
  # start one -- with nothing said. Refuse instead of guessing which is meant.
  Report ('fail ' + `$all.Count + ' winuae64 processes: ' +
          ((`$all | ForEach-Object { `$_.Id }) -join ',') +
          '; stop all but one')
  exit 1
}
`$p = `$all[0]
`$h = `$p.MainWindowHandle
if (`$h -eq [IntPtr]::Zero) { Report "fail pid=`$(`$p.Id) has no main window"; exit 1 }
"@

# The caller checks the pid against the run receipt before it dispatches; the
# helper checks it again, because between the two there is a whole
# scheduled-task launch, and that is long enough for another lane's `start` to
# have replaced the emulator underneath this one.
#
# The blank first and last lines are deliberate: this string is concatenated
# between two others, and a here-string does not promise a newline at either
# end of itself.
function Pid-Guard([int]$Id) {
  @"

if (`$p.Id -ne $Id) { Report "fail winuae64 pid=`$(`$p.Id) is not the pid=$Id this lane started"; exit 1 }

"@
}

# Raising the emulator is a prerequisite for `key` -- keybd_event goes to
# whatever has focus -- and for `winvm shot`, since anything else open on the
# guest desktop would otherwise sit on top of it.
$RaiseAndCheck = @'
[W]::ShowWindow($h,9) | Out-Null
[W]::BringWindowToTop($h) | Out-Null
[W]::SetForegroundWindow($h) | Out-Null
Start-Sleep -Milliseconds 300
$fg = ([W]::GetForegroundWindow() -eq $h)
'@

# -- `snapshot`, `restore` and `discard-snapshot`: the whole machine, over the pipe --
#
# snapshot <name>: `CFG statefile_save x` leaves a save pending, and
# `CFG statefile_path <folder>` points it at `<folder>\<last component>`, where
# WinUAE writes it within a couple of seconds. `CFG statefile_save <name>` alone
# writes nothing: WinUAE joins the state folder and a full path into one bad
# name. Each snapshot is `$StateRoot\<holder>\<name>\<name>`, replaced if it
# exists, and is waited on until it starts `ASF ` and stops growing.
# restore <name>: `CFG statefile <file>`, then a settle so the next key reaches
# the restored machine. discard-snapshot <name>: removes the folder.
#
# Output is the same as the floppy verbs': the verdict, the ownership tags,
# `<<m>> <seq> <label> <ms> <base64>` for each message sent and `<<r>>` for its
# reply, then `<<file>>`, `<<bytes>>`, `<<header>>` and `<<appeared_ms>>` for a
# snapshot, and `<<end>>`.
$StateRoot        = "$Root\States"
$StateNamePattern = '^[A-Za-z0-9_-]{1,32}\z'
$StateBoundMs     = 15000
$StatePollMs      = 250
$RestoreSettleMs  = 1500

# Length and first four bytes of a state file, read without locking WinUAE out; $null while it cannot be read.
function Read-StateHead([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
  try {
    $fs = [IO.File]::Open($Path, 'Open', 'Read', 'ReadWrite')
    try {
      $b = New-Object byte[] 4
      $n = $fs.Read($b, 0, 4)
      @{ len = $fs.Length; head = if ($n -gt 0) { ([BitConverter]::ToString($b, 0, $n) -replace '-', '') } else { '' } }
    } finally { $fs.Dispose() }
  } catch { $null }
}

function Send-Logged($Pipe, $Sw, $Tags, [int]$Seq, [string]$Label, [string]$Text) {
  $Tags.Add("<<m>> $Seq $Label $($Sw.ElapsedMilliseconds) $([Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($Text)))") | Out-Null
  $bytes = Send-Pipe $Pipe $Text
  $Tags.Add("<<r>> $Seq $Label $($Sw.ElapsedMilliseconds) $([Convert]::ToBase64String($bytes))") | Out-Null
}

function Invoke-State([string]$Verb) {
  $deny = Get-LaneDenial
  if ($deny) { $deny; exit 1 }
  if ($Holder.Contains('..') -or $Holder -cnotmatch '^[A-Za-z0-9._-]{1,64}\z') { 'fail -Holder is not a lane-safe name'; exit 1 }
  if ($Rest.Count -ne 1 -or $Rest[0] -cnotmatch $StateNamePattern) { "fail $Verb needs one snapshot name of 1-32 letters, digits, - and _"; exit 1 }
  $name = $Rest[0]
  $dir = "$StateRoot\$Holder\$name"
  $file = "$dir\$name"
  if ($Verb -eq 'discard-snapshot') {
    if (-not (Test-Path -LiteralPath $dir)) { "ok nothing to discard for $name"; '<<end>>'; exit 0 }
    Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $dir) { "fail $dir survived removal"; exit 1 }
    "ok discarded $name"
    '<<end>>'
    exit 0
  }
  if ($Verb -eq 'restore') {
    $h = Read-StateHead $file
    if (-not $h -or $h.head -cne '41534620') { "fail there is no snapshot $name for $Holder"; exit 1 }
  }
  $lane = Get-LaneEmulator
  if ($lane.err) { $lane.err; exit 1 }
  if ($Verb -eq 'snapshot') {
    if (Test-Path -LiteralPath $dir) { Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue }
    if (Test-Path -LiteralPath $dir) { "fail the old snapshot at $dir could not be removed"; exit 1 }
    New-Item -ItemType Directory -Force -Path $dir -ErrorAction Stop | Out-Null
  }
  $tags = New-Object System.Collections.ArrayList
  $pipe = $null; $open = $false; $verdict = $null
  try {
    Add-Type -Namespace Wish -Name PipeInfo -MemberDefinition '[DllImport("kernel32.dll", SetLastError=true)] public static extern bool GetNamedPipeServerProcessId(IntPtr Pipe, out uint ServerProcessId);'
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $pipe = New-Object IO.Pipes.NamedPipeClientStream '.', 'WinUAE', 'InOut'
    $pipe.Connect(5000)
    $pipe.ReadMode = [IO.Pipes.PipeTransmissionMode]::Message
    $open = $true
    $tags.Add("<<connect_ms>> $($sw.ElapsedMilliseconds)") | Out-Null
    $tags.Add("<<pid>> $($lane.proc.Id)") | Out-Null
    $tags.Add("<<started>> $($lane.proc.StartTime.ToString('o'))") | Out-Null
    $tags.Add("<<exe>> $($lane.exe)") | Out-Null
    [uint32]$server = 0
    if (-not [Wish.PipeInfo]::GetNamedPipeServerProcessId($pipe.SafePipeHandle.DangerousGetHandle(), [ref]$server)) {
      throw "GetNamedPipeServerProcessId failed, error $([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
    }
    $tags.Add("<<server_pid>> $server") | Out-Null
    if ($server -ne $lane.proc.Id) {
      $verdict = "fail \\.\pipe\WinUAE is served by pid=$server, not by this lane's winuae64 pid=$($lane.proc.Id)"
    }
    if (-not $verdict) {
      $again = Get-LaneEmulator
      if ($again.err) { $verdict = $again.err }
      elseif ($again.proc.Id -ne $lane.proc.Id) { $verdict = "fail winuae64 pid=$($again.proc.Id) is not the pid=$($lane.proc.Id) this lane started" }
    }
    if (-not $verdict -and $Verb -eq 'restore') {
      Send-Logged $pipe $sw $tags 0 'restore' "CFG statefile $file"
      Start-Sleep -Milliseconds $RestoreSettleMs
      $verdict = "ok restored $name pid=$($lane.proc.Id)"
    }
    if (-not $verdict -and $Verb -eq 'snapshot') {
      Send-Logged $pipe $sw $tags 0 'save' 'CFG statefile_save x'
      Send-Logged $pipe $sw $tags 1 'path' "CFG statefile_path $dir"
      $tags.Add("<<file>> $file") | Out-Null
      $until = $sw.ElapsedMilliseconds + $StateBoundMs
      $last = $null
      while ($sw.ElapsedMilliseconds -lt $until) {
        Start-Sleep -Milliseconds $StatePollMs
        $h = Read-StateHead $file
        if ($h -and $h.len -gt 0 -and $h.head -ceq '41534620' -and $last -and $last.len -eq $h.len) {
          $tags.Add("<<bytes>> $($h.len)") | Out-Null
          $tags.Add("<<header>> $($h.head)") | Out-Null
          $tags.Add("<<appeared_ms>> $($sw.ElapsedMilliseconds)") | Out-Null
          $verdict = "ok snapshot $name bytes=$($h.len) pid=$($lane.proc.Id)"
          break
        }
        $last = $h
      }
      if (-not $verdict) { $verdict = "fail the state file $file did not appear within $($StateBoundMs / 1000) s" }
    }
  } catch {
    $verdict = "fail $($_.Exception.GetType().FullName): $($_.Exception.Message)"
  } finally {
    if ($pipe) { $pipe.Dispose() }
  }
  if (-not $open) { $verdict; exit 1 }
  $verdict
  $tags
  '<<end>>'
}

# -- `drives` and `insert`: WinUAE's own pipe, from one process ----------------
#
# A floppy change goes down `\\.\pipe\WinUAE` as `CFG floppy<N> <path>`, and the
# only safe place to send it is a process that has just proved the pipe is the
# lane's own emulator's. So the ownership checks, the connection and every
# message are one PowerShell process: a separate successful `status` call would
# prove nothing about the pipe a later call reaches.
#
# Output. The first line is the verdict, `ok ...` or `fail ...`. Then one
# `<<tag>> value` line each for connect_ms, pid, started, exe and server_pid (in that order; the caller keys on the tag),
# and `<<r>> <seq> <label> <ms> <base64>` for every raw reply: seq 0 is the read
# before the setter (labels q0, q1 for `CFG floppy0` and `CFG floppy1`, dbg for
# `DBG c`) and the setter's own reply (label set); seq 1 upwards are the polls.
# `<<end>>` closes the block. A rejection or failure made before the pipe is open exits 1
# with the reason. Once the pipe is open the exit code is 0 whatever the verdict,
# so the raw replies of a failure reach the caller; the verdict line is the answer.
# The caller judges the replies itself; the checks here only decide what may be sent.
$DiskPattern = '^C:\\Amiga\\Disks\\wish[0-9]+-[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)*\.adf\z'
$DriveLine   = 'DEBUG: drive ([0-3]) motor (?:off| on) cylinder\s*\d+ sel (?:yes|no) (ro|rw) mfmpos \d+/\d+'
$PollBoundMs = 10000
$PollEveryMs = 250

# The one winuae64 this lane started, or why the caller must not touch the one
# that is there: the claim, the optional token, the run receipt, and the
# executable, all before anything is opened.
function Get-LaneDenial {
  $deny = Claim-Denial
  if ($deny) { return $deny }
  if ($WantTokenGiven) {
    # A token that was asked for and cannot be compared fails closed.
    if (-not $WantToken -or $WantToken.StartsWith('-', [StringComparison]::Ordinal)) { return "fail -Token needs the claim's token as its value" }
    $c = Get-Claim
    if (-not $c -or $c['token'] -cne $WantToken) {
      return "fail the WinUAE lane's claim token is not the one $Holder took"
    }
  }
  $null
}

function Get-LaneEmulator {
  $deny = Get-LaneDenial
  if ($deny) { return @{ err = $deny } }
  $mine = Resolve-MyEmulator
  if ($mine.err) { return @{ err = $mine.err } }
  $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$($mine.proc.Id)" -ErrorAction SilentlyContinue
  $path = if ($cim) { $cim.ExecutablePath } else { $null }
  if ($path -ne $Exe) { return @{ err = "fail winuae64 pid=$($mine.proc.Id) runs $path, not $Exe" } }
  @{ proc = $mine.proc; run = $mine.run; exe = $path }
}

# One message out, one reply back, both NUL-terminated as `uaeipc.cpp` wants: a
# request without its NUL picks up bytes of a longer earlier one.
function Send-Pipe($Pipe, [string]$Text, [int]$WaitMs = 10000) {
  $b = [Text.Encoding]::ASCII.GetBytes($Text)
  $msg = New-Object byte[] ($b.Length + 1)
  [Array]::Copy($b, $msg, $b.Length)
  $Pipe.Write($msg, 0, $msg.Length)
  $Pipe.Flush()
  $buf = New-Object byte[] 65536
  $ms = New-Object IO.MemoryStream
  do {
    $task = $Pipe.ReadAsync($buf, 0, $buf.Length)
    if (-not $task.Wait($WaitMs)) { throw "the pipe accepted a message and never replied in $WaitMs ms" }
    $n = $task.Result
    if ($n -gt 0) { $ms.Write($buf, 0, $n) }
    if ($n -eq 0) { break }
  } while (-not $Pipe.IsMessageComplete)
  ,$ms.ToArray()
}

function Read-Drives($Pipe, $Sw, [int]$Seq, $Tags, [long]$Until = 0) {
  $out = @{}
  foreach ($item in @(@('q0', 'CFG floppy0'), @('q1', 'CFG floppy1'), @('dbg', 'DBG c'))) {
    # A read may not outlast the poll's own deadline.
    $wait = if ($Until) { [int][Math]::Max(250, [Math]::Min(10000, $Until - $Sw.ElapsedMilliseconds)) } else { 10000 }
    $bytes = Send-Pipe $Pipe $item[1] $wait
    $Tags.Add("<<r>> $Seq $($item[0]) $($Sw.ElapsedMilliseconds) $([Convert]::ToBase64String($bytes))") | Out-Null
    $out[$item[0]] = [Text.Encoding]::GetEncoding('iso-8859-1').GetString($bytes).TrimEnd([char]0)
  }
  # A path is the text after the status line, or empty for `404`.
  $paths = @{}
  foreach ($n in 0, 1) {
    $t = $out["q$n"]
    $paths[$n] = if ($t.StartsWith("200 `n", [StringComparison]::Ordinal)) { $t.Substring(5) } else { '' }
  }
  $modes = @{}
  foreach ($m in [regex]::Matches($out['dbg'], $DriveLine)) { $modes[[int]$m.Groups[1].Value] = $m.Groups[2].Value }
  @{ q0 = $out['q0']; paths = $paths; modes = $modes }
}

function Invoke-Diagnose {
  # A diagnostic read uses the same receipt and pipe ownership checks as a disk read.
  if ($Rest.Count -lt 2 -or $Rest.Count -gt 3) { 'fail diagnose needs CFG <gfx_api|floppy0|floppy1> or DBG <c|m> [hex-address]'; exit 1 }
  $query = $null
  if ($Rest[0] -ceq 'CFG' -and $Rest.Count -eq 2 -and
      $Rest[1] -cin @('gfx_api','floppy0','floppy1')) { $query = "CFG $($Rest[1])" }
  if ($Rest[0] -ceq 'DBG' -and $Rest[1] -ceq 'c' -and $Rest.Count -eq 2) { $query = 'DBG c' }
  if ($Rest[0] -ceq 'DBG' -and $Rest[1] -ceq 'm' -and $Rest.Count -eq 3 -and
      $Rest[2] -cmatch '^[0-9A-Fa-f]{1,8}\z') { $query = "DBG m $($Rest[2]) 1" }
  if (-not $query) { 'fail diagnose refused an unapproved read'; exit 1 }
  $lane = Get-LaneEmulator
  if ($lane.err) { $lane.err; exit 1 }
  $tags = New-Object System.Collections.ArrayList
  $pipe = $null; $open = $false; $verdict = $null
  try {
    Add-Type -Namespace Wish -Name PipeInfo -MemberDefinition '[DllImport("kernel32.dll", SetLastError=true)] public static extern bool GetNamedPipeServerProcessId(IntPtr Pipe, out uint ServerProcessId);'
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $pipe = New-Object IO.Pipes.NamedPipeClientStream '.', 'WinUAE', 'InOut'
    $pipe.Connect(5000)
    $pipe.ReadMode = [IO.Pipes.PipeTransmissionMode]::Message
    $open = $true
    $tags.Add("<<connect_ms>> $($sw.ElapsedMilliseconds)") | Out-Null
    $tags.Add("<<pid>> $($lane.proc.Id)") | Out-Null
    $tags.Add("<<started>> $($lane.proc.StartTime.ToString('o'))") | Out-Null
    $tags.Add("<<exe>> $($lane.exe)") | Out-Null
    [uint32]$server = 0
    if (-not [Wish.PipeInfo]::GetNamedPipeServerProcessId($pipe.SafePipeHandle.DangerousGetHandle(), [ref]$server)) {
      throw "GetNamedPipeServerProcessId failed, error $([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
    }
    $tags.Add("<<server_pid>> $server") | Out-Null
    if ($server -ne $lane.proc.Id) {
      $verdict = "fail pipe server pid=$server differs from lane pid=$($lane.proc.Id)"
    }
    if (-not $verdict) {
      $again = Get-LaneEmulator
      if ($again.err) { $verdict = $again.err }
      elseif ($again.proc.Id -ne $lane.proc.Id) { $verdict = 'fail lane PID changed before read' }
    }
    if (-not $verdict) {
      $bytes = Send-Pipe $pipe $query 10000
      $tags.Add("<<r>> 0 read $($sw.ElapsedMilliseconds) $([Convert]::ToBase64String($bytes))") | Out-Null
      $verdict = "ok diagnose pid=$($lane.proc.Id)"
    }
  } catch {
    $verdict = "fail $($_.Exception.GetType().FullName): $($_.Exception.Message)"
  } finally {
    if ($pipe) { $pipe.Dispose() }
  }
  if (-not $open) { $verdict; exit 1 }
  $verdict
  $tags
  '<<end>>'
}

function Invoke-PrivateConfig([string]$Verb) {
  $deny = Claim-Denial
  if ($deny) { $deny; exit 1 }
  if ($Rest.Count -ne 1 -or $Rest[0] -cne "C:\Amiga\configs\wish705-$Holder.uae") {
    'fail private config path does not name this holder'; exit 1
  }
  $path = $Rest[0]
  if ($Verb -eq 'config-hash') {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { 'fail private config is missing'; exit 1 }
    "ok $((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower())"
  } else {
    Remove-Item -LiteralPath $path -ErrorAction Stop
    if (Test-Path -LiteralPath $path) { 'fail private config survived removal'; exit 1 }
    'ok private config removed'
  }
}

function Invoke-Floppy([string]$Verb) {
  $write = ($Verb -eq 'insert')
  if ($write) {
    # Refused before the claim is even read: nothing about the request can be right.
    $deny = Claim-Denial
    if ($deny) { $deny; exit 1 }
    if ($Rest.Count -ne 3) { 'fail insert needs <drive> <path> <sha256>'; exit 1 }
    $drive = $Rest[0]; $path = $Rest[1]; $want = $Rest[2]
    if ($drive -cnotmatch '^[01]\z') { "fail '$drive' is not DF0 or DF1"; exit 1 }
    if ($path.Length -gt 200 -or $path.Contains('..') -or $path -cnotmatch $DiskPattern) {
      "fail $path is not a staged ADF under C:\Amiga\Disks"; exit 1
    }
    $prefix = [regex]::Match($path, '^C:\\Amiga\\Disks\\wish[0-9]+-').Value
    if (-not $path.Substring($prefix.Length).StartsWith("$Holder-", [StringComparison]::Ordinal)) {
      "fail $path is not staged for $Holder"; exit 1
    }
    if ($want -cnotmatch '^[0-9A-Fa-f]{64}\z') { "fail '$want' is not a SHA-256"; exit 1 }
    $drive = [int]$drive
  }
  $lane = Get-LaneEmulator
  if ($lane.err) { $lane.err; exit 1 }
  $tags = New-Object System.Collections.ArrayList
  $verdict = $null
  $sw = $null
  $pipe = $null
  $open = $false
  try {
    Add-Type -Namespace Wish -Name PipeInfo -MemberDefinition '[DllImport("kernel32.dll", SetLastError=true)] public static extern bool GetNamedPipeServerProcessId(IntPtr Pipe, out uint ServerProcessId);'
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $pipe = New-Object IO.Pipes.NamedPipeClientStream '.', 'WinUAE', 'InOut'
    $pipe.Connect(5000)
    $pipe.ReadMode = [IO.Pipes.PipeTransmissionMode]::Message
    $open = $true
    $tags.Add("<<connect_ms>> $($sw.ElapsedMilliseconds)") | Out-Null
    $tags.Add("<<pid>> $($lane.proc.Id)") | Out-Null
    $tags.Add("<<started>> $($lane.proc.StartTime.ToString('o'))") | Out-Null
    $tags.Add("<<exe>> $($lane.exe)") | Out-Null
    [uint32]$server = 0
    if (-not [Wish.PipeInfo]::GetNamedPipeServerProcessId($pipe.SafePipeHandle.DangerousGetHandle(), [ref]$server)) {
      throw "GetNamedPipeServerProcessId failed, error $([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
    }
    $tags.Add("<<server_pid>> $server") | Out-Null
    if ($server -ne $lane.proc.Id) {
      $verdict = "fail \\.\pipe\WinUAE is served by pid=$server, not by this lane's winuae64 pid=$($lane.proc.Id)"
    }
    if (-not $verdict) {
      # The claim can be stolen with -Override while the pipe was opening; ask again.
      $again = Get-LaneEmulator
      if ($again.err) { $verdict = $again.err }
      elseif ($again.proc.Id -ne $lane.proc.Id) { $verdict = "fail winuae64 pid=$($again.proc.Id) is not the pid=$($lane.proc.Id) this lane started" }
    }
    if (-not $verdict) {
      $before = Read-Drives $pipe $sw 0 $tags
      if (-not $before.q0.StartsWith("200 `n", [StringComparison]::Ordinal)) {
        $verdict = "fail The WinUAE pipe is not answering configuration queries ($($before.q0)); nothing was sent"
      }
      elseif (-not $write) { $verdict = "ok drives pid=$($lane.proc.Id)" }
      else {
        $o = 1 - $drive
        if ($before.paths[$o] -ceq $path) { $verdict = "fail $path is already in DF$o" }
        elseif ($before.paths[$drive] -ceq $path) {
          # Nothing is sent on this branch, so the last look and the hash check do not apply: the drive already holds the path and no mutation follows.
          $verdict = if ($before.modes[$drive] -ceq 'rw') { "ok already drive=$drive" }
                     else { "fail DF$drive names $path but holds no disk" }
        }
      }
    }
    if (-not $verdict -and $write) {
      # The last look before the one mutation, then the file: it is read as late as
      # it can be, so the hash describes what WinUAE will open.
      $last = Get-LaneDenial
      if ($last) { $verdict = $last }
    }
    if (-not $verdict -and $write) {
      if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { $verdict = "fail $path does not exist" }
      else {
        $got = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
        if ($got -ne $want.ToUpper()) { $verdict = "fail $path hashes $($got.ToLower()), not $($want.ToLower())" }
      }
    }
    if (-not $verdict -and $write) {
      $bytes = Send-Pipe $pipe "CFG floppy$drive $path"
      $tags.Add("<<r>> 0 set $($sw.ElapsedMilliseconds) $([Convert]::ToBase64String($bytes))") | Out-Null
      $setAt = $sw.ElapsedMilliseconds
      $until = $setAt + $PollBoundMs
      $seq = 0; $sawPath = $false; $sawRo = $false; $rwRun = 0; $applied = $false
      while ($sw.ElapsedMilliseconds -lt $until -and -not $verdict -and -not $applied) {
        Start-Sleep -Milliseconds $PollEveryMs
        # A read that starts this close to the deadline would time out on a healthy pipe and name the wrong reason.
        if (($until - $sw.ElapsedMilliseconds) -lt 500) { break }
        $seq++
        $now = Read-Drives $pipe $sw $seq $tags $until
        if ($now.paths[$o] -cne $before.paths[$o] -or $now.modes[$o] -cne $before.modes[$o]) {
          $verdict = "fail DF$o changed while DF$drive was being changed"
        }
        if ($now.paths[$drive] -ceq $path) { $sawPath = $true }
        if ($sawPath -and -not $sawRo) { if ($now.modes[$drive] -ceq 'ro') { $sawRo = $true } }
        elseif ($sawRo) {
          if ($now.modes[$drive] -ceq 'rw' -and $now.paths[$drive] -ceq $path) { $rwRun++ } else { $rwRun = 0 }
          if ($rwRun -ge 2) { $applied = $true }
        }
      }
      if (-not $verdict) {
        $verdict = if ($applied) { "ok inserted drive=$drive polls=$seq" }
                   else { "fail DF$drive was not seen holding $path within $($PollBoundMs / 1000) s" }
      }
    }
  } catch {
    $verdict = "fail $($_.Exception.GetType().FullName): $($_.Exception.Message)"
  } finally {
    if ($pipe) { $pipe.Dispose() }
  }
  # Nothing was sent and there are no replies to keep: a failure before the pipe is open is a rejection.
  if (-not $open) { $verdict; exit 1 }
  $verdict
  $tags
  '<<end>>'
}

switch ($Cmd) {

  'claim' {
    # A tag is not a mutex: `winvm acquire wish-re` from two agents shares one
    # lease file, and the second one's release shuts the VM down under the
    # first. This refuses the second holder instead -- and refuses it whether
    # the two calls arrive an hour or a millisecond apart, which is the part
    # that had to be built rather than asserted. See Try-TakeClaim for what is
    # guaranteed and what is not.
    if (-not $Holder) { 'fail claim needs -Holder <id>'; exit 1 }
    if ($Holder -notmatch '^[A-Za-z0-9._-]{1,64}$') { "fail '$Holder' is not a usable holder name"; exit 1 }
    # Decide from the claim's state, create the file atomically, then read it
    # back and confirm this call's token is the one in it. The confirmation is
    # what makes the answer true rather than merely likely: a delete-and-create
    # pair racing another over a stale or stolen claim can still cross, and a
    # caller whose token was overwritten reports the loss instead of announcing
    # a lane it does not hold.
    $token  = [guid]::NewGuid().ToString('N').Substring(0, 12)
    $taken  = $false
    $lost   = $null
    for ($attempt = 0; $attempt -lt 4 -and -not $taken; $attempt++) {
      $r = Read-Claim
      $previous = $null
      if ($r['state'] -eq 'held') {
        $c = $r['claim']
        if ($c['holder'] -ne $Holder -and -not $Override) {
          "fail the WinUAE lane is claimed by $($c['holder']) since $($c['since']); one Amiga lane at a time"
          Claim-Way-Out $c 'take'
          exit 1
        }
        if ($c['holder'] -eq $Holder) {
          # Already ours, so there is nothing to write, and writing anyway is
          # what the fault was: re-asserting a claim used to delete the file
          # first, and for the couple of milliseconds in between the lane read
          # plainly FREE -- not held, not unreadable -- so another holder's
          # CreateNew landing in there won it without -Override, and its success
          # line did not even say it had taken anything, because what it read
          # was an empty lane. A holder retrying a claim whose ssh reply was
          # lost is an ordinary thing to do.
          #
          # Measured with the gap widened to 200 ms so it could be seen at all:
          # five intrusions in twelve seconds. Touching nothing removes the
          # window rather than narrowing it, and `since` then keeps saying when
          # the lane was actually taken.
          #
          # The first attempt at this wrote a temporary file and called
          # [IO.File]::Replace to rename it over the claim. It never once
          # worked: PowerShell turns the $null backup-path argument into an
          # empty string, and Replace answers "The path is not of a legal
          # form" -- so every re-claim failed, and said "the lane was taken by
          # <yourself> while this call was running".
          "ok claimed by $Holder (already yours since $($c['since']))"
          exit 0
        } else {
          $previous = $c['holder']
          Remove-Item $ClaimFile -Force -ErrorAction SilentlyContinue
        }
      }
      elseif ($r['state'] -eq 'stale') {
        # From an earlier boot. Nobody can still be driving, because every
        # emulator and every run in flight died with the restart.
        Remove-Item $ClaimFile -Force -ErrorAction SilentlyContinue
      }
      elseif ($r['state'] -eq 'unreadable') {
        if (-not $Override) {
          'fail the claim file is there and cannot be read; another claim may be in flight'
          'Try again, or take the lane with: winuae.ps1 claim -Holder <id> -Override'
          exit 1
        }
        Remove-Item $ClaimFile -Force -ErrorAction SilentlyContinue
      }
      if (Try-TakeClaim @{ holder = $Holder; since = (Get-Date).ToString('o'); boot = (Boot-Stamp); token = $token }) {
        Start-Sleep -Milliseconds 150
        $after = Read-Claim
        if ($after['state'] -eq 'held' -and $after['claim']['token'] -eq $token) {
          $taken = $true
          $stolen = if ($previous) { " (taken from $previous)" } else { '' }
          "ok claimed by $Holder$stolen"
        } else {
          $lost = $after['claim']
        }
      } else {
        $lost = (Read-Claim)['claim']
        Start-Sleep -Milliseconds 50
      }
    }
    if (-not $taken) {
      $who = if ($lost -and $lost['holder']) { $lost['holder'] } else { 'another caller' }
      "fail the WinUAE lane was taken by $who while this call was running; one Amiga lane at a time"
      exit 1
    }
  }

  'release' {
    # Releasing does not stop the emulator: the next holder would find one it
    # did not start and be refused by every command, which is the right way
    # round -- an emulator nobody claims is somebody's unfinished run until a
    # person says otherwise.
    if (-not $Holder) { 'fail release needs -Holder <id>'; exit 1 }
    $c = Get-Claim
    if (-not $c) { 'ok nothing to release'; exit 0 }
    if ($c['holder'] -ne $Holder -and -not $Override) {
      "fail the WinUAE lane is claimed by $($c['holder']), not by $Holder"
      "If $($c['holder']) has gone, release it anyway with: winuae.ps1 release -Holder $Holder -Override"
      exit 1
    }
    Remove-Item $ClaimFile -ErrorAction SilentlyContinue
    "ok released by $Holder"
  }

  'start' {
    $deny = Claim-Denial
    if ($deny) { $deny; exit 1 }
    $already = @(Get-Process -Name winuae64 -ErrorAction SilentlyContinue)
    if ($already.Count -gt 0) {
      # Starting over a live emulator would be ignored by the scheduler and the
      # loop below would then report the OLD process as this call's success,
      # with whatever config that one was given.
      $r = Read-Kv $RunFile
      ($already | ForEach-Object {
        # Only name a holder when the receipt is about THIS process. A leftover
        # receipt would otherwise blame an emulator a person started at the
        # console on whoever last used the lane.
        $whose = if ($r['pid'] -and [int]$r['pid'] -eq $_.Id -and $r['holder']) { " started by $($r['holder'])" } else { '' }
        "fail winuae64 already running pid=$($_.Id)$whose; stop it first"
      })
      exit 1
    }
    $wanted = ($Rest -join ' ')
    # No execution time limit: this one is meant to run until `stop`.
    $bad = Register-Session1Task $Task $Exe $wanted ([TimeSpan]::Zero)
    if ($bad) { $bad; exit 1 }
    # Everything below the launch is one question: is the emulator that is
    # running the one THIS call asked for? Six keystrokes went into a stranger's
    # Pools of Darkness because the old loop asked only whether a winuae64
    # existed -- #116.
    $launchedAt = Get-Date
    Start-Session1Task $Task
    for ($i = 0; $i -lt 120; $i++) {
      $q = @(Get-Process -Name winuae64 -ErrorAction SilentlyContinue)
      if ($q.Count -gt 1) {
        "fail $($q.Count) winuae64 processes after starting: $(($q | ForEach-Object { $_.Id }) -join ',')"
        exit 1
      }
      if ($q.Count -eq 1) {
        $proc = $q[0]
        $cmdline = (Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.Id)" -ErrorAction SilentlyContinue).CommandLine
        $expected = "`"$Exe`" $wanted"
        if (($cmdline -replace '\s+', ' ').Trim() -ne ($expected -replace '\s+', ' ').Trim()) {
          "fail winuae64 pid=$($proc.Id) is running a command line this call did not pass"
          "  wanted: $expected"
          "  found:  $cmdline"
          exit 1
        }
        # Same command line and still not ours: a neighbouring lane restarting
        # the same config would otherwise be reported as this call's success.
        if ($proc.StartTime -lt $launchedAt.AddSeconds(-2)) {
          "fail winuae64 pid=$($proc.Id) started $($proc.StartTime.ToString('o')), before this call did at $($launchedAt.ToString('o'))"
          exit 1
        }
        Write-Kv $RunFile @{
          holder  = $Holder
          pid     = $proc.Id
          started = $proc.StartTime.ToString('o')
          args    = $wanted
        }
        "ok pid=$($proc.Id) session=$($proc.SessionId)"
        exit 0
      }
      Start-Sleep -Milliseconds 250
    }
    "fail no winuae64 process after 30s: $(Why-NotRun $Task)"; exit 1
  }

  'stop' {
    # Ends the tree this task started. Never a kill by name: nothing here
    # touches a winuae64 somebody else launched -- and "somebody else" is the
    # ordinary case on a VM with one task and one process name, which is why
    # the receipt is checked before anything is stopped.
    $deny = Claim-Denial
    if ($deny) { $deny; exit 1 }
    if (-not (Get-Process -Name winuae64 -ErrorAction SilentlyContinue)) {
      Remove-Item $RunFile -ErrorAction SilentlyContinue
      'ok stopped'; exit 0
    }
    $mine = Resolve-MyEmulator
    if ($mine.err -and -not $Override) {
      $mine.err
      'stop refuses an emulator it did not launch; pass -Override to end it anyway'
      exit 1
    }
    if ($mine.err) { "ok overriding: $($mine.err)" }
    Stop-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 40; $i++) {
      if (-not (Get-Process -Name winuae64 -ErrorAction SilentlyContinue)) {
        Remove-Item $RunFile -ErrorAction SilentlyContinue
        'ok stopped'; exit 0
      }
      Start-Sleep -Milliseconds 250
    }
    'fail winuae64 still running 10s after Stop-ScheduledTask'; exit 1
  }

  'front' {
    $deny = Claim-Denial
    if ($deny) { $deny; exit 1 }
    $mine = Resolve-MyEmulator
    if ($mine.err) { $mine.err; exit 1 }
    $r = Invoke-Session1 'winuae-front' ($Preamble + (Pid-Guard $mine.proc.Id) + $RaiseAndCheck + @'

Report $(if ($fg) { "ok raised pid=$($p.Id) hwnd=$h" } else { "fail pid=$($p.Id) did not take the foreground" })
'@)
    $r
    if ($r -notmatch '^ok') { exit 1 }
  }

  'key' {
    # Synthesise a real key press in session 1. keybd_event goes in at the
    # driver level, so WinUAE's DirectInput keyboard sees it; PostMessage
    # would not. $Rest[0] is a virtual-key code in hex, e.g. 7A for F11.
    #
    # -Extended adds KEYEVENTF_EXTENDEDKEY, and it is not cosmetic. WinUAE
    # reads scancodes, and keybd_event derives one from the virtual key
    # without the E0 prefix unless asked: VK_UP, VK_DOWN, VK_LEFT and
    # VK_RIGHT then arrive as DIK_NUMPAD8, 2, 4 and 6. So `key 26` is the
    # keypad and `key 26 -Extended` is the cursor key, and both matter here --
    # Amiga Curse and Amiga Silver Blades read the party's direction from
    # either. See #361 (An Amiga party cannot be made to walk, because the
    # WinUAE driver sends only keystrokes).
    #
    # `responding` is reported for information and is NOT a receipt for the
    # debugger being up: measured at the debugger's own prompt, with the
    # emulation thread held, `Responding` was still True and the title bar
    # still read "[goldbox-a500.uae] - WinUAE". The receipt for F11 is the ">"
    # prompt in what `send` reads back off the console.
    $deny = Claim-Denial
    if ($deny) { $deny; exit 1 }
    if (-not ($Rest[0] -match '^[0-9A-Fa-f]{1,2}$')) { "fail '$($Rest[0])' is not a hex VK code"; exit 1 }
    $vk = $Rest[0]
    $down = if ($Extended) { 1 } else { 0 }   # KEYEVENTF_EXTENDEDKEY
    $up   = $down + 2                         # ... | KEYEVENTF_KEYUP
    $how  = if ($Extended) { ' extended' } else { '' }
    $mine = Resolve-MyEmulator
    if ($mine.err) { $mine.err; exit 1 }
    $r = Invoke-Session1 'winuae-key' ($Preamble + (Pid-Guard $mine.proc.Id) + $RaiseAndCheck + @"

if (-not `$fg) { Report "fail pid=`$(`$p.Id) did not take the foreground, so the key would go elsewhere"; exit 1 }
[W]::keybd_event(0x$vk, 0, $down, [IntPtr]::Zero)
Start-Sleep -Milliseconds 120
[W]::keybd_event(0x$vk, 0, $up, [IntPtr]::Zero)
Start-Sleep -Milliseconds 500
`$p.Refresh()
Report "ok pressed VK 0x$vk$how at pid=`$(`$p.Id) responding=`$(`$p.Responding)"
"@)
    $r
    if ($r -notmatch '^ok') { exit 1 }
  }

  'send' {
    # $Rest is passed straight to winuae-send.ps1. Quote it as ONE argument --
    #   send '-File C:\Amiga\cmds.txt'
    #   send '-DumpOnly -Tail 400'
    # unquoted, PowerShell tries to bind -File and -Tail to this script's own
    # parameters and fails with AmbiguousParameter.
    # The injector has to run in session 1 too: consoles are per-session, so
    # AttachConsole from here -- session 0 -- can never see WinUAE's, and says
    # so with GetLastError 203.
    $deny = Claim-Denial
    if ($deny) { $deny; exit 1 }
    # Two emulators means two consoles, and the injector would attach to
    # whichever was listed first; an emulator this lane did not start means
    # typing into somebody else's game. Same rule as `front` and `key`.
    $mine = Resolve-MyEmulator
    if ($mine.err) { $mine.err; exit 1 }
    $p = $mine.proc
    Remove-Item $SendLog -ErrorAction SilentlyContinue
    $token = [guid]::NewGuid().ToString('N').Substring(0, 12)
    $sendargs = $Rest -join ' '
    # A caller-supplied -TargetPid used to be preferred verbatim, which walked
    # straight past the ownership check above: the injector would attach to
    # whatever console that pid owns. It was inert only because
    # Resolve-MyEmulator refuses when there is more than one winuae64 -- safety
    # belonging to a different check is not safety here. The driver knows the
    # right pid; anything else is refused.
    # -match is not global, so it reads only the FIRST -TargetPid: given two,
    # the check would pass on the good one while both were forwarded to
    # winuae-send.ps1, whose binder's preference between them is not something
    # this depends on. Refuse the form instead of needing the answer.
    # 'IgnoreCase' is not decoration: [regex]::Matches is the static .NET call
    # and is case-SENSITIVE, while the -match below is not. Without it,
    # `-targetpid 6136 -TargetPid 8272` counts as one occurrence, the rejection
    # never fires, -match reads the first, and both flags are forwarded exactly
    # as they were before any of this was written.
    if (@([regex]::Matches($sendargs, '-TargetPid', 'IgnoreCase')).Count -gt 1) {
      'fail send was given more than one -TargetPid'
      exit 1
    }
    if ($sendargs -match '-TargetPid(?:\s+(\d+))?') {
      $given = $Matches[1]
      if (-not $given -or [int]$given -ne $p.Id) {
        $shown = if ($given) { $given } else { '(no pid)' }
        "fail send was given -TargetPid $shown, but this lane's emulator is pid=$($p.Id)"
        exit 1
      }
    } else {
      $sendargs = "-TargetPid $($p.Id) $sendargs"
    }
    $sendargs = "$sendargs -Token $token"
    # Bounded, unlike `start`: this finishes or it has gone wrong. A command
    # costs ~0.7s and a batch is tens of lines, so ten minutes is generous.
    $bad = Register-Session1Task 'winuae-send' 'powershell.exe' `
      ("-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden " +
       "-File $Root\winuae-send.ps1 $sendargs") ([TimeSpan]::FromMinutes(10))
    if ($bad) { $bad; exit 1 }
    Start-Session1Task 'winuae-send'
    # winuae-send.ps1 ends every path with "--- exit N token=...". Wait for it
    # rather than for the task, so what is reported is the injector's own
    # verdict -- and match OUR token, so a log an earlier call left behind
    # cannot be read as this one's.
    #
    # Eleven minutes against the task's ten: waiting exactly as long as the
    # limit races it, and "killed by its own ExecutionTimeLimit" and "still
    # going" then look identical. The extra minute lets Why-NotRun report the
    # scheduler's own reason instead.
    $verdict = {
      $tail = Read-SendLog
      if (-not $tail) { return $null }
      $last = $tail | Select-String -Pattern "--- exit (\d+) token=$token" | Select-Object -Last 1
      if ($last) { return @{ code = [int]$last.Matches[0].Groups[1].Value; log = $tail } }
      return $null
    }
    # The injector can die without writing its verdict -- measured: the
    # unguarded version reached "CONIN opened" and went no further, and the
    # task went back to Ready with LastTaskResult 1. Watching for that turns an
    # eleven-minute wait into a couple of seconds for the whole class of
    # "it started and never finished".
    $sawRunning = $false
    for ($i = 0; $i -lt 6600; $i++) {
      $v = & $verdict
      if (-not $v -and ($i % 10) -eq 0) {
        $st = (Get-ScheduledTask -TaskName 'winuae-send').State
        if ($st -eq 'Running') { $sawRunning = $true }
        elseif (-not $sawRunning -and $i -ge 300) {
          # Thirty seconds and it has never once been seen running: this is the
          # nobody-logged-on case, and waiting out the other ten and a half
          # minutes teaches nothing that Why-NotRun cannot say now.
          "fail winuae-send never started: $(Why-NotRun 'winuae-send')"; exit 1
        }
        elseif ($sawRunning) {
          # The state change and the last line of the log are not ordered
          # against each other, so look once more before calling it a death.
          Start-Sleep -Milliseconds 500
          $v = & $verdict
          if (-not $v) {
            # `Why-NotRun` carries the task's own `lastResult`, so a verdict
            # line lost to a failing write still surfaces the injector's real
            # exit code -- the line is lost, the code is not.
            "fail winuae-send ended without writing a verdict: $(Why-NotRun 'winuae-send')" +
              $(if ($script:readFailures) { " (send.log could not be read $script:readFailures times)" } else { '' })
            Read-SendLog
            exit 1
          }
        }
      }
      if ($v) {
        $v.log
        if ($v.code -ne 0) { "fail winuae-send exited $($v.code)"; exit $v.code }
        "ok sent to pid $($p.Id)"; exit 0
      }
      Start-Sleep -Milliseconds 100
    }
    "fail winuae-send never finished: $(Why-NotRun 'winuae-send')"; exit 1
  }

  'roms' {
    # The GUI does not use the kickstart_rom_file path in a .uae config. It
    # resolves ROMs through WinUAE's own scanned database, so on a machine
    # where the scan has never run, opening WinUAE tells a person there are no
    # ROMs at all -- "One of the following system ROMs is required: KS ROM
    # v1.3 ... [315093-02] ... click Rescan ROMs".
    #
    # Two registry values do it, with no GUI and no clicking: point
    # KickstartPath at the ROM directory, and delete the DetectedROMs subkey.
    # WinUAE rescans KickstartPath at startup whenever that database is
    # missing, so the next launch -- headless, use_gui=no -- rebuilds it.
    # Measured: 5 built-in pseudo-ROMs before, 14 entries after.
    #
    # Run this once and `winvm promote`, so the Gold image always has it.
    # `start` refuses over a live emulator and so does this: the scan launches
    # its own `winuae64`, and for the minute it runs there are two, which is
    # exactly the ambiguity `front`, `key` and `send` now refuse. Nothing
    # enforced this, and `roms` is the one command that creates the condition.
    $deny = Claim-Denial
    if ($deny) { $deny; exit 1 }
    $live = Get-Process -Name winuae64 -ErrorAction SilentlyContinue
    if ($live) {
      ($live | ForEach-Object { "fail winuae64 running pid=$($_.Id); roms starts its own, stop this one first" })
      exit 1
    }
    if (-not (Test-Path $RomDir)) { "fail no ROM directory at $RomDir"; exit 1 }
    # Say what actually went wrong. Unchecked, a refused or misdirected write
    # surfaces three steps later as "no KS 1.3 ... under $RomDir", which reads
    # as a missing ROM file and sends the next person to the wrong place
    # entirely. Measured: Set-ItemProperty on a key that does not exist is a
    # NON-terminating ItemNotFoundException -- $? goes False and the script
    # walks straight on.
    New-Item -Path $RomKey -Force -ErrorAction SilentlyContinue | Out-Null
    try { Set-ItemProperty $RomKey -Name KickstartPath -Value $RomDir -ErrorAction Stop }
    catch { "fail could not write KickstartPath under ${RomKey}: $($_.Exception.Message)"; exit 1 }
    $wrote = (Get-ItemProperty $RomKey -Name KickstartPath -ErrorAction SilentlyContinue).KickstartPath
    if ($wrote -ne $RomDir) { "fail KickstartPath reads back as '$wrote', not '$RomDir'"; exit 1 }

    Remove-Item "$RomKey\DetectedROMs" -Recurse -Force -ErrorAction SilentlyContinue
    $scan = Start-Process $Exe -PassThru -ArgumentList `
      '-f', "$Root\configs\goldbox-a500.uae", '-s', 'floppy0=', '-s', 'floppy1='
    # Wait for the database WinUAE is being run to build, rather than sleeping a
    # fixed ten seconds and killing whatever state the scan had reached. A
    # slower guest would otherwise be left with a partial DetectedROMs, which is
    # worse than the five-entry baseline it replaced.
    $ks13 = $null
    for ($i = 0; $i -lt 120; $i++) {
      Start-Sleep -Milliseconds 500
      if (-not (Test-Path "$RomKey\DetectedROMs")) { continue }
      $props = (Get-Item "$RomKey\DetectedROMs").Property
      $roms = $props | ForEach-Object { (Get-ItemProperty "$RomKey\DetectedROMs" -Name $_).$_ }
      # The one the ROM dialog asks for by name -- Kickstart 1.3 rev 34.5, 256k.
      # It arrives last of the real entries, so seeing it means the scan is done.
      $ks13 = $roms | Where-Object { $_ -match '\[315093-02\]' }
      if ($ks13) { break }
    }
    Stop-Process -Id $scan.Id -Force -ErrorAction SilentlyContinue   # the pid we started, not a name
    if (-not (Test-Path "$RomKey\DetectedROMs")) { 'fail the scan wrote no ROM database'; exit 1 }
    $props = (Get-Item "$RomKey\DetectedROMs").Property
    $props | ForEach-Object { (Get-ItemProperty "$RomKey\DetectedROMs" -Name $_).$_ } |
      Where-Object { $_ -notmatch '^:' } | Sort-Object
    if (-not $ks13) { "fail no KS 1.3 rev 34.5 [315093-02] under $RomDir"; exit 1 }
    "ok $($props.Count) entries, System ROMs = $RomDir"
  }

  'clean' {
    # Scheduled tasks outlive the run that registered them, and `winvm promote`
    # would weld them into the golden image; golden should carry the emulator
    # and the scripts, not the scaffolding.
    #
    # Refusing while the emulator is alive is safety, not tidiness. Unregistering
    # winuae-run does NOT stop a winuae64 that task already launched, and with
    # the definition gone `stop`'s Stop-ScheduledTask is a silent no-op --
    # measured: on an unregistered name it returns $? = False, prints nothing
    # and throws nothing. `stop` would then report "still running" for ever and
    # the only route left would be a kill by name, which is forbidden here and
    # has already killed the wrong window once.
    if (Get-Process -Name winuae64 -ErrorAction SilentlyContinue) {
      'fail winuae64 is running; run `stop` first, or clean would strand it'
      exit 1
    }
    $c = Get-Claim
    if ($c -and $c['holder'] -ne $Holder -and -not $Override) {
      "fail the WinUAE lane is claimed by $($c['holder']) since $($c['since']); clean would take the scaffolding out from under it"
      "If $($c['holder']) has gone, clean anyway with: winuae.ps1 clean -Override"
      exit 1
    }
    foreach ($t in @($Task) + $Helpers) {
      Unregister-ScheduledTask -TaskName $t -Confirm:$false -ErrorAction SilentlyContinue
    }
    Remove-Item $Receipt, $SendLog, $RunFile, $ClaimFile, "$Root\console.txt" -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $StateRoot -Recurse -Force -ErrorAction SilentlyContinue
    'ok cleaned'
  }

  'drives' {
    # Read-only: what DF0 and DF1 name and whether each holds a disk. See the
    # notes above Invoke-Floppy for the output.
    Invoke-Floppy 'drives'
  }

  'diagnose' { Invoke-Diagnose }
  'config-hash' { Invoke-PrivateConfig 'config-hash' }
  'config-remove' { Invoke-PrivateConfig 'config-remove' }
  'snapshot' { Invoke-State 'snapshot' }
  'restore' { Invoke-State 'restore' }
  'discard-snapshot' { Invoke-State 'discard-snapshot' }

  'insert' {
    # insert <drive 0|1> <path> <sha256>: the one mutation this script makes over
    # WinUAE's pipe. The path must be a disk staged for -Holder under
    # C:\Amiga\Disks and the file must hash to <sha256> before anything is sent.
    Invoke-Floppy 'insert'
  }

  'status' {
    Get-Process -Name winuae64 -ErrorAction SilentlyContinue |
      ForEach-Object { "pid=$($_.Id) session=$($_.SessionId) responding=$($_.Responding) start=$($_.StartTime)" }
    $c = Get-Claim
    if ($c) { "claim = $($c['holder']) since $($c['since'])" } else { 'claim = none' }
    $r = Read-Kv $RunFile
    if ($r.ContainsKey('pid')) { "run   = pid=$($r['pid']) holder=$($r['holder']) args=$($r['args'])" } else { 'run   = no receipt' }
    "System ROMs = $((Get-ItemProperty $RomKey -Name KickstartPath -ErrorAction SilentlyContinue).KickstartPath)"
    $n = if (Test-Path "$RomKey\DetectedROMs") {
           (Get-Item "$RomKey\DetectedROMs" | Select-Object -ExpandProperty Property).Count
         } else { 0 }
    "ROM database = $n entries"
  }
}
