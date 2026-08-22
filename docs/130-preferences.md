# Preferences

**Status: built.** `wish/preferences.py`, `File > Preferences…` (`Ctrl+,`).
Donald: *"The 'Finding a game disk' section of the readme worries me. This is
going to cause confusion. I think we need a preferences window under the file
menu … configurations for where wish looks for game disks, as well as the
backend … The backend option should move into the preferences dialog."*

---

## The verdict

* **The dialog holds three things: where the game disks are, which live backend
  to use, and the debug log.** Nothing else. Fog of war and the map's own knobs
  stay on the map, where you change them mid-play.
* **One directory setting, not two.** The editor's game disk and the
  automapper's map disks are the same box of `.D64`s in practice, and the
  editor already expands a named disk into its whole directory. One folder,
  one row in the dialog, both searches fed from it.
* **Precedence, in one sentence: the Game directory setting is the answer**, and
  a command-line option beats it for one run. The environment variables stay
  for the tests and the tools and leave the user documentation.
* **Half the value is the report, not the form.** The dialog says which folder
  is in use, who named it, which titles are in it, how many maps came out, and
  which image the item names came from. A user who types nothing still learns
  what went wrong.
* **The Ultimate's host goes in the dialog; the password does not.** No secret
  is written to a settings file this project tells people to read and hand-edit.
  The dialog shows whether `$POR_ULTIMATE_PASSWORD` is set and nothing more.

---

## 1. The problem, measured

Two searches, three environment variables, one flag each, none of it in the
window.

| | wants | resolved in | order before this |
|---|---|---|---|
| Character editor | a game **disk image** — item names, spell names, the icon charset, the icon option tables | `editor/window.py` `_disk_candidates` | `--game-disk` → `$POR_GAME_DISK` → the open save's own directory → the directory of whatever `--game-disk`/`$POR_GAME_DISK` named |
| Automapper | a **directory** of that title's disks — every `GEO` on them | `automap/paths.py` `disk_candidates` → `locate_disks` | `$POR_DISKS` alone if set, else cwd, `~`, `~/Documents`, `~/Games`, `~/c64`, `~/roms`, `~/Downloads` each × `"<Title> Disks"`, `"<Title>"`, `PoR`, then cwd and `~` |
| Roster's readied item | the same names, again | `automap/live.py` `item_names` | `find_disks(game)`, i.e. the automapper's order |

Three call sites, three orders, no shared function. **CONFIRMED** — read at
`2f0137d`. All three now go through `paths.resolve_disks`, and the roster's
copy is handed the answer rather than searching (`AutomapWindow(disks=…)`).

What the user saw when it went wrong:

| symptom | where | said why? |
|---|---|---|
| items listed as `word 8` | editor tab, inventory table | yes, but named the flag and the env var |
| empty grid, no map | map tab | no — the grid drew and said "looking for the game", which is about the emulator, not the disks |
| `no game disks found, so the map tab will be empty` | **stderr** | only to a terminal. `wish` launched from a desktop icon or an unpacked PyInstaller build printed it to nowhere |

The last row was the whole bug. The diagnostic existed and was good; it was
delivered to a channel a GUI user does not have. Both now say **File >
Preferences…**, in the window.

---

## 2. What went in, and what stayed out

| field | set where | verdict | why |
|---|---|---|---|
| `backend` | was View > Backend, radio group | **in the dialog** | asked for; and it is a once-per-machine fact about your desk, not a play control |
| `interval_ms` | was `--interval` only | **in the dialog**, under the backend | it belongs to the backend (200 ms VICE, 500 ms Ultimate) and is meaningless to touch mid-play. **0 now means "the backend's own"**, which is what the blank-looking spin box says; the default changed from 200 for that reason |
| `diagnostics` | was View > Debug log, forgotten at every restart | **in the dialog**, and remembered — see §11 | Donald asked for both |
| `reveal` | map toolbar toggle, the `fog_box`, and `R` | **stays on the map** | you flip it while walking. A setting you toggle twenty times an hour does not belong behind a menu and a dialog |
| `sight` | nothing — read by the map, written by no UI | **stays out** | it changes what the map draws, same class as `reveal` |
| `geometry`, `window_width`, `window_height` | written on close | **never in the dialog** | remembered state, not a preference; nobody types a window size. See §12 |
| *(new)* `disks` | — | **in the dialog** | the point of the exercise |
| *(new)* `ultimate_host` | was `$POR_ULTIMATE` only | **in the dialog** | see §6 |

**The rule the table applies:** a preferences dialog collects the settings you
set *once*, about this machine. Everything you set *while playing* belongs on
the thing you are playing with.

Still out, for its own stated reason: **which tab opens** (`--tab`). Not asked
for, and the window opens on the map because that is what you have open beside
the game.

---

## 3. One search or two

**One.** The dialog shows one row: *Folder*.

The argument for two is that they are different things — a file for the editor,
a directory for the map — and they need not be co-located. The argument against
is stronger on all three counts:

1. **The editor already treats a named disk as a directory.** `_disk_candidates`
   takes whatever `--game-disk` named, walks up to its parent, and globs the
   whole title from there, because *"the disks come as a set … the icon charset
   and the icon option tables live on different disks."* The editor's real
   requirement is already a directory; the file is an entry point into one.
2. **Neither side wants a specific image.** The editor tries every candidate
   until a read succeeds (`_find_disk`); the map globs all of them and takes the
   first copy of each `GEO`.
3. **Two rows invite the wrong question.** A dialog asking *where are your game
   disks* and *where is your game disk* teaches the user that these are
   different, which is the confusion being fixed.

The case a single folder loses is *"use this exact image for item names"*.
`--game-disk` keeps it, as a flag, which is the right shape for a one-off.

The fallback keeps working and is now *visible*: with the folder empty, the
editor still finds a disk sitting beside the open save, and the dialog reports
that it did and where from.

---

## 4. Precedence

> **The setting in Preferences is the answer.** A command-line option beats it
> for one run; nothing else does.

One function, `automap.paths.resolve_disks(flag, beside, game, settings)`,
returning `(directory | None, source)`. Everything that wants disks calls it:
`automap/__main__.py::default_disks` and `load_maps_titled`, `wish/__main__.py`,
`WishWindow`, and the dialog's own report — which is why the report can name
the source honestly instead of guessing.

| rank | source constant | who uses it |
|---|---|---|
| 1 | `FLAG` — `--disks` / `--game-disk` | scripts, and anyone testing two sets of disks without changing a setting. A person using the window never types it |
| 2 | `PREFERENCE` — **the Game directory setting** | everyone. This is the one that matters |
| 3 | `ENVIRONMENT` — `$POR_DISKS` | the test suite and `tools/`; undocumented for users |
| 4 | `BESIDE` — beside the open save | automatic, and usually right |
| 5 | `SEARCHED` — the candidate-directory search | automatic, `disk_candidates`, unchanged |
| 6 | `NOWHERE` — nothing found | reported as such, in every row |

A folder named by the flag or by the setting **is the answer whether or not it
holds any disks**. Reporting an empty folder as empty beats silently searching
somewhere else, which is the "it is ignoring what I typed" complaint.

`$POR_DISKS` and `$POR_GAME_DISK` keep working, for the tests and the tools,
and are out of the user-facing documentation. `$POR_DISKS` used to
short-circuit the entire search; it keeps that power over the two automatic
searches and loses it to the setting only. **This does not disturb the suite**:
`tests/conftest.py::_isolate_config` points all four config variables at a
`tmp_path`, so no test ever sees a saved preference.

`Settings` is imported **inside** `resolve_disks`, not at module scope:
`automap/config.py` already does `from .paths import config_dir`, and the
reverse import at module level is a cycle. `automap/live.py` does the same.

---

## 5. Feedback in the window

### 5a. The dialog reports before it asks

```
Preferences                                                   [x]

┌─ Game disks ─────────────────────────────────────────────────┐
│  Folder  [ /home/donald/c64/Pool of Radiance Disks   ] [Browse…] [Clear] │
│                                                              │
│  In use   /home/donald/c64/Pool of Radiance Disks            │
│  Set by   this preference                                    │
│  Titles   Pool of Radiance (8 disks) · Curse of the          │
│           Azure Bonds (6 disks)                              │
│                                                              │
│  Leave it empty to search: beside the open save disk first,  │
│  then the usual folders.                                     │
└──────────────────────────────────────────────────────────────┘
```

Three report lines, each answering a question somebody has actually had:

| line | answers | source |
|---|---|---|
| **In use** | "is it even looking where I put them?" | `resolve_disks(...)[0]` |
| **Set by** | "why is it ignoring what I typed?" | `resolve_disks(...)[1]`, plus a note when `$POR_DISKS` or a saved preference was overridden |
| **Titles** | "are these the right disks?" | `paths.titles_in` + a count per `disk_globs` |

It printed three more — **Maps**, **Names** and **Icons**, counting the GEOs
and naming the disks the item names and the icon charset came off. Donald had
them out after the first Windows build ("remove Maps, Names, and Icons"): they
answer questions nobody is asking at the moment of opening this dialog, and the
map tab and the item column answer them where somebody is already looking. The
scan that fed them is gone with them, so the dialog no longer opens every
`D64` in the folder to draw itself.

Failure states are stated as failures, in the same slots: *Titles — none; no
`POOL*.D64` or `CURSE*.D64` here*. The empty answer is more informative than a
missing row.

`report(settings, flag, beside, game)` is a **plain function returning
`(label, value)` pairs**, so what the dialog claims is tested without opening
one. The folder scan is `lru_cache`d on the folder, and typing is debounced by
`SETTLE_MS` (400 ms); Browse and Clear apply at once. No OK button — see §8.

### 5b. Two changes outside the dialog, which are the actual fix

| where | before | now |
|---|---|---|
| map tab, no maps loaded | empty grid; the reason went to stderr | the grid says **"No game disks found, so there are no maps. File > Preferences… to say where they are."** — `AutomapWindow.waiting_text()`, drawn word-wrapped where the map would be. The status line still belongs to the connection: it says "looking for a running game" as it always did |
| editor tab, no game disk | *"pass `--game-disk`, set `$POR_GAME_DISK`, or put a game disk beside the save"* | *"No game disk found, so items show as name-table indices: File > Preferences… to say where the disks are."* Same for the `button_item_add` tooltip |

The stderr line in `wish/__main__.py` stays for the terminal user, and now
names the folder it tried and who named it. It is not the only channel any more.

---

## 6. The backend section

The View > Backend group moved across whole, keeping both of its honest
behaviours:

```
┌─ Live backend ───────────────────────────────────────────────┐
│  (•) Whichever answers                                       │
│  ( ) VICE      [answering]                                   │
│  ( ) Ultimate  [not answering] [unverified]                  │
│                                                              │
│  Ultimate host  [ ultimate64.local            ]              │
│  Password       from $POR_ULTIMATE_PASSWORD — not set        │
│                                                              │
│  Poll every     [ the backend's own (VICE 200, Ultimate 500) ]│
└──────────────────────────────────────────────────────────────┘
```

* **The radios are a view of the window's `QAction`s**, which stay in a
  `QActionGroup` and in no menu. One model, so the preference, the session and
  the dialog cannot disagree — and `label_backends` and `_prefer_backend` moved
  across unchanged rather than being rewritten.
* **Offered but marked.** A backend that is not answering is still selectable:
  you set the preference before you start the emulator as often as after.
  `label_backends()` runs on the dialog's `showEvent` and on every `refresh`,
  not on a timer: `probe()` is a TCP connect, wrong on a poll timer and stale
  if done once at startup.
* **The state is a badge, not more label text.** On Windows the two ran
  together — the style draws a radio button's text tight against its circle,
  and "Ultimate not answering, unverified…" read as one sentence. The label is
  the name; the state and the unverified mark are `QLabel`s with a frame, a
  ground and an ink of their own (`preferences.ANSWERING`, `SILENT`,
  `UNVERIFIED`). Both colours are named on every badge, so a dark desktop theme
  cannot leave dark ink on a dark ground.
* **Unverified stays said**, from `Backend.verified` — in its own badge, whose
  tooltip is still "nobody on this project has the hardware".

### The Ultimate host

`$POR_ULTIMATE` had no UI at all, and this backend is *only* reachable by
naming a host: with nothing set it is never probed and never offered. So the
one control that turns the feature on was invisible.

`Settings.ultimate_host: str = ""`; empty means "not configured", so the
no-probe, no-delay, no-error behaviour for a network with no Ultimate on it is
unchanged.

**How it reaches the backend, and the loose end.** `wish/ultimate.py::configured()`
reads `$POR_ULTIMATE` and nothing else, and that file was outside this task's
file list, so `preferences.apply_ultimate_host()` puts the preference *into the
environment of this process* — one lookup path, and the §4 precedence holds
(the setting first, the user's own value put back when the box is emptied). It
does nothing at all when there is no preference and none was ever applied.
**The tidier fix is four lines in `configured()`**: read `Settings.ultimate_host`
before the env vars, and delete `apply_ultimate_host`. Worth doing next time
that file is open.

### The password — not in the settings file, and not in the dialog

**A password field is the one thing here that must not be stored in
`automap.json` in clear text.** That file is documented to the user as *"one
small JSON file you can read and edit"*, it is in the folder `wish --debug`
writes logs into, and a project whose selling point is that it touches nothing
it should not must not start a habit of writing secrets to a world-readable
dotfile.

| | |
|---|---|
| what the dialog shows | `Password  from $POR_ULTIMATE_PASSWORD — set` / `— not set` |
| what it never shows | the value, or a masked stand-in for it |
| what it never writes | anything |
| what it gains | the diagnostic — *"is the password reaching wish at all?"* — the only question a user actually has here, and the one an env var answers worst |

Why not a keyring: a new runtime dependency, a new PyInstaller hook, a new
failure mode on a headless Linux box with no Secret Service, added for
**hardware nobody on this project owns**. If somebody with an Ultimate reports
that the env var is awkward, add `keyring` behind a `try: import` then.

---

## 7. Where the settings live

Three facts constrain this, and the third is the sharp one:

1. `Settings` is `automap/config.py`, writing `automap.json` under
   `config_dir()`.
2. Donald has that file on this machine already, and it holds a window size he
   would notice losing.
3. **`editor/` may not import `automap/`.** `tests/test_wish.py::test_editor_imports_nothing_live`
   greps every `editor/*.py` for the string `automap` and fails the build. That
   is the project's first architectural decision made mechanical, and this work
   does not get to weaken it.

So `Settings` stays in `automap/`, and the editor gets the folder the way it
already gets a game disk — **handed in by its caller**:

```
EditorWindow(save, game_disk, disks=None)      # a plain str path
```

`wish/window.py` resolves once with `paths.resolve_disks`, passes the directory
to `EditorWindow.__init__`, and calls `EditorWindow.set_disks()` when the
dialog changes it. `editor/window.py` puts `disks` into `_disk_candidates`
between `self.game_disk` and `$POR_GAME_DISK` — matching §4 — and imports
nothing new. The grep test keeps passing, unmodified, which is the point.

Standalone `python -m automap` reaches the same precedence for free, because
`resolve_disks` lives in `automap/paths.py` and `default_disks` calls it.

**The `automap.json` → `settings.json` rename is deferred.** It was argued for
here and it is still cheap (about ten lines in `load()` and one test), but
nothing in the dialog needs it, and `docs/122-release-testing.md` names the old
file in a checklist that was outside this task's scope to edit. Doing it and
leaving that doc stale is worse than doing it later. The argument for doing it
before a `v*` tag still stands.

---

## 8. Files that changed

**Not a Designer form.** `editor/character.ui` is the only `.ui` in the tree,
and `tools/genui.py` hard-codes that one pair of paths. Every other dialog and
panel in this project is hand-written PyQt, and this one re-probes backends and
re-runs a directory search as you type, which is code either way.

| file | change |
|---|---|
| **`wish/preferences.py`** | **new.** `PreferencesDialog(QDialog)`, the pure `report()`, `apply_ultimate_host()`, and the `SHORTCUT` constant |
| `wish/window.py` | `File > Preferences…`; the backend actions live in no menu; `preferences()`/`show_dialog()`; `set_disks`/`reload_disks`/`set_ultimate_host`/`set_interval`; the debug-log indicator; geometry on close |
| `wish/session.py` | `set_interval`, so the dialog can retime a running poll |
| `wish/__main__.py` | resolves once with `resolve_disks` and passes `--disks` down; the stderr text names the folder, the source, and File > Preferences |
| `automap/config.py` | `disks`, `ultimate_host`, `geometry`, `diagnostics`; `interval_ms` default 200 → 0; `remember_geometry`/`restore_geometry`/`clamp_to_screen` |
| `automap/paths.py` | `resolve_disks` and its six source constants |
| `automap/__main__.py` | `default_disks` and `load_maps_titled` call `resolve_disks`; the stderr text |
| `automap/window.py` | `disks=` parameter, `set_maps()`, `no_maps`, `waiting_text()`, the wrapped grid text, geometry only when it is the window |
| `editor/window.py` | `disks=` parameter, `set_disks()`, `_disk_candidates` gains rank 2, `game_disk_found`/`icon_parts_disk` for the report, and the two "no game disk" strings name the dialog |

**No OK/Cancel — a single `Close`.** Every control here applies at once (the
backend menu it replaces already did), and a Cancel would need an undo path
back through `Session.prefer`, a map reload and the editor's item tables.

`QKeySequence.StandardKey.Preferences` resolves on this Linux/Qt 6 build to the
**`XF86Settings` multimedia key** — `QKeySequence(StandardKey.Preferences).toString()`
returns `'Settings'` — so the action would get a shortcut no ordinary keyboard
can produce. `SHORTCUT = "Ctrl+,"`, spelled out. **CONFIRMED**, this tree,
PyQt6 in `.venv`.

### Tests

`tests/test_preferences.py`, 30 of them, and two rules it obeys: **no modal
dialog** (`WishWindow.show_dialog` is the seam; `exec()` is never called) and
**no game data in the repository** (empty files of the right *name*, which is
all a glob can see; the two tests that need real maps and real item names
symlink the player's own disks into a folder no search covers and skip when
there are none).

| what | asserts |
|---|---|
| precedence | all six ranks, with the **source string** checked in each |
| the report | names the folder, the source, the titles with disk counts; states each failure in its own slot; says when `$POR_DISKS` is set and overridden; a flag says "this run only" and names the preference it beat |
| the dialog | the report updates with no OK pressed; clearing goes back to searching; the radios are the window's actions and still write `settings.backend` and call `session.prefer`; "unverified" still said; `&Backend` is gone from View |
| the Ultimate | the host round-trips to the JSON and reaches `configured()`; **no password key in `asdict(Settings)` and no password in the written file** |
| geometry | a resize is remembered and restored; bigger than the screen is cut down; off the edge is brought back; settings from before this still give a size |
| the debug log | remembered across a restart, restored without a modal, and said in the title and the status bar |
| the acceptance case | one folder set in the dialog, item names and maps arrive **without a restart**, and survive a restart |

---

## 9. Verification

The case that decides it: **disks in a folder no search covers, and a user who
has never opened a terminal.** Rows 1–4 are the acceptance test, covered by
`test_one_folder_gets_item_names_and_a_map_without_a_restart`.

| # | do | expect |
|---|---|---|
| 1 | `unset POR_DISKS POR_GAME_DISK`; put the disks in `~/Desktop/porgame/`; launch `wish` from the desktop; open a save | items read `word 8`; map tab empty — **and both say "File > Preferences…"** |
| 2 | File > Preferences, Browse to `~/Desktop/porgame` | report fills in: *Set by — this preference*, *Titles — Pool of Radiance (8 disks)* |
| 3 | Close | items are named **without a restart**; the map tab draws |
| 4 | quit, relaunch from the desktop | still works. Nothing was typed in a terminal at any point |
| 5 | `export POR_DISKS=/somewhere/else`, relaunch | the preference still wins; *Set by — this preference ($POR_DISKS is set and overridden)* |
| 6 | clear the preference, relaunch | *Set by — `$POR_DISKS`*. Donald's own machine, unchanged |
| 7 | `wish --disks /third/place` with a preference set | *Set by — --disks, this run only*; the saved preference is shown and marked unused |
| 8 | point the folder at an empty directory | *Titles — none; no `POOL*.D64` or `CURSE*.D64` here.* No crash, no exception dialog |
| 9 | point it at a directory holding both titles' disks, with a Curse save open | *Titles* lists both; the maps and item names loaded come from **Curse** — the `game` argument is threaded through, not defaulted |
| 10 | `chmod a-w` the config directory, change a preference | dialog works, the change applies for this run, nothing raises (`Settings.save` swallows `OSError`) |
| 11 | point it at a folder of truncated downloads | the map tab says it has no maps. The window stays up: `wish/window.py::load_maps_titled` swallows and logs |
| 12 | set the Ultimate host, no device on the network | *Ultimate* carries a **not answering** badge and an **unverified** one. No timeout stall on the poll timer, no error dialog |
| 13 | `grep -rn automap editor/` | **empty**, and `test_editor_imports_nothing_live` passes |
| 14 | `grep -rn 'password' ~/.config/wish/automap.json` | **empty**, after a session with the dialog open and a password set in the environment |

---

## 10. Wording `README.md` needs

Donald's file — **reported, not written.**

The deleted "Finding a game disk" section should not come back as a list of
three fallbacks. What replaces it, wherever the disks are first mentioned:

> **Where wish looks for the game disks.** Open **File > Preferences** and
> point it at the folder holding your `.D64` images. It tells you what it found
> there — which games, how many maps, which disk the item names came off — so
> you can see it worked without starting the game.
>
> Left empty, wish looks beside the save disk you opened and then in the usual
> places. `--disks` overrides the preference for one run; `$POR_DISKS` is used
> only when the preference is empty.

And in the Ultimate section, replacing step 1's `export POR_ULTIMATE=…`:

> **1. Say where the device is.** File > Preferences > Live backend > Ultimate
> host. There is no discovery: until you name a host this backend is never
> probed, so a network with no Ultimate on it costs nothing. `$POR_ULTIMATE`
> still works and is used when the preference is empty.
>
> **2. Firmware 3.12 and later may require a password.** This one stays an
> environment variable — `$POR_ULTIMATE_PASSWORD` — because wish's settings
> file is plain JSON you are meant to be able to read, and a password does not
> belong in it. The Preferences dialog shows whether it is set.

The "If both are answering" paragraph telling people to edit `"backend"` in the
settings file should point at File > Preferences instead; the JSON keeps
working and no longer needs documenting.

And, for the debug log:

> **Debug log.** File > Preferences > Diagnostics. It stays on until you turn
> it off, including across restarts — so while it is on the window title says
> `[logging]` and the status bar says so too. View > Show log opens the file.

---

## 11. The debug log — remembered, and therefore visible

Donald: *"should move into the preferences dialog and it should persist between
sessions."*

This reverses a deliberate decision whose reason was in the code: *"Off at
every start, and deliberately not remembered: a logging setting that survives a
restart is one you forget is on."* **The concern is real and has not gone
away** — a log that quietly grows for months has no diagnostic value left,
because nobody knows when it started. So the setting persists *with* the
mitigation:

* **The window title carries `[logging]`** while the log is on. That is what a
  screenshot in a bug report shows, and it survives being minimised into a
  window list.
* **The status bar carries a permanent `● debug log on`**, beside the fog-of-war
  box. That is what is on screen whatever the window is doing, including
  full-screen, and it is where this window already puts its standing state.

Both, because they are visible in different situations and neither costs
anything. The toggle itself is `Settings.diagnostics`; **View > Show log stays**,
because that is how you get to the file.

Two implementation notes:

* **Nothing is announced any more.** Turning it on used to put up a modal note
  saying where the file was and what it recorded; Donald had both that and the
  paragraph under the checkbox out after the first Windows build — *"debug logs
  don't need an explanation"*. The path goes to the status bar, `[logging]`
  goes to the title, and `announce` survives for the one thing worth
  interrupting for: a log file that would not open. `_debug_log(on,
  announce=False)` is still the startup path, where even that is wrong.
* **The field is `diagnostics`, not `debug_log`.** `tests/test_debuglog.py`
  asserts `not [f for f in fields(settings) if "log" in f.name]` — it still
  encodes the superseded decision, and it was outside this task's scope to
  edit. **That test is Donald's to retire**, and when it goes the field should
  be renamed to say what it is.

---

## 12. Window geometry

Donald: *"Can the gui window remember its size if a user resizes it? And reopen
at that same size?"*

Before this it half-worked, and the main window ignored it: `AutomapWindow`
saved `window_width`/`window_height` and restored them, but `wish/window.py`
did `win.resize(max(settings.window_width, 1875), max(settings.window_height,
1030))` — a floor regardless of what was saved — and nothing wrote the size
back when the merged window was resized. Worse, the hosted map window's
`shutdown()` wrote *its own* size — the size of a page inside a tab — over the
remembered one, so what was in the file was not a window size at all.

What it does now:

* **`saveGeometry()` / `restoreGeometry()`**, base64 in `Settings.geometry`.
  They carry the position and the screen as well as the size, and
  `restoreGeometry` knows how to refuse a geometry saved on a monitor that is
  no longer attached.
* **`clamp_to_screen`** afterwards, always: Qt will happily restore a window
  larger than the screen it lands on, and 1875 px is wider than plenty of
  laptops. The frame is what is clamped, not the client area, so a window sized
  to the whole work area and then given a title bar still fits.
* **And again after `show()`.** The first Windows build opened taller than the
  screen with the status bar off the bottom, and the clamp had not fired at
  all: before `show()` there is no frame, `frameGeometry()` equals
  `geometry()`, the chrome measures zero, and 1030 px "fits" a 1032 px work
  area right up until the title bar arrives. So the clamp now assumes
  `config.UNSHOWN_CHROME` (16 × 48) while there is no frame to measure, and
  `run()` clamps a second time once the window is up, when the numbers are
  real and the answer can only get smaller. It also leaves a **maximised**
  window alone — resizing one un-maximises it, and maximising was Donald's own
  workaround. `tests/test_windowslayout.py` fakes a 1920 × 1032 screen and a
  frame, because the offscreen platform draws neither.
* **`window_width` and `window_height` are still written**, kept current, for an
  older build reading the same file — and they are the fallback on the first
  run after this change, so **nobody loses their window**. Donald's saved 940 ×
  820 raised by the `FIRST_RUN` floor of 1875 × 1030 is exactly what the old
  code did, so the first run after the upgrade looks identical; the second run
  onwards uses whatever he resized to.
* **Only the window that *is* a window remembers.** `AutomapWindow.shutdown()`
  writes geometry only when `drive=True`; hosted, `WishWindow.closeEvent` does.

---

## Open

* **`sight` has no UI anywhere** and is deliberately left that way. Whether it
  should get one, and on the map rather than in this dialog, is a separate
  question nobody has asked yet.
* **Per-title folders.** Somebody with Pool of Radiance and Curse in different
  directories gets one folder box and has to change it when they switch games.
  Correct for one folder holding both (the common case); wrong for a split
  shelf. Deferred until it bites — the fix is additive, a folder per title in
  the same box.
* **`wish-editor` standalone** (`editor/__main__.py`) takes `--game-disk` and
  cannot read a preference: the grep test globs `editor/*.py`, which includes
  `__main__.py`, so that entry point may not import `automap` either. It either
  keeps the limitation, or something outside `editor/` resolves the folder and
  passes it in — a third `main` in `wish/`, which is arguably where
  [`129-one-binary.md`](129-one-binary.md) is heading anyway.
* **`automap/live.py::item_names` still has its own `find_disks` default.** The
  window hands it the resolved folder, so nothing in the application reaches
  that path any more; the default is one line to delete next time that file is
  open.
