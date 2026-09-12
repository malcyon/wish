"""Reading a C64 combat icon back into menu choices, and the reverse table.

`#320 (A C64 party converted to DOS arrives with no combat figure at all,
because the table only runs one way)` needs two things the other direction
did not: a way to say which weapon and head drew an icon, since the C64
stores the drawn cells rather than an index, and a table saying which DOS
option each C64 one becomes.

What would actually break here is a conversion putting the wrong figure on a
converted character, silently -- every wrong answer composes a complete,
plausible drawing. So these check the two properties that make a wrong answer
impossible rather than merely unlikely: that recognition is exact for the
weapon over every icon the game's own menus can reach, and that a row the
forward table already decided is not quietly re-decided here.
"""

import pathlib
import sys

import pytest
from gamedata import game_file

from goldbox.iconparts import (
    CELLS_PER_POSE,
    DEFAULT_BACKGROUND,
    DEFAULT_PART_COLOURS,
    MULTICOLOUR,
    SPACE,
    WEAPON_ONLY_CELLS,
    IconParts,
    c64_icon_tables,
    dos_icon_tables,
    dos_part_colours,
)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))

#: The four C64 lists, with what `SPELLN64`'s `$B0DA` says each holds.
LISTS = (("large", "weapons", 35), ("large", "heads", 23),
         ("small", "weapons", 28), ("small", "heads", 14))

#: DOS's own counts, which its ICON menu wraps at (#130).
DOS_BODIES, DOS_HEADS = 32, 14

#: The colour set the DOS game writes for a character it has just rolled.
DEFAULT_DOS_COLOURS = bytes.fromhex("91a2b3c4e6f7")


@pytest.fixture(scope="module")
def parts() -> IconParts:
    return IconParts(game_file("SPELLE64"), game_file("SPELLN64"))


@pytest.fixture(scope="module")
def table():
    import iconreverse
    return iconreverse.load_tables()


@pytest.fixture(scope="module")
def reverse_tables():
    """`goldbox.iconparts.c64_icon_tables()` -- the reader `IconParts.
    dos_icon_from_c64` uses, independent of `tools/iconreverse.py`'s own
    `load_tables` the way `table` above is not."""
    return c64_icon_tables()


# -- recognising an icon -----------------------------------------------------

def test_no_head_option_writes_the_fourteen_cells_the_weapon_owns(parts):
    """The measurement the whole recogniser rests on.

    `WEAPON_ONLY_CELLS` is asserted rather than assumed: if any head option
    in either list drew into one of those fourteen cells, the weapon could
    not be read out of them, and every icon a converted character got would
    be plausible and wrong.
    """
    blank = bytes([SPACE] * (CELLS_PER_POSE * 2))
    for size in ("small", "large"):
        for option in range(parts.count(size, "head")):
            drawn = parts.apply(blank, size, "head", option)
            for cell in WEAPON_ONLY_CELLS:
                assert drawn[cell] == SPACE, (size, option, cell)


def test_all_sixty_three_weapon_options_draw_a_different_fourteen(parts):
    """28 small plus 35 large, and no two share a signature -- so the weapon
    *and* which list it came from are read out of a dict rather than searched
    for."""
    seen = {}
    blank = bytes([SPACE] * (CELLS_PER_POSE * 2))
    for size in ("small", "large"):
        for option in range(parts.count(size, "weapon")):
            drawn = parts.apply(blank, size, "weapon", option)
            key = bytes(drawn[c] for c in WEAPON_ONLY_CELLS)
            assert key not in seen, (seen.get(key), (size, option))
            seen[key] = (size, option)
    assert len(seen) == 63


def test_every_composed_icon_names_its_own_weapon_back(parts):
    """All 2331 (weapon, head) pairs across both size lists, mixed sizes
    included -- the weapon comes back exactly, 2331 of 2331."""
    blank = bytes([SPACE] * (CELLS_PER_POSE * 2))
    checked = 0
    for wsize in ("small", "large"):
        for weapon in range(parts.count(wsize, "weapon")):
            base = parts.apply(blank, wsize, "weapon", weapon)
            for hsize in ("small", "large"):
                for head in range(parts.count(hsize, "head")):
                    shape = parts.apply(base, hsize, "head", head)
                    read = parts.recognise(shape, prefer=hsize)
                    assert (read.weapon_size, read.weapon) == (wsize, weapon)
                    named = {(read.head_size, read.head), *read.alternatives}
                    assert (hsize, head) in named, (wsize, weapon, hsize, head)
                    checked += 1
    assert checked == 2331


def test_the_head_is_named_alone_except_where_a_weapon_hides_the_difference(
        parts):
    """201 of the 2331 compositions name more than one head, over 96 distinct
    drawings -- and every one of them is a weapon covering cells 0 and 9.

    Seven of the 23 large heads are another head with a hair glyph added
    there, and small heads 0 and 5 are the identical drawing; a weapon that
    fills those cells makes the pair indistinguishable. That is not a defect
    to route around -- the two figures are the same picture -- but a caller
    must be able to see it, which is what `alternatives` is for.
    """
    blank = bytes([SPACE] * (CELLS_PER_POSE * 2))
    ambiguous, shapes = 0, set()
    for wsize in ("small", "large"):
        for weapon in range(parts.count(wsize, "weapon")):
            base = parts.apply(blank, wsize, "weapon", weapon)
            for hsize in ("small", "large"):
                for head in range(parts.count(hsize, "head")):
                    read = parts.recognise(parts.apply(base, hsize, "head",
                                                       head), prefer=hsize)
                    if read.alternatives:
                        ambiguous += 1
                        shapes.add(parts.apply(base, hsize, "head", head))
    assert (ambiguous, len(shapes)) == (201, 96)


def test_small_heads_zero_and_five_are_the_same_drawing(parts):
    """The one pair of options in any of the four lists that are, so the one
    place where no recogniser could ever separate them."""
    blank = bytes([SPACE] * (CELLS_PER_POSE * 2))
    assert (parts.apply(blank, "small", "head", 0)
            == parts.apply(blank, "small", "head", 5))
    other = [(s, k, a, b)
             for s in ("small", "large") for k in ("weapon", "head")
             for a in range(parts.count(s, k)) for b in range(a + 1,
                                                              parts.count(s, k))
             if parts.apply(blank, s, k, a) == parts.apply(blank, s, k, b)]
    assert other == [("small", "head", 0, 5)]


def test_an_icon_no_weapon_drew_is_refused(parts):
    """A hand-authored icon has to raise rather than compose a figure the
    player never chose. SHARA THE GRAY's is the real case (#130)."""
    with pytest.raises(ValueError):
        parts.recognise(bytes(range(18)))
    with pytest.raises(ValueError):
        parts.recognise(parts.compose("large", 0, 1)[:17])


def test_a_mixed_size_icon_is_read_as_the_two_lists_it_came_from(parts):
    """Size is never written back, so a large weapon under a small head is
    legal and one is on the player's disks -- HOGARTH's."""
    shape = parts.apply(parts.apply(bytes([SPACE] * 18), "small", "weapon", 21),
                        "large", "head", 1)
    read = parts.recognise(shape)
    assert (read.weapon_size, read.weapon) == ("small", 21)
    assert (read.head_size, read.head) == ("large", 1)


def test_the_default_icon_reads_back_as_the_choices_that_made_it(parts):
    """`(large, weapon 0, head 1)` is what character creation writes for 8 of
    8 rolled characters, so it is the icon a conversion meets most often."""
    read = parts.recognise(parts.default_icon()[:18])
    assert (read.weapon_size, read.weapon, read.head_size, read.head) == (
        "large", 0, "large", 1)
    assert read.exact and not read.alternatives


# -- a C64 icon becomes a DOS one (#320) --------------------------------------
#
# `IconParts.dos_icon_from_c64` is the write side's own source for
# `icon_head`/`icon_body`/`icon_colours` (`goldbox.dos_codec.write`'s `icon`
# argument) -- `recognise` plus a lookup in `tools/iconreverse.yaml`,
# read here through `c64_icon_tables`.

def _composed(parts, size, weapon, head, colours=None):
    """One whole 36-byte icon, the way `tools/iconpoke.py` composes one."""
    shape = parts.compose(size, weapon, head)
    per_class = colours or DEFAULT_PART_COLOURS
    seed = bytes([DEFAULT_BACKGROUND | MULTICOLOUR] * len(shape))
    return shape + parts.colours_for(shape, per_class, seed)


def test_the_default_icon_becomes_dos_head_5_body_0(parts, reverse_tables):
    """Weapon 0 and head 1 are both forced rows -- `0: {dos: 0}` and
    `1: {dos: 5}` in `tools/iconreverse.yaml` -- so this is the one answer
    a correct reader can give, not a preference among several."""
    icon = parts.default_icon()
    result = parts.dos_icon_from_c64(icon, reverse_tables)
    assert (result.head, result.body) == (5, 0)
    assert result.choice.exact and not result.choice.alternatives


def test_six_different_c64_icons_become_six_different_dos_figures(
        parts, reverse_tables):
    """The issue's own Testing section: six icons that differ on the C64
    read back into six different `(icon_head, icon_body)` pairs."""
    figures = [("large", 0, 0), ("large", 7, 4), ("large", 11, 9),
              ("small", 3, 2), ("small", 16, 7), ("large", 21, 12)]
    pairs = [(r.head, r.body) for r in
            (parts.dos_icon_from_c64(_composed(parts, s, w, h), reverse_tables)
             for s, w, h in figures)]
    assert len(set(pairs)) == 6, pairs


def test_a_forced_row_recomposes_to_the_c64_icon_it_came_from(parts,
                                                               reverse_tables):
    """Weapon 11 (large) and head 9 (large) are both forced, so the round
    trip through `dos_icon_from_c64` and back through `dos_icon` has to
    reach the same eighteen screen codes -- the property
    `test_a_c64_figure_survives_a_round_trip_through_dos` pins for the
    table's own rows, checked here through the actual reader and writer.
    """
    original = _composed(parts, "large", 11, 9)
    result = parts.dos_icon_from_c64(original, reverse_tables)
    forward = dos_icon_tables(size="large")
    back = parts.dos_icon(result.head, result.body, "large", result.colours,
                          forward)
    assert back[:18] == original[:18]


def test_a_judgement_row_gives_the_nearest_figure_not_an_error(parts,
                                                                reverse_tables):
    """Weapon 0 with head 0 is not a forced pair -- large head 0 is a
    "judgement" row, Donald's nearest figure rather than a round-tripping
    one (`tools/iconreverse.py --coverage`) -- so this only has to compose
    without raising and land on the row the table actually names, not on
    whether it comes home byte for byte."""
    original = _composed(parts, "large", 0, 0)
    choice = parts.recognise(original[:18])
    result = parts.dos_icon_from_c64(original, reverse_tables)
    assert result.body == reverse_tables.weapons[(choice.weapon_size,
                                                   choice.weapon)]
    assert result.head == reverse_tables.heads[(choice.head_size,
                                                choice.head)]


def test_an_icon_with_no_weapon_is_refused(parts, reverse_tables):
    """The same refusal `recognise` makes on its own, reached through the
    higher-level method rather than worked around."""
    with pytest.raises(ValueError):
        parts.dos_icon_from_c64(bytes(range(36)), reverse_tables)


def test_the_colours_of_a_part_the_icon_draws_nothing_of_are_not_invented(
        parts, reverse_tables):
    """Weapon 0 is empty hands: no weapon-class cell is drawn, so there is
    no colour to read for it, and the DOS weapon colour byte falls back to
    :data:`DEFAULT_BACKGROUND`'s own row rather than a class this icon
    never used. Invisible either way -- nothing draws there -- and pinned
    so a future change cannot make it silently answer something else.
    """
    icon = parts.default_icon()
    result = parts.dos_icon_from_c64(icon, reverse_tables)
    low, high = reverse_tables.colours[DEFAULT_BACKGROUND]
    weapon_pos = 5  # DOS_PAIR_CLASSES = (body, arm, leg, hair, shield, weapon)
    assert result.colours[weapon_pos] == (high << 4) | low


# -- the table ---------------------------------------------------------------

def test_the_reverse_table_has_a_row_for_every_option_the_game_offers(table):
    """A missing row is a character with no figure, which is the bug (#320)."""
    for size, kind, count in LISTS:
        rows = table[(size, kind)]
        assert sorted(rows) == list(range(count)), (size, kind)
        limit = DOS_BODIES if kind == "weapons" else DOS_HEADS
        for c64, (dos, alt) in rows.items():
            assert 0 <= dos < limit, (size, kind, c64, dos)
            for other in alt:
                assert 0 <= other < limit, (size, kind, c64, other)
                assert other != dos, (size, kind, c64)


#: The rows Donald chose against the forward table, 2026-09-07, having been
#: shown every figure and told what it costs: a C64 figure on one of these
#: rows becomes a DOS figure that comes back as a *different* C64 figure, so
#: a party converted out and back does not keep it. He ruled *"Apply them;
#: the picture matters more"* -- the figure a player is given in DOS should
#: look like the one he had, ahead of surviving a round trip nobody makes.
#:
#: **This is a record of a decision, not a defect to be tidied away.** A
#: later reader who "fixes" one of these back is undoing his judgement. Six
#: of the seven are small heads, where four separate C64 heads now become DOS
#: head 0.
DONALDS_OVERRIDES = {
    ("large", "weapons"): (29,),
    ("small", "heads"): (0, 4, 6, 7, 8, 13),
}


def test_a_row_the_forward_table_decided_is_not_re_decided_here(table):
    """The property that makes a converted party keep its own figures.

    Where exactly one DOS option becomes a C64 option, reversing it is the
    only answer that returns a player their own figure on a round trip;
    where several do, the answer has to be one of them. A row that named
    anything else would send a save out and bring a different figure back.
    """
    for size, kind, count in LISTS:
        forward = dos_icon_tables(size=size)
        source = forward.weapons if kind == "weapons" else forward.heads
        preimages: dict[int, list[int]] = {}
        for dos, c64 in source.items():
            if c64 < count:
                preimages.setdefault(c64, []).append(dos)
        allowed = DONALDS_OVERRIDES.get((size, kind), ())
        for c64, pre in preimages.items():
            if c64 in allowed:
                continue
            assert table[(size, kind)][c64][0] in pre, (size, kind, c64, pre)


def test_a_c64_figure_survives_a_round_trip_through_dos(parts, table):
    """C64 option -> DOS option -> C64 option, for all 100 rows.

    This is what a player would see: convert a C64 party to DOS, convert it
    back, and the figures are the ones they chose. It holds for every row
    whose C64 option is some DOS option's target; the rows where it cannot
    hold are exactly the ones DOS has no figure for, and those are counted
    rather than skipped.
    """
    lost = []
    for size, kind, count in LISTS:
        forward = dos_icon_tables(size=size)
        source = forward.weapons if kind == "weapons" else forward.heads
        for c64, (dos, _) in table[(size, kind)].items():
            if source[dos] != c64:
                lost.append((size, kind, c64, dos, source[dos]))
    # 35 + 23 + 28 + 14 = 100 rows. Thirty-two cannot come home because DOS
    # has no figure for them -- the count `tools/iconreverse.py --coverage`
    # calls "fresh" -- and seven more because Donald chose the picture over
    # the round trip; see `DONALDS_OVERRIDES`.
    assert len(lost) == 32 + sum(len(v) for v in DONALDS_OVERRIDES.values())
    for size, kind, count in LISTS:
        forward = dos_icon_tables(size=size)
        source = forward.weapons if kind == "weapons" else forward.heads
        targets = {c for c in source.values() if c < count}
        allowed = DONALDS_OVERRIDES.get((size, kind), ())
        for entry in lost:
            if entry[:2] == (size, kind) and entry[2] not in allowed:
                assert entry[2] not in targets, entry


def test_the_colour_table_brings_the_shipped_default_set_home_unchanged(
        table):
    """`91 A2 B3 C4 E6 F7` out to the C64 and back, byte for byte.

    The forward table folds sixteen EGA colours onto the C64's eight, so a
    reverse row has to choose a pair -- and the pair every row names is the
    one the game's own default set uses, `(n, n | 8)`. All six parts of a
    freshly rolled DOS character therefore convert out and back to the bytes
    they started with. A row that picked the other member of a fold would
    fail here rather than in a fight.
    """
    reverse = table["colours"]
    per_class = dos_part_colours(DEFAULT_DOS_COLOURS)
    from goldbox.iconparts import DOS_PAIR_CLASSES, PART_CLASSES
    back = bytearray(6)
    for i, part in enumerate(DOS_PAIR_CLASSES):
        low, high = reverse[per_class[PART_CLASSES.index(part)]]
        back[i] = (high << 4) | low
    assert bytes(back) == DEFAULT_DOS_COLOURS


def test_every_c64_colour_has_a_row_and_the_pair_is_a_light_and_a_dark(table):
    """Eight rows, one per C64 icon colour, each naming an EGA colour and the
    same colour with bit 3 set -- which is what EGA's sixteen are: eight
    colours and their bright twins."""
    reverse = table["colours"]
    assert sorted(reverse) == list(range(8))
    for c64, (low, high) in reverse.items():
        assert 0 <= low < 8 and high == low | 8, c64
    assert len({low for low, _ in reverse.values()}) == 8


# -- the player's own icons --------------------------------------------------

def test_every_icon_on_the_players_disks_reads_back_into_menu_choices(parts):
    """The measurement that says the recogniser works on real saves rather
    than on shapes this test composed itself.

    222 icons over the three C64 disk sets on this machine, 35 distinct
    shapes, and every one of them names a weapon and a head. Seven of the 35
    are not a plain (weapon, head) composition -- they carry a cell an
    earlier menu choice left behind, which the game draws exactly as stored
    -- and the recogniser has to name those too, because a conversion that
    refused them would drop a real character's figure.
    """
    import iconreverse
    folders = iconreverse.save_folders()
    if not any(folders.values()):
        pytest.skip("needs the C64 disks; set $POR_DISKS")
    rows = iconreverse.census(parts, folders)
    if not rows:
        pytest.skip("no C64 saved games on the disks that are here")
    unread = [r for r in rows if "error" in r]
    assert not unread, [r["shape"] for r in unread]
    assert len(rows) >= 19, f"only {len(rows)} distinct shapes; expected 19+"
    residue = [r for r in rows if not r["choice"].exact]
    assert residue, "no icon carrying an earlier choice's cell was found"


def test_the_coverage_report_accounts_for_every_row(table):
    """100 rows over the four lists, each classed exactly once."""
    import iconreverse
    counts = {"forced": 0, "choice": 0, "fresh": 0}
    for (size, kind), row in iconreverse.coverage(table).items():
        assert not row["missing"], (size, kind, row["missing"])
        assert (sorted(row["disagrees"])
                == sorted(DONALDS_OVERRIDES.get((size, kind), ()))), (
            size, kind, row["disagrees"])
        for kind_name in row["kinds"].values():
            counts[kind_name] += 1
    assert sum(counts.values()) == 100
    assert counts["forced"] == 54 and counts["choice"] == 14
    assert counts["fresh"] == 32


def test_the_recogniser_and_the_table_agree_on_which_lists_exist(parts, table):
    """The counts in `tools/iconreverse.py` are the overlay's own, so a build
    that numbered its lists differently fails here rather than writing a row
    for an option that does not exist."""
    for size, kind, count in LISTS:
        assert parts.count(size, kind[:-1]) == count
        assert len(table[(size, kind)]) == count


def test_the_named_alternatives_are_never_the_proposal_itself(table):
    """A drafted row's `alt` is what Donald swaps to, so listing the proposal
    among them would waste the one thing the document is for."""
    for size, kind, _ in LISTS:
        for c64, (dos, alt) in table[(size, kind)].items():
            assert dos not in alt, (size, kind, c64)
            assert len(set(alt)) == len(alt), (size, kind, c64)
