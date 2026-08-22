# One window — plan

**Status: built.** `wish`, with `wish-editor` and `wish-automap` as aliases
onto the tab each name implies. The build report is
`work/reports/one-window.md`; the Ultimate backend in `wish/ultimate.py` is the
one part that is **unverified**, because nobody has the hardware.

Two programs today: `wish-editor` (a file tool) and `wish-automap` (a live map).
They share `por/`, a toolkit and a purpose, and nothing else. This merges them
into one application with tabs, and reshapes the character sheet.

The command is **`wish`** — free again since the CLI became `wish-cli`.

---

## Tabs

Exactly two to begin with, and a third planned separately in
[the live view](100-live-view.md):

| tab | |
|---|---|
| **Character Editor** | the whole sheet on one page, no inner tabs |
| **Automapper** | as it is now, and it becomes the [combat view](101-combat-view.md) while a fight is on |

---

## The sheet loses its tabs and gains boxes

`editor/character.ui` currently buries 60-odd fields behind nine tabs —
abilities, combat, levels, thief skills, money, appearance, inventory, spells,
other. That was a first pass, and it is wrong: you cannot see a character. You
click through nine pages to answer "is this the wounded one".

Replace the `QTabWidget` with `QGroupBox`es on a scrolling page. A group box
draws a titled border, which is exactly the delineation wanted, and Designer
handles them like any other container so the rearrange-in-Designer loop is
untouched.

Suggested arrangement, left column then right, but **this is Donald's to
rearrange** — that is the point of the `.ui`:

| box | holds |
|---|---|
| Identity | name, race, class, class bits, sex, alignment, age |
| Abilities | the six scores, exceptional strength, effective strength |
| Combat | hit points, THAC0, armour class, movement, saving throws |
| Experience & levels | XP, character level, the four per-class levels, drain |
| Thief skills | the eight percentages; hidden entirely for a non-thief |
| Money | the seven coin types |
| Appearance | portrait head and body, the combat icon |
| Inventory | the sixteen item slots |
| Spells | spellbook and memorised list |

Two boxes are big enough to deserve their own scroll area rather than stretching
the page: **Inventory** and **Spells**. Everything else fits.

**Nothing about the binding changes.** Widgets still bind by `objectName` —
`field_strength` to the `strength` field in `por/layout.py` — and `findChild`
does not care whether the widget's parent is a tab or a group box. The read-only
rules, the flush-before-switch, the losslessness test: all untouched.

**Hide empty boxes rather than showing zeros.** A fighter has no spellbook and
no thief skills; a page showing eight `0`s invites someone to type in them. Hide
the box when nothing in it applies, which the class bits already tell us.

---

## The shape of the application

A new top-level package, `wish/`, that owns the window and the connection.
`editor/` and `automap/` stay as they are and become libraries of widgets.

```
wish/
  __init__.py
  __main__.py      the `wish` command
  window.py        the tabbed main window, menu, status bar
  session.py       the shared live connection and its state machine
  backends.py      which live backends exist, how to find one
```

That keeps the project's first decision intact: **the editor never talks to a
live machine** ([README.md](README.md) §"How the code is laid out"). `editor/` gains no import of `automap`, `por/` stays
transport-free, and the file path — open, edit, save — works with no emulator
present, which is how most people will use it.

### One connection, shared

This is the constraint that decides the design, and it is measured, not assumed:
**VICE serves exactly one binary-monitor connection at a time.** It accepts a
second TCP connection and then silently ignores it. So the map tab and the live
tab **cannot each open their own** — the second would hang with no error.

`wish/session.py` owns a single `Target` and hands it to whoever is looking at
it. Its job:

* find a backend and attach, retrying on a timer when there is none;
* expose one `poll()` that reads what the *visible* tab needs and no more,
  because the cost is per round trip;
* publish state changes to subscribers so tabs render from the same snapshot;
* drop back to "waiting" and reattach when the emulator goes away.

Only the visible tab polls. Switching tabs changes what is read, not how often.

**And when something else already holds the monitor, the map says so in red.**
The two cases look identical from the outside unless they are told apart: with
nothing running the TCP connect is *refused*, and with another client attached
the connect *succeeds* and is then never served. `ViceTarget` pings on attach
and raises `MonitorBusy` when the ping times out, so "waiting for a game" is
never said about a game that is running. It is a colour and not a dialog,
because it clears on its own the moment the other client lets go —
`ss -tnp | grep 6502` names the process holding it.

---

## Making the Commodore 64 Ultimate easy to add

The Ultimate has a network interface and can read memory over it, so it is a
second backend rather than a second program. What stops that today is not the
`Target` protocol — that is already two methods and deliberately no more — but
three things that leaked around it.

**1. `fix()` is a method on `ViceTarget` and uses `Monitor` directly.** It calls
`is_bitmap`, `screen_address` and `read_screen`, all of which take a `Monitor`.
Reading the party's position off the game's status line is not VICE-specific —
any backend that can read memory can do it. Rewrite those four as free functions
over `Target.read`, and `fix()` becomes backend-neutral. This is the single
biggest unlock and is worth doing even if the Ultimate never happens, because it
also makes `fix()` testable against a plain byte dictionary.

**2. Discovery is hard-coded to a TCP probe of `127.0.0.1:6502`.** Make it a
property of the backend:

```python
@dataclass
class Backend:
    name: str                     # "VICE", "Ultimate"
    probe: Callable[[], bool]      # is one there right now?
    connect: Callable[[], Target]
    setup_hint: str                # what to tell the user if not
    default_interval_ms: int       # the Ultimate will want a slower poll
```

`backends.py` holds the list; the session tries each in turn. A user with both
gets whichever answers, and a preference in the config settles ties.

**3. `resume()` is VICE-specific and must stay out of the contract.** VICE stops
the machine while the monitor socket is serviced and needs an explicit resume;
the Ultimate does not stop at all. `Target` already excludes it — keep it that
way, and let `ViceTarget` call it internally. `docs/96` made this decision
already and it has held.

Two further Ultimate-specific facts to design around rather than discover late:

* **Latency is much higher** — a network round trip to a device, not a loopback
  socket. Hence `default_interval_ms` per backend, and hence *batch aggressively*
  (already the rule: one read of `$4900`–`$64FF` beats sixty small ones).
* **It does not disturb the machine**, so the 7%-fast effect measured under VICE
  will not appear. Nothing should assume either way.

Nothing here needs the Ultimate in hand. The refactor is justified by testability
alone, and it means adding the backend later is writing one class and one entry
in a list.

---

## What the merged window keeps

* **Open / Save / Save As** for the editor's file, with the timestamped backups
  and atomic write already built. The map tab has no file of its own.
* **The window title** carries the open save and a dirty marker, regardless of
  which tab is showing.
* **The status bar** shows the file on the editor tab and the connection on the
  live tabs, so it always answers "what am I looking at".
* `wish-editor` and `wish-automap` stay as commands, as thin aliases that open
  `wish` on the right tab. Nobody's habit breaks, and the automapper stays
  usable as a single-purpose window beside the game — which is how it is
  actually used.

---

## Order of work

1. `wish/backends.py` and the `fix()` refactor — backend-neutral, headless,
   tested against a fake `Target`. **Land this alone**; it is the Ultimate work
   and it is independently justified.
2. `wish/session.py` — one connection, retry, subscribers. Tested with the
   existing `ReplayTarget`.
3. `wish/window.py` with two tabs wrapping the existing widgets unchanged.
   Prove both still work before touching the sheet.
4. `character.ui`: tabs to group boxes. Purely a `.ui` change plus hiding empty
   boxes; no binding code moves.
5. The aliases, and the README.

---

## Verification

* The editor tab opens, edits and saves a disk **with no emulator running at
  all**, and a no-op save is still byte-identical.
* Opening the map tab and the live tab in turn never opens a second connection —
  assert one `Target` instance for the window's lifetime.
* Killing VICE while the map tab is showing drops to "waiting", and restarting
  it reattaches, with the editor tab unaffected throughout.
* Every field that had a widget on a tab still binds after the group-box
  conversion: assert the bound-widget count is unchanged.
* Move a group box in Qt Designer, restart, confirm the fields still bind and
  are still read-only or editable as before.
* A fighter's window shows no spellbook and no thief-skills box.
