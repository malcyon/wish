"""Sweep of `tools/*.py` for the read-only-specimen staging bug (#472, #476,
#487, #492).

`tools/specimens.py add` makes every specimen read-only on purpose, so nobody
edits the evidence by accident.  `shutil.copy` carries that mode onto the
copy.  A tool that stages such a copy where the running game has to write --
a pool slot's `SIDE0.D64`, a DOSBox instance's `SAVE` directory -- hands the
game a save disk it cannot write to, **and the game does not complain**.
Every write is refused in silence and the run reports success.  On 2026-09-08
a driven Curse run walked its whole menu sequence, left no character file, and
that was read as the game not writing one.  The second half of the same bug is
louder: the next run staging into that directory dies on a bare
`PermissionError` over the leftover.

Four rounds of this were found by hand, one file at a time -- `#430`, `#455`,
`#469`, then `#472`'s twenty-two slot copies, then `#476`'s six tools and
`#487`'s two more sites in one of those same six files.

**This sweep is a destination test with a reviewed allowlist**, which is the
shape `tests/test_repository_contents.py` already uses for
`tests/fixtures/`.  Three attempts at a predicate that separates the good
copies from the bad ones automatically were abandoned on `#492`; a person
reads each call site instead and writes down which it is.

## What the sweep flags

A destination that reaches one of three directories, tracked through
assignments and through a helper's `out`-shaped parameters:

* **a pool slot's own directory** -- `slot.dir`, `slot_dir`.  Reused by every
  later tenant of that slot.
* **a tool's own `--out`** -- `args.out`, `args.output`, `args.dir`.  It
  defaults to a fixed path under `work/`, so it is reused across invocations
  unless the caller passes a new one each time.
* **an emulator instance's staged save directory** -- `save_dir`,
  `save_file(...)`.  This is where the running game reads and writes its
  saved games, so a read-only file here is the silent failure above.

## What the sweep does not flag, and why

**Only `shutil.copy`, `shutil.copy2` and `shutil.copytree` can create the
poisoned file.**  Measured on 2026-09-10, copying a `0444` source on this
machine:

| call | mode of the new file |
|---|---|
| `shutil.copy` | `-r--r--r--` |
| `shutil.copy2` | `-r--r--r--` |
| `shutil.copytree` | `-r--r--r--` |
| `shutil.copyfile` | `-rw-rw-r--` |
| `Path.write_bytes` | `-rw-rw-r--` |

`copyfile` and `write_bytes` open the destination for writing and leave the
default mode on it, so neither can put a read-only file anywhere.  Both can
*fail* on a read-only leftover, but only one of the three above can have left
one, so flagging the three covers the cause.  `tools/instance.py` and
`tools/dosabilitypair.py` already stage this way deliberately.

`tools/session.py` is exempt: `stage_writable` is the function everything
else is supposed to go through, and this is its own implementation.

## The rule for the allowlist

**It may shrink, and it must not grow without a reason written beside the new
entry.**  A new entry is somebody deciding a copy is safe, and this sweep
exists to make somebody take that decision deliberately.  The question to
answer in the reason is the direction: does the source come from **outside**
the run -- a specimen, a player's disk, a `--src` argument -- or is it
something **this run produced**?  Nothing a run produces is read-only, so a
copy of a run's own artefact into `--out` is not this defect.

`OPEN_DEFECTS` is the other list, and it is not an allowlist: those sites are
the real thing, filed and unfixed.  An entry leaves it when the site is
fixed, never because it became inconvenient.
"""
from __future__ import annotations

import ast
import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"

#: The only file allowed to call `shutil.copy` on one of these destinations
#: directly: it is `stage_writable`'s own implementation.
EXEMPT = {"session.py"}

#: The three calls that carry the source's mode onto the copy.  See the
#: module docstring for the measurement that leaves `copyfile` and
#: `write_bytes` out.
MODE_CARRYING = {"copy", "copy2", "copytree"}

#: An expression naming one of the three directories a copy must not land in
#: read-only.  Matched as text against the right-hand side of an assignment
#: and against the destination expression itself.
REUSED = ("slot.dir", "slot_dir", "args.out", "args.output", "args.dir",
          "save_dir", ".save_file(")

#: Parameter names that are one of those directories by convention throughout
#: `tools/`.  A staging helper takes the path as a bare parameter -- which is
#: how `#487`'s two `tools/traitsave.py` sites hid from a sweep that only read
#: call sites -- so a function that takes one of these is scanned as though it
#: had built the directory itself.
REUSED_PARAMS = {"out", "outdir", "out_dir", "staging", "staging_dir",
                 "save_dir", "slot_dir"}


# -- the reviewed allowlist ---------------------------------------------------

#: Every mode-carrying copy in `tools/` whose destination is one of the three
#: reused directories and which a person has read and ruled safe, keyed by
#: file and by the destination expression as it is written.  The reason says
#: what is copied, where it came from, and why it cannot be a read-only
#: specimen.  Read the module docstring before adding one.
ARTEFACT_COPIES: dict[tuple[str, str], str] = {
    # -- a screenshot the run's own emulator took, seconds earlier.  `shot()`
    # writes the PNG through `import` into the instance's `shots/`, so it
    # arrives with the default mode and nothing downstream reads it as a save.
    ("convertrun.py", 'out / "items.png"'): "the inventory screen this run shot",
    ("convertrun.py", 'out / "loaded.png"'): "the load screen this run shot",
    ("convertrun.py", 'out / "sheet.png"'): "the character sheet this run shot",
    ("convertrun.py", 'out / "stuck.png"'): "the screen this run was stuck on",
    ("convertrun.py", 'out / "walked.png"'): "the world after this run walked",
    ("curseregain.py", "shots / png.name"): "this run's own shots directory",
    ("dosencsave.py", "shots / png.name"): "this run's own shots directory",
    ("dosfightrun.py", 'out / f"{name}.png"'): "this run's own shots directory",
    ("dosfightwatch.py", 'out / "encounter.png"'): "the encounter this run shot",
    ("dosfightwatch.py", 'out / "engine-encounter.png"'):
        "the engine-slot encounter this run shot",
    ("dosfightwatch.py", 'out / "engine-loaded.png"'):
        "the engine-slot load screen this run shot",
    ("dosfightwatch.py", 'out / "loaded.png"'): "the load screen this run shot",
    ("dosgnome.py", "out / png.name"): "this run's own shots directory",
    ("dositemcap.py", "out / png.name"): "this run's own shots directory",
    ("dosladder.py", "shots / png.name"): "this run's own shots directory",
    ("dosnewsave.py", 'out / "items.png"'): "the inventory screen this run shot",
    ("dosnewsave.py", 'out / "loaded.png"'): "the load screen this run shot",
    ("dosnewsave.py", 'out / "sheet.png"'): "the character sheet this run shot",
    ("dosnewsave.py", 'out / "stuck.png"'): "the screen this run was stuck on",
    ("dosnewsave.py", 'out / "walked.png"'): "the world after this run walked",
    ("dosoutdoor.py", 'out / "loaded.png"'): "the load screen this run shot",
    ("dosoutdoor.py", 'out / "walked.png"'): "the world after this run walked",
    ("dosoutdoorprobe.py", 'out / "loaded.png"'): "the load screen this run shot",
    ("dosoutdoorprobe.py", 'out / f"{letter}.png"'):
        "one probe slot's load screen this run shot",
    ("dosparty.py", "shots / png.name"): "this run's own shots directory",
    ("dosportraitparty.py", 'out / "seq-0.png"'): "the first sheet this run shot",
    ("dosportraitparty.py", 'out / f"probe-{n}-{key}.png"'):
        "the sheet after one keypress this run made",
    ("dosportraitparty.py", 'out / f"seq-{n}-{key}.png"'):
        "the sheet after one keypress this run made",
    ("dosportraitparty.py", 'out / f"sheet-{index}.png"'):
        "one character's sheet this run shot",
    ("dossheetread.py", "shots / png.name"): "this run's own shots directory",
    ("dosshop.py", "shots / png.name"): "this run's own shots directory",
    ("dostrain.py", "shots / png.name"): "this run's own shots directory",
    ("dostrainprobe.py", "shots / png.name"): "this run's own shots directory",
    ("dualclassagain.py", "shots / png.name"): "this run's own shots directory",
    ("portraitshot.py", 'out / "portrait.png"'): "the portrait this run shot",
    ("portraitshot.py", 'out / "sheet.png"'): "the character sheet this run shot",
    ("portraitshot.py", 'out / f"key{n}-{key}.png"'):
        "the sheet after one keypress this run made",

    # -- a save the run's own game wrote, kept as evidence.  The staged disk
    # and the staged `SAVE` tree are both writable before the game is booted
    # -- `tools/session.py`'s `_restage` and `dosbox.Session.stage` see to
    # that -- so what the game leaves behind is writable too.
    ("c64addprobe.py", "kept"):
        "the slot's SIDE0.D64 after the game's own SAVE CURRENT GAME",
    ("c64addprobe.py", 'out / f"disk-{tag}.D64"'):
        "the slot's SIDE0.D64 as the game left it, kept for a directory read",
    ("c64nametable.py", "kept"):
        "the slot's SIDE0.D64 after the game's own SAVE CURRENT GAME",
    ("c64outdoor.py", 'out / "SEED.D64"'):
        "the SIDE0.D64 this run seeded in its own slot, staged by stage_disks",
    ("c64outdoor.py", "out / name"): "the slot's SIDE0.D64 after ENCAMP > SAVE",
    ("convertrun.py", "out / p.name"):
        "the CHRDAT records the game wrote in this run's staged tree",
    ("convertrun.py", "s.save_dir / p.name"):
        "the .d64 and .SAV files Wish's own writer built for this run, into a "
        "tree Session.stage(fresh=True) has just rebuilt",
    ("curseregain.py", "d / p.name"):
        "the save files the game wrote in this run's staged tree",
    ("defeatdrive.py", 'out / "save-after.d64"'):
        "the slot's SIDE0.D64 after the fight this run drove",
    ("defeatdrive.py", 'out / "save-end.d64"'):
        "the slot's SIDE0.D64 at the end of the run",
    ("dosencsave.py", "d / p.name"):
        "the save files the game wrote in this run's staged tree",
    ("dosladder.py", "d / p.name"):
        "the save files the game wrote in this run's staged tree",
    ("dosnewsave.py", "out / p.name"):
        "the CHRDAT records the game wrote in this run's staged tree",
    ("dosoutdoor.py", "out / p.name"):
        "the CHRDAT records the game wrote in this run's staged tree",
    ("dosoutdoorprobe.py", "out / p.name"):
        "the save and CHRDAT records the game wrote in this run's staged tree",
    ("dosparty.py", "save / p.name"):
        "the save files the game wrote in this run's staged tree",
    ("dostrain.py", "d / p.name"):
        "the save files the game wrote in this run's staged tree",
    ("dossheetread.py", "dest"):
        "the whole staged SAVE tree after the game resaved it; the destination "
        "is rmtree'd first, so no leftover survives either",
    ("fleedrive.py", 'out / "save-after.d64"'):
        "the slot's SIDE0.D64 after the flee this run drove",
    ("portraitshot.py", "keep"):
        "the staged SAVE tree kept as a template; rmtree'd first",
    ("statusdrive.py", 'out / "saved.d64"'):
        "the slot's SIDE0.D64 after the game's own save",
    ("traitask.py", 'out / "saved.d64"'):
        "the slot's SIDE0.D64 after the game's own save",
    ("traitdrive.py", 'out / "saved.d64"'):
        "the slot's SIDE0.D64 after the game's own save",
    ("traitsave.py", 'out / "saved.d64"'):
        "the slot's SIDE0.D64 after the game's own save",

    # -- copied from outside the run, and the site restores the write bit
    # itself on the very next line.  These predate `stage_writable` and do
    # its second half; what they do not do is unlink the destination first,
    # so an earlier run killed between the copy and the chmod leaves one that
    # the next `shutil.copy` cannot open.  Routing them through
    # `stage_writable` would close that, and none of them is the silent
    # failure this sweep is for.
    ("cursethac0.py", "out"): "a --base save disk, chmod 0o644 on the next line",
    ("dositemcap.py", "dest"):
        "a $WISH_SPECIMENS save tree, chmod 0o644 on the next line",
    ("inventorycheck.py", "dest"):
        "a --base save disk, chmod 0o644 on the next line",
    ("pursecheck.py", "dest"):
        "a --base save disk, chmod 0o644 on the next line",
    ("ssbedit.py", "dest"):
        "a --base save disk, chmod 0o644 on the next line",
}

#: Sites the sweep names that are the defect, filed and not yet fixed.  This
#: is not an allowlist and it is not a place to put a copy nobody wants to
#: think about: an entry leaves when the site is fixed.
#:
#: `#495`'s six emptied this dict.  Each site now routes through
#: `tools.session.stage_writable`, so the sweep no longer finds a bare
#: `shutil.copy`/`copy2`/`copytree` into any of the three reused directories
#: anywhere in `tools/`.
OPEN_DEFECTS: dict[tuple[str, str], str] = {}


# -- the sweep ----------------------------------------------------------------

def _own_statements(scope):
    """A scope's own statements, without descending into a nested scope.

    Tracking names file-wide, which an earlier version of this sweep did,
    makes one function's `dest` stand in for another's -- `tools/doscurse.py`
    copies into `$WISH_SPECIMENS` through a variable of that name, and was
    reported as a staging copy for no better reason than the spelling.
    """
    out = []
    for child in ast.iter_child_nodes(scope):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef, ast.Lambda)):
            continue
        out.append(child)
    return out


def _scopes(tree):
    """The module body and every function body, each with its own statements."""
    yield tree, _own_statements(tree)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node, _own_statements(node)


def _walk(statements):
    for statement in statements:
        yield from ast.walk(statement)


def _names_a_reused_directory(text: str) -> bool:
    return any(name in text for name in REUSED)


def _tracked(statements, source: str, seeded) -> set[str]:
    """Names bound, directly or through another such name, to a reused
    directory.

    Iterated to a fixed point rather than in one pass, because the chain can
    be several assignments long: `here = pathlib.Path(slot.dir)`, then
    `work_save = f"{here}/SIDE0.D64"`, then a copy into `work_save` --
    `tools/walkrun.py`, and the shape the committed `#476` sweep walked past.
    """
    names = set(seeded)
    while True:
        before = set(names)
        for node in _walk(statements):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if value is None:
                continue
            text = ast.get_source_segment(source, value) or ""
            if not (_names_a_reused_directory(text)
                    or any(isinstance(n, ast.Name) and n.id in names
                           for n in ast.walk(value))):
                continue
            targets = (node.targets if isinstance(node, ast.Assign)
                       else [node.target])
            for target in targets:
                for n in ast.walk(target):
                    if isinstance(n, ast.Name):
                        names.add(n.id)
        if names == before:
            return names


def _seeded_parameters(node) -> set[str]:
    a = node.args
    every = list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)
    return {arg.arg for arg in every if arg.arg in REUSED_PARAMS}


def reused_destination_copies(root: pathlib.Path = TOOLS) -> dict:
    """Every mode-carrying copy in `root` landing in a reused directory.

    Keyed by `(filename, destination expression)` and valued with the lines
    it was found on.  The key is what the two lists above are written
    against: a line number moves whenever anything above it is edited, and a
    list keyed on one would go stale without anybody's copy having changed.

    **The destination need not be a bare name.**  `staging / "STAGED.D64"` is
    a `BinOp`, so every name inside the destination expression is checked
    rather than only asking whether the whole expression *is* a tracked name.
    """
    found: dict[tuple[str, str], set[int]] = {}
    for path in sorted(root.glob("*.py")):
        if path.name in EXEMPT:
            continue
        # `encoding="utf-8"` and not the platform default: Windows reads as
        # cp1252, and several tools here carry a byte it has no character
        # for -- an em dash, a `▸`, a game string quoted in a docstring.  Both
        # Windows CI jobs went red on `UnicodeDecodeError` at position 3972 of
        # the first such file while both Linux jobs passed.
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue
        scopes = list(_scopes(tree))
        module_names = _tracked(scopes[0][1], source, ())
        for node, statements in scopes:
            if node is tree:
                names = module_names
            else:
                names = _tracked(statements, source,
                                 module_names | _seeded_parameters(node))
            for call in _walk(statements):
                if not isinstance(call, ast.Call):
                    continue
                func = call.func
                if not (isinstance(func, ast.Attribute)
                        and isinstance(func.value, ast.Name)
                        and func.value.id == "shutil"
                        and func.attr in MODE_CARRYING):
                    continue
                if len(call.args) < 2:
                    continue
                dest = call.args[1]
                text = ast.get_source_segment(source, dest) or ""
                if not (_names_a_reused_directory(text)
                        or any(isinstance(n, ast.Name) and n.id in names
                               for n in ast.walk(dest))):
                    continue
                found.setdefault((path.name, text), set()).add(call.lineno)
    return found


def _where(found: dict, key) -> str:
    return f"{key[0]}:{','.join(str(n) for n in sorted(found[key]))}"


# -- the tree as it stands ----------------------------------------------------

def test_every_copy_into_a_reused_directory_has_been_read_and_ruled_on():
    """#492: a copy that is neither on the allowlist nor on the filed-defect
    list is one nobody has looked at."""
    found = reused_destination_copies()
    unruled = sorted(set(found) - set(ARTEFACT_COPIES) - set(OPEN_DEFECTS))
    assert unruled == [], (
        "these copy into a pool slot, a tool's own --out, or an emulator "
        "instance's staged SAVE directory with a call that carries the "
        "source's mode, and nobody has said which kind they are. Read each "
        "one: if the source is something this run produced, add it to "
        "ARTEFACT_COPIES with a reason; if it comes from outside the run, "
        "route it through tools.session.stage_writable:\n  "
        + "\n  ".join(f"{_where(found, key)}  {key[1]}" for key in unruled))


def test_the_allowlist_names_no_copy_that_has_gone_away():
    """The list may shrink, and a stale entry is how it grows by accident:
    an entry nothing matches any more would silently bless whatever took that
    destination expression next."""
    found = reused_destination_copies()
    stale = sorted(set(ARTEFACT_COPIES) - set(found))
    assert stale == [], (
        "these allowlist entries match no copy in tools/ any more, so delete "
        "them:\n  " + "\n  ".join(f"{f}  {d}" for f, d in stale))


def test_every_filed_defect_is_still_there_and_still_filed():
    """`OPEN_DEFECTS` is a claim about the tree, so it can be wrong. An entry
    whose site has been fixed comes out; one that is still there keeps its
    issue number in the reason, so the next reader can go and look."""
    found = reused_destination_copies()
    fixed = sorted(set(OPEN_DEFECTS) - set(found))
    assert fixed == [], (
        "these are fixed -- take them out of OPEN_DEFECTS:\n  "
        + "\n  ".join(f"{f}  {d}" for f, d in fixed))
    assert all("#" in reason for reason in OPEN_DEFECTS.values()), (
        "every OPEN_DEFECTS entry names the issue it was filed as")


def test_the_two_lists_do_not_overlap():
    """A site is safe or it is a defect. Both would let a real one hide behind
    a reason somebody wrote for the other list."""
    both = sorted(set(ARTEFACT_COPIES) & set(OPEN_DEFECTS))
    assert both == [], both


def test_every_reason_says_something():
    assert [k for k, v in ARTEFACT_COPIES.items() if len(v) < 20] == []


# -- proof against the tree the bug was actually in ---------------------------

#: The six tools `#476` fixed and the one `#487` fixed, with the commit that
#: fixed each.  `git show <sha>~1:<path>` reads the defective version without
#: touching the working tree.
PRE_FIX = (
    ("0eda257", "statusdrive.py"),
    ("0eda257", "testpartyrun.py"),
    ("0eda257", "traitask.py"),
    ("0eda257", "traitdrive.py"),
    ("0eda257", "traitsave.py"),
    ("0eda257", "turndrive.py"),
    ("9fd51fb", "traitsave.py"),
)

#: What the sweep has to name in each of those files: the destination
#: expression of the copy that handed the game a read-only save disk.  The two
#: `traitsave.py` rows under `9fd51fb` are `#487`'s, and they are the ones
#: `#476`'s shape missed -- they land straight in `--out` rather than in an
#: `out / "disks"` under it, and the source is a bare parameter with no
#: `args.` in it, which is what defeated the direction test.
PRE_FIX_SITES = {
    ("0eda257", "statusdrive.py"): {"staging / save"},
    ("0eda257", "testpartyrun.py"): {'staging / "STAGED.D64"'},
    ("0eda257", "traitask.py"): {"staging_dir / save"},
    ("0eda257", "traitdrive.py"): {"staging_dir / save"},
    ("0eda257", "traitsave.py"): {"staging_dir / save", "original", "edited"},
    ("0eda257", "turndrive.py"): {'staging / "STAGED.D64"'},
    ("9fd51fb", "traitsave.py"): {"original", "edited"},
}


def _checked_out(sha: str, name: str, into: pathlib.Path) -> pathlib.Path:
    done = subprocess.run(["git", "show", f"{sha}~1:tools/{name}"],
                          cwd=ROOT, capture_output=True)
    if done.returncode != 0:
        pytest.skip(f"no git history for {sha}: "
                    f"{done.stderr.decode('utf-8', 'replace').strip()}")
    (into / name).write_bytes(done.stdout)
    return into


@pytest.mark.parametrize(("sha", "name"), PRE_FIX)
def test_the_sweep_names_every_tool_that_was_defective_before_the_fix(
        sha, name, tmp_path):
    """A sweep that only ever asserts `== []` against a clean tree cannot be
    told apart from one whose matching never matches. This is what tells them
    apart: eight sites across seven files, each read out of the commit that
    fixed it.

    An earlier attempt caught four of the six `#476` tools, which is how it
    was found wanting.
    """
    where = tmp_path / f"{sha}-{name}"
    where.mkdir()
    _checked_out(sha, name, where)

    found = reused_destination_copies(where)
    named = {dest for (_, dest) in found}

    assert PRE_FIX_SITES[(sha, name)] <= named, (
        f"{sha}~1:tools/{name} staged a save into a reused directory with a "
        f"bare shutil.copy and the sweep did not name it; found {sorted(named)}")


def test_the_sweep_names_all_eight_pre_fix_sites_together(tmp_path):
    """The count, in one assertion: six tools for `#476` and two more sites
    for `#487`, eight staging copies in seven files."""
    total = 0
    for sha, name in PRE_FIX:
        where = tmp_path / f"{sha}-{name}"
        where.mkdir()
        _checked_out(sha, name, where)
        found = reused_destination_copies(where)
        wanted = PRE_FIX_SITES[(sha, name)]
        total += sum(len(found[key]) for key in found if key[1] in wanted)

    # `traitsave.py` appears twice, once per commit, and `#487`'s two sites
    # are in both versions -- so the eight distinct defects are counted ten
    # times here.  What the number proves is that every one is reachable.
    assert total == 10, total


# -- the negative case --------------------------------------------------------

#: Real sites in `tools/` where a run copies something it produced itself into
#: its own `--out`. Each was read for `#492` and each has to stay off the
#: defect list, or the sweep is a nuisance and the next reader learns to
#: ignore it.
OWN_RESULT = (
    ("convertrun.py", 'out / "loaded.png"'),      # a screenshot it just took
    ("statusdrive.py", 'out / "saved.d64"'),      # the disk the game just wrote
    ("defeatdrive.py", 'out / "save-after.d64"'),  # the same, after a fight
    ("dosladder.py", "d / p.name"),               # the staged tree's own records
)


@pytest.mark.parametrize(("name", "dest"), OWN_RESULT)
def test_a_run_copying_its_own_result_into_out_is_not_a_defect(name, dest):
    """The sweep sees these -- it is a destination test -- and what it must
    never do is report one as the bug. Nothing a run produces is read-only:
    a screenshot arrives from `import`, a save disk from the game writing the
    slot's own writable `SIDE0.D64`."""
    assert (name, dest) in ARTEFACT_COPIES, (name, dest)
    assert (name, dest) not in OPEN_DEFECTS, (name, dest)


def test_the_failure_message_names_none_of_the_run_s_own_results():
    """The assertion a person actually reads. If any of the four above ever
    reached it, the next reader would learn the sweep cries wolf."""
    found = reused_destination_copies()
    unruled = set(found) - set(ARTEFACT_COPIES) - set(OPEN_DEFECTS)
    assert unruled & set(OWN_RESULT) == set()


def test_a_copyfile_or_a_write_bytes_into_out_is_not_flagged(tmp_path):
    """Neither carries the source's mode, so neither can leave the read-only
    file this sweep is about. The measurement is in the module docstring."""
    (tmp_path / "toolstub.py").write_text(
        "import pathlib\n"
        "import shutil\n"
        "\n"
        "def stage(args, src):\n"
        "    out = pathlib.Path(args.out)\n"
        "    shutil.copyfile(src, out / 'SIDE0.D64')\n"
        "    (out / 'copy.d64').write_bytes(src.read_bytes())\n")

    assert reused_destination_copies(tmp_path) == {}


def test_a_copy_into_an_unrelated_directory_is_not_flagged(tmp_path):
    """`$WISH_SPECIMENS` is where a specimen is *meant* to go, read-only and
    all -- `tools/doscurse.py`'s `copy` command does exactly this."""
    (tmp_path / "toolstub.py").write_text(
        "import pathlib\n"
        "import shutil\n"
        "\n"
        "SPECIMENS = pathlib.Path('/specimens')\n"
        "\n"
        "def keep(s, name):\n"
        "    dest = SPECIMENS / name\n"
        "    shutil.copytree(s.save_dir, dest)\n")

    assert reused_destination_copies(tmp_path) == {}


def test_a_wrapped_copy_is_not_flagged(tmp_path):
    """`stage_writable` itself, or a call routed through it, is not a hit."""
    (tmp_path / "toolstub.py").write_text(
        "import pathlib\n"
        "from tools import session as S\n"
        "\n"
        "def stage(slot, save):\n"
        "    S.stage_writable(save, pathlib.Path(slot.dir) / 'SIDE0.D64')\n")

    assert reused_destination_copies(tmp_path) == {}


# -- the shapes the sweep exists to catch, spelled out ------------------------

def test_the_sweep_catches_a_copy_into_a_pool_slot(tmp_path):
    """`#430`, `#455`, `#469`: the slot's own directory, written inline."""
    (tmp_path / "toolstub.py").write_text(
        "import pathlib\n"
        "import shutil\n"
        "\n"
        "def stage(slot, save):\n"
        "    shutil.copy(save, pathlib.Path(slot.dir) / 'SIDE0.D64')\n")

    assert reused_destination_copies(tmp_path) == {
        ("toolstub.py", "pathlib.Path(slot.dir) / 'SIDE0.D64'"): {5}}


def test_the_sweep_catches_a_slot_path_built_two_assignments_earlier(tmp_path):
    """`tools/walkrun.py`'s shape, and the one the committed `#476` sweep
    walked past: the slot's directory reaches the call through two hops, and
    neither the destination expression nor the assignment that built it
    mentions `slot.dir`."""
    (tmp_path / "toolstub.py").write_text(
        "import shutil\n"
        "\n"
        "def stage(slot, base):\n"
        "    here = str(slot.dir)\n"
        "    work_save = f'{here}/SIDE0.D64'\n"
        "    shutil.copy(base, work_save)\n")

    assert reused_destination_copies(tmp_path) == {
        ("toolstub.py", "work_save"): {6}}


def test_the_sweep_catches_a_copy_into_any_out_scoped_directory(tmp_path):
    """`#492`: the committed sweep matched the literal name `"disks"`, so a
    tool staging into `out / "stage"` had the identical defect and passed in
    silence."""
    (tmp_path / "toolstub.py").write_text(
        "import pathlib\n"
        "import shutil\n"
        "\n"
        "def stage(args, src):\n"
        "    out = pathlib.Path(args.out)\n"
        "    staging = out / 'stage'\n"
        "    staging.mkdir(parents=True, exist_ok=True)\n"
        "    shutil.copy(src, staging / 'STAGED.D64')\n")

    assert reused_destination_copies(tmp_path) == {
        ("toolstub.py", "staging / 'STAGED.D64'"): {8}}


def test_the_sweep_catches_a_copy_in_a_helper_that_takes_out_as_a_parameter(
        tmp_path):
    """`#487`'s shape: the staging happens inside a helper, so `--out` is a
    bare parameter and there is no `args.` anywhere near the call."""
    (tmp_path / "toolstub.py").write_text(
        "import shutil\n"
        "\n"
        "def stage(out, src):\n"
        "    original = out / 'original.d64'\n"
        "    shutil.copy(src, original)\n")

    assert reused_destination_copies(tmp_path) == {
        ("toolstub.py", "original"): {5}}


def test_the_sweep_catches_a_copy_into_a_staged_save_directory(tmp_path):
    """The silent half of the bug: the game reads and writes its saved games
    out of the instance's staged `SAVE` directory, so a read-only record there
    is refused on every write with no message at all."""
    (tmp_path / "toolstub.py").write_text(
        "import shutil\n"
        "\n"
        "def stage(s, source, letter):\n"
        "    for p in sorted(source.glob('CHRDAT*')):\n"
        "        shutil.copy(p, s.save_dir / p.name)\n")

    assert reused_destination_copies(tmp_path) == {
        ("toolstub.py", "s.save_dir / p.name"): {5}}


def test_the_sweep_catches_copy2_and_copytree(tmp_path):
    """`#476` and everything before it looked for one spelling. All three of
    these carry the source's mode -- measured, in the module docstring."""
    (tmp_path / "toolstub.py").write_text(
        "import pathlib\n"
        "import shutil\n"
        "\n"
        "def stage(args, src, tree):\n"
        "    out = pathlib.Path(args.out)\n"
        "    shutil.copy2(src, out / 'SIDE0.D64')\n"
        "    shutil.copytree(tree, out / 'SAVE')\n")

    assert reused_destination_copies(tmp_path) == {
        ("toolstub.py", "out / 'SIDE0.D64'"): {6},
        ("toolstub.py", "out / 'SAVE'"): {7}}
