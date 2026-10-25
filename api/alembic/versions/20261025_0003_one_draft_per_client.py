"""Один DRAFT на клиента: частичный уникальный индекс (issue #7, design §3.3).

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # UNIQUE с WHERE PostgreSQL не поддерживает — только частичный уникальный индекс
    op.create_index(
        "uq_applications_one_draft",
        "applications",
        ["owner_user_id"],
        unique=True,
        postgresql_where="status = 'DRAFT'",
    )


def downgrade() -> None:
    op.drop_index("uq_applications_one_draft", table_name="applications")
