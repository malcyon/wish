"""A C64 Ultimate on the network, read for real."""

import os
from pathlib import Path

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
    if not dev.cli:
        explicit = os.environ.get("C64U_CLI")
        if explicit:
            pytest.fail(f"$C64U_CLI is {explicit}, which does not exist")
        pytest.fail("the c64u command-line tool is not installed: set $C64U_CLI or put c64u on PATH")
    if not (Path(dev.cli).is_file() and os.access(dev.cli, os.X_OK)):
        pytest.fail(f"the c64u command-line tool at {dev.cli} is not an executable file")
    # `available()` cannot tell a CLI that runs and exits non-zero, or prints
    # non-JSON, from a device that is off, so both land in this skip.
    if not dev.available():
        where = f" at {dev.host}" if dev.host else ""
        pytest.skip(f"C64 Ultimate did not answer{where}")
    seen = {dev.read_mem(0xD012, 1)[0] for _ in range(8)}
    assert len(seen) > 1, f"$D012 never moved across 8 reads: {seen}"
