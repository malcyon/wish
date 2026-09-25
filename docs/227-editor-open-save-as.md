# Open and Save As in the Character Editor

**Implementation built (stages 1 to 4); File > Convert remains behind
`WISH_EXPERIMENTAL_POD_CONVERT`; no conversion has been loaded in its
destination game through Save As yet, and Windows validation is pending.** Still
open: no emulator run of any Save As output (`docs/235` plans the Save As matrix
and it is unstarted); Windows validation; the verification matrix of
conditional refusals is unrecorded; slot-picker and multi-save Amiga disk
behaviour through Save As are unconfirmed; retiring Convert waits on a Pools of
Darkness Save As route. The Character Editor opens
C64, DOS and Amiga saves and saves to any supported platform through two split
buttons. Each button has a main action and a separate menu arrow: Open opens a
save file, while its arrow also offers a DOS folder picker; Save updates the
current save, while its arrow offers Save As C64, Save As DOS and Save As Amiga.

Choosing a destination platform reveals a compact section for its output path
inside the editor. It stays hidden during ordinary editing. This replaces the
separate File > Convert workflow, keeping conversion beside the save being
edited without a permanent row of destination controls. Conversion must
preserve the player's data; there is no dropped-fields panel.

Donald approved this layout on 2026-09-21 for #511 (Open a DOS save folder and an
Amiga save disk in the Character Editor, so editing a DOS character does not
mean two conversions), prioritizing compactness and fewer clicks. The existing
editor is described in [The character editor](97-editor.md).

## Selected layout

```text
Character Editor
┌───────────┬──────────┬─────────────────────┐
│ Open…   ▾ │ Save   ▾ │ Preview changes…    │
└───────────┴──────────┴─────────────────────┘
Pool of Radiance · DOS · Save A · [Source path]

Open arrow                 Save arrow
┌─────────────────────┐    ┌─────────────────────┐
│ Open file…          │    │ Save As C64…        │
│ Open DOS folder…    │    │ Save As DOS…        │
└─────────────────────┘    │ Save As Amiga…      │
                           └─────────────────────┘
```

The main Open button opens the file picker immediately. The main Save button
writes to the current source; opening either menu must not trigger its main
action. Save's menu includes the current platform for making a native copy and
the supported other platforms for conversion. The title never changes.

Choosing a Save As entry opens a compact destination section inside the editor,
above the roster. The selected platform is already known; there is no second
format chooser. The section contains the output filename or folder, Browse,
Cancel and Save As. Show a game-files selector only when required assets cannot
be resolved from preferences. Show the destination save letter when applicable,
without requiring another choice for a newly created save. There is no source
picker in this section: its source is the editor's current party and edits.

No destination section is visible during ordinary editing. It closes on Cancel
or successful Save As. It consumes the existing editor area rather than
resizing the top-level window. Truncate long source paths, give destination paths
shrinkable fields, and stack conditional controls vertically. Keep the roster
and character sheet usable through the existing splitters and scrolling.

Two clicks choose another platform: the Save arrow, then its menu entry.
Browsing and the final Save As remain explicit. Resolve game assets and suggest
an unused output path automatically, so a valid suggestion needs no Browse.
Do not insert a conversion wizard or a success acknowledgement.

File-menu actions call the same handlers. Ctrl+O opens a file, Ctrl+S saves,
and Ctrl+Shift+S opens the destination-platform menu. Preserve Preview changes
as the comparison of the player's edits, not a conversion-loss report.
The menu labels above are part of the approved layout; additional necessary
player-facing wording still follows the GUI-text rule before implementation.

## Save behavior

| Operation | Behavior |
|---|---|
| Open file | Detect C64 `.d64`, Amiga `.adf`, or DOS saved-game files through `Source.detect`; preserve existing C64 roster/character opening support. |
| Open DOS folder | Detect the folder through the same source model; remember the folder itself, not its parent. |
| Choose source save | A file naming a DOS save letter selects that save; a multi-save folder or Amiga disk requires an explicit choice among complete saves. Reuse the existing slot picker. |
| Save | Write native edits to the current file or folder and current save letter, using existing backup preferences. A no-op writes nothing. |
| Save As, same platform | Copy the source container with current edits, preserving other saves and opaque native data. Do not convert through another platform. |
| Save As, other platform | Convert the selected saved game, including pending edits, into a new destination container of the same title. |
| Success | Validate and open the written destination, update the path/platform/letter and saved baselines, then close the destination section. The next Save writes there. |
| Cancel or failure | Keep the current source, selected character and pending edits. Do not emit a successful save or change the active path prematurely. |

Opening another source, changing its save letter, or closing with pending edits
must share the unsaved-changes handling currently in `EditorBinding.close()`;
`load()` does not already invoke it. Factor the guard out and avoid reusing
closing-specific wording for Open. Canceling that guard keeps both the
source and its selected save letter. Save As must never save the original as an
implicit prerequisite to conversion. Distinct destination paths leave the
source untouched. Same-platform Save As targeting the current container and
letter uses the normal Save path; reject aliases that would make a different
operation overwrite its source.

### Destinations

| Platform | Destination and default |
|---|---|
| C64 | A new `.d64` at the chosen filename. There is no destination save-letter control. |
| DOS | A new save folder. Cross-platform writers currently create save A; a same-platform copy preserves the source folder's saves and selected letter. |
| Amiga | A new `.adf` at the chosen filename. C64 conversion creates save A; DOS conversion retains its source letter. A same-platform copy preserves all saves and the selected letter. |

The existing conversion writers publish into a fresh output folder. Adapt that
publication layer so C64 and Amiga Save As can use a chosen image filename;
do not implement new codecs to accommodate a filename picker.

Cross-platform Save As does not merge a party into one slot of an existing disk.
Replacing an existing image means replacing the whole image, with confirmation
and a backup. DOS output uses a new folder initially; refuse a nonempty target
instead of mixing files with an unrelated save. Existing-source Save continues
to update the appropriate DOS files. A slot-merging writer is outside this
design and must not be implied by a destination dropdown.

Asset requirements belong to each title and conversion direction. Reuse the
configured game folders; source C64 combat figures can require C64 game disks,
and the destination can require its own game data. Do not copy the old dialog's
blanket Amiga game-disk requirement: the Silver Blades Amiga writer does not
need it. Game assets remain read-only inputs, never save templates.

## Dropped fields are high-priority defects

Donald's instruction for this design is explicit: **every dropped field is a
serious bug with `Priority: High`; it is not a supported conversion outcome.**

* There is no dropped-fields panel, warning list, loss acknowledgement,
  "save anyway" option, or "no conversion warnings" success line.
* Retain field accounting, conversion diagnostics and debug logging for agents
  and tests. Removing the UI must not suppress evidence or remove fields from
  the accounting that detects a loss.
* Check both `report.dropped` and lossy entries in `report.losses`, including
  name truncation. Retire `dosimport.name_warnings` as a player-consent path;
  a loss does not become acceptable by being classified outside the drop list.
* Every detected drop gets a bug issue with `Priority: High`, or the existing
  issue is updated to that priority with its evidence. Fix the conversion;
  documenting the defect, hiding a control or accepting a test failure does
  not complete the work.
* A known drop blocks release of the affected conversion. If discovered during
  an attempted save, stop before publication and leave the source, destination
  and editor state unchanged. Use the ordinary save-failure path with technical
  details in the debug log; never silently succeed or offer consent to lose data.
* Do not add a discard chooser or relabel an unexplained loss as a platform
  limitation. Investigate it. Proven format constants and values reconstructed
  by the engine remain distinct from lost state, with evidence for that claim.

This is the acceptance requirement for this work, including any broader
interpretation of an exception in the existing conversion rules. Diagnostics
do not automatically submit a player's save or create public issues at runtime;
agents file the defects they investigate.

## Implementation sequence

The registry already provides all six cross-platform directions for Pool of
Radiance, Curse of the Azure Bonds and Secret of the Silver Blades. It does not
promise conversion for every title the editor can open. Build menu entries from
the actual title's supported directions plus its native-copy operation.

| Stage | Owner and files | Required result |
|---|---|---|
| 1. Capture current edits | Reverse-engineering agent: new `editor/saveplan.py`, native assembly in `editor/window.py::_write_back`, source/rehearsal interfaces in `editor/convert.py`, focused new `tests/editor/test_saveplan.py` | An isolated snapshot combines original native data with all pending edits, including inventory and supported traits/effects. Preparing it writes neither source files nor live editor baselines. C64, DOS and Amiga conversions consume it. |
| 2. Prepare and publish | Reverse-engineering agent: `editor/saveplan.py`, `editor/convert.py`, `editor/files.py`, relevant conversion/editor tests | Extract asset resolution, rehearsal and output preparation from `ConvertDialog`. Add native copies, validation, loss refusal, explicit output paths, backups and publication with recovery on failure. Return a destination descriptor and a validated party for adoption. |
| 3. Wire split Open and Save buttons | Qt UI specialist: `wish/window.ui`, generated `wish/ui_window.py`, `wish/window.py`, `editor/window.py`, editor/preferences/layout tests | Implement split buttons and the conditional destination section in Designer; connect toolbar, menus and shortcuts to one controller. Adopt the prepared destination only after successful publication. |
| 4. Establish parity and retire Convert (done except for Pools of Darkness: File > Convert survives only behind `WISH_EXPERIMENTAL_POD_CONVERT`, its dialog refuses a reported loss, and it is removed with the flag) | Qt UI specialist after backend verification: obsolete conversion-dialog wiring/form, affected tests, `docs/97-editor.md`, `docs/117-save-conversion.md`, package inventory rows | Partly done: native copies and every direction except Pools of Darkness work from Save As. Remove File > Convert and its dialog code when a Pools of Darkness Save As route exists. Retain the direction registry, codecs and conversion tests. |

Stages are sequential; ownership transfers explicitly because they share files.
Each implementation agent receives the approved scope and its own test files;
code review follows each stage that writes code. If a codec cannot preserve a
field, stop that route, record the high-priority defect and route the missing
byte work to the appropriate specialist. Do not substitute UI for the fix.

The stage-1 regression was concrete: `Source.detect(path, party)` used the open
party for C64 but reread DOS and Amiga sources from disk, so a conversion could
omit unsaved native edits. It now takes the party branch for every port and
`editor.saveplan.prepare` assembles the port's own bytes. A snapshot must
retain the native data outside the C64-shaped editing model, not rebuild the
whole save from the visible sheet alone. The native rewrite machinery in
[The differential rewrite](223-the-differential-rewrite.md) is the starting point.

Publication must prepare and validate all output before changing the active
document. Reuse `editor/files.py`'s backup and recovery mechanisms; image writes
use a temporary sibling and replacement, while new DOS folders stage the complete
set before publication. Do not describe several per-file replacements as one
atomic transaction. Inject failures to establish rollback and recovery behavior.
Invalidate prepared output whenever an edit, destination or required asset changes.

Adoption is part of the transaction. `_adopt()` currently changes the party and
path before rebuilding the UI, so validate the destination and prepare bindings
before publication, then retain enough previous state to recover if activation
fails. Recovery restores the old document, selection, dirty baselines and path,
and restores a replaced destination from its backup or removes a newly published
output. If recovery itself fails, retain the backup and recovery evidence and
report an ordinary save failure; do not claim that nothing was written.

## Acceptance evidence

* Opening each supported source shape selects the intended complete saved game;
  canceled source/slot selection changes nothing. Existing C64 roster disks and
  standalone-character behavior remain covered.
* On C64, DOS and Amiga, edit a character and an item, then Save As without Save.
  Reopen the destination and observe both edits; compare the source bytes with
  their originals. The next Save updates only the adopted destination.
* Exercise all six cross-platform directions for each of the three registered
  titles, plus native Save As on all three platforms. Cover empty and extreme
  cases. Read results independently, assert state and empty drop accounting,
  and preserve unrelated native data on same-platform copies.
* A forced dropped field fails before any destination write. No loss-report
  widget or accept-loss action exists. The regression goes red when the guard
  is removed; deleting field accounting is not a passing repair.
* Cancel, invalid assets, failed backup, failed publication, destination
  validation failure and failed adoption preserve pending edits and do not
  redirect later Save. Inject adoption failure after publication and verify
  both editor restoration and destination recovery, including failed recovery.
  Replacing an image backs up the destination's original bytes. A new output
  creates no unnecessary backup; a repeated unchanged Save writes nothing.
* Render empty, loaded, menu-open, destination-open, missing-assets and long-path
  states. Verify the existing small-desktop constraints on native Windows as
  well as offscreen Qt. Follow the repository's font range and platform-aware
  sizing tests; a Linux Fusion screenshot alone does not prove Windows fit.
* Reuse `tests/convert/test_convert.py`, `test_convertmatrix.py`, the native
  rewrite tests, `tests/editor/test_editor.py`, `tests/wish/test_preferences.py`
  and `test_mapscale.py`; add focused service tests rather than a second matrix.
  Run the affected tests, including the conversion tests that read game data,
  Ruff and generated-UI checks per stage. Push, then check CI, which runs the
  whole suite, for the pushed SHA, including Windows.
* Byte-level checks are not proof that a game loads the output. Reuse applicable
  existing emulator evidence and obtain fresh load, walk and character-sheet
  evidence for changed conversion behavior under the emulator rules. Report
  exactly which titles and directions were exercised and what remains unproven.

This document specifies the design and records that it is built. It does not
claim Windows validation, an emulator run of any Save As output, or a
successful conversion loaded in its destination game.
