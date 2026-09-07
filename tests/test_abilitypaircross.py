from __future__ import annotations

"""A crossed DOS ability pair keeps its permanent and in-force halves apart
through the conversion, in both directions (#404).

`#401 (Which byte of a DOS ability pair is the current score, now that the
C64's two arrays are named)` read the DOS engine and confirmed in the running
game that `goldbox.dos._ability_pair` had the six ability scores inverted:
the record's lower byte is the *permanent* score and the higher one is what
is *in force*, and the exceptional-strength percentile runs the other way
round.  `docs/204-the-dos-ability-pair.md` has the full account.

**A round trip cannot see this bug**, because DOS to C64 and back crosses the
pair twice and comes home byte for byte -- see `tests/test_doswriter.py`'s own
note.  What proves the fix is a specimen whose two halves *disagree*, read one
way and then the other:

* `~/wish-specimens/coab-dos/WISH-SPEC-curse-401-crossed-ability-pairs` -- DOS
  Curse's own `ENCAMP > SAVE`, six characters, one ability pair apart on each
  (strength, wisdom or exceptional strength), read in `#401`'s own DOSBox run
  and confirmed against the sheet.
* `~/wish-specimens/coab-c64/WISH-SPEC-curse-367-crossed-abilities-resave.D64`
  -- the C64 counterpart from `#367`, six characters, one ability apart on
  each (strength, intelligence or constitution), the engine's own
  `SAVE CURRENT GAME` after training two of them.

Both are read-only specimens under `$WISH_SPECIMENS`; these tests skip
cleanly without them.
"""

import pathlib
import sys

import gamedata
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from goldbox import c64_codec, c64_save, dos, games, neutral  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.record import CharacterRecord  # noqa: E402

CURSE_GAME = games.CURSE_OF_THE_AZURE_BONDS
CONTAINER = c64_save.CURSE_OF_THE_AZURE_BONDS


def _dos_crossed_specimen():
    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    where = (root / "coab-dos" /
             "WISH-SPEC-curse-401-crossed-ability-pairs")
    if not where.is_dir():
        pytest.skip(f"needs {where}")
    return where


def _c64_crossed_specimen():
    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    where = (root / "coab-c64" /
             "WISH-SPEC-curse-367-crossed-abilities-resave.D64")
    if not where.is_file():
        pytest.skip(f"needs {where}")
    return where


#: name -> (dos file, permanent, in force), read out of the six 422-byte
#: records and matching `provenance.toml`'s own account of the specimen.
DOS_CROSSED = {
    "MATHEW": ("CHRDATE1.SAV", "exceptional_strength", 100, 0),
    "MARK": ("CHRDATE2.SAV", "exceptional_strength", 0, 100),
    "TRAVIS": ("CHRDATE3.SAV", "wisdom", 15, 7),
    "LEDERA": ("CHRDATE4.SAV", "wisdom", 7, 15),
    "SHARA": ("CHRDATE5.SAV", "strength", 9, 17),
    "PHILIPPE": ("CHRDATE6.SAV", "strength", 18, 9),
}

#: The C64 byte the permanent and in-force half of each ability lands on.
C64_IN_FORCE_OFFSET = dict(zip(neutral.ABILITIES, range(0x014, 0x01B)))
C64_PERMANENT_OFFSET = dict(zip(neutral.ABILITIES, range(0x065, 0x06C)))


# --- DOS -> neutral -----------------------------------------------------

@pytest.mark.parametrize("who", sorted(DOS_CROSSED))
def test_dos_to_neutral_separates_permanent_from_in_force(who):
    """Six characters, one crossed pair apiece: the neutral ability is
    always what the sheet drew (the score in force), never the rolled
    (permanent) one.

    `docs/204-the-dos-ability-pair.md`'s table names which DOS specimen
    proves which ability; `SHARA`, `PHILIPPE`, `TRAVIS` and `LEDERA` prove
    the six-score direction and `MATHEW`/`MARK` prove exceptional strength
    runs the other way.
    """
    where = _dos_crossed_specimen()
    filename, ability, permanent, in_force = DOS_CROSSED[who]
    dos_char = dos.read_character(where / filename)
    assert dos_char.name == who
    neutral_char = dos.to_neutral(dos_char)
    assert neutral_char.get(ability) == in_force, \
        f"{who}'s {ability} in force"
    assert neutral_char.get("abilities_second")[ability] == permanent, \
        f"{who}'s permanent {ability}"


# --- DOS -> C64, through the whole converter -----------------------------

@pytest.mark.parametrize("who", sorted(DOS_CROSSED))
def test_dos_to_c64_lands_each_half_on_the_byte_the_docs_table_names(who):
    """The same six characters, converted whole through `dos.convert_save`
    into a C64 `SAVEDGAME0` payload: the score in force at `0x014`-`0x01A`,
    the permanent score at `0x065`-`0x06B`, per character slot.

    This is the player-visible path (`#404`): a Girdle of Giant Strength's
    boost, or a shadow's drain, has to still be the *in-force* half and not
    the permanent one once the save is on the other port.
    """
    where = _dos_crossed_specimen()
    filename, ability, permanent, in_force = DOS_CROSSED[who]
    save0 = bytearray(CONTAINER.payload_size)
    dos.convert_save(where, "E", save0, game=CURSE_GAME)
    # `write_c64_save` does not keep the DOS file order -- read each C64
    # slot's own name rather than assume one, the C64 slot for `MATHEW`
    # (`CHRDATE1.SAV`) turned out to be the DOS file order reversed.
    record = next(
        save0[CONTAINER.slot(i):CONTAINER.slot(i) + 0x100]
        for i in range(6)
        if save0[CONTAINER.slot(i):CONTAINER.slot(i) + 16]
               .split(b"\0")[0].decode("ascii") == who)
    assert record[C64_IN_FORCE_OFFSET[ability]] == in_force, \
        f"{who}'s {ability} in force on the C64"
    assert record[C64_PERMANENT_OFFSET[ability]] == permanent, \
        f"{who}'s permanent {ability} on the C64"


# --- C64 -> DOS -----------------------------------------------------------

#: name -> slot index (file order in the D64's directory is the party order;
#: `provenance.toml` names the crossing), ability, permanent, in force --
#: read straight off `WISH-SPEC-curse-367-crossed-abilities-resave.D64`'s own
#: provenance, where `0x014` is always what the engine's own sheet and
#: weight-allowance recompute agreed was current.
C64_CROSSED = {
    "PHILIPPE": ("strength", 18, 9),
    "SHARA": ("strength", 9, 18),
    "LEDERA": ("intelligence", 16, 7),
    "TRAVIS": ("intelligence", 7, 16),
    "MARK": ("constitution", 17, 8),
    "MATHEW": ("constitution", 8, 17),
}


def _c64_party():
    """Every character in the crossed C64 save, as neutral records, keyed by
    name."""
    from goldbox.d64 import split_load_address

    path = _c64_crossed_specimen()
    payload = split_load_address(D64.open(path).read_file("SAVEAZURE"))[1]
    out = {}
    for slot in range(6):
        raw = payload[CONTAINER.slot(slot):CONTAINER.slot(slot) + 0x100]
        rec = CharacterRecord(bytes(raw) + bytes(580 - len(raw)),
                              stored_size=0x100)
        n = c64_codec.read(rec, game=CURSE_GAME)
        out[str(n.get("name")).strip()] = n
    return out


@pytest.mark.parametrize("who", sorted(C64_CROSSED))
def test_c64_to_dos_writes_the_permanent_byte_first(who):
    """The mirror image: a C64 record whose two arrays disagree writes DOS's
    lower byte from the permanent array (`0x065`) and the higher byte from
    the score in force (`0x014`), for the six scores.

    `#401` measured no C64 exceptional-strength crossing, so this direction
    is proven on the three abilities `#367` staged: strength, intelligence
    and constitution.
    """
    party = _c64_party()
    ability, permanent, in_force = C64_CROSSED[who]
    neutral_char = party[who]
    assert neutral_char.get(ability) == in_force, \
        f"{who}'s {ability} read off the C64 as in force"
    rec, _, _, _ = dos.write(neutral_char, shape=dos.CURSE_OF_THE_AZURE_BONDS)
    f = dos.FIELDS_BY_NAME_FOR[dos.CURSE_OF_THE_AZURE_BONDS.key][ability]
    assert rec[f.offset] == permanent, f"{who}'s permanent {ability} in DOS"
    assert rec[f.offset + 1] == in_force, f"{who}'s {ability} in force in DOS"


# --- the control: an agreeing pair is unaffected -------------------------

def test_a_character_whose_halves_agree_converts_exactly_as_before():
    """The overwhelming case -- every specimen this project can reach but
    the two staged above -- where both bytes of every pair hold the same
    number, so the fix must not move anything for it.
    """
    from goldbox.dos_layout import CURSE_OF_THE_AZURE_BONDS as CURSE_SHAPE
    from goldbox.dos_layout import FIELDS_BY_NAME_FOR

    rec = bytearray(CURSE_SHAPE.record_size)
    rec[0] = 5
    rec[1:6] = b"AGREE"
    table = FIELDS_BY_NAME_FOR[CURSE_SHAPE.key]
    for ability, value in (("strength", 17), ("intelligence", 12),
                           ("wisdom", 9), ("dexterity", 14),
                           ("constitution", 15), ("charisma", 10),
                           ("exceptional_strength", 0)):
        f = table[ability]
        rec[f.offset], rec[f.offset + 1] = value, value
    dos_char = dos.DosCharacter(bytes(rec), shape=CURSE_SHAPE)
    neutral_char = dos.to_neutral(dos_char)
    for ability, value in (("strength", 17), ("intelligence", 12),
                           ("wisdom", 9), ("dexterity", 14),
                           ("constitution", 15), ("charisma", 10),
                           ("exceptional_strength", 0)):
        assert neutral_char.get(ability) == value, ability
        assert neutral_char.get("abilities_second")[ability] == value, ability
    written, _, _, _ = dos.write(neutral_char, shape=CURSE_SHAPE)
    for ability, value in (("strength", 17), ("intelligence", 12),
                           ("wisdom", 9), ("dexterity", 14),
                           ("constitution", 15), ("charisma", 10),
                           ("exceptional_strength", 0)):
        f = table[ability]
        assert written[f.offset:f.offset + 2] == bytes((value, value)), \
            ability
