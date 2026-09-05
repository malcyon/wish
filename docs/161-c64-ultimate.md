# The C64 Ultimate, as a second reading

Everything this project believes about the C64 came out of VICE. The
automapper's addresses, the character record offsets, the trainer tables, the
ECL decoding: one emulator's account of the machine, never checked against the
machine. The C64 Ultimate on Donald's desk is an FPGA recreation rather than an
emulator, so a reading taken off it is genuinely independent — which is the
whole reason it is worth the trouble.

`tools/c64u.py` is the wrapper. `#240 (Drive Pool of Radiance on the C64
Ultimate, so a VICE reading can be checked against hardware)` is the work.

## When to reach for it, and when not to

For most of this project's work VICE is strictly better and the Ultimate adds
nothing. VICE's binary monitor gives breakpoints, watchpoints, single-step,
execute-until-return and CPU history; the Ultimate has none of those over its
REST API, only DMA memory reads and writes. Finding which routine writes a
byte, reading a table out of an overlay, tracing what the engine decides — VICE
answers those faithfully, and sixteen VICE slots run unattended in parallel
where the Ultimate is one physical machine Donald is often using himself.

Four things are genuinely the hardware's. These are arguments from how the
machine is built, not measurements this project has taken:

1. **The real 1541.** An FPGA 1541, not an emulation of one. The fastloader
   (`docs/131-fastloader.md`), copy protection, and drive timing are exactly
   where an emulator is most likely to diverge, and where nobody would notice
   if it did.
2. **A DMA read does not stop the CPU.** VICE's monitor stops and resumes it —
   `wish/ultimate.py`'s docstring records the resulting 7%-fast effect.
   Watching a value evolve under real timing is a different instrument, not a
   slower one.
3. **It is the arbiter.** Every C64 measurement this project has made came out
   of VICE. When a reading is surprising, the Ultimate is the only thing that
   can say whether the emulator was wrong.
4. **The debug stream** — a clock-cycle-accurate trace of the 6510 and the
   1541 bus together, with a disassembler, registers and watchpoints. VICE's
   monitor gives the CPU; it does not give a cycle-accurate drive-bus trace.
   For fastloader and protection work this is a capability the project does
   not otherwise have — see "What needs the Ethernet cable" below for why it
   is not currently reachable.

One thing that is **not** a use case: a state an agent cannot cheaply drive to
— a character trained at a hall, a party that actually loses a fight — is an
argument for **manual testing**, not for this machine. Donald, 2026-09-04,
correcting a proposed use case built on exactly this: *"I could do the same
thing myself in VICE. It's just an argument for manual testing."* Manual
testing is valuable on its own terms; it does not follow that it wants
different hardware than VICE already offers.

Measured, not argued: for `#240 (Drive Pool of Radiance on the C64 Ultimate,
so a VICE reading can be checked against hardware)`, Donald ran Pool of
Radiance on the Ultimate with Wish connected, and the automapper and roster
worked, with about a second between moving and the map catching up against a
500ms poll interval.

## The machine

CONFIRMED, tested from this machine on 2026-09-04 and recorded in Donald's
`~/c64u-reference.md`:

| | |
|---|---|
| Product | C64 Ultimate (Starlight Edition), NTSC |
| Firmware / FPGA / core | 3.14 / 121 / 1.47 |
| Address | `192.168.1.231`, DHCP, **over WiFi** |
| CLI | `c64u` v0.9.4 at `~/.local/bin/c64u` |
| Drives | `a` = 1541 on bus 8, enabled; `b` = 1541 on bus 9, disabled; SoftIEC on bus 11, disabled |

The device also carries a static `192.168.2.64` in both its Ethernet and WiFi
settings. It is unused because DHCP is on, and it is not the live address.

The REST API is served on port 80 by the **Web Remote Control** service, and
`c64u fs` needs **FTP File Service**. Both are set in the device's own menu,
not from the CLI.

## The behaviours that decide how a dump is read

Five behaviours, all CONFIRMED. Four are Donald's own hardware tests in
`~/c64u-reference.md`, section "Verified hardware behaviour" — measurements on
this physical machine, not documentation. The fifth is `#240 (Drive Pool of
Radiance on the C64 Ultimate, so a VICE reading can be checked against
hardware)`'s own comparison reading, 2026-09-04.

**DMA follows the CPU's current banking, so a dump cannot say which bank state
it was taken in.** Poking a routine that writes `$35` to `$01` and then stores
to `$A000` and `$E000`, and running it, makes those addresses read back as the
values stored; before it they read as BASIC and KERNAL ROM. Nothing is hidden,
but the dump carries no record of which side of that it was taken on, so the
bank state has to be written down separately at the time. `tools/c64u.py`'s
`dump()` takes `banking` as an argument and writes it into a JSON sidecar for
exactly this reason; "unknown" is the default and it is a real answer, not a
placeholder.

**`$00` and `$01` read as the RAM underneath, not the 6510 processor port.**
Both come back `00`. The port is internal to the CPU and answers only the CPU's
own accesses; a DMA cycle is a real bus cycle and hits the RAM. The consequence
is the one that matters: **banking cannot be read or set over DMA at all.**
Changing it means running code on the C64.

**VIC colour registers read back with the unused upper bits set, and VICE
agrees with the hardware there.** `$D020` returns `FE` on hardware, not `0E` —
`~/c64u-reference.md` is right about that reading, and stays right. Corrected
2026-09-04: the earlier text here went on to say this needed masking before a
VICE comparison, which was an assumption about VICE that nobody had checked.
Checked now: `$D020`-`$D02E` read `F0 F0 F9 FF F3 F4 F0 F2 F2 F2 F1 F1 F1 F7
FC` on both machines, byte for byte. No mask is needed there, and none of that
range has ever been a hardware-versus-VICE difference.

**Colour RAM is where the mask actually earns its place.** Over
`$D800`-`$DBE7`, the hardware's upper nybble read `A` on 998 bytes of 1000 and
`2` on the other two, where VICE read `0` on all 1000 — those four bits are
open bus and answer with the VIC's last bus fetch, not a fixed value. Mask with
`& 0x0F` before comparing anything in `$D800`-`$DBFF` — `c64u.mask_vic_colour()`
— or the difference found there is entirely ours.

**A DMA write persists only where nothing else drives the address.**

| Target | Result | Why |
|---|---|---|
| `$D020` border colour | sticks | nothing else writes it |
| `$0400` screen RAM | sticks | plain RAM |
| `$DC00` CIA 1 port A | gone within a frame | the KERNAL keyboard scan rewrites it sixty times a second |

"The write did nothing" almost always means something else owns that register.

**A "read-only" DMA read is not side-effect-free either.** Reading `$D01E` and
`$D01F` clears them: a first reading returned `3B` from both, a second, seconds
later, returned `00`. They are the VIC's sprite-to-sprite and
sprite-to-background collision latches, and reading them is what clears them.
Reading `$DC0B` or `$DD0B` latches the CIA time-of-day until something reads
the tenths register at `$DC08`/`$DD08`; a block read ascending through
`$DC00`-`$DC0F` reads tenths before hours and leaves the clock latched behind
it. Nothing the automapper polls touches either register — it reads `$4900`,
`$8300`, `$D011`, `$D018`, `$DD00` and the screen — so this is a caution for
anything that dumps the wider I/O page, not a defect in the live tab.

**One contradiction, resolved.** `README.md:287` in the c64u repo says DMA
writes reach "only RAM, not I/O-mapped CIA registers". That is wrong for reads
at least: three consecutive reads of `$D012` returned `E0`, `48`, `FE` — the
raster counter moving. `skills/c64u-cli/references/limits.md` is right, and
explains the observable ("writing `$DC00` appears to do nothing") by the
keyboard scan rather than by DMA not reaching I/O. Trust the skill.

## What the CLI can do, and what it is for here

| Job | Command | What it gives this project |
|---|---|---|
| Read memory | `machine read-mem <addr> --length N --raw` | a genuine DMA cycle, reaching live I/O; the second reading for any address `automap/` polls |
| Write memory | `machine write-mem <addr> <hex>` | poking a value to see what the game does with it; 128 bytes a call, hex as **one** argument |
| Hold the machine still | `machine pause` / `resume` | pulls the DMA line low, so a 64K dump is coherent rather than smeared across many HTTP round-trips |
| Run code | `runners run-prg-upload <local.prg>` | the only way to change banking, since `$01` is unreachable over DMA |
| Mount a disk | `drives mount-upload a <local.d64>` | the player's own images, uploaded from a copy under `work/` |
| Type at it | `machine sendkey '<petscii>'` | KERNAL buffer only — see below |
| Device settings | `config get` / `set` / `export` | read freely; `save-to-flash`, `load-from-flash` and `reset-to-default` are refused by `tools/c64u.py` |

**`sendkey` writes PETSCII into the KERNAL keyboard buffer at `$0277` and the
count at `$00C6`.** That is the path BASIC, `INPUT` and `GET` read from. A
program polling the keyboard *matrix* through CIA 1 (`$DC00`/`$DC01`) never
sees it, because the hardware scan overwrites the value before the program
reads. The buffer is ten bytes; longer strings are chunked and the running
program has to drain each chunk. `\stop` works only when the machine is idle.

## What needs the Ethernet cable

`c64u streams listen video|audio|debug` fails on a WiFi-only connection with
`No Operational Network Interface`. The REST API is served by the WiFi side,
but the streams are emitted by the **FPGA out of the Ethernet MAC**, and there
is no setting that routes them over WiFi ("Interface Type" in the config is a
Freeze-menu setting, unrelated to networking). CONFIRMED in
`~/c64u-reference.md`.

What is lost is the **debug stream**: a clock-cycle-accurate 6510/VIC/1541 bus
trace with a disassembler, CPU registers and watchpoints, over firmware 3.7+.
That is the most powerful analysis tool on the device and the one that would
most change what this project can do — a watchpoint on a real machine, against
`d6502`'s static reading.

**The machine stays on WiFi, deliberately.** Donald, 2026-09-04: *"The C64U is
connected via wifi. It is not connected via ethernet. I could figure that out
if we really did need it, but I don't plan to right now."* The cost of the
debug stream is one cable; it is worth asking for only when a disk-level
question actually needs it, not by default.

## The addresses hold on hardware

CONFIRMED, 2026-09-04. `tools/c64ucompare.py` read twelve regions off Donald's
idle Ultimate, party standing in The Slums, and the same twelve out of a pooled
VICE running the same save, then walked the VICE party to the hardware's own
square so the two differed in nothing but the machine. **21,776 bytes of
memory the game writes were compared, and three differ — all three the
two-minute game-clock gap the walk could not close:**

| address | Ultimate | VICE | |
|---|---|---|---|
| `$49C7` | `00` | `02` | the clock's minute units, 11:50 against 11:52 |
| `$CE47` | `30` | `32` | the same digit on the status line |
| `$49F0` | `09` | `0B` | previous square's x; the two parties arrived from opposite sides |

Everything else agrees byte for byte: the dungeon view, the party list, colour
RAM, the roster page, the live position triple at `$C000`-`$C05F`, the
`DUNGEON` overlay, and `SECSET`/`ITEMNAMES`/`ITEMS`. Two 1541s — one an FPGA
recreation, one an emulation — loaded the same overlays off the same disk
images and put the same bytes at the same addresses. This is the first
hardware reading this project has taken, and it puts hardware behind every C64
measurement made so far.

### Pinning the save and the square

The hardware's own state had to be identified before anything was compared:
its `$4900` image differs from `SAVEDGAME0` on `NEWSAVE6.D64` by 4 bytes of
7168 and its `$8300` page by 0 of 256, where every other save on the player's
disks is 72 to 1062 bytes away. `tools/c64ucompare.py vice --to 10,8,1 --clock
11:50 --move-mode` then booted that save in VICE and walked the party to the
hardware's square, `(10,8)` facing E, by reading the game's own status line —
landing two game-minutes past 11:50, which is the source of all three
remaining differences.

### `party_fix`'s three registers, on hardware

`$D011` (`1B`) and `$D018` (`35`) read identically on both machines; `$DD00`
reads `10` on hardware against `C4` on VICE and agrees in bits 0-1, which is
all `screen_address()` reads — the upper six bits are the serial bus and
differ because the two drives are in different states. `party_fix()` returned
`source="status"` on hardware, the preferred path rather than the `$49C0`
fallback. `wish/ultimate.py` still grades `party_fix` PROBABLE there; that
grade was not touched by this reading and is not this document's to fix.

### The exclusion list, measured rather than assumed

The Ultimate cannot be paused while Donald is at it, so a hardware reading
happens on a running CPU. Two readings of the same 22,591 bytes, seconds
apart, differ at exactly seven addresses:

| address | what moves |
|---|---|
| `$D012` | raster counter |
| `$D01E`, `$D01F` | sprite collision latches, cleared by the read itself |
| `$DC04`, `$DC05` | CIA 1 timer A |
| `$00A1`, `$00A2` | KERNAL jiffy clock |

A third reading seven minutes later differed from the first in one more byte,
`$00A0`, the jiffy clock's third byte — so a 22.5 KB DMA read taken over
several HTTP round trips is coherent on an idle game without pausing anything,
which is what makes a hardware reading possible at all while a player sits at
the machine. `tools/c64ucompare.py`'s `--stable` flag takes this list as known
moving parts, so a comparison against VICE never reports one of them as a
disagreement.

### One band cannot agree, and it is not evidence

`$6D20`-`$6EFF`, 480 bytes inside `SECSET`, differs in 296 — and it is memory
the game never writes in this state. VICE holds its power-on RAM pattern
there, `FF FF 00 00 00 00 FF FF FF FF 00 00 00 00 FF FF` on a sixteen-byte
period, matching 370 of the region's 480 bytes against only 15% of the rest of
the same `$6500`-`$82FF` read. The Ultimate holds stale PETSCII from earlier in
Donald's session — `PRESS BUTTON`, `DONE`, `ALL SCROLLS`. Of the 110 bytes VICE
*did* write there, 105 equal the hardware. A freshly booted emulator and a
machine that has been running for hours cannot agree about RAM neither program
has written, and a difference there is not a disagreement about the game.

### The reading is not bracketed

The Ultimate stopped answering while this comparison was being taken —
`tools/c64u.py info` exits 3, and it is still unreachable as this is written.
Three hardware readings over the ten minutes before that were identical but
for the jiffy clock, so the state was not moving, but there is no reading
afterward to prove it stayed that way. If the machine returns and the party
has not moved, re-running `tools/c64ucompare.py hw` and diffing it against
`work/c64u/240/hw-c` settles this in thirty seconds.

## Without the CLI: REST and FTP direct

`tools/c64u.py` shells out to the `c64u` binary. Wish cannot: a player who
installs Wish has no CLI, so `#272 (A Commodore 64 Ultimate tab: swap disks,
boot, and grab the save over the REST API)` needs the same jobs done from
Python's own standard library. `tools/c64urest.py` is that, and everything in
this section was measured with it on Donald's machine on 2026-09-05, firmware
3.14.

**REST does everything except retrieve a file.** The firmware's route table
has `files:info` and four image-creation routes and nothing that returns a
file's bytes, so the one job that has to come back to the PC — fetching the
save the game wrote — is **FTP**, anonymous on port 21, exactly as
`c64u fs download` does it. Four fifths of the work is HTTP on port 80 and one
fifth is FTP, and anything a person reads should say which.

### What the wire actually does

CONFIRMED, each of these measured rather than read out of the firmware source:

* **`ftplib` works untouched.** `ftplib.FTP`, `login("anonymous",
  "anonymous")`, default passive mode: the greeting is `220 C64 Ultimate FTP`,
  `LIST /` gives `SD`, `Flash` and `Temp`, and `RETR` of a mounted image
  returns all 174,848 bytes of a valid `.d64`. No dependency to install.
* **`image_path` is empty; the device path comes back in `image_file`.** After
  a `POST /v1/drives/a:mount` upload, `GET /v1/drives` answers `"image_file":
  "/Temp/temp0000", "image_path": ""` for drive `a`. Anything that reads
  `image_path` to learn where the image landed gets nothing.
* **An uploaded image is always named `temp%04x`.** Sending
  `Content-Disposition: attachment; filename="SPIKEA.D64"` alongside the
  `application/octet-stream` body does not change it. The name has to be
  remembered by whoever uploaded it.
* **A remount by path needs `type`.** `PUT
  /v1/drives/a:mount?image=/Temp/temp0000&mode=readwrite` answers `HTTP 400
  {"errors": ["Invalid Type ''"]}`, because `files:info` reports the temp
  file's `extension` as `""` and there is nothing to infer from. With
  `type=d64` it mounts.
* **`runners:run_prg` needs no reset, and costs a `/Temp` file.** A `POST`
  with the program as the body runs it from wherever the machine is — the
  screen shows the firmware performing the machine's own `LOAD` and `RUN` —
  and the program is uploaded to `/Temp` first, taking the next `temp%04x`
  name.
* **`/Temp` does not evict.** Thirty-five files, thirty-two of them full disk
  images and about 5.9 MB in total, uploaded one after another with nothing
  ever removed; the first upload was still readable at the end. The ten-file
  limit in the firmware's master branch (`kManagedTempMaxFiles`) does not
  apply on 3.14. `/Temp` is still cleared by a power cycle, which is the
  reason a save has to be fetched before the machine is switched off.

### Writes go to the device's copy, and only a remount by path brings them back

A `readwrite` mount writes to the `/Temp` copy and never to the local file.
Measured with a 79-byte program that opens `MARK1,S,W` on device 8 and writes
seven bytes:

| Step | Result |
|---|---|
| upload a blank image, run the program | the device's copy has `MARK1`; the local file does not |
| mount a different image, then `PUT ...:mount` back **by `/Temp` path**, run a second marker | the device's copy has `MARK1` **and** `MARK2` |
| mount the same **local** file again with `POST` | the new copy is byte-identical to the local file — both markers gone |

That last row is the trap in the disk-flipping workflow: swapping a save disk
out and back in by re-uploading loses everything the game wrote to it.

### The device's copy lags the drive by about ten seconds

**A file fetched too soon is wrong, and says so.** Timing a single write and
fetching the whole image repeatedly:

| Time since the program started | The new file's directory entry | Track 17's BAM entry |
|---|---|---|
| 3.5 s | not in the directory at all | unchanged |
| 6.5 s | type `$01` — an unclosed file — 0 blocks | `00 00 00 00` |
| 9.6 s onwards, to 46 s | type `$81`, 1 block | correct |

The image stayed mounted throughout, so it is time and not the eject that
settles it, and the same six-byte signature appeared in three separate runs.
The data block is present and readable in every sample; it is the directory
entry's closed flag, its block count and the BAM that arrive late.

So anything fetching a save should **check the image rather than sleep**: a
directory entry whose type byte has bit 7 clear is a file the drive has not
finished closing, `goldbox.d64` can already see it, and the answer is to fetch
again. PROBABLE, and unresolved, is which side of the FPGA/firmware line
defers those sectors.

### Booting a game without the CLI

`POST /v1/runners:run_prg` with the image's **first PRG**, read locally, boots
all three C64 titles from a `/Temp` copy with no reset first — `BOOT` on
`POOL1.D64` (1304 bytes) and `CURSE_A.D64` (1273), `SECRET BLADE/[%]` on
`SILVER-1.D64` (4138). Pool of Radiance went the whole way: `Y` to `DISABLE
FASTLOADER (Y/N) ?`, about two and a half minutes of blank screen, then the
game's frame and roster.

Two things that catch a reader out. **The screen moves**: with the game up,
`$D018` is `$35` and `$DD00` is `$C4`, which puts it at `$CC00`, so `$0400`
reads as zeros and proves nothing. Find it the way `automap.target.party_fix`
does. And **a blank screen during a load is normal** with the fastloader
disabled — the jiffy clock at `$00A0` advancing is what says the machine is
alive, and it was, all the way through the two and a half minutes.

## What is still UNKNOWN

Nothing below has been measured. Each line says what would settle it.

| Question | Grade | The experiment |
|---|---|---|
| How many `read-mem` calls a second, at the automapper's poll size | UNKNOWN | `tools/c64u.py time-reads --count 100`. One poll of Pool of Radiance is two blocks — `$4900` for `$1C00` bytes and `$8300` for `$100` — so it is two HTTP round-trips over WiFi. The number decides whether the Ultimate can back a live tab or only a stop-and-dump measurement |
| Whether Pool of Radiance can be driven from `sendkey` at the stages that are not the boot prompt | PARTLY ANSWERED | The boot's `DISABLE FASTLOADER (Y/N) ?` **can** be driven — see "Booting a game without the CLI" below, where a `Y` written to `$0277` with `01` at `$00C6` was echoed as `yes`. So that stage reads through the KERNAL's `GETIN`. The main menu, camp and the movement loop are still untried and may each answer differently: `tools/c64u.py probe-key ' '` at each, a `$00C6` returning to zero meaning the stage can be driven and a count that sits there meaning the keyboard matrix |

## Rules for working with it

* **It is one physical device on somebody's desk.** Only one agent has it at a
  time, and if Donald is playing, nobody does.
* **Never `config save-to-flash`, `config load-from-flash` or `config
  reset-to-default`.** The first persists a change past power-off; the second
  replaces the live settings wholesale; the third cannot be undone from the
  CLI. `config export > work/c64u-config-backup.json` before changing any
  setting, and leave the device on the settings it started with.
  `tools/c64u.py` refuses all three, and `machine poweroff` with them.
* **Never `c64u ui` or `c64u streams listen`** from an agent: both put a window
  on the desktop Donald is working at. Refused in the wrapper too.
* **Do not leave it paused, frozen or looping.** `machine reset` is the way out
  of a program that will not stop, and `paused()` in the wrapper resumes from a
  `finally` so a failure mid-dump cannot leave it held.
* **Success means "accepted", not "worked".** `run-prg-upload` reports success
  once the machine has been told to start. Read back a byte only that program
  could have produced — a blank screen proves nothing if it was already blank.
* **Nothing read off the machine is committed.** A dump is the game's bytes;
  it lives under `work/`, which is gitignored, and stays there.

## Reference

`~/c64u-reference.md` is Donald's own notes and the source for most of what is
graded CONFIRMED above; "The addresses hold on hardware" is `#240 (Drive Pool
of Radiance on the C64 Ultimate, so a VICE reading can be checked against
hardware)`'s own reading instead, under `work/c64u/240/`. The two Agent Skills
are `.claude/skills/c64u-cli/`
(the tool: `commands.md`, `workflows.md`, `limits.md`) and
`.claude/skills/c64-knowledge/` (the hardware: twelve quickrefs, one per
subsystem). Read one reference file, the one covering the subsystem at hand;
`examples/` is there to be built and run, not read.
