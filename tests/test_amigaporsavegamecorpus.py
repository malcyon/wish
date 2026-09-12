"""Every Amiga Pool of Radiance saved game on the machine, against the map.

`#316 (Write the Amiga Pool of Radiance saved game from the source save, so a
converted party arrives where it was standing)` named the container's regions
from the save routine and from the shipped slot A.  These tests take the same
boundaries back off the *files*, over every saved game in the specimen tree --
nineteen of them at the time of writing, twelve written by the Amiga engine
itself, standing in three areas and in both view modes.

What they would catch: a change to `POR_CHARACTER_TABLE`, to `POR_ECL_BUFFER`,
to `por_word_offset`'s arithmetic or to the ByteKiller depacker.  Each is a
boundary the writer builds the file around, and each is found here by a
property of the bytes -- a `CHRDAT` string, a match against the player's own
`ecl.dax`, three documented constants -- so none of it agrees with
`goldbox.amiga_por` by construction.

Everything reads the player's own disks: the saved games out of
`$WISH_SPECIMENS`, `ecl.dax` off Pool of Radiance disk 2.  Nothing is
committed and every test skips on a machine that has neither.
"""

from __future__ import annotations

import hashlib

import pytest

from goldbox import amiga_dax, amiga_por
from goldbox.amiga_adf import AmigaDisk
from tests import gamedata

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

ECL_DAX = "/ecl.dax"

#: `WISH-SPEC-por-amiga-outdoor` slot B, one of the two saved games Amiga Pool
#: of Radiance itself made on the travel grid.  Named because it is the
#: specimen that settles the `$5082` question below: its ancestor went in
#: holding three different values, so the engine had something to copy.
OUTDOOR_ENGINE_SAVE = ("por-amiga", "WISH-SPEC-por-amiga-outdoor",
                       "savgamB.dat")


# ---------------------------------------------------------------------------
# The corpus
# ---------------------------------------------------------------------------

def _saved_games() -> list[tuple[str, bytes]]:
    """Every distinct Pool of Radiance saved game inside a specimen `.adf`.

    Deduplicated by content, because the same file is on more than one disk
    image: a slot the engine wrote is on the image before and after the run
    that followed it.
    """
    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    found: dict[str, tuple[str, bytes]] = {}
    for image in sorted(root.rglob("*.[aA][dD][fF]")):
        try:
            disk = AmigaDisk(bytearray(image.read_bytes()))
        except Exception:
            continue                      # not a filesystem we can read
        for path, _entry in disk.walk():
            if "savgam" not in path.lower():
                continue
            data = disk.read_file(path)
            if len(data) != amiga_por.POR_SAVEGAME_SIZE:
                continue                  # Curse's is 15221, not this title
            found.setdefault(hashlib.md5(data).hexdigest(),
                             (f"{image.parent.name}{path}", data))
    if not found:
        pytest.skip("no Amiga Pool of Radiance saved game in the specimen tree")
    return [found[key] for key in sorted(found, key=lambda k: found[k][0])]


@pytest.fixture(scope="module")
def corpus() -> list[tuple[str, bytes]]:
    return _saved_games()


@pytest.fixture(scope="module")
def ecl_dax() -> bytes:
    from tools import amigasaves, gamedisks

    if not gamedisks.candidates("amiga"):
        pytest.skip("no Amiga disks; set $AMIGA_DISKS")
    for _name, data in amigasaves.images():
        try:
            return AmigaDisk(bytearray(data)).read_file(ECL_DAX)
        except Exception:
            continue
    pytest.skip("no Amiga Pool of Radiance disk 2 here")


# ---------------------------------------------------------------------------
# The four boundaries, re-derived from the bytes
# ---------------------------------------------------------------------------

def test_every_saved_game_here_is_the_documented_length(corpus):
    """13,141, which is DOS's 13,137 less a container byte and plus five."""
    wrong = [name for name, data in corpus
             if len(data) != amiga_por.POR_SAVEGAME_SIZE]
    assert not wrong, f"{len(wrong)} of {len(corpus)}: {wrong}"


def test_the_name_table_starts_where_the_map_says(corpus):
    """The tail is thirteen bytes because `CHRDAT` begins at 12813.

    Found by searching for the string rather than by reading
    `POR_CHARACTER_TABLE`, so this is the measurement the constant is meant
    to record.  It is what makes the Amiga's tail five longer than DOS's
    eight, and with the missing container byte it is the whole of the
    four-byte difference.
    """
    misplaced = [(name, data.find(b"CHRDAT")) for name, data in corpus
                 if data.find(b"CHRDAT") != amiga_por.POR_CHARACTER_TABLE]
    assert not misplaced, f"{len(misplaced)} of {len(corpus)}: {misplaced}"


def test_the_five_bytes_nothing_reads_are_zero(corpus):
    """12805-12809: two the square struct pads to, three of wallset entry 0."""
    start, end = amiga_por.POR_SQUARE_PAD
    dirty = [(name, data[start:end].hex()) for name, data in corpus
             if set(data[start:end]) - {0}]
    assert not dirty, f"{len(dirty)} of {len(corpus)}: {dirty}"


def test_the_count_byte_and_the_arrays_own_word_agree(corpus):
    """Byte 12812 against `$503E`, which is `por_word_offset` arithmetic."""
    offset = amiga_por.por_word_offset(0x503E)
    disagree = [(name, data[offset] << 8 | data[offset + 1],
                 data[amiga_por.POR_PARTY_SIZE_BYTE]) for name, data in corpus
                if (data[offset] << 8 | data[offset + 1])
                != data[amiga_por.POR_PARTY_SIZE_BYTE]]
    assert not disagree, f"{len(disagree)} of {len(corpus)}: {disagree}"


def test_the_variable_arrays_documented_constants_are_where_they_should_be(
        corpus):
    """`$4FE1` = 255, `$506D` = 16, `$50F6` = 1 -- the array's base and stride.

    Three constants at three widely separated addresses land right only if
    the array starts at file offset 0 and each word is two big-endian bytes.
    """
    expected = {0x4FE1: 255, 0x506D: 16, 0x50F6: 1}
    wrong = []
    for name, data in corpus:
        for address, value in expected.items():
            offset = amiga_por.por_word_offset(address)
            got = data[offset] << 8 | data[offset + 1]
            if got != value:
                wrong.append((name, f"${address:04X}", got, value))
    assert not wrong, f"{len(wrong)} readings wrong: {wrong}"


def test_the_script_buffer_holds_an_unpacked_ecl_dax_block(corpus, ecl_dax):
    """The area's script **as the loader unpacks it**, minus its header word.

    This is the second half of `#316`'s open question -- as shipped, or as
    unpacked?  Every block on the disk is ByteKiller-packed; every saved game
    here holds one of them depacked, from its byte 2 on, then zero to 12800.
    So the answer is *unpacked*, and it holds for a party outdoors as well as
    in.  A depacker that came back subtly wrong would fail this on every file
    at once.
    """
    unpacked = {block_id: amiga_dax.block(ecl_dax, block_id)
                for block_id in amiga_dax.block_ids(ecl_dax)}
    start, end = amiga_por.POR_ECL_BUFFER
    head = amiga_por.POR_ECL_HEADER
    unmatched, tails = [], []
    for name, data in corpus:
        probe = data[start:start + 64]
        hit = [i for i, block in unpacked.items()
               if block[head:head + 64] == probe]
        if not hit:
            unmatched.append(name)
            continue
        body = unpacked[hit[0]][head:]
        if data[start:start + len(body)] != body:
            unmatched.append(f"{name}: matched block {hit[0]} then diverged")
        elif set(data[start + len(body):end]) - {0}:
            tails.append(f"{name}: block {hit[0]}, then not zero")
    assert not unmatched, f"{len(unmatched)} of {len(corpus)}: {unmatched}"
    assert not tails, f"{len(tails)} of {len(corpus)}: {tails}"


# ---------------------------------------------------------------------------
# What DOS does and the Amiga does not
# ---------------------------------------------------------------------------

def test_the_amiga_does_not_keep_doss_three_way_copy_of_the_square_byte():
    """`$5082` is a third name for the attribute byte on DOS, and not here.

    `docs/141-dos-savegame.md` grades `$5082` == `$5200` == the tail's
    attribute byte CONFIRMED, in 21 of 21 engine-written DOS specimens.  This
    saved game is the one the Amiga engine wrote after a party whose ancestor
    held three *different* values there landed on the travel grid: it rewrote
    all three -- 25, 0, 0 became 0, 1, 1 -- and still left `$5082` unequal to
    the other two.  So the copy belongs to the DOS engine's code path, and
    deriving either word from the tail byte here would write a value the Amiga
    engine itself does not.

    `docs/165-amiga-savegame.md`, "DOS's third name for the attribute byte is
    not the Amiga's".
    """
    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    where = root.joinpath(*OUTDOOR_ENGINE_SAVE)
    if not where.is_file():
        pytest.skip(f"needs {'/'.join(OUTDOOR_ENGINE_SAVE[1:])}")
    data = where.read_bytes()

    def word(address: int) -> int:
        offset = amiga_por.por_word_offset(address)
        return data[offset] << 8 | data[offset + 1]

    attribute = data[amiga_por.POR_SQUARE_PROPERTY]
    assert attribute == 1
    assert word(0x5200) == attribute        # these two do agree here
    assert word(0x5082) == 0                # and this one does not follow


def test_neither_of_the_two_words_is_written_from_anything(corpus, ecl_dax):
    """Both are declared unsourced and written zero, which the engine took.

    The guard on the finding above: if a later change derived `$5082` or
    `$5200` from the square attribute -- reasonable-looking, since DOS does --
    this goes red rather than a converted party arriving with a word the
    Amiga's own engine never writes.
    """
    declared = {address for address, _words, _why
                in amiga_por.POR_SAVGAM_UNSOURCED}
    assert {0x5082, 0x5200} <= declared

    state = amiga_por.por_state_from_amiga(corpus[0][1], corpus[0][0])
    built, _report = amiga_por.new_por_savegame(state, "B", 1, ecl_dax)
    for address in (0x5082, 0x5200):
        offset = amiga_por.por_word_offset(address)
        assert built[offset] << 8 | built[offset + 1] == 0


def test_a_build_that_declines_a_word_says_so_rather_than_claiming_it_is_zero_everywhere(
        corpus, ecl_dax):
    """`#441 (A converted Amiga save's provenance claims three words are
    zero in every saved game, and they are not)`.

    `por_savegame_zeroes`'s catch-all sentence used to fall on `$49FF` when
    no portrait crossed and on `$49C3`/`$49C4` when the party is indoors --
    both left zero correctly, and both told a reader the word "reads zero
    in every Amiga saved game on this machine", which is false: `$49FF`
    reads 3 in most of the corpus here, including the one SSI shipped, and
    `$49C3`/`$49C4` are what the outdoor branch writes correctly on a party
    standing on the travel grid.  A word this build merely declines to
    write must say so, not claim to have measured it.
    """
    from goldbox import dos_savegame

    state = amiga_por.por_state_from_amiga(corpus[0][1], corpus[0][0])
    assert state.outdoors is False        # the indoor half of the gate

    built, report = amiga_por.new_por_savegame(state, "B", 1, ecl_dax,
                                           portraits=False)

    portrait_offset = amiga_por.por_word_offset(0x49FF)
    assert built[portrait_offset] << 8 | built[portrait_offset + 1] == 0
    travel_offset = amiga_por.por_word_offset(dos_savegame.TRAVEL_X)
    assert built[travel_offset:travel_offset + 4] == b"\x00\x00\x00\x00"

    for offset in (portrait_offset, travel_offset):
        why = report.sources[offset]
        assert "this word reads zero in every Amiga saved game" not in why, why
        assert "#441" in why, why
    assert "does not write the word" in report.sources[portrait_offset]
    assert "writes no travel square" in report.sources[travel_offset]


# ---------------------------------------------------------------------------
# The reader, pointed at the disk a conversion produces
# ---------------------------------------------------------------------------

def _poolsave_disk(tmp_path, names=("savgamB.dat", "savgamC.dat")):
    """A `POOLSAVE` disk shaped like the one a conversion writes.

    Synthetic on purpose, so this never skips: what is being tested is where
    the reader looks, not what the bytes say.
    """
    disk = AmigaDisk.blank("POOLSAVE")
    for name in names:
        disk.write_file(f"/{name}", bytes(amiga_por.POR_SAVEGAME_SIZE))
    where = tmp_path / "poolsave.adf"
    disk.save(where)
    return where


def test_a_save_disks_slots_are_found_in_the_root(tmp_path):
    """A `POOLSAVE` disk keeps its saved games in the root, not in a drawer.

    The situation: you convert a party, `tools/toamigapor.py --save-disk`
    hands you a `POOLSAVE.ADF`, and you point the reader at it to see what
    went on.  It used to answer `name a saved game or an --adf image`, as
    though you had given it nothing -- because it walked for `save/savgam*`
    and a save disk has no `save` drawer.
    """
    from tools import amigasavegame

    disk = AmigaDisk.open(_poolsave_disk(tmp_path))
    found = sorted(path for path, _data in amigasavegame.savegames_on(disk))
    assert found == ["/savgamB.dat", "/savgamC.dat"]


def test_a_game_disks_save_drawer_is_still_found(tmp_path):
    """And the drawer a game disk uses keeps working."""
    from tools import amigasavegame

    disk = AmigaDisk.blank("poolgame")
    disk.make_dir("/save")
    disk.write_file("/save/savgamA.dat", bytes(amiga_por.POR_SAVEGAME_SIZE))
    disk.write_file("/ecl.dax", b"not a saved game")
    where = tmp_path / "poolgame.adf"
    disk.save(where)

    reopened = AmigaDisk.open(where)
    found = sorted(path for path, _data in amigasavegame.savegames_on(reopened))
    assert found == ["/save/savgamA.dat"]


def test_a_disk_with_no_saved_game_says_so_rather_than_blaming_the_reader(
        tmp_path):
    """Naming an image and getting nothing off it is not naming no image."""
    from tools import amigasavegame

    disk = AmigaDisk.blank("POOLDATA")
    disk.write_file("/ecl.dax", b"not a saved game")
    where = tmp_path / "pooldata.adf"
    disk.save(where)

    with pytest.raises(SystemExit) as raised:
        amigasavegame.main(["--adf", str(where)])
    assert "no saved game on" in str(raised.value)
    assert "POOLDATA" in str(raised.value)


def test_the_sweep_says_how_wide_the_zero_argument_is(corpus):
    """`--sweep` measures the corpus the writer's zeroes rest on.

    4,072 of the 13,141 bytes are written zero because no Amiga saved game
    here holds anything at that address, and that argument is only as wide as
    the places the parties have stood.  The table says how wide: how many
    words are ever non-zero, and how many a corpus of one place alone would
    have missed.

    Asserted as a shape rather than as the numbers, which move whenever a
    saved game is added -- except the one that must not move, that the whole
    corpus sees at least what any one place in it sees.
    """
    from tools import amigasavegame

    parsed = [(name, amigasavegame.parse(data, source=name))
              for name, data in corpus]
    text = amigasavegame.sweep(parsed)
    assert f"{len(corpus)} saved games" in text

    places = {save.word(0x5012) for _name, save in parsed}
    assert f"{len(places)} places" in text
    for container in places:
        assert f"\n  {container:5d} " in text

    # The union cannot be smaller than any one place's set, so the last
    # column is never negative -- which is the arithmetic the table rests on.
    assert " -" not in text.split("\n", 2)[2]
