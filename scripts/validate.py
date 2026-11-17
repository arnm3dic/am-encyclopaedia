#!/usr/bin/env python3
"""Check every entry's frontmatter and section order.

Usage:
    python3 scripts/validate.py [path ...]

With no arguments, checks every .md file under entries/ except _TEMPLATE.md.
Exits 1 if any entry has a problem. No third-party dependencies: the frontmatter
subset used here (scalars and inline [a, b] lists) is parsed directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENTRIES = REPO / "entries"

REQUIRED = ("title", "slug", "category", "domains", "cultures", "status")
LIST_FIELDS = ("aliases", "domains", "cultures")
VALID_STATUS = ("draft", "reviewed")

SECTIONS = (
    "Summary",
    "Core meanings",
    "By tradition",
    "Inversions and tensions",
    "Related entries",
    "Sources",
)
OPTIONAL_SECTIONS = ("Inversions and tensions",)


def split_frontmatter(text: str) -> tuple[list[str], str]:
    """Return (frontmatter lines, body). Raises ValueError if absent."""
    if not text.startswith("---\n"):
        raise ValueError("no frontmatter block (file must start with ---)")
    end = text.find("\n---\n", 3)
    if end == -1:
        raise ValueError("frontmatter block is never closed")
    return text[4:end].splitlines(), text[end + 5 :]


def parse_frontmatter(lines: list[str]) -> dict[str, object]:
    data: dict[str, object] = {}
    for raw in lines:
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"frontmatter line is not key: value -> {line!r}")
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            items = [v.strip().strip("'\"") for v in inner.split(",")] if inner else []
            data[key] = [v for v in items if v]
        else:
            data[key] = value.strip("'\"")
    return data


def body_sections(body: str) -> list[str]:
    return [
        line[3:].strip()
        for line in body.splitlines()
        if line.startswith("## ")
    ]


def check(path: Path) -> list[str]:
    problems: list[str] = []
    try:
        fm_lines, body = split_frontmatter(path.read_text(encoding="utf-8"))
        fm = parse_frontmatter(fm_lines)
    except (ValueError, UnicodeDecodeError) as exc:
        return [str(exc)]

    for field in REQUIRED:
        value = fm.get(field)
        if value is None or value == "" or value == []:
            problems.append(f"{field}: missing or empty")

    for field in LIST_FIELDS:
        if field in fm and not isinstance(fm[field], list):
            problems.append(f"{field}: must be a list, e.g. [wisdom, death]")

    slug = fm.get("slug")
    if slug and slug != path.stem:
        problems.append(f"slug: {slug!r} does not match filename {path.stem!r}")

    category = fm.get("category")
    if category and category != path.parent.name:
        problems.append(
            f"category: {category!r} does not match folder {path.parent.name!r}"
        )

    status = fm.get("status")
    if status and status not in VALID_STATUS:
        problems.append(
            f"status: {status!r} must be one of {', '.join(VALID_STATUS)}"
        )

    found = body_sections(body)
    unknown = [s for s in found if s not in SECTIONS]
    if unknown:
        problems.append(f"unknown section(s): {', '.join(unknown)}")

    for name in SECTIONS:
        if name not in found and name not in OPTIONAL_SECTIONS:
            problems.append(f"missing section: {name}")

    known = [s for s in found if s in SECTIONS]
    if known != sorted(known, key=SECTIONS.index):
        problems.append(
            "sections out of order; expected: " + " -> ".join(SECTIONS)
        )

    return problems


def targets(argv: list[str]) -> list[Path]:
    if argv:
        return [Path(a).resolve() for a in argv]
    return sorted(p for p in ENTRIES.rglob("*.md") if p.name != "_TEMPLATE.md")


def main(argv: list[str]) -> int:
    paths = targets(argv)
    if not paths:
        print("no entries found")
        return 0

    failed = 0
    for path in paths:
        problems = check(path)
        rel = path.relative_to(REPO) if REPO in path.parents else path
        if problems:
            failed += 1
            print(f"FAIL {rel}")
            for problem in problems:
                print(f"       {problem}")
        else:
            print(f"ok   {rel}")

    print(f"\n{len(paths) - failed} ok, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
