---
paths:
  - "wish/**"
  - "editor/**"
  - "automap/**"
  - "ui/**"
---

# Help text in the GUI

**Every word a user reads in the interface is Donald's to approve.** Labels,
button text, tooltips, status messages, empty-state lines, dialog prose --
propose the wording, do not ship it.

**When in doubt, leave it out and say so in the reply.** The interface kept
growing sentences that explained itself until it read as a program apologising
for itself; every one of them was removed on request. Removing a sentence is
cheap, and a user reading a paragraph that should never have existed is not.

**"It matches the wording already there" is not approval.** The sentences
already in the interface read well to somebody who knows the machinery, which
is everybody who has reviewed them and nobody who is using the program.
Donald's verdict on three strings shipped that way --
`#96 (Three interface strings shipped tonight without being approved)` -- was
*"they won't be understood by humans"*.

**Everything a person reads starts with a capital letter.** The Messages panel,
the status bar, a dialog, a tooltip, a label, an empty-state line, the debug
log, what the CLI prints, and the assistant's own replies in the terminal.
Assistant-written strings start lowercase far more often than human-written
ones, because they are written as fragments -- `no party to read`, `waiting for
the game` -- and nobody looks at the finished line.

**Capitalise the composed line, not the strings that go into it.** The first
word is usually the caller's -- `_report("fast travel", outcome)`,
`action.label.lower()` on the action bar -- so upper-casing each message
constant leaves the prefix lowercase and changes nothing a user sees. Do it
where the final line is assembled: `FastTravelBar._report` and
`ActionBar._report` each do it in one place, and
`test_a_messages_panel_line_opens_with_a_capital` pins it.

**Only the first letter, never `str.capitalize()`**, which lower-cases the rest
and would turn the combat log's `MAGNUS MISSES.` into `Magnus misses.` and
mangle `$6E11`. `line[:1].upper() + line[1:]` is the whole of it, and it is
already right for a line starting with a proper noun, an address, or the game's
own shouted text.

**A fragment stays a fragment.** A string only ever pasted into the middle of a
sentence is not a line a person reads, and capitalising it mid-line is worse
than leaving it. The test is where the string ends up, not what it looks like
in the source.

**Never open a sentence with a quotation that starts lowercase.** Quoting a
lowercase string is correct; starting a sentence with that quote makes the
sentence lowercase anyway. Put words in front of it: *The line reads `counts
towards commissions completed`, and it names a label the window no longer
shows.*

**No memory address, register or file offset in front of a player.** In a
docstring, a code comment, a `docs/` page or an issue, cite it -- that is what
makes a finding checkable. In a tooltip, a label, a panel column or a message,
it is a developer's note that escaped. The same goes for anything else only a
developer knows: a script filename like `ECL08`, a record offset like `0x0A1`,
a raw flag byte. `also needs $4A97 (Cadorna's chambers) unpaid` becomes `also
needs Cadorna's chambers unpaid`, and nothing is lost -- the address stays in
`goldbox/commissions.py`. `test_no_quest_log_tooltip_shows_a_memory_address`
pins it for that panel.

**The debug log is the exception**, and `WISH_DEBUG` output generally: it is
read by whoever is debugging, and an address there is the point.

**Look at the string in the running window before proposing it, not in the
source.** A line that reads well in the code can repeat the prefix the pane
puts in front of it, and that is invisible in a diff and obvious in a
screenshot. `QWidget.grab()` works under `offscreen`, so a screenshot never
needs a visible window:

```sh
env -u WAYLAND_DISPLAY -u XDG_SESSION_TYPE QT_QPA_PLATFORM=offscreen \
    GDK_BACKEND=x11 .venv/bin/python your_script.py
```

`tests/conftest.py` forces `QT_QPA_PLATFORM=offscreen`, so `pytest` is safe;
anything that builds a `QApplication` outside the suite is not.
`tools/iconsheet.py` is the pattern.

Why these rules exist, and the incidents behind them:
`docs/160-why-these-rules.md`, "Help text in the GUI".
