"""How much of a defeated party's treasure a companion takes, by port and title.

DOS, Amiga Pool of Radiance and DOS Curse and Silver Blades run one rule after
a won fight: each companion adds his share's low three bits to the companions'
parts, and every member adds to the party's denominator.  Each pile of coins
(and gems and jewellery) then loses a whole number of parts, so the answer is a
fraction.  The C64 rolls once per defeated monster instead, so the answer is a
chance, and the game never says which companion took a purse (the C64 reading
is in the R1 comment on the issue for the Character Editor's treasure-share
line).

A member's ``status`` is the port's own status byte, and the two families read
it in opposite senses.  On DOS and the Amiga a member counts as standing when it
is 0.  On the C64 zero means an empty party slot, and a companion is up when
bit 7 is clear.

Two grades are not CONFIRMED.  A C64 companion whose status is 0 sits in an
empty slot, so he is left out of both S and N; the code read only says bit 7
must be clear, and `POST.COM $194A` would settle whether a zero status counts.
C64 Silver Blades returns 0 because its counting pass skips companions while
`$7EA0` is 0, and that flag being 0 in every played game is PROBABLE; its
results carry ``certain=False``.

Nothing here reads a file or a disk, and nothing is written.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from fractions import Fraction

__all__ = [
    "Member",
    "MemberShare",
    "PartyShares",
    "RULES",
    "dos_shares",
    "c64_shares",
    "party_shares",
    "share_for",
    "pile_cut",
    "split_piles",
    "status_from_condition",
]

_POOL = "pool-of-radiance"
_CURSE = "curse-of-the-azure-bonds"
_SILVER = "secret-of-the-silver-blades"

_COMPANION_BIT = 0x80
_DOS_PARTS_MASK = 0x07
_C64_PARTS_MASK = 0x03

#: A DOS-family pile's quotient is kept as one byte, so the cut stops growing
#: once a pile of one kind passes this many times the denominator.
_QUOTIENT_WRAP = 256

FRACTION = "fraction"
CHANCE = "chance"


@dataclasses.dataclass(frozen=True)
class Member:
    """One party member as the engine's split code reads him."""

    #: The control byte; above 0x7F is a companion.
    control: int
    #: The raw treasure-share byte.
    share: int
    #: The port's own status byte.
    status: int

    @property
    def companion(self) -> bool:
        return bool(self.control & _COMPANION_BIT)


@dataclasses.dataclass(frozen=True)
class MemberShare:
    """What one companion takes, and the numbers it was worked from."""

    #: `"fraction"` of each pile (DOS family) or `"chance"` per defeated
    #: monster (C64).
    kind: str
    #: His own part: `parts / denominator`.
    value: Fraction
    #: His own parts, zero when he counts for nothing.
    parts: int
    #: Every member's count, the denominator of the DOS fraction.  On the C64
    #: it is `S + N + 1`.
    denominator: int
    #: The companions' parts together (DOS `C`, C64 `S`).
    companion_parts: int
    #: The occupied party slots, the C64's `N`; None on the DOS family.
    occupied_slots: int | None
    #: The pile size at which the DOS byte quotient wraps and less is taken;
    #: None on the C64.
    wrap_at: int | None
    #: False when the rule behind the value is PROBABLE rather than CONFIRMED.
    certain: bool = True


@dataclasses.dataclass(frozen=True)
class PartyShares:
    """The result for a whole party: one entry per member, None for a player."""

    kind: str
    #: Parallel to the members given; None for a member who is not a companion.
    shares: tuple[MemberShare | None, ...]
    #: All companions together: `C / A` of each pile, or the C64's one roll
    #: against the combined `S`.
    combined: Fraction
    #: False when the rule behind the figures is PROBABLE rather than CONFIRMED.
    certain: bool = True


def dos_shares(members: Sequence[Member]) -> PartyShares:
    """The DOS-family rule; Silver Blades' skipped pile is in `split_piles`."""
    parts = [_dos_parts(m) for m in members]
    total = sum(parts) + sum(1 for m in members if not _dos_counts_parts(m))
    companion_parts = sum(p for p, m in zip(parts, members) if _dos_counts_parts(m))
    shares: list[MemberShare | None] = []
    for m, p in zip(members, parts):
        if not m.companion:
            shares.append(None)
            continue
        shares.append(
            MemberShare(
                kind=FRACTION,
                value=Fraction(p, total) if total else Fraction(0),
                parts=p,
                denominator=total,
                companion_parts=companion_parts,
                occupied_slots=None,
                wrap_at=_QUOTIENT_WRAP * total,
            )
        )
    combined = Fraction(companion_parts, total) if total else Fraction(0)
    return PartyShares(FRACTION, tuple(shares), combined)


def _dos_counts_parts(m: Member) -> bool:
    """A companion whose status is 0 adds parts; anyone else adds one."""
    return m.companion and m.status == 0


def _dos_parts(m: Member) -> int:
    return (m.share & _DOS_PARTS_MASK) if _dos_counts_parts(m) else 0


def c64_shares(members: Sequence[Member]) -> PartyShares:
    """The C64 rule: one roll per defeated monster against the combined parts.

    The draw is 0 to `S + N` inclusive and the companions win below `S`, so the
    chance is `S / (S + N + 1)`.
    """
    occupied = sum(1 for m in members if m.status != 0)
    up = [
        m.companion and m.share != 0 and m.status != 0 and not m.status & 0x80
        for m in members
    ]
    parts = [(m.share & _C64_PARTS_MASK) if u else 0 for m, u in zip(members, up)]
    total_parts = sum(parts)
    denominator = total_parts + occupied + 1
    shares: list[MemberShare | None] = []
    for m, p in zip(members, parts):
        if not m.companion:
            shares.append(None)
            continue
        shares.append(
            MemberShare(
                kind=CHANCE,
                value=Fraction(p, denominator),
                parts=p,
                denominator=denominator,
                companion_parts=total_parts,
                occupied_slots=occupied,
                wrap_at=None,
            )
        )
    return PartyShares(CHANCE, tuple(shares), Fraction(total_parts, denominator))


def _c64_silver_blades(members: Sequence[Member]) -> PartyShares:
    """A played game's C64 Silver Blades skips its companions before counting."""
    occupied = sum(1 for m in members if m.status != 0)
    shares = tuple(
        MemberShare(CHANCE, Fraction(0), 0, occupied + 1, 0, occupied, None, False)
        if m.companion
        else None
        for m in members
    )
    return PartyShares(CHANCE, shares, Fraction(0), False)


#: One rule per (title key, port) whose code was read.  C64 Silver Blades is
#: PROBABLE, not CONFIRMED: it rests on the demo flag `$7EA0` being 0 in play.
RULES: dict[tuple[str, str], Callable[[Sequence[Member]], PartyShares]] = {
    (_POOL, "DOS"): dos_shares,
    (_POOL, "Amiga"): dos_shares,
    (_CURSE, "DOS"): dos_shares,
    (_SILVER, "DOS"): dos_shares,
    (_POOL, "C64"): c64_shares,
    (_CURSE, "C64"): c64_shares,
    (_SILVER, "C64"): _c64_silver_blades,
}


def party_shares(title_key: str, port: str, members: Sequence[Member]) -> PartyShares | None:
    """The party's split under the title's and port's rule, None with no rule."""
    rule = RULES.get((title_key, port))
    return None if rule is None else rule(members)


def share_for(
    title_key: str, port: str, members: Sequence[Member], index: int
) -> MemberShare | None:
    """One member's share, None for a player character or with no rule."""
    result = party_shares(title_key, port, members)
    return None if result is None else result.shares[index]


def status_from_condition(
    port: str, condition: tuple[str | None, bool | None] | None
) -> int | None:
    """The port's status byte for an editor `Member.condition`, None when unread.

    DOS and the Amiga read only whether the status is 0, so any state but
    "okay" is 1.  The C64 reads nonzero and bit 7, so a member in play is 1 and
    one out of play is 0x81.
    """
    if condition is None or condition[0] is None:
        return None
    name, in_play = condition
    if port == "C64":
        return 0x01 | (0x80 if in_play is False else 0)
    return 0 if name == "okay" else 1


def pile_cut(pile: int, denominator: int, companion_parts: int) -> int:
    """What the DOS-family loop takes from one pile: `((p div A) mod 256) * C`."""
    if pile <= 0 or companion_parts <= 0 or denominator <= 0:
        return 0
    return ((pile // denominator) % _QUOTIENT_WRAP) * companion_parts


def split_piles(
    piles: Sequence[int],
    denominator: int,
    companion_parts: int,
    title_key: str,
) -> list[int]:
    """The piles after the DOS-family split; Silver Blades leaves pile 0 alone."""
    first = 1 if title_key == _SILVER else 0
    return [
        p if i < first else p - pile_cut(p, denominator, companion_parts)
        for i, p in enumerate(piles)
    ]
