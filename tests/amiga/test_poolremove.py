"""`tools/amiga/poolremove.py`: the Training Hall REMOVE driver, checked with synthetic disks, maps and a fake game."""

from __future__ import annotations

import argparse
import json
import pathlib
import types

import pytest

from goldbox import amiga_adf, geo
from tools.amiga import poolremove
from tools.amiga.staging import sha256
from tools.amiga.winuaesession import RouteError

SIZE = poolremove.RECORD_SIZE
CONTROL = poolremove.NAMED_BYTES["control"]


def record(name: bytes, fill: int = 0x11) -> bytes:
    """A record that is no character's: `name` in its field, `fill` elsewhere, pointers set."""
    raw = bytearray([fill]) * SIZE
    raw[:poolremove.NAME_FIELD] = name.ljust(poolremove.NAME_FIELD, b"\0")
    for at, size in poolremove.POINTER_FIELDS:
        raw[at:at + size] = (0x00C01234 + at).to_bytes(size, "big")
    return bytes(raw)


# -- names and records ---------------------------------------------------------------------


def test_the_stem_drops_the_writers_set_and_upper_cases_letters():
    assert poolremove.cha_stem(b"Lady K.a*t,h?e/r:i;n|e") == b"LADYKATHERINE"
    assert poolremove.cha_stem(b"PRINCESS FATIMA") == b"PRINCESSFATIMA"


def test_the_stem_keeps_the_byte_an_amiga_record_holds_for_a_space():
    assert poolremove.cha_stem(b"LADY\xffKATHERINE") == b"LADY\xffKATHERINE"
    assert poolremove.cha_name(record(b"LADY\xffKATHERINE")) == "LADY\xffKATHERINE.cha"


def test_the_cleaned_name_keeps_the_old_tail_after_its_terminator():
    raw = record(b"ab.c")
    raw = raw[:6] + b"QQ" + raw[8:]
    cleaned = poolremove.cleaned_record(raw)
    assert cleaned[:4] == b"ABC\0" and cleaned[4:8] == raw[4:8] and cleaned[8:] == raw[8:]


def test_a_record_compares_outside_the_pointers_and_the_cleaned_name():
    memory = record(b"magnus")
    cha = bytearray(poolremove.cleaned_record(memory))
    for at, size in poolremove.POINTER_FIELDS:
        cha[at:at + size] = bytes(size)
    assert poolremove.record_differences(bytes(cha), memory) == []
    cha[0x50] ^= 0xFF
    assert [d["offset"] for d in poolremove.record_differences(bytes(cha), memory)] == ["0x050"]
    # A record whose name is not cleaned differs where the writer would have cleaned it.
    assert poolremove.record_differences(memory, memory)[0]["offset"] == "0x000"


# -- the disk verdict ----------------------------------------------------------------------


def disks(tmp_path, files_after: dict[str, bytes], *, change: dict[str, bytes] | None = None):
    before = amiga_adf.AmigaDisk.blank("POOLSAVE")
    before.write_file("/charlist.txt", b"")
    before.write_file("/CHRDATA1.sav", b"slot")
    after = amiga_adf.AmigaDisk(bytearray(before.to_bytes()))
    for path, data in {**files_after, **(change or {})}.items():
        after.write_file(path, data)
    return before, after


def test_a_remove_that_wrote_the_memory_record_passes(tmp_path):
    live = record(b"MAGNUS")
    cha = poolremove.cleaned_record(live)
    before, after = disks(tmp_path, {"/MAGNUS.cha": cha, "/MAGNUS.itm": b"", "/MAGNUS.spc": b"x",
                                     "/charlist.txt": b"MAGNUS\n"})
    verdict = poolremove.judge(before, after, live, live)
    assert verdict["success"], verdict["problems"]
    assert verdict["added"] == ["/magnus.cha", "/magnus.itm", "/magnus.spc"]
    assert verdict["changed"] == ["/charlist.txt"] and verdict["slot_differences"] == []


def test_a_disk_with_no_cha_fails(tmp_path):
    before, after = disks(tmp_path, {"/MAGNUS.itm": b""})
    verdict = poolremove.judge(before, after, record(b"MAGNUS"), record(b"MAGNUS"))
    assert not verdict["success"] and "the disk has no MAGNUS.cha" in verdict["problems"]


def test_a_slot_file_the_remove_changed_fails(tmp_path):
    live = record(b"MAGNUS")
    before, after = disks(tmp_path, {"/MAGNUS.cha": poolremove.cleaned_record(live)},
                          change={"/CHRDATA1.sav": b"other"})
    verdict = poolremove.judge(before, after, live, live)
    assert not verdict["success"] and verdict["other_changes"] == ["/chrdata1.sav"]


def test_a_cha_that_is_not_the_memory_record_fails(tmp_path):
    live = record(b"MAGNUS")
    cha = bytearray(poolremove.cleaned_record(live))
    cha[0x40] ^= 1
    before, after = disks(tmp_path, {"/MAGNUS.cha": bytes(cha)})
    verdict = poolremove.judge(before, after, live, live)
    assert not verdict["success"]
    assert [d["offset"] for d in verdict["memory_differences"]] == ["0x040"]


def test_a_slot_difference_is_listed_and_only_the_named_bytes_fail_it(tmp_path):
    live = record(b"MAGNUS")
    slot = bytearray(live)
    slot[0x40] ^= 1
    before, after = disks(tmp_path, {"/MAGNUS.cha": poolremove.cleaned_record(live)})
    verdict = poolremove.judge(before, after, live, bytes(slot))
    assert verdict["success"] and [d["offset"] for d in verdict["slot_differences"]] == ["0x040"]
    slot[CONTROL] = 0xB3
    verdict = poolremove.judge(before, after, live, bytes(slot))
    assert not verdict["success"]
    assert any("control, status or creature type" in p for p in verdict["problems"])


def test_a_cha_already_on_the_disk_that_remove_did_not_rewrite_fails(tmp_path):
    live = record(b"MAGNUS")
    cha = poolremove.cleaned_record(live)
    before, after = disks(tmp_path, {"/MAGNUS.cha": cha})
    before.write_file("/MAGNUS.cha", cha)
    verdict = poolremove.judge(before, after, live, live)
    assert not verdict["success"]
    assert any("did not write MAGNUS.cha" in p for p in verdict["problems"])


def test_a_cha_already_on_the_disk_that_remove_rewrote_passes(tmp_path):
    live = record(b"MAGNUS")
    before, after = disks(tmp_path, {"/MAGNUS.cha": poolremove.cleaned_record(live)})
    before.write_file("/MAGNUS.cha", record(b"MAGNUS", 0x22))
    verdict = poolremove.judge(before, after, live, live)
    assert verdict["success"], verdict["problems"]
    assert "/magnus.cha" in verdict["changed"] and verdict["other_changes"] == []


def test_a_fetched_disk_that_fails_verification_fails(tmp_path):
    live = record(b"MAGNUS")
    before, after = disks(tmp_path, {"/MAGNUS.cha": poolremove.cleaned_record(live)})
    after.verify = lambda: ["block 881: bitmap marks a used block free"]
    verdict = poolremove.judge(before, after, live, live)
    assert not verdict["success"]
    assert any("bitmap marks a used block free" in p for p in verdict["problems"])


# -- the walk ------------------------------------------------------------------------------


class Map:
    """New Phlan as the planner reads it: open everywhere but `walls`, script ids at `scripts`."""

    def __init__(self, walls=(), scripts=None):
        self.walls = set(walls)
        self.scripts = {poolremove.HALL_DOOR: 10, **(scripts or {})}

    def wall(self, x, y, direction):
        dx, dy = poolremove.DELTAS[direction]
        return int(((x, y), (x + dx, y + dy)) in self.walls
                   or ((x + dx, y + dy), (x, y)) in self.walls)

    def barrier(self, x, y, direction):
        return 0

    def script_id(self, x, y):
        return self.scripts.get((x, y), 0)


def test_the_walk_from_the_slums_crosses_the_gate_then_reaches_the_school():
    steps = poolremove.plan_walk(poolremove.SLUMS_START, Map())
    assert [s.key for s in steps[:3]] == ["NP6", "NP6", "NP8"]
    assert steps[2].expect == (poolremove.NEW_PHLAN, 0, 4, geo.EAST)
    door = [s for s in steps if s.expect and s.expect[0] == poolremove.HALL]
    assert door[0].expect == (poolremove.HALL, 6, 2, geo.EAST)
    assert steps[-1] == poolremove.WalkStep("NP8", None)
    assert [s.key for s in steps[-5:]] == ["NP4", "NP8", "NP8", "NP6", "NP8"]


def test_the_walk_goes_round_a_square_with_a_script():
    plain = poolremove.plan_walk((0, 4, 2, geo.EAST), Map())
    assert [s.expect for s in plain[:1]] == [(0, 5, 2, geo.EAST)]
    detour = poolremove.plan_walk((0, 4, 2, geo.EAST), Map(scripts={(5, 2): 7}))
    squares = [s.expect[1:3] for s in detour if s.expect and s.key == "NP8"]
    assert (5, 2) not in squares and squares[squares.index((6, 2)) - 1] != (5, 2)


def test_a_start_outside_new_phlan_is_blocked():
    with pytest.raises(RouteError, match="starts in New Phlan"):
        poolremove.plan_walk((3, 4, 2, geo.EAST), Map())


def test_a_closed_hall_is_blocked():
    with pytest.raises(RouteError, match="is closed"):
        poolremove.plan_walk((0, 4, 2, geo.EAST), Map(walls={((6, 1), (6, 0))}))


# -- the run, against a fake game ----------------------------------------------------------


NAMES = ["BRUTUS", "MAGNUS", "SILAS"]


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        self.now += 0.01
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def time(self):
        return 1_000_000.0 + self.now


class Game:
    """The screens, square, party and highlight of a Pool game the run drives."""

    def __init__(self, *, stuck=False, remove_works=True):
        self.screen = "wheel"
        self.place = (0, 4, 2, geo.EAST)
        self.records = {0x1000 + 0x200 * n: record(name.encode(), 0x10 + n)
                        for n, name in enumerate(NAMES)}
        self.party = list(self.records)
        self.current = self.party[0]
        self.stuck, self.remove_works = stuck, remove_works
        self.removed: bytes | None = None
        self.after_remove = "menu"
        self.keys: list[str] = []

    def press(self, key):
        self.keys.append(key)
        screen = self.screen
        moves = {("wheel", "RET"): "title", ("title", "RET"): "party_menu",
                 ("party_menu", "L"): "save_path", ("save_path", "RET"): "load_picker",
                 ("load_picker", "A"): "world", ("question", "Y"): "menu", ("menu", "B"): "world"}
        if (screen, key) in moves:
            self.screen = moves[screen, key]
        elif screen == "world" and key in ("NP4", "NP6", "NP2", "NP8") and not self.stuck:
            self.walk(key)
        elif screen == "menu" and key == "NP1":
            at = self.party.index(self.current)
            self.current = self.party[(at + 1) % len(self.party)]
        elif screen == "menu" and key == "R" and self.remove_works:
            self.removed = self.records[self.current]
            self.party.remove(self.current)
            self.current = self.party[0]
            self.screen = self.after_remove

    def walk(self, key):
        area, x, y, facing = self.place
        if key != "NP8":
            self.place = (area, x, y, (facing + {"NP6": 1, "NP2": 2, "NP4": 3}[key]) % 4)
            return
        dx, dy = poolremove.DELTAS[facing]
        x, y = x + dx, y + dy
        if (x, y) == poolremove.HALL_DOOR:
            area = poolremove.HALL
        if (x, y) == poolremove.SCHOOL:
            self.screen = "question"
            return
        self.place = (area, x, y, facing)


class Guest:
    remote_path = staticmethod(lambda issue, holder, key: f"C:/{key}")
    silence = staticmethod(lambda proof: proof is not None)

    def __init__(self, game):
        self.game, self.calls = game, []

    def _run(self, *args, timeout):
        return json.dumps({"muted": True})

    def grab(self, state, raw, crop, timeout):
        crop.write_text(self.game.screen)
        return True

    def press(self, holder, key, timeout):
        self.game.press(key)
        return "ok"

    def snapshot(self, name, holder):
        self.calls.append(("snapshot", name))
        self.saved = (self.game.place, self.game.screen)

    def restore(self, name, holder):
        self.calls.append(("restore", name))
        self.game.place, self.game.screen = self.saved

    def discard(self, name, holder):
        self.calls.append(("discard", name))

    def lane(self, holder, timeout):
        return 1


class Guards:
    """Every state's guard is the fake screen's name; the hall states are `question` and `menu`."""

    screens = {"title": "title", "wheel": "wheel", "party_menu": "party_menu",
               "save_path": "save_path", "load_picker": "load_picker", "world": "world",
               "hall_question": "question", "hall_menu": "menu"}

    def __init__(self, path):
        self.rules = dict(self.screens)

    def __contains__(self, state):
        return state in self.rules

    def __call__(self, state, crop):
        return self.rules.get(state) == pathlib.Path(crop).read_text()


class Live:
    def __init__(self, game):
        self.game, self.target = game, object()

    def place(self):
        return self.game.place

    def members(self):
        return [(record_name, a, self.game.records[a])
                for a in self.game.party
                for record_name in [self.game.records[a][:16].split(b"\0")[0].decode()]]

    def current(self):
        return self.game.current

    def select(self, want, press):
        line = int(want)
        while self.game.party.index(self.game.current) != line - 1:
            press("NP1")
        return {"address": hex(self.game.current), "line": line}


class Switch:
    def __init__(self, game):
        self.game, self.events = game, []

    def on(self):
        self.events.append("on")
        return {"action": "on"}

    def keys(self, names):
        for name in names:
            self.game.press(name)
        return {"pressed": list(names)}

    def off(self):
        self.events.append("off")
        return {"action": "off"}


class State:
    def __init__(self, path):
        pass

    def load(self):
        return {"on": False, "rows": []}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    game = Game()
    clock = Clock()
    monkeypatch.setattr(poolremove, "time", clock)
    monkeypatch.setattr(poolremove, "PixelGuards", Guards)
    monkeypatch.setattr(poolremove.noencounters, "WinuaeState", State)
    monkeypatch.setattr(poolremove.noencounters, "winuae_state_path", lambda holder: tmp_path / "s")
    events = []

    def boot(path, manifest, title, **kwargs):
        events.append("boot")
        return {"claim": "ok"}

    def halt(guest, holder, manifest_path, command):
        events.append("halt")
        manifest = json.loads(manifest_path.read_text())
        disk = amiga_adf.AmigaDisk.open(pathlib.Path(manifest["disks"]["save"]["path"]))
        if game.removed is not None:
            disk.write_file(f"/{poolremove.cha_name(game.removed)}",
                            poolremove.cleaned_record(game.removed))
        folder = manifest_path.parent / f"halt-{holder}-1"
        folder.mkdir()
        disk.save(folder / "fetched-save.adf")
        return {"release": f"ok released {holder}"}

    monkeypatch.setattr(poolremove.acceptance, "boot_lane", boot)
    monkeypatch.setattr(poolremove.acceptance, "halt_lane", halt)
    monkeypatch.setattr(poolremove.amiga_savegame, "read_por_characters",
                        lambda disk, letter, drawer: [types.SimpleNamespace(raw=game.records[a])
                                                      for a in sorted(game.records)])
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    entries = {}
    for key in ("disk1", "disk2"):
        (inputs / f"{key}.adf").write_bytes(key.encode())
    save = amiga_adf.AmigaDisk.blank("POOLSAVE")
    save.write_file("/charlist.txt", b"")
    save.save(inputs / "save.adf")
    for key in ("disk1", "disk2", "save"):
        path = inputs / f"{key}.adf"
        entries[key] = {"path": str(path), "sha256": sha256(path)}
    manifest = {"title": "pool", "disks": entries, "loaded_letter": "A", "names_a": NAMES,
                "state_a": {"area": 0, "x": 4, "y": 2, "facing": geo.EAST}}
    path = inputs / "prepare.json"
    path.write_text(json.dumps(manifest))

    def go(member="MAGNUS", **options):
        args = argparse.Namespace(manifest=path, member=member, holder="h", out=tmp_path / "out",
                                  guards=None, wait_lane=0, walk_retry=1,
                                  budget=2400)
        return poolremove.run(args, guest=Guest(game), live_factory=lambda holder: Live(game),
                              switch_factory=lambda target: Switch(game),
                              load_geo=lambda name: Map(), **options)

    return types.SimpleNamespace(game=game, events=events, go=go, out=tmp_path / "out")


def test_the_run_removes_the_member_and_judges_the_disk(rig):
    receipt = rig.go()
    assert receipt["success"] and receipt["verdict"]["file"] == "MAGNUS.cha"
    assert rig.events == ["boot", "halt"]
    assert rig.game.keys[-3:] == ["NP1", "R", "B"] and "E" not in rig.game.keys
    assert (rig.out / "member-memory.bin").read_bytes() == rig.game.records[0x1200]


def test_a_member_the_slot_lacks_stops_before_any_lane(rig):
    with pytest.raises(RouteError, match="exactly one ROLAND"):
        rig.go(member="ROLAND")
    assert rig.events == [] and not rig.out.exists() and "E" not in rig.game.keys


def test_the_run_needs_the_hall_guards_before_any_lane(rig, monkeypatch):
    monkeypatch.setattr(poolremove, "HALL_GUARDS", {})
    with pytest.raises(RouteError, match="the hall's screens have no guards"):
        rig.go()
    assert rig.events == [] and "E" not in rig.game.keys


def test_a_manifest_with_no_place_is_blocked_with_a_sentence():
    with pytest.raises(RouteError, match="records no loaded place"):
        poolremove.manifest_place({"title": "pool"})


def test_a_step_that_does_not_move_retries_once_then_halts(rig):
    rig.game.stuck = True
    with pytest.raises(RouteError, match="left the party at"):
        rig.go()
    receipt = json.loads((rig.out / "receipt.json").read_text())
    assert rig.events == ["boot", "halt"] and not receipt["success"]
    assert len(receipt["walk"]) == 2 and "R" not in rig.game.keys and "E" not in rig.game.keys


def test_a_remove_that_leaves_the_member_halts_without_a_verdict_pass(rig):
    rig.game.remove_works = False
    with pytest.raises(RouteError, match="still in the party"):
        rig.go()
    receipt = json.loads((rig.out / "receipt.json").read_text())
    assert rig.events == ["boot", "halt"] and not receipt["success"]
    assert "B" not in rig.game.keys and "E" not in rig.game.keys


def test_an_unknown_screen_after_remove_leaves_begin_unsent(rig):
    rig.game.after_remove = "unknown"
    with pytest.raises(RouteError, match="hall_menu did not match"):
        rig.go()
    receipt = json.loads((rig.out / "receipt.json").read_text())
    assert rig.events == ["boot", "halt"] and not receipt["success"]
    assert rig.game.keys[-1] == "R" and "B" not in rig.game.keys and "E" not in rig.game.keys


def test_the_built_in_hall_guards_load_beside_the_pool_guards(tmp_path):
    rules = poolremove.PixelGuards(poolremove._guard_file(tmp_path, None)).rules
    assert set(poolremove.HALL_STATES) <= set(rules) and "world" in rules


def test_every_screen_of_the_run_is_matched_by_a_guard(rig):
    receipt = rig.go()
    assert receipt["success"] and not any(e.get("settled") for e in receipt["screens"])
    assert "E" not in rig.game.keys
