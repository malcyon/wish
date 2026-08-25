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

Two traps, both hit during this work.

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
| `BPLIST`, `BPDEL *`, `BPDEL <n>` | list and delete breakpoints | CONFIRMED |
| `RUN` | resume | CONFIRMED |
| F11 / F10 | step one instruction / over a `CALL` | CONFIRMED |
| `LOG`, `LOGS`, `LOGL` | CPU trace to `LOGCPU.TXT` | UNTESTED |
| `MEMFIND` / `MEMS` | in-emulator memory search | UNTESTED — dumping and searching host-side is easier |

Two quirks that will cost an hour if nobody says them:

* **`MEMDUMPBIN` cannot read more than 64K in one call.** Ask for `100000` and
  you get 1 MB of the *same* 64K repeated sixteen times — the offset wraps, and
  the file's size is no warning. A megabyte is sixteen calls,
  `MEMDUMPBIN 0000 0 10000`, `MEMDUMPBIN 1000 0 10000`, … `F000`.
* **A fresh `BPM` remembers the value 00**, so unless the byte really is zero
  the first hit is spurious and arrives the instant you `RUN`. Absorb it, then
  `RUN` again; the second hit is a real change.

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

Reproduced twice with the same base. **The base address is not a finding to
reuse** — it is where DOS happened to load this build with this config, and
`$39940` is CONFIRMED only for the configuration in this document. The finding
is the *recipe*: dump, then locate the array by matching a save you already
hold. The scripts are `work/dosboxx/find_clock.py` and `work/dosboxx/probe.py`
(scratch, gitignored).

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

## A harness, if one is wanted

`tools/dosboxx.py` would be `tools/dosbox.py` with the launch replaced: same
slot lease, same staged game tree, same `Screen` digests and the same
`PoolOfRadiance` keystroke protocol, plus the pty, `dbg(cmd) -> str`,
`read(seg, ofs, n) -> bytes` over the 64K limit, `watch(addr)`, `step()` and a
`halted()` probe. It is filed as an issue rather than built here.
