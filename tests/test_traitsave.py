"""The editor's own write path, driven the way `#417` measures it.

`#417 (Prove the game applies a trait Wish wrote, so WISH_EXPERIMENTAL_TRAITS
can come off)` is measurement M3, and everything it adds to `#252 (Does a C64
trait slot apply an item-granted effect id, or only the ones its own READY
routine wrote?)` is the **write path**: not a byte poked into a `.d64`, but the
Add button, the picker, and `File > Save`. `tools/traitsave.py` is what drives
that, and what these tests hold down is the property the measurement rests on
-- **the button and the menu together change one byte, at record `0x0AD`, and
nothing else on the disk.**

A tool that quietly wrote the byte itself would produce the same disk and prove
nothing, so the write test runs against a save built by `gamedata.synthetic_party`
and asserts on the whole image: one differing byte in 174,848.
"""

from __future__ import annotations

import argparse

import pytest
from gamedata import synthetic_save

from goldbox import layout
from tools import traitsave

#: `gamedata.synthetic_party` names every character a record's worth of
#: capital Ws, so the name is the layout's and not a literal here.
EVERYBODY = "W" * layout.NAME_SIZE

#: Resist Fire, the id `#417` names, and the one `docs/171-c64-trait-slots.md`
#: has on the spell-damage and saving-throw check lists.
RESIST_FIRE = 20


def test_a_records_offset_is_its_slot_times_the_stride():
    assert traitsave.record_offset(0) == 0x4D00 - 0x4900
    assert traitsave.record_offset(2) - traitsave.record_offset(1) == 0x100


def test_the_diff_says_which_record_and_whether_it_is_a_trait_slot():
    before = bytearray(0x800)
    after = bytearray(before)
    at = traitsave.record_offset(2) + traitsave.TRAIT_SLOT
    after[at] = RESIST_FIRE
    after[at + 0x20] = 7            # outside the ten, same record
    diff = traitsave.body_diff(bytes(before), bytes(after))
    assert [d["offset"] for d in diff] == [at, at + 0x20]
    assert [d["slot"] for d in diff] == [2, 2]
    assert [d["in_trait_block"] for d in diff] == [True, False]


def test_an_unchanged_body_has_no_diff():
    body = bytes(range(256)) * 4
    assert traitsave.body_diff(body, body) == []


def _run(tmp_path, monkeypatch, who: str, trait: str) -> tuple[int, object]:
    """`traitsave.py write` against a save built from the format."""
    # Deleted again at teardown, whatever the tool sets: `monkeypatch.setenv`
    # on a variable that was unset restores it to unset, and this one must
    # never leak into the tests that check the flag is off by default.
    monkeypatch.setenv("WISH_EXPERIMENTAL_TRAITS", "0")
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME"):
        monkeypatch.setenv(var, str(tmp_path / "config"))
    disks = tmp_path / "no-disks"
    disks.mkdir()
    save = synthetic_save(tmp_path)
    args = argparse.Namespace(out=str(tmp_path / "run"), disks=str(disks),
                              quiet=True, save=str(save), who=who, trait=trait)
    return traitsave.write(args), tmp_path / "run"


@pytest.mark.usefixtures("_one_qapplication")
def test_the_add_button_and_the_file_menu_change_one_byte(tmp_path, monkeypatch):
    """The whole disk differs by the trait, and by nothing else.

    This is the shape of M3's first half. If `tools/traitsave.py` ever stopped
    going through the button and wrote the byte itself the assertion below
    would still pass -- so the guard is the *count*: a save that rewrote a
    derived field, a checksum or a name would show more than one byte here,
    and the measurement on `#417` would be about something other than the
    trait.
    """
    rc, run = _run(tmp_path, monkeypatch, EVERYBODY, "Resist Fire")
    assert rc == 0
    original = (run / "original.d64").read_bytes()
    edited = (run / "edited.d64").read_bytes()
    assert len(original) == len(edited)
    differ = [i for i in range(len(original)) if original[i] != edited[i]]
    assert len(differ) == 1
    assert original[differ[0]] == 0 and edited[differ[0]] == RESIST_FIRE
    body = traitsave.body_diff(traitsave.save_body(run / "original.d64"),
                               traitsave.save_body(run / "edited.d64"))
    assert len(body) == 1
    assert body[0]["in_trait_block"] and body[0]["now"] == RESIST_FIRE


@pytest.mark.usefixtures("_one_qapplication")
def test_a_name_no_character_has_writes_nothing(tmp_path, monkeypatch):
    rc, run = _run(tmp_path, monkeypatch, "NOBODY", "Resist Fire")
    assert rc == 1
    assert (run / "original.d64").read_bytes() == (run / "edited.d64").read_bytes()


@pytest.mark.usefixtures("_one_qapplication")
def test_a_trait_the_picker_does_not_offer_writes_nothing(tmp_path, monkeypatch):
    """The picker's OK button stays disabled, so `add_trait` adds nothing.

    The failure mode this rules out is a run that reports success having put
    something else in the slot: `TraitPicker.chosen` reads the selection, and
    a filter that matches no row leaves no selection to read.
    """
    rc, run = _run(tmp_path, monkeypatch, EVERYBODY, "no such trait")
    assert rc == 1
    assert (run / "original.d64").read_bytes() == (run / "edited.d64").read_bytes()
