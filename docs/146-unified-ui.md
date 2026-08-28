# Consolidate UI into a Single Qt Designer File (Revised)

## Goal

One `wish/window.ui` that defines the entire application layout. Opening it in Qt Designer shows the same window a user sees. All panels, cards, buttons, and fields are visible and repositionable. Only dialogs (preferences, import, export, parts picker, note editor, add-item) keep separate `.ui` files.

Standalone entry points (`python -m editor`, `python -m automap`) are dropped.

## Current State

19 `.ui` files across three packages. The three main windows (`wish/window.ui`, `automap/window.ui`, `editor/character.ui`) nest as `QMainWindow`s-inside-tabs. The automap's panels are loaded from 8 separate `.ui` files and assembled in code. `editor/character.ui` (50KB) is already monolithic — the template to generalise.

---

## What Goes into the Unified `.ui`

### Everything inlined — pre-created at maximum capacity

| Element | Count | Today | After |
|---|---|---|---|
| CharacterCard | 8 max (party slots) | Created in a loop by `RosterPanel._card()` | 8 `QFrame`s in the `.ui`, hidden/shown by code |
| HP Bar per card | 1 per card = 8 | Created in `CharacterCard.__init__` | 8 promoted `Bar` widgets in the `.ui` |
| XP Bar per card | 3 per card = 24 | Created in `CharacterCard.__init__` | 24 promoted `Bar` widgets in the `.ui` |
| Action buttons | 5 (Heal, Store, Restore, Identify, Clear QF) | Created in a loop by `ActionBar.__init__` | 5 `ElidingButton`s in the `.ui` (promoted) |
| FastTravelBar | 1 | From `fasttravelbar.ui` | Inlined |
| BottomStrip labels | 4 (`where`, `clock`, `area`, `effects`) | From `bottomstrip.ui` | Inlined as `ElidingLabel`s (promoted) |
| NotesPanel | 1 (`heading` + `QListWidget`) | From `notes.ui` | Inlined |
| CommissionsPanel | 1 (`heading` + scroll + `completed` label) | From `commissions.ui` | Inlined |
| MessagesPanel | 1 (`heading` + `QListWidget`) | From `messages.ui` | Inlined |
| RosterPanel frame | 1 (`heading` + scroll + column layout) | From `roster.ui` | Inlined |
| ActionBar frame | 1 (grid + `watch_box` + `note`) | From `actionbar.ui` | Inlined |
| Editor form | 1 | From `character.ui` (50KB) | Absorbed verbatim |
| SpellbookEditor | 1 (`QListWidget`) | From `spellbook.ui` | Inlined (just a `QListWidget`) |
| MemorisedEditor | 1 (list + combo + buttons + label) | From `memorised.ui` | Inlined |

### What stays as promoted widgets

These are custom-painted widgets with no child layout to design — they draw via `QPainter`. They appear as labelled rectangles in Designer, which is correct since there is nothing to rearrange inside them:

| Widget | Base class | Header | Instances |
|---|---|---|---|
| `Bar` | `QWidget` | `automap.panel` | 32 (8 HP + 24 XP) |
| `IconRow` | `QWidget` | `automap.panel` | 16 (8 conditions + 8 quickfight) |
| `ElidingButton` | `QPushButton` | `automap.panel` | 5 action buttons + 2 FT buttons |
| `ElidingCheckBox` | `QCheckBox` | `automap.panel` | 1 (`watch_box`) |
| `ElidingComboBox` | `QComboBox` | `automap.panel` | 1 (FT destination) |
| `ElidingLabel` | `QLabel` | `automap.panel` | 4 (bottom strip) + card labels |
| `RosterView` | `QTableView` | `editor.rosterview` | 1 |
| `EffectsView` | `QTableView` | `editor.effects` | 1 |
| `IconEditor` | `QWidget` | `editor.iconwidget` | 1 |

> [!NOTE]
> `SpellbookEditor` and `MemorisedEditor` are no longer promoted widgets — their content (a `QListWidget`, a `QComboBox`, two buttons, a label) is inlined directly into the unified `.ui`. The Python classes become controllers that operate on those widgets by `objectName`.

### What stays as separate `.ui` files (6 dialogs)

| File | Why |
|---|---|
| `automap/noteeditor.ui` | Popup dialog |
| `editor/dosimport.ui` | Modal dialog |
| `editor/exports.ui` | Modal dialog |
| `editor/inventory.ui` | Modal dialog ("Add item") |
| `editor/partspicker.ui` | Modal dialog |
| `wish/preferences.ui` | Modal dialog |

---

## Unified `.ui` Structure

```
QMainWindow "WishWindow"
├── QMenuBar (empty — built in code)
├── QStatusBar "statusbar"
└── QWidget "centralwidget"
    └── QVBoxLayout (margins=0)
        └── QTabWidget "tabs"

            ═══ Tab 0: "Automapper" ═══════════════════════════
            QWidget "tab_automap"
            └── QGridLayout "automap_grid"
                ├── (0,0) QWidget "automap_roster"  [fixed width 270]
                │   └── QVBoxLayout
                │       ├── QLabel "automap_roster_heading" [bold, "Party"]
                │       └── QScrollArea
                │           └── QWidget
                │               └── QVBoxLayout "automap_roster_column"
                │                   ├── QFrame "card_0"  ← CharacterCard layout
                │                   │   └── QVBoxLayout
                │                   │       ├── QHBoxLayout (name + conditions + combat)
                │                   │       │   ├── QLabel "card_0_name" [bold]
                │                   │       │   ├── IconRow "card_0_conditions" [promoted]
                │                   │       │   ├── spacer
                │                   │       │   └── QLabel "card_0_combat" [8pt]
                │                   │       ├── QHBoxLayout (class + quickfight + level_up)
                │                   │       │   ├── QLabel "card_0_klass" [8pt]
                │                   │       │   ├── spacer
                │                   │       │   ├── IconRow "card_0_quickfight" [promoted]
                │                   │       │   └── QPushButton "card_0_level_up" [8pt]
                │                   │       ├── QVBoxLayout "card_0_bars"
                │                   │       │   ├── Bar "card_0_hp" [promoted]
                │                   │       │   ├── Bar "card_0_xp_0" [promoted]
                │                   │       │   ├── Bar "card_0_xp_1" [promoted]
                │                   │       │   └── Bar "card_0_xp_2" [promoted]
                │                   │       ├── QLabel "card_0_readied" [8pt]
                │                   │       └── QLabel "card_0_effects" [8pt]
                │                   ├── QFrame "card_1" ... (same structure)
                │                   ├── ...
                │                   ├── QFrame "card_7"
                │                   └── vertical spacer
                │
                ├── (0,1) QWidget "map_column" [AlignTop]
                │   └── QVBoxLayout (spacing=4, margins=0)
                │       ├── QStackedWidget "map_stack" [AlignHCenter]
                │       │   (MapCanvas + CombatCanvas added in code)
                │       ├── QWidget "actions_bar" [AlignHCenter]
                │       │   └── QGridLayout "actions_grid"
                │       │       ├── (0,0) ElidingButton "action_heal" ["Heal party"]
                │       │       ├── (0,1) ElidingButton "action_store" ["Store spells"]
                │       │       ├── (0,2) ElidingButton "action_restore" ["Restore spells"]
                │       │       ├── (1,0) ElidingButton "action_identify" ["Identify items"]
                │       │       ├── (1,1) ElidingButton "action_clear_qf" ["Clear quickfight"]
                │       │       ├── (2,0) ElidingCheckBox "watch_box"
                │       │       └── (2,1-2) QLabel "actions_note" [8pt]
                │       ├── QWidget "fasttravel_bar" [AlignHCenter]
                │       │   └── QGridLayout
                │       │       ├── ElidingComboBox "ft_combo"
                │       │       ├── ElidingButton "ft_button" ["Fast Travel"]
                │       │       ├── ElidingButton "ft_back_button" ["Travel Back"]
                │       │       └── QLabel "ft_note" [8pt]
                │       └── vertical spacer
                │
                ├── (0,2) QWidget "automap_side" [maxWidth=460]
                │   └── QVBoxLayout (margins=0, spacing=6)
                │       └── QSplitter "side_splitter" [Vertical]
                │           ├── QWidget "notes_panel"
                │           │   └── QVBoxLayout
                │           │       ├── QLabel "notes_heading" [bold, "Notes"]
                │           │       └── QListWidget "notes_list"
                │           ├── QWidget "commissions_panel"
                │           │   └── QVBoxLayout
                │           │       ├── QLabel "commissions_heading" [bold]
                │           │       ├── QScrollArea "commissions_scroll"
                │           │       │   └── QWidget
                │           │       │       └── QVBoxLayout "commissions_column"
                │           │       │           └── QLabel "commissions_completed" [8pt]
                │           │       └── (Groups/Rows created in code within commissions_column)
                │           └── QWidget "messages_panel"
                │               └── QVBoxLayout
                │                   ├── QLabel "messages_heading" [bold, "Messages"]
                │                   └── QListWidget "messages_list"
                │
                ├── (1, 0-2) QWidget "bottom_strip"
                │   └── QHBoxLayout
                │       ├── ElidingLabel "strip_where"
                │       ├── ElidingLabel "strip_clock"
                │       ├── ElidingLabel "strip_area"
                │       └── ElidingLabel "strip_effects" [8pt]
                │
                └── (2, 0-2) QLabel "strength_label" [8pt, "party strength --"]

            ═══ Tab 1: "Character Editor" ════════════════════
            QWidget "tab_editor"
            └── QVBoxLayout "editor_outer"
                ├── QHBoxLayout "buttons"
                │   ├── QPushButton "button_open"
                │   ├── QPushButton "button_save"
                │   ├── QPushButton "button_save_as"
                │   ├── QPushButton "button_preview"
                │   └── spacer
                ├── QHBoxLayout "header_row"
                │   ├── RosterView "roster" [promoted]
                │   ├── QGroupBox "box_identity" ("Character")
                │   │   └── ... (all identity fields, verbatim from character.ui)
                │   └── spacer "header_slack"
                └── QTabWidget "sheet_tabs"
                    ├── Tab "Stats" → QScrollArea → QGridLayout "sheet_columns"
                    │   ├── box_abilities, box_levels, box_money, box_roster
                    │   ├── box_saves, box_thief_skills, box_combat, box_appearance
                    │   └── box_effects (EffectsView promoted, spans rows)
                    ├── Tab "Inventory" → QScrollArea
                    │   ├── box_inventory (QTableView + add/delete buttons)
                    │   └── box_traits (QTableView)
                    └── Tab "Spells" → QScrollArea → box_spells
                        ├── QListWidget "field_spells_known" (was SpellbookEditor)
                        ├── QListWidget "field_spells_memorised_list"
                        ├── QComboBox "field_spells_memorised_choice"
                        ├── QPushButton "field_spells_memorised_add"
                        ├── QPushButton "field_spells_memorised_remove"
                        └── QLabel "field_spells_memorised_capacity"
```

> [!NOTE]
> **Commission rows** are the one element that stays partially dynamic. The `CommissionsPanel` creates `Group` and `Row` widgets within `commissions_column` at runtime because the number of commissions varies by game state (0–20+). The `.ui` provides the container (`commissions_column` layout) and the static elements (`commissions_heading`, `commissions_completed`, `commissions_scroll`). The rows themselves are lightweight label pairs and are not worth pre-creating at maximum because the maximum is the full commission table (20+ entries) and they would clutter Designer without adding design value — they are single-line text items in a scroll area, not layout elements you'd want to reposition.

---

## Proposed Changes

### Component 1: Build the Unified `wish/window.ui`

#### [MODIFY] wish/window.ui

Grows from 24 lines to ~2500+ lines. Built by:

1. Start with the current `wish/window.ui` skeleton (QMainWindow + QTabWidget).
2. Add `tab_automap` as the first tab page. Inline the grid layout from `automap/window.ui`, replacing placeholder widgets with the actual panel content from each panel's `.ui`.
3. Inline 8 `CharacterCard` frames into the roster column, each with the full widget tree from `card.ui` (name, conditions `IconRow`, combat label, class label, quickfight `IconRow`, level_up button, HP `Bar`, 3 XP `Bar`s, readied label, effects label). Name them with `card_N_` prefixes.
4. Inline the 5 action buttons from `actionbar.ui`'s pattern, plus the watch checkbox and note label.
5. Inline the fast travel row from `fasttravelbar.ui`.
6. Inline the bottom strip's 4 `ElidingLabel`s from `bottomstrip.ui`.
7. Inline notes, commissions, messages panel content from their `.ui` files.
8. Add `tab_editor` as the second tab page. Move the entire content of `editor/character.ui`'s central widget here verbatim.
9. Inline `spellbook.ui`'s `QListWidget` and `memorised.ui`'s widgets directly into the Spells tab.
10. Merge all `<customwidgets>` declarations from all absorbed `.ui` files into one block.

**objectName conventions:**
- Automap card widgets: `card_0_name` through `card_7_name`, `card_0_hp`, `card_0_xp_0`, etc.
- Action buttons: `action_heal`, `action_store`, `action_restore`, `action_identify`, `action_clear_qf`
- Fast travel: `ft_combo`, `ft_button`, `ft_back_button`, `ft_note`
- Bottom strip: `strip_where`, `strip_clock`, `strip_area`, `strip_effects`
- All editor widgets: unchanged objectNames from `character.ui` (`field_name`, `field_race`, `box_abilities`, etc.)

---

### Component 2: Refactor Window Classes

#### [MODIFY] wish/window.py — `WishWindow`

The biggest change. The class takes over all UI logic from both `EditorWindow` and `AutomapWindow`.

**Before:**
```python
self.editor = EditorWindow(save, game_disk, ...)
self.map = AutomapWindow(self.mapper, ...)
self.tabs.addTab(self.map, "Automapper")
self.tabs.addTab(self.editor, "Character Editor")
```

**After:**
```python
self.ui = Ui_WishWindow()
self.ui.setupUi(self)
# Both tabs already exist in the .ui

# Automap: add custom canvases to the stacked widget
self.canvas = MapCanvas(self.state, self)
self.battle_canvas = CombatCanvas(self)
self.ui.map_stack.addWidget(self.canvas)
self.ui.map_stack.addWidget(self.battle_canvas)

# Cards: find the 8 pre-created card frames, wrap in CharacterCard controllers
self.cards = [self._init_card(i) for i in range(8)]

# Action buttons: find by objectName, wire to actions
for action in engine.actions(game=game):
    button = self.findChild(ElidingButton, f"action_{action.name}")
    button.clicked.connect(lambda ...: self.run(action))

# Editor: all widgets are already in the .ui
self._widgets = self._find_field_widgets()  # same scan as today
self._fill_combos()
...
```

#### [MODIFY] editor/window.py → becomes `EditorBinding` mixin/helper

The editor's field-binding logic (`_find_field_widgets`, `_fill_combos`, `_size_fields`, `_compact`, `_weight_columns`, `_wire_dirty`, load/save/flush) is extracted into a class that operates on any root widget:

```python
class EditorBinding:
    """Binds editor fields to goldbox record data. Works on any widget tree."""

    def __init__(self, root: QWidget, ...):
        self.root = root
        self._widgets = self._find_field_widgets()
        ...

    def _child(self, name):
        return self.root.findChild(QWidget, name)
```

`WishWindow` creates an `EditorBinding(self)` for the editor tab. The old `EditorWindow` class is deleted.

#### [MODIFY] automap/window.py → controller logic extracted

The automap's tick/poll/combat/drawing logic is extracted similarly. `MapCanvas` and `CombatCanvas` remain as classes since they are `QWidget` subclasses with `paintEvent`. The window orchestration (timer, polling, combat switching) moves into a controller class or directly into `WishWindow`.

#### [MODIFY] automap/panel.py — `CharacterCard`, `RosterPanel`, panel classes

- `CharacterCard` becomes a controller class (not a `QFrame` subclass). It receives widget references by objectName prefix:
  ```python
  class CharacterCard:
      def __init__(self, root, index):
          self.frame = root.findChild(QFrame, f"card_{index}")
          self.name = root.findChild(QLabel, f"card_{index}_name")
          self.hp = root.findChild(Bar, f"card_{index}_hp")
          self.xp = [root.findChild(Bar, f"card_{index}_xp_{j}")
                      for j in range(3)]
          ...
  ```
- `RosterPanel` becomes a controller managing the 8 pre-created cards:
  ```python
  class RosterPanel:
      def __init__(self, root):
          self.cards = [CharacterCard(root, i) for i in range(8)]
      def show_snapshot(self, snap):
          for i, who in enumerate(snap.characters):
              self.cards[i].show_character(who)
              self.cards[i].frame.show()
          for card in self.cards[len(snap.characters):]:
              card.frame.hide()
  ```

- `BottomStrip`, `NotesPanel`, `MessagesPanel`, `CommissionsPanel` become controllers that find their widgets by objectName in the unified form.

#### [MODIFY] automap/actionbar.py — `ActionBar`, `FastTravelBar`

Same pattern. The action buttons are found by objectName rather than created in a loop. The 5 actions are a fixed set (`actions()` returns exactly 5), so the 5 buttons in the `.ui` map 1:1.

```python
class ActionBar:
    BUTTON_NAMES = ("action_heal", "action_store", "action_restore",
                    "action_identify", "action_clear_qf")

    def __init__(self, root, *, say=None, game=None):
        self.actions = engine.actions(game=game)
        self.buttons = {}
        for action, name in zip(self.actions, self.BUTTON_NAMES):
            button = root.findChild(ElidingButton, name)
            button.setText(action.label)
            button.setToolTip(action.description)
            button.clicked.connect(...)
            self.buttons[action.name] = button
        self.watch_box = root.findChild(ElidingCheckBox, "watch_box")
        self.note = root.findChild(QLabel, "actions_note")
```

#### [MODIFY] editor/spellwidget.py — `SpellbookEditor`, `MemorisedEditor`

These no longer load their own `.ui` files. They become controllers that find their widgets by objectName in the unified form:

```python
class SpellbookEditor:
    def __init__(self, root):
        self.list = root.findChild(QListWidget, "field_spells_known")
        ...

class MemorisedEditor:
    def __init__(self, root):
        self.list = root.findChild(QListWidget, "field_spells_memorised_list")
        self.choice = root.findChild(QComboBox, "field_spells_memorised_choice")
        self.add = root.findChild(QPushButton, "field_spells_memorised_add")
        ...
```

---

### Component 3: Deleted Files

#### `.ui` files absorbed (11):
- [DELETE] `wish/window.ui` (replaced by new unified version — same path, complete rewrite)
- [DELETE] `automap/window.ui`
- [DELETE] `automap/actionbar.ui`
- [DELETE] `automap/bottomstrip.ui`
- [DELETE] `automap/card.ui`
- [DELETE] `automap/commissions.ui`
- [DELETE] `automap/fasttravelbar.ui`
- [DELETE] `automap/messages.ui`
- [DELETE] `automap/notes.ui`
- [DELETE] `automap/roster.ui`
- [DELETE] `editor/character.ui`
- [DELETE] `editor/spellbook.ui`
- [DELETE] `editor/memorised.ui`

#### Generated files no longer needed (13):
- [DELETE] `automap/ui_window.py`
- [DELETE] `automap/ui_actionbar.py`
- [DELETE] `automap/ui_bottomstrip.py`
- [DELETE] `automap/ui_card.py`
- [DELETE] `automap/ui_commissions.py`
- [DELETE] `automap/ui_fasttravelbar.py`
- [DELETE] `automap/ui_messages.py`
- [DELETE] `automap/ui_notes.py`
- [DELETE] `automap/ui_roster.py`
- [DELETE] `editor/ui_character.py`
- [DELETE] `editor/ui_spellbook.py`
- [DELETE] `editor/ui_memorised.py`

`wish/ui_window.py` stays — it is now generated from the unified `wish/window.ui`.

#### Standalone entry points removed:
- [DELETE or gut] `editor/__main__.py`
- [DELETE or gut] `automap/__main__.py`

---

### Component 4: Build System

#### [MODIFY] tools/genui.py

Update `UI_DIRS`:
```python
UI_DIRS = [
    ROOT / "editor",     # dosimport.ui, exports.ui, inventory.ui, partspicker.ui
    ROOT / "automap",    # noteeditor.ui only
    ROOT / "wish",       # window.ui (the unified file), preferences.ui
]
```

No structural change needed — the tool discovers `.ui` files by glob and compiles them. Fewer files means fewer generated outputs.

#### [MODIFY] designer (project root)

```bash
#!/usr/bin/bash
/usr/lib/qt6/bin/designer wish/window.ui
```

---

## Execution Order

1. **Build `wish/window.ui`** — merge all content into one file, test it opens in Designer.
2. **Refactor panel classes** → controllers that find widgets by objectName.
3. **Refactor `EditorWindow`** → `EditorBinding` helper.
4. **Refactor `AutomapWindow`** → controller/mixin.
5. **Rewrite `WishWindow`** to use the unified `.ui` directly.
6. **Delete absorbed `.ui` files, generated `ui_*.py` files, standalone `__main__.py` files.**
7. **Update imports everywhere** — panels, widgets, tests.
8. **Update `tools/genui.py`** — adjust `UI_DIRS` if needed.
9. **Run tests, fix breakage.**

---

## Verification Plan

### Automated Tests

```bash
# Full test suite
python -m pytest tests/ -x -v

# UI compilation check (CI gate)
python tools/genui.py --check
```

### Manual Verification

1. **Open in Designer:** `./designer wish/window.ui`
   - Both tabs visible
   - Automapper tab shows: 8 card frames in the roster column, 5 action buttons, fast travel row, notes/commissions/messages panels in a splitter, bottom strip with 4 labels, strength label
   - Character Editor tab shows: the full form (all group boxes, fields, tables) — same as opening `editor/character.ui` today
   - All promoted widgets appear as labelled rectangles (Bar, IconRow, RosterView, EffectsView, IconEditor)

2. **Rearrange test:** Move `box_combat` to a different grid position in the Stats tab, save, launch the app — the change is reflected.

3. **Launch the app:** `python -m wish` — identical appearance and behaviour.

4. **Card visibility:** Open a save with 4 characters — 4 cards visible, 4 hidden.

5. **Action buttons:** All 5 buttons enabled/disabled correctly based on game state.

6. **Dialogs:** Preferences, Import, Export, Parts Picker, Note Editor, Add Item — all still work.
