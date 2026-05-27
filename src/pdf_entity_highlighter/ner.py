from __future__ import annotations

import re
import os
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path
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


class VnCoreNlpEntityDetector:
    def __init__(
        self,
        model_dir: str | Path | None = None,
        download: bool = False,
        min_length: int = 2,
        max_heap_size: str = "-Xmx2g",
    ) -> None:
        ensure_java_runtime()
        try:
            import py_vncorenlp
        except ImportError as exc:
            raise ImportError(
                "py_vncorenlp is required for the VnCoreNLP engine. "
                'Install it with: python -m pip install -e ".[vncorenlp]"'
            ) from exc

        self.model_dir = Path(model_dir).expanduser().resolve() if model_dir else default_vncorenlp_dir()
        if download:
            download_vncorenlp_model(self.model_dir)
        if not vncorenlp_model_exists(self.model_dir):
            raise FileNotFoundError(
                "VnCoreNLP model files were not found. Run with "
                f"--download-vncorenlp --vncorenlp-dir {self.model_dir}"
            )

        current_dir = Path.cwd()
        try:
            self._model = py_vncorenlp.VnCoreNLP(
                annotators=["wseg", "pos", "ner"],
                save_dir=str(self.model_dir),
                max_heap_size=max_heap_size,
            )
        finally:
            os.chdir(current_dir)
        self._min_length = min_length

    def extract(self, text: str, labels: set[str]) -> list[Entity]:
        annotation = self._model.annotate_text(text)
        return entities_from_vncorenlp_annotation(annotation, labels, min_length=self._min_length)


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


def entities_from_vncorenlp_annotation(
    annotation: Any,
    labels: set[str],
    min_length: int = 2,
) -> list[Entity]:
    tagged_tokens: list[tuple[str, str]] = []
    if isinstance(annotation, dict):
        sentences = [annotation[key] for key in sorted(annotation)]
    else:
        sentences = annotation

    for sentence in sentences:
        for item in sentence:
            if isinstance(item, dict):
                token = item.get("wordForm") or item.get("word") or item.get("form") or ""
                tag = item.get("nerLabel") or item.get("ner") or item.get("nerTag") or "O"
            elif isinstance(item, (list, tuple)) and len(item) >= 4:
                token = item[1]
                tag = item[3]
            else:
                continue
            tagged_tokens.append((str(token), str(tag)))

    return entities_from_tagged_tokens(tagged_tokens, labels, min_length=min_length)


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


def ensure_java_runtime() -> None:
    if not os.environ.get("JAVA_HOME"):
        for candidate in (
            Path("/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"),
            Path("/usr/local/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"),
            Path("/opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home"),
            Path("/usr/local/opt/openjdk/libexec/openjdk.jdk/Contents/Home"),
        ):
            if candidate.exists():
                os.environ["JAVA_HOME"] = str(candidate)
                break

    java = shutil.which("java")
    if not java:
        raise RuntimeError("VnCoreNLP requires Java 1.8+ but no java executable was found.")

    result = subprocess.run([java, "-version"], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("VnCoreNLP requires a working Java 1.8+ runtime.")


def default_vncorenlp_dir() -> Path:
    return Path.home() / ".pdf-entity-highlighter" / "vncorenlp"


def vncorenlp_model_exists(model_dir: str | Path) -> bool:
    model_dir = Path(model_dir)
    return (model_dir / "VnCoreNLP-1.2.jar").exists() and (model_dir / "models").is_dir()


def download_vncorenlp_model(model_dir: str | Path) -> None:
    model_dir = Path(model_dir).expanduser().resolve()
    files = {
        "VnCoreNLP-1.2.jar": "VnCoreNLP-1.2.jar",
        "models/wordsegmenter/vi-vocab": "models/wordsegmenter/vi-vocab",
        "models/wordsegmenter/wordsegmenter.rdr": "models/wordsegmenter/wordsegmenter.rdr",
        "models/postagger/vi-tagger": "models/postagger/vi-tagger",
        "models/ner/vi-500brownclusters.xz": "models/ner/vi-500brownclusters.xz",
        "models/ner/vi-ner.xz": "models/ner/vi-ner.xz",
        "models/ner/vi-pretrainedembeddings.xz": "models/ner/vi-pretrainedembeddings.xz",
    }

    base_url = "https://raw.githubusercontent.com/vncorenlp/VnCoreNLP/master"
    for relative_path, remote_path in files.items():
        destination = model_dir / relative_path
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(f"{base_url}/{remote_path}", destination)
