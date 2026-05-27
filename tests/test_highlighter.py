from pathlib import Path

import fitz

from pdf_entity_highlighter.highlighter import highlight_pdf
from pdf_entity_highlighter.ner import Entity


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
