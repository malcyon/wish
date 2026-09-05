"""A DOS character's own combat figure, converted to the C64's eighteen cells.

`#130 (A converted DOS party arrives with six identical combat figures, not
its own)`: every character a DOS import produced got the same composed
default, so a party of an archer, a robed mage and four fighters walked onto
the combat floor as six identical unarmed men.  `IconParts.dos_icon` is what
gives each of them his own figure back.

What these check is what a player would see go wrong: two characters who
looked different in DOS still looking different on the C64, and every figure
being one the game's own ICON menu could have made -- because an icon that is
*not* is eighteen screen codes of somebody else's character set, and the
engine draws it without complaint.
"""

import pytest
from gamedata import game_file

from goldbox.iconparts import (
    DOS_CAP_COLOUR,
    DOS_HIGH_NIBBLE_PARTS,
    DOS_PAIR_CLASSES,
    PART_CLASSES,
    IconParts,
    dos_icon_tables,
    dos_part_colours,
    dos_size,
)

#: The set 42 of the 54 shipped records across the four titles carry.
DEFAULT_COLOURS = bytes.fromhex("91a2b3c4e6f7")

#: What the engine's own icon editor allows: `GAME.OVR:0x1D553`-`0x1D62B`
#: wraps the head at 13 and the body at 31.
DOS_HEADS = range(14)
DOS_BODIES = range(32)


@pytest.fixture(scope="module")
def parts() -> IconParts:
    """The option tables, read off the player's character-creation disk."""
    return IconParts(game_file("SPELLE64"), game_file("SPELLN64"))


@pytest.fixture(scope="module")
def tables():
    return dos_icon_tables()


@pytest.fixture(scope="module")
def legal(parts) -> set[bytes]:
    """Every shape any sequence of ICON menu choices reaches. Slow."""
    return parts.legal_shapes()


def test_the_table_names_every_figure_a_dos_player_can_choose(tables):
    """Fourteen heads and thirty-two bodies, which is what the editor wraps at.

    A missing row is a character the conversion would refuse, and the record
    byte comes from the player's own game rather than from us.
    """
    assert sorted(tables.heads) == list(DOS_HEADS)
    assert sorted(tables.weapons) == list(DOS_BODIES)
    assert len(tables.ega_to_c64) == 16
    assert all(0 <= c <= 7 for c in tables.ega_to_c64)


def test_every_row_names_a_c64_option_that_exists(parts, tables):
    assert max(tables.weapons.values()) < parts.count("large", "weapon")
    assert max(tables.heads.values()) < parts.count("large", "head")


def test_every_dos_figure_becomes_an_icon_the_game_could_have_made(
        parts, tables, legal):
    """All 896 of them: 32 bodies x 14 heads x two sizes.

    Membership in `legal_shapes` is the check that matters.  Eighteen screen
    codes that no menu reaches are not a figure -- they are eighteen glyphs
    of `CHARPIC00` in whatever order, and the engine draws them anyway.
    """
    checked = 0
    for size in ("small", "large"):
        for body in DOS_BODIES:
            for head in DOS_HEADS:
                icon = parts.dos_icon(head, body, size, DEFAULT_COLOURS,
                                      tables)
                assert len(icon) == 36
                assert icon[:18] in legal, f"{size} body {body} head {head}"
                checked += 1
    assert checked == 896


def test_two_characters_with_different_figures_get_different_icons(
        parts, tables):
    """The defect this issue is about: six characters, six figures.

    The party staged by `tools/dosiconstage.py`, which is the one driven
    through the game in `docs/193-a-converted-party-in-a-fight.md`.
    """
    party = [(0, 1, "large"), (3, 24, "large"), (6, 28, "large"),
             (2, 9, "small"), (13, 16, "small"), (5, 3, "large")]
    icons = {parts.dos_icon(head, body, size, DEFAULT_COLOURS, tables)[:18]
             for head, body, size in party}
    assert len(icons) == len(party)


def test_a_small_character_whose_row_is_large_only_still_gets_his_figure(
        parts, tables, legal):
    """Six weapon rows and three head rows name options only the large list has.

    The C64 offers a small character 28 weapons and 14 heads.  Size is never
    written back by the ICON menu, so a mixed icon is one the game's own
    menus reach -- HOGARTH's, on the player's disks, is one.  Without this a
    dwarf with a crossbow would raise instead of converting.
    """
    over = [(head, body) for head in DOS_HEADS for body in DOS_BODIES
            if (tables.heads[head] >= parts.count("small", "head")
                or tables.weapons[body] >= parts.count("small", "weapon"))]
    assert over, "no row lands past a small character's own lists any more"
    for head, body in over:
        icon = parts.dos_icon(head, body, "small", DEFAULT_COLOURS, tables)
        assert icon[:18] in legal


def test_a_small_row_in_range_composes_from_the_small_list(parts, tables):
    """And the mixing above happens only where it has to.

    DOS body 0 and head 0 both name options the small list holds, so a small
    character gets the small art rather than the large art at that index.
    """
    small = parts.dos_icon(0, 0, "small", DEFAULT_COLOURS, tables)
    large = parts.dos_icon(0, 0, "large", DEFAULT_COLOURS, tables)
    assert small[:18] != large[:18]


def test_each_part_takes_the_nibble_that_covers_most_of_it(parts, tables):
    """`0x0C1`-`0x0C6`, in the order the engine's recolour lookup uses them.

    Read back through `part_colours`, which is the menu value each part of a
    drawn icon implies -- so this checks the colours as the game would show
    them in ICON > COLOR rather than as we wrote them.

    **Every byte here holds two different colours**, which is what makes the
    test say anything: a DOS byte is a pair and the C64 keeps one colour a
    part, so the conversion has to choose. The leg and the shield take the
    high nibble because that is the colour covering most of those two shapes
    -- 56-65% of the leg in 32 of 32 bodies, 68-72% of the shield in 8 of 8
    (`tools/dosnibbles.py`, #130). Everything else takes the low one.
    Reading the low nibble for all six turned MAGNUS's yellow shield black.
    """
    #        body    arm     leg     hair    shield  weapon
    #  low:  green   blue    yellow  white   red     cyan
    # high:  brown   grey    pink    d.grey  purple  l.green
    colours = bytes([0x62, 0x81, 0xD0 | 0x0E, 0x8F, 0x54, 0xA3])
    icon = parts.dos_icon(3, 24, "large", colours, tables)
    got = parts.part_colours(icon[18:], icon[:18])
    ega = tables.ega_to_c64
    for part, value in (("body", 0x02), ("arm", 0x01), ("leg", 0x0D),
                        ("hair", 0x0F), ("shield", 0x05), ("weapon", 0x03)):
        klass = PART_CLASSES.index(part)
        if klass in got:                # a figure need not own every part
            assert got[klass] == ega[value], part


def test_the_cap_has_no_dos_pair_and_takes_its_own_colour(tables):
    """Every DOS hat is drawn in pixel values the record cannot recolour."""
    got = dos_part_colours(DEFAULT_COLOURS, tables)
    assert got[PART_CLASSES.index("cap")] == DOS_CAP_COLOUR


def test_the_high_nibble_moves_the_leg_and_the_shield_and_nothing_else(
        parts, tables):
    """Which of a DOS pair reaches the C64, part by part.

    This test used to say the opposite -- that the high nibble changes
    nothing at all -- and that was the defect rather than a finding. The C64
    keeps one colour a part, so exactly one of the two is chosen, and for the
    leg and the shield it is the high one (#130).
    """
    low = bytes(v & 0x0F for v in DEFAULT_COLOURS)
    plain = parts.dos_icon(0, 1, "large", low, tables)

    # The four parts that take the low nibble: their high nibble is ignored.
    others = bytearray(low)
    for i, part in enumerate(DOS_PAIR_CLASSES):
        if part not in DOS_HIGH_NIBBLE_PARTS:
            others[i] |= 0x50
    assert parts.dos_icon(0, 1, "large", bytes(others), tables) == plain

    # The two that take the high nibble: theirs is what a player sees.
    for part in DOS_HIGH_NIBBLE_PARTS:
        moved = bytearray(low)
        moved[DOS_PAIR_CLASSES.index(part)] |= 0x50
        assert parts.dos_icon(0, 1, "large", bytes(moved), tables) != plain, part


def test_a_figure_the_table_does_not_name_is_refused(parts, tables):
    with pytest.raises(ValueError, match="head 14"):
        parts.dos_icon(14, 0, "large", DEFAULT_COLOURS, tables)
    with pytest.raises(ValueError, match="body 32"):
        parts.dos_icon(0, 32, "large", DEFAULT_COLOURS, tables)


def test_a_size_no_player_record_holds_is_refused():
    """A monster's `0x0C0` is zero, and a monster draws from other art."""
    assert dos_size(1) == "small"
    assert dos_size(2) == "large"
    with pytest.raises(ValueError, match="size 0"):
        dos_size(0)
