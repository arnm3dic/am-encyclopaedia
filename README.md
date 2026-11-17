# AM Encyclopaedia

Named for Albert Gallatin Mackey (1807–1881), whose *Encyclopædia of Freemasonry
and Its Kindred Sciences* set the pattern this collection follows: a symbol per
entry, traced to its sources.

A reference work on symbolic meanings: what things have stood for, where that
association comes from, and how it shifts between cultures and periods.

Each symbol is one Markdown file with structured frontmatter, so the collection
stays readable as plain text, diffs cleanly in git, and can later be rendered as
a website or queried as data without being rewritten.

## Structure

```
entries/
  animals/      owl, raven, snake, lion, ...
  plants/       olive, lotus, yew, rosemary, ...
  colors/       red, white, purple, ...
  numbers/      three, seven, twelve, ...
  objects/      mirror, key, bridge, anchor, ...
  celestial/    moon, north star, eclipse, ...
  _TEMPLATE.md  copy this to start a new entry
scripts/
  validate.py   checks every entry's frontmatter and section order
```

Categories are folders, not a fixed taxonomy — add one when a symbol genuinely
doesn't fit the existing six.

## Adding an entry

```bash
cp entries/_TEMPLATE.md entries/animals/raven.md
$EDITOR entries/animals/raven.md
python3 scripts/validate.py
```

File names are lowercase and hyphenated (`north-star.md`), one symbol per file.
See [CONTRIBUTING.md](CONTRIBUTING.md) for the entry conventions and what counts
as a usable source.

## Entry format

Frontmatter carries the machine-readable fields:

```yaml
---
title: Owl
slug: owl
category: animals
aliases: [owls, strix]
domains: [wisdom, death, night]
cultures: [greek, roman, celtic, japanese]
status: draft
---
```

- `domains` — the meanings themselves, as lowercase single words or short phrases
- `cultures` — traditions the entry actually documents, not every place the symbol appears
- `status` — `draft` until sourced and read back, then `reviewed`

The body then runs: summary, core meanings, by tradition, inversions and
tensions, related entries, sources. `scripts/validate.py` enforces that order.

## Conventions

Claims about a specific tradition get a source. Where traditions disagree the
entry says so rather than averaging them into a single meaning — the
disagreement is usually the interesting part. Modern commercial or New Age
associations are labelled as such and not blended with older attestations.

## Status

Early. The two entries in `entries/` are worked examples of the format, not a
sample of finished quality.
