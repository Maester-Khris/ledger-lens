"""X1 crops (spec section 6): render cited pages locally, cut a field's evidence by its Docling box, read it with
local OCR. Nothing here leaves the machine."""
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.contracts.crops import crop, ocr_lines, render_pages
from app.documents.types import Box

FIXTURE = Path(__file__).parent / "fixtures" / "documents" / "client_agreement.pdf"
LETTER = (612.0, 792.0)


def _page(dpi: int) -> Image.Image:
    scale = dpi / 72
    return Image.new("RGB", (round(LETTER[0] * scale), round(LETTER[1] * scale)), "white")


def test_render_pages_at_dpi():
    pages = render_pages(FIXTURE, [1, 2], dpi=200)
    assert set(pages) == {1, 2}
    assert pages[2].size == (1700, 2200)  # 612 x 792 pt at 200 dpi
    assert pages[1].mode == "RGB"


def test_crop_bottomleft_box_maps_to_pixels():
    box = Box(page_no=1, l=72, t=720, r=144, b=648, coord_origin="BOTTOMLEFT")  # 1 inch square, 1 inch from top-left
    assert crop(_page(144), LETTER, box, pad_pt=0).size == (144, 144)


def test_crop_topleft_box_maps_to_the_same_pixels():
    page = _page(144)
    ImageDraw.Draw(page).rectangle((144, 144, 287, 287), fill="black")  # the square, in pixels
    bottomleft = crop(page, LETTER, Box(1, 72, 720, 144, 648, "BOTTOMLEFT"), pad_pt=0)
    topleft = crop(page, LETTER, Box(1, 72, 72, 144, 144, "TOPLEFT"), pad_pt=0)
    assert bottomleft.tobytes() == topleft.tobytes()
    assert bottomleft.getpixel((72, 72)) == (0, 0, 0)  # the crop is the black square, not a white margin


def test_crop_pads_and_clamps_to_the_page():
    assert crop(_page(144), LETTER, Box(1, 72, 720, 144, 648, "BOTTOMLEFT"), pad_pt=6).size == (168, 168)
    corner = Box(1, 0, 792, 36, 756, "BOTTOMLEFT")  # top-left corner: padding cannot go off the page
    assert crop(_page(144), LETTER, corner, pad_pt=6).size == (84, 84)


def test_no_box_means_the_whole_page():
    page = _page(144)
    assert crop(page, LETTER, None).size == page.size


@pytest.fixture(scope="module")
def fee_lines_image() -> Image.Image:
    image = Image.new("RGB", (900, 120), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("DejaVuSans.ttf", 32)
    draw.text((10, 10), "On the first $1,000,000   0.85%", fill="black", font=font)
    draw.text((10, 60), "Thereafter   0.60%", fill="black", font=font)
    return image


def test_ocr_lines_merges_boxes_on_one_row_left_to_right(fee_lines_image):
    lines = ocr_lines(fee_lines_image)
    assert [line.text for line in lines] == ["On the first $1,000,000 0.85%", "Thereafter 0.60%"]
    left, top, right, bottom = lines[0].box
    assert left < 30 and right > 500 and top < bottom <= 60  # one box around both words of the first row


def test_ocr_lines_of_a_blank_image_is_empty():
    assert ocr_lines(Image.new("RGB", (200, 80), "white")) == []
