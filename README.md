# AM Encyclopaedia

A searchable offline edition of Albert G. Mackey's *An Encyclopaedia of
Freemasonry and Its Kindred Sciences* (new and revised edition, 1914), built
as a progressive web app.

Compiled for the Brethren's reference by Arnie T. Free for education and
private study; not to be sold. See the About panel in the app for the full
terms.

## Publishing it

`docs/` is the built site, and GitHub Pages serves it straight from the
repository:

    Settings -> Pages -> Source: Deploy from a branch
                      -> Branch: main, folder: /docs

The address is then `https://<user>.github.io/<repo>/`. Everything in the app
resolves relatively -- the manifest's `start_url` and `scope` are `.`, the
data is fetched from the module's own URL, and the service worker registers
at `sw.js` -- so it works from a subpath with no changes.

`docs/` is committed rather than built on a runner. The data is produced by
the Python pipeline from a 58 MB scan that is not in this repository, so
there is nothing a build step could regenerate it from.

Rebuild it with `node app/build.mjs`, which writes `app/dist/` and copies it
to `docs/`.

The source is a 946-page scan. Volume 1 carries a 2007 OCR layer that splices
the two columns together mid-line; volume 2 carries none at all. Both are
discarded: the pipeline re-OCRs every page.

## Two codebases

```
pipeline/   Python. Runs once on a desktop. PDF -> dictionary.db -> entries.json
app/        The PWA. Ships the finished data; never parses a PDF.
```

Extraction never runs on a user's device. The book is fixed, so deriving the
text once means OCR errors are corrected in one place for everybody.

## How entries are found

Mackey sets entries run-on: a headword starts mid-column and is marked only by
being bold. OCR discards font weight, so the pipeline measures it from the
image — the distance transform of each word's ink gives a stroke width, and
body text measures 4.0 against a headword's 6.0.

Alphabetical order is then an independent check on the result: a headword that
breaks ordering is either a false positive or a misread, and every one is
reported rather than silently kept.

## Running the extraction spike

```bash
python3 -I pipeline/run_spike.py path/to/source.pdf --out build/spike
```

Writes `entries.json`, `issues.json`, `report.txt` and the page images.
Requires `tesseract`, `poppler-utils`, and Python with `numpy`, `scipy`,
`pillow`.

## Status

Phase 1 complete: 30-page spike, 136 entries, 13 flagged issues, two pages
hand-verified at 100% headword accuracy. See the plan document for the full
roadmap.
