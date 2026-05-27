from pdf_entity_highlighter.cli import parse_hex_color


def test_parse_hex_color() -> None:
    assert parse_hex_color("#ff8000") == (1.0, 128 / 255, 0.0)
    assert parse_hex_color("00ff00") == (0.0, 1.0, 0.0)
