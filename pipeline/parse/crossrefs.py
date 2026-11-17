"""Find the cross-references Mackey threads through the book.

He refers constantly -- "See Captivity.", "(See Temple, Order of.)", "which
see." -- and those references are the structure of the work. Followed, they
turn a flat list of articles into something you can navigate.

A reference is only recorded as resolved when its target matches a headword we
actually extracted. Unresolved ones are kept with their raw text rather than
dropped: they are evidence of entries the extraction missed, and they are a
better list of what is absent than anything we could derive from the entries
alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .normalise import sort_key

# "(See Temple, Order of.)" / "See Captivity." / "See also Ark."
_PARENTHESISED = re.compile(r"\((?:see|cf\.?)\s+(?:also\s+)?([^)]{2,80})\)", re.IGNORECASE)
_BARE = re.compile(r"(?:^|[.;]\s+)See\s+(?:also\s+)?([A-Z][^.;]{1,70})\.", re.MULTILINE)
# "...the degree of Babylonish Pass, which see." The reference is to whatever
# term immediately precedes it, which may be one word or several and is not
# always capitalised ("a baculus, which see").
_WHICH_SEE = re.compile(
    r"((?:[A-Za-z][\w'’-]*)(?:\s+[A-Za-z][\w'’-]*){0,3})\s*,?\s*which see",
    re.IGNORECASE)

_TRAILING = re.compile(r"\s*(?:,\s*)?(?:q\.?v\.?|which see)\s*$", re.IGNORECASE)

# Mackey cites scripture constantly ("See Exodus xvii. 10-12."). Those are
# citations, not cross-references to other articles, and recording them as
# links would point at entries that do not exist.
_BIBLE_BOOKS = {
    "genesis", "exodus", "leviticus", "numbers", "deuteronomy", "joshua",
    "judges", "ruth", "samuel", "kings", "chronicles", "ezra", "nehemiah",
    "esther", "job", "psalm", "psalms", "proverbs", "ecclesiastes", "isaiah",
    "jeremiah", "lamentations", "ezekiel", "daniel", "hosea", "joel", "amos",
    "obadiah", "jonah", "micah", "nahum", "habakkuk", "zephaniah", "haggai",
    "zechariah", "malachi", "matthew", "mark", "luke", "john", "acts",
    "romans", "corinthians", "galatians", "ephesians", "philippians",
    "colossians", "thessalonians", "timothy", "titus", "philemon", "hebrews",
    "james", "peter", "jude", "revelation", "gen", "exod", "lev", "num",
    "deut", "josh", "judg", "sam", "chron", "neh", "esth", "ps", "prov",
    "eccl", "isa", "jer", "lam", "ezek", "dan", "hab", "zech", "mal", "matt",
    "rom", "cor", "gal", "eph", "phil", "col", "thess", "tim", "philem",
    "heb", "pet", "rev",
}


def _is_citation(target: str) -> bool:
    """True for a scripture or page citation rather than an article title."""
    tokens = [t.strip(".,;:()").lower() for t in target.split()]
    tokens = [t for t in tokens if t]
    if not tokens:
        return True
    head = tokens[1] if (tokens[0].isdigit() and len(tokens) > 1) else tokens[0]
    return head in _BIBLE_BOOKS

# Grammatical fragments the patterns sometimes pick up instead of a term.
_STOPWORDS = {
    "the", "a", "an", "it", "this", "that", "these", "those", "which", "him",
    "them", "the power", "the same", "the word", "the above", "the first",
    "the second", "he", "she", "they", "we", "you", "its", "his", "her",
    "and", "or", "but", "of", "in", "on", "to", "for", "with", "by",
}

# Lead-ins that are part of the sentence, not the term.
_LEAD_IN = re.compile(
    r"^(?:the|a|an|his|her|its|their|our|this|that|of|is|was|were|are|be|been|"
    r"called|named|styled|termed|known as|word|term|degree|order|rite)\s+",
    re.IGNORECASE)


@dataclass
class CrossRef:
    raw_target: str
    kind: str              # 'see' | 'see_also'
    resolved_id: int | None = None

    def as_dict(self) -> dict:
        return {"raw_target": self.raw_target, "kind": self.kind,
                "resolved_id": self.resolved_id}


def _clean(target: str) -> str:
    text = target.strip()
    text = _TRAILING.sub("", text)
    text = text.strip(" .,;:“”\"'")
    # Keep only the first clause: "Temple, Order of" survives, a trailing
    # explanatory sentence does not.
    text = re.split(r"\s+(?:and|or)\s+", text)[0] if len(text) > 40 else text
    return text.strip()


def extract(body: str) -> list[CrossRef]:
    """Cross-references mentioned in one entry's body.

    Italic markers are stripped first. Mackey sets the target of a reference
    in italic, so the marker lands between "See " and the name -- and the
    patterns, which expect a capital there, stopped matching. That quietly
    halved the resolved references when italics were introduced.
    """
    body = body.replace("\x02", "").replace("\x03", "")
    found: list[CrossRef] = []
    seen: set[str] = set()

    def add(raw: str, kind: str) -> None:
        target = _clean(raw)
        # Strip a grammatical lead-in, but only while something is left.
        while True:
            shortened = _LEAD_IN.sub("", target, count=1).strip()
            if shortened == target or len(shortened) < 3:
                break
            target = shortened
        if len(target) < 3 or len(target) > 70:
            return
        if not any(c.isalpha() for c in target):
            return
        if target.lower() in _STOPWORDS:
            return
        if _is_citation(target):
            return
        # A target that is mostly digits or roman numerals is a citation.
        letters = sum(c.isalpha() for c in target)
        if letters < max(3, len(target) * 0.5):
            return
        key = target.lower()
        if key in seen:
            return
        seen.add(key)
        found.append(CrossRef(target, kind))

    for match in _PARENTHESISED.finditer(body):
        add(match.group(1), "see_also")
    for match in _BARE.finditer(body):
        add(match.group(1), "see")
    for match in _WHICH_SEE.finditer(body):
        add(_which_see_target(match.group(1)), "see")
    return found


def _which_see_target(phrase: str) -> str:
    """Narrow "...staff was a baculus, which see" down to the term itself.

    "which see" points at whatever immediately precedes it. When the phrase
    holds a capitalised word the term starts there ("Babylonish Pass"); when it
    is all lower case the term is the final word ("baculus").
    """
    words = phrase.split()
    if not words:
        return phrase
    for index, word in enumerate(words):
        if word[:1].isupper() and index > 0:
            return " ".join(words[index:])
    if words[0][:1].isupper():
        return phrase
    return words[-1]


def resolve(entries: list[dict]) -> tuple[int, int]:
    """Attach cross-references to entries and link them to targets by headword.

    Returns (total found, number resolved).
    """
    index: dict[str, int] = {}
    for entry in entries:
        key = sort_key(entry["headword"])
        if key and key not in index:
            index[key] = entry["id"]

    total = resolved = 0
    for entry in entries:
        refs = extract(entry.get("body", ""))
        for ref in refs:
            total += 1
            target_id = index.get(sort_key(ref.raw_target))
            if target_id is not None and target_id != entry["id"]:
                ref.resolved_id = target_id
                resolved += 1
        entry["crossrefs"] = [r.as_dict() for r in refs]
    return total, resolved
