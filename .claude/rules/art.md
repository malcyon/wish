---
paths:
  - "ui/**"
  - "assets/**"
  - "**/*.svg"
---

# Art

**No AI-generated art, anywhere, ever.** Not icons, not logos, not textures, not
placeholders "until we find a real one". This is Donald's rule and it is not
negotiable by an agent that finds it inconvenient.

**Do not modify somebody else's art either.** An icon lifted from Font Awesome
is drawn the way Fonticons drew it. If it does not work at a size, the answer is
a different icon, or not using it at that size -- never nudging the artist's
geometry until it does. An assistant that moves a path point is making art, and
that is the thing it must not do.

**Art comes from a set with a licence we can honour** -- Font Awesome Free, CC
BY 4.0, attributed in the README and the About box -- or from a human being.

**Attribution names a work as its author titled it.** game-icons.net's
`embrassed-energy` is titled *Embraced energy* on its own page, so the licence
credit says "Embraced Energy" -- `wish/licenses.py`'s `TITLES` is the one-entry
override that does it. The identifier, the archive filename and the URL keep the
filename's spelling, because the committed path data is diffed against that file
and that is the address that resolves.

Why these rules exist, and the incidents behind them:
`docs/160-why-these-rules.md`, "Art".
