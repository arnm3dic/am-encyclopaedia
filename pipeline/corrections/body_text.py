"""Repair systematic OCR misreads in the body text.

Headwords were re-read from the page images; body text was not, and it still
carries the engine's habitual confusions -- `Maaonic` for Masonic, `Anderaon`
for Anderson, `frecmasonry` for freemasonry. These matter because definition
search is built on this text: an entry that says `Maaonic` cannot be found by
searching for Masonic.

Deciding what to repair needs two tests, not one.

The first is frequency: a rare spelling whose single-substitution neighbour is
common is a candidate. On its own that test is wrong often enough to do damage
-- `stops` is rare here and `steps` is common, but `stops` is a perfectly good
word, and so are `wove` and `bails`.

The second test is whether the token looks like English at all. A character
trigram model built from the corpus's own common words scores `maaonic` far
below `stops`, because `aao` barely occurs in English while every part of
`stops` is ordinary. Only tokens that fail both tests are touched.

No modern dictionary is used, here or anywhere else in the pipeline: this text
writes practise, sepulcher, antient and connexion, and a word list would
reject them.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

TOKEN = re.compile(r"[A-Za-zÀ-ɏ]+")

# Shapes this engine confuses on this typeface, in both directions.
CONFUSIONS: list[tuple[str, str]] = [
    ("a", "s"), ("s", "a"), ("e", "c"), ("c", "e"), ("i", "l"), ("l", "i"),
    ("o", "e"), ("e", "o"), ("n", "u"), ("u", "n"), ("h", "b"), ("b", "h"),
    ("t", "f"), ("f", "t"), ("v", "r"), ("r", "v"), ("m", "rn"), ("rn", "m"),
    ("d", "cl"), ("cl", "d"), ("g", "q"), ("q", "g"), ("ii", "n"),
]

RARE = 2          # the suspect spelling occurs at most this often
COMMON = 25       # ...and its neighbour at least this often
MIN_LENGTH = 4
MARGIN = 1.1      # the repair must score this much better per trigram


@dataclass
class BodyFix:
    before: str
    after: str
    occurrences: int
    score_before: float
    score_after: float

    def as_dict(self) -> dict:
        return {"before": self.before, "after": self.after,
                "occurrences": self.occurrences,
                "score_before": round(self.score_before, 2),
                "score_after": round(self.score_after, 2)}


class EnglishShape:
    """How ordinary a word's letters look, judged by the corpus's own prose.

    Trained only on words the corpus uses often, so the model learns what this
    book's English looks like -- including its French, Latin and Hebrew -- and
    not what a modern dictionary thinks words should be.
    """

    def __init__(self, common: dict[str, int]):
        self.trigrams: Counter[str] = Counter()
        self.bigrams: Counter[str] = Counter()
        for word, count in common.items():
            padded = f"  {word} "
            weight = min(count, 500)      # don't let "the" dominate
            for i in range(len(padded) - 2):
                self.trigrams[padded[i:i + 3]] += weight
                self.bigrams[padded[i:i + 2]] += weight
        self.vocabulary = len({t[0] for t in self.trigrams} | {"a"})

    def score(self, word: str) -> float:
        """Mean log probability per trigram. Higher is more ordinary."""
        padded = f"  {word.lower()} "
        if len(padded) < 3:
            return -99.0
        total = 0.0
        count = 0
        for i in range(len(padded) - 2):
            trigram = padded[i:i + 3]
            context = self.bigrams.get(trigram[:2], 0)
            # Laplace smoothing keeps an unseen trigram finite but costly.
            probability = (self.trigrams.get(trigram, 0) + 0.1) / (context + 0.1 * 40)
            total += math.log(probability)
            count += 1
        return total / count


def build_counts(entries: list[dict]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for entry in entries:
        for token in TOKEN.findall(entry.get("body", "")):
            counts[token.lower()] += 1
    return counts


def _variants(word: str) -> list[str]:
    out: list[str] = []
    for wrong, right in CONFUSIONS:
        start = 0
        while True:
            at = word.find(wrong, start)
            if at == -1:
                break
            out.append(word[:at] + right + word[at + len(wrong):])
            start = at + 1
    return out


def second_opinion(path: Path) -> set[str]:
    """Words the 2007 OCR of this scan also read.

    The PDF carries an OmniPage text layer over volume 1 from 2007. It is
    useless for structure -- it splices the two columns together mid-line --
    but as a bag of words it is an independent reading of the same ink by a
    different engine fifteen years earlier. A rare spelling both engines
    produce is probably on the page; one only this pass produced is probably
    a misread. It protects `wove`, `theo` and `stops`, which the frequency and
    shape tests between them would have "corrected" into other words.

    It covers volume 1 only, so M-Z has no such protection.
    """
    if not path.exists():
        return set()
    text = path.read_text(encoding="utf-8", errors="replace")
    return {word.lower() for word in TOKEN.findall(text)}


def plan(entries: list[dict], attested: set[str] | None = None) -> list[BodyFix]:
    """Decide which body-text tokens to repair."""
    counts = build_counts(entries)
    common = {word: count for word, count in counts.items() if count >= COMMON}
    model = EnglishShape(common)

    # Where the corpus already writes the word often, it is not a misread --
    # this is what protects Gabaon, Pharaonic and the like.
    fixes: list[BodyFix] = []
    attested = attested or set()
    for word, count in counts.items():
        if count > RARE or len(word) < MIN_LENGTH:
            continue
        if word in attested:
            continue          # the 2007 engine read it too; leave it alone
        before = model.score(word)
        best: tuple[float, str] | None = None
        for candidate in _variants(word):
            if counts.get(candidate, 0) < COMMON:
                continue
            after = model.score(candidate)
            if after - before < MARGIN:
                continue
            if best is None or after > best[0]:
                best = (after, candidate)
        if best is not None:
            fixes.append(BodyFix(word, best[1], count, before, best[0]))
    fixes.sort(key=lambda f: -f.occurrences)
    return fixes


def plan_against(entries: list[dict], lexicon: Counter, trusted: set[str],
                 min_evidence: int = 5, margin: float = 0.4) -> list[BodyFix]:
    """Repairs attested by the other printing, applied across the whole book.

    The article-by-article comparison in corrections/reference.py can only fix
    a word inside an article it managed to locate, and it locates about nine in
    ten -- the rest are articles the 1914 revision added, which do not exist in
    the 1874 book. It also works on the aligned words, so a word the scan
    broke across a line and rejoined wrongly can slip past it: "mid-" and
    "die" on two lines become "middie", which no single word box contains and
    the 600 dpi re-read therefore never sees.

    This pass has neither limitation. It works on the finished text, and asks
    one question of each word: is this a word neither printing uses, whose
    confusable neighbour both of them use? "Middie" is not in the 1874 book;
    "middle" is, 284 times. That is enough, and it is the same evidence the
    article-level comparison would have used, just not tied to an article.

    The scan's word has to be absent from the other printing entirely, not
    merely rare in it. At a threshold of two occurrences this pass turned
    "bills of exchange" into "hills of exchange" and "earnestly and
    vigorously" into "rigorously": both are ordinary words that the 1874 book
    happens to use exactly once.
    """
    counts = build_counts(entries)
    model = EnglishShape({w: c for w, c in counts.items() if c >= COMMON})

    fixes: list[BodyFix] = []
    for word, count in counts.items():
        if len(word) < MIN_LENGTH or word in trusted or lexicon.get(word, 0) >= 1:
            continue
        before = model.score(word)
        best: tuple[float, str, int] | None = None
        for candidate in _variants(word):
            evidence = lexicon.get(candidate, 0)
            if evidence < min_evidence:
                continue
            # The scan writing it this way repeatedly, and the other spelling
            # hardly at all, is this edition's habit rather than a misread.
            if count > 2 and counts.get(candidate, 0) < 5 * count:
                continue
            after = model.score(candidate)
            # A smaller margin than the corpus-only pass uses, because the
            # evidence here is much stronger: the other printing writes the
            # replacement and does not write this word at all. The model is
            # only here to stop a swap between two spellings that both look
            # like English.
            if after - before < margin:
                continue
            if best is None or evidence > best[2]:
                best = (after, candidate, evidence)
        if best is not None:
            fixes.append(BodyFix(word, best[1], count, before, best[0]))
    fixes.sort(key=lambda f: -f.occurrences)
    return fixes


def plan_joins(entries: list[dict], lexicon: Counter, trusted: set[str]) -> list[BodyFix]:
    """Rejoin a word the scan broke in two.

    A word hyphenated across a line is normally put back together when the
    lines are joined, but not when the break falls between columns or pages,
    or when the hyphen itself did not survive the scan. What is left is two
    fragments sitting side by side: "sym bolism", "jurisdic tion", "an cient".
    Each fragment is invisible to every other repair here, because none of
    them can see that the word continues in the next token.

    The test is the same one used everywhere else, and it needs the other
    printing to work: at least one of the two pieces is a word neither
    printing uses, and the two run together are a word the 1874 book uses.
    "Tory" and "his" are both ordinary words, but "his tory" joins to
    "history", and only one side has to be unattested for that to be safe.
    """
    known = set(trusted) | {word for word, count in lexicon.items() if count >= 1}
    joins: Counter[tuple[str, str]] = Counter()
    counts = build_counts(entries)

    for entry in entries:
        tokens = TOKEN.findall(entry.get("body", ""))
        for first, second in zip(tokens, tokens[1:]):
            left, right = first.lower(), second.lower()
            if len(left) < 2 or len(right) < 2:
                continue
            if left in known and right in known:
                continue
            joined = left + right
            if lexicon.get(joined, 0) >= 5 or counts.get(joined, 0) >= COMMON:
                joins[(left, right)] += 1

    return [BodyFix(f"{a} {b}", a + b, n, 0.0, 0.0) for (a, b), n in joins.items()]


def apply_joins(entries: list[dict], fixes: list[BodyFix]) -> int:
    """Close the gap, keeping the first fragment's capitalisation."""
    changed = 0
    for fix in fixes:
        left, right = fix.before.split(" ", 1)
        pattern = re.compile(
            rf"(?<![A-Za-zÀ-ɏ])({re.escape(left)})(\s+)({re.escape(right)})"
            rf"(?![A-Za-zÀ-ɏ])", re.IGNORECASE)

        def shaped(match: re.Match[str]) -> str:
            head = match.group(1)
            word = fix.after
            if head.isupper() and len(head) > 1:
                return word.upper()
            if head[:1].isupper():
                return word[:1].upper() + word[1:]
            return word

        for entry in entries:
            body = entry.get("body", "")
            if not body:
                continue
            body, count = pattern.subn(shaped, body)
            if count:
                entry["body"] = body
                changed += count
    return changed


def apply(entries: list[dict], fixes: list[BodyFix]) -> int:
    """Rewrite the body text, preserving each occurrence's capitalisation."""
    mapping = {fix.before: fix.after for fix in fixes}
    if not mapping:
        return 0
    pattern = re.compile(
        r"\b(" + "|".join(sorted(map(re.escape, mapping), key=len, reverse=True)) + r")\b",
        re.IGNORECASE)

    changed = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal changed
        found = match.group(0)
        replacement = mapping.get(found.lower())
        if replacement is None:
            return found
        changed += 1
        if found.isupper():
            return replacement.upper()
        if found[:1].isupper():
            return replacement[:1].upper() + replacement[1:]
        return replacement

    for entry in entries:
        body = entry.get("body", "")
        if body:
            entry["body"] = pattern.sub(replace, body)
    return changed


# ---------------------------------------------------------------------------
# Words fused together
#
# The scan loses the space between words often enough to matter: "Inthe Masonic
# phrase", "intoGabaon", "theOrder". Phrase search is built on this text, so a
# fused pair makes the phrase around it unfindable.
#
# Splitting is riskier than substituting, because English is full of compounds
# that look fused -- flooring, listen, statesmen, bylaws, behave, withhold. Two
# narrow rules catch the real cases without touching those.

# Mc and Mac names carry an internal capital legitimately.
_NAME_PREFIX = re.compile(r"^(?:Mc|Mac|De|Di|Du|La|Le|O')[A-Z]")
_INNER_CAPITAL = re.compile(r"(?<=[a-z])(?=[A-Z])")

LEAD_WORDS = {"the", "a", "an"}
TAIL_WORDS = {"the", "this", "that", "which", "these", "those", "such",
              "his", "her", "its", "their", "and"}
FUNCTION_WORDS = {"in", "of", "to", "and", "is", "at", "by", "for", "with",
                  "as", "from", "was", "were", "it", "on", "or", "are", "be",
                  "into", "upon", "that", "this"}


def plan_splits(entries: list[dict], attested: set[str] | None = None) -> list[BodyFix]:
    """Find fused word pairs worth separating.

    Rule one: an internal capital. "theOrder" and "intoGabaon" can only be two
    words; no English word has a capital in the middle. Mc and Mac names are
    the exception and are excluded.

    Rule two: an article or preposition fused to a following word, where the
    pair cannot be an English word -- "forthe", "theritual", "aninteresting".
    Anything that could be a compound is left alone, which is why "bylaws",
    "behave" and "withhold" survive.
    """
    attested = attested or set()
    counts = build_counts(entries)
    raw: Counter[str] = Counter()
    for entry in entries:
        for token in TOKEN.findall(entry.get("body", "")):
            raw[token] += 1

    fixes: list[BodyFix] = []
    seen: set[str] = set()

    for token, count in raw.items():
        if len(token) < 6 or _NAME_PREFIX.match(token):
            continue
        parts = _INNER_CAPITAL.split(token)
        if len(parts) == 2 and all(len(p) >= 2 for p in parts):
            fixes.append(BodyFix(token, " ".join(parts), count, 0.0, 0.0))
            seen.add(token.lower())

    for word, count in counts.items():
        # "inthe" and "ofthe" are five characters; a longer minimum skipped
        # every one of them.
        if len(word) < 5 or word in seen:
            continue
        for cut in range(1, len(word) - 1):
            head, tail = word[:cut], word[cut:]
            if counts.get(tail, 0) < COMMON and tail not in TAIL_WORDS:
                continue

            # A preposition fused to an article -- "inthe", "forthe",
            # "fromthe" -- cannot be an English word however often it appears,
            # so neither the rarity test nor the 2007 veto applies. A fused
            # join is systematic: "Inthe" occurs nine times, and requiring
            # rarity skipped every one of them.
            unambiguous = tail in TAIL_WORDS and head in FUNCTION_WORDS
            if unambiguous:
                fixes.append(BodyFix(word, f"{head} {tail}", count, 0.0, 0.0))
                seen.add(word)
                break

            # An article fused to an ordinary word could be a compound
            # ("atone" is "a" plus "tone"), so this half keeps both guards.
            if count > RARE or word in attested:
                break
            if head in LEAD_WORDS and len(tail) >= 4:
                fixes.append(BodyFix(word, f"{head} {tail}", count, 0.0, 0.0))
                seen.add(word)
                break
    return fixes


def apply_splits(entries: list[dict], fixes: list[BodyFix]) -> int:
    """Insert the missing spaces, keeping each occurrence's capitalisation."""
    mapping = {fix.before.lower(): fix.after for fix in fixes}
    if not mapping:
        return 0
    pattern = re.compile(
        r"\b(" + "|".join(sorted(map(re.escape, mapping), key=len, reverse=True)) + r")\b",
        re.IGNORECASE)
    changed = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal changed
        found = match.group(0)
        replacement = mapping.get(found.lower())
        if replacement is None:
            return found
        changed += 1
        if found[:1].isupper():
            return replacement[:1].upper() + replacement[1:]
        return replacement

    for entry in entries:
        body = entry.get("body", "")
        if body:
            entry["body"] = pattern.sub(replace, body)
    return changed


def apply_word_overrides(entries: list[dict], by_entry: dict) -> int:
    """Replace whole words within one article.

    Separate from apply_entry_overrides because that one matches a literal
    substring, which is right for a phrase keyed to a headword and wrong for a
    single word: "amo" would rewrite the middle of "among". Here the match is
    anchored to word boundaries, every occurrence in the article is taken --
    the word is one the book does not use, so each occurrence is the same
    misread -- and the original capitalisation is kept.
    """
    changed = 0
    for entry in entries:
        pairs = by_entry.get(entry.get("headword", ""))
        if not pairs:
            continue
        body = entry.get("body", "")
        for before, after in pairs:
            # Italic markers sit between characters, so the pattern tolerates
            # them anywhere inside the word.
            middle = "[\x02\x03]*".join(re.escape(c) for c in before)
            pattern = re.compile(rf"(?<![A-Za-zÀ-ɏ]){middle}(?![A-Za-zÀ-ɏ])",
                                 re.IGNORECASE)

            def shaped(match: re.Match[str]) -> str:
                raw = match.group(0)
                found = re.sub(r"[\x02\x03]", "", raw)
                if found.isupper() and len(found) > 1:
                    word = after.upper()
                elif found[:1].isupper():
                    word = after[:1].upper() + after[1:]
                else:
                    word = after
                # Any italic markers the word carried have to come back out,
                # or the run they open is never closed and the rest of the
                # article turns italic in the reader.
                opens = "\x02" if "\x02" in raw else ""
                closes = "\x03" if "\x03" in raw else ""
                return f"{opens}{word}{closes}"

            body, count = pattern.subn(shaped, body)
            changed += count
        entry["body"] = body
    return changed


def apply_entry_overrides(entries: list[dict], overrides: dict) -> int:
    """Apply corrections scoped to a single entry.

    Some words are only wrong in one place. "Paris" appears 216 times in this
    book and is right in 215 of them; in the article on Arts it is a misread of
    "Parts", because the sentence is about the phrase "arts, parts, and points"
    and the book has a Parts entry for the cross-reference to point at. No
    corpus-wide rule can tell those apart, so this one is scoped and verified
    against the page image.
    """
    changed = 0
    by_headword = {k: v for k, v in overrides.items() if not k.startswith("_")}
    for entry in entries:
        pairs = by_headword.get(entry.get("headword", ""))
        if not pairs:
            continue
        for before, after in pairs:
            # Italic markers sit between characters, so the pattern has to
            # tolerate them anywhere.
            pattern = re.compile("[\x02\x03]*".join(re.escape(c) for c in before))
            body = entry.get("body", "")
            if pattern.search(body):
                entry["body"] = pattern.sub(after.replace("\\", "\\\\"), body, count=1)
                changed += 1
    return changed


# Compound numbers whose hyphen the scan lost: "thirtythird" for thirty-third.
NUMBER_TENS = {"twenty", "thirty", "forty", "fifty", "sixty", "seventy",
               "eighty", "ninety"}
NUMBER_UNITS = {"first", "second", "third", "fourth", "fifth", "sixth",
                "seventh", "eighth", "ninth", "one", "two", "three", "four",
                "five", "six", "seven", "eight", "nine", "thirds", "fourths"}

# Only these tails are safe to split off. "in", "at", "to" and "is" look like
# joins but are far more often a truncation -- "meetin" is meeting without its
# g, not "meet in", and splitting it makes the text worse.
SAFE_TAILS = {"of", "and"}


def plan_more_splits(entries: list[dict], attested: set[str] | None = None) -> list[BodyFix]:
    """Two further classes of fused words that can be told apart with certainty.

    A general split pass cannot be made safe here. Word-pair evidence from the
    2007 reading accepts "op tion" and "con found"; the trigram model scores
    the genuine "thisis" and the ordinary "penitent" within a hundredth of each
    other. So only these two classes are taken.
    """
    attested = attested or set()
    counts = build_counts(entries)
    fixes: list[BodyFix] = []

    for word, count in counts.items():
        if len(word) < 5:
            continue
        for cut in range(3, len(word) - 2):
            head, tail = word[:cut], word[cut:]
            if head in NUMBER_TENS and tail in NUMBER_UNITS:
                fixes.append(BodyFix(word, f"{head}-{tail}", count, 0.0, 0.0))
                break
        else:
            if word in attested:
                continue
            for cut in range(3, len(word) - 1):
                head, tail = word[:cut], word[cut:]
                if tail in SAFE_TAILS and counts.get(head, 0) >= COMMON:
                    fixes.append(BodyFix(word, f"{head} {tail}", count, 0.0, 0.0))
                    break
    return fixes
