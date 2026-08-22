# Does the fastloader answer make any difference? — plan

**Status: nothing measured. This is the plan for a measurement, plus three
config facts found while writing it that may settle the question before the
emulator is started at all.**

Donald: *"You have guidance on whether we should answer Y/N to the fastloader
question, but in my experience, either option makes no difference at all. It
still takes a long time to load."*

---

## The verdict, in advance

**No document in this project cites a measurement.** Every statement of the
guidance traces back to one assertion — "leaving the game's loader on conflicts
with [JiffyDOS]" — repeated in five places and timed in none. Donald is
challenging an assumption, not a finding.

And the assumption looks shaky for a reason nobody has written down:

> **JiffyDOS is PROBABLY only half-installed here.** `vicerc` sets
> `DosName1541ii`, which VICE applies only to a drive of type **1542** (its
> number for the 1541-**II**). `Drive8Type` does not appear in `vicerc` at all,
> and that file is rewritten on exit (`SaveResourcesOnExit=1`), so drive 8 is at
> VICE's default — a plain **1541**, whose ROM comes from `DosName1541`, which
> is unset and therefore stock.

JiffyDOS is a protocol between a patched kernal and a patched *drive*. With only
the C64 half installed, the kernal detects a stock drive and falls back to
ordinary serial. That makes **`Y` the slowest possible path**, not the fastest —
and it makes the guidance not merely unmeasured but backwards.

That is the leading hypothesis, it is check #1 below, and it costs one monitor
command.

---

## 1. Where the guidance lives, and what it rests on

| where | what it says | evidence offered |
|---|---|---|
| `docs/00-overview.md:59-67` | answer **Y**; "JiffyDOS does the fast loading; leaving the game's loader on conflicts with it, and the failure mode looks like a bad disk image" | none |
| `docs/70-driving-the-game.md:124` | table row: `DISABLE FASTLOADER (Y/N)?` → `Y` (VICE runs JiffyDOS here) | none |
| `docs/122-release-testing.md:379` | release walkthrough step L7: "Answer **Y**" | none |
| `docs/122-release-testing.md:549-550` | Windows walkthrough: "**Y** if this VICE has JiffyDOS; a stock Windows VICE will not, in which case **N**" | none — and this is the one that could mislead a stranger |
| `docs/123-parallel-sessions.md:110,521` | a pooled `vicerc` must keep the JiffyDOS paths *because* the fastloader answer depends on them | none; it cites `00-overview` |
| `tools/session.py:302-306` | `Session.boot()` answers `y` unconditionally | none |
| memory `vice-jiffydos-fastloader-prompt.md` | states the conflict as fact | none |
| `skills/goldbox/references/driving.md:101` | "answer per the emulator's own fast-loading setup" | the only one already agnostic; it survives whatever we find |

Two of those describe a *failure* ("looks like a bad disk image"), which is a
different claim from *slower* and is not what Donald is reporting. Both claims
need separating, and the plan below separates them: a cell either boots or it
does not, and if it boots it has a time.

**Polarity, stated once, because half the confusion is here.** The prompt is
`DISABLE FASTLOADER (Y/N)?`.

* **`Y` = disable the game's own loader** → loading goes through the KERNAL,
  where JiffyDOS (if fully installed) accelerates it.
* **`N` = keep the game's own loader** → the game uploads its own code to the
  drive and neither KERNAL nor JiffyDOS is involved.

---

## 2. Pre-flight — three checks before any timing run

All three are cheap, none needs the game running, and #1 may end the
investigation.

| # | check | how | what it would mean |
|---|---|---|---|
| 1 | **`Drive8Type`** | `resourceget Drive8Type` on the text monitor (`127.0.0.1:6510`), the socket `tools/session.py` already opens | `1541` → the JiffyDOS drive ROM is **not loaded** and the `Y` path is plain serial. `1542` → JiffyDOS is fully installed and hypothesis H1 dies |
| 2 | **`AutostartHandleTrueDriveEmulation=1`** (`vicerc`, present) | already read; confirm with `resourceget` | VICE turns true drive emulation **off** for the autostart and puts it back afterwards — the binary carries `Restoring true drive state of drive %d:%d`. Part of every boot therefore loads through VICE's trap at host speed, under *neither* loader. A real confound; pin it to `0` for the runs |
| 3 | **which kernal is actually live** | read `$E000-$FFFF` through the monitor and `cmp` against `JiffyDOS_C64_6.01.bin` and `kernal-901227-03.bin` | proves what is in the machine rather than what the rc names. Do this for the stock-kernal row too, or that row proves nothing |

Also worth recording once, since they set the units: `MachineVideoStandard=2`
(NTSC) and `MachinePowerFrequency=60`. The jiffy clock ticks 60/s here, which
matches the 62-jiffies-in-1.03 s already in `docs/50-experiments.md`.

---

## 3. What is timed

### The window

Donald asked for "load the game to the title screen". A script needs both ends
nailed down, and the boot has more than one interesting segment, so record a
**timeline of milestones** and report the segments as well as the total.

| marker | detected by | why |
|---|---|---|
| **T0** launch | the moment `porlaunch.sh` execs `x64sc` | includes Xephyr and VICE startup — reported, never compared |
| **M1** `DISABLE FASTLOADER (Y/N)?` on screen | text on the screen | everything before this is the autostart of `BOOT`, which happens under `AutostartWarp` and with TDE flipped off — it is *not* the thing being measured |
| **M2** the answer key delivered | the `xdotool` call returns | **the start of the timed window** |
| **M3** the title / credits screen | see below | **the headline end condition** |
| **M4** `INPUT THE CODE WORD` | text | |
| **M5** main menu, `LOAD SAVED GAME` | text | |
| **M6** `BEGIN ADVENTURING` | text | the party is loaded |
| **M7** `ENCAMP` | text | in the world |

**M2 → M3 is the number Donald asked for.** M3 → M7 is reported too, because
the fastloader affects every overlay load and the game is heavily overlaid: if
the loader matters at all, it matters more over the whole boot than over the
first segment. If a difference exists anywhere it will show up in the segment
table.

### Detecting M3 without a human watching

`automap/screen.py` will not do it directly: `is_bitmap()` exists precisely
because "title and credit screens are bitmaps and cannot be read as text", yet
`Session.boot()` finds `PLAY GAME` as *text*. So there are at least two screens
here and their order is not documented.

**Do not guess the marker — derive it.** First run of the experiment is a
**trace run**: one boot, sampled every 0.25 s, recording `$D011` bit 5 (bitmap
mode), the VIC screen address, row 24 as text, and a frame capture. Read the
trace, choose M3 from it, and write the chosen predicate into the harness. Then
every timed run uses that predicate and nothing else.

Expect M3 to end up as *"`$D011` bit 5 sets and the frame stops changing"*, with
`PLAY GAME` on row 24 as the secondary marker — but that is a **GUESS** until
the trace says so.

### Which clock

**The headline number is wall clock**, because that is what Donald experiences
and what the complaint is about. Emulated time is the cross-check.

| clock | use it? | why |
|---|---|---|
| host `time.monotonic()` | **yes — the answer is in this** | it is what a person waits |
| **CIA #1 TOD**, `$DC08-$DC0B` | **yes — the cross-check** | driven by the power-frequency input, so it keeps counting whatever the CPU is doing |
| KERNAL jiffy clock, `$A0-$A2` | **no** | it is ticked by the KERNAL IRQ, and **a fastloader disables interrupts**. It would under-count exactly the interval in question and would bias the `N` cell low — the one clock guaranteed to give a wrong answer to this particular question. `docs/70:239` recommends it for elapsed emulated time in general; that recommendation does not extend here, and this document is the exception |

Validate the TOD before trusting it: read it twice across a 30 s idle at the
title screen and check it advanced 30.0 ± 0.2 s. If the game writes the TOD
registers, or sets CRB bit 7, this fails and the cross-check is dropped rather
than fudged. Reading through the monitor with `side_effects=0` bypasses the
latch/unlatch pair, so read all four bytes in one burst — **PROBABLE**, confirm
in the idle test.

At `-speed 100` with warp off the two clocks should agree within 1-2 %. **If
they disagree, report both**, and the disagreement is itself the finding: warp
was on, or the host could not keep up.

### Do not measure through the monitor

Polling the binary monitor hands the emulation ~14.3 ms of extra emulated time
*per `resume()`* (`docs/50-experiments.md`, "Polling does not stall the
emulator"). At 0.25 s that is 5.7 % — on a 90 s boot, five seconds, quite
possibly larger than the effect being hunted.

So **poll the X server, not the emulator**:

```
ffmpeg -f x11grab -framerate 4 -video_size 1400x1050 -i :7 \
       -vf scale=350:-1 -y work/drive/timing/<cell>-<run>.mkv
```

Frame timestamps come out of the container, the emulator is not touched, and
each run leaves a re-examinable artefact. Two monitor connections per run —
one TOD read just before M2, one just after M3 — cost ~28 ms of distortion
between them and are the only monitor traffic in the window.

`x11grab` costs host CPU, which could in principle slow the emulator. Control:
record **every** cell so the cost is a constant, and run one extra
unrecorded cell timed by TOD alone to bound it.

Fallback if `ffmpeg -f x11grab` will not attach to Xephyr: `import -window root
ppm:-` in a loop, hashing each frame and keeping only the first frame of each
new hash. `Keyboard.screenshot()` in `tools/drive.py:112` already shells to
`import`. PPM rather than PNG because PNG metadata defeats hashing.

---

## 4. The matrix

**Constants for every cell**, set on the command line so no config file is
touched:

| setting | value | why |
|---|---|---|
| warp | `+warp +autostart-warp` | **warp must be off.** `InitialWarpMode` defaults off but `AutostartWarp` does not obviously; pass both explicitly and verify by wall-vs-TOD agreement |
| `-speed 100` | already in `porlaunch.sh` | pins emulated to real time |
| `AutostartHandleTrueDriveEmulation` | `0` | otherwise VICE flips TDE off and back mid-boot (pre-flight #2) |
| `+saveres` | **mandatory** | `SaveResourcesOnExit=1` in Donald's rc. Without `+saveres`, a run that overrides `-kernal` writes the *stock* kernal path into his config on exit. This is the single most dangerous line in the experiment |
| disk images | one fixed copy set under `work/drive/` | `Session.attach` refuses anything else, and the game writes to its disks |
| process | cold `x64sc` per run | no state carried between runs |

The cells:

| cell | kernal + drive ROM | answer | `Drive8Type` | runs | what it is for |
|---|---|---|---|---|---|
| **A** | JiffyDOS both halves | **Y** | as found | 5 | today's guidance, as actually configured |
| **B** | JiffyDOS both halves | **N** | as found | 5 | Donald's claim |
| **C** | stock (`kernal-901227-03.bin` + `dos1541-325302-01+901229-05.bin`) | **Y** | as found | 5 | **the diagnostic cell.** If A ≈ C, JiffyDOS is doing nothing on the Y path |
| **D** | stock both halves | **N** | as found | 5 | the game's own loader with no JiffyDOS anywhere; should equal B if the loader is real |
| **E** | JiffyDOS both halves | **Y** | forced **1542** | 3 | only if pre-flight #1 says `1541`. This is the "make JiffyDOS actually work" cell, and it may be the entire answer |
| **F** | as found | **N** | as found, TDE **off** (`+drive8truedrive`) | 1 | a probe, not a timing cell. A custom drive loader cannot work without a real drive; expect a hang or a corrupt load, which is the "looks like a bad disk image" symptom `00-overview` describes — attached to the wrong cause |
| **G** | as found | **Y** | as found, `AutostartHandleTrueDriveEmulation=1`, autostart warp default | 3 | the control: how much were the two VICE defaults distorting the numbers everyone has been looking at? |

The stock-kernal rows need **both** ROMs swapped —
`-kernal <stock> -dos1541II <stock>` — because swapping one leaves a
half-installed JiffyDOS, which is the very state under suspicion. Both stock
ROMs ship inside the flatpak at
`~/.local/share/flatpak/app/net.sf.VICE/current/active/files/share/vice/{C64,DRIVES}/`.

`-config <file>` would be tidier than command-line overrides, and
`docs/123-parallel-sessions.md` §2 claims `x64sc` 3.10 has it. **I could not find
the literal `-config` in this binary's option strings** (the help text "Specify
config file" is there; the flag is not). Check `x64sc -help | grep -i config`
before relying on it; `+saveres` plus command-line overrides needs no such
check and is what this plan uses.

### Why five runs

Not for the average — for the **spread**. Emulated 1541 loading is nearly
deterministic; the host is not. Five runs give a range, and **the range is what
makes the Y-vs-N difference interpretable**: if the within-cell range exceeds
the between-cell gap, there is no gap. One measurement of a loading time is
worth almost nothing, and two is worth only slightly more.

Discard run 1 of each cell as host-page-cache warm-up, report **median and full
range** of runs 2-5, and publish every individual number. Five runs × seven
cells × ~3 minutes ≈ **75 minutes of serialised emulator time**, plus the trace
run and the probes.

---

## 5. Running it unattended

`tools/session.py` does most of it already. What it needs:

| # | change | where |
|---|---|---|
| 1 | the fastloader answer becomes a parameter | `Session.__init__`, used at `session.py:305`; default from `POR_FASTLOADER`, falling back to today's `y` |
| 2 | extra launch flags pass through | `porlaunch.sh` already forwards `$MONFLAGS`; add a `$PORFLAGS` alongside it rather than widening `MONFLAGS` |
| 3 | milestone timestamps recorded | one `(name, monotonic, tod)` row per marker, written as JSON per run |
| 4 | the boot is **not** aborted at M3 | run through to M7 so the segment table is complete |

### Hazards, all of them already known here

* **`tools/session.py:69-70` and `:105-106` run `pkill -x x64sc` on every launch
  and every close.** For 25 sequential launches that is 25 chances to kill
  somebody else's emulator or Donald's own game. Check `ss -tnp | grep 6502`
  before starting, **announce the run**, and do not start it while another agent
  holds VICE. `docs/123-parallel-sessions.md` §1 item 2 calls removing those four
  calls the single most important change in that plan; if `tools/instance.py`
  (**P46**) lands first, run this on the pool instead and the hazard goes away.
* **Never leave a checkpoint armed when the socket closes.** This experiment
  needs no checkpoints at all. Do not add any.
* **One binary-monitor connection per VICE process.** Two monitor touches per
  run, both connect-read-close.
* **XTEST keys do not reach the game while a monitor client holds the socket.**
  Never type with a monitor connection open. The fastloader prompt itself is
  answered by XTEST today and that works (`session.py:305`); `Return` at the
  code-word prompt does not, and goes through `press_kernal()` — the KERNAL
  buffer at `$0277`/`$C6`. If any cell's answer key is swallowed, the KERNAL
  buffer is the reliable route for `Y`/`N` too.
* **The first input burst after a screen change is reliably swallowed.** Verify
  the answer landed by effect — the prompt clears — not by having sent it.
* **`+saveres` on every launch.** Repeated because forgetting it once
  permanently changes Donald's kernal.

---

## 6. What each outcome means

### If A and B differ by more than the within-cell range

The guidance stands and now has a number. Write it into `docs/00-overview.md`,
replace "conflicts with it" with the measured margin, and stop.

### If A ≈ B — the interesting case

Five hypotheses, each with the cell or probe that kills it. **They are not
alternatives to be argued between; the matrix tests all five in the same 25
runs.**

| # | hypothesis | predicts | killed by |
|---|---|---|---|
| **H1** | **JiffyDOS is half-installed** (kernal patched, drive ROM stock), so `Y` is plain serial | **A ≈ C**, and **E ≪ A** | pre-flight #1 (`Drive8Type`), cell C, cell E |
| **H2** | The answer never reaches the game | drive-8 RAM and the game's flag byte identical after `Y` and after `N` | the drive-RAM read below |
| **H3** | The game's loader is **absent** — these are cracked releases and a cracker removed it, leaving a vestigial prompt | **no drive code uploaded under either answer**; B ≈ D ≈ A | the drive-RAM read below |
| **H4** | JiffyDOS masks the difference; both paths are genuinely fast and comparable | **C ≫ A** (stock kernal makes `Y` much slower) while B ≈ D | cell C |
| **H5** | Transfer is not the bottleneck — seek, decompression, and VICE's TDE-off autostart dominate | the gap appears in no segment; **G ≠ A** by a lot | the segment table, cell G |

H1 and H4 are mutually exclusive and **cell C separates them in five runs**.
That is the highest-value cell in the matrix after A and B.

### The drive-RAM read — the decisive diagnostic for H2 and H3

A C64 fastloader works by **uploading 6502 code into the 1541's own RAM**
(`$0300-$07FF`) and running a private transfer protocol. So:

> Read drive 8's RAM immediately after the first game load. If `N` leaves code
> there and `Y` leaves it stock, the answer reaches the game and the two loaders
> are genuinely different. If **neither** answer puts code there, the game's
> loader is not being used at all — H2 or H3 — and no amount of timing will
> distinguish Y from N because there is nothing behind the prompt.

Mechanically: VICE's `MEM_GET` body is `side_effects, start, end, **memspace**,
bank`, and `automap/vice.py:170` hard-codes that memspace byte to `0` (main
CPU). Drive 8 is memspace `1`. Either add the parameter — a one-line change to
`Monitor.read`, worth making permanently — or use the text monitor's
device-prefixed form (`m 8:0300 07ff`, syntax **PROBABLE**, confirm with
`help m` on the text socket).

Distinguishing H2 from H3 once drive RAM comes back empty for both: find the
byte the prompt handler writes and watch it change between a `Y` boot and an
`N` boot. If it changes, the answer arrived and the code behind it does nothing
(H3, the cracker). If it does not change, the keystroke never landed (H2), and
the fix is `press_kernal()` rather than XTEST.

### If cell F hangs or corrupts

That is the "**failure mode looks like a bad disk image**" that
`docs/00-overview.md:61` blames on the fastloader answer — reproduced, with true
drive emulation as the actual cause. Worth confirming precisely because the
overview's advice may be right about the *symptom* and wrong about the *cause*,
and a stranger following `122` §W3 on Windows is being told to fix it with the
wrong knob.

---

## 7. What to do with the answer

### Documents that would need correcting

| file | what changes |
|---|---|
| `docs/00-overview.md:59-67` | the whole paragraph. It asserts a conflict and a failure mode with no evidence; replace with the measured segment table and a one-line recommendation |
| `docs/70-driving-the-game.md:124` | the row keeps an answer; the parenthetical reason changes or goes |
| `docs/122-release-testing.md:379,549-550` | **the Windows instruction is the priority** — it tells a stranger with a stock VICE to answer `N` on the strength of this same untested assumption |
| `docs/123-parallel-sessions.md:110,521` | check 4's stated reason ("the fastloader answer depends on it") may evaporate. The check itself survives on reproducibility grounds; rewrite the justification, do not delete the row |
| memory `vice-jiffydos-fastloader-prompt.md` | Donald's file. **Flag it, do not edit it** |
| `skills/goldbox/references/driving.md:101` | already agnostic; expect no change |
| `docs/50-experiments.md` | gains the experiment: hypothesis, matrix, every individual run, and the hypotheses that died. That is the actual product |
| `docs/TASKS.md` | a row under "Needs an emulator". Next free code is **P69** |

### `tools/session.py`

Whichever way it lands:

1. **Make the answer a parameter** (`POR_FASTLOADER`, default the winner).
   Today it is a constant `y` at `session.py:305` with no way to override it,
   which is why nobody has ever A/B'd it.
2. **Keep answering *something*.** The prompt blocks the boot; the failure mode
   of not answering is a 120 s timeout at `session.py:302`.
3. **Do not make it conditional on the kernal in code.** Runtime inference about
   which ROM VICE loaded is fragile and invisible. If the right answer really
   does depend on the kernal, that belongs with the launch flags, which the
   instance pool (**P46**) already owns.
4. **Change the default only if the margin exceeds the within-cell range**, and
   put the measured numbers in the docstring in one line.

If H1 is confirmed, there is a fifth action worth more than any of them:
**recommend Donald set `Drive8Type=1542`** so the JiffyDOS drive ROM he
installed is actually loaded. That is a suggestion to a human about his own
config, not a change to make — nothing in this project writes his `vicerc`.

---

## 8. Verification

| # | check | how |
|---|---|---|
| 1 | `python3 -m pytest tests/ -q` unchanged | this document changes no code |
| 2 | `~/.var/app/net.sf.VICE/config/vice/vicerc` byte-identical after every run | `cmp` before and after. **The most important check in the list**, given `SaveResourcesOnExit=1` and a `-kernal` override |
| 3 | nothing under `/mnt/media/roms/c64/Pool of Radiance Disks/` changed | `find … -newermt` after the run |
| 4 | no checkpoints survive any run | `checkpoints_clear()` returns 0 at close |
| 5 | warp really was off | wall clock and CIA TOD agree within 2 % in every cell |
| 6 | the stock-kernal cells really ran a stock kernal | pre-flight #3, per cell, not once |
