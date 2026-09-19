"""Silver Blades and Curse each draw two different save-disk prompts (#539).

`tools/secret_of_the_silver_blades/ssbwarp.py`'s own `SAVE_PROMPT = "SAVE DISK"` is a substring of the
party-menu loader's prompt, `INSERT BLADES SAVE DISK. PRESS A KEY.`, but not
of camp's, `INSERT YOUR SAVE GAME DISK` -- so `SSBSession.handle_prompt`
recognised the loader prompt fine and only missed the camp one, and
`ENCAMP > SAVE` sat on the camp prompt forever. `tools/curse_of_the_azure_bonds/curserun.py` carried
the same wrong constant for Curse, and `CurseSession.save_game`'s `wait_bar`
calls `handle_prompt` on every poll, so the same narrower gap applied there
too.

Nothing here needs an emulator. `FakeSSBSession` and `FakeCurseSession`
subclass the real drivers -- `tests/test_session_indoors.py`'s pattern of
loading them with `load_tools_module` rather than faking a stand-in class --
so what is under test is the real `handle_prompt`, with a screen, a drive and
a keyboard that are all fixed answers.
"""

from __future__ import annotations

from conftest import load_tools_module

from automap.screen import Screen

SSB = load_tools_module("ssbwarp")
CURSE = load_tools_module("curserun")

#: Row 18 and row 24 of the camp prompt, the same wording all three titles
#: draw from `ENCAMP > SAVE` -- confirmed on Silver Blades'
#: `cited/52/walk-amigatoc64-ssb/ssbcheck/04-resaved.png` and in the
#: disk bytes at `SILVER-1.D64` offset `0x2230F`.
CAMP_PROMPT_TOP = "INSERT YOUR SAVE GAME DISK"
CAMP_PROMPT_BOTTOM = "PRESS ANY KEY TO CONTINUE"

#: The party-menu loader's own save-disk prompt, one wording per title --
#: `SILVER-1.D64` offset `0x23A21` for Silver Blades.
SSB_LOADER_PROMPT = "INSERT BLADES SAVE DISK. PRESS A KEY."
CURSE_LOADER_PROMPT = "INSERT CURSE SAVE DISK, PRESS A KEY"

SSB_SIDE_PROMPT = "INSERT SIDE A, AND PRESS ANY KEY."
CURSE_SIDE_PROMPT = "INSERT SIDE # 3, AND PRESS ANY KEY."

WORLD_BAR = "MOVE VIEW CAST AREA ENCAMP SEARCH LOOK"


def screen_of(rows: dict[int, str]) -> Screen:
    """A `Screen` carrying *rows*, blank everywhere else."""
    codes = bytearray(0x20 for _ in range(1000))
    for row, text in rows.items():
        for i, ch in enumerate(text.upper()):
            codes[row * 40 + i] = ord(ch) - 0x40 if "A" <= ch <= "Z" else ord(ch)
    return Screen(bytes(codes), bytes(1000), 0xCC00)


class FakeKbd:
    def __init__(self):
        self.sent: list[str] = []

    def key(self, name, hold=0.0, gap=0.0):
        self.sent.append(name)


class _FakeDriverMixin:
    """What every `handle_prompt` needs: an attach, a screen, a log."""

    def __init__(self, save_disk: str, here: str, screen=None):
        self.save_disk = save_disk
        self.here = here
        self.attached = ""      # nothing attached yet, so the first prompt
                                 # this test sends is always a change
        self.kbd = FakeKbd()
        self._last_prompt = 0.0
        self._screen = screen
        self.attaches: list[str] = []
        self.kernal: list[int] = []
        self.said: list[str] = []

    def screen(self):
        return self._screen

    def attach(self, path, unit: int = 8, settle=None) -> None:
        self.attaches.append(path)
        self.attached = path

    def press_kernal(self, code: int) -> None:
        self.kernal.append(code)

    def log(self, *a) -> None:
        self.said.append(" ".join(str(x) for x in a))


class FakeSSBSession(_FakeDriverMixin, SSB.SSBSession):
    pass


class FakeCurseSession(_FakeDriverMixin, CURSE.CurseSession):
    pass


# -- the two titles' loader wordings do not match each other's --------------


def test_each_titles_loader_wording_is_its_own():
    """The reverse check: Silver Blades' needle must not answer Curse's
    loader prompt, and Curse's must not answer Silver Blades'."""
    assert SSB.LOADER_SAVE_PROMPT not in CURSE_LOADER_PROMPT
    assert CURSE.LOADER_SAVE_PROMPT not in SSB_LOADER_PROMPT


# -- Silver Blades -------------------------------------------------------


def test_ssb_handle_prompt_recognises_the_camp_save_prompt(tmp_path):
    """The bug: `ENCAMP > SAVE` draws this and `handle_prompt` never
    pressed through it. Red without the fix."""
    save_disk = tmp_path / "SIDE0.D64"
    save_disk.touch()
    sess = FakeSSBSession(str(save_disk), str(tmp_path),
                          screen_of({18: CAMP_PROMPT_TOP,
                                     24: CAMP_PROMPT_BOTTOM}))
    assert sess.handle_prompt() is True
    assert sess.attaches == [str(save_disk)]
    assert sess.kbd.sent == ["space"]


def test_ssb_handle_prompt_still_recognises_the_loader_save_prompt(tmp_path):
    """The guard: the wider needle must not lose the wording that already
    worked -- the party-menu loader's own prompt."""
    save_disk = tmp_path / "SIDE0.D64"
    save_disk.touch()
    sess = FakeSSBSession(str(save_disk), str(tmp_path),
                          screen_of({24: SSB_LOADER_PROMPT}))
    assert sess.handle_prompt() is True
    assert sess.attaches == [str(save_disk)]
    assert sess.kbd.sent == ["space"]


def test_ssb_handle_prompt_still_attaches_a_side_and_not_the_save_disk(
        tmp_path):
    """The save needle must not swallow an ordinary side prompt."""
    save_disk = tmp_path / "SIDE0.D64"
    save_disk.touch()
    (tmp_path / "SIDE1.D64").touch()
    sess = FakeSSBSession(str(save_disk), str(tmp_path),
                          screen_of({24: SSB_SIDE_PROMPT}))
    assert sess.handle_prompt() is True
    assert sess.attaches == [str(tmp_path / "SIDE1.D64")]


def test_ssb_handle_prompt_answers_nothing_at_the_world_bar(tmp_path):
    save_disk = tmp_path / "SIDE0.D64"
    save_disk.touch()
    sess = FakeSSBSession(str(save_disk), str(tmp_path),
                          screen_of({24: WORLD_BAR}))
    assert sess.handle_prompt() is False
    assert sess.attaches == []
    assert sess.kbd.sent == []


def test_ssb_enter_world_idle_gate_still_waits_out_the_camp_prompt():
    """`enter_world`'s `stop_at_idle` gate checked the same needle
    (`#539`) -- prove `save_disk_wanted` alone recognises what it needs to,
    the function the gate itself now calls."""
    assert SSB.save_disk_wanted(CAMP_PROMPT_TOP + "\n" + CAMP_PROMPT_BOTTOM)
    assert SSB.save_disk_wanted(SSB_LOADER_PROMPT)
    assert not SSB.save_disk_wanted(WORLD_BAR)


# -- Curse -----------------------------------------------------------------


def test_curse_handle_prompt_recognises_the_camp_save_prompt(tmp_path):
    """Curse has the same gap (#539); `CurseSession.save_game` is covered
    by its own `wait_bar` today, but `handle_prompt` on its own did not
    recognise this wording either. Red without the fix."""
    save_disk = tmp_path / "SIDE0.D64"
    save_disk.touch()
    sess = FakeCurseSession(str(save_disk), str(tmp_path),
                            screen_of({18: CAMP_PROMPT_TOP,
                                       24: CAMP_PROMPT_BOTTOM}))
    assert sess.handle_prompt() is True
    assert sess.attaches == [str(save_disk)]
    assert sess.kernal == [0x20]


def test_curse_handle_prompt_still_recognises_the_loader_save_prompt(
        tmp_path):
    save_disk = tmp_path / "SIDE0.D64"
    save_disk.touch()
    sess = FakeCurseSession(str(save_disk), str(tmp_path),
                            screen_of({24: CURSE_LOADER_PROMPT}))
    assert sess.handle_prompt() is True
    assert sess.attaches == [str(save_disk)]
    assert sess.kernal == [0x20]


def test_curse_handle_prompt_still_attaches_a_side_and_not_the_save_disk(
        tmp_path):
    save_disk = tmp_path / "SIDE0.D64"
    save_disk.touch()
    sess = FakeCurseSession(str(save_disk), str(tmp_path),
                            screen_of({24: CURSE_SIDE_PROMPT}))
    assert sess.handle_prompt() is True
    assert sess.attaches == [str(tmp_path / "SIDE3.D64")]


def test_curse_handle_prompt_answers_nothing_at_the_world_bar(tmp_path):
    save_disk = tmp_path / "SIDE0.D64"
    save_disk.touch()
    sess = FakeCurseSession(str(save_disk), str(tmp_path),
                            screen_of({24: WORLD_BAR}))
    assert sess.handle_prompt() is False
    assert sess.attaches == []
    assert sess.kernal == []

