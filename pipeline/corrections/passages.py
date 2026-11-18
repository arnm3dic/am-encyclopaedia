"""Repair a passage the scan mangled, from the same edition's text.

Everything else in this project repairs one word at a time, and there is a
whole class of damage it cannot touch. On printed page 851 the scan reads:

    The error lation of maling aa wenn » Which was a vio;

where the page says "The error of making an even number, which was a
violation". Three lines have run together -- the word boxes there are 70
pixels tall where a line is 30, because at one bit per pixel the ink of
adjacent lines met and the engine read them as one. There is no word to
substitute for another: words are merged, split and lost. The same thing
happens in miniature all over the book, which is where "um brage",
"undoubt edly" and "crownin ff" come from.

The repair is to take the passage from the other copy. That is only defensible
because it is the same edition -- the 1924 reprint of the 1914 revision, same
plates, same pagination -- so its sentences are this book's sentences, not an
editor's later rewriting of them.

A passage is replaced only when all of this holds:

  * it sits between two anchors of at least three words that matched exactly,
    so there is no doubt where it begins and ends;
  * it is at most 25 words, because a long disagreement is a rewritten
    article, not a damaged line;
  * our side is damaged: at least one word in it appears nowhere in the other
    copy;
  * their side is clean: every word attested, no word repeated back to back
    (which is how a running head looks when the alignment slips), of
    comparable length, and it reads more like English than ours does on the
    trigram model.

Each replacement is recorded with the article, both readings and the page, so
any of them can be read back against the page image.
"""

from __future__ import annotations

import difflib
import re
from collections import Counter
from dataclasses import dataclass

from pipeline.corrections import reference as ref
from pipeline.corrections.body_text import EnglishShape

MAX_SPAN = 25
MIN_ANCHOR = 3
SHAPE_MARGIN = 0.15
MIN_REFERENCE_COUNT = 2


@dataclass
class Repair:
    headword: str
    printed_page: int | None
    before: str
    after: str

    def as_dict(self) -> dict:
        return {"headword": self.headword, "printed_page": self.printed_page,
                "before": self.before, "after": self.after}


def _reads_like_english(words: list[str], model: EnglishShape) -> float:
    scores = [model.score(w) for w in words if len(w) >= 3]
    return sum(scores) / len(scores) if scores else 0.0


def _regions(matcher: difflib.SequenceMatcher) -> list[tuple[int, int, int, int]]:
    """Damaged stretches, taking a one- or two-word match as part of the damage.

    Where lines have run together the difference does not arrive as one tidy
    block. On page 851 it comes out as: a stray "lation", then "of" matching,
    then "maling aa wenn" against "making an even number". Treating those as
    three separate problems leaves each of them without an anchor to stand on.
    Treated as one stretch between "eleven the error" and "which was a", both
    ends are solid and the whole thing can be replaced at once.
    """
    regions: list[tuple[int, int, int, int]] = []
    current: list[int] | None = None
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal" and i2 - i1 >= MIN_ANCHOR:
            if current:
                regions.append(tuple(current))
                current = None
            continue
        if tag == "equal" and current is None:
            continue                      # a short match with nothing to join
        if current is None:
            current = [i1, i2, j1, j2]
        else:
            current[1], current[3] = i2, j2
    if current:
        regions.append(tuple(current))
    return regions


def plan(entries: list[dict], reference: ref.Reference, trusted: set[str],
         model: EnglishShape) -> list[Repair]:
    known = set(trusted) | {w for w, c in reference.counts.items()
                            if c >= MIN_REFERENCE_COUNT}
    # How badly a word has to read before it counts as damaged rather than
    # merely unusual: the lower quartile of the words the book is known to use.
    attested = sorted(model.score(w) for w in known if len(w) >= 4)
    floor = attested[len(attested) // 4] if attested else -99.0
    common = {w for w, c in reference.counts.most_common(300)}
    out: list[Repair] = []

    for entry in entries:
        mine = ref.words_of(ref.flatten(entry.get("body", "")))
        if len(mine) < 10:
            continue
        start = reference.locate(mine)
        if start is None:
            continue
        window = slice(max(0, start - 20), start + len(mine) + 200)
        theirs = reference.words[window]
        theirs_raw = reference.raw[window]
        matcher = difflib.SequenceMatcher(None, mine, theirs, autojunk=False)

        anchored_end, anchored_start = set(), set()
        for block in matcher.get_matching_blocks():
            if block.size >= MIN_ANCHOR:
                anchored_end.add(block.a + block.size)
                anchored_start.add(block.a)

        for i1, i2, j1, j2 in _regions(matcher):
            ours, replacement = mine[i1:i2], theirs[j1:j2]
            written = theirs_raw[j1:j2]
            if not (1 <= len(ours) <= MAX_SPAN) or not (1 <= len(replacement) <= MAX_SPAN):
                continue
            if i1 not in anchored_end or i2 not in anchored_start:
                continue
            # A replacement much shorter or longer than what it replaces is
            # the alignment slipping, not a repair. One span of twenty-one
            # words in Trestle-Board would have been swapped for three,
            # deleting a sentence the page actually prints.
            if not (max(1, len(ours) // 2) <= len(replacement) <= len(ours) * 2 + 1):
                continue
            if all(word in known for word in ours):
                continue                                   # not damaged
            if any(word not in known for word in replacement):
                continue                                   # their side suspect
            if any(a == b for a, b in zip(replacement, replacement[1:])):
                continue                                   # a running head slipped in
            if len(replacement) < len(ours):
                # A repair that uses fewer words has to be made of roughly
                # the same letters, or it is dropping something the page
                # prints: "um brage" into "umbrage" keeps every letter, while
                # "bodfrey roclaimed" into "proclaimed" quietly loses
                # Godfrey.
                a, b = "".join(ours), "".join(replacement)
                if ref.edits(a, b, max(2, len(a) // 4)) > max(2, len(a) // 4):
                    continue
            ours_reads = _reads_like_english(ours, model)
            theirs_reads = _reads_like_english(replacement, model)
            # Only compare when both sides have a word long enough to score.
            # Comparing a real score against the zero returned for "o" or "ig"
            # rejected every repair of a one-letter stub.
            if ours_reads and theirs_reads and theirs_reads - ours_reads < SHAPE_MARGIN:
                continue
            if all(len(w) < 3 for w in ours + replacement):
                pass          # too short for the trigram model to judge
            # A single word swapped for a single word, one edit apart, where
            # ours is a perfectly ordinary English word, is a spelling
            # difference between two copies rather than damage --
            # organisation against organization. Those are left to the
            # word-level pass, which settles them against the page image
            # instead of guessing.
            if (len(ours) == 1 and len(replacement) == 1
                    and len(ours[0]) >= 4
                    and ref.edits(ours[0], replacement[0], 3) <= 2
                    and model.score(ours[0]) >= floor):
                continue
            if len(ours) == len(written):
                # Word for word, keep ours wherever it is a word this book
                # uses. The other copy has its own misreads, and importing
                # them would be a poor trade: in one span it reads "bo" where
                # the page says "be", next to the "himeelf" that needed
                # fixing. Taking "himself" and keeping "be" gets both right.
                # Only where the two readings are plainly the same word.
                # Equal length does not mean the words line up: in the page
                # 851 passage, five of ours against five of theirs are five
                # scrambled words against five correct ones, and keeping
                # ours position by position produced "The error of of an aa
                # number" -- worse than what it replaced.
                written = [o if (o in trusted
                                 and ref.edits(o, w.lower(), 3) <= 2) else w
                           for o, w in zip(ours, written)]
                if all(o == w.lower() for o, w in zip(ours, written)):
                    continue
            elif (len(ours) == 1 and "".join(ours) == "".join(replacement)
                  and not all(w in common for w in replacement)):
                # The same letters, differently spaced. "tothe" against "to
                # the" is ours broken; "severus" against "Sever us" is theirs
                # broken. What separates them is that a word really run
                # together is run together with ordinary small words, so the
                # split is only trusted when every piece of it is one.
                continue
            out.append(Repair(entry.get("headword", ""), entry.get("printed_page"),
                              " ".join(ours), " ".join(written)))
    return out


def apply(entries: list[dict], repairs: list[Repair]) -> int:
    """Swap each damaged passage for the other copy's reading.

    Matching is done on the words alone, with whatever punctuation, line
    breaks and italic markers lie between them allowed to vary, because the
    scan's punctuation in a mangled passage is not worth preserving. The
    replacement carries no italic markers, so a passage that was italic in the
    original loses that; the alternative is leaving the sentence unreadable.
    """
    by_entry: dict[str, list[Repair]] = {}
    for repair in repairs:
        by_entry.setdefault(repair.headword, []).append(repair)

    changed = 0
    for entry in entries:
        found = by_entry.get(entry.get("headword", ""))
        if not found:
            continue
        body = entry.get("body", "")
        for repair in found:
            words = repair.before.split(" ")
            pattern = re.compile(
                r"(?<![A-Za-zÀ-ɏ])"
                + r"[^A-Za-zÀ-ɏ]+".join(re.escape(w) for w in words)
                + r"(?![A-Za-zÀ-ɏ])", re.IGNORECASE)
            def shaped(match: re.Match[str]) -> str:
                # Italic markers inside the span have to come back out in the
                # same numbers, or the run they open is never closed and the
                # rest of the article turns italic in the reader. An opener
                # goes in front of the replacement and a closer behind it,
                # which keeps both the count and the sense.
                found = match.group(0)
                opens = "\x02" * found.count("\x02")
                closes = "\x03" * found.count("\x03")
                return f"{opens}{repair.after}{closes}"

            body, count = pattern.subn(shaped, body, count=1)
            changed += count
        entry["body"] = body
    return changed


def build_model(entries: list[dict]) -> EnglishShape:
    counts: Counter[str] = Counter()
    for entry in entries:
        counts.update(ref.words_of(entry.get("body", "")))
    return EnglishShape({w: c for w, c in counts.items() if c >= 25})
