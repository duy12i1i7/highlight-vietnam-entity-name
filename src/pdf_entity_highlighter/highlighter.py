from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

import fitz

from pdf_entity_highlighter.ner import Entity
from pdf_entity_highlighter.ocr import (
    OcrOptions,
    OcrPage,
    find_ocr_text_rects,
    is_usable_ocr_page,
    ocr_page,
    should_ocr_page,
)

DEFAULT_COLORS: dict[str, tuple[float, float, float]] = {
    "PER": (1.0, 0.84, 0.22),
    "LOC": (0.44, 0.80, 0.45),
    "ORG": (0.36, 0.63, 0.96),
    "MISC": (0.78, 0.55, 0.90),
}


class EntityDetector(Protocol):
    def extract(self, text: str, labels: set[str]) -> list[Entity]:
        """Return named entities from plain text."""


class EntityValidator(Protocol):
    def validate(self, entity: Entity) -> tuple[bool, str | None]:
        """Return whether an entity should be highlighted."""


ProgressCallback = Callable[[int, int, str], None]
OcrPageGetter = Callable[[fitz.Page, OcrOptions], OcrPage]


@dataclass(frozen=True)
class PageHighlight:
    page: int
    text: str
    label: str
    matches: int


@dataclass(frozen=True)
class SkippedEntity:
    page: int
    text: str
    label: str
    reason: str


@dataclass(frozen=True)
class OcrFailure:
    page: int
    reason: str


@dataclass
class HighlightResult:
    input_path: str
    output_path: str
    pages_processed: int = 0
    pages_without_text: list[int] = field(default_factory=list)
    ocr_pages: list[int] = field(default_factory=list)
    ocr_failures: list[OcrFailure] = field(default_factory=list)
    highlights: list[PageHighlight] = field(default_factory=list)
    skipped: list[SkippedEntity] = field(default_factory=list)

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
            "ocr_pages": [page + 1 for page in self.ocr_pages],
            "ocr_failures": [
                {
                    "page": item.page + 1,
                    "reason": item.reason,
                }
                for item in self.ocr_failures
            ],
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
            "skipped": [
                {
                    "page": item.page + 1,
                    "text": item.text,
                    "label": item.label,
                    "reason": item.reason,
                }
                for item in self.skipped
            ],
        }


def highlight_pdf(
    input_path: str | Path,
    output_path: str | Path,
    detector: EntityDetector,
    labels: set[str],
    colors: dict[str, tuple[float, float, float]] | None = None,
    opacity: float = 0.35,
    validator: EntityValidator | None = None,
    progress_callback: ProgressCallback | None = None,
    ocr_options: OcrOptions | None = None,
    ocr_page_getter: OcrPageGetter = ocr_page,
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
        page_total = doc.page_count
        progress_total = page_total + 1
        if progress_callback:
            progress_callback(0, progress_total, "Opened PDF")

        for page_index, page in enumerate(doc):
            result.pages_processed += 1
            ocr_result: OcrPage | None = None
            if ocr_options and should_ocr_page(page, ocr_options):
                if progress_callback:
                    progress_callback(
                        page_index,
                        progress_total,
                        f"Page {page_index + 1}/{page_total}: running OCR",
                    )
                try:
                    ocr_result = ocr_page_getter(page, ocr_options)
                    result.ocr_pages.append(page_index)
                    if is_usable_ocr_page(ocr_result):
                        text = ocr_result.text
                    else:
                        text = ""
                except Exception as exc:
                    result.ocr_failures.append(OcrFailure(page=page_index, reason=str(exc)))
                    text = page.get_text("text")
            else:
                text = page.get_text("text")

            if not text.strip():
                result.pages_without_text.append(page_index)
                if progress_callback:
                    progress_callback(
                        page_index + 1,
                        progress_total,
                        f"Page {page_index + 1}/{page_total}: no extractable text",
                    )
                continue

            entities = detector.extract(text, normalized_labels)
            for entity in unique_entities(entities):
                if entity.label not in normalized_labels:
                    continue
                if validator:
                    accepted, reason = validator.validate(entity)
                    if not accepted:
                        result.skipped.append(
                            SkippedEntity(
                                page=page_index,
                                text=entity.text,
                                label=entity.label,
                                reason=reason or "rejected",
                            )
                        )
                        continue

                highlight_regions = find_highlight_regions(page, entity.text, ocr_result)
                if not highlight_regions:
                    continue

                annot = page.add_highlight_annot(highlight_regions)
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
                        matches=len(highlight_regions),
                    )
                )

            if progress_callback:
                progress_callback(
                    page_index + 1,
                    progress_total,
                    f"Page {page_index + 1}/{page_total}: highlighted",
                )

        if progress_callback:
            progress_callback(page_total, progress_total, "Saving output PDF")
        doc.save(output_path, garbage=4, deflate=True)
        if progress_callback:
            progress_callback(progress_total, progress_total, "Saved output PDF")
    finally:
        doc.close()

    return result


def find_highlight_regions(page: fitz.Page, text: str, ocr_result: OcrPage | None) -> list[fitz.Quad | fitz.Rect]:
    if ocr_result:
        regions: list[fitz.Rect] = []
        for occurrence in find_ocr_text_rects(ocr_result, text):
            regions.extend(occurrence)
        return regions

    return list(page.search_for(text, quads=True))


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
