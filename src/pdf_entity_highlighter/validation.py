from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Protocol

from pdf_entity_highlighter.ner import Entity


class EntityValidator(Protocol):
    def validate(self, entity: Entity) -> tuple[bool, str | None]:
        """Return whether an entity should be highlighted and an optional rejection reason."""


class StrictEntityValidator:
    """Conservative rules that trade recall for fewer false positives."""

    def validate(self, entity: Entity) -> tuple[bool, str | None]:
        text = normalize_spaces(entity.text)
        if not text:
            return False, "empty text"
        if _looks_like_code_or_metadata(text):
            return False, "looks like code or metadata"

        label = entity.label.upper()
        if label == "PER":
            return self._validate_person(text)
        if label == "LOC":
            return self._validate_location(text)
        if label == "ORG":
            return self._validate_org(text)
        return False, "unsupported label in strict mode"

    def _validate_person(self, text: str) -> tuple[bool, str | None]:
        tokens = text.split()
        if not 2 <= len(tokens) <= 5:
            return False, "person name must have 2 to 5 tokens"
        if any(strip_accents(token).casefold() in GENERIC_FALSE_POSITIVE_WORDS for token in tokens):
            return False, "contains generic word"
        if not all(token and token[0].isupper() for token in tokens):
            return False, "person name is not title-cased"

        first = strip_accents(tokens[0]).casefold()
        if first not in VIETNAMESE_SURNAMES and len(tokens) < 3:
            return False, "short person name without known surname"
        return True, None

    def _validate_location(self, text: str) -> tuple[bool, str | None]:
        normalized = normalize_key(text)
        if normalized in VIETNAMESE_LOCATIONS:
            return True, None

        without_prefix = remove_location_prefix(normalized)
        if without_prefix in VIETNAMESE_LOCATIONS:
            return True, None
        if has_trusted_location_prefix(text):
            return True, None

        return False, "location is not in strict gazetteer"

    def _validate_org(self, text: str) -> tuple[bool, str | None]:
        key = normalize_key(text)
        if any(keyword in key for keyword in ORG_KEYWORDS):
            return True, None
        return False, "organization lacks trusted keyword"


class ConfirmedEntityDetector:
    """Detector that only returns user-approved entities."""

    def __init__(self, entities: list[Entity]) -> None:
        self.entities = entities

    def extract(self, text: str, labels: set[str]) -> list[Entity]:
        normalized_labels = {label.upper() for label in labels}
        page_key = normalize_key(text)
        found: list[Entity] = []
        for entity in self.entities:
            if entity.label.upper() not in normalized_labels:
                continue
            if normalize_key(entity.text) in page_key:
                found.append(entity)
        return found


def load_confirmed_entities(path: str | Path) -> list[Entity]:
    entities: list[Entity] = []
    for line_number, raw_line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        label = "MISC"
        text = line
        for separator in ("\t", ",", "|"):
            if separator in line:
                maybe_label, maybe_text = line.split(separator, 1)
                if maybe_label.strip().upper() in {"PER", "LOC", "ORG", "MISC"}:
                    label = maybe_label.strip().upper()
                    text = maybe_text.strip()
                break

        text = normalize_spaces(text)
        if not text:
            raise ValueError(f"Confirmed entity list has empty text on line {line_number}.")
        entities.append(Entity(text=text, label=label))
    return dedupe_entities(entities)


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_key(text: str) -> str:
    return strip_accents(normalize_spaces(text)).casefold()


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    without_marks = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    return without_marks.replace("Đ", "D").replace("đ", "d")


def remove_location_prefix(key: str) -> str:
    for prefix in LOCATION_PREFIXES:
        if key.startswith(prefix):
            return key[len(prefix) :]
    return key


def has_trusted_location_prefix(text: str) -> bool:
    key = normalize_key(text)
    if any(word in key for word in LOCATION_STOP_WORDS):
        return False

    without_prefix = remove_location_prefix(key)
    if without_prefix == key:
        return False

    tokens = without_prefix.split()
    if not 1 <= len(tokens) <= 5:
        return False

    return any(re.search(r"[A-Za-zÀ-ỹĐđ]", token) for token in tokens)


def dedupe_entities(entities: list[Entity]) -> list[Entity]:
    seen: set[tuple[str, str]] = set()
    result: list[Entity] = []
    for entity in entities:
        key = (entity.label.upper(), normalize_key(entity.text))
        if key in seen:
            continue
        seen.add(key)
        result.append(Entity(text=entity.text, label=entity.label.upper()))
    return result


def _looks_like_code_or_metadata(text: str) -> bool:
    key = normalize_key(text)
    if any(word in key for word in METADATA_WORDS):
        return True
    if re.search(r"\d", text):
        return True
    if re.search(r"[#_/\\]|[A-Z]{2,}-\d|-\w*\d|\d\w*-", text):
        return True
    return False


GENERIC_FALSE_POSITIVE_WORDS = {
    "ban",
    "bieu",
    "chuong",
    "dong",
    "file",
    "muc",
    "phieu",
    "tai",
    "van ban",
}

METADATA_WORDS = {
    "ky hieu",
    "ma ho so",
    "ma so",
    "phong ban",
    "so hieu",
}

LOCATION_PREFIXES = (
    "thanh pho ",
    "tp. ",
    "tp ",
    "tinh ",
    "quan ",
    "huyen ",
    "thi xa ",
    "thi tran ",
    "xa ",
    "phuong ",
    "to dan pho ",
    "tdp ",
    "duong ",
)

LOCATION_STOP_WORDS = {
    "canh sat",
    "co quan",
    "cong an",
    "gioi tinh",
    "nguoi",
    "quyet dinh",
    "tien an",
    "tien su",
}

VIETNAMESE_SURNAMES = {
    "an",
    "bach",
    "bui",
    "cao",
    "chu",
    "dang",
    "dao",
    "dinh",
    "do",
    "doan",
    "duong",
    "giang",
    "ha",
    "ho",
    "hoang",
    "huynh",
    "khuc",
    "kieu",
    "la",
    "lai",
    "lam",
    "le",
    "lu",
    "luong",
    "ly",
    "mac",
    "mai",
    "nghiem",
    "ngo",
    "nguyen",
    "nham",
    "phan",
    "phi",
    "phung",
    "quach",
    "ta",
    "thach",
    "thai",
    "than",
    "tran",
    "trieu",
    "trinh",
    "truong",
    "van",
    "vi",
    "vo",
    "vu",
    "vũ",
}

VIETNAMESE_LOCATIONS = {
    normalize_key(name)
    for name in {
        "An Giang",
        "Bà Rịa Vũng Tàu",
        "Bắc Giang",
        "Bắc Kạn",
        "Bạc Liêu",
        "Bắc Ninh",
        "Bến Tre",
        "Bình Định",
        "Bình Dương",
        "Bình Phước",
        "Bình Thuận",
        "Cà Mau",
        "Cần Thơ",
        "Cao Bằng",
        "Đà Nẵng",
        "Đắk Lắk",
        "Đắk Nông",
        "Điện Biên",
        "Đồng Nai",
        "Đồng Tháp",
        "Gia Lai",
        "Hà Giang",
        "Hà Nam",
        "Hà Nội",
        "Hà Tĩnh",
        "Hải Dương",
        "Hải Phòng",
        "Hậu Giang",
        "Hòa Bình",
        "Hồ Chí Minh",
        "Hưng Yên",
        "Khánh Hòa",
        "Kiên Giang",
        "Kon Tum",
        "Lai Châu",
        "Lâm Đồng",
        "Lạng Sơn",
        "Lào Cai",
        "Long An",
        "Nam Định",
        "Nghệ An",
        "Ninh Bình",
        "Ninh Thuận",
        "Phú Thọ",
        "Phú Yên",
        "Quảng Bình",
        "Quảng Nam",
        "Quảng Ngãi",
        "Quảng Ninh",
        "Quảng Trị",
        "Sóc Trăng",
        "Sơn La",
        "Tây Ninh",
        "Thái Bình",
        "Thái Nguyên",
        "Thanh Hóa",
        "Thừa Thiên Huế",
        "Huế",
        "Tiền Giang",
        "Trà Vinh",
        "Tuyên Quang",
        "Vĩnh Long",
        "Vĩnh Phúc",
        "Yên Bái",
        "Việt Nam",
        "Sài Gòn",
        "Nha Trang",
        "Đà Lạt",
        "Hạ Long",
        "Vũng Tàu",
        "Phú Quốc",
        "Hội An",
        "Cam Ranh",
        "Buôn Ma Thuột",
        "Bảo Lộc",
        "Biên Hòa",
        "Biên Hoà",
        "Pleiku",
        "Mỹ Tho",
        "Rạch Giá",
        "Long Xuyên",
        "Côn Đảo",
        "Điện Biên Phủ",
        "Mộc Châu",
        "Phan Thiết",
        "Quy Nhơn",
        "Sa Pa",
        "Thủ Dầu Một",
        "Tuy Hòa",
        "Tuy Hoà",
    }
}

ORG_KEYWORDS = {
    "bo ",
    "cong ty",
    "dai hoc",
    "hoc vien",
    "ngan hang",
    "so ",
    "tap doan",
    "to chuc",
    "ubnd",
    "uy ban",
    "vien ",
}
