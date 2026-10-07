"""An ability edited on the sheet changes the score the game keeps.

Curse of the Azure Bonds and Secret of the Silver Blades keep every ability
twice: the permanent score (C64 `abilities_second` at `0x065`, DOS and Amiga
byte 0 of each pair, byte 1 for the percentile) and the score in force (C64
`0x014`, the other byte of the pair).  The engine rebuilds the score in force
from the permanent one -- C64 `ECL65 $913B` (Curse) and `$9612` (Silver
Blades) open with `LDA $7C65,X / STA $7C14,X`, and the DOS and Amiga
recomputes seed from the permanent byte (`docs/201-the-two-ability-arrays.md`,
`docs/204-the-dos-ability-pair.md`) -- so an edit to the score in force alone
is undone at the next rebuild.  Pool of Radiance keeps one copy, and its C64
bytes at `0x065` are part of the memorised-spell list.

Every record here is generated; nothing is read from a game disk.
"""
from __future__ import annotations

import pytest
from gamedata import synthetic_save
from support.editorwindow import make_root
from support.neutralrecords import _filled

from editor.binding import set_sheet_value
from goldbox import amiga_later, c64_port, dos_codec, dos_port, rewrite
from goldbox.amiga_port import CURSE_DELTAS, SILVER_BLADES_DELTAS
from goldbox.neutral import ABILITIES
from goldbox.record import CharacterRecord

LATER = (c64_port.CURSE_OF_THE_AZURE_BONDS,
         c64_port.SECRET_OF_THE_SILVER_BLADES)
IN_FORCE_AT = 0x014
PERMANENT_AT = 0x065

#: An edit for each of the seven, every one different from the 1-7 the made-up
#: records hold and from each other.
EDITS = {"strength": 15, "intelligence": 16, "wisdom": 12, "dexterity": 17,
         "constitution": 14, "charisma": 11, "exceptional_strength": 50}


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _record() -> CharacterRecord:
    """A record whose two arrays hold different values, so a write to the
    wrong one shows."""
    rec = CharacterRecord.blank()
    rec.set_raw("abilities_second", bytes(range(31, 38)))
    for i, name in enumerate(ABILITIES):
        rec.set(name, 21 + i)
    return rec


# --- the C64 sheet record -----------------------------------------------------
@pytest.mark.parametrize("game", LATER, ids=lambda g: g.key)
@pytest.mark.parametrize("name", ABILITIES)
def test_an_ability_edit_writes_the_permanent_and_the_in_force_score(game,
                                                                     name):
    rec = _record()
    before = rec.to_bytes()
    set_sheet_value(rec, name, EDITS[name], game)
    after = rec.to_bytes()
    i = ABILITIES.index(name)
    assert after[IN_FORCE_AT + i] == EDITS[name]
    assert after[PERMANENT_AT + i] == EDITS[name]
    moved = {at for at in range(len(after)) if after[at] != before[at]}
    assert moved == {IN_FORCE_AT + i, PERMANENT_AT + i}


@pytest.mark.parametrize("name", ABILITIES)
def test_a_pool_of_radiance_ability_edit_leaves_its_memorised_spells_alone(
        name):
    """Pool of Radiance keeps one copy; `0x065` is spell ids there."""
    rec = _record()
    before = rec.to_bytes()
    set_sheet_value(rec, name, EDITS[name], c64_port.POOL_OF_RADIANCE)
    after = rec.to_bytes()
    i = ABILITIES.index(name)
    moved = {at for at in range(len(after)) if after[at] != before[at]}
    assert moved == {IN_FORCE_AT + i}


def test_a_field_other_than_an_ability_writes_only_itself():
    rec = _record()
    before = rec.to_bytes()
    set_sheet_value(rec, "gold", 4321, c64_port.CURSE_OF_THE_AZURE_BONDS)
    assert rec.get("gold") == 4321
    assert rec.get_raw("abilities_second") == before[PERMANENT_AT:
                                                     PERMANENT_AT + 7]


# --- through the sheet itself -------------------------------------------------
def _window(path):
    from PyQt6.QtWidgets import QTabWidget

    from editor.window import EditorBinding
    root = make_root()
    w = EditorBinding(root, str(path))
    tabs = root.findChild(QTabWidget, "tabs")
    for i in range(tabs.count()):
        if tabs.widget(i).objectName() == "tab_editor":
            tabs.setCurrentIndex(i)
            break
    root.show()
    return w


@pytest.mark.parametrize("game", (*LATER, c64_port.POOL_OF_RADIANCE),
                         ids=lambda g: g.key)
def test_the_sheets_strength_box_writes_what_the_title_keeps(app, tmp_path,
                                                             game):
    """Strength 18 to 15 and wisdom 18 to 12 in the window: both arrays in
    Curse and Silver Blades, the one score in Pool of Radiance, and an
    untouched box writes nothing."""
    w = _window(synthetic_save(tmp_path, name=f"{game.key}.D64", game=game))
    member = w.party.member(w.current_row)
    member.record.set_raw("abilities_second", bytes((18, 18, 18, 18, 18, 18,
                                                     0)))
    w._populate()
    before = member.record.to_bytes()
    w._widgets["strength"].setValue(15)
    w._widgets["wisdom"].setValue(12)
    assert w._flush() == []
    after = member.record.to_bytes()
    moved = {at for at in range(len(after)) if after[at] != before[at]}
    expected = {IN_FORCE_AT, IN_FORCE_AT + 2}
    if game in LATER:
        expected |= {PERMANENT_AT, PERMANENT_AT + 2}
        assert after[PERMANENT_AT] == 15 and after[PERMANENT_AT + 2] == 12
    assert after[IN_FORCE_AT] == 15 and after[IN_FORCE_AT + 2] == 12
    assert moved == expected


# --- what reaches a DOS or Amiga save -----------------------------------------
def _game(key):
    return c64_port.by_key(key)


def _dos(deltas):
    record, itm, spc, _rep = dos_codec.write(_filled(_game(deltas.key)),
                                             deltas=deltas)
    stride = deltas.item_size
    items = [dos_codec.DosItem(itm[n * stride:(n + 1) * stride], stride)
             for n in range(len(itm) // stride)]
    effects = [spc[n * dos_port.EFFECT_SIZE:(n + 1) * dos_port.EFFECT_SIZE]
               for n in range(len(spc) // dos_port.EFFECT_SIZE)]
    char = dos_codec.DosCharacter(record, items=items, effects=effects,
                                  deltas=deltas)
    rec, _ = dos_codec.to_c64_record(char)
    return char, rec


def _edited(rec, game):
    out = CharacterRecord(rec.to_bytes(), rec.stored_size)
    set_sheet_value(out, "strength", 15, game)
    set_sheet_value(out, "wisdom", 12, game)
    set_sheet_value(out, "exceptional_strength", 50, game)
    return out


#: DOS and Amiga pair offsets: (permanent, in force) for the six scores,
#: (in force, permanent) for the percentile, docs/204.
_PAIRS = {"strength": (0x10, 0x11), "wisdom": (0x14, 0x15),
          "exceptional_strength": (0x1D, 0x1C)}


@pytest.mark.parametrize("deltas", (dos_port.CURSE_OF_THE_AZURE_BONDS,
                                    dos_port.SECRET_OF_THE_SILVER_BLADES),
                         ids=lambda d: d.key)
def test_a_dos_ability_edit_moves_both_bytes_of_the_pair(deltas):
    char, before = _dos(deltas)
    game = _game(deltas.key)
    out = rewrite.rewrite_dos(char, before, _edited(before, game), game)
    want = {"strength": 15, "wisdom": 12, "exceptional_strength": 50}
    for name, (permanent, in_force) in _PAIRS.items():
        assert (out.record[permanent], out.record[in_force]) == \
            (want[name], want[name]), name
    original = char.to_bytes()
    moved = {at for at in range(0x10, 0x1E) if out.record[at] != original[at]}
    assert moved == {at for pair in _PAIRS.values() for at in pair}


@pytest.mark.parametrize("deltas", (CURSE_DELTAS, SILVER_BLADES_DELTAS),
                         ids=lambda d: d.key)
def test_an_amiga_ability_edit_moves_both_bytes_of_the_pair(deltas):
    game = _game(deltas.dos.key)
    char, _rep = amiga_later.write_later(_filled(game), deltas=deltas)
    before, _ = dos_codec.neutral_to_c64_record(
        amiga_later.to_neutral_later(char))
    out = rewrite.rewrite_amiga_later(char, before, _edited(before, game),
                                      game)
    raw = out.character.raw
    want = {"strength": 15, "wisdom": 12, "exceptional_strength": 50}
    for name, (permanent, in_force) in _PAIRS.items():
        p, f = deltas.offset(permanent), deltas.offset(in_force)
        assert (raw[p], raw[f]) == (want[name], want[name]), name
