# RESTful User Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a SQLite-backed REST user system with registration, opaque bearer sessions, self-profile management, logout, migrations, tests, and a natural Chinese integration handoff.

**Architecture:** Keep HTTP wiring in FastAPI routes, validation in Pydantic schemas, transactions in services, SQLAlchemy queries in repositories, and persistence entities in models. Store Argon2id password hashes and SHA-256 bearer-token digests, use Alembic for schema lifecycle, and expose one stable error envelope.

**Tech Stack:** Python 3.13, uv, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic, SQLite, pwdlib with Argon2, pytest, Ruff

> **Trellis execution note:** This repository stores the plan in the active task
> directory instead of `docs/superpowers/plans`. After the user approves the
> final planning summary, run `task.py start`, load `trellis-before-dev`, and
> execute inline because this Codex session is configured for inline work.

---

## File Map

### Files to modify

- `.gitignore`: exclude SQLite database and sidecar files.
- `.env.example`: document safe database and session-lifetime defaults.
- `README.md`: add migration and authenticated API entry points.
- `pyproject.toml`: declare SQLAlchemy, Alembic, and Argon2 password support
  through `uv add`.
- `uv.lock`: regenerate only through uv.
- `src/inspire_flow_backend/core/config.py`: add database URL and positive
  session-lifetime settings.
- `src/inspire_flow_backend/main.py`: register application error handlers.
- `src/inspire_flow_backend/api/router.py`: compose user and session routers.
- `src/inspire_flow_backend/data/models/__init__.py`: import model classes for
  Alembic metadata discovery.
- `src/inspire_flow_backend/data/repositories/__init__.py`: retain an
  import-side-effect-free package.
- `tests/test_config.py`: verify new environment settings.

### Files to create

- `alembic.ini`: Alembic command configuration.
- `migrations/env.py`: bind settings and SQLAlchemy metadata into Alembic.
- `migrations/script.py.mako`: revision template.
- `migrations/versions/20260723_0001_create_users_and_auth_sessions.py`:
  initial reversible schema.
- `src/inspire_flow_backend/core/errors.py`: domain errors and HTTP handlers.
- `src/inspire_flow_backend/core/identity.py`: nickname cleanup and lookup-key
  normalization.
- `src/inspire_flow_backend/core/security.py`: Argon2id and opaque-token
  operations.
- `src/inspire_flow_backend/core/time.py`: timezone-aware UTC clock.
- `src/inspire_flow_backend/data/base.py`: declarative metadata base.
- `src/inspire_flow_backend/data/database.py`: engine, session factory, and
  foreign-key configuration.
- `src/inspire_flow_backend/data/types.py`: SQLite-aware UTC datetime type.
- `src/inspire_flow_backend/data/models/user.py`: internal user entity.
- `src/inspire_flow_backend/data/models/auth_session.py`: internal session
  entity.
- `src/inspire_flow_backend/data/repositories/users.py`: user queries and
  mutations without commits.
- `src/inspire_flow_backend/data/repositories/sessions.py`: session queries
  and mutations without commits.
- `src/inspire_flow_backend/schemas/errors.py`: stable error response models.
- `src/inspire_flow_backend/schemas/users.py`: registration, patch, and public
  user contracts.
- `src/inspire_flow_backend/schemas/sessions.py`: login and session contracts.
- `src/inspire_flow_backend/services/users.py`: registration and profile use
  cases.
- `src/inspire_flow_backend/services/sessions.py`: login, authentication, and
  logout use cases.
- `src/inspire_flow_backend/api/dependencies.py`: bearer authentication
  dependency.
- `src/inspire_flow_backend/api/routes/users.py`: registration and current-user
  endpoints.
- `src/inspire_flow_backend/api/routes/sessions.py`: login and logout
  endpoints.
- `tests/core/test_identity.py`: Unicode nickname behavior.
- `tests/core/test_security.py`: password and token behavior.
- `tests/data/test_types.py`: UTC conversion behavior.
- `tests/data/test_database.py`: SQLite connection configuration.
- `tests/data/test_migrations.py`: Alembic upgrade and downgrade smoke test.
- `tests/api/conftest.py`: isolated temporary database and API helpers.
- `tests/api/test_users.py`: registration and profile contracts.
- `tests/api/test_sessions.py`: login, bearer authentication, and logout
  contracts.
- `HANDOFF_USERSYS.MD`: Chinese integration handoff.

## Contract Names Shared Across Tasks

Use these names exactly so later tasks do not invent parallel contracts:

```python
# core
clean_nickname(value: str) -> str
nickname_key(value: str) -> str
utc_now() -> datetime
hash_password(password: str) -> str
verify_password(password: str, password_hash: str) -> bool
generate_session_token() -> str
digest_session_token(token: str) -> str

# services
register_user(db: Session, payload: UserCreate) -> User
update_user(db: Session, user: User, payload: UserUpdate) -> User
create_session(
    db: Session,
    payload: SessionCreate,
    ttl_hours: int,
) -> CreatedSession
resolve_session(db: Session, token: str) -> AuthenticatedSession
revoke_session(db: Session, auth_session: AuthSession) -> None

# dependency
get_current_session(...) -> AuthenticatedSession
```

`CreatedSession` contains the raw `access_token`, `expires_at`, and `user`.
`AuthenticatedSession` contains the persisted `session` and `user`.

### Task 1: Lock dependencies, settings, and ignored local state

**Files:**

- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `src/inspire_flow_backend/core/config.py`
- Modify: `tests/test_config.py`
- Modify: `.env.example`
- Modify: `.gitignore`

- [ ] **Step 1: Extend the settings test and confirm it fails**

Add these environment values to the existing environment-parsing test and
assert their types:

```python
monkeypatch.setenv("APP_DATABASE_URL", "sqlite:///./test.db")
monkeypatch.setenv("APP_SESSION_TTL_HOURS", "12")

settings = get_settings()

assert settings.database_url == "sqlite:///./test.db"
assert settings.session_ttl_hours == 12
```

Add a separate invalid-value test:

```python
def test_session_ttl_must_be_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_SESSION_TTL_HOURS", "0")
    get_settings.cache_clear()

    with pytest.raises(ValidationError):
        get_settings()

    get_settings.cache_clear()
```

Run:

```bash
uv run pytest tests/test_config.py -W error -q
```

Expected: failure because `Settings` has no `database_url` or
`session_ttl_hours`.

- [ ] **Step 2: Add runtime dependencies through uv**

Run:

```bash
uv add "sqlalchemy>=2.0,<3" "alembic>=1.18,<2" "pwdlib[argon2]>=0.3,<1"
```

Expected: `pyproject.toml` and `uv.lock` change; uv resolves successfully.

- [ ] **Step 3: Add the settings fields**

Change `core/config.py` imports and class body to include:

```python
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="APP_",
        extra="ignore",
    )

    name: str = "Inspire Flow Backend"
    environment: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./inspire_flow.db"
    session_ttl_hours: int = Field(default=24, gt=0)
```

- [ ] **Step 4: Document and ignore local database state**

Append safe settings to `.env.example`:

```dotenv
APP_DATABASE_URL=sqlite:///./inspire_flow.db
APP_SESSION_TTL_HOURS=24
```

Add these patterns to `.gitignore`:

```gitignore
*.db
*.db-journal
*.db-shm
*.db-wal
*.sqlite
*.sqlite3
```

Verify `.env.example` is still trackable:

```bash
git check-ignore -v .env.example
```

Expected: no output and exit status 1.

- [ ] **Step 5: Run the focused test**

Run:

```bash
uv run pytest tests/test_config.py -W error -q
```

Expected: all configuration tests pass.

- [ ] **Step 6: Commit the dependency/configuration slice**

Run:

```bash
git add pyproject.toml uv.lock src/inspire_flow_backend/core/config.py tests/test_config.py .env.example .gitignore
git commit -m "build: add authentication persistence dependencies"
```

Expected: one commit containing only dependency, settings, and ignore changes.

### Task 2: Establish database types and ORM entities

**Files:**

- Create: `src/inspire_flow_backend/core/time.py`
- Create: `src/inspire_flow_backend/data/base.py`
- Create: `src/inspire_flow_backend/data/types.py`
- Create: `src/inspire_flow_backend/data/database.py`
- Create: `src/inspire_flow_backend/data/models/user.py`
- Create: `src/inspire_flow_backend/data/models/auth_session.py`
- Modify: `src/inspire_flow_backend/data/models/__init__.py`
- Create: `tests/data/test_types.py`
- Create: `tests/data/test_database.py`

- [ ] **Step 1: Write UTC type tests and confirm they fail**

Create `tests/data/test_types.py`:

```python
from datetime import UTC, datetime, timedelta, timezone

import pytest

from inspire_flow_backend.data.types import UTCDateTime


def test_utc_datetime_normalizes_to_naive_utc_for_sqlite() -> None:
    column_type = UTCDateTime()
    source = datetime(2026, 7, 23, 18, 30, tzinfo=timezone(timedelta(hours=8)))

    stored = column_type.process_bind_param(source, None)

    assert stored == datetime(2026, 7, 23, 10, 30)
    assert stored.tzinfo is None


def test_utc_datetime_restores_aware_utc() -> None:
    column_type = UTCDateTime()

    restored = column_type.process_result_value(datetime(2026, 7, 23, 10, 30), None)

    assert restored == datetime(2026, 7, 23, 10, 30, tzinfo=UTC)


def test_utc_datetime_rejects_naive_input() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        UTCDateTime().process_bind_param(datetime(2026, 7, 23, 10, 30), None)
```

Run:

```bash
uv run pytest tests/data/test_types.py -W error -q
```

Expected: import failure because `data.types` does not exist.

- [ ] **Step 2: Implement the UTC clock and SQLAlchemy type**

Create `core/time.py`:

```python
from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)
```

Create `data/types.py`:

```python
from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime
    cache_ok = True

    def process_bind_param(
        self,
        value: datetime | None,
        dialect: Dialect,
    ) -> datetime | None:
        del dialect
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("UTCDateTime requires a timezone-aware datetime")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(
        self,
        value: datetime | None,
        dialect: Dialect,
    ) -> datetime | None:
        del dialect
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
```

- [ ] **Step 3: Create the declarative base and database session owner**

Create `data/base.py`:

```python
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
```

Create `data/database.py`:

```python
from collections.abc import Generator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from inspire_flow_backend.core.config import get_settings


def enable_sqlite_foreign_keys(engine: Engine) -> None:
    if engine.url.get_backend_name() != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def create_database_engine(database_url: str) -> Engine:
    connect_args: dict[str, bool] = {}
    if make_url(database_url).get_backend_name() == "sqlite":
        connect_args["check_same_thread"] = False
    database_engine = create_engine(database_url, connect_args=connect_args)
    enable_sqlite_foreign_keys(database_engine)
    return database_engine


engine = create_database_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db_session() -> Generator[Session]:
    with SessionLocal() as db:
        yield db
```

The DBAPI callback intentionally follows SQLAlchemy's dynamically typed event
signature. The repository does not enable Ruff's annotation rules, so no
suppression is required.

- [ ] **Step 4: Create the user model**

Create `data/models/user.py`:

```python
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.base import Base
from inspire_flow_backend.data.types import UTCDateTime

if TYPE_CHECKING:
    from inspire_flow_backend.data.models.auth_session import AuthSession


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        primary_key=True,
        default=uuid4,
    )
    nickname: Mapped[str] = mapped_column(String(50), nullable=False)
    nickname_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
    )
    avatar_url: Mapped[str | None] = mapped_column(String(2048))
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )
    sessions: Mapped[list["AuthSession"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
```

- [ ] **Step 5: Create the session model and metadata imports**

Create `data/models/auth_session.py`:

```python
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.base import Base
from inspire_flow_backend.data.types import UTCDateTime

if TYPE_CHECKING:
    from inspire_flow_backend.data.models.user import User


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (Index("ix_auth_sessions_user_id", "user_id"),)

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        primary_key=True,
        default=uuid4,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )
    user: Mapped["User"] = relationship(back_populates="sessions")
```

The final `data/models/__init__.py` must be:

```python
from inspire_flow_backend.data.models.auth_session import AuthSession
from inspire_flow_backend.data.models.user import User

__all__ = ["AuthSession", "User"]
```

The package imports both classes before mapper configuration while relationship
annotations remain forward references. Do not add a runtime model import at
the bottom of either model module.

- [ ] **Step 6: Run focused tests and a metadata smoke check**

Create `tests/data/test_database.py`:

```python
from pathlib import Path

from sqlalchemy import text

from inspire_flow_backend.data.database import create_database_engine


def test_enables_sqlite_foreign_keys(tmp_path: Path) -> None:
    engine = create_database_engine(
        f"sqlite:///{tmp_path / 'foreign-keys.db'}"
    )

    with engine.connect() as connection:
        enabled = connection.scalar(text("PRAGMA foreign_keys"))

    assert enabled == 1
    engine.dispose()
```

Run:

```bash
uv run pytest tests/data/test_types.py tests/data/test_database.py -W error -q
uv run python -c "from inspire_flow_backend.data.base import Base; import inspire_flow_backend.data.models; assert set(Base.metadata.tables) == {'users', 'auth_sessions'}"
```

Expected: UTC and foreign-key tests pass and both tables are registered.

### Task 3: Add a reversible initial Alembic migration

**Files:**

- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/script.py.mako`
- Create: `migrations/versions/20260723_0001_create_users_and_auth_sessions.py`
- Create: `tests/data/test_migrations.py`

- [ ] **Step 1: Write the migration smoke test and confirm it fails**

Create `tests/data/test_migrations.py`:

```python
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config


def test_migration_upgrades_and_downgrades_sqlite(tmp_path: Path) -> None:
    database_path = tmp_path / "migration.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")

    command.upgrade(config, "head")

    engine = sa.create_engine(f"sqlite:///{database_path}")
    inspector = sa.inspect(engine)
    assert set(inspector.get_table_names()) >= {
        "alembic_version",
        "users",
        "auth_sessions",
    }
    assert {column["name"] for column in inspector.get_columns("users")} == {
        "id",
        "nickname",
        "nickname_key",
        "avatar_url",
        "password_hash",
        "created_at",
        "updated_at",
    }
    assert {column["name"] for column in inspector.get_columns("auth_sessions")} == {
        "id",
        "user_id",
        "token_hash",
        "expires_at",
        "created_at",
    }
    assert {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("users")
    } == {"uq_users_nickname_key"}
    assert {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("auth_sessions")
    } == {"uq_auth_sessions_token_hash"}
    foreign_keys = inspector.get_foreign_keys("auth_sessions")
    assert len(foreign_keys) == 1
    assert foreign_keys[0]["constrained_columns"] == ["user_id"]
    assert foreign_keys[0]["referred_table"] == "users"
    assert foreign_keys[0]["options"]["ondelete"] == "CASCADE"
    assert {
        index["name"] for index in inspector.get_indexes("auth_sessions")
    } == {"ix_auth_sessions_user_id"}

    command.downgrade(config, "base")

    assert set(sa.inspect(engine).get_table_names()) == {"alembic_version"}
    engine.dispose()
```

Run:

```bash
uv run pytest tests/data/test_migrations.py -W error -q
```

Expected: failure because `alembic.ini` is absent.

- [ ] **Step 2: Add Alembic configuration and environment**

Create `alembic.ini`:

```ini
[alembic]
script_location = %(here)s/migrations
prepend_sys_path = .
path_separator = os
sqlalchemy.url =

[post_write_hooks]

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

Create `migrations/script.py.mako`:

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | Sequence[str] | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

Create `migrations/env.py` with this binding behavior:

```python
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from inspire_flow_backend.core.config import get_settings
from inspire_flow_backend.data.base import Base
from inspire_flow_backend.data.models import AuthSession, User

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

configured_url = config.get_main_option("sqlalchemy.url")
if not configured_url:
    config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata
assert {AuthSession.__tablename__, User.__tablename__} <= set(
    target_metadata.tables
)


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 3: Add the initial revision**

Create `migrations/versions/20260723_0001_create_users_and_auth_sessions.py`:

```python
"""create users and auth sessions

Revision ID: 20260723_0001
Revises:
Create Date: 2026-07-23 00:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260723_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("nickname", sa.String(length=50), nullable=False),
        sa.Column("nickname_key", sa.String(length=255), nullable=False),
        sa.Column("avatar_url", sa.String(length=2048), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("nickname_key", name="uq_users_nickname_key"),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("user_id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_auth_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_sessions")),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
    )
    op.create_index(
        "ix_auth_sessions_user_id",
        "auth_sessions",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("users")
```

The `Base.metadata` naming convention from Task 2 makes every `op.f()` name
deterministic.

- [ ] **Step 4: Run migration tests and inspect the generated schema**

Run:

```bash
uv run pytest tests/data/test_migrations.py -W error -q
tmp_dir="$(mktemp -d /tmp/inspire-flow-auth.XXXXXX)"
tmp_db="$tmp_dir/app.db"
APP_DATABASE_URL="sqlite:///$tmp_db" uv run alembic upgrade head
APP_DATABASE_URL="sqlite:///$tmp_db" uv run alembic current
APP_DATABASE_URL="sqlite:///$tmp_db" uv run alembic downgrade base
rm -f "$tmp_db"
rmdir "$tmp_dir"
```

Expected: pytest passes, `current` reports `20260723_0001 (head)`, and downgrade
completes.

- [ ] **Step 5: Commit persistence foundation**

Run:

```bash
git add alembic.ini migrations src/inspire_flow_backend/core/time.py src/inspire_flow_backend/data tests/data
git commit -m "feat: add SQLite user and session schema"
```

Expected: one commit with ORM infrastructure and reversible migration.

### Task 4: Implement identity and credential primitives

**Files:**

- Create: `src/inspire_flow_backend/core/identity.py`
- Create: `src/inspire_flow_backend/core/security.py`
- Create: `tests/core/test_identity.py`
- Create: `tests/core/test_security.py`

- [ ] **Step 1: Write nickname tests and confirm they fail**

Create `tests/core/test_identity.py`:

```python
import pytest

from inspire_flow_backend.core.identity import clean_nickname, nickname_key


def test_clean_nickname_trims_without_rewriting_display_value() -> None:
    assert clean_nickname("  Ａria  ") == "Ａria"


def test_nickname_key_applies_nfkc_and_casefold() -> None:
    assert nickname_key("ＡRIA") == nickname_key("aria")


@pytest.mark.parametrize("value", ["a", "x" * 51, "valid\\nname", "name\\u0000"])
def test_clean_nickname_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        clean_nickname(value)
```

Run:

```bash
uv run pytest tests/core/test_identity.py -W error -q
```

Expected: import failure.

- [ ] **Step 2: Implement nickname normalization**

Create `core/identity.py`:

```python
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
```

- [ ] **Step 3: Write password/token tests and confirm they fail**

Create `tests/core/test_security.py`:

```python
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
```

Run:

```bash
uv run pytest tests/core/test_security.py -W error -q
```

Expected: import failure.

- [ ] **Step 4: Implement password and token primitives**

Create `core/security.py`:

```python
import hashlib
import secrets

from pwdlib import PasswordHash

password_hash = PasswordHash.recommended()
DUMMY_PASSWORD_HASH = password_hash.hash(
    "dummy password used only to equalize failed login work"
)


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, password_hash_value: str) -> bool:
    return password_hash.verify(password, password_hash_value)


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def digest_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/core -W error -q
```

Expected: all identity and security tests pass.

### Task 5: Define safe API schemas and the error boundary

**Files:**

- Create: `src/inspire_flow_backend/schemas/users.py`
- Create: `src/inspire_flow_backend/schemas/sessions.py`
- Create: `src/inspire_flow_backend/schemas/errors.py`
- Create: `src/inspire_flow_backend/core/errors.py`
- Modify: `src/inspire_flow_backend/main.py`
- Create: `tests/api/conftest.py`
- Create: `tests/api/test_users.py`

- [ ] **Step 1: Add failing validation/error contract tests**

In `tests/api/test_users.py`, start with:

```python
def test_registration_validation_never_echoes_password(client: TestClient) -> None:
    password = "short"

    response = client.post(
        "/api/v1/users",
        json={"nickname": "aria", "password": password},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert password not in response.text


def test_registration_rejects_unknown_fields(client: TestClient) -> None:
    response = client.post(
        "/api/v1/users",
        json={
            "nickname": "aria",
            "password": "correct horse battery staple",
            "role": "admin",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
```

Initially construct the test app without a user router so the tests fail with
404; the completed fixture arrives in Task 8.

- [ ] **Step 2: Create public and input schemas**

Create `schemas/users.py` with:

```python
from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, field_validator, model_validator

from inspire_flow_backend.core.identity import clean_nickname

AvatarUrl = Annotated[HttpUrl, Field(max_length=2048)]


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nickname: str
    password: SecretStr = Field(min_length=15, max_length=128)
    avatar_url: AvatarUrl | None = None

    @field_validator("nickname")
    @classmethod
    def validate_nickname(cls, value: str) -> str:
        return clean_nickname(value)


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nickname: str | None = None
    avatar_url: AvatarUrl | None = None

    @field_validator("nickname")
    @classmethod
    def validate_nickname(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return clean_nickname(value)

    @model_validator(mode="after")
    def validate_supplied_fields(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one profile field is required")
        if "nickname" in self.model_fields_set and self.nickname is None:
            raise ValueError("Nickname cannot be null")
        return self


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nickname: str
    avatar_url: str | None
    created_at: datetime
    updated_at: datetime
```

Create `schemas/sessions.py`:

```python
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from inspire_flow_backend.core.identity import clean_nickname
from inspire_flow_backend.schemas.users import UserPublic


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nickname: str
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("nickname")
    @classmethod
    def validate_nickname(cls, value: str) -> str:
        return clean_nickname(value)


class SessionCreated(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user: UserPublic
```

- [ ] **Step 3: Define the error schema and application exceptions**

Create `schemas/errors.py`:

```python
from pydantic import BaseModel


class ErrorDetail(BaseModel):
    location: list[str | int]
    message: str
    type: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
```

Create `core/errors.py`:

```python
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


class ApplicationError(Exception):
    status_code = 500
    code = "application_error"
    message = "The request could not be completed"
    headers: dict[str, str] | None = None


class NicknameConflictError(ApplicationError):
    status_code = 409
    code = "nickname_conflict"
    message = "Nickname is already in use"


class InvalidCredentialsError(ApplicationError):
    status_code = 401
    code = "invalid_credentials"
    message = "Invalid nickname or password"


class InvalidSessionError(ApplicationError):
    status_code = 401
    code = "invalid_session"
    message = "A valid bearer session is required"
    headers = {"WWW-Authenticate": "Bearer"}


def error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, object]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, object] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return JSONResponse(
        status_code=status_code,
        content={"error": body},
        headers=headers,
    )


async def handle_application_error(
    request: Request,
    exc: ApplicationError,
) -> JSONResponse:
    del request
    return error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        headers=exc.headers,
    )


async def handle_request_validation_error(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    del request
    details = [
        {
            "location": list(error["loc"]),
            "message": str(error["msg"]),
            "type": str(error["type"]),
        }
        for error in exc.errors()
    ]
    return error_response(
        status_code=422,
        code="validation_error",
        message="Request validation failed",
        details=details,
    )


async def handle_http_exception(
    request: Request,
    exc: HTTPException,
) -> JSONResponse:
    del request
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return error_response(
        status_code=exc.status_code,
        code="http_error",
        message=message,
        headers=exc.headers,
    )


def register_error_handlers(application: FastAPI) -> None:
    application.add_exception_handler(
        ApplicationError,
        handle_application_error,
    )
    application.add_exception_handler(
        RequestValidationError,
        handle_request_validation_error,
    )
    application.add_exception_handler(
        HTTPException,
        handle_http_exception,
    )
```

Do not copy `input`, `ctx`, exception objects, request headers, or request
bodies into validation details.

- [ ] **Step 4: Register handlers in the app factory**

Update `main.py`:

```python
from inspire_flow_backend.core.errors import register_error_handlers


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title=settings.name, debug=settings.debug)
    register_error_handlers(application)
    application.include_router(api_router, prefix=settings.api_v1_prefix)
    return application
```

- [ ] **Step 5: Run schema unit checks**

Run:

```bash
uv run python -c "from inspire_flow_backend.schemas.users import UserCreate; assert UserCreate(nickname=' aria ', password='correct horse battery staple').nickname == 'aria'"
uv run ruff check src/inspire_flow_backend/core src/inspire_flow_backend/schemas
```

Expected: schema construction succeeds and Ruff reports no errors.

### Task 6: Implement user repositories and services with transaction ownership

**Files:**

- Create: `src/inspire_flow_backend/data/repositories/users.py`
- Create: `src/inspire_flow_backend/services/users.py`
- Expand: `tests/api/conftest.py`
- Expand: `tests/api/test_users.py`

- [ ] **Step 1: Build the isolated database fixture**

Create `tests/api/conftest.py`:

```python
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from inspire_flow_backend.data.base import Base
from inspire_flow_backend.data.database import (
    create_database_engine,
    get_db_session,
)
from inspire_flow_backend.data.models import AuthSession, User
from inspire_flow_backend.main import create_app


@pytest.fixture
def db_session_factory(
    tmp_path: Path,
) -> Generator[sessionmaker[Session], None, None]:
    database_path = tmp_path / "api.db"
    test_engine = create_database_engine(f"sqlite:///{database_path}")
    assert {AuthSession.__tablename__, User.__tablename__} <= set(
        Base.metadata.tables
    )
    Base.metadata.create_all(test_engine)
    factory = sessionmaker(bind=test_engine, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(test_engine)
    test_engine.dispose()


@pytest.fixture
def client(
    db_session_factory: sessionmaker[Session],
) -> Generator[TestClient, None, None]:
    application = create_app()

    def override_db_session() -> Generator[Session, None, None]:
        with db_session_factory() as db:
            yield db

    application.dependency_overrides[get_db_session] = override_db_session
    with TestClient(application) as test_client:
        yield test_client
    application.dependency_overrides.clear()
```

`Base.metadata.create_all()` is test fixture setup only. Application startup and
production commands continue to require Alembic.

- [ ] **Step 2: Add registration tests**

Add these observable cases to `tests/api/test_users.py`:

```python
def test_registers_user_with_public_fields(client: TestClient) -> None:
    before = datetime.now(UTC)
    response = client.post(
        "/api/v1/users",
        json={
            "nickname": " aria ",
            "password": "correct horse battery staple",
            "avatar_url": "https://cdn.example.com/aria.png",
        },
    )
    after = datetime.now(UTC)

    assert response.status_code == 201
    body = response.json()
    UUID(body["id"])
    assert body["nickname"] == "aria"
    assert body["avatar_url"] == "https://cdn.example.com/aria.png"
    assert before <= datetime.fromisoformat(body["created_at"]) <= after
    assert datetime.fromisoformat(body["updated_at"]) == datetime.fromisoformat(
        body["created_at"]
    )
    assert "password" not in response.text
    assert "nickname_key" not in response.text


def test_rejects_normalized_nickname_duplicate(client: TestClient) -> None:
    first = {
        "nickname": "Ａria",
        "password": "correct horse battery staple",
    }
    second = {
        "nickname": "aria",
        "password": "another secure passphrase value",
    }
    assert client.post("/api/v1/users", json=first).status_code == 201

    response = client.post("/api/v1/users", json=second)

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "nickname_conflict",
            "message": "Nickname is already in use",
        }
    }
```

Run the two tests and expect 404 until routes are added:

```bash
uv run pytest tests/api/test_users.py -W error -q
```

- [ ] **Step 3: Implement the user repository**

Create `data/repositories/users.py`:

```python
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from inspire_flow_backend.data.models.user import User


def get_user_by_id(db: Session, user_id: UUID) -> User | None:
    return db.get(User, user_id)


def get_user_by_nickname_key(db: Session, key: str) -> User | None:
    return db.scalar(select(User).where(User.nickname_key == key))


def add_user(db: Session, user: User) -> None:
    db.add(user)
```

Do not call `commit()` or translate HTTP/domain errors in this module.

- [ ] **Step 4: Implement registration and profile-update services**

Create `services/users.py`:

```python
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from inspire_flow_backend.core.errors import NicknameConflictError
from inspire_flow_backend.core.identity import nickname_key
from inspire_flow_backend.core.security import hash_password
from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.models.user import User
from inspire_flow_backend.data.repositories.users import add_user
from inspire_flow_backend.schemas.users import UserCreate, UserUpdate


def register_user(db: Session, payload: UserCreate) -> User:
    now = utc_now()
    user = User(
        nickname=payload.nickname,
        nickname_key=nickname_key(payload.nickname),
        avatar_url=str(payload.avatar_url) if payload.avatar_url is not None else None,
        password_hash=hash_password(payload.password.get_secret_value()),
        created_at=now,
        updated_at=now,
    )
    add_user(db, user)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise NicknameConflictError from error
    db.refresh(user)
    return user


def update_user(db: Session, user: User, payload: UserUpdate) -> User:
    changed = False
    if "nickname" in payload.model_fields_set:
        assert payload.nickname is not None
        new_nickname_key = nickname_key(payload.nickname)
        if (
            user.nickname != payload.nickname
            or user.nickname_key != new_nickname_key
        ):
            user.nickname = payload.nickname
            user.nickname_key = new_nickname_key
            changed = True

    if "avatar_url" in payload.model_fields_set:
        new_avatar_url = (
            str(payload.avatar_url) if payload.avatar_url is not None else None
        )
        if user.avatar_url != new_avatar_url:
            user.avatar_url = new_avatar_url
            changed = True

    if not changed:
        return user

    user.updated_at = utc_now()
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise NicknameConflictError from error
    db.refresh(user)
    return user
```

- [ ] **Step 5: Run service tests indirectly after route wiring**

Keep the registration tests red for now. Run:

```bash
uv run ruff check src/inspire_flow_backend/data/repositories/users.py src/inspire_flow_backend/services/users.py
```

Expected: Ruff passes.

### Task 7: Implement session repositories, services, and bearer resolution

**Files:**

- Create: `src/inspire_flow_backend/data/repositories/sessions.py`
- Create: `src/inspire_flow_backend/services/sessions.py`
- Create: `src/inspire_flow_backend/api/dependencies.py`
- Expand: `tests/api/test_sessions.py`

- [ ] **Step 1: Write session behavior tests and confirm they fail**

Create `tests/api/test_sessions.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from inspire_flow_backend.core.security import digest_session_token
from inspire_flow_backend.data.models.auth_session import AuthSession

PASSWORD = "correct horse battery staple"


def register(client: TestClient, nickname: str = "aria") -> None:
    response = client.post(
        "/api/v1/users",
        json={
            "nickname": nickname,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 201


def login(client: TestClient, nickname: str = "aria") -> str:
    response = client.post(
        "/api/v1/sessions",
        json={
            "nickname": nickname,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 201
    return response.json()["access_token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_login_returns_opaque_session_and_no_store_headers(
    client: TestClient,
) -> None:
    register(client)
    before = datetime.now(UTC)

    response = client.post(
        "/api/v1/sessions",
        json={"nickname": "aria", "password": PASSWORD},
    )
    after = datetime.now(UTC)

    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert len(body["access_token"]) >= 43
    assert body["user"]["nickname"] == "aria"
    expires_at = datetime.fromisoformat(body["expires_at"])
    assert before + timedelta(hours=24) <= expires_at
    assert expires_at <= after + timedelta(hours=24)
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Pragma"] == "no-cache"


def test_login_failures_do_not_reveal_nickname_existence(
    client: TestClient,
) -> None:
    register(client)

    unknown = client.post(
        "/api/v1/sessions",
        json={"nickname": "missing-user", "password": "wrong"},
    )
    incorrect = client.post(
        "/api/v1/sessions",
        json={"nickname": "aria", "password": "wrong"},
    )

    expected = {
        "error": {
            "code": "invalid_credentials",
            "message": "Invalid nickname or password",
        }
    }
    assert unknown.status_code == 401
    assert incorrect.status_code == 401
    assert unknown.json() == incorrect.json() == expected


def test_persists_only_session_token_digest(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    register(client)
    access_token = login(client)

    with db_session_factory() as db:
        persisted_hashes = list(db.scalars(select(AuthSession.token_hash)))

    assert access_token not in persisted_hashes
    assert digest_session_token(access_token) in persisted_hashes


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer unknown-token"},
        {"Authorization": "Bearer"},
    ],
)
def test_rejects_invalid_session_headers(
    client: TestClient,
    headers: dict[str, str],
) -> None:
    response = client.get("/api/v1/users/me", headers=headers)

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "invalid_session",
            "message": "A valid bearer session is required",
        }
    }
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_expired_session_is_rejected_and_removed(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    register(client)
    access_token = login(client)
    token_hash = digest_session_token(access_token)
    with db_session_factory() as db:
        auth_session = db.scalar(
            select(AuthSession).where(AuthSession.token_hash == token_hash)
        )
        assert auth_session is not None
        auth_session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    response = client.get("/api/v1/users/me", headers=bearer(access_token))

    assert response.status_code == 401
    with db_session_factory() as db:
        assert db.scalar(
            select(AuthSession).where(AuthSession.token_hash == token_hash)
        ) is None


def test_logout_revokes_only_the_current_session(client: TestClient) -> None:
    register(client)
    first_token = login(client)
    second_token = login(client)
    assert client.get(
        "/api/v1/users/me",
        headers=bearer(first_token),
    ).status_code == 200
    assert client.get(
        "/api/v1/users/me",
        headers=bearer(second_token),
    ).status_code == 200

    response = client.delete(
        "/api/v1/sessions/current",
        headers=bearer(first_token),
    )

    assert response.status_code == 204
    assert response.content == b""
    assert client.get(
        "/api/v1/users/me",
        headers=bearer(first_token),
    ).status_code == 401
    assert client.get(
        "/api/v1/users/me",
        headers=bearer(second_token),
    ).status_code == 200
```

Run:

```bash
uv run pytest tests/api/test_sessions.py -W error -q
```

Expected: route failures.

- [ ] **Step 2: Implement session repository operations**

Create `data/repositories/sessions.py`:

```python
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from inspire_flow_backend.data.models.auth_session import AuthSession


def add_session(db: Session, auth_session: AuthSession) -> None:
    db.add(auth_session)


def get_session_by_token_hash(db: Session, token_hash: str) -> AuthSession | None:
    statement = (
        select(AuthSession)
        .options(joinedload(AuthSession.user))
        .where(AuthSession.token_hash == token_hash)
    )
    return db.scalar(statement)


def delete_session(db: Session, auth_session: AuthSession) -> None:
    db.delete(auth_session)
```

- [ ] **Step 3: Implement session use cases**

Create `services/sessions.py`:

```python
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from inspire_flow_backend.core.errors import (
    InvalidCredentialsError,
    InvalidSessionError,
)
from inspire_flow_backend.core.identity import nickname_key
from inspire_flow_backend.core.security import (
    DUMMY_PASSWORD_HASH,
    digest_session_token,
    generate_session_token,
    verify_password,
)
from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.models.auth_session import AuthSession
from inspire_flow_backend.data.models.user import User
from inspire_flow_backend.data.repositories.sessions import (
    add_session,
    delete_session,
    get_session_by_token_hash,
)
from inspire_flow_backend.data.repositories.users import get_user_by_nickname_key
from inspire_flow_backend.schemas.sessions import SessionCreate


@dataclass(frozen=True, slots=True)
class CreatedSession:
    access_token: str
    expires_at: datetime
    user: User


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    session: AuthSession
    user: User


def create_session(
    db: Session,
    payload: SessionCreate,
    ttl_hours: int,
) -> CreatedSession:
    user = get_user_by_nickname_key(db, nickname_key(payload.nickname))
    password_hash_value = (
        user.password_hash if user is not None else DUMMY_PASSWORD_HASH
    )
    password_is_valid = verify_password(
        payload.password.get_secret_value(),
        password_hash_value,
    )
    if user is None or not password_is_valid:
        raise InvalidCredentialsError

    now = utc_now()
    access_token = generate_session_token()
    auth_session = AuthSession(
        user_id=user.id,
        token_hash=digest_session_token(access_token),
        expires_at=now + timedelta(hours=ttl_hours),
        created_at=now,
    )
    add_session(db, auth_session)
    db.commit()
    db.refresh(auth_session)
    return CreatedSession(
        access_token=access_token,
        expires_at=auth_session.expires_at,
        user=user,
    )


def resolve_session(db: Session, token: str) -> AuthenticatedSession:
    auth_session = get_session_by_token_hash(
        db,
        digest_session_token(token),
    )
    if auth_session is None:
        raise InvalidSessionError
    if auth_session.expires_at <= utc_now():
        delete_session(db, auth_session)
        db.commit()
        raise InvalidSessionError
    return AuthenticatedSession(
        session=auth_session,
        user=auth_session.user,
    )


def revoke_session(db: Session, auth_session: AuthSession) -> None:
    delete_session(db, auth_session)
    db.commit()
```

The raw token exists only in the local `access_token` variable and the returned
`CreatedSession`; it is never assigned to an ORM field.

- [ ] **Step 4: Implement the FastAPI bearer dependency**

Create `api/dependencies.py`:

```python
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from inspire_flow_backend.core.errors import InvalidSessionError
from inspire_flow_backend.data.database import get_db_session
from inspire_flow_backend.services.sessions import (
    AuthenticatedSession,
    resolve_session,
)

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_session(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    db: Annotated[Session, Depends(get_db_session)],
) -> AuthenticatedSession:
    if (
        credentials is None
        or credentials.scheme.casefold() != "bearer"
        or not credentials.credentials
    ):
        raise InvalidSessionError
    return resolve_session(db, credentials.credentials)
```

- [ ] **Step 5: Run static checks**

Run:

```bash
uv run ruff check src/inspire_flow_backend/data/repositories/sessions.py src/inspire_flow_backend/services/sessions.py src/inspire_flow_backend/api/dependencies.py
```

Expected: Ruff passes.

### Task 8: Wire resource routes and make registration/login tests green

**Files:**

- Create: `src/inspire_flow_backend/api/routes/users.py`
- Create: `src/inspire_flow_backend/api/routes/sessions.py`
- Modify: `src/inspire_flow_backend/api/router.py`
- Expand: `tests/api/test_users.py`
- Expand: `tests/api/test_sessions.py`

- [ ] **Step 1: Create user routes**

Create `api/routes/users.py`:

```python
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from inspire_flow_backend.api.dependencies import get_current_session
from inspire_flow_backend.data.database import get_db_session
from inspire_flow_backend.schemas.errors import ErrorResponse
from inspire_flow_backend.schemas.users import UserCreate, UserPublic, UserUpdate
from inspire_flow_backend.services.sessions import AuthenticatedSession
from inspire_flow_backend.services.users import register_user, update_user

router = APIRouter()


@router.post(
    "",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def create_user(
    payload: UserCreate,
    db: Annotated[Session, Depends(get_db_session)],
) -> UserPublic:
    return UserPublic.model_validate(register_user(db, payload))


@router.get(
    "/me",
    response_model=UserPublic,
    responses={401: {"model": ErrorResponse}},
)
def read_current_user(
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
) -> UserPublic:
    return UserPublic.model_validate(authenticated.user)


@router.patch(
    "/me",
    response_model=UserPublic,
    responses={
        401: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def patch_current_user(
    payload: UserUpdate,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> UserPublic:
    return UserPublic.model_validate(update_user(db, authenticated.user, payload))
```

- [ ] **Step 2: Create session routes**

Create `api/routes/sessions.py`:

```python
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from inspire_flow_backend.api.dependencies import get_current_session
from inspire_flow_backend.core.config import Settings, get_settings
from inspire_flow_backend.data.database import get_db_session
from inspire_flow_backend.schemas.errors import ErrorResponse
from inspire_flow_backend.schemas.sessions import SessionCreate, SessionCreated
from inspire_flow_backend.schemas.users import UserPublic
from inspire_flow_backend.services.sessions import (
    AuthenticatedSession,
    create_session,
    revoke_session,
)

router = APIRouter()


@router.post(
    "",
    response_model=SessionCreated,
    status_code=status.HTTP_201_CREATED,
    responses={401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def login(
    payload: SessionCreate,
    response: Response,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionCreated:
    created = create_session(db, payload, settings.session_ttl_hours)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return SessionCreated(
        access_token=created.access_token,
        expires_at=created.expires_at,
        user=UserPublic.model_validate(created.user),
    )


@router.delete(
    "/current",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: {"model": ErrorResponse}},
)
def logout(
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> Response:
    revoke_session(db, authenticated.session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 3: Compose resource routers**

Update `api/router.py`:

```python
from inspire_flow_backend.api.routes.sessions import router as sessions_router
from inspire_flow_backend.api.routes.users import router as users_router

api_router.include_router(users_router, prefix="/users", tags=["users"])
api_router.include_router(sessions_router, prefix="/sessions", tags=["sessions"])
```

Leave the existing health-router composition unchanged.

- [ ] **Step 4: Run registration and login suites**

Run:

```bash
uv run pytest tests/api/test_users.py tests/api/test_sessions.py -W error -q
```

Expected: current registration and session tests pass. If the FastAPI 204 route
asserts a response model, return a bare `Response` exactly as shown.

- [ ] **Step 5: Commit the working authentication slice**

Run:

```bash
git add src/inspire_flow_backend tests/core tests/api
git commit -m "feat: add REST user authentication"
```

Expected: registration, login, bearer resolution, and logout code plus tests
are committed together.

### Task 9: Complete profile and credential-disclosure coverage

**Files:**

- Expand: `tests/api/test_users.py`

- [ ] **Step 1: Test authenticated profile retrieval**

Add these helpers and the current-user test to `tests/api/test_users.py`:

```python
PASSWORD = "correct horse battery staple"


def register_and_login(
    client: TestClient,
    nickname: str = "aria",
) -> tuple[dict[str, object], str]:
    registration = client.post(
        "/api/v1/users",
        json={"nickname": nickname, "password": PASSWORD},
    )
    assert registration.status_code == 201
    login = client.post(
        "/api/v1/sessions",
        json={"nickname": nickname, "password": PASSWORD},
    )
    assert login.status_code == 201
    return registration.json(), login.json()["access_token"]


def authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_reads_current_public_user(client: TestClient) -> None:
    registered, access_token = register_and_login(client)

    response = client.get(
        "/api/v1/users/me",
        headers=authorization(access_token),
    )

    assert response.status_code == 200
    assert response.json() == registered
    assert "password" not in response.text
    assert "nickname_key" not in response.text
```

Run:

```bash
uv run pytest tests/api/test_users.py::test_reads_current_public_user -W error -q
```

Expected: pass.

- [ ] **Step 2: Test profile mutation and timestamp semantics**

```python
def test_changes_nickname_and_new_value_becomes_login_identifier(
    client: TestClient,
) -> None:
    registered, access_token = register_and_login(client)

    response = client.patch(
        "/api/v1/users/me",
        headers=authorization(access_token),
        json={"nickname": "Aria Renamed"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["nickname"] == "Aria Renamed"
    old_updated_at = datetime.fromisoformat(str(registered["updated_at"]))
    new_updated_at = datetime.fromisoformat(body["updated_at"])
    assert new_updated_at > old_updated_at
    assert new_updated_at.utcoffset() == timedelta(0)
    assert client.post(
        "/api/v1/sessions",
        json={"nickname": "aria", "password": PASSWORD},
    ).status_code == 401
    assert client.post(
        "/api/v1/sessions",
        json={"nickname": "aria renamed", "password": PASSWORD},
    ).status_code == 201


def test_changes_then_clears_avatar(client: TestClient) -> None:
    registered, access_token = register_and_login(client)

    changed = client.patch(
        "/api/v1/users/me",
        headers=authorization(access_token),
        json={"avatar_url": "https://cdn.example.com/new.png"},
    )
    cleared = client.patch(
        "/api/v1/users/me",
        headers=authorization(access_token),
        json={"avatar_url": None},
    )

    assert changed.status_code == 200
    assert changed.json()["avatar_url"] == "https://cdn.example.com/new.png"
    assert datetime.fromisoformat(
        changed.json()["updated_at"]
    ) > datetime.fromisoformat(str(registered["updated_at"]))
    assert cleared.status_code == 200
    assert cleared.json()["avatar_url"] is None
    assert datetime.fromisoformat(
        cleared.json()["updated_at"]
    ) > datetime.fromisoformat(changed.json()["updated_at"])


def test_profile_no_op_preserves_updated_at(client: TestClient) -> None:
    registered, access_token = register_and_login(client)

    response = client.patch(
        "/api/v1/users/me",
        headers=authorization(access_token),
        json={"nickname": "aria"},
    )

    assert response.status_code == 200
    assert response.json()["updated_at"] == registered["updated_at"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"nickname": None},
        {"unexpected": True},
    ],
)
def test_rejects_invalid_profile_patch(
    client: TestClient,
    payload: dict[str, object],
) -> None:
    _, access_token = register_and_login(client)

    response = client.patch(
        "/api/v1/users/me",
        headers=authorization(access_token),
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_rejects_profile_nickname_conflict(client: TestClient) -> None:
    _, access_token = register_and_login(client, "aria")
    other = client.post(
        "/api/v1/users",
        json={"nickname": "beta", "password": PASSWORD},
    )
    assert other.status_code == 201

    response = client.patch(
        "/api/v1/users/me",
        headers=authorization(access_token),
        json={"nickname": "ＢＥＴＡ"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "nickname_conflict"
```

Run:

```bash
uv run pytest tests/api/test_users.py -W error -q
```

Expected: all profile cases pass.

- [ ] **Step 3: Complete invalid registration coverage**

```python
@pytest.mark.parametrize(
    ("payload", "secret_value"),
    [
        (
            {"nickname": "a", "password": "correct horse battery staple"},
            None,
        ),
        (
            {"nickname": "aria", "password": "short"},
            "short",
        ),
        (
            {
                "nickname": "aria",
                "password": "correct horse battery staple",
                "avatar_url": "not-a-url",
            },
            None,
        ),
    ],
)
def test_rejects_invalid_registration_without_echoing_secrets(
    client: TestClient,
    payload: dict[str, object],
    secret_value: str | None,
) -> None:
    response = client.post("/api/v1/users", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    if secret_value is not None:
        assert secret_value not in response.text
```

Run:

```bash
uv run pytest tests/api/test_users.py -W error -q
```

Expected: invalid fields use the safe validation envelope and the submitted
password is absent from the response text.

- [ ] **Step 4: Verify no raw password reaches SQLite**

```python
def test_persists_only_argon2_password_hash(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    password = "correct horse battery staple"
    response = client.post(
        "/api/v1/users",
        json={"nickname": "aria", "password": password},
    )
    assert response.status_code == 201

    with db_session_factory() as db:
        user = db.scalar(select(User).where(User.nickname == "aria"))

    assert user is not None
    assert user.password_hash != password
    assert password not in user.password_hash
    assert user.password_hash.startswith("$argon2")
```

Add the required `select`, `Session`, `sessionmaker`, and `User` imports at the
top of `test_users.py`.

Run:

```bash
uv run pytest tests/api/test_users.py::test_persists_only_argon2_password_hash -W error -q
```

Expected: pass.

- [ ] **Step 5: Run the whole suite before documentation**

Run:

```bash
uv run pytest -W error
uv run ruff check .
uv run ruff format --check .
```

Expected: all existing health/config and new authentication tests pass with no
warnings; Ruff reports no changes required.

### Task 10: Write and humanize the integration handoff

**Files:**

- Create: `HANDOFF_USERSYS.MD`
- Modify: `README.md`
- Create during review, ignored by Git:
  `.trellis/tasks/07-23-user-auth/research/handoff-draft.md`
- Create during review, ignored by Git:
  `.trellis/tasks/07-23-user-auth/research/handoff-review.md`

- [ ] **Step 1: Re-read both requested writing skills before drafting**

Read the complete files:

```bash
sed -n '1,360p' /Users/ariakage/.codex/skills/humanizer/SKILL.md
sed -n '1,420p' /Users/ariakage/.codex/skills/humanizer-zh/SKILL.md
```

Apply both instructions to this document only. Record the first draft and the
review notes in the task research directory so the final root file remains
clean.

- [ ] **Step 2: Draft the handoff from the tested contract**

Write Chinese sections in this order:

1. `# 用户系统接入说明`
2. `## 先跑起来`: `uv sync --locked --dev`, `uv run alembic upgrade head`,
   `uv run uvicorn inspire_flow_backend.main:app --reload`.
3. `## 调用约定`: default base URL and JSON content type.
4. `## 没有默认账号`: registration then login.
5. `## 1. 注册`: method/path, body, `201` body, `409` and `422`.
6. `## 2. 登录并保存凭据`: request, response, extract `ACCESS_TOKEN`.
7. `## 3. 携带凭据`: exact Authorization header.
8. `## 4. 读取和修改资料`: GET and PATCH, avatar clearing.
9. `## 5. 注销`: DELETE, `204`, token reuse behavior.
10. `## 错误对照`: the four stable codes.
11. `## 凭据使用注意`: never source-control, log, URL, or publish a token;
    production uses TLS and rate limiting.
12. `## 接入检查`: compact actionable checklist.

Use these shell variables in every curl block:

```bash
BASE_URL="${BASE_URL:-http://127.0.0.1:8000/api/v1}"
NICKNAME="${NICKNAME:-aria}"
PASSWORD="${PASSWORD:?请先设置 PASSWORD}"
ACCESS_TOKEN="${ACCESS_TOKEN:?请先用登录响应中的 access_token 设置 ACCESS_TOKEN}"
```

Do not include a working password or token literal.

- [ ] **Step 3: Apply the English humanizer review**

Use `humanizer:humanizer` as an editorial checklist even though the output is
Chinese. Remove canned introductions, repeated conclusions, unnecessary
headings, inflated claims, reader-address clichés, and generic warnings. Save
specific detected patterns and edits in `research/handoff-review.md`.

- [ ] **Step 4: Apply the Chinese humanizer review**

Use `humanizer-zh` to replace mechanical transitions, fragment-heavy prose,
fake quotations, excessive parentheticals, slogan-like wording, and uniform
sentence rhythms. Keep exact HTTP methods, paths, JSON keys, commands, status
codes, and security warnings unchanged.

- [ ] **Step 5: Update README entry points**

Add concise links and commands:

```markdown
uv run alembic upgrade head
uv run uvicorn inspire_flow_backend.main:app --reload
```

Link `HANDOFF_USERSYS.MD` as the user-system integration contract and document
`APP_DATABASE_URL` plus `APP_SESSION_TTL_HOURS`.

- [ ] **Step 6: Run document safety scans**

Run:

```bash
test -s HANDOFF_USERSYS.MD
! rg -n '[—–]' HANDOFF_USERSYS.MD
! rg -n '(sk-[A-Za-z0-9_-]{20,}|Bearer [A-Za-z0-9_-]{20,}|password["=: ]+"[^$<{])' HANDOFF_USERSYS.MD
rg -n 'POST /api/v1/users|POST /api/v1/sessions|Authorization: Bearer|DELETE /api/v1/sessions/current' HANDOFF_USERSYS.MD
```

Expected: file exists; dash and credential scans find nothing; all four
integration markers are present.

- [ ] **Step 7: Commit tested documentation**

Run:

```bash
git add HANDOFF_USERSYS.MD README.md
git commit -m "docs: hand off user system integration"
```

Expected: only the final handoff and README are committed; task research stays
ignored.

### Task 11: Full quality gate, runtime smoke, and Trellis spec capture

**Files:**

- Modify: `.trellis/spec/backend/database-guidelines.md`
- Modify: `.trellis/spec/backend/error-handling.md`
- Modify if executable conventions changed:
  `.trellis/spec/backend/directory-structure.md`
- Modify if commands changed:
  `.trellis/spec/backend/quality-guidelines.md`
- Update: `.trellis/tasks/07-23-user-auth/implement.md` checkboxes during
  execution

- [ ] **Step 1: Run the locked quality gate**

Run:

```bash
uv lock --check
uv sync --locked --dev
uv run ruff check .
uv run ruff format --check .
uv run pytest -W error
```

Expected: every command exits 0; pytest has no warnings.

- [ ] **Step 2: Test migrations against a fresh disposable database**

Run:

```bash
smoke_dir="$(mktemp -d /tmp/inspire-flow-auth-smoke.XXXXXX)"
smoke_db="$smoke_dir/app.db"
APP_DATABASE_URL="sqlite:///$smoke_db" uv run alembic upgrade head
APP_DATABASE_URL="sqlite:///$smoke_db" uv run alembic current
```

Expected: the migration reaches `20260723_0001 (head)`. Preserve the explicit
temporary path for the next step; remove the directory only after the process
is stopped.

- [ ] **Step 3: Start Uvicorn and exercise the real HTTP boundary**

Start:

```bash
APP_DATABASE_URL="sqlite:///$smoke_db" uv run uvicorn inspire_flow_backend.main:app --host 127.0.0.1 --port 8765
```

From a second command session, verify:

```bash
curl --fail --silent http://127.0.0.1:8765/api/v1/health
curl --fail --silent --request POST http://127.0.0.1:8765/api/v1/users \
  --header 'Content-Type: application/json' \
  --data '{"nickname":"smoke-user","password":"smoke test passphrase value"}'
```

Then log in, call `/users/me`, log out, and confirm reuse returns `401`. Stop
Uvicorn cleanly and remove the explicit `$smoke_dir`.

- [ ] **Step 4: Inspect OpenAPI and repository safety**

Run:

```bash
uv run python -c "from inspire_flow_backend.main import app; paths=app.openapi()['paths']; expected={'/api/v1/health','/api/v1/users','/api/v1/users/me','/api/v1/sessions','/api/v1/sessions/current'}; assert expected <= set(paths)"
git status --short
git check-ignore -v inspire_flow.db
git diff --check
```

Expected: every route exists, a database filename matches `.gitignore`, and
there are no whitespace errors or unintended generated files.

- [ ] **Step 5: Capture proven conventions in Trellis specs**

Use `trellis-update-spec` after the code and tests prove the patterns. Replace
the empty database and error-handling spec templates with:

- SQLAlchemy synchronous session ownership and repository no-commit rule;
- Alembic migration commands and reversal order;
- SQLite foreign-key and UTC datetime conventions;
- stable error envelope and password-safe validation details;
- application error to HTTP mapping;
- required tests and forbidden direct route-to-model access.

Do not document an aspirational convention that the implementation does not
exercise.

- [ ] **Step 6: Review the final diff and close the implementation history**

Run:

```bash
git diff origin/main...HEAD --stat
git diff origin/main...HEAD --check
git status --short --branch
```

If spec changes are trackable, commit them with:

```bash
git add .trellis/spec/backend
git commit -m "docs: record authentication backend conventions"
```

If `.trellis/` is intentionally ignored, leave it unforced and record that
fact in the session journal.

- [ ] **Step 7: Finish the Trellis task only after all checks pass**

Run the project finish sequence:

```bash
python3 ./.trellis/scripts/task.py validate 07-23-user-auth
python3 ./.trellis/scripts/task.py finish
python3 ./.trellis/scripts/task.py archive 07-23-user-auth
```

Record the implementation commits and quality-gate result with
`.trellis/scripts/add_session.py`. Archive only when the acceptance criteria
and handoff checks are all satisfied.

## Acceptance Coverage Map

| PRD outcome | Owning task and executable check |
| --- | --- |
| Public UUID registration response | Task 6, `test_registers_user_with_public_fields` |
| NFKC/casefold nickname uniqueness | Task 4 unit test and Task 6 duplicate API test |
| Safe registration validation | Task 5 password-reflection test and Task 9 invalid-input matrix |
| Argon2id digest-only password storage | Task 4 security unit test and Task 9 persistence test |
| 24-hour login and no-store headers | Task 7, `test_login_returns_opaque_session_and_no_store_headers` |
| Generic credential failure | Task 7, `test_login_failures_do_not_reveal_nickname_existence` |
| Digest-only opaque token storage | Task 7, `test_persists_only_session_token_digest` |
| Current-user retrieval | Task 9, `test_reads_current_public_user` |
| Profile update, clearing, no-op, and conflict | Task 9 profile test group |
| Invalid and expired bearer behavior | Task 7 parameterized and expiry tests |
| Current-session-only logout | Task 7, `test_logout_revokes_only_the_current_session` |
| Reversible SQLite schema | Task 3 migration smoke test |
| UTC and foreign-key behavior | Task 2 type and database tests |
| Health and OpenAPI compatibility | Task 11 full suite and runtime smoke |
| Chinese integration handoff | Task 10 content markers and safety scans |
| Lock, lint, format, warnings, and runtime | Task 11 quality gate |

## Rollback Points

- Before Task 2, rollback is limited to dependency/configuration changes.
- After the initial migration, use `uv run alembic downgrade base` only on a
  disposable or backed-up database; it deletes both user and session tables.
- Before route composition, the health API remains independently runnable.
- Each commit boundary is cohesive. Prefer reverting the relevant feature
  commit over rewriting history.
- Never delete an existing SQLite file as part of rollback. Move it to a
  clearly named backup path if the user explicitly requests a destructive
  reset.

## Pre-Start Review Gate

Before `task.py start`, verify:

- [ ] The final planning summary has been shown to the user.
- [ ] A subsequent user message explicitly approves implementation.
- [ ] `prd.md`, `design.md`, and this file contain no unresolved product
      decisions.
- [ ] The endpoint paths, status codes, schema names, function names, and
      timestamp behavior match across all three artifacts.
- [ ] The implementation remains inline and does not dispatch sub-agents.
