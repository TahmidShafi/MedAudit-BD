"""Ingest loader and schema validator for raw medicine dataset."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Set, Tuple

import pandas as pd

from medaudit.ingest.models import BrandEntity, ProductRecord, SchemaValidationError

# All 10 real columns discovered during Phase 0 spike
EXPECTED_COLUMNS: List[str] = [
    "brand id",
    "brand name",
    "type",
    "slug",
    "dosage form",
    "generic",
    "strength",
    "manufacturer",
    "package container",
    "Package Size",
]


def validate_schema(columns: List[str] | Set[str]) -> None:
    """Validate that columns contain exactly the expected 10 columns.
    
    Fails loudly if unexpected columns appear or any required columns are missing.
    """
    actual_set = set(columns)
    expected_set = set(EXPECTED_COLUMNS)

    missing = expected_set - actual_set
    unexpected = actual_set - expected_set

    errors = []
    if missing:
        errors.append(f"Missing required columns: {sorted(list(missing))}")
    if unexpected:
        errors.append(f"Unexpected columns found: {sorted(list(unexpected))}")

    if errors:
        raise SchemaValidationError(" ; ".join(errors))


def load_dataset_records(filepath_or_df: str | Path | pd.DataFrame) -> Tuple[List[ProductRecord], Dict[int, BrandEntity]]:
    """Load dataset, validate 10-column schema, and build domain models.
    
    Returns:
        Tuple of:
            - List of 21,714 ProductRecord domain models (with product_id = raw 'brand id')
            - Dict mapping brand_id -> BrandEntity (the 14,013 deduplicated brand entities)
    """
    if isinstance(filepath_or_df, (str, Path)):
        df = pd.read_csv(filepath_or_df)
    elif isinstance(filepath_or_df, pd.DataFrame):
        df = filepath_or_df.copy()
    else:
        raise TypeError(f"Expected filepath or DataFrame, got {type(filepath_or_df)}")

    # 1. Validate Schema
    validate_schema(df.columns)

    # 2. Build Deduplicated Brands
    # Each distinct (normalized_brand_name, manufacturer) is assigned a deterministic 1-based brand_id.
    # We sort by (normalized_brand_name, manufacturer) to ensure deterministic ID assignment.
    unique_pairs = (
        df[["brand name", "manufacturer"]]
        .drop_duplicates()
        .copy()
    )
    unique_pairs["normalized_brand_name"] = unique_pairs["brand name"].astype(str).str.strip()
    unique_pairs = unique_pairs.sort_values(by=["normalized_brand_name", "manufacturer"]).reset_index(drop=True)

    brand_lookup: Dict[Tuple[str, str], int] = {}
    brand_entities: Dict[int, BrandEntity] = {}

    for idx, row in unique_pairs.iterrows():
        b_id = idx + 1
        raw_b_name = str(row["brand name"])
        norm_b_name = str(row["normalized_brand_name"])
        mfg = str(row["manufacturer"])
        
        entity = BrandEntity(
            brand_id=b_id,
            brand_name=raw_b_name,
            normalized_brand_name=norm_b_name,
            manufacturer=mfg,
        )
        brand_entities[b_id] = entity
        brand_lookup[(norm_b_name, mfg)] = b_id

    # 3. Map Raw Rows to ProductRecord Domain Models
    products: List[ProductRecord] = []
    for _, row in df.iterrows():
        p_id = int(row["brand id"])
        raw_b_name = str(row["brand name"])
        norm_b_name = raw_b_name.strip()
        mfg = str(row["manufacturer"])
        assigned_brand_id = brand_lookup[(norm_b_name, mfg)]

        # Handle nulls cleanly
        raw_generic = str(row["generic"]).strip() if pd.notna(row["generic"]) and str(row["generic"]).strip() != "" and str(row["generic"]).lower() != "nan" else None
        raw_strength = str(row["strength"]).strip() if pd.notna(row["strength"]) and str(row["strength"]).strip() != "" and str(row["strength"]).lower() != "nan" else None
        raw_container = str(row["package container"]).strip() if pd.notna(row["package container"]) and str(row["package container"]).strip() != "" and str(row["package container"]).lower() != "nan" else None
        raw_pkg_size = str(row["Package Size"]).strip() if pd.notna(row["Package Size"]) and str(row["Package Size"]).strip() != "" and str(row["Package Size"]).lower() != "nan" else None

        prod = ProductRecord(
            product_id=p_id,
            brand_id=assigned_brand_id,
            raw_brand_name=raw_b_name,
            normalized_brand_name=norm_b_name,
            type=str(row["type"]).strip(),
            slug=str(row["slug"]).strip(),
            dosage_form=str(row["dosage form"]).strip(),
            raw_generic=raw_generic,
            raw_strength=raw_strength,
            manufacturer=mfg,
            raw_package_container=raw_container,
            raw_package_size=raw_pkg_size,
        )
        products.append(prod)

    return products, brand_entities


def analyze_duplicate_combinations(df_or_records: pd.DataFrame | List[ProductRecord]) -> Dict[str, any]:
    """Inspect and report what causes duplicate (brand name, strength, dosage form, manufacturer) rows."""
    if isinstance(df_or_records, list):
        data = [
            {
                "product_id": r.product_id,
                "brand_name": r.normalized_brand_name,
                "strength": r.raw_strength,
                "dosage_form": r.dosage_form,
                "manufacturer": r.manufacturer,
                "package_container": r.raw_package_container,
                "package_size": r.raw_package_size,
                "slug": r.slug,
            }
            for r in df_or_records
        ]
        df = pd.DataFrame(data)
    else:
        df = df_or_records.copy()
        if "brand id" in df.columns:
            df["product_id"] = df["brand id"]
        if "package container" in df.columns:
            df["package_container"] = df["package container"]
        if "Package Size" in df.columns:
            df["package_size"] = df["Package Size"]
        if "brand name" in df.columns:
            df["brand_name"] = df["brand name"]
        if "dosage form" in df.columns:
            df["dosage_form"] = df["dosage form"]

    total_rows = len(df)
    unique_groups = df.groupby(["brand_name", "strength", "dosage_form", "manufacturer"], dropna=False).ngroups
    duplicate_rows_count = total_rows - unique_groups

    dups = df[df.duplicated(subset=["brand_name", "strength", "dosage_form", "manufacturer"], keep=False)].copy()
    groups = []
    
    for (b, s, d, m), grp in dups.groupby(["brand_name", "strength", "dosage_form", "manufacturer"], dropna=False):
        skus = []
        for _, r in grp.iterrows():
            skus.append({
                "product_id": int(r["product_id"]),
                "slug": str(r.get("slug", "")),
                "package_container": r.get("package_container"),
                "package_size": r.get("package_size"),
            })
        groups.append({
            "key": {"brand_name": b, "strength": s, "dosage_form": d, "manufacturer": m},
            "sku_count": len(grp),
            "skus": skus,
        })

    return {
        "total_rows": total_rows,
        "unique_combinations": unique_groups,
        "duplicate_rows_count": duplicate_rows_count,
        "duplicate_group_count": len(groups),
        "duplicate_groups": groups,
    }
