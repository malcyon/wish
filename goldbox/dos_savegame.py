"""The DOS ``SAVGAM<slot>.DAT`` saved game, mapped field by field (#59).

`goldbox/dos.py` decodes the DOS *character record*; this module is the map of
the saved game around it, the DOS counterpart of `docs/30-savegame-layout.md`.
Everything here was established by differential analysis in DOSBox: twelve
specimens -- Donald's own slots A, B and J, four saves taken one action
apart, two engine resaves of converted parties, and three saves made on the
overland travel map by playing there (#59's outdoor pass, `work/p59-outdoor`).
The five-region map below is Pool of Radiance's; the other three titles are
`SAVE_SHAPES`, one row of region widths each, and what is graded there is
graded there.  `docs/141-dos-savegame.md` is the prose
form; `docs/50-experiments.md` "Mapping the DOS saved game" is the reasoning.

The file, in five regions
-------------------------
====================  =========================================================
``0``                 one byte: the current area's ``.DAX`` container number
                      (1-8).  Numerically the same as the C64 ``POOL`` disk
                      side that carries the area.
``1``-``5120``        2560 ``u16le`` VM variables, indexed by the address the
                      ECL bytecode uses: ``offset = 1 + 2*(addr - $4900)``.
                      Sparse -- 2407 of 2560 words are zero in all nine
                      specimens.  Quest flags, the clock, the area, the party
                      size and the wallset triple all live here, mostly at the
                      *same ECL addresses the C64 uses*.
``5121``-``12800``    the ECL text buffer: the current area's script, its
                      ``ECL<n>.DAX`` block from byte 2 on.  **Live on load**
                      -- a retarget that leaves the template's script here
                      dies in ``Load3DMap`` whatever else it writes, so it is
                      one of the retarget's writes and the one thing the
                      recipe needs the game's own files for.
``12801``-``12808``   the party's square and size: x, y, facing (doubled),
                      then four bytes of unknowns, then the party size again
                      as one byte.  Outdoors x and y freeze at the last
                      indoor square and the live square is the VM pair
                      ``$49C3``/``$49C4`` -- `travel_square`.
``12809``-``13136``   eight 41-byte character slots -- a length-prefixed
                      ``CHRDAT<letter><n>`` filename the engine *actually
                      loads the party from* (proven: a slot-J file staged as
                      slot C loaded J's characters), each followed by 32
                      bytes of heap scratch.  Six are filled and the last two
                      hold the stack, which is the 82 bytes this page called
                      UI scratch until #175 -- see ``NAME_SLOTS``.
====================  =========================================================

Pools of Darkness is the other shape
------------------------------------
It writes 1024 **byte-wide** ECL variables from file offset 0, variable *N* at
offset *N* - 1, where the first three titles write 2560 ``u16le`` words from
``$4900``.  Nothing in it can line up with ``$5012`` or ``$503E`` under any
origin, which is why #53 could not find them.  ``pod_var`` reads it,
``POD_CLOCK`` and its siblings name what the engine puts in it, and its square
block is twelve bytes rather than eight -- ``SAVE_POOLS_OF_DARKNESS`` and
`docs/141-dos-savegame.md` carry the evidence (#175).
"""
from __future__ import annotations

import dataclasses
import struct


class DosSaveError(ValueError):
    """A buffer that is not a DOS saved game, or an address outside it.

    Its own class rather than `goldbox.dos.DosRecordError` because this module is
    the layer *under* `goldbox/dos.py` -- importing it the other way would invert
    the edge the module graph in `docs/117-save-conversion.md` exists to keep
    honest.  Both derive from `ValueError`, so a caller that catches that
    catches either.
    """


class DaxError(DosSaveError):
    """A `.DAX` block does not decode -- truncated, or not this container.

    A subclass so that `goldbox.dos.write_dos_save`, which catches `DosSaveError`
    around the block it lifts the target area's script out of, keeps catching
    it.
    """


SAVGAM_SIZE = 13137          # Pool of Radiance; Curse is 13149, Secret 5469,
                             # and Pools of Darkness has no SAVGAM?.DAT at all
                             # -- 1364 bytes of SAVGAM?.PTY beside a 12-byte
                             # VAULT?.DAT (#53). All four are in SAVE_SHAPES;
                             # only this one is decoded to the field.
DAX_NUMBER = 0               # byte 0: which GEO/ECL container holds the area
VAR_BASE = 0x4900
VAR_WORDS = 2560             # $4900-$52FF
VAR_OFFSET = 1

ECL_BUFFER = (5121, 12801)   # the loaded script text -- **live**, see below
#: The ECL text buffer holds the target area's `ECL<n>.DAX` block from its
#: third byte on: every block opens `88 13` -- `u16le` 5000 -- and the save
#: carries everything after it.  #59 measured the offset as 39/148/28 for
#: areas 0/21/20 and recorded the buffer as dead weight the loader refills;
#: both are wrong.  The offset is 2 for all three, and a retarget that leaves
#: the template's script in place dies in `Load3DMap` however many variables
#: it writes -- `work/p60/run2`, variant X1.
#:
#: Past the script's end the buffer is **all zeros** -- 6 of 6 specimens,
#: Donald's A/B/J and the three outdoor saves, remnants of 209/1972/3/1113
#: bytes each without one nonzero byte (#59, the outdoor pass).  An earlier
#: claim that it held stale remnants of longer previous scripts was wrong.
ECL_HEADER = 2

#: Pool of Radiance's own square offsets.  Curse of the Azure Bonds writes
#: its square at the same three bytes -- both engines emit the square block
#: the moment the variable array and the staged script run out, and both
#: those regions are the same size in the two titles (#253).  Silver Blades'
#: is at 5121 because it stages no script, and Pools of Darkness' is at 1024.
#: So a writer for any title but Pool of Radiance still reads
#: `shape.pos_x`/`pos_y`/`pos_facing` rather than these three names.
POS_X, POS_Y, POS_FACING = 12801, 12802, 12803
FACING_SCALE = 2             # 0 N, 2 E, 4 S, 6 W
# The four bytes between the facing and the party size, measured over the
# twelve genuine engine-written specimens (#59). None of them is party or
# place data and none is read by the load path, but a conversion that leaves
# them at the template's values is inheriting somebody else's state, so each
# has a measured value to write instead.
SCRATCH_BYTE = 12804         # unnamed and engine-maintained: it replaced a
                             # hand-built 0 with 9 in #59's run 9 and a
                             # from-nothing 0 with 14 in #26's. **Not a
                             # function of indoors**: this said so until
                             # 2026-09-02, and an indoor resave holding 14
                             # refuted it. 0 is written indoors because 8 of
                             # the 9 indoor specimens hold it and a save
                             # carrying it loads, not because 0 means indoors
SCRATCH_INDOORS, SCRATCH_OUTDOORS = 0, 14
VM_COPY_BYTE = 12805         # the low byte of $5200, equal in 13 of 13 files
VIEW_MODE_BYTE = 12806       # 1 indoors, 3 outdoors -- perfectly correlated
                             # with $49E6 in 12 of 12, so write it from that
TAIL_CONSTANT_BYTE = 12807   # 2 in all twelve genuine specimens
TAIL_CONSTANT = 2
VIEW_MODE_INDOORS, VIEW_MODE_OUTDOORS = 1, 3
PARTY_SIZE_BYTE = 12808      # the same count the word at $503E carries

PARTY_TABLE = 12809          # six entries of 41 bytes
PARTY_ENTRY = 41
PARTY_ENTRIES = 6
PARTY_NAME_LEN = 9           # length byte + up to 8 of "CHRDAT<letter><n>"
#: The trailing menu-text and heap scratch after the six character entries.
#: The same 82 bytes in all four titles, and it really is text scratch: it
#: holds `Camp: ` in a Pool of Radiance save and `Choose a FUNCTION` in a
#: Silver Blades one.
UI_SCRATCH = 82
#: The character-file table is **eight** 41-byte slots, not six and then 82
#: bytes of scratch.  Pools of Darkness' save routine copies names into
#: `[bp + 41*i - 0x171]` for `i` up to 8 and then writes `0x148` = 328 bytes in
#: one `BlockWrite` (`GAME.OVR:0x13595` and `0x13647`), and its *loader* reads
#: the same 328 for a Silver Blades container after seeking to 5140 -- which is
#: `SAVE_SECRET_OF_THE_SILVER_BLADES.party_table - 1` exactly (#175).
#:
#: So the 82 bytes are slots 6 and 7 left holding whatever was on the stack,
#: which is why they read `Camp: ` and `Choose a FUNCTION`.  8 x 41 = 328 =
#: `PARTY_ENTRIES * PARTY_ENTRY + UI_SCRATCH`, so no offset moves and both
#: constants keep their values; what changes is what the last 82 bytes *are*.
#: CONFIRMED for Pools of Darkness and Silver Blades from the code above;
#: PROBABLE for Pool of Radiance and Curse, where the evidence is that slots 6
#: and 7 land on the junk at exactly the 41-byte stride -- 13055 reads
#: `lter Exit` and 13096 a heap word in Donald's A, B and J.
#:
#: `character_files` still reads `PARTY_ENTRIES` of them, because no container
#: on this machine holds a seventh name and a junk slot with a plausible
#: length byte would be read as a filename the engine loads the party from.
NAME_SLOTS = 8

# ---------------------------------------------------------------------------
# Pools of Darkness: the byte-wide variable array (#175)
# ---------------------------------------------------------------------------
#: How many one-byte ECL variables the array holds.  `GAME.OVR:0x1A275` is the
#: only `GetMem` that fills the pointer the save routine writes from, and it
#: asks for `0x400`.
POD_VAR_COUNT = 1024
#: `GetVar`/`SetVar` (`GAME.OVR:0x6F14` and `0x6D51`) do `ax := index; dec ax`
#: and land on `les di, [0x87F8] / add di, ax / add di, 0xFFFF`, so **variable
#: *N* is file offset *N* - 1** and the numbering is 1-based.
POD_VAR_FIRST = 1

#: The clock: seven digits at file offsets 4-10, one byte each, each carrying
#: into the next at its own radix.  `GAME.OVR:0x27AF4` copies `block[i + 4]`
#: for `i` in 0..6 into a local word array, increments one digit, calls the
#: carry routine at `0x279F6`, and copies all seven back.
POD_CLOCK = 5                # variable 5, file offset 4
POD_CLOCK_DIGITS = 7
#: The radices, in digit order.  The carry routine indexes a seven-word table
#: at `DS:0x6D0A`; `GAME.EXE` file offset `0xE8F0` holds
#: `0a 00 0a 00 06 00 18 00 1e 00 0c 00 64 00` and nothing else in either
#: binary is a run of seven plausible radices.  It is Pool of Radiance's own
#: six -- `10 10 6 24 30 12`, `docs/141-dos-savegame.md` -- with **100**
#: appended, and when the seventh overflows the engine walks the character
#: list adding one to the word at record offset `0xB0` in each: the party
#: ageing a year.
POD_CLOCK_RADIX = (10, 10, 6, 24, 30, 12, 100)

POD_DUNGEON_MAP = 19         # file 18: `LoadX(block[0x12])` at `0x12FCA`
POD_WILDERNESS_X = 37        # file 36
POD_WILDERNESS_Y = 38        # file 37
POD_PARTY_COUNT = 32         # file 31: the save loop's bound, `es:[di + 0x1f]`
#: File 33.  Nonzero runs the dungeon; zero runs the wilderness.  Two sites
#: switch the interface mode on it alone -- `GAME.OVR:0x1522` and `0x6E1B`
#: both read `es:[di + 0x21]` and write mode 4 when it is set, 3 when it is
#: not -- and `GetVar` index 17 halves the facing only when it is set.
POD_IN_DUNGEON = 34
POD_WILDERNESS_REGION = 58   # file 57, indexed into a table at `DS:0x7D08`
#: The last variable the engine itself names.  `tools/dosptrfields.py` finds
#: displacements 0-58 and 195-197 off the block pointer and nothing else, so
#: variables 1-59 and 196-198 are the engine's and every other index is
#: whatever an `ECL1.DAX` script chooses to put there.
POD_ENGINE_VARS = 59

#: The twelve bytes of the Pools of Darkness square block, by file offset.
#: `shape.pos_x`/`pos_y`/`pos_facing` are the first three; these name the rest.
POD_PREVIOUS_MODE = 1029     # `DS:0x880D`, only ever assigned from `0x880C`
POD_MODE = 1030              # `DS:0x880C`: 3 wilderness, 4 dungeon, 2 in camp
POD_MAP = 1031               # `DS:0xA9F8`, a word; zeroed on leaving a dungeon
POD_MAP_BLOCK = 1033         # `DS:0xA9FA`, a word; the loader's second argument
POD_MODE_WILDERNESS, POD_MODE_DUNGEON = 3, 4


# ---------------------------------------------------------------------------
# The container, per title (#53)
# ---------------------------------------------------------------------------
#: One title's saved-game container, as a run of region widths (#53).
#:
#: `goldbox/dos_layout.py`'s `DosShape` is this table's sibling and the same
#: idea: a title is **a row of widths**, not a branch, and the widths have to
#: add up to the size the file actually is or the row raises at import.
#:
#: What all four share is a tail of `square_bytes` plus eight 41-byte name
#: slots -- 336 bytes where the square block is eight and 340 where it is
#: twelve, which is Pools of Darkness (#175).  Six of the eight slots are
#: filled and the last two hold the stack; this comment called those 82 bytes
#: "UI scratch" until `NAME_SLOTS` above was measured.  What the four titles
#: differ in is everything in front of that tail.
#:
#: Measured against **eleven containers** -- Donald's played Pool of Radiance
#: A/B/J out of the Steam `SavesDir`, the archives' own Pool of Radiance A/B,
#: Curse A/B, Silver Blades A/B and Pools of Darkness A/B -- deduplicated on
#: their bytes, because the archives ship most save directories twice and for
#: three of the four titles the copies are identical.
#: `tools/dossavgam.py` is what surveys them and `docs/141-dos-savegame.md`
#: is the prose.
@dataclasses.dataclass(frozen=True)
class DosSaveShape:
    """One title's `SAVGAM<slot>` file, as widths rather than offsets."""

    key: str
    title: str
    size: int
    #: `.DAT` for the first three; Pools of Darkness writes `.PTY` and keeps
    #: a 12-byte `VAULT<slot>.DAT` beside it, all zero in both specimens.
    suffix: str = ".DAT"
    #: One-byte ECL variables at file offset 0, variable *N* at offset *N*-1
    #: -- 1024 of them in Pools of Darkness, none anywhere else (#175).
    #: This is the *other* form of the variable array: the first three titles
    #: write 2560 `u16le` words at `var_offset`, and this one writes one byte
    #: per variable from the front of the file.
    var_bytes: int = 0
    #: Bytes before the header byte that nothing here has decoded.
    head: int = 0
    #: 1 where byte `head` is the area's `.DAX` container number, 0 where the
    #: file has no such byte.
    dax_bytes: int = 1
    #: `u16le` ECL variables from `var_base` up.
    var_words: int = VAR_WORDS
    #: **The address the title's own scripts call variable 0.** `$4900` in
    #: Pool of Radiance and `$4B00` in Curse of the Azure Bonds and Secret of
    #: the Silver Blades, whose whole save image is relocated by `$200`.
    #:
    #: CONFIRMED from the bytecode, both ports (`#192` step 0a): an address
    #: census over all 25 of Curse's `ECL` scripts finds 219 references into
    #: `$4B00`, 2053 into `$4C00`, 2 into `$4D00` and **none at all** into
    #: `$4900` or `$4A00`, and the C64 and DOS reference sets are identical
    #: because 21 of the 25 scripts are the same bytes on both ports.  The
    #: same routine appears in both titles' `DUNGEON` with every operand
    #: `$200` apart.
    #:
    #: **Nothing in this module takes an address in that space, and that is
    #: deliberate.** `word_offset` names its argument by Pool of Radiance's
    #: address for the same *word index*, which is what every measurement
    #: here was taken through and what every caller passes. A caller holding
    #: a Curse address converts with `pool_address` first; handing `$4C20` --
    #: a real Curse quest flag -- straight to `word_offset` is inside Pool of
    #: Radiance's guard and comes back as the word for index `$320`, which is
    #: a file offset 1024 bytes out and looks entirely plausible.
    var_base: int = VAR_BASE
    #: The staged `ECL<n>.DAX` script, or 0 where the title does not stage one.
    script_bytes: int = ECL_BUFFER[1] - ECL_BUFFER[0]
    #: Extra bytes Curse and Silver Blades write **inside** the square block,
    #: between its seventh byte and the party-size byte that ends it.  Zero in
    #: Pool of Radiance and in Pools of Darkness.
    #:
    #: Twelve bytes, and their *shape* is no longer unknown: the writer emits
    #: them as three passes of two `u16` each, `DS:0x722A + 4*i` and
    #: `DS:0x722C + 4*i` for `i` = 1, 2, 3 in Curse (`GAME.OVR:0x1F9D4`) and
    #: `DS:0x89D8`/`DS:0x89DA` in Silver Blades (`GAME.OVR:0x26BC7`).  So they
    #: are two three-element `u16` arrays interleaved, not twelve loose bytes
    #: (#253).
    #:
    #: **PROBABLE** that they are the wallset and wallmap triples Pool of
    #: Radiance keeps in the variable array at `WALLSET`/`WALLMAP`, which
    #: `$4AFA` and `$4AFD` hold at zero in all 121 Curse and Silver Blades
    #: containers here.  What fits: a shipped container reads
    #: `(0, $FFFF, $FFFF)` and `(1, $FFFF, $FFFF)`, which is
    #: `OUTDOOR_WALLSET` and this module's "`(1, $FFFF, $FFFF)` with one set
    #: loaded"; a played Curse one reads `(1, 2, 3)` and `(1, 2, 3)`, which is
    #: "`(1, 2, 3)` with three sets loaded"; Curse's initialiser at
    #: `GAME.OVR:0xF982` writes exactly the shipped pair.  What is missing:
    #: no site writes a real block id into either array -- the four indexed
    #: writers all store `$FFFF` -- so the value's source has not been read.
    #: Settling experiment: a `BPM` on `DS:0x722E` under DOSBox-X while the
    #: party enters an area with three wall sets, and see whether the writer
    #: is the same routine that fills `$4AFA` in Pool of Radiance.
    unnamed: int = 0
    #: The square block without `unnamed`: x, y, facing, engine state, and the
    #: party size as its last byte.  Eight bytes in the first three titles and
    #: **twelve** in Pools of Darkness, whose writer lays it out as five bytes
    #: from `DS:0xA9F3`, two interface-mode bytes, two words and the count
    #: (#175).
    square_bytes: int = 8

    def __post_init__(self) -> None:
        total = (self.var_bytes + self.head + self.dax_bytes
                 + 2 * self.var_words
                 + self.script_bytes + self.unnamed + self.square_bytes
                 + PARTY_ENTRIES * PARTY_ENTRY + UI_SCRATCH)
        if total != self.size:
            raise DosSaveError(
                f"{self.key}: the region widths add up to {total} bytes, not "
                f"the {self.size} the file is")

    @property
    def var_offset(self) -> "int | None":
        """File offset of the word for `$4900`, or None where there is none."""
        return (self.var_bytes + self.head + self.dax_bytes
                if self.var_words else None)

    @property
    def script_buffer(self) -> "tuple[int, int] | None":
        """Where the staged script sits, or None where none is staged."""
        if not self.script_bytes:
            return None
        start = self.var_bytes + self.head + self.dax_bytes + 2 * self.var_words
        return start, start + self.script_bytes

    @property
    def square(self) -> int:
        """The square block's first byte, which is x.

        Computed **forwards**, the way the writer emits the file: everything
        before it is the variable array and the staged script, so the block
        opens the moment those run out.  12801 in Pool of Radiance and in
        Curse alike, 5121 in Silver Blades, 1024 in Pools of Darkness.

        It was computed backwards from the party table until #253, which put
        Curse's and Silver Blades' twelve extra bytes in front of the block
        rather than inside it and so read x twelve bytes late.  Both
        arithmetics give the same answer wherever `unnamed` is 0, which is
        why Pool of Radiance never noticed and why the widths still tiled the
        file.
        """
        return (self.var_bytes + self.head + self.dax_bytes
                + 2 * self.var_words + self.script_bytes)

    @property
    def pos_x(self) -> int:
        """The square block's first byte, named rather than left for a
        caller to add to `square` by hand.

        **The same distance into every title's file**: the first byte after
        the variable array and the staged script.  Read out of each engine's
        own save routine -- the chain of `BlockWrite` calls that emits the
        file in order -- so it is the writer's arithmetic rather than an
        inference from a specimen (#253):

        =====================  ===========  ==========================
        title                  `GAME.OVR`   x is written from
        =====================  ===========  ==========================
        Pool of Radiance       `0x1FF85`    `DS:0x6AAD`, 5 bytes
        Curse of the Azure     `0x1F98B`    `DS:0x7229`, 5 bytes
        Bonds
        Secret of the Silver   `0x26B7E`    `DS:0x89D7`, 5 bytes
        Blades
        =====================  ===========  ==========================

        In all three that call lands at the same file offset the shape gives,
        and Pools of Darkness' own writer was read the same way for #175.

        A writer that hardcodes Pool of Radiance's `POS_X`, `POS_Y` and
        `POS_FACING` for another title's shape still wants
        `pos_x`/`pos_y`/`pos_facing` instead: the constants happen to agree
        for Curse and Silver Blades and do not for Pools of Darkness, whose
        square is at 1024.
        """
        return self.square

    @property
    def pos_y(self) -> int:
        return self.square + 1

    @property
    def pos_facing(self) -> int:
        return self.square + 2

    @property
    def party_table(self) -> int:
        return self.square + self.unnamed + self.square_bytes


#: Pool of Radiance, 13137 bytes.  Every offset above is this row's.
SAVE_POOL_OF_RADIANCE = DosSaveShape(
    key="pool-of-radiance", title="Pool of Radiance", size=13137)

#: Curse of the Azure Bonds, 13149.  **The same file as Pool of Radiance's
#: with twelve more bytes inside the square block**, and the variable array
#: is at the same offset holding the same ECL addresses: `$5012` equals the
#: header byte (2 and 2), `$503E` is the party size (6 and 6) and `$49E6` is
#: the indoors flag (1 and 1) in both specimens.
#:
#: Its save routine writes the file in this order, from the `BlockWrite`
#: chain at `GAME.OVR:0x1F909`-`0x1FAFC` (#253):
#:
#: =============  =====  ===========================================
#: file offset    bytes  source
#: =============  =====  ===========================================
#: 0                  1  `DS:0x5C08`, the `.DAX` container number
#: 1               5120  the variable array, as 2048 + 2048 + 1024
#: 5121            7680  the staged script
#: 12801              5  `DS:0x7229` -- x, y, facing, and two more
#: 12806              1  `DS:0x4FD4`
#: 12807              1  `DS:0x4FD3`
#: 12808             12  the two `u16[1..3]` arrays above
#: 12820              1  the party size
#: 12821            328  eight 41-byte character slots
#: =============  =====  ===========================================
SAVE_CURSE_OF_THE_AZURE_BONDS = DosSaveShape(
    key="curse-of-the-azure-bonds", title="Curse of the Azure Bonds",
    size=13149, unnamed=12, var_base=0x4B00)

#: Secret of the Silver Blades, 5469 -- and the reason it is less than half
#: the size is that **it stages no script**.  Its variable array is Pool of
#: Radiance's, at the same offset with the same three addresses reading the
#: same way; what is missing is the 7680-byte ECL text buffer.  Silver
#: Blades' own scripts are no smaller -- its largest `ECL<n>.DAX` block is
#: 7678 bytes against Pool of Radiance's 7679 -- so the engine reloads them
#: from the container rather than carrying them in the save.
#:
#: Its `BlockWrite` chain is Curse's with that one region taken out, at
#: `GAME.OVR:0x26B15`-`0x26D10`: 1 byte from `DS:0x7420`, then 5120 bytes of
#: variable array, then **5 bytes from `DS:0x89D7` at file offset 5121** --
#: x, y and the doubled facing -- then `DS:0x67E8`, `DS:0x67E7`, the twelve
#: bytes of `unnamed` from `DS:0x89D8`/`DS:0x89DA`, the party size at 5140
#: and 328 bytes of character slots at 5141 (#253).
SAVE_SECRET_OF_THE_SILVER_BLADES = DosSaveShape(
    key="secret-of-the-silver-blades", title="Secret of the Silver Blades",
    size=5469, script_bytes=0, unnamed=12, var_base=0x4B00)

#: Pools of Darkness, 1364 bytes of `SAVGAM<slot>.PTY` and a 12-byte
#: `VAULT<slot>.DAT` that is all zero in both specimens.
#:
#: **The 1024 bytes at the front are the ECL variable array, one byte per
#: variable, variable *N* at file offset *N*-1** (#175).  Not the 2560
#: `u16le` words the first three titles write -- which is why nothing here
#: could find `$5012` or `$503E` under any origin: the array is byte wide and
#: based at 0 rather than at an ECL address.  `var_bytes` rather than
#: `var_words`, and `pod_var` rather than `word`.
#:
#: Read out of the writer, not out of a save: `GAME.OVR` file offset `0x134BA`
#: is `BlockWrite(f, [DS:0x87F8]^, 0x400)`, and `GAME.OVR:0x1A275` is the one
#: `GetMem(0x400)` that fills that pointer, so the region is one allocation
#: written whole.  The five `BlockWrite`s that follow it name the twelve bytes
#: of the square block, and the loop at `0x13595` names the party table.
#:
#: **Its square block is twelve bytes, not eight**, and the four this row
#: called `unnamed` until #175 were its last four: `DS:0xA9F3`-`0xA9F7` (x, y,
#: facing and two engine bytes), then `DS:0x880D` and `DS:0x880C` (the
#: previous and current interface modes), then two words `DS:0xA9F8` and
#: `DS:0xA9FA` the dungeon loader passes to `LoadMap`, then the count of
#: character files.
SAVE_POOLS_OF_DARKNESS = DosSaveShape(
    key="pools-of-darkness", title="Pools of Darkness", size=1364,
    suffix=".PTY", var_bytes=POD_VAR_COUNT, dax_bytes=0, var_words=0,
    script_bytes=0, square_bytes=12)

SAVE_SHAPES: "tuple[DosSaveShape, ...]" = (
    SAVE_POOL_OF_RADIANCE, SAVE_CURSE_OF_THE_AZURE_BONDS,
    SAVE_SECRET_OF_THE_SILVER_BLADES, SAVE_POOLS_OF_DARKNESS)
SAVE_SHAPES_BY_KEY = {s.key: s for s in SAVE_SHAPES}
SAVE_SHAPES_BY_SIZE = {s.size: s for s in SAVE_SHAPES}


def save_shape_for(what: "int | str | DosSaveShape") -> DosSaveShape:
    """The container shape for a size, a title key, or a shape.

    **The size names the shape, not the title.**  Treasures of the Savage
    Frontier writes a 1364-byte `SAVGAM<slot>.PTY` and a 12-byte
    `VAULT<slot>.DAT` beside it, exactly as Pools of Darkness does, and its
    two shipped containers carry the same tail -- six `CHRDAT` entries 41
    bytes apart, a party size of 6, 82 bytes of UI scratch.  So a 1364-byte
    file is answered with the Pools of Darkness row and a caller that needs
    to know *which game* has to look at where the file came from (#53).
    """
    if isinstance(what, DosSaveShape):
        return what
    if isinstance(what, int):
        try:
            return SAVE_SHAPES_BY_SIZE[what]
        except KeyError:
            raise DosSaveError(
                f"{what} bytes is no DOS Gold Box saved game; the four this "
                f"project reads are "
                f"{', '.join(str(n) for n in sorted(SAVE_SHAPES_BY_SIZE))}"
            ) from None
    try:
        return SAVE_SHAPES_BY_KEY[what]
    except KeyError:
        raise DosSaveError(f"no DOS title keyed {what!r}") from None


# -- the named VM variables --------------------------------------------------
TRAVEL_X = 0x49C3            # the overland square, window-local, live only
TRAVEL_Y = 0x49C4            # outdoors -- see `travel_square`
AREA = 0x49C5                # the resident GEO block, **not the area** -- the
                             # two numbers coincide only for an area that
                             # loads its own map.  `LOADFILES`' first operand
                             # lands here, unless it is $FF or $7F, and the
                             # only reader hands it to the GEO loader
                             # (GAME.OVR:0x1A09 and 0x1FBBE; the C64's $2041,
                             # `docs/118-debug-mode.md`).  0 in all three
                             # outdoor saves, not the C64's SQRDATA number
                             # (#59, outdoor pass), and 0 in a hall, whose
                             # script loads no map at all (#257).  The name
                             # is the one twenty call sites already use;
                             # `geo_block` is what it should have been
EMPTY = 0xFFFF               # an empty word slot, the wallset triple's $FF
CLOCK_DIGITS = 6
CLOCK = 0x49C6               # six digit words, exactly the C64's six bytes:
                             # sub-minute, minute units, minute tens, hour,
                             # day, month (limits 10 10 6 24 30 12)
INDOORS = 0x49E6             # 1 in the three indoor specimens, 0 in the three
                             # outdoor ones; written 0->1 by the boat-back
                             # transition, writer 30F6:0CA1 (#59 run2)
SCRIPT = 0x49F2              # the area the party is in, indoors or out --
                             # `NEWECL`'s handler writes it and the startup
                             # path reads it straight back into the engine's
                             # current-area global (GAME.OVR:0x192F and
                             # 0x4067-0x4070), which is then what the travel
                             # -mode test compares against 25, 26 and 27
FLAGS_FIRST, FLAGS_LAST = 0x4A20, 0x4AF8    # quest flags, shared ECL addresses
WALLSET = 0x4AFA             # three words: WALLDEF/8X8D block ids, $FFFF empty
WALLMAP = 0x4AFD             # three words: (1,2,3) with three sets loaded,
                             # (1,$FFFF,$FFFF) with one
#: The wallset triple an **outdoor** save carries, and it is the engine's own
#: value rather than one inherited from wherever the party left the grid.
#:
#: Six engine-written overland specimens hold it: `work/p50-outdoor` and #59's
#: three of 2026-08, all of which departed New Phlan, which holds the same
#: three words -- and the three of `work/p59-wallset/keep`, which departed
#: **Sokol Keep's `(1, 5, 9)`** with that triple deliberately left in the
#: seed.  The engine replaced a triple it had never held, three times of
#: three, so live and stale are separated (#59, #190).
#:
#: **Nothing outdoors reads it.**  The seed carrying `(1, 5, 9)` on a travel
#: window loaded and drew, where indoors a wrong triple kills the load in
#: `LoadWallSet`.  So this is what an outdoor conversion writes because it is
#: what was measured, not because the load depends on it.
OUTDOOR_WALLSET = (0, EMPTY, EMPTY)

PARTY_SIZE = 0x503E          # 6 -> 1 when a six-member save became one member
DISK = 0x5012                # the DAX container number again, as a VM word;
                             # the geo load fails without it
ENCOUNTER_TEXT = 0x5227      # string buffer, one ASCII character per word
VM_SCRATCH = 0x5200          # byte 12805 is this word's low byte
# The shared, cross-port ECL variable space ends here. No ECL script in the
# thirty-script corpus references an address at or above $4AF9 (2544 distinct
# bracketed addresses), and on the C64 $4D00 upwards is the twelve character
# slots -- so nothing the DOS save holds above this can be sourced from a C64
# save, however tempting the address looks (#59).
ECL_SHARED_LAST = FLAGS_LAST
VAR_LAST = VAR_BASE + VAR_WORDS - 1          # $52FF

#: Words that hold the same value in every genuine specimen, as
#: `(address, value, why)`.  A conversion writes these rather than inheriting
#: them: the value is the same wherever it was measured, so it is a fact about
#: the file and not about the party the template belonged to.
#:
#: Measured over the four engine-written Pool of Radiance containers still on
#: this machine -- Donald's played A, B and J, and the archives' own
#: `Default files/Saves/SAVGAMA.DAT` -- and reported the same over twelve in
#: #59, eight of which lived under `work/` and are gone.  None of the three
#: has a name; what is known is that the value does not move.
SAVGAM_CONSTANTS: tuple[tuple[int, int, str], ...] = (
    (0x4FE1, 255, "255 in every specimen"),
    (0x506D, 16, "16 in every specimen"),
    (0x50F6, 1, "1 in every specimen"),
)


def pool_address(address: int, shape: "DosSaveShape | None" = None) -> int:
    """A title's own ECL address, as the Pool of Radiance address for the
    same word of the variable array.

    `$4C20` is a Curse of the Azure Bonds quest flag and `$4A20` is Pool of
    Radiance's; they are the **same word index**, `$120`, at the same file
    offset, because the whole save image moved by `$200` between the two
    titles and the array did not change shape (`DosSaveShape.var_base`).

    This exists because `word_offset` cannot tell the two apart: `$4C20` is
    inside Pool of Radiance's `$4900`-`$52FF` guard, so passing it raises
    nothing and returns the word for index `$320` -- a file offset 1024 bytes
    out, and every value read through it plausible and wrong.  A caller that
    has a Curse or Silver Blades address in hand converts here first.
    """
    shape = shape or SAVE_POOL_OF_RADIANCE
    return address - shape.var_base + VAR_BASE


def word_offset(address: int, shape: "DosSaveShape | None" = None) -> int:
    """File offset of the VM word for an ECL address.

    **The address is Pool of Radiance's**, whatever title the shape is, and
    what it really names is a *word index* into the array: `$4900` is index 0
    in every title that has one, because Curse and Silver Blades relocate the
    whole save image by `$200` without changing the array.  Their scripts
    call the same word `$4B00`, and `pool_address` is what converts.  This
    function does not, and cannot: a Curse address lands inside the guard
    below and comes back as a plausible offset 1024 bytes from the one the
    caller meant (`#192`).

    Pools of Darkness has no array here at all and raises.
    """
    shape = shape or SAVE_POOL_OF_RADIANCE
    if not shape.var_words:
        raise DosSaveError(
            f"a {shape.title} saved game holds no ECL variable array")
    if not VAR_BASE <= address < VAR_BASE + shape.var_words:
        raise DosSaveError(f"${address:04X} is outside the variable space")
    return shape.var_offset + 2 * (address - VAR_BASE)


def _shaped(save: bytes, shape: "DosSaveShape | None" = None) -> DosSaveShape:
    """The title this buffer is, refusing one that is no title's size.

    Every accessor here reads an offset a shape computes, so a buffer of the
    wrong length would read somebody else's region and hand back a plausible
    number.  Four sizes, four shapes -- 13137, 13149, 5469, 1364 -- and see
    `save_shape_for` for why that is a shape rather than a title.
    """
    if shape is None:
        return save_shape_for(len(save))
    shape = save_shape_for(shape)
    if len(save) != shape.size:
        raise DosSaveError(
            f"a {shape.title} saved game is {shape.size} bytes; this is "
            f"{len(save)}")
    return shape


def _whole(save: bytes) -> bytes:
    """Refuse a buffer that is not a Pool of Radiance saved game.

    The writers below encode the Pool of Radiance conversion and its offsets;
    reading is shape-aware and reading is what the other three titles get.
    """
    _shaped(save, SAVE_POOL_OF_RADIANCE)
    return save


def word(save: bytes, address: int,
         shape: "DosSaveShape | None" = None) -> int:
    shape = _shaped(save, shape)
    return struct.unpack_from("<H", save, word_offset(address, shape))[0]


# --- Pools of Darkness: the byte-wide array ---------------------------------
def pod_var_offset(index: int, shape: "DosSaveShape | None" = None) -> int:
    """File offset of the byte holding ECL variable `index`.

    `index - 1`, and the subtraction is the whole finding: `GetVar` and
    `SetVar` decrement the index and add it to the block base (#175).  A shape
    with no byte array raises rather than answering, because offset `index -
    1` in a Pool of Radiance save is a word of somebody else's variable.
    """
    shape = shape or SAVE_POOLS_OF_DARKNESS
    if not shape.var_bytes:
        raise DosSaveError(
            f"a {shape.title} saved game holds no byte-wide variable array")
    if not POD_VAR_FIRST <= index < POD_VAR_FIRST + shape.var_bytes:
        raise DosSaveError(
            f"variable {index} is outside the {shape.var_bytes} this title "
            f"has")
    return index - POD_VAR_FIRST


def pod_var(save: bytes, index: int,
            shape: "DosSaveShape | None" = None) -> int:
    """One ECL variable, as the engine's own 1-based index."""
    shape = _shaped(save, shape)
    return save[pod_var_offset(index, shape)]


def put_pod_var(save: bytearray, index: int, value: int,
                shape: "DosSaveShape | None" = None) -> None:
    """Write one ECL variable.  One byte: `SetVar`'s word form writes the
    variable and the one after it, so a caller wanting a word writes both."""
    shape = _shaped(save, shape)
    save[pod_var_offset(index, shape)] = value & 0xFF


def pod_in_dungeon(save: bytes, shape: "DosSaveShape | None" = None) -> bool:
    """Is the party in a dungeon rather than the wilderness?

    Variable 34, file offset 33.  The counterpart of `outdoors` for a title
    that has no `$49E6`, and read the same way round as the engine reads it:
    two sites switch the interface mode on this byte and nothing else.
    """
    return pod_var(save, POD_IN_DUNGEON, shape) != 0


def pod_clock(save: bytes, shape: "DosSaveShape | None" = None
              ) -> "tuple[int, int, int, int, int]":
    """(hour, minute, day, month, year) from the seven digits at 4-10.

    Minutes are two digits at file 5 and 6, tens above units, exactly as Pool
    of Radiance encodes them; `clock` above is the same arithmetic over words.
    The sub-minute digit at file 4 is dropped, as it is there.
    """
    d = [pod_var(save, POD_CLOCK + i, shape) for i in range(POD_CLOCK_DIGITS)]
    return d[3], d[2] * 10 + d[1], d[4], d[5], d[6]


def dax_number(save: bytes, shape: "DosSaveShape | None" = None) -> int:
    """Which GEO/ECL/WALLDEF/8X8D container holds the current area."""
    shape = _shaped(save, shape)
    if not shape.dax_bytes:
        raise DosSaveError(
            f"a {shape.title} saved game has no container-number byte")
    return save[shape.head]


def geo_block(save: bytes) -> int:
    """Which `GEO` was resident when the save was written.  **Not the area.**

    `$49C5`, and the only thing that reads it is the `GEO` loader.  The number
    equals the area id for an area that loads its own map, which is most of
    them, and that coincidence is what `area_id` was named for.

    Two kinds of place break it, and both read 0 here:

    * **the overland**, where no `GEO` is loaded at all -- 10 of 10 outdoor
      specimens (#59);
    * **an area whose script loads no map**, which in Pool of Radiance is
      the training hall (11) and Phlan City Hall (8).  `tools/loadfiles.py`
      finds no `LOADFILES` anywhere in `ECL0B`, so the hall runs on New
      Phlan's `GEO00` and leaves `$49C5` at 0 while `$49F2` says 11 (#257).
    """
    return word(save, AREA)


#: The old name for `geo_block`, kept because twenty call sites use it.  It
#: never meant the area: see `geo_block` and `AREA` above.
area_id = geo_block


def current_area(save: bytes) -> int:
    """The area the party is in, indoors or out.  `$49F2`, always.

    CONFIRMED from the engine's own code, on both ports.  `NEWECL`'s handler
    writes the departing area here and then sets the current-area global to
    its operand (`GAME.OVR:0x192F`, the C64's `$2011`-`$2016`), and the
    area-startup path reads the word straight back into that global
    (`GAME.OVR:0x4067`-`0x4070`) before comparing it against 25, 26 and 27 to
    choose travel mode.  Nothing anywhere loads `$49C5` into it.

    This read `$49C5` indoors until #257, on the belief that the two words
    always agree there.  They do not: `WISH-SPEC-por-party-trained-c2` and
    `WISH-SPEC-por-train-clamp` were saved in the training hall and hold
    `$49C5` = 0 with `$49F2` = 11, and their ECL text buffer is `ECL3.DAX`
    block 11 byte for byte, so 11 is where the party is.  Reading `$49C5`
    there named New Phlan.
    """
    return word(save, SCRIPT)


def clock(save: bytes) -> tuple[int, int, int, int]:
    """(hour, minute, day, month) -- the C64's digit encoding, as words."""
    d = [word(save, CLOCK + i) for i in range(6)]
    return d[3], d[2] * 10 + d[1], d[4], d[5]


def party_size(save: bytes, shape: "DosSaveShape | None" = None) -> int:
    """The party-size byte, the last of the square block.

    Reads 6 in all nine shipped containers of all four titles, which is what
    says the block sits in the same place in each.
    """
    shape = _shaped(save, shape)
    return save[shape.party_table - 1]


def position(save: bytes, shape: "DosSaveShape | None" = None
             ) -> tuple[int, int, int]:
    """(x, y, facing) with facing in the C64's units, 0 N 1 E 2 S 3 W.

    Indoors only for x and y: an outdoor save freezes 12801/12802 at the last
    indoor square (the pier, in all three specimens) while the facing byte
    stays live -- read `travel_square` when `outdoors(save)`.  The mirror of
    the C64, whose stale copy outdoors is `$49C0`-`$49C2` (#47, #59).

    The shipped Curse and Silver Blades containers hold (7, 13, 0), which is
    the square Curse's own initialiser leaves (`GAME.OVR:0xF95E` writes 7, 13
    and 0 into `DS:0x7229`-`DS:0x722B`).  They read `$FF` in all three until
    #253, which was this reader looking twelve bytes past the square, at the
    `unnamed` arrays' empty marker.

    **Pools of Darkness reads correctly here** as of #175, and did not before:
    its square is at 1024-1026 rather than the 1028-1030 the old `unnamed=4`
    row put it at.  Eight engine-written containers agree with the game's own
    status line -- `11,2 S 00:04` against (11, 2, 2) and `8,2 W 00:07` against
    (8, 2, 3) -- and a single right turn moved byte 1026 from 4 to 6 and
    nothing else in the file's first 1036 bytes.
    """
    shape = _shaped(save, shape)
    return (save[shape.pos_x], save[shape.pos_y],
            save[shape.pos_facing] // FACING_SCALE)


def outdoors(save: bytes) -> bool:
    """Was this save made on the overland travel map?  `$49E6` = 0 there.

    CONFIRMED three specimens each way (#59): 1 in A/B/J indoors, 0 in the
    three overland saves, and the boat-back transition was caught writing it
    0 -> 1 live.
    """
    return word(save, INDOORS) == 0


#: What the status line adds to the window-local x to print a world
#: coordinate, per outdoor area.  Window 26 measured on-screen -- world
#: `20,29` against `$49C3`/`$49C4` = (7,29), three of three (#59); 25 and 27
#: are the C64 seam arithmetic (write-up lost, `work/reports/world-map.md` §3:
#: window 25's x+13 is window 26's x, and 26's x+13 is 27's), PROBABLE for the DOS
#: display.  y is world y in every window.
WINDOW_X_OFFSET = {25: 0, 26: 13, 27: 26}


def travel_square(save: bytes) -> tuple[int, int]:
    """The overland square, window-local, from `$49C3`/`$49C4`.

    CONFIRMED (#59): three engine-written overland saves read (7,29), (7,28),
    (8,28) against on-screen `20,29`/`20,28`/`21,28` -- world x = local x +
    `WINDOW_X_OFFSET[area]` -- and a live watch caught one east step writing
    `$49C3` 7 -> 8.  Meaningful only when `outdoors(save)`; indoor saves hold
    zeros (A/B/J) or the stale square the party left the grid on.
    """
    return word(save, TRAVEL_X), word(save, TRAVEL_Y)


def wall_triple(save: bytes) -> tuple[int, int, int]:
    """The up-to-three wallset block ids, $FFFF = empty.

    Byte-identical to the C64 loaded-files cache slots 15-17 for the same
    area (PORSAVE13's Slums triple 2,4,1 == slot J's, PORSAVE's Sokol Keep
    1,5,9 == slot B's), so a converter can source it from the C64 save.  New
    Phlan is the exception: the C64 loads no `WALLSET` there and DOS's own
    save names one, and an all-empty triple draws it identically anyway.
    """
    return tuple(word(save, WALLSET + i) for i in range(3))


def put_character_files(save: bytearray, slot: str) -> None:
    """Name the files the engine will load the party from.

    The engine loads the party from these names and not from the slot letter
    chosen at the LOAD menu -- slot J's file staged as slot C loaded J's
    characters (#59) -- so a save that does not name its own files loads
    somebody else's party.  The engine's own resave rewrites the letters; so
    does this.  All six entries are written, not `count` of them: no specimen
    shows what a blanked entry does, and the party size says how many are
    read.
    """
    _whole(save)
    for n in range(PARTY_ENTRIES):
        at = PARTY_TABLE + n * PARTY_ENTRY
        name = f"CHRDAT{slot.upper()}{n + 1}".encode("ascii")
        save[at] = len(name)
        save[at + 1:at + 1 + len(name)] = name


def character_files(save: bytes,
                    shape: "DosSaveShape | None" = None) -> list[str]:
    """The CHRDAT filenames the engine will load the party from.

    Six of six in all nine shipped containers of all four titles, which is
    the anchor the per-title region map was measured from.
    """
    shape = _shaped(save, shape)
    out = []
    for n in range(PARTY_ENTRIES):
        at = shape.party_table + n * PARTY_ENTRY
        length = save[at]
        # An entry is one length byte, the name, then 32 bytes of heap
        # scratch, so a real name cannot exceed eight -- which is exactly
        # `CHRDATA1`. A looser bound reads the scratch as filename characters
        # and returns a wrong-but-plausible name instead of nothing.
        if 0 < length < PARTY_NAME_LEN:
            out.append(save[at + 1:at + 1 + length].decode("ascii", "replace"))
    return out


def encounter_text(save: bytes, limit: int = 96) -> str:
    """The encounter-message scratch, one character per word."""
    chars = []
    for i in range(limit):
        v = word(save, ENCOUNTER_TEXT + i)
        chars.append(chr(v) if 32 <= v < 127 else " ")
    return "".join(chars).strip()


# ---------------------------------------------------------------------------
# The `.DAX` container
# ---------------------------------------------------------------------------
#: A `.DAX` is a `u16le` index size, `size // 9` entries of
#: `id:u8, offset:u32le, raw:u16le, compressed:u16le`, then the block data with
#: each entry's offset relative to its start.  Blocks are byte run-length
#: coded: a lead byte under 128 copies the next `n + 1` bytes, one at or above
#: it repeats the next byte `256 - n` times.
#:
#: **One copy, here** (#76).  `tools/dosbox.py` carried a second and re-exports
#: this one; a retarget needs one ECL block out of the player's own archive and
#: `goldbox/` may not import from `tools/`, so the shared copy has to be this side
#: of the edge.
#:
#: This is *not* the Amiga container.  That one is big-endian, orders the entry
#: `id:u16 offset:u32 compressed:u16 raw:u16`, and is bit-packed rather than
#: run-length coded; `docs/117-save-conversion.md`'s "all 843 blocks of all 23
#: `.dax` files" is a statement about that format and `work/amiga/dax.py`, and
#: says nothing about this one (#65).
DAX_ENTRY = 9


def dax_index(data: bytes, name: str = "dax") -> list[tuple[int, int, int, int]]:
    """`(id, offset, raw size, compressed size)` for each block of a `.DAX`.

    A file too short for the index it declares is named as such rather than
    raising `struct.error` from inside a comprehension: the caller here is a
    conversion reading the player's own game directory, and "this file is not
    a .DAX" is the answer it has to be able to report.
    """
    try:
        size = struct.unpack_from("<H", data, 0)[0]
        return [struct.unpack_from("<BIHH", data, 2 + DAX_ENTRY * i)
                for i in range(size // DAX_ENTRY)]
    except struct.error as e:
        raise DaxError(f"{name}: not a .DAX: {e}") from e


def dax_unpack(block: bytes, raw_size: int, name: str = "block") -> bytes:
    """Decompress one `.DAX` block, or raise `DaxError` saying which.

    All three refusals mean the same thing -- a length that is not this
    block's -- and all three used to be silent (#65).  A run whose operand is
    past the end of the block raised `IndexError` from the subscript, and a
    block that ran out before `raw_size` returned a plausible prefix and left
    the caller to notice.  `goldbox.dos.write_dos_save` catches `DosSaveError` and
    keeps the template's square; an `IndexError` took the whole conversion down
    with a traceback instead.
    """
    out = bytearray()
    i = 0
    while i < len(block) and len(out) < raw_size:
        n = block[i]
        if n < 128:
            run = block[i + 1:i + 2 + n]
            if len(run) != n + 1:
                raise DaxError(
                    f"{name}: copy of {n + 1} bytes at {i} runs "
                    f"{n + 1 - len(run)} past the end of a {len(block)}-byte "
                    f"block")
            out += run
            i += n + 2
        else:
            if i + 1 >= len(block):
                raise DaxError(
                    f"{name}: repeat opcode at {i} is the last byte of a "
                    f"{len(block)}-byte block, so its operand is missing")
            out += bytes([block[i + 1]]) * (256 - n)
            i += 2
    if len(out) != raw_size:
        raise DaxError(
            f"{name}: unpacked to {len(out)} bytes, not the {raw_size} the "
            f"index states")
    return bytes(out)


def _dax_chunk(data: bytes, base: int, off: int, comp: int, name: str) -> bytes:
    """The stored bytes of one block, or a refusal naming what is short."""
    chunk = data[base + off:base + off + comp]
    if len(chunk) != comp:
        raise DaxError(
            f"{name}: the index states {comp} bytes at {base + off} but the "
            f"file holds {len(chunk)}")
    return chunk


def dax_blocks(data: bytes, name: str = "dax"):
    """Yield `(id, decompressed bytes)` for every block of a `.DAX`."""
    index = dax_index(data, name)
    base = 2 + struct.unpack_from("<H", data, 0)[0]
    for bid, off, raw, comp in index:
        chunk = _dax_chunk(data, base, off, comp, f"{name} block {bid}")
        yield bid, dax_unpack(chunk, raw, f"{name} block {bid}")


def dax_block(data: bytes, block_id: int, name: str = "dax") -> bytes:
    """One block of a `.DAX`, decompressed.  Raises if it is not there."""
    index = dax_index(data, name)
    base = 2 + struct.unpack_from("<H", data, 0)[0]
    for bid, off, raw, comp in index:
        if bid != block_id:
            continue
        where = f"{name} block {block_id}"
        return dax_unpack(_dax_chunk(data, base, off, comp, where), raw, where)
    raise DaxError(f"{name}: no block {block_id} in this .DAX")


# ---------------------------------------------------------------------------
# Writing: the retarget, and the two fields a conversion carries
# ---------------------------------------------------------------------------
def put_word(save: bytearray, address: int, value: int) -> None:
    _whole(save)
    struct.pack_into("<H", save, word_offset(address), value & 0xFFFF)


def put_position(save: bytearray, x: int, y: int, facing: int,
                 shape: "DosSaveShape | None" = None) -> None:
    """The square, with `facing` in the C64's 0-3.

    Writes through `shape.pos_x`/`pos_y`/`pos_facing`, not the Pool of
    Radiance constants of the same shape -- those are 12801-12803, which is
    Silver Blades' script buffer and is inside Pools of Darkness' variable
    array. `shape` defaults to whichever the buffer's own length names, so an
    existing Pool of Radiance caller is unaffected.

    **This is the one writer here that takes a title other than Pool of
    Radiance, and that is deliberate rather than an oversight.** Every other
    one opens with `_whole`, which refuses anything but a 13137-byte buffer;
    this one opens with `_shaped`, which takes any of the four known sizes.
    It is groundwork for #192, and the rest of the module follows when that
    lands. Until then a caller writing a whole Curse save gets this call and
    a `DosSaveError` from the next one, which is loud rather than silent.
    """
    shape = _shaped(save, shape)
    save[shape.pos_x], save[shape.pos_y] = x, y
    save[shape.pos_facing] = facing * FACING_SCALE


def put_tail_state(save: bytearray, *, indoors: bool = True) -> None:
    """Bytes 12804-12807, from measurement rather than from the template.

    `indoors` sets **two** of them, not one: the view-mode byte, which is a
    function of `$49E6` in 12 of 12 specimens, and the scratch byte at 12804,
    which is not.  12804 reads 0 in eight of the nine indoor specimens and 14
    in the ninth and in all three outdoor ones, so 0 and 14 are the values an
    engine-written save of a party standing in each place has held -- and
    that is all they are.  The engine maintains the byte itself: it replaced
    a written 0 with 9 in #59's run 9 and with 14 in #26's, the second of
    those standing **indoors**, which is what refuted reading it as an
    indoors flag.

    `TAIL_CONSTANT_BYTE` is 2 in all twelve genuine specimens regardless.
    `VM_COPY_BYTE` is written from `$5200` as it stands in this save, which is
    the relationship 13 of 13 files show.
    """
    _whole(save)
    save[SCRATCH_BYTE] = SCRATCH_INDOORS if indoors else SCRATCH_OUTDOORS
    save[VM_COPY_BYTE] = word(bytes(save), VM_SCRATCH) & 0xFF
    save[VIEW_MODE_BYTE] = VIEW_MODE_INDOORS if indoors else VIEW_MODE_OUTDOORS
    save[TAIL_CONSTANT_BYTE] = TAIL_CONSTANT


def put_travel_square(save: bytearray, x: int, y: int) -> None:
    """The overland square, window-local, into `$49C3`/`$49C4`.

    The facing byte still matters out there: the engine keeps 12803 live
    (doubled, as indoors) while 12801/12802 go stale, so a writer placing a
    party outdoors sets this *and* `put_position`'s facing.
    """
    _whole(save)
    put_word(save, TRAVEL_X, x)
    put_word(save, TRAVEL_Y, y)


def put_clock(save: bytearray, digits) -> None:
    """The six digit words, in the C64's own order and encoding."""
    _whole(save)
    digits = list(digits)
    if len(digits) != CLOCK_DIGITS:
        raise DosSaveError(f"the clock is {CLOCK_DIGITS} digits, not "
                           f"{len(digits)}")
    for i, d in enumerate(digits):
        put_word(save, CLOCK + i, d)


def put_party_size(save: bytearray, count: int) -> None:
    """Both copies, which move together."""
    _whole(save)
    put_word(save, PARTY_SIZE, count)
    save[PARTY_SIZE_BYTE] = count


def wall_map(wallset) -> tuple[int, int, int]:
    """The index map that goes with a triple: 1,2,3 for the slots it fills."""
    return tuple(EMPTY if w == EMPTY else i + 1 for i, w in enumerate(wallset))


def retarget(save: bytearray, *, area: int, dax: int, wallset, script: bytes,
             outdoors: bool = False) -> None:
    """Move a saved game to another area.  `script` is its `ECL` DAX block.

    Every write `RETARGET_WRITES` lists except the square and the party
    size, which a conversion sets separately because they change on their
    own.  Take any of these away and the game exits to DOS.

    **`outdoors` changes one of the nine writes, `$49C5`.**  A travel window
    is an area like any other everywhere else -- byte 0 and `$5012` are its
    DAX number, `$49F2` is its id, the ECL buffer is its own block -- but
    `$49C5` is **0** rather than the id, in 10 of 10 outdoor specimens, and
    that is the field that says the overland names no `GEO`.  The C64 is not
    the same here: its `$49C5` outdoors holds the `SQRDATA` number.
    """
    _whole(save)
    save[0] = dax
    put_word(save, AREA, 0 if outdoors else area)
    put_word(save, SCRIPT, area)
    put_word(save, DISK, dax)
    for i, w in enumerate(wallset):
        put_word(save, WALLSET + i, w)
    for i, w in enumerate(wall_map(wallset)):
        put_word(save, WALLMAP + i, w)
    body = script[ECL_HEADER:]
    start, end = ECL_BUFFER
    if len(body) > end - start:
        raise DosSaveError(f"area {area}'s script is {len(body)} bytes and the "
                           f"buffer holds {end - start}")
    save[start:start + len(body)] = body


#: What a retarget must write.  Established by bisection -- `work/p59` runs
#: 2-9 for the variables, `work/p60/run2` for the script buffer.  The naive
#: recipe (header + $49C5 + $49F2 + square) dies with "Unable to load geo in
#: Load3DMap."; so does the seven-write recipe that leaves the template's
#: script staged.
#:
#: CONFIRMED for three area pairs: 0 -> 20 (#59 run 9), 21 -> 20 and 20 -> 0
#: (`work/p60/run2`, X2 and X3), each loaded and walked.  The addresses are
#: formatted from the constants above so the recipe cannot drift from the map
#: it is a recipe for.
RETARGET_WRITES = (
    "byte 0 = the target area's DAX number",
    f"word ${AREA:04X} = the target area id, or 0 onto a travel window",
    f"word ${SCRIPT:04X} = the target area id",
    f"word ${DISK:04X} = the target area's DAX number",
    f"words ${WALLSET:04X}-${WALLSET + 2:04X} = the target's wallset triple "
    f"($FFFF = empty slot)",
    f"words ${WALLMAP:04X}-${WALLMAP + 2:04X} = (1,2,3) for three sets, "
    f"(1,$FFFF,$FFFF) for one",
    f"bytes {ECL_BUFFER[0]}-{ECL_BUFFER[1] - 1} = the target area's "
    f"ECL<n>.DAX block from byte {ECL_HEADER} on",
    f"bytes {POS_X}-{POS_FACING} = x, y, facing*{FACING_SCALE} indoors; on a "
    f"travel window the square is words ${TRAVEL_X:04X}/${TRAVEL_Y:04X} and "
    f"{POS_X}/{POS_X + 1} go stale, {POS_FACING} staying live",
    f"word ${PARTY_SIZE:04X} and byte {PARTY_SIZE_BYTE} = the party size",
)
