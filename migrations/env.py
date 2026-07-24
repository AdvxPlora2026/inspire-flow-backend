from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from inspire_flow_backend.core.config import get_settings
from inspire_flow_backend.data.base import Base
from inspire_flow_backend.data.models.agent_conversation import AgentConversation
from inspire_flow_backend.data.models.agent_message import AgentMessage
from inspire_flow_backend.data.models.auth_session import AuthSession
from inspire_flow_backend.data.models.transcription_job import TranscriptionJob
from inspire_flow_backend.data.models.user import User
from inspire_flow_backend.data.models.user_memory import UserMemory
from inspire_flow_backend.data.models.user_profile import UserProfile

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

configured_url = config.get_main_option("sqlalchemy.url")
if not configured_url:
    config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata
assert {
    AgentConversation.__tablename__,
    AgentMessage.__tablename__,
    AuthSession.__tablename__,
    TranscriptionJob.__tablename__,
    User.__tablename__,
    UserMemory.__tablename__,
    UserProfile.__tablename__,
} <= set(target_metadata.tables)


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
