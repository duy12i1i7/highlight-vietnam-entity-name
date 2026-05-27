from pathlib import Path

import pytest

from pdf_entity_highlighter.batch import resolve_output_paths, unique_output_path


def test_single_file_can_use_exact_output_pdf() -> None:
    source = Path("/tmp/source.pdf")
    output = Path("/tmp/result.pdf")

    assert resolve_output_paths([source], output) == {source: output}


def test_single_file_can_use_output_folder() -> None:
    source = Path("/tmp/source.pdf")
    output_dir = Path("/tmp/out")

    assert resolve_output_paths([source], output_dir) == {
        source: Path("/tmp/out/source-highlighted.pdf")
    }


def test_multiple_files_require_output_folder() -> None:
    with pytest.raises(ValueError):
        resolve_output_paths([Path("/tmp/a.pdf"), Path("/tmp/b.pdf")], Path("/tmp/result.pdf"))


def test_unique_output_path_adds_suffix(tmp_path: Path) -> None:
    existing = tmp_path / "a-highlighted.pdf"
    existing.write_text("already exists", encoding="utf-8")

    assert unique_output_path(tmp_path, "a-highlighted.pdf") == tmp_path / "a-highlighted-2.pdf"


def test_multiple_files_with_same_name_get_unique_outputs() -> None:
    first = Path("/tmp/one/a.pdf")
    second = Path("/tmp/two/a.pdf")

    assert resolve_output_paths([first, second], Path("/tmp/out")) == {
        first: Path("/tmp/out/a-highlighted.pdf"),
        second: Path("/tmp/out/a-highlighted-2.pdf"),
    }
