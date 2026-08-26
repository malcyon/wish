# Driving the game programmatically

Everything here was established the hard way. If you are automating Pool of
Radiance under VICE, read this before writing any input code.

## What the automapper needs, versus what automation needs

Worth separating, because they got conflated and made the map look harder to run
than it is.

**Reading** a running game needs one thing: VICE started with
`-binarymonitor -binarymonitoraddress 127.0.0.1:6502`, plus
`flatpak override --user --share=network net.sf.VICE` if it is the Flatpak. Set
`BinaryMonitor=1` in `vicerc` and every launch has it, including from a desktop
menu. Nothing below this line applies.

**Driving** a game — sending keys — needs everything below: the nested X server,
the input timing, the whole apparatus. `tools/porlaunch.sh` exists for that, not
for the automapper.

## Run it in a nested X server

`tools/rungame.sh <experiment>` starts **Xephyr** and runs VICE inside it. This
is not cosmetic:

* Under Wayland there is no dependable way to give an XWayland window keyboard
  focus. `xdotool windowactivate` returns success, `xdotool getactivewindow`
  *and* `_NET_ACTIVE_WINDOW` both name the VICE window, and the keystrokes
  still do not arrive.
* It appears to work right after launch only because VICE grabs real focus
  then. It stops the moment focus moves — for instance when the window is
  dragged to another monitor.
* Worse, keys sent while VICE lacks focus land in **whatever window does have
  it**, potentially a terminal.

Inside Xephyr there is no window manager, so the single window holds input focus
permanently and XTEST always reaches it. `windowactivate` *errors* there — that
is expected and harmless; do not "fix" it.

**Both `DISPLAY` and `--env=DISPLAY` must be set** on the `flatpak run` line: the
outer one decides which X socket the sandbox is given, the `--env` one tells the
app which to connect to. Setting only `--env` silently puts the window on the
host display.

## Input timing — the single biggest source of lost time

The game polls the **CIA keyboard matrix** directly rather than using KERNAL
input. Consequences:

* Writing to the KERNAL keyboard buffer (`$0277`, count at `$C6`) reaches the
  game at **text prompts and in the world**, but was never shown to reach a
  menu. See "The KERNAL keyboard buffer *does* work" below; the blanket "does
  nothing" that stood here was wrong.
* A press/release pair sent faster than the game's poll interval is missed
  entirely. `xdotool key` types `WYVERN` as `WRN`.

Send every key as **keydown, hold, keyup, gap**:

| context | hold | gap |
|---|---|---|
| menus (Up/Down/Return) | 0.10s | 0.14s |
| text entry generally | 0.15s | 0.28s |
| a `press any key` prompt | **0.25s** | — |

When a screen has just changed, the first burst is often swallowed — the game is
not reading input yet. Verify by effect and retry rather than trusting a single
send.

## What does *not* work

| attempt | result |
|---|---|
| `xdotool key --window <id>` | VICE ignores synthetic `XSendEvent` |
| `Alt+N` (fliplist next), plain or held | does not change the attached disk |
| `F10` | does not open the menu bar |
| synthetic mouse clicks on menus | do not register |
| **capitals via `xdotool key W`** | arrives as Shift+w, PETSCII `$D7`; the name prompt rejects any byte ≥ `$5B` and silently re-prompts. Type lowercase |
| XTEST `Return` at the code-word prompt | letters arrive, Return does not. Inject it instead |
| a single self-contained boot disk | impossible: the game demands side 3 the moment the copy protection passes, and other sides later |
| closing the binary monitor while a checkpoint is armed | VICE re-enters the monitor on the connection that was live when it stopped; with that socket closed the emulator freezes and no new connection is read. Only a kill recovers it |
| closing the text-monitor connection | wedges the binary monitor too — VICE serves one text-monitor connection per run |
| connecting to the text monitor first | it never breaks in on connect and sends no banner; it answers only while the machine is already stopped |
| a **second** binary-monitor connection while one is open | VICE accepts the TCP connection and then never answers it — the read times out with zero bytes. One binary monitor client at a time, so `automap` and `tools/session.py` cannot both be live |
| a stray **`wish` GUI** left running | the same failure wearing a different hat: it holds `6502` open, so every later `Monitor()` times out and the game looks frozen. `ss -tnp \| grep 6502` names the process holding it; nothing recovers but closing that client |
| `select_bar` on the **combat** and **items** command bars | their highlight is colour **7**, not 1, so `highlight_span` finds nothing and the call returns `False` after silently sending nothing. Read row 24's colour RAM and step the highlight yourself |
| `EXIT` out of `VIEW:ITEMS` → `READY` | the item list re-arms itself: choosing its `EXIT` returns to the bar, and the next `Return` drops straight back into the list. Rebooting the session was faster than escaping it |
| **XTEST keys while a binary-monitor client holds the socket** | thirty `Right` presses moved nothing; the first press after the client closed moved the highlight. A driver that both watches and types must **connect, read, close** for every poll, the way `tools/session.py` does — which is also why `automap` and a driving script cannot be one process |
| **entering area 11 (the training hall) by warping** | `ECL0B` reads `$6E82`, which the *departing* square's attribute byte sets, so a warp arrives with nothing to dispatch on and the game drops the party back into New Phlan within eight seconds. Walk in; do not warp in |
| loading `work/drive/SLUMS.D64` | the party comes up, `BEGIN ADVENTURING` prints `OUTWARD BOUND ...`, and the loader then asks for side 3 for ever, requesting **`WALLSET00`** — a file on none of the eight sides. Use the player's own saves for driving work |

`Alt+N` genuinely *is* the right binding (VICE's own
`share/vice/hotkeys/hotkeys-fliplist.vhk` maps `fliplist-next-8` to `<Alt>n`).
The problem is that VICE's **GTK layer never sees synthetic modifiers or
clicks** — only the emulation canvas receives keys.

## Disk swapping — solved, through the text monitor

VICE's **text** monitor has an `attach "<path>" 8` command, and both monitor
servers can be enabled at once (`-binarymonitor … -remotemonitor …`). That is
the whole disk-swap mechanism, and it removes the block the table above used to
describe.

Three rules, each learned by wedging the emulator:

1. **Open the binary monitor first.** The text monitor answers only while the
   machine is stopped, which is what connecting the binary monitor does.
2. **Open the text socket once and never close it.** VICE serves one such
   connection per run; closing it kills the binary monitor as well.
3. **Never send `x` on the text socket.** Resuming is the binary monitor's job.
4. **Re-attach even when the image is already in the drive.** The 1541 only
   notices a disk *change*, so answering `INSERT SIDE # n` with the same image
   already attached leaves the game asking for ever.

`tools/session.py` implements this as `Session.attach(path)`, and
`tools/walkrun.py` runs whole batches on it. Only copies under `work/drive/`
are ever attached — `attach` refuses any other path.

## Driving a session end to end

The order of operations, all of it in `tools/session.py`:

| step | what to do |
|---|---|
| `DISABLE FASTLOADER (Y/N)?` | `Y` (VICE runs JiffyDOS here) |
| credits screen | row 24 is `PLAY GAME  DEMO`; take it at once — **left alone the screen starts the demo by itself** |
| `INPUT THE CODE WORD:` | patch `$12D9` `D0 04` → `EA EA` (check the bytes first), type six letters, then inject `Return` through the KERNAL buffer |
| `INSERT SIDE # 3` / `INSERT YOUR GAME DISK #3` / `INSERT GAME DISK #3` | attach that side, press a key with a 0.25 s hold — and re-attach even if that image is already in the drive. Three wordings, on row 24 **or** row 18 — match the text, not the row |
| `INSERT YOUR SAVE GAME DISK` | attach the save disk, press a key |
| main menu | `LOAD SAVED GAME`, then `Return` on the already-white `YES` |
| party menu | `BEGIN ADVENTURING` |
| in the world | row 14 is the status line — `E 16:48 5,2`: facing, clock, x, y |
| `MOVE` | `I` forward, `J` turn left, `K` turn right, **`M` steps *backward*** without turning; `Return` leaves |
| `ENCAMP` → `SAVE` → `SAVE GAME` | writes `SAVEDGAME0`/`SAVEDGAME1` to whatever disk is in the drive |

**Read the position off the status line, not `$49C0`.** The memory copy is real
and it is what reaches the disk, but it lags a move — reading it straight after
a step gives the previous square.

**Nothing here can be taken on trust.** The command bar is not always redrawn,
so finding `MOVE` on row 24 is no evidence that MOVE was selected; and the first
input burst after a save is reliably swallowed. Verify every action by effect.

**The training hall is not a dead end** — that claim is withdrawn. Stepping
east from `6,2` into `7,2` prints `THE ROOM IS FILLED WITH DUELING PAIRS.` and
row 24 becomes **`PRESS <RETURN> OR BUTTON TO CONTINUE`**. Press Return, wait
~25 seconds for the scene to load, and answer the two `YES NO` questions the
trainer asks; the party then stands at `7,2` in the ordinary move mode.

**What is being loaded is area 11, `ECL0B`, the training hall** — square `(6,2)`
in `GEO00` carries script id 10, and `ECL00`'s `ONGOTO` sends id 10 to a handler
ending in `NEWECL 11`. It was long labelled "the arena" here and in
`goldbox/areas.py`; `ECL0B` also prints `WE TRAIN ONLY <class> HERE. DO YOU WANT TO
TRAIN?` at `$A0DD`, and both DOS sources name script 11 the training hall.
`7,2` itself carries script id 14, which `ECL00` sends to a handler that does
nothing — so a driver told to "go to `7,2`" and press keys there will wait for
ever. Drive to `(6,2)` and step east.

Three things made this look like a wedge:

* **The square is `7,2`, not `6,2`.** The status line keeps showing `6,2` for
  the whole encounter, because the step does not complete until the questions
  are answered.
* **`$306D` is the menu key reader**, and it only accepts `<`, `,`, CRSR-up,
  `>`, `.`, CRSR-down, CRSR-left, CRSR-right, `$0D`, `$5F` and the joystick.
  `I`, `J`, `K`, `M` fall out at `$30B6` with carry clear and are dropped —
  correct behaviour, not a fault.
* **The load takes ~25 s**, and `leave_move()` gives up after eight tries of
  0.6 s, so a `Return` that worked looked like one that did nothing.

Do not conclude "wedged" because row 24 lacks the label you wanted. Match
`PRESS <RETURN>` and `YES NO` and answer them.

## The KERNAL keyboard buffer *does* work at text prompts

The blanket claim that it does not is wrong. The game's key fetcher at `$2E4E`
reads `$0277` with the count at `$C6` — writing those two delivers a keystroke,
and it is the only thing that submits the code-word prompt. It is also the
reliable way to send `Return` anywhere, and a **move** key injected this way
stepped the party while a binary-monitor connection was held open, which XTEST
cannot do (`docs/50-experiments.md`, P20). The menus are a different matter:
they were never shown to read the buffer, so treat XTEST as the default and the
buffer as the escape hatch — except while a monitor client is connected, when
the buffer is the only thing that works at all.

## Reading the screen

The game runs in **text mode with its own character set**, so the screen is
readable as screen codes — no OCR, no image matching.

Compute the screen address from the VIC registers each time; it moves:

```python
d018 = peek(0xD018); dd00 = peek(0xDD00)
bank = (~dd00 & 3) * 0x4000
screen = bank + ((d018 >> 4) & 0xF) * 0x400      # $CC00 in-game, $0400 at boot
```

`$D011` bit 5 tells you whether the display is bitmap (title/credits) or text.
Bitmap screens cannot be read as text — use a screenshot.

**Menu selection is a colour, not a character.** The highlighted row is drawn in
white (colour 1), the rest green (colour 5). Colour RAM is always at `$D800`
regardless of VIC bank. `goldbox`-side helpers read it to find the highlight, then
press Up/Down the right number of times and Return. That is far more robust than
counting rows.

## Screenshots

`import -window <id>` on the nested display takes ~0.25s. Going through the MCP's
`vice_screenshot` takes several seconds — enough to lose races against menus that
time out. Use `import` unless you need the MCP for another reason.

## Which client talks to the monitor

Two exist, and only **one may be attached at a time** — VICE accepts a second
binary-monitor connection and then never answers it.

* `automap/vice.py` is the project's own client and the one to use for anything
  that walks: it holds the connection open across a session and `resume()`s,
  which is what watchpoints and the automapper both need.
* The **MCP server** (`axewater/mcp-vice-emu`, registered in `.mcp.json`) is for
  one-off probes. It is a **local fork** at `~/src/mcp-vice-emu`: upstream
  unconditionally spawns `${emulator}.exe` and has no attach-to-running mode, so
  it was patched with an `isMonitorListening()` probe that attaches when the port
  already answers, and the `.exe` suffix dropped off Windows. `cleanup()` only
  kills `this.process`, which stays null when attaching, so it will not kill an
  emulator it did not start. **Re-apply the patch if it is ever re-cloned or
  updated.** Its `vice_memory_read` takes `start`, not `address`.

**RetroDebugger is deliberately not installed.** It has no Linux AppImage or
`.deb` — a CMake source build means maintaining a second VICE — and its
real-time memory view is covered by a monitor read plus watchpoints. Revisit
only for something those cannot show.

## The binary monitor

* **Connecting stops the machine.** Nothing advances while a socket is open.
  Use connect → read → **close**; closing resumes. Verified against the KERNAL
  jiffy clock at `$A0-$A2`, which advances at exactly real time between
  connections.
* **A held-open connection that resumes does the opposite: it makes the game run
  fast.** Each stop/resume pair hands the emulation ~14.3 ms of *extra* emulated
  time, and the cost is per `resume()`, not per byte — one 7168-byte read costs
  the same as one `peek`. Measured against the same jiffy clock: polling flat
  out runs the machine at 3.05× real time, every 200 ms at 1.07×, every 500 ms
  at 1.03×. So batch a poll into **one** resume, and treat the poll interval as
  a speed dial: distortion is `14.3 ms / interval`.
* Do **not** infer "stopped" from a constant `$D012`. Monitor reads with
  side-effects disabled do not return live VIC counter values.
* VICE interleaves **unsolicited events** into the stream (type `0x62` STOPPED,
  `rid=0xFFFFFFFF`). A client that reads one response per request silently
  desyncs and returns the *previous* request's data. Match responses by request
  id.
* **`CMD_REGISTERS_AVAILABLE` (`0x83`) is served by this build**, whatever the
  comments in `automap/` used to say. It answers `A`=0, `X`=1, `Y`=2, **`PC`=3**
  (16 bits), `SP`=4, `FL`=5, plus `LIN`, `CYC`, `00` and `01`. Ask it rather
  than hard-coding the register numbers.
* **Watchpoints work**, and a store watchpoint settled what writes `$6DD5`.
  What made them look broken was leaving them armed across a socket close, and
  the `resume()`-rather-than-close rule above.
* `CHECKPOINT_SET` (`0x12`) answers with `CHECKPOINT_RESPONSE` (`0x11`), not
  with its own command type.
* **Always delete checkpoints when an experiment ends.** A stop-on-hit
  checkpoint left armed looks exactly like a hung game.
* Reading RAM under I/O (e.g. the charset at `$D000`) needs the `ram` bank —
  query `BANKS_AVAILABLE` (`0x82`); on this build `ram` is bank 1.

## Patching overlays

The game is heavily overlaid. An address holding the routine you patched is
**replaced wholesale** when another disk side loads. Patching the same address
blind a second time corrupted a live routine (`LDA #$01` → `NOP NOP`).

**Read and check the bytes before every write.**

## Snapshots

`DUMP` (`0x41`) / `UNDUMP` (`0x42`) over the binary monitor save and restore full
machine state. `work/E003-past-protection.vsf` is a snapshot taken at the
party-creation menu. Restoring proved unreliable in practice — the one attempt
left the machine at a fresh boot — so treat it as a convenience, not a
dependency.

## Character creation

Menus can be driven: **race → gender → roll stats → class → alignment → name**,
each a highlight-and-Return list. The class list offered depends on the race
(HUMAN offers only CLERIC / FIGHTER / MAGIC-USER / THIEF).

**Creation works.** It was blocked for a long time by one instruction:

```
$0C41  A2 13      LDX #$13
$0C43  BD 00 97   LDA $9700,X
$0C46  C9 5B      CMP #$5B
$0C48  B0 D0      BCS $0C1A     ; any byte >= $5B -> start the prompt over
$0C4A  9D 00 6B   STA $6B00,X
```

The name must be **unshifted PETSCII**, `$41`–`$5A`. `xdotool key W` sends
Shift+w, which arrives as `$D7`, so every capital failed the compare and the
prompt restarted — which is exactly what "Return clears the field and
re-prompts" looked like. Type the name in lowercase and the character is
created; `\x01WYVERN` was written to a save disk under script.

## Input buffer

Typed text lands at **`$9700`, in PETSCII**, not screen codes, and it appears
there **as it is typed**, not only when Return is pressed. Which PETSCII matters:
unshifted letters are `$41`–`$5A` and shifted ones `$C1`–`$DA`, and the
name-entry routine rejects anything at or above `$5B` (see above). The length
typed so far is at `$03B7` and the field width at `$03B8`.
