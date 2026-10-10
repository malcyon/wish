"""Amiga Pool of Radiance's temple raise, record stager and walk-until-encounter fight run, on fakes."""

from __future__ import annotations

import dataclasses
import json
import pathlib

import pytest

from goldbox import amiga_por, geo
from goldbox.amiga_adf import AmigaDisk
from tests.amiga import test_amigaacceptance_measure as measure
from tests.amiga import test_amigaacceptance_title as title_run
from tests.amiga.test_amigaacceptance import _audio_proof
from tests.amiga.test_amigaacceptance_accept import MapGuard, _IdentityMap
from tools.amiga import acceptance, route, route_pool, staging
from tools.amiga.route import RouteError
from tools.amiga.staging import StageError

clock = measure.clock  # the fixture that replaces the driver's time and sleep

GOLD = amiga_por.amiga_por_offset(0x08E)
CON = amiga_por.amiga_por_offset(0x014)


def _record(name=b"BRUTUS", gold=0, con=16):
    raw = bytearray(amiga_por.AMIGA_POR_RECORD_SIZE)
    raw[0:len(name)] = name
    raw[GOLD:GOLD + 2] = gold.to_bytes(2, "big")
    raw[CON] = con
    return bytes(raw)


# --- the record stager -------------------------------------------------------------------

def test_the_stager_writes_gold_big_endian_and_constitution_and_nothing_else():
    raw = _record()
    staged, fields = staging.stage_por_record(raw, {"gold": 6000, "constitution": 18})
    assert fields == {"gold": {"before": 0, "after": 6000},
                      "constitution": {"before": 16, "after": 18}}
    assert staged[GOLD:GOLD + 2] == bytes([0x17, 0x70]) and staged[CON] == 18
    assert [i for i in range(len(raw)) if raw[i] != staged[i]] == [CON, GOLD, GOLD + 1]


@pytest.mark.parametrize("changes, why", [
    ({"hp_current": 9}, "writes only"), ({"gold": 70000}, "does not fit"),
    ({"constitution": 256}, "does not fit"), ({}, "names no field")])
def test_the_stager_blocks_any_other_field_or_value(changes, why):
    with pytest.raises(StageError, match=why):
        staging.stage_por_record(_record(), changes)


def test_the_stager_blocks_a_record_of_the_wrong_size():
    with pytest.raises(StageError, match="288 bytes"):
        staging.stage_por_record(_record()[:-1], {"gold": 1})


@pytest.mark.parametrize("text, wanted", [
    ("1:gold=6000,constitution=18", (1, {"gold": 6000, "constitution": 18})),
    ("3:gold=5", (3, {"gold": 5}))])
def test_a_stage_record_parses(text, wanted):
    assert staging.parse_stage_record(text) == wanted


@pytest.mark.parametrize("text", ["gold=1", "x:gold=1", "1:", "1:gold", "1:gold=-1",
                                  "1:gold=1,gold=2"])
def test_a_malformed_stage_record_is_blocked(text):
    with pytest.raises(StageError):
        staging.parse_stage_record(text)


def _pool_disk(*records):
    disk = AmigaDisk.blank("POOLSAVE")
    for n, raw in enumerate(records, 1):
        disk.write_file(f"/CHRDATA{n}.sav", raw)
    return disk


def test_staging_a_member_changes_only_his_file_and_checks_back():
    disk = _pool_disk(_record(), _record(b"MAGNUS", gold=2, con=13))
    before = AmigaDisk(bytearray(disk.to_bytes()))
    staged = staging.stage_pool_member(disk, "A", 1, {"gold": 6000, "constitution": 18})
    assert staged["name"] == "BRUTUS" and staged["file"] == "/CHRDATA1.sav"
    assert disk.read_file("/CHRDATA2.sav") == before.read_file("/CHRDATA2.sav")
    staging.check_staged_member(before, disk, staged)
    disk.write_file("/CHRDATA2.sav", _record(b"MAGNUS", gold=3, con=13))
    with pytest.raises(StageError, match="more than the staged record"):
        staging.check_staged_member(before, disk, staged)


def test_staging_a_member_the_slot_lacks_is_blocked():
    with pytest.raises(StageError, match="members 1 to 1"):
        staging.stage_pool_member(_pool_disk(_record()), "A", 2, {"gold": 1})


# --- prepare's Pool options --------------------------------------------------------------

@pytest.mark.parametrize("kw, why", [
    (dict(name="curse", temple=True), "for Pool of Radiance"),
    (dict(temple=True, encounter=True), "two routes"),
    (dict(encounter=True, camp=("rest",)), "camp steps"),
    (dict(temple=True), "needs --stage-record"),
    (dict(temple=True, stage_record="2:gold=6000,constitution=18"), "needs --stage-record"),
    (dict(temple=True, stage_record="1:gold=5499,constitution=18"), "needs --stage-record"),
    (dict(temple=True, stage_record="1:gold=6000"), "needs --stage-record"),
    (dict(stage_record="1:hp=1"), "FIELD=VALUE|writes only|hp")])
def test_prepare_blocks_pool_options_that_cannot_run(kw, why):
    args = dict(name="pool", temple=False, encounter=False, camp=(), stage_record=None)
    args.update(kw)
    name = args.pop("name")
    try:
        staged = acceptance._pool_options(name, **args)
    except RouteError as exc:
        assert any(part in str(exc) for part in why.split("|")), exc
    else:
        # A field the stager does not take passes parsing and is blocked when staged.
        with pytest.raises(StageError, match="writes only"):
            staging.stage_por_record(_record(), staged[1])


def test_prepare_takes_the_temple_with_its_stage_record():
    assert acceptance._pool_options(
        "pool", temple=True, encounter=False, camp=(),
        stage_record="1:gold=6000,constitution=18") == (1, {"gold": 6000, "constitution": 18})


def _staged_manifest(tmp_path, monkeypatch, status):
    path = tmp_path / "save.adf"
    _pool_disk(_record(), _record(b"MAGNUS")).save(path)
    monkeypatch.setattr(acceptance, "POOL", dataclasses.replace(
        route_pool.POOL, read_slot=lambda _disk, _letter: {
            "members": [{"name": "BRUTUS", "status_bytes": [status, 0, 0, 0]}]}))
    return {"state_a": dict(route_pool.POOL_TEMPLE_START), "loaded_letter": "A",
            "names_a": ["BRUTUS", "MAGNUS"],
            "disks": {"save": {"path": str(path), "sha256": staging.sha256(path)}}}


def test_a_temple_prepare_stages_the_first_member_and_records_both_disks(tmp_path, monkeypatch):
    manifest = _staged_manifest(tmp_path, monkeypatch, acceptance.POOL_DEAD_STATUS)
    acceptance._stage_pool(tmp_path, manifest, (1, {"gold": 6000, "constitution": 18}),
                           temple=True, encounter=False)
    assert manifest["temple"] == {"member": "BRUTUS"}
    staged = manifest["staged_record"]
    assert staged["fields"]["gold"] == {"before": 0, "after": 6000}
    assert manifest["disks"]["save"]["sha256"] == staging.sha256(tmp_path / "save.adf")
    assert staged["before"]["sha256"] == staging.sha256(tmp_path / "save-unstaged.adf")
    staging.check_staged_member(AmigaDisk.open(tmp_path / "save-unstaged.adf"),
                                AmigaDisk.open(tmp_path / "save.adf"), staged)


def test_a_temple_prepare_whose_first_member_lives_is_blocked(tmp_path, monkeypatch):
    manifest = _staged_manifest(tmp_path, monkeypatch, 0)
    with pytest.raises(RouteError, match="is not dead"):
        acceptance._stage_pool(tmp_path, manifest, (1, {"gold": 6000, "constitution": 18}),
                               temple=True, encounter=False)


def test_a_temple_prepare_elsewhere_is_blocked(tmp_path, monkeypatch):
    manifest = _staged_manifest(tmp_path, monkeypatch, acceptance.POOL_DEAD_STATUS)
    manifest["state_a"] = {"area": 0, "x": 0, "y": 4, "facing": geo.WEST}
    with pytest.raises(RouteError, match="temple walk starts"):
        acceptance._stage_pool(tmp_path, manifest, None, temple=True, encounter=False)


# --- the temple route and its verdict ----------------------------------------------------

def _between(route_steps, first, last):
    keys = [key for key, _, _ in route_steps]
    return keys[keys.index(first) + 1:keys.index(last)]


def test_the_temple_route_walks_raises_and_saves_around_it():
    title = route_pool.POOL_TEMPLE
    assert _between(title.route, "C", "D") == [
        "N", "E", "NP6", "NP6", "NP8", "NP8", "NP4", "NP8", "Y", "H", *["NP2"] * 6, "H", "Y",
        "E", "E", "V", "E", "E", "S"]
    assert {"temple_greeting", "temple", "temple_services", "temple_raise_row",
            "temple_price"} <= title.strict
    # HEAL buys only on RAISE DEAD's own row, and YES pays only on its price screen.
    steps = list(title.route)
    for at, (key, state, _) in enumerate(steps):
        if state == "temple_price":
            assert steps[at - 1][1] == "temple_raise_row" and key == "H"
        if key == "Y" and steps[at - 1][1] == "temple_price":
            assert state == "temple_raise_row"


def test_pool_route_picks_the_temple_the_fight_or_the_walk(monkeypatch):
    start = dict(route_pool.POOL_TEMPLE_START)
    assert acceptance.pool_route({"temple": {"member": "BRUTUS"}, "state_a": start}) is (
        route_pool.POOL_TEMPLE)
    assert acceptance.pool_route({"encounter": True, "state_a": start}) is (
        route_pool.POOL_ENCOUNTER)
    assert acceptance.pool_route({"encounter": True, "state_a": dict(
        route_pool.POOL_TEMPLE_SQUARE)}) is route_pool.POOL_ENCOUNTER_FROM_TEMPLE
    monkeypatch.setattr(route_pool, "pool_title_for", lambda _m: "walk")
    monkeypatch.setattr(acceptance, "pool_title_for", lambda _m: "walk")
    assert acceptance.pool_route({"state_a": start}) == "walk"


STAGED_GOLD = 6000
COINS = ("copper", "silver", "electrum", "gold", "platinum", "gems", "jewelry")
#: The payer's purse before and after the raise in the two measured runs (synthetic copies of
#: the figures, no game bytes): gold only, and gold with 102 silver whose change lost 2 silver.
STAGED = dict.fromkeys(COINS, 0) | {"gold": STAGED_GOLD}
PAID = dict.fromkeys(COINS, 0) | {"platinum": 100}
STAGED_SILVER = dict(STAGED, silver=102)
PAID_SILVER = dict(PAID, platinum=101)
#: A second member whose purse the raise leaves alone.
OTHER = dict.fromkeys(COINS, 0) | {"silver": 103, "gold": 2, "platinum": 1}


def _slot(place, status=0, control=0, nodes=(), money=PAID, other=OTHER):
    return {"place": place,
            "members": [{"name": "BRUTUS", "status_bytes": [status, 1, 0, 0],
                         "control": control, "gold": money["gold"], "money": dict(money)},
                        {"name": "MAGNUS", "status_bytes": [0, 1, 0, 0], "control": 0,
                         "gold": other["gold"], "money": dict(other)}],
            "effects": {"BRUTUS": [list(n) for n in nodes]}}


START = dict(route_pool.POOL_TEMPLE_START)
SQUARE = dict(route_pool.POOL_TEMPLE_SQUARE)


def _verdict(b, d):
    return route_pool.temple_verdict(START, b, d, "BRUTUS", staged_gold=STAGED_GOLD)


@pytest.mark.parametrize(("money", "expected"), [
    (dict.fromkeys(COINS, 0), 0), (STAGED, 6000), (STAGED_SILVER, 6005), (PAID_SILVER, 505),
    (dict.fromkeys(COINS, 0) | {"copper": 199, "silver": 19, "electrum": 1}, 2),
    (dict.fromkeys(COINS, 0) | {"gems": 10, "jewelry": 10}, 0)])
def test_a_purse_counts_in_whole_gold_pieces_at_the_coin_rates(money, expected):
    assert route_pool.purse_in_gold(money) == expected


@pytest.mark.parametrize(("staged", "paid", "platinum"), [
    (STAGED, PAID, 100), (STAGED_SILVER, PAID_SILVER, 101)])
def test_a_raised_member_on_the_temple_square_passes(staged, paid, platinum):
    walk = _verdict(_slot(START, status=6, money=staged), _slot(SQUARE, money=paid))
    assert walk["b_ok"] and walk["d_ok"], walk["verdicts"]
    assert walk["area_crossed"] == {"from": 20, "to": 0}
    assert walk["raised"] == {"status": 0, "control": 0, "node_32": False, "gold": 0,
                              "platinum": platinum, "paid": True}
    assert walk["verdicts"][-1].endswith(f"BRUTUS paid 5500 and holds platinum {platinum}")


def test_change_left_in_gold_is_the_same_payment():
    assert _verdict(_slot(START, money=STAGED),
                    _slot(SQUARE, money=dict(STAGED, gold=500)))["d_ok"]


@pytest.mark.parametrize("after", [
    _slot(SQUARE, status=6), _slot(SQUARE, control=0xB3), _slot(SQUARE, nodes=[(32, 0, 5, 1)]),
    _slot(dict(SQUARE, y=4)), {"missing": True},
    # The money moved wrongly: nothing paid, gold left as staged with platinum added, too much
    # taken, a gem gone, another member paid, or the purse is not read.
    _slot(SQUARE, money=STAGED_SILVER), _slot(SQUARE, money=dict(STAGED_SILVER, platinum=101)),
    _slot(SQUARE, money=PAID), _slot(SQUARE, money=dict(PAID_SILVER, platinum=102)),
    _slot(SQUARE, money=dict(PAID_SILVER, gems=1)),
    _slot(SQUARE, money=PAID_SILVER, other=dict(OTHER, platinum=0)),
    {**_slot(SQUARE), "members": [{"name": "BRUTUS", "status_bytes": [0, 1, 0, 0],
                                   "control": 0, "gold": 0}]}])
def test_a_member_not_raised_elsewhere_or_not_paid_fails(after):
    assert not _verdict(_slot(START, status=6, money=STAGED_SILVER), after)["d_ok"]


def test_a_payment_one_platinum_short_names_the_change_expected():
    walk = _verdict(_slot(START, money=STAGED_SILVER), _slot(SQUARE, money=PAID))
    assert not walk["d_ok"] and not walk["raised"]["paid"]
    assert ("held 6005 gold in coins and then 500 (platinum 100), expected 505 after paying "
            "5500") in walk["verdicts"][-1]


@pytest.mark.parametrize(("coin", "amount"), [("electrum", 1), ("copper", 7), ("silver", 50)])
def test_a_purse_with_an_unmeasured_coin_rate_fails(coin, amount):
    walk = _verdict(_slot(START, money=dict(STAGED, **{coin: amount})), _slot(SQUARE, money=PAID))
    assert not walk["d_ok"]
    assert f"the temple's rate for {coin} is not measured" in walk["verdicts"][-1]


def test_a_control_slot_without_the_staged_gold_fails():
    walk = _verdict(_slot(START, money=PAID), _slot(SQUARE))
    assert not walk["d_ok"]
    assert "held 0 gold before, not the staged 6000" in walk["verdicts"][-1]


def test_a_control_save_that_moved_fails():
    walk = _verdict(_slot(SQUARE, money=STAGED), _slot(SQUARE))
    assert not walk["b_ok"] and walk["d_ok"]


def test_the_slot_reader_reads_every_coin_big_endian_at_its_dos_offset():
    raw = bytearray(_record(gold=0))
    for n, coin in enumerate(COINS):
        at = amiga_por.amiga_por_offset(0x088 + 2 * n)
        raw[at:at + 2] = (0x0100 + n).to_bytes(2, "big")
    reading = route_pool._pool_member_bytes(bytes(raw))
    assert reading["money"] == {coin: 0x0100 + n for n, coin in enumerate(COINS)}
    assert reading["gold"] == reading["money"]["gold"] == 0x0103


# --- the until_encounter step --------------------------------------------------------------

@pytest.mark.parametrize("key", [("NP8", "NP4", 0), ("NP8", "NP4", "9"), ("NP8", "F11", 3),
                                 ("NP8", "D", 3), "NP8", ("NP8", "NP4")])
def test_an_until_encounter_step_needs_two_keys_and_a_bound(key):
    with pytest.raises(RouteError, match="until_encounter"):
        dataclasses.replace(route_pool.POOL_ENCOUNTER,
                            route=((key, "encounter", "until_encounter"),),
                            kept_letters=("D",))


@pytest.mark.parametrize("title", [route_pool.POOL_ENCOUNTER,
                                   route_pool.POOL_ENCOUNTER_FROM_TEMPLE])
def test_the_fight_route_saves_nothing_and_ends_on_the_first_command_bar(title):
    assert title.control_letter is None and title.after_letter is None
    assert all(kind != "write" for *_, kind in title.route)
    assert title.route[-2:] == ((route_pool.ENCOUNTER_STEP, "encounter", "until_encounter"),
                                ("C", "combat_bar", "key"))
    assert title.measure_route[-2:] == title.route[-2:]
    assert acceptance.fights(title) and not acceptance.fights(route_pool.POOL)


def test_a_party_saved_at_the_temple_turns_about_steps_out_and_faces_west_before_the_walk():
    leave = (("NP2", "world", "turn"), ("NP8", "world", "move"), ("NP6", "world", "turn"))
    load = route_pool.POOL_ENCOUNTER.route[:-2]
    title = route_pool.POOL_ENCOUNTER_FROM_TEMPLE
    assert title.route == (*load, *leave, *route_pool.POOL_ENCOUNTER.route[-2:])
    assert title.measure_route == (*route_pool.POOL_ENCOUNTER.measure_route[:-2], *leave,
                                   *route_pool.POOL_ENCOUNTER.measure_route[-2:])


@pytest.mark.parametrize(("place", "expected"), [
    (dict(route_pool.POOL_TEMPLE_SQUARE), "POOL_ENCOUNTER_FROM_TEMPLE"),
    (dict(route_pool.POOL_TEMPLE_START), "POOL_ENCOUNTER"),
    (dict(route_pool.POOL_TEMPLE_SQUARE, facing=geo.SOUTH), "POOL_ENCOUNTER"),
    (None, "POOL_ENCOUNTER")])
def test_the_fight_route_leaves_the_temple_only_for_a_party_saved_there(place, expected):
    assert route_pool.pool_encounter_title({"state_a": place}) is getattr(route_pool, expected)


def test_a_fight_run_picks_its_route_from_the_start_square(tmp_path, clock, monkeypatch):
    seen = []
    monkeypatch.setattr(acceptance, "pool_encounter_title",
                        lambda manifest: seen.append(manifest["state_a"]) or _fight_title())
    guest = FightGuest(clock, met=1)
    result = _fight(tmp_path, clock, guest, title=route_pool.POOL_ENCOUNTER)
    assert len(seen) == 1 and result["success"], result["error"]


class FightGuest(title_run.TitleGuest):
    """Menus change with every key; on the map a step moves unless it is in `blocked`, and the
    `met`-th step shows the encounter menu, which COMBAT turns into the first command bar."""

    def __init__(self, clock, *, met=None, blocked=()):
        super().__init__(clock)
        self.met, self.blocked = met, set(blocked)
        self.walking = False
        self.steps = self.squares = self.turns = 0
        self.shown = None

    def press(self, holder, key, timeout=None):
        # The menus' fake, not the title guest's: COMBAT's `C` writes no save.
        measure.ScreenGuest.press(self, holder, key, timeout)
        if key == "NP8":
            self.walking = True
            self.steps += 1
            if self.steps == self.met:
                self.shown = "encounter"
            elif self.steps not in self.blocked:
                self.squares += 1
        elif key == "NP4":
            self.turns += 1
        elif key == "C" and self.shown == "encounter":
            self.shown = "combat"

    def _frame(self):
        if self.shown:
            return self.shown
        if self.walking:
            return f"world {self.squares} {self.turns}"
        return f"frame {self.presses}"

    def capture(self, state, raw, cropped, timeout=None):
        super().capture(state, raw, cropped, timeout)
        cropped.write_bytes(self._frame().encode())

    def grab(self, state, raw, cropped, timeout=None):
        super().grab(state, raw, cropped, timeout)
        cropped.write_bytes(self._frame().encode())
        return True


FIGHT_STATES = ("title", "party_menu", "save_path", "load_picker", "world", "sheet",
                "camp_save_picker", "encounter", "combat_bar")


def _content(path):
    return path.read_bytes().decode()


def _fight_guard():
    guard = MapGuard(states=FIGHT_STATES)
    guard.on = {
        "world": lambda p: guard.shown(p) == "world" or _content(p).startswith("world"),
        "encounter": lambda p: _content(p) == "encounter",
        "combat_bar": lambda p: _content(p) == "combat"}
    return guard


def _fight_title(most=route_pool.ENCOUNTER_MOVES):
    synthetic = title_run.make_title()
    return dataclasses.replace(
        route_pool.POOL_ENCOUNTER, mounted=synthetic.mounted, spares=synthetic.spares,
        save_disk=synthetic.save_disk, read_slot=synthetic.read_slot,
        slot_letters=synthetic.slot_letters, slot_files=synthetic.slot_files,
        interstitials=(),
        route=(*route_pool.POOL_ENCOUNTER.route[:-2],
               (("NP8", "NP4", most), "encounter", "until_encounter"),
               ("C", "combat_bar", "key")))


def _fight(tmp_path, clock, guest, *, title=None, encounter=True):
    path = title_run.manifest_for(tmp_path)
    data = json.loads(path.read_text())
    if encounter:
        data["encounter"] = True
    path.write_text(json.dumps(data))
    return acceptance.run_recon(
        path, guest=guest, guard=_fight_guard(), identity=_IdentityMap(),
        holder="wish303-test", audio_proof=_audio_proof(tmp_path),
        title=title or _fight_title(), reload=True)


def test_a_fight_walks_turns_at_a_wall_meets_the_encounter_and_keeps_the_battlefield(
        tmp_path, clock):
    guest = FightGuest(clock, met=4, blocked={2})
    result = _fight(tmp_path, clock, guest)
    assert result["success"], result["error"]
    keys = title_run._keys(guest)
    walk_keys = keys[keys.index("NP8"):]
    assert walk_keys == ["NP8", "NP8", "NP4", "NP8", "NP8", "C"]
    assert result["encounter_walk"] == {"state": "encounter", "steps": 4, "turns": 1,
                                        "met": True, "blocked_at": [2]}
    assert result["battlefield"].endswith("-combat_bar.png")
    assert result["disks_unchanged"] and all(result["disks_unchanged"].values())
    assert "D" not in keys and "S" not in keys


def test_a_fight_that_meets_nothing_stops_at_its_bound(tmp_path, clock):
    guest = FightGuest(clock, met=None)
    result = _fight(tmp_path, clock, guest, title=_fight_title(most=3))
    assert not result["success"]
    assert "no encounter screen within 3 steps" in result["error"]
    assert title_run._keys(guest).count("NP8") == 3 and "C" not in title_run._keys(guest)


def test_a_fight_needs_a_manifest_prepared_for_it(tmp_path, clock):
    with pytest.raises(RouteError, match="prepared with --encounter"):
        _fight(tmp_path, clock, FightGuest(clock, met=1), encounter=False)


def test_the_fight_crops_name_the_world_screen_for_the_guard_check(tmp_path, clock):
    guest = FightGuest(clock, met=2)
    _fight(tmp_path, clock, guest)
    shots = tmp_path / "recon1" / "shots"
    world = sorted(p.name for p in shots.glob("*-world-again-*.png"))
    met = sorted(p.name for p in shots.glob("*-encounter-again-*.png"))
    assert world == ["07-world-again-01.png", "07-world-again-01.raw.png"]
    assert met == ["07-encounter-again-02.png", "07-encounter-again-02.raw.png"]
    assert (shots / "07-encounter-again-02.png").read_bytes() == b"encounter"


class SurpriseGuest(FightGuest):
    """`FightGuest` whose `met`-th step shows the surprise page, which RETURN turns into the first
    command bar with no encounter menu between, as a surprised party's fight opens."""

    def press(self, holder, key, timeout=None):
        surprised = self.shown == "surprised"
        super().press(holder, key, timeout)
        if self.shown == "encounter":
            self.shown = "surprised"
        elif surprised and key == "RET":
            self.shown = "combat"


def _surprise_guard():
    guard = _fight_guard()
    guard.states.add("surprised")
    guard.on["surprised"] = lambda p: _content(p) == "surprised"
    return guard


def test_a_surprised_party_answers_the_page_and_reaches_the_first_command_bar_without_combat(
        tmp_path, clock):
    path = title_run.manifest_for(tmp_path)
    path.write_text(json.dumps({**json.loads(path.read_text()), "encounter": True}))
    guest = SurpriseGuest(clock, met=2)
    title = dataclasses.replace(_fight_title(), interstitials=route_pool.POOL_ENCOUNTER.interstitials)
    result = acceptance.run_recon(
        path, guest=guest, guard=_surprise_guard(), identity=_IdentityMap(),
        holder="wish303-test", audio_proof=_audio_proof(tmp_path), title=title, reload=True)
    assert result["success"], result["error"]
    keys = title_run._keys(guest)
    assert keys[keys.index("NP8"):] == ["NP8", "NP8", "RET"]
    assert result["encounter_walk"] == {"state": "encounter", "steps": 2, "turns": 0,
                                        "met": True, "blocked_at": [], "opened": "combat_bar"}
    assert {"skipped": "C", "step": 8, "opened_by": 7} in result["events"]
    assert result["battlefield"].endswith("07-combat_bar.png")
    assert (tmp_path / "recon1" / "shots" / "07-combat_bar-again-02.png").read_bytes() == b"combat"


def test_route_kinds_include_until_encounter():
    assert "until_encounter" in route._STEP_KINDS


# --- a temple run, end to end on fakes ------------------------------------------------------

def _temple_read_slot(disk, letter):
    try:
        raw = disk.read_file(f"/SAVE/savgam{letter}.sav")
    except Exception:
        return {"missing": True, "sha256": None}
    data = json.loads(raw)
    return {"sha256": "x", **data}


class TempleGuest(title_run.TitleGuest):
    """Saves C where the party stands and D on the temple square with BRUTUS as `raised` leaves him."""

    def __init__(self, clock, raised, money=PAID):
        super().__init__(clock, land=dict(SQUARE))
        self.raised, self.money = raised, money

    def _write(self, letter, place):
        remote = next(r for r in self.mounted if r and r.endswith(f"-{self.save_key}.adf"))
        disk = AmigaDisk(self.remote[remote])
        status, money = (self.raised, self.money) if letter == "D" else (6, STAGED)
        disk.write_file(f"/SAVE/savgam{letter}.sav", json.dumps(
            {**_slot(place, status=status, money=money), "names": title_run.NAMES}).encode())
        self.remote[remote] = disk.to_bytes()


def _temple_run(tmp_path, clock, monkeypatch, raised, money=PAID, temple_route=True):
    synthetic = title_run.make_title()
    title = dataclasses.replace(
        route_pool.POOL_TEMPLE if temple_route else synthetic, mounted=synthetic.mounted, spares=synthetic.spares,
        save_disk=synthetic.save_disk, read_slot=_temple_read_slot,
        slot_letters=synthetic.slot_letters, slot_files=synthetic.slot_files, interstitials=())
    path = title_run.manifest_for(tmp_path)
    data = json.loads(path.read_text())
    data["temple"] = {"member": "BRUTUS"}
    before = tmp_path / "save-unstaged.adf"
    before.write_bytes(pathlib.Path(data["disks"]["boot"]["path"]).read_bytes())
    data["staged_record"] = {"fields": {"gold": {"before": 0, "after": STAGED_GOLD}},
                             "before": {"path": str(before), "sha256": staging.sha256(before)}}
    monkeypatch.setattr(acceptance, "check_staged_member", lambda *_args: None)
    path.write_text(json.dumps(data))
    states = {s for _, s, _ in title.route} | {"title"}
    guest = TempleGuest(clock, raised, money)
    result = acceptance.run_recon(
        path, guest=guest, guard=MapGuard(states=states), identity=_IdentityMap(),
        holder="wish303-test", audio_proof=_audio_proof(tmp_path), title=title, accept=True)
    return guest, result


def test_a_temple_run_passes_when_slot_d_holds_him_raised_on_the_temple_square(tmp_path, clock, monkeypatch):
    guest, result = _temple_run(tmp_path, clock, monkeypatch, raised=0)
    assert result["success"], (result["error"], result["read"]["verdicts"])
    assert result["walk"]["raised"] == {"status": 0, "control": 0, "node_32": False,
                                        "gold": 0, "platinum": 100, "paid": True}
    keys = title_run._keys(guest)
    assert keys.count("Y") == 2 and keys.count("H") == 2


def test_a_temple_run_whose_slot_d_still_holds_him_dead_fails(tmp_path, clock, monkeypatch):
    _guest, result = _temple_run(tmp_path, clock, monkeypatch, raised=6)
    assert not result["success"]
    assert any("not raised" in line for line in result["read"]["verdicts"])


def test_a_temple_run_whose_raised_member_kept_his_gold_fails(tmp_path, clock, monkeypatch):
    _guest, result = _temple_run(tmp_path, clock, monkeypatch, raised=0, money=STAGED)
    assert not result["success"]
    assert any("not raised" in line and "expected 500 after paying 5500" in line
               for line in result["read"]["verdicts"])


def test_a_run_not_on_the_temple_route_is_not_judged_by_the_temple_verdict(tmp_path, clock, monkeypatch):
    _guest, result = _temple_run(tmp_path, clock, monkeypatch, raised=0, temple_route=False)
    assert "raised" not in result["walk"]


def test_a_staged_record_whose_unstaged_disk_changed_stops_the_run_before_the_claim(
        tmp_path, clock):
    before = tmp_path / "save-unstaged.adf"
    before.write_bytes(b"unstaged")
    path = title_run.manifest_for(tmp_path)
    data = json.loads(path.read_text())
    data["staged_record"] = {"before": {"path": str(before), "sha256": "0" * 64}}
    path.write_text(json.dumps(data))
    guest = title_run.TitleGuest(clock)
    with pytest.raises(RouteError, match="changed from preparation"):
        acceptance.run_recon(
            path, guest=guest, guard=MapGuard(states=("title", *title_run.STATES)),
            identity=_IdentityMap(), holder="wish303-test", audio_proof=_audio_proof(tmp_path),
            title=title_run.make_title(), accept=True)
    assert not any(c[0] == "claim" for c in guest.calls)


class _WalkIdentity(_IdentityMap):
    """`world` rule failing on the first `wrong` looks at a walking frame."""

    def __init__(self, wrong):
        super().__init__()
        self.wrong, self.looks = wrong, 0

    def __contains__(self, state):
        return state == "world" or super().__contains__(state)

    def __call__(self, state, path):
        if state != "world" or not _content(path).startswith("world"):
            return True
        self.looks += 1
        return self.looks > self.wrong


class _DrawingFightGuest(FightGuest):
    """A walking frame differs on every grab, as a list does while it is drawn."""

    def _frame(self):
        frame = super()._frame()
        return f"{frame} grab {self.grabs}" if self.walking else frame


def _walk(tmp_path, clock, guest, identity, most=2):
    path = title_run.manifest_for(tmp_path)
    data = json.loads(path.read_text())
    data["encounter"] = True
    path.write_text(json.dumps(data))
    return acceptance.run_recon(
        path, guest=guest, guard=_fight_guard(), identity=identity,
        holder="wish355-test", audio_proof=_audio_proof(tmp_path),
        title=_fight_title(most=most), reload=True)


def test_a_walk_screen_whose_party_is_drawn_late_is_polled_and_no_key_goes_out(tmp_path, clock):
    identity = _WalkIdentity(wrong=3)
    guest = _DrawingFightGuest(clock, met=None)
    result = _walk(tmp_path, clock, guest, identity)
    assert identity.looks > 3
    assert "no encounter screen within 2 steps" in result["error"]
    assert title_run._keys(guest).count("NP8") == 2


def test_a_walk_screen_with_the_wrong_party_on_one_frame_stops_after_three_looks(tmp_path, clock):
    identity = _WalkIdentity(wrong=10 ** 6)
    guest = FightGuest(clock, met=None)
    result = _walk(tmp_path, clock, guest, identity)
    assert identity.looks == 3
    assert "shows a party other than the prepared party" in result["error"]
    assert title_run._keys(guest).count("NP8") == 1
