"""The City Council's books: the reward ledger, the offer board, the summons.

Everything here reads the 224 persistent flag bytes at `$4A20`-`$4AFF`, which
live at offset `$0100` in `SAVEDGAME0` (load address `$4900`) and are the same
bytes in a running machine. No transport and no Qt, so this works from a save
file, from a live read, or from a test's own array.

Two structures in `ECL08` (the Phlan City Hall, disk 3) carry the whole state:

    $4AA6 + i, i = 0..25   the reward ledger. The area script writes 254 when
                           the job is done; the clerk pays and writes 255. 0 is
                           untouched, and four entries also keep a progress
                           marker between 1 and 253 in the same byte.
    $4AC1                  commissions completed -- bumped by the clerk for the
                           ten jobs that count as major.

The index *is* the quest: each has the clerk's own speech in the 26-entry
`ONGOSUB [$6E79], 26` table at `ECL08 $9D55`, which is where the names below
come from. The clerk pays on exactly 254 (`$9D1C COMPARE [$6E7A], 254`), so any
other value sits there untouched by her.

**Only four entries ever hold a value between 1 and 253**; the other
twenty-two are 0, 254 or 255 and nothing else. `MARKERS` below carries those
four, each read off the script that writes it. A ledger byte the clerk will not
pay for is a real state, not a decoding error.

**255 does not always mean the party was paid.** Two entries are closed at 255
without a reward: index 3 when the party fled the Buccaneer's Base and left the
boy behind (`ECL08 $9EAD`, beside "YOUR BUNGLING THE BIVANT RESCUE HAS COST
US"), and index 18 when the party broke the seal on Cadorna's iron box, which
`ECL08 $9AAF` closes on entry to the City Hall while Cadorna confronts them.

**Index 22 is dead.** No instruction in any of the thirty scripts reads or
writes `$4ABC`, and its handler is a bare `RETURN` — but its row in the clerk's
four payout tables at `ECL08 $B5E0`/`$B5F7`/`$B60E`/`$B625` is not empty, so it
was a commission once. It can never be anything but 0.

`offered()` re-implements the board at `ECL08 $A84D`: sixteen candidates tested
in a fixed order, each a `COMPARE`/`IF`/`GOTO $A890` gate, at most three offered
per visit. The cap counter is `$4A05`, in the per-script scratch page, so it
resets when the party leaves — and it is never reset inside the script, which is
why a second approach to the clerk on the same visit says only "BACK SO SOON? I
CAN ONLY REPEAT THE EARLIER OFFERS" and lists nothing.

Three things the board does that a pure predicate cannot show:

* **The graveyard commission is offered before the sixteen** (`ECL08 $A584`) and
  does not count against the cap. `graveyard_offer()` has it.
* **Being offered a job writes flags.** Candidates 3, 4, 5, 12, 13, 14 and 15
  set `$4AB0`, `$4A97`, `$4A9B`, `$4A8C`, `$4A98`, `$4A99`/`$4A6B` and `$4A9A`
  as the clerk speaks. `offered()` predicts, it does not simulate.
* **Running the board dry advances the plot.** If the loop reaches candidate 16
  without filling the three slots, `$A842`/`$AF2C` writes 254 into `$4ABE` —
  ledger index 24, "Cadorna exposed as a traitor" — so the next visit gets that
  speech.

The write-ups, `work/reports/quest-flags.md` and
`work/reports/commissions.md`, are lost; the plan and its evidence table are
`docs/103-quest-log-panel.md`.
Nothing outside those two structures and the named appointment flags is exposed,
because nothing else in the region is confirmed to the same standard.
"""

from __future__ import annotations

from dataclasses import dataclass

FLAGS_BASE = 0x4A20
FLAGS_END = 0x4B00
FLAGS_SIZE = FLAGS_END - FLAGS_BASE                 # 224

# The scratch page below the persistent block. An area change zeroes it, so
# it is read through `scratch()` and never mixed into `Flags`.
SCRATCH_BASE = 0x4A00
SCRATCH_SIZE = FLAGS_BASE - SCRATCH_BASE            # 32

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

# The ten handlers that bump $4AC1. Confirmed twice: ten `ADD 1, [$4AC1],
# [$4AC1]` sites in the clerk's speech table, and `npc_party.d64`, which has
# exactly these six of them paid and reads 6.
MAJOR = frozenset({0, 1, 10, 11, 12, 13, 15, 16, 17, 21})

# ---------------------------------------------------------------------------
# The 1-253 markers.
#
# A ledger byte is 0 untouched, 254 done, 255 paid -- and four of the
# twenty-six also serve as the area script's own progress counter in the same
# byte. These are all of them; every write in every script was enumerated, and
# no other entry is ever anything but 0, 254 or 255.
#
# Each line names the instruction that writes it, because that is the evidence.
MARKERS: dict[int, dict[int, str]] = {
    3: {  # $4AA9, the Bivant heir -- Buccaneer's Base, ECL01
        1: "the boy has been bought from the captain; still inside the base",
        128: "you fled the last fight and left the boy behind",
    },
    10: {  # $4AB0, Podal Plaza
        1: "the clerk has read out the commission",
    },
    14: {  # $4AB4, Cadorna's diplomatic mission -- Zhentil outpost, ECL1C
        1: "the outpost commandant is dead; still inside the outpost",
        253: "the outpost has been left; the ride home is what pays it",
    },
}

# Index 21 is a plain count rather than a set of states: `ECL14 $B6A4 ADD 1,
# [$4ABB], [$4ABB]`, then `$B6AD COMPARE [$4ABB], 25 / IF< / RETURN` and
# `SAVE 254`, so 25 clears the area and the byte never holds 25 itself.
#
# "Encounters" is the right noun and the call sites are what prove it. The
# three instructions above are a subroutine at `ECL14 $B69C`, guarded by
# `COMPARE [$4ABB], 254 / IF>= / RETURN`, and fourteen `GOSUB [$B69C]` sites
# call it. Every one of them sits immediately after a `COMBAT`:
#
#   * twelve after a *set* encounter's fight -- $9E73 $9F08 $A0BE $A3B2 $A514
#     $AA02 $AA87 $AB91 $ABFE $AC4B $AF7A $B10D. Each is behind its own
#     one-shot flag, and $A0BE/$A3B2 are two outcomes of one encounter (the
#     man who wants the potion), so ten to eleven distinct fights;
#   * two in the wandering-monster outcome handler at $B118, on the two
#     winning results -- `$6DC7 == 0`, and `$6DC7 == 1` with kills. A loss
#     (128) and a flight (129) branch away without counting, so **one won
#     fight is exactly one increment**.
#
# The wandering half is capped elsewhere. `$4A80` counts won wandering fights
# and both spawn sites refuse to roll another once it reaches 15 (`ECL14
# $9B32` and `$ADD6`, `COMPARE [$4A80], 15 / IF>= / EXIT`). That 15 is the
# number Ozzy_98's PC walkthrough quotes; it is a different counter from this
# one and does not contradict the 25. Ten set fights plus fifteen wandering
# ones is 25 exactly, and two saves that finished the slums show `$4A80` = 15
# with all nine one-shot flags and the potion-man's `$4A81` set -- 10 + 15.
# The guide's "the set encounters do not need to be cleared" is wrong: on the
# minimum path every one of them is needed.
SLUM_ENCOUNTERS = 25

#: How the 25 splits, for anything that has to explain the number.
SLUM_WANDERING = 15         # $4A80's cap, ECL14 $9B32 / $ADD6
SLUM_SET = SLUM_ENCOUNTERS - SLUM_WANDERING

# What each marker is worth, one line, for a panel that has to say something
# better than the number.
def marker_text(index: int, value: int) -> str | None:
    """What a ledger byte between 1 and 253 means, or None if it means nothing.

    `None` is the honest answer for a value no script writes: the four entries
    below are the only ones with markers, so anything else in 1..253 is a byte
    the game did not put there.
    """
    if not 0 < value < DONE:
        return None
    if index == 21:
        if value >= SLUM_ENCOUNTERS:            # 25 latches to 254 at once
            return None
        return f"{value} of {SLUM_ENCOUNTERS} encounters cleared"
    return MARKERS.get(index, {}).get(value)


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
        # The bound below matters and used to be missing. `$4A04` minus
        # `$4A20` is -28, which Python happily reads as the 28th byte from
        # the end -- so asking a `Flags` for a scratch-page address quietly
        # answered with `$4AE4`'s value instead of failing. Found while
        # wiring up the scratch page for #158.
        if not FLAGS_BASE <= address < FLAGS_END:
            raise IndexError(
                f"${address:04X} is outside ${FLAGS_BASE:04X}-"
                f"${FLAGS_END - 1:04X}; the scratch page is `scratch()`")
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

    @property
    def detail(self) -> str | None:
        """What the progress marker means, for the entries that keep one."""
        return marker_text(self.index, self.value)


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

# The seventeenth. `ECL08 $A584` runs before the sixteen and outside the
# three-offer cap, so the graveyard can be raised on a visit that also fills
# the board. Its `order` is -1 because it is not on the board's own list.
GRAVEYARD = Offer(-1, "end the graveyard menace", (11,))

# The strength the clerk demands before she raises it at all, and the strength
# above which she offers an enchanted weapon for accepting. `PARTYSTRENGTH` is
# computed from the party, not stored in the flags, which is why it is a
# parameter here -- see `docs/114-party-strength.md`.
GRAVEYARD_MIN_STRENGTH = 19
GRAVEYARD_WEAPON_STRENGTH = 36

# Commissions completed before the clerk will raise the graveyard at all.
GRAVEYARD_MIN_COMPLETED = 4


def graveyard_offer(source, party_strength: int | None = None) -> Offer | None:
    """`ECL08 $A584`: the graveyard commission, offered before the sixteen.

    Four gates, in the script's order: `$4AC1 >= 4`, the graveyard reward not
    already paid, party strength `>= 19`, and the commission not already
    accepted (`$4A96 != 255`). `party_strength` of None means "not known", and
    the strength gate is taken as passed.
    """
    f = flags(source)
    if f[COMPLETED] < GRAVEYARD_MIN_COMPLETED:
        return None
    if f.ledger(11) == PAID_VALUE:
        return None
    if party_strength is not None and party_strength < GRAVEYARD_MIN_STRENGTH:
        return None
    if f[0x4A96] == PAID_VALUE:
        return None
    return GRAVEYARD


def offered(source, limit: int = OFFER_LIMIT,
            party_strength: int | None = None) -> tuple[Offer, ...]:
    """What the clerk would offer on the next visit, in the board's order.

    The graveyard commission comes first and does not count against `limit`,
    which is how `ECL08` runs it: `$A584` is reached before `$A831` zeroes the
    board index, and `$4A05` is only bumped inside the board's own loop.
    """
    f = flags(source)
    out = []
    grave = graveyard_offer(f, party_strength)
    if grave is not None:
        out.append(grave)
    board = []
    for offer in BOARD:
        if _gate(offer.order, f):
            board.append(offer)
            if len(board) == limit:
                break
    return tuple(out + board)


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


# --- side quests an area script keeps for itself ----------------------------
#
# A quest the City Council never hears about: an area script hands it out, an
# area script closes it, and no ledger byte moves. Ohlo's potion errand in the
# Slums is the first one found (#157) and the shape is built for the rest.
#
# **The accept flag and the finish flag are not in the same half of the page.**
# `$4A00`-`$4A1F` is scratch the engine zeroes on every area change -- the
# `NEWECL` handler's `LDX #$1F / LDA #$00 / STA $4A00,X / DEX / BPL` at
# `DUNGEON $202A`-`$2032`, re-derived 2026-09-02 -- and `$4A20`-`$4AF8`
# survives one. So a quest whose acceptance is recorded in the scratch half is
# a quest the game forgets the moment the party walks out of the area, and
# `durable` on each flag is what says which half it is in.
#
# Every `where` below is a script address, which is unambiguous: an `ECL`
# loads at `$9900`. The offsets quoted on #157 and #158 are not -- two of the
# four are file offsets, one is an offset into the body after the two-byte
# load address, and one points four bytes into the instruction it names.

#: A quest's state, as an identifier. Not interface text: what a panel says
#: about a side quest is #158 step 4 and is Donald's to word.
QUEST_UNSEEN = "not seen"
QUEST_ACCEPTED = "accepted"
QUEST_IN_HAND = "part done"
QUEST_FINISHED = "finished"
QUEST_UNKNOWN = "unknown"


@dataclass(frozen=True)
class QuestFlag:
    """One byte at one value, and the instruction that puts it there."""

    address: int
    value: int
    meaning: str
    durable: bool
    where: str

    @property
    def scratch(self) -> bool:
        """True when an area change wipes this byte."""
        return SCRATCH_BASE <= self.address < FLAGS_BASE


@dataclass(frozen=True)
class SideQuest:
    """A quest on its own flag bytes, outside the council's ledger."""

    key: str
    name: str
    script: str
    area: int
    accept: QuestFlag
    finish: QuestFlag
    progress: tuple[QuestFlag, ...] = ()

    @property
    def flags(self) -> tuple[tuple[int, int, str], ...]:
        """Every (address, value, meaning) this quest is made of."""
        return tuple((f.address, f.value, f.meaning)
                     for f in (self.accept, *self.progress, self.finish))

    @property
    def durable(self) -> bool:
        """True when the game itself remembers the whole quest."""
        return all(f.durable for f in (self.accept, *self.progress, self.finish))


SIDE_QUESTS = (
    SideQuest(
        key="ohlo",
        name="Ohlo's potion",
        script="ECL14",
        area=0x14,
        # One `SAVE 250, [$4A04]` in the whole script: a scan of the raw
        # bytes for `09 00 FA 01 04 4A` finds exactly one occurrence, and the
        # walk reaches it. It sits after the menu arm that agrees to serve
        # him rather than fight him.
        accept=QuestFlag(
            0x4A04, 250, "the errand has been accepted",
            durable=False, where="ECL14 $A251 SAVE 250, [$4A04]"),
        # The booth in the old rope guild, gated on `$AE1E COMPARE [$4A81],
        # 250 / IF>= / EXIT` -- it will not serve a party that already has
        # the potion or has finished with him -- and on the password.
        progress=(QuestFlag(
            0x4A81, 250, "the potion has been collected from the booth",
            durable=True, where="ECL14 $B048 SAVE 250, [$4A81], after "
                                "$B042 SAVE 255, [$4A19]"),),
        # Two routes to 255 and the flag does not tell them apart: the
        # delivery at $A3A2/$A3A8, after the `TREASURE`/`COMBAT` pair that
        # pays 150 platinum and one random magic item, and the kill at
        # $A084/$A0B8, after the `COMBAT` at $A0B3. Both then `GOSUB $B69C`,
        # which is what counts it as one of the slums' 25 encounters.
        finish=QuestFlag(
            0x4A81, 255, "Ohlo dealt with: the potion delivered, or he was killed",
            durable=True, where="ECL14 $A3A8 (delivered) and $A0B8 (killed)"),
    ),
)


@dataclass(frozen=True)
class SideQuestState:
    """What a save says about one side quest."""

    quest: SideQuest
    state: str
    accept_value: int | None
    finish_value: int

    @property
    def ambiguous(self) -> bool:
        """`QUEST_UNSEEN` here could equally mean "accepted, then left".

        True whenever the accept flag is in the scratch page and the durable
        half says nothing. It is not a claim that the party accepted
        anything -- it is the statement that this save cannot tell the two
        apart, which is the whole reason #158 exists. All 16 saves on the
        machine that never met Ohlo read exactly like a party that accepted
        the errand and walked out of the Slums.
        """
        return self.state == QUEST_UNSEEN and not self.quest.accept.durable


class Scratch:
    """`$4A00`-`$4A1F`, the page an area change zeroes.

    Kept apart from `Flags` on purpose: a byte in here means something only
    while the script that wrote it is still resident, so a caller has to ask
    for it by name rather than get it mixed into the persistent block.
    """

    __slots__ = ("_data",)

    def __init__(self, data: bytes):
        if len(data) != SCRATCH_SIZE:
            raise ValueError(
                f"expected {SCRATCH_SIZE} scratch bytes, got {len(data)}")
        self._data = bytes(data)

    def __getitem__(self, address: int) -> int:
        return self._data[address - SCRATCH_BASE]

    def to_bytes(self) -> bytes:
        return self._data


def scratch(source) -> Scratch | None:
    """`$4A00`-`$4A1F` out of whichever container the caller holds.

    `None` where the source cannot carry it -- the 224 persistent bytes, or a
    `Flags`. Everything else `flags()` accepts does carry it: a `$4A00` page
    and `SAVEDGAME0` both start at or below `$4A00`.
    """
    if isinstance(source, Scratch):
        return source
    if isinstance(source, Flags):
        return None
    if hasattr(source, "to_bytes"):
        source = source.to_bytes()
    data = bytes(source)
    if len(data) == SCRATCH_SIZE:
        return Scratch(data)
    if len(data) == FLAGS_SIZE:
        return None
    if len(data) == 0x100:                     # a $4A00 page
        return Scratch(data[:SCRATCH_SIZE])
    if len(data) >= FLAGS_BASE - 0x4900:       # SAVEDGAME0 from $4900
        start = SCRATCH_BASE - 0x4900
        return Scratch(data[start:start + SCRATCH_SIZE])
    return None


def side_quests(source) -> tuple[SideQuestState, ...]:
    """What a save says about each side quest, as far as it can say anything.

    The durable flag is read from `flags()`; the accept flag is read from
    `scratch()` when the source carries it. A quest whose accept flag is in
    the scratch page and whose durable flag is still 0 reads as
    `QUEST_UNSEEN` from a save made outside its area **whether or not the
    party accepted it**, which is the whole reason #158 exists.
    """
    f = flags(source)
    s = scratch(source)
    out = []
    for quest in SIDE_QUESTS:
        finish_value = f[quest.finish.address]
        accept_value = None
        if quest.accept.durable:
            accept_value = f[quest.accept.address]
        elif s is not None:
            accept_value = s[quest.accept.address]
        if finish_value == quest.finish.value:
            state = QUEST_FINISHED
        elif any(f[p.address] == p.value for p in quest.progress
                 if p.durable):
            state = QUEST_IN_HAND
        elif accept_value is None:
            state = QUEST_UNKNOWN
        elif accept_value == quest.accept.value:
            state = QUEST_ACCEPTED
        else:
            state = QUEST_UNSEEN
        out.append(SideQuestState(quest=quest, state=state,
                                  accept_value=accept_value,
                                  finish_value=finish_value))
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


def read(source, party_strength: int | None = None) -> Commissions:
    """Everything, from the flag block."""
    f = flags(source)
    return Commissions(completed=f[COMPLETED], ledger=ledger(f),
                       offers=offered(f, party_strength=party_strength),
                       appointments=appointments(f))


def summary_lines(source) -> list[str]:
    """The panel as text, for a terminal. Same content, no Qt."""
    state = read(source)
    lines = [f"Quests completed: {state.completed}"]
    lines.append("Available:")
    lines += [f"  {o.text}" for o in state.offers] or ["  nothing"]
    for heading, rows in (("In progress:", state.in_progress),
                          ("Reward waiting:", state.reward_waiting),
                          ("Paid:", state.paid)):
        if rows:
            lines.append(heading)
            lines += [f"  {e.name}" + (f" - {e.detail}" if e.detail else "")
                      for e in rows]
    if state.outstanding:
        lines.append("Summoned to:")
        lines += [f"  {a.name} ({a.state})" for a in state.outstanding]
    return lines
