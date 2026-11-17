# Contributing

## One symbol per file

`entries/<category>/<slug>.md`, lowercase and hyphenated. If a symbol plausibly
belongs in two categories, pick one and cross-link from the other rather than
duplicating the entry.

## Frontmatter

| Field | Required | Notes |
| --- | --- | --- |
| `title` | yes | Display name, capitalised |
| `slug` | yes | Must match the filename without `.md` |
| `category` | yes | Must match the containing folder |
| `aliases` | no | Other names, including original-language terms |
| `domains` | yes | The meanings; lowercase, one or two words each |
| `cultures` | yes | Only traditions the entry actually documents |
| `status` | yes | `draft` or `reviewed` |

Run `python3 scripts/validate.py` before committing. It checks the fields above,
that `slug` and `category` agree with the path, and that the body sections appear
in the expected order.

## Writing an entry

**Say where a meaning comes from.** "The olive means peace" is a dictionary
entry. Why it means peace — and to whom — is the thing worth writing down.

**Keep traditions separate.** A symbol usually means several incompatible
things. Give each tradition its own subsection under *By tradition* instead of
merging them into one averaged meaning.

**Record disagreement.** If two traditions conflict, or a meaning inverted at
some point, that belongs in *Inversions and tensions* rather than being smoothed
over.

**Date the recent stuff.** Associations invented by advertising, Victorian
revival, or twentieth-century occultism are legitimate entries, but they are
labelled with their period so they don't read as ancient.

## Sources

Cite published scholarship, primary texts, or museum and archive material.
Author and title are enough; add page or book numbers where a specific claim
rests on a specific passage. Symbol-dictionary websites and AI output are not
sources — if a claim can't be traced further than those, leave it out or mark
the entry `draft` with a note.

Don't invent citations, including plausible-looking page numbers. An unsourced
claim marked as unsourced is more useful than a sourced-looking one that isn't.

## Status

Set `status: reviewed` only once every claim in the entry has a source and
someone has read it back against them. Everything starts at `draft`.
