from inspire_flow_backend.core.security import (
    digest_session_token,
    generate_session_token,
    hash_password,
    verify_password,
)


def test_password_hash_is_non_plaintext_and_verifiable() -> None:
    password = "correct horse battery staple"

    encoded = hash_password(password)

    assert encoded != password
    assert encoded.startswith("$argon2")
    assert verify_password(password, encoded) is True
    assert verify_password("incorrect password value", encoded) is False


def test_session_tokens_are_random_and_only_digest_deterministically() -> None:
    first = generate_session_token()
    second = generate_session_token()

    assert first != second
    assert len(first) >= 43
    assert digest_session_token(first) == digest_session_token(first)
    assert digest_session_token(first) != digest_session_token(second)
    assert len(digest_session_token(first)) == 64
