# gui

Tests for the scripts under `tools/gui/`, which photograph, measure and validate the window.

| file | purpose |
|---|---|
| `test_livecheck.py` | Checks that `tools/gui/livecheck.py` keeps a validation run out of the player's data directory and map notes, reads the screen from the chips rather than the processor's view, and compares its live cards with the save read cold. |
| `test_shotwindow.py` | Checks that `tools/gui/shotwindow.py` writes a picture of the window and reports its measurements without changing the application's font or outliving the shot. |
| `test_windows_vm_address.py` | Checks that no tracked file names the Windows VM's old address and that the tools connect to the current one. |
