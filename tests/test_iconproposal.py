"""`tools/iconproposal.py` reads its three tables from YAML, not Python (#130).

`#130 (A converted DOS party arrives with six identical combat figures, not
its own)`'s proposal used to live as three Python literals inside
`tools/iconproposal.py`. Donald asked for a YAML file he can edit by hand
instead, with `tools/iconproposal.py` reading it and `--markdown` generating
the judged document from it -- so `tools/iconproposal.yaml` is now the single
source, and this is where that is checked.

These tests pin the **shape** of the file rather than the matches in it: every
DOS figure has a row, every row names a C64 option, and all sixteen EGA
colours map to one of the C64's eight. The matches themselves are Donald's
judgement and change whenever he edits the file, which is what it is for.
"""

from __future__ import annotations

import contextlib
import io
import pathlib
import sys

import pytest
import yaml
from gamedata import disk_dir

from goldbox import games

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))

import iconcorrespond as ic  # noqa: E402
import iconproposal as ip  # noqa: E402

#: The shape of the proposal, which does not change when Donald edits it.
#:
#: **These deliberately do not pin the values.** An earlier version of this
#: file held the whole table as it stood in Python before the move to YAML and
#: asserted the two were equal, which was the right check for the migration
#: and the wrong one to leave behind: `tools/iconproposal.yaml` exists for
#: Donald to edit, so a test demanding it still equal the old Python turns his
#: first edit into a red build. It did -- he moved DOS weapon 2 from C64 5 to
#: 10 and CI went red on the migration oracle (#130).
#:
#: What is worth pinning is the shape: every DOS figure has a row, every row
#: names a C64 option that exists, and the colour table covers all sixteen EGA
#: entries. Those stay true however he rearranges the matches.
DOS_WEAPONS = 32
DOS_HEADS = 14
EGA_COLOURS = 16
C64_COLOURS = 8


def test_the_yaml_file_exists_beside_the_tool():
    assert ip.TABLE_PATH.name == "iconproposal.yaml"
    assert ip.TABLE_PATH.is_file()


def test_every_dos_weapon_has_a_row_naming_a_real_c64_option():
    weapons, alternatives, _, _, _ = ip.load_tables()
    assert sorted(weapons) == list(range(DOS_WEAPONS))
    assert all(isinstance(v, int) and v >= 0 for v in weapons.values())
    for dos_index, alts in alternatives.items():
        assert dos_index in weapons, dos_index
        assert all(isinstance(a, int) and a >= 0 for a in alts), dos_index


def test_every_dos_head_has_a_row_naming_a_real_c64_option():
    _, _, heads, alternatives, _ = ip.load_tables()
    assert sorted(heads) == list(range(DOS_HEADS))
    assert all(isinstance(v, int) and v >= 0 for v in heads.values())
    for dos_index, alts in alternatives.items():
        assert dos_index in heads, dos_index
        assert all(isinstance(a, int) and a >= 0 for a in alts), dos_index


def test_every_ega_colour_maps_to_one_the_c64_has():
    _, _, _, _, ega_to_c64 = ip.load_tables()
    assert len(ega_to_c64) == EGA_COLOURS
    assert all(0 <= c < C64_COLOURS for c in ega_to_c64), ega_to_c64


def test_forty_six_rows_total_between_weapons_and_heads():
    weapons, _, heads, _, _ = ip.load_tables()
    assert len(weapons) + len(heads) == DOS_WEAPONS + DOS_HEADS == 46


def test_the_module_level_tables_are_what_load_tables_returns():
    """`WEAPONS` etc. are loaded once at import time, from the same file."""
    weapons, weapon_alt, heads, head_alt, ega = ip.load_tables()
    assert ip.WEAPONS == weapons
    assert ip.WEAPON_ALTERNATIVES == weapon_alt
    assert ip.HEADS == heads
    assert ip.HEAD_ALTERNATIVES == head_alt
    assert ip.EGA_TO_C64 == ega


def test_from_markdown_is_gone():
    """The round trip this replaces must not come back (#130)."""
    assert not hasattr(ip, "read_markdown")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.suppress(SystemExit):
        ip.main(["--help"])
    assert "--from-markdown" not in buf.getvalue()


def test_a_malformed_yaml_row_is_caught_by_the_type(tmp_path):
    """A non-dict row (a bare number, the old Python shape) fails loudly.

    `tmp_path` rather than `tempfile.mkstemp`: the latter hands back an open
    descriptor as well as a path, and on Windows a file already open cannot
    be opened again -- `PermissionError: [WinError 32]`, which is what this
    test did on both Windows jobs in CI and on neither Linux one.
    """
    bad = tmp_path / "malformed.yaml"
    bad.write_text("weapons:\n  0: 5\nheads:\n  0: {c64: 7}\ncolours:\n"
                   + "\n".join(f"  {i}: {{c64: 0}}" for i in range(16)))
    with pytest.raises(TypeError):
        ip.load_tables(bad)


# -- the per-title override section (#330, #335) -----------------------------
#
# `tools/iconproposal.yaml` gained an `overrides:` section for a title whose
# art disagrees with Pool of Radiance's. Donald picked the first row on
# 2026-09-05 -- Silver Blades' head 10, for `#335 (Two combat-figure rows
# describe Pool of Radiance's art, and Silver Blades draws those two options
# differently)` -- and will pick more.
#
# **These pin the rule, not the rows.** Two earlier tests here asserted the
# section was empty and that every title got the base tables unchanged, which
# was true only until the first override existed, and both went red the
# evening it did. The rule that survives an edit is: a title with no section
# gets the base tables untouched, and a title with one gets exactly the rows
# its section names and no others.

def test_the_overrides_section_exists_and_names_only_titles_this_tool_draws():
    """The section is present, so a later removal fails loudly rather than
    `load_overrides` quietly treating "missing" the same as "empty"; and
    every key in it is a title `--title` will accept, so a typo in a title
    name cannot sit in the file silently overriding nothing."""
    data = yaml.safe_load(ip.TABLE_PATH.read_text())
    assert "overrides" in data, "the overrides: section is gone from the YAML"
    for title, sections in (data["overrides"] or {}).items():
        assert title in ip.DOS_TITLES, title
        assert set(sections) <= {"weapons", "heads"}, (title, sorted(sections))
        for kind, rows in sections.items():
            for dos_index, row in rows.items():
                assert isinstance(int(dos_index), int)
                assert isinstance(row["c64"], int), (title, kind, dos_index)


def test_load_overrides_parses_a_titles_section(tmp_path):
    path = tmp_path / "table.yaml"
    path.write_text(
        "weapons:\n  0: {c64: 1}\n"
        "heads:\n  0: {c64: 3}\n"
        "colours:\n" + "".join(f"  {i}: {{c64: 0}}\n" for i in range(16))
        + "overrides:\n  secret-of-the-silver-blades:\n"
        "    weapons:\n      0: {c64: 5}\n")
    assert ip.load_overrides(path) == {
        "secret-of-the-silver-blades": {"weapons": {0: 5}, "heads": {}}}


def test_a_title_with_no_override_of_its_own_gets_the_base_tables_unchanged():
    """The property a title's document relies on to say "nothing here needs
    judging" -- read against the real `tools/iconproposal.yaml`, so it holds
    whatever Donald has put in the section rather than only while it is
    empty."""
    overridden = ip.load_overrides()
    plain = [t for t in ip.DOS_TITLES if not any(overridden.get(t, {}).values())]
    assert plain, "every title now has an override; this test needs one without"
    for title in plain:
        weapons, heads = ip.tables_for_title(title)
        assert weapons == ip.WEAPONS, title
        assert heads == ip.HEADS, title


def test_a_title_with_an_override_gets_those_rows_and_no_others_changed():
    """The other half of the same rule, also against the real file: whatever
    a title's section names is what differs from the base table, exactly."""
    overridden = ip.load_overrides()
    named = {t: s for t, s in overridden.items() if any(s.values())}
    if not named:
        pytest.skip("no title has an override today; the rule needs one")
    for title, sections in named.items():
        weapons, heads = ip.tables_for_title(title)
        for kind, table, base in (("weapons", weapons, ip.WEAPONS),
                                  ("heads", heads, ip.HEADS)):
            rows = sections.get(kind, {})
            moved = {k: v for k, v in table.items() if base[k] != v}
            assert moved == {k: v for k, v in rows.items() if base[k] != v}, (
                title, kind)
            for dos_index, c64_index in rows.items():
                assert table[dos_index] == c64_index, (title, kind, dos_index)


def test_tables_for_title_applies_a_titles_own_override_and_only_that_row(
        tmp_path):
    path = tmp_path / "table.yaml"
    path.write_text(
        "weapons:\n  0: {c64: 1}\n  1: {c64: 2}\n"
        "heads:\n  0: {c64: 3}\n  1: {c64: 4}\n"
        "colours:\n" + "".join(f"  {i}: {{c64: 0}}\n" for i in range(16))
        + "overrides:\n  secret-of-the-silver-blades:\n"
        "    heads:\n      1: {c64: 9}\n")
    base_weapons, base_heads = ip.tables_for_title("pool-of-radiance", path)
    weapons, heads = ip.tables_for_title("secret-of-the-silver-blades", path)
    assert weapons == base_weapons                    # untouched table
    assert heads[0] == base_heads[0]                  # untouched row
    assert base_heads[1] == 4 and heads[1] == 9        # the overridden row
    # A different title's own section, if any, must never leak into this one.
    assert ip.tables_for_title("curse-of-the-azure-bonds", path) == (
        base_weapons, base_heads)


# -- comparing a title's own art against Pool of Radiance's (#330, #335) -----
#
# `redrawn_sizes` is what a title's `--markdown` document uses to mark a row
# "the same picture" or "redrawn" -- these pin it against the measurement
# `docs/168-dos-dax-and-combat-icons.md` already made, so a document is never
# trusted on a claim nobody checked here.

def _title_dos_game(title: str) -> pathlib.Path:
    dosicontitles = pytest.importorskip("tools.dosicontitles")
    gamedisks = pytest.importorskip("tools.gamedisks")
    root = gamedisks.find("dos-archives")
    if root is None or not root.is_dir():
        pytest.skip("needs the DOS archives; set $FR_ARCHIVES")
    try:
        return dosicontitles.find_folders(root, [title])[title]
    except SystemExit as exc:
        pytest.skip(str(exc))


def test_redrawn_sizes_is_empty_comparing_a_folder_to_itself():
    game = _dos_game()
    assert ip.redrawn_sizes(game, game, "weapon", 0) == []


def test_redrawn_sizes_finds_curse_redraws_nothing():
    pool, curse = _dos_game(), _title_dos_game("curse-of-the-azure-bonds")
    for dos_index in ip.WEAPONS:
        assert ip.redrawn_sizes(curse, pool, "weapon", dos_index) == []
    for dos_index in ip.HEADS:
        assert ip.redrawn_sizes(curse, pool, "head", dos_index) == []


def test_redrawn_sizes_finds_exactly_silver_blades_two_known_rows():
    pool = _dos_game()
    silver = _title_dos_game("secret-of-the-silver-blades")
    assert ip.redrawn_sizes(silver, pool, "head", 10) == ["large"]
    assert ip.redrawn_sizes(silver, pool, "weapon", 11) == ["small"]
    for dos_index in ip.HEADS:
        if dos_index != 10:
            assert ip.redrawn_sizes(silver, pool, "head", dos_index) == []
    for dos_index in ip.WEAPONS:
        if dos_index != 11:
            assert ip.redrawn_sizes(silver, pool, "weapon", dos_index) == []


# -- the per-title markdown document (#330, #335) -----------------------------

def test_markdown_with_no_title_reads_exactly_as_it_always_has(tmp_path):
    """The regression: a caller that names no title must see the same
    document -- no "Match" column and no claim about redrawing."""
    pytest.importorskip("PIL.Image")
    game, disk = _dos_game(), _c64_disk()
    out = tmp_path / "pool.md"
    ip.markdown(game, disk, "large", ip.DEFAULT_COLOURS, out)
    text = out.read_text()
    assert "for Pool of Radiance, for #130" in text
    assert "Match" not in text
    assert "redraws its own art" not in text


def test_markdown_for_curse_says_no_row_needs_judging(tmp_path):
    pytest.importorskip("PIL.Image")
    pool, pool_disk = _dos_game(), _c64_disk()
    curse = _title_dos_game("curse-of-the-azure-bonds")
    disk = _title_c64_disk("curse-of-the-azure-bonds")
    out = tmp_path / "curse.md"
    ip.markdown(curse, disk, "large", ip.DEFAULT_COLOURS, out,
               title="curse-of-the-azure-bonds", reference_game=pool,
               reference_disk=pool_disk)
    text = out.read_text()
    assert "Every row below is the same art Pool of Radiance draws" in text
    assert "no row here needs judging" in text
    assert "redraws this figure" not in text


def test_markdown_for_silver_blades_marks_the_two_redrawn_rows(tmp_path):
    pytest.importorskip("PIL.Image")
    pool, pool_disk = _dos_game(), _c64_disk()
    silver = _title_dos_game("secret-of-the-silver-blades")
    disk = _title_c64_disk("secret-of-the-silver-blades")
    out = tmp_path / "silver.md"
    ip.markdown(silver, disk, "large", ip.DEFAULT_COLOURS, out,
               title="secret-of-the-silver-blades", reference_game=pool,
               reference_disk=pool_disk)
    text = out.read_text()
    assert "redraws its own art for 2 of the rows below" in text
    lines = text.splitlines()
    # Keyed by which image a row draws, since the DOS index "10" and "11"
    # each appear once in the weapon table and once in the head table, and
    # only one of those four rows is the redrawn one.
    head_10 = next(row for row in lines if "dos-head-large-10.png" in row)
    weapon_11 = next(row for row in lines if "dos-weapon-large-11.png" in row)
    head_11 = next(row for row in lines if "dos-head-large-11.png" in row)
    weapon_10 = next(row for row in lines if "dos-weapon-large-10.png" in row)
    assert "redraws this DOS figure" in head_10
    assert "redraws this DOS figure" in weapon_11
    assert "redraws this DOS figure" not in head_11
    assert "redraws this DOS figure" not in weapon_10
    assert (out.parent / "img").is_dir()


# -- the C64 side comes off the title's own disk too (#330, #335) ------------
#
# Donald, 2026-09-05: *"I need to be able to match like to like. I can't do
# that if I don't have the C64 Secrets icons."* Both documents used to draw
# their C64 half off `POOL3.D64` whatever `--title` said, on the strength of
# `SPELLE64` being the identical bytes in all three titles. It is -- and the
# glyphs those option tables *name* live in `CHARPIC00`, which Silver Blades
# redraws in three places, so the claim was true of the screen codes and
# false of the pictures. These are what stops it coming back.

def _title_c64_disk(title: str):
    disk = ip.title_c64_disk(title, None)
    if disk is None:
        pytest.skip(f"needs the {title} C64 disks")
    return disk


@pytest.mark.parametrize("title", ip.DOS_TITLES)
def test_each_title_resolves_a_disk_of_its_own_carrying_the_icon_files(title):
    """`POOL3.D64`, `CURSE_A.D64` and `SILVER-1.D64` here -- but the names
    are not asserted, because what makes a side the right one is that it
    carries all three files, not what it is called."""
    from goldbox.d64 import D64

    disk = _title_c64_disk(title)
    assert disk.name.upper().endswith(".D64"), disk
    names = {entry.name for entry in D64.open(str(disk)).directory()}
    for wanted in ip.C64_ICON_FILES:
        assert wanted in names, (disk.name, wanted)
    #: And the side is one of that title's own, not another game's.
    assert disk.match(games.by_key(title).disk_glob), disk


def test_curse_draws_every_c64_option_exactly_as_pool_of_radiance_does():
    """184 options over both sizes and both kinds, pixel for pixel."""
    assert ip.c64_redrawn_options(_title_c64_disk("curse-of-the-azure-bonds"),
                                  _c64_disk()) == {}


def test_silver_blades_redraws_three_c64_options_and_only_those_three():
    """Weapon 13 at both sizes and large heads 8 and 13, which is what the
    three `CHARPIC00` glyphs 132, 133 and 207 are used by. The claim this
    replaces was that no figure used them (#330, #335)."""
    assert ip.c64_redrawn_options(
        _title_c64_disk("secret-of-the-silver-blades"), _c64_disk()) == {
            ("weapon", 13): ["small", "large"],
            ("head", 8): ["large"],
            ("head", 13): ["large"]}


def test_a_disk_compared_with_itself_redraws_nothing():
    disk = _c64_disk()
    assert ip.c64_redrawn_options(disk, disk) == {}


def test_the_silver_blades_document_names_its_own_disk_and_the_redrawn_rows(
        tmp_path):
    pytest.importorskip("PIL.Image")
    pool, pool_disk = _dos_game(), _c64_disk()
    silver = _title_dos_game("secret-of-the-silver-blades")
    disk = _title_c64_disk("secret-of-the-silver-blades")
    out = tmp_path / "silver.md"
    ip.markdown(silver, disk, "large", ip.DEFAULT_COLOURS, out,
               title="secret-of-the-silver-blades", reference_game=pool,
               reference_disk=pool_disk)
    text = out.read_text()
    assert f"own disk, `{disk.name}`" in text
    assert "3 of the options below are a different picture" in text
    #: Every C64 image the document shows is drawn off Silver Blades' disk,
    #: and Pool of Radiance's only ever appears as the thing a redrawn row is
    #: compared against -- three rows, one image each.
    assert text.count("img/c64-pool-of-radiance-") == 2
    weapon_19 = next(r for r in text.splitlines()
                     if "dos-weapon-large-19.png" in r)
    assert "redraws the C64 option this row names" in weapon_19
    assert "c64-secret-of-the-silver-blades-weapon-large-13.png" in weapon_19


def test_the_c64_image_files_carry_the_title_that_drew_them(tmp_path):
    """The stale-picture trap: the documents are regenerated into a
    directory that already holds the last run's images, and `_c64_png` skips
    a file that exists. With a name that did not say whose disk drew it, a
    Pool of Radiance figure survived a redraw of Silver Blades' document --
    which is the exact failure the change was made to stop."""
    pytest.importorskip("PIL.Image")
    pool, pool_disk = _dos_game(), _c64_disk()
    silver = _title_dos_game("secret-of-the-silver-blades")
    disk = _title_c64_disk("secret-of-the-silver-blades")
    out = tmp_path / "doc.md"
    ip.markdown(pool, pool_disk, "large", ip.DEFAULT_COLOURS, out)
    first = (out.parent / "img" / "c64-pool-of-radiance-weapon-large-13.png"
             ).read_bytes()
    ip.markdown(silver, disk, "large", ip.DEFAULT_COLOURS, out,
               title="secret-of-the-silver-blades", reference_game=pool,
               reference_disk=pool_disk)
    mine = (out.parent / "img" /
            "c64-secret-of-the-silver-blades-weapon-large-13.png").read_bytes()
    assert mine != first, "the second run reused the first run's picture"


def test_with_no_disk_of_its_own_the_document_draws_no_c64_figure(tmp_path):
    """A machine with the DOS archives and none of Silver Blades' C64 disks.
    The document is still written and still shows every DOS figure; what it
    must never do is fill the column with Pool of Radiance's art."""
    pytest.importorskip("PIL.Image")
    pool = _dos_game()
    silver = _title_dos_game("secret-of-the-silver-blades")
    out = tmp_path / "silver.md"
    ip.markdown(silver, None, "large", ip.DEFAULT_COLOURS, out,
               title="secret-of-the-silver-blades", reference_game=pool,
               reference_disk=None)
    text = out.read_text()
    assert "No Commodore 64 figure is drawn in this section." in text
    assert "Not drawn" in text
    assert "img/c64-" not in text
    assert "img/dos-weapon-large-19.png" in text


# -- the four sheets (#325) --------------------------------------------------
#
# `--kind head --size small` used to raise `ValueError: small head 16 is not
# one of 14` on its first mixed row and draw nothing at all -- two of the
# fourteen rows, DOS head 2 and DOS head 8, name a C64 option only the large
# list has. The art is Donald's and stays on his disks, so these skip
# without them.

def _dos_game():
    try:
        return ic.dos_game(None)
    except SystemExit:
        pytest.skip("needs the DOS game files; set POR_DOS_GAME")


def _c64_disk():
    if disk_dir() is None:
        pytest.skip("needs the C64 game disks")
    return ic.c64_disk(None)


@pytest.mark.parametrize("kind,size", [
    ("weapon", "large"), ("weapon", "small"),
    ("head", "large"), ("head", "small"),
])
def test_all_four_sheet_combinations_draw(kind, size, tmp_path):
    """The regression: every `--kind`/`--size` pair used to draw, or not."""
    game, disk = _dos_game(), _c64_disk()
    #: After the two skips above, never before them: CI has neither the game
    #: files nor Pillow, and an import at the top of the body raised
    #: `ModuleNotFoundError` before the missing disks could skip the test.
    Image = pytest.importorskip("PIL.Image")

    path = tmp_path / f"{kind}-{size}.png"
    ip.sheet(game, disk, kind, size, ip.DEFAULT_COLOURS, path)
    assert path.is_file()
    with Image.open(path) as image:
        rows = DOS_HEADS if kind == "head" else DOS_WEAPONS
        assert image.height > rows * 20     # one band a row, at minimum


def test_the_small_head_sheet_names_a_row_past_the_small_list(tmp_path):
    """`#325` was two such rows, DOS head 2 and DOS head 8; Donald edits the

    table by hand and the exact set moves, but as long as any row names a
    C64 option only the large list has, the sheet has to draw it rather than
    raise, and mark it rather than draw it silently at the wrong size.
    """
    game, disk = _dos_game(), _c64_disk()
    from goldbox.iconparts import IconParts

    parts = IconParts.load(str(disk))
    small_head_count = parts.count("small", "head")
    mixed = {dos: c64 for dos, c64 in ip.HEADS.items() if c64 >= small_head_count}
    assert mixed, "no mixed row in the current table; #325 needs one to check"
    assert {2, 8} & set(mixed), mixed

    path = tmp_path / "head-small.png"
    ip.sheet(game, disk, "head", "small", ip.DEFAULT_COLOURS, path)
    assert path.is_file()
