from __future__ import annotations

"""Converting the Amiga Curse and Silver Blades combat figure (#319, #396).

`#396 (Whether an Amiga Curse or Silver Blades record's combat-icon fields
share DOS's own numbering is unmeasured)` proved, from both engines' own
icon-drawing routines, that an Amiga Curse or Silver Blades record's
`icon_head`, `icon_body` and `icon_colours` are DOS's own fields holding
DOS's own numbers, indexing DOS's own art -- `docs/199-amiga-combat-icons.md`
is the write-up. `#319 (The Amiga export's drop line still says a conversion
"does not carry" a combat icon)` is what asked for the fields to convert
rather than for a better sentence about why they do not.

Every test here reads the corpus `tests/test_amiga.py` already reads: the
eleven Curse `.guy` pregens, the four played Curse characters and the six
shipped Silver Blades ones, 21 specimens total. `tests/test_amigalaterwrite.py`
already proves the round trip byte for byte; this file is about the two
things that are new -- the drop lines and the two composition directions.
"""

import pytest
from test_amiga import curse_characters, silver_blades_characters

from goldbox import amiga_later, amiga_port
from goldbox.iconparts import IconParts, dos_icon_tables, dos_size

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _all_characters():
    """`(label, character)` for all 21 specimens, both titles."""
    return ([("Curse", c) for c in curse_characters()]
            + [("Silver Blades", c) for c in silver_blades_characters()])


# ---------------------------------------------------------------------------
# The pane: the four drop lines are gone, because the fields convert
# ---------------------------------------------------------------------------

#: The phrases the four lines `goldbox.amiga.LATER_DROPPED_PLAYER_TEXT` used
#: to carry, lower-cased for a case-insensitive search. Watched failing
#: before the fix: reverting `LATER_TRANSFORMED`/`LATER_DROPPED` to move
#: `icon_head`, `icon_body` and `icon_colours` back onto `LATER_DROPPED`
#: brings all three back for every one of the 21 specimens below, and
#: `icon_dimension`'s line reappears the moment its `LATER_DROPPED_PLAYER_TEXT`
#: entry is restored.
_OLD_ICON_DROP_PHRASES = (
    "combat icon (head)",
    "combat icon (body)",
    "combat icon colours",
    "combat icon size",
)


def test_the_four_combat_icon_drop_lines_are_gone():
    """Neither title's pane says anything about the combat icon any more.

    21 of 21 specimens, both titles: not one of the four lines this pane
    used to carry for every character appears in `to_neutral_later`'s own
    drop list.
    """
    seen = 0
    for label, char in _all_characters():
        neutral = amiga_later.to_neutral_later(char)
        lowered = [d.lower() for d in neutral.dropped]
        for phrase in _OLD_ICON_DROP_PHRASES:
            assert not any(phrase in d for d in lowered), (
                label, char.name, phrase, neutral.dropped)
        seen += 1
    assert seen == 21, seen


def test_the_pane_still_reports_something_else():
    """The sweep above did not empty the whole drop list -- only checked that
    is not proof of anything. Every specimen still carries at least one
    unrelated drop line, such as the sheet portrait or the treasure share."""
    for label, char in _all_characters():
        neutral = amiga_later.to_neutral_later(char)
        assert neutral.dropped, (label, char.name)


def test_icon_head_body_and_colours_are_named_transformed_not_dropped():
    """The bookkeeping table itself: `later_field_disposition` is the test
    that every declared field is named in exactly one of direct, transformed
    or dropped, so this just points at where the three names live now."""
    transformed = {n for n, _ in amiga_later.LATER_TRANSFORMED}
    dropped = {n for n, _ in amiga_later.LATER_DROPPED}
    for name in ("icon_head", "icon_body", "icon_colours"):
        assert name in transformed, name
        assert name not in dropped, name
    # icon_dimension stays dropped, and carries no player-facing line --
    # Donald's ruling on the identical DOS line, 2026-09-06.
    assert "icon_dimension" in dropped
    assert "icon_dimension" not in amiga_later.LATER_DROPPED_PLAYER_TEXT


# ---------------------------------------------------------------------------
# Amiga -> DOS: editor.convert.amiga_combat_icon, verified for Curse and
# Silver Blades rather than assumed from Pool of Radiance
# ---------------------------------------------------------------------------

def test_amiga_combat_icon_reads_curse_and_silver_blades_records_too():
    """`editor.convert.amiga_combat_icon` was written for Amiga Pool of
    Radiance (#354) and this is the check that it needs no change to read a
    Curse or Silver Blades `AmigaCharacter` as well -- it does, once `.get()`
    replaces `.raw()` for the colours (`AmigaCharacter` has no `.raw(name)`
    method; its own `raw` attribute is the record's bytes).

    12 of 21 specimens hold the game's own default colours
    (`91 A2 B3 C4 E6 F7`) and a test that only saw those would prove
    nothing about a character who chose his own -- so this checks all 21,
    named individually where it matters below.
    """
    from editor.convert import amiga_combat_icon

    seen = 0
    for label, char in _all_characters():
        icon = amiga_combat_icon(char)
        assert icon.head == char.get("icon_head"), (label, char.name)
        assert icon.body == char.get("icon_body"), (label, char.name)
        assert icon.colours == bytes(char.get("icon_colours")), (
            label, char.name)
        assert "Amiga" in icon.figure_source
        assert "Amiga" in icon.colours_source
        # An Amiga source has no C64 menu behind it to have recognised a
        # choice from -- see the docstring's own "choice is left None".
        assert icon.choice is None
        seen += 1
    assert seen == 21, seen


def test_a_default_colours_character_and_a_customised_one_both_convert():
    """HOLLAND (Curse) carries the game's own freshly-made default,
    `91 A2 B3 C4 E6 F7`; ARIEL (Curse) chose her own. Both convert to
    exactly the bytes their own record holds, which a test that only ever
    saw the default could not tell apart from a bug that always writes it.
    """
    from editor.convert import amiga_combat_icon

    by_name = {c.name.strip().upper(): c for c in curse_characters()}
    default = bytes((0x91, 0xA2, 0xB3, 0xC4, 0xE6, 0xF7))
    holland = by_name["HOLLAND"]
    ariel = by_name["ARIEL"]
    assert bytes(holland.get("icon_colours")) == default
    assert bytes(ariel.get("icon_colours")) != default

    for char in (holland, ariel):
        icon = amiga_combat_icon(char)
        assert icon.colours == bytes(char.get("icon_colours")), char.name


def test_amiga_combat_icon_written_through_dos_write_matches_the_source():
    """The whole path, not just the builder: `goldbox.dos.write`'s own
    `icon` argument actually lands the bytes in the DOS record it produces,
    for a Curse and a Silver Blades specimen -- `tests/test_iconprovenance.py`
    already proves this for a synthetic record; this is the same claim on
    two real ones.
    """
    from editor.convert import amiga_combat_icon
    from goldbox import dos_codec

    for label, chars in (("Curse", curse_characters()),
                        ("Silver Blades", silver_blades_characters())):
        char = chars[0]
        icon = amiga_combat_icon(char)
        neutral_char = amiga_later.to_neutral_later(char)
        record, _itm, _spc, rep = dos_codec.write(neutral_char, icon=icon)
        shape = amiga_later.later_write_shape(neutral_char)
        f_head = shape.dos_field("icon_head")
        f_body = shape.dos_field("icon_body")
        f_colours = shape.dos_field("icon_colours")
        assert record[f_head.offset] == char.get("icon_head"), label
        assert record[f_body.offset] == char.get("icon_body"), label
        assert (record[f_colours.offset:f_colours.offset + f_colours.size]
                == bytes(char.get("icon_colours"))), label
        assert "already" in rep.sources[f_head.offset], label


# ---------------------------------------------------------------------------
# Amiga -> C64: goldbox.iconparts.IconParts.dos_icon, with the title so
# #335's Silver Blades override applies to the Amiga art too
# ---------------------------------------------------------------------------

def test_amiga_icon_fields_compose_a_legal_c64_figure_for_every_specimen():
    """`IconParts.dos_icon(head, body, size, colours, tables=...)` is what
    `goldbox.dos._icon_for` already calls for a DOS source; an Amiga Curse
    or Silver Blades record's own icon fields are the same four values
    (#396), passed through the title-aware table so a title's own override
    -- Silver Blades' redrawn head 10 and body 11 -- applies to the Amiga
    art as well as the DOS art it is identical to.
    """
    from gamedata import game_file

    parts = IconParts(game_file("SPELLE64"), game_file("SPELLN64"))
    seen = 0
    for title, chars in (
            ("curse-of-the-azure-bonds", curse_characters()),
            ("secret-of-the-silver-blades", silver_blades_characters())):
        for char in chars:
            head = char.get("icon_head")
            body = char.get("icon_body")
            size = dos_size(char.get("size"))
            colours = bytes(char.get("icon_colours"))
            tables = dos_icon_tables(title=title, size=size)
            icon36 = parts.dos_icon(head, body, size, colours, tables=tables)
            assert len(icon36) == 36, (title, char.name)
            seen += 1
    assert seen == 21, seen


def test_silver_blades_large_head_ten_needs_its_own_titles_table():
    """The one row this measurably changes: `tools/iconproposal.yaml`'s
    Silver Blades override sends DOS/Amiga head 10 at the large size to C64
    head 2 (a head that wears something), where the base table alone sends
    every title's head 10 to C64 head 15 (hair, nothing on top) -- wrong for
    Silver Blades, which redraws exactly this block with a hat (docs/199).

    No shipped Silver Blades specimen on this machine happens to carry head
    10, so this is the two DOS numbers the override table itself names,
    composed both ways to show they draw a different C64 figure.
    """
    from gamedata import game_file

    parts = IconParts(game_file("SPELLE64"), game_file("SPELLN64"))
    colours = bytes.fromhex("91a2b3c4e6f7")
    body = 24  # any legal large body; the head is what the override touches
    without_title = parts.dos_icon(10, body, "large", colours,
                                   tables=dos_icon_tables())
    with_title = parts.dos_icon(
        10, body, "large", colours,
        tables=dos_icon_tables(title="secret-of-the-silver-blades",
                              size="large"))
    assert without_title != with_title


# ---------------------------------------------------------------------------
# Anything -> Amiga: goldbox.amiga.write_later's new `icon` argument
# ---------------------------------------------------------------------------

def test_write_later_writes_zero_and_the_default_with_no_icon():
    """Backward compatibility: `write_later` with no `icon` argument writes
    exactly what it always has -- `icon_head`/`icon_body` zero and
    `icon_colours` the game's own freshly-made default -- so every existing
    caller that never knew about combat icons keeps working unchanged.
    """
    from goldbox import c64_port, neutral

    char = neutral.NeutralCharacter(
        "test", game=c64_port.by_key(amiga_port.CURSE_DELTAS.key))
    char.set("name", "TESTER", "a test name")
    for ability in neutral.ABILITIES:
        char.set(ability, 12, "a test score")
    built, _rep = amiga_later.write_later(char)
    assert built.get("icon_head") == 0
    assert built.get("icon_body") == 0
    assert bytes(built.get("icon_colours")) == bytes.fromhex("91a2b3c4e6f7")


def test_write_later_writes_a_given_icon_straight():
    """With an `icon`, `write_later` writes its three fields into the
    produced Amiga record unchanged -- the "write the five bytes straight"
    half of `#396`'s comment for `goldbox.amiga.write_later`."""
    from goldbox import c64_port, neutral
    from goldbox.iconparts import DosIcon

    icon = DosIcon(head=5, body=9, colours=bytes.fromhex("11223344e6f7"),
                  figure_source="test", colours_source="test")
    char = neutral.NeutralCharacter(
        "test", game=c64_port.by_key(amiga_port.SILVER_BLADES_DELTAS.key))
    char.set("name", "TESTER", "a test name")
    for ability in neutral.ABILITIES:
        char.set(ability, 12, "a test score")
    built, _rep = amiga_later.write_later(char, icon=icon)
    assert built.get("icon_head") == 5
    assert built.get("icon_body") == 9
    assert bytes(built.get("icon_colours")) == bytes.fromhex("11223344e6f7")
