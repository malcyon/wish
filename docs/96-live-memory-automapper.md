# Optional future feature: live memory and an automapper

**Status: built.** The code is the `automap/` package; this note is kept because
it records why the design is shaped the way it is.

It lives outside the character editor on purpose, and outside `por/` too: the
editor is a file tool with **zero emulator dependency** ([README.md](README.md)
§"How the code is laid out"), so everything that reads a running machine is in
`automap/` and neither `por/` nor `editor/` imports it.

| module | what it is |
|---|---|
| `automap/vice.py` | the binary-monitor client, moved here from `tools/drive.py`, which re-exports it |
| `automap/screen.py` | screen decoding over a plain `read` callable -- no VICE in it |
| `automap/target.py` | the two-method `Target` protocol, `party_fix` over any backend's `read`, and `ViceTarget` holding one connection open |
| `automap/area.py` | three strategies for "which `GEO` are we on" |
| `automap/state.py` | position, exploration, notes |
| `automap/render.py` | map geometry as drawing primitives, plus an SVG renderer — no Qt |
| `automap/live.py` | the running game's party, effects and clock, as plain data — no Qt |
| `automap/panel.py` | the roster cards and the bottom strip |
| `automap/window.py` | the PyQt6 window: roster left, map right, strip below |

Run it with the game already running: `wish --tab map` (or `python -m automap`,
which still opens it alone). Render a map offline with
`wish --svg GEO00 out.svg`, which needs no emulator.

The window and the connection now live in `wish/` -- see
[99-one-window.md](99-one-window.md). `wish/backends.py` holds the list of
backends and `wish/session.py` owns the single `Target`, because VICE serves
exactly one binary-monitor connection and ignores the second in silence.

## The idea

Read the party's map coordinates out of the running game and draw a live
automap, in the spirit of the Gold Box Companion. Optionally write memory too,
for things a save file cannot reach.

## Why it is cheap to add later

`por/` contains **no transport code at all** — no sockets, no disk knowledge
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

## Two backends, and only two

* **VICE**, over its binary monitor (`POR_DEBUG=1` already enables it).
* **Commodore 64 Ultimate**, over its network interface -- written, in
  `wish/ultimate.py`, and **unverified**: nobody on this project has the
  hardware. It speaks the documented REST API (`/v1/machine:readmem`,
  `/v1/machine:writemem`) and is offered only when `$POR_ULTIMATE` names a
  device that answers.

Deliberately not supporting other emulators or bare hardware. Most emulators
have no usable interface, and a real C64 would need a resident stub or a DMA
cartridge — a lot of fragility for very few users.

*(If a third is ever wanted, the cheapest by far is **watching the save file**:
poll its mtime and re-read on change. It needs no protocol, works on real
hardware with an SD2IEC, and fits the same interface with `writable=False`. It
is a fallback, not a priority.)*

## Backends differ in ways that change what you can build

Worth declaring rather than assuming:

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
it still decodes as a sane party, and refuse otherwise. For writes that check
should be mandatory.

**Batch aggressively.** Read `$4900`–`$64FF` in one call, not sixty small ones.
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

**And the area question is now answered, live.** The `GEO` file is a PRG loading
at `$0400`, and the game **does not relocate it**: `$0400` is the boot screen,
but in the world the screen has moved to `$CC00`, so the page is free and the
map is left where it lands. CONFIRMED in New Phlan — `$0400`–`$07FF` was
byte-identical to `GEO00` with 480/480 reciprocity, and a sweep of all 64K in
both the `cpu` and `ram` banks found no second copy. `ResidentGeo` reads it and
`Automapper.poll()` names the area outright every tenth poll, with `Fingerprint`
left running underneath as the contradiction check.

A `FilenameDigits` strategy — read the two digits the loader patches into the
`GEO00` stem — was tried and is dead, and the code is gone. `$24B4`–`$24B9` in
the running game reads `50 55 5a 5f 20 87`, not `GEO00`; the resident stem is at
`$40FB`, and nothing writes to its digits, so the filename is assembled in a
scratch buffer elsewhere.

`Fingerprint` on its own cannot finish on positive evidence: squares occupied
and steps completed need **111 steps** to get New Phlan down to one candidate.
A single *refused* step settles it, and `Automapper` now supplies one -- the
status line carries the game clock, so clock advanced + square unchanged +
facing unchanged is a refused step in the current facing. See below.

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
   backends than at five. **Done as far as it can be without hardware**: the
   interface survived on paper -- `party_fix` needed `read` and nothing else --
   and the last word belongs to a real device.


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

Two reads a poll -- `$4900`-`$64FF` and the roster page at `$8300` -- batched
into a single `resume()` by `ViceTarget.read_blocks`, and taken every fifth map
tick, which is once a second at the default interval. Only the visible tab polls
at all.

### The refused step -- wired up

`Fingerprint.refused()` had nothing calling it, because the mapper cannot see
key presses. It does not need to: the status line carries the game clock, and
**clock advanced by one minute + square unchanged + facing unchanged** is a
step the game refused. Positive evidence needs 111 steps to identify New Phlan;
one refusal settles it, because impassable edges are rare.

Guarded three ways -- both fixes must come from the status line (`$49C0` lags a
move, so a *successful* step read from memory looks identical), the clock must
have advanced by exactly one minute (longer is searching or camping; zero is
standing still), and the facing must not have changed.

**Unconfirmed against the running game: whether a bump costs a minute at all.**
A move does. If a bump costs nothing this never fires; if bashing a locked door
costs a minute it records a false blocked edge, which is what
`Fingerprint._narrow` now absorbs -- it refuses to narrow to zero candidates,
keeps the last set that fitted, and counts the contradiction instead.

## Still open

* **The multi-class experience split.** A card draws one bar per class, each
  against the single stored 24-bit number. Whether the game stores a total or a
  per-class share is not established -- LADY KATHERINE, the only multi-class
  specimen we hold, is level 1 in both classes and cannot tell them apart.
* **The two unit bits of the effect duration byte** are still shown as a number
  rather than guessed at.

### Closed

* ~~**Effect ids have no names.**~~ **They do.** 129 codes are named in
  `por/traits.py` -- 44 CONFIRMED, because a `MON*` record or a saved item
  carries the code on exactly the creature the meaning demands, and 84 PROBABLE
  from the DOS guide's 127-entry effect table. An effect on a roster card or a
  monster tooltip reads `petrifying gaze`, not `effect 27`; a code outside the
  table still falls back to `trait <n>`.
* ~~**During combat the map half should become the combat view.**~~ **Built.**
  The Automapper tab holds a `QStackedWidget` of two canvases and swaps them when
  the game enters and leaves combat, with the roster staying put. See
  [101-combat-view.md](101-combat-view.md).
