import base64
import hashlib
import hmac
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken

from inspire_flow_backend.core.config import Settings
from inspire_flow_backend.core.errors import ContextStorageUnavailableError

REDACTED_CREDENTIAL = "[REDACTED_CREDENTIAL]"

_PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE "
    r"KEY-----.*?-----END (?:[A-Z0-9 ]+ )?PRIVATE "
    r"KEY-----",
    flags=re.DOTALL,
)
_BEARER_PATTERN = re.compile(
    r"(?i)(\b(?:authorization\s*:\s*)?bearer\s+)[^\s,;]+",
)
_JWT_PATTERN = re.compile(
    r"\b[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b",
)
_SK_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b", flags=re.IGNORECASE)
_TOKEN_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret)"
    r"\b\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[A-Za-z0-9._~+/=-]{8,})",
)
_PASSWORD_ASSIGNMENT_PATTERN = re.compile(
    r"(?im)(\b(?:password|passwd|pwd)\b\s*[:=]\s*)[^\r\n,;&]+",
)


@dataclass(frozen=True, slots=True)
class RedactionResult:
    value: str
    was_redacted: bool


class ContextCipher:
    def __init__(self, key: bytes) -> None:
        try:
            decoded_key = base64.urlsafe_b64decode(key)
            self._fernet = Fernet(key)
        except (TypeError, ValueError) as exc:
            raise ContextStorageUnavailableError from exc
        if len(decoded_key) != 32:
            raise ContextStorageUnavailableError
        self._fingerprint_key = hmac.digest(
            decoded_key,
            b"inspire-flow-context-fingerprint-v1",
            "sha256",
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "ContextCipher":
        try:
            configured_key = settings.context_encryption_key
            if configured_key is not None:
                key = (
                    configured_key.get_secret_value()
                    .strip()
                    .encode(
                        "ascii",
                        errors="strict",
                    )
                )
            else:
                key = _load_or_create_key(settings.context_encryption_key_file)
            return cls(key)
        except (UnicodeError, ContextStorageUnavailableError) as exc:
            raise ContextStorageUnavailableError from exc

    def encrypt_text(self, value: str) -> str:
        try:
            return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")
        except (TypeError, ValueError, UnicodeError) as exc:
            raise ContextStorageUnavailableError from exc

    def decrypt_text(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, TypeError, ValueError, UnicodeError) as exc:
            raise ContextStorageUnavailableError from exc

    def encrypt_json(self, value: object) -> str:
        try:
            serialized = json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError) as exc:
            raise ContextStorageUnavailableError from exc
        return self.encrypt_text(serialized)

    def decrypt_json(self, token: str) -> object:
        try:
            return json.loads(self.decrypt_text(token))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ContextStorageUnavailableError from exc

    def fingerprint(self, user_id: UUID, category: str, content: str) -> str:
        normalized_content = " ".join(content.split()).casefold()
        message = "\x1f".join((str(user_id), category.strip().casefold(), normalized_content))
        return hmac.new(
            self._fingerprint_key,
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()


def redact_credentials(value: str) -> RedactionResult:
    redacted = value
    patterns: tuple[tuple[re.Pattern[str], str], ...] = (
        (_PRIVATE_KEY_PATTERN, REDACTED_CREDENTIAL),
        (_BEARER_PATTERN, rf"\1{REDACTED_CREDENTIAL}"),
        (_JWT_PATTERN, REDACTED_CREDENTIAL),
        (_SK_KEY_PATTERN, REDACTED_CREDENTIAL),
        (_TOKEN_ASSIGNMENT_PATTERN, rf"\1{REDACTED_CREDENTIAL}"),
        (_PASSWORD_ASSIGNMENT_PATTERN, rf"\1{REDACTED_CREDENTIAL}"),
    )
    for pattern, replacement in patterns:
        redacted = pattern.sub(replacement, redacted)
    return RedactionResult(value=redacted, was_redacted=redacted != value)


def redact_json_credentials(value: object) -> object:
    if isinstance(value, str):
        return redact_credentials(value).value
    if isinstance(value, Mapping):
        return {key: redact_json_credentials(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_json_credentials(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_json_credentials(item) for item in value)
    return value


def _load_or_create_key(path: Path) -> bytes:
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            file_descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return path.read_bytes().strip()

        key = Fernet.generate_key()
        try:
            with os.fdopen(file_descriptor, "wb") as key_file:
                key_file.write(key)
                key_file.flush()
                os.fsync(key_file.fileno())
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return key
    except (OSError, ValueError) as exc:
        raise ContextStorageUnavailableError from exc
