"""Lightweight schema validation test for tests/fixtures/price_labels.csv."""

import json
from pathlib import Path

import pandas as pd
import pytest

from medaudit.config import PROJECT_ROOT

FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "price_labels.csv"
PRICE_PARSER_PATH = PROJECT_ROOT / "src" / "medaudit" / "parsing" / "price.py"

ALLOWED_CONTAINER_TYPES = {
    "pack",
    "bottle",
    "vial",
    "ampoule",
    "tube",
    "drop",
    "spray",
    "inhaler",
    "cartridge",
    "pen",
    "sachet",
    "container",
    "unit_only",
    "other",
}

ALLOWED_COMPARISON_UNITS = {
    "per_unit",
    "per_ml",
    "per_gm",
    "per_l",
    "per_dose",
}

EXPECTED_CATEGORIES = {
    "unit_and_single_pack": 100,
    "volume_container_single": 75,
    "multi_pack_or_tier": 45,
    "other_format": 15,
    "unit_price_only": 10,
    "price_unavailable": 5,
}


import hashlib

LOCKED_FIXTURE_SHA256 = "6591aa77ca492ceb55eb7f9a34c35baedb287bfc3385ad9af520308bd7222b63"


def test_fixture_sha256_locked():
    """Assert the SHA-256 checksum of tests/fixtures/price_labels.csv to prove fixture integrity."""
    assert FIXTURE_PATH.exists(), f"Fixture file not found at {FIXTURE_PATH}"
    actual_hash = hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest()
    assert actual_hash == LOCKED_FIXTURE_SHA256, (
        f"Fixture SHA-256 mismatch! Expected {LOCKED_FIXTURE_SHA256}, got {actual_hash}"
    )


def test_fixture_file_exists_and_row_count():
    """Verify tests/fixtures/price_labels.csv exists and has exactly 250 rows with unique product_ids."""
    assert FIXTURE_PATH.exists(), f"Fixture file not found at {FIXTURE_PATH}"
    df = pd.read_csv(FIXTURE_PATH, encoding="utf-8")
    assert len(df) == 250, f"Expected 250 rows in fixture, found {len(df)}"
    assert df["product_id"].nunique() == 250, "product_id column contains duplicate IDs!"


def test_fixture_stratified_category_counts():
    """Verify exact category counts across the 250 rows."""
    df = pd.read_csv(FIXTURE_PATH, encoding="utf-8")
    counts = df["format_category"].value_counts().to_dict()
    for cat, expected_count in EXPECTED_CATEGORIES.items():
        assert counts.get(cat, 0) == expected_count, (
            f"Category '{cat}' expected {expected_count} rows, found {counts.get(cat, 0)}"
        )


def test_fixture_includes_delivery_variant_skus():
    """Verify delivery variant SKUs discovered in Phase 1 are included."""
    df = pd.read_csv(FIXTURE_PATH, encoding="utf-8")
    product_ids = set(df["product_id"])
    # 26940 (cartridge), 26939 (pen), 3446 (inhaler), 3443 (refill), 30170 (blister 21+7)
    for mandatory_id in [26940, 26939, 3446, 3443, 30170]:
        assert mandatory_id in product_ids, f"Mandatory delivery-variant SKU {mandatory_id} missing from fixture!"


def test_fixture_columns_and_json_schema():
    """Verify every row's expected_packs_json conforms strictly to the standardized schema."""
    df = pd.read_csv(FIXTURE_PATH, encoding="utf-8")
    expected_cols = [
        "product_id",
        "brand_name",
        "dosage_form",
        "raw_package_size",
        "raw_package_container",
        "format_category",
        "expected_packs_json",
        "needs_human_review",
        "review_notes",
    ]
    for col in expected_cols:
        assert col in df.columns, f"Missing required column: {col}"

    for idx, row in df.iterrows():
        p_id = row["product_id"]
        json_str = row["expected_packs_json"]
        assert isinstance(json_str, str), f"Row {p_id} expected_packs_json is not a string"

        try:
            packs = json.loads(json_str)
        except Exception as e:
            pytest.fail(f"Row {p_id} has invalid JSON: {e}")

        assert isinstance(packs, list), f"Row {p_id} expected_packs_json must be a JSON array"

        category = row["format_category"]
        if category == "price_unavailable":
            assert len(packs) == 0, f"Row {p_id} with category price_unavailable must have empty packs array"
        else:
            assert len(packs) > 0, f"Row {p_id} with category '{category}' must have at least one pack object"

        for p_idx, pack in enumerate(packs):
            # Check required fields
            for key in [
                "container_type",
                "volume_or_weight_value",
                "volume_or_weight_unit",
                "pack_qty",
                "unit_price_bdt",
                "pack_price_bdt",
                "normalized_unit_price_bdt",
                "comparison_unit",
            ]:
                assert key in pack, f"Row {p_id} pack[{p_idx}] missing required key '{key}'"

            # Check container_type
            assert pack["container_type"] in ALLOWED_CONTAINER_TYPES, (
                f"Row {p_id} pack[{p_idx}] container_type '{pack['container_type']}' not in allowed set"
            )

            # Check comparison_unit
            assert pack["comparison_unit"] in ALLOWED_COMPARISON_UNITS, (
                f"Row {p_id} pack[{p_idx}] comparison_unit '{pack['comparison_unit']}' not in allowed set"
            )

            # Check normalized_unit_price_bdt is numeric and positive
            norm_price = pack["normalized_unit_price_bdt"]
            assert norm_price is not None and isinstance(norm_price, (int, float)) and norm_price > 0, (
                f"Row {p_id} pack[{p_idx}] normalized_unit_price_bdt must be a positive number, got {norm_price}"
            )
