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
    "ch.", "fr.", "ger.", "lat.", "heb.", "gr.",
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
    rejected: bool = False
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
            "rejected": self.rejected,
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


SENTENCE_END = (".", ";", ":", "!", "?", "’", "\"")

# A sentence may close with the stop inside or before a quotation mark, and
# Mackey quotes constantly. Matching only a bare "." missed 81 real headwords
# in volume 2 alone, every one of them following a quoted passage.
SENTENCE_CLOSE = re.compile(r"[.!?][\"'‘’“”)\]]*$")
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
        # Must use the same test as the anchor check below. With a narrower
        # one, the walk stepped over "Ground.)" into the previous sentence,
        # and the span it built then failed its own anchor test and was lost
        # -- which is how "Zerubbabel." went missing entirely.
        if SENTENCE_CLOSE.search(text) and not _is_abbreviation(text):
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
            # Only an abbreviation or initial keeps a headword open past a full
            # stop. Treating "the next word is also bold" as continuation was
            # too loose: a short word after the headword can measure bold by
            # itself, and "Zerubbabel. In writing..." then never closed, losing
            # the entry altogether.
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

        # A span that nothing closed before it is kept, but marked. A headword
        # dropped in silence is invisible to a reader who searches for it; a
        # spurious one is visible and can be struck out in review. So the
        # doubtful ones are carried through to the correction pass rather than
        # discarded here.
        anchored = _follows_sentence_end(words, start)
        spans.append((start, end, anchored))
        index = end + 1
    return spans


def _follows_sentence_end(words: list[Word], start: int) -> bool:
    """A headword opens an entry, so something must have closed the last one.

    This is the check that separates headwords from italics. Mackey sets
    French and German book titles in italic throughout, and on volume 2's
    heavier scan their strokes measure as thick as bold -- "dans la Voie
    Profane" and the like then parse as headwords. Weight cannot tell them
    apart, but position can: a headword follows a full stop or begins the
    page, while an italic title sits inside a sentence.
    """
    if start == 0:
        return True
    previous = words[start - 1].text.rstrip()
    if not previous:
        return True
    if _is_abbreviation(previous):
        return False                 # "St." mid-headword, not a sentence end
    return bool(SENTENCE_CLOSE.search(previous))


def parse_page(page: Page, head: RunningHead, region: str) -> list[Entry]:
    """Entries beginning on this page, plus any leading continuation."""
    words = reading_order(page, head)
    if not words:
        return []

    spans = _headword_spans(words, loose_threshold=page.loose_threshold)
    entries: list[Entry] = []

    def confidence_of(slice_: list[Word]) -> float:
        values = [w.conf for w in slice_ if w.conf >= 0]
        return sum(values) / len(values) if values else 0.0

    if not spans:
        # No headword anywhere: the whole page continues a previous entry.
        return [Entry(headword="", body=_join_lines(words), pdf_page=page.pdf_page,
                      printed_page=head.printed_page, region=region,
                      confidence=confidence_of(words), is_continuation=True)]

    anchored_spans = [s for s in spans if s[2]]
    first_start = (anchored_spans[0][0] if anchored_spans else spans[0][0])
    if first_start > 0:
        lead = words[:first_start]
        entries.append(Entry(headword="", body=_join_lines(lead),
                             pdf_page=page.pdf_page, printed_page=head.printed_page,
                             region=region, confidence=confidence_of(lead),
                             is_continuation=True))

    for position, (start, end, anchored) in enumerate(spans):
        stop = spans[position + 1][0] if position + 1 < len(spans) else len(words)
        headword = _join_lines(words[start:end + 1])
        body = _join_lines(words[end + 1:stop])
        issues: list[str] = []
        if not body:
            issues.append("empty_body")
        if len(headword) < 3:
            issues.append("short_headword")
        if not anchored:
            issues.append("unanchored")
        entries.append(Entry(headword=headword, body=body, pdf_page=page.pdf_page,
                             printed_page=head.printed_page, region=region,
                             confidence=confidence_of(words[start:stop]),
                             rejected=not anchored, issues=issues))
    return entries
