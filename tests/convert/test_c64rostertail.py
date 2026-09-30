"""The C64 roster tail's damage bytes, rebuilt for a character with no weapon.

The C64 sheet prints roster `+0x13`-`+0x18` and only `LIBRARY $3918` rebuilds
them, at the party's first fight.  With nothing readied that rule is the
attack forms' dice plus the strength damage step, so the writer applies it and
a converted sheet shows the figure the first fight would.  A character with a
weapon readied, or an item readied when there is no type table to say what it
is, keeps the source's bytes.
"""

from __future__ import annotations

import pytest
from gamedata import needs_specimens, specimen_root
from test_c64thac0 import _TYPES, _item

from goldbox import c64_codec, dos_codec, effects
from goldbox.neutral import NeutralCharacter

CURSE = "curse-of-the-azure-bonds"
POOL = "pool-of-radiance"

#: A class-changed MATHEW's stale tail: `1D8+6` where the C64 rule gives `1D2+6`.
STALE_TAIL = bytes.fromhex("30 00 00 01 00 08 00 06 00")
FORMS = bytes.fromhex("02 00 01 00 02 00 00 00")

#: Fewer records than this means the tree is empty or partial, so the sweep
#: cannot claim full coverage; the agreement check still runs on what it found.
FULL_TREE = 600


def _char(game: str, strength: int, percentile: int = 0,
          inventory=None, forms: bytes | None = FORMS) -> NeutralCharacter:
    char = NeutralCharacter("test", source="made up", game=game)
    char.set("levels", {"fighter": 1}, "made up")
    char.set("strength", strength, "made up")
    char.set("exceptional_strength", percentile, "made up")
    if forms is not None:
        char.set("attack_forms", forms, "made up")
    char.set("roster_tail", STALE_TAIL, "made up: the stale source bytes")
    if inventory is not None:
        char.set("inventory", inventory, "made up")
    return char


@pytest.mark.parametrize("strength, percentile, byte7", [
    (18, 100, 6), (17, 0, 1), (21, 0, 9), (5, 0, 0xFF)])
def test_an_unarmed_tail_is_rebuilt_from_the_attack_forms(strength, percentile,
                                                         byte7):
    rec, _ = c64_codec.write(_char(CURSE, strength, percentile))
    assert rec.get_raw("roster_tail") == bytes(
        [0x30, 0, 0, 1, 0, 2, 0, byte7, 0])


def test_a_readied_item_with_no_type_table_keeps_the_sources_tail():
    rec, _ = c64_codec.write(_char(CURSE, 18, 100, [_item(1)]))
    assert rec.get_raw("roster_tail") == STALE_TAIL


def test_a_readied_item_whose_type_the_table_lacks_keeps_the_sources_tail():
    """The same item with no table at all keeps the tail, so a table that
    merely lacks its type must not decide the item is armour."""
    rec, _ = c64_codec.write(_char(POOL, 17, 0, [_item(0x77)]),
                             item_types=_TYPES)
    assert 0x77 not in _TYPES
    assert rec.get_raw("roster_tail") == STALE_TAIL


def test_a_tail_with_no_attack_forms_is_copied_not_zeroed():
    for types in (None, _TYPES):
        rec, _ = c64_codec.write(_char(CURSE, 17, 0, forms=None),
                                 item_types=types)
        assert rec.get_raw("roster_tail") == STALE_TAIL


def test_pool_armour_alone_is_recomputed_and_a_weapon_is_copied():
    armour, _ = c64_codec.write(_char(POOL, 17, 0, [_item(5)]),
                                item_types=_TYPES)
    assert armour.get_raw("roster_tail") == bytes(
        [0x30, 0, 0, 1, 0, 2, 0, 1, 0])
    weapon, _ = c64_codec.write(_char(POOL, 17, 0, [_item(1)]),
                                item_types=_TYPES)
    assert weapon.get_raw("roster_tail") == STALE_TAIL


def _native_strength_of(dos, title_key):
    """The score the C64's own Strength gives this DOS record, or `None`."""
    second = dos.get("abilities_second")
    rows = dos.get("running_effects")
    if not second or not rows:
        return None
    nodes = [effects.RunningEffect.from_record(
        bytes(r)[:effects.RUNNING_EFFECT_SIZE]) for r in rows]
    return effects.c64_later_strength_in_force(
        title_key,
        (second.get("strength"), second.get("exceptional_strength")),
        (dos.get("strength"), dos.get("exceptional_strength") or 0), nodes,
        dos.get("granted_effects") or (),
        effects.later_strength_warrior(dos.get("levels"),
                                       dos.get("former_levels")))


@needs_specimens
def test_the_c64_tail_agrees_with_the_dos_rebuild_on_every_unarmed_specimen():
    """DOS rebuilds these bytes with the same rule (`dos_combat_rebuild`), so
    on every specimen record where it applies the C64 writer must land on the
    same six bytes, including the records whose DOS file stores a stale tail.

    A record whose running Strength the writer rewrote to the C64's own score
    is left out: the DOS rebuild adds the damage step of the DOS score, and the
    C64's first fight adds the step of the score the C64 holds, so the two
    differ by design. It must hold a running Strength node whose C64 cast is
    what the writer's score equals.
    """
    root = specimen_root()
    checked, disagree, rescored = 0, [], []
    for folder in sorted(p for p in root.rglob("*") if p.is_dir()):
        for path in (sorted(folder.glob("CHRDAT*.SAV"))
                     + sorted(folder.glob("*.CHA"))):
            try:
                char = dos_codec.read_character(path)
            except dos_codec.DosRecordError as exc:
                if "is missing" not in str(exc):
                    raise
                continue
            if char.deltas.key not in c64_codec.DELTAS_BY_KEY:
                continue
            items = b"".join(i.to_bytes() for i in char.items)
            rebuilt = dos_codec.dos_combat_rebuild(
                char.to_bytes(), items, None, char.deltas)
            if rebuilt is None:
                continue
            rec, _ = dos_codec.to_c64_record(char)
            dos = dos_codec.to_neutral(char)
            if ((rec.get("strength"), rec.get("exceptional_strength"))
                    != (dos.get("strength"), dos.get("exceptional_strength"))):
                rescored.append(f"{folder.name}/{path.name}")
                assert (rec.get("strength"), rec.get("exceptional_strength")
                        ) == _native_strength_of(dos, char.deltas.key), (
                    f"{folder.name}/{path.name}: strength rewritten with no "
                    f"running Strength to explain it")
                continue
            checked += 1
            if rec.get_raw("roster_tail")[3:9] != rebuilt.attack_forms:
                disagree.append(f"{folder.name}/{path.name}")
    assert disagree == []
    assert rescored, "no specimen exercises the running-Strength skip"
    if checked < FULL_TREE:
        pytest.skip(f"only {checked} unarmed records found; a full specimen "
                    f"tree holds at least {FULL_TREE}")
