import hashlib
import os
from pathlib import Path
from uuid import UUID

import pytest
from cryptography.fernet import Fernet, InvalidToken

from inspire_flow_backend.core.config import Settings
from inspire_flow_backend.core.context_security import (
    ContextCipher,
    ContextStorageUnavailableError,
    redact_credentials,
    redact_json_credentials,
)

FIXED_KEY = b"79zUG7lNhJ1eTm2N-oWpgStPtMzGxJTgQ3wp8bVh3Y0="
OTHER_KEY = b"RXKAvr9YXRAYHZ__SFUYLiVYsSv_Kw3cLfK-SgMhYTU="
REDACTED = "[REDACTED_CREDENTIAL]"


def make_settings(tmp_path: Path, *, key: str | None = None) -> Settings:
    return Settings(
        _env_file=None,
        context_encryption_key=key,
        context_encryption_key_file=tmp_path / "context.key",
    )


def test_context_cipher_round_trips_text_and_json(tmp_path: Path) -> None:
    cipher = ContextCipher.from_settings(make_settings(tmp_path, key=FIXED_KEY.decode()))

    encrypted_text = cipher.encrypt_text("创作偏好：科技视频")
    encrypted_json = cipher.encrypt_json(
        {"type": "message", "role": "user", "content": [{"text": "一个新想法"}]}
    )

    assert "创作偏好" not in encrypted_text
    assert "一个新想法" not in encrypted_json
    assert cipher.decrypt_text(encrypted_text) == "创作偏好：科技视频"
    assert cipher.decrypt_json(encrypted_json) == {
        "type": "message",
        "role": "user",
        "content": [{"text": "一个新想法"}],
    }


def test_key_file_is_created_once_with_owner_only_permissions(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)

    first = ContextCipher.from_settings(settings)
    key_path = settings.context_encryption_key_file
    original_key = key_path.read_bytes()
    second = ContextCipher.from_settings(settings)

    assert len(original_key) == 44
    assert os.stat(key_path).st_mode & 0o777 == 0o600
    assert second.decrypt_text(first.encrypt_text("kept")) == "kept"
    assert key_path.read_bytes() == original_key


def test_blank_environment_key_falls_back_to_key_file(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, key="")

    cipher = ContextCipher.from_settings(settings)

    assert settings.context_encryption_key is None
    assert settings.context_encryption_key_file.exists()
    assert cipher.decrypt_text(cipher.encrypt_text("local fallback")) == "local fallback"


def test_environment_key_takes_precedence_over_key_file(tmp_path: Path) -> None:
    key_path = tmp_path / "context.key"
    key_path.write_bytes(OTHER_KEY)
    settings = make_settings(tmp_path, key=FIXED_KEY.decode())

    cipher = ContextCipher.from_settings(settings)
    token = cipher.encrypt_text("environment key wins")

    assert Fernet(FIXED_KEY).decrypt(token.encode()).decode() == "environment key wins"
    with pytest.raises(InvalidToken):
        Fernet(OTHER_KEY).decrypt(token.encode())


def test_invalid_key_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ContextStorageUnavailableError):
        ContextCipher.from_settings(make_settings(tmp_path, key="not-a-fernet-key"))


def test_fingerprint_is_stable_but_not_plain_sha256(tmp_path: Path) -> None:
    cipher = ContextCipher.from_settings(make_settings(tmp_path, key=FIXED_KEY.decode()))
    user_id = UUID("01234567-89ab-cdef-0123-456789abcdef")

    first = cipher.fingerprint(user_id, "creative_focus", "  科技 视频  ")
    second = cipher.fingerprint(user_id, "creative_focus", "科技 视频")
    plain = hashlib.sha256(f"{user_id}:creative_focus:科技 视频".encode()).hexdigest()

    assert first == second
    assert len(first) == 64
    assert first != plain


def test_redactor_removes_api_key_bearer_jwt_password_and_private_key() -> None:
    private_key_label = "PRIVATE " + "KEY"
    private_key = (
        f"-----BEGIN {private_key_label}-----\n"
        "YWJjZGVmZ2hpamtsbW5vcA==\n"
        f"-----END {private_key_label}-----"
    )
    source = (
        "api_key=test-secret-placeholder\n"
        "Authorization: Bearer opaque-secret-value\n"
        "jwt=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.signaturevalue\n"
        "password: correct horse battery staple\n"
        f"{private_key}"
    )

    result = redact_credentials(source)

    assert result.was_redacted is True
    assert result.value.count(REDACTED) >= 5
    for secret in (
        "test-secret-placeholder",
        "opaque-secret-value",
        "eyJhbGciOiJIUzI1NiJ9",
        "correct horse battery staple",
        "YWJjZGVmZ2hpamtsbW5vcA==",
    ):
        assert secret not in result.value


def test_recursive_redaction_preserves_non_secret_sdk_item_shape() -> None:
    item = {
        "type": "message",
        "role": "user",
        "content": [
            {"type": "input_text", "text": "用 token=top-secret-value 调试"},
            {"type": "input_image", "image_url": "https://example.test/demo.png"},
        ],
        "metadata": {"safe": True, "attempt": 1},
    }

    redacted = redact_json_credentials(item)

    assert redacted == {
        "type": "message",
        "role": "user",
        "content": [
            {"type": "input_text", "text": f"用 token={REDACTED} 调试"},
            {"type": "input_image", "image_url": "https://example.test/demo.png"},
        ],
        "metadata": {"safe": True, "attempt": 1},
    }
