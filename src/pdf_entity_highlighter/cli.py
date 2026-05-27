from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pdf_entity_highlighter.highlighter import DEFAULT_COLORS, highlight_pdf
from pdf_entity_highlighter.ner import UndertheseaEntityDetector


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    input_path = Path(args.input_pdf).expanduser().resolve()
    output_path = Path(args.output_pdf).expanduser().resolve()

    if not input_path.exists():
        parser.error(f"Input PDF not found: {input_path}")

    if input_path == output_path:
        parser.error("Output PDF must be different from input PDF.")

    colors = DEFAULT_COLORS.copy()
    try:
        colors.update(parse_color_overrides(args.color))
    except ValueError as exc:
        parser.error(str(exc))

    try:
        detector = UndertheseaEntityDetector(min_length=args.min_length)
    except ImportError as exc:
        print(str(exc), file=sys.stderr)
        print('Install the Vietnamese NER dependency with: python -m pip install -e ".[vi]"', file=sys.stderr)
        return 2

    result = highlight_pdf(
        input_path=input_path,
        output_path=output_path,
        detector=detector,
        labels=set(args.labels),
        colors=colors,
        opacity=args.opacity,
    )

    if args.report:
        report_path = Path(args.report).expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Saved highlighted PDF: {output_path}")
    print(
        "Summary: "
        f"{result.total_highlights} highlight(s), "
        f"{result.total_entities} unique entity mention(s), "
        f"{result.pages_processed} page(s) processed."
    )

    if result.pages_without_text:
        pages = ", ".join(str(page + 1) for page in result.pages_without_text)
        print(f"Warning: no extractable text on page(s): {pages}", file=sys.stderr)

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf-entity-highlight",
        description="Automatically highlight named entities in a searchable Vietnamese PDF.",
    )
    parser.add_argument("input_pdf", help="Path to the source PDF.")
    parser.add_argument("output_pdf", help="Path to the highlighted output PDF.")
    parser.add_argument(
        "--labels",
        nargs="+",
        default=["PER", "LOC"],
        help="NER labels to highlight. Default: PER LOC.",
    )
    parser.add_argument(
        "--color",
        action="append",
        default=[],
        metavar="LABEL=#RRGGBB",
        help="Override highlight color for a label. Can be passed multiple times.",
    )
    parser.add_argument(
        "--opacity",
        type=float,
        default=0.35,
        help="Highlight opacity from 0.0 to 1.0. Default: 0.35.",
    )
    parser.add_argument(
        "--min-length",
        type=int,
        default=2,
        help="Minimum entity text length to keep. Default: 2.",
    )
    parser.add_argument("--report", help="Optional path for a JSON summary report.")
    return parser


def parse_color_overrides(values: list[str]) -> dict[str, tuple[float, float, float]]:
    overrides: dict[str, tuple[float, float, float]] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"Invalid color override {value!r}; expected LABEL=#RRGGBB.")
        label, color = value.split("=", 1)
        label = label.strip().upper()
        if not label:
            raise ValueError(f"Invalid color override {value!r}; label is empty.")
        overrides[label] = parse_hex_color(color.strip())
    return overrides


def parse_hex_color(value: str) -> tuple[float, float, float]:
    if value.startswith("#"):
        value = value[1:]
    if len(value) != 6:
        raise ValueError("Colors must use #RRGGBB format.")
    try:
        red = int(value[0:2], 16)
        green = int(value[2:4], 16)
        blue = int(value[4:6], 16)
    except ValueError as exc:
        raise ValueError("Colors must use #RRGGBB format.") from exc
    return red / 255, green / 255, blue / 255
