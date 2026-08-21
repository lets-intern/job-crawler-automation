# Document Writing Rules

These apply to every document: markdown, HTML, generated reports, PDF. No skill restates them.

## No icons, no emoji

Do not use check marks, crosses, warning signs, stars, memo glyphs or any other pictogram.
Not in table cells, not as list bullets, not as heading decoration.

State status as a word: `성공` / `실패` / `주의`. Build hierarchy from heading level and weight.

Emoji render differently per font and platform, and they break in PDF export, copy-paste and search.

When removing a pictogram from a table cell, replace it with a word. Never leave the cell empty —
an empty cell reads as the opposite of what was meant.

## No decoration

No repeated rules (`===`, runs of `---`), no box drawing, no bold used for emphasis alone.

Do not state the same content twice, once as a table and once as prose. Pick one.

## Precision

Every path, filename, endpoint and command in a document must exist. Verify before writing it.
A document that sends the reader to a path that is not there costs more than no document.

A selector, a URL or a field name quoted in a document is copied from the code or the recipe, never
retyped from memory.

Markers inside code comments (`TODO`, `FIXME`) are unaffected by any of this.
