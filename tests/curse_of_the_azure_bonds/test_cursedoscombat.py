"""A C64 Curse party converted to DOS gets the current THAC0, the damage and
dice bytes of its attack and the current movement that DOS Curse itself
rebuilds when it loads the party (#634).

DOS Curse's character loader ends in the combat rebuild `GAME.OVR:0x382C5`
(overlay entry `ED:43`) and then the level recompute `FE:25` (`0x3B026`),
which is what rewrites `thac0_base`. The rebuild, read off the routine:

* **The attack.** The two dice counts, two die sizes and two damage bonuses
  are copied from the permanent attack forms (`0x11E`-`0x123`) into the
  roster tail (`0x19E`-`0x1A3`). With no weapon readied, the strength damage
  step (`0x38A5F`) is added to the first damage bonus and the strength to-hit
  step (`0x389BC`) to `thac0_base`, both only when `strength_bonus` is set.
  With a weapon readied, `0x376C8` takes the first attack's dice, sides and
  damage bonus from the item type table (`DS:0x5D10`, loaded from the game's
  own `ITEMS` file), adds the missile adjustment (`0x388A2`) to THAC0 for a
  ranged weapon, both strength steps for a weapon with type flag 4, the
  weapon's own plus to both, a readied arrow's or quarrel's plus, and 1 more
  to THAC0 for an elf with item type 0x24, 0x25 or 0x29-0x2C.
* **Movement** starts from the base movement byte; readied body armour over
  150 weighs it down to 9, over 399 to 6, and magical armour gives 3 back to
  a movement of 9 or less (`0x378C3`); then everything carried, less the
  strength allowance (`0x38AE5`), caps it at 9 over 512, 6 over 768 and 3
  over 1024 (`0x37A69`).

Everything below that reads a DOS or C64 record reads the player's own
specimens at run time and skips cleanly on a machine that has none. No game
bytes are committed.
"""

from __future__ import annotations

import pathlib

import pytest

from goldbox import c64_codec, dos_codec, items
from goldbox.d64 import D64
from goldbox.savegame import load_save

CURSE = "curse-of-the-azure-bonds"
DELTAS = dos_codec.CURSE_OF_THE_AZURE_BONDS


# --- the rule's tables, no game data needed ----------------------------------

@pytest.mark.parametrize("strength, percentile, flag, want", [
    (3, 0, True, -1), (2, 0, True, -2), (15, 0, True, 0), (16, 0, True, 1),
    (17, 0, True, 1), (18, 0, True, 2), (18, 50, True, 3), (18, 51, True, 3),
    (18, 76, True, 4), (18, 99, True, 5), (18, 100, True, 6), (19, 0, True, 7),
    (24, 0, True, 12), (25, 0, True, 14),
    # `0x38A5F` returns 0 before it looks at strength when the flag is clear.
    (18, 100, False, 0),
])
def test_the_strength_damage_step_is_0x38a5f(strength, percentile, flag, want):
    assert dos_codec.dos_strength_damage_bonus(strength, percentile,
                                               flag) == want


@pytest.mark.parametrize("dexterity, want", [
    (0, -4), (2, -4), (3, -3), (5, -1), (6, 0), (15, 0), (16, 1), (18, 3),
    (19, 3), (20, 3), (21, 4), (23, 4), (24, 5), (25, 5), (26, 0),
])
def test_the_missile_adjustment_is_0x388a2(dexterity, want):
    assert dos_codec.dos_missile_adjustment(dexterity) == want


@pytest.mark.parametrize("strength, percentile, want", [
    (3, 0, -350), (5, 0, -250), (7, 0, -150), (11, 0, 0), (12, 0, 100),
    (15, 0, 200), (16, 0, 350), (17, 0, 500), (18, 0, 750), (18, 50, 1000),
    (18, 90, 1500), (18, 99, 2000), (18, 100, 3000), (21, 0, 6000),
    (22, 0, 7500), (23, 0, 9000), (25, 0, 15000),
])
def test_the_weight_allowance_is_0x38ae5(strength, percentile, want):
    assert dos_codec.dos_weight_allowance(strength, percentile) == want


def _record(strength=12, percentile=0, movement=12, coins=0):
    """A DOS Curse record with only what the rebuild reads set."""
    table = dos_codec.FIELDS_BY_NAME_FOR[CURSE]
    rec = bytearray(DELTAS.record_size)
    f = table["strength"]
    rec[f.offset:f.end] = bytes((strength, strength))
    rec[table["exceptional_strength"].offset] = percentile
    rec[table["exceptional_strength"].offset + 1] = percentile
    rec[table["dexterity"].offset:table["dexterity"].end] = bytes((12, 12))
    rec[table["thac0_base"].offset] = 40
    rec[table["movement"].offset] = movement
    rec[table["strength_bonus"].offset] = 1
    rec[table["race"].offset] = 7
    gold = table["gold"]
    rec[gold.offset:gold.end] = coins.to_bytes(2, "little")
    return bytes(rec)


@pytest.mark.parametrize("coins, want", [
    (0, 12), (512, 12), (513, 9), (768, 9), (769, 6), (1024, 6), (1025, 3),
])
def test_movement_steps_down_with_what_is_carried_past_the_allowance(
        coins, want):
    """Strength 12 carries 100 before anything counts (`0x38AE5`)."""
    got = dos_codec.dos_combat_rebuild(_record(coins=coins + 100), b"", None)
    assert got.movement_current == want


def _item(type_index, *, readied=True, plus=0, weight=0, quantity=0):
    it = bytearray(DELTAS.item_size)
    fields = dos_codec.ITEM_FIELDS_BY_NAME
    it[fields["type_index"].offset] = type_index
    it[fields["readied"].offset] = 1 if readied else 0
    it[fields["plus"].offset] = plus & 0xFF
    w = fields["weight"]
    it[w.offset:w.end] = weight.to_bytes(2, "little")
    it[fields["quantity"].offset] = quantity
    return bytes(it)


def _types(**rows):
    """A synthetic 128-type table: `rows` maps `t<index>` to (location,
    medium dice, sides, bonus, weapon flags)."""
    table = bytearray(items.ITEM_TYPE_COUNT * items.ITEM_TYPE_SIZE)
    for key, (loc, dice, sides, bonus, flags) in rows.items():
        at = int(key[1:]) * items.ITEM_TYPE_SIZE
        table[at + items.TYPE_LOCATION] = loc
        table[at + items.TYPE_DAMAGE_MEDIUM:at + items.TYPE_DAMAGE_MEDIUM + 3] = \
            bytes((dice, sides, bonus))
        table[at + items.TYPE_WEAPON_FLAGS] = flags
    return bytes(table)


@pytest.mark.parametrize("weight, plus, base, want", [
    (150, 0, 12, 12), (151, 0, 12, 9), (399, 0, 12, 9), (400, 0, 12, 6),
    # Magical armour gives 3 back to a movement of 9 or less: 9 -> 12,
    # 6 -> 9, and a light suit on a base of 12 stays 12.
    (151, 1, 12, 12), (400, 2, 12, 9), (150, 1, 12, 12),
    # The same test on a cursed suit: any non-zero plus.
    (400, -1, 12, 9),
    # Light armour resets movement to the base byte, which can be under 9.
    (100, 1, 6, 9),
])
def test_body_armour_weighs_movement_down_as_0x378c3_does(weight, plus, base,
                                                          want):
    armour = _item(0x32, weight=0, plus=plus)
    # The weight the armour rule reads is the item's own; the encumbrance
    # rule reads it too, so keep the suit under the allowance by giving the
    # character the strength to carry it.
    armour = bytearray(armour)
    w = dos_codec.ITEM_FIELDS_BY_NAME["weight"]
    armour[w.offset:w.end] = weight.to_bytes(2, "little")
    got = dos_codec.dos_combat_rebuild(
        _record(strength=18, percentile=100, movement=base), bytes(armour),
        _types(t50=(2, 0, 0, 0, 0)))
    assert got.movement_current == want


def test_an_elf_gets_one_more_to_hit_with_six_weapon_types():
    """`0x3784A`: race 2 with item type 0x24, 0x25 or 0x29-0x2C adds 1 to
    THAC0 only, after the damage byte has taken the plus."""
    weapon = _item(0x24, plus=1)
    types = _types(t36=(0, 1, 8, 0, 4))
    human = dos_codec.dos_combat_rebuild(_record(), weapon, types)
    rec = bytearray(_record())
    rec[dos_codec.FIELDS_BY_NAME_FOR[CURSE]["race"].offset] = 2
    elf = dos_codec.dos_combat_rebuild(bytes(rec), weapon, types)
    assert elf.thac0_current == human.thac0_current + 1
    assert elf.attack_forms == human.attack_forms


def test_a_weapon_with_type_flag_1_takes_the_readied_arrows_plus():
    """`0x377EB`: a weapon with type flag 1 adds the plus of a readied item
    of type 0x49 to both the damage byte and THAC0."""
    launcher = _item(0x2B, plus=1)
    arrows = _item(0x49, plus=2, quantity=20)
    types = _types(t43=(0, 1, 6, 0, 1 | 2), t73=(10, 1, 6, 0, 0))
    got = dos_codec.dos_combat_rebuild(_record(), launcher + arrows, types)
    # thac0_base 40, dexterity 12 (no missile step), plus 1 + 2.
    assert got.thac0_current == 43
    assert got.attack_forms[4] == 3


def test_a_readied_item_with_no_type_table_is_not_rebuilt():
    """Without the game's own `ITEMS` table nobody can say whether a readied
    item is a weapon or armour, so the writer keeps the source's bytes."""
    assert dos_codec.dos_combat_rebuild(_record(), _item(0x01), None) is None


# --- game data: the player's own DOS Curse -----------------------------------

def _curse_game() -> pathlib.Path:
    from tools.dos import dosbox

    try:
        return dosbox.find_game("CURSE")
    except FileNotFoundError as exc:
        pytest.skip(f"needs the player's DOS Curse archives: {exc}")


def _item_types() -> bytes:
    types = dos_codec.item_type_table(_curse_game())
    if types is None:
        pytest.skip("the player's DOS Curse has no readable ITEMS file")
    return types


def test_the_item_type_table_is_the_one_the_engine_loads():
    """`GAME.OVR:0xFBD7`-`0xFC30` opens `ITEMS`, seeks to byte 2 and block-reads it
    into `DS:0x5D10`, which is where `0x376C8` reads a weapon's flags; type
    1, the melee weapon MATHEW has readied in `curse-131-four-items-readied`,
    is 1d8 against man-sized with type flag 4."""
    types = _item_types()
    assert len(types) == items.ITEM_TYPE_COUNT * items.ITEM_TYPE_SIZE
    type_1 = types[1 * 16:2 * 16]
    assert type_1[items.TYPE_LOCATION] == 0
    assert type_1[items.TYPE_DAMAGE_MEDIUM:items.TYPE_DAMAGE_MEDIUM + 2] \
        == bytes((1, 8))
    assert type_1[items.TYPE_WEAPON_FLAGS] & items.WEAPON_ADDS_STRENGTH


def _specimen_root() -> pathlib.Path:
    from tools.registry import specimens

    root = specimens.tree_root()
    if not root.is_dir():
        pytest.skip("needs the specimen tree; see tools/registry/specimens.py")
    return root


def _items_of(char) -> bytes:
    return b"".join(i.to_bytes() for i in char.items)


#: The one engine-written record the rebuild does not reproduce, and why:
#: MATHEW dual-classed from paladin to magic-user in play and was saved
#: without the combat rebuild running again, so his roster tail still holds
#: the 1d8 of a type-1 weapon he no longer has readied -- and his `thac0_current`
#: still holds the paladin's 47.
_STALE_AFTER_DUAL_CLASS = {
    ("por-dos/WISH-SPEC-curse-131-dualclassed-in-area-1", "CHRDATJ1.SAV")}


def test_the_rebuild_reproduces_every_engine_written_dos_curse_record():
    """The damage, dice and movement bytes of every DOS Curse record DOS
    Curse wrote, recomputed from the rest of the same record: 74 records on
    this machine less one named exception, so 73 -- 71 with nothing readied
    and 2 with a weapon (item type 1, 1d8 with flag 4, and item type 0x56, a ranged weapon
    that takes the missile step).

    `thac0_current` is not compared here: `FE:25` rewrites `thac0_base`
    after the rebuild has read it, so a record whose base moved at its last
    load keeps a THAC0 built from the old one (nine records here). The
    conversion test below checks it against the record the engine loaded.
    """
    import test_cursedossaves as saves

    types = _item_types()
    table = dos_codec.FIELDS_BY_NAME_FOR[CURSE]
    tail = table["roster_tail"]
    move = table["movement_current"].offset
    checked, armed, mismatched = 0, 0, []
    for specimen_dir, name, char in saves._curse_dos_records():
        if (specimen_dir, name) in _STALE_AFTER_DUAL_CLASS:
            continue
        rec = char.to_bytes()
        got = dos_codec.dos_combat_rebuild(rec, _items_of(char), types)
        checked += 1
        armed += any(i.to_bytes()[dos_codec.ITEM_FIELDS_BY_NAME["readied"]
                                   .offset] for i in char.items)
        want = (bytes(rec[tail.offset + 3:tail.end]), rec[move])
        if (got.attack_forms, got.movement_current) != want:
            mismatched.append((specimen_dir, name, char.name, want,
                               (got.attack_forms, got.movement_current)))
    assert checked >= 60, checked
    assert armed >= 2, armed
    assert mismatched == []


def test_the_rebuild_turns_wishs_file_into_the_engines_resave():
    """`coab-dos/WISH-SPEC-curse-632-wish-converted-resave`: slot A is what
    Wish wrote, slot B what DOS Curse saved after loading it and nothing
    else. The rebuild applied to each slot A record gives slot B's
    `thac0_current`, roster tail and movement, six of six -- MARK's 12 going
    to 9 is his 1,800 platinum against the 1,250 his 18/53 strength carries,
    550 over."""
    root = _specimen_root()
    d = root / "coab-dos/WISH-SPEC-curse-632-wish-converted-resave"
    if not d.is_dir():
        pytest.skip("needs coab-dos/WISH-SPEC-curse-632-wish-converted-resave")
    table = dos_codec.FIELDS_BY_NAME_FOR[CURSE]
    tail = table["roster_tail"]
    checked = 0
    for n in range(1, 7):
        loaded = dos_codec.read_character(d / f"CHRDATA{n}.SAV")
        saved = dos_codec.read_character(d / f"CHRDATB{n}.SAV")
        got = dos_codec.dos_combat_rebuild(loaded.to_bytes(),
                                           _items_of(loaded), None)
        assert got is not None, loaded.name
        assert got.thac0_current == saved.get("thac0_current"), loaded.name
        assert got.attack_forms == saved.to_bytes()[tail.offset + 3:tail.end], \
            loaded.name
        assert got.movement_current == saved.get("movement_current"), \
            loaded.name
        checked += 1
    assert checked == 6


# --- conversions ------------------------------------------------------------

def _c64_party(rel: str):
    root = _specimen_root()
    disk = root / rel
    if not disk.is_file():
        pytest.skip(f"needs specimen {rel}")
    game, sg0, sg1 = load_save(D64.open(str(disk)))
    out = []
    for slot in sg0.characters:
        block = sg1.roster(slot.index) if sg1 is not None else None
        inv = [i.raw for i in items.items_for_slot(sg0.to_bytes(), slot.index)]
        out.append(c64_codec.read(slot.record, roster=block, inventory=inv,
                                  game=game, source=disk.name))
    return out


def test_the_curse_h_party_converts_to_the_engines_own_attack_and_movement():
    """`por-c64/WISH-SPEC-curse-h-engine-resave-walked` against
    `coab-dos/WISH-SPEC-c64todos-curse-resave` slot A, DOS Curse's own save
    after loading an earlier Wish conversion of the same party.

    The roster tail and movement are compared for all six. `thac0_current`
    is not: the conversion the engine loaded was written at `65d4fe2c`,
    which gave the magic-user PHILIPPE `thac0_base` 39. The rebuild made that
    40 with his strength step, and `FE:25` then raised the base to 40, so the
    resave holds (40, 40). Today's writer gives him the base `FE:25` gives,
    40, and the rebuild on that is 41. The 632 test above covers
    `thac0_current` against the record the engine actually loaded.
    """
    party = _c64_party("por-c64/WISH-SPEC-curse-h-engine-resave-walked.D64")
    root = _specimen_root()
    d = root / "coab-dos/WISH-SPEC-c64todos-curse-resave"
    if not d.is_dir():
        pytest.skip("needs coab-dos/WISH-SPEC-c64todos-curse-resave")
    resave = {c.name: c for c in (dos_codec.read_character(d / f"CHRDATA{n}.SAV")
                                  for n in range(1, 7))}
    checked = 0
    for neutral in party:
        rec, _itm, _spc, _rep = dos_codec.write(neutral, deltas=DELTAS)
        char = dos_codec.DosCharacter(rec, deltas=DELTAS)
        want = resave[char.name]
        assert char.raw("roster_tail") == want.raw("roster_tail"), char.name
        assert char.get("movement_current") == want.get("movement_current"), \
            char.name
        checked += 1
    assert checked == 6


def _armed_as_a_stale_c64_record(char):
    """An engine-written DOS character with a weapon readied, as the C64
    would hand it over if its roster had not been rebuilt since: the unarmed
    1d2 attack of a freshly made character, `thac0_current` equal to the
    base, and movement 12 -- which is what the C64 MALE ELF MAGE in
    `coab-c64/WISH-SPEC-curse-party-with-items.D64` holds with his ranged weapon
    (item type 0x56) readied."""
    rec, _rep = dos_codec.to_c64_record(char)
    neutral = c64_codec.read(rec, source="stale roster")
    stale = bytearray(neutral.get("roster_tail"))
    stale[3:9] = bytes((1, 0, 2, 0, 0, 0))
    for name, value in (("roster_tail", bytes(stale)),
                        ("thac0_current", neutral.get("thac0_base")),
                        ("movement_current", 12)):
        old = neutral.fields[name]
        neutral.set(name, value, "a stale C64 roster", old.confidence)
    return neutral


@pytest.mark.parametrize("specimen, name, weapon, compare_thac0", [
    ("por-dos/WISH-SPEC-curse-131-four-items-readied", "CHRDATI1.SAV",
     "item type 1, melee", True),
    # His stored THAC0 42 is `thac0_base` 39 plus the weapon's missile step of 3
    # for dexterity 18: the rebuild ran while his base was 39, and `FE:25`
    # has since raised it to 40. The damage and movement bytes do not read
    # the base.
    ("coab-dos/WISH-SPEC-curse-574-area2-spiritual-hammer-rest",
     "CHRDATB6.SAV", "item type 0x56, ranged", False),
])
def test_an_armed_character_converts_to_what_the_engine_stores(
        specimen, name, weapon, compare_thac0):
    """A weapon readied: the writer takes the dice, sides and damage from the
    game's own `ITEMS` table and the to-hit steps the weapon's flags name,
    and the result is the engine's own record."""
    types = _item_types()
    path = _specimen_root() / specimen / name
    if not path.is_file():
        pytest.skip(f"needs specimen {specimen}")
    engine = dos_codec.read_character(path)
    neutral = _armed_as_a_stale_c64_record(engine)
    rec, _itm, _spc, _rep = dos_codec.write(neutral, deltas=DELTAS,
                                            item_types=types)
    got = dos_codec.DosCharacter(rec, deltas=DELTAS)
    assert got.raw("roster_tail") == engine.raw("roster_tail"), weapon
    assert got.get("movement_current") == engine.get("movement_current")
    if compare_thac0:
        assert got.get("thac0_current") == engine.get("thac0_current")


def test_a_conversion_reads_the_item_types_from_the_dos_game_it_writes_for(
        tmp_path):
    """`new_dos_save` reads `ITEMS` out of the DOS game directory it is
    given. `coab-c64/WISH-SPEC-curse-party-with-items.D64`'s MALE ELF MAGE has item
    type 0x56, a ranged weapon, readied and a C64 roster that still holds the unarmed 1d2 and THAC0 39;
    the converted file holds the weapon's dice and his missile step instead."""
    game = _curse_game()
    types = _item_types()
    rel = "coab-c64/WISH-SPEC-curse-party-with-items.D64"
    disk = _specimen_root() / rel
    if not disk.is_file():
        pytest.skip(f"needs specimen {rel}")
    _g, sg0, sg1 = load_save(D64.open(str(disk)))
    dos_codec.new_dos_save(sg0.to_bytes(), sg1.to_bytes() if sg1 else None,
                           tmp_path, "A", game, title=CURSE)
    party = {c.name: c for c in dos_codec.read_party(tmp_path, "A")}
    mage = party["MALE ELF MAGE"]
    weapon = next(i.to_bytes() for i in mage.items
                 if i.to_bytes()[dos_codec.ITEM_FIELDS_BY_NAME["readied"].offset])
    row = types[weapon[dos_codec.ITEM_FIELDS_BY_NAME["type_index"].offset] * 16:][:16]
    tail = mage.raw("roster_tail")
    assert (tail[3], tail[5], tail[7]) == tuple(
        row[items.TYPE_DAMAGE_MEDIUM:items.TYPE_DAMAGE_MEDIUM + 3])
    dexterity = mage.to_bytes()[dos_codec.FIELDS_BY_NAME_FOR[CURSE]
                                ["dexterity"].offset + 1]
    assert mage.get("thac0_current") == (
        mage.get("thac0_base") + dos_codec.dos_missile_adjustment(dexterity))
