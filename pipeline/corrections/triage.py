"""Decide the flagged candidates by where they fall in the alphabet.

Parsing holds back any headword-shaped span that nothing closed before it,
because on volume 2's heavier scan italic book titles measure as thick as bold.
That rule is deliberately blunt and catches real headwords too.

Alphabetical position decides them. The book is ordered, so a real headword
sits between its neighbours; an italic title lifted out of a sentence almost
never does. "Magic." between "Magi." and "Magician." is real. "dans la Voie
Profane" between them is not.

This is the same signal the validator uses to find errors, used here to recover
entries. It is structural, not a guess about the text, and every decision is
logged with its reason.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..parse.normalise import sort_key


@dataclass
class Decision:
    pdf_page: int
    headword: str
    promoted: bool
    reason: str
    previous: str = ""
    following: str = ""

    def as_dict(self) -> dict:
        return {
            "pdf_page": self.pdf_page, "headword": self.headword,
            "promoted": self.promoted, "reason": self.reason,
            "between": [self.previous, self.following],
        }


# A candidate must look like a headword, not like a fragment of a sentence.
MAX_WORDS = 7
MIN_LENGTH = 3


def _plausible(headword: str) -> tuple[bool, str]:
    text = headword.strip()
    if len(text) < MIN_LENGTH:
        return False, "too_short"
    if not text.endswith("."):
        return False, "no_terminal_stop"
    if len(text.split()) > MAX_WORDS:
        return False, "too_many_words"
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False, "no_letters"
    # Running text lifted mid-sentence is mostly lowercase; a headword is not.
    if sum(c.isupper() for c in letters) / len(letters) < 0.12:
        return False, "looks_like_running_text"
    if not text[0].isupper():
        return False, "no_initial_capital"
    return True, ""


def triage(sequence: list[dict]) -> tuple[list[Decision], int]:
    """Walk entries in document order, promoting candidates that fit.

    `sequence` is every parsed entry in reading order, accepted and rejected
    alike; rejected ones are promoted in place by clearing their flag. Returns
    the decisions and how many were promoted.

    Neighbours are taken from entries already accepted, so a run of adjacent
    candidates is judged against solid ground rather than against each other.
    """
    decisions: list[Decision] = []
    promoted = 0

    accepted_positions = [i for i, e in enumerate(sequence)
                          if not e.get("rejected") and not e["is_continuation"]
                          and e["headword"]]

    for index, entry in enumerate(sequence):
        if not entry.get("rejected"):
            continue

        # Front matter -- title page, preface, dedication -- has no running
        # head, and its lines are not entries. Without this the editors' names
        # off the title page are promoted as headwords.
        if not entry.get("page_has_guides"):
            decisions.append(Decision(entry["pdf_page"], entry["headword"],
                                      False, "front_matter_or_no_running_head"))
            continue

        headword = entry["headword"]
        ok, why = _plausible(headword)
        if not ok:
            decisions.append(Decision(entry["pdf_page"], headword, False, why))
            continue

        before = [p for p in accepted_positions if p < index]
        after = [p for p in accepted_positions if p > index]
        previous = sequence[before[-1]]["headword"] if before else ""
        following = sequence[after[0]]["headword"] if after else ""

        key = sort_key(headword)
        low = sort_key(previous) if previous else ""
        high = sort_key(following) if following else "￿"

        if low <= key <= high:
            entry["rejected"] = False
            entry["issues"] = [i for i in entry["issues"] if i != "unanchored"]
            entry["issues"].append("promoted_by_order")
            promoted += 1
            decisions.append(Decision(entry["pdf_page"], headword, True,
                                      "fits_alphabetically", previous, following))
        else:
            decisions.append(Decision(entry["pdf_page"], headword, False,
                                      "out_of_order", previous, following))

    return decisions, promoted
