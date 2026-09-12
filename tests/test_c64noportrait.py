"""A C64 character with no sheet portrait, read back honestly.

#503 (A C64 character with no sheet portrait arrives in DOS or on the Amiga
wearing the menu's first head): `HEAD00` is a real portrait -- the menu's
first entry -- so a C64 record with `0x0FE = 0x00` and `0x0FF = 0x00` cannot
be told apart, byte by byte, from a character who really chose it. `BODY00`
is not a menu entry at all (`goldbox.portraits.POOL_OF_RADIANCE_MENU.bodies`
starts at `0x01`), so it is the body byte, not the head byte, that says
"nobody chose a face" -- and the two must be read together.

None of these tests needs a game disk: every C64 record here is built from
zeroes with the two portrait bytes set by hand, and the DOS side is the
neutral vocabulary's own writer.
"""

from __future__ import annotations

from types import SimpleNamespace

from editor import convert
from goldbox import amiga_por, c64_codec, dos_codec, neutral
from goldbox.neutral import NeutralCharacter
from goldbox.portraits import PortraitTables
from goldbox.record import CharacterRecord

#: A synthetic menu with the same shape as Pool of Radiance's own real one:
#: fourteen heads with `HEAD00` -- art id `0x00` -- as the menu's first
#: entry, and twelve bodies starting at `0x01`, since `BODY00` names no art
#: on any port. A test does not depend on which other ids the game ships.
MENU = PortraitTables(heads=(0,) + tuple(range(1, 14)),
                      bodies=tuple(range(1, 13)),
                      source="synthetic, for this test")


def _c64_record(head: int, body: int) -> CharacterRecord:
    rec = CharacterRecord(bytes(CharacterRecord.SIZE))
    rec.set("portrait_head", head)
    rec.set("portrait_body", body)
    return rec


# -- the C64 record read into the neutral vocabulary -------------------------

def test_a_c64_record_holding_zero_in_both_portrait_bytes_reads_as_no_portrait():
    out = c64_codec.read(_c64_record(0x00, 0x00), game="pool-of-radiance")
    assert "portrait_head" not in out, out.get("portrait_head")
    assert "portrait_body" not in out, out.get("portrait_body")


def test_a_real_first_head_still_reads_as_the_choice_it_is():
    """The control: `HEAD00` with a real body is a character who really
    chose the menu's first head, and must not be swallowed by the fix
    above -- only a `BODY00` says "no portrait", not a `HEAD00`."""
    out = c64_codec.read(_c64_record(0x00, 0x04), game="pool-of-radiance")
    assert out.get("portrait_head") == 0x00
    assert out.get("portrait_body") == 0x04


def test_a_nonzero_head_with_no_body_still_reads_as_no_portrait():
    """`BODY00` is not a menu entry on any port, so a record holding it is
    read as having no portrait at all, whatever the head byte says -- an
    engine never writes this combination, and the fix does not need it to,
    but the rule is the body byte alone and not "both zero"."""
    out = c64_codec.read(_c64_record(0x08, 0x00), game="pool-of-radiance")
    assert "portrait_head" not in out
    assert "portrait_body" not in out


# -- the whole conversion: C64 to DOS -----------------------------------------

def test_a_c64_character_with_no_portrait_converts_to_dos_with_no_drop():
    """Fails today: the old reader gave DOS `portrait_head=0x00` (a real
    id, HEAD00) and no `portrait_body`, so `dos.write` wrote head position 1
    -- a face the character never chose -- and reported the body dropped
    over a body he never had.
    """
    neutral_char = c64_codec.read(_c64_record(0x00, 0x00),
                                  game="pool-of-radiance")
    rec, _itm, _spc, rep = dos_codec.write(neutral_char, portraits=MENU)
    assert not [d for d in rep.dropped if "portrait" in d.lower()], \
        rep.dropped
    head_field = dos_codec.FIELDS_BY_NAME["portrait_head"]
    body_field = dos_codec.FIELDS_BY_NAME["portrait_body"]
    assert rec[head_field.offset] == 0, "wrote a menu position for a face " \
        "the character never chose"
    assert rec[body_field.offset] == 0


def test_a_c64_character_with_a_real_first_head_still_converts_to_position_one():
    """The control that says the fix did not swallow a real choice: a
    record holding `HEAD00` and a real body still converts to DOS menu
    position 1 for the head, which is correct -- `HEAD00` really is the
    menu's first entry."""
    neutral_char = c64_codec.read(_c64_record(0x00, 0x04),
                                  game="pool-of-radiance")
    rec, _itm, _spc, rep = dos_codec.write(neutral_char, portraits=MENU)
    assert not [d for d in rep.dropped if "portrait" in d.lower()], \
        rep.dropped
    head_field = dos_codec.FIELDS_BY_NAME["portrait_head"]
    body_field = dos_codec.FIELDS_BY_NAME["portrait_body"]
    assert rec[head_field.offset] == 1
    assert rec[body_field.offset] == 4


# -- the Amiga savegame's own portrait switch (editor/convert.py:793) --------

def test_a_party_on_the_menus_first_head_still_switches_portraits_on(
        monkeypatch):
    """Every character in this party chose `HEAD00` and a real body -- the
    field is present and true to what the reader saw -- so the built
    savegame's own switch must come out true.  Fails today: `c.get(
    "portrait_head")` reads a real `0` as falsy and switches it off, over a
    party none of whom lack a face.
    """
    captured: dict = {}

    def fake_new_por_savegame(state, slot, n, ecl_dax, portraits):
        captured["portraits"] = portraits
        return b"savegame", SimpleNamespace(converted=[])

    def fake_make_por_save_disk(slot, party, savegame, icons=None):
        return SimpleNamespace(verify=lambda: [], to_bytes=lambda: b"disk")

    def fake_write_por(char, icon=None):
        return b"rec", b"itm", b"spc", neutral.Report()

    monkeypatch.setattr(amiga_por, "new_por_savegame", fake_new_por_savegame)
    monkeypatch.setattr(amiga_por, "make_por_save_disk", fake_make_por_save_disk)
    monkeypatch.setattr(amiga_por, "write_por", fake_write_por)

    party = []
    for _ in range(2):
        char = NeutralCharacter("C64")
        char.set("portrait_head", 0x00, "test")
        char.set("portrait_body", 0x04, "test")
        party.append(char)

    convert._rehearse_por_savegame(None, "A", party, b"")
    assert captured["portraits"] is True


def test_a_party_with_no_faces_at_all_still_switches_portraits_off(
        monkeypatch):
    """The control: nobody in this party has either portrait field set, so
    the switch is correctly false."""
    captured: dict = {}

    def fake_new_por_savegame(state, slot, n, ecl_dax, portraits):
        captured["portraits"] = portraits
        return b"savegame", SimpleNamespace(converted=[])

    def fake_make_por_save_disk(slot, party, savegame, icons=None):
        return SimpleNamespace(verify=lambda: [], to_bytes=lambda: b"disk")

    def fake_write_por(char, icon=None):
        return b"rec", b"itm", b"spc", neutral.Report()

    monkeypatch.setattr(amiga_por, "new_por_savegame", fake_new_por_savegame)
    monkeypatch.setattr(amiga_por, "make_por_save_disk", fake_make_por_save_disk)
    monkeypatch.setattr(amiga_por, "write_por", fake_write_por)

    party = [NeutralCharacter("C64") for _ in range(2)]

    convert._rehearse_por_savegame(None, "A", party, b"")
    assert captured["portraits"] is False
