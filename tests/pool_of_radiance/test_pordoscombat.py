"""A C64 Pool of Radiance party converted to DOS gets the current THAC0,
armour class, attack bytes and movement DOS Pool of Radiance's own combat
rebuild stores (#634).

DOS Pool of Radiance keeps its combat rebuild resident, at `START.EXE` image
`0x1758`, and **its loader never runs it**: a static walk from the party
loader (`GAME.OVR:0x1F5E8`, overlay entry `7C:48`) does not reach it, and two
engine resaves of a Wish conversion kept Wish's own numbers through LOAD,
walking and ENCAMP > SAVE. VIEW (`85:39` -> `0x21F32`, `85:2A` -> `0x21642`),
a fight and the item screens run it. Until one does, the party panel drawn
the moment the game loads (`0x1307` -> `0x148F`) prints the stored armour
class, and the PARTYSTRENGTH script command (`GAME.OVR:0x200C`) reads the
stored THAC0 and armour class into the size of a random encounter. So a
converted character whose stored numbers differ from the rebuild shows one
armour class in the panel and another on his sheet, and counts differently
towards the next encounter, until his first VIEW or fight.

The rebuild, read off the routine:

* **THAC0, the attack bytes and movement** follow Curse's rule
  (`goldbox.dos_codec.dos_combat_rebuild`) through Pool's own helpers:
  `0x0BA0` the weapon, `0x0D9B` body armour, `0x0F40` the encumbrance cap,
  `0x1D08` the missile step, `0x1E22`/`0x1EC5` the strength steps, `0x1F4B`
  the weight allowance; a readied bag of holding takes 5000 off the weight.
* **The armour class** (`0x1A17`-`0x1B83`, with `0x0E22` per readied item and
  `0x1C86` for dexterity) is the sum of five terms -- dexterity, shield,
  cloak, ring and armour -- with the armour term raised to the base armour
  class; roster tail byte 0 is armour + cloak + ring - 2.
* The item type table is the game's own `ITEMS` file, block-read to
  `DS:0x5582` at `GAME.OVR:0xEB6C`-`0xEBAE`.

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

POR = "pool-of-radiance"
DELTAS = dos_codec.POOL_OF_RADIANCE
TABLE = dos_codec.FIELDS_BY_NAME_FOR[POR]
_ITEM = dos_codec.ITEM_FIELDS_BY_NAME


# --- the rule, no game data needed -------------------------------------------

@pytest.mark.parametrize("dexterity, want", [
    (0, 0), (1, -4), (3, -4), (4, -3), (6, -1), (7, 0), (14, 0), (15, 1),
    (18, 4), (19, 4), (20, 4), (21, 5), (23, 5), (24, 6), (25, 6), (26, 0),
])
def test_the_dexterity_armour_step_is_start_exe_0x1c86(dexterity, want):
    assert dos_codec.dos_dexterity_armour_adjustment(dexterity) == want


def _record(dexterity=12, strength=12, movement=12, base_ac=50, coins=0):
    """A DOS Pool of Radiance record with only what the rebuild reads set."""
    rec = bytearray(DELTAS.record_size)
    rec[TABLE["strength"].offset] = strength
    rec[TABLE["dexterity"].offset] = dexterity
    rec[TABLE["thac0_base"].offset] = 40
    rec[TABLE["movement"].offset] = movement
    rec[TABLE["strength_bonus"].offset] = 1
    rec[TABLE["race"].offset] = 7
    rec[TABLE["armour_class_base"].offset] = base_ac
    gold = TABLE["gold"]
    rec[gold.offset:gold.end] = coins.to_bytes(2, "little")
    return bytes(rec)


def _item(type_index, *, readied=True, plus=0, weight=0, quantity=0, name1=0):
    it = bytearray(DELTAS.item_size)
    it[_ITEM["type_index"].offset] = type_index
    it[_ITEM["readied"].offset] = 1 if readied else 0
    it[_ITEM["plus"].offset] = plus & 0xFF
    w = _ITEM["weight"]
    it[w.offset:w.end] = weight.to_bytes(2, "little")
    it[_ITEM["quantity"].offset] = quantity
    it[_ITEM["name1"].offset] = name1
    return bytes(it)


def _types(**rows):
    """A synthetic 128-type table: `rows` maps `t<index>` to (location,
    protection byte)."""
    table = bytearray(items.ITEM_TYPE_COUNT * items.ITEM_TYPE_SIZE)
    for key, (loc, protection) in rows.items():
        at = int(key[1:]) * items.ITEM_TYPE_SIZE
        table[at + items.TYPE_LOCATION] = loc
        table[at + items.TYPE_PROTECTION] = protection
    return bytes(table)


#: Body armour of 56 (AC 4), a shield of 1, a cloak and a ring of
#: protection (protection 0 with bit 7), and a weaponless item type.
_ARMOURY = _types(t50=(2, 0x80 | 56), t51=(1, 0x80 | 1), t52=(5, 0x80),
                  t53=(9, 0x80), t54=(9, 0x80), t55=(3, 0x05))


@pytest.mark.parametrize("dexterity, kit, want_ac, want_bonus", [
    # Nothing readied: the base armour class, 50 (AC 10), and 50 - 2.
    (12, [], 50, 48),
    # Dexterity 16 adds 2 to the byte, and not to the armour bonus.
    (16, [], 52, 48),
    # Dexterity 5 takes 2 off.
    (5, [], 48, 48),
    # Banded mail and a shield: 56 + 1.
    (12, [_item(50), _item(51)], 57, 54),
    # A +1 shield counts 2.
    (12, [_item(50), _item(51, plus=1)], 58, 54),
    # A +2 cloak adds to the cloak term, and the armour bonus takes it.
    (12, [_item(50), _item(52, plus=2)], 58, 56),
    # Two rings of protection: the better one only.
    (12, [_item(53, plus=1), _item(54, plus=2)], 52, 50),
    # A ring with unenchanted armour counts; with +1 armour it is dropped.
    (12, [_item(50), _item(53, plus=2)], 58, 56),
    (12, [_item(50, plus=1), _item(53, plus=2)], 57, 55),
    # An item whose protection byte has no bit 7 adds nothing.
    (12, [_item(55)], 50, 48),
    # Unreadied armour adds nothing.
    (12, [_item(50, readied=False)], 50, 48),
])
def test_the_armour_class_is_the_five_terms_0x0e22_builds(
        dexterity, kit, want_ac, want_bonus):
    got = dos_codec.dos_combat_rebuild(_record(dexterity=dexterity),
                                       b"".join(kit), _ARMOURY, POR)
    assert (got.armour_class, got.armour_bonus) == (want_ac, want_bonus)


def test_armour_worse_than_the_base_leaves_the_base():
    """`0x1B2E`: the armour term is raised to the record's own base armour
    class, so padding of 52 on a base of 55 counts 55."""
    got = dos_codec.dos_combat_rebuild(
        _record(base_ac=55), _item(56),
        _types(t56=(2, 0x80 | 52)), POR)
    assert got.armour_class == 55


def test_a_readied_bag_of_holding_lightens_the_load():
    """`0x18DA` and `0x1AE3`: a readied item whose first name word is 0xBA
    takes 5000 off the weight the movement cap reads. Strength 12 carries
    100 before anything counts, so 5500 coins cap movement at 3 without the
    bag and leave it at 12 with it."""
    heavy = _record(coins=5500)
    types = _types(t60=(4, 0))
    without = dos_codec.dos_combat_rebuild(heavy, _item(60), types, POR)
    bag = dos_codec.dos_combat_rebuild(heavy, _item(60, name1=0xBA), types, POR)
    assert (without.movement_current, bag.movement_current) == (3, 12)


def test_curse_keeps_its_armour_class_unread():
    """Curse's rebuild has an armour half too (`0x19A`, `0x19B`) that has not
    been read, so the rule answers nothing for it and the writer copies."""
    rec = bytearray(dos_codec.CURSE_OF_THE_AZURE_BONDS.record_size)
    got = dos_codec.dos_combat_rebuild(bytes(rec), b"", None,
                                       "curse-of-the-azure-bonds")
    assert (got.armour_class, got.armour_bonus) == (None, None)


# --- game data: the player's own DOS Pool of Radiance ------------------------

def _pool_game() -> pathlib.Path:
    from tools.dos import dosbox

    try:
        return dosbox.find_game("POOLRAD")
    except FileNotFoundError as exc:
        pytest.skip(f"needs the player's DOS Pool of Radiance archives: {exc}")


def _item_types() -> bytes:
    types = dos_codec.item_type_table(_pool_game())
    if types is None:
        pytest.skip("the player's DOS Pool of Radiance has no readable ITEMS")
    return types


def test_the_item_type_table_is_the_one_the_engine_loads():
    """`GAME.OVR:0xEB6C`-`0xEBAE` opens `ITEMS`, seeks to byte 2 and
    block-reads it to `DS:0x5582`, where `0x0E22` reads a readied item's
    location (`+0`) and protection (`+6`). BRUTUS's two readied pieces in
    `por-190-c64-outdoor-1` are type 0x39, body armour of 56 (AC 4), and
    type 0x3B, a shield of 1."""
    types = _item_types()
    assert len(types) == items.ITEM_TYPE_COUNT * items.ITEM_TYPE_SIZE
    for type_index, location, protection in ((0x39, 2, 0x80 | 56),
                                             (0x3B, 1, 0x80 | 1)):
        row = types[type_index * 16:type_index * 16 + 16]
        assert (row[items.TYPE_LOCATION], row[items.TYPE_PROTECTION]) == (
            location, protection), hex(type_index)


def _specimen_root() -> pathlib.Path:
    from tools.registry import specimens

    root = specimens.tree_root()
    if not root.is_dir():
        pytest.skip("needs the specimen tree; see tools/registry/specimens.py")
    return root


def _items_of(char) -> bytes:
    return b"".join(i.to_bytes() for i in char.items)


def _weight_sum(rec: bytes, itm: bytes) -> int:
    """The encumbrance the rebuild itself stores (`0x17BE`-`0x1951`): every
    item's weight times its quantity, or once at quantity 0, plus the seven
    purses, 16-bit. No record here readies a bag of holding."""
    total = 0
    for i in range(0, len(itm), DELTAS.item_size):
        piece = itm[i:i + DELTAS.item_size]
        w = _ITEM["weight"]
        total += int.from_bytes(piece[w.offset:w.end], "little") * (
            piece[_ITEM["quantity"].offset] or 1)
    for coin in ("copper", "silver", "electrum", "gold", "platinum", "gems",
                 "jewelry"):
        f = TABLE[coin]
        total += int.from_bytes(rec[f.offset:f.end], "little")
    return total & 0xFFFF


#: Specimens whose combat bytes are not the DOS rebuild's, by who wrote them:
#: * Wish, and the DOS engine left them alone -- a load, a walk and
#:   ENCAMP > SAVE run no rebuild. Each is the engine's save of a conversion
#:   of ours, with no VIEW or fight on the characters kept here
#:   (`provenance.toml`): `amigatodos-por-resave`, `por-amiga-slums-dos-resave`,
#:   `por-amiga-newphlan-dos-resave`, `por-52-dialog-converted-resave`,
#:   `por-gnome-converted` (slot D; slot C is excluded as ours already) and
#:   `c64todos-pool-52-walk-resave`, whose one viewed character is taken back
#:   by `_VIEWED_AFTER_A_CONVERSION`;
#: * our own poke: `por-party-trained-c2` and `por-train-clamp` went in with
#:   gold 20000 and the encumbrance poked to match, and no VIEW or fight
#:   followed (`tools/dos/dostrain.py`);
#: * `issue641-dirten-seven-resave`, where every record came back as our
#:   writer wrote it bar the portrait bytes although the run viewed all seven
#:   sheets -- the unexplained case part 2 of #634 named for the saves.
_NOT_REBUILT = {
    "por-dos/WISH-SPEC-amigatodos-por-resave",
    "por-dos/WISH-SPEC-por-amiga-slums-dos-resave",
    "por-dos/WISH-SPEC-por-amiga-newphlan-dos-resave",
    "por-dos/WISH-SPEC-por-52-dialog-converted-resave",
    "por-dos/WISH-SPEC-por-gnome-converted",
    "por-dos/WISH-SPEC-c64todos-pool-52-walk-resave",
    "por-dos/WISH-SPEC-por-party-trained-c2",
    "por-dos/WISH-SPEC-por-train-clamp",
    "por-dos/WISH-SPEC-issue641-dirten-seven-resave",
}

#: The one character in `_NOT_REBUILT` whose sheet the run drew with VIEW,
#: so the rebuild ran on him: WISHFTR (`provenance.toml`).
_VIEWED_AFTER_A_CONVERSION = {
    ("por-dos/WISH-SPEC-c64todos-pool-52-walk-resave", "CHRDATD1.SAV"),
}


def _rebuilt_records():
    """Engine-written DOS Pool of Radiance records the DOS rebuild wrote last:
    stored encumbrance equal to the rebuild's own sum -- the rebuild writes it
    in the same pass, so a record that fails it has had its items or coins
    move since the rebuild last ran -- and not in `_NOT_REBUILT`."""
    import test_pordossaves as saves

    out = []
    for specimen_dir, name, char in saves._por_dos_records():
        rec = char.to_bytes()
        if (specimen_dir in _NOT_REBUILT
                and (specimen_dir, name) not in _VIEWED_AFTER_A_CONVERSION):
            continue
        if _weight_sum(rec, _items_of(char)) != int.from_bytes(
                rec[TABLE["encumbrance"].offset:TABLE["encumbrance"].end],
                "little"):
            continue
        out.append((specimen_dir, name, char))
    return out


def _stored(char):
    rec = char.to_bytes()
    tail = TABLE["roster_tail"]
    return (rec[TABLE["thac0_current"].offset], rec[TABLE["armour_class"].offset],
            rec[tail.offset], bytes(rec[tail.offset + 3:tail.end]),
            rec[TABLE["movement_current"].offset])


def _ruled(rebuilt):
    return (rebuilt.thac0_current, rebuilt.armour_class, rebuilt.armour_bonus,
            rebuilt.attack_forms, rebuilt.movement_current)


def test_the_rebuild_reproduces_every_rebuilt_engine_record():
    """Current THAC0, armour class, tail byte 0, the attack bytes and movement
    of every DOS Pool of Radiance record the DOS rebuild wrote last,
    recomputed from the rest of the same record: 62 records where this was
    measured and none missing. They are mostly unarmed; the one with
    anything readied is THRENDER GRONE, whose flail and banded mail were
    readied through VIEW > ITEMS > READY (`por-item-granted`): banded mail 56
    plus dexterity 17's 3 is his 59. The weapon, shield, ring and cloak
    terms rest on the bytecode and the synthetic tests above."""
    types = _item_types()
    records = _rebuilt_records()
    if not records:
        pytest.skip("needs the specimen tree; see tools/registry/specimens.py")
    armed, mismatched = 0, []
    for specimen_dir, name, char in records:
        got = dos_codec.dos_combat_rebuild(char.to_bytes(), _items_of(char),
                                           types, POR)
        armed += any(i.to_bytes()[_ITEM["readied"].offset] for i in char.items)
        if _ruled(got) != _stored(char):
            mismatched.append((specimen_dir, name, char.name))
    assert len(records) >= 55, len(records)
    assert armed >= 1, armed
    assert mismatched == []


def test_loading_and_walking_do_not_run_the_rebuild_and_view_does():
    """What makes the stored numbers reachable, from the engine's own saves:

    * `amigatodos-por-resave`, a Wish conversion loaded, walked one square
      and saved with ENCAMP > SAVE: LADY KATHERINE, TWIN and MALCYON, all
      magic-user 1 with `thac0_base` 40, still hold the 39 Wish wrote where
      the rebuild stores 40;
    * `por-amiga-slums-dos-resave`, loaded and saved: BRUTUS has nothing
      readied and still holds armour class 58 (AC 2), where the rebuild
      stores his base 50;
    * `por-enc-spoiled-viewed`, the control: VIEW drew WISHFTR's sheet only,
      and his movement is the rebuild's 3 for 19000 gold while the five
      whose sheets were not drawn, carrying the same gold, still hold 12."""
    types = _item_types()
    root = _specimen_root()

    def load(rel):
        path = root / rel
        if not path.is_file():
            pytest.skip(f"needs specimen {rel}")
        char = dos_codec.read_character(path)
        return char, dos_codec.dos_combat_rebuild(
            char.to_bytes(), _items_of(char), types, POR)

    for n in (3, 5, 6):
        char, got = load(f"por-dos/WISH-SPEC-amigatodos-por-resave/CHRDATA{n}.SAV")
        assert (char.get("thac0_current"), got.thac0_current) == (39, 40), \
            char.name
    char, got = load("por-dos/WISH-SPEC-por-amiga-slums-dos-resave/CHRDATD6.SAV")
    assert char.name == "BRUTUS"
    assert (char.get("armour_class"), got.armour_class) == (58, 50)
    for n in range(1, 7):
        char, got = load(f"por-dos/WISH-SPEC-por-enc-spoiled-viewed/CHRDATD{n}.SAV")
        assert got.movement_current == 3, char.name
        assert char.get("movement_current") == (3 if n == 1 else 12), char.name


# --- conversions -------------------------------------------------------------

def _c64_party(rel: str):
    disk = _specimen_root() / rel
    if not disk.is_file():
        pytest.skip(f"needs specimen {rel}")
    game, sg0, sg1 = load_save(D64.open(str(disk)))
    out = {}
    for slot in sg0.characters:
        block = sg1.roster(slot.index) if sg1 is not None else None
        inv = [i.raw for i in items.items_for_slot(sg0.to_bytes(), slot.index)]
        char = c64_codec.read(slot.record, roster=block, inventory=inv,
                              game=game, source=disk.name)
        out[str(char.get("name")).strip().upper()] = char
    return out


def test_an_unarmed_party_converts_to_the_numbers_dos_pool_stores():
    """`por-c64/WISH-SPEC-por-hall-2npc-recruit.D64`, nobody holding
    anything. LADY KATHERINE and MALCYON, magic-user 1, hold THAC0 39 on the
    C64 (the C64's magic-user row); DOS gives them base 40, and with
    strength 16 and 18 and no strength step the rebuild stores 40 -- which is
    what WISHMAG, a DOS-made magic-user 1, holds in every engine record on
    this machine. BRUTUS holds armour class 51 on the C64 with nothing
    readied and dexterity 14; the rebuild stores his base, 50. Before the fix
    the writer copied 39, 39 and 51."""
    party = _c64_party("por-c64/WISH-SPEC-por-hall-2npc-recruit.D64")
    written = {}
    for name in ("LADY KATHERINE", "MALCYON", "BRUTUS"):
        rec, _itm, _spc, _rep = dos_codec.write(party[name], deltas=DELTAS)
        written[name] = dos_codec.DosCharacter(rec, deltas=DELTAS)
    assert written["LADY KATHERINE"].get("thac0_current") == 40
    assert written["MALCYON"].get("thac0_current") == 40
    assert written["BRUTUS"].get("armour_class") == 50


def test_an_armed_party_converts_through_the_games_own_item_types(tmp_path):
    """`por-c64/WISH-SPEC-por-190-c64-outdoor-1.D64` converted with
    `new_dos_save`, which reads `ITEMS` out of the DOS game directory:

    * BRUTUS readies banded mail (56) and a shield (1) with dexterity 14, so
      the rebuild stores 57, AC 3, where the C64 holds 58. The engine's own
      resave in `docs/117-save-conversion.md` ("What the engine recomputes
      on load") recorded exactly this 58 -> 57 for BRUTUS;
    * MALCYON readies a dart, item type 9, whose weapon flags are 0x10 alone
      -- no missile step -- so the rebuild stores his base, 40, where the
      C64 holds 42;
    * LADY KATHERINE, magic-user 1, 40 where the C64 holds 39.

    Before the fix the writer copied 58, 42 and 39."""
    game = _pool_game()
    _item_types()
    rel = "por-c64/WISH-SPEC-por-190-c64-outdoor-1.D64"
    disk = _specimen_root() / rel
    if not disk.is_file():
        pytest.skip(f"needs specimen {rel}")
    _g, sg0, sg1 = load_save(D64.open(str(disk)))
    dos_codec.new_dos_save(sg0.to_bytes(), sg1.to_bytes() if sg1 else None,
                           tmp_path, "A", game, title=POR)
    party = {c.name: c for c in dos_codec.read_party(tmp_path, "A")}
    assert party["BRUTUS"].get("armour_class") == 57
    assert party["MALCYON"].get("thac0_current") == 40
    assert party["LADY KATHERINE"].get("thac0_current") == 40
    for char in party.values():
        want = dos_codec.dos_combat_rebuild(char.to_bytes(), _items_of(char),
                                            _item_types(), POR)
        assert _stored(char) == _ruled(want), char.name


def test_a_party_the_engine_viewed_converts_to_its_own_resave():
    """The control: `por-c64/WISH-SPEC-por-52-dialog-converted-resave.D64`
    against `por-dos/WISH-SPEC-c64todos-pool-52-walk-resave` slot D, DOS Pool
    of Radiance's own save after loading an earlier conversion of the same
    party, VIEWing WISHFTR and walking. These six already held the rebuild's
    numbers on the C64, so the fix changes nothing here, and every combat
    byte of all six equals the engine's."""
    party = _c64_party("por-c64/WISH-SPEC-por-52-dialog-converted-resave.D64")
    d = _specimen_root() / "por-dos/WISH-SPEC-c64todos-pool-52-walk-resave"
    if not d.is_dir():
        pytest.skip("needs por-dos/WISH-SPEC-c64todos-pool-52-walk-resave")
    resave = {c.name: c for c in (dos_codec.read_character(d / f"CHRDATD{n}.SAV")
                                  for n in range(1, 7))}
    checked = 0
    for neutral in party.values():
        rec, _itm, _spc, _rep = dos_codec.write(neutral, deltas=DELTAS,
                                                item_types=_item_types())
        char = dos_codec.DosCharacter(rec, deltas=DELTAS)
        assert _stored(char) == _stored(resave[char.name]), char.name
        checked += 1
    assert checked == 6
