"""The rule a DOS Gold Box engine uses to decide a dual-classed human has got
his old class back, and what the record holds when he has (`#408`).

`docs/209-the-regained-dual-class-on-dos.md` has the reading.  Three kinds of
test here, and only the first needs nothing:

* the rule itself, against a stub -- **the strictness of the `<` is the whole
  of it**, because a record sitting exactly on the threshold is the one the
  engine does *not* count as regained, and a `<=` would name a class the
  character has not got back;
* the family scan over the player's own overlays, which skips without them;
* the engine-written specimen `WISH-SPEC-curse-408-regained-paladin`, made by
  `tools/curseregain.py` under DOSBox, which skips without the tree.

Nothing here reads a byte this project wrote.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from goldbox import dos_codec  # noqa: E402
from tests import gamedata  # noqa: E402
from tools import dosbox, dualclassdos, dualclassregain  # noqa: E402


class _Stub:
    """The three things `regained` asks of a record, and nothing else."""

    def __init__(self, level, current, former):
        self._level = level
        self._arrays = {"class_levels": bytes(current),
                        "former_class_levels": bytes(former)}
        self.fields = dict.fromkeys(self._arrays)

    def raw(self, name):
        return self._arrays[name]

    def get(self, name):
        assert name == "level"
        return self._level


# --------------------------------------------------------------------------
# The rule
# --------------------------------------------------------------------------


def test_the_old_class_is_not_back_while_the_new_one_is_below_it():
    """A magic-user 1 with a paladin 5 behind him is still just a magic-user.

    This is every dual-classed DOS record in the corpus but one: the state one
    action after `HUMAN CHANGE CLASSES`.
    """
    char = _Stub(level=1, current=[0, 0, 0, 0, 0, 1, 0, 0],
                 former=[0, 0, 0, 5, 0, 0, 0, 0])
    assert dualclassregain.regained(char) == {}
    assert dualclassregain.predict_bits(char) == 0x01


def test_the_old_class_is_back_once_the_new_one_passes_it():
    char = _Stub(level=6, current=[0, 0, 0, 0, 0, 6, 0, 0],
                 former=[0, 0, 0, 5, 0, 0, 0, 0])
    assert dualclassregain.regained(char) == {3: 5}
    assert dualclassregain.predict_bits(char) == 0x41


def test_level_equal_to_the_former_level_is_not_a_regain():
    """`0x3B15B` is `cmp al, es:[di+0xE5] / jge skip`, so equal skips.

    Treasures of the Savage Frontier's OUGO is exactly this record -- a cleric
    8 whose former array holds 8 at the fighter's slot -- and his stored
    `class_bits` is `$02`, the cleric alone.  A rule written with `<=` gives
    `$0A` and contradicts the byte on the disk.
    """
    char = _Stub(level=8, current=[8, 0, 0, 0, 0, 0, 0, 0],
                 former=[0, 0, 8, 0, 0, 0, 0, 0])
    assert dualclassregain.regained(char) == {}
    assert dualclassregain.predict_bits(char) == 0x02


def test_a_character_who_never_dual_classed_is_his_own_classes():
    char = _Stub(level=5, current=[0, 0, 4, 0, 0, 0, 5, 0],
                 former=[0] * 8)
    assert dualclassregain.regained(char) == {}
    assert dualclassregain.predict_bits(char) == 0x0C


# --------------------------------------------------------------------------
# The family scan
# --------------------------------------------------------------------------


def _overlay(stem: str):
    if not dosbox.ARCHIVES.is_dir():
        pytest.skip("no DOS archives on this machine; set $FR_ARCHIVES")
    path = dualclassdos.find_overlay(stem)
    if path is None:
        pytest.skip(f"no {stem}/GAME.OVR on this machine")
    return path.read_bytes()


@pytest.mark.parametrize("stem, shape_key, at", [
    ("CURSE", "curse-of-the-azure-bonds", 0x3B119),
    ("SECRET", "secret-of-the-silver-blades", 0x3C2B1),
    ("Pools of Darkness", "pools-of-darkness", 0x38484),
])
def test_exactly_one_site_per_title_rebuilds_the_mask_from_the_former_array(
        stem, shape_key, at):
    rows = dualclassregain.derive_sites(_overlay(stem), shape_key)
    hits = [r for r in rows if r["former"] and r["level"]]
    assert len(rows) > 1, "the overlay should clear class_bits more than once"
    assert [r["at"] for r in hits] == [at]


def test_pool_of_radiance_has_no_such_site_at_all():
    """The control: no former array, so nothing to consult.

    A scan that answered True here would be matching bytes rather than
    finding a routine.
    """
    rows = dualclassregain.derive_sites(_overlay("POOLRAD"), "pool-of-radiance")
    assert rows, "Pool of Radiance still rebuilds the mask somewhere"
    assert not any(r["former"] or r["level"] for r in rows)


# --------------------------------------------------------------------------
# The record the engine wrote
# --------------------------------------------------------------------------

SPECIMEN = "curse-408-regained-paladin"


def _dos_specimen(name: str):
    """The DOS specimen folder, in whichever `*-dos` container it landed in.

    `tools/specimens.py` files a specimen under a directory named for its
    *title*, so a Curse of the Azure Bonds one is `coab-dos/` and only Pool of
    Radiance's are under `por-dos/`; `tests.gamedata.have_specimen` assumes
    the latter and cannot see this one.  Globbing is what
    `tests/test_convertmatrix.py` does for the same reason.
    """
    root = gamedata.specimen_root()
    if root is None:
        return None
    found = list(root.glob(f"*-dos/WISH-SPEC-{name}"))
    return found[0] if found else None


def _specimen():
    where = _dos_specimen(SPECIMEN)
    if where is None:
        pytest.skip(f"needs $WISH_SPECIMENS/*-dos/WISH-SPEC-{SPECIMEN}; "
                    f"see tools/specimens.py")
    return where


def test_the_engine_leaves_the_old_class_slot_at_zero():
    """MATHEW, trained past the paladin 5 he changed out of, in DOSBox.

    Both fields went into the run holding the answer that would refute this,
    so a pass is the engine's doing and not the staging's.
    """
    char = dos_codec.read_character(_specimen() / "CHRDATJ1.SAV")
    assert char.name.strip() == "MATHEW"
    assert list(char.raw("class_levels")) == [0, 0, 0, 0, 0, 6, 0, 0]
    assert list(char.raw("former_class_levels")) == [0, 0, 0, 5, 0, 0, 0, 0]
    assert char.get("level") == 6
    assert char.get("former_level") == 5
    assert char.get("class_bits") == 0x41
    assert char.get("char_class") == 5, "the class he changed into, alone"
    assert char.get("thac0_base") == 44, "the paladin 5 row, not magic-user 6"


def test_the_single_classed_control_from_the_same_boot():
    """PHILIPPE, staged to the same level and experience, trained beside him.

    Same party, same press, same numbers going in; the only difference is the
    former array, so `thac0_base` 41 against MATHEW's 44 is the regain and
    nothing else.
    """
    char = dos_codec.read_character(_specimen() / "CHRDATJ6.SAV")
    assert char.name.strip() == "PHILIPPE"
    assert list(char.raw("class_levels")) == [0, 0, 0, 0, 0, 6, 0, 0]
    assert not any(char.raw("former_class_levels"))
    assert char.get("class_bits") == 0x01
    assert char.get("thac0_base") == 41


def test_every_record_in_the_specimen_reproduces_from_the_rule():
    folder = _specimen()
    seen = 0
    for path in sorted(folder.glob("CHRDAT*.SAV")):
        char = dos_codec.read_character(path)
        assert char.get("class_bits") == dualclassregain.predict_bits(char), \
            f"{path.name} does not reproduce"
        seen += 1
    assert seen == 6, "the whole party, not a record of it"
