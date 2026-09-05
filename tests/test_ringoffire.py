"""The two Ring of Fire Resistance records the C64 ships, and which one Wish hands out.

`#285 (The C64's Ring of Fire Resistance grants nothing, and Wish should repair
it on conversion and on an editor save)` was filed against the game, and the
game is mostly innocent. Five records on the eight sides print RING OF FIRE
RESISTANCE and four of them grant effect 61 when they are readied; the fifth,
in `ITEMFILE17` on POOL3, has +14 and +15 zeroed. `load_item_templates` kept
the first record it met for a name and POOL3 sorts before POOL4, so every
reading of "the shipped template" -- and every ring the editor handed out --
was that one.

Everything here reads the player's own disks and skips without them. Nothing
is written down that the disks can be asked for.
"""

import pathlib

import pytest
from gamedata import disk_dir, game_file

from goldbox.d64 import D64, split_load_address
from goldbox.items import (
    EFFECT,
    ITEM_SIZE,
    PASSIVE_POWER,
    POWER,
    RING_OF_FIRE_RESISTANCE_ID,
    Item,
    is_item_list,
    load_item_names,
    load_item_templates,
    repair_ring_of_fire_resistance,
)

DISKS = disk_dir()
needs_disks = pytest.mark.skipif(
    DISKS is None or not (DISKS / "POOL1.D64").exists(),
    reason="needs the Pool of Radiance disks; set POR_DISKS")

GAME_DISK = f"{DISKS}/POOL1.D64"


def _every_record():
    """Every non-empty item record on every side, with where it came from."""
    for path in sorted(pathlib.Path(DISKS).glob("POOL[1-8].D64")):
        img = D64.open(str(path))
        for entry in img.directory():
            if not is_item_list(entry.name):
                continue
            _, payload = split_load_address(img.read_file(entry))
            stem = entry.name.decode("ascii", "replace").rstrip("\xa0")
            for i in range(len(payload) // ITEM_SIZE):
                raw = bytes(payload[i * ITEM_SIZE:(i + 1) * ITEM_SIZE])
                if any(raw):
                    yield f"{path.name}:{stem}[{i}]", raw


@needs_disks
def test_the_disks_carry_two_rings_and_one_of_them_is_dead():
    """The census the issue rests on, taken again from the bytes."""
    found = {where: raw for where, raw in _every_record()
             if tuple(raw[:4]) == RING_OF_FIRE_RESISTANCE_ID}
    assert len(found) == 2, found
    grants = {w: raw for w, raw in found.items() if raw[POWER] & PASSIVE_POWER}
    dead = {w: raw for w, raw in found.items() if not raw[POWER] & PASSIVE_POWER}
    assert len(grants) == 1 and len(dead) == 1, found
    assert "ITEMFILE1D" in next(iter(grants))
    assert "ITEMFILE17" in next(iter(dead))
    assert (next(iter(grants.values()))[EFFECT],
            next(iter(grants.values()))[POWER]) == (61, 0x81)
    assert (next(iter(dead.values()))[EFFECT],
            next(iter(dead.values()))[POWER]) == (0, 0)


@needs_disks
def test_the_template_wish_hands_out_is_the_one_that_grants():
    template = load_item_templates(GAME_DISK)["RING OF FIRE RESISTANCE"]
    assert (template[EFFECT], template[POWER]) == (61, 0x81)


@needs_disks
def test_only_two_names_disagree_about_granting():
    """The tie-break decides two names out of 163, and no others.

    If a third name ever falls into disagreement -- on this title or after a
    reader change -- the rule stops being a two-record correction and has to
    be argued again.
    """
    names = load_item_names(GAME_DISK)
    per: dict[str, set[bytes]] = {}
    for _, raw in _every_record():
        per.setdefault(Item(raw, names).name, set()).add(raw)
    split = {name: copies for name, copies in per.items()
             if len({bool(r[POWER] & PASSIVE_POWER) for r in copies}) > 1}
    assert set(split) == {"RING OF FIRE RESISTANCE", "LONG SWORD +2"}, split
    templates = load_item_templates(GAME_DISK)
    for name in split:
        assert templates[name][POWER] & PASSIVE_POWER


@needs_disks
def test_the_repair_leaves_the_working_ring_alone():
    """A ring that already dispatches is returned byte for byte."""
    template = load_item_templates(GAME_DISK)["RING OF FIRE RESISTANCE"]
    assert repair_ring_of_fire_resistance(template) == template


@needs_disks
def test_the_repair_writes_the_games_own_two_bytes():
    """A flattened ring comes back with `ITEMFILE1D`'s effect and power, and
    nothing else moved -- not a value of ours."""
    payload = game_file("ITEMFILE17")
    flat = next(bytes(payload[i * ITEM_SIZE:(i + 1) * ITEM_SIZE])
                for i in range(len(payload) // ITEM_SIZE)
                if tuple(payload[i * ITEM_SIZE:i * ITEM_SIZE + 4])
                == RING_OF_FIRE_RESISTANCE_ID)
    working = load_item_templates(GAME_DISK)["RING OF FIRE RESISTANCE"]
    fixed = repair_ring_of_fire_resistance(flat)
    assert (fixed[EFFECT], fixed[POWER]) == (working[EFFECT], working[POWER])
    assert fixed[:EFFECT] == flat[:EFFECT]


@needs_disks
def test_nothing_but_the_ring_is_repaired():
    """Every other record on the disks is returned unchanged, including the
    Long Sword +2, whose working copy carries an alignment lock."""
    touched = [where for where, raw in _every_record()
               if repair_ring_of_fire_resistance(raw) != raw]
    assert all("ITEMFILE17" in w for w in touched), touched
    assert len(touched) == 1, touched
