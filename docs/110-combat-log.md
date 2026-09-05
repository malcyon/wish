# A combat log

**Status: run against three live fights, and the checklist is closed.** 1428
frames of a slums fight — six characters against orcs — settled the region, the
timing and the shape of the messages, and found two defects that offline tests
could not see, because both turn on bytes only a running game writes. Both are
fixed; see `docs/50-experiments.md`, "The combat log's two defects, found in a
slums fight", and the two rules below marked **live**. A third fight settled
the last item: **the region scrolls** — item 7 below.

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
  **scrolls the window up by one line** — copies every row of the window up
  one, blanks the bottom, and decrements the cursor row. **Watched happening,
  P19 item 7 below**: the check is on the *column* wrap, not on the row.
  `$2D28` bumps `$03CD` when the cursor passes `$03F3`, compares the new row
  against `$03F5` and calls `$2CA5` only if it has reached the bottom. A
  fragment that `COMBAT $299A` places directly on a row past the bottom is not
  checked at all and prints over the combat map.

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

## The last line of all: how the game says who won

**Three lines, and until 2026-09-04 only one of them had been read.** They are
not in `SPELLN00` with the rest of the messages — they belong to `POST.COM`,
which runs after `COMBAT` returns, and they come out of its own 56-entry split
pointer table (lo `$2A8D`, hi `$2AC5`, at overlay base `$0800` and not the
`$1000` the PRG header claims). Entries 2, 3 and 4 sit next to each other:

| `$6DC7` | line, exactly as the game spells it | when |
|---|---|---|
| `$80` | `THE PARTY HAS LOST` | nobody on the party's side is standing and nobody ran |
| `$81` | `THE PARTY RUNS AWAY` | nobody standing, and at least one character's status is `RUNNING` |
| `$00`, `$01` | `THE PARTY HAS WON !` | somebody is still standing |

**The winning line has an exclamation mark and the other two do not.**
`THE PARTY HAS LOST` was read off two driven defeats
(`#128 (Nothing has ever read what the game prints when the party loses a
fight)`); the other two are CONFIRMED from the table. `DEFEATED`, which
`tools/session.py` guessed at for months, is not a word the game uses
anywhere.

`POST.COM $0896` is what decides, by walking every combatant's record and
counting on the status byte at record `0x100`, indexed by the side in
`$6C0C & $7F` — 0 the party, 1 the monsters. `$0903` then reads the party's
living count and writes the answer to `$6DC7`, which is the byte the ECL
scripts branch on (`docs/128-guide-and-scripting.md`,
`docs/134-commissions.md`).

**The line is printed in the full-width text window at row 10, column 1** —
not in the message band. `$0938` loads `#$0A` for the row and `$0E65` takes
the column from `$03F2`, which by then is the whole window rather than the
band `$0970` describes, so a reader that only slices columns 23–38 will miss
it. `CombatLog` does exactly that, so the end of a fight has to be found from
the mode byte and never from this line.

**And the losing line is where a Pool of Radiance game stops.** After the
message and its delay, `$0942`-`$0957` takes three readings and two of the
three ways out are `JMP $0957`, at `$0957` — a jump to itself.

Measured on the running machine, twice, with the same six-character party out
of `PORSAVE13.D64` (`tools/defeatdrive.py`, `work/issue128/run2` and `run3`):

* **66 of 66 program-counter samples read `$0957`** over 70 seconds in the
  second run, and 30 of 31 in the first — the odd one was `$2E25`, inside
  `LIBRARY $2E1F`'s own message delay, taken before the delay had expired;
* **the screen never changed again**, 67 consecutive readings of the same 25
  rows, and **row 24 is blank** — there is no `PRESS <RETURN>` and nothing to
  answer;
* pressing Return, then space, then Return at it changed neither the screen
  nor the program counter;
* `$6DC7` read `$80` and `$6E3E` read 6 throughout.

Nothing on any of the eight disk sides writes `$0957`, `$0958` or `$0959`, so
it is not a dispatch slot patched at run time, and `POST.COM` is byte-identical
on all eight sides. The player's machine is locked and their only way on is to
reset and reload.

The two runs are one party and one save, so what is CONFIRMED is that *this*
defeat locks the machine; that every defeat does rests on the branch, where
both remaining exits also reach `$0957` — `$2B70 >= $6E3E` is the whole party
`GONE` or `DEAD`, and `$6DE6` is written zero by `INIT $091A` and
`POST.COM $14D2` and by nothing else on the side. The one escape left is
`$2B5D`, the party's count of statuses with bit 4 set, and no instruction on
POOL1 sets that bit on a character's status.

## The seven status words, and what a defeat leaves behind

`LIBRARY $38BE` draws the `STATUS` line of the character sheet from the low
three bits of record `0x100`: `LDA $6C00 / AND #$07 / CLC / ADC #$29 / TAX`
into LIBRARY's own string table (lo `$3439`, hi `$347B`, 66 entries, base
`$2C48`), on row 22.

| status & 7 | word | notes |
|---|---|---|
| 0 | — | not a status; an empty roster slot reads 0 |
| 1 | `OK` | what every occupied slot of every save reads |
| 2 | `GONE` | |
| 3 | `DEAD` | |
| 4 | `DYING` | written the turn a character reaches 0 hit points |
| 5 | `UNCONSIOUS` | the game's spelling. Written when the fight ends and the party binds its dying (`COMBAT $2161`) |
| 6 | `RUNNING` | the state that turns a defeat into `THE PARTY RUNS AWAY` |
| 7 | `STONED` | |

Bit 7 on top of those means "out of the fight", which is what `POST.COM`'s
census tests first. So `$84` is a dying character and `$85` an unconscious
one, which is the pair `#235 (Two unattributed DOS byte ranges in the combat tail are dropped converting to C64, and nobody knows what they hold)` watched the engine write.

**A party that loses is left dying, not dead, and nothing binds it.** In both
driven defeats all six characters took `GOES DOWN` then `AND IS DYING`, and
the fight ended with every one of them at `$84`; the binding pass that turns
`$84` into `$85` belongs to the winning path. Nobody reached `DEAD` — a
character at 0 hit points has ten rounds of losing one a round to go, and the
fight was over before then.

**The save disk was not written.** `work/issue128/run3/save-after.d64` has the
same SHA-256 as the player's `PORSAVE13.D64`, `f7e7f1a2…`, so a defeat costs
whatever has happened since the last `ENCAMP > SAVE` and nothing more — and
there is no specimen to keep, because the game authored no bytes.

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
| 7 | the scroll | **CONFIRMED. It scrolls.** Third fight, kobolds and bugbears in the Slums with the P18 party. No natural block reaches row 22, so the window was made small instead: `COMBAT $0970`'s own four bytes were poked to `17 1E 01 11` — columns 23-29, bottom row 16 — while COMBAT was resident, and the game's own messages then overflowed it every round. Two things were watched. **A block that overflowed lost its top line**: `NAME / ATTACKS / SILAS / AND HIT / S FOR 3 / POINTS / OF DAMA / GE` came out as seven rows starting at `ATTACKS`, the name gone. And **rows moved up between two consecutive polls**: row 17 went `KOBOLD ` → `GOES DO` and row 18 `GOES` → `WN` while `$03F4`/`$03F5` stood at 17. At the shipped width nothing wraps far enough — a block would have to run about thirteen rows — which is why 2478 frames of two fights never saw it |
| 8 | after the fight | **not reached** — the fight was ended from the emulator, not through the panel |
| 9 | a fight the party **loses** | **CONFIRMED.** Two runs, `work/issue128/run2` and `run3`, six characters wounded to 1 hit point through the monitor and every turn passed. All six took `GOES DOWN` then `AND IS DYING`, then `THE PARTY HAS LOST` on row 10 of an otherwise empty full-width window, `$6DC7` = `$80`, all six roster statuses `$84`, the save disk untouched, and the machine stopped at `POST.COM $0957` |

Left to do: the same run through the real `AutomapWindow` rather than through
`CombatLog` alone.

**One caution from the scroll run.** With the window narrowed, `CombatLog`'s
own output is nonsense — it slices columns 23-38 from `$0970`'s *documented*
constant and so reads residue from outside the narrowed region. That is the
right behaviour for the shipped window and it is why the verdict above is read
off the raw rows rather than off the messages the reader produced. The raw
frames are `work/p18b/frames-narrow.jsonl`, with `frames-baseline.jsonl` and
`frames-shrink{14,17}.jsonl` beside them; `work/p18b/fight.py` is the driver,
and its `--shrink`/`--narrow` only ever write `$0973`/`$0971` when the four
bytes there really are COMBAT's `17 27 01 17` — the first attempt wrote to
`$0973` while another overlay owned it, which is the hazard
`docs/144-decoding-a-new-title.md` warns about.
