"""The icon editor's option tables, and the set of icons the game can make."""

import pathlib

import pytest
from gamedata import game_file

from goldbox.iconparts import CELLS_PER_POSE, SPACE, IconParts
from goldbox.icons import ICON_COUNT, icon_for_slot
from goldbox.savegame import SaveGame0

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def parts() -> IconParts:
    """The option tables, read off the player's character-creation disk."""
    return IconParts(game_file("SPELLE64"), game_file("SPELLN64"))


@pytest.fixture(scope="module")
def legal(parts) -> set[bytes]:
    """The whole reachable set. Slow enough to be worth computing once."""
    return parts.legal_shapes()


def test_the_counts_come_from_the_overlay_not_from_here(parts):
    """`$B0DA` holds `1C 0E 23 17` and `$B0DE` the four table addresses.

    Read rather than hardcoded, so a different build would be parsed correctly
    instead of being silently mis-sliced into plausible-looking rubbish.
    """
    assert parts.count("small", "weapon") == 28
    assert parts.count("small", "head") == 14
    assert parts.count("large", "weapon") == 35
    assert parts.count("large", "head") == 23
    assert parts.tables[("large", "weapon")][0] == 0xA800
    assert parts.tables[("large", "head")][0] == 0xA8F0
    assert parts.tables[("small", "weapon")][0] == 0xA9E0
    assert parts.tables[("small", "head")][0] == 0xAAD0


def test_a_composed_icon_is_eighteen_cells(parts):
    shape = parts.compose("large", 0, 1)
    assert len(shape) == CELLS_PER_POSE * 2
    assert shape != bytes([SPACE]) * len(shape)


def test_the_factory_default_is_large_weapon_zero_head_one(parts):
    """The commonest shape in the corpus, and it reconstructs exactly."""
    assert parts.compose("large", 0, 1).hex() == (
        "20a02086878806070820a020898a8b061011")


def test_changing_the_weapon_keeps_the_head(parts):
    """`$B26F`/`$B29B` save cells 0, 1, 9 and 10 and restore them.

    Without it the two menu items would not be independent and the reachable
    set would collapse to roughly the number of weapons.
    """
    one = parts.compose("large", 0, 5)
    two = parts.apply(one, "large", "weapon", 9)
    assert two[1] == one[1] and two[10] == one[10]
    assert two[4] != one[4]              # the body did change


def test_the_reachable_set_is_bigger_than_the_naive_product(parts, legal):
    """35x23 would be 805. Order matters and the two size pairs interact, so
    the real answer is larger -- which is why the editor explores rather than
    enumerating pairs."""
    assert len(parts.legal_shapes(("large",))) == 3138
    assert len(parts.legal_shapes(("small",))) == 1227
    assert len(legal) == 15328
    assert len(legal) > 35 * 23 + 28 * 14


def test_every_icon_we_hold_is_one_the_game_could_have_made(legal):
    """The check that the model is right rather than merely self-consistent.

    Only some of these reconstruct from a single (weapon, head) pair; the rest
    need a sequence, including one that mixes a large body with a small head.
    All of them are reachable.
    """
    shapes = set()
    for name in ("savedgame0.bin", "party6_savedgame0.bin",
                 "party6_after_combat.bin"):
        # The fixtures keep their two-byte load address; `from_prg` is what
        # strips it. Reading them raw shifts every icon two cells and makes
        # perfectly legal art look unreachable.
        save0 = SaveGame0.from_prg((FIXTURES / name).read_bytes()).to_bytes()
        for slot in range(ICON_COUNT):
            shape = bytes(icon_for_slot(save0, slot).shape)
            if set(shape) != {SPACE} and any(shape):
                shapes.add(shape)
    assert shapes, "no icons in the fixtures"
    outside = [s.hex() for s in shapes if s not in legal]
    assert not outside, f"not reachable by any menu sequence: {outside}"


def test_size_for_is_large_only_when_the_small_list_is_too_short(parts):
    """Public because `tools/iconproposal.py` needs the same rule (#325).

    A weapon or head numbered past the small list's own count composes
    large; anything the small list already holds stays small.
    """
    small_heads = parts.count("small", "head")
    small_weapons = parts.count("small", "weapon")
    assert parts.size_for("small", "head", small_heads - 1) == "small"
    assert parts.size_for("small", "head", small_heads) == "large"
    assert parts.size_for("small", "weapon", small_weapons) == "large"
    assert parts.size_for("large", "head", small_heads) == "large"


def test_an_option_out_of_range_is_refused(parts):
    with pytest.raises(ValueError):
        parts.compose("large", 35, 0)
    with pytest.raises(ValueError):
        parts.compose("small", 0, 14)


def test_the_colour_rule_reproduces_the_icons_we_hold(parts):
    """`colour[cell] = C[class(glyph)] | (8 if bit 7)`.

    103 of the 104 icon slots across every disk we have satisfy it cell for
    cell. The one that does not is SHARA THE GRAY on the shipped POOL1 party,
    which carries colour `$0F` in two cells where the rule allows only 0-7 plus
    the glyph's own bit 3 -- hand-authored art, not something the editor made.
    """
    save0 = SaveGame0.from_prg(
        (FIXTURES / "party6_savedgame0.bin").read_bytes()).to_bytes()
    checked = 0
    for slot in range(ICON_COUNT):
        icon = icon_for_slot(save0, slot)
        shape, colours = bytes(icon.shape), bytes(icon.colours)
        if set(shape) == {SPACE} or not any(shape):
            continue
        per_class = parts.part_colours(colours, shape)
        assert parts.colours_for(shape, per_class, colours) == colours
        checked += 1
    assert checked, "no icons to check"


def test_a_cell_holding_no_part_keeps_the_colour_it_had(parts):
    """The rule governs parts. A space has class $0F and its colour byte is
    residue -- inventing one disagreed with every icon in a save."""
    shape = parts.compose("small", 0, 1)
    existing = bytes([0x0E]) * len(shape)
    out = parts.colours_for(shape, {0: 1, 1: 2}, existing)
    for cell, glyph in enumerate(shape):
        if parts.part_class(glyph) >= 7:
            assert out[cell] == 0x0E


def test_the_editor_offers_only_icons_the_game_can_make(parts, legal, tmp_path):
    """The point of all of it. Whatever the picker is driven to, the result is
    a shape reachable from the game's own menus."""
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication

    from editor.partspicker import PartsPicker

    app = QApplication.instance() or QApplication([])
    charset = bytes(2048)               # shape is what matters, not the art
    shape = parts.compose("large", 0, 1)
    colours = parts.colours_for(shape, {k: 1 for k in range(7)}, bytes(18))
    dialog = PartsPicker(parts, charset, shape, colours)

    for row in (3, 17, 30):
        dialog.weapons.setCurrentRow(row)
        assert dialog.shape in legal
    for row in (2, 11, 22):
        dialog.heads.setCurrentRow(row)
        assert dialog.shape in legal
    dialog.size_box.setCurrentText("small")
    dialog.weapons.setCurrentRow(5)
    assert dialog.shape in legal, "mixing sizes must stay inside the set"
    assert len(dialog.shape) == CELLS_PER_POSE * 2
    app.processEvents()


# --- the same tables on three titles (#330) ---------------------------------
#
# `IconParts.dos_icon` takes no title.  Its C64 half is title-specific and
# safe -- `IconParts.load` fits the base from the disk it was handed -- but
# its DOS half reads one correspondence table, `tools/iconproposal.yaml`,
# built from Pool of Radiance's art.  These are what would fail if a title
# numbered its own art differently, because a wrong-but-in-range row composes
# a complete, plausible figure that is simply not the one the player made.
DOS_TITLES = ("pool-of-radiance", "curse-of-the-azure-bonds",
              "secret-of-the-silver-blades")

#: What Silver Blades re-drew, `tools/dosicontitles.py` against the archives:
#: `(file, option, size)`, both poses of each.  Nothing else in either file
#: differs from Pool of Radiance's in any of the three titles.
SILVER_BLADES_REDREW = {("CHEAD.DAX", 10, "large"), ("CBODY.DAX", 11, "small")}


@pytest.fixture(scope="module")
def dos_art():
    """Every title's `CHEAD.DAX` and `CBODY.DAX`, compared, or skip."""
    dosicontitles = pytest.importorskip("tools.dosicontitles")
    gamedisks = pytest.importorskip("tools.gamedisks")
    root = gamedisks.find("dos-archives")
    if root is None or not root.is_dir():
        pytest.skip("needs the DOS games; set $FR_ARCHIVES")
    try:
        folders = dosicontitles.find_folders(root, list(DOS_TITLES))
    except SystemExit as exc:
        pytest.skip(str(exc))
    return dosicontitles.compare_art(folders, "pool-of-radiance")


def test_all_three_titles_hold_the_same_thirty_two_bodies_and_fourteen_heads(
        dos_art):
    """The block ids are the numbering, and they are the same in all three.

    `icon_body + (64 if size 2) + (128 if pose 2)` is the block the engine
    loads, so a title that shipped a different set of options would hold a
    different set of ids.  All three hold 128 `CBODY` blocks over 32 options
    and 56 `CHEAD` blocks over 14 -- which is also what each title's own ICON
    menu wraps at.
    """
    for name, options, blocks in (("CBODY.DAX", 32, 128),
                                  ("CHEAD.DAX", 14, 56)):
        for key in DOS_TITLES:
            row = dos_art[name]["titles"][key]
            assert (row["options"], row["blocks"]) == (options, blocks), key
            assert row["added"] == [] and row["missing"] == [], key


def test_curse_ships_pool_of_radiances_combat_art_block_for_block(dos_art):
    """184 of 184 blocks byte-identical, so the table transfers unchanged."""
    total = 0
    for name in ("CBODY.DAX", "CHEAD.DAX"):
        row = dos_art[name]["titles"]["curse-of-the-azure-bonds"]
        assert row["redrawn"] == [], name
        assert row["identical"] == row["blocks"]
        total += row["identical"]
    assert total == 184


def test_silver_blades_redrew_two_options_and_only_those_two(dos_art):
    """182 of 184 blocks byte-identical; the two that are not are named.

    This is the test that fails if a later title diverges further, because
    every row of `tools/iconproposal.yaml` was chosen against Pool of
    Radiance's drawing of that option.  Silver Blades' head 10 at size 2
    wears a hat Pool of Radiance's does not, and its body 11 at size 1 holds
    no weapon where Pool of Radiance's holds one -- so those two rows
    describe a figure Silver Blades does not draw.
    """
    seen = set()
    for name in ("CBODY.DAX", "CHEAD.DAX"):
        row = dos_art[name]["titles"]["secret-of-the-silver-blades"]
        for hit in row["redrawn"]:
            seen.add((name, hit["option"], hit["size"]))
            assert hit["pose"] in (1, 2)
        assert row["identical"] == row["blocks"] - len(row["redrawn"])
    assert seen == SILVER_BLADES_REDREW


def test_the_redrawn_silver_blades_body_holds_no_weapon(dos_art):
    """Both poses of it, which is what makes the difference a figure rather
    than a stray pixel: Pool of Radiance's small body 11 draws weapon and
    weapon-highlight pixels and Silver Blades' draws neither."""
    redrawn = [h for h in
               dos_art["CBODY.DAX"]["titles"]
               ["secret-of-the-silver-blades"]["redrawn"]]
    assert len(redrawn) == 2
    for hit in redrawn:
        assert "weapon" in hit["parts_reference"]
        assert "weapon" not in hit["parts_here"]
        assert "weapon+" not in hit["parts_here"]


def test_every_title_numbers_its_icon_fields_where_our_layout_says(dos_art):
    """The engine's own ICON menu, read out of each `GAME.OVR`.

    Two things at once: the wrap constants are 13 and 31 in all three, so
    every title offers the same 14 heads and 32 bodies; and they are found at
    the record displacement `goldbox/dos_layout.py` gives that title, so a
    wrong offset in our own table shows up here rather than silently.
    """
    dosicontitles = pytest.importorskip("tools.dosicontitles")
    gamedisks = pytest.importorskip("tools.gamedisks")
    root = gamedisks.find("dos-archives")
    folders = dosicontitles.find_folders(root, list(DOS_TITLES))
    code = dosicontitles.read_code(folders, list(DOS_TITLES))
    for key in DOS_TITLES:
        assert code[key]["wraps"]["icon_head"] == [0, 13], key
        assert code[key]["wraps"]["icon_body"] == [0, 31], key


def test_each_later_title_copies_the_earlier_ones_icon_bytes_unchanged():
    """The shipped engines' own answer to this question (#330).

    Curse's importer reads a Pool of Radiance record's `icon_head`,
    `icon_body`, `size` and six `icon_colours` and writes them into its own
    record with no table in between; Silver Blades' importer does the same
    with a Curse record.  A game that renumbered its art could not do that.
    """
    dosicontitles = pytest.importorskip("tools.dosicontitles")
    gamedisks = pytest.importorskip("tools.gamedisks")
    root = gamedisks.find("dos-archives")
    if root is None or not root.is_dir():
        pytest.skip("needs the DOS games; set $FR_ARCHIVES")
    folders = dosicontitles.find_folders(root, list(DOS_TITLES))
    code = dosicontitles.read_code(folders, list(DOS_TITLES))
    for key in DOS_TITLES[1:]:
        copies = code[key]["copies"]
        for field in ("icon_head", "icon_body", "size", "icon_colours"):
            assert len(copies[field]) == 1, f"{key}: {field} {copies[field]}"


# -- the per-title override section (#330, #335) -----------------------------
#
# `tools/iconproposal.yaml` gained an `overrides:` section for a title whose
# C64 art disagrees with Pool of Radiance's, keyed by `goldbox.games.Game.key`.
# It is empty until Donald picks Silver Blades' two rows on
# `#335 (Two combat-figure rows describe Pool of Radiance's art, and Silver
# Blades draws those two options differently)`, and these pin that `dos_icon_
# tables` goes on reading exactly the base table -- for every title, since
# nothing calls it with one yet -- until a title's own section actually names
# a row.

def _table_yaml(tmp_path, overrides: str = "") -> pathlib.Path:
    """A minimal table -- two weapons, two heads, all sixteen colours."""
    path = tmp_path / "table.yaml"
    path.write_text(
        "weapons:\n" + "".join(f"  {i}: {{c64: {i}}}\n" for i in range(2))
        + "heads:\n" + "".join(f"  {i}: {{c64: {i}}}\n" for i in range(2))
        + "colours:\n" + "".join(f"  {i}: {{c64: 0}}\n" for i in range(16))
        + overrides)
    return path


def test_dos_icon_tables_with_no_title_ignores_any_overrides_section(tmp_path):
    path = _table_yaml(tmp_path, "overrides:\n  some-title:\n"
                                 "    weapons:\n      0: {c64: 99}\n")
    from goldbox.iconparts import dos_icon_tables
    assert dos_icon_tables(path).weapons[0] == 0


def test_a_title_with_no_override_composes_exactly_what_it_composes_today(
        tmp_path):
    """The regression: `title` used to be an argument `dos_icon_tables` did
    not accept at all, so this is also the test that the parameter exists."""
    path = _table_yaml(tmp_path, "overrides: {}\n")
    from goldbox.iconparts import dos_icon_tables
    base = dos_icon_tables(path)
    assert dos_icon_tables(path, title="curse-of-the-azure-bonds") == base
    assert dos_icon_tables(path, title="secret-of-the-silver-blades") == base
    assert dos_icon_tables(path, title=None) == base


def test_a_title_with_an_override_uses_it_for_that_row_alone(tmp_path):
    path = _table_yaml(tmp_path,
                       "overrides:\n  secret-of-the-silver-blades:\n"
                       "    heads:\n      1: {c64: 9}\n")
    from goldbox.iconparts import dos_icon_tables
    base = dos_icon_tables(path)
    overridden = dos_icon_tables(path, title="secret-of-the-silver-blades")
    assert base.heads[1] == 1                    # the un-overridden reading
    assert overridden.heads[1] == 9               # the row the override names
    assert overridden.heads[0] == base.heads[0]   # every other row untouched
    assert overridden.weapons == base.weapons     # the other table untouched
    # A different title's own key must never see another title's override.
    assert dos_icon_tables(path, title="pool-of-radiance") == base
    assert dos_icon_tables(path, title="curse-of-the-azure-bonds") == base


def test_the_shipped_table_reads_the_base_rows_for_every_title_but_its_own():
    """The rule, against the real `tools/iconproposal.yaml`: a title with no
    `overrides:` section of its own reads the base table untouched, and a
    title with one differs from it by exactly the rows that section names.

    This replaces a test that asserted the section was empty. It was, until
    Donald picked Silver Blades' head 10 on 2026-09-05 for `#335 (Two
    combat-figure rows describe Pool of Radiance's art, and Silver Blades
    draws those two options differently)`, and then it failed for having
    pinned a state rather than a rule.
    """
    import sys

    from goldbox.games import GAMES
    from goldbox.iconparts import dos_icon_tables

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent
                           / "tools"))
    import iconproposal as ip

    overrides = ip.load_overrides()
    base = dos_icon_tables()
    for game in GAMES:
        mine = dos_icon_tables(title=game.key)
        section = overrides.get(game.key, {})
        for kind, table, base_table in (("weapons", mine.weapons, base.weapons),
                                        ("heads", mine.heads, base.heads)):
            rows = section.get(kind, {})
            moved = {k: v for k, v in table.items() if base_table[k] != v}
            assert moved == {k: v for k, v in rows.items()
                             if base_table[k] != v}, (game.key, kind)
        assert mine.ega_to_c64 == base.ega_to_c64, game.key


def test_dos_icon_tables_with_no_title_reads_the_base_table():
    """No `title` means no override, whatever the section holds.

    The contract every existing caller relies on, and the reason Donald's
    Silver Blades head does not reach a conversion yet: `goldbox.dos.
    _icon_for` calls `IconParts.dos_icon` with no `tables`, which calls
    `dos_icon_tables()` with no `title`, so a converted Silver Blades
    character is still composed through the base row. Passing the title down
    is the rest of `#335 (Two combat-figure rows describe Pool of Radiance's
    art, and Silver Blades draws those two options differently)`.
    """
    import sys

    from goldbox.iconparts import dos_icon_tables

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent
                           / "tools"))
    import iconproposal as ip

    untitled = dos_icon_tables()
    base_weapons, _, base_heads, _, _ = ip.load_tables()
    assert untitled.weapons == base_weapons
    assert untitled.heads == base_heads


def test_a_size_specific_override_wins_and_only_at_that_size(tmp_path):
    """The C64 draws a small character from shorter lists than a large one,
    and the shared designs are redrawn rather than scaled -- so a row chosen
    against the large picture can be the wrong answer for a halfling.

    Donald asked for exactly that on 2026-09-05, for Pool of Radiance:
    DOS weapon 7 to C64 weapon 2 and DOS head 0 to C64 head 1, at the small
    size only. The base table sends them to 1 and 5, which stay right for a
    large character.
    """
    from goldbox import iconparts

    table = tmp_path / "t.yaml"
    table.write_text(
        "weapons:\n  7: {c64: 1}\n  9: {c64: 30}\n"
        "heads:\n  0: {c64: 5}\n"
        "colours:\n" + "".join(f"  {i}: {{c64: {i % 8}}}\n" for i in range(16))
        + "overrides:\n"
          "  pool-of-radiance:\n"
          "    weapons:\n      9: {c64: 31}\n"
          "    small:\n"
          "      weapons:\n        7: {c64: 2}\n"
          "      heads:\n        0: {c64: 1}\n")

    base = iconparts.dos_icon_tables(table)
    assert (base.weapons[7], base.heads[0]) == (1, 5)

    large = iconparts.dos_icon_tables(table, title="pool-of-radiance",
                                      size="large")
    assert (large.weapons[7], large.heads[0]) == (1, 5), "small-only leaked"

    small = iconparts.dos_icon_tables(table, title="pool-of-radiance",
                                      size="small")
    assert (small.weapons[7], small.heads[0]) == (2, 1)

    #: A size-free row in the same section still reaches both sizes, so the
    #: subsection is an exception to it rather than a replacement for it.
    assert large.weapons[9] == 31 and small.weapons[9] == 31

    #: And a title with no section of its own is untouched by either.
    other = iconparts.dos_icon_tables(table, title="curse-of-the-azure-bonds",
                                      size="small")
    assert (other.weapons[7], other.heads[0]) == (1, 5)
