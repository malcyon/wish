# Proves that one driver of WinUAE cannot destroy another's run. Runs on the
# Windows guest, against whichever copy of winuae.ps1 you point it at, so the
# same check can be run against an older copy to watch it fail.
#
#   export SSH_ASKPASS_REQUIRE=never
#   scp tools/winuae-lanecheck.ps1 donald@192.168.123.50:'C:/Amiga/'
#   winvm ssh 'powershell -NoProfile -ExecutionPolicy Bypass -File C:\Amiga\winuae-lanecheck.ps1'
#   winvm ssh 'powershell ... -File C:\Amiga\winuae-lanecheck.ps1 -Driver C:\Amiga\winuae-old.ps1'
#
# Written for #116 (Two agents cannot share the WinUAE VM, and neither of them
# can tell), where a second agent's `start` launched somebody else's config, its
# `key` typed six times into their game, and its `stop` ended their session
# three times in one night -- every call reporting ok.
#
# Each scenario is one of those, as a driver B doing something to a driver A's
# emulator. PASS means B was refused.
#
# It leaves nothing behind: the lane is reset before and after every scenario,
# and never by killing a process by name -- Stop-ScheduledTask ends the tree
# the task started, which is the only winuae64 this check ever creates.

param(
  [string]$Driver   = 'C:\Amiga\winuae.ps1',
  [int]$Rounds      = 3,
  [ValidateSet('all','args','own','hijack','foreignstop','foreignkey','claim')][string]$Scenario = 'all'
)

$Exe     = 'C:\Program Files\WinUAE\winuae64.exe'
$Root    = 'C:\Amiga'
$Task    = 'winuae-run'
$ConfigA = "$Root\configs\pod-a500.uae"        # driver A: Pools of Darkness
$ConfigB = "$Root\configs\goldbox-a500.uae"    # driver B: the Gold Box machine
$ArgsA   = "-log -f $ConfigA"
$ArgsB   = "-log -f $ConfigB"

if (-not (Test-Path $Driver))  { "fail no driver at $Driver"; exit 1 }
if (-not (Test-Path $ConfigA)) { "fail no config at $ConfigA"; exit 1 }
if (-not (Test-Path $ConfigB)) { "fail no config at $ConfigB"; exit 1 }

# An older winuae.ps1 has no -Holder and no claim, so the claim scenarios are
# reported as n/a against it rather than as failures of something it never had.
# Asked of the command word rather than of a -Holder parameter: winuae.ps1
# reads -Holder out of its remaining arguments, so there is no parameter of
# that name to look for.
$HasClaim = @(((Get-Command $Driver).Parameters['Cmd'].Attributes |
               Where-Object { $_ -is [System.Management.Automation.ValidateSetAttribute] }).ValidValues) -contains 'claim'

$script:pass = 0
$script:fail = 0
function Verdict([bool]$Ok, [string]$What, [string]$Saw) {
  if ($Ok) { $script:pass++; "  PASS $What" } else { $script:fail++; "  FAIL $What" }
  foreach ($l in @($Saw -split "`r?`n" | Where-Object { $_.Trim() -ne '' })) { "        | $l" }
}

function Drive([string[]]$DriverArgs) {
  $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Driver @DriverArgs 2>&1 | Out-String
  @{ out = $out.Trim(); code = $LASTEXITCODE }
}

function Holder-Args([string]$Who) { if ($HasClaim) { @('-Holder', $Who) } else { @() } }

# Every caller wraps this in @(), and that is not decoration. A function's
# array return is unrolled by the pipeline, so `(Emulators).Count` on a single
# emulator asks a CimInstance for a Count property it does not have, gets
# $null, and reports "A's emulator did not start" about one that had. Returning
# `,@(...)` to keep the array fixes that and breaks the empty case instead,
# where it wraps nothing in a one-element array. @() at the call site is the
# only form that is right at 0, 1 and n.
function Emulators { Get-CimInstance Win32_Process -Filter "Name='winuae64.exe'" -ErrorAction SilentlyContinue }

# Everything here goes through the task the lane owns. Never a kill by name:
# this check exists because killing by name is what destroyed other people's
# runs in the first place.
function Reset-Lane {
  Stop-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue
  for ($i = 0; $i -lt 60; $i++) {
    if (@(Emulators).Count -eq 0) { break }
    Start-Sleep -Milliseconds 250
  }
  Remove-Item "$Root\winuae-claim.txt", "$Root\winuae-run.txt" -ErrorAction SilentlyContinue
  @(Emulators).Count -eq 0
}

# Driver A, launching an emulator the way a second agent does: straight at the
# one shared task, which is all a second agent has.
function Start-AsIntruder([string]$Arguments) {
  $a = New-ScheduledTaskAction -Execute $Exe -Argument $Arguments -WorkingDirectory $Root
  $p = New-ScheduledTaskPrincipal -UserId "$env:COMPUTERNAME\donald" -LogonType Interactive
  $s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
         -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
  Register-ScheduledTask -TaskName $Task -Action $a -Principal $p -Settings $s -Force | Out-Null
  Stop-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue
  Start-ScheduledTask -TaskName $Task
  for ($i = 0; $i -lt 120; $i++) {
    $e = @(Emulators)
    if ($e.Count -ge 1) { return $e[0] }
    Start-Sleep -Milliseconds 250
  }
  $null
}

function Scenario-Args {
  "args: `start` passes its WinUAE arguments through untouched"
  for ($n = 1; $n -le $Rounds; $n++) {
    if (-not (Reset-Lane)) { Verdict $false "round ${n}: lane would not reset" ''; continue }
    if ($HasClaim) { Drive (@('claim') + (Holder-Args 'lanecheck')) | Out-Null }
    $r = Drive (@('start') + (Holder-Args 'lanecheck') +
                @('-log', '-f', $ConfigB, '-s', 'floppy0='))
    $cmd = (Emulators | Select-Object -First 1).CommandLine
    $want = "`"$Exe`" -log -f $ConfigB -s floppy0="
    Verdict (($cmd -replace '\s+', ' ').Trim() -eq $want) `
            "round ${n}: the emulator's command line is the one start was given" `
            ("start said: $($r.out)`nran: $cmd")
  }
  Reset-Lane | Out-Null
}

# The guards have to refuse the neighbour without refusing the holder, and a
# check that only ever asserts a refusal cannot tell a working lane from a
# bricked one.
function Scenario-Own {
  "own: the holder can start, drive and stop its own emulator"
  if (-not (Reset-Lane)) { Verdict $false 'lane would not reset' ''; return }
  if ($HasClaim) {
    $c = Drive @('claim', '-Holder', 'lanecheck')
    Verdict ($c.code -eq 0) 'the holder takes the lane' $c.out
  }
  $a = Drive (@('start') + (Holder-Args 'lanecheck') + @('-log', '-f', $ConfigB))
  Verdict ($a.code -eq 0 -and $a.out -match '^ok pid=') 'the holder can start' $a.out
  $k = Drive (@('key', '7A') + (Holder-Args 'lanecheck'))
  Verdict ($k.code -eq 0 -and $k.out -match '^ok pressed VK 0x7A') 'the holder can press F11' $k.out
  $s = Drive (@('stop') + (Holder-Args 'lanecheck'))
  Verdict ($s.code -eq 0 -and @(Emulators).Count -eq 0) 'the holder can stop' $s.out
  if ($HasClaim) {
    $r = Drive @('release', '-Holder', 'lanecheck')
    Verdict ($r.code -eq 0) 'the holder can release' $r.out
  }
  Reset-Lane | Out-Null
}

function Scenario-Hijack {
  "hijack: B's `start` must not report success for an emulator B did not launch"
  for ($n = 1; $n -le $Rounds; $n++) {
    if (-not (Reset-Lane)) { Verdict $false "round ${n}: lane would not reset" ''; continue }
    if ($HasClaim) { Drive (@('claim') + (Holder-Args 'driverB')) | Out-Null }
    # B asks for its own config. A -- a second agent, a stale script, a person
    # at the VM -- takes the one shared task the moment an emulator appears, so
    # what is running when B looks is A's. That is a sub-second overlap between
    # two calls, and it is what happened on the night this was filed.
    $job = Start-Job -ScriptBlock {
      param($drv, $cfg, $who)
      $ha = if ($who) { @('-Holder', $who) } else { @() }
      & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $drv start @ha -log -f $cfg 2>&1 | Out-String
      "exit=$LASTEXITCODE"
    } -ArgumentList $Driver, $ConfigB, $(if ($HasClaim) { 'driverB' } else { '' })
    # Take the task the moment B has started it, not when B's emulator appears:
    # WinUAE takes about a second to become a process, and that second is the
    # whole window. Trigger later and B sees its own emulator first, which is
    # the run that goes right.
    $before = (Get-ScheduledTaskInfo -TaskName $Task -ErrorAction SilentlyContinue).LastRunTime
    for ($i = 0; $i -lt 1500; $i++) {
      $now = (Get-ScheduledTaskInfo -TaskName $Task -ErrorAction SilentlyContinue).LastRunTime
      if ($now -ne $before) { break }
      Start-Sleep -Milliseconds 20
    }
    $intruder = Start-AsIntruder $ArgsA
    $out = (Receive-Job -Job $job -Wait -AutoRemoveJob) -join "`n"
    $live = Emulators | Select-Object -First 1
    $saidOk = $out -match '(?m)^ok pid='
    $runsA  = $live -and $live.CommandLine -match [regex]::Escape($ConfigA)
    Verdict (-not ($saidOk -and $runsA)) `
            "round ${n}: B was not handed A's emulator as its own success" `
            ("B said: $out`nrunning: $($live.CommandLine)")
  }
  Reset-Lane | Out-Null
}

function Scenario-ForeignStop {
  "foreignstop: B's `stop` must refuse an emulator A started"
  for ($n = 1; $n -le $Rounds; $n++) {
    if (-not (Reset-Lane)) { Verdict $false "round ${n}: lane would not reset" ''; continue }
    if ($HasClaim) { Drive (@('claim') + (Holder-Args 'driverA')) | Out-Null }
    $a = Drive (@('start') + (Holder-Args 'driverA') + @('-log', '-f', $ConfigA))
    if (@(Emulators).Count -ne 1) { Verdict $false "round ${n}: A's emulator did not start" $a.out; continue }
    $apid = @(Emulators)[0].ProcessId
    # B holds no claim at all, which is the ordinary case: it never knew there
    # was one to hold.
    $b = Drive @('stop')
    $stillA = @(Emulators | Where-Object { $_.ProcessId -eq $apid }).Count -eq 1
    Verdict $stillA "round ${n}: A's emulator survived B's stop" ("B said: $($b.out)")
    if ($HasClaim -and $stillA) {
      # And the layer under the claim: B holds the lane, having taken it after
      # A walked away, and still must not end a run it did not start.
      Drive (@('release') + (Holder-Args 'driverA') + @('-Override')) | Out-Null
      Drive (@('claim') + (Holder-Args 'driverB')) | Out-Null
      $b2 = Drive (@('stop') + (Holder-Args 'driverB'))
      $stillA2 = @(Emulators | Where-Object { $_.ProcessId -eq $apid }).Count -eq 1
      Verdict $stillA2 "round ${n}: A's emulator survived the new holder's stop" ("B said: $($b2.out)")
    }
  }
  Reset-Lane | Out-Null
}

function Scenario-ForeignKey {
  "foreignkey: B's `key` must refuse an emulator A started"
  for ($n = 1; $n -le $Rounds; $n++) {
    if (-not (Reset-Lane)) { Verdict $false "round ${n}: lane would not reset" ''; continue }
    if ($HasClaim) { Drive (@('claim') + (Holder-Args 'driverA')) | Out-Null }
    $a = Drive (@('start') + (Holder-Args 'driverA') + @('-log', '-f', $ConfigA))
    if (@(Emulators).Count -ne 1) { Verdict $false "round ${n}: A's emulator did not start" $a.out; continue }
    $b = Drive @('key', '7A')
    Verdict ($b.code -ne 0) "round ${n}: B's keypress was refused" ("B said: $($b.out)")
  }
  Reset-Lane | Out-Null
}

function Scenario-Claim {
  "claim: a second holder is refused"
  if (-not $HasClaim) { "  n/a $Driver has no claim"; return }
  Reset-Lane | Out-Null
  $first  = Drive @('claim', '-Holder', 'driverA')
  Verdict ($first.code -eq 0) 'the first holder is granted the lane' $first.out
  $second = Drive @('claim', '-Holder', 'driverB')
  Verdict ($second.code -ne 0) 'the second holder is refused' $second.out
  $wrong  = Drive @('release', '-Holder', 'driverB')
  Verdict ($wrong.code -ne 0) 'a release by anyone but the holder is refused' $wrong.out
  $steal  = Drive @('claim', '-Holder', 'driverB', '-Override')
  Verdict ($steal.code -eq 0 -and $steal.out -match 'taken from driverA') `
          'a stale claim can be taken deliberately, and says whose it was' $steal.out
  $free   = Drive @('release', '-Holder', 'driverB')
  Verdict ($free.code -eq 0) 'the holder can release' $free.out
  $unheld = Drive @('start', '-log', '-f', $ConfigB)
  Verdict ($unheld.code -ne 0) 'an unclaimed start is refused' $unheld.out
  Reset-Lane | Out-Null
}

"driver: $Driver (claim: $(if ($HasClaim) { 'yes' } else { 'no' })), $Rounds rounds"
if ($Scenario -in @('all','args'))        { Scenario-Args }
if ($Scenario -in @('all','claim'))       { Scenario-Claim }
if ($Scenario -in @('all','own'))         { Scenario-Own }
if ($Scenario -in @('all','hijack'))      { Scenario-Hijack }
if ($Scenario -in @('all','foreignstop')) { Scenario-ForeignStop }
if ($Scenario -in @('all','foreignkey'))  { Scenario-ForeignKey }

"$($script:pass) passed, $($script:fail) failed"
if (@(Emulators).Count -ne 0) { "warning: winuae64 still running: $(((Emulators) | ForEach-Object { $_.ProcessId }) -join ',')" }
if ($script:fail -gt 0) { exit 1 }
