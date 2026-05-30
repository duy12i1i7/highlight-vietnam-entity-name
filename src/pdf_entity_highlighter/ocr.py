from __future__ import annotations

import csv
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

import fitz


OCR_MODES = ("never", "auto", "always")
OCRMode = Literal["never", "auto", "always"]
OcrProgressCallback = Callable[[int, int, str], None]

TESSDATA_FILES = {
    "vie.traineddata": "https://github.com/tesseract-ocr/tessdata_fast/raw/main/vie.traineddata",
}


@dataclass(frozen=True)
class OcrOptions:
    mode: OCRMode = "auto"
    language: str = "vie"
    dpi: int = 300
    psm: int = 6
    min_confidence: float = 0.0
    download_data: bool = False
    tessdata_dir: str | Path | None = None


@dataclass(frozen=True)
class OcrWord:
    text: str
    rect: fitz.Rect
    start: int
    end: int
    line_key: tuple[int, int, int]
    confidence: float


@dataclass(frozen=True)
class OcrPage:
    text: str
    words: list[OcrWord]


def should_ocr_page(page: fitz.Page, options: OcrOptions) -> bool:
    if options.mode == "never":
        return False
    if options.mode == "always":
        return True

    text = page.get_text("text").strip()
    if not text:
        return True

    return full_page_image_coverage(page) >= 0.65


def ocr_page(page: fitz.Page, options: OcrOptions) -> OcrPage:
    tesseract = find_tesseract_executable()
    tessdata_dir = prepare_tessdata_dir(
        download=options.download_data,
        preferred_dir=options.tessdata_dir,
        language=options.language,
    )
    if not tesseract:
        raise RuntimeError("OCR requires Tesseract, but no bundled or system tesseract executable was found.")
    if not tessdata_language_exists(tessdata_dir, options.language):
        raise RuntimeError(
            "OCR language data is missing. Run with --download-ocr-data or use the packaged desktop app."
        )

    scale = options.dpi / 72
    matrix = fitz.Matrix(scale, scale)
    pixmap = page.get_pixmap(matrix=matrix, alpha=False)

    with tempfile.TemporaryDirectory(prefix="pdf-entity-ocr-") as temp_dir_text:
        temp_dir = Path(temp_dir_text)
        image_path = temp_dir / "page.png"
        pixmap.save(image_path)

        command = [
            str(tesseract),
            image_path.name,
            "stdout",
            "-l",
            options.language,
            "--psm",
            str(options.psm),
            "-c",
            "tessedit_create_tsv=1",
        ]
        result = subprocess.run(
            command,
            cwd=temp_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=ocr_subprocess_env(tessdata_dir),
        )
        if result.returncode != 0:
            raise RuntimeError(normalize_tesseract_error(result.stderr))

        return parse_tesseract_tsv(result.stdout, page.rect, scale, options.min_confidence)


def parse_tesseract_tsv(tsv_text: str, page_rect: fitz.Rect, scale: float, min_confidence: float = 0.0) -> OcrPage:
    rows = csv.DictReader(tsv_text.splitlines(), delimiter="\t")
    raw_words: list[dict[str, object]] = []
    for row in rows:
        if row.get("level") != "5":
            continue
        text = normalize_ocr_token(row.get("text", ""))
        if not text:
            continue
        confidence = parse_confidence(row.get("conf", "-1"))
        if confidence < min_confidence:
            continue

        left = parse_int(row.get("left"))
        top = parse_int(row.get("top"))
        width = parse_int(row.get("width"))
        height = parse_int(row.get("height"))
        line_key = (
            parse_int(row.get("block_num")),
            parse_int(row.get("par_num")),
            parse_int(row.get("line_num")),
        )
        word_number = parse_int(row.get("word_num"))
        rect = fitz.Rect(
            page_rect.x0 + left / scale,
            page_rect.y0 + top / scale,
            page_rect.x0 + (left + width) / scale,
            page_rect.y0 + (top + height) / scale,
        )
        raw_words.append(
            {
                "text": text,
                "line_key": line_key,
                "word_number": word_number,
                "rect": rect,
                "confidence": confidence,
            }
        )

    raw_words.sort(key=lambda item: (*item["line_key"], item["word_number"]))

    text_parts: list[str] = []
    words: list[OcrWord] = []
    current_line: tuple[int, int, int] | None = None
    cursor = 0

    for item in raw_words:
        line_key = item["line_key"]
        if current_line is not None:
            separator = "\n" if line_key != current_line else " "
            text_parts.append(separator)
            cursor += len(separator)

        word_text = str(item["text"])
        start = cursor
        text_parts.append(word_text)
        cursor += len(word_text)
        words.append(
            OcrWord(
                text=word_text,
                rect=item["rect"],
                start=start,
                end=cursor,
                line_key=line_key,
                confidence=float(item["confidence"]),
            )
        )
        current_line = line_key

    return OcrPage(text="".join(text_parts), words=words)


def find_ocr_text_rects(ocr_result: OcrPage, text: str) -> list[list[fitz.Rect]]:
    normalized_text = normalize_spaces(text)
    if not normalized_text:
        return []

    occurrences: list[list[fitz.Rect]] = []
    pattern = re.compile(re.escape(normalized_text), flags=re.IGNORECASE)
    for match in pattern.finditer(ocr_result.text):
        rects = [
            word.rect
            for word in ocr_result.words
            if word.end > match.start() and word.start < match.end()
        ]
        if rects:
            occurrences.append(rects)
    return occurrences


def is_usable_ocr_page(ocr_result: OcrPage) -> bool:
    if len(ocr_result.words) < 5:
        return False

    raw_length = sum(len(word.text) for word in ocr_result.words)
    if raw_length == 0:
        return False

    alpha_length = sum(len(re.findall(r"[A-Za-zÀ-ỹĐđ]", word.text)) for word in ocr_result.words)
    alpha_ratio = alpha_length / raw_length
    median_confidence = statistics.median(word.confidence for word in ocr_result.words)

    return alpha_ratio >= 0.35 and median_confidence >= 35


def full_page_image_coverage(page: fitz.Page) -> float:
    page_area = max(page.rect.get_area(), 1.0)
    max_coverage = 0.0
    try:
        image_infos = page.get_image_info(xrefs=True)
    except Exception:
        image_infos = []

    for image_info in image_infos:
        bbox = image_info.get("bbox")
        if not bbox:
            continue
        rect = fitz.Rect(bbox) & page.rect
        max_coverage = max(max_coverage, rect.get_area() / page_area)

    return min(max_coverage, 1.0)


def find_tesseract_executable() -> Path | None:
    bundled = bundled_tesseract_executable()
    if bundled:
        return bundled

    system = shutil.which("tesseract")
    return Path(system) if system else None


def bundled_tesseract_executable() -> Path | None:
    runtime_dir = resource_root() / "tesseract-runtime"
    executable = "tesseract.exe" if os.name == "nt" else "tesseract"
    candidates = [
        runtime_dir / "bin" / executable,
        runtime_dir / executable,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def prepare_tessdata_dir(
    download: bool = False,
    preferred_dir: str | Path | None = None,
    language: str = "vie",
) -> Path:
    if preferred_dir:
        preferred = Path(preferred_dir).expanduser().resolve()
        if download and not tessdata_language_exists(preferred, "vie"):
            download_tessdata(preferred)
        if tessdata_language_exists(preferred, language):
            return preferred

    bundled_dir = bundled_tessdata_dir()
    target_dir = default_tessdata_dir()
    if bundled_dir and not tessdata_language_exists(target_dir, "vie"):
        copy_tessdata(bundled_dir, target_dir)

    if download and not tessdata_language_exists(target_dir, "vie"):
        download_tessdata(target_dir)

    if tessdata_language_exists(target_dir, language):
        return target_dir

    system_dir = system_tessdata_dir()
    if tessdata_language_exists(system_dir, language):
        return system_dir

    return target_dir


def download_tessdata(tessdata_dir: str | Path) -> None:
    tessdata_dir = Path(tessdata_dir).expanduser().resolve()
    tessdata_dir.mkdir(parents=True, exist_ok=True)
    for filename, url in TESSDATA_FILES.items():
        destination = tessdata_dir / filename
        if destination.exists():
            continue
        urllib.request.urlretrieve(url, destination)


def copy_tessdata(source_dir: str | Path, target_dir: str | Path) -> None:
    source_dir = Path(source_dir)
    target_dir = Path(target_dir).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    for filename in TESSDATA_FILES:
        source = source_dir / filename
        if source.exists():
            shutil.copy2(source, target_dir / filename)


def tessdata_language_exists(tessdata_dir: str | Path, language: str) -> bool:
    tessdata_dir = Path(tessdata_dir)
    for code in language.split("+"):
        if code and not (tessdata_dir / f"{code}.traineddata").exists():
            return False
    return True


def bundled_tessdata_dir() -> Path | None:
    candidate = resource_root() / "tessdata"
    if tessdata_language_exists(candidate, "vie"):
        return candidate
    return None


def default_tessdata_dir() -> Path:
    return Path.home() / ".pdf-entity-highlighter" / "tessdata"


def system_tessdata_dir() -> Path:
    env_value = os.environ.get("TESSDATA_PREFIX")
    if env_value:
        return Path(env_value)
    if sys.platform == "darwin":
        return Path("/opt/homebrew/share/tessdata")
    if os.name == "nt":
        return Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "Tesseract-OCR" / "tessdata"
    return Path("/usr/share/tesseract-ocr/5/tessdata")


def ocr_subprocess_env(tessdata_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["TESSDATA_PREFIX"] = str(tessdata_dir)
    tesseract_dir = bundled_tesseract_executable()
    if tesseract_dir:
        runtime_dir = tesseract_dir.parents[1] if tesseract_dir.parent.name == "bin" else tesseract_dir.parent
        prepend_env_path(env, "PATH", tesseract_dir.parent)
        prepend_env_path(env, "LD_LIBRARY_PATH", runtime_dir / "lib")
        prepend_env_path(env, "DYLD_LIBRARY_PATH", runtime_dir / "lib")
    return env


def resource_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parents[2]


def prepend_env_path(env: dict[str, str], key: str, path: Path) -> None:
    if not path.exists():
        return
    current = env.get(key, "")
    value = str(path)
    parts = current.split(os.pathsep) if current else []
    if value not in parts:
        env[key] = os.pathsep.join([value, *parts])


def normalize_tesseract_error(stderr: str) -> str:
    text = normalize_spaces(stderr)
    return text or "Tesseract OCR failed."


def normalize_ocr_token(text: object) -> str:
    return normalize_spaces(str(text or ""))


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_confidence(value: object) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return -1.0


def parse_int(value: object) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0
