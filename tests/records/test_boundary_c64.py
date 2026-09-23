from __future__ import annotations

"""Boundary characters through the C64 writer: `#516 (Generate boundary
characters and check every writer's field widths, since no real save reaches a
limit and the corpus cannot find a wrong one)`, steps 4 and 5.

`tests/records/test_boundary.py` runs four Pool of Radiance extremes through
`goldbox.dos_codec.write`.  This module does the same into
`goldbox.c64_codec.write`, where the widths are the C64 record's own, and adds
two sweeps the DOS side did not need: every scalar the writer copies, at its
lowest, its highest and one past (parts C to H), and every class combination
Curse of the Azure Bonds' and Secret of the Silver Blades' own menus offer,
including what their dual-class route leaves (parts I to K).  The rule for a
value past a width is that the writer refuses it or writes exactly what fits
-- never a neighbour's byte, never a wrapped number.
`tools/records/boundarywidths.py` and `tools/records/laterchars.py` build the
characters; nothing here reads a game file except the disk-backed checks of
the memorised-spell width and the two later titles' own creation tables, which
skip without the disks.
"""

import logging

import pytest

from goldbox import (
    c64_codec,
    classcode,
    dos_codec,
    dos_port,
    effects,
    layout,
    spells,
    traits,
)
from goldbox import items as items_mod
from goldbox import levels as level_tables
from tools.records import boundarychars, boundarywidths, laterchars, laterlegality

GAMES = boundarywidths.GAMES
POOL = "pool-of-radiance"

#: The one drop line an ordinary DOS character produces: no combat art of its
#: own converts to the C64's character-set icon.  Anything else is a loss.
_ICON = "Combat icon:"

#: The drop line for a running effect a later title has no rule for.
_RUNNING = "running_effects:"

def _write(char):
    """`(record, report, back)`: the character written and read straight back."""
    rec, rep = c64_codec.write(char, payload=bytearray(0x1C00), party_slot=0,
                               clock_minutes=0)
    if getattr(char.game, "key", char.game) != POOL:
        # Curse and Silver Blades have no `effects.c64_row` rule yet, so each
        # running effect is an accounted drop. Step 3 of the running-effect
        # work adds their ids and removes this exemption; Pool of Radiance has
        # none.
        rep.dropped = [d for d in rep.dropped if not d.startswith(_RUNNING)]
    return rec, rep, c64_codec.read(rec, game=char.game)


def _losses(rep):
    return [d for d in rep.dropped if not d.startswith(_ICON)]


def _changed(a, b):
    """Offsets where two records differ."""
    ra, rb = a.to_bytes(), b.to_bytes()
    return [i for i in range(len(ra)) if ra[i] != rb[i]]


def _no_warnings(caplog):
    return [r.getMessage() for r in caplog.records
            if r.levelno >= logging.WARNING]


# --- A: the four reachable extremes, as a DOS record hands them over --------

#: Named because the writer works them out again for a title that has a table
#: for them, so a round trip against the source's value is the wrong check.
#: Saves and the two THAC0 bytes are `boundarywidths.recomputed_on_write`;
#: `tests/convert/test_c64thac0.py` and `tests/convert/test_neutral.py` check
#: what they are recomputed to.
_THIEF_COLUMNS = tuple(n for n, _ in c64_codec._THIEF_SKILL_COLUMNS)

#: A case field the reader has no neutral name for on the way back:
#: `granted_effects` shares its trait slots with the racial ids, so `read`
#: hands both back as `innate_effects` (`goldbox/c64_codec.py`, the trait-slot
#: block of `write`).  `running_effects` lives in the save's shared arrays,
#: which `read` is not given a payload for here.  `icon_head`, `icon_body`
#: and `icon_colours` have no C64 byte of their own at all -- the C64's own
#: combat figure is eighteen screen codes and eighteen colours in the save's
#: own table, not a field of the character record, so `read` has nothing to
#: hand back under these three names (see `TRANSFORMED`'s own entry).
_NOT_READ_BACK = {"granted_effects", "running_effects",
                  "icon_head", "icon_body", "icon_colours"}


@pytest.mark.parametrize("name", sorted(boundarychars.CASES))
def test_a_reachable_character_writes_to_the_c64_and_reads_back_whole(
        name, caplog):
    char = boundarywidths.case(name)
    with caplog.at_level(logging.WARNING, logger="wish.goldbox"):
        _, rep, back = _write(char)

    assert rep.warnings == [], (name, rep.warnings)
    assert _losses(rep) == [], (name, _losses(rep))
    assert rep.losses == [], (name, rep.losses)
    assert _no_warnings(caplog) == [], name
    assert set(char.keys()) - set(back.keys()) == _NOT_READ_BACK

    recomputed = set(boundarywidths.recomputed_on_write(POOL))
    thief = char.get("levels", {}).get("thief", 0)
    if thief and level_tables.thief_skill_race_differs_by_port(POOL):
        recomputed |= set(_THIEF_COLUMNS)
        wanted = level_tables.thief_skills(
            thief, char.get("race"), POOL, dexterity=char.get("dexterity"))
        assert [back.get(n) for n in _THIEF_COLUMNS] == list(wanted), name
        assert all(-128 <= v <= 127 for v in wanted), (name, wanted)

    for field in char.keys():
        if field in recomputed or field in _NOT_READ_BACK:
            continue
        want, got = char.get(field), back.get(field)
        if field == "levels":
            got = {k: v for k, v in got.items() if v}
        elif field == "spells_castable":
            want = {k: want.get(k, (0, 0, 0)) for k in ("cleric",
                                                        "magic-user")}
        elif field == "innate_effects":
            granted = [n[0] for n in char.get("granted_effects", [])]
            want, got = sorted(want + granted), sorted(got)
        assert got == want, (name, field, want, got)


def test_a_running_effect_is_written_as_a_row_and_reported_nowhere():
    """The caster's two Blesses become rows 63 and 62 of the shared arrays,
    with no line on any list."""
    char = boundarywidths.case("caster")
    assert char.get("running_effects"), "the boundary caster carries none"
    payload = bytearray(0x1C00)
    _, rep = c64_codec.write(char, payload=payload, party_slot=0,
                             clock_minutes=0)
    assert rep.dropped == [d for d in rep.dropped if d.startswith(_ICON)]
    assert rep.warnings == []
    assert rep.losses == []
    rows = [(payload[effects.EFFECT_ID_OFFSET + i],
             payload[effects.EFFECT_OWNER_OFFSET + i],
             payload[effects.EFFECT_DURATION_OFFSET + i],
             payload[effects.EFFECT_MAGNITUDE_OFFSET + i])
            for i in (63, 62)]
    assert rows == [(1, 0, 0xEE, 0x01), (1, 0, 0x01, 0x01)]


def test_a_bare_write_reports_the_combat_icon_fields_by_name():
    """`write(char)`, no `icon=` supplied: `icon_head`, `icon_body` and
    `icon_colours` are dropped under the "Combat icon" heading, by name, not
    under `Writer.finish`'s generic "the C64 conversion takes nothing from
    it" -- the sentence a field gets when nothing in `write` ever calls
    `use()` on it, which is what happens when `write` marks the three taken
    without composing a figure from them (#612)."""
    char = boundarywidths.case("warrior")
    assert char.get("icon_head") is not None, "the boundary base sets one"
    _, rep, _ = _write(char)
    icon_lines = [d for d in rep.dropped if d.startswith("Combat icon")]
    for field in ("icon_head", "icon_body", "icon_colours"):
        assert any(field in line for line in icon_lines), (field, rep.dropped)
    assert not any(f"{field}: the neutral record carries it" in d
                  for field in ("icon_head", "icon_body", "icon_colours")
                  for d in rep.dropped), rep.dropped


# --- B: every field the writer takes has a boundary -------------------------

def _copied_or_transformed():
    d = c64_codec.field_disposition()
    return {n for n, why in d.items()
            if not why.startswith(("dropped:", "derived:", "constant:"))}


def test_b_every_field_the_c64_writer_takes_has_a_boundary():
    """The hook into `field_disposition()`: a field added to the writer with no
    scalar range and no row in `boundarywidths.STRUCTURED` fails here."""
    covered = {s.neutral for s in boundarywidths.scalars()} \
        | set(boundarywidths.STRUCTURED)
    assert _copied_or_transformed() - covered == set()


def test_b_no_boundary_row_names_a_field_the_writer_has_lost():
    every = set(c64_codec.field_disposition())
    stale = set(boundarywidths.STRUCTURED) - every
    assert stale == set()


# --- C: every scalar at its lowest and highest, every title -----------------

@pytest.mark.parametrize("high", [False, True], ids=["lowest", "highest"])
@pytest.mark.parametrize("game", GAMES)
def test_c_every_scalar_at_its_extreme_round_trips(game, high, caplog):
    char = boundarywidths.at_extreme(game, high)
    with caplog.at_level(logging.WARNING, logger="wish.goldbox"):
        _, rep, back = _write(char)
    assert rep.warnings == [] and _losses(rep) == [], (game, rep.dropped)
    assert rep.losses == [], (game, rep.losses)
    assert _no_warnings(caplog) == []

    skipped = boundarywidths.recomputed_on_write(game, char.get("levels"))
    checked = 0
    for s in boundarywidths.scalars():
        if s.neutral in skipped:
            continue
        want = s.high if high else s.low
        assert back.get(s.neutral) == want, (game, s.neutral, want,
                                             back.get(s.neutral))
        checked += 1
    top = 255 if high else 0
    assert back.get("levels") == {n: top for n in c64_codec.LEVEL_FIELDS}
    # A sweep that skipped most of the scalars would pass by not looking.
    assert checked == len(boundarywidths.scalars()) - len(
        skipped.keys() & {s.neutral for s in boundarywidths.scalars()})
    assert checked > len(boundarywidths.scalars()) // 2


# --- D: one past a scalar is refused ----------------------------------------

@pytest.mark.parametrize("scalar", boundarywidths.scalars(),
                         ids=lambda s: s.neutral)
def test_d_one_past_a_scalar_is_refused_not_wrapped(scalar):
    """A value one past the field's own width has to raise, naming the field,
    in every title -- a `& 0xFF` here would write a different number.  Bar
    experience above its width, which is clamped instead."""
    for game in GAMES:
        if scalar.neutral in boundarywidths.recomputed_on_write(game):
            continue
        for past in (scalar.high + 1, scalar.low - 1):
            if scalar.neutral == "experience" and past > scalar.high:
                # Clamped, not refused: `test_xpceiling.py` has the clamp.
                # Below zero is still refused, and stays in this loop.
                continue
            char = boundarywidths.base(game)
            char.set(scalar.neutral, past, "boundary: one past")
            with pytest.raises(ValueError, match=scalar.c64):
                c64_codec.write(char)


def test_d_one_past_a_class_level_is_refused():
    for game in GAMES:
        char = boundarywidths.base(game)
        char.set("levels", {"fighter": 256}, "boundary: one past")
        with pytest.raises(ValueError, match="level_fighter"):
            c64_codec.write(char)


# --- E: the arrays, the name and the fixed-width blocks ---------------------

@pytest.mark.parametrize("game", GAMES)
def test_e_the_name_holds_its_width_and_refuses_one_more(game):
    width = boundarywidths.NAME_WIDTH
    for length in (0, 1, width):
        char = boundarywidths.base(game)
        char.set("name", "A" * length, "boundary")
        _, _, back = _write(char)
        assert back.get("name") == "A" * length, (game, length)
    char = boundarywidths.base(game)
    char.set("name", "A" * (width + 1), "boundary: one past")
    with pytest.raises(ValueError, match="name"):
        c64_codec.write(char)


def _array_case(game, field, ids_or_items, span):
    """`(record, back)` for `ids_or_items`, and every offset that differs from
    the same character with the field empty -- which must stay inside `span`,
    the field's own bytes."""
    char = boundarywidths.base(game)
    char.set(field, ids_or_items, "boundary")
    rec, _, back = _write(char)
    empty = boundarywidths.base(game)
    empty.set(field, [], "boundary: empty")
    rec_empty, _, _ = _write(empty)
    lo, hi = span
    strays = [i for i in _changed(rec, rec_empty) if not lo <= i < hi]
    assert strays == [], (game, field, strays)
    return rec, back


@pytest.mark.parametrize("game", GAMES)
def test_e_memorised_spells_fill_the_engines_width_and_stop(game):
    ceiling = boundarywidths.ceilings(game).memorised
    at, size = c64_codec.memorised_span(game)
    assert size == ceiling, (game, "the writer's row is not the engine's")

    ids = list(range(1, ceiling + 1))
    rec_full, back = _array_case(game, "spells_memorised", ids, (at, at + size))
    assert back.get("spells_memorised") == ids

    # One past, and far past: the same record, nothing in the next field.
    for count in (ceiling + 1, ceiling + 40):
        rec_over, back = _array_case(
            game, "spells_memorised", list(range(1, count + 1)),
            (at, at + size))
        assert rec_over == rec_full, (game, count)
        assert back.get("spells_memorised") == ids


@pytest.mark.parametrize("game", GAMES)
def test_e_a_spell_id_past_a_byte_is_refused(game):
    char = boundarywidths.base(game)
    char.set("spells_memorised", [256], "boundary: one past")
    with pytest.raises(ValueError):
        c64_codec.write(char)
    char.set("spells_memorised", [255], "boundary")
    assert _write(char)[2].get("spells_memorised") == [255]


@pytest.mark.parametrize("game", GAMES)
def test_e_the_spellbook_holds_every_id_its_mask_has_a_bit_for(game):
    top = boundarywidths.ceilings(game).spellbook
    at = layout.FIELDS_BY_NAME["spells_known"].offset
    size = spells.for_game(game).spellbook_size
    ids = list(range(1, top + 1))
    rec_full, back = _array_case(game, "spells_known", ids, (at, at + size))
    assert back.get("spells_known") == ids
    rec_over, back = _array_case(game, "spells_known", ids + [top + 1, top + 9],
                                 (at, at + size))
    assert rec_over == rec_full
    assert back.get("spells_known") == ids


@pytest.mark.parametrize("game", GAMES)
def test_e_sixteen_items_fit_and_a_seventeenth_changes_nothing(game):
    slots = boundarywidths.ceilings(game).items
    inv = layout.FIELDS_BY_NAME["inventory"]
    assert inv.size == slots * items_mod.ITEM_SIZE

    def items(n):
        return [boundarychars._item(weight_tenths=10 + i) for i in range(n)]

    rec_full, back = _array_case(game, "inventory", items(slots),
                                 (inv.offset, inv.end))
    assert back.get("inventory") == items(slots)
    for n in (slots + 1, slots + 20):
        rec_over, back = _array_case(game, "inventory", items(n),
                                     (inv.offset, inv.end))
        assert rec_over == rec_full, (game, n)
        assert back.get("inventory") == items(slots)


#: `(racial ids, item grants)` at, and one past, the ten trait slots.
_TRAIT_MIXES = [(10, 0), (11, 0), (4, 6), (4, 7), (0, 10), (0, 11), (10, 1)]


@pytest.mark.parametrize("game", GAMES)
@pytest.mark.parametrize("racial,grants", _TRAIT_MIXES)
def test_e_ten_trait_slots_are_shared_and_never_overrun(game, racial, grants):
    slots = boundarywidths.ceilings(game).traits
    first = traits.FIRST
    innate = list(range(1, racial + 1))
    granted = [boundarychars._effect(100 + i) for i in range(grants)]
    char = boundarywidths.base(game)
    char.set("innate_effects", innate, "boundary")
    char.set("granted_effects", granted, "boundary")
    rec, _, back = _write(char)

    kept = innate[:slots]
    room = slots - len(kept)
    expected = sorted(kept + [g[0] for g in granted][:room])
    assert sorted(back.get("innate_effects")) == expected, (game, racial,
                                                            grants)

    empty = boundarywidths.base(game)
    empty.set("innate_effects", [], "boundary: empty")
    empty.set("granted_effects", [], "boundary: empty")
    rec_empty, _, _ = _write(empty)
    strays = [i for i in _changed(rec, rec_empty)
              if not first <= i < first + slots]
    assert strays == [], (game, racial, grants, strays)


@pytest.mark.parametrize("game", GAMES)
def test_e_a_trait_id_past_a_byte_is_refused(game):
    char = boundarywidths.base(game)
    char.set("innate_effects", [256], "boundary: one past")
    with pytest.raises(ValueError):
        c64_codec.write(char)


@pytest.mark.parametrize("field,width", [("attack_forms", 8),
                                         ("roster_tail", 9)])
def test_e_a_fixed_width_block_takes_exactly_its_width(field, width):
    """Eight bytes and nine: one short or one long is refused rather than
    written into the field beside it."""
    for game in GAMES:
        for n in (width, width - 1, width + 1):
            char = boundarywidths.base(game)
            char.set(field, bytes(range(1, n + 1)), "boundary")
            if n == width:
                assert _write(char)[2].get(field) == bytes(range(1, n + 1))
            else:
                with pytest.raises(ValueError, match=field):
                    c64_codec.write(char)


@pytest.mark.parametrize("game", GAMES)
def test_e_a_treasure_share_is_kept_to_the_bits_the_c64_masks(game):
    """0 to 3 cross; a value with bit 2 set is refused rather than masked
    into a different share (`docs/195-three-dos-record-bytes-named-from-the-
    overlays.md`)."""
    for share in (0, 1, 2, 3):
        char = boundarywidths.base(game)
        char.set("treasure_share", share, "boundary")
        assert _write(char)[2].get("treasure_share") == share
    for share in (4, 7, 255):
        char = boundarywidths.base(game)
        char.set("treasure_share", share, "boundary: bit 2 set")
        with pytest.raises(ValueError, match="bit 2"):
            c64_codec.write(char)


@pytest.mark.parametrize("game", GAMES)
def test_e_a_portrait_byte_and_the_size_byte_hold_a_byte_and_no_more(game):
    for field in ("portrait_head", "portrait_body", "size_small"):
        for ok in (0 if field != "portrait_body" else 1, 255):
            char = boundarywidths.base(game)
            char.set(field, ok, "boundary")
            assert _write(char)[2].get(field) == ok, (game, field, ok)
        char = boundarywidths.base(game)
        char.set(field, 256, "boundary: one past")
        with pytest.raises(ValueError, match=field):
            c64_codec.write(char)


# --- F: the engine's own memorised width, off the player's disks ------------

@pytest.mark.parametrize("game", GAMES)
def test_f_the_engine_agrees_on_the_memorised_width(game):
    """`tools/c64/memorisedwidth.py`'s reading of the title's own `CAMP` -- the
    count-down immediate, plus one -- against `boundarywidths.ENGINE_MEMORISED`
    and the writer's row.  Skips without that title's disks."""
    from tools.c64 import coldread, memorisedwidth
    title = memorisedwidth.by_key(game)
    try:
        camp = coldread.overlay(title, b"CAMP", None)
    except SystemExit as exc:
        pytest.skip(f"needs the {game} C64 disks: {exc}")
    found = memorisedwidth.accesses(camp, coldread.staging(title) >> 8)
    offset, sites = max(found.items(), key=lambda kv: len(kv[1]))
    seeds = {s for *_, s in sites if s is not None}
    assert len(seeds) == 1, (game, seeds)
    at, size = c64_codec.memorised_span(game)
    assert offset == at, (game, offset, at)
    assert seeds.pop() + 1 == size == boundarywidths.ENGINE_MEMORISED[game]


# --- G: no DOS field is wider than the C64 field it converts into -----------

#: The DOS scalars wider than the C64 field they convert into, and nothing
#: else: Pool of Radiance, Curse of the Azure Bonds and Secret of the Silver
#: Blades keep experience in four bytes where the C64 record has three, so a
#: value from 16,777,216 up is clamped to 16,777,215 by `c64_codec.write`
#: (`test_xpceiling.py`).  No DOS engine caps the running total, so the
#: value is reachable by play alone (#597).
_DOS_WIDER = {("pool-of-radiance", "experience"),
              ("curse-of-the-azure-bonds", "experience"),
              ("secret-of-the-silver-blades", "experience")}


def test_g_only_experience_is_wider_in_dos_than_in_the_c64():
    """The refusals in test D are only reachable from a source that can hold a
    value the C64 cannot.  Every neutral scalar both writers name has a DOS
    range inside the C64's, bar the exceptions named above (the Amiga's record
    is the DOS record re-cut, so it adds none) -- and this fails the day one
    more appears or one goes."""
    dos_names = dict(dos_codec.DIRECT)
    compared = 0
    wider = set()
    for game in GAMES:
        table = dos_port.FIELDS_BY_NAME_FOR[game]
        for s in boundarywidths.scalars():
            dos_field = table.get(dos_names.get(s.neutral))
            if dos_field is None:
                continue
            span = boundarywidths.value_range(dos_field.kind, dos_field.size)
            if span is None:
                continue
            if not (s.low <= span[0] and span[1] <= s.high):
                wider.add((game, s.neutral))
            compared += 1
    assert compared > 100
    assert wider == _DOS_WIDER


# --- H: the harness can fail ------------------------------------------------

def test_h_the_harness_reports_a_memorised_list_narrower_than_the_engines(
        monkeypatch):
    """Narrow Pool of Radiance's writer row to the 69 bytes the layout declares
    for the field on its own, as it stood before `#268 (A character with more
    than sixteen memorised spells loses the rest, because the layout gives the
    list sixteen bytes and the game gives it eighty-one)`: the round trip
    loses twelve ids and the width check names the mismatch."""
    import dataclasses
    narrow = dataclasses.replace(c64_codec.POOL_OF_RADIANCE_RECORD,
                                 memorised=("spells_memorised",))
    monkeypatch.setitem(c64_codec.DELTAS_BY_KEY, POOL, narrow)
    ceiling = boundarywidths.ceilings(POOL).memorised
    char = boundarywidths.base(POOL)
    char.set("spells_memorised", list(range(1, ceiling + 1)), "boundary")
    _, _, back = _write(char)
    assert len(back.get("spells_memorised")) == 69 < ceiling
    assert c64_codec.memorised_span(POOL)[1] != ceiling


# --- I: every class Curse and Silver Blades can legally make -----------------

#: Both titles' combinations, flattened, so one parametrisation covers them.
_COMBINATIONS = [c for game in laterchars.GAMES
                 for c in laterchars.combinations(game)]


def _combination_holds(combo):
    """Write `combo` and check the classes come back as the menus offered them.

    The class bitmask and the level array have to agree, which is what ties
    the creation menu's own legality table to `goldbox/levels.py`'s racial
    limits: a race offered a class it may not advance in comes out with a bit
    set and no level under it.  `char_class` is asserted only where the
    title's table has a code -- eight of the fifteen pairs the dual-class
    route can leave have none, and `#409 (A regained dual-classed paladin or
    ranger has a class mask Curse's own table cannot name, so Wish shows him
    a class he is not)` settled that Wish writes nothing for those.
    """
    char = laterchars.build(combo)
    _, rep, back = _write(char)
    assert rep.warnings == [] and _losses(rep) == [], (combo.name, rep.dropped)
    assert rep.losses == [], (combo.name, rep.losses)

    held = {name: level for name, level in (back.get("levels") or {}).items()
            if level}
    assert held == combo.class_levels, (combo.name, held)
    assert held, combo.name
    for name in laterlegality.class_names(combo.bits):
        assert combo.class_levels.get(name), (combo.name, name)
    assert back.get("class_bits") == combo.bits, combo.name
    assert (back.get("former_levels") or {}) == combo.former_levels, combo.name
    code = classcode.code_for(combo.bits, combo.class_levels,
                              combo.former_levels, combo.game)
    if code is not None:
        assert back.get("char_class") == code, (combo.name, code)


@pytest.mark.parametrize("combo", _COMBINATIONS,
                         ids=lambda c: f"{c.game}-{c.name}")
def test_i_every_class_combination_the_later_menus_offer_round_trips(combo):
    """The class-legality sweep: every race and class entry Curse's and Silver
    Blades' own creation menus offer, and every pair their dual-class route can
    leave, at each class's own ceiling (`tools/records/laterlegality.py`)."""
    _combination_holds(combo)


def test_i_the_sweep_catches_a_class_the_race_may_not_advance_in():
    """The red proof for the class half: a legality row the game does not
    carry -- Curse's dwarf offered cleric/magic-user, which no dwarf may
    train -- builds a character whose mask names two classes his racial
    limits give him no level in, and the sweep says so."""
    game = "curse-of-the-azure-bonds"
    dwarf = [code for code, name in laterlegality.races(game)
             if name == "dwarf"][0]
    bits = (classcode.CLASS_BIT_FOR_NAME["cleric"]
            | classcode.CLASS_BIT_FOR_NAME["magic-user"])
    wrong = laterchars.Combination(
        game, dwarf, "dwarf", bits,
        tuple(sorted(laterlegality.at_their_ceilings(game, dwarf,
                                                     bits).items())),
        (), "creation")
    with pytest.raises(AssertionError):
        _combination_holds(wrong)


# --- J: the deepest caster either later title can reach ----------------------

def _caster_holds(game, memorised):
    """Write the deepest caster with `memorised` ids and hand back what
    came off the record.  `losses` is empty unless the list is past the
    title's slots."""
    char = laterchars.caster(game)
    char.set("spells_memorised", list(range(1, memorised + 1)), "boundary")
    _, rep, back = _write(char)
    assert rep.warnings == [] and _losses(rep) == [], (game, rep.dropped)
    assert bool(rep.losses) == (memorised > c64_codec.memorised_span(game)[1]), (
        game, rep.losses)
    return back


@pytest.mark.parametrize("game", laterchars.GAMES)
def test_j_the_deepest_later_caster_memorises_his_whole_capacity(game, caplog):
    """A dual-classed human holds two spell lists at once, which is the most
    either title can reach: Curse 40 of the 69 slots its own `CAMP` walks,
    Silver Blades 64 of 74.  Neither reaches its record's list, so the DOS
    record being wider than the C64's in both titles is unreachable rather
    than a loss."""
    wanted = laterchars.DEEPEST[game]["memorised"]
    _, width = c64_codec.memorised_span(game)
    assert wanted < width, (game, wanted, width)
    with caplog.at_level(logging.WARNING, logger="wish.goldbox"):
        back = _caster_holds(game, wanted)
    assert _no_warnings(caplog) == [], game
    assert back.get("spells_memorised") == list(range(1, wanted + 1))
    top = spells.for_game(game).last_spellbook_spell
    assert back.get("spells_known") == list(range(1, top + 1))


@pytest.mark.parametrize("game", laterchars.GAMES)
def test_j_the_sweep_catches_a_ceiling_row_above_the_games_own(game):
    """The red proof for the ceiling half: a class ceiling above the title's
    own gives the caster more spells than the record's list has room for, and
    the round trip comes back short rather than quietly wrapping."""
    _, width = c64_codec.memorised_span(game)
    back = _caster_holds(game, width + 1)
    assert back.get("spells_memorised") == list(range(1, width + 1))


# --- K: the tables the last two tests rest on are the game's own -------------

@pytest.mark.parametrize("game", laterchars.GAMES)
def test_k_the_later_creation_tables_are_the_games_own(game):
    """`laterlegality.READ_ON_DISK` against the title's own overlays, found by
    the menu builder's own operands.  Skips without that title's disks."""
    try:
        read = laterlegality.read_tables(game)
    except SystemExit as exc:
        pytest.skip(f"needs the {game} C64 disks: {exc}")
    kept = laterlegality.READ_ON_DISK[game]
    for field in ("legality_at", "class_bits_at", "race_bits_at",
                  "race_bits_in", "codes", "alignment_at", "legality",
                  "class_bits", "race_bits"):
        assert read[field] == kept[field], (game, field)
    assert read["alignment"] == laterlegality.ALIGNMENT_MASKS, game


@pytest.mark.parametrize("game", laterchars.GAMES)
def test_k_the_deepest_caster_is_the_one_the_engine_allows(game):
    """`laterchars.DEEPEST` re-derived from the game: every creation entry at
    its ceilings and every dual-class route, measured by how many spells each
    may hold.  Silver Blades' slot rows are read out of its own `ECL65`,
    independently of the ones `goldbox/spells.py` holds for it."""
    try:
        rows = (laterlegality.silver_slot_rows()
                if game == "secret-of-the-silver-blades" else None)
        total, held, former = laterlegality.deepest_caster(game, rows=rows)
    except SystemExit as exc:
        pytest.skip(f"needs the {game} C64 disks: {exc}")
    kept = laterchars.DEEPEST[game]
    assert (total, held, former) == (kept["memorised"], kept["levels"],
                                     kept["former"]), game


# --- L: every value the writer narrows is on `losses` ------------------------

def _lost(char):
    """`(report, caplog-free warnings)` for `char` written to the C64."""
    _, rep, _ = _write(char)
    return rep


@pytest.mark.parametrize("game", GAMES)
@pytest.mark.parametrize("value", [0x1000000, 0x7FFFFFFF])
def test_l_experience_past_three_bytes_is_a_loss_and_a_warning(game, value):
    char = boundarywidths.base(game)
    char.set("experience", value, "boundary: one past")
    rep = _lost(char)
    line = (f"experience: DOS holds {value}, which does not fit the C64's 3 "
            f"bytes; written as 16777215, the most they hold")
    assert rep.losses == [line], (game, rep.losses)
    assert line in rep.warnings
    assert line not in rep.dropped


@pytest.mark.parametrize("game", GAMES)
def test_l_a_memorised_list_past_the_titles_slots_is_on_losses_and_no_sentence(
        game):
    """Donald's ruling is that no sentence reaches a player for it, so the line
    is accounting only: `warnings` stays empty."""
    _, size = c64_codec.memorised_span(game)
    char = boundarywidths.base(game)
    char.set("spells_memorised", list(range(1, size + 4)), "boundary: one past")
    rep = _lost(char)
    assert rep.losses == [f"spells_memorised: 3 ids past the {size} slots "
                          f"this title's C64 record holds"], (game, rep.losses)
    assert rep.warnings == []


@pytest.mark.parametrize("game", GAMES)
def test_l_a_full_memorised_list_is_not_a_loss(game):
    _, size = c64_codec.memorised_span(game)
    char = boundarywidths.base(game)
    char.set("spells_memorised", list(range(1, size + 1)), "boundary")
    assert _lost(char).losses == []


@pytest.mark.parametrize("game", GAMES)
def test_l_more_items_than_slots_are_on_losses_and_no_sentence(game):
    ceiling = boundarywidths.ceilings(game).items
    char = boundarywidths.base(game)
    item = boundarychars._item()
    char.set("inventory", [item] * (ceiling + 2), "boundary: one past")
    rep = _lost(char)
    assert rep.losses == [f"inventory: 2 items past the {ceiling} slots the "
                          f"C64 record holds"], (game, rep.losses)
    assert rep.warnings == []


@pytest.mark.parametrize("game", GAMES)
def test_l_more_trait_ids_than_slots_are_on_losses_and_no_sentence(game):
    char = boundarywidths.base(game)
    char.set("innate_effects", list(range(1, traits.SLOTS + 3)),
             "boundary: one past")
    rep = _lost(char)
    assert len(rep.losses) == 1 and rep.losses[0].startswith(
        "item_effects: 2 racial"), (game, rep.losses)
    assert rep.warnings == []


@pytest.mark.parametrize("game", GAMES)
def test_l_spellbook_ids_above_the_mask_are_on_losses_and_no_sentence(game):
    top = spells.for_game(game).last_spellbook_spell
    char = boundarywidths.base(game)
    char.set("spells_known", list(range(1, top + 3)), "boundary: one past")
    rep = _lost(char)
    assert rep.losses == [f"spells_known: 2 ids above {top}, the last spell "
                          f"this title's spellbook mask holds"], (game, rep.losses)
    assert rep.warnings == []


@pytest.mark.parametrize("game", GAMES)
def test_l_a_class_with_no_c64_slot_is_on_losses_and_no_sentence(game):
    char = boundarywidths.base(game)
    char.set("levels", {"fighter": 5, "no-such-class": 3}, "boundary")
    rep = _lost(char)
    assert rep.losses == ["levels: no-such-class 3 has no slot in the C64 "
                          "record"], (game, rep.losses)
    assert rep.warnings == []


@pytest.mark.parametrize(
    "game", [g for g in GAMES if c64_codec.deltas_for(g).spell_slots])
def test_l_a_spell_count_past_a_nibble_is_clamped_and_a_loss(game):
    # Only the titles whose record packs the counts have a nibble to overflow.
    # `boundarywidths.base` is DOS-sourced, so the cleric column is rebuilt
    # from the class levels; a magic-user column is copied.
    char = boundarywidths.base(game)
    char.set("spells_castable", {"magic-user": (16, 0, 0)}, "boundary")
    rep = _lost(char)
    line = ("spells_castable: magic-user level 1 holds 16, which does not fit "
            "the C64's four-bit count; clamped to 15")
    assert line in rep.losses and line in rep.warnings, (game, rep.losses)


@pytest.mark.parametrize("game", GAMES)
def test_l_a_control_byte_past_a_byte_is_wrapped_and_a_loss(game):
    char = boundarywidths.base(game)
    char.set("npc", True, "boundary")
    char.set("npc_control_byte", 0x1FF, "boundary: one past")
    rep = _lost(char)
    line = ("npc_control_byte: 511 does not fit the C64's one-byte field; "
            "wrapped to 255")
    assert line in rep.losses and line in rep.warnings, (game, rep.losses)


@pytest.mark.parametrize("game", GAMES)
def test_l_a_reader_warning_reaches_warnings_and_never_losses(game):
    char = boundarywidths.base(game)
    char.warnings.append("a note the reader made about its own source")
    rep = _lost(char)
    assert "a note the reader made about its own source" in rep.warnings
    assert rep.losses == [], (game, rep.losses)
