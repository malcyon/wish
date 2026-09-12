from __future__ import annotations

"""A source-side drop line must not name a destination it does not know yet.

`#389 (A conversion to the Amiga tells the player what DOS does with their
character)`: convert a C64 party to the Amiga, and the combat-figure drop
line said "DOS draws its own combat art...", because
`goldbox.c64_codec.READ_DROPPED_PLAYER_TEXT["region_220"]` is composed while
reading the *source* record, before any writer -- DOS or Amiga -- has been
chosen, and it hard-coded "DOS" anyway.

Also covers the sibling defect on the write side: `goldbox.c64_codec.write`
dropped a combat icon with a line naming a file (`CHARPIC00`) and counting
screen codes and colours in front of a player, which `.claude/rules/
gui-text.md` bans, and opened lower-case, which `AGENTS.md` bans everywhere a
composed line reaches a reader.

The read-side reproduction is the exact one `#389`'s finding used: a C64
Silver Blades party the C64 engine itself wrote
(`WISH-SPEC-ssb-d-engine-resave.D64`), converted to Amiga Silver Blades with
`goldbox.amiga_later.write_later`.  The write-side one needs no specimen tree: any
Amiga Pool of Radiance record converted to the C64 has no computed combat
icon to pass in, so `write`'s `else` branch always fires.

A fourth and fifth instance turned up in `goldbox.dos_codec.write` itself, on the
sweep the issue asked for once the three read-side ones above were closed:
`write` always builds a DOS record, even when `goldbox.amiga_por.write_por` and
`write_later` are re-cutting it into an Amiga one, and it named "DOS" in
composed drop lines regardless of which writer was really asking. `write`
now takes an `into` parameter, defaulting to `"DOS"` for a direct write and
passed as `"Amiga"` by both Amiga writers, so the same sentence names the
destination that is actually being written -- `test_a_c64_pool_of_radiance_
party_converted_to_the_amiga_names_no_platform` is the portrait instance a
live C64 specimen reaches, and `test_an_amiga_source_character_converted_to_
the_amiga_names_no_platform` is the `encumbrance` instance an Amiga-sourced
character reaches.  Three more of `write`'s canned drop reasons named "DOS"
without being reachable by any specimen this project can build today
(`former_levels` and `abilities_second` need a Pool of Radiance character
carrying a dual-class field Pool of Radiance has no way to set; `turn_power`
and `infravision` are silenced project-wide) and were reworded for
consistency rather than left as a trap for the day one of them is.

A sixth turned up in `goldbox.amiga_por.to_neutral` (the Amiga Pool of Radiance
*reader*): its trailing-pad drop line named "the DOS record" while reading
the source, before any writer was chosen, and `tests/test_amigatoc64.py`
already proves an Amiga Pool of Radiance save converts to the C64 as well as
to DOS -- the same read-before-you-know-the-destination shape `region_220`
had.
"""

import re

import pytest
from gamedata import specimen_root
from test_amiga import amiga_por_records
from test_amigalaterwrite import engine_written_parties
from test_doslatertitles import _c64_disk, _c64_party

from goldbox import amiga_later, amiga_por, c64_codec, dos_codec, dos_port

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

#: A whole word, so a name that happens to contain the letters does not
#: false-positive; `re.IGNORECASE` catches a stray lower-case "dos".
NAMES_DOS = re.compile(r"\bDOS\b", re.IGNORECASE)

#: Same idea, for the third instance the issue's own comments traced:
#: `goldbox.dos_codec.to_neutral`'s portrait drop naming "C64" while reading a DOS
#: record, before any writer -- C64 or Amiga -- has been chosen.
NAMES_C64 = re.compile(r"\bC64\b", re.IGNORECASE)


def test_region_220s_player_text_names_no_platform():
    """The static table: no reader knows its destination yet, so its drop
    text must read the same regardless of which writer uses it."""
    text = c64_codec.READ_DROPPED_PLAYER_TEXT["region_220"]
    assert not NAMES_DOS.search(text), text


def test_the_c64_combat_icon_drop_names_no_file_or_byte_count():
    """Every Amiga Pool of Radiance record on the machine, converted to the
    C64 with no icon supplied -- the branch that used to name `CHARPIC00`
    and count screen codes and colours in front of a player."""
    seen = 0
    for path in amiga_por_records():
        c = amiga_por.read_amiga_por(path)
        n = amiga_por.to_neutral(c)
        _rec, rep = c64_codec.write(n)
        lines = [d for d in rep.dropped if d.lower().startswith("combat icon")]
        assert lines, (path, rep.dropped)
        for line in lines:
            assert "CHARPIC00" not in line, (path, line)
            assert not re.search(r"\d+ (screen codes|colours)", line), \
                (path, line)
            assert line[:1] == line[:1].upper(), (path, line)
        seen += 1
    assert seen >= 1, seen


def test_a_c64_party_converted_to_the_amiga_names_no_platform():
    """Live reproduction of `#389`'s own finding: six of six Silver Blades
    characters, converted with the exact command the issue used
    (`tools/amigalaterwrite.py --source .../WISH-SPEC-ssb-d-engine-resave.D64`).
    """
    root = specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    path = _c64_disk("ssb-d-engine-resave")
    _game, party = _c64_party(path)
    assert len(party) == 6
    checked = 0
    for char in party:
        _built, report = amiga_later.write_later(char)
        for line in report.dropped:
            assert not NAMES_DOS.search(line), (char.get("name"), line)
            assert "CHARPIC00" not in line, (char.get("name"), line)
            assert line[:1] == line[:1].upper(), (char.get("name"), line)
        checked += 1
    assert checked == 6


def test_an_amiga_pool_of_radiance_source_names_no_platform():
    """The sixth instance: `goldbox.amiga_por.to_neutral` reads an Amiga Pool of
    Radiance record through a DOS-shaped intermediate table
    (`goldbox.amiga_por.to_dos_record`) and reported its own trailing pad byte as
    something "the DOS record has no room for" -- unconditionally, while
    reading the source, before `to_neutral` or `write_por` know whether the
    destination is DOS, the C64 or another Amiga save.

    Every Amiga Pool of Radiance record `tests/test_amiga.py`'s own
    `amiga_por_records` can reach on this machine hits the branch, and
    `tests/test_amigatoc64.py` is the proof that the C64 is a real
    destination for this same source.
    """
    from test_amiga import amiga_por_records

    paths = amiga_por_records()
    if not paths:
        pytest.skip("needs an Amiga Pool of Radiance disk; see "
                    "tools/gamedisks.py")
    checked = 0
    for path in paths:
        char = amiga_por.read_amiga_por(path)
        neutral = amiga_por.to_neutral(char)
        lines = [d for d in neutral.dropped if "0x11F" in d]
        assert lines, (path, neutral.dropped)
        for line in lines:
            assert not NAMES_DOS.search(line), (path, line)
        checked += 1
    assert checked >= 1


def test_a_dos_portrait_the_menu_cannot_answer_for_names_no_platform():
    """The third instance the issue's own comments traced:
    `goldbox.dos_codec.to_neutral`'s portrait block named "C64" unconditionally,
    while reading the *source* DOS record -- before any writer, C64 or
    Amiga, has been chosen -- so a DOS-to-Amiga conversion inherited a claim
    about the C64 the same way the C64-to-Amiga direction inherited one
    about DOS.

    A synthetic all-zero Pool of Radiance record with `portrait_body` set to
    13 -- outside a synthetic fourteen-head, twelve-body menu -- needs no
    game disk: it is the same reproduction `test_dosconvert.py`'s portrait
    tests use, `PortraitTables._art`'s own `1 <= n <= len(table)` gate.
    """
    from goldbox.portraits import PortraitTables

    tables = PortraitTables(heads=tuple(range(1, 15)),
                             bodies=tuple(range(1, 13)),
                             source="synthetic, for this test")
    raw = bytearray(bytes(dos_codec.POOL_OF_RADIANCE.record_size))
    raw[dos_port.FIELDS_BY_NAME["portrait_body"].offset] = 13  # outside
    odd = dos_codec.DosCharacter(bytes(raw))                            # the menu
    neutral = dos_codec.to_neutral(odd, portraits=tables)
    lines = [d for d in neutral.dropped if "portrait (body)" in d.lower()]
    assert lines, neutral.dropped
    for line in lines:
        assert not NAMES_C64.search(line), line


def test_a_c64_pool_of_radiance_party_converted_to_the_amiga_names_no_platform():
    """The write side of the same bug, found after the three read-side
    instances above were fixed: `goldbox.dos_codec.write` builds a `portrait_head`/
    `portrait_body` drop line naming "the DOS record" unconditionally, and
    `goldbox.amiga_por.write_por` builds every Amiga Pool of Radiance record out
    of `goldbox.dos_codec.write`'s own -- so a C64 party with no creation-menu
    tables at hand for the Amiga side inherited a claim about DOS the same
    way `#389`'s Silver Blades combat-figure line inherited one.

    `WISH-SPEC-por-c64-hall-resave` is a Pool of Radiance C64 save with a
    head and body portrait set on every character, which used to be what
    made the branch fire: before `#479 (A Pool of Radiance party converted
    to an Amiga save disk loses every character's sheet portrait, because
    the Amiga writer never asks for the creation menu)`, `write_por` asked
    for no creation-menu tables at all, so every portrait was dropped for
    that reason alone.  It now asks for the Amiga's own menu and this
    party's faces are all in it, so nothing here drops any more -- the
    thing #479 fixed.  What this test is actually proving still needs a
    portrait no menu can place, so `portrait_head` is forced to `0xFF`,
    an id past both ports' fourteen-entry table.
    """
    path = _c64_disk("por-c64-hall-resave")
    _game, party = _c64_party(path)
    assert len(party) >= 1
    checked = 0
    for char in party:
        char.set("portrait_head", 0xFF,
                  "forced past the menu, so the drop this test needs fires "
                  "regardless of #479's fix")
        _record, _itm, _spc, report = amiga_por.write_por(char)
        portrait_lines = [d for d in report.dropped
                          if d.startswith("portrait_")]
        assert portrait_lines, (char.get("name"), report.dropped)
        for line in portrait_lines:
            assert not NAMES_DOS.search(line), (char.get("name"), line)
        checked += 1
    assert checked >= 1


def test_an_amiga_source_character_converted_to_the_amiga_names_no_platform():
    """A different field than `#389`'s own finding, in the same shape:
    `goldbox.dos_codec.WRITE_DROPPED`'s `encumbrance` reason said "the identity the
    DOS engine itself uses", and `goldbox.amiga_later.write_later` copies
    `goldbox.dos_codec.write`'s report verbatim -- so an Amiga Curse or Silver
    Blades character, which carries `encumbrance` on read
    (`goldbox.amiga_later.to_neutral_later`), was told about a DOS engine on its
    way to another Amiga save.

    `engine_written_parties` is `tests/test_amigalaterwrite.py`'s corpus of
    saved games the two later engines themselves wrote.
    """
    parties = engine_written_parties()
    if not parties:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    checked = 0
    for label, char in parties:
        neutral_char = amiga_later.to_neutral_later(char)
        assert "encumbrance" in neutral_char, (label, char.name)
        _built, report = amiga_later.write_later(neutral_char)
        for line in report.dropped:
            assert not NAMES_DOS.search(line), (label, char.name, line)
        checked += 1
    assert checked >= 1
