"""`tools/amigacontainercheck.py`, the check that an Amiga container is built.

The tool itself needs the player's C64 specimens and their Amiga disk 2;
everything here is synthetic, so the parts that decide what the tool *says*
are tested on a machine with neither.  The run against real files is the tool's
own job and its exit status.

The test that matters most is
:func:`test_neither_reader_calls_the_library_it_is_checking`.  The tool's
result means something only because its two ends share no reader -- the C64
payload read by hand at `address - 0x4900`, the built container read at fixed
offsets -- and the natural tidy-up is to replace either with a call into
`goldbox.amiga`, which would leave a tool that agrees with the writer by
construction and can never fail.  That test turns the tidy-up red.
"""

from __future__ import annotations

import inspect
import pathlib

import pytest

from tools import amigacontainercheck as check

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


# ---------------------------------------------------------------------------
# Two hand-built files, at the offsets the layout gives rather than the ones
# the tool computes
# ---------------------------------------------------------------------------

def a_c64_payload(x=14, y=4, facing=3, travel=(7, 28), geo=20,
                  clock=(0, 2, 2, 21, 0, 0), indoors=1, area=20) -> bytes:
    """A `SAVEDGAME0` payload with the eight fields set and nothing else.

    A memory image based at `$4900`, so `$49C0` is offset `0xC0`.  The offsets
    are written out rather than derived, so a tool that started reading the
    DOS container's layout -- everything one byte along -- fails here.
    """
    out = bytearray(0x800)
    out[0xC0], out[0xC1], out[0xC2] = x, y, facing
    out[0xC3], out[0xC4] = travel
    out[0xC5] = geo
    out[0xC6:0xCC] = bytes(clock)
    out[0xE6] = indoors
    out[0xF2] = area
    return bytes(out)


def a_container(x=14, y=4, facing=6, travel=(7, 28), geo=20,
                clock=(0, 2, 2, 21, 0, 0), indoors=1, area=20,
                view=1, mode=2, count=6) -> bytes:
    """13,141 bytes with the same eight fields, the Amiga's way.

    The variable array is big-endian words two bytes apart, so `$49C0` is
    offset `0x180`, and the square is three plain bytes in the tail at 12800.
    """
    out = bytearray(check.CONTAINER_SIZE)

    def word(offset: int, value: int) -> None:
        out[offset:offset + 2] = value.to_bytes(2, "big")

    word(0x186, travel[0])
    word(0x188, travel[1])
    word(0x18A, geo)
    for i, digit in enumerate(clock):
        word(0x18C + 2 * i, digit)
    word(0x1CC, indoors)
    word(0x1E4, area)
    out[12800], out[12801], out[12802] = x, y, facing
    out[12810], out[12811], out[12812] = view, mode, count
    return bytes(out)


# ---------------------------------------------------------------------------
# The two readers
# ---------------------------------------------------------------------------

def test_the_c64_reader_reads_the_documented_offsets():
    got = check.c64_fields(a_c64_payload())
    assert got == {"x": 14, "y": 4, "facing": 3, "travel": (7, 28),
                   "geo": 20, "clock": (0, 2, 2, 21, 0, 0),
                   "outdoors": False, "area": 20}


def test_a_c64_party_on_the_travel_grid_reads_as_outdoors():
    assert check.c64_fields(a_c64_payload(indoors=0))["outdoors"] is True


def test_the_container_reader_reads_big_endian_words_and_the_tail():
    got = check.container_fields(a_container())
    assert got["x"] == 14 and got["y"] == 4 and got["facing"] == 6
    assert got["clock"] == (0, 2, 2, 21, 0, 0)
    assert got["area"] == 20 and got["geo"] == 20
    assert got["travel"] == (7, 28)
    assert (got["view"], got["mode"], got["count"]) == (1, 2, 6)


def test_a_word_is_big_endian_rather_than_little():
    """An area of 256 is `01 00`, and reading it the other way gives 1."""
    raw = bytearray(a_container())
    raw[0x1E4:0x1E6] = (256).to_bytes(2, "big")
    assert check.container_fields(bytes(raw))["area"] == 256


def test_a_file_that_is_not_13141_bytes_is_refused():
    with pytest.raises(ValueError, match="13141"):
        check.container_fields(b"\0" * 13137)


def test_neither_reader_calls_the_library_it_is_checking():
    """The property the whole tool rests on, kept by a test.

    `c64_fields` and `container_fields` must name no field accessor from
    `goldbox` -- if either one starts calling the code being checked, the
    comparison agrees by construction and the tool can no longer fail.
    """
    banned = ("por_word", "world_state", "c64_save", "dos_savegame",
              "por_state_from", "amiga.", "SaveGame0")
    for func in (check.c64_fields, check.container_fields):
        # The docstrings name the accessors they promise not to call, so the
        # scan is of the code and the docstring is cut out first. Newlines are
        # normalised before the cut because `inspect.getsource` hands back the
        # file's own line endings while `__doc__` always holds `\n`, so on
        # Windows the docstring did not match itself and stayed in, which
        # turned this test red on CI and nowhere else.
        source = inspect.getsource(func).replace("\r\n", "\n")
        body = source.replace((func.__doc__ or "").replace("\r\n", "\n"), "")
        for name in banned:
            assert name not in body, f"{func.__name__} calls {name}"


# ---------------------------------------------------------------------------
# The comparison, and what it lets past
# ---------------------------------------------------------------------------

def test_the_facing_is_expected_doubled():
    """The C64 stores 0-3 and both DOS and the Amiga store it doubled."""
    assert check.expected(check.c64_fields(a_c64_payload()))["facing"] == 6


def test_an_agreeing_pair_matches_field_for_field():
    rows = check.compare(check.c64_fields(a_c64_payload()),
                         check.container_fields(a_container()))
    assert {r[3] for r in rows} == {check.MATCHED}


def test_a_container_at_the_wrong_clock_is_a_mismatch():
    """The failure this tool exists to catch: a container carrying somebody
    else's time of day."""
    rows = check.compare(
        check.c64_fields(a_c64_payload()),
        check.container_fields(a_container(clock=(0, 8, 4, 5, 0, 0))))
    bad = [r for r in rows if r[3] == check.MISMATCH]
    assert [r[0] for r in bad] == ["clock"]


def test_a_container_at_the_wrong_square_is_a_mismatch():
    rows = check.compare(check.c64_fields(a_c64_payload()),
                         check.container_fields(a_container(x=0, y=5)))
    assert sorted(r[0] for r in rows if r[3] == check.MISMATCH) == ["x", "y"]


def test_the_outdoor_geo_rule_is_declared_rather_than_a_mismatch():
    """Outdoors the writer writes `$49C5` = 0 on purpose, and says why."""
    source = check.c64_fields(a_c64_payload(indoors=0, geo=5))
    built = check.container_fields(a_container(indoors=0, geo=0))
    rows = {r[0]: r for r in check.compare(source, built)}
    assert rows["geo"][3] == check.DECLARED
    assert "SQRDATA" in rows["geo"][4]
    assert rows["area"][3] == check.MATCHED


def test_an_outdoor_container_at_the_wrong_travel_square_still_fails():
    """The declared list is three fields wide, not a blanket outdoors."""
    source = check.c64_fields(a_c64_payload(indoors=0, travel=(7, 28)))
    built = check.container_fields(a_container(indoors=0, travel=(1, 1)))
    bad = [r[0] for r in check.compare(source, built)
           if r[3] == check.MISMATCH]
    assert bad == ["travel"]


def test_an_indoor_container_writing_no_travel_square_is_declared():
    source = check.c64_fields(a_c64_payload(travel=(7, 28)))
    built = check.container_fields(a_container(travel=(0, 0)))
    rows = {r[0]: r for r in check.compare(source, built)}
    assert rows["travel"][3] == check.DECLARED


def test_which_fields_are_not_the_shipped_containers():
    shipped = check.container_fields(
        a_container(x=0, y=4, facing=6, geo=0, area=0,
                    clock=(0, 8, 4, 5, 0, 0)))
    built = check.container_fields(a_container())
    assert check.differs_from(built, shipped) == ["x", "clock", "area", "geo"]
    assert check.differs_from(shipped, shipped) == []


# ---------------------------------------------------------------------------
# The report and the command line
# ---------------------------------------------------------------------------

class _Report:
    """What `new_por_savegame` returns beside the file, as the tool reads
    it: how many bytes have a source, and which have none."""

    def __init__(self, unwritten=()):
        self.sources = {i: "x" for i in range(check.CONTAINER_SIZE)}
        self.unwritten = list(unwritten)


def _staged(monkeypatch, payload: bytes, container: bytes) -> pathlib.Path:
    """Point the tool's two file readers at bytes rather than at disks."""
    monkeypatch.setattr(check, "load_payload", lambda path, name: payload)
    monkeypatch.setattr(check, "build",
                        lambda *a, **k: (container, _Report()))
    return pathlib.Path("WISH-SPEC-synthetic.d64")


def test_the_report_says_every_container_matched(monkeypatch):
    save = _staged(monkeypatch, a_c64_payload(), a_container())
    lines, ok = check.report([save], b"", a_container(x=0, area=0, geo=0),
                             "B", 6)
    assert ok
    assert "1 save(s) checked, every container carries" in lines[-1]
    assert any("WISH-SPEC-synthetic.d64" in ln for ln in lines)


def test_the_report_fails_and_names_the_field(monkeypatch):
    """Watched failing is the whole point: the same run with one field of the
    container changed comes back false and says which."""
    save = _staged(monkeypatch, a_c64_payload(),
                   a_container(clock=(0, 8, 4, 5, 0, 0)))
    lines, ok = check.report([save], b"", None, "B", 6)
    assert not ok
    assert any("clock" in ln and "**" in ln for ln in lines)


def test_a_save_that_is_not_one_is_reported_rather_than_raising(monkeypatch):
    def boom(path, name):
        raise ValueError("no SAVEDGAME0 here")

    monkeypatch.setattr(check, "load_payload", boom)
    lines, ok = check.report([pathlib.Path("notasave.d64")], b"", None, "B", 6)
    assert not ok
    assert any("not a C64 Pool of Radiance save" in ln for ln in lines)


def test_a_refused_area_is_reported_rather_than_raising(monkeypatch):
    monkeypatch.setattr(check, "load_payload", lambda p, n: a_c64_payload())

    def refuse(*a, **k):
        raise ValueError("area 30 has no script in the Amiga game's ecl.dax")

    monkeypatch.setattr(check, "build", refuse)
    lines, ok = check.report([pathlib.Path("area30.d64")], b"", None, "B", 6)
    assert not ok
    assert any("refused" in ln and "area 30" in ln for ln in lines)


def test_the_specimen_glob_takes_por_d64s_and_nothing_else(tmp_path):
    where = tmp_path / "por-c64"
    where.mkdir()
    for name in ("WISH-SPEC-porunconscious1.d64",
                 "WISH-SPEC-por-party-twin-pair.D64",
                 "WISH-SPEC-curse-dual-classed.D64",
                 "WISH-SPEC-porunconscious1.provenance.toml"):
        (where / name).write_bytes(b"")
    assert [p.name for p in check.specimen_saves(tmp_path)] == [
        "WISH-SPEC-por-party-twin-pair.D64", "WISH-SPEC-porunconscious1.d64"]


def test_a_tree_with_no_saves_is_two_rather_than_a_traceback(tmp_path, capsys):
    assert check.main(["--specimens", str(tmp_path)]) == 2
    assert "no C64 Pool of Radiance saves" in capsys.readouterr().err


def test_no_ecl_dax_names_the_disk_it_is_on(tmp_path, monkeypatch, capsys):
    """Disk 2, by name, because that is the answer the reader needs."""
    where = tmp_path / "por-c64"
    where.mkdir()
    (where / "WISH-SPEC-por-synthetic.d64").write_bytes(b"")
    monkeypatch.setattr(check, "amiga_files", lambda a, b: (None, None))
    assert check.main(["--specimens", str(tmp_path)]) == 2
    assert "disk 2" in capsys.readouterr().err
