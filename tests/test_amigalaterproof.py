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

from goldbox import amiga, dos_layout
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

@pytest.mark.parametrize("shape", amiga.AMIGA_SHAPES, ids=lambda s: s.key)
def test_every_unsourced_byte_the_writer_declares_is_in_the_mask(shape):
    """`LATER_WRITE_UNSOURCED` is the list of Amiga offsets no DOS field
    reaches, so a resave is entitled to differ there and the diff must not
    report one."""
    mask = proof.declared_record_mask(shape)
    for at, size, _why in amiga.LATER_WRITE_UNSOURCED[shape.key]:
        assert set(range(at, at + size)) <= mask, hex(at)


@pytest.mark.parametrize("shape", amiga.AMIGA_SHAPES, ids=lambda s: s.key)
def test_the_mask_is_the_declared_lists_and_not_everything(shape):
    """The half that matters: a field the writer claims to convert has to be
    outside the mask, or the diff proves nothing.  Hit points, armour class
    and the seven abilities are what a player reads off the sheet."""
    mask = proof.declared_record_mask(shape)
    table = dos_layout.FIELDS_BY_NAME_FOR[shape.dos.key]
    for name in ("hp_max", "armour_class", "strength", "intelligence",
                 "wisdom", "dexterity", "constitution", "charisma",
                 "race", "char_class", "class_levels"):
        field = table[name]
        at = shape.offset(field.offset)
        assert not (set(range(at, at + field.size)) & mask), name


@pytest.mark.parametrize("shape", amiga.AMIGA_SHAPES, ids=lambda s: s.key)
def test_the_live_heap_pointers_the_engine_fills_in_are_masked(shape):
    """`effect_chain` and `item_chain` come back as real Amiga addresses in
    the engine's own resave -- measured on both titles, 2026-09-07 -- and
    `goldbox.dos.WRITE_UNSOURCED` is where the writer says so."""
    mask = proof.declared_record_mask(shape)
    table = dos_layout.FIELDS_BY_NAME_FOR[shape.dos.key]
    for name in ("effect_chain", "item_chain"):
        field = table[name]
        at = shape.offset(field.offset)
        assert set(range(at, at + field.size)) <= mask, name


# ---------------------------------------------------------------------------
# Naming an offset, which is what makes a diff line readable
# ---------------------------------------------------------------------------

def test_an_offset_in_the_record_is_named_by_its_field():
    shape = amiga.SILVER_BLADES_SHAPE
    at = shape.offset(dos_layout.FIELDS_BY_NAME_FOR[shape.dos.key]["hp_max"]
                      .offset)
    assert proof.field_at(shape, at) == "hp_max+0"


def test_silver_blades_names_its_re_encoded_spellbook():
    """The one region with no DOS field behind it: 117 flag bytes packed into
    15 of mask, which `AmigaShape.offset` cannot map."""
    shape = amiga.SILVER_BLADES_SHAPE
    assert proof.field_at(shape, amiga.AMIGA_SSB_SPELLBOOK_AT + 3) \
        == "spellbook+3"
