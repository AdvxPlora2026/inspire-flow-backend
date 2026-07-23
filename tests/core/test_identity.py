import pytest

from inspire_flow_backend.core.identity import clean_nickname, nickname_key


def test_clean_nickname_trims_without_rewriting_display_value() -> None:
    assert clean_nickname("  Ａria  ") == "Ａria"


def test_nickname_key_applies_nfkc_and_casefold() -> None:
    assert nickname_key("ＡRIA") == nickname_key("aria")


@pytest.mark.parametrize("value", ["a", "x" * 51, "valid\nname", "name\u0000"])
def test_clean_nickname_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        clean_nickname(value)
