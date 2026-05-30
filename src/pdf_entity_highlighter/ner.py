from __future__ import annotations

import re
import os
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


VNCORENLP_MODEL_FILES = {
    "VnCoreNLP-1.2.jar": "VnCoreNLP-1.2.jar",
    "models/wordsegmenter/vi-vocab": "models/wordsegmenter/vi-vocab",
    "models/wordsegmenter/wordsegmenter.rdr": "models/wordsegmenter/wordsegmenter.rdr",
    "models/postagger/vi-tagger": "models/postagger/vi-tagger",
    "models/ner/vi-500brownclusters.xz": "models/ner/vi-500brownclusters.xz",
    "models/ner/vi-ner.xz": "models/ner/vi-ner.xz",
    "models/ner/vi-pretrainedembeddings.xz": "models/ner/vi-pretrainedembeddings.xz",
}

ModelProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True)
class Entity:
    text: str
    label: str


class VnCoreNlpEntityDetector:
    def __init__(
        self,
        model_dir: str | Path | None = None,
        download: bool = False,
        min_length: int = 2,
        max_heap_size: str = "-Xmx2g",
        prepare_progress_callback: ModelProgressCallback | None = None,
    ) -> None:
        ensure_java_runtime()
        try:
            import py_vncorenlp
        except ImportError as exc:
            raise ImportError(
                "py_vncorenlp is required for VnCoreNLP. "
                "Install the project dependencies with: python -m pip install -e ."
            ) from exc

        self.model_dir = (
            Path(model_dir).expanduser().resolve()
            if model_dir
            else prepare_default_vncorenlp_model(prepare_progress_callback)
        )
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
        text = clean_ner_text(text)
        if not text:
            return []
        try:
            return self._extract_once(text, labels)
        except Exception:
            return self._extract_from_chunks(text, labels)

    def _extract_once(self, text: str, labels: set[str]) -> list[Entity]:
        annotation = self._model.annotate_text(text)
        return entities_from_vncorenlp_annotation(annotation, labels, min_length=self._min_length)

    def _extract_from_chunks(self, text: str, labels: set[str]) -> list[Entity]:
        entities: list[Entity] = []
        for chunk in split_ner_chunks(text):
            try:
                entities.extend(self._extract_once(chunk, labels))
            except Exception:
                continue
        return dedupe_entities(entities)


def entities_from_tagged_tokens(
    tagged_tokens: list[Any],
    labels: set[str],
    min_length: int = 2,
) -> list[Entity]:
    """Build entities from BIO-style NER tags."""

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


def clean_ner_text(text: str) -> str:
    lines = [normalize_text_line(line) for line in text.splitlines()]
    return "\n".join(line for line in lines if is_likely_text_line(line))


def split_ner_chunks(text: str, max_chars: int = 1800) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for line in text.splitlines():
        line = normalize_text_line(line)
        if not is_likely_text_line(line):
            continue
        if current and current_length + len(line) + 1 > max_chars:
            chunks.append("\n".join(current))
            current = []
            current_length = 0
        current.append(line)
        current_length += len(line) + 1

    if current:
        chunks.append("\n".join(current))
    return chunks


def normalize_text_line(line: str) -> str:
    line = re.sub(r"[^\w\sÀ-ỹĐđ,.;:()/%\\-]", " ", line, flags=re.UNICODE)
    return re.sub(r"\s+", " ", line).strip()


def is_likely_text_line(line: str) -> bool:
    if len(line) < 2:
        return False
    letters = re.findall(r"[A-Za-zÀ-ỹĐđ]", line)
    if len(letters) < 2:
        return False
    return len(letters) / max(len(line), 1) >= 0.35


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
    bundled_home = bundled_java_home()
    if bundled_home:
        os.environ["JAVA_HOME"] = str(bundled_home)
        prepend_path(bundled_home / "bin")
    elif os.environ.get("JAVA_HOME"):
        prepend_path(Path(os.environ["JAVA_HOME"]) / "bin")
    else:
        for candidate in java_home_candidates():
            if candidate.exists():
                os.environ["JAVA_HOME"] = str(candidate)
                prepend_path(candidate / "bin")
                break

    java = shutil.which("java")
    if not java:
        raise RuntimeError("VnCoreNLP requires Java 1.8+ but no java executable was found.")

    result = subprocess.run([java, "-version"], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("VnCoreNLP requires a working Java 1.8+ runtime.")


def default_vncorenlp_dir() -> Path:
    return Path.home() / ".pdf-entity-highlighter" / "vncorenlp"


def prepare_default_vncorenlp_model(progress_callback: ModelProgressCallback | None = None) -> Path:
    bundled_dir = bundled_vncorenlp_dir()
    if not bundled_dir:
        return default_vncorenlp_dir()

    target_dir = default_vncorenlp_dir()
    if vncorenlp_model_exists(target_dir):
        return target_dir

    copy_vncorenlp_model(bundled_dir, target_dir, progress_callback=progress_callback)
    return target_dir


def vncorenlp_model_exists(model_dir: str | Path) -> bool:
    model_dir = Path(model_dir)
    return all((model_dir / relative_path).exists() for relative_path in VNCORENLP_MODEL_FILES)


def download_vncorenlp_model(model_dir: str | Path) -> None:
    model_dir = Path(model_dir).expanduser().resolve()

    base_url = "https://raw.githubusercontent.com/vncorenlp/VnCoreNLP/master"
    for relative_path, remote_path in VNCORENLP_MODEL_FILES.items():
        destination = model_dir / relative_path
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(f"{base_url}/{remote_path}", destination)


def copy_vncorenlp_model(
    source_dir: str | Path,
    target_dir: str | Path,
    progress_callback: ModelProgressCallback | None = None,
) -> None:
    source_dir = Path(source_dir)
    target_dir = Path(target_dir).expanduser().resolve()
    total = len(VNCORENLP_MODEL_FILES)

    for index, relative_path in enumerate(VNCORENLP_MODEL_FILES, start=1):
        source = source_dir / relative_path
        destination = target_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        if progress_callback:
            progress_callback(index, total, f"Preparing built-in VnCoreNLP model ({index}/{total})")


def resource_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parents[2]


def bundled_vncorenlp_dir() -> Path | None:
    candidate = resource_root() / "vncorenlp"
    if vncorenlp_model_exists(candidate):
        return candidate
    return None


def bundled_java_home() -> Path | None:
    candidate = resource_root() / "java-runtime"
    executable = "java.exe" if os.name == "nt" else "java"
    if (candidate / "bin" / executable).exists():
        return candidate
    return None


def java_home_candidates() -> tuple[Path, ...]:
    return (
        Path("/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"),
        Path("/usr/local/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"),
        Path("/opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home"),
        Path("/usr/local/opt/openjdk/libexec/openjdk.jdk/Contents/Home"),
    )


def prepend_path(path: Path) -> None:
    if not path.exists():
        return
    current = os.environ.get("PATH", "")
    path_text = str(path)
    entries = current.split(os.pathsep) if current else []
    if path_text not in entries:
        os.environ["PATH"] = os.pathsep.join([path_text, *entries])
