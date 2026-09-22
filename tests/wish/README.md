# wish

Tests for the application in `wish/`: the window, preferences, game folders, the debug log, packaging, the icons and what they credit.

| file | purpose |
|---|---|
| `test_amigabackend.py` | Checks that the FS-UAE probe answers from `/proc/net/tcp` without opening a socket, that `connect()` keeps one socket per emulator run, and that a target whose memory is not a C64's is never handed to the roster, the action bar, Fast Travel or the combat reader, and that the Amiga backend row appears only behind `WISH_EXPERIMENTAL_AMIGA_FSUAE`. |
| `test_appicon.py` | Checks the application icon: that the shipped drawing and exports are the artist's own, the taskbar sizes come off the PNGs, and every `.ico` entry is 32-bit. |
| `test_assets.py` | Checks that every file the program reads at run time is found in a checkout and a frozen build, exists, and is listed in `wish.spec`. |
| `test_debuglog.py` | Checks that the debug log is off until asked for, keeps a crash regardless, and records no absolute path, character name or save byte. |
| `test_debugmode.py` | Checks debug mode's Fast Travel row against a `MemoryTarget`, the addresses written and their order, and how a backend is chosen. |
| `test_editoropensave.py` | Checks the File menu's own copies of the split Open and Save actions and their mnemonics, and that `Ctrl+Shift+S` pops the Save button's own destination menu rather than saving anywhere itself. |
| `test_gamefolders.py` | Checks that the shared disks folder folds into each title's own folder setting and that a title with no folder is not answered with another's. |
| `test_installdesktop.py` | Checks that `wish/installdesktop.py` writes the desktop entry and icon theme entries under a redirected data directory when it finds none, and never stops the window. |
| `test_licenses.py` | Checks that every glyph that ships is credited to the artist the program names in `THIRD_PARTY_LICENSES.md`, and that the Licenses dialog opens. |
| `test_mapscale.py` | Checks that the area map scales to the room it is given, that clicks and popovers follow the scale, and that the window can be made small. |
| `test_nativewatch.py` | Checks that the native message watch is off unless asked for, installs only on Windows and records nothing until asked. |
| `test_packaging.py` | Checks the frozen build's spec, that it makes one executable with the right entry script, and how the subcommands and console streams behave. |
| `test_paths.py` | Checks how a directory search settles on a title's disks and that the title reaches the automapper and its backend rather than being re-defaulted. |
| `test_preferences.py` | Checks File > Preferences: the precedence of flag, setting and environment, the report of what it found, and remembered folders. |
| `test_taskbaricon.py` | Checks that the window icon is the artist's committed PNG scaled down. |
| `test_windowslayout.py` | Checks the window and dialog layout rules that only broke on Windows, with the screen, frame and style faked. |
| `test_wish.py` | Checks the one-window application headless: backends and their probes, the session, the status line, the tabs and the import rules. |
| `test_wronggame.py` | Checks that the window notices a machine running a different game from the one it believes and refuses Level up and Fast Travel. |
