"""The Roster box's Abilities altered on DOS and Amiga Curse and Silver Blades.

Those engines store 1 in the share byte (`treasure_share`) when MODIFY
CHARACTER is left by KEEP, so the box shows it, read-only. Synthetic cases run
everywhere; the specimen cases open saves the game shipped (the Forgotten
Realms Archives' `Default files/Saves` for DOS, the title's own disk for the
Amiga) and skip only where those are absent.
"""
from __future__ import annotations

import pathlib

import pytest
from gamedata import synthetic_save
from PyQt6.QtWidgets import QTabWidget
from support.dossave import _game_dirs
from support.editorwindow import make_root

from editor.window import EditorBinding
from goldbox import c64_port


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


KEEP_TOOLTIP = ("Set when this character left MODIFY CHARACTER by pressing "
                "KEEP, whether or not anything was changed")
UNRECORDED_TOOLTIP = "Not recorded on this title"
POOL_TOOLTIP = ("Set when this character kept an ability or hit-point change "
                "at the trainer")

CURSE = c64_port.CURSE_OF_THE_AZURE_BONDS
SILVER = c64_port.SECRET_OF_THE_SILVER_BLADES
AMIGA_DISKS = pathlib.Path("/mnt/disks/amiga")


def _shown(path):
    root = make_root()
    w = EditorBinding(root, str(path))
    tabs = root.findChild(QTabWidget, "tabs")
    for i in range(tabs.count()):
        if tabs.widget(i).objectName() == "tab_editor":
            tabs.setCurrentIndex(i)
            break
    root.resize(1875, 1030)
    root.show()
    return w


def _synthetic(tmp_path, game, port, share=None, flags=None):
    w = _shown(synthetic_save(tmp_path, game=game))
    w.party.port = port
    member = w.party.member(0)
    if share is not None:
        member.record.set("treasure_share", share)
    if flags is not None:
        member.record.set("flags_0b8", flags)
    w._populate()
    return w, w._child("abilities_altered_combo")


@pytest.mark.parametrize("game", [CURSE, SILVER], ids=["curse", "silver"])
@pytest.mark.parametrize("port", ["dos", "amiga"])
@pytest.mark.parametrize("share,text", [(1, "Yes"), (0, "No")])
def test_the_share_byte_shows_yes_or_no(app, tmp_path, game, port, share, text):
    w, altered = _synthetic(tmp_path, game, port, share=share)
    assert altered.isVisible() and not altered.isEnabled()
    assert altered.currentText() == text
    assert altered.toolTip() == KEEP_TOOLTIP
    assert w._flush(0) == []


@pytest.mark.parametrize("game", [CURSE, SILVER], ids=["curse", "silver"])
def test_a_raw_share_above_one_is_not_yes(app, tmp_path, game):
    _, altered = _synthetic(tmp_path, game, "dos", share=2)
    assert altered.currentText() == "No"


@pytest.mark.parametrize("game", [CURSE, SILVER], ids=["curse", "silver"])
def test_the_c64_port_of_the_same_title_stays_empty(app, tmp_path, game):
    _, altered = _synthetic(tmp_path, game, "c64", share=1)
    assert altered.currentText() == ""
    assert altered.toolTip() == UNRECORDED_TOOLTIP


def test_dos_pool_of_radiance_keeps_its_own_field_and_wording(app, tmp_path):
    _, altered = _synthetic(tmp_path, c64_port.POOL_OF_RADIANCE, "dos",
                            share=0, flags=0x01)
    assert altered.currentText() == "Yes"
    assert altered.toolTip() == POOL_TOOLTIP


@pytest.mark.parametrize("game", [CURSE, SILVER], ids=["curse", "silver"])
def test_a_companion_hides_the_field_and_a_flip_shows_no(app, tmp_path, game):
    """A companion's share byte is a treasure share, not a KEEP record."""
    w, altered = _synthetic(tmp_path, game, "dos", share=1, flags=0x80)
    assert not altered.isVisible()
    w._child("control_combo").setCurrentText("Player-controlled")
    app.processEvents()
    assert altered.isVisible()
    assert altered.currentText() == "No"


# --- saves the game wrote ------------------------------------------------

def _dos(folder, name):
    where = _game_dirs().get(folder)
    if where is None:
        pytest.skip("needs the Forgotten Realms Archives; set FR_ARCHIVES")
    return where / name


def _amiga(folder, name):
    path = AMIGA_DISKS / folder / name
    if not path.is_file():
        pytest.skip(f"needs {path}")
    return path


def _show_each(path):
    w = _shown(path)
    combo = w._child("abilities_altered_combo")
    seen = {}
    for member in w.party.members:
        w._apply_control_state(member, member.is_npc, populate=True)
        seen[member.name] = (combo.currentText(), combo.toolTip(),
                             combo.isEnabled())
    return seen


SPECIMENS = [
    ("dos", "CURSE", "SAVGAMA.DAT", "MATHEW", "Yes"),
    ("dos", "SECRET", "SAVGAMA.DAT", "GUY DE VALOIS", "Yes"),
    ("dos", "SECRET", "SAVGAMA.DAT", "MALACHITE", "No"),
    ("amiga", "Curse_Of_The_Azure_Bonds", "CurseOfTheAzureBonds_A.adf",
     "GALAIN", "Yes"),
    ("amiga", "Secret_Of_The_Silver_Blades", "SecretOfTheSilverBlades_A.adf",
     "GUY DE VALOIS", "Yes"),
    ("amiga", "Secret_Of_The_Silver_Blades", "SecretOfTheSilverBlades_A.adf",
     "MALACHITE", "No"),
]


@pytest.mark.parametrize("port,folder,name,who,text", SPECIMENS)
def test_a_shipped_save_shows_what_its_share_byte_holds(
        app, port, folder, name, who, text):
    """Shipped, not watched: the Archives' DOS saves and the Amiga title
    disks. Each named character's byte is 1 (or 0 for MALACHITE)."""
    path = (_dos if port == "dos" else _amiga)(folder, name)
    seen = _show_each(path)
    shown, tooltip, enabled = seen[who]
    assert (shown, tooltip, enabled) == (text, KEEP_TOOLTIP, False)
