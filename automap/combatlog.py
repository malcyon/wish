"""Keeping the combat messages the game throws away.

The game prints who hit whom for how much into a sixteen-column panel on the
right of the combat screen, holds it for a delay loop, and paints over it.
Nothing saves it, and the delay is a **software loop**, so on an emulator
running faster than a 1 MHz 6510 the line is gone sooner in wall-clock time
than the player can read it. Keeping those lines is a fix, not a mirror.

No Qt in here, the same way `combat.py` has none: this folds screen text into
messages and the window paints them.

## Where the messages are

`COMBAT $2983` is the message printer, and it settles every open question:

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
$29A5  LDA $AF00,X      ; the message string, X + $39 into SPELLN00's table
$29AB  JMP $0962        ; print it
```

`$0969` is `LDA #$70 / LDX #$09 / JMP $485A`, and `LIBRARY $485A` copies four
bytes from the address in A/X to `$03F2`-`$03F5`. `COMBAT $0970` holds
`17 27 01 17`, so the combat text window is **columns 23-38, rows 1-22**, and
`$2989` moves the top to **row 10** for messages. Rows 1-9 of the same band are
the *acting combatant's* panel -- name, `HIT POINTS n`, `AC n`, weapon, read off
a live fight -- which is why the top matters and the band alone would not do.

| where | what |
|---|---|
| `$03F2` | window's left column |
| `$03F3` | one past its right column |
| `$03F4` | its top row -- **10 while a message is printing** |
| `$03F5` | one past its bottom row |
| `$03CC` | the cursor's column |
| `$03CD` | the cursor's row |
| `$49FC` | the message delay, `INIT` sets it to 2 and `CAMP` steps it |

## Whether it scrolls or overwrites

**Both, and mostly overwrites.** `$2983` clears rows 10-22 and starts again at
the top, so each new speaker wipes the panel. Within one speaker's block
`$299A` appends on the next row, and `$29BA` moves `$03F4` down to the row
below the cursor so a follow-up ("GOES DOWN", "IS KILLED") lands under what is
already there. Only when a block runs past row 22 does `LIBRARY $2D28` call
`$2CA5`, which scrolls the window up by one line.

So the four shapes a frame-to-frame change can take are: **grew** (more rows,
or more characters on the last row), **shrank** (the same rows with the bottom
ones cleared, which `$29B7` does when a follow-up's delay runs out),
**scrolled** (everything moved up one), and **replaced** (anything else). Each
gets its own rule below.

## Whether the game waits for a key

**No.** `COMBAT $28C3` reads `$49FC` and, if it is not zero, jumps to
`LIBRARY $2E1F` -- a `DEX`/`DEY` busy loop of about 325,000 cycles per unit,
so roughly a third of a second each, three of them at the default setting of 2.
Then `$29B7` clears the window. Nothing reads the keyboard in that path.

That is the whole risk: a message lives for about a second of *emulated* time
and then is gone. At the default 200 ms poll that is five frames, which is
plenty -- but it is the number to check first if messages start going missing.

## Deduplication

**Only consecutive identical frames are dropped, never identical content.**
Two "MAGNUS MISSES." in a row are both real, and the clear between them shows
up as a frame that no longer extends the last one. Where the clear itself falls
between two polls there is a second, independent edge: `$03F4` going back to 10
means `$2983` ran, which is a new block whatever the text says.

## The dice, beside what was printed

`poll` reads `$2B10` and `$A4F0`-`$A4FB` on the same burst as the screen, so
the dice cost bytes and not a round trip, and hands them to `rolls.py`. They
are kept on the frame that **starts** a block rather than at commit time,
because a block is committed when the game paints over it and by then `$2B10`
can belong to the next attack.

## What a live fight changed

Two rules here were wrong, and both turn on bytes only a running game writes —
see `docs/50-experiments.md`, "The combat log's two defects, found in a slums
fight", and `message_window` and `_shrank` below. In short: `$03F2`-`$03F5`
are the *command bar's* window a fifth of the time, and a block shrinks as
well as grows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from . import rolls
from .screen import SCREEN_COLS, SCREEN_ROWS, band, is_bitmap, screen_address

# Which overlay is running. The same gate `combat.py` uses.
MODE = 0x6E11
COMBAT = 2

#: left, one-past-right, top, one-past-bottom -- four consecutive bytes, which
#: is why `LIBRARY $485A` can set them with a four-byte copy.
WINDOW = 0x03F2
WINDOW_LEN = 4
#: column then row, in that order: `$3ECB` writes `$03CC`, `$488B` writes both.
CURSOR = 0x03CC
CURSOR_LEN = 2
#: The delay between a message and the clear that follows it, in units of about
#: a third of a second. `INIT $09AC` sets it to 2; `CAMP $0CA1`/`$0CA6` step it.
DELAY = 0x49FC

#: `COMBAT $0970`, the block `$0969` hands to `LIBRARY $485A`.
COMBAT_WINDOW = (23, 39, 1, 23)
#: `COMBAT $2989 LDA #$0A`. Rows 1-9 are the acting combatant's panel, not
#: messages.
MESSAGE_TOP = 0x0A


def plausible_window(block: bytes) -> tuple[int, int, int, int] | None:
    """The four window bytes, or None if they cannot be a window.

    `$03F2`-`$03F5` are ordinary RAM and hold whatever the last overlay left
    there. Validate before trust, the same rule `shape_from_params` follows.
    """
    if len(block) < WINDOW_LEN:
        return None
    left, right, top, bottom = block[:WINDOW_LEN]
    if not (left < right <= SCREEN_COLS and top < bottom <= 25):
        return None
    return left, right, top, bottom


def message_window(block: bytes) -> tuple[int, int, int | None, int]:
    """The region to read, and `$03F4` **only when it is ours**.

    `$03F2`-`$03F5` describe whichever window the game printed into last, and
    in a fight that is often not the message panel: the command bar sets
    `00 28 18 19` -- columns 0 to 39, row 24 -- every time it prints
    `GUARDING`, `MOVE VIEW` or `YOUR TEAMMATE IS DYING`. Believing those four
    bytes then slices whole rows 10 to 24 out of the screen, which is the
    combat map, the border and the command bar; the map is drawn in the game's
    own glyphs, so it decodes as `&'( )*+ ,-.` and lands in the log as a
    message. That is the "readable data mixed with a lot of garbage" this
    reader was reported for, and it is reproducible: 29 of 649 frames of one
    slums fight carried `00 28 18 19`, and four of them were logged.

    The columns are not in doubt -- `COMBAT $0970` is `17 27 01 17` on all
    eight disk sides -- so they are taken from `COMBAT_WINDOW` whenever the
    live bytes describe some other window, and `top` comes back as None
    because `$03F4` then belongs to that other window: reading it would put a
    false row into `_heads` and fire the restart edge on a command-bar print.
    The bottom is clamped either way, which keeps rows 23 and 24 -- the border
    and the command bar -- out of a message.
    """
    window = plausible_window(block)
    if window is None or window[:2] != COMBAT_WINDOW[:2]:
        left, right, _, bottom = COMBAT_WINDOW
        return left, right, None, bottom
    left, right, top, bottom = window
    if top < MESSAGE_TOP:
        # `$2983` sets the top to 10 and `$29BA` only ever moves it down, so a
        # top above row 10 is the whole text window -- `$0970`'s own `01` --
        # which the game restores when it repaints the party panel at the end
        # of a turn. Read as a message top it looks like `$2983` ran and fires
        # the restart edge, which logged the last message of a turn twice.
        top = None
    return left, right, top, min(bottom, COMBAT_WINDOW[3])


@dataclass(frozen=True)
class Message:
    """One block of the message panel, as it stood when it was painted over.

    `lines` is exactly what the rows held. `text` is those rows joined -- with
    no space where the row before it filled the window, because `LIBRARY $2D28`
    wraps on the character and not on the word, so a full row is a word cut in
    half rather than a line that ended.

    The parsed fields are **best effort and optional**. A line that will not
    parse keeps `subject`, `outcome` and `damage` as None and is shown by its
    `text`, which is still far better than what the game gives you.
    """

    lines: tuple[str, ...]
    text: str
    round: int | None = None
    subject: str | None = None
    outcome: str | None = None
    damage: int | None = None
    #: The dice as they stood when this block was first seen, or None. Only
    #: the first message of a block carries one -- a follow-up like "ORC GOES
    #: DOWN" is not an attack and has no roll of its own. See `rolls.py`.
    roll: "rolls.Roll | None" = None

    def __str__(self) -> str:
        return self.text


# The game's own vocabulary, from the string table `SPELLN00` loads at $AF00.
# Only the phrases that carry an outcome are listed: everything else falls
# through to a verbatim line, which is the rule.
_OUTCOMES = (
    ("AND MISSES", "miss"),
    ("AND HITS FOR", "hit"),
    ("IS HIT FOR", "hit"),
    ("AND IS DYING", "dying"),
    ("GOES DOWN", "down"),
    ("IS KILLED", "killed"),
    ("IS UNAFFECTED", "unaffected"),
    ("AVOIDS IT", "avoided"),
    ("SAVES", "saved"),
    ("ATTACKS", "attack"),
    ("CASTS A SPELL", "casts"),
    ("BEGINS CASTING", "casting"),
)

#: "AND HITS FOR 5 POINTS OF DAMAGE" -- `$2F29` prints the number between two
#: strings, so the digits are the only part that is not from the table.
_DAMAGE = re.compile(r"\bFOR +(\d+) +POINTS? +OF +DAMAGE")


def parse(text: str) -> tuple[str | None, str | None, int | None]:
    """Subject, outcome and damage, where the line says them.

    One block names one combatant -- the attacker in "X ATTACKS AND HITS FOR
    5", the target in "Y IS HIT FOR 5". Pairing the two is a later job and
    would be invention here.
    """
    hit = None
    for phrase, outcome in _OUTCOMES:
        at = text.find(phrase)
        if at >= 0 and (hit is None or at < hit[0]):
            hit = (at, outcome)
    if hit is None:
        return None, None, None
    at, outcome = hit
    subject = text[:at].strip() or None
    damage = _DAMAGE.search(text)
    return subject, outcome, int(damage.group(1)) if damage else None


#: Columns in the combat message window: `$0970` gives 23 to 38 inclusive.
WIDTH = COMBAT_WINDOW[1] - COMBAT_WINDOW[0]


def message(lines, round_no: int | None = None, width: int = WIDTH,
            roll: "rolls.Roll | None" = None) -> Message:
    """A `Message` from the rows of one block."""
    lines = tuple(lines)
    text = _join(lines, width)
    subject, outcome, damage = parse(text)
    return Message(lines=lines, text=text, round=round_no, subject=subject,
                   outcome=outcome, damage=damage, roll=roll)


def _join(lines: tuple[str, ...], width: int = WIDTH) -> str:
    """The rows as one sentence.

    A row that reached the window's right edge was cut mid-word by `$2D28`,
    which wraps on the character and not on the word, so it joins to the next
    with nothing between; a shorter row ended in a carriage return and joins
    with a space.
    """
    out = ""
    for i, line in enumerate(lines):
        if not out:
            out = line
        elif len(lines[i - 1]) >= width:
            out += line
        else:
            out += " " + line
    return out.strip()


def _rows(lines) -> tuple[str, ...]:
    """Right-strip every row and drop the blank ones off the end."""
    out = [line.rstrip() for line in lines]
    while out and not out[-1]:
        out.pop()
    return tuple(out)


def _extends(old: tuple[str, ...], new: tuple[str, ...]) -> bool:
    """Is `new` the same block with more printed into it?

    More rows, or more characters on the row the cursor was sitting on. Both
    happen between two polls of one block: `$299A` adds a row, and `$2F29`
    prints a number onto the row that is already there.
    """
    if not old:
        return True
    if len(new) < len(old):
        return False
    if list(new[:len(old) - 1]) != list(old[:-1]):
        return False
    return new[len(old) - 1].startswith(old[-1])


def _shrank(old: tuple[str, ...], new: tuple[str, ...]) -> bool:
    """Is `new` the same block with its bottom rows cleared?

    `$29BA` puts a follow-up under what is already showing and `$29B7` clears
    from that follow-up's own top when its delay runs out, so an eight-row
    block can go back to being the five rows it grew from. Without this rule
    that shorter frame is "anything else" -- the block is committed, the
    residue becomes the new pending block, and the next clear commits its first
    message a **second** time. Seen four times in one slums fight: every
    "X ATTACKS AND HITS FOR n" that killed something was logged twice.
    """
    return bool(old) and len(new) < len(old) and list(old[:len(new)]) == list(new)


def _scrolled(old: tuple[str, ...], new: tuple[str, ...], height: int) -> bool:
    """Did the window scroll up by one line?

    `$2D28` calls `$2CA5` when a block runs past the bottom row, so the whole
    window moves up and one row arrives at the bottom. Only checked when the
    window was full, so a block that merely happens to repeat a row is not
    mistaken for one.
    """
    return (len(old) >= height and len(new) == len(old)
            and list(new[:-1]) == list(old[1:]))


class CombatLog:
    """Frames of the message panel, folded into messages.

    `poll` is one burst per tick, so the cost is one `resume` -- about 14.3 ms
    of extra emulated time under VICE, on top of the two bursts the combat view
    already spends. Whether that is affordable is the one thing here that has
    to be measured on a live machine rather than reasoned about.
    """

    #: Kept messages. A long fight is a few hundred lines; past this the oldest
    #: go, the same bargain `MessagesPanel` makes.
    LIMIT = 1000

    def __init__(self, limit: int | None = None):
        self.messages: list[Message] = []
        self.limit = self.LIMIT if limit is None else limit
        self.round: int | None = None
        #: Where the screen was last time. Held so the whole poll is one burst:
        #: the region's address depends on `$D018`/`$DD00`, which are read in
        #: the same burst, so a frame read at a stale address is thrown away
        #: rather than logged. The screen moves once per overlay, so that costs
        #: at most one frame a fight.
        self._address: int | None = None
        self._pending: tuple[str, ...] = ()
        self._last: tuple[str, ...] | None = None
        self._last_top: int | None = None
        self._heads: set[int] = set()
        #: The dice read on the poll that first showed the block now building,
        #: held until it is committed. Read then rather than at commit time
        #: because a block is committed when the game paints over it, by which
        #: point `$2B10` may belong to the *next* attack.
        self._roll: rolls.Roll | None = None
        self._watch = rolls.RollWatch()
        self._height = COMBAT_WINDOW[3] - MESSAGE_TOP
        self._width = WIDTH
        self._round_over = True

    # -- folding frames into messages -------------------------------------

    def observe(self, rows, top: int | None = None,
                roll: "rolls.Roll | None" = None) -> list[Message]:
        """One frame of the message panel. Returns whatever it completed.

        `top` is `$03F4`, which `$2983` sets to 10 for a fresh block and
        `$29BA` moves down for a follow-up. It is the second edge: a block
        that is textually identical to the one before it is still a new block
        if `$03F4` went back up.

        `roll` is the dice as this frame read them, and is kept only where this
        frame starts a block -- see `_roll`.
        """
        frame = _rows(rows)
        restarted = (top is not None and self._last_top is not None
                     and top < self._last_top)
        if top is not None and top >= MESSAGE_TOP:
            self._heads.add(top)
        if top is not None:
            self._last_top = top
        if frame == self._last and not restarted:
            return []                   # the same frame twice is one message
        self._last = frame
        done: list[Message] = []
        if not frame:
            done += self._commit()
            self._heads.clear()
            return done
        fresh = not self._pending
        if restarted:
            done += self._commit()
            self._heads = {top} if top is not None else set()
            fresh = True
        elif _shrank(self._pending, frame):
            return done                 # a partial clear, not a new block
        elif _scrolled(self._pending, frame, self._height):
            self._pending = self._pending + (frame[-1],)
            return done
        elif not _extends(self._pending, frame):
            done += self._commit()
            self._heads = {top} if top is not None else set()
            fresh = True
        self._pending = frame
        if fresh:
            self._roll = (None if roll is None
                          else replace(roll, missed=self._watch.take()))
        return done

    def flush(self) -> list[Message]:
        """Commit whatever is on screen. Called when the fight ends.

        The last message of a fight is never painted over -- `COMBAT` returns
        to `LINKER` with it still up -- so without this it would be the one
        message the log lost.
        """
        done = self._commit()
        self._last = None
        self._last_top = None
        self._heads.clear()
        return done

    def _commit(self) -> list[Message]:
        block, self._pending = self._pending, ()
        if not block:
            return []
        # The roll goes on the first part only: `$29BA`'s follow-ups are
        # not attacks and have no dice of their own.
        done = [message(part, self.round, self._width,
                        self._roll if i == 0 else None)
                for i, part in enumerate(self._split(block))]
        self._roll = None
        self.messages.extend(done)
        while len(self.messages) > self.limit:
            self.messages.pop(0)
        return done

    def _split(self, block: tuple[str, ...]) -> list[tuple[str, ...]]:
        """One block into one message per speaker.

        `$29BA` appends a follow-up under what is already showing by moving
        `$03F4` to the row below the cursor, so one frame can hold "ORC GOES
        DOWN" under "MAGNUS ATTACKS AND HITS FOR 5". Every value `$03F4` took
        while this block was building is where a name was printed, so the
        splits are read rather than guessed. With none seen the block stays
        whole, which is the honest answer.
        """
        cuts = sorted(r - MESSAGE_TOP for r in self._heads
                      if MESSAGE_TOP < r < MESSAGE_TOP + len(block))
        parts, start = [], 0
        for cut in cuts + [len(block)]:
            if cut > start:
                parts.append(block[start:cut])
            start = cut
        return parts or [block]

    # -- reading a live machine -------------------------------------------

    def poll(self, target) -> list[Message]:
        """Read one frame off a live target. One burst.

        Returns the messages this frame completed -- usually none, because a
        message is only complete once the game has painted over it.
        """
        if target is None:
            return []
        if self._address is None:
            self._address = self._locate(target)
            return []
        blocks = ((0xD011, 1), (0xD018, 1), (0xDD00, 1), (MODE, 1),
                  (WINDOW, WINDOW_LEN), (CURSOR, CURSOR_LEN),
                  # Row 10 to the bottom of the screen, always: the window's
                  # own height is in the same burst and so is not known yet,
                  # and 200 spare bytes cost nothing when the price is the
                  # round trip.
                  (self._address + MESSAGE_TOP * SCREEN_COLS,
                   (SCREEN_ROWS - MESSAGE_TOP) * SCREEN_COLS),
                  # The dice, on the same burst. `docs/147-combat-rolls.md`:
                  # the cost of a read is the round trip and not the bytes, and
                  # the battle roster comes whole because the block wanted is
                  # named by `$A4F4`, which arrives in this same burst.
                  (rolls.D20, 1), (rolls.ATTACK, rolls.ATTACK_LEN),
                  (rolls.ROSTER, rolls.ROSTER_LEN))
        (d011, d018, dd00, mode, win, _cursor, codes,
         d20, attack, roster) = _burst(target, blocks)
        if not mode or mode[0] != COMBAT:
            return self.flush()
        if d011 and d011[0] & 0x20:
            return []                   # a bitmap screen has no text to read
        here = ((~dd00[0] & 3) * 0x4000) + ((d018[0] >> 4) & 0xF) * 0x400
        if here != self._address:
            self._address = here        # the screen moved; this frame is stale
            return []
        left, right, top, bottom = message_window(win)
        self._height = max(1, bottom - MESSAGE_TOP)
        self._width = right - left
        roll = rolls.read(d20, attack, roster)
        self._watch.update(roll)
        return self.observe(band(codes, left, right)[:self._height], top, roll)

    def _locate(self, target) -> int | None:
        """Where the screen is, as its own burst. Once, on the first poll."""
        read = getattr(target, "read", None)
        if read is None:
            return None
        if is_bitmap(read):
            return None
        return screen_address(read)

    # -- rounds ------------------------------------------------------------

    def note_round(self, initiative: bytes) -> None:
        """`$A380` reaching all-zero ends a round; the next non-zero starts one.

        Optional: with nothing passed the messages carry `round=None` and are
        still in order, which is most of what a round tag gives you.
        """
        if not any(initiative):
            self._round_over = True
            return
        if self._round_over:
            self.round = 1 if self.round is None else self.round + 1
            self._round_over = False


def _burst(target, blocks) -> list[bytes]:
    """One burst where the backend can do that; see `live.read_blocks`."""
    take = getattr(target, "read_blocks", None)
    if take is not None:
        return list(take(blocks))
    return [target.read(addr, length) for addr, length in blocks]
