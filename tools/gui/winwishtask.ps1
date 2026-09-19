<#
Run Wish on the Windows 11 VM's own visible desktop, so a person can look at
the real window at Windows' own font size.

`winvm ssh` lands in Windows session 0, whose window station nobody can see --
`docs/143-winuae-debugger.md` section 1. A GUI started from there never appears
on the screen and never appears in `winvm shot`. So every action here goes
through a scheduled task with an Interactive principal, which runs in whichever
session the user is logged on to, exactly as `C:\Amiga\winuae.ps1` does for
WinUAE.

**Nothing here touches the Amiga lane.** Its scheduled tasks are named
`winuae-*`, its files live under `C:\Amiga`, and neither appears below; every
task this file registers is named `wish-*`.

  winwishtask.ps1 -Action measure   the window's minimum width, to C:\Wish\measure.txt
  winwishtask.ps1 -Action start     open the editor on the ordinary party, and leave it up
  winwishtask.ps1 -Action stop      close it
  winwishtask.ps1 -Action status    what is registered and what is running

Written for #474 (Raising the UI font grows the window's minimum width with an ordinary party open, which is the defect #41 removed for the widest one).
Run on the guest through `tools/gui/winwish.py`, which copies it to C:\Wish.
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('measure', 'start', 'stop', 'status')]
    [string]$Action
)

$ErrorActionPreference = 'Stop'
$Root = 'C:\Wish'
$Py   = 'C:\Wish\venv\Scripts\python.exe'
$Pyw  = 'C:\Wish\venv\Scripts\pythonw.exe'

# Register-ScheduledTask -Force is documented not to end a running instance of
# the task, and #116 saw -Force reported as silently keeping the old action.
# Reading the registration back costs three lines and turns a wrong config into
# an error message. This is winuae.ps1's function, kept deliberately identical.
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
    $null
}

# Task Scheduler's MultipleInstances is IgnoreNew, so a Start while an earlier
# instance is alive is silently dropped. Stop first and wait for Running to
# clear, or a caller reads the previous run's output as its own.
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
    # 0x41303 is "the task has never run", which is what an Interactive
    # principal reports when there is no console logon to run in. It is the one
    # failure that looks exactly like success from the caller's side.
    if ($info.LastTaskResult -eq 267011) {
        $why = ' -- nobody is logged on at the console, so an Interactive task cannot run'
    }
    "state=$((Get-ScheduledTask -TaskName $Name).State) " +
    ("lastResult=0x{0:X}" -f $info.LastTaskResult) +
    " lastRun=$($info.LastRunTime)$why"
}

switch ($Action) {

  'measure' {
    $out = 'C:\Wish\measure.txt'
    Remove-Item $out -ErrorAction SilentlyContinue
    # A scheduled task action cannot redirect, so cmd.exe does it.
    $cmd = "/c `"`"$Py`" `"$Root\winwishmeasure.py`" > `"$out`" 2>&1`""
    $bad = Register-Session1Task 'wish-measure' 'cmd.exe' $cmd ([TimeSpan]::FromMinutes(10))
    if ($bad) { Write-Output $bad; exit 1 }
    Start-Session1Task 'wish-measure'
    for ($i = 0; $i -lt 180; $i++) {
        Start-Sleep -Seconds 1
        if ((Get-ScheduledTask -TaskName 'wish-measure').State -ne 'Running' -and (Test-Path $out)) { break }
    }
    Write-Output (Why-NotRun 'wish-measure')
    if (Test-Path $out) { Get-Content $out } else { Write-Output 'no output file' }
  }

  'start' {
    Remove-Item 'C:\Wish\window.log' -ErrorAction SilentlyContinue
    $bad = Register-Session1Task 'wish-window' $Pyw "`"$Root\winwishrun.py`"" ([TimeSpan]::Zero)
    if ($bad) { Write-Output $bad; exit 1 }
    Start-Session1Task 'wish-window'
    Start-Sleep -Seconds 8
    Write-Output (Why-NotRun 'wish-window')
    # MainWindowTitle reads empty from session 0 whatever the window says: this
    # query cannot see session 1's windows. The pid is the evidence, and
    # `winvm shot` is how to see the window itself.
    Get-Process pythonw -ErrorAction SilentlyContinue |
      ForEach-Object { "pythonw pid=$($_.Id)" }
    if (Test-Path 'C:\Wish\window.log') { '--- window.log ---'; Get-Content 'C:\Wish\window.log' }
  }

  'stop' {
    Stop-ScheduledTask -TaskName 'wish-window' -ErrorAction SilentlyContinue
    Get-Process pythonw -ErrorAction SilentlyContinue | Stop-Process -Force
    Write-Output 'stopped'
  }

  'status' {
    foreach ($t in 'wish-measure', 'wish-window') {
        if (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue) {
            Write-Output "$t : $(Why-NotRun $t)"
        } else { Write-Output "$t : not registered" }
    }
    Get-Process python, pythonw -ErrorAction SilentlyContinue |
      ForEach-Object { "$($_.ProcessName) pid=$($_.Id)" }
    quser
  }
}
