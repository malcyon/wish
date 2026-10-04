# Optional future feature: live memory and an automapper

**Status: built.** The code is the `automap/` package; this note is kept because
it records why the design is the way it is.

It lives outside the character editor on purpose, and outside `goldbox/` too: the
editor is a file tool with **zero emulator dependency** ([README.md](README.md)
§"How the code is laid out"), so everything that reads a running machine is in
`automap/` and neither `goldbox/` nor `editor/` imports it.

| module | what it is |
|---|---|
| `automap/vice.py` | the binary-monitor client, moved here from `tools/c64/drive.py`, which re-exports it |
| `automap/screen.py` | screen decoding over a bare `read` callable -- no VICE in it |
| `automap/target.py` | the two-method `Target` protocol, `party_fix` over any backend's `read`, and `ViceTarget` holding one connection open |
| `automap/area.py` | three strategies for "which `GEO` are we on" |
| `automap/state.py` | position, exploration, notes |
| `automap/render.py` | map geometry as drawing primitives, plus an SVG renderer — no Qt |
| `automap/c64.py` | one row per C64 title: the engine's own party square, `LINKER`'s dispatch byte, and each save-image region as a live address. A title nobody has run under a monitor has no addresses and is blocked |
| `automap/live.py` | the running game's party, effects and clock, as simple data — no Qt |
| `automap/panel.py` | the roster cards and the bottom strip |
| `automap/window.py` | the PyQt6 window: roster left, map right, strip below |

Run it with the game already running: `wish --tab map`. `python -m automap`
was the standalone way to open it alone, dropped in commit `4049fdf`
("Unified UI integration") when the window it built became the `wish` window's
own Map tab -- see [146-unified-ui.md](146-unified-ui.md). Render a map
offline with `wish --svg GEO00 out.svg`, which needs no emulator.

The window and the connection now live in `wish/` -- see
[99-one-window.md](99-one-window.md). `wish/backends.py` holds the list of
backends and `wish/session.py` owns the single `Target`, because VICE serves
exactly one binary-monitor connection and ignores the second in silence.

Which backend, which folder of game disks and whether the debug log is on are
all set in `File > Preferences…` (`Ctrl+,`) --
[130-preferences.md](130-preferences.md). The map tab says so itself when it
has no maps to draw.

## The idea

Read the party's map coordinates out of the running game and draw a live
automap, in the spirit of the Gold Box Companion. Optionally write memory too,
for things a save file cannot reach.

## Why it is cheap to add later

`goldbox/` contains **no transport code at all** — no sockets, no disk knowledge
beyond the D64 module. `CharacterRecord.from_bytes()` does not care whether the
bytes came from a disk image, a TCP socket or an HTTP response. So a live layer
does not disturb any existing code; it only has to supply bytes.

## The whole interface

```python
class Target(Protocol):
    def read(self, addr: int, length: int) -> bytes: ...
    def write(self, addr: int, data: bytes) -> None: ...
```

Everything else builds on those two. Breakpoints, stepping and similar are
VICE-only luxuries; keeping them out of the contract stops every other backend
having to pretend it has them.

## Two Commodore 64 backends, and only two

* **VICE**, over its binary monitor (`POR_DEBUG=1` already enables it).
* **Commodore 64 Ultimate**, over its network interface -- written, in
  `wish/ultimate.py`. Connecting and reading are CONFIRMED on Donald's own
  Ultimate with Pool of Radiance; writing (`UltimateTarget.write`) has not been
  exercised on the hardware. It speaks the documented REST API (`/v1/machine:readmem`,
  `/v1/machine:writemem`) and is offered only when a device answers at the
  **Ultimate host** named in `File > Preferences…`.

Deliberately not supporting other emulators or bare hardware. Most emulators
have no usable interface, and a real C64 would need a resident stub or a DMA
cartridge — a lot of fragility for very few users.

**There is a third now, for a different machine**: an Amiga under WinUAE or a
patched FS-UAE, in `automap/amiga.py`. The window offers it only behind
`WISH_EXPERIMENTAL_AMIGA_FSUAE` (FS-UAE, Linux) or
`WISH_EXPERIMENTAL_AMIGA_WINUAE` (WinUAE, Windows) — see
"[A third machine: the Amiga](#a-third-machine-the-amiga)" below for what it
does, what it cost to make the shared code take it, and what is left.

*(If a third is ever wanted, the cheapest by far is **watching the save file**:
poll its mtime and re-read on change. It needs no protocol, works on real
hardware with an SD2IEC, and fits the same interface with `writable=False`. It
is a fallback, not a priority.)*

## Backends differ in ways that change what you can build

Declare rather than assume:

| | VICE | Ultimate |
|---|---|---|
| writable | yes | expected, unverified |
| latency | ~1 ms, local TCP | higher; network |
| reading disturbs the machine | **yes** | expected no |

That last row is not a detail. **Connecting to VICE's binary monitor stops the
CPU** — during this project a perfectly healthy game was misdiagnosed as frozen
because of it ([the monitor-pause test](50-experiments.md)). The VICE backend
must hold one connection open and resume with `EXIT`, not connect per read.

The disturbance is not the one that was predicted, though. A held-open
connection that resumes makes the game run **fast**, not slow: each stop/resume
pair hands the emulation ~14.3 ms of extra emulated time, so polling flat out
runs the machine at 3.05× real time and the default 200 ms interval at 1.07×.
The cost is **per `resume()`, not per byte** — one 7168-byte read costs the same
as one `peek` — so batch a poll into a single resume and treat the interval as a
speed dial: distortion is `14.3 ms / interval`. Measured against the KERNAL
jiffy clock; see `docs/70-driving-the-game.md`.

Two other VICE sharp edges already paid for: responses must be matched by
**request id**, because unsolicited events interleave and a naive reader
silently returns the *previous* request's data ([the desynchronised reads](50-experiments.md)); and reading RAM under I/O
needs the explicit `ram` bank.

## The two problems that are not about transport

**Overlays make addresses conditional.** The party lives at `$4D00` *while the
right overlay is resident*. Patching `$12D9` after the game had swapped a
different overlay into that space corrupted a live routine — see the warning in
[Getting past the copy protection](50-experiments.md). So a live backend needs **validate-before-trust**: read the region, check
it still decodes as a sane party, and block otherwise. For writes that check
should be mandatory.

**Batch aggressively.** Read the whole save image in one call, not sixty small
ones — `$4900`–`$64FF` in Pool of Radiance, and whatever `goldbox/c64_port.py` says for
any other title.
At network latency that is the difference between a usable map and an unusable
one.

## The actual first task is not the transport

**The party's map coordinates are in the `SAVEDGAME0` header**, not the
character record: `$49C0` (x), `$49C1` (y) and `$49C2` (facing), established by
walking known distances and diffing. `SAVEDGAME1` was the standing candidate and
is ruled out — walking leaves it byte-identical.

A save-file automapper could be built today: export a position from every save
and plot it. Drawing the *walls* around that position needs the `GEO*` files,
and **those are decoded** — four 256-byte planes over a 16×16 grid, with wall
art as a nibble per edge and passability as two bits per edge. See
[GEO is solved](50-experiments.md). **Which `GEO` file a given *save* is on is
`$4BC2`**, the loader's "currently loaded" cache copied into the header — see
[the area id](50-experiments.md) and `docs/41-memory-regions.md`. A *live*
mapper does not even need that, because the running game keeps the whole map at
`$0400` (below).

The live-memory version needs the same addresses read out of a running game
rather than off a disk, and `SAVEDGAME0` is a verbatim image of `$4900`–`$64FF`,
so the addresses are the same ones.

**Two things about that do not transfer to another title**, and both are settled
in code now rather than in prose. The base moves — `$4B00` in Curse and Silver
Blades — so every address here is `save_load_address` plus a payload offset, and
the descriptor carries it. And the header triple is **not what moves**: `$49C0`
is refreshed only when `$1A3C` flushes it, so the fallback reads the engine's
own `$C04B`/`$C04C`/`$C04D` instead. That one is `C64Machine.live_position`, it is
*measured* per title — Pool of Radiance, Curse (`docs/120` §4) and Silver Blades
(`docs/121` §5), and no others — and a title where nobody has measured it has
None there and gets no fallback at all rather than a plausible wrong square.

**And the area question is now answered, live.** The `GEO` file is a PRG loading
at `$0400`, and the game **does not relocate it**: `$0400` is the boot screen,
but in the world the screen has moved to `$CC00`, so the page is free and the
map is left where it lands. CONFIRMED in New Phlan — `$0400`–`$07FF` was
byte-identical to `GEO00` with 480/480 reciprocity, and a sweep of all 64K in
both the `cpu` and `ram` banks found no second copy. `ResidentGeo` reads it and
`Automapper.poll()` names the area outright every tenth poll, with `Fingerprint`
left running underneath as the contradiction check.

**Why the page is free is a property of the machine, not of the game.**
`$0400`–`$07E7` is where the C64 puts its screen at power-on, and it does not
have to stay there: the top four bits of `$D018` place the screen in 1K steps
inside the 16K bank that bits 0–1 of CIA 2 port A (`$DD00`) select. That is
where `automap/screen.py`'s two lines of arithmetic come from, and it is why
they have to be re-run on every poll rather than cached (*Commodore 64
Programmer's Reference Guide*, "Graphics Locations", pp. 101–102 — see
[152-commodore-manuals.md](152-commodore-manuals.md)).

A `FilenameDigits` strategy — read the two digits the loader patches into the
`GEO00` stem — was tried and is dead, and the code is gone. `$24B4`–`$24B9` in
the running game reads `50 55 5a 5f 20 87`, not `GEO00`; the resident stem is at
`$40FB`, and nothing writes to its digits, so the filename is assembled in a
scratch buffer elsewhere.

`Fingerprint` on its own cannot finish on positive evidence: squares occupied
and steps completed need **111 steps** to get New Phlan down to one candidate.
A single *blocked* step settles it, and `Automapper` now supplies one -- the
status line carries the game clock, so clock advanced + square unchanged +
facing unchanged is a blocked step in the current facing. See below.

`SAVEDGAME1` past `$83FF` is **not** the other thing the game saves: it is
resident code and a graphics buffer. So an explored-squares bitmap is either in
the `$2E0`-byte header or is not saved at all, and an automapper may have to
track exploration itself.

## If it is ever built

1. Find the coordinates by diffing saves (no emulator needed).
2. Implement the `Target` protocol with the VICE backend only.
3. Draw the map from `Target`, so it never knows which backend it has.
4. Add the Ultimate backend, and see whether the interface survives contact with
   a second, slower transport. If it does not, better to learn that at two
   backends than at five. **Done**: the interface survived on paper --
   `party_fix` needed `read` and nothing else -- and reads were then confirmed
   on a real Ultimate (`docs/161-c64-ultimate.md`).


## What was open, and is now built

### Sight passes through closed doors -- fixed

`Exploration.visit` walked outwards while `Geo.is_passable` was true, and that
is true for **any** edge whose barrier is not `SOLID` -- an ordinary door, a
`LOCKED` one, a `WIZARD_LOCKED` one. So the fog lifted off rooms behind doors
the party had never opened.

Right rule for *walking*, wrong one for *seeing*. **Measured before choosing**,
over every square of `GEO00`:

| rule | squares revealed per stand |
|---|---|
| `is_passable` | 7.27 |
| blocked only by a *locked* door | **7.27 -- identical** |
| blocked by **any wall art** | **5.49** |

`GEO00` has **no locked or wizard-locked edges at all**: 542 open, 361 solid,
121 art-and-passable. Across all 29 files there are 130 locked and 14
wizard-locked against roughly thirty thousand edges, so a barrier-based rule
fixes essentially nothing -- what over-revealed was ordinary **doors**.

`automap.state.can_see_through` is the rule: sight passes only through an edge
with `wall(...) == 0`. Locked and wizard-locked doors are a strict subset of
"has art", so they block too. `is_passable` is untouched -- movement and the
fingerprint still need it. The re-measurement after the change gives 5.49, as
predicted.

A doorway you have walked through does not re-open to view, which is a small
loss and the honest one: the map has no idea whether a door was left open.

### The live view is on this tab -- built

[100-live-view.md](100-live-view.md) planned a third tab; it is part of the
Automapper tab instead, because the map and the party's state are looked at
together and neither is much use alone.

```
+----------------+-----------------------------+
|  roster        |                             |
|  name AC HP    |          the map            |
|  one card each |    (right, not centred)     |
+----------------+-----------------------------+
|  where, clock, area, effects, loaded files   |
+----------------------------------------------+
```

| module | what it is |
|---|---|
| `automap/live.py` | the two reads and the dataclasses. No Qt, no backend knowledge; testable against a dictionary of bytes |
| `automap/panel.py` | the cards and the bottom strip |

`docs/100-live-view.md` put `snapshot.py` under `wish/live/`. It is in
`automap/` instead for one structural reason: the panel is part of the
Automapper *window*, which lives in `automap/`, and `wish/` imports `automap/`
rather than the other way round. Nothing else about that plan changed.

Two reads a poll in Pool of Radiance -- `$4900`-`$64FF` and the roster page at
`$8300` -- batched into a single `resume()` by `ViceTarget.read_blocks`, and
taken every fifth map tick, which is once a second at the default interval. Only
the visible tab polls at all.

**One read in every title after it.** Curse and Silver Blades load the save at
`$4B00` and fold the roster into its last page at `$6700`, so the page is in
hand already and asking for it again would be a round trip for bytes we have.
`live.memory_blocks(game)` is where that choice is made and `goldbox/c64_port.py` is
where the numbers are; nothing in `automap/live.py` holds an address (#29 (The live reader uses Pool of Radiance's addresses on every title)).

### The blocked step -- wired up

`Fingerprint.record_blocked()` had nothing calling it, because the mapper cannot see
key presses. It does not need to: the status line carries the game clock, and
**clock advanced by one minute + square unchanged + facing unchanged** is a
step the game blocked. Positive evidence needs 111 steps to identify New Phlan;
one blocked step settles it, because impassable edges are rare.

Guarded three ways -- both fixes must come from the status line (the fallback is
only reached in camp, combat and menus, where an advancing clock is not a step),
the clock must
have advanced by exactly one minute (longer is searching or camping; zero is
standing still), and the facing must not have changed.

**Unconfirmed against the running game: whether a bump costs a minute at all.**
A move does. If a bump costs nothing this never fires; if bashing a locked door
costs a minute it records a false blocked edge, which is what
`Fingerprint._narrow` now absorbs -- it will not narrow to zero candidates,
keeps the last set that fitted, and counts the contradiction instead.

## Giving up on a connection, and hanging up while doing it

**VICE serves exactly one binary-monitor connection**, so a connection wish
gives up on and does not close is one it then competes with itself for. That is
what a random mid-session disconnection turned out to be (`#151 (The automapper loses VICE and cannot get back in, because it never hangs up the connection it gave up on)`): `close()`
was guarded on `_open`, every give-up path cleared `_open` before raising, and
`wish/window.py` keeps a second reference to the dead target in
`mapper.target`, so the socket stayed open and VICE went on serving it.

Measured on slot 1 with one connection held and a second client attaching, which
is exactly the state wish left itself in:

| attach attempt | what wish reports | how long |
|---|---|---|
| first | `MonitorBusy`, "something else is attached" | 1000.8 ms |
| second | `NotConnected: timed out` | 5004.7 ms |
| third | `NotConnected: timed out` | 5004.5 ms |

and `monitor_listening()` answered True, True, then False after 250.6 ms. Each
failed attach leaves another connection in VICE's accept queue; once it is full
every connect to the port hangs for the socket timeout. **It does not recover on
its own.** The 5004 ms is `Monitor`'s own `timeout=5.0` and not a measurement of
the emulator.

So `ViceTarget` hangs up **where the give-up happens** -- `_lost()` logs which
exception it was, closes the socket and returns the `NotConnected` -- rather
than leaving it to a caller. `close()` is unconditional and idempotent, and
`MonitorError` counts as a lost connection alongside `OSError`: it is a
`RuntimeError`, so it used to escape every handler with the connection kept.
After the fix the same situation reattaches in 117 ms.

Three facts from the same session, so nobody pays for them twice:

* **A read that times out does not leave the stream out of step.** On one
  connection, a `read($0400, 40)` given 0.5 ms to answer raised `TimeoutError`
  and the next two reads of `$A2` on the *same socket* both came back correct.
  So the give-up path needs no resynchronisation and a timeout is safe to
  retry on: what has to happen after one is the hanging up, and nothing else.
  `tools/gui/monitorchain.py` step 5.
* **Abandoning a socket does not freeze the game.** The jiffy clock at `$A2`
  went 42 to 164 across two seconds after a socket was closed with no `EXIT`
  sent -- VICE resumes when the connection drops.
* **Polling is nowhere near slow enough to be the trigger.** 3000 round trips
  idle and walking: median 9.5-13.9 ms, worst 32.6 ms, none over `SLOW_MS`.
  What made VICE go quiet for five seconds in the first place is still
  **UNKNOWN**.

## The travel grid: a third answer, not a missing one

**CONFIRMED in the running game, 2026-09-03** -- `tools/gui/mapmarker.py` on pool
slot 2, photographing the real map tab after every step -- **found** `party_fix`
producing **nothing** while the party was on the overland travel grid, so
`Automapper.poll` returned before anything was recorded and `AutomapState` kept
its last square, facing and `Geo`. `#205 (A party that walks out onto the
travel grid leaves the automapper's marker behind)` fixed it; this section
used to describe that broken state and now describes what replaced it.

| what the game shows | what the map showed, before the fix |
|---|---|
| `OUTDOORS 21:16 7,29` one step after leaving the Slums | `(14,4) facing W`, `The Slums`, marker on the square the party left |
| `OUTDOORS 22:02 7,28` on a save that starts outdoors | an empty grid, `square --`, `identifying...` |

Neither source survived out there:

* the **status line** was blocked by `_plausible`, which caps y at `GRID` = 16 --
  a dungeon's size -- while wilderness y runs to 28 and 29. North of row 16 it
  was worse than blocked: the loose `RE_STATUS` took the final `S` of
  `OUTDOORS` for a facing, so a party there read as a *plausible indoor* fix on
  a square it had never stood on -- the same fault `#189 (The emulator driver
  cannot move a party on the travel grid, and reads its facing out of the word
  OUTDOORS)` fixed in `tools/c64/session.py` and not here, until `#205 (A party that walks out onto the travel grid leaves the automapper's marker behind)`;
* the **fallback**, `C64Machine.live_position` = `$C04B`, read `4C 2F C5` outdoors,
  unchanged over four steps: `DUNGEON` is not the resident overlay there, so
  those are somebody else's code bytes and not a triple. Indoors the same three
  read `0F 04 03` then `0E 04 03`, matching the status line, while `$49C0`
  lagged a move at `0F 04 03`.

**What `#205 (A party that walks out onto the travel grid leaves the automapper's marker behind)` added.** `automap/target.py`'s `party_fix` now tries a second
status pattern, `OUTDOORS +(\d+):(\d+) +(\d+),(\d+)`, plausible over the travel
grid's own 18x36 window rather than the dungeon's 16x16 -- and `RE_STATUS`
itself gained the lookarounds `tools/c64/session.py` already had, so `OUTDOORS`
can no longer be read as a south-facing indoor line at all. The memory
fallback gained a third answer too, gated on `$49E6` (`goldbox/c64_port.py`'s
`Title.travel_grid`, **True for Pool of Radiance only** -- Curse and Silver
Blades ship no `SQRDATA`/`SQRPACI`/`WALLS` on any side, `docs/121-silver-blades.md`):
zero means the grid, and `$49C3`/`$49C4` is the window-local square; non-zero
falls through to the ordinary `$C04B` read exactly as before. `automap/state.py`'s
`AutomapState.outdoors` carries the flag to the tab: nothing is added to the
explored set or the fingerprint while it is set, and `Automapper.poll` runs
the resident check unconditionally on the first indoor fix after it, since
`_started` being False leaves no jump for the ordinary crossing guard to
notice.

Everything else on the tab was unaffected either way -- the roster, the clock
and the Quest Log keep up, because `poll_live` reads its own blocks. The world
itself -- terrain, the world coordinate, which window the party is on -- is
drawn on Pool of Radiance's travel grid:
[113-world-map.md](113-world-map.md) is the research and
[217-drawing-the-wilderness.md](217-drawing-the-wilderness.md) the build.

## A third machine: the Amiga

The Gold Box titles shipped on the Amiga too, and the automapper has a layout
row for all four: `automap/amiga.py` is a `Target` over an Amiga emulator's
own debugger. WinUAE on Windows and FS-UAE on Linux are supported; FS-UAE on
Windows or macOS is not, because `wish.fsuae.listening` reads `/proc` and the
connection helper runs on Linux only.
`docs/143-winuae-debugger.md` is the WinUAE transport, and the ticket is
`#37 (Automap the Amiga version, not just the C64)`.

**`MACHINES` has one row per title, found by an anchor string.** Each row names
the executable, a string that occurs in that title's executable and in no
other, the data-hunk offsets of the party's x, y and facing, and the pointer to
the resident `GEO` block. Silver Blades stores them as bytes and Curse as
words. Pools of Darkness' row also carries an overland pointer and flag: while
the flag is 1 the party is on its 38-by-15 overland, where the square bytes
keep the last indoor square, so `AmigaTarget.fix` answers a world-map fix and
the tab is blank rather than showing that stale square. Pool of Radiance's row
has `segments` and a travel grid, under "The flags, the fork and the maps".

**Four transports, one `AmigaTarget`.** The target owns the Amiga's memory map
and the transport decides how a read or a write reaches it:

| transport | reaches | how a read goes | how a write goes | halts the machine |
|---|---|---|---|---|
| `WinuaeDebugger` | WinUAE, from Linux through the Windows VM | F11, then `S <file> <addr> <n>` and `g` typed into the console, dump read back as base64, one `ssh` a batch | `W <addr> <bytes>` lines in the same batch | yes |
| `WinuaePipe` | WinUAE, through its own named pipe, from Linux through the VM | `DBG S ...` down the pipe between two emulated instructions, one `ssh` a batch | `W <addr> <bytes>` lines in the same batch | no |
| `WinuaeLocalPipe` (`automap/winuae.py`) | WinUAE, from Wish on the same Windows machine | `DBG S ...` down `\\.\pipe\WinUAE` in a Python call, one range at a time | `DBG W ...` lines of 16 bytes, at most 64 bytes a call, each receipt checked and the range read back | no |
| `FsuaeGdb` | a patched FS-UAE on the same machine, through the helper | a GDB-remote `m` packet over a loopback socket, answered from the emulator's frame handler | `M` packets of at most 64 bytes inside chip or slow memory, each answered `OK` | no |

`FsuaeGdb` is the one a player on Linux uses and `WinuaeLocalPipe` the one a
player on Windows uses: no console, no keypress, no `ssh`. The two `ssh`
transports are this project's test rig. `AmigaTarget.write` goes through a
transport's `write_memory` when it has one and `AmigaTarget.can_write` says
whether a write can reach the machine, which is what the Action buttons ask.
`verify=False` skips WinUAE's read-back for a write the game consumes within a
frame, such as the key buffer; FS-UAE has no read-back, only the emulator's
`OK`. The server closes its *listening* socket when a client goes, so one
connection is all a run of the emulator ever gets.

**What was measured on a running machine.** Amiga Silver Blades (2026-09-08):
the shipped `Automapper.poll()` named the area from the block the game itself
had loaded, followed a party through a turn and a step, would not move on a
step the map says is impassable and the game blocked too, and held its fix
while a shop menu was up. `automap/target.py`, `automap/live.py`,
`automap/state.py`, `automap/render.py` and `goldbox/geo.py` were untouched by
any of it.

Through Wish's own window on a patched FS-UAE, the marker matched the game's
position line, and a step taken while Wish was closed showed on reopening with
the same helper alive, on Pool of Radiance (New Phlan and the wilderness),
Curse (Buccaneer Base, `GEO01`), Silver Blades (`GEO10`) and Pools of Darkness
(`GEO21`, where the tab went blank on the overland). Under the test driver's
`session --window`, which builds the same tab, the party was followed across an
area change on Pool of Radiance (the three wilderness windows), Silver Blades
(New Verdigris into The Ruins) and Curse (the Dalelands map and the sewers).
**No area change has been watched through Wish's own window on any title.**
On WinUAE 6.0.3 Wish's own window followed Pool of Radiance through a turn and
two steps; Curse, Silver Blades and Pools of Darkness have been read only by the
tools there, and Pools of Darkness not at all.

### What the shared code had to learn, and it is one method

`ResidentGeo` read the C64's map block at a fixed `$0400`, because the C64's
loader leaves the `GEO` file where it read it and never moves it. The Amiga's
loader **allocates** the buffer, so there is no fixed address: the engine's own
map-indexing routines dereference a small-data global holding it. So
`ResidentGeo.address_now()` asks the backend where its own block is, with
`getattr`, the way `read_fix` and `screen_banks` already ask for `fix` and
`banks` — and a backend that cannot say keeps the fixed address every backend
had before. It is asked every poll rather than cached, because an area change
is exactly when the pointer may move.

### What is the C64's, in a program that mostly is not

| what | where | why it is the C64's |
|---|---|---|
| the status line | `target.party_fix` | a 40x25 PETSCII screen at a VIC-derived address. The Amiga answers `fix` itself from the engine's globals and never reaches it |
| the banking capability | `target.screen_banks`, `automap/vice.py` | a 68000 has one memory, so the capability is absent and `screen_banks` hands back the one reader |
| `RESIDENT_GEO`, `SEARCH_RANGES` | `automap/area.py` | `$0400`, and a sweep of `$0400`-`$CFFF`. `ResidentGeo.search()` cannot run on an Amiga: wrong ranges, and each region is a round trip |
| `_blocked_step` | `automap/state.py` | requires **both** fixes to come from the status line, so it never fires on a backend whose every fix is `"memory"` |
| `_running`'s cheap proof | `automap/state.py` | a status line proves a Gold Box game for free on the C64; on the Amiga only the resident map block can, which costs two round trips |
| `RESIDENT_EVERY`, `PROVEN_FOR`, the 200 ms timer | `automap/state.py`, `automap/window.py` | tuned to a poll costing 14 ms of emulated time |
| the live party tab, the Action buttons, Level up, Fast Travel | `automap/live.py`, `automap/actions.py` | the C64 save image at `Game.save_load_address`, and writes to C64 addresses. An Amiga gets `automap/amigaparty.py`, `automap/amigaactions.py` and `automap/amigafasttravel.py` instead; Level up is off on every Amiga title |
| combat, the combat log, the roll reader | `combat.py`, `combatlog.py`, `rolls.py`, `screen.py` | all read the C64 text screen |
| the map loader | `automap/maps.py` | walks a D64 directory for `GEO*` files first, and reads Amiga disk images only when it finds none |

Everything else transferred unchanged: `Fingerprint`, `render`, `notes`,
`Exploration`, `AutomapState`, `goldbox.geo`, and `ResidentGeo` itself.

### The maps are in one container, not one file each

The Amiga keeps every map of a title in `GEO.GLB`, a `GLIB` container on the
second disk — `/DISK2/GEO.GLB` on Silver Blades and `/DISKB/GEO.GLB` on Curse,
so `automap.amiga.load_maps` searches the image rather than tabulating a path.
Block 0 is an index of `(id, block)` pairs and the rest are 1024 bytes each.
They come back keyed `GEO{id:02X}`, which is the C64's own filename for the
same area, so an Amiga party's map is drawn on the same sheet and reads the
same notes: 17 maps for Silver Blades and 16 for Curse, all 33 plausible by
`automap.area.looks_like_a_map`.

### What a poll costs depends on the transport

Over WinUAE's console route a read is an `ssh` round trip plus a typed batch,
and a poll costs seconds. Over the FS-UAE socket it costs one frame's wait.

| what | WinUAE console | FsuaeGdb |
|---|---|---|
| one poll, position only | 10-22 s | about 10-20 ms |
| a poll that also re-reads the resident map | 31-50 s | one more packet |
| 512K of memory, searched on this side | 13-22 s | one packet, but the emulated machine misses a frame |

So `read_blocks` matters over the console for a reason that has nothing to do
with VICE's -- several ranges in one round trip is one `ssh` rather than
several -- and does not matter over the socket, where a transport with a
`read_memory` is asked for each block directly.

### Which title is running, and a target that is not a C64

`automap.amiga.locate_machines(read, machines)` reads each region of the
Amiga's memory once and searches it for every title's anchor string, so asking
after two titles costs one sweep. It returns `{title: [bases]}` -- a title with
more than one base, or two titles at once, is reported for the caller to
block and never resolved by taking the first. `AmigaTarget.locate()` is the
same search for one title.

**`AmigaTarget.c64_memory` is `False`**, an optional capability the window reads
with `getattr(target, "c64_memory", True)` the way it reads `halts_on_read`.
The C64 roster, the five live actions, Fast Travel, Level up and the combat
reader all read C64 addresses, which on a 68000 are ordinary chip RAM: the reads
succeed and decode the game's own unrelated bytes. So `AutomapBinding._refresh_roster`
never hands such a target to them: it calls `_refresh_amiga`, which gives the
buttons the `automap/amigaactions.py` classes, the cards `amigaparty.read_party`
and the Fast Travel row `automap/amigafasttravel.py`. `poll_battle` reads no
fight from it and the window's Level up handler returns at once. A layout with
no row of its own, or a machine that is not running the title the window was set
up for, leaves every button greyed. `automap.busguard`'s `BusGuard.clear` reads
the attribute too: it returns True before any read for such a target, so a
halting Amiga transport is not asked for a byte of `$DD00` on every tick.

### The FS-UAE backend's two pieces

`wish/fsuae.py` holds what a window backend needs and nothing that a player
reads.

* **`listening(port)` never connects.** It reads `/proc/net/tcp` and
  `/proc/net/tcp6` and says yes for a row in state `0A` on `0100007F:<port>`
  (loopback) or `00000000:<port>` (every address). VICE's probe is a connect
  that is dropped at once, and the window probes every backend each time File >
  Preferences opens. The fork closes its listening socket when a client that
  had connected goes; whether a bare connect-and-close does the same has not
  been tried, and the probe does not depend on the answer. Where there is no
  `/proc` the answer is no.
* **`connect()` never connects to the fork; it reads through the helper.**
  The fork serves one client per run and closes its door when that client
  leaves, so `automap.fsuaehelper` holds the connection and outlives Wish. When
  no helper is alive and the fork is listening, `connect()` starts one detached
  (not more often than `HELPER_RETRY`) and raises `FsuaeError` at once, so the
  window shows its waiting line and asks again a second later; it never waits
  for the helper. The helper's socket is connected, and greeted, with
  `FsuaeGdb.POLL_TIMEOUT` (one second each), so a busy helper holds the window
  for two seconds at most and the next tick tries again. **A helper that dies
  after taking the fork's connection cannot be replaced:** the fork never listens again, so the player has to restart
  FS-UAE. `listening(port)` also says yes while a helper is alive.
  `connect()` opens the helper's socket once per emulator run and caches the
  transport, the title found on it and the data hunk's base together. The window
  detaches on any `NotConnected` and attaches again on its next tick, and
  closing an `AmigaTarget` leaves the transport open on purpose. A title that
  has not loaded yet raises `FsuaeError` (a `NotConnected`) with the transport still
  cached, and the memory sweep is not repeated more often than `SWEEP_EVERY`
  after one ends, because each 512K read makes the emulated machine miss a
  frame.
  A sweep reads 64 KB at a time. It stops for the tick after
  `SWEEP_DEADLINE` (one second) and keeps what it has read, so one `connect()`
  holds the window for about two seconds at most and the next tick goes on from
  there. What it keeps is thrown away if no piece is added for
  `SWEEP_CACHE_AGE` (five seconds), which catches a gap in the ticks. It does
  not detect a reboot or reload during a sweep whose ticks keep adding pieces;
  such a result is caught afterwards, by the "more than one place" check and by
  the anchor re-read at the next `connect()`. After a piece times out, the next
  sweep reads 16 KB pieces, and a finished sweep goes back to 64 KB. How long
  a piece takes on a real machine has not been measured. A transport
  whose connection has failed (`FsuaeGdb.lost`) is dropped and replaced; a read
  timeout is not that, and keeps it. Because GDB-remote has no request ids, a
transport that timed out drops whatever its socket holds before the next request,
so a reply that was only late is not read as that request's answer. Whether the
fork drops or answers a request that reaches it while the emulator is paused
behind its menu has not been measured. A read of at most 4 KB waits one second
(`FsuaeGdb.POLL_TIMEOUT`, a choice and not a measurement), as does each piece
of a sweep and the helper handshake, because a poll runs on the window's own
thread; the transport's own twenty seconds is for reads made off it. Each `connect()` re-reads the cached title's anchor at its base and, when
it is gone, forgets the title and sweeps again without closing the socket; a
different port gets a new transport.
* **Writes go through the helper too.** It forwards `m` reads and `M` writes
  and nothing else (a client's `k` would quit the player's game), and an `M` is
  one to 64 bytes inside chip or slow memory, answered with the fork's own `OK`
  or error. The helper publishes `writes` in its JSON and `connect()` sets
  `FsuaeGdb.can_write` from it, so a helper that does not forward `M` leaves the
  Action buttons grey. The socket is mode 0600 in a 0700 directory.

### The party in memory

**Each Amiga title keeps its party as a singly linked list of heap records**,
not at fixed addresses, and `automap/amigaparty.py` walks it. A data-hunk
global holds the first record's address; each record holds the next one's at a
fixed offset; the last link is NULL. Each record also heads two lists of the
same kind, its items and its running effects. Every offset was read from the
title's save routine (which walks the list to write it) and its loader, then
measured on FS-UAE. `head` and `current` are offsets into the data hunk
`AmigaTarget.locate` returns (`h32` on Pool of Radiance); the rest are record or
node offsets. CONFIRMED from the code, and live on two boots per title.

| Title | Head | Current | Record `next` | Record | Items: head, node, `next` | Effects: head, node, `next` | Slot byte |
|---|---|---|---|---|---|---|---|
| Pool of Radiance | `h32+0xAEE` | `h32+0xAEA` | `+0x106` | `0x120` | `+0xCA`, `0x41`, `+0x2A` | `+0x80`, 10, `+0x06` | `+0xC1` |
| Curse | `g3cf8` | `g3cfc` | `+0x18E` | `0x1AC` | `+0x152`, `0x42`, `+0x2A` | `+0xF2`, 10, `+0x06` | `+0x147` |
| Silver Blades | `g5168` | `g516c` | `+0x13A` | `0x154` | `+0xFE`, `0x46`, `+0x2A` | `+0x96`, 10, `+0x06` | `+0xF1` |
| Pools of Darkness | `g57a4` | `g57a8` | `+0x00` | `0x194` | `+0x08`, `0x42`, `+0x2A` † | `+0x04`, 10, `+0x06` | `+0xBD` |
| **Grade** | CONFIRMED: code and both boots | CONFIRMED: code; read equal to the head after every load | CONFIRMED: code and both boots | CONFIRMED: the writers and the loaders' reads, and records equal to the file | CONFIRMED for Pool of Radiance and Curse (code and both boots); † for Silver Blades and Pools of Darkness | CONFIRMED: code and both boots; Silver Blades' from 10 nodes | CONFIRMED: code, and 0-5 on every member |

† Measured from dumps only. Silver Blades' item list is read from its writer
and reader, but neither save had items, so the only live nodes are the demo
party's two long swords. Pools of Darkness' head at `+0x08` is from its writer;
its loader was not read, and the node size `0x42` and the link `+0x2A` come
from the dumps (174 nodes, 0x46 apart, each a NULL-terminated chain whose
twenty bytes at `+0x2E` equal the file).

The routines, as file offsets into each executable (`tools/amiga/amiga68k.py`):
Pool of Radiance's save `0x27750`, record writer `0x2646C`, reader `0x267CE`,
append `0x26EAE`; Curse's save `0x26AF8`, writer `0x260C4`, reader `0x25056`,
append `0x26E2C`; Silver Blades' save `0x27C10`, writer `0x2713C`, reader
`0x268C0`, append `0x27F18`; Pools of Darkness' save `0x270E0` (it stops at
eight), writer `0x26338`, append `0x27394`; its loader was not read. Each
save routine is the same loop:

    movea.l  -$4306(a4), a2     ; g3cf8, the head (Curse)
    move.l   a2, d0
    beq.b    done               ; NULL ends the list
    ...                         ; write the record at a2
    movea.l  $18e(a2), a2       ; the record's next
    bra.b    loop

**A live record is the saved record, byte for byte, except for its pointer
longwords.** Each writer writes the record straight out of its heap block
(`write(fd, record, 0x1AC)`; Pool of Radiance `fwrite(record, 1, 0x120, fp)`),
and each loader reads the file into a fresh block and then rewrites the
pointers: Pool of Radiance clears `+0x106`, `+0xCA`, `+0x80` and `+0x10A`;
Curse clears `+0x18E` and `+0x192` and `0x1A45C` rebuilds the thirteen
readied-item pointers at `+0x156`; Silver Blades clears `+0x13A` and `+0x13E`.
So a file holds whatever heap addresses the party had when it was saved.
Pools of Darkness' writer puts the **item count** into `+0x08` for the write
and the pointer back after, so that longword is a count in the file and a
pointer in memory; its `+0x0C`-`+0x3F` are thirteen readied-item pointers.
Measured right after the game's own LOAD, memory dumped whole and each record
compared with the file it came from:

| Title, save | Boots | Records | Record bytes differing outside the pointers | Item nodes equal outside `next` | Effect nodes equal outside `next` |
|---|---|---|---|---|---|
| Pool of Radiance, `poolgame` slot B | 2 | 6, 6 | 0 of 12 | 34 of 34 | 12 of 12 |
| Curse, `CurseA` slot A | 2 | 4, 4 | 0 of 8 | 18 of 18 | 18 of 18 |
| Silver Blades, `Secret 1` slots B, A | 2 | 6, 6 | 0 of 12 | none in either save | 10 of 10 |
| Pools of Darkness, `POD 3` slots B, D | 2 | 6, 6 | 0 of 12 | 174 of 174 (the 20 bytes at `+0x2E`) † | 62 of 62 |
| **Grade** | | | CONFIRMED: 44 records, two independent boots per title | CONFIRMED for Pool of Radiance and Curse; † from dumps only for Pools of Darkness, and none measured for Silver Blades | CONFIRMED |

The two boots per title are independent: the first ran Kickstart 1.3 and the
second Kickstart 2.04, which moved every data hunk (Pool of Radiance
`0xC4E298` to `0xC5BAF8`, Curse `0xC4E238` to `0xC5D7B0`, Silver Blades
`0xC56BF8` to `0xC638E0`, Pools of Darkness `0xC57B18` to `0xC647C8`) and put
Pool of Radiance's records in chip memory (`0x4E844`). Two Kickstart 1.3 boots
of the same disks gave the same addresses to the byte, so a repeat boot tests
nothing. Names and current hit points read through the codec offsets matched
the game's own party list in 32 of 32 rows (16 members of Pool of Radiance,
Curse and Silver Blades, each on both boots); every member was at full hit
points, so the maximum is not told apart from the current value, and Pools of
Darkness' list was not on screen when it was dumped.
Silver Blades' only items were in the demo party (two long swords, read
through `+0xFE` and `+0x2A`).

**In a fight the monsters join the same list.** In Silver Blades' demo fight
the walk from `g5168` found the three party members and then two Ancient
Dragons, each a full record with slot byte 8, and a dragon's hit points fell
between two dumps. So a walk must allow more than eight records and a reader
keeps only slot bytes 0-7; `amigaparty.walk` returns a monster as a bare
record without following its item or effect lists, so a stray pointer in a
monster cannot hide the party, and `read_party` drops it. CONFIRMED on
Silver Blades (the demo fight), Pool of Radiance (three kobolds, slot byte 8)
and Pools of Darkness (23 monsters with slot bytes 8 to 11, one byte per kind
of monster); Curse has not been seen in a fight.

**The mode byte**, CONFIRMED live where a value is given:

| Title | Byte | Values read | In a fight |
|---|---|---|---|
| Pool of Radiance | `h32+0xBA` | 3 on the travel grid | 5 |
| Curse | `g3d56` | 0 at the party menu, 4 walking, 3 on the world map | not reached; 5 from the code (PROBABLE) |
| Silver Blades | `g525c` | 0 at the party menu, 2 at the journal prompt, 4 walking | 5 (the demo's fight, and griffons and a hill giant met by walking) |
| Pools of Darkness | `g5b12` | 0 at the party menu, 2 once loaded, 4 after a fight | 5 |

**After a Pools of Darkness fight, while `INSERT DISK 1` is up, the list head
reads NULL** with the records still in memory, so `read_party` gives None and
every action stays off there.

**Which writes are proven.** A row's `confirmed` set names an action only when
its field was written, seen on the game's own screen and kept across a game
step. Its `measured` set names the facts the Action gate asks for besides:
`hp_max`, the maximum seen on the sheet and kept across a step, which Heal
needs, and `combat_value`, the mode byte read in a fight, which every action
on Curse needs because Curse's fight value is otherwise from the code.
Measured with the `session` driver's `poke` (#37 (Automap the Amiga version,
not just the C64), the R2, R3 and gap-run comments):

| Title | `confirmed` | `measured` | Measured but not confirmed |
|---|---|---|---|
| Pool of Radiance | heal (`0x11D`), store and restore spells (`0x17`, 21 bytes), identify (item `+0x35`, mask 7; `+0x36` and `+0x37` did nothing) | `combat_value` | quickfight `0x111`: QUICK sets it, but writing 0 did not bring the character's turn menu back in a fight; `hp_max`: the sheet shows no maximum |
| Curse | heal (`0x1A9`), spells (`0x1E`, 84 bytes), identify (`+0x36`, mask 7; `+0x35` did nothing) | none | the fight value: no fight reached in three boots; `hp_max` (`0x78`): seen on the sheet, not read again after a step |
| Silver Blades | heal (`0x152`), spells (`0x1E`, 75 bytes), identify (`+0x36`, mask 7) | `combat_value` | `hp_max` (`0x70`): seen on the sheet, not read again after a step |
| Pools of Darkness | heal (`0x191`), spells (`0xCC`, 141 bytes), identify (`+0x36`, mask 7) | `hp_max` (`0x81`), `combat_value` | quickfight `0x185`: never written |

So with a writable emulator and no fight, a player would see Heal enabled on
Pools of Darkness only, Save spells, Restore spells and Identify on Pool of
Radiance, Silver Blades and Pools of Darkness, Quickfight off on none, and
nothing on Curse until a Curse fight is read. A button that is not enabled
shows the approved "Action unsupported" sentence with the title and "(Amiga)"
added (`amigaactions.unsupported`), and a title or backend that cannot write
(`AmigaTarget.can_write` false) enables Save spells only. Level up is off on
every Amiga title (`roster.set_levelling(False)`), and Heal needs `hp_max`
measured. `docs/212-the-live-tab-per-title.md` has the per-title result.

**The party cards read only the name, the hit points and the quickfight flag.**
`window.amiga_snapshot` leaves class, level, experience, armour class and THAC0
empty, so a card draws `?  L0`, experience 0 and armour class `--`, and the
hit-point bar's tooltip still names the C64's source. This is a defect, not a
design: each title's record carries those fields and the cards must show them.

**Pool of Radiance's record block is one byte short.** Its loader allocates
`malloc(0x11F)` (the size word before every record reads `0x123`, which is
`0x11F` plus the 4-byte word) and then reads `0x120` into it; the last byte
lands in the allocator's rounding. PROBABLE, from `0x24DC` and 12 records.

### Curse's world map

**Curse's Dalelands map is read from three engine values, all behind the data
hunk.** The script variables the C64 keeps at `$4Bxx`-`$4Exx` are `u16be` words
at `[g3d00] + 2 * address` (the VM's setter `0xceac` and getter `0xd09c`; the
pointer is the allocation minus `$9600`). CONFIRMED from `/Curse` and on
FS-UAE (three boots: the party entered the map three times, left it three
times, and a save made on it was loaded twice).

| What | Amiga | C64 counterpart | Values |
|---|---|---|---|
| Script in the buffer | `g5ce1`, byte | `$7F1B` | `$50`/`$51` on the map; set by the script-change opcode (`0x1e50c`) before the new script loads; 0 at the party menu after a load |
| Area id | `[g3d00] + 0x97E4` | `$4BF2` | lags: the departing id until the arriving script's entry returns |
| Indoors flag | `[g3d00] + 0x97CC` | `$4BE6` | 0 on the map |
| Place the party stands at | `[g3d00] + 0x9936` | `$4C9B` | 0 Tilverton, 1 Shadowdale, as the C64 |
| Place it is going to | `[g3d00] + 0x9938` | `$4C9C` | set when a destination is chosen |
| Game mode | `g3d56`, byte | -- | 3 on the map, 2 in camp there, 4 in a town |

**The square is not overwritten on the map**, unlike the C64's `$C04B`: it keeps
the last town square throughout, and on the way out it keeps it for 4 to 6
seconds after `g5ce1` names the town, until the arriving script's own `SAVE`s
place the party. No data-hunk byte marks that moment (twelve dumps of the hunk
across an exit), and the C64's view-drawn byte `$7EDB` has no Amiga
counterpart. So the reading that matches the game is: the map is up while
`g5ce1` (or, when it is 0, the area id) is `$50`/`$51`, and after that while
the area id is still `$50`/`$51` and the square still holds the bytes it held
on the map. `AmigaTarget._world_map_fix` is that rule, behind
`AmigaMachine.world_map`, and it gave a world-map fix from 1 s after `YES` on
entry, held it through the stale square on exit, and gave the sewer's `0,0 S` on
the first poll after the script placed the party, with the tab on `GEO03` at
that square. It costs two round trips a poll on Curse. It cannot tell an
arriving script that places the party on the very square the map left: the map
stays up until the area id changes. The live run, through the test driver's
`session --window`, is in [`50-experiments.md`](50-experiments.md), "Curse's
world map on the Amiga"; Wish's own window has not been on the Dalelands map.

**With only Amiga disks configured the world-map tab has no route page.** The tab
knows it is on the world map, the node and the destination, but
`automap/routes.py` reads `ECL50`, `ECL51` and `GDRIVE02` from C64 disks only,
and the Amiga marker cells for the Dalelands places have not been found (the
scripts are `ECL.GLB` blocks 23 and 24, byte for byte).

**`ECL.GLB` block numbers are not area ids.** Block 0 is a table of 25
(area id, block) word pairs; area `$50` is block 23 and `$51` block 24. The
engine loads through it: a save made on the map holds block 23 byte for byte.

### Fast Travel and Return without the program counter

**An Amiga trip needs only memory writes.** The C64's Fast Travel ends by
setting the PC to `NEWECL`'s tail. The Amiga engine is the DOS one, where
`NEWECL` (opcode `$20` in all four dispatch tables) loads the new script and
raises a flag the main loop acts on. So Wish can write a few of the game's own
statements (`SAVE` x, y, facing, then `NEWECL area`) into bytes past the end of
the loaded script, point the step entry at them, and deliver one key. The
game's interpreter then makes the area change, with its own loader, disk
prompt, came-from byte and arriving script. Measured under `fs-uae-gdb` in
all four titles: Curse (2 trips), Pool of Radiance (4) and Pools of Darkness
(3), then FT-L1 on Curse, Pool of Radiance and Silver Blades (a trip from New
Verdigris to The Ruins and its Return). Each started within one frame of the
key, and the party walked afterwards. **A Silver Blades trip to area 4 never
finished:** the game stayed on "LOADING...PLEASE WAIT" for 12 minutes with the
step entry still pointing at the statements, and why is not known.

The step entry is the word the main loop passes to the interpreter once a
forward key leaves the 3D menu, before the step is taken. Only `vm_init_ecl`
writes it, so the next script load also clears a redirect.

| | Pool of Radiance | Curse | Silver Blades | Pools of Darkness |
|---|---|---|---|---|
| `NEWECL` handler / `vm_init_ecl` (file offsets) | `0x286E6` / `0x954E` | `0x1E50C` / `0xC190` | `0x1E7E0` / `0xFE3A` | `0x1E828` / `0x103E2` |
| step entry word | `h32+0xAA` | `g584c` | `g732e` | `g72c6` |
| script buffer, `0x1E00` bytes | `[h32+0xA4]`; ECL address `A` at `+(A-$9900)` | `[g5006]+A` | `[g6956]+A` | `[g6ea6]+A` |
| cleared before a load | yes (`0x9718`) | yes (`0xC31A`) | no (`0xFF8E`) | no (`0x10502`); stale bytes seen live |
| area id | `h32+0x2F73` | `g5ce1` | `g79c9` | `g7a0a` |
| `SAVE` targets for the square | `$C04B`, `$C04C`, `$C04D` (facing 0-3) | same | same | variables `$34`, `$35`, `$11` |
| one-key buffer (flag, character) | none | `g3804`, `g3805` | `g4f6c`, `g4f6d` | `g5742`, `g5743` |
| menu kind / menu text | none (the menu is in locals) | `g1c24` / `g3342` | `g2384` / `g4a5e` | `g235e` / `g4f34` |
| **Grade** | CONFIRMED: code and 4 trips | CONFIRMED: code and 2 trips | CONFIRMED for the 2 trips to The Ruins and back; a trip to area 4 hung, so `automap/amigatrip.py` still holds its row unconfirmed | CONFIRMED: code and 3 trips |

**The key.** In Curse, Silver Blades and Pools of Darkness, writing `01 b8`
(pending, keypad 8) to the one-key buffer is read as a forward key. Pool of
Radiance's menu reads IntuiMessages itself, so the key there is a 52-byte
RAWKEY message (class `0x400`, code `0x08`, no reply port) placed in the
free buffer tail and linked onto the list of the game window's `UserPort`
(`[[h32+0x28]+0x56]`). The game's `ReplyMsg` marks it `NT_FREEMSG` and takes
the key. CONFIRMED live, 3 of 3. WinUAE's pipe also accepts
`EVT KEY_RAW_DOWN`/`KEY_RAW_UP`, which presses an emulated key without focus.
That is SPECULATIVE, read from its source and not sent.

**The gate.** In Curse and Pools of Darkness the 3D menu is waiting when the
menu kind reads 1, the menu text reads the world menu, the mode byte reads 4
and the key buffer is empty. At a "PRESS RETURN" text the kind read 2: 4 of 4
reads in Curse, 2 of 2 in Pools of Darkness. A key sent at the wrong prompt
was read and ignored at a "PRESS RETURN" text (Curse) and at a YES/NO menu
(Pool of Radiance), one sample each. Pool of Radiance has no menu global, so
its gate is the mode and view bytes only, and the gadget count below does not
tell its world menu from camp.

**Where the statements go.** The statements are 21 bytes, 27 with the
area-file `SAVE`. No reachable statement in any Pool of Radiance (29),
Curse (25) or Silver Blades (22) script names an address past its own end.
That is CONFIRMED by walking every script on the player's disks, and it holds
for Pools of Darkness too, now that its scripts are walked with its own operand
counts; the next section has the count, the free bytes per area and what the
two scripts with 2 free bytes can use instead.

**What the arriving script does.** It runs as it does for a walked exit, so
it may place the party itself. On a Return in Curse, Silver Blades and Pools of
Darkness it moved the party to its own arrival square, over the statements
(Curse 7,13 E, the same square the C64 lands on; Silver Blades 15,8 W). Arriving
in Curse's Tilverton from the sewers replayed the game's opening ("all your gear
is gone"), on the C64 too; on the Amiga the party's items were still there
afterwards. In Pool of Radiance a trip out of the wilderness grid into New Phlan
worked, where the C64 blocks it, and left fragments of the wilderness picture
around the 3D frame; a `SAVE` of `$49E6` did not clear them and the walked boat
exit leaves none. A trip onto the grid with `$49C3`/`$49C4` written landed on the
written square in 3 of 3 trips, then the game asked the boat question. A jump
to the dock lands on the recorded square (2 of 2), where the walked boat lands on
15,1 W. Standing on a door square and sending the forward key ran the door's own
exit and question.

**Setting the program counter is possible but not needed.** `fs-uae-gdb`'s
`P` packet cannot write PC or SR, and its A-register case writes past the
register file (`0x72E3D5`). It has no `G` handler. Its `qRcmd` `console r PC
<hex>` works on a machine halted by the `0x03` break: measured once, with the
machine resumed by `vCont;c`. The server sends no reply to a console command
with no output. WinUAE's `DBG r PC <hex>` reaches `m68k_setpc` with no halt,
and 3 of 30 idle samples were in supervisor code, so it is not safe there.

The three live runs, the static reading per title and the open design
questions are the R5 comments on #37 (Automap the Amiga version, not just the
C64).

**What the window offers.** `automap/amigafasttravel.py` offers a trip only when
the title's row in `automap/amigatrip.py` is `confirmed`, the target can write,
the gate passes and the area's script has the free bytes. A trip that behaves
differently from the C64's stays held (`Difference.offered` False) and the
button reads the approved unsupported sentence. Held today: Return on every
title; Curse's arrival in Tilverton; on Pool of Radiance every trip (`weak_gate`),
leaving the grid, doors and a leg onto the grid. Silver Blades' row is not
confirmed, so it offers nothing; Pools of Darkness has no area table, so its list
is empty.

### Fast Travel's free bytes, init entries and gates, read from the code

`tools/amiga/tripspace.py` computes each area's free bytes from the player's
disks at run time; `tripspace.py refs TITLE` repeats the script walk. Static
reads of `/program`, `/Curse` (`8d4ceba86e4b`), `/Secret` (`ba6c8b5ed94b`) and
`/Pools of Darkness` (`a572e95a7bc0`, `6f8fee2dd8ea`, `7dfac2362807`).

**Free bytes are `0x1E00` less the script's length on disk.** CONFIRMED from
the loaders: Pool of Radiance (`0x9718`) copies an `ecl.dax` block from its
third byte, so the length is the index's unpacked size less 2. Curse,
Silver Blades and Pools of Darkness read the whole `ECL.GLB` block that block
0's `(area, block)` table names (Curse `0x13C2C`; Silver Blades' `0x1722A` is
the same routine). No loader caps the copy at `0x1E00`, and no script on the
player's disks is longer. The tier counts below agree, area for area, with
`automap/amigatrip.py`'s `script_lengths` (132 of 132):

| Library on disk | Scripts | Not tier 1 | Fewer than 3 bytes free |
|---|---|---|---|
| Pool `ecl.dax` (`18266efce854`) | 29 | 1, 10, 20, 24, 28 (tier 3 once the 52-byte message is counted) | none; area 20 has exactly 3 |
| Curse `ECL.GLB` (`d9529ba83f50`) | 25 | 16 (16 free) | none |
| Silver Blades `ECL.GLB` (`8c247ad1e1ac`) | 22 | 32, 50, 65, 66 | none |
| Pools of Darkness `ECL.GLB` (`becddc5926af`, four of the player's disk sets) | 56 | 16, 20, 32, 33, 37, 50, 52, 66 | 32 and 66 (2 each) |
| Pools of Darkness `ECL.GLB` (`adb9afbd3eca`, the `[a]` set) | 56 | 20, 22, 69, 74, 81, 83 | none |

The two Pools of Darkness libraries are different releases of the scripts, and
the `[a]` set's executable is packed, so its operand counts were not read.

**Pools of Darkness' operand counts are its skip switch's.** CONFIRMED: the
routine a false `IF` calls to step over the next statement (`0x1182E`) is a
switch with one case per opcode, each loading a fixed number of operands or a
fixed number and then as many more as the last one says. Against Silver
Blades' table, eleven opcodes differ: `$0C` 4, `$1D` 0, `$1F` 1, `$21` 2, `$22`
0, `$23` 0, `$27` 4 then counted, `$29` 0, `$2C` 1, `$31` 2 then counted, `$37`
2. Each agrees with the opcode's own handler; `$23` clears the text window and
ends in the `EXIT` handler, so nothing runs after it. Walked with these counts,
33,715 statements in 56 scripts decode with none undecodable and none naming
the free tail; with Silver Blades' counts the same scripts give 547
undecodable offsets and 9 tail references. The `[a]` library, walked with the
same counts, gives 33,754 statements and none of either (PROBABLE for that
release, whose own executable was not read).

**Curse's and Silver Blades' skip switches step over six opcodes differently
from their handlers**: one byte over `$15`, `ONGOTO`, `ONGOSUB` and
`HORIZMENU`, one operand over `$34` and `$36`. No reachable `IF` in the 47
scripts is followed by one of them, so no player meets it. Walked with the
handlers' counts, Curse gives 14,183 statements and Silver Blades 15,321, with
none undecodable and none naming the tail, which agrees with the walk made
with the C64 tables. CONFIRMED.

**The init entry is the room for the two scripts with 2 free bytes.**
CONFIRMED from the code for Pools of Darkness: the init entry runs only in the
loop after `NEWECL` loads a script (`0x20180`) and on the start and load path
(`0x2028A`), which reloads the script from disk first (`0x10502`) whatever the
saved game holds. In both scripts the init entry is `$8014`, its first
statement is 6 bytes, and no statement reachable from the other four entries
covers or names its first 3 bytes. So `NEWECL` written over `$8014`, with the
step entry pointed there, runs only through Wish's redirect, and a trip that
does not fire puts the 3 bytes back. Pool of Radiance (`0x2B216`, when
`h32+0xBF` is set) and Curse (`0x20B0A`, when `g5856` is set) skip that reload
and run the init entry over the buffer they already hold, so there a save made
while an init patch is armed would run it on load. Neither needs the patch for
`NEWECL`. Pool's five tier-3 areas have 67 to 288 bytes from their init entry
that no statement from another entry covers, enough for the 52-byte message,
with that risk; PROBABLE, because that count does not look for operands naming
those bytes.

**Pool of Radiance's world menu leaves its gadgets on the window.** CONFIRMED
from the code and live, but the gadgets are no marker: `displayInput` (`0x319FE`) adds one boolean gadget per menu
word to the game window (`[h32+0x28]`) with `AddGadget` at position 0, and
removes them all with `RemoveGadget` on each of its six ways out, so while the menu waits
the window's `FirstGadget` (`+0x3E`) chain holds them. The gadgets are in the
routine's stack frame, `0x2C` bytes each: `TopEdge` (`+0x06`) 192,
`Height` (`+0x0A`) 8, `GadgetID` (`+0x26`) 1000 upwards, `LeftEdge` (`+0x04`)
eight times the word's column and `Width` (`+0x08`) eight times its length plus
2. The world menu (`0x2F39E`, view 1) has no prefix, so its six gadgets, head
first, are IDs 1005 to 1000 at left 232, 176, 120, 80, 40, 0 and width 34, 50,
50, 34, 34, 34. Read live (FT-L1), the chain matches that on every menu, and its
length equals the number of choices: the world menu and camp both hold six
gadgets with IDs 1005 to 1000, the camp rest-time menu seven (1006 to 1000), the
armourer's YES/NO two (1001, 1000) and a shop menu five (1004 to 1000). So the
gadget count cannot tell the world menu from camp, and `weak_gate` in
`automap/amigatrip.py` stays until another read does (gadget positions or text,
or the menu text). Whether the chain is absent at a "PRESS RETURN" text was not
reached.

**Every title sets the area byte before the new script loads.** CONFIRMED
from the four `NEWECL` handlers: each stores the came-from word, then the new
area id (Pool `h32+0x2F73`, Curse `g5ce1`, Silver Blades `g79c9`, Pools of
Darkness `g7a0a`), then calls the loader, which shows "Loading" and opens the
library, so any disk prompt comes later. A trip watched by its area byte is
seen to fire before the player is asked for a disk.

**The area-file byte decides which monsters and items load, not which script.**
The loaders name `ECL%d` (Curse, Silver Blades) with the area-file byte, then
look the area up in block 0 and, only if it is missing, look up 100 times the
file number plus the area. CONFIRMED from the code. No `ECL.GLB` or `GEO.GLB`
id on the player's disks is 100 or more, so a missing area-file write never
loads the wrong script or map. Curse's `MONCHA.GLB` (16 ids), `MONITM.GLB`
(10) and `MONSPC.GLB` (6), and Silver Blades' `ITEM.GLB` (5), do hold such
ids, so the byte decides which of those the arriving area finds. The scripts
set it in 25 Curse and 36 Silver Blades statements, and every value written
just before a `NEWECL` with a fixed destination matches that destination's
`disk` in `goldbox/areas.py` (12 of 12 and 11 of 11 destinations). So the `SAVE` is needed when the destination's disk differs
from the byte's current value. PROBABLE: that the byte is `$7F12`, which the
scripts write, and that the VM's `$7F12` reaches `g5858` (Curse) and `g5191`
(Silver Blades) through the routine at Curse `0x13CCA` and Silver Blades
`0x172C8`, which also keep the old value in `g5b61` and `g5192`. A tier-2
direct write should set both. Pools of Darkness loads a fixed `ECL1` and has
no such byte.

**Silver Blades' gate is Curse's.** CONFIRMED from the code and live (FT-L1): at
mode 4 (`g525c`, dispatch at `0x2EDB2`) the world menu calls the horizontal menu
at `0x2A736`, which sets the menu kind `g2384` to 1 and copies the menu text
into `g4a5e`; `g2384` is 2 in the key wait at `0x29FFC`. The one-key buffer
(`g4f6c` flag, `g4f6d` character) is filled and read by the same routine as
Curse's `g3804`, address for address, and a `01 b8` there was consumed at once.
At the 3D menu `g4a5e` read "Area Cast View Encamp Search Look" (spaces, not
Curse's NULs), `g2384` 1 and `g525c` 4; in camp `g2384` and `g525c` read 2 and
`g4a5e` the camp bar; during the "LOADING" overlay `g2384` read 2 and `g525c` 4.
A "PRESS RETURN" text was not reached, so that reading is still unconfirmed.

**Curse's opening in Tilverton has no "done" flag.** CONFIRMED from the
script: area 1's init entry compares the came-from word `$4BF2` with 1 and
exits if they are equal; otherwise it places the party at 7,13 N and runs the
opening. No quest flag takes part. The C64's `ECL01` has the same test. No
script sends a party to area 1 (0 of 47 `NEWECL` statements in Curse's 25
scripts), so a party reaches area 1's init from another area only on a new
game and on a trip. So every Fast Travel or Return into area 1 from another
area replays the opening; CONFIRMED live on the Amiga and on the C64 (FT-L1 and
FT-C1: Return from the sewers on both). PROBABLE: a
save made in area 1 holds `$4BF2` = 1, because the word takes the current
area once the init entry returns, so loading it does not replay the opening.
SPECULATIVE: writing the area byte `g5ce1` to 1 just before the key would make
`NEWECL` store 1 as came-from and skip the opening. `g5ce1` has no VM setter,
so a script `SAVE` cannot do it. To settle it: in FT-L1, arm a Curse trip from
area 3 to area 1 with `g5ce1` = 1 written with the key, and check that no
opening text appears and that the came-from word reads 1.

### The flags, the fork and the maps

**The window offers it only behind `WISH_EXPERIMENTAL_AMIGA_FSUAE`.** With the
variable set to `1`, `true`, `yes` or `on`, `wish/backends.py` lists a row named
"FS-UAE (Amiga)" whose probe is `wish.fsuae.listening` and whose opener is the
cached `wish.fsuae.connect`; anything else, including `0`, `off` and an empty
string, leaves the list as it was, with no probe and no import of `wish.fsuae`.
The row is not `disturbs` (a poll measured about 20 ms, served from the running
machine's frame handler) and polls every 200 ms, like VICE. Its removal
condition is written beside the flag's name in `wish/backends.py`.

**Either Amiga flag decides whether Wish names Pools of Darkness from its Amiga
disks and offers its folder row.** Pools of Darkness never shipped on the
Commodore 64, so no C64 container describes it. With `WISH_EXPERIMENTAL_AMIGA_FSUAE`
or `WISH_EXPERIMENTAL_AMIGA_WINUAE` on (`backends.amiga_only_titles`),
`automap.maps.AMIGA_ONLY_TITLES` (Pools of Darkness) joins the titles
Preferences has a disk-folder row for, and the map loader names a disk whose
volume says `POD 3` or `Pools of Darkness` as that title. With both off
neither happens, and a folder holding only Pools of Darkness disks gives no
maps.

**What the fork needs.** The player runs the game in `grahambates/fs-uae`,
branch `remote_debugger_prb28`, and not in stock FS-UAE, which has no such
server. The server is started by the fork's `remote_debugger=<seconds>` option, and it
listens on 2345 unless `remote_debugger_port=<port>` says otherwise; 2345 is the
port the row looks for, so a different port is not found. The fork closes its
listening socket when a client disconnects, which the helper is there to keep
from happening when Wish closes. The setup hint says only "the fork, not stock FS-UAE"; the branch
name and the options live here. The machine has to be the A500 of
`tools/amiga/goldbox-a500.uae`: the sweep and every range check read only 512K
of chip memory at `$000000` and 512K of slow memory at `$C00000`
(`automap.amiga.MEMORY`), so a configuration with fast RAM, more chip RAM or no
slow RAM waits on "Waiting to connect..." for ever.

**The maps come from the C64 disks when there are any, and otherwise from
loose Amiga disk images.** `automap.maps.load_maps_titled` reads the C64 disks
first. If it finds none it reads every `.adf` in the folder
(`_amiga_maps_titled`), naming each disk by its volume name, because an image's
file name is the player's to change: `GEO.GLB` for Curse, Silver Blades and
Pools of Darkness, `geo.dax` for Pool of Radiance. A volume that matches no
title is skipped. An `.adf` inside a `.zip` is not read. Where C64 disks are
configured, the area is named from them: every Silver Blades map is
byte-identical across the two ports, and the three Curse maps that differ do so
in two bytes, inside the 32 that `ResidentGeo` tolerates.

**Pool of Radiance's Amiga build has a row with `segments`.** It is not a
small-data binary: the anchor (the weapon-name table) is in hunk 31 and the
party's globals are in hunk 32, a BSS hunk. `data_base_for` reads the anchor's
allocation length (`size + 8` at `base - 8`) and the BPTR at `base - 4`, hops
to hunk 32 and checks that hunk's length the same way; a disagreement is a
`GuestError`. On the travel grid the view byte (`h32+0xC1`, 2 to 4) names the
window and must agree with the area byte (`h32+0x2F73`, 25 to 27); the block's
own area word lags a crossing by one and is never read. The square is the
window-local x and y in the block `[h32+0x98]`, valid only while that block's
indoors word is 0, and the heading is the facing byte, already 0 to 7.
`docs/165-amiga-savegame.md` has the hunk layout.

**Whether the `GEO` pointer moves on an area change is unmeasured.** The
automapper is right either way, because it re-reads the pointer every poll.
Area changes have been watched under the test driver (see "What was measured on
a running machine"), and the tab followed the arriving area each time, but none
has been shown through Wish's own window.

### The WinUAE backend: its transport and its row

Wish and WinUAE on one Windows machine talk through WinUAE's own named pipe,
`\\.\pipe\WinUAE` (then `WinUAE_1` to `WinUAE_9`). `automap/winuae.py` opens it
from Python in message mode: no PowerShell, no console window, nothing pressed
in the emulator. `wish/winuae.py` is the window side; its probe lists the pipe
directory and opens nothing, because WinUAE serves one client at a time.

* **Reads are `S "<absolute path>" <addr> <len>`,** one per range, into a file
  with a name of its own under Wish's data folder (`run/winuae`); `m` is not used
  because its output is capped near 4 KB a reply and about 500 lines for the life
  of the emulator process. The path is quoted, so spaces are safe. A pure-ASCII
  path goes as 8-bit text; any other goes with the UTF-8 byte-order mark, which
  has not been run against a real WinUAE. The reply's receipt is checked for the
  address, byte count and file name, and `wish-*.bin` files left behind by an
  abandoned request are deleted when the pipe is opened.
* **One handle is held while Wish is attached,** so the player's WinUAE log gets
  one connect line and not one per read. The target the window holds releases
  it on `close()`, and a connect that fails releases it too. A pipe another tool
  holds is waited for up to half a second (`WaitNamedPipe`), then the window
  asks again on its next tick.
* **Every read and write is overlapped with a deadline.** WinUAE does not
  service the pipe while its debugger waits at the F11 prompt, and a simple read
  would hang the window. A request waits two seconds, then is cancelled and the
  handle dropped (a late reply would answer the next request), and nothing is
  tried again for five seconds. A reply is read on only while WinUAE says more
  is coming, and a complete message without its NUL is an error.
* **The search for the running title is read in 64 KB pieces** (16 KB after a
  piece times out) through `wish/amigalocate.py`, one second a tick, each piece
  waiting no more than what is left of that second (0.2 s at least); what was
  read is kept and the next tick goes on from there, dropped only after five
  seconds without a new piece, with the
  window shown its waiting line meanwhile. Leftover dump files of this process
  are deleted when the pipe is opened and when it is closed.
* **Writes are `DBG W <addr> <bytes>` lines of at most 16 bytes, up to 64 bytes a
  call inside chip or slow memory.** Each reply must be a `Wrote ... at <address>.B`
  receipt for the byte and address sent, and the range is read back with `S`
  and compared unless the caller passes `verify=False`. The write is not atomic:
  a failure part-way leaves the earlier lines written, and the error says how
  many bytes went. The game redraws a changed field on its next redraw of the
  row or the sheet; the pipe does not make it.
* **The row exists.** `wish.winuae.AMIGA_WINUAE` is "WinUAE (Amiga)", with the
  hint "Run the game in WinUAE on this computer.", behind
  `WISH_EXPERIMENTAL_AMIGA_WINUAE`; it is listed before the FS-UAE row. With either
  Amiga flag on, the window loads the Amiga-only titles' maps and offers the
  Pools of Darkness folder.
* **It has run in Wish on Pool of Radiance only.** On WinUAE 6.0.3 Wish's own
  window followed the party through a turn and two steps with the right marker.
  After a restart of Wish the explored squares were lost; the notes are now saved
  as each new square is revealed, and that has not been run in a Windows build.
  Curse, Silver Blades and Pools of Darkness have not been run in Wish on WinUAE.
  The tests use a fake pipe, and the ones that use a real named pipe run only on
  Windows.

## Still open

* **The multi-class experience split.** A card draws one bar per class, each
  against the single stored 24-bit number. Whether the game stores a total or a
  per-class share is not established -- LADY KATHERINE, the only multi-class
  specimen we hold, is level 1 in both classes and cannot tell them apart.
* **The two unit bits of the effect duration byte** are still shown as a number
  rather than guessed at.

### Closed

* ~~**Effect ids have no names.**~~ **They do.** 129 codes are named in
  `goldbox/traits.py` -- 44 CONFIRMED, because a `MON*` record or a saved item
  carries the code on exactly the creature the meaning demands, and 84 PROBABLE
  from the DOS guide's 127-entry effect table. An effect on a roster card or a
  monster tooltip reads `petrifying gaze`, not `effect 27`; a code outside the
  table still falls back to `trait <n>`.
* ~~**During combat the map half should become the combat view.**~~ **Built.**
  The Automapper tab holds a `QStackedWidget` of two canvases and swaps them when
  the game enters and leaves combat, with the roster staying put. See
  [101-combat-view.md](101-combat-view.md).
