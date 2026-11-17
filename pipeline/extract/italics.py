"""Recover italics from the page image.

Mackey italicises constantly and it carries meaning: French, Latin and German
terms, book and periodical titles, and the target of every cross-reference --
"(See *Parts*, and also *Points*.)" OCR discards the distinction, so the text
loses it unless it is measured back off the ink.

Bold was recovered from stroke width; italic is recovered from slant. For each
word the image is sheared through a range of angles and the one that stacks
the strokes into the sharpest vertical columns wins. On this typeface roman
words settle around -3 to +3 degrees and italic words around +8, which parts
cleanly.

The shear is computed over ink coordinates rather than by rotating the image:
each angle is then a bincount over a few hundred points, which is fast enough
to run across 946 pages.
"""

from __future__ import annotations

import numpy as np

# Roman sits near zero; italic on this face measures about +8.
ANGLES = np.arange(-6.0, 15.0, 1.5)
ITALIC_DEGREES = 6.0

MIN_HEIGHT = 12
MIN_WIDTH = 24
MIN_INK = 70
# Two or three letters carry too few strokes for the shear to settle: "of"
# and "for" measured italic on a page where they plainly are not. Short words
# take their verdict from the run around them instead.
MIN_LETTERS = 4


def slant_of(ink: np.ndarray, left: int, top: int, width: int, height: int) -> float | None:
    """The shear angle that best verticalises this word's strokes.

    Returns None when the word is too small to measure: short words carry few
    strokes and the estimate becomes noise.
    """
    if height < MIN_HEIGHT or width < MIN_WIDTH:
        return None
    crop = ink[top:top + height, left:left + width]
    ys, xs = np.nonzero(crop)
    if ys.size < MIN_INK:
        return None

    centred = ys.astype(np.float32) - height / 2.0
    xs = xs.astype(np.float32)
    span = width + 2 * int(abs(np.tan(np.radians(ANGLES[-1]))) * height + 2)
    offset = (span - width) // 2

    best_score = -1.0
    best_angle = 0.0
    for angle in ANGLES:
        shifted = xs + centred * np.tan(np.radians(angle)) + offset
        columns = np.bincount(np.clip(shifted, 0, span - 1).astype(np.int32),
                              minlength=span).astype(np.float64)
        # Sharper peaks mean the strokes line up vertically at this shear.
        score = float((columns ** 2).sum())
        if score > best_score:
            best_score = score
            best_angle = float(angle)
    return best_angle


def mark_italics(page, ink: np.ndarray) -> int:
    """Measure every word on the page and flag the italic ones.

    Words too small to measure take the verdict of their neighbours: italics
    come in runs -- a title, a foreign phrase -- so a short word with italic
    on both sides is italic too.
    """
    measured: list[tuple[int, float]] = []
    for index, word in enumerate(page.words):
        letters = sum(c.isalnum() for c in word.text)
        angle = (slant_of(ink, word.left, word.top, word.width, word.height)
                 if letters >= MIN_LETTERS else None)
        word.italic = False
        word.slant = angle
        if angle is not None:
            measured.append((index, angle))

    if not measured:
        return 0

    for index, angle in measured:
        page.words[index].italic = angle >= ITALIC_DEGREES

    # Fill in the words that could not be measured.
    for index, word in enumerate(page.words):
        if word.slant is not None:
            continue
        before = next((page.words[j] for j in range(index - 1, -1, -1)
                       if page.words[j].slant is not None), None)
        after = next((page.words[j] for j in range(index + 1, len(page.words))
                      if page.words[j].slant is not None), None)
        if before is not None and after is not None and before.italic and after.italic:
            word.italic = True

    return sum(1 for word in page.words if word.italic)
