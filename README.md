# AM Encyclopaedia

A searchable offline edition of Albert G. Mackey's *An Encyclopaedia of
Freemasonry and Its Kindred Sciences* (revised edition, 1912), built as a
progressive web app.

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
