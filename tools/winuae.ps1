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
#   winvm ssh "$ps roms"                        # once, then winvm promote
#   winvm ssh "$ps start -log -f C:\Amiga\configs\goldbox-a500.uae"
#   winvm ssh "$ps key 7A"                      # F11: enter the debugger
#   winvm ssh "$ps send '-File C:\Amiga\cmds.txt'"
#   winvm ssh "$ps send '-DumpOnly -Tail 40'"   # read the console back
#   winvm ssh "$ps front"
#   winvm ssh "$ps status"
#   winvm ssh "$ps stop"                        # before clean, always
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

param(
  [Parameter(Mandatory=$true)]
  [ValidateSet('start','stop','front','status','send','key','roms','clean')][string]$Cmd,
  [Parameter(ValueFromRemainingArguments=$true)][string[]]$Rest
)

$Exe     = 'C:\Program Files\WinUAE\winuae64.exe'
$Root    = 'C:\Amiga'
$Task    = 'winuae-run'
$Helpers = 'winuae-front','winuae-key','winuae-send'
$Receipt = "$Root\winuae-action.txt"    # what a session 1 helper writes back
$SendLog = "$Root\send.log"
$RomKey  = 'HKCU:\Software\Arabuusimiehet\WinUAE'
$RomDir  = "$Root\Kickstarts\"

function Register-Session1Task {
  param([string]$Name, [string]$Program, [string]$Arguments, [TimeSpan]$Limit)
  $a = New-ScheduledTaskAction -Execute $Program -Argument $Arguments -WorkingDirectory $Root
  $p = New-ScheduledTaskPrincipal -UserId "$env:COMPUTERNAME\donald" -LogonType Interactive
  $s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit $Limit `
         -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
  Register-ScheduledTask -TaskName $Name -Action $a -Principal $p -Settings $s -Force | Out-Null
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
  Register-Session1Task $Name 'powershell.exe' `
    "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -EncodedCommand $enc" `
    ([TimeSpan]::FromMinutes(1))
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

switch ($Cmd) {

  'start' {
    $already = Get-Process -Name winuae64 -ErrorAction SilentlyContinue
    if ($already) {
      # Starting over a live emulator would be ignored by the scheduler and the
      # loop below would then report the OLD process as this call's success,
      # with whatever config that one was given.
      ($already | ForEach-Object { "fail winuae64 already running pid=$($_.Id); stop it first" })
      exit 1
    }
    # No execution time limit: this one is meant to run until `stop`.
    Register-Session1Task $Task $Exe ($Rest -join ' ') ([TimeSpan]::Zero)
    Start-Session1Task $Task
    for ($i = 0; $i -lt 120; $i++) {
      $q = Get-Process -Name winuae64 -ErrorAction SilentlyContinue
      if ($q) { $q | ForEach-Object { "ok pid=$($_.Id) session=$($_.SessionId)" }; exit 0 }
      Start-Sleep -Milliseconds 250
    }
    "fail no winuae64 process after 30s: $(Why-NotRun $Task)"; exit 1
  }

  'stop' {
    # Ends the tree this task started. Never a kill by name: nothing here
    # touches a winuae64 somebody else launched.
    Stop-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 40; $i++) {
      if (-not (Get-Process -Name winuae64 -ErrorAction SilentlyContinue)) { 'ok stopped'; exit 0 }
      Start-Sleep -Milliseconds 250
    }
    'fail winuae64 still running 10s after Stop-ScheduledTask'; exit 1
  }

  'front' {
    $r = Invoke-Session1 'winuae-front' ($Preamble + $RaiseAndCheck + @'

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
    # `responding` is reported for information and is NOT a receipt for the
    # debugger being up: measured at the debugger's own prompt, with the
    # emulation thread held, `Responding` was still True and the title bar
    # still read "[goldbox-a500.uae] - WinUAE". The receipt for F11 is the ">"
    # prompt in what `send` reads back off the console.
    if (-not ($Rest[0] -match '^[0-9A-Fa-f]{1,2}$')) { "fail '$($Rest[0])' is not a hex VK code"; exit 1 }
    $vk = $Rest[0]
    $r = Invoke-Session1 'winuae-key' ($Preamble + $RaiseAndCheck + @"

if (-not `$fg) { Report "fail pid=`$(`$p.Id) did not take the foreground, so the key would go elsewhere"; exit 1 }
[W]::keybd_event(0x$vk, 0, 0, [IntPtr]::Zero)
Start-Sleep -Milliseconds 120
[W]::keybd_event(0x$vk, 0, 2, [IntPtr]::Zero)
Start-Sleep -Milliseconds 500
`$p.Refresh()
Report "ok pressed VK 0x$vk at pid=`$(`$p.Id) responding=`$(`$p.Responding)"
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
    $all = @(Get-Process -Name winuae64 -ErrorAction SilentlyContinue)
    if ($all.Count -eq 0) { 'fail no winuae64'; exit 1 }
    if ($all.Count -gt 1) {
      # Two emulators means two consoles, and the injector would attach to
      # whichever was listed first. Same rule as `front` and `key`.
      "fail $($all.Count) winuae64 processes: $(($all | ForEach-Object { $_.Id }) -join ','); stop all but one"
      exit 1
    }
    $p = $all[0]
    Remove-Item $SendLog -ErrorAction SilentlyContinue
    $token = [guid]::NewGuid().ToString('N').Substring(0, 12)
    $sendargs = $Rest -join ' '
    if ($sendargs -notmatch '-TargetPid') { $sendargs = "-TargetPid $($p.Id) $sendargs" }
    $sendargs = "$sendargs -Token $token"
    # Bounded, unlike `start`: this finishes or it has gone wrong. A command
    # costs ~0.7s and a batch is tens of lines, so ten minutes is generous.
    Register-Session1Task 'winuae-send' 'powershell.exe' `
      ("-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden " +
       "-File $Root\winuae-send.ps1 $sendargs") ([TimeSpan]::FromMinutes(10))
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
      if (-not (Test-Path $SendLog)) { return $null }
      $tail = Get-Content $SendLog
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
            "fail winuae-send ended without writing a verdict: $(Why-NotRun 'winuae-send')"
            Get-Content $SendLog -ErrorAction SilentlyContinue
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
    foreach ($t in @($Task) + $Helpers) {
      Unregister-ScheduledTask -TaskName $t -Confirm:$false -ErrorAction SilentlyContinue
    }
    Remove-Item $Receipt, $SendLog, "$Root\console.txt" -ErrorAction SilentlyContinue
    'ok cleaned'
  }

  'status' {
    Get-Process -Name winuae64 -ErrorAction SilentlyContinue |
      ForEach-Object { "pid=$($_.Id) session=$($_.SessionId) responding=$($_.Responding) start=$($_.StartTime)" }
    "System ROMs = $((Get-ItemProperty $RomKey -Name KickstartPath -ErrorAction SilentlyContinue).KickstartPath)"
    $n = if (Test-Path "$RomKey\DetectedROMs") {
           (Get-Item "$RomKey\DetectedROMs" | Select-Object -ExpandProperty Property).Count
         } else { 0 }
    "ROM database = $n entries"
  }
}
