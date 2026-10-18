#!/usr/bin/env python3
"""Collect bounded Wish-window and WinUAE mapping evidence for one Amiga title.

This driver records observations. A person must review paired game and Wish images
before the corresponding mapping row can be accepted.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.amiga import guardmaps, noencounters, screens, winwish  # noqa: E402
from tools.amiga.winuaesession import (  # noqa: E402
    KEY_HOLD_FRAMES,
    RouteError,
    ShotTimedOut,
    WinGuest,
)

BUILD_SHA = re.compile(r"[0-9a-f]{40}\Z")
REQUIRED = ("load", "stationary", "walk", "transition", "reload", "reopen_step")
MAPPING_ROWS = ("title", "load", "stationary", "walk", "transition", "reload",
                "reopen", "walkout", "disconnect")
#: The reconnect leg loads the party, stops the game, and starts and loads it again.
RECONNECT_ROWS = ("title", "load", "disconnect", "reconnect")
STATUSES = ("passed", "failed", "unproven", "awaiting image review")
LEGS = ("mapping", "persist", "reconnect", "fight")
ACTION_KINDS = ("heal", "spells", "identify", "quickfight", "levelup")
#: The fight leg's rows before its own: the title and the load.
FIGHT_ROWS = ("title", "load")
#: Keys the fight leg may press after the load: its walk, its way into the fight and every
#: answer of the fight loop, each counted as an action key.
FIGHT_COMMANDS = 200
#: Steps the guarded walk to an encounter takes, and the backward restores it may spend on a
#: screen it does not answer.
FIGHT_WALK_STEPS = 40
FIGHT_RESTORES = 2
FIGHT_WALK_SNAPSHOT = "fight_walk"
#: The snapshots taken at CONTINUE BATTLE (the clear-quickfight edge) and at the Pools of Darkness
#: command bar where Quickfight off is pressed.
FIGHT_EDGE_SNAPSHOT = "fight_edge"
POD_QF_SNAPSHOT = "pod_qf"
#: The fight leg's extra rows, by the flag that adds them.
WATCH_ROWS = {"watch": ("watch_control_b", "watch_a"), "watch_dip": ("watch_dip",),
              "watch_map": ("watch_map",), "press_quickfight_off": ("qf_press_a", "qf_press_b")}
#: `--watch-map`: seconds from the last Q to the first glance at the game, between the later
#: glances, and the most the hold waits for CONTINUE BATTLE (it keeps the fight under
#: `cursefight.FIGHT_LIMIT`).
MAP_HOLD_FIRST = 300.0
MAP_HOLD_NEXT = 60.0
MAP_HOLD_LIMIT = 600.0
#: Seconds after a walk key before its screen is looked at.
FIGHT_STEP_SETTLE = 6.0
#: The Automapper's action buttons, by label, and the action name `PartyRow.combat_legal` uses.
GREYED_ACTIONS = {"Heal party": "heal", "Save spells": "store-spells",
                  "Restore spells": "restore-spells", "Identify": "identify",
                  "Quickfight off": "clear-quickfight"}
#: How `maproute.route_for` opens the sentence naming a title's missing route specimen.
SPECIMEN_GAPS = {"pool": "Pool needs ", "curse": "Curse needs ", "ssb": "Silver Blades needs ",
                 "darkness": "Pools of Darkness needs "}
#: The fight specimen each title other than Pool runs, pinned by its source: Curse's Tilverton
#: slot B (`cursefight.py stage` of the registered `WISH-SPEC-curse-c64toamiga-slotb-walked-saved-c`),
#: Silver Blades' slot D at 3,7 (`ssbfight.py stage` of `WISH-SPEC-amiga-ssb-foundation-walked`,
#: gate $4C2D set to 1) and Pools of Darkness' WISH-2 a3 slot D imported into B. Pool runs the
#: route's own outdoor specimen.
FIGHT_PINS: dict[str, dict[str, Any]] = {
    "curse": {"source_sha256": "752ed821e94cbedb96b7f8e8d4df09cd61e0c1a63c40ff2aab07d2c5203bcd71",
              "load": "B", "place": {"area": 1, "x": 4, "y": 4, "facing": 0}},
    "ssb": {"source_sha256": "e4f231fe86f30bfc31e32fa7b1262157a67fdcb85663ed4935fc7d70e62ccb20",
            "load": "D", "place": {"area": 16, "x": 3, "y": 7, "facing": 2}},
    "darkness": {"loaded": {"world_map": True},
                 "substitute_sha256": "ab19a53ebc43f87c5bbab53d7f1b41254e0207d51fa333be194b0cb12ab0fa67",
                 "substitute_letter": "D", "load": "B",
                 "place": {"area": 0, "x": 4, "y": 7, "facing": 1}},
}
#: The longest `--wait-lanes`, in seconds: the lane pool's own claim wait.
MAX_WAIT_LANES = 1800
#: Item-node bytes a title's save does not write, keyed by `PartyRow.title`; no load restores them.
UNSAVED_ITEM_PREFIX = {"Pools of Darkness": 0x2E}
#: The most keys a camp-LOAD reload by screen can press after a persist save: Silver Blades'
#: L, Y, slot, B, E and N; Pools of Darkness' L, Y, P, slot and B.
PERSIST_RELOAD_KEYS = 6
#: The most `continue` pages (PRESS RETURN TO CONTINUE) one camp LOAD answers on its way back to
#: the world bar. A party that has not set out shows the opening story: nine pages before the
#: treasure screen and three after its offer, twelve in all (`PUBLISHED_CONTINUE_LIMIT`);
#: the run that stopped at three had answered four pages, none of them a stale frame. Two more
#: are the margin.
PERSIST_CONTINUE_PAGES = 14
#: Seconds after a RETURN during which a frame identical to the page's own is the game not yet redrawn.
CONTINUE_SETTLE = 5.0
#: Screens a persist reload answers beyond its phases' own, which need a guard like any other.
PERSIST_BRANCH_STATES = {
    "ssb": frozenset({"load_anyway", "load_picker", "loaded_menu", "journal", "world",
                      "treasure_bar", "treasure", "continue"}),
    "darkness": frozenset({"load_anyway", "load_from", "load_picker", "loaded_menu", "world",
                           "continue"}),
}
MAX_SECONDS = 3300
CLEANUP_SECONDS = 300
MAX_MAPPING_COMMANDS = 40
#: Ordinary-run key limits above the default; the full Silver Blades route presses 44 keys,
#: the full Pools of Darkness route, with its village leg, 53, and the full Pool route, with
#: its walk-out to the travel grid, 55.
ORDINARY_MAPPING_COMMANDS = {"ssb": 44, "darkness": 53, "pool": 55}
#: The camp reload adds Y, the slot letter, B, E and N to the 38 keys before them.
CAMP_LOAD_MAPPING_COMMANDS = 43
#: Seconds to wait for each guarded camp LOAD screen, and for the disk load after the slot.
CAMP_LOAD_WAIT = 30
#: Seconds Wish may still show its Party heading as waiting for a game at the first checkpoint, and
#: the pause between looks; a Wish that never attached would otherwise be driven on to the button check.
#: Wish connected 184 s and 183 s after launch in the two Amiga heal runs measured, so this covers that with margin.
CONNECT_WAIT = 240
CONNECT_POLL = 5
#: The Party heading until Wish has a target. The Messages panel's "Waiting to connect..." row is not
#: used: a build older than the one that withdraws it on connect keeps it after connecting.
WAITING_HEADING = "Party - waiting for a game"
CAMP_SLOT_WAIT = 90
DISCOVERY_SECONDS = 1800
#: Seconds the Automapper waits between roster reads; the grab after a game restart waits one.
ROSTER_SECONDS = 1
#: The leave-town route checkpoints 13 times before its terminal key; 1800 s of route.
LEAVE_DISCOVERY_SECONDS = 2100
#: Where Wish's tab rests while the party walks: the Character Editor, which frees the pipe
#: for a key and a guard after every step, or the Automapper, which polls throughout.
WALK_TABS = ("editor", "map")
#: Keys in the measured walk (17 moves, 5 turns); the Automapper walk takes them one at a time.
MAP_WALK_KEYS = 22
#: Seconds the guarded walk took with the Character Editor showing (ssb-campload7).
EDITOR_WALK_SECONDS = 512
#: Seconds one Automapper key takes: guard, encounter switch, queue, lead and settle,
#: Wish's shot and controls, both tab changes, the guard after and the read.
MAP_KEY_SECONDS = 100
#: The leave-town limit with the Character Editor walk replaced by the Automapper one, 10% over.
MAP_WALK_DISCOVERY_SECONDS = (LEAVE_DISCOVERY_SECONDS - EDITOR_WALK_SECONDS
                              + math.ceil(MAP_WALK_KEYS * MAP_KEY_SECONDS * 11 / 10))
#: Emulated PAL frames a second; WinUAE's queued-key delays count frames.
AMIGA_FRAMES_PER_SECOND = 50
#: A queued key lands this many frames after it is queued (30 s), so the Automapper is
#: showing, and polling, before it lands.
WALK_LEAD_FRAMES = 1500
#: The Automapper must be showing this many seconds before a queued key can land.
WALK_TAB_MARGIN = 5.0
#: The slowest emulation, against the wall clock, the Wish shot still waits for. Nothing
#: measures the speed; the probes saw a 500-frame delay land in 8 to 12 s.
MIN_EMULATION_SPEED = 0.8
#: The slowest emulation a missed key is still waited out at before cleanup proceeds.
SLOW_EMULATION_SPEED = 0.5
#: Seconds the Automapper keeps polling after a key could have landed, before its shot.
WALK_SETTLE = 10.0
OPENING_THIRD_SECONDS = 1500
DISCOVERY_SNAPSHOT = "ssb_new_verdigris"
#: The guard name of a title's code-wheel question, which `amigacursewheel.py` answers. The
#: title wait answers it only where the guard source has a rule for it.
WHEEL_SCREENS = {"curse": "curse_wheel"}
#: The AmigaDOS windows a title leaves its player at after quitting, drawn in hires, so no
#: exact crop exists: a wait for one guards the window as WinUAE drew it (`screens.plain_cut`).
HIRES_SCREENS = {"pool": frozenset({"cli"}), "curse": frozenset({"reboot"})}
#: Seconds `amigacursewheel.answer` waits after each of its two keys, and a `type` step before
#: it grabs the guard frame for the next key.
WHEEL_SETTLE = 2.0
#: Seconds to recognize the screen again before each wheel key and each typed key.
KEY_GUARD_WAIT = 30
#: The most one checkpoint read fetches, as for `acceptance.py --read-at`.
READ_LIMIT = 4096
#: Party nodes this close are dumped as one span, so the batch stays a few dump commands.
PARTY_SPAN_GAP = 1024
DISCOVERY_DF0_SHA256 = "068bc3e2bfd79e6014d427b5aef730d2bd52f0ba1cd28c3664fd9306a04a6948"
OPENING_FIRST_RULE = {
    "box": [88, 302, 700, 400],
    "sha256": "bfae49833516dc7b065f8121a4d5e6bd346cb091462c2b65baf334889eab7cfb",
    "and": [{"box": [186, 404, 586, 426],
             "sha256": "604731cd6f2b106a3670ba258e49c2545af33d3742467843fcd3a8c0f9ad7fe9"}],
}
OPENING_SECOND_RULE = {
    "box": [88, 302, 700, 400],
    "sha256": "b2853ef5783edfbc138ca70d86ffab72c097b43bb3598145fc4a050a5e460f57",
    "and": [{"box": [186, 404, 586, 426],
             "sha256": "604731cd6f2b106a3670ba258e49c2545af33d3742467843fcd3a8c0f9ad7fe9"}],
}
OPENING_THIRD_RULE = {
    "box": [88, 302, 700, 400],
    "sha256": "68c1de2212991faf7da8fa11e9e806cd7d54f8c51e788d81e766dcc6f5d93bf4",
    "and": [{"box": [186, 404, 586, 426],
             "sha256": "604731cd6f2b106a3670ba258e49c2545af33d3742467843fcd3a8c0f9ad7fe9"}],
}
#: Discovery modes that walk the measured route to the east gate; the second answers YES.
LEAVE_MODES = ("ssb-leave", "ssb-leave-yes", "ssb-camp-load")
#: Leave-town modes that answer YES and check the arrival in The Ruins.
YES_MODES = ("ssb-leave-yes", "ssb-camp-load")
OPENING_MODES = ("ssb-opening-first", "ssb-opening-second", "ssb-opening-after-second",
                 "ssb-opening-after-third")


def _opening_first_phase(route: Any) -> Any:
    from tools.amiga import maproute  # noqa: PLC0415

    load = maproute._load("ssb", "D", opening_scene=True)
    if (route.title != "ssb" or route.loaded_slot != "D"
            or route.mounted != ("df0", "df1")
            or not route.phases or route.phases[0] != load):
        raise AcceptanceStop("opening discovery needs the exact Silver Blades load prefix")
    return maproute.Phase("opening_menu", "title", load.steps[:6])


def _discovery_phases(route: Any) -> dict[str, Any]:
    """Validate the measured prefix without accepting the unfinished mapping route."""
    from tools.amiga import maproute  # noqa: PLC0415

    if route.title != "ssb" or route.loaded_slot != "D" or route.mounted != ("df0", "df1"):
        raise AcceptanceStop("discovery needs the prepared Silver Blades slot D and two drives")
    phases = {phase.name: phase for phase in route.phases}
    if len(phases) != len(route.phases) or [p.name for p in route.phases[:3]] != [
            "load", "stationary", "walk"]:
        raise AcceptanceStop("discovery needs a distinct ordered load, stationary and walk prefix")
    if any(not phases[name].ready for name in ("load", "stationary", "walk")):
        raise AcceptanceStop("discovery prefix is not ready")
    load, stationary, walk = (phases[name] for name in ("load", "stationary", "walk"))
    if ([s.kind for s in load.steps] != ["key"] * 6 + ["answer", "key", "key"]
            or [s.key for s in load.steps[:6]] != ["P", "L", "D", "V", "E", "B"]
            or [s.key for s in load.steps[7:]] != ["E", "N"]
            or [s.key for s in stationary.steps] != ["NP4", "NP6", "NP6", "NP4"]
            or any(s.kind != "turn" for s in stationary.steps)
            or [s.kind for s in walk.steps].count("move") != 17
            or [s.kind for s in walk.steps].count("snapshot") != 1
            or [s.kind for s in walk.steps].count("encounters") != 2
            or walk.steps[0].kind != "snapshot"
            or walk.steps[0].snapshot != DISCOVERY_SNAPSHOT
            or [(s.kind, s.encounters) for s in walk.steps if s.kind == "encounters"] != [
                ("encounters", True), ("encounters", False)]
            or walk.steps[-1].kind != "encounters"
            or any(s.kind not in ("move", "turn", "snapshot", "encounters") for s in walk.steps)
            or any(s.key != "NP8" for s in walk.steps if s.kind == "move")
            or [s.key for s in walk.steps if s.kind == "turn"] != [
                "NP4", "NP6", "NP4", "NP6", "NP4"]):
        raise AcceptanceStop("discovery prefix is not the measured Silver Blades route")
    checkpoints = set()
    for phase in (load, stationary, walk):
        for step in phase.steps:
            expected = step.expected
            if expected and expected.compare_to and expected.compare_to not in checkpoints:
                raise AcceptanceStop(f"discovery checkpoint {expected.compare_to} is missing")
            if step.checkpoint:
                if step.checkpoint in checkpoints:
                    raise AcceptanceStop(f"discovery checkpoint {step.checkpoint} repeats")
                checkpoints.add(step.checkpoint)
    if not {"loaded", "ssb_exit_square", "ssb_facing_exit"} <= checkpoints:
        raise AcceptanceStop("discovery has no measured start and terminal checkpoints")
    final = walk.steps[-2].expected
    if (walk.steps[-2].checkpoint != "ssb_facing_exit" or final is None
            or dict(final.engine or {}) != {"area": 16, "x": 15, "y": 8, "facing": 1}):
        raise AcceptanceStop("discovery terminal square is not 15,8,E")
    if (load, stationary, walk) != (maproute._load("ssb", "D", opening_scene=True),
                                    maproute._ssb_stationary(), maproute._ssb_walk()):
        raise AcceptanceStop("discovery prefix differs from the guarded measured route")
    return {name: phases[name] for name in ("load", "stationary", "walk")}


def _transition_phase(route: Any) -> Any:
    """The measured leave-town YES, unchanged from the guarded route."""
    from tools.amiga import maproute  # noqa: PLC0415

    phase = next((p for p in route.phases if p.name == "transition"), None)
    if phase is None or not phase.ready or phase != maproute._ssb_transition():
        raise AcceptanceStop("leave-town YES needs the guarded leave-town transition")
    return phase

def _phase_keys(phase: Any) -> int:
    """The keys a phase sends: one per key, turn, move, insert, or typed character, and a party's members less one per select."""
    from automap import amigaparty  # noqa: PLC0415

    return sum((amigaparty.MAX_MEMBERS - 1 if step.kind == "select"
                else len(step.keys) if step.kind == "type" else 1)
               for step in phase.steps
               if step.kind in ("key", "turn", "move", "insert", "select", "type"))


def _action_budget(route: Any) -> int:
    keys = _phase_keys
    total = max(1, keys(next(phase for phase in route.phases if phase.name == "reload")))
    for action in route.actions:
        if action.enabled:
            visits = 3 if action.kind == "spells" else 2
            total += visits * (keys(action.show) + keys(action.back))
            total += 2 if action.kind == "spells" else 1
    return total


def _persist_budget(route: Any, letter: str) -> int:
    """Action keys the persist leg adds: its save and reload, which the default leg never presses."""
    from tools.amiga import maproute  # noqa: PLC0415

    saved, rest = maproute.persist_phases(route, letter)
    return _phase_keys(saved) + _phase_keys(rest) + (
        PERSIST_RELOAD_KEYS + 2 * PERSIST_CONTINUE_PAGES
        if route.title in maproute.BRANCHED_RELOAD else 0)


def _latest_landing(queued: float, speed: float) -> float:
    """When a key queued at `queued` has landed and been released at `speed` of full speed."""
    return queued + (WALK_LEAD_FRAMES + KEY_HOLD_FRAMES) / AMIGA_FRAMES_PER_SECOND / speed


def _key_effect_problem(kind: str, before: dict[str, Any] | None,
                        after: dict[str, Any] | None) -> str | None:
    """Why the fix after a walk key does not show it landing once: a move leaves the square,
    a turn keeps the square and changes the facing. None when it does."""
    if before is None or after is None:
        return "the game fix was not readable"
    was, now = (before["x"], before["y"]), (after["x"], after["y"])
    if kind == "move" and now == was:
        return f"the party stayed at {was[0]},{was[1]}"
    if kind == "turn" and (now != was or after["facing"] == before["facing"]):
        return f"the turn left the party at {now[0]},{now[1]} facing {after['facing']}, from {before}"
    return None


def _plain_cut(raw: pathlib.Path, crop: pathlib.Path) -> bool:
    """Write the 720x568 window of a known emulator frame to `crop` as drawn, with no check
    that each Amiga pixel is doubled, for a hires AmigaDOS window `screens.canonical` cannot
    cut; on an exact frame it is the same picture. False for a frame of no known size."""
    from PIL import Image  # noqa: PLC0415

    with Image.open(raw) as image:
        rgb = image.convert("RGB")
    if rgb.size != screens.CANONICAL:
        known = screens.FRAMES.get(rgb.size)
        if known is None:
            return False
        replication, origin = known
        left, top = origin[0] * replication, origin[1] * replication
        rgb = rgb.crop((left, top, left + screens.CANONICAL[0], top + screens.CANONICAL[1]))
    rgb.save(crop)
    return True


class AcceptanceStop(RuntimeError):
    """A route failed closed; the run still collects evidence and cleans up."""


@dataclasses.dataclass(frozen=True)
class _LevelupOffsets:
    """Where a title keeps the experience and hit points Level up changes, and its thresholds."""

    experience: int
    hp_rolled: int
    hp_max: int
    hp_current: int
    threshold: Any


@dataclasses.dataclass(frozen=True)
class FightPlan:
    """How the fight leg reaches one title's fight and answers it."""

    title: str
    #: `grid_walk` (Pool), `tavern` (Curse), `wander` (Silver Blades) or `walk` (Pools of Darkness).
    entry: str
    #: The `cursefight.FightRules` the fight loop answers by.
    rules: Any
    #: The guard of the map the fight starts and ends on, which the loop calls `world`.
    map_state: str
    #: The keys each screen may receive.
    allowed: dict[str, frozenset[str]]
    #: Screens the walk to the fight answers, and the screens that end it.
    walk_answers: dict[str, str] = dataclasses.field(default_factory=dict)
    opens: tuple[str, ...] = ()
    #: Rules added to the exported guard map for this run: a state's rule, or alternatives
    #: added to an existing state's rules.
    extra_guards: dict[str, Any] = dataclasses.field(default_factory=dict)
    #: Whether the party's hit points are raised at the first bar so it outlasts the fight.
    survive: bool = True

    def named(self) -> set[str]:
        """Every screen the walk and the fight loop answer or wait for, the map as `world`."""
        rules = self.rules
        named = {*rules.answers, *rules.won, *rules.starting, *rules.after_bars,
                 *self.walk_answers, *self.opens, "world"}
        if self.entry == "tavern":
            named |= {"tavern", "injuries", "continue"}
        return named

    def states(self) -> set[str]:
        """Every guard the walk and the fight loop answer or wait for."""
        return {self.map_state if state == "world" else state for state in self.named()}


#: Pool's treasure bar cut short of TAKE and SHARE (an encounter that left nothing), which reads
#: VIEW POOL EXIT; the exported rule is the long bar. Measured on the same box of the won
#: fight's treasure screen in `~/.cache/wish/acceptance/WISH-359/fight/pool/watch1/fight/098-fight.png`.
POOL_TREASURE_SHORT = {
    "box": [54, 418, 460, 432],
    "sha256": "772c3ec8bfe073937ddeaec782ebcf86f68a5dbfe4a822583de16176ed61721b"}


def fight_plan(title: str) -> FightPlan:
    """The fight leg's plan for one title."""
    from tools.amiga import cursefight, ssbfight  # noqa: PLC0415

    if title == "curse":
        return _walk_keys_only(FightPlan(
            "curse", "tavern", cursefight.CURSE_FIGHT, "world", dict(cursefight.ALLOWED_KEYS),
            extra_guards=dict(cursefight.FIGHT_GUARDS)))
    if title == "ssb":
        return _walk_keys_only(FightPlan(
            "ssb", "wander", ssbfight.SSB_FIGHT, "world", dict(ssbfight.ALLOWED_KEYS),
            extra_guards={"treasure_bar": [ssbfight.TREASURE_SHORT]}))
    fields = ("control", "quickfight", "hit_points")
    extra: dict[str, Any] = {}
    if title == "pool":
        # COMBAT on the encounter menu and RETURN on YOU ARE SURPRISED (`route_pool._SURPRISED`);
        # the end-of-fight guards are 827e2d5d's.
        answers = {"encounter": "C", "surprised": "RET", "combat_bar": "Q",
                   "continue_battle": "N", "party_won": "RET", "treasure": "E",
                   "treasure_left": "N", "continue": "RET"}
        known = ("world", "encounter", "surprised", "party_won", "treasure_left", "continue",
                 "combat_bar", "continue_battle", "treasure")
        walk = {"continue": "RET"}
        opens: tuple[str, ...] = ("encounter", "surprised", "combat_bar")
        entry, map_state = "grid_walk", "grid"
        extra = {"treasure": [POOL_TREASURE_SHORT]}
    elif title == "darkness":
        # ATTACK on the encounter menu (af62c3ab); the won page also matches `continue` and
        # the treasure question `yes_no`, so both come first.
        answers = {"encounter": "A", "combat_bar": "Q", "continue_battle": "N",
                   "party_won": "RET", "treasure": "E", "treasure_left": "N", "continue": "RET"}
        known = ("world", "encounter", "party_won", "treasure_left", "continue", "yes_no",
                 "combat_bar", "continue_battle", "treasure")
        walk = {"continue": "RET", "yes_no": "N"}
        opens = ("encounter", "combat_bar")
        entry, map_state = "walk", "world"
    else:
        raise AcceptanceStop(f"no fight plan for {title}")
    rules = cursefight.FightRules(known=known, answers=answers, bar_fields=fields,
                                  linger=60.0, won=("party_won",))
    allowed = {"world": frozenset({"NP8", "NP4"}),
               **{state: frozenset({key}) for state, key in answers.items()},
               **{state: frozenset({key}) for state, key in walk.items()}}
    return _walk_keys_only(FightPlan(title, entry, rules, map_state, allowed, walk, opens,
                                     extra_guards=extra))


#: Keys the map may receive in a fight leg: moves and turns, never camp's E.
FIGHT_MAP_KEYS = frozenset({"NP2", "NP4", "NP6", "NP8"})


def _walk_keys_only(plan: FightPlan) -> FightPlan:
    """A plan whose keys are only those of the screens it answers or waits for, and only walk
    keys on the map: no camp, save picker, exit or load key, so the leg can never save."""
    named = plan.named()
    allowed = {state: keys for state, keys in plan.allowed.items() if state in named}
    allowed["world"] = allowed.get("world", frozenset()) & FIGHT_MAP_KEYS
    return dataclasses.replace(plan, allowed=allowed)


def _fight_specimen(title: str, manifest: dict[str, Any], route: Any) -> dict[str, Any]:
    """The pinned fight specimen's place, or why the manifest is not one."""
    if title == "pool":
        gaps = [reason for reason in route.unresolved if reason.startswith(SPECIMEN_GAPS["pool"])]
        if gaps:
            raise AcceptanceStop("the Pool fight runs the route's own outdoor specimen: " + gaps[0])
        return {"place": None, "pin": "the route's outdoor specimen"}
    pin = FIGHT_PINS[title]
    problems = []
    if route.loaded_slot != pin["load"]:
        problems.append(f"loaded slot {route.loaded_slot}, not {pin['load']}")
    if manifest.get("state_a") != pin["place"]:
        problems.append(f"place {manifest.get('state_a')}, not {pin['place']}")
    if title == "darkness":
        source = manifest.get("substitute") or {}
        if (source.get("sha256"), source.get("letter")) != (pin["substitute_sha256"],
                                                            pin["substitute_letter"]):
            problems.append("not the pinned substitute slot")
    else:
        fight_ = manifest.get("fight") or {}
        source = fight_.get("source") or {}
        if source.get("sha256") != pin["source_sha256"]:
            problems.append("not the pinned source disk")
        if fight_.get("load") != pin["load"] or fight_.get("place") != pin["place"]:
            problems.append("its fight stage loads another slot or square")
        if title == "curse" and not fight_.get("route"):
            problems.append("its fight stage has no walk to the tavern")
        if title == "ssb" and ("facing" not in fight_ or "square" not in fight_):
            problems.append("its fight stage has no street pair")
    if problems:
        raise AcceptanceStop(f"the {title} fight needs its pinned specimen: " + "; ".join(problems))
    return {"place": dict(pin["place"]), "pin": pin, "loaded": pin.get("loaded")}


def _staged_gate(path: pathlib.Path, letter: str) -> int:
    """The Silver Blades wandering-fight gate in slot `letter` of a staged disk one."""
    from goldbox.amiga_adf import AmigaDisk  # noqa: PLC0415
    from tools.amiga import ssbfight  # noqa: PLC0415

    return ssbfight.word(AmigaDisk.open(path).read_file(f"/SAVE/savgam{letter}.sav"), ssbfight.GATE)


def _check_fight_stage(title: str, manifest: dict[str, Any], route: Any) -> dict[str, Any] | None:
    """A Silver Blades stage's source hash and its gate, read back from the staged slot."""
    if title != "ssb":
        return None
    from tools.amiga import ssbfight  # noqa: PLC0415

    fight_ = manifest["fight"]
    key = f"{ssbfight.GATE:04X}"
    staged = (fight_.get("staged") or {}).get(key) or {}
    if staged.get("after") != ssbfight.GATE_ON:
        raise AcceptanceStop(f"the Silver Blades stage did not set ${key} to {ssbfight.GATE_ON}")
    source = pathlib.Path(fight_["source"]["path"])
    if not source.is_file() or digest(source) != fight_["source"]["sha256"]:
        raise AcceptanceStop(f"the Silver Blades stage's source disk {source} is missing or changed")
    disk = next(m.path for m in route.media if m.key == route.mounted[0])
    value = _staged_gate(disk, route.loaded_slot)
    if value != ssbfight.GATE_ON:
        raise AcceptanceStop(f"the staged slot {route.loaded_slot} reads ${key} = {value}, "
                             f"not {ssbfight.GATE_ON}")
    return {"gate": key, "before": staged.get("before"), "value": value,
            "source_sha256": fight_["source"]["sha256"]}


def _check_fight(route: Any, manifest: dict[str, Any]) -> dict[str, Any]:
    """The fight leg's static dependencies: a ready load phase and the title's pinned specimen."""
    load = next((phase for phase in route.phases if phase.name == "load"), None)
    if load is None or route.phases[0].name != "load":
        raise AcceptanceStop("load must be the first phase")
    specimen = _fight_specimen(route.title, manifest, route)
    # Another phase's reason does not stop a leg that never runs that phase, and the specimen
    # gap is the pin's to judge.
    skipped = {phase.reason for phase in route.phases if not phase.ready and phase.name != "load"}
    unready = [] if load.ready else [f"load: {load.reason or 'no reason supplied'}"]
    unready.extend(reason for reason in route.unresolved if reason not in skipped
                   and not reason.startswith("Game-sheet routes")
                   and not (specimen["place"] is not None
                            and reason.startswith(SPECIMEN_GAPS[route.title])))
    if unready:
        raise AcceptanceStop("route incomplete: " + "; ".join(unready))
    from types import SimpleNamespace  # noqa: PLC0415

    _check_steps(SimpleNamespace(phases=[load]))
    return specimen


def _fight_load(route: Any, place: dict[str, int] | None,
                loaded: dict[str, Any] | None = None) -> Any:
    """The route's load phase, its `loaded` checkpoint expecting the fight specimen's square, or
    `loaded` when the pin gives one (Pools of Darkness' slot loads onto the overland)."""
    load = route.phases[0]
    if place is None:
        return load
    from tools.amiga import maproute  # noqa: PLC0415

    expected = maproute.Expected(
        engine=dict(loaded) if loaded else {k: place[k] for k in ("x", "y", "facing")})
    steps = tuple(dataclasses.replace(step, expected=expected) if step.checkpoint == "loaded"
                  else step for step in load.steps)
    return dataclasses.replace(load, steps=steps)


def _fight_memory(holder: str, route: Any) -> Any:
    """Reads of the running fight: the record in turn and its fields, the fix and the mode.

    Curse and Silver Blades use their fight drivers' own; Pool and Pools of Darkness read the
    record named by their party row's `current`, with its control, quickfight and hit points."""
    from automap import amigaparty  # noqa: PLC0415
    from tools.amiga import cursefight, ssbfight  # noqa: PLC0415

    if route.title == "curse":
        return cursefight.Memory(holder)
    if route.title == "ssb":
        return ssbfight.Memory(holder)
    row_ = amigaparty.ROWS[route.game_key]
    memory = cursefight.Memory(holder)
    memory.title = route.game_key
    memory.current = row_.current
    memory.record = {"control": row_.control.offset, "quickfight": row_.quickfight.offset,
                     "hit_points": row_.hp.offset}
    memory.record_size = row_.record_size
    return memory


def _fight_screens(controller: Any, plan: FightPlan, memory: Any) -> Any:
    """`cursefight.fight`'s screens over the controller's game and guards.

    Its map is the plan's `map_state` under the name `world`. Every key is an action key of the
    controller's budget; the first key on a command bar waits for the greyed check. The mode is
    read once on each newly seen screen and recorded with the key sent on it."""
    from automap import amigaparty  # noqa: PLC0415
    from tools.amiga import curseadd, cursefight  # noqa: PLC0415

    modes = controller.summary["fight"]["modes"]

    class FightScreens(curseadd.Screens):
        known = plan.rules.known
        allowed = plan.allowed

        def __init__(self) -> None:
            super().__init__(controller.game, controller.args.holder, controller.out / "fight",
                             controller.guards, controller.route_end, clock=controller.clock,
                             sleep=controller.sleep)
            self.last_state: object = object()
            self.memory = memory

        def _matches(self, state: str, crop: pathlib.Path) -> bool:
            name = plan.map_state if state == "world" else state
            rules = getattr(self.guards, "rules", None)
            return (rules is None or name in rules) and bool(self.guards(name, crop))

        def _mode(self) -> Any:
            if memory._target is None:
                return "not located"
            try:
                return curseadd.bounded(lambda _h: amigaparty.mode(memory.target()), memory.holder,
                                        cursefight.MODE_READ_LIMIT)
            except RouteError as exc:
                return f"error: {exc}"

        def look(self, label: str) -> tuple[list[str], pathlib.Path]:
            self.count += 1
            raw = self.out / f"{self.count:03d}-{label}-raw.png"
            crop = self.out / f"{self.count:03d}-{label}.png"
            try:
                self.grabbed = bool(self.guest.grab(label, raw, crop, self.left(20)))
            except ShotTimedOut as exc:
                controller.log("shot_retry", state=label, error=str(exc))
                self.grabbed = False
            if not self.grabbed:
                return [], raw
            seen = [state for state in self.known if self._matches(state, crop)]
            state = seen[0] if seen else None
            if state != self.last_state:
                self.last_state = state
                modes.append({"screen": state, "shot": str(crop), "mode": self._mode(),
                              "elapsed": round(controller.clock() - controller.started, 3)})
            return seen, crop

        def note(self, key: str, on: str) -> None:
            self.events.append({"from": on, "key": key})
            controller.log("key", key=key, screen=on)
            if modes and modes[-1]["screen"] == on and "key" not in modes[-1]:
                modes[-1]["key"] = key
            else:
                modes.append({"screen": on, "key": key, "mode": self._mode(),
                              "elapsed": round(controller.clock() - controller.started, 3)})

        def press(self, key: str, on: str) -> None:
            curseadd.require(key in self.allowed.get(on, ()),
                             f"{key} is not a key this driver sends on {on}")
            if on == "combat_bar":
                if not controller.greyed_done:
                    controller._fight_bar(memory)
                bars = controller.summary["fight"]["found"].get("bars") or []
                if controller.press_off and not controller.pod and bars:
                    controller._press_quickfight_off(bars)
                if (controller.watch_map and not controller.map_hold_done
                        and controller._last_quick(bars)):
                    # The last Q is queued with the Automapper showing, and stays showing.
                    self.press_queued(key, on)
                    controller._map_hold(plan, self)
                    return
            controller._count(action=True)
            if (on == "continue_battle" and controller.watch and not controller.edge_done
                    and controller._watch_edge(key)):
                # The edge queued the key itself, once on each branch.
                self.note(key, on)
                return
            self.guest.press(self.holder, key, timeout=self.left(30))
            self.note(key, on)

        def press_queued(self, key: str, on: str) -> dict[str, Any]:
            """The key queued in the emulator with the Automapper showing before it lands."""
            curseadd.require(key in self.allowed.get(on, ()),
                             f"{key} is not a key this driver sends on {on}")
            controller._count(action=True)
            schedule = controller._scheduled_key(key, show_map=True)
            self.note(key, on)
            return schedule

    return FightScreens()


def _merge_guards(path: pathlib.Path, extra: dict[str, Any]) -> None:
    """Add a fight plan's rules to an exported guard file: a new state, or alternatives."""
    rules = json.loads(path.read_text())
    for state, rule in extra.items():
        added = rule if isinstance(rule, list) else [rule]
        if state in rules:
            if not isinstance(rule, list):
                raise AcceptanceStop(f"the fight guard {state} is already a guard of this title")
            have = rules[state] if isinstance(rules[state], list) else [rules[state]]
            rules[state] = [*have, *added]
        else:
            rules[state] = rule
    path.write_text(json.dumps(rules, indent=2) + "\n")


def digest(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def row(status: str = "unproven", *, expected: Any = None, observed: Any = None,
        evidence: Any = None, reason: str | None = None) -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(status)
    return {"status": status, "expected": expected, "observed": observed,
            "evidence": evidence or [], "reason": reason}


def _driver_sha() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], check=True,
                            text=True, capture_output=True)
    return result.stdout.strip()


def _phase_map(route: Any) -> dict[str, Any]:
    phases = {phase.name: phase for phase in route.phases}
    if len(phases) != len(route.phases):
        raise AcceptanceStop("the route repeats a phase name")
    absent = [name for name in REQUIRED if name not in phases]
    if absent:
        raise AcceptanceStop(f"required phases missing: {', '.join(absent)}")
    names = [phase.name for phase in route.phases]
    if names[0] != "load":
        raise AcceptanceStop("load must be the first phase")
    if names.index("stationary") > names.index("walk"):
        raise AcceptanceStop("stationary must precede walk")
    if names.index("reload") > names.index("reopen_step"):
        raise AcceptanceStop("reload must precede reopen_step")
    checkpoints = set()
    for phase in route.phases:
        for step in phase.steps:
            expected = step.expected
            if (expected is not None and expected.compare_to is not None
                    and expected.compare_to not in checkpoints):
                raise AcceptanceStop(
                    f"checkpoint {expected.compare_to} must precede its comparison")
            if step.checkpoint:
                if step.checkpoint in checkpoints:
                    raise AcceptanceStop(f"checkpoint {step.checkpoint} is repeated")
                checkpoints.add(step.checkpoint)
    _check_steps(route)
    unready = [f"{p.name}: {p.reason or 'no reason supplied'}" for p in phases.values()
               if not p.ready]
    if route.unresolved:
        unready.extend(route.unresolved)
    if unready:
        raise AcceptanceStop("route incomplete: " + "; ".join(unready))
    return phases


def _check_steps(route: Any) -> None:
    """Typed keys, relaunches and checkpoint reads, checked before any lane is claimed."""
    for phase in route.phases:
        for step in phase.steps:
            keys = tuple(getattr(step, "keys", ()) or ())
            if step.kind == "type" and (not keys or step.key is not None):
                raise AcceptanceStop(f"{phase.name}: a type step needs its keys and no single key")
            if step.kind == "type" and not getattr(step, "screen", None):
                raise AcceptanceStop(f"{phase.name}: a type step needs the screen its keys go to")
            if (step.kind == "type" or getattr(step, "relaunch", False)) and not step.state:
                raise AcceptanceStop(f"{phase.name}: a {step.kind} step needs a screen to wait for")
            if step.kind != "type" and keys:
                raise AcceptanceStop(f"{phase.name}: only a type step has a key list")
            if getattr(step, "relaunch", False) and step.kind not in ("key", "type", "reset"):
                raise AcceptanceStop(f"{phase.name}: only a key, type or reset step can relaunch the program")
            if step.kind == "reset" and not getattr(step, "relaunch", False):
                raise AcceptanceStop(f"{phase.name}: a reset step restarts the program, so it relaunches")
            reads = tuple(getattr(step, "reads", ()) or ())
            if reads and not step.checkpoint:
                raise AcceptanceStop(f"{phase.name}: checkpoint reads need a checkpoint")
            for spec in reads:
                if spec.anchor not in ("abs", "base", "a4") or not 0 < spec.length <= READ_LIMIT:
                    raise AcceptanceStop(f"{phase.name}: read {spec.name} needs an abs, base or "
                                         f"a4 anchor and 1 to {READ_LIMIT} bytes")


def _title_pages(route: Any, guards: Any) -> tuple:
    """The interstitial rows the title wait answers: key rows waiting for `title`, and the
    title's code-wheel question when the guard source has a rule for it."""
    rows = tuple(row for row in route.amiga_title.interstitials
                 if row[1][0] == "keys" and row[2] is not None and "title" in row[2])
    wheel = WHEEL_SCREENS.get(route.title)
    if wheel and wheel in (getattr(guards, "rules", None) or {}):
        rows += ((wheel, ("wheel",), frozenset({"title"}), 1),)
    return rows


def _declared_pages(route: Any, phases: list[Any]) -> set[str]:
    """The screens the title wait and each phase's pages may press a key on."""
    rows = {row[0]: row for row in route.amiga_title.interstitials}
    names = {row[0] for row in _title_pages(route, None)}
    for phase in phases:
        for name in getattr(phase, "pages", ()) or ():
            if name not in rows:
                raise AcceptanceStop(f"{phase.name} names page {name}, which has no interstitial row")
            if rows[name][1][0] == "keys":
                names.add(name)
    return names


def _page_states(route: Any) -> set[str]:
    """The screens the load phase presses a key on, which need a guard like any other."""
    if route.title != "ssb" or not route.phases or route.phases[0].name != "load":
        return set()
    return {row[0] for row in route.amiga_title.interstitials if row[1][0] == "keys"
            and row[2] is None}


def _states(route: Any, *, actions: bool = True) -> set[str]:
    phases = [*route.phases]
    for action in route.actions:
        if actions and action.enabled:
            if action.show is None or action.back is None:
                raise AcceptanceStop(f"{action.kind} has no game-display route")
            if not action.show.ready or not action.back.ready:
                raise AcceptanceStop(f"{action.kind} has an unready game-display route")
            phases.extend((action.show, action.back))
    states = {state for phase in phases for state in
              (phase.initial_state, *(step.state for step in phase.steps))}
    return states | _page_states(route) | _declared_pages(route, phases)


def _selected_actions(args: argparse.Namespace, route: Any) -> list[Any]:
    """The enabled actions `--action` leaves to run (all of them without it)."""
    wanted = list(getattr(args, "action", None) or [])
    by_kind = {action.kind: action for action in route.actions}
    for kind in wanted:
        if kind not in by_kind:
            raise AcceptanceStop(f"--action {kind} is not an action of this route")
        if not by_kind[kind].enabled:
            raise AcceptanceStop(f"--action {kind} is not enabled on this route")
    return [action for action in route.actions
            if action.enabled and (not wanted or action.kind in wanted)]


def _check_persist(args: argparse.Namespace, route: Any) -> list[Any]:
    """The persist leg's static dependencies: the title's prefix phases, the reload and one action."""
    from tools.amiga import maproute  # noqa: PLC0415

    phases = {phase.name: phase for phase in route.phases}
    needed = (*maproute.LEG_PREFIX[route.title], "reload")
    absent = [name for name in needed if name not in phases]
    if absent:
        raise AcceptanceStop(f"required phases missing: {', '.join(absent)}")
    unready = [f"{name}: {phases[name].reason or 'no reason supplied'}"
               for name in needed if not phases[name].ready]
    # Another phase's reason does not stop a leg that never runs that phase.
    skipped = {phase.reason for phase in route.phases if not phase.ready
               and phase.name not in needed}
    unready.extend(reason for reason in route.unresolved if reason not in skipped)
    if unready:
        raise AcceptanceStop("route incomplete: " + "; ".join(unready))
    if route.phases[0].name != "load":
        raise AcceptanceStop("load must be the first phase")
    actions = _selected_actions(args, route)
    if not actions:
        raise AcceptanceStop("the persist leg needs at least one enabled action")
    for action in actions:
        if action.show is None or action.back is None:
            raise AcceptanceStop(f"{action.kind} has no game-display route")
        if not action.show.ready or not action.back.ready:
            raise AcceptanceStop(f"{action.kind} has an unready game-display route")
    return actions


def _check_reconnect(route: Any) -> None:
    """The reconnect leg's static dependencies: the load phase alone, ready and well formed."""
    load = next((phase for phase in route.phases if phase.name == "load"), None)
    if load is None:
        raise AcceptanceStop("required phases missing: load")
    if route.phases[0].name != "load":
        raise AcceptanceStop("load must be the first phase")
    # Another phase's reason does not stop a leg that never runs that phase.
    skipped = {phase.reason for phase in route.phases if not phase.ready
               and phase.name != "load"}
    unready = [] if load.ready else [f"load: {load.reason or 'no reason supplied'}"]
    unready.extend(reason for reason in route.unresolved if reason not in skipped)
    if unready:
        raise AcceptanceStop("route incomplete: " + "; ".join(unready))
    from types import SimpleNamespace  # noqa: PLC0415

    _check_steps(SimpleNamespace(phases=[load]))


def _persist_phases(route: Any, letter: str) -> list[Any]:
    """Every phase the persist leg runs, for the static checks."""
    from tools.amiga import maproute  # noqa: PLC0415

    names = (*maproute.LEG_PREFIX[route.title], "reload")
    return [*(phase for phase in route.phases if phase.name in names),
            *maproute.persist_phases(route, letter)]


def _persist_states(route: Any, actions: list[Any], letter: str) -> set[str]:
    phases = _persist_phases(route, letter)
    for action in actions:
        phases.extend((action.show, action.back))
    states = {state for phase in phases for state in
              (phase.initial_state, *(step.state for step in phase.steps))}
    return (states | PERSIST_BRANCH_STATES.get(route.title, frozenset()) | _page_states(route)
            | _declared_pages(route, phases) | {"title"})


def _deadline_limit(mode: str | None, walk_tab: str = "editor") -> int:
    """The largest total deadline, cleanup included, that a mode may run with."""
    if mode == "ssb-opening-after-third":
        return OPENING_THIRD_SECONDS
    if mode in LEAVE_MODES:
        return MAP_WALK_DISCOVERY_SECONDS if walk_tab == "map" else LEAVE_DISCOVERY_SECONDS
    return DISCOVERY_SECONDS if mode else MAX_SECONDS


def guest_failure_fields(exc: BaseException) -> dict[str, Any]:
    """The step, ssh exit code and command length of a failed guest command, for the failure event."""
    if not isinstance(exc, winwish.GuestError):
        return {}
    return {"step": exc.step, "exit_code": exc.exit_code, "command_length": exc.command_length}


def preflight(args: argparse.Namespace, *, guest: Any, route_for: Any,
              driver_sha: str | None = None) -> tuple[Any, Any, pathlib.Path, dict[str, Any]]:
    """Check every static dependency before a lane can be claimed.

    The guard export is built in a temporary folder beside its final place and renamed
    only when every check has passed, so a failed start leaves nothing to block the next.
    """
    final = pathlib.Path(args.out) / "guards-export"
    if final.exists():
        raise AcceptanceStop(f"guard export directory already exists: {final}")
    made: list[pathlib.Path] = []
    try:
        route, guards, zipped, info = _preflight(args, made, guest=guest, route_for=route_for,
                                                 driver_sha=driver_sha)
        try:
            made[0].rename(final)
        except OSError as exc:
            raise AcceptanceStop(f"guard export directory cannot be put in place: {exc}") from exc
    except BaseException:
        for folder in made:
            shutil.rmtree(folder, ignore_errors=True)
        raise
    info["guards"]["export"] = str(final / "guards.json")
    return route, guards, zipped, info


def _preflight(args: argparse.Namespace, made: list[pathlib.Path], *, guest: Any,
               route_for: Any, driver_sha: str | None = None,
               ) -> tuple[Any, Any, pathlib.Path, dict[str, Any]]:
    if not BUILD_SHA.fullmatch(args.sha):
        raise AcceptanceStop("--sha must be a full 40-digit frozen-build commit")
    mode = getattr(args, "discover", None)
    leg = getattr(args, "leg", "mapping")
    if leg == "persist" and mode:
        raise AcceptanceStop("--leg persist is not a discovery mode")
    if leg == "reconnect" and mode:
        raise AcceptanceStop("--leg reconnect is not a discovery mode")
    if leg == "reconnect" and getattr(args, "action", None):
        raise AcceptanceStop("--leg reconnect presses no actions")
    if leg == "fight" and mode:
        raise AcceptanceStop("--leg fight is not a discovery mode")
    if leg in ("mapping", "fight") and getattr(args, "action", None):
        raise AcceptanceStop("--action needs --leg persist")
    flags = [name for name in WATCH_ROWS if getattr(args, name, False)]
    if flags and leg != "fight":
        raise AcceptanceStop(f"--{flags[0].replace('_', '-')} needs --leg fight")
    if getattr(args, "watch_dip", False) and not getattr(args, "watch", False):
        raise AcceptanceStop("--watch-dip needs --watch")
    if getattr(args, "watch_dip", False) and args.title != "curse":
        raise AcceptanceStop("--watch-dip runs only on Curse of the Azure Bonds")
    if getattr(args, "watch_map", False) and not getattr(args, "watch", False):
        raise AcceptanceStop("--watch-map needs --watch")
    if getattr(args, "watch_map", False) and getattr(args, "press_quickfight_off", False):
        raise AcceptanceStop("--watch-map and --press-quickfight-off do not run together")
    if getattr(args, "press_quickfight_off", False) and args.title != "darkness":
        raise AcceptanceStop("--press-quickfight-off runs only on Pools of Darkness")
    if getattr(args, "quickfight_control", False) and not (
            leg == "persist" and args.title in ("curse", "ssb")
            and getattr(args, "action", None) == ["quickfight"]):
        raise AcceptanceStop("--quickfight-control runs only on --leg persist, Curse or Silver "
                             "Blades, with --action quickfight alone")
    wait_lanes = getattr(args, "wait_lanes", 0)
    if not 0 <= wait_lanes <= MAX_WAIT_LANES:
        raise AcceptanceStop(f"--wait-lanes must be from 0 to {MAX_WAIT_LANES} seconds")
    walk_tab = getattr(args, "walk_tab", "editor")
    if walk_tab == "map" and mode not in LEAVE_MODES:
        raise AcceptanceStop("--walk-tab map needs a leave-town discovery mode")
    opening = mode in OPENING_MODES
    discovery = mode in LEAVE_MODES or opening
    maximum = _deadline_limit(mode, walk_tab)
    if args.deadline > maximum or args.deadline <= CLEANUP_SECONDS:
        raise AcceptanceStop(f"--deadline must be above {CLEANUP_SECONDS} and at most {maximum}")
    if not pathlib.Path(args.manifest).is_file():
        raise AcceptanceStop("the prepared manifest is missing")
    manifest = json.loads(pathlib.Path(args.manifest).read_text())
    if leg != "fight" and isinstance(manifest, dict) and "fight" in manifest:
        raise AcceptanceStop("a fight stage runs only with --leg fight")
    route = route_for(args.title, manifest)
    if discovery:
        source = manifest.get("substitute")
        if args.title != "ssb" or manifest.get("title") != "ssb" or not isinstance(
                source, dict) or source.get("letter") != "A" or manifest.get("state_a") != {
                    "area": 16, "x": 3, "y": 3, "facing": 2}:
            raise AcceptanceStop("discovery needs source A imported into D at 16,3,3,S")
        if opening:
            if manifest.get("opening_scene") is not True:
                raise AcceptanceStop("opening discovery needs an approved opening scene")
            _opening_first_phase(route)
        else:
            _discovery_phases(route)
            if mode in YES_MODES:
                _transition_phase(route)
        from tools.amiga import route_silver_blades  # noqa: PLC0415

        route_silver_blades.journal_preflight(sys.executable)
    else:
        persist_actions = _check_persist(args, route) if leg == "persist" else None
        if leg == "reconnect":
            _check_reconnect(route)
        elif leg == "fight":
            fight_specimen = _check_fight(route, manifest)
            fight_stage = _check_fight_stage(args.title, manifest, route)
        elif persist_actions is None:
            _phase_map(route)
        if args.title == "ssb":
            from tools.amiga import route_silver_blades  # noqa: PLC0415

            route_silver_blades.journal_preflight(sys.executable)
    if not winwish._mute_proof(pathlib.Path(args.mute_proof)):
        raise AcceptanceStop("the WinUAE audio mute proof is missing or stale")
    if len(route.mounted) > 4 or not route.mounted:
        raise AcceptanceStop("route has no initial media or has more than four drives")
    media = {item.key: item for item in route.media}
    if len(media) != len(route.media) or any(k not in media for k in route.mounted):
        raise AcceptanceStop("the route media keys are missing or repeated")
    if discovery:
        from tools.amiga import route_silver_blades  # noqa: PLC0415

        pins = {"df0": DISCOVERY_DF0_SHA256,
                "df1": route_silver_blades.DISK_B_SHA256}
        if set(media) != set(pins) or any(media[key].sha256 != sha
                                          for key, sha in pins.items()):
            raise AcceptanceStop("discovery prepared media do not match the approved DF0/DF1 pins")
    for item in route.media:
        if not item.path.is_file() or digest(item.path) != item.sha256:
            raise AcceptanceStop(f"prepared medium {item.key} is missing or changed")
    persist = None
    if leg == "persist":
        from types import SimpleNamespace  # noqa: PLC0415

        from tools.amiga import maproute  # noqa: PLC0415

        letter = maproute.persist_letter(args.title, manifest, route.media)
        if letter is None:
            raise AcceptanceStop("every persist save letter is on the prepared save disk")
        _check_steps(SimpleNamespace(phases=_persist_phases(route, letter)))
        persist = {"letter": letter, "actions": [action.kind for action in persist_actions]}
    expected_source = f"guards_{guardmaps.FILES[route.title]}.json"
    if route.guard_path.name != expected_source or not route.guard_path.is_file():
        raise AcceptanceStop(f"the measured guard source must be {expected_source}")
    pathlib.Path(args.out).mkdir(parents=True, exist_ok=True)
    export_dir = pathlib.Path(tempfile.mkdtemp(prefix=".guards-export.", dir=args.out))
    made.append(export_dir)
    try:
        rc = guardmaps.main(["--maps", str(route.guard_path.parent), "export",
                             "--title", route.title, "--out", str(export_dir)])
    except (OSError, ValueError) as exc:
        raise AcceptanceStop(f"guard export failed: {exc}") from exc
    if rc:
        raise AcceptanceStop(f"guard export failed with exit {rc}")
    exported = export_dir / "guards.json"
    plan = fight_plan(route.title) if leg == "fight" else None
    if plan is not None:
        _merge_guards(exported, plan.extra_guards)
    guards = screens.PixelGuards(exported)
    if opening:
        phase = _opening_first_phase(route)
        states = {phase.initial_state, *(step.state for step in phase.steps),
                  "ssb_opening_first"}
        if mode != "ssb-opening-first":
            states.add("ssb_opening_second")
        if mode == "ssb-opening-after-third":
            states.add("ssb_opening_third")
    elif discovery:
        from tools.amiga import maproute  # noqa: PLC0415

        prefix = [*_discovery_phases(route).values(),
                  *((_transition_phase(route),) if mode in YES_MODES else ()),
                  *((maproute._ssb_camp(), maproute._ssb_camp_load(),
                     maproute._ssb_camp_reload()) if mode == "ssb-camp-load" else ())]
        states = {"title"} | _page_states(route) | {
            state for phase in prefix
            for state in (phase.initial_state, *(s.state for s in phase.steps))}
    elif persist:
        states = _persist_states(route, persist_actions, persist["letter"])
    elif plan is not None:
        load = route.phases[0]
        states = ({"title", load.initial_state, *(step.state for step in load.steps)}
                  | _page_states(route) | _declared_pages(route, [load]) | plan.states())
    else:
        states = _states(route, actions=False)
    missing = states - guards.rules.keys()
    if missing:
        raise AcceptanceStop("route has no measured guards for " + ", ".join(sorted(missing)))
    if opening and guards.rules["ssb_opening_first"] != OPENING_FIRST_RULE:
        raise AcceptanceStop("opening discovery needs the independent exact two-box guard")
    if mode in OPENING_MODES[1:] and guards.rules["ssb_opening_second"] != OPENING_SECOND_RULE:
        raise AcceptanceStop("second opening discovery needs the independent exact two-box guard")
    if mode == "ssb-opening-after-third" and guards.rules["ssb_opening_third"] != OPENING_THIRD_RULE:
        raise AcceptanceStop("third opening discovery needs the independent exact two-box guard")
    if not route.loaded_slot or len(route.loaded_slot) != 1:
        raise AcceptanceStop("the manifest has no single prepared load slot")
    if not driver_sha:
        driver_sha = _driver_sha()
    os.environ["GH_REPO"] = "malcyon/wish"
    zipped = winwish.fetch(guest, args.sha)
    listing = guest.gh("run", "list", "--workflow", winwish.WORKFLOW,
                       "--commit", args.sha, "--limit", "20", "--json",
                       "databaseId,headSha,conclusion,createdAt")
    release_run = winwish.pick_run(listing, args.sha)
    note = zipped.parent / winwish.COMMIT_FILE
    if not note.is_file() or note.read_text().strip() != args.sha:
        raise AcceptanceStop("the frozen artifact lacks a matching commit note")
    winwish.check_zip_commit(zipped, args.sha)
    info = {"build_sha": args.sha, "driver_sha": driver_sha,
            "release_run": release_run,
            "guards": {"source": str(route.guard_path),
                       "source_sha256": digest(route.guard_path),
                       "export": str(exported), "export_sha256": digest(exported)},
            "release_artifact": {"path": str(zipped), "sha256": digest(zipped)},
            "loaded_slot": route.loaded_slot, "provenance": dict(route.provenance),
            "media": {key: {"source": str(item.path), "source_sha256": item.sha256}
                       for key, item in media.items()}}
    if discovery:
        info["provenance"]["approved_media_sha256"] = pins
    if persist:
        info["leg"] = "persist"
        info["persist"] = persist
    if plan is not None:
        info["leg"] = "fight"
        info["fight"] = {"entry": plan.entry, "survive": plan.survive,
                         "place": fight_specimen["place"], "pin": fight_specimen["pin"],
                         "loaded": fight_specimen.get("loaded"),
                         "stage": fight_stage,
                         "walk": ({k: manifest["fight"].get(k)
                                   for k in ("place", "route", "square", "facing", "names")}
                                  if "fight" in manifest else None)}
    return route, guards, zipped, info


def _party_spans(blocks: list[tuple[int, int]],
                 memory: Any) -> list[tuple[int, int]]:
    """Merge nearby blocks into dump spans, never across a memory region."""
    regions = tuple(memory) if isinstance(memory, tuple) else ()

    def region(address: int, length: int) -> int | None:
        if not regions:
            return 0
        return next((base for base, size in regions
                     if base <= address and address + length <= base + size), None)

    spans: list[list[int]] = []
    for address, length in sorted(set(blocks)):
        home = region(address, length)
        if home is None:
            continue
        if (spans and spans[-1][2] == home
                and address <= spans[-1][0] + spans[-1][1] + PARTY_SPAN_GAP):
            spans[-1][1] = max(spans[-1][1], address + length - spans[-1][0])
        else:
            spans.append([address, length, home])
    return [(start, size) for start, size, _home in spans]


class _BatchedParty:
    """A pipe target whose party reads come from one batched read where they can.

    `amigaparty.read_party` reads every list a level per round trip, so a member
    carrying 24 items costs about 31 sequential WinUAE pipe round trips. The previous
    checkpoint's party names every node; dumping those spans in one call and
    answering `walk`'s levels from it gives the same walk, with all its pointer and
    plausibility checks. A level asking for any block outside the spans is read
    live, whole.
    """

    def __init__(self, target: Any, blocks: list[tuple[int, int]]):
        self.layout = getattr(target, "layout", None)
        self.data_base = getattr(target, "data_base", None)
        self.memory = getattr(target, "memory", None)
        self._source = target
        self.batched_blocks = len(blocks)
        self.live_reads = 0
        spans = _party_spans(blocks, self.memory) if blocks else []
        self._spans = list(zip(spans, self._read(spans))) if spans else []

    def _read(self, blocks: list[tuple[int, int]]) -> list[bytes]:
        many = getattr(self._source, "read_blocks", None)
        if many is not None:
            return [bytes(raw) for raw in many(blocks)]
        return [bytes(self._source.read(address, length)) for address, length in blocks]

    def _cached(self, address: int, length: int) -> bytes | None:
        for (start, size), raw in self._spans:
            if start <= address and address + length <= start + size:
                return raw[address - start:address - start + length]
        return None

    def read_blocks(self, blocks: Any) -> list[bytes]:
        want = [(block[0], block[1]) for block in blocks]
        found = [self._cached(address, length) for address, length in want]
        if all(raw is not None for raw in found):
            return found
        self.live_reads += 1
        return self._read(want)

    def read(self, address: int, length: int) -> bytes:
        return self.read_blocks([(address, length)])[0]


def _party_nodes(target: Any, party: Any) -> list[tuple[int, int]]:
    """Every record, item and effect node of a party just read, as `(address, size)`."""
    from automap import amigaparty  # noqa: PLC0415

    row = amigaparty.row_for(target)
    if row is None or not party:
        return []
    nodes = []
    for member in party:
        nodes.append((member.address, row.record_size))
        nodes += [(node.address, row.items.size) for node in member.item_nodes]
        nodes += [(node.address, row.effects.size) for node in member.effect_nodes]
    return nodes


def _is_party_heading(line: str) -> bool:
    """Whether a `controls` row is the Party panel's heading, `Party` or `Party - <message>`."""
    kind, _, rest = line.partition("|")
    name = rest.split("|", 1)[0]
    return kind == "Text" and (name == "Party" or name.startswith("Party - "))


class Controller:
    """One bounded boot with injectable guests and clock for lifecycle tests."""

    def __init__(self, args: argparse.Namespace, *, guest: Any, lane: Any,
                 game: Any, guards: Any, route: Any, zipped: pathlib.Path,
                 info: dict[str, Any], clock=time.monotonic, sleep=time.sleep):
        self.args, self.guest, self.lane, self.game = args, guest, lane, game
        self.guards, self.route, self.zipped, self.info = guards, route, zipped, info
        self.clock, self.sleep = clock, sleep
        self.out = pathlib.Path(args.out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.events = self.out / "events.jsonl"
        self.leg = getattr(args, "leg", "mapping")
        self.persist: dict[str, Any] | None = info.get("persist") if self.leg == "persist" else None
        self.fight: dict[str, Any] | None = info.get("fight") if self.leg == "fight" else None
        #: Whether the fight leg's greyed check has run, at the first command bar.
        self.greyed_done = False
        #: Whether the clear-quickfight edge at CONTINUE BATTLE has run, and the member the dip
        #: check staged QUICK on, and what the Pools of Darkness Quickfight off press recorded.
        self.edge_done = False
        self.watch = bool(getattr(args, "watch", False))
        self.press_off = bool(getattr(args, "press_quickfight_off", False))
        #: `--watch-map`: whether the last Q's hold with the Automapper showing has run.
        self.watch_map = bool(getattr(args, "watch_map", False))
        self.map_hold_done = False
        #: The persist leg's control: Quickfight off is not pressed, so the saved byte stays 1.
        self.quickfight_control = bool(getattr(args, "quickfight_control", False))
        self.dip: dict[str, Any] | None = None
        self.pod: dict[str, Any] = {}
        self.key_sent = 0.0
        self._set_deadlines()
        self.mapping_commands = self.action_commands = 0
        #: The reload after the game restarts has its own key budget, so it neither
        #: spends the mapping cap nor is stopped by it.
        self.reconnect_commands = 0
        self.reconnect_limit: int | None = None
        self.action_limit = FIGHT_COMMANDS if self.fight is not None else _action_budget(route) + (
            _persist_budget(route, self.persist["letter"]) if self.persist else 0)
        #: Set while the persist leg's own keys are pressed, so they count against the action budget.
        self.persist_keys = False
        #: RETURN presses on continue pages in the camp LOAD under way; `PERSIST_CONTINUE_PAGES` caps it.
        self.continue_presses = 0
        self.discovery = getattr(args, "discover", None) in (*LEAVE_MODES, *OPENING_MODES)
        self.discovery_snapshot = False
        self.encounters = None
        self.encounters_on = False
        self.booted = False
        #: Whether the game was started a second time after the disconnect grabs.
        self.restarted = False
        self.restart_stop_error: str | None = None
        #: The floppy images and WinUAE settings `_up` started the game with, for a restart.
        self.launch: tuple[tuple[str, ...], tuple[str, ...]] | None = None
        #: The pipe name Wish was pinned to when the game started; a build that follows the name needs a restart to reuse it.
        self.pipe: str | None = None
        #: `every` or `one`: how many lanes `up` claimed; `one` means Wish follows the lane's run receipt.
        self.lanes: str | None = None
        self.down_done = False
        self.pipe_released = False
        self.wish_closed = False
        #: Whether Wish has been seen attached to the game at a checkpoint.
        self.connection_checked = False
        #: The wall time by which the last queued key has landed even on slow emulation;
        #: None when no queued key can still land. WinUAE cannot take one back.
        self.keys_pending_until: float | None = None
        #: The party's square and facing after the Automapper walk's last key.
        self.walk_fix: dict[str, Any] | None = None
        self.remotes: dict[str, str] = {}
        self.checkpoints: dict[str, dict[str, Any]] = {}
        self.area_by_geo: dict[str, set[int]] | None = None
        self.party_nodes: list[tuple[int, int]] = []
        # Only a route with a walk-out phase has a walk-out row to prove.
        rows = RECONNECT_ROWS if self.leg == "reconnect" else tuple(
            name for name in MAPPING_ROWS if name != "walkout"
            or any(phase.name == "walkout" for phase in route.phases))
        if self.persist:
            from tools.amiga import maproute  # noqa: PLC0415

            rows = ("title", *maproute.LEG_PREFIX[route.title])
        if self.fight is not None:
            rows = FIGHT_ROWS
        self.summary: dict[str, Any] = {**info,
            "mapping": {name: row() for name in rows},
            "actions": ({} if self.leg in ("reconnect", "fight")
                        else {action.kind: row() for action in route.actions}),
            "original_slot_reload": row(),
            "checkpoints": self.checkpoints, "completed_sequence": [],
            "failure": None, "cleanup": {},
            #: Log reads that failed, so a run where nobody looked at Wish's log shows it.
            "wish_log_unread": 0}
        if self.persist:
            self.summary["persistence"] = row()
        if self.quickfight_control:
            self.summary["quickfight_control"] = row(expected=(
                "the game keeps the in-memory quickfight 1 at the camp readback, in the persist "
                "slot on the fetched disk, and after the reload"))
        if self.fight is not None:
            self.summary["fight"] = {"modes": [], "interventions": [], "walk": None,
                                     "found": {}, "outcome": None, "after": None}
            self.summary["fight_greyed"] = row()
            self.summary["fight_no_write"] = row()
            for flag, names in WATCH_ROWS.items():
                if getattr(args, flag, False):
                    for name in names:
                        self.summary[name] = row()
            if getattr(args, "watch_dip", False):
                self.summary["watch_dip"]["expected"] = (
                    "evidence only, not a pass condition: no read shows that a poll landed "
                    "inside the fight start's mode dip")

    def _set_deadlines(self) -> None:
        """Start the route clock now; `_up` starts it again once a lane wait has ended."""
        self.started = self.clock()
        self.reconnect_end = self.started + self.args.deadline - CLEANUP_SECONDS
        self.route_end = self.reconnect_end
        self.total_end = self.started + self.args.deadline

    def log(self, event: str, **data: Any) -> None:
        record = {"elapsed": round(self.clock() - self.started, 3),
                  "event": event, **data}
        with self.events.open("a") as stream:
            stream.write(json.dumps(record, default=str) + "\n")

    def left(self, limit: float) -> float:
        remaining = min(limit, self.route_end - self.clock())
        if remaining <= 0:
            raise AcceptanceStop("the bounded route time is spent")
        return remaining

    def _count(self, action: bool = False) -> None:
        if self.reconnect_limit is not None:
            if self.reconnect_commands >= self.reconnect_limit:
                raise AcceptanceStop(f"the {self.reconnect_limit}-command reconnect cap is reached")
            self.reconnect_commands += 1
            return
        name = "action_commands" if action else "mapping_commands"
        cap = (self.action_limit if action
               else CAMP_LOAD_MAPPING_COMMANDS if getattr(self.args, "discover", None) == "ssb-camp-load"
               else MAX_MAPPING_COMMANDS if getattr(self.args, "discover", None)
               else ORDINARY_MAPPING_COMMANDS.get(self.route.title, MAX_MAPPING_COMMANDS))
        if getattr(self, name) >= cap:
            raise AcceptanceStop(f"the {cap}-command {'action' if action else 'mapping'} cap is reached")
        setattr(self, name, getattr(self, name) + 1)

    def _game_section(self) -> None:
        if self.pipe_released:
            return
        if self.wish_closed:
            self.pipe_released = True
            return
        winwish.show_tab(self.guest, self.args.holder, "Character Editor")
        self.pipe_released = True
        self.log("pipe_released")

    def _free_pipe(self) -> str | None:
        """Leave the pipe to the driver for cleanup: the editor tab, or Wish closed when that tab cannot be shown.

        Returns None when the tab was shown, why Wish was closed when it was, or why closing it failed
        (the pipe is released and Wish is left open).
        """
        try:
            self._game_section()
            return None
        except winwish.WinwishError as exc:
            # Suppression is switched off afterwards whether or not Wish could be closed.
            self.pipe_released = True
            try:
                winwish.stop_wish(self.guest, self.args.holder)
            except Exception as stop:  # noqa: BLE001
                self.log("pipe_released", closed_wish=False, stop_failed=str(stop))
                return f"the editor tab could not be shown ({exc}), and closing Wish failed ({stop})"
            self.wish_closed = True
            self.log("pipe_released", closed_wish=str(exc))
            return f"the editor tab could not be shown ({exc}), so Wish was closed to free the pipe"

    def _encounters_off(self, failures: list[str]) -> None:
        """Free the pipe and switch encounter suppression off; each step's failure is recorded and the next still runs."""
        try:
            closed = self._free_pipe()
            if closed:
                failures.append(f"encounters: {closed}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"encounters: {exc}")
        try:
            self._switch(False)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"encounters: {exc}")

    def _map_section(self) -> None:
        if not self.pipe_released:
            return
        if self.wish_closed:
            raise AcceptanceStop("Wish is closed; start it before changing tabs")
        # Close the temporary debugger connection before Wish reacquires the pipe.
        self.game._pipe = None
        winwish.show_tab(self.guest, self.args.holder, "Automapper")
        self.pipe_released = False
        self.log("map_tab")

    def _capture(self, state: str, *, check: bool = True) -> dict[str, Any]:
        """Grab one frame and cut it to the Amiga screen.

        For the title's AmigaDOS screens (`HIRES_SCREENS`: Pool's `cli`, Curse's `reboot`), a
        frame of any size we know that is not an exact capture gets a plain cut instead, with the
        doubled-pixel check dropped; the guard's sha256 still decides whether it is that screen.
        """
        number = sum(1 for _ in self.out.glob("game-*.raw.png"))
        raw = self.out / f"game-{number:03d}.raw.png"
        crop = self.out / f"game-{number:03d}.png"
        exact = self.game.grab(state, raw, crop, self.left(30))
        evidence = {"raw": str(raw), "crop": str(crop) if exact else None,
                    "shot_source": self.game.last_shot}
        hires = HIRES_SCREENS.get(self.route.title, frozenset())
        if not exact and raw.is_file() and hires.intersection(state.split("/")) and _plain_cut(raw, crop):
            evidence.update(crop=str(crop), hires=True)
            exact = True
        self.log("game_frame", state=state, **evidence)
        if not exact:
            if check:
                raise AcceptanceStop(f"{state}: no exact Amiga crop; kept {raw}")
            return evidence
        if check and not self.guards(state, crop):
            raise AcceptanceStop(f"{state} screen was not recognized; kept {raw}")
        return evidence

    def _await(self, state: str, *, limit: float = 90,
               interstitials: tuple = ()) -> dict[str, Any]:
        end = self.clock() + self.left(limit)
        last = None
        timed_out: ShotTimedOut | None = None
        counts = [0] * len(interstitials)
        while self.clock() < end:
            try:
                last = self._capture(state, check=False)
            except ShotTimedOut as exc:
                # A slow round trip sends no key; ask again while this wait's own time holds.
                timed_out = exc
                self.summary.setdefault("shot_timeouts", []).append(
                    {"state": state, "error": str(exc)})
                self.log("shot_retry", state=state, error=str(exc))
                # A grab that fails at once must not spin: at most one a second.
                self.sleep(min(1.0, max(0, end - self.clock())))
                continue
            timed_out = None
            if last["crop"] is not None:
                crop = pathlib.Path(last["crop"])
                if self.guards(state, crop):
                    return last
                for at, (name, action, waiting_for, row_limit) in enumerate(interstitials):
                    if (action[0] in ("keys", "wheel") and counts[at] < row_limit
                            and (waiting_for is None or state in waiting_for)
                            and self.guards(name, crop)):
                        counts[at] += 1
                        if action[0] == "wheel":
                            self._answer_wheel(name)
                        else:
                            self._press_interstitial(name, action[1])
                        # The limit measures waiting for the screen, not acting on a page.
                        end = self.clock() + self.left(limit)
                        break
            self.sleep(min(1.0, max(0, end - self.clock())))
        if timed_out is not None:
            raise ShotTimedOut(f"{state} screen was not recognized before its deadline; "
                               f"last {last}; the last shot timed out: {timed_out}") from timed_out
        raise AcceptanceStop(f"{state} screen was not recognized before its deadline; last {last}")

    def _await_first(self, states: tuple[str, ...], *, limit: float
                     ) -> tuple[str | None, dict[str, Any] | None]:
        """The first of `states` a fresh frame matches, with that frame.

        No key is pressed here. When none matches within `limit`, give None and the last
        exact frame (None if no grab was exact), so the caller can stop on it."""
        label = "/".join(states)
        end = self.clock() + self.left(limit)
        last = None
        while self.clock() < end:
            try:
                frame = self._capture(label, check=False)
            except ShotTimedOut as exc:
                self.summary.setdefault("shot_timeouts", []).append(
                    {"state": label, "error": str(exc)})
                self.log("shot_retry", state=label, error=str(exc))
                self.sleep(min(1.0, max(0, end - self.clock())))
                continue
            if frame["crop"] is not None:
                last = frame
                crop = pathlib.Path(frame["crop"])
                for state in states:
                    if self.guards(state, crop):
                        return state, frame
            self.sleep(min(1.0, max(0, end - self.clock())))
        return None, last

    def _camp_reload(self) -> dict[str, Any]:
        """Camp L, Y on the guarded question, the slot on the guarded picker, then the reload.

        An unmeasured screen ends the run on its frame with a fix and Wish pair, and no
        further key."""
        from tools.amiga import maproute  # noqa: PLC0415

        discovery = self.summary["discovery"]
        discovery["status"] = "awaiting image review"

        def unmeasured(name: str, frame: dict[str, Any] | None, reason: str) -> dict[str, Any]:
            if frame is None:
                raise AcceptanceStop(f"{reason}; no exact crop was taken")
            self._checkpoint(name, None, frame)
            discovery["reason"] = reason
            return self.summary

        for step in maproute._ssb_camp_load().steps:
            self._press(step.key)
            state, frame = self._await_first((step.state,), limit=CAMP_LOAD_WAIT)
            if state is None:
                return unmeasured(f"ssb_camp_after_{step.key.lower()}", frame,
                                  f"The screen after camp {step.key} is not measured")
        self.summary["completed_sequence"].append("camp_load")
        reload = maproute._ssb_camp_reload()
        self._press(self.route.loaded_slot)
        state, frame = self._await_first(("loaded_menu", "world"), limit=CAMP_SLOT_WAIT)
        if state is None:
            return unmeasured("ssb_camp_after_slot", frame,
                              f"The screen after slot {self.route.loaded_slot} is not measured")
        if state == "world":
            final = reload.steps[-1]
            self._checkpoint(final.checkpoint, final.expected, frame)
            self.summary["completed_sequence"].append(reload.name)
        else:
            self.run_phase(reload)
        self.summary["mapping"]["reload"] = row("awaiting image review")
        discovery["reason"] = "The camp reload pair awaits image review"
        return self.summary

    def _press_interstitial(self, screen: str, key: str) -> None:
        if self.encounters_on:
            # The switch's own key path, so suppression is applied to this key as to a route key.
            result = self.encounters.keys([key])
            if result.get("stopped") or result.get("error") or result.get("pressed") != [key]:
                raise AcceptanceStop(f"encounter-controlled key {key} on {screen}: {result}")
        else:
            self.game.press(self.args.holder, key, self.left(30))
        self.summary["interstitial_keys"] = self.summary.get("interstitial_keys", 0) + 1
        self.log("interstitial", screen=screen, key=key)

    def _answer_wheel(self, screen: str) -> None:
        """The code-wheel question, read and answered by `amigacursewheel.py`, which records nothing."""
        from tools.amiga import amigacursewheel  # noqa: PLC0415

        if self.encounters_on:
            raise AcceptanceStop(f"{screen} appeared while encounters were controlled")
        try:
            answered = amigacursewheel.answer(self.args.holder, WHEEL_SETTLE,
                                              guard=lambda: self._still_on(screen))
        except (SystemExit, amigacursewheel.ScreenChanged) as exc:
            raise AcceptanceStop(f"{screen}: {exc}") from exc
        if not answered:
            raise AcceptanceStop(f"{screen} was recognized but no wheel challenge was read")
        self.summary["interstitial_keys"] = self.summary.get("interstitial_keys", 0) + 2
        self.log("interstitial", screen=screen, key="wheel")

    def _await_title(self) -> dict[str, Any]:
        """The title screen, answering the title's own boot pages and code wheel on the way."""
        return self._await("title", limit=self.route.amiga_title.title_limit,
                           interstitials=_title_pages(self.route, self.guards))

    def _phase_pages(self, phase: Any) -> tuple:
        names = set(getattr(phase, "pages", ()) or ())
        return tuple(row for row in self.route.amiga_title.interstitials if row[0] in names)

    def _still_on(self, screen: str) -> bool:
        """Whether a fresh frame shows `screen`; no key is pressed."""
        return self._await_first((screen,), limit=KEY_GUARD_WAIT)[0] is not None

    def _type(self, step: Any, *, action: bool) -> None:
        """A `type` step's keys in order, each counted and each sent only once a fresh
        frame, grabbed `WHEEL_SETTLE` after the previous key, shows the step's `screen`.

        Where the screen echoes the typed line, `screen` must name a guard whose boxes leave
        that line out, or the frame change stops the step at key 2."""
        for number, key in enumerate(step.keys, 1):
            if number > 1:
                # A frame grabbed at once can predate the previous key's effect.
                self.sleep(self.left(WHEEL_SETTLE))
            if not self._still_on(step.screen):
                raise AcceptanceStop(f"{step.screen} was not recognized before typed key "
                                     f"{number} of {len(step.keys)}")
            self._press(key, action=action)

    def _relaunch_ready(self, step: Any) -> None:
        """A program restart needs encounter suppression off, in memory and in its saved state."""
        if self.encounters_on:
            raise AcceptanceStop(f"{step.state}: the program restarts with encounter suppression on")
        if self.encounters is not None:
            saved = self.encounters.state.load()
            if saved["on"] or saved["rows"]:
                raise AcceptanceStop(f"{step.state}: the program restarts with encounter "
                                     f"suppression outstanding: {saved}")

    def _relaunched(self) -> None:
        """Forget what pointed into the old program: the batched party nodes and the
        encounter switch's target, which the next switch locates again."""
        self.party_nodes = []
        self.encounters = None
        self.log("relaunched")

    def _press(self, key: str, *, action: bool = False) -> None:
        self._count(action)
        if self.encounters_on:
            result = self.encounters.keys([key])
            if result.get("stopped") or result.get("error") or result.get("pressed") != [key]:
                raise AcceptanceStop(f"encounter-controlled key {key}: {result}")
        else:
            self.game.press(self.args.holder, key, self.left(30))
        self.log("key", key=key)

    def _switch(self, enabled: bool) -> None:
        if self.encounters is None:
            from automap import amiga  # noqa: PLC0415

            pipe = amiga.WinuaePipe(holder=self.args.holder)
            title = self.route.game_key
            self.encounters = noencounters.WinuaeEncounters(
                title, amiga.AmigaTarget(pipe, amiga.MACHINES[title]),
                state=noencounters.WinuaeState(noencounters.winuae_state_path(self.args.holder)),
                lane_check=lambda: pipe.drives(self.args.holder),
                press=lambda key: self.game.press(self.args.holder, key, self.left(30)))
        result = self.encounters.on() if enabled else self.encounters.off()
        if result.get("error") or result.get("stopped"):
            raise AcceptanceStop(f"encounter switch did not reach {enabled}: {result}")
        saved = self.encounters.state.load()
        if bool(saved["on"]) != enabled or (not enabled and saved["rows"]):
            raise AcceptanceStop(f"encounter switch readback did not reach {enabled}: {saved}")
        self.encounters_on = enabled
        self.log("encounters", enabled=enabled, readback=result)

    def _checkpoint(self, name: str, expected: Any, game_evidence: dict[str, Any],
                    *, reads: tuple = ()) -> None:
        timings: dict[str, float] = {}
        lap = self._lap(timings)
        engine, party_reads = self._read_engine(lap, reads=reads) if reads else self._read_engine(lap)
        if self.wish_closed:
            winwish.start_wish(self.guest, self.args.holder, reseed=False)
            self.wish_closed = False
        self._map_section()
        lap("map_tab")
        self.sleep(self.left(10))
        lap("settle")
        wish_path, controls_path = self._wish_pair(name, lap)
        self._record_checkpoint(name, expected, engine, game_evidence, wish_path, controls_path,
                                timings, party_reads)

    def _lap(self, timings: dict[str, float]) -> Any:
        mark = self.clock()

        def lap(part: str) -> None:
            nonlocal mark
            now = self.clock()
            timings[part] = round(now - mark, 3)
            mark = now
        return lap

    def _read_engine(self, lap: Any, *, reads: tuple = ()) -> tuple[dict[str, Any], dict[str, int]]:
        """The game's fix, area and party through a pipe connection the driver closes again."""
        from automap import (
            amiga,  # noqa: PLC0415
            amigaparty,  # noqa: PLC0415
        )
        from tools.amiga import amigatarget  # noqa: PLC0415

        target = amigatarget.connect_pipe(self.args.holder, amiga.MACHINES[self.route.game_key])
        lap("connect")
        row_ = amigaparty.row_for(target)
        base = getattr(target, "data_base", None)
        batch = ([(base + row_.head, 4), *self.party_nodes]
                 if self.party_nodes and row_ is not None and base is not None else [])
        reader = _BatchedParty(target, batch)
        party = amigaparty.read_party(reader)
        self.party_nodes = _party_nodes(target, party)
        party_reads = {"batched_blocks": reader.batched_blocks, "live_reads": reader.live_reads}
        lap("party")
        fix = target.fix()
        lap("fix")
        area = self._area_of(geo) if (geo := target.geo()) is not None else None
        lap("geo")
        engine = {"fix": (None if fix is None else
                          {"x": fix.x, "y": fix.y, "facing": fix.facing,
                           "outdoors": fix.outdoors, "world_map": fix.world_map,
                           "window": fix.window, "heading": fix.heading,
                           "world_node": getattr(fix, "world_node", None),
                           "world_leg": getattr(fix, "world_leg", None),
                           "area": area}),
                  "geo_sha256": (None if geo is None else hashlib.sha256(geo).hexdigest()),
                  "party": (None if party is None else [
                      {"slot": member.slot, "name": member.name,
                       "address": member.address, "raw": member.raw.hex(),
                       "items": [[node.address, node.raw.hex()] for node in member.item_nodes]}
                      for member in party])}
        if reads:
            engine["memory_reads"] = self._memory_reads(target, reads)
            lap("reads")
        target.close()
        self.game._pipe = None
        return engine, party_reads

    def _memory_reads(self, target: Any, reads: tuple) -> list[dict[str, Any]]:
        """Each read's bytes, or why it has none; a read never changes a verdict."""
        from tools.amiga.amigatarget import A4_BIAS  # noqa: PLC0415

        records = []
        for spec in reads:
            record: dict[str, Any] = {"name": spec.name, "anchor": spec.anchor,
                                      "offset": spec.offset, "length": spec.length,
                                      "hop": spec.hop}
            try:
                address = spec.offset
                if spec.anchor != "abs":
                    base = getattr(target, "data_base", None)
                    if base is None:
                        raise ValueError("the data hunk is not located")
                    address += base + (A4_BIAS if spec.anchor == "a4" else 0)
                if spec.hop is not None:
                    pointer = int.from_bytes(bytes(target.read(address, 4)), "big")
                    record.update(pointer_at=address, pointer=pointer)
                    if pointer == 0:
                        raise ValueError("the pointer is null")
                    address = pointer + spec.hop
                data = bytes(target.read(address, spec.length))
                record.update(address=address, hex=data.hex(),
                              set_bits=sum(bin(byte).count("1") for byte in data))
            except Exception as exc:  # noqa: BLE001
                record["error"] = f"{type(exc).__name__}: {exc}"
            records.append(record)
            self.log("memory_read", **record)
        return records

    def _await_connection(self, controls: list[str]) -> list[str]:
        """The controls once Wish's Party heading no longer waits for a game.

        Stops the run when the dump has no Party heading, when the wait reaches `CONNECT_WAIT`, or
        when the route time runs out first.
        """
        deadline = self.clock() + min(CONNECT_WAIT, self.route_end - self.clock())
        while True:
            seen = any(_is_party_heading(line) for line in controls)
            self.summary["party_heading_seen"] = seen
            if not seen:
                raise AcceptanceStop("the controls dump has no Party heading, so Wish's connection cannot be judged")
            if not any(WAITING_HEADING in line for line in controls):
                return controls
            if self.clock() >= deadline:
                if self.clock() >= self.route_end:
                    raise AcceptanceStop(f"the bounded route time ran out while Wish still showed '{WAITING_HEADING}'")
                raise AcceptanceStop(f"Wish still shows '{WAITING_HEADING}' {CONNECT_WAIT} s after the first checkpoint")
            self.sleep(CONNECT_POLL)
            controls = winwish.ui(self.guest, self.args.holder, "controls")

    def _wish_pair(self, name: str, lap: Any) -> tuple[pathlib.Path, pathlib.Path]:
        """Wish's shot and its controls, of whichever tab is showing."""
        wish_path = self.out / f"wish-{name}.png"
        winwish.shot(self.guest, self.args.holder, "wish", wish_path)
        lap("wish_shot")
        controls = winwish.ui(self.guest, self.args.holder, "controls")
        if not self.connection_checked:
            controls = self._await_connection(controls)
            self.connection_checked = True
        lap("controls")
        controls_path = self.out / f"controls-{name}.txt"
        controls_path.write_text("\n".join(controls) + "\n")
        return wish_path, controls_path

    def _record_checkpoint(self, name: str, expected: Any, engine: dict[str, Any],
                           game_evidence: dict[str, Any], wish_path: pathlib.Path,
                           controls_path: pathlib.Path, timings: dict[str, float],
                           party_reads: dict[str, int], **extra: Any) -> None:
        verdict = self._compare_checkpoint(name, expected, engine)
        self.checkpoints[name] = {"expected": asdict(expected) if expected else None,
                                  "observed": engine, "game": game_evidence,
                                  "comparison": verdict,
                                  "wish": str(wish_path), "wish_sidecar": str(wish_path) + ".json",
                                  "controls": str(controls_path),
                                  "elapsed": round(self.clock() - self.started, 3),
                                  "pair_atomic": False,
                                  "timings": timings, "party_reads": party_reads, **extra}
        self.log("checkpoint", name=name, game=game_evidence, wish=str(wish_path),
                 timings=timings, party_reads=party_reads, **extra)
        self._game_section()
        if verdict["status"] != "awaiting image review":
            raise AcceptanceStop(f"{name}: {verdict['reason'] or verdict['status']}")

    def _area_of(self, resident: bytes) -> int | None:
        """Identify an unchanged resident map from the prepared disks only."""
        from automap import amiga, maps  # noqa: PLC0415
        from goldbox.amiga_adf import AmigaDisk  # noqa: PLC0415

        if self.area_by_geo is None:
            self.area_by_geo = {}
            for medium in self.route.media:
                found = amiga.load_maps(medium.path)
                if not found and self.route.title == "pool":
                    found = maps._dax_maps(AmigaDisk.open(medium.path))
                for key, area in found.items():
                    name = hashlib.sha256(area.to_bytes()).hexdigest()
                    self.area_by_geo.setdefault(name, set()).add(int(key[3:], 16))
        ids = self.area_by_geo.get(hashlib.sha256(resident).hexdigest(), set())
        return next(iter(ids)) if len(ids) == 1 else None

    def _compare_checkpoint(self, name: str, expected: Any,
                            engine: dict[str, Any]) -> dict[str, Any]:
        if expected is None:
            if name in ("ssb_leave_terminal", "ssb_opening_after_first",
                        "ssb_opening_second", "ssb_opening_after_second",
                        "ssb_opening_third", "ssb_opening_after_third") and engine.get("fix") is None:
                return row("unproven", observed=engine, reason="the game fix was not readable")
            return row("awaiting image review", observed=engine)
        fix = engine.get("fix")
        if fix is None:
            return row("unproven", expected=asdict(expected), observed=engine,
                       reason="the game fix was not readable")
        missing = []
        for key, want in (expected.window or {}).items():
            if key not in fix:
                missing.append(f"window {key}")
            elif fix[key] != want:
                return row("failed", expected=asdict(expected), observed=engine,
                           reason=f"window {key} reads {fix[key]}, expected {want}")
        for key, want in (expected.engine or {}).items():
            # On Pool's travel grid, the game prints global coordinates while
            # target.fix() deliberately returns the local map-window square.
            if fix.get("outdoors") and key in ("x", "y"):
                continue
            if fix.get("outdoors") and key == "facing":
                # Travel headings use eight points; cardinal facings use four.
                heading = fix.get("heading")
                if heading is None:
                    missing.append("engine heading")
                elif heading != want * 2:
                    return row("failed", expected=asdict(expected), observed=engine,
                               reason=f"engine heading reads {heading}, expected {want * 2}")
                continue
            if key not in fix:
                missing.append(key)
            elif fix[key] != want:
                return row("failed", expected=asdict(expected), observed=engine,
                           reason=f"engine {key} reads {fix[key]}, expected {want}")
        if expected.compare_to:
            previous = self.checkpoints.get(expected.compare_to)
            if previous is None:
                return row("unproven", expected=asdict(expected), observed=engine,
                           reason=f"comparison checkpoint {expected.compare_to} is missing")
            old = previous["observed"].get("fix")
            if old is None:
                missing.append("previous fix")
            else:
                same_square = (fix["x"], fix["y"]) == (old["x"], old["y"])
                relation = expected.relation
                if relation == "stationary" and not same_square:
                    return row("failed", expected=asdict(expected), observed=engine,
                               reason=f"stationary control moved from {old} to {fix}")
                if relation == "moved" and same_square:
                    return row("failed", expected=asdict(expected), observed=engine,
                               reason=f"movement control stayed at {fix}")
                if relation == "equal" and fix != old:
                    return row("failed", expected=asdict(expected), observed=engine,
                               reason=f"reload changed established fix from {old} to {fix}")
                if relation == "view_changed":
                    view = (bool(fix.get("outdoors")), bool(fix.get("world_map")))
                    if view == (bool(old.get("outdoors")), bool(old.get("world_map"))):
                        return row("failed", expected=asdict(expected), observed=engine,
                                   reason=f"the view stayed (outdoors, world map) = {view}")
                if relation == "area_changed":
                    old_geo = previous["observed"].get("geo_sha256")
                    if old_geo is None or engine["geo_sha256"] is None:
                        missing.append("resident area")
                    elif old_geo == engine["geo_sha256"]:
                        return row("failed", expected=asdict(expected), observed=engine,
                                   reason="the resident map did not change")
        status = "unproven" if missing else "awaiting image review"
        return row(status, expected=asdict(expected), observed=engine,
                   reason=("unreadable expected fields: " + ", ".join(missing)) if missing else None)

    def flag_controls(self) -> None:
        """Pool's and Silver Blades' flag modes use the same boot and retain Wish settings.

        Map-only greys the five flagged actions and Level up; Fast Travel has no flag
        of its own and must read as it did with the flags on.
        """
        if self.route.title not in ("pool", "ssb"):
            return
        flagged_actions = ("Heal party", "Save spells", "Restore spells",
                           "Identify", "Quickfight off")
        controls_wanted = (*flagged_actions, "Fast Travel")
        flags_on_travel = None
        self._map_section()
        for name, features, delay in (("on", True, 10),
                                      ("map_only", False, 10),
                                      ("restored", True, 10)):
            if name != "on":
                winwish.restart_wish(self.guest, self.args.holder,
                                     features=features, reseed=False)
            self.sleep(self.left(delay))
            listing = winwish.ui(self.guest, self.args.holder, "controls")
            listed = self.out / f"flags-{name}.txt"
            listed.write_text("\n".join(listing) + "\n")
            picture = self.out / f"flags-{name}.png"
            winwish.shot(self.guest, self.args.holder, "wish", picture)
            controls = {}
            for line in listing:
                parts = line.split("|")
                if len(parts) >= 4 and parts[1] in controls_wanted:
                    controls.setdefault(parts[1], []).append(parts[3])
            missing = [key for key in controls_wanted if len(controls.get(key, ())) != 1]
            if missing:
                raise AcceptanceStop(f"{name} flags: absent or ambiguous controls {missing}; kept {listed}")
            if name == "on":
                flags_on_travel = controls["Fast Travel"][0]
            if name == "map_only":
                if any(controls[key][0] != "enabled=False" for key in flagged_actions):
                    raise AcceptanceStop(f"map-only flag left an action enabled; kept {listed}")
                if controls["Fast Travel"][0] != flags_on_travel:
                    raise AcceptanceStop(
                        f"map-only flag changed Fast Travel from the flags-on state; kept {listed}")
                if any("card_" in line and "_level_up" in line and "enabled=True" in line
                       for line in listing):
                    raise AcceptanceStop(f"map-only flag left Level up enabled; kept {listed}")
            self.summary.setdefault("flags", {})[name] = row(
                "awaiting image review", observed=controls,
                evidence=[str(listed), str(picture), str(picture) + ".json"])
            self.log("flags", mode=name, controls=controls, picture=str(picture))
        self._game_section()

    def _answer_journal(self) -> None:
        from tools.amiga import route_silver_blades  # noqa: PLC0415

        if self.route.title != "ssb":
            raise AcceptanceStop("journal answer is only defined for Silver Blades")
        disk = next(m.path for m in self.route.media if m.key == self.route.mounted[0])
        if self.discovery:
            self.summary["challenge_key_count"] = None
            self.summary["challenge_key_count_verified"] = False
            self.log("journal_answer", challenge_key_count=None, verified=False)
        code, answer = route_silver_blades.run_journal_answer(
            sys.executable, self.args.holder, disk, self.left(60))
        if code:
            raise AcceptanceStop(f"journal was not answered: {answer}")

    def _counts_as_action(self, action_context: Any, namespace: str | None) -> bool:
        return action_context is not None or namespace == "original_slot_reload" or self.persist_keys

    def run_phase(self, phase: Any, action_context: Any = None,
                  namespace: str | None = None) -> None:
        if not phase.ready:
            raise AcceptanceStop(f"{phase.name} is unready: {phase.reason}")
        self._game_section()
        last_frame = self._await(phase.initial_state, limit=self.route.amiga_title.wait_limits.get(
            phase.initial_state, self.route.amiga_title.title_limit))
        pages = self._phase_pages(phase)
        map_walk = getattr(self.args, "walk_tab", "editor") == "map" and phase.name == "walk"
        if map_walk:
            self.walk_fix = None
        before_state = phase.initial_state
        walk_keys = 0
        for step in phase.steps:
            kind = step.kind
            if map_walk and kind in ("turn", "move"):
                walk_keys += 1
                last_frame = self._map_walk_key(step, before_state, walk_keys)
                before_state = step.state
                continue
            relaunch = getattr(step, "relaunch", False)
            if relaunch:
                self._relaunch_ready(step)
            if kind == "type":
                self._type(step, action=self._counts_as_action(action_context, namespace))
            elif kind in ("key", "turn", "move"):
                self._press(step.key, action=self._counts_as_action(action_context, namespace))
            elif kind == "insert":
                medium = next(m for m in self.route.media if m.key == step.media)
                self.game.insert(self.args.holder, step.drive, self.remotes[step.media],
                                 self.left(60), medium.sha256)
                self._press(step.key, action=self._counts_as_action(action_context, namespace))
            elif kind == "reset":
                self.game.reset(self.args.holder, self.left(60))
                self.log("reset")
            elif kind == "snapshot":
                if self.discovery or self.encounters_on:
                    self._switch(False)
                self.game.snapshot(step.snapshot, self.args.holder)
                if self.discovery and step.snapshot == DISCOVERY_SNAPSHOT:
                    self.discovery_snapshot = True
            elif kind == "restore":
                if self.encounters_on:
                    self._switch(False)
                self.game.restore(step.snapshot, self.args.holder)
            elif kind == "encounters":
                self._switch(step.encounters)
            elif kind == "answer":
                self._answer_journal()
            elif kind == "select":
                if action_context is None:
                    raise AcceptanceStop("member selection outside an action")
                from automap import amiga  # noqa: PLC0415
                from tools.amiga import amigatarget  # noqa: PLC0415

                layout = amiga.MACHINES[self.route.game_key]
                target = amigatarget.connect_pipe(self.args.holder, layout)
                selected = amigatarget.select(
                    target, layout, action_context["member"],
                    press=lambda key: self._press(key, action=True),
                    wait=lambda: self.sleep(self.left(1)))
                target.close()
                if selected.get("error"):
                    raise AcceptanceStop(f"member selection: {selected['error']}")
                action_context.setdefault("selections", []).append(selected)
            elif kind != "observe":
                raise AcceptanceStop(f"unknown route step kind {kind}")
            if relaunch:
                # The old program's addresses are stale from the key on, whatever the wait finds.
                self._relaunched()
            frame = self._await(step.state, limit=self.route.amiga_title.wait_limits.get(
                step.state, 90), interstitials=pages)
            last_frame = frame
            before_state = step.state
            if step.checkpoint:
                expected = step.expected
                if namespace and expected and expected.compare_to:
                    from dataclasses import replace  # noqa: PLC0415

                    local = {s.checkpoint for s in phase.steps if s.checkpoint}
                    if action_context is not None:
                        local.update(action_context.get("visit_checkpoints", ()))
                    if expected.compare_to in local:
                        expected = replace(expected, compare_to=f"{namespace}.{expected.compare_to}")
                reads = tuple(getattr(step, "reads", ()) or ())
                self._checkpoint(f"{namespace}.{step.checkpoint}" if namespace else step.checkpoint,
                                 expected, frame, **({"reads": reads} if reads else {}))
                if action_context is not None:
                    action_context.setdefault("visit_checkpoints", set()).add(step.checkpoint)
        if action_context is not None and namespace:
            self._checkpoint(f"{namespace}.{phase.name}_end", None, last_frame)
        self.summary["completed_sequence"].append(
            f"{namespace}.{phase.name}" if namespace else phase.name)

    def _scheduled_key(self, key: str, *, show_map: bool, index: int | None = None) -> dict[str, Any]:
        """Queue `key` in the emulator, optionally with the Automapper showing before it can
        land, and wait until it has landed and Wish has polled for `WALK_SETTLE`.

        With `show_map` false the tab is left as it is, so a key can be sent with the Character
        Editor showing on the same lead and wait as the Automapper one. Returns the schedule."""
        before = self.clock()
        earliest = before + WALK_LEAD_FRAMES / AMIGA_FRAMES_PER_SECOND
        # The key may be queued in the emulator before the call raises, so cleanup waits from here.
        self.keys_pending_until = _latest_landing(before, MIN_EMULATION_SPEED)
        reply = self.game.schedule_key(self.args.holder, key, WALK_LEAD_FRAMES, self.left(60))
        sent = self.clock()
        latest = _latest_landing(sent, MIN_EMULATION_SPEED)
        self.keys_pending_until = latest
        self.key_sent = sent
        self.log("walk_key_queued", key=key, index=index, lead_frames=WALK_LEAD_FRAMES,
                 reply=reply)
        shown = None
        if show_map:
            self._map_section()
            shown = self.clock()
        schedule = {"key": key, "index": index, "lead_frames": WALK_LEAD_FRAMES,
                    "min_emulation_speed": MIN_EMULATION_SPEED,
                    "tab_shown_s": None if shown is None else round(shown - before, 3),
                    "key_earliest_s": round(earliest - before, 3),
                    "key_latest_s": round(latest - before, 3)}
        self.log("map_walk", **schedule)
        if shown is not None and shown > earliest - WALK_TAB_MARGIN:
            raise AcceptanceStop(f"the Automapper showed {shown - before:.1f} s after walk key "
                                 f"{key} was queued, within {WALK_TAB_MARGIN:.0f} s of its "
                                 f"earliest landing at {earliest - before:.0f} s")
        self.sleep(self.left(max(1.0, latest + WALK_SETTLE - self.clock())))
        if self.clock() < latest + WALK_SETTLE:
            raise AcceptanceStop(f"the route time ran out before walk key {key} could have "
                                 "landed and settled; no Wish shot was taken")
        self.keys_pending_until = None
        schedule["shot_s"] = round(self.clock() - before, 3)
        return schedule

    def _map_walk_key(self, step: Any, before_state: str, index: int) -> dict[str, Any]:
        """One walk key with the Automapper showing from before it lands until Wish's shot
        after it; returns the game frame taken after the shot.

        WinUAE's pipe takes one client, and Wish holds it while the Automapper polls, so the
        key is queued in the emulator, with the screen guarded and the encounter switch
        applied just before, and lands on its own frame. The Character Editor then frees the
        pipe for the guard after, and a read that the key moved or turned the party."""
        limits = self.route.amiga_title.wait_limits
        self._game_section()
        self._await(before_state, limit=limits.get(before_state, 90))
        if self.walk_fix is None:
            self.walk_fix = self._read_fix()
        fix_before = self.walk_fix
        self._count()
        if self.encounters_on:
            collected: list[str] = []
            press = self.encounters.press
            self.encounters.press = collected.append
            try:
                result = self.encounters.keys([step.key])
            finally:
                self.encounters.press = press
            if (result.get("stopped") or result.get("error")
                    or result.get("pressed") != [step.key] or collected != [step.key]):
                raise AcceptanceStop(f"encounter switch before walk key {step.key}: {result}")
            self.log("encounters_applied", before=step.key, readback=result)
        schedule = self._scheduled_key(step.key, show_map=True, index=index)
        sent = self.key_sent
        name = step.checkpoint or f"walk_key_{index:02d}"
        timings: dict[str, float] = {}
        lap = self._lap(timings)
        wish_path, controls_path = self._wish_pair(name, lap)
        self._game_section()
        lap("editor_tab")
        frame = self._await(step.state, limit=limits.get(step.state, 90))
        lap("game")
        if step.checkpoint:
            engine, party_reads = self._read_engine(lap)
            fix = engine["fix"]
            fix_after = None if fix is None else {k: fix[k] for k in ("x", "y", "facing")}
        else:
            fix_after = self._read_fix()
            lap("fix")
        self.walk_fix = fix_after
        problem = _key_effect_problem(step.kind, fix_before, fix_after)
        if (fix_before is not None and fix_after is not None
                and (fix_after["x"], fix_after["y"]) == (fix_before["x"], fix_before["y"])
                and (step.kind == "move" or fix_after["facing"] == fix_before["facing"])):
            # The key may only be late; cleanup waits for the slowest emulation it could run at.
            self.keys_pending_until = _latest_landing(sent, SLOW_EMULATION_SPEED)
        self.summary.setdefault("map_walk_keys", []).append(
            {"key": step.key, "kind": step.kind, "index": index, "schedule": schedule,
             "wish": str(wish_path), "controls": str(controls_path), "game": frame,
             "fix_before": fix_before, "fix_after": fix_after, "problem": problem,
             "timings": timings})
        self.log("map_walk_key", key=step.key, index=index, wish=str(wish_path), game=frame,
                 fix_before=fix_before, fix_after=fix_after, problem=problem, timings=timings)
        if step.checkpoint:
            self._record_checkpoint(step.checkpoint, step.expected, engine, frame, wish_path,
                                    controls_path, timings, party_reads, walk_tab="map",
                                    schedule=schedule)
        if problem is not None:
            raise AcceptanceStop(f"walk key {index} ({step.key}): {problem}")
        return frame

    def _read_fix(self) -> dict[str, Any] | None:
        """The party's square and facing, through a pipe connection the driver closes again."""
        from automap import amiga  # noqa: PLC0415
        from tools.amiga import amigatarget  # noqa: PLC0415

        target = amigatarget.connect_pipe(self.args.holder, amiga.MACHINES[self.route.game_key])
        try:
            fix = target.fix()
        finally:
            target.close()
            self.game._pipe = None
        return None if fix is None else {"x": fix.x, "y": fix.y, "facing": fix.facing}

    def _await_queued_keys(self) -> None:
        """Wait out a queued key that may still land, so cleanup never races it."""
        until, self.keys_pending_until = self.keys_pending_until, None
        if until is None:
            return
        wait = until - self.clock()
        if wait > 0:
            self.log("scheduled_key_wait", seconds=round(wait, 3))
            self.sleep(wait)

    def _fresh_party(self):
        from automap import amiga, amigaparty  # noqa: PLC0415
        from tools.amiga import amigatarget  # noqa: PLC0415

        target = amigatarget.connect_pipe(self.args.holder, amiga.MACHINES[self.route.game_key])
        party = amigaparty.read_party(target)
        if not party:
            target.close()
            raise AcceptanceStop("no complete current party is readable")
        return target, party

    @staticmethod
    def _member_record(member: Any) -> dict[str, Any]:
        return {"slot": member.slot, "name": member.name, "address": member.address,
                "raw": member.raw.hex(), "items": [
                    [node.address, node.raw.hex()] for node in member.item_nodes]}

    @staticmethod
    def _levelup_offsets(game_key: str) -> _LevelupOffsets:
        """The title's experience and hit-point offsets and its experience threshold."""
        from automap import amigalevelup as lv  # noqa: PLC0415

        table = {
            lv.POOL_OF_RADIANCE: _LevelupOffsets(
                lv._POR_EXPERIENCE, lv._POR_HP_ROLLED, lv._POR_HP_MAX, lv._POR_HP_CURRENT,
                lv.por_threshold),
            lv.CURSE: _LevelupOffsets(
                lv._CU_EXPERIENCE, lv._CU_HP_ROLLED, lv._CU_HP_MAX, lv._CU_HP_CURRENT,
                lv.curse_threshold),
            lv.SILVER_BLADES: _LevelupOffsets(
                lv._SB_EXPERIENCE, lv._SB_HP_ROLLED, lv._SB_HP_MAX, lv._SB_HP_CURRENT,
                lv.ssb_threshold),
            lv.POOLS_OF_DARKNESS: _LevelupOffsets(
                lv._POD_EXPERIENCE, lv._POD_HP_ROLLED, lv._POD_HP_MAX, lv._POD_HP_CURRENT,
                lv.pod_threshold),
        }
        if game_key not in table:
            raise AcceptanceStop(f"no Level up offsets are known for {game_key}")
        return table[game_key]

    def _levelup_pressable(self, member: Any) -> bool:
        """Whether one press can be verified: it asks for no spell and adds no effect node.

        Pool and Curse add int((die + bonus) / classes) to the maximum, which the verifier
        cannot split back into a roll and a bonus, so only a one-class member qualifies there.
        """
        import random  # noqa: PLC0415

        from automap import amigalevelup  # noqa: PLC0415

        key = self.route.game_key
        if key in (amigalevelup.POOL_OF_RADIANCE, amigalevelup.CURSE):
            if sum(1 for level in amigalevelup.summary(member.raw, key)["levels"] if level) != 1:
                return False
        try:
            plan = amigalevelup.plan_member(member, key, rng=random.Random(0))
        except amigalevelup.CannotLevel:
            return False
        return not plan.added_effects

    def _next_threshold(self, member: Any) -> int | None:
        """Experience that makes the one-class member's class ready, or None when it cannot."""
        from types import SimpleNamespace  # noqa: PLC0415

        from automap import amigalevelup  # noqa: PLC0415

        offsets = self._levelup_offsets(self.route.game_key)
        levels = amigalevelup.summary(member.raw, self.route.game_key)["levels"]
        held = [slot for slot, level in enumerate(levels) if level > 0]
        if len(held) != 1:
            return None
        slot = held[0]
        threshold = offsets.threshold(slot, levels[slot] + 1)
        staged = bytearray(member.raw)
        staged[offsets.experience:offsets.experience + 4] = threshold.to_bytes(4, "big", signed=True)
        if not amigalevelup.ready_classes(bytes(staged), self.route.game_key):
            return None
        after = SimpleNamespace(raw=bytes(staged), item_nodes=member.item_nodes,
                                effect_nodes=member.effect_nodes)
        return threshold if self._levelup_pressable(after) else None

    def _stageable_levelup_member(self, party: Any) -> Any:
        for member in sorted(party, key=lambda item: item.slot):
            if self._next_threshold(member) is not None:
                return member
        raise AcceptanceStop("No member is ready for Level up and none can be staged")

    def _action_input(self, action: Any) -> dict[str, Any]:
        """Stage only the plan's named input on a newly resolved member."""
        from automap import amigalevelup, amigaparty  # noqa: PLC0415

        target, party = self._fresh_party()
        before = [self._member_record(member) for member in party]
        choice = None
        try:
            for member in sorted(party, key=lambda item: item.slot):
                if action.selector == "hp" and member.hp_max >= 6 and member.hp > 0:
                    choice = member
                elif action.selector == "memorised" and any(member.memorised()):
                    choice = member
                elif action.selector == "item" and member.item_nodes:
                    choice = member
                elif action.selector == "controlled" and (member.row.control is None or
                        not member.row.control.value(member.raw)):
                    choice = member
                elif (action.selector == "levelup"
                        and amigalevelup.ready_classes(member.raw, self.route.game_key)
                        and self._levelup_pressable(member)):
                    choice = member
                if choice is not None:
                    break
            if action.selector == "levelup" and choice is None:
                choice = self._stageable_levelup_member(party)
            if choice is None:
                raise AcceptanceStop(f"no existing input for {action.selector}")
            context: dict[str, Any] = {"member": choice.name, "slot": choice.slot,
                                       "before": before}
            if action.kind == "heal":
                spot = choice.row.hp
                value = choice.hp_max - 5
                target.write(choice.address + spot.offset, value.to_bytes(spot.length, "big"))
                context["staged"] = {"hp": value}
            elif action.kind == "spells":
                index = next(i for i, value in enumerate(choice.memorised()) if value)
                context["spell_index"] = index
            elif action.kind == "identify":
                node = choice.item_nodes[0]
                spot = choice.row.hidden
                byte = node.raw[spot.offset]
                value = byte | spot.mask
                target.write(node.address + spot.offset, bytes([value]))
                context["staged"] = {"item_address": node.address,
                                      "hidden_before": byte, "hidden_staged": value}
            elif action.kind == "quickfight":
                spot = choice.row.quickfight
                if spot is None:
                    raise AcceptanceStop("this title has no quickfight spot")
                target.write(choice.address + spot.offset, bytes([1]))
                context["staged"] = {"quickfight": 1}
            elif action.kind == "levelup":
                offsets = self._levelup_offsets(self.route.game_key)
                if amigalevelup.ready_classes(choice.raw, self.route.game_key):
                    # Already eligible: nothing is staged, the record is the baseline.
                    threshold = amigalevelup.summary(choice.raw, self.route.game_key)["experience"]
                else:
                    threshold = self._next_threshold(choice)
                    target.write(choice.address + offsets.experience,
                                 threshold.to_bytes(4, "big", signed=True))
                context["staged"] = {"experience": threshold}
            staged_party = amigaparty.read_party(target)
            if not staged_party:
                raise AcceptanceStop("the staged party is not readable")
            context["baseline"] = [self._member_record(member) for member in staged_party]
            if action.kind == "levelup":
                staged_member = next(member for member in staged_party if member.slot == choice.slot)
                context["levelup_effects"] = [node.raw.hex() for node in staged_member.effect_nodes]
            self._verify_staging(action.kind, context, party)
            return context
        finally:
            target.close()

    @staticmethod
    def _party_by_slot(records: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
        slots = {record["slot"]: record for record in records}
        if len(slots) != len(records):
            raise AcceptanceStop("party has repeated slots")
        return slots

    def _verify_staging(self, kind: str, context: dict[str, Any], party: Any) -> None:
        original = self._party_by_slot(context["before"])
        staged = self._party_by_slot(context["baseline"])
        if original.keys() != staged.keys():
            raise AcceptanceStop("staging changed the party slots")
        slot = context["slot"]
        for member in party:
            old, new = original[member.slot], staged[member.slot]
            raw = bytearray.fromhex(old["raw"])
            items = [[address, data] for address, data in old["items"]]
            if member.slot == slot:
                if kind == "heal":
                    spot = member.row.hp
                    raw[spot.offset:spot.offset + spot.length] = context["staged"]["hp"].to_bytes(spot.length, "big")
                elif kind == "identify":
                    items[0][1] = (bytes.fromhex(items[0][1])[:member.row.hidden.offset]
                                   + bytes([context["staged"]["hidden_staged"]])
                                   + bytes.fromhex(items[0][1])[member.row.hidden.offset + 1:]).hex()
                elif kind == "quickfight":
                    raw[member.row.quickfight.offset] = 1
                elif kind == "levelup":
                    offset = self._levelup_offsets(self.route.game_key).experience
                    raw[offset:offset + 4] = context["staged"]["experience"].to_bytes(
                        4, "big", signed=True)
            if new["raw"] != raw.hex() or new["items"] != items or new["name"] != old["name"]:
                raise AcceptanceStop(f"staging changed an unexpected byte for {member.name}")

    def _verify_action(self, kind: str, context: dict[str, Any], after: list[dict[str, Any]],
                       *, step: str = "action") -> None:
        from automap import amigalevelup, amigaparty  # noqa: PLC0415

        baseline = self._party_by_slot(context["baseline"])
        actual = self._party_by_slot(after)
        if baseline.keys() != actual.keys():
            raise AcceptanceStop("action changed the party slots")
        row_ = amigaparty.ROWS[self.route.game_key]
        for slot, old in baseline.items():
            new = actual[slot]
            raw = bytearray.fromhex(old["raw"])
            items = [[address, data] for address, data in old["items"]]
            if kind == "heal":
                hp, maximum = row_.hp.value(raw), row_.hp_max.value(raw)
                if 0 < hp < maximum:
                    raw[row_.hp.offset:row_.hp.offset + row_.hp.length] = maximum.to_bytes(row_.hp.length, "big")
            elif kind == "identify":
                for node in items:
                    data = bytearray.fromhex(node[1])
                    data[row_.hidden.offset] &= ~row_.hidden.mask & 0xff
                    node[1] = data.hex()
            elif kind == "quickfight":
                if step != "control" and (row_.control is None or not row_.control.value(raw) & 0x80):
                    raw[row_.quickfight.offset] = 0
            elif kind == "spells":
                if step == "cleared" and slot == context["slot"]:
                    raw[row_.memorised.offset + context["spell_index"]] = 0
            elif kind == "levelup":
                if slot == context["slot"]:
                    import random  # noqa: PLC0415
                    from types import SimpleNamespace  # noqa: PLC0415

                    if "levelup_effects" not in context:
                        raise AcceptanceStop("Level up has no staged effect-node readback")
                    member = SimpleNamespace(
                        raw=bytes(raw),
                        item_nodes=[SimpleNamespace(raw=bytes.fromhex(data)) for _, data in items],
                        effect_nodes=[SimpleNamespace(raw=bytes.fromhex(data))
                                      for data in context["levelup_effects"]])

                    class Die:
                        def __init__(self, high):
                            self.high = high

                        def randint(self, low, high):
                            return high if self.high else low

                    try:
                        fixed = amigalevelup.plan_member(member, self.route.game_key,
                                                        rng=random.Random(0))
                        minimum = amigalevelup.plan_member(member, self.route.game_key,
                                                          rng=Die(False))
                        maximum = amigalevelup.plan_member(member, self.route.game_key,
                                                          rng=Die(True))
                    except amigalevelup.CannotLevel as exc:
                        raise AcceptanceStop(f"Level up plan cannot verify: {exc}") from exc
                    ready = amigalevelup.ready_classes(raw, self.route.game_key)
                    if fixed.classes != ready or fixed.added_effects:
                        raise AcceptanceStop("Level up classes or effect-node writes cannot be verified")
                    offsets = self._levelup_offsets(self.route.game_key)
                    hp_rolled, hp_max, hp_current = (
                        offsets.hp_rolled, offsets.hp_max, offsets.hp_current)
                    observed = bytes.fromhex(new["raw"])
                    rolled = (observed[hp_rolled] - raw[hp_rolled]) & 0xff
                    low = (amigalevelup.apply_to(raw, minimum)[hp_rolled] - raw[hp_rolled]) & 0xff
                    high = (amigalevelup.apply_to(raw, maximum)[hp_rolled] - raw[hp_rolled]) & 0xff
                    if not low <= rolled <= high:
                        raise AcceptanceStop("Level up rolled hit points outside the trainer's dice")
                    predicted = bytearray(amigalevelup.apply_to(raw, fixed))
                    if any(at <= hp_rolled < at + len(data) for at, data in fixed.writes):
                        fixed_roll = (predicted[hp_rolled] - raw[hp_rolled]) & 0xff
                        bonus = (predicted[hp_max] - raw[hp_max] - fixed_roll) & 0xff
                        damage = (raw[hp_max] - raw[hp_current]) & 0xff
                        predicted[hp_rolled] = observed[hp_rolled]
                        predicted[hp_max] = (raw[hp_max] + bonus + rolled) & 0xff
                        predicted[hp_current] = (0 if damage > predicted[hp_max]
                                                 else predicted[hp_max] - damage)
                    raw = predicted
            if new["name"] != old["name"] or new["raw"] != raw.hex() or new["items"] != items:
                raise AcceptanceStop(f"{kind} changed unexpected bytes for {old['name']}")

    def _wish_log_mark(self, control: str) -> set[tuple[str, str]] | None:
        """The exception records Wish's logs already hold, so only a new one is charged to the next click.

        None when the log cannot be read: that must not end an otherwise good run.
        """
        try:
            return {winwish.log_block_id(b) for b in winwish.wish_log_errors(self.guest, self.args.holder)}
        except winwish.WinwishError as exc:
            self.summary["wish_log_unread"] += 1
            self.log("wish_log_unread", control=control, error=str(exc))
            return None

    def _wish_log_stop(self, mark: set[tuple[str, str]] | None, control: str) -> None:
        """Stop the run when Wish logged an exception since `mark`."""
        if mark is None:
            return
        try:
            blocks = winwish.wish_log_errors(self.guest, self.args.holder)
        except winwish.WinwishError as exc:
            self.summary["wish_log_unread"] += 1
            self.log("wish_log_unread", control=control, error=str(exc))
            return
        new = [b for b in blocks if winwish.log_block_id(b) not in mark]
        if not new:
            self.log("wish_log_check", control=control, new=0)
            return
        self.log("wish_log_exception", control=control, file=new[0]["file"], lines=new[0]["lines"])
        raise AcceptanceStop(f"Wish logged an exception after {control}: {new[0]['exception']}")

    def _unique_action(self, label: str | None = None, automation_id: str | None = None,
                       *, context: dict[str, Any]) -> None:
        listing = winwish.ui(self.guest, self.args.holder, "controls")
        path = self.out / f"action-controls-{context['kind']}-{len(context['evidence']):02d}.txt"
        path.write_text("\n".join(listing) + "\n")
        context["evidence"].append(str(path))
        matches = [line for line in listing if len(parts := line.split("|")) >= 4
                   and ((automation_id is not None and parts[2] == automation_id)
                        or (label is not None and parts[1] == label))]
        if len(matches) != 1 or "enabled=True" not in matches[0]:
            raise AcceptanceStop(f"{label or automation_id}: absent, ambiguous or disabled; kept {path}")
        if context["kind"] == "levelup":
            if context["member"] not in matches[0]:
                raise AcceptanceStop(f"Level up card does not name {context['member']}; kept {path}")
        self._count(action=True)
        event = {"control": label or automation_id, "listing": str(path),
                 "acknowledged": False}
        context["clicks"].append(event)
        self.log("action_click_attempt", **event)
        context["log_control"] = event["control"]
        context["log_mark"] = self._wish_log_mark(event["control"])
        try:
            winwish.ui(self.guest, self.args.holder, "click", (() if label is None else (label,)),
                       automation_id=automation_id)
        except Exception as exc:
            raise AcceptanceStop(f"action click returned no acknowledgement: {exc}") from exc
        event["acknowledged"] = True
        self.log("action_click", **event)

    def _action_readback(self) -> list[dict[str, Any]]:
        target, party = self._fresh_party()
        try:
            return [self._member_record(member) for member in party]
        finally:
            target.close()

    def _action_visit(self, action: Any, context: dict[str, Any], label: str) -> None:
        namespace = f"{action.kind}.{label}"
        context["visit_checkpoints"] = set()
        before = set(self.checkpoints)
        frames_before = set(self.out.glob("game-*.raw.png"))
        try:
            self.run_phase(action.show, context, namespace=namespace)
            self.run_phase(action.back, context, namespace=namespace)
        finally:
            context["evidence"].extend(name for name in self.checkpoints if name not in before)
            context["evidence"].extend(str(path) for path in sorted(
                set(self.out.glob("game-*.raw.png")) - frames_before))

    def run_actions(self) -> None:
        labels = {"heal": "Heal party", "identify": "Identify",
                  "quickfight": "Quickfight off"}
        selected = {action.kind for action in _selected_actions(self.args, self.route)}
        for action in self.route.actions:
            if not action.enabled:
                self.summary["actions"][action.kind]["reason"] = "observation only on this route"
                continue
            if action.kind not in selected:
                self.summary["actions"][action.kind]["reason"] = "not selected by --action"
                continue
            context = {"kind": action.kind, "evidence": [], "clicks": []}
            result = self.summary["actions"][action.kind]
            result["evidence"] = context["evidence"]
            result["observed"] = context
            try:
                if action.show is None or action.back is None:
                    raise AcceptanceStop("the game-display route is incomplete")
                self._game_section()
                context.update(self._action_input(action))
                context["kind"] = action.kind
                context["staged_readback"] = self._action_readback()
                self._action_visit(action, context, "before")
                self._map_section()
                if action.kind == "spells":
                    self._unique_action("Save spells", context=context)
                    self._game_section()
                    context["saved"] = self._action_readback()
                    self._wish_log_stop(context["log_mark"], context["log_control"])
                    self._verify_action("spells", context, context["saved"])
                    self._game_section()
                    target, party = self._fresh_party()
                    try:
                        member = next(m for m in party if m.slot == context["slot"])
                        offset = member.row.memorised.offset + context["spell_index"]
                        target.write(member.address + offset, b"\x00")
                    finally:
                        target.close()
                    context["cleared"] = self._action_readback()
                    self._verify_action("spells", context, context["cleared"], step="cleared")
                    self._action_visit(action, context, "cleared")
                    self._map_section()
                    self._unique_action("Restore spells", context=context)
                elif action.kind == "levelup":
                    self._unique_action(automation_id=f"card_{context['slot']}_level_up", context=context)
                elif action.kind == "quickfight" and self.quickfight_control:
                    self.log("quickfight_control_not_pressed")
                else:
                    self._unique_action(labels[action.kind], context=context)
                self._game_section()
                context["after"] = self._action_readback()
                if "log_mark" in context:
                    self._wish_log_stop(context["log_mark"], context["log_control"])
                control = action.kind == "quickfight" and self.quickfight_control
                self._verify_action(action.kind, context, context["after"],
                                    step="control" if control else "action")
                self._action_visit(action, context, "after")
                result["expected"] = context.get("staged")
                if control:
                    # Not "awaiting image review", so the persistence check does not expect the byte cleared.
                    result["reason"] = "control run: Quickfight off not pressed"
                else:
                    result["status"] = "awaiting image review"
            except AcceptanceStop as exc:
                result["reason"] = str(exc)
                raise

    @staticmethod
    def _without_addresses(records: list[dict[str, Any]], row_: Any) -> list[dict[str, Any]]:
        normalized = []
        for record in records:
            raw = bytearray.fromhex(record["raw"])
            for offset in row_.pointers:
                raw[offset:offset + 4] = b"\x00" * 4
            items = []
            for _, value in record["items"]:
                node = bytearray.fromhex(value)
                node[row_.items.link:row_.items.link + 4] = b"\x00" * 4
                unsaved = UNSAVED_ITEM_PREFIX.get(row_.title, 0)
                node[:unsaved] = bytes(min(unsaved, len(node)))
                items.append(node.hex())
            normalized.append({"slot": record["slot"], "name": record["name"],
                               "raw": raw.hex(), "items": items})
        return sorted(normalized, key=lambda item: item["slot"])

    def _final_reload(self) -> None:
        from automap import amigaparty  # noqa: PLC0415

        self.summary["original_slot_reload"]["status"] = "unproven"
        initial = self.checkpoints.get("loaded", {}).get("observed")
        if not initial or initial.get("fix") is None or initial.get("party") is None:
            raise AcceptanceStop("the original loaded party and location were not recorded")
        reload_phase = next(phase for phase in self.route.phases if phase.name == "reload")
        if self.leg == "persist":
            # The persist leg skips the phases whose checkpoints the reload compares with;
            # this method compares with `loaded` itself.
            reload_phase = dataclasses.replace(reload_phase, steps=tuple(
                dataclasses.replace(step, expected=dataclasses.replace(
                    step.expected, compare_to=None, relation=None))
                if step.expected is not None and step.expected.compare_to else step
                for step in reload_phase.steps))
        from tools.amiga import maproute  # noqa: PLC0415

        if self.leg == "persist" and self.route.title in maproute.BRANCHED_RELOAD:
            self._reload_original_by_screen(reload_phase)
        else:
            self.run_phase(reload_phase, namespace="original_slot_reload")
        last = [name for name in self.checkpoints if name.startswith("original_slot_reload.")]
        if not last:
            raise AcceptanceStop("the original-slot reload has no checkpoint")
        final = self.checkpoints[last[-1]]["observed"]
        result = self.summary["original_slot_reload"]
        result["expected"] = initial
        result["observed"] = final
        result["evidence"] = last
        row_ = amigaparty.ROWS[self.route.game_key]
        if (final["fix"] != initial["fix"] or
                final["geo_sha256"] != initial["geo_sha256"] or
                final["party"] is None or
                self._without_addresses(final["party"], row_) !=
                self._without_addresses(initial["party"], row_)):
            result["reason"] = "original-slot reload changed location or party bytes"
            raise AcceptanceStop(result["reason"])
        result["status"] = "awaiting image review"

    def _press_to(self, key: str, states: tuple[str, ...], limit: float) -> tuple[str, dict[str, Any]]:
        """Press `key`, then give the first of `states` a fresh frame matches.

        Any other screen ends the run with its frame kept and no further key."""
        self._press(key, action=True)
        state, frame = self._await_first(states, limit=limit)
        if state is None:
            kept = frame["raw"] if frame else "no exact crop"
            raise AcceptanceStop(f"persist reload: the screen after {key} is none of "
                                 f"{', '.join(states)}; kept {kept}")
        return state, frame

    def _persist_save(self) -> None:
        """Camp, a readback on the guarded camp bar, then a save to the persist letter."""
        from tools.amiga import maproute  # noqa: PLC0415

        if self.encounters_on:
            raise AcceptanceStop("the persist save needs encounter suppression off")
        result = self.summary["persistence"]
        saved, rest = maproute.persist_phases(self.route, self.persist["letter"])
        frames = set(self.out.glob("game-*.raw.png"))
        self.persist_keys = True
        try:
            self._game_section()
            self.run_phase(saved)
            # Camp rewrites some bytes as it opens, so the readback follows its guarded bar.
            self._game_section()
            result["persist_before"] = self._action_readback()
            self.run_phase(rest)
        finally:
            self.persist_keys = False
            result["evidence"].extend(str(path) for path in sorted(
                set(self.out.glob("game-*.raw.png")) - frames))

    def _camp_load(self, letter: str) -> dict[str, Any]:
        """From the camp bar, camp LOAD of slot `letter`, answering only the guarded screens
        the title can show; the frame of the world bar it ends on."""
        self._game_section()
        self.continue_presses = 0
        if self.route.title == "ssb":
            state, _ = self._press_to("L", ("load_anyway", "load_picker"), CAMP_LOAD_WAIT)
            if state == "load_anyway":
                self._press_to("Y", ("load_picker",), CAMP_LOAD_WAIT)
            self._press_to(letter, ("loaded_menu",), CAMP_SLOT_WAIT)
            self._press_to("B", ("journal",), CAMP_LOAD_WAIT)
            self._answer_journal()
            state, frame = self._await_first(("world", "treasure_bar", "continue"),
                                             limit=CAMP_SLOT_WAIT)
            if state is None:
                kept = frame["raw"] if frame else "no exact crop"
                raise AcceptanceStop(f"persist reload: the screen after the journal answer "
                                     f"is none of world, treasure_bar or continue; kept {kept}")
            state, frame = self._through_continue(state, frame, ("treasure_bar",))
            if state == "treasure_bar":
                self._press_to("E", ("treasure",), CAMP_LOAD_WAIT)
                state, frame = self._press_to("N", ("world", "continue"), CAMP_SLOT_WAIT)
                state, frame = self._through_continue(state, frame, ())
            return frame
        state, _ = self._press_to("L", ("load_anyway", "load_from"), CAMP_LOAD_WAIT)
        if state == "load_anyway":
            self._press_to("Y", ("load_from",), CAMP_LOAD_WAIT)
        self._press_to("P", ("load_picker",), CAMP_LOAD_WAIT)
        self._press_to(letter, ("loaded_menu",), CAMP_SLOT_WAIT)
        state, frame = self._press_to("B", ("world", "continue"), CAMP_SLOT_WAIT)
        return self._through_continue(state, frame, ())[1]

    def _through_continue(self, state: str, frame: dict[str, Any], also: tuple[str, ...]
                          ) -> tuple[str, dict[str, Any]]:
        """RETURN on each `continue` page (the "grown bored with peace" text after a load), a
        bounded number of times, until the world bar or one of `also` is up."""
        while state == "continue":
            if self.continue_presses == PERSIST_CONTINUE_PAGES:
                raise AcceptanceStop(f"persist reload: still on a continue page after "
                                     f"{self.continue_presses} RETURN presses; kept {frame['raw']}")
            self.continue_presses += 1
            shown = digest(pathlib.Path(frame["crop"]))
            self._press("RET", action=True)
            pressed = self.clock()
            states = ("world", "continue", *also)
            while True:
                state, frame = self._await_first(states, limit=CAMP_SLOT_WAIT)
                if state is None:
                    kept = frame["raw"] if frame else "no exact crop"
                    raise AcceptanceStop(f"persist reload: the screen after RET is none of "
                                         f"{', '.join(states)}; kept {kept}")
                # The same page before the game has redrawn is not a second page.
                if (state == "continue" and digest(pathlib.Path(frame["crop"])) == shown
                        and self.clock() - pressed < CONTINUE_SETTLE):
                    self.sleep(self.left(1))
                    continue
                break
        return state, frame

    def _reload_original_by_screen(self, reload_phase: Any) -> None:
        """The persist leg's original-slot reload for the titles whose camp LOAD varies.

        After a save and a load the game may skip the LOAD ANYWAY question the mapping route
        meets, so each screen is guarded and nothing else is answered."""
        last = reload_phase.steps[-1]
        self.persist_keys = True
        try:
            self._game_section()
            self._press_to("E", ("camp",), CAMP_LOAD_WAIT)
            frame = self._camp_load(self.route.loaded_slot)
        finally:
            self.persist_keys = False
        self._checkpoint(f"original_slot_reload.{last.checkpoint}", last.expected, frame)
        self.summary["completed_sequence"].append("original_slot_reload.reload")

    def _persist_reload(self) -> None:
        """Camp LOAD of the persist letter, answering only the screens measured for the title."""
        from tools.amiga import maproute  # noqa: PLC0415

        if self.route.title not in maproute.BRANCHED_RELOAD:
            return
        letter = self.persist["letter"]
        frames = set(self.out.glob("game-*.raw.png"))
        self.persist_keys = True
        try:
            frame = self._camp_load(letter)
            self._checkpoint("persist_reloaded", maproute.Expected(
                compare_to="persist_saved", relation="equal"), frame)
            self.summary["completed_sequence"].append("persist_reload")
        finally:
            self.persist_keys = False
            self.summary["persistence"]["evidence"].extend(str(path) for path in sorted(
                set(self.out.glob("game-*.raw.png")) - frames))

    def _persist_differences(self, before: list[dict[str, Any]], after: list[dict[str, Any]],
                             ran: dict[str, dict[str, Any]]) -> tuple[list[str], list[str]]:
        """Bytes that differ across the save and reload: `(in this run's action spots, elsewhere)`.

        Heap addresses are zeroed first, as the original-slot reload does, since a reload
        places the records again."""
        from automap import amigaparty  # noqa: PLC0415

        row_ = amigaparty.ROWS[self.route.game_key]
        old = {r["slot"]: r for r in self._without_addresses(before, row_)}
        new = {r["slot"]: r for r in self._without_addresses(after, row_)}
        if old.keys() != new.keys() or any(old[k]["name"] != new[k]["name"] for k in old):
            return [], ["the party's members or names differ"]
        spans: set[int] = set()
        if "heal" in ran:
            spans.update(range(row_.hp.offset, row_.hp.offset + row_.hp.length))
        if "spells" in ran:
            spans.update(range(row_.memorised.offset, row_.memorised.offset + row_.memorised.length))
        if "quickfight" in ran and row_.quickfight is not None:
            spans.update(range(row_.quickfight.offset, row_.quickfight.offset + row_.quickfight.length))
        hidden = set(range(row_.hidden.offset, row_.hidden.offset + row_.hidden.length)) \
            if "identify" in ran else set()
        levelled = ran["levelup"]["slot"] if "levelup" in ran else None
        inside: list[str] = []
        outside: list[str] = []
        for slot in sorted(old):
            name = old[slot]["name"]
            was, now = bytes.fromhex(old[slot]["raw"]), bytes.fromhex(new[slot]["raw"])
            if len(was) != len(now):
                outside.append(f"{name} record length")
                continue
            for at in (i for i in range(len(was)) if was[i] != now[i]):
                (inside if slot == levelled or at in spans else outside).append(
                    f"{name}+0x{at:03X}")
            if len(old[slot]["items"]) != len(new[slot]["items"]):
                outside.append(f"{name} item count")
                continue
            for number, (a, b) in enumerate(zip(old[slot]["items"], new[slot]["items"], strict=True)):
                was, now = bytes.fromhex(a), bytes.fromhex(b)
                for at in (i for i in range(min(len(was), len(now))) if was[i] != now[i]):
                    (inside if at in hidden else outside).append(f"{name} item {number}+0x{at:02X}")
        return inside, outside

    def _persist_lost(self, after: list[dict[str, Any]], ran: dict[str, dict[str, Any]]) -> list[str]:
        """Actions whose field still holds the value the run staged, not the one Wish wrote."""
        from automap import amigaparty  # noqa: PLC0415

        row_ = amigaparty.ROWS[self.route.game_key]
        now = self._party_by_slot(after)
        lost = []
        for kind, context in ran.items():
            slot = context["slot"]
            if slot not in now:
                lost.append(f"{kind}: member {context['member']} is not in the reloaded party")
                continue
            raw = bytes.fromhex(now[slot]["raw"])
            staged = self._party_by_slot(context["baseline"])[slot]
            if kind == "heal" and row_.hp.value(raw) == context["staged"]["hp"]:
                lost.append(f"heal: hit points still hold the staged {context['staged']['hp']}")
            elif kind == "quickfight" and raw[row_.quickfight.offset] == context["staged"]["quickfight"]:
                lost.append("quickfight: the byte still holds the staged value")
            elif kind == "spells":
                cleared = bytes.fromhex(self._party_by_slot(context["cleared"])[slot]["raw"])
                at = row_.memorised.offset + context["spell_index"]
                if raw[at] == cleared[at]:
                    lost.append("spells: the spell still holds the cleared value")
            elif kind == "identify":
                index = next(i for i, (address, _) in enumerate(staged["items"])
                             if address == context["staged"]["item_address"])
                node = bytes.fromhex(now[slot]["items"][index][1])
                if node[row_.hidden.offset] == context["staged"]["hidden_staged"]:
                    lost.append("identify: the item still holds the staged hidden byte")
            elif kind == "levelup" and raw == bytes.fromhex(staged["raw"]):
                lost.append("levelup: the record still holds the staged experience")
        return lost

    def _verify_persist(self) -> None:
        """Compare the party read after the save and reload with the one read at camp."""
        result = self.summary["persistence"]
        self._game_section()
        after = self._action_readback()
        before = result["persist_before"]
        ran = {kind: entry["observed"] for kind, entry in self.summary["actions"].items()
               if entry["status"] == "awaiting image review"}
        inside, outside = self._persist_differences(before, after, ran)
        lost = self._persist_lost(after, ran)
        result.update(persist_after=after, differing={"in_action_spots": inside, "elsewhere": outside},
                      lost=lost, expected={"letter": self.persist["letter"]})
        result["evidence"].extend(name for name in ("persist_saved", "persist_reloaded")
                                  if name in self.checkpoints)
        if inside or lost:
            reasons = ([f"changed in an action's spot: {', '.join(inside)}"] if inside else []) + lost
            result.update(status="failed", reason="; ".join(reasons))
        elif outside:
            result.update(status="unproven",
                          reason="bytes outside this run's action spots differ: " + ", ".join(outside))
        else:
            result["status"] = "awaiting image review"

    def _verify_disk_slot(self) -> None:
        """The persist slot on the fetched working save disk lists the party that was reloaded."""
        from goldbox import amiga_adf  # noqa: PLC0415

        result = self.summary["persistence"]
        after = result.get("persist_after")
        if after is None:
            return
        key = self.route.amiga_title.save_disk
        copied = self.info["media"].get(key, {}).get("guest_working_copy")

        def fail(status: str, reason: str) -> None:
            if result["status"] == "awaiting image review":
                result.update(status=status, reason=reason)
            self.summary["failure"] = self.summary["failure"] or f"persistence {status}: {reason}"

        if not copied:
            fail("unproven", "the working save disk was not fetched")
            return
        try:
            reading = self.route.amiga_title.read_slot(
                amiga_adf.AmigaDisk.open(copied), self.persist["letter"])
        except Exception as exc:  # noqa: BLE001
            fail("unproven", f"the working save disk could not be read: {type(exc).__name__}: {exc}")
            return
        result["disk_slot"] = reading
        names = sorted(str(name).strip().upper() for name in reading.get("names") or [])
        wanted = sorted(record["name"].strip().upper() for record in after)
        if reading.get("missing") or reading.get("decode_error"):
            fail("failed", f"slot {self.persist['letter']} is not readable on the fetched disk: "
                           f"{reading.get('decode_error') or 'missing'}")
        elif names != wanted:
            # The reload already showed the right party; only the disk reader's padding,
            # truncation or case handling may differ, which nothing here has verified.
            fail("unproven", f"slot {self.persist['letter']} on the fetched disk lists {names}, "
                             f"the reloaded party {wanted}")

    def _verify_quickfight_control(self) -> None:
        """The staged member's quickfight byte at camp, on the fetched disk and after the reload."""
        if not self.quickfight_control:
            return
        from automap import amigaparty  # noqa: PLC0415
        from goldbox import amiga_adf, amiga_savegame  # noqa: PLC0415

        result = self.summary["quickfight_control"]
        result["status"] = "unproven"
        context = self.summary["actions"].get("quickfight", {}).get("observed") or {}
        name = str(context.get("member", "")).strip().upper()
        spot = amigaparty.ROWS[self.route.game_key].quickfight

        def read(records: list[dict[str, Any]] | None) -> int | None:
            for record in records or ():
                if str(record["name"]).strip().upper() == name:
                    return spot.value(bytes.fromhex(record["raw"]))
            return None

        persistence = self.summary["persistence"]
        camp, reloaded = read(persistence.get("persist_before")), read(persistence.get("persist_after"))
        disk = None
        copied = self.info["media"].get(self.route.amiga_title.save_disk, {}).get("guest_working_copy")
        reason = None
        if not copied:
            reason = "the working save disk was not fetched"
        else:
            try:
                saved = amiga_savegame.read_slot(amiga_adf.AmigaDisk.open(copied), self.persist["letter"])
                disk = next((spot.value(character.raw) for character in saved.characters
                             if str(character.name).strip().upper() == name), None)
            except Exception as exc:  # noqa: BLE001
                reason = f"the working save disk could not be read: {type(exc).__name__}: {exc}"
            else:
                if disk is None:
                    reason = f"{name} is not in slot {self.persist['letter']} on the fetched disk"
        reads = {"camp": camp, "disk": disk, "reloaded": reloaded}
        result["observed"] = reads
        offset = f"+0x{spot.offset:02X}"
        if camp != 1:
            result["reason"] = f"the quickfight byte {offset} read {camp} at camp, not the staged 1"
        elif disk == 0:
            result.update(status="failed", reason=(
                f"the game does not save the quickfight byte {offset}: slot "
                f"{self.persist['letter']} on the disk holds 0, so the persistence passes that "
                "pressed Quickfight off cannot be counted"))
        elif reason:
            result["reason"] = reason
        elif disk == 1 and reloaded == 1:
            result["status"] = "passed"
        else:
            result["reason"] = f"the reads at camp, on the disk and after the reload were {reads}"

    def run_persist(self) -> dict[str, Any]:
        """Load, press the selected actions, save to a letter the disk lacks, load it again, compare."""
        from tools.amiga import maproute  # noqa: PLC0415

        result = self.summary["persistence"]
        result["letter"] = self.persist["letter"]
        result["evidence"] = []
        try:
            self._up()
            self._game_section()
            title = self._await_title()
            self.summary["mapping"]["title"] = row("awaiting image review", evidence=[title])
            phases = {phase.name: phase for phase in self.route.phases}
            for name in maproute.LEG_PREFIX[self.route.title]:
                self.run_phase(phases[name])
                self.summary["mapping"][name] = row("awaiting image review")
            self.run_actions()
            self._persist_save()
            self._persist_reload()
            self._verify_persist()
            self._game_section()
            self._await("world")
            self._final_reload()
            if result["status"] != "awaiting image review":
                raise AcceptanceStop(f"persistence {result['status']}: {result['reason']}")
        except BaseException as exc:
            self.summary["failure"] = f"{type(exc).__name__}: {exc}"
            self.log("failure", error=self.summary["failure"], **guest_failure_fields(exc))
            if result["status"] == "unproven" and not result.get("reason"):
                result["reason"] = self.summary["failure"]
        finally:
            self._cleanup()
            self._verify_disk_slot()
            self._verify_quickfight_control()
            (self.out / "summary.json").write_text(json.dumps(self.summary, indent=2, default=str) + "\n")
        return self.summary

    def _read_mode(self) -> int | None:
        """One read of the game's mode byte, through a pipe connection the driver closes again."""
        from automap import amiga, amigaparty  # noqa: PLC0415
        from tools.amiga import amigatarget  # noqa: PLC0415

        target = amigatarget.connect_pipe(self.args.holder, amiga.MACHINES[self.route.game_key])
        try:
            return amigaparty.mode(target)
        finally:
            target.close()
            self.game._pipe = None

    @staticmethod
    def _record_differences(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[str]:
        """Each record byte and item node that differs, as `NAME +0xOFF` or `NAME item N`."""
        old = {record["slot"]: record for record in before}
        new = {record["slot"]: record for record in after}
        if old.keys() != new.keys():
            return [f"party slots {sorted(old)} became {sorted(new)}"]
        found = []
        for slot, record in old.items():
            then, now = bytes.fromhex(record["raw"]), bytes.fromhex(new[slot]["raw"])
            found += [f"{record['name']} +0x{at:02X}" for at in range(max(len(then), len(now)))
                      if then[at:at + 1] != now[at:at + 1]]
            if record["items"] != new[slot]["items"]:
                found.append(f"{record['name']} items")
        return found

    def _greyed_check(self, memory: Any) -> None:
        """At the first command bar: every action button greyed unless combat-legal, one click on
        a greyed one, and the bar, its owner, the mode and every party byte as they were."""
        from automap import amigaparty  # noqa: PLC0415
        from tools.amiga import curseadd, cursefight, maproute  # noqa: PLC0415

        result = self.summary["fight_greyed"]
        row_ = amigaparty.ROWS[self.route.game_key]
        observed: dict[str, Any] = {}
        result["observed"] = observed

        def owner() -> dict[str, Any] | None:
            return curseadd.bounded(lambda _h: memory.owner(), memory.holder,
                                    self.left(cursefight.READ_LIMIT))

        self._game_section()
        frame = self._capture("combat_bar")
        observed["owner"] = owner()
        observed["mode"] = self._read_mode()
        before = self._action_readback()
        if self.dip is not None:
            self._dip_at_first_bar(row_, before)
        self._checkpoint("fight_bar", None, frame, reads=(maproute.Read("mode", "base", row_.mode, 1),))
        listing_path = pathlib.Path(self.checkpoints["fight_bar"]["controls"])
        result["evidence"] = ["fight_bar", str(listing_path)]
        listing = listing_path.read_text().splitlines()
        enabled = {}
        for label in GREYED_ACTIONS:
            lines = [line for line in listing if len(parts := line.split("|")) >= 4 and parts[1] == label]
            if len(lines) != 1:
                result.update(status="failed", reason=f"{label} is absent or ambiguous; kept {listing_path}")
                raise AcceptanceStop(f"fight bar: {result['reason']}")
            enabled[label] = "enabled=True" in lines[0]
        observed["enabled"] = enabled
        wrong = [label for label, on in enabled.items()
                 if on and GREYED_ACTIONS[label] not in row_.combat_legal]
        wrong += [line.split("|")[2] for line in listing if len(line.split("|")) >= 4
                  and "card_" in line.split("|")[2] and "_level_up" in line.split("|")[2]
                  and "enabled=True" in line]
        if wrong:
            result.update(status="failed", reason=f"enabled in a fight: {', '.join(wrong)}; kept {listing_path}")
            raise AcceptanceStop(f"fight bar: {result['reason']}")
        label = next(label for label, action in GREYED_ACTIONS.items()
                     if action not in row_.combat_legal)
        click: dict[str, Any] = {"control": label, "acknowledged_as_action": False}
        self._map_section()
        mark = self._wish_log_mark(label)
        try:
            click["reply"] = winwish.ui(self.guest, self.args.holder, "click", (label,))
        except winwish.ControlDisabled as exc:
            # The click script found the button and left it alone: the answer a greyed one gives.
            click.update(disabled=exc.control, message=str(exc))
        except Exception as exc:  # noqa: BLE001 - the reply or error is the record, not a verdict
            click["error"] = f"{type(exc).__name__}: {exc}"
        observed["click"] = click
        self.log("greyed_click", **click)
        self._wish_log_stop(mark, label)
        self._game_section()
        problems = []
        try:
            again = self._capture("combat_bar")
            result["evidence"].append(again["raw"])
        except AcceptanceStop as exc:
            problems.append(f"the command bar did not stay: {exc}")
        observed["owner_after"] = owner()
        observed["mode_after"] = self._read_mode()
        after = self._action_readback()
        if (observed["owner_after"] or {}).get("address") != (observed["owner"] or {}).get("address"):
            problems.append(f"the bar's owner moved from {observed['owner']} to {observed['owner_after']}")
        for name in ("mode", "mode_after"):
            if observed[name] != row_.combat_value:
                problems.append(f"{name} reads {observed[name]}, not {row_.combat_value}")
        changed = self._record_differences(before, after)
        if changed:
            problems.append("party bytes changed: " + ", ".join(changed))
        observed["party_before"], observed["party_after"] = before, after
        if "reply" in click:
            # The click script invokes only an enabled control.
            problems.append(f"the click on {label} was carried out, so the button was enabled")
        elif "disabled" in click and click["disabled"] != label:
            problems.append(f"the click on {label} answered for {click['disabled']}")
        if problems:
            result.update(status="failed", reason="; ".join(problems))
        elif "error" in click:
            result.update(status="unproven",
                          reason=f"the click on {label} found no greyed button: {click['error']}")
        else:
            result["status"] = "awaiting image review"

    @staticmethod
    def _member_bytes(row_: Any, record: dict[str, Any]) -> tuple[int, int]:
        """The control bit 7 and the quickfight byte of one read-back record."""
        raw = bytes.fromhex(record["raw"])
        control = row_.control.value(raw) if row_.control is not None else 0
        return control, row_.quickfight.value(raw)

    def _stage_dip(self) -> None:
        """Write QUICK to the first member the computer does not already play, and read it back."""
        from automap import amiga, amigaparty  # noqa: PLC0415
        from tools.amiga import amigatarget  # noqa: PLC0415

        row_ = amigaparty.ROWS[self.route.game_key]
        target = amigatarget.connect_pipe(self.args.holder, amiga.MACHINES[self.route.game_key])
        try:
            party = amigaparty.read_party(target) or ()
            member = next((m for m in party
                           if not (row_.control.value(m.raw) if row_.control is not None else 0)), None)
            if member is None:
                raise AcceptanceStop("no member without a companion control byte to stage QUICK on")
            target.write(member.address + row_.quickfight.offset, b"\x01")
            again = amigaparty.read_party(target) or ()
            back = next((m for m in again if m.slot == member.slot), None)
            if back is None or row_.quickfight.value(back.raw) != 1:
                raise AcceptanceStop(f"the QUICK write to {member.name} did not read back")
        finally:
            target.close()
            self.game._pipe = None
        self.dip = {"slot": member.slot, "name": member.name, "address": member.address,
                    "before": row_.quickfight.value(member.raw)}
        self.log("watch_dip_staged", **self.dip)

    def _dip_at_first_bar(self, row_: Any, readback: list[dict[str, Any]]) -> None:
        """The staged member's QUICK byte at the first bar: 1 means Wish did not clear it while
        the mode dipped on the way into the fight."""
        record = next((r for r in readback if r["slot"] == self.dip["slot"]), None)
        value = None if record is None else self._member_bytes(row_, record)[1]
        result = self.summary["watch_dip"]
        result["observed"] = {**self.dip, "at_first_bar": value}
        if value == 1:
            result["status"] = "awaiting image review"
        elif value == 0:
            result.update(status="failed", reason=f"{self.dip['name']} reads QUICK 0 at the first bar")
        else:
            result["reason"] = f"{self.dip['name']} could not be read at the first bar"

    def _watch_edge(self, key: str) -> bool:
        """The clear-quickfight edge, taken on CONTINUE BATTLE, which nothing has yet left.

        The key is queued twice from one snapshot: with the Character Editor showing, where Wish
        does not poll, so the game alone decides what the quickfight bytes hold; then, after the
        snapshot is restored, with the Automapper showing. Returns whether it sent the key."""
        from automap import amigaparty  # noqa: PLC0415

        row_ = amigaparty.ROWS[self.route.game_key]
        holder = self.args.holder
        control_row, wish_row = self.summary["watch_control_b"], self.summary["watch_a"]
        self.edge_done = True
        self._game_section()
        self._await("continue_battle", limit=30)
        mode = self._read_mode()
        if mode != row_.combat_value:
            raise AcceptanceStop(f"CONTINUE BATTLE reads mode {mode}, not {row_.combat_value}")
        self.game.snapshot(FIGHT_EDGE_SNAPSHOT, holder)
        edge_before = self._action_readback()
        chosen = [r["slot"] for r in edge_before if self._member_bytes(row_, r) == (0, 1)]
        if not chosen:
            for result in (control_row, wish_row):
                result["reason"] = "no member was on QUICK and played by the party at CONTINUE BATTLE"
            return False
        by_slot = {r["slot"]: r for r in edge_before}
        companions = [slot for slot, r in by_slot.items() if self._member_bytes(row_, r)[0]]

        def quickfight(readback: list[dict[str, Any]], slot: int) -> int | None:
            record = next((r for r in readback if r["slot"] == slot), None)
            return None if record is None else self._member_bytes(row_, record)[1]

        schedule = self._scheduled_key(key, show_map=False)
        frame = self._await("party_won", limit=60)
        after = self._action_readback()
        mode_b = self._read_mode()
        problems = []
        if mode_b != row_.after_fight_value:
            problems.append(f"the mode reads {mode_b}, not {row_.after_fight_value}")
        cleared = [by_slot[slot]["name"] for slot in chosen if quickfight(after, slot) != 1]
        if cleared:
            problems.append("the game itself cleared QUICK on " + ", ".join(cleared))
        control_row.update(
            status="failed" if problems else "awaiting image review",
            reason="; ".join(problems) or None, evidence=[frame.get("raw")],
            observed={"set": chosen, "mode": mode_b, "schedule": schedule,
                      "party_after": after})
        control_after = after
        self.game.restore(FIGHT_EDGE_SNAPSHOT, holder)
        self._await("continue_battle", limit=60)
        mode_r = self._read_mode()
        changed = self._record_differences(edge_before, self._action_readback())
        if mode_r != row_.combat_value or changed:
            why = (f"the restored game reads mode {mode_r}, not {row_.combat_value}"
                   if mode_r != row_.combat_value else "party bytes differ after the restore: "
                   + ", ".join(changed))
            for result in (control_row, wish_row):
                result.update(status="unproven", reason=why)
            raise AcceptanceStop(f"fight_edge restore: {why}")
        self._count(action=True)
        schedule = self._scheduled_key(key, show_map=True)
        timings: dict[str, float] = {}
        wish_path, controls_path = self._wish_pair("watch_a", self._lap(timings))
        self._game_section()
        frame = self._await("party_won", limit=60)
        after = self._action_readback()
        mode_a = self._read_mode()
        problems = []
        if mode_a != row_.after_fight_value:
            problems.append(f"the mode reads {mode_a}, not {row_.after_fight_value}")
        kept = [by_slot[slot]["name"] for slot in chosen if quickfight(after, slot) != 0]
        if kept:
            problems.append("QUICK still set on " + ", ".join(kept))
        moved = [by_slot[slot]["name"] for slot in companions
                 if quickfight(after, slot) != quickfight(edge_before, slot)]
        if moved:
            problems.append("a companion's QUICK byte changed on " + ", ".join(moved))
        suffix = f" +0x{row_.quickfight.offset:02X}"
        # The control run takes the same journey, so the experience and fight teardown the game
        # itself writes are in its bytes too; only what Wish writes differs.
        other = [d for d in self._record_differences(control_after, after) if not d.endswith(suffix)]
        if other:
            problems.append("bytes other than QUICK changed: " + ", ".join(other))
        wish_row.update(
            status="failed" if problems else "awaiting image review",
            reason="; ".join(problems) or None,
            evidence=[str(wish_path), str(controls_path), frame.get("raw")],
            observed={"set": chosen, "companions": companions, "mode": mode_a,
                      "schedule": schedule, "timings": timings})
        odd = self._odd_modes()
        if odd:
            # Another mode value would disarm Wish's watcher, so a missing clear proves nothing.
            for result in (control_row, wish_row):
                if result["status"] == "awaiting image review":
                    result.update(status="unproven", reason=odd)
        return True

    def _last_quick(self, bars: list[dict[str, Any]]) -> bool:
        """Whether the bar just read is the last Q: every record the party plays and had not on
        QUICK at the first bar has had a bar. A companion or a `--watch-dip` member is not one."""
        from automap import amigaparty  # noqa: PLC0415

        before = (self.summary["fight_greyed"].get("observed") or {}).get("party_before") or []
        if not bars:
            return False
        if not any(r["address"] == bars[0]["address"] for r in before):
            raise AcceptanceStop("the first bar's owner is not a party record")
        row_ = amigaparty.ROWS[self.route.game_key]
        played = {r["address"] for r in before if self._member_bytes(row_, r) == (0, 0)}
        return bool(played) and played <= {bar["address"] for bar in bars}

    def _map_hold(self, plan: FightPlan, screens: Any) -> None:
        """Keep the Automapper showing after the last Q until CONTINUE BATTLE, glancing at the
        game after `MAP_HOLD_FIRST` seconds and then every `MAP_HOLD_NEXT`.

        Every glance frees the pipe, so Wish does not poll then. Every return, whether CONTINUE
        BATTLE, a command bar or a defeat screen, leaves Wish on the Character Editor with the
        pipe released; a stop on the time limit raises with the editor showing too."""
        self.map_hold_done = True
        result = self.summary["watch_map"]
        modes = self.summary["fight"]["modes"]
        gaps: list[dict[str, float]] = []
        shown = round(self.clock() - self.started, 3)
        began, wait = self.clock(), MAP_HOLD_FIRST
        while True:
            self.sleep(self.left(wait))
            wait = MAP_HOLD_NEXT
            opened = round(self.clock() - self.started, 3)
            self._game_section()
            frame = self._capture("hold", check=False)
            mode = self._read_mode()
            crop = frame.get("crop")
            state = next((name for name in ("continue_battle", "combat_bar", *plan.rules.defeat)
                          if crop and screens._matches(name, pathlib.Path(crop))), None)
            now = round(self.clock() - self.started, 3)
            modes.append({"screen": state, "mode": mode, "elapsed": now, "hold": True})
            gaps.append({"from": opened, "to": now})
            result["observed"] = {"map_shown_s": shown, "editor_gaps": gaps}
            if state == "continue_battle":
                self._grade_map_hold(result, frame, shown, gaps)
                return
            if state == "combat_bar":
                from tools.amiga import curseadd, cursefight  # noqa: PLC0415

                owner = curseadd.bounded(lambda _h: screens.memory.owner(), screens.memory.holder,
                                         self.left(cursefight.READ_LIMIT))
                result.update(status="failed", reason=(
                    f"a command bar showed for {(owner or {}).get('name')} during the hold"))
                return
            if state is not None:
                result["reason"] = f"the fight reached {state} during the hold"
                return
            if self.clock() - began >= MAP_HOLD_LIMIT:
                raise AcceptanceStop(
                    f"CONTINUE BATTLE did not show within {MAP_HOLD_LIMIT:.0f} s of the last Q")
            self._map_section()

    def _grade_map_hold(self, result: dict[str, Any], frame: dict[str, Any], shown: float,
                        gaps: list[dict[str, float]]) -> None:
        """The `watch_map` row at CONTINUE BATTLE, with the Character Editor showing: every member
        Q'd or staged still on QUICK, and no `Removed quickfight` line in Wish's Messages."""
        from automap import amigaparty  # noqa: PLC0415

        row_ = amigaparty.ROWS[self.route.game_key]
        wanted = {bar["address"]: bar["owner"] for bar in self.summary["fight"]["found"]["bars"]}
        if self.dip is not None:
            wanted[self.dip["address"]] = self.dip["name"]
        readback = self._action_readback()
        by_address = {r["address"]: r for r in readback}
        problems = []
        for address, name in wanted.items():
            record = by_address.get(address)
            value = None if record is None else self._member_bytes(row_, record)[1]
            if value != 1:
                problems.append(f"QUICK {0 if value is None else value} at CONTINUE BATTLE on {name}")
        self._map_section()
        timings: dict[str, float] = {}
        wish_path, controls_path = self._wish_pair("watch_map", self._lap(timings))
        if any("ListItem" in line and "Removed quickfight" in line
               for line in controls_path.read_text().splitlines()):
            problems.append("Wish's Messages list holds a Removed quickfight line")
        self._game_section()
        result.update(
            status="failed" if problems else "awaiting image review",
            reason="; ".join(problems) or None,
            evidence=[str(wish_path), str(controls_path), frame.get("raw")],
            observed={"set": sorted(wanted.values()), "party": readback,
                      "modes_in_hold": [m for m in self.summary["fight"]["modes"] if m.get("hold")],
                      "editor_gaps": gaps, "map_shown_s": shown})

    def _odd_modes(self) -> str | None:
        """Why the modes table cannot back the edge: a mode other than 2, 4 or 5 between the
        first command bar and CONTINUE BATTLE."""
        table = self.summary["fight"]["modes"]
        first = next((at for at, entry in enumerate(table) if entry["screen"] == "combat_bar"), None)
        if first is None:
            return None
        odd = [(entry["screen"], entry["mode"]) for entry in table[first:]
               if entry["mode"] not in (2, 4, 5)]
        return f"the mode read {odd} between the first bar and CONTINUE BATTLE" if odd else None

    def _press_quickfight_off(self, bars: list[dict[str, Any]]) -> None:
        """At the first bar of a member other than the first bar's, press Quickfight off in Wish.

        X is the first bar's member and Y the one whose bar this is. The state is snapshotted
        first, so the same turn can be replayed without the click."""
        from automap import amigaparty  # noqa: PLC0415

        x, y = bars[0], bars[-1]
        if y["address"] == x["address"]:
            return
        row_ = amigaparty.ROWS[self.route.game_key]
        holder = self.args.holder
        rows = (self.summary["qf_press_a"], self.summary["qf_press_b"])
        self.pod = {"x": x, "y": y, "y_index": len(bars) - 1, "snapshot": None}
        self._game_section()
        self.game.snapshot(POD_QF_SNAPSHOT, holder)
        before = self._action_readback()
        record = next((r for r in before if r["address"] == x["address"]), None)
        if record is None or self._member_bytes(row_, record)[1] != 1:
            for result in rows:
                result["reason"] = f"{x['owner']} was not on QUICK at {y['owner']}'s bar"
            return
        self.pod.update(snapshot=POD_QF_SNAPSHOT, before=before)
        self._map_section()
        mark = self._wish_log_mark("Quickfight off")
        try:
            reply = winwish.ui(self.guest, holder, "click", ("Quickfight off",))
        except Exception as exc:  # noqa: BLE001 - the error is the record
            rows[0].update(status="unproven", reason=f"Quickfight off returned no acknowledgement: {exc}")
            raise AcceptanceStop(rows[0]["reason"]) from exc
        self.log("quickfight_off_click", reply=reply)
        self._game_section()
        after = self._action_readback()
        self._wish_log_stop(mark, "Quickfight off")
        problems = []
        if self._member_bytes(row_, next(r for r in after if r["address"] == x["address"]))[1] != 0:
            problems.append(f"{x['owner']} still reads QUICK 1")
        free = {f"{r['name']} +0x{row_.quickfight.offset:02X}" for r in before
                if not self._member_bytes(row_, r)[0]}
        other = [d for d in self._record_differences(before, after) if d not in free]
        if other:
            problems.append("bytes other than QUICK changed: " + ", ".join(other))
        if problems:
            rows[0].update(status="failed", reason="; ".join(problems))
            raise AcceptanceStop("Quickfight off: " + rows[0]["reason"])

    def _pod_replay(self, plan: FightPlan, screens: Any, memory: Any) -> None:
        """Judge the click's run, then play the same turn again from the snapshot without it."""
        from tools.amiga import curseadd, cursefight  # noqa: PLC0415

        result = self.summary["fight"]
        click_row, control_row = self.summary["qf_press_a"], self.summary["qf_press_b"]
        pod = self.pod
        if not pod:
            for item in (click_row, control_row):
                item["reason"] = "the fight ended before a second member's command bar"
            return
        if pod["snapshot"] is None:
            return
        x, y = pod["x"], pod["y"]
        later = [bar for bar in (result["found"].get("bars") or [])[pod["y_index"] + 1:]
                 if bar["address"] == x["address"]]
        if click_row["status"] == "unproven":
            if later:
                click_row.update(status="awaiting image review",
                                 evidence=[bar["shot"] for bar in later],
                                 observed={"x": x["owner"], "bars": len(later)})
            else:
                click_row["reason"] = f"the fight ended before {x['owner']}'s next turn"
        self._game_section()
        self.game.restore(POD_QF_SNAPSHOT, self.args.holder)
        self._await("combat_bar", limit=60)
        owner = curseadd.bounded(lambda _h: memory.owner(), memory.holder,
                                 self.left(cursefight.READ_LIMIT))
        changed = self._record_differences(pod["before"], self._action_readback())
        if (owner or {}).get("address") != y["address"] or changed:
            why = (f"the restored bar belongs to {(owner or {}).get('name')}, not {y['owner']}"
                   if (owner or {}).get("address") != y["address"]
                   else "party bytes differ after the restore: " + ", ".join(changed))
            control_row.update(status="unproven", reason=why)
            raise AcceptanceStop(f"pod_qf restore: {why}")
        found_b: dict[str, Any] = {}
        result["found_b"] = found_b
        outcome = cursefight.fight(screens, memory, [], plan.rules, found=found_b)
        result["outcome_b"] = outcome["outcome"]
        bad = [bar for bar in found_b.get("bars", []) if bar["address"] == x["address"]]
        if bad:
            control_row.update(status="failed", evidence=[bar["shot"] for bar in bad],
                               reason=f"{x['owner']} got a command bar without the click")
        else:
            control_row.update(status="awaiting image review",
                               observed={"bars": len(found_b.get("bars", []))})

    def _survive(self) -> None:
        """Raise every member's hit points and maximum to one value the field holds unsigned and
        signed alike, so the party outlasts the fight. The leg never saves."""
        from automap import amiga, amigaparty  # noqa: PLC0415
        from tools.amiga import amigatarget  # noqa: PLC0415

        target = amigatarget.connect_pipe(self.args.holder, amiga.MACHINES[self.route.game_key])
        try:
            party = amigaparty.read_party(target)
            if not party:
                raise AcceptanceStop("no party is readable for the survival write")
            written = []
            for member in party:
                hp, top = member.row.hp, member.row.hp_max
                value = (1 << (8 * min(hp.length, top.length) - 1)) - 1
                target.write(member.address + top.offset, value.to_bytes(top.length, "big"))
                target.write(member.address + hp.offset, value.to_bytes(hp.length, "big"))
                written.append({"name": member.name, "address": member.address, "value": value,
                                "hp_before": member.hp, "hp_max_before": member.hp_max})
            again = amigaparty.read_party(target)
            if not again or any((m.hp, m.hp_max) != (w["value"], w["value"])
                                for m, w in zip(again, written)):
                raise AcceptanceStop("the survival write did not read back")
        finally:
            target.close()
            self.game._pipe = None
        self.summary["fight"]["interventions"].append({"survival": written})
        self.log("survival", members=written)

    def _fight_bar(self, memory: Any) -> None:
        """What the leg does at the first command bar, before its key."""
        self.greyed_done = True
        self._greyed_check(memory)
        if self.fight.get("survive"):
            self._survive()

    def _walk_to_fight(self, plan: FightPlan, screens: Any, memory: Any) -> dict[str, Any]:
        """NP8 on the map, NP4 after a key that left the square as it was, until a screen in
        `plan.opens`; the walk's own screens get their answer, and any other screen restores the
        snapshot taken before the first step, at most `FIGHT_RESTORES` times."""
        self._game_section()
        self.game.snapshot(FIGHT_WALK_SNAPSHOT, self.args.holder)
        steps: list[dict[str, Any]] = []
        restores, key = 0, "NP8"

        def settled() -> tuple[str | None, Any]:
            end = self.clock() + FIGHT_STEP_SETTLE * 3
            while True:
                seen, shot = screens.look("walk")
                state = seen[0] if seen else None
                if state is not None or self.clock() >= end:
                    return state, shot
                self.sleep(2.0)

        for _ in range(FIGHT_WALK_STEPS):
            # A key only on the recognised map.
            screens.wait(("world",), 30)
            before = memory.fix()
            screens.press(key, "world")
            self.sleep(FIGHT_STEP_SETTLE)
            state, shot = settled()
            answered = 0
            while state in plan.walk_answers and answered < 4:
                screens.press(plan.walk_answers[state], state)
                answered += 1
                self.sleep(FIGHT_STEP_SETTLE)
                state, shot = settled()
            if state in plan.opens:
                steps.append({"key": key, "before": before, "met": state, "shot": str(shot)})
                return {"steps": steps, "met": state, "restores": restores}
            if state == "world":
                after = memory.fix()
                steps.append({"key": key, "before": before, "after": after})
                key = ("NP4" if key == "NP8" and before is not None and after is not None
                       and after[:2] == before[:2] else "NP8")
                continue
            if state is None:
                # No guard matched, or no frame was grabbed: nothing says what the key did.
                raise AcceptanceStop(f"the walk to a fight met no recognized screen; kept {shot}")
            if restores >= FIGHT_RESTORES:
                raise AcceptanceStop(f"the walk to a fight met {state}, which it does not answer; "
                                     f"kept {shot}")
            steps.append({"key": key, "before": before, "unanswered": str(shot)})
            self.game.restore(FIGHT_WALK_SNAPSHOT, self.args.holder)
            restores += 1
            key = "NP4"
            self.sleep(FIGHT_STEP_SETTLE)
        raise AcceptanceStop(f"{FIGHT_WALK_STEPS} walk keys met no fight")

    def _fight_entry(self, plan: FightPlan, screens: Any, memory: Any) -> dict[str, Any]:
        """The way into the title's fight, ending once the fight has begun."""
        from tools.amiga import curseadd, cursefight, ssbfight  # noqa: PLC0415

        walk = self.fight.get("walk") or {}
        if plan.entry == "tavern":
            steps = cursefight.walk(screens, memory, walk["place"], walk["route"])
            cursefight.reach_tavern(screens)
            if getattr(self.args, "watch_dip", False):
                self._game_section()
                self._stage_dip()
                # Wish polls through the fight start's mode changes, then the pipe is freed.
                screens.press_queued("P", "tavern")
                self._game_section()
            else:
                screens.press("P", "tavern")
            screens.sleep(cursefight.AFTER_KEY)
            return {"steps": steps}
        if plan.entry == "wander":
            gate = curseadd.bounded(lambda _h: memory.variable(ssbfight.GATE), memory.holder,
                                    self.left(cursefight.READ_LIMIT))
            if gate != ssbfight.GATE_ON:
                raise AcceptanceStop(f"the gate ${ssbfight.GATE:04X} reads {gate} in the running "
                                     f"game, not {ssbfight.GATE_ON}; no step was sent")
            return {"gate": gate, **ssbfight.wander(screens, memory, walk["place"], walk)}
        return self._walk_to_fight(plan, screens, memory)

    def run_fight(self) -> dict[str, Any]:
        """Load the pinned specimen, walk into a fight, check the greyed buttons at the first
        bar, answer every screen to the map logging the mode, read the party back, and halt."""
        from tools.amiga import curseadd, cursefight  # noqa: PLC0415

        result = self.summary["fight"]
        try:
            self._up()
            self._game_section()
            title = self._await_title()
            self.summary["mapping"]["title"] = row("awaiting image review", evidence=[title])
            self.run_phase(_fight_load(self.route, self.fight.get("place"), self.fight.get("loaded")))
            self.summary["mapping"]["load"] = row("awaiting image review")
            plan = fight_plan(self.route.title)
            memory = _fight_memory(self.args.holder, self.route)
            curseadd.bounded(lambda _h: memory.target(), memory.holder,
                             self.left(cursefight.READ_LIMIT))
            screens = _fight_screens(self, plan, memory)
            result["walk"] = self._fight_entry(plan, screens, memory)
            outcome = cursefight.fight(screens, memory, [], plan.rules, found=result["found"])
            result["outcome"] = outcome["outcome"]
            if self.watch_map and not self.map_hold_done:
                self.summary["watch_map"]["reason"] = (
                    "the last quick member never got a command bar, so the hold never ran")
            if not self.greyed_done:
                raise AcceptanceStop("the fight ended before a command bar showed")
            if self.press_off:
                self._pod_replay(plan, screens, memory)
            self._game_section()
            result["after"] = self._action_readback()
            if self.summary["fight_greyed"]["status"] == "failed":
                raise AcceptanceStop(f"fight_greyed failed: {self.summary['fight_greyed']['reason']}")
        except BaseException as exc:
            self.summary["failure"] = f"{type(exc).__name__}: {exc}"
            self.log("failure", error=self.summary["failure"], **guest_failure_fields(exc))
            greyed = self.summary["fight_greyed"]
            if greyed["status"] == "unproven" and not greyed.get("reason"):
                greyed["reason"] = self.summary["failure"]
            for names in WATCH_ROWS.values():
                for name in names:
                    held = self.summary.get(name)
                    if held is not None and held["status"] == "unproven" and not held["reason"]:
                        held["reason"] = self.summary["failure"]
        finally:
            self._cleanup()
            self._verify_no_write()
            (self.out / "summary.json").write_text(json.dumps(self.summary, indent=2, default=str) + "\n")
        return self.summary

    def _verify_no_write(self) -> None:
        """The fight leg saves nothing, so every fetched working disk has the hash this run's own
        manifest staged it with; another prepare of the same specimen stamps other dates."""
        result = self.summary.get("fight_no_write")
        if result is None:
            return
        hashes, changed, missing = {}, [], []
        for medium in self.route.media:
            fetched = self.info["media"].get(medium.key, {}).get("guest_working_sha256")
            hashes[medium.key] = {"staged": medium.sha256, "fetched": fetched}
            if fetched is None:
                missing.append(medium.key)
            elif fetched != medium.sha256:
                changed.append(medium.key)
        result["observed"] = hashes
        if changed:
            result.update(status="failed",
                          reason=f"working disk {', '.join(changed)} changed with no save made")
            self.summary["failure"] = self.summary["failure"] or f"fight_no_write: {result['reason']}"
        elif missing:
            result.update(status="unproven", reason=f"working disk {', '.join(missing)} was not fetched")
        else:
            result.update(status="passed", reason=None)

    def _reload_party(self) -> None:
        """Load the party into the restarted game as the run's start did, then leave Wish on the Automapper."""
        load = next(phase for phase in self.route.phases if phase.name == "load")
        # The restarted emulator is a new pipe peer; nothing cached from the first may be reused.
        self.game._pipe = None
        # The boot shows the same copy-protection page as the first one did, before the title.
        self._game_section()
        self._await_title()
        self.reconnect_limit = _phase_keys(load)
        try:
            self.run_phase(load, namespace="reconnect-load")
        finally:
            self.reconnect_limit = None
        self._map_section()

    def _stage_media(self) -> None:
        for medium in self.route.media:
            remote = self.game.remote_path(self.route.amiga_title.issue,
                                           self.args.holder, medium.key)
            self.game.put(medium.path, remote, timeout=self.left(60))
            self.remotes[medium.key] = remote
            self.info["media"][medium.key]["guest"] = remote

    def _up(self, restarts_emulator: bool = False) -> None:
        self._stage_media()
        values = {"sha": self.args.sha, "holder": self.args.holder,
                  "mute_proof": self.args.mute_proof,
                  "df0": None, "df1": None, "df2": None, "df3": None,
                  "game": self.route.game_key, "zip": str(self.zipped),
                  "zip_sha256": self.info.get("release_artifact", {}).get("sha256"),
                  "uae_option": list(self.route.amiga_title.options),
                  "travel_targets": [], "map_only": self.discovery,
                  "clear_quickfight": bool(getattr(self.args, "watch", False)),
                  "wait_lanes": getattr(self.args, "wait_lanes", 0), "keep_lanes": False,
                  "restarts_emulator": restarts_emulator}
        for index, key in enumerate(self.route.mounted):
            values[f"df{index}"] = self.remotes[key]
        drives = winwish.floppy_paths(argparse.Namespace(**values))
        self.launch = (tuple(drives), (*winwish.floppy_options(len(drives)),
                                       *winwish.uae_options(values["uae_option"])))
        receipt = winwish.up(self.guest, self.lane, argparse.Namespace(**values))
        self.pipe = _pipe_name(receipt.get("winuae") if isinstance(receipt, dict) else None)
        self.lanes = receipt.get("lanes") if isinstance(receipt, dict) else None
        if values["wait_lanes"]:
            # Waiting for a free lane is not route time.
            self._set_deadlines()
        self.booted = True
        self.game.holder = self.args.holder
        self.log("up", receipt=receipt)

    def _cleanup(self) -> None:
        self._await_queued_keys()
        if self.discovery:
            self._cleanup_discovery()
            return
        failures = ([f"restart stop: {self.restart_stop_error}"]
                    if self.restart_stop_error else [])
        if self.encounters_on:
            self._encounters_off(failures)
        if self.booted:
            try:
                self._game_section()
                self.game._pipe = None
            except Exception as exc:  # noqa: BLE001
                failures.append(f"pipe: {exc}")
            try:
                self.summary["cleanup"]["logs"] = winwish.collect_log(
                    self.guest, self.args.holder, self.out / "logs")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"logs: {exc}")
            for medium in self.route.media:
                if medium.key not in self.remotes:
                    continue
                try:
                    copied = self.out / f"working-{medium.key}.adf"
                    self.game.get(self.remotes[medium.key], copied, timeout=60)
                    self.info["media"][medium.key]["guest_working_sha256"] = digest(copied)
                    self.info["media"][medium.key]["guest_working_copy"] = str(copied)
                except Exception as exc:  # noqa: BLE001
                    failures.append(f"working medium {medium.key}: {exc}")
            try:
                self.summary["cleanup"]["down"] = winwish.down(
                    self.guest, self.lane, self.args.holder)
                self.down_done = True
            except Exception as exc:  # noqa: BLE001
                failures.append(f"down: {exc}")
                try:
                    self.summary["cleanup"]["down_retry"] = winwish.down(
                        self.guest, self.lane, self.args.holder)
                    self.down_done = True
                except Exception as retry:  # noqa: BLE001
                    failures.append(f"down retry: {retry}")
            try:
                status = self.lane.status(30)
                self.summary["cleanup"]["lane_status"] = status
                if self.args.holder in status:
                    failures.append(f"holder {self.args.holder} remains in lane status")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"lane status: {exc}")
        for medium in self.route.media:
            try:
                self.info["media"][medium.key]["source_after_sha256"] = digest(medium.path)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"source medium {medium.key}: {exc}")
        self.summary["cleanup"]["errors"] = failures
        try:
            self.log("cleanup", errors=failures)
        except OSError as exc:
            failures.append(f"event log: {exc}")

    def _cleanup_discovery(self) -> None:
        """Reserve teardown time before optional transfer of working media."""
        failures = []
        cleanup = self.summary["cleanup"]
        if self.encounters is not None:
            try:
                persistent = self.encounters.state.load()
                cleanup["encounters_before"] = persistent
                if persistent["on"] or persistent["rows"] or self.encounters_on:
                    self._encounters_off(failures)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"encounters: {exc}")
        if self.discovery_snapshot and self.summary["failure"]:
            try:
                if self.encounters is not None:
                    state = self.encounters.state.load()
                    if state["on"] or state["rows"]:
                        raise AcceptanceStop("cannot restore with encounter suppression outstanding "
                                             f"(on: {bool(state['on'])}, rows: {state['rows']})")
                self._game_section()
                self.game.restore(DISCOVERY_SNAPSHOT, self.args.holder)
                from automap import amiga  # noqa: PLC0415
                from tools.amiga import amigatarget  # noqa: PLC0415

                target = amigatarget.connect_pipe(self.args.holder,
                                                   amiga.MACHINES[self.route.game_key])
                try:
                    fix = target.fix()
                    geo = target.geo()
                    area = self._area_of(geo) if geo is not None else None
                    restored = {"area": area, "x": fix.x, "y": fix.y,
                                "facing": fix.facing} if fix is not None else None
                finally:
                    target.close()
                cleanup["restored_fix"] = restored
                if restored != {"area": 16, "x": 3, "y": 3, "facing": 2}:
                    raise AcceptanceStop(f"restored fix is not 16,3,3,S: {restored}")
                cleanup["restored"] = True
            except Exception as exc:  # noqa: BLE001
                failures.append(f"restore: {exc}")

        def allowed(timeout: float, reserve: float = 0) -> float:
            seconds = min(timeout, self.total_end - self.clock() - reserve)
            if seconds <= 0:
                raise RouteError("discovery cleanup has no time before the holder release reserve")
            return seconds

        if self.booted:
            try:
                self._game_section()
                self.game._pipe = None
            except Exception as exc:  # noqa: BLE001
                failures.append(f"pipe: {exc}")

            owner = self

            class BoundedLane:
                def stop(self, holder: str, timeout: float) -> Any:
                    return owner.lane.stop(holder, allowed(timeout, 60))

                def release(self, holder: str, timeout: float) -> Any:
                    return owner.lane.release(holder, allowed(timeout))

            bounded_guest = winwish.Guest(
                run=lambda command, timeout: self.guest.run(command, allowed(timeout, 120)))
            try:
                cleanup["down"] = winwish.down(bounded_guest, BoundedLane(), self.args.holder)
                self.down_done = True
            except Exception as exc:  # noqa: BLE001
                failures.append(f"down: {exc}")
            try:
                status = self.lane.status(allowed(30))
                cleanup["lane_status"] = status
                if self.args.holder in status:
                    failures.append(f"holder {self.args.holder} remains in lane status")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"lane status: {exc}")
            if not self.down_done or "lane_status" not in cleanup or self.args.holder in cleanup["lane_status"]:
                failures.append(f"holder {self.args.holder} release is unverified")
            for medium in self.route.media:
                if medium.key not in self.remotes:
                    failures.append(f"working medium {medium.key}: no staged copy")
                    continue
                try:
                    copied = self.out / f"working-{medium.key}.adf"
                    self.game.get(self.remotes[medium.key], copied, timeout=allowed(60))
                    self.info["media"][medium.key]["guest_working_sha256"] = digest(copied)
                    self.info["media"][medium.key]["guest_working_copy"] = str(copied)
                except Exception as exc:  # noqa: BLE001
                    failures.append(f"working medium {medium.key}: {exc}")
        for medium in self.route.media:
            try:
                after = digest(medium.path)
                self.info["media"][medium.key]["source_after_sha256"] = after
                if after != medium.sha256:
                    failures.append(f"source medium {medium.key} changed")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"source medium {medium.key}: {exc}")
        if self.clock() > self.total_end:
            failures.append("the 1800-second total budget was exceeded during cleanup")
        try:
            self.log("cleanup", errors=failures)
        except OSError as exc:
            failures.append(f"event log: {exc}")
        cleanup["errors"] = failures
        if failures:
            if self.summary["failure"] is None:
                self.summary["failure"] = "Cleanup: " + "; ".join(failures)
            discovery = self.summary["discovery"]
            discovery["status"] = "failed"
            discovery["reason"] = self.summary["failure"]

    def _capture_unknown_frames(self, state: str, prefix: str, end: float,
                                *, stop_guard: str | None = None) -> dict[str, Any]:
        frames = self.summary["discovery"]["evidence"]
        start = len(frames)
        spent_by_timeout = False
        for number in range(3):
            remaining = end - self.clock()
            if remaining <= 0:
                if len(frames) == start:
                    raise AcceptanceStop("no terminal pipe frame within five seconds")
                break
            raw = self.out / f"{prefix}-{number}.raw.png"
            crop = self.out / f"{prefix}-{number}.png"
            previous = self.game.last_shot
            try:
                exact = self.game.grab(state, raw, crop, remaining)
            except Exception as exc:
                if raw.is_file():
                    current = self.game.last_shot
                    partial = {"raw": str(raw), "crop": None,
                               "shot_source": current.copy() if isinstance(current, dict)
                               and current is not previous else None,
                               "error": f"{type(exc).__name__}: {exc}"}
                    frames.append(partial)
                    self.log("terminal_frame", **partial)
                if not isinstance(exc, ShotTimedOut):
                    raise
                # A slow round trip sends no key: grab again inside the same window.
                timeout = {"attempt": number + 1, "allowed": round(remaining, 3),
                           "error": f"{type(exc).__name__}: {exc}"}
                self.summary["discovery"].setdefault("shot_timeouts", []).append(timeout)
                self.log("terminal_shot_timeout", **timeout)
                if number == 2 or end - self.clock() <= 0:
                    # Frames already captured are kept; with none, stop as before.
                    if not any(frame["crop"] is not None for frame in frames[start:]):
                        raise
                    spent_by_timeout = True
                    break
                continue
            current = self.game.last_shot
            source = current.copy() if isinstance(current, dict) and current is not previous else None
            frame = {"raw": str(raw), "crop": str(crop) if exact else None,
                     "shot_source": source}
            frames.append(frame)
            self.log("terminal_frame", **frame)
            if exact and (source is None or source.get("source") != "winuae-pipe"
                          or type(source.get("pid")) is not int or source["pid"] <= 0
                          or type(source.get("counter")) is not int or source["counter"] <= 0):
                raise AcceptanceStop("exact terminal crop has no fresh valid pipe shot provenance")
            if exact and self.clock() <= end and stop_guard and self.guards(stop_guard, crop):
                return frame
        current_frames = frames[start:]
        if not current_frames or (self.clock() > end and not spent_by_timeout):
            raise AcceptanceStop("terminal pipe frames exceeded five seconds")
        exact_frames = [frame for frame in current_frames if frame["crop"] is not None]
        if not exact_frames:
            raise AcceptanceStop("no exact terminal crop; raw pipe frames retained")
        if stop_guard:
            raise AcceptanceStop(f"{stop_guard} was not recognized within three fresh pipe frames")
        return exact_frames[-1]

    def run_opening_second(self) -> dict[str, Any]:
        """Stop at the selected guarded page, then capture only its approved successor."""
        self.summary["discovery"] = row()
        self.summary["challenge_key_count"] = None
        self.summary["challenge_key_count_verified"] = False
        try:
            phase = _opening_first_phase(self.route)
            mode = getattr(self.args, "discover", None)
            if mode not in OPENING_MODES[1:]:
                raise AcceptanceStop("second opening discovery mode is required")
            if (getattr(self.guards, "rules", {}).get("ssb_opening_first") != OPENING_FIRST_RULE
                    or self.guards.rules.get("ssb_opening_second") != OPENING_SECOND_RULE):
                raise AcceptanceStop("opening discovery needs both independent exact two-box guards")
            if (mode == "ssb-opening-after-third"
                    and self.guards.rules.get("ssb_opening_third") != OPENING_THIRD_RULE):
                raise AcceptanceStop("third opening discovery needs the independent exact two-box guard")
            self._up()
            self._game_section()
            title = self._await("title", limit=300)
            self.summary["mapping"]["title"] = row("awaiting image review", evidence=[title])
            self.run_phase(phase)
            self._answer_journal()
            self._await("ssb_opening_first", limit=300)
            self._press("RET")
            first_start = self.clock()
            second = self._capture_unknown_frames(
                "ssb_opening_unknown", "opening", min(first_start + 5, self.route_end),
                stop_guard="ssb_opening_second")
            self._checkpoint("ssb_opening_second", None, second)
            if self.checkpoints.get("ssb_opening_second", {}).get(
                    "observed", {}).get("fix") is None:
                raise AcceptanceStop("the game fix was not readable")
            if mode in ("ssb-opening-after-second", "ssb-opening-after-third"):
                # Reconfirm the page after the delayed, non-atomic Wish checkpoint.
                self._await("ssb_opening_second", limit=30)
                self._press("RET")
                second_start = self.clock()
                following = self._capture_unknown_frames(
                    "ssb_opening_after_second_unknown", "after-second",
                    min(second_start + 5, self.route_end),
                    stop_guard="ssb_opening_third" if mode == "ssb-opening-after-third" else None)
                following_name = ("ssb_opening_third" if mode == "ssb-opening-after-third"
                                  else "ssb_opening_after_second")
                self._checkpoint(following_name, None, following)
                if self.checkpoints.get(following_name, {}).get(
                        "observed", {}).get("fix") is None:
                    raise AcceptanceStop("the game fix was not readable")
                if mode == "ssb-opening-after-third":
                    previous_shot = self.game.last_shot
                    confirmed = self._await("ssb_opening_third", limit=30)
                    receipt = confirmed.get("shot_source")
                    if (receipt is previous_shot or not isinstance(receipt, dict)
                            or receipt.get("source") != "winuae-pipe"
                            or type(receipt.get("pid")) is not int or receipt["pid"] <= 0
                            or type(receipt.get("counter")) is not int or receipt["counter"] <= 0):
                        raise AcceptanceStop("third opening reconfirmation has no fresh pipe receipt")
                    self._press("RET")
                    third_start = self.clock()
                    terminal = self._capture_unknown_frames(
                        "ssb_opening_after_third_unknown", "after-third",
                        min(third_start + 5, self.route_end))
                    self._checkpoint("ssb_opening_after_third", None, terminal)
                    if self.checkpoints.get("ssb_opening_after_third", {}).get(
                            "observed", {}).get("fix") is None:
                        raise AcceptanceStop("the game fix was not readable")
            self.summary["discovery"]["status"] = "awaiting image review"
            self.summary["discovery"]["reason"] = "Opening image identification and mapping remain unproven"
        except BaseException as exc:
            self.summary["failure"] = f"{type(exc).__name__}: {exc}"
            self.log("failure", error=self.summary["failure"], **guest_failure_fields(exc))
            self.summary["discovery"]["status"] = "failed"
            self.summary["discovery"]["reason"] = self.summary["failure"]
        finally:
            self._cleanup()
            (self.out / "summary.json").write_text(json.dumps(self.summary, indent=2, default=str) + "\n")
        return self.summary

    def run_opening_first(self) -> dict[str, Any]:
        """Stop after one RETURN on the independently pinned first opening page."""
        self.summary["discovery"] = row()
        self.summary["challenge_key_count"] = None
        self.summary["challenge_key_count_verified"] = False
        try:
            phase = _opening_first_phase(self.route)
            if getattr(self.args, "discover", None) != "ssb-opening-first":
                raise AcceptanceStop("opening discovery mode is required")
            if getattr(self.guards, "rules", {}).get("ssb_opening_first") != OPENING_FIRST_RULE:
                raise AcceptanceStop("opening discovery needs the independent exact two-box guard")
            self._up()
            self._game_section()
            title = self._await("title", limit=300)
            self.summary["mapping"]["title"] = row("awaiting image review", evidence=[title])
            self.run_phase(phase)
            self._answer_journal()
            self._await("ssb_opening_first", limit=300)
            self._press("RET")
            end = min(self.clock() + 5, self.route_end)
            frame = self._capture_unknown_frames("ssb_opening_unknown", "opening", end)
            self._checkpoint("ssb_opening_after_first", None, frame)
            if self.checkpoints.get("ssb_opening_after_first", {}).get(
                    "observed", {}).get("fix") is None:
                raise AcceptanceStop("the game fix was not readable")
            self.summary["discovery"]["status"] = "awaiting image review"
            self.summary["discovery"]["reason"] = "Opening image identification and mapping remain unproven"
        except BaseException as exc:
            self.summary["failure"] = f"{type(exc).__name__}: {exc}"
            self.log("failure", error=self.summary["failure"], **guest_failure_fields(exc))
            self.summary["discovery"]["status"] = "failed"
            self.summary["discovery"]["reason"] = self.summary["failure"]
        finally:
            self._cleanup()
            (self.out / "summary.json").write_text(json.dumps(self.summary, indent=2, default=str) + "\n")
        return self.summary

    def run_discovery(self) -> dict[str, Any]:
        """Walk to the east gate; `ssb-leave` observes the leave-town question,
        `ssb-leave-yes` answers it YES and checks the arrival in The Ruins, and
        `ssb-camp-load` then encamps, answers camp LOAD's question, picks the prepared
        slot and checks the reloaded party, stopping on the first unmeasured screen."""
        self.summary["discovery"] = row()
        self.summary["challenge_key_count"] = None
        self.summary["challenge_key_count_verified"] = False
        try:
            phases = _discovery_phases(self.route)
            from tools.amiga import maproute  # noqa: PLC0415

            mode = getattr(self.args, "discover", None)
            transition = _transition_phase(self.route) if mode in YES_MODES else None
            camp = maproute._ssb_camp() if mode == "ssb-camp-load" else None
            self._up()
            self._game_section()
            title = self._await("title", limit=300)
            self.summary["mapping"]["title"] = row("awaiting image review", evidence=[title])
            for name in ("load", "stationary", "walk"):
                self.run_phase(phases[name])
                self.summary["mapping"][name] = row("awaiting image review")
            if self.encounters is None or self.encounters_on:
                raise AcceptanceStop("terminal encounter suppression was not verified off")
            state = self.encounters.state.load()
            if state["on"] or state["rows"]:
                raise AcceptanceStop(f"terminal encounter suppression remains active: {state}")
            if self.checkpoints.get("ssb_facing_exit", {}).get("comparison", {}).get(
                    "status") != "awaiting image review":
                raise AcceptanceStop("terminal 15,8,E checkpoint is not verified")
            if transition is not None:
                # NP8 waits for the leave-town guard; Y goes only after it matches.
                self.run_phase(transition)
                self.summary["mapping"]["transition"] = row("awaiting image review")
                if camp is None:
                    self.summary["discovery"]["status"] = "awaiting image review"
                    self.summary["discovery"]["reason"] = "The Ruins arrival pair awaits image review"
                    return self.summary
                # E after a fresh `world` match; L only after `camp` matches, then each
                # later key only on its guarded screen.
                self.run_phase(camp)
                self.game.snapshot("ssb_camp_load_terminal", self.args.holder)
                return self._camp_reload()
            self.game.snapshot("ssb_leave_terminal", self.args.holder)
            self._press("NP8")
            # The five seconds count from the key, as in the opening modes, not from before
            # its round trip.
            terminal_start = self.clock()
            end = min(terminal_start + 5, self.route_end)
            frame = self._capture_unknown_frames("ssb_leave_unknown", "leave", end)
            discovery = self.summary["discovery"]
            self._checkpoint("ssb_leave_terminal", None, frame)
            discovery["status"] = "awaiting image review"
            discovery["reason"] = "Prompt identification and mapping remain unproven"
        except BaseException as exc:
            self.summary["failure"] = f"{type(exc).__name__}: {exc}"
            self.log("failure", error=self.summary["failure"], **guest_failure_fields(exc))
            self.summary["discovery"]["status"] = "failed"
            self.summary["discovery"]["reason"] = self.summary["failure"]
        finally:
            self._cleanup()
            (self.out / "summary.json").write_text(json.dumps(self.summary, indent=2, default=str) + "\n")
        return self.summary

    def run_title(self) -> dict[str, Any]:
        try:
            # A build that follows the lane's run receipt needs only this lane; an older one
            # gets every lane so no other run's emulator can take its pipe name while the game is stopped.
            self._up(restarts_emulator=True)
            self._game_section()
            title = self._await_title()
            self.summary["mapping"]["title"] = row("awaiting image review", evidence=[title])
            reconnect = self.leg == "reconnect"
            if not reconnect:
                _phase_map(self.route)
            for phase in self.route.phases:
                name = phase.name
                if reconnect and name != "load":
                    continue
                if name == "reopen_step":
                    self._map_section()
                    winwish.stop_wish(self.guest, self.args.holder)
                    self.wish_closed = True
                self.run_phase(phase)
                label = "reopen" if name == "reopen_step" else name
                if label in self.summary["mapping"]:
                    self.summary["mapping"][label] = row("awaiting image review")
                if name == "load" and not reconnect:
                    self.flag_controls()
            if not reconnect:
                for action in self.route.actions:
                    if action.enabled:
                        self.summary["actions"][action.kind]["reason"] = (
                            "pressed only on the persist leg")
            self._map_section()
            if reconnect and self.launch is None:
                # Found before the game is stopped, while it can still be left running.
                raise AcceptanceStop("the game's launch settings were not recorded")
            connected = self.out / "connected.png"
            winwish.shot(self.guest, self.args.holder, "wish", connected)
            self.lane.stop(self.args.holder, self.left(60))
            pictures = []
            for index, delay in enumerate((0, 15, 30)):
                if delay:
                    self.sleep(self.left(delay))
                path = self.out / f"disconnect-{index}.png"
                winwish.shot(self.guest, self.args.holder, "wish", path)
                pictures.append(str(path))
            self.summary["mapping"]["disconnect"] = row(
                "awaiting image review", evidence=[str(connected), *pictures])
            if not reconnect:
                return self.summary
            # The same lane and the same Wish window: only the game comes back.
            drives, options = self.launch
            started = self.lane.start(self.args.holder, *drives,
                                      timeout=self.left(winwish.START_SECONDS + 30), options=options)
            self.restarted = True
            reopened = _pipe_name(started)
            if self.lanes == "one":
                if reopened is None:
                    raise AcceptanceStop("the restarted game named no pipe")
                # Wish follows this holder's run receipt, so the pipe it will open is the one the guest records now.
                running = self.guest.lane_run(self.args.holder)
                if running is None or running[1] != reopened:
                    raise AcceptanceStop(
                        f"the restarted game opened pipe {reopened}, but the holder's run receipt names "
                        f"{running[1] if running else 'none'}")
            elif self.pipe is not None and reopened != self.pipe:
                raise AcceptanceStop(
                    f"the restarted game opened pipe {reopened}, not Wish's {self.pipe}")
            self._reload_party()
            self.sleep(self.left(ROSTER_SECONDS))
            back = self.out / "reconnected.png"
            winwish.shot(self.guest, self.args.holder, "wish", back)
            self.summary["mapping"]["reconnect"] = row(
                "awaiting image review", evidence=[str(back)])
        except BaseException as exc:
            self.summary["failure"] = f"{type(exc).__name__}: {exc}"
            self.log("failure", error=self.summary["failure"], **guest_failure_fields(exc))
            incomplete = next((name for name, result in self.summary["mapping"].items()
                               if result["status"] == "unproven"), None)
            if incomplete:
                self.summary["mapping"][incomplete]["reason"] = self.summary["failure"]
        finally:
            if self.restarted:
                # Cleanup copies the working ADFs, which a running game holds open.
                left = self.total_end - self.clock()
                try:
                    if left <= 0:
                        raise AcceptanceStop("no time is left to stop the restarted game")
                    self.lane.stop(self.args.holder, min(60, left))
                except Exception as exc:  # noqa: BLE001
                    self.restart_stop_error = str(exc)
            self._cleanup()
            (self.out / "summary.json").write_text(json.dumps(self.summary, indent=2, default=str) + "\n")
        return self.summary


def _pipe_name(receipt: object) -> str | None:
    """The `pipe=` value of a lane start receipt, or None when it has none."""
    found = re.search(r"\bpipe=(\S+)", receipt) if isinstance(receipt, str) else None
    return found.group(1) if found else None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", choices=("pool", "curse", "ssb", "darkness"), required=True)
    parser.add_argument("--discover", choices=(*LEAVE_MODES, *OPENING_MODES))
    parser.add_argument("--manifest", type=pathlib.Path, required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--holder", required=True)
    parser.add_argument("--mute-proof", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--deadline", type=int)
    parser.add_argument("--walk-tab", choices=WALK_TABS, default="editor",
                        help="the Wish tab left showing while the party walks")
    parser.add_argument("--leg", choices=LEGS, default="mapping",
                        help="mapping is the whole route and presses no action; persist loads, "
                             "presses the actions, saves to a free slot and loads it again; "
                             "reconnect loads the "
                             "party, stops the game, grabs Wish, starts the game again and "
                             "reloads; fight loads a pinned fight specimen, walks into a fight, "
                             "checks the action buttons are greyed at the first command bar and "
                             "plays the fight on QUICK, logging the game's mode on each screen")
    parser.add_argument("--watch", action="store_true",
                        help="fight leg: start Wish with the clear-quickfight preference ticked "
                             "and take the Automapper and Character Editor branches at CONTINUE BATTLE")
    parser.add_argument("--watch-dip", action="store_true",
                        help="with --watch, Curse only: stage QUICK on one member and start the "
                             "fight with the Automapper showing")
    parser.add_argument("--watch-map", action="store_true",
                        help="fight leg, with --watch: keep the Automapper showing from the last Q "
                             "to CONTINUE BATTLE, glancing at the game now and then")
    parser.add_argument("--press-quickfight-off", action="store_true",
                        help="fight leg, Pools of Darkness only: press Quickfight off at a second "
                             "member's bar and replay from before it without")
    parser.add_argument("--quickfight-control", action="store_true",
                        help="persist leg, Curse or Silver Blades, with --action quickfight alone: "
                             "stage quickfight 1, do not press Quickfight off, save and reload, "
                             "and read the byte back")
    parser.add_argument("--action", action="append", choices=ACTION_KINDS,
                        help="run only this enabled action; repeat for several (--leg persist only)")
    parser.add_argument("--wait-lanes", type=int, default=0, metavar="SECONDS",
                        help=f"wait up to this long (0 to {MAX_WAIT_LANES}) for a free lane; "
                             "the wait is not route time")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.deadline is None:
        args.deadline = _deadline_limit(args.discover, args.walk_tab)
    from tools.amiga.maproute import route_for  # noqa: PLC0415

    guest, lane, game = winwish.Guest(), WinGuest(), WinGuest()
    try:
        route, guards, zipped, info = preflight(args, guest=guest, route_for=route_for)
        controller = Controller(args, guest=guest, lane=lane, game=game, guards=guards,
                                route=route, zipped=zipped, info=info)
        result = (controller.run_opening_first() if args.discover == "ssb-opening-first"
                  else controller.run_opening_second() if args.discover in OPENING_MODES[1:]
                  else controller.run_discovery() if args.discover
                  else controller.run_persist() if args.leg == "persist"
                  else controller.run_fight() if args.leg == "fight" else controller.run_title())
    except (AcceptanceStop, RouteError, winwish.WinwishError, OSError, ValueError) as exc:
        print(f"winwishaccept: {exc}", file=sys.stderr)
        return 2
    return 1 if result["failure"] or result["cleanup"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
