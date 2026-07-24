from pathlib import Path

import sqlalchemy as sa
from alembic import command

from tests.data.test_migrations import make_config

PUBLIC_WORKSHOP_TABLES = {
    "brand_organizations",
    "brand_memberships",
    "brand_invitations",
    "creator_workshops",
    "workshop_social_accounts",
    "workshop_contacts",
    "workshop_project_selections",
    "workshop_publications",
    "workshop_publication_social_accounts",
    "workshop_publication_contacts",
    "workshop_publication_project_cards",
    "workshop_brand_authorizations",
    "brand_follows",
    "brand_interests",
    "creator_inbox_items",
    "idempotency_records",
    "agent_turn_runs",
}


def test_public_workshop_migration_is_reversible(tmp_path: Path) -> None:
    database_path = tmp_path / "public-workshop.db"
    config = make_config(database_path)

    command.upgrade(config, "head")
    engine = sa.create_engine(f"sqlite:///{database_path}")
    inspector = sa.inspect(engine)

    assert PUBLIC_WORKSHOP_TABLES <= set(inspector.get_table_names())
    assert {
        "uq_brand_memberships_brand_id_user_id",
    } == {str(item["name"]) for item in inspector.get_unique_constraints("brand_memberships")}
    assert {
        "uq_workshop_brand_authorizations_creator_user_id_brand_id",
    } == {
        str(item["name"])
        for item in inspector.get_unique_constraints("workshop_brand_authorizations")
    }
    assert {
        "uq_brand_follows_brand_id_creator_user_id",
    } == {str(item["name"]) for item in inspector.get_unique_constraints("brand_follows")}
    assert {
        "uq_workshop_publications_workshop_user_id_version",
    } == {str(item["name"]) for item in inspector.get_unique_constraints("workshop_publications")}
    assert "updated_at" in {
        str(column["name"]) for column in inspector.get_columns("workshop_publications")
    }

    command.downgrade(config, "20260724_0008")
    assert PUBLIC_WORKSHOP_TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    assert {"users", "projects"} <= set(sa.inspect(engine).get_table_names())
    engine.dispose()
