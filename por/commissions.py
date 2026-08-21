"""The City Council's books: the reward ledger, the offer board, the summons.

Everything here reads the 224 persistent flag bytes at `$4A20`-`$4AFF`, which
live at offset `$0100` in `SAVEDGAME0` (load address `$4900`) and are the same
bytes in a running machine. No transport and no Qt, so this works from a save
file, from a live read, or from a test's own array.

Two structures in `ECL08` (the Phlan City Hall, disk 3) carry the whole state:

    $4AA6 + i, i = 0..25   the reward ledger. The area script writes 254 when
                           the job is done; the clerk pays and writes 255. 0 is
                           untouched, and a few small values are progress
                           markers an area script keeps in the same byte.
    $4AC1                  commissions completed -- bumped by the clerk for the
                           ten jobs that count as major.

The index *is* the quest: each has the clerk's own speech in the 26-entry
`ONGOSUB [$6E79], 26` table at `ECL08 $9D55`, which is where the names below
come from. Index 22's handler is a bare `RETURN`, so it has no name and is not
given one.

`offered()` re-implements the board at `ECL08 $A84D`: sixteen candidates tested
in a fixed order, each a two-instruction `COMPARE`/`IF`/`GOTO $A890` gate, at
most three offered per visit. The cap counter is `$4A05`, in the per-script
scratch page, so it resets when the party leaves.

Evidence for every line is in `work/reports/quest-flags.md`; the plan is
`docs/103-commissions-panel.md`. Nothing outside those two structures and the
named appointment flags is exposed, because nothing else in the region is
confirmed to the same standard.
"""

from __future__ import annotations

from dataclasses import dataclass

FLAGS_BASE = 0x4A20
FLAGS_END = 0x4B00
FLAGS_SIZE = FLAGS_END - FLAGS_BASE                 # 224

LEDGER_BASE = 0x4AA6
LEDGER_COUNT = 26
COMPLETED = 0x4AC1
OFFER_LIMIT = 3

# The two values the clerk's own code writes. Everything between 1 and 253 is
# an area script's private progress marker in the same byte.
DONE = 254
PAID_VALUE = 255

NOT_DONE = "not done"
IN_PROGRESS = "in progress"
REWARD_WAITING = "reward waiting"
PAID = "paid"

# name, and the script that writes 254 into it. `None` where the clerk's table
# has no speech: index 22's handler is a bare RETURN, so it is shown by index.
LEDGER = (
    ("Norris the Gray killed", "Kuto's Well (ECL1D)"),
    ("Sokal Keep cleared", "Sokal Keep (ECL15)"),
    ("area by the evil temple cleared", "Temple district (ECL18)"),
    ("Bivant heir rescued", "Buccaneer's Base (ECL01)"),
    ("library book: discourses", "Mendor's Library (ECL0F)"),
    ("library book: descriptions", "Mendor's Library (ECL0F)"),
    ("library book: maps", "Mendor's Library (ECL0F)"),
    ("library book: histories", "Mendor's Library (ECL0F)"),
    ("library book: records", "Mendor's Library (ECL0F)"),
    ("library book: of small value", "Mendor's Library (ECL0F)"),
    ("Podal Plaza auction", "Podal Plaza (ECL12)"),
    ("graveyard menace ended", "Valhingen Graveyard (ECL0A)"),
    ("Kovel Mansion thieves", "Kovel Mansion (ECL0E)"),
    ("Stojanow river pollution", "Yarash's pyramid (ECL17)"),
    ("Cadorna's diplomatic mission", "Zhentil outpost (ECL1C) / ECL19"),
    ("lizardmen stopped", "Lizardman keep (ECL10)"),
    ("kobolds stopped", "Kobold caves (ECL0D)"),
    ("nomads stopped", "Nomad camp (ECL11)"),
    ("Cadorna's textile treasure handed in", "Civilised Phlan (ECL00)"),
    ("Stojanow Gate taken", "Stojanow Gate (ECL09)"),
    ("Tyranthraxus defeated - the quest is over", "Valjevo Castle (ECL07)"),
    ("slums cleared", "The slums (ECL14)"),
    (None, None),
    ("Temple of Bane", "Temple district (ECL18)"),
    ("Cadorna exposed as a traitor", "City Hall (ECL08) / ECL04"),
    ("Cadorna killed", "Valjevo Castle (ECL03)"),
)
assert len(LEDGER) == LEDGER_COUNT

# The ten handlers that bump $4AC1.
MAJOR = frozenset({0, 1, 10, 11, 12, 13, 15, 16, 17, 21})


def ledger_name(index: int) -> str:
    """The clerk's own words, or the index where the clerk has no speech."""
    name = LEDGER[index][0]
    return name if name else f"ledger entry {index}"


# --- the flag block ---------------------------------------------------------

class Flags:
    """The 224 bytes, addressed the way the game addresses them."""

    __slots__ = ("_data",)

    def __init__(self, data: bytes):
        if len(data) != FLAGS_SIZE:
            raise ValueError(f"expected {FLAGS_SIZE} flag bytes, got {len(data)}")
        self._data = bytes(data)

    def __getitem__(self, address: int) -> int:
        return self._data[address - FLAGS_BASE]

    def ledger(self, index: int) -> int:
        return self[LEDGER_BASE + index]

    def to_bytes(self) -> bytes:
        return self._data


def flags(source) -> Flags:
    """The flag block, out of whichever container the caller happens to hold.

    Accepts a `Flags`, a `SaveGame0` (or anything with `to_bytes`), the whole
    `SAVEDGAME0` payload, the `$4A00` page a memory dump tends to come in, or
    the 224 bytes themselves. Lengths are distinct, so no flag is needed.
    """
    if isinstance(source, Flags):
        return source
    if hasattr(source, "to_bytes"):
        source = source.to_bytes()
    data = bytes(source)
    if len(data) == FLAGS_SIZE:
        return Flags(data)
    if len(data) == 0x100:                     # a $4A00 page
        return Flags(data[FLAGS_BASE - 0x4A00:])
    if len(data) >= FLAGS_END - 0x4900:        # SAVEDGAME0 from $4900
        start = FLAGS_BASE - 0x4900
        return Flags(data[start:start + FLAGS_SIZE])
    raise ValueError(f"cannot find $4A20-$4AFF in {len(data)} bytes")


# --- the ledger -------------------------------------------------------------

@dataclass(frozen=True)
class Entry:
    """One row of the reward ledger."""

    index: int
    address: int
    name: str
    source: str | None
    value: int
    major: bool

    @property
    def state(self) -> str:
        if self.value == PAID_VALUE:
            return PAID
        if self.value == DONE:
            return REWARD_WAITING
        return IN_PROGRESS if self.value else NOT_DONE

    @property
    def done(self) -> bool:
        return self.value >= DONE


def ledger(source) -> tuple[Entry, ...]:
    f = flags(source)
    return tuple(
        Entry(index=i, address=LEDGER_BASE + i, name=ledger_name(i),
              source=LEDGER[i][1], value=f.ledger(i), major=i in MAJOR)
        for i in range(LEDGER_COUNT)
    )


# --- the offer board, ECL08 $A84D -------------------------------------------

@dataclass(frozen=True)
class Offer:
    """A candidate on the board: what the clerk says, and what it settles."""

    order: int
    text: str
    ledger: tuple[int, ...]


def _gate(index, f):
    """The gates, in the board's own order and with its own comparisons.

    Kept as one function of the candidate number so each line sits beside the
    number `ECL08` tests it at. `L` is the ledger, `f[...]` a bare flag.
    """
    L = f.ledger
    if index == 0:
        return L(21) != PAID_VALUE
    if index == 1:
        return L(1) != PAID_VALUE
    if index == 2:
        return f[0x4AC2] != PAID_VALUE
    if index == 3:
        return L(10) != PAID_VALUE
    if index == 4:
        return (f[0x4A97] != PAID_VALUE and f[0x4ABE] < DONE
                and L(18) != PAID_VALUE)
    if index == 5:
        return L(1) == PAID_VALUE and f[0x4A9B] <= 253 and L(23) != PAID_VALUE
    if index == 6:
        return L(1) == PAID_VALUE and L(12) != PAID_VALUE
    if index == 7:
        return L(17) != PAID_VALUE
    if index == 8:
        return L(16) != PAID_VALUE
    if index == 9:
        return False                    # withdrawn: an unconditional GOTO $A890
    if index == 10:
        return L(13) != PAID_VALUE
    if index == 11:
        return L(15) != PAID_VALUE
    if index == 12:
        return L(1) == PAID_VALUE and L(3) == 0
    if index == 13:
        return f[0x4A98] != PAID_VALUE and (
            f[0x4ABE] >= DONE                       # the Zhentil Keep version
            or (f[0x4A97] == PAID_VALUE and L(14) != PAID_VALUE))
    if index == 14:
        return L(19) < DONE and f[0x4ABE] >= DONE
    if index == 15:
        return f[0x4A9A] < DONE and L(19) == PAID_VALUE and L(20) != PAID_VALUE
    raise IndexError(index)


BOARD = (
    Offer(0, "clear the slums", (21,)),
    Offer(1, "clear Sokal Keep", (1,)),
    Offer(2, "bring back books, maps and tomes", (4, 5, 6, 7, 8, 9)),
    Offer(3, "the Podal Plaza auction", (10,)),
    Offer(4, "see Councilman Cadorna", (18,)),
    Offer(5, "report to the Bishop of Tyr", (23,)),
    Offer(6, "clean out Kovel Mansion", (12,)),
    Offer(7, "stop the nomads", (17,)),
    Offer(8, "stop the kobolds", (16,)),
    Offer(9, "(withdrawn)", ()),
    Offer(10, "end the river's pollution", (13,)),
    Offer(11, "stop the lizardmen", (15,)),
    Offer(12, "rescue the Bivant heir", (3,)),
    Offer(13, "Cadorna's diplomatic mission", (14,)),
    Offer(14, "Lord Urslingen: take Stojanow Gate", (19,)),
    Offer(15, "the special council meeting", (20,)),
)
assert len(BOARD) == 16


def offered(source, limit: int = OFFER_LIMIT) -> tuple[Offer, ...]:
    """What the clerk would offer on the next visit, in the board's order."""
    f = flags(source)
    out = []
    for offer in BOARD:
        if _gate(offer.order, f):
            out.append(offer)
            if len(out) == limit:
                break
    return tuple(out)


# --- appointments -----------------------------------------------------------

# Two shapes share this idea. A *summons* runs 254 = go there, 255 = the
# interview has happened. A *marker* is only ever 255, and what that means
# differs per flag, so each carries its own words.
SUMMONS = "summons"
MARKER = "marker"

APPOINTMENTS = (
    (0x4A97, "Councilman Cadorna's chambers", SUMMONS, None, True),
    (0x4A98, "Cadorna's envoy mission", SUMMONS, None, True),
    (0x4A99, "Lord Urslingen, the Stojanow Gate briefing", SUMMONS, None, True),
    (0x4A9A, "the special council meeting", SUMMONS, None, True),
    (0x4A9B, "the Bishop of Tyr", SUMMONS, None, True),
    (0x4A8C, "the Bivant commission", MARKER, "live", True),
    (0x4A96, "the graveyard commission", MARKER, "accepted", True),
    (0x4AC2, "the book bounty", MARKER, "finished", False),
)


@dataclass(frozen=True)
class Appointment:
    """A place the Council has told the party to go, or a job it has handed out."""

    address: int
    name: str
    kind: str
    value: int
    state: str
    outstanding: bool


def appointments(source) -> tuple[Appointment, ...]:
    f = flags(source)
    out = []
    for address, name, kind, when_set, live_when_set in APPOINTMENTS:
        value = f[address]
        if kind == SUMMONS:
            state = ({DONE: "summoned", PAID_VALUE: "done"}
                     .get(value, "not yet"))
            outstanding = value == DONE
        else:
            state = when_set if value == PAID_VALUE else "not yet"
            outstanding = value == PAID_VALUE and live_when_set
        out.append(Appointment(address=address, name=name, kind=kind,
                               value=value, state=state,
                               outstanding=outstanding))
    return tuple(out)


# --- the whole picture ------------------------------------------------------

@dataclass(frozen=True)
class Commissions:
    """What the Council has asked for, and what it has already paid for."""

    completed: int
    ledger: tuple[Entry, ...]
    offers: tuple[Offer, ...]
    appointments: tuple[Appointment, ...]

    @property
    def reward_waiting(self) -> tuple[Entry, ...]:
        """Done, and the money is still sitting at the City Hall."""
        return tuple(e for e in self.ledger if e.value == DONE)

    @property
    def paid(self) -> tuple[Entry, ...]:
        return tuple(e for e in self.ledger if e.value == PAID_VALUE)

    @property
    def in_progress(self) -> tuple[Entry, ...]:
        """A non-zero byte below 254: an area script's own progress marker."""
        return tuple(e for e in self.ledger if 0 < e.value < DONE)

    @property
    def outstanding(self) -> tuple[Appointment, ...]:
        return tuple(a for a in self.appointments if a.outstanding)


def read(source) -> Commissions:
    """Everything, from the flag block."""
    f = flags(source)
    return Commissions(completed=f[COMPLETED], ledger=ledger(f),
                       offers=offered(f), appointments=appointments(f))


def summary_lines(source) -> list[str]:
    """The panel as text, for a terminal. Same content, no Qt."""
    state = read(source)
    lines = [f"Commissions completed: {state.completed}"]
    lines.append("Available:")
    lines += [f"  {o.text}" for o in state.offers] or ["  nothing"]
    for heading, rows in (("In progress:", state.in_progress),
                          ("Reward waiting:", state.reward_waiting),
                          ("Paid:", state.paid)):
        if rows:
            lines.append(heading)
            lines += [f"  {e.name}" for e in rows]
    if state.outstanding:
        lines.append("Summoned to:")
        lines += [f"  {a.name} ({a.state})" for a in state.outstanding]
    return lines
