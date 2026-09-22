"""Where each Amiga title strips characters out of a name, read off the player's disks.

The executables and records come from `gamedisks.yaml`'s `amiga` entry and the
specimen tree at run time, and every test that needs them skips without them,
which is what CI does. The model tests need nothing: the names in them are the
ones typed into the running game in `docs/206-three-amiga-questions.md` §2.
"""

from __future__ import annotations

import pytest

from tools.amiga import amigabackstab, amiganamespaces

#: One row a title: the strip routine, each call to it as `(call, where the
#: cleaned text goes)`, the routines that copy it back into a record with
#: whether they do so unconditionally, their callers, and the `$FF` swaps.
EXPECTED = {
    "pool-of-radiance": {
        "strip": 0x01634C,
        "sites": [(0x02649E, "record"), (0x0267FC, "buffer"),
                  (0x0272CE, "buffer"), (0x02734A, "buffer"),
                  (0x02797E, "buffer")],
        "in_place": {0x02646C: True},
        "record_callers": {0x02646C: [0x016B40, 0x018514, 0x02796E]},
        "ff_sites": [0x0184D6],
    },
    "curse-of-the-azure-bonds": {
        "strip": 0x013B74,
        "sites": [(0x019510, "buffer"), (0x02501A, "buffer"),
                  (0x025B00, "buffer"), (0x0261EA, "buffer"),
                  (0x0262B6, "buffer")],
        "in_place": {},
        "record_callers": {},
        "ff_sites": [],
    },
    "secret-of-the-silver-blades": {
        "strip": 0x017172,
        "sites": [(0x00D686, "buffer"), (0x026892, "buffer"),
                  (0x027318, "buffer"), (0x0273E8, "buffer")],
        "in_place": {},
        "record_callers": {},
        "ff_sites": [],
    },
    "pools-of-darkness": {
        "strip": 0x016E52,
        "sites": [(0x00E6A8, "buffer"), (0x0257D4, "buffer"),
                  (0x026492, "buffer"), (0x026554, "buffer")],
        "in_place": {},
        "record_callers": {},
        "ff_sites": [],
    },
}

_RAW: dict[str, bytes | None] = {}


def _finding(key: str) -> amiganamespaces.Finding:
    if key not in _RAW:
        _RAW[key] = amigabackstab.executable(amigabackstab.TITLES[key])
    raw = _RAW[key]
    if raw is None:
        pytest.skip(f"No Amiga {amigabackstab.TITLES[key].title} executable "
                    f"on any disk here.")
    return amiganamespaces.inspect(raw, key)


def test_every_amiga_title_is_read():
    assert sorted(amigabackstab.TITLES) == sorted(EXPECTED)


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_the_strip_routine_and_whether_it_reaches_a_record(key):
    """Pool of Radiance alone copies the cleaned name back into the record.

    Its save routine at `$2646C` does it before anything branches, so every
    save of a character strips it; the later titles clean a stack copy that
    becomes a file name, and no title but Pool of Radiance swaps a space for
    `$FF`, which its creation does before the first save.
    """
    finding = _finding(key)
    want = EXPECTED[key]
    assert finding.strip == want["strip"]
    assert [(s.at, s.result) for s in finding.sites] == want["sites"]
    assert finding.in_place == want["in_place"]
    assert finding.record_callers == want["record_callers"]
    assert finding.ff_sites == want["ff_sites"]


def test_creation_saves_right_after_the_ff_swap():
    finding = _finding("pool-of-radiance")
    assert finding.saved_after(0x0184D6) == 0x018514


@pytest.mark.parametrize("typed, saved", [
    (b"MARY SUE", b"MARYSUE"),
    (b"MARY SUE FOX", b"MARYSUEFOX"),
    (b"ABCDEFGHIJKLMNO", b"ABCDEFGHIJKLMNO"),
    (b"ABCDEFG HIJKLMN", b"ABCDEFGHIJKLMN"),
    (b"LADY KATHERINE", b"LADYKATHERINE"),
])
def test_the_model_gives_what_the_running_game_saved(typed, saved):
    """The four RENAMEs and one converted name `docs/206` read back."""
    assert amiganamespaces.por_saved(typed) == saved


def test_a_space_behind_a_stripped_byte_survives_one_save():
    """The set loop does not retest a position against the space after a delete."""
    assert amiganamespaces.por_saved(b"A  B") == b"A B"
    assert amiganamespaces.por_saved(b"J. R") == b"J R"
    assert amiganamespaces.por_saved(b"A B") == b"AB"


def test_creation_keeps_a_space_as_ff():
    assert amiganamespaces.por_created(b"mary sue") == b"MARY\xffSUE"


def test_every_pool_of_radiance_resave_on_the_disks_matches_the_model():
    """A record the engine resaved beside ours holds what `por_saved` predicts.

    The records on one image with the same letters all lie on one chain of
    saves: one of them is where it starts, and every other is what some
    number of saves leaves of it. A space behind a stripped byte takes two
    saves to go, and `por-amiga-ff-names` holds both steps.
    """
    every = amiganamespaces.everything()
    pairs = amiganamespaces.resaved(every)
    if not pairs:
        pytest.skip("No Amiga Pool of Radiance name with a stripped "
                    "character on any disk or specimen here.")
    assert any(match is not None for _name, match in pairs)
    por = [n for n in every if n.title == "Pool of Radiance"]

    def letters(name):
        return bytes(c for c in name.text if chr(c).isalnum())

    for name, _match in pairs:
        image = name.where.split(":", 1)[0]
        group = {other.text for other in por
                 if other.where.split(":", 1)[0] == image
                 and letters(other) == letters(name)}
        assert any(group <= set(amiganamespaces.por_chain(start))
                   for start in group), (image, sorted(group))


def test_the_model_chain_ends_where_a_save_changes_nothing():
    assert amiganamespaces.por_chain(b"A  B") == [b"A  B", b"A B", b"AB"]
    assert amiganamespaces.por_chain(b"MARY\xffSUE") == [b"MARY\xffSUE"]


def _watched():
    seen = amiganamespaces.watched()
    if seen is None:
        pytest.skip(f"No {amiganamespaces.WATCHED_SPECIMEN} in the specimen "
                    f"tree here.")
    return seen


def test_the_running_game_keeps_ff_and_strips_the_rest_one_step_a_save():
    """What the engine saved, read off the disk it wrote.

    `MARY<FF>SUE` comes through two saves in one boot and a third after a
    cold boot unchanged; `A  B` and `J. R` lose one byte to each save.
    """
    assert _watched() == amiganamespaces.WATCHED_SLOTS


@pytest.mark.parametrize("slot", sorted(amiganamespaces.WATCHED_FROM))
def test_every_watched_save_is_what_the_model_predicts(slot):
    seen = _watched()
    source = amiganamespaces.WATCHED_FROM[slot]
    assert seen[slot] == tuple(amiganamespaces.por_saved(name)
                               for name in seen[source])


def test_creation_stores_a_typed_space_as_ff():
    """`MARY SUE` typed at Create New Character, in the file and its name."""
    made = amiganamespaces.created()
    if made is None:
        pytest.skip(f"No {amiganamespaces.CREATED_SPECIMEN} in the specimen "
                    f"tree here.")
    assert made == amiganamespaces.CREATED_FILES
    assert amiganamespaces.por_created(b"MARY SUE") == made["CHRDATA1.sav"]
