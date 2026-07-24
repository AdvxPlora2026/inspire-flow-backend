# Security and Persistence Research

Accessed: 2026-07-23

## Password hashing

- FastAPI's current OAuth2 password example uses `pwdlib` and
  `PasswordHash.recommended()`, with the Argon2 optional dependency:
  <https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/>
- OWASP recommends Argon2id for password storage when available:
  <https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html>

Decision: use `pwdlib[argon2]` and `PasswordHash.recommended()`. Store only the
encoded Argon2id hash.

## Password input policy

- OWASP's authentication guidance treats passwords shorter than 15 characters
  as weak when MFA is absent, recommends supporting maximum lengths of at
  least 64 characters, allows Unicode and whitespace, and advises against
  composition rules:
  <https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html>

Decision: require 15 through 128 characters during registration, permit
Unicode and whitespace, and impose no character-class rule. Login accepts a
non-empty password through 128 characters so an incorrect short value still
gets the generic authentication failure.

## Opaque session token

- Python documents `secrets` as the preferred standard-library source of
  cryptographically strong random values for authentication and documents
  `token_urlsafe(nbytes)` as returning a URL-safe token with `nbytes` random
  bytes:
  <https://docs.python.org/3/library/secrets.html>
- OWASP requires server-side session invalidation when a user logs out:
  <https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html>

Decision: generate `secrets.token_urlsafe(32)`, return the raw token once,
persist only its SHA-256 digest, and delete the presented session row on
logout. SHA-256 is used as a lookup digest for a high-entropy random token, not
as a password hash.

## SQLite, UUIDs, and migrations

- SQLAlchemy documents the SQLite dialect and its file URL behavior:
  <https://docs.sqlalchemy.org/en/20/dialects/sqlite.html>
- SQLAlchemy's backend-agnostic `Uuid` type accepts Python UUID objects and can
  store character-based UUID values when native UUID support is disabled:
  <https://docs.sqlalchemy.org/en/20/core/type_basics.html#sqlalchemy.types.Uuid>
- Alembic documents its migration environment and autogeneration workflow:
  <https://alembic.sqlalchemy.org/en/latest/tutorial.html>
  <https://alembic.sqlalchemy.org/en/latest/autogenerate.html>

Decision: use synchronous SQLAlchemy 2.0 with the standard-library SQLite
driver, `Uuid(as_uuid=True, native_uuid=False)`, and one hand-reviewed Alembic
revision. Application startup does not call `create_all()`.

## Inferences

- A server-side opaque session is simpler than a signed JWT for immediate
  logout in a single-node SQLite service because revocation is a row deletion
  and no token denylist is needed.
- Storing only the token digest limits credential disclosure if the SQLite
  file is read. It does not replace file permissions, TLS, log hygiene, or
  deployment hardening.
- A dummy Argon2 verification on missing-user login narrows the obvious timing
  difference between unknown nicknames and incorrect passwords. It is not a
  claim of strict constant-time behavior.
