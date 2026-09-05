"""`tools/daxls.py` reads a `.DAX` the way the DOS engine does.

The container is built here from the documented format rather than read
from the game, so nothing of the game's enters the repository; one test at
the end reads the player's own `CBODY.DAX` and skips without it.
"""

from __future__ import annotations

import pathlib
import struct
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))

import daxls  # noqa: E402


def _rle(raw: bytes) -> bytes:
    """Pack a block as the engine's run-length coder would: one literal run."""
    out = bytearray()
    for i in range(0, len(raw), 128):
        chunk = raw[i:i + 128]
        out += bytes([len(chunk) - 1]) + chunk
    return bytes(out)


def _dax(blocks: dict[int, bytes]) -> bytes:
    """A whole container: index size, entries, then the packed blocks."""
    packed = {bid: _rle(raw) for bid, raw in blocks.items()}
    index = bytearray()
    body = bytearray()
    for bid, raw in blocks.items():
        index += struct.pack("<BIHH", bid, len(body), len(raw), len(packed[bid]))
        body += packed[bid]
    return struct.pack("<H", len(index)) + bytes(index) + bytes(body)


def _image(rows: int, eights: int, value: int) -> bytes:
    header = bytes([rows, 0, eights, 0]) + bytes(13)
    return header + bytes([value * 0x11]) * (rows * eights * 4)


def test_an_image_block_is_recognised_by_its_exact_length():
    block = _image(rows=3, eights=2, value=0xA)
    assert daxls.image_shape(block) == (3, 16)
    assert daxls.image_shape(block + b"\0") is None
    assert daxls.image_shape(bytes(10)) is None


def test_pixels_come_out_high_nibble_first():
    block = bytes([1, 0, 1, 0]) + bytes(13) + bytes([0x12, 0x34, 0x56, 0x78])
    assert daxls.pixels(block) == [[1, 2, 3, 4, 5, 6, 7, 8]]


def test_the_listing_names_every_block_and_its_shape():
    data = _dax({7: _image(2, 3, 1), 200: b"not an image at all"})
    lines = daxls.listing(data, "T.DAX")
    assert lines[0].startswith("T.DAX: ") and "2 blocks" in lines[0]
    assert "id   7" in lines[1] and "image 24x2" in lines[1]
    assert "id 200" in lines[2] and "image" not in lines[2]


def test_dump_and_png_write_what_was_asked(tmp_path):
    data = _dax({3: _image(4, 1, 0xF)})
    dax = tmp_path / "X.DAX"
    dax.write_bytes(data)
    out = tmp_path / "block.bin"
    assert daxls.main([str(dax), "--dump", "3", str(out)]) == 0
    assert out.read_bytes() == _image(4, 1, 0xF)
    png = tmp_path / "block.png"
    assert daxls.main([str(dax), "--png", "3", str(png), "--scale", "2"]) == 0
    from PIL import Image
    with Image.open(png) as image:
        assert image.size == (16, 8)


def test_a_missing_block_is_a_message_not_a_traceback(tmp_path):
    dax = tmp_path / "X.DAX"
    dax.write_bytes(_dax({1: _image(1, 1, 0)}))
    with pytest.raises(SystemExit) as e:
        daxls.main([str(dax), "--dump", "9", str(tmp_path / "no")])
    assert "no block 9" in str(e.value)


def test_the_players_cbody_is_128_image_blocks_of_24_by_24():
    """`CBODY.DAX` off the player's DOS game, through `tools/iconcorrespond.py`'s
    lookup; skipped when there is no DOS game on this machine."""
    import iconcorrespond as ic
    try:
        game = ic.dos_game(None)
    except SystemExit:
        pytest.skip("needs the DOS game files; set POR_DOS_GAME")
    lines = daxls.listing((game / "CBODY.DAX").read_bytes(), "CBODY.DAX")
    assert "128 blocks" in lines[0]
    assert all("image 24x24" in line for line in lines[1:])
