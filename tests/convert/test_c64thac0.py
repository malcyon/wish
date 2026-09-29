"""A converted character's THAC0 on the C64 sheet, computed rather than copied.

`#405 (A converted character's THAC0 on the C64 sheet is the source save's
stored byte, and the engine only corrects it at his first fight)`. The C64
sheet draws `thac0_current` straight (`LIBRARY $3758`) and nothing recomputes
it before the party's first fight, so a copied byte can carry a number the
C64's own tables would never produce -- a low-level magic-user or thief is
THAC0 20 on DOS and 21 on the C64 (`#318`). Donald's ruling on the issue:
compute it on the way out, the way `LIBRARY $3918` (`$3729` in Pool of
Radiance) rebuilds it at the party's first fight -- `thac0_base` plus the
AD&D strength to-hit bonus, gated on `strength_bonus_flag` -- so our number
and the engine's own first recompute agree from the moment the character
arrives. `docs/205-the-c64-thac0-rebuild.md` is the evidence, from `#368`.

Synthetic characters throughout except the last test, which reads the real
to-hit table off the player's own `LIBRARY` the way
`tests/convert/test_c64strengthflag.py` does, so the claim that our number is the
engine's own is checked rather than assumed.
"""

from __future__ import annotations

import gamedata
from gamedata import needs_disks
from support.dossave import _save_dir, needs_dos_saves

from goldbox import c64_codec, derive, dos_codec
from goldbox import levels as level_tables
from goldbox.encoding import COMBAT_BIAS, combat_value
from goldbox.items import TYPE_LOCATION, TYPE_WEAPON_FLAGS, ItemType, load_item_types
from goldbox.neutral import NeutralCharacter


def _char(levels: dict[str, int], strength: int = 10, percentile: int = 0,
          source_thac0_current: int | None = None) -> NeutralCharacter:
    """A neutral character with just enough to reach `c64_codec.write`'s
    THAC0 arithmetic: class levels, a strength score, and a source-stored
    `thac0_current` -- the byte a real save carries that this fix stops
    trusting."""
    char = NeutralCharacter("test", source="a made-up character")
    char.set("levels", levels, "made up")
    char.set("strength", strength, "made up")
    char.set("exceptional_strength", percentile, "made up")
    char.set("thac0_base", 8, "made up: overwritten by the class levels "
                              "regardless (#366)")
    if source_thac0_current is not None:
        char.set("thac0_current", source_thac0_current,
                 "made up: the source save's own stored byte")
    return char


def test_thac0_current_byte_adds_the_bonus_only_when_the_gate_is_open():
    """The pure arithmetic `LIBRARY $3918` does: `thac0_base` plus the
    strength to-hit bonus, and nothing added when `strength_bonus_flag` is
    clear (#277) -- the case `write` itself can never produce, since it
    always sets the flag to 1, so the gate is exercised directly here."""
    assert c64_codec.thac0_current_byte(44, 2, True) == 46
    assert c64_codec.thac0_current_byte(44, 2, False) == 44
    assert c64_codec.thac0_current_byte(44, 0, True) == 44


def test_thac0_current_byte_wraps_like_the_c64s_own_byte_arithmetic():
    """The stored byte is `60 - THAC0`; a strong bonus can carry it past 255
    the way an 8-bit `ADC` would, and the engine's own byte does the same."""
    assert c64_codec.thac0_current_byte(254, 3, True) == 1


def test_a_low_level_magic_user_arrives_with_the_c64s_own_thac0():
    """`#318 (DOS gives a low-level magic-user or thief THAC0 20 where the
    C64 gives 21, and our table holds only the C64's own)`: a magic-user 3's
    DOS save stores THAC0 20 -- byte 40 -- and the C64's own table gives 21.
    Before this fix the converted sheet showed 20, the DOS number, until the
    party's first fight; now it shows 21 from the moment the character
    arrives."""
    char = _char({"magic-user": 3}, source_thac0_current=COMBAT_BIAS - 20)
    rec, _ = c64_codec.write(char)
    expected = level_tables.base_thac0({"magic-user": 3}, char.game)
    assert expected == 21          # the C64's own table, not DOS's 20 (#366)
    assert rec.thac0_base_value == expected
    assert combat_value(rec.get("thac0")) == expected
    assert combat_value(rec.get("thac0")) != 20


def test_a_character_whose_source_thac0_already_agreed_converts_unchanged():
    """The control: a fighter 1's THAC0 is 20 in both ports (#318's own
    table), and strength 10 gives no bonus, so the recomputed byte matches
    the number the source already held."""
    expected = level_tables.base_thac0({"fighter": 1}, None)
    assert expected == 20
    char = _char({"fighter": 1}, strength=10,
                 source_thac0_current=COMBAT_BIAS - 20)
    rec, _ = c64_codec.write(char)
    assert combat_value(rec.get("thac0")) == 20


def test_a_strong_character_gets_his_bonus_through_the_full_conversion():
    """`#277`'s worked example, end to end through `write`: an 18/75 fighter
    1. `write` always opens the strength gate (#277), so his converted sheet
    carries the +2 to-hit bonus the C64's own table gives that score, two
    points better than his bare `thac0_base`."""
    char = _char({"fighter": 1}, strength=18, percentile=75,
                 source_thac0_current=COMBAT_BIAS - 99)   # a stale sentinel
    rec, _ = c64_codec.write(char)
    assert rec.get("strength_bonus_flag") == 1
    assert rec.get("strength_index") == 20
    base = combat_value(rec.get("thac0_base"))
    assert base == 20                          # fighter 1, C64's own table
    assert combat_value(rec.get("thac0")) == base - 2
    assert combat_value(rec.get("thac0")) != base


def test_our_number_is_what_the_engines_own_first_fight_would_write():
    """The real check: read `LIBRARY`'s own to-hit table for an 18/75
    fighter's row and confirm our recomputed byte is exactly what
    `LIBRARY $3918`'s `ADC` would leave in the roster the moment the party's
    first fight starts -- so the sheet never has to correct itself again.

    Same technique as
    `tests/convert/test_c64strengthflag.py::test_the_converted_fighter_reaches_plus_two_and_plus_three_in_the_games_own_tables`:
    the table stays on the player's own disk, and only the one number it
    gives comes back here.
    """
    library = gamedata.game_file("LIBRARY")
    base = 0x2C48

    def signed(table: int, row: int) -> int:
        byte = library[table - base + row]
        return byte - 256 if byte > 127 else byte

    char = _char({"fighter": 1}, strength=18, percentile=75,
                 source_thac0_current=COMBAT_BIAS - 1)
    rec, _ = c64_codec.write(char)
    row = rec.get("strength_index") if rec.get("strength_bonus_flag") else 0
    hit_from_the_game = signed(0x3651, row)
    engine_thac0 = combat_value(rec.get("thac0_base")) - hit_from_the_game
    assert combat_value(rec.get("thac0")) == engine_thac0


# -- Pool of Radiance: the readied weapon's terms (`LIBRARY $3729`) ----------
#
# Synthetic ITEMS types and items: a type record is 16 bytes with the body
# place at +0 and the weapon flags at +14, an item record has its type at +0,
# its plus at +4 and the readied bit at +6.

def _type(flags: int, location: int = 0) -> ItemType:
    raw = bytearray(16)
    raw[TYPE_LOCATION] = location
    raw[TYPE_WEAPON_FLAGS] = flags
    return ItemType(0, bytes(raw))


def _item(type_index: int, plus: int = 0, readied: bool = True) -> bytes:
    raw = bytearray(16)
    raw[0] = type_index
    raw[4] = plus & 0xFF
    raw[6] = 0x80 if readied else 0
    return bytes(raw)


#: Type 1 sword (strength, `$04`), 2 dart (missile only, `$1A` as the game's
#: dart), 3 hammer (`$14`: strength only), 4 both bits, 5 an unarmed body
#: item that is not a weapon, `$1C` and `$49` the two ammunition types.
_TYPES = {1: _type(0x04), 2: _type(0x1A), 3: _type(0x14), 4: _type(0x06),
          5: _type(0x00, location=2), 6: _type(0x83),
          0x1C: _type(0x8A, location=10), 0x49: _type(0x00, location=10)}


def _pool_char(inventory, dexterity: int = 18) -> NeutralCharacter:
    char = _char({"fighter": 3}, strength=18, percentile=75,
                 source_thac0_current=COMBAT_BIAS - 99)
    char.set("dexterity", dexterity, "made up")
    char.set("inventory", inventory, "made up")
    return char


def _pool(inventory, dexterity: int = 18):
    rec, rep = c64_codec.write(_pool_char(inventory, dexterity),
                               item_types=_TYPES)
    hit, _ = derive.strength_bonuses(18, 75)
    assert hit == 2
    return rec, hit


def test_with_no_weapon_readied_the_strength_bonus_is_added():
    rec, hit = _pool([_item(5)])
    assert rec.get("thac0") == rec.get("thac0_base") + hit


def test_a_dex_only_missile_takes_the_stored_dex_term_and_not_strength():
    rec, _ = _pool([_item(2)])
    assert rec.get("missile_attack_adjustment") == 3
    assert rec.get("thac0") == rec.get("thac0_base") + 3


def test_a_strength_only_thrown_weapon_takes_strength_and_its_plus():
    rec, hit = _pool([_item(3, plus=1)])
    assert rec.get("thac0") == rec.get("thac0_base") + hit + 1


def test_a_weapon_with_both_bits_takes_both():
    rec, hit = _pool([_item(4)])
    assert rec.get("thac0") == rec.get("thac0_base") + 3 + hit


def test_a_melee_weapon_takes_strength_and_a_cursed_plus_subtracts():
    rec, hit = _pool([_item(1, plus=-2)])
    assert rec.get("thac0") == rec.get("thac0_base") + hit - 2


def test_an_unreadied_weapon_counts_for_nothing():
    rec, hit = _pool([_item(1, plus=5, readied=False)])
    assert rec.get("thac0") == rec.get("thac0_base") + hit


def test_a_launcher_takes_its_ammunitions_plus():
    rec, _ = _pool([_item(6), _item(0x1C, plus=2)])
    assert rec.get("thac0") == rec.get("thac0_base") + 3 + 2
    rec, _ = _pool([_item(6), _item(0x1C, plus=2, readied=False)])
    assert rec.get("thac0") == rec.get("thac0_base") + 3


def test_the_dex_term_is_the_missile_table_not_dexterity_itself():
    table = {3: -3, 4: -2, 5: -1, 6: 0, 15: 0, 16: 1, 17: 2, 18: 3, 20: 3,
             21: 4, 25: 4}
    for dexterity, want in table.items():
        assert c64_codec.pool_missile_adjustment(dexterity) == want
        rec, _ = _pool([_item(2)], dexterity=dexterity)
        assert rec.get("missile_attack_adjustment") == want


def test_without_a_table_the_pool_byte_is_the_strength_only_one():
    char = _pool_char([_item(2)])
    rec, _ = c64_codec.write(char)
    hit, _ = derive.strength_bonuses(18, 75)
    assert rec.get("thac0") == rec.get("thac0_base") + hit
    assert rec.get("missile_attack_adjustment") == 0


def test_curse_and_silver_blades_keep_the_strength_only_byte():
    """Their weapon block (`$387E`) is unread, so the rule is not applied."""
    for game in ("curse-of-the-azure-bonds", "secret-of-the-silver-blades"):
        char = NeutralCharacter("test", source="a made-up character",
                                game=game)
        for name, value in (("levels", {"fighter": 3}), ("strength", 18),
                            ("exceptional_strength", 75), ("thac0_base", 8),
                            ("dexterity", 18),
                            ("inventory", [_item(2)])):
            char.set(name, value, "made up")
        char.set("thac0_current", 1, "made up")
        rec, _ = c64_codec.write(char, item_types=_TYPES)
        hit, _ = derive.strength_bonuses(18, 75)
        assert rec.get("thac0") == rec.get("thac0_base") + hit, game
        assert rec.get("missile_attack_adjustment") == 0, game


@needs_dos_saves
@needs_disks
def test_dos_pool_slot_a_arrives_with_the_engines_own_thac0_and_dex_term():
    """The party the #740 comments name, against the predictions posted on
    #405 (roster `+0x0E` and record `0x0EC`)."""
    types = load_item_types(gamedata.game_disk("POOL1"))
    got = {}
    for char in dos_codec.read_party(_save_dir(), "A"):
        rec, _ = dos_codec.to_c64_record(char, item_types=types)
        got[char.name] = (rec.get("thac0"), rec.get("missile_attack_adjustment"))
    assert got == {"SILAS": (0x2F, 3), "ASTRID": (0x2A, 3),
                   "GILES": (0x2A, 3), "ROLAND": (0x2A, 1),
                   "MAGNUS": (0x2F, 3), "BRUTUS": (0x2E, 3)}
