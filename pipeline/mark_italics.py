#!/usr/bin/env python3
"""Add italic flags to the cached words.

    python3 -I pipeline/mark_italics.py SOURCE.pdf --out build/full2 --limit 400

Re-renders each page and measures the slant of every word long enough to carry
the signal, then writes the flags back into the word cache. No OCR is involved,
so this is far cheaper than the original pass.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from PIL import Image

from pipeline.extract.ocr import (ExtractionError, INK_THRESHOLD, page_from_dict,
                                  page_to_dict, rasterize)
from pipeline.extract.italics import mark_italics


def process(args: tuple[str, int, str, str]) -> tuple[int, int]:
    pdf_path, pdf_page, words_dir, image_dir = args
    cached = Path(words_dir) / f"p{pdf_page:04d}.json"
    data = json.loads(cached.read_text(encoding="utf-8"))
    if data.get("failed") or not data.get("words"):
        return (pdf_page, 0)

    try:
        image_path = rasterize(Path(pdf_path), pdf_page, Path(image_dir))
    except ExtractionError:
        return (pdf_page, 0)

    page = page_from_dict(data)
    ink = np.array(Image.open(image_path).convert("L")) < INK_THRESHOLD
    count = mark_italics(page, ink)

    # page_to_dict carries the flag; everything else is unchanged.
    cached.write_text(json.dumps(page_to_dict(page), ensure_ascii=False),
                      encoding="utf-8")
    try:
        image_path.unlink()
    except OSError:
        pass
    return (pdf_page, count)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf")
    parser.add_argument("--out", default="build/full2")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--limit", type=int, default=0)
    options = parser.parse_args()

    out_dir = Path(options.out)
    words_dir = out_dir / "words"
    image_dir = out_dir / "italic_tmp"
    image_dir.mkdir(parents=True, exist_ok=True)
    marker = out_dir / "italics_done.json"

    done = set(json.loads(marker.read_text())) if marker.exists() else set()
    pages = sorted(int(p.stem[1:]) for p in words_dir.glob("p*.json"))
    todo = [p for p in pages if p not in done]
    if options.limit:
        todo = todo[: options.limit]

    if not todo:
        print(f"all {len(pages)} pages marked")
        return 0

    print(f"{len(done)}/{len(pages)} done. Marking {len(todo)} "
          f"({todo[0]}-{todo[-1]})...", flush=True)
    started = time.time()
    tasks = [(options.pdf, page, str(words_dir), str(image_dir)) for page in todo]
    total = 0
    with ProcessPoolExecutor(max_workers=options.workers) as pool:
        for index, (page, count) in enumerate(pool.map(process, tasks), 1):
            done.add(page)
            total += count
            if index % 100 == 0:
                print(f"  {index}/{len(todo)}  {(time.time()-started)/index:.2f}s/page",
                      flush=True)

    marker.write_text(json.dumps(sorted(done)))
    elapsed = time.time() - started
    print(f"Done in {elapsed/60:.1f} min. {total} italic words on these pages. "
          f"{len(pages)-len(done)} pages remain.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
