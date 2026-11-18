"""Running-head parsing and page-region classification.

The book holds three regions that need three different parsers:

    main           ~pp.  11-883   two-column prose, bold headwords
    pronouncing    ~pp. 884-911   three-column table
    bibliography   ~pp. 912-946   author and works list

Region is decided from the running head rather than from a page range, so the
boundaries do not have to be known in advance and drift in the scan cannot
misclassify a page.

The printed page number also comes from the running head. It must not be
computed from the PDF page number: the offset drifts through the book (PDF 30
is printed 21, PDF 100 is 89, PDF 840 is 836) because of unnumbered plates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..extract.ocr import Page, Word

FRONT_MARKERS = ("PREFACE", "PUBLISHERS' NOTE", "PUBLISHERS\u2019 NOTE",
                 "LIST OF ILLUSTRATIONS")
PRONOUNCING_MARKERS = ("PRONOUNCING", "PRONUNCIATION", "NOTATIONS")
BIBLIOGRAPHY_MARKERS = ("BIBLIOGRAPHY",)

REGION_MAIN = "main"
REGION_FRONT = "front"
REGION_PRONOUNCING = "pronouncing"
REGION_BIBLIOGRAPHY = "bibliography"
REGION_PLATE = "plate"

_PAGE_NUMBER = re.compile(r"^\d{1,4}$")


@dataclass
class RunningHead:
    words: list[Word]
    printed_page: int | None
    left_guide: str | None     # first entry on the page, per the head
    right_guide: str | None    # last entry on the page
    raw: str

    @property
    def bottom(self) -> int:
        return max((w.bottom for w in self.words), default=0)


def find_running_head(page: Page) -> RunningHead:
    """The topmost line of the page, if it looks like a running head.

    Identified by position rather than content: the head sits alone above the
    body with a clear gap. Returns an empty head when the page has none.
    """
    if not page.words:
        return RunningHead([], None, None, None, "")

    top_y = min(w.middle_y for w in page.words)
    typical_height = sorted(w.height for w in page.words)[len(page.words) // 2]
    band = [w for w in page.words if w.middle_y - top_y <= typical_height * 1.2]
    if not band:
        return RunningHead([], None, None, None, "")

    # A head is separated from the body by more than a line's leading. Without
    # that gap this is just the first line of text.
    below = [w.middle_y for w in page.words if w not in band]
    if below and (min(below) - top_y) < typical_height * 1.6:
        return RunningHead([], None, None, None, "")

    band.sort(key=lambda w: w.left)
    raw = " ".join(w.text for w in band)

    printed_page = None
    guides: list[str] = []
    for word in band:
        token = word.text.strip(".,;:'\"‘’")
        # Folios pick up stray marks from the scan edge ("«627"), so digits
        # are extracted rather than matched against the token as a whole.
        digits = re.sub(r"\D", "", token)
        if digits and len(digits) >= 2 and len(digits) == len(token.strip("«»‹›|.,'‘’\"<>()[]-_ ")):
            printed_page = int(digits)
            continue
        if _PAGE_NUMBER.match(token) and len(token) >= 2:
            printed_page = int(token)
            continue
        letters = [c for c in token if c.isalpha()]
        if len(letters) >= 3 and sum(c.isupper() for c in letters) >= len(letters) * 0.6:
            guides.append(token.upper())

    left_guide = guides[0] if guides else None
    right_guide = guides[-1] if len(guides) > 1 else None
    return RunningHead(band, printed_page, left_guide, right_guide, raw)


def classify(page: Page, head: RunningHead) -> str:
    """Which region this page belongs to."""
    if not page.words:
        return REGION_PLATE

    # The running head alone is not enough: on the Pronouncing Dictionary
    # pages the head often OCRs to noise ("tl"), and the page then parses as
    # main-dictionary prose and yields dozens of spurious entries.
    #
    # So the top of the body is searched too, but only for markers that appear
    # there in capitals. Matching case-insensitively would catch any article
    # that happens to discuss pronunciation.
    head_text = head.raw.upper()
    body_text = " ".join(w.text for w in page.words[:60])

    def seen(markers: tuple[str, ...]) -> bool:
        if any(marker in head_text for marker in markers):
            return True
        return any(marker in body_text for marker in markers)

    # The prefaces carry a running head but no Arabic folio, and read as
    # ordinary prose, so they were parsed as articles: the publishers' note
    # gave its last line as a headword and the article on the letter A, which
    # begins on the page after it, was filed under "T. M. H. Co."
    if head.printed_page is None and any(m in head_text for m in FRONT_MARKERS):
        return REGION_FRONT

    if seen(BIBLIOGRAPHY_MARKERS):
        return REGION_BIBLIOGRAPHY
    if seen(PRONOUNCING_MARKERS):
        return REGION_PRONOUNCING

    # A page with very little text and no head is a plate or a blank.
    if len(page.words) < 40:
        return REGION_PLATE
    return REGION_MAIN


def within_guides(headword: str, head: RunningHead) -> bool | None:
    """Does this headword fall between the page's running heads?

    An independent check on segmentation: a headword outside the guides is
    either a false positive or evidence the head was misread. Returns None when
    the guides are unavailable and no judgement can be made.
    """
    if not head.left_guide or not head.right_guide:
        return None
    key = headword.upper()
    lo, hi = head.left_guide, head.right_guide
    if lo > hi:
        lo, hi = hi, lo
    # Compare on the shared prefix length the guides actually provide.
    return lo[: len(key)] <= key[: max(len(lo), len(hi))] or key >= lo
