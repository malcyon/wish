# Testing the release packages by hand

**Status: not yet run.** No tag has been pushed, so nothing below has been done
on a real release page.

This is for you, at a keyboard, before the first `v*` tag is cut — or straight
after it, against the artefacts the tag produced. It covers what
[`106-releases.md`](106-releases.md) plans and what the README documents, from
the other end: does the *built package* work on a machine that is not this one.

The README already documents installing from source, VICE's binary monitor, and
where wish keeps its files. This does not repeat that. Where a step needs it,
it points at the README section by name.

---

## Read this first — three things that are already known

**1. The frozen builds ship one executable, not two.** `wish.spec` builds a
single `EXE(name="wish")` from `packaging/wish_main.py`. There is no `wish-cli`
in the `.tar.gz` or the `.zip`. So the CLI round trip can only be tested from
the wheel, and the frozen builds are tested through the window. That is
consistent with the README ("unpack and run `wish`") but worth knowing before
you go looking for a binary that is not there.

**2. `wish.exe --version` will print nothing on Windows.** The spec sets
`console=False`, so the Windows build has no console and
`packaging/wish_main.py` points `sys.stdout` at `os.devnull` to stop argparse
dying on it. Exit code 0, no output. That is the *fix* working, not a failure.
Get the version from **Help > About wish** instead. Every message the program
writes to stdout or stderr — including "no `POOL*.D64` game disks found" — is
invisible on Windows for the same reason.

**3. The Commodore 64 Ultimate backend cannot be tested.** Nobody on the
project has the hardware. It is written from vendor documentation and exercised
only against a stub. Leave `POR_ULTIMATE` unset and it is never probed, so it
costs nothing; there are no steps for it below because there is no honest way
to write them.

Also: `release.yml` does not run the test suite. A red `test.yml` does not block
a tag, and the two known failures in `106-releases.md` §Verification are not
about packaging.

---

## 1. Before you start

| | Linux | Windows |
|---|---|---|
| a save disk | a **copy** of one `PORSAVE*.D64` | the same copy, transferred over |
| a game disk | `POOLBOOT.D64` and `POOL1.D64`–`POOL8.D64` | the same set, copied over |
| VICE | already installed (Flatpak `net.sf.VICE`) | **not installed** — step W1 |
| Python | 3.12+, for the wheel test only | not needed at all |
| the artefacts | all four, plus `SHA256SUMS` | all four, plus `SHA256SUMS` |

The release page carries four files plus checksums:

| file | what it is |
|---|---|
| `por_tools-<version>-py3-none-any.whl` | the wheel |
| `por_tools-<version>.tar.gz` | the sdist |
| `wish-<version>-linux-x86_64.tar.gz` | the frozen Linux build |
| `wish-<version>-windows-x86_64.zip` | the frozen Windows build |
| `SHA256SUMS` | one line per file above |

**Two of them are `.tar.gz`.** One is the sdist, one is the frozen build. Read
the name, not the extension.

**Nothing in this walkthrough may touch your real save disks.** Step L1 makes a
working copy and everything afterwards operates on that copy or on files
derived from it. The one place it matters most is the editor: unlike the CLI,
the editor's **Save writes back to the file you opened** (it takes a backup
first — `editor/files.py::save_disk` — but it does write). Work on the copy.

---

## 2. Checksums, both platforms

Do this before unpacking anything.

**Linux**

```sh
cd ~/Downloads/wish-release
sha256sum --ignore-missing -c SHA256SUMS
```

Expect one `OK` per file you downloaded. `--ignore-missing` is there so a
partial download does not bury the real answer under "No such file".

**Windows** — PowerShell, in the folder holding the downloads:

```powershell
Get-Content SHA256SUMS | ForEach-Object {
  $p = $_ -split '\s+', 2
  $name = $p[1].TrimStart('*')
  if (Test-Path $name) {
    $h = (Get-FileHash $name -Algorithm SHA256).Hash
    "{0}  {1}" -f $(if ($h -eq $p[0].ToUpper()) { 'OK  ' } else { 'FAIL' }), $name
  }
}
```

Expect `OK` beside each file present. Anything else: stop, re-download, and if
it fails again the release page is wrong, not your disk.

---

## 3. Linux — the frozen `.tar.gz`

**L1.** Make the working copy. Everything downstream uses it.

```sh
mkdir -p ~/wish-test && cd ~/wish-test
cp "/home/donald/c64/Pool of Radiance Disks/PORSAVE11.D64" ./TESTSAVE.D64
```

**L2.** Unpack the frozen build.

```sh
tar xzf ~/Downloads/wish-release/wish-<version>-linux-x86_64.tar.gz
cd wish-<version>-linux-x86_64
ls wish
```

*Expect:* an executable `wish` beside a large pile of shared libraries (~156 MB
unpacked, three quarters of it Qt). *If `wish` is not there:* the archive was
built wrong — check what `tar tzf` lists at the top level.

**L3.** Version.

```sh
./wish --version
```

*Expect:* `wish <version>`, exactly the tag with the `v` stripped. `--version`
exits inside argparse before Qt is imported, so this works with no display.
*If it says `0.0.0+unknown` or a `.dev` version:* the build did not see the tag
— `wish/_version.py` was not written by the editable install in `release.yml`,
and the artefact is mislabelled. That is a release blocker.

There is **no `wish-cli` here** — see the note at the top. Confirm that by
looking, so you are not surprised later:

```sh
ls | grep -i cli    # expect: nothing
```

**L4.** Start the window on a save disk.

```sh
./wish --tab editor ~/wish-test/TESTSAVE.D64
```

*Expect:* the window opens on the Character Editor tab with the party loaded, a
roster down the left, and the title bar naming the file. On stderr you may see
"no `POOL*.D64` game disks found" if the disks are not where `automap/paths.py`
looks — harmless for the editor, and step L7 fixes it.

*If it does not start at all,* run it from a terminal and keep the traceback:
a frozen Qt build failing on a distribution other than Ubuntu usually names a
missing system library (`libEGL`, `libxkbcommon-x11`, `libGL`).

**L5.** Check the version the window reports: **Help > About wish**. It must
match step L3. This is the only route to the version on Windows, so confirm it
agrees here where you can check both.

**L6.** The round trip, through the window.

1. Pick a character. Change **gold** to `4321` — visible on the game's own
   character sheet, easy to spot, and nothing else depends on it.
2. **File > Save As…**, and give it a *new* name: `~/wish-test/EDITED.D64`.
   **Never plain Save on the first pass** — Save writes back to `TESTSAVE.D64`.
3. *Expect:* the status bar says `wrote EDITED.D64`.
4. **File > Open…** `EDITED.D64` and confirm gold reads `4321`.
5. Confirm the original is untouched:
   ```sh
   cmp "/home/donald/c64/Pool of Radiance Disks/PORSAVE11.D64" ~/wish-test/TESTSAVE.D64
   ```
   *Expect:* no output. *If it differs:* something wrote to a file it should not
   have, and that is the most serious failure in this document.

**L7.** The disk the game can read. This is the step that actually proves the
round trip.

1. Launch the game the usual way — `POR_DEBUG=1 ~/.local/bin/pool-of-radiance`
   (leave `POR_DEBUG=1` on; step 6 needs the monitor). Answer **Y** to the
   fastloader prompt.
2. When the game asks for a save disk, attach `~/wish-test/EDITED.D64` to
   drive 8.
3. Load the saved game and open that character's sheet.
4. *Expect:* gold reads 4321 and the party is otherwise exactly as you left it.
   *If the game rejects the disk or the party is wrong,* keep `EDITED.D64` — a
   broken disk is the evidence.

---

## 4. Linux — the wheel

This is the path a Python user takes, and it exercises code the frozen build
never runs: the entry points from installed metadata, `tools/` as an installed
package, and the version from installed metadata rather than `wish/_version.py`.

**L8.** A venv with nothing in it.

```sh
cd ~/wish-test
python3 -m venv .venv-release
source .venv-release/bin/activate
pip install "$HOME/Downloads/wish-release/por_tools-<version>-py3-none-any.whl[gui,automap]"
```

*Expect:* PyQt6 and PyYAML pulled in, no build step, no compiler.
*If pip refuses the extras syntax,* quote the whole argument — the brackets are
the shell's otherwise.

**L9.** Both commands report the version.

```sh
wish --version        # wish <version>
wish-cli --version    # wish-cli <version>
```

Both must print the same number as L3. `wish-cli` is `tools.wish:main`, and
`tools` only ships because `pyproject.toml` lists it in the wheel's packages —
if `wish-cli` dies in `ModuleNotFoundError: tools`, that list regressed.

**L10.** The CLI round trip.

```sh
cd ~/wish-test
wish-cli --export TESTSAVE.D64 --output party.yaml
sed -i 's/^\( *gold: \).*/\14321/' party.yaml      # or edit it by hand
wish-cli --import party.yaml --dry-run
wish-cli --import party.yaml --output CLI-EDITED.D64
```

*Expect:* the dry run lists the gold change and writes nothing; the import
writes `CLI-EDITED.D64`. *Expect also:* `wish-cli --import party.yaml --output
TESTSAVE.D64` is **refused** — "--output must differ from the original save".
Try it; a release where that guard is gone is a release that eats saves.

**L11.** Losslessness. Export and re-import with no edit at all, and the disk
must come back byte for byte:

```sh
wish-cli --export TESTSAVE.D64 --output plain.yaml
wish-cli --import plain.yaml --output ROUNDTRIP.D64
cmp TESTSAVE.D64 ROUNDTRIP.D64      # expect: no output
```

*If they differ,* stop. Everything else in the tool depends on this property.

**L12.** Boot `CLI-EDITED.D64` in the game as in L7, and confirm gold. Then
`deactivate` the venv.

---

## 5. Windows, from nothing

Assume a machine with no Python, no VICE, and no game files. Copy the game
disks, `TESTSAVE.D64`, and all five downloads over first.

Put the game disks somewhere `automap/paths.py` looks — the simplest is
`%USERPROFILE%\Documents\Pool of Radiance Disks\`. Anywhere else and you will
need `POR_DISKS`.

### W1. Install VICE

1. Download the Windows GTK3 build from
   <https://vice-emu.sourceforge.io/> — the "windows" download, a **zip**, not
   an installer. *(Unverified: VICE has shipped Windows builds as zips through
   3.7–3.9; check the page rather than trusting this line.)*
2. Right-click the zip > **Properties** > tick **Unblock** > OK. Do this before
   extracting: Windows stamps a downloaded zip with the mark of the web and
   File Explorer copies that stamp onto every file it extracts.
3. Extract to a **short path** — `C:\vice`. Deep Qt/VICE paths under a nested
   Downloads folder can run into the 260-character limit.
4. Run `C:\vice\bin\x64sc.exe` once, confirm you get a C64 screen, and quit.

### W2. Enable the binary monitor

The README's *Configuring VICE* section is the reference; the Windows specifics
are these.

1. **Quit VICE completely** before you touch the file. VICE rewrites its
   settings on exit and silently discards anything you changed while it was
   running. This is the single most common way to lose ten minutes here.
2. Open `%APPDATA%\vice\vice.ini` in Notepad. Paste the path into the Explorer
   address bar — `%APPDATA%` expands.
   *If the file does not exist:* VICE has not written one yet. Start
   `x64sc.exe`, use its own **Settings > Save settings** (wording varies by
   version — *unverified*), quit, and look again.
3. Under the `[C64SC]` section — create it if it is absent, as the last line of
   the file — add:
   ```ini
   BinaryMonitor=1
   BinaryMonitorAddress="127.0.0.1:6502"
   ```
4. Save, then start `x64sc.exe`.

**The alternative, which avoids the file entirely** and is worth trying first if
the ini fights you — a shortcut, or PowerShell:

```powershell
C:\vice\bin\x64sc.exe -binarymonitor -binarymonitoraddress 127.0.0.1:6502
```

*Expect, either way:* nothing visible. VICE does not announce the monitor. The
proof is step 6 attaching. *Possible on first run:* a Windows Defender Firewall
prompt when VICE opens the listening socket. It is bound to `127.0.0.1`, so
loopback should not need a rule — **unverified**; if you get the prompt, note
which choice you made, because it changes what step 6 means.

*If the setting does not stick:* you edited it while VICE was running. Quit,
edit, start. In that order.

**No Flatpak, so no `--share=network`.** That whole problem is Linux-only.

### W3. Start the game

Attach `POOLBOOT.D64` to drive 8 and autostart it. Answer the fastloader prompt
the way you do on Linux (**Y** if this VICE has JiffyDOS; a stock Windows VICE
will not, in which case **N**). Get to the point where a party is loaded and
standing somewhere in a map.

### W4. Unpack wish

1. Right-click `wish-<version>-windows-x86_64.zip` > **Properties** >
   **Unblock** > OK. Or, in PowerShell:
   ```powershell
   Unblock-File .\wish-<version>-windows-x86_64.zip
   ```
   Skipping this is what makes step W5's warning appear on *every* file rather
   than once.
2. Extract to a short path: `C:\wish`. Same 260-character reason as VICE, and
   the Qt tree inside is deeper.
3. *Expect:* `C:\wish\wish-<version>-windows-x86_64\wish.exe` and several
   hundred files beside it.
4. First extraction may be slow — Defender scans ~156 MB of fresh binaries.
   Minutes, not seconds, is normal.

### W5. Run it, past the warning

Double-click `wish.exe`.

*Expect:* **"Windows protected your PC"** — SmartScreen, because the executable
is unsigned and always will be; a certificate costs money and SmartScreen warns
on new signatures anyway. Click **More info**, then **Run anyway**.

*Expect then:* the wish window. *If instead the file vanishes,* Defender
quarantined it as a PyInstaller false positive — check Windows Security >
Protection history. **Unverified**: this happens to some PyInstaller builds and
not others, and nobody has run this one on Windows.

**Version:** `wish.exe --version` prints nothing here (see the note at the top).
Use **Help > About wish**. If you want the exit code:

```powershell
(Start-Process -FilePath C:\wish\wish-<version>-windows-x86_64\wish.exe `
  -ArgumentList '--version' -Wait -PassThru).ExitCode
```

*Expect:* `0`, and no printed version. *Unverified* — this is the exact path
that used to die in `AttributeError: 'NoneType' has no attribute 'write'`, so
if you get a PyInstaller traceback box instead, that is a real regression in
`packaging/wish_main.py` and worth a screenshot.

### W6. The round trip on Windows

Same as L6, with `TESTSAVE.D64` copied onto this machine:

1. **File > Open…**, pick `TESTSAVE.D64`.
2. Change gold to `1234` — a different number from the Linux run, so you can
   tell the two disks apart later.
3. **File > Save As…** > `EDITED-WIN.D64`. Not plain Save.
4. Reopen `EDITED-WIN.D64` and confirm.
5. In VICE, attach `EDITED-WIN.D64` and load the saved game. Gold reads 1234.

### W7. Where Windows keeps wish's files

The README's *Wish Config Files* table is the reference. On this machine you
will want to find them, and probably to clear them between runs:

| what | path | when it appears |
|---|---|---|
| settings | `%APPDATA%\wish\automap.json` | when the window closes |
| notes, explored squares | `%LOCALAPPDATA%\wish\maps\<AREA>.json` | when a note is added, or the window closes |
| debug log | `%APPDATA%\wish\logs\wish-*.log` | only while the log is on |
| save backups, when the disk's folder is read-only | `%LOCALAPPDATA%\wish\backups\` | on a save that changed something |

To test a genuinely first run, close wish and delete `%APPDATA%\wish` and
`%LOCALAPPDATA%\wish`. Paste those into the Explorer address bar; they expand.

*Expect:* a frozen build writes to the user directories and **never beside the
executable**. Check `C:\wish\wish-<version>-windows-x86_64\` after a session —
no `.json`, no `.log`. A frozen build that writes beside itself breaks the
moment somebody unpacks it under `Program Files`.

---

## 6. The automapper, both platforms

This is the feature most likely to break in a frozen build: it needs a socket
and a writable config directory, and neither is exercised by the editor.

Do it once on each platform, with the game running from step L7 / W3.

**M1.** With the game running and the monitor enabled, start wish on the map:

* Linux, frozen: `./wish --tab map`
* Linux, wheel: `wish --tab map`
* Windows: `wish.exe`, then **View > Automapper** (`Ctrl+1`)

**M2.** *Expect:* the status bar says `VICE: connected` within a second or two.

*If it says `waiting for a game — VICE: start VICE with its binary monitor
enabled …`:* the monitor is not listening. Linux: `ss -tln | grep 6502`.
Windows: `Test-NetConnection 127.0.0.1 -Port 6502` (*unverified spelling of the
result on a closed port*, but a `TcpTestSucceeded : False` is unambiguous).

*If it says something about the monitor being busy,* in red: something else
already holds it. VICE serves exactly one binary-monitor connection and ignores
the second. Close the other client.

**M3.** Walk the party three or four squares in the game.

*Expect:* the party marker moves on the map in step with the game, the squares
you cross fill in, and the area is named in the panel. Latency of a couple of
polls (200 ms each) is normal.

*If the map is empty but the connection is up:* no `POOL*.D64` were found and
there is no `GEO` to draw. Point `--disks` or `POR_DISKS` at them. On Windows
the warning that says so is invisible, so this is the symptom to recognise.

**M4.** Press **N** to put a note on the party's square. Type something into
it. Press **R** to toggle fog of war and back.

*Expect:* a marker in the corner of the square, and its text on hover.

**M5.** Close the window entirely. Reopen it and return to the map tab.

*Expect:* the note is still there, the explored squares are still filled, and
the window is the size you left it. Notes are written on every edit *and* on
shutdown, so both paths are covered by this one check.

*If they are gone:* the config directory is not writable, or the frozen build
resolved it somewhere unexpected. Check for the file — `~/.local/share/wish/maps/`
on Linux, `%LOCALAPPDATA%\wish\maps\` on Windows.

**M6.** Close and reopen wish with the game *not* running.

*Expect:* the window opens, the map tab says it is waiting, nothing crashes and
the editor tab works normally. A tool that requires the emulator to start is a
tool that is useless half the time.

---

## 7. Results

Tick as you go. `n/a` where a row does not apply to that platform.

| # | check | Linux | Windows |
|---|---|---|---|
| 2 | `SHA256SUMS` verifies | ☐ | ☐ |
| L2 | frozen archive unpacks, `wish` present | ☐ | ☐ (W4) |
| L3 | `wish --version` prints the tag | ☐ | n/a — no console |
| L5 | Help > About shows the same version | ☐ | ☐ (W5) |
| L4 | window opens on a save disk | ☐ | ☐ (W6) |
| L6 | edit, Save As, reopen — value stuck | ☐ | ☐ (W6) |
| L6 | the original save disk is byte-identical afterwards | ☐ | ☐ |
| L7 | the game loads the edited disk and shows the edit | ☐ | ☐ (W6) |
| L8 | wheel installs into a clean venv | ☐ | n/a |
| L9 | `wish` and `wish-cli` both report the version | ☐ | n/a |
| L10 | CLI export / dry-run / import round trip | ☐ | n/a |
| L10 | `--output` over the original is refused | ☐ | n/a |
| L11 | unedited round trip is byte-identical | ☐ | n/a |
| W1 | VICE installs and starts | n/a | ☐ |
| W2 | binary monitor enabled and survives a restart | n/a | ☐ |
| W5 | SmartScreen warning cleared, program runs | n/a | ☐ |
| W7 | settings and notes land in the user directories, not beside the exe | ☐ | ☐ |
| M2 | automapper attaches | ☐ | ☐ |
| M3 | the map tracks the party | ☐ | ☐ |
| M5 | notes and explored squares survive a restart | ☐ | ☐ |
| M6 | starts cleanly with no emulator running | ☐ | ☐ |
| 8 | debug log writes, and names no paths | ☐ | ☐ |

---

## 8. When a step fails

Capture these four things before you change anything. A failure you cannot
reproduce is a failure you cannot fix.

**1. The version.** `wish --version`, or Help > About on Windows. Without it
nobody knows which build you had.

**2. The debug log.** Off at every start, deliberately — it is not remembered
between runs.

* **View > Debug log** to turn it on. A dialog names the file.
* Reproduce the failure.
* **View > Show log** opens it in whatever the desktop uses for text.

| | path |
|---|---|
| Linux | `~/.config/wish/logs/wish-YYYYMMDD-HHMMSS.log` |
| Windows | `%APPDATA%\wish\logs\wish-YYYYMMDD-HHMMSS.log` |

One file per session, last five kept. It records versions, which backend
attached, the tab in view, poll timings, and tracebacks — and deliberately not
file paths, character names or any bytes from a save
([`104-debug-log.md`](104-debug-log.md)). It is safe to attach to anything.

*If the menu item turns itself back off,* the settings directory is not
writable. That is itself the bug.

**3. The terminal, on Linux.** Start the frozen build from a shell, not from a
file manager. A crash before Qt is up prints there and nowhere else. On
Windows there is no console, so the equivalent evidence is the PyInstaller
traceback box — screenshot it whole, including the scrollback.

**4. The files, kept.** A save disk that fails to round-trip *is* the bug
report. Keep `EDITED.D64` / `EDITED-WIN.D64` and the `party.yaml` that produced
it. They contain your own party and nothing of the game's, so they are yours to
send.

For the automapper specifically, add: which backend the status bar named,
whether `6502` was listening, and whether anything else was attached to the
monitor at the time.

---

## Marked unverified

Nobody has run any of this. These are the specific claims above that are
expectation rather than observation, and worth correcting in this file once you
know:

| where | claim |
|---|---|
| W1 | VICE ships its Windows build as a zip rather than an installer |
| W2 | `%APPDATA%\vice\vice.ini` does not exist until VICE has run and exited once |
| W2 | VICE's own **Settings > Save settings** wording, and that it creates the file |
| W2 | whether Windows Defender Firewall prompts when VICE binds `127.0.0.1:6502` |
| W5 | that SmartScreen shows "Windows protected your PC" and not something else |
| W5 | whether Defender quarantines this PyInstaller build as a false positive |
| W5 | `Start-Process -Wait -PassThru … .ExitCode` returning 0 with no output |
| W4 | that the 260-character path limit is actually reachable here |
| M2 | `Test-NetConnection`'s exact output for a closed port |
| — | the Windows zip running on a machine with no Python at all (`106-releases.md` records this as unverified too) |
| — | the Linux frozen build on any distribution other than the one it was built on |
| — | the Commodore 64 Ultimate backend, which cannot be tested at all |
