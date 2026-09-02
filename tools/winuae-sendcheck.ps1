# Provokes #95 (A WinUAE debugger batch can stop half-way through and leave the
# emulator halted): sends many debugger batches through winuae.ps1 and counts
# the ones that died without a verdict and the ones that lost a log line. Runs
# on the Windows guest, against whichever injector it is pointed at, so the
# version before the fix can be watched to fail.
#
#   export SSH_ASKPASS_REQUIRE=never
#   scp tools/winuae-sendcheck.ps1 donald@192.168.123.50:'C:/Amiga/'
#   winvm ssh 'powershell -NoProfile -ExecutionPolicy Bypass -File C:\Amiga\winuae-sendcheck.ps1'
#   winvm ssh 'powershell ... -File C:\Amiga\winuae-sendcheck.ps1 -Injector C:\Amiga\winuae-send-old.ps1'
#
# The fault was one batch in seven, so a handful of batches proves nothing:
# twenty eight-line batches put about four hundred log writes under the
# caller's ten-a-second poll of send.log, which is where the collision was.
# Measured 2026-09-01: 4 of 24 stock batches died and 12 log writes failed in
# 20 batches before the fix; 0 and 0 after.
#
# It needs the lane and an emulator. It takes the lane under -Holder and lets
# it go at the end; if no winuae64 is running it starts one with -log and stops
# it afterwards, through the driver, never by name. -Injector swaps the given
# file in over C:\Amiga\winuae-send.ps1 for the run and puts the original back
# whatever happens, because the driver finds its injector by that path alone.

param(
  [string]$Driver   = 'C:\Amiga\winuae.ps1',
  [string]$Holder   = 'sendcheck',
  [int]$Batches     = 20,
  [int]$Lines       = 8,
  [string]$Injector = ''
)

$Root     = 'C:\Amiga'
$Config   = "$Root\configs\goldbox-a500.uae"
$Live     = "$Root\winuae-send.ps1"
$Backup   = "$Root\winuae-send.sendcheck-backup.ps1"
$Batch    = "$Root\sendcheck-batch.txt"
$Resume   = "$Root\sendcheck-resume.txt"

if (-not (Test-Path $Driver)) { "fail no driver at $Driver"; exit 1 }
if (-not (Test-Path $Config)) { "fail no config at $Config"; exit 1 }
if ($Injector -and -not (Test-Path $Injector)) { "fail no injector at $Injector"; exit 1 }

function Drive { & $Driver @args 2>&1 | ForEach-Object { "$_" } }
function Verdict($lines) { @($lines | Where-Object { $_ -match '^(ok|fail)' })[-1] }

$claim = Drive claim -Holder $Holder
if ($claim -notmatch '^ok') { "fail could not take the lane: $claim"; exit 1 }
# A holder re-asserting its own lane is told so; the lane is then theirs to
# keep, and this check must not let it go on their behalf. An emulator carries
# the holder that started it in the run receipt, so a caller who already has
# one running passes that holder here.
$took = $claim -notmatch 'already yours'
$started = $false
$swapped = $false
$died = 0; $short = 0; $lost = 0
try {
  if (-not (Get-Process -Name winuae64 -ErrorAction SilentlyContinue)) {
    $r = Verdict (Drive start -Holder $Holder -log -f $Config)
    if ($r -notmatch '^ok') { "fail could not start an emulator: $r"; exit 1 }
    $started = $true
    "started an emulator: $r"
    # The debugger wants a console and a running machine, not a loaded game;
    # the fault was first seen 24 seconds into a load, so waiting for the title
    # would only hide the condition it was seen in.
    Start-Sleep -Seconds 8
  }
  if ($Injector) {
    Copy-Item -LiteralPath $Live -Destination $Backup -Force
    Copy-Item -LiteralPath $Injector -Destination $Live -Force
    $swapped = $true
    "injector: $Injector (original backed up to $Backup)"
  } else { "injector: $Live" }

  # Eight `m` lines and no `g`: the emulator stays halted, so one F11 serves
  # every batch and the check is nothing but send after send.
  [IO.File]::WriteAllText($Batch, (("m 40000 1`r`n") * $Lines))
  [IO.File]::WriteAllText($Resume, "g`r`n")
  $k = Verdict (Drive key 7A -Holder $Holder)
  if ($k -notmatch '^ok') { "fail F11 was not pressed: $k"; exit 1 }

  for ($i = 1; $i -le $Batches; $i++) {
    $out = @(Drive send "-File $Batch" -Holder $Holder)
    $v = Verdict $out
    $sent = @($out | Where-Object { $_ -match '^\d\d:\d\d:\d\d\.\d\d\d  line: ' }).Count
    $note = @($out | Where-Object { $_ -match 'log lines could not be written' })
    $what = 'ok'
    if ($v -match 'ended without writing a verdict') { $died++; $what = 'DIED' }
    elseif ($v -notmatch '^ok') { $died++; $what = 'FAILED' }
    if ($sent -lt $Lines) { $short++; if ($what -eq 'ok') { $what = 'short' } }
    if ($note) { $lost++ }
    "batch $i/$Batches $what lines_logged=$sent/$Lines $v"
  }
} finally {
  if ($swapped) {
    Copy-Item -LiteralPath $Backup -Destination $Live -Force
    Remove-Item -LiteralPath $Backup -Force -ErrorAction SilentlyContinue
    "injector restored"
  }
  Drive send "-File $Resume" -Holder $Holder | Where-Object { $_ -match '^(ok|fail)' } | ForEach-Object { "resume: $_" }
  Remove-Item -LiteralPath $Batch, $Resume -Force -ErrorAction SilentlyContinue
  if ($started) { "stop: " + (Verdict (Drive stop -Holder $Holder)) }
  if ($took) { "release: " + (Verdict (Drive release -Holder $Holder)) } else { "lane left with $Holder" }
}

"sendcheck: $died of $Batches batches died or failed, $short of $Batches logged fewer than $Lines lines, $lost reported a lost log line"
if ($died -eq 0 -and $short -eq 0 -and $lost -eq 0) { "PASS"; exit 0 } else { "FAIL"; exit 1 }
