# Loading a Curse save disk in a driven session

What Curse of the Azure Bonds' `LOAD SAVED GAME` actually does, and the three
different things that were making it refuse in a pooled VICE session —
`#291 (A Curse save disk will not load through the game's own front end in a
pooled session, so no C64 Curse party can be got in)`. All three printed the
same sentence, `UNABLE TO LOAD SAVED GAME.`, which is why one of them was
taken for all three.

**A Curse party can be got in.** `tools/curseload.py` does it, and did it four
times on 2026-09-05 on pool slot 1 with two different specimens.

## The refusal is the drive's own error number

`GEN $1F42` is the load, and `LIBRARY $3159` is what it calls:

```
$3159  JSR $31A6        keep A, X and Y
$315C  JSR $319F        SETNAM: length in A, pointer self-modified
$315F  LDA #$0F / LDX $038E / LDY #$00 / JSR $FFBA    SETLFS
$3169  JSR $31B0        A, X and Y back
$316C  LDA #$00 / JSR $FFD5                           LOAD
$3177  JMP $401E        turn the result into a number
```

It is a plain KERNAL `LOAD`. The name is not passed in: `GEN $1F38` stores
`$66` at `$31A0` and `$1F` at `$31A2`, which are the **operands of the
`LDX #$FF` and `LDY #$FF` inside `$319F`**, so the name pointer is written
into the instruction and points at `GEN $1F66`, `SAVEAZURE`. `LIBRARY $427C`
does the same thing with a table for every other file the game loads.

`$401E` decides what the caller sees, and it has two arms:

```
$401E  LDA $7E9F / BEQ $402D          the fastloader flag
$4023  LDA #$00 / BCC $4029 / LDA #$3E / STA $03F1 / RTS
$402D  TALK 8 / TKSA 15 / read the error channel, parse the number into $03F1
```

`$7E9F` is 1 while the game's own fastloader is installed — `GEN $16F9` sets
it after `JSR $B700` — and 0 while it is not, which `GEN $0840` does after
putting the KERNAL's `$0330` vector back. **On the party-formation menu no
fastloader is installed**, measured 0 at every boot, so the number the engine
tests at `GEN $1F4B` is the 1541's own error number, sitting in `$03F1` after
the refusal.

That one byte separates three different faults. CONFIRMED: measured in five
driven sessions.

| `$03F1` | the drive says | what happened |
|---|---|---|
| `00` | `00, OK` | loaded |
| `60` | `60, WRITE FILE OPEN` | the image's `SAVEAZURE` is a file the drive never closed |
| `62` | `62, FILE NOT FOUND` | the save disk was never in the drive |
| `74` | `74, DRIVE NOT READY` | the load was taken inside the drive's own settling time after the attach |

Reading the error channel resets it, so the drive's message buffer (drive
memory `$02D5`, VICE memspace 1) reads `00, OK` by the time anybody looks —
with the tail of the real message still under it, which is how
`00, OK,00,00 READY,00,00` comes to be a useful reading.

## The prompt the game only draws once

`GEN $1F30` calls `$182D` before the load:

```
$182D  LDA #$02 / STA $2CE1
$1832  LDA $03B4 / CMP $2CE1 / BEQ $1860      already the save disk: say nothing
$183A  ... draw INSERT CURSE SAVE DISK, PRESS A KEY, wait for a key ...
$1857  LDA $2CE1 / STA $03B4                  and remember it
```

So the game asks for the save disk **once per boot**, and never again once
`$03B4` reads 2. It does not initialise the drive, and it does not check what
it got: `$03B4` is set by having drawn the prompt, not by anything on the
disk. The general file loader is different — `LIBRARY $42A2` calls the
disk-swap routine at `$453B` on any failed load, and that one sends the drive
an `I` (`$406C`) and retries. **The save loader has no such recovery**: on a
refusal `GEN $1F52` jumps back to `$1F1E` and simply asks the question again.

`LIBRARY $2FF8` is the wait, and it takes **any key from the KERNAL buffer**
(`$C6`, `$0277`, via `$2FD7`) or any movement of the joystick on port 2
(`$DC00 & $1F`).

## Three faults, and what each one needs

### 62, and the second Return nobody sent on purpose

You pick `YES` at `LOAD SAVED GAME ? YES NO`, and the game loads from
whichever disk is already in the drive. `INSERT CURSE SAVE DISK, PRESS A KEY`
was drawn and answered in less time than it takes to read the screen, so
nobody ever saw it and nobody got the chance to swap the image.

The cause is two keypresses for one answer. `Session.select_bar` walks the
highlight and presses Return **over XTEST**; Curse's own key fetcher does not
read that, which is why every Curse tool follows it with a `press_kernal` —
but the KERNAL's interrupt has already put the XTEST Return in the buffer at
`$0277`. Two Returns are queued, the bar takes one, and the prompt takes the
other.

CONFIRMED by counting, with non-stopping execute checkpoints on `GEN $1F30`,
`$183A`, `$1F48` and `$1F4D` in one boot:

| answer | `$1F30` ask | `$183A` prompt drawn | `$1F48` load | `$1F4D` refused | `$03F1` |
|---|---|---|---|---|---|
| two keys, game side in the drive | 1 | 1 | 1 | 1 | 62 |
| one key, nothing attached | 1 | 1 | **0** | 0 | — |

The one-key run sat on `INSERT CURSE SAVE DISK, PRESS A KEY` for the whole
45-second budget and never took the load. That is the same prompt the two-key
run drew and dismissed inside one screen poll.

**This is also why `$03B4` looked broken.** Poked to 1 so the prompt would be
drawn again, `#291 (A Curse save disk will not load through the game's own front end in a pooled session, so no C64 Curse party can be got in)` reported that it was not. It was: `$183A` fired, and the
spare Return took it in under 1.5 seconds. The poke works.

`tools/curseload.py`'s `answer_yes` walks the bar with the arrows, which Curse
*does* read from XTEST, and answers with exactly one `press_kernal`.

### 74, and a wait the machine slept through

You attach the save disk at the prompt, press a key, and the load comes back
`74, DRIVE NOT READY` with the right disk in the drive.

An emulated 1541 reports itself not ready for about a second of its own clock
after an image is attached; that is how VICE tells the guest the disk changed.
`Session.attach` waited half a second **inside a monitor connection**, and the
machine is stopped for as long as one of those is open, so the wait passed no
emulated cycles at all and the drive never settled.

The wait now happens after the monitor lets go — `Session.ATTACH_SETTLE`, 3.0
seconds, overridable per call. CONFIRMED by the same command run twice with
nothing else changed: `$03F1` = 74 and a refusal without it, `$03F1` = 0 and
a party on the screen with it.

This is the same fault as `#192 (Convert a Curse of the Azure Bonds DOS save
into a C64 one, which the importer refuses today)`'s second `ENCAMP > SAVE`
coming back `--SAVE ERROR--` until the image was detached and put back.

### 60, and a save disk the drive never finished writing

Two of the five Curse specimens in `~/wish-specimens/por-c64/` hold
`SAVEAZURE` with directory type byte `$02` and a block count of zero — a file
the drive still believes is open for writing, which a listing shows as
`*PRG`. The 1541 will not open one for reading, and the engine reports
`60, WRITE FILE OPEN` as `UNABLE TO LOAD SAVED GAME.`

| disk | type | blocks | payload |
|---|---|---|---|
| `WISH-SPEC-curse-h-engine-resave.D64` | `$82` | 30 | 7426 |
| `WISH-SPEC-curse-h-engine-resave-walked.D64` | `$82` | 30 | 7426 |
| `WISH-SPEC-curse-train-input.D64` | `$82` | 30 | 7426 |
| `WISH-SPEC-curse-dual-classed.D64` | **`$02`** | **0** | 7426 |
| `WISH-SPEC-curse-trained-party.D64` | **`$02`** | **0** | 7426 |

The payload is intact in all five — the data blocks are written before the
directory entry is finished — so the disks are recoverable rather than lost.
`tools/curseload.py --repair` sets the bit and the block count in the staged
copy inside the pool slot, never in the specimen, and the repaired
`WISH-SPEC-curse-dual-classed.D64` loaded its party in the running game where
the specimen itself had not.

Both damaged disks were copied out of a pool slot after the engine's own
`SAVE CURRENT GAME`, and both of the sound ones under `work/issue18/` were
written by our tools before a boot; `work/issue192/run1/engine-resave.D64` is
an engine save that came out closed. So it is a race between the copy and the
drive rather than anything the engine does wrong, and it is ours.

## Getting a party in

`tools/curseload.py` is the tool, and `load_saved_game()` inside it is the
sequence, for any other tool that needs one:

1. walk the party menu to `LOAD SAVED GAME`, Return through the KERNAL buffer;
2. answer `LOAD SAVED GAME ? YES NO` with **one** key;
3. at `INSERT CURSE SAVE DISK, PRESS A KEY`, attach the save disk, let the
   drive settle, *then* press a key;
4. wait for `BEGIN ADVENTURING` on the menu, which is the party being in.

A refusal leaves **the question** up rather than the menu, because `GEN $1F52`
jumps to `$1F1E`. So a retry answers the bar that is already there; walking
the menu for a label that is only the bar's own text presses nothing and looks
exactly like a session that has stopped responding. Call `load_saved_game`
again with `retry=True`.

Two things about the front end that cost time before this and are settled:
the party menu's highlight is the **colour RAM at the label's own column**
rather than a row's dominant colour, so `Session.select_row` never starts the
walk (`tools/dualclassagain.py` has the reader), and Return is read from the
KERNAL buffer rather than from XTEST while the arrows are read from XTEST.

## What is not settled

**Whether the drive's error channel is readable while the fastloader is
installed.** `$7E9F` was 0 at the party menu in every session here, so the
`$4023` arm — where a failure is `$3E` and nothing says which — has never been
watched. It is the arm that runs once the party is adventuring, so a save
taken from inside the world reports its failures with less information than
the front end does. The experiment is to break at `GEN $1FDC` during an
`ENCAMP > SAVE` and read `$7E9F`.

**Why `#291 (A Curse save disk will not load through the game's own front end in a pooled session, so no C64 Curse party can be got in)`'s own sessions refused with the save disk attached.** Their logs
survive at `work/issue256-dual/c64/run.jsonl` and stop at `menu-miss` before
any load, so the refusals they describe came from driving by hand over the
command port and no transcript of that survives. All three faults above were
reachable from the state those sessions were in, and `$03F1` was never read at
the time, so which one they hit cannot be recovered. It does not matter for
the fix: all three are closed.
