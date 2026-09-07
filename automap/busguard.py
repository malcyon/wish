"""Decline to read a C64 Ultimate while its drive is mid-transfer.

**This is a workaround for somebody else's fault, and it does not end it.**
Every `readmem` over the Ultimate's interface stops the 6510 -- about 42 us
plus 1.1 us a byte, measured -- and a stop that lands inside a disk load
breaks the transfer beyond recovery: the KERNAL's serial receive is an
unbounded wait with interrupts off, so the machine hangs and only a reset
brings it back. Donald hits it in five or six minutes of play with the
automapper following along; an untouched machine ran forty without trouble.
`#375 (Wish has to work around the Ultimate freezing the C64 mid-load, which
hangs the game while the automapper follows along)` has the evidence and
`docs/197-duplicating-the-c64u-hang.md` the reproduction. Only the firmware
knows when its own 1541 is on the bus, so only the firmware can close the
window; what Wish can do is trigger it less often.

**What the guard does.** Before a tick, one byte: `$DD00`, CIA 2 port A, the
C64's own view of the serial bus. If the bus is mid-conversation the rest of
the tick -- four reads at rest, twelve on a roster tick -- is not taken. The
guard read is itself a read, so it is not free; it is short (one byte, ~42 us
frozen, less than one serial bit of 60-70 us) and it replaces four to twelve
longer ones exactly when they are dangerous.

**What it cannot do.** It races: a load that starts between the guard read
and the reads after it is still hit, and a bus that happens to be between
bytes reads as released. On the measured hazard -- of order one read in a
thousand during continuous loading -- this cuts the rate and cannot reach
zero. Say that wherever a person reads about it.

**How the byte is read.** Bits 3-5 are what the C64 itself drives (ATN, CLOCK
OUT, DATA OUT); bits 6-7 are CLOCK IN and DATA IN, set when the line is
released by everybody. Bits 0-2 are the VIC bank and the RS-232 output and
say nothing about the bus, so they are masked off. A bus with nothing driven
and both lines released -- `$C0` after masking -- is idle beyond argument:
`$C4` is the commonest healthy reading on Donald's unit (162 of 373 samples
over three runs with the game up, jiffy clock at full rate the whole time).

**The trap, and why a single byte is not enough.** The game's own fastloader
rests with the C64 holding CLOCK low and the drive holding DATA low -- three
hardware readings ten minutes apart on 2026-09-04, party idle in the Slums,
all `$10`. That is the KERNAL's between-bytes state too, so no rule on one
byte can tell "resting with the drive code loaded" from "mid-command". A guard
that called `$10` busy would never tick again for a player with the fastloader
on. So a busy-looking value that **holds still** for `SETTLE` consecutive
guard reads is treated as a resting state: a transfer moves through seven bus
states in milliseconds (565 changes in 1792 samples over one 40-second load),
and the same reading three times over a second and a half is not one. The
cost is `SETTLE` ticks of delay after a load that ends in such a state; the
gain is that no rest state, measured or not, can freeze the map.

The backend opts in with one attribute, `halts_on_read = True`, on its
target. `ViceTarget` never sets it: VICE stops the machine to read anyway and
the serial bus is emulated with the CPU, so there is nothing to protect.
"""

from __future__ import annotations

import logging

_log = logging.getLogger("wish.automap.busguard")

#: CIA 2 port A: VIC bank, RS-232 TXD, and the serial bus.
CIA2_PORT_A = 0xDD00

#: The bus bits: ATN OUT, CLOCK OUT, DATA OUT, CLOCK IN, DATA IN.
BUS_MASK = 0xF8

#: Nothing driven by the C64, both lines read released. `$C4`/`$C7` in the
#: samples; the state a KERNAL load leaves behind.
BUS_RELEASED = 0xC0

#: The attribute a target sets when each of its reads stops the processor.
HALTS_ON_READ = "halts_on_read"

#: How many consecutive identical busy-looking readings count as a resting
#: state rather than a transfer. Three at the Ultimate's 500 ms tick is a
#: second and a half; a load cycles its states far faster than that. Two would
#: let about a quarter of mid-load ticks through (the chance two independent
#: samples of the seven load states agree is about 0.26 on the measured
#: distribution); three lets through about seven per cent.
SETTLE = 3

#: The largest read the automapper makes on a tick: the save payload with the
#: roster folded into its last page, 7424 bytes on every title after Pool of
#: Radiance (whose own is 7168 plus a 256-byte roster page). Read size does
#: not order the hazard on the evidence -- 64 KB survived 225 reads and 32 KB
#: hung -- so this is hygiene rather than a fix, and a test holds every tick
#: read under it rather than any code splitting a bigger one, since splitting
#: would mean more requests and the hazard looks per request.
READ_CEILING = 0x1D00


def bus_released(dd00: int) -> bool:
    """Is the serial bus idle beyond argument on this reading of `$DD00`?"""
    return (dd00 & BUS_MASK) == BUS_RELEASED


class BusGuard:
    """One `$DD00` read before a tick, and a verdict on whether to take it.

    Counters are for the debug log and the tests: `passed` ticks went ahead,
    `skipped` did not, `settled` went ahead because a busy-looking value held
    still for `SETTLE` readings.
    """

    def __init__(self, settle: int = SETTLE):
        self.settle = settle
        self.passed = 0
        self.skipped = 0
        self.settled = 0
        self._last: int | None = None
        self._same = 0
        self._was_busy = False

    def allow(self, dd00: int) -> bool:
        """The verdict on one reading. Pure, so it can be tested on a table."""
        state = dd00 & BUS_MASK
        if state == BUS_RELEASED:
            self._last, self._same = state, 0
            return self._verdict(True)
        if state == self._last:
            self._same += 1
        else:
            self._last, self._same = state, 1
        if self._same >= self.settle:
            self.settled += 1
            return self._verdict(True)
        return self._verdict(False)

    def _verdict(self, go: bool) -> bool:
        if go:
            self.passed += 1
        else:
            self.skipped += 1
        if go == self._was_busy:
            # Log the edges only: a load keeps the bus busy for seconds, and a
            # line per skipped tick would be the whole log.
            _log.debug("bus %s; %d ticks skipped so far",
                       "released" if go else "busy, tick skipped",
                       self.skipped)
            self._was_busy = not go
        return go

    def clear(self, target) -> bool:
        """Read the bus and say whether this tick may go ahead.

        True at once, with no read at all, for a target that does not stop the
        processor to answer -- `halts_on_read` unset or False. Anything the
        read raises (`NotConnected` when the device has gone) is the caller's,
        exactly as a read inside the tick would be.
        """
        if not getattr(target, HALTS_ON_READ, False):
            return True
        return self.allow(target.read(CIA2_PORT_A, 1)[0])
