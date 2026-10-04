# gui

Tests for the scripts under `tools/gui/`, which photograph, measure and validate the window.

| file | purpose |
|---|---|
| `test_livecheck.py` | Checks that `tools/gui/livecheck.py` keeps a validation run out of the player's data directory and map notes, reads the screen from the chips rather than the processor's view, and compares its live cards with the save read cold. |
| `test_mapmarker.py` | Checks, over fakes, that `tools/gui/mapmarker.py` fights an outdoor encounter and resumes the walk (or stops on request) and logs `$033D` and the mapper's window and heading around each press. |
| `test_shotwindow.py` | Checks that `tools/gui/shotwindow.py` writes a picture of the window and reports its measurements without changing the application's font or outliving the shot. |
| `test_windowbuttons.py` | Checks that `tools/gui/windowbuttons.py` lists every button, blocks a disabled or hidden one, answers a question Yes or No and the spell dialog by label, and returns the Messages panel's new lines. |
| `test_windows_vm_address.py` | Checks that no tracked file names the Windows VM's old address and that the tools connect to the current one. |
