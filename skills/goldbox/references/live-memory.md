# Reading a running game whose addresses you do not know

**Start from the assumption that the addresses are wrong.** Every absolute
address this project knows is Pool of Radiance's. Curse shifts the save image by
`$200` and moves the roster into a different file entirely; nothing promises the
next title is as tidy.

## The search recipe

### 1. Find the save image in RAM — one step, no inference

A Gold Box save is a **verbatim memory image**. So:

1. Load a save in the emulator and leave the party standing still.
2. Take a 256-byte run from the middle of that same save file — somewhere
   non-zero, the character slots are ideal.
3. Read the machine's 64K and search for that run.
4. The offset names the base exactly.

Read both the `cpu` and the `ram` bank; a copy under I/O will not show up
otherwise. Sweep the whole 64K rather than a guessed range — the search that was
meant to settle the area question in this project kept coming back empty because
its range started one page above the answer.

### 2. If that fails, search for a value you know

In order of how unambiguous a hit is:

| Needle | Why |
|---|---|
| a **character name** — 6+ letters, ASCII, NUL-padded to 20 | effectively unique in 64K; a hit is the slot base |
| the **party's coordinates** — the byte pair matching what the status line shows | small values, so expect many hits; use as corroboration, not discovery |
| a **hit-point total** off the character sheet | 16-bit little endian; distinctive when the character is wounded to an odd number |
| the **money** you just spent down to a specific figure | a deliberate, unusual value is worth engineering before the search |

Engineer the needle where you can: a character named with an unusual string, a
purse counted down to a strange number, a party standing at coordinates nothing
else in memory would carry.

### 3. Corroborate with a second value at a known relative offset

Having found a name at address `A`, check that `A + 0x14` is strength,
`A + 0x76` is hit points maximum and `A + 0x0EB` is the class bitmask. Three
sane decodes is a slot base. The **stride** falls out of where the second
character's name sits.

Then derive the header: in both games studied, the header is the `$400` bytes
below the slot base, and the icon table ends exactly where the slots begin.

### 4. Corroborate again by changing it in game

This is the step people skip and it is the one that catches a wrong address.
Change the thing, re-read, and check the byte moved the way you predicted, when
you predicted:

* walk one square — x or y changes by one;
* turn on the spot — facing changes, position does not;
* buy armour — the roster's armour-class byte moves and the record's does not;
* take a wound — current hit points fall, maximum does not;
* cross an area boundary — the area byte in the loader cache changes.

A byte that predicts correctly under a deliberate change is the strongest
evidence available short of reading the code.

### 5. Then read the code

Scan every file on the disks for absolute operands landing in the region. What
*reads and writes* an address tells you what it is; correlation only tells you
what it correlates with. In this project the code route was the more productive
of the two every single time it was tried.

Where a structure has a **fixed base** this is devastatingly effective: the
character record answers to a fixed base in Pool of Radiance, so an absolute
operand inside its range *is* a record offset, and scanning the whole disk set
for those operands produced a map of which offsets the game's own code touches.
Level drain, the NPC flag, the effect list and the last item bytes all fell to
that after months of save-diffing had failed on them.

## The obvious address is not always the live one

In Pool of Radiance the party's x, y and facing bytes in the header are
genuinely the party's position and genuinely what reaches the disk. **They lag
a move**: read straight after a step they give the previous square. The status
line — facing, clock, x, y — is correct the moment the screen settles.

So the automapper reads the status line first, falls back to memory only when
the status line is not on screen (camp, combat, a menu), and tags every fix with
its source. Three rules follow for any title:

* **Find which copy is live on this title, by moving and watching.** Neither
  source is trustworthy by default. Curse and Silver Blades keep the save's copy
  at `$4BC0` and the engine's working copy at `$C04B`, and `$4BC0` does not move
  *at all* while the party walks — the severe version of a lag, and identical to
  it for the first step. On Silver Blades the **status line** is the one that
  lagged: it read `2,0` when every memory copy and the clock said `(3,0)`.
* **The address the save writes need not be the address the game reads**, and
  the live one need not be inside the save image at all. `$C04B` is not.
* **A cache has an update rule and you must find it.** The derived combat values
  refresh on equipment change and at no other time.

A third case worth knowing: a live poke into the item area is reverted, because
that region is a copy fed from a master elsewhere. **If a write does not stick,
you have found a copy, not a failure.**

## Overlays: an address means what you think only in the right moment

The game loads code and data on demand, so the same bytes hold different
routines minutes apart.

* **Every overlay lies about its declared load address.** In Pool of Radiance
  every overlay declares `$1000` and every one actually runs at `$0800`.
* **Establish a resident base by fitting.** Score internal `JSR` targets: the
  correct base puts 480-550 of them inside the file and near zero elsewhere. A
  one-byte error is detectable — `$2C48` beat `$2C47` at 359 of 522 against 290,
  and one particular `JSR` only decoded at all under the right one. Cross-check
  against patch sites: code elsewhere that stores into the overlay names its base
  directly.
* **Read and check the bytes before every write.** Patching an address blind a
  second time corrupted a live routine here.
* **Gate on the game's own mode flag, not on the screen.** Pool of Radiance
  keeps one byte saying which overlay is running. Regions that mean something in
  combat are a file staging buffer outside it, so a mapper that does not gate
  reads graphics as a map, or draws 64 combatants at (0,0).
* **Validate before trust.** Read the region, check it still decodes as a sane
  party, and refuse to draw or write if it does not. For writes that check is
  mandatory.

## The binary monitor's sharp edges

| | |
|---|---|
| **Match responses by request id.** | The monitor interleaves unsolicited events into the stream. A client that reads one response per request silently desyncs and returns the *previous* request's data. This costs an hour to rediscover. |
| **Connecting stops the machine.** | Hold **one** connection open and `resume()` after each burst rather than connecting per read. |
| **Polling speeds the game up, it does not stall it.** | Each stop/resume hands the emulation ~14.3 ms of *extra* emulated time. Flat out is 3.05× real time; 200 ms is 1.07×; 500 ms is 1.03×. Distortion is `14.3 ms / interval`. |
| **The cost is per `resume()`, not per byte.** | A 7168-byte read costs the same as one `peek`. Four peeks with four resumes cost 45.9 ms against 14.4 ms batched. Batch a whole poll into one resume. |
| **One connection per VICE process.** | A second is accepted at TCP level and then never answered, so two things at once means two emulators. In this repository, claim one through `tools/instance.py` — never launch outside the pool, never attach to one you did not launch, never kill by name. A timeout on the *greeting* means busy; a timeout on the *connect* means absent — different failures, different messages. |
| **Never leave a checkpoint armed when the socket closes.** | The emulator re-enters the monitor on a socket that no longer exists and only a kill recovers it. Delete every checkpoint at the end of every experiment. |
| **Reading RAM under I/O needs the explicit `ram` bank.** | Query the available banks rather than assuming an index. |
| **Do not infer "stopped" from a constant raster counter.** | Monitor reads with side effects disabled do not return live VIC values. |

## Reading the screen instead of memory

The game runs in **text mode with its own character set**, so the screen is
readable as screen codes — no OCR, no image matching. Two things move:

```python
d018 = peek(0xD018); dd00 = peek(0xDD00)
bank = (~dd00 & 3) * 0x4000
screen = bank + ((d018 >> 4) & 0xF) * 0x400   # $CC00 in-game, $0400 at boot
```

Recompute it every read. Check the bitmap bit first: title and credit screens
are bitmaps and cannot be read as text.

**Menu selection is a colour, not a character.** The highlighted row is drawn in
white against green, and colour RAM is at a fixed address regardless of VIC
bank. Read the colour to find the highlight rather than counting rows — and note
that some command bars use a different highlight colour, so a helper that
hard-codes one silently finds nothing and returns success.

Keep the screen decoder free of any emulator dependency: pass `read(addr, len)`
in as a callable. Then a second backend gets screen reading for free and a test
gets it against a dictionary of bytes.

## The backend contract

Two methods, deliberately no more:

```python
class Target(Protocol):
    def read(self, addr: int, length: int) -> bytes: ...
    def write(self, addr: int, data: bytes) -> None: ...
```

Breakpoints and stepping are emulator-only luxuries; keeping them out of the
contract stops every other backend having to pretend it has them. Everything
above — the party fix, the screen, the resident map — builds on those two, which
is why all of it is testable against a dictionary of bytes with no emulator at
all.
