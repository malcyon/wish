"""`staging._prepare_from`'s substitute slot: a party from a different disk at the route's loaded letter.

Built for #661 (A C64 party under a running spell loses it on the way to DOS
or the Amiga, because the C64 reader reads only the paladin's rows out of the
effect arrays), whose Amiga acceptance needs a way to put the Save As Amiga
output's party at the route's loaded letter on a copy of the pinned Curse
specimen. These tests build both disks synthetically, so they run with no
game data anywhere.
"""

from __future__ import annotations

import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from support.amigarecords import sample, synthetic_savegame  # noqa: E402
from support.amigasavegame import synthetic_curse  # noqa: E402

from goldbox import amiga_savegame  # noqa: E402
from goldbox.amiga_adf import AmigaDisk, AmigaDiskError  # noqa: E402
from tools.amiga import route_curse, route_pool, staging  # noqa: E402
from tools.amiga.staging import _Sources  # noqa: E402
from tools.amiga.winuaesession import RouteError  # noqa: E402

CURSE = route_curse.CURSE


def _curse_disk(tmp_path, name: str, slots: dict[str, tuple[str, ...]]) -> pathlib.Path:
    disk = AmigaDisk.blank("CurseA")
    disk.make_dir("/SAVE")
    for letter, names in slots.items():
        disk.write_file(f"/SAVE/savgam{letter}.dat", synthetic_curse(names))
    path = tmp_path / name
    disk.save(path)
    return path


@pytest.fixture
def sources(tmp_path):
    """A `_Sources` naming a two-slot pinned specimen (loaded A, later C), no side images."""
    specimen = _curse_disk(tmp_path, "pinned.adf",
                           {"A": ("ALPHA", "BETA"), "C": ("ALPHA", "BETA")})
    return _Sources("test-curse", CURSE, (), staging.sha256(specimen), "CurseA", "A", "C", {}), specimen


def test_with_no_substitute_the_manifest_reflects_the_pinned_specimen(tmp_path, sources):
    src, specimen = sources
    manifest = staging._prepare_from(src, tmp_path / "run", specimen)
    assert manifest["names_a"] == ["ALPHA", "BETA"]
    assert "substitute" not in manifest
    assert manifest["expected_after"] is not None
    assert AmigaDisk.open(manifest["disks"]["save"]["path"]).read_file(
        "/SAVE/savgamA.dat") == synthetic_curse(("ALPHA", "BETA"))


def test_a_substitute_has_no_expected_after_since_it_never_walked_the_route(tmp_path, sources):
    """A substituted party did not walk the pinned specimen's route, so its

    'later' checkpoint describes an unrelated party's position and must not
    be asserted against the substitute's actual post-walk place.
    """
    src, specimen = sources
    substitute = _curse_disk(tmp_path, "substitute.adf", {"A": ("GAMMA", "DELTA")})

    manifest = staging._prepare_from(src, tmp_path / "run", specimen, substitute=substitute)

    assert manifest["expected_after"] is None


def test_a_substitute_slot_replaces_the_loaded_letter_and_nothing_else(tmp_path, sources):
    src, specimen = sources
    substitute = _curse_disk(tmp_path, "substitute.adf", {"A": ("GAMMA", "DELTA")})

    manifest = staging._prepare_from(src, tmp_path / "run", specimen, substitute=substitute)

    assert manifest["names_a"] == ["GAMMA", "DELTA"]
    assert manifest["substitute"] == {
        "path": str(substitute), "sha256": staging.sha256(substitute), "letter": "A"}
    written = AmigaDisk.open(manifest["disks"]["save"]["path"])
    # The later letter, C, is untouched: still the pinned specimen's own party.
    assert written.read_file("/SAVE/savgamC.dat") == synthetic_curse(("ALPHA", "BETA"))
    # The pinned specimen and the substitute disk on disk are unread-only, unmodified.
    assert staging.sha256(specimen) == src.specimen_sha256
    assert AmigaDisk.open(specimen).read_file("/SAVE/savgamA.dat") == synthetic_curse(
        ("ALPHA", "BETA"))


def test_a_substitute_at_a_different_letter_is_read_by_that_letter(tmp_path, sources):
    src, specimen = sources
    substitute = _curse_disk(tmp_path, "substitute.adf", {"E": ("EPSILON",)})

    manifest = staging._prepare_from(
        src, tmp_path / "run", specimen, substitute=substitute, substitute_letter="E")

    assert manifest["names_a"] == ["EPSILON"]


def test_a_missing_substitute_is_refused(tmp_path, sources):
    src, specimen = sources
    with pytest.raises(RouteError, match="substitute .* is missing"):
        staging._prepare_from(src, tmp_path / "run", specimen,
                              substitute=tmp_path / "no-such-file.adf")


def test_a_substitute_with_no_such_letter_is_refused(tmp_path, sources):
    src, specimen = sources
    substitute = _curse_disk(tmp_path, "substitute.adf", {"A": ("GAMMA",)})
    with pytest.raises(RouteError, match="could not be imported"):
        staging._prepare_from(src, tmp_path / "run", specimen,
                              substitute=substitute, substitute_letter="Z")


def test_an_unreadable_substitute_is_refused_at_adf_open(tmp_path, sources):
    src, specimen = sources
    substitute = tmp_path / "broken.adf"
    substitute.write_bytes(b"not an ADF image" * 100)
    with pytest.raises(AmigaDiskError):
        staging._prepare_from(src, tmp_path / "run", specimen, substitute=substitute)


def test_a_substitute_that_fails_adf_verification_is_refused(tmp_path, sources):
    """A structurally valid ADF -- `AmigaDisk.open` succeeds -- whose root block
    checksum is wrong, so only `_prepare_from`'s own `source_disk.verify()`
    call, not `AmigaDisk.open`, rejects it."""
    src, specimen = sources
    disk = AmigaDisk.blank("CurseA")
    raw = bytearray(disk.to_bytes())
    # Flip a byte inside the root block's unused comment field (0x148-0x1A3),
    # clear of the hash table (0x18-0x137), type, name and sec-type fields --
    # so the block still opens and every hash chain still walks, but no
    # longer sums to zero.
    raw[disk.root * 512 + 0x150] ^= 0xFF
    substitute = tmp_path / "broken.adf"
    substitute.write_bytes(bytes(raw))
    # The corrupted disk does open (root found by its type/sec-type fields).
    AmigaDisk.open(substitute)
    with pytest.raises(RouteError, match=f"{re.escape(str(substitute))} fails ADF verification: "):
        staging._prepare_from(src, tmp_path / "run", specimen, substitute=substitute)


def _pool_disk(tmp_path, name, letter, member):
    disk = amiga_savegame.make_por_save_disk(
        letter, [sample(name=member)], synthetic_savegame(letter))
    path = tmp_path / name
    disk.save(path)
    return disk, path


def test_pool_substitute_copies_slot_bytes_and_keeps_other_slots(tmp_path):
    pinned, specimen = _pool_disk(tmp_path, "pool-pinned.adf", "A", "ALPHA")
    other, _ = _pool_disk(tmp_path, "pool-other.adf", "B", "BETA")
    for entry in other.entries():
        if entry.name.upper() in {"SAVE", "CHARLIST.TXT"}:
            continue
        pinned.write_file(f"/{entry.name}", other.read_file(f"/{entry.name}"))
    pinned.write_file("/CHRDATA1.itm", b"stale")
    pinned.write_file("/save", amiga_savegame.slot_list_bytes(["A", "B"]))
    pinned.save(specimen)
    source, substitute = _pool_disk(tmp_path, "pool-substitute.adf", "E", "GAMMA")
    src = _Sources("test-pool", route_pool.POOL, (), staging.sha256(specimen),
                   "POOLSAVE", "A", "B", {}, route_pool.POOL_SOURCES.import_slot)

    manifest = staging._prepare_from(
        src, tmp_path / "run-pool", specimen, substitute=substitute,
        substitute_letter="E")

    result = AmigaDisk.open(manifest["disks"]["save"]["path"])
    assert result.volume_name == "POOLSAVE"
    assert manifest["names_a"] == ["GAMMA"]
    assert manifest["expected_after"] is None
    assert route_pool._pool_slot_files(result, "B") == route_pool._pool_slot_files(pinned, "B")
    assert "/CHRDATA1.itm" not in [path for path, _ in result.walk()]
    assert set(amiga_savegame.read_slot_list(result, "")) == {"A", "B"}
    assert result.read_file("/CHRDATA1.sav") == source.read_file("/CHRDATE1.sav")
    assert amiga_savegame.read_por_slot(result, "A", drawer="")[1] == (
        amiga_savegame.retarget_savegame(source.read_file("/savgamE.dat"), "A"))
    assert staging.sha256(specimen) == src.specimen_sha256
    assert staging.sha256(substitute) == manifest["substitute"]["sha256"]


def test_pool_substitute_refuses_missing_source_letter(tmp_path):
    pinned, specimen = _pool_disk(tmp_path, "pool-pinned.adf", "A", "ALPHA")
    other, _ = _pool_disk(tmp_path, "pool-other.adf", "B", "BETA")
    for entry in other.entries():
        if entry.name.upper() in {"SAVE", "CHARLIST.TXT"}:
            continue
        pinned.write_file(f"/{entry.name}", other.read_file(f"/{entry.name}"))
    pinned.save(specimen)
    _, substitute = _pool_disk(tmp_path, "pool-substitute.adf", "E", "GAMMA")
    src = _Sources("test-pool", route_pool.POOL, (), staging.sha256(specimen),
                   "POOLSAVE", "A", "B", {}, route_pool.POOL_SOURCES.import_slot)
    with pytest.raises(RouteError, match="could not be imported"):
        staging._prepare_from(src, tmp_path / "run-pool", specimen,
                              substitute=substitute, substitute_letter="Z")
