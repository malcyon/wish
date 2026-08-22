# A combat log

**Status: run against a live fight, and it was wrong twice.** 1428 frames of a
slums fight — six characters against orcs — settled the region, the timing and
the shape of the messages, and found two defects that offline tests could not
see, because both turn on bytes only a running game writes. Both are fixed; see
`docs/50-experiments.md`, "The combat log's two defects, found in a slums
fight", and the two rules below marked **live**.

The game prints who hit whom for how much, holds it for a **software delay
loop**, and paints over it. Nothing saves it. On an emulator running faster than
a 1 MHz 6510 the line is gone sooner in wall-clock time than it can be read.
Keeping those lines fixes a real defect in the game rather than mirroring it.

---

## Where the message region is

**Columns 23–38, rows 10–22.** Read from the overlay, not guessed.

`COMBAT $2983` is the message printer:

```
$2983  STX $2B44        ; remember which message
$2986  JSR $0969        ; window := the four bytes at $0970
$2989  LDA #$0A
$298B  STA $03F4        ; ...then move its top row to 10
$298E  JSR $488B        ; cursor to the top-left of the window
$2991  JSR $2E19        ; clear the window
$2994  JSR $34C3        ; print the name at $6B00
$299A  INC $03CD        ; next row
$299D  JSR $3ECB        ; ...column 0 of it
$29A5  LDA $AF00,X      ; the message string
$29AB  JMP $0962        ; print it
```

`$0969` is `LDA #$70 / LDX #$09 / JMP $485A`, and `LIBRARY $485A` copies four
bytes from the address in `A`/`X` to `$03F2`-`$03F5`. `COMBAT $0970` holds
`17 27 01 17` — identical on all eight disk sides — so the combat text window is
**columns 23 to 38, rows 1 to 22**, and `$2989` moves its top to **row 10** for
messages. Rows 1–9 of the same band are the **acting combatant's** panel — the
name, `HIT POINTS n`, `AC n` and the readied weapon, all confirmed on screen —
which is why the top row matters and the whole band would not do.

**Live: the four bytes are often some other window.** `00 28 18 19` — the whole
of row 24 — is what the command bar leaves there whenever it prints `GUARDING`,
`MOVE VIEW` or `YOUR TEAMMATE IS DYING`, and it was in 29 of those 1428 frames.
Believed, it slices whole rows 10–24 out of the screen: the combat map in the
game's own glyphs, the border, and the command bar. So the *columns* come from
`$0970` and never from the live bytes, the bottom is clamped to row 22, and
`$03F4` is read only when the live bytes really are the message window and its
top is row 10 or below. `combatlog.message_window` is that rule.

| address | what |
|---|---|
| `$03F2` | the window's left column |
| `$03F3` | one past its right column |
| `$03F4` | its top row — **10 while a message is printing** |
| `$03F5` | one past its bottom row |
| `$03CC` | the cursor's column |
| `$03CD` | the cursor's row |
| `$49FC` | the message delay; `INIT $09AC` sets it to 2, `CAMP` steps it |
| `$6B00` | the current combatant's name, as a string |
| `$AF00`/`$AF80` | `SPELLN00`'s pointer table, lo and hi, 128 entries |

The four window bytes are read live every poll and **validated against
`$0970`'s columns** before use — they are ordinary RAM and hold whatever the
last overlay left there, which in a fight is usually the command bar.

## Whether it scrolls or overwrites

**Both, and mostly overwrites.**

* `$2983` clears rows 10–22 and starts again at the top, so **each new speaker
  wipes the panel**.
* Within one speaker's block, `$299A` appends on the next row, and `$29BA`
  moves `$03F4` down to the row below the cursor so a follow-up lands under
  what is already showing.
* Only when a block runs past row 22 does `LIBRARY $2D28` call `$2CA5`, which
  **scrolls the window up by one line**.

**Live: a block also *shrinks*.** `$29B7` clears from the follow-up's own top,
so an eight-row block goes back to being the five rows it grew from before the
window is cleared for good. Counted as *replaced*, that committed the block and
made its own residue the next one, and every killing blow in the captured fight
was logged twice. So a frame-to-frame change is one of **four** things —
*grew*, *shrank*, *scrolled*, *replaced* — and each gets its own rule in
`automap/combatlog.py`.

## Whether the game pauses for input

**No.** `COMBAT $28C3` reads `$49FC` and, if it is not zero, jumps to
`LIBRARY $2E1F`, a `DEX`/`DEY` busy loop of about 325,000 cycles per unit —
roughly a third of a second each, three of them at the default setting of 2.
Then `$29B7` clears the window. Nothing in that path reads the keyboard.

That is the whole risk, and the whole reason the feature is worth having: a
message lives about **a second of emulated time**. At the default 200 ms poll
that is five frames, which is plenty of margin — but it is the first number to
check if messages start going missing.

**Measured, and the estimate was right.** `$49FC` read 2 for the whole fight.
Timing the window from first text to clear against the jiffy clock at
`$A0`-`$A2`, over 49 messages: **60–62 jiffies** — one second exactly — for a
block with no follow-up, 72–74 where a follow-up was added, and 156–169 or 336
for a block whose follow-ups came in sequence. One second is the number to
poll against.

## What the messages are made of

`SPELLN00` loads at `$AF00` (`LIBRARY`'s type table, file type 6) and is 128
string pointers followed by the strings. `COMBAT` indexes it as `X + $39`, so
its message 0 is the table's entry 57. A line is a name from `$6B00` followed by
one or more fragments:

```
row 10   MAGNUS
row 11   ATTACKS
row 12   AND HITS FOR 5
row 13   POINTS OF DAMAGE
```

`$2F29` prints the number between two of those fragments, which is why a row
can gain characters between two polls without gaining a row.

**One block names one combatant** — the attacker in "X ATTACKS AND HITS FOR 5",
the target in "Y IS HIT FOR 5". Pairing the two across blocks is a later job and
would be invention now, so `Message` carries `subject`, `outcome` and `damage`
and nothing that claims to be a target.

## How "anything that is new" is decided

The screen is a rectangle that gets overwritten, not a stream, and **two
consecutive messages can be genuinely identical**. So:

* **Deduplicate only on consecutive identical frames, never on content.** A
  frame equal to the last one is the same message still showing.
* A frame that **extends** the pending block — more rows, or more characters on
  the last row — replaces it. One block is one message however many polls saw
  it being built.
* A frame that **shrank** — the same rows with the bottom ones cleared — is
  the follow-up's delay expiring, not a new block. The longer version stays
  pending. Without this rule every kill was logged twice.
* A frame that **scrolled** (the window was full and everything moved up one)
  appends the new bottom row instead of starting over.
* Anything else **replaces** the block, and the one before it is committed.
* An empty frame is the clear, and commits.
* And there is a second, independent edge: **`$03F4` going back to 10 means
  `$2983` ran**, so it is a new block whatever the text says. That is what
  saves the second "MAGNUS MISSES." when the blank frame between them falls
  between two polls. It is read **only** when the live window bytes are the
  message window's own and the top is row 10 or below: `$03F4` = 1 is `$0970`
  restoring the whole text window at the end of a turn, and taken as a message
  top it logged the turn's last message twice.

Splitting one frame into two messages uses the same byte: every value `$03F4`
took while the block was building is a row a name was printed on, so the splits
are read rather than guessed. With none seen the block stays whole, which is the
honest answer.

## What it does

* Appends to the **Messages panel**, tagged by round where the round is known
  (`$A380` reaching all-zero ends one).
* **Keeps the log after combat ends**, which is the entire point. The last
  message of a fight is never painted over — `COMBAT` returns to `LINKER` with
  it still up — so `CombatLog.flush()` is called when the fight ends, or it
  would be the one message the log lost.
* **Never invents structure.** A line that will not parse into a subject and an
  outcome is shown verbatim, and the raw rows travel with every message as the
  panel row's tooltip.

## Cost

**One extra burst per tick while a fight is running, and nothing at all outside
one.** The mode byte, the video registers, the window bytes, the cursor and the
520 bytes of screen rows all ride in a single burst, because the cost of a read
is the round trip and not the bytes — about **14.3 ms of extra emulated time per
`resume`**, measured in `docs/70-driving-the-game.md`. The combat view already
spends two bursts a tick; this makes three.

The screen's address is the one thing that cannot ride along, because computing
it needs `$D018`/`$DD00` read first. So the address is **held from the previous
poll** and re-derived from the registers in the same burst: if they disagree the
frame is thrown away rather than logged. The screen moves once per overlay, so
that costs at most one frame a fight.

`AutomapWindow.COMBAT_LOG` turns it off and `COMBAT_LOG_EVERY` polls less often.
They are class attributes rather than settings because `automap/config.py` was
another agent's file this session; they belong in `Settings` now that the
measurement is in — **200 ms**, five polls to the shortest message's one
second.

## Where the code is

| file | what |
|---|---|
| `automap/combatlog.py` | the region, the diff, the dedup, the parse. No Qt |
| `automap/screen.py` | `band`, which slices a window out of whole rows |
| `automap/window.py` | `poll_combat_log`, `log_combat`, and the flush |
| `tests/test_combatlog.py` | every rule, against constructed screens and two frames from the captured fight |
| `work/combatlog/fight.py` | drives a fight and records every poll (scratch, not shipped) |
| `work/combatlog/replay.py` | re-runs a recording through the reader (scratch) |

`log_combat` **defeats `MessagesPanel`'s own repeat-dropping**, and that is the
point of the feature: the panel drops a line identical to the one before it,
which is right for "waiting for the game" on every tick and wrong for two
"MAGNUS MISSES." in a row. It does that by passing `MessagesPanel.say`'s
`dedup=False`, which that panel now takes.

---

## Verified on a live machine

One fight, 1428 frames at ~0.18 s, six characters against orcs at (14,0) in the
Slums. `work/combatlog/fight.py` drove it and recorded every poll; the raw
frames replay through the reader with `work/combatlog/replay.py`, so any later
change to `combatlog.py` can be checked against the same fight without a
second one.

| # | what | result |
|---|---|---|
| 1 | the region | **CONFIRMED.** Messages in columns 23–38 of rows 10–22; `$03F2`-`$03F5` = `17 27 0A 17` for a fresh block, `17 27 0F 17` for a follow-up. Rows 1–9 are the *acting combatant's* panel, not the party's — this file was wrong |
| 2 | the delay | **CONFIRMED.** `$49FC` = 2; 60–62 jiffies for a plain message, 72–74 with a follow-up, over 49 of them |
| 3 | the stall | **No stall — the opposite.** Polling at 0.178 s ran the machine at **1.121× real time** (17471 jiffies in 259.8 s), which is the 14.3 ms per resume of `docs/70` plus the connect. Not measured against a `COMBAT_LOG = False` run, because the cost is per resume and the combat view already spends two |
| 4 | a whole fight | **CONFIRMED after two fixes.** 58 messages from 1428 frames, nothing garbled, nothing doubled, in order. Before the fixes: four garbage blocks and every killing blow twice |
| 5 | two consecutive messages | **CONFIRMED.** `MALCYON ATTACKS ORC AND HITS FOR 1 POINTS OF DAMAGE` and `... FOR 3 ...`, one blank frame apart, both kept |
| 6 | the split | **CONFIRMED.** `MAGNUS ATTACKS ORC AND HITS FOR 10 POINTS OF DAMAGE` and `ORC GOES DOWN AND IS DYING` came out of one eight-row frame as two messages, split on the `$03F4` = 15 the follow-up set |
| 7 | the scroll | **UNKNOWN.** No block in this fight passed row 22; the longest was eight rows. Needs a spell that hits several combatants |
| 8 | after the fight | **not reached** — the fight was ended from the emulator, not through the panel |

Left to do: item 7, and the same run through the real `AutomapWindow` rather
than through `CombatLog` alone.
