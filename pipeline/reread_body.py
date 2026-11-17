#!/usr/bin/env python3
"""Re-read suspect body words from the page images, one word at a time.

    python3 -I pipeline/reread_body.py SOURCE.pdf --out build/full2 --workers 4

Headwords have been re-read from the page since early on; body text never was,
and it carries the confusions the first pass made at 300 dpi with full-page
layout analysis. The one the reader notices most is l read as i: `middie` for
middle, `cochieus` for cochleus, `thelr` for their. The letters are a hairline
apart in this typeface and the scan is a photograph of a 1912 printing.

The fix is not a dictionary and not a model. It is the ink. A word cropped from
a 600 dpi render and read on its own, in single-word mode, is a second
independent reading of the same marks, and on the three words the reader
reported it returns middle, cochleus and their without being told what to look
for.

What gets re-read
-----------------
Every word on the page is too many -- 845,000 of them, and most are ordinary
English that the first pass read correctly. A word is re-read when it is not
already trusted (not a headword, and not used 25 times or more in the book,
which between them cover the book's own vocabulary including its French, Latin
and Hebrew) and one of:

  * swapping a confusable letter pair turns it into a trusted word, which is a
    concrete hypothesis the second reading can confirm or deny; or
  * it scores in the worst 5% of the corpus on the character-trigram model,
    which catches damage nobody had a hypothesis for.

That is about 4,400 words. The rest keep their first reading.

What is accepted
----------------
Only where the second reading lands on a word the book is known to use and the
first did not. Where both readings are unattested the first one stands: two
engines failing differently is not evidence for either, and inventing a word
would be worse than leaving the damage visible. `Lut:` on page 851 is the
example -- the second reading says `luk`, neither is the `lulim` on the page,
so nothing is changed and it is left in the report instead.

Nothing here is deleted. Every substitution is written to body_reread.json with
the page, the box, and what the word was before, and the parse stage applies
them from that file, so the original reading of every word is recoverable.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.corrections.body_text import CONFUSIONS, TOKEN, EnglishShape

REREAD_DPI = 600
SCALE = REREAD_DPI / 300           # cached boxes are in 300 dpi pixels
PAD = 14                           # padding around the crop, in 600 dpi pixels
UPSCALE = 2                        # tesseract reads small crops better enlarged

TRUST_COUNT = 25                   # uses in the book that make a word the book's own
MIN_LENGTH = 4
SHAPE_PERCENTILE = 5               # worst N% of shape scores are also re-read
MAX_LENGTH_DRIFT = 2               # a second reading this much longer or shorter is a bad crop

ROMAN = re.compile(r"^[ivxlcdm]+$")
CORE = re.compile(r"[A-Za-zÀ-ɏ]+")


# ---------------------------------------------------------------------------
# choosing what to re-read


def vocabulary(entries: list[dict]) -> tuple[set[str], Counter]:
    """The words the book is known to use, and how often it uses them."""
    counts: Counter[str] = Counter()
    trusted: set[str] = set()
    for entry in entries:
        for token in TOKEN.findall(entry.get("body", "")):
            counts[token.lower()] += 1
        for token in TOKEN.findall(entry.get("headword", "")):
            trusted.add(token.lower())
    trusted |= {word for word, count in counts.items() if count >= TRUST_COUNT}
    return trusted, counts


def _variants(word: str) -> set[str]:
    out: set[str] = set()
    for wrong, right in CONFUSIONS:
        start = 0
        while True:
            at = word.find(wrong, start)
            if at == -1:
                break
            out.add(word[:at] + right + word[at + len(wrong):])
            start = at + 1
    out.discard(word)
    return out


def suspects(entries: list[dict]) -> tuple[set[str], set[str]]:
    """Word types worth a second reading, and the trusted vocabulary."""
    trusted, counts = vocabulary(entries)
    model = EnglishShape({w: c for w, c in counts.items() if c >= TRUST_COUNT})

    open_words = [w for w in counts
                  if len(w) >= MIN_LENGTH and w not in trusted and not ROMAN.match(w)]
    scores = sorted(model.score(w) for w in open_words)
    cutoff = scores[max(0, len(scores) * SHAPE_PERCENTILE // 100 - 1)] if scores else -99

    chosen = set()
    for word in open_words:
        if any(v in trusted for v in _variants(word)) or model.score(word) <= cutoff:
            chosen.add(word)
    return chosen, trusted


def core_of(text: str) -> str:
    """The letters of a token, without the punctuation stuck to it."""
    found = CORE.findall(text)
    return "".join(found).lower()


# ---------------------------------------------------------------------------
# reading the ink


def page_targets(words_path: Path, chosen: set[str]) -> list[tuple[int, int, int, int, str]]:
    data = json.loads(words_path.read_text(encoding="utf-8"))
    if data.get("failed"):
        return []
    out = []
    for text, left, top, width, height, *_rest in data.get("words", []):
        if core_of(text) in chosen:
            out.append((left, top, width, height, text))
    return out


def reread_page(args: tuple[str, int, list, str]) -> list[dict]:
    pdf_path, pdf_page, targets, work_dir = args
    if not targets:
        return []

    # Each page's readings are written as they are made. A run over the whole
    # book takes a quarter of an hour, long enough that it will sometimes be
    # interrupted, and re-reading pages that were already read is pure waste.
    part = Path(work_dir).parent / "reread_parts" / f"p{pdf_page:04d}.json"
    if part.exists():
        try:
            return json.loads(part.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    from PIL import Image

    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    stem = work / f"r{pdf_page:04d}"
    result = subprocess.run(
        ["pdftoppm", "-r", str(REREAD_DPI), "-gray", "-png",
         "-f", str(pdf_page), "-l", str(pdf_page), pdf_path, str(stem)],
        capture_output=True, text=True)
    produced = sorted(work.glob(f"r{pdf_page:04d}*.png"))
    if result.returncode != 0 or not produced:
        return []

    image = Image.open(produced[0]).convert("L")
    page_width, page_height = image.size
    out = []

    for left, top, width, height, text in targets:
        box = (max(0, int(left * SCALE) - PAD),
               max(0, int(top * SCALE) - PAD),
               min(page_width, int((left + width) * SCALE) + PAD),
               min(page_height, int((top + height) * SCALE) + PAD))
        if box[2] - box[0] < 12 or box[3] - box[1] < 12:
            continue
        crop = image.crop(box)
        crop = crop.resize((crop.width * UPSCALE, crop.height * UPSCALE), Image.LANCZOS)
        crop_path = work / f"c{pdf_page:04d}_{left}_{top}.png"
        crop.save(crop_path)
        # --psm 8 is "a single word", which is exactly what the crop holds.
        read = subprocess.run(
            ["tesseract", str(crop_path), "stdout", "--psm", "8", "-l", "eng"],
            capture_output=True, text=True)
        crop_path.unlink(missing_ok=True)
        if read.returncode != 0:
            continue
        second = " ".join(read.stdout.split()).strip()
        if second:
            out.append({"pdf_page": pdf_page, "left": left, "top": top,
                        "first": text, "second": second})

    produced[0].unlink(missing_ok=True)
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# deciding


def decide(readings: list[dict], trusted: set[str],
           elsewhere: set[str] | None = None) -> list[dict]:
    """Keep only the second readings that land on a word the book uses.

    `elsewhere` is the vocabulary of the other printing of the same book (see
    corrections/reference.py). A second reading that lands on a word the 1874
    edition uses is attested even when this scan never managed to read it --
    which is how Recueil, a word this extraction had only ever misread, gets
    accepted.
    """
    accepted = []
    known = trusted | (elsewhere or set())
    for record in readings:
        first, second = record["first"], record["second"]
        before, after = core_of(first), core_of(second)
        if not after or before == after:
            continue
        if before in known or after not in known:
            continue
        if abs(len(after) - len(before)) > MAX_LENGTH_DRIFT:
            continue
        accepted.append(dict(record, before=before, after=after,
                             text=_respell(first, second)))
    return accepted


def _respell(first: str, second: str) -> str:
    """Put the second reading's letters into the first reading's token.

    The punctuation stays as the first pass had it. A crop carries a stray
    comma or quote often enough that taking the second reading whole would
    trade one kind of damage for another, and the first pass saw the word in
    its line, where the punctuation actually is.
    """
    letters = CORE.findall(second)
    if not letters:
        return first
    replacement = "".join(letters)

    def shaped(match: re.Match[str]) -> str:
        found = match.group(0)
        if found.isupper() and len(found) > 1:
            return replacement.upper()
        if found[:1].isupper():
            return replacement[:1].upper() + replacement[1:].lower()
        return replacement.lower()

    return CORE.sub(shaped, first, count=1) if CORE.search(first) else first


# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf")
    parser.add_argument("--out", default="build/full2")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0, help="first N pages only")
    parser.add_argument("--start", type=int, default=0, help="skip pages below this")
    options = parser.parse_args()

    out_dir = Path(options.out)
    entries = json.loads((out_dir / "entries.json").read_text(encoding="utf-8"))["entries"]
    chosen, trusted = suspects(entries)
    print(f"{len(chosen)} word types to re-read, {len(trusted)} trusted")

    words_dir = out_dir / "words"
    jobs = []
    total = 0
    for path in sorted(words_dir.glob("p*.json")):
        pdf_page = int(path.stem[1:])
        if options.limit and pdf_page > options.limit:
            continue
        if pdf_page < options.start:
            continue
        targets = page_targets(path, chosen)
        if targets:
            jobs.append((options.pdf, pdf_page, targets, str(out_dir / "reread_tmp")))
            total += len(targets)
    print(f"{total} words on {len(jobs)} pages")

    started = time.time()
    readings: list[dict] = []
    done = 0
    with ProcessPoolExecutor(max_workers=options.workers) as pool:
        for result in pool.map(reread_page, jobs):
            readings.extend(result)
            done += 1
            if done % 50 == 0:
                rate = done / (time.time() - started)
                print(f"  {done}/{len(jobs)} pages  {rate:.1f}/s  "
                      f"{(len(jobs) - done) / max(rate, 0.01) / 60:.1f} min left", flush=True)

    # Merge in everything read by earlier runs, so a run that covers part of
    # the book still produces a complete file.
    readings = []
    for part in sorted((out_dir / "reread_parts").glob("p*.json")):
        try:
            readings.extend(json.loads(part.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue

    accepted = decide(readings, trusted)
    agree = sum(1 for r in readings if core_of(r["first"]) == core_of(r["second"]))
    print(f"read {len(readings)}; {agree} agreed; {len(accepted)} corrections")

    (out_dir / "body_reread.json").write_text(
        json.dumps({"readings": readings, "accepted": accepted},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {out_dir / 'body_reread.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
