# A logo, and an icon Windows will show

**Status: built and wired.** Task **P74**. Donald — *"We need an icon for the
app that Windows will show in the task bar. Until I can hire an artist, we can
use something from Font Awesome."*

The mark is Font Awesome's `hat-wizard` on an indigo tile. Donald, 2026-08:
*"Change the logo icon used to the wizard hat from the font awesome set."* It
is generated from `ui/icons.py`, so it cannot drift from the glyph the program
paints, and there is no artist to wait for. §5 is what shipped, §6 is the
small-size problem it brought with it, and §1 and §2 are the brief for the
artist, when there is one.

---

## The verdict

* **The glyph is Font Awesome's `hat-wizard`**, path data verbatim from
  `svgs-full/solid/`, in `ui/icons.py` under `FONT_AWESOME`. A leaning cone
  with two sparkles cut out of it, over a rounded bar. Wish is a spell; the hat
  is the spellcaster.
* **Font Awesome as an app icon is legal.** CC BY 4.0 is satisfied by the
  credit in the README and in Help > About — the attribution does not have to
  be *on* the icon, which is as well, because an `.ico` has nowhere to carry
  one. The About box also says the drawing was changed, which the licence
  requires and §6 is the change. What CC BY does not grant is exclusivity:
  this is a mark anyone else may also ship. §3.
* **The brim never touches the cone, at any size.** That is Fonticons'
  drawing, not a fault — from 22 px up the gap reads as a gap and the icon is
  a hat resting on a table. It is a fault at 16 and 20, where both edges land
  on part-covered pixels and the icon is a fin over a grey smear, so those two
  sizes slide the bar up until it meets the cone. §6.
* **What it looks like at 16 px, honestly.** A white leaning cone with two
  dark nicks in it, flaring into a bar, inside a rounded indigo square. One
  connected mass — the bar `109` sets. The sparkles are what make it a hat
  rather than a fin, and they are two dark pixels each at that size, so it is
  legible without being self-evident. It is unmistakable from 32 up.

---

## 1. Every asset, with real sizes

This is the table to hand an artist. One master vector; everything else is a
size-tuned export from it, and the small ones are **tuned, not scaled** — see
§2.

| asset | pixel sizes | format | background | has to survive |
|---|---|---|---|---|
| **master** | 1024×1024, drawn on a 640-unit grid to match `ui/icons.py` | SVG, filled paths, **no strokes** | transparent | being the only source of everything below |
| **Windows `.ico`** | 16, 20, 24, 32, 40, 48, 64, 256 | ICO — 32-bit BGRA DIB for ≤64, PNG for 256 | transparent | 16 px against a dark *and* a light taskbar |
| **macOS `.icns`** | 16, 32, 64, 128, 256, 512, 1024 (16/32/128/256/512 each ×1 and @2x) | ICNS built from an `.iconset` directory | transparent, glyph inside Apple's rounded square: 824×824 centred in 1024, corner radius ≈185 | the Dock's own drop shadow, which eats the outer edge |
| **Linux hicolor** | 16, 22, 24, 32, 48, 64, 128, 256, plus one `scalable` | PNG per size + SVG | transparent | GNOME's 22 and KDE's 24, which are nobody's export defaults |
| **About dialog** | 64 logical → 64, 128, 192 px for 1×, 2×, 3× | `QPixmap` painted from the vector | the dialog's own ground, light theme and dark | sitting beside three lines of text without shouting |
| **README lockup** | 1200×300, displayed at `width=400` | SVG preferred, PNG fallback | transparent | GitHub's light **and** dark reading themes |
| **GitHub social preview** | 1280×640, safe area 1120×560 | PNG | opaque | being cropped by Slack, Twitter and Discord cards |

### Why those `.ico` entries

A `.ico` is a container. Windows picks the entry nearest the size it wants and
**bilinearly scales when it has to** — a 256 squeezed to 16 is mush, which is
the entire reason a hand-tuned 16 goes in the file.

| size | where Windows uses it |
|---|---|
| **16** | title bar, Alt-Tab, Explorer's List and Details views, the taskbar when "use small taskbar buttons" is on |
| **20, 24, 40** | the same slots at 125 %, 150 % and 250 % display scaling — Windows does not round to 16 or 32, it asks for these |
| **32** | the taskbar button at 100 % scaling and the desktop shortcut. With 16, the pair that matters most |
| **48** | Explorer's Medium and Large icon views, and the shell's default shortcut size |
| **64** | 32 at 200 % scaling |
| **256** | Explorer's Extra Large view, the file's Properties sheet, and anything that shows the exe big |

**Windows takes the taskbar icon from the executable's resource, not from Qt.**
`QApplication.setWindowIcon` sets the title bar, Alt-Tab and the taskbar button
of a *running* window; a pinned shortcut, and the file in Explorer, use the
`.ico` PyInstaller embedded. Both are needed and they must be the same drawing.

---

## 2. What a 16×16 icon can be

State this in the brief, because at 16 pixels almost nothing survives and an
artist asked for a scene will deliver one.

`109-icon-choices.md` already derived the rule the hard way, from a magnified
sheet: **one connected silhouette, every feature at least about 64 units in the
640 box** — a tenth of the width, which is 1.6 px at 16. The failure that kills
a glyph is *separation*, not mush: `hat-wizard`'s brim stops touching its cone
and the icon reads as a shark's fin. That is the app icon's own glyph, and §6
is what had to be done about it at 16 and 20.

| reads at 16 | does not |
|---|---|
| one bold silhouette with a strong outline — a cone, a key, an arrow | two or more separate parts (FA's `wand-sparkles` becomes three loose dots) |
| a filled tile with the shape knocked out of it | a shape on transparency, which is grey pixels on an unknown ground |
| at most one or two interior holes, each ≥10 % of the box | fine interior detail, hatching, texture |
| two colours and the background | gradients, shadows, bevels — all of which eat the one pixel of edge |
| a single letterform, if it is heavy | any word, any number of two digits |
| asymmetry that survives a squint | a perspective view of anything |

Two more the artist will not think of: it has to read **against both a dark and
a light taskbar**, so the silhouette cannot depend on being dark; and it has to
be recognisable **in monochrome**, because Windows renders it that way in some
places and screen readers describe it in none.

**"Knocked out" turned out to want one amendment.** Cutting the shape out of
the tile leaves the taskbar showing through the shape, so on a dark desktop a
dark tile carries a dark hole and there is nothing to see. What ships fills the
hat with paper instead: the same silhouette, with a ground guaranteed on both
sides of every edge, and it still reads greyscale.

---

## 3. The attribution question

This project already carries Font Awesome Free 7.3.1 path data in `ui/icons.py`
under **CC BY 4.0**, licence text in
[`licences/fontawesome-LICENSE.txt`](licences/fontawesome-LICENSE.txt), credited
in the README's *Credits* and in `wish/about.py`.

**What CC BY 4.0 obliges, for an application icon.** Wherever the work is
distributed: name the creator (Fonticons, Inc.), name the licence, link to it,
link to the source, and say if you changed it. It does **not** have to appear on
the icon or in the icon file — "any reasonable manner for the medium" is the
licence's own wording, and a credit in an About box is the accepted form for
software. **wish already discharges this**, in two places, and the About box
now also says the drawing was changed — §6 — which is the clause a recoloured,
part-rearranged glyph brings into play.

Two costs, accepted rather than avoided:

1. **CC BY grants no exclusivity.** Anyone may ship the identical mark under the
   identical terms. A logo is the one asset where that is the point.
2. **The obligation follows the artefact forever.** A `.ico` embedded as a
   Windows resource has nowhere to carry a credit, so the credit lives in a
   dialog the user must open — defensible, but it has to be defended again at
   every new place the mark appears: a store listing, a `.desktop` file, a
   favicon, a screenshot in someone else's article.

And note the set's own trap, already recorded in `ui/icons.py`: **the brands are
off limits** — the licence forbids brand-logo use and the set ships
`wizards-of-the-coast`.

### Why `hat-wizard`

Donald asked for it by name. It suits the program: Wish is the ninth-level
spell, and a wizard's hat is the one thing that says *magic* without saying
*combat* — and the program is a character editor first.

It is the glyph [`109-icon-choices.md`](109-icon-choices.md) rejected, and that
rejection stands where it was made: **the map's magic-user icon is still ours**,
because at 13 px in a map cell the brim comes away and the glyph is a fin. An
app icon is a different job — 16 is the smallest it is ever drawn, it sits on
its own tile rather than beside a wall, and the sizes that matter most are 32
and up. §6 is what the two smallest sizes cost.

Everything already available, judged as a logo:

| candidate | source | as an app icon |
|---|---|---|
| **`hat-wizard`** | Font Awesome | **chosen** — Donald's call; §6 for the two smallest sizes |
| `wizard-hat` | ours | the previous mark, and still the map's magic-user glyph |
| `sword` | ours | says combat; the program does not do combat |
| `swords` | ours | reads as a starburst at small sizes, and already means "encounter" on the map |
| `chest`, `hood` | ours | fine glyphs, poor identities — a chest is a file manager, a hood is a VPN |
| `location-dot` | Font Awesome | the other FA pick: it says *map*, and its counter is the 64-unit floor the whole rule was set from |

**When the artist is hired**, the brief is §1 plus §2, and the one thing to buy
that a cheap job will skip: **hand-tuned 16, 24 and 32**, not exports of the
1024. That is most of the work and all of the difference.

---

## 4. Where each asset is used

| place | mechanism | file |
|---|---|---|
| the Windows exe, Explorer, a pinned shortcut | `EXE(..., icon="assets/wish.ico")` | `wish.spec` |
| the taskbar button and title bar of a running window | `app.setWindowIcon(app_icon())`, a pixmap per size so Qt picks rather than scales | `wish/window.py::dress` |
| the taskbar *grouping* on Windows | `SetCurrentProcessExplicitAppUserModelID` before the first window, or a Python-hosted window can group and pin under the interpreter | `wish/window.py::dress` |
| the panel icon on Linux | `app.setDesktopFileName("wish")` — GNOME and KDE match a window to its `.desktop` by app id, and a Wayland window gets a generic icon without it. There is still no `.desktop` file and the Linux artefact is a tarball, so the hicolor PNGs sit under `assets/` waiting for a package | `wish/window.py::dress` |
| Help > About | a hand-built `QMessageBox` with `setIconPixmap(appicon.pixmap(64))`; `QMessageBox.about` paints the platform's information icon and takes no picture | `wish/about.py` |
| the README | an `<img>` at the top — **Donald's file; ask** | `README.md` |
| the icon files themselves | a generator, offscreen, in the shape of `tools/iconsheet.py` | `tools/genicons.py` |

---

## 5. What was built

**The drawing** is `ui/appicon.py`, beside `iconpaint.py` because it is the same
job: `icons.py` path data turned into pixels. `hat-wizard` on a rounded tile,
`#2b3a67` behind `#f7f9fb`, the glyph inset 10 % of the side and centred on its
own ink rather than on the 640 box, which sits high in it. Indigo rather than
the interface's near-black `#16202b`: a near-black tile is invisible on
Windows' dark taskbar, and being visible against an unknown ground is the whole
reason to have a tile.

**The generator** is `tools/genicons.py`, offscreen through `ui.iconpaint`
exactly as `tools/iconsheet.py` renders the sheet. Every size is rendered from
the vector; nothing is a downscale of anything. It writes:

| file | what |
|---|---|
| `assets/wish.ico` | 16, 20, 24, 32, 40, 48, 64, 256 — DIB below 256, PNG at 256, 48 KB |
| `assets/icons/hicolor/{N}x{N}/apps/wish.png` | 16, 22, 24, 32, 48, 64, 128, 256 |
| `assets/wish.png` | 256, for a README |

The `.ico` container is written here in `struct` rather than by Pillow. Not for
the fun of it: a `.ico` wants a DIB for the small entries and a PNG for the 256,
and every library that writes one makes that choice for the whole file at once.
Thirty lines buys the mix the shell documents and leaves the generator needing
nothing Qt does not already provide.

**The output is committed.** PyInstaller wants the `.ico` to exist when it reads
`wish.spec`, so generating it in CI would mean a build step before every build;
committing it keeps the release a single command. `tests/test_appicon.py`
re-renders every artefact and compares, so a change to the path data that
nobody regenerated fails the build instead of shipping the old drawing.

**The comparison is pixels, not bytes**, and it is worth saying why. It was
bytes, and CI went red on every runner with the same six names — `wish.ico`,
`wish.png`, and the 22, 48, 64 and 256 hicolor PNGs — while 16, 24, 32 and 128
came back byte-identical on all of them. That split is the diagnosis. A
rasterising difference cannot be selective: the smallest edit worth catching
moves pixels at *every* size (one path point by 1/640 moves 10 px at 16 and
218 at 256), and one ulp on the scale factor moves none anywhere. A
compressor's output differs exactly where the data leads it to — and the
compressor is not ours. `ldd libQt6Gui.so.6` resolves `libpng16.so.16` and
`libz.so.1` to the *host's* copies on Linux; the Windows wheel bundles its own.
Qt promises the pixels, so the pixels are what is asserted, and the committed
bytes only have to decode to them. `tools/genicons.py --check` uses the same
`differences()` and says how many pixels moved and by how much.

**The tests measure the drawing, not the file list.** The 16 is rasterised and
flood-filled to prove it is one connected piece — the failure that killed
`hat-wizard` on the map — its widest row is checked to be the bottom one and at
least 8 px across, so the brim is still there, and the 16 stored in the `.ico`
is compared pixel for pixel against a fresh 16 to prove it is not a squeezed
256. `test_the_brim_is_slid_up_below_22_and_left_where_it_was_above` is §6 as
an assertion: one piece at 16 and 20, two pieces with a whole row of tile
between them at 22, 24, 32 and 48.

**The no-images rule is gone**, so none of this needed working around. Donald,
2026-08: *"You need to remove that test that blocks all pngs. We don't need
that."* `tests/test_repository_contents.py` still refuses disk images,
executables, audio and PDFs, which is the part that was ever about the game.

### Still not done

* **No `.desktop` file and no macOS bundle.** The hicolor PNGs are generated and
  committed, but nothing installs them: the Linux artefact is a tarball. Wire
  them up when there is a package. `.icns` waits for a Mac to test on.
* **No README lockup.** A mark plus the word, 1200×300, is an artist's job or an
  hour in Inkscape; `assets/wish.png` is the mark alone in the meantime.
* **Nobody has seen it on a Windows taskbar.** That is a row for
  [`122-release-testing.md`](122-release-testing.md)'s Windows column, and it
  now has somebody who can tick it.

---

## 6. The brim, and the two sizes it does not survive

Font Awesome draw `hat-wizard` as three subpaths: the cone, with a four-point
sparkle notched out of its foot; a second sparkle; and the brim, a rounded bar.
**The bar never touches the cone.** The cone's last point is `y=464.1` and the
bar starts at `y=512`, so there are 48 units of nothing between them — 7.5 % of
the drawing's height, at every size. That is the drawing, not a defect: it is a
hat resting on a table.

Rasterised on the tile, with the glyph inset 10 %, the gap is `0.077 × size`
pixels. Measured:

| size | what the gap does | what the bar does |
|---|---|---|
| **16** | 1.2 px — no row is pure tile; cone and bar smear together | never reaches full paper: a grey band |
| **20** | 1.5 px — two part-covered rows, no clean one | solid, but the gap under it is a smudge |
| **22** | 1.7 px — **one whole row of tile** | solid, two rows |
| **24** | 1.8 px — one whole row | solid, two rows |
| **32** and up | 2.5 px and rising | solid, and the gap reads as deliberate |

So `ui/appicon.py` carries `CLOSE_BELOW = 22`. At 16 and 20 the bar is cut off
the path and translated up by the 47.9 units of the gap, so it meets the cone's
foot and the silhouette is one connected mass; the glyph is then centred on its
own (now 48 units shorter) ink, so it does not ride high. At 22 and above the
path is drawn exactly as Fonticons wrote it.

**Three treatments were rendered and looked at before this one was picked.**

| treatment | verdict |
|---|---|
| leave it verbatim everywhere | 16 is a fin over a grey smear. No. |
| slide the bar up **below 22** | **chosen.** Fixes the two that fail, changes nothing that works |
| fill the sparkles in as well, for a clean small silhouette | **actively worse** — the sparkles are what make it a hat. Without them it is precisely the shark's fin `109` named |
| keep `wizard-hat` at 16 and 22 and the FA hat above | two different marks a size apart, for one size that needed help |

The third row is the finding worth keeping: the notch in the cone's foot is not
decoration. Fill it and the glyph loses the only feature that distinguishes a
wizard's hat from a dorsal fin.

`tests/test_appicon.py::test_the_brim_is_slid_up_below_22_and_left_where_it_was_above`
asserts all of it: one piece at 16 and 20; two pieces with at least one whole
row of tile between them at 22, 24, 32 and 48.
