"""`write_pod` reports a field the engine rebuilds as derived, never dropped
(#617).

Before this, `POD_WRITE_UNTAKEN` folded `attack_level`, `portrait_head` and
`portrait_body` into `neutral.Writer`'s one drop channel, so every one of
them landed on `report.dropped` and `editor.saveplan.losses` would have
counted it as a loss -- nothing the writer actually loses, since the game
rebuilds `attack_level` from class and level on load and the portrait pair is
zero in every record either port has ever produced.

`test_an_unusual_armour_class_base_converts_instead_of_being_refused` is
`#635 (Read what a Pools of Darkness armour-class base other than 50 means,
so the Amiga conversion writes it instead of refusing)`: both engines seed
the current armour-class calculation from the stored base at creation and on
every rebuild, so a base other than 50 is real state and copying it through
is what keeps the character's armour class the one he had.
"""

from __future__ import annotations

import struct

from editor import saveplan
from goldbox import amiga_pod, dos_codec, dos_port

POD = dos_port.POOLS_OF_DARKNESS


def _fighter_raw() -> bytearray:
    return bytearray(amiga_pod.PodWriter(
        name="TEST",
        character_class=amiga_pod.CLASSES.index("FIGHTER"),
        class_levels=(0, 0, 1, 0, 0, 0, 0),
        class_bits=amiga_pod.CLASS_BIT["fighter"],
    ).to_bytes())


def test_attack_level_and_portrait_are_derived_not_dropped():
    """An ordinary character reports none of the three on `dropped`, all
    three on `derived`, and `saveplan.losses` empty.

    Amiga Pools of Darkness has no `attack_level` byte of its own -- see
    `POD_WRITE_DERIVED`'s own entry -- so `pod_to_neutral` never sets the
    field; a DOS Pools of Darkness source does, which is the direction the
    body's Testing section asks for, so it is set here the way `goldbox`'s
    own "made up" tests build a field a route does not otherwise reach.
    """
    character = amiga_pod.pod_to_neutral(bytes(_fighter_raw()))
    character.set("attack_level", 3, "test: as a DOS Pools of Darkness "
                  "source would carry it")
    _writer, report = amiga_pod.write_pod(character)

    names = {"attack_level", "portrait_head", "portrait_body"}
    dropped_names = {line.split(":", 1)[0] for line in report.dropped}
    derived_names = {line.split(":", 1)[0] for line in report.derived}
    assert names.isdisjoint(dropped_names)
    assert names <= derived_names
    assert saveplan.losses(report) == []


def _dos_pod_record(armour_class_base: int,
                    items: tuple[dos_codec.DosItem, ...] = ()
                    ) -> dos_codec.DosCharacter:
    """A made-up DOS Pools of Darkness paladin, level 12, holding the given
    stored armour-class base -- the same record shape
    `test_a_paladins_cure_byte_survives_dos_to_amiga_and_back` builds in
    `tests/amiga/test_podamiga.py`, so this needs no disks and carries no
    game bytes."""
    f = dos_port.FIELDS_BY_NAME_FOR[POD.key]
    raw = bytearray(POD.record_size)
    raw[0] = 5
    raw[1:6] = b"JORIL"
    raw[f["race"].offset] = 5
    raw[f["class_levels"].offset + 5] = 12
    raw[f["class_bits"].offset] = 0x40
    raw[f["armour_class_base"].offset] = armour_class_base
    return dos_codec.DosCharacter(bytes(raw), items=items)


def _dos_pod_readied_item() -> dos_codec.DosItem:
    """One readied item, plain armour, for the equipped half of the
    conversion proof below."""
    itemf = dos_port.ITEM_FIELDS_BY_NAME
    data = bytearray(dos_port.ITEM_SIZE)
    data[itemf["type_index"].offset] = 18
    data[itemf["readied"].offset] = 1
    struct.pack_into("<H", data, itemf["weight"].offset, 40)
    data[itemf["quantity"].offset] = 1
    struct.pack_into("<H", data, itemf["value"].offset, 100)
    return dos_codec.DosItem(bytes(data))


def test_an_unusual_armour_class_base_converts_instead_of_being_refused():
    """`#635 (Read what a Pools of Darkness armour-class base other than 50
    means, so the Amiga conversion writes it instead of refusing)`: a DOS
    Pools of Darkness character whose stored base is 49 -- displayed base AC
    11, not the unarmoured 10 every measured record holds -- has real state.
    Both engines seed the current armour-class calculation from that byte, at
    creation and on every rebuild, so the conversion must write it rather
    than refuse the save or silently replace it with the unarmoured
    constant.

    Checked with and without a readied item in the source, because the base
    the writer copies through must not depend on what else the character is
    carrying: it is one byte at `0x0B3`, not the bonus the engine derives
    from the item nodes on load."""
    for carrying in (False, True):
        items = (_dos_pod_readied_item(),) if carrying else ()
        dos_char = _dos_pod_record(49, items=items)
        source = dos_codec.to_neutral(dos_char)
        assert source.get("armour_class_base") == 49, carrying

        writer, report = amiga_pod.write_pod(source)
        raw = writer.to_bytes()

        assert raw[amiga_pod.ARMOUR_CLASS] == 49, carrying
        assert not any("armour_class_base" in line for line in report.losses), \
            carrying
        assert not any(
            "armour_class_base" in line for line in report.dropped), carrying
        assert saveplan.losses(report) == [], carrying

        back = amiga_pod.pod_to_neutral(raw)
        assert back.get("armour_class_base") == 49, carrying

        # The effective, displayed base -- `60 - stored`, the family's usual
        # bias -- agrees between the DOS source and the converted `.pc`,
        # with the same equipment either side of the comparison.
        source_ac = 60 - source.get("armour_class_base")
        converted_ac = 60 - amiga_pod.PodCharacter.from_bytes(raw).raw[
            amiga_pod.ARMOUR_CLASS]
        assert source_ac == converted_ac == 11, carrying


def test_an_unusual_portrait_byte_is_reported_as_a_loss():
    """Same guard, for the portrait pair -- zero in 19 of 19 `.pc` files."""
    raw = _fighter_raw()
    raw[amiga_pod.PORTRAIT_HEAD] = 7
    character = amiga_pod.pod_to_neutral(bytes(raw))

    _writer, report = amiga_pod.write_pod(character)

    assert len(report.losses) == 1
    assert "portrait_head" in report.losses[0]
    assert not any("portrait_head" in line for line in report.dropped)
