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
from collections import Counter
from functools import lru_cache
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Tesseract parallelises internally with OpenMP. With one worker process per
# core, those threads contend; pinning each process to a single thread is
# faster overall.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

from pipeline.extract.ocr import (ExtractionError, page_from_dict, page_to_dict,
                                  read_page)
from pipeline.corrections import body_text, ocr_fixes, triage
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


@lru_cache(maxsize=4)
def _word_fixes(out_dir: str) -> dict[tuple[int, int, int], tuple[str, str]]:
    """Corrections from the 600 dpi re-read, keyed by the word's own box.

    They are applied to the page as it is parsed rather than to the cached OCR
    output, which stays exactly as the first pass left it. That means a
    correction reaches the headword, the cross-references and the search index
    as well as the body text, and that deleting one file undoes all of it.
    """
    path = Path(out_dir) / "word_fixes.json"
    if not path.exists():
        return {}
    out = {}
    for fix in json.loads(path.read_text(encoding="utf-8")):
        out[(fix["pdf_page"], fix["left"], fix["top"])] = (fix["was"], fix["now"])
    return out


def parse_one(path: Path) -> dict:
    """Stage 2: parse one cached page. Cheap, so it is re-run freely."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("failed"):
        return {"pdf_page": data["pdf_page"], "region": "failed",
                "failed": data["failed"], "entries": []}

    page = page_from_dict(data)

    fixes = _word_fixes(str(path.parent.parent))
    if fixes:
        for word in page.words:
            found = fixes.get((page.pdf_page, word.left, word.top))
            # The `was` check means a stale correction file cannot silently
            # rewrite a word it was never about.
            if found and word.text == found[0]:
                word.text = found[1]
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
        "entries": [dict(e.as_dict(), page_has_guides=bool(head.left_guide and head.right_guide))
                    for e in entries],
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
    """Repair and fill the printed page numbers.

    The folio is read off the running head, so it carries the same OCR errors
    as everything else: a stray mark adds a digit (page 841 read as 8387), a
    faint one loses it (440 read as 44), and the unnumbered front matter picks
    up numbers from nowhere at all (1877 and up).

    The offset between the printed and the PDF page number is piecewise
    constant: it slips by one at every unnumbered plate, and once, between PDF
    pages 346 and 347, it jumps by twenty-eight, where the scan skips a stretch
    the printing numbered. Within a run the neighbours say what a folio should
    be.

    Two things this has to get right, both learned the hard way.

    The offsets are taken from a snapshot, never from the record being
    rewritten. An earlier version read and wrote the same field as it walked
    the book, so a repaired folio fed the next window, and a single bad patch
    marched a constant error through hundreds of pages -- 363 of the 760 pages
    that carry a legible folio ended up disagreeing with their own running
    head, in runs with tidy deltas of -27, +3 and +15.

    And the local offset is the commonest value in the window, not the median.
    At the jump a window straddles two runs, and the median of two clusters
    lands between them, on a value no page has; the mode takes whichever run
    the page is actually in.
    """
    ordered = sorted((r for r in records if r.get("region") == regions.REGION_MAIN),
                     key=lambda r: r["pdf_page"])
    if not ordered:
        return 0

    # The snapshot: what the running heads said, before anything is rewritten.
    raw: list[int | None] = []
    for record in ordered:
        folio = record.get("printed_page")
        raw.append(folio - record["pdf_page"]
                   if isinstance(folio, int) and 1 <= folio <= 1200 else None)

    window = 12
    offsets: list[int | None] = []
    for index in range(len(ordered)):
        near = [o for o in raw[max(0, index - window): index + window + 1] if o is not None]
        if not near:
            offsets.append(None)
            continue
        counts = Counter(near).most_common()
        offsets.append(counts[0][0] if counts[0][1] >= 3 else None)

    # A gap with no agreeing neighbours borrows the nearest run's offset.
    for index, offset in enumerate(offsets):
        if offset is not None:
            continue
        for step in range(1, len(offsets)):
            for probe in (index - step, index + step):
                if 0 <= probe < len(offsets) and offsets[probe] is not None:
                    offsets[index] = offsets[probe]
                    break
            if offsets[index] is not None:
                break

    changed = 0
    for index, record in enumerate(ordered):
        offset = offsets[index]
        if offset is None:
            continue
        expected = record["pdf_page"] + offset
        folio = record.get("printed_page")
        if isinstance(folio, int) and abs(folio - expected) <= 1 and 1 <= folio <= 1200:
            continue
        record["printed_page"] = expected if expected >= 1 else None
        record["folio_repaired"] = True
        changed += 1

    # Front matter and plates carry no folio of their own.
    for record in records:
        if record.get("region") != regions.REGION_MAIN:
            record["printed_page"] = None
    return changed


def merge_false_splits(entries: list) -> int:
    """Rejoin articles that a phantom headword cut in two.

    A bold fragment mid-article -- "It.", "In the.", "I. WILL." -- opens what
    looks like a new entry, and everything after it is attributed to that
    fragment instead of to the article it belongs to. On page 498 one such
    fragment held 14,262 characters of the article on the Name of God.

    The marks of a false split are that the headword repeats one seen earlier
    and that it breaks alphabetical order. Those are merged back into the
    entry above, text and all, since the headword itself was only ever part of
    a sentence.
    """
    from pipeline.parse.normalise import sort_key

    merged = 0
    keep: list = []
    seen: set[str] = set()
    previous_key = ""
    for entry in entries:
        key = sort_key(entry.headword)
        repeat = key in seen
        out_of_order = bool(previous_key) and key < previous_key
        if repeat and out_of_order and keep:
            host = keep[-1]
            tail = f"{entry.headword} {entry.body}".strip()
            host.body = f"{host.body} {tail}".strip()
            if "merged_false_split" not in host.issues:
                host.issues.append("merged_false_split")
            merged += 1
            continue
        keep.append(entry)
        seen.add(key)
        previous_key = key
    entries[:] = keep
    return merged


def drop_false_headwords(entries: list) -> list:
    """Remove entries that have no definition and sit out of alphabetical order.

    A dictionary entry with no text is of no use to a reader, and one that also
    breaks the ordering is a bold word mistaken for a headword rather than an
    article whose body went astray -- "Bn.", "Ha.", "In the." Entries with an
    empty body that are correctly ordered are kept and flagged, since those are
    real headwords whose text needs recovering.
    """
    from pipeline.parse.normalise import sort_key

    keep: list = []
    previous_key = ""
    for entry in entries:
        empty = not entry.body.strip()
        key = sort_key(entry.headword)
        out_of_order = bool(previous_key) and key < previous_key
        if empty and out_of_order:
            continue
        keep.append(entry)
        previous_key = key
    return keep


def aggregate(out_dir: Path, correct: bool = True) -> dict:
    words_dir = out_dir / "words"
    records = [parse_one(p) for p in sorted(words_dir.glob("p*.json"))]
    interpolated = interpolate_folios(records)

    # Phase 3: decide the held-back candidates and repair headword misreads,
    # both against alphabetical order, before anything else is computed.
    decisions: list = []
    fixes: list = []
    promoted = 0
    if correct:
        sequence = [raw for record in sorted(records, key=lambda r: r["pdf_page"])
                    for raw in record.get("entries", [])]
        # Strip marginal marks before the overrides are matched: an override
        # keys on the headword as printed, and "L. H.] Seald Miserables."
        # does not match "Seald Miserables." until the mark is gone.
        fixes += ocr_fixes.strip_artifacts(sequence)
        overrides_path = Path(__file__).resolve().parent / "corrections" / "overrides.json"
        if overrides_path.exists():
            overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
            fixes += ocr_fixes.apply_overrides(sequence, overrides)
        decisions, promoted = triage.triage(sequence)
        fixes += ocr_fixes.repair(sequence)

        (out_dir / "decisions.json").write_text(
            json.dumps([d.as_dict() for d in decisions], indent=2, ensure_ascii=False),
            encoding="utf-8")
        (out_dir / "fixes.json").write_text(
            json.dumps([f.as_dict() for f in fixes], indent=2, ensure_ascii=False),
            encoding="utf-8")

    # Push interpolated folios down onto the entries themselves.
    # The page record now holds the repaired folio, so it replaces whatever the
    # running head gave the entry rather than only filling a gap.
    folio_by_page = {r["pdf_page"]: r.get("printed_page") for r in records}
    for record in records:
        for raw in record.get("entries", []):
            raw["printed_page"] = folio_by_page.get(record["pdf_page"])

    entries = stitch(records)

    # Body text carries the engine's habitual confusions -- "Maaonic" for
    # Masonic -- which silently break definition search. Repair them against
    # three tests: the spelling is rare, its neighbour is common, and it does
    # not look like English by the corpus's own trigrams. The 2007 OCR layer
    # over volume 1 vetoes anything it also read.
    body_count = 0
    body_plan: list = []
    if correct:
        as_dicts = [{"body": e.body} for e in entries]
        attested = body_text.second_opinion(out_dir.parent / "omnipage2007.txt")
        body_plan = body_text.plan(as_dicts, attested)
        body_count = body_text.apply(
            [{"body": e.body} if False else e.__dict__ for e in entries], body_plan)
        entry_overrides_path = (Path(__file__).resolve().parent / "corrections"
                                / "body_overrides.json")
        if entry_overrides_path.exists():
            body_count += body_text.apply_entry_overrides(
                [e.__dict__ for e in entries],
                json.loads(entry_overrides_path.read_text(encoding="utf-8")))

        # The 1874 printing's vocabulary, used across the whole book: a word
        # neither printing uses, whose confusable neighbour both do, is a
        # misread. This catches what the article-by-article comparison cannot
        # -- articles the 1914 revision added, and words the scan broke across
        # a line and rejoined wrongly.
        lexicon_path = Path("build/reference/lexicon1874.json")
        if lexicon_path.exists():
            lexicon = Counter(json.loads(lexicon_path.read_text(encoding="utf-8")))
            trusted = set()
            for entry in entries:
                trusted.update(w.lower() for w in body_text.TOKEN.findall(entry.headword))
            against = body_text.plan_against(
                [e.__dict__ for e in entries], lexicon, trusted)
            body_count += body_text.apply([e.__dict__ for e in entries], against)
            body_plan = body_plan + against

            # Words the scan broke in two at a column or page break.
            joins = body_text.plan_joins(
                [e.__dict__ for e in entries], lexicon, trusted)
            body_count += body_text.apply_joins([e.__dict__ for e in entries], joins)
            body_plan = body_plan + joins

        # Corrections the 1874 printing attests to, scoped to the article they
        # were found in. These come last among the word-level repairs so that
        # a word the re-read already fixed is not reconsidered.
        reference_path = out_dir / "reference_fixes.json"
        if reference_path.exists():
            by_entry = json.loads(reference_path.read_text(encoding="utf-8"))["by_entry"]
            body_count += body_text.apply_word_overrides(
                [e.__dict__ for e in entries], by_entry)

        split_plan = body_text.plan_splits(
            [e.__dict__ for e in entries], attested)
        body_count += body_text.apply_splits([e.__dict__ for e in entries], split_plan)
        more = body_text.plan_more_splits([e.__dict__ for e in entries], attested)
        body_count += body_text.apply_splits([e.__dict__ for e in entries], more)
        split_plan = split_plan + more
        body_plan = body_plan + split_plan
        (out_dir / "body_fixes.json").write_text(
            json.dumps([f.as_dict() for f in body_plan], indent=2, ensure_ascii=False),
            encoding="utf-8")

    dropped = 0
    merged = 0
    if correct:
        before = len(entries)
        entries = drop_false_headwords(entries)
        dropped = before - len(entries)
        merged = merge_false_splits(entries)

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
        "candidates_promoted": promoted,
        "false_headwords_dropped": dropped,
        "false_splits_merged": merged,
        "body_text_fixes": body_count,
        "body_text_token_types": len(body_plan),
        "candidates_considered": len(decisions),
        "ocr_headword_fixes": len(fixes),
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
