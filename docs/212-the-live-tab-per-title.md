# The live automapper tab, measured on all three titles

`#34 (Validate the live automapper tab per title)` asked for the automapper
tab to be validated title by title, in the order its own body sets out: draw
the map and walk it, cross an area boundary and read the area byte either
side, the roster cards, the condition and quickfight badges, and each of the
five live actions. Until 2026-09-08 that had been done on Pool of Radiance
alone; `docs/139-per-title-validation.md`'s C-rows carried fourteen `U` for
Curse of the Azure Bonds and sixteen for Secret of the Silver Blades.

This page is what three driven sessions found. The results themselves are in
`docs/139`'s matrix, which is where somebody looks them up; what is here is
the run, the method and the things that went wrong on the way.

## 0. The answers

**Ten checks, three titles, thirty passes and no failures.** The runs are
`work/issue34/por5`, `work/issue34/curse6` and `work/issue34/ssb6`, taken on
2026-09-08 against `automap/` as it stands at `edcf842`.

| `docs/139` row | check | Pool of Radiance | Curse | Silver Blades |
|---|---|---|---|---|
| C7 | the map is identified and drawn | `GEO00`, New Phlan | `GEO01` | `GEO10` |
| C12 | the roster cards read the party | 6 cards, 18/18 fields | 6, 18/18 | 6, 18/18 |
| C13 | a condition badge is drawn from a staged effect | `running-ninja` | `running-ninja` | **none, by design** |
| C7W | the marker follows a walk | 4/4 steps | 4/4 | 4/4 |
| C6 | the area is re-read across a boundary | `GEO00` to `GEO01` | `GEO01` to `GEO03` | `GEO10` to `GEO20` |
| C16 | Heal party | MELCAR 1 to 6 | PALADIN | MORGAINE 1 to 35 |
| C17 | Save and Restore spells | MELCAR, SLEEP | PALADIN | PAINE |
| C18 | Identify | 1 item | 1 item | 1 item |
| C14, C19 | the quickfight badge, lit and cleared | slot 5, `$83AC` | yes | yes |
| C20 | Level up | offered | offered | **refused, writing nothing** |

The two bold cells are refusals, and both are the shipped behaviour being
right rather than a gap: Silver Blades has no badge table (`#196 (The automapper's condition badges name a Silver Blades trait with Pool of Radiance's meaning)`) and its
trainer has never been measured (`#16 (Level Up assumes Pool of Radiance, and silently corrupts a Curse character)`, `goldbox.levels.trainer_measured`).
Each was measured as a refusal rather than assumed -- §2 and §3.

## 1. The run is the shipped code, called

`tools/livecheck.py` boots a title on a pooled VICE slot from a save disk in
the specimen tree, gets the party into the world, and then calls the tab's own
code:

| what it reports | what it calls |
|---|---|
| the marker, the area, the explored set | `automap.state.Automapper.poll()` |
| a roster card | `automap.live.read_snapshot` |
| a condition badge | `automap.live.badges`, through `Character.conditions` |
| the quickfight badge | `Character.quickfight`, off roster `+0x0C` bit 7 |
| the five buttons | `automap.actions.HealParty`, `StoreSpells`, `RestoreSpells`, `IdentifyItems`, `ClearQuickfight` |
| a boundary crossing | `automap.actions.FastTravel` |

**A tool that reproduced any of those its own way would be measuring itself.**
`tools/ssbwarp.py` makes that distinction for one action already -- its
`--via-actions` exists because its own `warp()` writes the same six bytes and
proves nothing about the code a player runs -- and this file is that argument
applied to the whole tab.

## 2. What is new, and what it rests on

**The first Curse and Silver Blades maps ever drawn from a running machine.**
Both identified their area by an exact byte match of the block at `$0400`
against the disk copies -- `GEO01` in Curse, `GEO10` in Silver Blades -- and
`Automapper.title_check` came back `ours` on both, which is `#21 (The running game is guessed from a preference, so both title safeguards can fail open)`'s safeguard
agreeing rather than abstaining. The drawn map is written out as SVG through
`automap.render.to_svg`, the same geometry the window paints, whole and
explored-only.

**The square and the facing came from the game's own status line on all
three.** `Fix.source` reads `status`, not `memory`, so `party_fix`'s
title-independent claim -- every title draws `E 16:48  5,2` on row 14 -- is
now watched on the later two rather than argued from the code. The memory
fallback at `$C04B` was measured separately under `#29 (The live reader uses Pool of Radiance's addresses on every title)`.

**The live cards were crossed against the same save read cold off the disk.**
Name, maximum hit points and experience for every character, from
`goldbox.savegame.load_save` on one side and `live.read_snapshot` on the
other: 18 of 18 fields on each title, 0 disagreements. A matching name from
one reader is the reader agreeing with itself; from two independent ones it is
evidence.

**The save image's own area byte does not follow a fast travel; the resident
map does.** Across all three crossings the block at `$0400` changed to the
arriving area's map and `AutomapState.area` followed it, while
`SaveGame0.area` in the resident save image still named the area the party
left, twenty seconds after the arrival:

| title | resident, before | resident, after | header area byte, after |
|---|---|---|---|
| Pool of Radiance | `GEO00` | `GEO01` | still 0 |
| Curse | `GEO01` | `GEO03` | still 1 |
| Silver Blades | `GEO10` | `GEO20` | still 16 |

That is the resident image being a copy the engine rewrites when it saves,
rather than live state, and it is why the automapper identifying an area from
`$0400` rather than from the header is the right reading. CONFIRMED, three
titles, one crossing each.

**A badge was drawn, on a title that had never drawn one.** Nothing in the
corpus would have produced one: no save this project holds, for any title, has
a spell running, so a badge check over what is there reports "no badge drawn"
-- which is also what a broken `badges()` reports. So one effect row is
written into the four arrays the way the game writes one -- id at `+$000`,
owner at `+$040`, duration at `+$080`, magnitude at `+$280`, all four measured
in every title under `#31 (Cold-read Curse and Silver Blades for the fields the editor shows)` -- and the card is read back through
`live.read_snapshot`. Effect 39 is hasted, and it is the one glyph in
`live.CONDITION_BADGES` covering exactly one id, so a badge drawn from it can
only have come from that row.

* Pool of Radiance, `$4900`/`$4940`/`$4980`/`$4B80`: `running-ninja` on
  GARWAN's card.
* Curse, `$4B00`/`$4B40`/`$4B80`/`$4D80`: `running-ninja` on MALE ELF MAGE's.
* Silver Blades, the same four addresses: **the card carries the effect and
  draws no glyph**, and the id turns up in `Character.unbadged_effects`
  instead. That is `#196 (The automapper's condition badges name a Silver Blades trait with Pool of Radiance's meaning)`'s deliberate refusal measured rather than assumed --
  sixteen of the seventeen badged ids are unnamed in
  `traits.NAMES_SILVER_BLADES`, so a glyph there would assert a meaning
  nobody has read.

**Level up refuses on Silver Blades in `run`, not in `legality`.** The action
answers *legal* there, because `Action.legality` only asks the loader's mode
flag; what refuses is `level_up_blockers` inside `run`, and the window
additionally never builds the button (`roster.levelling` is False). So the
check runs the action and measures that it wrote nothing:
`levelling MORGAINE would write fields we cannot derive, so it writes
nothing`, 0 writes. On Pool of Radiance and Curse there are no blockers and
the action is offered -- which is `#18 (Measure Curse's trainer so Level Up works there)` having measured Curse's trainer, and
is a row `docs/139` still carried as a refusal.

**The quickfight bit had never been seen set on any title.** `docs/139`'s C14
said so: the flag resolved to `$670C` on both later machines under `#29 (The live reader uses Pool of Radiance's addresses on every title)` and
nobody was ever on quickfight. Here it is staged into roster `+0x0C` bit 7,
`Character.quickfight` reads it back True -- which is the badge a card draws --
and `ClearQuickfight` then puts it out, on all three titles.

### Staging a byte is how four of these are reachable at all

No save this project holds has a character on quickfight, an unidentified
item, or (in the Curse party that carries items) a memorised spell. A check
that reports "nothing to do" in those cases is measuring the corpus rather
than the program, so four checks write an input first:

| check | staged | why the write is not the result |
|---|---|---|
| Heal party | current hit points to 1 in the roster block | `HealParty` finds the wound and writes the maximum; the read-back is `live.read_snapshot`'s |
| Quickfight off | roster `+0x0C` bit 7 | `Character.quickfight` reads it, `ClearQuickfight` clears it, and the read-back is a fresh snapshot |
| Identify | an item's hidden-name bits `+6` low three | `IdentifyItems` finds them and clears them, and the byte is read again four seconds later through `live.read_blocks` |
| Save spells | one spell id, where nobody has any | neither action goes through the engine, so an id put there from outside is the same input a night's rest leaves |

This is the distinction `.claude/rules/testing.md` draws: editing an **input**
and watching the code compute from it is a valid experiment; reading back a
value our own writer stored and calling it the game's is not.

**The memorised list is spoiled before it is restored.** `RestoreSpells` writes
nothing when the bytes already match, so a read-back with the list left alone
is the store's own copy coming home. The check zeroes the span first -- what
the answer cannot be -- and only then restores.

## 3. Identify sticks, which was not certain

`automap/actions.py:IdentifyItems` carries a warning that its write may not
stick: the item area is a copy fed from a master elsewhere, and a poked weight
was reverted by the game. So the check reads the flag byte again four seconds
of emulated time later, through `live.read_blocks` rather than out of the
writer's hands. On all three titles the cleared bits were still cleared.

That is one reading per title, on one item each, taken seconds after the
write. It says the copy is not refreshed immediately; it does not say a
subsequent area load leaves it alone. **PROBABLE**, and the experiment that
would settle it is to identify, then cross an area boundary, then read the
same byte.

## 4. Five harness faults, all ours

**Moving `$XDG_DATA_HOME` stops VICE launching.** The first version of
`livecheck.py` reassigned it, to keep a validation run's explored squares out
of the player's real map notes. A Flatpak *user* installation lives under
`$XDG_DATA_HOME/flatpak`, so `tools/porlaunch.sh`'s `flatpak run net.sf.VICE`
stopped finding the installed emulator, fell back to the system installation,
defaulted to the `master` branch and wrote `app/net.sf.VICE/x86_64/master not
installed` into the slot's `vice.log`. Three boots died three seconds in, and
all the Python saw was `RuntimeError: VICE never came up`. The tool rebinds
`automap.state._data_dir` instead, and
`tests/test_livecheck.py::test_importing_the_tool_leaves_xdg_data_home_alone`
fails without that. **Read the slot's `vice.log` when a boot never comes up**:
it had the answer within three seconds and nothing else did.

**The Silver Blades driver would not press a movement key**, and said so:
*"the driver pressed nothing: it read this party as being on the travel grid,
where I is not a direction. That is a driver error and not a wall."*
`tools/ssbwarp.py`'s `SSBSession` never sets `Session.game`, so `indoors()`
reads Pool of Radiance's `$49E6` -- a byte of `LIBRARY` code in this title
that happens to read zero. It is `#360 (The session driver will not walk a Curse or Silver Blades party in a dungeon, because it reads Pool of Radiance's indoors flag)`'s defect surviving in the one driver
`#360 (The session driver will not walk a Curse or Silver Blades party in a dungeon, because it reads Pool of Radiance's indoors flag)` did not touch, and Curse, whose subclass does declare its title, walked
in the same batch as the control. Filed as `#426 (The session driver will not
walk a Silver Blades party, because SSBSession never says which title it is)`.

**A walk starts fights, and every action is refused in one.** The first Pool
of Radiance run left the Slums, took four steps into a wandering encounter,
and Heal party, Fast Travel and Level up all answered "refused during a
fight". That is the gate working and it measured nothing, so the actions now
run before the walk and Pool of Radiance's default save stands in New Phlan,
which has no wandering monsters.

**A Flatpak emulator cannot be launched from a worktree under `/tmp`.**
Measuring at `HEAD` while another agent had `automap/actions.py` uncommitted
meant a detached worktree, and the obvious place for one is the session's
scratch directory. `tools/porlaunch.sh` runs `flatpak run net.sf.VICE`, and
the Flatpak's own filesystem permissions do not include `/tmp` -- so `Xvfb`
came up, `x64sc` never did, and three runs failed with
`RuntimeError: VICE never came up` and an empty process list. The worktree
has to sit somewhere under the home directory. The symptom that names it is
`ps` showing `Xvfb` and no `x64sc` at all.

**A route can end where it started and still have been followed.** `JIKI`
against a wall is turn, blocked forward, turn back, blocked forward: the
marker tracked both turns and the first and last readings are identical. The
verdict is per step now -- the marker changed exactly on the steps the driver
saw the game accept, and every step the marker and the game's own status line
agree on the square and the facing.

## 5. What this run did not establish

* **The combat view and the combat log on the later titles.** `docs/139`'s
  C10 and C11, and out of scope by that document's own G7: the addresses are
  Pool of Radiance's overlay's and re-deriving them is a project. Nothing here
  opened either on Curse or Silver Blades.
* **A *walked* boundary.** The crossing here is Fast Travel, which is the
  button a player presses and needs no route somebody has already found. A
  party walking through a door into another area is a different path through
  `Automapper.poll` -- `_area_may_have_changed` and the jump guard -- and it
  is untested on the later two titles.
* **Whether an identified item survives an area load.** §3.
* **The badge *names* on Silver Blades.** `live.BADGE_TABLES` gives that title
  no groups, so it draws none; that is the deliberate refusal `#196 (The automapper's condition badges name a Silver Blades trait with Pool of Radiance's meaning)` built and
  what this run confirms is that it refuses rather than that the refusal is
  right. Naming its effect codes is still unread work.
* **Anything on the three Krynn-era titles.** They have no `mode_flag` and no
  `live_position`, so every action refuses and the memory fallback answers
  None. Nothing here changes that.

## 6. Re-running it

    tools/livecheck.py --title por   --walk JIKI --boundary --out work/issue34/por
    tools/livecheck.py --title curse --walk JIKI --boundary --out work/issue34/curse
    tools/livecheck.py --title ssb   --walk JIKI --boundary --out work/issue34/ssb

Each claims its own pool slot, copies the player's disks into it and reads
them only, and tears the slot down at the end. The save disks come out of the
specimen tree, so the run does not depend on anything under `work/`:

| title | save disk | why that one |
|---|---|---|
| Pool of Radiance | `WISH-SPEC-por-amiga-newphlan-c64-resave.D64` | a town, so no wandering monsters, and seventeen items with sixteen readied |
| Curse | `WISH-SPEC-curse-party-with-items.D64` | the only Curse save anybody has with an item area in it (`#32 (One Curse session, to get a party with items)`), added to the tree by this work |
| Silver Blades | `WISH-SPEC-ssb-d-engine-resave-walked.D64` | an engine-written save of a converted party, standing in `GEO10` |
