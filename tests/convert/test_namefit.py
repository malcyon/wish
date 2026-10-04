"""`editor.saveplan.fit_names` and `name_width`, the seam Stage A of
`#619 (A name cut to the destination's width and a value clamped into a
narrower field reach report.warnings only, so no caller can see the loss)`
puts between a neutral party and the writer that would otherwise cut a name
that does not fit.

No game disk needed: every character here is `tools/records/boundarychars.py`'s
own synthetic base character, read as though off a C64 disk, the way a real
conversion hands one to `goldbox.dos_codec.write`.
"""

from __future__ import annotations

import pytest

from editor import saveplan
from goldbox import dos_port
from goldbox.layout import NAME_SIZE
from tools.records import boundarychars


def _char(name: str):
    char = boundarychars._base()
    char.set("name", name, "test")
    return char


def test_a_name_within_the_width_comes_back_unchanged():
    char = _char("SHORT NAME")
    party = saveplan.fit_names([char], "dos", boundarychars.GAME)
    assert party == [char]
    assert char.get("name") == "SHORT NAME"


def test_a_long_name_with_no_replacement_names_it_and_the_width():
    char = _char("ABCDEFGHIJKLMNOPQR")
    with pytest.raises(saveplan.NamesDoNotFit) as excinfo:
        saveplan.fit_names([char], "dos", boundarychars.GAME)
    assert excinfo.value.unfit == ((0, "ABCDEFGHIJKLMNOPQR"),)
    assert excinfo.value.width == 15


def test_a_replacement_is_written_and_the_writer_has_nothing_left_to_cut():
    from goldbox import dos_codec

    char = _char("ABCDEFGHIJKLMNOPQR")
    saveplan.fit_names([char], "dos", boundarychars.GAME,
                       {0: "RENAMED"})
    assert char.get("name") == "RENAMED"
    record, itm, spc, report = dos_codec.write(char)
    assert report.losses == []
    deltas = dos_codec.write_deltas(char)
    items = [dos_codec.DosItem(itm[i:i + deltas.item_size], deltas.item_size)
             for i in range(0, len(itm), deltas.item_size)]
    effects = [spc[i:i + dos_codec.EFFECT_SIZE]
              for i in range(0, len(spc), dos_codec.EFFECT_SIZE)]
    back = dos_codec.to_neutral(
        dos_codec.DosCharacter(record, items=items, effects=effects,
                               deltas=deltas))
    assert back.get("name") == "RENAMED"


@pytest.mark.parametrize("bad", ["", "A" * 16, "CAFÉ"])
def test_a_replacement_that_does_not_fit_raises_saveaserror(bad):
    char = _char("ABCDEFGHIJKLMNOPQR")
    with pytest.raises(saveplan.SaveAsError):
        saveplan.fit_names([char], "dos", boundarychars.GAME,
                           {0: bad})


def test_two_characters_sharing_one_long_name_each_take_their_own_replacement():
    long_name = "ABCDEFGHIJKLMNOPQR"
    a = _char(long_name)
    b = _char(long_name)
    with pytest.raises(saveplan.NamesDoNotFit) as excinfo:
        saveplan.fit_names([a, b], "dos", boundarychars.GAME)
    assert excinfo.value.unfit == ((0, long_name), (1, long_name))
    saveplan.fit_names([a, b], "dos", boundarychars.GAME,
                       {0: "FIRST", 1: "SECOND"})
    assert a.get("name") == "FIRST"
    assert b.get("name") == "SECOND"


def test_a_replacement_for_one_of_two_leaves_the_other_named_as_unfit():
    long_name = "ABCDEFGHIJKLMNOPQR"
    a, b = _char(long_name), _char(long_name)
    with pytest.raises(saveplan.NamesDoNotFit) as excinfo:
        saveplan.fit_names([a, b], "dos", boundarychars.GAME, {1: "SECOND"})
    assert excinfo.value.unfit == ((0, long_name),)
    assert b.get("name") == "SECOND"


@pytest.mark.parametrize("position", [-1, 1, 7])
def test_a_key_that_is_not_a_position_in_the_party_raises_saveaserror(position):
    char = _char("SHORT NAME")
    with pytest.raises(saveplan.SaveAsError):
        saveplan.fit_names([char], "dos", boundarychars.GAME,
                           {position: "RENAMED"})
    assert char.get("name") == "SHORT NAME"


@pytest.mark.parametrize("key", dos_port.LAYOUTS.keys())
def test_name_width_per_port_and_title(key):
    assert saveplan.name_width("c64", key) == NAME_SIZE
    assert saveplan.name_width("dos", key) == 15
    assert saveplan.name_width("amiga", key) == 15


# ---------------------------------------------------------------------------
# What a destination shows as typed, not only how long a name it holds
# ---------------------------------------------------------------------------

POOL, CURSE, SILVER, DARKNESS = (
    "pool-of-radiance", "curse-of-the-azure-bonds",
    "secret-of-the-silver-blades", "pools-of-darkness")
BACKQUOTE = "A`B"


def _asks_for_a_name(port: str, title: str, name: str) -> bool:
    try:
        saveplan.check_names([name], port, title)
    except saveplan.NamesDoNotFit as exc:
        assert exc.unfit == ((0, name),)
        return True
    return False


@pytest.mark.parametrize("port, title, name, unfit", [
    # Amiga Pool deletes `. * , ? / : ;` at its first save and draws the
    # rest as written.
    ("amiga", POOL, "J.R", True),
    ("amiga", POOL, "A|B", True),
    ("amiga", POOL, "A[B", False),
    ("amiga", POOL, "X{Y}Z~W", False),
    ("amiga", POOL, "A B", False),
    ("amiga", POOL, "Guy de Valois ", False),
    # Amiga Curse and Silver Blades draw the backquote and `{ | } ~` as
    # other glyphs.
    ("amiga", CURSE, BACKQUOTE, True),
    ("amiga", CURSE, "A{B", True),
    ("amiga", CURSE, "F/T", False),
    ("amiga", CURSE, "J,R", False),
    ("amiga", CURSE, "A[B", False),
    ("amiga", CURSE, "Guy de Valois ", False),
    ("amiga", SILVER, BACKQUOTE, True),
    ("amiga", SILVER, "A{B", True),
    ("amiga", SILVER, "F/T", False),
    ("amiga", SILVER, "Guy de Valois ", False),
    # DOS draws `[ \ ] ^ _` and `{ | } ~` as other glyphs, and the backquote
    # blank, on every title.
    *[(port, title, name, True)
      for port, title in (("dos", POOL), ("dos", CURSE), ("dos", SILVER),
                          ("dos", DARKNESS))
      for name in ("A[B", BACKQUOTE, "X~Y")],
    *[(port, title, name, False)
      for port, title in (("dos", POOL), ("dos", CURSE), ("dos", SILVER),
                          ("dos", DARKNESS))
      for name in ("J,R", "F/T", "Guy de Valois ")],
    # The C64 draws the same characters differently, and Curse and Silver
    # Blades cut a removed character's file name at a comma.
    ("c64", POOL, "A[B", True),
    ("c64", POOL, BACKQUOTE, True),
    ("c64", POOL, "J,R", False),
    ("c64", POOL, "F/T", False),
    ("c64", CURSE, "J,R", True),
    ("c64", CURSE, "F/T", False),
    ("c64", CURSE, "Guy de Valois ", False),
    ("c64", SILVER, "J,R", True),
    ("c64", SILVER, "F/T", False),
    ("c64", SILVER, "Guy de Valois ", False),
    # A byte outside printable ASCII is drawn as something else everywhere.
    *[(port, title, name, True)
      for port, title in (("dos", CURSE), ("c64", POOL), ("amiga", CURSE),
                          ("amiga", POOL))
      for name in ("Xåy", "X\x01Y")],
])
def test_a_name_the_destination_cannot_show_is_named_as_unfit(
        port, title, name, unfit):
    assert _asks_for_a_name(port, title, name) is unfit
    assert saveplan.name_fits(name, port, title) is (not unfit)


def test_a_chosen_name_the_destination_cannot_show_is_blocked():
    with pytest.raises(saveplan.SaveAsError) as excinfo:
        saveplan.check_names(["JR"], "dos", CURSE, {0: "A{B"})
    assert not isinstance(excinfo.value, saveplan.NamesDoNotFit)


def test_a_suggested_name_drops_what_the_destination_cannot_show_then_cuts():
    shown = saveplan.shown_characters("dos", CURSE)
    assert saveplan.suggest_name("A{B|C}D~E", 15, shown) == "ABCDE"
    long_name = "ABCDEFGHIJKLMNOPQR"
    assert saveplan.suggest_name(long_name, 15, shown) == long_name[:15]
    assert saveplan.suggest_name("ABCDEFGHIJKLMN  PQR", 15, shown) == (
        "ABCDEFGHIJKLMN")


def test_check_names_names_the_same_characters_as_fit_names():
    names = ["A{B", "SHORT", "ABCDEFGHIJKLMNOPQR"]
    party = [_char(name) for name in names]
    with pytest.raises(saveplan.NamesDoNotFit) as by_party:
        saveplan.fit_names(party, "dos", boundarychars.GAME)
    with pytest.raises(saveplan.NamesDoNotFit) as by_strings:
        saveplan.check_names(names, "dos", boundarychars.GAME)
    assert by_party.value.unfit == by_strings.value.unfit == (
        (0, "A{B"), (2, "ABCDEFGHIJKLMNOPQR"))
    assert by_strings.value.shown == saveplan.shown_characters(
        "dos", boundarychars.GAME)


def test_check_names_returns_the_choices_it_accepted():
    assert saveplan.check_names(["A{B", "OK"], "dos", CURSE, {0: "AB"}) == {
        0: "AB"}
    assert saveplan.check_names(["OK"], "dos", CURSE) == {}
