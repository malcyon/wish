"""`tools/icons/dosiconstage.py` writes each title's figure bytes at that title's own offsets."""
import pytest

from goldbox import dos_port
from tools.icons import dosiconstage

COLOURS = "91a2b3c4e6f7"

#: (title key, record size, head, body, colours) as the layout tables place them.
OFFSETS = [
    ("pool-of-radiance", 285, 0x0BD, 0x0BE, 0x0C1),
    ("curse-of-the-azure-bonds", 422, 0x141, 0x142, 0x145),
    ("secret-of-the-silver-blades", 439, 0x153, 0x154, 0x157),
    ("pools-of-darkness", 510, 0x19A, 0x19B, 0x19E),
]


@pytest.mark.parametrize("key,size,head,body,colours", OFFSETS)
def test_figure_lands_at_the_titles_own_offsets(tmp_path, key, size, head, body, colours):
    assert dos_port.deltas_for(size).key == key
    path = tmp_path / "CHRDATD1.SAV"
    path.write_bytes(bytes(size))
    dosiconstage.stage(tmp_path, "D", [(8, 22, COLOURS)])
    data = path.read_bytes()
    expected = bytearray(size)
    expected[head], expected[body] = 8, 22
    expected[colours:colours + 6] = bytes.fromhex(COLOURS)
    assert data == bytes(expected)
