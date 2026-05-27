from __future__ import annotations

from pathlib import Path


def resolve_output_paths(input_files: list[Path], output_target: Path) -> dict[Path, Path]:
    if not input_files:
        raise ValueError("Select at least one PDF file.")

    if len(input_files) > 1 and output_target.suffix.lower() == ".pdf":
        raise ValueError("Choose an output folder when processing multiple PDF files.")

    if len(input_files) == 1 and output_target.suffix.lower() == ".pdf":
        return {input_files[0]: output_target}

    output_dir = output_target
    output_paths: dict[Path, Path] = {}
    reserved: set[Path] = set()
    for input_file in input_files:
        output_path = unique_output_path(
            output_dir,
            f"{input_file.stem}-highlighted.pdf",
            reserved=reserved,
        )
        output_paths[input_file] = output_path
        reserved.add(output_path)
    return output_paths


def unique_output_path(output_dir: Path, filename: str, reserved: set[Path] | None = None) -> Path:
    reserved = reserved or set()
    candidate = output_dir / filename
    if not candidate.exists() and candidate not in reserved:
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    index = 2
    while True:
        next_candidate = output_dir / f"{stem}-{index}{suffix}"
        if not next_candidate.exists() and next_candidate not in reserved:
            return next_candidate
        index += 1
