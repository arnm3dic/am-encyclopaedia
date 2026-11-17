"""Compare the extraction against an independent printing of the same book.

The scan in hand is the 1914 Hughan and Hawkins revision. The Internet Archive
carries a 1908 digitisation of the 1874 first edition -- a different printing,
a different scanner, a different OCR engine, fifteen years apart. For Mackey's
own articles the two editions are word for word the same. The Winding Stairs
article is typical: the only difference in the whole paragraph is that 1874
says "in the York and American Rites" where 1914 says "in the American Rite".

That makes it the best adjudicator this project has had. The 2007 OmniPage
layer inside the PDF is a second opinion on the *same ink*, so it makes the
same mistakes in the same places -- it reads i for l exactly where this pass
does, and using it as attestation launders the error. A separate printing
cannot do that.

It is a witness, not an authority. The scan is the authority: it is the book
the reader has, and the 1914 edition genuinely differs from 1874 in places --
articles rewritten, people who died after 1874 added, cross-references
repointed. So a difference between the two is never on its own a reason to
change anything.

A word is only replaced when all of this holds:

  * the alignment is confident -- the words on both sides of it match;
  * it is one word for one word, not a rewritten phrase, which is what an
    editorial change looks like;
  * the two spellings are within two edits of each other, so it is a misread
    rather than a different word;
  * the scan's word is not one this book uses -- not a headword, and not
    written 25 times or more across the corpus;
  * and the 1874 word is.

Everything proposed is written out with its page, its entry and the sentence
it sits in, so every change can be read back against the page image.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

WORD = re.compile(r"[A-Za-z]+")
TRUST_COUNT = 25
MAX_EDITS = 2
MIN_ANCHOR = 5          # words in the anchor used to find an entry
CONTEXT = 2             # matching words required either side of a difference
SHAPE_MARGIN = 0.5      # how much more like English the replacement must look


def flatten(text: str) -> str:
    """One long line: hyphenation at line ends joined, whitespace collapsed."""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[‐-―]", "-", text)
    text = re.sub(r"-\s*\n\s*", "", text)          # obso- \n lete -> obsolete
    return re.sub(r"\s+", " ", text)


def words_of(text: str) -> list[str]:
    return [m.group(0).lower() for m in WORD.finditer(text)]


def edits(a: str, b: str, cap: int = 3) -> int:
    """Levenshtein distance, stopped once it passes cap."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (ca != cb)))
        if min(current) > cap:
            return cap + 1
        previous = current
    return previous[-1]


@dataclass
class Proposal:
    headword: str
    pdf_page: int | None
    printed_page: int | None
    before: str
    after: str
    context: str
    distance: int

    def as_dict(self) -> dict:
        return {"headword": self.headword, "pdf_page": self.pdf_page,
                "printed_page": self.printed_page, "before": self.before,
                "after": self.after, "context": self.context,
                "distance": self.distance}


@dataclass
class Report:
    proposals: list[Proposal] = field(default_factory=list)
    entries_located: int = 0
    entries_missed: int = 0
    words_compared: int = 0
    words_equal: int = 0
    rejected: Counter = field(default_factory=Counter)

    @property
    def agreement(self) -> float:
        return self.words_equal / self.words_compared if self.words_compared else 0.0


class Reference:
    """The other printing, indexed so an article can be found in it quickly."""

    def __init__(self, text: str):
        self.flat = flatten(text)
        self.words = words_of(self.flat)
        self.counts = Counter(self.words)
        self.index: dict[tuple[str, ...], list[int]] = {}
        key_length = MIN_ANCHOR
        for position in range(len(self.words) - key_length + 1):
            key = tuple(self.words[position:position + key_length])
            # Only the first few places a phrase occurs are worth keeping.
            bucket = self.index.setdefault(key, [])
            if len(bucket) < 4:
                bucket.append(position)

    def locate(self, needle: list[str]) -> int | None:
        """Where this article starts in the reference, by its opening words."""
        for start in range(0, min(len(needle) - MIN_ANCHOR, 40)):
            key = tuple(needle[start:start + MIN_ANCHOR])
            where = self.index.get(key)
            if where and len(where) == 1:
                return where[0] - start
        for start in range(0, min(len(needle) - MIN_ANCHOR, 40)):
            key = tuple(needle[start:start + MIN_ANCHOR])
            where = self.index.get(key)
            if where:
                return where[0] - start
        return None


def trusted_vocabulary(entries: list[dict]) -> set[str]:
    counts: Counter[str] = Counter()
    trusted: set[str] = set()
    for entry in entries:
        counts.update(words_of(entry.get("body", "")))
        trusted.update(words_of(entry.get("headword", "")))
    trusted |= {word for word, count in counts.items() if count >= TRUST_COUNT}
    return trusted


def compare(entries: list[dict], reference: Reference, trusted: set[str],
            shape=None, own: Counter | None = None) -> Report:
    report = Report()
    own = own if own is not None else Counter()

    for entry in entries:
        body = entry.get("body", "")
        mine = words_of(flatten(body))
        if len(mine) < MIN_ANCHOR * 2:
            continue

        start = reference.locate(mine)
        if start is None:
            report.entries_missed += 1
            continue
        report.entries_located += 1

        # A generous window: the two printings set the same text differently,
        # so the article's length drifts.
        theirs = reference.words[max(0, start - 20):start + len(mine) + 200]
        matcher = difflib.SequenceMatcher(None, mine, theirs, autojunk=False)

        blocks = matcher.get_matching_blocks()
        report.words_compared += len(mine)
        report.words_equal += sum(b.size for b in blocks)

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag != "replace" or i2 - i1 != 1 or j2 - j1 != 1:
                if tag == "replace":
                    report.rejected["phrase_differs"] += 1
                continue
            before, after = mine[i1], theirs[j1]

            if before in trusted:
                report.rejected["scan_word_is_the_book's"] += 1
                continue
            if reference.counts[before] >= 1:
                # The other printing uses this spelling too, so it is a word
                # the book has, and the difference is editorial rather than a
                # misread. This is what keeps rabbis from becoming rabbins and
                # archeologists from becoming archaeologists -- and it keeps
                # the reference's own OCR errors out, since Macons survives
                # where the 1874 scan read maqons.
                report.rejected["both_printings_use_it"] += 1
                continue
            if reference.counts[after] < 2:
                report.rejected["reference_word_is_rare"] += 1
                continue
            if len(before) < 3 or len(after) < 3:
                report.rejected["too_short_to_judge"] += 1
                continue
            if shape is not None and shape.score(after) - shape.score(before) < SHAPE_MARGIN:
                # Both spellings look like English, so this is the two editions
                # differing rather than a misread: worshipers against
                # worshippers, traveled against travelled, honor against
                # honour. The 1914 printing Americanised a great deal of the
                # 1874 spelling, and that is the book the reader has.
                report.rejected["both_look_like_english"] += 1
                continue
            mine_count, theirs_count = own.get(before, 0), own.get(after, 0)
            if mine_count > 2 and theirs_count < 5 * mine_count:
                # The scan writes it this way repeatedly and rarely the other
                # way: that is this edition's habit, not a slip.
                report.rejected["scan_is_consistent"] += 1
                continue
            distance = edits(before, after)
            if distance > MAX_EDITS:
                report.rejected["too_far_apart"] += 1
                continue
            if not _anchored(matcher, i1, i2):
                report.rejected["alignment_unsure"] += 1
                continue

            where = body.lower().find(before)
            context = body[max(0, where - 60):where + len(before) + 60] if where >= 0 else ""
            report.proposals.append(Proposal(
                headword=entry.get("headword", ""),
                pdf_page=entry.get("pdf_page"),
                printed_page=entry.get("printed_page"),
                before=before, after=after,
                context=" ".join(context.split()),
                distance=distance))
    return report


def _anchored(matcher: difflib.SequenceMatcher, i1: int, i2: int) -> bool:
    """True when the words on both sides of a difference matched.

    A substitution floating inside a stretch of disagreement is usually the
    alignment slipping, not a misread.
    """
    before_ok = after_ok = False
    for block in matcher.get_matching_blocks():
        if block.a + block.size == i1 and block.size >= CONTEXT:
            before_ok = True
        if block.a == i2 and block.size >= CONTEXT:
            after_ok = True
    return before_ok and after_ok


def load(path: Path) -> Reference:
    return Reference(path.read_text(encoding="utf-8", errors="replace"))
