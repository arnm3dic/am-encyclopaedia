"""Decide between two readings of the same printed headword.

recheck.py reads every headword twice: once from the 300 dpi page with layout
analysis, once from a 600 dpi crop in single-line mode. They disagree on about
one headword in eight, and neither is reliably right -- the first pass reads
"Adontram" where the second reads "Adoniram", and the second reads "Abiution"
where the first reads "Ablution".

The book itself decides. A real term recurs in the body text; a misread does
not. "Adoniram" appears throughout, "Adontram" never. This is evidence from
the same 1912 text rather than from a modern dictionary, which matters because
the book's own spelling is inconsistent -- `practise` outnumbers `practice`,
`sepulcher` outnumbers `sepulchre`, and `antient`, `connexion` and `shew` all
appear. A word list would reject those as errors.

Only clear cases are changed: one reading well attested, the other essentially
absent. Anything closer is left alone and reported.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..parse.normalise import normalise

_TOKEN = re.compile(r"[A-Za-zÀ-ɏ']+")

ATTESTED = 3        # a reading is supported at this many occurrences
ABSENT = 1          # ...and opposed at this many or fewer
MIN_TOKEN = 4       # shorter tokens are too common to carry evidence


# OCR of a cropped line sometimes picks up the quotation mark that opens the
# line above it.
_EDGE_JUNK = re.compile(
    r"""^[\s\u2018\u2019\u201c\u201d'"`.,:;|\\/-]+|[\s\u2018\u201c`|\\]+$""")


def tidy(text: str) -> str:
    """Trim marks the crop picked up from its edges."""
    return _EDGE_JUNK.sub("", text).strip()


@dataclass
class Verdict:
    pdf_page: int
    first: str
    second: str
    chosen: str
    reason: str
    changed: bool

    def as_dict(self) -> dict:
        return {"pdf_page": self.pdf_page, "first": self.first, "second": self.second,
                "chosen": self.chosen, "reason": self.reason, "changed": self.changed}


def _differing(first: str, second: str) -> tuple[list[str], list[str]]:
    """The words that actually differ between the two readings.

    Judging a reading on all of its words lets the words they share decide the
    question. "Charles XTWI." against "Charles XHI." was settled by "Charles",
    which both agree on, and the roman numeral -- the only thing in dispute --
    was changed from one wrong value to another. Only the disputed words count.
    """
    a = _TOKEN.findall(first)
    b = _TOKEN.findall(second)
    if len(a) != len(b):
        return (a, b)
    changed_a = [x for x, y in zip(a, b) if x.lower() != y.lower()]
    changed_b = [y for x, y in zip(a, b) if x.lower() != y.lower()]
    return (changed_a, changed_b)


def _evidence(tokens: list[str], lexicon: dict[str, int]) -> tuple[int, int]:
    """(weakest support, number of tokens judged) for a set of words.

    A reading is only as good as its worst word, so the minimum is what counts:
    "Age, Masonie." is wrong because of one token, not on average.
    """
    judged = [t for t in tokens if len(t) >= MIN_TOKEN]
    if not judged:
        return (-1, 0)
    return (min(lexicon.get(token.lower(), 0) for token in judged), len(judged))


def adjudicate(rows: list[dict], lexicon: dict[str, int]) -> list[Verdict]:
    """Choose between the two readings of each disagreeing headword."""
    verdicts: list[Verdict] = []
    for row in rows:
        if row["agree"]:
            continue
        first, second = row["first"], row["second"]

        if not second.strip():
            verdicts.append(Verdict(row["pdf_page"], first, second, first,
                                    "second reading empty", False))
            continue

        # The second pass sometimes drops or adds only punctuation. The first
        # pass saw the word in its line, so it is the better judge of that.
        if normalise(first).replace(" ", "") == normalise(second).replace(" ", ""):
            verdicts.append(Verdict(row["pdf_page"], first, second, first,
                                    "same letters, different punctuation", False))
            continue

        changed_first, changed_second = _differing(first, second)
        first_support, first_tokens = _evidence(changed_first, lexicon)
        second_support, second_tokens = _evidence(changed_second, lexicon)

        if first_tokens == 0 or second_tokens == 0:
            verdicts.append(Verdict(row["pdf_page"], first, second, first,
                                    "the disputed words are too short to judge", False))
            continue

        if second_support >= ATTESTED and first_support <= ABSENT:
            cleaned = tidy(second)
            verdicts.append(Verdict(
                row["pdf_page"], first, second, cleaned,
                f"second reading attested {second_support}x, first {first_support}x",
                cleaned != first))
        elif first_support >= ATTESTED and second_support <= ABSENT:
            verdicts.append(Verdict(
                row["pdf_page"], first, second, first,
                f"first reading attested {first_support}x, second {second_support}x", False))
        else:
            verdicts.append(Verdict(
                row["pdf_page"], first, second, first,
                f"neither decisive ({first_support}x vs {second_support}x)", False))
    return verdicts


def build_lexicon(entries: list[dict]) -> dict[str, int]:
    """Token frequencies over the body text, which no headword contributes to."""
    counts: dict[str, int] = {}
    for entry in entries:
        for token in _TOKEN.findall(entry.get("body", "")):
            lowered = token.lower()
            counts[lowered] = counts.get(lowered, 0) + 1
    return counts
