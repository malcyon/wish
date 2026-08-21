"""Presentation code shared by the editor and the map.

Neither package owns it. `automap/` talks to a running machine and `editor/`
must never do so -- `tests/test_wish.py::test_editor_imports_nothing_live`
greps every file in `editor/` for the word `automap` to keep that honest. Icon
drawing is pure geometry and belongs to both, so it lives here rather than
forcing the editor to import from a package named after the emulator.
"""
