# A combat log

**Status: built and tested offline; not yet run against a live fight.** The
three questions the plan said had to be found first were answered by
disassembling `COMBAT` and `LIBRARY` rather than by watching a screen, which is
better evidence. What is left is timing, and timing needs the emulator — the
numbered list at the end is a single sitting's work.

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
messages. Rows 1–9 of the same band are the party panel, which is why the top
row matters and the whole band would not do.

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

The four window bytes are read live every poll and validated before use — they
are ordinary RAM and hold whatever the last overlay left there — with `$0970`'s
values as the fallback.

## Whether it scrolls or overwrites

**Both, and mostly overwrites.**

* `$2983` clears rows 10–22 and starts again at the top, so **each new speaker
  wipes the panel**.
* Within one speaker's block, `$299A` appends on the next row, and `$29BA`
  moves `$03F4` down to the row below the cursor so a follow-up lands under
  what is already showing.
* Only when a block runs past row 22 does `LIBRARY $2D28` call `$2CA5`, which
  **scrolls the window up by one line**.

So a frame-to-frame change is one of three things — *grew*, *scrolled*,
*replaced* — and each gets its own rule in `automap/combatlog.py`.

## Whether the game pauses for input

**No.** `COMBAT $28C3` reads `$49FC` and, if it is not zero, jumps to
`LIBRARY $2E1F`, a `DEX`/`DEY` busy loop of about 325,000 cycles per unit —
roughly a third of a second each, three of them at the default setting of 2.
Then `$29B7` clears the window. Nothing in that path reads the keyboard.

That is the whole risk, and the whole reason the feature is worth having: a
message lives about **a second of emulated time**. At the default 200 ms poll
that is five frames, which is plenty of margin — but it is the first number to
check if messages start going missing.

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
* A frame that **scrolled** (the window was full and everything moved up one)
  appends the new bottom row instead of starting over.
* Anything else **replaces** the block, and the one before it is committed.
* An empty frame is the clear, and commits.
* And there is a second, independent edge: **`$03F4` going back to 10 means
  `$2983` ran**, so it is a new block whatever the text says. That is what
  saves the second "MAGNUS MISSES." when the blank frame between them falls
  between two polls.

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
another agent's file this session; they belong in `Settings` once the
measurement below says what the interval should be.

## Where the code is

| file | what |
|---|---|
| `automap/combatlog.py` | the region, the diff, the dedup, the parse. No Qt |
| `automap/screen.py` | `band`, which slices a window out of whole rows |
| `automap/window.py` | `poll_combat_log`, `log_combat`, and the flush |
| `tests/test_combatlog.py` | every rule, against constructed screens |

`log_combat` **defeats `MessagesPanel`'s own repeat-dropping**, and that is the
point of the feature: the panel drops a line identical to the one before it,
which is right for "waiting for the game" on every tick and wrong for two
"MAGNUS MISSES." in a row. It does that by clearing the panel's `_last` before
each line; `MessagesPanel` should grow an explicit `dedup=False` argument when
`automap/panel.py` is free to edit.

---

## Still to verify on a live machine

In order, one sitting, one fight in the New Phlan training hall:

1. **The region.** Enter combat, dump the screen, confirm the messages are in
   columns 23–38 of rows 10–22 and that rows 1–9 hold the party panel. Read
   `$03F2`-`$03F5` at the same moment and confirm `17 27 0A 17`.
2. **The delay.** Read `$49FC` (expected 2), then take the jiffy clock at
   `$A0`-`$A2` when a message appears and again when it clears. Expected about
   60 jiffies. This is the number that decides the poll interval.
3. **The stall.** Same jiffy technique as `docs/70-driving-the-game.md`: run a
   fight with `COMBAT_LOG = False` and again with it on, and record the
   difference in jiffies per wall-clock second. Write the measurement into this
   file. A log that stutters the fight is worse than no log.
4. **A whole fight, end to end.** Compare the panel's lines against a video of
   the same fight: nothing missed, nothing doubled, in order.
5. **Two identical consecutive messages.** A character with two attacks a round
   missing twice is the natural case; a low-level fighter against a high-AC
   target will produce it soon enough. Both must appear.
6. **The split.** Confirm that a kill — "X ATTACKS AND HITS FOR n POINTS OF
   DAMAGE" followed by "Y GOES DOWN" and "Y IS KILLED" in the same frame —
   comes out as separate messages, which is the `$03F4` rule doing its job.
7. **The scroll.** Only fires when a block passes row 22, which needs a long
   block — a spell that affects several combatants is the likely one. Confirm
   nothing is repeated across the scroll.
8. **After the fight.** Return to the world and confirm the log is still there
   and still readable, including the last message.

Then write the run up in `docs/50-experiments.md` and prune whatever this file
claims that the run contradicts.
