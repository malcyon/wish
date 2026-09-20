"""Nothing in a DOS engine caps experience below the C64's three bytes
(`#597`).

The DOS Curse and Silver Blades records keep experience in four bytes where
every C64 record keeps three, so a converted character could carry a number
the destination has no room for.  Three questions, in that order, and this
file answers them from the game's own bytes rather than from the records
anybody happens to own:

* is the engine's running total really 32 bits, or a word the record merely
  has room for?  A `add`/`adc` pair into the longword says it is;
* does anything cap it?  A cap at the C64's ceiling has to compare the *high*
  word against `0x0100` or more, and no title does;
* what does our conversion do with a value that does not fit?  It refuses,
  naming the field, and writes nothing.

The synthetic half runs anywhere.  The overlay scan skips without the
player's DOS archives and the conversion skips without the specimen tree, so
CI runs the first and reports the rest as skips.  `docs/117-save-conversion.md`
has the finding and `tools/records/xpceiling.py` is the reader.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import gamedata  # noqa: E402

from goldbox import dos_port as dl  # noqa: E402
from tools.dos import dosbox  # noqa: E402
from tools.records import xpceiling  # noqa: E402

TITLES = sorted(xpceiling.STEMS)

#: An engine-written record per title, and one of its character files.  Both
#: were written by the DOS game itself under `tools/dos/dosbox.py`, so the
#: bytes around the experience this test replaces are the engine's.
RECORDS = {
    "curse-of-the-azure-bonds": ("coab-dos",
                                 "WISH-SPEC-curse-408-regained-paladin"),
    "secret-of-the-silver-blades": ("ssb-dos", "WISH-SPEC-c64todos-ssb-resave"),
}


def _overlay(key: str) -> bytes:
    if not dosbox.ARCHIVES.is_dir():
        pytest.skip("no DOS archives on this machine; set $FR_ARCHIVES")
    path = xpceiling.overlay(key)
    if path is None:
        pytest.skip(f"no {xpceiling.STEMS[key]}/GAME.OVR on this machine")
    return path.read_bytes()


def _record(key: str) -> bytes:
    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/registry/specimens.py")
    platform, name = RECORDS[key]
    where = root / platform / name
    if not where.is_dir():
        pytest.skip(f"needs {where}")
    for path in sorted(where.glob("CHRDAT*.SAV")):
        data = path.read_bytes()
        try:
            found = dl.deltas_for(len(data)).key
        except Exception:                                # pragma: no cover
            continue
        if found == key:
            return data
    pytest.skip(f"no {key} record in {where}")


# --------------------------------------------------------------------------
# The matcher, against bytes this file builds
# --------------------------------------------------------------------------

#: `add es:[di+0x127], ax` then `adc es:[di+0x129], dx`, which is how a
#: 16-bit compiler emits `+=` on a `long` reached through a far pointer.
_PAIR = bytes.fromhex("26 01 85 27 01 26 11 95 29 01".replace(" ", ""))


def test_the_matcher_finds_an_add_adc_pair_and_nothing_else():
    image = b"\x90" * 8 + _PAIR + b"\x90" * 8
    assert xpceiling.accumulates(image, 0x127) == [8]
    assert xpceiling.accumulates(image, 0x129) == []


@pytest.mark.parametrize("what, image", [
    # the `adc` lands on a different displacement, so the two are not one long
    ("adc elsewhere", _PAIR[:8] + bytes([0x2B, 0x01])),
    # the `adc` is on another base register, so it is another structure
    ("adc on bx", _PAIR[:7] + bytes([0x97]) + _PAIR[8:]),
    # no segment override: not a far pointer, so not a character record
    ("no prefix", _PAIR[1:]),
])
def test_the_matcher_refuses_a_near_miss(what, image):
    assert xpceiling.accumulates(b"\x90" * 8 + image + b"\x90" * 8,
                                 0x127) == [], what


#: `cmp es:[di+0x129], 0x0100` -- what a cap at the C64's ceiling would have
#: to look like, since `experience >= 0x1000000` is `high word >= 0x0100`.
_CAP = bytes.fromhex("2681bd29010001")


def test_the_cap_detector_fires_on_a_high_word_compare_that_would_bound_it():
    """The detector is not vacuous: given the compare, it says so.

    Without this the "no title caps it" tests above would pass on a scanner
    that found nothing at all.
    """
    image = b"\x90" * 8 + _CAP + b"\x90" * 8
    assert xpceiling.high_word_constants(image, 0x127) == {0x0100}
    assert xpceiling.capped_below(image, 0x127)
    # And one that bounds the value higher than the C64's ceiling does not.
    assert not xpceiling.capped_below(image, 0x127, ceiling=0x1FFFFFF)


# --------------------------------------------------------------------------
# The engines
# --------------------------------------------------------------------------


@pytest.mark.parametrize("key", TITLES)
def test_every_dos_engine_adds_into_experience_thirty_two_bits_wide(key):
    """The running total is a longword in all four engines.

    Pool of Radiance is in this list deliberately.  `goldbox/dos_port.py`
    calls its experience three bytes at `0x0AC` with an unattributed
    `gap_0af` beside it, and the engine's own accumulate writes `0x0AE` and
    `0x0AF` together -- so the gap is the top byte of the same long, and the
    three-byte reading holds only while no character passes `0xFFFFFF`.
    """
    image = _overlay(key)
    at = xpceiling.experience_offset(key)
    assert xpceiling.accumulates(image, at), (
        f"{key}: no add/adc pair into the longword at {at:#05x}")


@pytest.mark.parametrize("key", TITLES)
def test_no_dos_engine_caps_experience_below_the_c64_width(key):
    """No high-word compare could bound the total at or below `0xFFFFFF`.

    `experience >= 0x1000000` is exactly `high word >= 0x0100`, so a cap at
    the C64's ceiling would have to show up as such a compare.  The constants
    that do turn up are the high halves of each title's character-creation
    starting totals -- 0 for Curse's 8,333/12,500/25,000, 1 and 3 for Silver
    Blades' 66,667/100,000/200,000, 7, 11 and 22 for Pools of Darkness'.
    """
    image = _overlay(key)
    at = xpceiling.experience_offset(key)
    constants = xpceiling.high_word_constants(image, at)
    assert not xpceiling.capped_below(image, at), (
        f"{key}: high word compared against {sorted(constants)}")


# --------------------------------------------------------------------------
# The conversion
# --------------------------------------------------------------------------


@pytest.mark.parametrize("key", sorted(RECORDS))
def test_the_c64_width_is_the_last_value_that_converts(key):
    record = _record(key)
    read_back, did = xpceiling.convert(record, xpceiling.C64_CEILING)
    assert read_back == str(xpceiling.C64_CEILING)
    assert did == f"wrote {xpceiling.C64_CEILING} " \
                  f"({xpceiling.C64_CEILING:#x}) -- kept"


@pytest.mark.parametrize("key", sorted(RECORDS))
def test_one_past_the_c64_width_is_refused_and_never_wrapped(key):
    """The bug this issue was opened against would be a silent wrap.

    `goldbox.c64_codec.write` raises instead, naming the field and the width,
    so a high-experience character cannot be quietly converted into a poorer
    one.  `editor/convert.py` catches it with every other conversion failure,
    so what a player sees today is the generic refusal.
    """
    record = _record(key)
    for value in (xpceiling.C64_CEILING + 1, 0x7FFFFFFF):
        read_back, did = xpceiling.convert(record, value)
        assert read_back == str(value), (
            f"{key}: the DOS record lost {value}, reading back {read_back}")
        assert did.startswith("refused: "), f"{key}: {did}"
        assert "experience" in did and "3 bytes" in did
