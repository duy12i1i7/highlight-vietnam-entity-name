import fitz

from pdf_entity_highlighter.ocr import (
    OcrPage,
    OcrOptions,
    OcrWord,
    find_ocr_text_rects,
    is_usable_ocr_page,
    parse_tesseract_tsv,
)


def test_parse_tesseract_tsv_builds_text_and_word_rects() -> None:
    tsv = "\n".join(
        [
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
            "5\t1\t1\t1\t1\t1\t10\t20\t40\t10\t95\tNguyễn",
            "5\t1\t1\t1\t1\t2\t55\t20\t25\t10\t94\tVăn",
            "5\t1\t1\t1\t2\t1\t10\t45\t45\t10\t93\tHà",
            "5\t1\t1\t1\t2\t2\t60\t45\t35\t10\t92\tNội",
        ]
    )

    page = parse_tesseract_tsv(tsv, fitz.Rect(0, 0, 200, 200), scale=2)

    assert page.text == "Nguyễn Văn\nHà Nội"
    assert page.words[0].rect == fitz.Rect(5, 10, 25, 15)
    assert page.words[-1].start == len("Nguyễn Văn\nHà ")


def test_find_ocr_text_rects_returns_entity_word_boxes() -> None:
    page = OcrPage(
        text="Ông Nguyễn Văn A ở Hà Nội",
        words=[
            OcrWord("Ông", fitz.Rect(0, 0, 10, 10), 0, 3, (1, 1, 1), 90),
            OcrWord("Nguyễn", fitz.Rect(12, 0, 42, 10), 4, 10, (1, 1, 1), 90),
            OcrWord("Văn", fitz.Rect(44, 0, 58, 10), 11, 14, (1, 1, 1), 90),
            OcrWord("A", fitz.Rect(60, 0, 66, 10), 15, 16, (1, 1, 1), 90),
            OcrWord("ở", fitz.Rect(68, 0, 74, 10), 17, 18, (1, 1, 1), 90),
            OcrWord("Hà", fitz.Rect(76, 0, 86, 10), 19, 21, (1, 1, 1), 90),
            OcrWord("Nội", fitz.Rect(88, 0, 102, 10), 22, 25, (1, 1, 1), 90),
        ],
    )

    matches = find_ocr_text_rects(page, "Nguyễn Văn A")

    assert matches == [[fitz.Rect(12, 0, 42, 10), fitz.Rect(44, 0, 58, 10), fitz.Rect(60, 0, 66, 10)]]


def test_ocr_options_default_to_auto() -> None:
    assert OcrOptions().mode == "auto"


def test_is_usable_ocr_page_rejects_low_signal_noise() -> None:
    page = OcrPage(
        text="@@@ === ---",
        words=[
            OcrWord("@@@", fitz.Rect(0, 0, 10, 10), 0, 3, (1, 1, 1), 10),
            OcrWord("===", fitz.Rect(12, 0, 22, 10), 4, 7, (1, 1, 1), 10),
            OcrWord("---", fitz.Rect(24, 0, 34, 10), 8, 11, (1, 1, 1), 10),
            OcrWord("...", fitz.Rect(36, 0, 46, 10), 12, 15, (1, 1, 1), 10),
            OcrWord("~~~", fitz.Rect(48, 0, 58, 10), 16, 19, (1, 1, 1), 10),
        ],
    )

    assert is_usable_ocr_page(page) is False
