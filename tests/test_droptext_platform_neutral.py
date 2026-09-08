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
`goldbox.amiga.write_later`.  The write-side one needs no specimen tree: any
Amiga Pool of Radiance record converted to the C64 has no computed combat
icon to pass in, so `write`'s `else` branch always fires.
"""

import re

import pytest
from gamedata import specimen_root
from test_amiga import amiga_por_records
from test_doslatertitles import _c64_disk, _c64_party

from goldbox import amiga, c64_codec, dos, dos_layout

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

#: A whole word, so a name that happens to contain the letters does not
#: false-positive; `re.IGNORECASE` catches a stray lower-case "dos".
NAMES_DOS = re.compile(r"\bDOS\b", re.IGNORECASE)

#: Same idea, for the third instance the issue's own comments traced:
#: `goldbox.dos.to_neutral`'s portrait drop naming "C64" while reading a DOS
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
        c = amiga.read_amiga_por(path)
        n = amiga.to_neutral(c)
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
        _built, report = amiga.write_later(char)
        for line in report.dropped:
            assert not NAMES_DOS.search(line), (char.get("name"), line)
            assert "CHARPIC00" not in line, (char.get("name"), line)
            assert line[:1] == line[:1].upper(), (char.get("name"), line)
        checked += 1
    assert checked == 6


def test_a_dos_portrait_the_menu_cannot_answer_for_names_no_platform():
    """The third instance the issue's own comments traced:
    `goldbox.dos.to_neutral`'s portrait block named "C64" unconditionally,
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
    raw = bytearray(bytes(dos.POOL_OF_RADIANCE.record_size))
    raw[dos_layout.FIELDS_BY_NAME["portrait_body"].offset] = 13  # outside
    odd = dos.DosCharacter(bytes(raw))                            # the menu
    neutral = dos.to_neutral(odd, portraits=tables)
    lines = [d for d in neutral.dropped if "portrait (body)" in d.lower()]
    assert lines, neutral.dropped
    for line in lines:
        assert not NAMES_C64.search(line), line
