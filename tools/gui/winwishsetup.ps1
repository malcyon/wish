<#
Install what Wish needs inside the Windows 11 VM, and unpack the repository
there. Runs **inside the guest**; `tools/gui/winwish.py setup` puts it there and
starts it, over `winvm ssh`, in session 0 -- nothing here needs a visible
desktop.

Everything lands under `C:\Wish`. Nothing here touches `C:\Amiga`, `C:\VICE`,
or anything the WinUAE lane owns.

The guest ships no real Python: `python.exe` on the PATH is the Microsoft Store
execution alias, which opens the Store rather than an interpreter. So the
python.org installer is downloaded and run per-user -- the guest has working
internet, measured 2026-09-10.

Written for #474 (Raising the UI font grows the window's minimum width with an ordinary party open, which is the defect #41 removed for the widest one).

  export SSH_ASKPASS_REQUIRE=never
  tools/gui/winwish.py setup      # copies this over and runs it; run it that way
#>
param(
    [string]$Version = '3.12.10',
    [string]$Archive = 'C:\Wish\wish-tree.tar.gz'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

New-Item -ItemType Directory -Force -Path C:\Wish\dl | Out-Null

$exe = "C:\Wish\dl\python-$Version-amd64.exe"
$py  = Join-Path $env:LOCALAPPDATA ('Programs\Python\Python' +
       ($Version -split '\.')[0] + ($Version -split '\.')[1] + '\python.exe')

if (-not (Test-Path $py)) {
    if (-not (Test-Path $exe)) {
        Invoke-WebRequest -UseBasicParsing -OutFile $exe `
          -Uri "https://www.python.org/ftp/python/$Version/python-$Version-amd64.exe"
    }
    Write-Output ("downloaded: " + (Get-Item $exe).Length + " bytes")
    $p = Start-Process -FilePath $exe -Wait -PassThru -ArgumentList @(
        '/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_pip=1',
        'Include_tcltk=0', 'Include_test=0', 'Include_doc=0',
        'AssociateFiles=0', 'Shortcuts=0')
    Write-Output ("installer exit: " + $p.ExitCode)
}
if (-not (Test-Path $py)) { Write-Error "no interpreter at $py"; exit 1 }
& $py -V

$root = 'C:\Wish\wish'
if (Test-Path $Archive) {
    if (Test-Path $root) { Remove-Item -Recurse -Force $root }
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    Push-Location $root
    # Windows 11 ships bsdtar as tar.exe, which reads a .tar.gz directly.
    & tar.exe -xzf $Archive
    Pop-Location
    Write-Output ("extracted into " + $root)
}

$vpy = 'C:\Wish\venv\Scripts\python.exe'
if (-not (Test-Path $vpy)) { & $py -m venv C:\Wish\venv }
& $vpy -m pip install --disable-pip-version-check --quiet --upgrade pip
# pytest is not for running the suite here: `tests/test_windowslayout.py`
# imports it at module scope, and `_ordinary_party` lives in that module.
& $vpy -m pip install --disable-pip-version-check --quiet `
    "PyQt6>=6.6" "pyyaml>=6.0" "pytest>=8.0"
& $vpy -c "import PyQt6.QtCore as c, sys; print(sys.version); print('PyQt', c.PYQT_VERSION_STR, 'Qt', c.QT_VERSION_STR)"
