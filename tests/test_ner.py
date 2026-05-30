import os
from pathlib import Path

from pdf_entity_highlighter.ner import (
    Entity,
    bundled_java_home,
    clean_ner_text,
    entities_from_tagged_tokens,
    entities_from_vncorenlp_annotation,
    prepare_default_vncorenlp_model,
)


def test_entities_from_bio_tags() -> None:
    tagged_tokens = [
        ("Ông", "Nc", "B-NP", "O"),
        ("Nguyễn", "Np", "B-NP", "B-PER"),
        ("Văn", "Np", "B-NP", "I-PER"),
        ("A", "Np", "B-NP", "I-PER"),
        ("ở", "E", "B-PP", "O"),
        ("Hà Nội", "Np", "B-NP", "B-LOC"),
        (".", "CH", "O", "O"),
    ]

    assert entities_from_tagged_tokens(tagged_tokens, {"PER", "LOC"}) == [
        Entity("Nguyễn Văn A", "PER"),
        Entity("Hà Nội", "LOC"),
    ]


def test_entities_are_filtered_by_label() -> None:
    tagged_tokens = [
        ("Nguyễn", "Np", "B-NP", "B-PER"),
        ("Văn", "Np", "B-NP", "I-PER"),
        ("A", "Np", "B-NP", "I-PER"),
        ("Hà Nội", "Np", "B-NP", "B-LOC"),
    ]

    assert entities_from_tagged_tokens(tagged_tokens, {"LOC"}) == [
        Entity("Hà Nội", "LOC"),
    ]


def test_entities_from_vncorenlp_annotation() -> None:
    annotation = {
        0: [
            {"wordForm": "Ông", "nerLabel": "O"},
            {"wordForm": "Nguyễn_Văn_A", "nerLabel": "B-PER"},
            {"wordForm": "ở", "nerLabel": "O"},
            {"wordForm": "Hà_Nội", "nerLabel": "B-LOC"},
        ]
    }

    assert entities_from_vncorenlp_annotation(annotation, {"PER", "LOC"}) == [
        Entity("Nguyễn Văn A", "PER"),
        Entity("Hà Nội", "LOC"),
    ]


def test_clean_ner_text_removes_low_signal_ocr_noise() -> None:
    text = "Nguyễn Văn A ở Hà Nội\n@@@ === ---\nCỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM"

    assert clean_ner_text(text) == "Nguyễn Văn A ở Hà Nội\nCỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM"


def test_prepare_default_vncorenlp_model_copies_bundled_model(tmp_path: Path, monkeypatch) -> None:
    model_dir = tmp_path / "vncorenlp"
    files = [
        "VnCoreNLP-1.2.jar",
        "models/wordsegmenter/vi-vocab",
        "models/wordsegmenter/wordsegmenter.rdr",
        "models/postagger/vi-tagger",
        "models/ner/vi-500brownclusters.xz",
        "models/ner/vi-ner.xz",
        "models/ner/vi-pretrainedembeddings.xz",
    ]
    for relative_path in files:
        path = model_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative_path, encoding="utf-8")
    monkeypatch.setattr("sys._MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    prepared_dir = prepare_default_vncorenlp_model()

    assert prepared_dir == tmp_path / "home" / ".pdf-entity-highlighter" / "vncorenlp"
    assert (prepared_dir / "models" / "wordsegmenter" / "wordsegmenter.rdr").exists()


def test_bundled_java_home_detects_packaged_runtime(tmp_path: Path, monkeypatch) -> None:
    executable = "java.exe" if os.name == "nt" else "java"
    java_bin = tmp_path / "java-runtime" / "bin"
    java_bin.mkdir(parents=True)
    (java_bin / executable).write_text("java", encoding="utf-8")
    monkeypatch.setattr("sys._MEIPASS", str(tmp_path), raising=False)

    assert bundled_java_home() == tmp_path / "java-runtime"
