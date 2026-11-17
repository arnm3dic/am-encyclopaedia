"""Turn a page of measured words into dictionary entries.

Reading order is column 0 top-to-bottom, then column 1. Entries run on: a
headword begins mid-column and the entry continues until the next headword,
which may be on the next page. Text before the first headword on a page is a
continuation of the entry that started earlier, and is emitted as such so the
full run can stitch pages together.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..extract.ocr import Page, Word
from .regions import RunningHead
from .normalise import first_letter, normalise, sort_key

MAX_HEADWORD_WORDS = 9        # longest real headwords run to about 7 words
HEADWORD_START = re.compile(r"^[A-ZÆŒ]")
TERMINATES = (".", ".’", ".\"", ".'")

# Periods that sit *inside* a headword rather than ending it.
ABBREVIATIONS = {
    "st.", "ste.", "mt.", "dr.", "mr.", "mrs.", "rev.", "hon.", "col.",
    "gen.", "capt.", "maj.", "sgt.", "jr.", "sr.", "no.", "vol.", "pt.",
    "ch.", "fr.", "ger.", "lat.", "heb.", "gr.", "lodge.",
}
_INITIAL = re.compile(r"^[A-Z]\.$")


def _is_abbreviation(text: str) -> bool:
    """True for a token whose period is internal to the headword."""
    token = text.strip()
    if _INITIAL.match(token):          # "J.", "G.", "D." -- a person's initial
        return True
    return token.lower() in ABBREVIATIONS


@dataclass
class Entry:
    headword: str
    body: str
    pdf_page: int
    printed_page: int | None
    region: str
    confidence: float
    is_continuation: bool = False
    issues: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "headword": self.headword,
            "headword_plain": normalise(self.headword),
            "headword_sort": sort_key(self.headword),
            "letter": first_letter(self.headword),
            "body": self.body,
            "pdf_page": self.pdf_page,
            "printed_page": self.printed_page,
            "region": self.region,
            "confidence": round(self.confidence, 1),
            "is_continuation": self.is_continuation,
            "issues": self.issues,
        }


def reading_order(page: Page, head: RunningHead) -> list[Word]:
    """Body words, in the order a reader meets them."""
    head_ids = {id(w) for w in head.words}
    body = [w for w in page.words if id(w) not in head_ids]
    return sorted(body, key=lambda w: (w.column, w.line, w.left))


def _join_lines(words: list[Word]) -> str:
    """Assemble text, rejoining words broken across line ends.

    A trailing hyphen at a line break is usually syllabification ("knowl-" +
    "edge"), so the hyphen goes. When the continuation is capitalised it is
    more likely a real compound ("Rose-" + "Croix"), so the hyphen stays.
    """
    if not words:
        return ""
    pieces: list[str] = []
    pending_hyphen = False
    current_line = words[0].line
    for word in words:
        text = word.text
        if pending_hyphen:
            if text[:1].isupper():
                pieces.append("-" + text)
            else:
                pieces.append(text)
            pending_hyphen = False
            current_line = word.line
            continue
        if word.line != current_line:
            current_line = word.line
        if text.endswith("-") and len(text) > 1:
            pieces.append(" " + text[:-1] if pieces else text[:-1])
            pending_hyphen = True
            continue
        pieces.append(" " + text if pieces else text)
    text = "".join(pieces)
    # OCR of this scan leaves spaces before terminal punctuation.
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return re.sub(r"\s{2,}", " ", text).strip()


# Stroke width is quantised by the distance transform -- body text measures
# 4.00 and the next step up is 4.47 -- so this threshold sits just above the
# page median rather than at a fraction that could fall between two steps.
LOOSE_BOLD_RATIO = 1.05
SENTENCE_END = (".", ";", ":", "!", "?", "’", "\"")
CONNECTORS = {"of", "the", "and", "de", "du", "da", "von", "van", "le", "la", "des"}
ROMAN_NUMERAL = re.compile(r"^(?:I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII)\.$")


def _extend_backwards(words: list[Word], start: int, loose: float) -> int:
    """Recover a headword's opening words when OCR under-measured their weight.

    "Cooke Manuscript." and "Sons of the Prophets." lose their first words when
    only the later ones clear the bold threshold, which leaves a truncated
    headword that then breaks alphabetical order. Walking back with a looser
    threshold recovers them.
    """
    first = words[start]
    position = start
    while position > 0 and (start - position) < 4:
        previous = words[position - 1]
        current = words[position]
        if previous.line == current.line:
            if current.left - previous.right > 120:
                break
        elif previous.line == current.line - 1 and previous.column == current.column:
            # A headword may wrap a line. Only accept the wrap when `previous`
            # genuinely ends its line and `current` begins the next.
            line_words = [w for w in words if w.line == previous.line]
            next_words = [w for w in words if w.line == current.line]
            if previous is not max(line_words, key=lambda w: w.left):
                break
            if current is not min(next_words, key=lambda w: w.left):
                break
        else:
            break
        text = previous.text.strip()
        if text.endswith(SENTENCE_END) and not _is_abbreviation(text):
            break                               # that is the previous entry
        is_connector = text.lower().strip(",") in CONNECTORS
        if previous.stroke_width < loose and not is_connector:
            break
        position -= 1
    # A headword starts with a capital; if walking back did not reach one,
    # the extension was wrong and the original start stands.
    while position < start and not HEADWORD_START.match(words[position].text):
        position += 1
    return position


def _headword_spans(words: list[Word], loose_threshold: float = 0.0) -> list[tuple[int, int]]:
    """Index ranges over `words` that form headwords.

    A span opens on a bold word that starts with a capital, and closes on the
    first word ending in a period. Non-bold words are absorbed while the span
    is open: OCR occasionally misses the weight of one word inside a bold run
    ("Babylon, Red Cross of." loses "Cross"), and closing on the period
    recovers it.
    """
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(words):
        word = words[index]
        if not word.bold or not HEADWORD_START.match(word.text):
            index += 1
            continue
        if word.text.isupper() and len(word.text) > 3:
            # A stray all-caps token is a running-head remnant, not a headword.
            index += 1
            continue

        end = None
        for offset in range(MAX_HEADWORD_WORDS):
            position = index + offset
            if position >= len(words):
                break
            candidate = words[position]
            if offset > 0 and candidate.line - words[position - 1].line > 1:
                break      # ran past a line without closing: not a headword
            if not candidate.text.rstrip().endswith(TERMINATES):
                continue
            # A period does not always end a headword. "Lodge of St. John."
            # and "Zschokke, J. H. D." both carry internal periods, so closing
            # on the first one truncates the headword and leaves the remainder
            # to open a spurious entry out of alphabetical order.
            following = words[position + 1] if position + 1 < len(words) else None
            if following is not None and following.bold:
                continue                      # bold continues: still inside it
            if _is_abbreviation(candidate.text) and following is not None:
                continue                      # "St.", "J.", "Mt." are internal
            end = position
            break
        if end is None:
            index += 1
            continue

        bold_count = sum(1 for w in words[index:end + 1] if w.bold)
        if bold_count < max(1, (end - index + 1) // 2):
            index += 1
            continue

        # Numbered divisions inside a long article ("I.", "II.") are set bold
        # and are not headwords.
        if ROMAN_NUMERAL.match(words[index].text.strip()) and index == end:
            index += 1
            continue

        start = _extend_backwards(words, index, loose_threshold) if loose_threshold else index
        if spans and start <= spans[-1][1]:
            start = index                       # never overlap the previous span
        spans.append((start, end))
        index = end + 1
    return spans


def parse_page(page: Page, head: RunningHead, region: str) -> list[Entry]:
    """Entries beginning on this page, plus any leading continuation."""
    words = reading_order(page, head)
    if not words:
        return []

    spans = _headword_spans(words, loose_threshold=page.median_stroke * LOOSE_BOLD_RATIO)
    entries: list[Entry] = []

    def confidence_of(slice_: list[Word]) -> float:
        values = [w.conf for w in slice_ if w.conf >= 0]
        return sum(values) / len(values) if values else 0.0

    if not spans:
        # No headword anywhere: the whole page continues a previous entry.
        return [Entry(headword="", body=_join_lines(words), pdf_page=page.pdf_page,
                      printed_page=head.printed_page, region=region,
                      confidence=confidence_of(words), is_continuation=True)]

    first_start = spans[0][0]
    if first_start > 0:
        lead = words[:first_start]
        entries.append(Entry(headword="", body=_join_lines(lead),
                             pdf_page=page.pdf_page, printed_page=head.printed_page,
                             region=region, confidence=confidence_of(lead),
                             is_continuation=True))

    for position, (start, end) in enumerate(spans):
        stop = spans[position + 1][0] if position + 1 < len(spans) else len(words)
        headword = _join_lines(words[start:end + 1])
        body = _join_lines(words[end + 1:stop])
        issues: list[str] = []
        if not body:
            issues.append("empty_body")
        if len(headword) < 3:
            issues.append("short_headword")
        entries.append(Entry(headword=headword, body=body, pdf_page=page.pdf_page,
                             printed_page=head.printed_page, region=region,
                             confidence=confidence_of(words[start:stop]),
                             issues=issues))
    return entries
