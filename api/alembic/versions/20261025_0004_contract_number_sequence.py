"""Последовательность номеров договоров CF-<год>-<6 цифр> (issue #7).

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Отдельная последовательность, а не max(number) + 1: параллельные APPROVE не столкнутся.
    op.execute("CREATE SEQUENCE contract_number_seq START 1")


def downgrade() -> None:
    op.execute("DROP SEQUENCE contract_number_seq")
