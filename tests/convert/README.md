# convert

Tests for converting a character or a save between ports and titles: the neutral record, each port's codec, and the conversion tools and window code.

| file | purpose |
|---|---|
| `test_amigalatericonconvert.py` | Checks that an Amiga Curse or Silver Blades combat figure is reported as converted and composes a legal C64 figure, on the player's specimens. |
| `test_amigaporiconconvert.py` | Checks that `write_por` writes a given combat figure and that a C64 or DOS party converted to Amiga Pool of Radiance arrives with its own. |
| `test_amigaporcharacters.py` | Checks that `read_por_characters` reads an Amiga Pool of Radiance slot's character files in order, stops at the first missing one and refuses a bad slot letter. |
| `test_amigatoc64.py` | Checks an Amiga Pool of Radiance save slot becoming a C64 one: the party's square, area, clock and quest flags. |
| `test_amigatodos.py` | Checks the writing half of an Amiga Pool of Radiance save becoming a DOS save folder. |
| `test_c64abilityaltered.py` | Checks that the flag a score altered in the modification screen sets crosses between the C64's own control-byte bit and the byte DOS and the Amiga keep it in, both ways and on the player's save disks. |
| `test_c64classcode.py` | Checks that `goldbox.c64_codec.read` repairs a class code the C64 engine stopped maintaining after training. |
| `test_c64identity.py` | Checks that the DOS identity byte crosses into the C64 identity pair and back. |
| `test_c64noportrait.py` | Checks that a C64 character with no sheet portrait is read as having none rather than as the menu's first head. |
| `test_c64strengthflag.py` | Checks that a converted character keeps the C64 strength-bonus flag its bonus to hit and damage depends on. |
| `test_c64thac0.py` | Checks that a converted character's THAC0 on the C64 sheet is computed from the C64's own tables rather than copied. |
| `test_c64traitslots.py` | Checks which effects from both neutral effect lists reach the C64's ten trait slots. |
| `test_convert.py` | Checks `editor.convert`'s registry: which directions the library can write whole, as round trips, and the dialog built on it. |
| `test_convertmatrix.py` | Checks that the bytes `File ▸ Convert…` writes for each of the six DOS and C64 directions equal what the library's own entry point writes. |
| `test_convertrun.py` | Checks that `tools/convert/convertrun.py` stubs the three message boxes a successful C64 write can reach. |
| `test_curseconvert.py` | Checks a DOS Curse of the Azure Bonds save converting to a C64 one, both the record and the container. |
| `test_dosclasscode.py` | Checks that `goldbox.dos_codec.write` repairs a class code that contradicts the record's own classes. |
| `test_dosconversionarea.py` | Checks that a conversion writes the area a C64 party stands in, including the areas whose script loads no map. |
| `test_dosconvert.py` | Checks a DOS Pool of Radiance save converting to a C64 one field by field: no loss on the way in and every drop reported. |
| `test_dosimport.py` | Checks the helpers `editor/dosimport.py` gives the convert dialog: `rehearse`, `pane_text`, `name_warnings` and `log_unshown_losses`. |
| `test_dosthac0floor.py` | Checks that a C64 magic-user of level 1-5 arrives in DOS holding the engine's own THAC0 20, and that `dos_engine_thac0` matches the census rule over the player's own tables. |
| `test_dosregainedclass.py` | Checks that a regained dual-classed C64 character crosses to DOS with its old class bit and level slot right. |
| `test_doswriter.py` | Checks that the DOS writer is the reader's inverse: a neutral character becomes a 285-byte record and reads back. |
| `test_droptext_platform_neutral.py` | Checks that a drop line written while reading the source names no destination it does not yet know. |
| `test_namefit.py` | Checks `editor.saveplan.fit_names` and `name_width`: a name over the destination's width is named rather than cut, a chosen replacement is written with nothing left to clamp, and every title's width per port. |
| `test_neutral.py` | Checks the neutral character record and the codecs around it: what is written unchanged, what is reported and what is refused. |
| `test_podconvert.py` | Checks converting a DOS Pools of Darkness character to the Amiga and back. |
| `test_podsave.py` | Checks `goldbox.dos_codec.pod_savgam`/`new_pod_save_from` and `editor.convert.PodAmigaToDos` writing a Pools of Darkness DOS save from an Amiga saved game, behind `WISH_EXPERIMENTAL_POD_CONVERT`. |
| `test_poolwisdombonus.py` | Checks that a converted DOS Pool of Radiance cleric with wisdom 12 or 13 gets the C64's own first-level spell count. |
| `test_rewrite.py` | Checks that a DOS or Amiga character written back with nothing edited is byte-identical and that an edited field lands while the engine's own bytes survive everywhere else, on generated records and on every specimen. |
| `test_runningeffects.py` | Checks that a spell with time left keeps its minutes going DOS to Amiga and back, in every Amiga title, on both byte orders. |
| `test_ssbconvert.py` | Checks a DOS Secret of the Silver Blades save converting to a C64 one, the twin of the Curse file. |
| `test_toamigapor.py` | Checks that `tools/amiga/toamigapor.py` writes a C64 or DOS party into an Amiga Pool of Radiance save slot. |
| `test_toamigapor_marching_order.py` | Checks that a C64 party converted to an Amiga disk arrives in the Amiga's marching order. |
