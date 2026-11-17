#!/usr/bin/env python3
"""Turn the two independent checks into one set of corrections.

    python3 -I pipeline/apply_corrections.py --out build/full2

Two things now read the book besides the first OCR pass:

  * reread_body.py crops each suspect word out of a 600 dpi render and reads
    it again on its own. That is the same ink, read better.
  * corrections/reference.py aligns every article against the 1874 printing
    digitised by the Internet Archive. That is different ink, read by a
    different engine, and it is what catches damage the crop cannot -- a word
    the first pass turned into a different real word.

This writes what each found, keeping them apart so a mistake can be traced to
the check that made it:

  word_fixes.json       word-box corrections, applied when the page is parsed,
                        so they flow into headwords, cross-references and the
                        search index as well as the body text.
  reference_fixes.json  article-scoped corrections, applied after stitching.

Both files carry the original reading of every word they touch. Nothing is
deleted and nothing is rewritten in place; the word cache from the OCR pass is
never modified, so the whole book can be rebuilt without them.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.corrections import reference as ref
from pipeline.corrections.body_text import EnglishShape
from pipeline.reread_body import core_of, decide, vocabulary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="build/full2")
    parser.add_argument("--reference", default="build/reference/mackey1874.txt")
    options = parser.parse_args()

    out_dir = Path(options.out)
    entries = json.loads((out_dir / "entries.json").read_text(encoding="utf-8"))["entries"]

    reference = ref.load(Path(options.reference))
    print(f"reference: {len(reference.words)} words, {len(reference.counts)} types")

    trusted, counts = vocabulary(entries)
    shape = EnglishShape({w: c for w, c in counts.items() if c >= ref.TRUST_COUNT})
    elsewhere = {word for word, count in reference.counts.items() if count >= 2}

    # --- the ink, read again -------------------------------------------------
    reread_path = out_dir / "body_reread.json"
    word_fixes: list[dict] = []
    if reread_path.exists():
        readings = json.loads(reread_path.read_text(encoding="utf-8"))["readings"]
        accepted = decide(readings, trusted, elsewhere)
        for record in accepted:
            word_fixes.append({"pdf_page": record["pdf_page"],
                               "left": record["left"], "top": record["top"],
                               "was": record["first"], "now": record["text"]})
        print(f"re-read: {len(readings)} words, {len(word_fixes)} corrections")
    else:
        print("re-read: not run yet")

    (out_dir / "word_fixes.json").write_text(
        json.dumps(word_fixes, ensure_ascii=False, indent=1), encoding="utf-8")

    # --- the other printing --------------------------------------------------
    report = ref.compare(entries, reference, trusted, shape, Counter(counts))
    print(f"reference: located {report.entries_located} articles, "
          f"missed {report.entries_missed}, "
          f"word agreement {report.agreement:.3f}, "
          f"{len(report.proposals)} corrections")

    # How often the two checks found the same thing independently -- the
    # closest thing to a confidence measure this project has. They are not
    # deduplicated: a word fixed in one place by the re-read can still be
    # wrong elsewhere in the same article, and the article-level fix is
    # applied to every occurrence, so an already-corrected one simply no
    # longer matches.
    from_ink = {(f["pdf_page"], core_of(f["was"])) for f in word_fixes}
    by_entry: dict[str, list[list[str]]] = {}
    both = 0
    for proposal in report.proposals:
        if (proposal.pdf_page, proposal.before) in from_ink:
            both += 1
        pairs = by_entry.setdefault(proposal.headword, [])
        pair = [proposal.before, proposal.after]
        if pair not in pairs:
            pairs.append(pair)
    print(f"  {both} of them the re-read had already found the same way")

    # Merge rather than replace: a run after the corrections are already in
    # the text sees only what is left, and dropping the rest would undo it on
    # the next rebuild.
    existing_path = out_dir / "reference_fixes.json"
    detail = [p.as_dict() for p in report.proposals]
    if existing_path.exists():
        previous = json.loads(existing_path.read_text(encoding="utf-8"))
        for headword, pairs in previous.get("by_entry", {}).items():
            kept = by_entry.setdefault(headword, [])
            for pair in pairs:
                if pair not in kept:
                    kept.append(pair)
        detail = previous.get("detail", []) + detail
    existing_path.write_text(
        json.dumps({"by_entry": by_entry, "detail": detail},
                   ensure_ascii=False, indent=1), encoding="utf-8")

    total = len(word_fixes) + sum(len(v) for v in by_entry.values())
    print(f"wrote {total} corrections to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
