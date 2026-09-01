# WinUAE's debugger, driven from Linux

The Amiga side needs what the C64 side has in VICE's binary monitor and the DOS
side has in `docs/142-dosbox-x-debugger.md`: memory reads, watchpoints,
breakpoints, registers and single-stepping on a running game, driven unattended.

WinUAE has all of it. What it does **not** have is a socket, and that shapes
everything below.

**Read this before writing a WinUAE backend.** §11 says which claims were
checked and how. The whole path — boot a title, halt it, read its memory, get
the bytes back to Linux — has been run; see `#91 (Configure WinUAE in the
Windows VM so an Amiga title can be driven unattended)`.

## 1. Where it runs

WinUAE is Windows-only, so it runs in the Windows 11 VM described in
`jellyfin-stack/ansible/README-windows-vm.md`, on this machine under
QEMU/KVM. From here it is reached with:

```sh
export SSH_ASKPASS_REQUIRE=never   # see below; set it once, for the session
winvm acquire wish-re          # start the VM, take a lease
winvm ssh "$ps claim -Holder por-run"          # take the one Amiga lane -- 1.1
winvm ssh "$ps start -Holder por-run -log -f C:\Amiga\configs\goldbox-a500.uae"
winvm shot /tmp/screen.png     # see the emulator's screen, from a script
winvm ssh "$ps stop -Holder por-run"
winvm ssh "$ps release -Holder por-run"
winvm release wish-re          # drop the lease; last one out shuts it down
```

where `$ps` is `powershell -NoProfile -ExecutionPolicy Bypass -File
C:\Amiga\winuae.ps1`. **The `-ExecutionPolicy Bypass` is not decoration.**
Every scope of the guest's execution policy is `Undefined`, which on Windows 11
client means `Restricted`, and `powershell -File` on any of these scripts fails
with "running scripts is disabled on this system".

**`SSH_ASKPASS_REQUIRE=never` is not decoration either.** When authentication
falls through, OpenSSH does not fail: with no tty and `DISPLAY` set it runs
`SSH_ASKPASS`, which on this desktop is `ksshaskpass`, and a KDE password
dialog appears in front of whoever is sitting at the machine. Three of them
arrived that way in one night. Set it for anything that can reach `ssh` or
`scp` — including `winvm up` and `winvm acquire` — so a failure stays a failure
and can be read.

**`winvm ssh` does now pass `-o BatchMode=yes`, and this page used to say it
did not.** Read on 2026-09-01, `/usr/local/bin/winvm` builds one `SSH_OPTS`
array carrying `BatchMode=yes` and exports `SSH_ASKPASS_REQUIRE=never` at the
top of the file, with a comment naming the drift that let the dialogs through:
*"`wait_ssh` had BatchMode and the `ssh` subcommand did not"*. So it was true
and has been fixed. Keep exporting the variable anyway — anything of ours that
reaches `ssh` or `scp` directly is not covered by `winvm`'s options, and it
costs nothing.

| what | where |
|---|---|
| WinUAE 64-bit 6.0.3 | `C:\Program Files\WinUAE\winuae64.exe` in the guest — note the `64`, there is no `winuae.exe` |
| Kickstart ROMs | `C:\Amiga\Kickstarts` — the fourteen out of `~/FS-UAE/Kickstarts` |
| Game disk images | `C:\Amiga\Disks` — Pool of Radiance, Curse, Silver Blades, Pools of Darkness as `.adf`/`.zip` |
| guest address | `192.168.123.50`, static — no DHCP on that libvirt network |
| host → guest | `ssh donald@192.168.123.50`, key-only |
| the machine config | `tools/goldbox-a500.uae`, deployed to `C:\Amiga\configs\` |
| the guest-side driver | `tools/winuae.ps1` and `tools/winuae-send.ps1`, deployed to `C:\Amiga\` |
| the check on the driver | `tools/winuae-lanecheck.ps1` — proves one driver cannot destroy another's run, 1.1 |

**`winvm ssh` lands in Windows session 0; the VM's screen is session 1.** They
are different window stations, and the consequences are not cosmetic:

* a GUI process started from an SSH shell never appears in `winvm shot`;
* nothing in session 0 can raise or focus a session 1 window;
* `AttachConsole` cannot cross the boundary either — it fails with
  `GetLastError 203` every time.

`tools/winuae.ps1` exists for this one reason: every action it takes goes
through a scheduled task with an `Interactive` principal, which runs in
whichever session the user is logged on to.

The ROMs are raw dumps, not Cloanto's encrypted ones, so WinUAE identifies them
by CRC and no `rom.key` is needed. `C:\Amiga` is excluded from Defender's
real-time scanning, which is what would otherwise cost real time on ADF and HDF
images.

**Kickstarts are ROMs; the game floppies are disk images.** They are kept in
separate directories because only one of them is a ROM path as WinUAE means it,
and conflating the two makes the setting that matters ambiguous.

### The ROM database, which is not the config's ROM path

`tools/goldbox-a500.uae` names the Kickstart by absolute path, and that is
enough for a command-line run. **The GUI does not use it.** WinUAE's own
windows resolve ROMs through a scanned database in the registry, so on a
machine where the scan has never run, opening WinUAE tells a person there are
no ROMs at all — "One of the following system ROMs is required: KS ROM v1.3
(A500,A1000,A2000) rev 34.5 (256k) [315093-02] ... Check the System ROM path in
the Paths panel and click Rescan ROMs."

Two registry values under `HKCU\Software\Arabuusimiehet\WinUAE` settle it:

| value | what it is |
|---|---|
| `KickstartPath` | the Paths panel's *System ROMs* box. Ships as `C:\Users\Public\Documents\Amiga Files\WinUAE\`, which holds no ROMs |
| `DetectedROMs` | a subkey holding the scan's results, one `ROM_nnn` value per ROM |

**Delete `DetectedROMs` and WinUAE rescans `KickstartPath` at its next
startup — a `use_gui=no` run rescans exactly as the GUI does**, so no click and
no window is needed anywhere. `winuae.ps1 roms` sets the path, deletes the
subkey, takes one headless run to rebuild it, and then checks the result.
Measured: 5 entries before, all of them WinUAE's own pseudo-ROMs (`SuperIV`,
`HRTMon`, `AROS`, `NOROM`, `ENABLED`); 14 after, of which nine are real files.

**The ROM the dialog asks for is present**: `C:\Amiga\Kickstarts\kick34005.A500`
is 262,144 bytes with SHA-1 `891e9a547772fe0c6c19b610baf8bc4ea7fcb785`, which
is Kickstart 1.3 rev 34.5 [315093-02]. It is `ROM_006` after the scan.

This is in golden, so opening WinUAE on the VM gets the Quickstart panel reading
`A500` and `1.3 ROM, OCS, 512 KB Chip + 512 KB Slow RAM (most common)`. Re-run
`winuae.ps1 roms` and promote again if the ROM directory ever changes.

**Not against a live session.** The scan is a real `winuae64` run, so for the
minute it takes there are two of them, and `front`, `key` and `send` pick their
target by process name — with two, the wrong one can be picked in silence.
`roms` refuses while an emulator is running, and those three refuse when they
find more than one, naming both pids. Stop the session first.

An SSH shell cannot leave one behind on its own: sshd ends its session's whole
process tree when the call returns, so an emulator started from one dies with
the call that started it. `roms` is one way to two emulators; **a second driver
is the other**, and that one is not rare — `tools/winuae-lanecheck.ps1`'s
`hijack` round produced `fail 2 winuae64 processes after starting: 1944,9640`
from two `start` calls a second apart.

### 1.1 One lane at a time, and the claim that enforces it

**The hazard is not two emulators. It is two drivers of the one emulator**, and
until 2026-09-01 nothing on this machine could tell them apart. There is one
scheduled task, one interactive session and one `winuae64`, and `key`, `send`
and `front` find their target by process *name* — so a second agent does not
get a second emulator, it gets yours. `#116 (Two agents cannot share the WinUAE
VM, and neither of them can tell)` is the night that cost: six keystrokes into
a stranger's Pools of Darkness, a `start` that reported `ok pid=6644` for
somebody else's config, and a `stop` that ended their session three times.

`winvm acquire <tag>` does not help, and must not be mistaken for a mutex: two
agents using the documented `wish-re` tag share one lease file, and
`winvm release` shuts the VM down when the last lease goes — so the polite
thing at the end of a run kills the other agent's emulator.

`winuae.ps1` now says the constraint out loud and enforces it:

| call | what it does |
|---|---|
| `claim -Holder <id>` | takes the lane; refuses a second holder, naming who has it and since when |
| `release -Holder <id>` | gives it back. Does *not* stop the emulator |
| `claim -Holder <id> -Override` | takes a lane whose holder has gone away, and says whose it was |
| everything that touches the emulator | `start`, `stop`, `key`, `send`, `front` and `roms` refuse a caller who is not the holder |

**The claim is a create, not a read-then-write**, and the difference was
measured rather than reasoned about. Six `claim` calls released at the same
instant against the first version — which read the lane, found it free, and
wrote — granted the lane to **all six** in two rounds of three, and one of
those rounds ended with no claim file at all, because `Set-Content` collided
with itself: *"Set-Content : Stream was not readable"*. That is the belief this
whole page exists to destroy, in the mechanism built to prevent it.

What replaced it is one atomic NTFS create — `[IO.File]::Open` with
`CreateNew` — followed by reading the file back and confirming this call's own
token is in it. So **when `claim` prints ok, the file on disk carries that
call's token**, and two callers cannot both see that. Eight rounds of six
simultaneous claims since: exactly one holder, every time.

Two things it does not promise, said here rather than left to be discovered:
two callers both passing `-Override` can take the lane from each other, because
a steal deletes and re-creates and both are entitled to; and a claim file that
is present but unreadable is refused rather than assumed free — the first
version assumed free, and the losers of a race then deleted the winner's claim
and took the lane, which granted 2, 2 and 3 holders of six across five rounds
even after the create was made atomic.

**A holder re-asserting a lane it already holds touches nothing at all**, and
that is the third thing this had to be taught. Re-claiming used to delete the
file and write it again, and for the couple of milliseconds in between the lane
read plainly *free* — not held, not unreadable — so another holder's `CreateNew`
landing in there won it **without `-Override`**, and its success line did not
even say it had taken anything, because what it read was an empty lane. A
holder retrying a claim whose ssh reply was lost is an ordinary thing to do.
Now the call reports `ok claimed by <id> (already yours since …)` and writes
nothing, which removes the window rather than narrowing it.

**A claim file that is present, has no `holder` line, and was last written
before this boot is treated as stale.** `Try-TakeClaim` writes `boot` before
`holder`, so a process killed between the two — an ssh drop takes the child
PowerShell's whole tree, which is how this guest fails — leaves a wreck that
would otherwise be `unreadable` for ever, refusing every command until a person
passed `-Override`. The clock settles it: nothing written before this boot can
be a write in flight now, and §1.1's promise that a claim cannot outlive its
boot holds for the wreckage too.

**Every refusal says how to get unstuck.** An agent whose predecessor died
without releasing would otherwise read only "claimed by dead-agent since 09:14"
and have a lock nothing tells it how to clear, so each refusal carries the
`-Override` line that clears it.

Two checks sit under the claim, because a claim only binds a caller who passes
`-Holder`:

* **`start` verifies what it launched.** After the task starts, it compares the
  running `winuae64`'s command line with the one this call passed, and refuses
  a process that started before the call did. That is what turns the hijack
  into an error: `fail winuae64 pid=1568 is running a command line this call
  did not pass`, quoting both.
* **`start` writes a receipt** — `C:\Amiga\winuae-run.txt`, holding the pid, its
  start time, the arguments and the holder — and `stop`, `key`, `send` and
  `front` refuse a `winuae64` that is not the one in it. `stop -Override` ends
  it anyway and says what it is overriding.
* **`send` refuses a `-TargetPid` that is not this lane's emulator.** It used to
  prefer a caller's own `-TargetPid` over the pid the ownership check had just
  proved, which walked straight past that check into whatever console the given
  pid owns. It was inert only because a *different* check refuses two
  emulators.

The claim is a file in the guest, `C:\Amiga\winuae-claim.txt`, and it records
the boot it was taken in: a claim cannot outlive a restart, because every
emulator and every run in flight died with it. Nothing in the guest can see
whether the *Linux* process that took a claim is still alive, so a claim left
behind by an agent that died is taken with `-Override`, deliberately, by
somebody who has looked.

**`-Holder` and `-Override` are read out of the remaining arguments rather than
declared as parameters**, and that is worth knowing before editing the script.
PowerShell fills a positional parameter *before* a
`ValueFromRemainingArguments` one, wherever each is declared and whatever
`Position` each is given: measured, with `-Holder` at `Position=99` and `$Rest`
at `Position=1`, `winuae.ps1 key 7A` bound `cmd=[key] holder=[7A] rest=[]` and
the keypress was refused for having no VK code.

`tools/winuae-lanecheck.ps1` is the proof, and it runs against whichever copy
of the driver it is pointed at, so an older one can be watched to fail.
Measured 2026-09-01; the round count is per row, because the rare ones need
more of them:

| scenario | before | after |
|---|---|---|
| `stop` from a second driver ends the first's emulator | 3 of 3 | 0 of 3 |
| `key` from a second driver presses into the first's game | 3 of 3 | 0 of 3 |
| `start` reports the neighbour's emulator as its own success | 7 of 9 | 0 of 9 |
| six simultaneous `claim`s grant more than one holder | 2 of 3 rounds, all six granted | 0 of 8 rounds |
| a second holder takes a lane while its holder re-asserts it | 4 of 4 rounds, with the window widened | 0 of 4 rounds, widened and not |
| `send` obeys a `-TargetPid` that is not the lane's emulator | yes | refused |
| the holder's own `start`, `key`, `send` and `stop` still work | works | works |

**The hijack rounds say whether they actually raced**, and that is not a
detail: it needs two `start` calls to overlap inside the second WinUAE takes to
become a process, so a round that never reached that condition proves nothing
and must not read as a pass. The check starts the intruder the instant the
task's `LastRunTime` moves, samples for the intruder's config while the other
call is still running, prints `N of R rounds actually raced`, and fails outright
when that is none. Both runs above raced 8 or 9 rounds of 9.

Its verdict is about **the pid the second call reported**, not about whatever is
running when the round ends. Asking the second question failed a round against
the *fixed* driver, where the second call had verified its own emulator and
returned, and the intruder replaced it afterwards — a real thing, but a
different one, and nothing `start` can prevent once it has returned. The run
receipt is what refuses that caller's next command, and the check now says so on
its own line rather than counting it either way.

Windows Update is disabled in the guest. It is never going to be patched, and
left on it wrote a 16 GB overlay in 25 minutes of uptime — update payloads and a
6 GB pagefile — all of which then has to be merged on `winvm promote`.

## 2. The VM resets in one second, and that shapes how you use it

The VM's disk is two files, and knowing which is which is the difference
between losing an afternoon's work and not caring that you did.

```
win11-golden.qcow2   28G     frozen baseline. Never written to.
win11.qcow2         ~200K    what the VM runs from: only what has CHANGED.
                             backing file: win11-golden.qcow2
```

qcow2 lets one disk declare another as its **backing file**. Reads the overlay
does not have fall through to golden; writes only ever land in the overlay. So
the running VM sees a complete Windows while the overlay holds nothing but the
diff.

| command | what it does | cost |
|---|---|---|
| `winvm revert` | delete the overlay, make a new empty one, restore the UEFI varstore | ~1 second |
| `winvm promote` | fold the overlay into golden — the current state becomes the new baseline | seconds |

**`winvm` has no answer for a `paused` domain**, and one turns up whenever
Donald has looked at the VM himself and left it. Measured on a domain paused
from his desktop with no lease held:

* `winvm up`, and so `winvm acquire`, dies on `error: Domain is already
  active` — `up` special-cases only `running`, and `virsh start` refuses an
  active domain. `acquire` writes its lease file *before* calling `up`, so the
  failed acquire leaves a lease nobody holds.
* `winvm down` prints `down` and does nothing: both its `shutdown` and its
  `destroy` are guarded on the state being `running`.
* `winvm promote` is guarded the same way, so on a paused domain it would
  `qemu-img commit` the overlay of a **live** QEMU into golden. That is the
  dangerous one.

`virsh -c qemu:///system resume win11` first, then `winvm down` and the rest
behave normally.

**`winvm ssh` does not pass `-o BatchMode=yes`**, so it can put a credential
dialog on the host's desktop — §1. It is `winvm`'s fault and not ours, but ours
is the side that can stop triggering it: export `SSH_ASKPASS_REQUIRE=never`.

**This is not a backup.** Both files sit on the same NVMe; if the disk dies they
die together. It is the opposite of a backup: machinery for throwing work away
cheaply. That is what makes it safe to point a debugger at an unknown binary,
let a game trash itself, or install something dubious — `winvm revert` and the
machine is clean again, without the 25-minute Windows install.

The consequence for daily use: **decide whether a file should survive a
revert.** Memory dumps, save files, WinUAE configs and throwaway test binaries
should not — they live in the overlay and are meant to evaporate. Game disks and
tools you will want in every future session should, which means copying them in
and then running `winvm promote` once.

**Run `winuae.ps1 stop`, then `clean`, before promoting.** Scheduled tasks
outlive the run that registered them, and a promote would weld this document's
scaffolding into the baseline of every future session. `clean` unregisters the
four task names and removes the receipt, `send.log` and `console.txt`.

**`clean` refuses while the emulator is running, and that is safety rather than
tidiness.** Unregistering `winuae-run` does not stop a `winuae64` that task
already launched, and with the definition gone `stop` has nothing to stop:
measured, `Stop-ScheduledTask` on an unregistered name returns `$? = False`,
prints nothing and throws nothing. `stop` would then report "still running"
for ever, and the only route left would be a kill by name — which this project
forbids, and which has already killed the wrong window once.

`winvm revert` also restores `win11_VARS.golden.fd` over the UEFI varstore.
Reverting the disk alone can leave a firmware boot entry pointing at an EFI
partition that no longer matches, and the VM then boots to a firmware menu.

## 3. Copying files in and out

The guest runs OpenSSH with your key already authorised, so this is ordinary
`scp`. Copying the 27 Gold Box disk images (16.6 MB) took 13 seconds.

```sh
scp build/wish-snapshot.exe donald@192.168.123.50:'C:/Amiga/'
scp -r ~/roms/amiga/Curse_Of_The_Azure_Bonds donald@192.168.123.50:'C:/Amiga/Disks/'
scp donald@192.168.123.50:'C:/Amiga/dump/party.bin' /tmp/     # and back out
```

Forward slashes in the remote path. Quote it, because `C:` before a path would
otherwise look like a host name to `scp`.

**A one-off build to test by hand needs nothing else.** Copy it, run it, and
when you are finished `winvm revert` removes it along with everything else it
touched — registry keys, temp files, whatever it installed. That is the
intended workflow for a throwaway: **do not promote it.** Promoting would weld
a snapshot build into the baseline of every future session.

```sh
scp build/wish-snapshot.exe donald@192.168.123.50:'C:/Users/donald/Desktop/'
# ... test it through the SPICE console in virt-manager ...
winvm revert          # gone, and so is anything it changed
```

Two things worth knowing:

* `scp` works even though the guest's SSH default shell is PowerShell. Modern
  `scp` transfers over the SFTP subsystem, which does not invoke a shell.
  Anything that *does* run a shell command sees PowerShell.
* **`winvm ssh` and `winvm up` must not be run under `sudo`.** They shell out to
  `ssh`, and under sudo that runs as root, which has none of your keys — `winvm
  up` then waits for a readiness check that can never pass. Run `winvm` as
  yourself; it needs the `libvirt` group, not root.

## 4. There is no GDB server. Do not go looking for one.

`uae-dap` and `vscode-amiga-debug` both drive WinUAE over the GDB remote serial
protocol, which makes it look as though a socket exists. **It does not exist in
stock WinUAE.** Both projects ship *patched* binaries.

Checked against WinUAE master:

* `debug.cpp` is 9,527 lines and contains **zero** occurrences of `gdb`.
* `cfgfile.cpp` accepts `debugging_features`, and its permitted values are the
  whole of `static const TCHAR *debugfeatures[] = { _T("segtracker"),
  _T("fsdebug"), 0 };` — no `gdbserver` among them.
* The debugger's input comes from `console_get(input, MAX_LINEWIDTH)`
  (`debug.cpp:7903`). A console read. No listener, no command file.

So either build a patched WinUAE and get a socket, or drive the console. This
document drives the console, because a patched emulator is a second thing to
maintain and the console turns out to be enough.

## 5. Starting a game unattended

Two command-line switches carry everything (`main.cpp:1023` and `:1035`):

| switch | effect |
|---|---|
| `-f <config>` | load a `.uae` configuration file |
| `-s <key>=<value>` | set one configuration line, exactly as it would appear in the file |
| `-log` | allocate a console and log to it |

`-s` is the important one: **any** config key can be overridden from the command
line, so one committed `.uae` file plus a few `-s` flags covers every run and
nothing has to be rewritten per test. An empty value ejects: `-s floppy0=`.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Amiga\winuae.ps1 start -log `
    -f C:\Amiga\configs\goldbox-a500.uae `
    -s floppy0=C:\Amiga\Disks\Curse_Of_The_Azure_Bonds\CurseOfTheAzureBonds_A.adf
```

**`use_gui=no` in the config is what makes an unattended run possible.** Without
it WinUAE opens its settings dialog and waits for a human; with it, emulation
starts on the first instruction.

**`floppy_speed=800`.** At the real 100, Curse of the Azure Bonds was still a
blank white screen 35 seconds in, with only the drive track counters moving to
say it was alive — and a blank white screen is also what Kickstart 1.3's
insert-disk hand sits on, so anything watching by screenshot cannot tell
loading from failure. At 800 the title is up inside 45 seconds.

**The ADFs on this machine are cracked releases**, and that is what makes an
unattended boot possible at all. Curse runs straight from its title art to
`CRACKED BY SKID ROW/VALHALLA!` and then the game's own PLAY / DEMO / TRANSFER /
QUIT menu; an original disk would stop for a code-wheel question with nobody
there to answer it.

**`C:\Users\Public\Documents\Amiga Files\WinUAE\winuaebootlog.txt` is the
first place to look when a run misbehaves.** It records which config loaded,
the Kickstart version (`KS ver = 34 (0x22)` for 1.3), and every rejected line as
`unknown config entry: '...'`. That is how `win32.active_nocapture_pause` was
found not to exist.

### `use_debugger=true` does not work on Windows. Do not use it.

`cfgfile.cpp:3774` really does parse `use_debugger` into
`currprefs.start_debugger`, and `main.cpp:1306` really does read it:

```c
if (currprefs.start_debugger && debuggable ())
    activate_debugger ();
```

But the Windows port defines the second half as a hard zero, with no `#ifdef`
around it:

```c
// od-win32/win32.cpp:3777
int debuggable (void)
{
    return 0;
}
```

So `-s use_debugger=true` and `-D` set a flag nothing ever reads. It is worse
than a no-op: with `-log` it floods the console with `Denise queue without
lock! id=1`, thousands of lines, which scrolls the 5000-line buffer clean and
starves emulation badly enough that Curse never reached its title screen in six
minutes.

### The way in is an input event

The only surviving caller of `activate_debugger()` is `AKS_ENTERDEBUGGER`,
reached from the input event `SPC_ENTERDEBUGGER` (`inputevents.def:371`,
"Activate the built-in debugger"). **It has no default binding.** Five config
lines give it one, and `tools/goldbox-a500.uae` carries them:

```
input.config=1
input.1.keyboard.0.friendlyname=WinUAE keyboard
input.1.keyboard.0.name=NULLKEYBOARD
input.1.keyboard.0.empty=false
input.1.keyboard.0.button.87.0=SPC_ENTERDEBUGGER
```

87 is `DIK_F11`. Pressing it must be a real key at the driver level —
`keybd_event` after `SetForegroundWindow`, from session 1; `PostMessage` does
not reach DirectInput. `winuae.ps1 key 7A` does both.

`activate_debugger()` carries one more guard worth knowing before designing
anything headless:

```c
if (!is_interactive_console() || isfullscreen () > 0) return;
```

**The debugger cannot be entered while WinUAE is fullscreen.** Keep
`gfx_fullscreen_amiga=false`.

**There is no window-level sign that the debugger is up.** With the emulation
thread held at the `>` prompt, `Get-Process winuae64` still reported
`Responding = True`, and `winvm shot` still showed the title bar reading
`[goldbox-a500.uae] - WinUAE` — no `(Not Responding)`. The receipt for F11 is
the prompt itself, in what §6's console readback returns.

## 6. Getting output back without reading the screen

This is the whole trick, and it is the same one `tools/dosboxx.py` uses for
DOSBox-X's `MEMDUMP.BIN`.

```
S <file> <addr> <n>    Save a block of Amiga memory.
L <file> <addr> [<n>]  Load a block of Amiga memory.
```

`S` writes memory straight to a **host file**. So a memory read is not a screen
scrape and never has been: issue `S`, then read the bytes off the filesystem.
That is what makes a `Target` possible at all.

```
S C:\Amiga\dump\party.bin 200000 200
```

Then, from Linux:

```sh
scp donald@192.168.123.50:C:/Amiga/dump/party.bin /tmp/
```

**The path must be absolute.** A relative one is not resolved against the
process working directory: `S t2.bin 40000 10`, run with the working directory
set to `C:\Amiga`, reported success and wrote to
`C:\Users\Public\Documents\Amiga Files\WinUAE\t2.bin` — WinUAE's data path.

`m <address> [<lines>]` also dumps memory, but to the console as formatted hex.
Use it when a human is looking.

Parsing it is not unreasonable, though, because **the console can be read back
as text rather than scraped as pixels**: `ReadConsoleOutputCharacter` over the
attached screen buffer returns the debugger's own output — register dumps, `m`
hex, the `>` prompt. `tools/winuae-send.ps1` does it after every batch. The
buffer is 120x5000; read the tail around the cursor, because marshalling all
600,000 characters is slow enough to notice.

## 7. Getting commands *in*

Solved, by §7's option 1. `tools/winuae-send.ps1` is the implementation.

The debugger reads from WinUAE's console with `ReadConsole` one character at a
time, in line mode (`writelog.cpp`, `console_get`). So `AttachConsole` to the
emulator and `WriteConsoleInput` key events into its input buffer, and the
debugger reads them as typing. It needs no window focus, which is what makes it
safe to run while somebody is using the desktop.

The proof, on a running Curse of the Azure Bonds:

```
>W 40000 ba 5e ba 11 c0 ff ee 5a
Wrote BA (186) at 00040000.B   ... eight lines ...
>S C:\Amiga\dump\readpath2.bin 40000 10
Wrote 00040000 - 0004000F (16 bytes) to 'C:\Amiga\dump\readpath2.bin'.
>m 40000 1
00040000 BA5E BA11 C0FF EE5A FC0E 3215 FFFF FEFF  .^.....Z..2.....
>g
```

`xxd` of that file on Linux: `ba5e ba11 c0ff ee5a fc0e 3215 ffff feff` — the
first eight bytes the pattern, the last eight whatever the game had there, and
identical to what `m` printed. That is `WinuaeTarget.read` and `.write`
demonstrated rather than costed.

**`g` really resumes, and the way to prove it is a second halt.** The Amiga
screen can sit on one frame for minutes at a time, so a screenshot proves
nothing; a second `F11` does. Across two halts the CPU was parked in the same
Kickstart idle instruction — `00fc0f90 stop #$2000`, which is why `CPU: 0%` is
normal and not a sign of a wedge — while `VPOS` had moved from 104 to 208. The
beam had run; the emulator had run.

Six traps, each of which reads as "the route does not work":

1. **The debugger needs a console, and `use_debugger=true` does not make one.**
   `AttachConsole` then fails with `GetLastError 5`. `-log` makes WinUAE call
   `AllocConsole()`, and that is the console the debugger later uses.
2. **`-console` does not *create* a console** — it tells WinUAE it was launched
   from one. Launching via `cmd.exe` so WinUAE inherits cmd's console does not
   work either: WinUAE frees it, `AttachConsole` fails, and the cmd console
   stays empty. It also orphans the emulator, because `cmd /c` returns
   immediately for a GUI app, so `Stop-ScheduledTask` kills only cmd.
3. **`AttachConsole` cannot cross sessions** — `GetLastError 203` from an SSH
   shell, every time. §1.
4. **PowerShell drops writes to a struct inside a typed array.**
   `$recs[$i].EventType = 1` sets the field on a boxed *copy*; the array keeps
   two zeroed `INPUT_RECORD`s, `WriteConsoleInput` returns success, the console
   discards them, `GetNumberOfConsoleInputEvents` reports nothing pending, and
   not one character appears at the prompt. Build the struct in a local and
   assign the whole thing.
5. **A scheduled task started while its own last instance is still alive does
   not run, and the caller reads that instance's receipt as its own.** Task
   Scheduler's `MultipleInstances` defaults to `IgnoreNew` and there is nothing
   else to ask for — `New-ScheduledTaskSettingsSet`'s enum offers only
   `Parallel`, `Queue` and `IgnoreNew`, with no `StopExisting`. Nor does
   `Register-ScheduledTask -Force` end the running instance. Measured: caller A's
   helper was still sleeping, caller B re-registered, started, and after 12.3 s
   read `ok gen=A` as the answer to a call that never ran. So `winuae.ps1` calls
   `Stop-ScheduledTask` before every `Start-ScheduledTask`, and stamps each call
   with a token the helper echoes — a receipt without this call's own token is
   somebody else's, or half-written, and is ignored either way.
6. **A helper can die without writing its verdict, and waiting out the timeout
   is the wrong way to find out.** Measured on a `send` given neither `-File`
   nor `-DumpOnly`: `send.log` reached `CONIN opened` and stopped there, the
   task went back to `Ready` with `LastTaskResult = 1`, and the caller sat for
   the full timeout. Watching the task state as well as the log turns that into
   a five-second failure that quotes how far the injector actually got.

The rejected alternative was **`SendKeys` after `AppActivate`**: simpler, and
fragile in exactly the way that matters, since it depends on window focus.

**Every action says what it actually achieved, and exits non-zero when it did
not.** `Start-ScheduledTask` on an `Interactive` principal returns success and
runs nothing at all when nobody is logged on at the console — measured, with
session 1 logged off: `LastTaskResult = 0x41303`, `LastRunTime = 11/30/1999`,
and the task never leaves `Ready`. That is the silent failure that costs most
here, because a `key` reporting "pressed" leaves the debugger closed, `send`
then types into a console that was never created, and the run looks fine until
somebody reads the empty dumps hours later.

So each session 1 helper writes a one-line receipt — `ok raised pid=... hwnd=...`
or `fail ...` — that `winuae.ps1` waits for, and `winuae-send.ps1` ends every
path with `--- exit N token=...`. Both carry the caller's own token, for the
reason in trap 5. When no receipt arrives the caller reports the scheduler's own
reason rather than guessing.

**A malformed call fails in milliseconds, not at the end of a timeout.**
`winuae-send.ps1` checks its arguments before it touches a console, because the
alternative is not an error message: with `$File` empty, `Get-Content -Path ''`
is merely a *non-terminating* error in an ordinary console and the script walks
straight past it — but in session 1, attached to WinUAE's console, the same
statement killed the process outright, and neither outcome ever wrote `--- exit`.
That is the hang-rather-than-fail class, and it is the one that matters most for
anything running unattended.

A failed `WriteConsoleInput` **falls through to the console readback** rather
than exiting on the spot. The run that most needs the debugger's own words is
the one where the injection went wrong, and returning early there was the only
way to lose them.

One hazard is already handled: Windows consoles ship with **QuickEdit** on, and
a single click inside one puts the console in selection mode, which *blocks the
writing process indefinitely*. A stray click while someone watches the VM would
wedge a run with no error anywhere. The VM's `guest-setup.ps1` disables
QuickEdit for this reason. Do not turn it back on.

## 8. The commands that matter

From `debug.cpp`'s own help text.

| command | what it does |
|---|---|
| `g [<address>]` | run, from here or from `<address>` |
| `t [n]` | step one or more instructions |
| `z` | step *over* a `JSR`/`DBRA` |
| `r` | dump the CPU; `r <reg> <value>` modifies one |
| `m <addr> [<lines>]` | memory dump, to the console |
| `d <addr> [<lines>]` | disassemble |
| `S <file> <addr> <n>` | **save memory to a host file** |
| `W <addr> <values>` | write memory; `W <addr> 'string'` for text |
| `f <addr>` | add/remove a breakpoint; `fl` lists, `fd` removes all |
| `fo <n> <reg> <oper> <val>` | conditional register breakpoint |
| `w <num> <addr> <len> <R/W/I> <F/C/L/N>` | memory watchpoint |
| `s "<string>"/<values> [<addr>] [<end>]` | search memory |
| `C <value>` | trainer search — see §9 |
| `Cl` | list the addresses a trainer search has narrowed to |
| `D[idxzs]` | deep trainer: refine by larger/smaller/same/different |
| `T` | exec tasks and their PCs |
| `x` | close the debugger (the emulator keeps running) |
| `q` | quit the emulator — do not |

## 9. Finding an address in a running game

This is the part that matters for reverse-engineering, and WinUAE is unusually
well equipped for it: `C` and `D` are a built-in **trainer search**, which is
precisely the "find where hit points live" problem.

The loop is the classic one, and it needs no prior knowledge of the layout:

```
C 55            (the fighter has 55 hit points)
g               (let the game run; take a hit)
D d             (deep search: the value must now be SMALLER)
g               (heal)
D i             (must now be LARGER)
Cl              (list what survived)
```

Each `D` intersects the candidate set with the constraint. Three or four rounds
usually leaves a handful of addresses; `w` a watchpoint on each and the writer
identifies itself.

That is a better first move than disassembling, and it is how a C64 address in
`docs/40-memory-map.md` would have been found if VICE had the feature.

**The Amiga is not the C64 and the addresses do not carry over.** Nothing in
`goldbox/games.py` applies: different CPU, different memory map, relocatable
hunks. `goldbox/amiga.py` decodes the *save record*, which is a file format and
title-independent; a live address is neither.

## 10. Fitting it to `automap`

`automap/target.py` fixes the contract at two methods, deliberately:

```python
class Target(Protocol):
    def read(self, addr: int, length: int) -> bytes: ...
    def write(self, addr: int, data: bytes) -> None: ...
```

A `WinuaeTarget` implements `read` as *issue `S`, read the file back* and
`write` as `W`. Breakpoints and stepping stay out, exactly as they stayed out
for the Commodore 64 Ultimate backend — a second backend should not have to
pretend it has them.

Two differences from `ViceTarget` that a design should account for:

* **The round trip is a file, not a socket.** `ViceTarget` measured ~14.3 ms of
  extra emulated time per `resume()` and concluded *batch reads, keep resumes
  rare*. Here the cost is a console write plus a file read plus an `scp`, which
  is far worse. Batching is not an optimisation; it is the design. Read one
  large block, not several small ones.
* **The debugger stops the machine.** Entering it halts emulation until `g`.
  `ViceTarget`'s polling model — read, resume, repeat — maps onto that, but the
  distortion per poll will need measuring against the Amiga's own timers before
  any claim is made about how fast the game runs while a map is open.

Nothing in `automap/screen.py`, `render.py` or `state.py` is VICE-specific, but
`screen.py` *is* C64-specific: it reads a 40x25 text screen out of a fixed
place. The Amiga has no such thing, and a status line will have to be found
another way — likely OCR off `winvm shot`, or the position triple direct from
memory once §9 has located it.

## 11. What was checked, and what was not

**Checked against WinUAE master source, 2026-08-25:**

* no `gdb` anywhere in `debug.cpp` (9,527 lines); `debugging_features` is
  `segtracker` or `fsdebug` only
* debugger input is `console_get` — no socket, no command file
* `-f` and `-s` are real switches, and `-s` sets any config line
* `od-win32/win32.cpp:3777` is `int debuggable (void) { return 0; }`, so
  `use_debugger=true` cannot start the debugger on Windows — §5
* `activate_debugger()` returns early unless `is_interactive_console()` and not
  fullscreen — §5
* `SPC_ENTERDEBUGGER` (`inputevents.def:371`) is the only remaining caller, and
  nothing binds it by default
* the command table in §8, and `S`/`L`/`C`/`D`/`w`, are quoted from the
  debugger's own help text

**Checked on the VM itself, 2026-08-25:**

* the VM is up and `ssh donald@192.168.123.50` works with key auth, which is
  what `winvm ssh` rides on
* `WinUAE 64-bit 6.0.3` is installed, and the binary is **`winuae64.exe`**
* all fourteen Kickstart ROMs are in `C:\Amiga\Kickstarts`; the Curse and
  Silver Blades ADFs and the Pool of Radiance and Pools of Darkness zips are in
  `C:\Amiga\Disks`
* `C:\Amiga\Kickstarts` and `C:\Program Files\WinUAE` are both in
  `(Get-MpPreference).ExclusionPath`
* the guest clock agrees with the host to the minute
* console QuickEdit is off
* the guest's execution policy is `Undefined` in every scope, so every script
  here needs `-ExecutionPolicy Bypass` — §1
* **`winvm ssh` runs in session 0 and the VM's screen is session 1** — §1
* **Curse of the Azure Bonds boots to its title screen unattended** from
  `winuae64.exe -f C:\Amiga\configs\goldbox-a500.uae`, verified by
  `winvm shot`; the ADFs are cracked releases, which is why nothing stops for
  the code wheel — §5
* **F11 opens the debugger** with the binding in §5, and `g` resumes into the
  game's own menu
* **`AttachConsole` + `WriteConsoleInput` drives it**, and
  `ReadConsoleOutputCharacter` reads the replies back — §7
* **`S <file> <addr> <n>` writes a host file**, and the bytes survive `scp` to
  Linux unchanged: `W 40000 ba 5e ba 11 c0 ff ee 5a` then `S` then `scp` gave
  `ba5e ba11 c0ff ee5a fc0e 3215 ffff feff`, matching what `m 40000 1` printed
  — §7. Re-run after every change to the driver scripts: six runs now, six
  different patterns. The trailing eight bytes are the game's, and two runs
  halted at the same point in the load returned the same `f1e0 0000 235b f9e3`
  from different sessions — a free check that this is live memory rather than
  an echo of the write
* **`g` resumes, proved by halting again**: `VPOS` moved from 104 to 208 between
  two `F11` halts, with the CPU parked in the Kickstart's `stop #$2000` both
  times — §7
* **a relative path in `S` resolves against WinUAE's data path**, not the
  process working directory — §6
* **the ROM scan can be driven with no GUI**: `KickstartPath` set and
  `DetectedROMs` deleted, one `use_gui=no` run rebuilds the database from 5
  pseudo-ROM entries to 14 — §1. Proved by screenshot: the "system ROMs is
  required" dialog before, the Quickstart panel reading `A500` / `1.3 ROM, OCS`
  after
* **an `Interactive` scheduled task started with nobody logged on at the
  console silently does not run** — `LastTaskResult = 0x41303` — §7
* **`MultipleInstances` defaults to `IgnoreNew`, `Register-ScheduledTask -Force`
  does not end a running instance, and there is no `StopExisting` to ask for.**
  A caller starting a task whose last instance is still alive read that
  instance's receipt as its own after 12.3 s — §7, trap 5
* **`Stop-ScheduledTask` on an unregistered task name is a silent no-op**:
  `$? = False`, nothing printed, nothing thrown. That is what would strand an
  emulator if `clean` ran before `stop` — §2
* **`winuae-send.ps1` given neither `-File` nor `-DumpOnly` died at
  `CONIN opened` without writing `--- exit`**, and the caller waited out its
  whole timeout. Guarded now, and the guard was watched to fail: rc 6 in 2.9 s
  with the guard, no verdict at all without it — §7, trap 6
* **the debugger does not make the window stop responding.** At the `>` prompt
  `Responding` was still `True` and the title bar unchanged — §5 said otherwise
  and was wrong
* the configuration, the two driver scripts and the ROM database survive
  `winvm revert`, having been folded into golden with `winvm promote`. Golden's
  copy of `winuae.ps1` is now the pre-`#116 (Two agents cannot share the WinUAE
  VM, and neither of them can tell)` one and no longer matches `tools/` — see
  the 2026-09-01 block below
* **`front`, `key` and `send` refuse two emulators, and `roms` refuses one.**
  Watched to bite against a second `winuae64` started on purpose and stopped by
  its own pid: all three reported `fail 2 winuae64 processes: 1244,3652; stop
  all but one` with rc 1, and `roms` reported `fail winuae64 running pid=...;
  roms starts its own, stop this one first` for each — §1
* **a backtick inside the `$Preamble` here-string is an escape, not a
  character.** `` `roms` `` in a comment there emitted a carriage return,
  PowerShell read it as a line ending, and the rest of the comment became a
  command — parsing clean and failing only in the branch it was written for.
  Double every backtick in that here-string
* **`send` can die part-way through a batch**, once in seven runs: PowerShell's
  own host reported `The handle is invalid` 0x6 into the attached console and
  the injector stopped, leaving the emulator halted with two lines of the batch
  unsent. The caller's no-verdict guard reported it in five seconds rather than
  waiting out the timeout. Not diagnosed —
  `#95 (A WinUAE debugger batch can stop half-way through and leave the
  emulator halted)`

**Checked on the VM itself, 2026-09-01**, for `#116 (Two agents cannot share
the WinUAE VM, and neither of them can tell)`:

* **`Register-ScheduledTask -Force` DOES replace a running task's action here,
  and `#116 (Two agents cannot share the WinUAE VM, and neither of them can
  tell)` says it does not.** Three of three `-Force` registrations over a
  `winuae-run` instance that was running an emulator left
  `Actions.Arguments` reading the arguments just passed, not the earlier ones.
  So the hijack that issue describes is not a scheduler quirk: it is two
  drivers of one task overlapping, and the fix has to be ownership rather than
  a workaround for `-Force`. The read-back check in `Register-Session1Task`
  stays, because it costs three lines and it is what would catch a Windows
  build that does behave the reported way
* **re-registering the task detaches the instance it had running.** After a
  `-Force` register, `(Get-ScheduledTask winuae-run).State` read `Ready` while
  the emulator that task launched was still alive — so the task's state is not
  a reliable answer to "is my emulator running". `Stop-ScheduledTask` still
  ended the process, 1.8 s later
* the guards in 1.1, before and after — the table there
* **a read-then-write claim is not a claim.** Six `claim` calls released at one
  instant against the first version granted the lane to all six in two rounds of
  three, and one of those rounds ended with no claim file at all, `Set-Content`
  having collided with itself. An atomic `CreateNew` alone still granted two and
  three holders of six, because a loser reading the winner's half-written file
  saw no claim and deleted it; create-then-confirm-the-token gives exactly one
  holder, 8 rounds of 8
* **the re-claim window cannot be hit by chance, and had to be widened to be
  seen at all.** Storming the committed driver with a holder re-asserting its
  lane while three others claimed — 198 attempts over four rounds — produced no
  intrusion; the gap between its `Remove-Item` and its `CreateNew` is a couple
  of milliseconds and a fresh `powershell.exe` takes longer than that to reach
  its first `Test-Path`. With a `Start-Sleep -Milliseconds 200` inserted in that
  gap in a copy, the same storm let another holder in **five times in twelve
  seconds**, with no `-Override` anywhere. The same 200 ms in the same place in
  the fixed driver: no intrusion in four rounds and 228 attempts
* **the storm only works because the callers jitter.** Without it every job runs
  the same length of cycle from the same starting instant, so the other
  holders' reads keep landing in the same phase of the holder's — always after
  its write, never in the gap. Measured: 131 attempts against the widened copy,
  not one intrusion; with `Start-Sleep -Milliseconds (Get-Random 0 400)`, five
* **`[IO.File]::Replace` cannot take `$null` for its backup path from
  PowerShell.** The first attempt at a windowless re-claim wrote a temporary
  file and renamed it over the claim; it never once worked. PowerShell turns
  the `$null` argument into an empty string and Replace answers *"The path is
  not of a legal form"*, so every re-claim failed — and reported "the lane was
  taken by \<yourself\> while this call was running". Caught by the scenario
  that was written for the window itself, which counted the holder's own
  re-assertions and found zero
* **`send` obeyed a caller-supplied `-TargetPid`** over the pid its own
  ownership check had just proved. Refused now, and watched: `fail send was
  given -TargetPid 8272, but this lane's emulator is pid=6136`, with the lane's
  own console read-back still returning `--- exit 0`. A *duplicated*
  `-TargetPid` is now refused outright rather than depending on which of the two
  `winuae-send.ps1`'s binder would take — `-match` reads only the first
* **`@($null).Count` is 1**, so `winuae.ps1 stop` with no other arguments walked
  into "Cannot index into a null array" the first time the argument scan was
  written against `@($Rest)`
* **a function's array return is unrolled**, so `(Emulators).Count` on a single
  emulator asks a `CimInstance` for a property it has not got and gets `$null`.
  `,@(...)` fixes the one-element case and breaks the empty one; `@()` at the
  call site is the only form right at 0, 1 and n. It reported "A's emulator did
  not start" about an emulator that had
* **golden still carries the pre-`#116 (Two agents cannot share the WinUAE VM,
  and neither of them can tell)` `winuae.ps1`.** The fixed copy was deployed
  into the running guest's overlay and not promoted, so it does not survive
  `winvm revert`, and the 2026-08-25 line above about golden's copies hashing
  equal to `tools/` is no longer true. `scp tools/winuae.ps1
  donald@192.168.123.50:'C:/Amiga/'` after any revert, and promote deliberately
  when the overlay holds nothing else you would not want in the baseline

**Not checked, and needing a session at the machine:**

* the §9 trainer loop against a real Gold Box title — `C`, `D` and `Cl` have
  not been run
* watchpoints and breakpoints (`w`, `f`, `fo`) — nothing beyond `W`, `S`, `m`
  and `g` has been exercised
* how far the game runs *behind* a debugger halt, which §10 says must be
  measured before any claim about live automapping
* `front`, `key` and `send` have been exercised only against a *running*
  emulator and against *no session 1 logon*. A locked session 1 — where the
  task runs but `SetForegroundWindow` cannot succeed — has not been tried, and
  it is the case `front`'s `foreground=` receipt exists for
* whether the `092%` that Curse's loader prints to the console for minutes on
  end is the cracked release waiting for something or an emulation fault. The
  game keeps running behind it — memory reads and `g` both work — so it has not
  been chased
* anything at all about *Pools of Darkness*, *Pool of Radiance* or *Secret of
  the Silver Blades* specifically — only Curse has been booted, and the Pool
  of Radiance and Pools of Darkness images in the guest are still `.zip`

§1 to §8 are reliable. §9 and §10 are a plan.
