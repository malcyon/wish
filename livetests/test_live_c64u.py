"""A C64 Ultimate on the network, read for real."""

import pytest

from tools.c64 import c64u


def test_the_raster_counter_moves_between_two_reads():
    """The claim under test: a DMA read reaches live I/O.
    `README.md:287` in the c64u repo says DMA writes reach only RAM; two reads
    of $D012 coming back different disproves it for reads at least.

    Read-only, but the machine is on a desk and may have somebody playing on
    it.
    """
    dev = c64u.Ultimate()
    if not dev.available():
        pytest.skip("no C64 Ultimate answered")
    seen = {dev.read_mem(0xD012, 1)[0] for _ in range(8)}
    assert len(seen) > 1, f"$D012 never moved across 8 reads: {seen}"
