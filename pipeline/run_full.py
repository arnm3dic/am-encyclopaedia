#!/usr/bin/env python3
"""Phase 2: extract the whole book.

The run takes about three quarters of an hour, so it checkpoints: each page is
cached as its own JSON file and a second invocation skips what is already done.
Use --limit to work through the book in sessions.

    python3 -I pipeline/run_full.py SOURCE.pdf --out build/full --limit 200
    python3 -I pipeline/run_full.py SOURCE.pdf --out build/full --aggregate

Page images are deleted after each page is parsed unless --keep-images is
given: at 300 dpi the full book is about a gigabyte of PNGs, and they are
regenerable from the PDF in under a second each.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Tesseract parallelises internally with OpenMP. With one worker process per
# core, those threads contend; pinning each process to a single thread is
# faster overall.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

from pipeline.extract.ocr import (ExtractionError, page_from_dict, page_to_dict,
                                  read_page)
from pipeline.parse import regions
from pipeline.parse.entries import Entry, parse_page
from pipeline.validate import checks


def page_count(pdf_path: Path) -> int:
    out = subprocess.run(["pdfinfo", str(pdf_path)], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith("Pages:"):
            return int(line.split()[-1])
    raise ExtractionError("could not read page count from pdfinfo")


def ocr_one(args: tuple[str, int, str, str, bool]) -> dict:
    """Stage 1: OCR a page and cache its words. The expensive half."""
    pdf_path, pdf_page, words_dir, image_dir, keep_images = args
    target = Path(words_dir) / f"p{pdf_page:04d}.json"
    try:
        page = read_page(Path(pdf_path), pdf_page, Path(image_dir))
    except ExtractionError as error:
        record = {"pdf_page": pdf_page, "failed": str(error), "words": [],
                  "width": 0, "height": 0, "gutter_x": 0, "median_stroke": 0.0,
                  "p75_stroke": 0.0, "mean_conf": 0.0}
        target.write_text(json.dumps(record), encoding="utf-8")
        return record

    record = page_to_dict(page)
    target.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    if not keep_images:
        try:
            Path(page.image_path).unlink()
        except OSError:
            pass
    return record


def parse_one(path: Path) -> dict:
    """Stage 2: parse one cached page. Cheap, so it is re-run freely."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("failed"):
        return {"pdf_page": data["pdf_page"], "region": "failed",
                "failed": data["failed"], "entries": []}

    page = page_from_dict(data)
    head = regions.find_running_head(page)
    region = regions.classify(page, head)
    entries = parse_page(page, head, region) if region == regions.REGION_MAIN else []
    return {
        "pdf_page": page.pdf_page,
        "region": region,
        "printed_page": head.printed_page,
        "running_head": head.raw,
        "guides": [head.left_guide, head.right_guide],
        "words": len(page.words),
        "bold_words": sum(1 for w in page.words if w.bold),
        "median_stroke": round(page.median_stroke, 2),
        "p75_stroke": round(page.p75_stroke, 2),
        "bold_threshold": round(page.bold_threshold, 2),
        "mean_conf": round(page.mean_conf, 1),
        "entries": [e.as_dict() for e in entries],
    }


def stitch(records: list[dict]) -> list[Entry]:
    """Join continuations onto the entry they belong to.

    An article may run across a column break, a page break, or several pages
    (KNIGHTS covers three). Text before the first headword on a page continues
    the last entry seen, so appending it there reassembles the whole article.
    Continuations with nothing before them -- the very first page of a region,
    or after a plate -- are dropped, having nothing to attach to.
    """
    entries: list[Entry] = []
    for record in sorted(records, key=lambda r: r["pdf_page"]):
        for raw in record.get("entries", []):
            if raw.get("rejected"):
                continue      # carried separately, for the correction pass
            if raw["is_continuation"]:
                if entries and raw["body"]:
                    previous = entries[-1]
                    previous.body = f"{previous.body} {raw['body']}".strip()
                    if raw["pdf_page"] != previous.pdf_page and "spans_pages" not in previous.issues:
                        previous.issues.append("spans_pages")
                continue
            entries.append(Entry(
                headword=raw["headword"], body=raw["body"], pdf_page=raw["pdf_page"],
                printed_page=raw["printed_page"], region=raw["region"],
                confidence=raw["confidence"], is_continuation=False,
                issues=list(raw["issues"]),
            ))
    return entries


def interpolate_folios(records: list[dict]) -> int:
    """Fill printed page numbers the running head did not yield.

    The offset between PDF and printed page is locally constant but drifts
    across the book, so a missing folio is recovered from its neighbours rather
    than from a single global offset. Returns how many were filled.
    """
    ordered = sorted(records, key=lambda r: r["pdf_page"])
    known = [(r["pdf_page"], r["printed_page"]) for r in ordered
             if isinstance(r.get("printed_page"), int)]
    if not known:
        return 0
    filled = 0
    for record in ordered:
        if isinstance(record.get("printed_page"), int):
            continue
        if record.get("region") in (regions.REGION_PLATE, None):
            continue
        pdf_page = record["pdf_page"]
        nearest = min(known, key=lambda pair: abs(pair[0] - pdf_page))
        if abs(nearest[0] - pdf_page) <= 6:
            record["printed_page"] = nearest[1] + (pdf_page - nearest[0])
            record["folio_interpolated"] = True
            filled += 1
    return filled


def aggregate(out_dir: Path) -> dict:
    words_dir = out_dir / "words"
    records = [parse_one(p) for p in sorted(words_dir.glob("p*.json"))]
    interpolated = interpolate_folios(records)

    # Push interpolated folios down onto the entries themselves.
    folio_by_page = {r["pdf_page"]: r.get("printed_page") for r in records}
    for record in records:
        for raw in record.get("entries", []):
            if raw.get("printed_page") is None:
                raw["printed_page"] = folio_by_page.get(record["pdf_page"])

    entries = stitch(records)
    issues = checks.check(entries)
    summary = checks.summarise(entries, issues)

    candidates = [raw for record in sorted(records, key=lambda r: r["pdf_page"])
                  for raw in record.get("entries", []) if raw.get("rejected")]
    (out_dir / "candidates.json").write_text(
        json.dumps(candidates, indent=2, ensure_ascii=False), encoding="utf-8")
    summary["rejected_candidates"] = len(candidates)

    regions_count: dict[str, int] = {}
    for record in records:
        key = record.get("region", "failed")
        regions_count[key] = regions_count.get(key, 0) + 1

    letters: dict[str, int] = {}
    for entry in entries:
        letters[entry.as_dict()["letter"]] = letters.get(entry.as_dict()["letter"], 0) + 1

    summary.update({
        "pages_processed": len(records),
        "regions": regions_count,
        "folios_interpolated": interpolated,
        "letters": dict(sorted(letters.items())),
        "multi_page_entries": sum(1 for e in entries
                                  if "spans_pages" in e.issues),
        "total_body_chars": sum(len(e.body) for e in entries),
    })

    (out_dir / "entries.json").write_text(
        json.dumps({"summary": summary, "entries": [e.as_dict() for e in entries]},
                   indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "issues.json").write_text(
        json.dumps([i.as_dict() for i in issues], indent=2, ensure_ascii=False),
        encoding="utf-8")
    (out_dir / "pages.json").write_text(
        json.dumps(records, ensure_ascii=False), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf")
    parser.add_argument("--out", default="build/full")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--limit", type=int, default=0, help="pages to do this session")
    parser.add_argument("--aggregate", action="store_true", help="aggregate and stop")
    parser.add_argument("--keep-images", action="store_true")
    options = parser.parse_args()

    out_dir = Path(options.out)
    words_dir = out_dir / "words"
    image_dir = out_dir / "images"
    for directory in (out_dir, words_dir, image_dir):
        directory.mkdir(parents=True, exist_ok=True)

    total = page_count(Path(options.pdf))
    done = {int(p.stem[1:]) for p in words_dir.glob("p*.json")}
    todo = [n for n in range(1, total + 1) if n not in done]

    if options.aggregate or not todo:
        summary = aggregate(out_dir)
        print(json.dumps(summary, indent=2)[:1800])
        print(f"\n{len(done)}/{total} pages in the word cache.")
        return 0

    batch = todo[: options.limit] if options.limit else todo
    print(f"{len(done)}/{total} done. OCR of {len(batch)} pages "
          f"({batch[0]}-{batch[-1]}) with {options.workers} workers...", flush=True)

    started = time.time()
    tasks = [(options.pdf, n, str(words_dir), str(image_dir), options.keep_images)
             for n in batch]
    with ProcessPoolExecutor(max_workers=options.workers) as pool:
        for index, _ in enumerate(pool.map(ocr_one, tasks), 1):
            if index % 25 == 0:
                rate = (time.time() - started) / index
                print(f"  {index}/{len(batch)}  {rate:.2f}s/page", flush=True)

    elapsed = time.time() - started
    remaining = len(todo) - len(batch)
    print(f"Batch done in {elapsed/60:.1f} min ({elapsed/len(batch):.2f}s/page). "
          f"{remaining} pages remain.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
