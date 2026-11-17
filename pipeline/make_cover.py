"""Turn a photograph of the book into the app's logo.

The source is a snapshot of the physical binding — Mackey's Revised
Encyclopedia of Freemasonry, volume 2 — sitting on a table, lit from one side
and photographed slightly from above.  Three things have to go before it can
be an icon: the room behind it, the keystone from the camera angle, and the
ragged hand-held edges.

The method, in order:

  1.  Segment the book by blueness (blue minus the mean of red and green).
      The cloth is the only strongly blue thing in the frame.

  2.  Fit a straight line to each of the four sides of that silhouette, using
      the per-row and per-column extremes of the mask and a trimmed
      total-least-squares fit.  Fitting *lines* rather than tracing the mask is
      what refines the edges: a hand-held photograph and an imperfect threshold
      both wobble by a pixel or two, and the wobble is what reads as a cut-out.
      The corners are the intersections of the fitted lines, so they are exact
      even where the mask frayed (the dark lower-right ornament, which is
      barely blue at all, took a bite out of that corner).

  3.  Warp that quadrilateral onto a rectangle.  The camera was above the book
      and the top board is nearer than the bottom, so the top edge measures 465
      pixels and the bottom 374.  Undoing it recovers the cover as it actually
      is — symmetric, square-on, the lettering the same size top and bottom.

  4.  Crop the board edges away.  The spine side and the top edge are visible
      as bands of cloth at a different angle to the face; they are part of the
      book but not part of the cover, and they would read as dirt on an icon.
      The crop is centred on the stamped border rather than on the silhouette,
      which is why the margins come out even.

The aspect ratio is the one weak point.  Recovering it from the homography
needs the two vanishing points, and this view is close enough to frontal that
the horizontal one is at infinity — the closed form returns a negative focal
length.  So the warp uses 0.70, and the face crop lands at 0.685; the edition
is about 6.5 by 9.5 inches, or 0.684.  That agreement is a check, not a
coincidence we rely on.

Run from the repository root:

    python3 pipeline/make_cover.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
PHOTO = ROOT / "pipeline" / "assets" / "cover-photo.jpg"
IMG = ROOT / "app" / "public" / "img"

# The app's paper, for the icons that cannot be transparent.
PAPER = (238, 242, 243)  # #f3f2ee in BGR

WARP_ASPECT = 0.70  # width / height of the whole book, as warped
WARP_HEIGHT = 1200


# --------------------------------------------------------------------------
# the silhouette


def silhouette(im: np.ndarray) -> np.ndarray:
    """Mask of the book: the one strongly blue region in the frame."""
    b, g, r = (im[:, :, i].astype(np.int16) for i in range(3))
    blue = np.clip(b - (r + g) // 2, 0, 255).astype(np.uint8)

    _, mask = cv2.threshold(blue, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))

    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if n < 2:
        raise SystemExit("no blue region found in the photograph")
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    mask = (labels == biggest).astype(np.uint8) * 255

    # Fill the interior: the darkest stamping is not blue enough to survive the
    # threshold, and leaves holes.
    h, w = mask.shape
    flood = mask.copy()
    cv2.floodFill(flood, np.zeros((h + 2, w + 2), np.uint8), (0, 0), 255)
    return mask | cv2.bitwise_not(flood)


def _fit_line(points: list[tuple[int, int]], rounds: int = 6):
    """Trimmed total-least-squares line through points -> (centroid, direction)."""
    p = np.asarray(points, float)
    keep = np.ones(len(p), bool)
    for _ in range(rounds):
        centre = p[keep].mean(0)
        _, _, vt = np.linalg.svd(p[keep] - centre)
        direction = vt[0]
        normal = np.array([-direction[1], direction[0]])
        residual = np.abs((p - centre) @ normal)
        keep = residual < max(1.0, 2.5 * np.median(residual[keep]))
    return centre, direction


def corners(mask: np.ndarray) -> np.ndarray:
    """The four corners of the book, as intersections of fitted edge lines."""
    h, w = mask.shape
    on = mask > 0

    def along_rows(last: bool, lo: float, hi: float):
        out = []
        for y in range(int(h * lo), int(h * hi)):
            xs = np.flatnonzero(on[y])
            if xs.size:
                out.append((int(xs[-1] if last else xs[0]), y))
        return out

    def along_cols(last: bool, lo: float, hi: float):
        out = []
        for x in range(int(w * lo), int(w * hi)):
            ys = np.flatnonzero(on[:, x])
            if ys.size:
                out.append((x, int(ys[-1] if last else ys[0])))
        return out

    # The middle of each side only: the corners themselves are where a mask
    # frays, and including them would drag the line off true.
    left = _fit_line(along_rows(False, 0.08, 0.92))
    right = _fit_line(along_rows(True, 0.08, 0.92))
    top = _fit_line(along_cols(False, 0.10, 0.90))
    bottom = _fit_line(along_cols(True, 0.10, 0.90))

    def meet(a, b):
        (c1, d1), (c2, d2) = a, b
        t = np.linalg.solve(np.array([d1, -d2]).T, c2 - c1)
        return c1 + t[0] * d1

    return np.array(
        [meet(top, left), meet(top, right), meet(bottom, right), meet(bottom, left)],
        dtype=np.float32,
    )


# --------------------------------------------------------------------------
# the cover face


def flatten(im: np.ndarray, quad: np.ndarray) -> np.ndarray:
    """Undo the camera angle: map the book's quadrilateral onto a rectangle."""
    out_w = int(round(WARP_HEIGHT * WARP_ASPECT))
    dst = np.float32(
        [[0, 0], [out_w, 0], [out_w, WARP_HEIGHT], [0, WARP_HEIGHT]]
    )
    m = cv2.getPerspectiveTransform(quad, dst)
    return cv2.warpPerspective(
        im, m, (out_w, WARP_HEIGHT),
        flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE,
    )


def face(flat: np.ndarray) -> np.ndarray:
    """Crop the visible board edges away, centred on the stamped border.

    The outer border of the stamping is the darkest vertical line near each
    side; centring on those two rather than on the silhouette is what makes the
    left and right margins match, since the spine-side board eats into the
    silhouette on the left only.
    """
    grey = cv2.cvtColor(flat, cv2.COLOR_BGR2GRAY).astype(float)
    h, w = grey.shape
    profile = grey[int(h * 0.12): int(h * 0.88)].mean(0)
    profile = np.convolve(profile, np.ones(5) / 5, "same")

    def darkest_in(lo: int, hi: int) -> int:
        return lo + int(np.argmin(profile[lo:hi]))

    # The joint at the spine is darker still, so the left search starts past it.
    left_border = darkest_in(int(w * 0.07), int(w * 0.12))
    right_border = darkest_in(int(w * 0.95), int(w * 0.99))
    centre = (left_border + right_border) / 2

    half = min(centre - 48, w - 4 - centre)
    x0, x1 = int(round(centre - half)), int(round(centre + half))

    rows = grey[:, int(w * 0.2): int(w * 0.8)].mean(1)
    y0 = int(np.argmin(rows[: int(h * 0.04)]) + 2)      # joint below the top board
    y1 = h - int(np.argmin(rows[-int(h * 0.03):][::-1]) + 2)
    return flat[y0:y1, x0:x1]


def enhance(face_im: np.ndarray) -> np.ndarray:
    """Clean the photograph up for small sizes.

    A phone photograph of dark blue cloth is noisy, and the gold is only a few
    shades off the cloth once it is 48 pixels wide.  Bilateral first so the
    grain goes without the stamping, then unsharp, then a little saturation and
    contrast so the lettering survives the downscale.
    """
    den = cv2.bilateralFilter(face_im, 7, 28, 7)
    blur = cv2.GaussianBlur(den, (0, 0), 2.2)
    sharp = cv2.addWeighted(den, 1.55, blur, -0.55, 0)

    hsv = cv2.cvtColor(sharp, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 1] *= 1.12
    hsv[..., 2] = np.clip((hsv[..., 2] - 128) * 1.10 + 132, 0, 255)
    return cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2BGR)


# --------------------------------------------------------------------------
# the icons


def rounded_alpha(w: int, h: int, radius: int, ss: int = 4) -> np.ndarray:
    """An anti-aliased rounded rectangle, drawn large and shrunk."""
    big = np.zeros((h * ss, w * ss), np.uint8)
    r = radius * ss
    cv2.rectangle(big, (r, 0), (w * ss - r, h * ss), 255, -1)
    cv2.rectangle(big, (0, r), (w * ss, h * ss - r), 255, -1)
    for cx, cy in ((r, r), (w * ss - r, r), (r, h * ss - r), (w * ss - r, h * ss - r)):
        cv2.circle(big, (cx, cy), r, 255, -1)
    return cv2.resize(big, (w, h), interpolation=cv2.INTER_AREA)


def book_at(cover: np.ndarray, height: int) -> np.ndarray:
    """The cover at a given height, BGRA, corners rounded, background clear."""
    aspect = cover.shape[1] / cover.shape[0]
    w = int(round(height * aspect))
    small = cv2.resize(cover, (w, height), interpolation=cv2.INTER_AREA)
    radius = max(2, round(height * 0.018))
    out = np.dstack([small, rounded_alpha(w, height, radius)])
    return out


def place(book: np.ndarray, size: int, background=None) -> np.ndarray:
    """Centre the book on a square canvas, clear or paper-coloured."""
    canvas = np.zeros((size, size, 4), np.uint8)
    if background is not None:
        canvas[:, :, :3] = background
        canvas[:, :, 3] = 255
    h, w = book.shape[:2]
    y, x = (size - h) // 2, (size - w) // 2
    patch = canvas[y:y + h, x:x + w]
    a = book[:, :, 3:4].astype(np.float32) / 255.0
    patch[:, :, :3] = (book[:, :, :3] * a + patch[:, :, :3] * (1 - a)).astype(np.uint8)
    patch[:, :, 3] = np.maximum(patch[:, :, 3], book[:, :, 3])
    return canvas


def save_png(path: Path, bgra: np.ndarray) -> None:
    """Write BGRA through PIL, which optimises the PNG; OpenCV does not.

    An image with nothing transparent in it is written without an alpha
    channel at all -- smaller, and it says plainly which icons are cut out and
    which have the paper behind them.
    """
    rgba = bgra[:, :, [2, 1, 0, 3]]
    if (rgba[:, :, 3] == 255).all():
        Image.fromarray(rgba[:, :, :3]).save(path, "PNG", optimize=True)
    else:
        Image.fromarray(rgba).save(path, "PNG", optimize=True)


def main() -> int:
    if not PHOTO.exists():
        print(f"missing {PHOTO}", file=sys.stderr)
        return 1
    im = cv2.imread(str(PHOTO))
    quad = corners(silhouette(im))
    cover = enhance(face(flatten(im, quad)))
    print(f"cover {cover.shape[1]}x{cover.shape[0]}  aspect {cover.shape[1] / cover.shape[0]:.4f}")

    IMG.mkdir(parents=True, exist_ok=True)
    # The flat cover stays out of the app: nothing serves it, and at full size
    # it would be the heaviest file in the bundle.  It lives beside the
    # photograph as the working master.
    cv2.imwrite(str(PHOTO.parent / "cover-flat.png"), cover)

    # "any": the book alone, nothing behind it.
    for size in (512, 192):
        save_png(IMG / f"icon-{size}.png", place(book_at(cover, round(size * 0.985)), size))

    # "maskable": Android may crop to a circle of 80% of the canvas, so the
    # book has to fit inside that circle, diagonal and all.
    size = 512
    inner = int(0.80 * size / np.hypot(1.0, cover.shape[1] / cover.shape[0]))
    save_png(IMG / "icon-maskable-512.png", place(book_at(cover, inner), size, PAPER))

    # iOS composites transparency onto black and applies its own rounding.
    save_png(IMG / "apple-touch-icon.png", place(book_at(cover, 150), 180, PAPER))

    for name in ("icon-512.png", "icon-192.png",
                 "icon-maskable-512.png", "apple-touch-icon.png"):
        p = IMG / name
        print(f"  {name:24s} {p.stat().st_size / 1024:6.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
