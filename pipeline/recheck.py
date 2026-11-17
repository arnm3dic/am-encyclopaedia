#!/usr/bin/env python3
"""Re-read every headword from the page images at higher resolution.

    python3 -I pipeline/recheck.py SOURCE.pdf --out build/full2 --limit 200

The first pass OCRs a whole page at 300 dpi with automatic layout analysis,
which is the right setting for finding columns and paragraphs but not the best
one for reading six words accurately. Here each headword is located from that
pass, cropped, rendered at 600 dpi and read again in single-line mode.

Two independent readings of the same ink is a far better test than any
dictionary. The book is a mixture of American and archaic British spelling --
`practise` outnumbers `practice` 109 to 24, `sepulcher` outnumbers `sepulchre`
30 to 4, and `antient`, `connexion` and `shew` all appear -- so a modern word
list would reject correct text as readily as wrong text. Where the two
readings agree the headword stands. Where they differ, that is reported.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.extract.ocr import ExtractionError, page_from_dict
from pipeline.parse import regions
from pipeline.parse.entries import (MAX_HEADWORD_WORDS, TERMINATES, HEADWORD_START,
                                    _extend_backwards, _follows_sentence_end,
                                    _is_abbreviation, _join_lines, reading_order)
from pipeline.parse.normalise import normalise

RECHECK_DPI = 600
SCALE = RECHECK_DPI / 300          # cached boxes are in 300 dpi pixels
PAD = 10                           # padding around the crop, in 600 dpi pixels


def headword_boxes(page, head) -> list[tuple[str, tuple[int, int, int, int]]]:
    """Each headword on the page with the box that encloses it."""
    words = reading_order(page, head)
    if not words:
        return []

    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(words):
        word = words[index]
        if not word.bold or not HEADWORD_START.match(word.text):
            index += 1
            continue
        if word.text.isupper() and len(word.text) > 3:
            index += 1
            continue
        end = None
        for offset in range(MAX_HEADWORD_WORDS):
            position = index + offset
            if position >= len(words):
                break
            candidate = words[position]
            if offset > 0 and candidate.line - words[position - 1].line > 1:
                break
            if not candidate.text.rstrip().endswith(TERMINATES):
                continue
            following = words[position + 1] if position + 1 < len(words) else None
            if _is_abbreviation(candidate.text) and following is not None:
                continue
            end = position
            break
        if end is None:
            index += 1
            continue
        bold_count = sum(1 for w in words[index:end + 1] if w.bold)
        if bold_count < max(1, (end - index + 1) // 2):
            index += 1
            continue
        start = _extend_backwards(words, index, page.loose_threshold)
        if spans and start <= spans[-1][1]:
            start = index
        if _follows_sentence_end(words, start):
            spans.append((start, end))
        index = end + 1

    out = []
    for start, end in spans:
        group = words[start:end + 1]
        # A headword that wraps a line cannot be cropped as one box.
        if len({w.line for w in group}) > 1:
            continue
        left = min(w.left for w in group)
        top = min(w.top for w in group)
        right = max(w.right for w in group)
        bottom = max(w.bottom for w in group)
        out.append((_join_lines(group), (left, top, right, bottom)))
    return out


def reread(args: tuple[str, int, str]) -> list[dict]:
    pdf_path, pdf_page, words_dir = args
    cached = Path(words_dir) / f"p{pdf_page:04d}.json"
    data = json.loads(cached.read_text(encoding="utf-8"))
    if data.get("failed") or not data.get("words"):
        return []

    page = page_from_dict(data)
    head = regions.find_running_head(page)
    if regions.classify(page, head) != regions.REGION_MAIN:
        return []
    targets = headword_boxes(page, head)
    if not targets:
        return []

    work = Path(words_dir).parent / "recheck_tmp"
    work.mkdir(parents=True, exist_ok=True)
    stem = work / f"hi{pdf_page:04d}"
    result = subprocess.run(
        ["pdftoppm", "-r", str(RECHECK_DPI), "-gray", "-png",
         "-f", str(pdf_page), "-l", str(pdf_page), pdf_path, str(stem)],
        capture_output=True, text=True)
    if result.returncode != 0:
        return []
    produced = sorted(work.glob(f"hi{pdf_page:04d}*.png"))
    if not produced:
        return []
    image_path = produced[0]

    from PIL import Image
    image = Image.open(image_path).convert("L")
    width, height = image.size

    out = []
    for original, (left, top, right, bottom) in targets:
        box = (max(0, int(left * SCALE) - PAD), max(0, int(top * SCALE) - PAD),
               min(width, int(right * SCALE) + PAD), min(height, int(bottom * SCALE) + PAD))
        if box[2] - box[0] < 10 or box[3] - box[1] < 10:
            continue
        crop_path = work / f"c{pdf_page:04d}_{box[0]}_{box[1]}.png"
        image.crop(box).save(crop_path)
        # --psm 7 reads the crop as a single line, which is what it is.
        read = subprocess.run(
            ["tesseract", str(crop_path), "stdout", "--psm", "7", "-l", "eng"],
            capture_output=True, text=True)
        crop_path.unlink(missing_ok=True)
        if read.returncode != 0:
            continue
        second = " ".join(read.stdout.split()).strip()
        out.append({
            "pdf_page": pdf_page,
            "first": original,
            "second": second,
            "agree": normalise(original) == normalise(second),
        })

    image_path.unlink(missing_ok=True)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf")
    parser.add_argument("--out", default="build/full2")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--limit", type=int, default=0)
    options = parser.parse_args()

    out_dir = Path(options.out)
    words_dir = out_dir / "words"
    target = out_dir / "recheck.json"

    done: dict[str, list] = {}
    if target.exists():
        done = json.loads(target.read_text(encoding="utf-8"))

    pages = sorted(int(p.stem[1:]) for p in words_dir.glob("p*.json"))
    todo = [p for p in pages if str(p) not in done]
    if options.limit:
        todo = todo[: options.limit]
    if not todo:
        total = sum(len(v) for v in done.values())
        disagree = sum(1 for v in done.values() for r in v if not r["agree"])
        print(json.dumps({"headwords_rechecked": total, "disagreements": disagree,
                          "pages": len(done)}, indent=2))
        return 0

    print(f"{len(done)}/{len(pages)} pages done. Re-reading {len(todo)} "
          f"({todo[0]}-{todo[-1]})...", flush=True)
    started = time.time()
    tasks = [(options.pdf, page, str(words_dir)) for page in todo]
    with ProcessPoolExecutor(max_workers=options.workers) as pool:
        for index, (page, rows) in enumerate(zip(todo, pool.map(reread, tasks)), 1):
            done[str(page)] = rows
            if index % 50 == 0:
                rate = (time.time() - started) / index
                print(f"  {index}/{len(todo)}  {rate:.2f}s/page", flush=True)

    target.write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")
    elapsed = time.time() - started
    checked = sum(len(v) for v in done.values())
    disagree = sum(1 for v in done.values() for r in v if not r["agree"])
    print(f"Done in {elapsed/60:.1f} min. {checked} headwords read twice, "
          f"{disagree} disagreements. {len(pages)-len(done)} pages remain.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
