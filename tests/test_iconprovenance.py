"""`#379 (The DOS writer's byte accounting says an Amiga party's combat
figure was recognised off C64 screen codes)`.

`goldbox.dos.write`'s byte-accounting report used to say every `DosIcon` it
was handed had been read back off eighteen C64 screen codes and looked up
through `tools/iconreverse.yaml`, whatever port actually built it. An Amiga
Pool of Radiance record stores `icon_head`, `icon_body` and `icon_colours` at
the same offsets DOS does, so `editor.convert.amiga_combat_icon` copies the
numbers across unchanged -- nothing is recognised, composed or looked up, and
the sentence named a route the bytes did not take.

The fix moves the sentence onto `goldbox.iconparts.DosIcon` itself, built by
whoever made the icon -- `IconParts.dos_icon_from_c64` for a C64 source and
`amiga_combat_icon` for an Amiga one -- so `write` only ever quotes it.
"""

from gamedata import game_file
from test_neutral import _filled

from goldbox import dos, dos_layout
from goldbox.iconparts import IconParts, c64_icon_tables


def _synthetic_dos_char(head: int, body: int, colours: bytes, size: int = 2):
    """A `goldbox.dos.DosCharacter` carrying nothing but a combat figure --
    enough for `editor.convert.amiga_combat_icon`, which reads only
    `icon_head`, `icon_body`, `icon_colours` and `size`.

    `amiga_combat_icon` takes the `DosCharacter` `goldbox.amiga.
    to_dos_record` already re-cut an Amiga record into (`goldbox.amiga.
    read_por_slot`'s own list), so handing it one built directly exercises
    the same code `amiga_combat_icon` runs without needing an Amiga `.adf`.
    """
    f_head = dos_layout.FIELDS_BY_NAME["icon_head"]
    f_body = dos_layout.FIELDS_BY_NAME["icon_body"]
    f_colours = dos_layout.FIELDS_BY_NAME["icon_colours"]
    f_size = dos_layout.FIELDS_BY_NAME["size"]
    raw = bytearray(dos_layout.RECORD_SIZE)
    raw[f_head.offset] = head
    raw[f_body.offset] = body
    raw[f_size.offset] = size
    raw[f_colours.offset:f_colours.end] = colours
    return dos.DosCharacter(bytes(raw))


def test_an_amiga_sourced_icon_report_names_no_c64_mechanism():
    """Watched failing before the fix: the line read exactly the C64
    sentence below, off an icon nothing had recognised."""
    from editor.convert import amiga_combat_icon

    icon = amiga_combat_icon(
        _synthetic_dos_char(head=5, body=9, colours=bytes.fromhex(
            "11223344e6f7")))
    rec, _, _, rep = dos.write(_filled(), icon=icon)
    f_head = dos_layout.FIELDS_BY_NAME["icon_head"]
    f_colours = dos_layout.FIELDS_BY_NAME["icon_colours"]
    assert rec[f_head.offset] == 5

    head_line = rep.sources[f_head.offset]
    colours_line = rep.sources[f_colours.offset]
    for line in (head_line, colours_line):
        assert "recognised" not in line, line
        assert "screen codes" not in line, line
        assert "iconreverse" not in line, line
        assert "Amiga" in line, line
    # It says what did happen instead: the number was already there.
    assert "already" in head_line and "copied" in head_line, head_line
    assert "already" in colours_line and "copied" in colours_line, colours_line


def test_a_c64_sourced_icon_report_is_unchanged():
    """The control: the sentence `dos_icon_from_c64` builds for a real C64
    icon reads exactly as it did before `DosIcon` carried its own
    provenance."""
    parts = IconParts(game_file("SPELLE64"), game_file("SPELLN64"))
    icon36 = parts.compose("large", 7, 4) + bytes.fromhex(
        "0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e")
    icon = parts.dos_icon_from_c64(icon36, c64_icon_tables())
    rec, _, _, rep = dos.write(_filled(), icon=icon)
    f_head = dos_layout.FIELDS_BY_NAME["icon_head"]
    f_body = dos_layout.FIELDS_BY_NAME["icon_body"]
    f_colours = dos_layout.FIELDS_BY_NAME["icon_colours"]

    head_line = rep.sources[f_head.offset]
    body_line = rep.sources[f_body.offset]
    colours_line = rep.sources[f_colours.offset]
    assert head_line == (
        f"icon_head: {rec[f_head.offset]} -- the C64 source record's own "
        f"combat icon, recognised off its eighteen screen codes and looked "
        f"up through tools/iconreverse.yaml (#320, weapon "
        f"{icon.choice.weapon_size} {icon.choice.weapon}, head "
        f"{icon.choice.head_size} {icon.choice.head})")
    assert body_line == (
        f"icon_body: {rec[f_body.offset]} -- the C64 source record's own "
        f"combat icon, recognised off its eighteen screen codes and looked "
        f"up through tools/iconreverse.yaml (#320, weapon "
        f"{icon.choice.weapon_size} {icon.choice.weapon}, head "
        f"{icon.choice.head_size} {icon.choice.head})")
    assert colours_line == (
        f"icon_colours: {icon.colours.hex()} -- the C64 source record's "
        f"own combat icon colours, converted through the same table's "
        f"colour rows (#320)")


def test_written_bytes_are_the_icon_numbers_either_way():
    """The prose changed; the bytes did not, for either source."""
    from editor.convert import amiga_combat_icon

    f_head = dos_layout.FIELDS_BY_NAME["icon_head"]
    f_body = dos_layout.FIELDS_BY_NAME["icon_body"]
    f_colours = dos_layout.FIELDS_BY_NAME["icon_colours"]

    amiga_icon = amiga_combat_icon(
        _synthetic_dos_char(head=5, body=9, colours=bytes.fromhex(
            "11223344e6f7")))
    rec, _, _, _ = dos.write(_filled(), icon=amiga_icon)
    assert rec[f_head.offset] == 5
    assert rec[f_body.offset] == 9
    assert rec[f_colours.offset:f_colours.end] == bytes.fromhex(
        "11223344e6f7")

    parts = IconParts(game_file("SPELLE64"), game_file("SPELLN64"))
    icon36 = parts.compose("large", 7, 4) + bytes.fromhex(
        "0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e")
    c64_icon = parts.dos_icon_from_c64(icon36, c64_icon_tables())
    rec2, _, _, _ = dos.write(_filled(), icon=c64_icon)
    assert rec2[f_head.offset] == c64_icon.head
    assert rec2[f_body.offset] == c64_icon.body
    assert rec2[f_colours.offset:f_colours.end] == c64_icon.colours
