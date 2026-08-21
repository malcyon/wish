# Purge the game's files from the git history — plan

**Status: planned, not started. Do this before the repository gets any
attention.**

`tests/fixtures/` is clean now, but **the four files are still in the history**,
and GitHub serves any commit to anyone who asks for it. Deleting a file in a
later commit does not remove it; it only stops it being in the tip.

## What has to go

| path | what it is |
|---|---|
| `tests/fixtures/SPELLN64.bin` | the game's 6502 executable code |
| `tests/fixtures/SPELLE64.bin` | a game data file |
| `tests/fixtures/GEO04.bin` | a game map |
| `tests/fixtures/pool1_savedgame0.bin` | SSI's shipped party |
| `tests/fixtures/combat-arena.bin` | a capture of live machine memory |

All five were added and removed within a few days, so the affected range is
short — but the rewrite has to cover every commit that ever contained them.

## How

**`git filter-repo`**, not `filter-branch`. It is the tool the git project now
points at, it is far faster, and it handles path removal in one pass:

```
git filter-repo --invert-paths \
    --path tests/fixtures/SPELLN64.bin \
    --path tests/fixtures/SPELLE64.bin \
    --path tests/fixtures/GEO04.bin \
    --path tests/fixtures/pool1_savedgame0.bin \
    --path tests/fixtures/combat-arena.bin
```

It is not installed by default; `pipx install git-filter-repo` or the distro
package. It also insists on a fresh clone by default, which is a feature.

## The order that matters

1. **Tag or clone the current state first.** The history rewrite in this
   repository has already been done once, so there is a working pattern.
2. Rewrite.
3. **Verify the blobs are gone, not merely unreferenced:**
   `git log --all --diff-filter=A --name-only --format= | sort -u | grep fixtures`
   should list only the saved games, and
   `git rev-list --objects --all | grep -c SPELLN64` should be zero.
4. `git push --force`.
5. **Ask GitHub to garbage-collect.** A force push leaves the old objects
   reachable by direct SHA on GitHub's side for a while. Unreachable objects are
   collected eventually, and opening a support request is the way to hurry it.
6. Anyone with a clone re-clones. Right now that is one person, which is exactly
   why this should happen now rather than later.

## Note

This is one of the two reasons to do it soon. The other is that
`docs/50-experiments.md` is the largest object in the history by a wide margin
and is rewritten on nearly every commit; if the repository is ever slow to
clone, that is why, not these five files.
