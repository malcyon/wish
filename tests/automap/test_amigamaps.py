"""Checks that the automapper's map loader finds an Amiga title's maps.

A folder of `.adf` images holds no C64 disk, so `load_maps_titled` used to
return nothing for it and the window drew no area. The synthetic disks here
are built with `AmigaDisk.blank` and hold no game data; the tests against a
player's own disks skip without them.
"""

from __future__ import annotations

import struct
import zipfile

import pytest

from automap import amiga, gamedisks, paths
from automap.maps import _volume_title, load_maps_titled
from goldbox import amiga_dax, c64_port
from goldbox.amiga_adf import AmigaDisk
from goldbox.geo import GEO_SIZE

PORTS = (c64_port.POOL_OF_RADIANCE, c64_port.CURSE_OF_THE_AZURE_BONDS,
         c64_port.SECRET_OF_THE_SILVER_BLADES)


def block(seed: int) -> bytes:
    """1024 bytes that are not any map, each distinct from every other seed."""
    return bytes((seed * 31 + i) & 0xFF for i in range(GEO_SIZE))


def glib(maps: dict[int, bytes]) -> bytes:
    """A `GEO.GLB`: the index block, then one block per map."""
    ids = sorted(maps)
    index = struct.pack(">H", len(ids)) + b"".join(
        struct.pack(">HH", ident, n + 1) for n, ident in enumerate(ids))
    blocks = [index] + [maps[i] for i in ids]
    body = b"".join(blocks)
    head = (b"GLIB" + struct.pack(">I", len(body))
            + struct.pack(">HH", len(blocks), 0) + b"GEO ")
    start = len(head) + 4 * (len(blocks) + 1)
    offsets, at = [], start
    for b in blocks:
        offsets.append(at)
        at += len(b)
    offsets.append(at)
    return head + b"".join(struct.pack(">I", o) for o in offsets) + body


def packed(raw: bytes) -> bytes:
    """`raw` in the Amiga `.dax`'s packing, using only its literal runs.

    The reader consumes bits from the end of the block, so the runs are
    written backwards, and each longword yields 32 bits from its low bit up.
    """
    bits: list[int] = []
    data = raw[::-1]
    for at in range(0, len(data), 8):
        chunk = data[at:at + 8]
        bits += [0, 0] + [(len(chunk) - 1) >> s & 1 for s in (2, 1, 0)]
        for byte in chunk:
            bits += [byte >> s & 1 for s in range(7, -1, -1)]
    bits += [0] * (-len(bits) % 32)
    words = [sum(bit << n for n, bit in enumerate(bits[i:i + 32]))
             for i in range(0, len(bits), 32)]
    first = 1                                  # no data bits, only the sentinel
    check = first
    for word in words:
        check ^= word
    stream = b"".join(struct.pack(">I", w) for w in reversed(words))
    out = stream + struct.pack(">III", first, check, len(raw))
    assert amiga_dax.unpack(out, len(raw)) == raw
    return out


def dax(maps: dict[int, bytes]) -> bytes:
    """A `geo.dax`: each block the C64's load address and then the map."""
    ids = sorted(maps)
    chunks = [packed(b"\x00\x04" + maps[i]) for i in ids]
    entries, at = b"", 0
    for ident, chunk in zip(ids, chunks):
        entries += amiga_dax.ENTRY.pack(ident, at, len(chunk), GEO_SIZE + 2)
        at += len(chunk)
    return struct.pack(">H", len(entries)) + entries + b"".join(chunks)


def disk(volume: str, drawer: str | None, name: str, data: bytes) -> AmigaDisk:
    image = AmigaDisk.blank(volume)
    if drawer:
        image.make_dir(drawer)
    image.write_file(f"{drawer}/{name}" if drawer else name, data)
    return image


def put(folder, filename: str, image: AmigaDisk) -> None:
    (folder / filename).write_bytes(image.to_bytes())


MAPS = {0x10: block(1), 0x15: block(2), 0x20: block(3)}


def test_a_folder_of_silver_blades_disks_gives_that_disks_own_maps(tmp_path):
    put(tmp_path, "b.adf", disk("Secret 2", "DISK2", "GEO.GLB", glib(MAPS)))
    maps, game = load_maps_titled(str(tmp_path))
    assert game is c64_port.SECRET_OF_THE_SILVER_BLADES
    assert {k: g.to_bytes() for k, g in maps.items()} == {
        "GEO10": MAPS[0x10], "GEO15": MAPS[0x15], "GEO20": MAPS[0x20]}


def test_the_disk_globs_are_not_taught_about_adf(tmp_path):
    """The character editor reads the same globs to decide which disks it opens,
    so the Amiga branch is reached without them."""
    before = {g.key: paths.disk_globs(g) for g in c64_port.GAMES}
    put(tmp_path, "b.adf", disk("CurseB", "DISKB", "GEO.GLB", glib(MAPS)))
    assert load_maps_titled(str(tmp_path))[0]
    assert {g.key: paths.disk_globs(g) for g in c64_port.GAMES} == before
    assert not any("adf" in p.lower() for g in c64_port.GAMES
                   for p in paths.disk_globs(g))
    assert paths.titles_in(tmp_path) == []
    assert not paths.has_disks(tmp_path, c64_port.CURSE_OF_THE_AZURE_BONDS)


def test_pool_of_radiances_maps_come_out_of_geo_dax(tmp_path):
    put(tmp_path, "por1.adf", disk("poolgame", None, "program", b"x" * 600))
    put(tmp_path, "por2.adf", disk("POOLDATA", None, "geo.dax", dax(MAPS)))
    maps, game = load_maps_titled(str(tmp_path))
    assert game is c64_port.POOL_OF_RADIANCE
    assert {k: g.to_bytes() for k, g in maps.items()} == {
        "GEO10": MAPS[0x10], "GEO15": MAPS[0x15], "GEO20": MAPS[0x20]}


def test_an_extension_in_capitals_is_read(tmp_path):
    put(tmp_path, "B.ADF", disk("Secret 2", "DISK2", "GEO.GLB", glib(MAPS)))
    assert len(load_maps_titled(str(tmp_path))[0]) == 3


def test_a_title_asked_for_is_never_given_another_titles_disk(tmp_path):
    put(tmp_path, "b.adf", disk("Secret 2", "DISK2", "GEO.GLB", glib(MAPS)))
    assert load_maps_titled(
        str(tmp_path), c64_port.CURSE_OF_THE_AZURE_BONDS) == (
        {}, c64_port.CURSE_OF_THE_AZURE_BONDS)


def test_a_folder_of_several_titles_answers_the_first_in_games_order(tmp_path):
    put(tmp_path, "a.adf", disk("Secret 2", "DISK2", "GEO.GLB", glib({1: block(9)})))
    put(tmp_path, "b.adf", disk("CurseB", "DISKB", "GEO.GLB", glib({2: block(8)})))
    assert load_maps_titled(str(tmp_path))[1] is c64_port.CURSE_OF_THE_AZURE_BONDS
    maps, game = load_maps_titled(str(tmp_path),
                                  c64_port.SECRET_OF_THE_SILVER_BLADES)
    assert list(maps) == ["GEO01"] and game is c64_port.SECRET_OF_THE_SILVER_BLADES


def test_pools_of_darkness_is_no_title_the_automapper_has(tmp_path):
    """Its `POD 3` carries a `GEO.GLB` too, and must not be drawn as another
    title's areas."""
    put(tmp_path, "pod3.adf", disk("POD 3", "DISK3", "GEO.GLB", glib(MAPS)))
    assert load_maps_titled(str(tmp_path)) == ({}, None)
    assert load_maps_titled(
        str(tmp_path), c64_port.SECRET_OF_THE_SILVER_BLADES)[0] == {}


def test_a_file_that_is_not_a_disk_is_skipped(tmp_path):
    (tmp_path / "junk.adf").write_bytes(b"not a disk")
    put(tmp_path, "b.adf", disk("Secret 2", "DISK2", "GEO.GLB", glib(MAPS)))
    assert len(load_maps_titled(str(tmp_path))[0]) == 3


def test_a_disk_a_title_keeps_no_maps_on_gives_none(tmp_path):
    put(tmp_path, "a.adf", disk("Secret 1", None, "Secret", b"x" * 600))
    assert load_maps_titled(str(tmp_path)) == ({}, None)


@pytest.mark.parametrize("volume,title", [
    ("poolgame", c64_port.POOL_OF_RADIANCE),
    ("POOLDATA", c64_port.POOL_OF_RADIANCE),
    ("CurseA", c64_port.CURSE_OF_THE_AZURE_BONDS),
    ("Secret 1", c64_port.SECRET_OF_THE_SILVER_BLADES),
    ("Pools Of Darkness 1", None),
    ("POD 3", None),
])
def test_a_volume_names_its_title(volume, title):
    assert _volume_title(volume) is title


# -- the player's own disks ---------------------------------------------------


def _folder_of(title, tmp_path):
    """Copies of one title's disks from wherever the registry says Amiga disks
    are, whether loose or inside a `.zip`, one per distinct volume."""
    try:
        roots = gamedisks.candidates("amiga")
    except (Exception, SystemExit):
        roots = []
    seen: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        images = [p.read_bytes() for p in sorted(root.rglob("*"))
                  if p.suffix.lower() == ".adf"]
        for archive in sorted(root.rglob("*.zip")):
            try:
                with zipfile.ZipFile(archive) as z:
                    images += [z.read(n) for n in z.namelist()
                               if n.lower().endswith(".adf")]
            except zipfile.BadZipFile:
                continue
        for data in images:
            try:
                volume = AmigaDisk(data).volume_name
            except Exception:
                continue
            if _volume_title(volume) is title and volume not in seen:
                seen.add(volume)
                (tmp_path / f"{len(seen)}.adf").write_bytes(data)
    if not seen:
        pytest.skip(f"no Amiga disk of {title.title}; set $AMIGA_DISKS")
    return tmp_path


@pytest.mark.parametrize("title", PORTS, ids=[t.key for t in PORTS])
def test_the_loader_finds_a_title_off_the_players_own_amiga_disks(title, tmp_path):
    from automap.area import looks_like_a_map
    folder = _folder_of(title, tmp_path)
    maps, game = load_maps_titled(str(folder))
    assert game is title
    assert maps, f"no maps found for {title.title}"
    assert all(k.startswith("GEO") for k in maps)
    assert [k for k, g in maps.items() if not looks_like_a_map(g)] == []
    if title is not c64_port.POOL_OF_RADIANCE:
        own, _image = amiga.load_maps_in(folder)
        assert {k: g.to_bytes() for k, g in maps.items()} == {
            k: g.to_bytes() for k, g in own.items()}
