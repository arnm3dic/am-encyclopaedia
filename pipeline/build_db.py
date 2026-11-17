#!/usr/bin/env python3
"""Phase 4: build dictionary.db from the extracted entries.

    python3 -I pipeline/build_db.py build/full2/entries.json --out build/dictionary.db

The database is the canonical artifact. It is what validates the extraction,
what a future native build would ship, and what export_web.py derives the web
bundle from. It is built offline and never written to by the app: user data
(favourites, history) lives in a second file, so shipping a corrected
dictionary is a file swap rather than a migration.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.parse import crossrefs
from pipeline.parse.normalise import first_letter, normalise, sort_key

SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE entry (
  id              INTEGER PRIMARY KEY,
  headword        TEXT    NOT NULL,
  headword_plain  TEXT    NOT NULL,
  headword_sort   TEXT    NOT NULL,
  letter          TEXT    NOT NULL,
  body            TEXT    NOT NULL,
  pronunciation   TEXT,
  notes           TEXT,
  printed_page    INTEGER,
  pdf_page        INTEGER NOT NULL,
  region          TEXT    NOT NULL,
  ocr_confidence  REAL,
  needs_review    INTEGER NOT NULL DEFAULT 0,
  body_chars      INTEGER NOT NULL
);

CREATE TABLE entry_issue (
  entry_id  INTEGER NOT NULL REFERENCES entry(id) ON DELETE CASCADE,
  code      TEXT    NOT NULL
);

CREATE TABLE cross_ref (
  from_entry  INTEGER NOT NULL REFERENCES entry(id) ON DELETE CASCADE,
  to_entry    INTEGER REFERENCES entry(id),
  raw_target  TEXT    NOT NULL,
  kind        TEXT    NOT NULL
);

CREATE TABLE meta (
  key    TEXT PRIMARY KEY,
  value  TEXT NOT NULL
);

CREATE INDEX idx_entry_sort   ON entry(headword_sort);
CREATE INDEX idx_entry_letter ON entry(letter, headword_sort);
CREATE INDEX idx_entry_page   ON entry(printed_page);
CREATE INDEX idx_entry_plain  ON entry(headword_plain);
CREATE INDEX idx_issue_entry  ON entry_issue(entry_id);
CREATE INDEX idx_xref_from    ON cross_ref(from_entry);
CREATE INDEX idx_xref_to      ON cross_ref(to_entry);
"""

# Definition search. External-content tables keep one copy of the text.
FTS = """
CREATE VIRTUAL TABLE entry_fts USING fts5(
  headword, body, notes,
  content='entry', content_rowid='id',
  tokenize="unicode61 remove_diacritics 2"
);
INSERT INTO entry_fts(rowid, headword, body, notes)
  SELECT id, headword, body, COALESCE(notes, '') FROM entry;
INSERT INTO entry_fts(entry_fts) VALUES('optimize');
"""

# Substring search over headwords. The trigram tokenizer makes LIKE '%aut%'
# an indexed operation rather than a scan -- the middle-of-word case. The web
# app does this in memory instead, but the table is here for any native build
# and as the fallback if the corpus ever outgrows memory.
TRIGRAM = """
CREATE VIRTUAL TABLE entry_trigram USING fts5(
  headword_plain,
  content='entry', content_rowid='id',
  tokenize="trigram"
);
INSERT INTO entry_trigram(rowid, headword_plain)
  SELECT id, headword_plain FROM entry;
INSERT INTO entry_trigram(entry_trigram) VALUES('optimize');
"""

REVIEW_CODES = {"unanchored", "low_confidence", "empty_body", "short_headword",
                "promoted_by_order", "ocr_corrected", "margin_mark_removed"}


def build(entries_path: Path, out_path: Path) -> dict:
    data = json.loads(entries_path.read_text(encoding="utf-8"))
    raw_entries = data["entries"]
    source_summary = data["summary"]

    rows = []
    for index, entry in enumerate(raw_entries, start=1):
        headword = entry["headword"]
        rows.append({
            "id": index,
            "headword": headword,
            "headword_plain": normalise(headword),
            "headword_sort": sort_key(headword),
            "letter": first_letter(headword),
            "body": entry["body"],
            "printed_page": entry.get("printed_page"),
            "pdf_page": entry["pdf_page"],
            "region": entry.get("region", "main"),
            "ocr_confidence": entry.get("confidence"),
            "issues": entry.get("issues", []),
        })

    total_refs, resolved_refs = crossrefs.resolve(rows)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    connection = sqlite3.connect(out_path)
    connection.executescript(SCHEMA)

    connection.executemany(
        """INSERT INTO entry (id, headword, headword_plain, headword_sort, letter,
                              body, printed_page, pdf_page, region, ocr_confidence,
                              needs_review, body_chars)
           VALUES (:id, :headword, :headword_plain, :headword_sort, :letter,
                   :body, :printed_page, :pdf_page, :region, :ocr_confidence,
                   :needs_review, :body_chars)""",
        [dict(row,
              needs_review=int(bool(REVIEW_CODES & set(row["issues"]))),
              body_chars=len(row["body"]))
         for row in rows])

    connection.executemany(
        "INSERT INTO entry_issue (entry_id, code) VALUES (?, ?)",
        [(row["id"], code) for row in rows for code in row["issues"]])

    connection.executemany(
        "INSERT INTO cross_ref (from_entry, to_entry, raw_target, kind) VALUES (?,?,?,?)",
        [(row["id"], ref["resolved_id"], ref["raw_target"], ref["kind"])
         for row in rows for ref in row.get("crossrefs", [])])

    connection.executescript(FTS)
    connection.executescript(TRIGRAM)

    meta = {
        "source_title": "An Encyclopaedia of Freemasonry and Its Kindred Sciences",
        "source_author": "Albert G. Mackey",
        "source_edition": "Revised edition (Hawkins and Hughan), 1912",
        "source_pages": "946",
        "entries": str(len(rows)),
        "extraction_mean_confidence": str(source_summary.get("mean_confidence", "")),
        "cross_refs": str(total_refs),
        "cross_refs_resolved": str(resolved_refs),
        "schema_version": "1",
    }
    connection.executemany("INSERT INTO meta (key, value) VALUES (?, ?)",
                           list(meta.items()))
    connection.commit()
    connection.executescript("PRAGMA journal_mode = DELETE;")
    connection.execute("VACUUM")
    connection.commit()

    stats = {
        "entries": len(rows),
        "needs_review": connection.execute(
            "SELECT COUNT(*) FROM entry WHERE needs_review = 1").fetchone()[0],
        "cross_refs": total_refs,
        "cross_refs_resolved": resolved_refs,
        "letters": connection.execute(
            "SELECT COUNT(DISTINCT letter) FROM entry").fetchone()[0],
        "db_bytes": out_path.stat().st_size,
    }
    connection.close()
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("entries", help="entries.json from the extraction")
    parser.add_argument("--out", default="build/dictionary.db")
    options = parser.parse_args()

    stats = build(Path(options.entries), Path(options.out))
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
