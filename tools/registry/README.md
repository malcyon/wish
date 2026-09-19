# registry

Scripts that say where things are and who holds them: the game disks, the specimen tree and its backups, the emulator instance pool and the scratch directories.

| file | purpose |
|---|---|
| `gamedisks.py` | The registry of where the game disks and saves are: this machine's `gamedisks.yaml` (gitignored, copied from `gamedisks.yaml.example`) with environment variables winning; with no arguments it prints each entry's layer, path and whether it exists. |
| `instance.py` | The VICE instance pool: six resources per slot (two monitor ports, a command port, an X display, a work directory, a private `vicerc`) held by an `fcntl.flock` lease, so a crashed run's slot frees itself; `status` reports idle and leaking slots, `claim -- <command>` tears down its own process group on `SIGTERM`, and nothing here kills a process by name. |
| `scratch.py` | Says where a tool writes what it produces: `scratch_dir("dosbox", "shots")` is `<tmp>/wish/dosbox/shots` and `cache_dir("testrun")` is `~/.cache/wish/testrun`; neither creates anything, `ensure(path)` does it just before the first write; import it with `from tools.registry import scratch`. |
| `specimenbackup.py` | Counts the copies of the specimen tree and makes one more: `audit` hashes files under a directory or archive (SHA-256, never by name), `archive` writes the whole tree to one new file outside the repository, `verify` reads an archive back against the live `provenance.toml` files. |
| `specimens.py` | Manages `$WISH_SPECIMENS` (default `~/wish-specimens`), the tree of DOS, C64 and Amiga records this project watched being written: `add` copies a save in with a `provenance.toml` and makes it read-only, `check` verifies each file's SHA-256 and flags unaccounted files, `list` shows the tree. |
