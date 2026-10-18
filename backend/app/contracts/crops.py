"""X1 crops: render cited pages, crop element bounding boxes, read lines with local OCR."""
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image
import pypdfium2 as pdfium

from app.documents.types import Box


@dataclass(frozen=True)
class OcrLine:
    text: str
    box: tuple[int, int, int, int]  # left, top, right, bottom in image pixels


def render_pages(pdf_path: Path, pages: Iterable[int], dpi: int = 200) -> dict[int, Image.Image]:
    """Render 1-based PDF pages to RGB PIL images at the requested DPI.

    Local rendering avoids network transfer and preserves high resolution for OCR.
    """
    doc = pdfium.PdfDocument(str(pdf_path))
    scale = dpi / 72
    rendered: dict[int, Image.Image] = {}
    for page_no in pages:
        page = doc[page_no - 1]
        img = page.render(scale=scale).to_pil()
        if img.mode != "RGB":
            img = img.convert("RGB")
        rendered[page_no] = img
    return rendered


def crop(page: Image.Image, page_size_pt: tuple[float, float], box: Box | None, pad_pt: float = 6) -> Image.Image:
    """Crop a page image to an element's bounding box with padding, or return the whole page.

    Cropping isolates cited evidence to reduce image size and shield personal data from vision models.
    """
    if box is None:
        return page.copy()
    page_width_pt, page_height_pt = page_size_pt
    scale = page.width / page_width_pt
    if box.coord_origin == "BOTTOMLEFT":
        top = (page_height_pt - box.t) * scale
        bottom = (page_height_pt - box.b) * scale
    else:
        top = box.t * scale
        bottom = box.b * scale
    left = box.l * scale
    right = box.r * scale

    y_min, y_max = min(top, bottom), max(top, bottom)
    x_min, x_max = min(left, right), max(left, right)

    pad_px = pad_pt * scale
    crop_left = max(0, int(round(x_min - pad_px)))
    crop_top = max(0, int(round(y_min - pad_px)))
    crop_right = min(page.width, int(round(x_max + pad_px)))
    crop_bottom = min(page.height, int(round(y_max + pad_px)))

    return page.crop((crop_left, crop_top, crop_right, crop_bottom))


@lru_cache(maxsize=1)
def _ocr_engine():
    from rapidocr import RapidOCR

    return RapidOCR()


def ocr_lines(image: Image.Image) -> list[OcrLine]:
    """Extract text lines with pixel bounding boxes, merging words that share a row.

    The fee table re-read needs a band's text and its rate on one line.
    """
    if image.width == 0 or image.height == 0:
        return []
    if image.mode != "RGB":
        image = image.convert("RGB")

    engine = _ocr_engine()
    result = engine(np.array(image))
    if result is None or getattr(result, "boxes", None) is None or getattr(result, "txts", None) is None:
        return []
    if len(result.boxes) == 0 or len(result.txts) == 0:
        return []

    items: list[tuple[float, float, float, float, str]] = []
    for pts, text in zip(result.boxes, result.txts):
        t_str = text.strip()
        if not t_str:
            continue
        l = float(min(pt[0] for pt in pts))
        r = float(max(pt[0] for pt in pts))
        t = float(min(pt[1] for pt in pts))
        b = float(max(pt[1] for pt in pts))
        items.append((min(l, r), min(t, b), max(l, r), max(t, b), t_str))

    if not items:
        return []

    n = len(items)
    parent = list(range(n))

    def find(i: int) -> int:
        path: list[int] = []
        while parent[i] != i:
            path.append(i)
            i = parent[i]
        for p in path:
            parent[p] = i
        return i

    def union(i: int, j: int) -> None:
        root_i = find(i)
        root_j = find(j)
        if root_i != root_j:
            parent[root_i] = root_j

    for i in range(n):
        _, t_i, _, b_i, _ = items[i]
        h_i = b_i - t_i
        for j in range(i + 1, n):
            _, t_j, _, b_j, _ = items[j]
            h_j = b_j - t_j
            sh = min(h_i, h_j)
            overlap = min(b_i, b_j) - max(t_i, t_j)
            if sh > 0 and overlap > 0.5 * sh:
                union(i, j)

    clusters: dict[int, list[tuple[float, float, float, float, str]]] = {}
    for i in range(n):
        root = find(i)
        clusters.setdefault(root, []).append(items[i])

    rows: list[OcrLine] = []
    for cluster_items in clusters.values():
        cluster_items.sort(key=lambda x: x[0])
        row_text = " ".join(x[4] for x in cluster_items)
        left = int(round(min(x[0] for x in cluster_items)))
        top = int(round(min(x[1] for x in cluster_items)))
        right = int(round(max(x[2] for x in cluster_items)))
        bottom = int(round(max(x[3] for x in cluster_items)))
        rows.append(OcrLine(text=row_text, box=(left, top, right, bottom)))

    rows.sort(key=lambda r: (r.box[1], r.box[0]))
    return rows
