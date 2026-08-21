# Converting between the DOS and C64 versions — plan

**Status: planned, not started. Feasible at the character level; a whole-save
conversion is a different and much larger question.**

Donald asked whether the editor could turn a DOSBox save into a C64 save and
back. The short answer is **yes for characters, probably not for saves**, and
the difference is worth stating before any code is written.

---

## What the two formats actually are

The record is **rearranged, not translated**. Both ports store the same
information; neither stores it in the same place.

| field | DOS | C64 |
|---|---|---|
| name | `0x000` length byte, then 15 | `0x000`, 20 bytes, NUL-padded |
| strength | `0x010` | `0x014` |
| intelligence | `0x011` | `0x015` |
| exceptional strength | `0x016` | `0x01A` |
| THAC0 base | `0x02D` | `0x071` |
| race / class | `0x02E` / `0x02F` | `0x072` / `0x073` |
| age | `0x030`, 2 bytes | `0x074`, 2 bytes |
| hit points maximum | `0x032`, **1 byte** | `0x076`, **2 bytes** |

The early fields differ by **exactly four**, which is exactly how much wider the
C64's name field is — the abilities are otherwise in the same order. Past that
the layouts diverge properly.

Two things that are *not* obstacles, and are worth saying so nobody worries
about them: **both machines are little-endian**, so multi-byte fields need no
swapping; and the DOS character file is ASCII, so names need padding and
length-prefixing rather than transliteration. There is no PETSCII in the record.

The DOS layout above comes from the community format notes in
`work/coab-research/formats/`, **not from a file we have decoded ourselves**.
Treat it as PROBABLE until checked against a real DOS save.

---

## Convert characters, not saves

The natural unit is the **character file**, and that is not a workaround — it
is what the games themselves move. Pool of Radiance exports characters, and
Curse of the Azure Bonds imports a party from Pool of Radiance. The format
exists to be moved.

A whole save carries far more: the party's position, the clock, the twelve
record slots, the item area, the loaded-file cache, the quest flags at
`$4A20`-`$4AFF`, the exploration the game does not store. Much of that is
addresses and file indices specific to one port. **Converting a save means
claiming those correspond, and mostly nobody has shown that they do.**

So: characters convert. A party converts, one character at a time. A save
does not, and the plan should say so plainly rather than half-doing it.

---

## The shape of it

We already have the neutral middle. `por/yaml_io.py` decodes a C64 record into
named fields and writes it back; `por/layout.py` is the field table. Conversion
is the same idea with a second table:

```
DOS character file  ->  decode  ->  named fields  ->  encode  ->  C64 record
C64 record          ->  decode  ->  named fields  ->  encode  ->  DOS file
```

That means a new `por/dos_layout.py` beside `por/layout.py`, in the same
declarative style with a confidence on every field, and the existing YAML
export as the interchange. **No new format is invented**: the middle is the one
the editor already uses.

---

## What cannot survive the trip, and must be said out loud

* **The combat icon.** C64 icons are 18 screen codes into `CHARPIC00` plus 18
  colours — a C64 charset. DOS has no such thing. Going to C64, the icon must
  be built from the option tables (`por/iconparts.py` composes a legal one);
  going to DOS, it is dropped.
* **Portrait ids.** `HEADnn`/`BODYnn` name files on the C64 disks. The DOS art
  is a different set with different numbering.
* **Anything cached rather than stored.** The C64 roster block holds derived
  combat values; they should be recomputed for the target, not copied.
* **Item and spell numbering**, until someone checks they agree. They may; the
  spell list is the same game. **Do not assume it.**

## Losslessness, which is the project's whole promise

`wish` never modifies a save it was given, and a no-op save is byte-identical.
**Conversion cannot honour that in both directions**, because the target format
has fields the source does not carry.

So the rule has to be explicit:

* conversion **always writes a new file** and never touches the source;
* every field that could not be carried is **reported**, not silently defaulted
  — the same discipline as `--dry-run` in the CLI;
* a round trip (C64 to DOS to C64) is **not** expected to be byte-identical,
  and a test should assert what it *is* expected to preserve, so the losses are
  a fixed known list rather than a surprise.

---

## What has to be found out first

1. **Verify the DOS record against a real DOS save.** We have none. This is the
   blocker, and it is small: one DOS save of a known party.
2. **The DOS save container.** The C64 keeps `SAVEDGAME0`/`SAVEDGAME1` as PRG
   files on a D64. What does the DOS version write, and where do character
   files live relative to it?
3. **Do the item and spell tables agree** between ports?
4. **Does DOS store anything the C64 does not?** If so, C64 to DOS has holes to
   fill as well.

## Order of work

1. Get a DOS save and check the layout above. Nothing else is worth doing
   first.
2. `por/dos_layout.py`, declarative, confidence per field.
3. Read a DOS character into the existing YAML export. That alone is useful —
   it makes `wish-cli` a DOS character viewer.
4. Write a C64 record from that YAML.
5. The reverse.
6. An editor menu item, once the CLI path is trustworthy.

## Verification

* A DOS character read and written back unchanged, byte for byte — the same
  losslessness bar the C64 side already holds.
* A C64 character converted to DOS and back preserves everything on the
  documented "survives" list, and nothing on the "lost" list surprises anyone.
* A converted character **loads in the target game** and its sheet reads the
  same. That is the only test that really counts, and it needs both emulators.
