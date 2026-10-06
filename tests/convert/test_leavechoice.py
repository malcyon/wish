"""The player's choice of what to leave behind reaches the C64 writer (#432).

A DOS Silver Blades character whose joined scrolls need more than the C64's
sixteen slots converts once the player names what stays behind; each item left
is one line of `Report.left_behind` and never a loss, so Save As does not
block the player's own choice.
"""

from __future__ import annotations

import logging
import random
import shutil
import time

import pytest
from support import packoverflow
from test_joinedscroll import (
    SCROLL_A,
    SCROLL_B,
    SSB,
    _party_file,
    _record,
    _shipped_party,
)

from editor import convert, dosimport, saveplan
from goldbox import dos_codec
from goldbox.neutral import ScrollBundle

NO_LEAVE_MESSAGE = "need 17 C64 item slots"


def _crowded_folder(tmp_path):
    """The archives' shipped Silver Blades party with member 1's pack
    replaced by fifteen items and a joined pair: 17 C64 slots."""
    folder = tmp_path / "crowded"
    shutil.copytree(_shipped_party(), folder)
    (folder / "CHRDATA1.SAV").write_bytes(_record(16))
    (folder / "CHRDATA1.STF").write_bytes(
        _party_file(15, SCROLL_A, SCROLL_B))
    return folder


def _files():
    return dosimport.GameFiles(icon=bytes(36), animate=bytes(852))


def test_a_pack_that_needs_17_slots_converts_once_the_player_chooses(
        tmp_path, caplog):
    folder = _crowded_folder(tmp_path)
    with pytest.raises(dos_codec.JoinedScrollsDoNotFit,
                       match=NO_LEAVE_MESSAGE):
        dosimport.rehearse(folder, "A", _files())

    # The wish logger is silenced while the GUI debug log is off, and a
    # logger level filters before caplog's root handler sees the record.
    with caplog.at_level(logging.INFO, logger="wish"):
        conversion = dosimport.rehearse(folder, "A", _files(),
                                        leave={0: {3}})
    report = conversion.report
    assert len(report.left_behind) == 1
    assert "left behind" in report.left_behind[0]
    for line in (*report.losses, *report.dropped):
        assert "inventory" not in line.lower(), line
    # The writer logs each left item; a second logger repeating them would
    # print every line twice.
    logged = [r.getMessage() for r in caplog.records
              if any(line in r.getMessage() for line in report.left_behind)]
    assert len(logged) == len(report.left_behind) == 1, logged


def test_saveplan_rehearse_hands_the_choice_to_the_direction(monkeypatch):
    monkeypatch.setattr(saveplan, "requirements", lambda *a: [])
    seen = {}

    class Fake:
        destination_port = "c64"
        source_port = "dos"

        def rehearse(self, source, slot, options, names=None, leave=None):
            seen["leave"] = leave
            return "rehearsal"

    class Source:
        slot = "A"
        path = "x"

    class Assets:
        game_files = object()

        def has(self, need):
            return True

    got = saveplan.rehearse(Fake(), Source(), Assets(),
                            leave={0: frozenset({3})})
    assert got == ("rehearsal", "A")
    assert seen["leave"] == {0: frozenset({3})}


@pytest.mark.parametrize("name", [
    "C64ToDos", "AmigaToDos", "C64ToAmiga"])
def test_a_direction_that_writes_no_c64_record_blocks_a_choice(name):
    direction = getattr(convert, name, None)
    if direction is None:
        pytest.skip(f"no {name} class")
    inst = direction.__new__(direction)
    inst.source_port, inst.destination_port = "a", "b"
    inst.deltas = SSB
    with pytest.raises(saveplan.SaveAsError):
        inst.rehearse(type("S", (), {"slot": "A", "path": "x"})(), "A", None,
                      leave={0: {1}})


def test_dos_to_amiga_blocks_a_choice_for_a_title_with_no_joined_scroll():
    from goldbox import dos_port

    inst = convert.DosToAmiga.__new__(convert.DosToAmiga)
    inst.source_port, inst.destination_port = "dos", "amiga"
    inst.deltas = dos_port.CURSE_OF_THE_AZURE_BONDS
    with pytest.raises(saveplan.SaveAsError):
        inst.rehearse(type("S", (), {"slot": "A", "path": "x"})(), "A", None,
                      leave={0: {1}})


def test_the_choice_reaches_the_dos_to_c64_direction(monkeypatch):
    seen = {}

    def fake(folder, slot, options, leave=None):
        seen["leave"] = leave
        raise RuntimeError("stop")

    monkeypatch.setattr(dosimport, "rehearse", fake)
    direction = convert.DosToC64.__new__(convert.DosToC64)
    direction.source_port, direction.deltas = "dos", SSB
    direction._name = "N{slot}"

    class Source:
        def folder(self):
            import contextlib
            return contextlib.nullcontext("f")

    with pytest.raises(RuntimeError):
        direction.rehearse(Source(), "A", _files(), leave={0: {3}})
    assert seen["leave"] == {0: {3}}


def test_saveplan_rehearse_hands_the_effects_choice_to_the_direction(
        monkeypatch):
    monkeypatch.setattr(saveplan, "requirements", lambda *a: [])
    seen = {}

    class Fake:
        destination_port = "c64"
        source_port = "dos"

        def rehearse(self, source, slot, options, names=None, leave=None,
                     leave_effects=None):
            seen["leave_effects"] = leave_effects
            return "rehearsal"

    class Source:
        slot = "A"
        path = "x"

    class Assets:
        game_files = object()

        def has(self, need):
            return True

    got = saveplan.rehearse(Fake(), Source(), Assets(),
                            leave_effects={0: frozenset({3})})
    assert got == ("rehearsal", "A")
    assert seen["leave_effects"] == {0: frozenset({3})}


def test_saveplan_rehearse_sends_no_effects_argument_without_a_choice(
        monkeypatch):
    """A direction that has no effects to choose about is not handed the
    argument."""
    monkeypatch.setattr(saveplan, "requirements", lambda *a: [])

    class Fake:
        destination_port = "dos"
        source_port = "c64"

        def rehearse(self, source, slot, options, names=None, **chosen):
            assert "leave_effects" not in chosen
            return "rehearsal"

    class Source:
        slot = "A"
        path = "x"

    class Assets:
        game_files = object()
        source_files = type("F", (), {"icon": None})()
        dos_folder = None

        def has(self, need):
            return True

    saveplan.rehearse(Fake(), Source(), Assets(), leave_effects={})


def test_the_effects_choice_reaches_the_dos_to_c64_direction(monkeypatch):
    seen = {}

    def fake(folder, slot, options, leave=None, leave_effects=None):
        seen["leave_effects"] = leave_effects
        raise RuntimeError("stop")

    monkeypatch.setattr(dosimport, "rehearse", fake)
    direction = convert.DosToC64.__new__(convert.DosToC64)
    direction.source_port, direction.deltas = "dos", SSB
    direction._name = "N{slot}"

    class Source:
        def folder(self):
            import contextlib
            return contextlib.nullcontext("f")

    with pytest.raises(RuntimeError):
        direction.rehearse(Source(), "A", _files(), leave_effects={0: {3}})
    assert seen["leave_effects"] == {0: {3}}


def _reference_items_to_leave(overflow, leave):
    """The exhaustive search `amiga_items_to_leave` replaced, kept to check it."""
    leave = {m: set(v) for m, v in (leave or {}).items()}
    if dos_codec.amiga_scrolls_over_limit(overflow, leave) == 0:
        return 0
    groups = []
    for member in overflow.members:
        ticked = leave.get(member, set())
        loose = []
        for u in overflow.units:
            if u.member == member and u.kind == "item":
                loose.extend(i for i in u.indices if i not in ticked)
        groups.append((member, loose))
        for u in overflow.units:
            if u.member == member and u.kind == "joined":
                groups.append((member,
                               [i for i in u.indices if i not in ticked]))
    groups = [g for g in groups if g[1]]
    total = sum(len(g[1]) for g in groups)

    def fits(counts):
        trial = {m: set(v) for m, v in leave.items()}
        for (member, free), n in zip(groups, counts):
            trial.setdefault(member, set()).update(free[:n])
        return dos_codec.amiga_scrolls_over_limit(overflow, trial) == 0

    def spread(start, left, counts):
        if left == 0:
            return fits(counts + [0] * (len(groups) - len(counts)))
        if start == len(groups):
            return False
        for n in range(min(left, len(groups[start][1])), -1, -1):
            if spread(start + 1, left - n, counts + [n]):
                return True
        return False

    for k in range(1, total + 1):
        if spread(0, k, []):
            return k
    return total


def _crowd(*members):
    """A neutral party; each member is `(plain items, joined scroll sizes)`."""
    chars = []
    for n, (plain, sizes) in enumerate(members):
        char = packoverflow.member(f"M{n}", plain)
        inventory = list(char.get("inventory"))
        bundles = []
        for size in sizes:
            bundles.append(ScrollBundle(len(inventory), size,
                                        packoverflow.head(size)))
            inventory.extend(packoverflow.scroll(1) for _ in range(size))
        char.set("inventory", inventory, "made up")
        char.set("scroll_bundles", tuple(bundles), "made up")
        chars.append(char)
    return chars


def _amiga_overflow(*members):
    found = dos_codec.pack_overflow(_crowd(*members), "amiga")
    assert found
    return found[0]


# One or two members (plain items, joined scroll sizes) whose joined scrolls
# pass the limit by 1 to 30 after the best unjoin; the exhaustive search leaves
# one to three items for them.
SMALL_PARTIES = [
    [(12, (3, 2, 4, 2, 7, 5, 4, 8, 4, 12)), (15, (4, 10, 2, 11, 6, 11, 3, 3, 4, 10, 11, 3, 4, 8))],
    [(16, (4, 5, 4, 4, 1, 6, 9, 6, 8, 12)), (16, (12, 7, 12, 6, 4, 8, 8, 1, 2, 8, 7, 3))],
    [(11, (8, 4, 6, 10, 12, 4, 1, 9, 1, 1, 1)), (11, (3, 1, 1, 3, 2, 7, 12, 10, 2, 11, 5, 9))],
    [(8, (1, 3, 3, 9, 5, 3, 1, 7, 12, 1, 5, 9, 2)), (10, (8, 7, 12, 2, 6, 6, 2, 3, 11, 1, 2))],
    [(16, (2, 7, 8, 8, 6, 11, 6, 3, 1, 3, 5, 2, 4, 6)), (15, (4, 12, 3, 10, 3, 7, 3, 3, 3, 5))],
    [(7, (10, 4, 3, 5, 3, 6, 4, 4, 7, 2, 3)), (6, (11, 4, 3, 4, 11, 2, 11, 12, 5, 1, 7, 6, 7))],
    [(16, (7, 7, 2, 10, 3, 10, 9, 8, 1, 12, 1, 12, 8, 8)), (2, (10, 3, 1, 3, 7, 8, 4, 5, 1, 4))],
    [(15, (7, 5, 11, 11, 1, 3, 11, 4, 8, 3, 11)), (14, (12, 1, 4, 8, 4, 7, 3, 3, 10, 3, 2, 3, 9))],
    [(9, (3, 2, 2, 12, 8, 4, 8, 3, 6, 11)), (12, (10, 4, 7, 4, 11, 3, 4, 10, 6, 1, 10, 9, 8))],
    [(5, (12, 11, 8, 5, 1, 2, 6, 12, 4, 7, 3, 8)), (7, (11, 4, 2, 8, 10, 2, 4, 1, 4, 8, 3))],
    [(14, (8, 6, 3, 11, 2, 9, 8, 4, 8, 1, 11, 6)), (4, (3, 4, 9, 6, 8, 1, 4, 3, 2, 8, 2, 8))],
    [(14, (9, 7, 3, 4, 3, 4, 8, 4, 12, 4)), (7, (3, 2, 9, 8, 7, 2, 10, 12, 8, 8, 12, 1, 8, 1))],
]


@pytest.mark.parametrize("members", SMALL_PARTIES)
def test_items_to_leave_matches_the_exhaustive_search(members):
    overflow = _amiga_overflow(*members)
    pack_sizes = {m: len(overflow.items[n])
                  for n, m in enumerate(overflow.members)}
    rng = random.Random(len(str(members)))
    for attempt in range(4):
        leave = {}
        for member, size in pack_sizes.items():
            if attempt and rng.random() < 0.7:
                leave[member] = set(rng.sample(range(size),
                                               rng.randrange(0, min(size, 6))))
        got = dos_codec.amiga_items_to_leave(overflow, leave)
        assert got == _reference_items_to_leave(overflow, leave)


@pytest.fixture
def cold_member_tables():
    """Empty the per-member table caches so the test sees a cold build."""
    dos_codec._member_unjoin_table.cache_clear()
    dos_codec._member_leave_options.cache_clear()


def test_items_to_leave_for_a_late_game_party_returns_at_once(
        cold_member_tables):
    overflow = _amiga_overflow(*[(8, (10,) * 13)] * 2)
    start = time.perf_counter()
    got = dos_codec.amiga_items_to_leave(overflow, {})
    assert time.perf_counter() - start < 1.0
    assert got > 0
    left = dos_codec.amiga_scrolls_over_limit(overflow, {})
    assert left > 0


def test_items_to_leave_for_six_members_returns_at_once(cold_member_tables):
    overflow = _amiga_overflow(*[(6, (10,) * 6)] * 6)
    start = time.perf_counter()
    got = dos_codec.amiga_items_to_leave(overflow, {})
    assert time.perf_counter() - start < 1.0
    assert got > 0


def _tables_built(call):
    """How many member tables `call` had to build rather than reuse."""
    before = (dos_codec._member_unjoin_table.cache_info().misses,
              dos_codec._member_leave_options.cache_info().misses)
    call()
    after = (dos_codec._member_unjoin_table.cache_info().misses,
             dos_codec._member_leave_options.cache_info().misses)
    return after[0] - before[0], after[1] - before[1]


def test_a_tick_rebuilds_only_the_ticked_members_tables(cold_member_tables):
    overflow = _amiga_overflow(*[(4 + 2 * n, (10,) * 16) for n in range(6)])
    leave = {overflow.members[0]: {0}}
    dos_codec.amiga_items_to_leave(overflow, leave)
    # One more item ticked for the second member only.
    leave = {overflow.members[0]: {0}, overflow.members[1]: {0}}
    unjoin, options = _tables_built(
        lambda: dos_codec.amiga_items_to_leave(overflow, leave))
    assert unjoin == 1
    # The widening search may call each size of `cap` afresh for the ticked
    # member, and never for the five that did not change.
    assert 1 <= options <= 8
    # The same call again builds nothing.
    assert _tables_built(
        lambda: dos_codec.amiga_items_to_leave(overflow, leave)) == (0, 0)


@pytest.mark.parametrize("members", [
    [(12, (3, 2, 4, 2, 7, 5, 4, 8)), (15, (4, 10, 2, 11, 6, 11, 3)),
     (9, (10, 4, 7, 4, 11, 3, 4, 10))],
    [(7, (10, 4, 3, 5, 3, 6, 4, 4)), (6, (11, 4, 3, 4, 11, 2, 11, 12)),
     (14, (8, 6, 3, 11, 2, 9, 8, 4))],
])
def test_items_to_leave_for_three_members_matches_the_exhaustive_search(
        members):
    overflow = _amiga_overflow(*members)
    for leave in ({}, {overflow.members[1]: {0, 1}},
                  {overflow.members[0]: {2}, overflow.members[2]: {0}}):
        assert (dos_codec.amiga_items_to_leave(overflow, leave)
                == _reference_items_to_leave(overflow, leave))


@pytest.mark.parametrize("members", [
    [(6, (3, 4, 2, 5)), (7, (4, 3, 6, 2))],
    [(4, (5, 5, 3)), (5, (2, 6, 4)), (3, (4, 4, 4))],
])
def test_items_to_leave_when_unjoining_must_fit_the_rows(members, monkeypatch):
    from goldbox import amiga_later
    monkeypatch.setattr(amiga_later, "AMIGA_SSB_ITEM_ROWS", 14)
    monkeypatch.setattr(amiga_later, "AMIGA_SSB_JOINED_SCROLL_LIMIT", 6)
    overflow = _amiga_overflow(*members)
    for leave in ({}, {overflow.members[0]: {0}}):
        assert (dos_codec.amiga_items_to_leave(overflow, leave)
                == _reference_items_to_leave(overflow, leave))
