"""Unit tests for src/medaudit/ingest/ module."""

import pandas as pd
import pytest

from medaudit.ingest.loader import (
    EXPECTED_COLUMNS,
    analyze_duplicate_combinations,
    load_dataset_records,
    validate_schema,
)
from medaudit.ingest.models import BrandEntity, ProductRecord, SchemaValidationError


def create_mock_dataframe(n_rows: int = 5) -> pd.DataFrame:
    """Helper to create a valid 10-column DataFrame."""
    data = {
        "brand id": list(range(101, 101 + n_rows)),
        "brand name": [f"Brand {i}" for i in range(1, n_rows + 1)],
        "type": ["allopathic"] * n_rows,
        "slug": [f"slug-{i}" for i in range(1, n_rows + 1)],
        "dosage form": ["Tablet"] * n_rows,
        "generic": [f"Generic {i}" for i in range(1, n_rows + 1)],
        "strength": [f"{i * 10} mg" for i in range(1, n_rows + 1)],
        "manufacturer": ["Pharma Ltd"] * n_rows,
        "package container": ["Unit Price: ৳ 5.00"] * n_rows,
        "Package Size": ["(10's pack: ৳ 50.00)"] * n_rows,
    }
    return pd.DataFrame(data)


def test_validate_schema_passes_with_exact_columns():
    df = create_mock_dataframe(3)
    validate_schema(df.columns)  # Should not raise


def test_validate_schema_fails_on_missing_column():
    df = create_mock_dataframe(3)
    df_missing = df.drop(columns=["Package Size"])
    with pytest.raises(SchemaValidationError) as exc_info:
        validate_schema(df_missing.columns)
    assert "Missing required columns: ['Package Size']" in str(exc_info.value)


def test_validate_schema_fails_on_unexpected_column():
    df = create_mock_dataframe(3)
    df["extra_column"] = "unexpected"
    with pytest.raises(SchemaValidationError) as exc_info:
        validate_schema(df.columns)
    assert "Unexpected columns found: ['extra_column']" in str(exc_info.value)


def test_validate_schema_fails_on_both_missing_and_unexpected():
    df = create_mock_dataframe(3)
    df_altered = df.rename(columns={"Package Size": "wrong_size"})
    with pytest.raises(SchemaValidationError) as exc_info:
        validate_schema(df_altered.columns)
    err = str(exc_info.value)
    assert "Missing required columns: ['Package Size']" in err
    assert "Unexpected columns found: ['wrong_size']" in err


def test_load_dataset_records_maps_brand_id_to_product_id():
    df = create_mock_dataframe(2)
    products, brands = load_dataset_records(df)
    assert len(products) == 2
    assert products[0].product_id == 101
    assert products[1].product_id == 102
    assert isinstance(products[0], ProductRecord)


def test_load_dataset_records_deduplicates_brand_entities():
    # 3 SKUs with same brand name and manufacturer
    data = {
        "brand id": [1, 2, 3],
        "brand name": ["Napa", "Napa", "Napa"],
        "type": ["allopathic", "allopathic", "allopathic"],
        "slug": ["napa-tab", "napa-syp", "napa-drop"],
        "dosage form": ["Tablet", "Syrup", "Drop"],
        "generic": ["Paracetamol", "Paracetamol", "Paracetamol"],
        "strength": ["500 mg", "120 mg/5 ml", "80 mg/ml"],
        "manufacturer": ["Beximco", "Beximco", "Beximco"],
        "package container": ["Unit Price: ৳ 1.20", "60 ml bottle", "15 ml drop"],
        "Package Size": ["(100's pack)", None, None],
    }
    df = pd.DataFrame(data)
    products, brands = load_dataset_records(df)
    assert len(products) == 3
    # Exactly 1 BrandEntity created for Napa + Beximco
    assert len(brands) == 1
    assert 1 in brands
    assert brands[1].brand_name == "Napa"
    assert brands[1].manufacturer == "Beximco"
    # All 3 products reference brand_id = 1
    assert all(p.brand_id == 1 for p in products)


def test_load_dataset_records_preserves_nullable_package_size():
    data = {
        "brand id": [1, 2],
        "brand name": ["A", "B"],
        "type": ["allopathic", "allopathic"],
        "slug": ["slug-a", "slug-b"],
        "dosage form": ["Tablet", "Syrup"],
        "generic": ["GenA", "GenB"],
        "strength": ["10 mg", "5 mg"],
        "manufacturer": ["MfgA", "MfgB"],
        "package container": ["pkg1", "pkg2"],
        "Package Size": [None, "(50's pack: ৳ 200.00)"],
    }
    products, _ = load_dataset_records(pd.DataFrame(data))
    assert products[0].raw_package_size is None
    assert products[1].raw_package_size == "(50's pack: ৳ 200.00)"


def test_load_dataset_records_handles_null_generic_and_strength():
    data = {
        "brand id": [1],
        "brand name": ["TestBrand"],
        "type": ["allopathic"],
        "slug": ["slug-test"],
        "dosage form": ["Capsule"],
        "generic": [None],
        "strength": [None],
        "manufacturer": ["TestMfg"],
        "package container": [None],
        "Package Size": [None],
    }
    products, _ = load_dataset_records(pd.DataFrame(data))
    assert products[0].raw_generic is None
    assert products[0].raw_strength is None
    assert products[0].raw_package_container is None
    assert products[0].raw_package_size is None


def test_analyze_duplicate_combinations_reports_group_breakdown():
    # 2 rows with identical (brand, strength, dosage form, mfg) but different packages
    data = {
        "brand id": [10, 11, 12],
        "brand name": ["Abasaglar", "Abasaglar", "DistinctBrand"],
        "type": ["allopathic", "allopathic", "allopathic"],
        "slug": ["abasaglar-sc", "abasaglar-sc", "distinct-slug"],
        "dosage form": ["SC Injection", "SC Injection", "Tablet"],
        "generic": ["Insulin Glargine", "Insulin Glargine", "Metformin"],
        "strength": ["100 IU/ml", "100 IU/ml", "500 mg"],
        "manufacturer": ["Eli Lilly", "Eli Lilly", "Square"],
        "package container": ["3 ml cartridge", "3 ml pen", "Unit Price: ৳ 5.00"],
        "Package Size": ["(5's pack)", None, None],
    }
    df = pd.DataFrame(data)
    dup_report = analyze_duplicate_combinations(df)
    assert dup_report["total_rows"] == 3
    assert dup_report["unique_combinations"] == 2
    assert dup_report["duplicate_rows_count"] == 1
    assert dup_report["duplicate_group_count"] == 1
    grp = dup_report["duplicate_groups"][0]
    assert grp["key"]["brand_name"] == "Abasaglar"
    assert grp["sku_count"] == 2
    assert grp["skus"][0]["product_id"] == 10
    assert grp["skus"][1]["product_id"] == 11
