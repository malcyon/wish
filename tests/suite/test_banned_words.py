"""The banned words in `.claude/rules/words.md` stay out of the tracked files.

A term is banned in the scope `SCOPES` gives it: every tracked text file,
Markdown only, or `None` for a ban that depends on meaning and is left to review.
Citations (`#N (title)`, `WISH-N (title)`) are blanked first because a
citation quotes an issue's own title. While the sweep of the stem `refus` is
unfinished, `LIMITS_EVERY` and `LIMITS_MARKDOWN` hold the most matches each
file may still carry; a limit only ever goes down, and both dicts are deleted
when the sweep is done.
"""
import collections
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[2]
WORDS = ".claude/rules/words.md"

#: The scope of every bold term in the first cell of a row of the words table;
#: a term missing here fails `test_every_banned_term_has_a_scope`, so a new row
#: cannot be added without deciding where it is checked.
SCOPES = {
    "corpus": "every", "load-bearing": "every", "fair": "every",
    "blast radius": "every", "obviate": "every", "retarget": "every",
    "worth": "every", "census": "every",
    "refuse": "every", "refuses": "every", "refused": "every",
    "refusing": "every", "refusal": "every", "refusals": "every",
    # Code uses these as names: numpy `.shape`, `math.floor`, Qt's ElideRight.
    "shape": "markdown", "plain": "markdown", "floor": "markdown",
    "elide": "markdown",
    # The ban depends on meaning ("carry" is the 6502 flag, "bite" a monster
    # attack), so a reviewer reads for these.
    "carried": None, '"X follows Y"': None, '"bites"': None,
}
#: Self-rating phrases of the words table's sentence row; Markdown only.
PHRASES = ("says so out loud", "the important thing here",
           "narrower than it looks", "worse than it looks", "worse than I said",
           "the interesting kind", "earned its keep", "paid for itself",
           "was the right call")
#: The forms of the stem, whose identifiers are banned too (camelCase included).
STEM = {"refuse", "refuses", "refused", "refusing", "refusal", "refusals"}

#: Third-party text, the table itself and this file, which names the words.
EXCLUDED = (WORDS, "tests/suite/test_banned_words.py", "LICENSE",
            "THIRD_PARTY_LICENSES.md")
#: Python's own name for a socket error.
TOKEN_EXEMPT = ("ConnectionRefusedError",)
#: Lines a ban cannot reach, as (path, text of the line); none now.
ALLOWED_LINES: tuple[tuple[str, str], ...] = ()

# Most matches each file may carry until the sweep removes them (path: count).
LIMITS_EVERY: dict[str, int] = {
    ".claude/agents/emulator-runner.md": 1,
    ".claude/hooks/check-gh-issue-titles.py": 2,
    ".claude/hooks/check-issue-reads.py": 16,
    ".claude/hooks/check-issue-titles.py": 3,
    ".claude/hooks/check-issue-writes.py": 16,
    ".claude/hooks/check-orchestrator-edits.py": 4,
    ".claude/hooks/notify-context-size.py": 1,
    ".claude/hooks/shellcommands.py": 1,
    ".claude/rules/conversions.md": 6,
    ".claude/rules/emulator.md": 1,
    ".claude/rules/issues.md": 1,
    ".claude/skills/orchestrate/SKILL.md": 1,
    "ansible/README.md": 14,
    "ansible/group_vars/all/vault.yml.example": 1,
    "ansible/inventory.yml.example": 2,
    "ansible/roles/agent-vm-guest/tasks/main.yml": 1,
    "ansible/roles/agent-vm-guest/templates/release-update.py.j2": 2,
    "ansible/roles/agent-vm/tasks/main.yml": 3,
    "ansible/roles/agent-winvm-access/defaults/main.yml": 2,
    "ansible/roles/agent-winvm-access/tasks/authorize.yml": 1,
    "ansible/roles/agent-winvm-access/tasks/hostkey.yml": 1,
    "ansible/roles/agent-winvm-access/tasks/verify.yml": 1,
    "ansible/roles/agent-winvm-access/templates/wish-winvm.conf.j2": 1,
    "ansible/roles/sandbox-network/defaults/main.yml": 2,
    "ansible/roles/sandbox-network/tasks/isolation-test-guest.yml": 1,
    "ansible/roles/sandbox-network/templates/sandbox-network.xml.j2": 1,
    "ansible/roles/windows-vm/tasks/teardown.yml": 1,
    "ansible/roles/windows-vm/templates/guest-setup.ps1.j2": 2,
    "ansible/roles/windows-vm/templates/winvm.sh.j2": 4,
    "automap/README.md": 6,
    "automap/actionbar.py": 7,
    "automap/actions.py": 29,
    "automap/amiga.py": 37,
    "automap/amigaactions.py": 2,
    "automap/area.py": 2,
    "automap/c64.py": 5,
    "automap/combat.py": 1,
    "automap/config.py": 5,
    "automap/fasttravel.py": 2,
    "automap/live.py": 2,
    "automap/routes.py": 1,
    "automap/state.py": 12,
    "automap/target.py": 7,
    "automap/vice.py": 1,
    "automap/window.py": 3,
    "automap/winuae.py": 1,
    "docs/10-disk-format.md": 2,
    "docs/101-combat-view.md": 1,
    "docs/102-live-actions.md": 7,
    "docs/103-quest-log-panel.md": 3,
    "docs/107-roster-and-notes.md": 2,
    "docs/110-combat-log.md": 1,
    "docs/116-second-game.md": 3,
    "docs/117-save-conversion.md": 31,
    "docs/118-debug-mode.md": 12,
    "docs/119-test-party.md": 9,
    "docs/120-curse-testing.md": 6,
    "docs/121-silver-blades.md": 8,
    "docs/122-release-testing.md": 6,
    "docs/123-parallel-sessions.md": 3,
    "docs/124-amiga-port.md": 10,
    "docs/125-bug-notes.md": 3,
    "docs/126-forum-findings.md": 1,
    "docs/130-preferences.md": 3,
    "docs/132-logo.md": 2,
    "docs/133-active-effects.md": 3,
    "docs/134-commissions.md": 2,
    "docs/135-levelling.md": 9,
    "docs/136-condition-badges.md": 1,
    "docs/138-multiple-games.md": 3,
    "docs/139-per-title-validation.md": 13,
    "docs/142-dosbox-x-debugger.md": 2,
    "docs/143-winuae-debugger.md": 24,
    "docs/144-decoding-a-new-title.md": 4,
    "docs/148-d6502.md": 6,
    "docs/150-departing-prologues.md": 1,
    "docs/152-commodore-manuals.md": 1,
    "docs/160-why-these-rules.md": 42,
    "docs/161-c64-ultimate.md": 4,
    "docs/163-dos-vm-address-map.md": 1,
    "docs/165-amiga-savegame.md": 1,
    "docs/166-amiga-records-from-the-code.md": 1,
    "docs/170-c64-identity-pair.md": 4,
    "docs/171-c64-trait-slots.md": 4,
    "docs/172-curse-trainer.md": 6,
    "docs/173-carrying-limits.md": 8,
    "docs/175-silver-blades-save-conversion.md": 2,
    "docs/176-changing-class-twice.md": 7,
    "docs/178-turning-undead.md": 2,
    "docs/179-loading-a-curse-save.md": 4,
    "docs/180-writing-a-later-dos-record.md": 2,
    "docs/185-a-party-that-has-not-set-out.md": 5,
    "docs/191-the-amiga-save-disk.md": 1,
    "docs/192-curse-dual-class.md": 6,
    "docs/194-the-dos-training-ladder.md": 4,
    "docs/195-three-dos-record-bytes-named-from-the-overlays.md": 5,
    "docs/196-the-amiga-saved-game-built.md": 3,
    "docs/20-character-record.md": 2,
    "docs/206-three-amiga-questions.md": 1,
    "docs/209-the-regained-dual-class-on-dos.md": 3,
    "docs/212-the-live-tab-per-title.md": 7,
    "docs/215-the-dos-experience-award-and-the-scroll-bundle.md": 4,
    "docs/217-drawing-the-wilderness.md": 3,
    "docs/218-the-wish-agent-bot.md": 6,
    "docs/219-the-agent-sandbox.md": 22,
    "docs/222-naming-curses-effect-codes-from-their-handlers.md": 4,
    "docs/223-the-differential-rewrite.md": 4,
    "docs/225-the-dos-backstab-multiplier.md": 4,
    "docs/226-the-c64-running-effect-crosswalk.md": 8,
    "docs/227-editor-open-save-as.md": 3,
    "docs/228-pools-of-darkness-spells-and-creation.md": 1,
    "docs/230-who-reads-a-dos-effect-node.md": 1,
    "docs/232-the-c64-control-byte-per-title.md": 3,
    "docs/234-a-paladins-cure-disease-across-dos-and-the-c64.md": 3,
    "docs/235-destination-game-acceptance-runs.md": 8,
    "docs/236-requirements-for-adding-a-new-platform.md": 3,
    "docs/50-experiments.md": 33,
    "docs/70-driving-the-game.md": 6,
    "docs/80-fields-wanted.md": 1,
    "docs/86-spell-table.md": 1,
    "docs/90-specimens.md": 2,
    "docs/95-wish-cli.md": 7,
    "docs/96-live-memory-automapper.md": 15,
    "docs/97-editor.md": 7,
    "docs/99-one-window.md": 1,
    "docs/README.md": 7,
    "editor/README.md": 5,
    "editor/convert.py": 9,
    "editor/dosimport.py": 3,
    "editor/effects.py": 2,
    "editor/files.py": 3,
    "editor/inventory.py": 1,
    "editor/namefit.py": 1,
    "editor/roster.py": 3,
    "editor/saveplan.py": 23,
    "editor/spellwidget.py": 1,
    "editor/window.py": 20,
    "goldbox-bugs.md": 3,
    "goldbox/README.md": 4,
    "goldbox/amiga_adf.py": 8,
    "goldbox/amiga_later.py": 4,
    "goldbox/amiga_pod.py": 8,
    "goldbox/amiga_por.py": 2,
    "goldbox/amiga_savegame.py": 8,
    "goldbox/areas.py": 3,
    "goldbox/c64_codec.py": 16,
    "goldbox/c64_save.py": 3,
    "goldbox/classcode.py": 1,
    "goldbox/commissions.py": 1,
    "goldbox/d64.py": 11,
    "goldbox/dos_codec.py": 50,
    "goldbox/dos_port.py": 4,
    "goldbox/dos_savegame.py": 2,
    "goldbox/effects.py": 7,
    "goldbox/iconparts.py": 1,
    "goldbox/items.py": 3,
    "goldbox/layout.py": 2,
    "goldbox/levels.py": 6,
    "goldbox/levelup.py": 9,
    "goldbox/neutral.py": 7,
    "goldbox/portraits.py": 1,
    "goldbox/rewrite.py": 1,
    "goldbox/savegame.py": 1,
    "goldbox/spells.py": 3,
    "goldbox/titles.py": 1,
    "goldbox/traits.py": 4,
    "goldbox/world_state.py": 8,
    "goldbox/yaml_io.py": 8,
    "platform-differences.md": 2,
    "tests/README.md": 1,
    "tests/amiga/README.md": 10,
    "tests/amiga/fakes.py": 7,
    "tests/amiga/test_amiga.py": 24,
    "tests/amiga/test_amiga68k.py": 1,
    "tests/amiga/test_amiga_adf.py": 21,
    "tests/amiga/test_amiga_savegame.py": 1,
    "tests/amiga/test_amigaacceptance.py": 16,
    "tests/amiga/test_amigaacceptance_accept.py": 33,
    "tests/amiga/test_amigaacceptance_camp.py": 14,
    "tests/amiga/test_amigaacceptance_campitems.py": 4,
    "tests/amiga/test_amigaacceptance_measure.py": 7,
    "tests/amiga/test_amigaacceptance_poolrest.py": 1,
    "tests/amiga/test_amigaacceptance_snapshot.py": 1,
    "tests/amiga/test_amigaacceptance_ssbjoin.py": 5,
    "tests/amiga/test_amigaacceptance_ssbsubstitute.py": 5,
    "tests/amiga/test_amigaacceptance_staged.py": 6,
    "tests/amiga/test_amigaacceptance_stageplace.py": 9,
    "tests/amiga/test_amigaacceptance_title.py": 44,
    "tests/amiga/test_amigaacceptance_titles.py": 40,
    "tests/amiga/test_amigabackstab.py": 1,
    "tests/amiga/test_amigabladesjournal.py": 1,
    "tests/amiga/test_amigacontainercheck.py": 5,
    "tests/amiga/test_amigadarknesssubstitute.py": 2,
    "tests/amiga/test_amigadrivecheck.py": 33,
    "tests/amiga/test_amigaeffectreader.py": 3,
    "tests/amiga/test_amigaglobal.py": 1,
    "tests/amiga/test_amigajournalgates.py": 4,
    "tests/amiga/test_amigalaterproof.py": 2,
    "tests/amiga/test_amigalaterslot.py": 3,
    "tests/amiga/test_amigalaterwrite.py": 2,
    "tests/amiga/test_amigaparty.py": 7,
    "tests/amiga/test_amigapipe.py": 47,
    "tests/amiga/test_amigapool.py": 2,
    "tests/amiga/test_amigaporsavegame.py": 6,
    "tests/amiga/test_amigaporsavegameboundaries.py": 1,
    "tests/amiga/test_amigaroutepool.py": 3,
    "tests/amiga/test_amigasavedisk.py": 1,
    "tests/amiga/test_amigasavegame.py": 7,
    "tests/amiga/test_amigashots.py": 1,
    "tests/amiga/test_amigastaging.py": 12,
    "tests/amiga/test_amigastagingsubstitute.py": 5,
    "tests/amiga/test_amigatarget.py": 13,
    "tests/amiga/test_fsuaegdb.py": 52,
    "tests/amiga/test_fsuaepor.py": 1,
    "tests/amiga/test_guardmaps.py": 1,
    "tests/amiga/test_installfsuae.py": 15,
    "tests/amiga/test_m68dis.py": 1,
    "tests/amiga/test_noencounters_winuae.py": 6,
    "tests/amiga/test_podamiga.py": 6,
    "tests/amiga/test_podderived.py": 3,
    "tests/amiga/test_podsavegame.py": 6,
    "tests/amiga/test_savegamelosses.py": 1,
    "tests/amiga/test_winuaeps1.py": 2,
    "tests/amiga/test_winvmguest.py": 10,
    "tests/amiga/test_winwish.py": 9,
    "tests/areas/README.md": 1,
    "tests/areas/test_areas.py": 3,
    "tests/areas/test_exitcombat.py": 1,
    "tests/areas/test_exitreentry.py": 1,
    "tests/areas/test_exitroute.py": 2,
    "tests/areas/test_fasttravel.py": 3,
    "tests/areas/test_fasttravelrun.py": 12,
    "tests/areas/test_p20.py": 2,
    "tests/areas/test_pertitlefasttravel.py": 5,
    "tests/areas/test_questflags.py": 1,
    "tests/areas/test_reentrypoints.py": 3,
    "tests/areas/test_world.py": 3,
    "tests/automap/README.md": 2,
    "tests/automap/test_actions.py": 39,
    "tests/automap/test_amigaactions.py": 2,
    "tests/automap/test_amigalocate.py": 1,
    "tests/automap/test_amigawindow.py": 1,
    "tests/automap/test_automap.py": 29,
    "tests/automap/test_automapbanks.py": 2,
    "tests/automap/test_c64machine.py": 6,
    "tests/automap/test_columns.py": 1,
    "tests/automap/test_combat.py": 1,
    "tests/automap/test_combatlog.py": 1,
    "tests/automap/test_commissions.py": 1,
    "tests/automap/test_fsuaehelper.py": 4,
    "tests/automap/test_latercombat.py": 2,
    "tests/automap/test_printedframe.py": 1,
    "tests/automap/test_stale_status.py": 2,
    "tests/automap/test_wilderness_recording.py": 1,
    "tests/automap/test_winuae.py": 5,
    "tests/c64/README.md": 6,
    "tests/c64/test_c64acceptance.py": 16,
    "tests/c64/test_c64addprobe.py": 2,
    "tests/c64/test_c64creation.py": 10,
    "tests/c64/test_c64status.py": 2,
    "tests/c64/test_c64u.py": 5,
    "tests/c64/test_c64uload.py": 2,
    "tests/c64/test_coldread.py": 3,
    "tests/c64/test_curedrive.py": 1,
    "tests/c64/test_d6502.py": 1,
    "tests/c64/test_effectdrive.py": 3,
    "tests/c64/test_launch.py": 1,
    "tests/c64/test_no_encounters.py": 4,
    "tests/c64/test_openingscene.py": 2,
    "tests/c64/test_outdoordrive.py": 2,
    "tests/c64/test_overlay.py": 2,
    "tests/c64/test_panelindex.py": 1,
    "tests/c64/test_partysheets.py": 3,
    "tests/c64/test_savecheck_glyphs.py": 3,
    "tests/c64/test_savecheck_icon_bank.py": 5,
    "tests/c64/test_savecheck_walk_routing.py": 1,
    "tests/c64/test_screenbank.py": 1,
    "tests/c64/test_session.py": 1,
    "tests/c64/test_session_indoors.py": 1,
    "tests/c64/test_session_snapshot.py": 3,
    "tests/c64/test_session_vice_exit.py": 2,
    "tests/c64/test_session_walk_stop.py": 9,
    "tests/c64/test_traitsave.py": 2,
    "tests/c64/test_turndrive.py": 2,
    "tests/c64/test_walkrun.py": 8,
    "tests/convert/README.md": 4,
    "tests/convert/test_amigaporcharacters.py": 1,
    "tests/convert/test_amigatoc64.py": 7,
    "tests/convert/test_amigatodos.py": 2,
    "tests/convert/test_animatedparty.py": 4,
    "tests/convert/test_c64movement.py": 3,
    "tests/convert/test_c64traitslots.py": 1,
    "tests/convert/test_convert.py": 52,
    "tests/convert/test_convertamigatoc64.py": 1,
    "tests/convert/test_convertmatrix.py": 3,
    "tests/convert/test_convertrun.py": 19,
    "tests/convert/test_curseconvert.py": 4,
    "tests/convert/test_curseworldmap.py": 1,
    "tests/convert/test_dosclasscode.py": 1,
    "tests/convert/test_dosconversionarea.py": 5,
    "tests/convert/test_dosconvert.py": 17,
    "tests/convert/test_dosimport.py": 4,
    "tests/convert/test_doswriter.py": 17,
    "tests/convert/test_hirelingshare.py": 5,
    "tests/convert/test_joinedscroll.py": 13,
    "tests/convert/test_joinedscroll_c64_packs.py": 1,
    "tests/convert/test_leavechoice.py": 2,
    "tests/convert/test_leaveeffects.py": 2,
    "tests/convert/test_namefit.py": 1,
    "tests/convert/test_neutral.py": 10,
    "tests/convert/test_podconvert.py": 7,
    "tests/convert/test_podsave.py": 19,
    "tests/convert/test_rewrite.py": 5,
    "tests/convert/test_runningeffects.py": 39,
    "tests/convert/test_saveasdrive.py": 3,
    "tests/convert/test_ssbconvert.py": 4,
    "tests/convert/test_toamigapor.py": 6,
    "tests/convert/test_toamigapor_marching_order.py": 1,
    "tests/curse_of_the_azure_bonds/test_curse.py": 1,
    "tests/curse_of_the_azure_bonds/test_curse_worldmap.py": 9,
    "tests/curse_of_the_azure_bonds/test_cursedualtrain.py": 4,
    "tests/curse_of_the_azure_bonds/test_curseflee.py": 1,
    "tests/curse_of_the_azure_bonds/test_curselevels.py": 3,
    "tests/curse_of_the_azure_bonds/test_curselive.py": 7,
    "tests/curse_of_the_azure_bonds/test_curseload.py": 20,
    "tests/curse_of_the_azure_bonds/test_cursememorize.py": 1,
    "tests/curse_of_the_azure_bonds/test_cursepaladin.py": 2,
    "tests/curse_of_the_azure_bonds/test_curseregain.py": 1,
    "tests/curse_of_the_azure_bonds/test_cursethac0.py": 1,
    "tests/curse_of_the_azure_bonds/test_cursetrainer.py": 6,
    "tests/curse_of_the_azure_bonds/test_cursewarp.py": 1,
    "tests/curse_of_the_azure_bonds/test_curtraitnames.py": 6,
    "tests/dos/test_dos_savegame.py": 13,
    "tests/dos/test_dosacceptance.py": 116,
    "tests/dos/test_dosbox.py": 12,
    "tests/dos/test_dosbox_walked.py": 2,
    "tests/dos/test_dosboxx.py": 6,
    "tests/dos/test_dosfightwatch.py": 10,
    "tests/dos/test_dosgnome.py": 2,
    "tests/dos/test_doslatercontainer.py": 3,
    "tests/dos/test_dosoutdoor.py": 2,
    "tests/dos/test_dosoutdoorprobe.py": 3,
    "tests/dos/test_dosoutdoorwrite.py": 3,
    "tests/dos/test_dosparty.py": 1,
    "tests/dos/test_dospod.py": 12,
    "tests/dos/test_dosraces.py": 3,
    "tests/dos/test_dossave.py": 8,
    "tests/dos/test_dossavewritemap.py": 1,
    "tests/dos/test_dossavsweep.py": 1,
    "tests/dos/test_dosscrollbundle.py": 2,
    "tests/dos/test_dossnapshot.py": 2,
    "tests/dos/test_dosspcexpiry.py": 2,
    "tests/dos/test_dosvmwatch.py": 1,
    "tests/dos/test_dualclassdos.py": 3,
    "tests/dos/test_ssbimport.py": 2,
    "tests/editor/README.md": 2,
    "tests/editor/test_convertrejection.py": 4,
    "tests/editor/test_editor.py": 27,
    "tests/editor/test_hirelingopen.py": 1,
    "tests/editor/test_namefitdialog.py": 4,
    "tests/editor/test_pertitle_ui.py": 1,
    "tests/editor/test_saveasui.py": 16,
    "tests/editor/test_saveplan.py": 5,
    "tests/editor/test_saveplan_dosfolder.py": 1,
    "tests/editor/test_savepublish.py": 70,
    "tests/gamedata.py": 2,
    "tests/generate/test_classdiagram.py": 2,
    "tests/generate/test_classedges.py": 1,
    "tests/github/test_wishagent.py": 2,
    "tests/gui/README.md": 1,
    "tests/gui/test_mapmarker.py": 5,
    "tests/hooks/README.md": 4,
    "tests/hooks/test_check_issue_reads.py": 25,
    "tests/hooks/test_check_issue_writes.py": 20,
    "tests/hooks/test_check_orchestrator_edits.py": 4,
    "tests/hooks/test_notify_context_size.py": 1,
    "tests/icons/test_dosicon.py": 3,
    "tests/icons/test_iconparts.py": 1,
    "tests/icons/test_iconreverse.py": 3,
    "tests/icons/test_portraits.py": 3,
    "tests/plane/test_policy.py": 9,
    "tests/pool_of_radiance/README.md": 1,
    "tests/pool_of_radiance/test_combatdrive.py": 1,
    "tests/pool_of_radiance/test_dirtenicon.py": 5,
    "tests/pool_of_radiance/test_tavernbrawl.py": 12,
    "tests/records/README.md": 3,
    "tests/records/test_abilitypair.py": 1,
    "tests/records/test_backstab_multiplier.py": 1,
    "tests/records/test_boundary.py": 20,
    "tests/records/test_boundary_amiga.py": 1,
    "tests/records/test_boundary_c64.py": 11,
    "tests/records/test_corrections.py": 1,
    "tests/records/test_curedisease.py": 1,
    "tests/records/test_derive.py": 1,
    "tests/records/test_effectcrosswalk.py": 1,
    "tests/records/test_effects.py": 29,
    "tests/records/test_encsweep.py": 3,
    "tests/records/test_fieldsweep.py": 1,
    "tests/records/test_flags0b8.py": 1,
    "tests/records/test_gametables.py": 2,
    "tests/records/test_geoports.py": 3,
    "tests/records/test_innateeffects.py": 14,
    "tests/records/test_levels.py": 1,
    "tests/records/test_liveparty.py": 1,
    "tests/records/test_pairs.py": 1,
    "tests/records/test_pod_spells.py": 1,
    "tests/records/test_record.py": 2,
    "tests/records/test_spellbooksweep.py": 1,
    "tests/records/test_strength.py": 2,
    "tests/records/test_xpceiling.py": 3,
    "tests/registry/README.md": 1,
    "tests/registry/test_instance.py": 6,
    "tests/registry/test_scratch.py": 1,
    "tests/registry/test_specimenbackup.py": 4,
    "tests/registry/test_specimens.py": 10,
    "tests/registry/test_tooldisks.py": 3,
    "tests/saves/README.md": 5,
    "tests/saves/test_binary_roundtrip.py": 3,
    "tests/saves/test_c64container.py": 3,
    "tests/saves/test_d64_blank.py": 4,
    "tests/saves/test_d64_variants.py": 6,
    "tests/saves/test_savegame.py": 3,
    "tests/saves/test_world_state.py": 5,
    "tests/saves/test_yaml_dualclass.py": 9,
    "tests/saves/test_yaml_io.py": 9,
    "tests/secret_of_the_silver_blades/test_silverblades.py": 1,
    "tests/secret_of_the_silver_blades/test_ssblevels.py": 4,
    "tests/secret_of_the_silver_blades/test_ssblive.py": 6,
    "tests/secret_of_the_silver_blades/test_ssbprologue.py": 1,
    "tests/secret_of_the_silver_blades/test_ssbtrainer.py": 2,
    "tests/secret_of_the_silver_blades/test_ssbtrainpress.py": 2,
    "tests/secret_of_the_silver_blades/test_ssbwarp.py": 1,
    "tests/suite/test_repository_contents.py": 1,
    "tests/suite/test_staging_sweep.py": 2,
    "tests/suite/test_testparty.py": 6,
    "tests/suite/test_testpartyrun.py": 40,
    "tests/suite/test_toolhelp.py": 2,
    "tests/support/automapbanks.py": 1,
    "tests/support/latercombat.py": 1,
    "tests/wish/README.md": 1,
    "tests/wish/test_amigabackend.py": 9,
    "tests/wish/test_debugmode.py": 18,
    "tests/wish/test_gamefolders.py": 1,
    "tests/wish/test_mapscale.py": 1,
    "tests/wish/test_preferences.py": 1,
    "tests/wish/test_winuaebackend.py": 5,
    "tests/wish/test_wish.py": 5,
    "tests/wish/test_wronggame.py": 1,
    "tools/README.md": 1,
    "tools/amiga/README.md": 12,
    "tools/amiga/acceptance.py": 16,
    "tools/amiga/amigabladesjournal.py": 4,
    "tools/amiga/amigacontainercheck.py": 1,
    "tools/amiga/amigadrive.py": 1,
    "tools/amiga/amigadrivecheck.py": 17,
    "tools/amiga/amigalaterproof.py": 1,
    "tools/amiga/amigalaterslot.py": 1,
    "tools/amiga/amigalaterwrite.py": 1,
    "tools/amiga/fromamigapor.py": 1,
    "tools/amiga/fsuaegdb.py": 25,
    "tools/amiga/fsuaepor.py": 1,
    "tools/amiga/installfsuae.py": 8,
    "tools/amiga/m68dis.py": 5,
    "tools/amiga/m68discheck.py": 15,
    "tools/amiga/noencounters.py": 11,
    "tools/amiga/route.py": 43,
    "tools/amiga/route_camp.py": 2,
    "tools/amiga/route_pool.py": 1,
    "tools/amiga/route_silver_blades.py": 6,
    "tools/amiga/screens.py": 1,
    "tools/amiga/staging.py": 4,
    "tools/amiga/toamigapor.py": 1,
    "tools/amiga/winuae-lanecheck.ps1": 17,
    "tools/amiga/winuae-send.ps1": 1,
    "tools/amiga/winuae.ps1": 20,
    "tools/amiga/winuaepipe.py": 1,
    "tools/amiga/winuaesession.py": 1,
    "tools/amiga/winvmguest.py": 12,
    "tools/amiga/winwish.py": 3,
    "tools/areas/eclflags.py": 2,
    "tools/areas/eclwalk.py": 1,
    "tools/areas/fasttravelrun.py": 16,
    "tools/areas/newecl.py": 2,
    "tools/areas/wallpins.py": 4,
    "tools/areas/windowsquare.py": 3,
    "tools/c64/README.md": 1,
    "tools/c64/abilitypair.py": 1,
    "tools/c64/acceptance.py": 54,
    "tools/c64/backstab.py": 1,
    "tools/c64/c64addchar.py": 2,
    "tools/c64/c64outdoor.py": 1,
    "tools/c64/c64recordoperandsweep.py": 1,
    "tools/c64/c64u.py": 8,
    "tools/c64/c64ucompare.py": 2,
    "tools/c64/c64uhang.py": 1,
    "tools/c64/c64uload.py": 1,
    "tools/c64/c64urest.py": 1,
    "tools/c64/coldread.py": 1,
    "tools/c64/creation.py": 12,
    "tools/c64/dualclassagain.py": 1,
    "tools/c64/effectcrosswalk.py": 1,
    "tools/c64/livelevel.py": 3,
    "tools/c64/loadrace.py": 1,
    "tools/c64/route_pool.py": 3,
    "tools/c64/savecheck.py": 3,
    "tools/c64/session.py": 17,
    "tools/c64/splatload.py": 6,
    "tools/c64/statusdrive.py": 1,
    "tools/c64/turndrive.py": 1,
    "tools/c64/walkrun.py": 1,
    "tools/convert/convertamigadisks.py": 4,
    "tools/convert/convertdialogdrive.py": 5,
    "tools/convert/convertrun.py": 3,
    "tools/convert/convertshots.py": 2,
    "tools/convert/hallconvert.py": 2,
    "tools/convert/rewritesweep.py": 6,
    "tools/convert/saveasdrive.py": 8,
    "tools/curse_of_the_azure_bonds/README.md": 5,
    "tools/curse_of_the_azure_bonds/curseareazero.py": 1,
    "tools/curse_of_the_azure_bonds/cursedisk.py": 2,
    "tools/curse_of_the_azure_bonds/curseload.py": 4,
    "tools/curse_of_the_azure_bonds/cursememorize.py": 1,
    "tools/curse_of_the_azure_bonds/cursepaladin.py": 2,
    "tools/curse_of_the_azure_bonds/curseregain.py": 3,
    "tools/curse_of_the_azure_bonds/curserun.py": 3,
    "tools/curse_of_the_azure_bonds/cursethac0.py": 4,
    "tools/curse_of_the_azure_bonds/cursetrain.py": 2,
    "tools/curse_of_the_azure_bonds/cursewarp.py": 4,
    "tools/curse_of_the_azure_bonds/doscurse.py": 1,
    "tools/dos/README.md": 2,
    "tools/dos/acceptance.py": 40,
    "tools/dos/dosaddchar.py": 6,
    "tools/dos/dosaffectreads.py": 1,
    "tools/dos/dosbox.py": 11,
    "tools/dos/dosboxx.py": 4,
    "tools/dos/dosdisk.py": 2,
    "tools/dos/dosfightwatch.py": 4,
    "tools/dos/dosgnome.py": 1,
    "tools/dos/dositemcap.py": 2,
    "tools/dos/dosladder.py": 4,
    "tools/dos/dosmodifyprobe.py": 1,
    "tools/dos/dosnewsave.py": 1,
    "tools/dos/dosoutdoorprobe.py": 1,
    "tools/dos/dosparty.py": 1,
    "tools/dos/dospod.py": 1,
    "tools/dos/dosrecordwrite.py": 1,
    "tools/dos/dosscrollbundle.py": 1,
    "tools/dos/dossheetread.py": 3,
    "tools/dos/dosslotwatch.py": 1,
    "tools/dos/dosspcexpiry.py": 4,
    "tools/dos/dosvmwatch.py": 2,
    "tools/dos/screens.py": 1,
    "tools/dos/staging.py": 2,
    "tools/generate/genexits.py": 1,
    "tools/generate/genspells.py": 1,
    "tools/github/issueread.py": 2,
    "tools/gui/livecheck.py": 13,
    "tools/gui/mapmarker.py": 4,
    "tools/gui/shotwindow.py": 2,
    "tools/gui/winwish.py": 1,
    "tools/icons/iconpoke.py": 2,
    "tools/plane/client.py": 1,
    "tools/plane/policy.py": 1,
    "tools/pool_of_radiance/README.md": 1,
    "tools/pool_of_radiance/defeatdrive.py": 1,
    "tools/pool_of_radiance/dirtenicon.py": 2,
    "tools/pool_of_radiance/fightrun.py": 1,
    "tools/pool_of_radiance/fleedrive.py": 2,
    "tools/pool_of_radiance/koboldnpc.py": 2,
    "tools/pool_of_radiance/loadfailurereplay.py": 1,
    "tools/pool_of_radiance/movekeysweep.py": 1,
    "tools/pool_of_radiance/ohlowatch.py": 2,
    "tools/pool_of_radiance/outdoorstep.py": 2,
    "tools/pool_of_radiance/outdoorwalk.py": 1,
    "tools/pool_of_radiance/tavernbrawl.py": 11,
    "tools/pool_of_radiance/worldtiles.py": 1,
    "tools/records/boundarywidths.py": 6,
    "tools/records/carryceiling.py": 2,
    "tools/records/encsweep.py": 1,
    "tools/records/fieldsweep.py": 1,
    "tools/records/geoports.py": 1,
    "tools/records/infravision.py": 1,
    "tools/records/xpceiling.py": 1,
    "tools/registry/instance.py": 4,
    "tools/registry/scratch.py": 1,
    "tools/registry/specimenbackup.py": 4,
    "tools/registry/specimens.py": 18,
    "tools/secret_of_the_silver_blades/ssbdisk.py": 2,
    "tools/secret_of_the_silver_blades/ssbsession.py": 2,
    "tools/secret_of_the_silver_blades/ssbtrain.py": 1,
    "tools/secret_of_the_silver_blades/ssbwarp.py": 3,
    "tools/suite/suiterun.py": 1,
    "tools/suite/testparty.py": 5,
    "tools/suite/testpartyrun.py": 14,
    "tools/wish.py": 1,
    "tools/wishagent.py": 2,
    "wish/__main__.py": 1,
    "wish/preferences.py": 2,
    "wish/ultimate.py": 2,
    "wish/window.py": 4,
}
LIMITS_MARKDOWN: dict[str, int] = {
    ".agents/skills/caveman/SKILL.md": 2,
    "CHANGELOG.md": 2,
    "docs/109-icon-choices.md": 2,
    "docs/114-party-strength.md": 2,
    "docs/118-debug-mode.md": 2,
    "docs/126-forum-findings.md": 6,
    "docs/128-guide-and-scripting.md": 4,
    "docs/144-decoding-a-new-title.md": 2,
    "docs/160-why-these-rules.md": 8,
    "docs/166-amiga-records-from-the-code.md": 2,
    "docs/192-curse-dual-class.md": 1,
    "docs/224-the-dos-thac0-lower-limit.md": 1,
    "docs/50-experiments.md": 8,
    "docs/88-map-files.md": 1,
    "docs/95-wish-cli.md": 1,
    "docs/97-editor.md": 1,
    "docs/98-automap-notes.md": 1,
}


def terms_in_table(text):
    found = []
    for line in text.splitlines():
        if line.startswith("| **"):
            found += re.findall(r"\*\*(.+?)\*\*", line.split("|")[1])
    return found


def _word(term):
    return re.escape(term).replace(r"\ ", "[ -]").replace(r"\-", "[ -]")


def pattern(terms):
    """The regex for `terms`: whole words, and words after an underscore (a
    word character, so `\\b` would pass a name joined by one); the stem's forms
    also after a lowercase letter (camelCase)."""
    plain = "|".join(_word(t) for t in terms)
    text = rf"(?i:(?:(?<![A-Za-z0-9])|_)(?:{plain})(?![a-z]))"
    if any(t in STEM for t in terms):
        forms = "|".join(sorted(t[len("refus"):] for t in STEM))
        text += rf"|[a-z]Refus(?:{forms})(?![a-z])"
    return text


def _blank_citations(text):
    """Blank every `#N (...)` and `WISH-N (...)` span, parentheses balanced
    across line breaks, keeping each newline so line numbers stay put."""
    out, i = [], 0
    for m in re.finditer(r"(?:#|WISH-)\d+ \(", text):
        if m.start() < i:
            continue
        depth, j = 1, m.end()
        while j < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[j], 0)
            j += 1
        out.append(text[i:m.start()])
        out.append(re.sub(r"[^\n]", " ", text[m.start():j]))
        i = j
    out.append(text[i:])
    return "".join(out)


def _allowed(path, line):
    return any(path == p and fragment in line for p, fragment in ALLOWED_LINES)


def scan(root, terms, pathspec=()):
    """Return `{path: [(line number, line), ...]}` for matches of `terms` in the
    tracked files of `root`, after the exemptions. `git grep` finds the lines;
    Python reads only those, because a regex over every line is ten times slower."""
    regex = pattern(terms)
    exclude = [f":(exclude){p}" for p in EXCLUDED]
    listed = subprocess.run(
        ["git", "grep", "-I", "-n", "-P", "-e", regex, "--", *(pathspec or ["."]), *exclude],
        cwd=root, capture_output=True, text=True, errors="replace", check=False)
    if listed.returncode not in (0, 1):
        raise RuntimeError(listed.stderr)
    candidates = collections.defaultdict(list)
    for row in listed.stdout.splitlines():
        path, number, _ = row.split(":", 2)
        candidates[path].append(int(number))
    compiled = re.compile(regex)
    found = {}
    for path, numbers in candidates.items():
        text = (pathlib.Path(root) / path).read_text(encoding="utf-8", errors="replace")
        lines = text.split("\n")
        for token in TOKEN_EXEMPT:
            text = text.replace(token, " " * len(token))
        blanked = _blank_citations(text).split("\n")
        hits = []
        for n in numbers:
            if not _allowed(path, lines[n - 1]):
                hits += [(n, lines[n - 1])] * len(compiled.findall(blanked[n - 1]))
        if hits:
            found[path] = hits
    return found


def _terms(scope):
    terms = [t for t, s in SCOPES.items() if s == scope]
    return terms + (list(PHRASES) if scope == "markdown" else [])


def _check(found, limits):
    over = {p: (len(h), limits.get(p, 0), h[0]) for p, h in found.items()
            if len(h) > limits.get(p, 0)}
    assert not over, "banned words past a file's limit (path: found, allowed, first):\n" + "\n".join(
        f"  {p}: {n}, {m}, line {first[0]}: {first[1].strip()[:100]}"
        for p, (n, m, first) in sorted(over.items()))


def test_every_banned_term_has_a_scope():
    table = set(terms_in_table((ROOT / WORDS).read_text(encoding="utf-8")))
    assert table - set(SCOPES) == set(), "give each new term of the table a scope in SCOPES"
    assert set(SCOPES) - table == set(), "a term in SCOPES is no longer in the table"


def test_banned_words_stay_out_of_every_tracked_text_file():
    _check(scan(ROOT, _terms("every")), LIMITS_EVERY)


def test_banned_words_stay_out_of_markdown():
    _check(scan(ROOT, _terms("markdown"), ["*.md"]), LIMITS_MARKDOWN)


def _repo(tmp_path, name, text):
    (tmp_path / name).write_text(text, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", name], cwd=tmp_path, check=True)
    return tmp_path


def test_the_scan_catches_the_stem_in_identifiers_and_ignores_the_exempt(tmp_path):
    text = ("walk_refused = 1\nLOSS_REFUSED = 2\nisRefused = 3\nrefusing = 4\n"
            "except ConnectionRefusedError: pass\n"
            "# See #5 (a title that says refused,\n#   across two lines) here\n"
            "AIABJREFUs = 5\nREFUSAL_X = 6\n")
    found = scan(_repo(tmp_path, "sample.py", text), _terms("every"))
    assert [n for n, _ in found["sample.py"]] == [1, 2, 3, 4, 9]
