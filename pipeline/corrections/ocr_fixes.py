"""Repair OCR misreads in headwords, using alphabetical order as the test.

Tesseract confuses a small, predictable set of letter shapes on this typeface:
`Franeis` for Francis, `Fiaming` for Flaming, `Widew` for Widow, `Seroll` for
Scroll. Left alone each one breaks search -- nobody finds "Scroll" by typing
it -- and each one shows up as a headword out of alphabetical order.

That gives a test rather than a guess. A substitution is applied only when it
moves the headword back into order with its neighbours. Anything that does not
is left alone and reported, so the correction never rests on a hunch about what
a word ought to be.

Only headwords are repaired. Body text is left exactly as OCR'd: an error there
is visible to a reader in context, while an error in a headword silently hides
the entry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import product

from ..parse.normalise import sort_key

# Shape confusions, both directions where the pair is genuinely ambiguous in
# this typeface. Order matters only for reporting.
CONFUSIONS: list[tuple[str, str]] = [
    ("e", "c"), ("c", "e"),
    ("i", "l"), ("l", "i"),
    ("I", "l"), ("l", "I"),
    ("rn", "m"), ("m", "rn"),
    ("e", "o"), ("o", "e"),
    ("a", "o"), ("o", "a"),
    ("h", "b"), ("b", "h"),
    ("t", "f"), ("f", "t"),
    ("s", "8"), ("8", "s"),
    ("0", "o"), ("o", "0"),
    ("1", "l"), ("l", "1"),
    ("u", "n"), ("n", "u"),
    ("v", "y"), ("y", "v"),
    ("ii", "u"), ("cl", "d"),
    ("J", "I"), ("G", "C"), ("C", "G"),
    ("E", "B"), ("B", "E"),
]

MAX_EDITS = 2            # two substitutions is already generous for one headword
MAX_VARIANTS = 4000      # guard against combinatorial blow-up on long headwords

# A correction must make the word commoner, not merely better-sorted. Without
# this, the ordering test alone will happily corrupt a correct headword into
# nonsense that happens to sort where the gap is -- it turned "Abracadabra."
# into "Abraeodabra." on the first run.
# Raised after review. The corpus is its own lexicon, so a systematic OCR
# error is itself attested: "geometrie" appears six times because the same
# c-for-e misread happens elsewhere, which was enough to "correct" a perfectly
# good "Geometric Points." into it. Corrections verified against the page
# images live in overrides.json instead.
MIN_EVIDENCE = 10        # the corrected token must appear at least this often
MIN_RATIO = 3.0          # ...and this many times more often than the original

_TOKEN = re.compile(r"[A-Za-zÀ-ɏ']+")


def build_lexicon(entries: list[dict]) -> dict[str, int]:
    """Token frequencies over all extracted body text.

    The corpus is its own best dictionary here. A general English word list
    would not hold Tetragrammaton, Kadosh, Maçonnerie or the several thousand
    proper names this book turns on, and would reject correct headwords as
    readily as wrong ones. Body text runs to about four million characters, so
    a word Mackey uses is well attested within it.
    """
    counts: dict[str, int] = {}
    for entry in entries:
        for token in _TOKEN.findall(entry.get("body", "")):
            lowered = token.lower()
            counts[lowered] = counts.get(lowered, 0) + 1
    return counts


def _more_plausible(before: str, after: str, lexicon: dict[str, int]) -> bool:
    """True when every word the edit touched became markedly commoner."""
    old_tokens = _TOKEN.findall(before)
    new_tokens = _TOKEN.findall(after)
    if len(old_tokens) != len(new_tokens):
        return False
    changed = False
    for old, new in zip(old_tokens, new_tokens):
        if old == new:
            continue
        changed = True
        old_count = lexicon.get(old.lower(), 0)
        new_count = lexicon.get(new.lower(), 0)
        # Only words that look like misreads are touched. When a headword is
        # out of order it may be its neighbour that is wrong, and without this
        # the edit lands on the innocent one -- it turned a correct "Geometric
        # Points." into "Geometrie Points." because the entry before it was
        # the one actually misread.
        if old_count >= MIN_EVIDENCE:
            return False
        if new_count < MIN_EVIDENCE:
            return False
        if new_count < max(MIN_RATIO * old_count, MIN_EVIDENCE):
            return False
    return changed


@dataclass
class Fix:
    pdf_page: int
    before: str
    after: str
    reason: str

    def as_dict(self) -> dict:
        return {"pdf_page": self.pdf_page, "before": self.before,
                "after": self.after, "reason": self.reason}


def _variants(text: str, max_edits: int = MAX_EDITS) -> list[str]:
    """Every spelling reachable by at most `max_edits` shape substitutions."""
    sites: list[list[tuple[int, str, str]]] = []
    for wrong, right in CONFUSIONS:
        for match in re.finditer(re.escape(wrong), text):
            sites.append([(match.start(), wrong, right)])
    flat = [site[0] for site in sites]
    if not flat:
        return []

    results: set[str] = set()
    for count in range(1, max_edits + 1):
        for combination in product(flat, repeat=count):
            positions = [c[0] for c in combination]
            if len(set(positions)) != len(positions):
                continue
            edited = text
            for position, wrong, right in sorted(combination, key=lambda c: -c[0]):
                edited = edited[:position] + right + edited[position + len(wrong):]
            results.add(edited)
            if len(results) > MAX_VARIANTS:
                return list(results)
    results.discard(text)
    return list(results)


# Editorial initials closed by a bracket, carried over from the printed page's
# margin: "L. H.] Abiram." The entry is Abiram, and left alone nobody searching
# for it finds it.
_MARGIN_MARK = re.compile(r"^[\[\(]?\s*[A-Z]\.?\s*[A-Z]\.?\s*[\]\}\)][-\s,]*")


def strip_artifacts(sequence: list[dict]) -> list[Fix]:
    """Remove marginal marks that OCR glued onto the front of a headword."""
    fixes: list[Fix] = []
    for entry in sequence:
        headword = entry.get("headword", "")
        match = _MARGIN_MARK.match(headword)
        if not match:
            continue
        cleaned = headword[match.end():].strip()
        if len(cleaned) < 3 or not cleaned[0].isupper():
            continue
        fixes.append(Fix(entry["pdf_page"], headword, cleaned, "margin_mark_removed"))
        entry["headword"] = cleaned
        entry.setdefault("issues", []).append("margin_mark_removed")
    return fixes


def repair(sequence: list[dict]) -> list[Fix]:
    """Fix out-of-order headwords where a shape substitution restores order.

    `sequence` is every accepted entry in document order; headwords are edited
    in place. Returns what was changed.
    """
    fixes: list[Fix] = []
    live = [e for e in sequence
            if not e.get("rejected") and not e["is_continuation"] and e["headword"]]
    lexicon = build_lexicon(sequence)

    for index in range(1, len(live)):
        entry = live[index]
        previous_key = sort_key(live[index - 1]["headword"])
        key = sort_key(entry["headword"])
        if key >= previous_key:
            continue                       # already in order

        following_key = (sort_key(live[index + 1]["headword"])
                         if index + 1 < len(live) else "￿")

        best: str | None = None
        best_count = 0
        for candidate in _variants(entry["headword"]):
            candidate_key = sort_key(candidate)
            if not (previous_key <= candidate_key <= following_key):
                continue
            if not _more_plausible(entry["headword"], candidate, lexicon):
                continue
            # Among the spellings that both sort correctly and are attested,
            # take the best attested.
            score = min((lexicon.get(t.lower(), 0) for t in _TOKEN.findall(candidate)),
                        default=0)
            if score > best_count:
                best, best_count = candidate, score
        if best is None:
            continue

        fixes.append(Fix(entry["pdf_page"], entry["headword"], best,
                         f"restores_order; corrected form attested {best_count}x"))
        entry["headword"] = best
        entry.setdefault("issues", []).append("ocr_corrected")

    return fixes


def apply_overrides(sequence: list[dict], overrides: dict[str, str]) -> list[Fix]:
    """Apply hand-written corrections from corrections/overrides.json.

    These take precedence over anything inferred. The file maps a headword
    exactly as extracted to its corrected form, so a reviewer can fix what the
    structural test cannot reach.
    """
    fixes: list[Fix] = []
    for entry in sequence:
        replacement = overrides.get(entry.get("headword", ""))
        if replacement:
            fixes.append(Fix(entry["pdf_page"], entry["headword"], replacement,
                             "manual_override"))
            entry["headword"] = replacement
            entry.setdefault("issues", []).append("manual_override")
    return fixes
