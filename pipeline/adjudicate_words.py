#!/usr/bin/env python3
"""Where the two printings disagree about a word, go back to the ink.

    python3 -I pipeline/adjudicate_words.py SOURCE.pdf --out build/full2

The scan is the 1914 revision; the Internet Archive's copy is the 1874 first
edition, and for Mackey's own articles the two are word for word the same.
Head to head on 1,849 single-word disagreements, the scan is the odd one out
411 times and the 1874 text 258 times -- so the other copy is better, but it
is an OCR too, and copying from it wholesale would trade one set of errors for
a smaller set of someone else's.

So neither text gets the casting vote. Every word the two disagree about is
cropped out of a 600 dpi render and read on its own, and that reading decides:

    the ink says what the scan says   -> the scan was right, change nothing
    the ink says what the 1874 says   -> correct it
    the ink says neither              -> leave it, and write it down

The third case is the important one. Two engines failing differently is not
evidence for a third answer, and a word nobody can read is better left visibly
wrong than quietly invented.

This also protects the places the two editions genuinely differ. The 1914
printing Americanised much of 1874's spelling, and where the page really does
say worshipers the ink says so too, so the word stands. No list of exceptions
is needed, because the question being asked is no longer "which text is
right?" but "what is actually printed?"
"""

from __future__ import annotations

import argparse
import difflib
import json
import subprocess
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.corrections import reference as ref
from pipeline.reread_body import REREAD_DPI, SCALE, PAD, UPSCALE, core_of

MIN_LENGTH = 3
MAX_EDITS = 3          # further apart than this is a different word, not a misread

# The one place where the ink and the 1874 text make the same mistake, so the
# vote comes out 2-1 against the truth. "Dict." is how Mackey cites a
# dictionary, and c read as e is the commonest confusion in this typeface:
# both the 600 dpi crop and the 1874 engine turn it into "Diet.". Four
# occurrences, and the reading is not in doubt, so this pass leaves them.
NEVER = {("dict", "diet")}


def disagreements(entries: list[dict], reference: ref.Reference) -> list[dict]:
    """Every one-for-one word difference between the two printings."""
    out: list[dict] = []
    for entry in entries:
        mine = ref.words_of(ref.flatten(entry.get("body", "")))
        if len(mine) < 10:
            continue
        start = reference.locate(mine)
        if start is None:
            continue
        theirs = reference.words[max(0, start - 20):start + len(mine) + 200]
        matcher = difflib.SequenceMatcher(None, mine, theirs, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag != "replace" or i2 - i1 != 1 or j2 - j1 != 1:
                continue
            scan, other = mine[i1], theirs[j1]
            if len(scan) < MIN_LENGTH or len(other) < MIN_LENGTH:
                continue
            if ref.edits(scan, other, MAX_EDITS) > MAX_EDITS:
                continue
            start_page = entry.get("pdf_page")
            if not isinstance(start_page, int):
                continue
            # Entries record where they begin, not where they end. A page
            # holds roughly 4,000 characters in two columns, so this covers
            # the article and a little past it. Overshooting is harmless:
            # the decision is made by what is printed in the box, so a box
            # belonging to the next article is still judged correctly.
            span = 1 + min(6, len(entry.get("body", "")) // 4000)
            out.append({"headword": entry.get("headword", ""),
                        "pdf_page": start_page,
                        "pages": list(range(start_page, start_page + span)),
                        "scan": scan, "other": other})
    return out


def boxes_for(words_dir: Path, pages: list[int]) -> dict[int, dict[str, list[tuple]]]:
    """Word boxes on the given pages, grouped by the word's letters."""
    out: dict[int, dict[str, list[tuple]]] = {}
    for page in pages:
        path = words_dir / f"p{page:04d}.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("failed"):
            continue
        grouped: dict[str, list[tuple]] = defaultdict(list)
        for text, left, top, width, height, *_rest in data.get("words", []):
            grouped[core_of(text)].append((left, top, width, height, text))
        out[page] = grouped
    return out


def read_page(args: tuple[str, int, list, str]) -> list[dict]:
    """Crop and re-read each target on one page. Cached, so a run can resume."""
    pdf_path, pdf_page, targets, work_dir = args
    if not targets:
        return []

    from PIL import Image

    work = Path(work_dir)
    part = work / "parts" / f"p{pdf_page:04d}.json"
    if part.exists():
        try:
            return json.loads(part.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    work.mkdir(parents=True, exist_ok=True)
    stem = work / f"a{pdf_page:04d}"
    result = subprocess.run(
        ["pdftoppm", "-r", str(REREAD_DPI), "-gray", "-png",
         "-f", str(pdf_page), "-l", str(pdf_page), pdf_path, str(stem)],
        capture_output=True, text=True)
    produced = sorted(work.glob(f"a{pdf_page:04d}*.png"))
    if result.returncode != 0 or not produced:
        return []

    image = Image.open(produced[0]).convert("L")
    page_width, page_height = image.size
    out = []
    for left, top, width, height, text, scan, other in targets:
        box = (max(0, int(left * SCALE) - PAD), max(0, int(top * SCALE) - PAD),
               min(page_width, int((left + width) * SCALE) + PAD),
               min(page_height, int((top + height) * SCALE) + PAD))
        if box[2] - box[0] < 12 or box[3] - box[1] < 12:
            continue
        crop = image.crop(box)
        crop = crop.resize((crop.width * UPSCALE, crop.height * UPSCALE), Image.LANCZOS)
        crop_path = work / f"c{pdf_page:04d}_{left}_{top}.png"
        crop.save(crop_path)
        read = subprocess.run(
            ["tesseract", str(crop_path), "stdout", "--psm", "8", "-l", "eng"],
            capture_output=True, text=True)
        crop_path.unlink(missing_ok=True)
        if read.returncode != 0:
            continue
        out.append({"pdf_page": pdf_page, "left": left, "top": top,
                    "was": text, "scan": scan, "other": other,
                    "ink": " ".join(read.stdout.split()).strip()})

    produced[0].unlink(missing_ok=True)
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf")
    parser.add_argument("--out", default="build/full2")
    parser.add_argument("--reference", default="build/reference/mackey1874.txt")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--pages", default="", help="e.g. 1-400, to run in parts")
    options = parser.parse_args()

    out_dir = Path(options.out)
    entries = json.loads((out_dir / "entries.json").read_text(encoding="utf-8"))["entries"]
    reference = ref.load(Path(options.reference))

    found = disagreements(entries, reference)
    print(f"{len(found)} single-word disagreements between the two printings")

    # Map each disagreement onto the word box it came from. An article can run
    # over several pages, so all of its pages are searched; a word that was
    # broken across a line and rejoined has no box of its own and is skipped
    # here -- the whole-book lexicon pass is what catches those.
    words_dir = out_dir / "words"
    by_page: dict[int, list] = defaultdict(list)
    seen: set[tuple] = set()
    unplaced = 0

    # A word the book uses constantly is not what this is for: a disagreement
    # on "and" or "the" is the alignment slipping a notch, and chasing every
    # box that holds one would mean re-reading tens of thousands of words to
    # learn nothing.
    common = Counter()
    for entry in entries:
        common.update(ref.words_of(entry.get("body", "")))
    found = [item for item in found if common[item["scan"]] < 100]
    print(f"{len(found)} after dropping disagreements on the book's commonest words")

    seen_pairs: set[tuple] = set()
    for item in found:
        pair = (item["headword"], item["scan"], item["other"])
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        pages = [p for p in (item["pages"] or []) if isinstance(p, int)]
        if not pages:
            continue
        grouped = boxes_for(words_dir, pages)
        hits = 0
        for page in pages:
            for left, top, width, height, text in grouped.get(page, {}).get(item["scan"], []):
                key = (page, left, top)
                if key in seen:
                    continue
                seen.add(key)
                by_page[page].append((left, top, width, height, text,
                                      item["scan"], item["other"]))
                hits += 1
                # Three candidate boxes is enough: each is judged on its own
                # ink, so picking the occurrence the alignment meant is not
                # necessary for the verdict to be right.
                if hits >= 3:
                    break
            if hits >= 3:
                break
        unplaced += (hits == 0)
    total = sum(len(v) for v in by_page.values())
    print(f"{total} of them found on the page; {unplaced} had no word box of their own")

    first, last = 0, 10 ** 6
    if options.pages:
        bounds = options.pages.split("-")
        first, last = int(bounds[0]), int(bounds[-1])
    jobs = [(options.pdf, page, targets, str(out_dir / "adjudicate"))
            for page, targets in sorted(by_page.items()) if first <= page <= last]
    print(f"{len(jobs)} pages to read")

    started = time.time()
    done = 0
    with ProcessPoolExecutor(max_workers=options.workers) as pool:
        for _ in pool.map(read_page, jobs):
            done += 1
            if done % 50 == 0:
                rate = done / (time.time() - started)
                print(f"  {done}/{len(jobs)} pages  "
                      f"{(len(jobs) - done) / max(rate, 0.01) / 60:.1f} min left", flush=True)

    readings = []
    for part in sorted((out_dir / "adjudicate" / "parts").glob("p*.json")):
        try:
            readings.extend(json.loads(part.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue

    verdicts = Counter()
    fixes = []
    unresolved = []
    for record in readings:
        ink = core_of(record["ink"])
        if ink == record["scan"]:
            verdicts["scan was right"] += 1
        elif ink == record["other"]:
            if (record["scan"], record["other"]) in NEVER:
                verdicts["both misread it the same way"] += 1
                unresolved.append(record)
                continue
            verdicts["1874 was right"] += 1
            fixes.append({"pdf_page": record["pdf_page"], "left": record["left"],
                          "top": record["top"], "was": record["was"],
                          "now": _respell(record["was"], record["other"])})
        else:
            verdicts["ink says neither"] += 1
            unresolved.append(record)

    for verdict, count in verdicts.most_common():
        print(f"  {verdict}: {count}")

    (out_dir / "adjudicated.json").write_text(
        json.dumps({"fixes": fixes, "unresolved": unresolved,
                    "verdicts": dict(verdicts)}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"wrote {len(fixes)} corrections, {len(unresolved)} left for a human")
    return 0


def _respell(token: str, letters: str) -> str:
    """Put the decided letters into the token, keeping its punctuation and case."""
    import re
    core = re.compile(r"[A-Za-zÀ-ɏ]+")

    def shaped(match: re.Match[str]) -> str:
        found = match.group(0)
        if found.isupper() and len(found) > 1:
            return letters.upper()
        if found[:1].isupper():
            return letters[:1].upper() + letters[1:]
        return letters

    return core.sub(shaped, token, count=1)


if __name__ == "__main__":
    raise SystemExit(main())
