#!/usr/bin/env python3
"""Phase 1: run the extraction pipeline over a sample of pages.

    python3 -I pipeline/run_spike.py SOURCE.pdf --out build/spike

Writes entries.json, issues.json, report.txt and the page images, so the
extraction can be judged against the originals before committing to the full
946-page run.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.extract.ocr import ExtractionError, read_page
from pipeline.parse import regions
from pipeline.parse.entries import parse_page
from pipeline.validate import checks

# 30 pages: a spread across the main dictionary, plus every hard case I know of.
SPIKE_PAGES: dict[int, str] = {
    11:  "first page of A",
    54:  "no text in the 2007 layer - plate?",
    71:  "normal, several short entries",
    85:  "no text in the 2007 layer - plate?",
    100: "normal; ground truth hand-checked",
    161: "normal",
    191: "dense, many short entries",
    200: "run of 'Cross, ...' entries",
    282: "dense, many short entries",
    300: "normal",
    372: "normal",
    400: "KNIGHTS - multi-page entry, no headword expected",
    401: "KNIGHTS - continuation",
    432: "dense",
    440: "very dense - 17 headwords",
    445: "volume boundary; no 2007 text layer from here on",
    446: "just past the volume boundary",
    462: "normal",
    500: "long NAMES entry, single headword",
    522: "table page - known false-positive source",
    582: "normal",
    600: "normal",
    642: "normal",
    700: "normal",
    763: "normal",
    800: "TREE-WORSHIP, long entry",
    853: "normal, late Z-approach",
    883: "last page of Z",
    885: "Pronouncing Dictionary - three-column table",
    930: "Bibliography",
}


def process(args: tuple[str, int, str]) -> dict:
    pdf_path, pdf_page, image_dir = args
    started = time.time()
    try:
        page = read_page(Path(pdf_path), pdf_page, Path(image_dir))
    except ExtractionError as error:
        return {"pdf_page": pdf_page, "failed": str(error), "entries": [],
                "seconds": time.time() - started}

    head = regions.find_running_head(page)
    region = regions.classify(page, head)
    entries = parse_page(page, head, region) if region in (regions.REGION_MAIN,) else []

    return {
        "pdf_page": pdf_page,
        "region": region,
        "printed_page": head.printed_page,
        "running_head": head.raw,
        "guides": [head.left_guide, head.right_guide],
        "words": len(page.words),
        "bold_words": sum(1 for w in page.words if w.bold),
        "median_stroke": round(page.median_stroke, 2),
        "gutter_x": page.gutter_x,
        "mean_conf": round(page.mean_conf, 1),
        "image": Path(page.image_path).name,
        "entries": [e.as_dict() for e in entries],
        "seconds": round(time.time() - started, 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", help="source PDF")
    parser.add_argument("--out", default="build/spike", help="output directory")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--pages", help="comma-separated page list, overriding the spike set")
    options = parser.parse_args()

    out_dir = Path(options.out)
    image_dir = out_dir / "pages"
    out_dir.mkdir(parents=True, exist_ok=True)
    image_dir.mkdir(parents=True, exist_ok=True)

    if options.pages:
        pages = [int(p) for p in options.pages.split(",")]
    else:
        pages = sorted(SPIKE_PAGES)

    print(f"Running {len(pages)} pages with {options.workers} workers...")
    started = time.time()
    tasks = [(options.pdf, page, str(image_dir)) for page in pages]
    with ProcessPoolExecutor(max_workers=options.workers) as pool:
        results = list(pool.map(process, tasks))
    results.sort(key=lambda r: r["pdf_page"])
    elapsed = time.time() - started

    from pipeline.parse.entries import Entry
    flat: list[Entry] = []
    for result in results:
        for raw in result["entries"]:
            flat.append(Entry(
                headword=raw["headword"], body=raw["body"], pdf_page=raw["pdf_page"],
                printed_page=raw["printed_page"], region=raw["region"],
                confidence=raw["confidence"], is_continuation=raw["is_continuation"],
                issues=raw["issues"],
            ))

    issues = checks.check(flat)
    summary = checks.summarise(flat, issues)
    summary["pages"] = len(pages)
    summary["seconds"] = round(elapsed, 1)
    summary["seconds_per_page"] = round(elapsed / max(len(pages), 1), 2)

    (out_dir / "entries.json").write_text(
        json.dumps({"summary": summary, "pages": results}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    (out_dir / "issues.json").write_text(
        json.dumps([i.as_dict() for i in issues], indent=2, ensure_ascii=False),
        encoding="utf-8")

    lines = [
        "PHASE 1 EXTRACTION SPIKE",
        "=" * 70,
        f"pages            {summary['pages']}",
        f"entries          {summary['entries']}",
        f"continuations    {summary['continuations']}",
        f"mean OCR conf    {summary['mean_confidence']}%",
        f"errors           {summary['errors']}",
        f"warnings         {summary['warnings']}",
        f"time             {summary['seconds']}s ({summary['seconds_per_page']}s/page)",
        "",
        "PER PAGE",
        "-" * 70,
    ]
    for result in results:
        if result.get("failed"):
            lines.append(f"  p{result['pdf_page']:<5} FAILED  {result['failed']}")
            continue
        note = SPIKE_PAGES.get(result["pdf_page"], "")
        real = sum(1 for e in result["entries"] if not e["is_continuation"])
        lines.append(
            f"  p{result['pdf_page']:<5} printed={str(result['printed_page']):>5}  "
            f"{result['region']:<13} entries={real:<3} conf={result['mean_conf']:<5} "
            f"head={result['running_head'][:30]!r}  {note}")
    report = "\n".join(lines)
    (out_dir / "report.txt").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
