from pathlib import Path

from pdf_entity_highlighter.ner import Entity
from pdf_entity_highlighter.validation import (
    ConfirmedEntityDetector,
    StrictEntityValidator,
    load_confirmed_entities,
)


def test_strict_validator_rejects_metadata_false_positives() -> None:
    validator = StrictEntityValidator()

    assert validator.validate(Entity("Trang", "PER"))[0] is False
    assert validator.validate(Entity("ký hiệu HS-0101-VN", "LOC"))[0] is False
    assert validator.validate(Entity("phòng ban PB63", "LOC"))[0] is False
    assert validator.validate(Entity("Văn bản tiếng Việt", "LOC"))[0] is False


def test_strict_validator_accepts_common_vietnamese_entities() -> None:
    validator = StrictEntityValidator()

    assert validator.validate(Entity("Đinh Lan Hương", "PER"))[0] is True
    assert validator.validate(Entity("Nha Trang", "LOC"))[0] is True
    assert validator.validate(Entity("Việt Nam", "LOC"))[0] is True
    assert validator.validate(Entity("phường Hồng Giang", "LOC"))[0] is True
    assert validator.validate(Entity("thị xã Chũ", "LOC"))[0] is True
    assert validator.validate(Entity("Tổ dân phố Nguộn Trong", "LOC"))[0] is True
    assert validator.validate(Entity("tỉnh Bắc Giang Tiền án", "LOC"))[0] is False


def test_load_confirmed_entities(tmp_path: Path) -> None:
    path = tmp_path / "confirmed.txt"
    path.write_text(
        "# approved\nPER,Nguyễn Văn A\nLOC|Hà Nội\nMISC entry without label\n",
        encoding="utf-8",
    )

    assert load_confirmed_entities(path) == [
        Entity("Nguyễn Văn A", "PER"),
        Entity("Hà Nội", "LOC"),
        Entity("MISC entry without label", "MISC"),
    ]


def test_confirmed_detector_only_returns_approved_entities() -> None:
    detector = ConfirmedEntityDetector(
        [
            Entity("Nguyễn Văn A", "PER"),
            Entity("Hà Nội", "LOC"),
            Entity("Không có trong trang", "LOC"),
        ]
    )

    assert detector.extract("Ông Nguyễn Văn A ở Hà Nội.", {"PER", "LOC"}) == [
        Entity("Nguyễn Văn A", "PER"),
        Entity("Hà Nội", "LOC"),
    ]
