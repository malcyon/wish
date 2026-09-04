"""`tools/dosvmwatch.py`'s translation from the file's contiguous names to the VM's addresses.

`docs/141-dos-savegame.md` names the 2560 words of `SAVGAM<slot>.DAT` as
`$4900` + word index.  The engine's own classifier (`GAME.OVR:0x7BCE`) puts
words 1024-2047 at `$6B00`-`$6EFF` and 2048-2559 at `$9700`-`$98FF`, which
is what `docs/163-dos-vm-address-map.md` rests on; a translation off by one
block would send a `BPM` to the wrong word and name the wrong script
register.  No emulator here: the arithmetic alone.
"""

import pytest

from tools.dosvmwatch import vm_address


@pytest.mark.parametrize("named, vm", [
    (0x4900, 0x4900),   # the first block is at its own address
    (0x49C4, 0x49C4),   # the travel y
    (0x4CFF, 0x4CFF),   # the last word of the first block
    (0x4D00, 0x6B00),   # the second block starts at $6B00
    (0x4FD2, 0x6DD2),   # the rest-interruption interval
    (0x4FD3, 0x6DD3),   # and its chance
    (0x507A, 0x6E7A),   # the overland script's loop register
    (0x507D, 0x6E7D),   # the register ECL00's prologue copies into $49FD
    (0x5082, 0x6E82),   # the departing square's attribute
    (0x50FF, 0x6EFF),   # the last word of the second block
    (0x5100, 0x9700),   # the third block starts at $9700
    (0x5200, 0x9800),   # the name workspace
    (0x52FF, 0x98FF),   # the last word in the file
])
def test_each_block_lands_at_the_address_the_classifier_uses(named, vm):
    assert vm_address(named) == vm


def test_an_address_below_the_array_is_refused():
    with pytest.raises(ValueError):
        vm_address(0x48FF)
