from __future__ import annotations

"""Boundary characters: `#516 (Generate boundary characters and check every
writer's field widths, since no real save reaches a limit and the corpus
cannot find a wrong one)`.

Every conversion test elsewhere in this project runs against records that
exist, which cannot find a width that is wrong until a real save happens to
reach it -- `#508 (A converted magic-user loses memorised spells on the way
to DOS, because our table says a title has fewer slots than the engine gives
it)` sat unnoticed for exactly that reason.  `tools/records/boundarychars.py` builds
four Pool of Radiance characters at the game's own reachable extremes; this
module runs every one of them through `goldbox.dos_codec.write` and checks
the writer came back whole (A), that the generator itself has not missed a
field the writer takes (B), the one array width the engine's own code
corroborates (C), and that the harness can actually fail (D).
"""

import dataclasses
import logging

import pytest
from test_doswriter import _portrait_tables

from goldbox import dos_codec, dos_port
from tools.records import boundarychars

CASES = boundarychars.CASES

#: Fields the writer recomputes rather than copies for a C64 source, so a
#: round trip against the *original* neutral value is not the right check --
#: `tests/test_neutral.py::test_every_value_a_writer_takes_comes_back_out_of_
#: the_record` keeps the same list for the C64 writer, and `#516`'s plan
#: comment carries it over here for the DOS one.  `attack_level` is a fifth,
#: found while building this: DOS Pool of Radiance never stores a real
#: fighting level (`#527`), so both the write and the read recompute it from
#: the class levels rather than round-tripping the byte, and
#: `tests/test_doswriter.py`'s own full round trip checks it against the
#: title's rule instead of against the original for the same reason
#: (`_attack_level_allowance`).
_RECOMPUTED_ON_A_C64_SOURCE = {
    "thac0_base", "thac0_current",
    "save_paralysis", "save_petrification", "save_wands", "save_breath",
    "save_spell",
    "thief_pick_pockets", "thief_open_locks", "thief_find_traps",
    "thief_move_silently", "thief_hide_in_shadows", "thief_hear_noise",
    "thief_climb_walls", "thief_read_languages",
    "spells_castable",
    "attack_level",
}

#: The portrait pair reports itself without help when there is no menu to
#: read (`goldbox.dos_codec.write`'s own account), so it is out of the round
#: trip by name rather than compared -- test A takes the mask off when
#: `_portrait_tables()` can read the menu.
_PORTRAIT_FIELDS = ("portrait_head", "portrait_body")


def _active_fields() -> list[str]:
    """Every neutral field `write_field_disposition` copies or transforms."""
    d = dos_codec.write_field_disposition("pool-of-radiance")
    return [name for name, why in d.items()
            if not why.startswith(("dropped:", "derived:", "constant:"))]


def _round_trip(char, tables=None):
    """`(back, rep)`: the case written to DOS and read straight back."""
    rec, itm, spc, rep = dos_codec.write(char, portraits=tables)
    deltas = dos_port.POOL_OF_RADIANCE
    items = [dos_codec.DosItem(itm[i:i + deltas.item_size])
             for i in range(0, len(itm), deltas.item_size)]
    effects = [spc[i:i + dos_codec.EFFECT_SIZE]
               for i in range(0, len(spc), dos_codec.EFFECT_SIZE)]
    back = dos_codec.to_neutral(
        dos_codec.DosCharacter(rec, items=items, effects=effects,
                               deltas=deltas), portraits=tables)
    return back, rep


# --- A: every case goes through the writer and comes back whole -------------

@pytest.mark.parametrize("name", sorted(CASES))
def test_a_boundary_character_writes_and_reads_back_whole(name, caplog):
    build = CASES[name]
    char = build()
    tables = _portrait_tables()
    excluded = set(_RECOMPUTED_ON_A_C64_SOURCE)
    if tables is None:
        excluded |= set(_PORTRAIT_FIELDS)

    with caplog.at_level(logging.WARNING, logger="wish.goldbox.dos_codec"):
        back, rep = _round_trip(char, tables)

    assert rep.warnings == [], (name, rep.warnings)
    expected_dropped = ([] if tables is not None else
                        [d for d in rep.dropped
                         if any(f in d for f in _PORTRAIT_FIELDS)])
    unexpected = [d for d in rep.dropped if d not in expected_dropped]
    assert unexpected == [], (name, unexpected)
    if tables is None:
        assert len(rep.dropped) == 2, (name, rep.dropped)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING], \
        (name, [r.getMessage() for r in caplog.records])

    for field in _active_fields():
        if field in excluded:
            continue
        want = char.get(field)
        got = back.get(field)
        if field == "levels":
            # The read side always hands back all eight DOS slots, zero for
            # a class the character does not hold; the case only names the
            # ones it does.
            got = {k: v for k, v in got.items() if v}
        assert got == want, (name, field, want, got)


# --- B: every active field has a value in the generator's own base ----------

def test_b_every_active_field_has_a_boundary_value():
    """The hook into `field_disposition()`: a field added to
    `goldbox/neutral.py` and wired into the writer has no value in
    `tools.records.boundarychars._base()` until somebody says what its extreme is,
    and this fails until they do."""
    base = boundarychars._base()
    missing = set(_active_fields()) - set(base.keys())
    assert missing == set()


# --- C: the engine's own width, for the one corroborated array --------------

capstone = pytest.importorskip("capstone")

from tools.dos import dosarraywidth  # noqa: E402

_SKIPPED_TITLES: list[str] = []


@pytest.mark.parametrize("title", sorted(dosarraywidth.STEMS))
def test_c_the_engine_agrees_with_our_table_on_spells_memorised(title):
    try:
        overlay = dosarraywidth.find_overlay(title)
    except FileNotFoundError as exc:
        _SKIPPED_TITLES.append(title)
        pytest.skip(f"needs the DOS {title} archives: {exc}")
    f = dos_port.FIELDS_BY_NAME_FOR[title]["spells_memorised"]
    got = dosarraywidth.width(overlay.read_bytes(), f.offset)
    assert got == f.size, (title, got, f.size)


# --- D: the regression tests for the harness itself --------------------------

def _old_table() -> dos_port.DosDeltas:
    """Pool of Radiance's table as it stood before `#508`'s fix: 16 slots at
    `0x01C` and a five-byte `gap_017` in front, rebuilt as a `DosDeltas`
    override rather than a second copy of the layout."""
    pool = dos_port.POOL_OF_RADIANCE
    return dataclasses.replace(
        pool,
        sizes={**pool.sizes, "spells_memorised": 16},
        inserts={**pool.inserts, "exceptional_strength": 5})


def test_d_the_harness_reports_the_table_508_corrected(monkeypatch, caplog):
    old = _old_table()
    monkeypatch.setitem(
        dos_port.FIELDS_BY_NAME_FOR, "pool-of-radiance",
        {f.name: f for f in dos_port.layout_for(old)})
    char = CASES["caster"]()
    with caplog.at_level(logging.WARNING, logger="wish.goldbox.dos_codec"):
        back, rep = _round_trip(char, tables=None)
    assert len(back.get("spells_memorised")) == 16
    assert any(
        "spells_memorised: 20 ids and Pool of Radiance allots 16 slots, "
        "so 4 were not written (#508)" in r.getMessage()
        for r in caplog.records)


def test_d_the_engine_check_reports_the_table_508_corrected():
    """The old table declared 16 bytes at `0x01C` -- the wrong **offset** as
    well as the wrong size, which is the whole of `#508`'s story: the real
    array starts five bytes earlier, at `0x017`, and nothing before the
    fix's own offset has any engine access at all (`width()` there answers
    `None`, not a number to disagree with). So the comparison this makes is
    the one the engine check could actually have made: the old table's own
    declared *size* against what `width()` reads at the array's real
    offset, which is what the fixed table now names.
    """
    pytest.importorskip("capstone")
    old = _old_table()
    old_size = {f.name: f for f in dos_port.layout_for(old)
               }["spells_memorised"].size
    real_offset = dos_port.FIELDS_BY_NAME["spells_memorised"].offset
    try:
        overlay = dosarraywidth.find_overlay("pool-of-radiance")
    except FileNotFoundError as exc:
        pytest.skip(f"needs the DOS Pool of Radiance archives: {exc}")
    got = dosarraywidth.width(overlay.read_bytes(), real_offset)
    assert got != old_size, (got, old_size)
    assert got == 21
