# registry

Tests for the machine-local registries: the game-disk registry, the emulator instance pool, scratch directories and the specimen store.

| file | purpose |
|---|---|
| `test_gamedisks.py` | Checks `automap/gamedisks.py`: environment variable over registry, search order, home expansion, the one-line message for a missing registry, and that the committed example is a complete registry. |
| `test_instance.py` | Checks the emulator instance pool in `tools/registry/instance.py`: slot allocation, leases and contention, the reap table and the seeded `vicerc`, none of which needs an emulator. |
| `test_scratch.py` | Checks that `tools/registry/scratch.py` gives one directory per tool under the temp directory and creates nothing until asked. |
| `test_specimenbackup.py` | Checks that `tools/registry/specimenbackup.py` counts the copies of each recorded specimen and archives, verifies and refuses destinations correctly, in a temporary tree. |
| `test_specimens.py` | Checks that `tools/registry/specimens.py` adds specimens read-only with their hashes and provenance, then lists and checks them, under a temporary root that is never the real store. |
| `test_tooldisks.py` | Checks that every disk-reading tool stops with a message, rather than scanning the current directory, on a machine with no disks. |
