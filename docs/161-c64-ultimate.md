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

## The four behaviours that decide how a dump is read

All four are CONFIRMED. The evidence in each case is Donald's own hardware test
in `~/c64u-reference.md`, section "Verified hardware behaviour" — measurements
on this physical machine, not documentation.

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

**VIC colour registers read back with the unused upper bits set.** `$D020`
returns `FE`, not `0E`. The colour registers and colour RAM `$D800-$DBE7` are
four bits wide and the top four float high. Mask with `& 0x0F` before comparing
anything against a VICE reading — `c64u.mask_vic_colour()` — or the difference
found is entirely ours.

**A DMA write persists only where nothing else drives the address.**

| Target | Result | Why |
|---|---|---|
| `$D020` border colour | sticks | nothing else writes it |
| `$0400` screen RAM | sticks | plain RAM |
| `$DC00` CIA 1 port A | gone within a frame | the KERNAL keyboard scan rewrites it sixty times a second |

"The write did nothing" almost always means something else owns that register.

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

## What is still UNKNOWN

Nothing below has been measured. Each line says what would settle it.

| Question | Grade | The experiment |
|---|---|---|
| How many `read-mem` calls a second, at the automapper's poll size | UNKNOWN | `tools/c64u.py time-reads --count 100`. One poll of Pool of Radiance is two blocks — `$4900` for `$1C00` bytes and `$8300` for `$100` — so it is two HTTP round-trips over WiFi. The number decides whether the Ultimate can back a live tab or only a stop-and-dump measurement |
| Whether Pool of Radiance can be driven from `sendkey` | UNKNOWN | `tools/c64u.py probe-key ' '` at each stage: title screen, main menu, camp, the movement loop. `$00C6` returning to zero means something called the KERNAL's `GETIN` and the stage can be driven; a count that sits there means the matrix, and the answer is that the Ultimate can be read but not driven. It may differ between stages, so all four have to be tried |
| Whether the addresses this project reads hold on hardware | UNKNOWN | Boot the same disk on both, reach the same point, and compare `poll` against the VICE binary monitor's read of the same two ranges. **Disagreement is the finding that justifies the exercise; agreement is the hardware behind every C64 measurement made so far** |
| Whether the game boots at all from `drives mount-upload` | UNKNOWN | It should — a 1541 on bus 8 with the player's own image — but the fastloader and the copy protection are the two things that could differ from VICE, and neither has been tried |

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

`~/c64u-reference.md` is Donald's own notes and the source for everything
graded CONFIRMED above. The two Agent Skills are `.claude/skills/c64u-cli/`
(the tool: `commands.md`, `workflows.md`, `limits.md`) and
`.claude/skills/c64-knowledge/` (the hardware: twelve quickrefs, one per
subsystem). Read one reference file, the one covering the subsystem at hand;
`examples/` is there to be built and run, not read.
