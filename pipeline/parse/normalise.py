"""Normalisation rules shared by the pipeline and the web app.

CRITICAL: app/src/core/normalise.ts must behave identically to this module.
A query normalised differently from the stored text silently returns nothing,
and it presents as a search bug rather than a normalisation bug.

Both implementations are tested against tests/fixtures/normalise.json. If you
change a rule here, change it there and regenerate the fixtures.
"""

from __future__ import annotations

import re
import unicodedata

# Punctuation is stripped except apostrophes and hyphens *between* word
# characters: "Mason's" and "Rose-Croix" keep their shape, while a trailing
# headword period or a leading quote does not.
_INNER_HYPHEN = re.compile(r"(?<=\w)-(?=\w)")
_INNER_APOSTROPHE = re.compile(r"(?<=\w)['’](?=\w)")
_HYPHEN_MARK = "\x00"
_APOSTROPHE_MARK = "\x01"
# The two marks are excluded here so they survive to be restored below.
_NON_WORD = re.compile(r"[^\w\s\x00\x01]", re.UNICODE)
_WS = re.compile(r"\s+")


def strip_diacritics(text: str) -> str:
    """Maçon -> Macon, Thébäische -> Thebaische.

    Decompose, drop combining marks, recompose. Handles the French, German and
    transliterated Hebrew that run through this book.
    """
    decomposed = unicodedata.normalize("NFD", text)
    without_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    # A few letters carry no combining mark and must be mapped explicitly.
    table = str.maketrans({
        "ß": "ss", "æ": "ae", "Æ": "ae",
        "œ": "oe", "Œ": "oe", "ø": "o", "Ø": "o",
        "đ": "d", "Đ": "d", "þ": "th", "Þ": "th",
    })
    return unicodedata.normalize("NFC", without_marks.translate(table))


def normalise(text: str) -> str:
    """The canonical form used for matching, in both engines.

    Lowercase, diacritics removed, inner hyphens and apostrophes kept, all
    other punctuation dropped, whitespace collapsed.

    >>> normalise("Babylon, Red Cross of.")
    'babylon red cross of'
    >>> normalise("  Maçon   ")
    'macon'
    >>> normalise("Rose-Croix")
    'rose-croix'
    >>> normalise("Mason's Word")
    "mason's word"
    """
    if not text:
        return ""
    # Italic markers are carried inline in stored text; they are styling, not
    # content, and must never reach a match key.
    text = text.replace("\x02", "").replace("\x03", "")
    text = strip_diacritics(text)
    text = text.lower()
    text = _INNER_HYPHEN.sub(_HYPHEN_MARK, text)
    text = _INNER_APOSTROPHE.sub(_APOSTROPHE_MARK, text)
    text = _NON_WORD.sub(" ", text)
    text = text.replace(_HYPHEN_MARK, "-").replace(_APOSTROPHE_MARK, "'")
    return _WS.sub(" ", text).strip()


def sort_key(text: str) -> str:
    """Ordering key. Like normalise(), but hyphens and apostrophes also go,
    so that "Rose-Croix" and "Rose Croix" sort together.

    >>> sort_key("Rose-Croix")
    'rose croix'
    """
    plain = normalise(text).replace("-", " ").replace("'", " ")
    return _WS.sub(" ", plain).strip()


def first_letter(text: str) -> str:
    """The A-Z bucket for the index. Non-alphabetic headwords bucket as '#'."""
    key = sort_key(text)
    if key and key[0].isalpha():
        return key[0].upper()
    return "#"
