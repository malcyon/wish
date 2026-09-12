from __future__ import annotations

"""Which byte of a DOS ability pair the engine treats as the score in force.

`#401 (Which byte of a DOS ability pair is the current score, now that the
C64's two arrays are named)`. From Curse of the Azure Bonds onward a DOS record
keeps every ability twice, side by side, and **every record this project can
reach holds the two bytes equal** -- 406 pairs across 58 Curse records -- so no
saved game can separate them and the answer had to come out of the engine.

It did, and it is not one answer for all seven pairs:

* for strength through charisma the **lower** address of each pair is the
  permanent score and the higher one is what is in force;
* for the exceptional-strength percentile it is the other way round, `0x01C`
  in force and `0x01D` permanent.

The tests below pin that to the shipped `GAME.OVR` of five DOS engines, with
Pool of Radiance -- which keeps one copy of each ability and can therefore have
none of the signatures -- as the negative control. They read the player's own
archives through `tools/dosbox.find_game` and skip cleanly without them; no
game bytes are in this repository, and the synthetic records the staging tests
use are built here out of zeroes.

The other half of the evidence is a run in DOSBox that cannot be asserted from
a test: six characters staged with one pair apart, four of four ability
crossings drawn from the higher byte on the sheet and two of two percentile
crossings from the lower one. It is on `#401` and in
`docs/204-the-dos-ability-pair.md`.
"""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from goldbox import dos_port  # noqa: E402
from tools import dosabilitypair as ap  # noqa: E402

#: Long enough for the 422-byte Curse shape, which is the smallest of the three
#: that keep pairs.
RECORD_SIZE = 422


def _record(name: str, **pairs: tuple[int, int]) -> bytes:
    """A synthetic record: a count byte, a name, and whichever pairs are given.

    Generated here rather than sliced out of a save, because a slice of a game
    file is the game's data under a new name (`AGENTS.md`).
    """
    data = bytearray(RECORD_SIZE)
    data[0] = len(name)
    data[1:1 + len(name)] = name.encode("ascii")
    for ability, (first, second) in pairs.items():
        off = ap.PAIRS[ability]
        data[off], data[off + 1] = first, second
    return bytes(data)


# --- the tool's offsets are the layout module's ------------------------------


def test_the_pair_offsets_are_the_ones_the_layout_declares():
    """A pair's lower address is where `goldbox/dos_layout.py` puts the field.

    The tool would otherwise be free to drift away from the module the rest of
    the project reads records with, and every claim in `docs/204` is stated as
    a record offset.
    """
    layout = {f.name: f for f in
              dos_port.layout_for(dos_port.CURSE_OF_THE_AZURE_BONDS)}
    declared = {"str": "strength", "int": "intelligence", "wis": "wisdom",
                "dex": "dexterity", "con": "constitution", "cha": "charisma",
                "exstr": "exceptional_strength"}
    for short, long in declared.items():
        assert layout[long].offset == ap.PAIRS[short], long
        assert layout[long].size == 2, long


@pytest.mark.parametrize("shape", [
    dos_port.CURSE_OF_THE_AZURE_BONDS,
    dos_port.SECRET_OF_THE_SILVER_BLADES,
    dos_port.POOLS_OF_DARKNESS])
def test_every_later_shape_puts_the_pairs_at_the_same_offsets(shape):
    """The three later record sizes differ everywhere after the abilities and
    nowhere before them, so one set of offsets answers for all three."""
    layout = {f.name: f for f in dos_port.layout_for(shape)}
    assert layout["strength"].offset == 0x010
    assert layout["exceptional_strength"].offset == 0x01C


def test_pool_of_radiance_keeps_one_byte_and_so_has_no_pairs():
    """The negative control for the whole finding."""
    layout = {f.name: f for f in
              dos_port.layout_for(dos_port.POOL_OF_RADIANCE)}
    assert layout["strength"].size == 1
    assert layout["exceptional_strength"].size == 1


# --- staging, which is how a pair is made to disagree ------------------------


def test_stage_writes_the_first_number_at_the_lower_address(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    (src / "CHRDATD1.SAV").write_bytes(_record("SHARA", str=(17, 17)))
    (src / "SAVGAMD.DAT").write_bytes(b"\0" * 16)
    out = tmp_path / "out"
    assert ap.main(["stage", "--save", str(src), "--out", str(out),
                    "--set", "SHARA:str=9/17"]) == 0
    got = (out / "CHRDATD1.SAV").read_bytes()
    assert (got[0x010], got[0x011]) == (9, 17)
    # The container is copied whole, so the staged save is a save.
    assert (out / "SAVGAMD.DAT").read_bytes() == b"\0" * 16


def test_stage_leaves_every_other_byte_where_it_was(tmp_path):
    """One thing differs, or the run is wasted."""
    src = tmp_path / "in"
    src.mkdir()
    before = _record("PHILIPPE", str=(18, 18), wis=(14, 14), exstr=(0, 0))
    (src / "CHRDATD6.SAV").write_bytes(before)
    out = tmp_path / "out"
    ap.main(["stage", "--save", str(src), "--out", str(out),
             "--set", "PHILIPPE:str=18/9"])
    after = (out / "CHRDATD6.SAV").read_bytes()
    assert [i for i in range(len(before)) if before[i] != after[i]] == [0x011]


def test_stage_takes_the_file_stem_as_well_as_the_name(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    (src / "CHRDATD3.SAV").write_bytes(_record("TRAVIS", wis=(15, 15)))
    out = tmp_path / "out"
    ap.main(["stage", "--save", str(src), "--out", str(out),
             "--set", "CHRDATD3:wis=15/7"])
    got = (out / "CHRDATD3.SAV").read_bytes()
    assert (got[0x014], got[0x015]) == (15, 7)


def test_stage_says_so_when_no_record_carries_the_name(tmp_path, capsys):
    src = tmp_path / "in"
    src.mkdir()
    (src / "CHRDATD1.SAV").write_bytes(_record("SHARA", str=(17, 17)))
    out = tmp_path / "out"
    assert ap.main(["stage", "--save", str(src), "--out", str(out),
                    "--set", "NOBODY:str=9/17"]) == 1
    assert "NOBODY" in capsys.readouterr().err


def test_read_prints_both_bytes_of_every_pair(tmp_path, capsys):
    path = tmp_path / "CHRDATE5.SAV"
    path.write_bytes(_record("SHARA", str=(9, 17), exstr=(100, 0)))
    ap.main(["read", str(path)])
    out = capsys.readouterr().out
    assert "SHARA" in out and "str=9/17" in out and "exstr=100/0" in out


# --- and against the engines themselves --------------------------------------


def _overlay(stem: str) -> bytes:
    try:
        path = ap.overlay(stem)
    except FileNotFoundError:
        pytest.skip(f"needs the DOS {stem} archive; set FR_ARCHIVES")
    if not path.is_file():
        pytest.skip(f"no GAME.OVR beside DOS {stem}")
    return path.read_bytes()


def _hits(data: bytes, name: str) -> int:
    import re
    pattern = next(p for n, p, _ in ap.SIGNATURES if n == name)
    return len(list(re.finditer(pattern, data, re.S)))


#: The five DOS engines of this family that keep ability pairs.
PAIRED = pytest.mark.parametrize("stem", [
    "CURSE", "SECRET", "DARKNESS", "GATEWAY", "TREASURE"])


@PAIRED
@pytest.mark.parametrize("signature", [n for n, _, _ in ap.SIGNATURES])
def test_every_signature_is_in_every_paired_engine(stem, signature):
    """The six routines that say which byte is which, in all five.

    A finding taken from the engine's own instructions cannot be poisoned by
    an edited save (`.claude/rules/testing.md`), and five engines agreeing is
    what turns one reading of one overlay into a rule of the family.
    """
    assert _hits(_overlay(stem), signature) >= 1


@pytest.mark.parametrize("signature", [n for n, _, _ in ap.SIGNATURES])
def test_pool_of_radiance_has_none_of_them(signature):
    """The negative control: one copy of each ability, so none of these
    routines can exist -- and none does. A signature that matched here would
    mean the byte patterns are catching something other than what they claim
    to."""
    assert _hits(_overlay("POOLRAD"), signature) == 0


@PAIRED
def test_the_recompute_reads_the_lower_byte_and_writes_the_higher(stem):
    """`recompute-seed` and `recompute-store` are the whole answer for the six.

    The seed is `mov al, es:[di+0x10]` reached through `add di, ax` with `ax`
    twice the ability index, and the store is `mov es:[di+0x11], al`. A value
    computed from the other is the derived one, so the higher byte is what is
    in force.
    """
    data = _overlay(stem)
    assert _hits(data, "recompute-seed") >= 1
    assert _hits(data, "recompute-store") >= 1
    # And the mirror image of the store never appears anywhere in the file: a
    # *computed* value -- one held in a local and put into the record -- goes
    # into the higher byte once or twice per engine and into the lower byte
    # nought times in all five. The lower byte is only ever written by the
    # copy at the end of creation and by the Pool of Radiance import, both of
    # which move a value from somewhere else rather than derive one.
    import re
    reverse = rb"\x8a\x46.\xc4\x7e.\x26\x88\x45\x10"
    assert not list(re.finditer(reverse, data, re.S))


@PAIRED
def test_creation_copies_the_six_one_way_and_the_percentile_the_other(stem):
    """The asymmetry, in two instructions of one routine.

    Character creation ends by copying `[0x11 + 2i]` onto `[0x10 + 2i]` for the
    six abilities and `0x01C` onto `0x01D` for the percentile -- in Curse the
    two are 28 bytes apart in the same loop's tail. So the rolled score becomes
    the permanent one in both cases, and the byte the roll lives in is the
    higher one for the six and the lower one for the percentile.
    """
    data = _overlay(stem)
    assert _hits(data, "creation-copy-abilities") >= 1
    assert _hits(data, "creation-copy-exceptional") >= 1


@PAIRED
def test_one_routine_compares_against_the_pair_0x10_and_0x1d(stem):
    """`is-stronger` names both permanent bytes in four instructions.

    It asks whether an item's `18/xx` beats the character's own, and the score
    it compares against is `0x10` while the percentile is `0x1D` -- one lower
    byte and one higher one, which is the asymmetry stated by the engine in a
    single expression.
    """
    assert _hits(_overlay(stem), "is-stronger") == 1


def test_the_higher_byte_is_the_one_the_curse_overlay_mostly_touches():
    """The census's shape, which is the C64's the other way round.

    `#367` counted 129 references to the C64's current array against 38 to its
    base; here the six higher bytes outnumber the six lower ones by more than
    two to one, and the percentile goes the other way. It is a linear scan of a
    byte stream and therefore an upper bound rather than a count of
    instructions -- asserted as a ratio, not a number, so it says the same
    thing on a differently patched copy of the game.
    """
    import collections
    import re
    data = _overlay("CURSE")
    counts: collections.Counter = collections.Counter()
    for prefix in ap.OPCODES:
        for m in re.finditer(re.escape(prefix), data):
            disp = data[m.end()]
            if 0x10 <= disp <= 0x1D:
                counts[disp] += 1
    lower = sum(counts[d] for d in range(0x10, 0x1B, 2))
    higher = sum(counts[d] for d in range(0x11, 0x1C, 2))
    assert higher > 2 * lower
    assert counts[0x1C] > 2 * counts[0x1D]
