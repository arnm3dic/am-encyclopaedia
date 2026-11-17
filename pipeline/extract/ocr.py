"""Rasterise a PDF page, OCR it, and measure the weight of every word.

The weight measurement is what makes entry segmentation possible. Mackey sets
entries run-on: a new headword begins mid-paragraph and is distinguished from
surrounding prose only by being bold. OCR discards font weight -- Tesseract's
legacy engine reported it, but current builds ship LSTM-only training data and
`--oem 0` fails.

So we measure the ink directly. For each word box, the distance transform of
its ink pixels gives, at each pixel, the distance to the nearest background
pixel; twice the 80th percentile of that is a robust stroke-width estimate.
Body text in this scan measures 4.0 and headwords 6.0, which separates cleanly.

Ink *density* (black pixels over box area) does not work: short round words
like "names" score as high as genuine bold.
"""

from __future__ import annotations

import csv
import io
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

RENDER_DPI = 300
INK_THRESHOLD = 128          # 8-bit grey below this counts as ink
MIN_INK_PIXELS = 20          # smaller marks are speckle, not letters
BOLD_RATIO = 1.25            # stroke width this many times the page median = bold


class ExtractionError(RuntimeError):
    pass


@dataclass
class Word:
    text: str
    left: int
    top: int
    width: int
    height: int
    conf: float
    stroke_width: float
    bold: bool = False
    column: int = 0
    line: int = 0

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def middle_y(self) -> int:
        return self.top + self.height // 2


@dataclass
class Page:
    pdf_page: int
    image_path: Path
    width: int
    height: int
    words: list[Word] = field(default_factory=list)
    gutter_x: int = 0
    median_stroke: float = 0.0
    mean_conf: float = 0.0


def rasterize(pdf_path: Path, pdf_page: int, out_dir: Path, dpi: int = RENDER_DPI) -> Path:
    """Render one page to a greyscale PNG. Returns the file written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / f"page{pdf_page:04d}"
    result = subprocess.run(
        ["pdftoppm", "-r", str(dpi), "-gray", "-png",
         "-f", str(pdf_page), "-l", str(pdf_page), str(pdf_path), str(stem)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise ExtractionError(f"pdftoppm failed on page {pdf_page}: {result.stderr.strip()}")
    produced = sorted(out_dir.glob(f"page{pdf_page:04d}*.png"))
    if not produced:
        raise ExtractionError(f"pdftoppm produced no image for page {pdf_page}")
    return produced[0]


def _run_tesseract(image_path: Path) -> str:
    """OCR to TSV. --psm 3 performs automatic page segmentation, which detects
    the two columns and reads them in order; without it the columns interleave.
    """
    result = subprocess.run(
        ["tesseract", str(image_path), "stdout", "--psm", "3", "-l", "eng", "tsv"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise ExtractionError(f"tesseract failed on {image_path.name}: {result.stderr.strip()}")
    return result.stdout


def _stroke_width(ink_crop: np.ndarray) -> float | None:
    if ink_crop.size == 0 or ink_crop.sum() < MIN_INK_PIXELS:
        return None
    distances = ndimage.distance_transform_edt(ink_crop)
    values = distances[ink_crop]
    if values.size == 0:
        return None
    return float(2.0 * np.percentile(values, 80))


def find_gutter(ink: np.ndarray, body_top: int) -> int:
    """Locate the whitespace channel between the two columns.

    A fixed page midpoint is wrong: on page 100 the true gutter sits at x=882
    where the midpoint is 933, which splits headwords across columns and
    corrupts reading order. Project ink vertically and find the widest low-ink
    run near the middle instead.
    """
    height, width = ink.shape
    body = ink[body_top:, :]
    if body.size == 0:
        return width // 2
    column_ink = body.sum(axis=0).astype(float)
    lo, hi = int(width * 0.38), int(width * 0.62)
    band = column_ink[lo:hi]
    if band.size == 0:
        return width // 2
    threshold = max(band.min() + 1.0, body.shape[0] * 0.002)
    best_run, best_centre, run = 0, None, 0
    for i, value in enumerate(band):
        if value <= threshold:
            run += 1
            if run > best_run:
                best_run, best_centre = run, i - run // 2
        else:
            run = 0
    if best_centre is None:
        return width // 2
    return lo + best_centre


def read_page(pdf_path: Path, pdf_page: int, image_dir: Path) -> Page:
    """Rasterise, OCR, measure stroke widths, assign columns and lines."""
    image_path = rasterize(pdf_path, pdf_page, image_dir)
    grey = np.array(Image.open(image_path).convert("L"))
    ink = grey < INK_THRESHOLD
    height, width = ink.shape

    rows = list(csv.DictReader(io.StringIO(_run_tesseract(image_path)),
                               delimiter="\t", quoting=csv.QUOTE_NONE))
    words: list[Word] = []
    for row in rows:
        try:
            if int(row["level"]) != 5:
                continue
            text = (row.get("text") or "").strip()
            if not text:
                continue
            left, top = int(row["left"]), int(row["top"])
            w, h = int(row["width"]), int(row["height"])
            conf = float(row.get("conf") or -1)
        except (ValueError, KeyError, TypeError):
            continue
        if w < 6 or h < 8:
            continue
        stroke = _stroke_width(ink[top:top + h, left:left + w])
        if stroke is None:
            continue
        words.append(Word(text=text, left=left, top=top, width=w, height=h,
                          conf=conf, stroke_width=stroke))

    page = Page(pdf_page=pdf_page, image_path=image_path, width=width,
                height=height, words=words)
    if not words:
        return page

    strokes = np.array([word.stroke_width for word in words])
    page.median_stroke = float(np.median(strokes))
    bold_threshold = page.median_stroke * BOLD_RATIO
    for word in words:
        word.bold = word.stroke_width >= bold_threshold

    confidences = [w.conf for w in words if w.conf >= 0]
    page.mean_conf = float(np.mean(confidences)) if confidences else 0.0

    body_top = min(w.top for w in words)
    page.gutter_x = find_gutter(ink, body_top)
    for word in words:
        # Assign by the word's centre, so a word straddling the channel lands
        # in the column that holds most of it.
        word.column = 0 if (word.left + word.width // 2) < page.gutter_x else 1

    _assign_lines(page)
    return page


def _assign_lines(page: Page) -> None:
    """Group words into reading lines within each column.

    Tesseract's own line numbering is per-block and does not survive our column
    reassignment, so lines are rebuilt from vertical position. Words on a line
    vary in `top` by their ascenders, so lines are matched on vertical overlap
    rather than on equal tops.
    """
    line_counter = 0
    for column in (0, 1):
        in_column = sorted((w for w in page.words if w.column == column),
                           key=lambda w: (w.middle_y, w.left))
        current: list[Word] = []
        current_mid = None
        for word in in_column:
            tolerance = max(word.height * 0.6, 8)
            if current_mid is not None and abs(word.middle_y - current_mid) <= tolerance:
                current.append(word)
                current_mid = sum(w.middle_y for w in current) / len(current)
            else:
                if current:
                    line_counter += 1
                    for w in current:
                        w.line = line_counter
                current = [word]
                current_mid = word.middle_y
        if current:
            line_counter += 1
            for w in current:
                w.line = line_counter
