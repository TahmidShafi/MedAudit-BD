"""Unit and integration tests for SQLite database (data/processed/medaudit.db)."""

import sqlite3
import pytest

from medaudit.config import PROJECT_ROOT

DB_PATH = PROJECT_ROOT / "data" / "processed" / "medaudit.db"


@pytest.fixture(scope="module")
def db_conn():
    """Module-level fixture providing connection to built database."""
    assert DB_PATH.exists(), f"Database not found at {DB_PATH}. Run scripts/01_build_db.py first."
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    yield conn
    conn.close()


def test_database_table_row_counts(db_conn):
    """Verify exact row counts for primary tables matching Phase 3 requirements."""
    cursor = db_conn.cursor()

    # Exact expected counts
    expected_counts = {
        "brands": 14013,
        "products": 21714,
        "price_packs": 23096,
        "lasa_pairs": 3358,
    }

    for table, expected in expected_counts.items():
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        actual = cursor.fetchone()[0]
        assert actual == expected, f"Table '{table}' expected {expected} rows, got {actual}"

    # Child tables with minimum expected rows
    cursor.execute("SELECT COUNT(*) FROM generic_components")
    assert cursor.fetchone()[0] >= 21714

    cursor.execute("SELECT COUNT(*) FROM strength_components")
    assert cursor.fetchone()[0] >= 20000

    cursor.execute("SELECT COUNT(*) FROM parse_anomalies")
    assert cursor.fetchone()[0] >= 500


def test_foreign_key_integrity(db_conn):
    """Verify that foreign keys are strictly valid and there are no orphan rows."""
    cursor = db_conn.cursor()
    cursor.execute("PRAGMA foreign_key_check;")
    violations = cursor.fetchall()
    assert len(violations) == 0, f"Foreign key integrity violations found: {violations}"


def test_index_existence(db_conn):
    """Verify that all required query performance indexes are created."""
    cursor = db_conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
    indexes = {row[0] for row in cursor.fetchall()}

    expected_indexes = {
        "idx_brands_normalized",
        "idx_products_brand_id",
        "idx_products_form_strength",
        "idx_generic_components_generic",
        "idx_generic_components_product_id",
        "idx_strength_components_product_id",
        "idx_price_packs_product_id",
        "idx_price_packs_norm_price",
    }
    for idx in expected_indexes:
        assert idx in indexes, f"Required index '{idx}' is missing from database"


def test_sample_brand_and_product_relationships(db_conn):
    """Test lookup of known product (e.g. Napa) and its related child rows."""
    cursor = db_conn.cursor()

    # Look up Napa 500 mg tablet
    cursor.execute(
        """
        SELECT p.product_id, b.brand_name, b.manufacturer, p.dosage_form, p.normalized_strength, p.release_type
        FROM products p
        JOIN brands b ON p.brand_id = b.brand_id
        WHERE b.brand_name = 'Napa' AND p.dosage_form = 'Tablet' AND p.normalized_strength = '500 mg'
        """
    )
    rows = cursor.fetchall()
    assert len(rows) > 0, "Napa 500 mg Tablet not found in products"
    prod_id = rows[0][0]

    # Verify generic components
    cursor.execute(
        "SELECT canonical_generic, is_nti FROM generic_components WHERE product_id = ?",
        (prod_id,),
    )
    gen_rows = cursor.fetchall()
    assert len(gen_rows) == 1
    assert gen_rows[0][0] == "paracetamol"
    assert gen_rows[0][1] == 0  # Paracetamol is not NTI

    # Verify price packs
    cursor.execute(
        "SELECT container_type, pack_qty, unit_price_bdt, normalized_unit_price_bdt, comparison_unit FROM price_packs WHERE product_id = ?",
        (prod_id,),
    )
    packs = cursor.fetchall()
    assert len(packs) > 0
    assert packs[0][0] == "pack"
    assert packs[0][4] == "per_unit"


def test_nti_flags_in_database(db_conn):
    """Verify that NTI drugs (Warfarin, Levothyroxine, Insulin) have is_nti = 1."""
    cursor = db_conn.cursor()

    for nti_generic in ["warfarin", "levothyroxine", "digoxin"]:
        cursor.execute(
            "SELECT COUNT(*) FROM generic_components WHERE canonical_generic = ? AND is_nti = 1",
            (nti_generic,),
        )
        count = cursor.fetchone()[0]
        assert count > 0, f"Expected NTI generic '{nti_generic}' to be flagged is_nti = 1"

    # Non-NTI check
    cursor.execute(
        "SELECT COUNT(*) FROM generic_components WHERE canonical_generic = 'paracetamol' AND is_nti = 1"
    )
    assert cursor.fetchone()[0] == 0


def test_parse_anomalies_logged(db_conn):
    """Verify that anomalies from generic, strength, and price modules are recorded."""
    cursor = db_conn.cursor()
    cursor.execute("SELECT DISTINCT module FROM parse_anomalies")
    modules = {row[0] for row in cursor.fetchall()}
    assert "generic" in modules
    assert "strength" in modules
    assert "price" in modules


def test_bootstrap_is_database_complete():
    """Verify bootstrap module detects complete database and invalid paths."""
    from medaudit.db.bootstrap import is_database_complete, ensure_database
    from pathlib import Path

    # Real DB is complete
    assert is_database_complete(DB_PATH) is True

    # Non-existent DB is not complete
    dummy_path = Path("data/processed/nonexistent_dummy.db")
    assert is_database_complete(dummy_path) is False

    # Calling ensure_database on existing complete DB returns path immediately without rebuild
    assert ensure_database(DB_PATH) == DB_PATH

