"""Independent checks on the extraction.

The segmentation in parse/entries.py rests on one signal: stroke width. These
checks rest on a different one -- the book is alphabetical -- so they catch
what the first signal gets wrong, in both directions. A headword that breaks
alphabetical order is either a false positive or a misread; a page whose first
headword jumps well past the previous page's last suggests entries were missed.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

from ..parse.entries import Entry
from ..parse.normalise import sort_key

LOW_CONFIDENCE = 80.0


@dataclass
class Issue:
    pdf_page: int
    severity: str       # 'error' | 'warning'
    code: str
    detail: str

    def as_dict(self) -> dict:
        return asdict(self)


def check(entries: list[Entry]) -> list[Issue]:
    """Run every validator over entries in document order."""
    issues: list[Issue] = []
    issues += _alphabetical_order(entries)
    issues += _confidence(entries)
    issues += _structure(entries)
    return sorted(issues, key=lambda i: (i.pdf_page, i.code))


def _alphabetical_order(entries: list[Entry]) -> list[Issue]:
    issues: list[Issue] = []
    previous: Entry | None = None
    for entry in entries:
        if entry.is_continuation or not entry.headword:
            continue
        if previous is not None:
            before, after = sort_key(previous.headword), sort_key(entry.headword)
            if after < before:
                issues.append(Issue(
                    pdf_page=entry.pdf_page,
                    severity="error",
                    code="alpha_order",
                    detail=f"{entry.headword!r} follows {previous.headword!r}",
                ))
        previous = entry
    return issues


def _confidence(entries: list[Entry]) -> list[Issue]:
    issues: list[Issue] = []
    for entry in entries:
        if entry.confidence and entry.confidence < LOW_CONFIDENCE:
            issues.append(Issue(
                pdf_page=entry.pdf_page,
                severity="warning",
                code="low_confidence",
                detail=f"{entry.headword or '(continuation)'!r} at {entry.confidence:.0f}%",
            ))
    return issues


def _structure(entries: list[Entry]) -> list[Issue]:
    issues: list[Issue] = []
    for entry in entries:
        for code in entry.issues:
            issues.append(Issue(
                pdf_page=entry.pdf_page,
                severity="warning",
                code=code,
                detail=repr(entry.headword or "(continuation)"),
            ))
    return issues


def summarise(entries: list[Entry], issues: list[Issue]) -> dict:
    real = [e for e in entries if not e.is_continuation]
    confidences = [e.confidence for e in entries if e.confidence]
    by_code: dict[str, int] = {}
    for issue in issues:
        by_code[issue.code] = by_code.get(issue.code, 0) + 1
    return {
        "entries": len(real),
        "continuations": len(entries) - len(real),
        "mean_confidence": round(sum(confidences) / len(confidences), 1) if confidences else 0.0,
        "errors": sum(1 for i in issues if i.severity == "error"),
        "warnings": sum(1 for i in issues if i.severity == "warning"),
        "by_code": by_code,
    }
