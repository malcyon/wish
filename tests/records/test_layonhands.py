"""Where each port keeps a paladin's lay-on-hands use.

Read off the player's own executables at run time by
`tools/dos/layonhands.py`, `tools/amiga/amigalayonhands.py` and
`tools/c64/curedisease.py`; each title skips cleanly without its disks. No
game bytes are fixtures here: only addresses, ids and durations.
"""

from __future__ import annotations

import pytest

from tools.amiga import amigalayonhands
from tools.c64 import curedisease
from tools.dos import layonhands

#: The effect id a spent lay on hands is kept under, per title and port.
#: The C64 also keeps record byte 0x013; DOS and Amiga keep nothing else.
HEAL_ID = {
    "curse": {"c64": 140, "dos": 140, "amiga": 140},
    "silver-blades": {"c64": 109, "dos": 109, "amiga": 140},
    "pools-of-darkness": {"dos": 109, "amiga": 140},
}

C64 = {"curse": "curse-of-the-azure-bonds",
       "silver-blades": "secret-of-the-silver-blades"}
AMIGA = {"curse": "curse-of-the-azure-bonds",
         "silver-blades": "secret-of-the-silver-blades",
         "pools-of-darkness": "pools-of-darkness"}

#: DOS `GAME.OVR` file offsets: heal routine, its add_affect call, the gate
#: routine and its find_affect push, the empty handler, and the cure's
#: routine, id and decremented record byte.
DOS = {
    "curse": dict(routine=0x2A734, site=0x2A806, gate=0x2A64D,
                  gate_site=0x2A68F, gate_tests=(0x75, 0x114, 0x195),
                  handler=0x129B8, cure=(0x2A849, 141, 0x191)),
    "silver-blades": dict(routine=0x2AF21, site=0x2AFF5, gate=0x2AE3B,
                          gate_site=0x2AE7D, gate_tests=(0x6C, 0x11B, 0x1A6),
                          handler=0x145CA, cure=(0x2B04B, 110, 0x6D)),
    "pools-of-darkness": dict(routine=0x26BC3, site=0x26C90, gate=0x26ADA,
                              gate_site=0x26B1D,
                              gate_tests=(0xAE, 0x15B, 0x1ED),
                              handler=0x1DCCF, cure=(0x26CE6, 110, 0xAF)),
}

#: Amiga executable file offsets: heal routine, its add_affect call and the
#: routine called, the find_affect call, the handler (None: past the table),
#: and the cure's routine, id and decremented record byte.
AMIGA_AT = {
    "curse": dict(routine=0x023A9A, site=0x023B54, add=0x00F176,
                  gate_site=0x023A2A, find=0x01B6D2, handler=0x0127AE,
                  cure=(0x023B64, 141, 0x196)),
    "silver-blades": dict(routine=0x024E30, site=0x024ED8, add=0x012DAC,
                          gate_site=0x024DC0, find=0x01AB12, handler=None,
                          cure=(0x024EE6, 110, 0x6D)),
    "pools-of-darkness": dict(routine=0x023DA0, site=0x023E62, add=0x012FD4,
                              gate_site=0x023D30, find=0x01A6EE, handler=None,
                              cure=(0x023EA2, 110, 0x80)),
}


def _dos(title: str) -> dict:
    try:
        game = layonhands.find_game(title)
    except FileNotFoundError as exc:
        pytest.skip(str(exc))
    return layonhands.inspect(game, title)


def _amiga(key: str) -> dict:
    raw = amigalayonhands.executable(key)
    if raw is None:
        pytest.skip(f"no Amiga {key} executable on the registry's disks")
    return amigalayonhands.inspect(raw, key)


@pytest.mark.parametrize("title", sorted(DOS))
def test_dos_keeps_lay_on_hands_as_a_one_day_node_and_no_byte(title):
    """HEAL adds the node; the sheet offers HEAL only while it is absent."""
    f = _dos(title)
    want = DOS[title]
    heal = f["heal"]
    assert (heal.routine, heal.site) == (want["routine"], want["site"])
    assert (heal.effect_id, heal.minutes, heal.value, heal.flag) == (
        HEAL_ID[title]["dos"], 1440, 0, 0)
    assert heal.far_writes == ()            # no record byte written
    gate = f["heal_gate"]
    assert (gate["routine"], gate["site"], gate["record_tests"]) == (
        want["gate"], want["gate_site"], want["gate_tests"])
    # The id's only constant uses: this add and this gate.
    assert {k: len(v) for k, v in f["heal_sites"].items()} == {
        "add_affect": 1, "find_affect": 1}
    assert f["heal_handler"] == ("GAME.OVR", want["handler"])
    assert f["heal_handler_empty"]
    cure = f["cure"]
    assert (cure.routine, cure.effect_id, cure.decrements) == (
        want["cure"][0], want["cure"][1], (want["cure"][2],))
    assert (cure.minutes, cure.value, cure.flag) == (10080, 0, 1)


@pytest.mark.parametrize("title", sorted(AMIGA_AT))
def test_amiga_keeps_lay_on_hands_as_node_140_and_no_byte(title):
    f = _amiga(AMIGA[title])
    want = AMIGA_AT[title]
    heal = f["heal"]
    assert (heal.routine, heal.site, heal.add_affect) == (
        want["routine"], want["site"], want["add"])
    assert (heal.effect_id, heal.minutes, heal.value, heal.flag) == (
        HEAL_ID[title]["amiga"], 1440, 0, 0)
    assert heal.stores == ()
    assert f["add_affect_stores"] == (True, True)   # id at +0, duration at +2
    gate = f["gate"]
    assert (gate["site"], gate["find_affect"], gate["compares_byte_0"]) == (
        want["gate_site"], want["find"], True)
    assert f["heal_handler"] == want["handler"]
    if want["handler"] is not None:
        assert f["heal_handler_empty"]
    else:
        # Past the table's end: Silver Blades and Pools of Darkness fill
        # slot 109 with an empty handler and push Curse's 140 instead.
        assert heal.effect_id not in f["table"]["filled"]
        assert f["table"]["filled"][109] is not None
    # Every constant push of the id is the gate, the add, or (Silver Blades
    # only) a four-argument call that is no effect routine.
    callees = [to for _, to in f["heal_pushes"]]
    assert want["find"] in callees and want["add"] in callees
    assert len(callees) == (3 if title == "silver-blades" else 2)
    cure = f["cure"]
    assert (cure.routine, cure.effect_id, cure.decrements) == (
        want["cure"][0], want["cure"][1], (want["cure"][2],))
    assert (cure.minutes, cure.value, cure.flag) == (10080, 0, 1)


@pytest.mark.parametrize("title", sorted(C64))
def test_c64_keeps_a_record_byte_and_a_one_day_row(title):
    try:
        f = curedisease.inspect_title(C64[title])
    except SystemExit as exc:
        pytest.skip(str(exc))
    assert f["lay_on_hands"] == 0x013
    timer = f["lay_timer"]
    assert (timer.effect_id, timer.duration, timer.magnitude) == (
        HEAL_ID[title]["c64"], 0xC1, 0xC1)


def test_pool_of_radiance_has_no_heal_on_dos_or_amiga():
    ran = 0
    try:
        ran += 1
        assert _dos("pool")["heal"] is None
    except pytest.skip.Exception:
        ran -= 1
    raw = amigalayonhands.executable("pool-of-radiance")
    if raw is not None:
        ran += 1
        assert amigalayonhands.inspect(raw, "pool-of-radiance")["heal"] is None
    if not ran:
        pytest.skip("no DOS or Amiga Pool of Radiance on this machine")


#: The Amiga expiry routine: where it scales the elapsed count by the clock's
#: table, and where it takes the result off a node's duration word.
EXPIRY_AT = {
    "curse": (0x001E6E, 0x001F04),
    "silver-blades": (0x002ABE, 0x002B4C),
    "pools-of-darkness": (0x00288E, 0x0028FC),
}


@pytest.mark.parametrize("title", sorted(EXPIRY_AT))
def test_amiga_node_duration_counts_minutes(title):
    """The clock scales every elapsed count into the node's unit by 10, 6
    and 24 -- ten minutes, an hour, a day -- exactly as DOS does, so the
    1440 on the heal node is one day in minutes."""
    f = _amiga(AMIGA[title])
    e = f["expiry"]
    assert (e["scale_site"], e["subtract_site"]) == EXPIRY_AT[title]
    assert e["table"][:6] == (10, 10, 6, 24, 30, 12)
    assert e["unit_minutes"] == (1, 10, 60, 1440)
    assert f["heal"].minutes == e["unit_minutes"][3]


#: Every caller of the Amiga handler dispatcher, by where its id comes from.
#: `argument` is a routine whose own callers all push a constant id.
DISPATCH = {
    "silver-blades": dict(
        dispatcher=0x0120DC, lea=0x01211A, item_slot=120, constants=15,
        gated=(0x011E8C, 0x012774), item=(0x023596, 0x035616),
        argument=(0x0120CE, 0x011FA0, 112)),
    "pools-of-darkness": dict(
        dispatcher=0x01214C, lea=0x01218A, item_slot=127, constants=16,
        gated=(0x011F08,), item=(0x02201E, 0x031906),
        argument=(0x01213E, 0x012016, 126)),
}


@pytest.mark.parametrize("title", sorted(DISPATCH))
def test_amiga_heal_node_never_reaches_the_handler_table(title):
    """Silver Blades and Pools of Darkness push 140, past the table's end.

    No caller of the dispatcher can hand it 140: every constant id and every
    id a wrapper's callers push is below it, the item path never indexes the
    table, and the callers that pass a node's own id test its flag byte first,
    which HEAL writes as 0.  The dispatcher is the one place the table's
    base is loaded.
    """
    f = _amiga(AMIGA[title])
    want = DISPATCH[title]
    table = f["table"]
    heal = f["heal"]
    assert table["dispatcher"] == want["dispatcher"]
    assert table["indexers"] == (want["lea"],)
    assert f["item_slot"] == want["item_slot"]
    assert heal.effect_id > max(table["filled"]) and heal.flag == 0
    exe = amigalayonhands.amiga68k.Executable.parse(amigalayonhands.executable(AMIGA[title]))
    found = amigalayonhands.dispatch_callers(exe.data, exe, table)
    kinds = {}
    for c in found:
        kinds.setdefault(c.kind, []).append(c)
        assert heal.effect_id not in c.ids
    assert "unread" not in kinds
    assert len(kinds["constant"]) == want["constants"]
    assert tuple(c.site for c in kinds["flag-tested"]) == want["gated"]
    assert tuple(c.site for c in kinds["item"]) == want["item"]
    (arg,) = kinds["argument"]
    assert (arg.site, arg.via, max(arg.ids)) == want["argument"]
    assert max(i for c in found for i in c.ids) < want["item_slot"]
