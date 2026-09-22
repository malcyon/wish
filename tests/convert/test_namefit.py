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
    assert excinfo.value.unfit == ("ABCDEFGHIJKLMNOPQR",)
    assert excinfo.value.width == 15


def test_a_replacement_is_written_and_the_writer_has_nothing_left_to_cut():
    from goldbox import dos_codec

    char = _char("ABCDEFGHIJKLMNOPQR")
    saveplan.fit_names([char], "dos", boundarychars.GAME,
                       {"ABCDEFGHIJKLMNOPQR": "RENAMED"})
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
                           {"ABCDEFGHIJKLMNOPQR": bad})


def test_two_characters_sharing_one_long_name_both_take_the_replacement():
    a = _char("ABCDEFGHIJKLMNOPQR")
    b = _char("ABCDEFGHIJKLMNOPQR")
    saveplan.fit_names([a, b], "dos", boundarychars.GAME,
                       {"ABCDEFGHIJKLMNOPQR": "RENAMED"})
    assert a.get("name") == "RENAMED"
    assert b.get("name") == "RENAMED"


@pytest.mark.parametrize("key", dos_port.LAYOUTS.keys())
def test_name_width_per_port_and_title(key):
    assert saveplan.name_width("c64", key) == NAME_SIZE
    assert saveplan.name_width("dos", key) == 15
    assert saveplan.name_width("amiga", key) == 15
