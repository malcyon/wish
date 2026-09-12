"""The class code byte, shared between the two codecs that need it (#310).

Every Gold Box character record says its class twice: a bitmask and a single
code.  `docs/187-the-class-code-byte.md` has the full reading; this module
holds the part both `goldbox/c64_codec.py` and `goldbox/dos_codec.py` need alike --
the per-title table a class bitmask's code comes from, and the rule that says
what the code *should* be from a record's own classes.

`goldbox/c64_codec.py` cannot import `goldbox/dos_codec.py` and `goldbox/dos_codec.py`
imports `goldbox/c64_codec.py` -- neither may import the other, `goldbox/dos_codec.py`
says so beside `WRITES` -- so this table lives in the middle, where both
codecs can reach it.  `goldbox.dos_codec.CLASS_CODE_TABLE` and
`goldbox.dos_codec.CLASS_CODE_FOR_BITS` re-export the two tables below, and
`goldbox.yaml_io.CLASS_CODES` re-exports :data:`POOL_OF_RADIANCE_CLASS_CODES`,
so nothing that already imports them by name has to change.
"""

from __future__ import annotations

from . import titles

__all__ = [
    "CLASS_CODE_TABLE",
    "CLASS_CODE_FOR_BITS",
    "POOL_OF_RADIANCE_CLASS_CODES",
    "CLASS_BIT_FOR_NAME",
    "table_for",
    "code_for",
    "repair",
]

#: Curse of the Azure Bonds' own class table, `GEN $1951`: seventeen bytes
#: indexed by the class code and holding the bitmask that code stands for.
#: 0 cleric, 1 druid, 2 fighter, 3 paladin, 4 ranger, 5 magic-user, 6 thief,
#: 7 monk, and 8 upward for the multi-class combinations, which is the
#: standard Gold Box order every title's front end lists its classes in.
#: The druid's entry and the monk's are 0 because no Gold Box record carries
#: either class.
#:
#: **It is the C64's bit order**, the one the neutral record uses.  And it is
#: **Curse's own** table: index 10 is `0x82`, cleric and ranger, where Pool
#: of Radiance -- which has neither a paladin nor a ranger -- carries
#: cleric/magic-user there, in :data:`POOL_OF_RADIANCE_CLASS_CODES`.  The two
#: agree on every combination either title can actually make, and Secret of
#: the Silver Blades uses this table too: its own `GEN` never writes the byte
#: at all, so there is no table of its own to read.
#: `docs/187-the-class-code-byte.md` has the reading.
CLASS_CODE_TABLE: tuple[int, ...] = (
    0x02, 0x00, 0x08, 0x40, 0x80, 0x01, 0x04, 0x00,
    0x0A, 0x0B, 0x82, 0x03, 0x06, 0x09, 0x0C, 0x0D, 0x05)

#: Bitmask -> class code, from the table above, first occurrence winning so
#: the two zero entries do not claim the empty mask.
CLASS_CODE_FOR_BITS: dict[int, int] = {
    bits: code for code, bits in reversed(list(enumerate(CLASS_CODE_TABLE)))
    if bits}

#: Pool of Radiance's own table, from the game's 1989 BASIC editor, which
#: agrees with all four multi-class codes derived from the bitmask.  Moved
#: here from `goldbox/yaml_io.py`'s `CLASS_CODES`, which re-exports it.
POOL_OF_RADIANCE_CLASS_CODES: dict[int, int] = {
    2: 0,            # cleric
    8: 2,            # fighter
    1: 5,            # magic-user
    4: 6,            # thief
    2 | 8: 8,        # cleric/fighter
    1 | 2 | 8: 9,    # cleric/fighter/magic-user
    1 | 2: 11,       # cleric/magic-user
    2 | 4: 12,       # cleric/thief
    1 | 8: 13,       # fighter/magic-user
    4 | 8: 14,       # fighter/thief
    1 | 4 | 8: 15,   # fighter/magic-user/thief
    1 | 4: 16,       # magic-user/thief
}

#: Title key -> the table its own C64 engine (or, for Pool of Radiance, its
#: creation-era BASIC editor) uses.  A title with no row here gets Curse's,
#: which is what every measured title but Pool of Radiance agrees with.
_TABLES: dict[str, dict[int, int]] = {
    "pool-of-radiance": POOL_OF_RADIANCE_CLASS_CODES,
}


def table_for(game: object) -> dict[int, int]:
    """The bitmask -> code table for one title's own engine.

    `game` is whatever a caller has in hand for the title -- a
    `goldbox.c64_port.C64Container`, its `.key`, or `None` -- the same three shapes
    `goldbox.c64_codec.record_shape` accepts.
    """
    key = getattr(game, "key", game)
    return _TABLES.get(key, CLASS_CODE_FOR_BITS)


#: Class name -> its bit in the shared order, from `goldbox/titles.py`'s own
#: per-title lists so the two cannot drift apart.  Krynn's is the widest,
#: adding the Knight of Solamnia at `0x10`; every other title's is a subset.
CLASS_BIT_FOR_NAME: dict[str, int] = {
    name: bit for bit, name in titles.CLASS_BITS_KRYNN}


def code_for(bits: int, levels: "dict[str, int] | None" = None,
             former_levels: "dict[str, int] | None" = None,
             game: object = None) -> "int | None":
    """The class code a record's own classes name, or `None`.

    **The mask decides it, except for a dual-classed character, who takes
    the level array instead** (#310).  A dual-classed character's mask
    carries the old class's bit back once his new class passes the level he
    left the old one at, so the mask names two classes where the code names
    the one he *is*.  **On DOS his level array holds exactly the class he is
    now**, because the old class's slot is zeroed at the change and stays
    zero.  **On the C64 it does not**: once he trains past the level he left
    the old class at, the old slot fills again -- PHILIPPE, a magic-user 6 who
    changed to fighter and trained to fighter 8, holds magic-user 6 *and*
    fighter 8, with a mask naming both (`docs/208-the-class-combo-and-the-
    conversion.md`, `#393 (A dual-classed Curse character may show one class
    in the editor and convert as another, and no specimen exists to tell)`).
    That is why the two must be read together rather than either alone.
    `GEN $1939` agrees -- it branches away from the mask walk entirely when
    `dual_class_level` is set.

    Everybody else is read off the mask.  SILAS, the shipped Pool of
    Radiance fighter, carries a thief 1 in his level array that neither his
    mask nor his code has ever heard of; reading the levels there would make
    him a fighter/thief, which is this conversion inventing a class for a
    character the game calls a fighter.

    `None` when there is nothing to decide with, or when the classes are a
    combination the title's own table has no code for -- three exist, and
    `goldbox.yaml_io.class_code_for` refuses those for the same reason: a
    code that is not in the table means a different class.
    """
    table = table_for(game)
    former = former_levels or {}
    if any(former.values()):
        derived = 0
        for name, level in (levels or {}).items():
            if level:
                derived |= CLASS_BIT_FOR_NAME.get(name, 0)
        return table.get(derived)
    return table.get(int(bits or 0))


def repair(code: int, bits: int, levels: "dict[str, int] | None" = None,
           former_levels: "dict[str, int] | None" = None,
           game: object = None) -> "int | None":
    """The code that should replace `code`, or `None` when it should not move.

    `None` both when the classes name no code at all -- nothing to repair
    with -- and when the wanted code already agrees with `code`, which is
    228 of 228 DOS records and 48 of 48 C64 Pool of Radiance and Silver
    Blades ones measured (`docs/187-the-class-code-byte.md`).  The one title
    this ever fires on is Curse of the Azure Bonds: its own trainer stores
    the wrong CPU register at `GEN $1939` and leaves `char_class` reading 0,
    or, for a dual-classed character, the level he left his old class at.
    """
    want = code_for(bits, levels, former_levels, game)
    if want is None or want == int(code):
        return None
    return want
