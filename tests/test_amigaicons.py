from __future__ import annotations

"""The Amiga Curse and Silver Blades combat-icon art, against DOS's own.

`#396 (Whether an Amiga Curse or Silver Blades record's combat-icon fields
share DOS's own numbering is unmeasured)`.  Every assertion here is a
measurement taken off the player's own disks by `tools/amigaicons.py`, and
every one of them would go red if a later change to the reader silently
started reading the tiles at the wrong stride, in the wrong plane order, or
through a translation table that was fitted to the art rather than read out of
the executable.

`docs/199-amiga-combat-icons.md` is the write-up.  Nothing here commits any of
the game's bytes: the counts are counts and the two tables are integers read
at a named address.
"""

import functools

import pytest

from tools import amigaicons, gamedisks

#: The sixteen-entry table both executables hold: a DOS pixel value's Amiga
#: palette entry.  Read at `/Curse` `g0ee4` and `/Secret` `g2374`.
TRANSLATION = (0, 7, 12, 13, 2, 14, 11, 9, 8, 6, 5, 15, 3, 10, 4, 1)

#: The six part codes a record's `icon_colours` bytes are written through --
#: body, arm, leg, hair, shield, weapon -- at `/Curse` `g1bb9` and `/Secret`
#: `g1f76`.  `goldbox.dos.DOS_PAIR_CLASSES` is DOS's own copy.
PARTS = (1, 2, 3, 4, 6, 7)

#: How many `CHEAD` and `CBODY` blocks each library holds: fourteen heads and
#: thirty-two bodies, at two sizes in two poses.
HEAD_BLOCKS, BODY_BLOCKS = 56, 128

#: The one place the Amiga art is not the DOS art: the hat-and-plume
#: highlight, DOS pixel value 13, which the Amiga tiles hold as palette entry
#: 0 rather than the 20 the translation table asks for.  Neither entry is
#: recoloured by anything a player chooses, so this is a fixed difference in
#: the drawing and not a field anybody converts.
PLUME_HIGHLIGHT = {"curse-of-the-azure-bonds": 42,
                   "secret-of-the-silver-blades": 50}


def _disks():
    if not gamedisks.candidates("amiga"):
        pytest.skip("no Amiga disks; set $AMIGA_DISKS")


@functools.lru_cache(maxsize=1)
def _art():
    """One disk's worth of `CHEAD.TLB`/`CBODY.TLB` per title.

    Two copies of each Amiga set are on this machine and their art drawers
    are byte-identical, so which copy answers does not matter; taking the
    first keeps the comparison from being run twice over.  Pools of Darkness'
    disk 3 carries a `CHEAD.TLB` too and `_belongs` leaves it out: it is that
    title's *portrait* library, not a third copy of these.
    """
    out = {}
    for volume, files in sorted(amigaicons.find_art().items()):
        for key in amigaicons.TITLES:
            if amigaicons._belongs(volume, key):
                out.setdefault(key, (volume, files))
    return out


@functools.lru_cache(maxsize=None)
def _executable(key: str) -> bytes:
    found = amigaicons.find_executable(amigaicons.TITLES[key]["exe"])
    if found is None:
        pytest.skip(f"no /{amigaicons.TITLES[key]['exe']} on any disk here")
    return found[1]


def _title_art(key: str):
    _disks()
    art = _art()
    if key not in art:
        pytest.skip(f"no Amiga {key} art disk here")
    _volume, files = art[key]
    return (amigaicons.tiles(files["CHEAD.TLB"], "CHEAD.TLB"),
            amigaicons.tiles(files["CBODY.TLB"], "CBODY.TLB"))


def _dos_art(key: str):
    where = amigaicons.dos_directory(amigaicons.TITLES[key]["dos_dir"])
    if where is None:
        pytest.skip(f"no DOS {key} game directory; set $FR_ARCHIVES")
    return (amigaicons.dos_tiles(where / "CHEAD.DAX"),
            amigaicons.dos_tiles(where / "CBODY.DAX"))


# ---------------------------------------------------------------------------
# The tables, read out of the two executables
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("key", sorted(amigaicons.TITLES))
def test_both_titles_translate_a_dos_pixel_the_same_way(key):
    """The table is the engine's, not one fitted to the pictures.

    Both executables hold the same sixteen bytes, and the icon routine reads
    them to turn the nibble a player chose into a palette entry -- so a
    conversion writing DOS's own colour nibbles is writing what this table
    expects.
    """
    _disks()
    data = _executable(key)
    base = amigaicons.data_hunk(data)
    at = amigaicons.TITLES[key]["tables"]["colour"]
    assert tuple(data[base + at:base + at + 16]) == TRANSLATION


@pytest.mark.parametrize("key", sorted(amigaicons.TITLES))
def test_the_six_recoloured_parts_are_dos_own_six(key):
    """Body, arm, leg, hair, shield, weapon -- the same six in the same order
    as DOS's `ds:0x3CF5` table, so the six `icon_colours` bytes mean the same
    parts on both ports."""
    _disks()
    data = _executable(key)
    base = amigaicons.data_hunk(data)
    at = amigaicons.TITLES[key]["tables"]["parts"]
    assert tuple(data[base + at:base + at + 6]) == PARTS


@pytest.mark.parametrize("key", sorted(amigaicons.TITLES))
def test_size_one_is_the_small_library_and_size_two_the_large(key):
    """`size` indexes a letter table whose entries 1 and 2 are `S` and `T`,
    exactly as DOS's `04 53 54` does, and the block loader adds 0x40 for the
    `T`.  A conversion that wrote 0 or 3 here would name no file."""
    _disks()
    data = _executable(key)
    base = amigaicons.data_hunk(data)
    at = amigaicons.TITLES[key]["tables"]["letter"]
    assert data[base + at + 1:base + at + 3] == b"ST"


# ---------------------------------------------------------------------------
# The art
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("key", sorted(amigaicons.TITLES))
def test_the_amiga_libraries_hold_dos_own_block_ids(key):
    """56 head blocks and 128 body blocks, and the *same numbers* -- 0-13,
    64-77, 128-141, 192-205 for a head.  An Amiga library that had renumbered
    its art would fail here before any pixel was compared."""
    heads, bodies = _title_art(key)
    dos_heads, dos_bodies = _dos_art(key)
    assert len(heads) == HEAD_BLOCKS and len(bodies) == BODY_BLOCKS
    assert sorted(heads) == sorted(dos_heads)
    assert sorted(bodies) == sorted(dos_bodies)


@pytest.mark.parametrize("key", sorted(amigaicons.TITLES))
def test_every_body_block_is_the_dos_block_through_the_engines_table(key):
    """73728 pixels a title, and every one of them predicted.

    This is what makes the numbering claim a measurement: Amiga body 17 is
    not merely *a* figure, it is DOS body 17's own pixels.
    """
    _heads, bodies = _title_art(key)
    _dos_heads, dos_bodies = _dos_art(key)
    checked, wrong = 0, 0
    for art, (height, width, rows) in sorted(bodies.items()):
        dos_height, dos_width, dos_rows = dos_bodies[art]
        assert (height, width) == (dos_height, dos_width) == (24, 24)
        for r in range(height):
            for x in range(width):
                checked += 1
                want = amigaicons.predicted(dos_rows[r][x], TRANSLATION)
                wrong += rows[r][x] != want
    assert (checked, wrong) == (BODY_BLOCKS * 24 * 24, 0)


@pytest.mark.parametrize("key", sorted(amigaicons.TITLES))
def test_the_heads_differ_only_in_the_plume_highlight(key):
    """Every head pixel is DOS's too, bar the hat highlight.

    42 pixels in Curse and 50 in Silver Blades hold palette entry 0 where the
    DOS block holds pixel value 13 and the engine's table asks for 20.  It is
    named rather than tolerated: a reader bug would not land on one DOS value
    and leave the other fifteen exact.
    """
    heads, _bodies = _title_art(key)
    dos_heads, _dos_bodies = _dos_art(key)
    odd, wrong = 0, 0
    for art, (height, width, rows) in sorted(heads.items()):
        dos_height, dos_width, dos_rows = dos_heads[art]
        assert (height, width) == (dos_height, dos_width)
        for r in range(height):
            for x in range(width):
                want = amigaicons.predicted(dos_rows[r][x], TRANSLATION)
                if rows[r][x] == want:
                    continue
                if (dos_rows[r][x], rows[r][x]) == (13, 0):
                    odd += 1
                else:
                    wrong += 1
    assert (odd, wrong) == (PLUME_HIGHLIGHT[key], 0)


def test_silver_blades_redrew_the_same_four_blocks_on_both_ports():
    """`docs/168-dos-dax-and-combat-icons.md` measured Silver Blades redrawing
    DOS head 10 large and body 11 small.  The Amiga carries the same two
    re-draws and nothing else, so the per-title override
    `tools/iconproposal.yaml` holds for a Silver Blades record whichever port
    it came off."""
    curse_heads, curse_bodies = _title_art("curse-of-the-azure-bonds")
    ssb_heads, ssb_bodies = _title_art("secret-of-the-silver-blades")
    heads = [a for a in sorted(curse_heads) if curse_heads[a] != ssb_heads[a]]
    bodies = [a for a in sorted(curse_bodies)
              if curse_bodies[a] != ssb_bodies[a]]
    assert (heads, bodies) == ([74, 202], [11, 139])


# ---------------------------------------------------------------------------
# The specimens
# ---------------------------------------------------------------------------
def test_every_specimen_names_art_that_is_on_the_disks():
    """The 21 Curse and Silver Blades records, each `(icon_head, icon_body,
    size)` resolved to the four blocks the loader would ask for.

    A record holding a number outside the menu's range, or a size the letter
    table has no entry for, would name a block no library holds -- which is
    the failure this would catch if the fields turned out not to be these
    fields after all.
    """
    _disks()
    lines: list[str] = []
    assert amigaicons.report_census(lines.append) == 0
    assert lines[-1].endswith("records")
    assert int(lines[-1].split()[0]) == 21


# ---------------------------------------------------------------------------
# The reader itself
# ---------------------------------------------------------------------------
def test_a_file_that_is_not_a_glib_container_is_named_as_such():
    """`.TLB` is not the `.dax` `goldbox/amiga_dax.py` reads, and a caller
    handing one to the other gets a sentence rather than a struct error."""
    with pytest.raises(amigaicons.GlibError) as raised:
        amigaicons.glib_blocks(b"DOS\0" + bytes(40), "ecl.dax")
    assert "ecl.dax" in str(raised.value)
    assert "not a GLIB container" in str(raised.value)


def test_a_glib_whose_first_block_is_not_a_tile_index_is_named_too():
    """Pools of Darkness' disk 3 carries its own `CHEAD.TLB` -- the portrait
    art, in a container whose block 0 is empty -- so an unfiltered sweep meets
    one, and it has to say which file rather than raise a struct error."""
    with pytest.raises(amigaicons.GlibError) as raised:
        amigaicons.tile_index(b"", "Disk3_CHEAD.TLB")
    assert "Disk3_CHEAD.TLB" in str(raised.value)
    assert "not a tile index" in str(raised.value)


def test_the_icon_menu_wraps_the_head_at_13_and_the_body_at_31():
    """Found with `tools/amigarecordrefs.py`, and the reason 14 and 32 are
    claims about the Amiga rather than borrowed from DOS.

    A menu that offered fifteen heads would put an `icon_head` of 14 in a
    record, and a conversion writing DOS's fourteen would then be writing a
    narrower range than the destination allows -- so the compare is the
    measurement, not the specimens.
    """
    _disks()
    from tools import amigarecordrefs
    for key, head, body in (("curse-of-the-azure-bonds", 0x145, 0x146),
                            ("secret-of-the-silver-blades", 0xEF, 0xF0)):
        data = _executable(key)
        start, end = amigarecordrefs.code_range(data)
        for at, last in ((head, 0xD), (body, 0x1F)):
            wraps = [text for _where, text
                     in amigarecordrefs.sites(data, at, start, end)
                     if text == f"cmpi.b #${last:x}, ${at:x}(a0)"]
            assert wraps, f"{key}: nothing compares +0x{at:X} against {last}"


def test_the_engine_writes_one_into_icon_dimension_at_creation():
    """`icon_dimension` is 1 in all 21 specimens, and this is why: both
    binaries hold an immediate store of 1 into that byte, which is DOS's own
    `mov byte es:[di+0x6C], 1`.  A constant across specimens is not a
    constant; a store in the engine is."""
    _disks()
    from tools import amigarecordrefs
    for key, at in (("curse-of-the-azure-bonds", 0xDE),
                    ("secret-of-the-silver-blades", 0x81)):
        data = _executable(key)
        start, end = amigarecordrefs.code_range(data)
        stores = [text for _where, text
                  in amigarecordrefs.sites(data, at, start, end)
                  if text.startswith("move.b #$1, ")]
        assert stores, f"{key}: nothing writes 1 into +0x{at:X}"


def test_a_transparent_pixel_is_the_only_odd_numbered_prediction():
    """The plane order is the finding, so it is asserted rather than assumed:
    plane 0 is the transparency mask and planes 1-4 the four-bit colour, which
    makes a tile's number `2 * entry` for everything the character draws and
    1 for the hole it does not."""
    predictions = [amigaicons.predicted(v, TRANSLATION) for v in range(16)]
    assert predictions[0] == 1
    assert all(p % 2 == 0 for p in predictions[1:])
    assert sorted(predictions) == sorted({1} | {2 * TRANSLATION[v]
                                                for v in range(1, 16)})
