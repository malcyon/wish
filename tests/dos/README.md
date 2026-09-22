# dos

Tests for the DOS port: the DOS saved game and character record, the DOS record writers, and the tools under `tools/dos/` that drive and read DOSBox.

| file | purpose |
|---|---|
| `test_daxls.py` | Checks that `tools/dos/daxls.py` reads a `.DAX` container built here the way the DOS engine does, and reads the player's own `CBODY.DAX`. |
| `test_dos_savegame.py` | Checks the byte map of the DOS saved game in `goldbox/dos_savegame.py` from both sides of every boundary, on buffers built here and on the player's specimens. |
| `test_dosabilitypair.py` | Checks `tools/dos/dosabilitypair.py`'s offsets against the layout and its staging of an ability pair whose two bytes disagree. |
| `test_dosaffectreads.py` | Checks that `tools/dos/dosaffectreads.py` reads the handler tables, the ids whose node value byte is read, the generic dispel and removal readers, the item-grant forms and the strength-item encoding out of each title's own engine, and pins its pointer tracker on synthetic routines. |
| `test_dosarraywidth.py` | Checks that `tools/dos/dosarraywidth.py`'s lookback window stops at a `retf` and reads Pool of Radiance's cleric spell count correctly. |
| `test_dosbox.py` | Checks `tools/dos/dosbox.py`'s PPM decoding, digests, bar and area readers, pool-slot claiming and save-staging rules without starting an emulator. |
| `test_dosbox_walked.py` | Checks `judge_step` and `run_walked` in `tools/dos/dosbox.py` tell a walk from a wall from a driver that pressed nothing, from recorded readings. |
| `test_dosboxx.py` | Checks `tools/dos/dosboxx.py`'s segmented addressing, chunked memory reads, debugger commands and config against a stubbed DOSBox-X. |
| `test_dosdisk.py` | Checks that the `.d64` disk built from a DOS party reads back through `goldbox.savegame` and `goldbox.c64_codec` as the DOS party's own. |
| `test_dosdropcensus.py` | Checks that the `0x0E6` column of `tools/dos/dosdropcensus.py` reports a former level from the layout's own field name. |
| `test_dosencrecompute.py` | Checks the encumbrance recompute `tools/dos/dosencrecompute.py` reads out of the shipped binaries, on the player's own copy of the archives. |
| `test_dosencsave.py` | Checks which screens make DOS Pool of Radiance rewrite a stored encumbrance, on the saves `tools/dos/dosencsave.py` staged. |
| `test_dosfight.py` | Checks the record offsets and fight verdicts of `tools/dos/dosfightrun.py`, and that its driver answers each bar it recognises. |
| `test_dosfightwatch.py` | Checks that `walk_to_encounter` waits out a frame caught mid-redraw and gives up naming its digest at a bar nobody has labelled. |
| `test_dosgnome.py` | Checks the step grammar of `tools/dos/dosgnome.py` and how it splits a `.SPC` file into records, against the characters it rolled. |
| `test_dosladder.py` | Checks the training-hall routing of `tools/dos/dosladder.py` against the player's `GEO00`, and the records its trainer wrote. |
| `test_doslatercontainer.py` | Checks the Curse and Silver Blades `SAVGAM<slot>.DAT` container built from nothing, on synthetic buffers and on converted C64 specimens. |
| `test_doslatertitles.py` | Checks the DOS record writer for each later title: the field tables, record widths, item and effect files, and the fields only those titles have. |
| `test_dosoutdoor.py` | Checks the four fields `tools/dos/dosoutdoor.py` plants so an indoor saved game loads onto a travel window. |
| `test_dosoutdoorprobe.py` | Checks the route grammar and the seed `tools/dos/dosoutdoorprobe.py` plants before DOSBox runs. |
| `test_dosoutdoorwrite.py` | Checks that the DOS writer places a party on the travel grid with each window's own container and the engine's outdoor wallset. |
| `test_dospod.py` | Checks the step grammar of `tools/dos/dospod.py` and where it finds the Pools of Darkness game directory. |
| `test_dosraces.py` | Checks that each DOS title's race table is the one its game holds and that every shipped record is a race its class may be. |
| `test_dosracialseed.py` | Checks that `tools/dos/dosracialseed.py` reads what the engine seeds by race and how effect 97 adds the constitution band. |
| `test_dosrecordloops.py` | Checks that `tools/dos/dosrecordloops.py` counts a word-stride loop by its entries and not by the bytes it spans. |
| `test_dossavcensus.py` | Checks which saved games `tools/dos/dossavcensus.py` counts and which it excludes as hand-built or never adventured. |
| `test_dossave.py` | Checks the 285-byte DOS Pool of Radiance character record and its item, effect and spellbook files, on synthetic records and the player's specimens. |
| `test_dossavewritemap.py` | Checks that `tools/dos/dossavewritemap.py` reads a title's save map off its writer and that it agrees with the title's `DosContainer`. |
| `test_dosscrollbundle.py` | Checks the item chain a Silver Blades scroll bundle hangs from its 67-byte item, and how `tools/dos/dosscrollbundle.py` walks it. |
| `test_dosshop.py` | Checks the New Phlan shop squares and scripts `tools/dos/dosshop.py` uses, and the record the engine wrote after a purchase. |
| `test_dosslotwatch.py` | Checks that `tools/dos/dosslotwatch.py` stages writable copies of a read-only `--save` and survives a second run into the same directory. |
| `test_dostailcensus.py` | Checks that `tools/dos/dostailcensus.py` does not count a Gateway or Treasures record as a Curse or Pools of Darkness one. |
| `test_dosvmwatch.py` | Checks the translation `tools/dos/dosvmwatch.py` makes from a saved-game word to its VM address, and its writable staging of a save. |
| `test_dosxpaward.py` | Checks the experience-award bytes before a DOS record's portrait against three routes read out of the shipped engines. |
| `test_dualclassdos.py` | Checks how `tools/dos/dualclassdos.py` names the game tree a record came from, and its boundary listing and string search. |
| `test_innateids.py` | Checks that `tools/dos/innateids.py` reads the innate effect ids character creation adds for each race and class out of the engine. |
