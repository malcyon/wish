# Draft: a report to the 1541ultimate project on `readmem` during a disk load

**Not yet sent.** This is the text this project would post upstream, drafted
2026-09-07 for `#375 (Wish has to work around the Ultimate freezing the C64
mid-load, which hangs the game while the automapper follows along)` and
resting on `docs/197-duplicating-the-c64u-hang.md`. Donald decides whether,
where and under whose name it goes. Everything below the rule is the report;
nothing in it is ours to ask for beyond what the measurements support.

Two things a sender should fill in first: which existing thread it belongs on
(the issue body names 1541ultimate issue 710 as where REST-API features get
built; check that before citing it), and whether to attach
`tools/c64uhang.py`'s generated disk or leave the reader with the GEOS stick,
which needs nothing from us.

---

## `machine:readmem` during a serial-bus transfer hangs the C64 in the KERNAL's byte-receive loop

### Summary

A `GET /v1/machine:readmem` halts the 6510 for the length of the DMA transfer.
When that halt lands inside a serial-bus transfer, the transfer is lost and the
C64 stays in the KERNAL's `ACPTR` wait -- interrupts off, waiting on `$DD00`
for a byte that never arrives -- until it is reset. Reproduced by hand from a
written procedure on **3.14 / FPGA 121 / core 1.47** and again, unchanged, on
**1.1.0 / FPGA 122 / core 1.49**, on one C64 Ultimate (`unique_id 5D0060`),
over WiFi. No game is involved: three lines of BASIC reading a file from the
GEOS disk on the USB stick that ships with the machine, plus a `curl` loop.

The ask is a `readmem` (and `writemem`) that does not halt the CPU while the
internal 1541 is in a transfer -- waiting for an idle bus, or answering "busy"
so the client can retry. Only the firmware knows when its own drive is on the
wire; a client reading `$DD00` to guess is a race (we do it anyway, and it
reduces the rate rather than ending it).

### Reproduction, with nothing but the machine and `curl`

Substitute your device's address.

1. Insert the USB stick that came with the machine and mount its GEOS disk
   read-only:

   ```sh
   curl -s -X PUT "http://$HOST/v1/drives/a:mount?image=/USB1/GEOS%20Boot%20Disk.d64&type=d64&mode=readonly"
   ```

2. At the C64's `READY.` prompt, type (or send with your keyboard tool):

   ```basic
   10 OPEN2,8,2,"DESK TOP,P,R"
   20 GET#2,A$:IF ST=0 THEN 20
   30 CLOSE2:GOTO 10
   RUN
   ```

   This reads `desk top.cvt` -- the largest file on the disk, about 30 KB --
   a byte at a time for ever, and throws every byte away. Nothing is written
   and nothing is loaded into memory; it only keeps the KERNAL's plainest
   serial read (`ACPTR`, `$EE13`) running.

3. From another machine, read memory in a loop:

   ```sh
   while true; do
     curl -s -o /dev/null "http://$HOST/v1/machine:readmem?address=0400&length=32768"
     sleep 0.5
   done
   ```

4. Watch the KERNAL jiffy clock, three bytes at `$00A0`, which advances only
   while interrupts are serviced:

   ```sh
   while true; do
     curl -s "http://$HOST/v1/machine:readmem?address=00A0&length=3" | xxd -p
     sleep 5
   done
   ```

   While the program runs the value climbs at a fraction of real time (the
   KERNAL has interrupts off while it talks to the drive). **When it holds
   one value across several readings ten seconds or more apart, the C64 is
   hung.** A single frozen reading proves nothing -- a normal load also stops
   this clock for seconds -- so wait for it to stay put.

Expect to wait. The hazard is roughly one read in a thousand, so at one read
every half-second it is about a 70 % chance in ten minutes and 97 % in thirty.
By hand it took rather under an hour each time; our driven runs took 5.6 and
23 minutes.

### What the hung machine looks like

Taken over `readmem` after the clock stopped, on both firmware versions:

| | 3.14 / 121 / 1.47 | 1.1.0 / 122 / 1.49 |
|---|---|---|
| jiffy `$00A0-$00A2` | `00b90b`, frozen across 45 s | `006e76`, frozen across 45 s |
| `$DD00` (CIA 2 PRA) | `$67` on six consecutive samples | `$67` on six consecutive samples |
| `$DC0D` (CIA 1 ICR) | `$81` -- an interrupt latched and never serviced | `$81` |
| `$0314/$0315` | `$EA31`, the KERNAL's own IRQ vector | `$EA31` |
| screen | intact, no corruption | intact |

So the processor is inside an `SEI` region it never leaves, and nothing has
been written anywhere: the drive code, the screen and the loaded data are
byte-perfect in every capture. It is a machine waiting, not a machine fed bad
bytes.

In the driven reproduction (a one-line BASIC `LOAD` loop on a generated disk)
the top of the stack resolves to a clean nested call chain -- BASIC's `LOAD`
(`$E175 jsr $FFD5`) into the KERNAL load (`$F501 jsr $EE13`, `ACPTR`) into the
serial receive (`$EE37 jsr $EEA9`, the "read `$DD00` until stable" loop). The
REST API cannot report the stack pointer, so the exact instruction is inferred;
that it is in the serial receive is not.

### Measurements

**The halt.** Timed against the jiffy clock on 3.14: about **42 µs fixed plus
1.1 µs a byte**. A 7168-byte read stops the CPU about 7.9 ms; 32 KB about
36 ms. (Whether a 64 KB read is one halt or several was not measured.) A
KERNAL serial bit is 60-70 µs wide.

**It needs the traffic.** Three forty-minute runs of the game's own attract
loop with no requests at all: no hang. With requests: one hang at 23 minutes,
and two runs cut short by the web service failing under sustained polling
(a separate matter).

**Size does not order it, on this evidence.** Every run below had the drive
working throughout (checked from `$DD00` cycling its load states, the screen
hash holding, and the jiffy rate):

| host read | CPU halt | reads while loading | outcome |
|---|---|---|---|
| 2048 B | ~2.3 ms | 210 | no hang in 7 min |
| 7168 B | ~7.9 ms | ~240 | no hang in 18 min |
| 8192 B | ~9 ms | 210 | no hang in 7 min |
| 16384 B | ~18 ms | 195 | no hang in 7 min |
| **32768 B** | ~36 ms | ~150 | **hung at 5.6 min** |
| **53248 B** | ~57 ms | 98 | **hung at 23 min** |
| 65536 B | ~72 ms | 225 | no hang in 8 min |

Two hangs in about 1,300 reads, at two sizes, with 64 KB surviving 225 reads:
the per-read hazard during continuous KERNAL loading is of order **one in a
thousand at any size tried**, and two events cannot say whether bigger is
worse. Halts of 9 and 18 ms landed some 400 times with the bus active and
did nothing, so whatever the drive-side tolerance is, it is well past the
1 ms one might expect from the EOI handshake; we do not know what it is.

### What we ask for

Any of these would end it for every client rather than for ours:

* `readmem`/`writemem` wait until the internal drive is not in a transfer
  before halting the CPU (the firmware's 1541 knows when it is on the bus;
  a bounded wait with a timeout would do);
* or the routes answer an error (409, say) while the drive is busy, so a
  client can retry;
* or a documented way to ask whether a DMA read is safe right now.

### What we do meanwhile, and why it is not enough

Our tool reads one byte of `$DD00` before each polling tick and skips the
tick when the bus is not in the released state (`bits 3-7 = 11000`). It
races -- a load starting between that byte and the next read is still hit --
and the byte is itself a halt. On the measured distribution of bus states it
cuts our requests during a load by about three quarters and cannot reach
zero. The C64 side also cannot tell a drive resting with fastloader code
loaded (`$10`: C64 holding CLOCK, drive holding DATA, for ten minutes at a
stretch) from a command in flight, which is one more reason this belongs in
the firmware.

### One machine

All of this is one unit. The fault could be this board; we have no second
Ultimate to say otherwise, and the procedure above is written so that anybody
with one can find out in an hour.
