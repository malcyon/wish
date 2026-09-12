"""`tools/amigalaterproof.py`: the run harness that put `write_later` in front
of the two later Amiga games.

The run itself is in `docs/203-a-converted-later-amiga-party-in-the-running-game.md`
and cannot be a test -- it needs a Windows VM, WinUAE and the player's own
disks.  What can be tested is the two things the harness decides on its own,
because both of them would spoil a run silently:

* **the ordering**, which is why this tool exists rather than
  `tools/amigalaterwrite.py --into`.  The writer's riskiest choice is a
  boolean chain head where `write_por` writes NULL, and a wrong head does not
  spoil one character -- the loader's file position desynchronises and every
  character *after* it is read out of the wrong bytes.  So the character
  carrying the items has to be put in front of the others, and the C64 saves
  this converts from keep theirs last;
* **the mask**, which has to be the lists the writers *declare* and never
  whatever happened to differ (`.claude/rules/conversions.md`).  A mask that
  quietly widened would turn a real regression into a clean run.
"""

from __future__ import annotations

import pytest
from gamedata import specimen_root

from goldbox import amiga_later, amiga_port, dos_port
from tools import amigalaterproof as proof

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


class _Stub:
    """Only `.name` is read by `reorder`, so only `.name` is here."""

    def __init__(self, name: str) -> None:
        self.name = name


def _party(*names: str) -> list:
    return [(None, _Stub(n), None) for n in names]


def _names(built: list) -> list[str]:
    return [c.name for _a, c, _b in built]


# ---------------------------------------------------------------------------
# The ordering
# ---------------------------------------------------------------------------

def test_the_named_character_goes_to_the_front_and_the_rest_keep_their_order():
    built = _party("MORGAINE", "DOMINIC", "MALACHITE", "Guy de Valois ")
    moved = proof.reorder(built, "Guy de Valois")
    assert _names(moved) == ["Guy de Valois ", "MORGAINE", "DOMINIC",
                             "MALACHITE"]


def test_the_name_is_matched_without_case_or_the_amiga_trailing_space():
    """An Amiga record's own copy of a name can carry a trailing space the
    C64's does not (`#308`), and a command line is typed in whatever case
    the person felt like."""
    built = _party("MORGAINE", "Guy de Valois ")
    assert _names(proof.reorder(built, "  guy DE valois  "))[0] \
        == "Guy de Valois "


def test_a_party_with_no_first_named_is_left_exactly_as_it_came():
    built = _party("MORGAINE", "DOMINIC")
    assert proof.reorder(built, None) is built


def test_a_name_nobody_in_the_party_has_is_refused_rather_than_ignored():
    """Silently converting the party in its original order would produce a
    disk that looks right and tests nothing: the character with the items
    would still be last, with nobody behind him to be corrupted."""
    built = _party("MORGAINE", "DOMINIC")
    with pytest.raises(SystemExit) as bad:
        proof.reorder(built, "GUY DE VALOIS")
    assert "MORGAINE" in str(bad.value)      # it names who is actually there


# ---------------------------------------------------------------------------
# The mask
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("shape", amiga_port.AMIGA_DELTAS, ids=lambda s: s.key)
def test_every_unsourced_byte_the_writer_declares_is_in_the_mask(shape):
    """`LATER_WRITE_UNSOURCED` is the list of Amiga offsets no DOS field
    reaches, so a resave is entitled to differ there and the diff must not
    report one."""
    mask = proof.declared_record_mask(shape)
    for at, size, _why in amiga_later.LATER_WRITE_UNSOURCED[shape.key]:
        assert set(range(at, at + size)) <= mask, hex(at)


@pytest.mark.parametrize("shape", amiga_port.AMIGA_DELTAS, ids=lambda s: s.key)
def test_the_mask_is_the_declared_lists_and_not_everything(shape):
    """The half that matters: a field the writer claims to convert has to be
    outside the mask, or the diff proves nothing.  Hit points, armour class
    and the seven abilities are what a player reads off the sheet."""
    mask = proof.declared_record_mask(shape)
    table = dos_port.FIELDS_BY_NAME_FOR[shape.dos.key]
    for name in ("hp_max", "armour_class", "strength", "intelligence",
                 "wisdom", "dexterity", "constitution", "charisma",
                 "race", "char_class", "class_levels"):
        field = table[name]
        at = shape.offset(field.offset)
        assert not (set(range(at, at + field.size)) & mask), name


@pytest.mark.parametrize("shape", amiga_port.AMIGA_DELTAS, ids=lambda s: s.key)
def test_the_live_heap_pointers_the_engine_fills_in_are_masked(shape):
    """`effect_chain` and `item_chain` come back as real Amiga addresses in
    the engine's own resave -- measured on both titles, 2026-09-07 -- and
    `goldbox.dos.WRITE_UNSOURCED` is where the writer says so."""
    mask = proof.declared_record_mask(shape)
    table = dos_port.FIELDS_BY_NAME_FOR[shape.dos.key]
    for name in ("effect_chain", "item_chain"):
        field = table[name]
        at = shape.offset(field.offset)
        assert set(range(at, at + field.size)) <= mask, name


def test_the_derived_bytes_the_engine_recomputes_are_masked():
    """`#402 (Amiga Curse recomputes thac0_current and a roster_tail byte on
    load, and no declared list says so)`: the two Curse offsets in
    `LATER_WRITE_DERIVED` are exactly `thac0_current` and the sixth byte of
    `roster_tail`, computed from the shift map rather than typed twice."""
    shape = amiga_port.CURSE_DELTAS
    table = dos_port.FIELDS_BY_NAME_FOR[shape.dos.key]
    want = {shape.offset(table["thac0_current"].offset),
            shape.offset(table["roster_tail"].offset) + 5}
    mask = proof.declared_record_mask(shape)
    assert want <= mask
    got = {at for at, _size, _why in amiga_later.LATER_WRITE_DERIVED[shape.key]}
    assert got == want


def test_silver_blades_has_no_derived_bytes_declared():
    """UNMEASURED, not confirmed absent (`#402`): Silver Blades' converted
    party happened to agree with the engine's resave, which proves nothing,
    so nothing is masked there yet."""
    assert amiga_later.LATER_WRITE_DERIVED[amiga_port.SILVER_BLADES_DELTAS.key] == ()


def test_the_curse_engine_resave_leaves_only_combat_figure_outside_the_lists():
    """The live-game evidence `#402` rests on: Amiga Curse loaded a party
    `write_later` converted and wrote it back through `ENCAMP > SAVE`, and
    before this fix `thac0_current`, one `roster_tail` byte and
    `combat_figure` were the only bytes outside the declared lists.
    `combat_figure` is the writer's own known gap; the other two are now on
    `LATER_WRITE_DERIVED`, so nothing but `combat_figure` should be left.

    `docs/203-a-converted-later-amiga-party-in-the-running-game.md`.
    """
    root = specimen_root()
    if root is None:
        pytest.skip("no $WISH_SPECIMENS; see tools/specimens.py")
    source = (root / "coab-c64" /
              "WISH-SPEC-curse-52-dialog-converted-resave.D64")
    theirs_path = (root / "coab-amiga" /
                   "WISH-SPEC-coab-amiga-converted-resave" / "savgamC.dat")
    if not source.is_file() or not theirs_path.is_file():
        pytest.skip("the #384/#402 specimens are not on this machine")

    amigalaterwrite = proof.amigalaterwrite
    built = amigalaterwrite.convert(amigalaterwrite.party_from(source))
    ours_by_name = {c.name.strip().upper(): c for _n, c, _r in built}

    theirs_data = theirs_path.read_bytes()
    theirs_by_name = {c.name.strip().upper(): c
                      for c in proof.party_of(theirs_data, str(theirs_path))}

    assert {"MATHEW", "PHILIPPE"} <= ours_by_name.keys()
    loose: set[str] = set()
    for name, mine in ours_by_name.items():
        twin = theirs_by_name.get(name)
        if twin is None:
            continue
        a, b = mine.block_bytes(), twin.block_bytes()
        mask = proof.declared_block_mask(mine)
        for at in range(min(len(a), len(b))):
            if a[at] != b[at] and at not in mask:
                loose.add(proof.field_at(mine.deltas, at))
    assert loose == {"combat_figure+0"}


# ---------------------------------------------------------------------------
# Naming an offset, which is what makes a diff line readable
# ---------------------------------------------------------------------------

def test_an_offset_in_the_record_is_named_by_its_field():
    shape = amiga_port.SILVER_BLADES_DELTAS
    at = shape.offset(dos_port.FIELDS_BY_NAME_FOR[shape.dos.key]["hp_max"]
                      .offset)
    assert proof.field_at(shape, at) == "hp_max+0"


def test_silver_blades_names_its_re_encoded_spellbook():
    """The one region with no DOS field behind it: 117 flag bytes packed into
    15 of mask, which `AmigaDeltas.offset` cannot map."""
    shape = amiga_port.SILVER_BLADES_DELTAS
    assert proof.field_at(shape, amiga_later.AMIGA_SSB_SPELLBOOK_AT + 3) \
        == "spellbook+3"
