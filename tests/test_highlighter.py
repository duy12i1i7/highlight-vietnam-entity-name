from pathlib import Path

import fitz

from pdf_entity_highlighter.highlighter import highlight_pdf
from pdf_entity_highlighter.ner import Entity
from pdf_entity_highlighter.ocr import OcrPage, OcrOptions, OcrWord


class FakeDetector:
    def extract(self, text: str, labels: set[str]) -> list[Entity]:
        return [
            Entity("Nguyen Van A", "PER"),
            Entity("Ha Noi", "LOC"),
            Entity("Cong ty ABC", "ORG"),
        ]


def test_highlight_pdf_adds_annotations(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Nguyen Van A dang lam viec tai Ha Noi cho Cong ty ABC.")
    doc.save(input_path)
    doc.close()

    result = highlight_pdf(input_path, output_path, FakeDetector(), {"PER", "LOC"})

    assert output_path.exists()
    assert result.total_entities == 2
    assert result.total_highlights == 2

    highlighted = fitz.open(output_path)
    try:
        annotations = list(highlighted[0].annots() or [])
    finally:
        highlighted.close()

    assert len(annotations) == 2


def test_highlight_pdf_reports_page_progress(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"

    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Nguyen Van A o Ha Noi.")
    doc.new_page().insert_text((72, 72), "Nguyen Van A o Ha Noi.")
    doc.save(input_path)
    doc.close()

    events: list[tuple[int, int, str]] = []
    highlight_pdf(
        input_path,
        output_path,
        FakeDetector(),
        {"PER", "LOC"},
        progress_callback=lambda current, total, message: events.append((current, total, message)),
    )

    assert events[0] == (0, 3, "Opened PDF")
    assert events[-1] == (3, 3, "Saved output PDF")
    assert [event[0] for event in events] == [0, 1, 2, 2, 3]


def test_highlight_pdf_can_use_ocr_word_boxes(tmp_path: Path) -> None:
    input_path = tmp_path / "scan.pdf"
    output_path = tmp_path / "output.pdf"

    doc = fitz.open()
    doc.new_page()
    doc.save(input_path)
    doc.close()

    def fake_ocr_page(_page, _options):
        return OcrPage(
            text="Nguyen Van A o Ha Noi",
            words=[
                OcrWord("Nguyen", fitz.Rect(72, 72, 110, 84), 0, 6, (1, 1, 1), 90),
                OcrWord("Van", fitz.Rect(112, 72, 136, 84), 7, 10, (1, 1, 1), 90),
                OcrWord("A", fitz.Rect(138, 72, 148, 84), 11, 12, (1, 1, 1), 90),
                OcrWord("o", fitz.Rect(150, 72, 158, 84), 13, 14, (1, 1, 1), 90),
                OcrWord("Ha", fitz.Rect(160, 72, 176, 84), 15, 17, (1, 1, 1), 90),
                OcrWord("Noi", fitz.Rect(178, 72, 200, 84), 18, 21, (1, 1, 1), 90),
            ],
        )

    result = highlight_pdf(
        input_path,
        output_path,
        FakeDetector(),
        {"PER", "LOC"},
        ocr_options=OcrOptions(mode="always"),
        ocr_page_getter=fake_ocr_page,
    )

    assert result.ocr_pages == [0]
    assert result.total_entities == 2
    assert result.total_highlights == 5

    highlighted = fitz.open(output_path)
    try:
        annotations = list(highlighted[0].annots() or [])
    finally:
        highlighted.close()

    assert len(annotations) == 2
