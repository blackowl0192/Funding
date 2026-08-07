from pathlib import Path

from funding_terminal.db.migrations import discover_migrations


def test_discover_migrations_sorted_by_numeric_prefix(tmp_path: Path) -> None:
    (tmp_path / "010_ten.sql").write_text("SELECT 10;", encoding="utf-8")
    (tmp_path / "001_one.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "notes.sql").write_text("ignored", encoding="utf-8")

    migrations = discover_migrations(tmp_path)

    assert [migration.version for migration in migrations] == [1, 10]


def test_project_migrations_include_capital_and_fee_model() -> None:
    migrations = discover_migrations(Path("migrations"))

    assert [migration.version for migration in migrations] == [1, 2]
    assert migrations[1].name == "002_capital_and_fee_model.sql"


def test_capital_fee_migration_is_idempotent_sql() -> None:
    sql = Path("migrations/002_capital_and_fee_model.sql").read_text(encoding="utf-8")

    assert "ADD COLUMN IF NOT EXISTS spot_budget" in sql
    assert "DROP COLUMN IF EXISTS spot_maker_fee" in sql
    assert "has_legacy_fee_columns" in sql
    assert "trading_settings_budget_within_total" in sql
