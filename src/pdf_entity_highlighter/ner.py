from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Entity:
    text: str
    label: str


class UndertheseaEntityDetector:
    def __init__(self, min_length: int = 2) -> None:
        try:
            from underthesea import ner
        except ImportError as exc:
            raise ImportError("Underthesea is required for Vietnamese NER.") from exc

        self._ner = ner
        self._min_length = min_length

    def extract(self, text: str, labels: set[str]) -> list[Entity]:
        tagged_tokens = self._ner(text)
        return entities_from_tagged_tokens(tagged_tokens, labels, min_length=self._min_length)


def entities_from_tagged_tokens(
    tagged_tokens: list[Any],
    labels: set[str],
    min_length: int = 2,
) -> list[Entity]:
    """Build entities from BIO-style NER tags returned by Underthesea."""

    normalized_labels = {label.upper() for label in labels}
    entities: list[Entity] = []
    current_tokens: list[str] = []
    current_label: str | None = None

    def flush() -> None:
        nonlocal current_tokens, current_label
        if not current_tokens or not current_label:
            current_tokens = []
            current_label = None
            return

        text = join_entity_tokens(current_tokens)
        if current_label in normalized_labels and len(text) >= min_length:
            entities.append(Entity(text=text, label=current_label))
        current_tokens = []
        current_label = None

    for item in tagged_tokens:
        token = extract_token(item)
        tag = extract_ner_tag(item)
        prefix, label = split_bio_tag(tag)

        if prefix is None or label is None:
            flush()
            continue

        if prefix == "B" or label != current_label:
            flush()
            current_tokens = [token]
            current_label = label
            continue

        current_tokens.append(token)

    flush()
    return dedupe_entities(entities)


def extract_token(item: Any) -> str:
    if isinstance(item, (list, tuple)) and item:
        token = str(item[0])
    else:
        token = str(item)
    return token.replace("_", " ").strip()


def extract_ner_tag(item: Any) -> str:
    if not isinstance(item, (list, tuple)):
        return "O"

    for value in reversed(item):
        text = str(value)
        if text == "O" or re.match(r"^[BI]-[A-Za-z]+$", text):
            return text
    return "O"


def split_bio_tag(tag: str) -> tuple[str | None, str | None]:
    if tag == "O" or "-" not in tag:
        return None, None

    prefix, label = tag.split("-", 1)
    prefix = prefix.upper()
    label = label.upper()
    if prefix not in {"B", "I"}:
        return None, None
    return prefix, label


def join_entity_tokens(tokens: list[str]) -> str:
    text = " ".join(token for token in tokens if token)
    text = re.sub(r"\s+([,.;:!?%)\]}])", r"\1", text)
    text = re.sub(r"([([{])\s+", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def dedupe_entities(entities: list[Entity]) -> list[Entity]:
    seen: set[tuple[str, str]] = set()
    result: list[Entity] = []
    for entity in entities:
        key = (entity.label, entity.text.casefold())
        if key in seen:
            continue
        seen.add(key)
        result.append(entity)
    return result
