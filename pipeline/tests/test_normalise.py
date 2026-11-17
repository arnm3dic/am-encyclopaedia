#!/usr/bin/env python3
"""Check normalisation against the shared fixtures.

The TypeScript implementation runs the same file. If these two ever disagree,
searches fail silently: the query is normalised one way, the stored text
another, and nothing matches. That presents as a broken search engine rather
than a broken string function, which is why it is pinned here.

    python3 -I pipeline/tests/test_normalise.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pipeline.parse.normalise import first_letter, normalise, sort_key

FIXTURES = Path(__file__).resolve().parent / "normalise_fixtures.json"


def main() -> int:
    if not FIXTURES.exists():
        print(f"no fixtures at {FIXTURES}; run pipeline/export_web.py first")
        return 1

    cases = json.loads(FIXTURES.read_text(encoding="utf-8"))
    failures = []
    for case in cases:
        text = case["input"]
        for name, actual in (("normalise", normalise(text)),
                             ("sort_key", sort_key(text)),
                             ("first_letter", first_letter(text))):
            if actual != case[name]:
                failures.append((text, name, case[name], actual))

    for text, name, expected, actual in failures[:20]:
        print(f"FAIL {name}({text!r}): expected {expected!r}, got {actual!r}")

    print(f"\n{len(cases)} fixtures, {len(cases)*3 - len(failures)} assertions passed, "
          f"{len(failures)} failed")

    # Properties that must hold whatever the rules are.
    invariants = 0
    for case in cases:
        value = case["normalise"]
        assert value == value.strip(), f"leading/trailing space in {value!r}"
        assert "  " not in value, f"double space in {value!r}"
        assert value == value.lower(), f"uppercase survived in {value!r}"
        invariants += 3
    print(f"{invariants} invariants held")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
