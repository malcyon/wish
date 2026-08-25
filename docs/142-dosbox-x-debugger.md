# DOSBox-X's debugger, driven by a script

The DOS side now has what the C64 side has had all along: memory reads,
watchpoints, breakpoints, registers and single-stepping on a running game.
**It can be driven unattended.** The debugger is an ncurses program with no
socket and no command file, but its input is the process's own terminal and its
output goes to a host log file, so a pty on one end and a log tail on the other
make it scriptable — the same shape as `tools/dosbox.py`'s keystrokes-in,
files-out, and nothing here is read off the screen.

`tools/dosbox.py`'s three primitives still stand for driving the *game*. This
document adds a fourth: the emulator will tell you what it is doing.

## What is installed

**DOSBox-X 2026.08.02, built from source with the debugger enabled, at
`/usr/local/bin/dosbox-x`.** The build was:

```sh
curl -L -o dosbox-x.tar.gz \
  https://github.com/joncampbell123/dosbox-x/archive/refs/tags/dosbox-x-v2026.08.02.tar.gz
sudo apt-get build-dep dosbox-x        # before the package was purged
sudo apt-get install libncurses-dev
cd dosbox-x-dosbox-x-v2026.08.02
./build-debug-sdl2 --prefix=/usr/local # = ./configure --enable-debug=heavy --enable-sdl2
sudo make install
```

`--enable-debug=heavy` is the load-bearing flag: plain `--enable-debug` compiles
the debugger but `#if C_HEAVY_DEBUG` guards `BPM`, and a watchpoint is the whole
point.

**Neither packaged build has a debugger, so do not reach for one.** Ubuntu
noble's `dosbox-x` 2024.03.01 and Flathub's `com.dosbox_x.DOSBox-X` 2026.08.02
were both installed, tested and removed: neither links ncurses, neither prints a
`Debugging options:` section for `--help`, and `-break-start` is silently
ignored by both. `dosbox-x --help | grep -c helpdebug` is the one-line test — 1
means you have the debugger, 0 means you do not. Ordinary DOSBox 0.74-3
(`/usr/bin/dosbox`) is untouched and `tools/dosbox.py` still uses it.

The C64 side is untouched: no VICE or FS-UAE configuration was changed.

## Starting it so it cannot draw on the user's desktop

Three traps, all hit during this work.

**The Wayland trap.** DOSBox-X asks for a working directory with a `zenity`
folder chooser when it has no configured one. `zenity` is GTK, GTK prefers
`WAYLAND_DISPLAY` over `DISPLAY`, and Donald's desktop is Wayland (COSMIC) — so
a correctly set `DISPLAY=:40` was ignored and **the dialog opened over his
editor**. Unsetting `WAYLAND_DISPLAY` is what actually confines the process:

```sh
env -u WAYLAND_DISPLAY -u XDG_SESSION_TYPE -u XAUTHORITY \
    GDK_BACKEND=x11 QT_QPA_PLATFORM=xcb DISPLAY=:40 dosbox-x -conf ...
```

**The dialog itself.** Do not rely on the environment alone: give the config a
working directory so nothing is ever asked. In `[dosbox]`:

```ini
working directory option = custom
working directory default = /path/to/instance
title                    = wishdbg
```

That directory is also where `MEMDUMP.BIN` lands, which is how a memory read
gets back to the host. `-nopromptfolder` on the command line is a second belt.

The rest of the config is `tools/dosbox.py`'s, plus:

```ini
[log]
logfile     = /path/to/instance/dbg.log
debuggerrun = debugger
```

`logfile` is what makes this scriptable at all — see below.

**The window trap.** A session that shares another run's display captures the
wrong window, and every screenshot comes back solid black (#83). Two DOSBox-X
processes on one display leave two top-level windows with the same title, the
same `640x400+80+100`, both `IsViewable`, and both returned by `xdotool search`:

```
0x20000b "wishdbg - DOSBox-X 2026.08.02: START - 30000 cycles/ms"  640x400+80+100
0x40000b "wishdbg - DOSBox-X 2026.08.02: START - 30000 cycles/ms"  640x400+80+100
```

Nothing about the windows separates them. What makes one of them black is the
stacking: they overlap exactly, `Backing Store State: NotUseful`, and there is
no compositor under a bare `Xvfb`, so **`import -window` on the obscured window
reads back one flat colour** — X keeps no contents for a window nobody can see.
`import` succeeds, so nothing downstream notices: `settle()` calls two identical
black frames a finished screen, every `wait_for` on it times out, and
`load_game` reports a save that loads perfectly as never having loaded.

Three things follow, all of them in `tools/dosboxx.py` now:

* **Choose the window by `_NET_WM_PID`**, which SDL2 sets and which is the only
  thing that told the two apart. Choosing by content is *wrong* here — the
  window with pixels in it is whichever process drew last, not ours.
* **Never share a display.** `boot()` refuses to start when an X server is
  already listening on the slot's display, because that is the condition the
  two windows need. The check connects to `/tmp/.X11-unix/X<n>`: `xdotool`
  cannot answer it, as it exits 1 both for "no windows matched" and for "Can't
  open display", which is also why the old readiness loop never waited for
  anything.
* **Refuse a capture of one colour by name.** `shot()` raises `BlankCapture`
  rather than writing a PNG that looks like a game drawing nothing.

The condition that starts it is a leaked process: `Xvfb` and `dosbox-x` are
started with `start_new_session=True`, so a run whose Python is killed outright
leaves both alive, holding the display against the next session to claim that
slot.

## Reaching the debugger

| how | when to use it |
|---|---|
| `-break-start` on the command line | break before anything runs |
| `DEBUGBOX PROG.EXE` in `[autoexec]` | break at a program's entry point |
| **Alt+Pause in the emulator window** | break into a game already running |

Alt+Pause is `MK_pause` with `MMOD2` in `src/gui/sdlmain.cpp`, and reaches a
windowed instance through `xdotool key --clearmodifiers alt+Pause` after
`xdotool windowfocus`. **XTEST, not `xdotool key --window`**: SDL2 ignores the
synthetic events that DOSBox 0.74's SDL1 accepted, so the `--window` form used
throughout `tools/dosbox.py` silently does nothing here.

**The debugger only exists if DOSBox-X was started from a terminal.** On Linux
it draws in the terminal that launched the process, not in a window of its own,
so a session with no controlling tty has no debugger at all. `pty.openpty()` is
a terminal for this purpose, and must be given a size — ncurses draws nothing in
a 0×0 pty:

```python
master, slave = pty.openpty()
fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 60, 160, 0, 0))
p = subprocess.Popen([...], stdin=slave, stdout=slave, stderr=slave,
                     env=env | {"TERM": "xterm"}, start_new_session=True)
```

## The loop that makes it scriptable

**In: a line on the pty. Out: a line in the log file.**

* Commands are typed characters ending in `\n` (0x0A; `case 0x0A` in
  `DEBUG_CheckKeys` is what parses the input line).
* Every message the debugger prints goes through `DEBUG_ShowMsg`, which writes
  to `debuglog` unbuffered *as well as* to its curses window
  (`src/debug/debug_gui.cpp`). So `[log] logfile=` turns the debugger's replies
  into a host text file that a script can tail. **No screen scraping.**
* Function keys are terminfo sequences, so `TERM` must match what you send:
  F11 (step into) is `\x1b[23~` and F10 (step over) is `\x1b[21~` for `xterm`.

**The debugger answers only while the emulator is halted, and input typed while
it runs is thrown away** — `debug_gui.cpp` flushes pending input when the
debugger opens (`while (getch() >= 0);`). That gives a clean halted/running
test, which matters because a *code* breakpoint prints nothing when it fires:

> send `EV IP`; if a line appears in the log, the emulator is stopped.

Measured: with no breakpoints set, three probes during a run produced no log
lines and were discarded, and the game visibly moved a square meanwhile; the
next Alt+Pause produced exactly one.

## The commands that matter

Addresses are `segment:offset`, hexadecimal, and **the offset wraps at 64K**
(`GetAddress(seg,ofs)` is real-mode `seg*16 + (ofs & 0xFFFF)`). A linear address
`L` is safest as `(L >> 4):(L & 0xF)`.

| command | does | grade |
|---|---|---|
| `MEMDUMPBIN <seg> <ofs> <len>` | writes `MEMDUMP.BIN` in the working directory | CONFIRMED |
| `MEMDUMP <seg> <ofs> <len>` | the same as `MEMDUMP.TXT`, hex + ASCII | CONFIRMED |
| `EV <expr> [<expr>…]` | echoes values **to the log**: register names (`EAX`, `CS`, `IP`, `PSPSEG`, flags), hex literals, `+ - * / & \| ^ << >>` | CONFIRMED |
| `SM <seg>:<ofs> <byte>…` | writes memory | CONFIRMED |
| `BPM <seg>:<ofs>` | **watchpoint**: breaks when that *one byte's value changes*, logging `Memory breakpoint : SSSS:OOOO - old -> new` | CONFIRMED |
| `BP <seg>:<ofs>` | code breakpoint; stops, but **logs nothing** | CONFIRMED |
| `BPINT <int> [ah] [al]` | break on an interrupt call | UNTESTED |
| `BPLM <linear>` | the same watchpoint on a linear address, no segment | UNTESTED |
| `FM <seg>:<ofs> <byte>` | **freeze**: writes the byte back every time anything changes it | UNTESTED |
| `BPLIST`, `BPDEL *`, `BPDEL <n>` | list and delete breakpoints | CONFIRMED |
| `RUN` | resume | CONFIRMED |
| F11 / F10 | step one instruction / over a `CALL` | CONFIRMED |
| `LOG`, `LOGS`, `LOGL` | CPU trace to `LOGCPU.TXT` | UNTESTED |
| `MEMFIND` / `MEMS` | in-emulator memory search | UNTESTED — dumping and searching host-side is easier |

Three quirks that will cost an hour if nobody says them. All three are hidden
by `tools/dosboxx.py`, so this is the explanation rather than the instruction:

* **`MEMDUMPBIN` cannot read more than 64K in one call.** Ask for `100000` and
  you get 1 MB of the *same* 64K repeated sixteen times — the offset wraps, and
  the file's size is no warning. A megabyte is sixteen calls,
  `MEMDUMPBIN 0000 0 10000`, `MEMDUMPBIN 1000 0 10000`, … `F000`.
* **A fresh `BPM` remembers the value 00**, so unless the byte really is zero
  the first hit is spurious and arrives the instant you `RUN`. Absorb it, then
  `RUN` again; the second hit is a real change.
* **A command is cut at 254 characters in silence** (`MAXCMDLEN` in
  `src/debug/debug.cpp`). A long `SM` writes the bytes that survived the cut
  and reports `Memory changed` for them, so a write of a whole record looks
  like it worked and did not. Keep an `SM` to about sixty bytes.

Two smaller things, both useful:

* `MEMDUMPBIN`'s `Memory dump binary success.` is printed *after* `fclose`, so
  seeing that line means the file is complete. There is no size to poll and no
  race.
* `ParseCommand` upper-cases the whole line, so commands and register names are
  case-insensitive — and `EV AF` is the auxiliary-carry flag rather than the
  number `0xAF`. Quote it, `EV "AF"`, to mean the number.

## Proving it on the game: the DOS clock

The question this had to answer is one the save-file differentials already
settled, so the answer is checkable: `docs/141-dos-savegame.md` puts the ECL VM
variables at `SAVGAM?.DAT` offset 1, two bytes per ECL address, with the clock
at `$49C6`-`$49CB` and `$49C7` the minute units. Slot J reads 10:56, so `$49C7`
is 6.

1. Booted Pool of Radiance under DOSBox-X, loaded Donald's slot J, Alt+Pause.
2. Sixteen `MEMDUMPBIN`s for the first megabyte.
3. Searched that image, on the host, for every 12-byte window of the save's own
   5120-byte VM array that is not mostly zeros. **All 62 of them vote for one
   base: linear `$39940`**, where 5118 of the 5120 bytes equal the file. (The
   two that differ are `$4FD2` and `$4FD3`, `$18` in the file and 0 live — both
   in the unnamed group. The runner-up bases, 7 votes each, are the same array
   matched at an offset.)
4. So `$49C7` is at `$39940 + 2*0xC7` = linear `$39ACE` = `39AC:000E`, and the
   dump has `06` there, which is what the file has.
5. `BPM 39AC:E`, absorb the spurious hit, `RUN`, then one step forward:

   ```
   DEBUG: Memory breakpoint : 39AC:000E - 06 -> 07
   ```

   The minute ticked, exactly as the save-file differential said it would, and
   the debugger caught the write. `EV CS IP` at the break reads `2f69 462`.
6. `BP 2F69:0462` then stops on every tick; `SM 39AC:E 09` writes the byte and
   a re-dump reads `09` back.

**The base address is not a finding to reuse** — it is where DOS happened to
load this build with this config, and `$39940` is CONFIRMED only for the
configuration in this document. The finding is the *recipe*: dump, then locate
the array by matching a save you already hold.

All six steps are now `python3 tools/dosboxx.py clock`, which runs them
unattended in about twenty seconds and prints what it found. It has produced
`$39940`, 62 voting windows, 5118 of 5120 bytes equal, `39AC:000E` live `06`,
the spurious `00 -> 06`, the tick `06 -> 07` and `2f69 462` on every run so
far. `tests/test_dosboxx.py` asserts all of that behind `WISH_DOSBOXX_DRIVE=1`
— everything except the base address, which is exactly the number that is not
allowed to be a finding.

## What it cannot do

* **No socket, no scripting language, no command file.** `ParseCommand` has
  exactly two callers: the curses input line and a GUI dialog. Everything above
  is a pty pretending to be a person typing.
* **No structured output.** The log carries what `DEBUG_ShowMsg` prints and
  nothing else. The register window, the disassembly and the data view are
  drawn in curses and never reach the log — `EV` is the only way to get a
  register value out, and there is no way to get disassembly out except by
  rendering the terminal (tmux `capture-pane`, or a `pyte` screen).
* **A code breakpoint firing is invisible.** No message; probe for it.
* **Watchpoints are one byte, on change.** A word takes two, a write of the
  same value is not seen, and there is no read watchpoint.
* **Heavy debugging costs speed** — every instruction is checked against every
  memory breakpoint.
* **It cannot be shared.** One debugger per process, on that process's
  terminal, like VICE's one binary-monitor connection per process.

## The harness

`tools/dosboxx.py` is `tools/dosbox.py` with the launch replaced: the same slot
lease, the same staged game tree, the same `Screen` digests, and
`PoolOfRadiance` drives it unchanged, which is what gets a run to a loaded save
before there is anything worth looking at. Displays :40-:47, so the two pools
and VICE's :10-:17 never collide.

```python
from tools import dosbox, dosboxx

with dosboxx.claim("what I am doing") as slot:
    with dosboxx.XSession(slot, dosbox.find_game("POOLRAD")) as s:
        por = dosbox.PoolOfRadiance(s)
        por.to_main_menu(); por.load_game("J")
        s.attach()                       # Alt+Pause; True when it answered
        image = s.read(0, 0x100000)      # sixteen MEMDUMPBINs, joined
        base, votes, same = dosboxx.locate(image, save[1:5121])
        s.watch(base + 0x18E)            # BPM, spurious first hit absorbed
        hit = s.until_break(timeout=180)  # RUN, then the next real change
        s.regs("CS", "IP")               # EV, the only way registers come out
        s.write(base + 0x18E, b"\x09")   # SM, split to fit the 254-char line
```

The rest: `dbg(cmd, expect=…)` types any command and returns what it added to
the log, `halted()` is the `EV IP` probe, `brk()` sets a code breakpoint and
`wait_halt()` notices it firing, `step()` and `step_over()` are F11 and F10,
`breakpoints()` and `clear_breakpoints()` are `BPLIST` and `BPDEL *`.

Addresses are linear `int`s or `(segment, offset)` tuples everywhere, and
`linear()`, `seg_off()` and `chunks()` are the arithmetic on their own, so the
64K rule can be tested without an emulator — and is.
