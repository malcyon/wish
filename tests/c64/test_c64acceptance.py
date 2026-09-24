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
    assert captures == ["attack-before-PHILIPPE", "attack-after-PHILIPPE"]


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
