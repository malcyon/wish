"""`write_pod` reports a field the engine rebuilds as derived, never dropped
(#617).

Before this, `POD_WRITE_UNTAKEN` folded `attack_level`, `portrait_head` and
`portrait_body` into `neutral.Writer`'s one drop channel, so every one of
them landed on `report.dropped` and `editor.saveplan.losses` would have
counted it as a loss -- nothing the writer actually loses, since the game
rebuilds `attack_level` from class and level on load and the portrait pair is
zero in every record either port has ever produced.
"""

from __future__ import annotations

from editor import saveplan
from goldbox import amiga_pod


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


def test_an_unusual_armour_class_base_is_reported_as_a_loss():
    """A source whose `armour_class_base` is not the 50 every record measured
    holds gets one `report.losses` line and no `report.dropped` line -- the
    guard `write_pod` adds rather than writing an unmeasured value through."""
    raw = _fighter_raw()
    raw[amiga_pod.ARMOUR_CLASS] = 49
    character = amiga_pod.pod_to_neutral(bytes(raw))

    _writer, report = amiga_pod.write_pod(character)

    assert len(report.losses) == 1
    assert "armour_class_base" in report.losses[0]
    assert "49" in report.losses[0]
    assert not any("armour_class_base" in line for line in report.dropped)
    assert saveplan.losses(report) == report.losses


def test_an_unusual_portrait_byte_is_reported_as_a_loss():
    """Same guard, for the portrait pair -- zero in 19 of 19 `.pc` files."""
    raw = _fighter_raw()
    raw[amiga_pod.PORTRAIT_HEAD] = 7
    character = amiga_pod.pod_to_neutral(bytes(raw))

    _writer, report = amiga_pod.write_pod(character)

    assert len(report.losses) == 1
    assert "portrait_head" in report.losses[0]
    assert not any("portrait_head" in line for line in report.dropped)
