# Requirements for Adding a New Platform

A player must be able to load the right party, inspect it, move, save and
reload it in each game the new platform supports. Establish that foundation
with existing game saves before implementing or testing conversions that
depend on the platform. Format research, readers and driver code needed to
prove the foundation are part of this first stage.

## Scope and the four-game matrix

The table below defines the required title coverage. For each proposed
platform, complete a matrix in its tracking issue with one row per title and
the columns **Game**, **Status**, **Release/media**, **Specimen provenance**,
**Driver command**, **Evidence**, and **Remaining work and owner**. Link the
durable documentation of proven scope and reproducible setup from that issue.
Shared emulator code does not prove another title's menus, disk handling or
save protocol.

| Game | Required foundation assessment |
|---|---|
| Pool of Radiance | Establish the port's release and media; prove its complete foundation route. |
| Curse of the Azure Bonds | Establish the port's release and media; prove its complete foundation route. |
| Secret of the Silver Blades | Establish the port's release and media; prove its complete foundation route. |
| Pools of Darkness | Establish the port's release and media; prove its complete foundation route. |

Use **Proven**, **Incomplete**, or **No released port**, with evidence for the
last case and an explicit statement of the resulting support scope. Missing
disks, dependencies, tools, captures or knowledge mean incomplete. They are
not an absent port or a passed check. Any proposed exclusion of a released
port requires Donald's explicit scope decision and remains visible as an
exclusion. Complete the foundation gate for every included port before
starting dependent conversion implementation or testing.

## Foundation gate

| Check | Required evidence |
|---|---|
| Platform definition | Name the machine, emulator and version, operating environment, game releases, disk or installation variants and save containers covered. Record required firmware, configuration and media hashes; do not claim untested variants. |
| Emulator memory interface | Select an emulator with a scriptable debugger, monitor or equivalent interface that lets Wish repeatedly read live game memory during play. Prove access from the machine running Wish, including address translation, memory banks or relocated game data where applicable. Measure read latency and consistency, establish whether reads pause the emulator, and prove polling resumes play safely without disturbing disk transfers. A debugger window without programmatic reads is insufficient. Breakpoints and stepping aid investigation; memory writes are required only for features that write to the running game. Document the supported capabilities and limits using the [target contract](../automap/target.py). |
| Reproducible provisioning | Document the host and guest setup, package and private-helper revisions, configuration and commands needed to recreate the working environment. Provision through the maintained setup rather than relying on one machine's shell state. |
| Actual dependency preflight | Check the interpreter the driver will invoke, its imports, registry paths and readable runtime assets before claiming a slot. Exercise the real helper offline against a retained capture or other representative input, including parsing and lookup; successful imports alone do not prove it works. Keep private challenge and answer contents out of public logs. |
| Generated assets | Give runtime-generated artifacts an external cache location, regeneration command, input provenance and integrity checks. A fresh checkout must be sufficient to discover and rebuild them from the player's inputs. Do not depend on a repository-local `work/` directory or commit generated game content. |
| Inputs and staging | Resolve the player's read-only media through `gamedisks.yaml` and the registry. Record specimen provenance and hashes, distinguish found saves from saves observed being written, and stage only copies before loading. Keep original media and registered specimens unchanged. |
| Isolation and silence | Claim the platform's pool slot or exclusive lane. Isolate configuration, ports, display and writable media; keep the emulator off the player's desktop. Establish silence on the actual audio path and retain its verification. Follow the [emulator rules](../.claude/rules/emulator.md). |
| Bounded driver | Provide one repeatable command per title over shared platform helpers. Set justified deadlines, cleanup time and retry limits; record keys, disk changes and recognized states. Unknown screens, failed captures and spent deadlines stop with evidence and a failed verdict. |
| Screen and state guards | Measure the title's boot, load, sheet, movement and save states, including interstitial prompts. Inspect the emulator's client area, excluding unrelated desktop changes. Check the requested member's identity against the input; a matching generic frame is insufficient. |
| Boot and load | Boot the declared media configuration, load the intended slot and confirm the party and world state. Demonstrate that the driver did not load a bundled or earlier party. |
| Inspect and move | Open the requested member's sheet and verify its identity and relevant values. Execute a declared movement route and read the resulting coordinates, facing and area. A redraw, clock tick, roster selection or turn alone does not prove a step. |
| Live automapper | For each included game, connect Wish to the chosen emulator and prove that the map follows the party's actual area, position and facing as it moves and changes areas. Establish each title's live memory layout, synchronize map data with the observed area, and verify load, restart and disconnect handling without showing stale state as current. Include a stationary control; screenshots or periodic save-file reads alone do not establish live memory integration. |
| Save, decode and reload | Save through the game's own controls. Wait for a completed write before copying the output, decode it and compare party identity, place and the declared fields with the observed state. Reload that game-written output and verify the party and saved place again. |
| Repeatability and control | Run the complete command twice from clean checkouts at the same pushed SHA with CI green, using the same specimen and configuration; require matching declared readback verdicts. Run a deliberate no-movement control, such as turns followed by save and readback. The control must show an unchanged square, and the movement judge must reject it as evidence of a step. Record whether a successful control has its own success exit. |
| Evidence and cleanup | Retain the command, SHA, dirty state, environment and media manifest, input as booted, captures, state transitions, checkpoints, verdicts and engine output through the [scratch/cache helpers](../tools/registry/scratch.py). Record failure and cleanup outcomes too. Preserve reusable engine-written saves with [the specimen registry](../tools/registry/specimens.py) before releasing the slot, and tear down only the run's own resources. |

The foundation proves the harness on existing saves. It does not require a
finished conversion UI or converter, and it does not prove either. Staging an
existing slot into media the game reads is a harness prerequisite; acceptance
of Wish's published conversion output belongs to the next gate. The existing
[destination-game acceptance plan](235-destination-game-acceptance-runs.md)
describes the driver and retained-evidence approach.

## Naming by responsibility

Each platform's harness lives in `tools/<platform>/` under lowercase names that say what the file is responsible for:

| File | Responsibility |
|---|---|
| `acceptance.py` | The supported acceptance command: dispatch and verdicts. |
| `session.py` | The platform session lifecycle and the driving operations shared by every title; C64's existing module keeps its place, and the emulator transport stays where it is. |
| `screens.py` | Screen recognition and guard helpers. |
| `staging.py` | Validated copies and preparation of input media. |
| `route_pool.py`, `route_curse.py`, `route_silver_blades.py`, `route_darkness.py` | Title-specific route descriptions and actions, where separating them removes a mixed responsibility. |
| `runlog.py` | The shared run log and signal handling (C64: `tools/c64/runlog.py`). |

The rules:

* A canonical implementation lives under its responsibility name.
* An old name is deleted after its maintained callers, tests and current documentation move. A compatibility wrapper exists only for a specifically identified consumer, and is recorded with a concrete removal condition.
* An extracted shared helper keeps one implementation.
* Evidence directories and recorded commands from earlier runs stay as history under the names they were run with.
* No second `session.py` may exist under `tools/`: `tests/conftest.py:_tool_path` refuses a bare tool name with more than one match, and twenty tests load `session` by bare name.
* Test files keep distinct base names across platforms, because the test directories have no `__init__.py`.

### Old to new

| Old | New |
|---|---|
| `c64acceptance.py` in `tools/c64/` | `tools/c64/acceptance.py` |
| `porlaunch.sh` in `tools/c64/` | `tools/c64/launch.sh` |
| `Log`, `Terminated`, `catch_signals`, `keep_old_log` in `tools/c64/savecheck.py` | `tools/c64/runlog.py` |
| `highlighted`, `walk_menu` in `tools/c64/dualclassagain.py` | `tools/curse_of_the_azure_bonds/curseload.py` |
| `dosacceptance.py` in `tools/dos/` | `tools/dos/acceptance.py` |
| The `--note` default `dosacceptance` (a pool-lease label) | Unchanged. |
| `_SAVGAM`, `containers_in`, `slots_in`, `source_slot`, `install`, `HALL_WORD`, `HALL_OPEN`, `HALL_TITLES`, `stage_hall`, `stage_xp`, `stage_node`, `node_dict` in `tools/dos/acceptance.py` | `tools/dos/staging.py` |
| `bar_signature`, `name_signature`, `status_square`, `roster_name`, `roster_line`, `sheet_name`, `on_items_list`, `item_rows`, `item_highlight`, and the constants they read (`CELL`, `STATUS_TEXT_X`, `STATUS_COLUMNS`, `POD_ROSTER`, `POD_SHEET_NAME`, `POD_NAME_CELLS`, `POD_NAME_ROWS`, `ITEMS_BAR_HEAD`, `ITEMS_BAR_HEAD_CELLS`, `ITEM_READIED_COLUMN`, `ITEM_INK`, `ITEM_LIST_RECT`, `ITEM_HIGHLIGHT_PIXELS`, `BLANK_NAME`) in `tools/dos/acceptance.py` | `tools/dos/screens.py` |
| `BARS`, `MENU_RECT`, `MENU_BEFORE`, `MENU_AFTER`, `RouteLost`, and the `Driver` methods `shot`, `bar`, `wait_bar`, `press`, `menu`, `to_party_menu`, `intro` in `tools/dos/ssbimport.py` | `tools/dos/route_silver_blades.py`, where the methods are on `Route` |
| `_silver_session_class` in `tools/c64/curedrive.py` | `silver_session_class` in `tools/secret_of_the_silver_blades/ssbsession.py` |
| The run's pool-lease owner label `c64acceptance/<issue>/<run>` | Unchanged. |

The Amiga renames are partly done. `tools/amiga/amigaacceptance.py` became `tools/amiga/staging.py`, and `amigaacceptance.py` stays only as a temporary import shim for `amigasecretsave.py`, removed when that caller is pointed at `staging.py`. The other Amiga names are planned and have not been renamed: `winuaesession.py`, `screens.py`, `route.py`, the `route_*.py` files and `acceptance.py`.

What stayed: `status_column` and the measured digests and key constants in `tools/dos/acceptance.py`, and the import and CURE experiment in `tools/dos/ssbimport.py`.

## Conversion gate

| Check | Required result after the foundation gate |
|---|---|
| Module boundaries | Keep format definitions, readers and writers in `goldbox/`, using its title and platform descriptions and neutral records. Keep emulator transport and live reads in `automap/` and driving tools, and application publication in `editor/`. Follow the existing [library responsibilities](../goldbox/README.md); avoid a second converter inside the harness. |
| Complete field accounting | Account for every neutral field in the readers and writers, including party/world state, items, spells and effects. Declare transformations, measured constants and fields the game demonstrably derives. Resolve unknown bytes needed to construct output; do not inherit them from an unrelated party's save. Preserve opaque data when editing in place. |
| Same-title directions | Enumerate both directions between the new platform and every supported peer with a port of the same title. Wish changes platforms; the game performs transfers between titles. A proven direction does not prove its reverse. |
| Successful conversion | Preserve the player's behavior with empty drop and loss lists. Refusing a valid save is unfinished conversion work. Establish any claimed platform capacity limit in the running game before designing how the player chooses what fits. Follow the [conversion rules](../.claude/rules/conversions.md). |
| Application output | Produce the exact bytes through the application's supported Save As/publication path, preserve the source and unrelated slots, and boot those published bytes as the player would. Extra harness repairs to the published container cannot count as application acceptance; use the [Open and Save As contract](227-editor-open-save-as.md). |
| Live conversion proof | Reuse the proven destination harness for each direction. Load, inspect, move, save, decode and reload the converted party; exercise the behavior the conversion changes and retain the identity and movement controls. Compare round trips using declared masks, not a mask built from whatever happened to differ. |

## Release gate and ownership

| Check | Requirement |
|---|---|
| Automated verification | Add meaningful reader, writer, container, direction and failure-path tests, including empty and extreme valid cases. Use generated inputs and private game-data tests through the registry; record skips and their causes. Prove regression tests fail without the fix. Follow the [testing rules](../.claude/rules/testing.md). |
| Review and CI | Run affected tests, relevant private tests, lint and generated-UI checks; complete required review and CI for the exact pushed SHA under the [commit rules](../.claude/rules/commits.md). Passing tests complements the live gates; it does not replace them. |
| Experimental gate | Keep incomplete platform functionality behind `WISH_EXPERIMENTAL_<FEATURE>`, with the default-off behavior verified and an explicit removal condition beside its definition. Remove the gate only after the claimed scope has passed these gates and its open defects are resolved; follow the [feature-flag rules](../.claude/rules/feature-flags.md). |
| Player interface | Obtain Donald's approval for new wording and appearance, including platform names, media requirements and destination controls. Follow the [GUI-text rules](../.claude/rules/gui-text.md); technical failures belong in useful diagnostics, not permanent explanations for missing conversion support. |
| Unresolved work | Every incomplete matrix row or failed gate names the failed step, evidence, next resolving action and owner in the tracker. A missing tool or dependency is work to assign, not grounds to mark the platform unsupported. Follow the [issue rules](../.claude/rules/issues.md). |
| Responsibility | The Wish orchestrator owns application and driver work, workers, tests, reviews and delivery. The host advisor owns authorized host/VM provisioning and maintenance. Donald owns support-scope and interface decisions. State the exact prerequisite when handing work between roles; a dependency on one repair does not require closing an unrelated whole ticket. |
| Durable documentation | Keep the support matrix and setup instructions explicit about proven scope, link evidence and outstanding owners, and add lookup rows for new modules and tools. Apply the [documentation rules](../.claude/rules/documentation.md); game content stays outside the repository under [AGENTS.md](../AGENTS.md). |
