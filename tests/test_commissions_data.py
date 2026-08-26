"""What the ledger's own bytes mean, checked against the shipped scripts.

`tests/test_commissions.py` covers the module's shape. This file covers the
*findings*: the four entries that keep a progress marker, the one that is dead,
and the one address two scripts fight over. Where the evidence is in the
bytecode, the test reads the bytecode off the player's disks rather than
trusting the table.

The disk-backed tests need no ECL decoder. A byte operand in this VM is always
`01 lo hi`, so counting that three-byte sequence in a script's payload counts
its references to one address -- strictly an over-count, since the sequence can
fall inside a string, which is the safe direction for an "is never referenced"
assertion.
"""

from __future__ import annotations

import pathlib

import pytest
from gamedata import disk_dir

import goldbox.commissions as C
from goldbox.d64 import D64, load_payload


def operand(address: int) -> bytes:
    """The three bytes a script spends naming one byte-wide address."""
    return bytes((0x01, address & 0xFF, address >> 8))


def _scripts() -> list[tuple[str, bytes]]:
    where = disk_dir()
    if where is None:
        pytest.skip("needs the game disks; set POR_DISKS to where they are")
    out = []
    for disk in sorted(where.glob("POOL*.[dD]64")):
        try:
            image = D64(disk.read_bytes())
        except Exception:
            continue
        for entry in image.directory():
            name = entry.name
            name = name if isinstance(name, bytes) else str(name).encode("latin1")
            if not name.startswith(b"ECL"):
                continue
            payload = load_payload(str(disk), name)
            out.append((name.decode(), payload[2:]))
    if not out:
        pytest.skip("no POOL disk here carries the scripts")
    return out


def references(address: int) -> dict[str, int]:
    """Script name -> how many times it names `address`."""
    seq = operand(address)
    return {name: payload.count(seq)
            for name, payload in _scripts() if payload.count(seq)}


def block(**values: int) -> bytes:
    """A flag block with a few bytes set, everything else zero."""
    data = bytearray(C.FLAGS_SIZE)
    for key, value in values.items():
        data[int(key[1:], 16) - C.FLAGS_BASE] = value
    return bytes(data)


# --- the 1-253 markers -------------------------------------------------------

def test_only_four_entries_keep_a_marker():
    """Every other ledger byte is 0, 254 or 255 and nothing else."""
    assert set(C.MARKERS) == {3, 10, 14}
    for index in range(C.LEDGER_COUNT):
        expected = index in C.MARKERS or index == 21
        assert any(C.marker_text(index, v) for v in range(1, C.DONE)) is expected


@pytest.mark.parametrize("index,value", [
    (3, 1), (3, 128), (10, 1), (14, 1), (14, 253),
])
def test_documented_markers_have_words(index, value):
    assert C.marker_text(index, value)


@pytest.mark.parametrize("value", [0, C.DONE, C.PAID_VALUE])
def test_marker_text_is_only_for_the_middle(value):
    assert C.marker_text(21, value) is None


def test_the_slums_counter_reads_as_a_count():
    assert C.marker_text(21, 4) == "4 of 25 encounters cleared"
    # `ECL14 $B6AD COMPARE [$4ABB], 25 / IF< / RETURN` then `SAVE 254`, so the
    # byte latches at 24 and 25 is never stored.
    assert C.marker_text(21, 24)
    assert C.marker_text(21, C.SLUM_ENCOUNTERS) is None


def test_the_slums_split_adds_up():
    """`$4A80` stops the wandering rolls at 15 (`ECL14 $9B32`, `$ADD6`) and
    there are ten set fights behind it, which is where the 25 comes from."""
    assert C.SLUM_WANDERING == 15
    assert C.SLUM_SET + C.SLUM_WANDERING == C.SLUM_ENCOUNTERS


def test_a_marker_reaches_the_entry():
    entry = C.ledger(block(x4ABB=4))[21]
    assert entry.state == C.IN_PROGRESS
    assert entry.detail == "4 of 25 encounters cleared"
    assert not entry.done


def test_the_clerk_pays_on_254_alone():
    """`ECL08 $9D1C COMPARE [$6E7A], 254 / IF=`: 253 is not close enough."""
    ledger = C.ledger(block(x4AB4=253))
    assert ledger[14].value == 253
    assert ledger[14].state == C.IN_PROGRESS
    assert not any(e.done for e in ledger)


# --- ledger index 22 ---------------------------------------------------------

def test_index_22_has_no_name():
    assert C.LEDGER[22] == (None, None)
    assert C.ledger_name(22) == "ledger entry 22"


def test_no_script_names_ledger_index_22():
    """`$4ABC`. Nothing writes it, so it can never leave 0."""
    assert references(C.LEDGER_BASE + 22) == {}


# --- the address two scripts share -------------------------------------------

def test_the_special_council_meeting_flag_has_two_owners():
    """`$4A9A` is the council's summons *and* a wilderness animation's counter.

    `ECL08` names it four times (`$AE97`, `$AF1E`, `$B28B`, `$B3B2`) and
    `ECL1A` three (`$AE11`, `$AF2B`, `$AF3B`), and `ECL1A` is not a City Hall
    script. `goldbox-bugs.md` has what the player loses.
    """
    where = references(0x4A9A)
    assert where == {"ECL08": 4, "ECL1A": 3}


def test_a_ledger_row_is_read_outside_the_city_hall():
    """The ledger is not private to the clerk, and the panel should know it.

    `$4AA7` is Sokal Keep's row. `ECL15` writes 254, `ECL08` pays -- and
    `ECL00 $9C5C COMPARE [$4AA7], 254` is civilised Phlan deciding whether the
    harbour master will sell passage to the keep. A ledger entry is world
    state, not bookkeeping.
    """
    assert set(references(C.LEDGER_BASE + 1)) == {"ECL00", "ECL08", "ECL15"}


# --- the offer board ---------------------------------------------------------

def test_major_is_ten_named_commissions():
    assert len(C.MAJOR) == 10
    assert all(C.LEDGER[i][0] for i in C.MAJOR)


def test_the_graveyard_is_offered_before_the_board():
    """`ECL08 $A584` runs ahead of `$A84D` and outside the three-offer cap."""
    state = block(x4AC1=C.GRAVEYARD_MIN_COMPLETED)
    offers = C.offered(state)
    assert offers[0] is C.GRAVEYARD
    assert len(offers) == C.OFFER_LIMIT + 1


@pytest.mark.parametrize("flags,strength", [
    (dict(x4AC1=3), None),                                   # too few completed
    (dict(x4AC1=6, x4AB1=C.PAID_VALUE), None),               # already paid
    (dict(x4AC1=6, x4A96=C.PAID_VALUE), None),               # already accepted
    (dict(x4AC1=6), C.GRAVEYARD_MIN_STRENGTH - 1),           # party too weak
])
def test_each_graveyard_gate_suppresses_it(flags, strength):
    assert C.graveyard_offer(block(**flags), strength) is None


def test_the_board_caps_at_three():
    assert len(C.offered(block())) == C.OFFER_LIMIT


def test_the_withdrawn_candidate_is_never_offered():
    """`ECL08 $AC0F` is a bare `GOTO $A890`: candidate 9 settles nothing."""
    everything = block()
    assert C.BOARD[9] not in C.offered(everything, limit=len(C.BOARD))


def test_nothing_is_offered_once_everything_is_paid():
    paid = {f"x{addr:04X}": C.PAID_VALUE for addr in
            list(range(C.LEDGER_BASE, C.LEDGER_BASE + C.LEDGER_COUNT))
            + [0x4AC2, 0x4A96, 0x4A97, 0x4A98, 0x4A99, 0x4A9A, 0x4A9B]}
    paid["x4AC1"] = 10
    assert C.offered(block(**paid)) == ()


def test_read_carries_the_party_strength_through():
    weak = C.read(block(x4AC1=6), party_strength=1)
    strong = C.read(block(x4AC1=6), party_strength=99)
    assert C.GRAVEYARD not in weak.offers
    assert C.GRAVEYARD in strong.offers


# --- the fixture the repository does hold ------------------------------------

def test_the_shipped_save_has_an_empty_ledger():
    path = pathlib.Path(__file__).parent / "fixtures" / "savedgame0.bin"
    state = C.read(path.read_bytes())
    assert state.completed == 0
    assert state.in_progress == ()
    assert state.paid == ()
