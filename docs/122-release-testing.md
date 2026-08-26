# Testing the release packages by hand

**Status: the Linux half was run on 2026-08-22, and the first Windows run
followed the same day.** No tag has been pushed, so none of it has been done
against a real release page — the Linux run used artefacts built locally by
`§0b`, at version `0.0.1.dev165+g24a77e835.d20260822`. `§7` says which rows each
run covered, and each Linux section carries a note saying what was actually
watched. Anything without such a note is still expectation.

**The Windows run answered the console questions and found four real defects.**
`wish.exe` from Explorer opens the window with no console anywhere behind it,
and `wish --help` and `wish --version` typed into a Command Prompt print
normally — the console-borrowing path in note 2 works. The defects are in `§7`.

This is for you, at a keyboard, before the first `v*` tag is cut — or straight
after it, against the artefacts the tag produced. It covers what
[`106-releases.md`](106-releases.md) plans and what the README documents, from
the other end: does the *built package* work on a machine that is not this one.

The README already documents installing from source, VICE's binary monitor, and
where wish keeps its files. This does not repeat that. Where a step needs it,
it points at the README section by name.

---

## Read this first — three things that are already known

**1. Both platforms ship one executable, and it is the same one.** `wish-cli`
shipped beside `wish` on Linux until [129-one-binary.md](129-one-binary.md)
folded it in as `wish export` and `wish import`. Every command-line step below
is therefore a step against `wish` itself, on either platform — and on Windows
the subcommands' output does reach a `cmd` window, see note 2.

**2. `wish.exe --version` prints, and this has now been watched.** The spec
builds the window `console=False`, so the process starts with no console of its
own; `packaging/wish_main.py` repairs the streams before anything writes — an
inherited handle first (a redirect, a pipe), else the console that launched us,
borrowed with `AttachConsole(ATTACH_PARENT_PROCESS)` and written through
`CONOUT$`, else `os.devnull`.

*Verified 2026-08-22, on Donald's Windows machine:* `wish --help` and
`wish --version` typed into a Command Prompt both print their output there,
ordinarily — "the CLI works perfectly fine in windows". Double-clicked from
Explorer the window opens and **there is no console window anywhere**, which
is both halves of the assertion: the borrow works where there is something to
borrow, and the windowed build never conjures a console where there is not.

Started by double-click there is still no console to borrow, so messages
written before the window is up — the "no game disks … so the map tab will be
empty" line included — go to `os.devnull` and are lost. The window's
**Help > About wish** is the version either way. The fallback chain is also
unit-tested on Linux (`tests/test_packaging.py`) and `release.yml` asserts on
the output of `wish.exe --version`, so a regression fails the tag rather than
shipping.

**3. The Commodore 64 Ultimate backend cannot be tested.** Nobody on the
project has the hardware. It is written from vendor documentation and exercised
only against a stub. Leave `POR_ULTIMATE` unset and it is never probed, so it
costs nothing; there are no steps for it below because there is no honest way
to write them.

`release.yml` runs the whole test suite before it builds anything — a red
`test.yml` now stops a tag. The two known failures in `106-releases.md`
§Verification are not about packaging.

---

## 0. Getting a Windows package to test

**This document is the Windows half.** The Linux artefacts are validated by the
assistant, in a throwaway virtual environment that is deleted afterwards —
`§2`, `§3`, `§4` and the Linux side of `§6` record what was run and what came
out, and `§7`'s Linux column is filled in. Nothing here asks you to
`pip install` anything on your own machine, because a second `wish` on your
`PATH` is exactly the confusion this project does not need.

**PyInstaller cannot cross-compile.** It bundles the interpreter it is running
on, so a Windows executable has to be built on Windows. There is no flag, and
Wine is not worth the trouble. That leaves two ways to get one:

**The easy way — let GitHub build it, no tag needed.** `release.yml` has a
`workflow_dispatch` trigger, so:

1. GitHub → **Actions** → **release** → **Run workflow**, on `main`.
2. Wait for it. The `windows build` job is the one you want.
3. Download the **`frozen-windows`** artefact from the run's summary page. It
   is a zip containing `wish-<version>-windows-x86_64.zip`.
4. Copy that to the laptop and start at **W1**, or to the VM by `§0c`.

A manual run **builds and stops** — it does not make a release page. Only a
`v*` tag does that. The version will be a development one like
`0.1.0.dev12+g1a2b3c4` rather than a clean tag; that is expected and does not
affect what you are testing.

**The other way — build it on the laptop.** Needs Python 3.12+ there, and is
`§0b` below. Prefer the first way: it needs nothing installed on Windows at
all, which is also closer to what a real user does.

---

## 0b. Building on the laptop, if you would rather

Every step of the release build runs locally, and these are the commands CI
uses.

Everything lands in `dist/`. Start from a clean checkout of what you mean to
test.

**B1. The environment.** The editable install is what writes `wish/_version.py`,
and that file is how a frozen build knows what it is.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[gui]" pyinstaller build
```

**B2. What version will it claim?** The version comes from the nearest git tag
via `hatch-vcs`. With no tag you get something like
`0.0.1.dev158+gae28e8dcb`, which is fine for exercising the machinery but is
not what a release looks like. To rehearse the real thing, tag first — locally,
and delete it afterwards:

```sh
git tag v0.1.0
python3 -c "from wish import __version__; print(__version__)"   # 0.1.0
```

**B3. The wheel, and the sdist that goes with it.**

```sh
python3 -m build                # dist/wish_goldbox-<version>-py3-none-any.whl
```

Two files come out: the wheel and `wish_goldbox-<version>.tar.gz`, the sdist.
Both are what CI builds — **the sdist goes to PyPI and not to the release
page**, see §1. `--wheel` skips it if you only want the file §4 installs.

The distribution is `wish-goldbox`, because `wish` is taken on PyPI by an
unrelated package; setuptools spells the hyphen as an underscore in file names.
The command is still `wish`.

**B4. The frozen build.** About ten seconds, and roughly 157 MB unpacked.

```sh
pyinstaller --noconfirm wish.spec
ls dist/wish                    # wish and _internal/, nothing else
dist/wish/wish --version        # wish <version>
dist/wish/wish export --help    # usage: wish export ...
```

The second of those is the only check that reaches `tools.wish`, which the
subcommands import from inside `main()` and PyInstaller's scan cannot see.

**B5. Name and pack it the way CI does.** The platform in the name is the only
thing distinguishing this `.tar.gz` from a source archive, so do not skip it.

```sh
V=$(python3 -c "from wish import __version__; print(__version__)")
NAME="wish-$V-linux-x86_64"
mv dist/wish "dist/$NAME"
tar -C dist -czf "$NAME.tar.gz" "$NAME"
```

**B6. Gather and checksum.** CI's `publish` job puts every artefact in one
directory and runs `sha256sum *` there, so every line in `SHA256SUMS` is a bare
file name. Do the same, or §2 cannot check the file: a line reading
`dist/wish_goldbox-….whl` is a name that does not exist beside `SHA256SUMS`,
and `--ignore-missing` then skips it in silence — one `OK` instead of two, and
exit status 0. That failure was reproduced on 2026-08-22, which is why this
step no longer says `sha256sum dist/*.whl *.tar.gz`.

```sh
mkdir -p release
cp dist/*.whl "$NAME.tar.gz" release/
(cd release && sha256sum * > SHA256SUMS && cat SHA256SUMS)
```

`dist/*.whl` and not `dist/*`: the sdist is in `dist/` too and does not belong
on a release page, and `$NAME.tar.gz` is the frozen build, which does.

**B7. Windows.** The same steps on the Windows machine, with one difference:
the packing step is PowerShell rather than `tar`. `pyinstaller` produces
`dist/wish/wish.exe` and nothing else beside `_internal/`, the same as Linux.

```powershell
Move-Item dist/wish "dist/wish-<version>-windows-x86_64"
Compress-Archive -Path "dist/wish-<version>-windows-x86_64" `
                 -DestinationPath "wish-<version>-windows-x86_64.zip"
```

**B8. Gather and checksum, on Windows.** B6's counterpart, and it was missing:
the Windows path stopped at the zip, so §2 sent you to verify a `SHA256SUMS`
that nothing on this machine had written. Bare file names, like B6, so §2 can
find each file beside it.

```powershell
New-Item -ItemType Directory -Force release | Out-Null
Copy-Item "wish-<version>-windows-x86_64.zip" release/
Push-Location release
Get-ChildItem -File | Where-Object Name -ne SHA256SUMS | ForEach-Object {
  "{0}  {1}" -f (Get-FileHash $_ -Algorithm SHA256).Hash.ToLower(), $_.Name
} | Set-Content -Encoding ascii SHA256SUMS
Get-Content SHA256SUMS
Pop-Location
```

**Tidy up.** If you tagged in B2, `git tag -d v0.1.0` before you forget — a
stray local tag will change the version of the next thing you build.

**A dirty or moving tree changes the version.** `hatch-vcs` runs
`git describe --dirty`, so an uncommitted edit anywhere in the checkout appends
`.dYYYYMMDD` to the version, and a commit landing between B1 and B3 gives the
wheel and the frozen build *different* version strings. Neither is fatal for
exercising the machinery — CI builds from a clean checkout at a tag and gets a
clean number — but build from a quiet tree if you want the names to match.

*Run by the assistant on 2026-08-22, in a throwaway venv under `work/`, at
version `0.0.1.dev165+g24a77e835.d20260822`. B1–B6 all worked; the frozen build
took 9.4 s and came to 158 MB unpacked, the wheel to 386 KB, the tarball to
60 MB. B6 was rewritten in the course of the run — see the note on it.
B7 is CI's own Windows recipe, and is unverified by hand — you are the first
person to run it.*

---

## 0c. Getting it onto the Windows VM

The laptop is not the only Windows there is. The `win11` domain under libvirt
runs the same build, and `winvm` carries the non-interactive SSH options, so a
failed copy is an error on stderr rather than a credential dialog on the
desktop.

```sh
winvm acquire wish-test
winvm scp ~/Downloads/wish-win/'wish-<version>-windows-x86_64.zip' \
          donald@192.168.123.50:'C:/Users/donald/Desktop/'
winvm release wish-test        # when you are done
```

`winvm scp` hands its arguments straight to `scp`, so the destination needs the
full `donald@192.168.123.50:` prefix — unlike `winvm ssh`, which fills the guest
in for you. Quote the filename: a development version carries a `+`.

To unpack without opening Explorer:

```sh
winvm ssh 'powershell -NoProfile -Command "Expand-Archive -Force -Path C:\Users\donald\Desktop\wish-<version>-windows-x86_64.zip -DestinationPath C:\wish"'
```

**Starting `wish.exe` over `winvm ssh` will show you nothing.** That shell lands
in Windows session 0 and the VM's screen is session 1, so the window appears on
neither and `winvm shot` cannot capture it. Start it from the VM's own desktop.
`143-winuae-debugger.md` has the detail, the lease model and the scheduled-task
workaround, and is the reference for `winvm` generally — this section is only
how a release package gets across.

**The VM is a second environment, not a substitute for the laptop.** It is the
same build on different hardware, drivers and display stack, and §7's table has
one Windows column — so say which machine a result came from when you fill it
in.

---

## 1. Before you start

| | Linux | Windows |
|---|---|---|
| a save disk | a **copy** of one `PORSAVE*.D64` | the same copy, transferred over |
| a game disk | `POOLBOOT.D64` and `POOL1.D64`–`POOL8.D64` | the same set, copied over |
| VICE | already installed (Flatpak `net.sf.VICE`) | **not installed** — step W1 |
| Python | 3.12+, for the wheel test only | not needed at all |
| the artefacts | all three, plus `SHA256SUMS` — from a release page, or built yourself in §0 | the same |

The release page carries three files we build, plus checksums:

| file | what it is |
|---|---|
| `wish_goldbox-<version>-py3-none-any.whl` | the wheel |
| `wish-<version>-linux-x86_64.tar.gz` | the frozen Linux build |
| `wish-<version>-windows-x86_64.zip` | the frozen Windows build |
| `SHA256SUMS` | one line per file above |

Above them GitHub adds **Source code (zip)** and **Source code (tar.gz)** on
its own, for every tag. They are archives of the repository at that commit,
they are not built by us, and they cannot be renamed or removed -- which is why
our own sdist stays off the page. Three things called some variation of
"source" on one page is worse than none. It is built, and it goes to PyPI,
where it is the only source anyone can get: see
[`106-releases.md`](106-releases.md) §5.

**Nothing in this walkthrough may touch your real save disks.** Step L1 makes a
working copy and everything afterwards operates on that copy or on files
derived from it. The one place it matters most is the editor: unlike the CLI,
the editor's **Save writes back to the file you opened** (it takes a backup
first — `editor/files.py::save_disk` — but it does write). Work on the copy.

---

## 2. Checksums, both platforms

**Only for a release you downloaded.** If you built the artefacts yourself in
§0 there is nothing here to catch: you have the bytes you just made, and the
`SHA256SUMS` you would check them against is one you wrote in B6 or B8. Skip
to §3. A frozen build straight out of `pyinstaller` is `wish.exe` and
`_internal/` in `dist/wish` and nothing else -- no checksum file, because
making one is a later step, and running §2 against it reports nothing at all.

Do this before unpacking anything.

**Linux**

```sh
cd ~/Downloads/wish-release
sha256sum --ignore-missing -c SHA256SUMS
```

**Count the `OK` lines.** One per file you downloaded — two from a Linux-only
download, three with the Windows zip. `--ignore-missing` is there so a partial
download does not bury the real answer under "No such file", and the price is
that a *name* it cannot find is skipped in silence: a `SHA256SUMS` whose lines
carry directories rather than bare names verifies nothing and still exits 0.
That is a check on `SHA256SUMS`, not on your download, and B6 is where it is
fixed.

*Run by the assistant on 2026-08-22 against the `0.0.1.dev165+g24a77e835.d20260822`
wheel and tarball: two `OK` lines, exit 0.*

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

*Run by the assistant on 2026-08-22 against
`wish-0.0.1.dev165+g24a77e835.d20260822-linux-x86_64.tar.gz`. L1–L7 all passed;
every measurement and every quoted string below is from that run. It was done
under `work/relcheck/` rather than `~/wish-test`, and with `XDG_CONFIG_HOME`
and `XDG_DATA_HOME` redirected there, so that nothing landed in Donald's own
`~/.config/wish` or `~/.local/share/wish` — both were confirmed untouched
afterwards. The window steps ran on a headless `Xvfb` driven by `xdotool`.*

**L1.** Make the working copy. Everything downstream uses it.

```sh
mkdir -p ~/wish-test && cd ~/wish-test
cp "/home/donald/c64/Pool of Radiance Disks/PORSAVE11.D64" ./TESTSAVE.D64
```

**L2.** Unpack the frozen build.

```sh
tar xzf ~/Downloads/wish-release/wish-<version>-linux-x86_64.tar.gz
cd wish-<version>-linux-x86_64
ls
```

*Expect:* two entries and no more — `wish` and `_internal/`. 157 MB unpacked,
155 MB of it `_internal/`, three quarters of that Qt; the tarball itself is
59 MB. *If there is a second executable:* `wish.spec` grew one back, and
`tests/test_packaging.py` and CI's "there is exactly one executable" step should
both have caught it first.

**L3.** Version.

```sh
./wish --version
```

*Expect:* `wish <version>`, exactly the tag with the `v` stripped. `--version`
exits inside argparse before Qt is imported, so this works with no display.
*If it says `0.0.0+unknown` or a `.dev` version:* the build did not see the tag
— `wish/_version.py` was not written by the editable install in `release.yml`,
and the artefact is mislabelled. That is a release blocker.

**L3a.** The subcommands are in the same executable:

```sh
./wish export --help
```

*Expect:* `usage: wish export [-h] [--output FILE] ... SAVE.D64`. *If it dies in
`ModuleNotFoundError: tools`:* the `tools.wish` hidden import fell out of
`wish.spec`. Steps L10 and L11 work against `./wish` as well, and running them
here exercises the frozen build rather than the installed one, which is the
interesting half.

**L4.** Start the window on a save disk.

```sh
./wish --tab editor ~/wish-test/TESTSAVE.D64
```

*Expect:* the window opens on the Character Editor tab with the party loaded, a
roster down the left, and the title bar reading `wish - TESTSAVE.D64`. On
stderr you may see a "no game disks … so the map tab will be empty" line if the
disks are not where `automap/paths.py` looks — harmless for the editor, and
step L7 fixes it.

*Also expect,* above the inventory table: `No game disk found, so items show as
name-table indices`, and every item listed as `word 8`, `word 9` and so on.
That is a **different** lookup from the automapper's — it wants `--game-disk` or
`$POR_GAME_DISK`, and finding the disks for the map tab does not satisfy it.
Not a fault, but it is the first thing in the window that looks like one.

*If it does not start at all,* run it from a terminal and keep the traceback:
a frozen Qt build failing on a distribution other than Ubuntu usually names a
missing system library (`libEGL`, `libxkbcommon-x11`, `libGL`).

**L5.** Check the version the window reports: **Help > About wish**. It must
match step L3. It is the only route to the version after a double-click on
Windows, so confirm it agrees here where you can check both.

**L6.** The round trip, through the window.

1. Pick a character. Change **gold** to `4321` — visible on the game's own
   character sheet, easy to spot, and nothing else depends on it.
2. **File > Save As…**, and give it a *new* name: `~/wish-test/EDITED.D64`.
   **Never plain Save on the first pass** — Save writes back to `TESTSAVE.D64`.
   The dialog opens with `TESTSAVE.D64` already in the File name box and
   selected, so a reflexive Return here overwrites the file the step is trying
   to protect. Type over it.
3. *Expect:* the status bar says `wrote EDITED.D64`, and the title bar becomes
   `wish - EDITED.D64`.
4. **File > Open…** `TESTSAVE.D64` — gold must read `2` again — then
   `EDITED.D64`, where it must read `4321`. Reopening only the edited disk
   proves nothing: the field is already showing 4321 from the edit.
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
3. Load the saved game and open that character's sheet — **VIEW CHARACTER**
   from the party menu, before **BEGIN ADVENTURING**.
4. *Expect:* gold reads 4321 and the party is otherwise exactly as you left it.
   *If the game rejects the disk or the party is wrong,* keep `EDITED.D64` — a
   broken disk is the evidence.

*Verified 2026-08-22:* the game loaded `EDITED.D64`, listed all six characters
at their right AC and HP, and MALCYON's sheet read `GOLD 4321`. The same was
done again with `CLI-EDITED.D64` from L10 (step **L12**), where BRUTUS — gold 0
on the original disk — read `GOLD 4321`.

---

## 4. Linux — the wheel

This is the path a Python user takes, and it exercises code the frozen build
never runs: the entry points from installed metadata, `tools/` as an installed
package, and the version from installed metadata rather than `wish/_version.py`.

*Run by the assistant on 2026-08-22 against
`wish-0.0.1.dev165+g24a77e835.d20260822-py3-none-any.whl` — the distribution
was still called `wish` on the day, so a wheel built now is
`wish_goldbox-<version>-py3-none-any.whl`. L8–L12 all passed.*

**L8.** A venv with nothing in it.

```sh
cd ~/wish-test
python3 -m venv .venv-release
source .venv-release/bin/activate
pip install "$HOME/Downloads/wish-release/wish_goldbox-<version>-py3-none-any.whl[gui,automap]"
```

*Expect:* PyQt6, PyQt6-Qt6, PyQt6_sip and PyYAML pulled in — five packages
including `wish-goldbox` itself, which is the distribution's name and not the
command's — with no build step and no compiler.
*If pip refuses the extras syntax,* quote the whole argument — the brackets are
the shell's otherwise.

**L9.** The one command reports the version, and carries the subcommands.

```sh
wish --version        # wish <version>
wish export --help    # usage: wish export ...
ls .venv-release/bin | grep wish   # exactly one name
```

The version must be the same number as L3. `tools` only ships because
`pyproject.toml` lists it in the wheel's packages — if `wish export` dies in
`ModuleNotFoundError: tools`, that list regressed.

**Exactly one name.** `wish-cli`, `wish-editor` and `wish-automap` were dropped
in [129-one-binary.md](129-one-binary.md); any of them reappearing means
`[project.scripts]` grew an entry back.

**L10.** The CLI round trip.

```sh
cd ~/wish-test
wish export TESTSAVE.D64 -o party.yaml
sed -i 's/^\( *gold: \).*/\14321/' party.yaml      # or edit it by hand
wish import party.yaml --dry-run
wish import party.yaml -o CLI-EDITED.D64
```

*Expect:* the dry run lists **one line per character** — that `sed` rewrites
every `gold:` in the file, so a six-strong party gives
`slot 0 MALCYON: gold 2 -> 4321` down to `slot 5 BRUTUS: gold 0 -> 4321` and
`6 change(s) (dry run, nothing written)` — and writes nothing; the import writes
`CLI-EDITED.D64`. *Expect also:* `wish import party.yaml -o TESTSAVE.D64` is
**refused**, exit 2, on
`--output must differ from the original save; refusing to overwrite it`.
Try it; a release where that guard is gone is a release that eats saves.

**L11.** Losslessness. Export and re-import with no edit at all, and the disk
must come back byte for byte:

```sh
wish export TESTSAVE.D64 -o plain.yaml
wish import plain.yaml -o ROUNDTRIP.D64
cmp TESTSAVE.D64 ROUNDTRIP.D64      # expect: no output
```

*If they differ,* stop. Everything else in the tool depends on this property.

**L11a.** The same, on a **second title**. `goldbox/games.py` detects the title from
the save file's own name and load address and carries geometry for six of them, so
this is the step that proves the frozen build ships that table rather than
defaulting everything to Pool of Radiance. Copy a Curse of the Azure Bonds save
disk (`SAVEAZURE`) or a Secret of the Silver Blades one (`SAVEDBASH`) beside its
own game disks and repeat L11 against it.

*Expect:* the export names the right title in its header comment, the party
decodes, and the re-import is byte-identical. *If the export refuses the disk,*
the title table did not make it into the package — that is a release blocker for
the same reason L9's `ModuleNotFoundError: tools` is.

*Verified 2026-08-22* against a Curse of the Azure Bonds save made by the
project's own driven session (`work/curse/CURSESAVE2.D64`), there being no
`SAVEAZURE` disk in `/mnt/media/roms`. It exported three characters under
`# Curse of the Azure Bonds character export`, and re-imported byte for byte.
Silver Blades remains untested: the disks are there, a save is not.

**L12.** Boot `CLI-EDITED.D64` in the game as in L7, and confirm gold. Then
`deactivate` the venv.

---

## 5. Windows, from nothing

Assume a machine with no Python, no VICE, and no game files. Copy the game
disks, `TESTSAVE.D64`, and all five downloads over first.

On the VM, `winvm revert` restores the golden base, so "from nothing" is
repeatable: install, test, revert, test again. The laptop gives you one clean
run per reinstall. Do **not** `winvm promote` — that makes the state you have
just been testing the new baseline, which is the opposite of what this section
is for.

Put the game disks somewhere `automap/paths.py` looks — the simplest is
`%USERPROFILE%\Documents\Pool of Radiance Disks\`. Anywhere else and you will
need `POR_DISKS`.

### W1. Install VICE

1. Download the Windows GTK3 build from
   <https://vice-emu.sourceforge.io/> — the "windows" download, a **zip**, not
   an installer. *(Unverified: VICE has shipped Windows builds as zips through
   3.7–3.9; check the page rather than trusting this line.)*
2. Extract to a **short path** — `C:\vice`. Deep Qt/VICE paths under a nested
   Downloads folder can run into the 260-character limit.
3. Run `C:\vice\bin\x64sc.exe` once, confirm you get a C64 screen, and quit.

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

**Do exactly what a user would do — do not unblock anything.** A user who
downloads a zip and double-clicks it meets whatever Windows does next, and that
is the thing being tested.

1. Extract to a short path: `C:\wish`. Same 260-character reason as VICE, and
   the Qt tree inside is deeper.
2. *Expect:* `C:\wish\wish-<version>-windows-x86_64\wish.exe`, `_internal\`
   and nothing else at the top level. One executable, the same as Linux — note
   1.
3. First extraction may be slow — Defender scans ~156 MB of fresh binaries.
   Minutes, not seconds, is normal.

### W5. Run it, past the warning

Double-click `wish.exe`.

*Expect:* **"Windows protected your PC"** — SmartScreen, because the executable
is unsigned and always will be; a certificate costs money and SmartScreen warns
on new signatures anyway. Click **More info**, then **Run anyway**.

*Expect then:* **the wish window, and no console window behind it.** That is
the assertion — a windowed build that opens a black console box alongside the
map is a packaging mistake. *Confirmed 2026-08-22:* the GUI launched from
Explorer and there was no console window anywhere.

*If instead the file vanishes,* Defender quarantined it as a PyInstaller false
positive — check Windows Security > Protection history. **Unverified**: this
happens to some PyInstaller builds and not others.

**The command line, which now works.**

```powershell
cd C:\wish\wish-<version>-windows-x86_64
.\wish.exe --version
.\wish.exe --help
```

*Expect:* both print, in the window you typed them in. *Confirmed 2026-08-22*
from a Command Prompt: the version printed, the help text printed, and the
output was ordinary — no interleaving with the shell's next prompt worth
noting. Nobody is expected to use the command line on Windows, and the version
is in **Help > About wish** too, but it is no longer an open question.

*If you get a PyInstaller traceback box, that is a real regression* and worth a
screenshot: this path used to die in `AttributeError: 'NoneType' object has no
attribute 'write'`.

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
| notes, explored squares | `%LOCALAPPDATA%\wish\maps\<GAME>\<AREA>.json` | when a note is added, or the window closes |
| debug log | `%APPDATA%\wish\logs\wish-*.log` | only while the log is on |
| save backups | the folder named in File > Preferences — `backups\` beside the save until the player picks another | on a save that changed something |

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

*Linux side run by the assistant on 2026-08-22 against the frozen
`0.0.1.dev165+g24a77e835.d20260822` build, with the game standing in New Phlan
at (4,2). M2–M6 all passed. Every quoted string below is what the window
actually showed.*

**M1.** With the game running and the monitor enabled, start wish on the map:

* Linux, frozen: `./wish --tab map`
* Linux, wheel: `wish --tab map`
* Windows: `wish.exe`, then **View > Automapper** (`Ctrl+1`)

**M2.** *Expect,* within a second or two, the party and the map to be **live**.
There is no "connected" announcement — a connection that works says so by
working:

* the six characters fill the roster down the left, with AC, THAC0, hit points
  and readied items;
* the strip under the map reads the party's square, facing, the game clock and
  the area — `(4,2) facing E   16:47   New Phlan   party effects: none`, which
  should agree with the game's own status line;
* the status bar counts squares — `13/256 seen   revealing   [status]`. The
  bracketed word is where the position came from, and `[status]` means the
  game's status line, which is the ordinary case.

*If it instead says `waiting for a game - VICE: start VICE with its binary
monitor enabled …`:* the monitor is not listening. Linux: `ss -tln | grep 6502`.
Windows: `Test-NetConnection 127.0.0.1 -Port 6502` (*unverified spelling of the
result on a closed port*, but a `TcpTestSucceeded : False` is unambiguous).

*If it says something about the monitor being busy,* in red: something else
already holds it. VICE serves exactly one binary-monitor connection and ignores
the second. Close the other client.

**M3.** Walk the party three or four squares in the game.

*Expect:* the party marker moves on the map in step with the game, the squares
you cross fill in, the seen count and the clock climb together, and the area
stays named. Three steps east took the strip from `(4,2) facing E 16:47` to
`(6,2) facing E 16:49` and the count from `7/256` to `13/256`. Latency of a
couple of polls (200 ms each) is normal.

*If the map is empty but the connection is up:* no game disks were found and
there is no `GEO` to draw. Point `--disks` or `POR_DISKS` at them. The warning
that says so goes to stderr, so on Windows you only see it if you started
`wish.exe` from a terminal — after a double-click this empty map is the only
symptom.

**M4.** Put a note on the party's square: **click the square**, or press **N**
with the map focused — the keystroke reaches the canvas only once it has
keyboard focus, so a click is the reliable way in. A popover opens, headed with
the coordinates and a row of icon buttons; type the text and press Return, or
click **Keep**. Then press **R** to toggle fog of war and back.

*Expect:* a small marker in the corner of the square, and its text on hover.
`R` flips the status bar between `revealing` and `whole map`, and the **Fog of
war** box at the right-hand end of the status bar follows it.

**M5.** Close the window entirely. Reopen it and return to the map tab.

*Expect:* the note is still there, the explored squares are still filled, and
the window is the size you left it. Notes are written on every edit *and* on
shutdown, so both paths are covered by this one check.

The files to look at, if you want to see it rather than infer it:
`~/.local/share/wish/maps/GEO00.json` holds `"notes"` keyed by `"6,2"` and a
`"seen"` list; `~/.config/wish/automap.json` holds `window_width`,
`window_height`, `reveal`, `interval_ms` and `sight`.

*If they are gone:* the config directory is not writable, or the frozen build
resolved it somewhere unexpected. Check for the file — `~/.local/share/wish/maps/`
on Linux, `%LOCALAPPDATA%\wish\maps\` on Windows.

**M6.** Close and reopen wish with the game *not* running.

*Expect:* the window opens, the map tab draws an empty grid and says
`waiting for a game - VICE: start VICE with its binary monitor enabled …`
followed by the `$POR_ULTIMATE` hint, the action buttons grey out, nothing
crashes, and the editor tab works normally. A tool that requires the emulator to
start is a tool that is useless half the time.

*Cosmetic, seen on 2026-08-22:* that waiting message is long enough to run off
both ends of the party panel it is drawn in. Legible enough to act on, ugly.

---

## 7. Results

Tick as you go. `n/a` where a row does not apply to that platform.

**The Linux column is filled in.** Every ✅ was watched by the assistant on
**2026-08-22**, at version **`0.0.1.dev165+g24a77e835.d20260822`**, against
artefacts built by `§0b` from this working tree.

**The Windows column is half filled in**, by Donald on **2026-08-22**, on his
own Windows machine. Eleven rows ✅ ⁵. The rest are still his to do.

| # | check | Linux | Windows |
|---|---|---|---|
| 2 | `SHA256SUMS` verifies | ✅ | ☐ |
| L2 | frozen archive unpacks, `wish` present | ✅ | ✅ ⁵ |
| L3 | `wish --version` prints the version | ✅ ¹ | ✅ ⁵ |
| L3a | `wish export --help` prints its usage | ✅ | ✅ ⁵ |
| W5 | **the window opens and no console appears** | n/a | ✅ ⁵ |
| L5 | Help > About shows the same version | ✅ | ✅ ⁵ |
| L4 | window opens on a save disk | ✅ | ✅ ⁵ |
| L6 | edit, Save As, reopen — value stuck | ✅ | ☐ (W6) |
| L6 | the original save disk is byte-identical afterwards | ✅ | ☐ |
| L7 | the game loads the edited disk and shows the edit | ✅ | ☐ (W6) |
| L8 | wheel installs into a clean venv | ✅ | n/a |
| L9 | `wish --version`, and exactly one name in `bin` | ✅ | n/a |
| W4 | one executable in the zip, beside `_internal/` | n/a | ☐ |
| L10 | `wish export` / dry-run / `wish import` round trip | ✅ ⁴ | ☐ |
| L10 | `-o` over the original is refused | ✅ ⁴ | ☐ |
| L11 | unedited round trip is byte-identical | ✅ ⁴ | ☐ |
| L11a | the same, on a Curse or Silver Blades save | ✅ (Curse) | n/a |
| L12 | the game loads the **CLI**-edited disk and shows the edit | ✅ | ☐ |
| W1 | VICE installs and starts | n/a | ☐ |
| W2 | binary monitor enabled and survives a restart | n/a | ☐ |
| W5 | SmartScreen warning cleared, program runs | n/a | ☐ |
| W7 | settings and notes land in the user directories, not beside the exe | ✅ | ☐ |
| M2 | automapper attaches | ✅ | ✅ ⁵ ⁶ |
| M3 | the map tracks the party | ✅ | ✅ ⁵ |
| M5 | notes and explored squares survive a restart | ✅ ² | ✅ ⁵ |
| M6 | starts cleanly with no emulator running | ✅ | ✅ ⁵ |
| 8 | debug log writes, and names no paths | ✅ ³ | ✅ ⁵ |

¹ **No `v*` tag has been cut, so what is proven is the pipe, not the tag.** The
version built, printed and reported was `hatch-vcs`'s development string, and it
was identical in the wheel, in `dist/wish/wish` and in Help > About. Whether a real tag comes through clean is `release.yml`'s "the
version is the tag" step, which has also never run.

⁴ **Re-run on 2026-08-22 under the new spelling**, `wish export` / `wish import`
rather than `wish-cli`, after [129-one-binary.md](129-one-binary.md) merged the
two binaries: the same six `gold 2 -> 4321` lines, the same refusal on exit 2,
and `cmp` silent on the unedited round trip. Verified both in a wheel installed
into a throwaway venv and in `dist/wish/wish` from a local `pyinstaller` run.
The Windows column is no longer `n/a` for these — the subcommands ship there
now — but it is untested, and nobody is expected to use them there.

² The note, the explored squares and the saved geometry in `automap.json` all
survived. **The window did not come back at the size it was left** — but the
test ran on a bare `Xvfb` with no window manager, and geometry restore is the
window manager's business, so that is the harness and not the build. Untested.

³ The log wrote, and rewrote every absolute path to `~.../basename` as promised.
**Its first line read `wish unknown` on the day** — the version was looked up by
distribution name, and the distribution had been renamed out from under it.
Fixed: `wish/debuglog.py` now takes `wish.__version__`, which is the same string
`wish --version` prints and works in a frozen build where there is no metadata
at all. The metadata lookup that remains, in `wish/__init__.py`, names
`wish-goldbox` and is checked against `pyproject.toml` by
`tests/test_packaging.py`. **Unverified since the fix** — no build has been
re-run against it.

⁵ **Watched by Donald on 2026-08-22**, on Windows, on the first run of this
half. The three that mattered most, in his words: *"Running wish.exe from the
Windows Explorer launches the GUI. Running wish --help from the Windows Command
displays the help text. Running --version prints the version. The CLI works
perfectly fine in windows. When run from Windows Explorer, the gui launches and
there is no console window anywhere."*

⁶ **M1** — starting on the map tab — has no row of its own; it is what M2
attaches from, and it was run.

**The run found four real defects**, which is what a first run on a new platform
is for. An oversized window on his display, unreadable spin boxes in the editor,
the roster selection, and a fog-of-war fault in the automapper. All four are
being fixed elsewhere and none of them is a packaging fault, so none of them
un-ticks a row above.

---

## 8. When a step fails

Capture these four things before you change anything. A failure you cannot
reproduce is a failure you cannot fix.

**1. The version.** `wish --version` — from a terminal on Windows too — or
Help > About. Without it nobody knows which build you had. The debug log's first
line carries it too, and should agree; if it says `wish unknown`, that is the
rename bug of 2026-08-22 come back and it is worth reporting on its own.

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

**3. The terminal.** Start the frozen build from a shell, not from a file
manager, on either platform: a crash before Qt is up prints there and nowhere
else, and on Windows a shell is the only thing that gives the process a console
to print to at all. After a double-click the evidence is PyInstaller's traceback
box instead — screenshot it whole, including the scrollback.

**4. The files, kept.** A save disk that fails to round-trip *is* the bug
report. Keep `EDITED.D64` / `EDITED-WIN.D64` and the `party.yaml` that produced
it. They contain your own party and nothing of the game's, so they are yours to
send.

For the automapper specifically, add: which backend the status bar named,
whether `6502` was listening, and whether anything else was attached to the
monitor at the time.

---

## Marked unverified

The Linux steps were run on 2026-08-22 and their sections now say what was
watched; the first Windows run followed the same day and retired four rows that
used to be here — that `wish.exe --version` reaches a terminal, that its output
lands after the shell's prompt, whether a windowed build opens a stray console,
and whether the frozen build starts at all on Windows. All four are now
observed and their sections say so. Everything below is what is *still*
expectation rather than observation, and worth correcting in this file once you
know:

| where | claim |
|---|---|
| §0b B2 | that a real `v*` tag produces a clean version through the whole build — only a `hatch-vcs` development string has ever been carried end to end |
| L11a | Secret of the Silver Blades: its game disks are here, a `SAVEDBASH` save is not, so only Curse has been round-tripped |
| M5 | that the window comes back the size it was left — the settings file records it, but the Linux run had no window manager to honour it |
| W1 | VICE ships its Windows build as a zip rather than an installer |
| W2 | `%APPDATA%\vice\vice.ini` does not exist until VICE has run and exited once |
| W2 | VICE's own **Settings > Save settings** wording, and that it creates the file |
| W2 | whether Windows Defender Firewall prompts when VICE binds `127.0.0.1:6502` |
| W5 | that SmartScreen shows "Windows protected your PC" and not something else |
| W5 | whether Defender quarantines this PyInstaller build as a false positive |
| W4 | that the Windows zip holds one executable and no more — asserted in CI on both platforms and unit-tested; the zip has now been unpacked and run, but nobody counted what was in it |
| W4 | that the 260-character path limit is actually reachable here |
| M2 | `Test-NetConnection`'s exact output for a closed port |
| — | the Windows zip running on a machine with **no Python at all** — it ran on Donald's Windows machine on 2026-08-22, which is not known to be bare (`106-releases.md` records this as unverified too) |
| — | the Linux frozen build on any distribution other than the one it was built on |
| — | the Commodore 64 Ultimate backend, which cannot be tested at all |
