"""The census `tools/dossavcensus.py` takes of the DOS saved games present.

Every grade in `docs/141-dos-savegame.md` is a **count**, and a count is only
worth its exclusions: `#59 (Map the DOS saved game, not just the character
record)` reached two wrong conclusions by counting files nobody should have
counted -- a bisection whose twelve variants all carried the same ECL buffer,
and an outdoor field whose value matched the template every specimen had
departed from. Both looked like measurements.

So the test that matters here is `hand_built`. A file we assembled is not
evidence about what the engine writes, and if a `SEED-` or a `built/`
directory ever slips back into the corpus the counts quietly inflate and
nothing goes red. The rest of the module -- `find_saves`, `describe`,
`census`, `_label` -- is pure over bytes and paths and is covered alongside.

**No game bytes are committed here.** The synthetic buffers below are zeroes
with a handful of words set by address, which is a size and a layout rather
than anything of the game's; the tests that need a real container read
Donald's own through the same gate `tests/test_dosoutdoor.py` uses, and skip
without it.
"""
from __future__ import annotations

import pathlib
import struct
import sys

import pytest
from test_dossave import _save_dir, needs_dos_saves

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import dos_savegame as sg  # noqa: E402
from tools import dossavcensus as census  # noqa: E402


def _blank(shape: sg.DosSaveShape = sg.SAVE_POOL_OF_RADIANCE, **words) -> bytes:
    """A container of the right size, all zero but for the words named.

    Not a slice of anything: `bytearray(shape.size)` and then `put_word` at
    the addresses a test cares about.
    """
    save = bytearray(shape.size)
    for address, value in words.items():
        at = sg.word_offset(int(address.lstrip("a"), 16), shape)
        struct.pack_into("<H", save, at, value)
    return bytes(save)


def _write(where: pathlib.Path, name: str, data: bytes) -> pathlib.Path:
    where.mkdir(parents=True, exist_ok=True)
    path = where / name
    path.write_bytes(data)
    return path


# -- hand_built, the exclusion the counts rest on -------------------------

@pytest.mark.parametrize("name", ["BUILT-SAVGAMA.DAT", "SEED-SAVGAMB.DAT"])
def test_a_prefixed_file_is_hand_built(tmp_path, name):
    """`BUILT-` and `SEED-` are ours, whatever directory they sit in."""
    assert census.hand_built(tmp_path / name)


def test_a_file_in_a_built_directory_is_hand_built(tmp_path):
    """`work/p26/issue191/built/SAVGAMA.DAT` carries no prefix at all.

    It is the one hand-built specimen on this machine whose *name* says
    nothing, so the directory is the second test and dropping it is how that
    file got counted as engine-written the first time.
    """
    assert census.hand_built(tmp_path / "built" / "SAVGAMA.DAT")


@pytest.mark.parametrize("name", ["SAVGAMA.DAT", "RESAVE-SAVGAMD.DAT",
                                  "SAVGAMJ.DAT"])
def test_an_engine_written_file_is_not_hand_built(tmp_path, name):
    """`RESAVE-` is the engine's own `ENCAMP > SAVE` and must be counted.

    The prefix names where the file came from in our runs, not who wrote it:
    excluding it would throw away seven of the corpus's specimens.
    """
    assert not census.hand_built(tmp_path / "run2" / name)


def test_the_counts_exclude_hand_built_and_stubs(tmp_path):
    """End to end: three files in, one counted.

    A seed, a stub and an engine-written save. Only the last has anything to
    say about what the engine writes, and `census` is handed only that one.
    """
    # `$49C9` is the hour: the stub test is "zero script buffer and a clock
    # that reads 00:00", and `$49C6` is the sub-minute digit, which `clock()`
    # does not return -- setting only that leaves a save looking like a stub.
    played = _blank(a49E6=1, a49C9=10, a5012=2, a4900=7)
    seed = _blank(a49E6=1, a49C9=10, a5012=2, a4900=9)
    stub = _blank()                       # zero clock, zero script buffer
    _write(tmp_path, "SAVGAMA.DAT", played)
    _write(tmp_path, "SEED-SAVGAMB.DAT", seed)
    _write(tmp_path, "SAVGAMC.DAT", stub)

    found = [p for p in census.find_saves([tmp_path])
             if tmp_path in p.parents or p.parent == tmp_path]
    kept = [census.describe(p) for p in found]
    counted = [s for s in kept if not s["hand_built"] and not s["stub"]]
    assert [s["label"].split(":")[-1] for s in counted] == ["A"]


# -- find_saves ----------------------------------------------------------

def test_find_saves_filters_on_the_container_size(tmp_path):
    """The size is the filter, so another title's container drops out."""
    ours = _write(tmp_path, "SAVGAMA.DAT", _blank())
    curse = _write(tmp_path, "SAVGAMB.DAT",
                   bytes(sg.SAVE_CURSE_OF_THE_AZURE_BONDS.size))
    junk = _write(tmp_path, "SAVGAMC.DAT", b"not a saved game")
    found = census.find_saves([tmp_path])
    assert ours in found
    assert curse not in found and junk not in found


def test_find_saves_picks_the_asked_for_title(tmp_path):
    """`--title` swaps which size is wanted, and nothing else."""
    ours = _write(tmp_path, "SAVGAMA.DAT", _blank())
    curse = _write(tmp_path, "SAVGAMB.DAT",
                   bytes(sg.SAVE_CURSE_OF_THE_AZURE_BONDS.size))
    found = census.find_saves([tmp_path],
                              sg.SAVE_CURSE_OF_THE_AZURE_BONDS)
    assert curse in found and ours not in found


def test_find_saves_deduplicates_on_the_bytes(tmp_path):
    """The archives ship most save directories twice.

    Counting a file twice because it is in two places is the same defect as
    counting a seed: the corpus size stops meaning what it says.
    """
    same = _blank(a49E6=1, a49C6=3)
    a = _write(tmp_path / "one", "SAVGAMA.DAT", same)
    b = _write(tmp_path / "two", "SAVGAMA.DAT", same)
    found = census.find_saves([tmp_path])
    assert (a in found) != (b in found)


def test_a_seed_never_wins_the_name_of_an_identical_engine_save(tmp_path):
    """When two files share their bytes, the kept one is not the seed.

    Deduplication keeps whichever it meets first, so the order matters: a
    reader who saw `SEED-` in the specimen list would take a count of ours
    for a count of the engine's.
    """
    same = _blank(a49E6=1, a49C6=3)
    engine = _write(tmp_path, "SAVGAMA.DAT", same)
    _write(tmp_path, "SEED-SAVGAMA.DAT", same)
    found = census.find_saves([tmp_path])
    assert engine in found
    assert not any(census.hand_built(p) and p.parent == tmp_path
                   for p in found)


# -- describe and census -------------------------------------------------

def test_describe_refuses_to_invent_a_pools_of_darkness_reading(tmp_path):
    """Pools of Darkness has no container byte and no variable array.

    A number read at Pool of Radiance's offsets would be a plausible-looking
    lie, which is the failure `#175 (Decode the first 1024 bytes of the Pools
    of Darkness saved game)` is trying not to inherit.
    """
    path = _write(tmp_path, "SAVGAMA.PTY",
                  bytes(sg.SAVE_POOLS_OF_DARKNESS.size))
    got = census.describe(path, sg.SAVE_POOLS_OF_DARKNESS)
    for field in ("area", "clock", "flags", "wallset", "dax_byte", "indoors"):
        assert got[field] is None, field
    assert got["party_size"] == 0          # the tail is still readable
    # Twelve, not eight. This asserted eight until #175 read the writer out of
    # `GAME.OVR`: Pools of Darkness lays its square block out as five bytes
    # from `DS:0xA9F3`, two interface-mode bytes, two words and the count of
    # character files, and the four bytes in front of it that this project
    # called "unnamed" were its own last four.
    assert len(got["tail"]) == sg.SAVE_POOLS_OF_DARKNESS.square_bytes == 12


def test_census_counts_the_words_that_are_zero_everywhere(tmp_path):
    """Two containers in, and only the words one of them sets are live."""
    a = _blank(a49C6=1, a5012=2)
    b = _blank(a49C6=3, a503E=6)
    report = census.census([{"label": "a"}, {"label": "b"}], [a, b],
                           sg.SAVE_POOL_OF_RADIANCE)
    assert sorted(report["live"]) == ["$49C6", "$5012", "$503E"]
    assert report["zero_everywhere"] == sg.VAR_WORDS - 3
    assert report["live"]["$49C6"] == [1, 3]


def test_census_of_a_title_with_no_variable_array_counts_nothing():
    """Rather than counting 2560 zeroes it does not have."""
    report = census.census([{"label": "a"}],
                           [bytes(sg.SAVE_POOLS_OF_DARKNESS.size)],
                           sg.SAVE_POOLS_OF_DARKNESS)
    assert report["words_total"] == 0 and report["live"] == {}


# -- labels --------------------------------------------------------------

def test_the_label_keeps_the_provenance_prefix(tmp_path):
    """A reader has to be able to see which specimens we assembled."""
    assert census._label(tmp_path / "run2" / "SEED-SAVGAMB.DAT") == "run2:sB"
    assert census._label(tmp_path / "run2" / "RESAVE-SAVGAMD.DAT") == "run2:rD"
    assert census._label(tmp_path / "run2" / "SAVGAMA.DAT") == "run2:A"


def test_two_titles_of_one_size_get_different_labels(tmp_path):
    """Pools of Darkness and Treasures of the Savage Frontier both write 1364.

    A size-filtered sweep finds four files under two slot letters, and a
    label that says only `shipped:A` twice conflates two titles' specimens.
    """
    root = tmp_path / "Collection Two" / "games"
    pod = root / "Pools of Darkness" / "GAME" / "DARKNESS" / "SAVE"
    tsf = root / "Treasures of the Savage Frontier" / "GAME" / "X" / "SAVE"
    pod.mkdir(parents=True)
    tsf.mkdir(parents=True)
    assert census._label(pod / "SAVGAMA.PTY") != \
        census._label(tsf / "SAVGAMA.PTY")


# -- against the player's own containers ---------------------------------

@needs_dos_saves
def test_the_players_own_saves_are_found_and_read():
    """The gate the rest of the DOS suite uses, so this skips without them."""
    where = _save_dir()
    mine = {p.read_bytes() for p in where.glob("SAVGAM?.DAT")
            if p.stat().st_size == sg.SAVGAM_SIZE}
    if not mine:
        pytest.skip("no Pool of Radiance container in the player's save dir")
    found = census.find_saves()
    # Matched on bytes rather than on path: the archives ship the same
    # containers under `GAME/POOLRAD/SAVE` as well, and deduplication keeps
    # whichever of the two identical files it met first.
    assert mine <= {p.read_bytes() for p in found}
    for path in found:
        got = census.describe(path)
        assert got["party_size"] == 6
        assert not got["hand_built"]
        assert len(got["tail"]) == 8
