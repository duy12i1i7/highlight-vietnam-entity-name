from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pdf_entity_highlighter.highlighter import DEFAULT_COLORS, highlight_pdf
from pdf_entity_highlighter.ner import UndertheseaEntityDetector, VnCoreNlpEntityDetector
from pdf_entity_highlighter.validation import (
    ConfirmedEntityDetector,
    StrictEntityValidator,
    load_confirmed_entities,
)


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
        if args.confirmed_only:
            confirmed_entities = load_confirmed_entities(args.confirmed_only)
            if not confirmed_entities:
                parser.error("Confirmed entity list is empty.")
            detector = ConfirmedEntityDetector(confirmed_entities)
            validator = None
        else:
            if args.engine == "vncorenlp":
                detector = VnCoreNlpEntityDetector(
                    model_dir=args.vncorenlp_dir,
                    download=args.download_vncorenlp,
                    min_length=args.min_length,
                    max_heap_size=args.vncorenlp_heap,
                )
            else:
                detector = UndertheseaEntityDetector(min_length=args.min_length)
            validator = StrictEntityValidator() if args.strict else None
    except ImportError as exc:
        print(str(exc), file=sys.stderr)
        print('Install dependencies with: python -m pip install -e .', file=sys.stderr)
        print('For the optional Underthesea engine, use: python -m pip install -e ".[vi]"', file=sys.stderr)
        return 2
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))

    result = highlight_pdf(
        input_path=input_path,
        output_path=output_path,
        detector=detector,
        labels=set(args.labels),
        colors=colors,
        opacity=args.opacity,
        validator=validator,
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
    if result.skipped:
        print(f"Skipped by validation: {len(result.skipped)} candidate(s).")

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
    parser.add_argument(
        "--engine",
        choices=["underthesea", "vncorenlp"],
        default="vncorenlp",
        help="NER engine to use before validation. Default: vncorenlp.",
    )
    parser.add_argument(
        "--vncorenlp-dir",
        default=None,
        help=(
            "VnCoreNLP model directory. Default: bundled model in the desktop app, "
            "or ~/.pdf-entity-highlighter/vncorenlp when running from source."
        ),
    )
    parser.add_argument(
        "--download-vncorenlp",
        action="store_true",
        help="Download VnCoreNLP jar and model files into --vncorenlp-dir before running.",
    )
    parser.add_argument(
        "--vncorenlp-heap",
        default="-Xmx2g",
        help="Java heap setting for VnCoreNLP. Default: -Xmx2g.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=True,
        help="Use conservative validation rules to reduce false positives. Enabled by default.",
    )
    parser.add_argument(
        "--no-strict",
        action="store_false",
        dest="strict",
        help="Disable strict validation.",
    )
    parser.add_argument(
        "--confirmed-only",
        metavar="FILE",
        help=(
            "Bypass NER and highlight only approved entities from a UTF-8 text file. "
            "Each line can be TEXT or LABEL,TEXT. This is the only mode suitable when false positives are unacceptable."
        ),
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
