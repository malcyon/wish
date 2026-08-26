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

function Say($m) { "$((Get-Date).ToString('HH:mm:ss.fff'))  $m" | Add-Content -Path $Log }
function LastErr { [Runtime.InteropServices.Marshal]::GetLastWin32Error() }
# Every path out ends with this line, and winuae.ps1 waits for it. Without a
# marker the caller cannot tell "still working" from "died before it started".
# The token is the caller's own, so a log left behind by an earlier run cannot
# be mistaken for this one's verdict.
function Finish([int]$code) { Say "--- exit $code token=$Token"; exit $code }

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
