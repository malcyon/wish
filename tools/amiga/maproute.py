"""Measured game sequences and inputs for a Wish window beside WinUAE."""

from __future__ import annotations

import dataclasses
import pathlib
import re
from collections.abc import Mapping
from typing import Literal

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
    relation: Literal["equal", "stationary", "moved", "area_changed"] | None = None


@dataclasses.dataclass(frozen=True)
class Step:
    kind: Literal[
        "key", "turn", "move", "insert", "answer", "snapshot", "restore",
        "encounters", "select", "observe",
    ]
    state: str
    key: str | None = None
    drive: int | None = None
    media: str | None = None
    snapshot: str | None = None
    encounters: bool | None = None
    checkpoint: str | None = None
    expected: Expected | None = None


@dataclasses.dataclass(frozen=True)
class Phase:
    name: str
    initial_state: str
    steps: tuple[Step, ...]
    ready: bool = True
    reason: str | None = None


@dataclasses.dataclass(frozen=True)
class Action:
    kind: Literal["heal", "spells", "identify", "quickfight", "levelup"]
    enabled: bool
    selector: Literal["hp", "memorised", "item", "controlled", "pod_levelup"] | None
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


def _phase(name: str, initial: str, *steps: Step) -> Phase:
    return Phase(name, initial, steps)


def _missing(name: str, initial: str, reason: str) -> Phase:
    return Phase(name, initial, (), ready=False, reason=reason)


def _load(title: str, slot: str, opening_scene: bool = False) -> Phase:
    if title == "pool":
        return _phase(
            "load", "title",
            Step("key", "party_menu", key="RET"),
            Step("key", "save_path", key="L"),
            Step("key", "load_picker", key="RET"),
            Step("key", "world", key=slot, checkpoint="loaded",
                 expected=Expected(engine={"area": 26, "x": 20, "y": 29, "facing": 1},
                                   window={"x": 7, "y": 29})),
            Step("key", "sheet", key="V", checkpoint="load_sheet"),
            Step("key", "world", key="E"),
        )
    if title == "curse":
        return _phase(
            "load", "title",
            Step("key", "load_picker", key="L"),
            Step("key", "loaded_menu", key=slot),
            Step("key", "sheet", key="V", checkpoint="load_sheet"),
            Step("key", "loaded_menu", key="E"),
            Step("key", "world", key="B", checkpoint="loaded"),
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
             expected=Expected(engine={"area": 21, "x": 1, "y": 2, "facing": 1})),
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
    return dataclasses.replace(
        base, route=tuple(steps), measure_route=tuple(steps), control_letter=None,
        after_letter=None, kept_letters=(), plain_keys=(), interstitial_letters=(),
    )


def _actions(title: str) -> tuple[Action, ...]:
    """Offer selectors to the controller, but no press before its game-screen route is measured."""
    return (
        Action("heal", False, "hp", None, None),
        Action("spells", False, "memorised", None, None),
        Action("identify", False, "item", None, None),
        Action("quickfight", False, "controlled" if title != "darkness" else None, None, None),
        Action("levelup", False, "pod_levelup" if title == "darkness" else None, None, None),
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
    # WISH-1 comments f911dc9f and 582a3174: the exit square's NP8 asks the leave-town
    # question, and YES reached The Ruins (area 32) at 11,2,E in the recorded run.
    return _phase(
        "transition", "world",
        Step("move", "leave_town", key="NP8"),
        Step("key", "world", key="Y", checkpoint="ssb_ruins_arrival",
             expected=Expected(engine={"area": 32, "x": 11, "y": 2, "facing": 1},
                               compare_to="ssb_facing_exit", relation="area_changed")),
    )


def _phases(title: str, load: Phase) -> tuple[Phase, ...]:
    if title == "pool":
        needs = {
            "stationary": "Indoor stationary turns after TAKE BOAT are not measured.",
            "walk": "No guarded three-step route from the outdoor specimen is recorded.",
            "transition": "TAKE BOAT into New Phlan lacks a measured prompt guard and key sequence.",
            "reload": "The game's no-save return to the load picker is not measured.",
            "reopen_step": "The post-restart step from the outdoor specimen is not measured.",
        }
    elif title == "curse":
        needs = {
            "stationary": "Sewer stationary turns after the journey and entry are not measured.",
            "walk": "The guarded three-step sewer walk is not recorded.",
            "transition": "JOURNEY ON meets a scripted battle, and SEARCH AREA has no measured prompt guard.",
            "reload": "The game's no-save return to the load picker is not measured.",
            "reopen_step": "The post-restart sewer step is not measured.",
        }
    elif title == "ssb":
        needs = {
            "reload": "The game's no-save return to the load picker is not measured.",
            "reopen_step": "The post-restart Ruins step is not measured.",
        }
    else:
        needs = {
            "stationary": "Two turns each way from GEO21 are not recorded.",
            "walk": "Three guarded GEO21 movement checkpoints are not recorded.",
            "transition": "No guarded on-foot entrance from the overland is established.",
            "reload": "The recorded slot-D load is not an original-slot B reload route.",
            "reopen_step": "The post-restart GEO21 step is not measured.",
        }
    if title == "ssb":
        return (
            load, _ssb_stationary(), _ssb_walk(), _ssb_transition(),
            *(_missing(name, "world", needs[name]) for name in _REQUIRED[4:]),
        )
    if title in ("pool", "curse"):
        return (
            load, _phase("outdoor", "world", Step("observe", "world", checkpoint="outdoor")),
            _missing("transition", "world", needs["transition"]),
            _missing("stationary", "world", needs["stationary"]),
            _missing("walk", "world", needs["walk"]),
            _missing("reload", "world", needs["reload"]),
            _missing("reopen_step", "world", needs["reopen_step"]),
        )
    return (load, *(_missing(name, "world", needs[name]) for name in _REQUIRED[1:]))


def _source_provenance(manifest: Mapping[str, object]) -> dict[str, object]:
    source = manifest.get("substitute")
    if not isinstance(source, Mapping):
        return {}
    return {key: source[key] for key in ("path", "sha256", "letter") if key in source}


def _specimen_gaps(title: str, manifest: Mapping[str, object],
                   source: Mapping[str, object], media: tuple[Media, ...],
                   slot: str) -> tuple[str, ...]:
    if title == "pool":
        if slot != "A" or (source.get("letter"), source.get("sha256")) != (
                "B", _POOL_OUTDOOR_SHA256):
            return ("Pool needs the registered outdoor source slot B imported into prepared slot A.",)
    elif title == "curse":
        if slot != "B" or (source.get("letter"), source.get("sha256")) != (
                "F", _CURSE_WORLD_SHA256):
            return ("Curse needs the registered Tilverton world-map slot F imported into prepared slot B.",)
    elif title == "ssb":
        if slot != "D" or manifest.get("state_a") != {
                "area": 16, "x": 3, "y": 3, "facing": 2}:
            return ("Silver Blades needs prepared slot D at New Verdigris 3,3 S.",)
    elif slot != "B" or manifest.get("state_a") != {
            "area": 21, "x": 1, "y": 2, "facing": 1} or next(
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
    load = _load(title, slot, opening_scene)
    phases = _phases(title, load)
    source = _source_provenance(manifest)
    specimen_gaps = _specimen_gaps(title, manifest, source, media, slot)
    provenance: dict[str, object] = {
        "prepared_slot": slot,
        "source_slot": source.get("letter"),
        "source_sha256": source.get("sha256"),
        "guard_source": _GUARD_NAMES[title],
        "route_evidence": {
            "pool": "WISH-1 comment 01e40161; route_pool.py load prefix",
            "curse": "WISH-1 comment 01e40161; route_curse.py load prefix",
            "ssb": "WISH-1 comment d7590a18; route_silver_blades.py load prefix",
            "darkness": "WISH-1 comment 01e40161; route_darkness.py load prefix",
        }[title],
        "confidence": {
            "pool": "CONFIRMED: The prepared source letter and outdoor coordinates are recorded in WISH-1 and WISH-359.",
            "curse": "CONFIRMED: The prepared source letter and Dalelands route are recorded in WISH-1.",
            "ssb": "CONFIRMED: WISH-1 comment d7590a18 measured the walk from 3,3 to 15,8 in one boot. PROBABLE: The four-turn control composes its measured left/right keys and needs a live readback.",
            "darkness": "CONFIRMED: The disk-2 prompt and GEO21 loading route are recorded in route_darkness.py.",
        }[title],
    }
    unresolved = (
        *specimen_gaps,
        *(phase.reason for phase in phases if not phase.ready and phase.reason),
        "Game-sheet routes and readbacks for the Wish action presses are not measured.",
    )
    guard_path = pathlib.Path(__file__).resolve().with_name(_GUARD_NAMES[title])
    return MappingRoute(
        title, _GAME_KEYS[title], _legacy_title(base, load), guard_path, media,
        tuple(key for key in base.mounted if key is not None), slot, phases,
        _actions(title), provenance, unresolved,
    )
