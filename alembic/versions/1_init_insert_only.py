from alembic import op


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_update_delete()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'Table % is insert-only. Updates and deletes are forbidden.', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql;
    """)

    insert_only_tables = [
        "scoring_results",
        "decision_proposals",
        "credit_decisions",
        "external_snapshots",
        "application_events",
    ]

    for table in insert_only_tables:
        op.execute(f"""
            CREATE TRIGGER {table}_insert_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION prevent_update_delete();
        """)


def downgrade() -> None:
    insert_only_tables = [
        "scoring_results",
        "decision_proposals",
        "credit_decisions",
        "external_snapshots",
        "application_events",
    ]
    for table in insert_only_tables:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_insert_only ON {table};")
    op.execute("DROP FUNCTION IF EXISTS prevent_update_delete();")
