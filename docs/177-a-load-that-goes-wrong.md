# A load that goes wrong on the C64 Ultimate

Pool of Radiance stops on Donald's Commodore 64 Ultimate. Sometimes it freezes
with a clean screen; sometimes the screen fills with meaningless characters and
the game is gone. `#286 (Pool of Radiance on the C64 Ultimate sometimes hangs on
a disk load)` is the ticket. This document is what has been measured, what it
rules out, and what it does not.

**Nothing here says whose fault it is.** Four candidates are live and this work
eliminated none of them: the game's own code, the Ultimate's firmware, its 1541
emulation, and the particular unit on Donald's desk. Donald, 2026-09-05:
*"Remember that the cause could be anything. The game software, the firmware,
the 1541 software, or bad hardware. It is only one machine."* A sample of one
machine cannot separate a firmware defect from a fault in that machine.

## What a player sees

Two endings, both from identical inputs.

**The hang.** The game is loading -- the screen shows whatever panel it was on,
often with `ONWARD BOUND ...` on the message line -- and it never comes back.
Nothing responds. The machine has to be reset and anything unsaved is gone.

**The crash.** The screen fills with coloured rubbish, all at once or spreading,
and the game is over. Those are not stray sector bytes: they are the game's own
map data at `$0400` being drawn as text because the VIC has gone back to bank 0.

## The reproduction, and it is cheaper than the one on the ticket

Donald's own recipe walks a party to a stable in The Slums, searches, takes the
loot and leaves the treasure screen. That works, and the square is identified
below, but it is not needed. **The opening demo does it.**

Boot `POOL1.D64`, answer `Y` to `DISABLE FASTLOADER (Y/N) ?`, and touch nothing
else. The attract loop plays the party list, the welcome text, an animated
dungeon view and the credits, and then starts again -- loading from disk
continuously, forever, unattended. On 2026-09-05 the first run stopped after
about nine minutes and the second after about ten, one each way.

    tools/c64uplay.py boot work/issue286/disks/POOL1.D64 --mode readonly
    tools/c64uplay.py keys Y --wait
    tools/c64uplay.py hangwatch --log work/x.jsonl --capture work/x-hang

`hangwatch` takes the memory regions itself the moment the machine stops, which
matters because the failure is intermittent and unattended.

## Telling a hang from a load

**A stopped jiffy clock is not a hang.** The KERNAL's serial routines run with
interrupts off, so `$00A0`-`$00A2` stops for the length of every load; an
earlier reading on this issue watched it stop for two and a half minutes during
a boot that was perfectly healthy.

What separates them, measured on this machine on 2026-09-05:

| | healthy | hung |
|---|---|---|
| longest stretch with neither the screen nor the jiffy clock moving | **2 samples, about 6 seconds** (164 samples of a running demo) | 80 s and counting, 20 samples |
| `$0000`-`$01FF` | changes constantly | one sha256 for every sample |
| 40 KB across `$0200`-`$07FF`, `$2000`-`$3FFF`, `$8000`-`$9FFF`, `$C000`-`$C3FF` | | one sha256, 8 samples over 45 s |
| `$DC0D` CIA 1 interrupt latch | serviced | `$91` -- bit 7 set, asserted and **never acknowledged** |
| `$D01A` | | `$F0`, every VIC interrupt source disabled |

An interrupt standing unacknowledged with everything else frozen is a processor
inside an `SEI` region that will not leave it. Six seconds of legitimate quiet
against eighty of silence is what makes a 45-second threshold safe.

`$D012` keeps moving throughout and proves nothing: the VIC runs whatever the
processor does.

## The serial bus at the moment it stops

`$DD00` is the C64's own view of the serial bus. Three readings on one machine
on one afternoon:

| state | samples | distinct values | reading |
|---|---|---|---|
| BASIC ready, disk mounted, bus idle | 5 | 1 | `$97` |
| a load that completes | 1792 in 40 s | 9 | `$4F` 762, `$27` 382, `$87` 287, `$C7` 171, `$47` 103, `$07` 63, `$67` 21, `$9F` 2, `$1F` 1 -- **565 consecutive changes** |
| hung | 20 in 80 s | 1 | `$C4` |

**`$C4` is not a strange value.** It is the commonest single reading in a
healthy run -- 76 of 164 samples of a working demo. Bits 3, 4 and 5 are zero, so
the C64 is driving nothing at all; bits 6 and 7 are both set. CONFIRMED: the
serial bus froze in a state the protocol passes through normally, rather than in
an illegal one. Which side stopped first is **not** determined, and the polarity
of bits 6 and 7 is not worth arguing from a single machine.

## What was not damaged

Both hangs in evidence put **no bad bytes anywhere anybody has looked.**

* Donald's `ONWARD BOUND` capture holds the resident `DUNGEON` overlay, and all
  6144 bytes captured are byte-for-byte the file on all eight `POOL*.D64`. The
  file is 9088 bytes and the last 2944 are unmeasured.
* The 2026-09-05 hang holds `$C000`-`$C3FF` byte-for-byte equal to `GDRIVE00` as
  it ships, 1024 of 1024.
* Zero page, the stack page, the screen and colour RAM carry nothing resembling
  stray sector data in either.

So neither hang is a transfer that delivered the wrong bytes. It is a machine
waiting. **The artifacts-then-crash Donald saw at a treasure screen still has no
capture behind it**, and the crash that was captured turned out to be the game's
own data made visible rather than corruption -- see below.

## The crash, when it was caught

Run 2 ended in BASIC, not in a freeze.

| reading | value | what it says |
|---|---|---|
| `$0314`/`$0315` | `31 EA` | the KERNAL's own IRQ handler, not the game's |
| `$D018` | `$15` | screen `$0400`, character ROM -- the KERNAL default |
| `$DD00` | `$97` | VIC bank 0 -- the KERNAL default |
| `$0288` | `$CC` | the screen page pointer is **still the game's** |
| `$CC00` read as text | `READY.` | BASIC printed its prompt into the game's old buffer |
| jiffy clock | advancing | the processor is running |

The jiffy clock had not restarted, so **no reset happened**: the game fell out to
a BASIC warm start on its own. `$0314` restored while `$0288` was not is the
signature of something that ran `RESTOR` without running the screen init.
**Which KERNAL path it took is not determined** -- the Ultimate's REST API has
no route returning processor registers (`machine:state`, `machine:registers` and
`machine` all answer 404) and the cycle-accurate debug stream needs the Ethernet
cable this machine does not have (`docs/161-c64-ultimate.md`).

The visible rubbish is the game's own data at `$0400`, where `GEO` and `SQRPACI`
load, drawn as characters. Its first 32 bytes appear nowhere in `POOL1.D64`, so
it is not a disk block landing in the wrong place.

## Reading a stopped machine

Three things make a capture worth taking, and all three are in
`tools/c64uplay.py`'s region list.

**The loaded-files cache at `$6E13` says where the game was.**
`docs/140-loaded-files-cache.md` has the twenty-five slots; bit 7 of a slot is a
reload marker. A stopped machine with several slots marked is one that stopped
part-way through a batch.

| slot | Donald's `ONWARD BOUND` hang | 2026-09-05 hang | 2026-09-05 crash |
|---|---|---|---|
| 2, `GEO` | `GEO14` | `GEO12` | `GEO12` |
| 8, `ECL` | `ECL14` | `ECL64` | `ECL1E` |
| 3, `SECSET` | `SECSET02` | `SECSET64` | `SECSET64` |
| 0, `GDRIVE` | `GDRIVE01` | `GDRIVE00` | `GDRIVE00` |
| slots marked for reload | 9 | 7 | 13 |

`GEO14`/`ECL14` is The Slums, which puts Donald's capture exactly where his
report says it was. The other two are the `64` and `1E` families of the opening
demo. **Three stops, three different places in the game, one machine.**

**`$6B00` is the character-record buffer**, and the disks prove it rather than
implying it: `POOL1.D64` carries a file named `\x01BRUTUS` whose PRG load address
is `$6B00` and whose length is 580 bytes, the record size.

**`runners:run_prg` leaves the firmware's boot stub in the stack page.** At
`$0150`-`$0186` of a machine booted that way:

    A9 40 8D FF DF 58 A9 54 8D FE DF A9 00 85 02 20 33 A5 20 59 A6 4C AE A7

`LDA #$40 / STA $DFFF / CLI / LDA #$54 / STA $DFFE / LDA #$00 / STA $02 /
JSR $A533 / JSR $A659 / JMP $A7AE` -- the cartridge command registers, then
BASIC's relink, CLR and interpreter loop -- followed by the ASCII string
`/TEMP/TEMP0001`, the device path of the uploaded PRG. PROBABLE that it is
inert: it runs once, at boot, and the game overwrites it the moment its own
stack nests about forty calls deep. It is written down because 55 bytes of
firmware in page 1 of a game's memory costs the next reader twenty minutes.

## Finding the stable from the game's data

Donald's recipe names a walkthrough pin on a map picture. The square can be had
from the disks instead, and the chain is worth keeping because it generalises.

1. **The treasure identifies the file.** The two items are a Short Bow +1 and
   Arrows +1. `ITEMFILE29` on `POOL2.D64` holds exactly two records: `ARROW(S)
   +1` with quantity `$14` at `+10`, and `SHORT BOW +1`. (The walkthrough says
   ten arrows; the file says twenty.)
2. **The file identifies the statements.** `TREASURE`'s last operand is the item
   file: `41` = `$29` = `ITEMFILE29`, and where bit 7 is set the low seven bits
   are the number, so `129` is `ITEMFILE01`. `255` means no items. Every value in
   `ECL14`'s seven `TREASURE` statements resolves to a file on the disks.
   `ITEMFILE29` is named twice, at `$A4AC` and `$AB2F`.
3. **The statements identify the squares.** `goldbox/geo.py` reads plane `$200`
   of a `GEO` as a per-square script id in bits 0-6; `ECL14` masks it with 127 at
   `$9987` and dispatches 21 ways at `$99C9`. `$A4AC` is inside the handler for
   id **5**, which `GEO14` puts on **(5,2) and (6,2)**; `$AB2F` is inside id 12,
   at (0,0).
4. **One of the two is gated on searching.** Id 5 begins `COMPARE [$6DCA], 1 /
   IF<> / EXIT`, prints a 36-byte message, and offers a two-option menu
   (`OP$2B [$9801], 2, "3 bytes", "2 bytes"`). Id 12 is an unconditional coin
   hoard with no menu.

**So the stable is `GEO14` (5,2) and (6,2), script id 5.** PROBABLE: the chain
holds and nothing contradicts it, but nobody has stood on the square. Ids 4 and 5
together are a 2x3 room in the north-west quarter, which agrees with Donald's
"north-west corner of the slums".

Corroboration from an unexpected direction: the character-record buffer in
Donald's hang capture holds GARRETT carrying **both** of `ITEMFILE29`'s records,
byte for byte, at `$6B60` and `$6B70`. His `ONWARD BOUND` capture was taken
minutes after collecting the treasure his reproduction describes.

## What could not be reached

**Which loop the processor sat in.** No route returns registers, the stack page
cannot localise it without the stack pointer, and DMA reads of memory will not
close it. Getting it needs either the Ethernet cable and the debug stream, or a
reproduction under an emulator where the processor can be read.

**Driving the game past the demo.** `tools/c64uplay.py probe` reports which of
two ways a stage reads the keyboard: a `$00C6` that returns to zero is the
KERNAL's buffer and can be driven from here, a count that sits there is CIA 1's
matrix and cannot. `DISABLE FASTLOADER (Y/N) ?` is the first; **the attract loop
is the second**, so an agent with only the REST API cannot press a key to reach
the main menu, and Donald's own recipe cannot be driven this way at all.

## The tools

| tool | what it does here |
|---|---|
| `tools/c64uplay.py` | boots, answers a prompt, tells a KERNAL stage from a matrix stage, watches until the machine stops and captures ten regions when it does |
| `tools/c64urest.py` | the transport underneath it -- REST for the machine, FTP for a file |
| `tools/porattract.py` | the same attract loop under a pooled VICE, sampling the **program counter**, which is the control the hardware cannot provide |
