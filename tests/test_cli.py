from pdf_entity_highlighter.cli import build_parser, parse_hex_color


def test_parse_hex_color() -> None:
    assert parse_hex_color("#ff8000") == (1.0, 128 / 255, 0.0)
    assert parse_hex_color("00ff00") == (0.0, 1.0, 0.0)


def test_cli_defaults_to_strict_validation() -> None:
    args = build_parser().parse_args(["input.pdf", "output.pdf"])

    assert args.strict is True
    assert args.ocr == "auto"
    assert args.ocr_language == "vie"


def test_cli_can_disable_strict_validation() -> None:
    args = build_parser().parse_args(["input.pdf", "output.pdf", "--no-strict"])

    assert args.strict is False


def test_cli_can_disable_ocr() -> None:
    args = build_parser().parse_args(["input.pdf", "output.pdf", "--ocr", "never"])

    assert args.ocr == "never"
