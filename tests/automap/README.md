# automap

Tests for the live automapper in `automap/`: its map model and geometry, the party and combat views, the combat log, the panels and the live actions, run against `MemoryTarget` and synthetic screens with no emulator.

| file | purpose |
|---|---|
| `test_actions.py` | Checks the live actions (healing, identifying, levelling, the trainer flags and re-entry) through the addresses they write to a `MemoryTarget`. |
| `test_automap.py` | Checks the automapper's map model, sight and wall geometry, party panel and notes against recorded machines built from the saved-game fixtures. |
| `test_automapbanks.py` | Checks that the screen address, the bitmap test and the status line are read from the memory the processor sees during a load, and that a poll still costs one resume. |
| `test_busguard.py` | Checks that `automap/busguard.py` reads `$DD00` before a tick, holds the tick off while the bus is busy and cannot hold it off for ever. |
| `test_c64machine.py` | Checks the per-title live addresses of `automap/c64.py`, that the three titles nobody has run answer none, and that every action refuses on them. |
| `test_columns.py` | Checks that the automapper's three columns open at their old widths, can be dragged wider or shut, and are remembered across a restart. |
| `test_combat.py` | Checks the combat view against a composed arena: what it reads, how the map, bars and conditions draw, and what a click lands on. |
| `test_combatlog.py` | Checks the combat log against synthetic screens: how a message window is read, deduplicated, split into messages and rounds, and shown with its dice. |
| `test_commissions.py` | Checks the decoder for the City Council's ledger flags and the panel that draws the commissions. |
| `test_commissions_data.py` | Checks what the ledger's entries mean against the shipped scripts and disks: which keep a marker, which is dead and which two scripts share one address. |
| `test_conditionbadges.py` | Checks that the roster card shows a badge for each effect it belongs to and no other, keeps its height with every badge lit, and credits every glyph. |
| `test_issue286a2.py` | Checks that a live tick makes four reads, and twelve on every fifth tick, from a machine standing in New Phlan. |
| `test_latercombat.py` | Checks that a fight in Curse or Silver Blades is read at those titles' own addresses and that the reader as it stood finds none. |
| `test_marching_order.py` | Checks that the automapper and the editor list the party from the highest occupied slot down, including across a gap in the slots. |
| `test_messages_panel.py` | Checks that the Messages panel follows the newest line only while the reader is at the bottom. |
| `test_panel.py` | Checks that a roster card keeps its classes, level and Level up button in the width its column gives it, however many badges are lit or how large the font. |
| `test_pertitle_live.py` | Checks that the roster card's badges, class and experience bar come from the open title's tables rather than Pool of Radiance's. |
| `test_shading.py` | Checks the three ways solid rock is shaded on the combat map: anchored to the square, joined across neighbours and still legible when the cell shrinks. |
