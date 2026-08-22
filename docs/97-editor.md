# The character editor — plan

**Status: built.** `wish [SAVE.D64]`, on the Character Editor tab of the one
window (`python -m editor` still opens it alone). This document is the design;
it is kept because it records why the editor is shaped the way it is.

A PyQt6 desktop editor over the same `por/` library the CLI uses. It opens a
`.D64` save or a `.chr` export, shows a character sheet, and writes the disk
back. It **never talks to VICE** — that promise is what keeps it a file tool,
and it is why the live automapper is a separate `automap/` package.

---

## The `.ui` file is the layout, and it is meant to be edited

The form is `editor/character.ui`, a Qt Designer file **compiled to Python** by
`tools/genui.py`, which wraps `pyuic6`:

```
editor/character.ui   --pyuic6-->   editor/ui_character.py
```

That matches how everything else generated in this repo works — `gendocs.py`,
`genitems.py`, `genspells.py`, `genmaps.py` — and it means the generated module
can be read, and gives autocompletion for every widget on the form.

**The loop is: open `character.ui` in Designer, drag fields around, save,
restart the editor.** `editor/window.py` compares mtimes at startup and
regenerates when the `.ui` is newer than the `.py`, so there is no separate
build step to forget and no way to run a stale form. `tools/genui.py` exists for
CI and for building a wheel, where `pyuic6` should not be a runtime dependency.

Both routes were tested before choosing. Runtime `uic.loadUi` also works and
also resolves promoted widgets, so this is a preference rather than a
constraint: codegen was picked because it is what the project does everywhere
else, and because a generated file that can be read beats one that cannot.

**Nothing about the binding below depends on the choice.** Widgets are found
with `findChild(QWidget, name)` on the built form, which behaves identically
whether the form came from `loadUi` or from `setupUi`.

**Widgets bind to record fields by `objectName`.** A widget called
`field_strength` is bound to the `strength` entry in `por/layout.py`; one called
`field_thac0_base` to `thac0_base`. Nothing in the code knows where on the form
a field sits, so **rearranging in Designer needs no code change at all**. The
binder walks the form once at startup:

```python
for field in LAYOUT.fields:
    widget = self.findChild(QWidget, f"field_{field.name}")
    if widget is not None:
        bind(widget, field)
```

Consequences worth stating, because they are what make this work:

* A field with no widget is simply not shown. Adding one to the form is enough
  to expose it — no registration list to update.
* A widget with no matching field is a hard error at startup, not a silent
  no-op. A typo in Designer should be loud.
* Widget *type* decides the editor: `QSpinBox` for numbers, `QLineEdit` for the
  name, `QComboBox` for race/class/alignment (populated from the game's own
  tables in `docs/40-memory-map.md`), `QCheckBox` for bit flags.
* **The dropdowns follow the open title.** Race and the class bitmask are
  not the same list in every game -- Silver Blades' human is 6 where Pool of
  Radiance's is 7, and Krynn's races are a different list altogether -- so
  the boxes are refilled from `editor/enums.py::tables_for(game)` on every
  open. A code the title does not name, like Curse's 6, shows as its raw
  number rather than under a name we would be guessing at.
* **Width comes from the layout too.** The kind and the byte count give the
  widest value a field can hold -- `255` for a `u8`, `65535` for a coin count,
  `-128` for a thief skill, twenty characters for the name -- and the box is
  sized to that, so a field added to the form later is right without anybody
  sizing it. `editor/binding.py::widest_text`.

Qt Designer is installed: `/usr/lib/qt6/bin/designer` (there is no `designer6`
on the PATH, and `designer -v` opens the GUI rather than printing a version).
`pyuic6` ships in the venv.

**Placing the icon widget in Designer** is the one non-obvious step: drop a
plain `QWidget` on the form, right-click it, choose *Promote to…*, and enter
class name `IconEditor` with header file `editor.iconwidget`. It then behaves
like any other widget and can be moved and resized freely. Verified working
through both `pyuic6` and `loadUi`.

---

## The sheet is one page of boxes

The first pass buried sixty-odd fields behind nine inner tabs, and that was
wrong: you could not see a character. `QGroupBox`es on a `QScrollArea` replaced
them -- Character, Abilities, Combat, Experience and levels, Thief skills,
Money, Appearance, Inventory, Item traits, Active effects, Spells -- two columns
of form boxes with the wide ones spanning the width beneath. A group box draws a titled border, which is
the delineation the tabs were standing in for, and Designer treats it like any
other container, so the rearrange-in-Designer loop is untouched.

**A box with nothing in it that applies is hidden**, from the class bits:
`box_thief_skills` needs bit 4 and `box_spells` needs bit 1 or 2. A fighter
shown eight thief-skill zeros invites somebody to type in them. Hiding is a
display decision only -- the bytes behind a hidden box are written back
untouched, which
`tests/test_editor.py::test_a_hidden_box_is_still_written_back_untouched` pins.

## Opening and saving

Two buttons on the form, `button_open` and `button_save`, wired to `QAction`s so
the menu and the shortcuts (`Ctrl+O`, `Ctrl+S`, `Ctrl+Shift+S`) share one
implementation. Named, so Designer can move them like anything else.

**Open** is a `QFileDialog` filtered to `*.d64` plus all-files. Only disk images
are offered: a `.chr` export is a file *inside* a D64, not on the host, so there
is nothing else to pick.

**Save writes back to the file you opened.** No forced new filename, no
`-EDITED` suffix. *Save As* opens the dialog if you want a copy; plain Save does
not ask.

That is a deliberate departure from the CLI, which **refuses** to write over its
input (`tools/wish.py`, "--output must differ from the original save"). The CLI
is a batch tool where clobbering the input is nearly always a mistake; an editor
with the file open in front of you is the opposite case. But the departure has
to be paid for:

**Saving must be atomic.** `D64.save` today is a plain truncate-and-write:

```python
def save(self, path):
    with open(path, "wb") as fh:
        fh.write(self._data)
```

Interrupt that -- crash, full disk, power cut -- and the save disk is destroyed,
with no copy anywhere. Change it to write a temporary file beside the target,
`fsync`, then `os.replace` over the original, which is atomic on POSIX. The CLI
gets the same protection for free, and no caller changes.

**Back up on every save.** Before each overwrite, copy the file as it currently
stands to a timestamped backup:

```
PORSAVE11.D64
backups/PORSAVE11.D64.2026-08-20T09-14-32
```

Not a single `NAME.bak` overwritten each time. A corrupt edit often is not
noticed until the game is booted, by which point you may have saved twice more,
and a one-deep backup would already have been overwritten with the damage. Depth
is the whole value.

A D64 is 171 KB, so twenty backups cost 3.4 MB. Keep the most recent **20** per
file and prune the oldest; make the count a preference for anyone who wants
more.

Two rules that keep the backups meaningful:

* **A save that changes nothing writes nothing** -- not the disk, not a backup.
  Compare the bytes first and report "no changes" instead. Every backup on disk
  then corresponds to a real edit.
* **Save As to a new filename makes no backup**, because there is nothing yet to
  lose.

If the directory holding the save is not writable, fall back to
`~/.local/share/wish/backups/` rather than failing the save. Worth being aware
that this project's own working rule is never to write to
`/home/donald/c64/Pool of Radiance Disks/` -- that rule governs scripts and
agents, not a person deliberately editing their own save through the editor, but
the fallback means a read-only disk directory still cannot cost you a save.

**No modal diff on save.** An editor that interrogates you every time you press
Ctrl+S is an editor you stop pressing Ctrl+S in. Save just saves, and the status
bar reports what happened ("wrote 3 changed characters to PORSAVE11.D64").
*Preview changes…* is a separate action for when you want it, and it renders the
same text `--dry-run` already produces.

The window title carries the open file and a dirty marker; closing with unsaved
changes prompts.

The game disk for item and spell names is found the way the CLI finds it --
`--game-disk`, then `$POR_GAME_DISK`, then any game disk of the save's own
title beside it -- `POOL*.D64` for Pool of Radiance, `CURSE*.D64` for Curse --
and the status bar says whether names are available, because a save opened
without one shows items as bare numbers and that should not look like a bug.

---

## The roster, and picking who to edit

The window is master-detail: a **roster strip** across the top, the character
sheet below it. Click a character, the sheet fills with that character. The
strip is sized to its rows -- eight at most -- and the rest of the height goes
to the sheet.

**The game's own party list is three columns** -- name, armour class, current
hit points, with the hit points coloured when current is below maximum --
established by disassembling all 64 call sites into the string printer while
looking for a status field. The editor shows **five**: mirroring the game was
right for recognising the party, but here you are choosing who to work on, and
"the dwarf fighter" is how you think of them.

| column | where it comes from |
|---|---|
| name | record `0x000`, the slot in `SAVEDGAME0` |
| race | record `0x072` |
| class | record `0x0EB`, the bitmask the game itself reads |
| AC | `SAVEDGAME1` roster block `+0x0F`, as `60 - AC` |
| HP | roster block `+0x19`, against `hp_max` at record `0x076` |
| NPC | record `0x0B8` bit 7 |

Note the AC and HP columns come from **`SAVEDGAME1`, not the character record**
-- they are the only place those live in a save. The editor therefore has both
files open at once, which `por/savegame.py` already models with `SaveGame0` and
`SaveGame1`.

### Three kinds of file open into the same roster

| file | roster shows |
|---|---|
| a save disk | up to 8 slots; occupied ones only, in slot order |
| a `.chr` export | one row, and the list is inert |
| a **roster disk** | one row per standalone character file on the disk |

The third is real and easy to miss: `PORSAVE10.D64` has **no `SAVEDGAME0` and no
`SAVEDGAME1`** -- it is eight `\x01NAME` files and nothing else. An editor that
assumes a save disk always has `SAVEDGAME0` will fail on it. Detect by what the
directory holds, not by the filename.

For a roster disk and a `.chr` there are no `SAVEDGAME1` blocks, so AC and HP
have nowhere to come from. Show them blank rather than inventing them, and grey
the corresponding sheet fields -- the same read-only machinery as everything
else below.

### Switching characters

The sheet edits an in-memory `CharacterRecord`. Switching rows must **flush the
current record first**, or an edit made and not tabbed out of is silently lost.
Keep a dirty flag per slot, not one for the whole file, so the save dialog can
say which characters changed.

Nothing here is exempt from the Designer rule: the roster is a `QTableView`
called `roster` on the form, so it can be moved, resized, or put in a dock
without touching code. Its model is built in `window.py` and attached by name.

---

## Read-only is derived, not hand-maintained

Three independent reasons a field must not be edited, all computed from data the
project already keeps rather than from a list somebody remembers to update:

| reason | source | shown as |
|---|---|---|
| **The game recomputes it** | `por/derive.py` | read-only, with the computed value |
| **We do not understand it** | `Confidence.UNKNOWN` in `por/layout.py` | read-only, greyed |
| **The write would be dropped** | offset ≥ `0x100` while editing a *save* | read-only, with a note |

The third is the subtle one and it is a real trap: a save slot is **256 bytes**
and a record is 580, so `0x10D`, `0x10E`, `0x10F`, `0x119` and the combat icon
exist in a `.chr` export and nowhere in a save. `wish` accepts an edit to them
and the write goes nowhere. The editor must grey them out when the file is a
save and enable them when it is an export — the same widget, different state.

The first covers armour class, THAC0 and damage bonus. `por/derive.py` already
computes what each *should* be; the editor shows the stored value, shows the
expected one beside it, and flags a disagreement rather than silently
reconciling. That is the same discipline the importer learned the hard way: two
losslessness bugs came from "helpfully" making two fields agree.

`PROBABLE` and `GUESS` fields stay **editable** but carry their confidence in
the tooltip. Refusing to edit them would make the editor useless for exactly the
experiments that promote them.

---

## The combat icon

The requirement: editable, showing the real pixel art, with a colour picker.

### What is known

`por/icons.py` has it: 36 bytes per character in a shared table at `$4BE0`,
split in half — **18 screen codes** then **18 colour values**, C64 colours 0-15.
Confirmed by changing icons in game and diffing; MAGNUS changed only the colour
half.

### What the probe established -- all of it, without an emulator

See [the combat icon is two poses, in multicolour](50-experiments.md).

**The grid is two 3x3 poses stacked**, the glyphs are `CHARPIC00`, and the three
shared multicolour values come from `COM.PREP`: background 11, multicolour 1 is
10, multicolour 2 is 0. `por/icons.py` carries them and `icon_pixels()` returns
the art as a grid of colour indices.

### The widget

`IconEditor(QWidget)`, **promoted in Designer** so it can be placed and moved on
the form like any other widget while living in `editor/iconwidget.py`.

* Draws the 3×6 grid at a large integer zoom (8× gives 192×384), so pixels stay
  crisp.
* Click a cell → a 16-swatch C64 palette popup, using the names already in
  `por/icons.py`. Not `QColorDialog`: the C64 has sixteen colours and offering a
  full colour wheel would let the user pick something the machine cannot show.
* The glyph in a cell is changed from the same menu -- `Glyph 228…` above the
  colours -- opening a scrollable grid of all 253 `CHARPIC00` glyphs, drawn in
  the same multicolour scheme so what you pick is what you get. Changing the
  shape half is what a real icon change does; the diffing showed both halves
  move.
* Emits `iconChanged` so the main window can mark the file dirty.

Editing the icon is only meaningful for a `.chr` export, because the icon lives
at `0x220` — beyond a save slot's 256 bytes. In a save the icons come from the
shared table at `$4BE0`, which the editor writes directly. Both paths exist in
`por/` already (`icon_for_slot`, and `por/yaml_io.py` writes the table), so the
widget can be backed by either.

---

## Structure

```
editor/
  __init__.py
  __main__.py       python -m editor [FILE.D64] -- the editor on its own
  app.py            QApplication wiring, dirty tracking
  files.py          open, save, save-as; atomic replace and the first-save backup
  window.py         builds the form, binds widgets to fields
  roster.py         the party model behind the roster table
  binding.py        objectName -> layout field, and the read-only rules
  iconwidget.py     IconEditor, promoted in Designer
  glyphpicker.py    the CHARPIC00 grid behind a cell's shape
  inventory.py      the sixteen item slots, the table on the form, and the
                    traits of the selected item
  effects.py        the ten active-effect slots at 0x0AD. The namespace is
                    named -- 129 codes in por/traits.py -- so a slot reads
                    "petrifying gaze", and only a code outside the table falls
                    back to "trait <n>"
  spellwidget.py    the spellbook and the memorised list, promoted
  enums.py          race/class/alignment/sex, per title, from por/yaml_io.py
  changes.py        what a save would write, in --dry-run's form
  character.ui      the form -- EDIT THIS in Qt Designer
  ui_character.py   generated from it; do not edit
  palette.py        the sixteen C64 colours as QColor
tools/genui.py      character.ui -> ui_character.py
```

`por/` gains nothing except the shared-colour constants once they are measured.
The editor is a consumer of the library, not an extension of it.

---

## Order of work

1. ~~**The icon probe.**~~ ✅ Done, and it needed no emulator -- `COM.PREP`
   states the colours outright.
2. `binding.py` and the read-only rules, tested headless against
   `por/layout.py` — no Qt needed to assert that `armour_class` is read-only
   because `derive.py` computes it, and that `0x119` is read-only for a save and
   editable for an export.
3. `roster.py` -- the party model, headless-testable: open each of the three
   file kinds, list who is in them, and report AC and HP where a `SAVEDGAME1`
   exists. `PORSAVE10.D64` is the specimen that proves the roster-disk path.
4. `character.ui` with a first pass at the sheet, `tools/genui.py`, and
   `window.py` to build and bind it. **Prove the rearrange-in-Designer loop
   works before adding more fields** — move one field in Designer, save,
   restart, confirm it still binds and is still read-only or editable as
   before. Everything after this step assumes that loop is solid.
5. `IconEditor`, promoted into the form.
6. Open and save: the dialogs, atomic replace in `D64.save`, timestamped
   backups with pruning, and the non-modal status report. Do the atomic-write
   change first and on its own -- it protects the CLI too, and it is the one
   part of this plan that can destroy a real save disk if it is wrong.
7. ~~Save, with a dry-run diff.~~ ✅ Done, as a **separate non-modal**
   *Preview changes…*; Save itself still never asks.
8. ~~Items, spells, the glyph picker and the dropdowns.~~ ✅ Done. Items and
   the combat icon live outside the character record -- `$5900 + slot * $100`
   and the shared table at `$4BE0` -- so both are patched into `SAVEDGAME0`
   separately from the slots, and only when they actually changed. The icon
   was not written back at all before that; every colour edit was dropped.

---

## Verification

* `pytest tests/test_editor_binding.py` — the binding and read-only rules, run
  headless. `QT_QPA_PLATFORM=offscreen` makes widget tests work in CI too; the
  automapper's window is already smoke-tested that way.
* Open `character.ui` in Qt Designer, move a field to a different group box,
  save, restart: the field must still bind and still be editable or read-only
  as before, with no code edited and no command run in between. That is the
  requirement this design exists to meet.
  `tests/test_editor.py::test_moving_a_box_in_designer_needs_no_code_change`
  does the same thing to a whole box, in a copy of the form.
* `git status` must be clean after a rebuild — if `ui_character.py` differs, the
  committed copy was stale.
* Render every icon on `PORSAVE11.D64` and compare against a screenshot of the
  party in combat. The icons must match pixel for pixel; if the shared colours
  are wrong this is where it shows.
* Open `PORSAVE11.D64` and confirm the roster lists all six characters with the
  armour class and hit points the game shows -- ROLAND at 5 of 7, wounded and
  coloured. Then open `PORSAVE10.D64` and confirm the roster-disk path lists its
  eight standalone characters instead of crashing on a missing `SAVEDGAME0`.
* Edit a field, click another character, click back: the edit must still be
  there. That is the flush-before-switch bug, and it is the easiest one to ship
  by accident.
* **Round-trip in place**: open a save, change nothing, press Save, and assert
  the file is byte-identical to what it was. This matters more now that Save
  overwrites -- a losslessness bug used to cost you a new file, and now it costs
  you the original.
* Kill the process mid-save (or point it at a full filesystem) and confirm the
  original is intact and the temporary file is the only casualty.
* Save three times with a real edit between each; confirm three backups exist,
  newest last, and that the oldest still restores the state before the first
  edit. Then save a fourth time with nothing changed and confirm **no** fourth
  backup appears.
* Save twenty-one times and confirm the oldest backup is pruned, not the newest. The same losslessness bar the CLI holds, and the editor must
  not weaken it.


---

## Open tasks

Everything below the icon picker landed; see
[the editor fixes report](../work/reports/editor-fixes.md) for what each one
does now. In short: the roster carries race and class and is sized to its rows,
every box is as wide as the widest value its bytes can hold (derived from
`por/layout.py`), `Identity` is `Character`, the item column fits the longest
of the 163 names the game disks carry, and two tables joined the sheet -- the
selected item's traits, and the ten active-effect slots at `0x0AD`.

`0x0AD` is *not* a racial trait mask, which is what it was called here for a
while. It is a list of active effect codes, seeded per race by `GEN $0BF3` from a
table indexed by the race byte -- so an elf is born carrying 107 and a half-elf
124, and every other race is born with an empty block.

### The combat icon picker — done

**It now offers a weapon and a head, which is what the game offers.** The old
picker put every glyph in `CHARPIC00` into each of 18 cells and would happily
build a figure with two heads.

`SPELLN64` on disk 3 is the game's own icon editor and `SPELLE64` its data.
`por/iconparts.py` reads both — the counts and table addresses come out of the
overlay at `$B0DA`/`$B0DE` rather than being hardcoded — and
`editor/partspicker.py` is the dialog over it: two lists, every entry rendered
as the icon it would produce, plus the SIZE control the game has.

The reachable set is **15328 shapes**. Not 805: a weapon change preserves the
head cells, and SIZE is never written back to `0x099`, so sizes can be mixed.
Of the 11 distinct icons on our disks only 6 are a plain (weapon, head) pair
and all 11 are inside the closure — a product model would have rejected five
real icons. Written up in `docs/50-experiments.md`.

**Still free-form: colour.** The COLOR menu offers one colour per part class,
and `colour[cell] = C[class] | (8 if bit 7)` reproduces 103 of our 104 icon
slots. `IconParts.colours_for` implements it and the picker keeps colours legal
as the shape changes, but the right-click menu still sets a single cell. That
is the remaining way to build something the game would not.

