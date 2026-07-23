import unicodedata

MIN_NICKNAME_LENGTH = 2
MAX_NICKNAME_LENGTH = 50


def clean_nickname(value: str) -> str:
    cleaned = value.strip()
    normalized = unicodedata.normalize("NFKC", cleaned)
    if not MIN_NICKNAME_LENGTH <= len(normalized) <= MAX_NICKNAME_LENGTH:
        raise ValueError("Nickname must contain 2 to 50 characters")
    if any(unicodedata.category(character).startswith("C") for character in cleaned):
        raise ValueError("Nickname must not contain control characters")
    return cleaned


def nickname_key(value: str) -> str:
    return unicodedata.normalize("NFKC", clean_nickname(value)).casefold()
