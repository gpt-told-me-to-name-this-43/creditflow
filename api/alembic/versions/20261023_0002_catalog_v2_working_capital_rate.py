"""Design 2.5 products-v2: working_capital 24% → 25%, без изменения снимков расчётов.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Пустой каталог заполнит новый seed; уже заполненный v1 обновляется миграцией.
    # Чужую/нестандартную ставку не перезаписываем. Снимки ранее принятых условий неизменны.
    op.execute(
        "UPDATE credit_products SET annual_rate_pct = 25 "
        "WHERE id = 'working_capital' AND annual_rate_pct = 24"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE credit_products SET annual_rate_pct = 24 "
        "WHERE id = 'working_capital' AND annual_rate_pct = 25"
    )
