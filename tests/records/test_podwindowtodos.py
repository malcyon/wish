"""Amiga Pools of Darkness' `field_83_87` window reaches DOS byte for byte
(#614).

`tests/amiga/test_podamiga.py::test_the_pod_window_carries_its_third_and_fourth_bytes`
proves the Amiga-to-Amiga leg: `amiga_pod.pod_to_neutral` hangs the window on
the neutral record and `amiga_pod.to_pc` writes it back. This file proves the
other leg, that the same neutral record's window reaches
`goldbox.dos_codec.write`'s DOS Pools of Darkness output at `0x149`/`0x14A`,
through `dos_codec.window_source` rather than the writer's constant.
"""
from __future__ import annotations

import pytest

from goldbox import amiga_pod, dos_codec, dos_port


@pytest.mark.parametrize("third,fourth", ((0, 0), (3, 0xAB)))
def test_the_pod_window_reaches_dos_at_0x149_0x14a(third, fourth):
    raw = bytearray(amiga_pod.PodWriter(
        name="TEST",
        character_class=amiga_pod.CLASSES.index("FIGHTER"),
        class_levels=(0, 0, 1, 0, 0, 0, 0),
        class_bits=amiga_pod.CLASS_BIT["fighter"],
    ).to_bytes())
    raw[amiga_pod.FIELD_83_87_THIRD] = third
    raw[amiga_pod.FIELD_83_87_FOURTH] = fourth
    character = amiga_pod.pod_to_neutral(bytes(raw))

    rec, _itm, _spc, _report = dos_codec.write(
        character, deltas=dos_port.POOLS_OF_DARKNESS)
    assert rec[0x149] == third
    assert rec[0x14A] == fourth
