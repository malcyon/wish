from __future__ import annotations

"""Turning undead: the byte the C64 keeps, and the one DOS never keeps.

`#288 (A converted cleric or paladin arrives on the C64 unable to turn undead,
because DOS keeps no turning byte and nothing computes one)`. What a player
saw: convert a party to the C64, walk a cleric into a fight, and the combat
bar reads `MOVE VIEW AIM USE CAST QUICK DONE` -- **the word TURN is not on
it**. `COMBAT $09D9` is `LDA $6BA4 / BNE`, and the branch not taken loads
`#$DF` into the mask that builds the bar, which is the bit belonging to the
sixth word of the eight at `$1344`. That word is `TURN`.

Two halves, and only the first needs the player's disks:

* the **gate** and the **table** are read off the game's own overlays, so the
  disk gets to contradict the claim rather than a transcription of it;
* the **conversion** is checked on records built from `goldbox/dos_layout.py`
  and `goldbox/neutral.py`'s own tables, so it runs anywhere.

Nothing here is a fixture sliced out of a game file: `AGENTS.md` forbids that,
and every disk-backed test skips when the disks are absent.

`tools/turncensus.py` is the census these tests rest on -- 210 C64 records on
this machine, 187 of them agreeing with the derivation and every one of the 23
that do not being a save this converter itself wrote.
"""

import pytest

from goldbox import c64_codec, derive, dos, dos_layout, games, levels, neutral
from goldbox.d64 import D64
from goldbox.layout import Confidence
from goldbox.savegame import load_save
from tests import gamedata

POOL = games.POOL_OF_RADIANCE
CURSE = games.CURSE_OF_THE_AZURE_BONDS
SSB = games.SECRET_OF_THE_SILVER_BLADES

#: `MOVE VIEW AIM USE CAST TURN QUICK DONE` -- the count byte at the head of
#: the table says eight, and TURN is the sixth, so its mask bit is 5 and the
#: byte that clears it is `$DF`.
TURN_BIT = 5
TURN_MASK = 0xDF


def _overlay(game, name: bytes) -> bytes:
    """One title's overlay payload at the address it runs at, or skip."""
    from tests.test_coldread import _root
    from tools import coldread
    return coldread.overlay(game, name, _root(game))


def _at(body: bytes, address: int, count: int) -> bytes:
    """`count` bytes of an overlay that runs at `$0800`, by run-time address."""
    from tools import coldread
    return bytes(coldread.table(body, coldread.GEN_BASE, address, count))


def _c64_specimen(name: str):
    """A single-file C64 specimen, checked against its own hash, or skip.

    `tests/gamedata.py:specimen` wants a directory and the C64 half of the
    tree is one `.D64` beside one `.provenance.toml`, which nothing had needed
    from a test before. A file that no longer hashes to what its provenance
    recorded **fails** rather than skips: at that point it is somebody's edit
    rather than evidence (`.claude/rules/testing.md`).
    """
    from tools import specimens

    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    found = [p for p in (root / "por-c64").glob(f"WISH-SPEC-{name}.[dD]64")]
    if not found:
        pytest.skip(f"needs specimen WISH-SPEC-{name}")
    path = found[0]
    prov = path.with_suffix(".provenance.toml")
    recorded = specimens.read_provenance(prov).get("sha256", {})
    actual = specimens.sha256_file(path)
    if recorded.get(path.name) not in (None, actual):
        pytest.fail(f"WISH-SPEC-{name}: {path.name} has changed since it was "
                    f"recorded; run tools/specimens.py check")
    return path


# --- the gate: what a player does not see ------------------------------------

def test_the_c64_combat_bar_drops_turn_when_the_turning_byte_is_zero():
    """`COMBAT $09CF` builds the combat bar's mask, and this is the test on it.

        $09CF  LDA #$FF / STA $48F8      every command allowed
        $09D9  LDA $6BA4                 turn_power
        $09DC  BNE $09E3                 non-zero: leave TURN alone
        $09DE  LDA #$DF / JSR $133D      zero: clear bit 5

    `$133D` is `AND $48F8 / STA $48F8`, and `$0A24` hands that mask to the bar
    builder with the word table at `$1344`, whose count byte is 8 and whose
    sixth word is `TURN`. So a cleric holding zero is not offered the command
    at all, which is what a converted cleric held.
    """
    combat = _overlay(POOL, b"COMBAT")
    assert _at(combat, 0x09CF, 5) == b"\xA9\xFF\x8D\xF8\x48"      # mask = $FF
    assert _at(combat, 0x09D9, 7) == b"\xAD\xA4\x6B\xD0\x05\xA9\xDF"
    assert _at(combat, 0x133D, 7) == b"\x2D\xF8\x48\x8D\xF8\x48\x60"
    assert _at(combat, 0x0A24, 8) == b"\xAD\xF8\x48\xA2\x44\xA0\x13\x20"

    assert _at(combat, 0x1344, 2) == b"\x08\x00"      # eight commands on it
    table = _at(combat, 0x1346, 40).split(b"\x00")
    assert table[TURN_BIT] == b"TURN"
    assert TURN_MASK == 0xFF & ~(1 << TURN_BIT)


def test_curse_and_silver_blades_gate_the_same_command_the_same_way():
    """The same shape in both later titles, in `ECL64` rather than `COMBAT`.

    Curse: `LDA $7CA4 / BEQ +8`, and the fall-through is `LDA #$DF`. Silver
    Blades: `LDA $7CA4 / BEQ +5`, same `#$DF`. Each has one extra condition of
    its own past the byte -- Curse a table read at `$95E8,X` and Silver Blades
    a byte at `$7D1D` -- and neither can reach the command with a zero here.

    Curse's own eight-word table sits in the same file and reads `TURN` at
    index 5. Silver Blades keeps its words in `COMBAT2` instead, which
    `ECL64` names by pointer (`LDX #$A8 / LDY #$F8`, `$F8A8`); that file's
    table is the same eight words, so the bit is the same bit.
    """
    curse = _overlay(CURSE, b"ECL64")
    assert _at(curse, 0x1848, 6) == b"\xAD\xA4\x7C\xF0\x08\xAE"
    assert _at(curse, 0x1855, 2) == b"\xA9\xDF"
    assert _at(curse, 0x18A6, 2) == b"\x08\x00"       # eight commands
    assert _at(curse, 0x18A8, 40).split(b"\x00")[TURN_BIT] == b"TURN"

    ssb = _overlay(SSB, b"ECL64")
    assert _at(ssb, 0x1840, 5) == b"\xAD\xA4\x7C\xF0\x05"
    assert _at(ssb, 0x184A, 2) == b"\xA9\xDF"
    combat2 = _overlay(SSB, b"COMBAT2")
    head = combat2.index(b"\x08\x00MOVE\x00VIEW")
    assert combat2[head + 2:head + 42].split(b"\x00")[TURN_BIT] == b"TURN"


# --- the table: where the number comes from ----------------------------------

def _ssb_turn_power(cleric: int, paladin: int) -> int:
    """`GEN $13A5`, which is Curse's `$113F` with one branch more."""
    best = max(int(cleric), max(0, int(paladin) - 2))
    if best == 0 or best < 4:
        return best
    value = best + 1
    if value < 10:
        return value
    return 10 if value < 15 else 12


def test_silver_blades_computes_its_turning_level_at_gen_13a5():
    """The routine, and `goldbox/levels.py`'s expansion of it.

        $13A5  LDA $7CCF / SEC / SBC #$02      the paladin, two levels back
        $13AB  BCS +2 / LDA #$00               never below zero
        $13AF  CMP $7CCA / BCS +3 / LDA $7CCA  the better of that and cleric
        $13B7  BEQ store                       turns nothing: store zero
        $13B9  CMP #$04 / BCC store            1, 2 and 3 as they stand
        $13BD  ADC #$00                        + 1 from 4 up
        $13BF  CMP #$0A / BCC store
        $13C3  CMP #$0F / BCC $13CB            10 up to 14
        $13C7  LDA #$0C                        12 from 15
        $13CD  STA $7CA4

    Over a cleric's whole range that is `1 2 3 5 6 7 8 9 10 10 10 10 10 12` --
    Pool of Radiance's `$2399` table entry for entry, reached a third way.
    """
    gen = _overlay(SSB, b"GEN")
    assert _at(gen, 0x13A5, 6) == b"\xAD\xCF\x7C\x38\xE9\x02"
    assert _at(gen, 0x13AF, 6) == b"\xCD\xCA\x7C\xB0\x03\xAD"
    assert _at(gen, 0x13B7, 6) == b"\xF0\x14\xC9\x04\x90\x10"
    assert _at(gen, 0x13BD, 8) == b"\x69\x00\xC9\x0A\x90\x0A\xC9\x0F"
    assert _at(gen, 0x13C7, 2) == b"\xA9\x0C"
    assert _at(gen, 0x13CD, 3) == b"\x8D\xA4\x7C"           # STA turn_power

    tables = levels.SECRET_OF_THE_SILVER_BLADES
    for cleric in range(0, tables.ceiling("cleric") + 1):
        for paladin in range(0, tables.ceiling("paladin") + 1):
            assert tables.turning_level(cleric, paladin) == \
                _ssb_turn_power(cleric, paladin), (cleric, paladin)
    assert tables.turn_power == levels.POOL_OF_RADIANCE.turn_power


def test_the_shipped_silver_blades_cleric_and_paladin_store_that_level():
    """`SAVEDBASH`, the party SSI ships: DOMINIC a cleric 8 and GUY DE VALOIS
    a paladin 8. Two records, and they are what makes the reading above a
    measurement rather than an expansion of code nobody has checked."""
    from tests.test_silverblades import _party

    sg0, _sg1 = _party()
    seen = {}
    for slot in sg0.slots:
        record = slot.record
        if record is None:
            continue
        want = _ssb_turn_power(record.get("level_cleric"),
                              record.get("level_paladin"))
        assert record.get("turn_power") == want, record.name
        if want:
            seen[str(record.name)] = want
    assert seen == {"DOMINIC": 9, "GUY DE VALOIS": 7}, seen


def test_the_curse_party_trained_in_its_own_hall_wrote_the_same_numbers():
    """Two engine-written values on a party this project **converted**.

    `WISH-SPEC-curse-trained-party` is the Curse party of
    `#18 (Measure Curse's trainer so Level Up works there)` after its own
    training hall levelled it. SHARA reached cleric 6 and the trainer wrote 7
    at `0x0A4`; MATHEW reached paladin 6 and it wrote 5. MARK, a paladin 5 the
    hall did not train, is still on the zero the conversion left him -- which
    is the bug, on the same disk as the proof.
    """
    disk = D64.open(str(_c64_specimen("curse-trained-party")))
    _game, sg0, _sg1 = load_save(disk)
    stored = {str(s.record.name): (s.record.get("level_cleric"),
                                   s.record.get("level_paladin"),
                                   s.record.get("turn_power"))
              for s in sg0.slots if s.record is not None}
    assert stored["SHARA"] == (6, 0, 7)
    assert stored["MATHEW"] == (0, 6, 5)
    assert stored["MARK"] == (0, 5, 0)          # not trained, still broken
    for name, (cleric, paladin, byte) in stored.items():
        if name != "MARK":
            assert derive.turn_power(CURSE, {"cleric": cleric,
                                             "paladin": paladin}) == byte, name


# --- the conversion: disk-free ----------------------------------------------

def _neutral(game, **class_levels) -> neutral.NeutralCharacter:
    """A neutral character with nothing but a name and some class levels."""
    char = neutral.NeutralCharacter("test", source="built here", game=game)
    char.set("name", "TURNER", "built here", Confidence.CONFIRMED,
             neutral.Provenance.RESHAPED)
    char.set("levels", dict(class_levels), "built here")
    char.set("class_bits", 2 if class_levels.get("cleric") else 1,
             "built here")
    return char


@pytest.mark.parametrize("game", [POOL, CURSE, SSB])
def test_a_converted_cleric_arrives_able_to_turn_undead(game):
    """The regression the ticket asks for: a cleric 8 must reach `0x0A4` as 9.

    Before the fix the writer copied whatever the source gave it, which for
    every DOS record is zero -- `goldbox/dos.py` reads DOS `0x076`, and that
    byte is the *undead's* row rather than the caster's, zero on every player
    character in either port.
    """
    rec, _rep = c64_codec.write(_neutral(game, cleric=8))
    assert rec.get("turn_power") == 9
    assert rec.get("turn_class") == 0      # the other half: nobody is undead


@pytest.mark.parametrize("game", [CURSE, SSB])
def test_a_converted_paladin_turns_as_a_cleric_two_levels_weaker(game):
    rec, _rep = c64_codec.write(_neutral(game, paladin=8))
    assert rec.get("turn_power") == 7
    low, _rep = c64_codec.write(_neutral(game, paladin=2))
    assert low.get("turn_power") == 0      # a paladin turns nothing until 3


@pytest.mark.parametrize("game", [POOL, CURSE, SSB])
def test_a_converted_magic_user_still_turns_nothing(game):
    """The control. Zero is a real answer here, and it is the byte the game
    itself stores for a character who turns nothing."""
    rec, _rep = c64_codec.write(_neutral(game, magic_user=9))
    assert rec.get("turn_power") == 0


def test_the_whole_of_pool_of_radiances_own_table_is_reachable():
    """Every entry of `$2399`, through the writer rather than the table."""
    got = [c64_codec.write(_neutral(POOL, cleric=n))[0].get("turn_power")
           for n in range(0, 15)]
    assert got == [0, 1, 2, 3, 5, 6, 7, 8, 9, 10, 10, 10, 10, 10, 12]


def test_the_conversion_says_it_computed_the_byte_rather_than_copying_it():
    """Every one of the 580 bytes has a provenance, and this one says
    `computed` rather than naming a source field it did not read."""
    _rec, rep = c64_codec.write(_neutral(POOL, cleric=3))
    line = rep.sources[0x0A4]
    assert "computed" in line and "cleric" in line
    assert rep.unaccounted == []


# --- end to end, from a DOS record ------------------------------------------

def _dos_record(shape, **values) -> bytes:
    """A `shape`'s own size of DOS record with the named fields set.

    Built from `goldbox/dos_layout.py`'s table, so it is ours and needs no
    disks. The same helper `tests/test_ssbconvert.py` uses, kept here rather
    than imported so this file stands on its own.
    """
    rec = bytearray(shape.record_size)
    table = dos_layout.FIELDS_BY_NAME_FOR[shape.key]
    for name, value in values.items():
        field = table[name]
        raw = bytes([value] * field.size) if isinstance(value, int) else value
        assert len(raw) == field.size, name
        rec[field.span] = raw
    return bytes(rec)


def _class_levels(size: int, **by_slot) -> bytes:
    out = bytearray(size)
    for slot, level in by_slot.items():
        out[int(slot)] = level
    return bytes(out)


def test_a_dos_cleric_converted_to_the_c64_can_turn_undead():
    """The whole path, `goldbox.dos.to_c64_record`, on a DOS Pool of Radiance
    record with cleric 8 in slot 0 of its own level array and **nothing** at
    `0x076`, which is what every DOS record holds there."""
    shape = dos_layout.POOL_OF_RADIANCE
    size = dos_layout.FIELDS_BY_NAME_FOR[shape.key]["class_levels"].size
    raw = _dos_record(shape, class_bits=0x02, char_class=0, level=8,
                      class_levels=_class_levels(size, **{"0": 8}))
    assert raw[0x076] == 0
    rec, _rep = dos.to_c64_record(dos.DosCharacter(raw))
    assert rec.get("level_cleric") == 8
    assert rec.get("turn_power") == 9
