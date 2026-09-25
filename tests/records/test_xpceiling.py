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
* what does our conversion do with a value that does not fit?  It writes the
  C64's largest experience, `0xFFFFFF`, and records a drop line saying what
  the character held.  A refusal would leave the player no converted
  character at all, which is what the ruling on the issue chose against.

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

    Pool of Radiance is in this list deliberately: its accumulate writes
    `0x0AE` and `0x0AF` together, which is why `goldbox/dos_port.py` declares
    its experience as four bytes at `0x0AC`.
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
def test_one_past_the_c64_width_is_clamped_and_never_wrapped(key):
    """A wrap would quietly convert a rich character into a poor one.

    `goldbox.c64_codec.write` writes the field's largest value instead and
    puts a line on `report.warnings`, which reaches the debug log and no
    player-facing text.  It used to raise here; the experience is now
    clamped so the character converts at all.
    """
    record = _record(key)
    for value in (xpceiling.C64_CEILING + 1, 0x7FFFFFFF):
        read_back, did = xpceiling.convert(record, value)
        assert read_back == str(value), (
            f"{key}: the DOS record lost {value}, reading back {read_back}")
        assert did.startswith(f"wrote {xpceiling.C64_CEILING} "), f"{key}: {did}"
        assert f"clamped from {value}" in did
        assert f"experience: DOS holds {value}" in did


# --------------------------------------------------------------------------
# The clamp, on records this file builds (runs without the specimen tree)
# --------------------------------------------------------------------------

#: A zeroed record of each DOS title whose experience is four bytes, at its
#: own record size.  Every field is zero, so the only number in play is the
#: experience the test writes.
_BLANK_SIZES = {"curse-of-the-azure-bonds": 422,
                "secret-of-the-silver-blades": 439}


def _clamped(key: str, value: int):
    """`(record, report)` from a blank DOS record at `value` experience."""
    import struct

    from goldbox import c64_codec, dos_codec
    shape = dl.deltas_for(_BLANK_SIZES[key])
    assert shape.key == key
    buf = bytearray(_BLANK_SIZES[key])
    struct.pack_into("<I", buf, xpceiling.experience_offset(key), value)
    dos = dos_codec.DosCharacter(bytes(buf), deltas=shape)
    assert dos.get("experience") == value
    return c64_codec.write(dos_codec.to_neutral(dos))


@pytest.mark.parametrize("key", sorted(_BLANK_SIZES))
@pytest.mark.parametrize("value", [0x1000000, 0x7FFFFFFF])
def test_experience_past_three_bytes_converts_as_the_c64_maximum(key, value):
    """Refused before: `ValueError: experience: 16777216 does not fit in 3
    bytes`.  A character with that much converts at `0xFFFFFF` now, and the
    warning line names the value that was held so the debug log can say why the
    number changed."""
    rec, rep = _clamped(key, value)
    assert rec.get("experience") == xpceiling.C64_CEILING
    assert not [d for d in rep.losses if d.startswith("experience:")]
    lines = [d for d in rep.warnings if d.startswith("experience:")]
    assert len(lines) == 1, rep.warnings
    assert not [d for d in rep.dropped if d.startswith("experience:")]
    assert str(value) in lines[0] and str(xpceiling.C64_CEILING) in lines[0]


@pytest.mark.parametrize("key", sorted(_BLANK_SIZES))
def test_the_c64_maximum_is_kept_exactly_and_drops_nothing(key):
    rec, rep = _clamped(key, xpceiling.C64_CEILING)
    assert rec.get("experience") == xpceiling.C64_CEILING
    assert not [d for d in rep.losses if d.startswith("experience:")]


@pytest.mark.parametrize("key", sorted(_BLANK_SIZES))
def test_a_negative_experience_is_still_refused(key):
    """The clamp is for a value too big; one no field can hold still raises."""
    from goldbox import c64_codec
    from tools.records import boundarywidths
    char = boundarywidths.base(key)
    char.set("experience", -1, "test: below zero")
    with pytest.raises(ValueError, match="experience"):
        c64_codec.write(char)
