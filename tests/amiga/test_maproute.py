"""The Amiga Wish-window routes stop before any screen sequence lacks evidence."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from tools.amiga import maproute, route_darkness
from tools.amiga.winuaesession import RouteError


def _manifest(title: str, root: Path) -> dict:
    keys = {
        "pool": ("disk1", "disk2", "save"),
        "curse": ("save", "diskb"),
        "ssb": ("df0", "df1"),
        "darkness": ("disk1", "disk3", "disk2"),
    }[title]
    disks = {key: {"path": str(root / f"{key}.adf"), "sha256": "a" * 64}
             for key in keys}
    if title == "pool":
        return {
            "title": title, "loaded_letter": "A", "disks": disks,
            "substitute": {"letter": "B",
                           "sha256": "4c2bf105215976eaafaa89f07a5da3e06ff838357e07eacd13afe0d1376fddf3"},
        }
    if title == "curse":
        return {
            "title": title, "loaded_letter": "B", "disks": disks,
            "substitute": {"letter": "F",
                           "sha256": "c88dd261fb83772128a76e34cf09dc83dc6d5039c60c031a1432df5e48e04896"},
        }
    if title == "ssb":
        return {
            "title": title, "loaded_letter": "D", "slot_letter": "D", "disks": disks,
            "state_a": {"area": 16, "x": 3, "y": 3, "facing": 2},
            "substitute": {"letter": "A", "sha256": "b" * 64},
        }
    disks["disk3"]["sha256"] = route_darkness.DARKNESS_DISK3_SHA256
    return {
        "title": title, "loaded_letter": "B", "disks": disks,
        "state_a": {"area": 2, "x": 1, "y": 2, "facing": 1},
    }


def _yulash_manifest(root: Path) -> dict:
    return {**_manifest("curse", root),
            "substitute": {"letter": "C", "sha256": maproute._CURSE_YULASH_SHA256},
            "state_a": {"area": 16, "x": 2, "y": 6, "facing": 1}}


@pytest.mark.parametrize("title,load_key,load_state", [
    ("pool", "A", "grid"),
    ("curse", "B", "loaded_menu"),
    ("ssb", "D", "loaded_menu"),
    ("darkness", "B", "disk2_prompt"),
])
def test_the_game_loads_the_prepared_slot_and_never_saves(
        title: str, load_key: str, load_state: str, tmp_path: Path):
    route = maproute.route_for(title, _manifest(title, tmp_path))

    assert route.loaded_slot == load_key
    assert route.phases[0].name == "load"
    assert any(step.key == load_key and step.state == load_state
               for step in route.phases[0].steps)
    assert all(step.kind != "write" for phase in route.phases for step in phase.steps)
    assert all(step[2] != "write" for step in route.amiga_title.route)
    assert route.provenance["source_slot"] != route.loaded_slot or title == "darkness"
    assert route.guard_path.is_absolute()


@pytest.mark.parametrize("title", ("pool", "curse", "ssb", "darkness"))
def test_every_title_with_a_measured_source_is_ready_and_the_tilverton_curse_save_is_not(
        title: str, tmp_path: Path):
    route = maproute.route_for(title, _manifest(title, tmp_path))
    phases = {phase.name: phase for phase in route.phases}

    assert set(phases) == {"load", "stationary", "walk", "transition", "reload",
                           "reopen_step"} | ({"outdoor"} if title in ("pool", "curse") else set()) | (
                               {"walkout"} if title == "pool" else set()) | (
                               {"village"} if title == "darkness" else set())
    if title == "curse":
        assert not phases["transition"].ready
        assert phases["transition"].reason in route.unresolved
        yulash = maproute.route_for("curse", _yulash_manifest(tmp_path))
        assert all(phase.ready for phase in yulash.phases)
        assert yulash.unresolved == ()
    else:
        assert all(phase.ready for phase in route.phases)
        assert route.unresolved == ()
    assert [action.kind for action in route.actions] == [
        "heal", "spells", "identify", "quickfight", "levelup"]
    assert {action.kind for action in route.actions if action.enabled} == (
        set() if title == "pool" else {"heal", "identify"} | EXTRA_ENABLED[title])


EXTRA_ENABLED = {"ssb": {"quickfight"}, "curse": {"quickfight"}, "darkness": {"spells"}}


def _enabled(title: str, tmp_path: Path) -> dict[str, maproute.Action]:
    route = maproute.route_for(title, _manifest(title, tmp_path))
    return {action.kind: action for action in route.actions if action.enabled}


@pytest.mark.parametrize("title", ("ssb", "darkness", "curse"))
def test_heal_and_identify_carry_the_measured_camp_routes(title: str, tmp_path: Path):
    actions = _enabled(title, tmp_path)

    heal, identify = actions["heal"], actions["identify"]
    assert [(s.kind, s.state, s.key) for s in heal.show.steps] == [
        ("key", "camp", "E"), ("select", "camp", None), ("key", "camp_sheet", "V")]
    assert (heal.show.initial_state, heal.show.steps[-1].checkpoint) == ("world", "heal_sheet")
    assert [(s.state, s.key) for s in heal.back.steps] == [("camp", "E"), ("world", "E")]
    assert heal.back.initial_state == "camp_sheet"
    assert [(s.kind, s.state, s.key) for s in identify.show.steps] == [
        ("key", "camp", "E"), ("select", "camp", None), ("key", "camp_sheet", "V"),
        ("key", "camp_items", "I")]
    assert identify.show.steps[-1].checkpoint == "identify_items"
    assert identify.back.initial_state == "camp_items"
    assert [(s.state, s.key) for s in identify.back.steps] == [
        ("camp_sheet", "E"), ("camp", "E"), ("world", "E")]


@pytest.mark.parametrize("title", ("ssb", "curse"))
def test_quickfight_off_visits_the_sheet_as_heal_does(title: str, tmp_path: Path):
    heal, qf = (_enabled(title, tmp_path)[k] for k in ("heal", "quickfight"))

    for mine, theirs in ((qf.show, heal.show), (qf.back, heal.back)):
        assert mine.initial_state == theirs.initial_state
        assert [(s.kind, s.state, s.key) for s in mine.steps] == [
            (s.kind, s.state, s.key) for s in theirs.steps]
    assert qf.selector == "controlled"


def test_pools_of_darkness_quickfight_stays_off_between_fights(tmp_path: Path):
    by_kind = {a.kind: a for a in maproute.route_for(
        "darkness", _manifest("darkness", tmp_path)).actions}
    assert not by_kind["quickfight"].enabled


def test_pools_of_darkness_spells_visit_the_cast_list(tmp_path: Path):
    spells = _enabled("darkness", tmp_path)["spells"]

    assert spells.show.initial_state == "world"
    assert [(s.kind, s.state, s.key) for s in spells.show.steps] == [
        ("key", "camp", "E"), ("select", "camp", None), ("key", "camp_magic", "M"),
        ("key", "camp_cast_5", "C")]
    assert spells.show.steps[-1].checkpoint == "spells_cast"
    assert spells.back.initial_state == "camp_cast_5"
    assert [(s.state, s.key) for s in spells.back.steps] == [
        ("camp_magic", "E"), ("camp", "E"), ("world", "E")]


@pytest.mark.parametrize("title", ("ssb", "darkness", "curse"))
def test_the_enabled_actions_wait_only_for_screens_the_title_guards(title: str, tmp_path: Path):
    actions = _enabled(title, tmp_path)
    route = maproute.route_for(title, _manifest(title, tmp_path))
    guards = json.loads(route.guard_path.read_text())["guards"]
    phases = [p for a in actions.values() for p in (a.show, a.back)]
    states = {p.initial_state for p in phases} | {s.state for p in phases for s in p.steps}

    assert states <= guards.keys()
    # The Pools of Darkness Cast list also matches camp_use_list.
    assert "camp_use_list" not in states


@pytest.mark.parametrize("title", ("pool", "curse", "ssb", "darkness"))
def test_the_actions_without_a_measured_route_stay_off_and_pool_has_no_camp_route(
        title: str, tmp_path: Path):
    route = maproute.route_for(title, _manifest(title, tmp_path))
    by_kind = {action.kind: action for action in route.actions}
    off = {"spells", "quickfight", "levelup"} - EXTRA_ENABLED.get(title, set())

    assert not any(by_kind[k].enabled for k in off)
    assert all(by_kind[k].show is None for k in off)
    if title == "pool":
        assert not any(action.enabled for action in route.actions)


def test_the_tilverton_curse_save_keeps_its_observe_only_outdoor_phase(tmp_path: Path):
    route = maproute.route_for("curse", _manifest("curse", tmp_path))

    assert [phase.name for phase in route.phases] == [
        "load", "outdoor", "transition", "stationary", "walk", "reload", "reopen_step"]
    assert route.phases[1].steps[0].kind == "observe"
    assert not route.phases[2].ready


@pytest.mark.parametrize("title", ("pool", "curse", "curse-yulash", "ssb", "darkness"))
def test_every_ready_step_has_an_existing_screen_guard_and_unique_checkpoint(
        title: str, tmp_path: Path):
    route = (maproute.route_for("curse", _yulash_manifest(tmp_path)) if title == "curse-yulash"
             else maproute.route_for(title, _manifest(title, tmp_path)))
    guards = json.loads(route.guard_path.read_text())["guards"]
    ready = [phase for phase in route.phases if phase.ready]
    states = {phase.initial_state for phase in ready}
    states.update(step.state for phase in ready for step in phase.steps)
    checkpoints = [step.checkpoint for phase in ready for step in phase.steps
                   if step.checkpoint]

    assert states <= guards.keys()
    assert len(checkpoints) == len(set(checkpoints))
    assert all(step.media in {disk.key for disk in route.media}
               for phase in ready for step in phase.steps if step.kind == "insert")


def test_silver_blades_replays_the_measured_new_verdigris_walk(tmp_path: Path):
    route = maproute.route_for("ssb", _manifest("ssb", tmp_path))
    phases = {phase.name: phase for phase in route.phases}
    walk = phases["walk"]

    assert phases["stationary"].ready and walk.ready
    assert [step.key for step in walk.steps if step.kind == "move"] == ["NP8"] * 17
    assert [step.expected.engine for step in walk.steps if step.checkpoint][-1] == {
        "area": 16, "x": 15, "y": 8, "facing": 1}
    assert walk.steps[0].kind == "snapshot"
    assert walk.steps[1].encounters is True
    assert walk.steps[-1].encounters is False


def test_an_unstarted_silver_blades_party_plays_its_opening_story_in_the_load(tmp_path: Path):
    manifest = {**_manifest("ssb", tmp_path), "opening_scene": True}
    route = maproute.route_for("ssb", manifest)
    load = route.phases[0]

    assert [(s.kind, s.state, s.key) for s in load.steps[5:]] == [
        ("key", "journal", "B"), ("answer", "treasure_bar", None),
        ("key", "treasure", "E"), ("key", "world", "N")]
    assert load.steps[-1].checkpoint == "loaded"
    assert route.amiga_title.wait_limits["treasure_bar"] == 300
    pages = [row for row in route.amiga_title.interstitials if row[0] == "continue"]
    assert [(row[1], row[3]) for row in pages] == [(("keys", "RET"), 12)]
    plain = maproute.route_for("ssb", _manifest("ssb", tmp_path))
    assert [s.state for s in plain.phases[0].steps[-1:]] == ["world"]


def test_a_different_source_party_does_not_gain_the_outdoor_claim(tmp_path: Path):
    manifest = _manifest("pool", tmp_path)
    manifest["substitute"] = {"letter": "F", "sha256": "b" * 64}

    route = maproute.route_for("pool", manifest)

    assert route.unresolved[0].startswith("Pool needs the registered outdoor source")


def test_manifest_media_and_slot_must_be_well_formed(tmp_path: Path):
    manifest = _manifest("darkness", tmp_path)
    manifest["loaded_letter"] = "BA"
    with pytest.raises(RouteError, match="loaded_letter"):
        maproute.route_for("darkness", manifest)
    manifest["loaded_letter"] = "B"
    manifest["disks"]["disk2"]["sha256"] = "unverified"
    with pytest.raises(RouteError, match="SHA-256"):
        maproute.route_for("darkness", manifest)


def test_route_values_cannot_be_mutated():
    with pytest.raises(dataclasses.FrozenInstanceError):
        maproute.Step("observe", "world").state = "title"


def test_silver_blades_transition_answers_the_guarded_leave_town_question(tmp_path: Path):
    route = maproute.route_for("ssb", _manifest("ssb", tmp_path))
    phases = {phase.name: phase for phase in route.phases}
    transition = phases["transition"]
    guards = json.loads(route.guard_path.read_text())["guards"]

    assert [phase.name for phase in route.phases][:4] == [
        "load", "stationary", "walk", "transition"]
    assert transition.ready and transition.initial_state == "world"
    assert [(s.kind, s.key, s.state, s.checkpoint) for s in transition.steps] == [
        ("move", "NP8", "leave_town", None),
        ("key", "Y", "world", "ssb_ruins_arrival")]
    expected = transition.steps[1].expected
    assert dict(expected.engine) == {"area": 32, "x": 11, "y": 2, "facing": 1}
    assert (expected.compare_to, expected.relation) == ("ssb_facing_exit", "area_changed")
    assert "leave_town" in guards
    assert not any("leave-town" in reason for reason in route.unresolved)
    assert phases["reload"].ready and phases["reopen_step"].ready


def test_silver_blades_camp_step_encamps_from_the_ruins_on_the_camp_guard(tmp_path: Path):
    route = maproute.route_for("ssb", _manifest("ssb", tmp_path))
    camp = maproute._ssb_camp()
    guards = json.loads(route.guard_path.read_text())["guards"]

    assert camp.ready and camp.initial_state == "world"
    assert [(s.kind, s.key, s.state, s.checkpoint) for s in camp.steps] == [
        ("key", "E", "camp", None)]
    assert "camp" in guards
    assert "camp" not in [phase.name for phase in route.phases]


def test_silver_blades_camp_load_answers_only_the_guarded_question(tmp_path: Path):
    route = maproute.route_for("ssb", _manifest("ssb", tmp_path))
    camp_load = maproute._ssb_camp_load()
    guards = json.loads(route.guard_path.read_text())["guards"]

    assert camp_load.ready and camp_load.initial_state == "camp"
    assert [(s.kind, s.key, s.state, s.checkpoint) for s in camp_load.steps] == [
        ("key", "L", "load_anyway", None),
        ("key", "Y", "load_picker", None)]
    assert {"load_anyway", "load_picker"} <= guards.keys()
    # The box covers the bar's question text, not only its YES/NO buttons, so the
    # treasure screen's YES/NO bar cannot match it.
    assert guards["load_anyway"]["box"] == [72, 404, 686, 426]
    assert guards["load_anyway"]["sha256"] != guards["camp"]["sha256"]
    assert "camp_load" not in [phase.name for phase in route.phases]


def test_silver_blades_camp_reload_replays_the_title_load_tail(tmp_path: Path):
    route = maproute.route_for("ssb", _manifest("ssb", tmp_path))
    reload = maproute._ssb_camp_reload()
    load = maproute._load("ssb", "D", opening_scene=True)

    assert reload.ready and reload.initial_state == "loaded_menu"
    assert [(s.kind, s.key, s.state) for s in reload.steps] == [
        (s.kind, s.key, s.state) for s in load.steps[5:]]
    final = reload.steps[-1]
    assert final.checkpoint == "ssb_camp_reloaded"
    assert dict(final.expected.engine) == {"area": 16, "x": 3, "y": 3, "facing": 2}
    assert (final.expected.compare_to, final.expected.relation) == (
        "ssb_ruins_arrival", "area_changed")
    assert "camp_reload" not in [phase.name for phase in route.phases]


def test_silver_blades_reload_goes_through_camp_load_and_the_prepared_slot(tmp_path: Path):
    route = maproute.route_for("ssb", _manifest("ssb", tmp_path))
    phases = {phase.name: phase for phase in route.phases}
    reload = phases["reload"]

    assert [phase.name for phase in route.phases][-2:] == ["reload", "reopen_step"]
    assert reload.steps == (*maproute._ssb_camp().steps, *maproute._ssb_camp_load().steps,
                            maproute.Step("key", "loaded_menu", key="D"),
                            *maproute._ssb_camp_reload().steps)
    assert [s.key for s in reload.steps if s.key] == list("ELYDBEN")
    reopen = phases["reopen_step"]
    assert [s.key for s in reopen.steps if s.key] == ["NP8"]
    step = next(s for s in reopen.steps if s.checkpoint)
    assert step.checkpoint == "ssb_reopen_step"
    assert dict(step.expected.engine) == {"area": 16, "x": 3, "y": 4, "facing": 2}
    assert (step.expected.compare_to, step.expected.relation) == (
        "ssb_camp_reloaded", "moved")


def test_no_action_line_is_listed_while_every_action_is_disabled(tmp_path: Path):
    route = maproute.route_for("pool", _manifest("pool", tmp_path))

    assert not any("action" in reason for reason in route.unresolved)


def test_pools_of_darkness_accepts_the_area_the_prepared_saves_record(tmp_path: Path):
    manifest = _manifest("darkness", tmp_path)
    assert maproute._specimen_gaps(
        "darkness", manifest, {}, maproute.route_for("darkness", manifest).media, "B") == ()
    media = maproute.route_for("darkness", manifest).media
    manifest["state_a"] = {"area": 2, "x": 2, "y": 2, "facing": 1}
    assert maproute._specimen_gaps("darkness", manifest, {}, media, "B")
    manifest["state_a"] = {"area": 21, "x": 1, "y": 2, "facing": 1}
    assert maproute._specimen_gaps("darkness", manifest, {}, media, "B")


#: Each route key in order, as (phase, key, screen awaited after it, capture frame showing that
#: screen). The frames are the WinUAE capture boots' own, cut to the Amiga screen and kept as
#: `amiga-grab-crops/<run>__<frame>.png`; None where the boot never pressed that key. A frame
#: from the first load stands in for the same screen after a restart. A frame naming its own
#: run (`<run>__<frame>`) comes from a later capture boot of the same title.
#: The walk-out from 14,1 facing west to the travel grid, as capture boot wish1-pwalk1 pressed it.
_POOL_WALKOUT_KEYS = (
    ("walkout", "NP8", "world", "wish1-pwalk1__17-w_NP8_2"),
    ("walkout", "NP8", "world", "wish1-pwalk1__18-w_NP8_3"),
    ("walkout", "NP8", "world", "wish1-pwalk1__19-w_NP8_4"),
    ("walkout", "NP4", "world", "wish1-pwalk1__20-t_NP4"),
    ("walkout", "NP8", "world", "wish1-pwalk1__21-s_NP8"),
    ("walkout", "NP2", "world", "wish1-pwalk1__22-about_NP2"),
    ("walkout", "NP8", "harbour_master", "wish1-pwalk1__24-harbour_b"),
    ("walkout", "W", "harbour_payer", "wish1-pwalk1__25-west"),
    ("walkout", "RET", "world", "wish1-pwalk1__27-pay_b"),
    ("walkout", "NP6", "world", "wish1-pwalk1__28-e_NP6"),
    ("walkout", "NP8", "world", "wish1-pwalk1__29-e_NP8_1"),
    ("walkout", "NP8", "world", "wish1-pwalk1__30-e_NP8_2"),
    ("walkout", "NP8", "world", "wish1-pwalk1__31-e_NP8_3"),
    ("walkout", "NP8", "continue", "wish1-pwalk1__33-board_b"),
    ("walkout", "RET", "boat_question", "wish1-pwalk1__35-sail_b"),
    ("walkout", "S", "grid", "wish1-pwalk1__37-stay_b"),
)
_POOL_KEYS = (
    ("load", "RET", "party_menu", "06-wait3"), ("load", "L", "save_path", "07-L"),
    ("load", "RET", "load_picker", "08-save_path"), ("load", "A", "grid", "10-after_A"),
    ("load", "V", "sheet", "11-V"), ("load", "E", "grid", "12-E"),
    ("outdoor", "NP8", "grid", "13-grid_north"),
    ("transition", "NP2", "boat_question", "14-boat"),
    ("transition", "T", "world", "16-newphlan_b"),
    ("stationary", "NP4", "world", "17-turn_NP4"), ("stationary", "NP4", "world", "18-turn_NP4"),
    ("stationary", "NP6", "world", "19-turn_NP6"), ("stationary", "NP6", "world", "20-turn_NP6"),
    ("walk", "NP8", "world", "21-walk_NP8_1"), ("walk", "NP8", "world", "22-walk_NP8_2"),
    ("walk", "NP8", "world", "23-walk_NP8_3"), ("walk", "NP6", "world", "24-turn_NP6"),
    ("walk", "NP6", "world", "25-turn_NP6"), ("walk", "NP8", "world", "26-walk_NP8_4"),
    ("reload", "E", "camp", "27-camp"), ("reload", "S", "camp_save_picker", "28-save"),
    ("reload", "C", "quit_prompt", "30-save_C_b"), ("reload", "Y", "cli", "31-afterY_t5"),
    ("reload", "PROGRAM", "title", "40-menu2"), ("reload", "RET", "party_menu", "41-menu2b"),
    ("reload", "L", "save_path", "42-L2"), ("reload", "RET", "load_picker", "43-path2"),
    ("reload", "A", "grid", "46-reloaded"),
    ("reopen_step", "NP8", "grid", "wish1-pwalk1__12-grid_north"),
    ("reopen_step", "NP2", "boat_question", "wish1-pwalk1__14-boat_b"),
    ("reopen_step", "T", "world", None),
    ("reopen_step", "NP8", "world", "wish1-pwalk1__16-w_NP8_1"),
    *_POOL_WALKOUT_KEYS,
)
_CURSE_KEYS = (
    ("load", "L", "load_picker", "06-L"), ("load", "B", "loaded_menu", "08-menu"),
    ("load", "V", "sheet", "09-V"), ("load", "E", "loaded_menu", "10-E"),
    ("load", "B", "world", "11-B"),
    ("stationary", "NP4", "world", "12-turn_NP4"), ("stationary", "NP4", "world", "13-turn_NP4"),
    ("stationary", "NP6", "world", "14-turn_NP6"), ("stationary", "NP6", "world", "15-turn_NP6"),
    ("walk", "NP4", "world", "16-w_NP4"), ("walk", "NP4", "world", "17-w_NP4"),
    ("walk", "NP8", "world", "18-w_NP8_1"), ("walk", "NP8", "world", "19-w_NP8_2"),
    ("walk", "NP6", "world", "20-w_NP6"), ("walk", "NP6", "world", "21-w_NP6"),
    ("walk", "NP8", "yulash_checkpoint", "22-w_NP8_3"), ("walk", "M", "world", "23-answer_M"),
    ("walk", "NP8", "world", "24-w_NP8_4"),
    ("transition", "NP4", "world", "25-t_NP4"), ("transition", "NP4", "world", "26-t_NP4"),
    ("transition", "NP8", "world", "27-t_NP8_1"), ("transition", "NP8", "world", "28-t_NP8_2"),
    ("transition", "NP8", "dalelands", "29-t_NP8_3"),
    ("outdoor", "E", "yulash_arrival", "30-enter"), ("outdoor", "S", "world", "31-sneak"),
    ("reload", "E", "camp", "32-camp"), ("reload", "S", "camp_save_picker", "33-camp_S"),
    ("reload", "F", "exit_game", "34-save_F"), ("reload", "Y", "reboot", "36-afterY_5"),
    ("reload", "RESET", "title", "05-after_wheel"), ("reload", "L", "load_picker", "06-L"),
    ("reload", "B", "loaded_menu", "08-menu"), ("reload", "B", "world", "11-B"),
    ("reopen_step", "NP4", "world", None), ("reopen_step", "NP4", "world", None),
    ("reopen_step", "NP8", "world", None),
)
#: The Pools of Darkness village capture boot's own crops, kept with its run outside the crop
#: folders the guard maps label; a frame named with `/` is under the acceptance cache folder.
_PODCAP = "WISH-396/podcap1/shots"
_DARKNESS_KEYS = (
    ("load", "P", "party_menu", "05-esc3"), ("load", "L", "load_from", "06-L"),
    ("load", "P", "load_picker", "07-P"), ("load", "B", "disk2_prompt", "09-prompt"),
    ("load", "SPACE", "loaded_menu", "10-space"), ("load", "V", "sheet", "12-V"),
    ("load", "E", "loaded_menu", "13-E"), ("load", "B", "journal", "14-B"),
    ("load", "X", "journal_answer", "15-X"), ("load", "RET", "world", "16-ret"),
    ("stationary", "NP4", "world", "17-turn_NP4"), ("stationary", "NP4", "world", "18-turn_NP4"),
    ("stationary", "NP6", "world", "19-turn_NP6"), ("stationary", "NP6", "world", "20-turn_NP6"),
    ("walk", "NP8", "world", "21-w_NP8_1"), ("walk", "NP8", "world", "22-w_NP8_2"),
    ("walk", "NP4", "world", "23-w_NP4"), ("walk", "NP4", "world", "24-w_NP4"),
    ("walk", "NP8", "world", "25-w_NP8_3"), ("walk", "NP8", "world", "26-w_NP8_4"),
    ("transition", "E", "camp", "27-camp"), ("transition", "L", "load_anyway", "28-camp_L"),
    ("transition", "Y", "load_from", "29-Y"), ("transition", "P", "load_picker", "30-P"),
    ("transition", "D", "loaded_menu", "31-D"), ("transition", "B", "world", "33-B"),
    ("transition", "NP8", "world", "34-ov_NP8_1"), ("transition", "NP8", "world", "35-ov_NP8_2"),
    ("transition", "NP8", "world", "36-ov_NP8_3"), ("transition", "NP4", "yes_no", "37-ov_NP4"),
    ("transition", "Y", "mulmaster_guards", "38-enterY"), ("transition", "M", "world", "39-M"),
    ("reload", "E", "camp", "40-camp"), ("reload", "L", "load_anyway", "41-camp_L"),
    ("reload", "Y", "load_from", "42-Y"), ("reload", "P", "load_picker", "43-P"),
    ("reload", "B", "loaded_menu", "45-after_B"), ("reload", "B", "world", "46-B"),
    ("reopen_step", "NP8", "world", "47-reopen_NP8"),
    ("village", "E", "camp", "27-camp"), ("village", "L", "load_anyway", "28-camp_L"),
    ("village", "Y", "load_from", "29-Y"), ("village", "P", "load_picker", "30-P"),
    ("village", "D", "loaded_menu", "31-D"), ("village", "B", "world", "33-B"),
    ("village", "NP8", "world", f"{_PODCAP}/23-ov_NP8_1"),
    ("village", "NP8", "world", f"{_PODCAP}/24-ov_NP8_2"),
    ("village", "NP4", "world", f"{_PODCAP}/25-ov_NP4_3"),
    ("village", "NP4", "world", f"{_PODCAP}/26-ov_NP4_4"),
    ("village", "NP4", "world", f"{_PODCAP}/27-ov_NP4_5"),
    ("village", "NP4", "yes_no", f"{_PODCAP}/28-ov_NP4_6"),
    ("village", "Y", "continue", f"{_PODCAP}/31-afterY_9"),
    ("village", "RET", "world", f"{_PODCAP}/36-ret1"),
)
_CAPTURES = {"pool": ("wish1-pcap1", _POOL_KEYS), "curse": ("wish1-cccap1", _CURSE_KEYS),
             "darkness": ("wish1-cdcap1", _DARKNESS_KEYS)}


def _capture_route(title: str, root: Path):
    return maproute.route_for("curse", _yulash_manifest(root)) if title == "curse" else (
        maproute.route_for(title, _manifest(title, root)))


def _route_keys(route) -> list[tuple[str, str, str]]:
    keys = []
    for phase in route.phases:
        for step in phase.steps:
            if step.kind == "type":
                keys.append((phase.name, "".join(step.keys).replace("RET", ""), step.state))
            elif step.kind == "reset":
                keys.append((phase.name, "RESET", step.state))
            elif step.kind in ("key", "turn", "move", "insert"):
                keys.append((phase.name, step.key, step.state))
    return keys


@pytest.mark.parametrize("title", ("pool", "curse", "darkness"))
def test_each_route_presses_the_capture_boots_keys_and_waits_for_their_screens(
        title: str, tmp_path: Path):
    route = _capture_route(title, tmp_path)

    assert _route_keys(route) == [(phase, key, state) for phase, key, state, _ in _CAPTURES[title][1]]
    assert route.unresolved == ()


def test_the_pool_reload_saves_to_c_quits_and_types_program_at_the_prompt(tmp_path: Path):
    route = maproute.route_for("pool", _manifest("pool", tmp_path))
    reload = {phase.name: phase for phase in route.phases}["reload"]
    typed = next(step for step in reload.steps if step.kind == "type")

    assert typed.keys == ("P", "R", "O", "G", "R", "A", "M", "RET")
    assert (typed.screen, typed.state, typed.relaunch) == ("cli", "title", True)
    assert reload.pages == ("wheel", "save_path")
    loaded = route.phases[0].steps[3]
    assert (dict(loaded.expected.engine), dict(loaded.expected.window)) == (
        {"outdoors": True, "facing": 1}, {"x": 7, "y": 29})
    final = reload.steps[-1]
    assert (final.checkpoint, final.expected.compare_to, final.expected.relation) == (
        "pool_reloaded", "pool_walk_end", "area_changed")


def test_the_curse_reload_exits_the_game_and_soft_resets_the_amiga(tmp_path: Path):
    route = maproute.route_for("curse", _yulash_manifest(tmp_path))
    reload = {phase.name: phase for phase in route.phases}["reload"]
    reset = next(step for step in reload.steps if step.kind == "reset")

    assert (reset.state, reset.relaunch) == ("title", True)
    assert reload.pages == ("front_end", "intro")
    assert route.amiga_title.wait_limits["title"] == route.amiga_title.title_limit
    world = next(s for p in route.phases for s in p.steps if s.checkpoint == "curse_world")
    assert dict(world.expected.engine) == {"world_map": True, "world_node": 10}
    assert world.expected.relation == "view_changed"
    assert dict(route.phases[0].steps[-1].expected.engine) == {
        "area": 16, "x": 2, "y": 6, "facing": 1}


def test_a_curse_yulash_save_without_its_square_is_not_the_measured_source(tmp_path: Path):
    manifest = {**_yulash_manifest(tmp_path), "state_a": {"area": 16, "x": 0, "y": 6, "facing": 1}}
    route = maproute.route_for("curse", manifest)

    assert route.unresolved[0].startswith("Curse needs the registered Yulash slot C")


def test_pools_of_darkness_loads_into_geo21_and_keeps_the_overland_bytes(tmp_path: Path):
    route = maproute.route_for("darkness", _manifest("darkness", tmp_path))
    steps = [s for p in route.phases for s in p.steps if s.checkpoint]
    loaded = next(s for s in steps if s.checkpoint == "loaded")

    assert dict(loaded.expected.engine) == {"area": 33, "x": 1, "y": 2, "facing": 1}
    overland = [s for s in steps if s.checkpoint.startswith("pod_overland")]
    assert [s.checkpoint for s in overland] == [
        "pod_overland", "pod_overland_1", "pod_overland_2", "pod_overland_3", "pod_overland_4"]
    assert all(s.expected is None and s.reads == maproute._POD_OVERLAND for s in overland)
    mulmaster = next(s for s in steps if s.checkpoint == "pod_mulmaster")
    assert dict(mulmaster.expected.engine) == {"area": 19, "x": 0, "y": 3, "facing": 1}


def test_pools_of_darkness_reads_the_area_id_in_mulmaster_aerie_and_the_unnamed_village(
        tmp_path: Path):
    """GEO13 is Mulmaster's and Zhentil Keep's map, and GEO14 no area names, so only the game's
    own area byte, data hunk +0x7A0A, says which place each checkpoint stands in."""
    route = maproute.route_for("darkness", _manifest("darkness", tmp_path))
    steps = {s.checkpoint: s for p in route.phases for s in p.steps if s.checkpoint}
    area_id = (maproute.Read("area_id", "base", 0x7A0A, 1),)

    assert [name for name, s in steps.items() if s.reads == area_id] == [
        "pod_mulmaster", "pod_reloaded", "pod_village"]
    assert [p.name for p in route.phases][-2:] == ["reopen_step", "village"]
    village = steps["pod_village"]
    assert dict(village.expected.engine) == {"area": 20, "x": 5, "y": 7, "facing": 1}
    assert (village.expected.compare_to, village.expected.relation) == (
        "pod_reopen_step", "area_changed")
    phase = next(p for p in route.phases if p.name == "village")
    assert [s.kind for s in phase.steps].count("encounters") == 2
    walk = [s for s in phase.steps if s.kind == "move"]
    assert [s.key for s in walk] == ["NP8", "NP8", "NP4", "NP4", "NP4", "NP4"]


def test_the_whole_pools_of_darkness_route_fits_its_own_key_limit(tmp_path: Path):
    from types import SimpleNamespace

    from tools.amiga import winwishaccept

    route = maproute.route_for("darkness", _manifest("darkness", tmp_path))
    keys = sum(1 for phase in route.phases for step in phase.steps
               if step.kind in ("key", "turn", "move", "insert"))
    cap = winwishaccept.ORDINARY_MAPPING_COMMANDS["darkness"]

    assert cap == keys > winwishaccept.MAX_MAPPING_COMMANDS
    runner = SimpleNamespace(reconnect_limit=None, args=SimpleNamespace(discover=None),
                             route=SimpleNamespace(title="darkness"), mapping_commands=0)
    for _ in range(keys):
        winwishaccept.Controller._count(runner)
    with pytest.raises(winwishaccept.AcceptanceStop, match=f"{cap}-command mapping cap"):
        winwishaccept.Controller._count(runner)


def _kept_crops(prefix: str):
    from tools.registry import scratch

    return scratch.cache_dir("acceptance") / "amiga-grab-crops", prefix


def _exported_guards(title: str, tmp_path: Path):
    from tools.amiga import guardmaps, screens

    out = tmp_path / f"guards-{title}"
    maps = Path(guardmaps.__file__).parent
    assert guardmaps.main(["--maps", str(maps), "export", "--title", title, "--out", str(out)]) == 0
    return screens.PixelGuards(out / "guards.json")


@pytest.mark.parametrize("title", ("pool", "curse", "darkness"))
def test_every_screen_a_route_waits_for_matches_the_capture_frame_that_showed_it(
        title: str, tmp_path: Path):
    """Reads the capture boots' frames, so it skips on a machine without them."""
    crops, prefix = _kept_crops(_CAPTURES[title][0])
    frames = [(state, crops.parent / f"{frame}.png" if "/" in frame
               else crops / (f"{frame}.png" if "__" in frame else f"{prefix}__{frame}.png"))
              for _, _, state, frame in _CAPTURES[title][1] if frame]
    if not all(path.is_file() for _, path in frames):
        pytest.skip(f"the {title} capture frames are not on this machine")
    guards = _exported_guards(title, tmp_path)

    assert [(state, path.name) for state, path in frames if not guards(state, path)] == []


#: Each guard the capture boots added, and every capture frame of its title that shows it.
_NEW_GUARDS = {
    "pool": {"grid": {"10-after_A", "12-E", "13-grid_north", "46-reloaded"},
             "boat_question": {"14-boat"},
             "cli": {"31-afterY_t2", "31-afterY_t5", "31-afterY_t10", "31-afterY_t20"}},
    "curse": {"yulash_checkpoint": {"22-w_NP8_3"}, "dalelands": {"29-t_NP8_3"},
              "yulash_arrival": {"30-enter"},
              "reboot": {"35-exitY", "36-afterY_5", "37-afterY_8", "38-afterY_12", "39-stop1",
                         "40-stop2", "41-stop3"}},
    "darkness": {"load_anyway": {"28-camp_L", "41-camp_L"}, "mulmaster_guards": {"38-enterY"}},
}


@pytest.mark.parametrize("title", ("pool", "curse", "darkness"))
def test_each_new_guard_matches_only_the_capture_frames_that_show_its_screen(
        title: str, tmp_path: Path):
    """Reads the capture boots' frames, so it skips on a machine without them."""
    crops, prefix = _kept_crops(_CAPTURES[title][0])
    frames = sorted(crops.glob(f"{prefix}__*.png"))
    if len(frames) < 40:
        pytest.skip(f"the {title} capture frames are not on this machine")
    guards = _exported_guards(title, tmp_path)

    for state, wanted in _NEW_GUARDS[title].items():
        assert {path.stem.split("__", 1)[1] for path in frames if guards(state, path)} == wanted, state


#: Capture boot wish1-pwalk1's frames of the screens the Pool walk-out waits on: every frame of
#: that boot each guard matches, the two harbour guards included.
_WALKOUT_GUARDS = {
    "harbour_master": {"24-harbour_b"},
    "harbour_payer": {"25-west"},
    "continue": {"33-board_b"},
    "boat_question": {"14-boat_b", "35-sail_b"},
    "grid": {"12-grid_north", "36-stay", "37-stay_b"},
}


def test_the_harbour_guards_match_only_the_walkout_frames_that_show_their_screens(tmp_path: Path):
    """Reads capture boot wish1-pwalk1's frames, so it skips on a machine without them."""
    crops, prefix = _kept_crops("wish1-pwalk1")
    frames = sorted(crops.glob(f"{prefix}__*.png"))
    if len(frames) < 36:
        pytest.skip("the Pool walk-out capture frames are not on this machine")
    guards = _exported_guards("pool", tmp_path)

    for state, wanted in _WALKOUT_GUARDS.items():
        assert {path.stem.split("__", 1)[1] for path in frames if guards(state, path)} == wanted, state


def test_the_pool_walkout_buys_west_and_sails_from_the_pier_to_the_grids_dock(tmp_path: Path):
    route = maproute.route_for("pool", _manifest("pool", tmp_path))
    names = [phase.name for phase in route.phases]
    walkout = route.phases[-1]
    checkpoints = {step.checkpoint: step.expected for step in walkout.steps if step.checkpoint}

    assert names[-2:] == ["reopen_step", "walkout"]
    assert walkout.initial_state == route.phases[-2].steps[-1].state == "world"
    assert (walkout.steps[0].kind, walkout.steps[0].snapshot) == ("snapshot", "pool_harbour")
    # The harbour master answers only a party stepping north onto 11,1 from 11,2.
    assert dict(checkpoints["pool_harbour_approach"].engine) == {
        "area": 0, "x": 11, "y": 2, "facing": 2}
    assert dict(checkpoints["pool_harbour_master"].engine) == {
        "area": 0, "x": 11, "y": 1, "facing": 0}
    assert checkpoints["pool_harbour_door"].compare_to == "pool_reopen_step"
    keyed = [(step.key, step.state) for step in walkout.steps if step.kind == "key"]
    assert keyed == [("W", "harbour_payer"), ("RET", "world"), ("RET", "boat_question"),
                     ("S", "grid")]
    landed = checkpoints["pool_walkout_grid"]
    assert (dict(landed.engine), dict(landed.window)) == (
        {"outdoors": True, "facing": 1}, {"x": 7, "y": 29})
    assert (landed.compare_to, landed.relation) == ("pool_pier", "view_changed")
    switched = False
    for step in walkout.steps:
        if step.kind == "encounters":
            switched = step.encounters
        elif step.kind == "key":
            assert not switched, f"{step.key} is pressed with the encounter switch on"
    assert not switched


def test_the_walkout_landing_passes_with_the_pier_map_still_resident(tmp_path: Path):
    """The pier and grid readings of live run pool-walkout2-rerun: sailing out leaves New
    Phlan's map block resident, so only the view and the dock square tell the landing apart."""
    from tests.amiga import test_winwishaccept as driver
    from tools.amiga import winwishaccept

    route = maproute.route_for("pool", _manifest("pool", tmp_path))
    landed = next(step.expected for step in route.phases[-1].steps
                  if step.checkpoint == "pool_walkout_grid")
    new_phlan = "4d2541a2db2e3c3af90a9f1de437e2483146be72a91a766f7b970aec9d2db326"
    controller = winwishaccept.Controller(
        driver._args(tmp_path), guest=object(), lane=object(), game=driver.FakeGame(),
        guards=object(), route=driver._route(), zipped=tmp_path / "build.zip",
        info={"media": {}}, clock=driver.FakeClock())
    controller.checkpoints["pool_pier"] = {"observed": {
        "fix": {"x": 14, "y": 1, "facing": 1, "outdoors": False, "world_map": False,
                "window": None, "heading": None, "area": 0},
        "geo_sha256": new_phlan}}
    grid = {"fix": {"x": 7, "y": 29, "facing": None, "outdoors": True, "world_map": False,
                    "window": 1, "heading": 2, "area": 0},
            "geo_sha256": new_phlan}

    assert controller._compare_checkpoint("pool_walkout_grid", landed, grid)["status"] == (
        "awaiting image review")
    still_indoors = {**grid, "fix": {**grid["fix"], "outdoors": False}}
    assert controller._compare_checkpoint(
        "pool_walkout_grid", landed, still_indoors)["status"] == "failed"


def test_only_a_title_whose_reload_restarts_the_game_waits_the_boots_title_limit_for_the_title(
        tmp_path: Path):
    from tools.amiga import route_silver_blades

    ssb = maproute.route_for("ssb", _manifest("ssb", tmp_path)).amiga_title
    assert ssb.wait_limits == route_silver_blades.published_title("D").wait_limits
    assert "title" not in ssb.wait_limits
    for title in ("pool", "darkness"):
        route = maproute.route_for(title, _manifest(title, tmp_path)).amiga_title
        assert route.wait_limits["title"] == route.title_limit
    curse = maproute.route_for("curse", _yulash_manifest(tmp_path)).amiga_title
    assert curse.wait_limits["title"] == curse.title_limit


def _media_with(tmp_path: Path, key: str, slots: tuple[tuple[str, str], ...] = ()):
    """A blank AmigaDOS disk holding the named (directory, file) pairs, as the save disk `key`."""
    from goldbox.amiga_adf import AmigaDisk

    disk = AmigaDisk.blank()
    for directory in sorted({d for d, _ in slots if d}):
        disk.make_dir(directory)
    for directory, name in slots:
        disk.write_file(f"{directory}/{name}", b"x")
    path = tmp_path / f"{key}.adf"
    disk.save(path)
    return (maproute.Media(key, path, "a" * 64),)


@pytest.mark.parametrize("title,key,files,expected", [
    # Pool: D first; A is loaded and C is the reload phase's own save letter.
    ("pool", "save", (), "D"),
    ("pool", "save", (("", "savgamD.dat"),), "E"),
    ("pool", "save", tuple(("", f"savgam{c}.dat") for c in "DEFGHIJ"), None),
    ("curse", "save", (), "G"),
    ("curse", "save", (("/SAVE", "savgamG.dat"),), "H"),
    ("curse", "save", tuple(("/SAVE", f"savgam{c}.dat") for c in "GHIJ"), None),
    # Silver Blades: E first, because its camp save letter D is the loaded slot.
    ("ssb", "df0", (), "E"),
    ("darkness", "disk3", (("/SAVE", "savgamG.pty"),), "H"),
    ("darkness", "disk3", (("/SAVE", "savgamG.pty"), ("/SAVE", "savgamH.pty")), None),
])
def test_persist_letter_skips_the_loaded_reload_and_present_letters(
        title: str, key: str, files, expected, tmp_path: Path):
    if title in ("curse", "darkness"):
        # The save drawer exists on these disks even when no slot is in it.
        files = (("/SAVE", "other"), *files)
    media = _media_with(tmp_path, key, files)

    assert maproute.persist_letter(title, _manifest(title, tmp_path), media) == expected


def _keys(phase: maproute.Phase) -> list[tuple[str, str | None]]:
    return [(step.state, step.key) for step in phase.steps if step.kind in ("key", "type")]


def test_persist_phases_reuse_the_measured_reload_keys_with_the_persist_letter(tmp_path: Path):
    pool = maproute.route_for("pool", _manifest("pool", tmp_path))
    saved, rest = maproute.persist_phases(pool, "E")
    reload = next(p for p in pool.phases if p.name == "reload")

    assert saved.steps[0].kind == "observe" and saved.steps[0].checkpoint == "persist_saved"
    assert _keys(saved) == [("camp", "E")]
    # Only the save letter and the load letter change; the relaunch and the pages stay.
    assert _keys(rest) == [
        ("camp_save_picker", "S"), ("quit_prompt", "E"), ("cli", "Y"), ("title", None),
        ("party_menu", "RET"), ("save_path", "L"), ("load_picker", "RET"), ("world", "E")]
    assert _keys(reload)[1:] == [
        ("camp_save_picker", "S"), ("quit_prompt", "C"), ("cli", "Y"), ("title", None),
        ("party_menu", "RET"), ("save_path", "L"), ("load_picker", "RET"), ("grid", "A")]
    assert rest.pages == reload.pages
    assert [s.relaunch for s in rest.steps] == [s.relaunch for s in reload.steps[1:]]
    final = rest.steps[-1]
    assert final.checkpoint == "persist_reloaded" and final.state == "world"
    assert final.expected == maproute.Expected(compare_to="persist_saved", relation="equal")

    curse = maproute.route_for("curse", _yulash_manifest(tmp_path))
    saved, rest = maproute.persist_phases(curse, "H")
    reload = next(p for p in curse.phases if p.name == "reload")
    assert _keys(rest) == [("camp_save_picker", "S"), ("exit_game", "H"), ("reboot", "Y"),
                           ("load_picker", "L"), ("loaded_menu", "H"), ("world", "B")]
    assert [s.kind for s in rest.steps] == [s.kind for s in reload.steps[1:]]
    assert rest.steps[-1].checkpoint == "persist_reloaded"


@pytest.mark.parametrize("title,letter", [("ssb", "E"), ("darkness", "G")])
def test_persist_phases_save_only_for_the_titles_the_controller_reloads(
        title: str, letter: str, tmp_path: Path):
    route = maproute.route_for(title, _manifest(title, tmp_path))
    saved, rest = maproute.persist_phases(route, letter)

    assert _keys(saved) == [("camp", "E")]
    assert _keys(rest) == [("camp_save_picker", "S"), ("exit_game", letter), ("camp", "N")]
    assert all(step.checkpoint is None for step in rest.steps)


def test_the_persist_leg_prefix_is_the_load_and_pool_boat_only(tmp_path: Path):
    assert maproute.LEG_PREFIX == {"pool": ("load", "outdoor", "transition"),
                                   "curse": ("load",), "ssb": ("load",), "darkness": ("load",)}
    pool = maproute.route_for("pool", _manifest("pool", tmp_path))
    names = [p.name for p in pool.phases]
    assert all(name in names for name in maproute.LEG_PREFIX["pool"])


def _spells_manifest(title: str, root: Path) -> dict:
    party = maproute.SPELLS_PARTIES[title]
    return {**_manifest(title, root),
            "substitute": {"letter": party.letter, "sha256": party.sha256},
            "state_a": dict(party.place)}


@pytest.mark.parametrize("title,letter", [("curse", "G"), ("ssb", "E")])
def test_the_spells_party_passes_the_persist_leg_and_never_the_mapping_leg(
        title: str, letter: str, tmp_path: Path):
    from types import SimpleNamespace

    from tools.amiga import winwishaccept

    route = maproute.route_for(title, _spells_manifest(title, tmp_path))

    with pytest.raises(winwishaccept.AcceptanceStop, match="pinned for the persist leg"):
        winwishaccept._phase_map(route)
    actions = winwishaccept._check_persist(SimpleNamespace(action=["heal"]), route)
    assert [action.kind for action in actions] == ["heal"]
    saved, rest = maproute.persist_phases(route, letter)
    assert saved.steps[0].checkpoint == "persist_saved"
    assert ("exit_game", letter) in _keys(rest)
    assert set(route.unresolved) == {maproute._PERSIST_ONLY}
    assert route.provenance["spells_party"].endswith(f"slot {maproute.SPELLS_PARTIES[title].letter}")


def test_the_curse_spells_party_loads_and_reloads_on_its_own_square(tmp_path: Path):
    route = maproute.route_for("curse", _spells_manifest("curse", tmp_path))
    yulash = maproute.route_for("curse", _yulash_manifest(tmp_path))
    phases = {phase.name: phase for phase in route.phases}
    reload = next(phase for phase in yulash.phases if phase.name == "reload")
    square = maproute.Expected(engine={"x": 5, "y": 13, "facing": 3})

    assert phases["load"].steps[-1].expected == square
    assert phases["reload"].steps[-1].expected == square
    assert phases["reload"].ready and phases["load"].ready
    assert [(s.kind, s.state, s.key, s.relaunch) for s in phases["reload"].steps] == [
        (s.kind, s.state, s.key, s.relaunch) for s in reload.steps]
    assert phases["reload"].pages == reload.pages


@pytest.mark.parametrize("title,change", [
    ("curse", {"state_a": {"area": 1, "x": 5, "y": 12, "facing": 3}}),
    ("curse", {"substitute": {"letter": "F"}}),
    ("curse", {"loaded_letter": "C"}),
    ("ssb", {"state_a": {"area": 16, "x": 3, "y": 5, "facing": 2}}),
])
def test_a_spells_party_off_its_pin_gets_no_persist_route(
        title: str, change: dict, tmp_path: Path):
    from types import SimpleNamespace

    from tools.amiga import winwishaccept

    manifest = _spells_manifest(title, tmp_path)
    if "substitute" in change:
        change = {"substitute": {**manifest["substitute"], **change["substitute"]}}
    route = maproute.route_for(title, {**manifest, **change})

    assert "spells_party" not in route.provenance
    with pytest.raises(winwishaccept.AcceptanceStop, match="route incomplete"):
        winwishaccept._check_persist(SimpleNamespace(action=["heal"]), route)


@pytest.mark.parametrize("title,key", [
    ("curse", "curse-of-the-azure-bonds"), ("ssb", "secret-of-the-silver-blades")])
def test_the_pinned_spells_party_holds_a_ready_spell_for_the_selector_to_clear(
        title: str, key: str):
    import hashlib

    from gamedata import specimen

    from automap import amigaparty
    from goldbox import amiga_adf, amiga_savegame

    party = maproute.SPELLS_PARTIES[title]
    path = specimen(party.specimen, platform="amiga") / party.file
    assert hashlib.sha256(path.read_bytes()).hexdigest() == party.sha256
    saved = amiga_savegame.read_slot(amiga_adf.AmigaDisk.open(path), party.letter, key)
    state = amiga_savegame.state_from_savegame(saved)
    row = amigaparty.ROWS[key]
    spot = row.memorised

    def memorised(member) -> bytes:
        return member.raw[spot.offset:spot.offset + spot.length]

    assert {"area": state.area, "x": state.x, "y": state.y, "facing": state.facing} == party.place
    # The selector takes the first member by party slot with any memorised byte, and clears
    # that member's first non-zero byte.
    chosen = next(member for member in sorted(saved.characters, key=lambda m: m.raw[row.slot])
                  if any(memorised(member)))
    assert chosen.raw[:15].split(b"\0")[0].decode("latin1") == party.member
    first = next(value for value in memorised(chosen) if value)
    ready = [value for value in memorised(chosen) if value and not value & 0x80]
    # Bit 7 marks a spell still being memorised, which the Cast list does not show.
    assert not first & 0x80
    # Curse's Cast list for a member with no spell left shows no list at all, so its party
    # keeps one after the clear.
    assert len(ready) >= (2 if title == "curse" else 1)


def _outdoor(route):
    phase = next(p for p in route.phases if p.name == "outdoor")
    return phase, [(s.kind, s.state, s.key, s.seconds, s.checkpoint) for s in phase.steps]


def test_the_mapping_route_enters_yulash_with_no_hold(tmp_path: Path):
    _phase, steps = _outdoor(maproute.route_for("curse", _yulash_manifest(tmp_path)))
    assert steps == [("key", "yulash_arrival", "E", None, None),
                     ("key", "world", "S", None, "curse_yulash_again")]


def test_the_arrival_hold_leg_holds_the_question_then_watches_yulash(tmp_path: Path):
    route = maproute.route_for("curse", _yulash_manifest(tmp_path), arrival_hold=120)
    _phase, steps = _outdoor(route)

    after = maproute.AFTER_ARRIVAL_HOLD
    assert steps == [("key", "yulash_arrival", "E", None, None),
                     ("hold", "yulash_arrival", None, 120, None),
                     ("hold", "world", "S", after, None),
                     ("observe", "world", None, None, "curse_yulash_again")]
    assert route.provenance["measurement"]["leg"] == "arrival_hold"
    assert route.unresolved == ()


def test_the_search_area_leg_takes_search_area_into_area_17(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(maproute, "search_flag", lambda media, slot: 1)
    route = maproute.route_for("curse", _yulash_manifest(tmp_path), search_area=True)
    phase, steps = _outdoor(route)

    assert phase.initial_state == "dalelands_search" and phase.pages == ("continue",)
    assert steps == [("key", "continue", "S", None, None),
                     ("hold", "continue", "RET", maproute.SEARCH_LOAD_HOLD, None),
                     ("key", "continue", "RET", None, None),
                     ("hold", "continue", None, maproute.PAGE_SETTLE, None),
                     ("key", "continue", "RET", None, None),
                     ("hold", "continue", None, maproute.PAGE_SETTLE, None),
                     ("observe", "world", None, None, None),
                     ("hold", "world", None, maproute.AFTER_ARRIVAL_HOLD, None),
                     ("observe", "world", None, None, "curse_search_arrival")]
    world = next(s for p in route.phases for s in p.steps if s.checkpoint == "curse_world")
    assert world.state == "dalelands_search"
    reload = next(s for p in route.phases for s in p.steps if s.checkpoint == "curse_reloaded")
    assert (reload.expected.compare_to, reload.expected.relation) == (
        "curse_search_arrival", "area_changed")
    guards = json.loads(route.guard_path.read_text())["guards"]
    states = {p.initial_state for p in route.phases} | {
        s.state for p in route.phases for s in p.steps}
    assert states <= guards.keys()


def test_the_search_area_leg_needs_the_staged_flag(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(maproute, "search_flag", lambda media, slot: 0)
    with pytest.raises(RouteError, match=r"\$4C5B = 1"):
        maproute.route_for("curse", _yulash_manifest(tmp_path), search_area=True)


@pytest.mark.parametrize("title,legs", [
    ("curse", {"arrival_hold": 120}), ("ssb", {"arrival_hold": 120}),
    ("curse", {"search_area": True}),
])
def test_the_measurement_legs_need_the_yulash_party(title, legs, tmp_path: Path):
    with pytest.raises(RouteError, match="Yulash"):
        maproute.route_for(title, _manifest(title, tmp_path), **legs)


def test_the_two_measurement_legs_are_separate_and_a_hold_has_seconds(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(maproute, "search_flag", lambda media, slot: 1)
    with pytest.raises(RouteError, match="separate"):
        maproute.route_for("curse", _yulash_manifest(tmp_path), arrival_hold=5, search_area=True)
    with pytest.raises(RouteError, match="positive"):
        maproute.route_for("curse", _yulash_manifest(tmp_path), arrival_hold=0)


def test_the_search_flag_is_read_from_the_save_disks_slot_in_curses_numbering(tmp_path: Path):
    from goldbox import amiga_savegame
    from goldbox.amiga_adf import AmigaDisk

    data = bytearray(6000)
    at = amiga_savegame.CURSE.vm_offset(maproute.SEARCH_FLAG - 0x200)
    data[at:at + 2] = (1).to_bytes(2, "big")
    disk = AmigaDisk.blank("Save")
    disk.make_dir("/SAVE")
    disk.write_file(amiga_savegame.slot_path(amiga_savegame.CURSE, "B"), bytes(data))
    disk.save(tmp_path / "save.adf")
    media = (maproute.Media("save", tmp_path / "save.adf", "a" * 64),)

    assert maproute.search_flag(media, "B") == 1
