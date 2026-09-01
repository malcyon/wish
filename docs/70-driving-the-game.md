# Driving the game programmatically

Everything here was established the hard way. If you are automating Pool of
Radiance under VICE, read this before writing any input code.

## What the automapper needs, versus what automation needs

Worth separating, because they got conflated and made the map look harder to run
than it is.

**Reading** a running game needs one thing: VICE started with
`-binarymonitor -binarymonitoraddress 127.0.0.1:6502`, plus
`flatpak override --user --share=network net.sf.VICE` if it is the Flatpak. Set
`BinaryMonitorServer=1` in `vicerc` and every launch has it, including from a
desktop menu -- the name ends in `Server`, and VICE ignores a resource it does
not recognise without a word. Nothing below this line applies.

**Driving** a game — sending keys — needs everything below: the nested X server,
the input timing, the whole apparatus. `tools/porlaunch.sh` exists for that, not
for the automapper.

## Run it in a nested X server

Claim a slot from the instance pool (`tools/instance.py`) and launch through
`tools/porlaunch.sh`, which starts VICE on that slot's own **Xephyr** display —
see [`123-parallel-sessions.md`](123-parallel-sessions.md) for how to claim
one. Running nested is not cosmetic:

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
| `select_bar` on the **items** command bar | its highlight was recorded as colour **7** rather than 1, so `highlight_span` finds nothing and the call returns `False` after silently sending nothing. Read row 24's colour RAM and step the highlight yourself. **The row used to name the combat bar too and that half is wrong** (#125): Pool of Radiance's combat bar reads `1 1 1 1 5 5 5 …` in `$D800 + 24 * 40` with `MOVE VIEW AIM USE QUICK DONE` on screen — colour 1 on the highlighted cells, the same shape as every other bar — on four runs across three saves. The items half has not been re-measured and no specimen was ever recorded for it |
| `EXIT` out of `VIEW:ITEMS` → `READY` | the item list re-arms itself: choosing its `EXIT` returns to the bar, and the next `Return` drops straight back into the list. Rebooting the session was faster than escaping it |
| **XTEST keys while a binary-monitor client holds the socket** | thirty `Right` presses moved nothing; the first press after the client closed moved the highlight. A driver that both watches and types must **connect, read, close** for every poll, the way `tools/session.py` does — which is also why `automap` and a driving script cannot be one process |
| **entering area 11 (the training hall) by fasttraveling** | `ECL0B` reads `$6E82`, which the *departing* square's attribute byte sets, so a fasttravel arrives with nothing to dispatch on and the game drops the party back into New Phlan within eight seconds. Walk in; do not fasttravel in |
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

## Driving a fight

`tools/session.py` drives one: `in_combat()`, `combat_state()`, `combat_bar()`
and `fight()`. Before those existed every agent that needed a fight wrote its
own loop, and `work/drive/qffight.py`, `work/combatlog/walkabout.py` and
`work/p118-step3/run.py` are three of them.

**`tools/fightrun.py` is the runner**: boot a pool slot, load a save, walk
until something ambushes the party, drive every command bar with
`melee_turn`, and print who took the turns, how many had an enemy in contact
and how many of those ended with a blow. Three copies of it were written into
`work/` for `#126`, `#127` and `#165` and thrown away with that directory; the
log it writes still belongs in `work/`, the tool does not.

**`$6E11` says whether there is a fight**: `1` DUNGEON, `2` COMBAT. It is
LINKER's own dispatch byte and `automap/combat.py` documents the rest of it.

**Row 24 is the whole of what a fight asks you**, and telling its kinds apart is
most of the work. 807 readings across the twelve logs in `work/p118-step3/`
hold 18 distinct bars, and every one of them is one of these:

| kind | what it looks like | what to do |
|---|---|---|
| command | `MOVE VIEW AIM USE [CAST] QUICK DONE`, and `MOVE` drops off once the character has no squares left | one character's turn |
| move | `MOVE/ATTACK, MOVE LEFT = 9` | a direction, **not** a menu |
| continue | `CONTINUE BATTLE : YES NO` | `NO` ends the fight |
| press | `PRESS <RETURN> OR BUTTON TO CONTINUE` | inject `$0D` |
| done | `GUARD DELAY QUIT SPEED EXIT` — what `DONE` opens | `GUARD` ends the turn, and so does `QUIT` when GUARD is not offered |
| exit | a treasure bar | take `EXIT` |
| yesno | `ATTACK ALLY: YES NO` | answer `NO` |
| message | `GUARDING`, `YOUR TEAMMATE IS DYING` | wait |
| blank | empty | a monster's turn; wait |
| none | no readable screen at all | not the same as an empty bar |

**A half-redrawn bar reads as a message, and must not be forced into a kind.**
`MOVE/AT`, `MO` and a row of the screen's own border were all caught on row 24.
Wait and read again.

**The move sub-bar is not a menu and `select_bar` must never be pointed at it.**
`MOVE` is a word on `MOVE/ATTACK, MOVE LEFT = 9` exactly as it is on the command
bar, so matching cannot save you — `Right` sent there steps the character rather
than moving a highlight. `Session.combat_bar` refuses every bar that is not a
menu.

**Take the highlight from the same snapshot as the text.** `Screen` carries its
own colour RAM; `Session.highlight_span` does a second monitor read, so the two
come from different moments. Outside a fight that never shows. In one the bar is
redrawn for every character in turn, and the walk goes the wrong way.

**The fight is not over when `$6E11` leaves 2.** `THE PARTY HAS WON !`, the
experience share and any treasure all run afterwards under POST.COM. A driver
that stops at the mode byte leaves the party at a `PRESS <RETURN>` for ever, so
`fight()` runs until DUNGEON is back **and** the status line is on screen.

**And it is still not over there.** Two boots of `PORSAVE13.D64` on the same
route each won at about 150 seconds and then spent the whole rest of the
budget without handing the party back to the world. Row 24 after the win, in
the order it appeared (`work/issue165/fix2.jsonl`):

```
CONTINUE BATTLE : YES NO
PRESS <RETURN> OR BUTTON TO CONTINUE
VIEW TAKE POOL SHARE EXIT          <- the treasure bar
VIEW:ITEMS TRADE DROP EXIT         <- the item list, which re-arms itself
GO BACK LEAVE TREASURE             <- and this is where it stayed
```

`GO BACK LEAVE TREASURE` matches no branch of `combat_state` — no DONE, no
PRESS, no DELAY-and-SPEED, no EXIT, no YES and NO — so it reads as a message
and `fight()` waits at it for ever. `#171 (A won fight leaves the driven
party at the treasure screen instead of back in the world)` is the ticket;
`LEAVE TREASURE` has never been pressed.

**`DONE` does not end a turn — it opens a sub-bar.**
`GUARD DELAY QUIT SPEED EXIT`, and **`GUARD` on that is what ends the turn**,
which is where the `GUARDING` on row 24 in the older logs was coming from. A
driver that takes DONE and stops is asked for the same character's command
again: 210 turns in 420 seconds, no blow struck (`work/p126/melee4.log`).
Tell it apart from a treasure bar, which also carries EXIT, by `GUARD` and
`DELAY` being on it.

**Two of the five commands end the turn and two do not, and the difference is
what starved a fight of turns.** `GUARD` ends it and leaves the character
guarding; **`QUIT` ends it outright** — Donald, who plays this game,
2026-09-01: *"In Combat, QUIT ends the turn immediately."* That is his
testimony rather than a screen read, and it is the whole evidence for QUIT
here. `DELAY` **postpones** a character instead of finishing with it, and
`EXIT` only backs out to the same character's command bar; both leave the
driver being asked for the same character again.

**`GUARD` drops off the bar for some characters**, which leaves
`DELAY QUIT SPEED EXIT` — and `end_turn` used to fall to DELAY there. One
character who could not strike then took **50 of the 54 turns** that had an
enemy in contact, in a fight of 56 driven turns, while the other five never
acted again (`#165`, `work/issue127/after1.jsonl`). `Session.ENDS_TURN` is
`GUARD` then `QUIT` and `Session.LEAVES_BAR` is `DELAY` then `EXIT`, in that
order, so a bar with no GUARD gets QUIT. Why GUARD drops off is still not
established; the obvious suspect is that it is only offered to a character
that has not moved yet.

**`QUICK` reached the same sub-bar** and the quickfight bit at roster `+0x0C`
did not move on any of six characters (`work/p126/quick.log`). Whether QUICK
opens it in its own right or the highlight walk landed on DONE was not
distinguished, so nothing is claimed about QUICK beyond that it did not resolve
a turn.

### There is no attack key

`MOVE/ATTACK` is the whole of it: take `MOVE`, and a step into an occupied
square is a blow. That is why six runs of `#118` step 3 could get the party to
the end of a fight without any of them swinging — the driver kept entering move
mode and pressing Return to get out again.

Donald, who plays this game, says the same thing unprompted, 2026-09-01:
*"When I play, I normally use MOVE to move my character into an enemy square,
which causes them to attack the enemy. You can also AIM or CAST. Readied items
affect whether you can attack from a distance or not."* That is how the
commands work rather than a statement about what a dart-readied character can
do in melee, so it supports the missile-weapon reading below without settling
it. **Nothing in this project has driven `AIM` or `CAST`.**

**Combat movement is the joystick, and under the pool's seeded `vicerc` that
is the numeric keypad.** Measured key by key at a `MOVE LEFT = 12` bar, reading
the square each press spent out of the combatant table
(`work/p126/run1.log`):

| key | step | key | step |
|---|---|---|---|
| `KP_8` | north | `KP_7` | north-west |
| `KP_2` | south | `KP_9` | north-east |
| `KP_4` | west (PROBABLE) | `KP_1` | south-west |
| `KP_6` | east | `KP_3` | south-east |

Seven of the eight were seen to move a character. `KP_4` is graded PROBABLE
because on the one turn it was tried the square west of the acting character
held another party member.

**XTEST `Up`, `Down`, `Left` and `Right` move nothing in a fight**, and neither
do the world's own `I`, `J`, `K`, `M`. All eight were pressed at a live move
sub-bar and `MOVE LEFT` did not change once. This is a property of VICE's
keyset rather than of the machine: what would move the table is a `vicerc` with
a different joystick mapping.

**A step into an ally is a blow too, and the game asks first.** Walking a
character at (26,11) west into a party member on (25,11) put
`ATTACK ALLY: YES NO` on row 24 — which is the clearest confirmation there is
that a step onto an occupied square is an attack. `Session.melee_turn` ranks
the eight squares and drops any a party member is standing on; an enemy's
square is never dropped, because that step is the point.

### A blow spends no movement, and that is what hid it

**`MOVE LEFT` does not go down when the step is an attack, and the character
does not move.** ROLAND at (29,13) pressed `KP_1` into an orc on (28,14): the
count read 9 before and 9 after, nobody moved, and **the orc went from 5 hit
points to 1** (`work/issue127/sweep1.jsonl`, turn 15). So neither the count on
row 24 nor the position table says a blow happened. What says it is the
target's hit points, and the move sub-bar going away a moment later.

That is what `#127` was: `melee_turn` read the count, found it unchanged,
concluded "the step cost nothing so it did not happen", put the one key that
would land the blow into `avoid`, and passed the turn — with the character
standing next to the orc. **26 of 27 turns of one fight went that way.**

**Do not decide a step on one read either.** Asking `await_bar` for the bar you
are already looking at answers in 20 milliseconds without waiting for anything:
all 27 of those reads came back in 0.02–0.03 s. `Session.await_step` waits for
**either** the count to go down **or** the character's square to change, over
several reads, and `Session.AFTER_MOVE` is the set of row-24 kinds that mean
the sub-bar has gone.

**A character with a missile weapon readied appears not to be able to strike
this way** — PROBABLE, not confirmed. MALCYON with `13 DART` readied pressed
into an adjacent orc six times, each watched for ten seconds with nothing else
sent: no message, no damage, the sub-bar never went
(`work/issue127/probe1.jsonl`). Every character who did land or attempt a blow
in the same fight had a melee weapon — a mace, a long sword. It rests on one
character on one side and four on the other, and the weapon was never changed
and re-tried. `melee_turn` gives a blow `ATTACK_TIMEOUT` seconds and passes the
turn if it has not resolved, so such a character does not stand there pressing
a key that cannot work.

**Nonzero terrain is impassable, confirmed in a driven fight.** LADY KATHERINE
at (29,11) pressed `KP_9` into (30,10), terrain code 1: `MOVE LEFT` 5 and 5,
nobody moved; every press into a code-0 square moved her. `docs/101-combat-view.md`
said "0 is floor" from the renderer, and this is the same fact from the game.
`Session.step_towards` does **not** consult it yet and will aim a character at a
wall.

**`KP_0` leaves move mode**; `KP_5` does nothing. Neither behaved as a fire
button.

**The game names whose turn it is** in the right-hand panel — the acting
character's name, hit points, armour class and readied weapon, from column 22.
That beats inferring it from initiative, which several combatants hold at once.

**A character with no movement left loses `MOVE` from its own command bar**:
the bar becomes `VIEW AIM USE QUICK DONE`. A driver that recognises a command
bar by `MOVE` *and* `DONE` sits waiting at a bar that is asking it for a
command. Match on `DONE`.

**A driven turn costs about four seconds when it lands a blow**, and the number
that used to be here — twelve — was almost all waste. `combat_bar` has no way
of saying "that command is not on this bar": it waits for the label to appear
and spins to its full timeout when it never does. `end_turn` asked for GUARD,
DELAY and EXIT blind, and **441 of one 605-second fight's seconds, 73% of it,
went on words that were not on row 24** (`work/issue127/diag1.jsonl`). It reads
the bar once now and asks only for what is on it.

**Never point `combat_bar` at a label you have not seen on the bar.** That is
the general rule the 441 seconds are the specific case of.

`fight(budget=...)` still defaults to 300 seconds, which is not enough for a
fight of eight orcs against six characters; give it a number that matches the
fight.

`Session.melee_turn` is all of that together: read the fight, find the acting
character, take `MOVE`, and step towards the nearest living enemy until the
sub-bar goes away.

**A won fight is not a fought fight.** Six runs before `#126` ended with
`THE PARTY HAS WON !` and no character having attacked — the party guarded, the
monsters wandered off, and a log of command bars cannot tell that from a
victory. `FightResult.acted` is the distinction: it looks for a `HITS`,
`MISSES` or `DAMAGE` line, which is the only evidence a blow was struck.

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
