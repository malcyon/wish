# Preferences — plan

**Status: nothing built.** Donald: *"The 'Finding a game disk' section of the
readme worries me. This is going to cause confusion. I think we need a
preferences window under the file menu … configurations for where wish looks
for game disks, as well as the backend … The backend option should move into
the preferences dialog."*

---

## The verdict

* **The dialog holds two things: where the game disks are, and which live
  backend to use.** Nothing else. Fog of war and the map's own knobs stay on
  the map, where you change them mid-play.
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
* **`automap.json` becomes `settings.json`**, migrated once on load. Cost is
  about ten lines and one test, and Donald does nothing.

---

## 1. The problem, measured

Two searches, three environment variables, one flag each, none of it in the
window.

| | wants | resolved in | order today |
|---|---|---|---|
| Character editor | a game **disk image** — item names, spell names, the icon charset, the icon option tables | `editor/window.py:511` `_disk_candidates` | `--game-disk` → `$POR_GAME_DISK` → the open save's own directory → the directory of whatever `--game-disk`/`$POR_GAME_DISK` named |
| Automapper | a **directory** of that title's disks — every `GEO` on them | `automap/paths.py:70` `disk_candidates` → `locate_disks` | `$POR_DISKS` alone if set, else cwd, `~`, `~/Documents`, `~/Games`, `~/c64`, `~/roms`, `~/Downloads` each × `"<Title> Disks"`, `"<Title>"`, `PoR`, then cwd and `~` |
| Roster's readied item | the same names, again | `automap/live.py:318` `item_names` | `find_disks(game)`, i.e. the automapper's order |

Three call sites, three orders, no shared function. **CONFIRMED** — read in
this tree at `2f0137d`.

What the user sees when it goes wrong:

| symptom | where | says why? |
|---|---|---|
| items listed as `word 8` | editor tab, inventory table | yes, but names the flag and the env var: *"pass `--game-disk`, set `$POR_GAME_DISK`, or put a game disk beside the save"* (`editor/window.py:895`) |
| empty grid, no map | map tab | no — the grid draws and says "looking for the game", which is about the emulator, not the disks |
| `no game disks found, so the map tab will be empty` | **stderr** | only to a terminal. `wish` launched from a desktop icon or an unpacked PyInstaller build prints it to nowhere (`wish/__main__.py:110`) |

The last row is the whole bug. The diagnostic exists and is good; it is
delivered to a channel a GUI user does not have.

**And it is now undocumented.** The uncommitted `README.md` in this tree
deletes the "Finding a game disk" section along with the CLI section it sat
under. The search still runs; nothing describes it. That raises the priority of
this work rather than lowering it.

---

## 2. What goes in, and what stays out

`Settings` today (`automap/config.py`):

| field | set where today | verdict | why |
|---|---|---|---|
| `backend` | **View > Backend**, radio group | **into the dialog** | asked for; and it is a once-per-machine fact about your desk, not a play control |
| `interval_ms` | `--interval` only, no UI | **into the dialog**, under the backend | it belongs to the backend (200 ms VICE, 500 ms Ultimate) and it is meaningless to touch mid-play. A blank field meaning "the backend's own" keeps the good default |
| `reveal` | map toolbar toggle, the `fog_box` in the status bar, and `R` | **stays on the map** | you flip it while walking, to check a corridor you have not lit. A setting you toggle twenty times an hour does not belong behind a menu and a dialog |
| `sight` | **nothing** — read at `automap/window.py:413`, never written by any UI | **stays out** | it changes what the map draws, same class as `reveal`. If it earns a control it earns one on the map, not here. Out of scope for this plan |
| `window_width` / `window_height` | written by `closeEvent` | **never in the dialog** | remembered state, not a preference; nobody types a window size |
| *(new)* `disks` | — | **into the dialog** | the point of the exercise |
| *(new)* `ultimate_host` | `$POR_ULTIMATE` only | **into the dialog** | see §6 |

**The rule the table is applying:** a preferences dialog collects the settings
you set *once*, about this machine. Everything you set *while playing* belongs
on the thing you are playing with. Collecting all six of these would make the
dialog longer and each row harder to find.

Two things that are settings-shaped and stay out for their own stated reasons:

* **Debug log** — already deliberately not remembered ("a logging setting that
  survives a restart is one you forget is on", `wish/window.py:151`). Leave it
  on the View menu.
* **Which tab opens** — `--tab`. Not asked for, and the window opens on the map
  because that is what you have open beside the game.

---

## 3. One search or two

**One.** The dialog shows one row: *Game disks: `<folder>`*.

The argument for two is that they are different things — a file for the editor,
a directory for the map — and they need not be co-located. The argument against
is stronger on all three counts:

1. **The editor already treats a named disk as a directory.** `_disk_candidates`
   takes whatever `--game-disk` named, walks up to its parent, and globs the
   whole title from there, with the comment *"The disks come as a set. Being
   told `POOL1.D64` says where the other seven are, and they are not
   interchangeable — the icon charset and the icon option tables live on
   different disks."* The editor's real requirement is already a directory; the
   file is an entry point into one.
2. **Neither side wants a specific image.** The editor tries every candidate
   until a read succeeds (`_find_disk`), because which disk carries the charset
   is not knowable in advance. The map globs all of them and takes the first
   copy of each `GEO`. A single-file setting would be a worse fit for both.
3. **Two rows invite the wrong question.** A dialog asking *where are your game
   disks* and *where is your game disk* teaches the user that these are
   different, which is the confusion being fixed.

The case a single folder loses is *"use this exact image for item names"*.
`--game-disk` keeps it, and it keeps it as a flag, which is the right shape for
a one-off. **Recommendation: no per-image preference. If it is ever wanted, it
is a second row and it is additive.**

The fallback keeps working and is now *visible*: with the folder empty, the
editor still finds a disk sitting beside the open save, and the dialog reports
that it did and where from.

---

## 4. Precedence

> **The setting in Preferences is the answer.** A command-line option beats it
> for one run; nothing else does.

There is one thing to configure — **Game directory** — and it is saved in the
config file. That is the whole user-facing rule.

| rank | source | who uses it |
|---|---|---|
| 1 | `--disks` / `--game-disk` on the command line | scripts, and anyone testing two sets of disks without changing a setting. A person using the window never types it |
| 2 | **the Game directory setting** | everyone. This is the one that matters |
| 3 | beside the open save | automatic, editor only, and usually right |
| 4 | the candidate-directory search | automatic, `disk_candidates`, unchanged |

**`$POR_DISKS` and `$POR_GAME_DISK` are not user settings and should stop
being documented as though they were.** Of twenty references in the tree,
almost all are the test suite and the developer tools -- `tests/gamedata.py`
uses `$POR_DISKS` to find Donald's disks without hardcoding a path, and
`tools/geomap.py` and `tools/genmaps.py` do the same. Exactly one runtime line
reads it (`automap/paths.py:71`). They predate there being any interface, and
then the README described them as a user's third option.

So: **keep them working, for the tests and the tools, and take them out of the
user-facing documentation.** They sit below the setting, above the automatic
searches, and nobody who uses the window ever meets them.

**What changes today's behaviour:** `$POR_DISKS` currently short-circuits the
entire search (`automap/paths.py:71-73`). It keeps that power over the two
automatic searches and loses it to the setting only. **This does not disturb the suite**:
`tests/conftest.py::_isolate_config` points all four config variables at a
`tmp_path`, so no test ever sees a saved preference, and `tests/gamedata.py`
keeps reading `$POR_DISKS` exactly as it does now. **CONFIRMED** — read
`tests/conftest.py:56` and `tests/gamedata.py:44`.

**One function, not five.** `automap.paths.resolve_disks(flag=None,
beside=None, game=None)` returns `(directory | None, source)` where `source` is
one of `"--disks"`, `"preferences"`, `"$POR_DISKS"`, `"beside the save"`,
`"searched"`, `"nothing found"`. Everything that wants disks calls it:
`automap/__main__.py::default_disks`, `automap/live.py::_item_names`,
`wish/window.py`, and the dialog's own report — which is why the report can
name the source honestly instead of guessing.

`Settings` must be imported inside the function body, not at module scope:
`automap/config.py` already does `from .paths import config_dir`, and the
reverse import at module level is a cycle. Function-local imports are the house
pattern here (`automap/live.py:330` does exactly this).

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
│  Maps     29 GEO files                                       │
│  Names    POOL1.D64 — 163 items, 56 spells                   │
│  Icons    POOL1.D64 · icon parts POOL3.D64                   │
│                                                              │
│  Leave it empty to search: beside the open save disk first,  │
│  then the usual folders.                                     │
└──────────────────────────────────────────────────────────────┘
```

Six report lines, and each one answers a question somebody has actually had:

| line | answers | source |
|---|---|---|
| **In use** | "is it even looking where I put them?" | `resolve_disks(...)[0]` |
| **Set by** | "why is it ignoring what I typed?" | `resolve_disks(...)[1]` |
| **Titles** | "are these the right disks?" | `paths.titles_in(where)` + a count per `disk_globs` |
| **Maps** | "why is the map tab blank?" | `len(load_maps_titled(where, game)[0])` |
| **Names** | "why are my items numbers?" | the image `_find_disk(load_item_names)` settled on |
| **Icons** | "why can't I edit the combat icon?" | `_find_disk(load_icon_charset)` and `_find_disk(IconParts.load)` — they are different disks and that surprises people |

Failure states are stated as failures, in the same slots: *Titles — none; no
`POOL*.D64` or `CURSE*.D64` here*. *Maps — none.* *Names — not found, so items
show as name-table indices.* The empty answer is more informative than a
missing row.

**Live, on every keystroke and every Browse.** Re-resolving is a `glob` and a
`titles_in`; opening one `D64` for the names row is the only real cost and it
is already cached (`automap/live.py`). No OK button — see §7.

### 5b. Two changes outside the dialog, which are the actual fix

A dialog nobody opens fixes nothing. The two silent failures must announce
themselves *and name the route*:

| where | today | after |
|---|---|---|
| map tab, no maps loaded | empty grid; the reason went to stderr | the grid says **"No game disks found, so there are no maps. File > Preferences… to say where they are."** `AutomapWindow.waiting()` already exists for exactly this and is already wired through `WishWindow._session_said` |
| editor tab, no game disk | *"pass `--game-disk`, set `$POR_GAME_DISK`, or put a game disk beside the save"* (`editor/window.py:895`) | *"No game disk found, so items show as name-table indices. **File > Preferences…** to say where the disks are."* Same for the `button_item_add` tooltip |

The stderr line in `wish/__main__.py:110` stays for the terminal user. It is
not the only channel any more.

---

## 6. The backend section

The View > Backend group moves across whole, keeping both of its honest
behaviours:

```
┌─ Live backend ───────────────────────────────────────────────┐
│  (•) Whichever answers                                       │
│  ( ) VICE — answering                                        │
│  ( ) Ultimate — not answering; unverified, nobody here        │
│      has the hardware                                        │
│                                                              │
│  Ultimate host  [ ultimate64.local            ]  (or host:port) │
│  Password       from $POR_ULTIMATE_PASSWORD — not set         │
│                                                              │
│  Poll every     [        ] ms   (blank: the backend's own —   │
│                                  VICE 200, Ultimate 500)      │
└──────────────────────────────────────────────────────────────┘
```

* **Offered but marked.** A backend that is not answering is still selectable,
  as today — you set the preference before you start the emulator as often as
  after. `label_backends()` moves from `menu.aboutToShow` to the dialog's
  `showEvent` plus a **Re-check** trigger on any host edit. Same rationale
  verbatim: `probe()` is a TCP connect, wrong on a poll timer and stale if done
  once at startup.
* **Unverified stays said in words**, from `Backend.verified`, not hard-coded
  in the dialog.
* **Selecting still does two things**, and `_prefer_backend` already does them
  correctly: write `settings.backend` and call `session.prefer(name)`, which
  drops a *different* attached backend so the next poll lands on the chosen
  one. Move the method, do not rewrite it.

### The Ultimate host — into the dialog

`$POR_ULTIMATE` has no UI at all today, and this backend is *only* reachable by
naming a host: with nothing set it is never probed and never offered
(`wish/ultimate.py::configured`). So the one control that turns the feature on
is invisible. It belongs here.

`configured()` gains the same precedence as everything else: the preference
first, then `$POR_ULTIMATE` / `$WISH_ULTIMATE`. `Settings.ultimate_host: str =
""`; empty means "not configured", so the no-probe, no-delay, no-error
behaviour for a network with no Ultimate on it is unchanged.

### The password — not in the settings file, and not in the dialog

**A password field is the one thing here that must not be stored in
`automap.json`/`settings.json` in clear text.** That file is documented to the
user as *"one small JSON file you can read and edit"*, it is in the folder
`wish --debug` writes logs into, and a project whose selling point is that it
touches nothing it should not must not start a habit of writing secrets to a
world-readable dotfile.

**Recommendation: no password entry field at all. One read-only line, showing
whether the environment variable is set.**

| | |
|---|---|
| what the dialog shows | `Password  from $POR_ULTIMATE_PASSWORD — set` / `— not set` |
| what it never shows | the value, or a masked stand-in for it |
| what it never writes | anything |
| what it gains | the diagnostic — *"is the password reaching wish at all?"* — which is the only question a user actually has here, and the one an env var answers worst |

Why not a keyring: `keyring` is a new runtime dependency, a new PyInstaller
hook, a new failure mode on a headless Linux box with no Secret Service, and it
would be added for **hardware nobody on this project owns and a firmware
requirement described as "3.12 and later *may* require"**. That is a poor
trade. If somebody with an Ultimate reports that the env var is awkward, add
`keyring` behind a `try: import` then, and let the field be disabled with the
reason shown when the import fails. **Not now.**

Confidence: this is a judgement, not a finding. The facts it rests on —
password is header-only, env-only, and the backend is unverified — are
**CONFIRMED** from `wish/ultimate.py`.

---

## 7. Where the settings live

Three facts constrain this, and the third is the sharp one:

1. `Settings` is `automap/config.py`, writing `automap.json` under
   `config_dir()`.
2. Donald has that file on this machine already, and it holds a window size he
   would notice losing.
3. **`editor/` may not import `automap/`.** `tests/test_wish.py:349`
   `test_editor_imports_nothing_live` greps every `editor/*.py` for the string
   `automap` and fails the build. That is the project's first architectural
   decision made mechanical (`docs/README.md`, rule 1) and this work does not
   get to weaken it.

### The file: rename, migrate once, keep the old copy

`FILE = "settings.json"`. `Settings.load()` reads it; if it is absent and
`automap.json` is present, it reads the old file and returns those values.
`save()` only ever writes the new name. The old file is **not deleted** — an
older `wish` binary run afterwards still finds its settings, and a stale 200-byte
JSON costs nothing.

**Migration cost: about ten lines in `load()` and one test.** Donald does
nothing and notices nothing. Doing it now is much cheaper than after a `v*`
tag, on the same argument as [`129-one-binary.md`](129-one-binary.md).

### The module: leave it in `automap/`, pass the answer down

Do **not** move `Settings` into `wish/` or a new top-level package. `automap`
is a standalone program (`python -m automap`) and owns its own config; moving
the class buys nothing and touches every import of it.

The editor gets the folder the way it already gets a game disk — **handed in by
its caller**:

```
EditorWindow(save, game_disk, disks=None)      # a plain str path
```

`wish/window.py` resolves once with `paths.resolve_disks(...)`, passes the
directory to `EditorWindow.__init__`, and calls a new `EditorWindow.set_disks()`
when the dialog changes it. `editor/window.py` puts `disks` into
`_disk_candidates` between `self.game_disk` and `$POR_GAME_DISK` — matching §4 —
and imports nothing new. The grep test keeps passing, unmodified, which is the
point.

Standalone `python -m automap` reaches the same precedence for free, because
`resolve_disks` lives in `automap/paths.py` and `default_disks` calls it.

---

## 8. Files that change

**Not a Designer form.** `editor/character.ui` is the only `.ui` in the tree,
and `tools/genui.py` hard-codes that one pair of paths (`UI`/`PY` at
`tools/genui.py:20`). Every other dialog and panel in this project — `about.py`,
`noteeditor.py`, `commissions.py`, the warp bar — is hand-written PyQt.
**CONFIRMED.** Write this one in code too: it re-probes backends and re-runs a
directory search on every keystroke, which is code either way, and a second
`.ui` would mean a second `--check` path in CI for a form with eleven widgets.

| file | change |
|---|---|
| **`wish/preferences.py`** | **new.** `PreferencesDialog(QDialog)`: the two group boxes of §5a and §6, the report refresh, `Close` only. Sibling of `wish/about.py` and about the same weight |
| `wish/window.py` | `File > Preferences…` above the separator; delete `_backend_menu` and the View > Backend submenu; keep `label_backends` and `_prefer_backend` as the dialog's callbacks; on a folder change, re-resolve, reload maps into `self.mapper`, and `self.editor.set_disks(...)` |
| `automap/config.py` | `disks: str = ""`, `ultimate_host: str = ""`; `FILE = "settings.json"` + the one-time read of `automap.json` |
| `automap/paths.py` | `resolve_disks(flag, beside, game) -> (Path|None, str)` — the single precedence function, with a function-local `Settings` import |
| `automap/__main__.py` | `default_disks` calls `resolve_disks`; the stderr text names File > Preferences too |
| `automap/live.py` | `item_names` calls `resolve_disks` instead of `find_disks` |
| `automap/window.py` | the waiting text distinguishes "no emulator" from "no disks, no maps" |
| `editor/window.py` | `disks=` parameter, `set_disks()`, `_disk_candidates` gains rank 2, and the two "no game disk" strings name the dialog |
| `wish/ultimate.py` | `configured()` reads `Settings.ultimate_host` before the env vars |
| `README.md` | **Donald's file — wording reported, not written.** See §10 |
| `docs/97-editor.md:179` | the three-step order there is superseded by §4 — replace, do not append |
| `docs/99-one-window.md` | View > Backend has moved to File > Preferences |
| `docs/96-live-memory-automapper.md`, `docs/100-live-view.md` | wherever `$POR_DISKS` is described as the way to say where disks are |
| `docs/README.md` | one index row for `130-preferences.md` |

### Tests

| file | asserts |
|---|---|
| `tests/test_paths.py` | `resolve_disks` precedence, all five ranks, with the **source string** checked in each — a flag beats a preference, a preference beats `$POR_DISKS`, `$POR_DISKS` beats the search, and an unset everything returns `(None, "nothing found")`. Empty files of the right *name* are enough, as the module already notes |
| `tests/test_automap.py` | `automap.json` migrates to `settings.json` once, values intact; a `settings.json` already present wins and the old file is not read; a corrupt old file is still "no settings yet" |
| **`tests/test_preferences.py`** | **new.** The report names the folder, the titles and the map count for a synthetic directory; changing the folder updates the report with no OK pressed; **`asdict(settings)` contains no password key after the dialog has been open**; the Ultimate host round-trips to the JSON |
| `tests/test_wish.py` | File > Preferences exists and opens; the backend radios still write `settings.backend` and still call `session.prefer`; the labels still say "not answering" and "unverified"; **`test_editor_imports_nothing_live` unchanged and still passing** |
| `tests/test_editor.py` | with `disks=` given and no `--game-disk`, item names load; the no-disk message names the dialog |

Baseline to hold: **1197 passed, 2 skipped** (`python3 -m pytest tests/ -q`,
59.8 s, measured on this tree at `2f0137d`).

### One implementation note worth writing down now

`QKeySequence.StandardKey.Preferences` resolves on this Linux/Qt 6 build to the
**`XF86Settings` multimedia key**, not `Ctrl+,` — measured:
`QKeySequence(StandardKey.Preferences).toString()` returns `'Settings'`. Using
the standard key would give the action a shortcut no ordinary keyboard can
produce. Use an explicit `QKeySequence("Ctrl+,")`, which is what every desktop
expects anyway. **CONFIRMED**, this tree, PyQt6 in `.venv`.

**No OK/Cancel — a single `Close`.** Every control here already applies at once
today (the backend menu wrote and called `prefer` on click), and a Cancel would
need an undo path back through `Session.prefer`, a map reload and the editor's
item tables. Immediate-apply is both less code and the behaviour the existing
menu already taught.

---

## 9. Verification

The case that decides it: **disks in a folder no search covers, and a user who
has never opened a terminal.**

| # | do | expect |
|---|---|---|
| 1 | `unset POR_DISKS POR_GAME_DISK`; put the disks in `~/Desktop/porgame/`; launch `wish` from the desktop; open a save | items read `word 8`; map tab empty — **and both say "File > Preferences…"** |
| 2 | File > Preferences, Browse to `~/Desktop/porgame` | report fills in: *Set by — this preference*, *Titles — Pool of Radiance (8 disks)*, *Maps — 29*, *Names — POOL1.D64* |
| 3 | Close | items are named **without a restart**; the map tab draws |
| 4 | quit, relaunch from the desktop | still works. Nothing was typed in a terminal at any point |
| 5 | `export POR_DISKS=/somewhere/else`, relaunch | the preference still wins; the dialog says *Set by — this preference* and notes `$POR_DISKS` is set and overridden |
| 6 | clear the preference, relaunch | *Set by — `$POR_DISKS`*. Donald's own machine, unchanged |
| 7 | `wish --disks /third/place` with a preference set | *Set by — `--disks` (this run only)*; the saved preference is shown but marked overridden, and closing the dialog does not silently rewrite it |
| 8 | point the folder at an empty directory | *Titles — none; no `POOL*.D64` or `CURSE*.D64` here.* No crash, no exception dialog |
| 9 | point it at a directory holding both titles' disks, with a Curse save open | *Titles* lists both; maps and names come from **Curse** — the `game` argument is threaded through, not defaulted |
| 10 | `chmod a-w` the config directory, change a preference | dialog works, the change applies for this run, nothing raises (`Settings.save` already swallows `OSError`) |
| 11 | with `automap.json` present and no `settings.json`, launch and close | `settings.json` appears with the old values; `automap.json` still there |
| 12 | set the Ultimate host, no device on the network | *Ultimate — not answering; unverified*. No timeout stall on the poll timer, no error dialog |
| 13 | `grep -rn automap editor/` | **empty**, and `tests/test_wish.py::test_editor_imports_nothing_live` passes |
| 14 | `grep -rn 'POR_ULTIMATE_PASSWORD\|password' ~/.config/wish/settings.json` | **empty**, after a session with the dialog open and a password set in the environment |

Rows 1–4 are the acceptance test. Rows 5–7 are the precedence rule made
observable. Rows 13–14 are the two rules this work could quietly break.

---

## 10. Wording `README.md` needs

Donald's file, and it carries an uncommitted edit — **reported, not written.**

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

---

## Open

* **`sight` has no UI anywhere** and is deliberately left that way here. Whether
  it should get one, and on the map rather than in this dialog, is a separate
  question nobody has asked yet.
* **Per-title folders.** Somebody with Pool of Radiance and Curse in different
  directories gets one folder box and has to change it when they switch games.
  Correct for one folder holding both (the common case, and what
  `titles_in`/`locate_disks` are built for); wrong for a split shelf. Deferred
  until it bites — the fix is additive, a folder per title in the same box.
* **`wish-editor` standalone** (`editor/__main__.py`) takes `--game-disk` and
  cannot read a preference: the grep test globs `editor/*.py`, which includes
  `__main__.py`, so that entry point may not import `automap` either. It either
  keeps the limitation, or something outside `editor/` has to resolve the
  folder and pass it in — a third `main` in `wish/`, which is arguably where
  [`129-one-binary.md`](129-one-binary.md) is heading anyway. Unresolved, and
  it does not block the main window, which is what Donald asked for.
