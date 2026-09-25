"""The half of `tools/c64/c64acceptance.py` a machine with no emulator can check.

The driver stages effect rows, trait slots and item bytes into a copy of a C64
save, boots it and reads the camp list of spells in effect and a character's
ITEMS list off the screen. What is asserted here is that the staging writes the
bytes the step names and nothing else, that a step list the driver cannot run
is refused before a slot is claimed, and that the two screen readers read the
screens the game's own strings put up: the camp list (`CAMP $16C3`-`$1797`,
" IS AFFECTED BY:" and "PRESS ANY KEY TO CONTINUE") and the item list, where
Detect Magic prints a `*` before a magic item's name (`LIBRARY $39B7`-`$39C3`).

The composed screens are built from those strings and the Pool item-list
capture `cited/252/probe4/screen.txt`, not from a live run. The fixture save is
the committed `tests/fixtures/savedgame0.bin` party written as a disk by
`dos_codec.save_disk`, the way `tests/convert/test_runningeffects.py` builds
one. Two tests read the player's `PORSAVE13.D64` and skip without it.
"""

from __future__ import annotations

import json
import pathlib

import gamedata
import pytest

from goldbox import c64_save, dos_codec, effects
from goldbox.c64_port import POOL_OF_RADIANCE
from goldbox.d64 import D64, split_load_address
from goldbox.items import ITEM_SIZE
from goldbox.savegame import SaveGame0, SaveGame1
from tools.c64 import c64acceptance as A

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"


def _fixture_disk(tmp_path: pathlib.Path) -> pathlib.Path:
    payload = SaveGame0.from_prg((FIXTURES / "savedgame0.bin").read_bytes()).to_bytes()
    save1 = SaveGame1.from_prg((FIXTURES / "savedgame1.bin").read_bytes()).to_bytes()
    path = tmp_path / "fixture-source.d64"
    path.write_bytes(dos_codec.save_disk(payload, save1, POOL_OF_RADIANCE).to_bytes())
    return path


def _payload(path: pathlib.Path) -> bytes:
    image = D64.open(str(path))
    return split_load_address(image.read_file(POOL_OF_RADIANCE.save_file))[1]


# --- parsing -----------------------------------------------------------------

def test_a_row_stage_is_read_as_effectdrive_reads_it():
    assert A.parse_rows(["63=05:FF:0A:03"]) == [(63, 5, 0xFF, 0x0A, 0x03)]
    assert A.parse_rows(["63=05:FF:0A:03,62=01:00:2F:01"]) == [
        (63, 5, 0xFF, 0x0A, 0x03), (62, 1, 0, 0x2F, 1)]


@pytest.mark.parametrize("text", ["63=05:FF:0A", "64=05:FF:0A:03",
                                  "63=105:FF:0A:03"])
def test_a_row_stage_out_of_range_is_refused(text):
    with pytest.raises(ValueError):
        A.parse_rows([text])


def test_trait_and_item_stages():
    assert A.parse_traits(["0:9=38"]) == [(0, 9, 38)]
    assert A.parse_items(["1:2:4=1", "0:15:10=0x20"]) == [(1, 2, 4, 1),
                                                         (0, 15, 10, 0x20)]
    for bad in ("0:10=38", "8:0=1"):
        with pytest.raises(ValueError):
            A.parse_traits([bad])
    for bad in ("1:16:4=1", "1:2:16=1", "1:2:4=256", "1:2=1"):
        with pytest.raises(ValueError):
            A.parse_items([bad])


def test_the_steps_parse_and_keep_their_arguments():
    steps = A.parse_steps(["load", "camp-list", "items LADY KATHERINE",
                           "items 2", "rest 8h", "rest 1h30m", "peek $4900 64",
                           "fight 90", "save"])
    assert [(s.verb, s.arg) for s in steps] == [
        ("load", ""), ("camp-list", ""), ("items", "LADY KATHERINE"),
        ("items", "2"), ("rest", "8h"), ("rest", "1h30m"),
        ("peek", "$4900 64"), ("fight", "90"), ("save", "")]
    assert A.parse_rest("8h") == (0, 8)
    assert A.parse_rest("1h30m") == (30, 1)
    assert A.parse_peek("$4900 64") == (0x4900, 64)


@pytest.mark.parametrize("steps", [
    [],                                   # nothing to do
    ["camp-list"],                        # load must come first
    ["load", "load"],                     # one boot, one load
    ["load", "dance"],                    # not a step
    ["load", "items"],                    # whose items?
    ["load", "save now"],                 # save takes nothing
    ["load", "rest 8"],                   # a unit is required
    ["load", "rest 61m"],                 # the minutes byte is under an hour
    ["load", "peek 4900"],                # and how many bytes?
    ["load", "fight 0"],
])
def test_a_step_list_the_driver_cannot_run_is_refused(steps):
    with pytest.raises(ValueError):
        A.parse_steps(steps)


def test_a_title_the_driver_does_not_boot_is_refused_before_a_slot_is_claimed(
        tmp_path, monkeypatch):
    def no_slot(*a, **k):
        raise AssertionError("a slot was claimed")
    monkeypatch.setattr(A.S, "claim_slot", no_slot)
    with pytest.raises(SystemExit) as info:
        A.main(["--title", "ssb", "--save", str(_fixture_disk(tmp_path)),
                "--steps", "load", "camp-list", "--out", str(tmp_path / "out")])
    assert info.value.code == 2


# --- staging -----------------------------------------------------------------

def test_staging_writes_exactly_the_named_bytes(tmp_path):
    src = _fixture_disk(tmp_path)
    dest = tmp_path / "staged-copy.d64"
    before = _payload(src)
    took = A.stage(src, dest, "pool-of-radiance",
                   rows=[(63, 5, 0xFF, 0x0A, 0x03)],
                   traits=[(0, 9, 38)],
                   items=[(0, 2, 4, 1)])
    after = _payload(dest)
    box = c64_save.CONTAINERS["pool-of-radiance"]
    wanted = {
        effects.EFFECT_ID_OFFSET + 63: 5,
        effects.EFFECT_OWNER_OFFSET + 63: 0xFF,
        effects.EFFECT_DURATION_OFFSET + 63: 0x0A,
        effects.EFFECT_MAGNITUDE_OFFSET + 63: 0x03,
        box.slot(0) + A.TRAIT_SLOT + 9: 38,
        box.items(0) + 2 * ITEM_SIZE + 4: 1,
    }
    changed = {i: after[i] for i in range(len(after)) if after[i] != before[i]}
    assert changed == {i: v for i, v in wanted.items() if before[i] != v}
    assert all(after[i] == v for i, v in wanted.items())
    assert len(after) == len(before)
    assert _payload(src) == before, "the source was written"
    assert took["rows"] == [{"slot": 63, "was": [before[i + 63] for i in (
        effects.EFFECT_ID_OFFSET, effects.EFFECT_OWNER_OFFSET,
        effects.EFFECT_DURATION_OFFSET, effects.EFFECT_MAGNITUDE_OFFSET)],
        "now": [5, 0xFF, 0x0A, 0x03]}]
    assert took["effects"] == [[63, 5, 0xFF, 0x0A, 0x03]]
    assert took["magic_items"]["0"] == [2]


def test_staging_refuses_a_save_of_another_title(tmp_path):
    with pytest.raises(ValueError, match="Pool of Radiance"):
        A.stage(_fixture_disk(tmp_path), tmp_path / "staged-copy.d64",
                "curse-of-the-azure-bonds")


def test_stage_only_writes_the_evidence_and_claims_no_slot(tmp_path, monkeypatch):
    def no_slot(*a, **k):
        raise AssertionError("a slot was claimed")
    monkeypatch.setattr(A.S, "claim_slot", no_slot)
    out = tmp_path / "evidence"
    rc = A.main(["--title", "pool", "--save", str(_fixture_disk(tmp_path)),
                 "--stage-row", "63=05:FF:0A:03", "--stage-only",
                 "--steps", "load", "items BRUTUS", "--out", str(out)])
    assert rc == 0
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["staged"]["effects"] == [[63, 5, 0xFF, 0x0A, 0x03]]
    assert summary["completed"] is True and summary["results"] == []
    assert (out / "staged.D64").is_file()


def test_an_evidence_directory_is_never_reused(tmp_path):
    out = tmp_path / "evidence"
    out.mkdir()
    (out / "run.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(SystemExit) as info:
        A.main(["--title", "pool", "--save", str(_fixture_disk(tmp_path)),
                "--stage-only", "--steps", "load", "--out", str(out)])
    assert info.value.code == 2


def test_staging_matches_the_two_drivers_it_stands_in_for(tmp_path):
    """On a real Pool save, the same stage through `effectdrive.stage_effects`
    and `traitdrive.stage_traits` gives the same disk byte for byte."""
    porsave = gamedata.save_disk("PORSAVE13")
    from tools.c64 import effectdrive, traitdrive
    from tools.c64 import session as S
    ours = tmp_path / "ours.d64"
    theirs = tmp_path / "theirs.d64"
    A.stage(porsave, ours, "pool-of-radiance",
            rows=[(63, 5, 0xFF, 0x0A, 0x03), (62, 5, 2, 0x0A, 0x03)],
            traits=[(1, 9, 38)])
    S.stage_writable(porsave, theirs)
    effectdrive.stage_effects(theirs, [(63, 5, 0xFF, 0x0A, 0x03),
                                       (62, 5, 2, 0x0A, 0x03)])
    traitdrive.stage_traits(theirs, [(1, 9, 38)])
    assert ours.read_bytes() == theirs.read_bytes()


def test_porsave13_holds_no_magic_item_so_a_run_must_stage_one(tmp_path):
    """The reading needs an item Detect Magic marks: bonus byte `+4` not 0
    (`LIBRARY $39BC`). PORSAVE13's six characters hold 55 items and none."""
    porsave = gamedata.save_disk("PORSAVE13")
    took = A.stage(porsave, tmp_path / "porsave13-copy.d64", "pool-of-radiance")
    assert took["magic_items"] == {}
    took = A.stage(porsave, tmp_path / "porsave13-item.d64", "pool-of-radiance",
                   items=[(1, 2, 4, 1)])
    assert took["magic_items"] == {"1": [2]}


# --- the screens ---------------------------------------------------------------

def _window(lines: dict[int, str], bar: str = "") -> list[str]:
    """A 25-row screen in the frame the Pool capture shows: `@[[..[@` top and
    bottom, `$` down both sides, text from column 1, and the bar on row 24."""
    rows = []
    for r in range(25):
        if r in (0, 23):
            rows.append("@" + "[" * 38 + "@")
        elif r == 24:
            rows.append(bar.ljust(40))
        else:
            rows.append("$" + lines.get(r, "").ljust(38) + "$")
    return rows


def test_a_camp_list_page_names_who_and_what():
    rows = _window({1: "THE WHOLE PARTY  IS AFFECTED BY:",
                    3: "DETECT MAGIC", 4: "BLESS"},
                   bar="PRESS ANY KEY TO CONTINUE")
    page = A.camp_list_page(rows)
    assert page == A.CampPage("THE WHOLE PARTY", ["DETECT MAGIC", "BLESS"], True)


def test_an_empty_camp_list_page_lists_nothing():
    rows = _window({1: "MALCYON IS AFFECTED BY:"},
                   bar="PRESS ANY KEY TO CONTINUE")
    assert A.camp_list_page(rows) == A.CampPage("MALCYON", [], True)


def _whom_screen(names=("BRUTUS", "LADY KATHERINE", "MALCYON")) -> list[str]:
    """The whom menu as PORSAVE13's capture draws it: the party panel, from
    column 17 under `NAME  AC HP`, with `THE WHOLE PARTY` and `EXIT` under the
    names and the question on row 24."""
    rows = [" " * 40 for _ in range(24)]

    def put(r, text):
        rows[r] = rows[r][:17] + text.ljust(23)[:23]
    put(2, "NAME            AC HP")
    for i, name in enumerate([*names, "THE WHOLE PARTY", "EXIT"]):
        put(4 + i, name.ljust(17) + ("6 5" if i < len(names) else ""))
    return rows + ["DISPLAY SPELLS ON WHOM?".ljust(40)]


def test_the_whom_menu_is_read_off_the_party_panel():
    rows = _whom_screen()
    assert A.camp_list_page(rows) is None
    assert A.whom_entries(rows) == ["BRUTUS", "LADY KATHERINE", "MALCYON",
                                    "THE WHOLE PARTY"]


def test_the_world_panel_is_not_a_whom_menu():
    rows = _whom_screen()
    rows[24] = WORLD_BAR.ljust(40)
    assert A.whom_entries(rows) == []


PROBE4 = {1: "MALCYON", 3: "EQUIPPED ITEM", 5: " YES CLOAK",
          6: " YES 13 DART", 7: " NO  DAGGER", 8: " EXIT"}


def test_the_item_list_reads_the_pool_capture():
    rows = _window(PROBE4, bar="READY TRADE DROP EXIT")
    entries = A.item_entries(rows)
    assert [(e["readied"], e["text"], e["marked"]) for e in entries] == [
        (True, "CLOAK", False), (True, "13 DART", False),
        (False, "DAGGER", False)]


def test_a_detect_magic_mark_is_read_where_the_game_prints_it():
    rows = _window({**PROBE4, 6: " YES 13 *DART +1"},
                   bar="READY TRADE DROP EXIT")
    entries = A.item_entries(rows)
    assert [e["marked"] for e in entries] == [False, True, False]
    assert entries[1]["text"] == "13 *DART +1"


def test_compare_names_the_rows_that_differ_only_by_the_mark(tmp_path):
    def summary(where, dart):
        rows = _window({**PROBE4, 6: dart}, bar="READY TRADE DROP EXIT")
        where.mkdir()
        (where / "summary.json").write_text(json.dumps({"results": [
            {"step": "items MALCYON", "verb": "items", "who": "MALCYON",
             "entries": A.item_entries(rows)},
            {"step": "camp-list", "verb": "camp-list",
             "lists": {"MALCYON": ["DETECT MAGIC"] if "*" in dart else []}},
        ]}), encoding="utf-8")
        return where
    got = A.compare(summary(tmp_path / "control", " YES 13 DART +1"),
                    summary(tmp_path / "staged", " YES 13 *DART +1"))
    assert got["items"] == [{"who": "MALCYON", "row": 1,
                             "a": "YES 13 DART +1", "b": "YES 13 *DART +1",
                             "only_the_mark": True}]
    assert got["camp_list"] == [{"who": "MALCYON", "only_a": [],
                                 "only_b": ["DETECT MAGIC"]}]


# --- the steps, on a session that serves the screens the game draws ------------

WORLD_BAR = "MOVE VIEW CAST AREA ENCAMP SEARCH LOOK"
CAMP = "ENCAMP:SAVE VIEW MAGIC REST ALTER EXIT"
MAGIC = "CAST MEMORIZE SCRIBE DISPLAY REST EXIT"


class FakeScreen:
    def __init__(self, rows):
        self._rows = rows

    def row(self, r):
        return self._rows[r]


class FakeKeyboard:
    def __init__(self, session):
        self.session = session

    def key(self, name, *timing):
        return self.session._go(("key", name))

    def screenshot(self, path):
        pathlib.Path(path).write_bytes(b"")
        return True


class FakeSession:
    """The screens `CAMP $16C3` and `LIBRARY $4424` put up, as a state machine
    moved by the keys the driver sends. A key with no transition fails the
    test, so a step that presses anything the game would not take is seen."""

    def __init__(self, screens, moves, start):
        self.screens, self.moves, self.state = screens, moves, start
        self.kbd = FakeKeyboard(self)
        self.sent = []

    def _go(self, what):
        self.sent.append(what)
        key = (self.state, what)
        assert key in self.moves, f"no transition for {key}"
        self.state = self.moves[key]
        return True

    def screen(self):
        return FakeScreen(self.screens[self.state])

    def handle_prompt(self, s=None):
        return False

    def settle(self, seconds=0):
        pass

    def select_bar(self, label, row=24, timeout=0):
        return self._go(("bar", label))

    def select_row(self, label, timeout=0, column=None):
        return self._go(("row", label))

    def select_party(self, index, timeout=0):
        return self._go(("party", index))

    def press_kernal(self, code):
        return self._go(("key", code))

    def leave_sheet(self):
        return self._go(("leave",))


def test_curse_attack_records_the_named_fighters_row_transition(monkeypatch):
    from types import SimpleNamespace

    row = [[62, 25, 0, 0, 5]]
    actors = [SimpleNamespace(name="SHARA", index=1),
              SimpleNamespace(name="PHILIPPE", index=0)]

    class FightSession:
        def battle(self):
            return object()

        def acting(self, battle):
            return actors.pop(0)

    def strike(sess, state):
        if not actors:
            row.clear()
        return A.S.ATTACK

    monkeypatch.setattr(A.S.Session, "melee_turn", strike)
    run = A.CurseRun.__new__(A.CurseRun)
    run.attack_by = "PHILIPPE"
    run.attack_owner = 0
    run.attack_evidence = None
    run.first_effect_loss = None
    run.last_effect_row = None
    run.reading = lambda: {"effects": row.copy()}
    captures = []
    run.capture = lambda tag: captures.append(tag)
    run.log = SimpleNamespace(emit=lambda *a, **k: None)
    sess = FightSession()
    bar = SimpleNamespace(text="MOVE VIEW AIM USE QUICK DONE")

    assert run._named_melee(sess, bar) == A.S.ATTACK
    assert run.attack_evidence is None
    assert run._named_melee(sess, bar) == A.S.ATTACK
    assert run.attack_evidence == {
        "actor": "PHILIPPE", "index": 0, "owner": 0,
        "bar": bar.text, "chosen": A.S.ATTACK,
        "before": [62, 25, 0, 0, 5], "after": None}
    assert captures.index("attack-before-PHILIPPE") < captures.index(
        "attack-after-PHILIPPE")
    assert captures.count("tactic-before") == captures.count("tactic-after") == 2


@pytest.mark.parametrize("loss_phase", ["route-step", "combat-setup", "tactic-after"])
def test_curse_keeps_the_first_effect_loss_when_no_attack_was_returned(
        monkeypatch, loss_phase):
    from types import SimpleNamespace

    row = [[62, 25, 0, 0, 5]]
    events = []
    actors = iter((SimpleNamespace(name="PHILIPPE", index=0, x=4, y=5, hp=33),
                   SimpleNamespace(name="PHILIPPE", index=0, x=5, y=5, hp=33),
                   SimpleNamespace(name="SHARA", index=1, x=6, y=5, hp=20),
                   SimpleNamespace(name="PHILIPPE", index=0, x=5, y=5, hp=28)))
    answers = iter(("MOVE", "GUARD", "QUIT", A.S.ATTACK))

    class FightSession:
        combat = False

        def battle(self):
            return object()

        def acting(self, battle):
            return next(actors)

        def mode(self):
            return 2 if self.combat else 1

    def choose(*args):
        answer = next(answers)
        if answer == "QUIT" and loss_phase == "tactic-after":
            row.clear()
        return answer

    monkeypatch.setattr(A.S.Session, "melee_turn", choose)
    run = A.CurseRun.__new__(A.CurseRun)
    run.sess = FightSession()
    run.attack_by = "PHILIPPE"
    run.attack_owner = 0
    run.attack_evidence = None
    run.first_effect_loss = None
    run.last_effect_row = None
    run.reading = lambda: {"effects": [r.copy() for r in row], "clock": [0] * 6}
    run.capture = lambda tag: [tag]
    run.log = SimpleNamespace(emit=lambda kind, **kw: events.append((kind, kw)))
    if loss_phase == "route-step":
        run.observe_curse("route-before")
        row.clear()
        run.observe_curse("route-step")
        row.append([62, 25, 0, 0, 5])
    elif loss_phase == "combat-setup":
        run.observe_curse("route-after")
        row.clear()
        run.observe_curse("combat-setup")
        row.append([62, 25, 0, 0, 5])

    run.sess.combat = True
    bar = SimpleNamespace(text="MOVE VIEW AIM QUICK DONE")
    assert run._named_melee(run.sess, bar) == "MOVE"
    assert run._named_melee(run.sess, bar) == "GUARD"
    assert run._named_melee(run.sess, bar) == "QUIT"
    assert run._named_melee(run.sess, bar) == A.S.ATTACK
    observed = [kw for kind, kw in events if kind == "curse-observation"]
    assert [kw["chosen"] for kw in observed if "chosen" in kw] == [
        "MOVE", "GUARD", "QUIT", A.S.ATTACK]
    assert any((kw.get("actor") or {}).get("name") == "SHARA" for kw in observed)
    assert run.first_effect_loss["phase"] == loss_phase
    assert any(kw.get("first_effect_loss") == run.first_effect_loss
               for kw in observed)
    assert run.attack_evidence is None


def test_curse_quit_control_uses_only_done_and_quit():
    from types import SimpleNamespace

    sent = []

    class Session:
        def combat_bar(self, word, timeout):
            sent.append(word)
            return True

        def await_bar(self, kinds, timeout):
            assert kinds == (A.S.BAR_DONE,)
            return object()

        def combat_state(self):
            return SimpleNamespace(text="GUARD DELAY QUIT SPEED EXIT")

    assert A.CurseRun._quit_turn(Session()) == "QUIT"
    assert sent == ["DONE", "QUIT"]


def test_curse_plain_fight_keeps_plain_route_and_tactic(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from tools.c64 import laterbattle
    from tools.curse_of_the_azure_bonds import cursethac0

    calls = []

    class Route:
        last_goto_steps = 3

        def __init__(self, out, quiet):
            self.file = SimpleNamespace(close=lambda: None)
            calls.append("plain-route")

        def goto(self, target, steps, geo):
            return True

    class Session:
        def in_combat(self):
            return True

        def await_bar(self, kinds, timeout, interval):
            calls.append("optional-command-wait")
            return None

        def fight(self, *, budget, tactic):
            calls.append(("fight", tactic))
            return A.S.FightResult("ended", 1, 1.0, [], [])

    monkeypatch.setattr(laterbattle, "Battle", Route)
    monkeypatch.setattr(cursethac0, "area_geo", lambda *a: ("GEO01", object()))
    run = A.CurseRun.__new__(A.CurseRun)
    run.attack_by = ""
    run.attack_owner = None
    run.attack_evidence = None
    run.quit_evidence = None
    run.sess = Session()
    run.out = tmp_path
    run.staged_disk = tmp_path / "staged.D64"
    run.disks = "unused"
    run.to_world = lambda: True
    run.await_combat = lambda: True
    run.capture = lambda tag: calls.append(tag)
    run.observe_curse = lambda *a, **k: pytest.fail("diagnostic observation")
    got = run.fight("10", "I", 5)
    assert got["walked"] == 3
    assert calls[0] == "plain-route"
    assert calls[-3] == "optional-command-wait"
    assert calls[-2] == ("fight", A.S.Session.melee_turn)


@pytest.mark.parametrize("advance", ["rejected", "actor", "combat-ended"])
def test_curse_quit_requires_turn_advancement(advance):
    from types import SimpleNamespace

    philippe = SimpleNamespace(name="PHILIPPE", index=0, x=5, y=5, hp=33)
    shara = SimpleNamespace(name="SHARA", index=1, x=6, y=5, hp=20)
    events = []

    class Session:
        calls = 0

        def battle(self):
            return object()

        def acting(self, battle):
            self.calls += 1
            return shara if advance == "actor" and self.calls > 1 else philippe

        def mode(self):
            return 1 if advance == "combat-ended" and self.calls > 0 else 2

        def combat_state(self):
            return SimpleNamespace(text="MOVE VIEW AIM QUICK DONE")

        def settle(self, seconds):
            pass

    run = A.CurseRun.__new__(A.CurseRun)
    run.sess = Session()
    run.attack_by = "PHILIPPE"
    run.attack_owner = 0
    run.attack_evidence = None
    run.quit_evidence = None
    run.quit_nonattacking = True
    run.first_effect_loss = None
    run._quit_turn = lambda sess: "QUIT"
    run.capture = lambda tag: []
    run.observe_curse = lambda phase, **kw: (
        events.append((phase, kw)) or {"row": [62, 25, 0, 0, 5]})
    run.log = SimpleNamespace(emit=lambda *a, **k: None)
    assert run._named_melee(run.sess, SimpleNamespace(text="MOVE VIEW AIM")) == "QUIT"
    if advance != "rejected":
        assert run.quit_evidence["advanced_to"] == (
            "SHARA" if advance == "actor" else "combat-ended")
        assert run.quit_evidence["persisted"] is True
        assert any(phase == "quit-confirmed" for phase, _ in events)
    else:
        assert run.quit_evidence is None
        assert sum(phase == "quit-await" for phase, _ in events) == 8


def test_curse_one_step_skips_wall_edge_and_occupant_and_checks_landing():
    from types import SimpleNamespace

    actor = SimpleNamespace(name="PHILIPPE", index=0, x=5, y=5, hp=33)
    other = SimpleNamespace(name="SHARA", index=1, x=5, y=6, hp=20)
    picked = []

    class Battle:
        shape = SimpleNamespace(holds=lambda x, y: x >= 5 and y >= 5)
        combatants = (actor, other)

        @staticmethod
        def square(x, y):
            return 1 if (x, y) == (6, 5) else 0

        @staticmethod
        def at(x, y):
            return other if (x, y) == (5, 6) else None

    class Session:
        kbd = SimpleNamespace(key=lambda key, *args: picked.append(key))

        def battle(self):
            return Battle()

        def acting(self, battle):
            return actor

        def combat_bar(self, word, timeout):
            return True

        def await_bar(self, kinds, timeout):
            return object()

        def settle(self, seconds):
            pass

    run = A.CurseRun.__new__(A.CurseRun)
    run.sess = Session()
    run.observe_curse = lambda phase, **kw: {}
    with pytest.raises(A.StepFailed, match="did not reach"):
        run.probe_one_step()
    assert picked == ["KP_3"]  # The only open, unoccupied in-bounds square.


def test_curse_missing_first_command_bar_keeps_screen_and_fails():
    class Session:
        def await_bar(self, kinds, timeout, interval):
            return None

    run = A.CurseRun.__new__(A.CurseRun)
    run.sess = Session()
    captures = []
    run.capture = lambda tag: captures.append(tag)
    with pytest.raises(A.StepFailed, match="first command bar"):
        run.first_command_bar()
    assert captures == ["lost-first-command-bar"]


def test_curse_observes_done_branch_outside_tactic_and_restores_end_turn():
    from types import SimpleNamespace

    row = [[62, 25, 0, 0, 5]]
    events = []

    class Session(A.S.Session):
        done = False

        def in_combat(self):
            return True

        def mode(self):
            return 2

        def screen(self):
            return SimpleNamespace(text=lambda: "GUARD DELAY QUIT",
                                   row=lambda n: "GUARD DELAY QUIT",
                                   colours=bytes(1000), codes=bytes(1000))

        def combat_state(self, screen=None):
            return A.S.CombatBar(A.S.BAR_DONE if not self.done else "idle",
                                 "GUARD DELAY QUIT")

        def handle_prompt(self, screen=None):
            pass

        def idle(self, seconds):
            import time
            time.sleep(0.03)

        def battle(self):
            return object()

        def mon(self, timeout):
            class Monitor:
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    pass

                def read(self, address, length):
                    return bytes(length)

                def resume(self):
                    pass

            return Monitor()

        def acting(self, battle):
            return SimpleNamespace(name="PHILIPPE", index=0, x=5, y=5, hp=33)

        def end_turn(self):
            row.clear()
            self.done = True
            return "GUARD"

    sess = Session.__new__(Session)
    run = A.CurseRun.__new__(A.CurseRun)
    run.sess = sess
    run.attack_owner = 0
    run.first_effect_loss = None
    run.last_effect_row = None
    run.reading = lambda: {"effects": [r.copy() for r in row], "clock": [0] * 6}
    run.capture = lambda tag: [tag]
    run.log = SimpleNamespace(emit=lambda kind, **kw: events.append((kind, kw)))
    result = run.observed_fight(0.02)
    assert result.blows == 0
    assert "end_turn" not in vars(sess)
    observed = [kw for kind, kw in events if kind == "curse-observation"]
    assert [kw["phase"] for kw in observed] == ["done-before", "done-after"]
    assert observed[-1]["chosen"] == "GUARD"
    assert run.first_effect_loss["phase"] == "done-after"


def test_curse_quit_control_validates_persistence_without_an_attack():
    row = [62, 25, 0, 0, 5]
    quit_evidence = {"actor": "PHILIPPE", "chosen": "QUIT",
                     "before": row, "after": row, "advanced_to": "SHARA"}
    A.validate_curse_quit(quit_evidence, "PHILIPPE")
    with pytest.raises(A.StepFailed, match="no confirmed QUIT"):
        A.validate_curse_quit(None, "PHILIPPE")
    with pytest.raises(A.StepFailed, match="no confirmed QUIT"):
        A.validate_curse_quit({**quit_evidence, "advanced_to": None}, "PHILIPPE")
    with pytest.raises(A.StepFailed, match="absent after"):
        A.validate_curse_quit({**quit_evidence, "after": None}, "PHILIPPE")


def test_curse_quit_control_completes_without_named_attack(tmp_path, monkeypatch):
    import contextlib
    from types import SimpleNamespace

    from tools.curse_of_the_azure_bonds import curserun

    source = _fixture_disk(tmp_path)
    slot = _Slot(tmp_path)
    monkeypatch.setattr(A.SC, "catch_signals", lambda: None)
    monkeypatch.setattr(A.S, "claim_slot", lambda *a, **k: slot)
    monkeypatch.setattr(A, "stage", lambda *a, **k: {"effects": [],
                                                    "magic_items": []})
    monkeypatch.setattr(curserun, "stage", lambda *a, **k: "first")

    class Session:
        save_disk = "disk"

        def __init__(self, *a, **k):
            pass

        def watching_dialogs(self):
            return contextlib.nullcontext()

        def terminate(self):
            pass

    monkeypatch.setattr(curserun, "CurseSession", Session)

    class Run:
        attack_evidence = None
        quit_evidence = {"actor": "PHILIPPE", "chosen": "QUIT",
                         "before": [62, 25, 0, 0, 5],
                         "after": [62, 25, 0, 0, 5], "persisted": True,
                         "advanced_to": "SHARA"}
        first_effect_loss = None

        def __init__(self, *args):
            pass

        def load(self):
            return {}

        def fight(self, *args):
            return {"named_attack": None, "named_quit": self.quit_evidence}

        def reading(self):
            return {"effects": [[62, 25, 0, 0, 5]]}

        def capture(self, tag):
            pass

    monkeypatch.setattr(A, "CurseRun", Run)
    args = SimpleNamespace(title="curse", max_seconds=120, stage_row=[],
                           stage_trait=[], stage_item=[], stage_only=False,
                           checkpoint=[], pool=None, issue="671", run="fake-quit",
                           disks="unused", attack_by="PHILIPPE", walk="I",
                           walk_steps=60, quit_nonattacking=True, probe_step=False)
    out = tmp_path / "evidence"
    assert A.run(args, A.parse_steps(["load", "fight 30"]), out, source) == 0
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["completed"] is True
    assert summary["named_attack"] is None
    assert summary["named_quit"]["persisted"] is True


@pytest.mark.parametrize("before,after,saved,expected", [
    ([], [], [], 1),
    (["INVISIBILITY"], ["INVISIBILITY"], [], 1),
    (["INVISIBILITY"], [], [[62, 25, 0, 0, 5]], 1),
    (["INVISIBILITY"], [], [], 0),
])
def test_curse_attack_needs_both_status_lists_and_the_engine_save(
        tmp_path, monkeypatch, before, after, saved, expected):
    import contextlib
    from types import SimpleNamespace

    from tools.curse_of_the_azure_bonds import curserun

    source = _fixture_disk(tmp_path)
    slot = _Slot(tmp_path)
    monkeypatch.setattr(A.SC, "catch_signals", lambda: None)
    monkeypatch.setattr(A.S, "claim_slot", lambda *a, **k: slot)
    monkeypatch.setattr(A, "stage", lambda *a, **k: {"effects": [],
                                                    "magic_items": []})
    monkeypatch.setattr(curserun, "stage", lambda *a, **k: "first")

    class Session:
        save_disk = "disk"

        def __init__(self, *a, **k):
            pass

        def watching_dialogs(self):
            return contextlib.nullcontext()

        def terminate(self):
            pass

    monkeypatch.setattr(curserun, "CurseSession", Session)

    class Run:
        attack_evidence = {"actor": "PHILIPPE", "index": 0, "owner": 0,
                           "chosen": A.S.ATTACK, "before": [62, 25, 0, 0, 5],
                           "after": None}

        def __init__(self, *a, **k):
            self.lists = iter((before, after))

        def load(self):
            return {}

        def camp_list(self, who):
            return {"lists": {who: next(self.lists)}}

        def fight(self, *a):
            return {"named_attack": self.attack_evidence}

        def save(self, staged):
            return {"effects": saved, "kept": "saved.D64"}

        def reading(self):
            return {"effects": []}

        def capture(self, tag):
            pass

    monkeypatch.setattr(A, "CurseRun", Run)
    args = SimpleNamespace(title="curse", max_seconds=120, stage_row=[],
                           stage_trait=[], stage_item=[], stage_only=False,
                           checkpoint=[], pool=None, issue="671", run="fake",
                           disks="unused", attack_by="PHILIPPE", walk="I",
                           walk_steps=60)
    out = tmp_path / "evidence"
    rc = A.run(args, A.parse_steps(["load", "camp-list PHILIPPE", "fight 600",
                                    "camp-list PHILIPPE", "save"]), out, source)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert rc == expected and summary["completed"] is (expected == 0)
    assert ("lost" in summary) is (expected == 1)


def test_curse_unreadable_brawl_acknowledgement_is_answered_once():
    class Session:
        def __init__(self):
            self.keys = []
            self.looks = 0

        def in_combat(self):
            return bool(self.keys)

        def screen(self):
            self.looks += 1
            return None

        def press_kernal(self, code):
            self.keys.append(code)

        def settle(self, seconds):
            pass

    run = A.CurseRun.__new__(A.CurseRun)
    run.sess = Session()
    run.capture = lambda tag: None
    assert run.await_combat() is True
    assert run.sess.keys == [0x0D]
    assert run.sess.looks == 1


def _pool_run(tmp_path, sess):
    log = A.Log(tmp_path)
    return A.PoolRun(sess, log, tmp_path, POOL_OF_RADIANCE, {}), log


def test_camp_list_reads_every_name_page_by_page_and_goes_back_to_the_world(tmp_path):
    whom = _whom_screen(("MALCYON",))
    screens = {
        "world": _window({}, WORLD_BAR), "camp": _window({}, CAMP),
        "magic": _window({}, MAGIC), "whom": whom,
        "on-m": whom, "on-p": whom, "on-x": whom,
        "m": _window({1: "MALCYON IS AFFECTED BY:", 3: "DETECT MAGIC"}, A.CONTINUE),
        "p1": _window({1: "THE WHOLE PARTY  IS AFFECTED BY:", 3: "DETECT MAGIC",
                       4: "BLESS"}, A.CONTINUE),
        "p2": _window({1: "THE WHOLE PARTY  IS AFFECTED BY:", 3: "PRAYER"},
                      A.CONTINUE),
    }
    moves = {
        ("world", ("bar", "ENCAMP")): "camp", ("camp", ("bar", "MAGIC")): "magic",
        ("magic", ("bar", "DISPLAY")): "whom",
        ("whom", ("party", 0)): "on-m", ("on-m", ("key", "Return")): "m",
        ("m", ("key", 0x0D)): "whom",
        ("whom", ("party", 1)): "on-p", ("on-p", ("key", "Return")): "p1",
        ("p1", ("key", 0x0D)): "p2", ("p2", ("key", 0x0D)): "whom",
        ("whom", ("party", 2)): "on-x", ("on-x", ("key", "Return")): "magic",
        ("magic", ("bar", "EXIT")): "camp",
        ("camp", ("bar", "EXIT")): "world",
    }
    sess = FakeSession(screens, moves, "world")
    run, log = _pool_run(tmp_path, sess)
    got = run.camp_list("")
    log.close()
    assert got == {"offered": ["MALCYON", "THE WHOLE PARTY"],
                   "lists": {"MALCYON": ["DETECT MAGIC"],
                             "THE WHOLE PARTY": ["DETECT MAGIC", "BLESS", "PRAYER"]}}
    assert sess.state == "world"
    assert len(list(tmp_path.glob("*-camp-list-*.txt"))) == 3


@pytest.mark.parametrize("exit_result", ["magic", "whom", "unknown"])
def test_curse_camp_list_exits_whom_and_reaches_world_or_fails(
        tmp_path, exit_result):
    whom = _whom_screen(("PHILIPPE",))
    screens = {
        "world": _window({}, WORLD_BAR), "camp": _window({}, CAMP),
        "magic": _window({}, MAGIC), "whom": whom, "on-p": whom,
        "on-x": whom, "unknown": _window({}, "UNKNOWN EXIT MENU"),
        "p": _window({1: "PHILIPPE IS AFFECTED BY:", 3: "INVISIBILITY"},
                     A.CONTINUE),
    }
    moves = {
        ("world", ("bar", "ENCAMP")): "camp",
        ("camp", ("bar", "MAGIC")): "magic",
        ("magic", ("bar", "DISPLAY")): "whom",
        ("whom", ("party", 0)): "on-p",
        ("on-p", ("key", "Return")): "p",
        ("p", ("key", 0x0D)): "whom",
        ("whom", ("party", 2)): "on-x",
        ("on-x", ("key", "Return")): exit_result,
        ("magic", ("bar", "EXIT")): "camp",
        ("camp", ("bar", "EXIT")): "world",
    }

    class CurseSession(FakeSession):
        def press_bar(self, label, row=24, timeout=0):
            return self._go(("bar", label))

        def to_world_bar(self, timeout=0):
            return self.state == "world"

    sess = CurseSession(screens, moves, "world")
    run = A.CurseRun.__new__(A.CurseRun)
    run.sess = sess
    run.out = tmp_path
    run.log = A.Log(tmp_path)
    run.shots = 0
    try:
        if exit_result == "magic":
            got = run.camp_list("PHILIPPE")
            assert got["lists"] == {"PHILIPPE": ["INVISIBILITY"]}
            assert sess.state == "world"
            assert sess.sent[-4:] == [
                ("party", 2), ("key", "Return"),
                ("bar", "EXIT"), ("bar", "EXIT"),
            ]
            route = sorted(tmp_path.glob("*-exit-*.txt"))
            assert [p.name.split("-", 1)[1] for p in route] == [
                "exit-whom.txt", "exit-magic.txt", "exit-camp.txt"]
            assert [p.read_text(encoding="utf-8").splitlines()[-1].strip()
                    for p in route] == [MAGIC, CAMP, WORLD_BAR]
        else:
            with pytest.raises(A.StepFailed, match="world bar never came back"):
                run.camp_list("PHILIPPE")
            assert sess.state == exit_result
            if exit_result == "unknown":
                assert sess.sent[-2:] == [("party", 2), ("key", "Return")]
                assert any("UNKNOWN EXIT MENU" in p.read_text(encoding="utf-8")
                           for p in tmp_path.glob("*lost-world-route.txt"))
    finally:
        run.log.close()


def test_items_reads_the_list_of_the_member_asked_for_and_leaves_it(tmp_path):
    screens = {
        "world": _window({}, WORLD_BAR),
        "sheet": _window({1: "LADY KATHERINE"}, "VIEW:ITEMS SPELLS TRADE DROP EXIT"),
        "items": _window({**PROBE4, 1: "LADY KATHERINE", 6: " YES 13 *DART"},
                         "READY TRADE DROP EXIT"),
    }
    moves = {
        ("world", ("party", 1)): "world", ("world", ("bar", "VIEW")): "sheet",
        ("sheet", ("bar", "ITEMS")): "items", ("items", ("bar", "EXIT")): "sheet",
        ("sheet", ("leave",)): "world",
    }
    sess = FakeSession(screens, moves, "world")
    run, log = _pool_run(tmp_path, sess)
    got = run.items("2")
    log.close()
    assert got["marked"] == ["YES 13 *DART"]
    assert [e["row"] for e in got["entries"]] == ["YES CLOAK", "YES 13 *DART",
                                                  "NO  DAGGER"]
    assert sess.state == "world"


# --- the run's deadline and clean-up -------------------------------------------

class _Slot:
    n, display = 1, ":99"

    def __init__(self, dir_):
        self.dir = dir_
        self.torn = False

    def teardown(self):
        self.torn = True


class _Sess:
    def __init__(self, *a, **k):
        self.save_disk = "x"

    def watching_dialogs(self):
        import contextlib
        return contextlib.nullcontext()

    fail_terminate = False

    def terminate(self):
        if _Sess.fail_terminate:
            raise RuntimeError("terminate failed")


class _Pool:
    def __init__(self, *a, **k):
        self.ticks = k.get("ticks")

    def load(self):
        return {}

    def peek(self, arg):
        _Pool.clock[0] += 100
        return {}

    def reading(self):
        return {}

    def capture(self, *a):
        pass


def _drive(tmp_path, monkeypatch, steps, max_seconds=150.0, claim=None, slot=None):
    import types
    slot = slot or _Slot(tmp_path)
    _Pool.clock = [0.0]
    monkeypatch.setattr(A.SC, "catch_signals", lambda: None)
    monkeypatch.setattr(A.S, "claim_slot", claim or (lambda *a, **k: slot))
    monkeypatch.setattr(A.S, "stage_disks", lambda *a, **k: "first")
    monkeypatch.setattr(A.S, "stage_writable",
                        lambda src, dest: __import__("shutil").copyfile(src, dest))
    monkeypatch.setattr(A.S, "Session", _Sess)
    monkeypatch.setattr(A, "PoolRun", _Pool)
    args = types.SimpleNamespace(
        title="pool", stage_row=[], stage_trait=[], stage_item=[],
        stage_only=False, checkpoint=[], pool=None, issue="i", run="r",
        disks=None, walk="I", walk_steps=1, max_seconds=max_seconds)
    out = tmp_path / "out"
    rc = A.run(args, A.parse_steps(steps), out, _fixture_disk(tmp_path),
               clock=lambda: _Pool.clock[0])
    return rc, slot, out


def test_a_run_past_its_deadline_is_lost_and_releases_the_slot(tmp_path, monkeypatch):
    rc, slot, out = _drive(tmp_path, monkeypatch,
                           ["load", "peek 1000 1", "peek 1000 1", "peek 1000 1"], 150.0)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert rc == 1 and not summary["completed"]
    assert "seconds were spent" in summary["lost"]
    assert len(summary["results"]) == 3
    assert slot.torn


def test_a_failing_terminate_still_releases_the_slot(tmp_path, monkeypatch):
    slot = _Slot(tmp_path)
    monkeypatch.setattr(_Sess, "fail_terminate", True)
    with pytest.raises(RuntimeError, match="terminate failed"):
        _drive(tmp_path, monkeypatch, ["load"], 1e9, slot=slot)
    assert slot.torn


def test_a_failing_claim_closes_the_log(tmp_path, monkeypatch):
    closed = []
    monkeypatch.setattr(A.Log, "close", lambda self: closed.append(True))

    def boom(*a, **k):
        raise RuntimeError("no slot")
    with pytest.raises(RuntimeError, match="no slot"):
        _drive(tmp_path, monkeypatch, ["load"], claim=boom)
    assert closed


# --- the camp cures (Curse: CURE BLINDNESS and the paladin's CURE) ---------------

@pytest.mark.parametrize("step", [
    "cast SHARA CURE BLINDNESS>PHILIPPE",       # no colon
    "cast SHARA:CURE BLINDNESS PHILIPPE",       # no arrow
    "cast SHARA:FIREBALL>PHILIPPE",             # not a camp cure
    "cast SHARA:CURE BLINDNESS>",               # nobody
    "cure MARK",                                # nobody
    "cure >LEDERA",                             # no paladin
])
def test_cast_and_cure_steps_parse_and_bad_ones_are_refused(step):
    with pytest.raises(ValueError):
        A.parse_steps(["load", step])


def test_cast_and_cure_steps_keep_their_names_and_the_pool_refuses_them(tmp_path):
    steps = A.parse_steps(["load", "camp-list PHILIPPE,LEDERA",
                           "cast SHARA:cure blindness>PHILIPPE", "cure MARK>LEDERA"])
    assert A.parse_cast(steps[2].arg) == ("SHARA", "CURE BLINDNESS", "PHILIPPE")
    assert A.parse_cure(steps[3].arg) == ("MARK", "LEDERA")
    with pytest.raises(SystemExit) as info:
        A.main(["--title", "pool", "--save", str(_fixture_disk(tmp_path)),
                "--stage-only", "--steps", "load", "cure MARK>LEDERA",
                "--out", str(tmp_path / "out")])
    assert info.value.code == 2


def test_camp_list_reads_each_named_member(tmp_path):
    whom = _whom_screen(("PHILIPPE", "LEDERA"))
    screens = {
        "world": _window({}, WORLD_BAR), "camp": _window({}, CAMP),
        "magic": _window({}, MAGIC), "whom": whom,
        "on-p": whom, "on-l": whom, "on-x": whom,
        "p": _window({1: "PHILIPPE IS AFFECTED BY:", 3: "BLIND"}, A.CONTINUE),
        "l": _window({1: "LEDERA IS AFFECTED BY:", 3: "DISEASE"}, A.CONTINUE),
    }
    moves = {
        ("world", ("bar", "ENCAMP")): "camp", ("camp", ("bar", "MAGIC")): "magic",
        ("magic", ("bar", "DISPLAY")): "whom",
        ("whom", ("party", 0)): "on-p", ("on-p", ("key", "Return")): "p",
        ("p", ("key", 0x0D)): "whom",
        ("whom", ("party", 1)): "on-l", ("on-l", ("key", "Return")): "l",
        ("l", ("key", 0x0D)): "whom",
        ("whom", ("party", 3)): "on-x", ("on-x", ("key", "Return")): "magic",
        ("magic", ("bar", "EXIT")): "camp", ("camp", ("bar", "EXIT")): "world",
    }
    sess = FakeSession(screens, moves, "world")
    run, log = _pool_run(tmp_path, sess)
    got = run.camp_list("PHILIPPE,LEDERA")
    log.close()
    assert got["lists"] == {"PHILIPPE": ["BLIND"], "LEDERA": ["DISEASE"]}
    assert sess.state == "world"


CAST_LIST = "CAST MEMORIZE SCRIBE NEXT PREV EXIT"
CAST_SCREENS = {
    "camp": _window({}, CAMP), "magic": _window({}, MAGIC),
    "list": _window({3: "CURE BLINDNESS"}, CAST_LIST),
    "picking": _window({1: "PICK A SPELL", 3: "CURE BLINDNESS"}, CAST_LIST),
    "whom": [*_whom_screen(("PHILIPPE", "SHARA", "LEDERA"))[:24],
             "CAST SPELL ON WHOM?".ljust(40)],
    "on": _whom_screen(("PHILIPPE",)),
    "msg": _window({2: "PHILIPPE CAN SEE AGAIN"}, A.CONTINUE),
    "unknown": _window({}, "SOMETHING ELSE"),
}


def _cast_moves(pick):
    """The moves up to the pick key, then whatever `pick` says the keys do."""
    return {
        ("camp", ("party", 1)): "camp", ("camp", ("bar", "MAGIC")): "magic",
        ("magic", ("bar", "CAST")): "list", ("list", ("bar", "CAST")): "picking",
        ("whom", ("party", 0)): "on", ("on", ("key", "Return")): "msg",
        ("msg", ("key", 0x0D)): "magic", **pick,
    }


def _curse_run(tmp_path, sess, rows=(), joy=False):
    run = A.CurseRun.__new__(A.CurseRun)
    run.sess = sess
    run.out = tmp_path
    run.log = A.Log(tmp_path)
    run.shots = 0
    run.names = ["PHILIPPE", "SHARA", "LEDERA", "TRAVIS", "MARK", "MATHEW"]
    run.joy = joy
    run.pick_wait = run.bar_wait = run.whom_wait = 0.3
    run.panel_index = lambda who: {"SHARA": 1, "MARK": 4}[who]
    readings = iter(rows)
    run.reading = lambda: {"effects": [r.copy() for r in next(readings)]}
    return run


class _CurseFake(FakeSession):
    def press_bar(self, label, row=24, timeout=0):
        return self._go(("bar", label))


def _cast(tmp_path, pick, joy=False, rows=None):
    blind, disease = [62, 33, 0, 0, 5], [61, 34, 2, 0, 0x85]
    rows = rows or [[blind, disease], [disease]]
    sess = _CurseFake(CAST_SCREENS, _cast_moves(pick), "camp")
    run = _curse_run(tmp_path, sess, rows, joy)
    return run, sess


def test_curse_cast_records_the_targets_row_transition(tmp_path):
    run, sess = _cast(tmp_path, {("picking", ("key", "Return")): "whom"})
    try:
        got = run.cast("SHARA:CURE BLINDNESS>PHILIPPE")
    finally:
        run.log.close()
    assert got["row_before"] == [62, 33, 0, 0, 5] and got["row_after"] is None
    assert got["effects_after"] == [[61, 34, 2, 0, 0x85]]
    assert (got["id"], got["owner"], got["key"]) == (33, 0, "xtest-return")
    assert got["messages"] == [["PHILIPPE CAN SEE AGAIN"]]
    assert sess.sent == [("party", 1), ("bar", "MAGIC"), ("bar", "CAST"),
                         ("bar", "CAST"), ("key", "Return"), ("party", 0),
                         ("key", "Return"), ("key", 0x0D)]


def test_curse_cast_tries_the_kernal_key_when_the_first_did_nothing(tmp_path):
    run, sess = _cast(tmp_path, {("picking", ("key", "Return")): "picking",
                                 ("picking", ("key", 0x0D)): "whom"})
    try:
        got = run.cast("SHARA:CURE BLINDNESS>PHILIPPE")
    finally:
        run.log.close()
    assert got["key"] == "kernal-return"
    assert sess.sent[4:6] == [("key", "Return"), ("key", 0x0D)]


def test_curse_cast_sends_fire_only_with_the_joystick(tmp_path):
    both_dead = {("picking", ("key", "Return")): "picking",
                 ("picking", ("key", 0x0D)): "picking"}
    run, sess = _cast(tmp_path, both_dead)
    with pytest.raises(A.StepFailed, match="none of"):
        run.cast("SHARA:CURE BLINDNESS>PHILIPPE")
    run.log.close()
    assert sess.sent[4:] == [("key", "Return"), ("key", 0x0D)]
    assert list(tmp_path.glob("*lost-pick.txt"))

    (tmp_path / "joy").mkdir()
    run, sess = _cast(tmp_path / "joy",
                      {**both_dead, ("picking", ("key", "KP_0")): "whom"}, joy=True)
    try:
        got = run.cast("SHARA:CURE BLINDNESS>PHILIPPE")
    finally:
        run.log.close()
    assert got["key"] == "joystick-fire"
    assert sess.sent[4:7] == [("key", "Return"), ("key", 0x0D), ("key", "KP_0")]


def test_curse_cast_stops_at_once_when_a_key_changes_the_screen_to_something_else(
        tmp_path):
    run, sess = _cast(tmp_path, {("picking", ("key", "Return")): "unknown"}, joy=True)
    with pytest.raises(A.StepFailed, match="not the target question"):
        run.cast("SHARA:CURE BLINDNESS>PHILIPPE")
    run.log.close()
    assert sess.sent[-1] == ("key", "Return") and sess.state == "unknown"
    assert list(tmp_path.glob("*lost-pick-changed.txt"))


def test_curse_cure_names_its_target_and_leaves_the_sheet(tmp_path):
    dis, timer = [61, 34, 2, 0, 0x85], [59, 141, 4, 199, 199]
    screens = {
        "camp": _window({}, CAMP),
        "sheet": _window({1: "MARK"}, "VIEW:ITEMS SPELLS TRADE DROP CURE EXIT"),
        "whom": CAST_SCREENS["whom"], "on": CAST_SCREENS["on"],
        "sheet2": _window({1: "MARK"}, "VIEW:ITEMS SPELLS TRADE DROP EXIT"),
    }
    moves = {
        ("camp", ("party", 4)): "camp", ("camp", ("bar", "VIEW")): "sheet",
        ("sheet", ("bar", "CURE")): "whom", ("whom", ("party", 2)): "on",
        ("on", ("key", "Return")): "sheet2", ("sheet2", ("bar", "EXIT")): "camp",
    }
    sess = _CurseFake(screens, moves, "camp")
    run = _curse_run(tmp_path, sess, [[dis], [timer]])
    try:
        got = run.cure("MARK>LEDERA")
    finally:
        run.log.close()
    assert got["row_before"] == dis and got["row_after"] is None
    assert got["effects_after"] == [timer] and (got["id"], got["owner"]) == (34, 2)
    assert sess.state == "camp"


def test_curse_cure_fails_with_a_capture_when_the_sheet_offers_no_cure(tmp_path):
    screens = {"camp": _window({}, CAMP),
               "sheet": _window({}, "VIEW:ITEMS SPELLS TRADE DROP EXIT")}
    sess = _CurseFake(screens, {("camp", ("party", 4)): "camp",
                                ("camp", ("bar", "VIEW")): "sheet"}, "camp")
    run = _curse_run(tmp_path, sess, [])
    with pytest.raises(A.StepFailed, match="offers no CURE"):
        run.cure("MARK>LEDERA")
    run.log.close()
    assert list(tmp_path.glob("*lost-cure-not-offered.txt"))


def _evidence():
    base = [[60, 45, 4, 0, 255], [63, 141, 5, 199, 199]]
    blind, dis, timer = [62, 33, 0, 0, 5], [61, 34, 2, 0, 0x85], [59, 141, 4, 199, 199]
    return [
        {"verb": "camp-list", "lists": {"PHILIPPE": ["BLIND"], "LEDERA": ["DISEASE"]}},
        {"verb": "cast", "caster": "SHARA", "caster_owner": 1, "spell": "CURE BLINDNESS",
         "target": "PHILIPPE", "owner": 0, "id": 33, "word": "BLIND",
         "row_before": blind, "row_after": None,
         "effects_before": [*base, blind, dis], "effects_after": [*base, dis]},
        {"verb": "cure", "paladin": "MARK", "caster_owner": 4, "target": "LEDERA",
         "owner": 2, "id": 34, "word": "DISEASE",
         "row_before": dis, "row_after": None,
         "effects_before": [*base, dis], "effects_after": [*base, timer]},
        {"verb": "camp-list", "lists": {"PHILIPPE": [], "LEDERA": []}},
        {"verb": "save", "kept": "saved.D64", "effects": [*base, timer]},
    ]


def _party(memorised=(0,)):
    return lambda path: {"SHARA": {"owner": 1, "memorised": list(memorised)}}


def test_curse_cures_pass_on_the_complete_evidence():
    A.validate_curse_cures(_evidence(), "saved.D64", _party())


def _mutate(fn):
    def change(results):
        fn(results)
        return results
    return change


@pytest.mark.parametrize("mutation,match", [
    (lambda r: r[1].update(row_before=None), "already absent"),
    (lambda r: r[1].update(row_after=[62, 33, 0, 0, 5]), "refuted"),
    (lambda r: r[2].update(row_after=[61, 34, 2, 0, 0x85]), "refuted"),
    (lambda r: r[0]["lists"].update(PHILIPPE=[]), "did not show PHILIPPE"),
    (lambda r: r[3]["lists"].update(LEDERA=["DISEASE"]), "still showed LEDERA"),
    (lambda r: r[4]["effects"].append([62, 33, 0, 0, 5]), "still held PHILIPPE"),
    (lambda r: r[1]["effects_after"].pop(0), "also took away"),
    (lambda r: r[2]["effects_after"].pop(), "add one id-141"),
    (lambda r: r[4]["effects"].pop(), "lost MARK's id-141"),
    (lambda r: r[1]["effects_after"].append([58, 141, 1, 9, 9]), "added"),
])
def test_curse_cures_need_every_piece_of_evidence(mutation, match):
    results = _evidence()
    mutation(results)
    with pytest.raises(A.StepFailed, match=match):
        A.validate_curse_cures(results, "saved.D64", _party())


def test_curse_cures_need_the_spell_gone_from_the_saved_memorised_list():
    with pytest.raises(A.StepFailed, match="memorised"):
        A.validate_curse_cures(_evidence(), "saved.D64", _party((37, 0)))


def test_saved_characters_reads_each_name_slot_and_memorised_list(tmp_path):
    from goldbox.savegame import load_save
    disk = _fixture_disk(tmp_path)
    got = A.saved_characters(disk)
    _, sg0, _ = load_save(D64.open(str(disk)))
    assert set(got) == {s.record.name.upper() for s in sg0.characters}
    assert all(set(v) == {"owner", "memorised"} for v in got.values())


def test_a_curse_run_with_cures_gives_the_slot_a_joystick_and_validates_them(
        tmp_path, monkeypatch):
    from types import SimpleNamespace

    from tools.curse_of_the_azure_bonds import curserun

    slot = _Slot(tmp_path)
    slot.vicerc = tmp_path / "vicerc"
    slot.vicerc.write_text("Sound=0\n", encoding="utf-8")
    monkeypatch.setattr(A.SC, "catch_signals", lambda: None)
    monkeypatch.setattr(A.S, "claim_slot", lambda *a, **k: slot)
    monkeypatch.setattr(A, "stage", lambda *a, **k: {"effects": [], "magic_items": []})
    monkeypatch.setattr(curserun, "stage", lambda *a, **k: "first")
    monkeypatch.setattr(curserun, "CurseSession", _Sess)
    evidence = _evidence()
    seen = []
    monkeypatch.setattr(A, "validate_curse_cures",
                        lambda results, path: seen.append((results[-1]["verb"], path)))

    class Run:
        joy = False

        def __init__(self, *a, **k):
            seen.append("built after the vicerc: " + slot.vicerc.read_text(
                encoding="utf-8").replace("\n", "|"))

        def load(self):
            return {}

        def cast(self, arg):
            return {k: v for k, v in evidence[1].items() if k != "verb"}

        def cure(self, arg):
            return {k: v for k, v in evidence[2].items() if k != "verb"}

        def save(self, staged):
            return {"kept": "saved.D64", "effects": []}

        def reading(self):
            return {"effects": []}

        def capture(self, tag):
            pass

    monkeypatch.setattr(A, "CurseRun", Run)
    args = SimpleNamespace(title="curse", max_seconds=120, stage_row=[],
                           stage_trait=[], stage_item=[], stage_only=False,
                           checkpoint=[], pool=None, issue="671", run="joy",
                           disks="unused", joy=True)
    steps = ["load", "cast SHARA:CURE BLINDNESS>PHILIPPE", "cure MARK>LEDERA", "save"]
    assert A.run(args, A.parse_steps(steps), tmp_path / "evidence",
                 _fixture_disk(tmp_path)) == 0
    assert seen == ["built after the vicerc: Sound=0|JoyDevice2=1|",
                    ("save", "saved.D64")]
