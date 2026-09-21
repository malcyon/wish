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
corroborates (C), and that the harness can actually fail (D).  Parts E to H
sweep the writer's own field widths in all four titles it builds a record
for -- every scalar at its width and one past it, the one place a C64 field is
wider than its DOS one, and every legal Curse and Silver Blades character --
with `tools/records/doswidths.py` building the characters, and part I settles
whether the C64's item block can be handed a wrong-length item by anything
that builds one from a DOS record.
"""

import dataclasses
import logging

import pytest
from support.doswriter import _portrait_tables

from goldbox import c64_codec, dos_codec, dos_port, layout
from tools.records import boundarychars, doswidths, laterchars

CASES = boundarychars.CASES

#: Fields the writer recomputes rather than copies for a C64 source, so a
#: round trip against the *original* neutral value is not the right check.
#: `tools/records/doswidths.py` keeps the list with the writer's own reason
#: beside each name, and `tests/convert/test_neutral.py::test_every_value_a_
#: writer_takes_comes_back_out_of_the_record` keeps its own for the C64 writer.
_RECOMPUTED_ON_A_C64_SOURCE = set(doswidths.RECOMPUTED)

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
    """`(back, rep)`: the case written to DOS and read straight back, in the
    title the character carries."""
    rec, itm, spc, rep = dos_codec.write(char, portraits=tables)
    deltas = dos_codec.write_deltas(char)
    items = [dos_codec.DosItem(itm[i:i + deltas.item_size], deltas.item_size)
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


# --- E: every scalar at its declared width, in all four titles ---------------

POOL = "pool-of-radiance"
CURSE = "curse-of-the-azure-bonds"
SILVER = "secret-of-the-silver-blades"
POOLS_OF_DARKNESS = "pools-of-darkness"

#: The drop lines a base character produces in each title, by field, and no
#: others.  Pool of Radiance drops the portrait pair because there is no menu
#: to turn it into a position with; Pools of Darkness keeps no drained-level
#: pair, no lighter coins and no per-hit-point rate, so a base character that
#: sets them is told.  Any other line is a loss the sweep has not accounted for.
_BASE_DROPS = {
    POOL: {"portrait_head", "portrait_body"},
    CURSE: set(),
    SILVER: set(),
    POOLS_OF_DARKNESS: {"levels_drained", "hp_lost_to_drain", "copper",
                        "silver", "electrum", "gold",
                        "experience_per_hit_point"},
}

#: Every scalar the sweep sets, with its title, so each is a test of its own.
_SWEPT = [(game, s) for game in doswidths.GAMES
          for s in doswidths.scalars(game)
          if s.neutral not in doswidths.ALWAYS_RECOMPUTED]


def _ids(pair):
    return f"{pair[0]}-{pair[1].neutral}"


def _dropped_fields(rep) -> set[str]:
    return {line.split(":")[0] for line in rep.dropped}


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records
            if r.levelno >= logging.WARNING]


@pytest.mark.parametrize("high", [False, True], ids=["lowest", "highest"])
@pytest.mark.parametrize("pair", _SWEPT, ids=_ids)
def test_e_a_scalar_at_its_width_writes_and_reads_back_equal(pair, high,
                                                            caplog):
    game, s = pair
    want = s.high if high else s.low
    char = doswidths.base(game)
    char.set(s.neutral, want, "boundary")
    with caplog.at_level(logging.WARNING, logger="wish.goldbox.dos_codec"):
        back, rep = _round_trip(char)
    assert rep.warnings == [], (game, s.neutral, rep.warnings)
    assert _dropped_fields(rep) == _BASE_DROPS[game], (game, rep.dropped)
    assert _warnings(caplog) == [], (game, s.neutral)
    assert back.get(s.neutral) == want, (game, s.neutral, want,
                                         back.get(s.neutral))


@pytest.mark.parametrize("game", doswidths.GAMES)
def test_e_the_recomputed_scalars_never_reach_their_byte(game):
    """A value set on `thac0_base` or `char_class` is discarded for one the
    writer works out, so a round trip and a value past the width both say
    nothing about them -- the two records are the same whatever was set."""
    swept = {s.neutral: s for s in doswidths.scalars(game)}
    checked = 0
    for name in sorted(set(swept) & set(doswidths.ALWAYS_RECOMPUTED)):
        records = []
        for value in (swept[name].low, swept[name].high):
            char = doswidths.base(game)
            char.set(name, value, "boundary")
            records.append(dos_codec.write(char)[0])
        assert records[0] == records[1], (game, name)
        checked += 1
    assert checked >= 2


@pytest.mark.parametrize("game", doswidths.GAMES)
def test_e_every_numeric_target_is_a_scalar_or_says_why_not(game):
    """The hook into `write_targets`: a numeric field added to the writer is
    swept as a scalar unless `doswidths.STRUCTURED` gives its neutral field a
    sentence, and a sentence for a field no title writes goes stale."""
    left_out = set(doswidths.structured_targets(game).values())
    assert left_out <= set(doswidths.STRUCTURED), (game, left_out)
    seen = {n for g in doswidths.GAMES
            for n in doswidths.structured_targets(g).values()}
    assert set(doswidths.STRUCTURED) == seen


def test_e_the_sweep_covers_the_scalars_it_says_it_does():
    """The counts a sweep that skipped most fields would not reach, per title:
    the numeric targets `write_targets` names less the ones with their own
    sentence."""
    counts = {g: len(doswidths.scalars(g)) for g in doswidths.GAMES}
    assert counts == {POOL: 48, CURSE: 41, SILVER: 41, POOLS_OF_DARKNESS: 34}


@pytest.mark.parametrize("game", doswidths.GAMES)
def test_e_a_size_and_a_class_mask_hold_what_the_writer_says(game):
    """`size_small` is stored plus one, so 254 is the most a byte holds and 255
    is clamped, naming `size`; a class mask past a byte is clamped, naming
    `class_bits`.  Neither is a simple width, so neither is in the sweep."""
    char = doswidths.base(game)
    char.set("size_small", 254, "boundary")
    back, rep = _round_trip(char)
    assert back.get("size_small") == 254 and rep.warnings == []

    char.set("size_small", 255, "boundary: one past")
    back, rep = _round_trip(char)
    assert back.get("size_small") == 254
    assert "size: 256 does not fit the DOS one-byte field; clamped" \
        in rep.warnings

    char = doswidths.base(game)
    char.set("class_bits", 256, "boundary: one past")
    _, rep = _round_trip(char)
    assert "class_bits: 256 does not fit the DOS one-byte field; clamped" \
        in rep.warnings


# --- F: one past a width is clamped, refused or (I8) wrapped, by name -------

#: The scalars a DOS field cannot hold one past, with the width each is
#: declared at: every multi-byte one, which the writer refuses with a
#: `ValueError`.  The widths are typed here, not read from the table, so a
#: field the table narrows or widens fails; and named, so a field that moves
#: from one side to the other fails rather than falling out of the sweep.
_COINS = {name: 2 for name in ("copper", "silver", "electrum", "gold",
                               "platinum", "gems", "jewelry")}
_LATER_REFUSED = {"age": 2, "experience": 4, "experience_award": 2, **_COINS}
_REFUSED = {
    POOL: dict(_LATER_REFUSED),
    CURSE: dict(_LATER_REFUSED),
    SILVER: dict(_LATER_REFUSED),
    POOLS_OF_DARKNESS: {"age": 2, "experience": 4, "experience_award": 2,
                        **{n: 2 for n in ("platinum", "gems", "jewelry")}},
}

#: The eight thief percentages: `Kind.I8`, which `dos_codec.write` does not
#: clamp the way it clamps a `U8`.  One past 127 wraps to -128 with no line.
_WRAPPED = {f"thief_{n}" for n in (
    "pick_pockets", "open_locks", "find_traps", "move_silently",
    "hide_in_shadows", "hear_noise", "climb_walls", "read_languages")}

_SWEPT_PAST = [(game, s) for game in doswidths.GAMES
               for s in doswidths.scalars(game)
               if s.neutral not in doswidths.ALWAYS_RECOMPUTED]


def _side(game, s) -> str:
    if s.neutral in _REFUSED[game]:
        return "refused"
    return "wrapped" if s.neutral in _WRAPPED else "clamped"


@pytest.mark.parametrize("pair", _SWEPT_PAST, ids=_ids)
def test_f_one_past_a_width_is_handled_the_way_its_side_says(pair):
    game, s = pair
    side = _side(game, s)
    above, below = s.high + 1, s.low - 1
    char = doswidths.base(game)

    if side == "refused":
        for past in (above, below):
            char.set(s.neutral, past, "boundary: one past")
            with pytest.raises(ValueError, match=f"{s.dos}: {past} does not "
                               f"fit in {s.size} bytes"):
                dos_codec.write(char)
    elif side == "clamped":
        for past, kept in ((above, s.high), (below, s.low)):
            char.set(s.neutral, past, "boundary: one past")
            back, rep = _round_trip(char)
            assert (f"{s.dos}: {past} does not fit the DOS one-byte field; "
                    f"clamped") in rep.warnings, (game, s.neutral, rep.warnings)
            assert back.get(s.neutral) == kept, (game, s.neutral)
    else:
        char.set(s.neutral, above, "boundary: one past")
        back, rep = _round_trip(char)
        assert back.get(s.neutral) == s.low, (game, s.neutral)
        assert rep.warnings == []


@pytest.mark.parametrize("game", doswidths.GAMES)
def test_f_the_two_sides_exhaust_the_scalars(game):
    """Every swept scalar is a refused multi-byte field, a wrapped `I8` or a
    clamped `U8` -- by the layout's own kind, so a field that changes width
    or kind is caught by the names above no longer agreeing with it."""
    table = dos_port.FIELDS_BY_NAME_FOR[game]
    names = {s.neutral for s in doswidths.scalars(game)
             if s.neutral not in doswidths.ALWAYS_RECOMPUTED}
    assert set(_REFUSED[game]) <= names
    swept = {s.neutral: s for s in doswidths.scalars(game)}
    assert {n: swept[n].size for n in _REFUSED[game]} == _REFUSED[game]
    for s in doswidths.scalars(game):
        if s.neutral in doswidths.ALWAYS_RECOMPUTED:
            continue
        kind = table[s.dos].kind
        want = ("refused" if s.size > 1 else
                "wrapped" if kind is layout.Kind.I8 else "clamped")
        assert _side(game, s) == want, (game, s.neutral, kind, s.size)
    assert _WRAPPED <= names


def test_f_a_wrapped_thief_column_is_unreachable_from_any_source():
    """The `I8` wrap needs a source that can hold 128 in a thief column, and
    every reader hands the column back as a signed byte too: the C64 record's
    and every DOS title's are `I8`, so the value cannot exist."""
    assert {layout.FIELDS_BY_NAME[n].kind for n in _WRAPPED} == {layout.Kind.I8}
    for game in doswidths.GAMES:
        table = dos_port.FIELDS_BY_NAME_FOR[game]
        assert {table[n].kind for n in _WRAPPED} == {layout.Kind.I8}, game


# --- G: the only field wider in the C64 than in DOS is hit points ------------

#: The scalars whose C64 field is wider than the DOS one they convert into,
#: and nothing else -- the mirror of `test_boundary_c64.py`'s own list, where
#: DOS is the wider side.  The C64 keeps hit points in two bytes and every
#: paired DOS title in one.  A third entry fails the test.
_C64_WIDER = {(game, name) for game in (POOL, CURSE, SILVER)
              for name in ("hp_max", "hp_current")}


def test_g_only_hit_points_are_wider_in_the_c64_than_in_dos():
    c64_names = dict(c64_codec.DIRECT)
    wider = set()
    compared = 0
    for game in c64_codec.DELTAS_BY_KEY:
        table = dos_port.FIELDS_BY_NAME_FOR[game]
        for neutral, dos_name in dos_codec.WRITE_DIRECT:
            c64_field = layout.FIELDS_BY_NAME.get(c64_names.get(neutral))
            dos_field = table.get(dos_name)
            if c64_field is None or dos_field is None:
                continue
            c64_span = doswidths.boundarywidths.value_range(
                c64_field.kind, c64_field.size)
            dos_span = doswidths.boundarywidths.value_range(
                dos_field.kind, dos_field.size)
            if c64_span is None or dos_span is None:
                continue
            if not (dos_span[0] <= c64_span[0] and c64_span[1] <= dos_span[1]):
                wider.add((game, neutral))
            compared += 1
    assert compared > 100
    assert wider == _C64_WIDER


@pytest.mark.parametrize("game", [POOL, CURSE, SILVER])
@pytest.mark.parametrize("value", [256, 300, 0xFFFF])
@pytest.mark.parametrize("name", ["hp_max", "hp_current"])
def test_g_a_hit_point_total_the_c64_holds_is_clamped_and_reported(
        game, name, value):
    char = doswidths.base(game)
    char.set(name, value, "boundary: a C64 two-byte total")
    back, rep = _round_trip(char)
    assert back.get(name) == 255, (game, name, value)
    assert f"{name}: {value} does not fit the DOS one-byte field; clamped" \
        in rep.warnings


# --- H: every legal Curse and Silver Blades character, C64 to DOS ------------

_COMBINATIONS = [c for game in laterchars.GAMES
                 for c in laterchars.combinations(game)]


def _held(back) -> dict:
    return {k: v for k, v in (back.get("levels") or {}).items() if v}


def _later_holds(char, combo, caplog):
    with caplog.at_level(logging.WARNING, logger="wish.goldbox.dos_codec"):
        back, rep = _round_trip(doswidths.c64_sourced(char))
    assert rep.warnings == [] and rep.dropped == [], (combo.name, rep.dropped)
    assert _warnings(caplog) == [], combo.name
    # A dual-classed character who has regained his old class carries both in
    # the source's level array; DOS never stores that, so the old slot stays
    # zero and the class he left comes back as `former_levels` (#408).
    held = {k: v for k, v in combo.class_levels.items()
            if k not in combo.former_levels}
    assert _held(back) == held, (combo.name, _held(back))
    assert (back.get("former_levels") or {}) == combo.former_levels, combo.name
    assert back.get("class_bits") == combo.bits, combo.name
    assert back.get("race") == combo.race, combo.name
    return back


@pytest.mark.parametrize("combo", _COMBINATIONS,
                         ids=lambda c: f"{c.game}-{c.name}")
def test_h_every_class_combination_the_later_menus_offer_writes_to_dos(
        combo, caplog):
    _later_holds(laterchars.build(combo), combo, caplog)


def test_h_the_sweep_is_the_129_the_c64_sweep_runs():
    assert {g: sum(1 for c in _COMBINATIONS if c.game == g)
            for g in laterchars.GAMES} == {
        CURSE: 64, SILVER: 65}


def _caster_combo(game):
    char = laterchars.caster(game)
    levels = {k: v for k, v in char.get("levels").items() if v}
    return char, levels


@pytest.mark.parametrize("game", laterchars.GAMES)
def test_h_the_deepest_later_caster_memorises_his_whole_list(game, caplog):
    char, levels = _caster_combo(game)
    levels = {k: v for k, v in levels.items()
              if k not in char.get("former_levels")}
    wanted = laterchars.DEEPEST[game]["memorised"]
    with caplog.at_level(logging.WARNING, logger="wish.goldbox.dos_codec"):
        back, rep = _round_trip(doswidths.c64_sourced(char))
    assert rep.warnings == [] and rep.dropped == [], (game, rep.dropped)
    assert _warnings(caplog) == [], game
    assert _held(back) == levels
    assert back.get("spells_memorised") == list(range(1, wanted + 1))
    allotted = dos_port.FIELDS_BY_NAME_FOR[game]["spells_memorised"].size
    assert wanted < allotted, (game, wanted, allotted)


def _narrowed(game: str, slots: int) -> dos_port.DosDeltas:
    """`game`'s table with `slots` memorised-list bytes and the rest of the
    field's width left as an unnamed run after it, so the record still adds
    up to its size -- the same override part D uses for Pool of Radiance."""
    deltas = dos_port.deltas_for(game)
    was = deltas.sizes["spells_memorised"]
    return dataclasses.replace(
        deltas, sizes={**deltas.sizes, "spells_memorised": slots},
        inserts={**deltas.inserts, "spells_memorised": was - slots})


@pytest.mark.parametrize("game", laterchars.GAMES)
def test_h_the_sweep_reports_a_memorised_list_narrower_than_the_engines(
        game, monkeypatch, caplog):
    """The red proof: a table that gives the list fewer slots than the deepest
    caster memorises loses the rest, and the round trip says so."""
    wanted = laterchars.DEEPEST[game]["memorised"]
    monkeypatch.setitem(
        dos_port.FIELDS_BY_NAME_FOR, game,
        {f.name: f for f in dos_port.layout_for(_narrowed(game, wanted - 8))})
    char, _ = _caster_combo(game)
    with caplog.at_level(logging.WARNING, logger="wish.goldbox.dos_codec"):
        back, _ = _round_trip(doswidths.c64_sourced(char))
    assert len(back.get("spells_memorised")) == wanted - 8
    assert any(f"spells_memorised: {wanted} ids" in m
               for m in _warnings(caplog))


# --- I: the C64's item block is never handed a wrong-length item -------------

@pytest.mark.parametrize("size", sorted({s.item_size
                                         for s in dos_codec.DELTAS}))
@pytest.mark.parametrize("fill", [0x00, 0x55, 0xFF])
def test_i_a_dos_item_becomes_exactly_sixteen_bytes(size, fill):
    """`c64_codec.write` copies each inventory item into a 16-byte slot with a
    slice assignment, so two items of 17 and 15 bytes would cancel to 256 and
    shift every later boundary without an error.  The two builders that turn a
    DOS item into a C64 one -- `DosItem.to_c64` and `item_to_c64`, which
    `amiga_later` and `amiga_pod` also call -- return a tuple of sixteen byte
    values or refuse, so the case is not reachable through either."""
    data = bytearray([fill]) * size
    at, width = dos_codec.ITEM_TAIL
    for i in range(at, min(at + width, size)):
        data[i] = 0
    assert len(dos_codec.item_to_c64(bytes(data))) == c64_codec.ITEM_SIZE == 16
    assert len(dos_codec.DosItem(bytes(data), size).to_c64()) == 16


@pytest.mark.parametrize("length", [0, 15, 16, 62, 64, 66, 68, 130])
def test_i_a_dos_item_of_any_other_length_is_refused(length):
    with pytest.raises(dos_codec.DosRecordError):
        dos_codec.item_to_c64(bytes(length))


def test_i_a_nonzero_item_tail_is_refused_not_dropped():
    data = bytearray(67)
    data[dos_codec.ITEM_TAIL[0]] = 1
    with pytest.raises(dos_codec.DosRecordError):
        dos_codec.item_to_c64(bytes(data))
