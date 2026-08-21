# A debug mode, and Warp To — plan

**Status: researched, nothing built.** The research question — what the game
does when the party walks through an area exit — is answered, and the answer is
small enough to reproduce from outside.

---

## The finding: an area exit is nine bytes and an overlay restart

The hypothesis was right. **A script fires**, and it is the area's own `ECL`.
The exit is not a table of doorway squares in the map file and not a patched
filename; it is bytecode reached through the square-attribute dispatch that
`docs/50-experiments.md` already documented, and it ends in one opcode.

The shape, in every one of the eleven scripts that leave a map:

```
COMPARE [$6DD5], 0 / IF= / EXIT     ; only on a real step
CALL [$C01E]                        ; GDRIVE00 entry 10
SAVE 255, [$6DC9]                   ; cancel the move the party was making
[ SAVE <x>, mapX / <y>, mapY / <d>, mapDir ]   ; where you land, sometimes
[ SAVE <n>, [$6E12] ]               ; which POOL disk the next area is on
NEWECL <area>
```

`mapX`, `mapY`, `mapDir` are `$C04B`, `$C04C`, `$C04D` — the live party square
inside `GDRIVE00`, of which `$49C0`-`$49C2` is a lagging copy.

**`NEWECL` — opcode `$20`, handler `DUNGEON $2011` — is the whole transition.**
It does not load a map. It does five things:

| at | what | why it matters to us |
|---|---|---|
| `$2011`-`$2016` | `$49F2 = $6E1B & $7F` | the **outgoing** area id, which is how the arriving script knows where you came from |
| `$2019`-`$2023` | evaluate the operand; skip everything if it is `$FF` or equals the current id | **warping to the area you are already in is a no-op** |
| `$2025`-`$2027` | `$6E1B = new \| $80` | the ECL slot of the loaded-files cache, bit 7 = "reload me" |
| `$202A`-`$2032` | zero `$4A00`-`$4A1F` | the origin of the scratch/persistent split |
| `$2034`-`$203E` | `JSR $1A3C`, `INC $6DDD`, `LDX $03BF / TXS`, `JMP $0809` | flush the position, reset the stack, restart `DUNGEON` |

`$1A3C` is `if $49E6 then copy $C04B..$C04D into $49C0..$49C2` — so the save's
party position is written from the live one at exactly this moment, which is why
`$49C0` "lags a move".

The restart re-enters `DUNGEON` at `$0809`, which loads whatever in
`$6E13`-`$6E2B` carries bit 7 and then calls the new script's **entry 4**, the
area-initialisation entry (`work/reports/ecl-opcodes.md`, CONFIRMED). Entry 4
looks like this, in 26 of 30 scripts:

```
SAVE <n>, [$49FD] / SAVE <n>, [$49FE]     ; wall colours
LOADFILES <own GEO>, <n>, <n>             ; the map, at last
LOADPIECES <a>, <b>, <c>
COMPARE [$49F2], <own id> / IF= / EXIT    ; re-entry from itself: change nothing
[ SAVE <x>, mapX / <y>, mapY / <d>, mapDir ]
```

`LOADFILES`' handler is `$2041`: operand 1 goes to `$49C5` unless it is `$FF`,
and `$49C5` is then requested as **file type 2 (`GEO`)** when `$49E6` says
indoors, or **type 4 (`SQRDATA`)** when it says the overland map. Those are
cache slots `$6E15` and `$6E17`, mirrored in a save at `$4BC2` and `$4BC4`.

### Confidence

| claim | confidence |
|---|---|
| An exit is a per-square script id dispatched by the area's `ECL`, ending in `NEWECL` | **CONFIRMED** — the `GEO00` (6,2) prediction in `docs/50-experiments.md`, and eleven scripts with the shape above |
| `NEWECL` sets `$49F2`, `$6E1B\|$80`, zeroes `$4A00`-`$4A1F`, restarts at `$0809` | **CONFIRMED** — read off `DUNGEON $2011`-`$203E` |
| `$6E12` is the `POOL` disk the target area lives on | **CONFIRMED** — 32 of 33 static `SAVE n, [$6E12]` / `NEWECL t` pairs match the disk that carries `ECLt`; the one exception sets it in a `GOSUB` |
| The arriving script loads its own `GEO`, not the departing one | **CONFIRMED** — every script's `LOADFILES` first operand is its own id (see the exceptions below) |
| `$C04B`/`$C04C`/`$C04D` are the party square and writing them teleports | **CONFIRMED** — `$1A3C`; 29 of 30 scripts write them |
| A warp can be performed from outside by making those writes and setting PC to `$2034` | **GUESS** — the writes are the game's own, the entry point is not one the game uses from where we would use it |
| The loader prompts for a disk when `$6E12` names one that is not in the drive | **PROBABLE** — `LIBRARY $43A4` reads `$6E12`; nobody has watched it happen |

**A table of exit squares per area does not exist**, and neither does a patched
filename stem: `automap/area.py`'s `FilenameDigits` was already retired for the
same reason (`$24B4` reads six bytes of graphics). The two mechanisms the
evidence supports are the script and the cache slot; nothing else.

---

## The areas

Thirty scripts, twenty-nine maps, and they are not one-to-one. `ECL0C` does not
exist; `ECL08`, `ECL0B`, `ECL13` and `ECL1E` have no `LOADFILES` and therefore no
map of their own; three scripts carry two maps each.

Arrival is the square the game itself puts you on, harvested from the departing
scripts' `SAVE <n>, mapX` and from the arriving scripts' entry 4. Facing is
`0 N, 1 E, 2 S, 3 W`.

| id | `ECL` | `GEO` | disk | name | arrival | confidence |
|---|---|---|---|---|---|---|
| 0 | `00` | `00` | POOL3 | New Phlan | 15,1 W | CONFIRMED |
| 1 | `01` | `01` | POOL6 | Buccaneer Base | 8,0 S | CONFIRMED |
| 2 | `02` | `02` | POOL4 | Cadorna Textile House | 0,4 W | CONFIRMED |
| 3 | `03` | `03` | POOL5 | Valjevo Castle, a floor | — | PROBABLE |
| 4 | `04` | `04` | POOL5 | Valjevo Castle, a floor | — | PROBABLE |
| 5 | `05` | `05` | POOL5 | Valjevo Castle, a floor | — | PROBABLE |
| 6 | `06` | `06` | POOL5 | Valjevo Castle, a floor | 4,15 N | PROBABLE |
| 7 | `07` | `07` | POOL5 | Valjevo Castle, the pool | 5,7 | PROBABLE |
| 8 | `08` | — | POOL3 | Phlan City Hall | — | CONFIRMED |
| 9 | `09` | `09` | POOL2 | Stojanow Gate | — | CONFIRMED |
| 10 | `0A` | `0A` | POOL4 | Valhingen Graveyard | 0,4 W | CONFIRMED |
| 11 | `0B` | — | POOL3 | the arena | — | CONFIRMED |
| 13 | `0D` | `0D` | POOL8 | the kobold caves | 6,15 N | CONFIRMED |
| 14 | `0E` | `0E` | POOL3 | Kovel Mansion | 4,0 S | CONFIRMED |
| 15 | `0F` | `0F` | POOL2 | Mendor's Library | — | CONFIRMED |
| 16 | `10` | `10`, `1E` | POOL8 | the lizardman keep | 8,14 N | CONFIRMED |
| 17 | `11` | `11` | POOL7 | the nomad camp | 1,14 E | CONFIRMED |
| 18 | `12` | `12` | POOL1 | Podol Plaza | 0,4 W | CONFIRMED |
| 19 | `13` | — | POOL6 | Cave of Diogenes | — | CONFIRMED |
| 20 | `14` | `14` | POOL2 | the Slums | — | CONFIRMED |
| 21 | `15` | `15` | POOL4 | Sokol Keep | — | CONFIRMED |
| 22 | `16` | `16` | POOL7 | Yarash's pyramid | 15,7 E | CONFIRMED |
| 23 | `17` | `17` | POOL7 | Yarash's pyramid, lower | 15,0 S | PROBABLE |
| 24 | `18` | `18`, `1F` | POOL1 | Temple of Bane | 15,4 W | CONFIRMED |
| 25 | `19` | `19` + `SQRDATA04` | POOL6 | wilderness, west window | — | CONFIRMED |
| 26 | `1A` | `1A` + `SQRDATA05` | POOL7 | wilderness, middle window | — | CONFIRMED |
| 27 | `1B` | `1B` + `SQRDATA06` | POOL8 | wilderness, east window | — | CONFIRMED |
| 28 | `1C` | `1C` | POOL6 | Zhentil Keep outpost | 7,0 S | CONFIRMED |
| 29 | `1D` | `1D`, `20` | POOL8 | Kuto's Well (and its catacombs) | — | CONFIRMED |
| 30 | `1E` | — | POOL1 | unidentified | — | UNKNOWN |

Names come from `docs/88-map-files.md` (nine city blocks matched by wall
geometry), `work/reports/world-map.md` (the wilderness site list) and
`work/reports/quest-flags.md`. The five POOL5 floors are a castle because
`ECL07` writes ledger flag 20 and prints the party leaving one; **which floor is
which is not known**, and reading them is exactly the job
`docs/115-review-the-scripts.md` is waiting on a human for.

Fifteen areas have no known arrival square. For those the warp supplies one
itself — see below — and the dropdown says so.

---

## 1. Where debug mode lives

**Recommendation: an environment variable, `WISH_DEBUG=1`, with `--debug` as an
alias that sets it. No `Settings` field, no persistence.**

`wish/window.py` already makes the argument for the debug log: *"Off at every
start, and deliberately not remembered: a logging setting that survives a
restart is one you forget is on."* A mode that **writes to the running game**
earns that rule twice over. A `Settings` flag is the one option to reject
outright.

An env var over a menu item alone, because the consumer is an unattended test
harness that cannot click. An env var over a bare flag, because `wish`,
`wish-editor` and `wish-automap` are three entry points and the packaged build
is launched from a desktop file; one variable covers all of them.

New module `wish/debugmode.py`, about fifteen lines: `enabled()` reads the
variable once, `enable()` for `--debug` and for tests. Nothing else imports
`os.environ`.

What it gates, and only this:

* the Warp row on the automapper screen;
* a line in the debug log each time a warp is attempted, with the addresses
  written — the log's privacy claims are unaffected, these are our own writes;
* later, if wanted: a raw-poke box and a "run script entry" control, which the
  same research makes almost free (`$6E47`/`$6E48` is the VM's PC and `$1581` is
  its fetch loop).

Nothing about the editor changes. Nothing about the save-file path changes.

---

## 2. The Warp To control

A row under the map, beside `ActionBar`, in the map's own column — the same
argument that put the actions there: it acts on what is drawn above it.

* **`QComboBox`**, thirty entries, sorted by name with the unidentified last.
  Each row reads `New Phlan — GEO00, POOL3`. An area with no name reads
  `ECL1E — no map, POOL1`, which is honest and still selectable.
* **`Warp To` button**, disabled with the reason in its tooltip, exactly as
  `ActionBar` does it: no emulator, not `ViceTarget`, `$6E11 != 1`, or the
  selected area is the current one.
* **A disk line** under the row: `needs POOL7 — POOL3 is in drive 8`. This is
  the same free win `docs/113-world-map.md` identified for the overland map.
* **`Warp Back`**, which restores the id and square captured before the last
  warp. One button, and it turns a warp from a one-way trip into a probe.

The area table is data, not UI: **`por/areas.py`**, a frozen dataclass per area
carrying id, `ECL`, `GEO`s, disk, name, confidence and arrival square, generated
into this document by `tools/gendocs.py` the way `por/layout.py` already is.
`automap/state.py`'s `AREA_NAMES` becomes a view over it, so there is one table
and not two.

---

## 3. What a warp writes

Preconditions, all read first, one round trip:

| read | must be |
|---|---|
| `$6E11` | `1` — `DUNGEON` is the resident overlay |
| `$6E1B & $7F` | not the target; `NEWECL` skips a same-area transition and so would we |
| `$49E6` | non-zero for a `GEO` area, zero for the overland map |
| PC | inside `DUNGEON`'s world key-wait loop at `$10C2` — not mid-script, not mid-load |

Then, in this order, and this is the game's own sequence with the operand
evaluation removed:

| # | write | bytes | from |
|---|---|---|---|
| 1 | `$6E12` = disk number | 1 | the departing scripts' `SAVE n, [$6E12]` |
| 2 | `$C04B`-`$C04D` = x, y, facing | 3 | the arrival square, when we are supplying one |
| 3 | `$49F2` = current `$6E1B & $7F` | 1 | `$2011`-`$2016` |
| 4 | `$6E1B` = target \| `$80` | 1 | `$2025`-`$2027` |
| 5 | `$4A00`-`$4A1F` = zero | 32 | `$202A`-`$2032` |
| 6 | PC = `$2034` | — | the tail of `NEWECL`, run as the game runs it |

Then resume. **Entering at `$2034` rather than `$2011` is the whole trick**: it
skips the operand fetch, which needs a script stream we are not in, and keeps
`JSR $1A3C` (flush `$C04B` into `$49C0`) and `INC $6DDD`, which we would
otherwise have to guess at. `$203A` reloads the stack pointer from `$03BF`, so
the call depth we interrupt does not matter and the `JSR` at `$2034` costs
nothing.

**Copied from observed behaviour:** writes 1, 3, 4, 5 and the entry at `$2034`.
**Guesses to be tested:** that the key-wait loop is a safe place to hijack the
PC from, and that `$C04B` survives the overlay restart — it is in `GDRIVE00`,
which is resident and not reloaded, so it should, but nothing has watched it.

### Where the party lands

Three cases, in order:

1. **The arriving script sets it** (areas 1, 16, 17, 22, 23, 28) — write nothing
   and let entry 4 do its job.
2. **We know a square another script uses** (the arrival column above) — write
   that. It is the game's own answer for that door.
3. **Neither** — pick a square from the target `GEO` read off the player's disk:
   the first square with at least one passable edge and, where the automapper
   has explored the area before, a square it has recorded the party standing on.
   `por/geo.py` already answers both questions and needs no emulator.

Keeping the party's current square is the one option to avoid: the maps do not
line up and (13,13) in the Slums is a wall in Sokol Keep.

---

## 4. Failure modes, and why it is off by default

| failure | what it looks like | guard |
|---|---|---|
| wrong disk in drive 8 | `LIBRARY` prompts and the game sits there | read `$6E12`'s disk and say so before warping; time the warp out and report |
| `$6E11 != 1` | `$2034` is some other overlay's code — an immediate crash | refuse; re-check at apply time, not only in the tooltip |
| PC mid-script or mid-load | the stack reset discards work in flight; the screen may be left half-drawn | refuse unless the PC is in the key-wait loop |
| target == current area | nothing happens, silently, and `$4A00` is not cleared | refuse, with the reason |
| arrival square is a wall or off-map | not a crash — the party stands inside a wall and cannot move | choose the square from the map, never carry one over |
| **quest flags are inconsistent** | the arriving script assumes things the party never did | unavoidable, and the honest answer is to say it in the tooltip: a warp is not the same as playing there |
| the player saves after a warp | a save disk with that inconsistency baked in | debug mode must be pointed at a **copy**; the automapper never writes a disk and this does not change that |

`/home/donald/c64/Pool of Radiance Disks/` is read-only for this project and
warping does not change that: every byte here goes to RAM. The rule that matters
is the one above it — **attach a copy to the emulator**, because the game's own
save command will happily write a warped party out.

Off by default because it writes to a running machine on a control that is one
click from the map, and because a feature nobody in normal play needs should not
be on the screen at all.

### One hazard that is no longer a hazard

`(6,2)` in New Phlan does **not** wedge input. That claim was withdrawn in
`docs/50-experiments.md`, "There is no training-hall wedge, and it was never
(6,2)": stepping `(6,2) → (7,2)` is an ordinary encounter that takes about 25
seconds to load, the status line keeps reading `6,2` for the whole of it, and
the four runs that "died there" were four runs of one wrong assumption. The
real lesson for a warp harness is the timeout: **allow 30 seconds for an area
change**, not five.

---

## 5. What it unlocks

Every one of these needs a party standing somewhere it takes an evening of play
to reach.

* **`automap/area.py` against all 29 maps.** `ResidentGeo` matches `$0400` byte
  for byte against the disk copies; warping to each area in turn turns that into
  a 29-case test instead of one anecdote about New Phlan.
* **`Fingerprint.refused()`, which nothing calls.** `docs/50` notes that one
  refused step identifies New Phlan instantly where 111 positive steps are
  needed. A warp plus a scripted walk into a known wall produces that step on
  demand.
* **The overland map.** `docs/113-world-map.md` is blocked on W1 — "the first
  step onto the travel grid" — and on 648 live bytes at `$8C00`. Warping to area
  26 gets a party outdoors in a second, and it is the single largest thing this
  unblocks.
* **Combat and the combat view**, by warping to a floor with a fixed patrol
  rather than waiting on a wandering-monster roll.
* **The commissions panel**, against `ECL08` (City Hall), where the ledger the
  panel reads is actually written.
* **`GEO1E`, `GEO1F`, `GEO20`** — the three maps that share a script with
  another and that no fingerprint has ever seen.

---

## 6. Verification

A warp worked if all four hold. The first three are memory reads and cost one
round trip together.

| check | address | expected |
|---|---|---|
| the script changed | `$6E1B & $7F` | the target id |
| the map changed | `$6E15 & $7F` (`$4BC2` in a save) | the target's `GEO` number |
| **the map is the right map** | `$0400`-`$07FF` | byte-identical to the disk copy — `ResidentGeo.identify()` |
| the party is somewhere sane | the game's own status line | a square that is walkable on that map |

The third is the one that matters and it already exists: an exact 1024-byte
match against the file, so a hit is certain and needs no fingerprinting.

Automated, the whole thing is one function:

```
warp(area) -> poll ResidentGeo.identify() every 200 ms for 30 s
           -> assert it equals the expected GEO name
           -> assert the status-line square is passable on that map
```

Unit tests need no emulator: `Warp.apply` returns the same `Outcome` the actions
return, with `writes` as `(address, bytes)` pairs, so the sequence above is
asserted against `MemoryTarget` and a recording stub for the PC. That is how
`tests/test_actions.py` already works.

---

## Open questions only a live session can settle

Each of these is one experiment, and none of them needs more than a few minutes
at the monitor.

1. **Is `$2034` safe to enter from the key-wait loop?** Stand in New Phlan, make
   the five writes, set PC to `$2034`, resume. Watch for the drive light, then
   for `$0400` to change. This is the experiment the whole plan rests on.
2. **Does `$C04B` survive the restart?** Write a square that is not the current
   one, warp, and read `$C04B` and the status line afterwards. If it does not,
   the arrival square has to be written after the load instead, which means a
   second stop on a checkpoint at the end of entry 4.
3. **What does the loader do with the wrong disk in the drive?** Warp from a
   POOL3 area to a POOL7 one with POOL3 attached and photograph the screen. If
   it prompts, the harness needs a disk-attach step — and `automap/vice.py`
   implements no attach command, so that is a second question: whether VICE's
   binary monitor can attach an image, or whether the harness must relaunch.
4. **Does a warp to an area with no known arrival square land somewhere legal?**
   Try areas 3, 4, 5, 9, 15, 20, 21, 29 with a square chosen from the `GEO` and
   see whether the party can walk.
5. **Is `$6DD5` really "a step was taken"?** Every exit handler gates on it and
   nothing has confirmed what sets it to zero. It is read by 18 scripts and
   written by `DUNGEON $0B05`/`$10EE`, which is a five-minute watchpoint.
6. **What is `ECL1E`?** No script contains a static `NEWECL 30`, it has no
   `LOADFILES`, and it is the one area with no name at all. Warping to it is the
   cheapest way to find out, and is a good first use of the button.
7. **Does the overland map warp the same way?** Areas 25-27 go through the
   `$49E6 == 0` branch of `LOADFILES` and load a `SQRDATA`, not a `GEO`.
   Everything above assumes the indoor branch.
