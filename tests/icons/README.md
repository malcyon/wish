# icons

Tests for combat icons and portraits: the option tables that compose a figure, the proposal and reverse tables that convert one between ports, and the tools that draw and measure them.

| file | purpose |
|---|---|
| `test_dosfigures.py` | Checks that `tools/icons/dosfigures.py` takes the large-list promotion rule from `IconParts.size_for` instead of keeping its own copy. |
| `test_dosicon.py` | Checks that a DOS character's combat figure converts to eighteen C64 cells that keep two different characters looking different and stay within figures the game's menus can make. |
| `test_iconcorrespond.py` | Checks that the DOS and C64 combat-icon option lists differ in length and order, so a DOS body number is never read as the C64 weapon with the same number. |
| `test_iconpackaging.py` | Checks that the combat-figure proposal table reaches an installed and a frozen Wish, and that a build which has lost it says where it should have been. |
| `test_iconparts.py` | Checks the icon editor's option tables, the set of icons the game can make and the per-title overrides of the DOS and C64 figure tables. |
| `test_iconproposal.py` | Checks that `tools/icons/iconproposal.py` reads its three tables from `iconproposal.yaml` and that every DOS option and EGA colour has a row. |
| `test_iconprovenance.py` | Checks that the DOS writer's byte accounting does not claim an Amiga party's combat figure was read off C64 screen codes. |
| `test_iconredrawn.py` | Checks that `tools/icons/iconredrawn.py` reads both ends of a comparison at run time instead of naming the diverging options or the C64 figure a row uses. |
| `test_iconreverse.py` | Checks that a C64 combat icon reads back into the weapon and head that drew it, and that the reverse table does not re-decide a row the forward table settled. |
| `test_icons.py` | Checks `goldbox/icons.py`'s combat-icon table: where it ends, that an entry splits into screen-code and colour halves, and that a cell with bit 3 clear draws hires rather than multicolour. |
| `test_iconswing.py` | Checks that `tools/icons/iconswing.py` counts and compares the engine's own reads of an icon's second pose, with a fake monitor and a built character set. |
| `test_portraits.py` | Checks that `goldbox/portraits.py`'s head and body tables are found in the game's own files and agree between the C64 and DOS ports. |
| `test_sheetportrait.py` | Checks that only Pool of Radiance's C64 character sheet draws a portrait, and re-derives that from the player's own disks. |
