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
        "state_a": {"area": 21, "x": 1, "y": 2, "facing": 1},
    }


@pytest.mark.parametrize("title,load_key,load_state", [
    ("pool", "A", "world"),
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
def test_an_unmeasured_transition_blocks_the_title_before_a_lane_is_claimed(
        title: str, tmp_path: Path):
    route = maproute.route_for(title, _manifest(title, tmp_path))
    phases = {phase.name: phase for phase in route.phases}

    assert set(phases) == {"load", "stationary", "walk", "transition", "reload",
                           "reopen_step"} | ({"outdoor"} if title in ("pool", "curse") else set())
    # Silver Blades has a measured leave-town transition; its reload still blocks it.
    blocking = "reload" if title == "ssb" else "transition"
    assert phases["transition"].ready is (title == "ssb")
    assert not phases[blocking].ready
    assert phases[blocking].reason in route.unresolved
    assert route.unresolved
    assert [action.kind for action in route.actions] == [
        "heal", "spells", "identify", "quickfight", "levelup"]
    assert all(not action.enabled for action in route.actions)


@pytest.mark.parametrize("title", ("pool", "curse"))
def test_outdoor_routes_enter_an_area_before_indoor_checks(title: str, tmp_path: Path):
    route = maproute.route_for(title, _manifest(title, tmp_path))

    assert [phase.name for phase in route.phases] == [
        "load", "outdoor", "transition", "stationary", "walk", "reload", "reopen_step"]
    assert route.phases[1].steps[0].kind == "observe"
    assert not route.phases[2].ready


@pytest.mark.parametrize("title", ("pool", "curse", "ssb", "darkness"))
def test_every_ready_step_has_an_existing_screen_guard_and_unique_checkpoint(
        title: str, tmp_path: Path):
    route = maproute.route_for(title, _manifest(title, tmp_path))
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
    assert not phases["reload"].ready and not phases["reopen_step"].ready


def test_silver_blades_camp_step_encamps_from_the_ruins_on_the_camp_guard(tmp_path: Path):
    route = maproute.route_for("ssb", _manifest("ssb", tmp_path))
    camp = maproute._ssb_camp()
    guards = json.loads(route.guard_path.read_text())["guards"]

    assert camp.ready and camp.initial_state == "world"
    assert [(s.kind, s.key, s.state, s.checkpoint) for s in camp.steps] == [
        ("key", "E", "camp", None)]
    assert "camp" in guards
    assert "camp" not in [phase.name for phase in route.phases]
    assert not {phase.name: phase for phase in route.phases}["reload"].ready


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
    assert not {phase.name: phase for phase in route.phases}["reload"].ready
