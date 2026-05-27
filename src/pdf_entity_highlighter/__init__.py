"""Highlight named entities in searchable PDF files."""

from pdf_entity_highlighter.highlighter import HighlightResult, highlight_pdf
from pdf_entity_highlighter.ner import Entity

__all__ = ["Entity", "HighlightResult", "highlight_pdf"]
