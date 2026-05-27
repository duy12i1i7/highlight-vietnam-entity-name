from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import fitz

from pdf_entity_highlighter.ner import Entity

DEFAULT_COLORS: dict[str, tuple[float, float, float]] = {
    "PER": (1.0, 0.84, 0.22),
    "LOC": (0.44, 0.80, 0.45),
    "ORG": (0.36, 0.63, 0.96),
    "MISC": (0.78, 0.55, 0.90),
}


class EntityDetector(Protocol):
    def extract(self, text: str, labels: set[str]) -> list[Entity]:
        """Return named entities from plain text."""


@dataclass(frozen=True)
class PageHighlight:
    page: int
    text: str
    label: str
    matches: int


@dataclass
class HighlightResult:
    input_path: str
    output_path: str
    pages_processed: int = 0
    pages_without_text: list[int] = field(default_factory=list)
    highlights: list[PageHighlight] = field(default_factory=list)

    @property
    def total_highlights(self) -> int:
        return sum(item.matches for item in self.highlights)

    @property
    def total_entities(self) -> int:
        return len(self.highlights)

    def to_dict(self) -> dict[str, object]:
        return {
            "input_path": self.input_path,
            "output_path": self.output_path,
            "pages_processed": self.pages_processed,
            "pages_without_text": [page + 1 for page in self.pages_without_text],
            "total_entities": self.total_entities,
            "total_highlights": self.total_highlights,
            "highlights": [
                {
                    "page": item.page + 1,
                    "text": item.text,
                    "label": item.label,
                    "matches": item.matches,
                }
                for item in self.highlights
            ],
        }


def highlight_pdf(
    input_path: str | Path,
    output_path: str | Path,
    detector: EntityDetector,
    labels: set[str],
    colors: dict[str, tuple[float, float, float]] | None = None,
    opacity: float = 0.35,
) -> HighlightResult:
    """Highlight detected entities in a PDF and save a new PDF."""

    input_path = Path(input_path)
    output_path = Path(output_path)
    normalized_labels = {label.upper() for label in labels}
    palette = DEFAULT_COLORS.copy()
    if colors:
        palette.update({label.upper(): color for label, color in colors.items()})

    result = HighlightResult(str(input_path), str(output_path))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(input_path)
    try:
        for page_index, page in enumerate(doc):
            result.pages_processed += 1
            text = page.get_text("text")
            if not text.strip():
                result.pages_without_text.append(page_index)
                continue

            entities = detector.extract(text, normalized_labels)
            for entity in unique_entities(entities):
                if entity.label not in normalized_labels:
                    continue

                quads = page.search_for(entity.text, quads=True)
                if not quads:
                    continue

                annot = page.add_highlight_annot(quads)
                color = palette.get(entity.label, DEFAULT_COLORS["MISC"])
                annot.set_colors(stroke=color)
                if hasattr(annot, "set_opacity"):
                    annot.set_opacity(opacity)
                annot.update()

                result.highlights.append(
                    PageHighlight(
                        page=page_index,
                        text=entity.text,
                        label=entity.label,
                        matches=len(quads),
                    )
                )

        doc.save(output_path, garbage=4, deflate=True)
    finally:
        doc.close()

    return result


def unique_entities(entities: Iterable[Entity]) -> list[Entity]:
    seen: set[tuple[str, str]] = set()
    unique: list[Entity] = []
    for entity in entities:
        key = (entity.label, entity.text.casefold())
        if key in seen:
            continue
        seen.add(key)
        unique.append(entity)
    return unique
