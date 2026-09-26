"""The Silver Blades session the C64 drivers use, built when asked for."""
from __future__ import annotations


def silver_session_class():
    """`ssbwarp.SSBSession` with `CurseSession`'s bar helpers.

    The camp, sheet and rest steps wait for and press bars the same way
    in both later titles; `curserun.CurseSession` holds those helpers and
    Silver Blades' session does not, so they are borrowed rather than
    copied.
    """
    from tools.curse_of_the_azure_bonds import curserun
    from tools.secret_of_the_silver_blades import ssbwarp

    class SilverCureSession(ssbwarp.SSBSession):
        BLANK = curserun.CurseSession.BLANK
        press_bar = curserun.CurseSession.press_bar
        wait_bar = curserun.CurseSession.wait_bar
        to_world_bar = curserun.CurseSession.to_world_bar
        live_triple = curserun.CurseSession.live_triple

    return SilverCureSession
