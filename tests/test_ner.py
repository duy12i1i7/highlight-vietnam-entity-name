from pdf_entity_highlighter.ner import Entity, entities_from_tagged_tokens


def test_entities_from_underthesea_bio_tags() -> None:
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
