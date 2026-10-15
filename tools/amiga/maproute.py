"""Measured game sequences and inputs for a Wish window beside WinUAE."""

from __future__ import annotations

import dataclasses
import pathlib
import re
from collections.abc import Mapping
from typing import Literal

from goldbox import amiga_adf
from tools.amiga import route_curse, route_darkness, route_pool, route_silver_blades
from tools.amiga.route import AmigaTitle
from tools.amiga.winuaesession import RouteError


@dataclasses.dataclass(frozen=True)
class Media:
    key: str
    path: pathlib.Path
    sha256: str


@dataclasses.dataclass(frozen=True)
class Expected:
    engine: Mapping[str, int] | None = None
    window: Mapping[str, int] | None = None
    compare_to: str | None = None
    relation: Literal["equal", "stationary", "moved", "area_changed", "view_changed"] | None = None


@dataclasses.dataclass(frozen=True)
class Read:
    """Bytes read at a checkpoint for the record only; no verdict depends on them.

    The address is `offset` from `anchor`: `abs` is zero, `base` the located data hunk and
    `a4` that hunk plus the A4 bias, as `--read-at` counts them. With `hop`, the big-endian
    long at that address is a pointer and the bytes are read at the pointer plus `hop`.
    """

    name: str
    anchor: Literal["abs", "base", "a4"]
    offset: int
    length: int
    hop: int | None = None


@dataclasses.dataclass(frozen=True)
class Step:
    kind: Literal[
        "key", "turn", "move", "insert", "answer", "snapshot", "restore",
        "encounters", "select", "observe", "type", "reset",
    ]
    state: str
    key: str | None = None
    drive: int | None = None
    media: str | None = None
    snapshot: str | None = None
    encounters: bool | None = None
    checkpoint: str | None = None
    expected: Expected | None = None
    #: A `type` step's keys, each sent once `screen` is recognized, then one wait for `state`.
    keys: tuple[str, ...] = ()
    #: The screen a `type` step's keys go to, recognized again before every key.
    screen: str | None = None
    #: The step starts the game program again, so memory read before it is stale. A `reset`
    #: step, which soft-resets the emulated Amiga, always does.
    relaunch: bool = False
    #: Read-only bytes recorded with the step's checkpoint.
    reads: tuple[Read, ...] = ()


@dataclasses.dataclass(frozen=True)
class Phase:
    name: str
    initial_state: str
    steps: tuple[Step, ...]
    ready: bool = True
    reason: str | None = None
    #: The title's interstitial screens this phase may answer while it waits for a step's screen.
    pages: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class Action:
    kind: Literal["heal", "spells", "identify", "quickfight", "levelup"]
    enabled: bool
    selector: Literal["hp", "memorised", "item", "controlled", "levelup"] | None
    show: Phase | None
    back: Phase | None


@dataclasses.dataclass(frozen=True)
class MappingRoute:
    title: str
    game_key: str
    amiga_title: AmigaTitle
    guard_path: pathlib.Path
    media: tuple[Media, ...]
    mounted: tuple[str, ...]
    loaded_slot: str
    phases: tuple[Phase, ...]
    actions: tuple[Action, ...]
    provenance: Mapping[str, object]
    unresolved: tuple[str, ...] = ()


_GAME_KEYS = {
    "pool": "pool-of-radiance",
    "curse": "curse-of-the-azure-bonds",
    "ssb": "secret-of-the-silver-blades",
    "darkness": "pools-of-darkness",
}
_GUARD_NAMES = {
    "pool": "guards_pool.json",
    "curse": "guards_curse.json",
    "ssb": "guards_silver_blades.json",
    "darkness": "guards_darkness.json",
}
_SHA256 = re.compile(r"[0-9a-f]{64}")
_SLOT = re.compile(r"[A-Z]")
_REQUIRED = ("load", "stationary", "walk", "transition", "reload", "reopen_step")
_POOL_OUTDOOR_SHA256 = "4c2bf105215976eaafaa89f07a5da3e06ff838357e07eacd13afe0d1376fddf3"
_CURSE_WORLD_SHA256 = "c88dd261fb83772128a76e34cf09dc83dc6d5039c60c031a1432df5e48e04896"
#: The registered Curse game save in Yulash, imported from its slot C into prepared slot B.
_CURSE_YULASH_SHA256 = "8a28aaf5fe7226c81b0931fce22709c51e9648ae759f4b90fbb37f6bf8b24fdf"
_CURSE_YULASH = {"area": 16, "x": 2, "y": 6, "facing": 1}
#: Pools of Darkness slot B in Aerie. The save records area 2; the resident map is GEO21,
#: which the controller reports as area 33.
_POD_AERIE = {"area": 33, "x": 1, "y": 2, "facing": 1}
#: Pool's travel grid at the New Phlan dock, map-window square 7,29 facing east. The resident
#: grid map is no geo.dax block, so no area is expected on the grid.
_POOL_DOCK = Expected(engine={"outdoors": True, "facing": 1}, window={"x": 7, "y": 29})


@dataclasses.dataclass(frozen=True)
class SpellsParty:
    """A registered party whose Cast list shows Save and Restore spells clearing a spell.

    `route_for` gives it the load and the camp reload and no mapping phase, so only the
    persist leg can run it. `specimen` names the registered folder without `WISH-SPEC-`.
    """

    specimen: str
    file: str
    sha256: str
    letter: str
    place: Mapping[str, int]
    #: The first member by party slot with a memorised spell, whom the spells selector picks.
    member: str


#: One spells party per title whose mapping party cannot show a cleared spell.
SPELLS_PARTIES = {
    # The game's own save of slot C in Tilverton. SHARA holds Find Traps (22) twice at record
    # +0x70 and +0x71, so clearing the first leaves one in her Cast list; PHILIPPE holds
    # Magic Missile, Stinking Cloud and Fireball (15, 34, 47) at +0x6F to +0x71.
    "curse": SpellsParty(
        "wish-677-curse-mn2xe43ffvzwqylsmu-mfrwgzlqoqyq", "fetched-df0.adf",
        "85966196be11013bee365d62006976c4444c6dbd763ac96f137f38d831c8b787", "C",
        {"area": 1, "x": 5, "y": 13, "facing": 3}, "SHARA"),
    # The game's own save of slot C in New Verdigris. PAINE holds Invisibility to Animals
    # (80) at record +0x68, the only memorised spell in any Silver Blades save registered.
    "ssb": SpellsParty(
        "wish-667-ssb-heywcmjtgzrwklltoawxa33tgi-meza", "fetched-df0.adf",
        "b6538d4e540baea597905f27a6713d263f4223e9fe26791fcb4d61ceaef1facd", "C",
        {"area": 16, "x": 3, "y": 3, "facing": 2}, "PAINE"),
}
_SPELLS_SLOT = {"curse": "B", "ssb": "D"}
_PERSIST_ONLY = "The spells party is pinned for the persist leg, which walks no mapping phase."


def _slot_from(manifest: Mapping[str, object]) -> str:
    slot = manifest.get("loaded_letter", manifest.get("slot_letter"))
    if not isinstance(slot, str) or not _SLOT.fullmatch(slot):
        raise RouteError("Prepared manifest needs one loaded_letter or legacy slot_letter")
    legacy = manifest.get("slot_letter")
    if legacy is not None and legacy != slot:
        raise RouteError("Prepared manifest loaded_letter and slot_letter disagree")
    return slot


def _entry(key: str, raw: object) -> Media:
    if not isinstance(raw, Mapping):
        raise RouteError(f"Prepared manifest has no {key} media entry")
    source, digest = raw.get("path"), raw.get("sha256")
    if not isinstance(source, str) or not pathlib.Path(source).is_absolute():
        raise RouteError(f"Prepared manifest {key} needs an absolute media path")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise RouteError(f"Prepared manifest {key} needs a SHA-256")
    return Media(key, pathlib.Path(source), digest)


def _media_for(title: str, manifest: Mapping[str, object], base: AmigaTitle
               ) -> tuple[Media, ...]:
    disks = manifest.get("disks")
    if not isinstance(disks, Mapping):
        if title != "ssb":
            raise RouteError("Prepared manifest has no disks table")
        disks = {key: manifest.get(key) for key in ("df0", "df1")}
    return tuple(_entry(key, disks.get(key)) for key in base.disk_keys)


def _phase(name: str, initial: str, *steps: Step, pages: tuple[str, ...] = ()) -> Phase:
    return Phase(name, initial, steps, pages=pages)


#: The Silver Blades opening story's continue pages, and the treasure offer that can stand in
#: for the camp bar, answered while the opening-scene load and the camp reload wait.
_SSB_STORY_PAGES = ("continue", "treasure")


def _missing(name: str, initial: str, reason: str) -> Phase:
    return Phase(name, initial, (), ready=False, reason=reason)


def _load(title: str, slot: str, opening_scene: bool = False,
          curse_yulash: bool = False, curse_square: Mapping[str, int] | None = None) -> Phase:
    if title == "pool":
        return _phase(
            "load", "title",
            Step("key", "party_menu", key="RET"),
            Step("key", "save_path", key="L"),
            Step("key", "load_picker", key="RET"),
            Step("key", "grid", key=slot, checkpoint="loaded", expected=_POOL_DOCK),
            Step("key", "sheet", key="V", checkpoint="load_sheet"),
            Step("key", "grid", key="E"),
        )
    if title == "curse":
        return _phase(
            "load", "title",
            Step("key", "load_picker", key="L"),
            Step("key", "loaded_menu", key=slot),
            Step("key", "sheet", key="V", checkpoint="load_sheet"),
            Step("key", "loaded_menu", key="E"),
            Step("key", "world", key="B", checkpoint="loaded",
                 expected=(Expected(engine=_CURSE_YULASH) if curse_yulash
                           else Expected(engine=curse_square) if curse_square else None)),
        )
    if title == "ssb":
        prefix = (
            Step("key", "party_menu", key="P"),
            Step("key", "load_picker", key="L"),
            Step("key", "loaded_menu", key=slot),
            Step("key", "sheet", key="V", checkpoint="load_sheet"),
            Step("key", "loaded_menu", key="E"),
            Step("key", "journal", key="B"),
        )
        expected = Expected(engine={"area": 16, "x": 3, "y": 3, "facing": 2})
        if opening_scene:
            # The opening pages between these steps are the title's continue interstitials.
            return _phase(
                "load", "title", *prefix,
                Step("answer", "treasure_bar"),
                Step("key", "treasure", key="E"),
                Step("key", "world", key="N", checkpoint="loaded", expected=expected),
                pages=_SSB_STORY_PAGES,
            )
        return _phase("load", "title", *prefix,
                      Step("answer", "world", checkpoint="loaded", expected=expected))
    return _phase(
        "load", "title",
        Step("key", "party_menu", key="P"),
        Step("key", "load_from", key="L"),
        Step("key", "load_picker", key="P"),
        Step("key", "disk2_prompt", key=slot),
        Step("insert", "loaded_menu", key="SPACE", drive=0, media="disk2"),
        Step("key", "sheet", key="V", checkpoint="load_sheet"),
        Step("key", "loaded_menu", key="E"),
        Step("key", "journal", key="B"),
        Step("key", "journal_answer", key="X"),
        Step("key", "world", key="RET", checkpoint="loaded",
             expected=Expected(engine=_POD_AERIE)),
    )


def _base_title(title: str, slot: str, opening_scene: bool = False) -> AmigaTitle:
    if title == "pool":
        return route_pool.POOL
    if title == "curse":
        return route_curse.CURSE
    if title == "ssb":
        if slot not in ("A", "D"):
            raise RouteError(f"Silver Blades prepared slot {slot} has no measured load route")
        return route_silver_blades.published_title(slot, opening_scene=opening_scene)
    return route_darkness.DARKNESS


def _legacy_title(base: AmigaTitle, load: Phase) -> AmigaTitle:
    """Keep the title's waits and interstitials without its foundation save steps."""
    steps = []
    for step in load.steps:
        if step.kind == "insert":
            steps.append(((step.drive, step.media, step.key), step.state, "insert"))
        elif step.kind in ("key", "turn", "move", "answer"):
            steps.append((step.key, step.state, step.kind))
    # A Pool, Curse or Pools of Darkness reload restarts the game, and waits for the title as
    # long as the boot's own title wait.
    restarts = base in (route_pool.POOL, route_curse.CURSE, route_darkness.DARKNESS)
    return dataclasses.replace(
        base, route=tuple(steps), measure_route=tuple(steps), control_letter=None,
        after_letter=None, kept_letters=(), plain_keys=(), interstitial_letters=(),
        wait_limits={**base.wait_limits, "title": base.title_limit} if restarts else base.wait_limits,
    )


def _camp_actions(title: str) -> dict[str, tuple[Phase, Phase]]:
    """The show and back visits measured live for Heal and Identify on the three Amiga camps.

    Every visit selects the member again, because the game keeps the last highlighted one.
    """
    if title == "pool":
        return {}
    heal_show = _phase("heal_show", "world", Step("key", "camp", key="E"),
                       Step("select", "camp"),
                       Step("key", "camp_sheet", key="V", checkpoint="heal_sheet"))
    heal_back = _phase("heal_back", "camp_sheet", Step("key", "camp", key="E"),
                       Step("key", "world", key="E"))
    identify_show = _phase(
        "identify_show", "world", Step("key", "camp", key="E"), Step("select", "camp"),
        Step("key", "camp_sheet", key="V"),
        Step("key", "camp_items", key="I", checkpoint="identify_items"))
    identify_back = _phase(
        "identify_back", "camp_items", Step("key", "camp_sheet", key="E"),
        Step("key", "camp", key="E"), Step("key", "world", key="E"))
    return {"heal": (heal_show, heal_back), "identify": (identify_show, identify_back)}


def _actions(title: str) -> tuple[Action, ...]:
    """Press only the actions whose camp route was measured; the rest stay off."""
    measured = _camp_actions(title)

    def action(kind: str, selector: str | None) -> Action:
        show, back = measured.get(kind, (None, None))
        return Action(kind, kind in measured, selector, show, back)

    return (
        action("heal", "hp"),
        action("spells", "memorised"),
        action("identify", "item"),
        action("quickfight", "controlled" if title != "darkness" else None),
        action("levelup", "levelup"),
    )


def _ssb_stationary() -> Phase:
    # The New Verdigris run recorded left/right turns and unchanged squares.
    return _phase(
        "stationary", "world",
        Step("turn", "world", key="NP4", checkpoint="turn_east",
             expected=Expected(engine={"area": 16, "x": 3, "y": 3, "facing": 1},
                               compare_to="loaded", relation="stationary")),
        Step("turn", "world", key="NP6", checkpoint="turn_south",
             expected=Expected(engine={"area": 16, "x": 3, "y": 3, "facing": 2},
                               compare_to="loaded", relation="stationary")),
        Step("turn", "world", key="NP6", checkpoint="turn_west",
             expected=Expected(engine={"area": 16, "x": 3, "y": 3, "facing": 3},
                               compare_to="loaded", relation="stationary")),
        Step("turn", "world", key="NP4", checkpoint="turn_south_again",
             expected=Expected(engine={"area": 16, "x": 3, "y": 3, "facing": 2},
                               compare_to="loaded", relation="stationary")),
    )


def _ssb_walk() -> Phase:
    # WISH-1 comment d7590a18 records each segment from New Verdigris to its exit.
    steps = [
        Step("snapshot", "world", snapshot="ssb_new_verdigris"),
        Step("encounters", "world", encounters=True),
        Step("move", "world", key="NP8"),
        Step("move", "world", key="NP8", checkpoint="ssb_south_2",
             expected=Expected(engine={"area": 16, "x": 3, "y": 5, "facing": 2},
                               compare_to="loaded", relation="moved")),
        Step("turn", "world", key="NP4"),
        Step("move", "world", key="NP8"),
        Step("move", "world", key="NP8", checkpoint="ssb_east_2",
             expected=Expected(engine={"area": 16, "x": 5, "y": 5, "facing": 1},
                               compare_to="ssb_south_2", relation="moved")),
        Step("turn", "world", key="NP6"),
        Step("move", "world", key="NP8"),
        Step("move", "world", key="NP8", checkpoint="ssb_south_4",
             expected=Expected(engine={"area": 16, "x": 5, "y": 7, "facing": 2},
                               compare_to="ssb_east_2", relation="moved")),
        Step("turn", "world", key="NP4"),
    ]
    for n in range(10):
        steps.append(Step(
            "move", "world", key="NP8",
            **({"checkpoint": "ssb_east_10",
                "expected": Expected(engine={"area": 16, "x": 15, "y": 7, "facing": 1},
                                     compare_to="ssb_south_4", relation="moved")}
               if n == 9 else {}),
        ))
    steps.extend((
        Step("turn", "world", key="NP6"),
        Step("move", "world", key="NP8", checkpoint="ssb_exit_square",
             expected=Expected(engine={"area": 16, "x": 15, "y": 8, "facing": 2},
                               compare_to="ssb_east_10", relation="moved")),
        Step("turn", "world", key="NP4", checkpoint="ssb_facing_exit",
             expected=Expected(engine={"area": 16, "x": 15, "y": 8, "facing": 1},
                               compare_to="ssb_exit_square", relation="stationary")),
        Step("encounters", "world", encounters=False),
    ))
    return Phase("walk", "world", tuple(steps))


def _ssb_transition() -> Phase:
    # The exit square's NP8 asks whether to leave town; Y is sent only once that question
    # is recognized, and the party is expected in The Ruins (area 32) at 11,2,E.
    return _phase(
        "transition", "world",
        Step("move", "leave_town", key="NP8"),
        Step("key", "world", key="Y", checkpoint="ssb_ruins_arrival",
             expected=Expected(engine={"area": 32, "x": 11, "y": 2, "facing": 1},
                               compare_to="ssb_facing_exit", relation="area_changed")),
    )


def _ssb_camp() -> Phase:
    # E after a fresh `world` match, and the camp bar is checked as its result: the first
    # key of a reload through camp LOAD.
    return _phase("camp", "world", Step("key", "camp", key="E"))


def _ssb_camp_load() -> Phase:
    # Camp L asks GAME NOT SAVED. LOAD ANYWAY? (guard `load_anyway`); Y goes only on that
    # question, and the screen after it must be the load picker the title route measured.
    return _phase(
        "camp_load", "camp",
        Step("key", "load_anyway", key="L"),
        Step("key", "load_picker", key="Y"),
    )


def _ssb_camp_reload() -> Phase:
    # From the loaded party's menu, the title route's B and opening story back into New
    # Verdigris at the prepared slot's square, compared with the Ruins arrival it left.
    return _phase(
        "camp_reload", "loaded_menu",
        Step("key", "journal", key="B"),
        Step("answer", "treasure_bar"),
        Step("key", "treasure", key="E"),
        Step("key", "world", key="N", checkpoint="ssb_camp_reloaded",
             expected=Expected(engine={"area": 16, "x": 3, "y": 3, "facing": 2},
                               compare_to="ssb_ruins_arrival", relation="area_changed")),
        pages=_SSB_STORY_PAGES,
    )


def _ssb_reload(slot: str) -> Phase:
    """Camp LOAD back to the prepared slot, from the camp bar to the New Verdigris square."""
    steps = (*_ssb_camp().steps, *_ssb_camp_load().steps,
             Step("key", "loaded_menu", key=slot), *_ssb_camp_reload().steps)
    return _phase("reload", "world", *steps, pages=_SSB_STORY_PAGES)


def _ssb_reopen() -> Phase:
    # Encounters stay off in town, as in the walk; the step is one square north of the reload.
    return _phase(
        "reopen_step", "world",
        Step("encounters", "world", encounters=True),
        Step("move", "world", key="NP8", checkpoint="ssb_reopen_step",
             expected=Expected(engine={"area": 16, "x": 3, "y": 4, "facing": 2},
                               compare_to="ssb_camp_reloaded", relation="moved")),
        Step("encounters", "world", encounters=False),
    )


def _turns(prefix: str, compare: str, place: Mapping[str, int],
           facings: tuple[int, int, int, int]) -> Phase:
    """Left, left, right, right on one square, each checked against `compare` as stationary."""
    names = ("turn_1", "turn_2", "turn_3", "turn_4")
    return _phase("stationary", "world", *(
        Step("turn", "world", key=key, checkpoint=f"{prefix}_{name}",
             expected=Expected(engine={**place, "facing": facing}, compare_to=compare,
                               relation="stationary"))
        for key, name, facing in zip(("NP4", "NP4", "NP6", "NP6"), names, facings)))


def _at(area: int, x: int, y: int, facing: int, compare: str,
        relation: Literal["stationary", "moved", "area_changed", "view_changed"]) -> Expected:
    return Expected(engine={"area": area, "x": x, "y": y, "facing": facing},
                    compare_to=compare, relation=relation)


def _pool_phases() -> tuple[Phase, ...]:
    """The outdoor specimen from the New Phlan dock on the travel grid: a step north, the boat
    into New Phlan, turns and a walk there, then a save to C, quit to the AmigaDOS prompt,
    `program` typed there, slot A loaded again, the boat back in, and the walk out by sea."""
    outdoor = _phase(
        "outdoor", "grid",
        Step("snapshot", "grid", snapshot="pool_grid"),
        Step("encounters", "grid", encounters=True),
        Step("move", "grid", key="NP8", checkpoint="pool_grid_north",
             expected=Expected(engine={"outdoors": True, "facing": 0}, window={"x": 7, "y": 28},
                               compare_to="loaded", relation="moved")),
    )
    transition = _phase(
        "transition", "grid",
        Step("move", "boat_question", key="NP2"),
        Step("encounters", "boat_question", encounters=False),
        Step("key", "world", key="T", checkpoint="pool_newphlan",
             expected=_at(0, 15, 1, 3, "pool_grid_north", "area_changed")),
    )
    stationary = _turns("pool", "pool_newphlan", {"area": 0, "x": 15, "y": 1}, (2, 1, 2, 3))
    walk = _phase(
        "walk", "world",
        Step("snapshot", "world", snapshot="pool_newphlan"),
        Step("encounters", "world", encounters=True),
        Step("move", "world", key="NP8"),
        Step("move", "world", key="NP8"),
        Step("move", "world", key="NP8", checkpoint="pool_west_3",
             expected=_at(0, 12, 1, 3, "pool_turn_4", "moved")),
        Step("turn", "world", key="NP6"),
        Step("turn", "world", key="NP6", checkpoint="pool_turned",
             expected=_at(0, 12, 1, 1, "pool_west_3", "stationary")),
        Step("move", "world", key="NP8", checkpoint="pool_walk_end",
             expected=_at(0, 13, 1, 1, "pool_turned", "moved")),
        Step("encounters", "world", encounters=False),
    )
    # The save to C is the only way back to the load picker: Pool's camp has no load.
    reload = _phase(
        "reload", "world",
        Step("key", "camp", key="E"),
        Step("key", "camp_save_picker", key="S"),
        Step("key", "quit_prompt", key="C"),
        Step("key", "cli", key="Y"),
        Step("type", "title", keys=("P", "R", "O", "G", "R", "A", "M", "RET"), screen="cli",
             relaunch=True),
        Step("key", "party_menu", key="RET"),
        Step("key", "save_path", key="L"),
        Step("key", "load_picker", key="RET"),
        Step("key", "grid", key="A", checkpoint="pool_reloaded",
             expected=dataclasses.replace(_POOL_DOCK, compare_to="pool_walk_end",
                                          relation="area_changed")),
        pages=("wheel", "save_path"),
    )
    reopen = _phase(
        "reopen_step", "grid",
        Step("encounters", "grid", encounters=True),
        Step("move", "grid", key="NP8"),
        Step("move", "boat_question", key="NP2"),
        Step("encounters", "boat_question", encounters=False),
        Step("key", "world", key="T"),
        Step("encounters", "world", encounters=True),
        Step("move", "world", key="NP8", checkpoint="pool_reopen_step",
             expected=_at(0, 14, 1, 3, "pool_reloaded", "area_changed")),
        Step("encounters", "world", encounters=False),
    )
    return outdoor, transition, stationary, walk, reload, reopen, _pool_walkout()


def _pool_walkout() -> Phase:
    """From the reopen step's 14,1 facing west to the travel grid by the WEST passage.

    The harbour master at 11,1 speaks only to a party stepping north onto him from 11,2
    (ECL00 `$9C43`); W buys WEST and RETURN at WHO WILL PAY? picks the highlighted member, who
    pays 1 platinum. The pier end at 15,1 prints YOU BOARD A BOAT. on a continue page, and the
    boat lands the party on the grid's dock square, where the game asks TAKE BOAT or STAY
    before it prints the square; STAY leaves it on the grid. Sailing out loads no map: the
    resident block stays New Phlan's, so the landing is checked as a change of view."""
    return _phase(
        "walkout", "world",
        Step("snapshot", "world", snapshot="pool_harbour"),
        Step("encounters", "world", encounters=True),
        Step("move", "world", key="NP8"),
        Step("move", "world", key="NP8"),
        Step("move", "world", key="NP8", checkpoint="pool_harbour_door",
             expected=_at(0, 11, 1, 3, "pool_reopen_step", "moved")),
        Step("turn", "world", key="NP4"),
        Step("move", "world", key="NP8", checkpoint="pool_harbour_approach",
             expected=_at(0, 11, 2, 2, "pool_harbour_door", "moved")),
        Step("turn", "world", key="NP2"),
        Step("move", "harbour_master", key="NP8", checkpoint="pool_harbour_master",
             expected=_at(0, 11, 1, 0, "pool_harbour_approach", "moved")),
        Step("encounters", "harbour_master", encounters=False),
        Step("key", "harbour_payer", key="W"),
        Step("key", "world", key="RET"),
        Step("encounters", "world", encounters=True),
        Step("turn", "world", key="NP6"),
        Step("move", "world", key="NP8"),
        Step("move", "world", key="NP8"),
        Step("move", "world", key="NP8", checkpoint="pool_pier",
             expected=_at(0, 14, 1, 1, "pool_harbour_master", "moved")),
        Step("move", "continue", key="NP8"),
        Step("encounters", "continue", encounters=False),
        Step("key", "boat_question", key="RET"),
        Step("key", "grid", key="S", checkpoint="pool_walkout_grid",
             expected=dataclasses.replace(_POOL_DOCK, compare_to="pool_pier",
                                          relation="view_changed")),
    )


def _curse_reload(expected: Expected) -> Phase:
    """Save to F, quit, reset and load slot B again; Curse's camp has no load, and its exit
    leaves AmigaDOS asking for a reboot."""
    return _phase(
        "reload", "world",
        Step("key", "camp", key="E"),
        Step("key", "camp_save_picker", key="S"),
        Step("key", "exit_game", key="F"),
        Step("key", "reboot", key="Y"),
        Step("reset", "title", relaunch=True),
        Step("key", "load_picker", key="L"),
        Step("key", "loaded_menu", key="B"),
        Step("key", "world", key="B", checkpoint="curse_reloaded", expected=expected),
        pages=("front_end", "intro"),
    )


def _spells_phases(title: str, load: Phase, slot: str, party: SpellsParty
                   ) -> tuple[Phase, ...]:
    """The load and the camp reload a spells party needs; every mapping phase stays missing."""
    if title == "curse":
        reload = _curse_reload(Expected(engine=_square(party)))
    else:
        # The reload's comparison is with the transition's arrival, which this party never makes.
        reload = _ssb_reload(slot)
        reload = dataclasses.replace(reload, steps=tuple(
            dataclasses.replace(step, expected=dataclasses.replace(
                step.expected, compare_to=None, relation=None))
            if step.expected is not None and step.expected.compare_to else step
            for step in reload.steps))
    return (load, *(_missing(name, "world", _PERSIST_ONLY)
                    for name in ("stationary", "walk", "transition")),
            reload, _missing("reopen_step", "world", _PERSIST_ONLY))


def _square(party: SpellsParty) -> dict[str, int]:
    """The party's square and facing; the Tilverton area byte is not yet read in a running game."""
    return {key: party.place[key] for key in ("x", "y", "facing")}


def _curse_phases() -> tuple[Phase, ...]:
    """The Yulash save at 2,6 facing east: turns, a walk west and back through the
    checkpoint square, out to the world map, ENTER CITY and SNEAK IN, then a save to F, the
    game's exit, a soft reset and slot B loaded again."""
    yulash = {"area": 16, "y": 6}
    stationary = _turns("curse", "loaded", {**yulash, "x": 2}, (0, 3, 0, 1))
    walk = _phase(
        "walk", "world",
        Step("snapshot", "world", snapshot="curse_yulash"),
        Step("encounters", "world", encounters=True),
        Step("turn", "world", key="NP4"),
        Step("turn", "world", key="NP4"),
        Step("move", "world", key="NP8"),
        Step("move", "world", key="NP8", checkpoint="curse_west_2",
             expected=_at(16, 0, 6, 3, "curse_turn_4", "moved")),
        Step("turn", "world", key="NP6"),
        Step("turn", "world", key="NP6", checkpoint="curse_turned_east",
             expected=_at(16, 0, 6, 1, "curse_west_2", "stationary")),
        # Facing east onto 1,6 asks ATTEMPT TO SNEAK PAST / MOVE NORMALLY; MOVE NORMALLY
        # clears it with no further page.
        Step("move", "yulash_checkpoint", key="NP8"),
        Step("key", "world", key="M"),
        Step("move", "world", key="NP8", checkpoint="curse_walk_end",
             expected=_at(16, 2, 6, 1, "curse_turned_east", "moved")),
        Step("encounters", "world", encounters=False),
    )
    transition = _phase(
        "transition", "world",
        Step("encounters", "world", encounters=True),
        Step("turn", "world", key="NP4"),
        Step("turn", "world", key="NP4"),
        Step("move", "world", key="NP8"),
        Step("move", "world", key="NP8", checkpoint="curse_exit_square",
             expected=_at(16, 0, 6, 3, "curse_walk_end", "moved")),
        Step("encounters", "world", encounters=False),
        Step("move", "dalelands", key="NP8", checkpoint="curse_world",
             expected=Expected(engine={"world_map": True, "world_node": 10},
                               compare_to="curse_exit_square", relation="view_changed")),
    )
    outdoor = _phase(
        "outdoor", "dalelands",
        Step("key", "yulash_arrival", key="E"),
        Step("key", "world", key="S", checkpoint="curse_yulash_again",
             expected=_at(16, 0, 6, 1, "curse_world", "view_changed")),
    )
    reload = _curse_reload(_at(16, 2, 6, 1, "curse_yulash_again", "moved"))
    reopen = _phase(
        "reopen_step", "world",
        Step("encounters", "world", encounters=True),
        Step("turn", "world", key="NP4"),
        Step("turn", "world", key="NP4"),
        Step("move", "world", key="NP8", checkpoint="curse_reopen_step",
             expected=_at(16, 1, 6, 3, "curse_reloaded", "moved")),
        Step("encounters", "world", encounters=False),
    )
    return stationary, walk, transition, outdoor, reload, reopen


#: The overland party's flag, x and y: the long at data hunk +0x57AC points at them, +0x24.
_POD_OVERLAND = (Read("overland", "base", 0x57AC, 3, hop=0x24),)
#: The game's own area id (the trip rows' area byte), which names a map two areas share.
_POD_AREA_ID = (Read("area_id", "base", 0x7A0A, 1),)


def _darkness_phases() -> tuple[Phase, ...]:
    """Slot B in Aerie: turns and a walk there, camp LOAD of slot D on the overland, four
    overland steps to Mulmaster's question, YES and MOVE ON, then camp LOAD of slot B. The overland checkpoints
    carry no verdict and keep the party bytes for the record. After the reopened step, camp
    LOAD of slot D again and six overland steps to the village of area 20, a map no area names."""
    aerie = {"area": 33, "y": 2}
    stationary = _turns("pod", "loaded", {**aerie, "x": 1}, (0, 3, 0, 1))
    walk = _phase(
        "walk", "world",
        Step("snapshot", "world", snapshot="pod_aerie"),
        Step("encounters", "world", encounters=True),
        Step("move", "world", key="NP8"),
        Step("move", "world", key="NP8", checkpoint="pod_east_2",
             expected=_at(33, 3, 2, 1, "pod_turn_4", "moved")),
        Step("turn", "world", key="NP4"),
        Step("turn", "world", key="NP4", checkpoint="pod_turned_west",
             expected=_at(33, 3, 2, 3, "pod_east_2", "stationary")),
        Step("move", "world", key="NP8"),
        Step("move", "world", key="NP8", checkpoint="pod_walk_end",
             expected=_at(33, 1, 2, 3, "pod_turned_west", "moved")),
        Step("encounters", "world", encounters=False),
    )
    camp_load = (
        Step("key", "camp", key="E"),
        Step("key", "load_anyway", key="L"),
        Step("key", "load_from", key="Y"),
        Step("key", "load_picker", key="P"),
    )
    transition = _phase(
        "transition", "world", *camp_load,
        Step("key", "loaded_menu", key="D"),
        Step("key", "world", key="B", checkpoint="pod_overland", reads=_POD_OVERLAND),
        Step("snapshot", "world", snapshot="pod_overland"),
        Step("encounters", "world", encounters=True),
        *(Step("move", "world", key="NP8", checkpoint=f"pod_overland_{n}", reads=_POD_OVERLAND)
          for n in (1, 2, 3)),
        Step("move", "yes_no", key="NP4", checkpoint="pod_overland_4", reads=_POD_OVERLAND),
        Step("encounters", "yes_no", encounters=False),
        Step("key", "mulmaster_guards", key="Y"),
        Step("key", "world", key="M", checkpoint="pod_mulmaster",
             expected=_at(19, 0, 3, 1, "pod_walk_end", "area_changed"), reads=_POD_AREA_ID),
    )
    reload = _phase(
        "reload", "world", *camp_load,
        Step("key", "loaded_menu", key="B"),
        Step("key", "world", key="B", checkpoint="pod_reloaded",
             expected=_at(33, 1, 2, 1, "pod_mulmaster", "area_changed"), reads=_POD_AREA_ID),
    )
    reopen = _phase(
        "reopen_step", "world",
        Step("encounters", "world", encounters=True),
        Step("move", "world", key="NP8", checkpoint="pod_reopen_step",
             expected=_at(33, 2, 2, 1, "pod_reloaded", "moved")),
        Step("encounters", "world", encounters=False),
    )
    # Slot D at overland 34,14: north twice and west four times to the village square 30,12,
    # whose question's YES loads area 20 on GEO14 at 5,7 facing east.
    village = _phase(
        "village", "world", *camp_load,
        Step("key", "loaded_menu", key="D"),
        Step("key", "world", key="B"),
        Step("snapshot", "world", snapshot="pod_village_overland"),
        Step("encounters", "world", encounters=True),
        *(Step("move", "world", key=key) for key in ("NP8", "NP8", "NP4", "NP4", "NP4")),
        Step("move", "yes_no", key="NP4"),
        Step("encounters", "yes_no", encounters=False),
        Step("key", "continue", key="Y"),
        Step("key", "world", key="RET", checkpoint="pod_village",
             expected=_at(20, 5, 7, 1, "pod_reopen_step", "area_changed"), reads=_POD_AREA_ID),
    )
    return stationary, walk, transition, reload, reopen, village


def _phases(title: str, load: Phase, slot: str, curse_yulash: bool = False
            ) -> tuple[Phase, ...]:
    if title == "pool":
        return (load, *_pool_phases())
    if title == "curse" and curse_yulash:
        return (load, *_curse_phases())
    if title == "darkness":
        return (load, *_darkness_phases())
    if title == "ssb":
        return (
            load, _ssb_stationary(), _ssb_walk(), _ssb_transition(),
            _ssb_reload(slot), _ssb_reopen(),
        )
    # The Tilverton world-map slot reaches no indoor area by ordinary keys.
    return (
        load, _phase("outdoor", "world", Step("observe", "world", checkpoint="outdoor")),
        _missing("transition", "world",
                 "JOURNEY ON meets a scripted battle, and SEARCH AREA has no measured prompt guard."),
        _missing("stationary", "world",
                 "Sewer stationary turns after the journey and entry are not measured."),
        _missing("walk", "world", "The guarded three-step sewer walk is not recorded."),
        _missing("reload", "world", "The game's no-save return to the load picker is not measured."),
        _missing("reopen_step", "world", "The post-restart sewer step is not measured."),
    )


def _source_provenance(manifest: Mapping[str, object]) -> dict[str, object]:
    source = manifest.get("substitute")
    if not isinstance(source, Mapping):
        return {}
    return {key: source[key] for key in ("path", "sha256", "letter") if key in source}


def _curse_yulash(manifest: Mapping[str, object], source: Mapping[str, object],
                  slot: str) -> bool:
    """Whether the prepared Curse party is the registered Yulash save at 2,6 facing east."""
    return (slot == "B" and (source.get("letter"), source.get("sha256")) == ("C", _CURSE_YULASH_SHA256)
            and manifest.get("state_a") == _CURSE_YULASH)


def _spells_party(title: str, manifest: Mapping[str, object], source: Mapping[str, object],
                  slot: str) -> SpellsParty | None:
    """The pinned spells party, when the prepared slot holds it on its own square."""
    party = SPELLS_PARTIES.get(title)
    if party is None or slot != _SPELLS_SLOT[title]:
        return None
    if (source.get("letter"), source.get("sha256")) != (party.letter, party.sha256):
        return None
    return party if manifest.get("state_a") == party.place else None


def _specimen_gaps(title: str, manifest: Mapping[str, object],
                   source: Mapping[str, object], media: tuple[Media, ...],
                   slot: str) -> tuple[str, ...]:
    if _spells_party(title, manifest, source, slot) is not None:
        return ()
    if title == "pool":
        if slot != "A" or (source.get("letter"), source.get("sha256")) != (
                "B", _POOL_OUTDOOR_SHA256):
            return ("Pool needs the registered outdoor source slot B imported into prepared slot A.",)
    elif title == "curse":
        world_map = slot == "B" and (source.get("letter"), source.get("sha256")) == (
            "F", _CURSE_WORLD_SHA256)
        if not world_map and not _curse_yulash(manifest, source, slot):
            return ("Curse needs the registered Yulash slot C or Tilverton world-map slot F "
                    "imported into prepared slot B.",)
    elif title == "ssb":
        if slot != "D" or manifest.get("state_a") != {
                "area": 16, "x": 3, "y": 3, "facing": 2}:
            return ("Silver Blades needs prepared slot D at New Verdigris 3,3 S.",)
    elif slot != "B" or manifest.get("state_a") != {
            "area": 2, "x": 1, "y": 2, "facing": 1} or next(
                m.sha256 for m in media if m.key == "disk3") != route_darkness.DARKNESS_DISK3_SHA256:
        return ("Pools of Darkness needs registered disk 3 slot B at GEO21 1,2 E.",)
    return ()


def route_for(title: str, manifest: Mapping[str, object]) -> MappingRoute:
    """Describe the measured part of one prepared title, and block unmeasured phases."""
    if title not in _GAME_KEYS:
        raise RouteError(f"Unknown Amiga mapping title {title!r}")
    if not isinstance(manifest, Mapping) or manifest.get("title") != title:
        raise RouteError(f"Prepared manifest is not for {title}")
    slot = _slot_from(manifest)
    opening_scene = manifest.get("opening_scene") is True
    base = _base_title(title, slot, opening_scene)
    media = _media_for(title, manifest, base)
    source = _source_provenance(manifest)
    curse_yulash = title == "curse" and _curse_yulash(manifest, source, slot)
    spells = _spells_party(title, manifest, source, slot)
    load = _load(title, slot, opening_scene, curse_yulash,
                 _square(spells) if spells is not None and title == "curse" else None)
    phases = (_spells_phases(title, load, slot, spells) if spells is not None
              else _phases(title, load, slot, curse_yulash))
    specimen_gaps = _specimen_gaps(title, manifest, source, media, slot)
    provenance: dict[str, object] = {
        "prepared_slot": slot,
        "source_slot": source.get("letter"),
        "source_sha256": source.get("sha256"),
        "guard_source": _GUARD_NAMES[title],
        "route_evidence": {
            "pool": "WISH-1 comments 01e40161 and 23bf5b91 (capture boot CP); route_pool.py load prefix",
            "curse": ("WISH-1 comments 591c10fb (capture boot CC), 7fcffdf6 and 766cbc82; "
                      "route_curse.py load prefix" if curse_yulash
                      else "WISH-1 comment 01e40161; route_curse.py load prefix"),
            "ssb": "WISH-1 comment d7590a18; route_silver_blades.py load prefix",
            "darkness": ("WISH-1 comments 6ed8e2c1 (capture boot CD) and 7fcffdf6; "
                         "route_darkness.py load prefix"),
        }[title],
        "confidence": {
            "pool": ("CONFIRMED: Every key, screen and fix up to the reload was matched in one WinUAE boot. "
                     "PROBABLE: The plain-cut AmigaDOS guard, the reopen step composed from measured keys, "
                     "and New Phlan read as area 0."),
            "curse": ("CONFIRMED: Every key, screen and fix through the camp exit was matched in one WinUAE boot. "
                      "PROBABLE: The soft reset through the pipe and the load after it, and Yulash read as area 16."
                      if curse_yulash else
                      "CONFIRMED: The prepared source letter and Dalelands route are recorded in WISH-1."),
            "ssb": "CONFIRMED: WISH-1 comment d7590a18 measured the walk from 3,3 to 15,8 in one boot. PROBABLE: The four-turn control composes its measured left/right keys and needs a live readback.",
            "darkness": ("CONFIRMED: Every key, screen, fix and resident map of the route was matched in one "
                         "WinUAE boot."),
        }[title],
    }
    if spells is not None:
        provenance["spells_party"] = f"WISH-SPEC-{spells.specimen}/{spells.file} slot {spells.letter}"
        provenance["confidence"] = (
            "CONFIRMED: The party, slot and memorised bytes were read off the registered disk. "
            "SPECULATIVE: The load and camp reload are the mapping route's keys, not yet matched "
            "with this party on its square.")
    unresolved = (
        *specimen_gaps,
        *(phase.reason for phase in phases if not phase.ready and phase.reason),
        *(("Game-sheet routes and readbacks for the Wish action presses are not measured.",)
          if any(action.enabled and (action.show is None or action.back is None)
                 for action in _actions(title)) else ()),
    )
    guard_path = pathlib.Path(__file__).resolve().with_name(_GUARD_NAMES[title])
    return MappingRoute(
        title, _GAME_KEYS[title], _legacy_title(base, load), guard_path, media,
        tuple(key for key in base.mounted if key is not None), slot, phases,
        _actions(title), provenance, unresolved,
    )


#: The phases `--leg persist` runs before its save, in the route's own order. Pool loads onto
#: the travel grid, so it takes the boat into New Phlan first; the other titles save where
#: the load leaves the party.
LEG_PREFIX = {
    "pool": ("load", "outdoor", "transition"),
    "curse": ("load",),
    "ssb": ("load",),
    "darkness": ("load",),
}
#: Titles whose reload from camp asks screens that differ by save state, so the controller
#: answers it screen by screen; Pool and Curse restart the game and reuse their reload phase.
BRANCHED_RELOAD = frozenset({"ssb", "darkness"})
#: The letters `persist_letter` may use, in order. A letter outside the game's own save picker
#: is never offered: Silver Blades' camp save letter D is its loaded slot.
_PERSIST_LETTERS = {"pool": "DEFGHIJ", "curse": "GHIJ", "ssb": "EFGHIJ", "darkness": "GH"}
#: The letter a title's reload phase saves to before it quits; the persist save must not use it.
_RELOAD_SAVE_LETTER = {"pool": "C", "curse": "F"}


def persist_letter(title: str, manifest: Mapping[str, object], media: tuple[Media, ...]
                   ) -> str | None:
    """The first persist-save letter the prepared save disk does not hold, or None."""
    if title not in _GAME_KEYS:
        raise RouteError(f"Unknown Amiga mapping title {title!r}")
    slot = _slot_from(manifest)
    base = _base_title(title, slot, manifest.get("opening_scene") is True)
    held = next((item for item in media if item.key == base.save_disk), None)
    if held is None:
        raise RouteError(f"Prepared manifest has no {base.save_disk} save disk")
    present = set(base.slot_letters(amiga_adf.AmigaDisk.open(held.path)))
    taken = present | {slot} | ({_RELOAD_SAVE_LETTER[title]} if title in _RELOAD_SAVE_LETTER else set())
    return next((letter for letter in _PERSIST_LETTERS[title] if letter not in taken), None)


def _persist_reload_tail(title: str, steps: tuple[Step, ...], letter: str) -> tuple[Step, ...]:
    """A reload phase's steps after its camp key, saving to and loading `letter`, ending at `world`."""
    save_state, save_key = (("quit_prompt", "C") if title == "pool" else ("exit_game", "F"))
    swapped = [dataclasses.replace(step, key=letter)
               if step.state == save_state and step.key == save_key else step
               for step in steps]
    if swapped == list(steps):
        raise RouteError(f"{title} reload has no save to {save_key}")
    # The load letter is the last key of Pool's reload and the one before the last of Curse's.
    at = len(swapped) - (1 if title == "pool" else 2)
    load = swapped[at]
    if load.kind != "key" or load.key != ("A" if title == "pool" else "B"):
        raise RouteError(f"{title} reload does not end by loading its slot")
    swapped[at] = dataclasses.replace(load, key=letter)
    last = swapped[-1]
    swapped[-1] = dataclasses.replace(
        last, state="world", checkpoint="persist_reloaded",
        expected=Expected(compare_to="persist_saved", relation="equal"))
    return tuple(swapped)


def persist_phases(route: MappingRoute, letter: str) -> tuple[Phase, Phase]:
    """The persist leg's `(saved, rest)` phases, from measured keys only.

    `saved` observes `world` as checkpoint `persist_saved` and presses camp E. `rest` starts
    at the camp bar: Pool and Curse save to `letter`, quit and load it again, ending at
    checkpoint `persist_reloaded` compared equal to `persist_saved`; Silver Blades and Pools
    of Darkness only save to `letter` and answer N, and the controller reloads them.
    """
    title = route.title
    saved = _phase("persist_saved", "world",
                   Step("observe", "world", checkpoint="persist_saved"),
                   Step("key", "camp", key="E"))
    if title in BRANCHED_RELOAD:
        return saved, _phase("persist_save", "camp",
                             Step("key", "camp_save_picker", key="S"),
                             Step("key", "exit_game", key=letter),
                             Step("key", "camp", key="N"))
    reload = next((phase for phase in route.phases if phase.name == "reload"), None)
    if reload is None or not reload.ready:
        raise RouteError(f"{title} has no ready reload phase to derive the persist save from")
    if reload.steps[0].state != "camp" or reload.steps[0].key != "E":
        raise RouteError(f"{title} reload does not open with camp E")
    return saved, Phase("persist_reload", "camp",
                        _persist_reload_tail(title, reload.steps[1:], letter),
                        pages=reload.pages)
