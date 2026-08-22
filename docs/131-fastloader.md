# Does the fastloader answer make any difference?

**Status: measured.** 24 boots, five per cell. `work/reports/p69-fastloader.md`
is the run sheet, `work/p69/` holds the harness and the raw JSON.

Donald: *"You have guidance on whether we should answer Y/N to the fastloader
question, but in my experience, either option makes no difference at all. It
still takes a long time to load."*

---

## The answer

**On this machine, Donald is right.** `Y` reaches the main menu in 167.8 s and
`N` in 168.8 s — a 1.0 s margin against a within-cell spread of up to 1.1 s.
The two answers are not distinguishable by waiting.

**On a stock kernal the answer is worth 39 s, and `N` is the faster one.** So
the advice is real but it is *kernal-dependent*, and exactly one document in
the project already said so.

| kernal + drive ROM | answer | answer key → main menu | spread over 5 runs |
|---|---|---|---|
| JiffyDOS both halves (Donald's) | `Y` | **167.8 s** | 0.3 |
| JiffyDOS both halves | `N` | 168.8 s | 1.1 |
| stock 901227-03 + 251968-03 | `Y` | 238.6 s | 0.2 |
| stock both halves | **`N`** | **199.6 s** | 1.0 |

**And it is not because there is nothing behind the prompt.** The two answers
leave visibly different code in the drive; the difference is real and it is
JiffyDOS that erases it. See "the drive-RAM read" below.

---

## Polarity, stated once, because half the confusion is here

The prompt is `DISABLE FASTLOADER (Y/N)?`.

* **`Y` = disable the game's own loader** → loading goes through the KERNAL,
  where JiffyDOS accelerates it.
* **`N` = keep the game's own loader** → the game uploads its own code into the
  drive and runs a private transfer protocol.

---

## What the machine actually is

Three pre-flight facts, each of which killed a hypothesis before any timing.

| check | value | consequence |
|---|---|---|
| `resourceget "Drive8Type"` | **1542** — the 1541-**II** | **JiffyDOS is fully installed.** `DosName1541ii` is the resource that governs a 1542, and it names the JiffyDOS drive ROM |
| drive 8 ROM at `$E780` | `60 AD 0C 1C 29 1F …` | the JiffyDOS 1541-II 6.00 image. Stock 1541-II reads `EA` there and stock 1541 reads `60 EA` — three-way separable in sixteen bytes |
| md5 of the live `$E000-$FFFF` | `be09394f…` on the default flags, `39065497…` under cell C and D's | byte-identical to `JiffyDOS_C64_6.01.bin` and to `kernal-901227-03.bin` respectively, so `-kernal` does take |

**`Drive8Type` is absent from `vicerc`, and VICE's default here is 1542, not
1541.** The plan this document replaces reasoned from a default of 1541 and
built its leading hypothesis on it. That reasoning was wrong and one monitor
command settled it.

**Do not identify the kernal from a short window at `$E000`.** JiffyDOS 6.01
and `901227-03` share their opening bytes; the per-run 16-byte probe that did
so proved nothing, and the md5 of the whole 8 KB is what the row above rests
on. The drive ROM needs no such care — `$E780` separates all three candidates.

`-config <file>` **does** exist in this `x64sc`; the earlier draft could not
find it in the option strings. The runs use it, through the instance pool's
per-slot `vicerc`.

---

## The matrix

Constants, all on the command line so no config file is touched: `+saveres`,
`+warp`, `+autostart-warp`, `+autostart-handle-tde`, `-speed 100`, a cold
`x64sc` and a fresh copy of side 1 per run, `POR_HEADLESS=1`, one pool slot per
worker.

| cell | kernal + drive ROM | answer | runs |
|---|---|---|---|
| **A** | JiffyDOS both halves | `Y` | 5 + 1 serial control |
| **B** | JiffyDOS both halves | `N` | 5 |
| **C** | stock `kernal-901227-03` + `dos1541ii-251968-03` | `Y` | 5 |
| **D** | stock both halves | `N` | 5 |
| **G** | as found, VICE's own autostart warp and TDE handling | `Y` | 2 |
| **F** | as found, true drive emulation **off** | `N` | 1 probe |

Cell **E** — "force `Drive8Type=1542` and see whether JiffyDOS starts
working" — was never run, because pre-flight #1 showed it is already 1542.

### Milestones

| marker | detected by |
|---|---|
| **T0** | `porlaunch.sh` execs `x64sc` |
| **M1** | `DISABLE FASTLOADER (Y/N)?` on screen |
| **M2** | the answer key delivered — **the timed window opens here** |
| **M3** | the title picture: `$D011` bit 5 sets |
| **M4** | the credits screen, `PLAY GAME` readable |
| **M5** | `INPUT THE CODE WORD` |

**M3 is a soft marker and its numbers should not be leaned on.** M2→M3 and
M3→M4 are exactly anti-correlated in every cell — 31.9 + 131.4 and 40.1 + 123.2
both make 163.3 — so the screen-mode edge is being caught at one of two places
about 8.3 s apart while M4 stays fixed to a tenth. M2→M4 and M2→M5 are the
numbers with a claim behind them.

### Which clock

**Wall clock, `time.monotonic()` on the host**, because that is what a person
waits.

The KERNAL jiffy clock at `$A0-$A2` is not used and must not be: it is ticked
by the KERNAL IRQ and a fastloader disables interrupts, so it would under-count
exactly the interval in question and bias the `N` cells low.

**The CIA #1 TOD cross-check was dropped, not fudged.** `$DC08-$DC0B` read one
o'clock and zero tenths at every sample of every run — it does not advance in
this configuration and measures nothing. What replaces it: `resourceget`
confirms `AutostartWarp=0` and `Speed=100` per run, and the VICE status bar
reads `101% cpu / 60.3 fps` with the warp indicator dark in every capture.

### On polling the monitor

The plan forbade it, on the grounds that each `resume()` hands the emulation
~14.3 ms and 0.25 s polling would distort a 90 s boot by seconds. The runs poll
at **1.0 s** instead, identically in every cell, and the distortion is bounded
by the result rather than by the argument: **four of the five timed cells
reproduce M2→M5 within 0.3 s over five cold processes.** A systematic error
that repeats to a tenth of a second cannot be what a 39 s gap is made of.

Three sessions ran in parallel on three pool slots. The serial control boot of
cell A came out at 167.6 s against the parallel runs' 167.7–167.9 s, so
contention on a 12-core host is worth 0.3 s.

---

## What died

| # | hypothesis | verdict |
|---|---|---|
| **H1** | JiffyDOS is half-installed, so `Y` is plain serial | **dead.** `Drive8Type=1542` and the drive ROM at `$E780` is the JiffyDOS image |
| **H2** | the answer never reaches the game | **dead.** Drive 8's RAM after the first load differs between `Y` and `N` in 976 of 1280 bytes |
| **H3** | the game's loader is absent — a cracker removed it, leaving a vestigial prompt | **dead.** Under `N` a kilobyte of drive RAM matches no sector on the disk |
| **H4** | JiffyDOS masks the difference; both paths are fast and comparable | **survives, and is the answer.** It predicted C ≫ A, which holds by 70.8 s. Its second clause, B ≈ D, fails by 30.8 s |
| **H5** | transfer is not the bottleneck; the gap appears in no segment and G ≠ A | **dead.** The gap is squarely in the loading segments, and G ≡ A inside the timed window |

**H4's second clause failing is a finding in itself.** `N` means the game's own
loader, so B and D should have loaded at the same speed whatever kernal was
underneath — and they differ by 30.8 s. A large part of what is loaded between
the answer and the main menu therefore goes through the KERNAL *whichever way
the prompt is answered*, and that is why JiffyDOS helps both cells and why the
answer changes so little on this machine.

### The drive-RAM read, and what it settled

Drive 8's RAM `$0300-$07FF` was read on the text monitor (`m 8:0300 07ff`)
immediately after the first game load, and every populated page compared
against the sectors of `POOL1.D64`.

| answer | `$0300` | `$0400` | `$0500` | `$0600` | `$0700` |
|---|---|---|---|---|---|
| **`Y`** | on disk | on disk | on disk | empty | on disk |
| **`N`** | **not on disk** | **not on disk** | **not on disk** | **not on disk** | on disk |

Under `Y` every non-empty page of drive RAM is a verbatim sector off the disk —
ordinary DOS buffers, nothing uploaded. Under `N` a kilobyte of drive RAM
matches **no sector on the disk at all**: it arrived over the serial bus. That
is the game's fastloader, present and running, in a cracked release. Both
dumps are byte-identical run to run, and the pattern is the same under a stock
kernal as under JiffyDOS.

### Cell F: the "bad disk image" symptom, and its real cause

With true drive emulation off, the boot **never reaches the fastloader prompt
at all**. It stops at `SEARCHING FOR *` under the JiffyDOS banner and stays
there; the run was abandoned at 909 s with drive RAM completely empty.

`docs/00-overview.md` attributes a failure that "looks like a bad disk image"
to answering the prompt wrongly. That failure is reproducible from true drive
emulation, and it happens **before the question is asked** — so it cannot be
what the answer causes. No answer failed a boot in this experiment: all 23
timed runs reached the code-word prompt, ten of them on the answer the
guidance calls wrong for their kernal.

### Cell G: what VICE's own defaults were doing

`AutostartWarp` and `AutostartHandleTrueDriveEmulation` left at VICE's defaults
give M2→M5 = 167.7 s against cell A's 167.8 — identical. The whole of their
effect, 3.1 s, is in T0→M2, the autostart of `BOOT` before the prompt appears.
They were never distorting the loading; they were distorting the launch.

---

## The segment table

| cell | | M2→M3 title | M3→M4 credits | M4→M5 code word | M2→M5 | T0→M5 |
|---|---|---|---|---|---|---|
| **A** | JiffyDOS `Y` | 31.9 | 131.4 | 4.4 | **167.8** | 182.5 |
| **B** | JiffyDOS `N` | 43.2 | 121.2 | 4.4 | **168.8** | 183.6 |
| **C** | stock `Y` | 69.9 | 160.2 | 8.5 | **238.6** | 256.4 |
| **D** | stock `N` | 75.0 | 121.1 | 4.4 | **199.6** | 217.4 |
| **G** | defaults `Y` | 31.9 | 131.4 | 4.4 | **167.7** | 179.4 |

Medians of five runs; the per-run numbers and ranges are in the run sheet.
Read M2→M3 and M3→M4 together, for the reason under "Milestones".

**M3→M4 has a floor of about 121 s**, hit by both `N` cells and by neither `Y`
cell. The title picture is displayed for a fixed time and the credits load
happens behind it: when the load fits, the segment is the timer; when it does
not, the segment is the load. Cell C is 39 s over the floor, and that is
precisely the 39 s by which it loses to cell D.

So on a stock kernal the answer is worth 39 s of waiting, and on this one the
title sequence has already absorbed everything there was to absorb.

---

## What follows

* **`tools/session.py` keeps `y` as its default.** The margin on this machine,
  1.0 s, does not exceed the within-cell range, 1.1 s, so there is no
  measurement here that argues for changing it — and `Y` is the right answer
  by 39 s on the stock-kernal configuration's mirror image. The docstring
  carries the numbers.
* **A stock VICE should answer `N`** — 199.6 s against 238.6 s.
  `docs/122-release-testing.md` §W3 already says this, and is the only place in
  the project that had it right.
* **Nothing needs `Drive8Type` set.** VICE defaults it to 1542 here and the
  JiffyDOS drive ROM loads.
* **The failure mode `docs/00-overview.md` describes belongs to true drive
  emulation, not to the answer.** Cell F reproduces it; no mis-answered boot
  reproduces anything.
