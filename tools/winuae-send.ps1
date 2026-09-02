# Type lines into WinUAE's debugger console, and read the console back.
#
# Runs on the Windows guest, in the same session as WinUAE: consoles are
# per-session, so a process in session 0 -- which is where `winvm ssh` lands --
# can never attach to one owned by session 1. `winuae.ps1 send` starts it there.
#
# The guest's execution policy is Undefined in every scope, which on Windows 11
# client means Restricted, so -ExecutionPolicy Bypass is not decoration: without
# it these fail with "running scripts is disabled on this system".
#
#   $ps = 'powershell -NoProfile -ExecutionPolicy Bypass -File C:\Amiga\winuae-send.ps1'
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\Amiga\winuae-send.ps1 `
#       -TargetPid 1234 -File C:\Amiga\cmds.txt
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\Amiga\winuae-send.ps1 `
#       -TargetPid 1234 -DumpOnly
#
# The write half is docs/143 §7 option 1: AttachConsole, then WriteConsoleInput
# key events into the input buffer. It needs no window focus.
#
# The read half is the same trick backwards: ReadConsoleOutputCharacter over
# the attached screen buffer gives the debugger's own output as text, so a
# reply never has to be scraped off a screenshot.
#
# NOTHING IN HERE MAY LET AN ERROR REACH POWERSHELL'S HOST. Windows PowerShell's
# console host opens its CONOUT$ handle once, at startup, and keeps it; the
# FreeConsole/AttachConsole below leaves that handle pointing at a console that
# no longer exists. The host does not notice until it has to render something
# through it -- an error, a warning, a progress bar -- and then it throws `The
# Win32 internal error "The handle is invalid" 0x6 occurred while getting
# console output buffer information`, the pipeline stops, and the batch is left
# half-typed with the emulator halted (#95). Measured: 2 of 2 probes died on
# their first Write-Warning after the swap, and 4 of 24 stock batches died the
# same way. So errors are made terminating, warnings and progress are silenced,
# a trap turns anything that still escapes into a logged verdict, and the log
# is written through a handle that shares the file with the caller polling it,
# because that poll was the error: Add-Content against a Get-Content reader
# raised `Stream was not readable` 12 times in 20 batches.
param(
  [int]$TargetPid,
  [string]$File,
  [switch]$DumpOnly,
  [string]$Out = 'C:\Amiga\console.txt',
  [int]$Tail = 120,
  [string]$Log = 'C:\Amiga\send.log',
  [string]$Token = ''
)

Add-Type @"
using System;
using System.Runtime.InteropServices;

[StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
public struct KEY_EVENT_RECORD {
  [MarshalAs(UnmanagedType.Bool)] public bool bKeyDown;
  public ushort wRepeatCount;
  public ushort wVirtualKeyCode;
  public ushort wVirtualScanCode;
  public char   UnicodeChar;
  public uint   dwControlKeyState;
}

[StructLayout(LayoutKind.Explicit, CharSet = CharSet.Unicode)]
public struct INPUT_RECORD {
  [FieldOffset(0)] public ushort EventType;
  [FieldOffset(4)] public KEY_EVENT_RECORD KeyEvent;
}

[StructLayout(LayoutKind.Sequential)]
public struct COORD { public short X; public short Y; }

[StructLayout(LayoutKind.Sequential)]
public struct SMALL_RECT { public short Left, Top, Right, Bottom; }

[StructLayout(LayoutKind.Sequential)]
public struct CONSOLE_SCREEN_BUFFER_INFO {
  public COORD dwSize;
  public COORD dwCursorPosition;
  public ushort wAttributes;
  public SMALL_RECT srWindow;
  public COORD dwMaximumWindowSize;
}

public static class Con {
  public const uint GENERIC_READ = 0x80000000, GENERIC_WRITE = 0x40000000;
  public const uint FILE_SHARE_READ = 1, FILE_SHARE_WRITE = 2;
  public const uint OPEN_EXISTING = 3;

  [DllImport("kernel32.dll", SetLastError=true)] public static extern bool AttachConsole(uint pid);
  [DllImport("kernel32.dll", SetLastError=true)] public static extern bool FreeConsole();
  [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
  public static extern IntPtr CreateFileW(string name, uint access, uint share,
      IntPtr sa, uint disp, uint flags, IntPtr tmpl);
  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern bool WriteConsoleInputW(IntPtr h, INPUT_RECORD[] recs, uint n, out uint written);
  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern bool GetNumberOfConsoleInputEvents(IntPtr h, out uint n);
  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern bool GetConsoleScreenBufferInfo(IntPtr h, out CONSOLE_SCREEN_BUFFER_INFO info);
  [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
  public static extern bool ReadConsoleOutputCharacterW(IntPtr h, [Out] char[] buf,
      uint len, COORD at, out uint read);
  [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr h);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern short VkKeyScanW(char c);
}
"@

# See the header: an error record that reaches the host kills the process.
$ErrorActionPreference   = 'Stop'
$WarningPreference       = 'SilentlyContinue'
$ProgressPreference      = 'SilentlyContinue'
$VerbosePreference       = 'SilentlyContinue'
$DebugPreference         = 'SilentlyContinue'
$InformationPreference   = 'SilentlyContinue'

# The caller reads this file ten times a second while it is being written.
# Add-Content does not share it: against that reader it failed 574 of 600
# appends in a tight loop and a dozen times across 20 real batches. A stream
# opened with FileShare.ReadWrite|Delete failed 0 of 600 against the same
# reader, whichever way the reader opened the file. The retry is for a share
# mode the reader might one day get wrong; the count is so a lost line is
# reported rather than silently missing from the caller's account.
$script:lost = 0
function Say($m) {
  $text = "$((Get-Date).ToString('HH:mm:ss.fff'))  $m`r`n"
  for ($try = 0; $try -lt 5; $try++) {
    try {
      $fs = New-Object IO.FileStream($Log, [IO.FileMode]::Append, [IO.FileAccess]::Write,
              ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
      try {
        $b = [Text.Encoding]::UTF8.GetBytes($text)
        $fs.Write($b, 0, $b.Length)
      } finally { $fs.Close() }
      return
    } catch { Start-Sleep -Milliseconds 20 }
  }
  $script:lost++
}
function LastErr { [Runtime.InteropServices.Marshal]::GetLastWin32Error() }
# Every path out ends with this line, and winuae.ps1 waits for it. Without a
# marker the caller cannot tell "still working" from "died before it started".
# The token is the caller's own, so a log left behind by an earlier run cannot
# be mistaken for this one's verdict.
function Finish([int]$code) {
  if ($script:lost -gt 0) { Say "--- $script:lost log lines could not be written" }
  Say "--- exit $code token=$Token"; exit $code
}
# Anything that still escapes is written here, by us, and becomes exit 7 --
# never handed to the host to print. `exit` inside Finish ends the script from
# inside the trap, so the trap never falls through to the host's own error
# output, which is the call that dies.
trap {
  Say "died: $($_.Exception.GetType().FullName): $($_.Exception.Message) (line $($_.InvocationInfo.ScriptLineNumber))"
  Finish 7
}

$status = 0
Say "--- pid=$TargetPid file=$File dumponly=$DumpOnly token=$Token"

# Check the arguments before touching the console, so a malformed call fails in
# milliseconds. Unguarded, `Get-Content -Path ''` behaves differently depending
# on where it runs, and neither way is survivable: in an ordinary console it is
# a NON-terminating error, so the foreach body never runs and the caller is
# told `ok sent` for a call that sent nothing; in session 1, attached to
# WinUAE's console, it killed the process where it stood -- send.log stopped at
# `CONIN opened`, the task went back to Ready with LastTaskResult 1, and no
# `--- exit` line was ever written. Both were measured.
if ($TargetPid -le 0) { Say "no -TargetPid"; Finish 6 }
if (-not $DumpOnly -and -not $File) { Say "neither -File nor -DumpOnly"; Finish 6 }
if (-not $DumpOnly -and -not (Test-Path -LiteralPath $File)) {
  Say "-File '$File' does not exist"; Finish 6
}

# A scheduled task's powershell.exe gets its own console; AttachConsole refuses
# while one is held.
[Con]::FreeConsole() | Out-Null
if (-not [Con]::AttachConsole([uint32]$TargetPid)) {
  Say "AttachConsole failed, GetLastError=$(LastErr)"   # 5 = the target has no console
  Finish 2
}
Say "attached"

$open = {
  param($name, $access)
  [Con]::CreateFileW($name, $access,
    ([Con]::FILE_SHARE_READ -bor [Con]::FILE_SHARE_WRITE),
    [IntPtr]::Zero, [Con]::OPEN_EXISTING, 0, [IntPtr]::Zero)
}

if (-not $DumpOnly) {
  $hin = & $open 'CONIN$' ([Con]::GENERIC_READ -bor [Con]::GENERIC_WRITE)
  if ($hin -eq ([IntPtr](-1)) -or $hin -eq [IntPtr]::Zero) {
    Say "CONIN open failed, GetLastError=$(LastErr)"; Finish 3
  }
  Say "CONIN opened"

  function Send-Char([char]$c) {
    $vk = [Con]::VkKeyScanW($c) -band 0xFF
    $recs = New-Object 'INPUT_RECORD[]' 2
    foreach ($i in 0,1) {
      $k = New-Object KEY_EVENT_RECORD
      $k.bKeyDown = ($i -eq 0)
      $k.wRepeatCount = 1
      $k.wVirtualKeyCode = [uint16]$vk
      $k.wVirtualScanCode = 0
      $k.UnicodeChar = $c
      $k.dwControlKeyState = 0
      # Build the whole struct first. `$recs[$i].EventType = 1` sets a field on
      # a boxed COPY of the array element and silently throws it away, which
      # posts two zeroed records the console drops without a word.
      $r = New-Object INPUT_RECORD
      $r.EventType = 1                 # KEY_EVENT
      $r.KeyEvent = $k
      $recs[$i] = $r
    }
    $written = 0
    if (-not [Con]::WriteConsoleInputW($hin, $recs, 2, [ref]$written)) {
      Say "WriteConsoleInput failed, GetLastError=$(LastErr)"; return $false
    }
    return $true
  }

  foreach ($line in (Get-Content -Path $File)) {
    Say "line: $line"
    foreach ($c in $line.ToCharArray()) { if (-not (Send-Char $c)) { $status = 4; break } }
    if ($status -ne 0) { break }
    Send-Char ([char]13) | Out-Null    # VK_RETURN carries CR as its UnicodeChar
    Start-Sleep -Milliseconds 700
    $n = 0; [Con]::GetNumberOfConsoleInputEvents($hin, [ref]$n) | Out-Null
    Say "  unconsumed input events: $n"
  }
  [Con]::CloseHandle($hin) | Out-Null
}

# Read the console screen buffer back as text.
$hout = & $open 'CONOUT$' ([Con]::GENERIC_READ -bor [Con]::GENERIC_WRITE)
if ($hout -eq ([IntPtr](-1)) -or $hout -eq [IntPtr]::Zero) {
  Say "CONOUT open failed, GetLastError=$(LastErr)"; Finish 5
}
$info = New-Object CONSOLE_SCREEN_BUFFER_INFO
if ([Con]::GetConsoleScreenBufferInfo($hout, [ref]$info)) {
  # The buffer is 5000 lines and WinUAE fills a lot of it at startup. Read the
  # tail only: the whole thing is 600,000 characters and marshalling that on
  # every command would dominate the round trip.
  $w = [int]$info.dwSize.X
  $cy = [int]$info.dwCursorPosition.Y
  $top = [Math]::Max(0, $cy - $Tail + 1)
  $rows = $cy - $top + 1
  Say "buffer ${w}x$($info.dwSize.Y) cursor $($info.dwCursorPosition.X),$cy reading rows $top..$cy"
  $n = [uint32]($w * $rows)
  $buf = New-Object 'char[]' $n
  $at = New-Object COORD; $at.X = 0; $at.Y = [int16]$top
  $read = 0
  if ([Con]::ReadConsoleOutputCharacterW($hout, $buf, $n, $at, [ref]$read)) {
    $s = New-Object string (,$buf)
    $sb = New-Object System.Text.StringBuilder
    for ($i = 0; $i -lt [int]$read; $i += $w) {
      [void]$sb.AppendLine($s.Substring($i, [Math]::Min($w, [int]$read - $i)).TrimEnd())
    }
    [IO.File]::WriteAllText($Out, $sb.ToString())
    Say "dumped $read chars to $Out"
  } else { Say "ReadConsoleOutputCharacter failed, GetLastError=$(LastErr)" }
} else { Say "GetConsoleScreenBufferInfo failed, GetLastError=$(LastErr)" }
[Con]::CloseHandle($hout) | Out-Null

[Con]::FreeConsole() | Out-Null
Finish $status
