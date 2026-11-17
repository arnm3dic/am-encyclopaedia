#!/usr/bin/env python3
"""Phase 4: derive the web bundle from dictionary.db.

    python3 -I pipeline/export_web.py build/dictionary.db --out app/public/data

Emits three files:

  headwords.json   every headword, compact. The app holds this in memory and
                   answers exact, prefix, suffix, substring and fuzzy searches
                   against it directly -- about 4,000 strings, so a scan costs
                   microseconds and needs no index.
  entries.json     the full text, loaded once and kept in memory.
  meta.json        provenance and counts, shown on the settings screen.

The definition index is deliberately not prebuilt here. Serialising one from
Python would couple this script to a JavaScript library's internal format, and
a change on either side would fail silently. The app builds it at first run
from entries.json, which takes a few hundred milliseconds, and caches it.

Fixtures for the shared normalisation rules are written alongside, so the
TypeScript implementation can be tested against the Python one.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.parse.normalise import first_letter, normalise, sort_key

# Fixed words whose normalisation exercises every rule: diacritics in several
# languages, ligatures, internal hyphens and apostrophes, trailing stops.
FIXTURE_SEEDS = [
    "Babylon, Red Cross of.", "Maçon", "Rose-Croix", "Mason's Word",
    "Ægypt", "Thébäische", "33°", "Knight Kadosh.",
    "  spaced   out  ", "", "St. John's Day.", "Zschokke, J. H. D.",
    "Maçonnerie d'Adoption", "Schröder, Friedrich Ludwig",
    "Tetragrammaton", "A.'. L.'.", "Beaucéant", "Ne Plus Ultra",
]


def export(db_path: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row

    rows = connection.execute(
        """SELECT id, headword, headword_plain, headword_sort, letter, body,
                  printed_page, pdf_page, needs_review
           FROM entry ORDER BY headword_sort, id"""
    ).fetchall()

    # Compact and positional: the app reads these by index, so the file stays
    # small enough to ship and parse quickly.
    headwords = [[r["id"], r["headword"], r["headword_plain"], r["letter"],
                  r["printed_page"] or 0] for r in rows]
    entries = {str(r["id"]): [r["headword"], r["body"], r["printed_page"] or 0,
                              r["pdf_page"], r["needs_review"]] for r in rows}

    refs: dict[str, list] = {}
    for row in connection.execute(
            "SELECT from_entry, to_entry, raw_target, kind FROM cross_ref"):
        refs.setdefault(str(row["from_entry"]), []).append(
            [row["to_entry"], row["raw_target"], row["kind"]])

    meta = {key: value for key, value in connection.execute("SELECT key, value FROM meta")}
    counts = {letter: count for letter, count in connection.execute(
        "SELECT letter, COUNT(*) FROM entry GROUP BY letter ORDER BY letter")}
    meta["letter_counts"] = counts
    meta["schema"] = {
        "headwords": ["id", "headword", "plain", "letter", "printed_page"],
        "entries": ["headword", "body", "printed_page", "pdf_page", "needs_review"],
        "crossrefs": ["to_entry", "raw_target", "kind"],
    }

    (out_dir / "headwords.json").write_text(
        json.dumps(headwords, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (out_dir / "entries.json").write_text(
        json.dumps({"entries": entries, "crossrefs": refs},
                   ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (out_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    fixtures = write_fixtures(out_dir.parent.parent / "pipeline" / "tests"
                              if (out_dir.parent.parent / "pipeline").exists()
                              else Path("pipeline/tests"),
                              [r["headword"] for r in rows])
    connection.close()

    return {
        "headwords_bytes": (out_dir / "headwords.json").stat().st_size,
        "entries_bytes": (out_dir / "entries.json").stat().st_size,
        "entries": len(rows),
        "fixtures": fixtures,
    }


def write_fixtures(tests_dir: Path, headwords: list[str]) -> int:
    """Pin the normalisation rules so both implementations can be checked.

    `normalise.py` and `normalise.ts` must agree exactly. A query normalised
    one way and stored text normalised another returns nothing at all, and it
    reads as a search bug rather than a normalisation bug. These pairs are the
    contract; both test suites run them.
    """
    tests_dir.mkdir(parents=True, exist_ok=True)
    # Seeds, plus a spread of real headwords so the awkward ones are covered.
    sample = FIXTURE_SEEDS + headwords[:: max(1, len(headwords) // 220)]
    cases = [{"input": text,
              "normalise": normalise(text),
              "sort_key": sort_key(text),
              "first_letter": first_letter(text)}
             for text in sample]
    (tests_dir / "normalise_fixtures.json").write_text(
        json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(cases)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db", nargs="?", default="build/dictionary.db")
    parser.add_argument("--out", default="app/public/data")
    options = parser.parse_args()
    stats = export(Path(options.db), Path(options.out))
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
